"""
pgappforge/plugins/fintech/payments/models.py

Payments Engine models.

Covers: SWIFT/RTGS (high-value), ACH/EFT (batch), PESALINK (Kenya interbank
retail), Standing Orders, Direct Debits, Card Payments, and cross-border
remittances.

Design rules enforced:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents — never Decimal/float in storage
  - PaymentOrder is effectively immutable after submission (service enforces)
  - Table name convention: py_<entity>
"""
from __future__ import annotations

import json
import os
import uuid
import logging
from datetime import datetime, date, timezone
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
from sqlalchemy.types import TypeDecorator

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# PostgreSQL sequences for collision-safe reference generation
# ---------------------------------------------------------------------------

py_payment_ref_seq = sa.Sequence("py_payment_ref_seq", start=1, increment=1)
py_batch_ref_seq = sa.Sequence("py_batch_ref_seq", start=1, increment=1)
py_so_ref_seq = sa.Sequence("py_so_ref_seq", start=1, increment=1)


# ---------------------------------------------------------------------------
# EncryptedJSONB — TypeDecorator that encrypts/decrypts connectivity_config
# ---------------------------------------------------------------------------

def _get_fernet():
	"""Return a Fernet instance using PY_RAIL_SECRET_KEY or env var."""
	try:
		from flask import current_app
		key = current_app.config.get("PY_RAIL_SECRET_KEY")
	except RuntimeError:
		key = None
	if key is None:
		key = os.environ.get("PY_RAIL_SECRET_KEY")
	if key is None:
		log.warning(
			"EncryptedJSONB: PY_RAIL_SECRET_KEY not set; "
			"connectivity_config stored as plaintext JSON"
		)
		return None
	try:
		from cryptography.fernet import Fernet
		if isinstance(key, str):
			key = key.encode()
		return Fernet(key)
	except Exception as exc:
		log.warning("EncryptedJSONB: failed to init Fernet: %s", exc)
		return None


class EncryptedJSONB(TypeDecorator):
	"""Stores a JSON-serialisable dict as Fernet-encrypted text.

	Falls back to plaintext JSON when PY_RAIL_SECRET_KEY is absent so that
	development environments work without a key configured.
	"""

	impl = Text
	cache_ok = True

	def process_bind_param(self, value: Any, dialect: Any) -> str | None:
		if value is None:
			return None
		serialised = json.dumps(value)
		fernet = _get_fernet()
		if fernet is None:
			return serialised
		try:
			return fernet.encrypt(serialised.encode()).decode()
		except Exception as exc:
			log.warning("EncryptedJSONB.encrypt failed, storing plaintext: %s", exc)
			return serialised

	def process_result_value(self, value: str | None, dialect: Any) -> Any:
		if value is None:
			return None
		fernet = _get_fernet()
		if fernet is not None:
			try:
				return json.loads(fernet.decrypt(value.encode()).decode())
			except Exception:
				# Not encrypted (legacy plaintext row) — fall through
				pass
		try:
			return json.loads(value)
		except Exception as exc:
			log.warning("EncryptedJSONB.decrypt: cannot parse value: %s", exc)
			return None


# ---------------------------------------------------------------------------
# PaymentOrder — single outbound or inbound payment instruction
# ---------------------------------------------------------------------------

