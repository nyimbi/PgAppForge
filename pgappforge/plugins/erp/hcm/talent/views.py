"""
pgappforge/plugins/erp/hcm/talent/views.py

Flask views for the HCM Talent Management plugin.

Registered views:
  RequisitionView        — CRUD + approve/post actions
  CandidateView          — CRUD
  ApplicationView        — CRUD + stage-advance action
  InterviewView          — CRUD + complete action
  OfferView              — CRUD + send/accept/decline actions
  PerformanceReviewView  — CRUD + submit/finalise actions
  TrainingView           — course CRUD + enroll/complete enrollment actions
  TalentReportView       — 3 canned reports:
                           * Pipeline Funnel (per requisition)
                           * Offer Analytics (acceptance rate, avg salary)
                           * Training Completion (per course)

All mutating endpoints: POST/PUT JSON → JSON.
List/detail: HTML for FAB list rendering; JSON available via ?format=json.
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
# RequisitionView
# ---------------------------------------------------------------------------

class RequisitionView(BaseView):
	"""Job requisition CRUD + lifecycle.

	GET  /talent/requisitions/                — list
	GET  /talent/requisitions/<id>            — detail
	POST /talent/requisitions/                — create (DRAFT)
	PUT  /talent/requisitions/<id>            — update (DRAFT only)
	POST /talent/requisitions/<id>/approve    — DRAFT → APPROVED
	POST /talent/requisitions/<id>/post       — APPROVED → POSTED
	POST /talent/requisitions/<id>/cancel     — → CANCELLED
	"""

	route_base = "/talent/requisitions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.talent.models import Requisition
		session = _get_session()
		q = sa.select(Requisition).order_by(sa.desc(Requisition.created_at))
		for field, col in (
			("tenant_id", Requisition.tenant_id),
			("status", Requisition.status),
			("hiring_manager_id", Requisition.hiring_manager_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		reqs = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"requisitions": [
				{
					"id": r.id, "requisition_number": r.requisition_number,
					"position_id": r.position_id,
					"hiring_manager_id": r.hiring_manager_id,
					"headcount": r.headcount,
					"status": r.status,
					"salary_range_min_cents": r.salary_range_min_cents,
					"salary_range_max_cents": r.salary_range_max_cents,
					"currency_code": r.currency_code,
				}
				for r in reqs
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(r.requisition_number)}</td>"
			f"<td>{_he(r.headcount)}</td>"
			f"<td>{_he(r.currency_code)} {(r.salary_range_min_cents or 0) / 100:,.0f}–{(r.salary_range_max_cents or 0) / 100:,.0f}</td>"
			f"<td><span class='label label-{'success' if r.status in ('FILLED',) else 'info'}'>{_he(r.status)}</span></td>"
			f"<td><a href='/talent/requisitions/{_he(r.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for r in reqs
		)
		body = (
			'<h3>Job Requisitions</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Req #</th><th>Headcount</th><th>Salary Range</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Requisitions", body), 200)

	@expose("/<string:req_id>")
	@has_access
	def detail(self, req_id: str):
		from pgappforge.plugins.erp.hcm.talent.models import Requisition
		session = _get_session()
		req = session.get(Requisition, req_id)
		if req is None:
			abort(404)
		return jsonify({
			"id": req.id, "tenant_id": req.tenant_id,
			"requisition_number": req.requisition_number,
			"position_id": req.position_id,
			"hiring_manager_id": req.hiring_manager_id,
			"recruiter_id": req.recruiter_id,
			"department_id": req.department_id,
			"headcount": req.headcount,
			"target_start_date": req.target_start_date.isoformat() if req.target_start_date else None,
			"salary_range_min_cents": req.salary_range_min_cents,
			"salary_range_max_cents": req.salary_range_max_cents,
			"currency_code": req.currency_code,
			"status": req.status,
			"job_description": req.job_description,
			"required_skills": req.required_skills,
			"approved_by": req.approved_by,
			"approved_at": req.approved_at.isoformat() if req.approved_at else None,
			"filled_at": req.filled_at.isoformat() if req.filled_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.talent.models import Requisition
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "requisition_number")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		sal_min = data.get("salary_range_min_cents")
		sal_max = data.get("salary_range_max_cents")
		if sal_min is not None:
			assert isinstance(int(sal_min), int), "salary_range_min_cents must be int"
		if sal_max is not None:
			assert isinstance(int(sal_max), int), "salary_range_max_cents must be int"

		req = Requisition(
			tenant_id=data["tenant_id"],
			requisition_number=data["requisition_number"],
			position_id=data.get("position_id"),
			hiring_manager_id=data.get("hiring_manager_id"),
			recruiter_id=data.get("recruiter_id"),
			department_id=data.get("department_id"),
			headcount=int(data.get("headcount", 1)),
			target_start_date=(
				date_type.fromisoformat(data["target_start_date"])
				if data.get("target_start_date") else None
			),
			salary_range_min_cents=int(sal_min) if sal_min is not None else None,
			salary_range_max_cents=int(sal_max) if sal_max is not None else None,
			currency_code=data.get("currency_code", "USD"),
			job_description=data.get("job_description"),
			required_skills=data.get("required_skills") or [],
			status="DRAFT",
		)
		session.add(req)
		session.commit()
		return jsonify({"ok": True, "id": req.id}), 201

	@expose("/<string:req_id>/approve", methods=["POST"])
	@has_access
	def approve(self, req_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		approver_id = data.get("approver_id")
		if not approver_id:
			return jsonify({"ok": False, "error": "approver_id required"}), 400
		svc = TalentService()
		try:
			req = svc.approve_requisition(req_id, approver_id, session)
			session.commit()
			return jsonify({"ok": True, "status": req.status})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:req_id>/post", methods=["POST"])
	@has_access
	def post_req(self, req_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		svc = TalentService()
		try:
			req = svc.post_requisition(req_id, session)
			session.commit()
			return jsonify({"ok": True, "status": req.status})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:req_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, req_id: str):
		from pgappforge.plugins.erp.hcm.talent.models import Requisition
		session = _get_session()
		req = session.get(Requisition, req_id)
		if req is None:
			abort(404)
		if req.status in ("FILLED",):
			return jsonify({"ok": False, "error": "Cannot cancel a FILLED requisition"}), 400
		req.status = "CANCELLED"
		req.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "CANCELLED"})


# ---------------------------------------------------------------------------
# CandidateView
# ---------------------------------------------------------------------------

class CandidateView(BaseView):
	"""Candidate master CRUD.

	GET  /talent/candidates/          — list
	GET  /talent/candidates/<id>      — detail
	POST /talent/candidates/          — create
	PUT  /talent/candidates/<id>      — update
	"""

	route_base = "/talent/candidates"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.talent.models import Candidate
		session = _get_session()
		q = sa.select(Candidate).order_by(sa.desc(Candidate.created_at))
		if request.args.get("source"):
			q = q.where(Candidate.source == request.args["source"])
		if request.args.get("tenant_id"):
			q = q.where(Candidate.tenant_id == request.args["tenant_id"])
		candidates = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"candidates": [
				{
					"id": c.id, "full_name": c.full_name, "email": c.email,
					"source": c.source, "current_title": c.current_title,
					"experience_years": str(c.experience_years) if c.experience_years else None,
				}
				for c in candidates
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(c.full_name)}</td>"
			f"<td>{_he(c.email)}</td>"
			f"<td>{_he(c.current_title or '')}</td>"
			f"<td>{_he(c.source)}</td>"
			f"<td><a href='/talent/candidates/{_he(c.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for c in candidates
		)
		body = (
			'<h3>Candidates</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Name</th><th>Email</th><th>Current Title</th><th>Source</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Candidates", body), 200)

	@expose("/<string:candidate_id>")
	@has_access
	def detail(self, candidate_id: str):
		from pgappforge.plugins.erp.hcm.talent.models import Candidate
		session = _get_session()
		c = session.get(Candidate, candidate_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id, "tenant_id": c.tenant_id, "party_id": c.party_id,
			"full_name": c.full_name, "email": c.email, "phone": c.phone,
			"source": c.source, "current_employer": c.current_employer,
			"current_title": c.current_title,
			"desired_salary_cents": c.desired_salary_cents,
			"notice_period_days": c.notice_period_days,
			"work_authorization": c.work_authorization,
			"experience_years": str(c.experience_years) if c.experience_years else None,
			"skills": c.skills,
			"linkedin_url": c.linkedin_url,
			"portfolio_url": c.portfolio_url,
			"resume_url": c.resume_url,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.talent.models import Candidate
		session = _get_session()
		data = request.get_json(silent=True) or {}
		if not data.get("tenant_id"):
			return jsonify({"ok": False, "error": "tenant_id required"}), 400

		desired_salary = data.get("desired_salary_cents")
		if desired_salary is not None:
			assert isinstance(int(desired_salary), int), "desired_salary_cents must be int"

		c = Candidate(
			tenant_id=data["tenant_id"],
			party_id=data.get("party_id"),
			full_name=data.get("full_name"),
			email=data.get("email"),
			phone=data.get("phone"),
			source=data.get("source", "DIRECT"),
			current_employer=data.get("current_employer"),
			current_title=data.get("current_title"),
			desired_salary_cents=int(desired_salary) if desired_salary is not None else None,
			notice_period_days=data.get("notice_period_days"),
			work_authorization=data.get("work_authorization"),
			experience_years=data.get("experience_years"),
			skills=data.get("skills") or [],
			linkedin_url=data.get("linkedin_url"),
			portfolio_url=data.get("portfolio_url"),
			resume_url=data.get("resume_url"),
		)
		session.add(c)
		session.commit()
		return jsonify({"ok": True, "id": c.id}), 201

	@expose("/<string:candidate_id>", methods=["PUT"])
	@has_access
	def update(self, candidate_id: str):
		from pgappforge.plugins.erp.hcm.talent.models import Candidate
		session = _get_session()
		c = session.get(Candidate, candidate_id)
		if c is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = [
			"full_name", "email", "phone", "source", "current_employer", "current_title",
			"desired_salary_cents", "notice_period_days", "work_authorization",
			"experience_years", "skills", "linkedin_url", "portfolio_url", "resume_url",
		]
		for field in updatable:
			if field in data:
				setattr(c, field, data[field])
		c.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# ApplicationView
# ---------------------------------------------------------------------------

class ApplicationView(BaseView):
	"""Application CRUD + pipeline stage management.

	GET  /talent/applications/                   — list
	GET  /talent/applications/<id>               — detail
	POST /talent/applications/                   — create
	POST /talent/applications/<id>/advance       — advance pipeline stage
	"""

	route_base = "/talent/applications"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.talent.models import Application
		session = _get_session()
		q = sa.select(Application).order_by(sa.desc(Application.applied_at))
		for field, col in (
			("requisition_id", Application.requisition_id),
			("candidate_id", Application.candidate_id),
			("stage", Application.stage),
			("tenant_id", Application.tenant_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		apps = session.execute(q.limit(500)).scalars().all()
		return jsonify({"applications": [
			{
				"id": a.id, "requisition_id": a.requisition_id,
				"candidate_id": a.candidate_id,
				"applied_at": a.applied_at.isoformat() if a.applied_at else None,
				"stage": a.stage,
				"rejection_reason": a.rejection_reason,
			}
			for a in apps
		]})

	@expose("/<string:app_id>")
	@has_access
	def detail(self, app_id: str):
		from pgappforge.plugins.erp.hcm.talent.models import Application
		session = _get_session()
		app = session.get(Application, app_id)
		if app is None:
			abort(404)
		return jsonify({
			"id": app.id, "tenant_id": app.tenant_id,
			"requisition_id": app.requisition_id,
			"candidate_id": app.candidate_id,
			"applied_at": app.applied_at.isoformat() if app.applied_at else None,
			"stage": app.stage,
			"rejection_reason": app.rejection_reason,
			"source": app.source,
			"recruiter_notes": app.recruiter_notes,
			"interviews": [
				{
					"id": i.id, "interview_type": i.interview_type,
					"scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
					"status": i.status, "overall_rating": str(i.overall_rating) if i.overall_rating else None,
					"recommendation": i.recommendation,
				}
				for i in app.interviews
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.talent.models import Application, Requisition
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "requisition_id", "candidate_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		req = session.get(Requisition, data["requisition_id"])
		if req is None:
			return jsonify({"ok": False, "error": "requisition not found"}), 404
		if req.status not in ("POSTED", "IN_PROGRESS"):
			return jsonify({"ok": False, "error": f"Requisition is {req.status!r}; must be POSTED or IN_PROGRESS to accept applications"}), 400

		app = Application(
			tenant_id=data["tenant_id"],
			requisition_id=data["requisition_id"],
			candidate_id=data["candidate_id"],
			source=data.get("source"),
			recruiter_notes=data.get("recruiter_notes"),
			stage="APPLIED",
		)
		session.add(app)

		# Auto-transition requisition to IN_PROGRESS
		if req.status == "POSTED":
			req.status = "IN_PROGRESS"
			req.updated_at = datetime.now(timezone.utc)

		session.commit()
		return jsonify({"ok": True, "id": app.id}), 201

	@expose("/<string:app_id>/advance", methods=["POST"])
	@has_access
	def advance(self, app_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		new_stage = data.get("stage")
		if not new_stage:
			return jsonify({"ok": False, "error": "stage required"}), 400
		svc = TalentService()
		try:
			app = svc.advance_stage(
				app_id, new_stage, session,
				rejection_reason=data.get("rejection_reason", ""),
				recruiter_notes=data.get("recruiter_notes", ""),
			)
			session.commit()
			return jsonify({"ok": True, "stage": app.stage})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# InterviewView
# ---------------------------------------------------------------------------

class InterviewView(BaseView):
	"""Interview scheduling and completion.

	POST /talent/interviews/                     — schedule interview
	GET  /talent/interviews/<id>                 — detail
	POST /talent/interviews/<id>/complete        — record scorecard + recommendation
	POST /talent/interviews/<id>/cancel          — cancel
	"""

	route_base = "/talent/interviews"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.talent.models import Interview
		session = _get_session()
		q = sa.select(Interview).order_by(sa.desc(Interview.scheduled_at))
		if request.args.get("application_id"):
			q = q.where(Interview.application_id == request.args["application_id"])
		if request.args.get("status"):
			q = q.where(Interview.status == request.args["status"])
		interviews = session.execute(q.limit(500)).scalars().all()
		return jsonify({"interviews": [
			{
				"id": i.id, "application_id": i.application_id,
				"interview_type": i.interview_type,
				"scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
				"duration_minutes": i.duration_minutes,
				"status": i.status,
				"overall_rating": str(i.overall_rating) if i.overall_rating else None,
				"recommendation": i.recommendation,
			}
			for i in interviews
		]})

	@expose("/<string:interview_id>")
	@has_access
	def detail(self, interview_id: str):
		from pgappforge.plugins.erp.hcm.talent.models import Interview
		session = _get_session()
		iv = session.execute(
			sa.select(Interview).where(Interview.id == interview_id)
		).scalar_one_or_none()
		if iv is None:
			abort(404)
		return jsonify({
			"id": iv.id, "tenant_id": iv.tenant_id,
			"application_id": iv.application_id,
			"interview_type": iv.interview_type,
			"scheduled_at": iv.scheduled_at.isoformat() if iv.scheduled_at else None,
			"duration_minutes": iv.duration_minutes,
			"interviewer_ids": iv.interviewer_ids,
			"location": iv.location,
			"status": iv.status,
			"scorecard": iv.scorecard,
			"overall_rating": str(iv.overall_rating) if iv.overall_rating else None,
			"recommendation": iv.recommendation,
			"completed_at": iv.completed_at.isoformat() if iv.completed_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def schedule(self):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		application_id = data.pop("application_id", None)
		if not application_id:
			return jsonify({"ok": False, "error": "application_id required"}), 400
		if not data.get("interview_type") or not data.get("scheduled_at"):
			return jsonify({"ok": False, "error": "interview_type and scheduled_at required"}), 400
		svc = TalentService()
		try:
			iv = svc.schedule_interview(application_id, data, session)
			session.commit()
			return jsonify({"ok": True, "id": iv.id, "status": iv.status}), 201
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:interview_id>/complete", methods=["POST"])
	@has_access
	def complete(self, interview_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("overall_rating", "recommendation")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		svc = TalentService()
		try:
			iv = svc.complete_interview(
				interview_id,
				scorecard=data.get("scorecard") or {},
				overall_rating=str(data["overall_rating"]),
				recommendation=data["recommendation"],
				session=session,
			)
			session.commit()
			return jsonify({
				"ok": True,
				"status": iv.status,
				"overall_rating": str(iv.overall_rating),
				"recommendation": iv.recommendation,
			})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:interview_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, interview_id: str):
		from pgappforge.plugins.erp.hcm.talent.models import Interview
		session = _get_session()
		iv = session.execute(
			sa.select(Interview).where(Interview.id == interview_id)
		).scalar_one_or_none()
		if iv is None:
			abort(404)
		if iv.status != "SCHEDULED":
			return jsonify({"ok": False, "error": f"Interview is {iv.status!r}; must be SCHEDULED to cancel"}), 400
		iv.status = "CANCELLED"
		iv.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "CANCELLED"})


# ---------------------------------------------------------------------------
# OfferView
# ---------------------------------------------------------------------------

class OfferView(BaseView):
	"""Employment offer management.

	POST /talent/offers/                       — extend offer (DRAFT)
	GET  /talent/offers/<id>                   — detail
	POST /talent/offers/<id>/send              — DRAFT → SENT
	POST /talent/offers/<id>/accept            — SENT → ACCEPTED
	POST /talent/offers/<id>/decline           — SENT → DECLINED
	"""

	route_base = "/talent/offers"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.talent.models import Offer
		session = _get_session()
		q = sa.select(Offer).order_by(sa.desc(Offer.created_at))
		if request.args.get("status"):
			q = q.where(Offer.status == request.args["status"])
		if request.args.get("tenant_id"):
			q = q.where(Offer.tenant_id == request.args["tenant_id"])
		offers = session.execute(q.limit(500)).scalars().all()
		return jsonify({"offers": [
			{
				"id": o.id, "application_id": o.application_id,
				"base_salary_cents": o.base_salary_cents,
				"currency_code": o.currency_code,
				"signing_bonus_cents": o.signing_bonus_cents,
				"start_date": o.start_date.isoformat() if o.start_date else None,
				"expiry_date": o.expiry_date.isoformat() if o.expiry_date else None,
				"status": o.status,
			}
			for o in offers
		]})

	@expose("/<string:offer_id>")
	@has_access
	def detail(self, offer_id: str):
		from pgappforge.plugins.erp.hcm.talent.models import Offer
		session = _get_session()
		offer = session.get(Offer, offer_id)
		if offer is None:
			abort(404)
		return jsonify({
			"id": offer.id, "tenant_id": offer.tenant_id,
			"application_id": offer.application_id,
			"base_salary_cents": offer.base_salary_cents,
			"currency_code": offer.currency_code,
			"signing_bonus_cents": offer.signing_bonus_cents,
			"equity_details": offer.equity_details,
			"start_date": offer.start_date.isoformat() if offer.start_date else None,
			"expiry_date": offer.expiry_date.isoformat() if offer.expiry_date else None,
			"status": offer.status,
			"sent_at": offer.sent_at.isoformat() if offer.sent_at else None,
			"responded_at": offer.responded_at.isoformat() if offer.responded_at else None,
			"decline_reason": offer.decline_reason,
			"notes": offer.notes,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		application_id = data.pop("application_id", None)
		if not application_id:
			return jsonify({"ok": False, "error": "application_id required"}), 400
		required = ("base_salary_cents", "start_date", "expiry_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		svc = TalentService()
		try:
			offer = svc.extend_offer(application_id, data, session)
			session.commit()
			return jsonify({
				"ok": True, "id": offer.id,
				"base_salary_cents": offer.base_salary_cents,
				"status": offer.status,
			}), 201
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:offer_id>/send", methods=["POST"])
	@has_access
	def send(self, offer_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		svc = TalentService()
		try:
			offer = svc.send_offer(offer_id, session)
			session.commit()
			return jsonify({"ok": True, "status": offer.status})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:offer_id>/accept", methods=["POST"])
	@has_access
	def accept(self, offer_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		svc = TalentService()
		try:
			offer = svc.accept_offer(offer_id, session)
			session.commit()
			return jsonify({"ok": True, "status": offer.status})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:offer_id>/decline", methods=["POST"])
	@has_access
	def decline(self, offer_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		svc = TalentService()
		try:
			offer = svc.decline_offer(offer_id, data.get("reason", ""), session)
			session.commit()
			return jsonify({"ok": True, "status": offer.status})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# PerformanceReviewView
# ---------------------------------------------------------------------------

class PerformanceReviewView(BaseView):
	"""Performance review CRUD + workflow.

	GET  /talent/reviews/                     — list
	GET  /talent/reviews/<id>                 — detail
	POST /talent/reviews/                     — create (DRAFT)
	PUT  /talent/reviews/<id>                 — update (DRAFT only)
	POST /talent/reviews/<id>/submit          — DRAFT → SUBMITTED
	POST /talent/reviews/<id>/finalise        — SUBMITTED|CALIBRATED → FINAL
	"""

	route_base = "/talent/reviews"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.talent.models import PerformanceReview
		session = _get_session()
		q = sa.select(PerformanceReview).order_by(sa.desc(PerformanceReview.period_end))
		for field, col in (
			("employee_id", PerformanceReview.employee_id),
			("review_cycle", PerformanceReview.review_cycle),
			("status", PerformanceReview.status),
			("tenant_id", PerformanceReview.tenant_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		reviews = session.execute(q.limit(500)).scalars().all()
		return jsonify({"reviews": [
			{
				"id": r.id, "employee_id": r.employee_id, "reviewer_id": r.reviewer_id,
				"review_cycle": r.review_cycle,
				"period_start": r.period_start.isoformat() if r.period_start else None,
				"period_end": r.period_end.isoformat() if r.period_end else None,
				"overall_rating": str(r.overall_rating) if r.overall_rating else None,
				"rating_label": r.rating_label,
				"status": r.status,
			}
			for r in reviews
		]})

	@expose("/<string:review_id>")
	@has_access
	def detail(self, review_id: str):
		from pgappforge.plugins.erp.hcm.talent.models import PerformanceReview
		session = _get_session()
		r = session.get(PerformanceReview, review_id)
		if r is None:
			abort(404)
		return jsonify({
			"id": r.id, "tenant_id": r.tenant_id,
			"employee_id": r.employee_id, "reviewer_id": r.reviewer_id,
			"review_cycle": r.review_cycle,
			"period_start": r.period_start.isoformat() if r.period_start else None,
			"period_end": r.period_end.isoformat() if r.period_end else None,
			"overall_rating": str(r.overall_rating) if r.overall_rating else None,
			"rating_label": r.rating_label,
			"goals_achievement": r.goals_achievement,
			"competency_scores": r.competency_scores,
			"development_plan": r.development_plan,
			"status": r.status,
			"submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
			"finalised_at": r.finalised_at.isoformat() if r.finalised_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.talent.models import PerformanceReview
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "employee_id", "reviewer_id", "review_cycle", "period_start", "period_end")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		valid_cycles = ("ANNUAL", "MID_YEAR", "PROBATION", "360")
		if data["review_cycle"] not in valid_cycles:
			return jsonify({"ok": False, "error": f"review_cycle must be one of {valid_cycles}"}), 400

		r = PerformanceReview(
			tenant_id=data["tenant_id"],
			employee_id=data["employee_id"],
			reviewer_id=data["reviewer_id"],
			review_cycle=data["review_cycle"],
			period_start=date_type.fromisoformat(data["period_start"]),
			period_end=date_type.fromisoformat(data["period_end"]),
			goals_achievement=data.get("goals_achievement") or [],
			competency_scores=data.get("competency_scores") or [],
			development_plan=data.get("development_plan"),
			status="DRAFT",
		)
		session.add(r)
		session.commit()
		return jsonify({"ok": True, "id": r.id}), 201

	@expose("/<string:review_id>/submit", methods=["POST"])
	@has_access
	def submit(self, review_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		svc = TalentService()
		try:
			r = svc.submit_review(review_id, session)
			session.commit()
			return jsonify({"ok": True, "status": r.status})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:review_id>/finalise", methods=["POST"])
	@has_access
	def finalise(self, review_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		from pgappforge.plugins.erp.hcm.talent.models import PerformanceReview
		from decimal import Decimal
		session = _get_session()
		data = request.get_json(silent=True) or {}

		# Allow setting rating at finalise time
		if data.get("overall_rating") or data.get("rating_label"):
			r = session.get(PerformanceReview, review_id)
			if r is None:
				abort(404)
			if data.get("overall_rating"):
				r.overall_rating = Decimal(str(data["overall_rating"]))
			if data.get("rating_label"):
				r.rating_label = data["rating_label"]
			session.flush()

		svc = TalentService()
		try:
			r = svc.finalise_review(review_id, session)
			session.commit()
			return jsonify({
				"ok": True, "status": r.status,
				"overall_rating": str(r.overall_rating) if r.overall_rating else None,
			})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# TrainingView
# ---------------------------------------------------------------------------

class TrainingView(BaseView):
	"""Training course catalogue + enrollment management.

	GET  /talent/training/courses/               — list courses
	POST /talent/training/courses/               — create course
	POST /talent/training/enroll                 — enroll employee
	GET  /talent/training/enrollments/           — list enrollments
	POST /talent/training/enrollments/<id>/complete — mark completed
	"""

	route_base = "/talent/training"
	default_view = "courses"

	@expose("/courses")
	@has_access
	def courses(self):
		from pgappforge.plugins.erp.hcm.talent.models import TrainingCourse
		session = _get_session()
		q = sa.select(TrainingCourse).order_by(TrainingCourse.title)
		if request.args.get("delivery"):
			q = q.where(TrainingCourse.delivery == request.args["delivery"])
		if request.args.get("active_only", "1") == "1":
			q = q.where(TrainingCourse.is_active.is_(True))
		courses = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"courses": [
				{
					"id": c.id, "course_code": c.course_code, "title": c.title,
					"provider": c.provider, "delivery": c.delivery,
					"duration_hours": str(c.duration_hours),
					"cost_cents": c.cost_cents, "is_active": c.is_active,
				}
				for c in courses
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(c.course_code)}</td>"
			f"<td>{_he(c.title)}</td>"
			f"<td>{_he(c.provider or 'Internal')}</td>"
			f"<td>{_he(c.delivery)}</td>"
			f"<td class='text-right'>{c.duration_hours}</td>"
			f"<td class='text-right'>{c.cost_cents / 100:,.2f}</td>"
			f"</tr>"
			for c in courses
		)
		body = (
			'<h3>Training Courses</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Code</th><th>Title</th><th>Provider</th>'
			'<th>Delivery</th><th>Hours</th><th>Cost</th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Training Courses", body), 200)

	@expose("/courses", methods=["POST"])
	@has_access
	def create_course(self):
		from pgappforge.plugins.erp.hcm.talent.models import TrainingCourse
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "course_code", "title")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		cost = int(data.get("cost_cents", 0))
		assert isinstance(cost, int), "cost_cents must be int"

		c = TrainingCourse(
			tenant_id=data["tenant_id"],
			course_code=data["course_code"],
			title=data["title"],
			provider=data.get("provider"),
			delivery=data.get("delivery", "ONLINE"),
			duration_hours=data.get("duration_hours", 0),
			cost_cents=cost,
			skills_taught=data.get("skills_taught") or [],
			is_active=bool(data.get("is_active", True)),
			description=data.get("description"),
		)
		session.add(c)
		session.commit()
		return jsonify({"ok": True, "id": c.id}), 201

	@expose("/enroll", methods=["POST"])
	@has_access
	def enroll(self):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("employee_id", "course_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		svc = TalentService()
		try:
			enrollment = svc.enroll_training(data["employee_id"], data["course_id"], session)
			# Set tenant_id from request if provided
			if data.get("tenant_id") and not enrollment.tenant_id:
				enrollment.tenant_id = data["tenant_id"]
			session.commit()
			return jsonify({"ok": True, "id": enrollment.id, "status": enrollment.status}), 201
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/enrollments")
	@has_access
	def enrollments(self):
		from pgappforge.plugins.erp.hcm.talent.models import TrainingEnrollment
		session = _get_session()
		q = sa.select(TrainingEnrollment).order_by(sa.desc(TrainingEnrollment.enrolled_at))
		for field, col in (
			("employee_id", TrainingEnrollment.employee_id),
			("course_id", TrainingEnrollment.course_id),
			("status", TrainingEnrollment.status),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		enrollments = session.execute(q.limit(500)).scalars().all()
		return jsonify({"enrollments": [
			{
				"id": e.id, "employee_id": e.employee_id, "course_id": e.course_id,
				"enrolled_at": e.enrolled_at.isoformat() if e.enrolled_at else None,
				"completed_at": e.completed_at.isoformat() if e.completed_at else None,
				"score": str(e.score) if e.score else None,
				"status": e.status,
			}
			for e in enrollments
		]})

	@expose("/enrollments/<string:enrollment_id>/complete", methods=["POST"])
	@has_access
	def complete_enrollment(self, enrollment_id: str):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		svc = TalentService()
		try:
			enrollment = svc.complete_training(
				enrollment_id,
				score=str(data.get("score", "100.00")),
				certificate_url=data.get("certificate_url", ""),
				session=session,
			)
			session.commit()
			return jsonify({"ok": True, "status": enrollment.status, "score": str(enrollment.score)})
		except TalentServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# TalentReportView — 3 canned reports
# ---------------------------------------------------------------------------

class TalentReportView(BaseView):
	"""Talent Management canned reports.

	GET /talent/reports/pipeline     — Pipeline Funnel per requisition
	GET /talent/reports/offers       — Offer Analytics (acceptance rate, avg salary)
	GET /talent/reports/training     — Training Completion per course
	"""

	route_base = "/talent/reports"
	default_view = "pipeline"

	@expose("/pipeline")
	@has_access
	def pipeline(self):
		"""Pipeline Funnel — stage counts for a given requisition."""
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentServiceError
		session = _get_session()
		requisition_id = request.args.get("requisition_id")
		if not requisition_id:
			return jsonify({"error": "requisition_id required"}), 400
		svc = TalentService()
		try:
			summary = svc.pipeline_summary(requisition_id, session)
		except TalentServiceError as exc:
			return jsonify({"error": str(exc)}), 400

		if request.args.get("format") == "json":
			return jsonify(summary)

		stage_rows = "".join(
			f"<tr><td>{_he(stage)}</td><td class='text-right'>{count}</td>"
			f"<td class='text-right'>{count / max(summary['total_applications'], 1) * 100:.1f}%</td></tr>"
			for stage, count in summary["stages"].items()
		)
		body = (
			f'<h3>Pipeline Funnel — {_he(summary["requisition_number"])}</h3>'
			f'<p>Status: <strong>{_he(summary["status"])}</strong> | Headcount: {summary["headcount"]}</p>'
			'<table class="table table-condensed table-bordered" style="width:400px">'
			'<thead><tr><th>Stage</th><th>Count</th><th>Conversion</th></tr></thead>'
			f'<tbody>{stage_rows}</tbody></table>'
			f'<p>Interviews Scheduled: {summary["interviews_scheduled"]} | '
			f'Offers Sent: {summary["offers_sent"]} | Offers Accepted: {summary["offers_accepted"]}</p>'
			f'<p>Avg Interview Rating: {summary["avg_interview_rating"] or "N/A"}</p>'
		)
		return make_response(_page_html("Pipeline Funnel", body), 200)

	@expose("/offers")
	@has_access
	def offers(self):
		"""Offer Analytics — acceptance rate and salary distribution."""
		from pgappforge.plugins.erp.hcm.talent.models import Offer
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = sa.select(
			Offer.status,
			sa.func.count().label("cnt"),
			sa.func.coalesce(sa.func.avg(Offer.base_salary_cents), 0).label("avg_salary"),
			sa.func.coalesce(sa.func.min(Offer.base_salary_cents), 0).label("min_salary"),
			sa.func.coalesce(sa.func.max(Offer.base_salary_cents), 0).label("max_salary"),
		).group_by(Offer.status)
		if tenant_id:
			q = q.where(Offer.tenant_id == tenant_id)
		rows = session.execute(q).all()

		data = [
			{
				"status": r.status,
				"count": r.cnt,
				"avg_salary_cents": int(r.avg_salary or 0),
				"min_salary_cents": int(r.min_salary or 0),
				"max_salary_cents": int(r.max_salary or 0),
			}
			for r in rows
		]
		total = sum(d["count"] for d in data)
		accepted = next((d["count"] for d in data if d["status"] == "ACCEPTED"), 0)
		sent_total = sum(d["count"] for d in data if d["status"] in ("SENT", "ACCEPTED", "DECLINED", "EXPIRED"))
		acceptance_rate = (accepted / sent_total * 100) if sent_total else 0.0

		if request.args.get("format") == "json":
			return jsonify({
				"offer_analytics": data,
				"total_offers": total,
				"acceptance_rate_pct": round(acceptance_rate, 1),
			})

		trs = "".join(
			f"<tr><td>{_he(d['status'])}</td><td class='text-right'>{d['count']}</td>"
			f"<td class='text-right'>{d['avg_salary_cents'] / 100:,.0f}</td>"
			f"<td class='text-right'>{d['min_salary_cents'] / 100:,.0f}</td>"
			f"<td class='text-right'>{d['max_salary_cents'] / 100:,.0f}</td></tr>"
			for d in data
		)
		body = (
			'<h3>Offer Analytics</h3>'
			f'<p>Acceptance Rate: <strong>{acceptance_rate:.1f}%</strong> ({accepted}/{sent_total} sent)</p>'
			'<table class="table table-condensed table-bordered">'
			'<thead><tr><th>Status</th><th>Count</th><th>Avg Salary</th><th>Min</th><th>Max</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
		)
		return make_response(_page_html("Offer Analytics", body), 200)

	@expose("/training")
	@has_access
	def training(self):
		"""Training Completion — completion rates per course."""
		from pgappforge.plugins.erp.hcm.talent.models import TrainingCourse, TrainingEnrollment
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				TrainingCourse.course_code,
				TrainingCourse.title,
				TrainingEnrollment.status,
				sa.func.count().label("cnt"),
				sa.func.coalesce(sa.func.avg(TrainingEnrollment.score), 0).label("avg_score"),
			)
			.join(TrainingEnrollment, TrainingEnrollment.course_id == TrainingCourse.id)
			.group_by(TrainingCourse.course_code, TrainingCourse.title, TrainingEnrollment.status)
			.order_by(TrainingCourse.title, TrainingEnrollment.status)
		)
		if tenant_id:
			q = q.where(TrainingCourse.tenant_id == tenant_id)
		rows = session.execute(q).all()

		# Aggregate by course
		by_course: dict[str, dict] = {}
		for r in rows:
			key = r.course_code
			if key not in by_course:
				by_course[key] = {"course_code": key, "title": r.title, "statuses": {}}
			by_course[key]["statuses"][r.status] = {
				"count": r.cnt, "avg_score": float(r.avg_score or 0)
			}

		data = list(by_course.values())

		if request.args.get("format") == "json":
			return jsonify({"training_report": data})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(d['course_code'])}</td>"
			f"<td>{_he(d['title'])}</td>"
			f"<td class='text-right'>{d['statuses'].get('ENROLLED', {}).get('count', 0)}</td>"
			f"<td class='text-right'>{d['statuses'].get('COMPLETED', {}).get('count', 0)}</td>"
			f"<td class='text-right'>{d['statuses'].get('COMPLETED', {}).get('avg_score', 0):.1f}</td>"
			f"</tr>"
			for d in data
		)
		body = (
			'<h3>Training Completion Report</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Code</th><th>Course</th><th>Enrolled</th><th>Completed</th><th>Avg Score</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
		)
		return make_response(_page_html("Training Report", body), 200)


__all__ = [
	"RequisitionView",
	"CandidateView",
	"ApplicationView",
	"InterviewView",
	"OfferView",
	"PerformanceReviewView",
	"TrainingView",
	"TalentReportView",
]
