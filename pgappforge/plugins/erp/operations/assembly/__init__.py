"""
pgappforge/plugins/erp/operations/assembly/__init__.py

AssemblyPlugin — Bill-of-Materials assembly and kitting ERP plugin.

Domain: operations
Depends on: foundation, inventory

Full assembly lifecycle:
  AssemblyOrder (DRAFT → IN_PROGRESS → POSTED | CANCELLED)
  AssemblyLine  (component BOM lines per order)

  create_assembly_order() → allocate components, compute standard cost
  post_assembly()         → consume components, produce FG, post GL variance
  cancel_assembly()       → cancel pre-post orders

Events emitted:
  ops.assembly.created
  ops.assembly.posted
  ops.assembly.component.consumed
  ops.assembly.cancelled
  ops.assembly.variance

Events consumed:
  (none — driven by explicit service calls)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.inventory",
        "pgappforge.plugins.erp.operations.assembly",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.assembly import AssemblyPlugin
    plugin = AssemblyPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AssemblyPlugin(BasePlugin):
	"""Assembly Management ERP plugin.

	Provides bill-of-materials assembly orders: component consumption,
	finished-goods production, weighted-average costing, and GL variance posting.

	Integrates with:
	  - Inventory plugin (_update_stock_level) for component consumption and FG receipt
	  - GL plugin (post_journal) for production variance posting to account 5990
	"""

	name = "assembly"
	domain = "operations"
	depends_on: list[str] = ["foundation", "inventory"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="assembly",
			version="1.0.0",
			description=(
				"Assembly Management — bill-of-materials assembly orders, component "
				"consumption, finished-goods production, weighted-average costing, "
				"and GL production variance posting."
			),
			author="PgAppForge Contributors",
			tags=["ops", "assembly", "kitting", "manufacturing", "inventory"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_asm_order_list",
				"can_asm_order_create",
				"can_asm_order_post",
				"can_asm_order_cancel",
				"can_asm_line_list",
				"can_asm_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"ops.assembly.created",
			"ops.assembly.posted",
			"ops.assembly.component.consumed",
			"ops.assembly.cancelled",
			"ops.assembly.variance",
		]

	def subscribe_to(self) -> list[str]:
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"ASM_MENU_CATEGORY": "Assembly",
			"ASM_GL_VARIANCE_ACCOUNT": "5990",
			"ASM_GL_CLEARING_ACCOUNT": "5980",
			"ASM_POST_VARIANCE_TO_GL": True,
		}
		self.config = {**defaults, **self.config}
		log.info("AssemblyPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		# Views are registered lazily to avoid import-time DB queries
		try:
			from pgappforge.plugins.erp.operations.assembly.views import (
				AssemblyOrderView,
				AssemblyLineView,
			)
			cat = self.config.get("ASM_MENU_CATEGORY", "Assembly")
			self.add_view(AssemblyOrderView, "Assembly Orders", icon="fa-industry", category=cat)
			self.add_view(AssemblyLineView, "Assembly Lines", icon="fa-list-ol", category=cat)
			log.info("AssemblyPlugin: views registered under category %r", cat)
		except ImportError:
			log.debug("AssemblyPlugin: views module not available, skipping view registration")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.assembly.models import (
			AssemblyOrder,
			AssemblyLine,
		)
		return [AssemblyOrder, AssemblyLine]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> AssemblyPlugin:
	"""Construct an AssemblyPlugin without activating it."""
	return AssemblyPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.assembly.models import (  # noqa: E402
	AssemblyOrder,
	AssemblyLine,
)
from pgappforge.plugins.erp.operations.assembly.events import (  # noqa: E402
	AssemblyOrderCreatedEvent,
	AssemblyOrderPostedEvent,
	AssemblyComponentConsumedEvent,
	AssemblyOrderCancelledEvent,
	AssemblyVariancePostedEvent,
)
from pgappforge.plugins.erp.operations.assembly.services import (  # noqa: E402
	AssemblyService,
	AssemblyServiceError,
	AssemblyOrderNotFoundError,
	AssemblyInvalidStatusError,
	AssemblyInsufficientStockError,
)

__all__ = [
	# plugin
	"AssemblyPlugin",
	"create_plugin",
	# models
	"AssemblyOrder",
	"AssemblyLine",
	# events
	"AssemblyOrderCreatedEvent",
	"AssemblyOrderPostedEvent",
	"AssemblyComponentConsumedEvent",
	"AssemblyOrderCancelledEvent",
	"AssemblyVariancePostedEvent",
	# services
	"AssemblyService",
	"AssemblyServiceError",
	"AssemblyOrderNotFoundError",
	"AssemblyInvalidStatusError",
	"AssemblyInsufficientStockError",
]
