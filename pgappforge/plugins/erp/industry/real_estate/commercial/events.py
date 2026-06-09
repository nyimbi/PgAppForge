"""
pgappforge/plugins/erp/industry/real_estate/commercial/events.py

Domain events for the Commercial Real Estate sub-plugin.

All monetary fields are integer cents — never float.

Events emitted
--------------
  re_com.lease.signed      — commercial lease signed / activated
  re_com.cam.reconciled    — CAM reconciliation finalised for a property-year
  re_com.loi.accepted      — letter of intent accepted; caller should create lease
  re_com.space.vacated     — commercial space unit vacated (lease terminated / expired)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Lease events
# ---------------------------------------------------------------------------

@dataclass
class CommercialLeaseSignedEvent(DomainEvent):
	"""Emitted when a CommercialLease transitions to ACTIVE."""
	event_type: str = "re_com.lease.signed"
	lease_id: str = ""
	space_id: str = ""
	tenant_party_id: str = ""
	monthly_rent_cents: int = 0


# ---------------------------------------------------------------------------
# CAM events
# ---------------------------------------------------------------------------

@dataclass
class CAMReconciliationFinalizedEvent(DomainEvent):
	"""Emitted when a CAMReconciliation record is set to FINAL status."""
	event_type: str = "re_com.cam.reconciled"
	property_id: str = ""
	year: int = 0
	variance_cents: int = 0


# ---------------------------------------------------------------------------
# LOI events
# ---------------------------------------------------------------------------

@dataclass
class LOIAcceptedEvent(DomainEvent):
	"""Emitted when a Letter of Intent is accepted by the landlord."""
	event_type: str = "re_com.loi.accepted"
	loi_id: str = ""
	property_id: str = ""
	prospect_party_id: str = ""


# ---------------------------------------------------------------------------
# Space events
# ---------------------------------------------------------------------------

@dataclass
class SpaceVacatedEvent(DomainEvent):
	"""Emitted when a SpaceUnit transitions to VACANT (lease terminated/expired)."""
	event_type: str = "re_com.space.vacated"
	space_id: str = ""
	property_id: str = ""


__all__ = [
	"CommercialLeaseSignedEvent",
	"CAMReconciliationFinalizedEvent",
	"LOIAcceptedEvent",
	"SpaceVacatedEvent",
]
