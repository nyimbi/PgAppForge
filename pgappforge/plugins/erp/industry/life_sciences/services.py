"""
pgappforge/plugins/erp/industry/life_sciences/services.py

LifeSciencesService — stateless business logic for the Life Sciences plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Safe to call from background jobs, CLI commands, and tests.

GxP invariants:
  - TrialEvent rows are NEVER updated — corrections insert a new CORRECTION row.
  - RegulatorySubmission is IMMUTABLE once status=APPROVED.
  - TrialSubject data is IMMUTABLE once status=COMPLETED or WITHDRAWN.
  - All arm randomization uses permuted block design for statistical validity.
"""
from __future__ import annotations

import logging
import math
import random
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LifeSciencesError(Exception):
	"""Base error for Life Sciences domain violations."""


class TrialNotFoundError(LifeSciencesError):
	"""No ClinicalTrial with the given id."""


class SubjectNotFoundError(LifeSciencesError):
	"""No TrialSubject with the given id."""


class EligibilityError(LifeSciencesError):
	"""Subject does not meet trial eligibility criteria."""


class DuplicateSubjectError(LifeSciencesError):
	"""subject_number already exists in this trial."""


class TrialStatusError(LifeSciencesError):
	"""Trial is not in a state that allows the requested operation."""


class SubmissionNotFoundError(LifeSciencesError):
	"""No RegulatorySubmission with the given id."""


# ---------------------------------------------------------------------------
# LifeSciencesService
# ---------------------------------------------------------------------------

