"""
pgappforge/plugins/erp/operations/quality/views.py

Flask views for the Quality Management plugin.

Registered views:
  InspectionPlanView   — CRUD
  QualityInspectionView — CRUD + start/record-results actions
  NCRView              — CRUD + advance-status action
  QCReportView         — 3 reports:
                         * Inspection Summary (pass/fail rates by product)
                         * NCR Aging (open NCRs by severity / overdue)
                         * Supplier Quality Trend
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

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
# InspectionPlanView
# ---------------------------------------------------------------------------

class InspectionPlanView(BaseView):
	"""Inspection Plan CRUD.

	GET  /qc/plans/         — list
	GET  /qc/plans/<id>     — detail
	POST /qc/plans/         — create
	PUT  /qc/plans/<id>     — update
	"""

	route_base = "/qc/plans"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.quality.models import InspectionPlan
		session = _get_session()
		q = sa.select(InspectionPlan).order_by(InspectionPlan.inspection_type)
		for field, col in (
			("tenant_id", InspectionPlan.tenant_id),
			("product_id", InspectionPlan.product_id),
			("inspection_type", InspectionPlan.inspection_type),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		if request.args.get("active") == "1":
			q = q.where(InspectionPlan.is_active == True)
		plans = session.execute(q.limit(500)).scalars().all()
		return jsonify({"inspection_plans": [
			{
				"id": p.id, "product_id": p.product_id,
				"inspection_type": p.inspection_type, "name": p.name,
				"sampling_pct": str(p.sampling_pct),
				"is_active": p.is_active, "version": p.version,
			}
			for p in plans
		]})

	@expose("/<string:plan_id>")
	@has_access
	def detail(self, plan_id: str):
		from pgappforge.plugins.erp.operations.quality.models import InspectionPlan
		session = _get_session()
		plan = session.get(InspectionPlan, plan_id)
		if plan is None:
			abort(404)
		return jsonify({
			"id": plan.id, "tenant_id": plan.tenant_id,
			"product_id": plan.product_id,
			"inspection_type": plan.inspection_type, "name": plan.name,
			"description": plan.description,
			"sampling_pct": str(plan.sampling_pct),
			"acceptance_criteria": plan.acceptance_criteria,
			"is_active": plan.is_active, "version": plan.version,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.quality.models import InspectionPlan
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "product_id", "inspection_type", "name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		plan = InspectionPlan(
			tenant_id=data["tenant_id"],
			product_id=data["product_id"],
			inspection_type=data["inspection_type"],
			name=data["name"],
			description=data.get("description"),
			sampling_pct=data.get("sampling_pct", 100),
			acceptance_criteria=data.get("acceptance_criteria") or {},
			is_active=bool(data.get("is_active", True)),
			version=data.get("version", "1"),
		)
		session.add(plan)
		session.commit()
		return jsonify({"ok": True, "id": plan.id}), 201

	@expose("/<string:plan_id>", methods=["PUT"])
	@has_access
	def update(self, plan_id: str):
		from pgappforge.plugins.erp.operations.quality.models import InspectionPlan
		session = _get_session()
		plan = session.get(InspectionPlan, plan_id)
		if plan is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "description", "sampling_pct", "acceptance_criteria", "is_active", "version"):
			if f in data:
				setattr(plan, f, data[f])
		plan.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# QualityInspectionView
# ---------------------------------------------------------------------------

class QualityInspectionView(BaseView):
	"""Quality Inspection CRUD + result recording.

	GET  /qc/inspections/                      — list
	GET  /qc/inspections/<id>                  — detail
	POST /qc/inspections/                      — create (auto-computes sample qty from plan)
	POST /qc/inspections/<id>/start            — PENDING → IN_PROGRESS
	POST /qc/inspections/<id>/record-results   — record findings → PASSED/FAILED
	"""

	route_base = "/qc/inspections"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.quality.models import QualityInspection
		session = _get_session()
		q = sa.select(QualityInspection).order_by(sa.desc(QualityInspection.inspection_date))
		for field, col in (
			("tenant_id", QualityInspection.tenant_id),
			("status", QualityInspection.status),
			("reference_type", QualityInspection.reference_type),
			("reference_id", QualityInspection.reference_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		inspections = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"inspections": [
				{
					"id": i.id,
					"reference_type": i.reference_type, "reference_id": i.reference_id,
					"inspection_date": i.inspection_date.isoformat() if i.inspection_date else None,
					"inspected_quantity": str(i.inspected_quantity),
					"accepted_quantity": str(i.accepted_quantity),
					"rejected_quantity": str(i.rejected_quantity),
					"status": i.status, "overall_result": i.overall_result,
					"disposition": i.disposition,
				}
				for i in inspections
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(i.reference_type)}/{_he(i.reference_id[:8])}…</td>"
			f"<td>{_he(i.inspection_date)}</td>"
			f"<td class='text-right'>{_he(i.inspected_quantity)}</td>"
			f"<td class='text-right text-danger'>{_he(i.rejected_quantity)}</td>"
			f"<td><span class='label label-{'success' if i.status=='PASSED' else 'danger' if i.status=='FAILED' else 'default'}'>{_he(i.status)}</span></td>"
			f"<td><a href='/qc/inspections/{_he(i.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for i in inspections
		)
		body = (
			'<h3>Quality Inspections</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Reference</th><th>Date</th><th>Inspected</th>'
			'<th>Rejected</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Quality Inspections", body), 200)

	@expose("/<string:inspection_id>")
	@has_access
	def detail(self, inspection_id: str):
		from pgappforge.plugins.erp.operations.quality.models import QualityInspection
		session = _get_session()
		insp = session.get(QualityInspection, inspection_id)
		if insp is None:
			abort(404)
		return jsonify({
			"id": insp.id, "tenant_id": insp.tenant_id,
			"reference_type": insp.reference_type, "reference_id": insp.reference_id,
			"plan_id": insp.plan_id,
			"inspected_quantity": str(insp.inspected_quantity),
			"accepted_quantity": str(insp.accepted_quantity),
			"rejected_quantity": str(insp.rejected_quantity),
			"uom": insp.uom,
			"inspector_id": insp.inspector_id,
			"inspection_date": insp.inspection_date.isoformat() if insp.inspection_date else None,
			"status": insp.status,
			"findings": insp.findings,
			"overall_result": insp.overall_result,
			"disposition": insp.disposition,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from decimal import Decimal
		from datetime import date as date_type
		from pgappforge.plugins.erp.operations.quality.services import QCService, QCServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "reference_type", "reference_id",
		            "product_id", "lot_quantity", "inspection_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			insp = QCService().create_inspection(
				reference_type=data["reference_type"],
				reference_id=data["reference_id"],
				product_id=data["product_id"],
				tenant_id=data["tenant_id"],
				lot_quantity=Decimal(str(data["lot_quantity"])),
				inspection_date=date_type.fromisoformat(data["inspection_date"]),
				inspector_id=data.get("inspector_id"),
				session=session,
				inspection_type=data.get("inspection_type", "INCOMING"),
			)
			session.commit()
			return jsonify({
				"ok": True, "id": insp.id,
				"inspected_quantity": str(insp.inspected_quantity),
			}), 201
		except QCServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:inspection_id>/start", methods=["POST"])
	@has_access
	def start(self, inspection_id: str):
		from pgappforge.plugins.erp.operations.quality.models import QualityInspection
		from pgappforge.plugins.erp.operations.quality.events import InspectionStartedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		insp = session.get(QualityInspection, inspection_id)
		if insp is None:
			abort(404)
		if insp.status != "PENDING":
			return jsonify({"ok": False, "error": f"Cannot start inspection in status {insp.status!r}"}), 400
		data = request.get_json(silent=True) or {}
		insp.status = "IN_PROGRESS"
		insp.inspector_id = data.get("inspector_id") or insp.inspector_id
		insp.updated_at = datetime.now(timezone.utc)
		emit_event(
			InspectionStartedEvent(
				aggregate_id=inspection_id,
				aggregate_type="QualityInspection",
				tenant_id=insp.tenant_id,
				inspection_id=inspection_id,
				inspector_id=insp.inspector_id or "",
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "status": insp.status})

	@expose("/<string:inspection_id>/record-results", methods=["POST"])
	@has_access
	def record_results(self, inspection_id: str):
		from decimal import Decimal
		from pgappforge.plugins.erp.operations.quality.services import QCService, QCServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("accepted_quantity", "rejected_quantity", "disposition")
		missing = [f for f in required if f not in data]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			insp = QCService().record_results(
				inspection_id=inspection_id,
				accepted_quantity=Decimal(str(data["accepted_quantity"])),
				rejected_quantity=Decimal(str(data["rejected_quantity"])),
				findings=data.get("findings") or [],
				disposition=data["disposition"],
				session=session,
			)
			session.commit()
			return jsonify({
				"ok": True, "status": insp.status,
				"overall_result": insp.overall_result,
				"disposition": insp.disposition,
			})
		except QCServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# NCRView
# ---------------------------------------------------------------------------

class NCRView(BaseView):
	"""Non-Conformance Report CRUD + CAPA workflow.

	GET  /qc/ncrs/                   — list
	GET  /qc/ncrs/<id>               — detail
	POST /qc/ncrs/                   — open new NCR
	POST /qc/ncrs/<id>/advance       — advance status with CAPA data
	"""

	route_base = "/qc/ncrs"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.quality.models import NonConformanceReport
		session = _get_session()
		q = sa.select(NonConformanceReport).order_by(sa.desc(NonConformanceReport.created_at))
		for field, col in (
			("tenant_id", NonConformanceReport.tenant_id),
			("status", NonConformanceReport.status),
			("severity", NonConformanceReport.severity),
			("product_id", NonConformanceReport.product_id),
			("source_type", NonConformanceReport.source_type),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		ncrs = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"ncrs": [
				{
					"id": n.id, "ncr_number": n.ncr_number,
					"source_type": n.source_type, "product_id": n.product_id,
					"severity": n.severity, "status": n.status,
					"quantity_affected": str(n.quantity_affected),
					"due_date": n.due_date.isoformat() if n.due_date else None,
					"closed_at": n.closed_at.isoformat() if n.closed_at else None,
				}
				for n in ncrs
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(n.ncr_number)}</td>"
			f"<td>{_he(n.source_type)}</td>"
			f"<td>{_he(n.product_id)}</td>"
			f"<td><span class='label label-{'danger' if n.severity=='CRITICAL' else 'warning' if n.severity=='MAJOR' else 'default'}'>{_he(n.severity)}</span></td>"
			f"<td>{_he(str(n.quantity_affected))}</td>"
			f"<td><span class='label label-info'>{_he(n.status)}</span></td>"
			f"<td>{_he(n.due_date or '—')}</td>"
			f"<td><a href='/qc/ncrs/{_he(n.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for n in ncrs
		)
		body = (
			'<h3>Non-Conformance Reports</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>NCR #</th><th>Source</th><th>Product</th>'
			'<th>Severity</th><th>Qty Affected</th><th>Status</th><th>Due</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Non-Conformance Reports", body), 200)

	@expose("/<string:ncr_id>")
	@has_access
	def detail(self, ncr_id: str):
		from pgappforge.plugins.erp.operations.quality.models import NonConformanceReport
		session = _get_session()
		ncr = session.get(NonConformanceReport, ncr_id)
		if ncr is None:
			abort(404)
		return jsonify({
			"id": ncr.id, "tenant_id": ncr.tenant_id,
			"ncr_number": ncr.ncr_number,
			"source_type": ncr.source_type,
			"source_reference_id": ncr.source_reference_id,
			"inspection_id": ncr.inspection_id,
			"product_id": ncr.product_id,
			"quantity_affected": str(ncr.quantity_affected),
			"uom": ncr.uom, "batch_lot_number": ncr.batch_lot_number,
			"severity": ncr.severity, "description": ncr.description,
			"status": ncr.status,
			"root_cause": ncr.root_cause,
			"corrective_action": ncr.corrective_action,
			"preventive_action": ncr.preventive_action,
			"owner_id": ncr.owner_id,
			"due_date": ncr.due_date.isoformat() if ncr.due_date else None,
			"closed_at": ncr.closed_at.isoformat() if ncr.closed_at else None,
			"closed_by": ncr.closed_by,
			"supplier_id": ncr.supplier_id,
			"supplier_claim_value_cents": ncr.supplier_claim_value_cents,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from decimal import Decimal
		from datetime import date as date_type
		from pgappforge.plugins.erp.operations.quality.services import QCService, QCServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "source_type", "product_id", "quantity_affected",
		            "description", "severity")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			ncr = QCService().open_ncr(
				tenant_id=data["tenant_id"],
				source_type=data["source_type"],
				source_reference_id=data.get("source_reference_id"),
				inspection_id=data.get("inspection_id"),
				product_id=data["product_id"],
				quantity_affected=Decimal(str(data["quantity_affected"])),
				uom=data.get("uom", "EA"),
				description=data["description"],
				severity=data["severity"],
				session=session,
				owner_id=data.get("owner_id"),
				due_date=date_type.fromisoformat(data["due_date"]) if data.get("due_date") else None,
				supplier_id=data.get("supplier_id"),
			)
			session.commit()
			return jsonify({"ok": True, "id": ncr.id, "ncr_number": ncr.ncr_number}), 201
		except QCServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:ncr_id>/advance", methods=["POST"])
	@has_access
	def advance(self, ncr_id: str):
		from pgappforge.plugins.erp.operations.quality.services import QCService, QCServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		new_status = data.get("status")
		updated_by = data.get("updated_by", "")
		if not new_status:
			return jsonify({"ok": False, "error": "status required"}), 400
		try:
			ncr = QCService().advance_ncr(
				ncr_id=ncr_id,
				new_status=new_status,
				updated_by=updated_by,
				session=session,
				root_cause=data.get("root_cause"),
				corrective_action=data.get("corrective_action"),
				preventive_action=data.get("preventive_action"),
			)
			session.commit()
			return jsonify({
				"ok": True, "status": ncr.status,
				"closed_at": ncr.closed_at.isoformat() if ncr.closed_at else None,
			})
		except QCServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# QCReportView — 3 canned reports
# ---------------------------------------------------------------------------

class QCReportView(BaseView):
	"""Quality Management reports.

	GET /qc/reports/inspection-summary   — Inspection pass/fail rates
	GET /qc/reports/ncr-aging            — Open NCR aging by severity
	GET /qc/reports/supplier-quality     — Supplier quality trend
	"""

	route_base = "/qc/reports"
	default_view = "inspection_summary"

	@expose("/inspection-summary")
	@has_access
	def inspection_summary(self):
		"""Inspection pass/fail rate summary by product."""
		from pgappforge.plugins.erp.operations.quality.models import QualityInspection
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				QualityInspection.reference_type,
				QualityInspection.overall_result,
				sa.func.count().label("count"),
				sa.func.sum(QualityInspection.inspected_quantity).label("total_inspected"),
				sa.func.sum(QualityInspection.rejected_quantity).label("total_rejected"),
			)
			.where(QualityInspection.status.in_(["PASSED", "FAILED"]))
			.group_by(QualityInspection.reference_type, QualityInspection.overall_result)
			.order_by(QualityInspection.reference_type)
		)
		if tenant_id:
			q = q.where(QualityInspection.tenant_id == tenant_id)

		rows = session.execute(q).all()
		data = [
			{
				"reference_type": r.reference_type,
				"overall_result": r.overall_result,
				"count": r.count,
				"total_inspected": str(r.total_inspected or 0),
				"total_rejected": str(r.total_rejected or 0),
			}
			for r in rows
		]

		if request.args.get("format") == "json":
			return jsonify({"inspection_summary": data})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['reference_type'])}</td>"
			f"<td><span class='label label-{'success' if r['overall_result']=='PASS' else 'danger'}'>{_he(r['overall_result'])}</span></td>"
			f"<td class='text-right'>{r['count']}</td>"
			f"<td class='text-right'>{r['total_inspected']}</td>"
			f"<td class='text-right text-danger'>{r['total_rejected']}</td>"
			f"</tr>"
			for r in data
		)
		body = (
			'<h3>Inspection Summary</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Reference Type</th><th>Result</th><th>Count</th>'
			'<th>Total Inspected</th><th>Total Rejected</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Inspection Summary", body), 200)

	@expose("/ncr-aging")
	@has_access
	def ncr_aging(self):
		"""Open NCR aging: count/qty by severity, flagging overdue."""
		from pgappforge.plugins.erp.operations.quality.models import NonConformanceReport
		from datetime import date as date_type
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		today = date_type.today()

		q = (
			sa.select(NonConformanceReport)
			.where(NonConformanceReport.status != "CLOSED")
			.order_by(
				sa.case(
					(NonConformanceReport.severity == "CRITICAL", 1),
					(NonConformanceReport.severity == "MAJOR", 2),
					else_=3,
				),
				NonConformanceReport.due_date.nullslast(),
			)
		)
		if tenant_id:
			q = q.where(NonConformanceReport.tenant_id == tenant_id)
		ncrs = session.execute(q.limit(500)).scalars().all()

		data = [
			{
				"ncr_number": n.ncr_number,
				"product_id": n.product_id,
				"severity": n.severity,
				"status": n.status,
				"quantity_affected": str(n.quantity_affected),
				"due_date": n.due_date.isoformat() if n.due_date else None,
				"days_overdue": (today - n.due_date).days if n.due_date and n.due_date < today else 0,
				"source_type": n.source_type,
			}
			for n in ncrs
		]

		if request.args.get("format") == "json":
			return jsonify({"ncr_aging": data, "count": len(data)})

		trs = "".join(
			f"<tr class='{'danger' if r['days_overdue'] > 0 else ''}'>"
			f"<td>{_he(r['ncr_number'])}</td>"
			f"<td>{_he(r['product_id'])}</td>"
			f"<td><span class='label label-{'danger' if r['severity']=='CRITICAL' else 'warning' if r['severity']=='MAJOR' else 'default'}'>{_he(r['severity'])}</span></td>"
			f"<td>{_he(r['status'])}</td>"
			f"<td>{_he(r['due_date'] or '—')}</td>"
			f"<td class='text-danger'>{r['days_overdue'] if r['days_overdue'] > 0 else '—'}</td>"
			f"</tr>"
			for r in data
		)
		body = (
			f'<h3>NCR Aging — {len(data)} open</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>NCR #</th><th>Product</th><th>Severity</th>'
			'<th>Status</th><th>Due Date</th><th>Days Overdue</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("NCR Aging", body), 200)

	@expose("/supplier-quality")
	@has_access
	def supplier_quality(self):
		"""Supplier quality trend: NCR counts and rejected qty by supplier."""
		from pgappforge.plugins.erp.operations.quality.models import NonConformanceReport
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				NonConformanceReport.supplier_id,
				sa.func.count().label("ncr_count"),
				sa.func.sum(NonConformanceReport.quantity_affected).label("total_qty_affected"),
				sa.func.sum(
					sa.case((NonConformanceReport.severity == "CRITICAL", 1), else_=0)
				).label("critical_count"),
				sa.func.sum(
					sa.case((NonConformanceReport.severity == "MAJOR", 1), else_=0)
				).label("major_count"),
			)
			.where(
				NonConformanceReport.source_type == "SUPPLIER",
				NonConformanceReport.supplier_id.isnot(None),
			)
			.group_by(NonConformanceReport.supplier_id)
			.order_by(sa.desc(sa.func.count()))
		)
		if tenant_id:
			q = q.where(NonConformanceReport.tenant_id == tenant_id)

		rows = session.execute(q.limit(100)).all()
		data = [
			{
				"supplier_id": r.supplier_id,
				"ncr_count": r.ncr_count,
				"total_qty_affected": str(r.total_qty_affected or 0),
				"critical_count": r.critical_count,
				"major_count": r.major_count,
			}
			for r in rows
		]

		if request.args.get("format") == "json":
			return jsonify({"supplier_quality": data})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['supplier_id'])}</td>"
			f"<td class='text-right'>{r['ncr_count']}</td>"
			f"<td class='text-right text-danger'>{r['critical_count']}</td>"
			f"<td class='text-right text-warning'>{r['major_count']}</td>"
			f"<td class='text-right'>{r['total_qty_affected']}</td>"
			f"</tr>"
			for r in data
		)
		body = (
			'<h3>Supplier Quality Trend</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Supplier ID</th><th>NCR Count</th>'
			'<th>Critical</th><th>Major</th><th>Total Qty Affected</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Supplier Quality Trend", body), 200)


__all__ = [
	"InspectionPlanView",
	"QualityInspectionView",
	"NCRView",
	"QCReportView",
]
