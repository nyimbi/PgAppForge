from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"ReferralSubmittedEvent",
	"ReferralHiredEvent",
	"ReferralRewardPaidEvent",
	"ReferralExpiredEvent",
]


@dataclass
class ReferralSubmittedEvent(DomainEvent):
	event_type: str = field(default="hcm.referral.submitted", init=False)
	referral_id: str = ""
	referrer_id: str = ""
	candidate_name: str = ""
	position_id: str = ""


@dataclass
class ReferralHiredEvent(DomainEvent):
	event_type: str = field(default="hcm.referral.hired", init=False)
	referral_id: str = ""
	referrer_id: str = ""
	candidate_id: str = ""
	reward_amount_cents: int = 0


@dataclass
class ReferralRewardPaidEvent(DomainEvent):
	event_type: str = field(default="hcm.referral.reward.paid", init=False)
	referral_id: str = ""
	referrer_id: str = ""
	amount_cents: int = 0
	payment_date: str = ""  # ISO date string


@dataclass
class ReferralExpiredEvent(DomainEvent):
	event_type: str = field(default="hcm.referral.expired", init=False)
	referral_id: str = ""
	referrer_id: str = ""
