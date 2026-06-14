"""Territory management service."""
from __future__ import annotations
import uuid
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.crm.territory_management.models import SalesTerritory, TerritoryAssignment


def _uuid() -> str:
	return str(uuid.uuid4())


class TerritoryManagementService:
	def define_territory(self, tenant_id: str, name: str, rules: list[dict[str, Any]], region: str | None = None, session: Any = None) -> SalesTerritory:
		t = SalesTerritory(id=_uuid(), tenant_id=tenant_id, name=name, rules=rules, region=region)
		if session:
			session.add(t)
		return t

	def assign_territory(self, territory_id: str, salesperson_id: str, effective_from: Any, session: Any) -> TerritoryAssignment:
		a = TerritoryAssignment(id=_uuid(), territory_id=territory_id, salesperson_id=salesperson_id, effective_from=effective_from)
		session.add(a)
		return a

	def reassign_territory(self, territory_id: str, old_rep_id: str, new_rep_id: str, effective_from: Any, session: Any) -> TerritoryAssignment:
		session.execute(
			sa.update(TerritoryAssignment).where(
				TerritoryAssignment.territory_id == territory_id,
				TerritoryAssignment.salesperson_id == old_rep_id,
				TerritoryAssignment.is_active.is_(True),
			).values(is_active=False, effective_to=effective_from)
		)
		return self.assign_territory(territory_id, new_rep_id, effective_from, session)


__all__ = ["TerritoryManagementService"]
