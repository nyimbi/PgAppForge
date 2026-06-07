from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class ServiceContractCreatedEvent(DomainEvent):
	event_type: str = "crm.service_contracts.created"
	contract_id: str = ""
	customer_id: str = ""
	value_cents: int = 0
	tenant_id: str = ""


@dataclass
class ServiceContractInvoiceGeneratedEvent(DomainEvent):
	event_type: str = "crm.service_contracts.invoice.generated"
	contract_id: str = ""
	invoice_id: str = ""
	period: str = ""
	amount_cents: int = 0


@dataclass
class ServiceContractRenewedEvent(DomainEvent):
	event_type: str = "crm.service_contracts.renewed"
	contract_id: str = ""
	old_end_date: str = ""
	new_end_date: str = ""


@dataclass
class ServiceContractCancelledEvent(DomainEvent):
	event_type: str = "crm.service_contracts.cancelled"
	contract_id: str = ""
	reason: str = ""


@dataclass
class SLABreachEvent(DomainEvent):
	event_type: str = "crm.service_contracts.sla.breach"
	contract_id: str = ""
	work_order_id: str = ""
	response_hours: int = 0
	sla_hours: int = 0


@dataclass
class ContractExpiryAlertEvent(DomainEvent):
	event_type: str = "crm.service_contracts.expiry.alert"
	contract_id: str = ""
	days_until_expiry: int = 0


__all__ = [
	"ServiceContractCreatedEvent",
	"ServiceContractInvoiceGeneratedEvent",
	"ServiceContractRenewedEvent",
	"ServiceContractCancelledEvent",
	"SLABreachEvent",
	"ContractExpiryAlertEvent",
]
