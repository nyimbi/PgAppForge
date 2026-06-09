"""
tests/ci/test_real_estate_gaps.py

Import-level and static contract tests for the three real estate sub-plugins:
  - property_management
  - commercial
  - portfolio

Strategy:
  - Pure import + attribute inspection — no DB, no Flask context.
  - FAB stubs in conftest.py handle the flask_appbuilder import chain.
  - _xirr is exercised with synthetic cash-flow data (pure Python, no DB).
  - BPM action registration is verified by listing the registry after importing
    the services modules that contain @BPMActionRegistry.register decorators.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 1. Property Management — model tablenames
# ---------------------------------------------------------------------------

def test_property_management_models_import():
	from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
		PropertyUnit,
		TenantLease,
		RentPayment,
		LateFeeRecord,
		MaintenanceRequest,
		WorkOrder,
	)
	assert PropertyUnit.__tablename__ == "pm_unit"
	assert TenantLease.__tablename__ == "pm_tenant_lease"


# ---------------------------------------------------------------------------
# 2. Commercial — model tablenames
# ---------------------------------------------------------------------------

def test_commercial_models_import():
	from pgappforge.plugins.erp.industry.real_estate.commercial.models import (
		SpaceUnit,
		CommercialLease,
		CAMReconciliation,
		LOI,
		LeaseAbstract,
	)
	assert SpaceUnit.__tablename__ == "re_com_space"


# ---------------------------------------------------------------------------
# 3. Portfolio — model tablenames
# ---------------------------------------------------------------------------

def test_portfolio_models_import():
	from pgappforge.plugins.erp.industry.real_estate.portfolio.models import (
		PropertyPortfolio,
		PropertyDebt,
		CapExRecord,
		InvestorHolding,
		DistributionRecord,
	)
	assert PropertyPortfolio.__tablename__ == "re_portfolio"


# ---------------------------------------------------------------------------
# 4. PropertyManagementPlugin metadata
# ---------------------------------------------------------------------------

def test_property_management_plugin_metadata():
	from pgappforge.plugins.erp.industry.real_estate.property_management import PropertyManagementPlugin
	p = PropertyManagementPlugin.__new__(PropertyManagementPlugin)
	assert p.name == "property_management"
	assert "real_estate" in p.depends_on


# ---------------------------------------------------------------------------
# 5. CommercialREPlugin metadata
# ---------------------------------------------------------------------------

def test_commercial_plugin_metadata():
	from pgappforge.plugins.erp.industry.real_estate.commercial import CommercialREPlugin
	assert CommercialREPlugin.name == "commercial_re"


# ---------------------------------------------------------------------------
# 6. PortfolioPlugin metadata
# ---------------------------------------------------------------------------

def test_portfolio_plugin_metadata():
	from pgappforge.plugins.erp.industry.real_estate.portfolio import PortfolioPlugin
	assert PortfolioPlugin.name == "real_estate_portfolio"


# ---------------------------------------------------------------------------
# 7. PropertyManagementService callable surface
# ---------------------------------------------------------------------------

def test_pm_service_importable():
	from pgappforge.plugins.erp.industry.real_estate.property_management.services import (
		PropertyManagementService,
	)
	assert callable(PropertyManagementService().get_rent_roll)
	assert callable(PropertyManagementService().apply_late_fees)


# ---------------------------------------------------------------------------
# 8. CommercialLeaseService callable surface
# ---------------------------------------------------------------------------

def test_commercial_service_importable():
	from pgappforge.plugins.erp.industry.real_estate.commercial.services import CommercialLeaseService
	assert callable(CommercialLeaseService().reconcile_cam)


# ---------------------------------------------------------------------------
# 9. PortfolioAnalyticsService callable surface
# ---------------------------------------------------------------------------

def test_portfolio_service_importable():
	from pgappforge.plugins.erp.industry.real_estate.portfolio.services import PortfolioAnalyticsService
	assert callable(PortfolioAnalyticsService().compute_irr)
	assert callable(PortfolioAnalyticsService().get_cap_rate)


# ---------------------------------------------------------------------------
# 10. _xirr helper — basic ≈10% IRR
# ---------------------------------------------------------------------------

def test_xirr_helper_basic():
	from pgappforge.plugins.erp.industry.real_estate.portfolio.services import _xirr
	from datetime import date
	# Investment of 100_000 with return of 110_000 after 1 year ≈ 10% IRR
	flows = [(date(2025, 1, 1), -100_000), (date(2026, 1, 1), 110_000)]
	rate = _xirr(flows)
	assert rate is not None
	assert abs(float(rate) - 0.10) < 0.01


# ---------------------------------------------------------------------------
# 11. CAM reconciliation method present
# ---------------------------------------------------------------------------

def test_cam_reconciliation_variance():
	from pgappforge.plugins.erp.industry.real_estate.commercial.services import CommercialLeaseService
	svc = CommercialLeaseService()
	# Verify reconcile_cam logic exists (import only, no DB needed)
	assert hasattr(svc, "reconcile_cam")


# ---------------------------------------------------------------------------
# 12. BPM action registry — all required real-estate actions registered
# ---------------------------------------------------------------------------

def test_bpm_registrations_present():
	# Importing the services modules triggers @BPMActionRegistry.register decorators.
	import pgappforge.plugins.erp.industry.real_estate.services  # noqa: F401 — registers realestate.* + rental.* + lease.*
	import pgappforge.plugins.erp.industry.real_estate.property_management.services  # noqa: F401 — registers pm.*
	import pgappforge.plugins.erp.industry.real_estate.commercial.services  # noqa: F401 — registers re_com.*
	import pgappforge.plugins.erp.industry.real_estate.portfolio.services  # noqa: F401 — registers re_portfolio.*

	from pgappforge.plugins.workflow.engine import BPMActionRegistry
	actions = {c["name"] for c in BPMActionRegistry.list_capabilities()}

	for expected in [
		"realestate.list_property",
		"realestate.calculate_avm",
		"rental.create_order",
		"lease.terminate_lease",
		"pm.record_payment",
		"re_com.reconcile_cam",
		"re_portfolio.get_cap_rate",
	]:
		assert expected in actions, f"BPM action {expected!r} not registered"


# ---------------------------------------------------------------------------
# 13. RentPaymentView security contract — read-only base_permissions
# ---------------------------------------------------------------------------

def test_view_security_contracts_re():
	from pgappforge.plugins.erp.industry.real_estate.property_management.views import (
		RentPaymentView,
		PropertyManagementDashboardView,
	)
	# Rent payments are read-only — base_permissions must be a subset of list+show
	assert set(RentPaymentView.base_permissions) <= {"can_list", "can_show"}
