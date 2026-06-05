"""
pgappforge/plugins/erp/hcm/org/services.py

OrgService — stateless business logic for the HCM Org Management plugin.

All methods accept an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Key public methods:
  create_legal_entity(data, session)              -> LegalEntity
  create_org_unit(data, session)                  -> OrgUnit
  restructure_org_unit(unit_id, new_parent_id, session) -> OrgUnit
  create_position(data, session)                  -> Position
  fill_position(position_id, employee_id, session) -> Position
  vacate_position(position_id, employee_id, session) -> Position
  publish_compensation_grade(data, session)       -> CompensationGrade
  active_grade(grade_code, session)               -> CompensationGrade | None
  org_tree(entity_id, session)                    -> list[dict]
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

class OrgServiceError(Exception):
	"""Base domain error for Org operations."""


class LegalEntityNotFoundError(OrgServiceError):
	pass


class OrgUnitNotFoundError(OrgServiceError):
	pass


class PositionNotFoundError(OrgServiceError):
	pass


class PositionAlreadyFilledError(OrgServiceError):
	pass


# ---------------------------------------------------------------------------
# OrgService
# ---------------------------------------------------------------------------

class OrgService:
	"""Stateless Org Management domain service."""

	# ------------------------------------------------------------------
	# LegalEntity
	# ------------------------------------------------------------------

	def create_legal_entity(self, data: dict[str, Any], session: Any) -> Any:
		"""Create a LegalEntity.

		Args:
			data: dict with keys: tenant_id, entity_code, entity_name,
			      country_code, payroll_currency, fiscal_year_start_month,
			      tax_id (opt), address (opt).
			session: SQLAlchemy session.

		Returns:
			New LegalEntity (not committed).
		"""
		from pgappforge.plugins.erp.hcm.org.models import LegalEntity
		from pgappforge.plugins.erp.hcm.org.events import LegalEntityCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "entity_code", "entity_name", "country_code")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise OrgServiceError(f"Missing required fields: {missing}")

		entity = LegalEntity(
			tenant_id=data["tenant_id"],
			entity_code=data["entity_code"].upper(),
			entity_name=data["entity_name"],
			country_code=data["country_code"].upper(),
			payroll_currency=data.get("payroll_currency", "USD").upper(),
			fiscal_year_start_month=int(data.get("fiscal_year_start_month", 1)),
			tax_id=data.get("tax_id"),
			address=data.get("address") or {},
			is_active=True,
		)
		session.add(entity)
		session.flush()

		emit_event(
			LegalEntityCreatedEvent(
				aggregate_id=entity.id,
				aggregate_type="LegalEntity",
				tenant_id=entity.tenant_id,
				entity_id=entity.id,
				entity_code=entity.entity_code,
				entity_name=entity.entity_name,
				country_code=entity.country_code,
				payroll_currency=entity.payroll_currency,
			),
			session,
		)
		log.info("OrgService.create_legal_entity: %s created", entity.entity_code)
		return entity

	def deactivate_legal_entity(self, entity_id: str, session: Any) -> Any:
		"""Deactivate a LegalEntity (soft delete — is_active=False)."""
		from pgappforge.plugins.erp.hcm.org.models import LegalEntity
		from pgappforge.plugins.erp.hcm.org.events import LegalEntityDeactivatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		entity = session.get(LegalEntity, entity_id)
		if entity is None:
			raise LegalEntityNotFoundError(f"LegalEntity {entity_id!r} not found")
		entity.is_active = False
		entity.updated_at = datetime.now(timezone.utc)
		emit_event(
			LegalEntityDeactivatedEvent(
				aggregate_id=entity_id,
				aggregate_type="LegalEntity",
				tenant_id=entity.tenant_id,
				entity_id=entity_id,
				entity_code=entity.entity_code,
			),
			session,
		)
		return entity

	# ------------------------------------------------------------------
	# OrgUnit
	# ------------------------------------------------------------------

	def create_org_unit(self, data: dict[str, Any], session: Any) -> Any:
		"""Create an OrgUnit node.

		Args:
			data: dict with keys: tenant_id, entity_id, org_code, org_name,
			      org_type, parent_id (opt), cost_center_code (opt),
			      headcount_budget (opt).
		"""
		from pgappforge.plugins.erp.hcm.org.models import OrgUnit, LegalEntity
		from pgappforge.plugins.erp.hcm.org.events import OrgUnitCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "entity_id", "org_code", "org_name", "org_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise OrgServiceError(f"Missing required fields: {missing}")

		org_type = data["org_type"].upper()
		valid_types = {"DIVISION", "DEPARTMENT", "TEAM", "UNIT"}
		if org_type not in valid_types:
			raise OrgServiceError(f"org_type must be one of {valid_types}")

		unit = OrgUnit(
			tenant_id=data["tenant_id"],
			entity_id=data["entity_id"],
			org_code=data["org_code"].upper(),
			org_name=data["org_name"],
			org_type=org_type,
			parent_id=data.get("parent_id"),
			cost_center_code=data.get("cost_center_code"),
			headcount_budget=data.get("headcount_budget"),
			is_active=True,
		)
		session.add(unit)
		session.flush()

		emit_event(
			OrgUnitCreatedEvent(
				aggregate_id=unit.id,
				aggregate_type="OrgUnit",
				tenant_id=unit.tenant_id,
				org_unit_id=unit.id,
				org_code=unit.org_code,
				org_type=unit.org_type,
				entity_id=unit.entity_id,
				parent_id=unit.parent_id or "",
			),
			session,
		)
		log.info("OrgService.create_org_unit: %s (%s) created", unit.org_code, unit.org_type)
		return unit

	def restructure_org_unit(
		self,
		unit_id: str,
		new_parent_id: str | None,
		session: Any,
		new_manager_id: str | None = None,
	) -> Any:
		"""Move an OrgUnit to a new parent and/or assign a new manager."""
		from pgappforge.plugins.erp.hcm.org.models import OrgUnit
		from pgappforge.plugins.erp.hcm.org.events import OrgUnitRestructuredEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		unit = session.get(OrgUnit, unit_id)
		if unit is None:
			raise OrgUnitNotFoundError(f"OrgUnit {unit_id!r} not found")

		old_parent = unit.parent_id or ""
		old_manager = unit.manager_id or ""

		unit.parent_id = new_parent_id
		if new_manager_id is not None:
			unit.manager_id = new_manager_id
		unit.updated_at = datetime.now(timezone.utc)

		emit_event(
			OrgUnitRestructuredEvent(
				aggregate_id=unit_id,
				aggregate_type="OrgUnit",
				tenant_id=unit.tenant_id,
				org_unit_id=unit_id,
				old_parent_id=old_parent,
				new_parent_id=new_parent_id or "",
				old_manager_id=old_manager,
				new_manager_id=new_manager_id or "",
			),
			session,
		)
		return unit

	# ------------------------------------------------------------------
	# Position
	# ------------------------------------------------------------------

	def create_position(self, data: dict[str, Any], session: Any) -> Any:
		"""Create a budgeted Position.

		Args:
			data: dict with keys: tenant_id, position_code, entity_id,
			      org_unit_id, position_title, employment_type,
			      job_code (opt), graded_salary_min_cents (opt),
			      graded_salary_max_cents (opt).
		"""
		from pgappforge.plugins.erp.hcm.org.models import Position
		from pgappforge.plugins.erp.hcm.org.events import PositionCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "position_code", "entity_id", "org_unit_id", "position_title")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise OrgServiceError(f"Missing required fields: {missing}")

		sal_min = data.get("graded_salary_min_cents")
		sal_max = data.get("graded_salary_max_cents")
		if sal_min is not None:
			assert isinstance(sal_min, int), "graded_salary_min_cents must be int"
		if sal_max is not None:
			assert isinstance(sal_max, int), "graded_salary_max_cents must be int"
		if sal_min is not None and sal_max is not None and sal_min > sal_max:
			raise OrgServiceError("graded_salary_min_cents must be <= graded_salary_max_cents")

		position = Position(
			tenant_id=data["tenant_id"],
			position_code=data["position_code"].upper(),
			entity_id=data["entity_id"],
			org_unit_id=data["org_unit_id"],
			job_code=data.get("job_code"),
			position_title=data["position_title"],
			employment_type=data.get("employment_type", "FULL_TIME").upper(),
			is_filled=False,
			graded_salary_min_cents=sal_min,
			graded_salary_max_cents=sal_max,
			is_active=True,
		)
		session.add(position)
		session.flush()

		emit_event(
			PositionCreatedEvent(
				aggregate_id=position.id,
				aggregate_type="Position",
				tenant_id=position.tenant_id,
				position_id=position.id,
				position_code=position.position_code,
				org_unit_id=position.org_unit_id,
				entity_id=position.entity_id,
				employment_type=position.employment_type,
			),
			session,
		)
		log.info("OrgService.create_position: %s created", position.position_code)
		return position

	def fill_position(self, position_id: str, employee_id: str, session: Any) -> Any:
		"""Mark a position as filled by the given employee."""
		from pgappforge.plugins.erp.hcm.org.models import Position
		from pgappforge.plugins.erp.hcm.org.events import PositionFilledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		position = session.get(Position, position_id)
		if position is None:
			raise PositionNotFoundError(f"Position {position_id!r} not found")
		if position.is_filled:
			raise PositionAlreadyFilledError(f"Position {position.position_code!r} is already filled")

		position.is_filled = True
		position.updated_at = datetime.now(timezone.utc)

		emit_event(
			PositionFilledEvent(
				aggregate_id=position_id,
				aggregate_type="Position",
				tenant_id=position.tenant_id,
				position_id=position_id,
				position_code=position.position_code,
				employee_id=employee_id,
			),
			session,
		)
		return position

	def vacate_position(self, position_id: str, employee_id: str, session: Any) -> Any:
		"""Mark a position as vacant when an employee leaves."""
		from pgappforge.plugins.erp.hcm.org.models import Position
		from pgappforge.plugins.erp.hcm.org.events import PositionVacatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		position = session.get(Position, position_id)
		if position is None:
			raise PositionNotFoundError(f"Position {position_id!r} not found")

		position.is_filled = False
		position.updated_at = datetime.now(timezone.utc)

		emit_event(
			PositionVacatedEvent(
				aggregate_id=position_id,
				aggregate_type="Position",
				tenant_id=position.tenant_id,
				position_id=position_id,
				position_code=position.position_code,
				vacated_by_employee_id=employee_id,
			),
			session,
		)
		return position

	# ------------------------------------------------------------------
	# CompensationGrade
	# ------------------------------------------------------------------

	def publish_compensation_grade(self, data: dict[str, Any], session: Any) -> Any:
		"""Insert a new CompensationGrade band (effective-dated; immutable ledger).

		All amount fields must be integer cents.

		Args:
			data: dict with keys: tenant_id, grade_code, grade_label,
			      min_cents, mid_cents, max_cents, currency_code,
			      effective_from (ISO date str or date).
		"""
		from pgappforge.plugins.erp.hcm.org.models import CompensationGrade
		from pgappforge.plugins.erp.hcm.org.events import CompensationGradePublishedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		for field in ("min_cents", "mid_cents", "max_cents"):
			v = data.get(field)
			if v is None:
				raise OrgServiceError(f"Missing required field: {field}")
			assert isinstance(v, int), f"{field} must be int (cents)"

		min_c, mid_c, max_c = int(data["min_cents"]), int(data["mid_cents"]), int(data["max_cents"])
		if not (min_c <= mid_c <= max_c):
			raise OrgServiceError("Comp grade requires min_cents <= mid_cents <= max_cents")

		eff = data.get("effective_from")
		if isinstance(eff, str):
			eff = date.fromisoformat(eff)
		elif eff is None:
			eff = datetime.now(timezone.utc).date()

		grade = CompensationGrade(
			tenant_id=data["tenant_id"],
			grade_code=data["grade_code"].upper(),
			grade_label=data["grade_label"],
			min_cents=min_c,
			mid_cents=mid_c,
			max_cents=max_c,
			currency_code=data.get("currency_code", "USD").upper(),
			effective_from=eff,
		)
		session.add(grade)
		session.flush()

		emit_event(
			CompensationGradePublishedEvent(
				aggregate_id=grade.id,
				aggregate_type="CompensationGrade",
				tenant_id=grade.tenant_id,
				grade_id=grade.id,
				grade_code=grade.grade_code,
				min_cents=min_c,
				mid_cents=mid_c,
				max_cents=max_c,
				currency_code=grade.currency_code,
				effective_from=eff.isoformat(),
			),
			session,
		)
		log.info(
			"OrgService.publish_compensation_grade: %s eff=%s min=%d¢ max=%d¢",
			grade.grade_code, eff, min_c, max_c,
		)
		return grade

	def active_grade(self, grade_code: str, session: Any, as_of: date | None = None) -> Any | None:
		"""Return the active CompensationGrade for grade_code as of a given date.

		Returns the row with the highest effective_from <= as_of.
		Returns None if no matching grade exists.
		"""
		from pgappforge.plugins.erp.hcm.org.models import CompensationGrade

		ref_date = as_of or datetime.now(timezone.utc).date()
		return session.execute(
			sa.select(CompensationGrade)
			.where(CompensationGrade.grade_code == grade_code.upper())
			.where(CompensationGrade.effective_from <= ref_date)
			.order_by(sa.desc(CompensationGrade.effective_from))
			.limit(1)
		).scalar_one_or_none()

	# ------------------------------------------------------------------
	# Org tree query
	# ------------------------------------------------------------------

	def org_tree(self, entity_id: str, session: Any) -> list[dict]:
		"""Return a flat list of OrgUnit dicts for the given entity.

		Callers can reconstruct the tree using parent_id.
		"""
		from pgappforge.plugins.erp.hcm.org.models import OrgUnit

		units = session.execute(
			sa.select(OrgUnit)
			.where(OrgUnit.entity_id == entity_id)
			.where(OrgUnit.is_active.is_(True))
			.order_by(OrgUnit.org_code)
		).scalars().all()

		return [
			{
				"id": u.id,
				"org_code": u.org_code,
				"org_name": u.org_name,
				"org_type": u.org_type,
				"parent_id": u.parent_id,
				"manager_id": u.manager_id,
				"cost_center_code": u.cost_center_code,
				"headcount_budget": u.headcount_budget,
			}
			for u in units
		]


	# ------------------------------------------------------------------
	# Position vacancy report
	# ------------------------------------------------------------------

	def get_vacancy_report(
		self,
		session: Any,
		org_unit_id: str | None = None,
		tenant_id: str = "",
	) -> list[dict]:
		"""Return open (unfilled, active) positions with vacancy age in days.

		Args:
			session: SQLAlchemy session.
			org_unit_id: Optional filter — only positions in this org unit.
			tenant_id: Tenant scope filter; empty string skips tenant filter.

		Returns:
			List of dicts with keys:
			  position_id, position_code, position_title, org_unit_id,
			  grade_code, last_vacated_at, days_open.
		"""
		from pgappforge.plugins.erp.hcm.org.models import Position

		try:
			stmt = (
				sa.select(Position)
				.where(Position.is_filled.is_(False))
				.where(Position.is_active.is_(True))
			)
			if tenant_id:
				stmt = stmt.where(Position.tenant_id == tenant_id)
			if org_unit_id:
				stmt = stmt.where(Position.org_unit_id == org_unit_id)
			stmt = stmt.order_by(Position.last_vacated_at.asc().nullsfirst())

			positions = session.execute(stmt).scalars().all()
			now = datetime.now(timezone.utc)
			result = []
			for p in positions:
				if p.last_vacated_at is not None:
					delta = now - p.last_vacated_at
					days_open = delta.days
				else:
					# Position was never filled — age from creation
					created = p.created_at if p.created_at else now
					days_open = (now - created).days
				result.append({
					"position_id": p.id,
					"position_code": p.position_code,
					"position_title": p.position_title,
					"org_unit_id": p.org_unit_id,
					"grade_code": p.grade_code,
					"last_vacated_at": p.last_vacated_at.isoformat() if p.last_vacated_at else None,
					"days_open": days_open,
				})
			return result
		except Exception:
			log.exception("OrgService.get_vacancy_report failed")
			raise

	# ------------------------------------------------------------------
	# JobGrade
	# ------------------------------------------------------------------

	def create_grade(self, data: dict[str, Any], session: Any) -> Any:
		"""Create or replace a JobGrade master-data entry.

		Args:
			data: dict with keys: tenant_id, grade_code, grade_name,
			      min_salary_cents, mid_salary_cents, max_salary_cents,
			      currency_code (opt, default 'KES').

		Returns:
			New JobGrade (not committed).

		Raises:
			OrgServiceError: If salary ordering is violated or required fields missing.
		"""
		from pgappforge.plugins.erp.hcm.org.models import JobGrade

		try:
			required = ("tenant_id", "grade_code", "grade_name", "min_salary_cents", "mid_salary_cents", "max_salary_cents")
			missing = [f for f in required if data.get(f) is None]
			if missing:
				raise OrgServiceError(f"Missing required fields: {missing}")

			mn = int(data["min_salary_cents"])
			md = int(data["mid_salary_cents"])
			mx = int(data["max_salary_cents"])
			assert isinstance(mn, int) and isinstance(md, int) and isinstance(mx, int), "salary fields must be int cents"
			if not (mn <= md <= mx):
				raise OrgServiceError("JobGrade requires min_salary_cents <= mid_salary_cents <= max_salary_cents")

			grade = JobGrade(
				tenant_id=data["tenant_id"],
				grade_code=data["grade_code"].upper(),
				grade_name=data["grade_name"],
				min_salary_cents=mn,
				mid_salary_cents=md,
				max_salary_cents=mx,
				currency_code=data.get("currency_code", "KES").upper(),
			)
			session.add(grade)
			session.flush()
			log.info("OrgService.create_grade: %s created", grade.grade_code)
			return grade
		except OrgServiceError:
			raise
		except Exception:
			log.exception("OrgService.create_grade failed")
			raise

	def check_salary_in_band(
		self,
		session: Any,
		grade_code: str,
		salary_cents: int,
		tenant_id: str,
	) -> bool:
		"""Check whether salary_cents falls within the JobGrade band.

		Args:
			session: SQLAlchemy session.
			grade_code: JobGrade.grade_code (case-insensitive).
			salary_cents: Proposed annual salary in integer cents.
			tenant_id: Tenant scope.

		Returns:
			True if min_salary_cents <= salary_cents <= max_salary_cents.

		Raises:
			OrgServiceError: If the grade does not exist.
		"""
		from pgappforge.plugins.erp.hcm.org.models import JobGrade

		try:
			assert isinstance(salary_cents, int), "salary_cents must be int"
			grade = session.execute(
				sa.select(JobGrade)
				.where(JobGrade.tenant_id == tenant_id)
				.where(JobGrade.grade_code == grade_code.upper())
				.limit(1)
			).scalar_one_or_none()
			if grade is None:
				raise OrgServiceError(f"JobGrade {grade_code!r} not found for tenant {tenant_id!r}")
			return grade.min_salary_cents <= salary_cents <= grade.max_salary_cents
		except OrgServiceError:
			raise
		except Exception:
			log.exception("OrgService.check_salary_in_band failed")
			raise

	# ------------------------------------------------------------------
	# ReportingLine
	# ------------------------------------------------------------------

	def set_reporting_line(
		self,
		from_position_id: str,
		to_position_id: str,
		session: Any,
		line_type: str = "SOLID",
		effective_from: date | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Establish a reporting line between two positions.

		For SOLID lines: closes any existing open SOLID line from from_position_id
		before inserting the new one (enforces single-solid invariant in Python;
		the DB partial-unique index is the hard guard).

		Args:
			from_position_id: The reporting position (subordinate).
			to_position_id: The manager position.
			session: SQLAlchemy session.
			line_type: 'SOLID' or 'DOTTED'.
			effective_from: Effective date; defaults to today.
			tenant_id: Tenant scope; inferred from position if empty.

		Returns:
			New ReportingLine (not committed).
		"""
		from pgappforge.plugins.erp.hcm.org.models import Position, ReportingLine
		from pgappforge.plugins.erp.hcm.org.events import ReportingLineSetEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		try:
			line_type = line_type.upper()
			if line_type not in ("SOLID", "DOTTED"):
				raise OrgServiceError("line_type must be SOLID or DOTTED")

			from_pos = session.get(Position, from_position_id)
			if from_pos is None:
				raise PositionNotFoundError(f"Position {from_position_id!r} not found")
			to_pos = session.get(Position, to_position_id)
			if to_pos is None:
				raise PositionNotFoundError(f"Position {to_position_id!r} not found")

			eff = effective_from or datetime.now(timezone.utc).date()
			resolved_tenant = tenant_id or from_pos.tenant_id

			# Close existing open SOLID line for this position to maintain invariant
			if line_type == "SOLID":
				existing = session.execute(
					sa.select(ReportingLine)
					.where(ReportingLine.from_position_id == from_position_id)
					.where(ReportingLine.line_type == "SOLID")
					.where(ReportingLine.effective_to.is_(None))
				).scalars().all()
				for old in existing:
					old.effective_to = eff
					old.updated_at = datetime.now(timezone.utc)

			rl = ReportingLine(
				tenant_id=resolved_tenant,
				from_position_id=from_position_id,
				to_position_id=to_position_id,
				line_type=line_type,
				effective_from=eff,
				effective_to=None,
			)
			session.add(rl)
			session.flush()

			emit_event(
				ReportingLineSetEvent(
					aggregate_id=rl.id,
					aggregate_type="ReportingLine",
					tenant_id=resolved_tenant,
					reporting_line_id=rl.id,
					from_position_id=from_position_id,
					to_position_id=to_position_id,
					line_type=line_type,
					effective_from=eff.isoformat(),
				),
				session,
			)
			log.info(
				"OrgService.set_reporting_line: %s -(%s)-> %s eff=%s",
				from_position_id, line_type, to_position_id, eff,
			)
			return rl
		except (OrgServiceError, PositionNotFoundError):
			raise
		except Exception:
			log.exception("OrgService.set_reporting_line failed")
			raise

	def end_reporting_line(
		self,
		reporting_line_id: str,
		session: Any,
		effective_to: date | None = None,
	) -> Any:
		"""Close an active reporting line by setting its effective_to date.

		Args:
			reporting_line_id: PK of the ReportingLine to close.
			session: SQLAlchemy session.
			effective_to: End date; defaults to today.

		Returns:
			Updated ReportingLine (not committed).
		"""
		from pgappforge.plugins.erp.hcm.org.models import ReportingLine
		from pgappforge.plugins.erp.hcm.org.events import ReportingLineEndedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		try:
			rl = session.get(ReportingLine, reporting_line_id)
			if rl is None:
				raise OrgServiceError(f"ReportingLine {reporting_line_id!r} not found")
			if rl.effective_to is not None:
				raise OrgServiceError(f"ReportingLine {reporting_line_id!r} is already closed (effective_to={rl.effective_to})")

			end = effective_to or datetime.now(timezone.utc).date()
			rl.effective_to = end
			rl.updated_at = datetime.now(timezone.utc)

			emit_event(
				ReportingLineEndedEvent(
					aggregate_id=reporting_line_id,
					aggregate_type="ReportingLine",
					tenant_id=rl.tenant_id,
					reporting_line_id=reporting_line_id,
					from_position_id=rl.from_position_id,
					to_position_id=rl.to_position_id,
					effective_to=end.isoformat(),
				),
				session,
			)
			log.info("OrgService.end_reporting_line: %s closed eff_to=%s", reporting_line_id, end)
			return rl
		except OrgServiceError:
			raise
		except Exception:
			log.exception("OrgService.end_reporting_line failed")
			raise

	def get_org_chart(
		self,
		session: Any,
		root_employee_id: str,
		depth: int = 3,
		tenant_id: str = "",
	) -> dict:
		"""Build a nested org-chart tree rooted at root_employee_id.

		Traverses active SOLID reporting lines up to `depth` levels.
		Each node: {id, name, title, reports: [...]}

		The method is position-centric: root_employee_id is treated as a
		position_id.  Personnel names are not joined here (no dependency on
		the Personnel plugin); callers can enrich with employee names.

		Args:
			session: SQLAlchemy session.
			root_employee_id: Position ID of the root node.
			depth: Maximum levels to recurse (default 3).
			tenant_id: Tenant scope filter.

		Returns:
			Nested dict tree.
		"""
		from pgappforge.plugins.erp.hcm.org.models import Position, ReportingLine

		try:
			def _build_node(position_id: str, current_depth: int) -> dict:
				pos = session.get(Position, position_id)
				node: dict = {
					"id": position_id,
					"position_code": pos.position_code if pos else position_id,
					"title": pos.position_title if pos else "",
					"reports": [],
				}
				if current_depth <= 0:
					return node

				stmt = (
					sa.select(ReportingLine)
					.where(ReportingLine.to_position_id == position_id)
					.where(ReportingLine.line_type == "SOLID")
					.where(ReportingLine.effective_to.is_(None))
				)
				if tenant_id:
					stmt = stmt.where(ReportingLine.tenant_id == tenant_id)

				direct_reports = session.execute(stmt).scalars().all()
				for rl in direct_reports:
					child = _build_node(rl.from_position_id, current_depth - 1)
					node["reports"].append(child)

				return node

			return _build_node(root_employee_id, depth)
		except Exception:
			log.exception("OrgService.get_org_chart failed")
			raise

	# ------------------------------------------------------------------
	# Org change requests  (OrgRestructureRequest)
	# ------------------------------------------------------------------

	def raise_change_request(self, data: dict[str, Any], session: Any) -> Any:
		"""Raise an OrgRestructureRequest for review.

		Args:
			data: dict with keys: tenant_id, org_unit_id, restructure_type,
			      requested_by, effective_date (ISO str or date),
			      description (opt), change_payload_json (opt).

		Valid restructure_type values: MERGE, SPLIT, RENAME, REPARENT, ABOLISH.

		Returns:
			New OrgRestructureRequest in DRAFT status (not committed).
		"""
		from pgappforge.plugins.erp.hcm.org.models import OrgUnit, OrgRestructureRequest
		from pgappforge.plugins.erp.hcm.org.events import OrgRestructureRequestRaisedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		try:
			required = ("tenant_id", "org_unit_id", "restructure_type", "requested_by", "effective_date")
			missing = [f for f in required if not data.get(f)]
			if missing:
				raise OrgServiceError(f"Missing required fields: {missing}")

			valid_types = {"MERGE", "SPLIT", "RENAME", "REPARENT", "ABOLISH"}
			rtype = data["restructure_type"].upper()
			if rtype not in valid_types:
				raise OrgServiceError(f"restructure_type must be one of {valid_types}")

			unit = session.get(OrgUnit, data["org_unit_id"])
			if unit is None:
				raise OrgUnitNotFoundError(f"OrgUnit {data['org_unit_id']!r} not found")

			eff = data["effective_date"]
			if isinstance(eff, str):
				eff = date.fromisoformat(eff)

			req = OrgRestructureRequest(
				tenant_id=data["tenant_id"],
				org_unit_id=data["org_unit_id"],
				restructure_type=rtype,
				requested_by=data["requested_by"],
				effective_date=eff,
				description=data.get("description"),
				change_payload_json=data.get("change_payload_json") or {},
				status="DRAFT",
			)
			session.add(req)
			session.flush()

			emit_event(
				OrgRestructureRequestRaisedEvent(
					aggregate_id=req.id,
					aggregate_type="OrgRestructureRequest",
					tenant_id=req.tenant_id,
					request_id=req.id,
					org_unit_id=req.org_unit_id,
					restructure_type=rtype,
					requested_by=req.requested_by,
					effective_date=eff.isoformat(),
				),
				session,
			)
			log.info(
				"OrgService.raise_change_request: %s for unit %s eff=%s",
				rtype, req.org_unit_id, eff,
			)
			return req
		except (OrgServiceError, OrgUnitNotFoundError):
			raise
		except Exception:
			log.exception("OrgService.raise_change_request failed")
			raise

	def approve_change(
		self,
		request_id: str,
		approved_by: str,
		session: Any,
	) -> Any:
		"""Approve a DRAFT OrgRestructureRequest.

		Args:
			request_id: PK of the OrgRestructureRequest.
			approved_by: Identifier of the approver.
			session: SQLAlchemy session.

		Returns:
			Updated OrgRestructureRequest in APPROVED status.
		"""
		from pgappforge.plugins.erp.hcm.org.models import OrgRestructureRequest
		from pgappforge.plugins.erp.hcm.org.events import OrgRestructureRequestApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		try:
			req = session.get(OrgRestructureRequest, request_id)
			if req is None:
				raise OrgServiceError(f"OrgRestructureRequest {request_id!r} not found")
			if req.status != "DRAFT":
				raise OrgServiceError(
					f"Cannot approve request in status {req.status!r}; expected DRAFT"
				)

			req.status = "APPROVED"
			req.approved_by = approved_by
			req.approved_at = datetime.now(timezone.utc)
			req.updated_at = datetime.now(timezone.utc)

			emit_event(
				OrgRestructureRequestApprovedEvent(
					aggregate_id=request_id,
					aggregate_type="OrgRestructureRequest",
					tenant_id=req.tenant_id,
					request_id=request_id,
					org_unit_id=req.org_unit_id,
					approved_by=approved_by,
				),
				session,
			)
			log.info("OrgService.approve_change: request %s approved by %s", request_id, approved_by)
			return req
		except OrgServiceError:
			raise
		except Exception:
			log.exception("OrgService.approve_change failed")
			raise

	def apply_pending_changes(
		self,
		session: Any,
		as_of_date: date | None = None,
		tenant_id: str = "",
	) -> dict:
		"""Apply all APPROVED OrgRestructureRequests whose effective_date <= as_of_date.

		This method executes the structural mutations described in
		change_payload_json and writes OrgUnitHistory audit rows.

		Supported restructure_type mutations applied here:
		  RENAME    — sets org_name from change_payload_json['after']['org_name']
		  REPARENT  — sets parent_id from change_payload_json['after']['parent_id']
		  ABOLISH   — sets OrgUnit.status = 'ABOLISHED' and is_active = False

		MERGE and SPLIT are complex multi-unit operations; this method
		marks them APPLIED but delegates the structural work to the payload
		— callers must supply pre-populated change_payload_json.

		Args:
			session: SQLAlchemy session.
			as_of_date: Cut-off date (inclusive); defaults to today.
			tenant_id: Tenant scope; empty = all tenants.

		Returns:
			dict with keys: applied (list of request_ids), skipped (list of request_ids), errors (list of str).
		"""
		from pgappforge.plugins.erp.hcm.org.models import OrgUnit, OrgUnitHistory, OrgRestructureRequest
		from pgappforge.plugins.erp.hcm.org.events import OrgRestructureRequestAppliedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		try:
			cut_off = as_of_date or datetime.now(timezone.utc).date()

			stmt = (
				sa.select(OrgRestructureRequest)
				.where(OrgRestructureRequest.status == "APPROVED")
				.where(OrgRestructureRequest.effective_date <= cut_off)
			)
			if tenant_id:
				stmt = stmt.where(OrgRestructureRequest.tenant_id == tenant_id)
			stmt = stmt.order_by(OrgRestructureRequest.effective_date.asc())

			pending = session.execute(stmt).scalars().all()
			applied: list[str] = []
			skipped: list[str] = []
			errors: list[str] = []

			for req in pending:
				try:
					unit = session.get(OrgUnit, req.org_unit_id)
					if unit is None:
						errors.append(f"request {req.id}: OrgUnit {req.org_unit_id!r} not found")
						skipped.append(req.id)
						continue

					before_snap: dict = {
						"org_name": unit.org_name,
						"parent_id": unit.parent_id,
						"status": unit.status,
					}

					rtype = req.restructure_type
					payload_after = (req.change_payload_json or {}).get("after", {})

					if rtype == "RENAME":
						new_name = payload_after.get("org_name")
						if not new_name:
							errors.append(f"request {req.id}: RENAME missing after.org_name in change_payload_json")
							skipped.append(req.id)
							continue
						unit.org_name = new_name

					elif rtype == "REPARENT":
						unit.parent_id = payload_after.get("parent_id")

					elif rtype == "ABOLISH":
						unit.status = "ABOLISHED"
						unit.is_active = False

					# MERGE / SPLIT: structural work is in payload; just mark applied
					unit.updated_at = datetime.now(timezone.utc)

					history = OrgUnitHistory(
						tenant_id=req.tenant_id,
						org_unit_id=req.org_unit_id,
						change_type=rtype,
						effective_date=req.effective_date,
						old_value_json=before_snap,
						new_value_json=payload_after,
						changed_by=req.approved_by or "system",
					)
					session.add(history)

					req.status = "APPLIED"
					req.updated_at = datetime.now(timezone.utc)

					emit_event(
						OrgRestructureRequestAppliedEvent(
							aggregate_id=req.id,
							aggregate_type="OrgRestructureRequest",
							tenant_id=req.tenant_id,
							request_id=req.id,
							org_unit_id=req.org_unit_id,
							restructure_type=rtype,
						),
						session,
					)
					applied.append(req.id)
					log.info("OrgService.apply_pending_changes: applied request %s (%s)", req.id, rtype)
				except Exception as exc:
					errors.append(f"request {req.id}: {exc}")
					skipped.append(req.id)
					log.exception("OrgService.apply_pending_changes: error on request %s", req.id)

			session.flush()
			return {"applied": applied, "skipped": skipped, "errors": errors}
		except Exception:
			log.exception("OrgService.apply_pending_changes failed")
			raise

	# ------------------------------------------------------------------
	# Workforce analytics
	# ------------------------------------------------------------------

	def get_headcount_report(
		self,
		session: Any,
		as_of_date: date | None = None,
		group_by: str = "department",
		tenant_id: str = "",
	) -> dict:
		"""Return headcount grouped by org unit or department.

		Counts filled and vacant active positions as of as_of_date.
		(as_of_date is recorded for labelling only; live data is always
		point-in-time current unless HeadcountSnapshot is used.)

		Args:
			session: SQLAlchemy session.
			as_of_date: Reference date for the report label.
			group_by: 'department' groups by OrgUnit; any other value
			          returns an aggregate across all units.
			tenant_id: Tenant scope filter.

		Returns:
			dict with keys: as_of (ISO date), group_by, rows (list of dicts),
			totals {total_filled, total_vacant, total_positions}.
		"""
		from pgappforge.plugins.erp.hcm.org.models import Position, OrgUnit

		try:
			ref = as_of_date or datetime.now(timezone.utc).date()

			stmt = (
				sa.select(
					Position.org_unit_id,
					sa.func.count().label("total"),
					sa.func.sum(sa.cast(Position.is_filled, sa.Integer)).label("filled"),
				)
				.where(Position.is_active.is_(True))
				.group_by(Position.org_unit_id)
			)
			if tenant_id:
				stmt = stmt.where(Position.tenant_id == tenant_id)

			rows_raw = session.execute(stmt).all()

			# Enrich with org unit name
			unit_ids = [r.org_unit_id for r in rows_raw]
			units_by_id: dict[str, Any] = {}
			if unit_ids:
				units = session.execute(
					sa.select(OrgUnit).where(OrgUnit.id.in_(unit_ids))
				).scalars().all()
				units_by_id = {u.id: u for u in units}

			rows = []
			total_filled = 0
			total_vacant = 0
			for r in rows_raw:
				filled = int(r.filled or 0)
				total = int(r.total or 0)
				vacant = total - filled
				total_filled += filled
				total_vacant += vacant
				unit = units_by_id.get(r.org_unit_id)
				rows.append({
					"org_unit_id": r.org_unit_id,
					"org_unit_name": unit.org_name if unit else None,
					"org_type": unit.org_type if unit else None,
					"filled": filled,
					"vacant": vacant,
					"total": total,
				})

			return {
				"as_of": ref.isoformat(),
				"group_by": group_by,
				"rows": rows,
				"totals": {
					"total_filled": total_filled,
					"total_vacant": total_vacant,
					"total_positions": total_filled + total_vacant,
				},
			}
		except Exception:
			log.exception("OrgService.get_headcount_report failed")
			raise

	def get_attrition_rate(
		self,
		session: Any,
		from_date: date,
		to_date: date,
		tenant_id: str = "",
	) -> dict:
		"""Compute attrition rate from vacancy events in the period.

		Attrition = positions vacated in period / average filled positions.
		Uses last_vacated_at on Position as the vacancy event timestamp.

		Args:
			session: SQLAlchemy session.
			from_date: Period start (inclusive).
			to_date: Period end (inclusive).
			tenant_id: Tenant scope filter.

		Returns:
			dict with keys: from_date, to_date, vacated_count,
			avg_filled, attrition_rate_pct.
		"""
		from pgappforge.plugins.erp.hcm.org.models import Position

		try:
			assert from_date <= to_date, "from_date must be <= to_date"

			from_dt = datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc)
			to_dt = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc)

			base = sa.select(Position).where(Position.is_active.is_(True))
			if tenant_id:
				base = base.where(Position.tenant_id == tenant_id)

			# Positions vacated during the period
			vacated_stmt = base.where(
				Position.last_vacated_at >= from_dt,
			).where(
				Position.last_vacated_at <= to_dt,
			)
			vacated_count = session.execute(
				sa.select(sa.func.count()).select_from(vacated_stmt.subquery())
			).scalar_one()

			# Average filled: (filled at start + filled at end) / 2 approximation
			# We use current is_filled count as end-of-period proxy
			total_stmt = base.where(Position.is_filled.is_(True))
			filled_now = session.execute(
				sa.select(sa.func.count()).select_from(total_stmt.subquery())
			).scalar_one()

			avg_filled = max(filled_now, 1)  # avoid division by zero
			attrition_pct = round((vacated_count / avg_filled) * 100, 2)

			return {
				"from_date": from_date.isoformat(),
				"to_date": to_date.isoformat(),
				"vacated_count": vacated_count,
				"avg_filled": filled_now,
				"attrition_rate_pct": attrition_pct,
			}
		except Exception:
			log.exception("OrgService.get_attrition_rate failed")
			raise

	def get_span_of_control(
		self,
		session: Any,
		org_unit_id: str,
		tenant_id: str = "",
	) -> dict:
		"""Compute span-of-control metrics for all manager positions in an org unit.

		Span = number of positions with an active SOLID reporting line pointing
		to a given manager position.  Flags outliers at < 2 (under-delegation)
		or > 12 (overload).

		Args:
			session: SQLAlchemy session.
			org_unit_id: Scope to positions in this org unit.
			tenant_id: Tenant scope filter.

		Returns:
			dict with keys: org_unit_id, managers (list of dicts), summary.
			Each manager dict: {position_id, position_code, position_title,
			direct_reports, flag (OK|UNDER_DELEGATION|OVERLOADED)}.
		"""
		from pgappforge.plugins.erp.hcm.org.models import Position, ReportingLine

		UNDER_THRESHOLD = 2
		OVER_THRESHOLD = 12

		try:
			# Get all positions in the org unit
			pos_stmt = (
				sa.select(Position)
				.where(Position.org_unit_id == org_unit_id)
				.where(Position.is_active.is_(True))
			)
			if tenant_id:
				pos_stmt = pos_stmt.where(Position.tenant_id == tenant_id)
			positions = session.execute(pos_stmt).scalars().all()
			pos_ids = [p.id for p in positions]
			pos_map = {p.id: p for p in positions}

			if not pos_ids:
				return {
					"org_unit_id": org_unit_id,
					"managers": [],
					"summary": {"min_span": 0, "max_span": 0, "avg_span": 0.0, "manager_count": 0},
				}

			# Count direct reports per manager (to_position_id) within the unit
			span_stmt = (
				sa.select(
					ReportingLine.to_position_id,
					sa.func.count().label("direct_reports"),
				)
				.where(ReportingLine.to_position_id.in_(pos_ids))
				.where(ReportingLine.line_type == "SOLID")
				.where(ReportingLine.effective_to.is_(None))
				.group_by(ReportingLine.to_position_id)
			)
			span_rows = session.execute(span_stmt).all()

			managers = []
			spans: list[int] = []
			for row in span_rows:
				pos = pos_map.get(row.to_position_id)
				span = int(row.direct_reports)
				spans.append(span)
				if span < UNDER_THRESHOLD:
					flag = "UNDER_DELEGATION"
				elif span > OVER_THRESHOLD:
					flag = "OVERLOADED"
				else:
					flag = "OK"
				managers.append({
					"position_id": row.to_position_id,
					"position_code": pos.position_code if pos else None,
					"position_title": pos.position_title if pos else None,
					"direct_reports": span,
					"flag": flag,
				})

			managers.sort(key=lambda m: m["direct_reports"], reverse=True)
			avg_span = round(sum(spans) / len(spans), 2) if spans else 0.0

			return {
				"org_unit_id": org_unit_id,
				"managers": managers,
				"summary": {
					"min_span": min(spans) if spans else 0,
					"max_span": max(spans) if spans else 0,
					"avg_span": avg_span,
					"manager_count": len(managers),
				},
			}
		except Exception:
			log.exception("OrgService.get_span_of_control failed")
			raise

	def get_open_position_aging(
		self,
		session: Any,
		tenant_id: str = "",
	) -> list[dict]:
		"""Return all open (unfilled) active positions with age buckets.

		Age buckets: 0-30 days, 31-60, 61-90, 90+ days.

		Args:
			session: SQLAlchemy session.
			tenant_id: Tenant scope filter.

		Returns:
			list of dicts with keys: position_id, position_code, position_title,
			org_unit_id, grade_code, days_open, age_bucket.
		"""
		from pgappforge.plugins.erp.hcm.org.models import Position

		try:
			stmt = (
				sa.select(Position)
				.where(Position.is_filled.is_(False))
				.where(Position.is_active.is_(True))
			)
			if tenant_id:
				stmt = stmt.where(Position.tenant_id == tenant_id)

			positions = session.execute(stmt).scalars().all()
			now = datetime.now(timezone.utc)
			result = []
			for p in positions:
				ref_dt = p.last_vacated_at or p.created_at or now
				days_open = max(0, (now - ref_dt).days)
				if days_open <= 30:
					bucket = "0-30"
				elif days_open <= 60:
					bucket = "31-60"
				elif days_open <= 90:
					bucket = "61-90"
				else:
					bucket = "90+"
				result.append({
					"position_id": p.id,
					"position_code": p.position_code,
					"position_title": p.position_title,
					"org_unit_id": p.org_unit_id,
					"grade_code": p.grade_code,
					"days_open": days_open,
					"age_bucket": bucket,
				})

			result.sort(key=lambda x: x["days_open"], reverse=True)
			return result
		except Exception:
			log.exception("OrgService.get_open_position_aging failed")
			raise


__all__ = [
	"OrgService",
	"OrgServiceError",
	"LegalEntityNotFoundError",
	"OrgUnitNotFoundError",
	"PositionNotFoundError",
	"PositionAlreadyFilledError",
]
