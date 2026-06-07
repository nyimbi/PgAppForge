"""
pgappforge/plugins/erp/finance/intercompany/models.py

SQLAlchemy models for the Intercompany Posting plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - ALL monetary amounts: BigInteger cents (NEVER Numeric/float for money)
  - ALL models: tenant_id VARCHAR(50) NOT NULL
  - Soft FKs across plugin boundaries (VARCHAR, no DB-level FK constraint)
  - PostgreSQL: JSONB for document_data, TIMESTAMPTZ, BigInteger cents
  - AuditMixin on every mutable entity

Table prefix: ic_

Key design:
  ICOutboxTransaction — created by source entity, represents a pending send.
  ICInboxTransaction  — created simultaneously at target entity; receiver acts on this.
  correlation_id      — shared string linking outbox ↔ inbox for reconciliation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	CheckConstraint,
	Column,
	DateTime,
	ForeignKey,
	Index,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ICOutboxTransaction
# ---------------------------------------------------------------------------

class ICOutboxTransaction(AuditMixin, Model):
	"""Outbound intercompany transaction: created by the source entity.

	Lifecycle: PENDING → SENT → ACCEPTED | REJECTED

	document_data JSONB schema depends on transaction_type:
	  PO_MIRROR      — {po_number, lines: [{product_id, qty, unit_cost_cents, ...}], ...}
	  SO_MIRROR      — {so_number, lines: [...], ...}
	  JOURNAL_MIRROR — {period, lines: [{account, debit_cents, credit_cents}], ...}
	  PAYMENT_MIRROR — {payment_ref, amount_cents, currency, payment_date, ...}

	source_entity_id / target_entity_id are soft FKs to the entity registry.
	correlation_id links this outbox to its corresponding ICInboxTransaction.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ic_outbox"
	__table_args__ = (
		Index("ix_ic_outbox_tenant_source_status", "tenant_id", "source_entity_id", "status"),
		Index("ix_ic_outbox_tenant_target_status", "tenant_id", "target_entity_id", "status"),
		Index("ix_ic_outbox_correlation", "correlation_id"),
		CheckConstraint(
			"status IN ('PENDING','SENT','ACCEPTED','REJECTED')",
			name="ck_ic_outbox_status",
		),
		CheckConstraint(
			"transaction_type IN ('PO_MIRROR','SO_MIRROR','JOURNAL_MIRROR','PAYMENT_MIRROR')",
			name="ck_ic_outbox_type",
		),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	source_entity_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Entity originating the IC transaction (soft FK)",
	)
	target_entity_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Entity that must receive and post the mirror document (soft FK)",
	)
	transaction_type = Column(
		String(30),
		nullable=False,
		comment="PO_MIRROR | SO_MIRROR | JOURNAL_MIRROR | PAYMENT_MIRROR",
	)
	document_data = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Full serialised document payload; schema determined by transaction_type",
	)

	# Lifecycle
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | SENT | ACCEPTED | REJECTED",
	)
	sent_at = Column(DateTime(timezone=True), nullable=True)
	response_at = Column(DateTime(timezone=True), nullable=True)
	rejection_reason = Column(Text, nullable=True)
	correlation_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Shared ID linking this outbox to the matching ICInboxTransaction",
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
	inbox_transactions: list[ICInboxTransaction] = relationship(
		"ICInboxTransaction",
		back_populates="outbox",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ICOutboxTransaction id={self.id!r} type={self.transaction_type!r} "
			f"{self.source_entity_id!r}→{self.target_entity_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ICInboxTransaction
# ---------------------------------------------------------------------------

class ICInboxTransaction(AuditMixin, Model):
	"""Inbound intercompany transaction: received by the target entity.

	Created simultaneously with ICOutboxTransaction by send_transaction().
	The target entity acts on this record: accept → post mirror document,
	or reject → set status=REJECTED with reason on outbox.

	Lifecycle: PENDING → ACCEPTED | REJECTED

	created_document_id — ID of the mirror document created at the target entity
	  (e.g. a sales order UUID for PO_MIRROR, journal entry UUID for JOURNAL_MIRROR).
	  This is a soft FK; the type depends on transaction_type.

	outbox_id is a nullable FK to ic_outbox (SET NULL on delete, for orphan safety).
	"""

	__allow_unmapped__ = True
	__tablename__ = "ic_inbox"
	__table_args__ = (
		Index("ix_ic_inbox_tenant_target_status", "tenant_id", "target_entity_id", "status"),
		Index("ix_ic_inbox_correlation", "correlation_id"),
		CheckConstraint(
			"status IN ('PENDING','ACCEPTED','REJECTED')",
			name="ck_ic_inbox_status",
		),
		CheckConstraint(
			"transaction_type IN ('PO_MIRROR','SO_MIRROR','JOURNAL_MIRROR','PAYMENT_MIRROR')",
			name="ck_ic_inbox_type",
		),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	outbox_id = Column(
		String(50),
		ForeignKey("ic_outbox.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="Originating outbox record; SET NULL if outbox is deleted",
	)

	source_entity_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Entity that sent this transaction",
	)
	target_entity_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="This entity — the receiver",
	)
	transaction_type = Column(
		String(30),
		nullable=False,
		comment="PO_MIRROR | SO_MIRROR | JOURNAL_MIRROR | PAYMENT_MIRROR",
	)
	document_data = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Copy of outbox document_data at send time",
	)

	# Lifecycle
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | ACCEPTED | REJECTED",
	)
	created_document_id = Column(
		String(50),
		nullable=True,
		comment="Soft FK: ID of the mirror document created upon acceptance",
	)
	processed_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp of accept/reject action",
	)
	correlation_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Shared correlation ID linking inbox to outbox",
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
	outbox: ICOutboxTransaction | None = relationship(
		"ICOutboxTransaction",
		back_populates="inbox_transactions",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ICInboxTransaction id={self.id!r} type={self.transaction_type!r} "
			f"{self.source_entity_id!r}→{self.target_entity_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ICOutboxTransaction",
	"ICInboxTransaction",
]
