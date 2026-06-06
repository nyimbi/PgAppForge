"""
pgappforge/plugins/erp/platform/documents/models.py

SQLAlchemy 2.x models for the Document Management System (DMS) plugin.

Table prefix: dms_

All models:
  - Use PostgreSQL-specific types (JSONB, UUID, DateTime with timezone)
  - Carry tenant_id for multi-tenancy
  - Mix in AuditMixin for automatic audit-trail logging
  - Use UUID4 string PKs with server_default fallback
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Text,
	UniqueConstraint,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"Document",
	"DocumentVersion",
	"DocumentFolder",
	"DocumentAccess",
]


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# DocumentFolder — declared before Document (FK target)
# ---------------------------------------------------------------------------

class DocumentFolder(AuditMixin, Model):
	"""Hierarchical folder tree for organising documents.

	Self-referential parent_id enables arbitrary nesting.
	path_string stores the materialised path (e.g. /root/hr/contracts)
	for efficient subtree queries without recursive CTEs on every read.
	"""

	__tablename__ = "dms_folder"
	__table_args__ = (
		Index("ix_dms_folder_tenant_parent", "tenant_id", "parent_id"),
		Index("ix_dms_folder_tenant_path", "tenant_id", "path_string"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	name = Column(VARCHAR(300), nullable=False)
	parent_id = Column(
		UUID(as_uuid=False),
		ForeignKey("dms_folder.id", ondelete="SET NULL"),
		nullable=True,
	)
	owner_id = Column(VARCHAR(50), nullable=True)

	# JSONB access policy — {"roles": {"HR_ADMIN": "EDIT"}, "users": {"u123": "VIEW"}}
	access_policy = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default=sa.text("'{}'::jsonb"),
	)

	# Materialised path string: /parent-id/child-id/... for subtree queries
	path_string = Column(Text, nullable=True)

	# Optional binding to an external entity (project, department, etc.)
	entity_id = Column(VARCHAR(50), nullable=True)

	# Relationships
	parent = relationship(
		"DocumentFolder",
		remote_side="DocumentFolder.id",
		back_populates="children",
		lazy="select",
	)
	children = relationship(
		"DocumentFolder",
		back_populates="parent",
		lazy="select",
	)
	documents = relationship(
		"Document",
		back_populates="folder",
		lazy="select",
	)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

class Document(AuditMixin, Model):
	"""Central document record.

	latest_version_id is a soft FK updated by the service whenever a new
	DocumentVersion is persisted — avoids a join in the common read path.

	search_vector is a PostgreSQL tsvector populated via to_tsvector() in
	DocumentService and kept current on every title/description change.
	The GIN index on it (and on tags) makes FTS and containment queries fast.
	"""

	__tablename__ = "dms_document"
	__table_args__ = (
		Index("ix_dms_doc_tenant_status", "tenant_id", "status"),
		Index("ix_dms_doc_owner_tenant", "owner_id", "tenant_id"),
		Index("ix_dms_doc_source", "source_module", "source_record_id"),
		# GIN indexes for PostgreSQL FTS and JSONB containment
		Index("ix_dms_doc_fts", "search_vector", postgresql_using="gin"),
		Index("ix_dms_doc_tags", "tags", postgresql_using="gin"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	title = Column(VARCHAR(500), nullable=False)
	description = Column(Text, nullable=True)

	folder_id = Column(
		UUID(as_uuid=False),
		ForeignKey("dms_folder.id", ondelete="SET NULL"),
		nullable=True,
	)
	owner_id = Column(VARCHAR(50), nullable=False)

	# ACTIVE / ARCHIVED / DELETED
	status = Column(VARCHAR(20), nullable=False, default="ACTIVE", server_default="ACTIVE")

	# CONTRACT / POLICY / INVOICE / REPORT / OTHER
	doc_type = Column(VARCHAR(50), nullable=True)

	tags = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default=sa.text("'[]'::jsonb"),
	)

	# Soft FK to dms_version.id — updated by service layer
	latest_version_id = Column(VARCHAR(50), nullable=True)

	# Cross-plugin attachment: which module + record owns this document
	source_module = Column(VARCHAR(100), nullable=True)
	source_record_id = Column(VARCHAR(50), nullable=True)

	# PostgreSQL tsvector for full-text search
	search_vector = Column(TSVECTOR, nullable=True)

	metadata_ = Column(
		"metadata_",
		JSONB,
		nullable=False,
		default=dict,
		server_default=sa.text("'{}'::jsonb"),
	)

	# Relationships
	folder = relationship("DocumentFolder", back_populates="documents", lazy="select")
	versions = relationship(
		"DocumentVersion",
		back_populates="document",
		lazy="select",
		order_by="DocumentVersion.version_number",
	)
	access_grants = relationship(
		"DocumentAccess",
		back_populates="document",
		lazy="select",
	)


# ---------------------------------------------------------------------------
# DocumentVersion
# ---------------------------------------------------------------------------

class DocumentVersion(AuditMixin, Model):
	"""Immutable snapshot of a document file at a point in time.

	is_current=True only on the latest version; the service marks previous
	versions False when a new version is uploaded.
	"""

	__tablename__ = "dms_version"
	__table_args__ = (
		UniqueConstraint(
			"document_id", "version_number",
			name="uq_dms_version_doc_num",
		),
		Index("ix_dms_version_doc_current", "document_id", "is_current"),
		Index("ix_dms_version_tenant_uploaded", "tenant_id", "uploaded_at"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	document_id = Column(
		UUID(as_uuid=False),
		ForeignKey("dms_document.id", ondelete="CASCADE"),
		nullable=False,
	)
	version_number = Column(Integer, nullable=False, default=1)
	filename = Column(VARCHAR(500), nullable=False)
	file_path = Column(Text, nullable=False)
	file_size_bytes = Column(Integer, nullable=True)
	mime_type = Column(VARCHAR(100), nullable=True)
	checksum_sha256 = Column(VARCHAR(64), nullable=True)
	uploaded_by = Column(VARCHAR(50), nullable=False)
	uploaded_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=sa.func.now(),
		server_default=sa.text("now()"),
	)
	change_summary = Column(Text, nullable=True)
	is_current = Column(
		Boolean,
		nullable=False,
		default=True,
		server_default=sa.text("true"),
	)

	metadata_ = Column(
		"metadata_",
		JSONB,
		nullable=False,
		default=dict,
		server_default=sa.text("'{}'::jsonb"),
	)

	document = relationship("Document", back_populates="versions", lazy="select")


# ---------------------------------------------------------------------------
# DocumentAccess
# ---------------------------------------------------------------------------

class DocumentAccess(AuditMixin, Model):
	"""Per-document ACL entry — grants a user or role a specific access level.

	expires_at=None means perpetual access.  The service layer checks this
	at read time and treats expired grants as non-existent (soft expiry).
	"""

	__tablename__ = "dms_access"
	__table_args__ = (
		UniqueConstraint(
			"document_id", "grantee_id", "grantee_type",
			name="uq_dms_access_doc_grantee",
		),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	document_id = Column(
		UUID(as_uuid=False),
		ForeignKey("dms_document.id", ondelete="CASCADE"),
		nullable=False,
	)
	grantee_id = Column(VARCHAR(50), nullable=False)
	# USER / ROLE
	grantee_type = Column(
		VARCHAR(20),
		nullable=False,
		default="USER",
		server_default="USER",
	)
	# VIEW / COMMENT / EDIT / ADMIN
	access_level = Column(
		VARCHAR(20),
		nullable=False,
		default="VIEW",
		server_default="VIEW",
	)
	granted_by = Column(VARCHAR(50), nullable=False)
	granted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=sa.func.now(),
		server_default=sa.text("now()"),
	)
	expires_at = Column(DateTime(timezone=True), nullable=True)

	document = relationship("Document", back_populates="access_grants", lazy="select")
