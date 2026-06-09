"""
pgappforge/plugins/erp/industry/real_estate/commercial/services.py

CommercialLeaseService — stateless business logic for the Commercial RE sub-plugin.

All methods accept an explicit SQLAlchemy 2.x session.
No session.commit() inside service methods — callers own the transaction boundary.

Monetary invariant: ALL amounts are integer cents throughout.

Key methods
-----------
  create_space(...)                    -> SpaceUnit
  create_commercial_lease(...)         -> CommercialLease
  get_rent_schedule(lease_id, session) -> list[dict]
  create_cam_budget(...)               -> CAMBudget
  record_cam_actual(...)               -> CAMActual
  reconcile_cam(...)                   -> CAMReconciliation
  create_lease_abstract(...)           -> LeaseAbstract
  get_lease_abstract(...)              -> dict
  submit_loi(...)                      -> LOI
  accept_loi(...)                      -> LOI
  terminate_commercial_lease(...)      -> CommercialLease
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CommercialREServiceError(Exception):
	"""Base exception for Commercial RE service errors."""


class SpaceNotFoundError(CommercialREServiceError):
	pass


class LeaseNotFoundError(CommercialREServiceError):
	pass


class LOINotFoundError(CommercialREServiceError):
	pass


class CommercialREValidationError(CommercialREServiceError):
	"""Business rule validation failure — HTTP 422."""


# ---------------------------------------------------------------------------
# CommercialLeaseService
# ---------------------------------------------------------------------------

class CommercialLeaseService:
	"""Stateless Commercial Real Estate business logic.

	Instantiate per-request or as a singleton — no instance state.
	"""

	# ------------------------------------------------------------------
	# create_space
	# ------------------------------------------------------------------

	def create_space(
		self,
		property_id: str,
		suite_code: str,
		sqft: int | None,
		unit_type: str,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	) -> Any:
		"""Create a new commercial SpaceUnit.

		Args:
			property_id: UUID of the parent re_property record.
			suite_code:  Unique suite identifier within the property (e.g. "101A").
			sqft:        Rentable square footage; None is allowed.
			unit_type:   OFFICE / RETAIL / INDUSTRIAL / STORAGE / MEDICAL.
			tenant_id:   Platform tenant UUID.
			session:     SQLAlchemy session.
			**kwargs:    Optional: floor (int), asking_rent_cents (int), status (str).

		Returns:
			SpaceUnit instance (flushed, not committed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import SpaceUnit

		assert session is not None, "session required"
		valid_types = ("OFFICE", "RETAIL", "INDUSTRIAL", "STORAGE", "MEDICAL")
		if unit_type not in valid_types:
			raise CommercialREValidationError(
				f"Invalid unit_type {unit_type!r}; expected one of {valid_types}"
			)

		space = SpaceUnit(
			tenant_id=tenant_id,
			property_id=property_id,
			suite_code=suite_code,
			sqft=sqft,
			unit_type=unit_type,
			floor=kwargs.get("floor"),
			asking_rent_cents=kwargs.get("asking_rent_cents"),
			status=kwargs.get("status", "VACANT"),
		)
		session.add(space)
		session.flush()

		log.info(
			"CommercialLeaseService.create_space: suite=%r type=%r sqft=%s property=%r",
			suite_code, unit_type, sqft, property_id,
		)
		return space

	# ------------------------------------------------------------------
	# create_commercial_lease
	# ------------------------------------------------------------------

	def create_commercial_lease(
		self,
		space_id: str,
		tenant_party_id: str,
		landlord_id: str,
		lease_type: str,
		base_rent_cents: int,
		lease_start: date | str,
		lease_end: date | str,
		tenant_id: str,
		session: Any,
		*,
		cam_estimate_cents: int = 0,
		insurance_estimate_cents: int = 0,
		tax_estimate_cents: int = 0,
		rent_schedule: list[dict] | None = None,
		options: list[dict] | None = None,
	) -> Any:
		"""Create a CommercialLease and mark the SpaceUnit as OCCUPIED.

		Emits CommercialLeaseSignedEvent.

		Args:
			space_id:                  UUID of the SpaceUnit.
			tenant_party_id:           UUID of the lessee (foundation.Party soft FK).
			landlord_id:               UUID of the lessor (foundation.Party soft FK).
			lease_type:                NNN / MODIFIED_GROSS / FULL_SERVICE / GROSS.
			base_rent_cents:           Monthly base rent in cents (must be > 0).
			lease_start:               Lease commencement date (date or ISO string).
			lease_end:                 Lease expiry date (date or ISO string).
			tenant_id:                 Platform tenant UUID.
			session:                   SQLAlchemy session.
			cam_estimate_cents:        Monthly CAM estimate in cents.
			insurance_estimate_cents:  Monthly insurance pass-through estimate in cents.
			tax_estimate_cents:        Monthly tax pass-through estimate in cents.
			rent_schedule:             Optional stepped-rent list [{period, amount_cents}].
			options:                   Optional lease option list [{type, notice_days, terms}].

		Returns:
			CommercialLease instance (flushed, not committed).

		Raises:
			SpaceNotFoundError:           Space not found.
			CommercialREValidationError:  Business rule violation.
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import (
			CommercialLease,
			SpaceUnit,
		)
		from pgappforge.plugins.erp.industry.real_estate.commercial.events import (
			CommercialLeaseSignedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert session is not None, "session required"
		assert base_rent_cents > 0, "base_rent_cents must be > 0"

		if isinstance(lease_start, str):
			lease_start = date.fromisoformat(lease_start)
		if isinstance(lease_end, str):
			lease_end = date.fromisoformat(lease_end)

		if lease_end <= lease_start:
			raise CommercialREValidationError("lease_end must be after lease_start")

		valid_types = ("NNN", "MODIFIED_GROSS", "FULL_SERVICE", "GROSS")
		if lease_type not in valid_types:
			raise CommercialREValidationError(
				f"Invalid lease_type {lease_type!r}; expected one of {valid_types}"
			)

		space = session.get(SpaceUnit, space_id)
		if space is None:
			raise SpaceNotFoundError(f"SpaceUnit {space_id!r} not found")

		lease = CommercialLease(
			tenant_id=tenant_id,
			space_id=space_id,
			tenant_party_id=tenant_party_id,
			landlord_id=landlord_id,
			lease_type=lease_type,
			base_rent_cents=int(base_rent_cents),
			cam_estimate_cents=int(cam_estimate_cents),
			insurance_estimate_cents=int(insurance_estimate_cents),
			tax_estimate_cents=int(tax_estimate_cents),
			lease_start=lease_start,
			lease_end=lease_end,
			status="ACTIVE",
			rent_schedule=rent_schedule or [],
			options=options or [],
		)
		session.add(lease)
		session.flush()

		# Mark space occupied
		space.status = "OCCUPIED"
		space.updated_at = datetime.now(timezone.utc)

		emit_event(
			CommercialLeaseSignedEvent(
				aggregate_id=lease.id,
				aggregate_type="CommercialLease",
				tenant_id=tenant_id,
				lease_id=lease.id,
				space_id=space_id,
				tenant_party_id=str(tenant_party_id or ""),
				monthly_rent_cents=lease.base_rent_cents,
			),
			session,
		)

		log.info(
			"CommercialLeaseService.create_commercial_lease: lease=%r space=%r "
			"type=%r base=%d¢/mo",
			lease.id, space_id, lease_type, base_rent_cents,
		)
		return lease

	# ------------------------------------------------------------------
	# get_rent_schedule
	# ------------------------------------------------------------------

	def get_rent_schedule(self, lease_id: str, session: Any) -> list[dict]:
		"""Expand a CommercialLease rent schedule into month-by-month entries.

		If CommercialLease.rent_schedule has entries, use them (keyed by period
		"YYYY-MM"); gaps between defined steps are filled with the last known rate.
		Otherwise generate a flat schedule at base_rent_cents for every month
		from lease_start to lease_end (inclusive).

		Returns:
			[{"period_month": "YYYY-MM", "amount_cents": int}, ...]
			Ordered chronologically from lease_start to lease_end.

		Raises:
			LeaseNotFoundError: Lease not found.
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import CommercialLease

		assert session is not None, "session required"

		lease = session.get(CommercialLease, lease_id)
		if lease is None:
			raise LeaseNotFoundError(f"CommercialLease {lease_id!r} not found")

		# Build step map: "YYYY-MM" -> amount_cents
		step_map: dict[str, int] = {}
		for entry in (lease.rent_schedule or []):
			period = entry.get("period") or entry.get("period_month", "")
			amount = int(entry.get("amount_cents", lease.base_rent_cents))
			if period:
				step_map[period] = amount

		result: list[dict] = []
		cur = lease.lease_start
		end = lease.lease_end
		current_rate = lease.base_rent_cents

		while cur <= end:
			period_key = cur.strftime("%Y-%m")
			# Update current rate if a step is defined for this period
			if period_key in step_map:
				current_rate = step_map[period_key]
			result.append({"period_month": period_key, "amount_cents": current_rate})
			# Advance one month
			_, last_day = calendar.monthrange(cur.year, cur.month)
			if cur.month == 12:
				cur = cur.replace(year=cur.year + 1, month=1, day=1)
			else:
				cur = cur.replace(month=cur.month + 1, day=1)

		return result

	# ------------------------------------------------------------------
	# create_cam_budget
	# ------------------------------------------------------------------

	def create_cam_budget(
		self,
		property_id: str,
		year: int,
		total_budget_cents: int,
		categories: dict,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Upsert the annual CAM budget for a property-year.

		Args:
			property_id:        UUID of the re_property record.
			year:               Calendar year (e.g. 2026).
			total_budget_cents: Total annual CAM budget in cents.
			categories:         Dict breakdown {maintenance, insurance, taxes, management} in cents.
			tenant_id:          Platform tenant UUID.
			session:            SQLAlchemy session.

		Returns:
			CAMBudget instance (created or updated, flushed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import CAMBudget

		assert session is not None, "session required"
		assert total_budget_cents >= 0, "total_budget_cents must be >= 0"

		existing = session.execute(
			sa.select(CAMBudget).where(
				CAMBudget.tenant_id == tenant_id,
				CAMBudget.property_id == property_id,
				CAMBudget.year == year,
			)
		).scalar_one_or_none()

		if existing is not None:
			existing.total_budget_cents = int(total_budget_cents)
			existing.categories = categories or {}
			session.flush()
			log.info(
				"CommercialLeaseService.create_cam_budget: updated property=%r year=%d total=%d¢",
				property_id, year, total_budget_cents,
			)
			return existing

		budget = CAMBudget(
			tenant_id=tenant_id,
			property_id=property_id,
			year=year,
			total_budget_cents=int(total_budget_cents),
			categories=categories or {},
		)
		session.add(budget)
		session.flush()
		log.info(
			"CommercialLeaseService.create_cam_budget: created property=%r year=%d total=%d¢",
			property_id, year, total_budget_cents,
		)
		return budget

	# ------------------------------------------------------------------
	# record_cam_actual
	# ------------------------------------------------------------------

	def record_cam_actual(
		self,
		property_id: str,
		year: int,
		total_actual_cents: int,
		categories: dict,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Upsert the actual annual CAM spend for a property-year.

		Args:
			property_id:       UUID of the re_property record.
			year:              Calendar year.
			total_actual_cents: Total actual CAM spend in cents.
			categories:        Dict breakdown in cents.
			tenant_id:         Platform tenant UUID.
			session:           SQLAlchemy session.

		Returns:
			CAMActual instance (created or updated, flushed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import CAMActual

		assert session is not None, "session required"
		assert total_actual_cents >= 0, "total_actual_cents must be >= 0"

		existing = session.execute(
			sa.select(CAMActual).where(
				CAMActual.tenant_id == tenant_id,
				CAMActual.property_id == property_id,
				CAMActual.year == year,
			)
		).scalar_one_or_none()

		if existing is not None:
			existing.total_actual_cents = int(total_actual_cents)
			existing.categories = categories or {}
			session.flush()
			log.info(
				"CommercialLeaseService.record_cam_actual: updated property=%r year=%d total=%d¢",
				property_id, year, total_actual_cents,
			)
			return existing

		actual = CAMActual(
			tenant_id=tenant_id,
			property_id=property_id,
			year=year,
			total_actual_cents=int(total_actual_cents),
			categories=categories or {},
		)
		session.add(actual)
		session.flush()
		log.info(
			"CommercialLeaseService.record_cam_actual: created property=%r year=%d total=%d¢",
			property_id, year, total_actual_cents,
		)
		return actual

	# ------------------------------------------------------------------
	# reconcile_cam
	# ------------------------------------------------------------------

	def reconcile_cam(
		self,
		property_id: str,
		year: int,
		tenant_id: str,
		session: Any,
		*,
		finalize: bool = False,
	) -> Any:
		"""Compute year-end CAM reconciliation for a property.

		Algorithm:
		  1. Read CAMBudget and CAMActual for (property_id, year).
		  2. Query all ACTIVE CommercialLeases for the property whose term
		     overlaps the calendar year.
		  3. Compute total occupied sqft = sum of SpaceUnit.sqft for those leases.
		  4. For NNN / MODIFIED_GROSS leases:
		       proration_pct      = lease.space.sqft / total_occupied_sqft
		       estimated_cents    = total_budget_cents * proration_pct
		       actual_cents       = total_actual_cents * proration_pct
		       trueup_cents       = actual_cents - estimated_cents
		     FULL_SERVICE / GROSS leases are allocated zero (landlord absorbs CAM).
		  5. Upserts CAMReconciliation.
		  6. If finalize=True: sets status=FINAL, sets reconciled_at, emits
		     CAMReconciliationFinalizedEvent.

		Returns:
			CAMReconciliation instance (flushed).

		Raises:
			CommercialREValidationError: CAMBudget or CAMActual missing for the year.
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import (
			CAMBudget,
			CAMActual,
			CAMReconciliation,
			CommercialLease,
			SpaceUnit,
		)
		from pgappforge.plugins.erp.industry.real_estate.commercial.events import (
			CAMReconciliationFinalizedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert session is not None, "session required"

		budget = session.execute(
			sa.select(CAMBudget).where(
				CAMBudget.tenant_id == tenant_id,
				CAMBudget.property_id == property_id,
				CAMBudget.year == year,
			)
		).scalar_one_or_none()
		if budget is None:
			raise CommercialREValidationError(
				f"No CAMBudget found for property={property_id!r} year={year}"
			)

		actual = session.execute(
			sa.select(CAMActual).where(
				CAMActual.tenant_id == tenant_id,
				CAMActual.property_id == property_id,
				CAMActual.year == year,
			)
		).scalar_one_or_none()
		if actual is None:
			raise CommercialREValidationError(
				f"No CAMActual found for property={property_id!r} year={year}"
			)

		# Find all ACTIVE leases overlapping the calendar year
		year_start = date(year, 1, 1)
		year_end = date(year, 12, 31)

		leases_q = (
			sa.select(CommercialLease)
			.join(SpaceUnit, CommercialLease.space_id == SpaceUnit.id)
			.where(CommercialLease.tenant_id == tenant_id)
			.where(SpaceUnit.property_id == property_id)
			.where(CommercialLease.status == "ACTIVE")
			.where(CommercialLease.lease_start <= year_end)
			.where(CommercialLease.lease_end >= year_start)
		)
		leases = session.execute(leases_q).scalars().all()

		# Compute total occupied sqft (NNN + MODIFIED_GROSS only participate in CAM)
		cam_leases = [
			l for l in leases
			if l.lease_type in ("NNN", "MODIFIED_GROSS")
		]
		space_ids = [l.space_id for l in cam_leases]
		sqft_map: dict[str, int] = {}
		if space_ids:
			spaces = session.execute(
				sa.select(SpaceUnit).where(SpaceUnit.id.in_(space_ids))
			).scalars().all()
			sqft_map = {s.id: (s.sqft or 0) for s in spaces}

		total_sqft = sum(sqft_map.values())

		allocations: list[dict] = []
		for lease in leases:
			if lease.lease_type not in ("NNN", "MODIFIED_GROSS"):
				# FULL_SERVICE / GROSS — landlord absorbs CAM
				allocations.append({
					"lease_id": lease.id,
					"lease_type": lease.lease_type,
					"proration_pct": 0.0,
					"estimated_cents": 0,
					"actual_cents": 0,
					"trueup_cents": 0,
				})
				continue

			lease_sqft = sqft_map.get(lease.space_id, 0)
			if total_sqft > 0:
				proration_pct = lease_sqft / total_sqft
			else:
				proration_pct = 0.0

			estimated_cents = int(budget.total_budget_cents * proration_pct)
			actual_cents_alloc = int(actual.total_actual_cents * proration_pct)
			trueup_cents = actual_cents_alloc - estimated_cents

			allocations.append({
				"lease_id": lease.id,
				"lease_type": lease.lease_type,
				"proration_pct": round(proration_pct, 6),
				"estimated_cents": estimated_cents,
				"actual_cents": actual_cents_alloc,
				"trueup_cents": trueup_cents,
			})

		variance = actual.total_actual_cents - budget.total_budget_cents

		# Upsert reconciliation record
		recon = session.execute(
			sa.select(CAMReconciliation).where(
				CAMReconciliation.tenant_id == tenant_id,
				CAMReconciliation.property_id == property_id,
				CAMReconciliation.year == year,
			)
		).scalar_one_or_none()

		if recon is None:
			recon = CAMReconciliation(
				tenant_id=tenant_id,
				property_id=property_id,
				year=year,
			)
			session.add(recon)

		recon.total_budgeted_cents = budget.total_budget_cents
		recon.total_actual_cents = actual.total_actual_cents
		recon.variance_cents = variance
		recon.tenant_allocations = allocations

		if finalize:
			recon.status = "FINAL"
			recon.reconciled_at = datetime.now(timezone.utc)
			emit_event(
				CAMReconciliationFinalizedEvent(
					aggregate_id=recon.id,
					aggregate_type="CAMReconciliation",
					tenant_id=tenant_id,
					property_id=property_id,
					year=year,
					variance_cents=variance,
				),
				session,
			)

		session.flush()

		log.info(
			"CommercialLeaseService.reconcile_cam: property=%r year=%d "
			"budget=%d¢ actual=%d¢ variance=%d¢ leases=%d finalize=%s",
			property_id, year, budget.total_budget_cents,
			actual.total_actual_cents, variance, len(leases), finalize,
		)
		return recon

	# ------------------------------------------------------------------
	# create_lease_abstract
	# ------------------------------------------------------------------

	def create_lease_abstract(
		self,
		lease_id: str,
		tenant_id: str,
		session: Any,
		**abstract_fields: Any,
	) -> Any:
		"""Create or replace the LeaseAbstract for a CommercialLease.

		Args:
			lease_id:        UUID of the CommercialLease.
			tenant_id:       Platform tenant UUID.
			session:         SQLAlchemy session.
			**abstract_fields: Any LeaseAbstract column values:
				commencement_date, expiry_date, rent_commencement_date,
				free_rent_months, tenant_improvement_cents, rent_steps,
				renewal_options, termination_option, exclusivity_clause,
				permitted_use, special_provisions.

		Returns:
			LeaseAbstract instance (flushed).

		Raises:
			LeaseNotFoundError: CommercialLease not found.
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import (
			CommercialLease,
			LeaseAbstract,
		)

		assert session is not None, "session required"

		lease = session.get(CommercialLease, lease_id)
		if lease is None:
			raise LeaseNotFoundError(f"CommercialLease {lease_id!r} not found")

		# Date coercion helpers
		def _coerce_date(val: Any) -> date | None:
			if val is None:
				return None
			if isinstance(val, date):
				return val
			return date.fromisoformat(str(val))

		existing = session.execute(
			sa.select(LeaseAbstract).where(LeaseAbstract.lease_id == lease_id)
		).scalar_one_or_none()

		if existing is not None:
			abstract = existing
		else:
			abstract = LeaseAbstract(tenant_id=tenant_id, lease_id=lease_id)
			session.add(abstract)

		abstract.commencement_date = _coerce_date(abstract_fields.get("commencement_date"))
		abstract.expiry_date = _coerce_date(abstract_fields.get("expiry_date"))
		abstract.rent_commencement_date = _coerce_date(abstract_fields.get("rent_commencement_date"))
		abstract.free_rent_months = int(abstract_fields.get("free_rent_months") or 0)
		abstract.tenant_improvement_cents = int(abstract_fields.get("tenant_improvement_cents") or 0)
		abstract.rent_steps = abstract_fields.get("rent_steps") or []
		abstract.renewal_options = abstract_fields.get("renewal_options") or []
		abstract.termination_option = abstract_fields.get("termination_option")
		abstract.exclusivity_clause = abstract_fields.get("exclusivity_clause")
		abstract.permitted_use = abstract_fields.get("permitted_use")
		abstract.special_provisions = abstract_fields.get("special_provisions")

		session.flush()

		log.info(
			"CommercialLeaseService.create_lease_abstract: lease=%r "
			"free_rent=%d months ti=%d¢",
			lease_id, abstract.free_rent_months, abstract.tenant_improvement_cents,
		)
		return abstract

	# ------------------------------------------------------------------
	# get_lease_abstract
	# ------------------------------------------------------------------

	def get_lease_abstract(self, lease_id: str, session: Any) -> dict:
		"""Return the LeaseAbstract for a CommercialLease as a formatted dict.

		Args:
			lease_id: UUID of the CommercialLease.
			session:  SQLAlchemy session.

		Returns:
			Dict with all abstract fields; dates formatted as ISO strings.

		Raises:
			LeaseNotFoundError: No abstract found for the lease.
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import LeaseAbstract

		assert session is not None, "session required"

		abstract = session.execute(
			sa.select(LeaseAbstract).where(LeaseAbstract.lease_id == lease_id)
		).scalar_one_or_none()

		if abstract is None:
			raise LeaseNotFoundError(
				f"No LeaseAbstract found for CommercialLease {lease_id!r}"
			)

		def _fmt(d: date | None) -> str | None:
			return d.isoformat() if d else None

		return {
			"id": abstract.id,
			"tenant_id": abstract.tenant_id,
			"lease_id": abstract.lease_id,
			"commencement_date": _fmt(abstract.commencement_date),
			"expiry_date": _fmt(abstract.expiry_date),
			"rent_commencement_date": _fmt(abstract.rent_commencement_date),
			"free_rent_months": abstract.free_rent_months,
			"tenant_improvement_cents": abstract.tenant_improvement_cents,
			"rent_steps": abstract.rent_steps or [],
			"renewal_options": abstract.renewal_options or [],
			"termination_option": abstract.termination_option,
			"exclusivity_clause": abstract.exclusivity_clause,
			"permitted_use": abstract.permitted_use,
			"special_provisions": abstract.special_provisions,
			"created_at": abstract.created_at.isoformat() if abstract.created_at else None,
		}

	# ------------------------------------------------------------------
	# submit_loi
	# ------------------------------------------------------------------

	def submit_loi(
		self,
		property_id: str,
		prospect_party_id: str,
		proposed_term_months: int,
		proposed_rent_cents: int,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	) -> Any:
		"""Create and submit a Letter of Intent.

		Sets status=SUBMITTED immediately on creation.

		Args:
			property_id:          UUID of the target property.
			prospect_party_id:    UUID of the prospective tenant (foundation.Party).
			proposed_term_months: Proposed lease term in months.
			proposed_rent_cents:  Proposed monthly rent in cents.
			tenant_id:            Platform tenant UUID.
			session:              SQLAlchemy session.
			**kwargs:             Optional: space_id, proposed_start_date,
			                       ti_requested_cents, free_rent_months,
			                       notes, expires_at.

		Returns:
			LOI instance with status=SUBMITTED (flushed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import LOI

		assert session is not None, "session required"

		proposed_start = kwargs.get("proposed_start_date")
		if isinstance(proposed_start, str):
			proposed_start = date.fromisoformat(proposed_start)

		loi = LOI(
			tenant_id=tenant_id,
			property_id=property_id,
			space_id=kwargs.get("space_id"),
			prospect_party_id=prospect_party_id,
			proposed_term_months=proposed_term_months,
			proposed_rent_cents=int(proposed_rent_cents),
			proposed_start_date=proposed_start,
			ti_requested_cents=int(kwargs.get("ti_requested_cents") or 0),
			free_rent_months=int(kwargs.get("free_rent_months") or 0),
			notes=kwargs.get("notes"),
			expires_at=kwargs.get("expires_at"),
			status="SUBMITTED",
		)
		session.add(loi)
		session.flush()

		log.info(
			"CommercialLeaseService.submit_loi: loi=%r property=%r "
			"prospect=%r rent=%d¢/mo term=%d months",
			loi.id, property_id, prospect_party_id,
			proposed_rent_cents, proposed_term_months,
		)
		return loi

	# ------------------------------------------------------------------
	# accept_loi
	# ------------------------------------------------------------------

	def accept_loi(self, loi_id: str, tenant_id: str, session: Any) -> Any:
		"""Accept a Letter of Intent.

		Sets LOI.status=ACCEPTED and emits LOIAcceptedEvent.
		The caller is responsible for converting the LOI into a CommercialLease.

		Args:
			loi_id:    UUID of the LOI.
			tenant_id: Platform tenant UUID.
			session:   SQLAlchemy session.

		Returns:
			Accepted LOI instance (flushed).

		Raises:
			LOINotFoundError:             LOI not found.
			CommercialREValidationError:  LOI is not in a valid state for acceptance.
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import LOI
		from pgappforge.plugins.erp.industry.real_estate.commercial.events import LOIAcceptedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert session is not None, "session required"

		loi = session.get(LOI, loi_id)
		if loi is None:
			raise LOINotFoundError(f"LOI {loi_id!r} not found")
		if loi.status not in ("SUBMITTED", "NEGOTIATING"):
			raise CommercialREValidationError(
				f"LOI {loi_id!r} is {loi.status!r}; must be SUBMITTED or NEGOTIATING to accept"
			)

		loi.status = "ACCEPTED"
		loi.updated_at = datetime.now(timezone.utc)
		session.flush()

		emit_event(
			LOIAcceptedEvent(
				aggregate_id=loi_id,
				aggregate_type="LOI",
				tenant_id=tenant_id,
				loi_id=loi_id,
				property_id=loi.property_id,
				prospect_party_id=str(loi.prospect_party_id),
			),
			session,
		)

		log.info(
			"CommercialLeaseService.accept_loi: loi=%r property=%r prospect=%r",
			loi_id, loi.property_id, loi.prospect_party_id,
		)
		return loi

	# ------------------------------------------------------------------
	# terminate_commercial_lease
	# ------------------------------------------------------------------

	def terminate_commercial_lease(
		self,
		lease_id: str,
		tenant_id: str,
		session: Any,
		*,
		termination_date: date | str | None = None,
	) -> Any:
		"""Terminate a CommercialLease and vacate its SpaceUnit.

		Sets CommercialLease.status=TERMINATED and SpaceUnit.status=VACANT.
		Emits SpaceVacatedEvent.

		Args:
			lease_id:         UUID of the CommercialLease.
			tenant_id:        Platform tenant UUID.
			session:          SQLAlchemy session.
			termination_date: Effective termination date; defaults to today.

		Returns:
			Updated CommercialLease instance (flushed).

		Raises:
			LeaseNotFoundError:           Lease not found.
			CommercialREValidationError:  Lease not in a terminatable state.
		"""
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import (
			CommercialLease,
			SpaceUnit,
		)
		from pgappforge.plugins.erp.industry.real_estate.commercial.events import SpaceVacatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert session is not None, "session required"

		lease = session.get(CommercialLease, lease_id)
		if lease is None:
			raise LeaseNotFoundError(f"CommercialLease {lease_id!r} not found")
		if lease.status not in ("ACTIVE", "DRAFT"):
			raise CommercialREValidationError(
				f"CommercialLease {lease_id!r} is {lease.status!r}; "
				"only ACTIVE or DRAFT leases can be terminated"
			)

		if isinstance(termination_date, str):
			termination_date = date.fromisoformat(termination_date)
		if termination_date is None:
			termination_date = date.today()

		lease.status = "TERMINATED"
		lease.lease_end = termination_date
		lease.updated_at = datetime.now(timezone.utc)

		# Vacate the space
		space = session.get(SpaceUnit, lease.space_id)
		if space is not None:
			space.status = "VACANT"
			space.updated_at = datetime.now(timezone.utc)
			property_id_for_event = str(space.property_id)
		else:
			property_id_for_event = ""

		emit_event(
			SpaceVacatedEvent(
				aggregate_id=lease.space_id,
				aggregate_type="SpaceUnit",
				tenant_id=tenant_id,
				space_id=lease.space_id,
				property_id=property_id_for_event,
			),
			session,
		)

		session.flush()

		log.info(
			"CommercialLeaseService.terminate_commercial_lease: lease=%r space=%r "
			"termination_date=%s",
			lease_id, lease.space_id, termination_date,
		)
		return lease


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

from pgappforge.plugins.workflow.engine import BPMActionRegistry  # noqa: E402


@BPMActionRegistry.register("re_com.create_space", "Create commercial space unit")
def _bpm_create_space(
	record_ctx: dict,
	session: Any,
	property_id: str = "",
	suite_code: str = "",
	sqft: int | None = None,
	unit_type: str = "OFFICE",
	**kw: Any,
) -> dict:
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = CommercialLeaseService()
		space = svc.create_space(
			property_id=property_id,
			suite_code=suite_code,
			sqft=sqft,
			unit_type=unit_type,
			tenant_id=tenant_id,
			session=session,
			**kw,
		)
		return {"status": "ok", "space_id": space.id, "suite_code": space.suite_code}
	except CommercialREServiceError as exc:
		log.warning("bpm re_com.create_space failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("re_com.reconcile_cam", "Run CAM reconciliation")
def _bpm_reconcile_cam(
	record_ctx: dict,
	session: Any,
	property_id: str = "",
	year: int = 0,
	finalize: bool = False,
	**kw: Any,
) -> dict:
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = CommercialLeaseService()
		recon = svc.reconcile_cam(
			property_id=property_id,
			year=year,
			tenant_id=tenant_id,
			session=session,
			finalize=finalize,
		)
		return {
			"status": "ok",
			"reconciliation_id": recon.id,
			"variance_cents": recon.variance_cents,
			"recon_status": recon.status,
		}
	except CommercialREServiceError as exc:
		log.warning("bpm re_com.reconcile_cam failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("re_com.submit_loi", "Submit letter of intent")
def _bpm_submit_loi(
	record_ctx: dict,
	session: Any,
	property_id: str = "",
	prospect_party_id: str = "",
	proposed_term_months: int = 0,
	proposed_rent_cents: int = 0,
	**kw: Any,
) -> dict:
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = CommercialLeaseService()
		loi = svc.submit_loi(
			property_id=property_id,
			prospect_party_id=prospect_party_id,
			proposed_term_months=proposed_term_months,
			proposed_rent_cents=proposed_rent_cents,
			tenant_id=tenant_id,
			session=session,
			**kw,
		)
		return {"status": "ok", "loi_id": loi.id, "loi_status": loi.status}
	except CommercialREServiceError as exc:
		log.warning("bpm re_com.submit_loi failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("re_com.accept_loi", "Accept LOI and trigger lease creation")
def _bpm_accept_loi(
	record_ctx: dict,
	session: Any,
	loi_id: str = "",
	**kw: Any,
) -> dict:
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = CommercialLeaseService()
		loi = svc.accept_loi(loi_id=loi_id, tenant_id=tenant_id, session=session)
		return {
			"status": "ok",
			"loi_id": loi.id,
			"loi_status": loi.status,
			"property_id": loi.property_id,
			"prospect_party_id": str(loi.prospect_party_id),
		}
	except CommercialREServiceError as exc:
		log.warning("bpm re_com.accept_loi failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = [
	"CommercialLeaseService",
	"CommercialREServiceError",
	"SpaceNotFoundError",
	"LeaseNotFoundError",
	"LOINotFoundError",
	"CommercialREValidationError",
]
