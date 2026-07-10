"""
pgappforge/plugins/erp/analytics/__init__.py

Analytics domain — executive dashboard plus four sub-plugins:
  operational  — KPIs, snapshots, saved queries, scheduled reports
  predictive   — ML models, predictions, anomaly detection
  cdp          — Customer Data Platform: unified profiles, identity graph, segments
  ai           — AI agents, conversations, messages, actions

Import the sub-plugin you need directly:
    from pgappforge.plugins.erp.analytics.operational import OperationalPlugin
    from pgappforge.plugins.erp.analytics.predictive import PredictivePlugin
    from pgappforge.plugins.erp.analytics.cdp import CDPPlugin
    from pgappforge.plugins.erp.analytics.ai import AIPlugin
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from flask import make_response, request

from pgappforge import BaseView, expose
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _to_decimal(value: object) -> Decimal:
	if value is None:
		return Decimal("0")
	try:
		return Decimal(str(value))
	except (InvalidOperation, ValueError, TypeError):
		return Decimal("0")


def _cents(value: object) -> int:
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


def _money(cents: object) -> str:
	amount = Decimal(_cents(cents)) / Decimal("100")
	sign = "-" if amount < 0 else ""
	return f"{sign}${abs(amount):,.2f}"


def _tenant_filter(model: Any, tenant_id: str | None) -> list[Any]:
	return [model.tenant_id == tenant_id] if tenant_id else []


def _period_bounds(raw_period: str | None) -> tuple[str, str, date, date]:
	labels = {
		"mtd": "Month to Date",
		"qtd": "Quarter to Date",
		"ytd": "Year to Date",
	}
	period = (raw_period or "mtd").lower()
	if period not in labels:
		period = "mtd"
	today = date.today()
	if period == "ytd":
		start = date(today.year, 1, 1)
	elif period == "qtd":
		quarter_month = ((today.month - 1) // 3) * 3 + 1
		start = date(today.year, quarter_month, 1)
	else:
		start = date(today.year, today.month, 1)
	return period, labels[period], start, today


def _prior_bounds(start: date, end: date) -> tuple[date, date]:
	days = (end - start).days + 1
	prior_end = start - timedelta(days=1)
	prior_start = prior_end - timedelta(days=days - 1)
	return prior_start, prior_end


def _ar_revenue(session: Any, tenant_id: str | None, start: date, end: date) -> int:
	try:
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice

		filters = [
			ARInvoice.invoice_date >= start,
			ARInvoice.invoice_date <= end,
			ARInvoice.status.notin_(["DRAFT", "CANCELLED", "VOID"]),
		]
		filters.extend(_tenant_filter(ARInvoice, tenant_id))
		value = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(ARInvoice.total_cents), 0)).where(*filters)
		).scalar_one()
		return _cents(value)
	except Exception as exc:
		log.debug("Executive dashboard revenue query failed: %s", exc)
		# TODO: Replace zero fallback with enterprise revenue service when available.
		return 0


def _ar_outstanding(session: Any, tenant_id: str | None, as_of: date) -> int:
	try:
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice

		filters = [
			ARInvoice.invoice_date <= as_of,
			ARInvoice.status.notin_(["PAID", "CANCELLED", "VOID", "WRITTEN_OFF"]),
		]
		filters.extend(_tenant_filter(ARInvoice, tenant_id))
		value = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(ARInvoice.balance_due_cents), 0)).where(*filters)
		).scalar_one()
		return max(_cents(value), 0)
	except Exception as exc:
		log.debug("Executive dashboard AR outstanding query failed: %s", exc)
		# TODO: Replace zero fallback with AR receivables KPI service when available.
		return 0


def _ap_outstanding(session: Any, tenant_id: str | None, as_of: date) -> int:
	try:
		from pgappforge.plugins.erp.finance.ap.models import APInvoice

		filters = [
			APInvoice.invoice_date <= as_of,
			APInvoice.status.notin_(["PAID", "CANCELLED", "VOID"]),
		]
		filters.extend(_tenant_filter(APInvoice, tenant_id))
		value = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(APInvoice.total_cents - APInvoice.paid_cents), 0)).where(*filters)
		).scalar_one()
		return max(_cents(value), 0)
	except Exception as exc:
		log.debug("Executive dashboard AP outstanding query failed: %s", exc)
		# TODO: Replace zero fallback with AP payables KPI service when available.
		return 0


def _ap_purchases(session: Any, tenant_id: str | None, start: date, end: date) -> int:
	try:
		from pgappforge.plugins.erp.finance.ap.models import APInvoice

		filters = [
			APInvoice.invoice_date >= start,
			APInvoice.invoice_date <= end,
			APInvoice.status.notin_(["CANCELLED", "VOID"]),
		]
		filters.extend(_tenant_filter(APInvoice, tenant_id))
		value = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(APInvoice.total_cents), 0)).where(*filters)
		).scalar_one()
		return _cents(value)
	except Exception as exc:
		log.debug("Executive dashboard purchases query failed: %s", exc)
		# TODO: Replace zero fallback with procurement spend service when available.
		return 0


def _gl_ebitda(session: Any, tenant_id: str | None, start: date, end: date) -> int:
	try:
		from pgappforge.plugins.erp.finance.gl.models import GLAccount, GLAccountBalance, GLPeriod

		filters = [
			GLPeriod.start_date <= end,
			GLPeriod.end_date >= start,
			GLAccount.account_type.in_(["REVENUE", "EXPENSE"]),
		]
		filters.extend(_tenant_filter(GLPeriod, tenant_id))
		filters.extend(_tenant_filter(GLAccountBalance, tenant_id))
		revenue_expr = sa.case(
			(GLAccount.account_type == "REVENUE", GLAccountBalance.period_credit - GLAccountBalance.period_debit),
			else_=0,
		)
		expense_expr = sa.case(
			(GLAccount.account_type == "EXPENSE", GLAccountBalance.period_debit - GLAccountBalance.period_credit),
			else_=0,
		)
		row = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(revenue_expr), 0),
				sa.func.coalesce(sa.func.sum(expense_expr), 0),
			)
			.select_from(GLAccountBalance)
			.join(GLAccount, GLAccount.account_code == GLAccountBalance.account_code)
			.join(GLPeriod, GLPeriod.id == GLAccountBalance.period_id)
			.where(*filters)
		).one()
		# TODO: Replace operating-profit approximation with explicit EBITDA account mapping.
		return _cents(row[0]) - _cents(row[1])
	except Exception as exc:
		log.debug("Executive dashboard EBITDA query failed: %s", exc)
		return 0


def _headcount(session: Any, tenant_id: str | None, as_of: date) -> int:
	if not tenant_id:
		# TODO: Replace zero fallback with tenant-aware context from the request/appbuilder session.
		return 0
	try:
		from pgappforge.plugins.erp.hcm.analytics.services import HrAnalyticsService

		payload = HrAnalyticsService.compute_headcount(tenant_id, as_of, session)
		return int(payload.get("total", 0))
	except Exception as exc:
		log.debug("Executive dashboard headcount query failed: %s", exc)
		# TODO: Replace zero fallback with HCM analytics dashboard service when available.
		return 0


def _open_orders(session: Any, tenant_id: str | None, as_of: date) -> int:
	try:
		from pgappforge.plugins.erp.crm.commerce.models import Order

		filters = [
			Order.created_at <= as_of,
			Order.status.in_(["CONFIRMED", "PROCESSING", "SHIPPED"]),
		]
		filters.extend(_tenant_filter(Order, tenant_id))
		value = session.execute(sa.select(sa.func.count(Order.id)).where(*filters)).scalar_one()
		return int(value or 0)
	except Exception as exc:
		log.debug("Executive dashboard open orders query failed: %s", exc)
		# TODO: Replace zero fallback with sales order backlog service when available.
		return 0


def _days(start: date, end: date) -> Decimal:
	return Decimal(max((end - start).days + 1, 1))


def _dso(session: Any, tenant_id: str | None, start: date, end: date) -> Decimal:
	revenue = _ar_revenue(session, tenant_id, start, end)
	if revenue <= 0:
		return Decimal("0.0")
	return (_to_decimal(_ar_outstanding(session, tenant_id, end)) / (_to_decimal(revenue) / _days(start, end))).quantize(Decimal("0.1"))


def _dpo(session: Any, tenant_id: str | None, start: date, end: date) -> Decimal:
	purchases = _ap_purchases(session, tenant_id, start, end)
	if purchases <= 0:
		return Decimal("0.0")
	return (_to_decimal(_ap_outstanding(session, tenant_id, end)) / (_to_decimal(purchases) / _days(start, end))).quantize(Decimal("0.1"))


def _metric(name: str, value: str, current: Decimal, prior: Decimal, good_when: str) -> dict[str, str]:
	trend = "up" if current >= prior else "down"
	favorable = current >= prior if good_when == "up" else current <= prior
	return {
		"name": name,
		"value": value,
		"trend": trend,
		"color": "#166534" if favorable else "#991b1b",
	}


def _exec_card(metric: dict[str, str]) -> str:
	return (
		f"<article class='exec-card' style='border-top-color:{metric['color']}'>"
		f"<h3>{_he(metric['name'])}</h3>"
		f"<p class='exec-value' style='color:{metric['color']}'>{_he(metric['value'])}</p>"
		f"<p class='exec-trend'>Trend: {_he(metric['trend'])}</p>"
		"</article>"
	)


class ExecutiveDashboardView(BaseView):
	"""Cross-domain executive dashboard."""

	route_base = "/analytics/executive"
	default_view = "index"

	@expose("/", methods=["GET"])
	@has_access
	def index(self):
		session = _get_session()
		period, label, start, end = _period_bounds(request.args.get("period", "mtd"))
		prior_start, prior_end = _prior_bounds(start, end)
		tenant_id = request.args.get("tenant_id") or None

		revenue = _ar_revenue(session, tenant_id, start, end)
		prior_revenue = _ar_revenue(session, tenant_id, prior_start, prior_end)
		ebitda = _gl_ebitda(session, tenant_id, start, end)
		prior_ebitda = _gl_ebitda(session, tenant_id, prior_start, prior_end)
		headcount = _headcount(session, tenant_id, end)
		prior_headcount = _headcount(session, tenant_id, prior_end)
		open_orders = _open_orders(session, tenant_id, end)
		prior_open_orders = _open_orders(session, tenant_id, prior_end)
		dso = _dso(session, tenant_id, start, end)
		prior_dso = _dso(session, tenant_id, prior_start, prior_end)
		dpo = _dpo(session, tenant_id, start, end)
		prior_dpo = _dpo(session, tenant_id, prior_start, prior_end)

		metrics = [
			_metric("Revenue", _money(revenue), _to_decimal(revenue), _to_decimal(prior_revenue), "up"),
			_metric("EBITDA", _money(ebitda), _to_decimal(ebitda), _to_decimal(prior_ebitda), "up"),
			_metric("Headcount", f"{headcount:,}", _to_decimal(headcount), _to_decimal(prior_headcount), "up"),
			_metric("Open Orders", f"{open_orders:,}", _to_decimal(open_orders), _to_decimal(prior_open_orders), "up"),
			_metric("DSO", f"{dso} days", dso, prior_dso, "down"),
			_metric("DPO", f"{dpo} days", dpo, prior_dpo, "down"),
		]
		cards = "".join(_exec_card(metric) for metric in metrics)
		options = "".join(
			f"<option value='{code}' {'selected' if period == code else ''}>{label_text}</option>"
			for code, label_text in {"mtd": "Month to Date", "qtd": "Quarter to Date", "ytd": "Year to Date"}.items()
		)
		html = (
			"<style>"
			".executive-dashboard{font-family:Arial,sans-serif;color:#1f2933;}"
			".executive-header{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin-bottom:16px;}"
			".executive-header h2{margin:0;font-size:24px;}"
			".executive-header p{margin:4px 0 0;color:#52606d;}"
			".period-selector{display:flex;gap:8px;align-items:center;}"
			".period-selector select,.period-selector button{border:1px solid #cbd2d9;border-radius:4px;padding:6px 8px;background:#fff;}"
			".period-selector button{background:#1f2933;color:#fff;}"
			".executive-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;}"
			".exec-card{border:1px solid #d9e2ec;border-top:4px solid;border-radius:8px;padding:14px;background:#fff;box-shadow:0 1px 2px rgba(15,23,42,.06);}"
			".exec-card h3{font-size:14px;margin:0 0 8px;color:#52606d;font-weight:600;}"
			".exec-value{font-size:26px;font-weight:700;margin:0 0 6px;}"
			".exec-trend{font-size:12px;color:#627d98;margin:0;}"
			"@media(max-width:800px){.executive-grid{grid-template-columns:1fr}.executive-header{display:block}.period-selector{margin-top:12px}}"
			"</style>"
			"<section class='executive-dashboard'>"
			"<div class='executive-header'>"
			f"<div><h2>Executive Dashboard</h2><p>{_he(label)}: {_he(start)} to {_he(end)}</p></div>"
			"<form method='get' class='period-selector'>"
			"<label for='period'>Period</label> "
			f"<select id='period' name='period'>{options}</select> "
			"<button type='submit'>Apply</button>"
			"</form>"
			"</div>"
			f"<div class='executive-grid'>{cards}</div>"
			"</section>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})


class AnalyticsPlugin(BasePlugin):
	"""Analytics root plugin with the cross-domain executive dashboard."""

	name = "analytics"
	domain = "analytics"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="analytics",
			version="1.0.0",
			description="Analytics executive dashboard and domain-level entry points.",
			author="PgAppForge Contributors",
			tags=["erp", "analytics", "executive-dashboard"],
			priority=PluginPriority.NORMAL,
			permissions=["can_analytics_executive"],
			safe_mode_compatible=True,
		)

	def register_views(self) -> None:
		category = self.config.get("ANALYTICS_MENU_CATEGORY", "Analytics")
		self.add_view(ExecutiveDashboardView, "Executive Dashboard", icon="fa-dashboard", category=category)
		log.info("AnalyticsPlugin: executive dashboard registered under category %r", category)

	def register_models(self) -> list:
		return []

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> AnalyticsPlugin:
	return AnalyticsPlugin(appbuilder, config=config or {})


__all__ = [
	"AnalyticsPlugin",
	"ExecutiveDashboardView",
	"create_plugin",
]
