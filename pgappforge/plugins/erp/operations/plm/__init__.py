"""
pgappforge/plugins/erp/operations/plm/__init__.py

PlmPlugin — Product Lifecycle Management plugin.

Domain: operations
Depends on: foundation

Scope: full PLM lifecycle — product creation, versioning, BOM management,
       engineering change orders, and stage-gate reviews.

Events emitted:
  ops.plm.version.created
  ops.plm.eco.submitted
  ops.plm.eco.approved
  ops.plm.bom.released
  ops.plm.stage_gate.passed

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.plm",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.plm import PlmPlugin
    plugin = PlmPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PlmPlugin(BasePlugin):
	"""Product Lifecycle Management (PLM) plugin.

	Provides:
	  - Product registry with lifecycle stages (CONCEPT → EOL)
	  - Versioned product snapshots (MAJOR/MINOR/PATCH) with approval workflow
	  - Bill of Materials with revision tracking and release gating
	  - Engineering Change Orders (ECO) with type, priority, and approval workflow
	  - Stage-gate review logging with full audit trail
	  - BPM-callable actions for workflow integration
	"""

	name = "plm"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="plm",
			version="1.0.0",
			description=(
				"Product Lifecycle Management — product registry, versioning, BOM management, "
				"engineering change orders, and stage-gate review workflows."
			),
			author="PgAppForge Contributors",
			tags=["ops", "plm", "bom", "engineering"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_plm_product_list",
				"can_plm_product_create",
				"can_plm_product_edit",
				"can_plm_version_list",
				"can_plm_version_create",
				"can_plm_version_approve",
				"can_plm_version_release",
				"can_plm_bom_list",
				"can_plm_bom_create",
				"can_plm_bom_release",
				"can_plm_eco_list",
				"can_plm_eco_create",
				"can_plm_eco_submit",
				"can_plm_eco_approve",
				"can_plm_stage_gate_approve",
				"can_plm_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"ops.plm.version.created",
			"ops.plm.eco.submitted",
			"ops.plm.eco.approved",
			"ops.plm.bom.released",
			"ops.plm.stage_gate.passed",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PLM_MENU_CATEGORY": "Product Lifecycle",
			"PLM_DEFAULT_LIFECYCLE_STAGE": "CONCEPT",
		}
		self.config = {**defaults, **self.config}
		log.info("PlmPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		cat = self.config.get("PLM_MENU_CATEGORY", "Product Lifecycle")
		log.info("PlmPlugin: views would be registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.plm.models import (
			PlmProduct,
			PlmProductVersion,
			BillOfMaterials,
			EngineeringChangeOrder,
		)
		return [PlmProduct, PlmProductVersion, BillOfMaterials, EngineeringChangeOrder]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> PlmPlugin:
	"""Construct a PlmPlugin without activating it."""
	return PlmPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.plm.models import (  # noqa: E402
	PlmProduct,
	PlmProductVersion,
	BillOfMaterials,
	EngineeringChangeOrder,
)
from pgappforge.plugins.erp.operations.plm.events import (  # noqa: E402
	ProductVersionCreatedEvent,
	EcoSubmittedEvent,
	EcoApprovedEvent,
	BomReleasedEvent,
	StageGatePassedEvent,
)
from pgappforge.plugins.erp.operations.plm.services import (  # noqa: E402
	PlmService,
	PlmServiceError,
	PlmNotFoundError,
	PlmStateError,
)

__all__ = [
	# plugin
	"PlmPlugin",
	"create_plugin",
	# models
	"PlmProduct",
	"PlmProductVersion",
	"BillOfMaterials",
	"EngineeringChangeOrder",
	# events
	"ProductVersionCreatedEvent",
	"EcoSubmittedEvent",
	"EcoApprovedEvent",
	"BomReleasedEvent",
	"StageGatePassedEvent",
	# services
	"PlmService",
	"PlmServiceError",
	"PlmNotFoundError",
	"PlmStateError",
]
