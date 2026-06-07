"""
pgappforge/plugins/erp/grc/ethics/events.py

Ethics Hotline domain events.

Events emitted:
  grc.ethics.report.submitted        — anonymous/named report received (NO PII)
  grc.ethics.case.opened             — case opened and assigned
  grc.ethics.case.resolved           — case closed with resolution
  grc.ethics.report.status.updated   — report status transition

PII discipline: reporter identity, contact details, and description are NEVER
included in events.  Investigators access those only through the Case view.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class EthicsReportSubmittedEvent(DomainEvent):
	event_type: str = "grc.ethics.report.submitted"
	report_id: str = ""
	category: str = ""
	severity: str = ""
	# NO reporter_contact, NO description — PII discipline


@dataclass
class EthicsCaseOpenedEvent(DomainEvent):
	event_type: str = "grc.ethics.case.opened"
	case_id: str = ""
	report_id: str = ""
	assigned_to: str = ""


@dataclass
class EthicsCaseResolvedEvent(DomainEvent):
	event_type: str = "grc.ethics.case.resolved"
	case_id: str = ""
	resolution_category: str = ""


@dataclass
class EthicsReportStatusUpdatedEvent(DomainEvent):
	event_type: str = "grc.ethics.report.status.updated"
	report_id: str = ""
	old_status: str = ""
	new_status: str = ""


__all__ = [
	"EthicsReportSubmittedEvent",
	"EthicsCaseOpenedEvent",
	"EthicsCaseResolvedEvent",
	"EthicsReportStatusUpdatedEvent",
]
