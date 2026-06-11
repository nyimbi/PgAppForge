"""ClerkAuthProvider — JWT-based auth with Clerk.dev.

Config keys (Flask app.config):
  CLERK_SECRET_KEY       = "sk_live_..."
  CLERK_PUBLISHABLE_KEY  = "pk_live_..."   # optional, for frontend
  CLERK_JWT_KEY          = "-----BEGIN PUBLIC KEY-----\\n..."  # PEM, for offline verify
  CLERK_ROLE_CLAIM       = "org_role"      # JWT claim carrying role (default: org_role)
  CLERK_ROLE_MAPPING     = {}              # optional: {"org:admin": "Admin"}
  CLERK_TIMEOUT          = 10
"""
from __future__ import annotations
import json, logging, time, urllib.request, urllib.error
from typing import Any

from pgappforge.security.providers.base import (
	AuthUser, AuthProviderError, AuthenticationError, TokenExpiredError,
)

log = logging.getLogger(__name__)

_CLERK_JWKS_URL = "https://api.clerk.dev/v1/jwks"
_CLERK_USERS_URL = "https://api.clerk.dev/v1/users"


def _cfg(key: str, default: Any = None) -> Any:
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except RuntimeError:
		return default


class ClerkAuthProvider:
	"""Clerk.dev authentication provider.

	Authentication flow (API/backend):
	  1. Frontend obtains a session JWT from Clerk's JS SDK
	  2. JWT is sent as Bearer token in Authorization header
	  3. validate_token() verifies the JWT using Clerk's JWKS endpoint
	  4. User info and org roles extracted from JWT claims

	For web SSO, Clerk handles the OAuth/OIDC redirect flow entirely.
	The backend only needs to validate the resulting JWT.
	"""

	provider = "clerk"

	@property
	def _secret_key(self) -> str:
		return _cfg("CLERK_SECRET_KEY", "")

	@property
	def _timeout(self) -> int:
		return int(_cfg("CLERK_TIMEOUT", 10))

	@property
	def _role_claim(self) -> str:
		return _cfg("CLERK_ROLE_CLAIM", "org_role")

	def _http_get(self, url: str) -> dict:
		headers = {
			"Accept": "application/json",
			"Authorization": f"Bearer {self._secret_key}",
		}
		req = urllib.request.Request(url, headers=headers)
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as e:
			raise AuthProviderError(f"Clerk HTTP {e.code}: {url}") from e
		except Exception as exc:
			raise AuthProviderError(f"Clerk request failed: {exc}") from exc

	def authenticate(self, credentials: dict[str, Any]) -> AuthUser | None:
		"""Clerk does not support username/password — use validate_token() with a JWT.

		If a 'token' key is present in credentials, delegates to validate_token.
		"""
		token = credentials.get("token")
		if token:
			return self.validate_token(token)
		log.debug("ClerkAuthProvider.authenticate: no token in credentials")
		return None

	def validate_token(self, token: str) -> AuthUser | None:
		"""Validate a Clerk session JWT."""
		try:
			claims = self._decode_jwt(token)
			if not claims:
				return None
			exp = claims.get("exp", 0)
			if exp and exp < time.time():
				raise TokenExpiredError("Clerk token expired")
			return self._claims_to_auth_user(claims, token)
		except TokenExpiredError:
			return None
		except Exception as exc:
			log.debug("ClerkAuthProvider.validate_token failed: %s", exc)
			return None

	def _decode_jwt(self, token: str) -> dict | None:
		"""Verify JWT signature using Clerk's JWKS or configured PEM key."""
		# Try static PEM key first (faster, no network)
		pem_key = _cfg("CLERK_JWT_KEY")
		try:
			import jwt as pyjwt
			if pem_key:
				return pyjwt.decode(
					token,
					pem_key,
					algorithms=["RS256"],
					options={"verify_exp": True},
				)
			# Fall back to JWKS endpoint
			from jwt import PyJWKClient
			jwks_client = PyJWKClient(_CLERK_JWKS_URL)
			signing_key = jwks_client.get_signing_key_from_jwt(token)
			return pyjwt.decode(
				token,
				signing_key.key,
				algorithms=["RS256"],
				options={"verify_exp": True},
			)
		except ImportError:
			log.warning(
				"PyJWT not installed — using unverified JWT decode "
				"(install: pip install PyJWT)"
			)
			import base64
			parts = token.split(".")
			if len(parts) != 3:
				return None
			try:
				return json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
			except Exception:
				return None
		except Exception as exc:
			log.debug("Clerk JWT decode failed: %s", exc)
			return None

	def _claims_to_auth_user(self, claims: dict, token: str) -> AuthUser:
		# Clerk puts user metadata in the JWT — extract roles from configured claim
		raw_role = claims.get(self._role_claim, "")
		roles = [raw_role] if isinstance(raw_role, str) and raw_role else (
			raw_role if isinstance(raw_role, list) else []
		)

		role_mapping = _cfg("CLERK_ROLE_MAPPING", {})
		mapped_roles = [role_mapping.get(r, r) for r in roles]

		# Clerk JWT uses 'sub' as the user ID, metadata in 'public_metadata'
		meta = claims.get("public_metadata") or {}
		org_id = claims.get("org_id") or claims.get("organization_id")

		return AuthUser(
			user_id=claims.get("sub", ""),
			username=claims.get("username") or claims.get("email", "").split("@")[0],
			email=claims.get("email", ""),
			first_name=meta.get("first_name", "") or claims.get("given_name", ""),
			last_name=meta.get("last_name", "") or claims.get("family_name", ""),
			roles=mapped_roles,
			permissions=set(),
			provider="clerk",
			token=token,
			raw_claims=claims,
			tenant_id=org_id,
		)

	def get_user_permissions(self, user_id: str) -> set[str]:
		roles = self.get_user_roles(user_id)
		perms: set[str] = set()
		role_permissions = _cfg("CLERK_ROLE_PERMISSIONS", {})
		for role in roles:
			perms.update(role_permissions.get(role, []))
		return perms

	def check_permission(self, user_id: str, resource: str, action: str) -> bool:
		perms = self.get_user_permissions(user_id)
		return f"{action}_{resource}" in perms or f"can_{action}" in perms

	def get_user_roles(self, user_id: str) -> list[str]:
		"""Fetch user roles from Clerk API (requires CLERK_SECRET_KEY)."""
		if not self._secret_key:
			return []
		try:
			data = self._http_get(f"{_CLERK_USERS_URL}/{user_id}")
			meta = data.get("public_metadata") or {}
			roles = meta.get("roles", [])
			return roles if isinstance(roles, list) else [roles]
		except Exception as exc:
			log.debug("ClerkAuthProvider.get_user_roles failed: %s", exc)
			return []

	def sync_to_fab(self, user: AuthUser, session: Any) -> Any:
		from pgappforge.security.providers.utils import sync_external_user_to_fab
		return sync_external_user_to_fab(user, lookup_by_email=True)


__all__ = ["ClerkAuthProvider"]
