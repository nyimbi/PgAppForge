"""
pgappforge/plugins/erp/hcm/payroll/views.py

Flask views for the HCM Payroll plugin.

Registered views:
  PayrollCalendarView   — CRUD
  PayrollRunView        — CRUD + calculate/approve/pay/bank-file/post-gl actions
  PayslipView           — list/detail + reverse action
  TaxWithholdingView    — CRUD
  PayrollReportView     — 3 canned reports:
                          * Payroll Summary (per run)
                          * Payslip Register (per employee/period)
                          * Statutory Summary (annual entity roll-up)

All mutating endpoints: POST/PUT JSON → JSON.
List/detail: HTML for FAB list rendering; JSON available via ?format=json.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge import expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
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
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>'
		'<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/3.4.1/css/bootstrap.min.css" integrity="sha384-HSMxcRTRxnN+Bdg0JdbxYKrThecOKuH5zCYotlSAcp1+c8xmyTe9GYg1l9a69psu" crossorigin="anonymous">'
		'<style>body{padding:24px} @media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


_PAYROLL_COUNTRY_CODES = ("KE", "UG", "TZ", "RW", "GH", "NG", "ZA", "ET")


def _payroll_run_country_code(run: object) -> str:
	meta = getattr(run, "metadata_", None) or {}
	if isinstance(meta, dict):
		for key in ("country_code", "country", "jurisdiction_code"):
			value = meta.get(key)
			if value:
				return str(value).upper()
	return str(getattr(run, "country_code", "") or "").upper()


def _payroll_country_breakdown(run: object) -> list[dict[str, int | str]]:
	breakdown = {
		code: {
			"country_code": code,
			"employee_count": 0,
			"total_gross_cents": 0,
			"total_net_cents": 0,
		}
		for code in _PAYROLL_COUNTRY_CODES
	}
	meta = getattr(run, "metadata_", None) or {}
	source = meta.get("country_breakdown") if isinstance(meta, dict) else None
	if isinstance(source, dict):
		source = [
			{"country_code": code, **(values if isinstance(values, dict) else {})}
			for code, values in source.items()
		]
	if isinstance(source, list):
		for row in source:
			if not isinstance(row, dict):
				continue
			code = str(row.get("country_code", "")).upper()
			if code in breakdown:
				breakdown[code]["employee_count"] = int(row.get("employee_count") or 0)
				breakdown[code]["total_gross_cents"] = int(row.get("total_gross_cents") or 0)
				breakdown[code]["total_net_cents"] = int(row.get("total_net_cents") or 0)
		return list(breakdown.values())

	code = _payroll_run_country_code(run)
	if code in breakdown:
		breakdown[code]["employee_count"] = int(getattr(run, "employee_count", 0) or 0)
		breakdown[code]["total_gross_cents"] = int(getattr(run, "total_gross_cents", 0) or 0)
		breakdown[code]["total_net_cents"] = int(getattr(run, "total_net_cents", 0) or 0)
	return list(breakdown.values())


def _payroll_compliance_status() -> dict[str, dict[str, str]]:
	return {
		code: {
			"status": "TODO",
			"note": "TODO: wire statutory filing/compliance model for this country.",
		}
		for code in _PAYROLL_COUNTRY_CODES
	}


def _payslip_is_mobile_money(payslip: object) -> bool:
	for attr in ("mobile_money_provider", "wallet_msisdn", "payment_channel", "payment_method"):
		value = getattr(payslip, attr, None)
		if value and "MOBILE" in str(value).upper():
			return True
	ref = str(getattr(payslip, "payment_reference", "") or "").upper()
	return any(token in ref for token in ("MPESA", "M-PESA", "MTN", "AIRTEL", "FLUTTERWAVE", "MOBILE_MONEY"))


def _mobile_money_rate_pct(payslips: list[object]) -> float:
	total = len(payslips)
	if total == 0:
		return 0.0
	mobile_count = sum(1 for payslip in payslips if _payslip_is_mobile_money(payslip))
	return round((mobile_count / total) * 100, 2)


# ---------------------------------------------------------------------------
# PayrollCalendarView
# ---------------------------------------------------------------------------

class PayrollCalendarView(BaseERPView):
	"""Payroll calendar CRUD.

	GET  /payroll/calendars/          — list
	GET  /payroll/calendars/<id>      — detail
	POST /payroll/calendars/          — create
	PUT  /payroll/calendars/<id>      — update
	"""

	route_base = "/payroll/calendars"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollCalendar
		session = _get_session()
		q = sa.select(PayrollCalendar).order_by(sa.desc(PayrollCalendar.fiscal_year), PayrollCalendar.name)
		if request.args.get("tenant_id"):
			q = q.where(PayrollCalendar.tenant_id == request.args["tenant_id"])
		if request.args.get("entity_id"):
			q = q.where(PayrollCalendar.entity_id == request.args["entity_id"])
		cals = session.execute(q.limit(200)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"calendars": [
				{
					"id": c.id, "name": c.name, "entity_id": c.entity_id,
					"pay_frequency": c.pay_frequency, "fiscal_year": c.fiscal_year,
					"is_active": c.is_active,
				}
				for c in cals
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(c.name)}</td>"
			f"<td>{_he(c.pay_frequency)}</td>"
			f"<td>{_he(c.fiscal_year)}</td>"
			f"<td>{'<span class=\"label label-success\">Yes</span>' if c.is_active else '<span class=\"label label-default\">No</span>'}</td>"
			f"<td><a href='/payroll/calendars/{_he(c.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for c in cals
		)
		body = (
			'<h3>Payroll Calendars</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Name</th><th>Frequency</th><th>Year</th><th>Active</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Payroll Calendars", body), 200)

	@expose("/<string:calendar_id>")
	@has_access
	def detail(self, calendar_id: str):
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollCalendar
		session = _get_session()
		cal = session.get(PayrollCalendar, calendar_id)
		if cal is None:
			abort(404)
		return jsonify({
			"id": cal.id, "tenant_id": cal.tenant_id, "entity_id": cal.entity_id,
			"name": cal.name, "pay_frequency": cal.pay_frequency,
			"fiscal_year": cal.fiscal_year, "is_active": cal.is_active,
			"periods": cal.periods,
			"created_at": cal.created_at.isoformat() if cal.created_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollCalendar
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "entity_id", "name", "pay_frequency", "fiscal_year")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		valid_freqs = ("WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY")
		if data["pay_frequency"] not in valid_freqs:
			return jsonify({"ok": False, "error": f"pay_frequency must be one of {valid_freqs}"}), 400

		cal = PayrollCalendar(
			tenant_id=data["tenant_id"],
			entity_id=data["entity_id"],
			name=data["name"],
			pay_frequency=data["pay_frequency"],
			fiscal_year=int(data["fiscal_year"]),
			periods=data.get("periods") or [],
			is_active=bool(data.get("is_active", True)),
		)
		session.add(cal)
		session.commit()
		return jsonify({"ok": True, "id": cal.id}), 201

	@expose("/<string:calendar_id>", methods=["PUT"])
	@has_access
	def update(self, calendar_id: str):
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollCalendar
		session = _get_session()
		cal = session.get(PayrollCalendar, calendar_id)
		if cal is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for field in ("name", "pay_frequency", "fiscal_year", "periods", "is_active"):
			if field in data:
				setattr(cal, field, data[field])
		cal.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# PayrollRunView
# ---------------------------------------------------------------------------

class PayrollRunView(BaseERPView):
	"""Payroll run CRUD + lifecycle actions.

	GET  /payroll/runs/                        — list
	GET  /payroll/runs/<id>                    — detail
	GET  /payroll/runs/<id>/dashboard          — KPI dashboard (HTML)
	POST /payroll/runs/                        — create (DRAFT)
	POST /payroll/runs/<id>/calculate          — run calculate_payrun()
	POST /payroll/runs/<id>/approve            — CALCULATED → APPROVED
	POST /payroll/runs/<id>/pay                — APPROVED → PAID
	GET  /payroll/runs/<id>/bank-file          — generate ISO 20022 XML
	POST /payroll/runs/<id>/post-gl            — post to GL
	"""

	route_base = "/payroll/runs"
	default_view = "list"
	search_columns = ["status", "payroll_type", "entity_id", "country_code"]
	list_columns = ["entity_id", "period_start", "period_end", "pay_date", "payroll_type", "status", "employee_count", "total_gross_cents", "total_net_cents"]
	import_columns = list_columns
	show_import = True

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun
		session = _get_session()
		q = sa.select(PayrollRun).order_by(sa.desc(PayrollRun.period_start))
		for field, col in (
			("tenant_id", PayrollRun.tenant_id),
			("entity_id", PayrollRun.entity_id),
			("status", PayrollRun.status),
			("payroll_type", PayrollRun.payroll_type),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		runs = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"payroll_runs": [
				{
					"id": r.id, "entity_id": r.entity_id,
					"period_start": r.period_start.isoformat() if r.period_start else None,
					"period_end": r.period_end.isoformat() if r.period_end else None,
					"pay_date": r.pay_date.isoformat() if r.pay_date else None,
					"payroll_type": r.payroll_type,
					"status": r.status,
					"employee_count": r.employee_count,
					"total_gross_cents": r.total_gross_cents,
					"total_net_cents": r.total_net_cents,
				}
				for r in runs
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(r.period_start)} – {_he(r.period_end)}</td>"
			f"<td>{_he(r.payroll_type)}</td>"
			f"<td>{r.employee_count}</td>"
			f"<td class='text-right'>{r.total_gross_cents / 100:,.2f}</td>"
			f"<td class='text-right'>{r.total_net_cents / 100:,.2f}</td>"
			f"<td><span class='label label-{'success' if r.status=='PAID' else 'info'}'>{_he(r.status)}</span></td>"
			f"<td><a href='/payroll/runs/{_he(r.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for r in runs
		)
		body = (
			'<h3>Payroll Runs</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Period</th><th>Type</th><th>Employees</th>'
			'<th>Gross</th><th>Net</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Payroll Runs", body), 200)

	@expose("/<string:run_id>")
	@has_access
	def detail(self, run_id: str):
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun
		session = _get_session()
		run = session.get(PayrollRun, run_id)
		if run is None:
			abort(404)
		return jsonify({
			"id": run.id, "tenant_id": run.tenant_id, "entity_id": run.entity_id,
			"calendar_id": run.calendar_id,
			"period_start": run.period_start.isoformat() if run.period_start else None,
			"period_end": run.period_end.isoformat() if run.period_end else None,
			"pay_date": run.pay_date.isoformat() if run.pay_date else None,
			"payroll_type": run.payroll_type, "status": run.status,
			"employee_count": run.employee_count,
			"total_gross_cents": run.total_gross_cents,
			"total_employee_tax_cents": run.total_employee_tax_cents,
			"total_employer_tax_cents": run.total_employer_tax_cents,
			"total_net_cents": run.total_net_cents,
			"calculated_at": run.calculated_at.isoformat() if run.calculated_at else None,
			"approved_by": run.approved_by,
			"approved_at": run.approved_at.isoformat() if run.approved_at else None,
			"paid_at": run.paid_at.isoformat() if run.paid_at else None,
			"gl_journal_id": run.gl_journal_id,
		})

	@expose("/<string:run_id>/dashboard")
	@has_access
	def dashboard(self, run_id: str):
		"""KPI dashboard for a single payroll run."""
		from flask import render_template
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip

		session = _get_session()
		run = session.get(PayrollRun, run_id)
		if run is None:
			abort(404)

		# Load payslips for this run
		payslips = session.execute(
			sa.select(Payslip)
			.where(Payslip.payrun_id == run_id)
			.where(Payslip.status != "REVERSED")
			.order_by(Payslip.employee_id).limit(100)
		).scalars().all()

		# ── KPI cards ───────────────────────────────────────────────────
		emp_count = run.employee_count or len(payslips)
		gross = (run.total_gross_cents or 0) / 100
		tax = (run.total_employee_tax_cents or 0) / 100
		net = (run.total_net_cents or 0) / 100

		kpi_html = self.kpi_cards([
			{
				"value": emp_count,
				"label": "Employees",
				"format": "integer",
				"icon": "fa-users",
				"color": "#1a56db",
			},
			{
				"value": gross,
				"label": "Gross Pay",
				"format": "currency",
				"icon": "fa-dollar",
				"color": "#0e9f6e",
			},
			{
				"value": tax,
				"label": "Total Tax",
				"format": "currency",
				"icon": "fa-bank",
				"color": "#e02424",
			},
			{
				"value": net,
				"label": "Net Pay",
				"format": "currency",
				"icon": "fa-money",
				"color": "#1a56db",
			},
		])

		# ── Approval buttons (BPM) ──────────────────────────────────────
		approval_html = None
		if getattr(run, "process_instance_id", None):
			approval_html = self.approval_buttons(
				run,
				advance_url="/workflow/advance",
				reject_url="/workflow/reject",
				instance_id_col="process_instance_id",
				step_col="current_step",
			)

		return render_template(
			"hcm_payroll_dash/payroll_run_dashboard.html",
			payrun=run,
			payslips=payslips,
			statutory_totals=None,
			kpi_html=kpi_html,
			approval_html=approval_html,
			country_breakdown=_payroll_country_breakdown(run),
			compliance_status=_payroll_compliance_status(),
			mobile_money_rate_pct=_mobile_money_rate_pct(payslips),
		)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "entity_id", "period_start", "period_end", "pay_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		valid_types = ("REGULAR", "OFF_CYCLE", "BONUS", "TERMINATION")
		payroll_type = data.get("payroll_type", "REGULAR")
		if payroll_type not in valid_types:
			return jsonify({"ok": False, "error": f"payroll_type must be one of {valid_types}"}), 400

		run = PayrollRun(
			tenant_id=data["tenant_id"],
			entity_id=data["entity_id"],
			calendar_id=data.get("calendar_id"),
			period_start=date_type.fromisoformat(data["period_start"]),
			period_end=date_type.fromisoformat(data["period_end"]),
			pay_date=date_type.fromisoformat(data["pay_date"]),
			payroll_type=payroll_type,
			status="DRAFT",
			notes=data.get("notes"),
		)
		session.add(run)
		session.commit()
		return jsonify({"ok": True, "id": run.id}), 201

	@expose("/<string:run_id>/calculate", methods=["POST"])
	@has_access
	def calculate(self, run_id: str):
		from pgappforge.plugins.erp.hcm.payroll.services import PayrollService, PayrollServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		employee_data = data.get("employee_data")
		if not employee_data:
			return jsonify({"ok": False, "error": "employee_data required"}), 400
		svc = PayrollService()
		try:
			run = svc.calculate_payrun(run_id, session, employee_data=employee_data)
			session.commit()
			return jsonify({
				"ok": True,
				"status": run.status,
				"employee_count": run.employee_count,
				"total_gross_cents": run.total_gross_cents,
				"total_net_cents": run.total_net_cents,
				"calculated_at": run.calculated_at.isoformat() if run.calculated_at else None,
			})
		except PayrollServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:run_id>/approve", methods=["POST"])
	@has_access
	def approve(self, run_id: str):
		from pgappforge.plugins.erp.hcm.payroll.services import PayrollService, PayrollServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		approver_id = data.get("approver_id")
		if not approver_id:
			return jsonify({"ok": False, "error": "approver_id required"}), 400
		svc = PayrollService()
		try:
			run = svc.approve_payrun(run_id, approver_id, session)
			session.commit()
			return jsonify({"ok": True, "status": run.status, "approved_at": run.approved_at.isoformat()})
		except PayrollServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:run_id>/pay", methods=["POST"])
	@has_access
	def pay(self, run_id: str):
		from pgappforge.plugins.erp.hcm.payroll.services import PayrollService, PayrollServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		svc = PayrollService()
		try:
			run = svc.mark_paid(run_id, session, bank_file_ref=data.get("bank_file_ref", ""))
			session.commit()
			return jsonify({"ok": True, "status": run.status, "paid_at": run.paid_at.isoformat()})
		except PayrollServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:run_id>/bank-file")
	@has_access
	def bank_file(self, run_id: str):
		from pgappforge.plugins.erp.hcm.payroll.services import PayrollService, PayrollServiceError
		session = _get_session()
		svc = PayrollService()
		try:
			xml = svc.generate_bank_file(run_id, session)
			if request.args.get("format") == "json":
				return jsonify({"ok": True, "xml": xml})
			resp = make_response(xml, 200)
			resp.headers["Content-Type"] = "application/xml"
			resp.headers["Content-Disposition"] = f'attachment; filename="payroll-{run_id[:8]}.xml"'
			return resp
		except PayrollServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:run_id>/post-gl", methods=["POST"])
	@has_access
	def post_gl(self, run_id: str):
		from pgappforge.plugins.erp.hcm.payroll.services import PayrollService, PayrollServiceError
		session = _get_session()
		svc = PayrollService()
		try:
			journal = svc.post_to_gl(run_id, session)
			session.commit()
			return jsonify({"ok": True, "journal": journal})
		except PayrollServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# PayslipView
# ---------------------------------------------------------------------------

class PayslipView(BaseERPView):
	"""Payslip list/detail + reversal.

	GET  /payroll/payslips/                   — list (filter by payrun_id / employee_id)
	GET  /payroll/payslips/<id>               — detail with lines
	POST /payroll/payslips/<id>/reverse       — reverse a PAID payslip
	"""

	route_base = "/payroll/payslips"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.payroll.models import Payslip
		session = _get_session()
		q = sa.select(Payslip).order_by(sa.desc(Payslip.created_at))
		for field, col in (
			("payrun_id", Payslip.payrun_id),
			("employee_id", Payslip.employee_id),
			("status", Payslip.status),
			("tenant_id", Payslip.tenant_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		payslips = session.execute(q.limit(1000)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"payslips": [
				{
					"id": p.id, "payrun_id": p.payrun_id,
					"employee_id": p.employee_id,
					"gross_pay_cents": p.gross_pay_cents,
					"net_pay_cents": p.net_pay_cents,
					"currency_code": p.currency_code,
					"status": p.status,
				}
				for p in payslips
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(p.employee_id)}</td>"
			f"<td class='text-right'>{p.gross_pay_cents / 100:,.2f}</td>"
			f"<td class='text-right'>{p.net_pay_cents / 100:,.2f}</td>"
			f"<td>{_he(p.currency_code)}</td>"
			f"<td><span class='label label-{'success' if p.status=='PAID' else 'default'}'>{_he(p.status)}</span></td>"
			f"<td><a href='/payroll/payslips/{_he(p.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for p in payslips
		)
		body = (
			'<h3>Payslips</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Employee</th><th>Gross</th><th>Net</th><th>CCY</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Payslips", body), 200)

	@expose("/<string:payslip_id>")
	@has_access
	def detail(self, payslip_id: str):
		from pgappforge.plugins.erp.hcm.payroll.models import Payslip
		session = _get_session()
		ps = session.get(Payslip, payslip_id)
		if ps is None:
			abort(404)
		return jsonify({
			"id": ps.id, "tenant_id": ps.tenant_id,
			"payrun_id": ps.payrun_id, "employee_id": ps.employee_id,
			"gross_pay_cents": ps.gross_pay_cents,
			"income_tax_cents": ps.income_tax_cents,
			"national_insurance_cents": ps.national_insurance_cents,
			"pension_employee_cents": ps.pension_employee_cents,
			"pension_employer_cents": ps.pension_employer_cents,
			"other_deductions_cents": ps.other_deductions_cents,
			"net_pay_cents": ps.net_pay_cents,
			"bank_account_iban": ps.bank_account_iban,
			"currency_code": ps.currency_code,
			"payment_reference": ps.payment_reference,
			"status": ps.status,
			"lines": [
				{
					"id": l.id, "line_type": l.line_type,
					"description": l.description,
					"units": str(l.units), "rate_cents": l.rate_cents,
					"amount_cents": l.amount_cents,
					"is_employer_cost": l.is_employer_cost,
					"gl_account": l.gl_account, "cost_center": l.cost_center,
				}
				for l in ps.lines
			],
		})

	@expose("/<string:payslip_id>/reverse", methods=["POST"])
	@has_access
	def reverse(self, payslip_id: str):
		from pgappforge.plugins.erp.hcm.payroll.services import PayrollService, PayrollServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		reason = data.get("reason", "")
		if not reason:
			return jsonify({"ok": False, "error": "reason required for payslip reversal"}), 400
		svc = PayrollService()
		try:
			reversal = svc.reverse_payslip(payslip_id, reason, session)
			session.commit()
			return jsonify({
				"ok": True,
				"reversal_payslip_id": reversal.id,
				"net_pay_cents": reversal.net_pay_cents,
				"status": reversal.status,
			})
		except PayrollServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# TaxWithholdingView
# ---------------------------------------------------------------------------

class TaxWithholdingView(BaseERPView):
	"""Tax withholding configuration CRUD.

	GET  /payroll/tax-withholding/             — list (filter by employee_id)
	GET  /payroll/tax-withholding/<id>         — detail
	POST /payroll/tax-withholding/             — create
	PUT  /payroll/tax-withholding/<id>         — update
	"""

	route_base = "/payroll/tax-withholding"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.payroll.models import TaxWithholding
		session = _get_session()
		q = sa.select(TaxWithholding).order_by(sa.desc(TaxWithholding.effective_from))
		if request.args.get("employee_id"):
			q = q.where(TaxWithholding.employee_id == request.args["employee_id"])
		if request.args.get("jurisdiction_code"):
			q = q.where(TaxWithholding.jurisdiction_code == request.args["jurisdiction_code"])
		rows = session.execute(q.limit(500)).scalars().all()
		return jsonify({"tax_withholding": [
			{
				"id": r.id, "employee_id": r.employee_id,
				"jurisdiction_code": r.jurisdiction_code,
				"filing_status": r.filing_status,
				"allowances": r.allowances,
				"additional_withholding_cents": r.additional_withholding_cents,
				"effective_from": r.effective_from.isoformat() if r.effective_from else None,
			}
			for r in rows
		]})

	@expose("/<string:wh_id>")
	@has_access
	def detail(self, wh_id: str):
		from pgappforge.plugins.erp.hcm.payroll.models import TaxWithholding
		session = _get_session()
		wh = session.get(TaxWithholding, wh_id)
		if wh is None:
			abort(404)
		return jsonify({
			"id": wh.id, "tenant_id": wh.tenant_id,
			"employee_id": wh.employee_id,
			"jurisdiction_code": wh.jurisdiction_code,
			"filing_status": wh.filing_status,
			"allowances": wh.allowances,
			"additional_withholding_cents": wh.additional_withholding_cents,
			"effective_from": wh.effective_from.isoformat() if wh.effective_from else None,
			"notes": wh.notes,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.payroll.models import TaxWithholding
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "employee_id", "jurisdiction_code", "effective_from")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		add_wh = int(data.get("additional_withholding_cents", 0))
		assert isinstance(add_wh, int), "additional_withholding_cents must be int"

		wh = TaxWithholding(
			tenant_id=data["tenant_id"],
			employee_id=data["employee_id"],
			jurisdiction_code=data["jurisdiction_code"],
			filing_status=data.get("filing_status"),
			allowances=int(data.get("allowances", 0)),
			additional_withholding_cents=add_wh,
			effective_from=date_type.fromisoformat(data["effective_from"]),
			notes=data.get("notes"),
		)
		session.add(wh)
		session.commit()
		return jsonify({"ok": True, "id": wh.id}), 201

	@expose("/<string:wh_id>", methods=["PUT"])
	@has_access
	def update(self, wh_id: str):
		from pgappforge.plugins.erp.hcm.payroll.models import TaxWithholding
		session = _get_session()
		wh = session.get(TaxWithholding, wh_id)
		if wh is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for field in ("filing_status", "allowances", "additional_withholding_cents", "notes"):
			if field in data:
				setattr(wh, field, data[field])
		wh.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# PayrollReportView — 3 canned reports
# ---------------------------------------------------------------------------

class PayrollReportView(BaseERPView):
	"""Payroll canned reports.

	GET /payroll/reports/summary         — Payroll Run Summary (per run)
	GET /payroll/reports/register        — Payslip Register (per employee/period)
	GET /payroll/reports/statutory       — Statutory Summary (annual roll-up)
	"""

	route_base = "/payroll/reports"
	default_view = "summary"

	@expose("/summary")
	@has_access
	def summary(self):
		"""Payroll Run Summary — gross/tax/net per run for a given entity/period."""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun
		session = _get_session()
		entity_id = request.args.get("entity_id")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(PayrollRun)
			.where(PayrollRun.status.in_(["CALCULATED", "APPROVED", "PAID"]))
			.order_by(sa.desc(PayrollRun.period_start))
		)
		if entity_id:
			q = q.where(PayrollRun.entity_id == entity_id)
		if tenant_id:
			q = q.where(PayrollRun.tenant_id == tenant_id)
		runs = session.execute(q.limit(200)).scalars().all()

		data = [
			{
				"id": r.id,
				"period": f"{r.period_start} – {r.period_end}",
				"pay_date": r.pay_date.isoformat() if r.pay_date else None,
				"payroll_type": r.payroll_type,
				"status": r.status,
				"employee_count": r.employee_count,
				"total_gross_cents": r.total_gross_cents,
				"total_employee_tax_cents": r.total_employee_tax_cents,
				"total_employer_tax_cents": r.total_employer_tax_cents,
				"total_net_cents": r.total_net_cents,
			}
			for r in runs
		]

		if request.args.get("format") == "json":
			return jsonify({"payroll_summary": data})

		total_gross = sum(d["total_gross_cents"] for d in data)
		total_net = sum(d["total_net_cents"] for d in data)

		trs = "".join(
			f"<tr>"
			f"<td>{_he(d['period'])}</td>"
			f"<td>{_he(d['pay_date'])}</td>"
			f"<td>{_he(d['payroll_type'])}</td>"
			f"<td class='text-right'>{d['employee_count']}</td>"
			f"<td class='text-right'>{d['total_gross_cents'] / 100:,.2f}</td>"
			f"<td class='text-right'>{d['total_employee_tax_cents'] / 100:,.2f}</td>"
			f"<td class='text-right'>{d['total_net_cents'] / 100:,.2f}</td>"
			f"<td><span class='label label-{'success' if d['status']=='PAID' else 'info'}'>{_he(d['status'])}</span></td>"
			f"</tr>"
			for d in data
		)
		body = (
			'<h3>Payroll Run Summary</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Period</th><th>Pay Date</th><th>Type</th><th>Employees</th>'
			'<th>Gross</th><th>Tax</th><th>Net</th><th>Status</th></tr></thead>'
			f'<tbody>{trs}'
			f'<tr class="info"><td colspan="4"><strong>Total</strong></td>'
			f'<td class="text-right"><strong>{total_gross / 100:,.2f}</strong></td><td></td>'
			f'<td class="text-right"><strong>{total_net / 100:,.2f}</strong></td><td></td></tr>'
			f'</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Payroll Summary", body), 200)

	@expose("/register")
	@has_access
	def register(self):
		"""Payslip Register — per-employee gross/deductions/net for a payrun."""
		from pgappforge.plugins.erp.hcm.payroll.models import Payslip
		session = _get_session()
		payrun_id = request.args.get("payrun_id")
		if not payrun_id:
			return jsonify({"error": "payrun_id required"}), 400

		payslips = session.execute(
			sa.select(Payslip)
			.where(Payslip.payrun_id == payrun_id)
			.where(Payslip.status != "REVERSED")
			.order_by(Payslip.employee_id)
		).scalars().all()

		data = [
			{
				"employee_id": p.employee_id,
				"gross_pay_cents": p.gross_pay_cents,
				"income_tax_cents": p.income_tax_cents,
				"ni_cents": p.national_insurance_cents,
				"pension_employee_cents": p.pension_employee_cents,
				"pension_employer_cents": p.pension_employer_cents,
				"other_deductions_cents": p.other_deductions_cents,
				"net_pay_cents": p.net_pay_cents,
				"currency_code": p.currency_code,
				"status": p.status,
			}
			for p in payslips
		]

		if request.args.get("format") == "json":
			return jsonify({"payrun_id": payrun_id, "payslip_register": data})

		trs = "".join(
			f"<tr>"
			f"<td style='font-size:0.8em'>{_he(d['employee_id'])}</td>"
			f"<td class='text-right'>{d['gross_pay_cents'] / 100:,.2f}</td>"
			f"<td class='text-right'>{d['income_tax_cents'] / 100:,.2f}</td>"
			f"<td class='text-right'>{d['ni_cents'] / 100:,.2f}</td>"
			f"<td class='text-right'>{d['pension_employee_cents'] / 100:,.2f}</td>"
			f"<td class='text-right'>{d['net_pay_cents'] / 100:,.2f}</td>"
			f"</tr>"
			for d in data
		)
		total_net = sum(d["net_pay_cents"] for d in data)
		body = (
			f'<h3>Payslip Register — Run {_he(payrun_id[:8])}</h3>'
			'<table class="table table-bordered table-condensed table-hover" style="font-size:0.85em">'
			'<thead><tr><th>Employee</th><th>Gross</th><th>Income Tax</th>'
			'<th>NI</th><th>Pension</th><th>Net Pay</th></tr></thead>'
			f'<tbody>{trs}'
			f'<tr class="info"><td><strong>Total</strong></td><td colspan="4"></td>'
			f'<td class="text-right"><strong>{total_net / 100:,.2f}</strong></td></tr>'
			f'</tbody></table>'
		)
		return make_response(_page_html("Payslip Register", body), 200)

	@expose("/statutory")
	@has_access
	def statutory(self):
		"""Statutory Payroll Summary — annual roll-up for government submission."""
		from pgappforge.plugins.erp.hcm.payroll.services import PayrollService, PayrollServiceError
		session = _get_session()
		entity_id = request.args.get("entity_id")
		year = request.args.get("year")
		if not entity_id or not year:
			return jsonify({"error": "entity_id and year required"}), 400
		svc = PayrollService()
		try:
			report = svc.statutory_report(entity_id, int(year), session)
		except PayrollServiceError as exc:
			return jsonify({"error": str(exc)}), 400

		if request.args.get("format") == "json":
			return jsonify(report)

		body = (
			f'<h3>Statutory Payroll Summary — {_he(year)}</h3>'
			f'<dl class="dl-horizontal">'
			f'<dt>Entity ID</dt><dd>{_he(entity_id)}</dd>'
			f'<dt>Total Employees</dt><dd>{report["total_employees"]}</dd>'
			f'<dt>Total Gross</dt><dd>{report["total_gross_cents"] / 100:,.2f}</dd>'
			f'<dt>Income Tax</dt><dd>{report["total_income_tax_cents"] / 100:,.2f}</dd>'
			f'<dt>NI (Employee)</dt><dd>{report["total_ni_employee_cents"] / 100:,.2f}</dd>'
			f'<dt>Pension (Employee)</dt><dd>{report["total_pension_employee_cents"] / 100:,.2f}</dd>'
			f'<dt>Pension (Employer)</dt><dd>{report["total_pension_employer_cents"] / 100:,.2f}</dd>'
			f'<dt>Total Net Pay</dt><dd><strong>{report["total_net_cents"] / 100:,.2f}</strong></dd>'
			f'</dl>'
			f'<p style="color:#888;font-size:0.75em">Generated {report["generated_at"]}</p>'
		)
		return make_response(_page_html(f"Statutory Summary {year}", body), 200)


__all__ = [
	"PayrollCalendarView",
	"PayrollRunView",
	"PayslipView",
	"TaxWithholdingView",
	"PayrollReportView",
]
