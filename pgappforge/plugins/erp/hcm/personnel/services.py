"""
pgappforge/plugins/erp/hcm/personnel/services.py

PersonnelService — stateless business logic for the HCM Personnel plugin.

All public methods accept an explicit SQLAlchemy session.
Transaction boundaries owned by the caller.

Key public methods:
  hire_employee(data, session)                    -> Employee
  terminate_employee(employee_id, data, session)  -> Employee
  transfer_employee(employee_id, data, session)   -> Employee
  record_compensation(data, session)              -> EmployeeCompensation
  current_compensation(employee_id, session)      -> EmployeeCompensation | None
  attach_document(data, session)                  -> EmployeeDocument
  verify_document(document_id, session)           -> EmployeeDocument
  expiring_documents(tenant_id, days, session)    -> list[EmployeeDocument]
  headcount_summary(entity_id, session)           -> dict
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
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


# ---------------------------------------------------------------------------
# PersonnelService
# ---------------------------------------------------------------------------

class PersonnelService:
	"""Stateless Personnel domain service."""

	# ------------------------------------------------------------------
	# Employee hiring
	# ------------------------------------------------------------------

	def hire_employee(self, data: dict[str, Any], session: Any) -> Any:
		"""Create an Employee record and optionally fill their position.

		Amounts: amount_cents for initial compensation must be integer cents.

		Args:
			data: dict with keys:
			  tenant_id, employee_number, entity_id, start_date (ISO date),
			  employment_type, org_unit_id (opt), position_id (opt),
			  manager_id (opt), party_id (opt),
			  cost_center_code (opt),
			  initial_compensation (opt): {pay_type, amount_cents (int),
			    currency_code, frequency, grade_code}

		Returns:
			New Employee (not committed).
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, EmployeeCompensation
		from pgappforge.plugins.erp.hcm.personnel.events import EmployeeHiredEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "employee_number", "entity_id", "start_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise PersonnelServiceError(f"Missing required fields: {missing}")

		start = data["start_date"]
		if isinstance(start, str):
			start = date.fromisoformat(start)

		probation_end = data.get("probation_end_date")
		if isinstance(probation_end, str):
			probation_end = date.fromisoformat(probation_end)

		employee = Employee(
			tenant_id=data["tenant_id"],
			employee_number=data["employee_number"],
			entity_id=data["entity_id"],
			party_id=data.get("party_id"),
			position_id=data.get("position_id"),
			org_unit_id=data.get("org_unit_id"),
			manager_id=data.get("manager_id"),
			employment_type=data.get("employment_type", "FULL_TIME").upper(),
			employment_status="ACTIVE",
			start_date=start,
			probation_end_date=probation_end,
			cost_center_code=data.get("cost_center_code"),
			national_id_encrypted=data.get("national_id_encrypted"),
			tax_id_encrypted=data.get("tax_id_encrypted"),
			bank_account_iban_encrypted=data.get("bank_account_iban_encrypted"),
			bank_bic=data.get("bank_bic"),
			rehire_eligible=True,
		)
		session.add(employee)
		session.flush()

		# Optional initial compensation
		comp_data = data.get("initial_compensation")
		if comp_data:
			amount = comp_data.get("amount_cents")
			assert isinstance(amount, int), "initial_compensation.amount_cents must be int"
			session.add(EmployeeCompensation(
				tenant_id=data["tenant_id"],
				employee_id=employee.id,
				effective_date=start,
				pay_type=comp_data.get("pay_type", "SALARY").upper(),
				amount_cents=amount,
				currency_code=comp_data.get("currency_code", "USD").upper(),
				frequency=comp_data.get("frequency", "ANNUAL").upper(),
				grade_code=comp_data.get("grade_code"),
				reason="NEW_HIRE",
				approved_by=comp_data.get("approved_by"),
			))

		# Fill position if provided
		if employee.position_id:
			try:
				from pgappforge.plugins.erp.hcm.org.services import OrgService
				OrgService().fill_position(employee.position_id, employee.id, session)
			except Exception as exc:
				log.warning("PersonnelService.hire: could not fill position: %s", exc)

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
		log.info("PersonnelService.hire_employee: %s hired", employee.employee_number)
		return employee

	# ------------------------------------------------------------------
	# Termination
	# ------------------------------------------------------------------

	def terminate_employee(
		self,
		employee_id: str,
		data: dict[str, Any],
		session: Any,
	) -> Any:
		"""Terminate an employee's engagement.

		Sets employment_status=TERMINATED, records termination metadata,
		vacates their position, and emits EmployeeTerminatedEvent.

		Args:
			employee_id: UUID of the Employee.
			data: dict with keys: termination_date (ISO date), termination_type,
			      termination_reason (opt), rehire_eligible (opt bool).
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee
		from pgappforge.plugins.erp.hcm.personnel.events import EmployeeTerminatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {employee_id!r} not found")

		if employee.employment_status in ("TERMINATED", "RETIRED"):
			raise PersonnelServiceError(
				f"Employee {employee.employee_number!r} is already {employee.employment_status!r}"
			)

		term_date = data.get("termination_date")
		if isinstance(term_date, str):
			term_date = date.fromisoformat(term_date)
		elif term_date is None:
			term_date = datetime.now(timezone.utc).date()

		term_type = data.get("termination_type", "VOLUNTARY").upper()
		valid_types = {"VOLUNTARY", "INVOLUNTARY", "REDUNDANCY", "RETIREMENT"}
		if term_type not in valid_types:
			raise PersonnelServiceError(f"termination_type must be one of {valid_types}")

		old_position_id = employee.position_id

		employee.employment_status = "RETIRED" if term_type == "RETIREMENT" else "TERMINATED"
		employee.termination_date = term_date
		employee.termination_type = term_type
		employee.termination_reason = data.get("termination_reason")
		employee.rehire_eligible = bool(data.get("rehire_eligible", True))
		employee.updated_at = datetime.now(timezone.utc)

		# Vacate position
		if old_position_id:
			try:
				from pgappforge.plugins.erp.hcm.org.services import OrgService
				OrgService().vacate_position(old_position_id, employee_id, session)
			except Exception as exc:
				log.warning("PersonnelService.terminate: could not vacate position: %s", exc)

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
		log.info("PersonnelService.terminate_employee: %s terminated (%s)", employee.employee_number, term_type)
		return employee

	# ------------------------------------------------------------------
	# Transfer
	# ------------------------------------------------------------------

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

		eff = data.get("effective_date")
		if isinstance(eff, str):
			eff = date.fromisoformat(eff)
		elif eff is None:
			eff = datetime.now(timezone.utc).date()

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
			# Vacate old position
			if old_position_id:
				try:
					from pgappforge.plugins.erp.hcm.org.services import OrgService
					OrgService().vacate_position(old_position_id, employee_id, session)
				except Exception as exc:
					log.warning("PersonnelService.transfer: vacate old position failed: %s", exc)
			# Fill new position
			try:
				from pgappforge.plugins.erp.hcm.org.services import OrgService
				OrgService().fill_position(new_position_id, employee_id, session)
			except Exception as exc:
				log.warning("PersonnelService.transfer: fill new position failed: %s", exc)
			employee.position_id = new_position_id

		employee.updated_at = datetime.now(timezone.utc)

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
		return employee

	# ------------------------------------------------------------------
	# Compensation
	# ------------------------------------------------------------------

	def record_compensation(self, data: dict[str, Any], session: Any) -> Any:
		"""Insert a new EmployeeCompensation row (immutable ledger).

		amount_cents MUST be integer. Never updates existing rows.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, EmployeeCompensation
		from pgappforge.plugins.erp.hcm.personnel.events import CompensationChangedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		employee = session.get(Employee, data.get("employee_id", ""))
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {data.get('employee_id')!r} not found")

		amount = data.get("amount_cents")
		if amount is None:
			raise CompensationError("amount_cents is required")
		assert isinstance(amount, int), "amount_cents must be int"
		if amount <= 0:
			raise CompensationError("amount_cents must be positive")

		eff = data.get("effective_date")
		if isinstance(eff, str):
			eff = date.fromisoformat(eff)
		elif eff is None:
			eff = datetime.now(timezone.utc).date()

		comp = EmployeeCompensation(
			tenant_id=employee.tenant_id,
			employee_id=employee.id,
			effective_date=eff,
			pay_type=data.get("pay_type", "SALARY").upper(),
			amount_cents=amount,
			currency_code=data.get("currency_code", "USD").upper(),
			frequency=data.get("frequency", "ANNUAL").upper(),
			grade_code=data.get("grade_code"),
			reason=data.get("reason", "OTHER").upper(),
			approved_by=data.get("approved_by"),
		)
		session.add(comp)
		session.flush()

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
		log.info(
			"PersonnelService.record_compensation: emp=%s %d¢ %s eff=%s",
			employee.employee_number, amount, comp.pay_type, eff,
		)
		return comp

	def current_compensation(self, employee_id: str, session: Any) -> Any | None:
		"""Return the active EmployeeCompensation row for an employee.

		Active = highest effective_date <= today.
		Returns None if no compensation record exists.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeCompensation

		today = datetime.now(timezone.utc).date()
		return session.execute(
			sa.select(EmployeeCompensation)
			.where(EmployeeCompensation.employee_id == employee_id)
			.where(EmployeeCompensation.effective_date <= today)
			.order_by(sa.desc(EmployeeCompensation.effective_date))
			.limit(1)
		).scalar_one_or_none()

	# ------------------------------------------------------------------
	# Documents
	# ------------------------------------------------------------------

	def attach_document(self, data: dict[str, Any], session: Any) -> Any:
		"""Attach a document metadata record to an employee."""
		from pgappforge.plugins.erp.hcm.personnel.models import Employee, EmployeeDocument

		employee = session.get(Employee, data.get("employee_id", ""))
		if employee is None:
			raise EmployeeNotFoundError(f"Employee {data.get('employee_id')!r} not found")

		issued = data.get("issued_date")
		if isinstance(issued, str):
			issued = date.fromisoformat(issued)

		expiry = data.get("expiry_date")
		if isinstance(expiry, str):
			expiry = date.fromisoformat(expiry)

		doc = EmployeeDocument(
			tenant_id=employee.tenant_id,
			employee_id=employee.id,
			document_type=data["document_type"].upper(),
			filename=data["filename"],
			storage_url=data["storage_url"],
			issued_date=issued,
			expiry_date=expiry,
			is_verified=False,
		)
		session.add(doc)
		session.flush()
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
		doc.updated_at = datetime.now(timezone.utc)

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
		return doc

	def expiring_documents(
		self,
		tenant_id: str,
		session: Any,
		within_days: int = 30,
	) -> list[Any]:
		"""Return EmployeeDocument rows expiring within *within_days* days."""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeeDocument
		from datetime import timedelta

		today = datetime.now(timezone.utc).date()
		cutoff = today + timedelta(days=within_days)
		return session.execute(
			sa.select(EmployeeDocument)
			.where(EmployeeDocument.tenant_id == tenant_id)
			.where(EmployeeDocument.expiry_date.isnot(None))
			.where(EmployeeDocument.expiry_date <= cutoff)
			.where(EmployeeDocument.expiry_date >= today)
			.order_by(EmployeeDocument.expiry_date)
		).scalars().all()

	# ------------------------------------------------------------------
	# Analytics
	# ------------------------------------------------------------------

	def headcount_summary(self, entity_id: str, session: Any) -> dict[str, Any]:
		"""Return headcount by employment_type and employment_status for an entity."""
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


__all__ = [
	"PersonnelService",
	"PersonnelServiceError",
	"EmployeeNotFoundError",
	"CompensationError",
	"DocumentError",
]
