"""Hedge accounting service — IFRS 9 effectiveness testing and recognition."""
from __future__ import annotations
import re
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.finance.hedge_accounting.models import HedgeRelationship, HedgeJournalEntry


def _uuid() -> str:
	return str(uuid.uuid4())


class HedgeAccountingService:
	def create_hedge_relationship(
		self,
		tenant_id: str,
		name: str,
		hedged_item_type: str,
		hedging_instrument_type: str,
		notional_cents: int,
		currency_code: str,
		start_date: Any,
		maturity_date: Any,
		session: Any,
	) -> HedgeRelationship:
		hedge = HedgeRelationship(
			id=_uuid(),
			tenant_id=tenant_id,
			name=name,
			hedged_item_type=hedged_item_type,
			hedging_instrument_type=hedging_instrument_type,
			notional_cents=notional_cents,
			currency_code=currency_code,
			start_date=start_date,
			maturity_date=maturity_date,
		)
		session.add(hedge)
		return hedge

	def test_effectiveness(
		self,
		hedge_id: str,
		period: str,
		instrument_change_cents: int,
		hedged_item_change_cents: int,
		session: Any,
	) -> HedgeJournalEntry:
		if not re.fullmatch(r"\d{4}-\d{2}", period or ""):
			raise ValueError("period must match YYYY-MM")
		hedge = session.get(HedgeRelationship, hedge_id)
		if hedged_item_change_cents == 0:
			ratio = None
			effective = 0
			ineffective = instrument_change_cents
		else:
			ratio = -(Decimal(str(instrument_change_cents)) / Decimal(str(hedged_item_change_cents))) * 100
			lower = Decimal(str(hedge.effectiveness_lower))
			upper = Decimal(str(hedge.effectiveness_upper))
			is_effective = lower <= ratio <= upper
			if is_effective:
				effective_abs = min(abs(instrument_change_cents), abs(hedged_item_change_cents))
				effective = effective_abs if instrument_change_cents >= 0 else -effective_abs
				ineffective = instrument_change_cents - effective
			else:
				effective = 0
				ineffective = instrument_change_cents

		entry = HedgeJournalEntry(
			id=_uuid(),
			hedge_id=hedge_id,
			period=period,
			hedging_instrument_change_cents=instrument_change_cents,
			hedged_item_change_cents=hedged_item_change_cents,
			effectiveness_ratio=ratio,
			effective_gain_cents=effective,
			ineffective_gain_cents=ineffective,
			oci_cents=effective if hedge.hedged_item_type == "CASH_FLOW" else 0,
			pl_cents=ineffective,
		)
		session.add(entry)
		return entry

	def get_hedge_summary(self, hedge_id: str, session: Any) -> dict[str, Any]:
		entries = session.execute(
			sa.select(HedgeJournalEntry)
			.where(HedgeJournalEntry.hedge_id == hedge_id)
			.order_by(HedgeJournalEntry.period)
		).scalars().all()
		return {
			"hedge_id": hedge_id,
			"entry_count": len(entries),
			"total_effective_cents": sum(e.effective_gain_cents for e in entries),
			"total_ineffective_cents": sum(e.ineffective_gain_cents for e in entries),
			"total_oci_cents": sum(e.oci_cents for e in entries),
		}


__all__ = ["HedgeAccountingService"]
