"""
pgappforge/plugins/erp/procurement/supplier_portal/events.py

Domain events for the Supplier Portal plugin.

Events emitted:
  procurement.supplier_portal.registered    — new supplier profile created
  procurement.supplier_portal.kyc.approved  — KYC documents approved
  procurement.supplier_portal.bank.verified — bank details verified
  procurement.supplier_portal.rated         — performance scorecard updated
  procurement.supplier_portal.suspended     — supplier suspended
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Registration / KYC events
# ---------------------------------------------------------------------------

@dataclass
class SupplierRegisteredEvent(DomainEvent):
	"""Emitted when a new SupplierProfile is created."""
	event_type: str = "procurement.supplier_portal.registered"
	supplier_id: str = ""
	company_name: str = ""
	tenant_id: str = ""


@dataclass
class KYCApprovedEvent(DomainEvent):
	"""Emitted when supplier KYC is approved."""
	event_type: str = "procurement.supplier_portal.kyc.approved"
	supplier_id: str = ""
	approved_by: str = ""


@dataclass
class SupplierBankDetailsVerifiedEvent(DomainEvent):
	"""Emitted when a supplier's bank details are verified."""
	event_type: str = "procurement.supplier_portal.bank.verified"
	supplier_id: str = ""
	bank_ref: str = ""         # external bank reference / verification token


# ---------------------------------------------------------------------------
# Performance / status events
# ---------------------------------------------------------------------------

@dataclass
class SupplierPerformanceRatedEvent(DomainEvent):
	"""Emitted when a SupplierPerformanceCard is created or updated."""
	event_type: str = "procurement.supplier_portal.rated"
	supplier_id: str = ""
	period: str = ""           # e.g. "2025-Q1"
	score: str = ""            # composite_score as Decimal string


@dataclass
class SupplierSuspendedEvent(DomainEvent):
	"""Emitted when a supplier's KYC status is set to SUSPENDED."""
	event_type: str = "procurement.supplier_portal.suspended"
	supplier_id: str = ""
	reason: str = ""


# ---------------------------------------------------------------------------
# Supplier self-service procurement events
# ---------------------------------------------------------------------------

@dataclass
class POAcknowledgedEvent(DomainEvent):
	"""Emitted when a supplier acknowledges a purchase order."""
	event_type: str = "procurement.supplier_portal.po.acknowledged"
	po_id: str = ""
	po_source: str = ""
	supplier_id: str = ""
	acknowledgement_id: str = ""
	confirmed_delivery_date: str = ""


@dataclass
class AdvanceShipmentNoticeSubmittedEvent(DomainEvent):
	"""Emitted when a supplier submits an advance shipment notice."""
	event_type: str = "procurement.supplier_portal.asn.submitted"
	po_id: str = ""
	po_source: str = ""
	supplier_id: str = ""
	asn_id: str = ""
	asn_number: str = ""
	tracking_number: str = ""


@dataclass
class VendorInvoiceSubmittedEvent(DomainEvent):
	"""Emitted when a supplier submits an invoice for AP approval."""
	event_type: str = "procurement.supplier_portal.invoice.submitted"
	po_id: str = ""
	po_source: str = ""
	supplier_id: str = ""
	invoice_id: str = ""
	invoice_number: str = ""
	amount_cents: int = 0


__all__ = [
	"SupplierRegisteredEvent",
	"KYCApprovedEvent",
	"SupplierBankDetailsVerifiedEvent",
	"SupplierPerformanceRatedEvent",
	"SupplierSuspendedEvent",
	"POAcknowledgedEvent",
	"AdvanceShipmentNoticeSubmittedEvent",
	"VendorInvoiceSubmittedEvent",
]
