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
- No magic tenant string.  An earlier version treated ``app.tenant_id =
  'SYSTEM'`` as a bypass, which meant any code holding a session could
  disable every policy by writing one string.  Bypass is now a separate
  GUC (``app.bypass_rls``) that only
  :func:`pgappforge.set_bypass_rls` can turn on, and only for a role
  listed in ``app.bypass_rls_roles``.
- Infrastructure tables (``ab_*``, ``pgaf_*``, ``alembic_version``) are
  explicitly excluded from RLS because they hold platform data shared across
  all tenants.
- ``FORCE ROW LEVEL SECURITY`` is set so that the table owner (the app DB
  role) is also subject to the policy.

Cross-tenant escape hatch — batch jobs only
-------------------------------------------
``set_bypass_rls(conn, on=True)`` lifts RLS for the current transaction.
It exists for batch jobs, migrations and reporting that must span tenants.
Never call it from request handling: an RLS bypass in a request path is a
cross-tenant data leak, and the audit trail cannot distinguish it from an
attack.  Prefer iterating tenants and running under each tenant's scope.

Usage
-----
::

    from pgappforge.multitenancy.rls import (
        enable_rls_all_tenant_tables,
        set_tenant_context,
        set_bypass_rls,
    )

    # Called once at startup (after all tables exist)
    n = enable_rls_all_tenant_tables(engine)

    # Called per-request (middleware handles this automatically)
    with session.begin():
        set_tenant_context(session, tenant_id="tenant-uuid-here")

    # Batch job only:
    with session.begin():
        set_bypass_rls(session, on=True)
"""
from __future__ import annotations

import logging
import os
import re
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
# Explicit cross-tenant bypass switch — policies test this, never the tenant id.
_BYPASS_VAR = "app.bypass_rls"
# Comma-separated role names permitted to set the bypass switch.
_BYPASS_ROLES_VAR = "app.bypass_rls_roles"
# Database role that owns the SECURITY DEFINER bypass function.
DEFAULT_SYSTEM_ROLE = os.environ.get("PGAF_SYSTEM_ROLE", "pgappforge_system")

# Unquoted-identifier shape; anything else is rejected rather than interpolated.
_ROLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _check_role_name(role: str) -> str:
	"""Reject role names that would not survive identifier interpolation."""
	if not _ROLE_NAME_RE.match(role or ""):
		raise ValueError(f"Invalid PostgreSQL role name: {role!r}")
	return role


# ---------------------------------------------------------------------------
# Per-table helpers
# ---------------------------------------------------------------------------

def enable_rls_on_table(table_name: str, engine: Any) -> None:
	"""Enable RLS and create the tenant-isolation policy on *table_name*.

	Idempotent: ``DROP POLICY IF EXISTS`` before ``CREATE POLICY``.

	Raises on DDL error (caller should catch and log).
	"""
	_check_role_name(table_name)
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
					OR current_setting('{_BYPASS_VAR}', true) = 'on'
				)
				WITH CHECK (
					tenant_id::text = current_setting('{_TENANT_VAR}', true)::text
					OR current_setting('{_BYPASS_VAR}', true) = 'on'
				)
		"""))
	log.info("multitenancy: RLS enabled on %s", table_name)


def disable_rls_on_table(table_name: str, engine: Any) -> None:
	"""Remove the tenant isolation policy and disable RLS on *table_name*.

	Useful during schema migrations run under :func:`set_bypass_rls`.
	"""
	_check_role_name(table_name)
	with engine.begin() as conn:
		conn.execute(sa.text(
			f"DROP POLICY IF EXISTS pgaf_tenant_isolation ON {table_name}"
		))
		conn.execute(sa.text(
			f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY"
		))
	log.info("multitenancy: RLS disabled on %s", table_name)


# ---------------------------------------------------------------------------
# Bypass switch — batch jobs only, never a request path
# ---------------------------------------------------------------------------

_BYPASS_FUNCTION_DDL = """
CREATE OR REPLACE FUNCTION pgappforge.set_bypass_rls("on" boolean)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
	allowed text;
	wanted boolean;
BEGIN
	wanted := "on";
	allowed := current_setting('app.bypass_rls_roles', true);
	IF allowed IS NULL OR allowed = '' THEN
		RAISE EXCEPTION 'pgappforge: % is not configured for database %',
			'app.bypass_rls_roles', current_database()
			USING ERRCODE = '55000';
	END IF;
	IF session_user <> ALL (string_to_array(allowed, ',')) THEN
		RAISE EXCEPTION
			'pgappforge: role % is not permitted to bypass row-level security', session_user
			USING ERRCODE = '42501';
	END IF;
	PERFORM set_config('app.bypass_rls', CASE WHEN wanted THEN 'on' ELSE 'off' END, true);
END
$fn$;
"""


