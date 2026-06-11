"""
pgappforge/plugins/fintech/bnpl/views.py

BNPL plugin views.

  BNPLMerchantView     — merchant CRUD (admin)
  BNPLApplicationView  — read-only application list + detail
  BNPLDashboardView    — live KPI dashboard at /bnpl/dashboard/
"""
from __future__ import annotations

import logging
from typing import Any

from flask import current_app
from flask_appbuilder import ModelView, BaseView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

from pgappforge.plugins.fintech.bnpl.models import (
	BNPLApplication,
	BNPLMerchant,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BNPLMerchantView
# ---------------------------------------------------------------------------

class BNPLMerchantView(ModelView):
	"""BNPL merchant administration — CRUD."""

	datamodel = SQLAInterface(BNPLMerchant)
	route_base = "/bnpl/merchants"

	list_title = "BNPL Merchants"
	show_title = "Merchant Details"
	add_title = "Onboard Merchant"
	edit_title = "Edit Merchant"

	list_columns = [
		"name",
		"merchant_category",
		"settlement_account_number",
		"commission_pct",
		"is_active",
	]

	show_fieldsets = [
		("Merchant", {
			"fields": [
				"name", "merchant_category", "is_active",
			]
		}),
		("Settlement", {
			"fields": [
				"settlement_account_number", "commission_pct",
			]
		}),
	]

	add_fieldsets = show_fieldsets
	edit_fieldsets = show_fieldsets

	label_columns: dict[str, str] = {
		"name": "Merchant Name",
		"merchant_category": "Category",
		"settlement_account_number": "Settlement Account",
		"commission_pct": "Commission %",
		"is_active": "Active",
	}

	search_columns = ["name", "merchant_category"]
	base_order = ("name", "asc")

	formatters_columns: dict[str, Any] = {
		"commission_pct": lambda v: f"{float(v)*100:.2f}%" if v is not None else "—",
		"is_active": lambda v: "Yes" if v else "No",
	}


# ---------------------------------------------------------------------------
# BNPLApplicationView — read-only
# ---------------------------------------------------------------------------

class BNPLApplicationView(ModelView):
	"""BNPL application list and detail — read-only."""

	datamodel = SQLAInterface(BNPLApplication)
	route_base = "/bnpl/applications"

	base_permissions = ["can_list", "can_show"]

	list_title = "BNPL Applications"
	show_title = "Application Details"

	list_columns = [
		"customer_id",
		"merchant_id",
		"order_amount_cents",
		"plan_type",
		"status",
		"credit_score",
		"created_at",
	]

	show_fieldsets = [
		("Application", {
			"fields": [
				"customer_id", "merchant_id", "order_amount_cents",
				"plan_type", "status",
			]
		}),
		("Credit Assessment", {
			"fields": [
				"credit_score", "affordability_score", "approved_limit_cents",
			]
		}),
		("Timestamps", {
			"fields": ["created_at", "updated_at"]
		}),
	]

	label_columns: dict[str, str] = {
		"customer_id": "Customer",
		"merchant_id": "Merchant",
		"order_amount_cents": "Order Amount",
		"plan_type": "Plan Type",
		"status": "Status",
		"credit_score": "Credit Score",
		"affordability_score": "Affordability Score",
		"approved_limit_cents": "Approved Limit",
		"created_at": "Applied At",
		"updated_at": "Updated",
	}

	search_columns = ["plan_type", "status"]
	base_order = ("created_at", "desc")

	formatters_columns: dict[str, Any] = {
		"order_amount_cents": lambda v: f"{v/100:,.2f}" if v is not None else "—",
		"approved_limit_cents": lambda v: f"{v/100:,.2f}" if v is not None else "—",
		"status": lambda v: (
			'<span class="badge bg-'
			+ {
				"PENDING": "warning",
				"APPROVED": "info",
				"DECLINED": "danger",
				"ACTIVE": "success",
				"COMPLETED": "primary",
				"DEFAULTED": "dark",
			}.get(v or "", "secondary")
			+ f'">{v}</span>'
		),
	}


# ---------------------------------------------------------------------------
# BNPLDashboardView
# ---------------------------------------------------------------------------

class BNPLDashboardView(BaseView):
	"""Live KPI dashboard for BNPL operations."""

	route_base = "/bnpl/dashboard"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self) -> str:
		"""Render the BNPL KPI dashboard."""
		try:
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				kpis: dict[str, Any] = {}
			else:
				session = ab.get_session
				kpis = self._build_kpis(session)
		except Exception as exc:
			log.warning("BNPLDashboardView.index: failed to build KPIs: %s", exc)
			kpis = {}

		return self.render_template(
			"appbuilder/general/dashboard.html",
			title="BNPL Dashboard",
			kpis=kpis,
		)

	@staticmethod
	def _count(session: Any, model: Any, **filters: Any) -> int:
		"""Return row count with optional equality filters."""
		from sqlalchemy import select, func

		stmt = select(func.count(model.id))
		for col_name, val in filters.items():
			stmt = stmt.where(getattr(model, col_name) == val)
		return session.execute(stmt).scalar_one()

	def _build_kpis(self, session: Any) -> dict[str, Any]:
		from pgappforge.plugins.fintech.bnpl.models import (
			BNPLApplication,
			BNPLMerchant,
			BNPLInstallment,
			BNPLPlan,
		)
		from sqlalchemy import select, func

		total_applications = self._count(session, BNPLApplication)
		pending_apps = self._count(session, BNPLApplication, status="PENDING")
		active_apps = self._count(session, BNPLApplication, status="ACTIVE")
		completed_apps = self._count(session, BNPLApplication, status="COMPLETED")
		defaulted_apps = self._count(session, BNPLApplication, status="DEFAULTED")
		active_merchants = self._count(session, BNPLMerchant, is_active=True)
		overdue_installments = self._count(session, BNPLInstallment, status="OVERDUE")
		active_plans = self._count(session, BNPLPlan, status="ACTIVE")

		# Total gross merchandise value (approved limit sum across ACTIVE+COMPLETED)
		gmv_result = session.execute(
			select(func.coalesce(func.sum(BNPLApplication.order_amount_cents), 0)).where(
				BNPLApplication.status.in_(["ACTIVE", "COMPLETED"])
			)
		).scalar_one()

		return {
			"total_applications": total_applications,
			"pending_apps": pending_apps,
			"active_apps": active_apps,
			"completed_apps": completed_apps,
			"defaulted_apps": defaulted_apps,
			"active_merchants": active_merchants,
			"overdue_installments": overdue_installments,
			"active_plans": active_plans,
			"gmv_cents": int(gmv_result),
			"gmv_display": f"{int(gmv_result)/100:,.2f}",
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"BNPLMerchantView",
	"BNPLApplicationView",
	"BNPLDashboardView",
]
