"""
pgappforge/plugins/erp/finance/consolidation/events.py

Domain events for the Group Consolidation plugin.

All amounts are integer cents (no float, ever).
Emitted inside the same SQLAlchemy session as the mutating operation so
persistence is atomic with the business transaction.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# Consolidation events
# ---------------------------------------------------------------------------

@dataclass
class ConsolidationRunStartedEvent(DomainEvent):
	"""Emitted when a consolidation run is initiated for a period."""
	event_type: str = "finance.consolidation.run.started"
	run_id: str = ""
	reporting_entity_id: str = ""
	period: str = ""          # e.g. "2025-01"


@dataclass
class IntercompanyEliminationPostedEvent(DomainEvent):
	"""Emitted when an intercompany elimination entry is created."""
	event_type: str = "finance.consolidation.elimination.posted"
	run_id: str = ""
	elimination_id: str = ""
	dr_entity: str = ""       # entity being debited (creditor side eliminated)
	cr_entity: str = ""       # entity being credited (debtor side eliminated)
	amount_cents: int = 0     # integer cents, always positive
	account: str = ""         # GL account code


@dataclass
class FXTranslationAppliedEvent(DomainEvent):
	"""Emitted when FX translation is applied to a subsidiary's trial balance."""
	event_type: str = "finance.consolidation.fx.applied"
	run_id: str = ""
	entity_id: str = ""
	period: str = ""
	reporting_currency: str = ""    # e.g. "USD"
	functional_currency: str = ""   # e.g. "EUR"
	rate_used: str = ""             # Decimal as string to avoid float


@dataclass
class ConsolidationRunCompletedEvent(DomainEvent):
	"""Emitted when a consolidation run finishes successfully."""
	event_type: str = "finance.consolidation.run.completed"
	run_id: str = ""
	period: str = ""
	entities_consolidated: int = 0
	eliminations_count: int = 0


@dataclass
class MinorityInterestComputedEvent(DomainEvent):
	"""Emitted when minority interest is calculated for a subsidiary."""
	event_type: str = "finance.consolidation.minority.computed"
	run_id: str = ""
	subsidiary_id: str = ""
	minority_pct: str = ""          # Decimal as string e.g. "20.0000"
	minority_equity_cents: int = 0  # integer cents


__all__ = [
	"ConsolidationRunStartedEvent",
	"IntercompanyEliminationPostedEvent",
	"FXTranslationAppliedEvent",
	"ConsolidationRunCompletedEvent",
	"MinorityInterestComputedEvent",
	"emit_event",
]
