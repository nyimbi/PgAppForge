"""
pgappforge/plugins/erp/crm/territory_management/services.py

TerritoryService — define territories, assign salespeople, evaluate coverage.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now_date() -> date:
	return datetime.now(timezone.utc).date()


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("Territory event emit failed: %s", exc)


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("territory.define")
	def _bpm_define(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "territory.define", "params": ctx}

	@_BPMReg.register("territory.assign")
	def _bpm_assign(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "territory.assign", "params": ctx}

except (ImportError, Exception):
	log.debug("BPMActionRegistry not available — Territory BPM actions not registered")


# ---------------------------------------------------------------------------
# TerritoryService
# ---------------------------------------------------------------------------

class TerritoryService:
	"""Service layer for Sales Territory Management."""

	def define_territory(
		self,
		name: str,
		region: str,
		rules: list[dict[str, Any]],
		tenant_id: str,
		session: Any,
		*,
		country_codes: list[str] | None = None,
		entity_id: str | None = None,
	) -> Any:
		"""Create a new sales territory with optional rule-based account matching.

		rules format: [{field: str, op: str, values: list}]
		"""
		from pgappforge.plugins.erp.crm.territory_management.models import SalesTerritory
		from pgappforge.plugins.erp.crm.territory_management.events import TerritoryDefinedEvent

		territory = SalesTerritory(
			id=_uuid4(),
			tenant_id=tenant_id,
			name=name,
			region=region,
			country_codes=country_codes or [],
			rules=rules or [],
			entity_id=entity_id,
			is_active=True,
		)
		session.add(territory)
		session.flush()

		_emit(
			TerritoryDefinedEvent(
				aggregate_id=territory.id,
				aggregate_type="SalesTerritory",
				tenant_id=tenant_id,
				territory_id=territory.id,
				name=name,
				region=region,
			),
			session,
		)
		log.info("Territory: defined %r [%s]", name, region)
		return territory

	def assign_territory(
		self,
		territory_id: str,
		salesperson_id: str,
		effective_from: date,
		session: Any,
	) -> Any:
		"""Assign a salesperson to a territory, closing any prior open assignment.

		Emits TerritoryAssignedEvent.
		"""
		from pgappforge.plugins.erp.crm.territory_management.models import (
			SalesTerritory,
			TerritoryAssignment,
		)
		from pgappforge.plugins.erp.crm.territory_management.events import TerritoryAssignedEvent

		# Close previous open assignment for this salesperson on this territory
		prev = session.execute(
			sa.select(TerritoryAssignment).where(
				TerritoryAssignment.territory_id == territory_id,
				TerritoryAssignment.salesperson_id == salesperson_id,
				TerritoryAssignment.effective_to.is_(None),
			)
		).scalar_one_or_none()
		if prev is not None:
			prev.effective_to = effective_from

		territory = session.execute(
			sa.select(SalesTerritory).where(SalesTerritory.id == territory_id)
		).scalar_one_or_none()
		if territory is None:
			raise ValueError(f"Territory {territory_id} not found")

		assignment = TerritoryAssignment(
			id=_uuid4(),
			tenant_id=territory.tenant_id,
			territory_id=territory_id,
			salesperson_id=salesperson_id,
			effective_from=effective_from,
			effective_to=None,
		)
		session.add(assignment)
		session.flush()

		_emit(
			TerritoryAssignedEvent(
				aggregate_id=assignment.id,
				aggregate_type="TerritoryAssignment",
				tenant_id=territory.tenant_id,
				territory_id=territory_id,
				salesperson_id=salesperson_id,
				effective_from=str(effective_from),
			),
			session,
		)
		log.info("Territory: assigned %s to salesperson %s", territory_id, salesperson_id)
		return assignment

	def get_accounts_in_territory(
		self,
		territory_id: str,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Return all customer accounts that match the territory's rules.

		Uses the Rules Engine _evaluate_conditions pattern to apply JSONB rules
		to Customer records. Falls back gracefully if CRM customer model is absent.
		"""
		from pgappforge.plugins.erp.crm.territory_management.models import SalesTerritory

		territory = session.execute(
			sa.select(SalesTerritory).where(SalesTerritory.id == territory_id)
		).scalar_one_or_none()
		if territory is None:
			raise ValueError(f"Territory {territory_id} not found")

		# Attempt to load Customer model from CRM sales plugin
		try:
			from pgappforge.plugins.erp.crm.sales.models import Customer
		except ImportError:
			log.debug("Territory: CRM Customer model not available, returning empty list")
			return []

		customers = session.execute(
			sa.select(Customer).where(Customer.tenant_id == tenant_id)
		).scalars().all()

		rules: list[dict[str, Any]] = territory.rules or []
		if not rules:
			# No rules — territory covers all accounts in region/country
			matching = []
			country_codes: list[str] = territory.country_codes or []
			for c in customers:
				country = getattr(c, "country_code", None) or getattr(c, "country", None)
				if not country_codes or (country and country.upper() in [cc.upper() for cc in country_codes]):
					matching.append({"id": c.id, "name": getattr(c, "name", str(c.id))})
			return matching

		# Apply rules engine evaluation pattern
		def _match(customer: Any, rules: list[dict[str, Any]]) -> bool:
			for rule in rules:
				field = rule.get("field", "")
				op = rule.get("op", "eq")
				values = rule.get("values", [])
				val = getattr(customer, field, None)
				if val is None:
					return False
				val_str = str(val).upper()
				vals_upper = [str(v).upper() for v in values]
				if op == "eq":
					if val_str not in vals_upper:
						return False
				elif op == "in":
					if val_str not in vals_upper:
						return False
				elif op == "not_in":
					if val_str in vals_upper:
						return False
				elif op == "contains":
					if not any(v in val_str for v in vals_upper):
						return False
				# unknown op — skip rule
			return True

		return [
			{"id": c.id, "name": getattr(c, "name", str(c.id))}
			for c in customers
			if _match(c, rules)
		]

	def reassign_territory(
		self,
		old_salesperson_id: str,
		new_salesperson_id: str,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Bulk-reassign all open territory assignments from one salesperson to another.

		Closes the old assignments and creates new ones with today as effective_from.
		Returns the number of territories reassigned.
		"""
		from pgappforge.plugins.erp.crm.territory_management.models import TerritoryAssignment

		today = _now_date()
		open_assignments = session.execute(
			sa.select(TerritoryAssignment).where(
				TerritoryAssignment.salesperson_id == old_salesperson_id,
				TerritoryAssignment.tenant_id == tenant_id,
				TerritoryAssignment.effective_to.is_(None),
			)
		).scalars().all()

		count = 0
		for old_asgn in open_assignments:
			old_asgn.effective_to = today
			new_asgn = TerritoryAssignment(
				id=_uuid4(),
				tenant_id=tenant_id,
				territory_id=old_asgn.territory_id,
				salesperson_id=new_salesperson_id,
				effective_from=today,
				effective_to=None,
			)
			session.add(new_asgn)
			count += 1

		session.flush()
		log.info(
			"Territory: reassigned %d territories from %s to %s",
			count, old_salesperson_id, new_salesperson_id,
		)
		return count
