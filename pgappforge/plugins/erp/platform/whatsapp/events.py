"""
pgappforge/plugins/erp/platform/whatsapp/events.py

Domain events for the WhatsApp Business API integration plugin.

Events emitted:
  platform.whatsapp.message.sent        — outbound template message queued/sent
  platform.whatsapp.message.delivered   — delivery confirmation received via webhook
  platform.whatsapp.message.read        — read receipt received via webhook
  platform.whatsapp.inbound             — inbound message received from user
  platform.whatsapp.template.approved   — template approved by WhatsApp / Meta
  platform.whatsapp.conversation.started — new conversation initiated
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Outbound message events
# ---------------------------------------------------------------------------

@dataclass
class WhatsAppMessageSentEvent(DomainEvent):
	"""Emitted when an outbound template message record is created (QUEUED status).

	The actual HTTP delivery to WhatsApp Business API is handled separately
	by the delivery worker; this event signals the outbox record is ready.
	"""
	event_type: str = "platform.whatsapp.message.sent"
	message_id: str = ""          # WhatsAppMessage.id (internal UUID)
	to_phone: str = ""            # E.164 destination number
	template_name: str = ""       # WhatsAppTemplate.template_name
	tenant_id: str = ""           # overrides DomainEvent.tenant_id for clarity


@dataclass
class WhatsAppMessageDeliveredEvent(DomainEvent):
	"""Emitted when a delivery confirmation arrives via the WhatsApp webhook.

	delivered_at is an ISO-8601 UTC string — never a float timestamp.
	"""
	event_type: str = "platform.whatsapp.message.delivered"
	message_id: str = ""          # WhatsAppMessage.id (internal UUID)
	to_phone: str = ""
	delivered_at: str = ""        # ISO-8601 UTC string


@dataclass
class WhatsAppMessageReadEvent(DomainEvent):
	"""Emitted when a read receipt arrives via the WhatsApp webhook."""
	event_type: str = "platform.whatsapp.message.read"
	message_id: str = ""          # WhatsAppMessage.id (internal UUID)
	to_phone: str = ""
	read_at: str = ""             # ISO-8601 UTC string


# ---------------------------------------------------------------------------
# Inbound message event
# ---------------------------------------------------------------------------

@dataclass
class WhatsAppInboundMessageEvent(DomainEvent):
	"""Emitted when an inbound message is received from a user.

	Triggers conversation state update and optional bot/agent routing.
	"""
	event_type: str = "platform.whatsapp.inbound"
	from_phone: str = ""          # E.164 sender number
	body: str = ""                # Text body (or caption for media)
	message_id: str = ""          # WhatsAppMessage.id (internal UUID)
	tenant_id: str = ""           # overrides DomainEvent.tenant_id for clarity


# ---------------------------------------------------------------------------
# Template lifecycle event
# ---------------------------------------------------------------------------

@dataclass
class WhatsAppTemplateApprovedEvent(DomainEvent):
	"""Emitted when WhatsApp / Meta approves a message template.

	Triggers a status update on WhatsAppTemplate to APPROVED and enables
	the template for outbound use.
	"""
	event_type: str = "platform.whatsapp.template.approved"
	template_id: str = ""         # WhatsAppTemplate.id (internal UUID)
	template_name: str = ""
	tenant_id: str = ""           # overrides DomainEvent.tenant_id for clarity


# ---------------------------------------------------------------------------
# Conversation event
# ---------------------------------------------------------------------------

@dataclass
class WhatsAppConversationStartedEvent(DomainEvent):
	"""Emitted when a new WhatsAppConversation record is created.

	Fired on first inbound or outbound contact with a previously-unseen number.
	"""
	event_type: str = "platform.whatsapp.conversation.started"
	conversation_id: str = ""     # WhatsAppConversation.id (internal UUID)
	from_phone: str = ""          # E.164 phone number
	tenant_id: str = ""           # overrides DomainEvent.tenant_id for clarity


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"WhatsAppMessageSentEvent",
	"WhatsAppMessageDeliveredEvent",
	"WhatsAppMessageReadEvent",
	"WhatsAppInboundMessageEvent",
	"WhatsAppTemplateApprovedEvent",
	"WhatsAppConversationStartedEvent",
]
