"""
pgappforge/plugins/erp/operations/rental/__init__.py

RentalPlugin — Rental Management plugin.

Domain: operations
Depends on: foundation

Scope: asset rental lifecycle — booking, activation, return, damage
       deposit handling, availability querying.

Events emitted:
  ops.rental.created
  ops.rental.started
  ops.rental.returned
  ops.rental.deposit.charged
  ops.rental.invoiced

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.rental",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.rental import RentalPlugin
    plugin = RentalPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class RentalPlugin(BasePlugin):
	"""Rental Management plugin.

	Provides:
	  - Rental asset registry with daily/weekly/monthly rates and deposit tracking
	  - Rental order lifecycle (PENDING → ACTIVE → COMPLETED | CANCELLED)
	  - Conflict detection for overlapping bookings
	  - Asset availability query (free-range computation)
	  - Damage deposit charge events on return
	  - BPM-callable actions for workflow integration
	"""

	name = "rental"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="rental",
			version="1.0.0",
			description=(
				"Rental Management — asset rental lifecycle: booking, activation, return, "
				"damage deposit handling, prorated refund calculation, and availability queries."
			),
			author="PgAppForge Contributors",
			tags=["ops", "rental", "asset-rental", "leasing"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_rental_asset_list",
				"can_rental_asset_create",
				"can_rental_asset_edit",
				"can_rental_order_list",
				"can_rental_order_create",
				"can_rental_order_start",
				"can_rental_order_return",
				"can_rental_order_cancel",
				"can_rental_availability_view",
				"can_rental_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"ops.rental.created",
			"ops.rental.started",
			"ops.rental.returned",
			"ops.rental.deposit.charged",
			"ops.rental.invoiced",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"RENTAL_MENU_CATEGORY": "Rentals",
			"RENTAL_ORDER_REF_PREFIX": "RNT",
			"RENTAL_MIN_BOOKING_DAYS": 1,
		}
		self.config = {**defaults, **self.config}
		log.info("RentalPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.operations.rental.views import (
			RentalOrdersDashboardView,
			RentalAssetView,
			RentalOrderView,
		)
		cat = self.config.get("RENTAL_MENU_CATEGORY", "Rentals")
		self.add_view(RentalOrdersDashboardView, "Rental Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(RentalAssetView, "Assets", icon="fa-cubes", category=cat)
		self.add_view(RentalOrderView, "Rental Orders", icon="fa-list", category=cat)
		log.info("RentalPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.rental.models import RentalAsset, RentalOrder
		return [RentalAsset, RentalOrder]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> RentalPlugin:
	"""Construct a RentalPlugin without activating it."""
	return RentalPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.rental.models import (  # noqa: E402
	RentalAsset,
	RentalOrder,
)
from pgappforge.plugins.erp.operations.rental.events import (  # noqa: E402
	RentalOrderCreatedEvent,
	RentalStartedEvent,
	RentalReturnedEvent,
	DamageDepositChargedEvent,
	RentalInvoiceGeneratedEvent,
)
from pgappforge.plugins.erp.operations.rental.services import (  # noqa: E402
	RentalService,
	RentalServiceError,
	RentalNotFoundError,
	RentalAssetNotFoundError,
	RentalStateError,
	RentalConflictError,
)

__all__ = [
	# plugin
	"RentalPlugin",
	"create_plugin",
	# models
	"RentalAsset",
	"RentalOrder",
	# events
	"RentalOrderCreatedEvent",
	"RentalStartedEvent",
	"RentalReturnedEvent",
	"DamageDepositChargedEvent",
	"RentalInvoiceGeneratedEvent",
	# services
	"RentalService",
	"RentalServiceError",
	"RentalNotFoundError",
	"RentalAssetNotFoundError",
	"RentalStateError",
	"RentalConflictError",
]
