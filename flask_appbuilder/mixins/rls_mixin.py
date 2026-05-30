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
	TTLCache = None

from flask import current_app, g, request
from flask_appbuilder import Model
from sqlalchemy import (
	JSON,
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Integer,
	String,
	Table,
	and_,
	event,
	func,
	or_,
	select,
)
from sqlalchemy.orm import Session, relationship
from sqlalchemy.orm.attributes import flag_modified

# SQLAlchemy 2.x mapped_column / Mapped — fall back gracefully on 1.x installs
try:
	from sqlalchemy.orm import Mapped, mapped_column
	_SA2 = True
except ImportError:
	_SA2 = False

# JSONB / ARRAY are PostgreSQL-specific; fall back to JSON for other databases
try:
	from sqlalchemy.dialects.postgresql import ARRAY, JSONB as _JSONB
	_AUDIT_CHANGES_TYPE = _JSONB
except ImportError:
	_AUDIT_CHANGES_TYPE = JSON

try:
	from sqlalchemy.inspection import inspect as sa_inspect
except ImportError:
	from sqlalchemy import inspect as sa_inspect

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Audit log table — registered against Flask-AppBuilder's shared metadata
# ---------------------------------------------------------------------------
rls_audit_log = Table(
	"rls_audit_log",
	Model.metadata,
	Column("id", Integer, primary_key=True),
	Column("timestamp", DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)),
	Column("action", String(50), nullable=False),
	Column("user_id", Integer, ForeignKey("ab_user.id"), nullable=False),
	Column("model", String(100), nullable=False),
	Column("item_id", Integer),
	Column("organization_id", Integer),
	Column("changes", _AUDIT_CHANGES_TYPE),
	Column("ip_address", String(50)),
	Column("user_agent", String(200)),
)


# ---------------------------------------------------------------------------
# Cache — uses cachetools when available, falls back to a plain dict LRU stub
# ---------------------------------------------------------------------------
class _SimpleTTLCache:
	"""Minimal TTL-less LRU-style dict used when cachetools is not installed."""

	def __init__(self, maxsize: int = 1000, ttl: int = 300) -> None:
		self._store: dict[str, Any] = {}
		self._maxsize = maxsize

	def get(self, key: str) -> Any | None:
		return self._store.get(key)

	def __setitem__(self, key: str, value: Any) -> None:
		if len(self._store) >= self._maxsize:
			# Evict oldest key
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


class RLSFilterCache:
	"""Cache for RLS filter results keyed by (user_id, model_name, org_id)."""

	def __init__(self, maxsize: int = 1000, ttl: int = 300) -> None:
		self._cache = _make_cache(maxsize=maxsize, ttl=ttl)

	def _key(self, user_id: int, model: str, org_id: int | None = None) -> str:
		return f"{user_id}:{model}:{org_id or 'all'}"

	def get(self, user_id: int, model: str, org_id: int | None = None) -> list[Any] | None:
		return self._cache.get(self._key(user_id, model, org_id))

	def set(self, user_id: int, model: str, filters: list[Any], org_id: int | None = None) -> None:
		self._cache[self._key(user_id, model, org_id)] = filters

	def invalidate(self, user_id: int | None = None, model: str | None = None) -> None:
		if user_id and model:
			self._cache.pop(self._key(user_id, model), None)
		else:
			self._cache.clear()


