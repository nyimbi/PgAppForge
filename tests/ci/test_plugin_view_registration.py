"""
tests/ci/test_plugin_view_registration.py

Verifies that plugin view modules:
1. Import cleanly (no missing deps, no circular imports)
2. Export view classes that each carry either `datamodel` or `route_base`

No Flask context, no DB, no mocks.  The FAB stubs in conftest.py handle the
flask_appbuilder import chain so SQLAInterface, ModelView, etc. are all stubs.
"""
from __future__ import annotations

import importlib

import pytest

PLUGIN_VIEW_MODULES = [
	"pgappforge.plugins.erp.hcm.benefits.views",
	"pgappforge.plugins.erp.operations.mrp.views",
	"pgappforge.plugins.erp.finance.revenue_recognition.views",
	"pgappforge.plugins.erp.grc.ethics.views",
	"pgappforge.plugins.erp.platform.tenant_control.views",
	"pgappforge.plugins.erp.platform.row_security.views",
	"pgappforge.plugins.erp.crm.loyalty.views",
	"pgappforge.plugins.erp.crm.subscriptions.views",
]


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_path", PLUGIN_VIEW_MODULES)
def test_views_module_importable(module_path: str) -> None:
	"""Module must import without raising any exception."""
	mod = importlib.import_module(module_path)
	# Has at least some public names — sanity check it's not empty
	assert hasattr(mod, "__all__") or len(dir(mod)) > 0


# ---------------------------------------------------------------------------
# __all__ integrity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_path", PLUGIN_VIEW_MODULES)
def test_views_have_all_dunder(module_path: str) -> None:
	"""Every plugin views module should declare __all__."""
	mod = importlib.import_module(module_path)
	assert hasattr(mod, "__all__"), f"{module_path} is missing __all__"


@pytest.mark.parametrize("module_path", PLUGIN_VIEW_MODULES)
def test_all_names_are_resolvable(module_path: str) -> None:
	"""Every name in __all__ must be importable from the module."""
	mod = importlib.import_module(module_path)
	all_names = getattr(mod, "__all__", [])
	for name in all_names:
		assert hasattr(mod, name), (
			f"{module_path}.__all__ lists '{name}' but it is not defined on the module"
		)


# ---------------------------------------------------------------------------
# View class structure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_path", PLUGIN_VIEW_MODULES)
def test_views_have_valid_structure(module_path: str) -> None:
	"""Each exported view class must declare datamodel (CRUD) or route_base (custom)."""
	mod = importlib.import_module(module_path)
	for name in getattr(mod, "__all__", []):
		cls = getattr(mod, name, None)
		if cls is None:
			continue
		assert hasattr(cls, "datamodel") or hasattr(cls, "route_base"), (
			f"{name} in {module_path} must have 'datamodel' or 'route_base'"
		)


@pytest.mark.parametrize("module_path", PLUGIN_VIEW_MODULES)
def test_no_exported_plain_functions(module_path: str) -> None:
	"""__all__ should only export classes, not bare functions or constants."""
	import inspect
	mod = importlib.import_module(module_path)
	for name in getattr(mod, "__all__", []):
		obj = getattr(mod, name, None)
		if obj is None:
			continue
		assert inspect.isclass(obj), (
			f"{module_path}.__all__ exports '{name}' which is not a class"
		)


# ---------------------------------------------------------------------------
# Per-module spot-checks on specific class sets
# ---------------------------------------------------------------------------

def test_benefits_views_exports_dashboard() -> None:
	mod = importlib.import_module("pgappforge.plugins.erp.hcm.benefits.views")
	assert "BenefitsDashboardView" in mod.__all__
	assert "BenefitPlanView"       in mod.__all__
	assert "BenefitEnrollmentView" in mod.__all__
	assert "BenefitClaimView"      in mod.__all__


def test_mrp_views_exports_expected_classes() -> None:
	mod = importlib.import_module("pgappforge.plugins.erp.operations.mrp.views")
	assert "MRPProductConfigView" in mod.__all__
	assert "MRPPlannedOrderView"  in mod.__all__
	assert "MRPRunView"           in mod.__all__
	assert "MRPDashboardView"     in mod.__all__


def test_revrec_views_exports_three_classes() -> None:
	mod = importlib.import_module("pgappforge.plugins.erp.finance.revenue_recognition.views")
	assert "RevRecContractView"    in mod.__all__
	assert "RevRecObligationView"  in mod.__all__
	assert "RevRecJournalEntryView" in mod.__all__


def test_ethics_views_exports_dashboard() -> None:
	mod = importlib.import_module("pgappforge.plugins.erp.grc.ethics.views")
	assert "EthicsReportView"          in mod.__all__
	assert "EthicsCaseView"            in mod.__all__
	assert "EthicsHotlineDashboardView" in mod.__all__


def test_tenant_control_views_exports_admin() -> None:
	mod = importlib.import_module("pgappforge.plugins.erp.platform.tenant_control.views")
	assert "TenantProfileView"     in mod.__all__
	assert "TenantUsageEventView"  in mod.__all__
	assert "TenantControlAdminView" in mod.__all__


def test_row_security_views_exports_admin() -> None:
	mod = importlib.import_module("pgappforge.plugins.erp.platform.row_security.views")
	assert "RowSecurityPolicyView" in mod.__all__
	assert "SecurityContextView"   in mod.__all__
	assert "RowSecurityAdminView"  in mod.__all__


def test_loyalty_views_exports_three_classes() -> None:
	mod = importlib.import_module("pgappforge.plugins.erp.crm.loyalty.views")
	assert "LoyaltyProgramView"     in mod.__all__
	assert "LoyaltyAccountView"     in mod.__all__
	assert "LoyaltyTransactionView" in mod.__all__


def test_subscriptions_views_exports_dashboard() -> None:
	mod = importlib.import_module("pgappforge.plugins.erp.crm.subscriptions.views")
	assert "SubscriptionPlanView"    in mod.__all__
	assert "SubscriptionView"        in mod.__all__
	assert "SubscriptionInvoiceView" in mod.__all__
	assert "MRRDashboardView"        in mod.__all__


# ---------------------------------------------------------------------------
# Dashboard views must use route_base (not datamodel)
# ---------------------------------------------------------------------------

def test_dashboard_views_use_route_base() -> None:
	"""Dashboard views that inherit BaseERPView must declare route_base, not datamodel."""
	dashboards = [
		("pgappforge.plugins.erp.hcm.benefits.views",              "BenefitsDashboardView"),
		("pgappforge.plugins.erp.operations.mrp.views",            "MRPDashboardView"),
		("pgappforge.plugins.erp.grc.ethics.views",                "EthicsHotlineDashboardView"),
		("pgappforge.plugins.erp.platform.tenant_control.views",   "TenantControlAdminView"),
		("pgappforge.plugins.erp.platform.row_security.views",     "RowSecurityAdminView"),
		("pgappforge.plugins.erp.crm.subscriptions.views",         "MRRDashboardView"),
	]
	for module_path, class_name in dashboards:
		mod = importlib.import_module(module_path)
		cls = getattr(mod, class_name)
		assert hasattr(cls, "route_base"), (
			f"{class_name} in {module_path} is a dashboard view and must have route_base"
		)
