"""
pgappforge/plugins/erp/grc/controls/views.py

Flask views for the GRC Controls plugin.

Endpoints:
  ControlFrameworkView  GET/POST /grc/controls/frameworks/
  ControlView           GET/POST /grc/controls/
                        POST     /grc/controls/<id>/status
  ControlTestView       POST     /grc/controls/<id>/tests
                        GET      /grc/controls/<id>/tests
  SoDView               GET/POST /grc/controls/sod/
                        GET      /grc/controls/sod/check
  ControlReportView     GET      /grc/controls/reports/{effectiveness,deficiencies,sod-matrix}
"""
from __future__ import annotations

import logging
from datetime import date

import sqlalchemy as sa
from flask import abort, jsonify, request

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
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.grc.controls.services import ControlsService
	return ControlsService()


# ---------------------------------------------------------------------------
# ControlFrameworkView
# ---------------------------------------------------------------------------

class ControlFrameworkView(BaseView):
	route_base = "/grc/controls/frameworks"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.grc.controls.models import ControlFramework
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(ControlFramework).order_by(ControlFramework.name)
		if tenant_id:
			q = q.where(ControlFramework.tenant_id == tenant_id)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"name": r.name,
				"version": r.version,
				"description": r.description,
				"is_active": r.is_active,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "name", "version")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		result = _svc().create_framework(
			session=session,
			tenant_id=data["tenant_id"],
			name=data["name"],
			version=data["version"],
			description=data.get("description"),
		)
		session.commit()
		return jsonify(result), 201


# ---------------------------------------------------------------------------
# ControlView
# ---------------------------------------------------------------------------

