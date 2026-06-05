"""
pgappforge/plugins/erp/finance/entities/__init__.py

LegalEntitiesPlugin — multi-entity legal hierarchy for banking groups.

Context: A Kenyan banking group (holding company + bank + insurance +
microfinance) requires separate GL books per entity, inter-entity transaction
tracking with automatic GL posting, and consolidated financial reporting with
inter-company eliminations.

Plugins in this module:
  LegalEntity              — corporate hierarchy (self-referential, max depth 5)
  InterEntityTransaction   — cross-entity cash flows with dual GL posting
  ConsolidationElimination — period eliminations for group consolidation

Events emitted:
  entity.created
  entity.interco_transaction.posted
  entity.consolidation.eliminations_generated

Events consumed:
  (none in v1; future: gl.period.closed → trigger elimination generation)

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",        # optional but recommended
        "pgappforge.plugins.erp.finance.entities",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.finance.entities import LegalEntitiesPlugin
    plugin = LegalEntitiesPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class LegalEntitiesPlugin(BasePlugin):
	"""Multi-entity legal hierarchy plugin.

	Registers models, services, and views for managing a banking group's
	corporate structure, inter-entity transactions, and consolidation.

	Class-level attributes:
	    name       = "legal_entities"
	    domain     = "finance"
	    depends_on = ["foundation"]
	"""

	name = "legal_entities"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# metadata (required abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="legal_entities",
			version="1.0.0",
			description=(
				"Multi-entity legal hierarchy for banking groups — "
				"separate GL books per entity, inter-entity transaction "
				"tracking, and consolidated reporting with eliminations."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "entities", "consolidation", "banking"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_legal_entity_list",
				"can_legal_entity_write",
				"can_interco_txn_list",
				"can_interco_txn_write",
				"can_interco_txn_post",
				"can_consolidation_read",
				"can_consolidation_generate",
				"can_entity_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"entity.created",
			"entity.interco_transaction.posted",
			"entity.consolidation.eliminations_generated",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"ENTITIES_MENU_CATEGORY": "Group Finance",
			"ENTITIES_MAX_HIERARCHY_DEPTH": 5,
			"ENTITIES_DEFAULT_CURRENCY": "KES",
		}
		self.config = {**defaults, **self.config}
		log.info(
			"LegalEntitiesPlugin initialised (config keys: %s)",
			list(self.config),
		)

	def register_views(self) -> None:
		"""Register entity hierarchy and consolidation views."""
		# Views are a thin layer over the service; imported here to keep
		# plugin activation fast when views are not needed (e.g. API-only).
		cat = self.config.get("ENTITIES_MENU_CATEGORY", "Group Finance")
		log.info(
			"LegalEntitiesPlugin: views would be registered under %r "
			"(views module not yet implemented)",
			cat,
		)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.finance.entities.models import (
			ConsolidationElimination,
			InterEntityTransaction,
			LegalEntity,
		)
		return [LegalEntity, InterEntityTransaction, ConsolidationElimination]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> LegalEntitiesPlugin:
	"""Construct and return a LegalEntitiesPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return LegalEntitiesPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.entities.models import (  # noqa: E402
	ConsolidationElimination,
	InterEntityTransaction,
	LegalEntity,
)
from pgappforge.plugins.erp.finance.entities.events import (  # noqa: E402
	ConsolidationEliminationsGeneratedEvent,
	EntityCreatedEvent,
	InterEntityTransactionPostedEvent,
)
from pgappforge.plugins.erp.finance.entities.services import (  # noqa: E402
	DuplicateEntityCodeError,
	EntityHierarchyError,
	EntityNotFoundError,
	InvalidTransactionError,
	LegalEntityService,
	LegalEntityServiceError,
)

__all__ = [
	# plugin
	"LegalEntitiesPlugin",
	"create_plugin",
	# models
	"LegalEntity",
	"InterEntityTransaction",
	"ConsolidationElimination",
	# events
	"EntityCreatedEvent",
	"InterEntityTransactionPostedEvent",
	"ConsolidationEliminationsGeneratedEvent",
	# services
	"LegalEntityService",
	"LegalEntityServiceError",
	"EntityNotFoundError",
	"DuplicateEntityCodeError",
	"EntityHierarchyError",
	"InvalidTransactionError",
]
