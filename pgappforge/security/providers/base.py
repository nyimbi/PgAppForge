"""Base AuthUser dataclass and AuthProvider / AuthorizationProvider Protocols."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class AuthUser:
	"""Normalised user object returned by all auth providers."""
	user_id: str
	username: str
	email: str
	first_name: str = ""
	last_name: str = ""
	roles: list[str] = field(default_factory=list)
	permissions: set[str] = field(default_factory=set)
	provider: str = "fab"
	token: str | None = None
	raw_claims: dict = field(default_factory=dict)
	tenant_id: str | None = None

	@property
	def is_active(self) -> bool:
		return bool(self.user_id)

	@property
	def full_name(self) -> str:
		return f"{self.first_name} {self.last_name}".strip() or self.username


@runtime_checkable
class AuthProvider(Protocol):
	"""Authentication + coarse-grained authorization provider."""

	def authenticate(self, credentials: dict[str, Any]) -> AuthUser | None:
		"""Validate credentials (username/password, token, etc). Returns None on failure."""
		...

	def validate_token(self, token: str) -> AuthUser | None:
		"""Validate a Bearer/session token. Returns None if invalid/expired."""
		...

	def get_user_permissions(self, user_id: str) -> set[str]:
		"""Return the flat permission set for a user (e.g. {'can_list_invoice', ...})."""
		...

	def check_permission(self, user_id: str, resource: str, action: str) -> bool:
		"""Check if user_id can perform action on resource."""
		...

	def get_user_roles(self, user_id: str) -> list[str]:
		"""Return role names for a user."""
		...

	def sync_to_fab(self, user: AuthUser, session: Any) -> Any:
		"""Upsert AuthUser into FAB's User table. Returns FAB user object."""
		...


@runtime_checkable
class AuthorizationProvider(Protocol):
	"""Pure authorization provider (Google Zanzibar / SpiceDB model).

	Complements any authentication provider.
	"""

	def check_permission(self, subject_type: str, subject_id: str,
	                      resource_type: str, resource_id: str,
	                      permission: str) -> bool:
		"""Check if subject can perform permission on resource."""
		...

	def write_relationship(self, subject_type: str, subject_id: str,
	                        relation: str, resource_type: str,
	                        resource_id: str) -> None:
		"""Write a relationship tuple."""
		...

	def delete_relationship(self, subject_type: str, subject_id: str,
	                         relation: str, resource_type: str,
	                         resource_id: str) -> None:
		...

	def expand_permissions(self, resource_type: str, resource_id: str,
	                        permission: str) -> list[str]:
		"""Return list of subjects that have this permission."""
		...


class AuthProviderError(Exception):
	pass


class AuthenticationError(AuthProviderError):
	pass


class TokenExpiredError(AuthProviderError):
	pass


class PermissionDeniedError(AuthProviderError):
	pass


__all__ = [
	"AuthUser", "AuthProvider", "AuthorizationProvider",
	"AuthProviderError", "AuthenticationError", "TokenExpiredError", "PermissionDeniedError",
]
