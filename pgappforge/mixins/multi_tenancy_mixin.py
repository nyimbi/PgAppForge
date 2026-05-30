"""
multi_tenancy_mixin.py

Row-level security and tenant isolation for SQLAlchemy models in PgAppForge.

Isolation strategies supported:
  1. Discriminator column  — tenant_id FK on every row (default, portable)
  2. PostgreSQL schemas    — each tenant lives in its own PG schema (opt-in)

Cross-tenant reporting is handled through the CrossTenantQuery helper, which
bypasses normal tenant scoping under an explicit allowlist of admin roles.

Author: Nyimbi Odero
Date: 25/08/2024
Updated: 2026-05-30 — complete rewrite: RLS, PG schema isolation, cross-tenant
                       reporting, SA 2.x mapped_column/Mapped, Python 3.12 hints
Version: 3.0
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Generator

from flask import current_app, g
from pgappforge import Model
from sqlalchemy import (
	JSON,
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	event,
	func,
	select,
	text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Session, declared_attr, relationship

try:
	from sqlalchemy.inspection import inspect as sa_inspect
except ImportError:
	from sqlalchemy import inspect as sa_inspect  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# PostgreSQL-specific types — graceful fallback for non-PG backends
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.dialects.postgresql import JSONB as _JSONB
	from sqlalchemy.dialects.postgresql import UUID as _PG_UUID
	_UUID_COL_TYPE = _PG_UUID(as_uuid=True)
	_JSONB_TYPE = _JSONB
	_PG_AVAILABLE = True
except ImportError:
	_UUID_COL_TYPE = String(36)
	_JSONB_TYPE = JSON
	_PG_AVAILABLE = False

# ---------------------------------------------------------------------------
# SQLAlchemy 2.x mapped_column / Mapped — fall back on 1.x installs
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.orm import Mapped, mapped_column
	_SA2 = True
except ImportError:
	_SA2 = False

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
	"""Timezone-aware UTC timestamp (datetime.utcnow is deprecated in 3.12)."""
	return datetime.now(timezone.utc)


def _resolve_session(session: Session | None = None) -> Session:
	"""
	Return *session* if provided; otherwise pull from PgAppForge's db
	extension.  Raises ValueError when neither source is available.
	"""
	if session is not None:
		return session
	try:
		from flask import current_app as _ca
		return _ca.extensions["sqlalchemy"].db.session
	except (KeyError, AttributeError, RuntimeError):
		pass
	raise ValueError(
		"No SQLAlchemy session available. "
		"Pass session= explicitly or call within a Flask application context."
	)


# ---------------------------------------------------------------------------
# Isolation strategy enum
# ---------------------------------------------------------------------------

class TenantIsolation(str, Enum):
	"""
	Row-level isolation strategy.

	DISCRIMINATOR — a tenant_id FK column on every table (portable, default).
	PG_SCHEMA     — each tenant gets its own PostgreSQL search_path schema.
	               Requires PostgreSQL and superuser/CREATEROLE privileges.
	"""
	DISCRIMINATOR = "discriminator"
	PG_SCHEMA = "pg_schema"


# ---------------------------------------------------------------------------
# Tenant model
# ---------------------------------------------------------------------------

class Tenant(Model):
	"""
	Central tenant registry.

	One row per tenant.  The ``schema_name`` field is populated only when
	``TenantIsolation.PG_SCHEMA`` strategy is in use.

	Hierarchy: tenants may have a parent (e.g. reseller → sub-tenant).  The
	``full_hierarchy`` hybrid property walks this chain from root to leaf.

	Attributes:
		id              UUID primary key (PG native UUID; String(36) elsewhere).
		name            Human-readable display name, unique across all tenants.
		slug            URL-safe identifier, unique.  Used in subdomains / paths.
		domain          Optional custom domain for domain-based routing.
		schema_name     PostgreSQL schema name when PG_SCHEMA isolation is used.
		status          "active" | "suspended" | "pending".
		plan_id         Subscription plan identifier (free / starter / pro / ent).
		settings        Opaque JSONB settings bag (JSONB on PG, JSON elsewhere).
		extra_metadata  Extensible attribute bag — do not collide with SA metadata.
		parent_id       Self-referential FK for hierarchical tenants.
		created_at      UTC creation timestamp.
		updated_at      UTC last-modification timestamp.
	"""

	__tablename__ = "nx_tenants"
	__table_args__ = (
		Index("ix_nx_tenants_slug", "slug"),
		Index("ix_nx_tenants_status", "status"),
		Index("ix_nx_tenants_domain", "domain"),
		Index("ix_nx_tenants_parent", "parent_id"),
	)

	id = Column(_UUID_COL_TYPE, primary_key=True, default=uuid.uuid4)
	name = Column(Text, unique=True, nullable=False)
	slug = Column(String(100), unique=True, nullable=False)
	domain = Column(Text, unique=True, nullable=True)
	schema_name = Column(String(63), unique=True, nullable=True)  # PG identifier limit

	status = Column(String(20), nullable=False, default="active")
	plan_id = Column(String(50), nullable=False, default="free")

	settings = Column(_JSONB_TYPE, default=dict, nullable=False)
	extra_metadata = Column(_JSONB_TYPE, default=dict, nullable=False)

	created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
	updated_at = Column(
		DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
	)

	parent_id = Column(_UUID_COL_TYPE, ForeignKey("nx_tenants.id"), nullable=True)
	parent: Tenant | None = relationship(  # type: ignore[assignment]
		"Tenant",
		remote_side="Tenant.id",
		backref="children",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Tenant slug={self.slug!r} status={self.status!r}>"

	@hybrid_property
	def is_active(self) -> bool:
		return self.status == "active"

	@hybrid_property
	def is_root(self) -> bool:
		"""True when this tenant has no parent."""
		return self.parent_id is None

	@property
	def full_hierarchy(self) -> list[Tenant]:
		"""Ancestor chain from root down to and including this tenant."""
		if self.is_root or self.parent is None:
			return [self]
		return self.parent.full_hierarchy + [self]

	def pg_schema_ddl(self) -> str:
		"""
		Return the DDL statement required to create this tenant's PG schema.

		Only meaningful when TenantIsolation.PG_SCHEMA is in use.
		The caller is responsible for executing this on an appropriate connection.

		Raises:
			ValueError: When schema_name is unset.
		"""
		if not self.schema_name:
			raise ValueError(
				f"Tenant {self.slug!r} has no schema_name — "
				"set it before calling pg_schema_ddl()."
			)
		safe = self.schema_name.replace('"', '""')
		return f'CREATE SCHEMA IF NOT EXISTS "{safe}";'


# ---------------------------------------------------------------------------
# Cross-tenant reporting helper
# ---------------------------------------------------------------------------

class CrossTenantQuery:
	"""
	Context manager / helper that temporarily bypasses tenant scoping so
	privileged code paths can query across all tenants.

	Only roles listed in ``allowed_roles`` (compared against ``g.user.roles``)
	may enter cross-tenant mode.  Raises ``PermissionError`` otherwise.

	Usage::

		with CrossTenantQuery(allowed_roles={"admin", "superuser"}):
			results = session.execute(select(Product)).scalars().all()

	Inside the ``with`` block, ``g._cross_tenant_active`` is True, which
	``MultiTenancyMixin.get_tenant_select()`` and ``.get_tenant_query()``
	check before applying the tenant filter.
	"""

	def __init__(self, allowed_roles: set[str] | None = None) -> None:
		self._allowed = allowed_roles or {"admin", "superuser"}

	def __enter__(self) -> CrossTenantQuery:
		user = getattr(g, "user", None)
		if user is None:
			raise PermissionError("No user context for cross-tenant query.")
		user_roles: set[str] = {
			r.name for r in getattr(user, "roles", [])
		}
		if not (user_roles & self._allowed):
			raise PermissionError(
				f"Cross-tenant queries require one of {self._allowed}; "
				f"user has {user_roles}."
			)
		g._cross_tenant_active = True
		return self

	def __exit__(self, *_: Any) -> None:
		g._cross_tenant_active = False

	@staticmethod
	@contextmanager
	def bypass(allowed_roles: set[str] | None = None) -> Generator[None, None, None]:
		"""Functional alias: ``with CrossTenantQuery.bypass(): ...``"""
		ctx = CrossTenantQuery(allowed_roles=allowed_roles)
		ctx.__enter__()
		try:
			yield
		finally:
			ctx.__exit__()


# ---------------------------------------------------------------------------
# PostgreSQL schema manager
# ---------------------------------------------------------------------------

class PGSchemaTenantManager:
	"""
	Manages PostgreSQL schema-per-tenant isolation.

	Each tenant gets a dedicated schema (e.g. ``tenant_acme``).  All tables
	for that tenant are created inside that schema using SQLAlchemy's
	``schema=`` table argument.

	Workflow:
	  1. Create tenant row (``Tenant`` model) and set ``schema_name``.
	  2. Call ``provision_schema(tenant, session)`` to CREATE SCHEMA IF NOT EXISTS.
	  3. Call ``set_search_path(tenant_slug, connection)`` at the start of each
	     request so queries land in the correct schema automatically.
	  4. Call ``deprovision_schema(tenant, session)`` to DROP SCHEMA … CASCADE on
	     tenant deletion (irreversible — use with caution).

	This class performs no DDL beyond schema creation/deletion.  Table DDL
	within schemas is handled by Alembic migrations scoped to each schema.
	"""

	SCHEMA_PREFIX = "tenant_"

	@classmethod
	def schema_for_slug(cls, slug: str) -> str:
		"""
		Derive a safe PostgreSQL identifier from a tenant slug.

		Strips non-alphanumeric characters and truncates to 63 bytes (PG limit).
		"""
		safe = "".join(c if c.isalnum() or c == "_" else "_" for c in slug.lower())
		name = f"{cls.SCHEMA_PREFIX}{safe}"
		return name[:63]

	@classmethod
	def provision_schema(cls, tenant: Tenant, session: Session) -> None:
		"""
		Execute ``CREATE SCHEMA IF NOT EXISTS`` for *tenant*.

		Sets ``tenant.schema_name`` when not already populated.

		Raises:
			RuntimeError: On non-PostgreSQL backends.
		"""
		if not _PG_AVAILABLE:
			raise RuntimeError(
				"PG_SCHEMA isolation requires PostgreSQL + psycopg2/asyncpg."
			)
		if not tenant.schema_name:
			tenant.schema_name = cls.schema_for_slug(tenant.slug)
			session.add(tenant)

		session.execute(text(tenant.pg_schema_ddl()))
		session.commit()
		log.info("Provisioned PG schema %r for tenant %r", tenant.schema_name, tenant.slug)

	@classmethod
	def deprovision_schema(cls, tenant: Tenant, session: Session) -> None:
		"""
		Execute ``DROP SCHEMA … CASCADE`` for *tenant*.

		IRREVERSIBLE.  The caller must confirm intent before invoking.

		Raises:
			ValueError: When schema_name is unset.
		"""
		if not tenant.schema_name:
			raise ValueError(f"Tenant {tenant.slug!r} has no schema_name.")
		safe = tenant.schema_name.replace('"', '""')
		session.execute(text(f'DROP SCHEMA IF EXISTS "{safe}" CASCADE;'))
		session.commit()
		log.warning(
			"Dropped PG schema %r for tenant %r — data is gone",
			tenant.schema_name, tenant.slug,
		)

	@classmethod
	def set_search_path(cls, schema_name: str, session: Session) -> None:
		"""
		Set ``search_path`` on the underlying connection for the current
		transaction so un-schema-qualified queries land in the right schema.

		Call this in a ``before_request`` hook after resolving the tenant::

			@app.before_request
			def set_tenant_schema():
				tenant = resolve_tenant_from_request()
				if tenant and tenant.schema_name:
					PGSchemaTenantManager.set_search_path(
						tenant.schema_name, db.session
					)
		"""
		safe = schema_name.replace('"', '""')
		session.execute(text(f'SET search_path TO "{safe}", public;'))


# ---------------------------------------------------------------------------
# Main mixin
# ---------------------------------------------------------------------------

class MultiTenancyMixin:
	"""
	Row-level security and tenant isolation mixin for PgAppForge models.

	Attach to any SQLAlchemy / FAB ``Model`` subclass to gain:

	Isolation
	---------
	* **Discriminator column** (default): every row carries a ``tenant_id`` UUID
	  FK pointing at ``nx_tenants.id``.  Queries are automatically scoped via
	  ``get_tenant_select()`` / ``get_tenant_query()``.
	* **PostgreSQL schema** (opt-in): set ``__isolation_strategy__ =
	  TenantIsolation.PG_SCHEMA`` and use ``PGSchemaTenantManager`` to create
	  per-tenant schemas.  The discriminator column is still present for
	  cross-schema admin queries.

	Security
	--------
	* ``before_insert`` auto-populates ``tenant_id`` from ``g.tenant_id``.
	* ``before_update`` makes ``tenant_id`` immutable — reassignment raises
	  ``ValueError`` immediately rather than silently corrupting data.
	* ``after_update`` emits structured audit log entries (field-level diff)
	  when ``__audit_changes__`` is ``True``.
	* Tenant existence + active status validated on insert when
	  ``__tenant_validation__`` is ``True``.
	* Cross-tenant queries only possible via ``CrossTenantQuery`` context
	  manager, restricted to roles in ``__cross_tenant_roles__``.

	Shared data
	-----------
	Set ``__shared_data__ = True`` to include rows with ``NULL`` tenant_id
	(i.e. system-wide defaults) in every tenant's query results.

	Indexes
	-------
	GIN index on ``extra_metadata`` (PostgreSQL only) + BTREE on ``tenant_id``
	are declared via ``__table_args__`` in subclasses using the helper
	``tenant_table_args()`` class method.

	Cross-tenant reporting
	----------------------
	Use ``CrossTenantQuery`` or ``CrossTenantQuery.bypass()``::

		with CrossTenantQuery(allowed_roles={"admin"}):
			all_products = session.execute(select(Product)).scalars().all()

	Class-level knobs (override per model):
		``__tenant_field__``         Column name for the FK (default: ``"tenant_id"``).
		``__shared_data__``          Include NULL-tenant rows (default: ``False``).
		``__audit_changes__``        Field-level diff logging on UPDATE (default: ``True``).
		``__tenant_validation__``    Validate tenant on INSERT (default: ``True``).
		``__isolation_strategy__``   ``TenantIsolation`` member (default: DISCRIMINATOR).
		``__cross_tenant_roles__``   Roles allowed to use ``CrossTenantQuery`` (default: ``{"admin"}``).

	Example::

		class Product(MultiTenancyMixin, Model):
			__tablename__ = "nx_products"
			__table_args__ = MultiTenancyMixin.tenant_table_args()

			id = Column(Integer, primary_key=True)
			name = Column(Text, nullable=False)

		class ProductModelView(ModelView):
			datamodel = TenantScopedSQLAInterface(Product)
	"""

	__tenant_field__: str = "tenant_id"
	__shared_data__: bool = False
	__audit_changes__: bool = True
	__tenant_validation__: bool = True
	__isolation_strategy__: TenantIsolation = TenantIsolation.DISCRIMINATOR
	__cross_tenant_roles__: set[str] = {"admin", "superuser"}

	# ------------------------------------------------------------------
	# Table args helper
	# ------------------------------------------------------------------

	@classmethod
	def tenant_table_args(
		cls,
		extra: tuple[Any, ...] = (),
		table_kwargs: dict[str, Any] | None = None,
	) -> tuple[Any, ...] | tuple[Any, ..., dict[str, Any]]:
		"""
		Return a ``__table_args__`` tuple that includes the recommended indexes
		for tenant isolation.

		Adds:
		  - BTREE index on ``tenant_id`` (all backends)
		  - GIN index on ``extra_metadata`` (PostgreSQL only — silently omitted
		    on other backends since GIN is a PG dialect extension)

		Args:
			extra: Additional ``Index`` / ``UniqueConstraint`` objects to include.
			table_kwargs: Optional dict of table-level kwargs (e.g.
				``{"schema": "myschema"}``).

		Returns:
			Tuple suitable for assignment to ``__table_args__``.

		Example::

			class Invoice(MultiTenancyMixin, Model):
				__tablename__ = "nx_invoices"
				__table_args__ = MultiTenancyMixin.tenant_table_args(
					extra=(UniqueConstraint("tenant_id", "invoice_number"),),
					table_kwargs={"schema": "billing"},
				)
		"""
		indexes: list[Any] = [
			Index(f"ix_{cls.__name__.lower()}_tenant_id", "tenant_id"),
		]
		if _PG_AVAILABLE:
			try:
				from sqlalchemy.dialects.postgresql import JSONB as _J  # noqa: F401
				indexes.append(
					Index(
						f"ix_{cls.__name__.lower()}_extra_metadata_gin",
						"extra_metadata",
						postgresql_using="gin",
					)
				)
			except Exception:
				pass

		result: tuple[Any, ...] = (*indexes, *extra)
		if table_kwargs:
			return (*result, table_kwargs)
		return result

	# ------------------------------------------------------------------
	# Declared columns / relationships
	# ------------------------------------------------------------------

	@declared_attr
	def tenant_id(cls):  # noqa: N805
		"""UUID tenant discriminator column with BTREE index."""
		return Column(
			_UUID_COL_TYPE,
			ForeignKey("nx_tenants.id", ondelete="RESTRICT"),
			nullable=False,
			index=True,
		)

	@declared_attr
	def tenant(cls):  # noqa: N805
		"""Lazy-select tenant relationship (avoid N+1 in list views)."""
		return relationship(
			"Tenant",
			lazy="select",
			foreign_keys=f"[{cls.__name__}.tenant_id]",
			backref=f"{cls.__name__.lower()}_set",
		)

	@declared_attr
	def created_at(cls):  # noqa: N805
		"""UTC row creation timestamp."""
		return Column(DateTime(timezone=True), default=_utcnow, nullable=False)

	@declared_attr
	def updated_at(cls):  # noqa: N805
		"""UTC last-update timestamp; auto-updated via onupdate."""
		return Column(
			DateTime(timezone=True),
			default=_utcnow,
			onupdate=_utcnow,
			nullable=False,
		)

	@declared_attr
	def extra_metadata(cls):  # noqa: N805
		"""
		Schema-less JSONB metadata bag.

		On PostgreSQL a GIN index can be declared via ``tenant_table_args()``.
		Intentionally named ``extra_metadata`` (not ``metadata``) to avoid
		shadowing SQLAlchemy's ``MetaData`` descriptor.
		"""
		return Column(_JSONB_TYPE, default=dict, nullable=False)

	# ------------------------------------------------------------------
	# ORM event hooks
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Register ORM event listeners after mapper configuration completes."""
		event.listen(cls, "before_insert", cls._evt_before_insert)
		event.listen(cls, "before_update", cls._evt_before_update)
		if cls.__audit_changes__:
			event.listen(cls, "after_update", cls._evt_after_update)

	@staticmethod
	def _evt_before_insert(mapper: Any, connection: Any, target: Any) -> None:
		"""
		Auto-populate ``tenant_id`` from ``g.tenant_id``.

		When ``__tenant_validation__`` is True, also asserts the target tenant
		is active via a session lookup.

		Raises:
			ValueError: Missing / inactive tenant.
		"""
		if target.tenant_id is None:
			target.tenant_id = MultiTenancyMixin.get_current_tenant_id()

		if target.__tenant_validation__:
			session = Session.object_session(target)
			if session is not None:
				tenant: Tenant | None = session.get(Tenant, target.tenant_id)
				if tenant is None or tenant.status != "active":
					raise ValueError(
						f"Insert rejected: tenant {target.tenant_id!r} is "
						f"{'missing' if tenant is None else 'not active (status=' + tenant.status + ')'}."
					)

	@staticmethod
	def _evt_before_update(mapper: Any, connection: Any, target: Any) -> None:
		"""
		Enforce ``tenant_id`` immutability.

		Raises:
			ValueError: On any attempt to reassign a record to a different tenant.
		"""
		state = sa_inspect(target)
		history = state.attrs[MultiTenancyMixin.__tenant_field__].history
		if history.has_changes() and history.deleted:
			old = history.deleted[0]
			new = history.added[0] if history.added else None
			raise ValueError(
				f"tenant_id is immutable — cannot move record from "
				f"{old!r} to {new!r}."
			)

	@staticmethod
	def _evt_after_update(mapper: Any, connection: Any, target: Any) -> None:
		"""
		Emit a structured audit log entry containing field-level diffs.

		Skipped silently when ``__audit_changes__`` is False at runtime.
		"""
		if not getattr(target, "__audit_changes__", True):
			return

		state = sa_inspect(target)
		changes: dict[str, dict[str, Any]] = {}
		for attr in state.attrs:
			hist = attr.history
			if hist.has_changes():
				changes[attr.key] = {
					"old": hist.deleted[0] if hist.deleted else None,
					"new": hist.added[0] if hist.added else None,
				}

		if changes:
			log.info(
				"Tenant audit: %s pk=%s tenant=%s changed=%s",
				target.__class__.__name__,
				getattr(target, "id", "?"),
				target.tenant_id,
				list(changes.keys()),
				extra={
					"audit_changes": changes,
					"tenant_id": str(target.tenant_id),
					"model": target.__class__.__name__,
				},
			)

	# ------------------------------------------------------------------
	# Tenant context resolution
	# ------------------------------------------------------------------

	@staticmethod
	def get_current_tenant_id() -> uuid.UUID | str:
		"""
		Resolve the active tenant ID from Flask's request context (``g.tenant_id``).

		Falls back to ``DEFAULT_TENANT_ID`` from app config when
		``ALLOW_NO_TENANT`` is True.

		Returns:
			Active tenant UUID (or string for non-Postgres backends).

		Raises:
			ValueError: When no tenant is set and fallback is disabled.
		"""
		tenant_id = getattr(g, "tenant_id", None)
		if tenant_id is not None:
			return tenant_id
		try:
			app_cfg = current_app.config
		except RuntimeError:
			raise ValueError("get_current_tenant_id() called outside Flask app context.")

		if app_cfg.get("ALLOW_NO_TENANT", False):
			default = app_cfg.get("DEFAULT_TENANT_ID")
			if default is not None:
				return default

		raise ValueError(
			"No tenant in request context. "
			"Call MultiTenancyMixin.set_current_tenant() in a before_request hook."
		)

	@classmethod
	def set_current_tenant(
		cls,
		tenant_id: uuid.UUID | str,
		session: Session | None = None,
	) -> None:
		"""
		Set the active tenant on ``g.tenant_id``, with optional DB validation.

		When ``__tenant_validation__`` is True the tenant row is fetched to
		confirm it exists and is active.

		Args:
			tenant_id: UUID or string UUID.
			session:   Optional SA session for the validation lookup.

		Raises:
			ValueError: When the tenant is missing or inactive.
		"""
		if isinstance(tenant_id, str):
			try:
				tenant_id = uuid.UUID(tenant_id)
			except ValueError:
				pass  # Keep as string for non-UUID backends

		if cls.__tenant_validation__:
			_session = _resolve_session(session)
			tenant: Tenant | None = _session.get(Tenant, tenant_id)
			if tenant is None or tenant.status != "active":
				raise ValueError(
					f"Cannot set tenant {tenant_id!r}: "
					f"{'not found' if tenant is None else 'status=' + tenant.status}."
				)

		g.tenant_id = tenant_id

		# PG schema: also update search_path for the session
		if (
			cls.__isolation_strategy__ == TenantIsolation.PG_SCHEMA
			and _PG_AVAILABLE
		):
			try:
				_session = _resolve_session(session)
				if tenant is not None and tenant.schema_name:  # type: ignore[possibly-undefined]
					PGSchemaTenantManager.set_search_path(tenant.schema_name, _session)
			except Exception as exc:
				log.warning("Could not set PG search_path: %s", exc)

	# ------------------------------------------------------------------
	# Query helpers
	# ------------------------------------------------------------------

	@classmethod
	def _cross_tenant_active(cls) -> bool:
		"""True when inside a CrossTenantQuery context."""
		return getattr(g, "_cross_tenant_active", False)

	@classmethod
	def get_tenant_select(cls):
		"""
		Return a tenant-scoped SQLAlchemy 2.x ``select()`` statement.

		Respects:
		  - ``__shared_data__``: also include rows where ``tenant_id IS NULL``.
		  - ``CrossTenantQuery`` context: skip the tenant filter entirely.

		Returns:
			``Select`` construct filtered to the current tenant (or unrestricted
			when inside a ``CrossTenantQuery`` block).
		"""
		stmt = select(cls)
		if cls._cross_tenant_active():
			return stmt

		tenant_id = cls.get_current_tenant_id()
		tenant_col = getattr(cls, cls.__tenant_field__)

		if cls.__shared_data__:
			stmt = stmt.where(
				(tenant_col == tenant_id) | (tenant_col.is_(None))
			)
		else:
			stmt = stmt.where(tenant_col == tenant_id)

		return stmt

	@classmethod
	def get_tenant_query(cls, query: Any = None) -> Any:
		"""
		Return a tenant-scoped legacy ``Query`` object (SA 1.x style).

		Kept for compatibility with PgAppForge's ``SQLAInterface`` layer.
		Prefer ``get_tenant_select()`` in new code.

		Args:
			query: Existing Query to narrow; defaults to ``cls.query``.

		Returns:
			Tenant-filtered Query.
		"""
		if query is None:
			query = cls.query  # type: ignore[attr-defined]

		if cls._cross_tenant_active():
			return query

		tenant_id = cls.get_current_tenant_id()
		tenant_col = getattr(cls, cls.__tenant_field__)

		if cls.__shared_data__:
			query = query.filter(
				(tenant_col == tenant_id) | (tenant_col.is_(None))
			)
		else:
			query = query.filter(tenant_col == tenant_id)

		return query

	@classmethod
	def for_tenant(cls, tenant_id: uuid.UUID | str, session: Session | None = None):
		"""
		Execute a tenant-scoped ``select()`` for an *explicit* tenant ID without
		touching ``g.tenant_id``.

		Useful in background tasks / CLI commands that run without a request
		context.

		Args:
			tenant_id: Explicit tenant UUID.
			session:   SA session to use; auto-resolved when None.

		Returns:
			List of model instances belonging to *tenant_id*.
		"""
		_session = _resolve_session(session)
		tenant_col = getattr(cls, cls.__tenant_field__)
		stmt = select(cls).where(tenant_col == tenant_id)
		return _session.execute(stmt).scalars().all()

	# ------------------------------------------------------------------
	# Cross-tenant aggregate / reporting queries
	# ------------------------------------------------------------------

	@classmethod
	def cross_tenant_count(
		cls,
		session: Session | None = None,
		allowed_roles: set[str] | None = None,
	) -> dict[str, int]:
		"""
		Return a ``{tenant_id: row_count}`` mapping across all tenants.

		Requires the current user to have a role in ``__cross_tenant_roles__``
		(or the ``allowed_roles`` override).

		Args:
			session:       SA session; auto-resolved when None.
			allowed_roles: Override the default cross-tenant role guard.

		Returns:
			Dict mapping tenant_id (as string) → row count.

		Raises:
			PermissionError: When the current user lacks sufficient roles.
		"""
		roles = allowed_roles or cls.__cross_tenant_roles__
		with CrossTenantQuery(roles):
			_session = _resolve_session(session)
			tenant_col = getattr(cls, cls.__tenant_field__)
			rows = (
				_session.execute(
					select(tenant_col, func.count().label("n"))
					.select_from(cls)
					.group_by(tenant_col)
				)
				.all()
			)
			return {str(r[0]): r[1] for r in rows}

	@classmethod
	def cross_tenant_latest(
		cls,
		n: int = 10,
		session: Session | None = None,
		allowed_roles: set[str] | None = None,
	) -> list[Any]:
		"""
		Return the *n* most recently updated rows across all tenants.

		Admin / reporting use only — guarded by ``CrossTenantQuery``.

		Args:
			n:             Maximum rows to return.
			session:       SA session; auto-resolved when None.
			allowed_roles: Cross-tenant role guard override.

		Returns:
			List of model instances ordered by ``updated_at`` descending.
		"""
		roles = allowed_roles or cls.__cross_tenant_roles__
		with CrossTenantQuery(roles):
			_session = _resolve_session(session)
			stmt = (
				select(cls)
				.order_by(cls.updated_at.desc())  # type: ignore[attr-defined]
				.limit(n)
			)
			return _session.execute(stmt).scalars().all()

	# ------------------------------------------------------------------
	# Bulk operations (tenant-scoped)
	# ------------------------------------------------------------------

	@classmethod
	def bulk_create(
		cls,
		data: list[dict[str, Any]],
		tenant_id: uuid.UUID | str | None = None,
		session: Session | None = None,
	) -> list[Any]:
		"""
		Bulk-insert rows, stamping each with the resolved tenant_id.

		Args:
			data:      List of field dicts (``tenant_id`` will be set automatically).
			tenant_id: Explicit override; defaults to current context tenant.
			session:   SA session; auto-resolved when None.

		Returns:
			List of newly created instances (flushed, not yet committed).

		Raises:
			ValueError: When no session is available.
		"""
		effective_tid = tenant_id or cls.get_current_tenant_id()
		_session = _resolve_session(session)
		instances: list[Any] = []
		for item in data:
			item.setdefault(cls.__tenant_field__, effective_tid)
			instances.append(cls(**item))
		_session.add_all(instances)
		_session.flush()
		return instances

	@classmethod
	def bulk_update(
		cls,
		data: list[dict[str, Any]],
		tenant_id: uuid.UUID | str | None = None,
		session: Session | None = None,
	) -> list[Any]:
		"""
		Bulk-update rows, enforcing that each record belongs to the tenant.

		Each dict in *data* must contain an ``"id"`` key.

		Args:
			data:      List of ``{"id": <pk>, field: value, …}`` dicts.
			tenant_id: Explicit override; defaults to current context tenant.
			session:   SA session; auto-resolved when None.

		Returns:
			List of updated instances (flushed).

		Raises:
			ValueError: When a record is not found or belongs to a different tenant.
		"""
		effective_tid = tenant_id or cls.get_current_tenant_id()
		_session = _resolve_session(session)
		tenant_col_attr = cls.__tenant_field__
		updated: list[Any] = []

		for item in data:
			record_id = item.pop("id")
			instance = _session.get(cls, record_id)
			if instance is None:
				raise ValueError(f"{cls.__name__} pk={record_id!r} not found.")
			if str(getattr(instance, tenant_col_attr)) != str(effective_tid):
				raise ValueError(
					f"{cls.__name__} pk={record_id!r} belongs to tenant "
					f"{getattr(instance, tenant_col_attr)!r}, not {effective_tid!r}."
				)
			for key, value in item.items():
				setattr(instance, key, value)
			updated.append(instance)

		_session.flush()
		return updated

	@classmethod
	def bulk_delete(
		cls,
		ids: list[Any],
		tenant_id: uuid.UUID | str | None = None,
		session: Session | None = None,
	) -> int:
		"""
		Bulk-delete rows by primary key, enforcing tenant ownership.

		Args:
			ids:       List of primary key values.
			tenant_id: Explicit override; defaults to current context tenant.
			session:   SA session; auto-resolved when None.

		Returns:
			Number of rows deleted.

		Raises:
			ValueError: When any record belongs to a different tenant.
		"""
		effective_tid = tenant_id or cls.get_current_tenant_id()
		_session = _resolve_session(session)
		tenant_col = getattr(cls, cls.__tenant_field__)

		rows = (
			_session.execute(
				select(cls)
				.where(cls.id.in_(ids))  # type: ignore[attr-defined]
				.where(tenant_col == effective_tid)
			)
			.scalars()
			.all()
		)

		found_ids = {getattr(r, "id") for r in rows}
		missing = set(ids) - found_ids
		if missing:
			raise ValueError(
				f"{cls.__name__}: ids {missing} not found for tenant {effective_tid!r}. "
				"Refusing partial delete."
			)

		for row in rows:
			_session.delete(row)
		_session.flush()
		return len(rows)

	# ------------------------------------------------------------------
	# Per-tenant statistics
	# ------------------------------------------------------------------

	@classmethod
	def get_tenant_statistics(
		cls,
		tenant_id: uuid.UUID | str | None = None,
		session: Session | None = None,
	) -> dict[str, Any]:
		"""
		Row-count, recency, and metadata key statistics for one tenant.

		Args:
			tenant_id: Explicit tenant; defaults to current context tenant.
			session:   SA session; auto-resolved when None.

		Returns:
			Dict with keys:
			  ``total_records``  — int
			  ``last_updated``   — datetime | None
			  ``metadata_keys``  — list[str] of distinct top-level ``extra_metadata``
			                       keys (PostgreSQL only; empty list on other backends)
		"""
		effective_tid = tenant_id or cls.get_current_tenant_id()
		_session = _resolve_session(session)
		tenant_col = getattr(cls, cls.__tenant_field__)

		total: int = _session.execute(
			select(func.count())
			.select_from(cls)
			.where(tenant_col == effective_tid)
		).scalar_one()

		last_updated = _session.execute(
			select(cls.updated_at)  # type: ignore[attr-defined]
			.where(tenant_col == effective_tid)
			.order_by(cls.updated_at.desc())  # type: ignore[attr-defined]
			.limit(1)
		).scalar_one_or_none()

		metadata_keys: list[str] = []
		if _PG_AVAILABLE and hasattr(cls, "extra_metadata"):
			try:
				keys = (
					_session.execute(
						select(func.jsonb_object_keys(cls.extra_metadata).distinct())
						.where(tenant_col == effective_tid)
					)
					.scalars()
					.all()
				)
				metadata_keys = list(keys)
			except Exception:
				pass  # Non-PG or missing jsonb support

		return {
			"total_records": total,
			"last_updated": last_updated,
			"metadata_keys": metadata_keys,
		}


