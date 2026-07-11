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
from collections import defaultdict
from datetime import date, datetime, timezone
from html import escape

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.plugins.erp.base_view import BaseERPModelView, BaseERPView
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


def _parse_date_arg(name: str, default: date) -> date:
	raw = request.args.get(name)
	if not raw:
		return default
	try:
		return date.fromisoformat(raw)
	except ValueError:
		abort(400, f"{name} must be an ISO date")


def _format_cents(cents: int | None) -> str:
	return f"{int(cents or 0) / 100:,.2f}"


def _normal_balance_amount(debit: int, credit: int, normal_balance: str | None) -> int:
	if (normal_balance or "").upper() == "CREDIT":
		return credit - debit
	return debit - credit


def _money_cell(cents: int | None) -> str:
	return f"<td class=\"money\">{escape(_format_cents(cents))}</td>"


def _report_page(title: str, body: str) -> object:
	resp = make_response(f"""<!doctype html>
<html>
<head>
	<meta charset="utf-8">
	<title>{escape(title)}</title>
	<style>
		body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2933; }}
		h1 {{ font-size: 24px; margin: 0 0 6px; }}
		h2 {{ font-size: 18px; margin: 24px 0 8px; }}
		.meta {{ color: #52606d; margin-bottom: 18px; }}
		.actions, .period-selector {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 16px 0; }}
		.actions a, .period-selector a {{ border: 1px solid #bcccdc; border-radius: 6px; padding: 8px 10px; color: #243b53; text-decoration: none; }}
		.actions a:hover, .period-selector a:hover, .period-selector a.active {{ background: #f0f4f8; }}
		table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
		th, td {{ border-bottom: 1px solid #d9e2ec; padding: 8px 10px; text-align: left; }}
		th {{ background: #f0f4f8; color: #334e68; font-weight: 600; }}
		tfoot td {{ font-weight: 700; border-top: 2px solid #829ab1; }}
		.money {{ text-align: right; font-variant-numeric: tabular-nums; }}
		.out-of-balance {{ color: #b91c1c; font-weight: 700; }}
		.badge {{ display: inline-block; border-radius: 999px; padding: 3px 9px; font-size: 12px; font-weight: 700; background: #e0e8f9; color: #1e3a8a; }}
		.badge-warning {{ background: #fee2e2; color: #991b1b; }}
		.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 24px; }}
		.section-total {{ font-weight: 700; }}
		.indent-1 {{ padding-left: 24px; }}
	</style>
</head>
<body>
{body}
</body>
</html>""")
	resp.headers["Content-Type"] = "text/html; charset=utf-8"
	return resp


def _account_totals(
	session,
	account_types: tuple[str, ...],
	from_date: date | None = None,
	to_date: date | None = None,
	tenant_id: str | None = None,
):
	from pgappforge.plugins.erp.finance.gl.models import (
		GLAccount,
		GLJournalEntry,
		GLJournalLine,
	)

	filters = [
		GLAccount.account_type.in_(account_types),
		GLJournalEntry.status == "POSTED",
	]
	if from_date is not None:
		filters.append(GLJournalEntry.posting_date >= from_date)
	if to_date is not None:
		filters.append(GLJournalEntry.posting_date <= to_date)
	if tenant_id:
		filters.append(GLJournalLine.tenant_id == tenant_id)

	stmt = (
		sa.select(
			GLAccount.account_code,
			GLAccount.account_name,
			GLAccount.account_type,
			GLAccount.account_subtype,
			GLAccount.normal_balance,
			sa.func.coalesce(sa.func.sum(GLJournalLine.base_debit), 0).label("debit_total"),
			sa.func.coalesce(sa.func.sum(GLJournalLine.base_credit), 0).label("credit_total"),
		)
		.select_from(GLAccount)
		.join(GLJournalLine, GLJournalLine.account_code == GLAccount.account_code)
		.join(GLJournalEntry, GLJournalEntry.id == GLJournalLine.entry_id)
		.where(*filters)
		.group_by(
			GLAccount.account_code,
			GLAccount.account_name,
			GLAccount.account_type,
			GLAccount.account_subtype,
			GLAccount.normal_balance,
		)
		.order_by(GLAccount.account_code)
	)
	return session.execute(stmt).all()


