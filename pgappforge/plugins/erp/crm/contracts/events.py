"""
pgappforge/plugins/erp/crm/contracts/events.py

Domain events for the Contract Lifecycle Management plugin.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class ContractCreatedEvent(DomainEvent):
	"""Emitted when a new contract is created (status DRAFT)."""
	event_type: str = "clm.contract.created"
	contract_id: str = ""
	contract_number: str = ""
	contract_type: str = ""
	counterparty_id: str = ""
	internal_owner_id: str = ""


@dataclass
class ContractApprovedEvent(DomainEvent):
	"""Emitted when all approvers have approved and contract moves to PENDING_SIGNATURE."""
	event_type: str = "clm.contract.approved"
	contract_id: str = ""
	contract_number: str = ""
	contract_type: str = ""
	counterparty_id: str = ""


@dataclass
class ContractSignedEvent(DomainEvent):
	"""Emitted when all signatories have signed and contract becomes ACTIVE."""
	event_type: str = "clm.contract.signed"
	contract_id: str = ""
	contract_number: str = ""
	contract_type: str = ""
	counterparty_id: str = ""
	signed_at: str = ""  # ISO datetime


@dataclass
class ObligationFulfilledEvent(DomainEvent):
	"""Emitted when a contract obligation is marked FULFILLED."""
	event_type: str = "clm.obligation.fulfilled"
	obligation_id: str = ""
	contract_id: str = ""
	obligation_type: str = ""
	fulfilled_at: str = ""  # ISO datetime


@dataclass
class ObligationOverdueEvent(DomainEvent):
	"""Emitted when an obligation passes its due_date without fulfilment."""
	event_type: str = "clm.obligation.overdue"
	obligation_id: str = ""
	contract_id: str = ""
	obligation_type: str = ""
	due_date: str = ""  # ISO date
	days_overdue: int = 0


@dataclass
class ContractRenewalAlertEvent(DomainEvent):
	"""Emitted when a contract is within its renewal_notice_days window and auto_renew is False."""
	event_type: str = "clm.contract.renewal_alert"
	contract_id: str = ""
	contract_number: str = ""
	expiry_date: str = ""  # ISO date
	days_to_expiry: int = 0


@dataclass
class ContractTerminatedEvent(DomainEvent):
	"""Emitted when a contract is terminated."""
	event_type: str = "clm.contract.terminated"
	contract_id: str = ""
	contract_number: str = ""
	reason: str = ""
	effective_date: str = ""  # ISO date


@dataclass
class LeaseRecognisedEvent(DomainEvent):
	"""Emitted on initial IFRS 16 recognition — GL entries posted."""
	event_type: str = "clm.lease.recognised"
	contract_id: str = ""
	contract_number: str = ""
	lease_type: str = ""
	rou_asset_cents: int = 0
	lease_liability_cents: int = 0
	recognition_date: str = ""  # ISO date


__all__ = [
	"ContractCreatedEvent",
	"ContractApprovedEvent",
	"ContractSignedEvent",
	"ObligationFulfilledEvent",
	"ObligationOverdueEvent",
	"ContractRenewalAlertEvent",
	"ContractTerminatedEvent",
	"LeaseRecognisedEvent",
]
