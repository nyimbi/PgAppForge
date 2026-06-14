"""ATS service."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.hcm.recruiting.models import JobRequisition, JobApplication, InterviewSchedule, OfferLetter


def _uuid() -> str:
	return str(uuid.uuid4())


class RecruitingService:
	def post_requisition(
		self,
		tenant_id: str,
		title: str,
		headcount: int = 1,
		department_id: str | None = None,
		session: Any = None,
	) -> JobRequisition:
		req = JobRequisition(
			id=_uuid(),
			tenant_id=tenant_id,
			title=title,
			headcount=headcount,
			department_id=department_id,
		)
		if session:
			session.add(req)
		return req

	def receive_application(
		self,
		requisition_id: str,
		tenant_id: str,
		candidate_name: str,
		candidate_email: str,
		source: str = "DIRECT",
		session: Any = None,
	) -> JobApplication:
		app = JobApplication(
			id=_uuid(),
			requisition_id=requisition_id,
			tenant_id=tenant_id,
			candidate_name=candidate_name,
			candidate_email=candidate_email,
			source=source,
		)
		if session:
			session.add(app)
		return app

	def schedule_interview(
		self,
		application_id: str,
		interviewer_id: str,
		scheduled_at: datetime,
		interview_format: str = "VIDEO",
		session: Any = None,
	) -> InterviewSchedule:
		interview = InterviewSchedule(
			id=_uuid(),
			application_id=application_id,
			interviewer_id=interviewer_id,
			scheduled_at=scheduled_at,
			interview_format=interview_format,
		)
		if session:
			session.add(interview)
		return interview

	def submit_feedback(self, interview_id: str, feedback: str, rating: int, session: Any) -> None:
		session.execute(
			sa.update(InterviewSchedule).where(InterviewSchedule.id == interview_id)
			.values(feedback=feedback, rating=rating, status="COMPLETED")
		)

	def create_offer(
		self,
		application_id: str,
		offered_salary_cents: int,
		start_date: Any,
		expiry_date: Any,
		session: Any,
	) -> OfferLetter:
		offer = OfferLetter(
			id=_uuid(),
			application_id=application_id,
			offered_salary_cents=offered_salary_cents,
			start_date=start_date,
			expiry_date=expiry_date,
		)
		session.add(offer)
		session.execute(
			sa.update(JobApplication).where(JobApplication.id == application_id)
			.values(status="OFFER")
		)
		return offer

	def accept_offer(self, offer_id: str, session: Any) -> None:
		offer = session.get(OfferLetter, offer_id)
		session.execute(
			sa.update(OfferLetter).where(OfferLetter.id == offer_id)
			.values(status="ACCEPTED", responded_at=datetime.now(timezone.utc))
		)
		session.execute(
			sa.update(JobApplication).where(JobApplication.id == offer.application_id)
			.values(status="HIRED")
		)

	def get_pipeline(self, requisition_id: str, session: Any) -> dict[str, int]:
		apps = session.execute(
			sa.select(JobApplication).where(JobApplication.requisition_id == requisition_id)
		).scalars().all()
		pipeline: dict[str, int] = {}
		for app in apps:
			pipeline[app.status] = pipeline.get(app.status, 0) + 1
		return pipeline


__all__ = ["RecruitingService"]