class PaymentOrder(ImmutableRecordMixin, AuditMixin, Model):
	"""Immutable payment order — insert-only after submission.

	Status flow:
	  PENDING → VALIDATED → AUTHORIZED → SUBMITTED_TO_SWITCH
	          → PROCESSING → SETTLED
	                       → REJECTED
	                       → RETURNED
	  PENDING → CANCELLED  (before AUTHORIZED only)

	payment_type values:
	  RTGS / EFT / PESALINK / SWIFT / STANDING_ORDER /
	  DIRECT_DEBIT / CHEQUE / CARD_PAYMENT / REMITTANCE

	charge_type (SWIFT charging convention):
	  SHA — charges shared between sender and receiver
	  OUR — all charges borne by sender
	  BEN — all charges borne by beneficiary

	uetr — SWIFT Unique End-to-end Transaction Reference (UUID v4 as per gSRP).
	"""

	__allow_unmapped__ = True
	__tablename__ = "py_payment_order"
	__table_args__ = (
		Index("ix_py_po_reference", "payment_reference"),
		Index("ix_py_po_debtor", "debtor_account_id"),
		Index("ix_py_po_status", "status"),
		Index("ix_py_po_batch", "batch_id"),
		Index("ix_py_po_value_date", "value_date"),
		Index("ix_py_po_tenant", "tenant_id"),
		Index("ix_py_po_payment_type", "payment_type"),
		UniqueConstraint("payment_reference", name="uq_py_po_reference"),
		UniqueConstraint("uetr", name="uq_py_po_uetr"),
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

	# ── Identifiers ──────────────────────────────────────────────────────────
	payment_reference = Column(
		String(50),
		unique=True,
		nullable=False,
		comment="Bank-assigned human-readable reference (e.g. PAY-20260601-000123)",
	)
	payment_type = Column(
		String(30),
		nullable=False,
		comment=(
			"RTGS | EFT | PESALINK | SWIFT | STANDING_ORDER | "
			"DIRECT_DEBIT | CHEQUE | CARD_PAYMENT | REMITTANCE"
		),
	)

	# ── Debtor (sending) account ──────────────────────────────────────────────
	debtor_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id"),
		nullable=False,
		index=True,
		comment="FK to cb_account (sending account; always local)",
	)

	# ── Creditor (receiving) party ────────────────────────────────────────────
	creditor_account_number = Column(
		String(30),
		nullable=False,
		comment="Destination account number — may be external to this bank",
	)
	creditor_bank_code = Column(
		String(20),
		nullable=True,
		comment="BIC (SWIFT) or local CBK bank code; NULL for intra-bank",
	)
	creditor_name = Column(String(200), nullable=False)

	# ── Amounts (all INTEGER cents) ────────────────────────────────────────────
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Instruction amount in minor currency units of currency_code",
	)
	currency_code = Column(String(3), nullable=False, default="KES")
	exchange_rate = Column(
		Numeric(15, 6),
		nullable=False,
		default=1,
		comment="FX rate: 1 currency_code = exchange_rate KES. Always 1 for KES instructions.",
	)
	equivalent_ksh_cents = Column(
		Integer,
		nullable=False,
		comment="Amount expressed in KES cents after FX conversion (= amount_cents when KES)",
	)
	charges_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total bank charges in KES cents deducted from debtor or added per charge_type",
	)
	charge_type = Column(
		String(10),
		nullable=False,
		default="SHA",
		comment="SHA | OUR | BEN — SWIFT charging convention",
	)

	# ── Scheduling ────────────────────────────────────────────────────────────
	value_date = Column(
		Date,
		nullable=False,
		comment="Settlement value date (T+0 for RTGS/PESALINK, T+1 for EFT)",
	)

	# ── Purpose / narrative ───────────────────────────────────────────────────
	payment_purpose = Column(
		String(200),
		nullable=True,
		comment="Structured payment purpose code or free-text description",
	)
	remittance_info = Column(
		Text,
		nullable=True,
		comment="Free-text remittance information forwarded to beneficiary",
	)

	# ── Channel / origin ──────────────────────────────────────────────────────
	channel = Column(
		String(20),
		nullable=False,
		default="ONLINE",
		comment="ONLINE | MOBILE | BRANCH | API | BULK_FILE | STANDING_ORDER",
	)

	# ── Lifecycle status ──────────────────────────────────────────────────────
	status = Column(
		String(30),
		nullable=False,
		default="PENDING",
		comment=(
			"PENDING | VALIDATED | AUTHORIZED | SUBMITTED_TO_SWITCH | "
			"PROCESSING | SETTLED | REJECTED | RETURNED | CANCELLED"
		),
	)
	submitted_at = Column(DateTime(timezone=True), nullable=True)
	settled_at = Column(DateTime(timezone=True), nullable=True)
	returned_at = Column(DateTime(timezone=True), nullable=True)
	rejection_code = Column(
		String(20),
		nullable=True,
		comment="ISO 20022 or rail-specific rejection reason code",
	)
	rejection_reason = Column(Text, nullable=True)

	# ── Rail-specific identifiers ─────────────────────────────────────────────
	uetr = Column(
		String(36),
		nullable=True,
		unique=True,
		comment="SWIFT Unique End-to-end Transaction Reference (UUID v4, gSRP compliant)",
	)
	authorization_code = Column(
		String(50),
		nullable=True,
		comment="Authorizer employee ID or system code that approved this payment",
	)
	batch_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK to py_payment_batch when this order belongs to an ACH/EFT batch",
	)

	# ── Compliance ────────────────────────────────────────────────────────────
	sanctions_checked = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True when an OFAC/UN/EU sanctions screen has been run",
	)
	aml_flagged = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True when AML pre-check raised a suspicious activity flag",
	)

	# ── Funds hold ────────────────────────────────────────────────────────────
	hold_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="AccountHold.id from CoreBankingService.place_hold(); released on cancel/reject/return",
	)

	# ── Timestamps ────────────────────────────────────────────────────────────
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
		server_default=sa.text("NOW()"),
		comment="Set once at insert; meaningful updates use status transition records",
	)

	def __repr__(self) -> str:
		return (
			f"<PaymentOrder {self.payment_reference!r} "
			f"type={self.payment_type!r} "
			f"status={self.status!r} "
			f"amount={self.amount_cents}c {self.currency_code}>"
		)


