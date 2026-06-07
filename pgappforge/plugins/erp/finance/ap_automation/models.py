"""
pgappforge/plugins/erp/finance/ap_automation/models.py

SQLAlchemy models for the AP Invoice Automation plugin.

Design invariants:
  - All PKs: UUID4 string, gen_random_uuid() server default
  - All timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - All monetary amounts: BigInteger cents (NEVER float)
  - JSONB for extraction_log
  - raw_content stored as Text (PDF-extracted, email body, CSV row)
  - matched_vendor_id and ap_invoice_id are soft FKs (VARCHAR cross-plugin)

Table prefix: apc_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Column,
	Date,
	DateTime,
	Index,
	Integer,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# InvoiceCapture
# ---------------------------------------------------------------------------

class InvoiceCapture(AuditMixin, Model):
	"""Raw invoice capture record — the entry point for touchless AP automation.

	Lifecycle:
	  PENDING → EXTRACTED (after _extract_fields)
	         → MATCHED    (after match_to_vendor succeeds)
	         → CONVERTED  (after create_ap_invoice_from_capture)
	         → REJECTED   (explicit rejection)

	source_format describes the input medium:
	  TEXT     — plain text, pre-extracted by caller
	  PDF_TEXT — text layer extracted from PDF (e.g. via pdfminer)
	  EMAIL    — email body (HTML stripped)
	  CSV      — single CSV row or block

	extraction_log stores per-field regex match results for audit and debugging.

	OCR integration hook: replace _extract_fields() in APAutomationService
	with a call to an external OCR API (Google Vision, Azure Form Recognizer,
	Tesseract+pytesseract).  The pipeline from match_to_vendor onward is
	identical regardless of how the detected_* fields are populated.
	"""

	__allow_unmapped__ = True
	__tablename__ = "apc_capture"
	__table_args__ = (
		Index("ix_apc_capture_tenant_status", "tenant_id", "status"),
		Index("ix_apc_capture_tenant_vendor", "tenant_id", "matched_vendor_id"),
		{"extend_existing": True},
	)

	id = Column(
		String(36),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()::text"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	# ── Raw input ───────────────────────────────────────────────────────────
	raw_content = Column(Text, nullable=False)
	source_format = Column(String(30), nullable=False, default="TEXT", server_default="TEXT")

	# ── Extracted fields (stdlib regex; see APAutomationService._extract_fields) ──
	detected_vendor = Column(String(300), nullable=True)
	detected_amount_cents = Column(BigInteger, nullable=True)
	detected_date = Column(Date, nullable=True)
	detected_invoice_number = Column(String(100), nullable=True)
	detected_currency = Column(String(3), nullable=True)

	# ── Matching ────────────────────────────────────────────────────────────
	matched_vendor_id = Column(String(50), nullable=True)   # soft FK to ap_supplier.id
	confidence_pct = Column(Integer, nullable=True)          # 0–100

	# ── Workflow state ──────────────────────────────────────────────────────
	status = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
	ap_invoice_id = Column(String(50), nullable=True)        # soft FK to ap_invoice.id
	rejection_reason = Column(Text, nullable=True)

	# ── Audit log ───────────────────────────────────────────────────────────
	extraction_log = Column(JSONB, nullable=False, default=dict, server_default="{}")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)


__all__ = ["InvoiceCapture"]
