"""
pgappforge/plugins/erp/platform/edi/events.py

EDI Framework domain events.

Events emitted:
  platform.edi.message.sent        — outbound EDI message dispatched to partner
  platform.edi.message.received    — inbound EDI message received and logged
  platform.edi.partner.registered  — trading partner onboarded
  platform.edi.parse.error         — EDI parse failed with raw preview
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class EDIMessageSentEvent(DomainEvent):
	event_type: str = "platform.edi.message.sent"
	message_id: str = ""
	partner_id: str = ""
	message_type: str = ""
	protocol: str = ""
	tenant_id: str = ""


@dataclass
class EDIMessageReceivedEvent(DomainEvent):
	event_type: str = "platform.edi.message.received"
	message_id: str = ""
	partner_id: str = ""
	message_type: str = ""
	status: str = ""


@dataclass
class EDIPartnerRegisteredEvent(DomainEvent):
	event_type: str = "platform.edi.partner.registered"
	partner_id: str = ""
	name: str = ""
	protocol: str = ""
	tenant_id: str = ""


@dataclass
class EDIParseErrorEvent(DomainEvent):
	event_type: str = "platform.edi.parse.error"
	message_id: str = ""
	error: str = ""
	raw_preview: str = ""


__all__ = [
	"EDIMessageSentEvent",
	"EDIMessageReceivedEvent",
	"EDIPartnerRegisteredEvent",
	"EDIParseErrorEvent",
]
