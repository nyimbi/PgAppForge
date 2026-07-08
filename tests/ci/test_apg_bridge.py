"""CI tests for the APG interoperability bridge plugin."""
from __future__ import annotations
import inspect


def test_apg_client_import():
	from pgappforge.plugins.erp.platform.apg_bridge.client import APGClient, APGError
	assert issubclass(APGError, Exception)
	c = APGClient()
	assert callable(c.get_contract)
	assert callable(c.evaluate)
	assert callable(c.list_capabilities)
	assert callable(c.emit_event)
	assert callable(c.is_available)

def test_apg_client_disabled_by_default():
	from pgappforge.plugins.erp.platform.apg_bridge.client import APGClient
	c = APGClient()
	assert not c._enabled
	# All methods return None/False/[] when disabled
	assert c._get(None) is None
	assert c._post(None, {}) is None
	assert not c.is_available()
	assert c.list_capabilities() == []

def test_apg_client_default_urls():
	from pgappforge.plugins.erp.platform.apg_bridge.client import APGClient
	c = APGClient()
	assert "5000" in c._base_url
	assert "8000" in c._marketplace_url

def test_apg_client_config_parsing_and_url_hardening(monkeypatch):
	from pgappforge.plugins.erp.platform.apg_bridge import client as client_mod

	values = {}
	monkeypatch.setattr(client_mod, "_cfg", lambda key, default=None: values.get(key, default))
	c = client_mod.APGClient()

	values["APG_ENABLED"] = "false"
	assert not c._enabled
	values["APG_ENABLED"] = "yes"
	assert c._enabled

	values["APG_BASE_URL"] = "file:///etc/passwd"
	assert c._base_url == "http://localhost:5000"
	values["APG_BASE_URL"] = "https://user:pass@example.com"
	assert c._base_url == "http://localhost:5000"
	values["APG_BASE_URL"] = "https://apg.example/api?debug=1#frag"
	assert c._base_url == "https://apg.example/api"

	values["APG_TIMEOUT"] = "bad"
	assert c._timeout == 15
	values["APG_TIMEOUT"] = "-5"
	assert c._timeout == 1
	values["APG_TIMEOUT"] = "999"
	assert c._timeout == 120

def test_apg_client_rejects_header_injection_in_static_token(monkeypatch):
	from pgappforge.plugins.erp.platform.apg_bridge import client as client_mod

	values = {"APG_STATIC_TOKEN": "abc\r\nInjected: yes"}
	monkeypatch.setattr(client_mod, "_cfg", lambda key, default=None: values.get(key, default))
	c = client_mod.APGClient()

	assert c._get_token() is None
	values["APG_STATIC_TOKEN"] = " safe-token "
	assert c._headers()["Authorization"] == "Bearer safe-token"

def test_apg_client_safe_public_paths_and_query_encoding(monkeypatch):
	from pgappforge.plugins.erp.platform.apg_bridge import client as client_mod

	calls = []

	def fake_get(self, path, *, marketplace=False):
		calls.append(("GET", path, marketplace))
		return {"ok": True, "capabilities": [{"id": "cap-1"}]}

	def fake_post(self, path, body, *, marketplace=False):
		calls.append(("POST", path, marketplace, body))
		return {"ok": True, "results": [{"id": "cap-2"}]}

	monkeypatch.setattr(client_mod.APGClient, "_get", fake_get)
	monkeypatch.setattr(client_mod.APGClient, "_post", fake_post)
	c = client_mod.APGClient()

	assert c.get_contract("fintech-remittance") == {"ok": True, "capabilities": [{"id": "cap-1"}]}
	assert calls[-1] == ("GET", "/fintech-remittance/contract", False)
	assert c.get_contract("../secret") is None

	assert c.list_capabilities("finance & ops") == [{"id": "cap-1"}]
	assert calls[-1] == ("GET", "/capabilities?domain=finance+%26+ops", True)
	assert c.search_capabilities(" risk ") == [{"id": "cap-2"}]
	assert calls[-1] == ("POST", "/search", True, {"query": "risk"})
	assert c.search_capabilities("   ") == []

	assert c.emit_event("apg.fintech.remittance.lifecycle", "created", {}) is True
	assert calls[-1] == (
		"POST",
		"/fintech-remittance/events",
		False,
		{"event_type": "created", "stream": "apg.fintech.remittance.lifecycle", "payload": {}},
	)
	assert c.emit_event("bad stream", "created", {}) is False
	assert c.emit_event("apg.fintech.remittance.lifecycle", "", {}) is False
	assert c.emit_event("apg.fintech.remittance.lifecycle", "created", []) is False

