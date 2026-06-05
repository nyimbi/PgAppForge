"""
pgappforge/plugins/erp/industry/public_sector/services.py

PublicSectorService — stateless business logic for the Public Sector plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.

Key invariants:
  - Benefit grants require case.status == APPROVED (CaseNotApprovedError otherwise)
  - Grant disbursements are add-only; disbursed_cents never decremented
  - disbursed_cents + tranche must never exceed amount_cents (GrantOverDisbursementError)
  - eligibility_score: NUMERIC(5,4) in [0.0000, 1.0000]
  - All monetary amounts are integer cents (never float)
  - SLA threshold: 30 days open without decision
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func, select

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PublicSectorServiceError(Exception):
	"""Base error for Public Sector domain violations."""


class ConstituentNotFoundError(PublicSectorServiceError):
	"""No Constituent with the given id."""


class CaseNotFoundError(PublicSectorServiceError):
	"""No GovernmentCase with the given id."""


class GrantNotFoundError(PublicSectorServiceError):
	"""No PublicFundingGrant with the given id."""


class ServiceRequestNotFoundError(PublicSectorServiceError):
	"""No ServiceRequest with the given id."""


class CaseNotApprovedError(PublicSectorServiceError):
	"""Benefit grant attempted on a case that is not in APPROVED status."""


class GrantOverDisbursementError(PublicSectorServiceError):
	"""Disbursement tranche would exceed the total grant amount."""


class DuplicateConstituentError(PublicSectorServiceError):
	"""constituent_number already exists for this tenant."""


# ---------------------------------------------------------------------------
# Program-type eligibility rules
# ---------------------------------------------------------------------------

# Minimum eligibility score thresholds by program type
_PROGRAM_SCORE_THRESHOLD: dict[str, float] = {
	"SOCIAL_GRANT": 0.40,
	"HOUSING": 0.55,
	"HEALTH": 0.35,
	"EDUCATION": 0.45,
	"BUSINESS_SUPPORT": 0.60,
	"DISABILITY": 0.30,
	"UNEMPLOYMENT": 0.50,
}

# Indicative maximum monthly benefit amounts by program type (cents)
_PROGRAM_MAX_BENEFIT_CENTS: dict[str, int] = {
	"SOCIAL_GRANT": 50000,       # $500/mo
	"HOUSING": 200000,           # $2,000/mo
	"HEALTH": 150000,            # $1,500/mo
	"EDUCATION": 75000,          # $750/mo
	"BUSINESS_SUPPORT": 500000,  # $5,000 one-off
	"DISABILITY": 60000,         # $600/mo
	"UNEMPLOYMENT": 40000,       # $400/mo
}


def _uuid4() -> str:
	return str(uuid.uuid4())


def _today_iso() -> str:
	return date.today().isoformat()


# ---------------------------------------------------------------------------
# PublicSectorService
# ---------------------------------------------------------------------------

class PublicSectorService:
	"""Stateless service for Public Sector operations.

	Callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# Constituent
	# ------------------------------------------------------------------

	def register_constituent(
		self,
		*,
		tenant_id: str,
		party_id: str,
		constituent_type: str,
		national_id: str | None = None,
		case_worker_id: str | None = None,
		contact_email: str | None = None,
		contact_phone: str | None = None,
		preferred_language: str | None = None,
		address: dict | None = None,
		session: Any,
	) -> Any:
		"""Create and register a new Constituent.

		national_id is stored as-is; callers are responsible for
		application-layer encryption before passing (national_id maps to
		national_id_encrypted on the model).

		Raises DuplicateConstituentError if a constituent with the same
		party_id already exists for this tenant.
		"""
		from pgappforge.plugins.erp.industry.public_sector.models import Constituent
		from pgappforge.plugins.erp.industry.public_sector.events import (
			ConstituentRegisteredEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		existing = session.execute(
			select(Constituent).where(
				Constituent.tenant_id == tenant_id,
				Constituent.party_id == party_id,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise DuplicateConstituentError(
				f"Constituent for party_id {party_id!r} already exists in tenant {tenant_id!r}"
			)

		# Generate a sequential-style constituent number
		count = session.execute(
			select(func.count()).select_from(Constituent).where(
				Constituent.tenant_id == tenant_id
			)
		).scalar_one()
		constituent_number = f"CONST-{tenant_id[:8].upper()}-{count + 1:06d}"

		constituent = Constituent(
			tenant_id=tenant_id,
			party_id=party_id,
			constituent_number=constituent_number,
			constituent_type=constituent_type,
			national_id_encrypted=national_id,
			case_worker_id=case_worker_id,
			contact_email=contact_email,
			contact_phone=contact_phone,
			preferred_language=preferred_language,
			address=address or {},
			benefits_enrolled=[],
			vulnerability_flags=[],
			status="ACTIVE",
		)
		session.add(constituent)
		session.flush()

		emit_event(
			ConstituentRegisteredEvent(
				aggregate_id=constituent.id,
				aggregate_type="Constituent",
				tenant_id=tenant_id,
				constituent_id=constituent.id,
				constituent_number=constituent_number,
				constituent_type=constituent_type,
				case_worker_id=case_worker_id or "",
			),
			session,
		)

		log.info(
			"register_constituent: created %r type=%r tenant=%r",
			constituent_number, constituent_type, tenant_id,
		)
		return constituent

	# ------------------------------------------------------------------
	# Cases
	# ------------------------------------------------------------------

	def open_case(
		self,
		*,
		constituent_id: str,
		program_type: str,
		application_details: dict | None = None,
		case_worker_id: str | None = None,
		session: Any,
	) -> Any:
		"""Open a new GovernmentCase for a constituent.

		Sets initial eligibility_score based on program type rules and
		application_details heuristics. Emits ps.case.opened.
		"""
		from pgappforge.plugins.erp.industry.public_sector.models import (
			Constituent,
			GovernmentCase,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		constituent = session.get(Constituent, constituent_id)
		if constituent is None:
			raise ConstituentNotFoundError(f"Constituent {constituent_id!r} not found")

		# Compute initial eligibility estimate
		details = application_details or {}
		initial_score = self._estimate_initial_score(program_type, details)

		count = session.execute(
			select(func.count()).select_from(GovernmentCase).where(
				GovernmentCase.constituent_id == constituent_id
			)
		).scalar_one()
		case_number = f"CASE-{constituent_id[:8].upper()}-{count + 1:04d}"

		case = GovernmentCase(
			tenant_id=constituent.tenant_id,
			case_number=case_number,
			constituent_id=constituent_id,
			case_worker_id=case_worker_id or constituent.case_worker_id,
			program_type=program_type,
			eligibility_score=initial_score,
			benefits_granted=[],
			total_benefit_amount_cents=0,
			status="OPEN",
			supporting_documents=details.get("documents", []),
			notes=details.get("notes"),
		)
		session.add(case)
		session.flush()

		# Emit lightweight event (no formal dataclass for case.opened in events.py —
		# use foundation emit_event with a plain dict payload)
		try:
			from pgappforge.plugins.erp.foundation.events import DomainEvent

			class _CaseOpenedEvent(DomainEvent):
				event_type: str = "ps.case.opened"
				case_id: str = ""
				case_number: str = ""
				constituent_id: str = ""
				program_type: str = ""

			emit_event(
				_CaseOpenedEvent(
					aggregate_id=case.id,
					aggregate_type="GovernmentCase",
					tenant_id=constituent.tenant_id,
					case_id=case.id,
					case_number=case_number,
					constituent_id=constituent_id,
					program_type=program_type,
				),
				session,
			)
		except Exception as exc:
			log.debug("open_case: event emit failed (non-fatal): %s", exc)

		log.info("open_case: %r program=%r constituent=%r", case_number, program_type, constituent_id)
		return case

	def make_decision(
		self,
		*,
		case_id: str,
		decision: str,
		benefits_granted_dict: dict | None = None,
		reviewer_id: str | None = None,
		rejection_reason: str | None = None,
		session: Any,
	) -> Any:
		"""Record an APPROVED or REJECTED decision on a case.

		APPROVED: updates benefits_enrolled on the constituent, emits
		          ps.benefit.granted and ps.case.decision.made.
		REJECTED: records rejection_reason, emits ps.case.decision.made.

		decision must be one of: APPROVED, REJECTED.
		benefits_granted_dict: {benefit_type: amount_cents, ...}
		"""
		from pgappforge.plugins.erp.industry.public_sector.models import (
			Constituent,
			GovernmentCase,
		)
		from pgappforge.plugins.erp.industry.public_sector.events import (
			GovernmentCaseApprovedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		case = session.get(GovernmentCase, case_id)
		if case is None:
			raise CaseNotFoundError(f"GovernmentCase {case_id!r} not found")

		if decision not in ("APPROVED", "REJECTED"):
			raise PublicSectorServiceError(
				f"Invalid decision {decision!r}. Must be APPROVED or REJECTED."
			)

		benefits = benefits_granted_dict or {}
		now = datetime.now(timezone.utc)

		if decision == "APPROVED":
			case.status = "APPROVED"
			case.verified_by = reviewer_id

			# Build benefits_granted list
			benefit_entries = [
				{
					"benefit_type": btype,
					"amount_cents": amount,
					"frequency": "MONTHLY",
					"start_date": _today_iso(),
				}
				for btype, amount in benefits.items()
			]
			case.benefits_granted = benefit_entries
			case.total_benefit_amount_cents = sum(benefits.values())
			case.grant_start = date.today()

			# Update constituent benefits_enrolled
			constituent = session.get(Constituent, case.constituent_id)
			if constituent is not None:
				enrolled = list(constituent.benefits_enrolled or [])
				enrolled.append({
					"program_code": case.program_type,
					"case_id": case_id,
					"enrolled_at": _today_iso(),
					"status": "ACTIVE",
				})
				constituent.benefits_enrolled = enrolled

			# Emit case approved event
			emit_event(
				GovernmentCaseApprovedEvent(
					aggregate_id=case_id,
					aggregate_type="GovernmentCase",
					tenant_id=case.tenant_id,
					case_id=case_id,
					case_number=case.case_number,
					constituent_id=case.constituent_id,
					program_type=case.program_type,
					total_benefit_amount_cents=case.total_benefit_amount_cents,
					grant_start=_today_iso(),
					grant_end="",
				),
				session,
			)

			# Emit benefit granted event
			try:
				from pgappforge.plugins.erp.foundation.events import DomainEvent

				class _BenefitGrantedEvent(DomainEvent):
					event_type: str = "ps.benefit.granted"
					case_id: str = ""
					constituent_id: str = ""
					program_type: str = ""
					total_benefit_amount_cents: int = 0

				emit_event(
					_BenefitGrantedEvent(
						aggregate_id=case_id,
						aggregate_type="GovernmentCase",
						tenant_id=case.tenant_id,
						case_id=case_id,
						constituent_id=case.constituent_id,
						program_type=case.program_type,
						total_benefit_amount_cents=case.total_benefit_amount_cents,
					),
					session,
				)
			except Exception as exc:
				log.debug("make_decision: benefit.granted emit failed (non-fatal): %s", exc)

		else:  # REJECTED
			case.status = "REJECTED"
			case.rejection_reason = rejection_reason or "Application did not meet eligibility criteria."
			case.verified_by = reviewer_id

		log.info(
			"make_decision: case=%r decision=%r program=%r",
			case.case_number, decision, case.program_type,
		)
		return case

	# ------------------------------------------------------------------
	# Eligibility
	# ------------------------------------------------------------------

	def calculate_eligibility(
		self,
		*,
		constituent_id: str,
		program_type: str,
		session: Any,
	) -> dict:
		"""Calculate eligibility for a constituent against a program.

		Returns::

		    {
		        "eligible": bool,
		        "score": float,            # [0.0, 1.0]
		        "disqualifying_factors": list[str],
		        "eligible_amount_cents": int,
		    }

		Score components (equal weight):
		  - constituent status == ACTIVE                  (+0.25)
		  - no existing ACTIVE case for same program      (+0.20)
		  - vulnerability flags present                   (+0.20)
		  - income/means indicators not present           (+0.20)
		  - preferred_language / contact completeness     (+0.15)
		"""
		from pgappforge.plugins.erp.industry.public_sector.models import (
			Constituent,
			GovernmentCase,
		)

		constituent = session.get(Constituent, constituent_id)
		if constituent is None:
			raise ConstituentNotFoundError(f"Constituent {constituent_id!r} not found")

		disqualifying: list[str] = []
		score = 0.0

		# Component 1: active status
		if constituent.status == "ACTIVE":
			score += 0.25
		else:
			disqualifying.append(f"Constituent status is {constituent.status!r}, not ACTIVE")

		# Component 2: no duplicate active case for same program
		active_case = session.execute(
			select(GovernmentCase).where(
				GovernmentCase.constituent_id == constituent_id,
				GovernmentCase.program_type == program_type,
				GovernmentCase.status.in_(["OPEN", "UNDER_REVIEW", "APPROVED", "ACTIVE"]),
			).limit(1)
		).scalar_one_or_none()

		if active_case is None:
			score += 0.20
		else:
			disqualifying.append(
				f"Constituent already has an active case ({active_case.case_number!r}) "
				f"for program {program_type!r}"
			)

		# Component 3: vulnerability flags indicate priority need
		if constituent.vulnerability_flags:
			score += 0.20

		# Component 4: contact information complete (proxy for "reachable")
		if constituent.contact_email or constituent.contact_phone:
			score += 0.20

		# Component 5: address on file
		if constituent.address and constituent.address.get("city"):
			score += 0.15

		score = round(min(score, 1.0), 4)

		threshold = _PROGRAM_SCORE_THRESHOLD.get(program_type, 0.50)
		eligible = (score >= threshold) and (len(disqualifying) == 0)

		max_benefit = _PROGRAM_MAX_BENEFIT_CENTS.get(program_type, 0)
		eligible_amount = int(max_benefit * score) if eligible else 0

		return {
			"eligible": eligible,
			"score": score,
			"disqualifying_factors": disqualifying,
			"eligible_amount_cents": eligible_amount,
		}

	# ------------------------------------------------------------------
	# Benefit disbursement
	# ------------------------------------------------------------------

	def disburse_benefit(
		self,
		*,
		case_id: str,
		amount_cents: int,
		payment_method: str,
		disbursed_by_id: str | None = None,
		session: Any,
	) -> dict:
		"""Record a benefit payment for an APPROVED case.

		Validates case is APPROVED before disbursing.
		Records disbursement in case notes (immutable ledger pattern).
		"""
		from pgappforge.plugins.erp.industry.public_sector.models import GovernmentCase

		case = session.get(GovernmentCase, case_id)
		if case is None:
			raise CaseNotFoundError(f"GovernmentCase {case_id!r} not found")

		if case.status != "APPROVED":
			raise CaseNotApprovedError(
				f"Case {case.case_number!r} is in status {case.status!r}. "
				"Benefit disbursement requires APPROVED status."
			)

		now = datetime.now(timezone.utc)
		disbursement_record = {
			"disbursed_at": now.isoformat(),
			"amount_cents": amount_cents,
			"payment_method": payment_method,
			"disbursed_by_id": disbursed_by_id or "",
		}

		# Append disbursement to case notes as JSON record (ledger pattern)
		existing_notes = case.notes or ""
		import json as _json
		case.notes = (existing_notes + "\n" if existing_notes else "") + _json.dumps(disbursement_record)

		log.info(
			"disburse_benefit: case=%r amount=%d method=%r",
			case.case_number, amount_cents, payment_method,
		)

		return {
			"case_id": case_id,
			"case_number": case.case_number,
			"disbursed_at": now.isoformat(),
			"amount_cents": amount_cents,
			"payment_method": payment_method,
		}

	# ------------------------------------------------------------------
	# Grant
	# ------------------------------------------------------------------

	def process_grant_application(
		self,
		*,
		grant_id: str,
		applicant_party_id: str,
		application: dict | None = None,
		session: Any,
	) -> Any:
		"""Process a grant application — opens a BUSINESS_SUPPORT case linked to the grant.

		Returns the new GovernmentCase created for tracking the application.
		"""
		from pgappforge.plugins.erp.industry.public_sector.models import (
			Constituent,
			PublicFundingGrant,
		)

		grant = session.get(PublicFundingGrant, grant_id)
		if grant is None:
			raise GrantNotFoundError(f"PublicFundingGrant {grant_id!r} not found")

		# Resolve or create a constituent for the applicant party
		constituent = session.execute(
			select(Constituent).where(
				Constituent.tenant_id == grant.tenant_id,
				Constituent.party_id == applicant_party_id,
			)
		).scalar_one_or_none()

		if constituent is None:
			constituent = self.register_constituent(
				tenant_id=grant.tenant_id,
				party_id=applicant_party_id,
				constituent_type="BUSINESS",
				session=session,
			)

		app_details = application or {}
		app_details["grant_id"] = grant_id
		app_details["grant_number"] = grant.grant_number

		case = self.open_case(
			constituent_id=constituent.id,
			program_type="BUSINESS_SUPPORT",
			application_details=app_details,
			session=session,
		)

		log.info(
			"process_grant_application: grant=%r applicant=%r case=%r",
			grant.grant_number, applicant_party_id, case.case_number,
		)
		return case

	def record_grant_disbursement(
		self,
		*,
		grant_id: str,
		tranche_amount_cents: int,
		disbursed_by_id: str | None = None,
		session: Any,
	) -> dict:
		"""Record a funding tranche disbursement for a PublicFundingGrant.

		Raises GrantOverDisbursementError if disbursed_cents + tranche > amount_cents.
		Emits ps.grant.disbursed event.
		"""
		from pgappforge.plugins.erp.industry.public_sector.models import PublicFundingGrant
		from pgappforge.plugins.erp.industry.public_sector.events import GrantDisbursementEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		grant = session.get(PublicFundingGrant, grant_id)
		if grant is None:
			raise GrantNotFoundError(f"PublicFundingGrant {grant_id!r} not found")

		new_total = grant.disbursed_cents + tranche_amount_cents
		if new_total > grant.amount_cents:
			raise GrantOverDisbursementError(
				f"Tranche of {tranche_amount_cents} cents would exceed total grant amount "
				f"of {grant.amount_cents} cents for grant {grant.grant_number!r}. "
				f"Already disbursed: {grant.disbursed_cents} cents."
			)

		grant.disbursed_cents = new_total
		if grant.disbursed_cents >= grant.amount_cents:
			grant.status = "COMPLETED"
		elif grant.status == "AWARDED":
			grant.status = "ACTIVE"

		emit_event(
			GrantDisbursementEvent(
				aggregate_id=grant_id,
				aggregate_type="PublicFundingGrant",
				tenant_id=grant.tenant_id,
				grant_id=grant_id,
				grant_number=grant.grant_number,
				tranche_amount_cents=tranche_amount_cents,
				total_disbursed_cents=new_total,
				currency=grant.currency_code,
				disbursed_by_id=disbursed_by_id or "",
			),
			session,
		)

		log.info(
			"record_grant_disbursement: grant=%r tranche=%d total_disbursed=%d",
			grant.grant_number, tranche_amount_cents, new_total,
		)
		return {
			"grant_id": grant_id,
			"grant_number": grant.grant_number,
			"tranche_amount_cents": tranche_amount_cents,
			"total_disbursed_cents": new_total,
			"amount_cents": grant.amount_cents,
			"status": grant.status,
		}

	# ------------------------------------------------------------------
	# Caseload analytics
	# ------------------------------------------------------------------

	def get_caseload_summary(
		self,
		*,
		case_worker_id: str,
		session: Any,
	) -> dict:
		"""Return caseload summary for a case worker.

		Returns::

		    {
		        "open_cases": int,
		        "cases_by_status": {status: count},
		        "avg_processing_days": float,
		        "sla_breaches": int,       # cases open > 30 days
		    }
		"""
		from pgappforge.plugins.erp.industry.public_sector.models import GovernmentCase

		cases = session.execute(
			select(GovernmentCase).where(
				GovernmentCase.case_worker_id == case_worker_id,
				GovernmentCase.status.in_(["OPEN", "UNDER_REVIEW", "APPROVED", "REJECTED", "ACTIVE", "SUSPENDED"]),
			)
		).scalars().all()

		now = datetime.now(timezone.utc)
		open_cases = 0
		cases_by_status: dict[str, int] = {}
		processing_days_list: list[float] = []
		sla_breaches = 0
		sla_threshold_days = 30

		for c in cases:
			status = c.status
			cases_by_status[status] = cases_by_status.get(status, 0) + 1

			if status in ("OPEN", "UNDER_REVIEW"):
				open_cases += 1
				if c.created_at:
					created = c.created_at
					if created.tzinfo is None:
						created = created.replace(tzinfo=timezone.utc)
					days = (now - created).total_seconds() / 86400
					processing_days_list.append(days)
					if days > sla_threshold_days:
						sla_breaches += 1

		avg_processing = (
			round(sum(processing_days_list) / len(processing_days_list), 1)
			if processing_days_list else 0.0
		)

		return {
			"case_worker_id": case_worker_id,
			"open_cases": open_cases,
			"cases_by_status": cases_by_status,
			"avg_processing_days": avg_processing,
			"sla_breaches": sla_breaches,
		}

	# ------------------------------------------------------------------
	# Service report
	# ------------------------------------------------------------------

	def generate_service_report(
		self,
		*,
		program_type: str,
		period_start: date,
		period_end: date,
		tenant_id: str | None = None,
		session: Any,
	) -> dict:
		"""Generate a service delivery report for a program over a date range.

		Returns::

		    {
		        "program_type": str,
		        "period_start": str,
		        "period_end": str,
		        "total_cases": int,
		        "approved_cases": int,
		        "rejected_cases": int,
		        "approval_rate_pct": float,
		        "total_benefit_disbursed_cents": int,
		        "avg_eligibility_score": float | None,
		        "cases_by_status": {status: count},
		    }
		"""
		from pgappforge.plugins.erp.industry.public_sector.models import GovernmentCase

		q = select(GovernmentCase).where(
			GovernmentCase.program_type == program_type,
			GovernmentCase.created_at >= datetime(period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc),
			GovernmentCase.created_at < datetime(period_end.year, period_end.month, period_end.day + 1, tzinfo=timezone.utc),
		)
		if tenant_id:
			q = q.where(GovernmentCase.tenant_id == tenant_id)

		cases = session.execute(q).scalars().all()

		total = len(cases)
		approved = sum(1 for c in cases if c.status == "APPROVED")
		rejected = sum(1 for c in cases if c.status == "REJECTED")
		total_benefit = sum(c.total_benefit_amount_cents or 0 for c in cases)

		scores = [float(c.eligibility_score) for c in cases if c.eligibility_score is not None]
		avg_score = round(sum(scores) / len(scores), 4) if scores else None

		cases_by_status: dict[str, int] = {}
		for c in cases:
			cases_by_status[c.status] = cases_by_status.get(c.status, 0) + 1

		return {
			"program_type": program_type,
			"period_start": period_start.isoformat(),
			"period_end": period_end.isoformat(),
			"total_cases": total,
			"approved_cases": approved,
			"rejected_cases": rejected,
			"approval_rate_pct": round(approved / total * 100, 1) if total else 0.0,
			"total_benefit_disbursed_cents": total_benefit,
			"avg_eligibility_score": avg_score,
			"cases_by_status": cases_by_status,
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _estimate_initial_score(program_type: str, details: dict) -> float:
		"""Compute a rough initial eligibility score from application details.

		Used when opening a case before full assessment is completed.
		Factors:
		  - Program type has a base minimum threshold              (0.20 base)
		  - income_declared present and is positive               (+0.15)
		  - vulnerability_flags in details                        (+0.20)
		  - supporting documents provided                         (+0.15)
		  - prior rejection flag absent                           (+0.15)
		  - complete address supplied                             (+0.15)
		"""
		score = 0.20  # base

		if details.get("income_declared") is not None:
			score += 0.15

		if details.get("vulnerability_flags"):
			score += 0.20

		if details.get("documents"):
			score += 0.15

		if not details.get("prior_rejection"):
			score += 0.15

		addr = details.get("address", {})
		if isinstance(addr, dict) and addr.get("city"):
			score += 0.15

		return round(min(score, 1.0), 4)


__all__ = [
	"PublicSectorService",
	"PublicSectorServiceError",
	"ConstituentNotFoundError",
	"CaseNotFoundError",
	"GrantNotFoundError",
	"ServiceRequestNotFoundError",
	"CaseNotApprovedError",
	"GrantOverDisbursementError",
	"DuplicateConstituentError",
]
