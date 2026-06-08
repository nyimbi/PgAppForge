"""
pgappforge/plugins/erp/operations/repair/__init__.py

RepairPlugin — Repair / RMA plugin.

Domain: operations
Depends on: foundation

Scope: full repair lifecycle — intake, diagnosis, parts ordering,
       repair execution, QC, customer return, and warranty claims.

Events emitted:
  ops.repair.created
  ops.repair.diagnosed
  ops.repair.completed
  ops.repair.returned
  ops.repair.warranty.created

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.repair",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.repair import RepairPlugin
    plugin = RepairPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class RepairPlugin(BasePlugin):
	"""Repair / RMA plugin.

	Provides:
	  - Repair order lifecycle (RECEIVED → DIAGNOSING → IN_REPAIR → QC → RETURNED)
	  - Technician assignment and diagnosis recording
	  - Parts-used tracking (JSONB snapshot per order)
	  - Warranty claim management
	  - BPM-callable actions for workflow integration
	"""

	name = "repair"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="repair",
			version="1.0.0",
			description=(
				"Repair / RMA — full repair lifecycle: order intake, technician assignment, "
				"diagnosis, parts tracking, QC, customer return, and warranty claims."
			),
			author="PgAppForge Contributors",
			tags=["ops", "repair", "rma", "warranty"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_repair_order_list",
				"can_repair_order_create",
				"can_repair_order_assign",
				"can_repair_order_diagnose",
				"can_repair_order_complete",
				"can_repair_order_return",
				"can_repair_order_cancel",
				"can_repair_warranty_list",
				"can_repair_warranty_create",
				"can_repair_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"ops.repair.created",
			"ops.repair.diagnosed",
			"ops.repair.completed",
			"ops.repair.returned",
			"ops.repair.warranty.created",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"REPAIR_MENU_CATEGORY": "Repair & RMA",
			"REPAIR_ORDER_REF_PREFIX": "RPR",
		}
		self.config = {**defaults, **self.config}
		log.info("RepairPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.operations.repair.views import (
			RepairOrdersDashboardView,
			RepairOrderView,
			WarrantyClaimView,
		)
		cat = self.config.get("REPAIR_MENU_CATEGORY", "Repair & RMA")
		self.add_view(RepairOrdersDashboardView, "Repair Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(RepairOrderView, "Repair Orders", icon="fa-wrench", category=cat)
		self.add_view(WarrantyClaimView, "Warranty Claims", icon="fa-shield", category=cat)
		log.info("RepairPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.repair.models import RepairOrder, WarrantyClaim
		return [RepairOrder, WarrantyClaim]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> RepairPlugin:
	"""Construct a RepairPlugin without activating it."""
	return RepairPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.repair.models import (  # noqa: E402
	RepairOrder,
	WarrantyClaim,
)
from pgappforge.plugins.erp.operations.repair.events import (  # noqa: E402
	RepairOrderCreatedEvent,
	RepairDiagnosedEvent,
	RepairCompletedEvent,
	RepairReturnedToCustomerEvent,
	WarrantyClaimCreatedEvent,
)
from pgappforge.plugins.erp.operations.repair.services import (  # noqa: E402
	RepairService,
	RepairServiceError,
	RepairNotFoundError,
	RepairStateError,
)

__all__ = [
	# plugin
	"RepairPlugin",
	"create_plugin",
	# models
	"RepairOrder",
	"WarrantyClaim",
	# events
	"RepairOrderCreatedEvent",
	"RepairDiagnosedEvent",
	"RepairCompletedEvent",
	"RepairReturnedToCustomerEvent",
	"WarrantyClaimCreatedEvent",
	# services
	"RepairService",
	"RepairServiceError",
	"RepairNotFoundError",
	"RepairStateError",
]
