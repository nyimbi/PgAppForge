"""
pgappforge/plugins/fintech/card_issuing/models.py

Card Issuing models — BIN registry, issued cards, PIN blocks, and auth logs.

Design rules:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - PINBlock and CardAuthorizationLog: ImmutableRecordMixin (insert-only)
  - PAN is NEVER stored; only hash + last4 + masked form are persisted

Table name convention: ci_<entity>
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
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# CardBIN — Bank Identification Number registry
# ---------------------------------------------------------------------------

class CardBIN(AuditMixin, Model):
	"""BIN registry entry — maps a 6-8 digit BIN to a card scheme and product.

	network: VISA | MASTERCARD | AMEX | UNIONPAY | DISCOVER
	card_type: DEBIT | CREDIT | PREPAID | VIRTUAL
	product_code: optional product code for this BIN range (e.g. "VISA_DEBIT_KES")
	"""

	__allow_unmapped__ = True
	__tablename__ = "ci_card_bin"
	__table_args__ = (
		UniqueConstraint("bin_code", name="uq_ci_card_bin_code"),
		Index("ix_ci_card_bin_network", "network"),
		Index("ix_ci_card_bin_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	bin_code = Column(
		String(8),
		unique=True,
		nullable=False,
		comment="6-8 digit BIN / IIN (Bank Identification Number)",
	)
	network = Column(
		String(10),
		nullable=False,
		comment="VISA | MASTERCARD | AMEX | UNIONPAY | DISCOVER",
	)
	card_type = Column(
		String(10),
		nullable=False,
		default="DEBIT",
		comment="DEBIT | CREDIT | PREPAID | VIRTUAL",
	)
	product_code = Column(
		String(20),
		nullable=True,
		comment="Optional product code for this BIN range",
	)
	is_active = Column(Boolean, nullable=False, default=True)

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
	issued_cards: list[IssuedCard] = relationship(
		"IssuedCard",
		back_populates="bin",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<CardBIN {self.bin_code!r} network={self.network!r} type={self.card_type!r}>"


# ---------------------------------------------------------------------------
# IssuedCard — the issued payment card record
# ---------------------------------------------------------------------------

class IssuedCard(AuditMixin, Model):
	"""An issued payment card linked to a customer account.

	The PAN (Primary Account Number) is NEVER stored.  Only the hash,
	last 4 digits, and a masked form are persisted for display and lookup.

	status flow:
	  INACTIVE → ACTIVE (activate_card) → BLOCKED (block_card / pin_locked)
	  ACTIVE   → REPLACED (replace_card — old card blocked, new card issued)
	  ACTIVE   → EXPIRED  (expiry check)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ci_issued_card"
	__table_args__ = (
		Index("ix_ci_card_account", "account_id"),
		Index("ix_ci_card_bin", "bin_id"),
		Index("ix_ci_card_status", "status"),
		Index("ix_ci_card_hash", "card_number_hash"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	account_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Customer account identifier (FK to core banking Account)",
	)
	bin_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ci_card_bin.id"),
		nullable=False,
		index=True,
	)

	# PAN fields — PAN itself is NEVER stored
	card_number_hash = Column(
		String(64),
		nullable=False,
		comment="SHA-256 hex hash of the PAN for lookup without storing PAN",
	)
	card_number_last4 = Column(
		String(4),
		nullable=False,
		comment="Last 4 digits of the PAN for display",
	)
	card_number_masked = Column(
		String(19),
		nullable=False,
		comment="Masked PAN for display, e.g. 4242 **** **** 1234",
	)

	# Expiry
	expiry_month = Column(Integer, nullable=False, comment="Expiry month (1-12)")
	expiry_year = Column(Integer, nullable=False, comment="Expiry year (4 digits)")

	# Card identity
	cardholder_name = Column(
		String(26),
		nullable=False,
		comment="Cardholder name embossed on card (max 26 chars per ISO 7813)",
	)
	is_virtual = Column(
		Boolean,
		nullable=False,
		default=True,
		comment="True for virtual-only cards (no physical plastic)",
	)

	# Card lifecycle
	status = Column(
		String(12),
		nullable=False,
		default="INACTIVE",
		comment="INACTIVE | ACTIVE | BLOCKED | REPLACED | EXPIRED",
	)
	block_reason = Column(
		String(50),
		nullable=True,
		comment="Reason for blocking: PIN_LOCKED | FRAUD | LOST | STOLEN | OPERATOR",
	)

	# Limits & usage
	daily_limit_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Per-day spend limit in minor currency units; 0 = no limit",
	)

	# PIN management
	pin_set_at = Column(DateTime(timezone=True), nullable=True)
	pin_attempts = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Consecutive failed PIN attempts since last success; blocked at 3",
	)

	# Lifecycle timestamps
	activated_at = Column(DateTime(timezone=True), nullable=True)
	last_used_at = Column(DateTime(timezone=True), nullable=True)

	# Flexible metadata (e.g. issuer notes, channel restrictions)
	card_metadata: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Flexible card metadata (issuer notes, channel restrictions, etc.)",
	)

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
	bin: CardBIN = relationship("CardBIN", back_populates="issued_cards", lazy="select")
	pin_block: PINBlock | None = relationship(
		"PINBlock",
		back_populates="card",
		uselist=False,
		lazy="select",
	)
	authorization_logs: list[CardAuthorizationLog] = relationship(
		"CardAuthorizationLog",
		back_populates="card",
		lazy="select",
		order_by="CardAuthorizationLog.created_at.desc()",
	)

	def __repr__(self) -> str:
		return (
			f"<IssuedCard {self.id!r} "
			f"masked={self.card_number_masked!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# PINBlock — encrypted PIN storage (immutable; delete+insert to change PIN)
# ---------------------------------------------------------------------------

class PINBlock(ImmutableRecordMixin, Model):
	"""Encrypted PIN block for a card.

	CRITICAL INVARIANT: rows are INSERT-ONLY.  To change a PIN, the service
	deletes the existing row and inserts a new one.  This preserves a clean
	audit trail without UPDATE operations.

	algorithm: encryption algorithm used — default AES256GCM.
	encrypted_pin: base64-encoded ciphertext.
	pin_nonce: base64-encoded nonce (12 bytes for AES-GCM).
	"""

	__allow_unmapped__ = True
	__tablename__ = "ci_pin_block"
	__table_args__ = (
		UniqueConstraint("card_id", name="uq_ci_pin_block_card"),
		Index("ix_ci_pin_block_card", "card_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	card_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ci_issued_card.id"),
		unique=True,
		nullable=False,
		index=True,
	)
	encrypted_pin = Column(
		Text,
		nullable=False,
		comment="Base64-encoded AES-256-GCM ciphertext of the PIN",
	)
	pin_nonce = Column(
		Text,
		nullable=False,
		comment="Base64-encoded 12-byte GCM nonce used for this PIN encryption",
	)
	algorithm = Column(
		String(20),
		nullable=False,
		default="AES256GCM",
		comment="Encryption algorithm: AES256GCM",
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		comment="Timestamp when this PIN block was created (immutable)",
	)

	# Relationship
	card: IssuedCard = relationship("IssuedCard", back_populates="pin_block", lazy="select")

	def __repr__(self) -> str:
		return f"<PINBlock card_id={self.card_id!r} algo={self.algorithm!r}>"


# Register immutability guard
PINBlock._register_immutability()


# ---------------------------------------------------------------------------
# CardAuthorizationLog — immutable transaction authorization audit trail
# ---------------------------------------------------------------------------

class CardAuthorizationLog(ImmutableRecordMixin, Model):
	"""Immutable record of every card authorization attempt.

	One row per authorization request regardless of outcome.
	Approved and declined attempts are both recorded.

	authorization_type: PURCHASE | REFUND | CASH_ADVANCE | BALANCE_INQUIRY | 3DS_AUTH
	result: APPROVED | DECLINED | ERROR
	decline_reason: INSUFFICIENT_FUNDS | CARD_BLOCKED | EXPIRED_CARD |
	                DAILY_LIMIT_EXCEEDED | PIN_INCORRECT | INVALID_CARD | FRAUD_DECLINE
	"""

	__allow_unmapped__ = True
	__tablename__ = "ci_auth_log"
	__table_args__ = (
		Index("ix_ci_auth_card", "card_id"),
		Index("ix_ci_auth_result", "result"),
		Index("ix_ci_auth_created", "created_at"),
		Index("ix_ci_auth_rrn", "rrn"),
		Index(
			"ix_ci_auth_card_created",
			"card_id",
			"created_at",
			postgresql_using="brin",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	card_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ci_issued_card.id"),
		nullable=False,
		index=True,
	)
	authorization_type = Column(
		String(20),
		nullable=True,
		comment="PURCHASE | REFUND | CASH_ADVANCE | BALANCE_INQUIRY | 3DS_AUTH",
	)
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Transaction amount in minor currency units",
	)
	currency_code = Column(String(3), nullable=False, default="KES")

	# Merchant info
	merchant_name = Column(String(100), nullable=True)
	merchant_category_code = Column(
		String(4),
		nullable=True,
		comment="ISO 18245 Merchant Category Code (4 digits)",
	)
	terminal_id = Column(
		String(8),
		nullable=True,
		comment="POS terminal ID (up to 8 chars per ISO 8583)",
	)

	# Authorization outcome
	result = Column(
		String(10),
		nullable=False,
		comment="APPROVED | DECLINED | ERROR",
	)
	decline_reason = Column(
		String(50),
		nullable=True,
		comment=(
			"INSUFFICIENT_FUNDS | CARD_BLOCKED | EXPIRED_CARD | "
			"DAILY_LIMIT_EXCEEDED | PIN_INCORRECT | INVALID_CARD | FRAUD_DECLINE"
		),
	)
	authorization_code = Column(
		String(6),
		nullable=True,
		comment="6-char approval code returned to terminal on APPROVED",
	)
	rrn = Column(
		String(12),
		nullable=True,
		index=True,
		comment="Retrieval Reference Number (ISO 8583 F37, 12 chars)",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationship
	card: IssuedCard = relationship(
		"IssuedCard",
		back_populates="authorization_logs",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CardAuthorizationLog card={self.card_id!r} "
			f"type={self.authorization_type!r} "
			f"result={self.result!r} "
			f"amount={self.amount_cents}c>"
		)


# Register immutability guard
CardAuthorizationLog._register_immutability()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"CardBIN",
	"IssuedCard",
	"PINBlock",
	"CardAuthorizationLog",
]
