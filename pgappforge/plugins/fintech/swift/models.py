"""
pgappforge/plugins/fintech/swift/models.py

SWIFT messaging models for correspondent banking.

Design rules:
  - ALL monetary amounts: INTEGER cents — never Decimal/float in storage
  - PKs: UUID(as_uuid=False) + default=lambda: str(uuid.uuid4())
  - All timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - PostgreSQL ONLY: JSONB, gen_random_uuid()
  - Every model: tenant_id, created_at, updated_at
  - Table name convention: swift_<entity>

Supported message types:
  MT103  — Single Customer Credit Transfer (international retail payments)
  MT202  — Financial Institution Transfer (bank-to-bank cover payments)
  MT900  — Confirmation of Debit (nostro debit confirmation)
  MT910  — Confirmation of Credit (nostro credit confirmation)

gpi (SWIFT Global Payments Innovation):
  UETR   — Unique End-to-End Transaction Reference (UUID4, RFC 4122)
  Status codes: ACSP (processing), ACCC (completed), RJCT (rejected), PDNG (pending)
"""
from __future__ import annotations

import uuid
import logging
from datetime import date, datetime, timezone
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
# SWIFTMessage
# ---------------------------------------------------------------------------

class SWIFTMessage(ImmutableRecordMixin, AuditMixin, Model):
	"""SWIFT FIN message record — outbound or inbound.

	Covers MT103, MT202, MT900, MT910 message types.

	raw_message stores the actual SWIFT FIN block text (:20: ... -}) for
	audit, replay, and bureau transmission. In production this field feeds
	directly into the SWIFT Alliance Access / SWIFT Service Bureau queue.

	amount_cents is always in the currency denoted by currency_code (minor
	units, e.g. USD cents, KES cents). Never float.

	Status flow (outbound):
	  DRAFT → SENT → ACKNOWLEDGED → DELIVERED | FAILED | REJECTED

	Status flow (inbound):
	  RECEIVED → PROCESSED | FAILED | REJECTED

	uetr: UUID4 Unique End-to-End Transaction Reference per SWIFT gpi.
	      Mandatory for MT103 from Nov 2020 (gpi mandatory adoption).
	      Optional for MT202 (MT202 COV carries it).
	"""

	__allow_unmapped__ = True
	__tablename__ = "swift_message"
	__table_args__ = (
		UniqueConstraint("message_ref", "tenant_id", name="uq_swift_msg_ref_tenant"),
		Index("ix_swift_msg_type", "message_type"),
		Index("ix_swift_msg_status", "status"),
		Index("ix_swift_msg_uetr", "uetr"),
		Index("ix_swift_msg_tenant_created", "tenant_id", "created_at"),
		Index("ix_swift_msg_value_date", "value_date"),
		# Tenant-scoped indexes for common filtered queries
		Index("ix_swift_msg_tenant_status", "tenant_id", "status"),
		Index("ix_swift_msg_tenant_uetr", "tenant_id", "uetr"),
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
		comment="Multi-tenant isolation key",
	)

	# Message identity
	message_ref = Column(
		String(16),
		nullable=False,
		comment="SWIFT field :20: — sender's reference, max 16 chars, unique per tenant",
	)
	message_type = Column(
		String(10),
		nullable=False,
		comment="MT103 | MT202 | MT900 | MT910",
	)
	direction = Column(
		String(10),
		nullable=False,
		comment="OUTBOUND | INBOUND",
	)
	status = Column(
		String(16),
		nullable=False,
		default="DRAFT",
		server_default="'DRAFT'",
		comment="DRAFT | SENT | ACKNOWLEDGED | DELIVERED | RECEIVED | PROCESSED | FAILED | REJECTED",
	)

	# BIC addresses
	sender_bic = Column(
		String(11),
		nullable=False,
		comment="BIC11 of the sending institution (field :1: / block 1)",
	)
	receiver_bic = Column(
		String(11),
		nullable=False,
		comment="BIC11 of the receiving institution (field :2: / block 2)",
	)

	# Value / settlement
	value_date = Column(
		Date,
		nullable=False,
		comment="Settlement value date (field :32A: YYMMDD)",
	)
	currency_code = Column(
		String(3),
		nullable=False,
		comment="ISO 4217 currency code e.g. USD, EUR, KES",
	)
	amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Transfer amount in minor currency units (integer cents — never float)",
	)

	# MT103 customer fields (nullable — absent for MT202/MT900/MT910)
	ordering_customer = Column(
		Text,
		nullable=True,
		comment="MT103 field :50K: — ordering customer name/account",
	)
	beneficiary_customer = Column(
		Text,
		nullable=True,
		comment="MT103 field :59: — beneficiary customer name/account",
	)
	remittance_info = Column(
		Text,
		nullable=True,
		comment="MT103 field :70: — remittance information (max 4×35 chars in SWIFT)",
	)

	# Raw FIN message body
	raw_message = Column(
		Text,
		nullable=True,
		comment="Full SWIFT FIN block 4 text starting with {4: through -}",
	)

	# gpi UETR
	uetr = Column(
		String(36),
		nullable=True,
		index=True,
		comment="UUID4 Unique End-to-End Transaction Reference (mandatory MT103 gpi from Nov 2020)",
	)

	# Lifecycle timestamps
	ack_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when ACK/NAK received from SWIFT network (UAK/UNK)",
	)
	delivered_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when gpi status ACCC received — funds confirmed delivered",
	)

	# Error fields
	error_code = Column(
		String(10),
		nullable=True,
		comment="SWIFT error/reason code e.g. AC01, AG01, FOCR",
	)
	error_text = Column(
		Text,
		nullable=True,
		comment="Human-readable error description from SWIFT or receiving bank",
	)

	# GL linkage
	gl_journal_id = Column(
		Text,
		nullable=True,
		comment="Journal ID from GL plugin for the debit/credit posting (non-FK to avoid circular mapper)",
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

	# Relationship to gpi status trail
	gpi_statuses: list[SWIFTGpiStatus] = relationship(
		"SWIFTGpiStatus",
		back_populates="message",
		cascade="all, delete-orphan",
		lazy="select",
		foreign_keys="SWIFTGpiStatus.message_id",
	)

	def __repr__(self) -> str:
		return (
			f"<SWIFTMessage ref={self.message_ref!r} type={self.message_type} "
			f"dir={self.direction} status={self.status!r} "
			f"amount={self.amount_cents} {self.currency_code}>"
		)


# ---------------------------------------------------------------------------
# SWIFTGpiStatus
# ---------------------------------------------------------------------------

class SWIFTGpiStatus(Model):
	"""SWIFT gpi (Global Payments Innovation) tracker status update.

	Each row represents a single status update received from the gpi Tracker
	for a payment identified by its UETR. Multiple updates accumulate over the
	payment's lifecycle as it passes through correspondent chains.

	status_code follows ISO 20022 / SWIFT gpi codes:
	  ACSP — Accepted Settlement In Process (intermediate agent)
	  ACCC — Accepted Credit Completed (final beneficiary credited)
	  RJCT — Rejected (with mandatory reason code in status_reason)
	  PDNG — Pending investigation / investigation in progress

	agent_bic:     the agent bank sending this status update
	updated_by_bank: the gpi member bank that wrote this update to the tracker
	raw_payload:   the original JSON payload from the gpi Tracker API (stored
	               verbatim for audit and replay)

	This table is append-only — status updates are never mutated.
	"""

	__allow_unmapped__ = True
	__tablename__ = "swift_gpi_status"
	__table_args__ = (
		Index("ix_swift_gpi_uetr", "uetr"),
		Index("ix_swift_gpi_message_id", "message_id"),
		Index("ix_swift_gpi_status_code", "status_code"),
		Index("ix_swift_gpi_tenant_ts", "tenant_id", "event_timestamp"),
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
		comment="Multi-tenant isolation key",
	)

	uetr = Column(
		String(36),
		nullable=False,
		index=True,
		comment="UUID4 UETR linking back to the originating SWIFTMessage",
	)
	message_id = Column(
		UUID(as_uuid=False),
		ForeignKey("swift_message.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# gpi status
	status_code = Column(
		String(4),
		nullable=False,
		comment="ACSP | ACCC | RJCT | PDNG",
	)
	agent_bic = Column(
		String(11),
		nullable=False,
		comment="BIC of the agent bank reporting this status",
	)
	status_reason = Column(
		String(4),
		nullable=True,
		comment="ISO 20022 reason code — mandatory for RJCT e.g. AC01, AG01, FOCR",
	)
	updated_by_bank = Column(
		String(11),
		nullable=False,
		comment="BIC of the gpi member bank that wrote this update to the tracker",
	)
	event_timestamp = Column(
		DateTime(timezone=True),
		nullable=False,
		comment="Timestamp of the status event at the reporting agent",
	)
	raw_payload = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Verbatim JSON payload from SWIFT gpi Tracker API",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationship
	message: SWIFTMessage = relationship(
		"SWIFTMessage",
		back_populates="gpi_statuses",
		foreign_keys=[message_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<SWIFTGpiStatus uetr={self.uetr!r} status={self.status_code} "
			f"agent={self.agent_bic} ts={self.event_timestamp}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SWIFTMessage",
	"SWIFTGpiStatus",
]