# Register immutability guard — blocks ORM UPDATE after insert
PaymentOrder._register_immutability()


# ---------------------------------------------------------------------------
# PaymentBatch — ACH/EFT bulk file submission
# ---------------------------------------------------------------------------

class PaymentBatch(AuditMixin, Model):
	"""Aggregation of multiple PaymentOrders submitted as a single clearing file.

	Status flow:
	  DRAFT → VALIDATED → AUTHORIZED → SUBMITTED → PROCESSING
	       → SETTLED | PARTIALLY_SETTLED | FAILED

	payment_file_content: ISO 20022 PAIN.001 bulk XML or SWIFT MT102 file stored
	as text.  In production this should be offloaded to object storage; the column
	is provided for smaller deployments and development use.
	"""

	__allow_unmapped__ = True
	__tablename__ = "py_payment_batch"
	__table_args__ = (
		Index("ix_py_batch_number", "batch_number"),
		Index("ix_py_batch_status", "status"),
		Index("ix_py_batch_value_date", "value_date"),
		Index("ix_py_batch_tenant", "tenant_id"),
		UniqueConstraint("batch_number", name="uq_py_batch_number"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	batch_number = Column(
		String(30),
		unique=True,
		nullable=False,
		comment="Bank-assigned batch reference (e.g. BATCH-ACH-20260601-001)",
	)
	batch_type = Column(
		String(20),
		nullable=False,
		comment="ACH_DEBIT | ACH_CREDIT | EFT | RTGS",
	)
	value_date = Column(Date, nullable=False)
	currency_code = Column(String(3), nullable=False, default="KES")

	# ── Totals (maintained by service on each payment add/remove) ────────────
	total_payments = Column(Integer, nullable=False, default=0)
	total_amount_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Sum of amount_cents across all member PaymentOrders",
	)
	accepted_count = Column(Integer, nullable=False, default=0)
	rejected_count = Column(Integer, nullable=False, default=0)

	# ── Status ────────────────────────────────────────────────────────────────
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment=(
			"DRAFT | VALIDATED | AUTHORIZED | SUBMITTED | "
			"PROCESSING | SETTLED | PARTIALLY_SETTLED | FAILED"
		),
	)
	submitted_at = Column(DateTime(timezone=True), nullable=True)

	# ── Clearing-house response ───────────────────────────────────────────────
	clearing_reference = Column(
		String(100),
		nullable=True,
		comment="Reference returned by CBK/KEPSS/PESALINK clearing house",
	)
	payment_file_content = Column(
		Text,
		nullable=True,
		comment="ISO 20022 PAIN.001 XML or SWIFT MT102 generated for this batch",
	)

	# ── Timestamps ────────────────────────────────────────────────────────────
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
			f"<PaymentBatch {self.batch_number!r} "
			f"type={self.batch_type!r} "
			f"status={self.status!r} "
			f"total={self.total_payments} orders>"
		)


