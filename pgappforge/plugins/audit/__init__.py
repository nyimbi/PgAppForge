"""Audit Trail & Compliance Engine for pgappforge.

AuditMixin: attach to any SQLAlchemy Model to enable automatic audit logging.

Usage:
	class Patient(AuditMixin, Model):
		__tablename__ = "patients"
		__audit_pii_fields__ = frozenset({"date_of_birth", "ssn", "phone"})
"""
from __future__ import annotations
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, ClassVar

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

__all__ = ["AuditMixin", "AuditPlugin"]


class AuditMixin:
	"""Attach to any SQLAlchemy Model to enable automatic audit logging.

	Uses SessionEvents (after_flush + after_commit) rather than mapper events
	to avoid the illegal-session-access-during-flush problem.

	Fields:
		__audit_exclude_fields__: columns never included in diffs (e.g. "updated_at")
		__audit_pii_fields__: columns hashed before storage (GDPR compliance)
	"""

	__audit_exclude_fields__: ClassVar[frozenset] = frozenset(
		{"created_on", "changed_on", "created_at", "updated_at", "row_hash"}
	)
	__audit_pii_fields__: ClassVar[frozenset] = frozenset()

	def __init_subclass__(cls, **kwargs: object) -> None:
		super().__init_subclass__(**kwargs)
		_register_audit_listeners(cls)

	@classmethod
	def anonymize(cls, session: Session, entity_id: Any) -> int:
		"""GDPR right-to-erasure: replace PII field values in audit log.

		Replaces actual values with [REDACTED-sha256(value)] in all audit
		rows for this entity, preserving the diff structure for audit purposes.

		Returns: number of audit rows anonymized.
		"""
		from pgappforge.plugins.audit.models import AuditLog
		import sqlalchemy as sa
		rows = session.execute(
			sa.select(AuditLog)
			.where(AuditLog.model_name == cls.__name__)
			.where(AuditLog.entity_id == str(entity_id))
		).scalars().all()

		pii_fields = getattr(cls, "__audit_pii_fields__", frozenset())
		count = 0
		for row in rows:
			diffs = dict(row.field_diffs or {})
			changed = False
			for field in pii_fields:
				if field in diffs:
					for side in ("before", "after"):
						if diffs[field].get(side) is not None:
							val = str(diffs[field][side])
							diffs[field][side] = (
								f"[REDACTED-{hashlib.sha256(val.encode()).hexdigest()[:16]}]"
							)
							changed = True
			if changed:
				row.field_diffs = diffs
				count += 1
		if count:
			session.flush()
		return count


def _compute_hash(field_diffs: dict, prev_hash: str | None) -> str:
	payload = json.dumps(field_diffs, sort_keys=True, default=str) + (prev_hash or "")
	return hashlib.sha256(payload.encode()).hexdigest()


def _get_field_diffs(
	instance: Any,
	operation: str,
	pii_fields: frozenset,
	exclude_fields: frozenset,
) -> dict:
	"""Extract field-level diffs from SQLAlchemy instance inspection."""
	from sqlalchemy import inspect as sa_inspect
	try:
		state = sa_inspect(instance)
	except Exception:
		return {}
	diffs: dict = {}
	for attr in state.attrs:
		col_name = attr.key
		if col_name in exclude_fields:
			continue
		history = attr.history
		if not history.has_changes():
			continue
		before = history.deleted[0] if history.deleted else None
		after = history.added[0] if history.added else None
		if operation == "INSERT":
			before = None
		if operation == "DELETE":
			after = None
		if before == after:
			continue
		# Mask PII fields
		if col_name in pii_fields:
			if before is not None:
				before = f"[REDACTED-{hashlib.sha256(str(before).encode()).hexdigest()[:16]}]"
			if after is not None:
				after = f"[REDACTED-{hashlib.sha256(str(after).encode()).hexdigest()[:16]}]"
		diffs[col_name] = {"before": before, "after": after}
	return diffs


# session_id -> list[dict]; staging dict for pending audit rows between
# after_flush and after_commit
_PENDING_AUDIT_ROWS: dict[int, list[dict]] = {}


def _register_audit_listeners(model_cls: type) -> None:
	"""Mark a model class as audit-enabled. Session listeners are global."""
	if not hasattr(model_cls, "_pgaf_audit_enabled"):
		model_cls._pgaf_audit_enabled = True


