"""
pgappforge/views/erd_object_manager.py

DatabaseObjectManager — manages PostgreSQL database objects beyond tables:
  Domains, Event Triggers, Views, Materialized Views, RLS Policies.

Companion to TriggerProcedureManager in erd_schema_manager.py.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)


# ─── Object Templates ─────────────────────────────────────────────────────────
# Each template has: type, icon, category, label, description, sql, params, defaults

OBJECT_TEMPLATES: dict[str, dict] = {

    # ── Domains ───────────────────────────────────────────────────────────────

    "domain_email": {
        "type": "domain", "icon": "fa-at", "category": "validation",
        "label": "Email address domain",
        "description": "TEXT domain with RFC-5322 email pattern CHECK constraint.",
        "sql": (
            "CREATE DOMAIN {schema}.{name} AS TEXT\n"
            "    CONSTRAINT {name}_email_check\n"
            "    CHECK (VALUE IS NULL OR VALUE ~* '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$');"
        ),
        "params": ["name", "schema"],
        "defaults": {"name": "email_address", "schema": "public"},
    },
    "domain_positive_int": {
        "type": "domain", "icon": "fa-hashtag", "category": "validation",
        "label": "Positive integer domain",
        "description": "INTEGER domain constrained to be strictly > 0.",
        "sql": (
            "CREATE DOMAIN {schema}.{name} AS INTEGER\n"
            "    CONSTRAINT {name}_positive CHECK (VALUE > 0);"
        ),
        "params": ["name", "schema"],
        "defaults": {"name": "positive_int", "schema": "public"},
    },
    "domain_money": {
        "type": "domain", "icon": "fa-dollar-sign", "category": "finance",
        "label": "Non-negative money domain",
        "description": "NUMERIC(18,4) domain for monetary values (must be >= 0).",
        "sql": (
            "CREATE DOMAIN {schema}.{name} AS NUMERIC(18, 4)\n"
            "    CONSTRAINT {name}_non_negative CHECK (VALUE >= 0);"
        ),
        "params": ["name", "schema"],
        "defaults": {"name": "money_amount", "schema": "public"},
    },
    "domain_phone": {
        "type": "domain", "icon": "fa-phone", "category": "validation",
        "label": "International phone number domain",
        "description": "VARCHAR(20) accepting E.164-style phone numbers (+1234567890).",
        "sql": (
            "CREATE DOMAIN {schema}.{name} AS VARCHAR(20)\n"
            "    CONSTRAINT {name}_phone_check\n"
            "    CHECK (VALUE IS NULL OR VALUE ~ '^\\+?[0-9]{7,15}$');"
        ),
        "params": ["name", "schema"],
        "defaults": {"name": "phone_number", "schema": "public"},
    },
    "domain_percentage": {
        "type": "domain", "icon": "fa-percent", "category": "validation",
        "label": "Percentage domain (0–100)",
        "description": "NUMERIC(5,2) constrained to the 0–100 range.",
        "sql": (
            "CREATE DOMAIN {schema}.{name} AS NUMERIC(5, 2)\n"
            "    CONSTRAINT {name}_range CHECK (VALUE >= 0 AND VALUE <= 100);"
        ),
        "params": ["name", "schema"],
        "defaults": {"name": "percentage", "schema": "public"},
    },
    "domain_uuid": {
        "type": "domain", "icon": "fa-fingerprint", "category": "identity",
        "label": "UUID domain with auto-default",
        "description": "UUID domain that defaults to gen_random_uuid() on INSERT.",
        "sql": (
            "CREATE DOMAIN {schema}.{name} AS UUID\n"
            "    DEFAULT gen_random_uuid();"
        ),
        "params": ["name", "schema"],
        "defaults": {"name": "auto_uuid", "schema": "public"},
    },
    "domain_status": {
        "type": "domain", "icon": "fa-toggle-on", "category": "workflow",
        "label": "Status domain (enumerated TEXT)",
        "description": "TEXT domain constrained to a comma-separated list of allowed values.",
        "sql": (
            "CREATE DOMAIN {schema}.{name} AS TEXT\n"
            "    CONSTRAINT {name}_values\n"
            "    CHECK (VALUE IN ({allowed_values}));"
        ),
        "params": ["name", "schema", "allowed_values"],
        "defaults": {"name": "order_status", "schema": "public",
                     "allowed_values": "'draft','active','closed'"},
    },

    # ── Event Triggers ────────────────────────────────────────────────────────

    "event_trigger_log_ddl": {
        "type": "event_trigger", "icon": "fa-database", "category": "audit",
        "label": "Log all DDL changes",
        "description": "Records every DDL command (tag, object type/identity, user, timestamp) to ddl_audit_log.",
        "sql": (
            "CREATE TABLE IF NOT EXISTS ddl_audit_log (\n"
            "    id          BIGSERIAL PRIMARY KEY,\n"
            "    command_tag TEXT NOT NULL,\n"
            "    object_type TEXT,\n"
            "    object_name TEXT,\n"
            "    executed_by TEXT DEFAULT current_user,\n"
            "    executed_at TIMESTAMPTZ DEFAULT NOW()\n"
            ");\n\n"
            "CREATE OR REPLACE FUNCTION public.log_ddl_changes()\n"
            "RETURNS event_trigger LANGUAGE plpgsql AS $$\n"
            "DECLARE obj RECORD;\n"
            "BEGIN\n"
            "    FOR obj IN SELECT * FROM pg_event_trigger_ddl_commands() LOOP\n"
            "        INSERT INTO ddl_audit_log(command_tag, object_type, object_name)\n"
            "        VALUES (TG_TAG, obj.object_type, obj.object_identity);\n"
            "    END LOOP;\n"
            "END;\n"
            "$$;\n\n"
            "CREATE EVENT TRIGGER {name}\n"
            "ON ddl_command_end\n"
            "EXECUTE FUNCTION public.log_ddl_changes();"
        ),
        "params": ["name"],
        "defaults": {"name": "trg_log_ddl"},
    },
    "event_trigger_prevent_drop": {
        "type": "event_trigger", "icon": "fa-shield-halved", "category": "security",
        "label": "Prevent DROP on protected tables",
        "description": "Blocks DROP TABLE on tables listed in app.protected_tables session setting.",
        "sql": (
            "CREATE OR REPLACE FUNCTION public.prevent_drop_tables()\n"
            "RETURNS event_trigger LANGUAGE plpgsql AS $$\n"
            "DECLARE\n"
            "    obj              RECORD;\n"
            "    protected_tables TEXT[] := string_to_array(\n"
            "        current_setting('app.protected_tables', true), ',');\n"
            "BEGIN\n"
            "    FOR obj IN SELECT * FROM pg_event_trigger_dropped_objects()\n"
            "               WHERE object_type = 'table'\n"
            "    LOOP\n"
            "        IF obj.object_name = ANY(protected_tables) THEN\n"
            "            RAISE EXCEPTION 'DROP blocked: table is protected: %', obj.object_name;\n"
            "        END IF;\n"
            "    END LOOP;\n"
            "END;\n"
            "$$;\n\n"
            "CREATE EVENT TRIGGER {name}\n"
            "ON sql_drop\n"
            "EXECUTE FUNCTION public.prevent_drop_tables();"
        ),
        "params": ["name"],
        "defaults": {"name": "trg_prevent_drop"},
    },
    "event_trigger_notify_ddl": {
        "type": "event_trigger", "icon": "fa-bell", "category": "integration",
        "label": "Notify on DDL change (pg_notify)",
        "description": "Broadcasts a pg_notify message on every DDL event for external tooling.",
        "sql": (
            "CREATE OR REPLACE FUNCTION public.notify_ddl_change()\n"
            "RETURNS event_trigger LANGUAGE plpgsql AS $$\n"
            "BEGIN\n"
            "    PERFORM pg_notify('{channel}',\n"
            "        json_build_object('tag', TG_TAG, 'user', current_user,\n"
            "                          'at', now())::text);\n"
            "END;\n"
            "$$;\n\n"
            "CREATE EVENT TRIGGER {name}\n"
            "ON ddl_command_end\n"
            "EXECUTE FUNCTION public.notify_ddl_change();"
        ),
        "params": ["name", "channel"],
        "defaults": {"name": "trg_notify_ddl", "channel": "pgaf_ddl"},
    },

    # ── Materialized Views ────────────────────────────────────────────────────

    "matview_aggregate_summary": {
        "type": "materialized_view", "icon": "fa-chart-pie", "category": "analytics",
        "label": "Aggregate summary",
        "description": "Precomputed GROUP BY aggregation (count, sum, avg, min, max) with unique index.",
        "sql": (
            "CREATE MATERIALIZED VIEW IF NOT EXISTS {schema}.{name} AS\n"
            "SELECT\n"
            "    {group_col},\n"
            "    COUNT(*)         AS row_count,\n"
            "    SUM({value_col}) AS total,\n"
            "    AVG({value_col}) AS average,\n"
            "    MIN({value_col}) AS minimum,\n"
            "    MAX({value_col}) AS maximum\n"
            "FROM {source_table}\n"
            "GROUP BY {group_col}\n"
            "WITH DATA;\n\n"
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_{name}_{group_col}\n"
            "    ON {schema}.{name} ({group_col});"
        ),
        "params": ["name", "schema", "source_table", "group_col", "value_col"],
        "defaults": {"schema": "public", "name": "mv_summary",
                     "source_table": "orders", "group_col": "status", "value_col": "amount"},
    },
    "matview_daily_rollup": {
        "type": "materialized_view", "icon": "fa-chart-line", "category": "analytics",
        "label": "Daily time-series rollup",
        "description": "Aggregates a fact table by day using DATE_TRUNC for the last N days.",
        "sql": (
            "CREATE MATERIALIZED VIEW IF NOT EXISTS {schema}.{name} AS\n"
            "SELECT\n"
            "    DATE_TRUNC('day', {time_col})::date AS day,\n"
            "    COUNT(*)                             AS events,\n"
            "    SUM({value_col})                     AS total,\n"
            "    AVG({value_col})                     AS avg_value\n"
            "FROM {source_table}\n"
            "WHERE {time_col} >= NOW() - INTERVAL '{lookback_days} days'\n"
            "GROUP BY 1\n"
            "ORDER BY 1 DESC\n"
            "WITH DATA;\n\n"
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_{name}_day ON {schema}.{name} (day);"
        ),
        "params": ["name", "schema", "source_table", "time_col", "value_col", "lookback_days"],
        "defaults": {"schema": "public", "name": "mv_daily",
                     "source_table": "events", "time_col": "created_at",
                     "value_col": "amount", "lookback_days": "90"},
    },
    "matview_latest_per_group": {
        "type": "materialized_view", "icon": "fa-layer-group", "category": "analytics",
        "label": "Latest row per group (DISTINCT ON)",
        "description": "Keeps only the most recent row per group using DISTINCT ON.",
        "sql": (
            "CREATE MATERIALIZED VIEW IF NOT EXISTS {schema}.{name} AS\n"
            "SELECT DISTINCT ON ({group_col}) *\n"
            "FROM {source_table}\n"
            "ORDER BY {group_col}, {order_col} DESC\n"
            "WITH DATA;\n\n"
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_{name}_{group_col}\n"
            "    ON {schema}.{name} ({group_col});"
        ),
        "params": ["name", "schema", "source_table", "group_col", "order_col"],
        "defaults": {"schema": "public", "name": "mv_latest",
                     "source_table": "events", "group_col": "user_id", "order_col": "created_at"},
    },
    "matview_cross_join_report": {
        "type": "materialized_view", "icon": "fa-table", "category": "reporting",
        "label": "Denormalised report (JOIN two tables)",
        "description": "Caches a JOIN of two tables for fast reporting without live query cost.",
        "sql": (
            "CREATE MATERIALIZED VIEW IF NOT EXISTS {schema}.{name} AS\n"
            "SELECT\n"
            "    a.*,\n"
            "    b.{b_col} AS {b_alias}\n"
            "FROM {table_a} a\n"
            "JOIN {table_b} b ON b.id = a.{fk_col}\n"
            "WITH DATA;\n\n"
            "CREATE INDEX IF NOT EXISTS ix_{name}_fk ON {schema}.{name} ({fk_col});"
        ),
        "params": ["name", "schema", "table_a", "table_b", "fk_col", "b_col", "b_alias"],
        "defaults": {"schema": "public", "name": "mv_orders_customers",
                     "table_a": "orders", "table_b": "customers",
                     "fk_col": "customer_id", "b_col": "name", "b_alias": "customer_name"},
    },

    # ── Views ─────────────────────────────────────────────────────────────────

    "view_active_records": {
        "type": "view", "icon": "fa-eye", "category": "soft-delete",
        "label": "Active records (soft-delete filter)",
        "description": "Excludes soft-deleted rows by filtering WHERE deleted_at IS NULL.",
        "sql": (
            "CREATE OR REPLACE VIEW {schema}.{name} AS\n"
            "SELECT * FROM {source_table}\n"
            "WHERE deleted_at IS NULL;"
        ),
        "params": ["name", "schema", "source_table"],
        "defaults": {"schema": "public", "name": "v_active_customers",
                     "source_table": "customers"},
    },
    "view_tenant_scoped": {
        "type": "view", "icon": "fa-building", "category": "multi-tenant",
        "label": "Tenant-scoped view",
        "description": "Filters rows to the current tenant via app.current_tenant_id session setting.",
        "sql": (
            "CREATE OR REPLACE VIEW {schema}.{name} AS\n"
            "SELECT * FROM {source_table}\n"
            "WHERE {tenant_col}::text =\n"
            "      current_setting('app.current_tenant_id', true);"
        ),
        "params": ["name", "schema", "source_table", "tenant_col"],
        "defaults": {"schema": "public", "name": "v_my_orders",
                     "source_table": "orders", "tenant_col": "tenant_id"},
    },
    "view_recent_records": {
        "type": "view", "icon": "fa-clock", "category": "convenience",
        "label": "Recent records (LIMIT N)",
        "description": "Shows the most recent N rows ordered by a timestamp column.",
        "sql": (
            "CREATE OR REPLACE VIEW {schema}.{name} AS\n"
            "SELECT * FROM {source_table}\n"
            "ORDER BY {order_col} DESC\n"
            "LIMIT {limit_rows};"
        ),
        "params": ["name", "schema", "source_table", "order_col", "limit_rows"],
        "defaults": {"schema": "public", "name": "v_recent_orders",
                     "source_table": "orders", "order_col": "created_at", "limit_rows": "100"},
    },
    "view_joined_report": {
        "type": "view", "icon": "fa-code-merge", "category": "reporting",
        "label": "Joined report view",
        "description": "Denormalised view that JOINs two tables for easy ad-hoc reporting.",
        "sql": (
            "CREATE OR REPLACE VIEW {schema}.{name} AS\n"
            "SELECT\n"
            "    a.*,\n"
            "    b.{b_col} AS {b_alias}\n"
            "FROM {table_a} a\n"
            "JOIN {table_b} b ON b.id = a.{fk_col};"
        ),
        "params": ["name", "schema", "table_a", "table_b", "fk_col", "b_col", "b_alias"],
        "defaults": {"schema": "public", "name": "v_orders_with_customer",
                     "table_a": "orders", "table_b": "customers",
                     "fk_col": "customer_id", "b_col": "name", "b_alias": "customer_name"},
    },
    "view_audit_readable": {
        "type": "view", "icon": "fa-clipboard-list", "category": "audit",
        "label": "Human-readable audit log view",
        "description": "Formats the audit_log JSONB columns for easy reading.",
        "sql": (
            "CREATE OR REPLACE VIEW {schema}.{name} AS\n"
            "SELECT\n"
            "    id,\n"
            "    table_name,\n"
            "    action,\n"
            "    changed_by,\n"
            "    changed_at,\n"
            "    old_data - 'password' - 'token' AS old_safe,\n"
            "    new_data - 'password' - 'token' AS new_safe\n"
            "FROM audit_log\n"
            "ORDER BY changed_at DESC;"
        ),
        "params": ["name", "schema"],
        "defaults": {"schema": "public", "name": "v_audit_readable"},
    },

    # ── Policies (RLS) ────────────────────────────────────────────────────────

    "policy_tenant_isolation": {
        "type": "policy", "icon": "fa-shield", "category": "multi-tenant",
        "label": "Multi-tenant row isolation",
        "description": "Users see and modify only rows matching their tenant_id session variable.",
        "sql": (
            "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n"
            "ALTER TABLE {table} FORCE ROW LEVEL SECURITY;\n\n"
            "DROP POLICY IF EXISTS {policy_name} ON {table};\n"
            "CREATE POLICY {policy_name} ON {table}\n"
            "    USING ({tenant_col}::text = current_setting('app.current_tenant_id', true));"
        ),
        "params": ["table", "policy_name", "tenant_col"],
        "defaults": {"policy_name": "tenant_isolation", "tenant_col": "tenant_id"},
    },
    "policy_owner_only": {
        "type": "policy", "icon": "fa-user-lock", "category": "ownership",
        "label": "Owner-only access",
        "description": "Users can only read/modify rows they created (owner_col = session user ID).",
        "sql": (
            "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n\n"
            "DROP POLICY IF EXISTS {policy_name} ON {table};\n"
            "CREATE POLICY {policy_name} ON {table}\n"
            "    USING ({owner_col}::text = current_setting('app.current_user_id', true));"
        ),
        "params": ["table", "policy_name", "owner_col"],
        "defaults": {"policy_name": "owner_only", "owner_col": "created_by"},
    },
    "policy_public_read": {
        "type": "policy", "icon": "fa-globe", "category": "public-data",
        "label": "Public read, authenticated write",
        "description": "Anyone can SELECT; only authenticated sessions can INSERT/UPDATE/DELETE.",
        "sql": (
            "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n\n"
            "DROP POLICY IF EXISTS {policy_name}_read ON {table};\n"
            "CREATE POLICY {policy_name}_read ON {table}\n"
            "    FOR SELECT USING (true);\n\n"
            "DROP POLICY IF EXISTS {policy_name}_write ON {table};\n"
            "CREATE POLICY {policy_name}_write ON {table}\n"
            "    FOR ALL USING (current_user IS NOT NULL);"
        ),
        "params": ["table", "policy_name"],
        "defaults": {"policy_name": "public_read"},
    },
    "policy_admin_bypass": {
        "type": "policy", "icon": "fa-user-shield", "category": "admin",
        "label": "Admin bypass + user filter",
        "description": "Admins see all rows; non-admins see only their own (owner_col = session user).",
        "sql": (
            "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n\n"
            "DROP POLICY IF EXISTS {policy_name} ON {table};\n"
            "CREATE POLICY {policy_name} ON {table}\n"
            "    USING (\n"
            "        pg_has_role(current_user, '{admin_role}', 'member')\n"
            "        OR {owner_col}::text = current_setting('app.current_user_id', true)\n"
            "    );"
        ),
        "params": ["table", "policy_name", "admin_role", "owner_col"],
        "defaults": {"policy_name": "admin_bypass", "admin_role": "app_admin", "owner_col": "created_by"},
    },
    "policy_time_locked": {
        "type": "policy", "icon": "fa-calendar-xmark", "category": "temporal",
        "label": "Read-only after expiry timestamp",
        "description": "Allows SELECT on all rows; blocks UPDATE/DELETE after an expiry column passes.",
        "sql": (
            "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n\n"
            "DROP POLICY IF EXISTS {policy_name}_select ON {table};\n"
            "CREATE POLICY {policy_name}_select ON {table}\n"
            "    FOR SELECT USING (true);\n\n"
            "DROP POLICY IF EXISTS {policy_name}_modify ON {table};\n"
            "CREATE POLICY {policy_name}_modify ON {table}\n"
            "    FOR ALL USING ({expiry_col} IS NULL OR {expiry_col} > NOW());"
        ),
        "params": ["table", "policy_name", "expiry_col"],
        "defaults": {"policy_name": "time_locked", "expiry_col": "locked_until"},
    },
    "policy_column_masked": {
        "type": "policy", "icon": "fa-eye-slash", "category": "security",
        "label": "Column masking for non-privileged users",
        "description": "Privileged role sees full rows; others see rows with sensitive column nulled.",
        "sql": (
            "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n\n"
            "DROP POLICY IF EXISTS {policy_name}_full ON {table};\n"
            "CREATE POLICY {policy_name}_full ON {table}\n"
            "    FOR SELECT\n"
            "    USING (pg_has_role(current_user, '{privileged_role}', 'member'));\n\n"
            "-- Create a masking view for unprivileged users:\n"
            "CREATE OR REPLACE VIEW {table}_masked AS\n"
            "SELECT *, NULL::text AS {sensitive_col}\n"
            "FROM {table};"
        ),
        "params": ["table", "policy_name", "privileged_role", "sensitive_col"],
        "defaults": {"policy_name": "column_masked", "privileged_role": "app_privileged",
                     "sensitive_col": "ssn"},
    },
}


# ─── DatabaseObjectManager ─────────────────────────────────────────────────────

class DatabaseObjectManager:
    """Creates and manages PostgreSQL objects: Domains, Event Triggers,
    Views, Materialized Views, and RLS Policies.

    Usage::

        mgr = DatabaseObjectManager(engine)
        # Apply a template
        mgr.apply_object_template('view_active_records', table='customers',
                                   name='v_active_customers', schema='public')
        # List views
        views = mgr.list_views(schema='public')
        # Refresh a mat view
        mgr.refresh_mat_view('mv_daily', schema='public')
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ── Template API ──────────────────────────────────────────────────────────

    def list_object_templates(self, object_type: str | None = None) -> list[dict]:
        """Return all object templates, optionally filtered by type."""
        return [
            {
                "key":         k,
                "type":        v.get("type", ""),
                "label":       v.get("label", ""),
                "description": v.get("description", ""),
                "icon":        v.get("icon", "fa-cube"),
                "category":    v.get("category", "general"),
                "params":      v.get("params", []),
                "defaults":    v.get("defaults", {}),
                "sql":         v.get("sql", ""),
            }
            for k, v in OBJECT_TEMPLATES.items()
            if object_type is None or v.get("type") == object_type
        ]

    def apply_object_template(self, template_key: str, **params) -> dict:
        """Render a template with ``params`` and execute all statements."""
        tmpl = OBJECT_TEMPLATES.get(template_key)
        if not tmpl:
            raise ValueError(f"Unknown object template: {template_key!r}")
        ctx = {**tmpl.get("defaults", {}), **params}
        sql = tmpl["sql"]
        for k, v in ctx.items():
            sql = sql.replace("{" + k + "}", str(v))
        # Split on bare ';' at end-of-statement boundaries
        stmts = [s.strip() for s in sql.split(";") if s.strip()]
        try:
            with self.engine.begin() as conn:
                for stmt in stmts:
                    conn.execute(text(stmt))
            return {"applied": len(stmts), "sql": stmts, "errors": []}
        except Exception as exc:
            log.error("DatabaseObjectManager.apply_object_template failed: %s", exc)
            return {"applied": 0, "sql": stmts, "errors": [str(exc)]}

    # ── Domains ───────────────────────────────────────────────────────────────

    def list_domains(self, schema: str = "public") -> list[dict]:
        q = """
            SELECT d.domain_name, d.data_type, d.character_maximum_length,
                   d.domain_default,
                   cc.check_clause
            FROM information_schema.domains d
            LEFT JOIN information_schema.domain_constraints dc
                ON dc.domain_name = d.domain_name AND dc.domain_schema = d.domain_schema
            LEFT JOIN information_schema.check_constraints cc
                ON cc.constraint_name = dc.constraint_name
            WHERE d.domain_schema = :schema
            ORDER BY d.domain_name
        """
        with self.engine.connect() as conn:
            rows = conn.execute(text(q), {"schema": schema}).fetchall()
        return [dict(r._mapping) for r in rows]

    def drop_domain(self, name: str, schema: str = "public",
                    cascade: bool = False) -> dict:
        from pgappforge.views.erd_schema_manager import _qi
        suffix = " CASCADE" if cascade else ""
        return self._run(f"DROP DOMAIN IF EXISTS {_qi(schema)}.{_qi(name)}{suffix}")

    # ── Event Triggers ────────────────────────────────────────────────────────

    def list_event_triggers(self) -> list[dict]:
        q = """
            SELECT evtname AS name, evtevent AS event,
                   evtowner::regrole::text AS owner,
                   evtenabled AS enabled,
                   evtfoid::regproc::text AS function_name
            FROM pg_event_trigger
            ORDER BY evtname
        """
        with self.engine.connect() as conn:
            rows = conn.execute(text(q)).fetchall()
        return [dict(r._mapping) for r in rows]

    def drop_event_trigger(self, name: str) -> dict:
        from pgappforge.views.erd_schema_manager import _qi
        return self._run(f"DROP EVENT TRIGGER IF EXISTS {_qi(name)}")

    def toggle_event_trigger(self, name: str, enable: bool) -> dict:
        from pgappforge.views.erd_schema_manager import _qi
        action = "ENABLE" if enable else "DISABLE"
        return self._run(f"ALTER EVENT TRIGGER {_qi(name)} {action}")

    # ── Views ─────────────────────────────────────────────────────────────────

    def list_views(self, schema: str = "public") -> list[dict]:
        q = """
            SELECT table_name AS view_name,
                   view_definition
            FROM information_schema.views
            WHERE table_schema = :schema
            ORDER BY table_name
        """
        with self.engine.connect() as conn:
            rows = conn.execute(text(q), {"schema": schema}).fetchall()
        return [dict(r._mapping) for r in rows]

    def list_mat_views(self, schema: str = "public") -> list[dict]:
        q = """
            SELECT matviewname AS view_name,
                   ispopulated,
                   pg_size_pretty(pg_total_relation_size(
                       (schemaname||'.'||matviewname)::regclass)) AS size
            FROM pg_matviews
            WHERE schemaname = :schema
            ORDER BY matviewname
        """
        with self.engine.connect() as conn:
            rows = conn.execute(text(q), {"schema": schema}).fetchall()
        return [dict(r._mapping) for r in rows]

    def get_view_definition(self, name: str, schema: str = "public",
                             materialized: bool = False) -> str:
        if materialized:
            q = """SELECT definition FROM pg_matviews
                   WHERE matviewname = :name AND schemaname = :schema"""
        else:
            q = """SELECT view_definition FROM information_schema.views
                   WHERE table_name = :name AND table_schema = :schema"""
        with self.engine.connect() as conn:
            row = conn.execute(text(q), {"name": name, "schema": schema}).fetchone()
        return row[0] if row else ""

    def create_view(self, name: str, query: str, schema: str = "public",
                    materialized: bool = False) -> dict:
        from pgappforge.views.erd_schema_manager import _qi
        kind   = "MATERIALIZED VIEW" if materialized else "VIEW"
        suffix = " WITH DATA" if materialized else ""
        stmt   = (f"CREATE OR REPLACE {kind} {_qi(schema)}.{_qi(name)} AS\n"
                  f"{query.strip()}{suffix}")
        return self._run(stmt)

    def refresh_mat_view(self, name: str, schema: str = "public",
                          concurrently: bool = True) -> dict:
        from pgappforge.views.erd_schema_manager import _qi
        conc = " CONCURRENTLY" if concurrently else ""
        return self._run(
            f"REFRESH MATERIALIZED VIEW{conc} {_qi(schema)}.{_qi(name)}"
        )

    def drop_view(self, name: str, schema: str = "public",
                  materialized: bool = False) -> dict:
        from pgappforge.views.erd_schema_manager import _qi
        kind = "MATERIALIZED VIEW" if materialized else "VIEW"
        return self._run(f"DROP {kind} IF EXISTS {_qi(schema)}.{_qi(name)} CASCADE")

    # ── Policies ──────────────────────────────────────────────────────────────

    def list_policies(self, table: str | None = None,
                       schema: str = "public") -> list[dict]:
        where  = "AND tablename = :table" if table else ""
        params: dict = {"schema": schema}
        if table:
            params["table"] = table
        q = f"""
            SELECT policyname, tablename, permissive, roles,
                   cmd, qual, with_check
            FROM pg_policies
            WHERE schemaname = :schema {where}
            ORDER BY tablename, policyname
        """
        with self.engine.connect() as conn:
            rows = conn.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]

    def create_policy(self, table: str, name: str, using_expr: str,
                       command: str = "ALL", check_expr: str | None = None,
                       schema: str = "public") -> dict:
        from pgappforge.views.erd_schema_manager import _qi
        stmts = [
            f"ALTER TABLE {_qi(schema)}.{_qi(table)} ENABLE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {_qi(name)} ON {_qi(schema)}.{_qi(table)}",
        ]
        policy = (f"CREATE POLICY {_qi(name)} ON {_qi(schema)}.{_qi(table)}\n"
                  f"    FOR {command}\n"
                  f"    USING ({using_expr})")
        if check_expr:
            policy += f"\n    WITH CHECK ({check_expr})"
        stmts.append(policy)
        errors: list[str] = []
        applied = 0
        try:
            with self.engine.begin() as conn:
                for s in stmts:
                    conn.execute(text(s))
                    applied += 1
        except Exception as exc:
            errors.append(str(exc))
            applied = 0
        return {"applied": applied, "sql": stmts, "errors": errors}

    def drop_policy(self, table: str, name: str, schema: str = "public") -> dict:
        from pgappforge.views.erd_schema_manager import _qi
        return self._run(
            f"DROP POLICY IF EXISTS {_qi(name)} ON {_qi(schema)}.{_qi(table)}"
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, sql: str) -> dict:
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql))
            return {"applied": 1, "sql": [sql], "errors": []}
        except Exception as exc:
            log.error("DatabaseObjectManager: %s", exc)
            return {"applied": 0, "sql": [sql], "errors": [str(exc)]}
