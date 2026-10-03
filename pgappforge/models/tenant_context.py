"""
Multi-Tenant Context Management.

Handles tenant identification, context management, and request-scoped
tenant isolation for PgForge multi-tenant applications.
"""

import contextvars
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from functools import wraps
from typing import Optional, Callable, Any, TypeVar
from contextlib import contextmanager

from flask import g, has_app_context, has_request_context, request, jsonify, current_app
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

log = logging.getLogger(__name__)

T = TypeVar("T")

# Diagnostic-only cache ceiling; the health check flags oversize as a leak.
_TENANT_CACHE_MAX = 256


@dataclass(frozen=True)
class TenantScope:
	"""Immutable snapshot of the active tenant for one execution context.

	Carries more than the id: ``is_system`` marks a deliberate cross-tenant
	scope (batch jobs), ``scope_id`` identifies this particular scope so logs
	and audit rows can be correlated, ``created_at`` is an epoch timestamp
	used for staleness checks.
	"""

	tenant_id: int | None
	slug: str | None = None
	is_system: bool = False
	scope_id: str = field(default_factory=lambda: uuid.uuid4().hex)
	created_at: float = field(default_factory=time.time)


# Single source of truth for tenant identity.  Unlike ``flask.g`` this travels
# with ``contextvars.copy_context()`` into worker threads and asyncio tasks,
# and is isolated per context rather than shared.
_tenant_scope: contextvars.ContextVar[TenantScope | None] = (
	contextvars.ContextVar("pgappforge_tenant_scope", default=None)
)


def get_tenant_scope() -> TenantScope | None:
	"""Return the tenant scope bound to the current context, if any."""
	return _tenant_scope.get()


def set_tenant_scope(
	tenant_id: int | None,
	slug: str | None = None,
	is_system: bool = False,
) -> contextvars.Token:
	"""Bind a new :class:`TenantScope` to the current context; return its token."""
	return _tenant_scope.set(
		TenantScope(tenant_id=tenant_id, slug=slug, is_system=is_system)
	)


def reset_tenant_scope(token: contextvars.Token) -> None:
	"""Restore the scope captured by *token*."""
	_tenant_scope.reset(token)


def run_with_tenant(tenant_id: int | None, fn: Callable[[], T]) -> T:
	"""Run *fn* with *tenant_id* bound, restoring the previous scope on exit.

	Pass ``None`` to run *fn* with no tenant scope at all (reads then fall
	through to ``flask.g``).
	"""
	if tenant_id is None:
		token = _tenant_scope.set(None)
	else:
		token = set_tenant_scope(tenant_id)
	try:
		return fn()
	finally:
		_tenant_scope.reset(token)


def _resolve_work_app(app: Any | None) -> Any | None:
	"""Return a real app object for *app*, or the active one when inside a context."""
	if app is not None:
		return app
	if has_app_context():
		return current_app._get_current_object()
	return None


def work_item(
	tenant_id: int,
	fn: Callable[[], T],
	app: Any | None = None,
) -> Callable[[], T]:
	"""Wrap *fn* so it runs with tenant *tenant_id* on any thread or task.

	The wrapper re-establishes a Flask application context (from *app*, or
	from the ambient context when called inside one) and binds the tenant
	ContextVar inside a copied context, so the caller's own context is left
	untouched.

	``app`` is required when the wrapper is built outside an application
	context — otherwise the worker thread has nothing to push.
	"""
	resolved = _resolve_work_app(app)
	if resolved is None:
		raise RuntimeError(
			"work_item() requires app=... when no Flask application context is active"
		)

	def _run() -> T:
		# Everything happens inside the copied context, including the app
		# context push — pushing outside it would be invisible to fn.
		ctx = contextvars.copy_context()

		def _body() -> T:
			set_tenant_scope(tenant_id)
			with resolved.app_context():
				return fn()

		return ctx.run(_body)

	return _run


class TenantOperationError(Exception):
	"""Exception raised when tenant operations fail."""
	def __init__(self, message: str, original_error: Exception = None):
		super().__init__(message)
		self.original_error = original_error