class LifeSciencesService:
	"""Stateless service for Life Sciences Cloud operations.

	Callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# Subject enrollment
	# ------------------------------------------------------------------

	def enroll_subject(
		self,
		*,
		trial_id: str,
		subject_number: str,
		consent_date: date,
		arm: str,
		session: Any,
		site_id: str | None = None,
		dose_group: str | None = None,
		demographics: dict | None = None,
		screening_date: date | None = None,
	) -> Any:
		"""Enroll a subject into a clinical trial arm.

		Validates:
		  - Trial exists and is RECRUITING or ACTIVE.
		  - subject_number is unique within the trial.
		  - arm value is one of the trial's defined arms (if arms list present).
		  - Enrollment target not yet reached.

		Sets status=ENROLLED, records consent_date and arm assignment.
		Increments trial.enrolled_count.
		Emits TrialSubjectEnrolledEvent.

		Raises:
		  TrialNotFoundError, TrialStatusError, DuplicateSubjectError, EligibilityError.
		"""
		from pgappforge.plugins.erp.industry.life_sciences.models import (
			ClinicalTrial, TrialSubject,
		)
		from pgappforge.plugins.erp.industry.life_sciences.events import (
			TrialSubjectEnrolledEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		trial = session.get(ClinicalTrial, trial_id)
		if trial is None:
			raise TrialNotFoundError(f"ClinicalTrial {trial_id!r} not found")

		if trial.status not in ("RECRUITING", "ACTIVE"):
			raise TrialStatusError(
				f"Trial {trial.trial_id!r} status is {trial.status!r}; "
				f"enrollment requires RECRUITING or ACTIVE status"
			)

		if trial.enrollment_target > 0 and trial.enrolled_count >= trial.enrollment_target:
			raise EligibilityError(
				f"Trial {trial.trial_id!r} enrollment target ({trial.enrollment_target}) reached"
			)

		# Validate arm against trial arms definition (if populated)
		valid_arms = {a["arm_name"] for a in (trial.arms or []) if "arm_name" in a}
		if valid_arms and arm not in valid_arms:
			raise EligibilityError(
				f"Arm {arm!r} not defined in trial {trial.trial_id!r}. "
				f"Valid arms: {sorted(valid_arms)}"
			)

		# Check duplicate subject_number within trial
		existing = session.execute(
			select(TrialSubject).where(
				TrialSubject.trial_id == trial_id,
				TrialSubject.subject_number == subject_number,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise DuplicateSubjectError(
				f"subject_number {subject_number!r} already exists in trial {trial.trial_id!r}"
			)

		subject = TrialSubject(
			tenant_id=trial.tenant_id,
			trial_id=trial_id,
			subject_number=subject_number,
			site_id=site_id,
			consent_date=consent_date,
			screening_date=screening_date,
			randomization_date=date.today(),
			arm=arm,
			dose_group=dose_group,
			status="ENROLLED",
			demographics=demographics or {},
			protocol_deviations=[],
		)
		session.add(subject)

		# Increment enrolled count on trial
		trial.enrolled_count = (trial.enrolled_count or 0) + 1

		session.flush()

		emit_event(
			TrialSubjectEnrolledEvent(
				aggregate_id=subject.id,
				aggregate_type="TrialSubject",
				tenant_id=trial.tenant_id,
				subject_id=subject.id,
				subject_number=subject_number,
				trial_id=trial_id,
				arm=arm,
				consent_date=consent_date.isoformat(),
			),
			session,
		)

		log.info(
			"enroll_subject: trial=%r subject=%r arm=%r enrolled_count=%d",
			trial.trial_id, subject_number, arm, trial.enrolled_count,
		)
		return subject

	# ------------------------------------------------------------------
	# Adverse event recording
	# ------------------------------------------------------------------

	def record_adverse_event(
		self,
		*,
		subject_id: str,
		event_type: str,
		severity: dict,
		description: str,
		session: Any,
		event_date: datetime | None = None,
		is_serious: bool = False,
		serious_criteria: list | None = None,
		reported_by_id: str | None = None,
		authority_reference: str | None = None,
	) -> Any:
		"""Record an adverse event for a trial subject (IMMUTABLE — GxP).

		If is_serious=True or event_type=SAE:
		  - Sets reported_to_authority=True
		  - Emits SAEReportedEvent for downstream regulatory notification

		severity JSONB shape for AE/SAE:
		  {grade: int, attribution: str, outcome: str, expectedness: str}
		  grade 1=mild, 2=moderate, 3=severe, 4=life-threatening, 5=fatal

		Raises:
		  SubjectNotFoundError if subject_id does not exist.
		"""
		from pgappforge.plugins.erp.industry.life_sciences.models import (
			TrialSubject, TrialEvent,
		)
		from pgappforge.plugins.erp.industry.life_sciences.events import SAEReportedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		subject = session.get(TrialSubject, subject_id)
		if subject is None:
			raise SubjectNotFoundError(f"TrialSubject {subject_id!r} not found")

		valid_types = {"AE", "SAE", "DOSING", "VISIT", "LAB", "PROCEDURE", "PROTOCOL_DEVIATION", "CORRECTION"}
		if event_type not in valid_types:
			raise LifeSciencesError(f"event_type must be one of {valid_types}, got {event_type!r}")

		now = event_date or datetime.now(timezone.utc)
		is_sae = is_serious or event_type == "SAE"
		reported = is_sae  # SAE is auto-reported to authority

		event = TrialEvent(
			tenant_id=subject.tenant_id,
			subject_id=subject_id,
			event_type=event_type,
			event_date=now,
			description=description,
			severity=severity,
			reported_to_authority=reported,
			reported_at=datetime.now(timezone.utc) if reported else None,
			reported_by_id=reported_by_id,
			authority_reference=authority_reference,
			is_serious=is_sae,
			serious_criteria=serious_criteria or [],
		)
		session.add(event)
		session.flush()

		if is_sae:
			# Fetch trial_id for the event payload
			trial_id = str(subject.trial_id)
			emit_event(
				SAEReportedEvent(
					aggregate_id=event.id,
					aggregate_type="TrialEvent",
					tenant_id=subject.tenant_id,
					event_id=event.id,
					subject_id=subject_id,
					trial_id=trial_id,
					event_date=now.isoformat(),
					authority_reference=authority_reference or "",
					reported_by_id=reported_by_id or "",
					serious_criteria=serious_criteria or [],
				),
				session,
			)
			log.warning(
				"record_adverse_event: SAE recorded for subject=%r trial=%r criteria=%s",
				subject_id, trial_id, serious_criteria,
			)
		else:
			log.info(
				"record_adverse_event: AE type=%r grade=%s subject=%r",
				event_type, severity.get("grade"), subject_id,
			)

		return event

	# ------------------------------------------------------------------
	# Regulatory submissions
	# ------------------------------------------------------------------

	def submit_to_authority(
		self,
		*,
		trial_id: str | None,
		authority: str,
		submission_type: str,
		session: Any,
		submission_id: str | None = None,
		tenant_id: str | None = None,
		dossier_reference: str | None = None,
		notes: str | None = None,
	) -> Any:
		"""Create a regulatory submission record.

		trial_id may be None for post-marketing submissions (SAFETY_REPORT, VARIATION).
		submission_id defaults to a generated unique string.

		Raises:
		  TrialNotFoundError if trial_id provided but not found.
		  LifeSciencesError for invalid authority or submission_type values.
		"""
		from pgappforge.plugins.erp.industry.life_sciences.models import (
			ClinicalTrial, RegulatorySubmission,
		)
		import uuid

		valid_authorities = {"FDA", "EMA", "MHRA", "PMDA", "TGA", "HEALTH_CANADA", "OTHER"}
		if authority not in valid_authorities:
			raise LifeSciencesError(
				f"authority must be one of {valid_authorities}, got {authority!r}"
			)

		valid_types = {"IND", "NDA", "BLA", "ANDA", "MAA", "CTA", "VARIATION", "RENEWAL", "SAFETY_REPORT"}
		if submission_type not in valid_types:
			raise LifeSciencesError(
				f"submission_type must be one of {valid_types}, got {submission_type!r}"
			)

		resolved_tenant_id = tenant_id
		if trial_id is not None:
			trial = session.get(ClinicalTrial, trial_id)
			if trial is None:
				raise TrialNotFoundError(f"ClinicalTrial {trial_id!r} not found")
			resolved_tenant_id = resolved_tenant_id or trial.tenant_id

		if submission_id is None:
			submission_id = f"SUB-{uuid.uuid4().hex[:10].upper()}"

		sub = RegulatorySubmission(
			tenant_id=resolved_tenant_id or "",
			submission_id=submission_id,
			trial_id=trial_id,
			authority=authority,
			submission_type=submission_type,
			submission_date=date.today(),
			status="SUBMITTED",
			conditions=[],
			dossier_reference=dossier_reference,
			notes=notes,
		)
		session.add(sub)
		session.flush()

		log.info(
			"submit_to_authority: submission=%r trial=%r authority=%r type=%r",
			submission_id, trial_id, authority, submission_type,
		)
		return sub

	# ------------------------------------------------------------------
	# Clinical study report
	# ------------------------------------------------------------------

	def generate_clinical_study_report(
		self,
		trial_id: str,
		session: Any,
	) -> dict:
		"""Generate a structured Clinical Study Report (CSR) summary.

		Returns enrollment summary, AE/SAE counts by severity grade,
		completion rates, and milestone status.  Statistical efficacy
		analysis is stubbed — requires primary endpoint data.
		"""
		from pgappforge.plugins.erp.industry.life_sciences.models import (
			ClinicalTrial, TrialSubject, TrialEvent,
		)

		trial = session.get(ClinicalTrial, trial_id)
		if trial is None:
			raise TrialNotFoundError(f"ClinicalTrial {trial_id!r} not found")

		# Enrollment breakdown by arm and status
		enroll_rows = session.execute(
			sa.select(
				TrialSubject.arm,
				TrialSubject.status,
				func.count(TrialSubject.id).label("count"),
			)
			.where(TrialSubject.trial_id == trial_id)
			.group_by(TrialSubject.arm, TrialSubject.status)
		).all()

		enrollment_by_arm: dict[str, dict] = {}
		for r in enroll_rows:
			if r.arm not in enrollment_by_arm:
				enrollment_by_arm[r.arm] = {}
			enrollment_by_arm[r.arm][r.status] = r.count

		total_subjects = sum(
			sum(v.values()) for v in enrollment_by_arm.values()
		)
		completed = sum(
			v.get("COMPLETED", 0) for v in enrollment_by_arm.values()
		)
		withdrawn = sum(
			v.get("WITHDRAWN", 0) for v in enrollment_by_arm.values()
		)

		# AE/SAE summary
		ae_rows = session.execute(
			sa.select(
				TrialEvent.event_type,
				TrialEvent.is_serious,
				func.count(TrialEvent.id).label("count"),
			)
			.join(TrialSubject, TrialSubject.id == TrialEvent.subject_id)
			.where(
				TrialSubject.trial_id == trial_id,
				TrialEvent.event_type.in_(["AE", "SAE"]),
			)
			.group_by(TrialEvent.event_type, TrialEvent.is_serious)
		).all()

		ae_count = sum(r.count for r in ae_rows if r.event_type == "AE" and not r.is_serious)
		sae_count = sum(r.count for r in ae_rows if r.is_serious)

		# SAE severity grade distribution (from JSONB — best-effort)
		sae_events = session.execute(
			sa.select(TrialEvent.severity)
			.join(TrialSubject, TrialSubject.id == TrialEvent.subject_id)
			.where(
				TrialSubject.trial_id == trial_id,
				TrialEvent.is_serious.is_(True),
			)
		).scalars().all()

		grade_dist: dict[str, int] = {}
		for sev in sae_events:
			if isinstance(sev, dict):
				grade = str(sev.get("grade", "unknown"))
				grade_dist[grade] = grade_dist.get(grade, 0) + 1

		completion_rate = round(completed / total_subjects * 100, 2) if total_subjects > 0 else 0.0

		return {
			"trial_id": trial_id,
			"trial_ref": trial.trial_id,
			"title": trial.title,
			"phase": trial.phase,
			"indication": trial.indication,
			"status": trial.status,
			"enrollment_summary": {
				"target": trial.enrollment_target,
				"total_enrolled": total_subjects,
				"completed": completed,
				"withdrawn": withdrawn,
				"completion_rate_pct": completion_rate,
				"by_arm": enrollment_by_arm,
			},
			"adverse_events": {
				"ae_count": ae_count,
				"sae_count": sae_count,
				"sae_grade_distribution": grade_dist,
			},
			"milestones": {
				"start_date": trial.start_date.isoformat() if trial.start_date else None,
				"primary_endpoint": trial.primary_endpoint.isoformat() if trial.primary_endpoint else None,
				"estimated_completion": trial.estimated_completion_date.isoformat() if trial.estimated_completion_date else None,
				"actual_completion": trial.actual_completion_date.isoformat() if trial.actual_completion_date else None,
			},
			"efficacy_analysis": {
				"status": "stub",
				"note": "Primary endpoint efficacy analysis requires eCRF data integration.",
			},
		}

	# ------------------------------------------------------------------
	# Pharmacovigilance signal detection
	# ------------------------------------------------------------------

	def calculate_safety_signal(
		self,
		drug_name: str,
		ae_term: str,
		session: Any,
		tenant_id: str | None = None,
	) -> dict:
		"""Calculate pharmacovigilance signal metrics for a drug/AE pair.

		Computes:
		  - Reporting Odds Ratio (ROR)
		  - Proportional Reporting Ratio (PRR)

		Uses the 2x2 contingency table:
		  a = reports with drug AND ae_term
		  b = reports with drug but NOT ae_term
		  c = reports without drug but WITH ae_term
		  d = reports without drug and NOT ae_term

		ae_term is matched against TrialEvent.description (case-insensitive LIKE).
		drug_name matched against TrialEvent.severity JSONB 'drug' field or description.

		Returns dict with ROR, PRR, counts and signal flag.
		"""
		from pgappforge.plugins.erp.industry.life_sciences.models import TrialEvent

		# Count total AE events (proxy for all spontaneous reports in this dataset)
		base_q = sa.select(func.count(TrialEvent.id)).where(
			TrialEvent.event_type.in_(["AE", "SAE"])
		)
		if tenant_id:
			from pgappforge.plugins.erp.industry.life_sciences.models import TrialSubject
			base_q = base_q.join(
				TrialSubject, TrialSubject.id == TrialEvent.subject_id
			).where(TrialSubject.tenant_id == tenant_id)

		total_events = session.execute(base_q).scalar_one() or 0

		drug_lower = drug_name.lower()
		ae_lower = ae_term.lower()

		all_events = session.execute(
			sa.select(TrialEvent.description, TrialEvent.severity)
			.where(TrialEvent.event_type.in_(["AE", "SAE"]))
		).all()

		a = b = c = d = 0
		for ev_desc, ev_sev in all_events:
			desc = (ev_desc or "").lower()
			sev_str = str(ev_sev or "").lower()
			has_drug = drug_lower in desc or drug_lower in sev_str
			has_ae = ae_lower in desc

			if has_drug and has_ae:
				a += 1
			elif has_drug and not has_ae:
				b += 1
			elif not has_drug and has_ae:
				c += 1
			else:
				d += 1

		# Avoid division by zero with Haldane-Anscombe correction
		_a = a + 0.5
		_b = b + 0.5
		_c = c + 0.5
		_d = d + 0.5

		ror = (_a * _d) / (_b * _c)
		prr = (_a / (_a + _b)) / (_c / (_c + _d)) if (_a + _b) > 0 and (_c + _d) > 0 else 0.0

		# Signal: ROR > 2.0 with at least 3 co-reported cases (Evans criteria)
		is_signal = ror > 2.0 and a >= 3

		import math
		log_ror = math.log(ror) if ror > 0 else 0
		# Approximate 95% CI for log-ROR
		se_log_ror = math.sqrt(1 / _a + 1 / _b + 1 / _c + 1 / _d)
		ror_lower = math.exp(log_ror - 1.96 * se_log_ror)
		ror_upper = math.exp(log_ror + 1.96 * se_log_ror)

		return {
			"drug_name": drug_name,
			"ae_term": ae_term,
			"contingency_table": {"a": a, "b": b, "c": c, "d": d},
			"ror": round(ror, 4),
			"ror_95ci_lower": round(ror_lower, 4),
			"ror_95ci_upper": round(ror_upper, 4),
			"prr": round(prr, 4),
			"is_signal": is_signal,
			"signal_criteria": "Evans (ROR>2.0, n>=3)",
			"total_events_analysed": total_events,
		}

	# ------------------------------------------------------------------
	# Randomization
	# ------------------------------------------------------------------

	def randomize_subjects(
		self,
		trial_id: str,
		session: Any,
		randomization_ratio: str = "1:1",
		block_size_multiplier: int = 2,
	) -> dict:
		"""Assign treatment arms to unenrolled/screened subjects using permuted block randomization.

		randomization_ratio: "1:1", "2:1", "1:1:1" etc. (one part per arm, in trial.arms order).
		block_size_multiplier: block_size = sum(ratio_parts) * block_size_multiplier.

		Only assigns subjects currently in SCREENED status (pre-randomization).
		Updates subject.arm, subject.randomization_date, subject.status → ENROLLED.

		Returns summary dict with assignments made.
		"""
		from pgappforge.plugins.erp.industry.life_sciences.models import (
			ClinicalTrial, TrialSubject,
		)

		trial = session.get(ClinicalTrial, trial_id)
		if trial is None:
			raise TrialNotFoundError(f"ClinicalTrial {trial_id!r} not found")

		arms_def = trial.arms or []
		if not arms_def:
			raise LifeSciencesError(
				f"Trial {trial.trial_id!r} has no arms defined. "
				f"Populate trial.arms before randomizing."
			)

		# Parse ratio
		ratio_parts = [int(x) for x in randomization_ratio.split(":")]
		if len(ratio_parts) != len(arms_def):
			raise LifeSciencesError(
				f"randomization_ratio has {len(ratio_parts)} parts but trial has "
				f"{len(arms_def)} arms"
			)

		arm_names = [a["arm_name"] for a in arms_def]
		block_size = sum(ratio_parts) * block_size_multiplier

		# Build a block template: e.g. ratio 2:1 → [A, A, B]
		template: list[str] = []
		for arm_name, count in zip(arm_names, ratio_parts):
			template.extend([arm_name] * count)

		# Fetch subjects to randomize
		subjects = session.execute(
			select(TrialSubject)
			.where(
				TrialSubject.trial_id == trial_id,
				TrialSubject.status == "SCREENED",
			)
			.order_by(TrialSubject.created_at)
		).scalars().all()

		if not subjects:
			return {
				"trial_id": trial_id,
				"assignments": [],
				"total_randomized": 0,
				"message": "No SCREENED subjects found for randomization.",
			}

		# Generate enough permuted blocks to cover all subjects
		assignments: list[str] = []
		while len(assignments) < len(subjects):
			block = template.copy()
			random.shuffle(block)
			assignments.extend(block)

		today = date.today()
		assignment_records = []
		for subj, arm in zip(subjects, assignments):
			subj.arm = arm
			subj.randomization_date = today
			subj.status = "ENROLLED"
			assignment_records.append({
				"subject_id": subj.id,
				"subject_number": subj.subject_number,
				"arm": arm,
			})

		trial.enrolled_count = (trial.enrolled_count or 0) + len(subjects)
		session.flush()

		log.info(
			"randomize_subjects: trial=%r assigned %d subjects ratio=%s",
			trial.trial_id, len(subjects), randomization_ratio,
		)
		return {
			"trial_id": trial_id,
			"trial_ref": trial.trial_id,
			"randomization_ratio": randomization_ratio,
			"block_size": block_size,
			"total_randomized": len(subjects),
			"assignments": assignment_records,
		}

	# ------------------------------------------------------------------
	# Trial dashboard
	# ------------------------------------------------------------------

	def get_trial_dashboard(
		self,
		trial_id: str,
		session: Any,
	) -> dict:
		"""Return operational dashboard for a trial.

		Returns enrollment rate, completion rate, AE/SAE summary,
		submission count, milestone adherence, and active/overdue flag.
		"""
		from pgappforge.plugins.erp.industry.life_sciences.models import (
			ClinicalTrial, TrialSubject, TrialEvent, RegulatorySubmission,
		)

		trial = session.get(ClinicalTrial, trial_id)
		if trial is None:
			raise TrialNotFoundError(f"ClinicalTrial {trial_id!r} not found")

		# Subject status counts
		status_rows = session.execute(
			sa.select(TrialSubject.status, func.count(TrialSubject.id).label("count"))
			.where(TrialSubject.trial_id == trial_id)
			.group_by(TrialSubject.status)
		).all()
		status_map = {r.status: r.count for r in status_rows}
		total_enrolled = sum(status_map.values())
		completed = status_map.get("COMPLETED", 0)
		withdrawn = status_map.get("WITHDRAWN", 0)

		enrollment_rate_pct = (
			round(total_enrolled / trial.enrollment_target * 100, 2)
			if trial.enrollment_target > 0 else 0.0
		)
		completion_rate_pct = (
			round(completed / total_enrolled * 100, 2)
			if total_enrolled > 0 else 0.0
		)

		# AE/SAE counts
		ae_count = session.execute(
			sa.select(func.count(TrialEvent.id))
			.join(TrialSubject, TrialSubject.id == TrialEvent.subject_id)
			.where(
				TrialSubject.trial_id == trial_id,
				TrialEvent.event_type == "AE",
				TrialEvent.is_serious.is_(False),
			)
		).scalar_one() or 0

		sae_count = session.execute(
			sa.select(func.count(TrialEvent.id))
			.join(TrialSubject, TrialSubject.id == TrialEvent.subject_id)
			.where(
				TrialSubject.trial_id == trial_id,
				TrialEvent.is_serious.is_(True),
			)
		).scalar_one() or 0

		unreported_sae = session.execute(
			sa.select(func.count(TrialEvent.id))
			.join(TrialSubject, TrialSubject.id == TrialEvent.subject_id)
			.where(
				TrialSubject.trial_id == trial_id,
				TrialEvent.is_serious.is_(True),
				TrialEvent.reported_to_authority.is_(False),
			)
		).scalar_one() or 0

		# Submissions
		sub_count = session.execute(
			sa.select(func.count(RegulatorySubmission.id))
			.where(RegulatorySubmission.trial_id == trial_id)
		).scalar_one() or 0

		# Milestone flags
		today = date.today()
		behind_schedule = (
			trial.primary_endpoint is not None
			and trial.actual_completion_date is None
			and trial.primary_endpoint < today
		)

		return {
			"trial_id": trial_id,
			"trial_ref": trial.trial_id,
			"title": trial.title,
			"phase": trial.phase,
			"status": trial.status,
			"enrollment": {
				"target": trial.enrollment_target,
				"enrolled": total_enrolled,
				"completed": completed,
				"withdrawn": withdrawn,
				"enrollment_rate_pct": enrollment_rate_pct,
				"completion_rate_pct": completion_rate_pct,
				"by_status": status_map,
			},
			"safety": {
				"ae_count": ae_count,
				"sae_count": sae_count,
				"unreported_sae_count": unreported_sae,
				"safety_flag": unreported_sae > 0,
			},
			"regulatory": {
				"submission_count": sub_count,
			},
			"milestones": {
				"start_date": trial.start_date.isoformat() if trial.start_date else None,
				"primary_endpoint": trial.primary_endpoint.isoformat() if trial.primary_endpoint else None,
				"estimated_completion": trial.estimated_completion_date.isoformat() if trial.estimated_completion_date else None,
				"actual_completion": trial.actual_completion_date.isoformat() if trial.actual_completion_date else None,
				"behind_schedule": behind_schedule,
			},
		}


__all__ = [
	"LifeSciencesService",
	"LifeSciencesError",
	"TrialNotFoundError",
	"SubjectNotFoundError",
	"EligibilityError",
	"DuplicateSubjectError",
	"TrialStatusError",
	"SubmissionNotFoundError",
]
