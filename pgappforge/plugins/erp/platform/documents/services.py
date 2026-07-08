"""
pgappforge/plugins/erp/platform/documents/services.py

Business logic for the Document Management System (DMS) plugin.

All methods accept an explicit SQLAlchemy Session so they participate in the
caller's unit of work — no hidden commits, no hidden sessions.

Cross-plugin attachment is first-class: attach_to_record() binds a document
to any module's record by (source_module, source_record_id).

BPM actions registered here:
  platform.documents.attach         — attach document to workflow record
  platform.documents.request_signature — request e-signature on document
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.events import emit_event
from pgappforge.plugins.erp.platform.documents.events import (
	DocumentArchivedEvent,
	DocumentSharedEvent,
	DocumentUploadedEvent,
	DocumentVersionCreatedEvent,
)
from pgappforge.plugins.erp.platform.documents.models import (
	Document,
	DocumentAccess,
	DocumentFolder,
	DocumentVersion,
)
from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)

_ACCESS_LEVELS = {"VIEW", "COMMENT", "EDIT", "ADMIN"}
_VISIBLE_ACCESS_LEVELS = {"VIEW", "COMMENT", "EDIT", "ADMIN"}
_WRITE_ACCESS_LEVELS = {"EDIT", "ADMIN"}
_ADMIN_ACCESS_LEVELS = {"ADMIN"}
_GRANTEE_TYPES = {"USER", "ROLE"}
_CHECKSUM_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SAFE_MODULE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")

__all__ = [
	"DocumentService",
	"DocumentServiceError",
	"DocumentValidationError",
	"DocumentNotFoundError",
	"DocumentAccessError",
	"DocumentStateError",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DocumentServiceError(Exception):
	"""Base exception for all DMS service errors."""


class DocumentValidationError(DocumentServiceError):
	"""Raised when caller supplied data violates the DMS service contract."""


class DocumentNotFoundError(DocumentServiceError):
	"""Raised when a requested document does not exist or is deleted."""


class DocumentAccessError(DocumentServiceError):
	"""Raised when the requestor lacks the required access level."""


class DocumentStateError(DocumentServiceError):
	"""Raised when a requested mutation is not valid for document state."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class DocumentService:
	"""Stateless service — instantiate once; all state lives in the session."""

	# ------------------------------------------------------------------
	# Upload
	# ------------------------------------------------------------------

	def upload_document(
		self,
		title: str,
		filename: str,
		file_path: str,
		owner_id: str,
		tenant_id: str,
		session: Session,
		*,
		description: str | None = None,
		folder_id: str | None = None,
		doc_type: str | None = None,
		tags: list | None = None,
		source_module: str | None = None,
		source_record_id: str | None = None,
		mime_type: str | None = None,
		file_size_bytes: int | None = None,
	) -> Document:
		"""Create a Document and its first DocumentVersion atomically.

		The search_vector is populated via plainto_tsquery so it is immediately
		queryable within the same transaction.

		Returns the persisted Document with latest_version_id set.
		"""
		title = self._require_text(title, "title", max_length=500)
		filename = self._require_text(filename, "filename", max_length=500)
		file_path = self._require_text(file_path, "file_path", max_length=2000)
		owner_id = self._require_text(owner_id, "owner_id", max_length=50)
		tenant_id = self._require_text(tenant_id, "tenant_id", max_length=36)
		description = self._optional_text(description, "description", max_length=10000)
		folder_id = self._optional_text(folder_id, "folder_id", max_length=36)
		doc_type = self._optional_text(doc_type, "doc_type", max_length=50, uppercase=True)
		tags = self._normalize_tags(tags)
		source_module = self._normalize_source_module(source_module)
		source_record_id = self._optional_text(source_record_id, "source_record_id", max_length=50)
		mime_type = self._normalize_mime_type(mime_type)
		file_size_bytes = self._normalize_file_size(file_size_bytes)
		if folder_id is not None:
			self._require_folder(folder_id, tenant_id, session)

		doc = Document(
			title=title,
			description=description,
			folder_id=folder_id,
			owner_id=owner_id,
			tenant_id=tenant_id,
			status="ACTIVE",
			doc_type=doc_type,
			tags=tags,
			source_module=source_module,
			source_record_id=source_record_id,
		)
		session.add(doc)
		session.flush()  # get doc.id

		version = DocumentVersion(
			document_id=doc.id,
			tenant_id=tenant_id,
			version_number=1,
			filename=filename,
			file_path=file_path,
			file_size_bytes=file_size_bytes,
			mime_type=mime_type,
			uploaded_by=owner_id,
			is_current=True,
		)
		session.add(version)
		session.flush()  # get version.id

		doc.latest_version_id = version.id

		# Update PostgreSQL full-text search vector
		self._update_search_vector(doc, session)

		session.flush()

		emit_event(
			DocumentUploadedEvent(
				aggregate_id=doc.id,
				tenant_id=tenant_id,
				doc_id=doc.id,
				filename=filename,
				mime_type=mime_type or "",
				uploader_id=owner_id,
			),
			session,
		)

		log.info("DMS: uploaded document %r (%s) for tenant %s", title, doc.id, tenant_id)
		return doc

	# ------------------------------------------------------------------
	# New version
	# ------------------------------------------------------------------

	def upload_new_version(
		self,
		document_id: str,
		filename: str,
		file_path: str,
		uploader_id: str,
		session: Session,
		*,
		change_summary: str | None = None,
		mime_type: str | None = None,
		file_size_bytes: int | None = None,
		checksum_sha256: str | None = None,
		tenant_id: str | None = None,
		uploader_role_ids: list[str] | None = None,
	) -> DocumentVersion:
		"""Upload a new version of an existing document.

		Marks all existing versions as is_current=False, creates the new
		version with version_number = max(existing) + 1, and updates
		document.latest_version_id and search_vector.
		"""
		document_id = self._require_text(document_id, "document_id", max_length=36)
		filename = self._require_text(filename, "filename", max_length=500)
		file_path = self._require_text(file_path, "file_path", max_length=2000)
		uploader_id = self._require_text(uploader_id, "uploader_id", max_length=50)
		change_summary = self._optional_text(
			change_summary, "change_summary", max_length=5000
		)
		mime_type = self._normalize_mime_type(mime_type)
		file_size_bytes = self._normalize_file_size(file_size_bytes)
		checksum_sha256 = self._normalize_checksum(checksum_sha256)
		tenant_id = self._optional_text(tenant_id, "tenant_id", max_length=36)
		uploader_role_ids = self._normalize_role_ids(uploader_role_ids)

		doc = self._get_existing_document(document_id, session, tenant_id=tenant_id)
		self._require_active_document(doc)
		if not self._has_required_access(
			doc,
			uploader_id,
			session,
			_WRITE_ACCESS_LEVELS,
			role_ids=uploader_role_ids,
		):
			raise DocumentAccessError(
				f"User {uploader_id!r} cannot upload a new version of document {document_id!r}"
			)

		# Mark all current versions as not current
		session.execute(
			sa.update(DocumentVersion)
			.where(DocumentVersion.document_id == document_id)
			.where(DocumentVersion.is_current.is_(True))
			.values(is_current=False)
		)

		# Determine next version number
		max_num_row = session.execute(
			sa.select(sa.func.max(DocumentVersion.version_number))
			.where(DocumentVersion.document_id == document_id)
		).scalar()
		next_num = (max_num_row or 0) + 1

		version = DocumentVersion(
			document_id=document_id,
			tenant_id=doc.tenant_id,
			version_number=next_num,
			filename=filename,
			file_path=file_path,
			file_size_bytes=file_size_bytes,
			mime_type=mime_type,
			checksum_sha256=checksum_sha256,
			uploaded_by=uploader_id,
			is_current=True,
			change_summary=change_summary,
		)
		session.add(version)
		session.flush()

		doc.latest_version_id = version.id
		self._update_search_vector(doc, session)
		session.flush()

		emit_event(
			DocumentVersionCreatedEvent(
				aggregate_id=document_id,
				tenant_id=doc.tenant_id,
				doc_id=document_id,
				version_id=version.id,
				version_number=next_num,
				uploader_id=uploader_id,
			),
			session,
		)

		log.info(
			"DMS: new version v%d for document %s by %s",
			next_num, document_id, uploader_id,
		)
		return version

	# ------------------------------------------------------------------
	# Read
	# ------------------------------------------------------------------

	def get_document(
		self,
		document_id: str,
		requestor_id: str,
		tenant_id: str,
		session: Session,
		*,
		role_ids: list[str] | None = None,
	) -> Document:
		"""Return a Document if the requestor has access, else raise.

		Access is granted when any of:
		  1. requestor_id == document.owner_id
		  2. A non-expired DocumentAccess row exists for the requestor
		  3. A non-expired DocumentAccess row exists for any ROLE the
		     service cannot resolve here — callers can pre-check role grants
		     by passing a synthesised grantee_id for the role.

		Raises DocumentNotFoundError for missing/deleted docs.
		Raises DocumentAccessError when access is denied.
		"""
		document_id = self._require_text(document_id, "document_id", max_length=36)
		requestor_id = self._require_text(requestor_id, "requestor_id", max_length=50)
		tenant_id = self._require_text(tenant_id, "tenant_id", max_length=36)
		role_ids = self._normalize_role_ids(role_ids)

		doc = session.execute(
			sa.select(Document)
			.where(Document.id == document_id)
			.where(Document.tenant_id == tenant_id)
		).scalar_one_or_none()

		if doc is None or doc.status == "DELETED":
			raise DocumentNotFoundError(f"Document {document_id!r} not found")

		if not self._has_required_access(
			doc,
			requestor_id,
			session,
			_VISIBLE_ACCESS_LEVELS,
			role_ids=role_ids,
		):
			raise DocumentAccessError(
				f"User {requestor_id!r} does not have access to document {document_id!r}"
			)

		return doc

	# ------------------------------------------------------------------
	# Search
	# ------------------------------------------------------------------

	def search_documents(
		self,
		query: str,
		tenant_id: str,
		session: Session,
		*,
		doc_type: str | None = None,
		tags: list | None = None,
		owner_id: str | None = None,
		limit: int = 50,
		requestor_id: str | None = None,
		role_ids: list[str] | None = None,
	) -> list[Document]:
		"""Full-text search over documents using PostgreSQL tsvector/tsquery.

		Additional filters for doc_type, JSONB tag containment, and owner_id
		are applied as AND conditions.  Results are ranked by ts_rank_cd
		descending so the most relevant documents appear first.
		"""
		tenant_id = self._require_text(tenant_id, "tenant_id", max_length=36)
		query = self._require_text(query, "query", max_length=500)
		doc_type = self._optional_text(doc_type, "doc_type", max_length=50, uppercase=True)
		tags = self._normalize_tags(tags) if tags is not None else None
		owner_id = self._optional_text(owner_id, "owner_id", max_length=50)
		limit = self._normalize_limit(limit)
		requestor_id = self._optional_text(requestor_id, "requestor_id", max_length=50)
		role_ids = self._normalize_role_ids(role_ids)

		tsquery_expr = sa.func.plainto_tsquery("english", query)

		stmt = (
			sa.select(Document)
			.where(Document.tenant_id == tenant_id)
			.where(Document.status != "DELETED")
			.where(Document.search_vector.op("@@")(tsquery_expr))
		)

		if doc_type is not None:
			stmt = stmt.where(Document.doc_type == doc_type)

		if tags:
			# JSONB containment: document.tags @> '["tag1","tag2"]'::jsonb
			import json
			stmt = stmt.where(
				Document.tags.op("@>")(sa.cast(json.dumps(tags), JSONB))
			)

		if owner_id is not None:
			stmt = stmt.where(Document.owner_id == owner_id)

		if requestor_id is not None:
			stmt = stmt.where(
				sa.or_(
					Document.owner_id == requestor_id,
					self._access_exists_clause(
						Document.id,
						tenant_id,
						requestor_id,
						role_ids,
						_VISIBLE_ACCESS_LEVELS,
					),
				)
			)

		# Order by FTS rank descending
		rank_expr = sa.func.ts_rank_cd(Document.search_vector, tsquery_expr)
		stmt = stmt.order_by(rank_expr.desc()).limit(limit)

		return list(session.execute(stmt).scalars().all())

	# ------------------------------------------------------------------
	# Access management
	# ------------------------------------------------------------------

	def grant_access(
		self,
		document_id: str,
		grantee_id: str,
		grantee_type: str,
		access_level: str,
		granted_by: str,
		session: Session,
		*,
		expires_at: datetime | None = None,
		tenant_id: str | None = None,
		grantor_role_ids: list[str] | None = None,
	) -> DocumentAccess:
		"""Upsert a DocumentAccess row, then emit DocumentSharedEvent.

		If a row already exists for (document_id, grantee_id, grantee_type)
		it is updated in place (access_level, expires_at).
		"""
		document_id = self._require_text(document_id, "document_id", max_length=36)
		grantee_id = self._require_text(grantee_id, "grantee_id", max_length=50)
		grantee_type = self._normalize_choice(
			grantee_type, "grantee_type", _GRANTEE_TYPES
		)
		access_level = self._normalize_choice(
			access_level, "access_level", _ACCESS_LEVELS
		)
		granted_by = self._require_text(granted_by, "granted_by", max_length=50)
		expires_at = self._normalize_expiry(expires_at)
		tenant_id = self._optional_text(tenant_id, "tenant_id", max_length=36)
		grantor_role_ids = self._normalize_role_ids(grantor_role_ids)

		doc = self._get_existing_document(document_id, session, tenant_id=tenant_id)
		if not self._has_required_access(
			doc,
			granted_by,
			session,
			_ADMIN_ACCESS_LEVELS,
			role_ids=grantor_role_ids,
		):
			raise DocumentAccessError(
				f"User {granted_by!r} cannot manage access for document {document_id!r}"
			)

		existing = session.execute(
			sa.select(DocumentAccess)
			.where(DocumentAccess.document_id == document_id)
			.where(DocumentAccess.grantee_id == grantee_id)
			.where(DocumentAccess.grantee_type == grantee_type)
		).scalar_one_or_none()

		if existing is not None:
			existing.access_level = access_level
			existing.expires_at = expires_at
			existing.granted_by = granted_by
			existing.granted_at = datetime.now(timezone.utc)
			grant = existing
		else:
			grant = DocumentAccess(
				document_id=document_id,
				tenant_id=doc.tenant_id,
				grantee_id=grantee_id,
				grantee_type=grantee_type,
				access_level=access_level,
				granted_by=granted_by,
				expires_at=expires_at,
			)
			session.add(grant)

		session.flush()

		emit_event(
			DocumentSharedEvent(
				aggregate_id=document_id,
				tenant_id=doc.tenant_id,
				doc_id=document_id,
				shared_with_ids=[grantee_id],
				access_level=access_level,
			),
			session,
		)

		return grant

	# ------------------------------------------------------------------
	# Archive
	# ------------------------------------------------------------------

	def archive_document(
		self,
		document_id: str,
		archived_by: str,
		session: Session,
		*,
		tenant_id: str | None = None,
		actor_role_ids: list[str] | None = None,
	) -> Document:
		"""Set document.status = ARCHIVED and emit DocumentArchivedEvent."""
		document_id = self._require_text(document_id, "document_id", max_length=36)
		archived_by = self._require_text(archived_by, "archived_by", max_length=50)
		tenant_id = self._optional_text(tenant_id, "tenant_id", max_length=36)
		actor_role_ids = self._normalize_role_ids(actor_role_ids)

		doc = self._get_existing_document(document_id, session, tenant_id=tenant_id)
		if not self._has_required_access(
			doc,
			archived_by,
			session,
			_ADMIN_ACCESS_LEVELS,
			role_ids=actor_role_ids,
		):
			raise DocumentAccessError(
				f"User {archived_by!r} cannot archive document {document_id!r}"
			)

		doc.status = "ARCHIVED"
		session.flush()

		emit_event(
			DocumentArchivedEvent(
				aggregate_id=document_id,
				tenant_id=doc.tenant_id,
				doc_id=document_id,
				archived_by=archived_by,
			),
			session,
		)

		log.info("DMS: archived document %s by %s", document_id, archived_by)
		return doc

	# ------------------------------------------------------------------
	# Cross-plugin attachment
	# ------------------------------------------------------------------

	def attach_to_record(
		self,
		document_id: str,
		source_module: str,
		source_record_id: str,
		session: Session,
		*,
		tenant_id: str | None = None,
		attached_by: str | None = None,
		actor_role_ids: list[str] | None = None,
	) -> Document:
		"""Bind a document to a record in another module.

		Sets (source_module, source_record_id) on the Document.
		Multiple documents can reference the same record; this is a many-to-one
		relationship from the document side.
		"""
		document_id = self._require_text(document_id, "document_id", max_length=36)
		source_module = self._normalize_source_module(source_module)
		if source_module is None:
			raise DocumentValidationError("source_module must be non-empty")
		source_record_id = self._require_text(
			source_record_id, "source_record_id", max_length=50
		)
		tenant_id = self._optional_text(tenant_id, "tenant_id", max_length=36)
		attached_by = self._optional_text(attached_by, "attached_by", max_length=50)
		actor_role_ids = self._normalize_role_ids(actor_role_ids)

		doc = self._get_existing_document(document_id, session, tenant_id=tenant_id)
		self._require_active_document(doc)
		if attached_by is not None and not self._has_required_access(
			doc,
			attached_by,
			session,
			_WRITE_ACCESS_LEVELS,
			role_ids=actor_role_ids,
		):
			raise DocumentAccessError(
				f"User {attached_by!r} cannot attach document {document_id!r}"
			)

		doc.source_module = source_module
		doc.source_record_id = source_record_id
		session.flush()

		log.info(
			"DMS: attached document %s to %s:%s",
			document_id, source_module, source_record_id,
		)
		return doc

	# ------------------------------------------------------------------
	# Folder tree
	# ------------------------------------------------------------------

	def get_folder_tree(
		self,
		tenant_id: str,
		session: Session,
		*,
		entity_id: str | None = None,
		max_depth: int = 50,
	) -> list[dict]:
		"""Return the complete folder hierarchy for a tenant as a list of dicts.

		Uses a recursive CTE (WITH RECURSIVE) for correctness across arbitrary
		depth.  The result is a flat list; callers build the tree structure from
		the parent_id references if needed.

		Each dict contains: id, name, parent_id, path_string, entity_id, depth.
		"""
		tenant_id = self._require_text(tenant_id, "tenant_id", max_length=36)
		entity_id = self._optional_text(entity_id, "entity_id", max_length=50)
		max_depth = self._normalize_limit(max_depth, field_name="max_depth", maximum=100)

		# Anchor: top-level folders (no parent)
		anchor = (
			sa.select(
				DocumentFolder.id,
				DocumentFolder.name,
				DocumentFolder.parent_id,
				DocumentFolder.path_string,
				DocumentFolder.entity_id,
				sa.literal(0).label("depth"),
			)
			.where(DocumentFolder.tenant_id == tenant_id)
			.where(DocumentFolder.parent_id.is_(None))
		)
		if entity_id is not None:
			anchor = anchor.where(DocumentFolder.entity_id == entity_id)

		anchor_cte = anchor.cte(name="folder_tree", recursive=True)

		# Recursive member
		child = sa.select(
			DocumentFolder.id,
			DocumentFolder.name,
			DocumentFolder.parent_id,
			DocumentFolder.path_string,
			DocumentFolder.entity_id,
			(anchor_cte.c.depth + 1).label("depth"),
		).join(anchor_cte, DocumentFolder.parent_id == anchor_cte.c.id).where(
			DocumentFolder.tenant_id == tenant_id,
			anchor_cte.c.depth < max_depth,
		)

		full_cte = anchor_cte.union_all(child)
		rows = session.execute(sa.select(full_cte).order_by(full_cte.c.depth)).all()

		return [
			{
				"id": row.id,
				"name": row.name,
				"parent_id": row.parent_id,
				"path_string": row.path_string,
				"entity_id": row.entity_id,
				"depth": row.depth,
			}
			for row in rows
		]

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _get_existing_document(
		self,
		document_id: str,
		session: Session,
		*,
		tenant_id: str | None = None,
	) -> Document:
		stmt = sa.select(Document).where(Document.id == document_id)
		if tenant_id is not None:
			stmt = stmt.where(Document.tenant_id == tenant_id)
		doc = session.execute(stmt).scalar_one_or_none()
		if doc is None or doc.status == "DELETED":
			raise DocumentNotFoundError(f"Document {document_id!r} not found")
		return doc

	def _require_active_document(self, doc: Document) -> None:
		if doc.status == "DELETED":
			raise DocumentNotFoundError(f"Document {doc.id!r} not found")
		if doc.status != "ACTIVE":
			raise DocumentStateError(
				f"Document {doc.id!r} is {doc.status}; only ACTIVE documents can be mutated"
			)

	def _require_folder(
		self,
		folder_id: str,
		tenant_id: str,
		session: Session,
	) -> DocumentFolder:
		folder = session.execute(
			sa.select(DocumentFolder).where(
				DocumentFolder.id == folder_id,
				DocumentFolder.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if folder is None:
			raise DocumentNotFoundError(
				f"Folder {folder_id!r} not found for tenant {tenant_id!r}"
			)
		return folder

	def _has_required_access(
		self,
		doc: Document,
		actor_id: str,
		session: Session,
		allowed_levels: set[str],
		*,
		role_ids: list[str] | None = None,
	) -> bool:
		if doc.owner_id == actor_id:
			return True

		role_ids = self._normalize_role_ids(role_ids)
		grant = session.execute(
			sa.select(DocumentAccess.id)
			.where(
				DocumentAccess.document_id == doc.id,
				DocumentAccess.tenant_id == doc.tenant_id,
				DocumentAccess.access_level.in_(allowed_levels),
				self._active_grant_clause(),
				sa.or_(
					sa.and_(
						DocumentAccess.grantee_type == "USER",
						DocumentAccess.grantee_id == actor_id,
					),
					sa.and_(
						DocumentAccess.grantee_type == "ROLE",
						DocumentAccess.grantee_id.in_(role_ids),
					) if role_ids else sa.false(),
				),
			)
			.limit(1)
		).first()
		return grant is not None

	def _access_exists_clause(
		self,
		document_id_expr: Any,
		tenant_id: str,
		requestor_id: str,
		role_ids: list[str],
		allowed_levels: set[str],
	) -> Any:
		grantee_clause = sa.or_(
			sa.and_(
				DocumentAccess.grantee_type == "USER",
				DocumentAccess.grantee_id == requestor_id,
			),
			sa.and_(
				DocumentAccess.grantee_type == "ROLE",
				DocumentAccess.grantee_id.in_(role_ids),
			) if role_ids else sa.false(),
		)
		return (
			sa.select(DocumentAccess.id)
			.where(
				DocumentAccess.document_id == document_id_expr,
				DocumentAccess.tenant_id == tenant_id,
				DocumentAccess.access_level.in_(allowed_levels),
				self._active_grant_clause(),
				grantee_clause,
			)
			.exists()
		)

	@staticmethod
	def _active_grant_clause() -> Any:
		now = datetime.now(timezone.utc)
		return sa.or_(DocumentAccess.expires_at.is_(None), DocumentAccess.expires_at > now)

	@staticmethod
	def _require_text(
		value: str,
		field_name: str,
		*,
		max_length: int,
		uppercase: bool = False,
	) -> str:
		if not isinstance(value, str):
			raise DocumentValidationError(f"{field_name} must be a string")
		text = value.strip()
		if not text:
			raise DocumentValidationError(f"{field_name} must be non-empty")
		if len(text) > max_length:
			raise DocumentValidationError(
				f"{field_name} must be {max_length} characters or fewer"
			)
		if _CONTROL_CHARS_RE.search(text):
			raise DocumentValidationError(f"{field_name} contains control characters")
		return text.upper() if uppercase else text

	def _optional_text(
		self,
		value: str | None,
		field_name: str,
		*,
		max_length: int,
		uppercase: bool = False,
	) -> str | None:
		if value is None:
			return None
		text = self._require_text(
			value, field_name, max_length=max_length, uppercase=uppercase
		)
		return text or None

	def _normalize_choice(self, value: str, field_name: str, choices: set[str]) -> str:
		text = self._require_text(value, field_name, max_length=20, uppercase=True)
		if text not in choices:
			allowed = ", ".join(sorted(choices))
			raise DocumentValidationError(f"{field_name} must be one of: {allowed}")
		return text

	def _normalize_tags(self, tags: list | None) -> list[str]:
		if tags is None:
			return []
		if not isinstance(tags, list):
			raise DocumentValidationError("tags must be a list of strings")
		if len(tags) > 50:
			raise DocumentValidationError("tags cannot contain more than 50 entries")
		normalized: list[str] = []
		seen: set[str] = set()
		for index, tag in enumerate(tags):
			text = self._require_text(
				tag, f"tags[{index}]", max_length=80
			)
			key = text.casefold()
			if key not in seen:
				normalized.append(text)
				seen.add(key)
		return normalized

	def _normalize_role_ids(self, role_ids: list[str] | None) -> list[str]:
		if role_ids is None:
			return []
		if not isinstance(role_ids, (list, tuple, set)):
			raise DocumentValidationError("role_ids must be a list of strings")
		normalized: list[str] = []
		seen: set[str] = set()
		for index, role_id in enumerate(role_ids):
			text = self._require_text(role_id, f"role_ids[{index}]", max_length=50)
			if text not in seen:
				normalized.append(text)
				seen.add(text)
		return normalized

	def _normalize_source_module(self, value: str | None) -> str | None:
		text = self._optional_text(value, "source_module", max_length=100)
		if text is None:
			return None
		if not _SAFE_MODULE_RE.fullmatch(text):
			raise DocumentValidationError(
				"source_module may contain only letters, digits, '.', '_', ':', and '-'"
			)
		return text

	def _normalize_mime_type(self, value: str | None) -> str | None:
		text = self._optional_text(value, "mime_type", max_length=100)
		if text is None:
			return None
		if "/" not in text or text.startswith("/") or text.endswith("/"):
			raise DocumentValidationError("mime_type must be a valid type/subtype value")
		return text.lower()

	@staticmethod
	def _normalize_file_size(value: int | None) -> int | None:
		if value is None:
			return None
		if isinstance(value, bool) or not isinstance(value, int):
			raise DocumentValidationError("file_size_bytes must be an integer")
		if value < 0:
			raise DocumentValidationError("file_size_bytes cannot be negative")
		if value > 10 * 1024 * 1024 * 1024 * 1024:
			raise DocumentValidationError("file_size_bytes exceeds the maximum supported size")
		return value

	def _normalize_checksum(self, value: str | None) -> str | None:
		text = self._optional_text(value, "checksum_sha256", max_length=64)
		if text is None:
			return None
		if not _CHECKSUM_RE.fullmatch(text):
			raise DocumentValidationError("checksum_sha256 must be 64 hexadecimal characters")
		return text.lower()

	@staticmethod
	def _normalize_limit(
		value: int,
		*,
		field_name: str = "limit",
		maximum: int = 200,
	) -> int:
		if isinstance(value, bool) or not isinstance(value, int):
			raise DocumentValidationError(f"{field_name} must be an integer")
		if value < 1 or value > maximum:
			raise DocumentValidationError(f"{field_name} must be between 1 and {maximum}")
		return value

	@staticmethod
	def _normalize_expiry(value: datetime | None) -> datetime | None:
		if value is None:
			return None
		if not isinstance(value, datetime):
			raise DocumentValidationError("expires_at must be a datetime")
		expiry = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
		if expiry <= datetime.now(timezone.utc):
			raise DocumentValidationError("expires_at must be in the future")
		return expiry

	def _update_search_vector(self, doc: Document, session: Session) -> None:
		"""Update doc.search_vector using PostgreSQL to_tsvector().

		Concatenates title + description (with weight on title) so that
		title matches rank higher than description matches.
		"""
		text_parts = [doc.title or ""]
		if doc.description:
			text_parts.append(doc.description)
		full_text = " ".join(text_parts)

		# Execute the tsvector update directly on the DB row to get the
		# correct binary representation back into the mapped column.
		session.execute(
			sa.update(Document)
			.where(Document.id == doc.id)
			.values(
				search_vector=sa.func.to_tsvector("english", full_text)
			)
		)
		# Expire the attribute so it is re-loaded on next access
		session.expire(doc, ["search_vector"])


# ---------------------------------------------------------------------------
# BPM action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"platform.documents.attach",
	"Attach document to workflow record",
)
def _bpm_attach_document(
	record_ctx: dict[str, Any],
	params: dict[str, Any],
	session: Session,
) -> dict[str, Any]:
	"""BPM capability: attach a document to the current workflow record.

	params:
	  document_id   — ID of the Document to attach
	  source_module — module identifier (e.g. "hcm.payroll")

	record_ctx:
	  record_id     — ID of the target record
	  module        — module name (used as source_module when not in params)
	"""
	svc = DocumentService()
	document_id = svc._require_text(
		params.get("document_id", ""), "document_id", max_length=36
	)
	source_module = params.get("source_module") or record_ctx.get("module", "")
	source_record_id = svc._require_text(
		record_ctx.get("record_id", ""), "record_id", max_length=50
	)
	attached_by = (
		params.get("attached_by")
		or record_ctx.get("actor_id")
		or record_ctx.get("user_id")
	)
	tenant_id = params.get("tenant_id") or record_ctx.get("tenant_id")
	doc = svc.attach_to_record(
		document_id,
		source_module,
		source_record_id,
		session,
		tenant_id=tenant_id,
		attached_by=attached_by,
	)
	return {"document_id": doc.id, "source_module": doc.source_module, "source_record_id": doc.source_record_id}


@BPMActionRegistry.register(
	"platform.documents.request_signature",
	"Request e-signature on document",
)
def _bpm_request_signature(
	record_ctx: dict[str, Any],
	params: dict[str, Any],
	session: Session,
) -> dict[str, Any]:
	"""BPM capability: raise an e-signature request for a document.

	params:
	  document_id  — ID of the Document requiring signatures
	  signatories  — list of user IDs / email addresses to sign
	  request_id   — optional idempotency key; auto-generated if absent

	Emits DocumentSignatureRequestedEvent and returns the request_id.
	"""
	import uuid as _uuid
	from pgappforge.plugins.erp.platform.documents.events import DocumentSignatureRequestedEvent

	svc = DocumentService()
	document_id = svc._require_text(
		params.get("document_id", ""), "document_id", max_length=36
	)
	signatories = params.get("signatories", [])
	if not isinstance(signatories, list) or not signatories:
		raise DocumentValidationError("signatories must be a non-empty list")
	signatories = [
		svc._require_text(signatory, f"signatories[{index}]", max_length=320)
		for index, signatory in enumerate(signatories)
	]
	request_id = svc._optional_text(
		params.get("request_id"), "request_id", max_length=100
	) or str(_uuid.uuid4())
	tenant_id = svc._optional_text(
		params.get("tenant_id") or record_ctx.get("tenant_id"),
		"tenant_id",
		max_length=36,
	)

	# Look up tenant_id from the document
	doc = svc._get_existing_document(document_id, session, tenant_id=tenant_id)
	svc._require_active_document(doc)

	emit_event(
		DocumentSignatureRequestedEvent(
			aggregate_id=document_id,
			tenant_id=doc.tenant_id,
			doc_id=document_id,
			request_id=request_id,
			signatories=signatories,
		),
		session,
	)

	log.info(
		"DMS: signature requested on document %s (request_id=%s, signatories=%s)",
		document_id, request_id, signatories,
	)
	return {"request_id": request_id, "document_id": document_id, "signatories": signatories}
