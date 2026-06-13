"""
tests/ci/test_security_protocol.py

Tests for pgappforge.security.protocol.SecurityManagerProtocol (ARCH-3).

Strategy
--------
- Structural typing checks using isinstance() on conformant / non-conformant
  duck-type classes.  No Flask context required.
- Export consistency: security.__init__ must re-export SecurityManagerProtocol.
- All 10 contracted methods and the auth_role_public property are checked.
"""
from __future__ import annotations

import pytest

from pgappforge.security.protocol import SecurityManagerProtocol


# ── Fixtures ──────────────────────────────────────────────────────────────────

class _FullBackend:
	"""Minimal class that satisfies every method in the Protocol."""

	def has_access(self, permission_name: str, view_name: str) -> bool:
		return True

	def add_role(self, name: str):
		return object()

	def find_role(self, name: str):
		return None

	def add_user(self, username, first_name, last_name, email, role, password=""):
		return object()

	def find_user(self, username="", email=""):
		return None

	def add_permission_view_menu(self, permission_name, view_menu_name):
		return object()

	def add_view_menu(self, view_menu_name):
		return object()

	def add_permission(self, name):
		return object()

	def get_user_roles(self, user):
		return []

	@property
	def auth_role_public(self) -> str:
		return "Public"


class _MissingOneMethod:
	"""Missing get_user_roles — should NOT satisfy the Protocol."""

	def has_access(self, p, v): return True
	def add_role(self, name): return object()
	def find_role(self, name): return None
	def add_user(self, u, fn, ln, e, r, password=""): return object()
	def find_user(self, username="", email=""): return None
	def add_permission_view_menu(self, p, v): return object()
	def add_view_menu(self, v): return object()
	def add_permission(self, n): return object()
	# get_user_roles intentionally omitted
	@property
	def auth_role_public(self): return "Public"


class _MissingProperty:
	"""Missing auth_role_public — should NOT satisfy the Protocol."""

	def has_access(self, p, v): return True
	def add_role(self, name): return object()
	def find_role(self, name): return None
	def add_user(self, u, fn, ln, e, r, password=""): return object()
	def find_user(self, username="", email=""): return None
	def add_permission_view_menu(self, p, v): return object()
	def add_view_menu(self, v): return object()
	def add_permission(self, n): return object()
	def get_user_roles(self, user): return []
	# auth_role_public intentionally omitted


# ── Protocol structural typing tests ─────────────────────────────────────────

def test_full_backend_satisfies_protocol():
	"""A class implementing all 10 members must pass isinstance()."""
	assert isinstance(_FullBackend(), SecurityManagerProtocol)


def test_missing_method_fails_protocol():
	"""A class missing get_user_roles must not satisfy the Protocol."""
	assert not isinstance(_MissingOneMethod(), SecurityManagerProtocol)


def test_missing_property_fails_protocol():
	"""A class missing auth_role_public must not satisfy the Protocol."""
	assert not isinstance(_MissingProperty(), SecurityManagerProtocol)


def test_bare_object_fails_protocol():
	"""A plain object with no methods must not satisfy the Protocol."""
	assert not isinstance(object(), SecurityManagerProtocol)


def test_none_fails_protocol():
	"""None is not an instance of SecurityManagerProtocol."""
	assert not isinstance(None, SecurityManagerProtocol)


# ── Protocol attribute catalogue ─────────────────────────────────────────────

_EXPECTED_MEMBERS = frozenset({
	"has_access",
	"add_role",
	"find_role",
	"add_user",
	"find_user",
	"add_permission_view_menu",
	"add_view_menu",
	"add_permission",
	"get_user_roles",
	"auth_role_public",
})


def test_protocol_exposes_all_expected_members():
	"""SecurityManagerProtocol must declare exactly the expected public API."""
	# __protocol_attrs__ is set by @runtime_checkable on Python 3.12+
	# Fall back to checking public members on the class.
	public = {m for m in dir(SecurityManagerProtocol) if not m.startswith("_")}
	missing = _EXPECTED_MEMBERS - public
	assert not missing, f"Protocol is missing members: {missing}"


# ── Export consistency ────────────────────────────────────────────────────────

def test_security_init_exports_protocol():
	"""pgappforge.security.__init__ must re-export SecurityManagerProtocol."""
	from pgappforge.security import SecurityManagerProtocol as Exported
	assert Exported is SecurityManagerProtocol


def test_protocol_is_runtime_checkable():
	"""SecurityManagerProtocol must be usable with isinstance() at runtime."""
	# If NOT runtime_checkable, isinstance() raises TypeError
	try:
		isinstance(object(), SecurityManagerProtocol)
	except TypeError:
		pytest.fail("SecurityManagerProtocol is not runtime_checkable")


# ── Behaviour of concrete backend through the Protocol ───────────────────────

def test_protocol_method_calls_work_on_conformant_class():
	"""Methods called via a Protocol-typed variable must behave correctly."""
	backend: SecurityManagerProtocol = _FullBackend()
	assert backend.has_access("can_list", "InvoiceView") is True
	assert backend.find_role("NonExistent") is None
	assert backend.find_user(username="admin") is None
	assert backend.get_user_roles(object()) == []
	assert backend.auth_role_public == "Public"