# ---------------------------------------------------------------------------
# PgAppForge SQLAInterface drop-in with automatic tenant scoping
# ---------------------------------------------------------------------------

try:
	from pgappforge.models.sqla.interface import SQLAInterface as _SQLAInterface

	class TenantScopedSQLAInterface(_SQLAInterface):
		"""
		Drop-in replacement for ``SQLAInterface`` that automatically restricts
		all queries to the active tenant when the backing model inherits from
		``MultiTenancyMixin``.

		Usage::

			class InvoiceModelView(ModelView):
				datamodel = TenantScopedSQLAInterface(Invoice)

		Cross-tenant admin queries work transparently via ``CrossTenantQuery``::

			with CrossTenantQuery(allowed_roles={"admin"}):
				view.datamodel.get_list(...)
		"""

		def query(
			self,
			filters: Any = None,
			order_column: str = "",
			order_direction: str = "",
		) -> Any:
			q = super().query(filters, order_column, order_direction)
			if issubclass(self.obj, MultiTenancyMixin):
				q = self.obj.get_tenant_query(q)
			return q

		def query_count(self, filters: Any = None) -> int:
			if issubclass(self.obj, MultiTenancyMixin):
				tenant_id = MultiTenancyMixin.get_current_tenant_id()
				tenant_col = getattr(self.obj, self.obj.__tenant_field__)
				stmt = (
					select(func.count())
					.select_from(self.obj)
					.where(tenant_col == tenant_id)
				)
				return self.session.execute(stmt).scalar_one()
			return super().query_count(filters)  # type: ignore[misc]

except ImportError:
	# FAB not installed in the current environment (e.g. testing mixin in isolation)
	log.debug(
		"pgappforge.models.sqla.interface not importable — "
		"TenantScopedSQLAInterface skipped."
	)