# ---------------------------------------------------------------------------
# PayStandingOrder — recurring payment instruction
# ---------------------------------------------------------------------------

class PayStandingOrder(AuditMixin, Model):
	"""Recurring payment executed on a schedule.

	frequency values:
	  WEEKLY | MONTHLY | QUARTERLY | ANNUALLY | SPECIFIC_DATES

	execution_day: day of month (1-31) for MONTHLY/QUARTERLY/ANNUALLY.
	  31 → last day of month semantics applied by service for short months.

	Status flow:
	  ACTIVE → PAUSED (manual) → ACTIVE (resume)
	  ACTIVE → CANCELLED (permanent)
	  ACTIVE → EXPIRED (end_date reached and no further executions due)
	"""

	__allow_unmapped__ = True
	__tablename__ = "py_standing_order"
	__table_args__ = (
		Index("ix_py_so_reference", "reference_number"),
		Index("ix_py_so_debtor", "debtor_account_id"),
		Index("ix_py_so_next_exec", "next_execution_date"),
		Index("ix_py_so_status", "status"),
		Index("ix_py_so_tenant", "tenant_id"),
		UniqueConstraint("reference_number", name="uq_py_so_reference"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	reference_number = Column(String(30), unique=True, nullable=False)
	debtor_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id"),
		nullable=False,
		index=True,
	)
	creditor_account_number = Column(String(30), nullable=False)
	creditor_name = Column(String(200), nullable=False)

	# ── Amount (integer cents) ────────────────────────────────────────────────
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Fixed instruction amount in KES cents (variable-amount SOs are out of scope)",
	)

	# ── Schedule ──────────────────────────────────────────────────────────────
	frequency = Column(
		String(20),
		nullable=False,
		comment="WEEKLY | MONTHLY | QUARTERLY | ANNUALLY | SPECIFIC_DATES",
	)
	execution_day = Column(
		Integer,
		nullable=True,
		comment=(
			"Day of month (1-31) for MONTHLY/QUARTERLY/ANNUALLY. "
			"NULL for WEEKLY or SPECIFIC_DATES."
		),
	)
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=True, comment="NULL = no expiry (indefinite)")
	next_execution_date = Column(
		Date,
		nullable=False,
		index=True,
		comment="Pre-computed; updated after each execution by the service",
	)

	# ── Purpose ───────────────────────────────────────────────────────────────
	payment_purpose = Column(String(200), nullable=True)

	# ── Execution statistics ──────────────────────────────────────────────────
	total_executed = Column(Integer, nullable=False, default=0)
	total_failed = Column(Integer, nullable=False, default=0)

	# ── Status ────────────────────────────────────────────────────────────────
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | PAUSED | CANCELLED | EXPIRED",
	)
	last_executed_at = Column(DateTime(timezone=True), nullable=True)

	# ── Timestamps ────────────────────────────────────────────────────────────
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
			f"<PayStandingOrder {self.reference_number!r} "
			f"freq={self.frequency!r} "
			f"next={self.next_execution_date!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# PaymentRail — connectivity + rule configuration per clearing rail
# ---------------------------------------------------------------------------

