from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

try:
	from cachetools import TTLCache
	_HAS_CACHETOOLS = True
except ImportError:
	_HAS_CACHETOOLS = False
	TTLCache = None  # type: ignore[misc,assignment]

from flask import current_app, g, request
from pgappforge import Model
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Table,
	Text,
	and_,
	event,
	or_,
	select,
	text,
)
from sqlalchemy.orm import Session, declared_attr

# SQLAlchemy 2.x mapped_column / Mapped — graceful fallback on 1.x
try:
	from sqlalchemy.orm import Mapped, mapped_column
	_SA2 = True
except ImportError:
	_SA2 = False  # type: ignore[assignment]

# PostgreSQL JSONB and ARRAY; fall back to JSON for non-PG databases
try:
	from sqlalchemy.dialects.postgresql import ARRAY, JSONB
	_PG_JSONB = JSONB
	_HAS_PG = True
except ImportError:
	from sqlalchemy import JSON as JSONB  # type: ignore[assignment]
	_HAS_PG = False

try:
	from sqlalchemy.inspection import inspect as sa_inspect
except ImportError:
	from sqlalchemy import inspect as sa_inspect  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit log table — appended to PgAppForge's shared metadata
# ---------------------------------------------------------------------------
# TEXT not VARCHAR for ip_address (IPv6 can exceed 50 chars) and user_agent
# JSONB on PG for changes; JSON elsewhere
_audit_changes_col = Column("changes", _PG_JSONB if _HAS_PG else JSONB)

rls_audit_log = Table(
	"rls_audit_log",
	Model.metadata,
	Column("id", Integer, primary_key=True),
	Column(
		"timestamp",
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		index=True,
	),
	Column("action", Text, nullable=False),
	Column("user_id", Integer, ForeignKey("ab_user.id"), nullable=False, index=True),
	Column("model", Text, nullable=False),
	Column("item_id", Integer, index=True),
	Column("organisation_id", Integer, index=True),
	Column("changes", _PG_JSONB if _HAS_PG else JSONB),
	Column("ip_address", Text),
	Column("user_agent", Text),
	Column("pg_policy_applied", Boolean, default=False),
	Column("session_vars_set", Boolean, default=False),
)

# Composite index: user + time range queries are the dominant access pattern
Index("ix_rls_audit_user_ts", rls_audit_log.c.user_id, rls_audit_log.c.timestamp)
Index("ix_rls_audit_org_model", rls_audit_log.c.organisation_id, rls_audit_log.c.model)


# ---------------------------------------------------------------------------
# Minimal TTL cache fallback when cachetools is absent
# ---------------------------------------------------------------------------
class _SimpleTTLCache:
	"""FIFO-eviction dict used when cachetools is not installed."""

	def __init__(self, maxsize: int = 1000, ttl: int = 300) -> None:
		self._store: dict[str, Any] = {}
		self._maxsize = maxsize
		# ttl ignored in fallback — document this limitation clearly

	def get(self, key: str) -> Any | None:
		return self._store.get(key)

	def __setitem__(self, key: str, value: Any) -> None:
		if len(self._store) >= self._maxsize:
			oldest = next(iter(self._store))
			del self._store[oldest]
		self._store[key] = value

	def __getitem__(self, key: str) -> Any:
		return self._store[key]

	def pop(self, key: str, default: Any = None) -> Any:
		return self._store.pop(key, default)

	def clear(self) -> None:
		self._store.clear()


def _make_cache(maxsize: int = 1000, ttl: int = 300) -> Any:
	if _HAS_CACHETOOLS:
		return TTLCache(maxsize=maxsize, ttl=ttl)
	return _SimpleTTLCache(maxsize=maxsize, ttl=ttl)


# ---------------------------------------------------------------------------
# Per-(user, model, org) filter result cache
# ---------------------------------------------------------------------------
class RLSFilterCache:
	"""Cache for compiled RLS filter lists keyed by (user_id, model_name, org_id)."""

	def __init__(self, maxsize: int = 1000, ttl: int = 300) -> None:
		self._cache = _make_cache(maxsize=maxsize, ttl=ttl)

	def _key(self, user_id: int, model: str, org_id: int | None = None) -> str:
		return f"{user_id}:{model}:{org_id or 'all'}"

	def get(self, user_id: int, model: str, org_id: int | None = None) -> list[Any] | None:
		return self._cache.get(self._key(user_id, model, org_id))

	def set(
		self,
		user_id: int,
		model: str,
		filters: list[Any],
		org_id: int | None = None,
	) -> None:
		self._cache[self._key(user_id, model, org_id)] = filters

	def invalidate(self, user_id: int | None = None, model: str | None = None) -> None:
		if user_id and model:
			self._cache.pop(self._key(user_id, model), None)
		else:
			self._cache.clear()


# ---------------------------------------------------------------------------
# PostgreSQL policy builder helpers
# ---------------------------------------------------------------------------

