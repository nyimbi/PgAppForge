"""
pgappforge/plugins/erp/crm/sign/services.py

SignatureService — stateless business logic for the E-Sign Portal plugin.

Key methods
-----------
  create_request(document_id, document_title, initiator_id, signatories_data,
                 tenant_id, session, *, signing_order, subject, message,
                 expires_at, bpm_instance_id) -> SignatureRequest
  send_request(request_id, session) -> SignatureRequest
  sign_document(access_token, signature_image_base64, session, *,
                ip_address, user_agent) -> SignatureSignatory
  decline_document(access_token, reason, session) -> SignatureSignatory
  check_expiry(session, *, tenant_id) -> list[SignatureRequest]
  get_request_status(request_id, session) -> dict
"""
from __future__ import annotations

import hashlib
import hmac as _hmac_mod
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


def _hash_token(raw: str) -> str:
	"""SHA-256 hash of a raw access token for safe DB storage."""
	return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SignServiceError(Exception):
	"""Base exception for the E-Sign Portal service layer."""


class SignNotFoundError(SignServiceError):
	"""Raised when a SignatureRequest or SignatureSignatory cannot be found."""


class SignStateError(SignServiceError):
	"""Raised when an operation is invalid for the current sign state."""


# ---------------------------------------------------------------------------
# SignatureService
# ---------------------------------------------------------------------------

