"""
pgappforge/plugins/erp/finance/gl/reports.py

FinancialReportService — wires GL service data to the PDF exporter.

Provides PDF and CSV downloads for:
  - Trial Balance
  - Income Statement (P&L)
  - Balance Sheet

PDF rendering delegates to pgappforge.export.pdf_exporter.PDFExporter when
reportlab is available; falls back to a manual reportlab call; returns b"" if
reportlab is absent entirely.  CSV export is pure-stdlib and always works.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

log = logging.getLogger(__name__)


def _cents(v: int) -> str:
	"""Format integer cents as a human-readable decimal string."""
	return f"{v / 100:,.2f}"


# ---------------------------------------------------------------------------
# FinancialReportService
# ---------------------------------------------------------------------------

class FinancialReportService:
	"""Generate downloadable financial statements as PDF or CSV.

	All ``session`` arguments are SQLAlchemy sessions compatible with
	``GLService`` (e.g. Flask-SQLAlchemy ``db.session`` or a scoped session
	obtained via ``appbuilder.get_session``).

	Amounts returned by ``GLService`` are integer cents throughout; this
	service converts them to display strings only at render time.
	"""

	# ------------------------------------------------------------------
	# Public: PDF generators
	# ------------------------------------------------------------------

	def generate_trial_balance_pdf(
		self,
		period_id: str,
		tenant_id: str | None,
		session: Any,
	) -> bytes:
		"""Trial balance as PDF bytes.  Returns b'' when reportlab is absent."""
		from pgappforge.plugins.erp.finance.gl.services import GLService
		data = GLService().get_trial_balance(period_id, session)

		headers = ["Code", "Account Name", "Type", "Period Dr", "Period Cr", "Closing Dr", "Closing Cr"]
		rows = [
			[
				r["account_code"],
				r["account_name"],
				r["account_type"],
				_cents(r["period_debit"]),
				_cents(r["period_credit"]),
				_cents(r["closing_debit"]),
				_cents(r["closing_credit"]),
			]
			for r in data
		]

		total_dr = sum(r["closing_debit"] for r in data)
		total_cr = sum(r["closing_credit"] for r in data)
		rows.append(["", "TOTAL", "", "", "", _cents(total_dr), _cents(total_cr)])

		metadata = {
			"period_id": period_id,
			"balanced": str(total_dr == total_cr),
		}
		if tenant_id:
			metadata["tenant_id"] = tenant_id

		return self._render_table_pdf(
			title=f"Trial Balance — Period {period_id}",
			headers=headers,
			rows=rows,
			metadata=metadata,
		)

	def generate_income_statement_pdf(
		self,
		period_id: str,
		tenant_id: str | None,
		session: Any,
	) -> bytes:
		"""Income Statement as PDF bytes.  Returns b'' when reportlab is absent."""
		from pgappforge.plugins.erp.finance.gl.services import GLService
		data = GLService().get_income_statement(period_id, session)

		headers = ["Code", "Account Name", "Amount"]
		rows: list[list[str]] = []

		rows.append(["", "— REVENUE —", ""])
		for r in data["revenue"]:
			rows.append([r["account_code"], r["account_name"], _cents(r["amount_cents"])])
		rows.append(["", "Total Revenue", _cents(data["total_revenue_cents"])])

		rows.append(["", "", ""])
		rows.append(["", "— EXPENSES —", ""])
		for r in data["expenses"]:
			rows.append([r["account_code"], r["account_name"], _cents(r["amount_cents"])])
		rows.append(["", "Total Expenses", _cents(data["total_expense_cents"])])

		rows.append(["", "", ""])
		net = data["net_income_cents"]
		label = "Net Income" if net >= 0 else "Net Loss"
		rows.append(["", label, _cents(net)])

		metadata = {"period_id": period_id}
		if tenant_id:
			metadata["tenant_id"] = tenant_id

		return self._render_table_pdf(
			title=f"Income Statement — Period {period_id}",
			headers=headers,
			rows=rows,
			metadata=metadata,
		)

	def generate_balance_sheet_pdf(
		self,
		period_id: str,
		tenant_id: str | None,
		session: Any,
	) -> bytes:
		"""Balance Sheet as PDF bytes.  Returns b'' when reportlab is absent."""
		from pgappforge.plugins.erp.finance.gl.services import GLService
		data = GLService().get_balance_sheet(period_id, session)

		headers = ["Code", "Account Name", "Amount"]
		rows: list[list[str]] = []

		rows.append(["", "— ASSETS —", ""])
		for r in data["assets"]["accounts"]:
			rows.append([r["account_code"], r["account_name"], _cents(r["amount_cents"])])
		rows.append(["", "Total Assets", _cents(data["assets"]["total_cents"])])

		rows.append(["", "", ""])
		rows.append(["", "— LIABILITIES —", ""])
		for r in data["liabilities"]["accounts"]:
			rows.append([r["account_code"], r["account_name"], _cents(r["amount_cents"])])
		rows.append(["", "Total Liabilities", _cents(data["liabilities"]["total_cents"])])

		rows.append(["", "", ""])
		rows.append(["", "— EQUITY —", ""])
		for r in data["equity"]["accounts"]:
			rows.append([r["account_code"], r["account_name"], _cents(r["amount_cents"])])
		rows.append(["", "Retained Earnings", _cents(data["equity"]["retained_earnings_cents"])])
		rows.append(["", "Net Income", _cents(data["equity"]["net_income_cents"])])
		rows.append(["", "Total Equity", _cents(data["equity"]["total_cents"])])

		rows.append(["", "", ""])
		rows.append(["", "Total Liabilities + Equity", _cents(data["total_liabilities_and_equity_cents"])])
		rows.append(["", "Balanced", str(data["balanced"])])

		metadata = {
			"period_id": period_id,
			"balanced": str(data["balanced"]),
		}
		if tenant_id:
			metadata["tenant_id"] = tenant_id

		return self._render_table_pdf(
			title=f"Balance Sheet — Period {period_id}",
			headers=headers,
			rows=rows,
			metadata=metadata,
		)

	# ------------------------------------------------------------------
	# Public: CSV generators (pure-stdlib, always works)
	# ------------------------------------------------------------------

	def generate_trial_balance_csv(
		self,
		period_id: str,
		tenant_id: str | None,
		session: Any,
	) -> str:
		"""Trial balance as CSV string."""
		from pgappforge.plugins.erp.finance.gl.services import GLService
		data = GLService().get_trial_balance(period_id, session)

		buf = io.StringIO()
		w = csv.writer(buf)
		w.writerow(["Account Code", "Account Name", "Account Type",
		            "Period Debit", "Period Credit", "Closing Debit", "Closing Credit"])
		for r in data:
			w.writerow([
				r.get("account_code", ""),
				r.get("account_name", ""),
				r.get("account_type", ""),
				r.get("period_debit", 0) / 100,
				r.get("period_credit", 0) / 100,
				r.get("closing_debit", 0) / 100,
				r.get("closing_credit", 0) / 100,
			])
		total_dr = sum(r["closing_debit"] for r in data)
		total_cr = sum(r["closing_credit"] for r in data)
		w.writerow(["", "TOTAL", "", "", "", total_dr / 100, total_cr / 100])
		return buf.getvalue()

	def generate_income_statement_csv(
		self,
		period_id: str,
		tenant_id: str | None,
		session: Any,
	) -> str:
		"""Income statement as CSV string."""
		from pgappforge.plugins.erp.finance.gl.services import GLService
		data = GLService().get_income_statement(period_id, session)

		buf = io.StringIO()
		w = csv.writer(buf)
		w.writerow(["Section", "Account Code", "Account Name", "Amount"])
		for r in data["revenue"]:
			w.writerow(["Revenue", r["account_code"], r["account_name"], r["amount_cents"] / 100])
		w.writerow(["Revenue", "", "Total Revenue", data["total_revenue_cents"] / 100])
		for r in data["expenses"]:
			w.writerow(["Expense", r["account_code"], r["account_name"], r["amount_cents"] / 100])
		w.writerow(["Expense", "", "Total Expenses", data["total_expense_cents"] / 100])
		label = "Net Income" if data["net_income_cents"] >= 0 else "Net Loss"
		w.writerow(["Summary", "", label, data["net_income_cents"] / 100])
		return buf.getvalue()

	def generate_balance_sheet_csv(
		self,
		period_id: str,
		tenant_id: str | None,
		session: Any,
	) -> str:
		"""Balance sheet as CSV string."""
		from pgappforge.plugins.erp.finance.gl.services import GLService
		data = GLService().get_balance_sheet(period_id, session)

		buf = io.StringIO()
		w = csv.writer(buf)
		w.writerow(["Section", "Account Code", "Account Name", "Amount"])
		for r in data["assets"]["accounts"]:
			w.writerow(["Asset", r["account_code"], r["account_name"], r["amount_cents"] / 100])
		w.writerow(["Asset", "", "Total Assets", data["assets"]["total_cents"] / 100])
		for r in data["liabilities"]["accounts"]:
			w.writerow(["Liability", r["account_code"], r["account_name"], r["amount_cents"] / 100])
		w.writerow(["Liability", "", "Total Liabilities", data["liabilities"]["total_cents"] / 100])
		for r in data["equity"]["accounts"]:
			w.writerow(["Equity", r["account_code"], r["account_name"], r["amount_cents"] / 100])
		w.writerow(["Equity", "", "Retained Earnings", data["equity"]["retained_earnings_cents"] / 100])
		w.writerow(["Equity", "", "Net Income", data["equity"]["net_income_cents"] / 100])
		w.writerow(["Equity", "", "Total Equity", data["equity"]["total_cents"] / 100])
		w.writerow(["Summary", "", "Total Liabilities + Equity",
		            data["total_liabilities_and_equity_cents"] / 100])
		w.writerow(["Summary", "", "Balanced", data["balanced"]])
		return buf.getvalue()

	# ------------------------------------------------------------------
	# Private: PDF rendering
	# ------------------------------------------------------------------

	def _render_table_pdf(
		self,
		title: str,
		headers: list[str],
		rows: list[list[str]],
		metadata: dict[str, str] | None = None,
	) -> bytes:
		"""Render tabular data as PDF.

		Strategy (in order):
		  1. PDFExporter.export() — preferred path; handles pagination, styling,
		     metadata section, and alternate row colours.
		  2. Direct reportlab — fallback when PDFExporter API is unavailable or
		     its signature has changed.
		  3. Return b'' — reportlab absent entirely.
		"""
		# -- Strategy 1: PDFExporter -----------------------------------------
		try:
			from pgappforge.export.pdf_exporter import PDFExporter, REPORTLAB_AVAILABLE
			if not REPORTLAB_AVAILABLE:
				raise ImportError("reportlab not installed")

			# PDFExporter.export() expects List[Dict[str, Any]]
			col_keys = [h.lower().replace(" ", "_") for h in headers]
			data_dicts = [{col_keys[i]: cell for i, cell in enumerate(row)} for row in rows]

			exporter = PDFExporter()
			options = {
				"title": title,
				"page_size": "A4",
				"table_style": "professional",
				"alternate_row_colors": True,
				"page_numbers": True,
				"include_metadata": bool(metadata),
			}
			return exporter.export(
				data=data_dicts,
				filename=title.replace(" ", "_") + ".pdf",
				metadata=metadata,
				options=options,
			)

		except Exception as exc:
			log.debug("PDFExporter path failed (%s), trying direct reportlab", exc)

		# -- Strategy 2: direct reportlab ------------------------------------
		try:
			from reportlab.lib.pagesizes import A4
			from reportlab.lib import colors
			from reportlab.lib.styles import getSampleStyleSheet
			from reportlab.lib.units import inch
			from reportlab.platypus import (
				SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
			)

			buf = io.BytesIO()
			doc = SimpleDocTemplate(buf, pagesize=A4,
			                        topMargin=inch, bottomMargin=inch,
			                        leftMargin=inch, rightMargin=inch)
			styles = getSampleStyleSheet()
			elements = [Paragraph(title, styles["Title"]), Spacer(1, 0.25 * inch)]

			if metadata:
				for k, v in metadata.items():
					label = k.replace("_", " ").title()
					elements.append(Paragraph(f"<b>{label}:</b> {v}", styles["Normal"]))
				elements.append(Spacer(1, 0.2 * inch))

			table_data = [headers] + rows
			col_count = len(headers)
			usable_width = A4[0] - 2 * inch
			# Give first two columns more room; split rest equally
			if col_count >= 3:
				col_widths = [1.0 * inch, 2.2 * inch] + \
				             [(usable_width - 3.2 * inch) / (col_count - 2)] * (col_count - 2)
			else:
				col_widths = [usable_width / col_count] * col_count

			t = Table(table_data, colWidths=col_widths, repeatRows=1)
			t.setStyle(TableStyle([
				# Header row
				("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#1a56db")),
				("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
				("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
				# Body
				("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
				("FONTSIZE",     (0, 0), (-1, -1), 9),
				("ROWBACKGROUNDS", (0, 1), (-1, -1),
				 [colors.white, colors.HexColor("#f9fafb")]),
				# Grid
				("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
				("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
				("LEFTPADDING",  (0, 0), (-1, -1), 6),
				("RIGHTPADDING", (0, 0), (-1, -1), 6),
				("TOPPADDING",   (0, 0), (-1, -1), 4),
				("BOTTOMPADDING",(0, 0), (-1, -1), 4),
			]))
			elements.append(t)
			doc.build(elements)
			result = buf.getvalue()
			buf.close()
			return result

		except ImportError:
			log.warning("reportlab not available; PDF generation skipped for %r", title)
			return b""
		except Exception as exc:
			log.error("Direct reportlab render failed for %r: %s", title, exc)
			return b""


__all__ = ["FinancialReportService"]
