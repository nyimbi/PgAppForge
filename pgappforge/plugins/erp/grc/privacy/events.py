"""
pgappforge/plugins/erp/grc/privacy/events.py

GRC Privacy plugin domain events.

Events emitted:
  privacy.consent.granted
  privacy.consent.withdrawn
  privacy.dsr.received
  privacy.dsr.completed
  privacy.dsr.overdue

Events consumed:
  party.created   — create default consent records for new data subjects
  party.merged    — merge consent records when parties are deduplicated
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class ConsentGrantedEvent(DomainEvent):
	event_type: str = "privacy.consent.granted"
	consent_id: str = ""
	party_id: str = ""
	purpose: str = ""
	legal_basis: str = ""
	source: str = ""


@dataclass
class ConsentWithdrawnEvent(DomainEvent):
	event_type: str = "privacy.consent.withdrawn"
	consent_id: str = ""
	party_id: str = ""
	purpose: str = ""
	withdrawn_at: str = ""


@dataclass
class DSRReceivedEvent(DomainEvent):
	event_type: str = "privacy.dsr.received"
	dsr_id: str = ""
	dsr_number: str = ""
	party_id: str = ""
	request_type: str = ""
	due_at: str = ""


@dataclass
class DSRCompletedEvent(DomainEvent):
	event_type: str = "privacy.dsr.completed"
	dsr_id: str = ""
	dsr_number: str = ""
	party_id: str = ""
	request_type: str = ""
	response_url: str = ""


@dataclass
class DSROverdueEvent(DomainEvent):
	event_type: str = "privacy.dsr.overdue"
	dsr_id: str = ""
	dsr_number: str = ""
	party_id: str = ""
	due_at: str = ""
	days_overdue: int = 0


__all__ = [
	"ConsentGrantedEvent",
	"ConsentWithdrawnEvent",
	"DSRReceivedEvent",
	"DSRCompletedEvent",
	"DSROverdueEvent",
]
