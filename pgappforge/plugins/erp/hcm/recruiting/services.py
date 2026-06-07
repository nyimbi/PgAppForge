"""
pgappforge/plugins/erp/hcm/recruiting/services.py

RecruitingService — stateless ATS / recruiting domain service.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Public methods:
  post_requisition(...)       -> JobRequisition
  receive_application(...)    -> JobApplication
  advance_status(...)         -> JobApplication
  schedule_interview(...)     -> InterviewSchedule
  submit_feedback(...)        -> InterviewSchedule
  create_offer(...)           -> OfferLetter
  accept_offer(...)           -> dict
  get_pipeline(...)           -> dict
  get_recruiting_dashboard(...)-> dict
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

# Valid status transitions for JobApplication
_APP_TRANSITIONS: dict[str, list[str]] = {
	"APPLIED":      ["SCREENING", "REJECTED", "WITHDRAWN"],
	"SCREENING":    ["PHONE_SCREEN", "REJECTED", "WITHDRAWN"],
	"PHONE_SCREEN": ["INTERVIEW", "REJECTED", "WITHDRAWN"],
	"INTERVIEW":    ["ASSESSMENT", "OFFER", "REJECTED", "WITHDRAWN"],
	"ASSESSMENT":   ["OFFER", "REJECTED", "WITHDRAWN"],
	"OFFER":        ["HIRED", "REJECTED", "WITHDRAWN"],
	"HIRED":        [],
	"REJECTED":     [],
	"WITHDRAWN":    [],
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RecruitingServiceError(Exception):
	"""Base domain error for recruiting operations."""


class RequisitionNotFoundError(RecruitingServiceError):
	pass


class ApplicationNotFoundError(RecruitingServiceError):
	pass


class InterviewNotFoundError(RecruitingServiceError):
	pass


class OfferNotFoundError(RecruitingServiceError):
	pass


class RecruitingStateError(RecruitingServiceError):
	"""Invalid state transition."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception as exc:
		log.debug("RecruitingService._emit: could not emit %s: %s", type(event).__name__, exc)


# ---------------------------------------------------------------------------
# BPM registration
# ---------------------------------------------------------------------------

def _register_bpm() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry

		@BPMActionRegistry.register(
			"hcm.recruiting.advance_application",
			"Advance recruiting application status",
		)
		def _bpm_advance(
			record_ctx: dict,
			session: Any,
			application_id: str = "",
			new_status: str = "",
			rejection_reason: str | None = None,
			**kw: Any,
		) -> dict:
			try:
				svc = RecruitingService()
				app = svc.advance_status(
					application_id, new_status, session,
					rejection_reason=rejection_reason,
				)
				return {"status": "ok", "application_id": app.id, "app_status": app.status}
			except Exception as exc:
				log.warning("bpm recruiting.advance_application failed: %s", exc)
				return {"status": "error", "message": str(exc)}

		@BPMActionRegistry.register(
			"hcm.recruiting.create_offer",
			"Create job offer letter",
		)
		def _bpm_create_offer(
			record_ctx: dict,
			session: Any,
			application_id: str = "",
			salary_cents: int = 0,
			start_date: str | None = None,
			expiry_date: str | None = None,
			bonus_cents: int = 0,
			currency_code: str = "KES",
			**kw: Any,
		) -> dict:
			from datetime import date
			tenant_id = record_ctx.get("tenant_id", "")
			try:
				sd = date.fromisoformat(start_date) if start_date else None
				ed = date.fromisoformat(expiry_date) if expiry_date else None
				svc = RecruitingService()
				offer = svc.create_offer(
					application_id, salary_cents, sd, ed, tenant_id, session,
					bonus_cents=bonus_cents,
					currency_code=currency_code,
				)
				return {"status": "ok", "offer_id": offer.id, "offer_status": offer.status}
			except Exception as exc:
				log.warning("bpm recruiting.create_offer failed: %s", exc)
				return {"status": "error", "message": str(exc)}

	except ImportError:
		log.debug("RecruitingService: BPM plugin not available, skipping registration")


