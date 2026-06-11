"""
pgappforge/plugins/fintech/insurtech/views.py

InsurTech views: product catalogue, policy management, claims, and dashboard.

Security posture:
  - InsuranceProductView: full CRUD for underwriting administrators
  - InsurancePolicyView:  list/show/add only (no edit — use service methods)
  - InsuranceClaimView:   list/show/add only (claims filed via service)
  - InsurTechDashboardView: read-only KPI dashboard
"""
from __future__ import annotations

import logging
from typing import Any

from flask_appbuilder import expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.erp.base_view import BaseERPModelView, BaseERPView
from pgappforge.plugins.fintech.insurtech.models import (
	InsuranceClaim,
	InsurancePolicy,
	InsurancePremium,
	InsuranceProduct,
	PolicyHolder,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# InsuranceProductView — product catalogue management
# ---------------------------------------------------------------------------

class InsuranceProductView(BaseERPModelView):
	"""Insurance product catalogue — full CRUD for underwriting administrators."""

	datamodel = SQLAInterface(InsuranceProduct)
	route_base = "/fintech/insurance-products"

	list_title = "Insurance Products"
	show_title = "Product Details"
	add_title = "New Product"
	edit_title = "Edit Product"

	list_columns = [
		"name", "product_code", "product_line",
		"underwriter_name", "is_active",
	]

	show_fieldsets = [
		("Product", {
			"fields": [
				"name", "product_code", "product_line",
				"underwriter_name", "is_active",
			]
		}),
		("Coverage Limits", {
			"fields": [
				"min_sum_insured_cents", "max_sum_insured_cents",
				"min_term_months", "max_term_months",
			]
		}),
		("Formula", {"fields": ["premium_formula"]}),
		("Audit", {"fields": ["created_at", "updated_at"]}),
	]
	add_fieldsets = [
		("Product", {
			"fields": [
				"name", "product_code", "product_line",
				"underwriter_name", "is_active",
			]
		}),
		("Coverage Limits", {
			"fields": [
				"min_sum_insured_cents", "max_sum_insured_cents",
				"min_term_months", "max_term_months",
			]
		}),
		("Formula", {"fields": ["premium_formula"]}),
	]
	edit_fieldsets = add_fieldsets

	label_columns = {
		"product_code": "Code",
		"product_line": "Line",
		"underwriter_name": "Underwriter",
		"min_sum_insured_cents": "Min Sum Insured (¢)",
		"max_sum_insured_cents": "Max Sum Insured (¢)",
		"min_term_months": "Min Term (months)",
		"max_term_months": "Max Term (months)",
		"premium_formula": "Premium Formula (JSONB)",
		"is_active": "Active",
	}

	search_columns = ["name", "product_code", "product_line", "underwriter_name"]
	base_order = ("name", "asc")

	formatters_columns: dict[str, Any] = {
		"product_line": lambda v: {
			"LIFE": '<span class="badge bg-primary">LIFE</span>',
			"HEALTH": '<span class="badge bg-success">HEALTH</span>',
			"PROPERTY": '<span class="badge bg-info">PROPERTY</span>',
			"MOTOR": '<span class="badge bg-warning text-dark">MOTOR</span>',
			"TRAVEL": '<span class="badge bg-secondary">TRAVEL</span>',
			"CROP": '<span class="badge bg-success">CROP</span>',
			"MICROINSURANCE": '<span class="badge bg-light text-dark">MICRO</span>',
		}.get(v or "", f'<span class="badge bg-secondary">{v}</span>'),
		"is_active": lambda v: (
			'<span class="badge bg-success">YES</span>'
			if v else
			'<span class="badge bg-danger">NO</span>'
		),
	}


# ---------------------------------------------------------------------------
# InsurancePolicyView — policy list/show/add
# ---------------------------------------------------------------------------

class InsurancePolicyView(BaseERPModelView):
	"""Insurance policy registry — list, show, and add. Edits via service only."""

	datamodel = SQLAInterface(InsurancePolicy)
	route_base = "/fintech/insurance-policies"

	list_title = "Insurance Policies"
	show_title = "Policy Details"
	add_title = "New Policy"

	base_permissions = ["can_list", "can_show", "can_add"]

	list_columns = [
		"policy_number", "holder_id", "product_id",
		"sum_insured_cents", "annual_premium_cents",
		"start_date", "end_date", "status",
	]

	show_fieldsets = [
		("Policy", {
			"fields": [
				"policy_number", "holder_id", "product_id", "status",
			]
		}),
		("Coverage", {
			"fields": [
				"sum_insured_cents", "annual_premium_cents",
				"start_date", "end_date",
			]
		}),
		("Cancellation", {
			"fields": ["cancellation_date", "cancellation_reason"]
		}),
		("Audit", {"fields": ["created_at", "updated_at"]}),
	]
	add_fieldsets = [
		("Policy", {
			"fields": [
				"policy_number", "holder_id", "product_id",
			]
		}),
		("Coverage", {
			"fields": [
				"sum_insured_cents", "annual_premium_cents",
				"start_date", "end_date",
			]
		}),
	]

	label_columns = {
		"policy_number": "Policy No.",
		"holder_id": "Policyholder",
		"product_id": "Product",
		"sum_insured_cents": "Sum Insured (¢)",
		"annual_premium_cents": "Annual Premium (¢)",
		"start_date": "Start",
		"end_date": "End",
	}

	search_columns = ["policy_number", "status"]
	base_order = ("created_at", "desc")

	formatters_columns: dict[str, Any] = {
		"status": lambda v: {
			"ACTIVE": '<span class="badge bg-success">ACTIVE</span>',
			"PENDING": '<span class="badge bg-secondary">PENDING</span>',
			"LAPSED": '<span class="badge bg-warning text-dark">LAPSED</span>',
			"CANCELLED": '<span class="badge bg-danger">CANCELLED</span>',
			"EXPIRED": '<span class="badge bg-dark">EXPIRED</span>',
			"REINSTATED": '<span class="badge bg-info">REINSTATED</span>',
		}.get(v or "", f'<span class="badge bg-light text-dark">{v}</span>'),
	}


# ---------------------------------------------------------------------------
# InsuranceClaimView — claim list/show/add
# ---------------------------------------------------------------------------

class InsuranceClaimView(BaseERPModelView):
	"""Insurance claims — list, show, and add. Adjudication via service only."""

	datamodel = SQLAInterface(InsuranceClaim)
	route_base = "/fintech/insurance-claims"

	list_title = "Insurance Claims"
	show_title = "Claim Details"
	add_title = "New Claim"

	base_permissions = ["can_list", "can_show", "can_add"]

	list_columns = [
		"claim_number", "policy_id", "claim_type",
		"amount_claimed_cents", "status", "submitted_at",
	]

	show_fieldsets = [
		("Claim", {
			"fields": [
				"claim_number", "policy_id", "claim_type", "status",
			]
		}),
		("Incident", {
			"fields": ["incident_date", "description", "amount_claimed_cents"]
		}),
		("Decision", {
			"fields": [
				"amount_approved_cents", "decided_at", "decided_by"
			]
		}),
		("Audit", {"fields": ["submitted_at"]}),
	]
	add_fieldsets = [
		("Claim", {
			"fields": ["policy_id", "claim_type"]
		}),
		("Incident", {
			"fields": ["incident_date", "description", "amount_claimed_cents"]
		}),
	]

	label_columns = {
		"claim_number": "Claim No.",
		"policy_id": "Policy",
		"claim_type": "Type",
		"amount_claimed_cents": "Claimed (¢)",
		"amount_approved_cents": "Approved (¢)",
		"submitted_at": "Submitted",
		"decided_at": "Decided",
		"decided_by": "Decided By",
	}

	search_columns = ["claim_number", "claim_type", "status"]
	base_order = ("submitted_at", "desc")

	formatters_columns: dict[str, Any] = {
		"status": lambda v: {
			"SUBMITTED": '<span class="badge bg-secondary">SUBMITTED</span>',
			"UNDER_REVIEW": '<span class="badge bg-info">REVIEWING</span>',
			"APPROVED": '<span class="badge bg-success">APPROVED</span>',
			"REJECTED": '<span class="badge bg-danger">REJECTED</span>',
			"PAID": '<span class="badge bg-primary">PAID</span>',
			"CLOSED": '<span class="badge bg-dark">CLOSED</span>',
		}.get(v or "", f'<span class="badge bg-light text-dark">{v}</span>'),
		"claim_type": lambda v: {
			"DEATH": '<span class="badge bg-dark">DEATH</span>',
			"HOSPITALIZATION": '<span class="badge bg-warning text-dark">HOSP.</span>',
			"PROPERTY_DAMAGE": '<span class="badge bg-info">PROPERTY</span>',
			"THEFT": '<span class="badge bg-danger">THEFT</span>',
			"ACCIDENT": '<span class="badge bg-warning text-dark">ACCIDENT</span>',
			"CROP_LOSS": '<span class="badge bg-success">CROP</span>',
			"CRITICAL_ILLNESS": '<span class="badge bg-danger">CRITICAL</span>',
		}.get(v or "", f'<span class="badge bg-secondary">{v}</span>'),
	}


# ---------------------------------------------------------------------------
# InsurTechDashboardView — KPI overview
# ---------------------------------------------------------------------------

class InsurTechDashboardView(BaseERPView):
	"""InsurTech KPI dashboard."""

	route_base = "/fintech/insurtech-dashboard"
	default_view = "index"

	def _count_policies(self, session: Any, status: str) -> int:
		return session.execute(
			select(sa.func.count(InsurancePolicy.id)).where(
				InsurancePolicy.status == status
			)
		).scalar_one()

	def _count_claims(self, session: Any, status: str) -> int:
		return session.execute(
			select(sa.func.count(InsuranceClaim.id)).where(
				InsuranceClaim.status == status
			)
		).scalar_one()

	def _sum_overdue_premiums(self, session: Any) -> int:
		result = session.execute(
			select(
				sa.func.coalesce(sa.func.sum(InsurancePremium.amount_cents), 0)
			).where(InsurancePremium.status == "OVERDUE")
		).scalar_one()
		return result

	@expose("/")
	@has_access
	def index(self):
		try:
			from flask_appbuilder.models.sqla.interface import SQLAInterface
			session = SQLAInterface(InsurancePolicy).session

			active_policies = self._count_policies(session, "ACTIVE")
			lapsed_policies = self._count_policies(session, "LAPSED")
			pending_claims = self._count_claims(session, "SUBMITTED")
			under_review = self._count_claims(session, "UNDER_REVIEW")
			approved_claims = self._count_claims(session, "APPROVED")
			overdue_cents = self._sum_overdue_premiums(session)

			kpi_html = self.kpi_cards([
				{
					"label": "Active Policies",
					"value": active_policies,
					"format": "integer",
					"color": "#1a56db",
					"icon": "fa-shield",
				},
				{
					"label": "Lapsed Policies",
					"value": lapsed_policies,
					"format": "integer",
					"color": "#d97706",
					"icon": "fa-exclamation-circle",
				},
				{
					"label": "Claims Pending",
					"value": pending_claims,
					"format": "integer",
					"color": "#7c3aed",
					"icon": "fa-file-text",
				},
				{
					"label": "Under Review",
					"value": under_review,
					"format": "integer",
					"color": "#0891b2",
					"icon": "fa-search",
				},
				{
					"label": "Claims Approved",
					"value": approved_claims,
					"format": "integer",
					"color": "#16a34a",
					"icon": "fa-check-circle",
				},
				{
					"label": "Overdue Premiums",
					"value": overdue_cents,
					"format": "currency",
					"color": "#dc2626",
					"icon": "fa-money",
				},
			])
		except Exception as exc:
			log.warning("InsurTechDashboardView: failed to load KPIs: %s", exc)
			kpi_html = ""

		return self.render_template(
			"appbuilder/general/model/list.html",
			kpi_html=kpi_html,
			title="InsurTech Dashboard",
			appbuilder=self.appbuilder,
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"InsuranceProductView",
	"InsurancePolicyView",
	"InsuranceClaimView",
	"InsurTechDashboardView",
]
