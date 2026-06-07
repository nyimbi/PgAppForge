"""
pgappforge/plugins/erp/finance/material_ledger/__init__.py

Material Ledger / Actual Costing plugin for PgAppForge ERP.

Entities:  CostingPeriod, MaterialLedger, MaterialMovement, CostSettlement
Service:   MaterialLedgerService
Events:    material_ledger.period_opened, .period_closed, .price_variance_posted,
           .cost_revalued, .settlement_run

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.material_ledger",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class MaterialLedgerPlugin(BasePlugin):
	"""Material Ledger / Actual Costing plugin.

	Provides: costing period management, per-material/per-plant cost
	accumulation (standard + variances), multi-level actual cost settlement,
	inventory revaluation at actual price, and integration with purchasing
	(PPV), production orders, and exchange rate differences.
	"""

	name = "material_ledger"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="material_ledger",
			version="1.0.0",
			description=(
				"Material Ledger / Actual Costing — costing period management, "
				"per-material/per-plant actual cost accumulation (standard price + "
				"purchase price variance + exchange rate diff + production variance), "
				"multi-level settlement run, and inventory revaluation to actual cost."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "costing", "material_ledger", "actual_costing", "ppv"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ml_period_read",
				"can_ml_period_open",
				"can_ml_period_close",
				"can_ml_movement_post",
				"can_ml_settlement_run",
				"can_ml_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"material_ledger.period_opened",
			"material_ledger.period_closed",
			"material_ledger.price_variance_posted",
			"material_ledger.cost_revalued",
			"material_ledger.settlement_run",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"purchase_order.invoice_verified",  # PPV posting on invoice verification
			"production_order.settled",          # absorption of production variances
			"exchange_rate.updated",             # FX difference on open PO receipts
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"ML_MENU_CATEGORY": "Material Ledger",
			"ML_DEFAULT_PLANT": "MAIN",
		}
		self.config = {**defaults, **self.config}
		log.info("MaterialLedgerPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.material_ledger.models import (
			CostingPeriod, MaterialLedger, MaterialMovement, CostSettlement,
		)
		return [CostingPeriod, MaterialLedger, MaterialMovement, CostSettlement]


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> MaterialLedgerPlugin:
	return MaterialLedgerPlugin(appbuilder, config=config or {})


# Public re-exports
from pgappforge.plugins.erp.finance.material_ledger.models import (  # noqa: E402
	CostingPeriod,
	MaterialLedger,
	MaterialMovement,
	CostSettlement,
)
from pgappforge.plugins.erp.finance.material_ledger.services import (  # noqa: E402
	MaterialLedgerService,
	MaterialLedgerError,
	PeriodNotFoundError,
	PeriodStatusError,
	LedgerNotFoundError,
)
from pgappforge.plugins.erp.finance.material_ledger.events import (  # noqa: E402
	MaterialPeriodOpenedEvent,
	MaterialPeriodClosedEvent,
	PriceVariancePostedEvent,
	MaterialCostRevaluedEvent,
	CostSettlementRunEvent,
)

__all__ = [
	"MaterialLedgerPlugin",
	"create_plugin",
	# models
	"CostingPeriod",
	"MaterialLedger",
	"MaterialMovement",
	"CostSettlement",
	# services
	"MaterialLedgerService",
	"MaterialLedgerError",
	"PeriodNotFoundError",
	"PeriodStatusError",
	"LedgerNotFoundError",
	# events
	"MaterialPeriodOpenedEvent",
	"MaterialPeriodClosedEvent",
	"PriceVariancePostedEvent",
	"MaterialCostRevaluedEvent",
	"CostSettlementRunEvent",
]
