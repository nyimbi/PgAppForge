"""
pgappforge/plugins/erp/industry/real_estate/property_management/views.py

Flask views for the Property Management sub-plugin.

Route summary
-------------
PropertyManagementDashboardView   /industry/property-management/
  └─ GET /industry/property-management/   — KPI dashboard

PropertyUnitView                  /pm/units/
  ├─ GET  /pm/units/              — list
  ├─ POST /pm/units/              — add
  └─ PUT  /pm/units/<id>          — edit

TenantLeaseView                   /pm/leases/
  ├─ GET  /pm/leases/             — list
  ├─ POST /pm/leases/             — add
  └─ PUT  /pm/leases/<id>         — edit

RentPaymentView                   /pm/rent-payments/
  └─ GET  /pm/rent-payments/      — list (read-only)

MaintenanceRequestView            /pm/maintenance/
  ├─ GET  /pm/maintenance/        — list
  ├─ POST /pm/maintenance/        — add
  └─ PUT  /pm/maintenance/<id>    — edit

WorkOrderView                     /pm/work-orders/
  ├─ GET  /pm/work-orders/        — list
  ├─ POST /pm/work-orders/        — add
  └─ PUT  /pm/work-orders/<id>    — edit
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import render_template

from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.base_view import BaseERPView, BaseERPModelView

from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
	PropertyUnit,
	TenantLease,
	RentPayment,
	MaintenanceRequest,
	WorkOrder,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model views
# ---------------------------------------------------------------------------

class PropertyUnitView(BaseERPModelView):
	"""CRUD view for PropertyUnit (pm_unit)."""

	datamodel    = SQLAInterface(PropertyUnit)
	route_base   = "/pm/units"

	list_columns = [
		"unit_number", "property_id", "floor", "sqft",
		"bedrooms", "bathrooms", "status",
	]
	show_columns = [
		"property_id", "unit_number", "floor", "sqft",
		"bedrooms", "bathrooms", "status",
	]
	add_columns  = [
		"property_id", "unit_number", "floor", "sqft",
		"bedrooms", "bathrooms", "status",
	]
	edit_columns = [
		"unit_number", "floor", "sqft", "bedrooms", "bathrooms", "status",
	]

	list_title = "Property Units"
	add_title  = "Add Unit"
	edit_title = "Edit Unit"
	search_columns = ["unit_number", "status"]
	label_columns = {
		"property_id": "Property",
		"unit_number": "Unit Number",
		"floor": "Floor",
		"sqft": "Sq Ft",
		"bedrooms": "Bedrooms",
		"bathrooms": "Bathrooms",
		"status": "Status",
	}


class TenantLeaseView(BaseERPModelView):
	"""CRUD view for TenantLease (pm_tenant_lease)."""

	datamodel    = SQLAInterface(TenantLease)
	route_base   = "/pm/leases"

	list_columns = [
		"unit_id", "tenant_party_id", "lease_start", "lease_end",
		"monthly_rent_cents", "security_deposit_cents", "lease_type",
		"escalation_type", "status",
	]
	show_columns = [
		"unit_id", "tenant_party_id", "landlord_id",
		"lease_start", "lease_end",
		"monthly_rent_cents", "security_deposit_cents",
		"lease_type", "escalation_type", "escalation_pct",
		"status", "renewal_option",
	]
	add_columns  = [
		"unit_id", "tenant_party_id", "landlord_id",
		"lease_start", "lease_end",
		"monthly_rent_cents", "security_deposit_cents",
		"lease_type", "escalation_type", "escalation_pct",
		"status", "renewal_option",
	]
	edit_columns = [
		"lease_start", "lease_end",
		"monthly_rent_cents", "security_deposit_cents",
		"lease_type", "escalation_type", "escalation_pct",
		"status", "renewal_option",
	]

	list_title = "Tenant Leases"
	add_title  = "New Lease"
	edit_title = "Edit Lease"
	search_columns = ["unit_id", "tenant_party_id", "lease_type", "status"]
	label_columns = {
		"unit_id": "Unit",
		"tenant_party_id": "Tenant Party",
		"landlord_id": "Landlord",
		"lease_start": "Lease Start",
		"lease_end": "Lease End",
		"monthly_rent_cents": "Monthly Rent (¢)",
		"security_deposit_cents": "Security Deposit (¢)",
		"lease_type": "Lease Type",
		"escalation_type": "Escalation Type",
		"escalation_pct": "Escalation %",
		"status": "Status",
		"renewal_option": "Renewal Option",
	}


class RentPaymentView(BaseERPModelView):
	"""Read-only view for RentPayment (pm_rent_payment)."""

	datamodel = SQLAInterface(RentPayment)
	route_base = "/pm/rent-payments"

	base_permissions = ["can_list", "can_show"]

	list_columns = [
		"lease_id", "period_month", "due_date", "paid_date",
		"amount_cents", "status", "payment_method", "reference",
	]

	list_title = "Rent Payments"
	show_columns = [
		"lease_id", "period_month", "due_date", "paid_date",
		"amount_cents", "status", "payment_method", "reference",
	]
	search_columns = ["lease_id", "period_month", "status", "payment_method", "reference"]
	label_columns = {
		"lease_id": "Lease",
		"period_month": "Period",
		"due_date": "Due Date",
		"paid_date": "Paid Date",
		"amount_cents": "Amount (¢)",
		"status": "Status",
		"payment_method": "Payment Method",
		"reference": "Reference",
	}


class MaintenanceRequestView(BaseERPModelView):
	"""CRUD view for MaintenanceRequest (pm_maintenance_request)."""

	datamodel    = SQLAInterface(MaintenanceRequest)
	route_base   = "/pm/maintenance"

	list_columns = [
		"unit_id", "category", "priority", "status",
		"description", "estimated_cost_cents", "actual_cost_cents",
	]
	show_columns = [
		"unit_id", "reported_by", "category", "description",
		"priority", "status", "estimated_cost_cents",
		"actual_cost_cents", "resolved_at", "photos",
	]
	add_columns  = [
		"unit_id", "reported_by", "category", "description",
		"priority", "status", "estimated_cost_cents", "photos",
	]
	edit_columns = [
		"category", "description", "priority", "status",
		"estimated_cost_cents", "actual_cost_cents", "resolved_at",
	]

	list_title = "Maintenance Requests"
	add_title  = "Log Maintenance Request"
	edit_title = "Edit Maintenance Request"
	search_columns = ["unit_id", "category", "priority", "status", "description"]
	label_columns = {
		"unit_id": "Unit",
		"reported_by": "Reported By",
		"category": "Category",
		"description": "Description",
		"priority": "Priority",
		"status": "Status",
		"estimated_cost_cents": "Estimated Cost (¢)",
		"actual_cost_cents": "Actual Cost (¢)",
		"resolved_at": "Resolved At",
		"photos": "Photos",
	}


class WorkOrderView(BaseERPModelView):
	"""CRUD view for WorkOrder (pm_work_order)."""

	datamodel    = SQLAInterface(WorkOrder)
	route_base   = "/pm/work-orders"

	list_columns = [
		"request_id", "vendor_id", "scheduled_date", "completed_date",
		"quoted_cost_cents", "actual_cost_cents", "status",
	]
	show_columns = [
		"request_id", "vendor_id", "work_description",
		"scheduled_date", "completed_date", "quoted_cost_cents",
		"actual_cost_cents", "status", "notes",
	]
	add_columns  = [
		"request_id", "vendor_id", "work_description",
		"scheduled_date", "quoted_cost_cents", "status", "notes",
	]
	edit_columns = [
		"vendor_id", "work_description", "scheduled_date", "completed_date",
		"quoted_cost_cents", "actual_cost_cents", "status", "notes",
	]

	list_title = "Work Orders"
	add_title  = "New Work Order"
	edit_title = "Edit Work Order"
	search_columns = ["request_id", "vendor_id", "status", "work_description"]
	label_columns = {
		"request_id": "Maintenance Request",
		"vendor_id": "Vendor",
		"work_description": "Work Description",
		"scheduled_date": "Scheduled Date",
		"completed_date": "Completed Date",
		"quoted_cost_cents": "Quoted Cost (¢)",
		"actual_cost_cents": "Actual Cost (¢)",
		"status": "Status",
		"notes": "Notes",
	}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class PropertyManagementDashboardView(BaseERPView):
	"""KPI dashboard for the Property Management sub-plugin."""

	route_base     = "/industry/property-management"
	default_view   = "index"

	@expose("/")
	@has_access
	def index(self):
		"""Render the property management KPI dashboard."""
		try:
			active_leases    = self._count(TenantLease,          status="ACTIVE")
		except Exception:
			active_leases    = 0

		try:
			vacant_units     = self._count(PropertyUnit,          status="VACANT")
		except Exception:
			vacant_units     = 0

		try:
			open_maintenance = self._count(MaintenanceRequest,    status="OPEN")
		except Exception:
			open_maintenance = 0

		try:
			pending_payments = self._count(RentPayment,           status="PENDING")
		except Exception:
			pending_payments = 0

		kpi_html = self.kpi_cards([
			{
				"label":  "Active Leases",
				"value":  active_leases,
				"format": "integer",
				"color":  "#1a56db",
				"icon":   "fa-file-text",
			},
			{
				"label":  "Vacant Units",
				"value":  vacant_units,
				"format": "integer",
				"color":  "#e3a008",
				"icon":   "fa-building",
			},
			{
				"label":  "Open Maintenance",
				"value":  open_maintenance,
				"format": "integer",
				"color":  "#e02424",
				"icon":   "fa-wrench",
			},
			{
				"label":  "Pending Payments",
				"value":  pending_payments,
				"format": "integer",
				"color":  "#057a55",
				"icon":   "fa-money",
			},
		])
		unit_status_rows = self._group_count_rows(PropertyUnit, "status")
		maintenance_status_rows = self._group_count_rows(MaintenanceRequest, "status")
		unit_status_chart = self.chart(
			unit_status_rows,
			chart_type="doughnut",
			x_col="label",
			y_col="value",
			title="Units by Status",
		)
		maintenance_status_chart = self.chart(
			maintenance_status_rows,
			chart_type="bar",
			x_col="label",
			y_col="value",
			title="Maintenance by Status",
		)
		chart_html = f"""
