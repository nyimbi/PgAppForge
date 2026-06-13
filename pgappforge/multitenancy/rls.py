"""
pgappforge/multitenancy/rls.py

PostgreSQL Row Level Security policy management.

Provides database-level tenant isolation: every table that carries a
``tenant_id`` column is locked down so that a PostgreSQL session can only
see rows whose ``tenant_id`` matches the session variable ``app.tenant_id``.

Design decisions
----------------
- Uses ``current_setting('app.tenant_id', true)`` (the ``true`` arg means
  it returns NULL rather than raising when the variable is unset, so
  unauthenticated sessions see zero rows — fail-safe).
- SYSTEM bypass: setting ``app.tenant_id`` to the literal string ``'SYSTEM'``
  grants superuser-style full visibility.  Guard this carefully.
- Infrastructure tables (``ab_*``, ``pgaf_*``, ``alembic_version``) are
  explicitly excluded from RLS because they hold platform data shared across
  all tenants.
- ``FORCE ROW LEVEL SECURITY`` is set so that the table owner (the app DB
  role) is also subject to the policy.

Usage
-----
::

    from pgappforge.multitenancy.rls import (
        enable_rls_all_tenant_tables,
        set_tenant_context,
        clear_tenant_context,
    )

    # Called once at startup (after all tables exist)
    n = enable_rls_all_tenant_tables(engine)

    # Called per-request (middleware handles this automatically)
    with session.begin():
        set_tenant_context(session, tenant_id="tenant-uuid-here")
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

# Tables that must NEVER be RLS-restricted (platform infrastructure)
RLS_EXCLUDE_TABLES: frozenset[str] = frozenset([
	# Citizen-dev metadata
	"pgaf_custom_field",
	# Audit / observability
	"pgaf_audit_log",
	"pgaf_ai_audit_log",
	"pgaf_deployment_log",
	# Agent memory
	"pgaf_agent_memory",
	# Workflow engine
	"pgaf_workflow_instance",
	"pgaf_workflow_task",
	# Multi-tenancy registry itself
	"pgaf_tenant",
	# FAB security tables
	"ab_user",
	"ab_role",
	"ab_permission",
	"ab_view_menu",
	"ab_permission_view_menu",
	"ab_user_role",
	"ab_user_permission_view",
	"ab_register_user",
	# Alembic
	"alembic_version",
])

# The session variable name used by all RLS policies
_TENANT_VAR = "app.tenant_id"
_SYSTEM_SENTINEL = "SYSTEM"


# ---------------------------------------------------------------------------
# Per-table helpers
# ---------------------------------------------------------------------------

def enable_rls_on_table(table_name: str, engine: Any) -> None:
	"""Enable RLS and create the tenant-isolation policy on *table_name*.

	Idempotent: ``DROP POLICY IF EXISTS`` before ``CREATE POLICY``.

	Raises on DDL error (caller should catch and log).
	"""
	policy_name = "pgaf_tenant_isolation"
	# Two-statement DDL must be separate executions (PostgreSQL parser rule)
	with engine.begin() as conn:
		conn.execute(sa.text(
			f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"
		))
		conn.execute(sa.text(
			f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"
		))
		conn.execute(sa.text(
			f"DROP POLICY IF EXISTS {policy_name} ON {table_name}"
		))
		conn.execute(sa.text(f"""
			CREATE POLICY {policy_name} ON {table_name}
				USING (
					tenant_id::text = current_setting('{_TENANT_VAR}', true)::text
					OR current_setting('{_TENANT_VAR}', true) = '{_SYSTEM_SENTINEL}'
				)
				WITH CHECK (
					tenant_id::text = current_setting('{_TENANT_VAR}', true)::text
					OR current_setting('{_TENANT_VAR}', true) = '{_SYSTEM_SENTINEL}'
				)
		"""))
	log.info("multitenancy: RLS enabled on %s", table_name)


def disable_rls_on_table(table_name: str, engine: Any) -> None:
	"""Remove the tenant isolation policy and disable RLS on *table_name*.

	Useful during schema migrations run as SYSTEM.
	"""
	with engine.begin() as conn:
		conn.execute(sa.text(
			f"DROP POLICY IF EXISTS pgaf_tenant_isolation ON {table_name}"
		))
		conn.execute(sa.text(
			f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY"
		))
	log.info("multitenancy: RLS disabled on %s", table_name)


# ---------------------------------------------------------------------------
# Bulk setup
# ---------------------------------------------------------------------------

def enable_rls_all_tenant_tables(engine: Any) -> int:
	"""Enable RLS on every public table that has a ``tenant_id`` column.

	Skips tables listed in :data:`RLS_EXCLUDE_TABLES`.

	Returns the number of tables successfully configured.
	"""
	with engine.connect() as conn:
		# Build the exclusion tuple dynamically — IN (:excluded) with a tuple
		# works for SQLAlchemy text() only via expanding bindparam
		rows = conn.execute(sa.text("""
			SELECT DISTINCT table_name
			FROM information_schema.columns
			WHERE column_name  = 'tenant_id'
			  AND table_schema = 'public'
			ORDER BY table_name
		""")).fetchall()

	count = 0
	for (table_name,) in rows:
		if table_name in RLS_EXCLUDE_TABLES:
			log.debug("multitenancy: skipping excluded table %s", table_name)
			continue
		try:
			enable_rls_on_table(table_name, engine)
			count += 1
		except Exception as exc:
			log.warning("multitenancy: RLS setup failed for %s: %s", table_name, exc)

	log.info("multitenancy: RLS enabled on %d table(s)", count)
	return count


def get_rls_status(engine: Any) -> list[dict]:
	"""Return RLS enablement status for all public tables.

	Each dict has keys: ``table_name``, ``rls_enabled``, ``force_rls``,
	``has_tenant_id``, ``policy_exists``.
	"""
	with engine.connect() as conn:
		rows = conn.execute(sa.text("""
			SELECT
				t.table_name,
				c.relrowsecurity		AS rls_enabled,
				c.relforcerowsecurity	AS force_rls,
				EXISTS (
					SELECT 1 FROM information_schema.columns ic
					WHERE ic.table_name   = t.table_name
					  AND ic.column_name  = 'tenant_id'
					  AND ic.table_schema = 'public'
				)							AS has_tenant_id,
				EXISTS (
					SELECT 1 FROM pg_policies pp
					WHERE pp.tablename  = t.table_name
					  AND pp.policyname = 'pgaf_tenant_isolation'
					  AND pp.schemaname = 'public'
				)							AS policy_exists
			FROM information_schema.tables t
			JOIN pg_class c ON c.relname = t.table_name
			WHERE t.table_schema = 'public'
			  AND t.table_type   = 'BASE TABLE'
			ORDER BY t.table_name
		""")).mappings().all()
	return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Per-request tenant context
# ---------------------------------------------------------------------------

def set_tenant_context(session_or_conn: Any, tenant_id: str) -> None:
	"""Set ``app.tenant_id`` for the current PostgreSQL session.

	Must be called at the start of each request **before** any SELECT/DML so
	that RLS policies see the correct tenant.

	The setting is transaction-local (``set_config(..., true)`` — the third
	arg ``is_local=true`` means it resets at transaction end).

	Parameters
	----------
	session_or_conn:
		SQLAlchemy :class:`~sqlalchemy.orm.Session` or
		:class:`~sqlalchemy.engine.Connection`.
	tenant_id:
		Tenant UUID string.  Pass ``'SYSTEM'`` for admin/migration bypass.
	"""
	if not tenant_id:
		return
	session_or_conn.execute(
		sa.text("SELECT set_config(:var, :val, true)"),
		{"var": _TENANT_VAR, "val": str(tenant_id)},
	)


def clear_tenant_context(session_or_conn: Any) -> None:
	"""Set tenant context to ``SYSTEM`` (bypasses all RLS policies).

	Use for background jobs and admin operations that must touch data across
	tenants.  Resets at transaction end (``is_local=true``).
	"""
	session_or_conn.execute(
		sa.text("SELECT set_config(:var, :val, true)"),
		{"var": _TENANT_VAR, "val": _SYSTEM_SENTINEL},
	)


def get_current_db_tenant(conn: Any) -> str | None:
	"""Read back the current ``app.tenant_id`` setting from PostgreSQL."""
	try:
		row = conn.execute(
			sa.text("SELECT current_setting(:var, true)", {"var": _TENANT_VAR})
		).scalar()
		return row or None
	except Exception:
		return None


__all__ = [
	"RLS_EXCLUDE_TABLES",
	"enable_rls_on_table",
	"disable_rls_on_table",
	"enable_rls_all_tenant_tables",
	"get_rls_status",
	"set_tenant_context",
	"clear_tenant_context",
	"get_current_db_tenant",
]
