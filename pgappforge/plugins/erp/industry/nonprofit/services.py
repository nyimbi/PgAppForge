"""
pgappforge/plugins/erp/industry/nonprofit/services.py

NonprofitService — stateless business logic for the Nonprofit Cloud plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Callers own transaction boundaries (commit/rollback).

Key invariants:
  - Donations are immutable once acknowledged_at is set
  - lifetime_giving_cents is add-only; decrements raise an error
  - Tax receipts are URL strings pointing to ReportForge-generated PDFs
  - All monetary amounts are integer cents — never float
  - LYBUNT = Last Year But Unfortunately Not This Year
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class NonprofitServiceError(Exception):
	"""Base error for Nonprofit Cloud domain violations."""


class DonorNotFoundError(NonprofitServiceError):
	"""No Donor with the given id."""


class DonationNotFoundError(NonprofitServiceError):
	"""No Donation with the given id."""


class ProgramNotFoundError(NonprofitServiceError):
	"""No NPOProgram with the given id."""


class DonationAlreadyAcknowledgedError(NonprofitServiceError):
	"""Donation is already acknowledged — it is immutable."""


# ---------------------------------------------------------------------------
# NonprofitService
# ---------------------------------------------------------------------------

class NonprofitService:
	"""Stateless service for Nonprofit Cloud operations."""

	# ------------------------------------------------------------------
	# Donation processing
	# ------------------------------------------------------------------

	def process_donation(
		self,
		*,
		tenant_id: str,
		donor_id: str,
		amount_cents: int,
		campaign_id: str | None = None,
		campaign_name: str | None = None,
		designation: str | None = None,
		payment_method: str | None = None,
		payment_reference: str | None = None,
		currency_code: str = "USD",
		is_recurring: bool = False,
		recurring_frequency: str | None = None,
		is_restricted: bool = False,
		session: Any,
	) -> Any:
		"""Record a donation, update donor aggregate fields, and emit event.

		Returns the created Donation.

		Side effects:
		  - donor.lifetime_giving_cents incremented (add-only)
		  - donor.gift_count incremented
		  - donor.last_gift_date updated
		  - donor.first_gift_date set if first donation
		  - donor.largest_gift_cents updated if this gift is the largest

		Does NOT post to GL — that is handled by the finance.gl integration
		listening to npo.donation.received.
		"""
		from pgappforge.plugins.erp.industry.nonprofit.models import Donation, Donor
		from pgappforge.plugins.erp.industry.nonprofit.events import DonationReceivedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		donor = session.get(Donor, donor_id)
		if donor is None:
			raise DonorNotFoundError(f"Donor {donor_id!r} not found")

		donation = Donation(
			tenant_id=tenant_id,
			donor_id=donor_id,
			campaign_id=campaign_id,
			campaign_name=campaign_name,
			amount_cents=amount_cents,
			currency_code=currency_code,
			functional_amount_cents=amount_cents,  # exchange_rate=1 default
			payment_method=payment_method,
			payment_reference=payment_reference,
			designation=designation,
			is_recurring=is_recurring,
			recurring_frequency=recurring_frequency,
			is_restricted=is_restricted,
			status="CLEARED",
		)
		session.add(donation)
		session.flush()

		# Update donor aggregate fields — add-only invariant
		today = date.today()
		if amount_cents > 0:
			donor.lifetime_giving_cents = (donor.lifetime_giving_cents or 0) + amount_cents
			donor.gift_count = (donor.gift_count or 0) + 1
			donor.last_gift_date = today
			if donor.first_gift_date is None:
				donor.first_gift_date = today
			if amount_cents > (donor.largest_gift_cents or 0):
				donor.largest_gift_cents = amount_cents

			# Re-segment giving level
			donor.giving_level = self._compute_giving_level(donor.lifetime_giving_cents)

		emit_event(
			DonationReceivedEvent(
				aggregate_id=donation.id,
				aggregate_type="Donation",
				tenant_id=tenant_id,
				donation_id=donation.id,
				donor_id=donor_id,
				campaign_id=campaign_id or "",
				amount_cents=amount_cents,
				currency=currency_code,
				payment_method=payment_method or "",
				is_recurring=is_recurring,
				designation=designation or "",
			),
			session,
		)

		log.info(
			"process_donation: donor=%r amount=%d¢ campaign=%r donation=%r",
			donor_id, amount_cents, campaign_id, donation.id,
		)
		return donation

	@staticmethod
	def _compute_giving_level(lifetime_cents: int) -> str:
		"""Segment donor by lifetime giving.

		    >= $10,000 → MAJOR
		    >= $1,000  → MID
		    else       → SMALL
		"""
		if lifetime_cents >= 10_000_00:
			return "MAJOR"
		if lifetime_cents >= 1_000_00:
			return "MID"
		return "SMALL"

	# ------------------------------------------------------------------
	# Tax receipts
	# ------------------------------------------------------------------

	def generate_tax_receipt(self, donation_id: str, session: Any) -> str:
		"""Generate a tax receipt PDF via ReportForge and return the URL.

		Sets donation.tax_receipt_url, donation.tax_receipt_number, and
		donation.acknowledged_at, making the record immutable.

		Returns the receipt URL string.
		"""
		from pgappforge.plugins.erp.industry.nonprofit.models import Donation
		from pgappforge.plugins.erp.industry.nonprofit.events import DonationAcknowledgedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		donation = session.get(Donation, donation_id)
		if donation is None:
			raise DonationNotFoundError(f"Donation {donation_id!r} not found")
		if donation.acknowledged_at is not None:
			# Receipt already generated — return existing URL
			return donation.tax_receipt_url or ""

		receipt_number = f"RCP-{donation.id[:8].upper()}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"

		# Attempt ReportForge integration; fall back to placeholder URL
		receipt_url = self._try_reportforge(donation, receipt_number)

		donation.tax_receipt_number = receipt_number
		donation.tax_receipt_url = receipt_url
		donation.acknowledged_at = datetime.now(timezone.utc)
		donation.status = "ACKNOWLEDGED"

		emit_event(
			DonationAcknowledgedEvent(
				aggregate_id=donation_id,
				aggregate_type="Donation",
				tenant_id=donation.tenant_id,
				donation_id=donation_id,
				donor_id=donation.donor_id,
				amount_cents=donation.amount_cents,
				currency=donation.currency_code,
				tax_receipt_number=receipt_number,
				tax_receipt_url=receipt_url,
			),
			session,
		)

		log.info(
			"generate_tax_receipt: donation=%r receipt=%r url=%r",
			donation_id, receipt_number, receipt_url,
		)
		return receipt_url

	@staticmethod
	def _try_reportforge(donation: Any, receipt_number: str) -> str:
		"""Attempt to call ReportForge; return placeholder URL on failure."""
		try:
			from flask import current_app
			rf = current_app.extensions.get("reportforge")
			if rf is not None:
				return rf.generate(
					template="nonprofit/tax_receipt",
					context={
						"donation_id": donation.id,
						"amount_cents": donation.amount_cents,
						"currency_code": donation.currency_code,
						"donated_at": donation.donated_at.isoformat() if donation.donated_at else "",
						"receipt_number": receipt_number,
						"designation": donation.designation or "",
					},
				)
		except Exception as exc:
			log.warning("_try_reportforge: non-fatal failure: %s", exc)
		# Fallback — downloadable stub URL
		return f"/nonprofit/receipts/{donation.id}.pdf"

	# ------------------------------------------------------------------
	# Prospect scoring
	# ------------------------------------------------------------------

	def score_major_gift_prospects(
		self,
		*,
		tenant_id: str,
		min_capacity_cents: int = 10_000_00,
		session: Any,
	) -> list[dict]:
		"""Score donors by giving history, capacity, engagement, and recency.

		Scoring dimensions (each 0–25 points, total 0–100):
		  - capacity:   largest_gift_cents relative to min_capacity_cents
		  - history:    gift_count (capped at 25)
		  - recency:    days since last_gift_date (more recent = higher score)
		  - engagement: lifetime_giving_cents / min_capacity_cents (capped)

		Returns list of dicts sorted by total_score desc, only donors with
		lifetime_giving_cents >= min_capacity_cents / 10 to avoid noise.
		"""
		from pgappforge.plugins.erp.industry.nonprofit.models import Donor

		floor_cents = min_capacity_cents // 10
		donors = session.execute(
			select(Donor).where(
				Donor.tenant_id == tenant_id,
				Donor.status == "ACTIVE",
				Donor.lifetime_giving_cents >= floor_cents,
			)
		).scalars().all()

		today = date.today()
		results: list[dict] = []

		for donor in donors:
			# Capacity score (0–25): largest gift as % of target
			capacity_ratio = min(1.0, (donor.largest_gift_cents or 0) / max(min_capacity_cents, 1))
			capacity_score = round(capacity_ratio * 25, 1)

			# History score (0–25): gift count capped at 25
			history_score = min(25.0, float(donor.gift_count or 0))

			# Recency score (0–25): gifts within 365 days score full; decay linearly
			if donor.last_gift_date:
				days_since = (today - donor.last_gift_date).days
				recency_score = max(0.0, 25.0 - (days_since / 365) * 25.0)
			else:
				recency_score = 0.0

			# Engagement score (0–25): lifetime giving relative to target
			engagement_ratio = min(1.0, (donor.lifetime_giving_cents or 0) / max(min_capacity_cents, 1))
			engagement_score = round(engagement_ratio * 25, 1)

			total_score = round(capacity_score + history_score + recency_score + engagement_score, 1)

			results.append({
				"donor_id": donor.id,
				"donor_number": donor.donor_number,
				"giving_level": donor.giving_level,
				"lifetime_giving_cents": donor.lifetime_giving_cents,
				"largest_gift_cents": donor.largest_gift_cents,
				"gift_count": donor.gift_count,
				"last_gift_date": donor.last_gift_date.isoformat() if donor.last_gift_date else None,
				"scores": {
					"capacity": capacity_score,
					"history": history_score,
					"recency": round(recency_score, 1),
					"engagement": engagement_score,
				},
				"total_score": total_score,
				"is_major_prospect": total_score >= 60.0,
			})

		results.sort(key=lambda d: d["total_score"], reverse=True)
		return results

	# ------------------------------------------------------------------
	# NPOProgram impact
	# ------------------------------------------------------------------

	def calculate_program_impact(self, program_id: str, session: Any) -> dict:
		"""Return program impact summary.

		Returns::

		    {
		        "program_id": "...",
		        "program_name": "...",
		        "beneficiaries_served": 1234,
		        "target_beneficiaries": 1500,
		        "beneficiaries_pct": 82.3,
		        "cost_per_beneficiary_cents": 4500,
		        "budget_utilisation_pct": 67.2,
		        "outcomes_achieved": 3,
		        "outcomes_total": 5,
		        "measurements": [...],
		    }
		"""
		from pgappforge.plugins.erp.industry.nonprofit.models import ImpactMeasurement, NPOProgram

		program = session.get(NPOProgram, program_id)
		if program is None:
			raise ProgramNotFoundError(f"NPOProgram {program_id!r} not found")

		measurements = session.execute(
			select(ImpactMeasurement)
			.where(ImpactMeasurement.program_id == program_id)
			.order_by(ImpactMeasurement.measurement_date.desc())
		).scalars().all()

		outcomes_achieved = sum(
			1 for m in measurements if m.actual_value >= m.target_value
		)

		beneficiaries = program.actual_beneficiaries or 0
		target = program.target_beneficiaries or 0
		beneficiaries_pct = round((beneficiaries / target * 100), 1) if target else None

		budget = program.budget_cents or 0
		spent = program.spent_cents or 0
		budget_util = round((spent / budget * 100), 1) if budget else None

		cost_per_beneficiary = (spent // beneficiaries) if beneficiaries else None

		return {
			"program_id": program_id,
			"program_code": program.program_code,
			"program_name": program.program_name,
			"status": program.status,
			"budget_cents": budget,
			"spent_cents": spent,
			"budget_utilisation_pct": budget_util,
			"beneficiaries_served": beneficiaries,
			"target_beneficiaries": target,
			"beneficiaries_pct": beneficiaries_pct,
			"cost_per_beneficiary_cents": cost_per_beneficiary,
			"outcomes_achieved": outcomes_achieved,
			"outcomes_total": len(measurements),
			"measurements": [
				{
					"measurement_id": m.id,
					"metric_name": m.metric_name,
					"metric_unit": m.metric_unit,
					"target_value": str(m.target_value),
					"actual_value": str(m.actual_value),
					"measurement_date": m.measurement_date.isoformat(),
					"achieved": m.actual_value >= m.target_value,
				}
				for m in measurements
			],
		}

	# ------------------------------------------------------------------
	# LYBUNT analysis
	# ------------------------------------------------------------------

	def run_lybunt_analysis(self, *, tenant_id: str, year: int, session: Any) -> list[dict]:
		"""Return donors who gave last year but have not yet given this year.

		LYBUNT = Last Year But Unfortunately Not This Year.
		This is the primary donor retention metric for nonprofits.

		Criteria:
		  - Has a CLEARED or ACKNOWLEDGED donation in (year-1)
		  - Has NO donation (any status except REVERSED/FAILED) in (year)

		Returns a list of dicts, sorted by last year's total giving desc.
		"""
		from pgappforge.plugins.erp.industry.nonprofit.models import Donation, Donor

		# Donors who gave last year
		last_year_start = date(year - 1, 1, 1)
		last_year_end = date(year - 1, 12, 31)

		gave_last_year_subq = (
			select(Donation.donor_id)
			.where(
				Donation.tenant_id == tenant_id,
				Donation.donated_at >= datetime(year - 1, 1, 1, tzinfo=timezone.utc),
				Donation.donated_at <= datetime(year - 1, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
				Donation.status.in_(["CLEARED", "ACKNOWLEDGED"]),
			)
			.distinct()
		)

		# Donors who have given this year
		gave_this_year_subq = (
			select(Donation.donor_id)
			.where(
				Donation.tenant_id == tenant_id,
				Donation.donated_at >= datetime(year, 1, 1, tzinfo=timezone.utc),
				Donation.status.notin_(["REVERSED", "FAILED"]),
			)
			.distinct()
		)

		# LYBUNT = gave last year AND NOT gave this year
		lybunt_donors = session.execute(
			select(Donor).where(
				Donor.tenant_id == tenant_id,
				Donor.id.in_(gave_last_year_subq),
				Donor.id.notin_(gave_this_year_subq),
				Donor.do_not_contact.is_(False),
			)
		).scalars().all()

		# Fetch last year's totals per donor for sorting
		last_year_totals_rows = session.execute(
			select(
				Donation.donor_id,
				func.sum(Donation.amount_cents).label("total_cents"),
				func.count(Donation.id).label("gift_count"),
			)
			.where(
				Donation.tenant_id == tenant_id,
				Donation.donated_at >= datetime(year - 1, 1, 1, tzinfo=timezone.utc),
				Donation.donated_at <= datetime(year - 1, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
				Donation.status.in_(["CLEARED", "ACKNOWLEDGED"]),
			)
			.group_by(Donation.donor_id)
		).all()
		totals_by_donor = {r.donor_id: r for r in last_year_totals_rows}

		results = []
		for donor in lybunt_donors:
			totals = totals_by_donor.get(donor.id)
			results.append({
				"donor_id": donor.id,
				"donor_number": donor.donor_number,
				"giving_level": donor.giving_level,
				"last_gift_date": donor.last_gift_date.isoformat() if donor.last_gift_date else None,
				"lifetime_giving_cents": donor.lifetime_giving_cents,
				f"year_{year - 1}_total_cents": totals.total_cents if totals else 0,
				f"year_{year - 1}_gift_count": totals.gift_count if totals else 0,
				"preferred_payment_method": donor.preferred_payment_method,
				"assigned_relationship_manager_id": donor.assigned_relationship_manager_id,
			})

		results.sort(
			key=lambda d: d.get(f"year_{year - 1}_total_cents", 0),
			reverse=True,
		)
		return results

	# ------------------------------------------------------------------
	# Grant pipeline
	# ------------------------------------------------------------------

	def forecast_grant_pipeline(self, *, tenant_id: str, session: Any) -> dict:
		"""Return expected grants grouped by quarter based on program end dates.

		Uses active programs with budget_cents as a proxy for expected grant
		disbursements.  A proper Grant model should be added for full pipeline
		tracking; this method provides a budget-based approximation.

		Returns::

		    {
		        "quarters": {
		            "2026-Q1": {"expected_cents": 12000000, "program_count": 3},
		            ...
		        },
		        "total_pipeline_cents": 48000000,
		    }
		"""
		from pgappforge.plugins.erp.industry.nonprofit.models import NPOProgram

		programs = session.execute(
			select(NPOProgram).where(
				NPOProgram.tenant_id == tenant_id,
				NPOProgram.status.in_(["ACTIVE", "PLANNED"]),
				NPOProgram.end_date.isnot(None),
			)
		).scalars().all()

		quarters: dict[str, dict] = {}
		for program in programs:
			if program.end_date is None:
				continue
			q = f"{program.end_date.year}-Q{(program.end_date.month - 1) // 3 + 1}"
			if q not in quarters:
				quarters[q] = {"expected_cents": 0, "program_count": 0}
			remaining = max(0, (program.budget_cents or 0) - (program.spent_cents or 0))
			quarters[q]["expected_cents"] += remaining
			quarters[q]["program_count"] += 1

		total = sum(v["expected_cents"] for v in quarters.values())
		sorted_quarters = dict(sorted(quarters.items()))

		return {
			"tenant_id": tenant_id,
			"quarters": sorted_quarters,
			"total_pipeline_cents": total,
		}

	# ------------------------------------------------------------------
	# Pledges
	# ------------------------------------------------------------------

	def create_pledge(
		self,
		*,
		tenant_id: str,
		donor_id: str,
		total_amount_cents: int,
		installments: int,
		start_date: date,
		campaign_id: str | None = None,
		designation: str | None = None,
		session: Any,
	) -> dict:
		"""Create a multi-installment pledge as individual Donation rows.

		Each installment is created with status=PENDING and is_recurring=True.
		Returns a pledge summary dict with all installment ids.

		Raises DonorNotFoundError if donor_id not found.
		"""
		from pgappforge.plugins.erp.industry.nonprofit.models import Donation, Donor

		donor = session.get(Donor, donor_id)
		if donor is None:
			raise DonorNotFoundError(f"Donor {donor_id!r} not found")

		if installments < 1:
			raise NonprofitServiceError("installments must be >= 1")

		pledge_id = str(uuid.uuid4())
		installment_cents = total_amount_cents // installments
		remainder_cents = total_amount_cents - (installment_cents * installments)

		from dateutil.relativedelta import relativedelta  # type: ignore[import]
		installment_rows: list[dict] = []
		donation_ids: list[str] = []

		for i in range(installments):
			amount = installment_cents + (remainder_cents if i == 0 else 0)
			due_date = start_date + relativedelta(months=i)
			donation = Donation(
				tenant_id=tenant_id,
				donor_id=donor_id,
				campaign_id=campaign_id,
				amount_cents=amount,
				currency_code="USD",
				functional_amount_cents=amount,
				designation=designation,
				is_recurring=True,
				recurring_frequency="MONTHLY",
				payment_reference=f"PLEDGE-{pledge_id[:8].upper()}-{i + 1:03d}",
				status="PENDING",
				donated_at=datetime(due_date.year, due_date.month, due_date.day, tzinfo=timezone.utc),
			)
			session.add(donation)
			session.flush()
			donation_ids.append(donation.id)
			installment_rows.append({
				"installment": i + 1,
				"donation_id": donation.id,
				"amount_cents": amount,
				"due_date": due_date.isoformat(),
				"status": "PENDING",
			})

		log.info(
			"create_pledge: donor=%r total=%d¢ installments=%d pledge=%r",
			donor_id, total_amount_cents, installments, pledge_id,
		)
		return {
			"pledge_id": pledge_id,
			"donor_id": donor_id,
			"total_amount_cents": total_amount_cents,
			"installments": installments,
			"start_date": start_date.isoformat(),
			"campaign_id": campaign_id,
			"designation": designation,
			"donation_ids": donation_ids,
			"installment_schedule": installment_rows,
		}


__all__ = [
	"NonprofitService",
	"NonprofitServiceError",
	"DonorNotFoundError",
	"DonationNotFoundError",
	"ProgramNotFoundError",
	"DonationAlreadyAcknowledgedError",
]
