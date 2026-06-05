"""
pgappforge/plugins/fintech/pswitch_adapter/models.py

SQLAlchemy 2.x models for the Pswitch Adapter plugin.

Tables
------
  pswitch_card_transaction   — one row per ISO 8583 authorization / clearing message
  pswitch_settlement_file    — one row per inbound settlement file (VISA/MC/KENSWITCH/…)

Design rules
------------
  - PostgreSQL ONLY — uses JSONB, TIMESTAMPTZ, gen_random_uuid()
  - All PKs: UUID(as_uuid=False) with Python default_factory + PG server default
  - Money stored as INTEGER CENTS in BigInteger columns
  - tenant_id on every table (multi-tenant)
  - AuditMixin for automatic audit trail
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
	DateTime,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"CardTransaction",
	"CardSettlementFile",
]

_uuid4 = lambda: str(uuid.uuid4())  # noqa: E731


# ---------------------------------------------------------------------------
# CardTransaction
# ---------------------------------------------------------------------------

class CardTransaction(AuditMixin, Model):
	"""One ISO 8583 authorization/clearing/settlement record per card transaction.

	Lifecycle: AUTHORIZED → CLEARED → SETTLED (happy path)
	           AUTHORIZED → REVERSED  (reversal)
	           DECLINED              (declined at auth time)

	Monetary fields
	---------------
	  amount_cents   — transaction amount in minor currency units (e.g. KES cents)

	ISO 8583 fields
	---------------
	  mti               — Message Type Indicator (e.g. "0100" auth, "0200" financial)
	  processing_code   — DE-3 (e.g. "000000" purchase, "010000" withdrawal)
	  response_code     — DE-39 2-char ISO response code
	  auth_code         — DE-38 6-char authorization code (present on approve)
	  terminal_id       — DE-41 8-char terminal identifier
	  acquirer_id       — DE-32 11-char acquiring institution identifier
	"""

	__allow_unmapped__ = True
	__tablename__ = "pswitch_card_transaction"
	__table_args__ = (
		Index("ix_pswitch_txn_tenant", "tenant_id"),
		Index("ix_pswitch_txn_account", "account_id"),
		Index("ix_pswitch_txn_status", "status"),
		Index("ix_pswitch_txn_authorized_at", "authorized_at"),
		UniqueConstraint("pswitch_txn_id", name="uq_pswitch_txn_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		String(64),
		nullable=False,
		index=True,
		comment="Tenant identifier",
	)

	# ------------------------------------------------------------------
	# Pswitch / ISO 8583 identity
	# ------------------------------------------------------------------

	pswitch_txn_id = Column(
		String(64),
		nullable=False,
		unique=True,
		comment="Transaction ID assigned by pswitch (STAN + system trace or UUID7)",
	)

	# ------------------------------------------------------------------
	# Core banking linkage
	# ------------------------------------------------------------------

	account_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK to core_banking Account.id (logical, no DB constraint for perf)",
	)

	# ------------------------------------------------------------------
	# Card details
	# ------------------------------------------------------------------

	card_pan_masked = Column(
		String(19),
		nullable=False,
		comment="PAN masked: first 6 + **** + last 4, e.g. 411111******1111",
	)
	card_scheme = Column(
		String(20),
		nullable=False,
		default="KENSWITCH",
		comment="VISA | MASTERCARD | AMEX | KENSWITCH | JCB",
	)

	# ------------------------------------------------------------------
	# Transaction classification
	# ------------------------------------------------------------------

	transaction_type = Column(
		String(20),
		nullable=False,
		comment="PURCHASE | WITHDRAWAL | REVERSAL | REFUND | BALANCE_INQUIRY",
	)
	mti = Column(
		String(4),
		nullable=False,
		comment="ISO 8583 Message Type Indicator, e.g. 0100/0110/0200/0420",
	)
	processing_code = Column(
		String(6),
		nullable=True,
		comment="DE-3: 000000=purchase, 010000=withdrawal, 200000=refund, etc.",
	)

	# ------------------------------------------------------------------
	# Amounts
	# ------------------------------------------------------------------

	amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Transaction amount in minor currency units (integer cents)",
	)
	currency_code = Column(
		String(3),
		nullable=False,
		default="KES",
		comment="ISO 4217 alpha-3 currency code",
	)

	# ------------------------------------------------------------------
	# Merchant / terminal
	# ------------------------------------------------------------------

	merchant_name = Column(String(100), nullable=True)
	merchant_category_code = Column(
		String(4),
		nullable=True,
		comment="ISO 18245 MCC",
	)
	terminal_id = Column(
		String(8),
		nullable=True,
		comment="DE-41: 8-char terminal ID",
	)
	acquirer_id = Column(
		String(11),
		nullable=True,
		comment="DE-32: acquiring institution ID (up to 11 digits)",
	)

	# ------------------------------------------------------------------
	# Authorization result
	# ------------------------------------------------------------------

	auth_code = Column(
		String(6),
		nullable=True,
		comment="DE-38: 6-char issuer authorization code (present on approve)",
	)
	response_code = Column(
		String(2),
		nullable=False,
		default="05",
		comment=(
			"ISO 8583 DE-39: '00'=approved, '05'=do not honor, "
			"'51'=insufficient funds, '54'=expired, etc."
		),
	)

	# ------------------------------------------------------------------
	# Lifecycle status
	# ------------------------------------------------------------------

	status = Column(
		String(20),
		nullable=False,
		default="DECLINED",
		comment="AUTHORIZED | CLEARED | SETTLED | REVERSED | DECLINED",
	)

	# ------------------------------------------------------------------
	# Timestamps (TIMESTAMPTZ — explicit timezone=True)
	# ------------------------------------------------------------------

	authorized_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="When the authorization was approved by pswitch",
	)
	cleared_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="When the clearing message was received",
	)
	settled_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="When the settlement file entry was posted to GL",
	)

	# ------------------------------------------------------------------
	# Core banking linkage (post-settlement)
	# ------------------------------------------------------------------

	ledger_entry_id = Column(
		String(36),
		nullable=True,
		comment="FK to LedgerEntry.id — set when settlement posts to GL",
	)
	hold_id = Column(
		String(36),
		nullable=True,
		comment="FK to AccountHold.id — set when authorization hold is placed",
	)

	# ------------------------------------------------------------------
	# Extensible attributes
	# ------------------------------------------------------------------

	attributes: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Overflow / scheme-specific fields (e.g. EMV data, network codes)",
	)

	# ------------------------------------------------------------------
	# Audit timestamps (not provided by AuditMixin columns — defined here
	# to match the project convention; AuditMixin adds the event log)
	# ------------------------------------------------------------------

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
			f"<CardTransaction {self.pswitch_txn_id} "
			f"{self.transaction_type} {self.amount_cents}c {self.status}>"
		)


# ---------------------------------------------------------------------------
# CardSettlementFile
# ---------------------------------------------------------------------------

class CardSettlementFile(AuditMixin, Model):
	"""One inbound settlement file from a card scheme or internal batch.

	Each file contains N records that debit/credit cardholder accounts.
	The service processes the file transactionally: all records succeed or
	the file rolls back to FAILED.

	Status lifecycle: RECEIVED → PROCESSING → POSTED → RECONCILED
	                            └──────────→ FAILED  (on any unrecoverable error)

	Monetary totals are in minor currency units (integer cents).
	"""

	__allow_unmapped__ = True
	__tablename__ = "pswitch_settlement_file"
	__table_args__ = (
		Index("ix_pswitch_sf_tenant", "tenant_id"),
		Index("ix_pswitch_sf_file_date", "file_date"),
		Index("ix_pswitch_sf_status", "status"),
		UniqueConstraint("file_ref", "tenant_id", name="uq_pswitch_sf_ref_tenant"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		String(64),
		nullable=False,
		index=True,
		comment="Tenant identifier",
	)

	# ------------------------------------------------------------------
	# File identity
	# ------------------------------------------------------------------

	file_date = Column(
		sa.Date,
		nullable=False,
		comment="Settlement date (value date for GL posting)",
	)
	file_ref = Column(
		String(50),
		nullable=False,
		comment="Unique file reference within tenant, e.g. VISA-20240601-001",
	)
	source = Column(
		String(20),
		nullable=False,
		default="INTERNAL",
		comment="VISA_NET | MASTERCARD_S2S | KENSWITCH | INTERNAL | MANUAL",
	)

	# ------------------------------------------------------------------
	# Aggregates
	# ------------------------------------------------------------------

	record_count = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total number of records in the file",
	)
	total_debits_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Sum of all DEBIT record amounts in minor currency units",
	)
	total_credits_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Sum of all CREDIT record amounts in minor currency units",
	)

	# ------------------------------------------------------------------
	# Processing state
	# ------------------------------------------------------------------

	status = Column(
		String(20),
		nullable=False,
		default="RECEIVED",
		comment="RECEIVED | PROCESSING | POSTED | RECONCILED | FAILED",
	)
	processed_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="When status transitioned to POSTED",
	)
	error_summary = Column(
		Text,
		nullable=True,
		comment="Human-readable error description if status=FAILED",
	)

	# ------------------------------------------------------------------
	# Audit timestamps
	# ------------------------------------------------------------------

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
			f"<CardSettlementFile {self.file_ref} "
			f"{self.source} {self.status} "
			f"{self.record_count} records>"
		)
