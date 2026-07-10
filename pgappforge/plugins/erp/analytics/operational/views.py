"""
pgappforge/plugins/erp/analytics/operational/views.py

Flask views for the Operational Analytics plugin.

Route summary
-------------
KPIDefinitionView    /analytics/kpis/
KPISnapshotView      /analytics/kpi-snapshots/
AnalyticsQueryView   /analytics/queries/
AnalyticsReportView  /analytics/reports/
  ├─ /kpi_dashboard    — KPI dashboard (HTML: on-track/at-risk/off-track counts)
  ├─ /trend/<kpi_id>   — KPI trend sparkline data (JSON)
  └─ /run/<report_id>  — Generate and return report payload (JSON)
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
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


_PERIOD_LABELS = {
	"mtd": "Month to Date",
	"qtd": "Quarter to Date",
	"ytd": "Year to Date",
}


def _period_bounds(raw_period: str | None) -> tuple[str, str, date, date]:
	period = (raw_period or "mtd").lower()
	if period not in _PERIOD_LABELS:
		period = "mtd"
	today = date.today()
	if period == "ytd":
		start = date(today.year, 1, 1)
	elif period == "qtd":
		quarter_month = ((today.month - 1) // 3) * 3 + 1
		start = date(today.year, quarter_month, 1)
	else:
		start = date(today.year, today.month, 1)
	return period, _PERIOD_LABELS[period], start, today


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


def _percent(numerator: object, denominator: object) -> Decimal:
	den = _to_decimal(denominator)
	if den == 0:
		return Decimal("0")
	return (_to_decimal(numerator) / den * Decimal("100")).quantize(Decimal("0.1"))


def _ratio(numerator: object, denominator: object) -> Decimal:
	den = _to_decimal(denominator)
	if den == 0:
		return Decimal("0")
	return (_to_decimal(numerator) / den).quantize(Decimal("0.01"))


def _tenant_filter(model: Any, tenant_id: str | None) -> list[Any]:
	return [model.tenant_id == tenant_id] if tenant_id else []


def _period_selector(period: str) -> str:
	options = "".join(
		f"<option value='{_he(code)}' {'selected' if period == code else ''}>{_he(label)}</option>"
		for code, label in _PERIOD_LABELS.items()
	)
	return (
		"<form method='get' class='period-selector'>"
		"<label for='period'>Period</label> "
		f"<select id='period' name='period'>{options}</select> "
		"<button type='submit'>Apply</button>"
		"</form>"
	)


def _dashboard_style() -> str:
	return (
		"<style>"
		".analytics-dashboard{font-family:Arial,sans-serif;color:#1f2933;}"
		".dashboard-header{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin-bottom:16px;}"
		".dashboard-header h2{margin:0;font-size:24px;}"
		".dashboard-header p{margin:4px 0 0;color:#52606d;}"
		".period-selector{display:flex;gap:8px;align-items:center;}"
		".period-selector select,.period-selector button{border:1px solid #cbd2d9;border-radius:4px;padding:6px 8px;background:#fff;}"
		".period-selector button{background:#1f2933;color:#fff;}"
		".kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;}"
		".kpi-card{border:1px solid #d9e2ec;border-radius:8px;padding:14px;background:#fff;box-shadow:0 1px 2px rgba(15,23,42,.06);}"
		".kpi-card h3{font-size:14px;margin:0 0 8px;color:#52606d;font-weight:600;}"
		".kpi-value{font-size:24px;font-weight:700;margin:0 0 6px;color:#102a43;}"
		".kpi-detail{font-size:12px;line-height:1.4;color:#627d98;margin:0;}"
		".bar-table{width:100%;border-collapse:collapse;margin-top:18px;}"
		".bar-table th,.bar-table td{padding:8px;border-bottom:1px solid #d9e2ec;text-align:left;vertical-align:middle;}"
		".bar-shell{height:18px;background:#edf2f7;border-radius:4px;overflow:hidden;min-width:160px;}"
		".bar-fill{height:18px;background:#2f855a;}"
		".bar-note{font-size:12px;color:#627d98;}"
		"</style>"
	)


def _kpi_card(title: str, value: str, detail: str) -> str:
	return (
		"<article class='kpi-card'>"
		f"<h3>{_he(title)}</h3>"
		f"<p class='kpi-value'>{_he(value)}</p>"
		f"<p class='kpi-detail'>{_he(detail)}</p>"
		"</article>"
	)


def _finance_revenue_vs_budget(session: Any, tenant_id: str | None, start: date, end: date) -> dict[str, Any]:
	try:
		from pgappforge.plugins.erp.finance.fpa.models import ForecastSnapshot
		from pgappforge.plugins.erp.finance.gl.models import GLAccount

		month_start = date(start.year, start.month, 1)
		filters = [
			ForecastSnapshot.period_month >= month_start,
			ForecastSnapshot.period_month <= end,
		]
		filters.extend(_tenant_filter(ForecastSnapshot, tenant_id))
		gl_filters = [GLAccount.account_type == "REVENUE"]
		gl_filters.extend(_tenant_filter(GLAccount, tenant_id))
		row = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(ForecastSnapshot.actual_cents), 0),
				sa.func.coalesce(sa.func.sum(ForecastSnapshot.budget_cents), 0),
			)
			.select_from(ForecastSnapshot)
			.join(GLAccount, GLAccount.account_code == ForecastSnapshot.gl_account_code)
			.where(*filters, *gl_filters)
		).one()
		actual = _cents(row[0])
		budget = _cents(row[1])
	except Exception as exc:
		log.debug("Financial dashboard revenue/budget query failed: %s", exc)
		# TODO: Replace zero fallback with dedicated FP&A revenue KPI once exposed.
		actual = 0
		budget = 0
	variance = actual - budget
	return {
		"actual": actual,
		"budget": budget,
		"variance": variance,
		"variance_pct": _percent(variance, budget),
	}


def _finance_cash_position(session: Any, tenant_id: str | None, end: date) -> int:
	try:
		from pgappforge.plugins.erp.finance.gl.models import GLAccount, GLAccountBalance, GLPeriod

		period_filters = [GLPeriod.end_date <= end]
		period_filters.extend(_tenant_filter(GLPeriod, tenant_id))
		period_id = session.execute(
			sa.select(GLPeriod.id)
			.where(*period_filters)
			.order_by(GLPeriod.end_date.desc())
			.limit(1)
		).scalar_one_or_none()
		if not period_id:
			return 0
		filters = [
			GLAccountBalance.period_id == period_id,
			GLAccount.account_type == "ASSET",
			sa.or_(
				GLAccount.account_name.ilike("%cash%"),
				GLAccount.account_subtype.ilike("%cash%"),
				GLAccount.ifrs_concept.ilike("%cash%"),
			),
		]
		filters.extend(_tenant_filter(GLAccountBalance, tenant_id))
		row = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(GLAccountBalance.closing_debit - GLAccountBalance.closing_credit), 0))
			.select_from(GLAccountBalance)
			.join(GLAccount, GLAccount.account_code == GLAccountBalance.account_code)
			.where(*filters)
		).scalar_one()
		return _cents(row)
	except Exception as exc:
		log.debug("Financial dashboard cash position query failed: %s", exc)
		# TODO: Replace zero fallback with treasury cash balance service when available.
		return 0


def _finance_ar_aging(session: Any, tenant_id: str | None, end: date) -> dict[str, int]:
	empty = {
		"current": 0,
		"1-30": 0,
		"31-60": 0,
		"61-90": 0,
		"91-120": 0,
		"120+": 0,
		"total": 0,
	}
	try:
		from pgappforge.plugins.erp.finance.ar.models import ARAging

		filters = [ARAging.snapshot_date <= end]
		filters.extend(_tenant_filter(ARAging, tenant_id))
		latest = session.execute(
			sa.select(sa.func.max(ARAging.snapshot_date)).where(*filters)
		).scalar_one_or_none()
		if latest is None:
			return empty
		row = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(ARAging.current_cents), 0),
				sa.func.coalesce(sa.func.sum(ARAging.days_1_30), 0),
				sa.func.coalesce(sa.func.sum(ARAging.days_31_60), 0),
				sa.func.coalesce(sa.func.sum(ARAging.days_61_90), 0),
				sa.func.coalesce(sa.func.sum(ARAging.days_91_120), 0),
				sa.func.coalesce(sa.func.sum(ARAging.over_120), 0),
				sa.func.coalesce(sa.func.sum(ARAging.total_outstanding_cents), 0),
			).where(*filters, ARAging.snapshot_date == latest)
		).one()
		return {
			"current": _cents(row[0]),
			"1-30": _cents(row[1]),
			"31-60": _cents(row[2]),
			"61-90": _cents(row[3]),
			"91-120": _cents(row[4]),
			"120+": _cents(row[5]),
			"total": _cents(row[6]),
		}
	except Exception as exc:
		log.debug("Financial dashboard AR aging query failed: %s", exc)
		# TODO: Replace zero fallback with AR aging service when available.
		return empty


def _finance_ap_outstanding(session: Any, tenant_id: str | None) -> int:
	try:
		from pgappforge.plugins.erp.finance.ap.models import APInvoice

		filters = [APInvoice.status.notin_(["PAID", "CANCELLED", "VOID"])]
		filters.extend(_tenant_filter(APInvoice, tenant_id))
		value = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(APInvoice.total_cents - APInvoice.paid_cents), 0))
			.where(*filters)
		).scalar_one()
		return max(_cents(value), 0)
	except Exception as exc:
		log.debug("Financial dashboard AP outstanding query failed: %s", exc)
		# TODO: Replace zero fallback with AP liability service when available.
		return 0


def _finance_open_purchase_commitments(session: Any, tenant_id: str | None) -> int:
	try:
		from pgappforge.plugins.erp.finance.ap.models import APPurchaseOrder

		filters = [APPurchaseOrder.status.in_(["APPROVED", "SENT", "PARTIAL", "RECEIVED"])]
		filters.extend(_tenant_filter(APPurchaseOrder, tenant_id))
		value = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(APPurchaseOrder.total_cents - APPurchaseOrder.invoiced_cents), 0))
			.where(*filters)
		).scalar_one()
		return max(_cents(value), 0)
	except Exception as exc:
		log.debug("Financial dashboard purchase commitment query failed: %s", exc)
		# TODO: Replace zero fallback with procurement commitments service when available.
		return 0


def _production_efficiency(session: Any, tenant_id: str | None, start: date, end: date) -> dict[str, Any]:
	try:
		from pgappforge.plugins.erp.operations.capacity_scheduling.models import CapacityLoad

		filters = [CapacityLoad.load_date >= start, CapacityLoad.load_date <= end]
		filters.extend(_tenant_filter(CapacityLoad, tenant_id))
		row = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(CapacityLoad.loaded_hours), 0),
				sa.func.coalesce(sa.func.sum(CapacityLoad.available_hours), 0),
			).where(*filters)
		).one()
		actual_hours = _to_decimal(row[0])
		planned_hours = _to_decimal(row[1])
	except Exception as exc:
		log.debug("Operational dashboard production efficiency query failed: %s", exc)
		# TODO: Replace loaded hours fallback with production execution actual hours when exposed.
		actual_hours = Decimal("0")
		planned_hours = Decimal("0")
	return {
		"actual_hours": actual_hours,
		"planned_hours": planned_hours,
		"rate": _percent(actual_hours, planned_hours),
	}


def _inventory_turnover(session: Any, tenant_id: str | None, start: date, end: date) -> dict[str, Any]:
	try:
		from pgappforge.plugins.erp.finance.material_ledger.models import CostingPeriod, MaterialLedger

		filters = [
			CostingPeriod.period_start <= end,
			CostingPeriod.period_end >= start,
		]
		filters.extend(_tenant_filter(MaterialLedger, tenant_id))
		row = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(MaterialLedger.issues_value_cents), 0),
				sa.func.coalesce(sa.func.sum(MaterialLedger.opening_value_cents), 0),
				sa.func.coalesce(sa.func.sum(MaterialLedger.closing_value_cents), 0),
			)
			.select_from(MaterialLedger)
			.join(CostingPeriod, CostingPeriod.id == MaterialLedger.period_id)
			.where(*filters)
		).one()
		issues = _cents(row[0])
		average_inventory = (_cents(row[1]) + _cents(row[2])) / 2
	except Exception as exc:
		log.debug("Operational dashboard inventory turnover query failed: %s", exc)
		# TODO: Replace zero fallback with material ledger turnover service when available.
		issues = 0
		average_inventory = 0
	return {
		"issues_cents": issues,
		"average_inventory_cents": int(average_inventory),
		"turnover": _ratio(issues, average_inventory),
	}


def _on_time_delivery(session: Any, tenant_id: str | None, start: date, end: date) -> dict[str, Any]:
	try:
		from pgappforge.plugins.erp.operations.transport.models import Shipment

		filters = [
			Shipment.status == "DELIVERED",
			Shipment.planned_delivery_date >= start,
			Shipment.planned_delivery_date <= end,
		]
		filters.extend(_tenant_filter(Shipment, tenant_id))
		rows = session.execute(
			sa.select(Shipment.planned_delivery_date, Shipment.actual_delivery_at).where(*filters)
		).all()
		total = len(rows)
		on_time = 0
		for planned_date, actual_at in rows:
			if actual_at is not None and actual_at.date() <= planned_date:
				on_time += 1
	except Exception as exc:
		log.debug("Operational dashboard on-time delivery query failed: %s", exc)
		# TODO: Replace zero fallback with logistics delivery performance service when available.
		total = 0
		on_time = 0
	return {
		"on_time": on_time,
		"total": total,
		"rate": _percent(on_time, total),
	}


def _warehouse_utilization(session: Any, tenant_id: str | None) -> dict[str, Any]:
	try:
		from pgappforge.plugins.erp.operations.warehouse.models import StorageLocation

		filters = [StorageLocation.is_active.is_(True)]
		filters.extend(_tenant_filter(StorageLocation, tenant_id))
		row = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(StorageLocation.current_units), 0),
				sa.func.coalesce(sa.func.sum(StorageLocation.capacity_units), 0),
			).where(*filters)
		).one()
		current_units = _to_decimal(row[0])
		capacity_units = _to_decimal(row[1])
	except Exception as exc:
		log.debug("Operational dashboard warehouse utilization query failed: %s", exc)
		# TODO: Replace zero fallback with warehouse capacity service when available.
		current_units = Decimal("0")
		capacity_units = Decimal("0")
	return {
		"current_units": current_units,
		"capacity_units": capacity_units,
		"rate": _percent(current_units, capacity_units),
	}


def _bar_row(label: str, value: Decimal, display: str, note: str) -> str:
	width = max(Decimal("0"), min(_to_decimal(value), Decimal("100")))
	return (
		"<tr>"
		f"<th>{_he(label)}</th>"
		"<td><div class='bar-shell'>"
		f"<div class='bar-fill' style='width:{width}%;'></div>"
		"</div></td>"
		f"<td>{_he(display)}<br><span class='bar-note'>{_he(note)}</span></td>"
		"</tr>"
	)


# ---------------------------------------------------------------------------
# FinancialAnalyticsDashboardView
# ---------------------------------------------------------------------------

class FinancialAnalyticsDashboardView(BaseView):
	"""Cross-finance dashboard for FP&A, GL, AR, AP, and purchase commitments."""

	route_base = "/analytics/financial-dashboard"
	default_view = "index"

	@expose("/", methods=["GET"])
	@has_access
	def index(self):
		session = _get_session()
		period, label, start, end = _period_bounds(request.args.get("period", "mtd"))
		tenant_id = request.args.get("tenant_id") or None
		revenue = _finance_revenue_vs_budget(session, tenant_id, start, end)
		cash_position = _finance_cash_position(session, tenant_id, end)
		ar_aging = _finance_ar_aging(session, tenant_id, end)
		ap_outstanding = _finance_ap_outstanding(session, tenant_id)
		purchase_commitments = _finance_open_purchase_commitments(session, tenant_id)

		ar_detail = (
			f"Current {_money(ar_aging['current'])}; 1-30 {_money(ar_aging['1-30'])}; "
			f"31-60 {_money(ar_aging['31-60'])}; 61-90 {_money(ar_aging['61-90'])}; "
			f"91-120 {_money(ar_aging['91-120'])}; 120+ {_money(ar_aging['120+'])}"
		)
		cards = "".join([
			_kpi_card(
				"Revenue vs Budget",
				_money(revenue["actual"]),
				f"Budget {_money(revenue['budget'])}; variance {_money(revenue['variance'])} ({revenue['variance_pct']}%)",
			),
			_kpi_card("Cash Position", _money(cash_position), "Latest GL cash-like asset balance"),
			_kpi_card("AR Aging Buckets", _money(ar_aging["total"]), ar_detail),
			_kpi_card("AP Outstanding", _money(ap_outstanding), "Open AP invoice balance"),
			_kpi_card("Open Purchase Commitments", _money(purchase_commitments), "Approved or partially fulfilled purchase orders"),
		])
		html = (
			_dashboard_style()
			+ "<section class='analytics-dashboard'>"
			"<div class='dashboard-header'>"
			f"<div><h2>Financial Analytics Dashboard</h2><p>{_he(label)}: {_he(start)} to {_he(end)}</p></div>"
			f"{_period_selector(period)}"
			"</div>"
			f"<div class='kpi-grid'>{cards}</div>"
			"</section>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})


# ---------------------------------------------------------------------------
# OperationalDashboardView
# ---------------------------------------------------------------------------

class OperationalDashboardView(BaseView):
	"""Operational dashboard for production, inventory, logistics, and warehouse KPIs."""

	route_base = "/analytics/operational-dashboard"
	default_view = "index"

	@expose("/", methods=["GET"])
	@has_access
	def index(self):
		session = _get_session()
		period, label, start, end = _period_bounds(request.args.get("period", "mtd"))
		tenant_id = request.args.get("tenant_id") or None
		production = _production_efficiency(session, tenant_id, start, end)
		inventory = _inventory_turnover(session, tenant_id, start, end)
		delivery = _on_time_delivery(session, tenant_id, start, end)
		warehouse = _warehouse_utilization(session, tenant_id)

		cards = "".join([
			_kpi_card(
				"Production Efficiency",
				f"{production['rate']}%",
				f"Actual {production['actual_hours']}h vs planned {production['planned_hours']}h",
			),
			_kpi_card(
				"Inventory Turnover",
				f"{inventory['turnover']}x",
				f"Issues {_money(inventory['issues_cents'])}; average inventory {_money(inventory['average_inventory_cents'])}",
			),
			_kpi_card(
				"On-time Delivery Rate",
				f"{delivery['rate']}%",
				f"{delivery['on_time']} of {delivery['total']} delivered shipments met planned delivery date",
			),
			_kpi_card(
				"Warehouse Utilization",
				f"{warehouse['rate']}%",
				f"{warehouse['current_units']} units used of {warehouse['capacity_units']} capacity",
			),
		])
		turnover_bar = min(inventory["turnover"] * Decimal("20"), Decimal("100"))
		rows = "".join([
			_bar_row("Production Efficiency", production["rate"], f"{production['rate']}%", "Actual vs planned hours"),
			_bar_row("Inventory Turnover", turnover_bar, f"{inventory['turnover']}x", "Scaled at 5x = 100%"),
			_bar_row("On-time Delivery", delivery["rate"], f"{delivery['rate']}%", "Delivered on or before plan"),
			_bar_row("Warehouse Utilization", warehouse["rate"], f"{warehouse['rate']}%", "Used capacity"),
		])
		html = (
			_dashboard_style()
			+ "<section class='analytics-dashboard'>"
			"<div class='dashboard-header'>"
			f"<div><h2>Operational Analytics Dashboard</h2><p>{_he(label)}: {_he(start)} to {_he(end)}</p></div>"
			f"{_period_selector(period)}"
			"</div>"
			f"<div class='kpi-grid'>{cards}</div>"
			"<table class='bar-table'><thead><tr><th>Metric</th><th>Bar</th><th>Value</th></tr></thead>"
			f"<tbody>{rows}</tbody></table>"
			"</section>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})


# ---------------------------------------------------------------------------
# KPIDefinitionView
# ---------------------------------------------------------------------------

class KPIDefinitionView(BaseView):
	"""KPI Definition CRUD.

	GET  /analytics/kpis/         — list (HTML)
	GET  /analytics/kpis/<id>     — detail (JSON)
	POST /analytics/kpis/         — create (JSON)
	PUT  /analytics/kpis/<id>     — update (JSON)
	"""

	route_base = "/analytics/kpis"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition
		rows = session.execute(
			sa.select(KPIDefinition).order_by(KPIDefinition.domain, KPIDefinition.kpi_code)
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.kpi_code)}</td><td>{_he(r.kpi_name)}</td>"
			f"<td>{_he(r.domain)}</td><td>{_he(r.frequency)}</td>"
			f"<td>{_he(r.target_direction)}</td><td>{'Active' if r.is_active else 'Inactive'}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>KPI Definitions</h2>"
			"<table><thead><tr><th>Code</th><th>Name</th><th>Domain</th>"
			"<th>Frequency</th><th>Direction</th><th>Status</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/<string:kpi_id>", methods=["GET"])
	@has_access
	def detail(self, kpi_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition
		row = session.execute(
			sa.select(KPIDefinition).where(KPIDefinition.id == kpi_id)
		).scalar_one_or_none()
		if row is None:
			abort(404)
		return jsonify({
			"id": row.id,
			"kpi_code": row.kpi_code,
			"kpi_name": row.kpi_name,
			"domain": row.domain,
			"formula": row.formula,
			"unit": row.unit,
			"frequency": row.frequency,
			"target_value": str(row.target_value) if row.target_value is not None else None,
			"target_direction": row.target_direction,
			"tags": row.tags or [],
			"is_active": row.is_active,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition
		kpi = KPIDefinition(
			tenant_id=data["tenant_id"],
			kpi_code=data["kpi_code"],
			kpi_name=data["kpi_name"],
			domain=data["domain"],
			formula=data.get("formula"),
			unit=data.get("unit"),
			frequency=data.get("frequency", "MONTHLY"),
			target_value=data.get("target_value"),
			target_direction=data.get("target_direction", "HIGHER"),
			owner_id=data.get("owner_id"),
			tags=data.get("tags", []),
			is_active=data.get("is_active", True),
		)
		session.add(kpi)
		session.commit()
		return jsonify({"id": kpi.id, "kpi_code": kpi.kpi_code}), 201


# ---------------------------------------------------------------------------
# KPISnapshotView
# ---------------------------------------------------------------------------

class KPISnapshotView(BaseView):
	"""KPI Snapshot management.

	GET  /analytics/kpi-snapshots/                    — list (HTML)
	POST /analytics/kpi-snapshots/                    — record new snapshot (JSON)
	GET  /analytics/kpi-snapshots/trend/<kpi_id>      — trend data (JSON)
	"""

	route_base = "/analytics/kpi-snapshots"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition, KPISnapshot
		rows = session.execute(
			sa.select(KPISnapshot, KPIDefinition.kpi_code)
			.join(KPIDefinition, KPIDefinition.id == KPISnapshot.kpi_id)
			.order_by(KPISnapshot.snapshot_date.desc())
			.limit(200)
		).all()
		items = [
			f"<tr><td>{_he(code)}</td><td>{_he(s.snapshot_date)}</td>"
			f"<td>{_he(s.actual_value)}</td><td>{_he(s.target_value or '—')}</td>"
			f"<td>{_he(s.variance_pct or '—')}%</td>"
			f"<td><span class='badge badge-{'success' if s.status == 'ON_TRACK' else 'warning' if s.status == 'AT_RISK' else 'danger'}'>"
			f"{_he(s.status)}</span></td></tr>"
			for s, code in rows
		]
		html = (
			"<h2>KPI Snapshots</h2>"
			"<table><thead><tr><th>KPI</th><th>Date</th><th>Actual</th>"
			"<th>Target</th><th>Variance</th><th>Status</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/", methods=["POST"])
	@has_access
	def record(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from datetime import date
		from pgappforge.plugins.erp.analytics.operational.services import OperationalAnalyticsService
		snap = OperationalAnalyticsService.record_snapshot(
			kpi_id=data["kpi_id"],
			snapshot_date=date.fromisoformat(data["snapshot_date"]),
			actual_value=Decimal(str(data["actual_value"])),
			session=session,
			target_override=Decimal(str(data["target_value"])) if data.get("target_value") else None,
		)
		session.commit()
		return jsonify({"id": snap.id, "status": snap.status}), 201

	@expose("/trend/<string:kpi_id>", methods=["GET"])
	@has_access
	def trend(self, kpi_id: str):
		session = _get_session()
		periods = min(int(request.args.get("periods", 12)), 52)
		from pgappforge.plugins.erp.analytics.operational.services import OperationalAnalyticsService
		snaps = OperationalAnalyticsService.get_kpi_trend(kpi_id, periods, session)
		return jsonify([
			{
				"date": str(s.snapshot_date),
				"actual": str(s.actual_value),
				"target": str(s.target_value) if s.target_value else None,
				"variance_pct": str(s.variance_pct) if s.variance_pct else None,
				"status": s.status,
			}
			for s in snaps
		])


# ---------------------------------------------------------------------------
# AnalyticsQueryView
# ---------------------------------------------------------------------------

class AnalyticsQueryView(BaseView):
	"""Saved Query management.

	GET  /analytics/queries/          — list
	POST /analytics/queries/          — create
	POST /analytics/queries/<id>/run  — execute with params (JSON)
	"""

	route_base = "/analytics/queries"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import AnalyticsQuery
		rows = session.execute(
			sa.select(AnalyticsQuery).order_by(AnalyticsQuery.name)
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.name)}</td><td>{'Public' if r.is_public else 'Private'}</td>"
			f"<td>{_he(r.last_run_at or 'Never')}</td>"
			f"<td>{_he(r.average_runtime_ms or '—')} ms</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Saved Queries</h2>"
			"<table><thead><tr><th>Name</th><th>Visibility</th>"
			"<th>Last Run</th><th>Avg Runtime</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/<string:query_id>/run", methods=["POST"])
	@has_access
	def run(self, query_id: str):
		session = _get_session()
		params = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.operational.services import (
			OperationalAnalyticsService,
			QueryExecutionError,
		)
		try:
			result = OperationalAnalyticsService.run_query(query_id, params, session)
			session.commit()
			return jsonify(result)
		except QueryExecutionError as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# AnalyticsReportView  (report catalogue + 3 built-in report templates)
# ---------------------------------------------------------------------------

class AnalyticsReportView(BaseView):
	"""Analytics Report definitions and generation.

	GET  /analytics/reports/                        — report catalogue (HTML)
	GET  /analytics/reports/kpi_dashboard           — KPI dashboard (HTML)
	GET  /analytics/reports/kpi_status_summary      — ON_TRACK/AT_RISK/OFF_TRACK counts (JSON)
	POST /analytics/reports/<id>/generate           — generate report (JSON)
	"""

	route_base = "/analytics/reports"
	default_view = "catalogue"

	@expose("/", methods=["GET"])
	@has_access
	def catalogue(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import AnalyticsReport
		rows = session.execute(
			sa.select(AnalyticsReport).order_by(AnalyticsReport.category, AnalyticsReport.name)
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.name)}</td><td>{_he(r.category)}</td>"
			f"<td>{'Scheduled' if r.is_scheduled else 'On-demand'}</td>"
			f"<td>{_he(r.last_generated_at or 'Never')}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Analytics Reports</h2>"
			"<table><thead><tr><th>Name</th><th>Category</th>"
			"<th>Schedule</th><th>Last Generated</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/kpi_dashboard", methods=["GET"])
	@has_access
	def kpi_dashboard(self):
		"""HTML KPI dashboard: latest snapshot per KPI with status badges."""
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition, KPISnapshot

		# Latest snapshot per KPI via subquery
		subq = (
			sa.select(
				KPISnapshot.kpi_id,
				sa.func.max(KPISnapshot.snapshot_date).label("max_date"),
			)
			.group_by(KPISnapshot.kpi_id)
			.subquery()
		)
		rows = session.execute(
			sa.select(KPISnapshot, KPIDefinition.kpi_code, KPIDefinition.kpi_name, KPIDefinition.domain)
			.join(KPIDefinition, KPIDefinition.id == KPISnapshot.kpi_id)
			.join(subq, sa.and_(
				subq.c.kpi_id == KPISnapshot.kpi_id,
				subq.c.max_date == KPISnapshot.snapshot_date,
			))
			.order_by(KPIDefinition.domain, KPIDefinition.kpi_code)
		).all()

		on_track = sum(1 for s, *_ in rows if s.status == "ON_TRACK")
		at_risk = sum(1 for s, *_ in rows if s.status == "AT_RISK")
		off_track = sum(1 for s, *_ in rows if s.status == "OFF_TRACK")

		cards = "".join(
			f"<div class='kpi-card status-{s.status.lower()}'>"
			f"<h4>{_he(name)}</h4><p class='domain'>{_he(domain)}</p>"
			f"<p class='actual'>{_he(s.actual_value)}</p>"
			f"<p class='variance'>{_he(s.variance_pct or '—')}%</p>"
			f"<span class='badge'>{_he(s.status)}</span></div>"
			for s, code, name, domain in rows
		)
		summary = (
			f"<div class='summary'>"
			f"<span class='on-track'>&#10003; {on_track} On Track</span> "
			f"<span class='at-risk'>&#9888; {at_risk} At Risk</span> "
			f"<span class='off-track'>&#10007; {off_track} Off Track</span>"
			f"</div>"
		)
		html = f"<h2>KPI Dashboard</h2>{summary}<div class='kpi-grid'>{cards}</div>"
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/kpi_status_summary", methods=["GET"])
	@has_access
	def kpi_status_summary(self):
		"""JSON: count of KPIs by status (latest snapshot per KPI)."""
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPISnapshot

		subq = (
			sa.select(
				KPISnapshot.kpi_id,
				sa.func.max(KPISnapshot.snapshot_date).label("max_date"),
			)
			.group_by(KPISnapshot.kpi_id)
			.subquery()
		)
		rows = session.execute(
			sa.select(KPISnapshot.status, sa.func.count().label("cnt"))
			.join(subq, sa.and_(
				subq.c.kpi_id == KPISnapshot.kpi_id,
				subq.c.max_date == KPISnapshot.snapshot_date,
			))
			.group_by(KPISnapshot.status)
		).all()

		return jsonify({row.status: row.cnt for row in rows})

	@expose("/<string:report_id>/generate", methods=["POST"])
	@has_access
	def generate(self, report_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.services import (
			OperationalAnalyticsService,
			ReportNotFoundError,
		)
		try:
			payload = OperationalAnalyticsService.generate_report(report_id, session)
			session.commit()
			return jsonify(payload)
		except ReportNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404


__all__ = [
	"FinancialAnalyticsDashboardView",
	"OperationalDashboardView",
	"KPIDefinitionView",
	"KPISnapshotView",
	"AnalyticsQueryView",
	"AnalyticsReportView",
]
