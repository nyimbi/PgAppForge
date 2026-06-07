"""
pgappforge/plugins/erp/operations/process_manufacturing/events.py

Domain events for the Process Manufacturing plugin.

All monetary amounts are integer cents — never float.
Quantities are Decimal-compatible strings where precision matters.

Events emitted:
  ops.process_mfg.recipe.created   — new recipe created in DRAFT status
  ops.process_mfg.recipe.approved  — recipe approved and ready for production
  ops.process_mfg.batch.created    — batch record created from approved recipe
  ops.process_mfg.batch.completed  — batch completed with actual yield recorded
  ops.process_mfg.yield.variance   — yield variance posted to GL
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class RecipeCreatedEvent(DomainEvent):
	"""Emitted when a new process manufacturing recipe is created."""
	event_type: str = "ops.process_mfg.recipe.created"
	recipe_id: str = ""
	product_id: str = ""
	version: str = ""
	tenant_id: str = ""


@dataclass
class RecipeApprovedEvent(DomainEvent):
	"""Emitted when a recipe transitions to APPROVED status."""
	event_type: str = "ops.process_mfg.recipe.approved"
	recipe_id: str = ""
	approved_by: str = ""


@dataclass
class BatchRecordCreatedEvent(DomainEvent):
	"""Emitted when a batch record is created from an approved recipe."""
	event_type: str = "ops.process_mfg.batch.created"
	batch_id: str = ""
	recipe_id: str = ""
	batch_number: str = ""


@dataclass
class BatchCompletedEvent(DomainEvent):
	"""Emitted when a batch record is completed with actual yield recorded."""
	event_type: str = "ops.process_mfg.batch.completed"
	batch_id: str = ""
	actual_yield: str = ""   # Decimal string
	yield_variance_pct: str = ""  # Decimal string


@dataclass
class YieldVariancePostedEvent(DomainEvent):
	"""Emitted when yield variance exceeds threshold and is posted to GL."""
	event_type: str = "ops.process_mfg.yield.variance"
	batch_id: str = ""
	variance_cents: int = 0  # Signed: positive = over-cost, negative = under-cost


__all__ = [
	"RecipeCreatedEvent",
	"RecipeApprovedEvent",
	"BatchRecordCreatedEvent",
	"BatchCompletedEvent",
	"YieldVariancePostedEvent",
]
