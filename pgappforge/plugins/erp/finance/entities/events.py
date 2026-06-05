"""
pgappforge/plugins/erp/finance/entities/events.py

Domain events for the Legal Entities plugin.

All events inherit from DomainEvent and are persisted atomically with the
business transaction via emit_event().

Events emitted by this module:
  entity.created                  — new LegalEntity registered
  entity.interco_transaction.posted — InterEntityTransaction posted to both GL books
  entity.consolidation.eliminations_generated — ConsolidationElimination batch created
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# EntityCreatedEvent
# ---------------------------------------------------------------------------

@dataclass
class EntityCreatedEvent(DomainEvent):
	"""Fired after a new LegalEntity row is committed.

	aggregate_type = "LegalEntity"
	aggregate_id   = entity.id
	"""

	event_type: str = "entity.created"
	entity_id: str = ""
	entity_code: str = ""
	entity_name: str = ""
	entity_type: str = ""
	parent_entity_id: str = ""
	functional_currency: str = "KES"
	level: int = 0


# ---------------------------------------------------------------------------
# InterEntityTransactionPostedEvent
# ---------------------------------------------------------------------------

@dataclass
class InterEntityTransactionPostedEvent(DomainEvent):
	"""Fired after an InterEntityTransaction reaches status=POSTED.

	Carries enough information for downstream consumers (e.g. consolidation
	engine, treasury) to act without re-querying the database.

	aggregate_type = "InterEntityTransaction"
	aggregate_id   = transaction.id
	"""

	event_type: str = "entity.interco_transaction.posted"
	transaction_id: str = ""
	transaction_ref: str = ""
	from_entity_id: str = ""
	to_entity_id: str = ""
	transaction_type: str = ""
	amount_cents: int = 0
	currency_code: str = "KES"
	value_date: str = ""          # ISO date string
	journal_id_from: str = ""
	journal_id_to: str = ""


# ---------------------------------------------------------------------------
# ConsolidationEliminationsGeneratedEvent
# ---------------------------------------------------------------------------

@dataclass
class ConsolidationEliminationsGeneratedEvent(DomainEvent):
	"""Fired after a full elimination batch is generated for a period.

	aggregate_type = "ConsolidationElimination"
	aggregate_id   = root_entity_id  (the consolidation parent)
	"""

	event_type: str = "entity.consolidation.eliminations_generated"
	period: str = ""
	root_entity_id: str = ""
	elimination_count: int = 0
	total_eliminated_cents: int = 0
	currency_code: str = "KES"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"EntityCreatedEvent",
	"InterEntityTransactionPostedEvent",
	"ConsolidationEliminationsGeneratedEvent",
]
