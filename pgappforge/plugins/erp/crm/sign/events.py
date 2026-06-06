"""
pgappforge/plugins/erp/crm/sign/events.py

Domain events for the E-Sign Portal plugin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class SignatureRequestCreatedEvent(DomainEvent):
	"""Emitted when a signature request is created and signatories are attached."""
	event_type: str = "crm.sign.request.created"
	request_id: str = ""
	document_id: str = ""
	initiator_id: str = ""
	signatories: list = field(default_factory=list)


@dataclass
class SignatureRequestSignedEvent(DomainEvent):
	"""Emitted when an individual signatory completes signing."""
	event_type: str = "crm.sign.signature.signed"
	signature_id: str = ""
	request_id: str = ""
	signer_id: str = ""
	signed_at: str = ""  # ISO datetime


@dataclass
class SignatureRequestCompletedEvent(DomainEvent):
	"""Emitted when all signatories have signed and the request is COMPLETED."""
	event_type: str = "crm.sign.request.completed"
	request_id: str = ""
	document_id: str = ""
	all_signed_at: str = ""  # ISO datetime


@dataclass
class SignatureRequestDeclinedEvent(DomainEvent):
	"""Emitted when a signatory declines to sign."""
	event_type: str = "crm.sign.signature.declined"
	request_id: str = ""
	signer_id: str = ""
	reason: str = ""


@dataclass
class SignatureRequestExpiredEvent(DomainEvent):
	"""Emitted when a signature request passes its expires_at without completion."""
	event_type: str = "crm.sign.request.expired"
	request_id: str = ""


__all__ = [
	"SignatureRequestCreatedEvent",
	"SignatureRequestSignedEvent",
	"SignatureRequestCompletedEvent",
	"SignatureRequestDeclinedEvent",
	"SignatureRequestExpiredEvent",
]
