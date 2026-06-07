from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"RowSecurityPolicyCreatedEvent",
	"RowSecurityPolicyUpdatedEvent",
	"SecurityContextComputedEvent",
]


@dataclass
class RowSecurityPolicyCreatedEvent(DomainEvent):
	event_type: str = field(default="platform.row_security.policy.created", init=False)
	policy_id: str = ""
	entity_type: str = ""
	tenant_id: str = ""


@dataclass
class RowSecurityPolicyUpdatedEvent(DomainEvent):
	event_type: str = field(default="platform.row_security.policy.updated", init=False)
	policy_id: str = ""
	scope_field: str = ""
	allowed_count: int = 0


@dataclass
class SecurityContextComputedEvent(DomainEvent):
	event_type: str = field(default="platform.row_security.context.computed", init=False)
	user_id: str = ""
	entity_types: list = field(default_factory=list)
