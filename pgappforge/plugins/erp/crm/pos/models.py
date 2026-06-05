"""
pgappforge/plugins/erp/crm/pos/models.py

Point of Sale models.

Design rules:
  - Table prefix: pos_
  - All PKs: UUID v4 via gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True))
  - All monetary amounts: BigInteger cents — never float
  - All models: tenant_id UUID NOT NULL + AuditMixin
  - lazy='select' throughout (SA 2.x)
  - JSONB for extensible metadata

Status lifecycles:
  POSTill:        OPEN → CLOSED | SUSPENDED
  POSTransaction: COMPLETED → VOIDED | REFUNDED
  POSPayment:     COMPLETED → REVERSED | FAILED
  POSShiftRecon:  OPEN → RECONCILED | DISCREPANCY
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
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


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# POSTill
# ---------------------------------------------------------------------------

class POSTill(AuditMixin, Model):
	"""Physical or virtual POS terminal.

	One till per shift; a new till row (or status reset) represents opening a
	new shift.  All transactions for a shift reference this row.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pos_till"
	__table_args__ = (
		UniqueConstraint("tenant_id", "till_code", name="uq_pos_till_code"),
		Index("ix_pos_till_tenant", "tenant_id"),
		Index("ix_pos_till_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	till_code = Column(String(20), nullable=False, comment="e.g. TILL-001")
	name = Column(String(200), nullable=False)
	location = Column(String(100), nullable=False)
	status = Column(
		String(15),
		nullable=False,
		default="CLOSED",
		comment="OPEN | CLOSED | SUSPENDED",
	)
	cashier_id = Column(UUID(as_uuid=False), nullable=True, comment="Currently assigned cashier")
	opened_at = Column(DateTime(timezone=True), nullable=True)
	opening_float_cents = Column(BigInteger, nullable=False, default=0)
	total_sales_cents = Column(BigInteger, nullable=False, default=0)
	total_returns_cents = Column(BigInteger, nullable=False, default=0)
	expected_closing_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="opening_float + total_sales - total_returns",
	)

	transactions: list[POSTransaction] = relationship(
		"POSTransaction",
		back_populates="till",
		lazy="select",
		order_by="POSTransaction.transaction_at",
	)

	def __repr__(self) -> str:
		return f"<POSTill {self.till_code!r} status={self.status!r} cashier={self.cashier_id!r}>"


# ---------------------------------------------------------------------------
# POSTransaction
# ---------------------------------------------------------------------------

class POSTransaction(AuditMixin, Model):
	"""A single POS transaction: SALE, RETURN, VOID, or EXCHANGE.

	IMMUTABLE once COMPLETED — voids create a linked VOID record; returns
	create a linked RETURN transaction.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pos_transaction"
	__table_args__ = (
		UniqueConstraint("receipt_number", "tenant_id", name="uq_pos_txn_receipt"),
		Index("ix_pos_txn_till", "till_id"),
		Index("ix_pos_txn_cashier", "cashier_id"),
		Index("ix_pos_txn_at", "transaction_at"),
		Index("ix_pos_txn_status", "status"),
		Index("ix_pos_txn_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	till_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pos_till.id", ondelete="RESTRICT"),
		nullable=False,
	)
	transaction_type = Column(
		String(15),
		nullable=False,
		comment="SALE | RETURN | VOID | EXCHANGE",
	)
	receipt_number = Column(String(30), nullable=False)
	transaction_at = Column(DateTime(timezone=True), nullable=False)
	cashier_id = Column(UUID(as_uuid=False), nullable=False)
	subtotal_cents = Column(BigInteger, nullable=False)
	discount_cents = Column(BigInteger, nullable=False, default=0)
	tax_cents = Column(BigInteger, nullable=False)
	total_cents = Column(BigInteger, nullable=False)
	status = Column(
		String(15),
		nullable=False,
		default="COMPLETED",
		comment="COMPLETED | VOIDED | REFUNDED",
	)
	void_reason = Column(Text, nullable=True)
	customer_id = Column(UUID(as_uuid=False), nullable=True)

	till: POSTill = relationship("POSTill", back_populates="transactions", lazy="select")
	lines: list[POSTransactionLine] = relationship(
		"POSTransactionLine",
		back_populates="transaction",
		lazy="select",
		cascade="all, delete-orphan",
	)
	payments: list[POSPayment] = relationship(
		"POSPayment",
		back_populates="transaction",
		lazy="select",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return (
			f"<POSTransaction {self.receipt_number!r} type={self.transaction_type!r} "
			f"total={self.total_cents} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# POSTransactionLine
# ---------------------------------------------------------------------------

class POSTransactionLine(AuditMixin, Model):
	"""Line item within a POS transaction."""

	__allow_unmapped__ = True
	__tablename__ = "pos_transaction_line"
	__table_args__ = (
		Index("ix_pos_txn_line_txn", "txn_id"),
		Index("ix_pos_txn_line_product", "product_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	txn_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pos_transaction.id", ondelete="CASCADE"),
		nullable=False,
	)
	product_code = Column(String(30), nullable=False)
	description = Column(String(200), nullable=False)
	quantity = Column(Numeric(8, 3), nullable=False)
	unit_price_cents = Column(BigInteger, nullable=False)
	discount_cents = Column(BigInteger, nullable=False, default=0)
	tax_rate_pct = Column(Numeric(5, 2), nullable=False, default=0)
	tax_cents = Column(BigInteger, nullable=False, default=0)
	line_total_cents = Column(BigInteger, nullable=False)

	transaction: POSTransaction = relationship(
		"POSTransaction",
		back_populates="lines",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<POSTransactionLine {self.product_code!r} qty={self.quantity} "
			f"total={self.line_total_cents}>"
		)


# ---------------------------------------------------------------------------
# POSPayment
# ---------------------------------------------------------------------------

class POSPayment(AuditMixin, Model):
	"""Payment leg of a POS transaction.

	A single transaction can have multiple payment legs (split payment).
	"""

	__allow_unmapped__ = True
	__tablename__ = "pos_payment"
	__table_args__ = (
		Index("ix_pos_payment_txn", "txn_id"),
		Index("ix_pos_payment_method", "payment_method"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	txn_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pos_transaction.id", ondelete="CASCADE"),
		nullable=False,
	)
	payment_method = Column(
		String(15),
		nullable=False,
		comment="CASH | CARD | MPESA | VOUCHER | CREDIT | SPLIT",
	)
	amount_cents = Column(BigInteger, nullable=False)
	reference = Column(String(50), nullable=True, comment="Card auth code, M-PESA txn ID, etc.")
	status = Column(
		String(15),
		nullable=False,
		default="COMPLETED",
		comment="COMPLETED | FAILED | REVERSED",
	)

	transaction: POSTransaction = relationship(
		"POSTransaction",
		back_populates="payments",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<POSPayment method={self.payment_method!r} amount={self.amount_cents} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# POSShiftReconciliation
# ---------------------------------------------------------------------------

class POSShiftReconciliation(AuditMixin, Model):
	"""End-of-shift cash reconciliation for a till.

	Captures expected vs actual cash, card and M-PESA totals, and the
	resulting variance.  Status DISCREPANCY triggers a management alert.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pos_shift_reconciliation"
	__table_args__ = (
		Index("ix_pos_shift_recon_till", "till_id"),
		Index("ix_pos_shift_recon_date", "shift_date"),
		Index("ix_pos_shift_recon_status", "status"),
		Index("ix_pos_shift_recon_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	till_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pos_till.id", ondelete="RESTRICT"),
		nullable=False,
	)
	shift_date = Column(Date, nullable=False)
	opened_by = Column(UUID(as_uuid=False), nullable=False)
	closed_by = Column(UUID(as_uuid=False), nullable=True)
	opening_float_cents = Column(BigInteger, nullable=False, default=0)
	expected_cash_cents = Column(BigInteger, nullable=False, default=0)
	actual_cash_cents = Column(BigInteger, nullable=False, default=0)
	variance_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="actual_cash - expected_cash; negative = short",
	)
	card_total_cents = Column(BigInteger, nullable=False, default=0)
	mpesa_total_cents = Column(BigInteger, nullable=False, default=0)
	transaction_count = Column(Integer, nullable=False, default=0)
	status = Column(
		String(15),
		nullable=False,
		default="OPEN",
		comment="OPEN | RECONCILED | DISCREPANCY",
	)

	till: POSTill = relationship("POSTill", lazy="select", foreign_keys=[till_id])

	def __repr__(self) -> str:
		return (
			f"<POSShiftReconciliation till={self.till_id!r} date={self.shift_date!r} "
			f"variance={self.variance_cents} status={self.status!r}>"
		)


__all__ = [
	"POSTill",
	"POSTransaction",
	"POSTransactionLine",
	"POSPayment",
	"POSShiftReconciliation",
]
