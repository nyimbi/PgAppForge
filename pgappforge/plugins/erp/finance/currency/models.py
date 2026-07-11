"""
pgappforge/plugins/erp/finance/currency/models.py

Tenant-scoped currency and exchange-rate models for finance workflows.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Column, Date, DateTime, Index, Numeric, String

from pgappforge.models.sqla import Model


def uuid7str() -> str:
	from uuid6 import uuid7
	return str(uuid7())


class ExchangeRate(Model):
	"""Tenant-scoped point-in-time exchange rate.

	rate stores how many to_currency minor units one from_currency unit buys.
	For example, KES/USD 0.0077 means 1 KES = 0.0077 USD.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_exchange_rates"
	__table_args__ = (
		Index(
			"ix_erp_exchange_rates_tenant_pair_date",
			"tenant_id",
			"from_currency",
			"to_currency",
			"effective_date",
		),
		Index("ix_erp_exchange_rates_tenant_date", "tenant_id", "effective_date"),
		{"extend_existing": True},
	)

	id = Column(String(36), primary_key=True, default=uuid7str)
	tenant_id = Column(String(36), nullable=False, index=True)
	from_currency = Column(String(3), nullable=False, index=True)
	to_currency = Column(String(3), nullable=False, index=True)
	rate = Column(
		Numeric(24, 12),
		nullable=False,
		comment="How many to_currency per 1 from_currency",
	)
	effective_date = Column(Date, nullable=False, index=True)
	source = Column(String(50), nullable=False, default="manual")
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<ExchangeRate {self.tenant_id!r} "
			f"{self.from_currency}/{self.to_currency} "
			f"rate={self.rate!r} date={self.effective_date!r}>"
		)


__all__ = [
	"ExchangeRate",
	"uuid7str",
]
