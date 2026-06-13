"""
tests/ci/test_pwa.py

CI tests for pgappforge.pwa — Offline PWA Generation Toggle.

Strategy
--------
- No Flask app context needed for unit tests of config + SW generation.
- Flask test client used for route tests (manifest.json, sw.js).
- All tests are synchronous; no external services required.

Run:
    uv run pytest -vxs tests/ci/test_pwa.py
"""
from __future__ import annotations

import json
import sys
import types

import pytest


# --------------------------------------------------------------------------- #
# Stub Flask minimally so pgappforge.pwa can be imported without the full stack
# --------------------------------------------------------------------------- #

def _ensure_flask_stub():
	"""Inject a real Flask app for route tests — use actual flask if available."""
	try:
		import flask  # noqa: F401
	except ImportError:
		flask_mod = types.ModuleType("flask")

		class _Response:
			def __init__(self, data, content_type="text/plain", headers=None):
				self.data = data
				self.content_type = content_type
				self.headers = headers or {}

		flask_mod.Response = _Response
		flask_mod.jsonify = lambda d: _Response(json.dumps(d), "application/json")
		sys.modules.setdefault("flask", flask_mod)


_ensure_flask_stub()


# --------------------------------------------------------------------------- #
# Import the module under test                                                 #
# --------------------------------------------------------------------------- #

from pgappforge.pwa import PWAConfig, generate_pwa_html_snippet, _generate_service_worker  # noqa: E402


# --------------------------------------------------------------------------- #
# PWAConfig defaults                                                           #
# --------------------------------------------------------------------------- #

class TestPWAConfig:
	def test_default_disabled(self):
		cfg = PWAConfig()
		assert cfg.enabled is False

	def test_default_app_name(self):
		cfg = PWAConfig()
		assert cfg.app_name == "PgAppForge"

	def test_default_cache_strategy(self):
		cfg = PWAConfig()
		assert cfg.cache_strategy == "network-first"

	def test_default_offline_pages_empty(self):
		cfg = PWAConfig()
		assert cfg.offline_pages == []

	def test_sync_queue_on_by_default(self):
		cfg = PWAConfig()
		assert cfg.sync_queue is True

	def test_mutability(self):
		cfg = PWAConfig()
		cfg.enabled = True
		cfg.app_name = "MyApp"
		cfg.offline_pages = ["/dashboard", "/reports"]
		assert cfg.enabled is True
		assert cfg.app_name == "MyApp"
		assert len(cfg.offline_pages) == 2


# --------------------------------------------------------------------------- #
# Service Worker generation                                                    #
# --------------------------------------------------------------------------- #

class TestGenerateServiceWorker:
	def _cfg(self, strategy: str = "network-first", sync: bool = True) -> PWAConfig:
		cfg = PWAConfig()
		cfg.cache_strategy = strategy
		cfg.sync_queue = sync
		cfg.app_name = "TestApp"
		return cfg

	def test_output_is_string(self):
		sw = _generate_service_worker(self._cfg())
		assert isinstance(sw, str)

	def test_contains_cache_name(self):
		sw = _generate_service_worker(self._cfg())
		assert "pgappforge-v1" in sw

	def test_contains_install_event(self):
		sw = _generate_service_worker(self._cfg())
		assert "install" in sw

	def test_contains_activate_event(self):
		sw = _generate_service_worker(self._cfg())
		assert "activate" in sw

	def test_contains_fetch_event(self):
		sw = _generate_service_worker(self._cfg())
		assert "fetch" in sw

	def test_network_first_strategy_comment(self):
		sw = _generate_service_worker(self._cfg("network-first"))
		assert "Network-first" in sw

	def test_cache_first_strategy_comment(self):
		sw = _generate_service_worker(self._cfg("cache-first"))
		assert "Cache-first" in sw

	def test_stale_while_revalidate_comment(self):
		sw = _generate_service_worker(self._cfg("stale-while-revalidate"))
		assert "Stale-while-revalidate" in sw

	def test_sync_queue_included_when_enabled(self):
		sw = _generate_service_worker(self._cfg(sync=True))
		assert "pgaf-sync-queue" in sw

	def test_sync_queue_absent_when_disabled(self):
		sw = _generate_service_worker(self._cfg(sync=False))
		assert "pgaf-sync-queue" not in sw

	def test_offline_pages_in_precache(self):
		cfg = self._cfg()
		cfg.offline_pages = ["/offline-page", "/reports"]
		sw = _generate_service_worker(cfg)
		assert "/offline-page" in sw
		assert "/reports" in sw

	def test_push_listener_present(self):
		sw = _generate_service_worker(self._cfg())
		assert "push" in sw

	def test_app_name_in_console_log(self):
		sw = _generate_service_worker(self._cfg())
		assert "TestApp" in sw

	def test_skip_waiting_called(self):
		sw = _generate_service_worker(self._cfg())
		assert "skipWaiting" in sw

	def test_clients_claim_called(self):
		sw = _generate_service_worker(self._cfg())
		assert "clients.claim" in sw

	def test_api_non_get_skipped(self):
		sw = _generate_service_worker(self._cfg())
		assert "/api/" in sw


