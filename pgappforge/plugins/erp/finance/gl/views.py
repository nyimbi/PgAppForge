"""
pgappforge/plugins/erp/finance/gl/views.py

Flask views for the General Ledger plugin.

Views registered:
  GLAccountView          — CRUD for Chart of Accounts
  GLCostCenterView       — CRUD for Cost Centres
  GLFiscalYearView       — CRUD for Fiscal Years
  GLPeriodView           — CRUD + close-period action
  GLJournalBatchView     — CRUD + post/submit/approve workflow
  GLJournalEntryView     — Detail + reverse action
  GLBudgetView           — CRUD for Budget entries
  GLAccountBalanceView   — Read-only balance viewer
  GLReportView           — 3 canned reports: Trial Balance, Budget vs Actual,
                           Account Ledger (transaction history)

All mutating endpoints POST JSON and return JSON.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------

def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.finance.gl.services import GLService
	return GLService()


# ---------------------------------------------------------------------------
# GLAccountView
# ---------------------------------------------------------------------------

class GLAccountView(BaseView):
	"""Chart of Accounts CRUD.

	GET  /gl/accounts/                 — list
	GET  /gl/accounts/<code>           — detail (JSON)
	POST /gl/accounts/                 — create
	PUT  /gl/accounts/<code>           — update (metadata only)
	"""

	route_base = "/gl/accounts"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.gl.models import GLAccount
		session = _get_session()
		accounts = session.execute(
			sa.select(GLAccount).order_by(GLAccount.account_code)
		).scalars().all()
		rows = [
			{
				"account_code": a.account_code,
				"account_name": a.account_name,
				"account_type": a.account_type,
				"normal_balance": a.normal_balance,
				"parent_code": a.parent_code,
				"is_posting_account": a.is_posting_account,
				"is_active": a.is_active,
				"currency_code": a.currency_code,
			}
			for a in accounts
		]
		return jsonify(rows)

	@expose("/<string:code>")
	@has_access
	def detail(self, code: str):
		from pgappforge.plugins.erp.finance.gl.models import GLAccount
		session = _get_session()
		acct = session.get(GLAccount, code)
		if acct is None:
			abort(404, f"Account {code!r} not found")
		return jsonify({
			"account_code": acct.account_code,
			"account_name": acct.account_name,
			"account_type": acct.account_type,
			"account_subtype": acct.account_subtype,
			"normal_balance": acct.normal_balance,
			"parent_code": acct.parent_code,
			"is_posting_account": acct.is_posting_account,
			"is_reconciliation_account": acct.is_reconciliation_account,
			"currency_code": acct.currency_code,
			"ifrs_concept": acct.ifrs_concept,
			"gaap_concept": acct.gaap_concept,
			"is_active": acct.is_active,
			"description": acct.description,
			"attributes": acct.attributes,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.gl.models import GLAccount
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("account_code", "account_name", "account_type", "tenant_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		# Set normal_balance default from account_type
		normal_balance_map = {
			"ASSET": "DEBIT",
			"EXPENSE": "DEBIT",
			"LIABILITY": "CREDIT",
			"EQUITY": "CREDIT",
			"REVENUE": "CREDIT",
			"STATISTICAL": "DEBIT",
		}
		acct = GLAccount(
			account_code=data["account_code"],
			tenant_id=data["tenant_id"],
			account_name=data["account_name"],
			account_type=data["account_type"],
			account_subtype=data.get("account_subtype"),
			normal_balance=data.get(
				"normal_balance",
				normal_balance_map.get(data["account_type"], "DEBIT"),
			),
			parent_code=data.get("parent_code"),
			is_posting_account=data.get("is_posting_account", True),
			is_reconciliation_account=data.get("is_reconciliation_account", False),
			currency_code=data.get("currency_code"),
			ifrs_concept=data.get("ifrs_concept"),
			gaap_concept=data.get("gaap_concept"),
			is_active=data.get("is_active", True),
			description=data.get("description"),
			attributes=data.get("attributes", {}),
		)
		session.add(acct)
		session.commit()
		return jsonify({"account_code": acct.account_code, "status": "created"}), 201

	@expose("/<string:code>", methods=["PUT"])
	@has_access
	def update(self, code: str):
		from pgappforge.plugins.erp.finance.gl.models import GLAccount
		session = _get_session()
		acct = session.get(GLAccount, code)
		if acct is None:
			abort(404, f"Account {code!r} not found")
		data = request.get_json(force=True) or {}
		for field in (
			"account_name", "account_subtype", "normal_balance",
			"is_posting_account", "is_reconciliation_account",
			"currency_code", "ifrs_concept", "gaap_concept",
			"is_active", "description", "parent_code",
		):
			if field in data:
				setattr(acct, field, data[field])
		if "attributes" in data:
			acct.attributes = {**(acct.attributes or {}), **data["attributes"]}
		session.commit()
		return jsonify({"account_code": code, "status": "updated"})


# ---------------------------------------------------------------------------
# GLPeriodView
# ---------------------------------------------------------------------------

class GLPeriodView(BaseView):
	"""GL Period CRUD + close-period business action.

	GET  /gl/periods/                  — list
	POST /gl/periods/                  — create
	POST /gl/periods/<id>/close        — close period
	"""

	route_base = "/gl/periods"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.gl.models import GLPeriod
		session = _get_session()
		periods = session.execute(
			sa.select(GLPeriod).order_by(GLPeriod.start_date)
		).scalars().all()
		return jsonify([
			{
				"id": p.id,
				"period_name": p.period_name,
				"period_number": p.period_number,
				"fiscal_year_id": p.fiscal_year_id,
				"start_date": p.start_date.isoformat() if p.start_date else None,
				"end_date": p.end_date.isoformat() if p.end_date else None,
				"status": p.status,
			}
			for p in periods
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.gl.models import GLPeriod
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "fiscal_year_id", "period_number", "start_date", "end_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		period = GLPeriod(
			tenant_id=data["tenant_id"],
			fiscal_year_id=data["fiscal_year_id"],
			period_number=data["period_number"],
			period_name=data.get("period_name"),
			start_date=date.fromisoformat(data["start_date"]),
			end_date=date.fromisoformat(data["end_date"]),
			status="OPEN",
		)
		session.add(period)
		session.commit()
		return jsonify({"period_id": period.id, "status": "created"}), 201

	@expose("/<string:period_id>/close", methods=["POST"])
	@has_access
	def close(self, period_id: str):
		from pgappforge.plugins.erp.finance.gl.services import (
			GLServiceError,
			PeriodHasOpenBatchesError,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		closed_by = data.get("closed_by")
		try:
			result = _svc().close_period(period_id, session, closed_by=closed_by)
			session.commit()
			return jsonify(result)
		except PeriodHasOpenBatchesError as exc:
			return jsonify({"error": str(exc)}), 422
		except GLServiceError as exc:
			return jsonify({"error": str(exc)}), 400


# ---------------------------------------------------------------------------
# GLJournalBatchView
# ---------------------------------------------------------------------------

class GLJournalBatchView(BaseView):
	"""Journal batch workflow.

	GET  /gl/batches/                  — list
	POST /gl/batches/                  — create batch
	POST /gl/batches/<id>/entries      — add journal entry + lines
	POST /gl/batches/<id>/submit       — submit for approval
	POST /gl/batches/<id>/approve      — approve
	POST /gl/batches/<id>/post         — post (validates balance)
	"""

	route_base = "/gl/batches"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.gl.models import GLJournalBatch
		session = _get_session()
		batches = session.execute(
			sa.select(GLJournalBatch).order_by(GLJournalBatch.created_at.desc()).limit(200)
		).scalars().all()
		return jsonify([
			{
				"id": b.id,
				"batch_number": b.batch_number,
				"batch_type": b.batch_type,
				"period_id": b.period_id,
				"status": b.status,
				"total_debits": b.total_debits,
				"total_credits": b.total_credits,
				"is_balanced": b.is_balanced,
			}
			for b in batches
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.gl.models import GLJournalBatch
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "period_id", "batch_number")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		batch = GLJournalBatch(
			tenant_id=data["tenant_id"],
			batch_number=data["batch_number"],
			batch_type=data.get("batch_type", "MANUAL"),
			period_id=data["period_id"],
			description=data.get("description"),
			status="DRAFT",
			total_debits=0,
			total_credits=0,
			is_balanced=False,
		)
		session.add(batch)
		session.commit()
		return jsonify({"batch_id": batch.id, "status": "created"}), 201

	@expose("/<string:batch_id>/entries", methods=["POST"])
	@has_access
	def add_entry(self, batch_id: str):
		"""Add a journal entry + lines to a batch.

		Body: {
		  "posting_date": "2025-01-31",
		  "description": "...",
		  "lines": [
		    {"account_code": "1000", "debit_amount": 100000, "credit_amount": 0,
		     "currency_code": "USD", "fx_rate": 1, "base_debit": 100000,
		     "base_credit": 0, "description": "Cash inflow"},
		    ...
		  ]
		}
		All amounts in integer cents.
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLJournalBatch, GLJournalEntry, GLJournalLine,
		)
		session = _get_session()
		batch = session.get(GLJournalBatch, batch_id)
		if batch is None:
			abort(404)
		if batch.status != "DRAFT":
			return jsonify({"error": f"Batch is {batch.status!r}, not DRAFT"}), 422

		data = request.get_json(force=True) or {}
		lines_data = data.get("lines", [])
		if not lines_data:
			return jsonify({"error": "At least one line required"}), 400

		entry = GLJournalEntry(
			tenant_id=batch.tenant_id,
			batch_id=batch_id,
			entry_type=data.get("entry_type", "MANUAL"),
			posting_date=date.fromisoformat(data["posting_date"]),
			description=data.get("description"),
			source_document_type=data.get("source_document_type"),
			source_document_id=data.get("source_document_id"),
			status="DRAFT",
		)
		session.add(entry)
		session.flush()

		for i, ld in enumerate(lines_data, 1):
			line = GLJournalLine(
				tenant_id=batch.tenant_id,
				entry_id=entry.id,
				line_number=i,
				account_code=ld["account_code"],
				cost_center_code=ld.get("cost_center_code"),
				project_code=ld.get("project_code"),
				debit_amount=int(ld.get("debit_amount", 0)),
				credit_amount=int(ld.get("credit_amount", 0)),
				currency_code=ld.get("currency_code", "USD"),
				fx_rate=ld.get("fx_rate", 1),
				base_debit=int(ld.get("base_debit", ld.get("debit_amount", 0))),
				base_credit=int(ld.get("base_credit", ld.get("credit_amount", 0))),
				description=ld.get("description"),
				reference=ld.get("reference"),
				party_id=ld.get("party_id"),
				tax_code=ld.get("tax_code"),
			)
			session.add(line)
			batch.total_debits += line.base_debit
			batch.total_credits += line.base_credit

		batch.is_balanced = (batch.total_debits == batch.total_credits)
		session.commit()
		return jsonify({"entry_id": entry.id, "is_balanced": batch.is_balanced}), 201

	@expose("/<string:batch_id>/post", methods=["POST"])
	@has_access
	def post(self, batch_id: str):
		from pgappforge.plugins.erp.finance.gl.services import (
			GLServiceError, JournalImbalancedError, PeriodClosedError,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			result = _svc().post_journal(batch_id, session, posted_by=data.get("posted_by"))
			session.commit()
			return jsonify(result)
		except (JournalImbalancedError, PeriodClosedError) as exc:
			return jsonify({"error": str(exc)}), 422
		except GLServiceError as exc:
			return jsonify({"error": str(exc)}), 400

	@expose("/<string:batch_id>/submit", methods=["POST"])
	@has_access
	def submit(self, batch_id: str):
		from pgappforge.plugins.erp.finance.gl.models import GLJournalBatch
		session = _get_session()
		batch = session.get(GLJournalBatch, batch_id)
		if batch is None:
			abort(404)
		if batch.status != "DRAFT":
			return jsonify({"error": f"Cannot submit from status {batch.status!r}"}), 422
		data = request.get_json(force=True) or {}
		batch.status = "SUBMITTED"
		batch.submitted_by = data.get("submitted_by")
		batch.submitted_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"batch_id": batch_id, "status": "SUBMITTED"})

	@expose("/<string:batch_id>/approve", methods=["POST"])
	@has_access
	def approve(self, batch_id: str):
		from pgappforge.plugins.erp.finance.gl.models import GLJournalBatch
		session = _get_session()
		batch = session.get(GLJournalBatch, batch_id)
		if batch is None:
			abort(404)
		if batch.status != "SUBMITTED":
			return jsonify({"error": f"Cannot approve from status {batch.status!r}"}), 422
		data = request.get_json(force=True) or {}
		batch.status = "APPROVED"
		batch.approved_by = data.get("approved_by")
		batch.approved_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"batch_id": batch_id, "status": "APPROVED"})


