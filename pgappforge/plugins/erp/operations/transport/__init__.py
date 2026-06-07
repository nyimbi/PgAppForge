"""
pgappforge/plugins/erp/operations/transport/__init__.py

Transport Management — carrier registry, freight rate cards, shipment lifecycle,
proof-of-delivery recording, and carrier performance analytics.

Domain: operations
Depends on: foundation

Scope:
  - Carrier register with type classification and performance KPIs
  - Freight rate cards: zone-pair + weight bracket + rate type (PER_KG/FLAT/PER_UNIT/PER_CBM)
  - Shipment lifecycle: PLANNED → BOOKED → DISPATCHED → IN_TRANSIT → DELIVERED
  - Freight cost computation from rate cards on carrier booking
  - Real-time tracking event append (JSONB log on shipment)
  - Proof-of-delivery (POD) reference recording
  - Carrier performance recomputation (on-time delivery rate)
  - Cross-plugin: advisory links to fleet_vehicle and fleet_driver

Events emitted:
  ops.transport.shipment.created
  ops.transport.shipment.dispatched
  ops.transport.shipment.delivered
  ops.transport.freight.computed
  ops.transport.carrier.performance

Events consumed:
  (none — transport is a standalone operations plugin)

BPM capabilities:
  ops.transport.create_shipment
  ops.transport.dispatch

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.transport",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.transport import TransportPlugin
    plugin = TransportPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TransportPlugin(BasePlugin):
	"""Transport Management plugin.

	Provides:
	  - Carrier registry with active/inactive flag and performance KPIs
	  - Freight rate cards with zone-pair, weight-bracket, and rate-type logic
	  - Shipment lifecycle management with status FSM enforcement
	  - Freight cost auto-computation on carrier booking
	  - Real-time tracking event log (append-only JSONB)
	  - Proof-of-delivery recording
	  - Carrier on-time delivery rate recomputation
	  - BPM integrations: ops.transport.create_shipment, ops.transport.dispatch
	"""

	name = "transport"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="transport",
			version="1.0.0",
			description=(
				"Transport Management — carrier registry, freight rate cards, "
				"shipment lifecycle, POD recording, and carrier performance analytics."
			),
			author="PgAppForge Contributors",
			tags=["ops", "transport", "logistics", "shipping", "freight"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_transport_carrier_list",
				"can_transport_carrier_write",
				"can_transport_rate_list",
				"can_transport_rate_write",
				"can_transport_shipment_list",
				"can_transport_shipment_create",
				"can_transport_shipment_book",
				"can_transport_shipment_dispatch",
				"can_transport_shipment_deliver",
				"can_transport_shipment_cancel",
				"can_transport_tracking_write",
				"can_transport_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"ops.transport.shipment.created",
			"ops.transport.shipment.dispatched",
			"ops.transport.shipment.delivered",
			"ops.transport.freight.computed",
			"ops.transport.carrier.performance",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"TRANSPORT_MENU_CATEGORY": "Transport",
			"TRANSPORT_DEFAULT_CURRENCY": "USD",
		}
		self.config = {**defaults, **self.config}
		log.info("TransportPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		cat = self.config.get("TRANSPORT_MENU_CATEGORY", "Transport")
		log.info(
			"TransportPlugin: views would be registered under category %r (views.py not yet added)", cat
		)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.transport.models import (
			Carrier,
			FreightRate,
			Shipment,
		)
		return [Carrier, FreightRate, Shipment]

	def activate(self) -> None:
		self.initialize()
		models = self.register_models()
		log.info("TransportPlugin activated — %d models registered", len(models))
		return models


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> TransportPlugin:
	return TransportPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.transport.models import (  # noqa: E402
	Carrier,
	FreightRate,
	Shipment,
	CARRIER_TYPES,
	RATE_TYPES,
	SHIPMENT_STATUSES,
	SOURCE_DOC_TYPES,
)
from pgappforge.plugins.erp.operations.transport.events import (  # noqa: E402
	ShipmentCreatedEvent,
	ShipmentDispatchedEvent,
	ShipmentDeliveredEvent,
	FreightCostComputedEvent,
	CarrierPerformanceUpdatedEvent,
)
from pgappforge.plugins.erp.operations.transport.services import (  # noqa: E402
	TransportService,
	TransportServiceError,
	ShipmentNotFoundError,
	CarrierNotFoundError,
	InvalidStatusTransitionError,
	FreightRateNotFoundError,
)

__all__ = [
	# plugin
	"TransportPlugin",
	"create_plugin",
	# models
	"Carrier",
	"FreightRate",
	"Shipment",
	# enum sets
	"CARRIER_TYPES",
	"RATE_TYPES",
	"SHIPMENT_STATUSES",
	"SOURCE_DOC_TYPES",
	# events
	"ShipmentCreatedEvent",
	"ShipmentDispatchedEvent",
	"ShipmentDeliveredEvent",
	"FreightCostComputedEvent",
	"CarrierPerformanceUpdatedEvent",
	# services
	"TransportService",
	"TransportServiceError",
	"ShipmentNotFoundError",
	"CarrierNotFoundError",
	"InvalidStatusTransitionError",
	"FreightRateNotFoundError",
]