# ---------------------------------------------------------------------------
# RecruitingService
# ---------------------------------------------------------------------------

class RecruitingService:
	"""Stateless ATS domain service.

	Instantiate once per application (no instance state).
	All public methods accept a SQLAlchemy Session as an explicit argument.
	"""

	# ------------------------------------------------------------------
	# post_requisition
	# ------------------------------------------------------------------

	def post_requisition(
		self,
		title: str,
		tenant_id: str,
		session: Any,
		*,
		department_id: str | None = None,
		entity_id: str | None = None,
		headcount: int = 1,
		employment_type: str = "FULL_TIME",
		hiring_manager_id: str | None = None,
		salary_min_cents: int | None = None,
		salary_max_cents: int | None = None,
		job_description: str | None = None,
		grade_level: str | None = None,
	) -> Any:
		"""Open a new job requisition and emit RequisitionPostedEvent.

		Args:
			title: Job title.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.

		Returns:
			Persisted JobRequisition with status=OPEN.
		"""
		from pgappforge.plugins.erp.hcm.recruiting.models import JobRequisition
		from pgappforge.plugins.erp.hcm.recruiting.events import RequisitionPostedEvent

		now = _now()
		req = JobRequisition(
			tenant_id=tenant_id,
			title=title,
			department_id=department_id,
			entity_id=entity_id,
			headcount=headcount,
			employment_type=employment_type,
			hiring_manager_id=hiring_manager_id,
			salary_min_cents=salary_min_cents,
			salary_max_cents=salary_max_cents,
			job_description=job_description,
			grade_level=grade_level,
			status="OPEN",
			posted_at=now,
		)
		session.add(req)
		session.flush()

		_emit(
			RequisitionPostedEvent(
				aggregate_id=req.id,
				aggregate_type="JobRequisition",
				tenant_id=tenant_id,
				req_id=req.id,
				title=title,
				entity_id=entity_id or "",
			),
			session,
		)
		log.info(
			"RecruitingService.post_requisition: req=%s title=%r tenant=%s",
			req.id, title, tenant_id,
		)
		return req

	# ------------------------------------------------------------------
	# receive_application
	# ------------------------------------------------------------------

	def receive_application(
		self,
		requisition_id: str,
		candidate_name: str,
		candidate_email: str,
		session: Any,
		*,
		source: str = "DIRECT",
		resume_url: str | None = None,
		referrer_id: str | None = None,
		candidate_phone: str | None = None,
		cover_letter: str | None = None,
	) -> Any:
		"""Submit a candidate application against an open requisition.

		Raises:
			RequisitionNotFoundError: Requisition not found.
			RecruitingStateError: Requisition not OPEN.

		Returns:
			Persisted JobApplication with status=APPLIED.
		"""
		from pgappforge.plugins.erp.hcm.recruiting.models import JobRequisition, JobApplication
		from pgappforge.plugins.erp.hcm.recruiting.events import ApplicationReceivedEvent

		req: Any = session.get(JobRequisition, requisition_id)
		if req is None:
			raise RequisitionNotFoundError(f"JobRequisition {requisition_id!r} not found")
		if req.status != "OPEN":
			raise RecruitingStateError(
				f"JobRequisition {requisition_id!r} is {req.status!r}; only OPEN requisitions accept applications"
			)

		app = JobApplication(
			tenant_id=req.tenant_id,
			requisition_id=requisition_id,
			candidate_name=candidate_name,
			candidate_email=candidate_email,
			candidate_phone=candidate_phone,
			source=source,
			resume_url=resume_url,
			cover_letter=cover_letter,
			referrer_employee_id=referrer_id,
			status="APPLIED",
		)
		session.add(app)
		session.flush()

		_emit(
			ApplicationReceivedEvent(
				aggregate_id=app.id,
				aggregate_type="JobApplication",
				tenant_id=req.tenant_id,
				app_id=app.id,
				req_id=requisition_id,
				candidate_name=candidate_name,
				source=source,
			),
			session,
		)
		log.info(
			"RecruitingService.receive_application: app=%s candidate=%r req=%s",
			app.id, candidate_name, requisition_id,
		)
		return app

	# ------------------------------------------------------------------
	# advance_status
	# ------------------------------------------------------------------

	def advance_status(
		self,
		application_id: str,
		new_status: str,
		session: Any,
		*,
		rejection_reason: str | None = None,
	) -> Any:
		"""Advance an application through the hiring pipeline.

		Raises:
			ApplicationNotFoundError: Application not found.
			RecruitingStateError: Invalid transition.

		Returns:
			Updated JobApplication.
		"""
		from pgappforge.plugins.erp.hcm.recruiting.models import JobApplication

		app: Any = session.get(JobApplication, application_id)
		if app is None:
			raise ApplicationNotFoundError(f"JobApplication {application_id!r} not found")

		allowed = _APP_TRANSITIONS.get(app.status, [])
		if new_status not in allowed:
			raise RecruitingStateError(
				f"Cannot advance application from {app.status!r} to {new_status!r}; "
				f"allowed: {allowed}"
			)

		app.status = new_status
		app.updated_at = _now()
		if rejection_reason and new_status == "REJECTED":
			app.rejection_reason = rejection_reason

		session.flush()
		log.info(
			"RecruitingService.advance_status: app=%s %r -> %r",
			application_id, app.status, new_status,
		)
		return app

	# ------------------------------------------------------------------
	# schedule_interview
	# ------------------------------------------------------------------

	def schedule_interview(
		self,
		application_id: str,
		interviewer_id: str,
		scheduled_at: datetime,
		session: Any,
		*,
		duration_minutes: int = 60,
		format: str = "VIDEO",
		location: str | None = None,
	) -> Any:
		"""Book an interview slot and emit InterviewScheduledEvent.

		Args:
			application_id: UUID of the JobApplication.
			interviewer_id: Employee / user ID of the interviewer.
			scheduled_at: Timezone-aware datetime for the interview.
			session: SQLAlchemy session.

		Returns:
			Persisted InterviewSchedule.
		"""
		from pgappforge.plugins.erp.hcm.recruiting.models import JobApplication, InterviewSchedule
		from pgappforge.plugins.erp.hcm.recruiting.events import InterviewScheduledEvent

		app: Any = session.get(JobApplication, application_id)
		if app is None:
			raise ApplicationNotFoundError(f"JobApplication {application_id!r} not found")

		schedule = InterviewSchedule(
			tenant_id=app.tenant_id,
			application_id=application_id,
			interviewer_id=interviewer_id,
			scheduled_at=scheduled_at,
			duration_minutes=duration_minutes,
			format=format,
			location=location,
		)
		session.add(schedule)
		session.flush()

		_emit(
			InterviewScheduledEvent(
				aggregate_id=schedule.id,
				aggregate_type="InterviewSchedule",
				tenant_id=app.tenant_id,
				schedule_id=schedule.id,
				app_id=application_id,
				interviewer_id=interviewer_id,
				scheduled_at=scheduled_at.isoformat(),
			),
			session,
		)
		log.info(
			"RecruitingService.schedule_interview: schedule=%s app=%s interviewer=%s",
			schedule.id, application_id, interviewer_id,
		)
		return schedule

	# ------------------------------------------------------------------
	# submit_feedback
	# ------------------------------------------------------------------

	def submit_feedback(
		self,
		schedule_id: str,
		feedback: str,
		rating: int,
		recommendation: str,
		session: Any,
	) -> Any:
		"""Record interviewer feedback and mark the interview complete.

		Args:
			schedule_id: UUID of the InterviewSchedule.
			feedback: Free-text feedback notes.
			rating: Integer 1–5.
			recommendation: STRONG_YES | YES | MAYBE | NO | STRONG_NO.
			session: SQLAlchemy session.

		Returns:
			Updated InterviewSchedule.
		"""
		from pgappforge.plugins.erp.hcm.recruiting.models import InterviewSchedule

		schedule: Any = session.get(InterviewSchedule, schedule_id)
		if schedule is None:
			raise InterviewNotFoundError(f"InterviewSchedule {schedule_id!r} not found")

		assert 1 <= rating <= 5, f"rating must be 1–5, got {rating}"

		now = _now()
		schedule.feedback = feedback
		schedule.rating = rating
		schedule.recommendation = recommendation
		schedule.completed_at = now
		schedule.updated_at = now
		session.flush()

		log.info(
			"RecruitingService.submit_feedback: schedule=%s rating=%d recommendation=%r",
			schedule_id, rating, recommendation,
		)
		return schedule

	# ------------------------------------------------------------------
	# create_offer
	# ------------------------------------------------------------------

	def create_offer(
		self,
		application_id: str,
		salary_cents: int,
		start_date: Any,
		expiry_date: Any,
		tenant_id: str,
		session: Any,
		*,
		bonus_cents: int = 0,
		currency_code: str = "KES",
	) -> Any:
		"""Create an offer letter and emit OfferExtendedEvent.

		Args:
			application_id: UUID of the JobApplication.
			salary_cents: Offered base salary in cents.
			start_date: Proposed start date (date or None).
			expiry_date: Offer expiry date (date or None).
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.

		Returns:
			Persisted OfferLetter with status=DRAFT.
		"""
		from pgappforge.plugins.erp.hcm.recruiting.models import JobApplication, OfferLetter
		from pgappforge.plugins.erp.hcm.recruiting.events import OfferExtendedEvent

		app: Any = session.get(JobApplication, application_id)
		if app is None:
			raise ApplicationNotFoundError(f"JobApplication {application_id!r} not found")

		offer = OfferLetter(
			tenant_id=tenant_id,
			application_id=application_id,
			offered_salary_cents=salary_cents,
			bonus_cents=bonus_cents,
			start_date=start_date,
			expiry_date=expiry_date,
			currency_code=currency_code,
			status="DRAFT",
		)
		session.add(offer)
		session.flush()

		# Advance application to OFFER stage
		if app.status not in ("OFFER", "HIRED"):
			app.status = "OFFER"
			app.updated_at = _now()

		_emit(
			OfferExtendedEvent(
				aggregate_id=offer.id,
				aggregate_type="OfferLetter",
				tenant_id=tenant_id,
				offer_id=offer.id,
				app_id=application_id,
				salary_cents=salary_cents,
			),
			session,
		)
		log.info(
			"RecruitingService.create_offer: offer=%s app=%s salary_cents=%d",
			offer.id, application_id, salary_cents,
		)
		return offer

	# ------------------------------------------------------------------
	# accept_offer
	# ------------------------------------------------------------------

	def accept_offer(
		self,
		offer_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Accept an offer letter, hire the candidate, and trigger onboarding.

		Side effects:
		  - offer.status = ACCEPTED
		  - application.status = HIRED
		  - Emits OfferAcceptedEvent
		  - Attempts to start onboarding journey via JourneyService
		  - Emits RequisitionFilledEvent if headcount fully filled

		Returns:
			{"hired": True, "onboarding_started": bool, "offer_id": str, "application_id": str}
		"""
		from pgappforge.plugins.erp.hcm.recruiting.models import JobApplication, OfferLetter
		from pgappforge.plugins.erp.hcm.recruiting.events import OfferAcceptedEvent, RequisitionFilledEvent

		offer: Any = session.get(OfferLetter, offer_id)
		if offer is None:
			raise OfferNotFoundError(f"OfferLetter {offer_id!r} not found")
		if offer.status not in ("SENT", "DRAFT", "PENDING_APPROVAL"):
			raise RecruitingStateError(
				f"OfferLetter {offer_id!r} is {offer.status!r}; cannot accept"
			)

		app: Any = session.get(JobApplication, offer.application_id)
		if app is None:
			raise ApplicationNotFoundError(f"JobApplication {offer.application_id!r} not found")

		now = _now()
		offer.status = "ACCEPTED"
		offer.accepted_at = now
		offer.updated_at = now
		app.status = "HIRED"
		app.updated_at = now
		session.flush()

		# Use application id as employee_id placeholder (real HRIS may differ)
		employee_id = app.id

		_emit(
			OfferAcceptedEvent(
				aggregate_id=offer.id,
				aggregate_type="OfferLetter",
				tenant_id=offer.tenant_id,
				offer_id=offer.id,
				app_id=app.id,
				employee_id=employee_id,
			),
			session,
		)

		# Trigger onboarding journey (best-effort)
		onboarding_started = False
		try:
			from pgappforge.plugins.erp.hcm.journeys.services import JourneyService
			from datetime import date
			JourneyService().start_journey(
				app.candidate_email,
				"ONBOARDING",
				date.today(),
				offer.tenant_id,
				session,
			)
			onboarding_started = True
		except Exception as exc:
			log.debug("RecruitingService.accept_offer: onboarding not started: %s", exc)

		# Check whether all requisition headcount is filled
		req: Any = app.requisition
		if req is None:
			req = session.get(
				__import__(
					"pgappforge.plugins.erp.hcm.recruiting.models",
					fromlist=["JobRequisition"],
				).JobRequisition,
				app.requisition_id,
			)

		req_filled = False
		if req is not None:
			hired_count: int = session.execute(
				sa.select(sa.func.count()).select_from(
					__import__(
						"pgappforge.plugins.erp.hcm.recruiting.models",
						fromlist=["JobApplication"],
					).JobApplication
				).where(
					sa.and_(
						__import__(
							"pgappforge.plugins.erp.hcm.recruiting.models",
							fromlist=["JobApplication"],
						).JobApplication.requisition_id == req.id,
						__import__(
							"pgappforge.plugins.erp.hcm.recruiting.models",
							fromlist=["JobApplication"],
						).JobApplication.status == "HIRED",
					)
				)
			).scalar_one()

			if hired_count >= req.headcount:
				from datetime import timedelta
				days_to_fill = (
					(now.date() - req.posted_at.date()).days
					if req.posted_at else 0
				)
				req.status = "FILLED"
				req.closed_at = now
				req.updated_at = now
				session.flush()
				req_filled = True

				_emit(
					RequisitionFilledEvent(
						aggregate_id=req.id,
						aggregate_type="JobRequisition",
						tenant_id=req.tenant_id,
						req_id=req.id,
						days_to_fill=days_to_fill,
						hires_count=hired_count,
					),
					session,
				)

		log.info(
			"RecruitingService.accept_offer: offer=%s app=%s hired=True onboarding=%s req_filled=%s",
			offer_id, app.id, onboarding_started, req_filled,
		)
		return {
			"hired": True,
			"onboarding_started": onboarding_started,
			"offer_id": offer.id,
			"application_id": app.id,
		}

	# ------------------------------------------------------------------
	# get_pipeline
	# ------------------------------------------------------------------

	def get_pipeline(
		self,
		requisition_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return pipeline analytics for a requisition.

		Returns:
		  {
		    requisition_id, title, status, headcount,
		    counts_by_status: {status: int},
		    conversion_rates: {stage -> next_stage: pct},
		    time_to_fill_days: int | None,
		  }
		"""
		from pgappforge.plugins.erp.hcm.recruiting.models import JobRequisition, JobApplication

		req: Any = session.get(JobRequisition, requisition_id)
		if req is None:
			raise RequisitionNotFoundError(f"JobRequisition {requisition_id!r} not found")

		rows = session.execute(
			sa.select(JobApplication.status, sa.func.count().label("cnt"))
			.where(JobApplication.requisition_id == requisition_id)
			.group_by(JobApplication.status)
		).all()

		counts: dict[str, int] = {row.status: row.cnt for row in rows}
		total = sum(counts.values())

		# Funnel conversion: applied → screening → interview → offer → hired
		funnel = ["APPLIED", "SCREENING", "INTERVIEW", "OFFER", "HIRED"]
		conversion: dict[str, float] = {}
		for i in range(len(funnel) - 1):
			top = counts.get(funnel[i], 0)
			bottom = counts.get(funnel[i + 1], 0)
			conversion[f"{funnel[i]}->{funnel[i+1]}"] = (
				round(bottom / top * 100, 1) if top > 0 else 0.0
			)

		time_to_fill: int | None = None
		if req.posted_at and req.closed_at:
			time_to_fill = (req.closed_at.date() - req.posted_at.date()).days

		return {
			"requisition_id": requisition_id,
			"title": req.title,
			"status": req.status,
			"headcount": req.headcount,
			"total_applications": total,
			"counts_by_status": counts,
			"conversion_rates": conversion,
			"time_to_fill_days": time_to_fill,
		}

	# ------------------------------------------------------------------
	# get_recruiting_dashboard
	# ------------------------------------------------------------------

	def get_recruiting_dashboard(
		self,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return tenant-level recruiting KPIs.

		Returns:
		  {
		    open_reqs: int,
		    applications_this_month: int,
		    offers_extended: int,
		    avg_time_to_fill_days: float | None,
		    source_breakdown: {source: int},
		  }
		"""
		from pgappforge.plugins.erp.hcm.recruiting.models import JobRequisition, JobApplication, OfferLetter
		from datetime import date

		# Open requisitions
		open_reqs: int = session.execute(
			sa.select(sa.func.count())
			.select_from(JobRequisition)
			.where(sa.and_(
				JobRequisition.tenant_id == tenant_id,
				JobRequisition.status == "OPEN",
			))
		).scalar_one()

		# Applications this calendar month
		today = date.today()
		month_start = today.replace(day=1)
		apps_this_month: int = session.execute(
			sa.select(sa.func.count())
			.select_from(JobApplication)
			.where(sa.and_(
				JobApplication.tenant_id == tenant_id,
				JobApplication.applied_at >= month_start,
			))
		).scalar_one()

		# Offers extended (non-DRAFT)
		offers_extended: int = session.execute(
			sa.select(sa.func.count())
			.select_from(OfferLetter)
			.where(sa.and_(
				OfferLetter.tenant_id == tenant_id,
				OfferLetter.status.notin_(["DRAFT"]),
			))
		).scalar_one()

		# Avg days to fill for FILLED reqs
		filled_rows = session.execute(
			sa.select(JobRequisition.posted_at, JobRequisition.closed_at)
			.where(sa.and_(
				JobRequisition.tenant_id == tenant_id,
				JobRequisition.status == "FILLED",
				JobRequisition.posted_at.isnot(None),
				JobRequisition.closed_at.isnot(None),
			))
		).all()

		days_list = [
			(row.closed_at.date() - row.posted_at.date()).days
			for row in filled_rows
		]
		avg_ttf: float | None = (
			round(statistics.mean(days_list), 1) if days_list else None
		)

		# Source breakdown
		source_rows = session.execute(
			sa.select(JobApplication.source, sa.func.count().label("cnt"))
			.where(JobApplication.tenant_id == tenant_id)
			.group_by(JobApplication.source)
		).all()
		source_breakdown = {row.source: row.cnt for row in source_rows}

		return {
			"open_reqs": open_reqs,
			"applications_this_month": apps_this_month,
			"offers_extended": offers_extended,
			"avg_time_to_fill_days": avg_ttf,
			"source_breakdown": source_breakdown,
		}


# ---------------------------------------------------------------------------
# Best-effort BPM registration at import time
# ---------------------------------------------------------------------------

try:
	_register_bpm()
except Exception as _exc:
	log.debug("RecruitingService: BPM registration failed: %s", _exc)


__all__ = [
	"RecruitingService",
	"RecruitingServiceError",
	"RequisitionNotFoundError",
	"ApplicationNotFoundError",
	"InterviewNotFoundError",
	"OfferNotFoundError",
	"RecruitingStateError",
]