class SignatureService:
	"""Stateless business logic for the E-Sign Portal."""

	# ------------------------------------------------------------------
	# 1. create_request
	# ------------------------------------------------------------------

	@staticmethod
	def create_request(
		document_id: str,
		document_title: str,
		initiator_id: str,
		signatories_data: list[dict[str, Any]],
		tenant_id: str,
		session: Any,
		*,
		signing_order: str = "PARALLEL",
		subject: str | None = None,
		message: str | None = None,
		expires_at: datetime | None = None,
		bpm_instance_id: str | None = None,
	) -> Any:
		"""Create a SignatureRequest with its signatories and log CREATED.

		signatories_data: list of dicts with keys:
		  signer_email (required), signer_name (required),
		  signer_id (optional), signer_role (optional), order_number (optional)
		"""
		from pgappforge.plugins.erp.crm.sign.models import SignatureRequest, SignatureSignatory, SignatureAuditLog
		from pgappforge.plugins.erp.crm.sign.events import SignatureRequestCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert document_id, "document_id is required"
		assert document_title, "document_title is required"
		assert initiator_id, "initiator_id is required"
		assert signatories_data, "At least one signatory is required"
		assert signing_order in ("PARALLEL", "SEQUENTIAL"), \
			f"signing_order must be PARALLEL or SEQUENTIAL, got {signing_order!r}"

		request = SignatureRequest(
			tenant_id=tenant_id,
			document_id=document_id,
			document_title=document_title,
			initiator_id=initiator_id,
			status="PENDING",
			signing_order=signing_order,
			subject=subject,
			message=message,
			expires_at=expires_at,
			bpm_instance_id=bpm_instance_id,
			metadata_={},
		)
		session.add(request)
		session.flush()

		signatory_ids: list[str] = []
		# Collect raw tokens (transient — sent to signers via email link, never re-read from DB)
		raw_tokens: list[str] = []
		for i, sig_data in enumerate(signatories_data):
			raw_token = secrets.token_urlsafe(32)
			signatory = SignatureSignatory(
				tenant_id=tenant_id,
				request_id=request.id,
				signer_id=sig_data.get("signer_id"),
				signer_email=sig_data["signer_email"],
				signer_name=sig_data["signer_name"],
				signer_role=sig_data.get("signer_role"),
				order_number=sig_data.get("order_number", i),
				status="PENDING",
				access_token=_hash_token(raw_token),
			)
			signatory._raw_token = raw_token  # transient — available on the in-memory object
			raw_tokens.append(raw_token)
			session.add(signatory)
			signatory_ids.append(sig_data["signer_email"])
		session.flush()
		# Attach raw tokens to request for immediate caller access (not persisted)
		request._raw_tokens = raw_tokens

		# Log CREATED
		session.add(SignatureAuditLog(
			tenant_id=tenant_id,
			request_id=request.id,
			signatory_id=None,
			action="CREATED",
			actor_id=initiator_id,
			metadata_={"document_id": document_id, "signing_order": signing_order},
		))
		session.flush()

		emit_event(SignatureRequestCreatedEvent(
			aggregate_id=request.id,
			aggregate_type="SignatureRequest",
			tenant_id=tenant_id,
			request_id=request.id,
			document_id=document_id,
			initiator_id=initiator_id,
			signatories=signatory_ids,
		), session)

		log.info(
			"SignatureService.create_request: request %s created for document %s with %d signatories",
			request.id, document_id, len(signatories_data),
		)
		return request

	# ------------------------------------------------------------------
	# 2. send_request
	# ------------------------------------------------------------------

	@staticmethod
	def send_request(request_id: str, session: Any) -> Any:
		"""Transition request to IN_PROGRESS and log SENT.

		For SEQUENTIAL orders, notifies only the first (order_number=0) signatory.
		For PARALLEL orders, all PENDING signatories are notified.
		Notification dispatch is best-effort (non-fatal).
		"""
		from pgappforge.plugins.erp.crm.sign.models import (
			SignatureRequest, SignatureSignatory, SignatureAuditLog,
		)

		request = session.execute(
			sa.select(SignatureRequest).where(SignatureRequest.id == request_id)
		).scalar_one_or_none()
		if request is None:
			raise SignNotFoundError(f"SignatureRequest {request_id} not found")
		if request.status not in ("PENDING",):
			raise SignStateError(
				f"Cannot send request in status {request.status!r}; must be PENDING"
			)

		request.status = "IN_PROGRESS"
		session.flush()

		session.add(SignatureAuditLog(
			tenant_id=request.tenant_id,
			request_id=request.id,
			signatory_id=None,
			action="SENT",
			actor_id=request.initiator_id,
			metadata_={"signing_order": request.signing_order},
		))
		session.flush()

		# Determine which signatories to notify
		if request.signing_order == "SEQUENTIAL":
			first = session.execute(
				sa.select(SignatureSignatory)
				.where(
					SignatureSignatory.request_id == request_id,
					SignatureSignatory.status == "PENDING",
				)
				.order_by(SignatureSignatory.order_number)
				.limit(1)
			).scalar_one_or_none()
			notify_list = [first] if first else []
		else:
			notify_list = list(
				session.execute(
					sa.select(SignatureSignatory).where(
						SignatureSignatory.request_id == request_id,
						SignatureSignatory.status == "PENDING",
					)
				).scalars().all()
			)

		# Non-fatal notification dispatch
		for sig in notify_list:
			try:
				SignatureService._notify_signatory(request, sig)
			except Exception as exc:
				log.warning(
					"SignatureService.send_request: notify %s failed (non-fatal): %s",
					sig.signer_email, exc,
				)

		log.info(
			"SignatureService.send_request: request %s IN_PROGRESS, %d notified",
			request_id, len(notify_list),
		)
		return request

	@staticmethod
	def _notify_signatory(request: Any, signatory: Any) -> None:
		"""Dispatch signing notification to a signatory (placeholder)."""
		log.debug(
			"SignatureService._notify_signatory: would email %s signing link with token %s",
			signatory.signer_email,
			signatory.access_token[:8] + "…" if signatory.access_token else "?",
		)

	# ------------------------------------------------------------------
	# 3. sign_document
	# ------------------------------------------------------------------

	@staticmethod
	def sign_document(
		access_token: str,
		signature_image_base64: str,
		session: Any,
		*,
		ip_address: str | None = None,
		user_agent: str | None = None,
	) -> Any:
		"""Record a signatory's signature via their one-click access token.

		If all signatories have now signed, calls _complete_request().
		For SEQUENTIAL requests, activates the next pending signatory.
		"""
		from pgappforge.plugins.erp.crm.sign.models import (
			SignatureRequest, SignatureSignatory, SignatureAuditLog,
		)
		from pgappforge.plugins.erp.crm.sign.events import SignatureRequestSignedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert access_token, "access_token is required"

		signatory = session.execute(
			sa.select(SignatureSignatory).where(
				SignatureSignatory.access_token == _hash_token(access_token)
			)
		).scalar_one_or_none()
		if signatory is None:
			raise SignNotFoundError(f"No signatory found for access_token provided")
		if signatory.status != "PENDING":
			raise SignStateError(
				f"Signatory is in status {signatory.status!r}; can only sign from PENDING"
			)

		now = datetime.now(timezone.utc)
		signatory.status = "SIGNED"
		signatory.signed_at = now
		signatory.signature_image_base64 = signature_image_base64
		signatory.ip_address = ip_address
		signatory.user_agent = user_agent
		# Invalidate the token to prevent re-use
		signatory.access_token = None
		session.flush()

		session.add(SignatureAuditLog(
			tenant_id=signatory.tenant_id,
			request_id=signatory.request_id,
			signatory_id=signatory.id,
			action="SIGNED",
			actor_id=signatory.signer_id,
			ip_address=ip_address,
			user_agent=user_agent,
			metadata_={"signed_at": now.isoformat()},
		))
		session.flush()

		emit_event(SignatureRequestSignedEvent(
			aggregate_id=signatory.request_id,
			aggregate_type="SignatureRequest",
			tenant_id=signatory.tenant_id,
			signature_id=signatory.id,
			request_id=signatory.request_id,
			signer_id=signatory.signer_id or "",
			signed_at=now.isoformat(),
		), session)

		# Check completion
		pending_count = session.execute(
			sa.select(sa.func.count()).select_from(SignatureSignatory).where(
				SignatureSignatory.request_id == signatory.request_id,
				SignatureSignatory.status == "PENDING",
			)
		).scalar_one()

		if pending_count == 0:
			SignatureService._complete_request(signatory.request_id, session)
		else:
			# For SEQUENTIAL: notify the next signatory
			request = session.execute(
				sa.select(SignatureRequest).where(
					SignatureRequest.id == signatory.request_id
				)
			).scalar_one_or_none()
			if request and request.signing_order == "SEQUENTIAL":
				next_sig = session.execute(
					sa.select(SignatureSignatory)
					.where(
						SignatureSignatory.request_id == signatory.request_id,
						SignatureSignatory.status == "PENDING",
					)
					.order_by(SignatureSignatory.order_number)
					.limit(1)
				).scalar_one_or_none()
				if next_sig:
					try:
						SignatureService._notify_signatory(request, next_sig)
					except Exception as exc:
						log.warning(
							"SignatureService.sign_document: next-signatory notify failed (non-fatal): %s",
							exc,
						)

		log.info(
			"SignatureService.sign_document: signatory %s signed request %s",
			signatory.signer_email, signatory.request_id,
		)
		return signatory

	# ------------------------------------------------------------------
	# 4. decline_document
	# ------------------------------------------------------------------

	@staticmethod
	def decline_document(access_token: str, reason: str, session: Any) -> Any:
		"""Record a signatory's decline and move the request to DECLINED."""
		from pgappforge.plugins.erp.crm.sign.models import (
			SignatureRequest, SignatureSignatory, SignatureAuditLog,
		)
		from pgappforge.plugins.erp.crm.sign.events import SignatureRequestDeclinedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert access_token, "access_token is required"

		signatory = session.execute(
			sa.select(SignatureSignatory).where(
				SignatureSignatory.access_token == _hash_token(access_token)
			)
		).scalar_one_or_none()
		if signatory is None:
			raise SignNotFoundError("No signatory found for access_token provided")
		if signatory.status != "PENDING":
			raise SignStateError(
				f"Signatory is in status {signatory.status!r}; can only decline from PENDING"
			)

		now = datetime.now(timezone.utc)
		signatory.status = "DECLINED"
		signatory.declined_at = now
		signatory.decline_reason = reason
		signatory.access_token = None
		session.flush()

		# Log decline on signatory
		session.add(SignatureAuditLog(
			tenant_id=signatory.tenant_id,
			request_id=signatory.request_id,
			signatory_id=signatory.id,
			action="DECLINED",
			actor_id=signatory.signer_id,
			metadata_={"reason": reason, "declined_at": now.isoformat()},
		))

		# Mark the overall request as DECLINED
		request = session.execute(
			sa.select(SignatureRequest).where(
				SignatureRequest.id == signatory.request_id
			)
		).scalar_one_or_none()
		if request and request.status not in ("COMPLETED", "CANCELLED"):
			request.status = "DECLINED"
			session.flush()
			session.add(SignatureAuditLog(
				tenant_id=signatory.tenant_id,
				request_id=signatory.request_id,
				signatory_id=None,
				action="DECLINED",
				actor_id=signatory.signer_id,
				metadata_={"declined_by": signatory.signer_email, "reason": reason},
			))
		session.flush()

		emit_event(SignatureRequestDeclinedEvent(
			aggregate_id=signatory.request_id,
			aggregate_type="SignatureRequest",
			tenant_id=signatory.tenant_id,
			request_id=signatory.request_id,
			signer_id=signatory.signer_id or "",
			reason=reason,
		), session)

		log.info(
			"SignatureService.decline_document: signatory %s declined request %s",
			signatory.signer_email, signatory.request_id,
		)
		return signatory

	# ------------------------------------------------------------------
	# 5. _complete_request (internal)
	# ------------------------------------------------------------------

	@staticmethod
	def _complete_request(request_id: str, session: Any) -> Any:
		"""Set status=COMPLETED, completed_at=now(), log COMPLETED, emit event."""
		from pgappforge.plugins.erp.crm.sign.models import SignatureRequest, SignatureAuditLog
		from pgappforge.plugins.erp.crm.sign.events import SignatureRequestCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		request = session.execute(
			sa.select(SignatureRequest).where(SignatureRequest.id == request_id)
		).scalar_one_or_none()
		if request is None:
			raise SignNotFoundError(f"SignatureRequest {request_id} not found")

		now = datetime.now(timezone.utc)
		request.status = "COMPLETED"
		request.completed_at = now
		session.flush()

		session.add(SignatureAuditLog(
			tenant_id=request.tenant_id,
			request_id=request.id,
			signatory_id=None,
			action="COMPLETED",
			actor_id=None,
			metadata_={"completed_at": now.isoformat()},
		))
		session.flush()

		emit_event(SignatureRequestCompletedEvent(
			aggregate_id=request.id,
			aggregate_type="SignatureRequest",
			tenant_id=request.tenant_id,
			request_id=request.id,
			document_id=request.document_id,
			all_signed_at=now.isoformat(),
		), session)

		log.info(
			"SignatureService._complete_request: request %s COMPLETED at %s",
			request_id, now.isoformat(),
		)
		return request

	# ------------------------------------------------------------------
	# 6. check_expiry
	# ------------------------------------------------------------------

	@staticmethod
	def check_expiry(session: Any, *, tenant_id: str | None = None) -> list[Any]:
		"""Find IN_PROGRESS requests past expires_at and mark them EXPIRED.

		Returns the list of expired SignatureRequest rows.
		"""
		from pgappforge.plugins.erp.crm.sign.models import SignatureRequest, SignatureAuditLog
		from pgappforge.plugins.erp.crm.sign.events import SignatureRequestExpiredEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		now = datetime.now(timezone.utc)
		stmt = sa.select(SignatureRequest).where(
			SignatureRequest.status == "IN_PROGRESS",
			SignatureRequest.expires_at.isnot(None),
			SignatureRequest.expires_at < now,
		)
		if tenant_id:
			stmt = stmt.where(SignatureRequest.tenant_id == tenant_id)

		expired_requests: list[Any] = list(session.execute(stmt).scalars().all())

		for request in expired_requests:
			request.status = "EXPIRED"
			session.flush()

			session.add(SignatureAuditLog(
				tenant_id=request.tenant_id,
				request_id=request.id,
				signatory_id=None,
				action="EXPIRED",
				actor_id=None,
				metadata_={"expired_at": now.isoformat()},
			))
			session.flush()

			emit_event(SignatureRequestExpiredEvent(
				aggregate_id=request.id,
				aggregate_type="SignatureRequest",
				tenant_id=request.tenant_id,
				request_id=request.id,
			), session)

		log.info(
			"SignatureService.check_expiry: %d requests expired",
			len(expired_requests),
		)
		return expired_requests

	# ------------------------------------------------------------------
	# 7. get_request_status
	# ------------------------------------------------------------------

	@staticmethod
	def get_request_status(request_id: str, session: Any) -> dict[str, Any]:
		"""Return a status summary for a SignatureRequest.

		Returns:
		  {
		    status: str,
		    signatories: [{name, email, status, signed_at}],
		    audit_log: [{action, actor_id, ip_address, created_at}],
		  }
		"""
		from pgappforge.plugins.erp.crm.sign.models import (
			SignatureRequest, SignatureSignatory, SignatureAuditLog,
		)

		request = session.execute(
			sa.select(SignatureRequest).where(SignatureRequest.id == request_id)
		).scalar_one_or_none()
		if request is None:
			raise SignNotFoundError(f"SignatureRequest {request_id} not found")

		signatories = list(
			session.execute(
				sa.select(SignatureSignatory)
				.where(SignatureSignatory.request_id == request_id)
				.order_by(SignatureSignatory.order_number)
			).scalars().all()
		)

		audit_rows = list(
			session.execute(
				sa.select(SignatureAuditLog)
				.where(SignatureAuditLog.request_id == request_id)
				.order_by(SignatureAuditLog.created_at)
			).scalars().all()
		)

		return {
			"request_id": request.id,
			"document_id": request.document_id,
			"document_title": request.document_title,
			"status": request.status,
			"signing_order": request.signing_order,
			"expires_at": request.expires_at.isoformat() if request.expires_at else None,
			"completed_at": request.completed_at.isoformat() if request.completed_at else None,
			"signatories": [
				{
					"signatory_id": s.id,
					"name": s.signer_name,
					"email": s.signer_email,
					"role": s.signer_role,
					"status": s.status,
					"signed_at": s.signed_at.isoformat() if s.signed_at else None,
					"declined_at": s.declined_at.isoformat() if s.declined_at else None,
				}
				for s in signatories
			],
			"audit_log": [
				{
					"action": a.action,
					"actor_id": a.actor_id,
					"ip_address": a.ip_address,
					"created_at": a.created_at.isoformat(),
					"metadata": a.metadata_,
				}
				for a in audit_rows
			],
		}


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

