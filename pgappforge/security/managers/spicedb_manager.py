"""
pgappforge/security/managers/spicedb_manager.py

SpiceDBSecurityManager — combines any auth provider with SpiceDB authorization.

Authentication: FAB built-in (or override AUTH_PROVIDER).
Authorization:  has_access() checks SpiceDB first; falls back to FAB RBAC
               when SpiceDB returns no result for the resource.

This allows a migration path: start with FAB RBAC, selectively override
resources with SpiceDB relationships at your own pace.
"""
from __future__ import annotations

import logging

from pgappforge.security.sqla.manager import SecurityManager

log = logging.getLogger(__name__)


class SpiceDBSecurityManager(SecurityManager):
	"""FAB SecurityManager that uses SpiceDB for fine-grained has_access() checks.

	Requires AUTHZ_PROVIDER = "spicedb" in app.config.

	Behaviour:
	  - SpiceDB not reachable / no authenticated user → delegates to FAB RBAC.
	  - SpiceDB GRANTED → access allowed immediately (FAB RBAC not consulted).
	  - SpiceDB DENIED  → access denied immediately (FAB RBAC cannot override).

	The fail-closed design means SpiceDB is authoritative once reachable.
	During SpiceDB bootstrap, temporarily remove AUTHZ_PROVIDER to let FAB
	RBAC handle initial admin access.
	"""

	def has_access(self, permission_name: str, view_name: str) -> bool:
		from pgappforge.security.providers.spicedb import get_authz_provider
		authz = get_authz_provider()
		if authz is not None:
			try:
				from flask_login import current_user
				if current_user and current_user.is_authenticated:
					if authz.check_permission(
						"user", str(current_user.id),
						"view", view_name,
						permission_name,
					):
						return True
					# SpiceDB explicitly denied — do NOT fall through to FAB RBAC
					# (avoids RBAC granting access that SpiceDB has denied)
					return False
			except Exception as exc:
				log.debug("SpiceDB has_access check failed, using FAB RBAC: %s", exc)
		return super().has_access(permission_name, view_name)

__all__ = ["SpiceDBSecurityManager"]