# ---------------------------------------------------------------------------
# Main mixin
# ---------------------------------------------------------------------------
class RowLevelSecurityMixin:
	"""
	Advanced Row Level Security (RLS) Mixin for Flask-AppBuilder ModelViews.

	Provides sophisticated access control at the row level through:
	- Multi-tenant organisation isolation
	- Hierarchical role-based permissions
	- Customisable business rules
	- Dynamic ownership models
	- Temporal access controls

	Features:
	- Automatic query filtering based on user context
	- Fine-grained organisation/tenant isolation
	- Hierarchical role-based access control
	- Custom security rules engine
	- Comprehensive audit logging
	- High-performance caching (cachetools when available, plain dict fallback)
	- Bulk operation security
	- Exception handling and recovery
	- Configurable fallback policies
	- Performance optimisations via permission caching
	- Temporal access control (opt-in)
	- Security event webhooks via SECURITY_WEBHOOKS config list
	- Access analytics / audit trail

	Configuration class attributes:
		organisation_field: str    — column storing org/tenant ID (default "organisation_id")
		owner_field: str           — column tracking record ownership (default "created_by")
		parent_field: str          — column for hierarchical org parent (default "parent_id")
		enable_audit: bool         — enable audit logging (default True)
		enable_caching: bool       — enable permission caching (default True)
		cache_ttl: int             — cache timeout in seconds (default 300)
		strict_mode: bool          — raise on RLS errors instead of falling back (default True)
		fallback_policy: str       — "deny" | "allow" | "custom" (default "deny")
		temporal_control: bool     — time-based access via valid_from/valid_to (default False)
		enable_delegation: bool    — honour delegated_orgs on the user object (default False)
		track_inheritance: bool    — expand permitted orgs to include sub-orgs (default True)
		enable_analytics: bool     — fire security webhooks on each audited action (default True)
		custom_rules: list[Callable] — callables(model_class, user) -> SQLAlchemy clause | None
		role_filters: dict[str, list[Callable] | None]
	"""

	# Core configuration
	organisation_field: str = "organisation_id"
	owner_field: str = "created_by"
	parent_field: str = "parent_id"
	enable_audit: bool = True
	enable_caching: bool = True
	cache_ttl: int = 300
	strict_mode: bool = True
	fallback_policy: str = "deny"

	# Advanced features
	temporal_control: bool = False
	enable_delegation: bool = False
	track_inheritance: bool = True
	enable_analytics: bool = True

	# Security rules — override in subclasses
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

	# Class-level cache shared across all instances of a given subclass
	_filter_cache: RLSFilterCache = RLSFilterCache()

	def __init__(self) -> None:
		super().__init__()
		self._setup_audit_hooks()
		self._init_cache()

	# ------------------------------------------------------------------
	# Initialisation helpers
	# ------------------------------------------------------------------

	def _setup_audit_hooks(self) -> None:
		"""Register SQLAlchemy event listeners for audit logging."""
		if self.enable_audit:
			event.listen(self.__class__, "after_insert", self._audit_insert)
			event.listen(self.__class__, "after_update", self._audit_update)
			event.listen(self.__class__, "after_delete", self._audit_delete)

	def _init_cache(self) -> None:
		"""Initialise per-instance permission cache."""
		if self.enable_caching:
			self._permission_cache = _make_cache(maxsize=1000, ttl=self.cache_ttl)

	# ------------------------------------------------------------------
	# Organisation hierarchy resolution
	# ------------------------------------------------------------------

	def get_organisation_hierarchy(self, org_id: int) -> set[int]:
		"""
		Return org_id plus the IDs of every recursively nested child organisation.

		Uses SQLAlchemy 2.x ``session.execute(select(...))`` internally; falls
		back to the legacy ``session.query(...)`` API on SQLAlchemy 1.x.
		"""
		orgs: set[int] = {org_id}
		try:
			model_cls = self.datamodel.obj
			session: Session = self.datamodel.session

			# Try SA 2.x style first
			try:
				stmt = select(model_cls).where(
					getattr(model_cls, self.parent_field) == org_id
				)
				children = session.execute(stmt).scalars().all()
			except TypeError:
				# SA 1.x fallback
				children = (
					session.query(model_cls)
					.filter(getattr(model_cls, self.parent_field) == org_id)
					.all()
				)

			for child in children:
				orgs.update(self.get_organisation_hierarchy(child.id))

		except Exception:
			logger.exception("Error resolving organisation hierarchy for org_id=%s", org_id)

		return orgs

	# ------------------------------------------------------------------
	# Core RLS query filter
	# ------------------------------------------------------------------

	def query_rls(self, query: Any) -> Any:
		"""
		Apply all applicable RLS filters to *query* and return the filtered query.

		Checks (in order):
		1. Presence of user context — raises or falls back per strict_mode / fallback_policy
		2. Admin bypass
		3. Organisation/tenant filter (with optional sub-org expansion)
		4. Role-based filters
		5. Custom security rules
		6. Temporal filters (when temporal_control is True)

		Results are cached per (user_id, model_name) when enable_caching is True.
		"""
		if not hasattr(g, "user"):
			if self.strict_mode:
				raise RuntimeError("No user context available for RLS")
			logger.warning("No user context for RLS — applying fallback policy '%s'", self.fallback_policy)
			return self._apply_fallback_policy(query)

		try:
			# Admin bypass
			if hasattr(g.user, "is_admin") and g.user.is_admin():
				return query

			# Check cache
			if self.enable_caching:
				cached_filters = self._filter_cache.get(g.user.id, self.__class__.__name__)
				if cached_filters is not None:
					return query.filter(and_(*cached_filters))

			filters: list[Any] = []

			# ---- Organisation/tenant filter ----
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
			role_filters = self.get_role_filters()
			if role_filters:
				filters.extend(role_filters)

			# ---- Custom security rules ----
			custom_filters = self.get_custom_filters()
			if custom_filters:
				filters.extend(custom_filters)

			# ---- Temporal filters ----
			if self.temporal_control:
				temporal_filter = self._get_temporal_filter()
				if temporal_filter is not None:
					filters.append(temporal_filter)

			if filters:
				query = query.filter(and_(*filters))
				if self.enable_caching:
					self._filter_cache.set(g.user.id, self.__class__.__name__, filters)

			return query

		except Exception as exc:
			logger.exception("Error applying RLS filters")
			if self.strict_mode:
				raise RuntimeError(f"RLS filter error: {exc}") from exc
			return self._apply_fallback_policy(query)

	def _apply_fallback_policy(self, query: Any) -> Any:
		"""Apply the configured fallback security policy."""
		if self.fallback_policy == "deny":
			return query.filter(False)
		elif self.fallback_policy == "allow":
			return query
		else:
			return self._apply_custom_fallback(query)

	def _apply_custom_fallback(self, query: Any) -> Any:
		"""Override to implement a custom fallback policy."""
		return query.filter(False)

	def _get_temporal_filter(self) -> Any | None:
		"""
		Build a time-window filter using ``valid_from`` / ``valid_to`` columns.

		Returns None if neither column exists on the model.
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
	# Permission resolution helpers
	# ------------------------------------------------------------------

	def get_permitted_orgs(self) -> list[int]:
		"""
		Collect all organisation IDs the current user is permitted to access.

		Sources (in order):
		- Direct organisation field on the user object
		- Organisations via roles/groups (user.organisations)
		- Delegated organisations (when enable_delegation is True)
		"""
		if not hasattr(g, "user"):
			return []

		orgs: list[int] = []

		if hasattr(g.user, self.organisation_field):
			org_id = getattr(g.user, self.organisation_field)
			if org_id is not None:
				orgs.append(org_id)

		if hasattr(g.user, "organisations"):
			orgs.extend(org.id for org in g.user.organisations)

		if self.enable_delegation and hasattr(g.user, "delegated_orgs"):
			orgs.extend(org.id for org in g.user.delegated_orgs)

		# Deduplicate, preserve order
		return list(dict.fromkeys(orgs))

	def get_role_filters(self) -> list[Any]:
		"""
		Evaluate role-based filter callables for each of the current user's roles.

		Each callable receives (model_class, user) and should return an
		SQLAlchemy clause expression or None.  Duplicate rules (by object
		identity) are evaluated only once.
		"""
		if not hasattr(g, "user") or not hasattr(g.user, "roles"):
			return []

		filters: list[Any] = []
		seen_rules: set[int] = set()

		for role in g.user.roles:
			role_rules = self.role_filters.get(role.name)
			if not role_rules:
				continue
			for rule in role_rules:
				rule_key = id(rule)
				if rule_key in seen_rules:
					continue
				seen_rules.add(rule_key)
				try:
					clause = rule(self.datamodel.obj, g.user)
					if clause is not None:
						filters.append(clause)
				except Exception:
					logger.exception("Role filter rule error for role '%s'", role.name)
					if self.strict_mode:
						raise

		return filters

	def get_custom_filters(self) -> list[Any]:
		"""
		Evaluate custom_rules callables.

		Each callable receives (model_class, user) and should return an
		SQLAlchemy clause expression or None.
		"""
		filters: list[Any] = []
		for rule in self.custom_rules:
			try:
				clause = rule(self.datamodel.obj, g.user)
				if clause is not None:
					filters.append(clause)
			except Exception as exc:
				logger.error("Custom RLS rule error: %s", exc)
				if self.strict_mode:
					raise

		return filters

	# ------------------------------------------------------------------
	# View hook overrides
	# ------------------------------------------------------------------

	def get_query(self) -> Any:
		"""Override ModelView.get_query to apply RLS filtering."""
		query = super().get_query()
		return self.query_rls(query)

	def pre_add(self, item: Any) -> None:
		"""
		Enforce RLS on add: verify organisation access and stamp ownership /
		timestamp fields.
		"""
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
		"""
		Enforce RLS on update: verify organisation access and stamp update
		timestamp fields.
		"""
		super().pre_update(item)
		self._require_user_context()
		self._verify_org_access(item)

		if hasattr(item, "updated_at"):
			item.updated_at = datetime.now(timezone.utc)
		if hasattr(item, "updated_by"):
			item.updated_by = g.user.id

		self._audit_log("update", item)

	def pre_delete(self, item: Any) -> None:
		"""Enforce RLS on delete: verify organisation access."""
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
		"""Raise PermissionError if the item's org is not in the permitted set."""
		if not hasattr(item, self.organisation_field):
			return
		org_id = getattr(item, self.organisation_field)
		if org_id is None:
			return
		permitted = self.get_permitted_orgs()
		if permitted and org_id not in permitted:
			raise PermissionError(
				f"Not authorised for organisation {org_id}. "
				f"Permitted: {permitted}"
			)

	# ------------------------------------------------------------------
	# Audit logging
	# ------------------------------------------------------------------

	def _audit_log(self, action: str, item: Any) -> None:
		"""
		Write an audit log entry for *action* on *item*.

		Change tracking uses SQLAlchemy's instance state inspection to capture
		before/after values for update and delete actions.

		Silently ignores failures unless strict_mode is True.
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
			}

			self.datamodel.session.execute(rls_audit_log.insert(), [log_entry])

			if self.enable_analytics:
				self._notify_security_webhooks(log_entry)

		except Exception as exc:
			logger.error("Audit logging error: %s", exc)
			if self.strict_mode:
				raise

	# SQLAlchemy event listener stubs — bound in _setup_audit_hooks
	@staticmethod
	def _audit_insert(mapper: Any, connection: Any, target: Any) -> None:
		logger.debug("RLS audit: insert %s id=%s", target.__class__.__name__, getattr(target, "id", None))

	@staticmethod
	def _audit_update(mapper: Any, connection: Any, target: Any) -> None:
		logger.debug("RLS audit: update %s id=%s", target.__class__.__name__, getattr(target, "id", None))

	@staticmethod
	def _audit_delete(mapper: Any, connection: Any, target: Any) -> None:
		logger.debug("RLS audit: delete %s id=%s", target.__class__.__name__, getattr(target, "id", None))

	# ------------------------------------------------------------------
	# Webhook notification
	# ------------------------------------------------------------------

	def _notify_security_webhooks(self, log_entry: dict[str, Any]) -> None:
		"""
		POST the audit log entry to each URL listed in SECURITY_WEBHOOKS config.

		``SECURITY_WEBHOOKS`` should be a list of dicts with at least a ``url``
		key.  Requires the ``requests`` package to be installed; logs a warning
		and skips gracefully if it is absent.

		Individual webhook failures are logged but do not abort the operation.
		"""
		try:
			import requests as _requests
		except ImportError:
			logger.warning(
				"'requests' package not installed — skipping security webhook notifications"
			)
			return

		try:
			webhooks: list[dict[str, Any]] = current_app.config.get("SECURITY_WEBHOOKS", [])
			# Serialise datetime/set values for JSON
			safe_entry = json.loads(json.dumps(log_entry, default=str))
			for webhook in webhooks:
				url = webhook.get("url")
				if not url:
					continue
				try:
					_requests.post(url, json=safe_entry, timeout=5)
				except _requests.exceptions.RequestException as exc:
					logger.error(
						"Security webhook POST failed for URL '%s': %s", url, exc
					)
		except Exception as exc:
			logger.error("Security webhook notification error: %s", exc)


"""
Usage Example
=============

