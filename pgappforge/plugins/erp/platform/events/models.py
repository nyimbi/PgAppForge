"""
pgappforge/plugins/erp/platform/events/models.py

Platform Event Bus models — durable subscription registry and delivery log.

Design notes:
  - EventSubscription: per-plugin handler registration, persistent across restarts.
  - EventDeliveryLog: immutable delivery audit trail (append-only, NEVER UPDATE).
  - All PKs: UUID v4 via gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - tenant_id on all mutable rows
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

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# EventSubscription
# ---------------------------------------------------------------------------

class EventSubscription(AuditMixin, Model):
	"""Persistent event handler registration.

	Tracks which plugin subscribed to which event type, the handler function
	path (dotted import string), retry policy, and dead-letter threshold.

	is_active=False disables delivery without removing the row, enabling
	replay after re-activation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_event_subscription"
	__table_args__ = (
		UniqueConstraint(
			"subscriber_plugin", "event_type",
			name="uq_erp_evtsub_plugin_type",
		),
		Index("ix_erp_evtsub_event_type", "event_type"),
		Index("ix_erp_evtsub_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=True, index=True,
	                   comment="NULL = system-wide subscription")

	# Subscription identity
	subscriber_plugin = Column(
		String(200),
		nullable=False,
		comment="Plugin name e.g. 'finance.gl'",
	)
	event_type = Column(
		String(200),
		nullable=False,
		comment="Event type string e.g. 'invoice.paid'",
	)
	handler_function = Column(
		String(500),
		nullable=False,
		comment="Dotted import path to the handler callable",
	)

	# Policy
	is_active = Column(Boolean, nullable=False, default=True)
	retry_count = Column(
		Integer,
		nullable=False,
		default=3,
		comment="Max delivery attempts before dead-lettering",
	)
	dead_letter_after = Column(
		Integer,
		nullable=False,
		default=5,
		comment="Total failures before marking DEAD_LETTER",
	)

	# Metadata
	description = Column(Text, nullable=True)
	filter_conditions: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Optional JSONLogic filter applied before delivery",
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
			f"<EventSubscription {self.subscriber_plugin!r}"
			f" on={self.event_type!r} active={self.is_active}>"
		)


# ---------------------------------------------------------------------------
# EventDeliveryLog  (append-only — NEVER UPDATE)
# ---------------------------------------------------------------------------

class EventDeliveryLog(Model):
	"""Immutable record of each delivery attempt for a subscription.

	One row per attempt.  Final state is one of:
	  DELIVERED — handler completed without exception.
	  FAILED    — handler raised; retry_count not yet exhausted.
	  DEAD_LETTER — retry budget exhausted; needs manual intervention.

	CRITICAL: NEVER UPDATE rows.  Use subscription.is_active = False to pause.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_event_delivery_log"
	__table_args__ = (
		Index("ix_erp_evtdlv_subscription", "subscription_id"),
		Index("ix_erp_evtdlv_event_id", "event_id"),
		Index("ix_erp_evtdlv_status", "status"),
		Index("ix_erp_evtdlv_delivered_at", "delivered_at",
		      postgresql_using="brin"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)

	event_id = Column(
		String(36),
		nullable=False,
		comment="DomainEvent.event_id (logical FK to erp_domain_event_log.event_id)",
	)
	subscription_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_event_subscription.id", ondelete="CASCADE"),
		nullable=False,
	)
	delivery_attempt = Column(
		Integer,
		nullable=False,
		default=1,
		comment="1-based attempt number",
	)
	delivered_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	status = Column(
		String(20),
		nullable=False,
		comment="DELIVERED | FAILED | DEAD_LETTER",
	)
	error_message = Column(Text, nullable=True)
	response_code = Column(
		Integer,
		nullable=True,
		comment="HTTP response code for webhook deliveries; NULL for in-process",
	)

	def __repr__(self) -> str:
		return (
			f"<EventDeliveryLog event={self.event_id!r}"
			f" sub={self.subscription_id!r} attempt={self.delivery_attempt}"
			f" status={self.status!r}>"
		)


__all__ = [
	"EventSubscription",
	"EventDeliveryLog",
]
