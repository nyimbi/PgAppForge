"""Loyalty engine service."""
from __future__ import annotations
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.crm.loyalty.models import LoyaltyProgram, LoyaltyAccount, LoyaltyTransaction


def _uuid() -> str:
	return str(uuid.uuid4())


class LoyaltyService:
	def enroll(self, customer_id: str, program_id: str, tenant_id: str, session: Any) -> LoyaltyAccount:
		acct = LoyaltyAccount(id=_uuid(), customer_id=customer_id, program_id=program_id, tenant_id=tenant_id)
		session.add(acct)
		return acct

	def earn_points(self, customer_id: str, program_id: str, order_amount_cents: int, tenant_id: str, session: Any) -> LoyaltyTransaction:
		prog = session.get(LoyaltyProgram, program_id)
		points = int(Decimal(str(order_amount_cents)) * Decimal(str(prog.points_per_cent)))
		acct = session.execute(sa.select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer_id, LoyaltyAccount.program_id == program_id)).scalar_one()
		session.execute(sa.update(LoyaltyAccount).where(LoyaltyAccount.id == acct.id).values(points_balance=LoyaltyAccount.points_balance + points, lifetime_points=LoyaltyAccount.lifetime_points + points))
		txn = LoyaltyTransaction(id=_uuid(), account_id=acct.id, transaction_type="EARN", points=points)
		session.add(txn)
		return txn

	def redeem_points(self, account_id: str, points_to_redeem: int, session: Any) -> int:
		acct = session.get(LoyaltyAccount, account_id)
		prog = session.get(LoyaltyProgram, acct.program_id)
		assert acct.points_balance >= points_to_redeem, "Insufficient points"
		discount_cents = int(Decimal(str(points_to_redeem)) * Decimal(str(prog.redemption_rate_pct)) / 100)
		session.execute(sa.update(LoyaltyAccount).where(LoyaltyAccount.id == account_id).values(points_balance=LoyaltyAccount.points_balance - points_to_redeem))
		txn = LoyaltyTransaction(id=_uuid(), account_id=account_id, transaction_type="REDEEM", points=-points_to_redeem)
		session.add(txn)
		return discount_cents

	def get_liability_report(self, tenant_id: str, session: Any) -> dict[str, Any]:
		accounts = session.execute(sa.select(LoyaltyAccount).where(LoyaltyAccount.tenant_id == tenant_id)).scalars().all()
		total_points = sum(a.points_balance for a in accounts)
		program_ids = list({a.program_id for a in accounts})
		total_liability_cents = 0
		for pid in program_ids:
			prog = session.get(LoyaltyProgram, pid)
			pts = sum(a.points_balance for a in accounts if a.program_id == pid)
			total_liability_cents += int(Decimal(str(pts)) * Decimal(str(prog.redemption_rate_pct)) / 100)
		return {"total_unredeemed_points": total_points, "estimated_liability_cents": total_liability_cents}


__all__ = ["LoyaltyService"]
