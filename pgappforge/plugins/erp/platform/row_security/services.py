"""
pgappforge/plugins/erp/platform/row_security/services.py

RowSecurityService — stateless row-level security enforcement.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed
except inside get_user_scope() where Flask is used best-effort to resolve
FAB role names.

Design:
  - define_policy():       upsert policy, invalidate all tenant SecurityContexts, emit event
  - get_user_scope():      check cache → compute from policies → cache result
  - apply_scope_filters(): append WHERE clauses to any SQLAlchemy select() stmt
  - No restrictions means full access (no allowed_values → see all)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry
from pgappforge.plugins.erp.platform.query_guard import (
	QueryGuardError,
	validate_sql_identifier,
)

from .events import (
	RowSecurityPolicyCreatedEvent,
	RowSecurityPolicyUpdatedEvent,
	SecurityContextComputedEvent,
)
from .models import RowSecurityPolicy, SecurityContext

__all__ = [
	"InvalidRowSecurityPolicyError",
	"RowSecurityService",
	"RowSecurityServiceError",
]

log = logging.getLogger(__name__)


class RowSecurityServiceError(Exception):
	"""Base error for row-security service violations."""


class InvalidRowSecurityPolicyError(RowSecurityServiceError):
	"""Policy or computed scope contains unsafe values."""


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		_emit_event(event, session)
	except Exception:
		log.debug("Event emission skipped: %s", type(event).__name__, exc_info=True)


class RowSecurityService:
	"""Stateless service for row-level security policy management and enforcement."""

	# ------------------------------------------------------------------
	# define_policy
	# ------------------------------------------------------------------

	@BPMActionRegistry.register(
		"platform.row_security.define_policy",
		"Define row-level security policy for a role",
	)
	def define_policy(
		self,
		role_id: str,
		entity_type: str,
		scope_field: str,
		allowed_values: list[str],
		name: str,
		tenant_id: str,
		session: Any,
		*,
		description: str | None = None,
		is_active: bool = True,
	) -> RowSecurityPolicy:
		"""Create or update an RLS policy for a role+entity_type combination.

		If a policy with the same (tenant_id, role_id, entity_type, scope_field)
		already exists it is updated in-place; otherwise a new one is inserted.
		All SecurityContext rows for the tenant are invalidated on change.

		Returns the RowSecurityPolicy instance.
		"""
		allowed_values = self._normalize_allowed_values(allowed_values)
		role_id = self._require_non_empty(role_id, "role_id")
		entity_type = self._require_non_empty(entity_type, "entity_type")
		scope_field = self._validate_scope_field(scope_field)
		name = self._require_non_empty(name, "name")
		tenant_id = self._require_non_empty(tenant_id, "tenant_id")

		existing = session.execute(
			select(RowSecurityPolicy).where(
				RowSecurityPolicy.tenant_id == tenant_id,
				RowSecurityPolicy.role_id == role_id,
				RowSecurityPolicy.entity_type == entity_type,
				RowSecurityPolicy.scope_field == scope_field,
			)
		).scalar_one_or_none()

		if existing is not None:
			existing.name = name
			existing.allowed_values = list(allowed_values)
			existing.is_active = is_active
			if description is not None:
				existing.description = description
			policy = existing
			session.flush()

			# Invalidate all cached contexts for this tenant
			self._invalidate_contexts(tenant_id, session)

			_emit(
				RowSecurityPolicyUpdatedEvent(
					aggregate_id=policy.id,
					aggregate_type="RowSecurityPolicy",
					tenant_id=tenant_id,
					policy_id=policy.id,
					scope_field=scope_field,
					allowed_count=len(allowed_values),
				),
				session,
			)
			log.info(
				"define_policy: updated policy %r for role=%r entity=%r",
				policy.name,
				role_id,
				entity_type,
			)
		else:
			policy = RowSecurityPolicy(
				id=_uuid4(),
				tenant_id=tenant_id,
				name=name,
				entity_type=entity_type,
				scope_field=scope_field,
				allowed_values=list(allowed_values),
				role_id=role_id,
				is_active=is_active,
				description=description,
			)
			session.add(policy)
			session.flush()

			# Invalidate all cached contexts for this tenant
			self._invalidate_contexts(tenant_id, session)

			_emit(
				RowSecurityPolicyCreatedEvent(
					aggregate_id=policy.id,
					aggregate_type="RowSecurityPolicy",
					tenant_id=tenant_id,
					policy_id=policy.id,
					entity_type=entity_type,
				),
				session,
			)
			log.info(
				"define_policy: created policy %r for role=%r entity=%r",
				policy.name,
				role_id,
				entity_type,
			)

		return policy

	# ------------------------------------------------------------------
	# get_user_scope
	# ------------------------------------------------------------------

	def get_user_scope(
		self,
		user_id: str,
		entity_type: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, list[str]]:
		"""Return the effective scope for a user+entity_type.

		Checks cached SecurityContext first.  If absent or expired, computes
		from active RowSecurityPolicy rows by resolving the user's FAB roles
		(best-effort — requires Flask app context).

		Returns: {scope_field: [allowed_values]}
		Empty dict means no restrictions — user sees all rows.
		"""
		# Check cache
		ctx = session.execute(
			select(SecurityContext).where(
				SecurityContext.user_id == user_id,
				SecurityContext.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if ctx is not None and (ctx.expires_at is None or ctx.expires_at > _now()):
			return ctx.computed_scope.get(entity_type, {})

		# Resolve user roles from FAB (Flask context, best-effort)
		role_names: list[str] = []
		try:
			from flask import current_app
			user = current_app.sm.find_user(id=user_id)
			role_names = [r.name for r in user.roles] if user else []
		except Exception:
			log.debug("get_user_scope: could not resolve roles for user %r", user_id)

		# Load matching policies
		if role_names:
			policies = session.execute(
				select(RowSecurityPolicy).where(
					RowSecurityPolicy.tenant_id == tenant_id,
					RowSecurityPolicy.is_active == sa.true(),
					RowSecurityPolicy.entity_type.in_([entity_type, "ANY"]),
					RowSecurityPolicy.role_id.in_(role_names),
				)
			).scalars().all()
		else:
			policies = []

		# Merge: union allowed_values per scope_field across all matching policies
		scope: dict[str, list[str]] = {}
		for p in policies:
			scope.setdefault(p.scope_field, []).extend(p.allowed_values or [])

		# Deduplicate
		scope = {field: list(dict.fromkeys(vals)) for field, vals in scope.items()}

		# Compute full context for caching (all entity types visible from policies)
		# We only have this entity_type's data; merge into existing cache if present
		full_scope: dict[str, dict[str, list[str]]] = {}
		if ctx is not None:
			full_scope = dict(ctx.computed_scope or {})
		full_scope[entity_type] = scope

		if ctx is None:
			ctx = SecurityContext(
				id=_uuid4(),
				tenant_id=tenant_id,
				user_id=user_id,
				computed_scope=full_scope,
				computed_at=_now(),
				expires_at=None,
			)
			session.add(ctx)
		else:
			ctx.computed_scope = full_scope
			ctx.computed_at = _now()

		session.flush()

		_emit(
			SecurityContextComputedEvent(
				aggregate_id=user_id,
				aggregate_type="SecurityContext",
				tenant_id=tenant_id,
				user_id=user_id,
				entity_types=list(full_scope.keys()),
			),
			session,
		)

		return scope

	# ------------------------------------------------------------------
	# apply_scope_filters
	# ------------------------------------------------------------------

	def apply_scope_filters(
		self,
		stmt: Any,
		entity_type: str,
		user_id: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Append RLS WHERE clauses to a SQLAlchemy select() statement.

		Usage::

		    stmt = select(Employee).where(...)
		    stmt = rls.apply_scope_filters(stmt, "EMPLOYEE", user_id, tenant_id, session)
		    rows = session.execute(stmt).scalars().all()

		An empty scope means no restrictions — the statement is returned unmodified.
		Each scope_field is treated as a literal column name; callers must ensure the
		queried model exposes that column.
		"""
		scope = self.get_user_scope(user_id, entity_type, tenant_id, session)
		if not scope:
			# No RLS policies → unrestricted access
			return stmt

		for field, allowed_values in scope.items():
			safe_field = self._validate_scope_field(field)
			safe_values = self._normalize_allowed_values(allowed_values)
			if safe_values:
				stmt = stmt.where(sa.literal_column(safe_field).in_(safe_values))
			# empty allowed_values means "deny all" — add impossible condition
			else:
				stmt = stmt.where(sa.false())

		return stmt

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _invalidate_contexts(self, tenant_id: str, session: Any) -> None:
		"""Delete all cached SecurityContext rows for a tenant."""
		session.execute(
			sa.delete(SecurityContext).where(SecurityContext.tenant_id == tenant_id)
		)
		log.debug("_invalidate_contexts: cleared SecurityContext cache for tenant %r", tenant_id)

	@staticmethod
	def _require_non_empty(value: Any, field_name: str) -> str:
		text = str(value or "").strip()
		if not text:
			raise InvalidRowSecurityPolicyError(f"{field_name} is required")
		return text

	@staticmethod
	def _validate_scope_field(scope_field: str) -> str:
		try:
			return validate_sql_identifier(scope_field, label="row-security scope")
		except QueryGuardError as exc:
			raise InvalidRowSecurityPolicyError(str(exc)) from exc

	@staticmethod
	def _normalize_allowed_values(values: Any) -> list[str]:
		if values is None:
			return []
		if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple, set)):
			raise InvalidRowSecurityPolicyError(
				"allowed_values must be a list of scalar values"
			)
		normalized: list[str] = []
		for value in values:
			if value is None or isinstance(value, (dict, list, tuple, set)):
				raise InvalidRowSecurityPolicyError(
					"allowed_values must contain only scalar values"
				)
			text = str(value).strip()
			if not text:
				raise InvalidRowSecurityPolicyError(
					"allowed_values cannot contain blank values"
				)
			normalized.append(text)
		return normalized