# --------------------------------------------------------------------------- #
# HTML snippet                                                                 #
# --------------------------------------------------------------------------- #

class TestGeneratePWAHTMLSnippet:
	def test_returns_string(self):
		snippet = generate_pwa_html_snippet()
		assert isinstance(snippet, str)

	def test_manifest_link_present(self):
		snippet = generate_pwa_html_snippet()
		assert 'rel="manifest"' in snippet

	def test_service_worker_register_present(self):
		snippet = generate_pwa_html_snippet()
		assert "serviceWorker" in snippet
		assert "register" in snippet

	def test_apple_mobile_web_app_capable(self):
		snippet = generate_pwa_html_snippet()
		assert "apple-mobile-web-app-capable" in snippet

	def test_theme_color_meta_present(self):
		snippet = generate_pwa_html_snippet()
		assert "theme-color" in snippet


# --------------------------------------------------------------------------- #
# Flask route integration — requires real Flask                               #
# --------------------------------------------------------------------------- #

try:
	from flask import Flask

	_HAS_FLASK = True
except ImportError:
	_HAS_FLASK = False


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask not installed")
class TestSetupPWARoutes:
	@pytest.fixture
	def app_disabled(self):
		from flask import Flask
		from pgappforge.pwa import setup_pwa, PWAConfig
		app = Flask(__name__)
		cfg = PWAConfig()
		cfg.enabled = False
		setup_pwa(app, cfg)
		app.config["TESTING"] = True
		return app

	@pytest.fixture
	def app_enabled(self):
		from flask import Flask
		from pgappforge.pwa import setup_pwa, PWAConfig
		app = Flask(__name__)
		cfg = PWAConfig()
		cfg.enabled = True
		cfg.app_name = "TestERP"
		cfg.cache_strategy = "network-first"
		setup_pwa(app, cfg)
		app.config["TESTING"] = True
		return app

	def test_disabled_no_manifest_route(self, app_disabled):
		with app_disabled.test_client() as c:
			rv = c.get("/manifest.json")
			assert rv.status_code == 404

	def test_enabled_manifest_200(self, app_enabled):
		with app_enabled.test_client() as c:
			rv = c.get("/manifest.json")
			assert rv.status_code == 200

	def test_manifest_content_type(self, app_enabled):
		with app_enabled.test_client() as c:
			rv = c.get("/manifest.json")
			assert "manifest+json" in rv.content_type or "json" in rv.content_type

	def test_manifest_valid_json(self, app_enabled):
		with app_enabled.test_client() as c:
			rv = c.get("/manifest.json")
			data = json.loads(rv.data)
			assert data["name"] == "TestERP"
			assert "icons" in data
			assert "shortcuts" in data

	def test_manifest_has_start_url(self, app_enabled):
		with app_enabled.test_client() as c:
			rv = c.get("/manifest.json")
			data = json.loads(rv.data)
			assert data["start_url"] == "/"

	def test_sw_js_200(self, app_enabled):
		with app_enabled.test_client() as c:
			rv = c.get("/sw.js")
			assert rv.status_code == 200

	def test_sw_js_content_type(self, app_enabled):
		with app_enabled.test_client() as c:
			rv = c.get("/sw.js")
			assert "javascript" in rv.content_type

	def test_sw_js_no_cache_header(self, app_enabled):
		with app_enabled.test_client() as c:
			rv = c.get("/sw.js")
			assert "no-store" in rv.headers.get("Cache-Control", "")

	def test_sw_js_service_worker_allowed_header(self, app_enabled):
		with app_enabled.test_client() as c:
			rv = c.get("/sw.js")
			assert rv.headers.get("Service-Worker-Allowed") == "/"

	def test_jinja_globals_set(self, app_enabled):
		assert app_enabled.jinja_env.globals["pwa_enabled"] is True
		assert app_enabled.jinja_env.globals["pwa_manifest_url"] == "/manifest.json"

	def test_jinja_globals_disabled(self, app_disabled):
		assert app_disabled.jinja_env.globals["pwa_enabled"] is False
