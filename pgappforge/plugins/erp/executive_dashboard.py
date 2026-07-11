"""
pgappforge/plugins/erp/executive_dashboard.py

ERP executive home dashboard with cross-domain KPI fallbacks.
"""
from __future__ import annotations

import logging
from datetime import date
from html import escape
from typing import Any

import sqlalchemy as sa
from markupsafe import Markup

from pgappforge import expose
from pgappforge.security.decorators import has_access

try:
	from pgappforge.plugins.erp.base_view import BaseERPView
except ImportError:  # pragma: no cover - fallback for minimal FAB deployments
	from flask_appbuilder import BaseView as BaseERPView

log = logging.getLogger(__name__)

METRIC_KEYS = (
	"revenue_ytd_cents",
	"headcount",
	"open_po_count",
	"overdue_ar_cents",
	"active_projects",
	"open_risks",
)


def _empty_metrics() -> dict[str, int | None]:
	return {key: None for key in METRIC_KEYS}


def _to_int(value: Any) -> int:
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


def _format_count(value: int | None) -> str:
	if value is None:
		return "N/A"
	return f"{value:,}"


def _format_currency(value: int | None) -> str:
	if value is None:
		return "N/A"
	amount = value / 100
	return f"${amount:,.2f}"


class ExecutiveDashboardView(BaseERPView):
	"""ERP executive landing page with resilient cross-domain KPIs."""

	route_base = "/erp/executive"
	default_view = "index"
	template = "appbuilder/general/model/list.html"

	@expose("/")
	@has_access
	def index(self):
		"""Render the ERP executive dashboard."""
		try:
			session = self._session()
		except Exception as exc:
			log.debug("ExecutiveDashboardView.index: could not obtain session: %s", exc)
			session = None

		metrics = self._gather_metrics(session) if session is not None else _empty_metrics()
		content = self._render_executive_dashboard(metrics)
		widgets = {
			"search": lambda: Markup(""),
			"list": lambda: content,
		}
		return self.render_template(
			self.template,
			title="Executive Dashboard",
			widgets=widgets,
			content=content,
		)

	def _gather_metrics(self, session: Any) -> dict[str, int | None]:
		"""Gather dashboard KPIs, returning None for unavailable domains."""
		metrics = _empty_metrics()
		today = date.today()
		year_start = date(today.year, 1, 1)

		try:
			from pgappforge.plugins.erp.finance.gl.models import (
				GLAccount,
				GLJournalEntry,
				GLJournalLine,
			)
		except ImportError as exc:
			log.debug("Executive dashboard revenue import unavailable: %s", exc)
		else:
			try:
				value = session.execute(
					sa.select(sa.func.coalesce(sa.func.sum(GLJournalLine.credit_amount), 0))
					.select_from(GLJournalLine)
					.join(GLJournalEntry, GLJournalEntry.id == GLJournalLine.entry_id)
					.join(GLAccount, GLAccount.account_code == GLJournalLine.account_code)
					.where(
						GLAccount.account_type == "REVENUE",
						GLJournalEntry.status == "POSTED",
						GLJournalEntry.posting_date >= year_start,
						GLJournalEntry.posting_date <= today,
					)
				).scalar()
				metrics["revenue_ytd_cents"] = _to_int(value)
			except Exception as exc:
				log.debug("Executive dashboard revenue query failed: %s", exc)

		try:
			from pgappforge.plugins.erp.hcm.personnel.models import Employee
		except ImportError as exc:
			log.debug("Executive dashboard headcount import unavailable: %s", exc)
		else:
			try:
				status_col = getattr(Employee, "status", None) or Employee.employment_status
				value = session.execute(
					sa.select(sa.func.count(Employee.id)).where(sa.func.lower(status_col) == "active")
				).scalar()
				metrics["headcount"] = _to_int(value)
			except Exception as exc:
				log.debug("Executive dashboard headcount query failed: %s", exc)

		try:
			from pgappforge.plugins.erp.finance.ap.models import APPurchaseOrder as PurchaseOrder
		except ImportError as exc:
			log.debug("Executive dashboard PO import unavailable: %s", exc)
		else:
			try:
				value = session.execute(
					sa.select(sa.func.count(PurchaseOrder.id)).where(
						sa.func.upper(PurchaseOrder.status).in_(
							("APPROVED", "PARTIALLY_RECEIVED", "PARTIAL")
						)
					)
				).scalar()
				metrics["open_po_count"] = _to_int(value)
			except Exception as exc:
				log.debug("Executive dashboard PO query failed: %s", exc)

		try:
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice as Invoice
		except ImportError as exc:
			log.debug("Executive dashboard AR import unavailable: %s", exc)
		else:
			try:
				outstanding_col = getattr(Invoice, "outstanding_cents", None) or Invoice.balance_due_cents
				value = session.execute(
					sa.select(sa.func.coalesce(sa.func.sum(outstanding_col), 0)).where(
						Invoice.due_date < today,
						outstanding_col > 0,
					)
				).scalar()
				metrics["overdue_ar_cents"] = _to_int(value)
			except Exception as exc:
				log.debug("Executive dashboard overdue AR query failed: %s", exc)

		try:
			from pgappforge.plugins.erp.projects.models import Project
		except ImportError as exc:
			log.debug("Executive dashboard project import unavailable: %s", exc)
		else:
			try:
				value = session.execute(
					sa.select(sa.func.count(Project.id)).where(sa.func.lower(Project.status) == "active")
				).scalar()
				metrics["active_projects"] = _to_int(value)
			except Exception as exc:
				log.debug("Executive dashboard active projects query failed: %s", exc)

		try:
			from pgappforge.plugins.erp.grc.erm.models import RiskRegister
		except ImportError as exc:
			log.debug("Executive dashboard risk import unavailable: %s", exc)
		else:
			try:
				value = session.execute(
					sa.select(sa.func.count(RiskRegister.id)).where(
						sa.func.lower(RiskRegister.status) == "open"
					)
				).scalar()
				metrics["open_risks"] = _to_int(value)
			except Exception as exc:
				log.debug("Executive dashboard open risks query failed: %s", exc)

		return metrics

	def _render_executive_dashboard(self, metrics: dict[str, int | None]) -> Markup:
		"""Render the Bootstrap KPI card grid."""
		cards = [
			{
				"label": "Revenue YTD",
				"value": _format_currency(metrics.get("revenue_ytd_cents")),
				"icon": "fa-line-chart",
				"variant": "success",
			},
			{
				"label": "Headcount",
				"value": _format_count(metrics.get("headcount")),
				"icon": "fa-users",
				"variant": "info",
			},
			{
				"label": "Open POs",
				"value": _format_count(metrics.get("open_po_count")),
				"icon": "fa-shopping-cart",
				"variant": "warning",
			},
			{
				"label": "Overdue AR",
				"value": _format_currency(metrics.get("overdue_ar_cents")),
				"icon": "fa-exclamation-triangle",
				"variant": "danger",
			},
			{
				"label": "Active Projects",
				"value": _format_count(metrics.get("active_projects")),
				"icon": "fa-briefcase",
				"variant": "primary",
			},
			{
				"label": "Open Risks",
				"value": _format_count(metrics.get("open_risks")),
				"icon": "fa-shield",
				"variant": "danger",
			},
		]
		card_html = "".join(self._render_kpi_card(card) for card in cards)
		as_of = escape(date.today().isoformat())
		return Markup(
			"<style>"
			".erp-exec-dashboard{padding:1.5rem 0;color:#1f2937;}"
			".erp-exec-header{display:flex;justify-content:space-between;gap:1rem;align-items:flex-end;margin-bottom:1rem;}"
			".erp-exec-header h2{margin:0;font-size:1.75rem;font-weight:700;}"
			".erp-exec-header p{margin:.25rem 0 0;color:#6b7280;}"
			".erp-exec-kpi{border-radius:.5rem;box-shadow:0 .125rem .45rem rgba(17,24,39,.08);}"
			".erp-exec-kpi .card-body{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;min-height:8.25rem;}"
			".erp-exec-label{font-size:.78rem;letter-spacing:0;text-transform:uppercase;color:#6b7280;font-weight:700;}"
			".erp-exec-value{font-size:2rem;line-height:1.1;font-weight:800;color:#111827;margin-top:.4rem;}"
			".erp-exec-icon{font-size:1.55rem;opacity:.75;}"
			".border-left-success{border-left:.35rem solid #198754!important;}"
			".border-left-info{border-left:.35rem solid #0dcaf0!important;}"
			".border-left-warning{border-left:.35rem solid #ffc107!important;}"
			".border-left-danger{border-left:.35rem solid #dc3545!important;}"
			".border-left-primary{border-left:.35rem solid #0d6efd!important;}"
			"@media(max-width:767.98px){.erp-exec-header{display:block}.erp-exec-value{font-size:1.65rem}}"
			"</style>"
			"<section class='erp-exec-dashboard container-fluid'>"
			"<div class='erp-exec-header'>"
			"<div><h2>Executive Dashboard</h2><p>Cross-domain ERP pulse</p></div>"
			f"<div class='text-muted small'>As of {as_of}</div>"
			"</div>"
			"<div class='row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3'>"
			f"{card_html}"
			"</div>"
			"</section>"
		)

	def _render_kpi_card(self, card: dict[str, str]) -> str:
		variant = escape(card["variant"])
		label = escape(card["label"])
		value = escape(card["value"])
		icon = escape(card["icon"])
		muted = " text-muted" if value == "N/A" else ""
		return (
			"<div class='col mb-3'>"
			f"<div class='card erp-exec-kpi h-100 border-left-{variant} border-start border-{variant} border-4'>"
			"<div class='card-body'>"
			"<div>"
			f"<div class='erp-exec-label'>{label}</div>"
			f"<div class='erp-exec-value{muted}'>{value}</div>"
			"</div>"
			f"<i class='fa {icon} text-{variant} erp-exec-icon' aria-hidden='true'></i>"
			"</div>"
			"</div>"
			"</div>"
		)


__all__ = ["ExecutiveDashboardView"]
