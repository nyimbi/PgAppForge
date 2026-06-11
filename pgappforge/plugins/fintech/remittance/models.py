"""
pgappforge/plugins/fintech/remittance/models.py

Remittance plugin models — cross-border money transfer corridors,
FX quotes, transactions, and AML/KYC compliance logging.

Design rules:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents — never Decimal/float in storage
  - Table name convention: ft_rem_<entity>
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# RemittanceCorridor — FX corridor configuration per tenant
# ---------------------------------------------------------------------------

class RemittanceCorridor(AuditMixin, Model):
	"""Defines a supported country-pair corridor with fees, FX, and payout rules.

	currency_pair: ISO format e.g. "KES/USD", "NGN/GBP"
	payout_methods: JSONB list of allowed methods —
	  BANK / MOBILE_MONEY / WALLET / CASH_PICKUP / CARD_PUSH
	fee_pct: applied as a fraction (0.0150 = 1.5%)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_rem_corridor"
	__table_args__ = (
		UniqueConstraint("tenant_id", "from_country", "to_country", name="uq_ft_rem_corridor_route"),
		Index("ix_ft_rem_corridor_tenant", "tenant_id"),
		Index("ix_ft_rem_corridor_countries", "from_country", "to_country"),
		Index("ix_ft_rem_corridor_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	from_country = Column(String(2), nullable=False, comment="ISO 3166-1 alpha-2 origin country")
	to_country = Column(String(2), nullable=False, comment="ISO 3166-1 alpha-2 destination country")
	currency_pair = Column(
		String(7),
		nullable=False,
		comment="FX pair e.g. KES/USD, NGN/GBP",
	)
	payout_methods: list[str] = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="BANK | MOBILE_MONEY | WALLET | CASH_PICKUP | CARD_PUSH",
	)
	min_amount_cents = Column(Integer, nullable=False, default=0)
	max_amount_cents = Column(Integer, nullable=False, default=0)
	flat_fee_cents = Column(Integer, nullable=False, default=0)
	fee_pct = Column(
		Numeric(5, 4),
		nullable=False,
		default=0,
		comment="Fee as decimal fraction e.g. 0.0150 = 1.5%",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	regulatory_notes = Column(Text, nullable=True)

	# Audit timestamps
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

	# Relationships
	quotes: list[RemittanceQuote] = relationship(
		"RemittanceQuote",
		back_populates="corridor",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RemittanceCorridor {self.from_country!r}→{self.to_country!r} "
			f"pair={self.currency_pair!r} active={self.is_active!r}>"
		)


# ---------------------------------------------------------------------------
# RemittanceQuote — time-limited FX + fee quote
# ---------------------------------------------------------------------------

class RemittanceQuote(Model):
	"""A time-limited FX quote for a specific send amount and corridor.

	Expires at expires_at (15 minutes from creation by default).
	receive_amount_cents = (send_amount_cents - fee_cents) * fx_rate
	total_debit_cents    = send_amount_cents + fee_cents
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_rem_quote"
	__table_args__ = (
		Index("ix_ft_rem_quote_tenant", "tenant_id"),
		Index("ix_ft_rem_quote_corridor", "corridor_id"),
		Index("ix_ft_rem_quote_expires", "expires_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	corridor_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_rem_corridor.id"),
		nullable=False,
		index=True,
	)
	send_amount_cents = Column(Integer, nullable=False)
	receive_amount_cents = Column(Integer, nullable=False)
	fx_rate = Column(Numeric(14, 6), nullable=False, comment="Exchange rate applied")
	fee_cents = Column(Integer, nullable=False, default=0)
	total_debit_cents = Column(
		Integer,
		nullable=False,
		comment="send_amount_cents + fee_cents",
	)
	payout_method = Column(String(20), nullable=False)
	expires_at = Column(DateTime(timezone=True), nullable=False)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	corridor: RemittanceCorridor = relationship(
		"RemittanceCorridor",
		back_populates="quotes",
		lazy="select",
	)
	transaction: RemittanceTransaction | None = relationship(
		"RemittanceTransaction",
		back_populates="quote",
		uselist=False,
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RemittanceQuote {self.id!r} "
			f"send={self.send_amount_cents}c "
			f"rate={self.fx_rate} "
			f"expires={self.expires_at!r}>"
		)


# ---------------------------------------------------------------------------
# RemittanceTransaction — the live transfer record
# ---------------------------------------------------------------------------

class RemittanceTransaction(AuditMixin, Model):
	"""A cross-border money transfer initiated from a quote.

	status flow:
	  PENDING → PROCESSING (after compliance pass)
	         → PAID        (after provider confirmation)
	         → CANCELLED   (customer/operator cancellation)
	         → REFUNDED    (reversal of PAID)
	         → FAILED      (provider-side failure)

	reference: operator-assigned unique token (required, UNIQUE).
	provider_reference: the external payout provider's reference.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_rem_transaction"
	__table_args__ = (
		Index("ix_ft_rem_txn_tenant", "tenant_id"),
		Index("ix_ft_rem_txn_quote", "quote_id"),
		Index("ix_ft_rem_txn_sender", "sender_customer_id"),
		Index("ix_ft_rem_txn_status", "status"),
		Index("ix_ft_rem_txn_reference", "reference"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	quote_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_rem_quote.id"),
		nullable=False,
		index=True,
	)
	sender_customer_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="UUID of the sending customer (FK to party table not enforced here)",
	)
	receiver_name = Column(String(200), nullable=False)
	receiver_phone = Column(String(30), nullable=False)
	receiver_account = Column(String(100), nullable=True)
	payout_method = Column(String(20), nullable=False)

	# Amounts (all cents — mirrored from quote at creation time)
	send_amount_cents = Column(Integer, nullable=False)
	receive_amount_cents = Column(Integer, nullable=False)
	fx_rate = Column(Numeric(14, 6), nullable=False)
	fee_cents = Column(Integer, nullable=False, default=0)

	# Status
	status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		comment="PENDING | PROCESSING | PAID | CANCELLED | REFUNDED | FAILED",
	)
	reference = Column(
		String(50),
		unique=True,
		nullable=False,
		comment="Operator-unique transfer reference",
	)
	provider_reference = Column(String(100), nullable=True)
	compliance_checked = Column(Boolean, nullable=False, default=False)

	# Audit timestamps
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

	# Relationships
	quote: RemittanceQuote = relationship(
		"RemittanceQuote",
		back_populates="transaction",
		lazy="select",
	)
	compliance_logs: list[RemittanceComplianceLog] = relationship(
		"RemittanceComplianceLog",
		back_populates="transaction",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RemittanceTransaction {self.reference!r} "
			f"status={self.status!r} "
			f"send={self.send_amount_cents}c>"
		)


# ---------------------------------------------------------------------------
# RemittanceComplianceLog — AML/KYC/OFAC check audit trail
# ---------------------------------------------------------------------------

class RemittanceComplianceLog(Model):
	"""Immutable audit record of each compliance check performed on a transfer.

	check_type: AML | KYC | OFAC | CBK_REPORT
	result:     PASS | FAIL | PENDING
	details:    JSONB — provider-specific result payload
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_rem_compliance"
	__table_args__ = (
		Index("ix_ft_rem_compliance_tenant", "tenant_id"),
		Index("ix_ft_rem_compliance_txn", "transaction_id"),
		Index("ix_ft_rem_compliance_type", "check_type"),
		Index("ix_ft_rem_compliance_result", "result"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	transaction_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_rem_transaction.id"),
		nullable=False,
		index=True,
	)
	check_type = Column(
		String(30),
		nullable=False,
		comment="AML | KYC | OFAC | CBK_REPORT",
	)
	result = Column(
		String(10),
		nullable=False,
		comment="PASS | FAIL | PENDING",
	)
	details: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
	)
	checked_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	transaction: RemittanceTransaction = relationship(
		"RemittanceTransaction",
		back_populates="compliance_logs",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RemittanceComplianceLog {self.id!r} "
			f"type={self.check_type!r} result={self.result!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"RemittanceCorridor",
	"RemittanceQuote",
	"RemittanceTransaction",
	"RemittanceComplianceLog",
]
