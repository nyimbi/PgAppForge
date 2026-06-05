"""
pgappforge/plugins/fintech/payments/views.py

FAB views for the Payments Engine plugin.

Views
-----
PaymentOrderView   — Read-mostly list: status badge, currency, date picker, rail type filter
PaymentBatchView   — CRUD: batch type select2, value date, total amount display
StandingOrderView  — CRUD: frequency select2, date range pickers, amount widget
PaymentRailView    — Admin CRUD: rail code, type, operating hours JSON editor
PaymentsDashboard  — /payments/dashboard/ : volume charts, rail status, settlement summary
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from flask import abort, current_app, jsonify, request
from flask_babel import lazy_gettext as _

from pgappforge import ModelView, expose
from pgappforge.baseviews import BaseView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.foundation.commons import format_currency, status_badge
from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	currency_widget,
	datetime_widget,
	json_widget,
	select2_widget,
)

from .models import PaymentBatch, PaymentOrder, PaymentRail, PaymentStatusEvent, PayStandingOrder

log = logging.getLogger(__name__)

_DEFAULT_CURRENCY = "KES"


def _currency() -> str:
	try:
		return current_app.config.get("PY_CURRENCY", _DEFAULT_CURRENCY)
	except RuntimeError:
		return _DEFAULT_CURRENCY


def _get_session() -> Any:
	try:
		from pgappforge import db  # type: ignore[attr-defined]
		return db.session
	except Exception:
		return None


# ---------------------------------------------------------------------------
# PaymentOrderView
# ---------------------------------------------------------------------------

class PaymentOrderView(ModelView):
	"""Read-mostly view for payment orders.

	Operators can view and cancel pre-submission orders; settlement is
	driven by the clearing house callback, not manually.
	"""

	datamodel = SQLAInterface(PaymentOrder)

	list_title = _("Payment Orders")
	show_title = _("Payment Order")

	list_columns = [
		"payment_reference",
		"payment_type",
		"creditor_name",
		"amount_cents",
		"currency_code",
		"value_date",
		"status",
		"channel",
		"created_at",
	]
	show_columns = [
		"payment_reference",
		"payment_type",
		"debtor_account_id",
		"creditor_account_number",
		"creditor_bank_code",
		"creditor_name",
		"amount_cents",
		"currency_code",
		"exchange_rate",
		"equivalent_ksh_cents",
		"charges_cents",
		"charge_type",
		"value_date",
		"payment_purpose",
		"remittance_info",
		"channel",
		"status",
		"submitted_at",
		"settled_at",
		"returned_at",
		"rejection_code",
		"rejection_reason",
		"uetr",
		"authorization_code",
		"batch_id",
		"sanctions_checked",
		"aml_flagged",
		"created_at",
		"updated_at",
	]
	search_columns = [
		"payment_reference",
		"creditor_name",
		"creditor_account_number",
		"status",
		"payment_type",
	]
	order_columns = [
		"payment_reference",
		"value_date",
		"created_at",
		"amount_cents",
		"status",
	]

	# No add/edit — orders are created via PaymentsService
	can_add = False
	can_edit = False
	can_delete = False

	label_columns = {
		"payment_reference": _("Reference"),
		"payment_type": _("Type"),
		"creditor_name": _("Beneficiary"),
		"creditor_account_number": _("Beneficiary Account"),
		"creditor_bank_code": _("Bank Code"),
		"amount_cents": _("Amount (cents)"),
		"currency_code": _("Currency"),
		"exchange_rate": _("FX Rate"),
		"equivalent_ksh_cents": _("KES Equivalent (cents)"),
		"charges_cents": _("Charges (cents)"),
		"charge_type": _("Charge Type"),
		"value_date": _("Value Date"),
		"payment_purpose": _("Purpose"),
		"remittance_info": _("Remittance Info"),
		"channel": _("Channel"),
		"status": _("Status"),
		"submitted_at": _("Submitted At"),
		"settled_at": _("Settled At"),
		"returned_at": _("Returned At"),
		"rejection_code": _("Rejection Code"),
		"rejection_reason": _("Rejection Reason"),
		"uetr": _("UETR"),
		"authorization_code": _("Auth Code"),
		"batch_id": _("Batch"),
		"sanctions_checked": _("Sanctions Checked"),
		"aml_flagged": _("AML Flagged"),
		"created_at": _("Created"),
		"updated_at": _("Updated"),
	}

	formatters_columns = {
		"amount_cents": currency_widget(_currency),
		"equivalent_ksh_cents": currency_widget(_currency),
		"charges_cents": currency_widget(_currency),
		"status": status_badge,
		"created_at": datetime_widget(),
		"submitted_at": datetime_widget(),
		"settled_at": datetime_widget(),
	}

	@expose("/cancel/<string:pk>", methods=["POST"])
	@has_access
	def cancel_order(self, pk: str) -> Any:
		"""Cancel a PENDING/VALIDATED payment via the service layer."""
		from .services import PaymentsService, PaymentImmutableError, PaymentNotFoundError
		from pgappforge.security import current_user  # type: ignore[attr-defined]
		session = _get_session()
		if session is None:
			abort(500, "Database session unavailable")

		# Derive tenant_id from the authenticated session — never from form data (IDOR)
		tenant_id = (
			getattr(current_user, "tenant_id", None)
			or current_app.config.get("PY_DEFAULT_TENANT", "default")
		)
		cancelled_by = request.form.get("cancelled_by", "ops_user")
		reason = request.form.get("reason", "")

		try:
			svc = PaymentsService(session, tenant_id=tenant_id)
			svc.cancel_payment(pk, cancelled_by=cancelled_by, cancellation_reason=reason)
			session.commit()
			return jsonify({"status": "cancelled", "payment_order_id": pk})
		except PaymentNotFoundError as exc:
			abort(404, str(exc))
		except PaymentImmutableError as exc:
			abort(409, str(exc))
		except Exception as exc:
			session.rollback()
			log.exception("cancel_order failed: %s", exc)
			abort(500, str(exc))


# ---------------------------------------------------------------------------
# PaymentBatchView
# ---------------------------------------------------------------------------

class PaymentBatchView(ModelView):
	"""CRUD view for ACH/EFT payment batches."""

	datamodel = SQLAInterface(PaymentBatch)

	list_title = _("Payment Batches")
	show_title = _("Payment Batch")

	list_columns = [
		"batch_number",
		"batch_type",
		"value_date",
		"total_payments",
		"total_amount_cents",
		"status",
		"submitted_at",
	]
	show_columns = [
		"batch_number",
		"batch_type",
		"value_date",
		"currency_code",
		"total_payments",
		"total_amount_cents",
		"accepted_count",
		"rejected_count",
		"status",
		"submitted_at",
		"clearing_reference",
		"created_at",
		"updated_at",
	]
	add_columns = [
		"batch_type",
		"value_date",
		"currency_code",
	]
	edit_columns = [
		"clearing_reference",
	]
	search_columns = ["batch_number", "batch_type", "status"]
	order_columns = ["batch_number", "value_date", "created_at", "status"]

	label_columns = {
		"batch_number": _("Batch Number"),
		"batch_type": _("Type"),
		"value_date": _("Value Date"),
		"currency_code": _("Currency"),
		"total_payments": _("# Orders"),
		"total_amount_cents": _("Total Amount (cents)"),
		"accepted_count": _("Accepted"),
		"rejected_count": _("Rejected"),
		"status": _("Status"),
		"submitted_at": _("Submitted At"),
		"clearing_reference": _("Clearing Reference"),
		"created_at": _("Created"),
		"updated_at": _("Updated"),
	}

	formatters_columns = {
		"total_amount_cents": currency_widget(_currency),
		"status": status_badge,
		"submitted_at": datetime_widget(),
		"created_at": datetime_widget(),
	}

	add_form_extra_fields = {
		"batch_type": select2_widget(
			choices=[
				("ACH_CREDIT", "ACH Credit"),
				("ACH_DEBIT", "ACH Debit"),
				("EFT", "EFT"),
				("RTGS", "RTGS"),
			],
		),
	}

	@expose("/generate-pain001/<string:pk>", methods=["POST"])
	@has_access
	def generate_pain001(self, pk: str) -> Any:
		"""Generate ISO 20022 PAIN.001 XML for a batch."""
		from .services import PaymentsService
		from pgappforge.security import current_user  # type: ignore[attr-defined]
		session = _get_session()
		if session is None:
			abort(500, "Database session unavailable")

		# Derive tenant_id from authenticated session — never from form data (IDOR)
		tenant_id = (
			getattr(current_user, "tenant_id", None)
			or current_app.config.get("PY_DEFAULT_TENANT", "default")
		)
		try:
			svc = PaymentsService(session, tenant_id=tenant_id)
			xml = svc.generate_pain001(pk)
			session.commit()
			return current_app.response_class(
				xml,
				mimetype="application/xml",
				headers={"Content-Disposition": f"attachment; filename=pain001_{pk}.xml"},
			)
		except Exception as exc:
			session.rollback()
			log.exception("generate_pain001 failed: %s", exc)
			abort(500, str(exc))

	@expose("/submit/<string:pk>", methods=["POST"])
	@has_access
	def submit_batch(self, pk: str) -> Any:
		"""Submit a DRAFT/VALIDATED/AUTHORIZED batch to the clearing rail."""
		from .services import PaymentsService, PaymentImmutableError, RailNotAvailableError
		from pgappforge.security import current_user  # type: ignore[attr-defined]
		session = _get_session()
		if session is None:
			abort(500, "Database session unavailable")

		tenant_id = (
			getattr(current_user, "tenant_id", None)
			or current_app.config.get("PY_DEFAULT_TENANT", "default")
		)
		try:
			svc = PaymentsService(session, tenant_id=tenant_id)
			batch = svc.submit_batch(pk, actor_id=getattr(current_user, "username", "ops_user"))
			session.commit()
			return jsonify({"status": batch.status, "batch_id": pk})
		except PaymentImmutableError as exc:
			abort(409, str(exc))
		except RailNotAvailableError as exc:
			abort(422, str(exc))
		except Exception as exc:
			session.rollback()
			log.exception("submit_batch failed: %s", exc)
			abort(500, str(exc))


# ---------------------------------------------------------------------------
# StandingOrderView
# ---------------------------------------------------------------------------

class StandingOrderView(ModelView):
	"""CRUD view for recurring standing orders."""

	datamodel = SQLAInterface(PayStandingOrder)

	list_title = _("Standing Orders")
	show_title = _("Standing Order")

	list_columns = [
		"reference_number",
		"creditor_name",
		"amount_cents",
		"frequency",
		"next_execution_date",
		"status",
		"total_executed",
	]
	show_columns = [
		"reference_number",
		"debtor_account_id",
		"creditor_account_number",
		"creditor_name",
		"amount_cents",
		"frequency",
		"execution_day",
		"start_date",
		"end_date",
		"next_execution_date",
		"payment_purpose",
		"total_executed",
		"total_failed",
		"status",
		"last_executed_at",
		"created_at",
		"updated_at",
	]
	add_columns = [
		"debtor_account_id",
		"creditor_account_number",
		"creditor_name",
		"amount_cents",
		"frequency",
		"execution_day",
		"start_date",
		"end_date",
		"payment_purpose",
	]
	edit_columns = ["end_date", "payment_purpose"]
	search_columns = ["reference_number", "creditor_name", "status", "frequency"]
	order_columns = ["reference_number", "next_execution_date", "created_at"]

	label_columns = {
		"reference_number": _("Reference"),
		"debtor_account_id": _("Debtor Account"),
		"creditor_account_number": _("Beneficiary Account"),
		"creditor_name": _("Beneficiary"),
		"amount_cents": _("Amount (cents)"),
		"frequency": _("Frequency"),
		"execution_day": _("Day of Month"),
		"start_date": _("Start Date"),
		"end_date": _("End Date"),
		"next_execution_date": _("Next Execution"),
		"payment_purpose": _("Purpose"),
		"total_executed": _("Executions"),
		"total_failed": _("Failed"),
		"status": _("Status"),
		"last_executed_at": _("Last Executed"),
		"created_at": _("Created"),
	}

	formatters_columns = {
		"amount_cents": currency_widget(_currency),
		"status": status_badge,
		"last_executed_at": datetime_widget(),
		"created_at": datetime_widget(),
	}

	add_form_extra_fields = {
		"frequency": select2_widget(
			choices=[
				("WEEKLY", "Weekly"),
				("MONTHLY", "Monthly"),
				("QUARTERLY", "Quarterly"),
				("ANNUALLY", "Annually"),
				("SPECIFIC_DATES", "Specific Dates"),
			],
		),
	}

	@expose("/pause/<string:pk>", methods=["POST"])
	@has_access
	def pause(self, pk: str) -> Any:
		"""Pause an ACTIVE standing order via the service layer."""
		from .services import PaymentsService, PaymentNotFoundError
		from pgappforge.security import current_user  # type: ignore[attr-defined]
		session = _get_session()
		if session is None:
			abort(500, "Database session unavailable")

		tenant_id = (
			getattr(current_user, "tenant_id", None)
			or current_app.config.get("PY_DEFAULT_TENANT", "default")
		)
		paused_by = getattr(current_user, "username", "ops_user")
		try:
			svc = PaymentsService(session, tenant_id=tenant_id)
			so = svc.pause_standing_order(pk, paused_by=paused_by)
			session.commit()
			return jsonify({"status": so.status, "standing_order_id": pk})
		except PaymentNotFoundError as exc:
			abort(404, str(exc))
		except AssertionError as exc:
			abort(409, str(exc))
		except Exception as exc:
			session.rollback()
			log.exception("pause_standing_order failed: %s", exc)
			abort(500, str(exc))

	@expose("/resume/<string:pk>", methods=["POST"])
	@has_access
	def resume(self, pk: str) -> Any:
		"""Resume a PAUSED standing order via the service layer."""
		from .services import PaymentsService, PaymentNotFoundError
		from pgappforge.security import current_user  # type: ignore[attr-defined]
		session = _get_session()
		if session is None:
			abort(500, "Database session unavailable")

		tenant_id = (
			getattr(current_user, "tenant_id", None)
			or current_app.config.get("PY_DEFAULT_TENANT", "default")
		)
		resumed_by = getattr(current_user, "username", "ops_user")
		try:
			svc = PaymentsService(session, tenant_id=tenant_id)
			so = svc.resume_standing_order(pk, resumed_by=resumed_by)
			session.commit()
			return jsonify({"status": so.status, "standing_order_id": pk})
		except PaymentNotFoundError as exc:
			abort(404, str(exc))
		except AssertionError as exc:
			abort(409, str(exc))
		except Exception as exc:
			session.rollback()
			log.exception("resume_standing_order failed: %s", exc)
			abort(500, str(exc))


# ---------------------------------------------------------------------------
# PaymentRailView
# ---------------------------------------------------------------------------

class PaymentRailView(ModelView):
	"""Admin CRUD view for payment rail configuration."""

	datamodel = SQLAInterface(PaymentRail)

	list_title = _("Payment Rails")
	show_title = _("Payment Rail")

	list_columns = [
		"rail_code",
		"rail_name",
		"rail_type",
		"settlement_type",
		"is_active",
	]
	show_columns = [
		"rail_code",
		"rail_name",
		"rail_type",
		"settlement_type",
		"operating_hours",
		"min_amount_cents",
		"max_amount_cents",
		"fee_structure",
		"is_active",
		"created_at",
		"updated_at",
	]
	add_columns = [
		"rail_code",
		"rail_name",
		"rail_type",
		"settlement_type",
		"min_amount_cents",
		"max_amount_cents",
		"is_active",
	]
	edit_columns = [
		"rail_name",
		"settlement_type",
		"min_amount_cents",
		"max_amount_cents",
		"operating_hours",
		"fee_structure",
		"is_active",
	]
	search_columns = ["rail_code", "rail_name", "rail_type"]
	order_columns = ["rail_code", "rail_type"]

	label_columns = {
		"rail_code": _("Rail Code"),
		"rail_name": _("Rail Name"),
		"rail_type": _("Rail Type"),
		"settlement_type": _("Settlement Type"),
		"operating_hours": _("Operating Hours (JSON)"),
		"min_amount_cents": _("Min Amount (cents)"),
		"max_amount_cents": _("Max Amount (cents)"),
		"fee_structure": _("Fee Structure (JSON)"),
		"is_active": _("Active"),
		"created_at": _("Created"),
		"updated_at": _("Updated"),
	}

	formatters_columns = {
		"operating_hours": json_widget(),
		"fee_structure": json_widget(),
		"min_amount_cents": currency_widget(_currency),
		"max_amount_cents": currency_widget(_currency),
		"created_at": datetime_widget(),
	}

	add_form_extra_fields = {
		"rail_type": select2_widget(
			choices=[
				("RTGS", "RTGS"),
				("ACH", "ACH"),
				("MOBILE", "Mobile"),
				("CARD", "Card"),
				("SWIFT", "SWIFT"),
				("CRYPTO", "Crypto"),
			],
		),
		"settlement_type": select2_widget(
			choices=[
				("REAL_TIME", "Real-time"),
				("DEFERRED", "Deferred"),
				("NEXT_DAY", "Next Day"),
			],
		),
	}


# ---------------------------------------------------------------------------
# PaymentsDashboard
# ---------------------------------------------------------------------------

class PaymentsDashboard(BaseView):
	"""Dashboard view for payments volume, rail status, and settlement summary.

	Endpoint: /payments/dashboard/
	"""

	route_base = "/payments"
	default_view = "dashboard"

	@expose("/dashboard/")
	@has_access
	def dashboard(self) -> Any:
		"""Render payments dashboard with daily volume and settlement metrics."""
		from flask import render_template_string
		session = _get_session()
		stats: dict[str, Any] = {}

		if session is not None:
			try:
				stats = self._load_stats(session)
			except Exception as exc:
				log.warning("PaymentsDashboard: stats query failed: %s", exc)

		# Minimal inline template — replace with appbuilder/payments/dashboard.html
		tmpl = """
		<div class="row">
		  <div class="col-sm-12">
		    <h3>Payments Dashboard</h3>
		    <ul>
		      <li>Today's orders: {{ stats.get('today_count', 0) }}</li>
		      <li>Today's volume (KES cents): {{ stats.get('today_volume', 0) }}</li>
		      <li>Settled: {{ stats.get('settled_count', 0) }}</li>
		      <li>Pending/Processing: {{ stats.get('inflight_count', 0) }}</li>
		      <li>Rejected today: {{ stats.get('rejected_count', 0) }}</li>
		    </ul>
		  </div>
		</div>
		"""
		return render_template_string(tmpl, stats=stats)

	def _load_stats(self, session: Any) -> dict[str, Any]:
		from datetime import date as _date
		today = _date.today()
		rows = session.execute(
			sa.select(
				PaymentOrder.status,
				sa.func.count().label("cnt"),
				sa.func.coalesce(sa.func.sum(PaymentOrder.amount_cents), 0).label("vol"),
			)
			.where(sa.func.date(PaymentOrder.created_at) == today)
			.group_by(PaymentOrder.status)
		).all()

		today_count = sum(r.cnt for r in rows)
		today_volume = sum(r.vol for r in rows)
		settled_count = next((r.cnt for r in rows if r.status == "SETTLED"), 0)
		rejected_count = next((r.cnt for r in rows if r.status == "REJECTED"), 0)
		inflight_count = sum(
			r.cnt for r in rows
			if r.status in {"PENDING", "VALIDATED", "AUTHORIZED", "SUBMITTED_TO_SWITCH", "PROCESSING"}
		)
		return {
			"today_count": today_count,
			"today_volume": today_volume,
			"settled_count": settled_count,
			"rejected_count": rejected_count,
			"inflight_count": inflight_count,
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"PaymentOrderView",
	"PaymentBatchView",
	"StandingOrderView",
	"PaymentRailView",
	"PaymentsDashboard",
]
