"""
pgappforge/multitenancy/middleware.py

Flask before/after-request hooks that set and clear the PostgreSQL
``app.tenant_id`` session variable on every HTTP request.

Tenant ID resolution order
---------------------------
1. ``X-Tenant-ID`` request header  (API clients, service-to-service calls)
2. ``current_user.tenant_id``      (authenticated browser sessions)
3. ``DEFAULT_TENANT_ID`` in Flask config  (single-tenant deployments)

The resolved ID is stored in ``flask.g.tenant_id`` for the request lifetime
and used to call :func:`~pgappforge.multitenancy.rls.set_tenant_context`.

Usage
-----
::

    from pgappforge.multitenancy.middleware import setup_tenant_middleware

    # With Flask-SQLAlchemy db object:
    setup_tenant_middleware(app, db_session_factory=db.session)

    # With AppBuilder session:
    setup_tenant_middleware(app)   # resolves via appbuilder.get_session()
"""
from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal resolver
# ---------------------------------------------------------------------------

def _resolve_tenant_id() -> str | None:
	"""Extract tenant ID from the current request context.

	Returns None if no tenant can be determined (anonymous / unauthenticated
	requests will see zero rows in RLS-protected tables).
	"""
	try:
		from flask import request, current_app

		# 1. Explicit header (service-to-service or API client)
		header_tid = request.headers.get("X-Tenant-ID")
		if header_tid:
			return header_tid.strip()

		# 2. Authenticated user's tenant_id attribute
		try:
			from flask_login import current_user	# type: ignore[import]
			if current_user and current_user.is_authenticated:
				tid = getattr(current_user, "tenant_id", None)
				if tid:
					return str(tid)
		except ImportError:
			pass

		# 3. App-level default (single-tenant / dev deployments)
		return current_app.config.get("DEFAULT_TENANT_ID")

	except Exception as exc:
		log.debug("multitenancy: tenant resolution error: %s", exc)
		return None


# ---------------------------------------------------------------------------
# Session factory helpers
# ---------------------------------------------------------------------------

def _get_session(db_session_factory: Any | None, app: Any) -> Any | None:
	"""Return a usable SQLAlchemy session/connection for the current request."""
	if db_session_factory is not None:
		# Caller supplied Flask-SQLAlchemy db.session (a scoped proxy)
		return db_session_factory

	# Try to get it from AppBuilder
	try:
		from flask import current_app
		ab = getattr(current_app, "appbuilder", None)
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
	except Exception:
		pass

	return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_tenant_middleware(
	app: Any,
	db_session_factory: Any = None,
) -> None:
	"""Register before/after-request hooks for tenant context management.

	Parameters
	----------
	app:
		Flask application instance.
	db_session_factory:
		Optional: a SQLAlchemy scoped session (e.g. ``db.session`` from
		Flask-SQLAlchemy).  When None, the middleware attempts to resolve
		it from ``current_app.appbuilder.get_session``.
	"""

	@app.before_request
	def _set_tenant_context() -> None:
		from flask import g
		from pgappforge.multitenancy.rls import set_tenant_context

		tid = _resolve_tenant_id()
		g.tenant_id = tid	# always set (even if None) for downstream reads

		if not tid:
			return

		session = _get_session(db_session_factory, app)
		if session is None:
			log.debug("multitenancy: no session available to set tenant context")
			return

		try:
			set_tenant_context(session, tid)
		except Exception as exc:
			# Log but don't abort the request — fail-open on context set,
			# but RLS will block data access if tenant_id is missing.
			log.debug("multitenancy: set_tenant_context failed: %s", exc)

	log.info("multitenancy: tenant middleware registered on %s", app.name)


def get_current_tenant_id() -> str | None:
	"""Return the tenant ID resolved for the current request.

	Returns None outside a request context or when no tenant was identified.
	"""
	try:
		from flask import g
		return getattr(g, "tenant_id", None)
	except RuntimeError:
		# Called outside Flask application context
		return None


def require_tenant(f: Callable) -> Callable:
	"""View decorator that returns 403 when no tenant context is set.

	Use on views that absolutely require a tenant (e.g. tenant-specific
	dashboards) rather than silently returning empty data.
	"""
	import functools

	@functools.wraps(f)
	def _wrapper(*args: Any, **kwargs: Any) -> Any:
		if get_current_tenant_id() is None:
			from flask import abort
			abort(403, description="Tenant context required.")
		return f(*args, **kwargs)

	return _wrapper


__all__ = [
	"setup_tenant_middleware",
	"get_current_tenant_id",
	"require_tenant",
]