# ---------------------------------------------------------------------------
# GLJournalEntryView
# ---------------------------------------------------------------------------

class GLJournalEntryView(BaseView):
	"""Journal entry detail + reversal action.

	GET  /gl/entries/<id>              — detail with lines
	POST /gl/entries/<id>/reverse      — create reversal entry
	"""

	route_base = "/gl/entries"
	default_view = "detail"

	@expose("/<string:entry_id>")
	@has_access
	def detail(self, entry_id: str):
		from pgappforge.plugins.erp.finance.gl.models import GLJournalEntry
		session = _get_session()
		entry = session.get(GLJournalEntry, entry_id)
		if entry is None:
			abort(404)
		return jsonify({
			"id": entry.id,
			"batch_id": entry.batch_id,
			"entry_number": entry.entry_number,
			"entry_type": entry.entry_type,
			"posting_date": entry.posting_date.isoformat() if entry.posting_date else None,
			"description": entry.description,
			"status": entry.status,
			"reversal_of_entry_id": entry.reversal_of_entry_id,
			"lines": [
				{
					"line_number": ln.line_number,
					"account_code": ln.account_code,
					"cost_center_code": ln.cost_center_code,
					"debit_amount": ln.debit_amount,
					"credit_amount": ln.credit_amount,
					"currency_code": ln.currency_code,
					"fx_rate": str(ln.fx_rate),
					"base_debit": ln.base_debit,
					"base_credit": ln.base_credit,
					"description": ln.description,
					"party_id": ln.party_id,
					"tax_code": ln.tax_code,
				}
				for ln in entry.lines
			],
		})

	@expose("/<string:entry_id>/reverse", methods=["POST"])
	@has_access
	def reverse(self, entry_id: str):
		from pgappforge.plugins.erp.finance.gl.services import (
			GLServiceError, PeriodClosedError,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("reversal_date"):
			return jsonify({"error": "reversal_date required"}), 400
		try:
			result = _svc().reverse_journal(
				entry_id=entry_id,
				reversal_date=date.fromisoformat(data["reversal_date"]),
				session=session,
				description=data.get("description"),
			)
			session.commit()
			return jsonify(result)
		except PeriodClosedError as exc:
			return jsonify({"error": str(exc)}), 422
		except GLServiceError as exc:
			return jsonify({"error": str(exc)}), 400


# ---------------------------------------------------------------------------
# GLBudgetView
# ---------------------------------------------------------------------------

class GLBudgetView(BaseView):
	"""Budget CRUD.

	GET  /gl/budgets/                  — list
	POST /gl/budgets/                  — create
	"""

	route_base = "/gl/budgets"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.gl.models import GLBudget
		session = _get_session()
		rows = session.execute(
			sa.select(GLBudget).order_by(GLBudget.account_code).limit(500)
		).scalars().all()
		return jsonify([
			{
				"id": b.id,
				"account_code": b.account_code,
				"cost_center_code": b.cost_center_code,
				"period_id": b.period_id,
				"version": b.version,
				"budget_amount": b.budget_amount,
				"revised_budget_amount": b.revised_budget_amount,
				"forecast_amount": b.forecast_amount,
			}
			for b in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.gl.models import GLBudget
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "account_code", "period_id", "budget_amount")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		budget = GLBudget(
			tenant_id=data["tenant_id"],
			account_code=data["account_code"],
			cost_center_code=data.get("cost_center_code"),
			period_id=data["period_id"],
			version=data.get("version", "ORIGINAL"),
			budget_amount=int(data["budget_amount"]),
			revised_budget_amount=data.get("revised_budget_amount"),
			forecast_amount=data.get("forecast_amount"),
			notes=data.get("notes"),
		)
		session.add(budget)
		session.commit()
		return jsonify({"budget_id": budget.id, "status": "created"}), 201


# ---------------------------------------------------------------------------
# GLReportView  (Trial Balance, Budget vs Actual, Account Ledger)
# ---------------------------------------------------------------------------

class GLReportView(BaseView):
	"""Canned GL reports.

	GET /gl/reports/trial-balance/<period_id>        — trial balance
	GET /gl/reports/budget-vs-actual/<period_id>     — budget vs actual
	GET /gl/reports/account-ledger/<account_code>    — full transaction history
	"""

	route_base = "/gl/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"reports": [
				{"name": "Trial Balance", "endpoint": "/gl/reports/trial-balance/<period_id>"},
				{"name": "Budget vs Actual", "endpoint": "/gl/reports/budget-vs-actual/<period_id>"},
				{"name": "Account Ledger", "endpoint": "/gl/reports/account-ledger/<account_code>"},
			]
		})

	@expose("/trial-balance/<string:period_id>")
	@has_access
	def trial_balance(self, period_id: str):
		session = _get_session()
		rows = _svc().get_trial_balance(period_id, session)
		total_dr = sum(r["closing_debit"] for r in rows)
		total_cr = sum(r["closing_credit"] for r in rows)
		return jsonify({
			"period_id": period_id,
			"rows": rows,
			"total_debit": total_dr,
			"total_credit": total_cr,
			"is_balanced": total_dr == total_cr,
		})

	@expose("/budget-vs-actual/<string:period_id>")
	@has_access
	def budget_vs_actual(self, period_id: str):
		session = _get_session()
		version = request.args.get("version", "ORIGINAL")
		rows = _svc().get_budget_vs_actual(period_id, session, version=version)
		return jsonify({"period_id": period_id, "version": version, "rows": rows})

	@expose("/account-ledger/<string:account_code>")
	@has_access
	def account_ledger(self, account_code: str):
		"""Full posted transaction history for one account.

		Query params:
		  from_date (ISO date, optional)
		  to_date   (ISO date, optional)
		  tenant_id (optional)
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLJournalLine, GLJournalEntry, GLJournalBatch,
		)
		session = _get_session()
		from_date = request.args.get("from_date")
		to_date = request.args.get("to_date")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				GLJournalLine.id,
				GLJournalLine.line_number,
				GLJournalEntry.posting_date,
				GLJournalEntry.entry_number,
				GLJournalEntry.description.label("entry_description"),
				GLJournalLine.description.label("line_description"),
				GLJournalLine.debit_amount,
				GLJournalLine.credit_amount,
				GLJournalLine.currency_code,
				GLJournalLine.base_debit,
				GLJournalLine.base_credit,
				GLJournalLine.cost_center_code,
				GLJournalLine.reference,
			)
			.join(GLJournalEntry, GLJournalEntry.id == GLJournalLine.entry_id)
			.join(GLJournalBatch, GLJournalBatch.id == GLJournalEntry.batch_id)
			.where(
				GLJournalLine.account_code == account_code,
				GLJournalEntry.status == "POSTED",
			)
			.order_by(GLJournalEntry.posting_date, GLJournalLine.line_number)
		)
		if from_date:
			q = q.where(GLJournalEntry.posting_date >= date.fromisoformat(from_date))
		if to_date:
			q = q.where(GLJournalEntry.posting_date <= date.fromisoformat(to_date))
		if tenant_id:
			q = q.where(GLJournalLine.tenant_id == tenant_id)

		rows = session.execute(q).all()
		running_balance = 0
		items = []
		for row in rows:
			running_balance += row.base_debit - row.base_credit
			items.append({
				"line_id": row.id,
				"posting_date": row.posting_date.isoformat() if row.posting_date else None,
				"entry_number": row.entry_number,
				"description": row.line_description or row.entry_description,
				"debit": row.debit_amount,
				"credit": row.credit_amount,
				"currency_code": row.currency_code,
				"base_debit": row.base_debit,
				"base_credit": row.base_credit,
				"running_balance": running_balance,
				"cost_center_code": row.cost_center_code,
				"reference": row.reference,
			})
		return jsonify({
			"account_code": account_code,
			"from_date": from_date,
			"to_date": to_date,
			"lines": items,
			"closing_balance": running_balance,
		})


__all__ = [
	"GLAccountView",
	"GLPeriodView",
	"GLJournalBatchView",
	"GLJournalEntryView",
	"GLBudgetView",
	"GLReportView",
]
