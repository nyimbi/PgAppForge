"""
pgappforge/plugins/fintech/mobile_money/views.py

FAB views for the Mobile Money + Agency Banking plugin.

Views
-----
WalletView           — CRUD: PhoneNumberWidget, CurrencyWidget, Select2 for tier/status
TransactionView      — Read-only list: CurrencyWidget, PhoneNumberWidget, DateTimePickerWidget
AgentView            — CRUD: MapWidget for location, CurrencyWidget for float, StarRatingWidget
MerchantView         — CRUD: CurrencyWidget, Select2 for till_type
AgentNetworkMapView  — /mobile-money/agent-map/ : GeographicHeatmapWidget for agent density
FloatDashboard       — /mobile-money/float/     : AdvancedChartsWidget, commission summary
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from flask import abort, current_app, jsonify, make_response, request
from flask_babel import lazy_gettext as _

from pgappforge import ModelView, expose
from pgappforge.baseviews import BaseView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.foundation.commons import format_currency, status_badge
from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	currency_widget,
	datetime_widget,
	heatmap_widget,
	json_widget,
	map_widget,
	phone_widget,
	select2_widget,
	star_widget,
)

from .models import (
	Agent,
	AgentCommission,
	DisbursementBatch,
	MerchantTill,
	MobileTransaction,
	MobileWallet,
)

log = logging.getLogger(__name__)

# Currency for display (override via app config MM_CURRENCY)
_DEFAULT_CURRENCY = "KES"


def _currency() -> str:
	try:
		return current_app.config.get("MM_CURRENCY", _DEFAULT_CURRENCY)
	except RuntimeError:
		return _DEFAULT_CURRENCY


def _get_session() -> Any:
	try:
		from pgappforge import db  # type: ignore[attr-defined]
		return db.session
	except Exception:
		db = current_app.extensions["sqlalchemy"]
		return db.session


def _he(s: str) -> str:
	"""Minimal HTML-escape for inline HTML."""
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{_he(title)}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		"<style>body{padding:24px}.mm-table{width:100%;border-collapse:collapse;background:#fff}"
		".mm-table th,.mm-table td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left}"
		".mm-table th{background:#f9fafb;font-size:12px;text-transform:uppercase;color:#374151}"
		"</style></head><body>"
		f"{body}</body></html>"
	)


def _format_cents(value: object) -> str:
	return format_currency(int(value or 0), _currency())


# ---------------------------------------------------------------------------
# WalletView
# ---------------------------------------------------------------------------

class WalletView(ModelView):
	"""CRUD view for MobileWallet.

	Sensitive fields (pin_hash, device_imei) are excluded from all lists/forms.
	"""

	datamodel = SQLAInterface(MobileWallet)
	route_base = "/mobile-money/wallets"

	list_title = "Mobile Wallets"
	add_title = "Register Wallet"
	edit_title = "Edit Wallet"
	show_title = "Wallet Detail"

	list_columns = [
		"msisdn", "wallet_type", "kyc_tier",
		"balance_cents", "daily_used_cents", "daily_limit_cents",
		"status", "last_transaction_at",
	]
	show_columns = [
		"msisdn", "customer_id", "linked_account_id",
		"wallet_type", "kyc_tier",
		"balance_cents", "max_balance_cents",
		"daily_limit_cents", "daily_used_cents",
		"status", "pin_attempts", "pin_locked_until",
		"last_transaction_at", "created_at", "updated_at",
	]
	add_columns = [
		"msisdn", "customer_id", "linked_account_id",
		"wallet_type", "kyc_tier",
		"max_balance_cents", "daily_limit_cents",
		"status",
	]
	edit_columns = [
		"linked_account_id", "wallet_type", "kyc_tier",
		"max_balance_cents", "daily_limit_cents",
		"status",
	]

	search_columns = ["msisdn", "wallet_type", "kyc_tier", "status"]
	order_columns = ["msisdn", "balance_cents", "last_transaction_at", "created_at"]

	label_columns = {
		"msisdn": "Mobile Number",
		"customer_id": "Customer",
		"linked_account_id": "Linked Bank Account",
		"wallet_type": "Wallet Type",
		"kyc_tier": "KYC Tier",
		"balance_cents": "Balance",
		"max_balance_cents": "Max Balance",
		"daily_limit_cents": "Daily Limit",
		"daily_used_cents": "Used Today",
		"pin_attempts": "Failed PIN Attempts",
		"pin_locked_until": "PIN Locked Until",
		"status": "Status",
		"last_transaction_at": "Last Transaction",
		"created_at": "Registered",
		"updated_at": "Last Updated",
	}

	formatters_columns = {
		"balance_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"max_balance_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"daily_limit_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"daily_used_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"status": lambda v, ctx: status_badge(v or ""),
		"kyc_tier": lambda v, ctx: f'<span class="badge bg-info">{_he(v or "")}</span>',
	}

	# Widget overrides
	add_form_extra_fields = {
		"msisdn": phone_widget(),
		"kyc_tier": select2_widget(["TIER_1", "TIER_2", "TIER_3"]),
		"wallet_type": select2_widget(["STANDARD", "PREMIUM", "MERCHANT", "AGENT"]),
		"status": select2_widget(["ACTIVE", "SUSPENDED", "CLOSED", "PENDING_KYC"]),
		"max_balance_cents": currency_widget(_DEFAULT_CURRENCY),
		"daily_limit_cents": currency_widget(_DEFAULT_CURRENCY),
	}
	edit_form_extra_fields = {
		"wallet_type": select2_widget(["STANDARD", "PREMIUM", "MERCHANT", "AGENT"]),
		"kyc_tier": select2_widget(["TIER_1", "TIER_2", "TIER_3"]),
		"status": select2_widget(["ACTIVE", "SUSPENDED", "CLOSED", "PENDING_KYC"]),
		"max_balance_cents": currency_widget(_DEFAULT_CURRENCY),
		"daily_limit_cents": currency_widget(_DEFAULT_CURRENCY),
	}


# ---------------------------------------------------------------------------
# TransactionView  (read-only)
# ---------------------------------------------------------------------------

class TransactionView(ModelView):
	"""Read-only list/detail view for MobileTransaction.

	No add/edit/delete — transactions are immutable ledger records.
	"""

	datamodel = SQLAInterface(MobileTransaction)
	route_base = "/mobile-money/transactions"

	list_title = "Mobile Money Transactions"
	show_title = "Transaction Detail"

	# Disable mutating endpoints
	can_add = False
	can_edit = False
	can_delete = False

	list_columns = [
		"transaction_id", "transaction_type", "sender_msisdn", "recipient_msisdn",
		"amount_cents", "fee_cents", "channel", "status",
		"initiated_at", "confirmation_code",
	]
	show_columns = [
		"transaction_id", "transaction_type",
		"sender_msisdn", "recipient_msisdn", "recipient_name",
		"merchant_code", "amount_cents", "fee_cents",
		"sender_balance_before_cents", "sender_balance_after_cents",
		"channel", "status", "failure_reason",
		"initiated_at", "completed_at",
		"stk_push_request_id", "confirmation_code",
		"agent_id", "original_transaction_id",
		"created_at",
	]

	search_columns = [
		"transaction_id", "sender_msisdn", "recipient_msisdn",
		"transaction_type", "status", "confirmation_code",
	]
	order_columns = ["initiated_at", "amount_cents", "transaction_type", "status"]

	label_columns = {
		"transaction_id": "Transaction ID",
		"transaction_type": "Type",
		"sender_msisdn": "Sender",
		"recipient_msisdn": "Recipient",
		"recipient_name": "Recipient Name",
		"merchant_code": "Merchant / Till",
		"amount_cents": "Amount",
		"fee_cents": "Fee",
		"sender_balance_before_cents": "Balance Before",
		"sender_balance_after_cents": "Balance After",
		"channel": "Channel",
		"status": "Status",
		"failure_reason": "Failure Reason",
		"initiated_at": "Initiated At",
		"completed_at": "Completed At",
		"stk_push_request_id": "STK Push Request",
		"confirmation_code": "Confirmation Code",
		"agent_id": "Agent",
		"original_transaction_id": "Original Transaction",
		"created_at": "Created At",
	}

	formatters_columns = {
		"amount_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"fee_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"sender_balance_before_cents": lambda v, ctx: format_currency(v or 0, _currency()) if v is not None else "—",
		"sender_balance_after_cents": lambda v, ctx: format_currency(v or 0, _currency()) if v is not None else "—",
		"status": lambda v, ctx: status_badge(v or ""),
		"sender_msisdn": lambda v, ctx: f'<span class="text-monospace">{_he(v or "")}</span>',
		"recipient_msisdn": lambda v, ctx: f'<span class="text-monospace">{_he(v or "")}</span>',
		"confirmation_code": lambda v, ctx: f'<strong>{_he(v or "")}</strong>',
	}

	show_fieldsets = [
		("Parties", {"fields": ["sender_msisdn", "recipient_msisdn", "recipient_name", "merchant_code"]}),
		("Amounts", {"fields": ["amount_cents", "fee_cents", "sender_balance_before_cents", "sender_balance_after_cents"]}),
		("Details", {"fields": ["transaction_type", "channel", "status", "failure_reason"]}),
		("References", {"fields": ["transaction_id", "confirmation_code", "stk_push_request_id", "original_transaction_id"]}),
		("Timestamps", {"fields": ["initiated_at", "completed_at", "created_at"]}),
	]

	add_form_extra_fields = {
		"sender_msisdn": phone_widget(),
		"recipient_msisdn": phone_widget(),
		"initiated_at": datetime_widget(),
		"completed_at": datetime_widget(),
		"status": select2_widget(["PENDING", "COMPLETED", "FAILED", "REVERSED", "EXPIRED"]),
		"transaction_type": select2_widget([
			"DEPOSIT", "WITHDRAWAL", "SEND_MONEY", "BUY_GOODS", "PAY_BILL",
			"AGENT_DEPOSIT", "AGENT_WITHDRAWAL", "AIRTIME_PURCHASE",
			"LOAN_REPAYMENT", "BANK_DEPOSIT", "BANK_WITHDRAWAL", "REVERSAL",
		]),
		"amount_cents": currency_widget(_DEFAULT_CURRENCY),
		"fee_cents": currency_widget(_DEFAULT_CURRENCY),
	}


class MobileMoneyTransactionView(ModelView):
	"""Provider-focused mobile money transaction list."""

	datamodel = SQLAInterface(MobileTransaction)
	route_base = "/mobile-money/provider-transactions"
	list_columns = ["amount", "provider", "status", "reference", "created_at"]
	search_columns = ["status", "transaction_id", "confirmation_code", "channel"]
	can_add = False
	can_edit = False
	can_delete = False

	label_columns = {
		"amount": "Amount",
		"provider": "Provider",
		"status": "Status",
		"reference": "Reference",
		"created_at": "Created At",
	}

	formatters_columns = {
		"amount": lambda v, ctx: format_currency(v or 0, _currency()),
		"status": lambda v, ctx: status_badge(v or ""),
		"reference": lambda v, ctx: f'<span class="text-monospace">{_he(v or "")}</span>',
	}


# ---------------------------------------------------------------------------
# AgentView
# ---------------------------------------------------------------------------

class AgentView(ModelView):
	"""CRUD view for Agent.

	MapWidget renders the location JSONB field.
	StarRatingWidget for agent rating.
	RangeSliderWidget shows float level relative to min/max.
	"""

	datamodel = SQLAInterface(Agent)
	route_base = "/mobile-money/agents"

	list_title = "Mobile Money Agents"
	add_title = "Register Agent"
	edit_title = "Edit Agent"
	show_title = "Agent Detail"

	list_columns = [
		"agent_code", "agent_type", "status",
		"current_float_cents", "min_float_cents", "max_float_cents",
		"total_transactions", "rating",
	]
	show_columns = [
		"agent_code", "party_id", "agent_type", "parent_agent_id",
		"float_account_id", "status",
		"current_float_cents", "min_float_cents", "max_float_cents",
		"commission_rate_pct",
		"location", "operating_hours",
		"total_transactions", "total_volume_cents",
		"last_float_top_up_at", "rating",
		"created_at", "updated_at",
	]
	add_columns = [
		"agent_code", "party_id", "agent_type", "parent_agent_id",
		"float_account_id",
		"min_float_cents", "max_float_cents",
		"commission_rate_pct",
		"location", "operating_hours",
		"status",
	]
	edit_columns = [
		"agent_type", "parent_agent_id",
		"min_float_cents", "max_float_cents",
		"commission_rate_pct",
		"location", "operating_hours",
		"status", "rating",
	]

	search_columns = ["agent_code", "agent_type", "status"]
	order_columns = ["agent_code", "current_float_cents", "total_transactions", "rating"]

	label_columns = {
		"agent_code": "Agent Code",
		"party_id": "Party / Business",
		"agent_type": "Agent Type",
		"parent_agent_id": "Parent Agent",
		"float_account_id": "Float Account",
		"current_float_cents": "Current Float",
		"min_float_cents": "Min Float",
		"max_float_cents": "Max Float",
		"commission_rate_pct": "Commission Rate (%)",
		"location": "Location",
		"operating_hours": "Operating Hours",
		"status": "Status",
		"total_transactions": "Total Transactions",
		"total_volume_cents": "Total Volume",
		"last_float_top_up_at": "Last Top-Up",
		"rating": "Rating",
		"created_at": "Registered",
		"updated_at": "Last Updated",
	}

	formatters_columns = {
		"current_float_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"min_float_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"max_float_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"total_volume_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"status": lambda v, ctx: status_badge(v or ""),
		"agent_type": lambda v, ctx: f'<span class="badge bg-secondary">{_he(v or "")}</span>',
		"rating": lambda v, ctx: (
			"".join(
				["★" if float(v or 0) >= i else "☆" for i in range(1, 6)]
			) if v is not None else "—"
		),
	}

	add_form_extra_fields = {
		"agent_type": select2_widget(["MASTER_AGENT", "AGGREGATOR", "SUBAGENT"]),
		"status": select2_widget(["ACTIVE", "SUSPENDED", "DEREGISTERED"]),
		"location": map_widget(zoom=13),
		"current_float_cents": currency_widget(_DEFAULT_CURRENCY),
		"min_float_cents": currency_widget(_DEFAULT_CURRENCY),
		"max_float_cents": currency_widget(_DEFAULT_CURRENCY),
		"operating_hours": json_widget(mode="code", height=150),
		"rating": star_widget(max_rating=5),
	}
	edit_form_extra_fields = {
		"agent_type": select2_widget(["MASTER_AGENT", "AGGREGATOR", "SUBAGENT"]),
		"status": select2_widget(["ACTIVE", "SUSPENDED", "DEREGISTERED"]),
		"location": map_widget(zoom=13),
		"min_float_cents": currency_widget(_DEFAULT_CURRENCY),
		"max_float_cents": currency_widget(_DEFAULT_CURRENCY),
		"operating_hours": json_widget(mode="code", height=150),
		"rating": star_widget(max_rating=5),
	}


# ---------------------------------------------------------------------------
# MerchantView
# ---------------------------------------------------------------------------

class MerchantView(ModelView):
	"""CRUD view for MerchantTill (Buy-Goods tills and Pay-Bill shortcodes)."""

	datamodel = SQLAInterface(MerchantTill)
	route_base = "/mobile-money/merchants"

	list_title = "Merchant Tills"
	add_title = "Register Till"
	edit_title = "Edit Till"
	show_title = "Till Detail"

	list_columns = [
		"till_number", "business_name", "till_type",
		"paybill_number", "category", "status",
		"total_received_cents", "last_settlement_at",
	]
	show_columns = [
		"till_number", "business_name", "merchant_id",
		"settlement_account_id", "till_type", "paybill_number",
		"category", "status", "daily_settlement",
		"total_received_cents", "last_settlement_at",
		"created_at", "updated_at",
	]
	add_columns = [
		"till_number", "business_name", "merchant_id",
		"settlement_account_id", "till_type", "paybill_number",
		"category", "daily_settlement", "status",
	]
	edit_columns = [
		"business_name", "settlement_account_id",
		"till_type", "paybill_number",
		"category", "daily_settlement", "status",
	]

	search_columns = ["till_number", "business_name", "paybill_number", "till_type", "status"]
	order_columns = ["till_number", "business_name", "total_received_cents"]

	label_columns = {
		"till_number": "Till Number",
		"business_name": "Business Name",
		"merchant_id": "Merchant (Party)",
		"settlement_account_id": "Settlement Account",
		"till_type": "Till Type",
		"paybill_number": "Pay-Bill Number",
		"category": "Business Category",
		"status": "Status",
		"daily_settlement": "Daily Settlement",
		"total_received_cents": "Total Received",
		"last_settlement_at": "Last Settlement",
		"created_at": "Registered",
		"updated_at": "Last Updated",
	}

	formatters_columns = {
		"total_received_cents": lambda v, ctx: format_currency(v or 0, _currency()),
		"status": lambda v, ctx: status_badge(v or ""),
		"till_type": lambda v, ctx: f'<span class="badge bg-primary">{_he(v or "")}</span>',
		"daily_settlement": lambda v, ctx: (
			'<span class="text-success">Yes</span>'
			if v
			else '<span class="text-muted">No</span>'
		),
	}

	add_form_extra_fields = {
		"till_type": select2_widget(["BUY_GOODS", "PAY_BILL"]),
		"status": select2_widget(["ACTIVE", "SUSPENDED", "DEREGISTERED"]),
	}
	edit_form_extra_fields = {
		"till_type": select2_widget(["BUY_GOODS", "PAY_BILL"]),
		"status": select2_widget(["ACTIVE", "SUSPENDED", "DEREGISTERED"]),
	}


# ---------------------------------------------------------------------------
# AgentNetworkMapView
# ---------------------------------------------------------------------------

class AgentNetworkMapView(BaseView):
	"""Geographic heatmap of agent network density.

	GET /mobile-money/agent-map/        — HTML page with heatmap widget
	GET /mobile-money/agent-map/data    — JSON [{lat, lng, weight, agent_code, float}]
	"""

	route_base = "/mobile-money/agent-map"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""Render the agent network map page."""
		widget_cfg = heatmap_widget()
		return self.render_template(
			"mobile_money/agent_network_map.html",
			title="Agent Network Map",
			widget=widget_cfg,
			data_url="/mobile-money/agent-map/data",
		)

	@expose("/data")
	@has_access
	def data(self):
		"""Return GeoJSON-style agent locations for the heatmap widget."""
		session = _get_session()
		try:
			rows = session.execute(
				sa.select(
					Agent.id,
					Agent.agent_code,
					Agent.agent_type,
					Agent.current_float_cents,
					Agent.min_float_cents,
					Agent.location,
					Agent.status,
					Agent.rating,
				).where(
					Agent.status == "ACTIVE",
					Agent.location.isnot(None),
				)
			).all()
		except Exception as exc:
			log.error("AgentNetworkMapView.data query failed: %s", exc)
			return jsonify({"error": str(exc)}), 500

		points = []
		for row in rows:
			loc = row.location or {}
			lat = loc.get("lat")
			lng = loc.get("lng")
			if lat is None or lng is None:
				continue
			# Weight by current_float relative to min_float for heatmap intensity
			min_f = row.min_float_cents or 1
			weight = min(float(row.current_float_cents or 0) / float(min_f), 5.0)
			points.append({
				"lat": float(lat),
				"lng": float(lng),
				"weight": weight,
				"agent_code": row.agent_code,
				"agent_type": row.agent_type,
				"float_display": format_currency(row.current_float_cents or 0, _currency()),
				"status": row.status,
				"rating": float(row.rating) if row.rating is not None else None,
				"address": loc.get("address", ""),
				"town": loc.get("town", ""),
				"county": loc.get("county", ""),
			})

		return jsonify({"points": points, "total": len(points)})


