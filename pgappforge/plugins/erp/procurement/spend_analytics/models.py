"""
pgappforge/plugins/erp/procurement/spend_analytics/models.py

Spend Analytics models.

Tables:
  spd_snapshot — pre-computed spend cube snapshot per tenant/period/supplier
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Column,
	DateTime,
	Index,
	Integer,
	String,
)
from sqlalchemy.dialects.postgresql import UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# SpendSnapshot
# ---------------------------------------------------------------------------

class SpendSnapshot(AuditMixin, Model):
	"""Pre-computed spend cube row per (tenant, period, supplier).

	period: ISO YYYY-MM string, e.g. "2024-01".
	amount_cents: BigInteger — all monetary values stored as integer cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "spd_snapshot"
	__table_args__ = (
		Index("ix_spd_snapshot_period", "tenant_id", "period"),
		Index("ix_spd_snapshot_supplier", "tenant_id", "supplier_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	period = Column(String(20), nullable=False, comment="YYYY-MM")
	supplier_id = Column(String(50), nullable=False)
	supplier_name = Column(String(300), nullable=False)
	category = Column(String(100), nullable=True)
	department = Column(String(100), nullable=True)
	amount_cents = Column(BigInteger, nullable=False, default=0)
	invoice_count = Column(Integer, nullable=False, default=0)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<SpendSnapshot period={self.period!r} supplier={self.supplier_id!r}"
			f" amount_cents={self.amount_cents}>"
		)


__all__ = ["SpendSnapshot"]
