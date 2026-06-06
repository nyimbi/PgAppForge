"""
pgappforge/plugins/erp/platform/whatsapp/models.py

SQLAlchemy models for the WhatsApp Business API integration plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured fields (components, template_params, tags)
  - PostgreSQL ONLY — no portability shims
  - Money is irrelevant here; no monetary columns in this domain

Table prefix: wa_
"""
from __future__ import annotations

import uuid
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


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# WhatsAppTemplate
# ---------------------------------------------------------------------------

class WhatsAppTemplate(AuditMixin, Model):
	"""WhatsApp message template registered with Meta / WhatsApp Business API.

	Templates must be approved by WhatsApp before they can be used for
	outbound messaging.  The ``components`` JSONB field stores the full
	WhatsApp template component structure (HEADER, BODY, FOOTER, BUTTONS)
	as returned/submitted to the WhatsApp Business API.

	status machine: PENDING → APPROVED | REJECTED
	                APPROVED → DISABLED (by WhatsApp or manually)

	wa_template_id is populated after approval with WhatsApp's own template ID.
	"""

	__allow_unmapped__ = True
	__tablename__ = "wa_template"
	__table_args__ = (
		Index("ix_wa_template_tenant_status", "tenant_id", "status"),
		Index("ix_wa_template_tenant_name", "tenant_id", "template_name"),
		UniqueConstraint("tenant_id", "template_name", name="uq_wa_template_tenant_name"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	template_name = Column(
		String(200),
		nullable=False,
		comment="WhatsApp template name — unique per tenant",
	)
	namespace = Column(
		String(200),
		nullable=True,
		comment="WhatsApp namespace (legacy BSPs); NULL for Cloud API",
	)
	language_code = Column(
		String(10),
		nullable=False,
		default="en",
		comment="BCP-47 language tag e.g. en, en_US, sw",
	)
	category = Column(
		String(30),
		nullable=False,
		comment="UTILITY | AUTHENTICATION | MARKETING",
	)
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | APPROVED | REJECTED | DISABLED",
	)
	components: list[dict[str, Any]] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="WhatsApp template component array (HEADER/BODY/FOOTER/BUTTONS)",
	)
	wa_template_id = Column(
		String(200),
		nullable=True,
		comment="WhatsApp's own template ID, populated after approval",
	)
	submitted_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="When template was submitted to WhatsApp for review",
	)
	approved_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="When WhatsApp approved the template",
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
	messages: list[WhatsAppMessage] = relationship(
		"WhatsAppMessage",
		back_populates="template",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<WhatsAppTemplate {self.template_name!r} "
			f"lang={self.language_code!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# WhatsAppMessage
# ---------------------------------------------------------------------------

class WhatsAppMessage(AuditMixin, Model):
	"""Individual WhatsApp message — outbound or inbound.

	Outbound messages start at QUEUED and are picked up by the delivery worker
	(see WhatsAppService.get_pending_outbound).  The worker sets wa_message_id
	and transitions to SENT; webhook callbacks drive DELIVERED/READ/FAILED.

	Inbound messages are created by process_inbound() with direction=INBOUND
	and status=DELIVERED (they arrived, so delivery is confirmed).

	linked_module / linked_record_id provide a polymorphic back-reference to
	the business record that triggered the message (e.g. workflow step, CRM
	campaign) without introducing circular FK dependencies.
	"""

	__allow_unmapped__ = True
	__tablename__ = "wa_message"
	__table_args__ = (
		Index("ix_wa_message_tenant_phone_sent", "tenant_id", "to_phone", "sent_at"),
		Index("ix_wa_message_wa_id", "wa_message_id"),
		Index("ix_wa_message_status_sent", "status", "sent_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	to_phone = Column(
		String(30),
		nullable=False,
		comment="E.164 destination phone number",
	)
	from_phone = Column(
		String(30),
		nullable=True,
		comment="E.164 source number (populated for INBOUND messages)",
	)
	direction = Column(
		String(10),
		nullable=False,
		comment="OUTBOUND | INBOUND",
	)
	message_type = Column(
		String(20),
		nullable=False,
		default="TEMPLATE",
		comment="TEMPLATE | TEXT | IMAGE | DOCUMENT | INTERACTIVE",
	)
	template_id = Column(
		UUID(as_uuid=False),
		ForeignKey("wa_template.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="FK to WhatsAppTemplate; NULL for TEXT/IMAGE/etc.",
	)
	template_params: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Variable substitution map for template components",
	)
	body = Column(
		Text,
		nullable=True,
		comment="Plain text body (TEXT messages) or media caption",
	)
	wa_message_id = Column(
		String(200),
		nullable=True,
		comment="WhatsApp's own message ID, set after successful API call",
	)
	status = Column(
		String(20),
		nullable=False,
		default="QUEUED",
		comment="QUEUED | SENT | DELIVERED | READ | FAILED",
	)
	sent_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="When the message was accepted by WhatsApp API",
	)
	delivered_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="When delivery was confirmed by WhatsApp webhook",
	)
	read_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="When read receipt was received via webhook",
	)
	error_code = Column(
		String(20),
		nullable=True,
		comment="WhatsApp API error code on FAILED status",
	)
	error_message = Column(
		Text,
		nullable=True,
		comment="Human-readable error from WhatsApp API",
	)
	linked_module = Column(
		String(100),
		nullable=True,
		comment="Source module e.g. 'workflow', 'crm.marketing'",
	)
	linked_record_id = Column(
		String(50),
		nullable=True,
		comment="UUID of the triggering record in linked_module",
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
	template: WhatsAppTemplate | None = relationship(
		"WhatsAppTemplate",
		back_populates="messages",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<WhatsAppMessage {self.id!r} dir={self.direction!r} "
			f"to={self.to_phone!r} type={self.message_type!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# WhatsAppConversation
# ---------------------------------------------------------------------------

class WhatsAppConversation(AuditMixin, Model):
	"""Aggregated conversation thread with a phone number.

	One row per (tenant_id, phone_number) pair.  Created on first contact
	(inbound or outbound) and updated on every subsequent message.

	status:
	  ACTIVE       — conversation is open; messages flowing
	  CLOSED       — manually closed by agent
	  BOT_HANDLED  — being handled by an automated bot flow

	tags: arbitrary JSONB list of strings for CRM/support categorisation.
	assigned_agent_id: soft FK to ab_user; NULL = unassigned / bot.
	contact_id: soft FK to CRM contact/party master (no DB FK to avoid dep).
	"""

	__allow_unmapped__ = True
	__tablename__ = "wa_conversation"
	__table_args__ = (
		UniqueConstraint("tenant_id", "phone_number", name="uq_wa_conversation_tenant_phone"),
		Index("ix_wa_conversation_tenant_status_last", "tenant_id", "status", "last_message_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	phone_number = Column(
		String(30),
		nullable=False,
		comment="E.164 phone number for this conversation",
	)
	contact_name = Column(
		String(200),
		nullable=True,
		comment="Display name — from WhatsApp profile or CRM lookup",
	)
	contact_id = Column(
		String(50),
		nullable=True,
		comment="Soft FK to CRM contact / erp_party.id",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | CLOSED | BOT_HANDLED",
	)
	last_message_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp of the most recent message in either direction",
	)
	message_count = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Running count of all messages in this conversation",
	)
	tags: list[str] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="Arbitrary label strings for filtering / routing",
	)
	notes = Column(
		Text,
		nullable=True,
		comment="Agent notes about this conversation",
	)
	assigned_agent_id = Column(
		String(50),
		nullable=True,
		comment="Soft FK to ab_user.id; NULL = unassigned",
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

	def __repr__(self) -> str:
		return (
			f"<WhatsAppConversation {self.phone_number!r} "
			f"status={self.status!r} msgs={self.message_count}>"
		)


# ---------------------------------------------------------------------------
# WhatsAppWebhookLog
# ---------------------------------------------------------------------------

class WhatsAppWebhookLog(AuditMixin, Model):
	"""Append-only log of raw webhook payloads received from WhatsApp / Meta.

	Every inbound webhook POST is persisted before processing so that:
	  - Failed processing can be retried from the log.
	  - Audit trail is maintained for compliance.
	  - Duplicate delivery (WhatsApp delivers at-least-once) can be detected.

	processed=False rows are available for reprocessing by a worker.
	error captures the exception message if processing failed.
	"""

	__allow_unmapped__ = True
	__tablename__ = "wa_webhook_log"
	__table_args__ = (
		Index("ix_wa_webhook_tenant_type_created", "tenant_id", "event_type", "created_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	event_type = Column(
		String(100),
		nullable=False,
		comment="Logical event type derived from payload e.g. messages.status, messages.inbound",
	)
	payload: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		comment="Full raw webhook payload from WhatsApp",
	)
	processed = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True once process_webhook() has handled this entry successfully",
	)
	error = Column(
		Text,
		nullable=True,
		comment="Exception message if processing failed; NULL on success",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<WhatsAppWebhookLog {self.id!r} type={self.event_type!r} "
			f"processed={self.processed}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"WhatsAppTemplate",
	"WhatsAppMessage",
	"WhatsAppConversation",
	"WhatsAppWebhookLog",
]
