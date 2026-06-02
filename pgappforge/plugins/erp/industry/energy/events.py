"""
pgappforge/plugins/erp/industry/energy/events.py

Domain events for the Energy plugin.

Events emitted:
  energy.meter.reading_submitted    — new meter reading recorded
  energy.bill.issued                — energy bill generated
  energy.bill.paid                  — bill fully settled
  energy.certificate.retired        — REC/REGO/GO certificate retired
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class MeterReadingSubmittedEvent(DomainEvent):
	event_type: str = "energy.meter.reading_submitted"
	reading_id: str = ""
	meter_id: str = ""
	meter_number: str = ""
	read_date: str = ""       # ISO date
	read_value: str = ""      # Decimal string
	consumption_kwh: str = "" # Decimal string
	read_type: str = ""


@dataclass
class EnergyBillIssuedEvent(DomainEvent):
	event_type: str = "energy.bill.issued"
	bill_id: str = ""
	bill_number: str = ""
	meter_id: str = ""
	customer_id: str = ""
	billing_period_start: str = ""  # ISO date
	billing_period_end: str = ""    # ISO date
	amount_cents: int = 0
	currency: str = ""
	due_date: str = ""


@dataclass
class EnergyBillPaidEvent(DomainEvent):
	event_type: str = "energy.bill.paid"
	bill_id: str = ""
	bill_number: str = ""
	meter_id: str = ""
	customer_id: str = ""
	amount_cents: int = 0
	currency: str = ""


@dataclass
class RenewableCertificateRetiredEvent(DomainEvent):
	event_type: str = "energy.certificate.retired"
	certificate_record_id: str = ""
	certificate_id: str = ""
	energy_type: str = ""
	generation_mwh: str = ""  # Decimal string
	registry_name: str = ""
	retirement_purpose: str = ""
	retired_by_id: str = ""


__all__ = [
	"MeterReadingSubmittedEvent",
	"EnergyBillIssuedEvent",
	"EnergyBillPaidEvent",
	"RenewableCertificateRetiredEvent",
]
