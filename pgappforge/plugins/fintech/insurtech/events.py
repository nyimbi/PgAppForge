"""
pgappforge/plugins/fintech/insurtech/events.py

InsurTech domain events.

All events extend DomainEvent from erp.foundation.events.
They are emitted by InsurTechService and should be persisted atomically
within the same SQLAlchemy session as the triggering operation.

Event catalogue
---------------
  insurtech.policy_issued       — new policy issued and set ACTIVE
  insurtech.premium_paid        — premium payment collected and posted to GL
  insurtech.claim_submitted     — claim filed against an active policy
  insurtech.claim_approved      — claim approved and payout scheduled
  insurtech.claim_rejected      — claim rejected by underwriter
  insurtech.policy_lapsed       — policy lapsed due to overdue premiums
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Policy lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class PolicyIssuedEvent(DomainEvent):
	"""Emitted when a new insurance policy is issued and activated."""
	event_type: str = "insurtech.policy_issued"
	policy_id: str = ""
	policy_number: str = ""
	holder_id: str = ""
	product_id: str = ""
	product_line: str = ""
	sum_insured_cents: int = 0
	annual_premium_cents: int = 0
	start_date: str = ""         # ISO date string
	end_date: str = ""           # ISO date string


@dataclass
class PremiumPaidEvent(DomainEvent):
	"""Emitted when a premium payment is collected and posted to GL."""
	event_type: str = "insurtech.premium_paid"
	premium_id: str = ""
	policy_id: str = ""
	policy_number: str = ""
	period: str = ""             # YYYY-MM
	amount_cents: int = 0
	gl_journal_id: str = ""
	paid_date: str = ""          # ISO date string


@dataclass
class ClaimSubmittedEvent(DomainEvent):
	"""Emitted when a claim is filed against an active policy."""
	event_type: str = "insurtech.claim_submitted"
	claim_id: str = ""
	claim_number: str = ""
	policy_id: str = ""
	policy_number: str = ""
	claim_type: str = ""
	amount_claimed_cents: int = 0
	incident_date: str = ""      # ISO date string


@dataclass
class ClaimApprovedEvent(DomainEvent):
	"""Emitted when a claim is approved and payout posted to GL."""
	event_type: str = "insurtech.claim_approved"
	claim_id: str = ""
	claim_number: str = ""
	policy_id: str = ""
	amount_approved_cents: int = 0
	decided_by: str = ""
	decided_at: str = ""         # ISO datetime string


@dataclass
class ClaimRejectedEvent(DomainEvent):
	"""Emitted when a claim is rejected by an underwriter."""
	event_type: str = "insurtech.claim_rejected"
	claim_id: str = ""
	claim_number: str = ""
	policy_id: str = ""
	reason: str = ""
	decided_by: str = ""
	decided_at: str = ""         # ISO datetime string


@dataclass
class PolicyLapsedEvent(DomainEvent):
	"""Emitted when a policy lapses due to overdue premiums beyond grace period."""
	event_type: str = "insurtech.policy_lapsed"
	policy_id: str = ""
	policy_number: str = ""
	holder_id: str = ""
	overdue_periods: list = None

	def __post_init__(self) -> None:
		if self.overdue_periods is None:
			self.overdue_periods = []


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

IT_POLICY_ISSUED = "insurtech.policy_issued"
IT_PREMIUM_PAID = "insurtech.premium_paid"
IT_CLAIM_SUBMITTED = "insurtech.claim_submitted"
IT_CLAIM_APPROVED = "insurtech.claim_approved"
IT_CLAIM_REJECTED = "insurtech.claim_rejected"
IT_POLICY_LAPSED = "insurtech.policy_lapsed"

ALL_IT_EVENT_TYPES: list[str] = [
	IT_POLICY_ISSUED,
	IT_PREMIUM_PAID,
	IT_CLAIM_SUBMITTED,
	IT_CLAIM_APPROVED,
	IT_CLAIM_REJECTED,
	IT_POLICY_LAPSED,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"PolicyIssuedEvent",
	"PremiumPaidEvent",
	"ClaimSubmittedEvent",
	"ClaimApprovedEvent",
	"ClaimRejectedEvent",
	"PolicyLapsedEvent",
	# event type constants
	"IT_POLICY_ISSUED",
	"IT_PREMIUM_PAID",
	"IT_CLAIM_SUBMITTED",
	"IT_CLAIM_APPROVED",
	"IT_CLAIM_REJECTED",
	"IT_POLICY_LAPSED",
	"ALL_IT_EVENT_TYPES",
]
