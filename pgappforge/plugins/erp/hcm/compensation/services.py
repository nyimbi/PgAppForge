from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from pgappforge.plugins.workflow.engine import BPMActionRegistry
from pgappforge.plugins.erp.hcm.compensation.events import (
	AllowanceAssignedEvent,
	AllowanceRevokedEvent,
	CompensationPackageCreatedEvent,
	CompensationPackageRevisedEvent,
	DeductionAssignedEvent,
	ReviewCycleApprovedEvent,
)
from pgappforge.plugins.erp.hcm.compensation.models import (
	AllowanceDefinition,
	CompensationPackage,
	CompensationReviewCycle,
	DeductionDefinition,
	EmployeeAllowance,
	EmployeeDeduction,
)

__all__ = [
	"CompensationServiceError",
	"CompensationNotFoundError",
	"CompensationStateError",
	"CompensationBudgetError",
	"CompensationService",
]


class CompensationServiceError(Exception):
	"""Base exception for compensation service errors."""


class CompensationNotFoundError(CompensationServiceError):
	"""Raised when a required compensation record cannot be found."""


class CompensationStateError(CompensationServiceError):
	"""Raised when an operation is invalid for the current state of a record."""


class CompensationBudgetError(CompensationServiceError):
	"""Raised when a compensation action would exceed a budget constraint."""


def _now_utc() -> datetime:
	return datetime.now(tz=timezone.utc)


def _emit(event: Any) -> None:
	"""Emit a domain event. Delegates to the event bus if available, otherwise no-op."""
	try:
		from pgappforge.plugins.erp.foundation.events import event_bus
		event_bus.publish(event)
	except Exception:
		pass