@contextmanager
def tenant_operation_boundary(operation_name: str):
	"""Error boundary for tenant operations to prevent cascading failures."""
	try:
		yield
	except Exception as e:
		log.error(f"Tenant operation '{operation_name}' failed: {str(e)}", exc_info=True)
		
		# Clear potentially corrupted tenant context
		try:
			_tenant_scope.set(None)
			if hasattr(g, 'current_tenant_id'):
				delattr(g, 'current_tenant_id')
			if hasattr(g, 'current_tenant'):
				delattr(g, 'current_tenant')
		except Exception:
			pass  # Don't fail on cleanup failure
		
		# Send alert if monitoring system is available
		try:
			if current_app and hasattr(current_app, 'extensions') and 'monitoring_system' in current_app.extensions:
				monitoring = current_app.extensions['monitoring_system']
				monitoring.send_alert(f"Tenant operation failure: {operation_name}", str(e))
		except Exception as monitor_error:
			log.debug(f"Failed to send monitoring alert: {monitor_error}")
		
		# Re-raise as TenantOperationError for consistent handling
		raise TenantOperationError(f"Operation '{operation_name}' failed: {str(e)}", e)


class TenantContext:
	"""
	Manages current tenant context for requests.
	
	Provides tenant resolution from subdomains/custom domains,
	context management, and request-scoped tenant isolation.
	"""
	
	def __init__(self):
		# Diagnostic only — never read for correctness.  Lock-guarded because
		# the app is multi-threaded; bounded so it cannot become a leak.
		self._tenant_cache: dict[str, Any] = {}
		self._cache_lock = threading.Lock()

	def _cache_tenant(self, tenant) -> None:
		"""Record a tenant in the diagnostic cache (bounded, lock-guarded)."""
		with self._cache_lock:
			if len(self._tenant_cache) >= _TENANT_CACHE_MAX:
				del self._tenant_cache[next(iter(self._tenant_cache))]
			self._tenant_cache[f"tenant:{tenant.id}"] = tenant

	def get_current_tenant(self):
		"""Get current tenant: ContextVar scope first, then ``flask.g``, then host resolution."""
		scope = _tenant_scope.get()
		if scope is not None and scope.tenant_id is not None:
			return getattr(g, 'current_tenant', None) or self._tenant_by_id(scope.tenant_id)

		if has_app_context() and hasattr(g, 'current_tenant'):
			return g.current_tenant

		if not has_request_context():
			return None

		# Try to resolve from request
		tenant = self._resolve_tenant_from_request()
		if tenant:
			g.current_tenant = tenant
			g.current_tenant_id = tenant.id

		return tenant

	def get_current_tenant_id(self) -> Optional[int]:
		"""Get current tenant ID: ContextVar scope first, then ``flask.g``, then host resolution."""
		scope = _tenant_scope.get()
		if scope is not None and scope.tenant_id is not None:
			return scope.tenant_id

		if has_app_context() and hasattr(g, 'current_tenant_id'):
			return g.current_tenant_id

		tenant = self.get_current_tenant()
		return tenant.id if tenant else None

	def set_tenant_context(self, tenant):
		"""Set tenant context for the current context and request.

		Writes ``g.current_tenant`` / ``g.current_tenant_id`` for backward
		compatibility and binds the ContextVar so the tenant survives a
		thread or task hop.
		"""
		g.current_tenant = tenant
		g.current_tenant_id = tenant.id
		set_tenant_scope(tenant.id, slug=getattr(tenant, 'slug', None))
		self._cache_tenant(tenant)

		log.debug(f"Set tenant context: {tenant.slug} (ID: {tenant.id})")

	def clear_tenant_context(self):
		"""Clear tenant context from the current context and request."""
		_tenant_scope.set(None)
		if not has_app_context():
			return
		if hasattr(g, 'current_tenant'):
			delattr(g, 'current_tenant')
		if hasattr(g, 'current_tenant_id'):
			delattr(g, 'current_tenant_id')

	def _resolve_tenant_from_request(self):
		"""Resolve tenant from request subdomain or custom domain.

		Host is the only accepted signal.  There is no header or query-string
		override: accepting one would let a caller claim any tenant on any
		host, which is a tenant-id oracle rather than a developer convenience.
		"""
		if not has_request_context():
			return None

		host = request.host.lower()

		# Check for custom domain first
		tenant = self._get_tenant_by_custom_domain(host)
		if tenant:
			log.debug(f"Resolved tenant {tenant.slug} from custom domain: {host}")
			return tenant

		# Check for subdomain pattern: {tenant}.yourdomain.com
		tenant = self._get_tenant_by_subdomain(host)
		if tenant:
			log.debug(f"Resolved tenant {tenant.slug} from subdomain: {host}")
			return tenant

		log.warning(f"Could not resolve tenant from host: {host}")
		return None

	def _tenant_by_id(self, tenant_id: int):
		"""Look up a tenant row by id (used when only the ContextVar survived)."""
		try:
			from .tenant_models import Tenant
			return Tenant.query.get(tenant_id)
		except Exception as exc:
			log.debug("Tenant lookup by id failed for %r: %s", tenant_id, exc)
			return None

	def _get_tenant_by_custom_domain(self, host: str):
		"""Get tenant by custom domain"""
		from .tenant_models import Tenant
		
		# Remove port if present
		domain = host.split(':')[0]
		
		tenant = Tenant.query.filter_by(custom_domain=domain).first()
		return tenant if tenant and tenant.is_active else None
	
	def _get_tenant_by_subdomain(self, host: str):
		"""Get tenant by subdomain pattern"""
		from .tenant_models import Tenant
		
		# Remove port if present
		host_parts = host.split(':')[0].split('.')
		
		# Need at least 3 parts for subdomain: subdomain.domain.tld
		if len(host_parts) < 3:
			return None
		
		subdomain = host_parts[0]
		
		# Skip common subdomains
		if subdomain in ('www', 'api', 'admin', 'app', 'portal'):
			return None
		
		tenant = Tenant.query.filter_by(slug=subdomain).first()
		return tenant if tenant and tenant.is_active else None
	
	def require_tenant_context(self):
		"""Decorator to ensure tenant context is available"""
		def decorator(f: Callable) -> Callable:
			@wraps(f)
			def decorated_function(*args, **kwargs):
				tenant = self.get_current_tenant()
				if not tenant:
					if request.is_json:
						return jsonify({
							'error': 'No tenant context', 
							'code': 'TENANT_REQUIRED'
						}), 400
					else:
						raise BadRequest("No tenant context available")
				
				return f(*args, **kwargs)
			return decorated_function
		return decorator
	
	def require_active_tenant(self):
		"""Decorator to ensure tenant is active"""
		def decorator(f: Callable) -> Callable:
			@wraps(f)
			def decorated_function(*args, **kwargs):
				tenant = self.get_current_tenant()
				if not tenant:
					if request.is_json:
						return jsonify({
							'error': 'No tenant context', 
							'code': 'TENANT_REQUIRED'
						}), 400
					else:
						raise BadRequest("No tenant context available")
				
				if not tenant.is_active:
					if request.is_json:
						return jsonify({
							'error': 'Tenant is not active', 
							'code': 'TENANT_INACTIVE'
						}), 403
					else:
						raise Forbidden("Tenant is not active")
				
				return f(*args, **kwargs)
			return decorated_function
		return decorator
	
	def require_tenant_feature(self, feature_name: str):
		"""Decorator to require specific tenant feature"""
		def decorator(f: Callable) -> Callable:
			@wraps(f)
			def decorated_function(*args, **kwargs):
				tenant = self.get_current_tenant()
				if not tenant:
					if request.is_json:
						return jsonify({
							'error': 'No tenant context', 
							'code': 'TENANT_REQUIRED'
						}), 400
					else:
						raise BadRequest("No tenant context available")
				
				if not tenant.has_feature(feature_name):
					if request.is_json:
						return jsonify({
							'error': f'Feature {feature_name} not available', 
							'code': 'FEATURE_NOT_AVAILABLE'
						}), 403
					else:
						raise Forbidden(f"Feature {feature_name} not available in your plan")
				
				return f(*args, **kwargs)
			return decorated_function
		return decorator
	
	def with_tenant_context(self, tenant):
		"""Context manager to temporarily set tenant context"""
		class TenantContextManager:
			def __init__(self, context_manager, tenant):
				self.context_manager = context_manager
				self.tenant = tenant
				self.previous_tenant = None
				self.previous_tenant_id = None
				self.scope_token = None

			def __enter__(self):
				# Save current context
				self.previous_tenant = getattr(g, 'current_tenant', None)
				self.previous_tenant_id = getattr(g, 'current_tenant_id', None)

				# Set new context
				self.context_manager.set_tenant_context(self.tenant)
				self.scope_token = _tenant_scope.set(
					TenantScope(tenant_id=self.tenant.id, slug=getattr(self.tenant, 'slug', None))
				)
				return self.tenant

			def __exit__(self, exc_type, exc_val, exc_tb):
				# Restore previous context
				if self.scope_token is not None:
					_tenant_scope.reset(self.scope_token)
				if self.previous_tenant:
					g.current_tenant = self.previous_tenant
					g.current_tenant_id = self.previous_tenant_id
				else:
					self.context_manager.clear_tenant_context()
		
		return TenantContextManager(self, tenant)


