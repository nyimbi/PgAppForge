"""CI tests for pluggable auth provider abstraction."""
from __future__ import annotations
import inspect, pytest


# ── Base / Protocol ──────────────────────────────────────────────────────────

def test_auth_user_dataclass():
	from pgappforge.security.providers.base import AuthUser
	u = AuthUser(user_id="u1", username="alice", email="alice@example.com",
	             roles=["Admin"], provider="keycloak")
	assert u.is_active
	assert u.full_name == "alice"
	assert "Admin" in u.roles

def test_auth_user_full_name():
	from pgappforge.security.providers.base import AuthUser
	u = AuthUser(user_id="u2", username="bob", email="bob@x.com",
	             first_name="Bob", last_name="Smith")
	assert u.full_name == "Bob Smith"

def test_auth_user_inactive_when_no_id():
	from pgappforge.security.providers.base import AuthUser
	u = AuthUser(user_id="", username="ghost", email="")
	assert not u.is_active

def test_exception_hierarchy():
	from pgappforge.security.providers.base import (
		AuthProviderError, AuthenticationError, TokenExpiredError, PermissionDeniedError
	)
	assert issubclass(AuthenticationError, AuthProviderError)
	assert issubclass(TokenExpiredError, AuthProviderError)
	assert issubclass(PermissionDeniedError, AuthProviderError)

def test_auth_provider_protocol():
	from pgappforge.security.providers.base import AuthProvider
	assert hasattr(AuthProvider, "authenticate")
	assert hasattr(AuthProvider, "validate_token")
	assert hasattr(AuthProvider, "check_permission")

def test_authz_provider_protocol():
	from pgappforge.security.providers.base import AuthorizationProvider
	assert hasattr(AuthorizationProvider, "check_permission")
	assert hasattr(AuthorizationProvider, "write_relationship")
	assert hasattr(AuthorizationProvider, "delete_relationship")


# ── FAB provider ─────────────────────────────────────────────────────────────

def test_fab_provider_name():
	from pgappforge.security.providers.fab import FABAuthProvider
	assert FABAuthProvider.provider == "fab"

def test_fab_validate_token_returns_none():
	from pgappforge.security.providers.fab import FABAuthProvider
	assert FABAuthProvider().validate_token("any-token") is None

def test_fab_authenticate_no_context_returns_none():
	from pgappforge.security.providers.fab import FABAuthProvider
	result = FABAuthProvider().authenticate({"username": "x", "password": "y"})
	assert result is None  # no Flask context

def test_fab_sync_returns_none():
	from pgappforge.security.providers.base import AuthUser
	from pgappforge.security.providers.fab import FABAuthProvider
	u = AuthUser(user_id="1", username="x", email="x@x.com")
	assert FABAuthProvider().sync_to_fab(u, None) is None


# ── Keycloak provider ─────────────────────────────────────────────────────────

def test_keycloak_provider_name():
	from pgappforge.security.providers.keycloak import KeycloakAuthProvider
	assert KeycloakAuthProvider.provider == "keycloak"

def test_keycloak_token_url_property():
	from pgappforge.security.providers.keycloak import KeycloakAuthProvider
	# Computed property — verify no crash, empty server URL returns predictable result
	p = KeycloakAuthProvider()
	url = p._token_url
	assert "/protocol/openid-connect/token" in url

def test_keycloak_claims_to_auth_user():
	from pgappforge.security.providers.keycloak import KeycloakAuthProvider
	p = KeycloakAuthProvider()
	claims = {
		"sub": "kc-user-001",
		"preferred_username": "jdoe",
		"email": "jdoe@example.com",
		"given_name": "John",
		"family_name": "Doe",
		"realm_access": {"roles": ["viewer", "editor"]},
		"resource_access": {},
	}
	user = p._claims_to_auth_user(claims, "tok")
	assert user.user_id == "kc-user-001"
	assert user.username == "jdoe"
	assert "viewer" in user.roles
	assert "editor" in user.roles
	assert user.provider == "keycloak"

def test_keycloak_role_mapping_applied():
	import os, importlib
	from pgappforge.security.providers.keycloak import KeycloakAuthProvider, _cfg
	p = KeycloakAuthProvider()
	claims = {
		"sub": "u1", "preferred_username": "u", "email": "u@x.com",
		"realm_access": {"roles": ["kc_admin"]},
		"resource_access": {},
	}
	# Without Flask context, _cfg returns default — role mapping empty, role unchanged
	user = p._claims_to_auth_user(claims, "tok")
	assert "kc_admin" in user.roles

def test_keycloak_unverified_decode():
	import json, base64
	from pgappforge.security.providers.keycloak import KeycloakAuthProvider
	payload = {"sub": "u1", "exp": 9999999999}
	enc = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
	fake_token = f"header.{enc}.sig"
	p = KeycloakAuthProvider()
	result = p._decode_unverified(fake_token)
	assert result is not None
	assert result["sub"] == "u1"


# ── Clerk provider ────────────────────────────────────────────────────────────

def test_clerk_provider_name():
	from pgappforge.security.providers.clerk import ClerkAuthProvider
	assert ClerkAuthProvider.provider == "clerk"

def test_clerk_authenticate_with_token():
	from pgappforge.security.providers.clerk import ClerkAuthProvider
	# No token in creds → None
	assert ClerkAuthProvider().authenticate({"username": "x"}) is None

