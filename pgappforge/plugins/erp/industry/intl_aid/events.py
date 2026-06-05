"""
pgappforge/plugins/erp/industry/intl_aid/events.py

Domain events for the International Aid plugin.

Events emitted:
  aid.project.created            — new IATI activity registered
  aid.transaction.disbursement   — funds disbursed to project
  aid.transaction.commitment     — new financial commitment recorded
  aid.results.updated            — result indicators refreshed
  aid.project.status.changed     — project lifecycle transition
  aid.beneficiaries.counted      — new beneficiary count recorded
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class AidProjectCreatedEvent(DomainEvent):
	event_type: str = "aid.project.created"
	project_id: str = ""
	iati_identifier: str = ""
	implementing_org_id: str = ""
	funding_org_id: str = ""
	recipient_country_code: str = ""
	total_budget_cents: int = 0
	currency_code: str = ""
	humanitarian: bool = False


@dataclass
class DisbursementRecordedEvent(DomainEvent):
	event_type: str = "aid.transaction.disbursement"
	transaction_id: str = ""
	project_id: str = ""
	iati_identifier: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	usd_value_cents: int = 0
	receiver_id: str = ""
	transaction_date: str = ""  # ISO date string


@dataclass
class CommitmentRecordedEvent(DomainEvent):
	event_type: str = "aid.transaction.commitment"
	transaction_id: str = ""
	project_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	provider_id: str = ""
	transaction_date: str = ""  # ISO date string


@dataclass
class ResultsUpdatedEvent(DomainEvent):
	event_type: str = "aid.results.updated"
	project_id: str = ""
	iati_identifier: str = ""
	indicators_updated: int = 0
	updated_indicator_ids: list = None  # list of str

	def __post_init__(self):
		if self.updated_indicator_ids is None:
			self.updated_indicator_ids = []


@dataclass
class ProjectStatusChangedEvent(DomainEvent):
	event_type: str = "aid.project.status.changed"
	project_id: str = ""
	iati_identifier: str = ""
	old_status: str = ""
	new_status: str = ""


@dataclass
class BeneficiariesCountedEvent(DomainEvent):
	event_type: str = "aid.beneficiaries.counted"
	count_id: str = ""
	project_id: str = ""
	measurement_date: str = ""  # ISO date string
	total_beneficiaries: int = 0


__all__ = [
	"AidProjectCreatedEvent",
	"DisbursementRecordedEvent",
	"CommitmentRecordedEvent",
	"ResultsUpdatedEvent",
	"ProjectStatusChangedEvent",
	"BeneficiariesCountedEvent",
]