from flask_appbuilder import Model, ModelView
from flask_appbuilder.models.mixins import AuditMixin
from flask_appbuilder.models.sqla.interface import SQLAInterface
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from flask_appbuilder.mixins.rls_mixin import RowLevelSecurityMixin


class Organisation(Model):
	__tablename__ = "organisations"
	id = Column(Integer, primary_key=True)
	name = Column(String(50), unique=True, nullable=False)
	parent_id = Column(Integer, ForeignKey("organisations.id"))

	parent = relationship("Organisation", remote_side=[id])
	children = relationship("Organisation")


class Department(Model):
	__tablename__ = "departments"
	id = Column(Integer, primary_key=True)
	name = Column(String(50), nullable=False)
	organisation_id = Column(Integer, ForeignKey("organisations.id"))

	organisation = relationship("Organisation")


class Document(Model, AuditMixin):
	__tablename__ = "documents"
	id = Column(Integer, primary_key=True)
	title = Column(String(100), nullable=False)
	content = Column(String(1000))
	department_id = Column(Integer, ForeignKey("departments.id"))
	organisation_id = Column(Integer, ForeignKey("organisations.id"))
	status = Column(String(20))

	department = relationship("Department")
	organisation = relationship("Organisation")


def user_in_department(obj, user):
	return obj.department_id in [d.id for d in user.departments]


class DocumentModelView(RowLevelSecurityMixin, ModelView):
	datamodel = SQLAInterface(Document)

	organisation_field = "organisation_id"
	enable_audit = True
	strict_mode = True

	custom_rules = [user_in_department]

	role_filters = {
		"admin": None,
		"manager": [
			lambda obj, user: obj.department_id in user.managed_departments,
		],
		"user": [
			lambda obj, user: obj.department_id == user.department_id,
			lambda obj, user: obj.status == "public",
		],
	}


# Register with Flask-AppBuilder
appbuilder.add_view(
	DocumentModelView,
	"Documents",
	icon="fa-file-text-o",
	category="Documents",
)
"""