def test_clerk_claims_to_auth_user():
	from pgappforge.security.providers.clerk import ClerkAuthProvider
	p = ClerkAuthProvider()
	claims = {
		"sub": "user_clerk_001",
		"email": "clerk@example.com",
		"org_role": "org:admin",
		"org_id": "org_abc",
	}
	user = p._claims_to_auth_user(claims, "tok")
	assert user.user_id == "user_clerk_001"
	assert user.email == "clerk@example.com"
	assert "org:admin" in user.roles
	assert user.tenant_id == "org_abc"
	assert user.provider == "clerk"


# ── SpiceDB ───────────────────────────────────────────────────────────────────

def test_spicedb_endpoint_property():
	from pgappforge.security.providers.spicedb import SpiceDBAuthorizationProvider
	p = SpiceDBAuthorizationProvider()
	ep = p._endpoint
	assert ep.startswith("http")

def test_spicedb_check_fails_closed_on_error():
	from pgappforge.security.providers.spicedb import SpiceDBAuthorizationProvider
	p = SpiceDBAuthorizationProvider()
	# No server running → should return False (fail-closed)
	result = p.check_permission("user", "u1", "resource", "r1", "can_view")
	assert result is False

def test_get_authz_provider_no_context():
	from pgappforge.security.providers.spicedb import get_authz_provider
	# No Flask context and AUTHZ_PROVIDER not set → None
	result = get_authz_provider()
	assert result is None


# ── BetterAuth ────────────────────────────────────────────────────────────────

def test_better_auth_provider_name():
	from pgappforge.security.providers.better_auth import BetterAuthProvider
	assert BetterAuthProvider.provider == "better_auth"

def test_better_auth_user_data_to_auth_user():
	from pgappforge.security.providers.better_auth import BetterAuthProvider
	p = BetterAuthProvider()
	data = {"id": "ba-001", "name": "Jane Doe", "email": "jane@x.com", "role": "admin"}
	user = p._user_data_to_auth_user(data, "tok")
	assert user.user_id == "ba-001"
	assert user.first_name == "Jane"
	assert user.last_name == "Doe"
	assert "admin" in user.roles
	assert user.provider == "better_auth"


# ── Factory / registry ────────────────────────────────────────────────────────

def test_get_security_manager_class_fab():
	from pgappforge.security.providers import get_security_manager_class
	from pgappforge.security.managers.fab_manager import FABSecurityManager
	assert get_security_manager_class("fab") is FABSecurityManager

def test_get_security_manager_class_keycloak():
	from pgappforge.security.providers import get_security_manager_class
	from pgappforge.security.managers.keycloak_manager import KeycloakSecurityManager
	assert get_security_manager_class("keycloak") is KeycloakSecurityManager

def test_get_security_manager_class_clerk():
	from pgappforge.security.providers import get_security_manager_class
	from pgappforge.security.managers.clerk_manager import ClerkSecurityManager
	assert get_security_manager_class("clerk") is ClerkSecurityManager

def test_get_security_manager_class_better_auth():
	from pgappforge.security.providers import get_security_manager_class
	from pgappforge.security.managers.better_auth_manager import BetterAuthSecurityManager
	assert get_security_manager_class("better_auth") is BetterAuthSecurityManager

def test_get_security_manager_class_unknown_falls_back():
	from pgappforge.security.providers import get_security_manager_class
	from pgappforge.security.managers.fab_manager import FABSecurityManager
	assert get_security_manager_class("unknown_provider_xyz") is FABSecurityManager

def test_get_auth_provider_no_context():
	from pgappforge.security.providers import get_auth_provider
	from pgappforge.security.providers.fab import FABAuthProvider
	p = get_auth_provider()
	assert isinstance(p, FABAuthProvider)


# ── Decorators ────────────────────────────────────────────────────────────────

def test_require_permission_importable():
	from pgappforge.security.providers.decorators import require_permission, require_role
	assert callable(require_permission)
	assert callable(require_role)

def test_require_permission_wraps_function():
	from pgappforge.security.providers.decorators import require_permission
	@require_permission("Invoice", "can_list")
	def my_view():
		return "ok"
	assert my_view.__name__ == "my_view"

def test_require_role_wraps_function():
	from pgappforge.security.providers.decorators import require_role
	@require_role("Admin", "Manager")
	def admin_view():
		return "ok"
	assert admin_view.__name__ == "admin_view"


# ── Landing page ──────────────────────────────────────────────────────────────

def test_landing_views_importable():
	from pgappforge.plugins.erp.platform.landing.views import LandingPageView, _MODULE_REGISTRY
	assert callable(LandingPageView.index)
	assert len(_MODULE_REGISTRY) >= 20

def test_landing_module_registry_structure():
	from pgappforge.plugins.erp.platform.landing.views import _MODULE_REGISTRY
	for m in _MODULE_REGISTRY:
		assert "name" in m
		assert "icon" in m
		assert "url" in m

def test_landing_template_exists():
	import os
	path = "pgappforge/templates/appbuilder/landing/landing.html"
	assert os.path.exists(path), f"Missing: {path}"

def test_landing_edit_template_exists():
	import os
	path = "pgappforge/templates/appbuilder/landing/landing_edit.html"
	assert os.path.exists(path), f"Missing: {path}"
