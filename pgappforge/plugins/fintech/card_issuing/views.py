"""
pgappforge/plugins/fintech/card_issuing/views.py

Card Issuing views: BIN registry, issued cards, authorization log, dashboard.

Security posture:
  - IssuedCardView: list/show only (no add/edit — cards are issued via service)
  - CardAuthorizationLogView: list/show only (immutable audit log)
  - CardBINView: full CRUD for admin operators
  - CardIssuingDashboardView: read-only KPI dashboard
"""
from __future__ import annotations

import logging
from typing import Any

from flask import current_app
from flask_appbuilder import expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPModelView, BaseERPView
from pgappforge.plugins.fintech.card_issuing.models import (
	CardAuthorizationLog,
	CardBIN,
	IssuedCard,
	PINBlock,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CardBINView — BIN registry management
# ---------------------------------------------------------------------------

class CardBINView(BaseERPModelView):
	"""Bank Identification Number registry — managed by card scheme operators."""

	datamodel = SQLAInterface(CardBIN)
	route_base = "/fintech/card-bins"

	list_title = "Card BINs"
	show_title = "BIN Details"
	add_title = "Add BIN"
	edit_title = "Edit BIN"

	list_columns = ["bin_code", "network", "card_type", "is_active"]

	show_fieldsets = [
		("BIN", {
			"fields": ["bin_code", "network", "card_type", "product_code", "is_active"]
		}),
	]
	add_fieldsets = show_fieldsets
	edit_fieldsets = show_fieldsets

	label_columns = {
		"bin_code": "BIN Code",
		"network": "Network",
		"card_type": "Card Type",
		"product_code": "Product Code",
		"is_active": "Active",
	}

	search_columns = ["bin_code", "network", "card_type"]
	base_order = ("bin_code", "asc")

	formatters_columns: dict[str, Any] = {
		"network": lambda v: {
			"VISA": '<span class="badge bg-primary">VISA</span>',
			"MASTERCARD": '<span class="badge bg-warning text-dark">MC</span>',
			"AMEX": '<span class="badge bg-success">AMEX</span>',
		}.get(v or "", f'<span class="badge bg-secondary">{v}</span>'),
	}


# ---------------------------------------------------------------------------
# IssuedCardView — read-only card list/show
# ---------------------------------------------------------------------------

class IssuedCardView(BaseERPModelView):
	"""Issued cards — list and show only; issuance is service-driven."""

	datamodel = SQLAInterface(IssuedCard)
	route_base = "/fintech/issued-cards"

	list_title = "Issued Cards"
	show_title = "Card Details"

	# Cards are issued and managed via the service, never via CRUD forms
	can_add = False
	can_edit = False
	can_delete = False

	base_permissions = ["can_list", "can_show"]

	list_columns = [
		"card_number_masked",
		"card_number_last4",
		"status",
		"is_virtual",
		"expiry_month",
		"expiry_year",
	]

	show_fieldsets = [
		("Card Identity", {
			"fields": [
				"card_number_masked", "card_number_last4",
				"cardholder_name", "is_virtual",
				"expiry_month", "expiry_year",
			]
		}),
		("Status", {
			"fields": ["status", "block_reason", "daily_limit_cents"]
		}),
		("Timestamps", {
			"fields": ["activated_at", "last_used_at", "pin_set_at", "pin_attempts"]
		}),
	]

	label_columns = {
		"card_number_masked": "Card Number",
		"card_number_last4": "Last 4",
		"cardholder_name": "Cardholder",
		"is_virtual": "Virtual",
		"expiry_month": "Exp. Month",
		"expiry_year": "Exp. Year",
		"status": "Status",
		"block_reason": "Block Reason",
		"daily_limit_cents": "Daily Limit",
		"activated_at": "Activated",
		"last_used_at": "Last Used",
		"pin_set_at": "PIN Set",
		"pin_attempts": "PIN Attempts",
	}

	search_columns = ["card_number_last4", "status", "cardholder_name"]
	base_order = ("created_at", "desc")

	formatters_columns: dict[str, Any] = {
		"status": lambda v: (
			'<span class="badge bg-'
			+ {
				"ACTIVE": "success",
				"INACTIVE": "secondary",
				"BLOCKED": "danger",
				"REPLACED": "warning",
				"EXPIRED": "dark",
			}.get(v or "", "secondary")
			+ f'">{v}</span>'
		),
		"daily_limit_cents": lambda v: (
			f"KES {v/100:,.2f}" if v else "No limit"
		),
	}


# ---------------------------------------------------------------------------
# CardAuthorizationLogView — immutable authorization audit log
# ---------------------------------------------------------------------------

class CardAuthorizationLogView(BaseERPModelView):
	"""Card authorization log — read-only audit trail of all auth attempts."""

	datamodel = SQLAInterface(CardAuthorizationLog)
	route_base = "/fintech/card-auth-log"

	list_title = "Authorization Log"
	show_title = "Authorization Detail"

	can_add = False
	can_edit = False
	can_delete = False

	base_permissions = ["can_list", "can_show"]

	list_columns = [
		"authorization_type",
		"amount_cents",
		"result",
		"merchant_name",
		"created_at",
	]

	show_fieldsets = [
		("Authorization", {
			"fields": [
				"authorization_type", "amount_cents", "currency_code",
				"result", "authorization_code", "decline_reason", "rrn",
			]
		}),
		("Merchant", {
			"fields": [
				"merchant_name", "merchant_category_code", "terminal_id",
			]
		}),
		("Timestamps", {
			"fields": ["created_at"]
		}),
	]

	label_columns = {
		"authorization_type": "Type",
		"amount_cents": "Amount",
		"currency_code": "Currency",
		"result": "Result",
		"authorization_code": "Auth Code",
		"decline_reason": "Decline Reason",
		"rrn": "RRN",
		"merchant_name": "Merchant",
		"merchant_category_code": "MCC",
		"terminal_id": "Terminal",
		"created_at": "Timestamp",
	}

	search_columns = ["authorization_type", "result", "merchant_name", "rrn"]
	base_order = ("created_at", "desc")

	formatters_columns: dict[str, Any] = {
		"result": lambda v: (
			'<span class="badge bg-success">APPROVED</span>'
			if v == "APPROVED"
			else '<span class="badge bg-danger">DECLINED</span>'
		),
		"amount_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "—",
	}


# ---------------------------------------------------------------------------
# CardIssuingDashboardView — live KPI dashboard
# ---------------------------------------------------------------------------

class CardIssuingDashboardView(BaseERPView):
	"""Card issuing KPI dashboard — active, virtual, and blocked card counts."""

	route_base = "/fintech/cards"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""Render dashboard with live card status counts."""
		try:
			session = current_app.appbuilder.get_session
		except Exception:
			session = None

		try:
			active_cards = self._count(IssuedCard, session=session, status="ACTIVE")
		except Exception:
			active_cards = 0

		try:
			virtual_cards = self._count(
				IssuedCard, session=session, is_virtual=True, status="ACTIVE"
			)
		except Exception:
			virtual_cards = 0

		try:
			blocked_cards = self._count(IssuedCard, session=session, status="BLOCKED")
		except Exception:
			blocked_cards = 0

		kpi_html = self.kpi_cards([
			{
				"label": "Active Cards",
				"value": active_cards,
				"format": "integer",
				"color": "#057a55",
				"icon": "fa-credit-card",
			},
			{
				"label": "Active Virtual",
				"value": virtual_cards,
				"format": "integer",
				"color": "#1a56db",
				"icon": "fa-mobile-alt",
			},
			{
				"label": "Blocked Cards",
				"value": blocked_cards,
				"format": "integer",
				"color": "#e02424",
				"icon": "fa-ban",
			},
		])

		return self.render_template(
			"card_issuing/dashboard.html",
			kpi_html=kpi_html,
			active_cards=active_cards,
			virtual_cards=virtual_cards,
			blocked_cards=blocked_cards,
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"CardBINView",
	"IssuedCardView",
	"CardAuthorizationLogView",
	"CardIssuingDashboardView",
]