# Global tenant context instance
tenant_context = TenantContext()


def get_current_tenant():
	"""Get current tenant from context"""
	return tenant_context.get_current_tenant()


def get_current_tenant_id() -> Optional[int]:
	"""Get current tenant ID from context"""
	return tenant_context.get_current_tenant_id()


def require_tenant_context():
	"""Decorator shortcut for requiring tenant context"""
	return tenant_context.require_tenant_context()


def require_active_tenant():
	"""Decorator shortcut for requiring active tenant"""
	return tenant_context.require_active_tenant()


def require_tenant_feature(feature_name: str):
	"""Decorator shortcut for requiring tenant feature"""
	return tenant_context.require_tenant_feature(feature_name)


def with_tenant_context(tenant):
	"""Context manager shortcut for tenant context"""
	return tenant_context.with_tenant_context(tenant)


class TenantAwareQuery:
	"""
	Enhanced query class with automatic tenant filtering.
	
	Provides safe database access with automatic tenant isolation
	to prevent cross-tenant data access.
	"""
	
	def __init__(self, model_class):
		self.model_class = model_class
		self.base_query = model_class.query
	
	def filter_by_tenant(self, tenant_id: int = None):
		"""Add tenant filter to query"""
		if tenant_id is None:
			tenant_id = get_current_tenant_id()
		
		if not tenant_id:
			raise ValueError("No tenant context available for query")
		
		if hasattr(self.model_class, 'tenant_id'):
			return self.base_query.filter(self.model_class.tenant_id == tenant_id)
		else:
			# Non-tenant-aware model, return as-is but log warning
			log.warning(f"Model {self.model_class.__name__} is not tenant-aware")
			return self.base_query
	
	def safe_get(self, record_id: int, tenant_id: int = None):
		"""Get record ensuring tenant isolation"""
		query = self.filter_by_tenant(tenant_id)
		record = query.filter(self.model_class.id == record_id).first()
		
		if not record:
			raise NotFound(f"{self.model_class.__name__} not found or access denied")
		
		return record
	
	def safe_get_or_404(self, record_id: int, tenant_id: int = None):
		"""Get record or raise 404 if not found/access denied"""
		return self.safe_get(record_id, tenant_id)
	
	def count_for_tenant(self, tenant_id: int = None) -> int:
		"""Count records for specific tenant"""
		query = self.filter_by_tenant(tenant_id)
		return query.count()


