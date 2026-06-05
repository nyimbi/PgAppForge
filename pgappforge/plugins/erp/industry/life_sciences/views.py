"""
pgappforge/plugins/erp/industry/life_sciences/views.py

Flask views for the Life Sciences plugin.

Views:
  ClinicalTrialView         — CRUD + Enroll Subject / Generate Report / Submit to Authority
  TrialSubjectView          — CRUD + privacy-gated national_id
  TrialEventView            — CRUD (immutable) + Report to Authority action
  RegulatorySubmissionView  — CRUD + Track Status / Upload Response
  AdverseEventDashboardView — BaseView at /life-sciences/safety/ — pharmacovigilance
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
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
	from pgappforge.plugins.erp.industry.life_sciences.services import LifeSciencesService
	return LifeSciencesService()


def _has_pii_access() -> bool:
	"""Return True if current user has can_ls_subject_pii_read permission."""
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab is None:
			return False
		sm = ab.sm
		return sm.has_access("can_ls_subject_pii_read", "TrialSubjectView")
	except Exception:
		return False


def _parse_date(s: str | None, default: date | None = None) -> date | None:
	if not s:
		return default
	return date.fromisoformat(s)


# ---------------------------------------------------------------------------
# ClinicalTrialView
# ---------------------------------------------------------------------------

class ClinicalTrialView(BaseView):
	"""Clinical trial CRUD + business actions.

	Widget hints:
	  - ProgressWidget (enrollment_target vs enrolled_count)
	  - DateRangeWidget (start_date / estimated_completion_date)
	  - Select2 (indication — coded therapeutic area list)

	GET  /life-sciences/trials/                         — list
	GET  /life-sciences/trials/<id>                     — detail
	POST /life-sciences/trials/                         — create
	POST /life-sciences/trials/<id>/enroll             — enroll subject
	POST /life-sciences/trials/<id>/randomize          — run permuted block randomization
	GET  /life-sciences/trials/<id>/report             — generate CSR summary
	GET  /life-sciences/trials/<id>/dashboard          — trial dashboard
	POST /life-sciences/trials/<id>/submit             — submit to regulatory authority
	"""

	route_base = "/life-sciences/trials"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.life_sciences.models import ClinicalTrial
		session = _get_session()
		phase = request.args.get("phase")
		status = request.args.get("status")
		tenant_id = request.args.get("tenant_id")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = (
			sa.select(ClinicalTrial)
			.order_by(ClinicalTrial.start_date.desc().nullslast())
			.limit(limit)
		)
		if phase:
			q = q.where(ClinicalTrial.phase == phase)
		if status:
			q = q.where(ClinicalTrial.status == status)
		if tenant_id:
			q = q.where(ClinicalTrial.tenant_id == tenant_id)

		trials = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": t.id,
				"trial_id": t.trial_id,
				"title": t.title,
				"phase": t.phase,
				"indication": t.indication,
				"sponsor_name": t.sponsor_name,
				"status": t.status,
				"enrollment_target": t.enrollment_target,
				"enrolled_count": t.enrolled_count,
				"start_date": t.start_date.isoformat() if t.start_date else None,
				"estimated_completion_date": t.estimated_completion_date.isoformat() if t.estimated_completion_date else None,
				# ProgressWidget hint: enrolled_count / enrollment_target
				"_enrollment_progress_pct": (
					round(t.enrolled_count / t.enrollment_target * 100, 1)
					if t.enrollment_target > 0 else 0
				),
				"_widget_hints": {
					"enrollment": "ProgressWidget",
					"indication": "Select2Widget",
					"trial_period": "DateRangeWidget",
				},
			}
			for t in trials
		])

	@expose("/<string:trial_id>")
	@has_access
	def detail(self, trial_id: str):
		from pgappforge.plugins.erp.industry.life_sciences.models import ClinicalTrial
		session = _get_session()
		t = session.get(ClinicalTrial, trial_id)
		if t is None:
			abort(404, f"ClinicalTrial {trial_id!r} not found")
		return jsonify({
			"id": t.id,
			"tenant_id": t.tenant_id,
			"trial_id": t.trial_id,
			"title": t.title,
			"protocol_number": t.protocol_number,
			"nct_number": t.nct_number,
			"phase": t.phase,
			"indication": t.indication,
			"therapeutic_area": t.therapeutic_area,
			"sponsor_id": t.sponsor_id,
			"sponsor_name": t.sponsor_name,
			"principal_investigator_id": t.principal_investigator_id,
			"enrollment_target": t.enrollment_target,
			"enrolled_count": t.enrolled_count,
			"start_date": t.start_date.isoformat() if t.start_date else None,
			"primary_endpoint": t.primary_endpoint.isoformat() if t.primary_endpoint else None,
			"estimated_completion_date": t.estimated_completion_date.isoformat() if t.estimated_completion_date else None,
			"actual_completion_date": t.actual_completion_date.isoformat() if t.actual_completion_date else None,
			"status": t.status,
			"regulatory_approvals": t.regulatory_approvals,
			"arms": t.arms,
			"endpoints": t.endpoints,
			"inclusion_criteria": t.inclusion_criteria,
			"exclusion_criteria": t.exclusion_criteria,
			"_enrollment_progress_pct": (
				round(t.enrolled_count / t.enrollment_target * 100, 1)
				if t.enrollment_target > 0 else 0
			),
			"_widget_hints": {
				"enrollment": "ProgressWidget",
				"indication": "Select2Widget",
				"trial_period": "DateRangeWidget",
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.life_sciences.models import ClinicalTrial
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "trial_id", "title", "phase", "indication", "enrollment_target")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		trial = ClinicalTrial(
			tenant_id=data["tenant_id"],
			trial_id=data["trial_id"],
			title=data["title"],
			protocol_number=data.get("protocol_number"),
			nct_number=data.get("nct_number"),
			phase=data["phase"],
			indication=data["indication"],
			therapeutic_area=data.get("therapeutic_area"),
			sponsor_id=data.get("sponsor_id"),
			sponsor_name=data.get("sponsor_name"),
			principal_investigator_id=data.get("principal_investigator_id"),
			enrollment_target=int(data["enrollment_target"]),
			enrolled_count=0,
			start_date=_parse_date(data.get("start_date")),
			primary_endpoint=_parse_date(data.get("primary_endpoint")),
			estimated_completion_date=_parse_date(data.get("estimated_completion_date")),
			status=data.get("status", "DESIGN"),
			regulatory_approvals=data.get("regulatory_approvals", []),
			arms=data.get("arms", []),
			endpoints=data.get("endpoints", []),
			inclusion_criteria=data.get("inclusion_criteria"),
			exclusion_criteria=data.get("exclusion_criteria"),
		)
		session.add(trial)
		session.commit()
		return jsonify({"trial_record_id": trial.id, "trial_id": trial.trial_id}), 201

	@expose("/<string:trial_id>/enroll", methods=["POST"])
	@has_access
	def enroll_subject(self, trial_id: str):
		"""Action: Enroll a subject into the trial."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("subject_number", "consent_date", "arm")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			subject = _svc().enroll_subject(
				trial_id=trial_id,
				subject_number=data["subject_number"],
				consent_date=date.fromisoformat(data["consent_date"]),
				arm=data["arm"],
				session=session,
				site_id=data.get("site_id"),
				dose_group=data.get("dose_group"),
				demographics=data.get("demographics"),
				screening_date=_parse_date(data.get("screening_date")),
			)
			session.commit()
			return jsonify({
				"subject_id": subject.id,
				"subject_number": subject.subject_number,
				"trial_id": trial_id,
				"arm": subject.arm,
				"status": subject.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:trial_id>/randomize", methods=["POST"])
	@has_access
	def randomize(self, trial_id: str):
		"""Action: Run permuted block randomization for SCREENED subjects."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			result = _svc().randomize_subjects(
				trial_id=trial_id,
				session=session,
				randomization_ratio=data.get("randomization_ratio", "1:1"),
				block_size_multiplier=int(data.get("block_size_multiplier", 2)),
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:trial_id>/report")
	@has_access
	def generate_report(self, trial_id: str):
		"""Action: Generate Clinical Study Report summary."""
		session = _get_session()
		try:
			return jsonify(_svc().generate_clinical_study_report(trial_id, session))
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:trial_id>/dashboard")
	@has_access
	def dashboard(self, trial_id: str):
		"""Action: Trial operational dashboard."""
		session = _get_session()
		try:
			return jsonify(_svc().get_trial_dashboard(trial_id, session))
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:trial_id>/submit", methods=["POST"])
	@has_access
	def submit_to_authority(self, trial_id: str):
		"""Action: Submit trial to a regulatory authority."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("authority", "submission_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			sub = _svc().submit_to_authority(
				trial_id=trial_id,
				authority=data["authority"],
				submission_type=data["submission_type"],
				session=session,
				submission_id=data.get("submission_id"),
				dossier_reference=data.get("dossier_reference"),
				notes=data.get("notes"),
			)
			session.commit()
			return jsonify({
				"submission_record_id": sub.id,
				"submission_id": sub.submission_id,
				"authority": sub.authority,
				"submission_type": sub.submission_type,
				"status": sub.status,
				"submission_date": sub.submission_date.isoformat(),
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# TrialSubjectView
# ---------------------------------------------------------------------------

class TrialSubjectView(BaseView):
	"""Trial subject CRUD with privacy-gated PII.

	Widget hints:
	  - DatePickerWidget: consent_date, screening_date
	  - Select2Widget:    arm

	Privacy: national_id (demographics.national_id) shown only to
	users with can_ls_subject_pii_read permission.

	GET  /life-sciences/subjects/         — list
	GET  /life-sciences/subjects/<id>     — detail (PII gated)
	"""

	route_base = "/life-sciences/subjects"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.life_sciences.models import TrialSubject
		session = _get_session()
		trial_id = request.args.get("trial_id")
		arm = request.args.get("arm")
		status = request.args.get("status")
		limit = min(int(request.args.get("limit", 200)), 1000)

		q = (
			sa.select(TrialSubject)
			.order_by(TrialSubject.subject_number)
			.limit(limit)
		)
		if trial_id:
			q = q.where(TrialSubject.trial_id == trial_id)
		if arm:
			q = q.where(TrialSubject.arm == arm)
		if status:
			q = q.where(TrialSubject.status == status)

		subjects = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": s.id,
				"trial_id": s.trial_id,
				"subject_number": s.subject_number,
				"arm": s.arm,
				"dose_group": s.dose_group,
				"status": s.status,
				"consent_date": s.consent_date.isoformat() if s.consent_date else None,
				"randomization_date": s.randomization_date.isoformat() if s.randomization_date else None,
				"completion_date": s.completion_date.isoformat() if s.completion_date else None,
				"_widget_hints": {
					"consent_date": "DatePickerWidget",
					"arm": "Select2Widget",
				},
			}
			for s in subjects
		])

	@expose("/<string:subject_id>")
	@has_access
	def detail(self, subject_id: str):
		from pgappforge.plugins.erp.industry.life_sciences.models import TrialSubject
		session = _get_session()
		s = session.get(TrialSubject, subject_id)
		if s is None:
			abort(404, f"TrialSubject {subject_id!r} not found")

		pii_access = _has_pii_access()
		demographics = dict(s.demographics or {})
		if not pii_access:
			# Redact national_id and other PII fields
			demographics.pop("national_id", None)
			demographics.pop("dob", None)
			demographics.pop("full_name", None)

		return jsonify({
			"id": s.id,
			"tenant_id": s.tenant_id,
			"trial_id": s.trial_id,
			"subject_number": s.subject_number,
			"site_id": s.site_id,
			"consent_date": s.consent_date.isoformat() if s.consent_date else None,
			"screening_date": s.screening_date.isoformat() if s.screening_date else None,
			"randomization_date": s.randomization_date.isoformat() if s.randomization_date else None,
			"completion_date": s.completion_date.isoformat() if s.completion_date else None,
			"withdrawal_date": s.withdrawal_date.isoformat() if s.withdrawal_date else None,
			"arm": s.arm,
			"dose_group": s.dose_group,
			"status": s.status,
			"withdrawal_reason": s.withdrawal_reason,
			"protocol_deviations": s.protocol_deviations,
			"demographics": demographics,
			"_pii_redacted": not pii_access,
			"_widget_hints": {
				"consent_date": "DatePickerWidget",
				"arm": "Select2Widget",
			},
		})


# ---------------------------------------------------------------------------
# TrialEventView
# ---------------------------------------------------------------------------

class TrialEventView(BaseView):
	"""Trial event CRUD (GxP IMMUTABLE) + SAE report action.

	Widget hints:
	  - Select2Widget:       event_type (MedDRA coded list)
	  - DatePickerWidget:    event_date
	  - StarRatingWidget:    severity.grade (1=mild → 5=fatal)

	GET  /life-sciences/events/                        — list
	GET  /life-sciences/events/<id>                    — detail
	POST /life-sciences/events/                        — record event (immutable create)
	POST /life-sciences/events/<id>/report-to-authority — SAE notification workflow
	"""

	route_base = "/life-sciences/events"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.life_sciences.models import TrialEvent
		session = _get_session()
		subject_id = request.args.get("subject_id")
		event_type = request.args.get("event_type")
		serious = request.args.get("is_serious")
		limit = min(int(request.args.get("limit", 200)), 1000)

		q = (
			sa.select(TrialEvent)
			.order_by(TrialEvent.event_date.desc())
			.limit(limit)
		)
		if subject_id:
			q = q.where(TrialEvent.subject_id == subject_id)
		if event_type:
			q = q.where(TrialEvent.event_type == event_type)
		if serious is not None:
			q = q.where(TrialEvent.is_serious == (serious.lower() == "true"))

		events = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": e.id,
				"subject_id": e.subject_id,
				"event_type": e.event_type,
				"event_date": e.event_date.isoformat() if e.event_date else None,
				"is_serious": e.is_serious,
				"severity_grade": (e.severity or {}).get("grade"),
				"reported_to_authority": e.reported_to_authority,
				"authority_reference": e.authority_reference,
				"_widget_hints": {
					"event_type": "Select2Widget",
					"event_date": "DatePickerWidget",
					"severity_grade": "StarRatingWidget",
				},
			}
			for e in events
		])

	@expose("/<string:event_id>")
	@has_access
	def detail(self, event_id: str):
		from pgappforge.plugins.erp.industry.life_sciences.models import TrialEvent
		session = _get_session()
		e = session.get(TrialEvent, event_id)
		if e is None:
			abort(404, f"TrialEvent {event_id!r} not found")
		return jsonify({
			"id": e.id,
			"tenant_id": e.tenant_id,
			"subject_id": e.subject_id,
			"event_type": e.event_type,
			"event_date": e.event_date.isoformat() if e.event_date else None,
			"description": e.description,
			"severity": e.severity,
			"reported_to_authority": e.reported_to_authority,
			"reported_at": e.reported_at.isoformat() if e.reported_at else None,
			"reported_by_id": e.reported_by_id,
			"authority_reference": e.authority_reference,
			"is_serious": e.is_serious,
			"serious_criteria": e.serious_criteria,
			"resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
			"created_at": e.created_at.isoformat() if e.created_at else None,
			"_immutable": True,
			"_widget_hints": {
				"event_type": "Select2Widget",
				"event_date": "DatePickerWidget",
				"severity_grade": "StarRatingWidget",
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Record an adverse event (immutable GxP create)."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("subject_id", "event_type", "description")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			event = _svc().record_adverse_event(
				subject_id=data["subject_id"],
				event_type=data["event_type"],
				severity=data.get("severity", {}),
				description=data["description"],
				session=session,
				event_date=(
					datetime.fromisoformat(data["event_date"])
					if data.get("event_date") else None
				),
				is_serious=bool(data.get("is_serious", False)),
				serious_criteria=data.get("serious_criteria"),
				reported_by_id=data.get("reported_by_id"),
				authority_reference=data.get("authority_reference"),
			)
			session.commit()
			return jsonify({
				"event_id": event.id,
				"subject_id": event.subject_id,
				"event_type": event.event_type,
				"is_serious": event.is_serious,
				"reported_to_authority": event.reported_to_authority,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:event_id>/report-to-authority", methods=["POST"])
	@has_access
	def report_to_authority(self, event_id: str):
		"""Action: SAE notification workflow — mark as reported and capture reference."""
		from pgappforge.plugins.erp.industry.life_sciences.models import TrialEvent, TrialSubject
		from pgappforge.plugins.erp.industry.life_sciences.events import SAEReportedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		e = session.get(TrialEvent, event_id)
		if e is None:
			abort(404)
		if not e.is_serious:
			return jsonify({"error": "Only SAE (serious) events can be reported to authority via this endpoint"}), 422

		data = request.get_json(force=True) or {}
		authority_reference = data.get("authority_reference", "")
		reported_by_id = data.get("reported_by_id", "")

		# GxP: we cannot update the TrialEvent row.
		# We emit the notification event and return — the event is already
		# marked reported_to_authority=True at creation for SAEs.
		# If it wasn't (edge case), we insert a CORRECTION event.
		if not e.reported_to_authority:
			subject = session.get(TrialSubject, e.subject_id)
			correction = TrialEvent(
				tenant_id=e.tenant_id,
				subject_id=e.subject_id,
				event_type="CORRECTION",
				event_date=datetime.now(timezone.utc),
				description=(
					f"SAE reporting correction: marking event {event_id} as reported. "
					f"Authority reference: {authority_reference}"
				),
				severity={"corrects_event_id": event_id},
				reported_to_authority=True,
				reported_at=datetime.now(timezone.utc),
				reported_by_id=reported_by_id or None,
				authority_reference=authority_reference,
				is_serious=True,
				serious_criteria=e.serious_criteria or [],
			)
			session.add(correction)

		emit_event(
			SAEReportedEvent(
				aggregate_id=event_id,
				aggregate_type="TrialEvent",
				tenant_id=e.tenant_id,
				event_id=event_id,
				subject_id=e.subject_id,
				trial_id="",  # resolved by consumer from subject
				event_date=e.event_date.isoformat() if e.event_date else "",
				authority_reference=authority_reference,
				reported_by_id=reported_by_id,
				serious_criteria=e.serious_criteria or [],
			),
			session,
		)
		session.commit()

		return jsonify({
			"event_id": event_id,
			"reported_to_authority": True,
			"authority_reference": authority_reference,
			"reported_by_id": reported_by_id,
		})


# ---------------------------------------------------------------------------
# RegulatorySubmissionView
# ---------------------------------------------------------------------------

class RegulatorySubmissionView(BaseView):
	"""Regulatory submission CRUD + status tracking + document upload.

	Widget hints:
	  - Select2Widget:          authority (FDA/EMA/MHRA/PMDA/TGA/HEALTH_CANADA)
	  - DocumentViewerWidget:   dossier_reference in detail

	GET  /life-sciences/submissions/                      — list
	GET  /life-sciences/submissions/<id>                  — detail
	POST /life-sciences/submissions/                      — create submission
	POST /life-sciences/submissions/<id>/status          — update status
	POST /life-sciences/submissions/<id>/upload-response — attach authority response (stub)
	GET  /life-sciences/submissions/<id>/track           — track current status
	"""

	route_base = "/life-sciences/submissions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.life_sciences.models import RegulatorySubmission
		session = _get_session()
		trial_id = request.args.get("trial_id")
		authority = request.args.get("authority")
		status = request.args.get("status")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = (
			sa.select(RegulatorySubmission)
			.order_by(RegulatorySubmission.submission_date.desc())
			.limit(limit)
		)
		if trial_id:
			q = q.where(RegulatorySubmission.trial_id == trial_id)
		if authority:
			q = q.where(RegulatorySubmission.authority == authority)
		if status:
			q = q.where(RegulatorySubmission.status == status)

		subs = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": s.id,
				"submission_id": s.submission_id,
				"trial_id": s.trial_id,
				"authority": s.authority,
				"submission_type": s.submission_type,
				"submission_date": s.submission_date.isoformat() if s.submission_date else None,
				"target_action_date": s.target_action_date.isoformat() if s.target_action_date else None,
				"approval_date": s.approval_date.isoformat() if s.approval_date else None,
				"status": s.status,
				"approval_reference": s.approval_reference,
				"_widget_hints": {
					"authority": "Select2Widget",
					"dossier_reference": "DocumentViewerWidget",
				},
			}
			for s in subs
		])

	@expose("/<string:sub_id>")
	@has_access
	def detail(self, sub_id: str):
		from pgappforge.plugins.erp.industry.life_sciences.models import RegulatorySubmission
		session = _get_session()
		s = session.get(RegulatorySubmission, sub_id)
		if s is None:
			abort(404, f"RegulatorySubmission {sub_id!r} not found")
		return jsonify({
			"id": s.id,
			"tenant_id": s.tenant_id,
			"submission_id": s.submission_id,
			"trial_id": s.trial_id,
			"authority": s.authority,
			"submission_type": s.submission_type,
			"submission_date": s.submission_date.isoformat() if s.submission_date else None,
			"target_action_date": s.target_action_date.isoformat() if s.target_action_date else None,
			"approval_date": s.approval_date.isoformat() if s.approval_date else None,
			"status": s.status,
			"approval_reference": s.approval_reference,
			"conditions": s.conditions,
			"labeling_approved": s.labeling_approved,
			"submission_manager_id": s.submission_manager_id,
			"dossier_reference": s.dossier_reference,
			"notes": s.notes,
			"_widget_hints": {
				"authority": "Select2Widget",
				"dossier_reference": "DocumentViewerWidget",
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Create a regulatory submission."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("authority", "submission_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			sub = _svc().submit_to_authority(
				trial_id=data.get("trial_id"),
				authority=data["authority"],
				submission_type=data["submission_type"],
				session=session,
				submission_id=data.get("submission_id"),
				tenant_id=data.get("tenant_id"),
				dossier_reference=data.get("dossier_reference"),
				notes=data.get("notes"),
			)
			session.commit()
			return jsonify({
				"submission_record_id": sub.id,
				"submission_id": sub.submission_id,
				"authority": sub.authority,
				"status": sub.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:sub_id>/status", methods=["POST"])
	@has_access
	def update_status(self, sub_id: str):
		"""Track Status action — update submission status from authority response."""
		from pgappforge.plugins.erp.industry.life_sciences.models import RegulatorySubmission
		from pgappforge.plugins.erp.industry.life_sciences.events import (
			RegulatorySubmissionApprovedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		s = session.get(RegulatorySubmission, sub_id)
		if s is None:
			abort(404)
		if s.status == "APPROVED":
			return jsonify({"error": "Submission is APPROVED and immutable. Create a variation for changes."}), 422

		data = request.get_json(force=True) or {}
		new_status = data.get("status")
		valid_statuses = {"SUBMITTED", "ACCEPTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "REFUSED", "WITHDRAWN"}
		if new_status not in valid_statuses:
			return jsonify({"error": f"status must be one of {valid_statuses}"}), 400

		old_status = s.status
		s.status = new_status

		if new_status == "APPROVED":
			s.approval_date = _parse_date(data.get("approval_date")) or date.today()
			s.approval_reference = data.get("approval_reference", s.approval_reference)
			emit_event(
				RegulatorySubmissionApprovedEvent(
					aggregate_id=sub_id,
					aggregate_type="RegulatorySubmission",
					tenant_id=s.tenant_id,
					submission_record_id=sub_id,
					submission_id=s.submission_id,
					trial_id=str(s.trial_id) if s.trial_id else "",
					authority=s.authority,
					submission_type=s.submission_type,
					approval_date=s.approval_date.isoformat(),
					approval_reference=s.approval_reference or "",
				),
				session,
			)

		if data.get("target_action_date"):
			s.target_action_date = _parse_date(data["target_action_date"])
		if data.get("notes"):
			s.notes = data["notes"]

		session.commit()
		return jsonify({
			"submission_id": s.submission_id,
			"old_status": old_status,
			"new_status": new_status,
			"approval_reference": s.approval_reference,
		})

	@expose("/<string:sub_id>/upload-response", methods=["POST"])
	@has_access
	def upload_response(self, sub_id: str):
		"""Upload Response action — attach authority response document (stub).

		Full implementation requires document management integration.
		"""
		from pgappforge.plugins.erp.industry.life_sciences.models import RegulatorySubmission
		session = _get_session()
		s = session.get(RegulatorySubmission, sub_id)
		if s is None:
			abort(404)
		data = request.get_json(force=True) or {}
		document_ref = data.get("document_reference", "")
		if document_ref:
			# Store in labeling_approved field as a document reference dict
			s.labeling_approved = {
				**(s.labeling_approved or {}),
				"authority_response_ref": document_ref,
				"uploaded_at": datetime.now(timezone.utc).isoformat(),
			}
			session.commit()
		return jsonify({
			"submission_id": s.submission_id,
			"document_reference": document_ref,
			"status": "stored" if document_ref else "no_document_provided",
			"note": "Full document management requires DMS integration.",
		})

	@expose("/<string:sub_id>/track")
	@has_access
	def track_status(self, sub_id: str):
		"""Track Status action — return current submission status and timeline."""
		from pgappforge.plugins.erp.industry.life_sciences.models import RegulatorySubmission
		session = _get_session()
		s = session.get(RegulatorySubmission, sub_id)
		if s is None:
			abort(404)

		today = date.today()
		days_since_submission = (today - s.submission_date).days if s.submission_date else None
		days_to_action = (
			(s.target_action_date - today).days
			if s.target_action_date and s.status not in ("APPROVED", "REFUSED", "WITHDRAWN")
			else None
		)

		return jsonify({
			"submission_id": s.submission_id,
			"authority": s.authority,
			"submission_type": s.submission_type,
			"status": s.status,
			"submission_date": s.submission_date.isoformat() if s.submission_date else None,
			"target_action_date": s.target_action_date.isoformat() if s.target_action_date else None,
			"approval_date": s.approval_date.isoformat() if s.approval_date else None,
			"approval_reference": s.approval_reference,
			"days_since_submission": days_since_submission,
			"days_to_action_date": days_to_action,
			"overdue": days_to_action is not None and days_to_action < 0,
			"conditions": s.conditions,
			"_widget_hints": {"dossier_reference": "DocumentViewerWidget"},
		})


# ---------------------------------------------------------------------------
# AdverseEventDashboardView
# ---------------------------------------------------------------------------

class AdverseEventDashboardView(BaseView):
	"""Pharmacovigilance / safety dashboard at /life-sciences/safety/.

	Widget hints:
	  - AdvancedChartsWidget: AE by type/severity, signal detection metrics

	GET /life-sciences/safety/                           — dashboard index
	GET /life-sciences/safety/ae-summary                 — AE/SAE by type and grade
	GET /life-sciences/safety/signal-detection           — PRR / ROR signal metrics
	GET /life-sciences/safety/unreported-saes            — SAEs pending authority notification
	"""

	route_base = "/life-sciences/safety"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"title": "Pharmacovigilance Safety Dashboard",
			"description": "AE/SAE reporting, signal detection (PRR/ROR), and regulatory compliance.",
			"endpoints": {
				"ae_summary": "/life-sciences/safety/ae-summary?tenant_id=<id>",
				"signal_detection": "/life-sciences/safety/signal-detection?drug_name=<n>&ae_term=<t>",
				"unreported_saes": "/life-sciences/safety/unreported-saes?tenant_id=<id>",
			},
			"_widget_hints": {
				"charts": "AdvancedChartsWidget",
				"type": "bar+severity",
			},
		})

	@expose("/ae-summary")
	@has_access
	def ae_summary(self):
		"""AE/SAE summary by event_type and severity grade across all trials."""
		from pgappforge.plugins.erp.industry.life_sciences.models import (
			TrialEvent, TrialSubject, ClinicalTrial,
		)
		from sqlalchemy import func as f

		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		trial_id = request.args.get("trial_id")

		q = (
			sa.select(
				TrialEvent.event_type,
				TrialEvent.is_serious,
				f.count(TrialEvent.id).label("count"),
			)
			.join(TrialSubject, TrialSubject.id == TrialEvent.subject_id)
			.where(TrialEvent.event_type.in_(["AE", "SAE"]))
			.group_by(TrialEvent.event_type, TrialEvent.is_serious)
			.order_by(TrialEvent.event_type)
		)
		if tenant_id:
			q = q.where(TrialSubject.tenant_id == tenant_id)
		if trial_id:
			q = q.where(TrialSubject.trial_id == trial_id)

		rows = session.execute(q).all()

		# SAE serious_criteria breakdown
		sae_criteria_q = (
			sa.select(TrialEvent.serious_criteria)
			.join(TrialSubject, TrialSubject.id == TrialEvent.subject_id)
			.where(TrialEvent.is_serious.is_(True))
		)
		if tenant_id:
			sae_criteria_q = sae_criteria_q.where(TrialSubject.tenant_id == tenant_id)
		criteria_rows = session.execute(sae_criteria_q).scalars().all()

		criteria_counts: dict[str, int] = {}
		for criteria_list in criteria_rows:
			for c in (criteria_list or []):
				criteria_counts[c] = criteria_counts.get(c, 0) + 1

		return jsonify({
			"tenant_id": tenant_id,
			"trial_id": trial_id,
			"ae_by_type": [
				{
					"event_type": r.event_type,
					"is_serious": r.is_serious,
					"count": r.count,
				}
				for r in rows
			],
			"sae_serious_criteria_breakdown": criteria_counts,
			"_widget_hints": {
				"charts": "AdvancedChartsWidget",
				"type": "bar",
				"dimensions": ["event_type", "is_serious"],
			},
		})

	@expose("/signal-detection")
	@has_access
	def signal_detection(self):
		"""Pharmacovigilance signal detection using PRR / ROR."""
		session = _get_session()
		drug_name = request.args.get("drug_name")
		ae_term = request.args.get("ae_term")
		tenant_id = request.args.get("tenant_id")

		if not drug_name or not ae_term:
			return jsonify({"error": "drug_name and ae_term query params required"}), 400

		try:
			result = _svc().calculate_safety_signal(
				drug_name=drug_name,
				ae_term=ae_term,
				session=session,
				tenant_id=tenant_id,
			)
			result["_widget_hints"] = {
				"charts": "AdvancedChartsWidget",
				"type": "signal_gauge",
			}
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/unreported-saes")
	@has_access
	def unreported_saes(self):
		"""List SAEs that have not yet been reported to a regulatory authority."""
		from pgappforge.plugins.erp.industry.life_sciences.models import (
			TrialEvent, TrialSubject,
		)

		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id query param required"}), 400

		rows = session.execute(
			sa.select(
				TrialEvent.id,
				TrialEvent.subject_id,
				TrialEvent.event_date,
				TrialEvent.description,
				TrialEvent.serious_criteria,
				TrialEvent.severity,
				TrialSubject.subject_number,
				TrialSubject.trial_id,
			)
			.join(TrialSubject, TrialSubject.id == TrialEvent.subject_id)
			.where(
				TrialSubject.tenant_id == tenant_id,
				TrialEvent.is_serious.is_(True),
				TrialEvent.reported_to_authority.is_(False),
			)
			.order_by(TrialEvent.event_date)
		).all()

		today = date.today()
		return jsonify({
			"tenant_id": tenant_id,
			"unreported_sae_count": len(rows),
			"unreported_saes": [
				{
					"event_id": r.id,
					"subject_id": r.subject_id,
					"subject_number": r.subject_number,
					"trial_id": str(r.trial_id),
					"event_date": r.event_date.isoformat() if r.event_date else None,
					"description": r.description,
					"serious_criteria": r.serious_criteria,
					"severity_grade": (r.severity or {}).get("grade"),
					"days_since_event": (
						(today - r.event_date.date()).days
						if r.event_date else None
					),
				}
				for r in rows
			],
			"_widget_hints": {
				"charts": "AdvancedChartsWidget",
				"flag": "safety_alert",
			},
		})


__all__ = [
	"ClinicalTrialView",
	"TrialSubjectView",
	"TrialEventView",
	"RegulatorySubmissionView",
	"AdverseEventDashboardView",
]
