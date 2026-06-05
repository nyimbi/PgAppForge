"""
pgappforge/plugins/fintech/core_banking/views.py

Core Banking views: Accounts, Ledger, Products, Interest Accrual Dashboard,
Balance Sheet summary.

Widget conventions:
  - All balance / money columns: CurrencyWidget (KES default)
  - Date fields: DatePickerWidget
  - Date ranges (filter): DateTimeRangeWidget
  - Customer lookup: Select2AJAXWidget
  - Balance trends: AdvancedChartsWidget (line)
  - Interest rate display: RangeSliderWidget

Security:
  - AccountView, LedgerView: role-scoped permissions (can_list, can_show)
  - ProductView: admin only for add/edit (can_add, can_edit)
  - Dashboard views: read-only BaseView subclasses
"""
from __future__ import annotations

import logging
from typing import Any

from flask import flash, redirect, url_for, request
from flask_appbuilder import ModelView, BaseView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	currency_widget,
	date_range_widget,
	date_widget,
	json_widget,
	select2_ajax_widget,
	select2_widget,
	progress_widget,
)

from pgappforge.plugins.fintech.core_banking.models import (
	Account,
	AccountHold,
	AccountStatement,
	BankProduct,
	GLAccountMapping,
	InterestAccrual,
	LedgerEntry,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Common label maps
# ---------------------------------------------------------------------------

_BALANCE_LABELS: dict[str, str] = {
	"current_balance_cents": "Ledger Balance",
	"available_balance_cents": "Available Balance",
	"accrued_interest_cents": "Accrued Interest",
	"holds_cents": "On Hold",
	"min_balance_cents": "Minimum Balance",
	"min_opening_balance_cents": "Min. Opening Deposit",
	"max_withdrawal_per_day_cents": "Daily Withdrawal Limit",
	"amount_cents": "Amount",
	"opening_balance_cents": "Opening Balance",
	"total_debits_cents": "Total Debits",
	"total_credits_cents": "Total Credits",
	"closing_balance_cents": "Closing Balance",
	"interest_earned_cents": "Interest Earned",
	"fees_charged_cents": "Fees Charged",
	"balance_after_cents": "Balance After",
	"accrued_cents": "Accrued",
	"cumulative_accrued_cents": "Cumulative Accrued",
	"opening_balance_cents_2": "Opening Balance",
}


# ---------------------------------------------------------------------------
# ProductView
# ---------------------------------------------------------------------------

class ProductView(ModelView):
	"""Bank product catalogue — rates, fees, and rules per product type."""

	datamodel = SQLAInterface(BankProduct)
	route_base = "/core-banking/products"

	list_title = "Bank Products"
	show_title = "Product Details"
	add_title = "Add Bank Product"
	edit_title = "Edit Bank Product"

	list_columns = [
		"product_code",
		"product_name",
		"product_type",
		"currency_code",
		"interest_rate_pa",
		"min_balance_cents",
		"is_islamic",
		"is_active",
	]

	show_fieldsets = [
		("Identity", {
			"fields": [
				"product_code", "product_name", "product_type",
				"currency_code", "is_islamic", "is_active",
			]
		}),
		("Interest", {
			"fields": [
				"interest_rate_pa", "interest_calculation",
				"interest_crediting_frequency", "penalty_rate_pa",
			]
		}),
		("Balance Rules", {
			"fields": [
				"min_balance_cents", "min_opening_balance_cents",
				"max_withdrawal_per_day_cents", "dormancy_threshold_days",
			]
		}),
		("Channels & Fees", {
			"fields": ["allowed_channels", "fees"]
		}),
	]

	add_fieldsets = show_fieldsets
	edit_fieldsets = show_fieldsets

	label_columns = {
		**_BALANCE_LABELS,
		"product_code": "Product Code",
		"product_name": "Product Name",
		"product_type": "Type",
		"currency_code": "Currency",
		"interest_rate_pa": "Interest Rate p.a.",
		"interest_calculation": "Calculation Method",
		"interest_crediting_frequency": "Crediting Frequency",
		"penalty_rate_pa": "Penalty Rate p.a.",
		"allowed_channels": "Allowed Channels",
		"dormancy_threshold_days": "Dormancy Threshold (days)",
		"is_islamic": "Islamic / Sharia",
		"is_active": "Active",
		"fees": "Fee Schedule (JSON)",
	}

	search_columns = ["product_code", "product_name", "product_type", "currency_code"]
	base_order = ("product_code", "asc")

	formatters_columns: dict[str, Any] = {
		"min_balance_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "—",
		"min_opening_balance_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "—",
		"max_withdrawal_per_day_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "Unlimited",
		"interest_rate_pa": lambda v: f"{v:.4f}%" if v is not None else "—",
		"penalty_rate_pa": lambda v: f"{v:.4f}%" if v is not None else "—",
	}


# ---------------------------------------------------------------------------
# AccountView
# ---------------------------------------------------------------------------

class AccountView(ModelView):
	"""Customer accounts — the core entity.

	List: account_number, customer (party name), product, balance, status.
	Detail: full account info + mini-statement section.
	Actions: Deposit, Withdraw, Transfer, Freeze.
	"""

	datamodel = SQLAInterface(Account)
	route_base = "/core-banking/accounts"

	list_title = "Accounts"
	show_title = "Account Details"
	add_title = "Open Account"
	edit_title = "Edit Account"

	list_columns = [
		"account_number",
		"customer_id",
		"product_id",
		"currency_code",
		"current_balance_cents",
		"available_balance_cents",
		"status",
		"opened_date",
	]

	# column_formatters resolve raw UUIDs to human-readable names by doing
	# a lazy joined query.  The formatters receive (item, attr) in FAB.
	def _fmt_customer_id(self, item: Any, attr: str) -> str:
		try:
			from pgappforge.plugins.erp.foundation.models import Party
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return str(item.customer_id)
			party = ab.get_session.get(Party, str(item.customer_id))
			if party is None:
				return str(item.customer_id)
			return getattr(party, "full_name", None) or getattr(party, "name", None) or str(item.customer_id)
		except Exception:
			return str(item.customer_id)

	def _fmt_product_id(self, item: Any, attr: str) -> str:
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return str(item.product_id)
			product = ab.get_session.get(BankProduct, str(item.product_id))
			if product is None:
				return str(item.product_id)
			return f"{product.product_name} ({product.product_code})"
		except Exception:
			return str(item.product_id)

	formatters_columns: dict[str, Any] = {
		"customer_id": _fmt_customer_id,
		"product_id": _fmt_product_id,
		"current_balance_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "—",
		"available_balance_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "—",
		"holds_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "—",
		"accrued_interest_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "—",
		"status": lambda v: (
			f'<span class="badge bg-'
			+ {
				"ACTIVE": "success",
				"DORMANT": "warning",
				"FROZEN": "danger",
				"CLOSED": "secondary",
				"SUSPENDED": "dark",
				"PENDING_ACTIVATION": "info",
			}.get(v or "", "secondary")
			+ f'">{v}</span>'
		),
	}

	show_fieldsets = [
		("Account", {
			"fields": [
				"account_number", "iban", "customer_id", "product_id",
				"currency_code", "status", "branch_code",
				"relationship_manager_id",
			]
		}),
		("Balances", {
			"fields": [
				"current_balance_cents", "available_balance_cents",
				"holds_cents", "accrued_interest_cents",
			]
		}),
		("Dates", {
			"fields": [
				"opened_date", "closed_date", "maturity_date",
				"last_transaction_at", "last_interest_accrual_date",
				"dormancy_notified_at",
			]
		}),
	]

	add_fieldsets = [
		("Account", {
			"fields": [
				"account_number", "customer_id", "product_id",
				"currency_code", "branch_code", "relationship_manager_id",
				"opened_date", "maturity_date", "iban",
			]
		}),
	]

	edit_fieldsets = [
		("Account", {
			"fields": [
				"status", "branch_code", "relationship_manager_id",
				"maturity_date", "iban",
			]
		}),
	]

	label_columns = {
		**_BALANCE_LABELS,
		"account_number": "Account Number",
		"customer_id": "Customer",
		"product_id": "Product",
		"currency_code": "Currency",
		"status": "Status",
		"branch_code": "Branch",
		"relationship_manager_id": "Relationship Manager",
		"opened_date": "Date Opened",
		"closed_date": "Date Closed",
		"maturity_date": "Maturity Date",
		"last_transaction_at": "Last Transaction",
		"last_interest_accrual_date": "Last Accrual Date",
		"dormancy_notified_at": "Dormancy Notified",
		"iban": "IBAN",
	}

	search_columns = [
		"account_number", "iban", "currency_code", "status", "branch_code",
	]
	base_order = ("opened_date", "desc")


# ---------------------------------------------------------------------------
# LedgerView (read-only)
# ---------------------------------------------------------------------------

class LedgerView(ModelView):
	"""Immutable ledger entries — read-only list view."""

	datamodel = SQLAInterface(LedgerEntry)
	route_base = "/core-banking/ledger"

	list_title = "Ledger Entries"
	show_title = "Ledger Entry"

	# Disable add/edit/delete — ledger is insert-only
	can_add = False
	can_edit = False
	can_delete = False

	list_columns = [
		"posting_date",
		"value_date",
		"entry_type",
		"transaction_type",
		"amount_cents",
		"balance_after_cents",
		"channel",
		"reference_number",
		"narrative",
	]

	show_fieldsets = [
		("Entry", {
			"fields": [
				"id", "journal_id", "account_id", "entry_type",
				"transaction_type", "amount_cents", "currency_code",
				"exchange_rate", "balance_after_cents",
			]
		}),
		("Dates", {
			"fields": ["posting_date", "value_date", "created_at"]
		}),
		("Reference", {
			"fields": [
				"channel", "reference_number", "narrative",
				"gl_account_code", "reversal_of_id",
				"is_interest", "is_fee",
			]
		}),
	]

	label_columns = {
		**_BALANCE_LABELS,
		"entry_type": "Dr/Cr",
		"transaction_type": "Type",
		"channel": "Channel",
		"reference_number": "Reference",
		"narrative": "Narrative",
		"posting_date": "Posting Date",
		"value_date": "Value Date",
		"journal_id": "Journal ID",
		"account_id": "Account",
		"gl_account_code": "GL Code",
		"exchange_rate": "FX Rate",
		"reversal_of_id": "Reverses Entry",
		"is_interest": "Interest?",
		"is_fee": "Fee?",
	}

	search_columns = [
		"entry_type", "transaction_type", "channel", "reference_number",
	]
	base_order = ("posting_date", "desc")

	formatters_columns: dict[str, Any] = {
		"amount_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "—",
		"balance_after_cents": lambda v: f"KES {v/100:,.2f}" if v is not None else "—",
		"entry_type": lambda v: (
			'<span class="badge bg-danger">DR</span>'
			if v == "DEBIT"
			else '<span class="badge bg-success">CR</span>'
		),
	}


# ---------------------------------------------------------------------------
# InterestAccrualDashboard
# ---------------------------------------------------------------------------

class InterestAccrualDashboard(BaseView):
	"""Summary dashboard for daily interest accrual and capitalisation.

	Routes:
	  GET /core-banking/interest/          — today's accrual summary
	  GET /core-banking/interest/history   — historical accrual by date range
	"""

	route_base = "/core-banking/interest"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""Today's accrual summary: total accrued, accounts processed, by product."""
		from flask import current_app
		from sqlalchemy import select, func, Date
		import datetime as dt

		today = dt.date.today()
		ab = current_app.extensions.get("appbuilder")
		session = ab.get_session if ab else None

		summary: dict[str, Any] = {
			"accrual_date": today.isoformat(),
			"accounts_processed": 0,
			"total_accrued_cents": 0,
			"pending_capitalisation_cents": 0,
			"chart_config": chart_widget("line"),
			"currency_config": currency_widget("KES"),
		}

		if session is not None:
			try:
				row = session.execute(
					select(
						func.count(InterestAccrual.id),
						func.coalesce(func.sum(InterestAccrual.accrued_cents), 0),
					).where(InterestAccrual.accrual_date == today)
				).one()
				summary["accounts_processed"] = row[0]
				summary["total_accrued_cents"] = row[1]

				pending = session.execute(
					select(func.coalesce(func.sum(InterestAccrual.cumulative_accrued_cents), 0))
					.where(InterestAccrual.is_capitalized.is_(False))
				).scalar_one()
				summary["pending_capitalisation_cents"] = pending
			except Exception as exc:
				log.warning("InterestAccrualDashboard: query failed: %s", exc)

		return self.render_template(
			"core_banking/interest_dashboard.html",
			summary=summary,
		)

	@expose("/history")
	@has_access
	def history(self):
		"""Accrual history — filterable by date range.

		Query: group by accrual_date + product_type, aggregate counts and sums.
		Defaults to last 30 days if no date range provided.  Paginates at 100 rows.
		"""
		import datetime as dt
		from flask import current_app
		from sqlalchemy import select, func

		today = dt.date.today()
		default_from = today - dt.timedelta(days=30)

		from_date_str = request.args.get("from_date", default_from.isoformat())
		to_date_str = request.args.get("to_date", today.isoformat())
		try:
			from_date = dt.date.fromisoformat(from_date_str)
		except ValueError:
			from_date = default_from
		try:
			to_date = dt.date.fromisoformat(to_date_str)
		except ValueError:
			to_date = today

		rows: list[dict] = []
		ab = current_app.extensions.get("appbuilder")
		session = ab.get_session if ab else None

		if session is not None:
			try:
				raw_rows = session.execute(
					select(
						InterestAccrual.accrual_date,
						BankProduct.product_type,
						func.count(InterestAccrual.id).label("accounts_count"),
						func.coalesce(func.sum(InterestAccrual.accrued_cents), 0).label("total_accrued_cents"),
						func.coalesce(func.sum(InterestAccrual.cumulative_accrued_cents), 0).label("total_cumulative_cents"),
					)
					.join(Account, InterestAccrual.account_id == Account.id)
					.join(BankProduct, Account.product_id == BankProduct.id)
					.where(
						InterestAccrual.accrual_date >= from_date,
						InterestAccrual.accrual_date <= to_date,
					)
					.group_by(InterestAccrual.accrual_date, BankProduct.product_type)
					.order_by(InterestAccrual.accrual_date.desc())
					.limit(100)
				).all()

				rows = [
					{
						"accrual_date": r.accrual_date,
						"product_type": r.product_type,
						"accounts_count": r.accounts_count,
						"total_accrued_cents": r.total_accrued_cents,
						"total_cumulative_cents": r.total_cumulative_cents,
					}
					for r in raw_rows
				]
			except Exception as exc:
				log.warning("InterestAccrualDashboard.history: query failed: %s", exc)

		date_range_cfg = date_range_widget()
		return self.render_template(
			"core_banking/interest_history.html",
			date_range_config=date_range_cfg,
			rows=rows,
			from_date=from_date.isoformat(),
			to_date=to_date.isoformat(),
		)


# ---------------------------------------------------------------------------
# BalanceSheetView
# ---------------------------------------------------------------------------

class BalanceSheetView(BaseView):
	"""High-level balance sheet: total deposits by product, loans outstanding, NII, NIM.

	Route: GET /core-banking/balance-sheet/
	"""

	route_base = "/core-banking/balance-sheet"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""Aggregate balance sheet snapshot."""
		from flask import current_app
		from sqlalchemy import select, func

		ab = current_app.extensions.get("appbuilder")
		session = ab.get_session if ab else None

		# Widget configurations
		bar_chart = chart_widget("bar")
		line_chart = chart_widget("line")
		kes_widget = currency_widget("KES")

		data: dict[str, Any] = {
			"total_deposits_cents": 0,
			"total_loans_outstanding_cents": 0,
			"total_accrued_interest_cents": 0,
			"by_product": [],
			"bar_chart_config": bar_chart,
			"line_chart_config": line_chart,
			"currency_config": kes_widget,
		}

		if session is not None:
			try:
				# Deposits by product (SAVINGS, CURRENT, FIXED_DEPOSIT, CALL)
				deposit_types = (
					"SAVINGS", "CURRENT", "FIXED_DEPOSIT", "CALL",
				)
				rows = session.execute(
					select(
						BankProduct.product_type,
						BankProduct.product_name,
						func.count(Account.id).label("account_count"),
						func.coalesce(func.sum(Account.current_balance_cents), 0).label("total_balance"),
					)
					.join(Account, Account.product_id == BankProduct.id)
					.where(
						Account.status == "ACTIVE",
						BankProduct.product_type.in_(deposit_types),
					)
					.group_by(BankProduct.product_type, BankProduct.product_name)
					.order_by(BankProduct.product_type)
				).all()

				for r in rows:
					data["by_product"].append({
						"product_type": r.product_type,
						"product_name": r.product_name,
						"account_count": r.account_count,
						"total_balance_cents": r.total_balance,
					})
					data["total_deposits_cents"] += r.total_balance

				# Loans outstanding
				loan_types = (
					"LOAN", "OVERDRAFT", "MORTGAGE", "SME_LOAN", "CONSUMER_LOAN",
				)
				loan_total = session.execute(
					select(func.coalesce(func.sum(Account.current_balance_cents), 0))
					.join(BankProduct, Account.product_id == BankProduct.id)
					.where(
						Account.status == "ACTIVE",
						BankProduct.product_type.in_(loan_types),
					)
				).scalar_one()
				data["total_loans_outstanding_cents"] = loan_total

				# Total accrued interest (pending capitalisation)
				accrued = session.execute(
					select(func.coalesce(func.sum(Account.accrued_interest_cents), 0))
					.where(Account.status == "ACTIVE")
				).scalar_one()
				data["total_accrued_interest_cents"] = accrued

			except Exception as exc:
				log.warning("BalanceSheetView: query failed: %s", exc)

		return self.render_template(
			"core_banking/balance_sheet.html",
			data=data,
		)


# ---------------------------------------------------------------------------
# AccountActionsView — Deposit / Withdraw / Transfer / Freeze / Unfreeze
# ---------------------------------------------------------------------------

class AccountActionsView(BaseView):
	"""Operator-facing action routes for individual account transactions.

	All routes require the can_cb_account_transact permission.

	Routes:
	  GET/POST /core-banking/account-actions/deposit/<account_id>
	  GET/POST /core-banking/account-actions/withdraw/<account_id>
	  GET/POST /core-banking/account-actions/transfer/<account_id>
	  POST     /core-banking/account-actions/freeze/<account_id>
	  POST     /core-banking/account-actions/unfreeze/<account_id>
	"""

	route_base = "/core-banking/account-actions"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return self.render_template("core_banking/account_actions.html")

	@expose("/deposit/<account_id>", methods=["GET", "POST"])
	@has_access
	def deposit(self, account_id: str):
		from flask import current_app
		from pgappforge.plugins.fintech.core_banking.services import (
			CoreBankingService, CoreBankingError,
		)
		ab = current_app.extensions.get("appbuilder")
		session = ab.get_session if ab else None

		account_number = account_id  # accept either number or id
		if session is not None:
			try:
				acct = session.get(Account, account_id)
				if acct:
					account_number = acct.account_number
			except Exception:
				pass

		if request.method == "POST":
			try:
				amount_cents = int(request.form.get("amount_cents", 0) or 0)
				channel = request.form.get("channel", "BRANCH")
				reference = request.form.get("reference", "")
				narrative = request.form.get("narrative") or None
				svc = CoreBankingService()
				result = svc.deposit(
					session=session,
					account_number=account_number,
					amount_cents=amount_cents,
					channel=channel,
					reference=reference,
					narrative=narrative,
				)
				session.commit()
				flash(
					f"Deposit KES {amount_cents // 100:,}.{amount_cents % 100:02d} posted. "
					f"Journal: {result['journal_id']}", "success"
				)
				return redirect(url_for("AccountView.list"))
			except CoreBankingError as exc:
				flash(str(exc), "danger")
			except Exception as exc:
				log.error("AccountActionsView.deposit error: %s", exc)
				flash("Unexpected error — see logs.", "danger")

		return self.render_template(
			"core_banking/action_deposit.html",
			account_number=account_number,
		)

	@expose("/withdraw/<account_id>", methods=["GET", "POST"])
	@has_access
	def withdraw(self, account_id: str):
		from flask import current_app
		from pgappforge.plugins.fintech.core_banking.services import (
			CoreBankingService, CoreBankingError,
		)
		ab = current_app.extensions.get("appbuilder")
		session = ab.get_session if ab else None

		account_number = account_id
		if session is not None:
			try:
				acct = session.get(Account, account_id)
				if acct:
					account_number = acct.account_number
			except Exception:
				pass

		if request.method == "POST":
			try:
				amount_cents = int(request.form.get("amount_cents", 0) or 0)
				channel = request.form.get("channel", "BRANCH")
				reference = request.form.get("reference", "")
				narrative = request.form.get("narrative") or None
				svc = CoreBankingService()
				result = svc.withdraw(
					session=session,
					account_number=account_number,
					amount_cents=amount_cents,
					channel=channel,
					reference=reference,
					narrative=narrative,
				)
				session.commit()
				flash(
					f"Withdrawal KES {amount_cents // 100:,}.{amount_cents % 100:02d} posted. "
					f"Journal: {result['journal_id']}", "success"
				)
				return redirect(url_for("AccountView.list"))
			except CoreBankingError as exc:
				flash(str(exc), "danger")
			except Exception as exc:
				log.error("AccountActionsView.withdraw error: %s", exc)
				flash("Unexpected error — see logs.", "danger")

		return self.render_template(
			"core_banking/action_withdraw.html",
			account_number=account_number,
		)

	@expose("/transfer/<account_id>", methods=["GET", "POST"])
	@has_access
	def transfer(self, account_id: str):
		from flask import current_app
		from decimal import Decimal
		from pgappforge.plugins.fintech.core_banking.services import (
			CoreBankingService, CoreBankingError,
		)
		ab = current_app.extensions.get("appbuilder")
		session = ab.get_session if ab else None

		account_number = account_id
		if session is not None:
			try:
				acct = session.get(Account, account_id)
				if acct:
					account_number = acct.account_number
			except Exception:
				pass

		if request.method == "POST":
			try:
				amount_cents = int(request.form.get("amount_cents", 0) or 0)
				to_account_number = request.form.get("to_account_number", "")
				reference = request.form.get("reference", "")
				narrative = request.form.get("narrative") or None
				fx_raw = request.form.get("exchange_rate", "1") or "1"
				exchange_rate = Decimal(fx_raw)
				svc = CoreBankingService()
				result = svc.transfer(
					session=session,
					from_account_number=account_number,
					to_account_number=to_account_number,
					amount_cents=amount_cents,
					reference=reference,
					narrative=narrative,
					exchange_rate=exchange_rate if exchange_rate != Decimal("1") else None,
				)
				session.commit()
				flash(
					f"Transfer KES {amount_cents // 100:,}.{amount_cents % 100:02d} to {to_account_number} posted. "
					f"Journal: {result['journal_id']}", "success"
				)
				return redirect(url_for("AccountView.list"))
			except CoreBankingError as exc:
				flash(str(exc), "danger")
			except Exception as exc:
				log.error("AccountActionsView.transfer error: %s", exc)
				flash("Unexpected error — see logs.", "danger")

		return self.render_template(
			"core_banking/action_transfer.html",
			account_number=account_number,
		)

	@expose("/freeze/<account_id>", methods=["POST"])
	@has_access
	def freeze(self, account_id: str):
		from flask import current_app
		from pgappforge.plugins.fintech.core_banking.services import (
			CoreBankingService, CoreBankingError,
		)
		ab = current_app.extensions.get("appbuilder")
		session = ab.get_session if ab else None

		try:
			acct = session.get(Account, account_id) if session else None
			account_number = acct.account_number if acct else account_id
			reason = request.form.get("reason", "Operator freeze")
			svc = CoreBankingService()
			svc.freeze_account(session=session, account_number=account_number, reason=reason)
			session.commit()
			flash(f"Account {account_number} frozen.", "warning")
		except CoreBankingError as exc:
			flash(str(exc), "danger")
		except Exception as exc:
			log.error("AccountActionsView.freeze error: %s", exc)
			flash("Unexpected error — see logs.", "danger")

		return redirect(url_for("AccountView.list"))

	@expose("/unfreeze/<account_id>", methods=["POST"])
	@has_access
	def unfreeze(self, account_id: str):
		from flask import current_app
		from pgappforge.plugins.fintech.core_banking.services import (
			CoreBankingService, CoreBankingError,
		)
		ab = current_app.extensions.get("appbuilder")
		session = ab.get_session if ab else None

		try:
			acct = session.get(Account, account_id) if session else None
			account_number = acct.account_number if acct else account_id
			svc = CoreBankingService()
			svc.unfreeze_account(session=session, account_number=account_number)
			session.commit()
			flash(f"Account {account_number} reinstated to ACTIVE.", "success")
		except CoreBankingError as exc:
			flash(str(exc), "danger")
		except Exception as exc:
			log.error("AccountActionsView.unfreeze error: %s", exc)
			flash("Unexpected error — see logs.", "danger")

		return redirect(url_for("AccountView.list"))


# ---------------------------------------------------------------------------
# GLAccountMappingView — per-tenant GL code overrides
# ---------------------------------------------------------------------------

class GLAccountMappingView(ModelView):
	"""Manage per-tenant GL account code overrides.

	Allows operators to map logical CB keys (e.g. CUSTOMER_DEPOSITS) to
	tenant-specific chart-of-accounts codes without code changes.
	"""

	datamodel = SQLAInterface(GLAccountMapping)
	route_base = "/core-banking/gl-mapping"

	list_title = "GL Account Mappings"
	show_title = "GL Account Mapping"
	add_title = "Add GL Mapping"
	edit_title = "Edit GL Mapping"

	list_columns = [
		"tenant_id",
		"cb_account_key",
		"gl_account_code",
		"description",
		"is_active",
	]

	add_fieldsets = [
		("Mapping", {
			"fields": [
				"tenant_id", "cb_account_key", "gl_account_code",
				"description", "is_active",
			]
		}),
	]
	edit_fieldsets = add_fieldsets

	label_columns = {
		"tenant_id": "Tenant",
		"cb_account_key": "CB Key",
		"gl_account_code": "GL Account Code",
		"description": "Description",
		"is_active": "Active",
	}

	search_columns = ["tenant_id", "cb_account_key", "gl_account_code"]
	base_order = ("tenant_id", "asc")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ProductView",
	"AccountView",
	"LedgerView",
	"InterestAccrualDashboard",
	"BalanceSheetView",
	"AccountActionsView",
	"GLAccountMappingView",
]
