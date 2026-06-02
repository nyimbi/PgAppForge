"""
pgappforge/plugins/erp/hcm/personnel/views.py

Flask views for the HCM Personnel Administration plugin.

Registered views:
  EmployeeView           — CRUD + terminate/transfer actions
  EmployeeCompensationView — read + record change (immutable ledger)
  EmployeeDocumentView   — CRUD + verify action
  PersonnelReportView    — 3 canned reports:
                           * Employee Roster
                           * Compensation Summary
                           * Document Expiry Alert
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
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
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>body{padding:24px} @media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


# ---------------------------------------------------------------------------
# EmployeeView
# ---------------------------------------------------------------------------

class EmployeeView(BaseView):
	"""Employee master CRUD + lifecycle actions.

	GET  /hcm/personnel/employees/                    — list
	GET  /hcm/personnel/employees/<id>                — detail
	POST /hcm/personnel/employees/                    — hire
	PUT  /hcm/personnel/employees/<id>                — update non-sensitive fields
	POST /hcm/personnel/employees/<id>/terminate      — terminate
	POST /hcm/personnel/employees/<id>/transfer       — transfer/reassign
	"""

	route_base = "/hcm/personnel/employees"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		session = _get_session()
		q = sa.select(Employee).order_by(Employee.employee_number)
		for arg, col in (
			("entity_id", Employee.entity_id),
			("employment_status", Employee.employment_status),
			("employment_type", Employee.employment_type),
			("org_unit_id", Employee.org_unit_id),
		):
			val = request.args.get(arg)
			if val:
				q = q.where(col == val)
		employees = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"employees": [
				{
					"id": e.id, "employee_number": e.employee_number,
					"entity_id": e.entity_id, "org_unit_id": e.org_unit_id,
					"position_id": e.position_id, "manager_id": e.manager_id,
					"employment_type": e.employment_type,
					"employment_status": e.employment_status,
					"start_date": e.start_date.isoformat() if e.start_date else None,
				}
				for e in employees
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(e.employee_number)}</td>"
			f"<td>{_he(e.employment_type)}</td>"
			f"<td><span class='label label-{'success' if e.employment_status=='ACTIVE' else 'warning'}'>{_he(e.employment_status)}</span></td>"
			f"<td>{_he(e.start_date)}</td>"
			f"<td><a href='/hcm/personnel/employees/{_he(e.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for e in employees
		)
		body = (
			'<h3>Employees</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Employee #</th><th>Type</th><th>Status</th><th>Start Date</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Employees", body), 200)

	@expose("/<string:employee_id>")
	@has_access
	def detail(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		session = _get_session()
		e = session.get(Employee, employee_id)
		if e is None:
			abort(404)
		return jsonify({
			"id": e.id, "tenant_id": e.tenant_id,
			"employee_number": e.employee_number, "party_id": e.party_id,
			"position_id": e.position_id, "entity_id": e.entity_id,
			"org_unit_id": e.org_unit_id, "manager_id": e.manager_id,
			"employment_type": e.employment_type,
			"employment_status": e.employment_status,
			"start_date": e.start_date.isoformat() if e.start_date else None,
			"probation_end_date": e.probation_end_date.isoformat() if e.probation_end_date else None,
			"termination_date": e.termination_date.isoformat() if e.termination_date else None,
			"termination_type": e.termination_type,
			"termination_reason": e.termination_reason,
			"rehire_eligible": e.rehire_eligible,
			"cost_center_code": e.cost_center_code,
			"bank_bic": e.bank_bic,
			# NOTE: encrypted fields never returned in API — callers must go through
			# the decryption service layer directly
			"created_at": e.created_at.isoformat() if e.created_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def hire(self):
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService, PersonnelServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			emp = PersonnelService().hire_employee(data, session)
			session.commit()
			return jsonify({"ok": True, "id": emp.id, "employee_number": emp.employee_number}), 201
		except (PersonnelServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:employee_id>", methods=["PUT"])
	@has_access
	def update(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		session = _get_session()
		e = session.get(Employee, employee_id)
		if e is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = [
			"employment_type", "org_unit_id", "manager_id",
			"cost_center_code", "bank_bic", "probation_end_date",
		]
		for field in updatable:
			if field in data:
				setattr(e, field, data[field])
		e.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:employee_id>/terminate", methods=["POST"])
	@has_access
	def terminate(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService, PersonnelServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			emp = PersonnelService().terminate_employee(employee_id, data, session)
			session.commit()
			return jsonify({
				"ok": True,
				"employment_status": emp.employment_status,
				"termination_date": emp.termination_date.isoformat() if emp.termination_date else None,
			})
		except (PersonnelServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:employee_id>/transfer", methods=["POST"])
	@has_access
	def transfer(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService, PersonnelServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			PersonnelService().transfer_employee(employee_id, data, session)
			session.commit()
			return jsonify({"ok": True})
		except PersonnelServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# EmployeeCompensationView
# ---------------------------------------------------------------------------

class EmployeeCompensationView(BaseView):
	"""Compensation history — read + record change (immutable ledger).

	GET  /hcm/personnel/compensation/<employee_id>         — compensation history
	GET  /hcm/personnel/compensation/<employee_id>/current — active rate
	POST /hcm/personnel/compensation/                      — record new comp row
	"""

	route_base = "/hcm/personnel/compensation"
	default_view = "history"

	@expose("/<string:employee_id>")
	@has_access
	def history(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeCompensation
		session = _get_session()
		rows = session.execute(
			sa.select(EmployeeCompensation)
			.where(EmployeeCompensation.employee_id == employee_id)
			.order_by(sa.desc(EmployeeCompensation.effective_date))
		).scalars().all()
		return jsonify({"compensation_history": [
			{
				"id": c.id,
				"effective_date": c.effective_date.isoformat() if c.effective_date else None,
				"pay_type": c.pay_type, "amount_cents": c.amount_cents,
				"currency_code": c.currency_code, "frequency": c.frequency,
				"grade_code": c.grade_code, "reason": c.reason,
				"approved_by": c.approved_by,
			}
			for c in rows
		]})

	@expose("/<string:employee_id>/current")
	@has_access
	def current(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService
		session = _get_session()
		comp = PersonnelService().current_compensation(employee_id, session)
		if comp is None:
			return jsonify({"current_compensation": None})
		return jsonify({"current_compensation": {
			"id": comp.id,
			"effective_date": comp.effective_date.isoformat() if comp.effective_date else None,
			"pay_type": comp.pay_type, "amount_cents": comp.amount_cents,
			"currency_code": comp.currency_code, "frequency": comp.frequency,
			"grade_code": comp.grade_code, "reason": comp.reason,
		}})

	@expose("/", methods=["POST"])
	@has_access
	def record(self):
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService, PersonnelServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			comp = PersonnelService().record_compensation(data, session)
			session.commit()
			return jsonify({
				"ok": True, "id": comp.id,
				"amount_cents": comp.amount_cents,
				"effective_date": comp.effective_date.isoformat() if comp.effective_date else None,
			}), 201
		except (PersonnelServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# EmployeeDocumentView
# ---------------------------------------------------------------------------

class EmployeeDocumentView(BaseView):
	"""Employee document management.

	GET  /hcm/personnel/documents/<employee_id>        — list documents for employee
	POST /hcm/personnel/documents/                     — attach document
	POST /hcm/personnel/documents/<doc_id>/verify      — mark verified
	"""

	route_base = "/hcm/personnel/documents"
	default_view = "list_for_employee"

	@expose("/<string:employee_id>")
	@has_access
	def list_for_employee(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeDocument
		session = _get_session()
		docs = session.execute(
			sa.select(EmployeeDocument)
			.where(EmployeeDocument.employee_id == employee_id)
			.order_by(sa.desc(EmployeeDocument.issued_date))
		).scalars().all()
		return jsonify({"documents": [
			{
				"id": d.id, "document_type": d.document_type,
				"filename": d.filename,
				"issued_date": d.issued_date.isoformat() if d.issued_date else None,
				"expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
				"is_verified": d.is_verified,
			}
			for d in docs
		]})

	@expose("/", methods=["POST"])
	@has_access
	def attach(self):
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService, PersonnelServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			doc = PersonnelService().attach_document(data, session)
			session.commit()
			return jsonify({"ok": True, "id": doc.id}), 201
		except (PersonnelServiceError, KeyError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:doc_id>/verify", methods=["POST"])
	@has_access
	def verify(self, doc_id: str):
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService, PersonnelServiceError
		session = _get_session()
		try:
			PersonnelService().verify_document(doc_id, session)
			session.commit()
			return jsonify({"ok": True, "is_verified": True})
		except PersonnelServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# PersonnelReportView
# ---------------------------------------------------------------------------

class PersonnelReportView(BaseView):
	"""Personnel canned reports.

	GET /hcm/personnel/reports/roster            — employee roster
	GET /hcm/personnel/reports/compensation      — compensation summary by grade
	GET /hcm/personnel/reports/expiring-docs     — documents expiring within N days
	"""

	route_base = "/hcm/personnel/reports"
	default_view = "roster"

	@expose("/roster")
	@has_access
	def roster(self):
		"""Active employee roster with current compensation."""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, EmployeeCompensation
		session = _get_session()
		entity_id = request.args.get("entity_id")
		today = datetime.now(timezone.utc).date()

		q = (
			sa.select(Employee)
			.where(Employee.employment_status == "ACTIVE")
			.order_by(Employee.employee_number)
		)
		if entity_id:
			q = q.where(Employee.entity_id == entity_id)

		employees = session.execute(q.limit(1000)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"roster": [
				{
					"id": e.id, "employee_number": e.employee_number,
					"entity_id": e.entity_id, "org_unit_id": e.org_unit_id,
					"employment_type": e.employment_type,
					"start_date": e.start_date.isoformat() if e.start_date else None,
				}
				for e in employees
			], "total": len(employees)})

		trs = "".join(
			f"<tr><td>{_he(e.employee_number)}</td>"
			f"<td>{_he(e.employment_type)}</td>"
			f"<td>{_he(e.start_date)}</td></tr>"
			for e in employees
		)
		body = (
			f'<h3>Employee Roster ({len(employees)} active)</h3>'
			f'<table class="table table-bordered table-condensed table-hover">'
			f'<thead><tr><th>Employee #</th><th>Type</th><th>Start Date</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Employee Roster", body), 200)

	@expose("/compensation")
	@has_access
	def compensation_summary(self):
		"""Compensation summary — employee count and average pay per grade."""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeCompensation
		session = _get_session()
		q = (
			sa.select(
				EmployeeCompensation.grade_code,
				EmployeeCompensation.currency_code,
				EmployeeCompensation.frequency,
				sa.func.count().label("count"),
				sa.func.avg(EmployeeCompensation.amount_cents).label("avg_cents"),
				sa.func.min(EmployeeCompensation.amount_cents).label("min_cents"),
				sa.func.max(EmployeeCompensation.amount_cents).label("max_cents"),
			)
			.where(EmployeeCompensation.grade_code.isnot(None))
			.group_by(
				EmployeeCompensation.grade_code,
				EmployeeCompensation.currency_code,
				EmployeeCompensation.frequency,
			)
			.order_by(EmployeeCompensation.grade_code)
		)
		if request.args.get("tenant_id"):
			q = q.where(EmployeeCompensation.tenant_id == request.args["tenant_id"])

		rows = session.execute(q).all()
		return jsonify({"compensation_summary": [
			{
				"grade_code": r.grade_code,
				"currency_code": r.currency_code,
				"frequency": r.frequency,
				"count": r.count,
				"avg_cents": int(r.avg_cents or 0),
				"min_cents": r.min_cents or 0,
				"max_cents": r.max_cents or 0,
			}
			for r in rows
		]})

	@expose("/expiring-docs")
	@has_access
	def expiring_docs(self):
		"""Documents expiring within N days (default 30)."""
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		days = int(request.args.get("days", 30))
		docs = PersonnelService().expiring_documents(tenant_id, session, within_days=days)

		if request.args.get("format") == "json":
			return jsonify({"expiring_documents": [
				{
					"id": d.id, "employee_id": d.employee_id,
					"document_type": d.document_type, "filename": d.filename,
					"expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
					"is_verified": d.is_verified,
				}
				for d in docs
			]})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(d.employee_id)}</td>"
			f"<td>{_he(d.document_type)}</td>"
			f"<td>{_he(d.filename)}</td>"
			f"<td class='text-danger'>{_he(d.expiry_date)}</td>"
			f"<td>{'<span class=\"label label-success\">Yes</span>' if d.is_verified else '<span class=\"label label-warning\">No</span>'}</td>"
			f"</tr>"
			for d in docs
		)
		body = (
			f'<h3>Documents Expiring Within {days} Days ({len(docs)} found)</h3>'
			f'<table class="table table-bordered table-condensed">'
			f'<thead><tr><th>Employee</th><th>Type</th><th>File</th><th>Expiry</th><th>Verified</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
		)
		return make_response(_page_html("Expiring Documents", body), 200)


__all__ = [
	"EmployeeView",
	"EmployeeCompensationView",
	"EmployeeDocumentView",
	"PersonnelReportView",
]
