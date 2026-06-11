"""
pgappforge/security/providers

Pluggable authentication and authorization provider abstraction.

Supported AUTH_PROVIDER values:
  "fab"         — Default. FAB built-in (DB, LDAP, OAuth, OpenID). Zero config.
  "keycloak"    — Keycloak OIDC. JWT validation via JWKS.
  "clerk"       — Clerk.dev JWT-based auth.
  "better_auth" — BetterAuth (betterauth.js) server integration.

Supported AUTHZ_PROVIDER values (layered on top of any AUTH_PROVIDER):
  "spicedb"     — SpiceDB / Authzed relationship-based access control.

Quick start::

  # app_factory.py
  from pgappforge.security.providers import get_security_manager_class

  appbuilder = AppBuilder(
      app, db.session,
      security_manager_class=get_security_manager_class(),
  )

  # app.config
  AUTH_PROVIDER = "keycloak"
  KEYCLOAK_SERVER_URL = "https://keycloak.example.com"
  KEYCLOAK_REALM = "myrealm"
  KEYCLOAK_CLIENT_ID = "pgappforge"
  KEYCLOAK_CLIENT_SECRET = "..."

  # Optional SpiceDB layered on top
  AUTHZ_PROVIDER = "spicedb"
  SPICEDB_ENDPOINT = "localhost:8443"
  SPICEDB_TOKEN = "..."
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_MANAGER_REGISTRY: dict[str, str] = {
	"fab":         "pgappforge.security.managers.fab_manager.FABSecurityManager",
	"keycloak":    "pgappforge.security.managers.keycloak_manager.KeycloakSecurityManager",
	"clerk":       "pgappforge.security.managers.clerk_manager.ClerkSecurityManager",
	"better_auth": "pgappforge.security.managers.better_auth_manager.BetterAuthSecurityManager",
	"spicedb":     "pgappforge.security.managers.spicedb_manager.SpiceDBSecurityManager",
}

_PROVIDER_REGISTRY: dict[str, str] = {
	"fab":         "pgappforge.security.providers.fab.FABAuthProvider",
	"keycloak":    "pgappforge.security.providers.keycloak.KeycloakAuthProvider",
	"clerk":       "pgappforge.security.providers.clerk.ClerkAuthProvider",
	"better_auth": "pgappforge.security.providers.better_auth.BetterAuthProvider",
}


def get_security_manager_class(provider: str | None = None):
	"""Return the FAB SecurityManager subclass for the configured AUTH_PROVIDER.

	Falls back to FABSecurityManager on any error.
	"""
	if provider is None:
		try:
			from flask import current_app
			provider = current_app.config.get("AUTH_PROVIDER", "fab").lower()
		except RuntimeError:
			provider = "fab"

	module_path = _MANAGER_REGISTRY.get(provider, _MANAGER_REGISTRY["fab"])
	try:
		import importlib
		parts = module_path.rsplit(".", 1)
		mod = importlib.import_module(parts[0])
		return getattr(mod, parts[1])
	except (ImportError, AttributeError) as exc:
		log.warning("AUTH_PROVIDER=%r manager unavailable (%s) — using FABSecurityManager", provider, exc)
		from pgappforge.security.managers.fab_manager import FABSecurityManager
		return FABSecurityManager


def get_auth_provider():
	"""Return the configured AuthProvider instance (app-level cached)."""
	try:
		from flask import current_app
		ext_key = "_pgaf_auth_provider"
		if ext_key in current_app.extensions:
			return current_app.extensions[ext_key]
		provider_name = current_app.config.get("AUTH_PROVIDER", "fab").lower()
		module_path = _PROVIDER_REGISTRY.get(provider_name, _PROVIDER_REGISTRY["fab"])
		import importlib
		parts = module_path.rsplit(".", 1)
		mod = importlib.import_module(parts[0])
		instance = getattr(mod, parts[1])()
		current_app.extensions[ext_key] = instance
		return instance
	except RuntimeError:
		from pgappforge.security.providers.fab import FABAuthProvider
		return FABAuthProvider()
	except Exception as exc:
		log.warning("get_auth_provider failed (%s) — using FABAuthProvider", exc)
		from pgappforge.security.providers.fab import FABAuthProvider
		return FABAuthProvider()


__all__ = [
	"get_security_manager_class",
	"get_auth_provider",
]
