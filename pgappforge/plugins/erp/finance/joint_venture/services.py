"""Joint venture accounting service."""
from __future__ import annotations
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.finance.joint_venture.models import JointVenture, JVCashCall, JVBilling


def _uuid() -> str:
	return str(uuid.uuid4())


class JointVentureService:
	def create_jv(
		self,
		tenant_id: str,
		name: str,
		operator_entity_id: str,
		partners: list[dict[str, Any]],
		session: Any,
	) -> JointVenture:
		total_pct = sum(Decimal(str(p["ownership_pct"])) for p in partners)
		assert abs(total_pct - 100) < Decimal("0.01"), f"Ownership % must sum to 100, got {total_pct}"
		jv = JointVenture(
			id=_uuid(),
			tenant_id=tenant_id,
			name=name,
			operator_entity_id=operator_entity_id,
			partners=partners,
		)
		session.add(jv)
		return jv

	def issue_cash_call(
		self,
		jv_id: str,
		period: str,
		total_cents: int,
		due_date: Any,
		session: Any,
	) -> JVCashCall:
		jv = session.get(JointVenture, jv_id)
		distribution = []
		for p in jv.partners:
			pct = Decimal(str(p["ownership_pct"])) / 100
			amount = int((Decimal(total_cents) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
			distribution.append({"entity_id": p["entity_id"], "amount_cents": amount})
		call = JVCashCall(
			id=_uuid(),
			jv_id=jv_id,
			period=period,
			total_cents=total_cents,
			due_date=due_date,
			distribution=distribution,
		)
		session.add(call)
		return call

	def distribute_expense(
		self,
		jv_id: str,
		expense_journal_id: str,
		period: str,
		total_cents: int,
		session: Any,
	) -> JVBilling:
		jv = session.get(JointVenture, jv_id)
		distribution = []
		for p in jv.partners:
			pct = Decimal(str(p["ownership_pct"])) / 100
			amount = int((Decimal(total_cents) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
			distribution.append({
				"entity_id": p["entity_id"],
				"ownership_pct": p["ownership_pct"],
				"amount_cents": amount,
			})
		billing = JVBilling(
			id=_uuid(),
			jv_id=jv_id,
			expense_journal_id=expense_journal_id,
			period=period,
			distribution=distribution,
		)
		session.add(billing)
		return billing


__all__ = ["JointVentureService"]
