"""
pgappforge/security/providers/decorators.py

Provider-agnostic permission and role decorators.
Work transparently across FAB, Keycloak, Clerk, BetterAuth, and SpiceDB.
"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Callable, Any

log = logging.getLogger(__name__)


def require_permission(resource: str, action: str = "can_access"):
	"""Require a permission on any configured auth provider.

	Works with FAB RBAC, Keycloak/Clerk/BetterAuth role mappings, and SpiceDB.

	Usage::
	    @require_permission("Invoice", "can_create")
	    def create_invoice(): ...

	    # SpiceDB resource-instance check:
	    @require_permission("invoice", "can_edit")
	    def edit_invoice(invoice_id): ...
	"""
	def decorator(fn: Callable) -> Callable:
		@wraps(fn)
		def wrapper(*args: Any, **kwargs: Any) -> Any:
			from flask import g, abort

			auth_user = getattr(g, "auth_user", None)
			if auth_user is not None:
				# SpiceDB check takes precedence when configured
				from pgappforge.security.providers.spicedb import get_authz_provider
				authz = get_authz_provider()
				if authz is not None:
					# Resolve resource_id from kwargs if template uses "resource:param"
					if ":" in resource:
						rtype, param = resource.split(":", 1)
						rid = str(kwargs.get(param, ""))
					else:
						rtype, rid = resource, resource
					if not authz.check_permission("user", auth_user.user_id, rtype, rid, action):
						abort(403)
					return fn(*args, **kwargs)

				# Provider-level permission check
				allowed = (
					action in auth_user.permissions
					or f"{action}_{resource}" in auth_user.permissions
					or any(r in ("admin", "Admin", "superuser") for r in auth_user.roles)
				)
				if not allowed:
					abort(403)
				return fn(*args, **kwargs)

			# Fall back to FAB has_access (covers browser sessions)
			try:
				from flask import current_app
				if not current_app.appbuilder.sm.has_access(action, resource):
					abort(403)
			except Exception:
				abort(403)
			return fn(*args, **kwargs)

		return wrapper
	return decorator


def require_role(*roles: str):
	"""Require at least one of the specified roles.

	Works with g.auth_user (API requests) and flask_login (browser sessions).

	Usage::
	    @require_role("Admin", "FinanceManager")
	    def approve_budget(): ...
	"""
	def decorator(fn: Callable) -> Callable:
		@wraps(fn)
		def wrapper(*args: Any, **kwargs: Any) -> Any:
			from flask import g, abort

			auth_user = getattr(g, "auth_user", None)
			if auth_user is not None:
				if not any(r in auth_user.roles for r in roles):
					abort(403)
				return fn(*args, **kwargs)

			# FAB / flask_login fallback
			try:
				from flask_login import current_user
				user_role_names = {role.name for role in getattr(current_user, "roles", [])}
				if not any(r in user_role_names for r in roles):
					abort(403)
			except Exception:
				abort(403)
			return fn(*args, **kwargs)

		return wrapper
	return decorator


__all__ = ["require_permission", "require_role"]