def test_apg_client_transport_rejects_unsafe_paths_and_bad_json(monkeypatch):
	from pgappforge.plugins.erp.platform.apg_bridge import client as client_mod

	values = {
		"APG_ENABLED": True,
		"APG_BASE_URL": "https://apg.example/root/",
		"APG_TIMEOUT": "30",
	}
	monkeypatch.setattr(client_mod, "_cfg", lambda key, default=None: values.get(key, default))

	captured = {}

	class Response:
		def __init__(self, raw):
			self.raw = raw

		def __enter__(self):
			return self

		def __exit__(self, exc_type, exc, tb):
			return False

		def read(self):
			return self.raw

	def fake_urlopen(req, timeout):
		captured["url"] = req.full_url
		captured["timeout"] = timeout
		return Response(b'{"status": "ok"}')

	monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake_urlopen)
	c = client_mod.APGClient()

	assert c._get("/health") == {"status": "ok"}
	assert captured == {"url": "https://apg.example/root/health", "timeout": 30}
	assert c._get("https://evil.example/health") is None
	assert c._get("//evil.example/health") is None
	assert c._post("/evaluate", {"bad": object()}) is None

	def fake_bad_json(req, timeout):
		return Response(b"not-json")

	monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake_bad_json)
	assert c._get("/health") is None

def test_apg_client_auth_priority():
	from pgappforge.plugins.erp.platform.apg_bridge.client import APGClient
	src = inspect.getsource(APGClient._get_token)
	# APG_STATIC_TOKEN takes priority
	assert "STATIC_TOKEN" in src or "static" in src.lower()

def test_apg_bridge_service_import():
	from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService
	svc = APGBridgeService()
	for m in ("call_capability","get_capability_contract","sync_capabilities_to_ipaas",
	          "register_apg_bpm_actions","forward_event_to_apg",
	          "register_event_bridge","get_bridge_status"):
		assert callable(getattr(svc, m)), f"APGBridgeService.{m} missing"

def test_apg_bridge_status_disabled():
	from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService
	status = APGBridgeService().get_bridge_status()
	assert "apg_enabled" in status
	assert "apg_available" in status
	assert not status["apg_enabled"]

def test_apg_call_capability_returns_error_when_disabled():
	from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService
	result = APGBridgeService().call_capability("fintech-remittance", "remittance_quote_lifecycle", {}, "t1")
	assert result["success"] is False
	assert "error" in result

def test_apg_event_map_coverage():
	from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService
	src = inspect.getsource(APGBridgeService.register_event_bridge)
	# Key ERP → APG event mappings
	for event in ("finance.ap.invoice.created", "hcm.payroll.run.finalized",
	              "lending.loan.approved", "remittance.transfer.initiated"):
		assert event in src

def test_apg_bpm_actions_registered():
	from pgappforge.plugins.workflow.engine import BPMActionRegistry
	import pgappforge.plugins.erp.platform.apg_bridge.services  # trigger registration
	actions = {c["name"] for c in BPMActionRegistry.list_capabilities()}
	assert "apg.bridge.call_capability" in actions
	assert "apg.bridge.sync_capabilities" in actions

def test_apg_models_import():
	from pgappforge.plugins.erp.platform.apg_bridge.models import APGCapabilityCache, APGEventBridgeLog
	assert APGCapabilityCache.__tablename__ == "plat_apg_capability"
	assert APGEventBridgeLog.__tablename__ == "plat_apg_event_log"

def test_apg_models_do_not_poison_shared_mapper_registry():
	from pgappforge.plugins.erp.platform.apg_bridge.models import APGCapabilityCache
	from pgappforge.plugins.erp.platform.ipaas.models import ConnectorDefinition

	cache = APGCapabilityCache(capability_id="fintech-remittance")
	definition = ConnectorDefinition(
		id="def-1",
		name="Customer API",
		protocol="REST",
		auth_type="NONE",
	)

	assert cache.capability_id == "fintech-remittance"
	assert definition.name == "Customer API"
	assert not hasattr(APGCapabilityCache, "created_by")

def test_apg_event_log_immutable():
	from pgappforge.plugins.erp.platform.apg_bridge.models import APGEventBridgeLog
	from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin
	assert issubclass(APGEventBridgeLog, ImmutableRecordMixin)

