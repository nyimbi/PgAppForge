"""
pgappforge/plugins/erp/finance/ar/invoice_pdf.py

InvoicePDFService — generates a professional PDF or CSV for an AR invoice.

PDF rendering uses reportlab (A4, professional layout with coloured header,
line-items table, totals block, and payment instructions).  Falls back to
b"" if reportlab is not installed.  CSV export is pure-stdlib and always works.

Usage
-----
	from pgappforge.plugins.erp.finance.ar.invoice_pdf import InvoicePDFService

	svc = InvoicePDFService()
	pdf_bytes = svc.generate_invoice_pdf(invoice_id, tenant_id, session)
	csv_str   = svc.generate_invoice_csv(invoice_id, tenant_id, session)
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

log = logging.getLogger(__name__)


class InvoicePDFService:
	"""Generate downloadable invoice documents (PDF or CSV) for AR invoices."""

	# ------------------------------------------------------------------
	# Public: PDF
	# ------------------------------------------------------------------

	def generate_invoice_pdf(self, invoice_id: str, tenant_id: str, session: Any) -> bytes:
		"""Generate a professional PDF invoice for emailing to customers.

		Returns bytes.  Raises ValueError if invoice not found.
		Returns empty bytes if reportlab is unavailable.
		"""
		from sqlalchemy import select
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice

		invoice = session.execute(
			select(ARInvoice).where(
				ARInvoice.id == invoice_id,
				ARInvoice.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if invoice is None:
			raise ValueError(f"ARInvoice {invoice_id!r} not found")

		return self._render_invoice_pdf(invoice)

	def _render_invoice_pdf(self, invoice: Any) -> bytes:
		"""Render invoice as PDF.  Falls back to empty bytes if reportlab absent."""
		try:
			from reportlab.lib.pagesizes import A4
			from reportlab.platypus import (
				SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
			)
			from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
			from reportlab.lib import colors
			from reportlab.lib.units import mm

			buf = io.BytesIO()
			doc = SimpleDocTemplate(
				buf, pagesize=A4,
				leftMargin=20 * mm, rightMargin=20 * mm,
				topMargin=20 * mm, bottomMargin=20 * mm,
			)
			styles = getSampleStyleSheet()
			PRIMARY = colors.HexColor("#1a56db")
			LIGHT_BG = colors.HexColor("#f9fafb")
			BORDER = colors.HexColor("#e5e7eb")

			title_style = ParagraphStyle(
				"InvTitle", parent=styles["Title"],
				fontSize=22, textColor=PRIMARY, spaceAfter=4,
			)
			header_style = ParagraphStyle(	# noqa: F841  (kept for completeness)
				"InvHeader", parent=styles["Normal"],
				fontSize=9, textColor=colors.HexColor("#6b7280"),
			)
			bold_style = ParagraphStyle(
				"InvBold", parent=styles["Normal"],
				fontSize=10, fontName="Helvetica-Bold",
			)

			elements: list[Any] = []

			# ── Header: INVOICE + invoice number ──────────────────────────────
			header_table = Table(
				[[
					Paragraph("INVOICE", title_style),
					Paragraph(f"#{invoice.invoice_number}", bold_style),
				]],
				colWidths=["70%", "30%"],
			)
			header_table.setStyle(TableStyle([
				("ALIGN",  (1, 0), (1, 0), "RIGHT"),
				("VALIGN", (0, 0), (-1, -1), "TOP"),
			]))
			elements.append(header_table)
			elements.append(Spacer(1, 6 * mm))

			# ── Invoice meta ───────────────────────────────────────────────────
			issue_date = (
				invoice.invoice_date.strftime("%d %b %Y")
				if hasattr(invoice, "invoice_date") and invoice.invoice_date
				else "—"
			)
			due_date = (
				invoice.due_date.strftime("%d %b %Y")
				if hasattr(invoice, "due_date") and invoice.due_date
				else "—"
			)
			meta_data = [
				["Invoice Date:", issue_date, "Status:", str(getattr(invoice, "status", "")).upper()],
				["Due Date:", due_date, "Currency:", str(getattr(invoice, "currency_code", "KES"))],
			]
			meta_table = Table(meta_data, colWidths=["25%", "25%", "25%", "25%"])
			meta_table.setStyle(TableStyle([
				("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
				("FONTNAME",     (2, 0), (2, -1), "Helvetica-Bold"),
				("FONTSIZE",     (0, 0), (-1, -1), 9),
				("BOTTOMPADDING",(0, 0), (-1, -1), 4),
			]))
			elements.append(meta_table)
			elements.append(Spacer(1, 8 * mm))

			# ── Line items ─────────────────────────────────────────────────────
			# Support both the ORM relationship (list[ARInvoiceLine]) and a plain
			# JSONB-style list stored on invoice.line_items (legacy / mock objects).
			line_items_raw = getattr(invoice, "line_items", None)
			if line_items_raw is None:
				# Try the ORM relationship
				orm_lines = getattr(invoice, "lines", None) or []
				line_items: list[dict[str, Any]] = [
					{
						"description": getattr(ln, "description", ""),
						"quantity": float(getattr(ln, "quantity", 1)),
						"unit_price_cents": getattr(ln, "unit_price_cents", 0),
						"total_cents": getattr(ln, "line_amount_cents", 0),
					}
					for ln in orm_lines
				]
			else:
				line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []

			rows: list[list[str]] = [["Description", "Qty", "Unit Price", "Total"]]
			for item in line_items:
				qty = item.get("quantity", 1)
				price = item.get("unit_price_cents", 0) / 100
				total = item.get("total_cents", 0) / 100
				rows.append([
					str(item.get("description", "")),
					str(qty),
					f"{price:,.2f}",
					f"{total:,.2f}",
				])

			# ── Totals ─────────────────────────────────────────────────────────
			subtotal = getattr(invoice, "subtotal_cents", 0) or 0
			tax      = getattr(invoice, "tax_cents", 0) or 0
			total    = getattr(invoice, "total_cents", 0) or 0

			rows.append(["", "", "Subtotal:", f"{subtotal / 100:,.2f}"])
			rows.append(["", "", "Tax:", f"{tax / 100:,.2f}"])
			rows.append(["", "", "TOTAL DUE:", f"{total / 100:,.2f}"])

			col_widths = ["50%", "10%", "20%", "20%"]
			n = len(rows)
			items_table = Table(rows, colWidths=col_widths)
			items_table.setStyle(TableStyle([
				("BACKGROUND",    (0, 0), (-1, 0),    PRIMARY),
				("TEXTCOLOR",     (0, 0), (-1, 0),    colors.white),
				("FONTNAME",      (0, 0), (-1, 0),    "Helvetica-Bold"),
				("FONTSIZE",      (0, 0), (-1, -1),   9),
				("ROWBACKGROUNDS",(0, 1), (-1, n - 4), [colors.white, LIGHT_BG]),
				("GRID",          (0, 0), (-1, n - 4), 0.3, BORDER),
				("FONTNAME",      (2, n - 3), (-1, -1), "Helvetica-Bold"),
				("FONTNAME",      (2, -1),    (-1, -1), "Helvetica-Bold"),
				("FONTSIZE",      (2, -1),    (-1, -1), 10),
				("TEXTCOLOR",     (2, -1),    (-1, -1), PRIMARY),
				("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
				("BOTTOMPADDING", (0, 0), (-1, -1), 4),
				("TOPPADDING",    (0, 0), (-1, -1), 4),
				("LEFTPADDING",   (0, 0), (-1, -1), 6),
			]))
			elements.append(items_table)

			# ── Payment instructions ───────────────────────────────────────────
			elements.append(Spacer(1, 8 * mm))
			elements.append(Paragraph("Payment Instructions", bold_style))
			elements.append(Paragraph(
				"Please reference the invoice number when making payment. "
				"Late payments may attract a 2% monthly charge.",
				styles["Normal"],
			))

			doc.build(elements)
			return buf.getvalue()

		except ImportError:
			log.debug("reportlab not installed; returning empty bytes for invoice PDF")
			return b""
		except Exception as exc:
			log.error("Invoice PDF render failed: %s", exc)
			return b""

	# ------------------------------------------------------------------
	# Public: CSV
	# ------------------------------------------------------------------

	def generate_invoice_csv(self, invoice_id: str, tenant_id: str, session: Any) -> str:
		"""CSV fallback for invoice line items.

		Returns a CSV string.  Raises ValueError if invoice not found.
		"""
		from sqlalchemy import select
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice

		invoice = session.execute(
			select(ARInvoice).where(
				ARInvoice.id == invoice_id,
				ARInvoice.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if invoice is None:
			raise ValueError(f"ARInvoice {invoice_id!r} not found")

		return self._render_invoice_csv(invoice)

	def _render_invoice_csv(self, invoice: Any) -> str:
		"""Render invoice as CSV string (pure stdlib, always works)."""
		buf = io.StringIO()
		w = csv.writer(buf)

		# Header summary row
		w.writerow(["Invoice Number", "Date", "Due Date", "Customer", "Total", "Status"])
		w.writerow([
			getattr(invoice, "invoice_number", ""),
			str(getattr(invoice, "invoice_date", "")),
			str(getattr(invoice, "due_date", "")),
			str(getattr(invoice, "customer_id", "")),
			(getattr(invoice, "total_cents", 0) or 0) / 100,
			getattr(invoice, "status", ""),
		])
		w.writerow([])

		# Line items
		w.writerow(["Description", "Qty", "Unit Price", "Total"])

		line_items_raw = getattr(invoice, "line_items", None)
		if line_items_raw is None:
			orm_lines = getattr(invoice, "lines", None) or []
			line_items = [
				{
					"description": getattr(ln, "description", ""),
					"quantity": float(getattr(ln, "quantity", 1)),
					"unit_price_cents": getattr(ln, "unit_price_cents", 0),
					"total_cents": getattr(ln, "line_amount_cents", 0),
				}
				for ln in orm_lines
			]
		else:
			line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []

		for item in line_items:
			w.writerow([
				item.get("description", ""),
				item.get("quantity", 1),
				(item.get("unit_price_cents", 0)) / 100,
				(item.get("total_cents", 0)) / 100,
			])

		return buf.getvalue()


__all__ = ["InvoicePDFService"]
