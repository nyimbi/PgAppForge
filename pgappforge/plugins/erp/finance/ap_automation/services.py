"""
pgappforge/plugins/erp/finance/ap_automation/services.py

APAutomationService — touchless AP invoice capture pipeline.

Pipeline:
  capture_invoice()                → InvoiceCapture (PENDING→EXTRACTED)
  match_to_vendor()                → InvoiceCapture (EXTRACTED→MATCHED)
  create_ap_invoice_from_capture() → dict with ap_invoice_id
  get_capture_accuracy()           → accuracy stats dict

Field extraction uses stdlib only (re, datetime).  No external ML or OCR
dependencies — the service documents hook points for OCR integration.

OCR integration hook
--------------------
Replace _extract_fields() with a call to an external OCR service:
  - Google Cloud Vision API (document_text_detection)
  - Azure Form Recognizer (invoice model)
  - Tesseract via pytesseract (local, open source)

The returned dict must contain the same keys (_vendor, _amount_cents,
_date, _invoice_number, _currency).  Everything from match_to_vendor()
onward works unchanged.

BPM actions registered:
  finance.ap_automation.capture — capture and extract raw invoice text
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.finance.ap_automation.models import InvoiceCapture
from pgappforge.plugins.erp.finance.ap_automation.events import (
	APInvoiceCreatedFromCaptureEvent,
	InvoiceCapturedEvent,
	InvoiceMatchedEvent,
	InvoiceRejectedEvent,
)
from pgappforge.plugins.erp.foundation.events import emit_event

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Amount patterns (ordered: most-specific first)
# ---------------------------------------------------------------------------
_AMOUNT_PATTERNS: list[re.Pattern] = [
	re.compile(
		r'(?:total|amount\s+due|grand\s+total|invoice\s+total)'
		r'[\s:]+(?:KES|USD|EUR|UGX|TZS)?\s*([\d,]+\.?\d*)',
		re.IGNORECASE,
	),
	re.compile(
		r'(?:KES|USD|EUR|UGX|TZS)\s*([\d,]+\.?\d*)',
		re.IGNORECASE,
	),
]

_DATE_PATTERNS: list[tuple[re.Pattern, str]] = [
	(re.compile(r'(?:date|invoice\s+date|dated)[\s:]+((\d{4}-\d{2}-\d{2}))', re.IGNORECASE), "%Y-%m-%d"),
	(re.compile(r'\b(\d{2}[/-]\d{2}[/-]\d{4})\b'), "%d/%m/%Y"),
	(re.compile(
		r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b',
		re.IGNORECASE,
	), "%d %b %Y"),
]

_INV_PATTERNS: list[re.Pattern] = [
	re.compile(r'invoice\s*(?:no|number|#)?[\s:#]*([A-Za-z0-9][A-Za-z0-9\-/]+)', re.IGNORECASE),
	re.compile(r'\bINV[\s\-:]*([A-Za-z0-9\-/]+)', re.IGNORECASE),
]

_VENDOR_PATTERNS: list[re.Pattern] = [
	re.compile(r'(?:from|vendor|supplier|bill\s+from)[\s:]+(.+)', re.IGNORECASE),
	re.compile(
		r'^([A-Z][A-Za-z\s,]+(?:Ltd|Limited|Inc|LLC|Corp|Co)\.?)',
		re.MULTILINE,
	),
]

_CURRENCY_RE = re.compile(r'\b(KES|USD|EUR|UGX|TZS|GBP|ZAR|NGN)\b', re.IGNORECASE)


def _emit(event: Any, session: Any = None) -> None:
	try:
		emit_event(event, session)
	except Exception as exc:
		log.debug("_emit: %s suppressed: %s", type(event).__name__, exc)


# ---------------------------------------------------------------------------
# APAutomationService
# ---------------------------------------------------------------------------

class APAutomationService:
	"""Stateless service — instantiate per request or share as singleton."""

	# ------------------------------------------------------------------
	# Capture entry point
	# ------------------------------------------------------------------

	def capture_invoice(
		self,
		raw_content: str,
		tenant_id: str,
		session: Any,
		*,
		source_format: str = "TEXT",
	) -> InvoiceCapture:
		"""Create an InvoiceCapture record, run field extraction, and persist.

		Steps:
		  1. Create PENDING capture with raw_content.
		  2. Run _extract_fields() — stdlib regex, no network calls.
		  3. Populate detected_* fields and set status=EXTRACTED.
		  4. Flush and emit InvoiceCapturedEvent.
		"""
		assert raw_content, "raw_content is required"

		capture = InvoiceCapture(
			tenant_id=tenant_id,
			raw_content=raw_content,
			source_format=source_format,
			status="PENDING",
		)
		session.add(capture)
		session.flush()  # get capture.id before extraction

		extracted = self._extract_fields(capture)

		capture.detected_vendor = extracted.get("vendor")
		capture.detected_amount_cents = extracted.get("amount_cents")
		capture.detected_date = extracted.get("invoice_date")
		capture.detected_invoice_number = extracted.get("invoice_number")
		capture.detected_currency = extracted.get("currency")
		capture.extraction_log = extracted
		capture.status = "EXTRACTED"
		session.flush()

		_emit(
			InvoiceCapturedEvent(
				aggregate_id=capture.id,
				aggregate_type="InvoiceCapture",
				tenant_id=tenant_id,
				capture_id=capture.id,
				detected_vendor=capture.detected_vendor or "",
				detected_amount_cents=capture.detected_amount_cents or 0,
			),
			session,
		)
		log.info(
			"capture_invoice: capture_id=%s vendor=%r amount=%s",
			capture.id, capture.detected_vendor, capture.detected_amount_cents,
		)
		return capture

	# ------------------------------------------------------------------
	# Field extraction (stdlib only)
	# ------------------------------------------------------------------

	def _extract_fields(self, capture: InvoiceCapture) -> dict:
		"""Extract structured fields from raw_content using stdlib regex.

		Returns a dict with keys:
		  vendor, amount_cents, invoice_date (date|None), invoice_number,
		  currency, raw_amount_str, raw_date_str, raw_vendor_str
		  plus per-field match debug info.

		OCR hook: replace this method body with an external OCR API call.
		The caller (capture_invoice) maps the returned dict to detected_* fields.
		"""
		text = capture.raw_content
		result: dict[str, Any] = {}

		# ── Amount ────────────────────────────────────────────────────
		amount_cents: int | None = None
		raw_amount: str | None = None
		for pat in _AMOUNT_PATTERNS:
			m = pat.search(text)
			if m:
				raw_amount = m.group(1).replace(",", "")
				try:
					amount_cents = int(float(raw_amount) * 100)
					result["amount_pattern_matched"] = pat.pattern[:60]
				except ValueError:
					pass
				break
		result["amount_cents"] = amount_cents
		result["raw_amount_str"] = raw_amount

		# ── Date ──────────────────────────────────────────────────────
		invoice_date: date | None = None
		raw_date: str | None = None
		for pat, fmt in _DATE_PATTERNS:
			m = pat.search(text)
			if m:
				# group(1) always the date string; group(2) may exist for named-context patterns
				raw_date = m.group(2) if pat.groups >= 2 and m.lastindex and m.lastindex >= 2 else m.group(1)
				try:
					# Normalise separators for dd/mm/yyyy variant
					normalised = raw_date.replace("-", "/")
					invoice_date = datetime.strptime(normalised, fmt.replace("-", "/")).date()
					result["date_pattern_matched"] = pat.pattern[:60]
				except (ValueError, AttributeError):
					# try alternate parse for month-name form
					try:
						invoice_date = datetime.strptime(raw_date.strip(), fmt).date()
					except ValueError:
						pass
				if invoice_date:
					break
		result["invoice_date"] = invoice_date
		result["raw_date_str"] = raw_date

		# ── Invoice number ────────────────────────────────────────────
		invoice_number: str | None = None
		for pat in _INV_PATTERNS:
			m = pat.search(text)
			if m:
				invoice_number = m.group(1).strip()
				result["inv_pattern_matched"] = pat.pattern[:60]
				break
		result["invoice_number"] = invoice_number

		# ── Vendor ────────────────────────────────────────────────────
		vendor: str | None = None
		for pat in _VENDOR_PATTERNS:
			m = pat.search(text)
			if m:
				vendor = m.group(1).strip()[:300]
				result["vendor_pattern_matched"] = pat.pattern[:60]
				break
		result["vendor"] = vendor
		result["raw_vendor_str"] = vendor

		# ── Currency ──────────────────────────────────────────────────
		currency: str | None = None
		m = _CURRENCY_RE.search(text)
		if m:
			currency = m.group(1).upper()
		result["currency"] = currency

		return result

	# ------------------------------------------------------------------
	# Vendor matching
	# ------------------------------------------------------------------

	def match_to_vendor(self, capture_id: str, session: Any) -> InvoiceCapture:
		"""Attempt to match the capture to an AP supplier via ILIKE fuzzy search.

		Sets:
		  matched_vendor_id = str(best_match.id)
		  confidence_pct    = 90 (unique match) | 70 (multiple candidates)
		  status            = MATCHED

		If the AP plugin is not installed or no match is found, the capture
		is left in EXTRACTED status (manual review required).
		"""
		capture: InvoiceCapture | None = session.execute(
			sa.select(InvoiceCapture).where(InvoiceCapture.id == capture_id)
		).scalar_one_or_none()
		assert capture is not None, f"InvoiceCapture {capture_id!r} not found"

		if not capture.detected_vendor:
			log.info("match_to_vendor: capture_id=%s has no detected_vendor, skipping", capture_id)
			return capture

		try:
			from pgappforge.plugins.erp.finance.ap.models import APSupplier

			search_term = capture.detected_vendor[:50]
			candidates = list(
				session.execute(
					sa.select(APSupplier).where(
						APSupplier.tenant_id == capture.tenant_id,
						APSupplier.name.ilike(f"%{search_term}%"),
					).limit(5)
				).scalars().all()
			)

			if candidates:
				best = candidates[0]
				capture.matched_vendor_id = str(best.id)
				capture.confidence_pct = 90 if len(candidates) == 1 else 70
				capture.status = "MATCHED"
				session.flush()

				_emit(
					InvoiceMatchedEvent(
						aggregate_id=capture.id,
						aggregate_type="InvoiceCapture",
						tenant_id=capture.tenant_id,
						capture_id=capture.id,
						vendor_id=str(best.id),
						confidence_pct=capture.confidence_pct,
					),
					session,
				)
				log.info(
					"match_to_vendor: capture_id=%s matched vendor_id=%s confidence=%d%%",
					capture_id, best.id, capture.confidence_pct,
				)
			else:
				log.info(
					"match_to_vendor: capture_id=%s no AP supplier matches for %r",
					capture_id, search_term,
				)

		except ImportError:
			log.debug("match_to_vendor: AP plugin not available, skipping vendor match")

		return capture

	# ------------------------------------------------------------------
	# Reject a capture
	# ------------------------------------------------------------------

	def reject_capture(
		self,
		capture_id: str,
		reason: str,
		session: Any,
	) -> InvoiceCapture:
		"""Manually reject a capture with a reason string."""
		capture: InvoiceCapture | None = session.execute(
			sa.select(InvoiceCapture).where(InvoiceCapture.id == capture_id)
		).scalar_one_or_none()
		assert capture is not None, f"InvoiceCapture {capture_id!r} not found"

		capture.status = "REJECTED"
		capture.rejection_reason = reason
		session.flush()

		_emit(
			InvoiceRejectedEvent(
				aggregate_id=capture.id,
				aggregate_type="InvoiceCapture",
				tenant_id=capture.tenant_id,
				capture_id=capture.id,
				reason=reason,
			),
			session,
		)
		log.info("reject_capture: capture_id=%s reason=%r", capture_id, reason)
		return capture

	# ------------------------------------------------------------------
	# AP invoice creation
	# ------------------------------------------------------------------

	def create_ap_invoice_from_capture(
		self,
		capture_id: str,
		session: Any,
	) -> dict:
		"""Convert a MATCHED or EXTRACTED capture into an AP invoice.

		The AP invoice is created via direct model instantiation so this service
		remains decoupled from APService internals.  The invoice lands in
		PENDING_REVIEW status so a human can confirm fields before GL posting.

		Returns dict:
		  {"capture_id": ..., "ap_invoice_id": ..., "amount_cents": ...}
		  or {"capture_id": ..., "error": ...} on failure.
		"""
		capture: InvoiceCapture | None = session.execute(
			sa.select(InvoiceCapture).where(InvoiceCapture.id == capture_id)
		).scalar_one_or_none()
		assert capture is not None, f"InvoiceCapture {capture_id!r} not found"
		assert capture.status in ("MATCHED", "EXTRACTED"), (
			f"Capture {capture_id!r} must be MATCHED or EXTRACTED (is {capture.status!r})"
		)

		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice

			inv_date = capture.detected_date or date.today()
			inv = APInvoice(
				tenant_id=capture.tenant_id,
				supplier_id=capture.matched_vendor_id or "UNKNOWN",
				invoice_number=(
					capture.detected_invoice_number
					or f"CAPTURE-{capture_id[:8]}"
				),
				invoice_date=inv_date,
				due_date=inv_date,
				subtotal_cents=capture.detected_amount_cents or 0,
				total_cents=capture.detected_amount_cents or 0,
				tax_cents=0,
				status="PENDING_REVIEW",
				currency_code=capture.detected_currency or "KES",
			)
			session.add(inv)
			session.flush()

			capture.ap_invoice_id = str(inv.id)
			capture.status = "CONVERTED"
			session.flush()

			_emit(
				APInvoiceCreatedFromCaptureEvent(
					aggregate_id=capture.id,
					aggregate_type="InvoiceCapture",
					tenant_id=capture.tenant_id,
					capture_id=capture_id,
					ap_invoice_id=str(inv.id),
					amount_cents=inv.total_cents,
				),
				session,
			)
			log.info(
				"create_ap_invoice_from_capture: capture_id=%s → ap_invoice_id=%s amount=%d",
				capture_id, inv.id, inv.total_cents,
			)
			return {
				"capture_id": capture_id,
				"ap_invoice_id": str(inv.id),
				"amount_cents": inv.total_cents,
			}

		except Exception as exc:
			log.warning("create_ap_invoice_from_capture: failed: %s", exc)
			return {"capture_id": capture_id, "error": str(exc)}

	# ------------------------------------------------------------------
	# Accuracy reporting
	# ------------------------------------------------------------------

	def get_capture_accuracy(self, tenant_id: str, session: Any) -> dict:
		"""Return auto-match accuracy stats for the tenant.

		Returns:
		  total_captures, auto_matched_pct, manual_review_count
		"""
		total: int = (
			session.execute(
				sa.select(sa.func.count())
				.select_from(InvoiceCapture)
				.where(InvoiceCapture.tenant_id == tenant_id)
			).scalar()
			or 0
		)
		matched: int = (
			session.execute(
				sa.select(sa.func.count())
				.select_from(InvoiceCapture)
				.where(
					InvoiceCapture.tenant_id == tenant_id,
					InvoiceCapture.status.in_(["MATCHED", "CONVERTED"]),
				)
			).scalar()
			or 0
		)
		return {
			"total_captures": total,
			"auto_matched_pct": round(matched / total * 100) if total else 0,
			"manual_review_count": total - matched,
		}


# ---------------------------------------------------------------------------
# BPM action registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry

	@BPMActionRegistry.register(
		"finance.ap_automation.capture",
		"Capture and extract AP invoice from raw text",
	)
	def _bpm_capture_invoice(
		record_ctx: dict,
		session: Any,
		raw_content: str = "",
		source_format: str = "TEXT",
		auto_match: bool = True,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = APAutomationService()
			capture = svc.capture_invoice(
				raw_content=raw_content,
				tenant_id=tenant_id,
				session=session,
				source_format=source_format,
			)
			if auto_match and capture.detected_vendor:
				capture = svc.match_to_vendor(capture.id, session)
			return {
				"status": "ok",
				"capture_id": capture.id,
				"capture_status": capture.status,
				"detected_vendor": capture.detected_vendor,
				"detected_amount_cents": capture.detected_amount_cents,
				"confidence_pct": capture.confidence_pct,
			}
		except Exception as exc:
			log.warning("bpm finance.ap_automation.capture failed: %s", exc)
			return {"status": "error", "message": str(exc)}

except ImportError:
	log.debug("ap_automation.services: BPMActionRegistry not available, skipping BPM registrations")


__all__ = ["APAutomationService"]
