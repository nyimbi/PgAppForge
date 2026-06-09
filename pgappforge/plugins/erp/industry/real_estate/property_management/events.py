"""
pgappforge/plugins/erp/industry/real_estate/property_management/events.py

Domain events emitted by the Property Management sub-plugin.

All events inherit DomainEvent from the foundation events module and follow
the same emit/subscribe contract: they are persisted to DomainEventLog inside
the caller's SQLAlchemy session (atomic) and dispatched in-process via the
_EVENT_BUS.

Event type namespace: pm.*

Usage
-----
    from pgappforge.plugins.erp.industry.real_estate.property_management.events import (
        RentPaymentReceivedEvent,
        emit_event,
    )

    emit_event(RentPaymentReceivedEvent(
        aggregate_id=lease.id,
        aggregate_type="TenantLease",
        tenant_id=lease.tenant_id,
        lease_id=lease.id,
        unit_id=unit.id,
        amount_cents=payment.amount_cents,
        period_month=payment.period_month,
    ), session)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event, subscribe  # noqa: F401


# ---------------------------------------------------------------------------
# Rent & fees
# ---------------------------------------------------------------------------

@dataclass
class RentPaymentReceivedEvent(DomainEvent):
	"""Fired when a rent payment is successfully recorded."""

	event_type:   str = "pm.rent.received"
	lease_id:     str = ""
	unit_id:      str = ""
	amount_cents: int = 0
	period_month: str = ""


@dataclass
class LateFeeAppliedEvent(DomainEvent):
	"""Fired when a late fee is applied to a lease for a given period."""

	event_type:   str = "pm.late_fee.applied"
	lease_id:     str = ""
	fee_cents:    int = 0
	period_month: str = ""


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

@dataclass
class MaintenanceRequestCreatedEvent(DomainEvent):
	"""Fired when a new maintenance request is opened."""

	event_type:  str = "pm.maintenance.created"
	request_id:  str = ""
	unit_id:     str = ""
	priority:    str = ""
	category:    str = ""


@dataclass
class WorkOrderCompletedEvent(DomainEvent):
	"""Fired when a work order is marked COMPLETED."""

	event_type:        str = "pm.work_order.completed"
	work_order_id:     str = ""
	actual_cost_cents: int = 0


# ---------------------------------------------------------------------------
# Lease lifecycle
# ---------------------------------------------------------------------------

@dataclass
class LeaseRenewalAcceptedEvent(DomainEvent):
	"""Fired when a tenant accepts a lease renewal offer."""

	event_type:    str  = "pm.lease.renewed"
	lease_id:      str  = ""
	new_rent_cents: int = 0
	new_lease_end: str  = ""   # ISO date string or "" for month-to-month


@dataclass
class TenantMoveInEvent(DomainEvent):
	"""Fired when a tenant move-in is completed."""

	event_type: str = "pm.tenant.move_in"
	lease_id:   str = ""
	unit_id:    str = ""


@dataclass
class TenantMoveOutEvent(DomainEvent):
	"""Fired when a tenant move-out is completed."""

	event_type: str = "pm.tenant.move_out"
	lease_id:   str = ""
	unit_id:    str = ""


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
	# re-exported from foundation
	"emit_event",
	"subscribe",
	# pm events
	"RentPaymentReceivedEvent",
	"LateFeeAppliedEvent",
	"MaintenanceRequestCreatedEvent",
	"WorkOrderCompletedEvent",
	"LeaseRenewalAcceptedEvent",
	"TenantMoveInEvent",
	"TenantMoveOutEvent",
]
