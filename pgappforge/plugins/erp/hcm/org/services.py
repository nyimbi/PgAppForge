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


__all__ = [
	"OrgService",
	"OrgServiceError",
	"LegalEntityNotFoundError",
	"OrgUnitNotFoundError",
	"PositionNotFoundError",
	"PositionAlreadyFilledError",
]
