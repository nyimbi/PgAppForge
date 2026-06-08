"""
pgappforge/plugins/erp/procurement/sourcing/__init__.py

Strategic Sourcing — RFQ management, competitive bidding, bid evaluation,
and purchase order award.

Domain: procurement
Depends on: foundation

Scope:
  - RFQ (Request for Quotation) lifecycle: DRAFT → PUBLISHED → CLOSED → AWARDED
  - Competitive, sole-source, and limited tender types
  - Supplier bid submission with deadline enforcement and duplicate prevention
  - Weighted multi-criteria bid evaluation (price / quality / delivery)
  - Automatic PO creation via SCM plugin on award
  - RFQ cancellation with reason tracking

Events emitted:
  procurement.sourcing.rfq.created
  procurement.sourcing.rfq.published
  procurement.sourcing.bid.submitted
  procurement.sourcing.bid.evaluated
  procurement.sourcing.po.awarded
  procurement.sourcing.rfq.cancelled

Events consumed:
  (none — sourcing is a standalone procurement plugin)

BPM capabilities:
  procurement.sourcing.create_rfq
  procurement.sourcing.award

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.procurement.sourcing",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.procurement.sourcing import SourcingPlugin
    plugin = SourcingPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SourcingPlugin(BasePlugin):
	"""Strategic Sourcing plugin.

	Provides:
	  - RFQ header + line items with evaluation criteria configuration
	  - Multi-supplier invitation list per RFQ
	  - Bid submission with deadline gating and duplicate prevention
	  - Weighted composite scoring: price (default 60%) + quality (20%) + delivery (20%)
	  - Automatic purchase order creation via SCM plugin on award
	  - RFQ cancellation with full audit trail
	  - BPM integrations: procurement.sourcing.create_rfq, procurement.sourcing.award
	"""

	name = "sourcing"
	domain = "procurement"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="sourcing",
			version="1.0.0",
			description=(
				"Strategic Sourcing — RFQ management, competitive bidding, "
				"bid evaluation, and purchase order award."
			),
			author="PgAppForge Contributors",
			tags=["procurement", "sourcing", "rfq", "rfp", "tendering", "supplier"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_sourcing_rfq_list",
				"can_sourcing_rfq_create",
				"can_sourcing_rfq_publish",
				"can_sourcing_rfq_cancel",
				"can_sourcing_rfq_award",
				"can_sourcing_bid_list",
				"can_sourcing_bid_submit",
				"can_sourcing_bid_evaluate",
				"can_sourcing_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"procurement.sourcing.rfq.created",
			"procurement.sourcing.rfq.published",
			"procurement.sourcing.bid.submitted",
			"procurement.sourcing.bid.evaluated",
			"procurement.sourcing.po.awarded",
			"procurement.sourcing.rfq.cancelled",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SOURCING_MENU_CATEGORY": "Procurement",
			"SOURCING_DEFAULT_CURRENCY": "USD",
			"SOURCING_DEFAULT_PRICE_WEIGHT": 60,
			"SOURCING_DEFAULT_QUALITY_WEIGHT": 20,
			"SOURCING_DEFAULT_DELIVERY_WEIGHT": 20,
		}
		self.config = {**defaults, **self.config}
		log.info("SourcingPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.procurement.sourcing.views import (
				RFQView,
				SupplierBidView,
			)
		except ImportError:
			log.warning("SourcingPlugin.register_views: views module not available — skipping.")
			return
		cat = self.config.get("SOURCING_MENU_CATEGORY", "Procurement")
		self.add_view(RFQView, "RFQs", icon="fa-bullhorn", category=cat)
		self.add_view(SupplierBidView, "Supplier Bids", icon="fa-gavel", category=cat)
		log.info("SourcingPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ, SupplierBid
		return [RFQ, SupplierBid]

	def activate(self) -> None:
		self.initialize()
		models = self.register_models()
		log.info("SourcingPlugin activated — %d models registered", len(models))
		return models


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> SourcingPlugin:
	return SourcingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.procurement.sourcing.models import (  # noqa: E402
	RFQ,
	SupplierBid,
	RFQ_TYPES,
	RFQ_STATUSES,
	BID_STATUSES,
)
from pgappforge.plugins.erp.procurement.sourcing.events import (  # noqa: E402
	RFQCreatedEvent,
	RFQPublishedEvent,
	BidSubmittedEvent,
	BidEvaluatedEvent,
	PurchaseOrderAwardedEvent,
	RFQCancelledEvent,
)
from pgappforge.plugins.erp.procurement.sourcing.services import (  # noqa: E402
	SourcingService,
	SourcingServiceError,
	RFQNotFoundError,
	BidNotFoundError,
	InvalidStatusTransitionError,
	DeadlinePassedError,
	DuplicateBidError,
)

__all__ = [
	# plugin
	"SourcingPlugin",
	"create_plugin",
	# models
	"RFQ",
	"SupplierBid",
	# enum sets
	"RFQ_TYPES",
	"RFQ_STATUSES",
	"BID_STATUSES",
	# events
	"RFQCreatedEvent",
	"RFQPublishedEvent",
	"BidSubmittedEvent",
	"BidEvaluatedEvent",
	"PurchaseOrderAwardedEvent",
	"RFQCancelledEvent",
	# services
	"SourcingService",
	"SourcingServiceError",
	"RFQNotFoundError",
	"BidNotFoundError",
	"InvalidStatusTransitionError",
	"DeadlinePassedError",
	"DuplicateBidError",
]