class CompensationService:
	"""Service layer for all compensation operations.

	All monetary arithmetic uses Decimal with ROUND_HALF_UP to avoid float drift.
	Compensation packages form an immutable ledger — salary fields are never mutated
	after insert; closing a package sets effective_to on the old row and inserts a new one.
	"""

	# ------------------------------------------------------------------
	# Package management
	# ------------------------------------------------------------------

	def assign_package(
		self,
		employee_id: str,
		grade_id: str | None,
		base_salary_cents: int,
		effective_from: date,
		session: Session,
		*,
		tenant_id: str,
		pay_frequency: str = "MONTHLY",
		package_type: str = "STANDARD",
		approved_by: str | None = None,
		notes: str | None = None,
		currency_code: str = "KES",
	) -> CompensationPackage:
		assert base_salary_cents > 0, "base_salary_cents must be positive"
		assert employee_id, "employee_id is required"
		assert tenant_id, "tenant_id is required"

		# Find any currently active package for this employee under this tenant
		existing_stmt = select(CompensationPackage).where(
			and_(
				CompensationPackage.employee_id == employee_id,
				CompensationPackage.tenant_id == tenant_id,
				CompensationPackage.effective_from <= effective_from,
				or_(
					CompensationPackage.effective_to.is_(None),
					CompensationPackage.effective_to >= effective_from,
				),
			)
		)
		existing = session.execute(existing_stmt).scalar_one_or_none()

		is_first = existing is None
		old_salary_cents: int = 0

		if existing is not None:
			old_salary_cents = existing.base_salary_cents
			existing.effective_to = effective_from - timedelta(days=1)
			session.flush()

		new_package = CompensationPackage(
			employee_id=employee_id,
			tenant_id=tenant_id,
			grade_id=grade_id,
			base_salary_cents=base_salary_cents,
			pay_frequency=pay_frequency,
			package_type=package_type,
			effective_from=effective_from,
			effective_to=None,
			approved_by=approved_by,
			approved_at=_now_utc() if approved_by else None,
			notes=notes,
			currency_code=currency_code,
			metadata_={},
		)
		session.add(new_package)
		session.flush()

		assert new_package.id, "Package must have an ID after flush"

		if is_first:
			_emit(
				CompensationPackageCreatedEvent(
					employee_id=employee_id,
					package_id=new_package.id,
					base_salary_cents=base_salary_cents,
					currency_code=currency_code,
					effective_from=effective_from,
				)
			)
		else:
			_emit(
				CompensationPackageRevisedEvent(
					employee_id=employee_id,
					package_id=new_package.id,
					old_salary_cents=old_salary_cents,
					new_salary_cents=base_salary_cents,
					change_reason=package_type,
				)
			)

		return new_package

	def get_active_package(
		self,
		employee_id: str,
		as_of_date: date,
		tenant_id: str,
		session: Session,
	) -> CompensationPackage | None:
		stmt = select(CompensationPackage).where(
			and_(
				CompensationPackage.employee_id == employee_id,
				CompensationPackage.tenant_id == tenant_id,
				CompensationPackage.effective_from <= as_of_date,
				or_(
					CompensationPackage.effective_to.is_(None),
					CompensationPackage.effective_to >= as_of_date,
				),
			)
		)
		return session.execute(stmt).scalar_one_or_none()

	# ------------------------------------------------------------------
	# Allowances
	# ------------------------------------------------------------------

	def get_active_allowances(
		self,
		employee_id: str,
		as_of_date: date,
		tenant_id: str,
		session: Session,
	) -> list[EmployeeAllowance]:
		stmt = (
			select(EmployeeAllowance)
			.join(AllowanceDefinition, EmployeeAllowance.allowance_def_id == AllowanceDefinition.id)
			.where(
				and_(
					EmployeeAllowance.employee_id == employee_id,
					EmployeeAllowance.tenant_id == tenant_id,
					EmployeeAllowance.effective_from <= as_of_date,
					or_(
						EmployeeAllowance.effective_to.is_(None),
						EmployeeAllowance.effective_to >= as_of_date,
					),
					AllowanceDefinition.is_active.is_(True),
				)
			)
		)
		return list(session.execute(stmt).scalars().all())

	def assign_allowance(
		self,
		employee_id: str,
		allowance_def_id: str,
		effective_from: date,
		tenant_id: str,
		session: Session,
		*,
		override_amount_cents: int | None = None,
	) -> EmployeeAllowance:
		assert employee_id, "employee_id is required"
		assert allowance_def_id, "allowance_def_id is required"
		assert tenant_id, "tenant_id is required"

		# Close any existing active allowance for same def
		existing_stmt = select(EmployeeAllowance).where(
			and_(
				EmployeeAllowance.employee_id == employee_id,
				EmployeeAllowance.allowance_def_id == allowance_def_id,
				EmployeeAllowance.tenant_id == tenant_id,
				EmployeeAllowance.effective_from <= effective_from,
				or_(
					EmployeeAllowance.effective_to.is_(None),
					EmployeeAllowance.effective_to >= effective_from,
				),
			)
		)
		existing = session.execute(existing_stmt).scalar_one_or_none()
		if existing is not None:
			existing.effective_to = effective_from - timedelta(days=1)
			session.flush()

		new_allowance = EmployeeAllowance(
			employee_id=employee_id,
			tenant_id=tenant_id,
			allowance_def_id=allowance_def_id,
			override_amount_cents=override_amount_cents,
			effective_from=effective_from,
			effective_to=None,
		)
		session.add(new_allowance)
		session.flush()

		assert new_allowance.id, "EmployeeAllowance must have an ID after flush"

		# Resolve effective amount for event
		effective_amount = override_amount_cents if override_amount_cents is not None else 0
		_emit(
			AllowanceAssignedEvent(
				employee_id=employee_id,
				allowance_def_id=allowance_def_id,
				amount_cents=effective_amount,
			)
		)

		return new_allowance

	def revoke_allowance(
		self,
		employee_allowance_id: str,
		effective_to: date,
		session: Session,
	) -> EmployeeAllowance:
		stmt = select(EmployeeAllowance).where(EmployeeAllowance.id == employee_allowance_id)
		allowance = session.execute(stmt).scalar_one_or_none()
		if allowance is None:
			raise CompensationNotFoundError(f"EmployeeAllowance {employee_allowance_id!r} not found")

		allowance.effective_to = effective_to
		session.flush()

		_emit(
			AllowanceRevokedEvent(
				employee_id=allowance.employee_id,
				employee_allowance_id=employee_allowance_id,
				effective_to=effective_to,
			)
		)

		return allowance

	# ------------------------------------------------------------------
	# Deductions
	# ------------------------------------------------------------------

	def get_active_deductions(
		self,
		employee_id: str,
		as_of_date: date,
		tenant_id: str,
		session: Session,
	) -> list[EmployeeDeduction]:
		stmt = (
			select(EmployeeDeduction)
			.join(DeductionDefinition, EmployeeDeduction.deduction_def_id == DeductionDefinition.id)
			.where(
				and_(
					EmployeeDeduction.employee_id == employee_id,
					EmployeeDeduction.tenant_id == tenant_id,
					EmployeeDeduction.effective_from <= as_of_date,
					or_(
						EmployeeDeduction.effective_to.is_(None),
						EmployeeDeduction.effective_to >= as_of_date,
					),
					DeductionDefinition.is_active.is_(True),
				)
			)
			.order_by(EmployeeDeduction.priority.asc())
		)
		return list(session.execute(stmt).scalars().all())

	def assign_deduction(
		self,
		employee_id: str,
		deduction_def_id: str,
		amount_cents: int,
		effective_from: date,
		tenant_id: str,
		session: Session,
		*,
		balance_remaining_cents: int | None = None,
		priority: int = 1,
		notes: str | None = None,
	) -> EmployeeDeduction:
		assert employee_id, "employee_id is required"
		assert deduction_def_id, "deduction_def_id is required"
		assert amount_cents > 0, "amount_cents must be positive"
		assert tenant_id, "tenant_id is required"

		new_deduction = EmployeeDeduction(
			employee_id=employee_id,
			tenant_id=tenant_id,
			deduction_def_id=deduction_def_id,
			amount_cents=amount_cents,
			balance_remaining_cents=balance_remaining_cents,
			priority=priority,
			effective_from=effective_from,
			effective_to=None,
			notes=notes,
		)
		session.add(new_deduction)
		session.flush()

		assert new_deduction.id, "EmployeeDeduction must have an ID after flush"

		_emit(
			DeductionAssignedEvent(
				employee_id=employee_id,
				deduction_def_id=deduction_def_id,
				amount_cents=amount_cents,
			)
		)

		return new_deduction

	# ------------------------------------------------------------------
	# Package computation
	# ------------------------------------------------------------------

	def compute_total_package(
		self,
		employee_id: str,
		as_of_date: date,
		tenant_id: str,
		session: Session,
	) -> dict[str, Any]:
		"""Compute a full compensation breakdown for an employee as of a given date.

		All arithmetic uses Decimal with ROUND_HALF_UP. Returns cents throughout.
		"""
		package = self.get_active_package(employee_id, as_of_date, tenant_id, session)
		if package is None:
			raise CompensationNotFoundError(
				f"No active compensation package for employee {employee_id!r} as of {as_of_date}"
			)

		base = Decimal(str(package.base_salary_cents))

		allowances_rows = self.get_active_allowances(employee_id, as_of_date, tenant_id, session)
		deductions_rows = self.get_active_deductions(employee_id, as_of_date, tenant_id, session)

		allowances_detail: list[dict[str, Any]] = []
		total_allowances = Decimal("0")

		for ea in allowances_rows:
			defn: AllowanceDefinition = ea.allowance_def
			if ea.override_amount_cents is not None:
				amount = Decimal(str(ea.override_amount_cents))
			elif defn.amount_cents and defn.amount_cents > 0:
				amount = Decimal(str(defn.amount_cents))
			else:
				pct = Decimal(str(defn.percentage_of_basic))
				amount = (base * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

			total_allowances += amount
			allowances_detail.append(
				{
					"employee_allowance_id": ea.id,
					"allowance_def_id": defn.id,
					"code": defn.code,
					"name": defn.name,
					"allowance_type": defn.allowance_type,
					"amount_cents": int(amount),
					"is_taxable": defn.is_taxable,
					"is_pensionable": defn.is_pensionable,
				}
			)

		deductions_detail: list[dict[str, Any]] = []
		total_deductions = Decimal("0")

		for ed in deductions_rows:
			defn: DeductionDefinition = ed.deduction_def
			amount = Decimal(str(ed.amount_cents))
			total_deductions += amount
			deductions_detail.append(
				{
					"employee_deduction_id": ed.id,
					"deduction_def_id": defn.id,
					"code": defn.code,
					"name": defn.name,
					"deduction_type": defn.deduction_type,
					"amount_cents": int(amount),
					"is_pre_tax": defn.is_pre_tax,
					"priority": ed.priority,
					"balance_remaining_cents": ed.balance_remaining_cents,
				}
			)

		gross_salary = base + total_allowances
		total_cost_to_company = gross_salary  # extend with employer-side costs as needed

		return {
			"employee_id": employee_id,
			"as_of_date": as_of_date.isoformat(),
			"package_id": package.id,
			"currency_code": package.currency_code,
			"base_salary_cents": int(base),
			"total_allowances_cents": int(total_allowances),
			"total_deductions_cents": int(total_deductions),
			"gross_salary_cents": int(gross_salary),
			"total_cost_to_company_cents": int(total_cost_to_company),
			"allowances": allowances_detail,
			"deductions": deductions_detail,
		}

	# ------------------------------------------------------------------
	# Review cycles
	# ------------------------------------------------------------------

	def approve_review_cycle(
		self,
		cycle_id: str,
		approver_id: str,
		session: Session,
	) -> CompensationReviewCycle:
		stmt = select(CompensationReviewCycle).where(CompensationReviewCycle.id == cycle_id)
		cycle = session.execute(stmt).scalar_one_or_none()
		if cycle is None:
			raise CompensationNotFoundError(f"CompensationReviewCycle {cycle_id!r} not found")

		if cycle.status != "IN_PROGRESS":
			raise CompensationStateError(
				f"Review cycle {cycle_id!r} cannot be approved from status {cycle.status!r}; "
				"expected IN_PROGRESS"
			)

		if cycle.committed_cents > cycle.budget_pool_cents:
			raise CompensationBudgetError(
				f"Committed {cycle.committed_cents} cents exceeds budget pool "
				f"{cycle.budget_pool_cents} cents for cycle {cycle_id!r}"
			)

		cycle.status = "APPROVED"
		cycle.approved_by = approver_id
		cycle.approved_at = _now_utc()
		session.flush()

		_emit(
			ReviewCycleApprovedEvent(
				cycle_id=cycle_id,
				approver_id=approver_id,
				committed_cents=cycle.committed_cents,
			)
		)

		return cycle


# ------------------------------------------------------------------
# BPM action registrations
# ------------------------------------------------------------------

@BPMActionRegistry.register(
	"hcm.compensation.assign_package",
	"Assign employee compensation package",
)
def _bpm_assign_package(
	employee_id: str,
	grade_id: str | None,
	base_salary_cents: int,
	effective_from: date,
	session: Session,
	**kwargs: Any,
) -> CompensationPackage:
	svc = CompensationService()
	return svc.assign_package(
		employee_id=employee_id,
		grade_id=grade_id,
		base_salary_cents=base_salary_cents,
		effective_from=effective_from,
		session=session,
		**kwargs,
	)


@BPMActionRegistry.register(
	"hcm.compensation.approve_review",
	"Approve compensation review cycle",
)
def _bpm_approve_review(
	cycle_id: str,
	approver_id: str,
	session: Session,
	**kwargs: Any,
) -> CompensationReviewCycle:
	svc = CompensationService()
	return svc.approve_review_cycle(
		cycle_id=cycle_id,
		approver_id=approver_id,
		session=session,
	)