def _register_bpm_actions() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry
	except ImportError:
		return

	@BPMActionRegistry.register(
		"crm.sign.create_request",
		"Create signature request from workflow",
	)
	def _bpm_create_request(
		record_ctx: dict,
		session: Any,
		document_id: str = "",
		document_title: str = "",
		initiator_id: str = "",
		signatories_data: list | None = None,
		signing_order: str = "PARALLEL",
		subject: str | None = None,
		message: str | None = None,
		bpm_instance_id: str | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			request = SignatureService.create_request(
				document_id=document_id,
				document_title=document_title,
				initiator_id=initiator_id or record_ctx.get("actor_id", "system"),
				signatories_data=signatories_data or [],
				tenant_id=tenant_id,
				session=session,
				signing_order=signing_order,
				subject=subject,
				message=message,
				bpm_instance_id=bpm_instance_id or record_ctx.get("instance_id"),
			)
			SignatureService.send_request(request.id, session)
			return {"status": "ok", "request_id": request.id, "request_status": request.status}
		except Exception as exc:
			log.warning("bpm crm.sign.create_request failed: %s", exc)
			return {"status": "error", "message": str(exc)}

	@BPMActionRegistry.register(
		"crm.sign.check_status",
		"Check if signature request is complete",
	)
	def _bpm_check_status(
		record_ctx: dict,
		session: Any,
		request_id: str = "",
		**kw: Any,
	) -> dict:
		try:
			summary = SignatureService.get_request_status(request_id, session)
			return {
				"status": "ok",
				"request_id": request_id,
				"request_status": summary["status"],
				"is_complete": summary["status"] == "COMPLETED",
				"signatories": summary["signatories"],
			}
		except Exception as exc:
			log.warning("bpm crm.sign.check_status failed: %s", exc)
			return {"status": "error", "message": str(exc)}


_register_bpm_actions()


__all__ = [
	"SignatureService",
	"SignServiceError",
	"SignNotFoundError",
	"SignStateError",
]
