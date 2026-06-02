"""
pgappforge/plugins/erp/platform/identity/events.py

Identity plugin domain events.

Events emitted:
  identity.provider.created
  identity.provider.deactivated
  identity.session.started
  identity.session.expired
  identity.mfa.device_verified
  identity.mfa.challenge_failed
  identity.policy.created
  identity.policy.changed

Events consumed:
  (none from upstream — identity is a platform-level concern)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class IdentityProviderCreatedEvent(DomainEvent):
	event_type: str = "identity.provider.created"
	provider_id: str = ""
	provider_type: str = ""
	name: str = ""


@dataclass
class IdentityProviderDeactivatedEvent(DomainEvent):
	event_type: str = "identity.provider.deactivated"
	provider_id: str = ""
	reason: str = ""


@dataclass
class UserSessionStartedEvent(DomainEvent):
	event_type: str = "identity.session.started"
	session_id: str = ""
	user_id: int = 0
	ip_address: str = ""
	mfa_required: bool = False


@dataclass
class UserSessionExpiredEvent(DomainEvent):
	event_type: str = "identity.session.expired"
	session_id: str = ""
	user_id: int = 0
	reason: str = ""  # TIMEOUT | LOGOUT | REVOKED


@dataclass
class MFADeviceVerifiedEvent(DomainEvent):
	event_type: str = "identity.mfa.device_verified"
	device_id: str = ""
	user_id: int = 0
	device_type: str = ""


@dataclass
class MFAChallengeFailedEvent(DomainEvent):
	event_type: str = "identity.mfa.challenge_failed"
	user_id: int = 0
	device_type: str = ""
	ip_address: str = ""
	attempt_count: int = 0


@dataclass
class AccessPolicyCreatedEvent(DomainEvent):
	event_type: str = "identity.policy.created"
	policy_id: str = ""
	policy_name: str = ""
	effect: str = ""
	principal_type: str = ""
	principal_id: str = ""


@dataclass
class AccessPolicyChangedEvent(DomainEvent):
	event_type: str = "identity.policy.changed"
	policy_id: str = ""
	policy_name: str = ""
	changed_fields: list = None

	def __post_init__(self):
		if self.changed_fields is None:
			self.changed_fields = []


__all__ = [
	"IdentityProviderCreatedEvent",
	"IdentityProviderDeactivatedEvent",
	"UserSessionStartedEvent",
	"UserSessionExpiredEvent",
	"MFADeviceVerifiedEvent",
	"MFAChallengeFailedEvent",
	"AccessPolicyCreatedEvent",
	"AccessPolicyChangedEvent",
]
