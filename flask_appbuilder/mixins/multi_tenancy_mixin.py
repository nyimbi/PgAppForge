"""
multi_tenancy_mixin.py

Multi-tenancy support for SQLAlchemy models in Flask-AppBuilder applications.
Provides automatic query scoping to the current tenant, data isolation between
tenants, optional shared-data mode, audit logging, bulk operations, and
tenant-scoped statistics.

Author: Nyimbi Odero
Date: 25/08/2024
Updated: 2026-05-30 — SQLAlchemy 2.x, Python 3.12 type hints
Version: 2.0
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import current_app, g
from flask_appbuilder import Model
from flask_appbuilder.models.sqla.interface import SQLAInterface
from sqlalchemy import (
	JSON,
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Integer,
	String,
	event,
	select,
	func,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session, declared_attr, relationship

# PostgreSQL-specific types with JSON fallback for portability
try:
	from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
	_UUID_TYPE = PG_UUID(as_uuid=True)
	_JSONB_TYPE = JSONB
	_PG_AVAILABLE = True
except ImportError:
	_UUID_TYPE = String(36)
	_JSONB_TYPE = JSON
	_PG_AVAILABLE = False

# SQLAlchemy 2.x mapped_column / Mapped with 1.x fallback
try:
	from sqlalchemy.orm import mapped_column, Mapped
	_SA2 = True
except ImportError:
	_SA2 = False

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
	"""Timezone-aware UTC now (datetime.utcnow is deprecated in 3.12)."""
	return datetime.now(timezone.utc)


class Tenant(Model):
	"""
	Represents a tenant in the system.

	Attributes:
		id: Primary key (UUID)
		name: Unique tenant name
		slug: URL-friendly identifier
		domain: Optional custom domain
		settings: Tenant-specific settings (JSONB / JSON)
		is_active: Tenant enabled flag
		created_at: Creation timestamp (UTC)
		updated_at: Last modification timestamp (UTC)
		extra_metadata: Extensible metadata blob
		parent_id: Parent tenant for hierarchical setups
		custom_attributes: Extensible attribute bag
	"""

	__tablename__ = "nx_tenants"

	id = Column(_UUID_TYPE, primary_key=True, default=uuid.uuid4)
	name = Column(String(100), unique=True, nullable=False, index=True)
	slug = Column(String(100), unique=True, nullable=False, index=True)
	domain = Column(String(255), unique=True, nullable=True)
	settings = Column(_JSONB_TYPE, default=dict, nullable=False)
	is_active = Column(Boolean, default=True, nullable=False)
	created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
	updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
	# Renamed from 'metadata' to avoid collision with SQLAlchemy's MetaData attribute
	extra_metadata = Column(_JSONB_TYPE, default=dict, nullable=False)
	parent_id = Column(_UUID_TYPE, ForeignKey("nx_tenants.id"), nullable=True)
	custom_attributes = Column(_JSONB_TYPE, default=dict, nullable=False)

	parent = relationship("Tenant", remote_side="Tenant.id", backref="children")

	def __repr__(self) -> str:
		return f"<Tenant {self.name}>"

	@hybrid_property
	def is_root(self) -> bool:
		"""True when tenant has no parent."""
		return self.parent_id is None

	@hybrid_property
	def full_hierarchy(self) -> list[Tenant]:
		"""Full ancestor chain from root down to this tenant."""
		if self.is_root:
			return [self]
		return self.parent.full_hierarchy + [self]


class MultiTenancyMixin:
	"""
	Advanced mixin for multi-tenant data isolation and management.

	Attach to any SQLAlchemy / FAB Model subclass to gain:
	- Automatic tenant_id population on INSERT
	- Tenant-ID immutability enforcement on UPDATE
	- Optional audit logging of changed fields
	- Tenant-scoped query helpers (compatible with SA 1.x and 2.x)
	- Bulk create / update / delete within a tenant scope
	- Tenant data statistics

	Class-level knobs (override per model):
		__tenant_field__       Column name holding the FK (default: "tenant_id")
		__shared_data__        When True, queries also return rows with NULL tenant_id
		__audit_changes__      When True, field changes are logged after UPDATE
		__cache_enabled__      When True, get_tenant_query() caches via app.cache
		__tenant_validation__  When True, INSERT/set_current_tenant validates tenant

	Usage::

		class Product(MultiTenancyMixin, Model):
			__tablename__ = "nx_products"
			id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
			name = Column(String(100), nullable=False)
			price = Column(Numeric(10, 2), nullable=False)

			__shared_data__ = True

		class ProductModelView(ModelView):
			datamodel = TenantScopedSQLAInterface(Product)
	"""

	__tenant_field__: str = "tenant_id"
	__shared_data__: bool = False
	__audit_changes__: bool = True
	__cache_enabled__: bool = True
	__tenant_validation__: bool = True

	# ------------------------------------------------------------------
	# Declared columns / relationships
	# ------------------------------------------------------------------

	@declared_attr
	def tenant_id(cls):
		"""Tenant foreign key with UUID type."""
		return Column(
			_UUID_TYPE,
			ForeignKey("nx_tenants.id"),
			nullable=False,
			index=True,
		)

	@declared_attr
	def tenant(cls):
		"""Eager-loaded tenant relationship."""
		return relationship(
			"Tenant",
			lazy="joined",
			foreign_keys=f"[{cls.__name__}.tenant_id]",
			backref=f"{cls.__name__.lower()}_set",
		)

	@declared_attr
	def created_at(cls):
		return Column(DateTime(timezone=True), default=_utcnow, nullable=False)

	@declared_attr
	def updated_at(cls):
		return Column(
			DateTime(timezone=True),
			default=_utcnow,
			onupdate=_utcnow,
			nullable=False,
		)

	@declared_attr
	def extra_metadata(cls):
		"""Schema-less metadata storage (JSONB on Postgres, JSON elsewhere)."""
		return Column(_JSONB_TYPE, default=dict, nullable=False)

	# ------------------------------------------------------------------
	# Event listeners
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Register ORM event listeners after mapper configuration."""
		event.listen(cls, "before_insert", cls._before_insert)
		event.listen(cls, "before_update", cls._before_update)
		if cls.__audit_changes__:
			event.listen(cls, "after_update", cls._after_update)

	@staticmethod
	def _before_insert(mapper, connection, target) -> None:
		"""
		Auto-populate tenant_id from Flask g and optionally validate the tenant.

		Raises:
			ValueError: If the resolved tenant is inactive or missing.
		"""
		if target.tenant_id is None:
			target.tenant_id = MultiTenancyMixin.get_current_tenant_id()

		if target.__tenant_validation__:
			session = Session.object_session(target)
			if session is not None:
				tenant = session.get(Tenant, target.tenant_id)
				if not tenant or not tenant.is_active:
					raise ValueError(
						f"Invalid or inactive tenant: {target.tenant_id}"
					)

	@staticmethod
	def _before_update(mapper, connection, target) -> None:
		"""
		Prevent tenant_id from being changed after initial insert.

		Raises:
			ValueError: If tenant_id modification is attempted.
		"""
		state = sa_inspect(target)
		history = state.attrs.tenant_id.history
		if history.has_changes() and history.deleted:
			raise ValueError(
				"tenant_id is immutable — cannot reassign a record to a different tenant"
			)

	@staticmethod
	def _after_update(mapper, connection, target) -> None:
		"""Emit a structured audit log entry for every changed field."""
		if not target.__audit_changes__:
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
				"Audit: %s[%s] changed fields=%s",
				target.__class__.__name__,
				getattr(target, "id", "?"),
				list(changes.keys()),
				extra={"audit_changes": changes, "tenant_id": str(target.tenant_id)},
			)

	# ------------------------------------------------------------------
	# Tenant context helpers
	# ------------------------------------------------------------------

	@staticmethod
	def get_current_tenant_id() -> uuid.UUID | str:
		"""
		Retrieve the tenant ID stored in Flask's request context (``g.tenant_id``).

		Falls back to ``DEFAULT_TENANT_ID`` from app config when
		``ALLOW_NO_TENANT`` is True.

		Returns:
			The current tenant's UUID (or string ID for non-Postgres backends).

		Raises:
			ValueError: When no tenant is set and fallback is disabled.
		"""
		tenant_id = getattr(g, "tenant_id", None)
		if tenant_id is None:
			if current_app.config.get("ALLOW_NO_TENANT", False):
				return current_app.config.get("DEFAULT_TENANT_ID")
			raise ValueError(
				"No tenant set in current request context. "
				"Call MultiTenancyMixin.set_current_tenant() in a before_request hook."
			)
		return tenant_id

	@classmethod
	def set_current_tenant(
		cls,
		tenant_id: uuid.UUID | str,
		session: Session | None = None,
	) -> None:
		"""
		Set the active tenant on Flask's ``g`` object, with optional validation.

		Args:
			tenant_id: UUID or string UUID of the tenant.
			session: Optional SA session used for validation lookup.
				When None and validation is enabled, the FAB db session is used.

		Raises:
			ValueError: If the tenant does not exist or is inactive.
		"""
		if isinstance(tenant_id, str):
			tenant_id = uuid.UUID(tenant_id)

		if cls.__tenant_validation__:
			from flask_appbuilder import current_app as _ca  # noqa: F401 — used below

			_session = session
			if _session is None:
				# Best-effort: pull from FAB's db extension
				try:
					from flask import current_app as ca

					_session = ca.extensions["sqlalchemy"].db.session
				except (KeyError, AttributeError):
					pass

			if _session is not None:
				tenant = _session.get(Tenant, tenant_id)
				if not tenant or not tenant.is_active:
					raise ValueError(
						f"Invalid or inactive tenant: {tenant_id}"
					)

		g.tenant_id = tenant_id

	# ------------------------------------------------------------------
	# Query helpers (SA 1.x legacy + SA 2.x select())
	# ------------------------------------------------------------------

	@classmethod
	def get_tenant_query(cls, query=None):
		"""
		Return a tenant-scoped legacy Query object (SA 1.x style).

		Compatible with Flask-AppBuilder's datamodel layer which still
		consumes Query objects.  Results are optionally cached via
		``current_app.cache`` when ``__cache_enabled__`` is True.

		Args:
			query: Existing Query to narrow; defaults to ``cls.query``.

		Returns:
			Tenant-filtered Query object.
		"""
		if query is None:
			query = cls.query

		tenant_id = cls.get_current_tenant_id()

		if cls.__cache_enabled__:
			cache_key = f"tenant_query_{cls.__name__}_{tenant_id}"
			cache = getattr(current_app, "cache", None)
			if cache is not None:
				cached = cache.get(cache_key)
				if cached is not None:
					return cached

		tenant_col = getattr(cls, cls.__tenant_field__)
		if cls.__shared_data__:
			query = query.filter(
				(tenant_col == tenant_id) | (tenant_col.is_(None))
			)
		else:
			query = query.filter(tenant_col == tenant_id)

		if cls.__cache_enabled__:
			cache = getattr(current_app, "cache", None)
			if cache is not None:
				cache.set(cache_key, query)

		return query

	@classmethod
	def get_tenant_select(cls):
		"""
		Return a tenant-scoped SQLAlchemy 2.x ``select()`` statement.

		Prefer this over ``get_tenant_query()`` in new code paths that
		use ``session.execute()``.

		Returns:
			``Select`` construct filtered to the current tenant.
		"""
		tenant_id = cls.get_current_tenant_id()
		tenant_col = getattr(cls, cls.__tenant_field__)
		stmt = select(cls)
		if cls.__shared_data__:
			stmt = stmt.where((tenant_col == tenant_id) | (tenant_col.is_(None)))
		else:
			stmt = stmt.where(tenant_col == tenant_id)
		return stmt

	# ------------------------------------------------------------------
	# Bulk operations
	# ------------------------------------------------------------------

	@classmethod
	def bulk_tenant_operation(
		cls,
		operation: str,
		data: list[dict[str, Any]],
		tenant_id: uuid.UUID | str | None = None,
		session: Session | None = None,
	) -> list[Any]:
		"""
		Execute bulk create / update / delete within a tenant scope.

		Args:
			operation: One of ``"create"``, ``"update"``, ``"delete"``.
			data: List of dicts.  For ``"update"`` each dict must contain ``"id"``.
				  For ``"delete"`` each dict must contain ``"id"``.
			tenant_id: Explicit tenant override; defaults to current context tenant.
			session: SA session to use; pulls from FAB db extension when None.

		Returns:
			List of affected model instances (empty for delete).

		Raises:
			ValueError: For unknown operations or missing session.
		"""
		effective_tenant = tenant_id or cls.get_current_tenant_id()
		if isinstance(effective_tenant, str):
			effective_tenant = uuid.UUID(effective_tenant)

		_session = session
		if _session is None:
			try:
				from flask import current_app as ca

				_session = ca.extensions["sqlalchemy"].db.session
			except (KeyError, AttributeError):
				pass
		if _session is None:
			raise ValueError(
				"No session available — pass session= or use within a Flask app context."
			)

		try:
			results: list[Any] = []
			tenant_col = cls.__tenant_field__

			if operation == "create":
				instances = []
				for item in data:
					item.setdefault(tenant_col, effective_tenant)
					instances.append(cls(**item))
				_session.add_all(instances)
				results = instances

			elif operation == "update":
				for item in data:
					record_id = item.pop("id")
					instance = _session.get(cls, record_id)
					if instance is None:
						continue
					if getattr(instance, tenant_col) != effective_tenant:
						raise ValueError(
							f"Record {record_id} does not belong to tenant {effective_tenant}"
						)
					for key, value in item.items():
						setattr(instance, key, value)
					results.append(instance)

			elif operation == "delete":
				ids = [item["id"] for item in data]
				tenant_filter = getattr(cls, tenant_col) == effective_tenant
				rows = (
					_session.execute(
						select(cls).where(cls.id.in_(ids)).where(tenant_filter)
					)
					.scalars()
					.all()
				)
				for row in rows:
					_session.delete(row)
				results = rows

			else:
				raise ValueError(
					f"Unknown bulk operation '{operation}'. "
					"Expected one of: create, update, delete."
				)

			_session.commit()
			return results

		except Exception:
			_session.rollback()
			raise

	# ------------------------------------------------------------------
	# Statistics
	# ------------------------------------------------------------------

	@classmethod
	def get_tenant_statistics(
		cls,
		tenant_id: uuid.UUID | str | None = None,
		session: Session | None = None,
	) -> dict[str, Any]:
		"""
		Return basic statistics for the model within a given tenant.

		Args:
			tenant_id: Tenant to query; defaults to current context tenant.
			session: SA session; auto-resolved from FAB db extension when None.

		Returns:
			Dict with keys:
			  - ``total_records``: int row count
			  - ``last_updated``: datetime | None of the most-recently-updated row
			  - ``metadata_keys``: list of distinct top-level extra_metadata keys
			    (Postgres only; empty list on other backends)
		"""
		effective_tenant = tenant_id or cls.get_current_tenant_id()

		_session = session
		if _session is None:
			try:
				from flask import current_app as ca

				_session = ca.extensions["sqlalchemy"].db.session
			except (KeyError, AttributeError):
				pass
		if _session is None:
			raise ValueError("No session available.")

		tenant_col = getattr(cls, cls.__tenant_field__)

		total = _session.execute(
			select(func.count()).select_from(cls).where(tenant_col == effective_tenant)
		).scalar_one()

		last_updated_row = _session.execute(
			select(cls.updated_at)
			.where(tenant_col == effective_tenant)
			.order_by(cls.updated_at.desc())
			.limit(1)
		).scalar_one_or_none()

		# JSONB key enumeration is Postgres-specific
		metadata_keys: list[str] = []
		if _PG_AVAILABLE and hasattr(cls, "extra_metadata"):
			try:
				from sqlalchemy.dialects.postgresql import array_agg

				rows = _session.execute(
					select(func.jsonb_object_keys(cls.extra_metadata).distinct())
					.where(tenant_col == effective_tenant)
				).scalars().all()
				metadata_keys = list(rows)
			except Exception:
				pass  # Non-Postgres or missing jsonb_object_keys

		return {
			"total_records": total,
			"last_updated": last_updated_row,
			"metadata_keys": metadata_keys,
		}


class TenantScopedSQLAInterface(SQLAInterface):
	"""
	Flask-AppBuilder ``SQLAInterface`` subclass that automatically scopes
	all queries to the active tenant when the backing model inherits from
	``MultiTenancyMixin``.

	Drop-in replacement::

		class ProductModelView(ModelView):
			datamodel = TenantScopedSQLAInterface(Product)
	"""

	def query(self, filters=None, order_column: str = "", order_direction: str = ""):
		"""Delegate to parent then narrow to tenant if model is multi-tenant."""
		query = super().query(filters, order_column, order_direction)
		if issubclass(self.obj, MultiTenancyMixin):
			cache_key = f"interface_query_{self.obj.__name__}_{filters}"
			if self.obj.__cache_enabled__:
				cache = getattr(current_app, "cache", None)
				if cache is not None:
					cached = cache.get(cache_key)
					if cached is not None:
						return cached

			query = self.obj.get_tenant_query(query)

			if self.obj.__cache_enabled__:
				cache = getattr(current_app, "cache", None)
				if cache is not None:
					cache.set(cache_key, query)

		return query
