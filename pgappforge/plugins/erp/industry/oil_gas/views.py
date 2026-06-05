"""
pgappforge/plugins/erp/industry/oil_gas/views.py

Flask views for the Oil & Gas plugin.

Views:
  FacilityView          — CRUD + facility dashboard (OEE, production summary)
  AssetView             — CRUD + criticality assessment action
  MaintenanceWorkView   — CRUD + approve/complete workflow actions
  ProductionRecordView  — CRUD + production trend chart
  HAZOPReviewView       — CRUD
  IncidentReportView    — CRUD + HSE KPI dashboard
  OilGasDashboardView   — Read-only consolidated O&G overview
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	currency_widget,
	date_widget,
	datetime_widget,
	json_widget,
	map_widget,
	select2_widget,
	chart_widget,
	date_range_widget,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session / service helpers
# ---------------------------------------------------------------------------

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
	raise RuntimeError("Cannot obtain DB session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.oil_gas.services import OilGasService
	return OilGasService()


# ---------------------------------------------------------------------------
# FacilityView
# ---------------------------------------------------------------------------

class FacilityView(BaseView):
	"""CRUD + OEE dashboard for Facilities.

	Widgets: map_widget for location, select2 for facility_type / status.
	"""

	route_base = "/oil-gas/facilities"
	default_view = "list"

	# Widget hints (consumed by FAB template machinery)
	field_widgets = {
		"location": map_widget(zoom=8),
		"facility_type": select2_widget(
			["UPSTREAM", "MIDSTREAM", "DOWNSTREAM", "REFINERY", "LNG"]
		),
		"status": select2_widget(
			["ACTIVE", "MAINTENANCE", "SHUTDOWN", "DECOMMISSIONED"]
		),
		"commissioning_date": date_widget(),
	}
	label_columns = {
		"facility_code": "Facility Code",
		"facility_type": "Type",
		"country_code": "Country",
		"design_capacity": "Design Capacity",
		"capacity_unit": "Unit",
		"commissioning_date": "Commissioned",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.oil_gas.models import Facility
		session = _get_session()
		rows = session.execute(
			sa.select(Facility).order_by(Facility.facility_code)
		).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"facility_code": r.facility_code,
				"name": r.name,
				"facility_type": r.facility_type,
				"country_code": r.country_code,
				"status": r.status,
				"commissioning_date": r.commissioning_date.isoformat() if r.commissioning_date else None,
			}
			for r in rows
		])

	@expose("/<facility_id>/oee")
	@has_access
	def oee_dashboard(self, facility_id: str):
		"""Return OEE metrics for a facility (last 30 days)."""
		period = int(request.args.get("period_days", 30))
		try:
			result = _svc().calculate_oee(facility_id, _get_session(), period_days=period)
			return jsonify(result)
		except Exception as exc:
			log.warning("oee_dashboard error: %s", exc)
			abort(400, str(exc))

	@expose("/<facility_id>/hse-kpis")
	@has_access
	def hse_kpis(self, facility_id: str):
		"""Return HSE KPIs for a facility."""
		period = int(request.args.get("period_days", 365))
		try:
			result = _svc().calculate_hse_kpis(facility_id, _get_session(), period_days=period)
			return jsonify(result)
		except Exception as exc:
			log.warning("hse_kpis error: %s", exc)
			abort(400, str(exc))

	@expose("/<facility_id>/maintenance-backlog")
	@has_access
	def maintenance_backlog(self, facility_id: str):
		"""Return open maintenance backlog for a facility."""
		try:
			result = _svc().generate_maintenance_backlog(facility_id, _get_session())
			return jsonify(result)
		except Exception as exc:
			log.warning("maintenance_backlog error: %s", exc)
			abort(400, str(exc))


# ---------------------------------------------------------------------------
# AssetView
# ---------------------------------------------------------------------------

class AssetView(BaseView):
	"""CRUD + criticality assessment for Assets.

	Widgets: select2 for asset_class, criticality, status.
	"""

	route_base = "/oil-gas/assets"
	default_view = "list"

	field_widgets = {
		"installation_date": date_widget(),
		"criticality": select2_widget(["A", "B", "C"]),
		"status": select2_widget(
			["OPERATIONAL", "STANDBY", "MAINTENANCE", "FAILED", "DECOMMISSIONED"]
		),
	}
	label_columns = {
		"tag_number": "Tag Number",
		"asset_class": "Asset Class",
		"design_pressure_bar": "Design Pressure (bar)",
		"design_temperature_c": "Design Temp (°C)",
		"criticality": "Criticality",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.oil_gas.models import Asset
		session = _get_session()
		rows = session.execute(
			sa.select(Asset).order_by(Asset.tag_number)
		).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"tag_number": r.tag_number,
				"facility_id": str(r.facility_id),
				"asset_class": r.asset_class,
				"criticality": r.criticality,
				"status": r.status,
			}
			for r in rows
		])

	@expose("/<asset_id>/criticality")
	@has_access
	def criticality_assessment(self, asset_id: str):
		"""Run criticality assessment for an asset."""
		try:
			result = _svc().assess_criticality(asset_id, _get_session())
			return jsonify(result)
		except Exception as exc:
			log.warning("criticality_assessment error: %s", exc)
			abort(400, str(exc))

	@expose("/<asset_id>/schedule-pm", methods=["POST"])
	@has_access
	def schedule_pm(self, asset_id: str):
		"""Schedule preventive maintenance for an asset.

		POST body: {frequency_days, horizon_days?, estimated_cost_cents?}
		"""
		body = request.get_json(silent=True) or {}
		freq = int(body.get("frequency_days", 90))
		horizon = int(body.get("horizon_days", 365))
		cost = int(body.get("estimated_cost_cents", 0))
		try:
			session = _get_session()
			orders = _svc().schedule_preventive_maintenance(
				asset_id, session,
				frequency_days=freq,
				horizon_days=horizon,
				estimated_cost_cents=cost,
			)
			session.add_all(orders)
			session.commit()
			return jsonify({"created": len(orders)}), 201
		except Exception as exc:
			log.warning("schedule_pm error: %s", exc)
			abort(400, str(exc))


# ---------------------------------------------------------------------------
# MaintenanceWorkView
# ---------------------------------------------------------------------------

class MaintenanceWorkView(BaseView):
	"""CRUD + approve/complete workflow for MaintenanceWork orders."""

	route_base = "/oil-gas/maintenance"
	default_view = "list"

	field_widgets = {
		"scheduled_start": datetime_widget(),
		"scheduled_end": datetime_widget(),
		"actual_start": datetime_widget(),
		"actual_end": datetime_widget(),
		"work_type": select2_widget(
			["PREVENTIVE", "CORRECTIVE", "CONDITION_BASED", "TURNAROUND"]
		),
		"status": select2_widget(
			["PLANNED", "APPROVED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
		),
		"safety_requirements": json_widget(mode="tree"),
		"estimated_cost_cents": currency_widget("USD"),
		"actual_cost_cents": currency_widget("USD"),
	}
	label_columns = {
		"work_order_number": "Work Order",
		"work_type": "Type",
		"estimated_cost_cents": "Est. Cost",
		"actual_cost_cents": "Actual Cost",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.oil_gas.models import MaintenanceWork
		session = _get_session()
		rows = session.execute(
			sa.select(MaintenanceWork).order_by(MaintenanceWork.scheduled_start)
		).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"work_order_number": r.work_order_number,
				"asset_id": str(r.asset_id),
				"work_type": r.work_type,
				"status": r.status,
				"scheduled_start": r.scheduled_start.isoformat() if r.scheduled_start else None,
				"estimated_cost_cents": r.estimated_cost_cents,
				"actual_cost_cents": r.actual_cost_cents,
			}
			for r in rows
		])


# ---------------------------------------------------------------------------
# ProductionRecordView
# ---------------------------------------------------------------------------

class ProductionRecordView(BaseView):
	"""CRUD + production trend chart for ProductionRecord."""

	route_base = "/oil-gas/production"
	default_view = "list"

	field_widgets = {
		"production_date": date_widget(),
		"product_type": select2_widget(
			["CRUDE_OIL", "GAS", "LNG", "REFINED_PRODUCT", "NGL"]
		),
		"quality_parameters": json_widget(mode="tree"),
		# Production trend chart for detail view
		"production_trend": chart_widget(chart_type="line"),
	}
	label_columns = {
		"production_date": "Date",
		"product_type": "Product",
		"quantity": "Quantity",
		"downtime_hours": "Downtime (hrs)",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.oil_gas.models import ProductionRecord
		session = _get_session()
		rows = session.execute(
			sa.select(ProductionRecord)
			.order_by(ProductionRecord.production_date.desc())
			.limit(500)
		).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"facility_id": str(r.facility_id),
				"production_date": r.production_date.isoformat(),
				"product_type": r.product_type,
				"quantity": float(r.quantity),
				"unit": r.unit,
				"downtime_hours": float(r.downtime_hours),
			}
			for r in rows
		])


# ---------------------------------------------------------------------------
# HAZOPReviewView
# ---------------------------------------------------------------------------

class HAZOPReviewView(BaseView):
	"""CRUD for HAZOP reviews."""

	route_base = "/oil-gas/hazop"
	default_view = "list"

	field_widgets = {
		"review_date": date_widget(),
		"next_review_date": date_widget(),
		"status": select2_widget(["DRAFT", "COMPLETED", "CLOSED"]),
		"findings": json_widget(mode="tree"),
		"action_items": json_widget(mode="tree"),
	}
	label_columns = {
		"review_date": "Review Date",
		"next_review_date": "Next Review",
		"review_leader_id": "Study Leader",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.oil_gas.models import HAZOPReview
		session = _get_session()
		rows = session.execute(
			sa.select(HAZOPReview).order_by(HAZOPReview.review_date.desc())
		).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"asset_id": str(r.asset_id),
				"review_date": r.review_date.isoformat(),
				"status": r.status,
				"findings_count": len(r.findings or []),
				"action_items_count": len(r.action_items or []),
				"next_review_date": r.next_review_date.isoformat() if r.next_review_date else None,
			}
			for r in rows
		])


# ---------------------------------------------------------------------------
# IncidentReportView
# ---------------------------------------------------------------------------

class IncidentReportView(BaseView):
	"""CRUD + HSE KPI summary for IncidentReports."""

	route_base = "/oil-gas/incidents"
	default_view = "list"

	field_widgets = {
		"reported_at": datetime_widget(),
		"occurred_at": datetime_widget(),
		"incident_type": select2_widget(
			["SPILL", "FIRE", "EXPLOSION", "INJURY", "NEAR_MISS", "ENVIRONMENTAL"]
		),
		"severity": select2_widget(["TIER1", "TIER2", "TIER3"]),
		"status": select2_widget(["OPEN", "UNDER_INVESTIGATION", "CLOSED"]),
		"corrective_actions": json_widget(mode="tree"),
		# Severity breakdown chart
		"severity_chart": chart_widget(chart_type="doughnut"),
	}
	label_columns = {
		"incident_type": "Type",
		"occurred_at": "Occurred",
		"reported_at": "Reported",
		"reported_to_regulator": "Regulator Notified",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.oil_gas.models import IncidentReport
		session = _get_session()
		rows = session.execute(
			sa.select(IncidentReport)
			.order_by(IncidentReport.occurred_at.desc())
			.limit(200)
		).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"facility_id": str(r.facility_id),
				"incident_type": r.incident_type,
				"severity": r.severity,
				"occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
				"casualties": r.casualties,
				"injuries": r.injuries,
				"status": r.status,
				"reported_to_regulator": r.reported_to_regulator,
			}
			for r in rows
		])


# ---------------------------------------------------------------------------
# OilGasDashboardView
# ---------------------------------------------------------------------------

class OilGasDashboardView(BaseView):
	"""Read-only consolidated O&G operations overview.

	Combines OEE sparklines (chart_widget), production totals (bar chart),
	HSE KPI table, and maintenance backlog count per facility.
	"""

	route_base = "/oil-gas/dashboard"
	default_view = "index"

	field_widgets = {
		"production_chart": chart_widget(chart_type="bar"),
		"oee_trend": chart_widget(chart_type="line"),
		"incident_breakdown": chart_widget(chart_type="doughnut"),
	}

	@expose("/")
	@has_access
	def index(self):
		"""Summary metrics across all facilities for the current tenant."""
		from pgappforge.plugins.erp.industry.oil_gas.models import (
			Facility, IncidentReport, MaintenanceWork,
		)
		from sqlalchemy import func

		session = _get_session()

		facility_count = session.execute(
			sa.select(func.count()).select_from(Facility)
		).scalar_one()

		open_incidents = session.execute(
			sa.select(func.count())
			.select_from(IncidentReport)
			.where(IncidentReport.status != "CLOSED")
		).scalar_one()

		now = datetime.now(timezone.utc)
		overdue_work_orders = session.execute(
			sa.select(func.count())
			.select_from(MaintenanceWork)
			.where(
				MaintenanceWork.status.in_(["PLANNED", "APPROVED"]),
				MaintenanceWork.scheduled_end < now,
			)
		).scalar_one()

		return jsonify({
			"facility_count": facility_count,
			"open_incidents": open_incidents,
			"overdue_work_orders": overdue_work_orders,
		})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"FacilityView",
	"AssetView",
	"MaintenanceWorkView",
	"ProductionRecordView",
	"HAZOPReviewView",
	"IncidentReportView",
	"OilGasDashboardView",
]
