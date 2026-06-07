"""
pgappforge/plugins/erp/finance/hedge_accounting/__init__.py

IFRS 9 / ASC 815 Hedge Accounting plugin for PgAppForge ERP.

Entities:  HedgeRelationship, HedgeEffectivenessTest, HedgeFairValueMovement
Service:   HedgeAccountingService
Events:    hedge_accounting.relationship_designated, .effectiveness_tested,
           .oci_reclassified, .relationship_discontinued, .mtm_updated

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.hedge_accounting",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class HedgeAccountingPlugin(BasePlugin):
	"""IFRS 9 / ASC 815 Hedge Accounting plugin.

	Provides: formal hedge relationship designation, dollar-offset effectiveness
	testing (prospective and retrospective), OCI/P&L fair value movement split,
	OCI reclassification, and hedge discontinuation accounting. Supports all
	three IFRS 9 hedge types: fair value, cash flow, and net investment.
	"""

	name = "hedge_accounting"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="hedge_accounting",
			version="1.0.0",
			description=(
				"IFRS 9 / ASC 815 Hedge Accounting — formal designation of fair value, "
				"cash flow, and net investment hedge relationships; dollar-offset "
				"effectiveness testing; OCI/P&L fair value movement recording; "
				"OCI reclassification; and hedge discontinuation accounting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "hedge", "ifrs9", "asc815", "oci", "derivatives"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_hedge_read",
				"can_hedge_designate",
				"can_hedge_test",
				"can_hedge_mtm",
				"can_hedge_oci_reclassify",
				"can_hedge_discontinue",
				"can_hedge_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"hedge_accounting.relationship_designated",
			"hedge_accounting.effectiveness_tested",
			"hedge_accounting.oci_reclassified",
			"hedge_accounting.relationship_discontinued",
			"hedge_accounting.mtm_updated",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"exchange_rate.updated",   # trigger MTM revaluation for FX hedges
			"treasury.fx_deal_settled", # trigger OCI reclassification on settlement
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"HEDGE_MENU_CATEGORY": "Hedge Accounting",
			"HEDGE_EFFECTIVENESS_LOWER_BOUND": "0.80",
			"HEDGE_EFFECTIVENESS_UPPER_BOUND": "1.25",
		}
		self.config = {**defaults, **self.config}
		log.info("HedgeAccountingPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.hedge_accounting.models import (
			HedgeRelationship, HedgeEffectivenessTest, HedgeFairValueMovement,
		)
		return [HedgeRelationship, HedgeEffectivenessTest, HedgeFairValueMovement]


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> HedgeAccountingPlugin:
	return HedgeAccountingPlugin(appbuilder, config=config or {})


# Public re-exports
from pgappforge.plugins.erp.finance.hedge_accounting.models import (  # noqa: E402
	HedgeRelationship,
	HedgeEffectivenessTest,
	HedgeFairValueMovement,
)
from pgappforge.plugins.erp.finance.hedge_accounting.services import (  # noqa: E402
	HedgeAccountingService,
	HedgeAccountingError,
	HedgeNotFoundError,
	HedgeStatusError,
	HedgeIneffectiveError,
	HedgeDesignationDetails,
)
from pgappforge.plugins.erp.finance.hedge_accounting.events import (  # noqa: E402
	HedgeRelationshipDesignatedEvent,
	EffectivenessTestedEvent,
	OciReclassifiedEvent,
	HedgeRelationshipDiscontinuedEvent,
	HedgeMtmUpdatedEvent,
)

__all__ = [
	"HedgeAccountingPlugin",
	"create_plugin",
	# models
	"HedgeRelationship",
	"HedgeEffectivenessTest",
	"HedgeFairValueMovement",
	# services
	"HedgeAccountingService",
	"HedgeAccountingError",
	"HedgeNotFoundError",
	"HedgeStatusError",
	"HedgeIneffectiveError",
	"HedgeDesignationDetails",
	# events
	"HedgeRelationshipDesignatedEvent",
	"EffectivenessTestedEvent",
	"OciReclassifiedEvent",
	"HedgeRelationshipDiscontinuedEvent",
	"HedgeMtmUpdatedEvent",
]
