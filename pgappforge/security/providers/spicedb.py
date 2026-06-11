"""
pgappforge/security/providers/spicedb.py

SpiceDBAuthorizationProvider — Google Zanzibar-style fine-grained authorization.

SpiceDB is PURE AUTHORIZATION. It does not authenticate users.
Pair with any auth provider (FAB/Keycloak/Clerk/BetterAuth) for authentication.

Config keys (Flask app.config):
  SPICEDB_ENDPOINT  = "localhost:8443"     # REST endpoint (http/https)
  SPICEDB_TOKEN     = "somerandomkeyhere"  # pre-shared token
  SPICEDB_TLS       = False                # True for production
  SPICEDB_TIMEOUT   = 5
  AUTHZ_PROVIDER    = "spicedb"            # enables SpiceDB for authorization

Enable:
  AUTH_PROVIDER  = "keycloak"   # (or fab, clerk, better_auth)
  AUTHZ_PROVIDER = "spicedb"

SpiceDB schema (set SPICEDB_SCHEMA or manage externally):
  definition user {}
  definition resource {
    relation owner: user
    relation viewer: user
    permission can_edit = owner
    permission can_view = viewer + owner
  }
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from pgappforge.security.providers.base import AuthorizationProvider, AuthProviderError

log = logging.getLogger(__name__)


def _cfg(key: str, default: Any = None) -> Any:
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except RuntimeError:
		return default


class SpiceDBAuthorizationProvider:
	"""SpiceDB (Authzed) REST API authorization provider.

	Implements the AuthorizationProvider protocol for relationship-based
	access control (ReBAC). All checks are fail-closed (returns False on error).
	"""

	@property
	def _endpoint(self) -> str:
		ep = _cfg("SPICEDB_ENDPOINT", "localhost:8443")
		if not ep.startswith("http"):
			prefix = "https" if _cfg("SPICEDB_TLS", False) else "http"
			ep = f"{prefix}://{ep}"
		return ep.rstrip("/")

	@property
	def _token(self) -> str:
		return _cfg("SPICEDB_TOKEN", "")

	@property
	def _timeout(self) -> int:
		return int(_cfg("SPICEDB_TIMEOUT", 5))

	def _http_post(self, path: str, body: dict) -> dict:
		url = f"{self._endpoint}{path}"
		data = json.dumps(body).encode()
		req = urllib.request.Request(
			url, data=data, method="POST",
			headers={
				"Content-Type": "application/json",
				"Authorization": f"Bearer {self._token}",
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			raise AuthProviderError(f"SpiceDB HTTP {exc.code}: {path}") from exc
		except Exception as exc:
			raise AuthProviderError(f"SpiceDB request failed: {exc}") from exc

	def check_permission(
		self,
		subject_type: str,
		subject_id: str,
		resource_type: str,
		resource_id: str,
		permission: str,
	) -> bool:
		"""Check if subject has permission on resource. Returns False on any error."""
		try:
			body = {
				"resource": {"objectType": resource_type, "objectId": resource_id},
				"permission": permission,
				"subject": {
					"object": {"objectType": subject_type, "objectId": subject_id}
				},
			}
			result = self._http_post("/v1/permissions/check", body)
			return result.get("permissionship") == "PERMISSIONSHIP_HAS_PERMISSION"
		except AuthProviderError as exc:
			log.warning("SpiceDB check_permission failed (fail-closed): %s", exc)
			return False

	def write_relationship(
		self,
		subject_type: str,
		subject_id: str,
		relation: str,
		resource_type: str,
		resource_id: str,
		*,
		operation: str = "OPERATION_TOUCH",
	) -> None:
		"""Write (or delete) a relationship tuple."""
		body = {
			"updates": [{
				"operation": operation,
				"relationship": {
					"resource": {"objectType": resource_type, "objectId": resource_id},
					"relation": relation,
					"subject": {
						"object": {"objectType": subject_type, "objectId": subject_id}
					},
				},
			}]
		}
		self._http_post("/v1/relationships/write", body)

	def delete_relationship(
		self,
		subject_type: str,
		subject_id: str,
		relation: str,
		resource_type: str,
		resource_id: str,
	) -> None:
		self.write_relationship(
			subject_type, subject_id, relation,
			resource_type, resource_id,
			operation="OPERATION_DELETE",
		)

	def expand_permissions(
		self, resource_type: str, resource_id: str, permission: str
	) -> list[str]:
		"""Return subjects that hold a given permission on a resource."""
		try:
			body = {
				"resource": {"objectType": resource_type, "objectId": resource_id},
				"permission": permission,
				"consistency": {"fullyConsistent": True},
			}
			result = self._http_post("/v1/permissions/expand", body)
			subjects: list[str] = []

			def _walk(node: dict) -> None:
				if "leaf" in node:
					for s in node["leaf"].get("subjects", []):
						obj = s.get("object", {})
						subjects.append(f"{obj.get('objectType','')}/{obj.get('objectId','')}")
				for child in node.get("intermediate", {}).get("children", []):
					_walk(child.get("expandedRelation", {}))

			_walk(result.get("treeRoot", {}))
			return subjects
		except Exception as exc:
			log.debug("SpiceDB expand_permissions failed: %s", exc)
			return []

	def write_schema(self, schema: str) -> None:
		self._http_post("/v1/schema/write", {"schema": schema})

	def read_schema(self) -> str:
		result = self._http_post("/v1/schema/read", {})
		return result.get("schemaText", "")


def get_authz_provider() -> SpiceDBAuthorizationProvider | None:
	"""Return SpiceDB provider if AUTHZ_PROVIDER=spicedb is configured. App-level cached."""
	try:
		from flask import current_app
		if current_app.config.get("AUTHZ_PROVIDER", "").lower() != "spicedb":
			return None
		ext_key = "_pgaf_authz_provider"
		if ext_key not in current_app.extensions:
			current_app.extensions[ext_key] = SpiceDBAuthorizationProvider()
		return current_app.extensions[ext_key]
	except RuntimeError:
		return None


__all__ = ["SpiceDBAuthorizationProvider", "get_authz_provider"]
