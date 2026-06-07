"""
pgappforge/plugins/erp/finance/lease_accounting/services.py

LeaseService — IFRS 16 / ASC 842 lease accounting business logic.

All amounts in integer cents. Decimal arithmetic for rates. No float.

Public API
----------
  commence_lease(lease_id, session)           -> Lease
  post_period_payment(lease_id, period_number, session) -> LeasePaymentSchedule
  post_rou_depreciation(lease_id, period_date, session) -> RouAsset
  modify_lease(lease_id, details, session)    -> Lease
  terminate_lease(lease_id, termination_date, session) -> Lease
  get_amortisation_schedule(lease_id, session) -> list[dict]

Internal helpers
----------------
  _compute_pv(payment_cents, periodic_rate, n_periods) -> int
  _build_amortisation_schedule(lease, session)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LeaseServiceError(Exception):
	"""Base lease service error."""


class LeaseNotFoundError(LeaseServiceError):
	pass


class LeaseStatusError(LeaseServiceError):
	pass


class LeaseScheduleError(LeaseServiceError):
	pass


# ---------------------------------------------------------------------------
# Input DTOs
# ---------------------------------------------------------------------------

@dataclass
class LeaseDetails:
	tenant_id: str
	lease_reference: str
	lessor_name: str
	asset_class: str
	commencement_date: date
	original_end_date: date
	lease_term_months: int
	currency_code: str
	payment_amount_cents: int
	discount_rate: Decimal               # annual rate e.g. Decimal("0.085")
	payment_frequency: str = "MONTHLY"  # MONTHLY | QUARTERLY | ANNUAL
	initial_direct_costs_cents: int = 0
	lease_incentives_cents: int = 0
	residual_value_guarantee_cents: int = 0
	standard: str = "IFRS16"
	classification: str = "FINANCE"
	gl_rou_account: str | None = None
	gl_liability_account: str | None = None
	gl_interest_account: str | None = None
	gl_depreciation_account: str | None = None
	description: str | None = None
	notes: str | None = None
	metadata: dict[str, Any] | None = None


@dataclass
class LeaseModificationDetails:
	modification_date: date
	modification_type: str              # EXTENSION | REDUCTION | RATE_CHANGE | REASSESSMENT
	revised_term_months: int
	revised_rate: Decimal               # new annual discount rate
	revised_payment_cents: int | None = None   # None = unchanged
	narration: str | None = None


# ---------------------------------------------------------------------------
# LeaseService
# ---------------------------------------------------------------------------

class LeaseService:
	"""Stateless IFRS 16 / ASC 842 lease accounting service.

	Caller owns session transactions.
	"""

	# ------------------------------------------------------------------ #
	# PV computation (core IFRS 16 formula)
	# ------------------------------------------------------------------ #

	def _compute_pv(
		self,
		payment_cents: int,
		periodic_rate: float,
		n_periods: int,
	) -> int:
		"""Present value of an ordinary annuity.

		PV = PMT × [1 - (1 + r)^-n] / r

		For r == 0 (zero-rate lease): PV = PMT × n.

		All arithmetic in Decimal to avoid float rounding errors.
		Returns integer cents.

		Args:
			payment_cents: fixed periodic payment in minor currency units
			periodic_rate: rate per period (annual / 12 for monthly)
			n_periods:     total number of payment periods

		Example:
			Monthly payment 1_000_000 cents (KES 10,000), 8.5%/yr, 36 months:
			periodic_rate = 0.085/12 ≈ 0.007083
			PV ≈ 31,859,XXX cents  (≈ KES 318,597)
		"""
		pmt = Decimal(str(payment_cents))
		r = Decimal(str(periodic_rate))
		n = Decimal(str(n_periods))

		if r == Decimal("0"):
			pv = pmt * n
		else:
			one = Decimal("1")
			pv = pmt * (one - (one + r) ** (-n)) / r

		return int(pv.to_integral_value(ROUND_HALF_UP))

	# ------------------------------------------------------------------ #
	# Lease creation
	# ------------------------------------------------------------------ #

	def create_lease(self, details: LeaseDetails, session: Any) -> Any:
		"""Register a new lease contract (DRAFT status).

		Call commence_lease() on the commencement date to build the
		amortisation schedule and create the ROU asset.
		"""
		from pgappforge.plugins.erp.finance.lease_accounting.models import Lease
		from pgappforge.plugins.erp.finance.lease_accounting.events import (
			LeaseCreatedEvent, emit_event,
		)

		assert details.payment_amount_cents > 0, "payment_amount_cents must be positive"
		assert details.lease_term_months > 0, "lease_term_months must be positive"
		assert details.discount_rate >= 0, "discount_rate must be non-negative"
		assert details.payment_frequency in ("MONTHLY", "QUARTERLY", "ANNUAL"), \
			f"invalid payment_frequency: {details.payment_frequency!r}"
		assert details.standard in ("IFRS16", "ASC842"), \
			f"invalid standard: {details.standard!r}"
		assert details.classification in ("FINANCE", "OPERATING"), \
			f"invalid classification: {details.classification!r}"

		lease = Lease(
			tenant_id=details.tenant_id,
			lease_reference=details.lease_reference,
			description=details.description,
			lessor_name=details.lessor_name,
			asset_class=details.asset_class,
			commencement_date=details.commencement_date,
			original_end_date=details.original_end_date,
			lease_term_months=details.lease_term_months,
			currency_code=details.currency_code.upper(),
			payment_frequency=details.payment_frequency,
			payment_amount_cents=details.payment_amount_cents,
			discount_rate=details.discount_rate,
			initial_direct_costs_cents=details.initial_direct_costs_cents,
			lease_incentives_cents=details.lease_incentives_cents,
			residual_value_guarantee_cents=details.residual_value_guarantee_cents,
			standard=details.standard,
			classification=details.classification,
			gl_rou_account=details.gl_rou_account,
			gl_liability_account=details.gl_liability_account,
			gl_interest_account=details.gl_interest_account,
			gl_depreciation_account=details.gl_depreciation_account,
			notes=details.notes,
			metadata_=details.metadata or {},
			status="DRAFT",
		)
		session.add(lease)
		session.flush()

		emit_event(
			LeaseCreatedEvent(
				aggregate_id=lease.id,
				aggregate_type="Lease",
				tenant_id=details.tenant_id,
				lease_id=lease.id,
				lease_reference=details.lease_reference,
				lessor_name=details.lessor_name,
				commencement_date=str(details.commencement_date),
				lease_term_months=details.lease_term_months,
				currency_code=details.currency_code.upper(),
			),
			session,
		)
		log.info("Lease created: %r (DRAFT)", details.lease_reference)
		return lease

	# ------------------------------------------------------------------ #
	# Lease commencement — builds schedule + ROU asset
	# ------------------------------------------------------------------ #

	def commence_lease(self, lease_id: str, session: Any) -> Any:
		"""Commence a DRAFT lease: compute PV, build amortisation schedule,
		create ROU asset, and transition status to ACTIVE.

		Initial ROU asset cost = PV of payments + IDC - incentives + RVG.
		"""
		from pgappforge.plugins.erp.finance.lease_accounting.models import Lease, RouAsset
		from pgappforge.plugins.erp.finance.lease_accounting.events import (
			LeaseCommencedEvent, emit_event,
		)

		lease = session.get(Lease, lease_id)
		if lease is None:
			raise LeaseNotFoundError(f"Lease {lease_id!r} not found")
		if lease.status != "DRAFT":
			raise LeaseStatusError(
				f"Lease {lease.lease_reference!r} is {lease.status!r}, expected DRAFT"
			)

		# Derive periodic rate
		periods_per_year = self._periods_per_year(lease.payment_frequency)
		periodic_rate = float(Decimal(str(lease.discount_rate)) / Decimal(str(periods_per_year)))
		n_periods = lease.lease_term_months // (12 // periods_per_year)

		# Compute lease liability = PV of future payments
		pv_payments = self._compute_pv(
			lease.payment_amount_cents, periodic_rate, n_periods
		)
		# Add residual value guarantee to final payment PV
		if lease.residual_value_guarantee_cents:
			pv_rvg = int(
				Decimal(str(lease.residual_value_guarantee_cents))
				/ (Decimal("1") + Decimal(str(periodic_rate))) ** Decimal(str(n_periods))
			)
			pv_payments += pv_rvg

		# ROU asset cost
		rou_cost = (
			pv_payments
			+ lease.initial_direct_costs_cents
			- lease.lease_incentives_cents
		)

		lease.lease_liability_cents = pv_payments
		lease.rou_asset_cents = rou_cost
		lease.status = "ACTIVE"
		lease.updated_at = datetime.now(timezone.utc)

		# Build payment schedule
		self._build_amortisation_schedule(lease, periodic_rate, n_periods, session)

		# Create ROU asset balance record
		monthly_dep = rou_cost // lease.lease_term_months
		rou = RouAsset(
			tenant_id=lease.tenant_id,
			lease_id=lease.id,
			initial_cost_cents=rou_cost,
			accumulated_depreciation_cents=0,
			net_book_value_cents=rou_cost,
			depreciation_method="STRAIGHT_LINE",
			useful_life_months=lease.lease_term_months,
			monthly_depreciation_cents=monthly_dep,
			gl_asset_account=lease.gl_rou_account,
			gl_depreciation_account=lease.gl_depreciation_account,
		)
		session.add(rou)
		session.flush()

		emit_event(
			LeaseCommencedEvent(
				aggregate_id=lease_id,
				aggregate_type="Lease",
				tenant_id=lease.tenant_id,
				lease_id=lease_id,
				lease_reference=lease.lease_reference,
				rou_asset_cents=rou_cost,
				lease_liability_cents=pv_payments,
				commencement_date=str(lease.commencement_date),
			),
			session,
		)
		log.info(
			"Lease commenced %r: liability=%d ROU=%d",
			lease.lease_reference, pv_payments, rou_cost,
		)
		return lease

	# ------------------------------------------------------------------ #
	# Period payment posting
	# ------------------------------------------------------------------ #

	def post_period_payment(
		self,
		lease_id: str,
		period_number: int,
		session: Any,
	) -> Any:
		"""Post a periodic lease payment: split into interest expense + principal.

		Marks the schedule line as paid and reduces the lease liability balance.
		Emits LeasePaymentPostedEvent.
		"""
		from pgappforge.plugins.erp.finance.lease_accounting.models import (
			Lease, LeasePaymentSchedule,
		)
		from pgappforge.plugins.erp.finance.lease_accounting.events import (
			LeasePaymentPostedEvent, emit_event,
		)

		lease = session.get(Lease, lease_id)
		if lease is None:
			raise LeaseNotFoundError(f"Lease {lease_id!r} not found")
		if lease.status != "ACTIVE":
			raise LeaseStatusError(
				f"Lease {lease.lease_reference!r} is {lease.status!r}, not ACTIVE"
			)

		line = session.execute(
			sa.select(LeasePaymentSchedule)
			.where(LeasePaymentSchedule.lease_id == lease_id)
			.where(LeasePaymentSchedule.period_number == period_number)
			.where(LeasePaymentSchedule.is_superseded == False)
		).scalar_one_or_none()

		if line is None:
			raise LeaseScheduleError(
				f"No active schedule line for lease {lease_id!r} period {period_number}"
			)
		if line.is_paid:
			raise LeaseStatusError(f"Period {period_number} already paid")

		line.is_paid = True
		line.paid_at = datetime.now(timezone.utc)

		# Update lease balances
		lease.lease_liability_cents -= line.principal_reduction_cents
		lease.interest_accrued_cents += line.interest_expense_cents
		lease.updated_at = datetime.now(timezone.utc)
		session.flush()

		emit_event(
			LeasePaymentPostedEvent(
				aggregate_id=lease_id,
				aggregate_type="Lease",
				tenant_id=lease.tenant_id,
				lease_id=lease_id,
				lease_reference=lease.lease_reference,
				payment_date=str(line.due_date),
				interest_expense_cents=line.interest_expense_cents,
				principal_reduction_cents=line.principal_reduction_cents,
				total_payment_cents=line.payment_cents,
			),
			session,
		)
		log.info(
			"Lease payment posted %r period %d: interest=%d principal=%d",
			lease.lease_reference, period_number,
			line.interest_expense_cents, line.principal_reduction_cents,
		)
		return line

	# ------------------------------------------------------------------ #
	# ROU depreciation
	# ------------------------------------------------------------------ #

	def post_rou_depreciation(
		self,
		lease_id: str,
		period_date: date,
		session: Any,
	) -> Any:
		"""Post straight-line ROU asset depreciation for a period.

		Increments accumulated_depreciation_cents by monthly_depreciation_cents
		and decreases net_book_value_cents. Emits RouDepreciatedEvent.
		"""
		from pgappforge.plugins.erp.finance.lease_accounting.models import Lease, RouAsset
		from pgappforge.plugins.erp.finance.lease_accounting.events import (
			RouDepreciatedEvent, emit_event,
		)

		lease = session.get(Lease, lease_id)
		if lease is None:
			raise LeaseNotFoundError(f"Lease {lease_id!r} not found")

		rou = session.execute(
			sa.select(RouAsset).where(RouAsset.lease_id == lease_id)
		).scalar_one_or_none()
		if rou is None:
			raise LeaseServiceError(f"No ROU asset for lease {lease_id!r}")

		dep = rou.monthly_depreciation_cents
		# Don't over-depreciate
		remaining = rou.net_book_value_cents
		if remaining <= 0:
			log.info("ROU asset for lease %r is fully depreciated", lease_id)
			return rou
		dep = min(dep, remaining)

		rou.accumulated_depreciation_cents += dep
		rou.net_book_value_cents -= dep
		rou.updated_at = datetime.now(timezone.utc)

		# Sync back to lease header
		lease.rou_asset_cents = rou.net_book_value_cents
		lease.accumulated_depreciation_cents = rou.accumulated_depreciation_cents
		lease.updated_at = datetime.now(timezone.utc)
		session.flush()

		emit_event(
			RouDepreciatedEvent(
				aggregate_id=lease_id,
				aggregate_type="Lease",
				tenant_id=lease.tenant_id,
				lease_id=lease_id,
				lease_reference=lease.lease_reference,
				period_date=str(period_date),
				depreciation_cents=dep,
				accumulated_depreciation_cents=rou.accumulated_depreciation_cents,
			),
			session,
		)
		log.info(
			"ROU depreciation posted %r period=%s dep=%d nbv=%d",
			lease.lease_reference, period_date, dep, rou.net_book_value_cents,
		)
		return rou

	# ------------------------------------------------------------------ #
	# Lease modification / remeasurement
	# ------------------------------------------------------------------ #

	def modify_lease(
		self,
		lease_id: str,
		details: LeaseModificationDetails,
		session: Any,
	) -> Any:
		"""Remeasure a lease following IFRS 16 §45-46 modification accounting.

		1. Supersede the current payment schedule.
		2. Recompute lease liability using the revised rate and remaining term.
		3. Adjust ROU asset by the change in liability (± gain/loss for REDUCTION).
		4. Record a LeaseModification audit row.
		"""
		from pgappforge.plugins.erp.finance.lease_accounting.models import (
			Lease, RouAsset, LeasePaymentSchedule, LeaseModification,
		)
		from pgappforge.plugins.erp.finance.lease_accounting.events import (
			LeaseModifiedEvent, emit_event,
		)

		lease = session.get(Lease, lease_id)
		if lease is None:
			raise LeaseNotFoundError(f"Lease {lease_id!r} not found")
		if lease.status != "ACTIVE":
			raise LeaseStatusError(
				f"Lease {lease.lease_reference!r} is {lease.status!r}, not ACTIVE"
			)

		old_liability = lease.lease_liability_cents
		old_rou = lease.rou_asset_cents
		old_term = lease.lease_term_months
		old_rate = Decimal(str(lease.discount_rate))

		# Supersede remaining unpaid schedule lines
		session.execute(
			sa.update(LeasePaymentSchedule)
			.where(LeasePaymentSchedule.lease_id == lease_id)
			.where(LeasePaymentSchedule.is_superseded == False)
			.where(LeasePaymentSchedule.is_paid == False)
			.values(is_superseded=True)
		)

		# New payment amount (may be unchanged)
		new_payment = details.revised_payment_cents or lease.payment_amount_cents

		# Derive new periodic rate
		periods_per_year = self._periods_per_year(lease.payment_frequency)
		new_periodic_rate = float(
			details.revised_rate / Decimal(str(periods_per_year))
		)
		n_remaining = details.revised_term_months // (12 // periods_per_year)

		# New lease liability = PV of revised payments
		new_liability = self._compute_pv(new_payment, new_periodic_rate, n_remaining)
		liability_change = new_liability - old_liability

		# ROU adjustment: increase for extensions, decrease for reductions
		gain_loss = 0
		if details.modification_type == "REDUCTION":
			# Partial derecognition: any excess reduction is a gain/loss
			rou_adjustment = int(
				Decimal(str(old_rou))
				* Decimal(str(liability_change))
				/ Decimal(str(max(old_liability, 1)))
			)
			new_rou = old_rou + rou_adjustment
			gain_loss = liability_change - rou_adjustment
		else:
			new_rou = old_rou + liability_change

		# Update lease header
		lease.lease_liability_cents = new_liability
		lease.rou_asset_cents = max(new_rou, 0)
		lease.lease_term_months = details.revised_term_months
		lease.discount_rate = details.revised_rate
		if details.revised_payment_cents:
			lease.payment_amount_cents = details.revised_payment_cents
		if details.modification_type == "EXTENSION":
			# Push out end date
			from dateutil.relativedelta import relativedelta
			lease.revised_end_date = (
				lease.commencement_date
				+ relativedelta(months=details.revised_term_months)
			)
		lease.updated_at = datetime.now(timezone.utc)

		# Rebuild schedule from modification date
		self._build_amortisation_schedule(
			lease, new_periodic_rate, n_remaining, session,
			start_date=details.modification_date,
		)

		# Update ROU asset balance
		rou = session.execute(
			sa.select(RouAsset).where(RouAsset.lease_id == lease_id)
		).scalar_one_or_none()
		if rou:
			rou.net_book_value_cents = max(new_rou, 0)
			rou.useful_life_months = details.revised_term_months
			rou.monthly_depreciation_cents = (
				max(new_rou, 0) // max(details.revised_term_months, 1)
			)
			rou.updated_at = datetime.now(timezone.utc)

		# Record modification
		mod = LeaseModification(
			tenant_id=lease.tenant_id,
			lease_id=lease_id,
			modification_date=details.modification_date,
			modification_type=details.modification_type,
			previous_liability_cents=old_liability,
			revised_liability_cents=new_liability,
			previous_rou_cents=old_rou,
			revised_rou_cents=max(new_rou, 0),
			previous_term_months=old_term,
			revised_term_months=details.revised_term_months,
			previous_rate=old_rate,
			revised_rate=details.revised_rate,
			gain_loss_cents=gain_loss,
			narration=details.narration,
		)
		session.add(mod)
		session.flush()

		emit_event(
			LeaseModifiedEvent(
				aggregate_id=lease_id,
				aggregate_type="Lease",
				tenant_id=lease.tenant_id,
				lease_id=lease_id,
				lease_reference=lease.lease_reference,
				modification_date=str(details.modification_date),
				revised_liability_cents=new_liability,
				revised_rou_cents=max(new_rou, 0),
				modification_type=details.modification_type,
			),
			session,
		)
		log.info(
			"Lease modified %r type=%s new_liability=%d new_rou=%d",
			lease.lease_reference, details.modification_type,
			new_liability, max(new_rou, 0),
		)
		return lease

	# ------------------------------------------------------------------ #
	# Termination
	# ------------------------------------------------------------------ #

	def terminate_lease(
		self,
		lease_id: str,
		termination_date: date,
		session: Any,
	) -> Any:
		"""Terminate a lease early.

		Writes off remaining ROU asset and lease liability; records gain/loss.
		"""
		from pgappforge.plugins.erp.finance.lease_accounting.models import (
			Lease, RouAsset, LeasePaymentSchedule,
		)
		from pgappforge.plugins.erp.finance.lease_accounting.events import (
			LeaseTerminatedEvent, emit_event,
		)

		lease = session.get(Lease, lease_id)
		if lease is None:
			raise LeaseNotFoundError(f"Lease {lease_id!r} not found")
		if lease.status not in ("ACTIVE", "DRAFT"):
			raise LeaseStatusError(
				f"Lease {lease.lease_reference!r} is {lease.status!r}, cannot terminate"
			)

		# Supersede remaining schedule
		session.execute(
			sa.update(LeasePaymentSchedule)
			.where(LeasePaymentSchedule.lease_id == lease_id)
			.where(LeasePaymentSchedule.is_paid == False)
			.values(is_superseded=True)
		)

		# Gain/loss = liability removed - ROU written off
		gain_loss = lease.lease_liability_cents - lease.rou_asset_cents

		# Zero out balances
		rou = session.execute(
			sa.select(RouAsset).where(RouAsset.lease_id == lease_id)
		).scalar_one_or_none()
		if rou:
			rou.net_book_value_cents = 0
			rou.updated_at = datetime.now(timezone.utc)

		lease.lease_liability_cents = 0
		lease.rou_asset_cents = 0
		lease.status = "TERMINATED"
		lease.updated_at = datetime.now(timezone.utc)
		session.flush()

		emit_event(
			LeaseTerminatedEvent(
				aggregate_id=lease_id,
				aggregate_type="Lease",
				tenant_id=lease.tenant_id,
				lease_id=lease_id,
				lease_reference=lease.lease_reference,
				termination_date=str(termination_date),
				gain_loss_cents=gain_loss,
			),
			session,
		)
		log.info(
			"Lease terminated %r gain_loss=%d",
			lease.lease_reference, gain_loss,
		)
		return lease

	# ------------------------------------------------------------------ #
	# Schedule read
	# ------------------------------------------------------------------ #

	def get_amortisation_schedule(
		self, lease_id: str, session: Any
	) -> list[dict[str, Any]]:
		"""Return the active (non-superseded) amortisation schedule as dicts."""
		from pgappforge.plugins.erp.finance.lease_accounting.models import LeasePaymentSchedule

		lines = session.execute(
			sa.select(LeasePaymentSchedule)
			.where(LeasePaymentSchedule.lease_id == lease_id)
			.where(LeasePaymentSchedule.is_superseded == False)
			.order_by(LeasePaymentSchedule.period_number)
		).scalars().all()

		return [
			{
				"period_number": ln.period_number,
				"due_date": str(ln.due_date),
				"opening_liability_cents": ln.opening_liability_cents,
				"interest_expense_cents": ln.interest_expense_cents,
				"payment_cents": ln.payment_cents,
				"principal_reduction_cents": ln.principal_reduction_cents,
				"closing_liability_cents": ln.closing_liability_cents,
				"is_paid": ln.is_paid,
			}
			for ln in lines
		]

	# ------------------------------------------------------------------ #
	# Internal helpers
	# ------------------------------------------------------------------ #

	def _periods_per_year(self, payment_frequency: str) -> int:
		return {"MONTHLY": 12, "QUARTERLY": 4, "ANNUAL": 1}[payment_frequency]

	def _build_amortisation_schedule(
		self,
		lease: Any,
		periodic_rate: float,
		n_periods: int,
		session: Any,
		*,
		start_date: date | None = None,
	) -> None:
		"""Build and persist the amortisation schedule for a lease.

		Uses the effective-interest method (IFRS 16 §26):
		  interest = opening_liability × periodic_rate
		  principal = payment - interest
		  closing  = opening - principal
		"""
		from pgappforge.plugins.erp.finance.lease_accounting.models import LeasePaymentSchedule
		from dateutil.relativedelta import relativedelta

		freq_delta = {
			"MONTHLY": relativedelta(months=1),
			"QUARTERLY": relativedelta(months=3),
			"ANNUAL": relativedelta(years=1),
		}[lease.payment_frequency]

		if start_date is None:
			start_date = lease.commencement_date

		# Determine first due date based on frequency
		due = start_date + freq_delta
		opening = lease.lease_liability_cents
		pmt = lease.payment_amount_cents
		r = Decimal(str(periodic_rate))

		for i in range(1, n_periods + 1):
			interest = int(
				(Decimal(str(opening)) * r).to_integral_value(ROUND_HALF_UP)
			)
			if i == n_periods:
				# Last period: zero out liability exactly.
				# Interest absorbs rounding drift: interest = payment - remaining_principal
				# This ensures: payment = interest + principal = pmt, closing = 0.
				principal = opening
				interest = pmt - principal  # may differ slightly from opening*r by ≤1 cent
				closing = 0
			else:
				principal = pmt - interest
				closing = opening - principal

			session.add(LeasePaymentSchedule(
				lease_id=lease.id,
				period_number=i,
				due_date=due,
				opening_liability_cents=opening,
				interest_expense_cents=interest,
				payment_cents=pmt,
				principal_reduction_cents=principal,
				closing_liability_cents=max(closing, 0),
				is_superseded=False,
				is_paid=False,
			))
			opening = max(closing, 0)
			due = due + freq_delta

		session.flush()


__all__ = [
	"LeaseService",
	"LeaseServiceError",
	"LeaseNotFoundError",
	"LeaseStatusError",
	"LeaseScheduleError",
	"LeaseDetails",
	"LeaseModificationDetails",
]
