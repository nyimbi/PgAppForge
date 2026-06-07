"""
pgappforge/plugins/erp/hcm/personnel/timeline.py

WorkerTimelineService — Workday-style unified worker timeline.

Aggregates effective-dated changes across all HCM modules into one chronological view.
Supports both complete timeline and point-in-time state reconstruction (get_as_of).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


class WorkerTimelineService:
	"""Unified worker timeline — aggregates effective-dated events across HCM modules.

	All queries use SQLAlchemy 2.x session.execute(select()) patterns.
	Cross-plugin imports are guarded; missing modules degrade gracefully.
	"""

	def get_timeline(
		self,
		employee_id: str,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Return all changes to an employee record in chronological order.

		Each event dict:
		  effective_date  — ISO-8601 date string
		  event_type      — POSITION_CHANGE | COMPENSATION_CHANGE | BENEFIT_ENROLLMENT | COMPENSATION_PACKAGE
		  changed_by      — string (empty if unknown)
		  entity          — logical domain name
		  description     — human-readable summary
		  old_value       — dict (may be None)
		  new_value       — dict

		Sources: EmployeePositionHistory, EmployeeCompensation, BenefitEnrollment, CompensationPackage
		"""
		events: list[dict[str, Any]] = []

		# 1. Position changes
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import EmployeePositionHistory
			pos_rows = session.execute(
				sa.select(EmployeePositionHistory)
				.where(
					EmployeePositionHistory.employee_id == employee_id,
					EmployeePositionHistory.tenant_id == tenant_id,
				)
				.order_by(EmployeePositionHistory.effective_from)
			).scalars().all()
			for r in pos_rows:
				events.append({
					"effective_date": str(r.effective_from),
					"event_type": "POSITION_CHANGE",
					"changed_by": r.changed_by or "",
					"entity": "position",
					"description": f"Position → {r.position_title or r.position_code}",
					"old_value": None,
					"new_value": {
						"position_code": r.position_code,
						"department_id": r.department_id,
						"manager_id": r.manager_id,
						"org_unit_id": r.org_unit_id,
					},
				})
		except Exception as exc:
			log.debug("WorkerTimelineService: position history unavailable: %s", exc)

		# 2. Salary changes
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import EmployeeCompensation
			comp_rows = session.execute(
				sa.select(EmployeeCompensation)
				.where(
					EmployeeCompensation.employee_id == employee_id,
					EmployeeCompensation.tenant_id == tenant_id,
				)
				.order_by(EmployeeCompensation.effective_date)
			).scalars().all()
			for i, r in enumerate(comp_rows):
				old_v = comp_rows[i - 1].amount_cents if i > 0 else None
				events.append({
					"effective_date": str(r.effective_date),
					"event_type": "COMPENSATION_CHANGE",
					"changed_by": "",
					"entity": "compensation",
					"description": f"Salary → {r.amount_cents} cents {r.currency_code}",
					"old_value": {"amount_cents": old_v},
					"new_value": {
						"amount_cents": r.amount_cents,
						"currency_code": r.currency_code,
					},
				})
		except Exception as exc:
			log.debug("WorkerTimelineService: compensation history unavailable: %s", exc)

		# 3. Benefit enrollments
		try:
			from pgappforge.plugins.erp.hcm.benefits.models import BenefitEnrollment
			ben_rows = session.execute(
				sa.select(BenefitEnrollment)
				.where(
					BenefitEnrollment.employee_id == employee_id,
					BenefitEnrollment.tenant_id == tenant_id,
				)
				.order_by(BenefitEnrollment.effective_from)
			).scalars().all()
			for r in ben_rows:
				events.append({
					"effective_date": str(r.effective_from),
					"event_type": "BENEFIT_ENROLLMENT",
					"changed_by": getattr(r, "enrolled_by", None) or "",
					"entity": "benefits",
					"description": f"Enrolled in plan {r.plan_id}",
					"old_value": None,
					"new_value": {
						"plan_id": r.plan_id,
						"status": r.status,
						"coverage_tier": getattr(r, "coverage_tier", None),
					},
				})
		except Exception as exc:
			log.debug("WorkerTimelineService: benefits history unavailable: %s", exc)

		# 4. Compensation packages
		try:
			from pgappforge.plugins.erp.hcm.compensation.models import CompensationPackage
			pkg_rows = session.execute(
				sa.select(CompensationPackage)
				.where(
					CompensationPackage.employee_id == employee_id,
					CompensationPackage.tenant_id == tenant_id,
				)
				.order_by(CompensationPackage.effective_from)
			).scalars().all()
			for r in pkg_rows:
				events.append({
					"effective_date": str(r.effective_from),
					"event_type": "COMPENSATION_PACKAGE",
					"changed_by": getattr(r, "approved_by", None) or "",
					"entity": "compensation_package",
					"description": f"{r.package_type} — {r.base_salary_cents} cents {r.currency_code}",
					"old_value": None,
					"new_value": {
						"base_salary_cents": r.base_salary_cents,
						"package_type": r.package_type,
					},
				})
		except Exception as exc:
			log.debug("WorkerTimelineService: comp packages unavailable: %s", exc)

		# Sort all events chronologically
		events.sort(key=lambda e: e["effective_date"])
		return events

	def get_as_of(
		self,
		employee_id: str,
		as_of_date: date,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return complete employee state as of a given date — Workday point-in-time query.

		Returns a dict with keys: employee_id, as_of, and optionally position, compensation.
		Each sub-dict contains only the fields available from the underlying model.
		"""
		state: dict[str, Any] = {
			"employee_id": employee_id,
			"as_of": str(as_of_date),
		}

		# Current position as of date
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import EmployeePositionHistory
			pos = session.execute(
				sa.select(EmployeePositionHistory)
				.where(
					EmployeePositionHistory.employee_id == employee_id,
					EmployeePositionHistory.tenant_id == tenant_id,
					EmployeePositionHistory.effective_from <= as_of_date,
					sa.or_(
						EmployeePositionHistory.effective_to.is_(None),
						EmployeePositionHistory.effective_to >= as_of_date,
					),
				)
				.order_by(EmployeePositionHistory.effective_from.desc())
				.limit(1)
			).scalar_one_or_none()
			if pos:
				state["position"] = {
					"code": pos.position_code,
					"title": pos.position_title,
					"department_id": pos.department_id,
					"manager_id": pos.manager_id,
					"org_unit_id": pos.org_unit_id,
				}
		except Exception as exc:
			log.debug("WorkerTimelineService.get_as_of: position unavailable: %s", exc)

		# Salary as of date
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import EmployeeCompensation
			comp = session.execute(
				sa.select(EmployeeCompensation)
				.where(
					EmployeeCompensation.employee_id == employee_id,
					EmployeeCompensation.tenant_id == tenant_id,
					EmployeeCompensation.effective_date <= as_of_date,
				)
				.order_by(EmployeeCompensation.effective_date.desc())
				.limit(1)
			).scalar_one_or_none()
			if comp:
				state["compensation"] = {
					"amount_cents": comp.amount_cents,
					"currency_code": comp.currency_code,
					"pay_type": comp.pay_type,
					"frequency": comp.frequency,
				}
		except Exception as exc:
			log.debug("WorkerTimelineService.get_as_of: compensation unavailable: %s", exc)

		return state

	def record_position_change(
		self,
		employee_id: str,
		new_position_code: str | None,
		new_position_title: str | None,
		department_id: str | None,
		manager_id: str | None,
		org_unit_id: str | None,
		effective_from: date,
		tenant_id: str,
		session: Any,
		*,
		changed_by: str | None = None,
		change_reason: str | None = None,
	) -> Any:
		"""Insert a new EmployeePositionHistory row and close the previous one.

		Closing semantics: set effective_to = effective_from - 1 day on the
		currently-open row (effective_to IS NULL), provided its effective_from
		predates the new row's effective_from.  Same-day replacements (rare
		corrections) leave effective_to equal to effective_from on the old row.

		Returns the newly inserted EmployeePositionHistory instance after flush.
		"""
		from pgappforge.plugins.erp.hcm.personnel.models import EmployeePositionHistory

		# Close previous open row
		prev = session.execute(
			sa.select(EmployeePositionHistory)
			.where(
				EmployeePositionHistory.employee_id == employee_id,
				EmployeePositionHistory.tenant_id == tenant_id,
				EmployeePositionHistory.effective_to.is_(None),
			)
			.order_by(EmployeePositionHistory.effective_from.desc())
			.limit(1)
		).scalar_one_or_none()

		if prev and prev.effective_from < effective_from:
			prev.effective_to = effective_from - timedelta(days=1)

		row = EmployeePositionHistory(
			tenant_id=tenant_id,
			employee_id=employee_id,
			position_code=new_position_code,
			position_title=new_position_title,
			department_id=department_id,
			manager_id=manager_id,
			org_unit_id=org_unit_id,
			effective_from=effective_from,
			changed_by=changed_by,
			change_reason=change_reason,
		)
		session.add(row)
		session.flush()
		return row


__all__ = ["WorkerTimelineService"]