def create_tenant_aware_query(model_class):
	"""Create a tenant-aware query for a model"""
	return TenantAwareQuery(model_class)


class TenantMiddleware:
	"""
	Flask middleware for tenant context management.
	
	Automatically resolves and sets tenant context for each request
	based on subdomain or custom domain.
	"""
	
	def __init__(self, app=None):
		self.app = app
		if app:
			self.init_app(app)
	
	def init_app(self, app):
		"""Initialize middleware with Flask app"""
		app.before_request(self.before_request)
		app.teardown_request(self.teardown_request)
		
		# Store reference in app extensions
		if not hasattr(app, 'extensions'):
			app.extensions = {}
		app.extensions['tenant_middleware'] = self
	
	def before_request(self):
		"""Set tenant context before each request"""
		try:
			# Skip tenant resolution for certain paths
			if self._should_skip_tenant_resolution():
				return
			
			# Resolve tenant from request
			tenant = tenant_context.get_current_tenant()
			if tenant:
				log.debug(f"Request tenant context: {tenant.slug}")
			else:
				log.debug("No tenant context for request")
		
		except Exception as e:
			log.error(f"Error setting tenant context: {e}")
			# Don't break the request for tenant resolution errors
	
	def teardown_request(self, exception):
		"""Clean up tenant context after request"""
		try:
			tenant_context.clear_tenant_context()
		except Exception as e:
			log.error(f"Error clearing tenant context: {e}")
	
	def _should_skip_tenant_resolution(self) -> bool:
		"""Check if tenant resolution should be skipped for this request"""
		skip_paths = [
			'/health',
			'/status', 
			'/_health',
			'/static/',
			'/favicon.ico'
		]
		
		path = request.path
		return any(path.startswith(skip_path) for skip_path in skip_paths)


def init_tenant_middleware(app):
	"""Initialize tenant middleware for Flask app"""
	return TenantMiddleware(app)