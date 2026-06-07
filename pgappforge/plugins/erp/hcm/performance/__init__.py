"""
pgappforge/plugins/erp/hcm/performance/__init__.py

PerformancePlugin — HCM Performance Review ERP plugin.

Comprehensive performance management: review cycles, goal/OKR tracking,
360-degree reviews, calibration, and continuous feedback.

  PerformanceCycle → PerformanceReview
  Goal (OKR / SMART / STRETCH / OPERATIONAL)
  ContinuousFeedback

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.performance.cycle.started
  hcm.performance.review.submitted
  hcm.performance.goal.created
  hcm.performance.goal.progress
  hcm.performance.feedback.given

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.performance",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.performance import PerformancePlugin
    plugin = PerformancePlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PerformancePlugin(BasePlugin):
	"""HCM Performance Review ERP plugin.

	Manages annual/quarterly review cycles, goal/OKR tracking, manager/peer/self
	360-degree reviews, statistical calibration, and continuous feedback loops.
	Cross-references with the talent module for 9-box placement.
	"""

	name = "performance"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="performance",
			version="1.0.0",
			description=(
				"HCM Performance Review — full performance management lifecycle: "
				"annual / quarterly review cycles, OKR / goal tracking with key results, "
				"SELF / MANAGER / PEER / 360-upward reviews, statistical calibration with "
				"9-box cross-reference, and continuous feedback. Workday-equivalent depth."
			),
			author="PgAppForge Contributors",
			tags=["hcm", "performance", "okr", "goals", "reviews", "360", "calibration", "workday"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_cycle_list",
				"can_cycle_write",
				"can_cycle_activate",
				"can_review_list",
				"can_review_submit",
				"can_review_calibrate",
				"can_goal_list",
				"can_goal_write",
				"can_goal_progress",
				"can_feedback_give",
				"can_feedback_read",
				"can_performance_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.performance.cycle.started",
			"hcm.performance.review.submitted",
			"hcm.performance.goal.created",
			"hcm.performance.goal.progress",
			"hcm.performance.feedback.given",
		]

	def subscribe_to(self) -> list[str]:
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PERFORMANCE_DEFAULT_RATING_SCALE": 5,
			"PERFORMANCE_CALIBRATION_ENABLED": True,
			"PERFORMANCE_CONTINUOUS_FEEDBACK_ENABLED": True,
			"PERFORMANCE_NINEBOX_INTEGRATION": True,
		}
		self.config = {**defaults, **self.config}
		log.info("PerformancePlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.performance.models import (
			PerformanceCycle,
			PerformanceReview,
			Goal,
			ContinuousFeedback,
		)
		return [PerformanceCycle, PerformanceReview, Goal, ContinuousFeedback]

	def register_views(self) -> None:
		log.info(
			"PerformancePlugin: no views registered (API-only mode); "
			"add views.py and call add_view() here to enable UI"
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> PerformancePlugin:
	return PerformancePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.performance.models import (  # noqa: E402
	PerformanceCycle,
	PerformanceReview,
	Goal,
	ContinuousFeedback,
)
from pgappforge.plugins.erp.hcm.performance.events import (  # noqa: E402
	PerformanceCycleStartedEvent,
	ReviewSubmittedEvent,
	GoalCreatedEvent,
	GoalProgressUpdatedEvent,
	FeedbackGivenEvent,
)
from pgappforge.plugins.erp.hcm.performance.services import (  # noqa: E402
	PerformanceService,
	PerformanceServiceError,
	CycleNotFoundError,
	ReviewNotFoundError,
	GoalNotFoundError,
	PerformanceStateError,
)

__all__ = [
	# plugin
	"PerformancePlugin",
	"create_plugin",
	# models
	"PerformanceCycle",
	"PerformanceReview",
	"Goal",
	"ContinuousFeedback",
	# events
	"PerformanceCycleStartedEvent",
	"ReviewSubmittedEvent",
	"GoalCreatedEvent",
	"GoalProgressUpdatedEvent",
	"FeedbackGivenEvent",
	# services
	"PerformanceService",
	"PerformanceServiceError",
	"CycleNotFoundError",
	"ReviewNotFoundError",
	"GoalNotFoundError",
	"PerformanceStateError",
]
