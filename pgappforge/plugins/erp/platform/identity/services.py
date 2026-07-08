"""
pgappforge/plugins/erp/platform/identity/services.py

IdentityService — stateless service for IAM operations.

Responsibilities:
  - Identity provider CRUD
  - Session lifecycle (create, validate, expire, revoke)
  - MFA device management (register, verify, set_primary)
  - Access policy evaluation (ALLOW/DENY with explicit-deny override)
  - SoD-aware role assignment (delegates conflict check to GRC controls)

All methods accept an explicit SQLAlchemy Session.  No Flask context assumed.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)

_POLICY_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,300}$")
_PERMISSION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,99}$")
_PRINCIPAL_TYPES = {"USER", "ROLE", "GROUP"}
_POLICY_EFFECTS = {"ALLOW", "DENY"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class IdentityServiceError(Exception):
	"""Base error for Identity domain violations."""


class ProviderNotFoundError(IdentityServiceError):
	"""No IdentityProvider with the given id."""


class SessionNotFoundError(IdentityServiceError):
	"""No UserSession with the given token or id."""


class SessionExpiredError(IdentityServiceError):
	"""Session token is past its expires_at."""


class MFADeviceNotFoundError(IdentityServiceError):
	"""No MFADevice with the given id."""


class PolicyNotFoundError(IdentityServiceError):
	"""No AccessPolicy with the given id."""


class PolicyConflictError(IdentityServiceError):
	"""Duplicate policy_name."""


# ---------------------------------------------------------------------------
# IdentityService
# ---------------------------------------------------------------------------

class IdentityService:
	"""Stateless IAM service."""

	DEFAULT_SESSION_HOURS = 8
	DEFAULT_IDLE_MINUTES = 30

	# ------------------------------------------------------------------
	# Identity Provider
	# ------------------------------------------------------------------

	def create_provider(
		self,
		session: Any,
		tenant_id: str,
		name: str,
		provider_type: str,
		config: dict,
		is_default: bool = False,
	) -> dict:
		"""Create a new identity provider.

		If is_default=True and another default exists, the old default is
		cleared (only one default per tenant).
		"""
		from pgappforge.plugins.erp.platform.identity.models import IdentityProvider
		from pgappforge.plugins.erp.platform.identity.events import (
			IdentityProviderCreatedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		if provider_type not in ("SAML", "OIDC", "LDAP", "LOCAL"):
			raise IdentityServiceError(
				f"Invalid provider_type {provider_type!r}; "
				"must be SAML | OIDC | LDAP | LOCAL"
			)

		if is_default:
			# Clear existing defaults for this tenant
			existing_defaults = session.execute(
				select(IdentityProvider).where(
					IdentityProvider.tenant_id == tenant_id,
					IdentityProvider.is_default.is_(True),
				)
			).scalars().all()
			for ep in existing_defaults:
				ep.is_default = False

		provider = IdentityProvider(
			tenant_id=tenant_id,
			name=name,
			provider_type=provider_type,
			config=config,
			is_default=is_default,
			is_active=True,
		)
		session.add(provider)
		session.flush()

		emit_event(
			IdentityProviderCreatedEvent(
				aggregate_id=provider.id,
				aggregate_type="IdentityProvider",
				tenant_id=tenant_id,
				provider_id=provider.id,
				provider_type=provider_type,
				name=name,
			),
			session,
		)
		log.info("IdentityService: created provider %r type=%r", name, provider_type)
		return {"provider_id": provider.id, "status": "created"}

	def deactivate_provider(
		self, session: Any, provider_id: str, reason: str = ""
	) -> dict:
		"""Deactivate an identity provider."""
		from pgappforge.plugins.erp.platform.identity.models import IdentityProvider
		from pgappforge.plugins.erp.platform.identity.events import (
			IdentityProviderDeactivatedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		provider = session.get(IdentityProvider, provider_id)
		if provider is None:
			raise ProviderNotFoundError(f"IdentityProvider {provider_id!r} not found")
		provider.is_active = False
		emit_event(
			IdentityProviderDeactivatedEvent(
				aggregate_id=provider_id,
				aggregate_type="IdentityProvider",
				tenant_id=str(provider.tenant_id),
				provider_id=provider_id,
				reason=reason,
			),
			session,
		)
		return {"provider_id": provider_id, "status": "deactivated"}

	# ------------------------------------------------------------------
	# Session lifecycle
	# ------------------------------------------------------------------

	def create_session(
		self,
		session: Any,
		tenant_id: str,
		user_id: int,
		ip_address: str | None = None,
		user_agent: str | None = None,
		session_hours: int | None = None,
		mfa_required: bool = False,
	) -> dict:
		"""Create a new user session and return the session token.

		Returns: {"session_id": str, "session_token": str, "expires_at": str}
		"""
		from pgappforge.plugins.erp.platform.identity.models import UserSession
		from pgappforge.plugins.erp.platform.identity.events import UserSessionStartedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		hours = session_hours or self.DEFAULT_SESSION_HOURS
		now = datetime.now(timezone.utc)
		token = secrets.token_hex(32)  # 64 hex chars
		expires_at = now + timedelta(hours=hours)

		sess = UserSession(
			tenant_id=tenant_id,
			user_id=user_id,
			session_token=token,
			ip_address=ip_address,
			user_agent=user_agent,
			started_at=now,
			last_activity_at=now,
			expires_at=expires_at,
			mfa_verified=not mfa_required,
			is_active=True,
		)
		session.add(sess)
		session.flush()

		emit_event(
			UserSessionStartedEvent(
				aggregate_id=sess.id,
				aggregate_type="UserSession",
				tenant_id=tenant_id,
				session_id=sess.id,
				user_id=user_id,
				ip_address=ip_address or "",
				mfa_required=mfa_required,
			),
			session,
		)
		return {
			"session_id": sess.id,
			"session_token": token,
			"expires_at": expires_at.isoformat(),
			"mfa_required": mfa_required,
		}

	def validate_session(
		self,
		session: Any,
		token: str,
		touch: bool = True,
	) -> dict:
		"""Validate a session token; optionally update last_activity_at.

		Raises SessionExpiredError if past expires_at or is_active=False.
		Returns session metadata dict on success.
		"""
		from pgappforge.plugins.erp.platform.identity.models import UserSession

		row = session.execute(
			select(UserSession).where(UserSession.session_token == token)
		).scalar_one_or_none()

		if row is None:
			raise SessionNotFoundError("Session token not found")
		if not row.is_active:
			raise SessionExpiredError("Session has been revoked")

		now = datetime.now(timezone.utc)
		if row.expires_at < now:
			row.is_active = False
			raise SessionExpiredError("Session token has expired")

		if touch:
			row.last_activity_at = now

		return {
			"session_id": row.id,
			"user_id": row.user_id,
			"tenant_id": str(row.tenant_id),
			"mfa_verified": row.mfa_verified,
			"expires_at": row.expires_at.isoformat(),
		}

	def revoke_session(self, session: Any, session_id: str, reason: str = "") -> dict:
		"""Revoke a session by id."""
		from pgappforge.plugins.erp.platform.identity.models import UserSession
		from pgappforge.plugins.erp.platform.identity.events import UserSessionExpiredEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		sess = session.get(UserSession, session_id)
		if sess is None:
			raise SessionNotFoundError(f"UserSession {session_id!r} not found")
		sess.is_active = False
		emit_event(
			UserSessionExpiredEvent(
				aggregate_id=session_id,
				aggregate_type="UserSession",
				tenant_id=str(sess.tenant_id),
				session_id=session_id,
				user_id=sess.user_id,
				reason=reason or "REVOKED",
			),
			session,
		)
		return {"session_id": session_id, "status": "revoked"}

	# ------------------------------------------------------------------
	# MFA Device
	# ------------------------------------------------------------------

	def register_mfa_device(
		self,
		session: Any,
		tenant_id: str,
		user_id: int,
		device_type: str,
		device_name: str,
		secret_encrypted: str,
		is_primary: bool = False,
	) -> dict:
		"""Register an MFA device.

		If is_primary=True, demotes any existing primary device for user.
		"""
		from pgappforge.plugins.erp.platform.identity.models import MFADevice

		if device_type not in ("TOTP", "SMS", "EMAIL", "WEBAUTHN"):
			raise IdentityServiceError(
				f"Invalid device_type {device_type!r}; must be TOTP|SMS|EMAIL|WEBAUTHN"
			)

		if is_primary:
			existing_primary = session.execute(
				select(MFADevice).where(
					MFADevice.user_id == user_id,
					MFADevice.is_primary.is_(True),
				)
			).scalars().all()
			for ep in existing_primary:
				ep.is_primary = False

		device = MFADevice(
			tenant_id=tenant_id,
			user_id=user_id,
			device_type=device_type,
			device_name=device_name,
			secret_encrypted=secret_encrypted,
			is_primary=is_primary,
			verified_at=None,
		)
		session.add(device)
		session.flush()
		log.info(
			"IdentityService: registered MFA device %r type=%r for user=%d",
			device_name, device_type, user_id,
		)
		return {"device_id": device.id, "status": "registered", "verified": False}

	def verify_mfa_device(
		self,
		session: Any,
		device_id: str,
		session_id: str | None = None,
	) -> dict:
		"""Mark an MFA device as verified; optionally mark session mfa_verified."""
		from pgappforge.plugins.erp.platform.identity.models import MFADevice, UserSession
		from pgappforge.plugins.erp.platform.identity.events import MFADeviceVerifiedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		device = session.get(MFADevice, device_id)
		if device is None:
			raise MFADeviceNotFoundError(f"MFADevice {device_id!r} not found")

		now = datetime.now(timezone.utc)
		device.verified_at = now

		if session_id:
			sess = session.get(UserSession, session_id)
			if sess:
				sess.mfa_verified = True

		emit_event(
			MFADeviceVerifiedEvent(
				aggregate_id=device_id,
				aggregate_type="MFADevice",
				tenant_id=str(device.tenant_id),
				device_id=device_id,
				user_id=device.user_id,
				device_type=device.device_type,
			),
			session,
		)
		return {"device_id": device_id, "verified_at": now.isoformat()}

	# ------------------------------------------------------------------
	# Access Policy
	# ------------------------------------------------------------------

	def create_policy(
		self,
		session: Any,
		tenant_id: str,
		policy_name: str,
		resource_type: str,
		principal_type: str,
		principal_id: str,
		permissions: list[str],
		effect: str = "ALLOW",
		resource_id: str | None = None,
		conditions: dict | None = None,
	) -> dict:
		"""Create a new access policy."""
		from pgappforge.plugins.erp.platform.identity.models import AccessPolicy
		from pgappforge.plugins.erp.platform.identity.events import AccessPolicyCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		tenant_id = self._require_non_empty(tenant_id, "tenant_id")
		policy_name = self._validate_policy_name(policy_name)
		resource_type = self._validate_resource_type(resource_type)
		resource_id = self._optional_non_empty(resource_id, "resource_id")
		principal_type = self._normalize_choice(
			principal_type,
			_PRINCIPAL_TYPES,
			"principal_type",
		)
		principal_id = self._require_non_empty(principal_id, "principal_id")
		permissions = self._normalize_permissions(permissions)
		effect = self._normalize_choice(effect, _POLICY_EFFECTS, "effect")
		if conditions is not None and not isinstance(conditions, dict):
			raise IdentityServiceError("conditions must be a JSON object")

		# Check for duplicate policy_name
		existing = session.execute(
			select(AccessPolicy).where(
				AccessPolicy.tenant_id == tenant_id,
				AccessPolicy.policy_name == policy_name,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise PolicyConflictError(
				f"AccessPolicy with name {policy_name!r} already exists"
			)

		policy = AccessPolicy(
			tenant_id=tenant_id,
			policy_name=policy_name,
			resource_type=resource_type,
			resource_id=resource_id,
			principal_type=principal_type,
			principal_id=principal_id,
			permissions=permissions,
			conditions=conditions or {},
			effect=effect,
			is_active=True,
		)
		session.add(policy)
		session.flush()

		emit_event(
			AccessPolicyCreatedEvent(
				aggregate_id=policy.id,
				aggregate_type="AccessPolicy",
				tenant_id=tenant_id,
				policy_id=policy.id,
				policy_name=policy_name,
				effect=effect,
				principal_type=principal_type,
				principal_id=principal_id,
			),
			session,
		)
		return {"policy_id": policy.id, "status": "created"}

	@staticmethod
	def _require_non_empty(value: Any, field_name: str) -> str:
		text = str(value or "").strip()
		if not text:
			raise IdentityServiceError(f"{field_name} is required")
		return text

	@staticmethod
	def _optional_non_empty(value: Any, field_name: str) -> str | None:
		if value is None:
			return None
		return IdentityService._require_non_empty(value, field_name)

	@staticmethod
	def _validate_policy_name(value: str) -> str:
		text = IdentityService._require_non_empty(value, "policy_name")
		if not _POLICY_NAME_RE.fullmatch(text):
			raise IdentityServiceError(
				"policy_name must contain only letters, numbers, _, ., :, or -"
			)
		return text

	@staticmethod
	def _validate_resource_type(value: str) -> str:
		text = IdentityService._require_non_empty(value, "resource_type")
		if text == "*":
			return text
		if not _POLICY_NAME_RE.fullmatch(text):
			raise IdentityServiceError(
				"resource_type must be '*' or a dotted resource identifier"
			)
		return text

	@staticmethod
	def _normalize_permissions(permissions: Any) -> list[str]:
		if isinstance(permissions, (str, bytes)) or not isinstance(permissions, (list, tuple, set)):
			raise IdentityServiceError("permissions must be a list of action strings")
		normalized: list[str] = []
		for permission in permissions:
			text = str(permission or "").strip()
			if text == "*":
				normalized.append(text)
				continue
			if not _PERMISSION_RE.fullmatch(text):
				raise IdentityServiceError(f"Invalid permission {permission!r}")
			normalized.append(text)
		normalized = list(dict.fromkeys(normalized))
		if not normalized:
			raise IdentityServiceError("permissions cannot be empty")
		return normalized

	@staticmethod
	def _normalize_choice(value: str, allowed: set[str], field_name: str) -> str:
		text = IdentityService._require_non_empty(value, field_name).upper()
		if text not in allowed:
			allowed_text = "|".join(sorted(allowed))
			raise IdentityServiceError(
				f"{field_name} must be {allowed_text}, got {value!r}"
			)
		return text

	def evaluate_access(
		self,
		session: Any,
		tenant_id: str,
		principal_type: str,
		principal_id: str,
		resource_type: str,
		action: str,
		resource_id: str | None = None,
	) -> dict:
		"""Evaluate whether a principal has access to perform action on resource.

		Algorithm: collect all matching policies; explicit DENY wins over ALLOW.
		Returns {"allowed": bool, "reason": str, "matched_policies": list[str]}
		"""
		from pgappforge.plugins.erp.platform.identity.models import AccessPolicy
		from sqlalchemy.dialects.postgresql import ARRAY

		q = select(AccessPolicy).where(
			AccessPolicy.tenant_id == tenant_id,
			AccessPolicy.principal_type == principal_type,
			AccessPolicy.principal_id == principal_id,
			AccessPolicy.resource_type.in_([resource_type, "*"]),
			AccessPolicy.is_active.is_(True),
		)
		if resource_id:
			q = q.where(
				sa.or_(
					AccessPolicy.resource_id == resource_id,
					AccessPolicy.resource_id.is_(None),
				)
			)
		else:
			q = q.where(AccessPolicy.resource_id.is_(None))

		policies = session.execute(q).scalars().all()

		deny_policies = []
		allow_policies = []

		for p in policies:
			if action in (p.permissions or []) or "*" in (p.permissions or []):
				if p.effect == "DENY":
					deny_policies.append(p.policy_name)
				else:
					allow_policies.append(p.policy_name)

		if deny_policies:
			return {
				"allowed": False,
				"reason": "Explicit DENY policy matched",
				"matched_policies": deny_policies,
			}
		if allow_policies:
			return {
				"allowed": True,
				"reason": "ALLOW policy matched",
				"matched_policies": allow_policies,
			}
		return {
			"allowed": False,
			"reason": "No matching policy (implicit deny)",
			"matched_policies": [],
		}


__all__ = [
	"IdentityService",
	"IdentityServiceError",
	"ProviderNotFoundError",
	"SessionNotFoundError",
	"SessionExpiredError",
	"MFADeviceNotFoundError",
	"PolicyNotFoundError",
	"PolicyConflictError",
]