def init_bypass_rls(engine: Any, system_role: str | None = None) -> str:
	"""Create ``pgappforge.set_bypass_rls`` and publish the allowed role list.

	Idempotent — call it on every startup.  The role list lands in the
	``app.bypass_rls_roles`` GUC as a database-level default, so every future
	session sees the same allow-list without the application having to set it.

	Returns the role name that was published.
	"""
	role = _check_role_name(system_role or DEFAULT_SYSTEM_ROLE)
	with engine.begin() as conn:
		conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS pgappforge"))
		conn.execute(sa.text(_BYPASS_FUNCTION_DDL))
		database = conn.execute(sa.text("SELECT current_database()")).scalar()
		quoted_db = '"' + str(database).replace('"', '""') + '"'
		conn.execute(sa.text(
			f"ALTER DATABASE {quoted_db} SET {_BYPASS_ROLES_VAR} = '{role}'"
		))
		try:
			conn.execute(sa.text(
				f"ALTER ROLE {role} IN DATABASE {quoted_db} "
				f"SET {_BYPASS_ROLES_VAR} = '{role}'"
			))
		except Exception as exc:
			log.debug("multitenancy: ALTER ROLE for %s skipped: %s", role, exc)
	dispose = getattr(engine, "dispose", None)
	if callable(dispose):
		dispose()
	log.info("multitenancy: RLS bypass restricted to role %s", role)
	return role


def set_bypass_rls(session_or_conn: Any, on: bool = True) -> None:
	"""Lift row-level security for the current transaction.

	BATCH JOBS ONLY.  The switch is transaction-local and only roles listed in
	``app.bypass_rls_roles`` may set it; anyone else gets error 42501.  A
	bypass inside request handling is an unaudited cross-tenant read, so call
	this from workers, migrations and cross-tenant reports only.
	"""
	session_or_conn.execute(
		sa.text("SELECT pgappforge.set_bypass_rls(:on)"), {"on": bool(on)}
	)


def get_bypass_rls(conn: Any) -> bool:
	"""True when the bypass switch is currently on for this session."""
	try:
		row = conn.execute(
			sa.text("SELECT current_setting(:var, true)"), {"var": _BYPASS_VAR}
		).scalar()
		return row == "on"
	except Exception:
		return False


# ---------------------------------------------------------------------------
# Bulk setup
# ---------------------------------------------------------------------------

def enable_rls_all_tenant_tables(engine: Any) -> int:
	"""Enable RLS on every public table that has a ``tenant_id`` column.

	Skips tables listed in :data:`RLS_EXCLUDE_TABLES`.

	Returns the number of tables successfully configured.
	"""
	try:
		init_bypass_rls(engine)
	except Exception as exc:
		log.warning("multitenancy: bypass function init failed, policies will deny bypass: %s", exc)
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
		Tenant UUID string.  There is no bypass value here — a tenant id is
		always a tenant id; cross-tenant work goes through
		:func:`set_bypass_rls`.
	"""
	if not tenant_id:
		return
	session_or_conn.execute(
		sa.text("SELECT set_config(:var, :val, true)"),
		{"var": _TENANT_VAR, "val": str(tenant_id)},
	)


def clear_tenant_context(session_or_conn: Any) -> None:
	"""Drop the tenant scope for this transaction: policies match zero rows.

	Fails safe.  Also switches the bypass off so a stale ``on`` from earlier
	in the same transaction cannot survive.  Resets at transaction end
	(``is_local=true``).
	"""
	session_or_conn.execute(
		sa.text("SELECT set_config(:var, :val, true)"),
		{"var": _TENANT_VAR, "val": ""},
	)
	session_or_conn.execute(
		sa.text("SELECT set_config(:var, :val, true)"),
		{"var": _BYPASS_VAR, "val": "off"},
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
	"DEFAULT_SYSTEM_ROLE",
	"enable_rls_on_table",
	"disable_rls_on_table",
	"enable_rls_all_tenant_tables",
	"get_rls_status",
	"init_bypass_rls",
	"set_bypass_rls",
	"get_bypass_rls",
	"set_tenant_context",
	"clear_tenant_context",
	"get_current_db_tenant",
]
