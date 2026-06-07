"""
pgappforge/plugins/erp/crm/territory_management/__init__.py

TerritoryPlugin — Sales Territory Management.

Domain:    crm
Depends:   foundation

Events emitted
--------------
  crm.territory.defined
  crm.territory.assigned
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TerritoryPlugin(BasePlugin):
	"""Sales Territory Management plugin.

	Covers territory definition with JSONB rule sets, salesperson assignments
	with date-range validity, bulk reassignment, and account-coverage queries.
	"""

	name = "territory_management"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="territory_management",
			version="1.0.0",
			description=(
				"Sales Territory Management — rule-based territory definition, "
				"salesperson assignments, and account coverage queries."
			),
			author="PgAppForge Contributors",
			tags=["crm", "territory", "sales", "assignment"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ter_territory_read",
				"can_ter_territory_write",
				"can_ter_territory_delete",
				"can_ter_assignment_read",
				"can_ter_assignment_write",
				"can_ter_reassign",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"crm.territory.defined",
			"crm.territory.assigned",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		log.info("TerritoryPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.territory_management.models import (
			SalesTerritory,
			TerritoryAssignment,
		)
		return [SalesTerritory, TerritoryAssignment]


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> TerritoryPlugin:
	return TerritoryPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.crm.territory_management.models import (  # noqa: E402
	SalesTerritory,
	TerritoryAssignment,
)
from pgappforge.plugins.erp.crm.territory_management.events import (  # noqa: E402
	TerritoryDefinedEvent,
	TerritoryAssignedEvent,
)
from pgappforge.plugins.erp.crm.territory_management.services import (  # noqa: E402
	TerritoryService,
)

__all__ = [
	"TerritoryPlugin",
	"create_plugin",
	"SalesTerritory",
	"TerritoryAssignment",
	"TerritoryDefinedEvent",
	"TerritoryAssignedEvent",
	"TerritoryService",
]