_PG_POLICY_TEMPLATE = """
DO $$
BEGIN
	IF NOT EXISTS (
		SELECT 1 FROM pg_policies
		WHERE schemaname = {schema!r}
		  AND tablename = {table!r}
		  AND policyname = {policy!r}
	) THEN
		{ddl};
	END IF;
END $$;
"""

_PG_ROLE_TEMPLATE = """
DO $$
BEGIN
	IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {role!r}) THEN
		CREATE ROLE {role_id};
	END IF;
END $$;
"""


def _pg_create_rls_policy(
	table: str,
	policy_name: str,
	using_expr: str,
	with_check_expr: str | None = None,
	schema: str = "public",
	command: str = "ALL",
	role: str = "PUBLIC",
) -> str:
	"""
	Return idempotent DDL to CREATE POLICY on *table* if it does not already exist.

	Args:
		table:            Target table name.
		policy_name:      Unique policy identifier within the table.
		using_expr:       USING clause expression (filters SELECT/DELETE/UPDATE).
		with_check_expr:  WITH CHECK clause expression (filters INSERT/UPDATE).
		                  Defaults to same as using_expr when None.
		schema:           Schema name (default "public").
		command:          SQL command the policy applies to ("ALL", "SELECT", ...).
		role:             Database role the policy applies to (default "PUBLIC").

	Returns:
		SQL string suitable for ``session.execute(text(...))`` inside a connection event.
	"""
	check_part = f"WITH CHECK ({with_check_expr or using_expr})"
	ddl = (
		f"CREATE POLICY {policy_name} ON {schema}.{table} "
		f"AS PERMISSIVE FOR {command} TO {role} "
		f"USING ({using_expr}) {check_part}"
	)
	return _PG_POLICY_TEMPLATE.format(
		schema=schema,
		table=table,
		policy=policy_name,
		ddl=ddl,
	)


def _pg_enable_rls(table: str, schema: str = "public") -> str:
	"""Return DDL to enable RLS and FORCE RLS (so table owners are also filtered)."""
	return (
		f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY;\n"
		f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY;"
	)


def _pg_disable_rls(table: str, schema: str = "public") -> str:
	return f"ALTER TABLE {schema}.{table} DISABLE ROW LEVEL SECURITY;"


def _pg_drop_policy(table: str, policy_name: str, schema: str = "public") -> str:
	return f"DROP POLICY IF EXISTS {policy_name} ON {schema}.{table};"


def _pg_set_session_vars(vars_: dict[str, str]) -> str:
	"""
	Return a SQL string that sets multiple ``app.`` namespace session variables
	in one statement via SELECT set_config().

	PostgreSQL session variables in the ``app.`` namespace are readable by RLS
	policy USING expressions via ``current_setting('app.user_id', true)``.

	Args:
		vars_: Mapping of variable name (without 'app.' prefix) to string value.

	Returns:
		A single SQL SELECT statement setting all variables.
	"""
	if not vars_:
		return "SELECT 1"
	selects = ", ".join(
		f"set_config('app.{k}', {v!r}, true)" for k, v in vars_.items()
	)
	return f"SELECT {selects}"


def _pg_admin_bypass_policy(table: str, schema: str = "public") -> str:
	"""
	Return DDL for an admin-bypass policy using ``current_setting('app.is_admin', true)``.

	Add this policy in addition to tenant-isolation policies.  When
	``app.is_admin`` is set to 'true' for a connection the admin sees all rows.
	"""
	return _pg_create_rls_policy(
		table=table,
		policy_name=f"{table}_admin_bypass",
		using_expr="current_setting('app.is_admin', true) = 'true'",
		schema=schema,
		command="ALL",
		role="PUBLIC",
	)


def _pg_tenant_isolation_policy(
	table: str,
	org_column: str = "organisation_id",
	schema: str = "public",
) -> str:
	"""
	Return DDL for a tenant-isolation policy that compares *org_column* against
	``current_setting('app.organisation_ids', true)``.

	The session variable is expected to be a JSON array of integers, e.g.
	``'[1, 2, 5]'``.  The policy uses a JSONB containment check for O(1) lookup.

	Args:
		table:      Table to protect.
		org_column: Column storing the organisation/tenant FK.
		schema:     Schema name.
	"""
	if _HAS_PG:
		# JSONB containment: fast GIN-indexable array membership check
		using = (
			f"(current_setting('app.is_admin', true) = 'true') OR "
			f"(current_setting('app.organisation_ids', true)::jsonb "
			f"@> to_jsonb({org_column}::int))"
		)
	else:
		# Fallback for non-PG: simple equality on a single org id
		using = (
			f"(current_setting('app.is_admin', true) = 'true') OR "
			f"({org_column}::text = current_setting('app.organisation_id', true))"
		)
	return _pg_create_rls_policy(
		table=table,
		policy_name=f"{table}_tenant_isolation",
		using_expr=using,
		schema=schema,
	)