def _period_range(period_key: str, today: date) -> tuple[date, date, str, str]:
	key = (period_key or "current_month").lower()
	if key == "quarter":
		start_month = ((today.month - 1) // 3) * 3 + 1
		start = date(today.year, start_month, 1)
		return start, today, "quarter", "Current Quarter"
	if key == "ytd":
		return date(today.year, 1, 1), today, "ytd", "Year to Date"
	start = date(today.year, today.month, 1)
	return start, today, "current_month", "Current Month"


# ---------------------------------------------------------------------------
# COAView
# ---------------------------------------------------------------------------

class COAView(BaseERPModelView):
	"""Model-backed Chart of Accounts view with grouped hierarchy output."""

	from pgappforge.plugins.erp.finance.gl.models import GLAccount

	datamodel = SQLAInterface(GLAccount)

	list_columns = [
		"account_code",
		"account_name",
		"account_type",
		"normal_balance",
		# TODO: GLAccount stores hierarchy in parent_code; there is no parent_account_id field.
		"parent_code",
		"is_active",
	]
	show_columns = [
		"account_code",
		"account_name",
		"account_type",
		"account_subtype",
		"normal_balance",
		"parent_code",
		"is_posting_account",
		"is_reconciliation_account",
		"currency_code",
		"ifrs_concept",
		"gaap_concept",
		"is_active",
		"description",
	]
	add_columns = [
		"tenant_id",
		"account_code",
		"account_name",
		"account_type",
		"account_subtype",
		"normal_balance",
		"parent_code",
		"is_posting_account",
		"is_reconciliation_account",
		"currency_code",
		"is_active",
		"description",
	]
	edit_columns = [
		"account_name",
		"account_type",
		"account_subtype",
		"normal_balance",
		"parent_code",
		"is_posting_account",
		"is_reconciliation_account",
		"currency_code",
		"is_active",
		"description",
	]
	label_columns = {
		"account_code": "Code",
		"account_name": "Account Name",
		"account_type": "Type",
		"normal_balance": "Normal Balance",
		"parent_code": "Parent Account",
	}
	search_columns = ["account_code", "account_name", "account_type"]
	base_order = ("account_code", "asc")

	@expose("/tree/")
	@has_access
	def tree(self):
		from pgappforge.plugins.erp.finance.gl.models import GLAccount

		session = _get_session()
		accounts = session.execute(
			sa.select(GLAccount).order_by(GLAccount.account_type, GLAccount.account_code)
		).scalars().all()
		by_code = {account.account_code: account for account in accounts}
		children_by_parent: dict[str | None, list[GLAccount]] = defaultdict(list)
		for account in accounts:
			parent_code = account.parent_code if account.parent_code in by_code else None
			children_by_parent[parent_code].append(account)

		def render_node(account: GLAccount, depth: int = 0) -> str:
			children = children_by_parent.get(account.account_code, [])
			status = "Active" if account.is_active else "Inactive"
			row = (
				"<tr>"
				f"<td class=\"indent-{min(depth, 1)}\">{escape(account.account_code)}</td>"
				f"<td>{escape(account.account_name)}</td>"
				f"<td>{escape(account.account_type)}</td>"
				f"<td>{escape(account.normal_balance)}</td>"
				f"<td>{escape(account.parent_code or '')}</td>"
				f"<td>{escape(status)}</td>"
				"</tr>"
			)
			return row + "".join(render_node(child, depth + 1) for child in children)

		groups = []
		for account_type in ("ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"):
			roots = [
				account for account in children_by_parent.get(None, [])
				if account.account_type == account_type
			]
			if not roots:
				continue
			rows = "".join(render_node(account) for account in roots)
			groups.append(f"""
<h2>{escape(account_type.title())}</h2>
<table>
	<thead>
		<tr><th>Code</th><th>Account Name</th><th>Type</th><th>Normal Balance</th><th>Parent Account</th><th>Status</th></tr>
	</thead>
	<tbody>{rows}</tbody>
</table>""")
		body = f"""
<h1>Chart of Accounts</h1>
<div class="meta">Accounts grouped by type and displayed by parent account hierarchy.</div>
{''.join(groups) if groups else '<p>No accounts found.</p>'}"""
		return _report_page("Chart of Accounts", body)


# ---------------------------------------------------------------------------
# GLAccountView
# ---------------------------------------------------------------------------

class GLAccountView(BaseERPView):
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

class GLPeriodView(BaseERPView):
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

class GLJournalBatchView(BaseERPView):
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

class GLJournalEntryView(BaseERPView):
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

class GLBudgetView(BaseERPView):
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
# GLDashboardView
# ---------------------------------------------------------------------------

class GLDashboardView(BaseERPView):
	"""General Ledger dashboard with report links and recent journals."""

	route_base = "/gl"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.finance.gl.models import (
			GLJournalBatch,
			GLJournalEntry,
			GLJournalLine,
		)

		session = _get_session()
		today = date.today()
		period_start, period_end, period_key, period_label = _period_range(
			request.args.get("period", "current_month"),
			today,
		)
		tenant_id = request.args.get("tenant_id") or None

		unposted_filters = [GLJournalEntry.status != "POSTED"]
		entry_filters = [
			GLJournalEntry.posting_date >= period_start,
			GLJournalEntry.posting_date <= period_end,
		]
		if tenant_id:
			unposted_filters.append(GLJournalEntry.tenant_id == tenant_id)
			entry_filters.append(GLJournalEntry.tenant_id == tenant_id)

		open_batch_filters = [GLJournalBatch.status.in_(["DRAFT", "SUBMITTED", "APPROVED"])]
		if tenant_id:
			open_batch_filters.append(GLJournalBatch.tenant_id == tenant_id)

		unposted_count = session.execute(
			sa.select(sa.func.count(GLJournalEntry.id)).where(*unposted_filters)
		).scalar_one() or 0
		open_batch_count = session.execute(
			sa.select(sa.func.count(GLJournalBatch.id)).where(*open_batch_filters)
		).scalar_one() or 0

		recent_rows = session.execute(
			sa.select(
				GLJournalEntry.id,
				GLJournalEntry.entry_number,
				GLJournalEntry.posting_date,
				GLJournalEntry.description,
				GLJournalEntry.status,
				GLJournalBatch.batch_number,
				sa.func.coalesce(sa.func.sum(GLJournalLine.base_debit), 0).label("debit_total"),
				sa.func.coalesce(sa.func.sum(GLJournalLine.base_credit), 0).label("credit_total"),
			)
			.join(GLJournalBatch, GLJournalBatch.id == GLJournalEntry.batch_id)
			.join(GLJournalLine, GLJournalLine.entry_id == GLJournalEntry.id)
			.where(*entry_filters)
			.group_by(
				GLJournalEntry.id,
				GLJournalEntry.entry_number,
				GLJournalEntry.posting_date,
				GLJournalEntry.description,
				GLJournalEntry.status,
				GLJournalBatch.batch_number,
			)
			.order_by(GLJournalEntry.posting_date.desc(), GLJournalEntry.created_at.desc())
			.limit(10)
		).all()

		period_links = []
		for key, label in (
			("current_month", "Current Month"),
			("quarter", "Quarter"),
			("ytd", "YTD"),
		):
			active = " active" if key == period_key else ""
			period_links.append(
				f"<a class=\"{active.strip()}\" href=\"/gl/?period={escape(key)}\">{escape(label)}</a>"
			)

		quick_links = f"""
<div class="actions">
	<a href="/gl/trial-balance/?as_of_date={escape(period_end.isoformat())}">Trial Balance</a>
	<a href="/gl/income-statement/?from_date={escape(period_start.isoformat())}&amp;to_date={escape(period_end.isoformat())}">Income Statement</a>
	<a href="/gl/balance-sheet/?as_of_date={escape(period_end.isoformat())}">Balance Sheet</a>
</div>"""
		warning_class = " badge-warning" if unposted_count > 0 else ""
		rows = []
		for row in recent_rows:
			rows.append(
				"<tr>"
				f"<td>{escape(row.posting_date.isoformat() if row.posting_date else '')}</td>"
				f"<td>{escape(row.entry_number or row.id)}</td>"
				f"<td>{escape(row.batch_number or '')}</td>"
				f"<td>{escape(row.description or '')}</td>"
				f"<td>{escape(row.status or '')}</td>"
				f"{_money_cell(row.debit_total)}"
				f"{_money_cell(row.credit_total)}"
				"</tr>"
			)
		body = f"""
<h1>General Ledger Dashboard</h1>
<div class="meta">{escape(period_label)}: {escape(period_start.isoformat())} to {escape(period_end.isoformat())}</div>
<div class="period-selector">{''.join(period_links)}</div>
{quick_links}
<p>
	<span class="badge{warning_class}">Unposted journals: {unposted_count}</span>
	<span class="badge">Open batches: {open_batch_count}</span>
</p>
<h2>Recent Journal Entries</h2>
<table>
	<thead>
		<tr><th>Date</th><th>Entry</th><th>Batch</th><th>Description</th><th>Status</th><th class="money">Debit</th><th class="money">Credit</th></tr>
	</thead>
	<tbody>{''.join(rows) if rows else '<tr><td colspan="7">No journal entries for this period.</td></tr>'}</tbody>
</table>"""
		if request.args.get("format") == "json":
			return jsonify({
				"period": period_key,
				"from_date": period_start.isoformat(),
				"to_date": period_end.isoformat(),
				"unposted_journals": unposted_count,
				"open_batches": open_batch_count,
				"recent_entries": [
					{
						"id": row.id,
						"entry_number": row.entry_number,
						"posting_date": row.posting_date.isoformat() if row.posting_date else None,
						"description": row.description,
						"status": row.status,
						"batch_number": row.batch_number,
						"debit_total": int(row.debit_total or 0),
						"credit_total": int(row.credit_total or 0),
						"debit_display": _format_cents(row.debit_total),
						"credit_display": _format_cents(row.credit_total),
					}
					for row in recent_rows
				],
			})
		return _report_page("General Ledger Dashboard", body)


# ---------------------------------------------------------------------------
# TrialBalanceView
# ---------------------------------------------------------------------------

class TrialBalanceView(BaseERPView):
	"""Trial balance as of a selected date."""

	route_base = "/gl"
	default_view = "trial_balance"

	@expose("/trial-balance/")
	@has_access
	def trial_balance(self):
		session = _get_session()
		as_of_date = _parse_date_arg("as_of_date", date.today())
		tenant_id = request.args.get("tenant_id") or None
		rows = []
		total_debit = 0
		total_credit = 0
		for row in _account_totals(
			session,
			("ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"),
			to_date=as_of_date,
			tenant_id=tenant_id,
		):
			debit = int(row.debit_total or 0)
			credit = int(row.credit_total or 0)
			balance = _normal_balance_amount(debit, credit, row.normal_balance)
			total_debit += debit
			total_credit += credit
			rows.append({
				"account_code": row.account_code,
				"account_name": row.account_name,
				"account_type": row.account_type,
				"debit_total": debit,
				"credit_total": credit,
				"balance": balance,
				"debit_display": _format_cents(debit),
				"credit_display": _format_cents(credit),
				"balance_display": _format_cents(balance),
			})

		is_balanced = total_debit == total_credit
		if request.args.get("format") == "json":
			return jsonify({
				"as_of_date": as_of_date.isoformat(),
				"rows": rows,
				"total_debit": total_debit,
				"total_credit": total_credit,
				"balance": total_debit - total_credit,
				"total_debit_display": _format_cents(total_debit),
				"total_credit_display": _format_cents(total_credit),
				"balance_display": _format_cents(total_debit - total_credit),
				"is_balanced": is_balanced,
			})

		html_rows = []
		for row in rows:
			html_rows.append(
				"<tr>"
				f"<td>{escape(row['account_code'])}</td>"
				f"<td>{escape(row['account_name'])}</td>"
				f"{_money_cell(row['debit_total'])}"
				f"{_money_cell(row['credit_total'])}"
				f"{_money_cell(row['balance'])}"
				"</tr>"
			)
		status = "Balanced" if is_balanced else "Out of balance"
		status_class = "" if is_balanced else " out-of-balance"
		body = f"""
<h1>Trial Balance</h1>
<div class="meta">As of {escape(as_of_date.isoformat())} <span class="{status_class.strip()}">{escape(status)}</span></div>
<table>
	<thead>
		<tr><th>Account Code</th><th>Account Name</th><th class="money">Debit</th><th class="money">Credit</th><th class="money">Balance</th></tr>
	</thead>
	<tbody>{''.join(html_rows) if html_rows else '<tr><td colspan="5">No posted ledger activity found.</td></tr>'}</tbody>
	<tfoot>
		<tr class="{status_class.strip()}"><td colspan="2">Totals</td>{_money_cell(total_debit)}{_money_cell(total_credit)}{_money_cell(total_debit - total_credit)}</tr>
	</tfoot>
</table>"""
		return _report_page("Trial Balance", body)


# ---------------------------------------------------------------------------
# IncomeStatementView
# ---------------------------------------------------------------------------

class IncomeStatementView(BaseERPView):
	"""Income statement for a selected date range."""

	route_base = "/gl"
	default_view = "income_statement"

	@expose("/income-statement/")
	@has_access
	def income_statement(self):
		today = date.today()
		from_date = _parse_date_arg("from_date", date(today.year, 1, 1))
		to_date = _parse_date_arg("to_date", today)
		tenant_id = request.args.get("tenant_id") or None
		session = _get_session()

		revenue_rows = []
		cogs_rows = []
		operating_expense_rows = []
		total_revenue = 0
		total_cogs = 0
		total_operating_expense = 0

		for row in _account_totals(
			session,
			("REVENUE", "EXPENSE"),
			from_date=from_date,
			to_date=to_date,
			tenant_id=tenant_id,
		):
			debit = int(row.debit_total or 0)
			credit = int(row.credit_total or 0)
			if row.account_type == "REVENUE":
				amount = credit - debit
				total_revenue += amount
				revenue_rows.append({
					"account_code": row.account_code,
					"account_name": row.account_name,
					"amount": amount,
					"amount_display": _format_cents(amount),
				})
				continue

			amount = debit - credit
			subtype = (row.account_subtype or "").upper()
			name = (row.account_name or "").upper()
			is_cogs = any(token in subtype or token in name for token in (
				"COGS",
				"COST OF GOODS",
				"COST_OF_GOODS",
				"COST OF SALES",
				"COST_OF_SALES",
			))
			target = cogs_rows if is_cogs else operating_expense_rows
			target.append({
				"account_code": row.account_code,
				"account_name": row.account_name,
				"amount": amount,
				"amount_display": _format_cents(amount),
			})
			if is_cogs:
				total_cogs += amount
			else:
				total_operating_expense += amount

		gross_profit = total_revenue - total_cogs
		operating_income = gross_profit - total_operating_expense
		net_income = total_revenue - total_cogs - total_operating_expense
		payload = {
			"from_date": from_date.isoformat(),
			"to_date": to_date.isoformat(),
			"revenue": revenue_rows,
			"cogs": cogs_rows,
			"operating_expenses": operating_expense_rows,
			"total_revenue": total_revenue,
			"total_cogs": total_cogs,
			"gross_profit": gross_profit,
			"total_operating_expense": total_operating_expense,
			"operating_income": operating_income,
			"net_income": net_income,
			"total_revenue_display": _format_cents(total_revenue),
			"total_cogs_display": _format_cents(total_cogs),
			"gross_profit_display": _format_cents(gross_profit),
			"total_operating_expense_display": _format_cents(total_operating_expense),
			"operating_income_display": _format_cents(operating_income),
			"net_income_display": _format_cents(net_income),
		}
		if request.args.get("format") == "json":
			return jsonify(payload)

		def section(title: str, rows: list[dict], total_label: str, total: int) -> str:
			body_rows = "".join(
				"<tr>"
				f"<td>{escape(row['account_code'])}</td>"
				f"<td>{escape(row['account_name'])}</td>"
				f"{_money_cell(row['amount'])}"
				"</tr>"
				for row in rows
			)
			return f"""
<h2>{escape(title)}</h2>
<table>
	<tbody>{body_rows if body_rows else '<tr><td colspan="3">No activity.</td></tr>'}</tbody>
	<tfoot><tr><td colspan="2">{escape(total_label)}</td>{_money_cell(total)}</tr></tfoot>
</table>"""

		body = f"""
<h1>Income Statement</h1>
<div class="meta">{escape(from_date.isoformat())} to {escape(to_date.isoformat())}</div>
{section("Revenue", revenue_rows, "Total Revenue", total_revenue)}
{section("Cost of Goods Sold", cogs_rows, "Total Cost of Goods Sold", total_cogs)}
<table><tbody><tr class="section-total"><td colspan="2">Gross Profit</td>{_money_cell(gross_profit)}</tr></tbody></table>
{section("Operating Expenses", operating_expense_rows, "Total Operating Expenses", total_operating_expense)}
<table>
	<tbody>
		<tr class="section-total"><td colspan="2">Operating Income</td>{_money_cell(operating_income)}</tr>
		<tr class="section-total"><td colspan="2">Net Income</td>{_money_cell(net_income)}</tr>
	</tbody>
</table>"""
		return _report_page("Income Statement", body)


# ---------------------------------------------------------------------------
# BalanceSheetView
# ---------------------------------------------------------------------------

class BalanceSheetView(BaseERPView):
	"""Balance sheet as of a selected date."""

	route_base = "/gl"
	default_view = "balance_sheet"

	@expose("/balance-sheet/")
	@has_access
	def balance_sheet(self):
		as_of_date = _parse_date_arg("as_of_date", date.today())
		tenant_id = request.args.get("tenant_id") or None
		session = _get_session()

		current_assets = []
		fixed_assets = []
		current_liabilities = []
		long_term_liabilities = []
		equity_rows = []
		total_assets = 0
		total_liabilities = 0
		total_equity = 0

		for row in _account_totals(
			session,
			("ASSET", "LIABILITY", "EQUITY"),
			to_date=as_of_date,
			tenant_id=tenant_id,
		):
			debit = int(row.debit_total or 0)
			credit = int(row.credit_total or 0)
			amount = _normal_balance_amount(debit, credit, row.normal_balance)
			item = {
				"account_code": row.account_code,
				"account_name": row.account_name,
				"amount": amount,
				"amount_display": _format_cents(amount),
			}
			subtype = (row.account_subtype or "").upper()
			name = (row.account_name or "").upper()
			if row.account_type == "ASSET":
				total_assets += amount
				if any(token in subtype or token in name for token in ("FIXED", "PPE", "PROPERTY", "EQUIPMENT", "NONCURRENT", "NON-CURRENT")):
					fixed_assets.append(item)
				else:
					current_assets.append(item)
			elif row.account_type == "LIABILITY":
				total_liabilities += amount
				if any(token in subtype or token in name for token in ("LONG", "NONCURRENT", "NON-CURRENT")):
					long_term_liabilities.append(item)
				else:
					current_liabilities.append(item)
			elif row.account_type == "EQUITY":
				total_equity += amount
				equity_rows.append(item)

		right_total = total_liabilities + total_equity
		is_balanced = total_assets == right_total
		payload = {
			"as_of_date": as_of_date.isoformat(),
			"current_assets": current_assets,
			"fixed_assets": fixed_assets,
			"current_liabilities": current_liabilities,
			"long_term_liabilities": long_term_liabilities,
			"equity": equity_rows,
			"total_assets": total_assets,
			"total_liabilities": total_liabilities,
			"total_equity": total_equity,
			"total_liabilities_and_equity": right_total,
			"is_balanced": is_balanced,
			"total_assets_display": _format_cents(total_assets),
			"total_liabilities_display": _format_cents(total_liabilities),
			"total_equity_display": _format_cents(total_equity),
			"total_liabilities_and_equity_display": _format_cents(right_total),
		}
		if request.args.get("format") == "json":
			return jsonify(payload)

		def statement_section(title: str, rows: list[dict], total_label: str, total: int) -> str:
			body_rows = "".join(
				"<tr>"
				f"<td>{escape(row['account_code'])}</td>"
				f"<td>{escape(row['account_name'])}</td>"
				f"{_money_cell(row['amount'])}"
				"</tr>"
				for row in rows
			)
			return f"""
<h2>{escape(title)}</h2>
<table>
	<tbody>{body_rows if body_rows else '<tr><td colspan="3">No balances.</td></tr>'}</tbody>
	<tfoot><tr><td colspan="2">{escape(total_label)}</td>{_money_cell(total)}</tr></tfoot>
</table>"""

		status = "Balanced" if is_balanced else "Out of balance"
		status_class = "" if is_balanced else " out-of-balance"
		body = f"""
<h1>Balance Sheet</h1>
<div class="meta">As of {escape(as_of_date.isoformat())} <span class="{status_class.strip()}">{escape(status)}</span></div>
<div class="grid">
	<div>
		{statement_section("Current Assets", current_assets, "Total Current Assets", sum(row["amount"] for row in current_assets))}
		{statement_section("Fixed Assets", fixed_assets, "Total Fixed Assets", sum(row["amount"] for row in fixed_assets))}
		<table><tbody><tr class="section-total"><td colspan="2">Total Assets</td>{_money_cell(total_assets)}</tr></tbody></table>
	</div>
	<div>
		{statement_section("Current Liabilities", current_liabilities, "Total Current Liabilities", sum(row["amount"] for row in current_liabilities))}
		{statement_section("Long-term Liabilities", long_term_liabilities, "Total Long-term Liabilities", sum(row["amount"] for row in long_term_liabilities))}
		<table><tbody><tr class="section-total"><td colspan="2">Total Liabilities</td>{_money_cell(total_liabilities)}</tr></tbody></table>
		{statement_section("Equity", equity_rows, "Total Equity", total_equity)}
		<table><tbody><tr class="section-total {status_class.strip()}"><td colspan="2">Total Liabilities and Equity</td>{_money_cell(right_total)}</tr></tbody></table>
	</div>
</div>"""
		return _report_page("Balance Sheet", body)


# ---------------------------------------------------------------------------
# GLReportView  (Trial Balance, Budget vs Actual, Account Ledger)
# ---------------------------------------------------------------------------

class GLReportView(BaseERPView):
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
		from pgappforge.plugins.erp.finance.gl.models import GLAccount, GLPeriod, GLJournalBatch
		session = _get_session()
		total_accounts = session.execute(
			sa.select(sa.func.count(GLAccount.account_code))
		).scalar() or 0
		total_periods = session.execute(
			sa.select(sa.func.count(GLPeriod.id))
		).scalar() or 0
		recent_journals = session.execute(
			sa.select(sa.func.count(GLJournalBatch.id)).where(
				GLJournalBatch.status.in_(["DRAFT", "SUBMITTED", "APPROVED"])
			)
		).scalar() or 0
		kpi_html = self.kpi_cards([
			{"label": "Chart of Accounts", "value": total_accounts,
			 "format": "integer", "color": "#1a56db", "icon": "fa-list"},
			{"label": "Fiscal Periods", "value": total_periods,
			 "format": "integer", "color": "#0e9f6e", "icon": "fa-calendar"},
			{"label": "Open Batches", "value": recent_journals,
			 "format": "integer", "color": "#e3a008", "icon": "fa-book"},
		])
		return jsonify({
			"kpi_html": str(kpi_html),
			"reports": [
				{"name": "Trial Balance",     "endpoint": "/gl/reports/trial-balance/<period_id>"},
				{"name": "Income Statement",  "endpoint": "/gl/reports/income-statement/<period_id>"},
				{"name": "Balance Sheet",     "endpoint": "/gl/reports/balance-sheet/<period_id>"},
				{"name": "Budget vs Actual",  "endpoint": "/gl/reports/budget-vs-actual/<period_id>"},
				{"name": "Account Ledger",    "endpoint": "/gl/reports/account-ledger/<account_code>"},
			],
		})

	@expose("/income-statement/<string:period_id>")
	@has_access
	def income_statement(self, period_id: str):
		"""Income Statement (Profit & Loss) for a GL period.

		Returns revenue accounts, expense accounts, and net income.
		Positive net_income_cents = profit; negative = loss.
		"""
		session = _get_session()
		result = _svc().get_income_statement(period_id, session)
		return jsonify(result)

	@expose("/balance-sheet/<string:period_id>")
	@has_access
	def balance_sheet(self, period_id: str):
		"""Balance Sheet as of the end of a GL period.

		Assets = Liabilities + Equity + Net Income for the period.
		The 'balanced' field is True when the accounting equation holds.
		"""
		session = _get_session()
		result = _svc().get_balance_sheet(period_id, session)
		return jsonify(result)

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


# ---------------------------------------------------------------------------
# ReportDownloadView  (PDF + CSV downloads for financial statements)
# ---------------------------------------------------------------------------

class ReportDownloadView(BaseERPView):
	"""Downloadable financial statements — PDF or CSV.

	GET /gl/reports/trial-balance/<period_id>.pdf
	GET /gl/reports/trial-balance/<period_id>.csv
	GET /gl/reports/income-statement/<period_id>.pdf
	GET /gl/reports/income-statement/<period_id>.csv
	GET /gl/reports/balance-sheet/<period_id>.pdf
	GET /gl/reports/balance-sheet/<period_id>.csv

	``fmt`` is the file extension: "pdf" or "csv".
	``tenant_id`` may be passed as a query-string parameter.
	"""

	route_base = "/gl/reports"
	default_view = "index"

	# Re-use the index from GLReportView so route_base collision is harmless
	# when both views are registered; the download routes are distinct.

	def _report_svc(self):
		from pgappforge.plugins.erp.finance.gl.reports import FinancialReportService
		return FinancialReportService()

	def _tenant(self) -> str | None:
		return request.args.get("tenant_id")

	@staticmethod
	def _pdf_response(data: bytes, filename: str):
		if not data:
			return make_response(
				jsonify({"error": "PDF generation unavailable — reportlab not installed"}),
				503,
			)
		resp = make_response(data)
		resp.headers["Content-Type"] = "application/pdf"
		resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
		return resp

	@staticmethod
	def _csv_response(data: str, filename: str):
		resp = make_response(data)
		resp.headers["Content-Type"] = "text/csv; charset=utf-8"
		resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
		return resp

	# -- Trial Balance -------------------------------------------------------

	@expose("/trial-balance/<string:period_id>.<string:fmt>")
	@has_access
	def download_trial_balance(self, period_id: str, fmt: str):
		"""Download trial balance as PDF or CSV.

		Accepted formats: ``pdf``, ``csv``.
		"""
		session = _get_session()
		svc = self._report_svc()
		tenant_id = self._tenant()

		if fmt == "pdf":
			data = svc.generate_trial_balance_pdf(period_id, tenant_id, session)
			return self._pdf_response(data, f"trial_balance_{period_id}.pdf")
		elif fmt == "csv":
			data = svc.generate_trial_balance_csv(period_id, tenant_id, session)
			return self._csv_response(data, f"trial_balance_{period_id}.csv")
		else:
			return make_response(jsonify({"error": f"Unsupported format {fmt!r}; use 'pdf' or 'csv'"}), 400)

	# -- Income Statement ----------------------------------------------------

	@expose("/income-statement/<string:period_id>.<string:fmt>")
	@has_access
	def download_income_statement(self, period_id: str, fmt: str):
		"""Download income statement as PDF or CSV."""
		session = _get_session()
		svc = self._report_svc()
		tenant_id = self._tenant()

		if fmt == "pdf":
			data = svc.generate_income_statement_pdf(period_id, tenant_id, session)
			return self._pdf_response(data, f"income_statement_{period_id}.pdf")
		elif fmt == "csv":
			data = svc.generate_income_statement_csv(period_id, tenant_id, session)
			return self._csv_response(data, f"income_statement_{period_id}.csv")
		else:
			return make_response(jsonify({"error": f"Unsupported format {fmt!r}; use 'pdf' or 'csv'"}), 400)

	# -- Balance Sheet -------------------------------------------------------

	@expose("/balance-sheet/<string:period_id>.<string:fmt>")
	@has_access
	def download_balance_sheet(self, period_id: str, fmt: str):
		"""Download balance sheet as PDF or CSV."""
		session = _get_session()
		svc = self._report_svc()
		tenant_id = self._tenant()

		if fmt == "pdf":
			data = svc.generate_balance_sheet_pdf(period_id, tenant_id, session)
			return self._pdf_response(data, f"balance_sheet_{period_id}.pdf")
		elif fmt == "csv":
			data = svc.generate_balance_sheet_csv(period_id, tenant_id, session)
			return self._csv_response(data, f"balance_sheet_{period_id}.csv")
		else:
			return make_response(jsonify({"error": f"Unsupported format {fmt!r}; use 'pdf' or 'csv'"}), 400)


__all__ = [
	"COAView",
	"GLDashboardView",
	"GLAccountView",
	"GLPeriodView",
	"GLJournalBatchView",
	"GLJournalEntryView",
	"GLBudgetView",
	"TrialBalanceView",
	"IncomeStatementView",
	"BalanceSheetView",
	"GLReportView",
	"ReportDownloadView",
]
