"""
Behavioral tests for Security Designer — ROLE_TEMPLATES structure, view method
presence, import_yaml validation, export_yaml shape, health_check return type,
and SecuritySnapshot model column types.

No Flask app context or database required for most tests.
import_yaml / export_yaml are exercised via direct method patching so the
savepoint / session machinery is bypassed while validation logic is tested.
"""
from __future__ import annotations

import unittest.mock as mock

from pgappforge.security.sqla.manager import SecurityManager as _SM

# Save the original get_session descriptor so we can restore it after this
# module's tests complete.  _make_sm_for_import() mutates SecurityManager at
# the CLASS level with type(sm).get_session = ..., which otherwise leaks into
# subsequent test modules and breaks any test that uses a real SecurityManager.
_ORIG_GET_SESSION: object = _SM.__dict__.get("get_session")


def teardown_module(module: object) -> None:
	"""Restore SecurityManager.get_session after this module's tests finish."""
	if _ORIG_GET_SESSION is None:
		if "get_session" in _SM.__dict__:
			delattr(_SM, "get_session")
	else:
		try:
			setattr(_SM, "get_session", _ORIG_GET_SESSION)
		except (AttributeError, TypeError):
			pass


# ─── ROLE_TEMPLATES structure ─────────────────────────────────────────────────

def test_role_templates_have_required_fields():
	"""Every template has label, description, and a permissions list."""
	from pgappforge.views.security_designer import ROLE_TEMPLATES
	for name, tpl in ROLE_TEMPLATES.items():
		assert "label" in tpl, f"Template {name!r} missing 'label'"
		assert "description" in tpl, f"Template {name!r} missing 'description'"
		assert isinstance(tpl.get("permissions"), list), (
			f"Template {name!r} missing 'permissions' list"
		)


def test_role_templates_all_known_names():
	"""Exactly the five expected template names are present."""
	from pgappforge.views.security_designer import ROLE_TEMPLATES
	expected = {"Admin", "Editor", "Viewer", "API-only", "Auditor"}
	assert set(ROLE_TEMPLATES.keys()) == expected


# ─── SecurityDesignerView endpoint presence ───────────────────────────────────

def test_security_designer_has_expected_endpoints():
	"""Every public API endpoint method exists on SecurityDesignerView."""
	from pgappforge.views.security_designer import SecurityDesignerView
	required = [
		"api_graph",
		"api_create_role",
		"api_delete_role",
		"api_grant_permission",
		"api_revoke_permission",
		"api_export_yaml",
		"api_import_yaml",
		"api_health_check",
		"api_simulate",
		"api_list_templates",
		"api_apply_template",
		"api_take_snapshot",
		"api_list_snapshots",
		"api_diff",
	]
	for method_name in required:
		assert hasattr(SecurityDesignerView, method_name), (
			f"SecurityDesignerView missing method: {method_name}"
		)


# ─── Internal helper callables ────────────────────────────────────────────────

def test_require_security_admin_function_exists():
	from pgappforge.views.security_designer import _require_security_admin
	assert callable(_require_security_admin)


def test_validate_csrf_imported_or_stub_exists():
	from pgappforge.views.security_designer import _validate_csrf
	assert callable(_validate_csrf)


# ─── export_yaml ─────────────────────────────────────────────────────────────

def test_export_yaml_returns_yaml_string_with_roles_key():
	"""export_yaml produces a YAML string whose root contains a 'roles' list.

	export_yaml calls SQLAlchemy select() with self.role_model — which must be
	a real mapped class.  We use the actual Role model and mock only the session
	execute chain so no database is needed.
	"""
	import yaml
	from pgappforge.security.sqla.manager import SecurityManager
	from pgappforge.security.sqla.models import Role

	sm = SecurityManager.__new__(SecurityManager)
	sm.role_model = Role
	sm.user_model = mock.MagicMock()

	# Build a fake role with one permission view
	fake_pv = mock.MagicMock()
	fake_pv.view_menu = mock.MagicMock(name="UserModelView")
	fake_pv.view_menu.name = "UserModelView"
	fake_pv.permission = mock.MagicMock(name="can_list")
	fake_pv.permission.name = "can_list"

	fake_role = mock.MagicMock(spec=Role)
	fake_role.name = "TestRole"
	fake_role.permissions = [fake_pv]

	fake_session = mock.MagicMock()
	fake_session.execute.return_value.scalars.return_value.unique.return_value.all.return_value = [
		fake_role
	]
	type(sm).get_session = property(lambda self: fake_session)

	result = sm.export_yaml(include_users=False)

	assert isinstance(result, str)
	parsed = yaml.safe_load(result)
	assert "roles" in parsed
	assert isinstance(parsed["roles"], list)


# ─── import_yaml validation ───────────────────────────────────────────────────

