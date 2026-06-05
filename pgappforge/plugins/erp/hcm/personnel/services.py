"""
pgappforge/plugins/erp/hcm/personnel/services.py

PersonnelService — stateless business logic for the HCM Personnel plugin.

All public methods accept an explicit SQLAlchemy session.
Transaction boundaries owned by the caller.

Key public methods (full list in __all__):
  hire_employee(data, session)                         -> Employee
  terminate_employee(employee_id, data, session)       -> Employee
  transfer_employee(employee_id, data, session)        -> Employee
  confirm_probation(employee_id, data, session)        -> Employee
  extend_probation(employee_id, days, session)         -> Employee
  employees_on_probation(tenant_id, session)           -> list[Employee]
  go_on_leave(employee_id, data, session)              -> Employee
  return_from_leave(employee_id, data, session)        -> Employee
  update_background_check(employee_id, data, session)  -> Employee
  find_prior_employment(party_id, tenant_id, session)  -> list[Employee]
  generate_employee_number(entity_id, session)         -> str

  record_compensation(data, session)                   -> EmployeeCompensation
  approve_compensation(comp_id, approver_id, session)  -> EmployeeCompensation
  reject_compensation(comp_id, approver_id, reason, session) -> EmployeeCompensation
  current_compensation(employee_id, session)           -> EmployeeCompensation | None

  attach_document(data, session)                       -> EmployeeDocument
  verify_document(document_id, session)                -> EmployeeDocument
  expiring_documents(tenant_id, days, session)         -> list[EmployeeDocument]

  issue_offer(employee_id, data, session)              -> EmploymentContract
  accept_offer(contract_id, data, session)             -> EmploymentContract
  activate_contract(contract_id, session)              -> EmploymentContract
  terminate_contract(contract_id, data, session)       -> EmploymentContract

  open_disciplinary_case(data, session)                -> DisciplinaryCase
  issue_show_cause(case_id, data, session)             -> DisciplinaryCase
  schedule_hearing(case_id, data, session)             -> DisciplinaryCase
  record_hearing_outcome(case_id, data, session)       -> DisciplinaryCase
  close_disciplinary_case(case_id, session)            -> DisciplinaryCase

  lodge_grievance(data, session)                       -> GrievanceCase
  acknowledge_grievance(case_id, data, session)        -> GrievanceCase
  review_grievance(case_id, data, session)             -> GrievanceCase
  resolve_grievance(case_id, data, session)            -> GrievanceCase
  escalate_grievance(case_id, data, session)           -> GrievanceCase
  overdue_grievances(tenant_id, session)               -> list[GrievanceCase]

  create_onboarding_plan(employee_id, data, session)   -> OnboardingPlan
  complete_onboarding_item(plan_id, item_key, data, session) -> OnboardingPlan

  initiate_exit(employee_id, data, session)            -> EmployeeExit
  clear_exit_item(exit_id, item_key, data, session)    -> EmployeeExit
  close_exit(exit_id, data, session)                   -> EmployeeExit
  compute_redundancy_pay(employee_id, termination_date, session) -> dict

  headcount_summary(entity_id, session)                -> dict
  headcount_budget_summary(entity_id, session)         -> dict
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PersonnelServiceError(Exception):
	"""Base domain error for Personnel operations."""


class EmployeeNotFoundError(PersonnelServiceError):
	pass


class CompensationError(PersonnelServiceError):
	pass


class DocumentError(PersonnelServiceError):
	pass


class ContractError(PersonnelServiceError):
	pass


class DisciplinaryError(PersonnelServiceError):
	pass


class GrievanceError(PersonnelServiceError):
	pass


class ExitError(PersonnelServiceError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Valid status transitions — any move not listed here is illegal without
# an explicit rehire path.
_VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
	"ACTIVE":     {"ON_LEAVE", "TERMINATED", "RETIRED"},
	"ON_LEAVE":   {"ACTIVE", "TERMINATED"},
	"TERMINATED": set(),    # use hire_employee with prior_employee_id to rehire
	"RETIRED":    set(),
}

_VALID_CONTRACT_TRANSITIONS: dict[str, set[str]] = {
	"DRAFT":      {"OFFERED"},
	"OFFERED":    {"ACCEPTED", "TERMINATED"},
	"ACCEPTED":   {"ACTIVE", "TERMINATED"},
	"ACTIVE":     {"AMENDED", "TERMINATED"},
	"AMENDED":    {"ACTIVE", "TERMINATED"},
	"TERMINATED": set(),
}

_VALID_DISC_TRANSITIONS: dict[str, set[str]] = {
	"OPEN":             {"SHOW_CAUSE_ISSUED", "CLOSED"},
	"SHOW_CAUSE_ISSUED": {"HEARING_SCHEDULED", "CLOSED"},
	"HEARING_SCHEDULED": {"HEARING_COMPLETE"},
	"HEARING_COMPLETE": {"CLOSED"},
	"CLOSED":           set(),
}

_VALID_GRIEVANCE_TRANSITIONS: dict[str, set[str]] = {
	"FILED":        {"ACKNOWLEDGED"},
	"ACKNOWLEDGED": {"UNDER_REVIEW", "ESCALATED", "RESOLVED"},
	"UNDER_REVIEW": {"RESOLVED", "ESCALATED"},
	"RESOLVED":     {"CLOSED"},
	"ESCALATED":    {"UNDER_REVIEW", "RESOLVED", "CLOSED"},
	"CLOSED":       set(),
}

_VALID_EXIT_TRANSITIONS: dict[str, set[str]] = {
	"INITIATED":   {"IN_PROGRESS"},
	"IN_PROGRESS": {"CLEARED"},
	"CLEARED":     {"CLOSED"},
	"CLOSED":      set(),
}


def _assert_status_transition(current: str, target: str, transitions: dict[str, set[str]], label: str) -> None:
	allowed = transitions.get(current, set())
	if target not in allowed:
		raise PersonnelServiceError(
			f"Illegal {label} transition: {current!r} → {target!r}. "
			f"Allowed from {current!r}: {allowed or {'(none)'}}"
		)


def _parse_date(val: Any) -> date | None:
	if val is None:
		return None
	if isinstance(val, date):
		return val
	return date.fromisoformat(str(val))


def _require_date(val: Any, field: str) -> date:
	d = _parse_date(val)
	if d is None:
		raise PersonnelServiceError(f"{field} is required")
	return d


def _today() -> date:
	return datetime.now(timezone.utc).date()


def _now() -> datetime:
	return datetime.now(timezone.utc)


# Kenya Employment Act 2007 s.35 minimum notice days by pay frequency
_KENYA_NOTICE_DAYS: dict[str, int] = {
	"ANNUAL":   28,
	"MONTHLY":  28,
	"BIWEEKLY": 14,
	"WEEKLY":   7,
	"HOURLY":   1,   # casual / same-day
}

# Kenya EA s.40: redundancy notice
_KENYA_REDUNDANCY_NOTICE_DAYS = 30


# ---------------------------------------------------------------------------
# PersonnelService
# ---------------------------------------------------------------------------

class PersonnelService:
	"""Stateless Personnel domain service.

	All monetary amounts are integer cents — never float.
	Caller owns transaction boundary (flush/commit).
	"""

	# ==========================================================================
	# Employee hiring
	# ==========================================================================

	def hire_employee(self, data: dict[str, Any], session: Any) -> Any:
		"""Create an Employee record and optionally fill their position.

		Enforces:
		  - background_check gate when tenant config REQUIRE_BACKGROUND_CHECK=True
		  - rehire detection via party_id / prior_employee_id
		  - EmployeeEntitlementsInitEvent for leave plugin to seed balances
		  - auto-generates employee_number if absent (format KE-{entity_code}-{seq:05d})
		  - creates OnboardingPlan if onboarding_items provided in data

		Args:
			data: dict with keys:
			  tenant_id (req), entity_id (req), start_date (req, ISO date),
			  employee_number (opt — auto-generated if absent),
			  employment_type (opt, default FULL_TIME),
			  org_unit_id, position_id, manager_id, party_id,
			  cost_center_code, national_id_encrypted, tax_id_encrypted,
			  bank_account_iban_encrypted, bank_bic,
			  probation_end_date (opt),
			  prior_employee_id (opt — UUID of prior termination record for rehire),
			  background_check_status (opt, default NOT_REQUIRED),
			  require_background_check (opt bool — tenant override),
			  initial_compensation (opt): {pay_type, amount_cents (int),
			    currency_code (default KES), frequency, grade_code, approved_by},
			  onboarding_items (opt): list of {key, label, due_days_from_start, owner_role}

		Returns:
			New Employee (not committed).
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import (
			Employee, EmployeeCompensation, OnboardingPlan,
		)
		from pgappforge.plugins.erp.hcm.personnel.events import (
			EmployeeHiredEvent, EmployeeEntitlementsInitEvent, EmployeeRehiredEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "entity_id", "start_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise PersonnelServiceError(f"Missing required fields: {missing}")

		start = _require_date(data["start_date"], "start_date")
		probation_end = _parse_date(data.get("probation_end_date"))

		# ------------------------------------------------------------------
		# Employee number — auto-generate if not provided
		# ------------------------------------------------------------------
		employee_number = data.get("employee_number") or self.generate_employee_number(
			data["entity_id"], session
		)

		# ------------------------------------------------------------------
		# Background check gate
		# ------------------------------------------------------------------
		bg_status = (data.get("background_check_status") or "NOT_REQUIRED").upper()
		require_bg = bool(data.get("require_background_check", False))
		if require_bg and bg_status not in ("PASSED", "WAIVED"):
			raise PersonnelServiceError(
				"Tenant requires background check. "
				f"background_check_status is {bg_status!r}; must be PASSED or WAIVED before hire."
			)

		# ------------------------------------------------------------------
		# Rehire detection
		# ------------------------------------------------------------------
		prior_employee_id: str = data.get("prior_employee_id") or ""
		prior_service_years: float = 0.0

		if not prior_employee_id and data.get("party_id"):
			prior_records = self.find_prior_employment(
				data["party_id"], data["tenant_id"], session
			)
			if prior_records:
				prior_employee_id = prior_records[0].id
				seniority_days = (start - prior_records[0].start_date).days
				prior_service_years = round(seniority_days / 365.25, 2)

		employee = Employee(
			tenant_id=data["tenant_id"],
			employee_number=employee_number,
			entity_id=data["entity_id"],
			party_id=data.get("party_id"),
			position_id=data.get("position_id"),
			org_unit_id=data.get("org_unit_id"),
			manager_id=data.get("manager_id"),
			employment_type=(data.get("employment_type") or "FULL_TIME").upper(),
			employment_status="ACTIVE",
			start_date=start,
			probation_end_date=probation_end,
			cost_center_code=data.get("cost_center_code"),
			national_id_encrypted=data.get("national_id_encrypted"),
			tax_id_encrypted=data.get("tax_id_encrypted"),
			bank_account_iban_encrypted=data.get("bank_account_iban_encrypted"),
			bank_bic=data.get("bank_bic"),
			rehire_eligible=True,
			background_check_status=bg_status,
			background_check_provider=data.get("background_check_provider"),
			background_check_ref=data.get("background_check_ref"),
		)
		session.add(employee)
		session.flush()

		# ------------------------------------------------------------------
		# Headcount / position fill — hard gate, not silently swallowed
		# ------------------------------------------------------------------
		if employee.position_id:
			try:
				from pgappforge.plugins.erp.hcm.org.services import OrgService
				org_svc = OrgService()
				# Headcount check — raises if position is full
				try:
					org_svc.position_headcount_check(employee.position_id, session)
				except Exception as hc_exc:
					raise PersonnelServiceError(
						f"Position headcount limit reached: {hc_exc}"
					) from hc_exc
				org_svc.fill_position(employee.position_id, employee.id, session)
			except PersonnelServiceError:
				raise
			except Exception as exc:
				log.warning("PersonnelService.hire: could not fill position: %s", exc)

		# ------------------------------------------------------------------
		# Initial compensation — default currency KES (Kenya context)
		# ------------------------------------------------------------------
		comp_data = data.get("initial_compensation")
		if comp_data:
			amount = comp_data.get("amount_cents")
			assert isinstance(amount, int), "initial_compensation.amount_cents must be int"
			session.add(EmployeeCompensation(
				tenant_id=data["tenant_id"],
				employee_id=employee.id,
				effective_date=start,
				pay_type=(comp_data.get("pay_type") or "SALARY").upper(),
				amount_cents=amount,
				currency_code=(comp_data.get("currency_code") or "KES").upper(),
				frequency=(comp_data.get("frequency") or "ANNUAL").upper(),
				grade_code=comp_data.get("grade_code"),
				reason="NEW_HIRE",
				approved_by=comp_data.get("approved_by"),
				approval_status="APPROVED",
			))

		# ------------------------------------------------------------------
		# Onboarding plan
		# ------------------------------------------------------------------
		onboarding_items = data.get("onboarding_items") or []
		if onboarding_items:
			plan = OnboardingPlan(
				tenant_id=data["tenant_id"],
				employee_id=employee.id,
				status="PENDING",
				checklist_items=[
					{
						"key": item.get("key", f"item_{i}"),
						"label": item.get("label", ""),
						"due_days_from_start": item.get("due_days_from_start", 30),
						"owner_role": item.get("owner_role", "HR"),
						"completed_at": None,
						"completed_by": None,
					}
					for i, item in enumerate(onboarding_items)
				],
			)
			session.add(plan)

		# ------------------------------------------------------------------
		# Events
		# ------------------------------------------------------------------
		try:
			emit_event(
				EmployeeHiredEvent(
					aggregate_id=employee.id,
					aggregate_type="Employee",
					tenant_id=employee.tenant_id,
					employee_id=employee.id,
					employee_number=employee.employee_number,
					entity_id=employee.entity_id,
					position_id=employee.position_id or "",
					org_unit_id=employee.org_unit_id or "",
					employment_type=employee.employment_type,
					start_date=start.isoformat(),
				),
				session,
			)
			# Entitlements init — leave plugin seeds statutory balances
			emit_event(
				EmployeeEntitlementsInitEvent(
					aggregate_id=employee.id,
					aggregate_type="Employee",
					tenant_id=employee.tenant_id,
					employee_id=employee.id,
					employee_number=employee.employee_number,
					entity_id=employee.entity_id,
					start_date=start.isoformat(),
					employment_type=employee.employment_type,
					annual_leave_days=21,
					maternity_leave_days=90,
					paternity_leave_days=14,
				),
				session,
			)
			if prior_employee_id:
				emit_event(
					EmployeeRehiredEvent(
						aggregate_id=employee.id,
						aggregate_type="Employee",
						tenant_id=employee.tenant_id,
						employee_id=employee.id,
						employee_number=employee.employee_number,
						entity_id=employee.entity_id,
						rehire_date=start.isoformat(),
						prior_employee_id=prior_employee_id,
						prior_service_years=prior_service_years,
					),
					session,
				)
		except Exception as evt_exc:
			log.warning("PersonnelService.hire_employee: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.hire_employee: %s hired (entity=%s)", employee.employee_number, employee.entity_id)
		return employee

	# ==========================================================================
	# Termination
	# ==========================================================================

	def terminate_employee(
		self,
		employee_id: str,
		data: dict[str, Any],
		session: Any,
	) -> Any:
		"""Terminate an employee's engagement.

		Enforces:
		  - Kenya Employment Act 2007 s.35 minimum notice periods
		  - s.40 redundancy: 1 month notice or pay in lieu
		  - INVOLUNTARY terminations require a DISMISSAL disciplinary outcome
		    unless disciplinary_bypass_reason is provided (stored in notes)
		  - Status transition guard

		Args:
			employee_id: UUID of the Employee.
			data: dict with keys:
			  termination_date (opt, ISO date — defaults to today),
			  termination_type (req: VOLUNTARY|INVOLUNTARY|REDUNDANCY|RETIREMENT),
			  termination_reason (opt),
			  rehire_eligible (opt bool, default True),
			  notice_waived (opt bool, default False),
			  notice_waiver_reason (opt str),
			  disciplinary_bypass_reason (opt str — required when INVOLUNTARY but no DISMISSAL case)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, DisciplinaryCase
		from pgappforge.plugins.erp.hcm.personnel.events import EmployeeTerminatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		_assert_status_transition(
			employee.employment_status,
			"RETIRED" if data.get("termination_type", "").upper() == "RETIREMENT" else "TERMINATED",
			_VALID_STATUS_TRANSITIONS,
			"employment_status",
		)

		term_date = _parse_date(data.get("termination_date")) or _today()
		term_type = (data.get("termination_type") or "VOLUNTARY").upper()
		valid_types = {"VOLUNTARY", "INVOLUNTARY", "REDUNDANCY", "RETIREMENT"}
		if term_type not in valid_types:
			raise PersonnelServiceError(f"termination_type must be one of {valid_types}")

		# ------------------------------------------------------------------
		# Kenya EA notice period enforcement
		# ------------------------------------------------------------------
		notice_waived = bool(data.get("notice_waived", False))
		if not notice_waived:
			comp = self.current_compensation(employee_id, session)
			freq = (comp.frequency if comp else "MONTHLY").upper()

			if term_type == "REDUNDANCY":
				min_notice = _KENYA_REDUNDANCY_NOTICE_DAYS
			else:
				min_notice = _KENYA_NOTICE_DAYS.get(freq, 28)

			days_given = (term_date - _today()).days
			if days_given < min_notice and term_type != "RETIREMENT":
				raise PersonnelServiceError(
					f"Kenya Employment Act s.35/s.40: minimum notice period is {min_notice} days "
					f"for {freq!r} pay frequency. "
					f"termination_date gives only {days_given} days notice. "
					f"Pass notice_waived=True with notice_waiver_reason to override."
				)

		# ------------------------------------------------------------------
		# INVOLUNTARY must have a DISMISSAL disciplinary case (or bypass)
		# ------------------------------------------------------------------
		if term_type == "INVOLUNTARY":
			dismissal_case = session.execute(
				sa.select(DisciplinaryCase)
				.where(DisciplinaryCase.employee_id == employee_id)
				.where(DisciplinaryCase.outcome == "DISMISSED")
				.where(DisciplinaryCase.status == "CLOSED")
				.limit(1)
			).scalar_one_or_none()

			if dismissal_case is None:
				bypass_reason = data.get("disciplinary_bypass_reason", "").strip()
				if not bypass_reason:
					raise PersonnelServiceError(
						"INVOLUNTARY termination requires a closed DisciplinaryCase with outcome=DISMISSED. "
						"Pass disciplinary_bypass_reason to override (must be documented)."
					)
				log.warning(
					"PersonnelService.terminate: INVOLUNTARY without DISMISSAL case — bypass: %r (emp=%s)",
					bypass_reason, employee.employee_number,
				)

		old_position_id = employee.position_id

		employee.employment_status = "RETIRED" if term_type == "RETIREMENT" else "TERMINATED"
		employee.termination_date = term_date
		employee.termination_type = term_type
		employee.termination_reason = data.get("termination_reason")
		employee.rehire_eligible = bool(data.get("rehire_eligible", True))
		employee.updated_at = _now()

		# Vacate position
		if old_position_id:
			try:
				from pgappforge.plugins.erp.hcm.org.services import OrgService
				OrgService().vacate_position(old_position_id, employee_id, session)
			except Exception as exc:
				log.warning("PersonnelService.terminate: could not vacate position: %s", exc)

		# Terminate active contract
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import EmploymentContract
			active_contract = session.execute(
				sa.select(EmploymentContract)
				.where(EmploymentContract.employee_id == employee_id)
				.where(EmploymentContract.status.in_(("ACTIVE", "ACCEPTED", "OFFERED")))
				.order_by(sa.desc(EmploymentContract.created_at))
				.limit(1)
			).scalar_one_or_none()
			if active_contract is not None:
				active_contract.status = "TERMINATED"
				active_contract.terminated_date = term_date
				active_contract.updated_at = _now()
				if notice_waived and data.get("notice_waiver_reason"):
					active_contract.notice_pay_in_lieu_cents = data.get("notice_pay_in_lieu_cents")
		except Exception as exc:
			log.warning("PersonnelService.terminate: contract termination failed (non-fatal): %s", exc)

		try:
			emit_event(
				EmployeeTerminatedEvent(
					aggregate_id=employee_id,
					aggregate_type="Employee",
					tenant_id=employee.tenant_id,
					employee_id=employee_id,
					employee_number=employee.employee_number,
					entity_id=employee.entity_id,
					position_id=old_position_id or "",
					termination_date=term_date.isoformat(),
					termination_type=term_type,
					termination_reason=employee.termination_reason or "",
					rehire_eligible=employee.rehire_eligible,
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.terminate_employee: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.terminate_employee: %s terminated (%s)", employee.employee_number, term_type)
		return employee

	# ==========================================================================
	# Transfer
	# ==========================================================================

	def transfer_employee(
		self,
		employee_id: str,
		data: dict[str, Any],
		session: Any,
	) -> Any:
		"""Transfer an employee to a new entity / org_unit / position.

		Args:
			data: dict with optional keys: new_entity_id, new_org_unit_id,
			      new_position_id, new_manager_id, effective_date (ISO date).
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		from pgappforge.plugins.erp.hcm.personnel.events import EmployeeTransferredEvent, EmployeeAssignedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		if employee.employment_status not in ("ACTIVE", "ON_LEAVE"):
			raise PersonnelServiceError(
				f"Cannot transfer employee with status {employee.employment_status!r}"
			)

		eff = _parse_date(data.get("effective_date")) or _today()

		old_entity_id = employee.entity_id
		old_position_id = employee.position_id or ""
		old_org_unit_id = employee.org_unit_id or ""

		cross_entity = "new_entity_id" in data and data["new_entity_id"] != employee.entity_id

		if data.get("new_entity_id"):
			employee.entity_id = data["new_entity_id"]
		if data.get("new_org_unit_id"):
			employee.org_unit_id = data["new_org_unit_id"]
		if data.get("new_manager_id") is not None:
			employee.manager_id = data["new_manager_id"]

		new_position_id = data.get("new_position_id")
		if new_position_id and new_position_id != old_position_id:
			if old_position_id:
				try:
					from pgappforge.plugins.erp.hcm.org.services import OrgService
					OrgService().vacate_position(old_position_id, employee_id, session)
				except Exception as exc:
					log.warning("PersonnelService.transfer: vacate old position failed: %s", exc)
			try:
				from pgappforge.plugins.erp.hcm.org.services import OrgService
				OrgService().fill_position(new_position_id, employee_id, session)
			except Exception as exc:
				log.warning("PersonnelService.transfer: fill new position failed: %s", exc)
			employee.position_id = new_position_id

		employee.updated_at = _now()

		try:
			if cross_entity:
				emit_event(
					EmployeeTransferredEvent(
						aggregate_id=employee_id,
						aggregate_type="Employee",
						tenant_id=employee.tenant_id,
						employee_id=employee_id,
						old_entity_id=old_entity_id,
						new_entity_id=employee.entity_id,
						effective_date=eff.isoformat(),
					),
					session,
				)
			else:
				emit_event(
					EmployeeAssignedEvent(
						aggregate_id=employee_id,
						aggregate_type="Employee",
						tenant_id=employee.tenant_id,
						employee_id=employee_id,
						old_position_id=old_position_id,
						new_position_id=employee.position_id or "",
						old_org_unit_id=old_org_unit_id,
						new_org_unit_id=employee.org_unit_id or "",
						effective_date=eff.isoformat(),
					),
					session,
				)
		except Exception as evt_exc:
			log.warning("PersonnelService.transfer_employee: event emission failed (non-fatal): %s", evt_exc)

		return employee

	# ==========================================================================
	# Probation
	# ==========================================================================

	def confirm_probation(self, employee_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Record probation outcome: confirmed, extended, or failed.

		Args:
			employee_id: UUID of the Employee.
			data: dict with keys:
			  confirmed (bool — True=pass, False=fail),
			  extension_days (opt int — extend probation, max 183 days total per EA s.42),
			  confirmed_date (opt ISO date, defaults to today),
			  notes (opt str)

		Kenya EA s.42: probation period max 6 months (183 days), extendable once.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, EmploymentContract
		from pgappforge.plugins.erp.hcm.personnel.events import ProbationConfirmedEvent, ContractConfirmedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		if employee.employment_status != "ACTIVE":
			raise PersonnelServiceError(
				f"Cannot confirm probation for employee with status {employee.employment_status!r}"
			)

		confirmed = bool(data.get("confirmed", True))
		extension_days: int | None = data.get("extension_days")
		confirmed_date = _parse_date(data.get("confirmed_date")) or _today()

		if extension_days is not None:
			# Validate extension does not exceed EA s.42 maximum of 183 days
			new_probation_end = (employee.probation_end_date or confirmed_date) + timedelta(days=extension_days)
			total_probation = (new_probation_end - employee.start_date).days
			if total_probation > 183:
				raise PersonnelServiceError(
					f"Kenya EA s.42: total probation period cannot exceed 183 days. "
					f"Extension would result in {total_probation} days."
				)
			employee.probation_end_date = new_probation_end
			outcome = "EXTENDED"
		elif confirmed:
			employee.probation_end_date = confirmed_date
			outcome = "CONFIRMED"
			# Activate contract
			active_contract = session.execute(
				sa.select(EmploymentContract)
				.where(EmploymentContract.employee_id == employee_id)
				.where(EmploymentContract.status.in_(("ACCEPTED", "ACTIVE")))
				.order_by(sa.desc(EmploymentContract.created_at))
				.limit(1)
			).scalar_one_or_none()
			if active_contract is not None and active_contract.status == "ACCEPTED":
				active_contract.status = "ACTIVE"
				active_contract.confirmed_date = confirmed_date
				active_contract.updated_at = _now()
				try:
					emit_event(
						ContractConfirmedEvent(
							aggregate_id=active_contract.id,
							aggregate_type="EmploymentContract",
							tenant_id=employee.tenant_id,
							contract_id=active_contract.id,
							employee_id=employee_id,
							confirmed_date=confirmed_date.isoformat(),
						),
						session,
					)
				except Exception as evt_exc:
					log.warning("PersonnelService.confirm_probation: ContractConfirmedEvent failed (non-fatal): %s", evt_exc)
		else:
			outcome = "FAILED"
			log.warning(
				"PersonnelService.confirm_probation: probation FAILED for %s — "
				"caller should initiate disciplinary/termination path",
				employee.employee_number,
			)

		employee.updated_at = _now()

		try:
			emit_event(
				ProbationConfirmedEvent(
					aggregate_id=employee_id,
					aggregate_type="Employee",
					tenant_id=employee.tenant_id,
					employee_id=employee_id,
					employee_number=employee.employee_number,
					outcome=outcome,
					new_probation_end_date=(employee.probation_end_date or "").isoformat() if employee.probation_end_date else "",
					confirmed_date=confirmed_date.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.confirm_probation: event emission failed (non-fatal): %s", evt_exc)

		log.info(
			"PersonnelService.confirm_probation: emp=%s outcome=%s",
			employee.employee_number, outcome,
		)
		return employee

	def employees_on_probation(self, tenant_id: str, session: Any) -> list[Any]:
		"""Return employees where probation_end_date >= today and status = ACTIVE."""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee

		today = _today()
		return session.execute(
			sa.select(Employee)
			.where(Employee.tenant_id == tenant_id)
			.where(Employee.employment_status == "ACTIVE")
			.where(Employee.probation_end_date.isnot(None))
			.where(Employee.probation_end_date >= today)
			.order_by(Employee.probation_end_date)
		).scalars().all()

	# ==========================================================================
	# Leave integration hooks
	# ==========================================================================

	def go_on_leave(self, employee_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Transition employee to ON_LEAVE status.

		Args:
			data: dict with keys:
			  leave_type (req), start_date (req ISO date),
			  expected_return_date (req ISO date)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		from pgappforge.plugins.erp.hcm.personnel.events import EmployeeOnLeaveEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		_assert_status_transition(
			employee.employment_status, "ON_LEAVE",
			_VALID_STATUS_TRANSITIONS, "employment_status",
		)

		leave_type = data.get("leave_type") or ""
		if not leave_type:
			raise PersonnelServiceError("leave_type is required")

		start = _require_date(data.get("start_date"), "start_date")
		expected_return = _require_date(data.get("expected_return_date"), "expected_return_date")

		employee.employment_status = "ON_LEAVE"
		employee.updated_at = _now()

		try:
			emit_event(
				EmployeeOnLeaveEvent(
					aggregate_id=employee_id,
					aggregate_type="Employee",
					tenant_id=employee.tenant_id,
					employee_id=employee_id,
					leave_type=leave_type,
					start_date=start.isoformat(),
					expected_return_date=expected_return.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.go_on_leave: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.go_on_leave: emp=%s leave_type=%s", employee.employee_number, leave_type)
		return employee

	def return_from_leave(self, employee_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Transition employee back to ACTIVE from ON_LEAVE.

		Args:
			data: dict with keys: actual_return_date (opt ISO date, defaults to today)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		from pgappforge.plugins.erp.hcm.personnel.events import EmployeeReturnedFromLeaveEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		_assert_status_transition(
			employee.employment_status, "ACTIVE",
			_VALID_STATUS_TRANSITIONS, "employment_status",
		)

		actual_return = _parse_date(data.get("actual_return_date")) or _today()

		employee.employment_status = "ACTIVE"
		employee.updated_at = _now()

		try:
			emit_event(
				EmployeeReturnedFromLeaveEvent(
					aggregate_id=employee_id,
					aggregate_type="Employee",
					tenant_id=employee.tenant_id,
					employee_id=employee_id,
					actual_return_date=actual_return.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.return_from_leave: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.return_from_leave: emp=%s returned %s", employee.employee_number, actual_return)
		return employee

	# ==========================================================================
	# Background check
	# ==========================================================================

	def update_background_check(self, employee_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Update background check status on an employee.

		Args:
			data: dict with keys:
			  status (req: NOT_REQUIRED|PENDING|PASSED|FAILED|WAIVED),
			  provider_ref (opt str),
			  provider (opt str)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		from pgappforge.plugins.erp.hcm.personnel.events import BackgroundCheckUpdatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		valid_statuses = {"NOT_REQUIRED", "PENDING", "PASSED", "FAILED", "WAIVED"}
		status = (data.get("status") or "").upper()
		if status not in valid_statuses:
			raise PersonnelServiceError(f"background_check status must be one of {valid_statuses}")

		employee.background_check_status = status
		if data.get("provider"):
			employee.background_check_provider = data["provider"]
		if data.get("provider_ref"):
			employee.background_check_ref = data["provider_ref"]
		employee.updated_at = _now()

		try:
			emit_event(
				BackgroundCheckUpdatedEvent(
					aggregate_id=employee_id,
					aggregate_type="Employee",
					tenant_id=employee.tenant_id,
					employee_id=employee_id,
					status=status,
					provider_ref=employee.background_check_ref or "",
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.update_background_check: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.update_background_check: emp=%s status=%s", employee.employee_number, status)
		return employee

	# ==========================================================================
	# Rehire detection
	# ==========================================================================

	def find_prior_employment(self, party_id: str, tenant_id: str, session: Any) -> list[Any]:
		"""Return terminated/retired Employee records for the same party_id.

		Ordered by start_date descending — most recent first.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee

		return session.execute(
			sa.select(Employee)
			.where(Employee.party_id == party_id)
			.where(Employee.tenant_id == tenant_id)
			.where(Employee.employment_status.in_(("TERMINATED", "RETIRED")))
			.order_by(sa.desc(Employee.start_date))
		).scalars().all()

	# ==========================================================================
	# Employee number generation
	# ==========================================================================

	def generate_employee_number(self, entity_id: str, session: Any) -> str:
		"""Generate a sequential employee number for the given entity.

		Format: KE-{entity_short}-{seq:05d}
		entity_short = first 6 hex chars of entity_id UUID.

		Uses a PostgreSQL sequence per entity (created on first use).
		Falls back to a count-based approach if DDL is unavailable.
		"""
		entity_short = re.sub(r"[^a-f0-9]", "", entity_id.lower())[:6].upper()
		seq_name = f"hcm_per_emp_seq_{entity_short.lower()}"

		try:
			# Create sequence if it does not exist (idempotent DDL)
			session.execute(sa.text(
				f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1 INCREMENT 1 NO CYCLE"
			))
			next_val = session.execute(
				sa.text(f"SELECT nextval('{seq_name}')")
			).scalar_one()
		except Exception as exc:
			log.warning("PersonnelService.generate_employee_number: sequence unavailable, using count fallback: %s", exc)
			from pgappforge.plugins.erp.hcm.personnel.models import Employee
			count = session.execute(
				sa.select(sa.func.count()).select_from(Employee)
				.where(Employee.entity_id == entity_id)
			).scalar_one()
			next_val = count + 1

		return f"KE-{entity_short}-{next_val:05d}"

	# ==========================================================================
	# Compensation
	# ==========================================================================

	def record_compensation(self, data: dict[str, Any], session: Any) -> Any:
		"""Insert a new EmployeeCompensation row (immutable ledger).

		Enforces:
		  - grade band: if grade_code provided and OrgJobGrade exists, validates
		    min_amount_cents <= amount_cents <= max_amount_cents
		  - approval_status: PENDING when amount exceeds COMP_APPROVAL_THRESHOLD_CENTS
		    (default 10,000,000 = 100,000 KES)
		  - grade_band_check_bypass: dict {approver_id, reason} to override band

		amount_cents MUST be integer. Never updates existing rows.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, EmployeeCompensation, OrgJobGrade
		from pgappforge.plugins.erp.hcm.personnel.events import CompensationChangedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, data.get("employee_id", ""))
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {data.get('employee_id')!r} not found")

		amount = data.get("amount_cents")
		if amount is None:
			raise CompensationError("amount_cents is required")
		if not isinstance(amount, int):
			raise CompensationError("amount_cents must be int")
		if amount <= 0:
			raise CompensationError("amount_cents must be positive")

		eff = _parse_date(data.get("effective_date")) or _today()

		# Grade band enforcement
		grade_code = data.get("grade_code")
		if grade_code:
			grade_band_bypass = data.get("grade_band_check_bypass")  # {approver_id, reason}
			if not grade_band_bypass:
				grade = session.execute(
					sa.select(OrgJobGrade)
					.where(OrgJobGrade.tenant_id == employee.tenant_id)
					.where(OrgJobGrade.grade_code == grade_code)
					.where(OrgJobGrade.effective_date <= eff)
					.order_by(sa.desc(OrgJobGrade.effective_date))
					.limit(1)
				).scalar_one_or_none()
				if grade is not None:
					if not (grade.min_amount_cents <= amount <= grade.max_amount_cents):
						raise CompensationError(
							f"Amount {amount}¢ is outside grade band {grade_code!r} "
							f"[{grade.min_amount_cents}¢ – {grade.max_amount_cents}¢]. "
							f"Pass grade_band_check_bypass={{approver_id, reason}} to override."
						)

		# Approval threshold — default 10_000_000 cents = 100,000 KES
		comp_approval_threshold = int(data.get("comp_approval_threshold_cents", 10_000_000))
		approval_status = "APPROVED"
		if amount > comp_approval_threshold:
			approval_status = "PENDING"
			log.info(
				"PersonnelService.record_compensation: amount %d¢ exceeds threshold %d¢ — PENDING approval",
				amount, comp_approval_threshold,
			)

		comp = EmployeeCompensation(
			tenant_id=employee.tenant_id,
			employee_id=employee.id,
			effective_date=eff,
			pay_type=(data.get("pay_type") or "SALARY").upper(),
			amount_cents=amount,
			currency_code=(data.get("currency_code") or "KES").upper(),
			frequency=(data.get("frequency") or "ANNUAL").upper(),
			grade_code=grade_code,
			reason=(data.get("reason") or "OTHER").upper(),
			approved_by=data.get("approved_by"),
			approval_status=approval_status,
		)
		session.add(comp)
		session.flush()

		try:
			emit_event(
				CompensationChangedEvent(
					aggregate_id=comp.id,
					aggregate_type="EmployeeCompensation",
					tenant_id=employee.tenant_id,
					compensation_id=comp.id,
					employee_id=employee.id,
					effective_date=eff.isoformat(),
					pay_type=comp.pay_type,
					amount_cents=amount,
					currency_code=comp.currency_code,
					frequency=comp.frequency,
					reason=comp.reason,
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.record_compensation: event emission failed (non-fatal): %s", evt_exc)

		log.info(
			"PersonnelService.record_compensation: emp=%s %d¢ %s eff=%s approval=%s",
			employee.employee_number, amount, comp.pay_type, eff, approval_status,
		)
		return comp

	def approve_compensation(self, comp_id: str, approver_id: str, session: Any) -> Any:
		"""Approve a PENDING compensation record.

		Only APPROVED records are considered by current_compensation.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeCompensation
		from pgappforge.plugins.erp.hcm.personnel.events import CompensationApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		comp = session.get(EmployeeCompensation, comp_id)
		if comp is None:
			raise CompensationError(f"EmployeeCompensation {comp_id!r} not found")
		if comp.approval_status != "PENDING":
			raise CompensationError(
				f"Cannot approve compensation with status {comp.approval_status!r}"
			)

		comp.approval_status = "APPROVED"
		comp.approved_by = approver_id
		comp.updated_at = _now()

		try:
			emit_event(
				CompensationApprovedEvent(
					aggregate_id=comp_id,
					aggregate_type="EmployeeCompensation",
					tenant_id=comp.tenant_id,
					compensation_id=comp_id,
					employee_id=comp.employee_id,
					approved_by=approver_id,
					amount_cents=comp.amount_cents,
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.approve_compensation: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.approve_compensation: comp=%s approved by %s", comp_id, approver_id)
		return comp

	def reject_compensation(self, comp_id: str, approver_id: str, reason: str, session: Any) -> Any:
		"""Reject a PENDING compensation record."""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeCompensation

		comp = session.get(EmployeeCompensation, comp_id)
		if comp is None:
			raise CompensationError(f"EmployeeCompensation {comp_id!r} not found")
		if comp.approval_status != "PENDING":
			raise CompensationError(
				f"Cannot reject compensation with status {comp.approval_status!r}"
			)

		comp.approval_status = "REJECTED"
		comp.approved_by = approver_id
		comp.approval_rejected_reason = reason
		comp.updated_at = _now()

		log.info("PersonnelService.reject_compensation: comp=%s rejected by %s", comp_id, approver_id)
		return comp

	def current_compensation(self, employee_id: str, session: Any) -> Any | None:
		"""Return the active (APPROVED) EmployeeCompensation row for an employee.

		Active = highest effective_date <= today with approval_status=APPROVED.
		Returns None if no approved compensation record exists.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeCompensation

		today = _today()
		return session.execute(
			sa.select(EmployeeCompensation)
			.where(EmployeeCompensation.employee_id == employee_id)
			.where(EmployeeCompensation.effective_date <= today)
			.where(EmployeeCompensation.approval_status == "APPROVED")
			.order_by(sa.desc(EmployeeCompensation.effective_date))
			.limit(1)
		).scalar_one_or_none()

	# ==========================================================================
	# Documents
	# ==========================================================================

	def attach_document(self, data: dict[str, Any], session: Any) -> Any:
		"""Attach a document metadata record to an employee.

		Version history: if an active document of the same document_type already
		exists for this employee, it is superseded (superseded_by_id set on old,
		version incremented on new, is_verified reset to False).
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, EmployeeDocument

		employee = session.get(Employee, data.get("employee_id", ""))
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {data.get('employee_id')!r} not found")

		issued = _parse_date(data.get("issued_date"))
		expiry = _parse_date(data.get("expiry_date"))
		doc_type = data["document_type"].upper()

		# Find existing active document of same type for version chain
		existing = session.execute(
			sa.select(EmployeeDocument)
			.where(EmployeeDocument.employee_id == employee.id)
			.where(EmployeeDocument.document_type == doc_type)
			.where(EmployeeDocument.superseded_by_id.is_(None))
			.order_by(sa.desc(EmployeeDocument.version))
			.limit(1)
		).scalar_one_or_none()

		next_version = 1
		if existing is not None:
			next_version = (existing.version or 1) + 1

		doc = EmployeeDocument(
			tenant_id=employee.tenant_id,
			employee_id=employee.id,
			document_type=doc_type,
			filename=data["filename"],
			storage_url=data["storage_url"],
			issued_date=issued,
			expiry_date=expiry,
			is_verified=False,
			version=next_version,
		)
		session.add(doc)
		session.flush()

		# Link supersession chain
		if existing is not None:
			existing.superseded_by_id = doc.id
			existing.updated_at = _now()

		return doc

	def verify_document(self, document_id: str, session: Any) -> Any:
		"""Mark a document as verified by HR."""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeDocument
		from pgappforge.plugins.erp.hcm.personnel.events import DocumentVerifiedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		doc = session.get(EmployeeDocument, document_id)
		if doc is None:
			raise DocumentError(f"EmployeeDocument {document_id!r} not found")

		doc.is_verified = True
		doc.updated_at = _now()

		try:
			emit_event(
				DocumentVerifiedEvent(
					aggregate_id=document_id,
					aggregate_type="EmployeeDocument",
					tenant_id=doc.tenant_id,
					document_id=document_id,
					employee_id=doc.employee_id,
					document_type=doc.document_type,
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.verify_document: event emission failed (non-fatal): %s", evt_exc)

		return doc

	def expiring_documents(
		self,
		tenant_id: str,
		session: Any,
		within_days: int = 30,
	) -> list[Any]:
		"""Return active EmployeeDocument rows expiring within *within_days* days."""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeDocument

		today = _today()
		cutoff = today + timedelta(days=within_days)
		return session.execute(
			sa.select(EmployeeDocument)
			.where(EmployeeDocument.tenant_id == tenant_id)
			.where(EmployeeDocument.expiry_date.isnot(None))
			.where(EmployeeDocument.expiry_date <= cutoff)
			.where(EmployeeDocument.expiry_date >= today)
			.where(EmployeeDocument.superseded_by_id.is_(None))  # active docs only
			.order_by(EmployeeDocument.expiry_date)
		).scalars().all()

	# ==========================================================================
	# Employment Contract lifecycle
	# ==========================================================================

	def issue_offer(self, employee_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Create or transition a contract to OFFERED state.

		If no contract exists, creates one in DRAFT then transitions to OFFERED.
		If a DRAFT contract exists for this employee, transitions it to OFFERED.

		Args:
			data: dict with keys:
			  contract_type (opt, default PERMANENT),
			  start_date (req ISO date),
			  end_date (opt ISO date — for FIXED_TERM),
			  notice_period_days (opt, default 28 per EA s.35),
			  offer_date (opt ISO date, defaults to today),
			  notes (opt str)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, EmploymentContract
		from pgappforge.plugins.erp.hcm.personnel.events import ContractIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		start = _require_date(data.get("start_date"), "start_date")
		offer_date = _parse_date(data.get("offer_date")) or _today()
		end_date = _parse_date(data.get("end_date"))
		contract_type = (data.get("contract_type") or "PERMANENT").upper()
		notice_period_days = int(data.get("notice_period_days", 28))

		# Find existing DRAFT contract or create new
		existing = session.execute(
			sa.select(EmploymentContract)
			.where(EmploymentContract.employee_id == employee_id)
			.where(EmploymentContract.status == "DRAFT")
			.order_by(sa.desc(EmploymentContract.created_at))
			.limit(1)
		).scalar_one_or_none()

		if existing is not None:
			_assert_status_transition("DRAFT", "OFFERED", _VALID_CONTRACT_TRANSITIONS, "contract status")
			contract = existing
			contract.contract_type = contract_type
			contract.start_date = start
			contract.end_date = end_date
			contract.notice_period_days = notice_period_days
		else:
			contract = EmploymentContract(
				tenant_id=employee.tenant_id,
				employee_id=employee_id,
				contract_type=contract_type,
				status="DRAFT",
				start_date=start,
				end_date=end_date,
				notice_period_days=notice_period_days,
				notes=data.get("notes"),
			)
			session.add(contract)
			session.flush()

		contract.status = "OFFERED"
		contract.offer_date = offer_date
		contract.updated_at = _now()

		try:
			emit_event(
				ContractIssuedEvent(
					aggregate_id=contract.id,
					aggregate_type="EmploymentContract",
					tenant_id=employee.tenant_id,
					contract_id=contract.id,
					employee_id=employee_id,
					contract_type=contract.contract_type,
					offer_date=offer_date.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.issue_offer: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.issue_offer: contract=%s emp=%s", contract.id, employee.employee_number)
		return contract

	def accept_offer(self, contract_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Transition contract to ACCEPTED.

		Args:
			data: dict with keys: accepted_date (opt ISO date, defaults to today)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import EmploymentContract
		from pgappforge.plugins.erp.hcm.personnel.events import ContractAcceptedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		contract = session.get(EmploymentContract, contract_id)
		if contract is None:
			raise ContractError(f"EmploymentContract {contract_id!r} not found")

		_assert_status_transition(contract.status, "ACCEPTED", _VALID_CONTRACT_TRANSITIONS, "contract status")

		accepted_date = _parse_date(data.get("accepted_date")) or _today()
		contract.status = "ACCEPTED"
		contract.accepted_date = accepted_date
		contract.updated_at = _now()

		try:
			emit_event(
				ContractAcceptedEvent(
					aggregate_id=contract_id,
					aggregate_type="EmploymentContract",
					tenant_id=contract.tenant_id,
					contract_id=contract_id,
					employee_id=contract.employee_id,
					accepted_date=accepted_date.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.accept_offer: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.accept_offer: contract=%s accepted", contract_id)
		return contract

	def activate_contract(self, contract_id: str, session: Any) -> Any:
		"""Transition contract from ACCEPTED to ACTIVE (probation confirmed)."""
		from pgappforge.plugins.erp.hcm.personnel.models import EmploymentContract

		contract = session.get(EmploymentContract, contract_id)
		if contract is None:
			raise ContractError(f"EmploymentContract {contract_id!r} not found")

		_assert_status_transition(contract.status, "ACTIVE", _VALID_CONTRACT_TRANSITIONS, "contract status")

		contract.status = "ACTIVE"
		contract.confirmed_date = contract.confirmed_date or _today()
		contract.updated_at = _now()

		log.info("PersonnelService.activate_contract: contract=%s ACTIVE", contract_id)
		return contract

	def terminate_contract(self, contract_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Terminate a contract at any post-DRAFT stage.

		Args:
			data: dict with keys: terminated_date (opt ISO date, defaults to today)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import EmploymentContract
		from pgappforge.plugins.erp.hcm.personnel.events import ContractTerminatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		contract = session.get(EmploymentContract, contract_id)
		if contract is None:
			raise ContractError(f"EmploymentContract {contract_id!r} not found")

		_assert_status_transition(contract.status, "TERMINATED", _VALID_CONTRACT_TRANSITIONS, "contract status")

		terminated_date = _parse_date(data.get("terminated_date")) or _today()
		contract.status = "TERMINATED"
		contract.terminated_date = terminated_date
		contract.updated_at = _now()

		try:
			emit_event(
				ContractTerminatedEvent(
					aggregate_id=contract_id,
					aggregate_type="EmploymentContract",
					tenant_id=contract.tenant_id,
					contract_id=contract_id,
					employee_id=contract.employee_id,
					terminated_date=terminated_date.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.terminate_contract: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.terminate_contract: contract=%s terminated", contract_id)
		return contract

	# ==========================================================================
	# Disciplinary workflow
	# ==========================================================================

	def open_disciplinary_case(self, data: dict[str, Any], session: Any) -> Any:
		"""Open a new disciplinary case.

		Args:
			data: dict with keys:
			  tenant_id (req), employee_id (req),
			  case_type (req: VERBAL_WARNING|WRITTEN_WARNING|FINAL_WARNING|DISMISSAL|OTHER),
			  offence_description (req),
			  offence_date (opt ISO date),
			  presiding_officer_id (opt UUID),
			  case_number (opt — auto-generated if absent)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, DisciplinaryCase
		from pgappforge.plugins.erp.hcm.personnel.events import DisciplinaryCaseOpenedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "employee_id", "case_type", "offence_description")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise DisciplinaryError(f"Missing required fields: {missing}")

		employee = session.get(Employee, data["employee_id"])
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {data['employee_id']!r} not found")

		valid_case_types = {"VERBAL_WARNING", "WRITTEN_WARNING", "FINAL_WARNING", "DISMISSAL", "OTHER"}
		case_type = data["case_type"].upper()
		if case_type not in valid_case_types:
			raise DisciplinaryError(f"case_type must be one of {valid_case_types}")

		# Auto-generate case number
		case_number = data.get("case_number") or self._next_case_number("DISC", data["tenant_id"], session)

		case = DisciplinaryCase(
			tenant_id=data["tenant_id"],
			employee_id=data["employee_id"],
			case_number=case_number,
			case_type=case_type,
			status="OPEN",
			offence_description=data["offence_description"],
			offence_date=_parse_date(data.get("offence_date")),
			presiding_officer_id=data.get("presiding_officer_id"),
		)
		session.add(case)
		session.flush()

		try:
			emit_event(
				DisciplinaryCaseOpenedEvent(
					aggregate_id=case.id,
					aggregate_type="DisciplinaryCase",
					tenant_id=data["tenant_id"],
					case_id=case.id,
					case_number=case_number,
					employee_id=data["employee_id"],
					case_type=case_type,
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.open_disciplinary_case: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.open_disciplinary_case: case=%s emp=%s type=%s", case.id, employee.employee_number, case_type)
		return case

	def issue_show_cause(self, case_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Issue a show-cause notice, transitioning case to SHOW_CAUSE_ISSUED.

		Args:
			data: dict with keys: issued_at (opt ISO date, defaults today), notes (opt)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import DisciplinaryCase

		case = session.get(DisciplinaryCase, case_id)
		if case is None:
			raise DisciplinaryError(f"DisciplinaryCase {case_id!r} not found")

		_assert_status_transition(case.status, "SHOW_CAUSE_ISSUED", _VALID_DISC_TRANSITIONS, "disciplinary case status")

		case.status = "SHOW_CAUSE_ISSUED"
		case.show_cause_issued_at = _parse_date(data.get("issued_at")) or _today()
		case.updated_at = _now()

		log.info("PersonnelService.issue_show_cause: case=%s", case_id)
		return case

	def schedule_hearing(self, case_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Schedule a disciplinary hearing.

		Args:
			data: dict with keys: hearing_date (req ISO date)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import DisciplinaryCase

		case = session.get(DisciplinaryCase, case_id)
		if case is None:
			raise DisciplinaryError(f"DisciplinaryCase {case_id!r} not found")

		_assert_status_transition(case.status, "HEARING_SCHEDULED", _VALID_DISC_TRANSITIONS, "disciplinary case status")

		hearing_date = _require_date(data.get("hearing_date"), "hearing_date")
		case.status = "HEARING_SCHEDULED"
		case.hearing_date = hearing_date
		case.updated_at = _now()

		log.info("PersonnelService.schedule_hearing: case=%s hearing=%s", case_id, hearing_date)
		return case

	def record_hearing_outcome(self, case_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Record hearing outcome and transition case to HEARING_COMPLETE.

		Args:
			data: dict with keys:
			  outcome (req: WARNING_ISSUED|DISMISSED|SUSPENDED|EXONERATED|OTHER),
			  outcome_date (opt ISO date, defaults to today),
			  outcome_notes (opt str),
			  hearing_notes (opt str),
			  suspension_start_date (opt ISO date — required when outcome=SUSPENDED),
			  suspension_end_date (opt ISO date),
			  suspension_is_paid (opt bool, default True)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import DisciplinaryCase
		from pgappforge.plugins.erp.hcm.personnel.events import DisciplinaryOutcomeRecordedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		case = session.get(DisciplinaryCase, case_id)
		if case is None:
			raise DisciplinaryError(f"DisciplinaryCase {case_id!r} not found")

		_assert_status_transition(case.status, "HEARING_COMPLETE", _VALID_DISC_TRANSITIONS, "disciplinary case status")

		valid_outcomes = {"WARNING_ISSUED", "DISMISSED", "SUSPENDED", "EXONERATED", "OTHER"}
		outcome = (data.get("outcome") or "").upper()
		if outcome not in valid_outcomes:
			raise DisciplinaryError(f"outcome must be one of {valid_outcomes}")

		outcome_date = _parse_date(data.get("outcome_date")) or _today()

		case.status = "HEARING_COMPLETE"
		case.outcome = outcome
		case.outcome_date = outcome_date
		case.outcome_notes = data.get("outcome_notes")
		if data.get("hearing_notes"):
			case.hearing_notes = data["hearing_notes"]

		if outcome == "SUSPENDED":
			susp_start = _parse_date(data.get("suspension_start_date"))
			if susp_start is None:
				raise DisciplinaryError("suspension_start_date required when outcome=SUSPENDED")
			case.suspension_start_date = susp_start
			case.suspension_end_date = _parse_date(data.get("suspension_end_date"))
			case.suspension_is_paid = bool(data.get("suspension_is_paid", True))

		case.updated_at = _now()

		try:
			emit_event(
				DisciplinaryOutcomeRecordedEvent(
					aggregate_id=case_id,
					aggregate_type="DisciplinaryCase",
					tenant_id=case.tenant_id,
					case_id=case_id,
					employee_id=case.employee_id,
					outcome=outcome,
					outcome_date=outcome_date.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.record_hearing_outcome: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.record_hearing_outcome: case=%s outcome=%s", case_id, outcome)
		return case

	def close_disciplinary_case(self, case_id: str, session: Any) -> Any:
		"""Close a disciplinary case (must be HEARING_COMPLETE or OPEN for early close)."""
		from pgappforge.plugins.erp.hcm.personnel.models import DisciplinaryCase

		case = session.get(DisciplinaryCase, case_id)
		if case is None:
			raise DisciplinaryError(f"DisciplinaryCase {case_id!r} not found")

		_assert_status_transition(case.status, "CLOSED", _VALID_DISC_TRANSITIONS, "disciplinary case status")

		case.status = "CLOSED"
		case.updated_at = _now()

		log.info("PersonnelService.close_disciplinary_case: case=%s closed", case_id)
		return case

	# ==========================================================================
	# Grievance management
	# ==========================================================================

	def lodge_grievance(self, data: dict[str, Any], session: Any) -> Any:
		"""Lodge a new grievance case.

		Kenya Employment Act s.47 requires internal grievance procedures.

		Args:
			data: dict with keys:
			  tenant_id (req), filed_by_employee_id (req),
			  grievance_type (req: HARASSMENT|DISCRIMINATION|UNSAFE_CONDITIONS|COMPENSATION|OTHER),
			  description (req),
			  filed_date (opt ISO date, defaults to today),
			  due_date (opt ISO date — SLA deadline),
			  respondent_employee_id (opt UUID),
			  assigned_to_id (opt UUID),
			  case_number (opt — auto-generated if absent)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, GrievanceCase
		from pgappforge.plugins.erp.hcm.personnel.events import GrievanceFiledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "filed_by_employee_id", "grievance_type", "description")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise GrievanceError(f"Missing required fields: {missing}")

		employee = session.get(Employee, data["filed_by_employee_id"])
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {data['filed_by_employee_id']!r} not found")

		valid_types = {"HARASSMENT", "DISCRIMINATION", "UNSAFE_CONDITIONS", "COMPENSATION", "OTHER"}
		grievance_type = data["grievance_type"].upper()
		if grievance_type not in valid_types:
			raise GrievanceError(f"grievance_type must be one of {valid_types}")

		filed_date = _parse_date(data.get("filed_date")) or _today()
		case_number = data.get("case_number") or self._next_case_number("GRIEV", data["tenant_id"], session)

		case = GrievanceCase(
			tenant_id=data["tenant_id"],
			filed_by_employee_id=data["filed_by_employee_id"],
			respondent_employee_id=data.get("respondent_employee_id"),
			assigned_to_id=data.get("assigned_to_id"),
			case_number=case_number,
			grievance_type=grievance_type,
			status="FILED",
			description=data["description"],
			filed_date=filed_date,
			due_date=_parse_date(data.get("due_date")),
		)
		session.add(case)
		session.flush()

		try:
			emit_event(
				GrievanceFiledEvent(
					aggregate_id=case.id,
					aggregate_type="GrievanceCase",
					tenant_id=data["tenant_id"],
					case_id=case.id,
					case_number=case_number,
					employee_id=data["filed_by_employee_id"],
					grievance_type=grievance_type,
					filed_date=filed_date.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.lodge_grievance: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.lodge_grievance: case=%s emp=%s type=%s", case.id, employee.employee_number, grievance_type)
		return case

	def acknowledge_grievance(self, case_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Acknowledge a filed grievance.

		Args:
			data: dict with keys:
			  acknowledged_date (opt ISO date, defaults to today),
			  assigned_to_id (opt UUID)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import GrievanceCase

		case = session.get(GrievanceCase, case_id)
		if case is None:
			raise GrievanceError(f"GrievanceCase {case_id!r} not found")

		_assert_status_transition(case.status, "ACKNOWLEDGED", _VALID_GRIEVANCE_TRANSITIONS, "grievance status")

		case.status = "ACKNOWLEDGED"
		case.acknowledged_date = _parse_date(data.get("acknowledged_date")) or _today()
		if data.get("assigned_to_id"):
			case.assigned_to_id = data["assigned_to_id"]
		case.updated_at = _now()

		log.info("PersonnelService.acknowledge_grievance: case=%s", case_id)
		return case

	def review_grievance(self, case_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Move grievance to UNDER_REVIEW.

		Args:
			data: dict with keys: assigned_to_id (opt UUID)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import GrievanceCase

		case = session.get(GrievanceCase, case_id)
		if case is None:
			raise GrievanceError(f"GrievanceCase {case_id!r} not found")

		_assert_status_transition(case.status, "UNDER_REVIEW", _VALID_GRIEVANCE_TRANSITIONS, "grievance status")

		case.status = "UNDER_REVIEW"
		if data.get("assigned_to_id"):
			case.assigned_to_id = data["assigned_to_id"]
		case.updated_at = _now()

		log.info("PersonnelService.review_grievance: case=%s UNDER_REVIEW", case_id)
		return case

	def resolve_grievance(self, case_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Resolve a grievance.

		Args:
			data: dict with keys:
			  resolution_notes (req),
			  resolved_date (opt ISO date, defaults to today)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import GrievanceCase
		from pgappforge.plugins.erp.hcm.personnel.events import GrievanceResolvedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		case = session.get(GrievanceCase, case_id)
		if case is None:
			raise GrievanceError(f"GrievanceCase {case_id!r} not found")

		_assert_status_transition(case.status, "RESOLVED", _VALID_GRIEVANCE_TRANSITIONS, "grievance status")

		resolution_notes = (data.get("resolution_notes") or "").strip()
		if not resolution_notes:
			raise GrievanceError("resolution_notes is required to resolve a grievance")

		resolved_date = _parse_date(data.get("resolved_date")) or _today()
		case.status = "RESOLVED"
		case.resolution_notes = resolution_notes
		case.resolved_date = resolved_date
		case.updated_at = _now()

		try:
			emit_event(
				GrievanceResolvedEvent(
					aggregate_id=case_id,
					aggregate_type="GrievanceCase",
					tenant_id=case.tenant_id,
					case_id=case_id,
					employee_id=case.filed_by_employee_id,
					resolved_date=resolved_date.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.resolve_grievance: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.resolve_grievance: case=%s resolved", case_id)
		return case

	def escalate_grievance(self, case_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Escalate a grievance.

		Args:
			data: dict with keys:
			  escalated_to_id (req UUID),
			  escalation_reason (req str)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import GrievanceCase
		from pgappforge.plugins.erp.hcm.personnel.events import GrievanceEscalatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		case = session.get(GrievanceCase, case_id)
		if case is None:
			raise GrievanceError(f"GrievanceCase {case_id!r} not found")

		_assert_status_transition(case.status, "ESCALATED", _VALID_GRIEVANCE_TRANSITIONS, "grievance status")

		escalated_to_id = data.get("escalated_to_id") or ""
		escalation_reason = (data.get("escalation_reason") or "").strip()
		if not escalated_to_id:
			raise GrievanceError("escalated_to_id is required")
		if not escalation_reason:
			raise GrievanceError("escalation_reason is required")

		case.status = "ESCALATED"
		case.escalated_to_id = escalated_to_id
		case.escalation_reason = escalation_reason
		case.updated_at = _now()

		try:
			emit_event(
				GrievanceEscalatedEvent(
					aggregate_id=case_id,
					aggregate_type="GrievanceCase",
					tenant_id=case.tenant_id,
					case_id=case_id,
					employee_id=case.filed_by_employee_id,
					escalated_to_id=escalated_to_id,
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.escalate_grievance: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.escalate_grievance: case=%s escalated to %s", case_id, escalated_to_id)
		return case

	def overdue_grievances(self, tenant_id: str, session: Any) -> list[Any]:
		"""Return open grievances past their due_date.

		Status in (FILED, ACKNOWLEDGED, UNDER_REVIEW, ESCALATED) and due_date < today.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import GrievanceCase

		today = _today()
		open_statuses = ("FILED", "ACKNOWLEDGED", "UNDER_REVIEW", "ESCALATED")
		return session.execute(
			sa.select(GrievanceCase)
			.where(GrievanceCase.tenant_id == tenant_id)
			.where(GrievanceCase.status.in_(open_statuses))
			.where(GrievanceCase.due_date.isnot(None))
			.where(GrievanceCase.due_date < today)
			.order_by(GrievanceCase.due_date)
		).scalars().all()

	# ==========================================================================
	# Onboarding
	# ==========================================================================

	def create_onboarding_plan(self, employee_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Create an onboarding plan for a new employee.

		Args:
			data: dict with keys:
			  tenant_id (req),
			  checklist_items (req list of {key, label, due_days_from_start, owner_role}),
			  template_id (opt UUID),
			  assigned_buddy_id (opt UUID),
			  induction_date (opt ISO date),
			  target_completion_date (opt ISO date)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, OnboardingPlan

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		tenant_id = data.get("tenant_id") or employee.tenant_id
		raw_items = data.get("checklist_items") or []

		checklist_items = [
			{
				"key": item.get("key", f"item_{i}"),
				"label": item.get("label", ""),
				"due_days_from_start": int(item.get("due_days_from_start", 30)),
				"owner_role": item.get("owner_role", "HR"),
				"completed_at": None,
				"completed_by": None,
			}
			for i, item in enumerate(raw_items)
		]

		plan = OnboardingPlan(
			tenant_id=tenant_id,
			employee_id=employee_id,
			template_id=data.get("template_id"),
			assigned_buddy_id=data.get("assigned_buddy_id"),
			induction_date=_parse_date(data.get("induction_date")),
			target_completion_date=_parse_date(data.get("target_completion_date")),
			status="PENDING",
			checklist_items=checklist_items,
		)
		session.add(plan)
		session.flush()

		log.info("PersonnelService.create_onboarding_plan: plan=%s emp=%s items=%d",
				 plan.id, employee.employee_number, len(checklist_items))
		return plan

	def complete_onboarding_item(
		self,
		plan_id: str,
		item_key: str,
		data: dict[str, Any],
		session: Any,
	) -> Any:
		"""Mark an onboarding checklist item as complete.

		Fires OnboardingCompletedEvent when all items are done.

		Args:
			plan_id: UUID of the OnboardingPlan.
			item_key: key of the checklist item to complete.
			data: dict with keys: completed_by (opt UUID/str)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import OnboardingPlan
		from pgappforge.plugins.erp.hcm.personnel.events import OnboardingCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		plan = session.get(OnboardingPlan, plan_id)
		if plan is None:
			raise PersonnelServiceError(f"OnboardingPlan {plan_id!r} not found")

		if plan.status == "COMPLETED":
			raise PersonnelServiceError(f"OnboardingPlan {plan_id!r} is already COMPLETED")
		if plan.status == "CANCELLED":
			raise PersonnelServiceError(f"OnboardingPlan {plan_id!r} is CANCELLED")

		items: list[dict[str, Any]] = list(plan.checklist_items or [])
		found = False
		for item in items:
			if item.get("key") == item_key:
				if item.get("completed_at") is not None:
					raise PersonnelServiceError(f"Onboarding item {item_key!r} is already completed")
				item["completed_at"] = _now().isoformat()
				item["completed_by"] = data.get("completed_by") or ""
				found = True
				break

		if not found:
			raise PersonnelServiceError(f"Onboarding item key {item_key!r} not found in plan {plan_id!r}")

		plan.checklist_items = items
		plan.status = "IN_PROGRESS"
		plan.updated_at = _now()

		# Check if all done
		all_done = all(item.get("completed_at") is not None for item in items)
		if all_done:
			completed_date = _today()
			plan.status = "COMPLETED"
			plan.completed_date = completed_date
			try:
				emit_event(
					OnboardingCompletedEvent(
						aggregate_id=plan_id,
						aggregate_type="OnboardingPlan",
						tenant_id=plan.tenant_id,
						plan_id=plan_id,
						employee_id=plan.employee_id,
						completed_date=completed_date.isoformat(),
					),
					session,
				)
			except Exception as evt_exc:
				log.warning("PersonnelService.complete_onboarding_item: OnboardingCompletedEvent failed (non-fatal): %s", evt_exc)
			log.info("PersonnelService.complete_onboarding_item: plan=%s ALL COMPLETE", plan_id)
		else:
			log.info(
				"PersonnelService.complete_onboarding_item: plan=%s item=%r completed (%d/%d done)",
				plan_id, item_key,
				sum(1 for i in items if i.get("completed_at")),
				len(items),
			)

		return plan

	# ==========================================================================
	# Exit / offboarding
	# ==========================================================================

	def initiate_exit(self, employee_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Create an exit record linked to an employee.

		Typically called automatically by terminate_employee, but can be called
		independently for structured offboarding before finalising termination.

		Args:
			data: dict with keys:
			  exit_type (req: RESIGNATION|REDUNDANCY|RETIREMENT|DISMISSAL|END_OF_CONTRACT|DEATH),
			  last_working_day (req ISO date),
			  resignation_date (opt ISO date),
			  exit_interview_date (opt ISO date),
			  exit_reason (opt str),
			  notice_period_days (opt int),
			  notice_waived (opt bool),
			  notice_waiver_reason (opt str),
			  clearance_items (opt list of {key, label} — defaults to standard 8 items),
			  currency_code (opt, default KES)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, EmployeeExit
		from pgappforge.plugins.erp.hcm.personnel.events import ExitInitiatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		valid_exit_types = {
			"RESIGNATION", "REDUNDANCY", "RETIREMENT",
			"DISMISSAL", "END_OF_CONTRACT", "DEATH",
		}
		exit_type = (data.get("exit_type") or "").upper()
		if exit_type not in valid_exit_types:
			raise ExitError(f"exit_type must be one of {valid_exit_types}")

		last_working_day = _require_date(data.get("last_working_day"), "last_working_day")

		# Default clearance checklist
		default_clearance_keys = [
			("IT_EQUIPMENT",    "Return all IT equipment (laptop, phone, accessories)"),
			("ACCESS_CARDS",    "Return access cards and building passes"),
			("LOANS",           "Settle outstanding company loans"),
			("LIBRARY",         "Return library books / company materials"),
			("SACCO_DEDUCTIONS","Process final SACCO deduction"),
			("ID_BADGE",        "Return company ID badge"),
			("COMPANY_PROPERTY","Return all company property"),
			("HR_DOCUMENTS",    "Complete HR exit documentation"),
		]
		raw_items = data.get("clearance_items") or []
		if raw_items:
			clearance_items = [
				{"key": i.get("key", f"item_{n}"), "label": i.get("label", ""), "cleared_by": None, "cleared_at": None, "notes": None}
				for n, i in enumerate(raw_items)
			]
		else:
			clearance_items = [
				{"key": k, "label": lbl, "cleared_by": None, "cleared_at": None, "notes": None}
				for k, lbl in default_clearance_keys
			]

		exit_record = EmployeeExit(
			tenant_id=employee.tenant_id,
			employee_id=employee_id,
			exit_type=exit_type,
			status="INITIATED",
			resignation_date=_parse_date(data.get("resignation_date")),
			last_working_day=last_working_day,
			exit_interview_date=_parse_date(data.get("exit_interview_date")),
			exit_reason=data.get("exit_reason"),
			notice_period_days=data.get("notice_period_days"),
			notice_waived=bool(data.get("notice_waived", False)),
			notice_waiver_reason=data.get("notice_waiver_reason"),
			clearance_items=clearance_items,
			currency_code=(data.get("currency_code") or "KES").upper(),
		)
		session.add(exit_record)
		session.flush()

		try:
			emit_event(
				ExitInitiatedEvent(
					aggregate_id=exit_record.id,
					aggregate_type="EmployeeExit",
					tenant_id=employee.tenant_id,
					exit_id=exit_record.id,
					employee_id=employee_id,
					exit_type=exit_type,
					last_working_day=last_working_day.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.initiate_exit: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.initiate_exit: exit=%s emp=%s type=%s", exit_record.id, employee.employee_number, exit_type)
		return exit_record

	def clear_exit_item(
		self,
		exit_id: str,
		item_key: str,
		data: dict[str, Any],
		session: Any,
	) -> Any:
		"""Mark a clearance item as cleared.

		Args:
			data: dict with keys: cleared_by (req UUID/str), notes (opt str)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeExit
		from pgappforge.plugins.erp.hcm.personnel.events import ExitClearedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		exit_record = session.get(EmployeeExit, exit_id)
		if exit_record is None:
			raise ExitError(f"EmployeeExit {exit_id!r} not found")

		if exit_record.status == "CLOSED":
			raise ExitError(f"Exit record {exit_id!r} is already CLOSED")

		cleared_by = (data.get("cleared_by") or "").strip()
		if not cleared_by:
			raise ExitError("cleared_by is required")

		items: list[dict[str, Any]] = list(exit_record.clearance_items or [])
		found = False
		for item in items:
			if item.get("key") == item_key:
				if item.get("cleared_at") is not None:
					raise ExitError(f"Clearance item {item_key!r} is already cleared")
				item["cleared_by"] = cleared_by
				item["cleared_at"] = _now().isoformat()
				item["notes"] = data.get("notes") or ""
				found = True
				break

		if not found:
			raise ExitError(f"Clearance item key {item_key!r} not found in exit {exit_id!r}")

		exit_record.clearance_items = items

		# Transition to IN_PROGRESS if still INITIATED
		if exit_record.status == "INITIATED":
			_assert_status_transition(exit_record.status, "IN_PROGRESS", _VALID_EXIT_TRANSITIONS, "exit status")
			exit_record.status = "IN_PROGRESS"

		# All items cleared → CLEARED
		all_cleared = all(item.get("cleared_at") is not None for item in items)
		if all_cleared:
			_assert_status_transition(exit_record.status, "CLEARED", _VALID_EXIT_TRANSITIONS, "exit status")
			cleared_date = _today()
			exit_record.status = "CLEARED"
			exit_record.cleared_date = cleared_date
			exit_record.updated_at = _now()
			try:
				emit_event(
					ExitClearedEvent(
						aggregate_id=exit_id,
						aggregate_type="EmployeeExit",
						tenant_id=exit_record.tenant_id,
						exit_id=exit_id,
						employee_id=exit_record.employee_id,
						cleared_date=cleared_date.isoformat(),
					),
					session,
				)
			except Exception as evt_exc:
				log.warning("PersonnelService.clear_exit_item: ExitClearedEvent failed (non-fatal): %s", evt_exc)
			log.info("PersonnelService.clear_exit_item: exit=%s ALL CLEARED", exit_id)
		else:
			exit_record.updated_at = _now()

		return exit_record

	def close_exit(self, exit_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Close an exit record — validates all clearance items are cleared.

		A closed exit record permits final payroll run (downstream check).

		Args:
			data: dict with keys:
			  closed_by_id (req UUID),
			  final_settlement_amount_cents (opt int),
			  certificate_issued (opt bool, default False),
			  settlement_paid_date (opt ISO date)
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeExit
		from pgappforge.plugins.erp.hcm.personnel.events import ExitClosedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		exit_record = session.get(EmployeeExit, exit_id)
		if exit_record is None:
			raise ExitError(f"EmployeeExit {exit_id!r} not found")

		_assert_status_transition(exit_record.status, "CLOSED", _VALID_EXIT_TRANSITIONS, "exit status")

		# Validate all clearance items cleared
		items: list[dict[str, Any]] = exit_record.clearance_items or []
		uncleared = [i["key"] for i in items if not i.get("cleared_at")]
		if uncleared:
			raise ExitError(
				f"Cannot close exit: the following clearance items are not yet cleared: {uncleared}"
			)

		closed_by_id = (data.get("closed_by_id") or "").strip()
		if not closed_by_id:
			raise ExitError("closed_by_id is required to close an exit")

		closed_date = _today()
		final_settlement = data.get("final_settlement_amount_cents")
		if final_settlement is not None:
			assert isinstance(final_settlement, int), "final_settlement_amount_cents must be int"
			exit_record.final_settlement_amount_cents = final_settlement

		exit_record.status = "CLOSED"
		exit_record.closed_by_id = closed_by_id
		exit_record.closed_date = closed_date
		exit_record.certificate_issued = bool(data.get("certificate_issued", False))
		if data.get("certificate_issued"):
			exit_record.certificate_issued_date = closed_date
		if data.get("settlement_paid_date"):
			exit_record.settlement_paid_date = _parse_date(data["settlement_paid_date"])
		exit_record.updated_at = _now()

		try:
			emit_event(
				ExitClosedEvent(
					aggregate_id=exit_id,
					aggregate_type="EmployeeExit",
					tenant_id=exit_record.tenant_id,
					exit_id=exit_id,
					employee_id=exit_record.employee_id,
					final_settlement_amount_cents=exit_record.final_settlement_amount_cents or 0,
					closed_date=closed_date.isoformat(),
				),
				session,
			)
		except Exception as evt_exc:
			log.warning("PersonnelService.close_exit: event emission failed (non-fatal): %s", evt_exc)

		log.info("PersonnelService.close_exit: exit=%s closed by %s", exit_id, closed_by_id)
		return exit_record

	def compute_redundancy_pay(
		self,
		employee_id: str,
		termination_date: date | str,
		session: Any,
	) -> dict[str, Any]:
		"""Compute redundancy pay per Kenya Employment Act 2007 s.40.

		Formula: 15 days basic pay per complete year of service.
		Monthly salary / 30 * (years_of_service * 15).

		Returns:
			dict with keys:
			  employee_id, start_date, termination_date,
			  years_of_service (float),
			  severance_days (int),
			  daily_rate_cents (int),
			  severance_amount_cents (int),
			  currency_code
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		term_date = _parse_date(termination_date)
		if term_date is None:
			raise PersonnelServiceError("termination_date is required")

		service_days = (term_date - employee.start_date).days
		years_of_service = service_days / 365.25
		complete_years = int(years_of_service)

		comp = self.current_compensation(employee_id, session)
		if comp is None:
			return {
				"employee_id": employee_id,
				"start_date": employee.start_date.isoformat(),
				"termination_date": term_date.isoformat(),
				"years_of_service": round(years_of_service, 4),
				"complete_years": complete_years,
				"severance_days": 0,
				"daily_rate_cents": 0,
				"severance_amount_cents": 0,
				"currency_code": "KES",
				"warning": "No approved compensation record found; severance_amount_cents=0",
			}

		# Normalise to monthly
		if comp.frequency == "ANNUAL":
			monthly_cents = comp.amount_cents // 12
		elif comp.frequency == "MONTHLY":
			monthly_cents = comp.amount_cents
		elif comp.frequency == "BIWEEKLY":
			monthly_cents = int(comp.amount_cents * 26 / 12)
		else:
			monthly_cents = comp.amount_cents  # HOURLY — best-effort

		daily_rate_cents = monthly_cents // 30
		severance_days = complete_years * 15
		severance_amount_cents = daily_rate_cents * severance_days

		return {
			"employee_id": employee_id,
			"start_date": employee.start_date.isoformat(),
			"termination_date": term_date.isoformat(),
			"years_of_service": round(years_of_service, 4),
			"complete_years": complete_years,
			"severance_days": severance_days,
			"daily_rate_cents": daily_rate_cents,
			"severance_amount_cents": severance_amount_cents,
			"currency_code": comp.currency_code,
		}

	# ==========================================================================
	# Analytics
	# ==========================================================================

	def headcount_summary(self, entity_id: str, session: Any) -> dict[str, Any]:
		"""Return headcount by employment_type × employment_status for an entity."""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee

		rows = session.execute(
			sa.select(
				Employee.employment_type,
				Employee.employment_status,
				sa.func.count().label("count"),
			)
			.where(Employee.entity_id == entity_id)
			.group_by(Employee.employment_type, Employee.employment_status)
			.order_by(Employee.employment_type, Employee.employment_status)
		).all()

		total_active = sum(r.count for r in rows if r.employment_status == "ACTIVE")
		breakdown = [
			{
				"employment_type": r.employment_type,
				"employment_status": r.employment_status,
				"count": r.count,
			}
			for r in rows
		]
		return {
			"entity_id": entity_id,
			"total_active": total_active,
			"breakdown": breakdown,
		}

	def headcount_budget_summary(self, entity_id: str, session: Any) -> dict[str, Any]:
		"""Return approved vs actual headcount per org unit within an entity.

		Joins against hcm_org_position to get approved_headcount.
		Returns: approved, filled (ACTIVE employees), vacant, over_budget per org_unit.

		Falls back to headcount_summary if org positions unavailable.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee

		try:
			from pgappforge.plugins.erp.hcm.org.models import Position  # type: ignore

			position_rows = session.execute(
				sa.select(
					Position.org_unit_id,
					sa.func.sum(Position.approved_headcount).label("approved"),
					sa.func.count().label("positions"),
				)
				.where(Position.entity_id == entity_id)
				.group_by(Position.org_unit_id)
			).all()

			approved_by_unit: dict[str | None, int] = {
				r.org_unit_id: int(r.approved or 0) for r in position_rows
			}
		except Exception as exc:
			log.warning("headcount_budget_summary: org.Position unavailable, returning basic summary: %s", exc)
			return self.headcount_summary(entity_id, session)

		filled_rows = session.execute(
			sa.select(
				Employee.org_unit_id,
				sa.func.count().label("filled"),
			)
			.where(Employee.entity_id == entity_id)
			.where(Employee.employment_status == "ACTIVE")
			.group_by(Employee.org_unit_id)
		).all()

		filled_by_unit: dict[str | None, int] = {r.org_unit_id: r.filled for r in filled_rows}

		all_units = set(approved_by_unit) | set(filled_by_unit)
		units_summary = []
		for unit_id in all_units:
			approved = approved_by_unit.get(unit_id, 0)
			filled = filled_by_unit.get(unit_id, 0)
			vacant = max(approved - filled, 0)
			over_budget = max(filled - approved, 0)
			utilisation_pct = round((filled / approved * 100) if approved else 0.0, 1)
			units_summary.append({
				"org_unit_id": unit_id,
				"approved": approved,
				"filled": filled,
				"vacant": vacant,
				"over_budget": over_budget,
				"utilisation_pct": utilisation_pct,
			})

		total_approved = sum(approved_by_unit.values())
		total_filled = sum(filled_by_unit.values())
		return {
			"entity_id": entity_id,
			"total_approved": total_approved,
			"total_filled": total_filled,
			"total_vacant": max(total_approved - total_filled, 0),
			"total_over_budget": max(total_filled - total_approved, 0),
			"utilisation_pct": round((total_filled / total_approved * 100) if total_approved else 0.0, 1),
			"by_org_unit": units_summary,
		}

	# ==========================================================================
	# Internal helpers
	# ==========================================================================

	@staticmethod
	def _next_case_number(prefix: str, tenant_id: str, session: Any) -> str:
		"""Generate a sequential human-readable case number.

		Format: {PREFIX}-{tenant_short}-{seq:05d}
		Falls back to timestamp if sequence creation fails.
		"""
		tenant_short = re.sub(r"[^a-f0-9]", "", tenant_id.lower())[:6].upper()
		seq_name = f"hcm_per_{prefix.lower()}_seq_{tenant_short.lower()}"
		try:
			session.execute(sa.text(
				f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1 INCREMENT 1 NO CYCLE"
			))
			next_val = session.execute(
				sa.text(f"SELECT nextval('{seq_name}')")
			).scalar_one()
			return f"{prefix}-{tenant_short}-{next_val:05d}"
		except Exception as exc:
			log.warning("_next_case_number: sequence unavailable for %s: %s", seq_name, exc)
			ts = int(datetime.now(timezone.utc).timestamp())
			return f"{prefix}-{tenant_short}-{ts}"


__all__ = [
	# Service
	"PersonnelService",
	# Exceptions
	"PersonnelServiceError",
	"EmployeeNotFoundError",
	"CompensationError",
	"DocumentError",
	"ContractError",
	"DisciplinaryError",
	"GrievanceError",
	"ExitError",
]