# ---------------------------------------------------------------------------
# FloatDashboard
# ---------------------------------------------------------------------------

class FloatDashboard(BaseView):
	"""Agent float levels and commission summary dashboard.

	GET /mobile-money/float/         — HTML dashboard page
	GET /mobile-money/float/chart    — JSON chart data for AdvancedChartsWidget
	GET /mobile-money/float/summary  — JSON commission summary table
	"""

	route_base = "/mobile-money/float"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""Render the float dashboard."""
		chart_cfg = chart_widget("bar")
		return self.render_template(
			"mobile_money/float_dashboard.html",
			title="Float & Commission Dashboard",
			chart=chart_cfg,
			chart_url="/mobile-money/float/chart",
			summary_url="/mobile-money/float/summary",
		)

	@expose("/chart")
	@has_access
	def chart(self):
		"""Return bar chart data: agent_code vs current_float_cents."""
		session = _get_session()
		try:
			rows = session.execute(
				sa.select(
					Agent.agent_code,
					Agent.current_float_cents,
					Agent.min_float_cents,
					Agent.max_float_cents,
					Agent.agent_type,
					Agent.status,
				).where(Agent.status == "ACTIVE")
				.order_by(sa.desc(Agent.current_float_cents))
				.limit(50)
			).all()
		except Exception as exc:
			log.error("FloatDashboard.chart query failed: %s", exc)
			return jsonify({"error": str(exc)}), 500

		labels = [r.agent_code for r in rows]
		float_data = [r.current_float_cents for r in rows]
		min_data = [r.min_float_cents for r in rows]

		return jsonify({
			"labels": labels,
			"datasets": [
				{
					"label": "Current Float",
					"data": float_data,
					"backgroundColor": [
						"#28a745" if f >= m else "#dc3545"
						for f, m in zip(float_data, min_data)
					],
				},
				{
					"label": "Min Float Required",
					"data": min_data,
					"backgroundColor": "#ffc107",
					"type": "line",
				},
			],
			"currency": _currency(),
		})

	@expose("/summary")
	@has_access
	def summary(self):
		"""Return commission summary: pending/approved/paid counts and totals."""
		session = _get_session()
		try:
			rows = session.execute(
				sa.select(
					AgentCommission.status,
					sa.func.count(AgentCommission.id).label("count"),
					sa.func.sum(AgentCommission.commission_earned_cents).label("earned"),
					sa.func.sum(AgentCommission.commission_paid_cents).label("paid"),
				).group_by(AgentCommission.status)
			).all()
		except Exception as exc:
			log.error("FloatDashboard.summary query failed: %s", exc)
			return jsonify({"error": str(exc)}), 500

		summary = []
		for row in rows:
			earned = int(row.earned or 0)
			paid = int(row.paid or 0)
			summary.append({
				"status": row.status,
				"count": row.count,
				"earned_cents": earned,
				"paid_cents": paid,
				"outstanding_cents": earned - paid,
				"earned_display": format_currency(earned, _currency()),
				"paid_display": format_currency(paid, _currency()),
				"outstanding_display": format_currency(earned - paid, _currency()),
			})

		# Overall float health stats
		try:
			health = session.execute(
				sa.select(
					sa.func.count(Agent.id).label("total_agents"),
					sa.func.sum(Agent.current_float_cents).label("total_float"),
					sa.func.sum(
						sa.case(
							(Agent.current_float_cents < Agent.min_float_cents, 1),
							else_=0,
						)
					).label("low_float_count"),
				).where(Agent.status == "ACTIVE")
			).one()
		except Exception:
			health = None

		return jsonify({
			"commission_summary": summary,
			"float_health": {
				"total_active_agents": int(health.total_agents or 0) if health else 0,
				"total_float_cents": int(health.total_float or 0) if health else 0,
				"total_float_display": format_currency(
					int(health.total_float or 0) if health else 0, _currency()
				),
				"low_float_agents": int(health.low_float_count or 0) if health else 0,
			},
		})


class MobileMoneyDashboardView(BaseERPView):
	"""Provider dashboard for M-Pesa, MTN, Airtel, and Flutterwave."""

	route_base = "/erp/fintech/mobile-money"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = _get_session()
		provider_stats = self._provider_stats(session)
		pending_reversals_count = self._pending_reversals_count(session)
		today_disbursements_total = self._today_disbursements_total(session)

		payload = {
			"provider_stats": provider_stats,
			"pending_reversals_count": pending_reversals_count,
			"today_disbursements_total": today_disbursements_total,
		}
		if request.args.get("format") == "json":
			return jsonify(payload)

		kpi_html = self.kpi_cards([
			{
				"label": "Pending Reversals",
				"value": pending_reversals_count,
				"format": "integer",
				"color": "#f59e0b",
				"icon": "fa-undo",
			},
			{
				"label": "Today Disbursements",
				"value": today_disbursements_total / 100,
				"format": "currency",
				"color": "#057a55",
				"icon": "fa-paper-plane",
			},
		])
		rows = "".join(
			"<tr>"
			f"<td>{_he(row['provider'])}</td>"
			f"<td class='text-right'>{row['volume_count']}</td>"
			f"<td class='text-right'>{row['success_rate_pct']:.2f}%</td>"
			f"<td class='text-right'>{_he(_format_cents(row['total_amount_cents']))}</td>"
			"</tr>"
			for row in provider_stats
		)
		body = (
			"<h3>Mobile Money Provider Dashboard</h3>"
			f"{kpi_html}"
			"<table class=\"mm-table\">"
			"<thead><tr><th>Provider</th><th class=\"text-right\">Volume Count</th>"
			"<th class=\"text-right\">Success Rate</th><th class=\"text-right\">Total Amount</th></tr></thead>"
			f"<tbody>{rows}</tbody></table>"
		)
		return make_response(_page_html("Mobile Money Dashboard", body), 200)

	def _provider_stats(self, session) -> list[dict[str, object]]:
		stats: list[dict[str, object]] = []
		for provider, condition in self._provider_conditions():
			try:
				row = session.execute(
					sa.select(
						sa.func.count(MobileTransaction.id).label("volume_count"),
						sa.func.coalesce(sa.func.sum(MobileTransaction.amount_cents), 0).label("total_amount_cents"),
						sa.func.coalesce(sa.func.sum(
							sa.case((MobileTransaction.status == "COMPLETED", 1), else_=0)
						), 0).label("success_count"),
					).where(condition)
				).one()
				volume_count = int(row.volume_count or 0)
				success_count = int(row.success_count or 0)
				success_rate_pct = (success_count / volume_count * 100) if volume_count else 0.0
				stats.append({
					"provider": provider,
					"volume_count": volume_count,
					"success_rate_pct": success_rate_pct,
					"total_amount_cents": int(row.total_amount_cents or 0),
				})
			except Exception:
				log.exception("MobileMoneyDashboardView: provider stats failed for %s", provider)
				stats.append({
					"provider": provider,
					"volume_count": 0,
					"success_rate_pct": 0.0,
					"total_amount_cents": 0,
				})
		return stats

	def _provider_conditions(self):
		upper_channel = sa.func.upper(sa.func.coalesce(MobileTransaction.channel, ""))
		upper_txn = sa.func.upper(sa.func.coalesce(MobileTransaction.transaction_id, ""))
		return [
			(
				"M-Pesa",
				sa.or_(
					upper_channel.in_(("MPESA", "M-PESA", "DARAJA", "STK_PUSH")),
					upper_txn.like("MP%"),
				),
			),
			("MTN", upper_channel.like("%MTN%")),
			("Airtel", upper_channel.like("%AIRTEL%")),
			("Flutterwave", upper_channel.like("%FLUTTERWAVE%")),
		]

	def _pending_reversals_count(self, session) -> int:
		try:
			return int(session.execute(
				sa.select(sa.func.count(MobileTransaction.id))
				.where(MobileTransaction.transaction_type == "REVERSAL")
				.where(MobileTransaction.status == "PENDING")
			).scalar() or 0)
		except Exception:
			log.exception("MobileMoneyDashboardView: pending reversal count failed")
			return 0

	def _today_disbursements_total(self, session) -> int:
		now = datetime.now(timezone.utc)
		start = now.replace(hour=0, minute=0, second=0, microsecond=0)
		end = start + timedelta(days=1)
		try:
			return int(session.execute(
				sa.select(sa.func.coalesce(sa.func.sum(DisbursementBatch.total_amount_cents), 0))
				.where(DisbursementBatch.created_at >= start)
				.where(DisbursementBatch.created_at < end)
				.where(DisbursementBatch.status.in_(("APPROVED", "PROCESSING", "COMPLETED")))
			).scalar() or 0)
		except Exception:
			log.exception("MobileMoneyDashboardView: today disbursement total failed")
			return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"WalletView",
	"TransactionView",
	"MobileMoneyTransactionView",
	"AgentView",
	"MerchantView",
	"AgentNetworkMapView",
	"FloatDashboard",
	"MobileMoneyDashboardView",
]