class PaymentRail(AuditMixin, Model):
	"""Configuration record for a payment clearing rail.

	rail_code examples: KEPSS, PESALINK, SWIFT, ACH_KENYA, MPESA, VISA, MASTERCARD

	rail_type:
	  RTGS | ACH | MOBILE | CARD | SWIFT | CRYPTO

	settlement_type:
	  REAL_TIME | DEFERRED | NEXT_DAY

	operating_hours JSONB shape:
	  {"open": "08:00", "close": "16:30", "timezone": "Africa/Nairobi",
	   "days": ["MON","TUE","WED","THU","FRI"]}

	fee_structure JSONB shape:
	  {"flat_cents": 5000, "pct": "0.0015", "tiers": [
	    {"min_cents": 0, "max_cents": 100000, "flat_cents": 3000},
	    {"min_cents": 100001, "max_cents": null, "flat_cents": 10000}
	  ]}

	connectivity_config JSONB: API endpoints and credentials (values must be
	encrypted at rest before storage — see pgappforge.plugins.integrations.encryption).
	"""

	__allow_unmapped__ = True
	__tablename__ = "py_payment_rail"
	__table_args__ = (
		Index("ix_py_rail_code", "rail_code"),
		Index("ix_py_rail_type", "rail_type"),
		Index("ix_py_rail_active", "is_active"),
		Index("ix_py_rail_tenant", "tenant_id"),
		UniqueConstraint("rail_code", name="uq_py_rail_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	rail_code = Column(
		String(20),
		unique=True,
		nullable=False,
		comment="Short canonical code: KEPSS | PESALINK | SWIFT | ACH_KENYA | MPESA | VISA | MASTERCARD",
	)
	rail_name = Column(String(100), nullable=False)
	rail_type = Column(
		String(20),
		nullable=False,
		comment="RTGS | ACH | MOBILE | CARD | SWIFT | CRYPTO",
	)
	settlement_type = Column(
		String(20),
		nullable=False,
		default="DEFERRED",
		comment="REAL_TIME | DEFERRED | NEXT_DAY",
	)
	operating_hours: dict[str, Any] = Column(
		JSONB,
		nullable=True,
		comment=(
			'{"open": "08:00", "close": "16:30", '
			'"timezone": "Africa/Nairobi", "days": ["MON","TUE","WED","THU","FRI"]}'
		),
	)

	# ── Amount limits (integer cents; NULL = unlimited) ───────────────────────
	max_amount_cents = Column(
		Integer,
		nullable=True,
		comment="Maximum single-transaction amount. NULL = unlimited.",
	)
	min_amount_cents = Column(
		Integer,
		nullable=False,
		default=1,
		comment="Minimum single-transaction amount in KES cents",
	)

	# ── Fee schedule ──────────────────────────────────────────────────────────
	fee_structure: dict[str, Any] = Column(
		JSONB,
		nullable=True,
		comment='{"flat_cents": 5000, "pct": "0.0015", "tiers": [...]}',
	)

	# ── Status / connectivity ─────────────────────────────────────────────────
	is_active = Column(Boolean, nullable=False, default=True)
	connectivity_config: dict[str, Any] = Column(
		EncryptedJSONB,
		nullable=True,
		comment="API endpoints and credentials — encrypted at rest via EncryptedJSONB (Fernet/AES-128-CBC)",
	)

	# ── Timestamps ────────────────────────────────────────────────────────────
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
			f"<PaymentRail {self.rail_code!r} "
			f"type={self.rail_type!r} "
			f"active={self.is_active}>"
		)


# ---------------------------------------------------------------------------
# PaymentStatusEvent — append-only audit trail of status transitions
# ---------------------------------------------------------------------------

class PaymentStatusEvent(ImmutableRecordMixin, AuditMixin, Model):
	"""Immutable audit record of every status transition on a PaymentOrder.

	This gives a full, tamper-evident timeline without updating the PaymentOrder
	row.  The service appends one row per transition.
	"""

	__allow_unmapped__ = True
	__tablename__ = "py_payment_status_event"
	__table_args__ = (
		Index("ix_py_pse_order", "payment_order_id"),
		Index("ix_py_pse_tenant", "tenant_id"),
		Index("ix_py_pse_created", "created_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	payment_order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("py_payment_order.id"),
		nullable=False,
		index=True,
	)
	from_status = Column(String(30), nullable=True, comment="NULL for the initial PENDING entry")
	to_status = Column(String(30), nullable=False)
	actor_id = Column(
		String(100),
		nullable=True,
		comment="User ID or system name that triggered the transition",
	)
	notes = Column(Text, nullable=True)

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
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<PaymentStatusEvent order={self.payment_order_id!r} "
			f"{self.from_status!r}→{self.to_status!r}>"
		)


PaymentStatusEvent._register_immutability()


# ---------------------------------------------------------------------------
# PaymentOutboxEvent — transactional outbox for durable event delivery
# ---------------------------------------------------------------------------

