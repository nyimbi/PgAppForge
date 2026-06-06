"""
pgappforge/plugins/erp/operations/plm/events.py

Domain events for the Product Lifecycle Management (PLM) plugin.

Events emitted:
  ops.plm.version.created     — new product version created
  ops.plm.eco.submitted       — engineering change order submitted for review
  ops.plm.eco.approved        — engineering change order approved
  ops.plm.bom.released        — bill of materials released
  ops.plm.stage_gate.passed   — product passed a stage gate review
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class ProductVersionCreatedEvent(DomainEvent):
	"""Emitted when a new PlmProductVersion row is created."""
	event_type: str = "ops.plm.version.created"
	version_id: str = ""
	product_id: str = ""
	version_number: str = ""


@dataclass
class EcoSubmittedEvent(DomainEvent):
	"""Emitted when an ECO transitions to SUBMITTED."""
	event_type: str = "ops.plm.eco.submitted"
	eco_id: str = ""
	title: str = ""
	submitted_by: str = ""


@dataclass
class EcoApprovedEvent(DomainEvent):
	"""Emitted when an ECO transitions to APPROVED."""
	event_type: str = "ops.plm.eco.approved"
	eco_id: str = ""
	approved_by: str = ""


@dataclass
class BomReleasedEvent(DomainEvent):
	"""Emitted when a BillOfMaterials transitions to RELEASED."""
	event_type: str = "ops.plm.bom.released"
	bom_id: str = ""
	product_id: str = ""
	version_number: str = ""


@dataclass
class StageGatePassedEvent(DomainEvent):
	"""Emitted when a product passes a named stage gate."""
	event_type: str = "ops.plm.stage_gate.passed"
	product_id: str = ""
	gate_name: str = ""
	approved_by: str = ""


__all__ = [
	"ProductVersionCreatedEvent",
	"EcoSubmittedEvent",
	"EcoApprovedEvent",
	"BomReleasedEvent",
	"StageGatePassedEvent",
]
