"""
pgappforge/plugins/erp/finance/lease_accounting/events.py

Domain events for the Lease Accounting (IFRS 16 / ASC 842) plugin.

Emitted events:
  lease_accounting.lease_created          — new lease contract registered
  lease_accounting.lease_commenced        — lease commencement date reached
  lease_accounting.lease_modified         — lease modification (remeasurement)
  lease_accounting.lease_terminated       — early termination or expiry
  lease_accounting.payment_posted         — periodic lease payment posted to GL
  lease_accounting.rou_depreciated        — right-of-use asset depreciation entry
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event


@dataclass
class LeaseCreatedEvent(DomainEvent):
	event_type: str = "lease_accounting.lease_created"
	lease_id: str = ""
	lease_reference: str = ""
	lessor_name: str = ""
	commencement_date: str = ""
	lease_term_months: int = 0
	currency_code: str = ""


@dataclass
class LeaseCommencedEvent(DomainEvent):
	event_type: str = "lease_accounting.lease_commenced"
	lease_id: str = ""
	lease_reference: str = ""
	rou_asset_cents: int = 0
	lease_liability_cents: int = 0
	commencement_date: str = ""


@dataclass
class LeaseModifiedEvent(DomainEvent):
	event_type: str = "lease_accounting.lease_modified"
	lease_id: str = ""
	lease_reference: str = ""
	modification_date: str = ""
	revised_liability_cents: int = 0
	revised_rou_cents: int = 0
	modification_type: str = ""   # EXTENSION | REDUCTION | RATE_CHANGE


@dataclass
class LeaseTerminatedEvent(DomainEvent):
	event_type: str = "lease_accounting.lease_terminated"
	lease_id: str = ""
	lease_reference: str = ""
	termination_date: str = ""
	gain_loss_cents: int = 0


@dataclass
class LeasePaymentPostedEvent(DomainEvent):
	event_type: str = "lease_accounting.payment_posted"
	lease_id: str = ""
	lease_reference: str = ""
	payment_date: str = ""
	interest_expense_cents: int = 0
	principal_reduction_cents: int = 0
	total_payment_cents: int = 0


@dataclass
class RouDepreciatedEvent(DomainEvent):
	event_type: str = "lease_accounting.rou_depreciated"
	lease_id: str = ""
	lease_reference: str = ""
	period_date: str = ""
	depreciation_cents: int = 0
	accumulated_depreciation_cents: int = 0


__all__ = [
	"LeaseCreatedEvent",
	"LeaseCommencedEvent",
	"LeaseModifiedEvent",
	"LeaseTerminatedEvent",
	"LeasePaymentPostedEvent",
	"RouDepreciatedEvent",
	"emit_event",
]
