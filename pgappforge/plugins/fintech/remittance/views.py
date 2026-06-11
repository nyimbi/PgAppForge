"""
pgappforge/plugins/fintech/remittance/views.py

Remittance plugin views.

  RemittanceCorridorView   — CRUD for corridor configuration (admin)
  RemittanceTransactionView — read-only transfer list + detail
  RemittanceDashboardView  — live KPI dashboard at /remittance/dashboard/
"""
from __future__ import annotations

import logging
from typing import Any

from flask import current_app
from flask_appbuilder import ModelView, BaseView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

from pgappforge.plugins.fintech.remittance.models import (
	RemittanceCorridor,
	RemittanceTransaction,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RemittanceCorridorView
# ---------------------------------------------------------------------------

class RemittanceCorridorView(ModelView):
	"""FX corridor configuration — admin CRUD."""

	datamodel = SQLAInterface(RemittanceCorridor)
	route_base = "/remittance/corridors"

	list_title = "Remittance Corridors"
	show_title = "Corridor Details"
	add_title = "Add Corridor"
	edit_title = "Edit Corridor"

	list_columns = [
		"from_country",
		"to_country",
		"currency_pair",
		"flat_fee_cents",
		"fee_pct",
		"is_active",
	]

	show_fieldsets = [
		("Route", {
			"fields": [
				"from_country", "to_country", "currency_pair",
				"payout_methods", "is_active",
			]
		}),
		("Amounts", {
			"fields": ["min_amount_cents", "max_amount_cents"]
		}),
		("Fees", {
			"fields": ["flat_fee_cents", "fee_pct"]
		}),
		("Compliance", {
			"fields": ["regulatory_notes"]
		}),
	]

	add_fieldsets = show_fieldsets
	edit_fieldsets = show_fieldsets

	label_columns: dict[str, str] = {
		"from_country": "From Country",
		"to_country": "To Country",
		"currency_pair": "Currency Pair",
		"payout_methods": "Payout Methods",
		"min_amount_cents": "Min Amount (cents)",
		"max_amount_cents": "Max Amount (cents)",
		"flat_fee_cents": "Flat Fee (cents)",
		"fee_pct": "Fee %",
		"is_active": "Active",
		"regulatory_notes": "Regulatory Notes",
	}

	search_columns = ["from_country", "to_country", "currency_pair"]
	base_order = ("from_country", "asc")

	formatters_columns: dict[str, Any] = {
		"flat_fee_cents": lambda v: f"{v/100:,.2f}" if v is not None else "—",
		"min_amount_cents": lambda v: f"{v/100:,.2f}" if v is not None else "—",
		"max_amount_cents": lambda v: f"{v/100:,.2f}" if v is not None else "—",
		"fee_pct": lambda v: f"{float(v)*100:.2f}%" if v is not None else "—",
		"is_active": lambda v: "Yes" if v else "No",
	}


# ---------------------------------------------------------------------------
# RemittanceTransactionView — read-only
# ---------------------------------------------------------------------------

class RemittanceTransactionView(ModelView):
	"""Cross-border transfer list and detail — read-only."""

	datamodel = SQLAInterface(RemittanceTransaction)
	route_base = "/remittance/transactions"

	base_permissions = ["can_list", "can_show"]

	list_title = "Remittance Transfers"
	show_title = "Transfer Details"

	list_columns = [
		"reference",
		"receiver_name",
		"payout_method",
		"send_amount_cents",
		"receive_amount_cents",
		"status",
		"created_at",
	]

	show_fieldsets = [
		("Transfer", {
			"fields": [
				"reference", "status", "payout_method",
				"send_amount_cents", "receive_amount_cents", "fx_rate", "fee_cents",
			]
		}),
		("Receiver", {
			"fields": [
				"receiver_name", "receiver_phone", "receiver_account",
			]
		}),
		("Provenance", {
			"fields": [
				"quote_id", "sender_customer_id", "provider_reference",
				"compliance_checked", "created_at", "updated_at",
			]
		}),
	]

	label_columns: dict[str, str] = {
		"reference": "Reference",
		"receiver_name": "Receiver Name",
		"receiver_phone": "Receiver Phone",
		"receiver_account": "Receiver Account",
		"payout_method": "Payout Method",
		"send_amount_cents": "Send Amount",
		"receive_amount_cents": "Receive Amount",
		"fx_rate": "FX Rate",
		"fee_cents": "Fee",
		"status": "Status",
		"quote_id": "Quote",
		"sender_customer_id": "Sender",
		"provider_reference": "Provider Reference",
		"compliance_checked": "Compliance Done",
		"created_at": "Created",
		"updated_at": "Updated",
	}

	search_columns = ["reference", "receiver_name", "status", "payout_method"]
	base_order = ("created_at", "desc")

	formatters_columns: dict[str, Any] = {
		"send_amount_cents": lambda v: f"{v/100:,.2f}" if v is not None else "—",
		"receive_amount_cents": lambda v: f"{v/100:,.2f}" if v is not None else "—",
		"fee_cents": lambda v: f"{v/100:,.2f}" if v is not None else "—",
		"status": lambda v: (
			'<span class="badge bg-'
			+ {
				"PENDING": "warning",
				"PROCESSING": "info",
				"PAID": "success",
				"CANCELLED": "secondary",
				"REFUNDED": "dark",
				"FAILED": "danger",
			}.get(v or "", "secondary")
			+ f'">{v}</span>'
		),
		"compliance_checked": lambda v: "Yes" if v else "No",
	}


# ---------------------------------------------------------------------------
# RemittanceDashboardView
# ---------------------------------------------------------------------------

class RemittanceDashboardView(BaseView):
	"""Live KPI dashboard for remittance operations."""

	route_base = "/remittance/dashboard"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self) -> str:
		"""Render the remittance KPI dashboard."""
		try:
			from pgappforge.plugins.fintech.remittance.models import (
				RemittanceTransaction,
				RemittanceCorridor,
			)
			import sqlalchemy as sa
			from sqlalchemy import select, func

			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				kpis: dict[str, Any] = {}
			else:
				session = ab.get_session
				kpis = self._build_kpis(session)
		except Exception as exc:
			log.warning("RemittanceDashboardView.index: failed to build KPIs: %s", exc)
			kpis = {}

		return self.render_template(
			"appbuilder/general/dashboard.html",
			title="Remittance Dashboard",
			kpis=kpis,
		)

	@staticmethod
	def _count(session: Any, model: Any, **filters: Any) -> int:
		"""Return row count for model with optional equality filters."""
		import sqlalchemy as sa
		from sqlalchemy import select, func

		stmt = select(func.count(model.id))
		for col_name, val in filters.items():
			stmt = stmt.where(getattr(model, col_name) == val)
		return session.execute(stmt).scalar_one()

	def _build_kpis(self, session: Any) -> dict[str, Any]:
		from pgappforge.plugins.fintech.remittance.models import (
			RemittanceTransaction,
			RemittanceCorridor,
		)
		import sqlalchemy as sa
		from sqlalchemy import select, func

		total_transfers = self._count(session, RemittanceTransaction)
		pending = self._count(session, RemittanceTransaction, status="PENDING")
		processing = self._count(session, RemittanceTransaction, status="PROCESSING")
		paid = self._count(session, RemittanceTransaction, status="PAID")
		failed = self._count(session, RemittanceTransaction, status="FAILED")
		active_corridors = self._count(session, RemittanceCorridor, is_active=True)

		# Total volume (cents) of PAID transfers
		volume_result = session.execute(
			select(func.coalesce(func.sum(RemittanceTransaction.send_amount_cents), 0)).where(
				RemittanceTransaction.status == "PAID"
			)
		).scalar_one()

		return {
			"total_transfers": total_transfers,
			"pending": pending,
			"processing": processing,
			"paid": paid,
			"failed": failed,
			"active_corridors": active_corridors,
			"paid_volume_cents": int(volume_result),
			"paid_volume_display": f"{int(volume_result)/100:,.2f}",
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"RemittanceCorridorView",
	"RemittanceTransactionView",
	"RemittanceDashboardView",
]
