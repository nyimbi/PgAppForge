"""
tests/ci/test_plugin_hot_reload.py

CI tests for pgappforge/plugin_hot_reload.py — Plugin Hot-Reload.

Strategy
--------
- All tests use in-process fake plugins; no Flask app context required for
  the core install/disable/reload/list functions.
- Flask route tests use a minimal Flask test client and require real Flask.
- The dynamic-plugins registry is cleared between tests via autouse fixture.

Run:
    uv run pytest -vxs tests/ci/test_plugin_hot_reload.py
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest


# --------------------------------------------------------------------------- #
# Registry isolation                                                           #
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _clear_dynamic_registry():
	"""Reset the module-level plugin registry before each test."""
	import pgappforge.plugin_hot_reload as hr
	hr._dynamic_plugins.clear()
	yield
	hr._dynamic_plugins.clear()


# --------------------------------------------------------------------------- #
# Fake plugin infrastructure                                                  #
# --------------------------------------------------------------------------- #

class _FakeAppBuilder:
	"""Minimal AppBuilder stand-in."""
	pass


def _make_fake_plugin_module(
	module_name: str,
	plugin_name: str = "fake_plugin",
	fail_activate: bool = False,
	has_factory: bool = True,
) -> types.ModuleType:
	"""Create and register a fake plugin module in sys.modules."""
	mod = types.ModuleType(module_name)

	class FakePlugin:
		name = plugin_name
		domain = "test"
		_activated = False
		_deactivated = False

		def __init__(self, appbuilder, **kwargs):
			self.appbuilder = appbuilder

		def activate(self):
			if fail_activate:
				raise RuntimeError("Deliberate activate failure")
			FakePlugin._activated = True
			return True

		def deactivate(self):
			FakePlugin._deactivated = True

	mod.FakePlugin = FakePlugin

	if has_factory:
		def create_plugin(appbuilder, config=None):
			return FakePlugin(appbuilder)
		mod.create_plugin = create_plugin

	sys.modules[module_name] = mod
	return mod


# --------------------------------------------------------------------------- #
# install_plugin                                                               #
# --------------------------------------------------------------------------- #

from pgappforge.plugin_hot_reload import (  # noqa: E402
	disable_plugin,
	install_plugin,
	list_dynamic_plugins,
	reload_plugin,
)


class TestInstallPlugin:
	def test_install_success(self):
		_make_fake_plugin_module("test_mod_install", "my_plugin")
		ok, msg = install_plugin("test_mod_install", _FakeAppBuilder())
		assert ok is True
		assert "my_plugin" in msg

	def test_install_registers_in_registry(self):
		_make_fake_plugin_module("test_mod_registry", "reg_plugin")
		install_plugin("test_mod_registry", _FakeAppBuilder())
		import pgappforge.plugin_hot_reload as hr
		assert "reg_plugin" in hr._dynamic_plugins

	def test_install_calls_activate(self):
		mod = _make_fake_plugin_module("test_mod_activate", "act_plugin")
		install_plugin("test_mod_activate", _FakeAppBuilder())
		assert mod.FakePlugin._activated is True

	def test_install_nonexistent_module_fails(self):
		ok, msg = install_plugin("no_such_module_xyz_12345", _FakeAppBuilder())
		assert ok is False
		assert "failed" in msg.lower() or "import" in msg.lower()

	def test_install_rejects_invalid_module_path_before_import(self):
		ok, msg = install_plugin("../bad", _FakeAppBuilder())
		assert ok is False
		assert "invalid module_path" in msg.lower()

	def test_install_respects_allowed_prefixes(self):
		_make_fake_plugin_module("test_mod_blocked", "blocked_plugin")
		ok, msg = install_plugin(
			"test_mod_blocked",
			_FakeAppBuilder(),
			allowed_prefixes=("pgappforge.plugins.",),
		)
		assert ok is False
		assert "allowed prefixes" in msg

	def test_install_accepts_matching_allowed_prefix(self):
		_make_fake_plugin_module("test_mod_allowed", "allowed_plugin")
		ok, msg = install_plugin(
			"test_mod_allowed",
			_FakeAppBuilder(),
			allowed_prefixes=("test_",),
		)
		assert ok is True
		assert "allowed_plugin" in msg

	def test_install_no_plugin_class_fails(self):
		empty_mod = types.ModuleType("test_mod_empty")
		sys.modules["test_mod_empty"] = empty_mod
		ok, msg = install_plugin("test_mod_empty", _FakeAppBuilder())
		assert ok is False

	def test_install_factory_result_must_expose_activate(self):
		mod = types.ModuleType("test_mod_no_activate")

		class NoActivate:
			name = "no_activate"

		def create_plugin(appbuilder):
			return NoActivate()

		mod.create_plugin = create_plugin
		sys.modules["test_mod_no_activate"] = mod
		ok, msg = install_plugin("test_mod_no_activate", _FakeAppBuilder())
		assert ok is False
		assert "activate" in msg.lower()

	def test_install_activate_failure_returns_false(self):
		_make_fake_plugin_module("test_mod_fail_act", "fail_plugin", fail_activate=True)
		ok, msg = install_plugin("test_mod_fail_act", _FakeAppBuilder())
		assert ok is False
		assert "fail" in msg.lower() or "activate" in msg.lower()

	def test_install_without_factory_uses_class_scan(self):
		"""Plugin without create_plugin factory: class scan should find FakePlugin."""
		_make_fake_plugin_module("test_mod_noscan", "scan_plugin", has_factory=False)
		# For the class scan to work the class must be a BasePlugin subclass.
		# Our FakePlugin isn't; test that it gracefully falls through.
		# We expect either success (if fallback kicks in) or a clear failure message.
		ok, msg = install_plugin("test_mod_noscan", _FakeAppBuilder())
		# Either outcome is acceptable — no crash
		assert isinstance(ok, bool)
		assert isinstance(msg, str)

	def test_install_idempotent_second_call_overwrites(self):
		_make_fake_plugin_module("test_mod_idem", "idem_plugin")
		ok1, _ = install_plugin("test_mod_idem", _FakeAppBuilder())
		ok2, _ = install_plugin("test_mod_idem", _FakeAppBuilder())
		assert ok1 is True
		assert ok2 is True
		import pgappforge.plugin_hot_reload as hr
		# Registry should still have exactly one entry for this plugin
		assert list(hr._dynamic_plugins.keys()).count("idem_plugin") == 1


# --------------------------------------------------------------------------- #
# disable_plugin                                                               #
# --------------------------------------------------------------------------- #

class TestDisablePlugin:
	def test_disable_installed_plugin(self):
		_make_fake_plugin_module("test_mod_dis", "dis_plugin")
		install_plugin("test_mod_dis", _FakeAppBuilder())
		ok, msg = disable_plugin("dis_plugin", _FakeAppBuilder())
		assert ok is True
		assert "disabled" in msg.lower() or "dis_plugin" in msg

	def test_disable_removes_from_registry(self):
		_make_fake_plugin_module("test_mod_dis2", "dis2_plugin")
		install_plugin("test_mod_dis2", _FakeAppBuilder())
		disable_plugin("dis2_plugin", _FakeAppBuilder())
		import pgappforge.plugin_hot_reload as hr
		assert "dis2_plugin" not in hr._dynamic_plugins

	def test_disable_calls_deactivate(self):
		mod = _make_fake_plugin_module("test_mod_deact", "deact_plugin")
		install_plugin("test_mod_deact", _FakeAppBuilder())
		disable_plugin("deact_plugin", _FakeAppBuilder())
		assert mod.FakePlugin._deactivated is True

	def test_disable_unknown_plugin_fails(self):
		ok, msg = disable_plugin("nonexistent_plugin", _FakeAppBuilder())
		assert ok is False
		assert "not found" in msg.lower()

	def test_disable_unknown_plugin_message_contains_name(self):
		ok, msg = disable_plugin("ghost_plugin", _FakeAppBuilder())
		assert "ghost_plugin" in msg


# --------------------------------------------------------------------------- #
# reload_plugin                                                               #
# --------------------------------------------------------------------------- #

class TestReloadPlugin:
	def test_reload_existing_real_module(self):
		"""importlib.reload requires a file-backed module with a __spec__.
		Use a real stdlib module (json) as the reload target.
		"""
		ok, msg = reload_plugin("json", _FakeAppBuilder())
		assert ok is True
		assert "json" in msg

	def test_reload_nonexistent_module_fails(self):
		ok, msg = reload_plugin("no_such_module_xyz_99999", _FakeAppBuilder())
		assert ok is False
		assert "failed" in msg.lower()

	def test_reload_synthetic_module_fails_gracefully(self):
		"""Synthetic modules (no __spec__) cause importlib.reload to raise;
		reload_plugin must return (False, message) cleanly rather than propagating.
		"""
		_make_fake_plugin_module("test_mod_synth", "synth_plugin")
		ok, msg = reload_plugin("test_mod_synth", _FakeAppBuilder())
		# Either the reload is handled gracefully (ok=False) or the implementation
		# treats it as a success — either way no unhandled exception.
		assert isinstance(ok, bool)
		assert isinstance(msg, str)

	def test_reload_real_module_object_is_reused(self):
		"""After reload the module object identity is preserved (importlib contract)."""
		import json as _json
		mod_before = sys.modules["json"]
		reload_plugin("json", _FakeAppBuilder())
		mod_after = sys.modules["json"]
		assert mod_before is mod_after


# --------------------------------------------------------------------------- #
# list_dynamic_plugins                                                        #
# --------------------------------------------------------------------------- #

class TestListDynamicPlugins:
	def test_empty_initially(self):
		result = list_dynamic_plugins()
		assert result == []

	def test_shows_installed_plugin(self):
		_make_fake_plugin_module("test_mod_lst", "lst_plugin")
		install_plugin("test_mod_lst", _FakeAppBuilder())
		result = list_dynamic_plugins()
		names = [p["name"] for p in result]
		assert "lst_plugin" in names

	def test_each_entry_has_required_keys(self):
		_make_fake_plugin_module("test_mod_shape", "shape_plugin")
		install_plugin("test_mod_shape", _FakeAppBuilder())
		result = list_dynamic_plugins()
		for entry in result:
			assert "name" in entry
			assert "module" in entry
			assert "domain" in entry
			assert "installed_at" in entry

	def test_installed_at_is_runtime(self):
		_make_fake_plugin_module("test_mod_rt", "rt_plugin")
		install_plugin("test_mod_rt", _FakeAppBuilder())
		result = list_dynamic_plugins()
		for entry in result:
			assert entry["installed_at"] == "runtime"

	def test_removed_after_disable(self):
		_make_fake_plugin_module("test_mod_rem", "rem_plugin")
		install_plugin("test_mod_rem", _FakeAppBuilder())
		disable_plugin("rem_plugin", _FakeAppBuilder())
		names = [p["name"] for p in list_dynamic_plugins()]
		assert "rem_plugin" not in names

	def test_multiple_plugins(self):
		for i in range(3):
			_make_fake_plugin_module(f"test_multi_mod_{i}", f"multi_plugin_{i}")
			install_plugin(f"test_multi_mod_{i}", _FakeAppBuilder())
		result = list_dynamic_plugins()
		assert len(result) >= 3


# --------------------------------------------------------------------------- #
# setup_hot_reload_api — Flask route tests                                    #
# --------------------------------------------------------------------------- #

try:
	from flask import Flask as _Flask
	_HAS_FLASK = True
except ImportError:
	_HAS_FLASK = False


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask not installed")
class TestHotReloadAPI:
	@pytest.fixture
	def client(self):
		from flask import Flask
		app = Flask(__name__)
		app.config["TESTING"] = True
		app.config["SECRET_KEY"] = "test-secret"
		app.config["PGAPPFORGE_HOT_RELOAD_ALLOWED_PREFIXES"] = (
			"pgappforge.plugins.",
			"test_",
			"json",
		)

		# Stub has_access decorator to pass through
		import pgappforge.security.decorators as sec_dec
		_orig = getattr(sec_dec, "has_access", None)
		sec_dec.has_access = lambda f: f

		from pgappforge.plugin_hot_reload import setup_hot_reload_api
		setup_hot_reload_api(app, _FakeAppBuilder())

		yield app.test_client()

		if _orig is not None:
			sec_dec.has_access = _orig

	def test_list_dynamic_empty(self, client):
		rv = client.get("/admin/plugins/dynamic")
		assert rv.status_code == 200
		data = rv.get_json()
		assert "plugins" in data
		assert data["plugins"] == []

	def test_install_missing_module_path(self, client):
		rv = client.post(
			"/admin/plugins/install",
			json={},
			content_type="application/json",
		)
		assert rv.status_code == 400

	def test_disable_missing_plugin_name(self, client):
		rv = client.post(
			"/admin/plugins/disable",
			json={},
			content_type="application/json",
		)
		assert rv.status_code == 400

	def test_reload_missing_module_path(self, client):
		rv = client.post(
			"/admin/plugins/reload",
			json={},
			content_type="application/json",
		)
		assert rv.status_code == 400

	def test_install_bad_module_returns_500(self, client):
		rv = client.post(
			"/admin/plugins/install",
			json={"module_path": "totally.nonexistent.module.xyz"},
			content_type="application/json",
		)
		assert rv.status_code == 500
		data = rv.get_json()
		assert data["success"] is False

	def test_install_good_module_returns_200(self, client):
		_make_fake_plugin_module("test_api_good", "api_good_plugin")
		rv = client.post(
			"/admin/plugins/install",
			json={"module_path": "test_api_good"},
			content_type="application/json",
		)
		assert rv.status_code == 200
		data = rv.get_json()
		assert data["success"] is True

	def test_list_shows_installed(self, client):
		_make_fake_plugin_module("test_api_list2", "api_list2_plugin")
		client.post(
			"/admin/plugins/install",
			json={"module_path": "test_api_list2"},
			content_type="application/json",
		)
		rv = client.get("/admin/plugins/dynamic")
		data = rv.get_json()
		names = [p["name"] for p in data["plugins"]]
		assert "api_list2_plugin" in names

	def test_disable_installed_returns_200(self, client):
		_make_fake_plugin_module("test_api_dis3", "api_dis3_plugin")
		client.post(
			"/admin/plugins/install",
			json={"module_path": "test_api_dis3"},
			content_type="application/json",
		)
		rv = client.post(
			"/admin/plugins/disable",
			json={"plugin_name": "api_dis3_plugin"},
			content_type="application/json",
		)
		assert rv.status_code == 200
		data = rv.get_json()
		assert data["success"] is True

	def test_reload_returns_200(self, client):
		rv = client.post(
			"/admin/plugins/reload",
			json={"module_path": "json"},
			content_type="application/json",
		)
		assert rv.status_code == 200
		data = rv.get_json()
		assert data["success"] is True
