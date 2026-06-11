"""
pgappforge/plugins/fintech/embedded_finance/views.py

Embedded Finance views: Partners, Products, and a live KPI dashboard.

Widget conventions:
  - Money columns:  CurrencyWidget (KES default)
  - JSONB columns:  JSONWidget
  - Boolean fields: BooleanWidget
  - Dashboard KPIs: live _count() queries via expose endpoint
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
from pgappforge.plugins.fintech.embedded_finance.models import (
	EmbeddedConsent,
	EmbeddedPartner,
	EmbeddedProduct,
	EmbeddedRevShareRecord,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Label maps
# ---------------------------------------------------------------------------

_MONEY_LABELS: dict[str, str] = {
	"gross_revenue_cents": "Gross Revenue",
	"partner_share_cents": "Partner Share",
	"net_cents":           "Net Revenue",
	"revenue_share_pct":   "Revenue Share %",
}


# ---------------------------------------------------------------------------
# EmbeddedPartnerView
# ---------------------------------------------------------------------------

class EmbeddedPartnerView(ModelView):
	"""Embedded finance partner management."""

	datamodel = SQLAInterface(EmbeddedPartner)
	route_base = "/embedded-finance/partners"

	list_title = "Embedded Partners"
	show_title = "Partner Details"
	add_title = "Register Partner"
	edit_title = "Edit Partner"

	list_columns = [
		"name",
		"partner_type",
		"status",
		"sandbox_mode",
		"revenue_share_pct",
		"onboarded_at",
	]
	show_columns = [
		"name",
		"partner_type",
		"status",
		"sandbox_mode",
		"revenue_share_pct",
		"onboarded_at",
		"created_on",
		"changed_on",
	]
	add_columns = [
		"tenant_id",
		"name",
		"partner_type",
		"revenue_share_pct",
		"sandbox_mode",
	]
	edit_columns = [
		"name",
		"partner_type",
		"revenue_share_pct",
		"sandbox_mode",
		"status",
	]
	search_columns = ["name", "partner_type", "status", "tenant_id"]
	order_columns = ["name", "status", "onboarded_at"]

	label_columns = {
		**_MONEY_LABELS,
		"sandbox_mode":      "Sandbox Mode",
		"onboarded_at":      "Onboarded At",
		"revenue_share_pct": "Rev Share %",
	}


# ---------------------------------------------------------------------------
# EmbeddedProductView
# ---------------------------------------------------------------------------

class EmbeddedProductView(ModelView):
	"""Embedded product catalogue — manage products enabled per partner."""

	datamodel = SQLAInterface(EmbeddedProduct)
	route_base = "/embedded-finance/products"

	list_title = "Embedded Products"
	show_title = "Product Details"
	add_title = "Enable Product"
	edit_title = "Edit Product Config"

	list_columns = [
		"partner_id",
		"product_type",
		"is_enabled",
		"go_live_at",
	]
	show_columns = [
		"partner_id",
		"product_type",
		"is_enabled",
		"config",
		"go_live_at",
	]
	add_columns = [
		"tenant_id",
		"partner_id",
		"product_type",
		"config",
		"go_live_at",
	]
	edit_columns = [
		"product_type",
		"is_enabled",
		"config",
		"go_live_at",
	]
	search_columns = ["product_type", "is_enabled", "tenant_id"]
	order_columns = ["product_type", "is_enabled", "go_live_at"]

	label_columns = {
		"partner_id":   "Partner",
		"product_type": "Product Type",
		"is_enabled":   "Enabled",
		"go_live_at":   "Go-Live Date",
		"config":       "Configuration",
	}
	formatters_columns = {
		"config": json_widget(),
	}


# ---------------------------------------------------------------------------
# EmbeddedDashboardView  — live KPI dashboard
# ---------------------------------------------------------------------------

class EmbeddedDashboardView(BaseView):
	"""Live embedded finance KPI dashboard.

	Endpoints:
	  GET /embedded-finance/dashboard/      — HTML dashboard
	  GET /embedded-finance/dashboard/kpis  — JSON KPI snapshot
	"""

	route_base = "/embedded-finance/dashboard"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		self.update_redirect()
		kpis = self._get_kpis()
		return self.render_template(
			"embedded_finance/dashboard.html",
			kpis=kpis,
			title="Embedded Finance Dashboard",
		)

	@expose("/kpis")
	@has_access
	def kpis(self):
		return jsonify(self._get_kpis())

	# -----------------------------------------------------------------------
	# Internal helpers
	# -----------------------------------------------------------------------

	def _get_kpis(self) -> dict[str, Any]:
		try:
			import sqlalchemy as sa
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return {}
			session = ab.get_session

			active_partners = self._count(
				session, EmbeddedPartner, EmbeddedPartner.status == "ACTIVE"
			)
			sandbox_partners = self._count(
				session,
				EmbeddedPartner,
				sa.and_(
					EmbeddedPartner.status == "ACTIVE",
					EmbeddedPartner.sandbox_mode.is_(True),
				),
			)
			live_partners = self._count(
				session,
				EmbeddedPartner,
				sa.and_(
					EmbeddedPartner.status == "ACTIVE",
					EmbeddedPartner.sandbox_mode.is_(False),
				),
			)
			enabled_products = self._count(
				session, EmbeddedProduct, EmbeddedProduct.is_enabled.is_(True)
			)
			active_consents = self._count(
				session, EmbeddedConsent, EmbeddedConsent.is_active.is_(True)
			)
			total_rev_share_gross = self._sum(
				session,
				EmbeddedRevShareRecord,
				EmbeddedRevShareRecord.gross_revenue_cents,
			)
			total_partner_share = self._sum(
				session,
				EmbeddedRevShareRecord,
				EmbeddedRevShareRecord.partner_share_cents,
			)

			return {
				"active_partners":          active_partners,
				"sandbox_partners":         sandbox_partners,
				"live_partners":            live_partners,
				"enabled_products":         enabled_products,
				"active_consents":          active_consents,
				"total_rev_share_gross_cents":   total_rev_share_gross,
				"total_partner_share_cents":     total_partner_share,
			}
		except Exception as exc:
			log.warning("EmbeddedDashboardView._get_kpis failed: %s", exc)
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
	"EmbeddedPartnerView",
	"EmbeddedProductView",
	"EmbeddedDashboardView",
]
