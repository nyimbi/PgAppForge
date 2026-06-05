"""
pgappforge/plugins/erp/industry/consumer_goods/__init__.py

Consumer Goods plugin — trade promotions, retail execution, shelf compliance,
planogram management, distribution coverage.

Domain: industry
Depends on: foundation, crm.sales, inventory

Events emitted:
  cg.promotion.launched
  cg.retail.visit.completed
  cg.shelf.compliance.flagged

Subscribed events:
  inventory.stock.low
  crm.sales.order.created

Usage
-----
Add to PGAPPFORGE_PLUGINS::

    "pgappforge.plugins.erp.industry.consumer_goods"

Or instantiate directly::

    from pgappforge.plugins.erp.industry.consumer_goods import ConsumerGoodsPlugin
    plugin = ConsumerGoodsPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ConsumerGoodsPlugin(BasePlugin):
	"""Consumer Goods ERP plugin.

	Registers 4 view groups covering:
	  - Trade Promotions (TPM)
	  - Retail Execution / field audits
	  - Planogram compliance
	  - Promotion Claims
	"""

	name = "consumer_goods"
	domain = "industry"
	depends_on: list[str] = ["foundation", "crm.sales", "inventory"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="consumer_goods",
			version="1.0.0",
			description=(
				"Consumer Goods — trade promotion management, retail execution, "
				"shelf/planogram compliance, promotion claims, distribution coverage."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "consumer_goods", "tpm", "retail", "planogram", "fmcg"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_cg_promotion_list",
				"can_cg_promotion_write",
				"can_cg_promotion_approve",
				"can_cg_retail_visit_list",
				"can_cg_retail_visit_write",
				"can_cg_planogram_list",
				"can_cg_planogram_write",
				"can_cg_claim_list",
				"can_cg_claim_write",
				"can_cg_claim_approve",
				"can_cg_analytics_view",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"cg.promotion.launched",
			"cg.retail.visit.completed",
			"cg.shelf.compliance.flagged",
		]

	def subscribe_to(self) -> list[str]:
		"""CG consumes:
		- inventory.stock.low:          check if OOS during active promo
		- crm.sales.order.created:      validate promo eligibility on order
		"""
		return [
			"inventory.stock.low",
			"crm.sales.order.created",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CG_MENU_CATEGORY": "Consumer Goods",
			"CG_PROMO_DEFAULT_CURRENCY": "USD",
			"CG_COMPLIANCE_PASS_THRESHOLD": "0.80",
			"CG_RETAIL_VISIT_REQUIRE_GPS": False,
		}
		self.config = {**defaults, **self.config}
		log.info("ConsumerGoodsPlugin initialised (config: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.consumer_goods.views import (
			TradePromotionView,
			RetailExecutionView,
			PlanoGramView,
			PromotionClaimView,
		)
		cat = self.config.get("CG_MENU_CATEGORY", "Consumer Goods")
		self.add_view(TradePromotionView, "Trade Promotions", icon="fa-tags", category=cat)
		self.add_view(RetailExecutionView, "Retail Execution", icon="fa-map-marker", category=cat)
		self.add_view(PlanoGramView, "Planograms", icon="fa-th", category=cat)
		self.add_view(PromotionClaimView, "Promotion Claims", icon="fa-file-text-o", category=cat)
		log.info("ConsumerGoodsPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.consumer_goods.models import (
			TradePromotion,
			PromotionClaim,
			RetailExecution,
			PlanoGram,
		)
		return [
			TradePromotion,
			PromotionClaim,
			RetailExecution,
			PlanoGram,
		]


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> ConsumerGoodsPlugin:
	return ConsumerGoodsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.consumer_goods.models import (  # noqa: E402
	TradePromotion,
	PromotionClaim,
	RetailExecution,
	PlanoGram,
)
from pgappforge.plugins.erp.industry.consumer_goods.events import (  # noqa: E402
	PromotionApprovedEvent,
	PromotionClaimSubmittedEvent,
	PromotionClaimPaidEvent,
	RetailVisitSubmittedEvent,
	PlanoGramUpdatedEvent,
)
from pgappforge.plugins.erp.industry.consumer_goods.services import (  # noqa: E402
	ConsumerGoodsService,
	ConsumerGoodsServiceError,
	PromotionNotFoundError,
	BudgetExceededError,
	ClaimNotFoundError,
)

__all__ = [
	"ConsumerGoodsPlugin",
	"create_plugin",
	# models
	"TradePromotion",
	"PromotionClaim",
	"RetailExecution",
	"PlanoGram",
	# events
	"PromotionApprovedEvent",
	"PromotionClaimSubmittedEvent",
	"PromotionClaimPaidEvent",
	"RetailVisitSubmittedEvent",
	"PlanoGramUpdatedEvent",
	# services
	"ConsumerGoodsService",
	"ConsumerGoodsServiceError",
	"PromotionNotFoundError",
	"BudgetExceededError",
	"ClaimNotFoundError",
]
