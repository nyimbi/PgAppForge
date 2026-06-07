"""
pgappforge/plugins/erp/finance/ap_automation/events.py

Domain events for the AP Invoice Automation plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  finance.ap_automation.captured        — raw invoice captured and extracted
  finance.ap_automation.matched         — capture matched to a known vendor
  finance.ap_automation.rejected        — capture rejected (bad data / low confidence)
  finance.ap_automation.ap_invoice_created — AP invoice created from a capture
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class InvoiceCapturedEvent(DomainEvent):
	"""Emitted after raw invoice content is captured and field extraction completes."""
	event_type: str = "finance.ap_automation.captured"
	capture_id: str = ""
	detected_vendor: str = ""
	detected_amount_cents: int = 0
	tenant_id: str = ""


@dataclass
class InvoiceMatchedEvent(DomainEvent):
	"""Emitted when a capture is matched to a known AP supplier."""
	event_type: str = "finance.ap_automation.matched"
	capture_id: str = ""
	vendor_id: str = ""
	confidence_pct: int = 0


@dataclass
class InvoiceRejectedEvent(DomainEvent):
	"""Emitted when a capture is rejected due to data quality or policy."""
	event_type: str = "finance.ap_automation.rejected"
	capture_id: str = ""
	reason: str = ""


@dataclass
class APInvoiceCreatedFromCaptureEvent(DomainEvent):
	"""Emitted when an AP invoice is successfully created from a capture."""
	event_type: str = "finance.ap_automation.ap_invoice_created"
	capture_id: str = ""
	ap_invoice_id: str = ""
	amount_cents: int = 0


__all__ = [
	"InvoiceCapturedEvent",
	"InvoiceMatchedEvent",
	"InvoiceRejectedEvent",
	"APInvoiceCreatedFromCaptureEvent",
]
