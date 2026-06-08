"""
pgappforge/plugins/erp/platform/mes/__init__.py

MESPlugin — Manufacturing Execution System framework.

Domain:    platform
Depends:   foundation

Events emitted
--------------
  platform.mes.machine.registered
  platform.mes.telemetry.ingested
  platform.mes.alert.raised
  platform.mes.oee.computed
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class MESPlugin(BasePlugin):
	"""Manufacturing Execution System plugin.

	Covers machine registration, real-time telemetry ingestion with threshold
	alerting, OEE (Overall Equipment Effectiveness) computation, production
	order linkage, and optional OPC-UA endpoint polling.
	"""

	name = "mes"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="mes",
			version="1.0.0",
			description=(
				"Manufacturing Execution System — machine registry, telemetry ingestion, "
				"OEE computation, downtime/quality alerting, and OPC-UA polling."
			),
			author="PgAppForge Contributors",
			tags=["platform", "mes", "oee", "telemetry", "opcua", "industry40"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_mes_machine_read",
				"can_mes_machine_write",
				"can_mes_telemetry_ingest",
				"can_mes_oee_compute",
				"can_mes_alert_read",
				"can_mes_alert_resolve",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.mes.machine.registered",
			"platform.mes.telemetry.ingested",
			"platform.mes.alert.raised",
			"platform.mes.oee.computed",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"MES_DEFAULT_DOWNTIME_THRESHOLD_MINUTES": 30,
			"MES_DEFAULT_QUALITY_THRESHOLD_PCT": 95.0,
		}
		self.config = {**defaults, **self.config}
		log.info("MESPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.mes.views import (
			MachineDefinitionView,
			MachineReadingView,
			ProductionAlertView,
		)
		cat = self.config.get("MES_MENU_CATEGORY", "Manufacturing Execution")
		self.add_view(MachineDefinitionView, "Machines", icon="fa-cog", category=cat)
		self.add_view(MachineReadingView, "Machine Readings", icon="fa-bar-chart", category=cat)
		self.add_view(ProductionAlertView, "Production Alerts", icon="fa-bell", category=cat)
		log.info("MESPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.mes.models import (
			MachineDefinition,
			MachineReading,
			ProductionAlert,
		)
		return [MachineDefinition, MachineReading, ProductionAlert]


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> MESPlugin:
	return MESPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.mes.models import (  # noqa: E402
	MachineDefinition,
	MachineReading,
	ProductionAlert,
)
from pgappforge.plugins.erp.platform.mes.events import (  # noqa: E402
	MachineRegisteredEvent,
	TelemetryIngestedEvent,
	ProductionAlertRaisedEvent,
	OEEComputedEvent,
)
from pgappforge.plugins.erp.platform.mes.services import MESService  # noqa: E402

__all__ = [
	"MESPlugin",
	"create_plugin",
	"MachineDefinition",
	"MachineReading",
	"ProductionAlert",
	"MachineRegisteredEvent",
	"TelemetryIngestedEvent",
	"ProductionAlertRaisedEvent",
	"OEEComputedEvent",
	"MESService",
]
