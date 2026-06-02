"""
pgappforge/plugins/erp/industry/nonprofit/events.py

Domain events for the Nonprofit plugin.

Events emitted:
  nonprofit.donation.received       — donation recorded and cleared
  nonprofit.donation.acknowledged   — receipt issued
  nonprofit.donor.upgraded          — giving level changed (e.g. SMALL→MID)
  nonprofit.program.impact_recorded — impact measurement saved
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class DonationReceivedEvent(DomainEvent):
	event_type: str = "nonprofit.donation.received"
	donation_id: str = ""
	donor_id: str = ""
	campaign_id: str = ""
	amount_cents: int = 0
	currency: str = ""
	payment_method: str = ""
	is_recurring: bool = False
	designation: str = ""


@dataclass
class DonationAcknowledgedEvent(DomainEvent):
	event_type: str = "nonprofit.donation.acknowledged"
	donation_id: str = ""
	donor_id: str = ""
	amount_cents: int = 0
	currency: str = ""
	tax_receipt_number: str = ""
	tax_receipt_url: str = ""


@dataclass
class DonorGivingLevelUpgradedEvent(DomainEvent):
	event_type: str = "nonprofit.donor.upgraded"
	donor_id: str = ""
	donor_number: str = ""
	old_level: str = ""
	new_level: str = ""
	lifetime_giving_cents: int = 0


@dataclass
class ImpactMeasurementRecordedEvent(DomainEvent):
	event_type: str = "nonprofit.program.impact_recorded"
	measurement_id: str = ""
	program_id: str = ""
	metric_name: str = ""
	target_value: str = ""  # Decimal string
	actual_value: str = ""  # Decimal string
	measurement_date: str = ""  # ISO date


__all__ = [
	"DonationReceivedEvent",
	"DonationAcknowledgedEvent",
	"DonorGivingLevelUpgradedEvent",
	"ImpactMeasurementRecordedEvent",
]
