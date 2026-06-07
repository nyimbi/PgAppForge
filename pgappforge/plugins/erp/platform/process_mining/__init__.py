"""
pgappforge/plugins/erp/platform/process_mining/__init__.py

ProcessMiningPlugin — event-log process discovery and conformance.

Domain:    platform
Depends:   foundation

Events emitted
--------------
  platform.process_mining.process.discovered
  platform.process_mining.bottleneck.found
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ProcessMiningPlugin(BasePlugin):
	"""Process Mining plugin.

	Discovers process graphs from DomainEventLog, computes cycle-time metrics,
	identifies top process variants, finds transition bottlenecks, and checks
	conformance against expected process sequences (Celonis-style).
	"""

	name = "process_mining"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="process_mining",
			version="1.0.0",
			description=(
				"Process Mining — event-log graph discovery, cycle-time analytics, "
				"variant detection, bottleneck identification, and conformance checking."
			),
			author="PgAppForge Contributors",
			tags=["platform", "process-mining", "event-log", "bottleneck", "celonis", "conformance"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_pm_discover",
				"can_pm_metrics",
				"can_pm_variants",
				"can_pm_bottlenecks",
				"can_pm_conformance",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.process_mining.process.discovered",
			"platform.process_mining.bottleneck.found",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		log.info("ProcessMiningPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.process_mining.models import ProcessMiningDefinition
		return [ProcessMiningDefinition]


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ProcessMiningPlugin:
	return ProcessMiningPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.process_mining.models import ProcessMiningDefinition  # noqa: E402
from pgappforge.plugins.erp.platform.process_mining.events import (  # noqa: E402
	ProcessDiscoveredEvent,
	BottleneckFoundEvent,
)
from pgappforge.plugins.erp.platform.process_mining.services import ProcessMiningService  # noqa: E402

__all__ = [
	"ProcessMiningPlugin",
	"create_plugin",
	"ProcessMiningDefinition",
	"ProcessDiscoveredEvent",
	"BottleneckFoundEvent",
	"ProcessMiningService",
]
