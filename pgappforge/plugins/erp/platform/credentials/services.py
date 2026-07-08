"""
pgappforge/plugins/erp/platform/credentials/services.py

CredentialsService — W3C Verifiable Credentials + Open Badges 3.0 operations.

Responsibilities:
  - Issue credentials (generates number, verification URL, QR code, VC JWT stub)
  - Verify credentials by token or URL fragment
  - Revoke credentials (status=REVOKED; IMMUTABLE otherwise)
  - Share credentials to LinkedIn via Share API
  - Generate full credential transcript for a recipient
  - Bulk-issue from a list of recipient dicts

All methods accept an explicit SQLAlchemy Session.  No Flask context assumed.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_VERIFICATION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_LINKEDIN_BEARER_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/=-]{16,4096}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")
_MAX_LINKEDIN_RESPONSE_BYTES = 64 * 1024
_MAX_LINKEDIN_COMMENTARY_CHARS = 2800
_MAX_LINKEDIN_TITLE_CHARS = 200
_MAX_LINKEDIN_DESCRIPTION_CHARS = 200
_MAX_SHARE_URL_CHARS = 2048


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class CredentialsServiceError(Exception):
	"""Base error for Credentials domain violations."""


class SchemaNotFoundError(CredentialsServiceError):
	"""No CredentialSchema with the given id."""


class CredentialNotFoundError(CredentialsServiceError):
	"""No IssuedCredential with the given id or token."""


class CredentialAlreadyRevokedError(CredentialsServiceError):
	"""Credential is already revoked."""


class CredentialImmutableError(CredentialsServiceError):
	"""Attempt to mutate an immutable issued credential field."""


# ---------------------------------------------------------------------------
# CredentialsService
# ---------------------------------------------------------------------------

class CredentialsService:
	"""Stateless service for digital credential lifecycle management."""

	# ------------------------------------------------------------------
	# Issue
	# ------------------------------------------------------------------

	def issue_credential(
		self,
		session: Any,
		tenant_id: str,
		schema_id: str,
		recipient_id: str,
		recipient_email: str,
		evidence: dict | None = None,
		narrative: str | None = None,
		expires_at: datetime | None = None,
		base_url: str = "https://credentials.example.com",
	) -> Any:
		"""Issue a credential to a recipient.

		Steps:
		  1. Load CredentialSchema; validate is_published.
		  2. Generate unique credential_number (seq-based slug).
		  3. Generate verification_url using a UUID token.
		  4. Generate QR code URL (points to verification portal).
		  5. Build W3C VC JWT stub (signing is caller's KMS responsibility).
		  6. Persist IssuedCredential.
		  7. Emit CredentialIssuedEvent.

		Returns the IssuedCredential ORM object (not yet committed; caller commits).
		"""
		from pgappforge.plugins.erp.platform.credentials.models import (
			CredentialSchema, IssuedCredential,
		)
		from pgappforge.plugins.erp.platform.credentials.events import CredentialIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		tenant_id = self._require_non_empty(tenant_id, "tenant_id")
		schema_id = self._require_non_empty(schema_id, "schema_id")
		recipient_id = self._require_non_empty(recipient_id, "recipient_id")
		recipient_email = self._validate_email(recipient_email, "recipient_email")
		evidence = self._validate_mapping(evidence, "evidence")
		base_url = self._validate_base_url(base_url)
		if expires_at is not None:
			self._validate_future_datetime(expires_at, "expires_at")

		schema = session.get(CredentialSchema, schema_id)
		if schema is None:
			raise SchemaNotFoundError(f"CredentialSchema {schema_id!r} not found")
		if not schema.is_published:
			raise CredentialsServiceError(
				f"CredentialSchema {schema_id!r} is not published"
			)

		now = datetime.now(timezone.utc)
		year = now.year
		credential_number = self._generate_credential_number(session, schema, year)
		verification_token = secrets.token_urlsafe(32)
		verification_url = f"{base_url}/verify/{verification_token}"
		qr_code_url = (
			f"{base_url}/qr/{verification_token}.png"
		)

		# W3C VC JWT stub (unsigned; KMS layer signs in production)
		vc_payload = self._build_vc_payload(
			credential_number=credential_number,
			schema=schema,
			recipient_id=recipient_id,
			recipient_email=recipient_email,
			issued_at=now,
			expires_at=expires_at,
			evidence=evidence,
			narrative=narrative or "",
			verification_url=verification_url,
		)
		vc_jwt_stub = self._encode_vc_jwt_stub(vc_payload)

		credential = IssuedCredential(
			tenant_id=tenant_id,
			credential_number=credential_number,
			schema_id=schema_id,
			recipient_id=recipient_id,
			recipient_email=recipient_email,
			issued_at=now,
			expires_at=expires_at,
			evidence=evidence,
			narrative=narrative,
			achievement_id=f"{base_url}/achievements/{schema.schema_id}",
			verification_url=verification_url,
			qr_code_url=qr_code_url,
			vc_jwt=vc_jwt_stub,
			status="ACTIVE",
		)
		session.add(credential)
		session.flush()

		emit_event(
			CredentialIssuedEvent(
				aggregate_id=credential.id,
				aggregate_type="IssuedCredential",
				tenant_id=tenant_id,
				credential_id=credential.id,
				credential_number=credential_number,
				schema_id=schema_id,
				recipient_id=recipient_id,
				recipient_email=recipient_email,
				verification_url=verification_url,
			),
			session,
		)
		log.info(
			"CredentialsService: issued %r to %r",
			credential_number, recipient_email,
		)
		return credential

	@staticmethod
	def _require_non_empty(value: Any, field_name: str) -> str:
		text = str(value or "").strip()
		if not text:
			raise CredentialsServiceError(f"{field_name} is required")
		return text

	@staticmethod
	def _validate_email(value: str, field_name: str) -> str:
		text = CredentialsService._require_non_empty(value, field_name)
		if not _EMAIL_RE.fullmatch(text):
			raise CredentialsServiceError(f"{field_name} must be a valid email address")
		return text

	@staticmethod
	def _validate_mapping(value: Any, field_name: str) -> dict:
		if value is None:
			return {}
		if not isinstance(value, dict):
			raise CredentialsServiceError(f"{field_name} must be a JSON object")
		return dict(value)

	@staticmethod
	def _validate_base_url(value: str) -> str:
		text = CredentialsService._require_non_empty(value, "base_url").rstrip("/")
		parsed = urlparse(text)
		if parsed.scheme != "https" or not parsed.netloc:
			raise CredentialsServiceError("base_url must be an absolute HTTPS URL")
		return text

	@staticmethod
	def _validate_linkedin_access_token(value: Any) -> str:
		token = CredentialsService._require_non_empty(value, "access_token")
		if token.lower().startswith("bearer "):
			raise CredentialsServiceError(
				"access_token must be the raw OAuth bearer token without a prefix"
			)
		if not _LINKEDIN_BEARER_TOKEN_RE.fullmatch(token):
			raise CredentialsServiceError(
				"access_token contains unsupported bearer token characters"
			)
		return token

	@staticmethod
	def _validate_linkedin_share_url(value: Any) -> str:
		url = CredentialsService._require_non_empty(value, "verification_url")
		if len(url) > _MAX_SHARE_URL_CHARS:
			raise CredentialsServiceError("verification_url is too long to share")
		parsed = urlparse(url)
		if parsed.scheme != "https" or not parsed.netloc:
			raise CredentialsServiceError("verification_url must be an absolute HTTPS URL")
		if parsed.username or parsed.password:
			raise CredentialsServiceError("verification_url cannot include credentials")
		if parsed.fragment:
			raise CredentialsServiceError("verification_url cannot include a fragment")
		hostname = (parsed.hostname or "").strip().lower()
		if not hostname or hostname == "localhost" or hostname.endswith(".localhost"):
			raise CredentialsServiceError("verification_url must use a public host")
		try:
			ipaddress.ip_address(hostname.strip("[]"))
		except ValueError:
			return url
		raise CredentialsServiceError("verification_url cannot use an IP literal host")

	@staticmethod
	def _linkedin_text(value: Any, max_chars: int, *, default: str = "") -> str:
		text = str(value if value is not None else default)
		text = _CONTROL_CHAR_RE.sub(" ", text)
		text = re.sub(r"\s+", " ", text).strip()
		if not text:
			text = default
		return text[:max_chars]

	@staticmethod
	def _read_limited_json_object_response(resp: Any, context: str) -> dict[str, Any]:
		payload = resp.read(_MAX_LINKEDIN_RESPONSE_BYTES + 1)
		if len(payload) > _MAX_LINKEDIN_RESPONSE_BYTES:
			raise CredentialsServiceError(f"{context} response is too large")
		data = json.loads(payload or b"{}")
		if not isinstance(data, dict):
			raise CredentialsServiceError(f"{context} response must be a JSON object")
		return data

	@staticmethod
	def _validate_future_datetime(value: datetime, field_name: str) -> None:
		if not isinstance(value, datetime):
			raise CredentialsServiceError(f"{field_name} must be a datetime")
		comparable = value
		if comparable.tzinfo is None:
			comparable = comparable.replace(tzinfo=timezone.utc)
		if comparable <= datetime.now(timezone.utc):
			raise CredentialsServiceError(f"{field_name} must be in the future")

	def _generate_credential_number(
		self,
		session: Any,
		schema: Any,
		year: int,
	) -> str:
		"""Generate a unique sequential credential number."""
		from pgappforge.plugins.erp.platform.credentials.models import IssuedCredential

		prefix_map = {
			"CERTIFICATE": "CERT",
			"BADGE": "BADGE",
			"LICENSE": "LIC",
			"DEGREE": "DEG",
			"MEMBERSHIP": "MBR",
			"AWARD": "AWD",
		}
		prefix = prefix_map.get(schema.credential_type, "CRED")
		count = session.execute(
			sa.select(func.count()).select_from(IssuedCredential).where(
				IssuedCredential.schema_id == schema.id,
			)
		).scalar_one()
		seq = str(count + 1).zfill(5)
		return f"{prefix}-{year}-{seq}"

	def _build_vc_payload(
		self,
		credential_number: str,
		schema: Any,
		recipient_id: str,
		recipient_email: str,
		issued_at: datetime,
		expires_at: datetime | None,
		evidence: dict,
		narrative: str,
		verification_url: str,
	) -> dict:
		"""Build a W3C Verifiable Credential JSON-LD payload."""
		vc: dict[str, Any] = {
			"@context": [
				"https://www.w3.org/2018/credentials/v1",
				"https://purl.imsglobal.org/spec/ob/v3p0/context.json",
			],
			"type": ["VerifiableCredential", "OpenBadgeCredential"],
			"id": verification_url,
			"issuer": str(schema.issuer_id),
			"issuanceDate": issued_at.isoformat(),
			"name": schema.name,
			"credentialSubject": {
				"id": f"mailto:{recipient_email}",
				"type": ["AchievementSubject"],
				"achievement": {
					"id": f"urn:credential:{credential_number}",
					"type": ["Achievement"],
					"name": schema.name,
					"description": schema.description or "",
					"criteria": {"narrative": schema.criteria_narrative or ""},
					"image": {"id": schema.image_url or ""},
				},
				"narrative": narrative,
				"evidence": evidence,
			},
		}
		if expires_at:
			vc["expirationDate"] = expires_at.isoformat()
		if schema.alignment:
			vc["credentialSubject"]["achievement"]["alignment"] = schema.alignment
		return vc

	def _encode_vc_jwt_stub(self, payload: dict) -> str:
		"""Produce an unsigned VC JWT stub (header.payload.UNSIGNED).

		In production, replace the signature with a real JWS over the
		base64url-encoded payload using the issuer's private key.
		"""
		import base64
		import json as _json

		def _b64url(data: dict) -> str:
			return base64.urlsafe_b64encode(
				_json.dumps(data, separators=(",", ":")).encode()
			).rstrip(b"=").decode()

		header = {"alg": "none", "typ": "JWT", "cty": "vc+ld+json"}
		return f"{_b64url(header)}.{_b64url(payload)}."

	# ------------------------------------------------------------------
	# Verify
	# ------------------------------------------------------------------

	def verify_credential(
		self,
		session: Any,
		tenant_id: str,
		verification_token: str,
		verifier_id: str | None = None,
		verifier_email: str | None = None,
	) -> Any:
		"""Verify a credential by its verification URL token.

		Checks:
		  1. Token resolves to an IssuedCredential.
		  2. Status is ACTIVE.
		  3. expires_at is not in the past (if set).

		Records a CredentialVerification row regardless of outcome.
		Returns the CredentialVerification ORM object.
		"""
		from pgappforge.plugins.erp.platform.credentials.models import (
			IssuedCredential, CredentialVerification,
		)
		from pgappforge.plugins.erp.platform.credentials.events import CredentialVerifiedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		tenant_id = self._normalize_optional_text(tenant_id, "tenant_id")
		token = self._extract_verification_token(verification_token)
		verifier_id = self._normalize_optional_text(verifier_id, "verifier_id")
		if verifier_email is not None:
			verifier_email = self._validate_email(verifier_email, "verifier_email")

		verify_suffix = f"/verify/{token}"
		credential = session.execute(
			select(IssuedCredential).where(
				sa.or_(
					IssuedCredential.verification_url == token,
					IssuedCredential.verification_url.endswith(verify_suffix),
				)
			)
		).scalar_one_or_none()

		now = datetime.now(timezone.utc)

		if credential is None:
			result = "NOT_FOUND"
			credential_id = None
		elif credential.status == "REVOKED":
			result = "REVOKED"
			credential_id = credential.id
		elif credential.expires_at and self._as_aware_datetime(credential.expires_at) < now:
			result = "EXPIRED"
			credential_id = credential.id
			# Lazily update status
			credential.status = "EXPIRED"
		elif credential.status == "ACTIVE":
			result = "VALID"
			credential_id = credential.id
		else:
			result = "INVALID"
			credential_id = credential.id

		details: dict[str, Any] = {
			"token": token,
			"checked_at": now.isoformat(),
			"result": result,
		}
		if credential is not None:
			details["credential_number"] = credential.credential_number
			details["issued_at"] = credential.issued_at.isoformat()
			details["schema_id"] = str(credential.schema_id)

		verification = CredentialVerification(
			tenant_id=str(credential.tenant_id) if credential is not None else tenant_id,
			credential_id=credential_id,
			verification_token=token,
			verified_at=now,
			verifier_id=verifier_id,
			verifier_email=verifier_email,
			result=result,
			verification_details=details,
		)
		session.add(verification)
		session.flush()

		emit_event(
			CredentialVerifiedEvent(
				aggregate_id=verification.id,
				aggregate_type="CredentialVerification",
				tenant_id=tenant_id,
				credential_id=str(credential_id) if credential_id else "",
				verification_id=verification.id,
				result=result,
				verifier_email=verifier_email or "",
			),
			session,
		)
		log.info(
			"CredentialsService: verified token=%r result=%r",
			token, result,
		)
		return verification

	@staticmethod
	def _normalize_optional_text(value: Any, field_name: str) -> str | None:
		if value is None:
			return None
		text = str(value).strip()
		if not text:
			return None
		if len(text) > 100:
			raise CredentialsServiceError(f"{field_name} cannot exceed 100 characters")
		return text

	@staticmethod
	def _extract_verification_token(value: Any) -> str:
		text = CredentialsService._require_non_empty(value, "verification_token")
		parsed = urlparse(text)
		path = parsed.path if parsed.scheme or parsed.netloc else text
		token = path.rstrip("/").split("/")[-1].strip()
		if not _VERIFICATION_TOKEN_RE.fullmatch(token):
			raise CredentialsServiceError("verification_token is malformed")
		return token

	@staticmethod
	def _as_aware_datetime(value: datetime) -> datetime:
		if value.tzinfo is None:
			return value.replace(tzinfo=timezone.utc)
		return value.astimezone(timezone.utc)

	# ------------------------------------------------------------------
	# Revoke
	# ------------------------------------------------------------------

	def revoke_credential(
		self,
		session: Any,
		credential_id: str,
		reason: str,
	) -> Any:
		"""Revoke an issued credential.

		Sets status=REVOKED, revoked_at=now(), revocation_reason.
		All other fields remain unchanged (immutability of issuance data).
		Returns the updated IssuedCredential.
		"""
		from pgappforge.plugins.erp.platform.credentials.models import IssuedCredential
		from pgappforge.plugins.erp.platform.credentials.events import CredentialRevokedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		credential_id = self._require_non_empty(credential_id, "credential_id")
		reason = self._require_non_empty(reason, "reason")

		credential = session.get(IssuedCredential, credential_id)
		if credential is None:
			raise CredentialNotFoundError(f"IssuedCredential {credential_id!r} not found")
		if credential.status == "REVOKED":
			raise CredentialAlreadyRevokedError(
				f"Credential {credential.credential_number!r} is already revoked"
			)

		now = datetime.now(timezone.utc)
		credential.status = "REVOKED"
		credential.revoked_at = now
		credential.revocation_reason = reason
		session.flush()

		emit_event(
			CredentialRevokedEvent(
				aggregate_id=credential_id,
				aggregate_type="IssuedCredential",
				tenant_id=str(credential.tenant_id),
				credential_id=credential_id,
				credential_number=credential.credential_number,
				recipient_id=str(credential.recipient_id),
				revocation_reason=reason,
			),
			session,
		)
		log.info(
			"CredentialsService: revoked %r reason=%r",
			credential.credential_number, reason,
		)
		return credential

	# ------------------------------------------------------------------
	# LinkedIn share
	# ------------------------------------------------------------------

	def share_to_linkedin(
		self,
		session: Any,
		tenant_id: str,
		credential_id: str,
		access_token: str,
	) -> dict:
		"""Share a credential to LinkedIn using the Share API.

		Creates a CredentialShare record then POSTs to LinkedIn's UGC API.
		Returns {"share_url": str, "share_id": str, "linkedin_post_id": str}

		access_token: OAuth 2.0 bearer token with w_member_social scope.
		The LinkedIn API call is best-effort; share record is created regardless.
		"""
		from pgappforge.plugins.erp.platform.credentials.models import (
			IssuedCredential, CredentialSchema, CredentialShare,
		)
		from pgappforge.plugins.erp.platform.credentials.events import CredentialSharedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		tenant_id = self._require_non_empty(tenant_id, "tenant_id")
		credential_id = self._require_non_empty(credential_id, "credential_id")
		access_token = self._validate_linkedin_access_token(access_token)

		credential = session.get(IssuedCredential, credential_id)
		if credential is None:
			raise CredentialNotFoundError(f"IssuedCredential {credential_id!r} not found")
		if str(credential.tenant_id) != tenant_id:
			raise CredentialNotFoundError(f"IssuedCredential {credential_id!r} not found")
		if credential.status != "ACTIVE":
			raise CredentialsServiceError(
				f"Cannot share credential with status={credential.status!r}"
			)

		schema = session.get(CredentialSchema, credential.schema_id)
		share_url = self._validate_linkedin_share_url(credential.verification_url)
		schema_name = self._linkedin_text(
			schema.name if schema else "credential",
			_MAX_LINKEDIN_TITLE_CHARS,
			default="credential",
		)
		schema_description = self._linkedin_text(
			schema.description if schema else "",
			_MAX_LINKEDIN_DESCRIPTION_CHARS,
		)
		commentary = self._linkedin_text(
			f"I earned the {schema_name}! Verify: {share_url}",
			_MAX_LINKEDIN_COMMENTARY_CHARS,
		)

		share_token = secrets.token_hex(32)
		share = CredentialShare(
			tenant_id=tenant_id,
			credential_id=credential_id,
			share_token=share_token,
			platform="LINKEDIN",
			view_count=0,
		)
		session.add(share)
		session.flush()

		# LinkedIn UGC API call
		linkedin_post_id = ""
		try:
			import urllib.request

			ugc_payload = json.dumps({
				"author": "urn:li:person:me",
				"lifecycleState": "PUBLISHED",
				"specificContent": {
					"com.linkedin.ugc.ShareContent": {
						"shareCommentary": {
							"text": commentary
						},
						"shareMediaCategory": "ARTICLE",
						"media": [{
							"status": "READY",
							"originalUrl": share_url,
							"title": {"text": schema_name},
							"description": {"text": schema_description},
						}],
					}
				},
				"visibility": {
					"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
				},
			}).encode()

			req = urllib.request.Request(
				"https://api.linkedin.com/v2/ugcPosts",
				data=ugc_payload,
				headers={
					"Authorization": f"Bearer {access_token}",
					"Content-Type": "application/json",
					"X-Restli-Protocol-Version": "2.0.0",
				},
				method="POST",
			)
			with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
				if getattr(resp, "status", 200) >= 300:
					raise CredentialsServiceError(
						f"LinkedIn share API returned HTTP {resp.status}"
					)
				response_data = self._read_limited_json_object_response(
					resp,
					"LinkedIn share API",
				)
				linkedin_post_id = self._linkedin_text(
					response_data.get("id", ""),
					128,
				)
		except Exception as exc:
			log.warning(
				"CredentialsService: LinkedIn share API call failed: %s", exc
			)

		emit_event(
			CredentialSharedEvent(
				aggregate_id=share.id,
				aggregate_type="CredentialShare",
				tenant_id=tenant_id,
				credential_id=credential_id,
				share_id=share.id,
				platform="LINKEDIN",
				recipient_email="",
			),
			session,
		)
		return {
			"share_url": share_url,
			"share_id": share.id,
			"share_token": share_token,
			"linkedin_post_id": linkedin_post_id,
		}

	# ------------------------------------------------------------------
	# Transcript
	# ------------------------------------------------------------------

	def generate_transcript(
		self,
		session: Any,
		recipient_id: str,
		include_revoked: bool = False,
	) -> list[dict]:
		"""Generate a full credential transcript for a recipient.

		Returns all ACTIVE credentials (and optionally REVOKED) ordered by
		issued_at descending, with schema metadata included.
		"""
		from pgappforge.plugins.erp.platform.credentials.models import (
			IssuedCredential, CredentialSchema,
		)

		q = (
			select(IssuedCredential, CredentialSchema)
			.join(CredentialSchema, CredentialSchema.id == IssuedCredential.schema_id)
			.where(IssuedCredential.recipient_id == recipient_id)
			.order_by(IssuedCredential.issued_at.desc())
		)
		if not include_revoked:
			q = q.where(IssuedCredential.status == "ACTIVE")

		rows = session.execute(q).all()
		return [
			{
				"credential_id": str(cred.id),
				"credential_number": cred.credential_number,
				"credential_type": schema.credential_type,
				"schema_name": schema.name,
				"schema_version": schema.version,
				"issued_at": cred.issued_at.isoformat(),
				"expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
				"status": cred.status,
				"verification_url": cred.verification_url,
				"qr_code_url": cred.qr_code_url,
				"narrative": cred.narrative,
				"image_url": schema.image_url,
				"issuer_id": str(schema.issuer_id),
			}
			for cred, schema in rows
		]

	# ------------------------------------------------------------------
	# Bulk issue
	# ------------------------------------------------------------------

	def bulk_issue(
		self,
		session: Any,
		tenant_id: str,
		schema_id: str,
		recipients: list[dict],
		base_url: str = "https://credentials.example.com",
	) -> list[Any]:
		"""Issue credentials to multiple recipients in one operation.

		Each item in recipients must have: recipient_id, recipient_email.
		Optional per-recipient keys: evidence (dict), narrative (str),
		expires_at (datetime).

		Returns list of IssuedCredential objects (failures are logged and
		excluded; partial success is normal).

		Emits BulkIssueCompletedEvent after all attempts.
		"""
		from pgappforge.plugins.erp.platform.credentials.events import BulkIssueCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		issued: list[Any] = []
		failed_emails: list[str] = []

		for rec in recipients:
			recipient_id = rec.get("recipient_id", "")
			recipient_email = rec.get("recipient_email", "")
			try:
				credential = self.issue_credential(
					session=session,
					tenant_id=tenant_id,
					schema_id=schema_id,
					recipient_id=recipient_id,
					recipient_email=recipient_email,
					evidence=rec.get("evidence"),
					narrative=rec.get("narrative"),
					expires_at=rec.get("expires_at"),
					base_url=base_url,
				)
				issued.append(credential)
			except Exception as exc:
				log.warning(
					"CredentialsService.bulk_issue: failed for %r: %s",
					recipient_email, exc,
				)
				failed_emails.append(recipient_email)

		emit_event(
			BulkIssueCompletedEvent(
				aggregate_id=schema_id,
				aggregate_type="CredentialSchema",
				tenant_id=tenant_id,
				schema_id=schema_id,
				issued_count=len(issued),
				failed_count=len(failed_emails),
				failed_emails=failed_emails,
			),
			session,
		)
		log.info(
			"CredentialsService.bulk_issue: schema=%r issued=%d failed=%d",
			schema_id, len(issued), len(failed_emails),
		)
		return issued


__all__ = [
	"CredentialsService",
	"CredentialsServiceError",
	"SchemaNotFoundError",
	"CredentialNotFoundError",
	"CredentialAlreadyRevokedError",
	"CredentialImmutableError",
]
