"""
pgappforge/plugins/erp/operations/process_manufacturing/__init__.py

ProcessManufacturingPlugin — Recipe management and batch execution for
process industries (pharma, food & beverage, chemicals, cosmetics).

Domain: operations
Depends on: foundation, inventory

Full lifecycle:
  Recipe (DRAFT → UNDER_REVIEW → APPROVED → OBSOLETE)
  RecipeIngredient  (ingredient BOM per recipe)
  BatchRecord (PLANNED → IN_PROCESS → COMPLETED | REJECTED)

  create_recipe()           → define formula, ingredients, process params
  approve_recipe()          → gate control: APPROVED enables batch creation
  create_batch_record()     → initiate production batch from approved recipe
  record_ingredients_used() → capture actual ingredient quantities + variances
  complete_batch()          → record actual yield, quality checks, post GL variance

Events emitted:
  ops.process_mfg.recipe.created
  ops.process_mfg.recipe.approved
  ops.process_mfg.batch.created
  ops.process_mfg.batch.completed
  ops.process_mfg.yield.variance

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.inventory",
        "pgappforge.plugins.erp.operations.process_manufacturing",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.process_manufacturing import ProcessManufacturingPlugin
    plugin = ProcessManufacturingPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ProcessManufacturingPlugin(BasePlugin):
	"""Process Manufacturing ERP plugin.

	Provides recipe management, batch record execution, ingredient tracking,
	yield variance computation, and GL posting for process industries.

	Integrates with:
	  - Inventory plugin for ingredient stock queries
	  - GL plugin for yield variance posting to accounts 5990 / 5000
	"""

	name = "process_manufacturing"
	domain = "operations"
	depends_on: list[str] = ["foundation", "inventory"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="process_manufacturing",
			version="1.0.0",
			description=(
				"Process Manufacturing — recipe management, batch records, ingredient "
				"tracking, yield variance computation, and GL posting for pharma, "
				"food & beverage, chemical, and cosmetic manufacturers."
			),
			author="PgAppForge Contributors",
			tags=[
				"operations", "manufacturing", "process", "recipe", "batch",
				"pharma", "food-beverage", "chemicals",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_prm_recipe_list",
				"can_prm_recipe_create",
				"can_prm_recipe_approve",
				"can_prm_batch_list",
				"can_prm_batch_create",
				"can_prm_batch_complete",
				"can_prm_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"ops.process_mfg.recipe.created",
			"ops.process_mfg.recipe.approved",
			"ops.process_mfg.batch.created",
			"ops.process_mfg.batch.completed",
			"ops.process_mfg.yield.variance",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PRM_MENU_CATEGORY": "Process Manufacturing",
			"PRM_GL_VARIANCE_ACCOUNT": "5990",
			"PRM_GL_WIP_ACCOUNT": "5000",
			"PRM_YIELD_VARIANCE_THRESHOLD_PCT": 5.0,
			"PRM_POST_VARIANCE_TO_GL": True,
		}
		self.config = {**defaults, **self.config}
		log.info("ProcessManufacturingPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.operations.process_manufacturing.views import (
			RecipeView,
			RecipeIngredientView,
			BatchRecordView,
		)
		cat = self.config.get("PRM_MENU_CATEGORY", "Process Manufacturing")
		self.add_view(RecipeView, "Recipes", icon="fa-flask", category=cat)
		self.add_view(RecipeIngredientView, "Ingredients", icon="fa-list-ul", category=cat)
		self.add_view(BatchRecordView, "Batch Records", icon="fa-clipboard", category=cat)
		log.info("ProcessManufacturingPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.process_manufacturing.models import (
			Recipe,
			RecipeIngredient,
			BatchRecord,
		)
		return [Recipe, RecipeIngredient, BatchRecord]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ProcessManufacturingPlugin:
	"""Construct a ProcessManufacturingPlugin without activating it."""
	return ProcessManufacturingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.process_manufacturing.models import (  # noqa: E402
	Recipe,
	RecipeIngredient,
	BatchRecord,
)
from pgappforge.plugins.erp.operations.process_manufacturing.events import (  # noqa: E402
	RecipeCreatedEvent,
	RecipeApprovedEvent,
	BatchRecordCreatedEvent,
	BatchCompletedEvent,
	YieldVariancePostedEvent,
)
from pgappforge.plugins.erp.operations.process_manufacturing.services import (  # noqa: E402
	ProcessManufacturingService,
	ProcessManufacturingError,
	RecipeNotFoundError,
	RecipeInvalidStatusError,
	BatchNotFoundError,
	BatchInvalidStatusError,
	MissingCriticalIngredientError,
)

__all__ = [
	# plugin
	"ProcessManufacturingPlugin",
	"create_plugin",
	# models
	"Recipe",
	"RecipeIngredient",
	"BatchRecord",
	# events
	"RecipeCreatedEvent",
	"RecipeApprovedEvent",
	"BatchRecordCreatedEvent",
	"BatchCompletedEvent",
	"YieldVariancePostedEvent",
	# services
	"ProcessManufacturingService",
	"ProcessManufacturingError",
	"RecipeNotFoundError",
	"RecipeInvalidStatusError",
	"BatchNotFoundError",
	"BatchInvalidStatusError",
	"MissingCriticalIngredientError",
]
