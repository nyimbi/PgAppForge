"""
pgappforge/plugins/erp/platform/document_management/services.py

Service layer for ERP entity attachments.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from flask import current_app, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from pgappforge.plugins.erp.platform.document_management.models import Attachment, uuid7str


class AttachmentServiceError(Exception):
	"""Base exception for attachment service failures."""


class AttachmentValidationError(AttachmentServiceError):
	"""Raised when an attachment upload fails validation."""


class AttachmentNotFoundError(AttachmentServiceError):
	"""Raised when an attachment does not exist for the tenant."""


class AttachmentService:
	"""Validate, store, query, and delete ERP entity attachments."""

	UPLOAD_FOLDER = "uploads/erp"
	MAX_FILE_SIZE = 52428800
	ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "png", "jpg", "jpeg", "csv", "txt"}

	def attach(
		self,
		session: Any,
		tenant_id: str,
		entity_type: str,
		entity_id: str,
		file_storage: FileStorage,
		uploaded_by: str,
		description: str | None = None,
	) -> Attachment:
		"""Validate and persist an uploaded file attachment."""
		tenant_id = self._required_text(tenant_id, "tenant_id", max_length=36)
		entity_type = self._required_text(entity_type, "entity_type", max_length=80)
		entity_id = self._required_text(entity_id, "entity_id", max_length=80)
		uploaded_by = self._required_text(uploaded_by, "uploaded_by", max_length=80)
		description = self._optional_text(description, max_length=5000)

		if file_storage is None or not getattr(file_storage, "filename", None):
			raise AttachmentValidationError("No file uploaded")

		original_filename = secure_filename(file_storage.filename or "")
		if not original_filename:
			raise AttachmentValidationError("Uploaded file has no valid filename")

		extension = self._extension(original_filename)
		file_size = self._file_size(file_storage)
		if file_size > self.MAX_FILE_SIZE:
			raise AttachmentValidationError(
				f"File exceeds maximum size of {self.MAX_FILE_SIZE} bytes"
			)

		attachment_id = uuid7str()
		filename = f"{attachment_id}.{extension}"
		relative_path = self._relative_storage_path(
			tenant_id,
			entity_type,
			entity_id,
			filename,
		)
		absolute_path = self._absolute_storage_path(relative_path)
		absolute_path.parent.mkdir(parents=True, exist_ok=True)
		file_storage.stream.seek(0)
		file_storage.save(str(absolute_path))

		try:
			attachment = Attachment(
				id=attachment_id,
				tenant_id=tenant_id,
				entity_type=entity_type,
				entity_id=entity_id,
				filename=filename,
				original_filename=original_filename,
				content_type=file_storage.mimetype or "application/octet-stream",
				file_size_bytes=file_size,
				storage_path=relative_path,
				uploaded_by=uploaded_by,
				description=description,
			)
			session.add(attachment)
			session.flush()
		except Exception:
			try:
				absolute_path.unlink()
			except FileNotFoundError:
				pass
			raise
		return attachment

	def get_attachments(
		self,
		session: Any,
		tenant_id: str,
		entity_type: str | None = None,
		entity_id: str | None = None,
	) -> list[Attachment]:
		"""Return tenant attachments, optionally filtered by entity."""
		tenant_id = self._required_text(tenant_id, "tenant_id", max_length=36)
		query = sa.select(Attachment).where(Attachment.tenant_id == tenant_id)
		if entity_type:
			query = query.where(Attachment.entity_type == entity_type)
		if entity_id:
			query = query.where(Attachment.entity_id == entity_id)
		query = query.order_by(Attachment.uploaded_at.desc())
		return list(session.execute(query).scalars().all())

	def delete(self, session: Any, tenant_id: str, attachment_id: str) -> Attachment:
		"""Verify tenant ownership, remove the stored file, and delete the row."""
		attachment = self._get_for_tenant(session, tenant_id, attachment_id)
		absolute_path = self._absolute_storage_path(attachment.storage_path)
		try:
			absolute_path.unlink()
		except FileNotFoundError:
			pass
		session.delete(attachment)
		session.flush()
		return attachment

	def get_download_url(self, attachment: Attachment | str) -> str:
		"""Return the Flask URL for downloading an attachment."""
		attachment_id = attachment if isinstance(attachment, str) else attachment.id
		return url_for("AttachmentView.download", id=attachment_id)

	def _get_for_tenant(
		self,
		session: Any,
		tenant_id: str,
		attachment_id: str,
	) -> Attachment:
		tenant_id = self._required_text(tenant_id, "tenant_id", max_length=36)
		attachment_id = self._required_text(attachment_id, "attachment_id", max_length=36)
		attachment = session.get(Attachment, attachment_id)
		if attachment is None or str(attachment.tenant_id) != tenant_id:
			raise AttachmentNotFoundError(f"Attachment {attachment_id!r} not found")
		return attachment

	def absolute_path(self, attachment: Attachment) -> Path:
		"""Return the filesystem path for an attachment row."""
		return self._absolute_storage_path(attachment.storage_path)

	def _extension(self, filename: str) -> str:
		extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
		if extension not in self.ALLOWED_EXTENSIONS:
			raise AttachmentValidationError(f"File type {extension!r} is not allowed")
		return extension

	def _file_size(self, file_storage: FileStorage) -> int:
		content_length = getattr(file_storage, "content_length", None)
		if content_length:
			return int(content_length)
		stream = file_storage.stream
		position = stream.tell()
		stream.seek(0, os.SEEK_END)
		size = stream.tell()
		stream.seek(position)
		return int(size)

	def _relative_storage_path(
		self,
		tenant_id: str,
		entity_type: str,
		entity_id: str,
		filename: str,
	) -> str:
		parts = [
			self.UPLOAD_FOLDER,
			self._safe_path_part(tenant_id),
			self._safe_path_part(entity_type),
			self._safe_path_part(entity_id),
			filename,
		]
		return "/".join(parts)

	def _absolute_storage_path(self, storage_path: str) -> Path:
		path = Path(storage_path)
		if path.is_absolute():
			return path
		return Path(current_app.instance_path) / path

	def _safe_path_part(self, value: str) -> str:
		part = secure_filename(str(value).strip())
		if not part:
			raise AttachmentValidationError("Invalid storage path component")
		return part

	def _required_text(self, value: object, name: str, *, max_length: int) -> str:
		text = str(value or "").strip()
		if not text:
			raise AttachmentValidationError(f"{name} is required")
		if len(text) > max_length:
			raise AttachmentValidationError(f"{name} must be {max_length} characters or fewer")
		return text

	def _optional_text(self, value: object, *, max_length: int) -> str | None:
		if value is None:
			return None
		text = str(value).strip()
		if not text:
			return None
		if len(text) > max_length:
			raise AttachmentValidationError(
				f"description must be {max_length} characters or fewer"
			)
		return text


__all__ = [
	"AttachmentService",
	"AttachmentServiceError",
	"AttachmentValidationError",
	"AttachmentNotFoundError",
]
