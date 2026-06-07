from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.crm.service_contracts.events import (
	ContractExpiryAlertEvent,
	ServiceContractCancelledEvent,
	ServiceContractCreatedEvent,
	ServiceContractInvoiceGeneratedEvent,
	ServiceContractRenewedEvent,
	SLABreachEvent,
)
from pgappforge.plugins.erp.crm.service_contracts.models import (
	ContractRenewal,
	ServiceContract,
)
from pgappforge.plugins.erp.crm.service_contracts.services import (
	ContractNotFoundError,
	ContractStateError,
	ServiceContractError,
	ServiceContractService,
)

log = logging.getLogger(__name__)


class ServiceContractsPlugin(BasePlugin):
	name = "service_contracts"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="service_contracts",
			version="1.0.0",
			description=(
				"Recurring maintenance service contracts with SLA tracking, "
				"auto-invoicing, and BPM-native approval. Exceeds NAV Service "
				"on IFRS 15 contract liability handling."
			),
			author="PgAppForge Contributors",
			tags=[
				"crm",
				"service",
				"contracts",
				"maintenance",
				"sla",
				"recurring-billing",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_service_contracts_list",
				"can_service_contracts_create",
				"can_service_contracts_invoice",
				"can_service_contracts_renew",
				"can_service_contracts_cancel",
				"can_service_contracts_sla_view",
			],
		)

	def get_events(self) -> list[str]:
		return [
			"crm.service_contracts.created",
			"crm.service_contracts.invoice.generated",
			"crm.service_contracts.renewed",
			"crm.service_contracts.cancelled",
			"crm.service_contracts.sla.breach",
			"crm.service_contracts.expiry.alert",
		]

	def subscribe_to(self) -> list[str]:
		return ["crm.service.work_order.closed"]

	def initialize(self) -> None:
		self.config.setdefault(
			"SERVICE_CONTRACTS_MENU_CATEGORY", "Service Contracts"
		)

	def register_models(self) -> list:
		return [ServiceContract, ContractRenewal]

	def register_views(self) -> None:
		log.info("ServiceContractsPlugin: views pending implementation")

	def setup_rules(self, session: Any) -> None:
		pass


def create_plugin(appbuilder: Any, config: dict | None = None) -> ServiceContractsPlugin:
	return ServiceContractsPlugin(appbuilder, config=config or {})


__all__ = [
	"ServiceContractsPlugin",
	"create_plugin",
	"ServiceContract",
	"ContractRenewal",
	"ServiceContractService",
	"ServiceContractError",
	"ContractNotFoundError",
	"ContractStateError",
]
