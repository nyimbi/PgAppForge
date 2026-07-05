"""
pgappforge/plugins/erp/procurement/supplier_portal/__init__.py

Supplier Portal — supplier registration, KYC workflow, bank detail verification,
performance scorecard, and suspension management.

Domain: procurement
Depends on: foundation

Scope:
  - Supplier self-registration with company + tax + contact details
  - KYC document upload and approval workflow (PENDING → APPROVED)
  - Bank detail capture and verification flag
  - Periodic performance scorecards with weighted composite scoring
  - Rolling overall_score maintained on supplier profile
  - Supplier suspension with reason audit trail
  - APPROVED supplier query with category filter

Events emitted:
  procurement.supplier_portal.registered
  procurement.supplier_portal.kyc.approved
  procurement.supplier_portal.bank.verified
  procurement.supplier_portal.rated
  procurement.supplier_portal.suspended

Events consumed:
  (none — supplier_portal is a standalone procurement plugin)

BPM capabilities:
  procurement.supplier_portal.approve_kyc
  procurement.supplier_portal.rate

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.procurement.supplier_portal",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.procurement.supplier_portal import SupplierPortalPlugin
    plugin = SupplierPortalPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SupplierPortalPlugin(BasePlugin):
	"""Supplier Portal plugin.

	Provides:
	  - Supplier profile registry with auto-generated supplier_ref
	  - KYC document management with approval workflow
	  - Bank detail capture with verification flag and timestamp
	  - Periodic performance scorecards:
	      composite = 0.4*on_time + 0.3*quality + 0.2*invoice_accuracy + 0.1*responsiveness
	  - Rolling overall_score on supplier profile
	  - Supplier suspension with reason and event trail
	  - Category-filtered APPROVED supplier queries
	  - BPM integrations: approve_kyc, rate
	"""

	name = "supplier_portal"
	domain = "procurement"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="supplier_portal",
			version="1.0.0",
			description=(
				"Supplier Portal — supplier registration, KYC workflow, "
				"bank detail verification, performance scorecard, and suspension management."
			),
			author="PgAppForge Contributors",
			tags=["procurement", "supplier", "kyc", "vendor-management", "portal"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_supplier_portal_list",
				"can_supplier_portal_register",
				"can_supplier_portal_kyc_submit",
				"can_supplier_portal_kyc_approve",
				"can_supplier_portal_kyc_reject",
				"can_supplier_portal_bank_verify",
				"can_supplier_portal_rate",
				"can_supplier_portal_suspend",
				"can_supplier_portal_preferred_flag",
				"can_supplier_portal_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"procurement.supplier_portal.registered",
			"procurement.supplier_portal.kyc.approved",
			"procurement.supplier_portal.bank.verified",
			"procurement.supplier_portal.rated",
			"procurement.supplier_portal.suspended",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SUPPLIER_PORTAL_MENU_CATEGORY": "Procurement",
			"SUPPLIER_PORTAL_PERFORMANCE_WEIGHTS": {
				"on_time": "0.4",
				"quality": "0.3",
				"invoice": "0.2",
				"responsiveness": "0.1",
			},
		}
		self.config = {**defaults, **self.config}
		log.info("SupplierPortalPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.procurement.supplier_portal.views import (
				SupplierPerformanceCardView,
				SupplierProfileView,
				SupplierRiskView,
				SupplierScorecardView,
			)
		except ImportError:
			log.warning("SupplierPortalPlugin.register_views: views module not available — skipping.")
			return
		cat = self.config.get("SUPPLIER_PORTAL_MENU_CATEGORY", "Procurement")
		self.add_view(SupplierProfileView, "Suppliers", icon="fa-truck", category=cat)
		self.add_view(SupplierPerformanceCardView, "Performance", icon="fa-star", category=cat)
		self.add_view(SupplierScorecardView, "Scorecards", icon="fa-dashboard", category=cat)
		self.add_view(SupplierRiskView, "Supplier Risks", icon="fa-warning", category=cat)
		log.info("SupplierPortalPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.procurement.supplier_portal.models import (
			SupplierPerformanceCard,
			SupplierProfile,
			SupplierRisk,
			SupplierScorecard,
		)
		return [SupplierProfile, SupplierPerformanceCard, SupplierScorecard, SupplierRisk]

	def activate(self) -> None:
		self.initialize()
		models = self.register_models()
		log.info("SupplierPortalPlugin activated — %d models registered", len(models))
		return models


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> SupplierPortalPlugin:
	return SupplierPortalPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.procurement.supplier_portal.models import (  # noqa: E402
	KYC_STATUSES,
	PRIMARY_CATEGORIES,
	RISK_TYPES,
	SupplierPerformanceCard,
	SupplierProfile,
	SupplierRisk,
	SupplierScorecard,
)
from pgappforge.plugins.erp.procurement.supplier_portal.events import (  # noqa: E402
	SupplierRegisteredEvent,
	KYCApprovedEvent,
	SupplierBankDetailsVerifiedEvent,
	SupplierPerformanceRatedEvent,
	SupplierSuspendedEvent,
)
from pgappforge.plugins.erp.procurement.supplier_portal.services import (  # noqa: E402
	SupplierPortalService,
	SupplierPortalServiceError,
	SupplierNotFoundError,
	InvalidStatusTransitionError,
	PerformanceCardNotFoundError,
)

__all__ = [
	# plugin
	"SupplierPortalPlugin",
	"create_plugin",
	# models
	"SupplierProfile",
	"SupplierPerformanceCard",
	"SupplierScorecard",
	"SupplierRisk",
	# enum sets
	"KYC_STATUSES",
	"PRIMARY_CATEGORIES",
	"RISK_TYPES",
	# events
	"SupplierRegisteredEvent",
	"KYCApprovedEvent",
	"SupplierBankDetailsVerifiedEvent",
	"SupplierPerformanceRatedEvent",
	"SupplierSuspendedEvent",
	# services
	"SupplierPortalService",
	"SupplierPortalServiceError",
	"SupplierNotFoundError",
	"InvalidStatusTransitionError",
	"PerformanceCardNotFoundError",
]