class PaymentOutboxEvent(ImmutableRecordMixin, AuditMixin, Model):
	"""Transactional outbox for durable at-least-once event delivery.

	Rows are inserted inside the same DB transaction as the business operation,
	guaranteeing atomicity.  A background worker polls for PENDING rows and calls
	the event bus; on success it marks DELIVERED.  After 10 failed attempts the
	row is marked DEAD for manual inspection.

	Status flow: PENDING → DELIVERED (happy path)
	             PENDING → DEAD     (10 failed attempts; manual review required)

	Polling query (run by scheduler):
	  SELECT * FROM py_payment_outbox
	   WHERE status = 'PENDING' AND next_retry_at <= NOW()
	   ORDER BY next_retry_at
	   LIMIT 100
	   FOR UPDATE SKIP LOCKED;
	"""

	__allow_unmapped__ = True
	__tablename__ = "py_payment_outbox"
	__table_args__ = (
		Index("ix_py_outbox_status_retry", "status", "next_retry_at"),
		Index("ix_py_outbox_tenant_key", "tenant_id", "idempotency_key"),
		Index("ix_py_outbox_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	event_type = Column(
		String(100),
		nullable=False,
		comment="Domain event type string, e.g. py.payment.settled",
	)
	payload = Column(
		JSONB,
		nullable=False,
		comment="Full serialised event dict; replayed verbatim by the delivery worker",
	)
	idempotency_key = Column(
		String(200),
		unique=True,
		nullable=False,
		comment="payment_reference + '::' + event_type — prevents duplicate delivery",
	)

	# ── Delivery state ────────────────────────────────────────────────────────
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | DELIVERED | DEAD",
	)
	attempts = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Number of delivery attempts made so far",
	)
	last_attempted_at = Column(DateTime(timezone=True), nullable=True)
	next_retry_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		comment="When the delivery worker should next attempt this row",
	)
	delivered_at = Column(DateTime(timezone=True), nullable=True)

	# ── Timestamps ────────────────────────────────────────────────────────────
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
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<PaymentOutboxEvent {self.event_type!r} "
			f"status={self.status!r} "
			f"attempts={self.attempts}>"
		)


PaymentOutboxEvent._register_immutability()


# ---------------------------------------------------------------------------
# PaymentReconciliationRun — ingest + match of clearing house settlement files
# ---------------------------------------------------------------------------

class PaymentReconciliationRun(AuditMixin, Model):
	"""Record of a single reconciliation pass against a clearing house file.

	Each run ingests a list of settlement items (payment_reference, amount_cents,
	cleared_at) and matches them against py_payment_order rows.  Discrepancies
	are collected in the exceptions JSONB column for ops review.

	Status flow: PENDING → PROCESSING → COMPLETE | FAILED
	"""

	__allow_unmapped__ = True
	__tablename__ = "py_reconciliation_run"
	__table_args__ = (
		Index("ix_py_recon_rail_date", "rail_code", "settlement_date"),
		Index("ix_py_recon_status", "status"),
		Index("ix_py_recon_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	rail_code = Column(String(20), nullable=False)
	settlement_date = Column(Date, nullable=False)
	file_reference = Column(
		String(100),
		nullable=True,
		comment="Clearing house file identifier or transmission reference",
	)

	# ── Progress / results ────────────────────────────────────────────────────
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | PROCESSING | COMPLETE | FAILED",
	)
	total_items = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total items in the settlement file",
	)
	matched_count = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Items matched to a known PaymentOrder",
	)
	unmatched_count = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Items in the file with no matching PaymentOrder",
	)
	exceptions = Column(
		JSONB,
		nullable=True,
		comment='List of {payment_reference, issue} dicts for ops review',
	)
	run_at = Column(DateTime(timezone=True), nullable=True)

	# ── Timestamps ────────────────────────────────────────────────────────────
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
			f"<PaymentReconciliationRun rail={self.rail_code!r} "
			f"date={self.settlement_date!r} "
			f"status={self.status!r} "
			f"matched={self.matched_count}/{self.total_items}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"PaymentOrder",
	"PaymentBatch",
	"PayStandingOrder",
	"PaymentRail",
	"PaymentStatusEvent",
	"PaymentOutboxEvent",
	"PaymentReconciliationRun",
	"EncryptedJSONB",
	"py_payment_ref_seq",
	"py_batch_ref_seq",
	"py_so_ref_seq",
]
