"""
pgappforge/plugins/erp/finance/hedge_accounting/events.py

Domain events for the Hedge Accounting (IFRS 9 / ASC 815) plugin.

Emitted events:
  hedge_accounting.relationship_designated — hedge relationship formally designated
  hedge_accounting.effectiveness_tested    — effectiveness test run (prospective/retrospective)
  hedge_accounting.oci_reclassified        — OCI balance reclassified to P&L
  hedge_accounting.relationship_discontinued — hedge dedesignation
  hedge_accounting.mtm_updated             — fair value of hedging instrument updated
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event


@dataclass
class HedgeRelationshipDesignatedEvent(DomainEvent):
	event_type: str = "hedge_accounting.relationship_designated"
	relationship_id: str = ""
	hedge_reference: str = ""
	hedge_type: str = ""   # FAIR_VALUE | CASH_FLOW | NET_INVESTMENT
	hedging_instrument_id: str = ""
	hedged_item_id: str = ""
	designation_date: str = ""


@dataclass
class EffectivenessTestedEvent(DomainEvent):
	event_type: str = "hedge_accounting.effectiveness_tested"
	relationship_id: str = ""
	hedge_reference: str = ""
	test_date: str = ""
	test_type: str = ""   # PROSPECTIVE | RETROSPECTIVE
	effectiveness_ratio: str = ""   # Decimal as string
	is_effective: bool = True


@dataclass
class OciReclassifiedEvent(DomainEvent):
	event_type: str = "hedge_accounting.oci_reclassified"
	relationship_id: str = ""
	hedge_reference: str = ""
	reclassification_date: str = ""
	amount_cents: int = 0
	reclassification_reason: str = ""


@dataclass
class HedgeRelationshipDiscontinuedEvent(DomainEvent):
	event_type: str = "hedge_accounting.relationship_discontinued"
	relationship_id: str = ""
	hedge_reference: str = ""
	discontinuation_date: str = ""
	reason: str = ""
	remaining_oci_cents: int = 0


@dataclass
class HedgeMtmUpdatedEvent(DomainEvent):
	event_type: str = "hedge_accounting.mtm_updated"
	relationship_id: str = ""
	hedge_reference: str = ""
	valuation_date: str = ""
	fair_value_cents: int = 0
	effective_portion_cents: int = 0
	ineffective_portion_cents: int = 0


__all__ = [
	"HedgeRelationshipDesignatedEvent",
	"EffectivenessTestedEvent",
	"OciReclassifiedEvent",
	"HedgeRelationshipDiscontinuedEvent",
	"HedgeMtmUpdatedEvent",
	"emit_event",
]
