"""
pgappforge/plugins/erp/operations/scm/events.py

Domain events for the Supply Chain Management plugin.

Emitted events:
  scm.supplier.created             — new supplier onboarded
  scm.supplier.approved            — supplier set as preferred/approved
  scm.supplier.kpi_updated         — rating / OTD% / quality_score recalculated
  scm.supplier_product.created     — new sourcing price record added
  scm.purchase_requisition.created — PR raised
  scm.purchase_requisition.approved — PR approved
  scm.purchase_order.created       — PO confirmed and sent to supplier
  scm.goods_receipt.created        — goods received and GRN posted
  scm.supplier_invoice.matched     — 3-way match passed (APPROVED)
  scm.supplier_invoice.disputed    — 3-way match failed (DISPUTED)
  scm.shipment.created             — new shipment tracking record
  scm.shipment.status_changed      — shipment milestone update
  scm.shipment.delivered           — shipment reached destination
  scm.shipment.exception           — shipment exception flagged

Consumed events (from upstream):
  ap.invoice.approved              — may trigger lead-time / quality KPI refresh
  pp.production_order.released     — may trigger replenishment purchase order creation
  qc.inspection.failed             — feeds supplier quality_score recalculation
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class SupplierCreatedEvent(DomainEvent):
	event_type: str = "scm.supplier.created"
	supplier_id: str = ""
	supplier_code: str = ""
	name: str = ""
	party_id: str = ""


@dataclass
class SupplierApprovedEvent(DomainEvent):
	event_type: str = "scm.supplier.approved"
	supplier_id: str = ""
	supplier_code: str = ""
	approved_by: str = ""


@dataclass
class SupplierKPIUpdatedEvent(DomainEvent):
	event_type: str = "scm.supplier.kpi_updated"
	supplier_id: str = ""
	supplier_code: str = ""
	rating: str = ""          # Decimal as string
	on_time_delivery_pct: str = ""
	quality_score: str = ""
	period_days: int = 365


@dataclass
class SupplierProductCreatedEvent(DomainEvent):
	event_type: str = "scm.supplier_product.created"
	supplier_product_id: str = ""
	supplier_id: str = ""
	product_id: str = ""
	price_cents: int = 0
	currency_code: str = ""
	lead_time_days: int = 0
	valid_from: str = ""


@dataclass
class PurchaseRequisitionCreatedEvent(DomainEvent):
	event_type: str = "scm.purchase_requisition.created"
	requisition_id: str = ""
	requester_id: str = ""
	department_id: str = ""
	required_by: str = ""
	item_count: int = 0


@dataclass
class PurchaseRequisitionApprovedEvent(DomainEvent):
	event_type: str = "scm.purchase_requisition.approved"
	requisition_id: str = ""
	approver_id: str = ""


@dataclass
class PurchaseOrderCreatedEvent(DomainEvent):
	event_type: str = "scm.purchase_order.created"
	po_id: str = ""
	po_number: str = ""
	supplier_id: str = ""
	requisition_id: str = ""
	order_date: str = ""
	expected_delivery_date: str = ""
	total_amount_cents: int = 0
	currency_code: str = ""
	line_count: int = 0


@dataclass
class GoodsReceiptCreatedEvent(DomainEvent):
	event_type: str = "scm.goods_receipt.created"
	grn_id: str = ""
	grn_number: str = ""
	po_id: str = ""
	received_date: str = ""
	received_by: str = ""
	accepted_total_cents: int = 0


@dataclass
class SupplierInvoiceMatchedEvent(DomainEvent):
	event_type: str = "scm.supplier_invoice.matched"
	invoice_id: str = ""
	invoice_number: str = ""
	po_id: str = ""
	supplier_id: str = ""
	total_cents: int = 0


@dataclass
class SupplierInvoiceDisputedEvent(DomainEvent):
	event_type: str = "scm.supplier_invoice.disputed"
	invoice_id: str = ""
	invoice_number: str = ""
	po_id: str = ""
	supplier_id: str = ""
	total_cents: int = 0
	match_notes: str = ""


@dataclass
class ShipmentCreatedEvent(DomainEvent):
	event_type: str = "scm.shipment.created"
	shipment_id: str = ""
	carrier: str = ""
	tracking_number: str = ""
	supplier_id: str = ""
	destination_warehouse_id: str = ""
	estimated_arrival: str = ""


@dataclass
class ShipmentStatusChangedEvent(DomainEvent):
	event_type: str = "scm.shipment.status_changed"
	shipment_id: str = ""
	carrier: str = ""
	tracking_number: str = ""
	old_status: str = ""
	new_status: str = ""
	location: str = ""
	note: str = ""


@dataclass
class ShipmentDeliveredEvent(DomainEvent):
	event_type: str = "scm.shipment.delivered"
	shipment_id: str = ""
	carrier: str = ""
	tracking_number: str = ""
	supplier_id: str = ""
	destination_warehouse_id: str = ""
	actual_arrival: str = ""
	estimated_arrival: str = ""
	days_variance: int = 0    # positive = late, negative = early


@dataclass
class ShipmentExceptionEvent(DomainEvent):
	event_type: str = "scm.shipment.exception"
	shipment_id: str = ""
	carrier: str = ""
	tracking_number: str = ""
	exception_description: str = ""
	location: str = ""


__all__ = [
	"SupplierCreatedEvent",
	"SupplierApprovedEvent",
	"SupplierKPIUpdatedEvent",
	"SupplierProductCreatedEvent",
	"PurchaseRequisitionCreatedEvent",
	"PurchaseRequisitionApprovedEvent",
	"PurchaseOrderCreatedEvent",
	"GoodsReceiptCreatedEvent",
	"SupplierInvoiceMatchedEvent",
	"SupplierInvoiceDisputedEvent",
	"ShipmentCreatedEvent",
	"ShipmentStatusChangedEvent",
	"ShipmentDeliveredEvent",
	"ShipmentExceptionEvent",
]