def _pg_owner_policy(
	table: str,
	owner_column: str = "created_by",
	schema: str = "public",
) -> str:
	"""
	Return DDL for an ownership policy granting access when *owner_column*
	matches ``current_setting('app.user_id', true)``.
	"""
	using = (
		f"(current_setting('app.is_admin', true) = 'true') OR "
		f"({owner_column}::text = current_setting('app.user_id', true))"
	)
	return _pg_create_rls_policy(
		table=table,
		policy_name=f"{table}_owner_access",
		using_expr=using,
		schema=schema,
		command="ALL",
	)


def apply_pg_session_vars(session: Session, user: Any, org_ids: list[int]) -> bool:
	"""
	Set PostgreSQL ``app.*`` session variables for the active *session* based on
	*user* and *org_ids*.

	Variables set:
	- ``app.user_id``         — str(user.id)
	- ``app.organisation_ids``— JSON array of permitted org IDs
	- ``app.organisation_id`` — first org ID (single-org compat fallback)
	- ``app.is_admin``        — 'true' or 'false'
	- ``app.roles``           — comma-separated role names

	Returns True if variables were set successfully, False otherwise.
	Silently ignores non-PostgreSQL backends.
	"""
	if not _HAS_PG:
		return False
	try:
		is_admin = "true" if (hasattr(user, "is_admin") and user.is_admin()) else "false"
		roles_str = ",".join(
			r.name for r in getattr(user, "roles", [])
		)
		vars_: dict[str, str] = {
			"user_id": str(user.id),
			"organisation_ids": json.dumps(org_ids),
			"organisation_id": str(org_ids[0]) if org_ids else "0",
			"is_admin": is_admin,
			"roles": roles_str,
		}
		session.execute(text(_pg_set_session_vars(vars_)))
		return True
	except Exception:
		logger.exception("Failed to set PostgreSQL session variables")
		return False


