"""IFRS 16 / ASC 842 lease accounting service."""
from __future__ import annotations
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.finance.lease_accounting.models import (
	Lease, LeasePaymentSchedule, LeaseModification,
)


def _uuid() -> str:
	return str(uuid.uuid4())


def _npv(rate: Decimal, cashflows: list[int]) -> Decimal:
	"""Net present value of periodic cashflows discounted at the given annual rate.

	Each cashflow is assumed to occur at the end of successive periods at the
	same frequency as the rate (i.e. pass an annual rate for annual cashflows).
	"""
	total = Decimal("0")
	for i, cf in enumerate(cashflows, start=1):
		total += Decimal(str(cf)) / (1 + rate) ** i
	return total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class LeaseService:
	def create_lease(
		self,
		tenant_id: str,
		name: str,
		start_date: date,
		end_date: date,
		discount_rate: float,
		payment_schedule: list[dict[str, Any]],
		currency_code: str = "KES",
		standard: str = "IFRS16",
		session: Any = None,
	) -> Lease:
		payments = [p["payment_cents"] for p in payment_schedule]
		rate = Decimal(str(discount_rate))
		pv = _npv(rate, payments)
		lease = Lease(
			id=_uuid(),
			tenant_id=tenant_id,
			name=name,
			start_date=start_date,
			end_date=end_date,
			discount_rate=discount_rate,
			currency_code=currency_code,
			payment_schedule=payment_schedule,
			rou_asset_cents=int(pv),
			lease_liability_cents=int(pv),
			standard=standard,
		)
		if session:
			session.add(lease)
		return lease

	def get_schedule(self, lease_id: str, session: Any) -> list[LeasePaymentSchedule]:
		return list(
			session.execute(
				sa.select(LeasePaymentSchedule)
				.where(LeasePaymentSchedule.lease_id == lease_id)
				.order_by(LeasePaymentSchedule.period)
			).scalars().all()
		)

	def process_period(self, lease_id: str, period: str, session: Any) -> LeasePaymentSchedule | None:
		row = session.execute(
			sa.select(LeasePaymentSchedule).where(
				LeasePaymentSchedule.lease_id == lease_id,
				LeasePaymentSchedule.period == period,
				LeasePaymentSchedule.gl_posted.is_(False),
			)
		).scalar_one_or_none()
		if row is None:
			return None
		session.execute(
			sa.update(LeasePaymentSchedule)
			.where(LeasePaymentSchedule.id == row.id)
			.values(gl_posted=True)
		)
		return row

	def modify_lease(
		self,
		lease_id: str,
		effective_date: date,
		new_payments: list[dict[str, Any]],
		new_discount_rate: float | None,
		reason: str,
		session: Any,
	) -> LeaseModification:
		payments = [p["payment_cents"] for p in new_payments]
		rate = Decimal(str(new_discount_rate)) if new_discount_rate else None
		pv = _npv(rate, payments) if rate else None
		mod = LeaseModification(
			id=_uuid(),
			lease_id=lease_id,
			effective_date=effective_date,
			new_payments=new_payments,
			new_discount_rate=new_discount_rate,
			reason=reason,
			remeasured_liability_cents=int(pv) if pv else None,
		)
		session.add(mod)
		if pv:
			session.execute(
				sa.update(Lease).where(Lease.id == lease_id)
				.values(lease_liability_cents=int(pv), discount_rate=new_discount_rate)
			)
		return mod


__all__ = ["LeaseService"]
