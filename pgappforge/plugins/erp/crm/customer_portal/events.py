"""
pgappforge/plugins/erp/crm/customer_portal/events.py

Domain events for the Customer Self-Service Portal plugin.

Events emitted
--------------
  crm.customer_portal.registered          — new portal user registered
  crm.customer_portal.login               — successful portal login
  crm.customer_portal.payment.initiated   — payment initiated from self-service
  crm.customer_portal.statement.downloaded — account statement downloaded
  crm.customer_portal.password.reset      — password reset completed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class CustomerPortalRegisteredEvent(DomainEvent):
	"""Emitted when a customer completes portal self-registration."""
	event_type: str = "crm.customer_portal.registered"
	user_id: str = ""
	customer_id: str = ""
	email: str = ""
	tenant_id: str = ""


@dataclass
class CustomerPortalLoginEvent(DomainEvent):
	"""Emitted on each successful portal authentication."""
	event_type: str = "crm.customer_portal.login"
	user_id: str = ""
	customer_id: str = ""
	ip_address: str = ""


@dataclass
class PortalPaymentInitiatedEvent(DomainEvent):
	"""Emitted when a customer submits a payment from the self-service portal."""
	event_type: str = "crm.customer_portal.payment.initiated"
	payment_id: str = ""
	customer_id: str = ""
	amount_cents: int = 0
	method: str = ""


@dataclass
class PortalStatementDownloadedEvent(DomainEvent):
	"""Emitted when a customer downloads an account statement."""
	event_type: str = "crm.customer_portal.statement.downloaded"
	customer_id: str = ""
	from_date: str = ""     # ISO date string
	to_date: str = ""       # ISO date string


@dataclass
class PortalPasswordResetEvent(DomainEvent):
	"""Emitted when a portal password reset is completed."""
	event_type: str = "crm.customer_portal.password.reset"
	user_id: str = ""
	customer_id: str = ""


__all__ = [
	"CustomerPortalRegisteredEvent",
	"CustomerPortalLoginEvent",
	"PortalPaymentInitiatedEvent",
	"PortalStatementDownloadedEvent",
	"PortalPasswordResetEvent",
]