class ControlView(BaseView):
	route_base = "/grc/controls"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.grc.controls.models import Control
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		framework_id = request.args.get("framework_id")
		q = sa.select(Control).order_by(Control.control_code)
		if tenant_id:
			q = q.where(Control.tenant_id == tenant_id)
		if framework_id:
			q = q.where(Control.framework_id == framework_id)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"control_code": r.control_code,
				"control_name": r.control_name,
				"control_type": r.control_type,
				"frequency": r.frequency,
				"automated": r.automated,
				"status": r.status,
				"framework_id": r.framework_id,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "framework_id", "control_code", "control_name",
			"control_objective", "control_type", "frequency",
		)
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().create_control(
				session=session,
				tenant_id=data["tenant_id"],
				framework_id=data["framework_id"],
				control_code=data["control_code"],
				control_name=data["control_name"],
				control_objective=data["control_objective"],
				control_type=data["control_type"],
				frequency=data["frequency"],
				automated=data.get("automated", False),
				owner_id=data.get("owner_id"),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:control_id>/status", methods=["POST"])
	@has_access
	def set_status(self, control_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("status"):
			return jsonify({"error": "status required"}), 400
		try:
			result = _svc().set_control_status(
				session, control_id=control_id, new_status=data["status"]
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ControlTestView
# ---------------------------------------------------------------------------

class ControlTestView(BaseView):
	route_base = "/grc/controls"
	default_view = "list_tests"

	@expose("/<string:control_id>/tests")
	@has_access
	def list_tests(self, control_id: str):
		from pgappforge.plugins.erp.grc.controls.models import ControlTest
		session = _get_session()
		rows = session.execute(
			sa.select(ControlTest)
			.where(ControlTest.control_id == control_id)
			.order_by(ControlTest.test_date.desc())
			.limit(100)
		).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"test_date": r.test_date.isoformat() if r.test_date else None,
				"tester_id": str(r.tester_id) if r.tester_id else None,
				"test_result": r.test_result,
				"deficiencies_noted": r.deficiencies_noted,
				"remediation_due": r.remediation_due.isoformat() if r.remediation_due else None,
				"evidence_urls": r.evidence_urls,
			}
			for r in rows
		])

	@expose("/<string:control_id>/tests", methods=["POST"])
	@has_access
	def record_test(self, control_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "test_date", "test_result")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().record_test(
				session=session,
				tenant_id=data["tenant_id"],
				control_id=control_id,
				test_date=date.fromisoformat(data["test_date"]),
				tester_id=data.get("tester_id"),
				test_result=data["test_result"],
				evidence_urls=data.get("evidence_urls"),
				deficiencies_noted=data.get("deficiencies_noted"),
				remediation_due=(
					date.fromisoformat(data["remediation_due"])
					if data.get("remediation_due") else None
				),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# SoDView
# ---------------------------------------------------------------------------

class SoDView(BaseView):
	route_base = "/grc/controls/sod"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.grc.controls.models import SegregationOfDuties
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(SegregationOfDuties).where(
			SegregationOfDuties.is_active.is_(True)
		).order_by(SegregationOfDuties.risk_level, SegregationOfDuties.role_a)
		if tenant_id:
			q = q.where(SegregationOfDuties.tenant_id == tenant_id)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"role_a": r.role_a,
				"role_b": r.role_b,
				"conflict_type": r.conflict_type,
				"risk_level": r.risk_level,
				"is_active": r.is_active,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def register(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "role_a", "role_b", "conflict_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().register_sod_rule(
				session=session,
				tenant_id=data["tenant_id"],
				role_a=data["role_a"],
				role_b=data["role_b"],
				conflict_type=data["conflict_type"],
				risk_level=data.get("risk_level", "HIGH"),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/check")
	@has_access
	def check(self):
		"""Check SoD conflict. Query params: tenant_id, role_a, role_b."""
		session = _get_session()
		args = request.args
		required = ("tenant_id", "role_a", "role_b")
		missing = [f for f in required if not args.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		result = _svc().check_sod_conflict(
			session,
			tenant_id=args["tenant_id"],
			role_a=args["role_a"],
			role_b=args["role_b"],
		)
		return jsonify(result)


# ---------------------------------------------------------------------------
# ControlReportView
# ---------------------------------------------------------------------------

class ControlReportView(BaseView):
	"""GRC Controls reports.

	GET /grc/controls/reports/effectiveness  — control effectiveness summary
	GET /grc/controls/reports/deficiencies   — open deficiencies needing remediation
	GET /grc/controls/reports/sod-matrix     — full SoD conflict matrix
	"""

	route_base = "/grc/controls/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"reports": [
				{"name": "Control Effectiveness", "endpoint": "/grc/controls/reports/effectiveness"},
				{"name": "Open Deficiencies", "endpoint": "/grc/controls/reports/deficiencies"},
				{"name": "SoD Conflict Matrix", "endpoint": "/grc/controls/reports/sod-matrix"},
			]
		})

	@expose("/effectiveness")
	@has_access
	def effectiveness(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		framework_id = request.args.get("framework_id")
		since_str = request.args.get("since")
		since = date.fromisoformat(since_str) if since_str else None
		rows = _svc().get_control_effectiveness_summary(
			session, tenant_id=tenant_id,
			framework_id=framework_id, since_date=since,
		)
		return jsonify(rows)

	@expose("/deficiencies")
	@has_access
	def deficiencies(self):
		from pgappforge.plugins.erp.grc.controls.models import ControlTest, Control
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = (
			sa.select(ControlTest, Control.control_code, Control.control_name)
			.join(Control, Control.id == ControlTest.control_id)
			.where(
				ControlTest.deficiencies_noted.isnot(None),
				ControlTest.deficiencies_noted != "",
			)
			.order_by(ControlTest.remediation_due)
		)
		if tenant_id:
			q = q.where(ControlTest.tenant_id == tenant_id)
		rows = session.execute(q).all()
		return jsonify([
			{
				"test_id": r.ControlTest.id,
				"control_code": r.control_code,
				"control_name": r.control_name,
				"test_date": r.ControlTest.test_date.isoformat() if r.ControlTest.test_date else None,
				"test_result": r.ControlTest.test_result,
				"deficiencies_noted": r.ControlTest.deficiencies_noted,
				"remediation_due": (
					r.ControlTest.remediation_due.isoformat()
					if r.ControlTest.remediation_due else None
				),
			}
			for r in rows
		])

	@expose("/sod-matrix")
	@has_access
	def sod_matrix(self):
		from pgappforge.plugins.erp.grc.controls.models import SegregationOfDuties
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(SegregationOfDuties).order_by(
			SegregationOfDuties.risk_level, SegregationOfDuties.role_a
		)
		if tenant_id:
			q = q.where(SegregationOfDuties.tenant_id == tenant_id)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"role_a": r.role_a,
				"role_b": r.role_b,
				"conflict_type": r.conflict_type,
				"risk_level": r.risk_level,
				"is_active": r.is_active,
			}
			for r in rows
		])


__all__ = [
	"ControlFrameworkView",
	"ControlView",
	"ControlTestView",
	"SoDView",
	"ControlReportView",
]
