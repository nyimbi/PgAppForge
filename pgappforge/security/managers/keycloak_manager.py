"""
pgappforge/security/managers/keycloak_manager.py

KeycloakSecurityManager — FAB SecurityManager that validates Keycloak JWTs.

For web (OAuth redirect) flows: configure FAB's AUTH_TYPE = AUTH_OAUTH with
Keycloak as provider. This manager maps Keycloak roles to FAB roles.

For API flows: validates Bearer JWT from Authorization header on every request,
sets g.auth_user for use with require_permission / require_role decorators.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.security.sqla.manager import SecurityManager

log = logging.getLogger(__name__)


class KeycloakSecurityManager(SecurityManager):
	"""FAB SecurityManager extended with Keycloak JWT validation."""

	def __init__(self, appbuilder):
		super().__init__(appbuilder)
		if appbuilder and getattr(appbuilder, "app", None):
			appbuilder.app.before_request(self.before_request)

	def get_oauth_user_info(self, provider_name: str, resp: Any) -> dict:
		"""Map Keycloak OAuth userinfo to FAB user fields, including role sync."""
		me = super().get_oauth_user_info(provider_name, resp)
		if not me:
			return {}
		try:
			from flask import current_app
			role_mapping = current_app.config.get("KEYCLOAK_ROLE_MAPPING", {})
			raw_roles = me.get("roles", []) or []
			me["role_keys"] = [role_mapping.get(r, r) for r in raw_roles]
		except Exception as exc:
			log.debug("KeycloakSecurityManager.get_oauth_user_info: %s", exc)
		return me

	def auth_user_oauth(self, userinfo: dict) -> Any:
		"""Upsert Keycloak OAuth user into FAB; sync roles from token claims."""
		user = super().auth_user_oauth(userinfo)
		if user and userinfo.get("role_keys"):
			try:
				role_objs = [
					self.find_role(r) or self.add_role(r)
					for r in userinfo["role_keys"]
				]
				user.roles = role_objs
				self.get_session.commit()
			except Exception as exc:
				log.warning("KeycloakSecurityManager role sync failed: %s", exc)
		return user

	def before_request(self) -> None:
		"""Validate Bearer JWT on API requests. Sets g.auth_user if valid."""
		try:
			from flask import request, g
			auth_header = request.headers.get("Authorization", "")
			if not auth_header.startswith("Bearer "):
				return
			token = auth_header[7:]
			from pgappforge.security.providers.keycloak import KeycloakAuthProvider
			auth_user = KeycloakAuthProvider().validate_token(token)
			if auth_user:
				g.auth_user = auth_user
		except Exception as exc:
			log.debug("KeycloakSecurityManager.before_request: %s", exc)


__all__ = ["KeycloakSecurityManager"]
