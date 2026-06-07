"""
pgappforge/plugins/erp/platform/tenant_control/events.py

Domain events for the Tenant Control plugin.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"TenantProvisionedEvent",
	"TenantSuspendedEvent",
	"PlanLimitBreachEvent",
]


@dataclass
class TenantProvisionedEvent(DomainEvent):
	"""Emitted when a new tenant is provisioned."""
	event_type: str = "platform.tenant.provisioned"
	tenant_id: str = ""
	name: str = ""
	plan_tier: str = ""


@dataclass
class TenantSuspendedEvent(DomainEvent):
	"""Emitted when a tenant is suspended (non-payment, abuse, etc.)."""
	event_type: str = "platform.tenant.suspended"
	tenant_id: str = ""
	reason: str = ""


@dataclass
class PlanLimitBreachEvent(DomainEvent):
	"""Emitted when a tenant exceeds a plan resource limit."""
	event_type: str = "platform.tenant.plan_limit_breach"
	tenant_id: str = ""
	resource: str = ""
	limit_value: int = 0
	actual_value: int = 0
