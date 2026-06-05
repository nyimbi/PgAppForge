"""
pgappforge/plugins/erp/industry/insurance/events.py

Domain events for the Insurance plugin.

All monetary fields are integer cents — never float.

Events emitted
--------------
  insurance.policy.issued        — new policy issued (DRAFT → ACTIVE)
  insurance.policy.lapsed        — policy lapsed due to non-payment
  insurance.claim.filed          — new claim filed
  insurance.claim.approved       — claim approved for payment
  insurance.claim.paid           — claim payment disbursed
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Policy events
# ---------------------------------------------------------------------------

@dataclass
class PolicyIssuedEvent(DomainEvent):
	"""Emitted when a policy transitions from DRAFT to ACTIVE."""
	event_type: str = "insurance.policy.issued"
	policy_id: str = ""
	policy_number: str = ""
	product_id: str = ""
	holder_id: str = ""
	coverage_amount_cents: int = 0
	annual_premium_cents: int = 0
	coverage_start: str = ""      # ISO date
	coverage_end: str = ""        # ISO date


@dataclass
class PolicyLapsedEvent(DomainEvent):
	"""Emitted when a policy lapses due to non-payment."""
	event_type: str = "insurance.policy.lapsed"
	policy_id: str = ""
	policy_number: str = ""
	holder_id: str = ""
	lapsed_at: str = ""           # ISO datetime


# ---------------------------------------------------------------------------
# Claim events
# ---------------------------------------------------------------------------

@dataclass
class ClaimFiledEvent(DomainEvent):
	"""Emitted when a new claim is filed against a policy."""
	event_type: str = "insurance.claim.filed"
	claim_id: str = ""
	claim_number: str = ""
	policy_id: str = ""
	claimant_id: str = ""
	claimed_amount_cents: int = 0
	incident_date: str = ""       # ISO date
	reported_date: str = ""       # ISO date


@dataclass
class ClaimApprovedEvent(DomainEvent):
	"""Emitted when a claim is approved for a specific payment amount."""
	event_type: str = "insurance.claim.approved"
	claim_id: str = ""
	claim_number: str = ""
	policy_id: str = ""
	approved_amount_cents: int = 0
	assessor_id: str = ""
	approved_at: str = ""         # ISO datetime


@dataclass
class ClaimPaidEvent(DomainEvent):
	"""Emitted when a claim payment is disbursed to the claimant."""
	event_type: str = "insurance.claim.paid"
	claim_id: str = ""
	claim_number: str = ""
	policy_id: str = ""
	paid_amount_cents: int = 0
	paid_at: str = ""             # ISO datetime


__all__ = [
	"PolicyIssuedEvent",
	"PolicyLapsedEvent",
	"ClaimFiledEvent",
	"ClaimApprovedEvent",
	"ClaimPaidEvent",
]
