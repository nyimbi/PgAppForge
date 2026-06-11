"""
pgappforge/security/providers/better_auth.py

BetterAuthProvider — integration with a BetterAuth (betterauth.js) server.

BetterAuth is an open-source TypeScript auth library.
This provider calls its REST API for session validation and user management.

Config keys (Flask app.config):
  BETTER_AUTH_URL        = "http://localhost:3000"   # BetterAuth server
  BETTER_AUTH_SECRET     = "..."                     # shared secret (X-Better-Auth-Secret header)
  BETTER_AUTH_TIMEOUT    = 10
  BETTER_AUTH_ROLE_CLAIM = "role"                    # user field carrying role
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from pgappforge.security.providers.base import AuthUser, AuthProviderError

log = logging.getLogger(__name__)


def _cfg(key: str, default: Any = None) -> Any:
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except RuntimeError:
		return default


class BetterAuthProvider:
	"""BetterAuth server integration provider.

	BetterAuth runs as a separate Node.js service. This provider
	calls its /api/auth REST endpoints for session management.

	All HTTP errors are caught; methods return None/empty on failure.
	"""

	provider = "better_auth"

	@property
	def _base_url(self) -> str:
		return _cfg("BETTER_AUTH_URL", "http://localhost:3000").rstrip("/")

	@property
	def _secret(self) -> str:
		return _cfg("BETTER_AUTH_SECRET", "")

	@property
	def _timeout(self) -> int:
		return int(_cfg("BETTER_AUTH_TIMEOUT", 10))

	@property
	def _role_claim(self) -> str:
		return _cfg("BETTER_AUTH_ROLE_CLAIM", "role")

	def _http_post(self, path: str, body: dict, *, cookie: str = "") -> dict:
		url = f"{self._base_url}/api/auth{path}"
		data = json.dumps(body).encode()
		headers: dict[str, str] = {"Content-Type": "application/json"}
		if self._secret:
			headers["x-better-auth-secret"] = self._secret
		if cookie:
			headers["Cookie"] = cookie
		req = urllib.request.Request(url, data=data, method="POST", headers=headers)
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			if exc.code in (401, 403):
				return {}
			body_txt = exc.read().decode(errors="replace")
			raise AuthProviderError(f"BetterAuth HTTP {exc.code}: {body_txt[:200]}") from exc
		except Exception as exc:
			raise AuthProviderError(f"BetterAuth request failed: {exc}") from exc

	def authenticate(self, credentials: dict[str, Any]) -> AuthUser | None:
		"""Authenticate via BetterAuth email/password sign-in."""
		try:
			result = self._http_post("/sign-in/email", {
				"email": credentials.get("email", credentials.get("username", "")),
				"password": credentials.get("password", ""),
			})
			user_data = result.get("user")
			if not user_data:
				return None
			token = result.get("token", "")
			return self._user_data_to_auth_user(user_data, token)
		except AuthProviderError as exc:
			log.warning("BetterAuthProvider.authenticate: %s", exc)
			return None

	def validate_token(self, token: str) -> AuthUser | None:
		"""Validate a BetterAuth session token."""
		try:
			result = self._http_post(
				"/get-session", {},
				cookie=f"better-auth.session_token={token}",
			)
			user_data = result.get("user")
			return self._user_data_to_auth_user(user_data, token) if user_data else None
		except Exception as exc:
			log.debug("BetterAuthProvider.validate_token: %s", exc)
			return None

	def _user_data_to_auth_user(self, user_data: dict, token: str) -> AuthUser:
		name = user_data.get("name", "")
		name_parts = name.split(" ", 1)
		raw_role = user_data.get(self._role_claim, "")
		roles = (
			raw_role.split(",") if isinstance(raw_role, str) and raw_role
			else (raw_role if isinstance(raw_role, list) else [])
		)
		role_mapping = _cfg("BETTER_AUTH_ROLE_MAPPING", {})
		mapped_roles = [role_mapping.get(r.strip(), r.strip()) for r in roles]
		return AuthUser(
			user_id=str(user_data.get("id", "")),
			username=user_data.get("name", "").replace(" ", "_").lower() or user_data.get("email", "").split("@")[0],
			email=user_data.get("email", ""),
			first_name=name_parts[0] if name_parts else "",
			last_name=name_parts[1] if len(name_parts) > 1 else "",
			roles=mapped_roles,
			provider="better_auth",
			token=token,
			raw_claims=user_data,
		)

	def get_user_permissions(self, user_id: str) -> set[str]:
		perms: set[str] = set()
		role_permissions = _cfg("BETTER_AUTH_ROLE_PERMISSIONS", {})
		for role in self.get_user_roles(user_id):
			perms.update(role_permissions.get(role, []))
		return perms

	def check_permission(self, user_id: str, resource: str, action: str) -> bool:
		return f"{action}_{resource}" in self.get_user_permissions(user_id)

	def get_user_roles(self, user_id: str) -> list[str]:
		"""Roles come from the session token — not re-fetched separately."""
		return []

	def sync_to_fab(self, user: AuthUser, session: Any) -> Any:
		try:
			from flask import current_app
			sm = current_app.appbuilder.sm
			fab_user = sm.find_user(email=user.email)
			if fab_user is None:
				role_objs = [sm.find_role(r) or sm.add_role(r) for r in user.roles]
				fab_user = sm.add_user(
					username=user.username,
					first_name=user.first_name,
					last_name=user.last_name,
					email=user.email,
					role=role_objs[0] if role_objs else sm.find_role(sm.auth_role_public),
					password="",
				)
			return fab_user
		except Exception as exc:
			log.warning("BetterAuthProvider.sync_to_fab: %s", exc)
			return None


__all__ = ["BetterAuthProvider"]
