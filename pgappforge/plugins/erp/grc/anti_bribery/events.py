"""
pgappforge/plugins/erp/grc/anti_bribery/events.py

Anti-Bribery & Corruption domain events.

Events emitted:
  grc.anti_bribery.gift.logged           — gift/entertainment entry recorded
  grc.anti_bribery.gift.approval_required — value exceeds threshold; needs review
  grc.anti_bribery.coi.submitted         — conflict-of-interest declaration filed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class GiftLoggedEvent(DomainEvent):
	event_type: str = "grc.anti_bribery.gift.logged"
	gift_id: str = ""
	value_cents: int = 0
	is_government_official: bool = False


@dataclass
class GiftApprovalRequiredEvent(DomainEvent):
	event_type: str = "grc.anti_bribery.gift.approval_required"
	gift_id: str = ""
	given_to: str = ""
	value_cents: int = 0
	threshold_cents: int = 0


@dataclass
class CoiDeclarationSubmittedEvent(DomainEvent):
	event_type: str = "grc.anti_bribery.coi.submitted"
	declaration_id: str = ""
	employee_id: str = ""
	category: str = ""


__all__ = [
	"GiftLoggedEvent",
	"GiftApprovalRequiredEvent",
	"CoiDeclarationSubmittedEvent",
]
