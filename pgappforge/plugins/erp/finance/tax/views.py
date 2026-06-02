"""
pgappforge/plugins/erp/finance/tax/views.py

Flask views for the Tax Management plugin.

Routes:
  TaxJurisdictionView   GET/POST /tax/jurisdictions/
  TaxCodeView           GET/POST /tax/codes/
  TaxTransactionView    GET      /tax/transactions/
                        POST     /tax/transactions/
  TaxReturnView         GET      /tax/returns/
                        POST     /tax/returns/generate
                        POST     /tax/returns/<id>/file
                        POST     /tax/returns/<id>/pay
  TaxReportView         GET      /tax/reports/vat-return/<id>
                        GET      /tax/reports/tax-liability
                        GET      /tax/reports/input-tax-credit
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


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
	raise RuntimeError("Cannot obtain database session")


def _he(s: str) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _fmt(v: int | None) -> str:
	if v is None:
		return ""
	return f"{v:,}"


# ---------------------------------------------------------------------------
# TaxJurisdictionView
# ---------------------------------------------------------------------------

class TaxJurisdictionView(BaseView):
	"""Tax jurisdiction CRUD.

	GET  /tax/jurisdictions/        — list (JSON)
	GET  /tax/jurisdictions/<id>    — detail (JSON)
	POST /tax/jurisdictions/        — create (JSON)
	PUT  /tax/jurisdictions/<id>    — update (JSON)
	"""

	route_base = "/tax/jurisdictions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.tax.models import TaxJurisdiction
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(TaxJurisdiction).order_by(TaxJurisdiction.code)
		if tenant_id:
			q = q.where(TaxJurisdiction.tenant_id == tenant_id)
		jurisdictions = session.execute(q).scalars().all()
		return jsonify({
			"jurisdictions": [
				{
					"id": j.id,
					"code": j.code,
					"name": j.name,
					"country_code": j.country_code,
					"region_code": j.region_code,
					"tax_type": j.tax_type,
					"tax_authority_name": j.tax_authority_name,
					"filing_frequency": j.filing_frequency,
					"is_active": j.is_active,
				}
				for j in jurisdictions
			]
		})

	@expose("/<string:jur_id>")
	@has_access
	def detail(self, jur_id: str):
		from pgappforge.plugins.erp.finance.tax.models import TaxJurisdiction
		session = _get_session()
		j = session.get(TaxJurisdiction, jur_id)
		if j is None:
			abort(404)
		return jsonify({
			"id": j.id,
			"code": j.code,
			"name": j.name,
			"country_code": j.country_code,
			"region_code": j.region_code,
			"tax_type": j.tax_type,
			"tax_authority_name": j.tax_authority_name,
			"tax_authority_reference": j.tax_authority_reference,
			"filing_frequency": j.filing_frequency,
			"is_active": j.is_active,
			"metadata": j.metadata_,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.tax.models import TaxJurisdiction
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "code", "name", "country_code", "tax_type", "tax_authority_name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		tax_type = data["tax_type"].upper()
		if tax_type not in ("VAT", "GST", "SALES_TAX", "WHT"):
			return jsonify({"ok": False, "error": "tax_type must be VAT, GST, SALES_TAX, or WHT"}), 400
		j = TaxJurisdiction(
			tenant_id=data["tenant_id"],
			code=data["code"].upper(),
			name=data["name"],
			country_code=data["country_code"].upper(),
			region_code=data.get("region_code"),
			tax_type=tax_type,
			tax_authority_name=data["tax_authority_name"],
			filing_frequency=(data.get("filing_frequency") or "MONTHLY").upper(),
			tax_authority_reference=data.get("tax_authority_reference"),
			metadata_=data.get("metadata") or {},
		)
		session.add(j)
		session.commit()
		return jsonify({"ok": True, "id": j.id}), 201

	@expose("/<string:jur_id>", methods=["PUT"])
	@has_access
	def update(self, jur_id: str):
		from pgappforge.plugins.erp.finance.tax.models import TaxJurisdiction
		session = _get_session()
		j = session.get(TaxJurisdiction, jur_id)
		if j is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "tax_authority_name", "tax_authority_reference",
		          "filing_frequency", "is_active"):
			if f in data:
				setattr(j, f, data[f])
		if "metadata" in data:
			j.metadata_ = data["metadata"]
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# TaxCodeView
# ---------------------------------------------------------------------------

class TaxCodeView(BaseView):
	"""Tax code (rate) CRUD.

	GET  /tax/codes/                     — list (JSON, filterable by jurisdiction_id)
	GET  /tax/codes/<id>                 — detail (JSON)
	POST /tax/codes/                     — create (JSON)
	GET  /tax/codes/lookup               — ?jurisdiction_code=NG-FIRS&code=STD&date=2026-01-01
	"""

	route_base = "/tax/codes"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.tax.models import TaxCode
		session = _get_session()
		jurisdiction_id = request.args.get("jurisdiction_id")
		tenant_id = request.args.get("tenant_id")
		q = sa.select(TaxCode).order_by(TaxCode.code, sa.desc(TaxCode.effective_from))
		if jurisdiction_id:
			q = q.where(TaxCode.jurisdiction_id == jurisdiction_id)
		if tenant_id:
			q = q.where(TaxCode.tenant_id == tenant_id)
		codes = session.execute(q).scalars().all()
		return jsonify({
			"tax_codes": [
				{
					"id": c.id,
					"code": c.code,
					"description": c.description,
					"jurisdiction_id": c.jurisdiction_id,
					"rate": str(c.rate),
					"effective_from": str(c.effective_from) if c.effective_from else None,
					"effective_to": str(c.effective_to) if c.effective_to else None,
					"is_input_tax": c.is_input_tax,
					"is_output_tax": c.is_output_tax,
					"is_zero_rated": c.is_zero_rated,
					"is_exempt": c.is_exempt,
					"is_active": c.is_active,
				}
				for c in codes
			]
		})

	@expose("/<string:code_id>")
	@has_access
	def detail(self, code_id: str):
		from pgappforge.plugins.erp.finance.tax.models import TaxCode
		session = _get_session()
		c = session.get(TaxCode, code_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id,
			"code": c.code,
			"description": c.description,
			"jurisdiction_id": c.jurisdiction_id,
			"rate": str(c.rate),
			"effective_from": str(c.effective_from) if c.effective_from else None,
			"effective_to": str(c.effective_to) if c.effective_to else None,
			"is_input_tax": c.is_input_tax,
			"is_output_tax": c.is_output_tax,
			"is_zero_rated": c.is_zero_rated,
			"is_exempt": c.is_exempt,
			"is_reverse_charge": c.is_reverse_charge,
			"gl_account": c.gl_account,
			"is_active": c.is_active,
			"metadata": c.metadata_,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.tax.models import TaxCode
		from decimal import Decimal
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "jurisdiction_id", "code", "description",
		            "rate", "effective_from", "gl_account")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			rate = Decimal(str(data["rate"]))
		except Exception:
			return jsonify({"ok": False, "error": "rate must be numeric"}), 400
		c = TaxCode(
			tenant_id=data["tenant_id"],
			jurisdiction_id=data["jurisdiction_id"],
			code=data["code"].upper(),
			description=data["description"],
			rate=rate,
			effective_from=date.fromisoformat(data["effective_from"]),
			effective_to=date.fromisoformat(data["effective_to"]) if data.get("effective_to") else None,
			is_input_tax=bool(data.get("is_input_tax", False)),
			is_output_tax=bool(data.get("is_output_tax", True)),
			is_zero_rated=bool(data.get("is_zero_rated", False)),
			is_exempt=bool(data.get("is_exempt", False)),
			is_reverse_charge=bool(data.get("is_reverse_charge", False)),
			gl_account=data["gl_account"],
			metadata_=data.get("metadata") or {},
		)
		session.add(c)
		session.commit()
		return jsonify({"ok": True, "id": c.id}), 201

	@expose("/lookup")
	@has_access
	def lookup(self):
		"""GET /tax/codes/lookup?jurisdiction_code=NG-FIRS&code=STD&date=2026-01-01"""
		from pgappforge.plugins.erp.finance.tax.services import TaxService, TaxCodeNotFoundError
		session = _get_session()
		jur_code = request.args.get("jurisdiction_code", "")
		code = request.args.get("code", "")
		date_str = request.args.get("date")
		tenant_id = request.args.get("tenant_id")
		as_of = date.fromisoformat(date_str) if date_str else date.today()
		svc = TaxService()
		tc = svc.get_applicable_tax_code(jur_code, code, as_of, tenant_id, session)
		if tc is None:
			return jsonify({"ok": False, "error": "no active tax code found"}), 404
		return jsonify({
			"ok": True,
			"id": tc.id,
			"code": tc.code,
			"rate": str(tc.rate),
			"is_zero_rated": tc.is_zero_rated,
			"is_exempt": tc.is_exempt,
			"gl_account": tc.gl_account,
		})


# ---------------------------------------------------------------------------
# TaxTransactionView
# ---------------------------------------------------------------------------

class TaxTransactionView(BaseView):
	"""Tax transaction log browser + manual post.

	GET  /tax/transactions/    — list (JSON, filterable)
	POST /tax/transactions/    — manually post a tax line (JSON)
	POST /tax/transactions/calculate — calculate tax without posting
	"""

	route_base = "/tax/transactions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.tax.models import TaxTransaction
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		tax_code_id = request.args.get("tax_code_id")
		period = request.args.get("period")  # e.g. "2026-01"
		q = (
			sa.select(TaxTransaction)
			.order_by(sa.desc(TaxTransaction.posting_date))
			.limit(500)
		)
		if tenant_id:
			q = q.where(TaxTransaction.tenant_id == tenant_id)
		if tax_code_id:
			q = q.where(TaxTransaction.tax_code_id == tax_code_id)
		if period:
			q = q.where(TaxTransaction.tax_period == period)
		txns = session.execute(q).scalars().all()
		return jsonify({
			"transactions": [
				{
					"id": t.id,
					"tax_code_id": t.tax_code_id,
					"source_document_type": t.source_document_type,
					"source_document_id": t.source_document_id,
					"taxable_amount_cents": t.taxable_amount_cents,
					"tax_amount_cents": t.tax_amount_cents,
					"is_recoverable": t.is_recoverable,
					"posting_date": str(t.posting_date) if t.posting_date else None,
					"tax_period": t.tax_period,
					"is_reversal": t.is_reversal,
				}
				for t in txns
			]
		})

	@expose("/", methods=["POST"])
	@has_access
	def post_transaction(self):
		from pgappforge.plugins.erp.finance.tax.services import (
			TaxService, TaxTransactionDetails, TaxServiceError,
		)
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "tax_code_id", "source_document_type",
		            "source_document_id", "taxable_amount_cents", "posting_date")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			from decimal import Decimal
			details = TaxTransactionDetails(
				tenant_id=data["tenant_id"],
				tax_code_id=data["tax_code_id"],
				source_document_type=data["source_document_type"],
				source_document_id=data["source_document_id"],
				taxable_amount_cents=int(data["taxable_amount_cents"]),
				posting_date=date.fromisoformat(data["posting_date"]),
				currency_code=data.get("currency_code", "NGN"),
				is_recoverable=bool(data.get("is_recoverable", True)),
				tax_period=data.get("tax_period"),
				exchange_rate=Decimal(str(data["exchange_rate"])) if data.get("exchange_rate") else None,
				is_reversal=bool(data.get("is_reversal", False)),
				reversal_of_id=data.get("reversal_of_id"),
			)
			txn = TaxService().post_tax_transaction(details, session)
			session.commit()
			return jsonify({
				"ok": True,
				"id": txn.id,
				"tax_amount_cents": txn.tax_amount_cents,
			}), 201
		except TaxServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/calculate", methods=["POST"])
	@has_access
	def calculate(self):
		"""POST /tax/transactions/calculate — dry-run tax calculation, no posting."""
		from pgappforge.plugins.erp.finance.tax.services import TaxService, TaxServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("amount_cents", "jurisdiction_code", "tax_code")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			as_of = date.fromisoformat(data["as_of_date"]) if data.get("as_of_date") else None
			tax_cents = TaxService().determine_tax(
				amount_cents=int(data["amount_cents"]),
				jurisdiction_code=data["jurisdiction_code"],
				tax_code_str=data["tax_code"],
				session=session,
				tenant_id=data.get("tenant_id"),
				as_of_date=as_of,
			)
			return jsonify({
				"ok": True,
				"amount_cents": int(data["amount_cents"]),
				"tax_amount_cents": tax_cents,
				"total_cents": int(data["amount_cents"]) + tax_cents,
			})
		except TaxServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# TaxReturnView
# ---------------------------------------------------------------------------

class TaxReturnView(BaseView):
	"""Tax return lifecycle management.

	GET  /tax/returns/              — list (JSON)
	GET  /tax/returns/<id>          — detail (JSON)
	POST /tax/returns/generate      — generate draft return for period
	POST /tax/returns/<id>/file     — submit to authority
	POST /tax/returns/<id>/pay      — mark as paid
	"""

	route_base = "/tax/returns"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.tax.models import TaxReturn
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		jurisdiction_id = request.args.get("jurisdiction_id")
		status = request.args.get("status")
		q = (
			sa.select(TaxReturn)
			.order_by(sa.desc(TaxReturn.period_start))
			.limit(100)
		)
		if tenant_id:
			q = q.where(TaxReturn.tenant_id == tenant_id)
		if jurisdiction_id:
			q = q.where(TaxReturn.jurisdiction_id == jurisdiction_id)
		if status:
			q = q.where(TaxReturn.status == status.upper())
		returns = session.execute(q).scalars().all()
		return jsonify({
			"tax_returns": [
				{
					"id": r.id,
					"jurisdiction_id": r.jurisdiction_id,
					"period_start": str(r.period_start) if r.period_start else None,
					"period_end": str(r.period_end) if r.period_end else None,
					"output_tax_cents": r.output_tax_cents,
					"input_tax_cents": r.input_tax_cents,
					"net_tax_cents": r.net_tax_cents,
					"status": r.status,
					"reference_number": r.reference_number,
					"filing_date": str(r.filing_date) if r.filing_date else None,
				}
				for r in returns
			]
		})

	@expose("/<string:return_id>")
	@has_access
	def detail(self, return_id: str):
		from pgappforge.plugins.erp.finance.tax.models import TaxReturn
		session = _get_session()
		r = session.get(TaxReturn, return_id)
		if r is None:
			abort(404)
		return jsonify({
			"id": r.id,
			"jurisdiction_id": r.jurisdiction_id,
			"period_start": str(r.period_start) if r.period_start else None,
			"period_end": str(r.period_end) if r.period_end else None,
			"output_tax_cents": r.output_tax_cents,
			"input_tax_cents": r.input_tax_cents,
			"net_tax_cents": r.net_tax_cents,
			"taxable_supplies_cents": r.taxable_supplies_cents,
			"exempt_supplies_cents": r.exempt_supplies_cents,
			"status": r.status,
			"reference_number": r.reference_number,
			"filing_date": str(r.filing_date) if r.filing_date else None,
			"due_date": str(r.due_date) if r.due_date else None,
			"payment_reference": r.payment_reference,
			"payment_date": str(r.payment_date) if r.payment_date else None,
			"notes": r.notes,
		})

	@expose("/generate", methods=["POST"])
	@has_access
	def generate(self):
		"""POST /tax/returns/generate — aggregate TaxTransactions into a draft return."""
		from pgappforge.plugins.erp.finance.tax.services import TaxService, TaxServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("jurisdiction_id", "period_start", "period_end")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			ret = TaxService().generate_vat_return(
				jurisdiction_id=data["jurisdiction_id"],
				period_start=date.fromisoformat(data["period_start"]),
				period_end=date.fromisoformat(data["period_end"]),
				session=session,
				tenant_id=data.get("tenant_id"),
			)
			session.commit()
			return jsonify({
				"ok": True,
				"id": ret.id,
				"output_tax_cents": ret.output_tax_cents,
				"input_tax_cents": ret.input_tax_cents,
				"net_tax_cents": ret.net_tax_cents,
				"status": ret.status,
			}), 201
		except TaxServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:return_id>/file", methods=["POST"])
	@has_access
	def file(self, return_id: str):
		from pgappforge.plugins.erp.finance.tax.services import TaxService, TaxServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		ref = data.get("reference_number", "")
		if not ref:
			return jsonify({"ok": False, "error": "reference_number required"}), 400
		filing_date = date.fromisoformat(data["filing_date"]) if data.get("filing_date") else None
		try:
			ret = TaxService().file_return(return_id, ref, session, filing_date=filing_date)
			session.commit()
			return jsonify({"ok": True, "id": ret.id, "status": ret.status})
		except TaxServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:return_id>/pay", methods=["POST"])
	@has_access
	def pay(self, return_id: str):
		from pgappforge.plugins.erp.finance.tax.services import TaxService, TaxServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		ref = data.get("payment_reference", "")
		if not ref:
			return jsonify({"ok": False, "error": "payment_reference required"}), 400
		payment_date = date.fromisoformat(data["payment_date"]) if data.get("payment_date") else None
		try:
			ret = TaxService().pay_return(return_id, ref, session, payment_date=payment_date)
			session.commit()
			return jsonify({"ok": True, "id": ret.id, "status": ret.status})
		except TaxServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# TaxReportView  (3 reports)
# ---------------------------------------------------------------------------

class TaxReportView(BaseView):
	"""Tax reports.

	GET /tax/reports/vat-return/<id>      — VAT Return detail (HTML, printable)
	GET /tax/reports/tax-liability        — Tax liability summary by jurisdiction (HTML)
	GET /tax/reports/input-tax-credit     — Input tax credit analysis (HTML)
	"""

	route_base = "/tax/reports"
	default_view = "tax_liability"

	@expose("/vat-return/<string:return_id>")
	@has_access
	def vat_return_detail(self, return_id: str):
		"""Full VAT Return report — printable format for submission or audit."""
		from pgappforge.plugins.erp.finance.tax.models import TaxJurisdiction, TaxReturn
		session = _get_session()
		r = session.get(TaxReturn, return_id)
		if r is None:
			abort(404)
		jur = session.get(TaxJurisdiction, r.jurisdiction_id)

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>VAT Return — {_he(str(r.period_start))} to {_he(str(r.period_end))}</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}} .tax-box{{border:2px solid #333;padding:12px;margin:8px 0}}
@media print{{.noprint{{display:none}}}}</style></head><body>
<div class="noprint"><button onclick="window.print()" class="btn btn-xs btn-primary">Print</button></div>
<h3>VAT Return</h3>
<dl class="dl-horizontal">
  <dt>Jurisdiction</dt><dd>{_he(jur.name if jur else r.jurisdiction_id)} ({_he(jur.code if jur else '')})</dd>
  <dt>Tax Authority</dt><dd>{_he(jur.tax_authority_name if jur else '')}</dd>
  <dt>Period</dt><dd>{_he(str(r.period_start))} to {_he(str(r.period_end))}</dd>
  <dt>Status</dt><dd><strong>{_he(r.status)}</strong></dd>
  <dt>Reference</dt><dd>{_he(r.reference_number or '—')}</dd>
  <dt>Filing Date</dt><dd>{_he(str(r.filing_date) if r.filing_date else '—')}</dd>
</dl>
<hr>
<div class="row">
  <div class="col-md-4">
    <div class="tax-box"><strong>Box 1: Output Tax</strong><br>
    <span style="font-size:1.4em">{_fmt(r.output_tax_cents)}</span></div>
  </div>
  <div class="col-md-4">
    <div class="tax-box"><strong>Box 2: Input Tax Deductible</strong><br>
    <span style="font-size:1.4em">{_fmt(r.input_tax_cents)}</span></div>
  </div>
  <div class="col-md-4">
    <div class="tax-box" style="background:#{'f5f5f5' if r.net_tax_cents >= 0 else 'fff3cd'}">
    <strong>Box 3: Net Tax {'Payable' if r.net_tax_cents >= 0 else 'Refundable'}</strong><br>
    <span style="font-size:1.6em;font-weight:bold">{_fmt(r.net_tax_cents)}</span></div>
  </div>
</div>
<dl class="dl-horizontal" style="margin-top:12px">
  <dt>Taxable Supplies</dt><dd>{_fmt(r.taxable_supplies_cents)}</dd>
  <dt>Exempt Supplies</dt><dd>{_fmt(r.exempt_supplies_cents)}</dd>
</dl>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/tax-liability")
	@has_access
	def tax_liability(self):
		"""Tax liability summary by jurisdiction for open filed returns."""
		from pgappforge.plugins.erp.finance.tax.models import TaxJurisdiction, TaxReturn
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				TaxJurisdiction.code,
				TaxJurisdiction.name,
				TaxJurisdiction.tax_type,
				TaxReturn.period_start,
				TaxReturn.period_end,
				TaxReturn.output_tax_cents,
				TaxReturn.input_tax_cents,
				TaxReturn.net_tax_cents,
				TaxReturn.status,
				TaxReturn.due_date,
			)
			.join(TaxReturn, TaxReturn.jurisdiction_id == TaxJurisdiction.id)
			.where(TaxReturn.status.in_(["FILED", "DRAFT"]))
			.where(TaxReturn.net_tax_cents > 0)
			.order_by(TaxReturn.due_date, TaxJurisdiction.code)
		)
		if tenant_id:
			q = q.where(TaxReturn.tenant_id == tenant_id)
		rows = session.execute(q).all()

		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(r.code)}</td>"
			f"<td>{_he(r.name)}</td>"
			f"<td>{_he(r.tax_type)}</td>"
			f"<td>{_he(str(r.period_start))}→{_he(str(r.period_end))}</td>"
			f"<td style='text-align:right'>{_fmt(r.output_tax_cents)}</td>"
			f"<td style='text-align:right'>{_fmt(r.input_tax_cents)}</td>"
			f"<td style='text-align:right'><strong>{_fmt(r.net_tax_cents)}</strong></td>"
			f"<td>{_he(str(r.due_date) if r.due_date else '—')}</td>"
			f"<td><span class='label label-{'warning' if r.status == 'DRAFT' else 'danger'}'>{_he(r.status)}</span></td>"
			f"</tr>"
			for r in rows
		)
		total = sum(r.net_tax_cents for r in rows)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Tax Liability Summary</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style></head><body>
<h3>Tax Liability Summary — Outstanding Returns</h3>
<table class="table table-bordered table-condensed table-hover" style="font-size:0.85em">
<thead><tr><th>Code</th><th>Jurisdiction</th><th>Type</th><th>Period</th>
<th style="text-align:right">Output</th><th style="text-align:right">Input</th>
<th style="text-align:right">Net Payable</th><th>Due Date</th><th>Status</th></tr></thead>
<tbody>{table_rows}</tbody>
<tfoot><tr class="danger"><td colspan="6"><strong>Total Outstanding</strong></td>
<td style="text-align:right"><strong>{_fmt(total)}</strong></td>
<td colspan="2"></td></tr></tfoot>
</table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/input-tax-credit")
	@has_access
	def input_tax_credit(self):
		"""Input tax credit analysis — recoverable vs irrecoverable by period."""
		from pgappforge.plugins.erp.finance.tax.models import TaxCode, TaxJurisdiction, TaxTransaction
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		period = request.args.get("period")  # e.g. "2026-01"

		q = (
			sa.select(
				TaxTransaction.tax_period,
				TaxCode.code.label("tax_code"),
				TaxJurisdiction.name.label("jurisdiction_name"),
				TaxTransaction.is_recoverable,
				sa.func.sum(TaxTransaction.taxable_amount_cents).label("total_taxable"),
				sa.func.sum(TaxTransaction.tax_amount_cents).label("total_tax"),
				sa.func.count(TaxTransaction.id).label("line_count"),
			)
			.join(TaxCode, TaxTransaction.tax_code_id == TaxCode.id)
			.join(TaxJurisdiction, TaxCode.jurisdiction_id == TaxJurisdiction.id)
			.where(TaxCode.is_input_tax.is_(True))
			.group_by(
				TaxTransaction.tax_period,
				TaxCode.code,
				TaxJurisdiction.name,
				TaxTransaction.is_recoverable,
			)
			.order_by(TaxTransaction.tax_period, TaxJurisdiction.name, TaxCode.code)
		)
		if tenant_id:
			q = q.where(TaxTransaction.tenant_id == tenant_id)
		if period:
			q = q.where(TaxTransaction.tax_period == period)
		rows = session.execute(q).all()

		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(r.tax_period or '—')}</td>"
			f"<td>{_he(r.jurisdiction_name)}</td>"
			f"<td>{_he(r.tax_code)}</td>"
			f"<td>{'<span class=\"label label-success\">Recoverable</span>' if r.is_recoverable else '<span class=\"label label-default\">Blocked</span>'}</td>"
			f"<td style='text-align:right'>{_fmt(int(r.total_taxable or 0))}</td>"
			f"<td style='text-align:right'><strong>{_fmt(int(r.total_tax or 0))}</strong></td>"
			f"<td style='text-align:right'>{r.line_count}</td>"
			f"</tr>"
			for r in rows
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Input Tax Credit Analysis</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style></head><body>
<h3>Input Tax Credit Analysis</h3>
<table class="table table-bordered table-condensed table-hover" style="font-size:0.85em">
<thead><tr><th>Period</th><th>Jurisdiction</th><th>Tax Code</th><th>Recoverability</th>
<th style="text-align:right">Taxable Base</th><th style="text-align:right">Tax Amount</th>
<th style="text-align:right">Lines</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"TaxJurisdictionView",
	"TaxCodeView",
	"TaxTransactionView",
	"TaxReturnView",
	"TaxReportView",
]