# ---------------------------------------------------------------------------
# Main mixin
# ---------------------------------------------------------------------------
class RowLevelSecurityMixin:
	"""
	PostgreSQL-first Row Level Security (RLS) mixin for PgAppForge ModelViews.

	Combines two complementary enforcement layers:

	1. **Database-level RLS** (PostgreSQL only): DDL helpers to CREATE POLICY
	   statements on the underlying table, so the database engine enforces
	   isolation even for raw SQL connections that bypass SQLAlchemy.  Policies
	   read ``app.*`` session variables (``app.user_id``, ``app.organisation_ids``,
	   ``app.is_admin``) set at connection/request time via ``apply_pg_session_vars``.

	2. **ORM-level filtering**: ``query_rls()`` injects SQLAlchemy WHERE clauses
	   into every ModelView query.  This is the primary enforcement path for
	   non-PostgreSQL backends and for ORM queries that run before PG policies
	   activate.

	Key features:

	- **Admin bypass**: users where ``is_admin()`` is truthy skip all filters at
	  both the ORM and PG policy level.
	- **Tenant isolation**: multi-organisation aware; expands to sub-orgs via
	  recursive hierarchy walk when ``track_inheritance=True``.
	- **PG session variables**: ``apply_pg_session_vars()`` stamps ``app.*``
	  locals on each request so PG policies work without a custom DB role per user.
	- **Policy DDL generation**: ``generate_pg_policies()`` returns ready-to-execute
	  DDL (tenant isolation + admin bypass + optional owner access) for a given
	  table.  Call once at schema migration time.
	- **Role-based filters**: ``role_filters`` dict maps role name -> list of
	  SQLAlchemy clause callables.
	- **Custom rules**: arbitrary callables via ``custom_rules``.
	- **Temporal access control**: opt-in via ``temporal_control=True``; honours
	  ``valid_from`` / ``valid_to`` datetime columns.
	- **Audit logging**: writes to ``rls_audit_log`` table (JSONB changes on PG,
	  JSON elsewhere) with composite indexes on (user_id, timestamp) and
	  (organisation_id, model).
	- **Security webhooks**: POSTs audit entries to ``SECURITY_WEBHOOKS`` config
	  URLs (requires ``requests`` package; skips gracefully if absent).
	- **Caching**: filter lists cached per (user_id, model_name) using cachetools
	  TTLCache when available, plain dict otherwise.
	- **Fallback policy**: ``"deny"`` (safe default), ``"allow"``, or ``"custom"``
	  applied when user context is missing or an error occurs.

	Configuration attributes (set on subclass):
		organisation_field (str):    Column storing org/tenant FK. Default "organisation_id".
		owner_field (str):           Column tracking record creator. Default "created_by".
		parent_field (str):          Column for hierarchical org parent. Default "parent_id".
		pg_schema (str):             PostgreSQL schema for DDL helpers. Default "public".
		pg_org_column (str):         Column name used in PG tenant-isolation policy.
		pg_owner_column (str):       Column name used in PG owner-access policy.
		enable_pg_session_vars (bool): Set ``app.*`` session variables each request.
		enable_pg_owner_policy (bool): Include owner-access policy in DDL generation.
		enable_audit (bool):         Write to ``rls_audit_log``. Default True.
		enable_caching (bool):       Cache compiled filter lists. Default True.
		cache_ttl (int):             Cache TTL seconds. Default 300.
		strict_mode (bool):          Raise on errors vs. fall back. Default True.
		fallback_policy (str):       "deny" | "allow" | "custom". Default "deny".
		temporal_control (bool):     Filter by valid_from/valid_to. Default False.
		enable_delegation (bool):    Include user.delegated_orgs. Default False.
		track_inheritance (bool):    Expand org IDs to include children. Default True.
		enable_analytics (bool):     Fire security webhooks. Default True.
		custom_rules (list[Callable]):  (model_cls, user) -> clause | None.
		role_filters (dict[str, list[Callable] | None]): Role-name -> rule list.
	"""

	# ------------------------------------------------------------------
	# Core configuration
	# ------------------------------------------------------------------
	organisation_field: str = "organisation_id"
	owner_field: str = "created_by"
	parent_field: str = "parent_id"

	# PostgreSQL-specific configuration
	pg_schema: str = "public"
	pg_org_column: str = "organisation_id"
	pg_owner_column: str = "created_by"
	enable_pg_session_vars: bool = True
	enable_pg_owner_policy: bool = False

	# Feature flags
	enable_audit: bool = True
	enable_caching: bool = True
	cache_ttl: int = 300
	strict_mode: bool = True
	fallback_policy: str = "deny"
	temporal_control: bool = False
	enable_delegation: bool = False
	track_inheritance: bool = True
	enable_analytics: bool = True

	# Security rule hooks — override in subclasses
	custom_rules: list[Callable] = []
	role_filters: dict[str, list[Callable] | None] = {
		"admin": None,
		"manager": [
			lambda obj, user: obj.department_id == user.department_id,
			lambda obj, user: obj.organisation_id in user.managed_orgs,
		],
		"user": [
			lambda obj, user: obj.created_by == user.id,
			lambda obj, user: obj.organisation_id == user.organisation_id,
		],
	}

	# Class-level filter cache (shared across instances of a given subclass)
	_filter_cache: RLSFilterCache = RLSFilterCache()

	def __init__(self) -> None:
		super().__init__()
		self._setup_audit_hooks()
		self._init_cache()

	# ------------------------------------------------------------------
	# Initialisation
	# ------------------------------------------------------------------

	def _setup_audit_hooks(self) -> None:
		"""Register SQLAlchemy instance-level event listeners for audit logging."""
		if self.enable_audit:
			event.listen(self.__class__, "after_insert", self._audit_insert)
			event.listen(self.__class__, "after_update", self._audit_update)
			event.listen(self.__class__, "after_delete", self._audit_delete)

	def _init_cache(self) -> None:
		if self.enable_caching:
			self._permission_cache = _make_cache(maxsize=1000, ttl=self.cache_ttl)

	# ------------------------------------------------------------------
	# PostgreSQL DDL / session-variable helpers (public API)
	# ------------------------------------------------------------------

	def generate_pg_policies(self, table: str | None = None) -> str:
		"""
		Return composite DDL enabling RLS on *table* and creating all configured
		policies (admin bypass + tenant isolation + optional owner access).

		Call this once during Alembic migrations or initial schema setup.

		Args:
			table: Table name.  Falls back to ``self.datamodel.obj.__tablename__``
			       when not provided.

		Returns:
			A multi-statement SQL string.  Each statement is idempotent.

		Raises:
			AttributeError: If table cannot be inferred and is not provided.
		"""
		if table is None:
			table = self.datamodel.obj.__tablename__

		schema = self.pg_schema
		parts: list[str] = [
			_pg_enable_rls(table, schema),
			_pg_admin_bypass_policy(table, schema),
			_pg_tenant_isolation_policy(table, self.pg_org_column, schema),
		]
		if self.enable_pg_owner_policy:
			parts.append(_pg_owner_policy(table, self.pg_owner_column, schema))

		return "\n\n".join(parts)

	def drop_pg_policies(self, table: str | None = None) -> str:
		"""
		Return DDL to DROP all policies generated by ``generate_pg_policies``
		and DISABLE RLS on *table*.  Useful in migrations or test teardown.
		"""
		if table is None:
			table = self.datamodel.obj.__tablename__
		schema = self.pg_schema
		parts = [
			_pg_drop_policy(table, f"{table}_admin_bypass", schema),
			_pg_drop_policy(table, f"{table}_tenant_isolation", schema),
		]
		if self.enable_pg_owner_policy:
			parts.append(_pg_drop_policy(table, f"{table}_owner_access", schema))
		parts.append(_pg_disable_rls(table, schema))
		return "\n".join(parts)

	def set_pg_session_context(self) -> bool:
		"""
		Stamp PostgreSQL ``app.*`` session variables for the current request user.

		Should be called at the start of each request (e.g. from a
		``before_request`` hook or ``get_query()``).  Idempotent and safe to
		call multiple times per request.

		Returns:
			True if variables were set, False if conditions not met (non-PG,
			no user context, etc.).
		"""
		if not _HAS_PG or not self.enable_pg_session_vars:
			return False
		if not hasattr(g, "user"):
			return False
		try:
			session: Session = self.datamodel.session
			org_ids = self.get_permitted_orgs()
			return apply_pg_session_vars(session, g.user, org_ids)
		except Exception:
			logger.exception("set_pg_session_context failed")
			return False

	# ------------------------------------------------------------------
	# Organisation hierarchy resolution
	# ------------------------------------------------------------------

	def get_organisation_hierarchy(self, org_id: int) -> set[int]:
		"""
		Return *org_id* plus all recursively nested child organisation IDs.

		Uses ``select()`` (SA 2.x) then falls back to ``session.query()`` (SA 1.x).
		Catches and logs exceptions without re-raising so a broken hierarchy does
		not block access for the parent org.
		"""
		orgs: set[int] = {org_id}
		try:
			model_cls = self.datamodel.obj
			session: Session = self.datamodel.session
			try:
				stmt = select(model_cls).where(
					getattr(model_cls, self.parent_field) == org_id
				)
				children = session.execute(stmt).scalars().all()
			except TypeError:
				children = (
					session.query(model_cls)
					.filter(getattr(model_cls, self.parent_field) == org_id)
					.all()
				)
			for child in children:
				orgs.update(self.get_organisation_hierarchy(child.id))
		except Exception:
			logger.exception(
				"RLS: error resolving organisation hierarchy for org_id=%s", org_id
			)
		return orgs

	# ------------------------------------------------------------------
	# Core ORM-level filter
	# ------------------------------------------------------------------

	def query_rls(self, query: Any) -> Any:
		"""
		Apply all applicable RLS WHERE clauses to *query*.

		Evaluation order:
		1. User context check — raises or falls back per strict_mode / fallback_policy.
		2. Admin bypass — returns query unmodified.
		3. PG session variable stamping (if enabled and on PostgreSQL).
		4. Organisation/tenant filter with optional sub-org expansion.
		5. Role-based filters.
		6. Custom security rules.
		7. Temporal filters (if temporal_control=True).

		Compiled filter lists are cached per (user_id, model_name) when
		enable_caching=True.

		Returns:
			The query with all applicable WHERE clauses applied.
		"""
		if not hasattr(g, "user"):
			if self.strict_mode:
				raise RuntimeError("No user context available for RLS")
			logger.warning(
				"RLS: no user context — applying fallback policy '%s'",
				self.fallback_policy,
			)
			return self._apply_fallback_policy(query)

		try:
			# Admin bypass at ORM level
			if hasattr(g.user, "is_admin") and g.user.is_admin():
				# Still stamp PG vars so DB-level policies see is_admin=true
				self.set_pg_session_context()
				return query

			# Stamp PG session vars for this request
			self.set_pg_session_context()

			# Cache hit
			if self.enable_caching:
				cached = self._filter_cache.get(g.user.id, self.__class__.__name__)
				if cached is not None:
					return query.filter(and_(*cached))

			filters: list[Any] = []

			# ---- Organisation / tenant filter ----
			permitted_orgs = self.get_permitted_orgs()
			if permitted_orgs:
				org_col = getattr(self.datamodel.obj, self.organisation_field, None)
				if org_col is not None:
					if self.track_inheritance:
						all_orgs: set[int] = set()
						for org_id in permitted_orgs:
							all_orgs.update(self.get_organisation_hierarchy(org_id))
						filters.append(org_col.in_(all_orgs))
					else:
						filters.append(org_col.in_(permitted_orgs))

			# ---- Role-based filters ----
			role_clauses = self.get_role_filters()
			if role_clauses:
				filters.extend(role_clauses)

			# ---- Custom security rules ----
			custom_clauses = self.get_custom_filters()
			if custom_clauses:
				filters.extend(custom_clauses)

			# ---- Temporal access control ----
			if self.temporal_control:
				temporal = self._get_temporal_filter()
				if temporal is not None:
					filters.append(temporal)

			if filters:
				query = query.filter(and_(*filters))
				if self.enable_caching:
					self._filter_cache.set(g.user.id, self.__class__.__name__, filters)

			return query

		except Exception as exc:
			logger.exception("RLS: error applying query filters")
			if self.strict_mode:
				raise RuntimeError(f"RLS filter error: {exc}") from exc
			return self._apply_fallback_policy(query)

	def _apply_fallback_policy(self, query: Any) -> Any:
		"""Apply the configured fallback security policy when normal RLS fails."""
		if self.fallback_policy == "deny":
			return query.filter(text("1=0"))
		elif self.fallback_policy == "allow":
			return query
		else:
			return self._apply_custom_fallback(query)

	def _apply_custom_fallback(self, query: Any) -> Any:
		"""Override to implement a project-specific fallback policy."""
		return query.filter(text("1=0"))

	def _get_temporal_filter(self) -> Any | None:
		"""
		Build a time-window filter using ``valid_from`` / ``valid_to`` columns.

		Returns None if neither column exists on the model.
		Handles NULL as "no bound" (open interval).
		"""
		model_cls = self.datamodel.obj
		has_from = hasattr(model_cls, "valid_from")
		has_to = hasattr(model_cls, "valid_to")
		if not (has_from or has_to):
			return None

		now = datetime.now(timezone.utc)
		clauses: list[Any] = []

		if has_from:
			clauses.append(
				or_(model_cls.valid_from.is_(None), model_cls.valid_from <= now)
			)
		if has_to:
			clauses.append(
				or_(model_cls.valid_to.is_(None), model_cls.valid_to >= now)
			)

		return and_(*clauses) if clauses else None

	# ------------------------------------------------------------------
	# Permission resolution
	# ------------------------------------------------------------------

	def get_permitted_orgs(self) -> list[int]:
		"""
		Collect all organisation IDs the current user may access.

		Sources consulted in order:
		- Direct ``organisation_field`` attribute on user object.
		- ``user.organisations`` iterable (organisation FK collection).
		- ``user.delegated_orgs`` when ``enable_delegation=True``.

		Returns a deduplicated list preserving first-seen order.
		"""
		if not hasattr(g, "user"):
			return []

		orgs: list[int] = []

		if hasattr(g.user, self.organisation_field):
			org_id = getattr(g.user, self.organisation_field)
			if org_id is not None:
				orgs.append(int(org_id))

		if hasattr(g.user, "organisations"):
			for org in g.user.organisations:
				orgs.append(int(org.id))

		if self.enable_delegation and hasattr(g.user, "delegated_orgs"):
			for org in g.user.delegated_orgs:
				orgs.append(int(org.id))

		return list(dict.fromkeys(orgs))

	def get_role_filters(self) -> list[Any]:
		"""
		Evaluate role-based filter callables for each of the current user's roles.

		Each callable receives ``(model_class, user)`` and must return an
		SQLAlchemy clause expression or None.  Rules with duplicate object identity
		are evaluated at most once per call.

		Returns a flat list of non-None clause expressions.
		"""
		if not hasattr(g, "user") or not hasattr(g.user, "roles"):
			return []

		filters: list[Any] = []
		seen: set[int] = set()

		for role in g.user.roles:
			rules = self.role_filters.get(role.name)
			if not rules:
				# admin role gets None → skip → no restriction
				continue
			for rule in rules:
				rule_id = id(rule)
				if rule_id in seen:
					continue
				seen.add(rule_id)
				try:
					clause = rule(self.datamodel.obj, g.user)
					if clause is not None:
						filters.append(clause)
				except Exception:
					logger.exception(
						"RLS: role filter rule error for role '%s'", role.name
					)
					if self.strict_mode:
						raise

		return filters

	def get_custom_filters(self) -> list[Any]:
		"""
		Evaluate ``custom_rules`` callables.

		Each callable receives ``(model_class, user)`` and must return an
		SQLAlchemy clause expression or None.

		Returns a flat list of non-None clause expressions.
		"""
		filters: list[Any] = []
		for rule in self.custom_rules:
			try:
				clause = rule(self.datamodel.obj, g.user)
				if clause is not None:
					filters.append(clause)
			except Exception as exc:
				logger.error("RLS: custom rule error: %s", exc)
				if self.strict_mode:
					raise
		return filters

	# ------------------------------------------------------------------
	# ModelView hook overrides
	# ------------------------------------------------------------------

	def get_query(self) -> Any:
		"""Override ModelView.get_query to inject RLS WHERE clauses."""
		return self.query_rls(super().get_query())

	def pre_add(self, item: Any) -> None:
		"""Enforce RLS on add: verify org access and stamp ownership/timestamp fields."""
		super().pre_add(item)
		self._require_user_context()
		self._verify_org_access(item)

		if hasattr(item, self.owner_field):
			setattr(item, self.owner_field, g.user.id)
		if hasattr(item, "created_at"):
			item.created_at = datetime.now(timezone.utc)
		if hasattr(item, "created_by"):
			item.created_by = g.user.id

		self._audit_log("add", item)

	def pre_update(self, item: Any) -> None:
		"""Enforce RLS on update: verify org access and stamp updated_at/updated_by."""
		super().pre_update(item)
		self._require_user_context()
		self._verify_org_access(item)

		if hasattr(item, "updated_at"):
			item.updated_at = datetime.now(timezone.utc)
		if hasattr(item, "updated_by"):
			item.updated_by = g.user.id

		self._audit_log("update", item)

	def pre_delete(self, item: Any) -> None:
		"""Enforce RLS on delete: verify org access before removal."""
		super().pre_delete(item)
		self._require_user_context()
		self._verify_org_access(item)
		self._audit_log("delete", item)

	# ------------------------------------------------------------------
	# Guard helpers
	# ------------------------------------------------------------------

	def _require_user_context(self) -> None:
		if not hasattr(g, "user"):
			raise PermissionError("User context required for this operation")

	def _verify_org_access(self, item: Any) -> None:
		"""
		Raise PermissionError if *item*'s organisation is not in the permitted set.

		Skipped for admin users and when the item has no organisation field.
		"""
		if hasattr(g.user, "is_admin") and g.user.is_admin():
			return
		if not hasattr(item, self.organisation_field):
			return
		org_id = getattr(item, self.organisation_field)
		if org_id is None:
			return
		permitted = self.get_permitted_orgs()
		if permitted and int(org_id) not in permitted:
			raise PermissionError(
				f"Not authorised for organisation {org_id}. "
				f"Permitted organisations: {permitted}"
			)

	# ------------------------------------------------------------------
	# Audit logging
	# ------------------------------------------------------------------

	def _audit_log(self, action: str, item: Any) -> None:
		"""
		Write an audit log entry for *action* on *item* to ``rls_audit_log``.

		Change tracking uses SQLAlchemy instance-state inspection to capture
		before/after attribute values for update and delete operations.

		Records whether PG session variables were applied and whether a PG
		policy is in effect (inferred from ``_HAS_PG``).

		Silently absorbs failures unless ``strict_mode=True``.
		"""
		if not self.enable_audit:
			return

		try:
			changes: dict[str, Any] = {}
			if action in ("update", "delete"):
				insp = sa_inspect(item)
				for attr in insp.attrs:
					hist = attr.history
					if hist.has_changes():
						changes[attr.key] = {
							"old": hist.deleted[0] if hist.deleted else None,
							"new": hist.added[0] if hist.added else None,
						}
					elif action == "delete" and hist.deleted:
						changes[attr.key] = {"old": hist.deleted[0], "new": None}

			log_entry: dict[str, Any] = {
				"action": action,
				"user_id": g.user.id,
				"model": item.__class__.__name__,
				"item_id": getattr(item, "id", None),
				"organisation_id": getattr(item, self.organisation_field, None),
				"timestamp": datetime.now(timezone.utc).isoformat(),
				"changes": changes,
				"ip_address": request.remote_addr if request else None,
				"user_agent": (request.user_agent.string if request else None),
				"pg_policy_applied": _HAS_PG,
				"session_vars_set": self.enable_pg_session_vars and _HAS_PG,
			}

			self.datamodel.session.execute(rls_audit_log.insert(), [log_entry])

			if self.enable_analytics:
				self._notify_security_webhooks(log_entry)

		except Exception as exc:
			logger.error("RLS: audit logging error: %s", exc)
			if self.strict_mode:
				raise

	# SQLAlchemy mapper-level event stubs (registered in _setup_audit_hooks)
	@staticmethod
	def _audit_insert(mapper: Any, connection: Any, target: Any) -> None:
		logger.debug(
			"RLS audit: insert %s id=%s",
			target.__class__.__name__,
			getattr(target, "id", None),
		)

	@staticmethod
	def _audit_update(mapper: Any, connection: Any, target: Any) -> None:
		logger.debug(
			"RLS audit: update %s id=%s",
			target.__class__.__name__,
			getattr(target, "id", None),
		)

	@staticmethod
	def _audit_delete(mapper: Any, connection: Any, target: Any) -> None:
		logger.debug(
			"RLS audit: delete %s id=%s",
			target.__class__.__name__,
			getattr(target, "id", None),
		)

	# ------------------------------------------------------------------
	# Security webhook notification
	# ------------------------------------------------------------------

	def _notify_security_webhooks(self, log_entry: dict[str, Any]) -> None:
		"""
		POST the audit log entry as JSON to each URL in ``SECURITY_WEBHOOKS`` config.

		``SECURITY_WEBHOOKS`` should be a list of dicts with at least a ``url`` key.
		Requires the ``requests`` package; logs a warning and returns if absent.
		datetime/set/bytes values are serialised with ``default=str``.
		Individual webhook failures are logged but do not propagate.
		"""
		try:
			import requests as _requests
		except ImportError:
			logger.warning(
				"RLS: 'requests' package not installed — skipping webhook notifications"
			)
			return

		try:
			webhooks: list[dict[str, Any]] = current_app.config.get(
				"SECURITY_WEBHOOKS", []
			)
			safe_entry = json.loads(json.dumps(log_entry, default=str))
			for webhook in webhooks:
				url = webhook.get("url")
				if not url:
					continue
				try:
					_requests.post(url, json=safe_entry, timeout=5)
				except _requests.exceptions.RequestException as exc:
					logger.error(
						"RLS: webhook POST failed for '%s': %s", url, exc
					)
		except Exception as exc:
			logger.error("RLS: webhook notification error: %s", exc)

	# ------------------------------------------------------------------
	# Bulk operation helpers
	# ------------------------------------------------------------------

	def bulk_verify_org_access(self, items: list[Any]) -> list[Any]:
		"""
		Filter *items* to those the current user is permitted to access.

		More efficient than calling ``_verify_org_access`` per item because
		permitted orgs are resolved once and set membership is O(1).

		Args:
			items: List of model instances.

		Returns:
			Subset of *items* the user may access.  Empty list when no user
			context or no permitted orgs.
		"""
		if not hasattr(g, "user"):
			return []
		if hasattr(g.user, "is_admin") and g.user.is_admin():
			return items

		permitted = set(self.get_permitted_orgs())
		if not permitted:
			return []

		result: list[Any] = []
		for item in items:
			org_id = getattr(item, self.organisation_field, None)
			if org_id is None or int(org_id) in permitted:
				result.append(item)
		return result

	def invalidate_user_cache(self, user_id: int | None = None) -> None:
		"""
		Invalidate cached RLS filters for *user_id*, or all users if None.

		Call after role/organisation membership changes.
		"""
		self._filter_cache.invalidate(user_id=user_id)


