"""
pgappforge/plugins/erp/hcm/position_management/__init__.py

PositionManagementPlugin — HCM Position Management ERP plugin.

Establishment register and headcount control:
  Position (org slot) → HeadcountRequest (annual planning)

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.positions.created
  hcm.positions.filled
  hcm.positions.vacated
  hcm.positions.headcount.variance

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.position_management",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.position_management import PositionManagementPlugin
    plugin = PositionManagementPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PositionManagementPlugin(BasePlugin):
	"""HCM Position Management ERP plugin.

	Manages the organisational establishment register: approved positions,
	FTE budgets, fill/vacate lifecycle, headcount variance alerting, and
	automatic replacement requisition triggering via the recruiting plugin.
	"""

	name = "position_management"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="position_management",
			version="1.0.0",
			description=(
				"HCM Position Management — organisational establishment register with "
				"approved position slots, FTE headcount budgeting, fill/vacate lifecycle, "
				"automatic headcount variance alerting, replacement requisition triggering, "
				"and annual headcount planning requests. Workday-equivalent depth."
			),
			author="PgAppForge Contributors",
			tags=["hcm", "positions", "headcount", "org-design", "workforce-planning", "workday"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_position_list",
				"can_position_write",
				"can_position_fill",
				"can_position_vacate",
				"can_headcount_request_list",
				"can_headcount_request_write",
				"can_headcount_request_approve",
				"can_org_chart_view",
				"can_workforce_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.positions.created",
			"hcm.positions.filled",
			"hcm.positions.vacated",
			"hcm.positions.headcount.variance",
		]

	def subscribe_to(self) -> list[str]:
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"POSITIONS_AUTO_REQUISITION_ON_VACATE": True,
			"POSITIONS_VARIANCE_ALERT_THRESHOLD": 0,
			"POSITIONS_DEFAULT_EMPLOYMENT_TYPE": "FULL_TIME",
		}
		self.config = {**defaults, **self.config}
		log.info("PositionManagementPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.position_management.models import (
			Position,
			HeadcountRequest,
		)
		return [Position, HeadcountRequest]

	def register_views(self) -> None:
		log.info(
			"PositionManagementPlugin: no views registered (API-only mode); "
			"add views.py and call add_view() here to enable UI"
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> PositionManagementPlugin:
	return PositionManagementPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.position_management.models import (  # noqa: E402
	Position,
	HeadcountRequest,
)
from pgappforge.plugins.erp.hcm.position_management.events import (  # noqa: E402
	PositionCreatedEvent,
	PositionFilledEvent,
	PositionVacatedEvent,
	HeadcountVarianceAlertEvent,
)
from pgappforge.plugins.erp.hcm.position_management.services import (  # noqa: E402
	PositionManagementService,
	PositionManagementError,
	PositionNotFoundError,
	PositionStateError,
)

__all__ = [
	# plugin
	"PositionManagementPlugin",
	"create_plugin",
	# models
	"Position",
	"HeadcountRequest",
	# events
	"PositionCreatedEvent",
	"PositionFilledEvent",
	"PositionVacatedEvent",
	"HeadcountVarianceAlertEvent",
	# services
	"PositionManagementService",
	"PositionManagementError",
	"PositionNotFoundError",
	"PositionStateError",
]
