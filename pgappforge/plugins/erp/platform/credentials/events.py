"""
pgappforge/plugins/erp/platform/credentials/events.py

Digital Credentials plugin domain events.

Events emitted:
  credentials.schema.published
  credentials.credential.issued
  credentials.credential.revoked
  credentials.credential.verified
  credentials.credential.shared
  credentials.bulk_issue.completed
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class CredentialSchemaPublishedEvent(DomainEvent):
	event_type: str = "credentials.schema.published"
	schema_id: str = ""
	credential_type: str = ""
	issuer_id: str = ""
	name: str = ""


@dataclass
class CredentialIssuedEvent(DomainEvent):
	event_type: str = "credentials.credential.issued"
	credential_id: str = ""
	credential_number: str = ""
	schema_id: str = ""
	recipient_id: str = ""
	recipient_email: str = ""
	verification_url: str = ""


@dataclass
class CredentialRevokedEvent(DomainEvent):
	event_type: str = "credentials.credential.revoked"
	credential_id: str = ""
	credential_number: str = ""
	recipient_id: str = ""
	revocation_reason: str = ""


@dataclass
class CredentialVerifiedEvent(DomainEvent):
	event_type: str = "credentials.credential.verified"
	credential_id: str = ""
	verification_id: str = ""
	result: str = ""
	verifier_email: str = ""


@dataclass
class CredentialSharedEvent(DomainEvent):
	event_type: str = "credentials.credential.shared"
	credential_id: str = ""
	share_id: str = ""
	platform: str = ""
	recipient_email: str = ""


@dataclass
class BulkIssueCompletedEvent(DomainEvent):
	event_type: str = "credentials.bulk_issue.completed"
	schema_id: str = ""
	issued_count: int = 0
	failed_count: int = 0
	failed_emails: list = field(default_factory=list)


__all__ = [
	"CredentialSchemaPublishedEvent",
	"CredentialIssuedEvent",
	"CredentialRevokedEvent",
	"CredentialVerifiedEvent",
	"CredentialSharedEvent",
	"BulkIssueCompletedEvent",
]
