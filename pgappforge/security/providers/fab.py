"""FABAuthProvider — wraps existing FAB SecurityManager. Zero config needed, default."""
from __future__ import annotations
import logging
from typing import Any
from pgappforge.security.providers.base import AuthUser, AuthProviderError

log = logging.getLogger(__name__)


class FABAuthProvider:
	"""Default auth provider — delegates entirely to FAB's built-in SecurityManager.

	No external dependencies. Works with FAB's DB auth, LDAP, OAuth, OpenID.
	This is the zero-migration default.
	"""

	provider = "fab"

	def authenticate(self, credentials: dict[str, Any]) -> AuthUser | None:
		try:
			from flask import current_app
			sm = current_app.appbuilder.sm
			username = credentials.get("username", "")
			password = credentials.get("password", "")
			user = sm.auth_user_db(username, password)
			if user is None:
				return None
			return self._fab_user_to_auth_user(user)
		except Exception as exc:
			log.debug("FABAuthProvider.authenticate failed: %s", exc)
			return None

	def validate_token(self, token: str) -> AuthUser | None:
		"""FAB uses session cookies; token validation not applicable. Returns None."""
		return None

	def get_user_permissions(self, user_id: str) -> set[str]:
		try:
			from flask import current_app
			sm = current_app.appbuilder.sm
			user = sm.get_user_by_id(int(user_id))
			if user is None:
				return set()
			return {
				f"{pvm.permission.name}_{pvm.view_menu.name}"
				for role in user.roles
				for pvm in role.permissions
			}
		except Exception:
			return set()

	def check_permission(self, user_id: str, resource: str, action: str) -> bool:
		try:
			from flask import current_app
			sm = current_app.appbuilder.sm
			return sm.has_access(action, resource)
		except Exception:
			return False

	def get_user_roles(self, user_id: str) -> list[str]:
		try:
			from flask import current_app
			sm = current_app.appbuilder.sm
			user = sm.get_user_by_id(int(user_id))
			return [r.name for r in (user.roles if user else [])]
		except Exception:
			return []

	def sync_to_fab(self, user: AuthUser, session: Any) -> Any:
		"""FABAuthProvider users are native FAB users — no sync needed."""
		return None

	@staticmethod
	def _fab_user_to_auth_user(fab_user: Any) -> AuthUser:
		return AuthUser(
			user_id=str(fab_user.id),
			username=fab_user.username,
			email=fab_user.email or "",
			first_name=fab_user.first_name or "",
			last_name=fab_user.last_name or "",
			roles=[r.name for r in (fab_user.roles or [])],
			provider="fab",
		)


__all__ = ["FABAuthProvider"]
