"""
pgappforge/plugins/fintech/treasury/views.py

Treasury views: FX Rates, FX Deals, Open Positions, Treasury Limits.

Widget conventions follow core_banking:
  - Money columns: CurrencyWidget
  - Date fields: DatePickerWidget
  - Rate columns: plain show (no special widget — 8dp Numeric)
  - Status columns: Select2Widget (dropdown)

Security:
  - FXRateView:        can_fx_rate_list, can_fx_rate_write
  - FXDealView:        can_fx_deal_list, can_fx_deal_book, can_fx_deal_settle
  - FXPositionView:    can_fx_position_view (read-only)
  - TreasuryLimitView: can_fx_limit_list, can_fx_limit_write (admin)
"""
from __future__ import annotations

import logging
from typing import Any

from flask import flash, redirect, url_for, request
from flask_appbuilder import ModelView, BaseView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

from pgappforge.plugins.fintech.treasury.models import (
	FXDeal,
	FXPosition,
	FXRate,
	TreasuryLimit,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Label maps
# ---------------------------------------------------------------------------

_MONEY_LABELS: dict[str, str] = {
	"bought_amount_cents": "Bought Amount",
	"sold_amount_cents": "Sold Amount",
	"pnl_cents": "Realised P&L",
	"long_amount_cents": "Long Amount",
	"short_amount_cents": "Short Amount",
	"revaluation_pnl_cents": "Revaluation P&L",
	"limit_amount_cents": "Limit Amount",
	"current_utilisation_cents": "Current Utilisation",
}


# ---------------------------------------------------------------------------
# FXRateView
# ---------------------------------------------------------------------------

class FXRateView(ModelView):
	"""FX rate management — upload and view bid/offer/mid rates per currency pair."""

	datamodel = SQLAInterface(FXRate)
	route_base = "/treasury/fx-rates"

	list_title = "FX Rates"
	show_title = "FX Rate Detail"
	add_title = "Upload FX Rate"
	edit_title = "Edit FX Rate"

	list_columns = [
		"base_currency",
		"quote_currency",
		"rate_type",
		"bid_rate",
		"offer_rate",
		"mid_rate",
		"rate_source",
		"valid_from",
		"is_active",
	]
	show_columns = [
		"id",
		"tenant_id",
		"base_currency",
		"quote_currency",
		"rate_type",
		"bid_rate",
		"offer_rate",
		"mid_rate",
		"rate_source",
		"valid_from",
		"valid_to",
		"is_active",
		"created_at",
		"updated_at",
	]
	add_columns = [
		"tenant_id",
		"base_currency",
		"quote_currency",
		"rate_type",
		"bid_rate",
		"offer_rate",
		"mid_rate",
		"rate_source",
		"valid_from",
	]
	edit_columns = [
		"bid_rate",
		"offer_rate",
		"mid_rate",
		"rate_source",
		"is_active",
	]
	search_columns = [
		"base_currency",
		"quote_currency",
		"rate_type",
		"rate_source",
		"is_active",
	]
	label_columns = {
		"base_currency": "Base Currency",
		"quote_currency": "Quote Currency",
		"rate_type": "Rate Type",
		"bid_rate": "Bid Rate",
		"offer_rate": "Offer Rate",
		"mid_rate": "Mid Rate",
		"rate_source": "Source",
		"valid_from": "Valid From",
		"valid_to": "Valid To",
		"is_active": "Active",
	}
	base_order = ("valid_from", "desc")


# ---------------------------------------------------------------------------
# FXDealView
# ---------------------------------------------------------------------------

class FXDealView(ModelView):
	"""FX deal blotter — view, book, confirm, and settle FX deals."""

	datamodel = SQLAInterface(FXDeal)
	route_base = "/treasury/fx-deals"

	list_title = "FX Deal Blotter"
	show_title = "FX Deal Detail"
	add_title = "Book FX Deal"
	edit_title = "Edit FX Deal"

	list_columns = [
		"deal_number",
		"deal_type",
		"status",
		"bought_currency",
		"sold_currency",
		"bought_amount_cents",
		"sold_amount_cents",
		"exchange_rate",
		"trade_date",
		"value_date",
		"counterparty_id",
	]
	show_columns = [
		"id",
		"tenant_id",
		"deal_number",
		"deal_type",
		"status",
		"bought_currency",
		"sold_currency",
		"bought_amount_cents",
		"sold_amount_cents",
		"exchange_rate",
		"trade_date",
		"value_date",
		"maturity_date",
		"counterparty_id",
		"nostro_account_code",
		"vostro_account_code",
		"trader_id",
		"our_reference",
		"their_reference",
		"confirmation_sent_at",
		"settled_at",
		"pnl_cents",
		"revaluation_rate",
		"created_at",
		"updated_at",
	]
	add_columns = [
		"tenant_id",
		"deal_number",
		"deal_type",
		"bought_currency",
		"sold_currency",
		"bought_amount_cents",
		"sold_amount_cents",
		"exchange_rate",
		"trade_date",
		"value_date",
		"maturity_date",
		"counterparty_id",
		"nostro_account_code",
		"vostro_account_code",
		"trader_id",
		"our_reference",
		"their_reference",
	]
	edit_columns = [
		"status",
		"their_reference",
		"confirmation_sent_at",
		"nostro_account_code",
		"vostro_account_code",
	]
	search_columns = [
		"deal_number",
		"deal_type",
		"status",
		"bought_currency",
		"sold_currency",
	]
	label_columns = {
		**_MONEY_LABELS,
		"deal_number": "Deal #",
		"deal_type": "Type",
		"bought_currency": "Bought CCY",
		"sold_currency": "Sold CCY",
		"exchange_rate": "Rate",
		"trade_date": "Trade Date",
		"value_date": "Value Date",
		"maturity_date": "Maturity Date",
		"counterparty_id": "Counterparty",
		"nostro_account_code": "Nostro Account",
		"vostro_account_code": "Vostro Account",
		"trader_id": "Trader",
		"our_reference": "Our Ref",
		"their_reference": "Their Ref",
		"confirmation_sent_at": "Confirmation Sent",
		"settled_at": "Settled At",
		"revaluation_rate": "Revaluation Rate",
	}
	base_order = ("trade_date", "desc")

	@expose("/settle/<string:deal_id>", methods=["POST"])
	@has_access
	def settle(self, deal_id: str) -> Any:
		"""Settle an FX deal via the TreasuryService."""
		from flask import current_app
		try:
			ab = current_app.extensions.get("appbuilder")
			session = ab.get_session
			tenant_id = request.form.get("tenant_id", "default")
			from pgappforge.plugins.fintech.treasury.services import TreasuryService
			svc = TreasuryService(session=session, tenant_id=tenant_id)
			deal = svc.settle_fx_deal(deal_id)
			session.commit()
			flash(f"Deal {deal.deal_number} settled successfully.", "success")
		except Exception as exc:
			flash(f"Settlement failed: {exc}", "danger")
			log.error("FXDealView.settle: %s", exc, exc_info=True)
		return redirect(url_for("FXDealView.list"))


# ---------------------------------------------------------------------------
# FXPositionView — read-only position dashboard
# ---------------------------------------------------------------------------

class FXPositionView(ModelView):
	"""Open FX position monitor — net long/short per currency per day."""

	datamodel = SQLAInterface(FXPosition)
	route_base = "/treasury/fx-positions"

	list_title = "FX Open Positions"
	show_title = "FX Position Detail"

	list_columns = [
		"currency_code",
		"position_date",
		"long_amount_cents",
		"short_amount_cents",
		"revaluation_rate",
		"revaluation_pnl_cents",
	]
	show_columns = [
		"id",
		"tenant_id",
		"currency_code",
		"position_date",
		"long_amount_cents",
		"short_amount_cents",
		"revaluation_rate",
		"revaluation_pnl_cents",
		"created_at",
		"updated_at",
	]
	search_columns = ["currency_code", "position_date"]
	label_columns = {
		**_MONEY_LABELS,
		"currency_code": "Currency",
		"position_date": "Position Date",
		"revaluation_rate": "Revaluation Rate",
	}
	base_order = ("position_date", "desc")

	# Positions are system-managed: disable add/edit/delete from the UI.
	can_add = False
	can_edit = False
	can_delete = False


# ---------------------------------------------------------------------------
# TreasuryLimitView
# ---------------------------------------------------------------------------

class TreasuryLimitView(ModelView):
	"""Treasury risk limit management — open position, counterparty, stop-loss, deal size."""

	datamodel = SQLAInterface(TreasuryLimit)
	route_base = "/treasury/limits"

	list_title = "Treasury Limits"
	show_title = "Treasury Limit Detail"
	add_title = "Add Treasury Limit"
	edit_title = "Edit Treasury Limit"

	list_columns = [
		"limit_type",
		"currency_code",
		"limit_amount_cents",
		"current_utilisation_cents",
		"breach_action",
		"is_active",
	]
	show_columns = [
		"id",
		"tenant_id",
		"limit_type",
		"currency_code",
		"counterparty_id",
		"limit_amount_cents",
		"current_utilisation_cents",
		"breach_action",
		"is_active",
		"created_at",
		"updated_at",
	]
	add_columns = [
		"tenant_id",
		"limit_type",
		"currency_code",
		"counterparty_id",
		"limit_amount_cents",
		"breach_action",
		"is_active",
	]
	edit_columns = [
		"limit_amount_cents",
		"breach_action",
		"is_active",
	]
	search_columns = ["limit_type", "currency_code", "breach_action", "is_active"]
	label_columns = {
		**_MONEY_LABELS,
		"limit_type": "Limit Type",
		"currency_code": "Currency",
		"counterparty_id": "Counterparty",
		"breach_action": "Breach Action",
		"is_active": "Active",
	}
	base_order = ("limit_type", "asc")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"FXRateView",
	"FXDealView",
	"FXPositionView",
	"TreasuryLimitView",
]