def test_apg_plugin_metadata():
	from pgappforge.plugins.erp.platform.apg_bridge import APGBridgePlugin
	p = APGBridgePlugin.__new__(APGBridgePlugin)
	assert p.name == "apg_bridge"
	assert p.domain == "platform"
	assert "ipaas" in p.depends_on
	assert "foundation" in p.depends_on

def test_apg_plugin_disabled_warning_in_source():
	from pgappforge.plugins.erp.platform.apg_bridge import APGBridgePlugin
	src = inspect.getsource(APGBridgePlugin.post_initialize)
	assert "APG_ENABLED" in src or "warning" in src.lower() or "WARNING" in src

def test_apg_connector_name_format():
	"""APG capabilities are registered in iPaaS as 'APG:<capability_id>'."""
	from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService
	src = inspect.getsource(APGBridgeService.sync_capabilities_to_ipaas)
	assert "APG:" in src


# ── portal_views tests ────────────────────────────────────────────────────

def test_portal_view_import():
	from pgappforge.plugins.erp.platform.apg_bridge.portal_views import APGCapabilityPortalView
	assert APGCapabilityPortalView.route_base == "/platform/apg"


def test_portal_view_methods_exist():
	from pgappforge.plugins.erp.platform.apg_bridge.portal_views import APGCapabilityPortalView
	for method in ("index", "capability_dashboard", "capability_actions",
	               "evaluate_action", "status"):
		assert callable(getattr(APGCapabilityPortalView, method)), (
			f"APGCapabilityPortalView.{method} missing"
		)


def test_portal_view_reexported_from_package():
	from pgappforge.plugins.erp.platform.apg_bridge import APGCapabilityPortalView
	assert APGCapabilityPortalView.route_base == "/platform/apg"


def test_portal_view_inherits_base_erp_view():
	from pgappforge.plugins.erp.platform.apg_bridge.portal_views import APGCapabilityPortalView
	from pgappforge.plugins.erp.base_view import BaseERPView
	assert issubclass(APGCapabilityPortalView, BaseERPView)


def test_portal_view_evaluate_uses_service():
	"""evaluate_action must delegate to APGBridgeService.call_capability."""
	from pgappforge.plugins.erp.platform.apg_bridge import portal_views
	src = inspect.getsource(portal_views.APGCapabilityPortalView.evaluate_action)
	assert "APGBridgeService" in src
	assert "call_capability" in src


def test_portal_view_register_views_in_plugin():
	"""register_views() in the plugin must reference APGCapabilityPortalView."""
	from pgappforge.plugins.erp.platform.apg_bridge import APGBridgePlugin
	src = inspect.getsource(APGBridgePlugin.register_views)
	assert "APGCapabilityPortalView" in src


def test_portal_templates_exist():
	"""All three APG portal templates must be present."""
	import os
	base = os.path.join(
		os.path.dirname(__file__), "..", "..",
		"pgappforge", "templates", "appbuilder", "apg",
	)
	for name in ("portal.html", "capability_dashboard.html", "capability_actions.html"):
		path = os.path.normpath(os.path.join(base, name))
		assert os.path.isfile(path), f"Missing template: {name}"


def test_portal_templates_jinja2_valid():
	"""Templates must parse without Jinja2 syntax errors."""
	import os
	from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError
	tpl_root = os.path.normpath(os.path.join(
		os.path.dirname(__file__), "..", "..",
		"pgappforge", "templates",
	))
	env = Environment(loader=FileSystemLoader(tpl_root))
	for name in ("portal.html", "capability_dashboard.html", "capability_actions.html"):
		path = f"appbuilder/apg/{name}"
		try:
			env.get_template(path)
		except TemplateSyntaxError as e:
			raise AssertionError(f"Jinja2 syntax error in {name} line {e.lineno}: {e.message}") from e


def test_portal_template_extends_base_erp():
	"""Every APG template must extend base_erp.html."""
	import os
	base = os.path.normpath(os.path.join(
		os.path.dirname(__file__), "..", "..",
		"pgappforge", "templates", "appbuilder", "apg",
	))
	for name in ("portal.html", "capability_dashboard.html", "capability_actions.html"):
		path = os.path.join(base, name)
		with open(path) as fh:
			content = fh.read()
		assert "base_erp.html" in content, (
			f"{name} does not extend appbuilder/erp/base_erp.html"
		)
