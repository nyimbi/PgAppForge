"""
pgappforge/plugins/erp/industry/real_estate/property_management/__init__.py

PropertyManagementPlugin — tenant/lease lifecycle, rent collection, maintenance,
move-in/move-out, and lease renewals.

Depends on: foundation, real_estate

Events emitted
--------------
  pm.rent.received          — rent payment recorded
  pm.late_fee.applied       — late fee applied to a lease
  pm.maintenance.created    — maintenance request opened
  pm.work_order.completed   — work order completed
  pm.lease.renewed          — lease renewal accepted
  pm.tenant.move_in         — tenant move-in completed
  pm.tenant.move_out        — tenant move-out completed

Events consumed
---------------
  realestate.lease.signed   — auto-activate a TenantLease when signed

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.real_estate",
        "pgappforge.plugins.erp.industry.real_estate.property_management",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.foundation.events import subscribe

log = logging.getLogger(__name__)


class PropertyManagementPlugin(BasePlugin):
	"""Property Management sub-plugin.

	Registers units, leases, payments, maintenance, and move records.
	Subscribes to realestate.lease.signed to auto-activate TenantLease rows.

	Class-level attributes:
	    name       = "property_management"
	    domain     = "industry"
	    depends_on = ["foundation", "real_estate"]
	"""

	name       = "property_management"
	domain     = "industry"
	depends_on: list[str] = ["foundation", "real_estate"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="property_management",
			version="1.0.0",
			description=(
				"Property Management sub-plugin — unit inventory, tenant leases, rent collection, "
				"late fees, maintenance requests, work orders, move-in/out, and lease renewals."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "real-estate", "property-management", "leasing"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_pm_unit_list",
				"can_pm_unit_write",
				"can_pm_lease_list",
				"can_pm_lease_write",
				"can_pm_payment_list",
				"can_pm_maintenance_list",
				"can_pm_maintenance_write",
				"can_pm_work_order_list",
				"can_pm_work_order_write",
				"can_pm_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"pm.rent.received",
			"pm.late_fee.applied",
			"pm.maintenance.created",
			"pm.work_order.completed",
			"pm.lease.renewed",
			"pm.tenant.move_in",
			"pm.tenant.move_out",
		]

	def subscribe_to(self) -> list[str]:
		return ["realestate.lease.signed"]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PM_MENU_CATEGORY":        "Property Management",
			"PM_LATE_FEE_GRACE_DAYS":  5,
			"PM_RENEWAL_DAYS_VALID":   30,
			"RE_CPI_PCT":              3.0,
		}
		self.config = {**defaults, **self.config}

		# Wire the realestate.lease.signed handler
		subscribe("realestate.lease.signed", self._on_realestate_lease_signed)

		log.info("PropertyManagementPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		pass

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			PropertyUnit,
			TenantLease,
			RentPayment,
			LateFeeRecord,
			MaintenanceRequest,
			WorkOrder,
			MoveRecord,
			LeaseRenewalOffer,
		)
		return [
			PropertyUnit,
			TenantLease,
			RentPayment,
			LateFeeRecord,
			MaintenanceRequest,
			WorkOrder,
			MoveRecord,
			LeaseRenewalOffer,
		]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.real_estate.property_management.views import (
			PropertyUnitView,
			TenantLeaseView,
			RentPaymentView,
			MaintenanceRequestView,
			WorkOrderView,
			PropertyManagementDashboardView,
		)

		cat = self.config.get("PM_MENU_CATEGORY", "Property Management")

		self.add_view(PropertyManagementDashboardView, "Dashboard",           icon="fa-tachometer",    category=cat)
		self.add_view(PropertyUnitView,                "Units",               icon="fa-building",      category=cat)
		self.add_view(TenantLeaseView,                 "Leases",              icon="fa-file-text",     category=cat)
		self.add_view(RentPaymentView,                 "Rent Payments",       icon="fa-money",         category=cat)
		self.add_view(MaintenanceRequestView,          "Maintenance",         icon="fa-wrench",        category=cat)
		self.add_view(WorkOrderView,                   "Work Orders",         icon="fa-clipboard",     category=cat)

		log.info("PropertyManagementPlugin: views registered under category %r", cat)

	# ------------------------------------------------------------------
	# Event handler
	# ------------------------------------------------------------------

	def _on_realestate_lease_signed(self, event: Any) -> None:
		"""Activate a TenantLease when realestate.lease.signed fires.

		The event payload is expected to carry ``lease_id`` and ``tenant_id``.
		Uses a short-lived session obtained from the app context when available.
		Errors are logged but never propagated — event handlers must not disrupt
		the emitting transaction.
		"""
		try:
			lease_id  = (event.payload or {}).get("lease_id") or getattr(event, "lease_id", None)
			tenant_id = getattr(event, "tenant_id", None)

			if not lease_id:
				log.debug("_on_realestate_lease_signed: no lease_id in event, skipping")
				return

			from flask import current_app
			session = current_app.appbuilder.get_session()

			from pgappforge.plugins.erp.industry.real_estate.property_management.models import TenantLease
			lease = session.get(TenantLease, lease_id)
			if lease is None:
				log.debug("_on_realestate_lease_signed: TenantLease %s not found, skipping", lease_id)
				return

			if lease.status == "DRAFT":
				lease.status = "ACTIVE"
				session.flush()
				log.info(
					"_on_realestate_lease_signed: activated TenantLease %s for tenant %s",
					lease_id, tenant_id,
				)
		except Exception:
			log.exception("_on_realestate_lease_signed: unhandled error (swallowed)")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> PropertyManagementPlugin:
	"""Construct and return a PropertyManagementPlugin bound to *appbuilder*."""
	return PropertyManagementPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.real_estate.property_management.models import (  # noqa: E402
	PropertyUnit,
	TenantLease,
	RentPayment,
	LateFeeRecord,
	MaintenanceRequest,
	WorkOrder,
	MoveRecord,
	LeaseRenewalOffer,
)
from pgappforge.plugins.erp.industry.real_estate.property_management.events import (  # noqa: E402
	RentPaymentReceivedEvent,
	LateFeeAppliedEvent,
	MaintenanceRequestCreatedEvent,
	WorkOrderCompletedEvent,
	LeaseRenewalAcceptedEvent,
	TenantMoveInEvent,
	TenantMoveOutEvent,
)
from pgappforge.plugins.erp.industry.real_estate.property_management.services import (  # noqa: E402
	PropertyManagementService,
	PropertyManagementError,
	UnitNotFoundError,
	LeaseNotFoundError,
	WorkOrderNotFoundError,
	MoveRecordNotFoundError,
	RenewalNotFoundError,
	PropertyManagementValidationError,
)

__all__ = [
	# plugin
	"PropertyManagementPlugin",
	"create_plugin",
	# models
	"PropertyUnit",
	"TenantLease",
	"RentPayment",
	"LateFeeRecord",
	"MaintenanceRequest",
	"WorkOrder",
	"MoveRecord",
	"LeaseRenewalOffer",
	# events
	"RentPaymentReceivedEvent",
	"LateFeeAppliedEvent",
	"MaintenanceRequestCreatedEvent",
	"WorkOrderCompletedEvent",
	"LeaseRenewalAcceptedEvent",
	"TenantMoveInEvent",
	"TenantMoveOutEvent",
	# services
	"PropertyManagementService",
	"PropertyManagementError",
	"UnitNotFoundError",
	"LeaseNotFoundError",
	"WorkOrderNotFoundError",
	"MoveRecordNotFoundError",
	"RenewalNotFoundError",
	"PropertyManagementValidationError",
]
