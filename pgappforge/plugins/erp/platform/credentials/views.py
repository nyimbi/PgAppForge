"""
pgappforge/plugins/erp/platform/credentials/views.py

Flask views for the Digital Credentials plugin.

Endpoints:
  CredentialSchemaView    GET/POST  /credentials/schemas/
                          GET       /credentials/schemas/<id>
  IssuedCredentialView    GET       /credentials/issued/
                          POST      /credentials/issue
                          POST      /credentials/issued/<id>/revoke
                          GET       /credentials/issued/<id>/share/linkedin
                          POST      /credentials/issued/<id>/share/linkedin
  VerificationPortalView  GET       /verify/<token>   (public, no auth)
  BulkIssueView           POST      /credentials/bulk-issue
  TranscriptView          GET       /credentials/transcript/<recipient_id>
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	rich_text_widget,
	file_widget,
	date_widget,
	qr_widget,
	select2_widget,
	json_widget,
)

log = logging.getLogger(__name__)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.platform.credentials.services import CredentialsService
	return CredentialsService()


# ---------------------------------------------------------------------------
# CredentialSchemaView
# ---------------------------------------------------------------------------

class CredentialSchemaView(BaseView):
	"""Credential schema definition CRUD.

	Widget hints (consumed by form builder):
	  criteria_narrative  → RichTextEditorWidget
	  image_url           → ImageCropWidget / FileUploadWidget
	  background_image_url → FileUploadWidget
	  alignment           → JSONEditorWidget
	  evidence_schema     → JSONEditorWidget
	  credential_type     → Select2Widget
	"""

	route_base = "/credentials/schemas"
	default_view = "list"

	form_widget_args = {
		"criteria_narrative": rich_text_widget(height=250),
		"image_url": file_widget(types=["png", "jpg", "svg", "webp"]),
		"background_image_url": file_widget(types=["png", "jpg", "webp"]),
		"alignment": json_widget(mode="tree", height=200),
		"evidence_schema": json_widget(mode="tree", height=200),
		"credential_type": select2_widget(
			choices=["CERTIFICATE", "BADGE", "LICENSE", "DEGREE", "MEMBERSHIP", "AWARD"]
		),
	}

	@expose("/")
	@has_access
	def list(self):
		"""List credential schemas for a tenant.

		Query params: tenant_id, credential_type, is_published
		"""
		from pgappforge.plugins.erp.platform.credentials.models import CredentialSchema
		session = _get_session()
		args = request.args
		q = sa.select(CredentialSchema).order_by(CredentialSchema.name)
		if args.get("tenant_id"):
			q = q.where(CredentialSchema.tenant_id == args["tenant_id"])
		if args.get("credential_type"):
			q = q.where(CredentialSchema.credential_type == args["credential_type"])
		if args.get("is_published") is not None:
			is_pub = args.get("is_published", "true").lower() != "false"
			q = q.where(CredentialSchema.is_published == is_pub)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"schema_id": r.schema_id,
				"name": r.name,
				"version": r.version,
				"credential_type": r.credential_type,
				"issuer_id": str(r.issuer_id),
				"is_published": r.is_published,
				"image_url": r.image_url,
				"tags": r.tags or [],
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Create a credential schema.

		Body (JSON): all CredentialSchema fields.
		Required: tenant_id, schema_id, name, credential_type, issuer_id.
		"""
		from pgappforge.plugins.erp.platform.credentials.models import CredentialSchema
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "schema_id", "name", "credential_type", "issuer_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		schema = CredentialSchema(
			tenant_id=data["tenant_id"],
			schema_id=data["schema_id"],
			name=data["name"],
			version=data.get("version", "1.0"),
			credential_type=data["credential_type"],
			issuer_id=data["issuer_id"],
			description=data.get("description"),
			criteria_narrative=data.get("criteria_narrative"),
			evidence_schema=data.get("evidence_schema"),
			image_url=data.get("image_url"),
			background_image_url=data.get("background_image_url"),
			alignment=data.get("alignment", []),
			tags=data.get("tags", []),
			is_published=data.get("is_published", True),
		)
		session.add(schema)
		session.commit()
		return jsonify({"id": schema.id, "schema_id": schema.schema_id, "status": "created"}), 201

	@expose("/<string:schema_id>")
	@has_access
	def get(self, schema_id: str):
		"""Return full schema detail."""
		from pgappforge.plugins.erp.platform.credentials.models import CredentialSchema
		session = _get_session()
		schema = session.get(CredentialSchema, schema_id)
		if schema is None:
			abort(404, f"CredentialSchema {schema_id!r} not found")
		return jsonify({
			"id": str(schema.id),
			"schema_id": schema.schema_id,
			"name": schema.name,
			"version": schema.version,
			"credential_type": schema.credential_type,
			"issuer_id": str(schema.issuer_id),
			"description": schema.description,
			"criteria_narrative": schema.criteria_narrative,
			"evidence_schema": schema.evidence_schema,
			"image_url": schema.image_url,
			"background_image_url": schema.background_image_url,
			"alignment": schema.alignment or [],
			"tags": schema.tags or [],
			"is_published": schema.is_published,
		})


