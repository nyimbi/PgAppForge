"""ATS models."""
from __future__ import annotations
import sqlalchemy as sa
from pgappforge.models.sqla import Model


class JobRequisition(Model):
	__tablename__ = "hcm_job_requisition"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	title = sa.Column(sa.String(200), nullable=False)
	department_id = sa.Column(sa.String(36), nullable=True, index=True)
	entity_id = sa.Column(sa.String(36), nullable=True)
	headcount = sa.Column(sa.Integer, nullable=False, default=1)
	salary_min_cents = sa.Column(sa.BigInteger, nullable=True)
	salary_max_cents = sa.Column(sa.BigInteger, nullable=True)
	currency_code = sa.Column(sa.String(3), nullable=False, default="KES")
	status = sa.Column(sa.String(20), nullable=False, default="OPEN")
	hiring_manager_id = sa.Column(sa.String(36), nullable=True)
	job_description = sa.Column(sa.Text, nullable=True)
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
	closed_at = sa.Column(sa.DateTime(timezone=True), nullable=True)


class JobApplication(Model):
	__tablename__ = "hcm_job_application"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	requisition_id = sa.Column(sa.String(36), sa.ForeignKey("hcm_job_requisition.id"), nullable=False, index=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	candidate_name = sa.Column(sa.String(200), nullable=False)
	candidate_email = sa.Column(sa.String(200), nullable=False)
	source = sa.Column(sa.String(20), nullable=False, default="DIRECT", comment="REFERRAL, JOB_BOARD, DIRECT, AGENCY")
	resume_url = sa.Column(sa.Text, nullable=True)
	status = sa.Column(sa.String(20), nullable=False, default="APPLIED", comment="APPLIED, SCREENING, INTERVIEW, OFFER, HIRED, REJECTED")
	applied_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
	employee_id = sa.Column(sa.String(36), nullable=True, comment="Set when converted to employee")


class InterviewSchedule(Model):
	__tablename__ = "hcm_interview_schedule"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	application_id = sa.Column(sa.String(36), sa.ForeignKey("hcm_job_application.id"), nullable=False, index=True)
	interviewer_id = sa.Column(sa.String(36), nullable=True)
	scheduled_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
	interview_format = sa.Column(sa.String(20), nullable=False, default="VIDEO", comment="VIDEO, IN_PERSON, PHONE")
	feedback = sa.Column(sa.Text, nullable=True)
	rating = sa.Column(sa.Integer, nullable=True, comment="1-5")
	status = sa.Column(sa.String(20), nullable=False, default="SCHEDULED")


class OfferLetter(Model):
	__tablename__ = "hcm_offer_letter"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	application_id = sa.Column(sa.String(36), sa.ForeignKey("hcm_job_application.id"), nullable=False, index=True)
	offered_salary_cents = sa.Column(sa.BigInteger, nullable=False)
	currency_code = sa.Column(sa.String(3), nullable=False, default="KES")
	start_date = sa.Column(sa.Date, nullable=True)
	expiry_date = sa.Column(sa.Date, nullable=True)
	status = sa.Column(sa.String(20), nullable=False, default="DRAFT", comment="DRAFT, SENT, ACCEPTED, DECLINED")
	sent_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
	responded_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
