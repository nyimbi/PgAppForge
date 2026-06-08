"""
pgappforge/plugins/erp/hcm/org/views.py

Flask views for the HCM Org Management plugin.

Registered views:
  LegalEntityView       — CRUD + activate/deactivate
  OrgUnitView           — CRUD + restructure action + org tree
  PositionView          — CRUD + fill/vacate actions
  JobCatalogView        — CRUD
  CompensationGradeView — read + publish (immutable ledger)
  OrgReportView         — 3 canned reports:
                          * Headcount by Org Unit
                          * Open Positions
                          * Compensation Grade Distribution
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
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
# LegalEntityView
# ---------------------------------------------------------------------------

class LegalEntityView(BaseERPView):
	"""Legal entity CRUD.

	GET  /hcm/org/entities/                — list
	GET  /hcm/org/entities/<id>            — detail
	POST /hcm/org/entities/                — create
	PUT  /hcm/org/entities/<id>            — update
	POST /hcm/org/entities/<id>/deactivate — deactivate
	"""

	route_base = "/hcm/org/entities"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.org.models import LegalEntity
		session = _get_session()
		q = sa.select(LegalEntity).order_by(LegalEntity.entity_code)
		if request.args.get("tenant_id"):
			q = q.where(LegalEntity.tenant_id == request.args["tenant_id"])
		if request.args.get("active") == "1":
			q = q.where(LegalEntity.is_active.is_(True))
		entities = session.execute(q.limit(200)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"legal_entities": [
				{
					"id": e.id, "entity_code": e.entity_code,
					"entity_name": e.entity_name, "country_code": e.country_code,
					"payroll_currency": e.payroll_currency, "is_active": e.is_active,
				}
				for e in entities
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(e.entity_code)}</td>"
			f"<td>{_he(e.entity_name)}</td>"
			f"<td>{_he(e.country_code)}</td>"
			f"<td>{_he(e.payroll_currency)}</td>"
			f"<td>{'<span class=\"label label-success\">Active</span>' if e.is_active else '<span class=\"label label-danger\">Inactive</span>'}</td>"
			f"<td><a href='/hcm/org/entities/{_he(e.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for e in entities
		)
		body = (
			'<h3>Legal Entities</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Code</th><th>Name</th><th>Country</th><th>Currency</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Legal Entities", body), 200)

	@expose("/<string:entity_id>")
	@has_access
	def detail(self, entity_id: str):
		from pgappforge.plugins.erp.hcm.org.models import LegalEntity
		session = _get_session()
		e = session.get(LegalEntity, entity_id)
		if e is None:
			abort(404)
		return jsonify({
			"id": e.id, "tenant_id": e.tenant_id,
			"entity_code": e.entity_code, "entity_name": e.entity_name,
			"tax_id": e.tax_id, "payroll_currency": e.payroll_currency,
			"country_code": e.country_code,
			"fiscal_year_start_month": e.fiscal_year_start_month,
			"address": e.address, "is_active": e.is_active,
			"created_at": e.created_at.isoformat() if e.created_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		svc = OrgService()
		try:
			entity = svc.create_legal_entity(data, session)
			session.commit()
			return jsonify({"ok": True, "id": entity.id}), 201
		except OrgServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:entity_id>", methods=["PUT"])
	@has_access
	def update(self, entity_id: str):
		from pgappforge.plugins.erp.hcm.org.models import LegalEntity
		session = _get_session()
		e = session.get(LegalEntity, entity_id)
		if e is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for field in ("entity_name", "tax_id", "payroll_currency", "fiscal_year_start_month", "address"):
			if field in data:
				setattr(e, field, data[field])
		e.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:entity_id>/deactivate", methods=["POST"])
	@has_access
	def deactivate(self, entity_id: str):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		session = _get_session()
		try:
			OrgService().deactivate_legal_entity(entity_id, session)
			session.commit()
			return jsonify({"ok": True, "is_active": False})
		except OrgServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# OrgUnitView
# ---------------------------------------------------------------------------

class OrgUnitView(BaseERPView):
	"""Org unit CRUD + restructure + org tree.

	GET  /hcm/org/units/                      — list
	GET  /hcm/org/units/<id>                  — detail
	POST /hcm/org/units/                      — create
	PUT  /hcm/org/units/<id>                  — update
	POST /hcm/org/units/<id>/restructure      — change parent/manager
	GET  /hcm/org/units/tree/<entity_id>      — flat org tree for entity
	"""

	route_base = "/hcm/org/units"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.org.models import OrgUnit
		session = _get_session()
		q = sa.select(OrgUnit).order_by(OrgUnit.org_code)
		if request.args.get("entity_id"):
			q = q.where(OrgUnit.entity_id == request.args["entity_id"])
		if request.args.get("org_type"):
			q = q.where(OrgUnit.org_type == request.args["org_type"].upper())
		units = session.execute(q.limit(500)).scalars().all()
		return jsonify({"org_units": [
			{
				"id": u.id, "org_code": u.org_code, "org_name": u.org_name,
				"org_type": u.org_type, "parent_id": u.parent_id,
				"entity_id": u.entity_id, "is_active": u.is_active,
			}
			for u in units
		]})

	@expose("/<string:unit_id>")
	@has_access
	def detail(self, unit_id: str):
		from pgappforge.plugins.erp.hcm.org.models import OrgUnit
		session = _get_session()
		u = session.get(OrgUnit, unit_id)
		if u is None:
			abort(404)
		return jsonify({
			"id": u.id, "tenant_id": u.tenant_id, "entity_id": u.entity_id,
			"org_code": u.org_code, "org_name": u.org_name, "org_type": u.org_type,
			"parent_id": u.parent_id, "cost_center_code": u.cost_center_code,
			"manager_id": u.manager_id, "headcount_budget": u.headcount_budget,
			"is_active": u.is_active,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			unit = OrgService().create_org_unit(data, session)
			session.commit()
			return jsonify({"ok": True, "id": unit.id}), 201
		except OrgServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:unit_id>/restructure", methods=["POST"])
	@has_access
	def restructure(self, unit_id: str):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			unit = OrgService().restructure_org_unit(
				unit_id,
				data.get("new_parent_id"),
				session,
				new_manager_id=data.get("new_manager_id"),
			)
			session.commit()
			return jsonify({"ok": True, "parent_id": unit.parent_id, "manager_id": unit.manager_id})
		except OrgServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/tree/<string:entity_id>")
	@has_access
	def tree(self, entity_id: str):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		session = _get_session()
		return jsonify({"org_tree": OrgService().org_tree(entity_id, session)})


# ---------------------------------------------------------------------------
# PositionView
# ---------------------------------------------------------------------------

class PositionView(BaseERPView):
	"""Position CRUD + fill/vacate.

	GET  /hcm/org/positions/              — list (filterable by is_filled, org_unit_id)
	GET  /hcm/org/positions/<id>          — detail
	POST /hcm/org/positions/              — create
	POST /hcm/org/positions/<id>/fill     — fill position (employee_id in body)
	POST /hcm/org/positions/<id>/vacate   — vacate position
	"""

	route_base = "/hcm/org/positions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.org.models import Position
		session = _get_session()
		q = sa.select(Position).order_by(Position.position_code)
		if request.args.get("org_unit_id"):
			q = q.where(Position.org_unit_id == request.args["org_unit_id"])
		if request.args.get("entity_id"):
			q = q.where(Position.entity_id == request.args["entity_id"])
		if request.args.get("is_filled") is not None:
			filled = request.args["is_filled"].lower() in ("1", "true")
			q = q.where(Position.is_filled.is_(filled))
		if request.args.get("active_only", "1") == "1":
			q = q.where(Position.is_active.is_(True))
		positions = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"positions": [
				{
					"id": p.id, "position_code": p.position_code,
					"position_title": p.position_title,
					"org_unit_id": p.org_unit_id,
					"employment_type": p.employment_type,
					"is_filled": p.is_filled,
					"graded_salary_min_cents": p.graded_salary_min_cents,
					"graded_salary_max_cents": p.graded_salary_max_cents,
				}
				for p in positions
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(p.position_code)}</td>"
			f"<td>{_he(p.position_title)}</td>"
			f"<td>{_he(p.employment_type)}</td>"
			f"<td>{'<span class=\"label label-success\">Filled</span>' if p.is_filled else '<span class=\"label label-warning\">Open</span>'}</td>"
			f"</tr>"
			for p in positions
		)
		body = (
			'<h3>Positions</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Code</th><th>Title</th><th>Type</th><th>Status</th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Positions", body), 200)

	@expose("/<string:position_id>")
	@has_access
	def detail(self, position_id: str):
		from pgappforge.plugins.erp.hcm.org.models import Position
		session = _get_session()
		p = session.get(Position, position_id)
		if p is None:
			abort(404)
		return jsonify({
			"id": p.id, "tenant_id": p.tenant_id,
			"position_code": p.position_code, "entity_id": p.entity_id,
			"org_unit_id": p.org_unit_id, "job_code": p.job_code,
			"position_title": p.position_title, "employment_type": p.employment_type,
			"is_filled": p.is_filled,
			"graded_salary_min_cents": p.graded_salary_min_cents,
			"graded_salary_max_cents": p.graded_salary_max_cents,
			"is_active": p.is_active,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			pos = OrgService().create_position(data, session)
			session.commit()
			return jsonify({"ok": True, "id": pos.id}), 201
		except OrgServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:position_id>/fill", methods=["POST"])
	@has_access
	def fill(self, position_id: str):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		employee_id = data.get("employee_id", "")
		try:
			OrgService().fill_position(position_id, employee_id, session)
			session.commit()
			return jsonify({"ok": True, "is_filled": True})
		except OrgServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:position_id>/vacate", methods=["POST"])
	@has_access
	def vacate(self, position_id: str):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			OrgService().vacate_position(position_id, data.get("employee_id", ""), session)
			session.commit()
			return jsonify({"ok": True, "is_filled": False})
		except OrgServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# JobCatalogView
# ---------------------------------------------------------------------------

class JobCatalogView(BaseERPView):
	"""Job catalog CRUD.

	GET  /hcm/org/jobs/   — list
	GET  /hcm/org/jobs/<id> — detail
	POST /hcm/org/jobs/   — create
	PUT  /hcm/org/jobs/<id> — update
	"""

	route_base = "/hcm/org/jobs"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.org.models import JobCatalog
		session = _get_session()
		q = sa.select(JobCatalog).order_by(JobCatalog.job_code)
		if request.args.get("job_family"):
			q = q.where(JobCatalog.job_family == request.args["job_family"])
		if request.args.get("active_only", "1") == "1":
			q = q.where(JobCatalog.is_active.is_(True))
		jobs = session.execute(q.limit(500)).scalars().all()
		return jsonify({"jobs": [
			{
				"id": j.id, "job_code": j.job_code, "job_title": j.job_title,
				"job_family": j.job_family, "job_function": j.job_function,
				"grade_level": j.grade_level, "flsa_status": j.flsa_status,
				"is_active": j.is_active,
			}
			for j in jobs
		]})

	@expose("/<string:job_id>")
	@has_access
	def detail(self, job_id: str):
		from pgappforge.plugins.erp.hcm.org.models import JobCatalog
		session = _get_session()
		j = session.get(JobCatalog, job_id)
		if j is None:
			abort(404)
		return jsonify({
			"id": j.id, "tenant_id": j.tenant_id, "job_code": j.job_code,
			"job_title": j.job_title, "job_family": j.job_family,
			"job_function": j.job_function, "grade_level": j.grade_level,
			"flsa_status": j.flsa_status, "is_active": j.is_active,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.org.models import JobCatalog
		from pgappforge.plugins.erp.hcm.org.events import JobCatalogCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "job_code", "job_title")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		j = JobCatalog(
			tenant_id=data["tenant_id"],
			job_code=data["job_code"].upper(),
			job_title=data["job_title"],
			job_family=data.get("job_family"),
			job_function=data.get("job_function"),
			grade_level=data.get("grade_level"),
			flsa_status=data.get("flsa_status"),
			is_active=True,
		)
		session.add(j)
		session.flush()
		emit_event(
			JobCatalogCreatedEvent(
				aggregate_id=j.id,
				aggregate_type="JobCatalog",
				tenant_id=j.tenant_id,
				job_catalog_id=j.id,
				job_code=j.job_code,
				job_title=j.job_title,
				job_family=j.job_family or "",
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": j.id}), 201

	@expose("/<string:job_id>", methods=["PUT"])
	@has_access
	def update(self, job_id: str):
		from pgappforge.plugins.erp.hcm.org.models import JobCatalog
		session = _get_session()
		j = session.get(JobCatalog, job_id)
		if j is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for field in ("job_title", "job_family", "job_function", "grade_level", "flsa_status", "is_active"):
			if field in data:
				setattr(j, field, data[field])
		j.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# CompensationGradeView
# ---------------------------------------------------------------------------

class CompensationGradeView(BaseERPView):
	"""Compensation grade read + publish (immutable ledger).

	GET  /hcm/org/grades/            — list all bands
	GET  /hcm/org/grades/active      — active grade per code as of today
	POST /hcm/org/grades/            — publish new band (INSERT only)
	"""

	route_base = "/hcm/org/grades"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.org.models import CompensationGrade
		session = _get_session()
		q = sa.select(CompensationGrade).order_by(
			CompensationGrade.grade_code, sa.desc(CompensationGrade.effective_from)
		)
		if request.args.get("tenant_id"):
			q = q.where(CompensationGrade.tenant_id == request.args["tenant_id"])
		grades = session.execute(q.limit(500)).scalars().all()
		return jsonify({"grades": [
			{
				"id": g.id, "grade_code": g.grade_code, "grade_label": g.grade_label,
				"min_cents": g.min_cents, "mid_cents": g.mid_cents, "max_cents": g.max_cents,
				"currency_code": g.currency_code,
				"effective_from": g.effective_from.isoformat() if g.effective_from else None,
			}
			for g in grades
		]})

	@expose("/", methods=["POST"])
	@has_access
	def publish(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			grade = OrgService().publish_compensation_grade(data, session)
			session.commit()
			return jsonify({
				"ok": True, "id": grade.id,
				"grade_code": grade.grade_code,
				"effective_from": grade.effective_from.isoformat(),
			}), 201
		except (OrgServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# OrgReportView
# ---------------------------------------------------------------------------

class OrgReportView(BaseERPView):
	"""Org Management canned reports.

	GET /hcm/org/reports/headcount         — headcount by org unit
	GET /hcm/org/reports/open-positions    — unfilled positions by entity
	GET /hcm/org/reports/grade-distribution — comp grade span analysis
	"""

	route_base = "/hcm/org/reports"
	default_view = "headcount"

	@expose("/dashboard")
	@has_access
	def dashboard(self):
		"""Org dashboard — KPIs."""
		from pgappforge.plugins.erp.hcm.org.models import LegalEntity, OrgUnit
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q_entities = sa.select(sa.func.count(LegalEntity.id)).where(LegalEntity.is_active.is_(True))
		q_units = sa.select(sa.func.count(OrgUnit.id)).where(OrgUnit.is_active.is_(True))
		q_emp = sa.select(sa.func.count(Employee.id)).where(Employee.employment_status == "ACTIVE")
		if tenant_id:
			q_entities = q_entities.where(LegalEntity.tenant_id == tenant_id)
			q_units = q_units.where(OrgUnit.tenant_id == tenant_id)
			q_emp = q_emp.where(Employee.tenant_id == tenant_id)

		total_entities = session.execute(q_entities).scalar() or 0
		total_departments = session.execute(q_units).scalar() or 0
		total_employees = session.execute(q_emp).scalar() or 0

		kpi_html = self.kpi_cards([
			{"label": "Legal Entities", "value": total_entities, "format": "integer", "color": "#1a56db", "icon": "fa-building"},
			{"label": "Total Employees", "value": total_employees, "format": "integer", "color": "#057a55", "icon": "fa-users"},
			{"label": "Departments", "value": total_departments, "format": "integer", "color": "#9061f9", "icon": "fa-sitemap"},
		])

		body = f'<h3>Org Dashboard</h3>{kpi_html}'
		return make_response(_page_html("Org Dashboard", body), 200)

	@expose("/headcount")
	@has_access
	def headcount(self):
		"""Headcount by org unit — active employees per unit."""
		from pgappforge.plugins.erp.hcm.org.models import OrgUnit
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		session = _get_session()
		entity_id = request.args.get("entity_id")

		q = (
			sa.select(
				OrgUnit.org_code,
				OrgUnit.org_name,
				OrgUnit.org_type,
				sa.func.count(Employee.id).label("headcount"),
			)
			.outerjoin(Employee, (Employee.org_unit_id == OrgUnit.id) & (Employee.employment_status == "ACTIVE"))
			.where(OrgUnit.is_active.is_(True))
			.group_by(OrgUnit.org_code, OrgUnit.org_name, OrgUnit.org_type)
			.order_by(OrgUnit.org_code)
		)
		if entity_id:
			q = q.where(OrgUnit.entity_id == entity_id)

		rows = session.execute(q).all()
		data = [
			{
				"org_code": r.org_code, "org_name": r.org_name,
				"org_type": r.org_type, "headcount": r.headcount,
			}
			for r in rows
		]

		if request.args.get("format") == "json":
			return jsonify({"headcount": data, "total": sum(r["headcount"] for r in data)})

		trs = "".join(
			f"<tr><td>{_he(r['org_code'])}</td><td>{_he(r['org_name'])}</td>"
			f"<td>{_he(r['org_type'])}</td><td class='text-right'>{r['headcount']}</td></tr>"
			for r in data
		)
		total = sum(r["headcount"] for r in data)
		body = (
			f'<h3>Headcount by Org Unit</h3>'
			f'<table class="table table-bordered table-condensed">'
			f'<thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Headcount</th></tr></thead>'
			f'<tbody>{trs}'
			f'<tr class="info"><td colspan="3"><strong>Total</strong></td><td class="text-right"><strong>{total}</strong></td></tr>'
			f'</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Headcount Report", body), 200)

	@expose("/open-positions")
	@has_access
	def open_positions(self):
		"""List unfilled active positions."""
		from pgappforge.plugins.erp.hcm.org.models import Position, OrgUnit
		session = _get_session()
		q = (
			sa.select(Position, OrgUnit.org_name)
			.join(OrgUnit, Position.org_unit_id == OrgUnit.id)
			.where(Position.is_filled.is_(False))
			.where(Position.is_active.is_(True))
			.order_by(Position.position_code)
		)
		if request.args.get("entity_id"):
			q = q.where(Position.entity_id == request.args["entity_id"])
		rows = session.execute(q).all()

		if request.args.get("format") == "json":
			return jsonify({"open_positions": [
				{
					"id": p.id, "position_code": p.position_code,
					"position_title": p.position_title,
					"org_unit": org_name,
					"employment_type": p.employment_type,
					"graded_salary_min_cents": p.graded_salary_min_cents,
					"graded_salary_max_cents": p.graded_salary_max_cents,
				}
				for p, org_name in rows
			]})

		trs = "".join(
			f"<tr><td>{_he(p.position_code)}</td><td>{_he(p.position_title)}</td>"
			f"<td>{_he(org_name)}</td><td>{_he(p.employment_type)}</td></tr>"
			for p, org_name in rows
		)
		body = (
			f'<h3>Open Positions ({len(rows)})</h3>'
			f'<table class="table table-bordered table-condensed">'
			f'<thead><tr><th>Code</th><th>Title</th><th>Org Unit</th><th>Type</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
		)
		return make_response(_page_html("Open Positions", body), 200)

	@expose("/grade-distribution")
	@has_access
	def grade_distribution(self):
		"""Compensation grade span analysis — employees per grade vs. band midpoint."""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeCompensation
		from pgappforge.plugins.erp.hcm.org.models import CompensationGrade
		from datetime import date as date_type
		session = _get_session()
		today = datetime.now(timezone.utc).date()

		# Latest comp row per employee
		subq = (
			sa.select(
				EmployeeCompensation.grade_code,
				sa.func.count().label("employee_count"),
				sa.func.avg(EmployeeCompensation.amount_cents).label("avg_amount_cents"),
				sa.func.min(EmployeeCompensation.amount_cents).label("min_amount_cents"),
				sa.func.max(EmployeeCompensation.amount_cents).label("max_amount_cents"),
			)
			.where(EmployeeCompensation.grade_code.isnot(None))
			.group_by(EmployeeCompensation.grade_code)
		)
		if request.args.get("tenant_id"):
			subq = subq.where(EmployeeCompensation.tenant_id == request.args["tenant_id"])

		rows = session.execute(subq).all()
		return jsonify({"grade_distribution": [
			{
				"grade_code": r.grade_code,
				"employee_count": r.employee_count,
				"avg_amount_cents": int(r.avg_amount_cents or 0),
				"min_amount_cents": r.min_amount_cents,
				"max_amount_cents": r.max_amount_cents,
			}
			for r in rows
		]})


__all__ = [
	"LegalEntityView",
	"OrgUnitView",
	"PositionView",
	"JobCatalogView",
	"CompensationGradeView",
	"OrgReportView",
]
