"""Position management service."""
from __future__ import annotations
import uuid
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.hcm.position_management.models import Position, HeadcountRequest


def _uuid() -> str:
	return str(uuid.uuid4())


class PositionManagementService:
	def create_position(
		self,
		tenant_id: str,
		position_code: str,
		title: str,
		budget_salary_cents: int | None = None,
		department_id: str | None = None,
		session: Any = None,
	) -> Position:
		pos = Position(
			id=_uuid(),
			tenant_id=tenant_id,
			position_code=position_code,
			title=title,
			budget_salary_cents=budget_salary_cents,
			department_id=department_id,
		)
		if session:
			session.add(pos)
		return pos

	def fill_position(self, position_id: str, employee_id: str, actual_salary_cents: int, session: Any) -> None:
		session.execute(
			sa.update(Position).where(Position.id == position_id).values(
				status="FILLED",
				incumbent_employee_id=employee_id,
				actual_salary_cents=actual_salary_cents,
			)
		)

	def vacate_position(self, position_id: str, session: Any) -> None:
		session.execute(
			sa.update(Position).where(Position.id == position_id).values(
				status="VACANT",
				incumbent_employee_id=None,
				actual_salary_cents=None,
			)
		)

	def get_headcount_variance(self, tenant_id: str, session: Any) -> dict[str, Any]:
		positions = session.execute(
			sa.select(Position).where(Position.tenant_id == tenant_id)
		).scalars().all()
		total = len(positions)
		filled = sum(1 for p in positions if p.status == "FILLED")
		vacant = sum(1 for p in positions if p.status == "VACANT")
		frozen = sum(1 for p in positions if p.status == "FROZEN")
		budget_total = sum(p.budget_salary_cents or 0 for p in positions)
		actual_total = sum(p.actual_salary_cents or 0 for p in positions)
		return {
			"total_positions": total,
			"filled": filled,
			"vacant": vacant,
			"frozen": frozen,
			"budget_salary_cents": budget_total,
			"actual_salary_cents": actual_total,
			"variance_cents": actual_total - budget_total,
		}


__all__ = ["PositionManagementService"]
