"""
pgappforge/plugins/erp/industry/public_sector/events.py

Domain events for the Public Sector plugin.

Events emitted:
  public_sector.case.approved          — benefit case approved
  public_sector.case.suspended         — benefit suspended
  public_sector.grant.disbursement     — funding tranche disbursed
  public_sector.constituent.registered — new constituent onboarded
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class ConstituentRegisteredEvent(DomainEvent):
	event_type: str = "public_sector.constituent.registered"
	constituent_id: str = ""
	constituent_number: str = ""
	constituent_type: str = ""
	case_worker_id: str = ""


@dataclass
class GovernmentCaseApprovedEvent(DomainEvent):
	event_type: str = "public_sector.case.approved"
	case_id: str = ""
	case_number: str = ""
	constituent_id: str = ""
	program_type: str = ""
	total_benefit_amount_cents: int = 0
	grant_start: str = ""  # ISO date
	grant_end: str = ""    # ISO date or ""


@dataclass
class GovernmentCaseSuspendedEvent(DomainEvent):
	event_type: str = "public_sector.case.suspended"
	case_id: str = ""
	case_number: str = ""
	constituent_id: str = ""
	reason: str = ""


@dataclass
class GrantDisbursementEvent(DomainEvent):
	"""Emitted each time a funding tranche is released."""
	event_type: str = "public_sector.grant.disbursement"
	grant_id: str = ""
	grant_number: str = ""
	tranche_amount_cents: int = 0
	total_disbursed_cents: int = 0
	currency: str = ""
	disbursed_by_id: str = ""


__all__ = [
	"ConstituentRegisteredEvent",
	"GovernmentCaseApprovedEvent",
	"GovernmentCaseSuspendedEvent",
	"GrantDisbursementEvent",
]
