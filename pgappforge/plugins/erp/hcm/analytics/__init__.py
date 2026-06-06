"""
pgappforge/plugins/erp/hcm/analytics/__init__.py

HR Analytics plugin — workforce metrics, flight risk scoring, diversity
reporting, turnover analytics, and headcount snapshots.

Domain: hcm
Sub-domain: analytics
Depends on: foundation

Events emitted:
  hcm.analytics.report.generated
  hcm.analytics.turnover.alert
  hcm.analytics.flight_risk.alert
  hcm.analytics.diversity.report
  hcm.analytics.headcount.changed

Events consumed:
  hcm.employee.hired        (trigger headcount snapshot)
  hcm.employee.terminated   (trigger turnover delta + headcount snapshot)
  hcm.payroll.run.paid      (aggregate compensation cost data)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.analytics",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.analytics import HrAnalyticsPlugin
    plugin = HrAnalyticsPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class HrAnalyticsPlugin(BasePlugin):
	"""HR Analytics ERP plugin.

	Provides workforce analytics: headcount, turnover, diversity,
	flight risk scoring, cost-per-hire, and dashboard aggregates.

	Registers:
	  - HrAnalyticsSnapshot, HrFlightRiskScore, HrAnalyticsReport models
	  - analytics.flight_risk.auto_alert ruleset
	  - hcm.analytics.compute_flight_risk BPM action
	"""

	name = "analytics"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="analytics",
			version="1.0.0",
			description=(
				"HR Analytics — workforce metrics and actionable insights: "
				"headcount snapshots, turnover rate tracking, diversity reporting, "
				"predictive flight risk scoring, cost-per-hire analysis, "
				"and consolidated HR dashboard."
			),
			author="PgAppForge Contributors",
			tags=["erp", "hcm", "analytics", "hr-metrics", "turnover"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_analytics_snapshot_list",
				"can_analytics_snapshot_generate",
				"can_flight_risk_list",
				"can_flight_risk_compute",
				"can_analytics_report_list",
				"can_analytics_report_generate",
				"can_hr_dashboard_view",
				"can_diversity_report_view",
				"can_turnover_report_view",
				"can_headcount_report_view",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.analytics.report.generated",
			"hcm.analytics.turnover.alert",
			"hcm.analytics.flight_risk.alert",
			"hcm.analytics.diversity.report",
			"hcm.analytics.headcount.changed",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.hired",
			"hcm.employee.terminated",
			"hcm.payroll.run.paid",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"HCM_ANALYTICS_MENU_CATEGORY": "HR Analytics",
			"HCM_ANALYTICS_TURNOVER_ALERT_PCT": "15.0",
			"HCM_ANALYTICS_FLIGHT_RISK_RECOMPUTE_ON_HIRE": True,
			"HCM_ANALYTICS_FLIGHT_RISK_RECOMPUTE_ON_TERMINATION": True,
			"HCM_ANALYTICS_DEFAULT_CURRENCY": "KES",
		}
		self.config = {**defaults, **self.config}
		log.info("HrAnalyticsPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		"""Views registered lazily to avoid circular imports at plugin load time."""
		try:
			from pgappforge.plugins.erp.hcm.analytics.views import (  # type: ignore[import]
				HrAnalyticsSnapshotView,
				HrFlightRiskScoreView,
				HrAnalyticsReportView,
				HrAnalyticsDashboardView,
			)
		except ImportError:
			log.debug("HrAnalyticsPlugin.register_views: views module not yet created; skipping")
			return

		cat = self.config.get("HCM_ANALYTICS_MENU_CATEGORY", "HR Analytics")

		self.add_view(HrAnalyticsDashboardView, "Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(HrAnalyticsSnapshotView, "Snapshots", icon="fa-camera", category=cat)
		self.add_view(HrFlightRiskScoreView, "Flight Risk", icon="fa-plane", category=cat)
		self.add_view(HrAnalyticsReportView, "Reports", icon="fa-bar-chart", category=cat)

		log.info("HrAnalyticsPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.analytics.models import (
			HrAnalyticsSnapshot,
			HrFlightRiskScore,
			HrAnalyticsReport,
		)
		return [
			HrAnalyticsSnapshot,
			HrFlightRiskScore,
			HrAnalyticsReport,
		]

	# ------------------------------------------------------------------
	# Event handlers
	# ------------------------------------------------------------------

	def on_event(self, event_type: str, event: Any, session: Any) -> None:
		"""Handle subscribed events.

		hcm.employee.hired       → trigger headcount snapshot for the tenant
		hcm.employee.terminated  → trigger headcount + turnover snapshots
		hcm.payroll.run.paid     → no-op (reserved for compensation analytics)
		"""
		from datetime import date

		if event_type in ("hcm.employee.hired", "hcm.employee.terminated"):
			tenant_id = getattr(event, "tenant_id", None) or (
				event.get("tenant_id", "") if isinstance(event, dict) else ""
			)
			if not tenant_id:
				return
			today = date.today()
			period_label = f"{today.year}-{today.month:02d}"
			try:
				from pgappforge.plugins.erp.hcm.analytics.services import HrAnalyticsService
				HrAnalyticsService.generate_snapshot(
					tenant_id=tenant_id,
					snapshot_type="HEADCOUNT",
					period=period_label,
					session=session,
				)
			except Exception as exc:
				log.warning(
					"HrAnalyticsPlugin.on_event: headcount snapshot failed for %s: %s",
					event_type, exc,
				)

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for the HR Analytics domain.

		Idempotent — skips rulesets that already exist.

		Rulesets:
		  analytics.flight_risk.auto_alert — auto-emit FlightRiskAlertEvent
		    when a computed score is HIGH or CRITICAL (enforced in service
		    layer; ruleset documents the policy for audit purposes).
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("HrAnalyticsPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			{
				"name": "analytics.flight_risk.auto_alert",
				"description": (
					"Automatically emit FlightRiskAlertEvent when a computed "
					"flight risk score is HIGH (61-80) or CRITICAL (81+). "
					"Enforced in HrAnalyticsService.compute_flight_risk(); "
					"this ruleset documents the policy for audit purposes."
				),
				"model_name": "HrFlightRiskScore",
				"stop_on_match": False,
				"rules": [
					{
						"name": "alert_on_high_flight_risk",
						"trigger_event": "on_after_create",
						"conditions_json": [
							{
								"field": "risk_level",
								"op": "in",
								"value": ["HIGH", "CRITICAL"],
							},
							{
								"field": "is_current",
								"op": "eq",
								"value": True,
							},
						],
						"actions_json": [
							{
								"type": "emit_event",
								"event_type": "hcm.analytics.flight_risk.alert",
								"fields": ["employee_id", "score", "risk_level", "factors"],
							},
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("HrAnalyticsPlugin.setup_rules: %d rulesets configured", len(RULESETS))


import sqlalchemy as sa  # noqa: E402 — needed inside setup_rules


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> HrAnalyticsPlugin:
	return HrAnalyticsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.analytics.models import (  # noqa: E402
	HrAnalyticsSnapshot,
	HrFlightRiskScore,
	HrAnalyticsReport,
)
from pgappforge.plugins.erp.hcm.analytics.events import (  # noqa: E402
	AnalyticsReportGeneratedEvent,
	TurnoverAlertEvent,
	FlightRiskAlertEvent,
	DiversityReportGeneratedEvent,
	HeadcountChangedEvent,
)
from pgappforge.plugins.erp.hcm.analytics.services import (  # noqa: E402
	HrAnalyticsService,
	AnalyticsServiceError,
	AnalyticsNotFoundError,
	AnalyticsStateError,
)

__all__ = [
	# plugin
	"HrAnalyticsPlugin",
	"create_plugin",
	# models
	"HrAnalyticsSnapshot",
	"HrFlightRiskScore",
	"HrAnalyticsReport",
	# events
	"AnalyticsReportGeneratedEvent",
	"TurnoverAlertEvent",
	"FlightRiskAlertEvent",
	"DiversityReportGeneratedEvent",
	"HeadcountChangedEvent",
	# service + exceptions
	"HrAnalyticsService",
	"AnalyticsServiceError",
	"AnalyticsNotFoundError",
	"AnalyticsStateError",
]
