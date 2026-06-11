"""KeycloakAuthProvider — OIDC-based auth with Keycloak.

Config keys (Flask app.config):
  KEYCLOAK_SERVER_URL    = "https://keycloak.example.com"
  KEYCLOAK_REALM         = "master"
  KEYCLOAK_CLIENT_ID     = "pgappforge"
  KEYCLOAK_CLIENT_SECRET = "..."
  KEYCLOAK_ROLE_MAPPING  = {}   # optional: {"keycloak_role": "fab_role"}
  KEYCLOAK_TIMEOUT       = 10
"""
from __future__ import annotations
import json, logging, time, urllib.request, urllib.error
from typing import Any
from functools import lru_cache

from pgappforge.security.providers.base import (
	AuthUser, AuthProviderError, AuthenticationError, TokenExpiredError,
)

log = logging.getLogger(__name__)


def _cfg(key: str, default: Any = None) -> Any:
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except RuntimeError:
		return default


class KeycloakAuthProvider:
	"""Keycloak OIDC authentication provider.

	Authentication flow:
	  1. User submits credentials → POST /realms/{realm}/protocol/openid-connect/token
	  2. Server validates → receives access_token (JWT) + refresh_token
	  3. Each request: validate_token(access_token) via JWKS verification
	  4. Roles extracted from JWT realm_access.roles + resource_access claims

	For web login (OAuth redirect), configure FAB's OAuth provider pointing at Keycloak
	and use KeycloakSecurityManager which maps Keycloak roles to FAB roles.
	"""

	provider = "keycloak"

	@property
	def _server_url(self) -> str:
		return _cfg("KEYCLOAK_SERVER_URL", "").rstrip("/")

	@property
	def _realm(self) -> str:
		return _cfg("KEYCLOAK_REALM", "master")

	@property
	def _client_id(self) -> str:
		return _cfg("KEYCLOAK_CLIENT_ID", "")

	@property
	def _client_secret(self) -> str:
		return _cfg("KEYCLOAK_CLIENT_SECRET", "")

	@property
	def _timeout(self) -> int:
		return int(_cfg("KEYCLOAK_TIMEOUT", 10))

	@property
	def _token_url(self) -> str:
		return f"{self._server_url}/realms/{self._realm}/protocol/openid-connect/token"

	@property
	def _jwks_url(self) -> str:
		return f"{self._server_url}/realms/{self._realm}/protocol/openid-connect/certs"

	@property
	def _userinfo_url(self) -> str:
		return f"{self._server_url}/realms/{self._realm}/protocol/openid-connect/userinfo"

	def _http_get(self, url: str, token: str | None = None) -> dict:
		headers = {"Accept": "application/json"}
		if token:
			headers["Authorization"] = f"Bearer {token}"
		req = urllib.request.Request(url, headers=headers)
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as e:
			raise AuthProviderError(f"Keycloak HTTP {e.code}: {url}") from e
		except Exception as exc:
			raise AuthProviderError(f"Keycloak request failed: {exc}") from exc

	def _http_post_form(self, url: str, data: dict) -> dict:
		import urllib.parse
		body = urllib.parse.urlencode(data).encode()
		req = urllib.request.Request(
			url, data=body, method="POST",
			headers={"Content-Type": "application/x-www-form-urlencoded"},
		)
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as e:
			body_txt = e.read().decode(errors="replace")
			raise AuthenticationError(f"Keycloak auth failed: {body_txt[:200]}") from e
		except Exception as exc:
			raise AuthProviderError(f"Keycloak post failed: {exc}") from exc

	def authenticate(self, credentials: dict[str, Any]) -> AuthUser | None:
		"""Authenticate via Resource Owner Password Credentials Grant (server-to-server).

		For browser flows, use OAuth redirect with KeycloakSecurityManager.
		"""
		try:
			data = {
				"grant_type": "password",
				"client_id": self._client_id,
				"client_secret": self._client_secret,
				"username": credentials.get("username", ""),
				"password": credentials.get("password", ""),
				"scope": "openid profile email",
			}
			token_response = self._http_post_form(self._token_url, data)
			access_token = token_response.get("access_token", "")
			if not access_token:
				return None
			return self.validate_token(access_token)
		except AuthenticationError:
			return None
		except Exception as exc:
			log.warning("KeycloakAuthProvider.authenticate error: %s", exc)
			return None

	def validate_token(self, token: str) -> AuthUser | None:
		"""Validate JWT token using Keycloak's JWKS endpoint."""
		try:
			claims = self._decode_jwt(token)
			if not claims:
				return None
			exp = claims.get("exp", 0)
			if exp and exp < time.time():
				raise TokenExpiredError("Keycloak token expired")
			return self._claims_to_auth_user(claims, token)
		except TokenExpiredError:
			return None
		except Exception as exc:
			log.debug("KeycloakAuthProvider.validate_token failed: %s", exc)
			return None

	def _decode_jwt(self, token: str) -> dict | None:
		"""Decode and verify JWT using PyJWT with Keycloak JWKS.

		Falls back to unverified decode if PyJWT not available (dev-only).
		"""
		try:
			import jwt as pyjwt
			from jwt import PyJWKClient
			jwks_client = PyJWKClient(self._jwks_url)
			signing_key = jwks_client.get_signing_key_from_jwt(token)
			return pyjwt.decode(
				token,
				signing_key.key,
				algorithms=["RS256"],
				audience=self._client_id,
				options={"verify_exp": True},
			)
		except ImportError:
			log.warning(
				"PyJWT not installed — using unverified JWT decode "
				"(install: pip install PyJWT)"
			)
			return self._decode_unverified(token)
		except Exception as exc:
			log.debug("JWT decode failed: %s", exc)
			return None

	@staticmethod
	def _decode_unverified(token: str) -> dict | None:
		"""Base64-decode JWT payload without signature verification.

		For development and testing only — never use in production without PyJWT.
		"""
		import base64
		parts = token.split(".")
		if len(parts) != 3:
			return None
		padding = parts[1] + "=" * (-len(parts[1]) % 4)
		try:
			return json.loads(base64.urlsafe_b64decode(padding))
		except Exception:
			return None

	@lru_cache(maxsize=1)
	def _get_jwks(self) -> dict:
		"""Cache JWKS (valid for TTL of signing keys — typically hours)."""
		return self._http_get(self._jwks_url)

	def _claims_to_auth_user(self, claims: dict, token: str) -> AuthUser:
		realm_roles = claims.get("realm_access", {}).get("roles", [])
		client_roles = (
			claims.get("resource_access", {})
			.get(self._client_id, {})
			.get("roles", [])
		)
		all_roles = list(set(realm_roles + client_roles))

		role_mapping = _cfg("KEYCLOAK_ROLE_MAPPING", {})
		mapped_roles = [role_mapping.get(r, r) for r in all_roles]

		return AuthUser(
			user_id=claims.get("sub", ""),
			username=claims.get("preferred_username", ""),
			email=claims.get("email", ""),
			first_name=claims.get("given_name", ""),
			last_name=claims.get("family_name", ""),
			roles=mapped_roles,
			permissions=set(),  # populated by get_user_permissions
			provider="keycloak",
			token=token,
			raw_claims=claims,
			tenant_id=claims.get("tenant_id") or claims.get("organization"),
		)

	def get_user_permissions(self, user_id: str) -> set[str]:
		"""Keycloak roles → FAB permissions (via role_permissions config)."""
		roles = self.get_user_roles(user_id)
		perms: set[str] = set()
		role_permissions = _cfg("KEYCLOAK_ROLE_PERMISSIONS", {})
		for role in roles:
			perms.update(role_permissions.get(role, []))
		return perms

	def check_permission(self, user_id: str, resource: str, action: str) -> bool:
		perms = self.get_user_permissions(user_id)
		return f"{action}_{resource}" in perms or f"can_{action}" in perms

	def get_user_roles(self, user_id: str) -> list[str]:
		"""User ID is the Keycloak 'sub' claim — roles are in the token, not re-fetched."""
		return []  # Roles are extracted from JWT claims at validate_token time

	def sync_to_fab(self, user: AuthUser, session: Any) -> Any:
		from pgappforge.security.providers.utils import sync_external_user_to_fab
		return sync_external_user_to_fab(user)


__all__ = ["KeycloakAuthProvider"]