# ---------------------------------------------------------------------------
# Standalone module-level helpers (usable without the mixin)
# ---------------------------------------------------------------------------

def generate_rls_policies_for_table(
	table: str,
	org_column: str = "organisation_id",
	owner_column: str = "created_by",
	schema: str = "public",
	include_owner_policy: bool = False,
) -> str:
	"""
	Generate complete, idempotent RLS DDL for *table*.

	Standalone alternative to ``RowLevelSecurityMixin.generate_pg_policies()``
	for use in Alembic migration scripts without instantiating a ModelView.

	Returns a multi-statement SQL string ready for
	``op.execute()`` or ``connection.execute(text(...))``.
	"""
	parts = [
		_pg_enable_rls(table, schema),
		_pg_admin_bypass_policy(table, schema),
		_pg_tenant_isolation_policy(table, org_column, schema),
	]
	if include_owner_policy:
		parts.append(_pg_owner_policy(table, owner_column, schema))
	return "\n\n".join(parts)


"""
Usage Examples
==============

--- 1. Basic ModelView with RLS ---

from pgappforge import Model, ModelView
from pgappforge.models.sqla.interface import SQLAInterface
from sqlalchemy import Column, Integer, String, ForeignKey
from pgappforge.mixins.rls_mixin import RowLevelSecurityMixin


class Document(Model):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    title = Column(String(100), nullable=False)
    organisation_id = Column(Integer, ForeignKey("organisations.id"))
    created_by = Column(Integer, ForeignKey("ab_user.id"))


class DocumentView(RowLevelSecurityMixin, ModelView):
    datamodel = SQLAInterface(Document)
    organisation_field = "organisation_id"
    enable_audit = True
    strict_mode = True


--- 2. Generating PG RLS policies in an Alembic migration ---

from pgappforge.mixins.rls_mixin import generate_rls_policies_for_table

def upgrade():
    ddl = generate_rls_policies_for_table(
        table="documents",
        org_column="organisation_id",
        include_owner_policy=True,
    )
    op.execute(ddl)

def downgrade():
    from pgappforge.mixins.rls_mixin import _pg_drop_policy, _pg_disable_rls
    op.execute(_pg_drop_policy("documents", "documents_admin_bypass"))
    op.execute(_pg_drop_policy("documents", "documents_tenant_isolation"))
    op.execute(_pg_drop_policy("documents", "documents_owner_access"))
    op.execute(_pg_disable_rls("documents"))


--- 3. Stamping PG session variables in a Flask before_request hook ---

from pgappforge.mixins.rls_mixin import apply_pg_session_vars

@app.before_request
def set_rls_context():
    if hasattr(g, "user") and g.user:
        db_session = appbuilder.get_session
        org_ids = [g.user.organisation_id] if g.user.organisation_id else []
        apply_pg_session_vars(db_session, g.user, org_ids)


--- 4. Custom security rules ---

def visible_to_department(model_cls, user):
    return model_cls.department_id == user.department_id


class ReportView(RowLevelSecurityMixin, ModelView):
    datamodel = SQLAInterface(Report)
    custom_rules = [visible_to_department]
    role_filters = {
        "admin": None,        # None = bypass all filters
        "analyst": [
            lambda m, u: m.published.is_(True),
        ],
    }
"""
