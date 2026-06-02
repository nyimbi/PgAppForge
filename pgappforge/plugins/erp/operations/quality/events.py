"""
pgappforge/plugins/erp/operations/quality/events.py

Domain events for the Quality Management plugin.

Emitted events:
  qc.inspection.created        — new inspection record created
  qc.inspection.started        — inspector begins inspection
  qc.inspection.passed         — inspection outcome PASSED
  qc.inspection.failed         — inspection outcome FAILED (triggers NCR)
  qc.ncr.opened                — new NCR raised
  qc.ncr.analysis_started      — NCR moved to ANALYSIS phase
  qc.ncr.correction_issued     — corrective action recorded
  qc.ncr.closed                — NCR closed after CAPA verification
  qc.ncr.reopened              — closed NCR reopened

Consumed events (from upstream):
  ap.grn.posted                — triggers INCOMING inspection if plan exists
  pp.production_order.completed — triggers OUTGOING inspection if plan exists
  scm.shipment.delivered       — may trigger INCOMING inspection
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class InspectionCreatedEvent(DomainEvent):
	event_type: str = "qc.inspection.created"
	inspection_id: str = ""
	reference_type: str = ""
	reference_id: str = ""
	product_id: str = ""
	inspection_type: str = ""   # from plan
	inspector_id: str = ""
	inspection_date: str = ""


@dataclass
class InspectionStartedEvent(DomainEvent):
	event_type: str = "qc.inspection.started"
	inspection_id: str = ""
	inspector_id: str = ""


@dataclass
class InspectionPassedEvent(DomainEvent):
	event_type: str = "qc.inspection.passed"
	inspection_id: str = ""
	reference_type: str = ""
	reference_id: str = ""
	product_id: str = ""
	accepted_quantity: str = ""   # Decimal as string
	rejected_quantity: str = ""
	disposition: str = ""


@dataclass
class InspectionFailedEvent(DomainEvent):
	event_type: str = "qc.inspection.failed"
	inspection_id: str = ""
	reference_type: str = ""
	reference_id: str = ""
	product_id: str = ""
	accepted_quantity: str = ""   # Decimal as string
	rejected_quantity: str = ""
	failure_summary: str = ""


@dataclass
class NCROpenedEvent(DomainEvent):
	event_type: str = "qc.ncr.opened"
	ncr_id: str = ""
	ncr_number: str = ""
	product_id: str = ""
	source_type: str = ""
	severity: str = ""
	quantity_affected: str = ""   # Decimal as string
	owner_id: str = ""
	due_date: str = ""


@dataclass
class NCRAnalysisStartedEvent(DomainEvent):
	event_type: str = "qc.ncr.analysis_started"
	ncr_id: str = ""
	ncr_number: str = ""
	owner_id: str = ""


@dataclass
class NCRCorrectionIssuedEvent(DomainEvent):
	event_type: str = "qc.ncr.correction_issued"
	ncr_id: str = ""
	ncr_number: str = ""
	corrective_action: str = ""
	preventive_action: str = ""
	owner_id: str = ""


@dataclass
class NCRClosedEvent(DomainEvent):
	event_type: str = "qc.ncr.closed"
	ncr_id: str = ""
	ncr_number: str = ""
	closed_by: str = ""
	root_cause: str = ""


@dataclass
class NCRReopenedEvent(DomainEvent):
	event_type: str = "qc.ncr.reopened"
	ncr_id: str = ""
	ncr_number: str = ""
	reason: str = ""
	reopened_by: str = ""


__all__ = [
	"InspectionCreatedEvent",
	"InspectionStartedEvent",
	"InspectionPassedEvent",
	"InspectionFailedEvent",
	"NCROpenedEvent",
	"NCRAnalysisStartedEvent",
	"NCRCorrectionIssuedEvent",
	"NCRClosedEvent",
	"NCRReopenedEvent",
]
