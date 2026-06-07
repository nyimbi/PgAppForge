"""
pgappforge/plugins/erp/grc/erm/events.py

Enterprise Risk Management domain events.

Events emitted:
  grc.erm.risk.created         — new risk registered
  grc.erm.risk.score.updated   — likelihood/impact recalculated
  grc.erm.kri.breach           — KRI threshold crossed
  grc.erm.treatment.updated    — risk treatment / owner changed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class RiskCreatedEvent(DomainEvent):
	event_type: str = "grc.erm.risk.created"
	risk_id: str = ""
	name: str = ""
	risk_score: int = 0


@dataclass
class RiskScoreUpdatedEvent(DomainEvent):
	event_type: str = "grc.erm.risk.score.updated"
	risk_id: str = ""
	old_score: int = 0
	new_score: int = 0


@dataclass
class KriBreachEvent(DomainEvent):
	event_type: str = "grc.erm.kri.breach"
	kri_id: str = ""
	risk_id: str = ""
	metric_name: str = ""
	threshold: str = ""      # Decimal serialised as str
	current_value: str = ""  # Decimal serialised as str


@dataclass
class RiskTreatmentUpdatedEvent(DomainEvent):
	event_type: str = "grc.erm.treatment.updated"
	risk_id: str = ""
	treatment: str = ""
	owner_id: str = ""


__all__ = [
	"RiskCreatedEvent",
	"RiskScoreUpdatedEvent",
	"KriBreachEvent",
	"RiskTreatmentUpdatedEvent",
]