# ---------------------------------------------------------------------------
# IssuedCredentialView
# ---------------------------------------------------------------------------

class IssuedCredentialView(BaseView):
	"""Issued credential list, issue, revoke, and share.

	Widget hints:
	  qr_code_url  → QrCodeWidget
	  expires_at   → DatePickerWidget
	  evidence     → JSONEditorWidget
	"""

	route_base = "/credentials/issued"
	default_view = "list"

	form_widget_args = {
		"qr_code_url": qr_widget(size=250),
		"expires_at": date_widget("YYYY-MM-DD"),
		"evidence": json_widget(mode="tree", height=200),
	}

	@expose("/")
	@has_access
	def list(self):
		"""List issued credentials.

		Query params: tenant_id, recipient_id, schema_id, status
		"""
		from pgappforge.plugins.erp.platform.credentials.models import IssuedCredential
		session = _get_session()
		args = request.args
		q = sa.select(IssuedCredential).order_by(IssuedCredential.issued_at.desc())
		if args.get("tenant_id"):
			q = q.where(IssuedCredential.tenant_id == args["tenant_id"])
		if args.get("recipient_id"):
			q = q.where(IssuedCredential.recipient_id == args["recipient_id"])
		if args.get("schema_id"):
			q = q.where(IssuedCredential.schema_id == args["schema_id"])
		if args.get("status"):
			q = q.where(IssuedCredential.status == args["status"].upper())
		limit = min(int(args.get("limit", 100)), 500)
		rows = session.execute(q.limit(limit)).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"credential_number": r.credential_number,
				"schema_id": str(r.schema_id),
				"recipient_id": str(r.recipient_id),
				"recipient_email": r.recipient_email,
				"issued_at": r.issued_at.isoformat(),
				"expires_at": r.expires_at.isoformat() if r.expires_at else None,
				"status": r.status,
				"verification_url": r.verification_url,
				"qr_code_url": r.qr_code_url,
			}
			for r in rows
		])

	@expose("/issue", methods=["POST"])
	@has_access
	def issue(self):
		"""Issue a single credential.

		Body: tenant_id, schema_id, recipient_id, recipient_email,
		      evidence (dict), narrative (str), expires_at (ISO str), base_url (str)
		"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "schema_id", "recipient_id", "recipient_email")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400

		expires_at = None
		if data.get("expires_at"):
			from datetime import datetime, timezone
			try:
				expires_at = datetime.fromisoformat(data["expires_at"])
				if expires_at.tzinfo is None:
					expires_at = expires_at.replace(tzinfo=timezone.utc)
			except ValueError:
				return jsonify({"error": "Invalid expires_at ISO format"}), 400

		try:
			credential = _svc().issue_credential(
				session=session,
				tenant_id=data["tenant_id"],
				schema_id=data["schema_id"],
				recipient_id=data["recipient_id"],
				recipient_email=data["recipient_email"],
				evidence=data.get("evidence"),
				narrative=data.get("narrative"),
				expires_at=expires_at,
				base_url=data.get("base_url", "https://credentials.example.com"),
			)
			session.commit()
			return jsonify({
				"credential_id": credential.id,
				"credential_number": credential.credential_number,
				"verification_url": credential.verification_url,
				"qr_code_url": credential.qr_code_url,
				"status": credential.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:credential_id>/revoke", methods=["POST"])
	@has_access
	def revoke(self, credential_id: str):
		"""Revoke a credential.

		Body: {"reason": str}
		"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		reason = data.get("reason", "")
		if not reason:
			return jsonify({"error": "reason required for revocation"}), 400
		try:
			credential = _svc().revoke_credential(
				session=session,
				credential_id=credential_id,
				reason=reason,
			)
			session.commit()
			return jsonify({
				"credential_id": credential.id,
				"credential_number": credential.credential_number,
				"status": credential.status,
				"revoked_at": credential.revoked_at.isoformat(),
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:credential_id>/share/linkedin", methods=["POST"])
	@has_access
	def share_linkedin(self, credential_id: str):
		"""Share a credential to LinkedIn.

		Body: {"tenant_id": str, "access_token": str}
		"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("access_token"):
			return jsonify({"error": "access_token required"}), 400
		try:
			result = _svc().share_to_linkedin(
				session=session,
				tenant_id=data.get("tenant_id", "default"),
				credential_id=credential_id,
				access_token=data["access_token"],
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# VerificationPortalView
# ---------------------------------------------------------------------------

class VerificationPortalView(BaseView):
	"""Public credential verification portal — no authentication required.

	GET /verify/<token>
	Returns a human-readable JSON verification result.
	"""

	route_base = "/verify"
	default_view = "verify"

	@expose("/<string:token>")
	def verify(self, token: str):
		"""Public endpoint: verify a credential by its URL token.

		No @has_access — publicly accessible for third-party verifiers.
		Records a CredentialVerification log row.
		"""
		session = _get_session()
		verifier_email = request.args.get("verifier_email")
		try:
			verification = _svc().verify_credential(
				session=session,
				tenant_id="",
				verification_token=token,
				verifier_email=verifier_email,
			)
			session.commit()
			return jsonify({
				"result": verification.result,
				"verified_at": verification.verified_at.isoformat(),
				"details": verification.verification_details,
			})
		except Exception as exc:
			log.warning("VerificationPortalView: error for token=%r: %s", token, exc)
			return jsonify({"result": "ERROR", "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# BulkIssueView
# ---------------------------------------------------------------------------

class BulkIssueView(BaseView):
	"""Bulk credential issuance from a recipient list.

	Widget hints:
	  recipients → SpreadsheetWidget (CSV upload parsed to list[dict])
	"""

	route_base = "/credentials/bulk-issue"
	default_view = "issue"

	form_widget_args = {
		"recipients": file_widget(types=["csv", "xlsx"]),
	}

	@expose("/", methods=["POST"])
	@has_access
	def issue(self):
		"""Bulk-issue credentials.

		Body (JSON):
		  tenant_id   str        required
		  schema_id   str        required
		  recipients  list[dict] required  each: {recipient_id, recipient_email,
		                                          evidence?, narrative?, expires_at?}
		  base_url    str        optional
		"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "schema_id", "recipients")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400

		recipients = data["recipients"]
		if not isinstance(recipients, list) or not recipients:
			return jsonify({"error": "recipients must be a non-empty list"}), 400

		try:
			issued = _svc().bulk_issue(
				session=session,
				tenant_id=data["tenant_id"],
				schema_id=data["schema_id"],
				recipients=recipients,
				base_url=data.get("base_url", "https://credentials.example.com"),
			)
			session.commit()
			return jsonify({
				"issued_count": len(issued),
				"total_requested": len(recipients),
				"credentials": [
					{
						"credential_id": c.id,
						"credential_number": c.credential_number,
						"recipient_email": c.recipient_email,
						"verification_url": c.verification_url,
					}
					for c in issued
				],
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# TranscriptView
# ---------------------------------------------------------------------------

class TranscriptView(BaseView):
	"""Credential transcript for a recipient."""

	route_base = "/credentials/transcript"
	default_view = "get"

	@expose("/<string:recipient_id>")
	@has_access
	def get(self, recipient_id: str):
		"""Return all active credentials for a recipient.

		Query params:
		  include_revoked  bool  default false
		"""
		session = _get_session()
		include_revoked = (
			request.args.get("include_revoked", "false").lower() == "true"
		)
		transcript = _svc().generate_transcript(
			session=session,
			recipient_id=recipient_id,
			include_revoked=include_revoked,
		)
		return jsonify({
			"recipient_id": recipient_id,
			"credential_count": len(transcript),
			"credentials": transcript,
		})


__all__ = [
	"CredentialSchemaView",
	"IssuedCredentialView",
	"VerificationPortalView",
	"BulkIssueView",
	"TranscriptView",
]
