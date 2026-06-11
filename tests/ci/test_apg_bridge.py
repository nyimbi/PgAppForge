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

