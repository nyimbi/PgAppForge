"""
pgappforge/plugins/fintech/agency/views.py

Agency Banking views: Outlets, Agents, Transactions (read-only), and
a live KPI dashboard.

Widget conventions:
  - Money columns:  CurrencyWidget (KES default)
  - JSONB columns:  JSONWidget
  - Status fields:  Select2Widget
  - Dashboard KPIs: live _count() / SUM queries via expose endpoints
"""
from __future__ import annotations

import logging
from typing import Any

from flask import jsonify
from flask_appbuilder import ModelView, BaseView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

from pgappforge.plugins.erp.foundation.view_helpers import (
	currency_widget,
	json_widget,
	select2_widget,
)
from pgappforge.plugins.fintech.agency.models import (
	AgencyAgent,
	AgencyCommission,
	AgencyFloat,
	AgencyOutlet,
	AgencyTransaction,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Label maps
# ---------------------------------------------------------------------------

_MONEY_LABELS: dict[str, str] = {
	"float_balance_cents":   "Float Balance",
	"float_minimum_cents":   "Minimum Float",
	"amount_cents":          "Amount",
	"fee_cents":             "Fee",
	"agent_commission_cents": "Commission",
	"current_balance_cents": "Current Balance",
	"gross_commission_cents": "Gross Commission",
	"tax_cents":             "WHT",
	"net_commission_cents":  "Net Commission",
}


# ---------------------------------------------------------------------------
# AgencyOutletView
# ---------------------------------------------------------------------------

class AgencyOutletView(ModelView):
	"""Agency outlet management — onboard, configure, and monitor outlets."""

	datamodel = SQLAInterface(AgencyOutlet)
	route_base = "/agency/outlets"

	list_title = "Agency Outlets"
	show_title = "Outlet Details"
	add_title = "Onboard Outlet"
	edit_title = "Edit Outlet"

	list_columns = [
		"name",
		"outlet_type",
		"status",
		"float_balance_cents",
		"float_minimum_cents",
		"created_on",
	]
	show_columns = [
		"name",
		"outlet_type",
		"status",
		"services",
		"location",
		"float_balance_cents",
		"float_minimum_cents",
		"created_on",
		"changed_on",
	]
	add_columns = [
		"tenant_id",
		"name",
		"outlet_type",
		"services",
		"location",
		"float_minimum_cents",
	]
	edit_columns = [
		"name",
		"outlet_type",
		"services",
		"location",
		"float_minimum_cents",
		"status",
	]
	search_columns = ["name", "outlet_type", "status", "tenant_id"]
	order_columns = ["name", "status", "float_balance_cents"]

	label_columns = _MONEY_LABELS
	formatters_columns = {
		"float_balance_cents": currency_widget("KES"),
		"float_minimum_cents": currency_widget("KES"),
		"services":            json_widget(),
		"location":            json_widget(),
	}


# ---------------------------------------------------------------------------
# AgencyAgentView
# ---------------------------------------------------------------------------

class AgencyAgentView(ModelView):
	"""Agency agent management — accreditation, KYC tier, and commissions."""

	datamodel = SQLAInterface(AgencyAgent)
	route_base = "/agency/agents"

	list_title = "Agency Agents"
	show_title = "Agent Details"
	add_title = "Add Agent"
	edit_title = "Edit Agent"

	list_columns = [
		"agent_name",
		"msisdn",
		"accreditation_status",
		"kyc_tier",
		"outlet_id",
		"created_on",
	]
	show_columns = [
		"agent_name",
		"msisdn",
		"national_id",
		"accreditation_status",
		"accredited_at",
		"kyc_tier",
		"outlet_id",
		"created_on",
		"changed_on",
	]
	add_columns = [
		"tenant_id",
		"outlet_id",
		"agent_name",
		"msisdn",
		"national_id",
	]
	edit_columns = [
		"agent_name",
		"msisdn",
		"national_id",
		"accreditation_status",
		"kyc_tier",
	]
	search_columns = ["agent_name", "msisdn", "accreditation_status", "tenant_id"]
	order_columns = ["agent_name", "accreditation_status", "created_on"]

	label_columns = {
		"agent_name":           "Agent Name",
		"msisdn":               "Mobile Number",
		"national_id":          "National ID",
		"accreditation_status": "Accreditation",
		"kyc_tier":             "KYC Tier",
		"outlet_id":            "Outlet",
		"accredited_at":        "Accredited At",
	}


# ---------------------------------------------------------------------------
# AgencyTransactionView  (read-only — immutable records)
# ---------------------------------------------------------------------------

class AgencyTransactionView(ModelView):
	"""Agency transaction log — read-only view of immutable transaction records."""

	datamodel = SQLAInterface(AgencyTransaction)
	route_base = "/agency/transactions"

	list_title = "Agency Transactions"
	show_title = "Transaction Detail"

	# No add/edit — immutable records
	can_add = False
	can_edit = False
	can_delete = False

	list_columns = [
		"reference",
		"service_type",
		"customer_msisdn",
		"amount_cents",
		"fee_cents",
		"agent_commission_cents",
		"status",
		"created_at",
	]
	show_columns = [
		"reference",
		"agent_id",
		"outlet_id",
		"service_type",
		"customer_msisdn",
		"amount_cents",
		"fee_cents",
		"agent_commission_cents",
		"status",
		"created_at",
	]
	search_columns = ["service_type", "status", "customer_msisdn", "reference", "tenant_id"]
	order_columns = ["created_at", "amount_cents", "status"]

	label_columns = _MONEY_LABELS
	formatters_columns = {
		"amount_cents":           currency_widget("KES"),
		"fee_cents":              currency_widget("KES"),
		"agent_commission_cents": currency_widget("KES"),
	}


# ---------------------------------------------------------------------------
# AgencyDashboardView  — live KPI dashboard
# ---------------------------------------------------------------------------

class AgencyDashboardView(BaseView):
	"""Live agency banking KPI dashboard.

	Endpoints:
	  GET /agency/dashboard/         — HTML dashboard page
	  GET /agency/dashboard/kpis     — JSON KPI snapshot
	"""

	route_base = "/agency/dashboard"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""Render the agency dashboard page."""
		self.update_redirect()
		kpis = self._get_kpis()
		return self.render_template(
			"agency/dashboard.html",
			kpis=kpis,
			title="Agency Banking Dashboard",
		)

	@expose("/kpis")
	@has_access
	def kpis(self):
		"""Return live KPI data as JSON for AJAX refresh."""
		return jsonify(self._get_kpis())

	# -----------------------------------------------------------------------
	# Internal helpers
	# -----------------------------------------------------------------------

	def _get_kpis(self) -> dict[str, Any]:
		"""Compute live KPIs with a single session fetch per metric."""
		try:
			import sqlalchemy as sa
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return {}
			session = ab.get_session

			active_outlets = self._count(session, AgencyOutlet, AgencyOutlet.status == "ACTIVE")
			accredited_agents = self._count(
				session, AgencyAgent, AgencyAgent.accreditation_status == "ACCREDITED"
			)
			pending_agents = self._count(
				session, AgencyAgent, AgencyAgent.accreditation_status == "PENDING"
			)
			today_txns = self._count(
				session,
				AgencyTransaction,
				sa.and_(
					AgencyTransaction.status == "COMPLETED",
					sa.cast(AgencyTransaction.created_at, sa.Date) == sa.func.current_date(),
				),
			)
			today_volume = self._sum(
				session,
				AgencyTransaction,
				AgencyTransaction.amount_cents,
				sa.and_(
					AgencyTransaction.status == "COMPLETED",
					sa.cast(AgencyTransaction.created_at, sa.Date) == sa.func.current_date(),
				),
			)
			low_float_outlets = session.execute(
				sa.select(sa.func.count()).select_from(AgencyOutlet).where(
					AgencyOutlet.status == "ACTIVE",
					AgencyOutlet.float_balance_cents < AgencyOutlet.float_minimum_cents,
				)
			).scalar_one_or_none() or 0

			return {
				"active_outlets":       active_outlets,
				"accredited_agents":    accredited_agents,
				"pending_agents":       pending_agents,
				"today_transactions":   today_txns,
				"today_volume_cents":   today_volume,
				"low_float_outlets":    low_float_outlets,
			}
		except Exception as exc:
			log.warning("AgencyDashboardView._get_kpis failed: %s", exc)
			return {}

	@staticmethod
	def _count(session, model, *filters) -> int:
		import sqlalchemy as sa
		q = sa.select(sa.func.count()).select_from(model)
		for f in filters:
			q = q.where(f)
		return session.execute(q).scalar_one_or_none() or 0

	@staticmethod
	def _sum(session, model, column, *filters) -> int:
		import sqlalchemy as sa
		q = sa.select(sa.func.coalesce(sa.func.sum(column), 0)).select_from(model)
		for f in filters:
			q = q.where(f)
		return session.execute(q).scalar_one_or_none() or 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"AgencyOutletView",
	"AgencyAgentView",
	"AgencyTransactionView",
	"AgencyDashboardView",
]
