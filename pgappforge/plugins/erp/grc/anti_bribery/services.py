"""Anti-bribery / FCPA service."""
from __future__ import annotations
import uuid
from datetime import date
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.grc.anti_bribery.models import GiftEntertainmentLog, ConflictOfInterestDeclaration

GOVT_OFFICIAL_THRESHOLD_CENTS = 5_000  # KES 50 equivalent
HIGH_VALUE_THRESHOLD_CENTS = 50_000    # KES 500 equivalent


def _uuid() -> str:
	return str(uuid.uuid4())


class AntiBriberyService:
	def log_gift(
		self,
		tenant_id: str,
		employee_id: str,
		given_to_name: str,
		gift_type: str,
		value_cents: int,
		gift_date: date,
		is_government_official: bool = False,
		purpose: str | None = None,
		currency_code: str = "KES",
		session: Any = None,
	) -> GiftEntertainmentLog:
		status = "PENDING"
		flag_reason = None
		if is_government_official and value_cents > GOVT_OFFICIAL_THRESHOLD_CENTS:
			status = "FLAGGED"
			flag_reason = f"Government official + value {value_cents} exceeds threshold {GOVT_OFFICIAL_THRESHOLD_CENTS}"
		elif value_cents > HIGH_VALUE_THRESHOLD_CENTS:
			status = "FLAGGED"
			flag_reason = f"High-value gift: {value_cents} > {HIGH_VALUE_THRESHOLD_CENTS}"
		log = GiftEntertainmentLog(
			id=_uuid(),
			tenant_id=tenant_id,
			employee_id=employee_id,
			given_to_name=given_to_name,
			gift_type=gift_type,
			value_cents=value_cents,
			currency_code=currency_code,
			gift_date=gift_date,
			purpose=purpose,
			is_government_official=is_government_official,
			status=status,
			flag_reason=flag_reason,
		)
		if session:
			session.add(log)
		return log

	def submit_coi_declaration(
		self,
		tenant_id: str,
		employee_id: str,
		description: str,
		declaration_date: date,
		session: Any,
	) -> ConflictOfInterestDeclaration:
		decl = ConflictOfInterestDeclaration(
			id=_uuid(),
			tenant_id=tenant_id,
			employee_id=employee_id,
			description=description,
			declaration_date=declaration_date,
		)
		session.add(decl)
		return decl

	def get_risk_exposure(
		self,
		tenant_id: str,
		period_start: date,
		period_end: date,
		session: Any,
	) -> dict[str, Any]:
		gifts = session.execute(
			sa.select(GiftEntertainmentLog).where(
				GiftEntertainmentLog.tenant_id == tenant_id,
				GiftEntertainmentLog.gift_date >= period_start,
				GiftEntertainmentLog.gift_date <= period_end,
			)
		).scalars().all()
		flagged = [g for g in gifts if g.status == "FLAGGED"]
		govt_count = sum(1 for g in gifts if g.is_government_official)
		return {
			"total_gifts": len(gifts),
			"total_value_cents": sum(g.value_cents for g in gifts),
			"flagged_count": len(flagged),
			"govt_official_count": govt_count,
			"pending_approval": sum(1 for g in gifts if g.status == "PENDING"),
		}


__all__ = ["AntiBriberyService"]
