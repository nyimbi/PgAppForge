"""
pgappforge/plugins/erp/industry/life_sciences/models.py

SQLAlchemy models for the Life Sciences plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid()
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - Clinical trial data is IMMUTABLE once signed off (GxP compliance)
  - TrialEvent severity: JSONB with structured adverse event grading
  - lazy='select' throughout
  - regulatory_approvals / conditions: JSONB

Table prefix: ls_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ClinicalTrial
# ---------------------------------------------------------------------------

class ClinicalTrial(AuditMixin, Model):
	"""Clinical trial master record.

	Tracks the full lifecycle from protocol design through regulatory
	approval.  regulatory_approvals JSONB stores approvals from multiple
	authorities: [{authority, approval_number, approval_date, expiry_date}]

	primary_endpoint stores the target completion date for the primary
	endpoint analysis.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ls_clinical_trial"
	__table_args__ = (
		Index("ix_ls_ct_tenant", "tenant_id"),
		Index("ix_ls_ct_sponsor", "sponsor_id"),
		Index("ix_ls_ct_phase", "phase"),
		Index("ix_ls_ct_status", "status"),
		UniqueConstraint("tenant_id", "trial_id", name="uq_ls_ct_tenant_trial"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	trial_id = Column(String(50), nullable=False, comment="Internal trial identifier; unique per tenant")
	title = Column(String(500), nullable=False)
	protocol_number = Column(String(100), nullable=True, comment="Sponsor's protocol number")
	nct_number = Column(String(20), nullable=True, comment="ClinicalTrials.gov NCT number if registered")

	phase = Column(
		String(5),
		nullable=False,
		comment="I|II|III|IV|EAP",  # EAP = Expanded Access Program
	)
	indication = Column(String(255), nullable=False, comment="Disease / therapeutic area")
	therapeutic_area = Column(String(100), nullable=True)

	sponsor_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation Party (sponsor)")
	sponsor_name = Column(String(255), nullable=True, comment="Denormalized")
	principal_investigator_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")

	enrollment_target = Column(Integer, nullable=False, default=0)
	enrolled_count = Column(Integer, nullable=False, default=0, comment="Live count; updated by enrollment service")

	start_date = Column(Date, nullable=True)
	primary_endpoint = Column(Date, nullable=True, comment="Target primary endpoint analysis date")
	estimated_completion_date = Column(Date, nullable=True)
	actual_completion_date = Column(Date, nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="DESIGN",
		comment="DESIGN|SUBMISSION|APPROVED|RECRUITING|ACTIVE|COMPLETED|SUSPENDED|TERMINATED|WITHDRAWN",
	)
	regulatory_approvals = Column(JSONB, nullable=False, default=list, comment="[{authority, approval_number, approval_date}]")
	arms = Column(JSONB, nullable=False, default=list, comment="[{arm_name, arm_type, allocation_pct, description}]")
	endpoints = Column(JSONB, nullable=False, default=list, comment="[{endpoint_type, description, timepoint}]")
	inclusion_criteria = Column(Text, nullable=True)
	exclusion_criteria = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	subjects: list[TrialSubject] = relationship("TrialSubject", back_populates="trial", lazy="select")
	regulatory_submissions: list[RegulatorySubmission] = relationship("RegulatorySubmission", back_populates="trial", lazy="select")

	def __repr__(self) -> str:
		return f"<ClinicalTrial {self.trial_id!r} phase={self.phase!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# TrialSubject
# ---------------------------------------------------------------------------

class TrialSubject(AuditMixin, Model):
	"""Clinical trial subject / participant.

	Subject numbers are unique within a trial (not globally) — the
	sponsor assigns subject_number per site.

	IMMUTABLE once status=COMPLETED or WITHDRAWN — create audit entries
	for any changes to consented data.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ls_trial_subject"
	__table_args__ = (
		Index("ix_ls_subj_trial", "trial_id"),
		Index("ix_ls_subj_tenant", "tenant_id"),
		Index("ix_ls_subj_status", "status"),
		Index("ix_ls_subj_arm", "arm"),
		UniqueConstraint("trial_id", "subject_number", name="uq_ls_subj_trial_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	trial_id = Column(UUID(as_uuid=False), ForeignKey("ls_clinical_trial.id"), nullable=False, index=True)
	subject_number = Column(String(50), nullable=False, comment="Site-assigned subject number; unique within trial")
	site_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to investigation site master")

	consent_date = Column(Date, nullable=False, comment="Date of informed consent signing")
	screening_date = Column(Date, nullable=True)
	randomization_date = Column(Date, nullable=True)
	completion_date = Column(Date, nullable=True)
	withdrawal_date = Column(Date, nullable=True)

	arm = Column(
		String(20),
		nullable=False,
		comment="TREATMENT|CONTROL|PLACEBO|OPEN_LABEL",
	)
	dose_group = Column(String(50), nullable=True, comment="Specific dose cohort within arm")

	status = Column(
		String(20),
		nullable=False,
		default="SCREENED",
		comment="SCREENED|ENROLLED|ACTIVE|COMPLETED|WITHDRAWN|SCREEN_FAILED",
	)
	withdrawal_reason = Column(String(100), nullable=True)
	protocol_deviations = Column(JSONB, nullable=False, default=list, comment="[{date, deviation_code, description, impact}]")
	demographics = Column(JSONB, nullable=False, default=dict, comment="{age, sex, weight_kg, ethnicity} — de-identified")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	trial: ClinicalTrial = relationship("ClinicalTrial", back_populates="subjects", lazy="select")
	events: list[TrialEvent] = relationship("TrialEvent", back_populates="subject", lazy="select")

	def __repr__(self) -> str:
		return f"<TrialSubject {self.subject_number!r} trial={self.trial_id!r} arm={self.arm!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# TrialEvent
# ---------------------------------------------------------------------------

class TrialEvent(AuditMixin, Model):
	"""Clinical trial event — adverse event, dosing, visit, or lab result.

	IMMUTABLE once created — GxP requires an audit trail.
	Corrections are new rows with event_type=CORRECTION referencing
	the original row in metadata.

	severity JSONB for AE/SAE grading (CTCAE):
	  {grade: int, attribution: str, outcome: str, expectedness: str}

	For DOSING events: {dose_mg, route, formulation, administered_by}
	For LAB events:    {test_name, value, unit, reference_range, flag}
	"""

	__allow_unmapped__ = True
	__tablename__ = "ls_trial_event"
	__table_args__ = (
		Index("ix_ls_event_subject", "subject_id"),
		Index("ix_ls_event_tenant", "tenant_id"),
		Index("ix_ls_event_type", "event_type"),
		Index("ix_ls_event_event_date", "event_date"),
		Index("ix_ls_event_reported", "reported_to_authority"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	subject_id = Column(UUID(as_uuid=False), ForeignKey("ls_trial_subject.id"), nullable=False, index=True)

	event_type = Column(
		String(20),
		nullable=False,
		comment="AE|SAE|DOSING|VISIT|LAB|PROCEDURE|PROTOCOL_DEVIATION|CORRECTION",
	)
	event_date = Column(DateTime(timezone=True), nullable=False, index=True)
	description = Column(Text, nullable=True)

	# Structured severity / event details
	severity = Column(JSONB, nullable=True, comment="AE/SAE: {grade, attribution, outcome}; DOSING: {dose_mg, route}; LAB: {value, unit, flag}")

	# Reporting
	reported_to_authority = Column(Boolean, nullable=False, default=False)
	reported_at = Column(DateTime(timezone=True), nullable=True)
	reported_by_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	authority_reference = Column(String(200), nullable=True, comment="Regulatory authority submission reference")

	# For SAE expedited reporting
	is_serious = Column(Boolean, nullable=False, default=False)
	serious_criteria = Column(JSONB, nullable=True, comment="[DEATH, LIFE_THREATENING, HOSPITALISATION, DISABILITY, CONGENITAL, OTHER]")
	resolved_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	subject: TrialSubject = relationship("TrialSubject", back_populates="events", lazy="select")

	def __repr__(self) -> str:
		return f"<TrialEvent subj={self.subject_id!r} type={self.event_type!r} date={self.event_date}>"


# ---------------------------------------------------------------------------
# RegulatorySubmission
# ---------------------------------------------------------------------------

class RegulatorySubmission(AuditMixin, Model):
	"""Regulatory submission to a health authority.

	Tracks IND, NDA, BLA, MAA, CTA submissions and their outcomes.
	conditions JSONB captures post-approval commitments/requirements:
	  [{condition_text, due_date, fulfilled: bool, evidence}]

	IMMUTABLE once status=APPROVED — corrections require a new submission
	or variation application.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ls_regulatory_submission"
	__table_args__ = (
		Index("ix_ls_regsub_tenant", "tenant_id"),
		Index("ix_ls_regsub_trial", "trial_id"),
		Index("ix_ls_regsub_authority", "authority"),
		Index("ix_ls_regsub_status", "status"),
		UniqueConstraint("tenant_id", "submission_id", name="uq_ls_regsub_tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	submission_id = Column(String(100), nullable=False, comment="Unique submission reference per tenant")
	trial_id = Column(UUID(as_uuid=False), ForeignKey("ls_clinical_trial.id"), nullable=True, index=True)

	authority = Column(
		String(10),
		nullable=False,
		comment="FDA|EMA|MHRA|PMDA|TGA|HEALTH_CANADA|OTHER",
	)
	submission_type = Column(
		String(20),
		nullable=False,
		comment="IND|NDA|BLA|ANDA|MAA|CTA|VARIATION|RENEWAL|SAFETY_REPORT",
	)
	submission_date = Column(Date, nullable=False)
	target_action_date = Column(Date, nullable=True, comment="PDUFA/regulatory clock target date")
	approval_date = Column(Date, nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="SUBMITTED",
		comment="SUBMITTED|ACCEPTED|UNDER_REVIEW|INFO_REQUESTED|APPROVED|REFUSED|WITHDRAWN",
	)
	approval_reference = Column(String(200), nullable=True, comment="Authority-issued approval number / license number")
	conditions = Column(JSONB, nullable=False, default=list, comment="[{condition_text, due_date, fulfilled, evidence}]")
	labeling_approved = Column(JSONB, nullable=True, comment="Approved label/SmPC content reference")

	submission_manager_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user (regulatory affairs manager)")
	dossier_reference = Column(String(200), nullable=True, comment="eCTD dossier sequence or document management ref")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	trial: ClinicalTrial | None = relationship("ClinicalTrial", back_populates="regulatory_submissions", lazy="select")

	def __repr__(self) -> str:
		return f"<RegulatorySubmission {self.submission_id!r} authority={self.authority!r} type={self.submission_type!r} status={self.status!r}>"


__all__ = [
	"ClinicalTrial",
	"TrialSubject",
	"TrialEvent",
	"RegulatorySubmission",
]