<div style="grid-column:1/-1;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-top:16px">
  <div class="erp-card" style="padding:16px">{unit_status_chart}</div>
  <div class="erp-card" style="padding:16px">{maintenance_status_chart}</div>
</div>
"""

		return render_template(
			"appbuilder/re_pm/dashboard.html",
			kpi_html=f"{kpi_html}{chart_html}",
			appbuilder=self.appbuilder,
		)

	def _group_count_rows(self, model: type, group_by: str) -> list[dict]:
		"""Return [{label, value}] rows for dashboard group-by charts."""
		try:
			session = self._session()
			column = getattr(model, group_by)
			q = (
				sa.select(column, sa.func.count())
				.select_from(model)
				.group_by(column)
				.order_by(column)
			)
			tenant_id = self._tenant_id()
			if tenant_id and hasattr(model, "tenant_id"):
				q = q.where(model.tenant_id == tenant_id)
			rows = [
				{"label": str(label or "Unspecified"), "value": int(count or 0)}
				for label, count in session.execute(q).all()
			]
			return rows or [{"label": "No Data", "value": 0}]
		except Exception:
			return [{"label": "Unavailable", "value": 0}]

	@expose("/rent-roll")
	@has_access
	def rent_roll(self):
		"""Rent roll report — all units, current period."""
		return render_template(
			"appbuilder/re_pm/rent_roll.html",
			appbuilder=self.appbuilder,
		)

	@expose("/maintenance-board")
	@has_access
	def maintenance_board(self):
		"""Kanban maintenance board."""
		return render_template(
			"appbuilder/re_pm/maintenance_board.html",
			appbuilder=self.appbuilder,
		)


__all__ = [
	"PropertyUnitView",
	"TenantLeaseView",
	"RentPaymentView",
	"MaintenanceRequestView",
	"WorkOrderView",
	"PropertyManagementDashboardView",
]
