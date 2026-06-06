"""
pgappforge/plugins/erp/platform/documents/events.py

Domain events for the Document Management System (DMS) plugin.

All events inherit from DomainEvent and carry a tenant_id for multi-tenancy.
emit_event() persists them atomically inside the caller's SQLAlchemy session.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"DocumentUploadedEvent",
	"DocumentVersionCreatedEvent",
	"DocumentTaggedEvent",
	"DocumentSharedEvent",
	"DocumentArchivedEvent",
	"DocumentSignatureRequestedEvent",
]


@dataclass
class DocumentUploadedEvent(DomainEvent):
	"""Emitted when a new document is uploaded for the first time.

	aggregate_id should be set to doc_id by the caller.
	aggregate_type is set to "Document".
	"""

	event_type: str = "platform.documents.uploaded"
	aggregate_type: str = "Document"

	doc_id: str = ""
	filename: str = ""
	mime_type: str = ""
	uploader_id: str = ""
	# tenant_id inherited from DomainEvent


@dataclass
class DocumentVersionCreatedEvent(DomainEvent):
	"""Emitted when a new version is uploaded against an existing document."""

	event_type: str = "platform.documents.version_created"
	aggregate_type: str = "Document"

	doc_id: str = ""
	version_id: str = ""
	version_number: int = 0
	uploader_id: str = ""


@dataclass
class DocumentTaggedEvent(DomainEvent):
	"""Emitted when the tag set on a document is updated."""

	event_type: str = "platform.documents.tagged"
	aggregate_type: str = "Document"

	doc_id: str = ""
	tags: list = field(default_factory=list)


@dataclass
class DocumentSharedEvent(DomainEvent):
	"""Emitted when document access is granted to one or more grantees."""

	event_type: str = "platform.documents.shared"
	aggregate_type: str = "Document"

	doc_id: str = ""
	shared_with_ids: list = field(default_factory=list)
	access_level: str = "VIEW"


@dataclass
class DocumentArchivedEvent(DomainEvent):
	"""Emitted when a document is moved to ARCHIVED status."""

	event_type: str = "platform.documents.archived"
	aggregate_type: str = "Document"

	doc_id: str = ""
	archived_by: str = ""


@dataclass
class DocumentSignatureRequestedEvent(DomainEvent):
	"""Emitted when an e-signature request is raised for a document."""

	event_type: str = "platform.documents.signature.requested"
	aggregate_type: str = "Document"

	doc_id: str = ""
	request_id: str = ""
	signatories: list = field(default_factory=list)