def setup_audit_session_events() -> None:
	"""Call once at app startup to wire the global session event listeners."""
	from sqlalchemy.orm import Session as SASession

	@sa_event.listens_for(SASession, "after_flush")
	def _after_flush(session, flush_context):
		pending = []
		for instance in list(session.new) + list(session.dirty) + list(session.deleted):
			cls = type(instance)
			if not getattr(cls, "_pgaf_audit_enabled", False):
				continue
			op = (
				"INSERT" if instance in session.new
				else "DELETE" if instance in session.deleted
				else "UPDATE"
			)
			exclude = getattr(cls, "__audit_exclude_fields__", frozenset())
			pii = getattr(cls, "__audit_pii_fields__", frozenset())
			diffs = _get_field_diffs(instance, op, pii, exclude)
			if not diffs and op == "UPDATE":
				continue
			entity_id = str(getattr(instance, "id", None) or "")
			pending.append({
				"model_name": cls.__name__,
				"entity_id": entity_id,
				"operation": op,
				"field_diffs": diffs,
				"_instance": instance,
			})
		if pending:
			_PENDING_AUDIT_ROWS.setdefault(id(session), []).extend(pending)

	@sa_event.listens_for(SASession, "after_commit")
	def _after_commit(session):
		sid = id(session)
		pending = _PENDING_AUDIT_ROWS.pop(sid, [])
		if not pending:
			return
		_write_audit_rows(pending)

	@sa_event.listens_for(SASession, "after_rollback")
	def _after_rollback(session):
		_PENDING_AUDIT_ROWS.pop(id(session), None)


def _write_audit_rows(pending: list[dict]) -> None:
	"""Write collected audit rows using a fresh session to survive rollback."""
	try:
		from flask import current_app
		from pgappforge.plugins.audit.models import AuditLog
		import sqlalchemy as sa
		from sqlalchemy.orm import Session as SASession

		engine = current_app.extensions["sqlalchemy"].engine
		with SASession(engine) as audit_session:
			for row_data in pending:
				# Get most recent hash for this entity (for chain integrity)
				prev = audit_session.execute(
					sa.select(AuditLog.row_hash)
					.where(AuditLog.model_name == row_data["model_name"])
					.where(AuditLog.entity_id == row_data["entity_id"])
					.order_by(sa.desc(AuditLog.created_at))
					.limit(1)
				).scalar()
				row_hash = _compute_hash(row_data["field_diffs"], prev)

				# Resolve actor from Flask-Login
				try:
					from flask_login import current_user as cu
					actor_id = (
						getattr(cu, "id", None)
						if cu and cu.is_authenticated
						else None
					)
				except Exception:
					actor_id = None

				# Actor-pattern enrichment: read actor_role from instance if present
				actor_role = None
				inst = row_data.get("_instance")
				if inst is not None and hasattr(inst, "actor_role"):
					try:
						actor_role = inst.actor_role
					except Exception:
						pass

				# Capture request context metadata when available
				ip_address = None
				user_agent = None
				try:
					from flask import request as flask_request
					ip_address = flask_request.remote_addr
					user_agent = flask_request.headers.get("User-Agent", "")[:512]
				except Exception:
					pass

				audit_session.add(AuditLog(
					model_name=row_data["model_name"],
					entity_id=row_data["entity_id"],
					operation=row_data["operation"],
					actor_id=actor_id,
					actor_role=actor_role,
					field_diffs=row_data["field_diffs"],
					row_hash=row_hash,
					prev_hash=prev,
					ip_address=ip_address,
					user_agent=user_agent,
				))
			audit_session.commit()
	except Exception as exc:
		log.error("Failed to write audit rows: %s", exc)


class AuditPlugin:
	"""AuditPlugin — register at app startup."""
	name = "audit"

	def initialize(self, app, appbuilder) -> None:
		setup_audit_session_events()
		log.info("AuditPlugin initialized")

	def register_views(self, appbuilder) -> None:
		from pgappforge.plugins.audit.views import AuditLogView
		appbuilder.add_view(
			AuditLogView,
			"Audit Log",
			icon="fa-history",
			category="Compliance",
		)
