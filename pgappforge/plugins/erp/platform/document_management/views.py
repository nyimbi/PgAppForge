"""
pgappforge/plugins/erp/platform/document_management/views.py

Flask-AppBuilder endpoints for ERP entity attachments.
"""
from __future__ import annotations

from flask import abort, jsonify, request, send_file
from pgappforge.baseviews import expose
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.document_management.services import (
	AttachmentNotFoundError,
	AttachmentService,
	AttachmentServiceError,
	AttachmentValidationError,
)


class AttachmentView(BaseERPView):
	"""Upload, download, and delete ERP entity attachments."""

	route_base = "/erp/attachments"

	@expose("/upload/", methods=["POST"])
	@has_access
	def upload(self):
		session = self._session()
		service = AttachmentService()
		file_storage = request.files.get("file") or request.files.get("attachment")
		try:
			attachment = service.attach(
				session=session,
				tenant_id=request.form.get("tenant_id") or self._tenant_id(),
				entity_type=request.form.get("entity_type", ""),
				entity_id=request.form.get("entity_id", ""),
				file_storage=file_storage,
				uploaded_by=request.form.get("uploaded_by") or self._current_user_id(),
				description=request.form.get("description"),
			)
			session.commit()
		except AttachmentValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 400
		except AttachmentServiceError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 404
		except Exception:
			session.rollback()
			raise
		return jsonify(self._serialize(attachment)), 201

	@expose("/<string:id>/download")
	@has_access
	def download(self, id: str):
		service = AttachmentService()
		try:
			attachment = service._get_for_tenant(
				self._session(),
				request.args.get("tenant_id") or self._tenant_id(),
				id,
			)
		except AttachmentNotFoundError:
			abort(404)
		path = service.absolute_path(attachment)
		if not path.exists():
			abort(404)
		return send_file(
			str(path),
			mimetype=attachment.content_type,
			as_attachment=True,
			download_name=attachment.original_filename,
		)

	@expose("/<string:id>/delete", methods=["POST"])
	@has_access
	def delete(self, id: str):
		session = self._session()
		service = AttachmentService()
		data = request.get_json(silent=True) or {}
		try:
			attachment = service.delete(
				session,
				data.get("tenant_id") or request.form.get("tenant_id") or self._tenant_id(),
				id,
			)
			session.commit()
		except AttachmentNotFoundError:
			session.rollback()
			abort(404)
		except AttachmentServiceError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 400
		except Exception:
			session.rollback()
			raise
		return jsonify({"status": "deleted", "id": str(attachment.id)})

	def _serialize(self, attachment) -> dict:
		return {
			"id": str(attachment.id),
			"tenant_id": str(attachment.tenant_id),
			"entity_type": attachment.entity_type,
			"entity_id": attachment.entity_id,
			"filename": attachment.filename,
			"original_filename": attachment.original_filename,
			"content_type": attachment.content_type,
			"file_size_bytes": int(attachment.file_size_bytes or 0),
			"uploaded_by": attachment.uploaded_by,
			"uploaded_at": attachment.uploaded_at.isoformat() if attachment.uploaded_at else None,
			"description": attachment.description,
			"download_url": AttachmentService().get_download_url(attachment),
		}

	def _current_user_id(self) -> str:
		try:
			user = self.appbuilder.sm.get_user_by_id(self.appbuilder.sm.get_user_id())
			return str(getattr(user, "id", "") or getattr(user, "username", "") or "system")
		except Exception:
			return "system"


__all__ = ["AttachmentView"]