def _make_sm_for_import():
	"""Return a bare SecurityManager with the minimum mocks for import_yaml."""
	from pgappforge.security.sqla.manager import SecurityManager

	sm = SecurityManager.__new__(SecurityManager)

	# Minimal appbuilder stub so admin_role_name resolution works
	app_stub = mock.MagicMock()
	app_stub.config = {"AUTH_ROLE_ADMIN": "Admin"}
	ab_stub = mock.MagicMock()
	ab_stub.app = app_stub
	sm.appbuilder = ab_stub

	# Session that supports begin_nested() as a context manager
	nested_cm = mock.MagicMock()
	nested_cm.__enter__ = mock.MagicMock(return_value=None)
	nested_cm.__exit__ = mock.MagicMock(return_value=False)

	session_stub = mock.MagicMock()
	session_stub.begin_nested.return_value = nested_cm
	type(sm).get_session = property(lambda self: session_stub)

	# find_role returns None so every role looks new
	sm.find_role = mock.MagicMock(return_value=None)
	sm.add_role = mock.MagicMock(return_value=mock.MagicMock(
		permissions=[], name="NewRole"
	))
	sm.find_permission_view_menu = mock.MagicMock(return_value=None)
	sm.find_view_menu = mock.MagicMock(return_value=None)
	sm.add_view_menu = mock.MagicMock(return_value=mock.MagicMock())
	sm.find_permission = mock.MagicMock(return_value=None)
	sm.add_permission = mock.MagicMock(return_value=mock.MagicMock())
	sm.add_permission_view_menu = mock.MagicMock(return_value=mock.MagicMock(id=1))
	sm.add_permission_role = mock.MagicMock()

	return sm


def test_import_yaml_size_cap():
	"""Payloads exceeding 256 KB are rejected with ValueError."""
	sm = _make_sm_for_import()
	big = "x" * 300_000  # 300 KB > 256 KB limit
	try:
		result = sm.import_yaml(big)
		# Some implementations return error dict; others raise
		assert result.get("ok") is False or "error" in result
	except ValueError:
		pass  # correct: raised ValueError


def test_import_yaml_validates_role_names():
	"""Role names that fail the regex land in skipped, not added_roles."""
	sm = _make_sm_for_import()
	yaml_text = "roles:\n  - name: 'bad name!'\n    permissions: []\n"
	result = sm.import_yaml(yaml_text, dry_run=True)
	assert "bad name!" not in result.get("added_roles", [])
	assert any("bad name!" in s for s in result.get("skipped", [])), (
		f"Expected 'bad name!' in skipped, got skipped={result.get('skipped')}"
	)


def test_import_yaml_blocks_admin_role_creation():
	"""The Admin role cannot be imported/created via import_yaml."""
	sm = _make_sm_for_import()
	yaml_text = "roles:\n  - name: Admin\n    permissions: []\n"
	result = sm.import_yaml(yaml_text, dry_run=True)
	assert "Admin" not in result.get("added_roles", [])
	assert any("Admin" in s for s in result.get("skipped", [])), (
		f"Expected 'Admin' in skipped, got skipped={result.get('skipped')}"
	)


def test_import_yaml_dry_run_returns_dry_run_true():
	"""import_yaml with dry_run=True must include dry_run=True in the result."""
	sm = _make_sm_for_import()
	result = sm.import_yaml("roles: []\n", dry_run=True)
	assert result.get("dry_run") is True


def test_import_yaml_empty_roles_ok():
	"""Empty roles list is a valid payload — returns ok=True with empty lists."""
	sm = _make_sm_for_import()
	result = sm.import_yaml("roles: []\n", dry_run=True)
	assert result.get("ok") is True
	assert result.get("added_roles") == []


# ─── security_health_check ────────────────────────────────────────────────────

def test_health_check_returns_list():
	"""security_health_check always returns a list (may be empty)."""
	from pgappforge.security.sqla.manager import SecurityManager
	from pgappforge.security.sqla.models import Role, User, PermissionView

	sm = SecurityManager.__new__(SecurityManager)

	# auth_role_admin is a read-only property on BaseSecurityManager;
	# patch it at the class level for this test only.
	with mock.patch.object(
		type(sm), "auth_role_admin", new_callable=mock.PropertyMock, return_value="Admin"
	):
		fake_session = mock.MagicMock()
		# execute().scalar() → 0 active admins (triggers no_active_admin check)
		fake_session.execute.return_value.scalar.return_value = 0
		# execute().scalars().unique().all() → empty role list
		fake_session.execute.return_value.scalars.return_value.unique.return_value.all.return_value = []
		type(sm).get_session = property(lambda self: fake_session)

		sm.role_model = Role
		sm.user_model = User
		sm.permissionview_model = PermissionView
		sm.find_role = mock.MagicMock(return_value=None)  # no Admin role found → skip check

		result = sm.security_health_check()

	assert isinstance(result, list)


# ─── SecuritySnapshot model column types ─────────────────────────────────────

def test_security_snapshot_model_has_jsonb():
	"""snapshot_json column uses PostgreSQL JSONB type."""
	from pgappforge.models.security_designer_models import SecuritySnapshot
	from sqlalchemy.dialects.postgresql import JSONB

	col = SecuritySnapshot.__table__.c.snapshot_json
	assert isinstance(col.type, JSONB), (
		f"Expected JSONB, got {type(col.type).__name__}"
	)


def test_security_snapshot_taken_at_is_timezone_aware():
	"""taken_at column is a timezone-aware DateTime."""
	from pgappforge.models.security_designer_models import SecuritySnapshot
	from sqlalchemy import DateTime

	col = SecuritySnapshot.__table__.c.taken_at
	assert isinstance(col.type, DateTime), (
		f"Expected DateTime, got {type(col.type).__name__}"
	)
	assert col.type.timezone is True, "taken_at must be timezone-aware (timezone=True)"
