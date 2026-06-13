"""
pgappforge/security/protocol.py

SecurityManagerProtocol — structural typing contract for all PgAppForge
security backends.

This Protocol decouples PgAppForge from Flask-AppBuilder's concrete
SecurityManager, enabling future FastAPI/Keycloak/OIDC backends to be
swapped in without touching view or permission code.

Any class that implements all methods and properties listed here is a valid
security backend, regardless of inheritance.  Python's structural subtyping
(PEP 544) means no explicit registration is required — duck typing is
enforced by the runtime_checkable decorator when isinstance() checks are used.

Compatibility
-------------
- pgappforge.security.sqla.manager.SecurityManager  ✓ (full superset)
- pgappforge.security.manager.BaseSecurityManager   ✓ (full superset)
- Future FastAPI JWT backend                        ✓ (implement these methods)
- Future Keycloak OIDC backend                      ✓ (implement these methods)
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SecurityManagerProtocol(Protocol):
	"""Contract that any PgAppForge security backend must satisfy.

	Both Flask-AppBuilder's SecurityManager and future FastAPI-based
	security implementations must be duck-type compatible with this protocol.

	Design notes
	------------
	- All methods use ``Any`` return types deliberately: concrete backends may
	  return ORM objects, dataclasses, or dicts — callers should not rely on
	  the internal structure.
	- ``find_*`` methods return ``None`` when the entity does not exist rather
	  than raising — callers must handle ``None``.
	- ``add_*`` methods are idempotent where the underlying store supports it;
	  concrete implementations should document their upsert semantics.
	"""

	# ── Access checks ─────────────────────────────────────────────────────────

	def has_access(self, permission_name: str, view_name: str) -> bool:
		"""Check if current user has permission on a view.

		Args:
			permission_name: FAB-style permission string, e.g. ``"can_list"``.
			view_name:       View menu name, e.g. ``"UserModelView"``.

		Returns:
			``True`` if the current user (from Flask-Login or equivalent) holds
			this permission; ``False`` otherwise.
		"""
		...

	# ── Role management ───────────────────────────────────────────────────────

	def add_role(self, name: str) -> Any:
		"""Create a role if it doesn't exist.

		Args:
			name: Role name.  Must be unique within the security store.

		Returns:
			The role object (ORM instance, dict, or equivalent).  If the role
			already exists, returns the existing object.
		"""
		...

	def find_role(self, name: str) -> Any | None:
		"""Find a role by name.

		Args:
			name: Exact role name to look up.

		Returns:
			Role object if found, ``None`` otherwise.
		"""
		...

	# ── User management ───────────────────────────────────────────────────────

	def add_user(
		self,
		username: str,
		first_name: str,
		last_name: str,
		email: str,
		role: Any,
		password: str = "",
	) -> Any:
		"""Create a user.

		Args:
			username:   Unique username / login handle.
			first_name: Given name.
			last_name:  Family name.
			email:      Primary e-mail address (used as login identifier in some
			            backends).
			role:       Role object returned by :meth:`add_role` or
			            :meth:`find_role`.
			password:   Plaintext password.  Concrete implementations must hash
			            this before persisting.  May be empty for SSO-only users.

		Returns:
			The created user object.
		"""
		...

	def find_user(self, username: str = "", email: str = "") -> Any | None:
		"""Find user by username or email.

		At least one of ``username`` or ``email`` must be non-empty.  Backends
		may prioritise one lookup key over the other.

		Returns:
			User object if found, ``None`` otherwise.
		"""
		...

	def get_user_roles(self, user: Any) -> list[Any]:
		"""Get roles for a user.

		Args:
			user: User object as returned by :meth:`add_user` or
			      :meth:`find_user`.

		Returns:
			List of role objects.  Empty list if the user has no roles.
		"""
		...

	# ── Permission / view-menu management ────────────────────────────────────

	def add_permission_view_menu(self, permission_name: str, view_menu_name: str) -> Any:
		"""Register a permission on a view menu.

		Creates the (permission, view_menu) pair in the security store if it
		does not already exist.

		Returns:
			The PermissionView (or equivalent) object.
		"""
		...

	def add_view_menu(self, view_menu_name: str) -> Any:
		"""Register a view menu entry.

		Args:
			view_menu_name: Canonical view menu name, e.g. ``"InvoiceModelView"``.

		Returns:
			The ViewMenu object.
		"""
		...

	def add_permission(self, name: str) -> Any:
		"""Create a permission.

		Args:
			name: Permission action string, e.g. ``"can_list"``, ``"can_edit"``.

		Returns:
			The Permission object.
		"""
		...

	# ── Properties ────────────────────────────────────────────────────────────

	@property
	def auth_role_public(self) -> str:
		"""Name of the public (unauthenticated) role.

		Typically ``"Public"`` in FAB.  Used by views that need to grant
		anonymous access to specific endpoints.
		"""
		...


__all__ = ["SecurityManagerProtocol"]
