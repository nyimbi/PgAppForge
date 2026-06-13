"""
pgappforge/audit.py

Platform-level audit logging system for PgAppForge.

Records every INSERT, UPDATE, and DELETE across all auditable SQLAlchemy
models into ``pgaf_audit_log``.

Compliance targets
------------------
- SOC 2 Type II  — CC7.2 / CC7.3 (change monitoring)
- ISO 27001      — A.12.4 (logging & monitoring)
- GDPR Art. 30   — records of processing activities
- CBK / SASRA    — Kenya regulator audit trail requirements

Design principles
-----------------
- **Immutable table**: no UPDATE or DELETE is ever issued against
  ``pgaf_audit_log`` by framework code.  Apply a PostgreSQL row-level
  security policy or trigger at the DB level to enforce this in production.
- **Non-fatal**: audit failures never break the main transaction.  Errors
  are logged at WARNING level and swallowed.
- **Lightweight**: the ``after_flush`` hook runs in the same transaction as
  the flushed objects, so no extra round-trip is needed.
- **Structured**: ``before_json`` / ``after_json`` / ``changed_fields`` give
  forensic inspectors everything they need without a separate diff tool.

Usage
-----
::

    # In your app factory, after all models are imported:
    from pgappforge.audit import setup_audit_listeners, create_audit_table

    create_audit_table(engine)          # idempotent — safe to call every boot
    setup_audit_listeners()             # wires global SQLAlchemy Session hooks

    # Mark a model as auditable:
    from pgappforge.audit import AuditableMixin

    class Invoice(AuditableMixin, db.Model):
        __tablename__ = "fin_invoice"
        ...

    # Query the log:
    from pgappforge.audit import query_audit
    rows = query_audit(table_name="fin_invoice", limit=50)
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, Index, String, Text, event
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def _uuid() -> str:
	"""Return a UUID7 string (time-sortable).

	Falls back to UUID4 when the ``uuid6`` package is not installed so that
	``pgappforge.audit`` can be imported in environments that have not yet
	run ``pip install uuid6`` (e.g. bare CI containers running only the
	test extras).  Production installs always have ``uuid6`` via
	``setup.py install_requires``.
	"""
	try:
		from uuid6 import uuid7
		return str(uuid7())
	except ImportError:
		import uuid as _uuid_mod
		return str(_uuid_mod.uuid4())


# ── Table definition (declarative-lite — no Base inheritance) ─────────────────
# We intentionally avoid inheriting from the app's Base so that this table can
# be created independently and never accidentally picked up by Alembic
# autogenerate for non-audit migrations.

class AuditLog:
	"""Platform-level audit log — records every INSERT, UPDATE, DELETE across
	all PgAppForge models.

	Immutable: no UPDATE or DELETE policies on this table.
	Queryable: indexed by table, record, user, and timestamp.
	Compliant: satisfies SOC2, CBK, SASRA, ISO 27001, GDPR Art. 30 requirements.

	This class is used solely for documentation and schema reference.
	The actual table is created via :func:`create_audit_table`.
	"""

	__tablename__ = "pgaf_audit_log"
	__table_args__ = (
		Index("ix_pgaf_audit_table_record", "table_name", "record_id"),
		Index("ix_pgaf_audit_user", "user_id", "created_at"),
		Index("ix_pgaf_audit_time", "created_at"),
		Index("ix_pgaf_audit_operation", "operation"),
		{"extend_existing": True},
	)

	id             = Column(String(36), primary_key=True, default=_uuid)
	table_name     = Column(String(100), nullable=False)
	record_id      = Column(String(100), nullable=False)   # PK of the affected row
	operation      = Column(String(10),  nullable=False)   # INSERT | UPDATE | DELETE
	user_id        = Column(String(36),  nullable=True)    # None for system operations
	user_email     = Column(String(255), nullable=True)
	before_json    = Column(JSONB,       nullable=True)    # state before the change
	after_json     = Column(JSONB,       nullable=True)    # state after the change
	changed_fields = Column(JSONB,       nullable=True)    # list of field names that changed
	created_at     = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	ip_address  = Column(INET,        nullable=True)
	session_id  = Column(String(100), nullable=True)
	request_id  = Column(String(36),  nullable=True)   # correlation with web request
	module      = Column(String(100), nullable=True)   # e.g. "hcm.payroll", "finance.gl"


# ── Model base mixin ──────────────────────────────────────────────────────────

class AuditableMixin:
	"""Add to any SQLAlchemy model to mark it as auditable.

	Models with this mixin will have all INSERT/UPDATE/DELETE operations
	recorded in ``pgaf_audit_log`` automatically by the session flush hook
	registered via :func:`setup_audit_listeners`.

	Usage::

		class Invoice(AuditableMixin, db.Model):
			__tablename__ = "fin_invoice"
			...

	Class attributes
	----------------
	__audit_exclude_fields__
		``frozenset`` of field names to suppress from change tracking.
		Defaults to ``{"updated_at", "changed_on"}`` — high-frequency
		timestamp fields that would generate noise without signal.
		Override per-model as needed::

			class Order(AuditableMixin, db.Model):
				__audit_exclude_fields__ = frozenset({"updated_at", "etag"})
	"""

	__audit_exclude_fields__: frozenset[str] = frozenset({"updated_at", "changed_on"})


# ── Skip list ─────────────────────────────────────────────────────────────────

_SKIP_TABLES: frozenset[str] = frozenset({
	"pgaf_audit_log",          # never audit the audit log itself
	"ab_user_session_cookie",  # high-volume, low-value session churn
	"alembic_version",         # migration metadata — not business data
})


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _model_to_dict(obj: Any) -> dict:
	"""Serialize a SQLAlchemy model instance to a JSON-safe dict.

	Handles ``datetime`` → ISO 8601 string, passes ``dict``/``list`` through,
	and coerces everything else with ``str()``.  Returns an empty dict on any
	unexpected error rather than propagating.
	"""
	result: dict = {}
	try:
		for col in obj.__table__.columns:
			val = getattr(obj, col.name, None)
			if val is None:
				result[col.name] = None
			elif isinstance(val, datetime):
				result[col.name] = val.isoformat()
			elif isinstance(val, (dict, list)):
				result[col.name] = val
			else:
				try:
					result[col.name] = str(val)
				except Exception:
					result[col.name] = None
	except Exception as exc:
		log.debug("_model_to_dict failed for %s: %s", type(obj).__name__, exc)
	return result


# ── Flask context helpers — all safe outside a request context ────────────────

def _get_current_user_info() -> tuple[str | None, str | None]:
	"""Return ``(user_id, user_email)`` from Flask-Login current_user.

	Returns ``(None, None)`` when called outside a Flask request context or
	when no user is authenticated (e.g. background jobs, CLI commands).
	"""
	try:
		from flask_login import current_user
		if current_user and current_user.is_authenticated:
			uid = str(getattr(current_user, "id", "") or "")
			email = getattr(current_user, "email", None)
			return uid or None, email or None
	except Exception:
		pass
	return None, None


def _get_request_ip() -> str | None:
	"""Return client IP from current Flask request, safe outside request."""
	try:
		from flask import request
		return request.remote_addr
	except Exception:
		return None


def _get_request_id() -> str | None:
	"""Return correlation request_id from Flask ``g``, safe outside request."""
	try:
		from flask import g
		return getattr(g, "request_id", None)
	except Exception:
		return None


# ── Module inference ──────────────────────────────────────────────────────────

_TABLE_PREFIX_MAP: dict[str, str] = {
	"hcm_":   "hcm",
	"fin_":   "finance",
	"erp_":   "erp",
	"crm_":   "crm",
	"ops_":   "operations",
	"grc_":   "grc",
	"cb_":    "core_banking",
	"sc_":    "sacco",
	"ft_":    "fintech",
	"plat_":  "platform",
	"pm_":    "property_management",
	"re_":    "real_estate",
	"club_":  "clubs",
}


def _get_module_for_table(table_name: str) -> str | None:
	"""Infer the PgAppForge module from table name prefix."""
	for prefix, module in _TABLE_PREFIX_MAP.items():
		if table_name.startswith(prefix):
			return module
	return None


# ── Event listener setup ──────────────────────────────────────────────────────

def setup_audit_listeners(session_factory=None) -> None:
	"""Wire up SQLAlchemy event listeners for audit logging.

	Call **once** during app startup, after all models are imported.

	The listener attaches to ``after_flush`` on the given session class (or the
	global :class:`sqlalchemy.orm.Session` if none is provided).  It inserts
	audit rows in the same database transaction as the flushed objects, so
	either both commit or both roll back.

	Args:
		session_factory: Optional SQLAlchemy Session class or scoped-session
		                 factory.  If ``None``, listens on the global
		                 ``Session`` class (affects all sessions in the process).

	Example — Flask-SQLAlchemy::

		from pgappforge.audit import setup_audit_listeners
		setup_audit_listeners(db.session.__class__)

	Example — global (affects every SQLAlchemy session)::

		from pgappforge.audit import setup_audit_listeners
		setup_audit_listeners()
	"""
	target = session_factory or Session

	@event.listens_for(target, "after_flush")
	def _after_flush(session: Session, flush_context: Any) -> None:
		user_id, user_email = _get_current_user_info()
		ip      = _get_request_ip()
		req_id  = _get_request_id()

		try:
			audit_rows: list[dict] = []

			# ── INSERTs ───────────────────────────────────────────────────────
			for obj in session.new:
				if not hasattr(obj, "__tablename__"):
					continue
				if obj.__tablename__ in _SKIP_TABLES:
					continue
				audit_rows.append({
					"id":             _uuid(),
					"table_name":     obj.__tablename__,
					"record_id":      str(getattr(obj, "id", "") or ""),
					"operation":      "INSERT",
					"user_id":        user_id,
					"user_email":     user_email,
					"before_json":    None,
					"after_json":     _model_to_dict(obj),
					"changed_fields": None,
					"created_at":     datetime.now(timezone.utc),
					"ip_address":     ip,
					"request_id":     req_id,
					"module":         _get_module_for_table(obj.__tablename__),
				})

			# ── UPDATEs ───────────────────────────────────────────────────────
			for obj in session.dirty:
				if not hasattr(obj, "__tablename__"):
					continue
				if obj.__tablename__ in _SKIP_TABLES:
					continue

				exclude = getattr(obj.__class__, "__audit_exclude_fields__", frozenset())
				changed: list[str] = []
				try:
					from sqlalchemy.orm import attributes as _attrs
					insp = sa.inspect(obj)
					for attr in insp.attrs:
						history = attr.history
						if history.has_changes() and attr.key not in exclude:
							changed.append(attr.key)
				except Exception as exc:
					log.debug("Failed to inspect changed attrs for %s: %s", type(obj).__name__, exc)

				if not changed:
					continue

				audit_rows.append({
					"id":             _uuid(),
					"table_name":     obj.__tablename__,
					"record_id":      str(getattr(obj, "id", "") or ""),
					"operation":      "UPDATE",
					"user_id":        user_id,
					"user_email":     user_email,
					"before_json":    None,   # pre-flush state not available post-flush
					"after_json":     _model_to_dict(obj),
					"changed_fields": changed,
					"created_at":     datetime.now(timezone.utc),
					"ip_address":     ip,
					"request_id":     req_id,
					"module":         _get_module_for_table(obj.__tablename__),
				})

			# ── DELETEs ───────────────────────────────────────────────────────
			for obj in session.deleted:
				if not hasattr(obj, "__tablename__"):
					continue
				if obj.__tablename__ in _SKIP_TABLES:
					continue
				audit_rows.append({
					"id":             _uuid(),
					"table_name":     obj.__tablename__,
					"record_id":      str(getattr(obj, "id", "") or ""),
					"operation":      "DELETE",
					"user_id":        user_id,
					"user_email":     user_email,
					"before_json":    _model_to_dict(obj),
					"after_json":     None,
					"changed_fields": None,
					"created_at":     datetime.now(timezone.utc),
					"ip_address":     ip,
					"request_id":     req_id,
					"module":         _get_module_for_table(obj.__tablename__),
				})

			if not audit_rows:
				return

			session.execute(
				sa.text(
					"INSERT INTO pgaf_audit_log "
					"(id, table_name, record_id, operation, user_id, user_email, "
					"before_json, after_json, changed_fields, created_at, "
					"ip_address, request_id, module) "
					"VALUES (:id, :table_name, :record_id, :operation, :user_id, :user_email, "
					":before_json::jsonb, :after_json::jsonb, :changed_fields::jsonb, :created_at, "
					":ip_address, :request_id, :module)"
				),
				[
					{
						**r,
						"before_json":    json.dumps(r["before_json"])    if r["before_json"]    is not None else None,
						"after_json":     json.dumps(r["after_json"])     if r["after_json"]     is not None else None,
						"changed_fields": json.dumps(r["changed_fields"]) if r["changed_fields"] is not None else None,
					}
					for r in audit_rows
				],
			)

		except Exception as exc:
			log.warning("Audit logging failed (non-fatal): %s", exc)


# ── DDL helper ────────────────────────────────────────────────────────────────

def create_audit_table(engine) -> None:
	"""Create ``pgaf_audit_log`` table directly (for use without Alembic).

	Idempotent — safe to call on every application boot.  Uses
	``CREATE TABLE IF NOT EXISTS`` and ``CREATE INDEX IF NOT EXISTS`` so
	repeated invocations are zero-cost on an already-provisioned database.

	Args:
		engine: SQLAlchemy engine connected to the target PostgreSQL database.
	"""
	ddl = """
	CREATE TABLE IF NOT EXISTS pgaf_audit_log (
		id              VARCHAR(36)  PRIMARY KEY,
		table_name      VARCHAR(100) NOT NULL,
		record_id       VARCHAR(100) NOT NULL,
		operation       VARCHAR(10)  NOT NULL,
		user_id         VARCHAR(36),
		user_email      VARCHAR(255),
		before_json     JSONB,
		after_json      JSONB,
		changed_fields  JSONB,
		created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
		ip_address      INET,
		session_id      VARCHAR(100),
		request_id      VARCHAR(36),
		module          VARCHAR(100)
	);
	CREATE INDEX IF NOT EXISTS ix_pgaf_audit_table_record
		ON pgaf_audit_log(table_name, record_id);
	CREATE INDEX IF NOT EXISTS ix_pgaf_audit_user
		ON pgaf_audit_log(user_id, created_at DESC);
	CREATE INDEX IF NOT EXISTS ix_pgaf_audit_time
		ON pgaf_audit_log(created_at DESC);
	CREATE INDEX IF NOT EXISTS ix_pgaf_audit_operation
		ON pgaf_audit_log(operation)
	"""
	with engine.begin() as conn:
		for stmt in ddl.strip().split(";"):
			s = stmt.strip()
			if s:
				conn.execute(sa.text(s))


# ── Query helper ──────────────────────────────────────────────────────────────

def query_audit(
	table_name: str | None = None,
	record_id:  str | None = None,
	user_id:    str | None = None,
	limit:      int        = 100,
	session=None,
) -> list[dict]:
	"""Query audit log with optional filters.

	Args:
		table_name: Filter to a specific table (exact match).
		record_id:  Filter to a specific record PK (exact match).
		user_id:    Filter to a specific user UUID (exact match).
		limit:      Maximum rows to return (capped at 500 internally).
		session:    SQLAlchemy session to use.  If ``None``, attempts to obtain
		            one from ``current_app.appbuilder.get_session()``.

	Returns:
		List of dicts, one per audit row, ordered by ``created_at DESC``.
		Returns an empty list if the session cannot be resolved.
	"""
	if session is None:
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
		except Exception:
			return []

	effective_limit = min(int(limit), 500)
	conditions: list[str] = []
	params: dict = {"lim": effective_limit}

	if table_name:
		conditions.append("table_name = :table_name")
		params["table_name"] = table_name
	if record_id:
		conditions.append("record_id = :record_id")
		params["record_id"] = record_id
	if user_id:
		conditions.append("user_id = :user_id")
		params["user_id"] = user_id

	where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
	rows = session.execute(
		sa.text(
			f"SELECT * FROM pgaf_audit_log {where} "
			"ORDER BY created_at DESC LIMIT :lim"
		),
		params,
	).fetchall()
	return [dict(r._mapping) for r in rows]


__all__ = [
	"AuditLog",
	"AuditableMixin",
	"setup_audit_listeners",
	"create_audit_table",
	"query_audit",
]
