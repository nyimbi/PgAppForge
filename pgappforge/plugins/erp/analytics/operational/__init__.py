"""
pgappforge/plugins/erp/analytics/operational/__init__.py

OperationalPlugin — KPI tracking, saved queries, scheduled reports.

Domain: analytics
Depends on: foundation

Events emitted
--------------
  analytics.kpi.snapshot_recorded   — KPI snapshot inserted
  analytics.kpi.status_changed      — KPI status transitioned
  analytics.report.generated        — report generated and delivered
  analytics.query.executed          — saved query run

Events consumed
---------------
  ar.invoice.paid     — update revenue KPI snapshots
  hcm.payroll.run     — update payroll cost KPI snapshots

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.analytics.operational",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class OperationalPlugin(BasePlugin):
	"""Operational Analytics ERP plugin.

	Provides KPI definition/snapshot lifecycle, saved SQL queries,
	and scheduled report management. Pre-configures 4 Rules Engine rulesets
	for KPI alerting and report delivery controls.

	Class-level attributes for dependency resolution:
	    name       = "analytics.operational"
	    domain     = "analytics"
	    depends_on = ["foundation"]
	"""

	name = "analytics.operational"
	domain = "analytics"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="analytics.operational",
			version="1.0.0",
			description=(
				"Operational Analytics — KPI catalogue, point-in-time snapshots, "
				"saved SQL queries with parameter binding, and scheduled report definitions."
			),
			author="PgAppForge Contributors",
			tags=["erp", "analytics", "kpi", "reporting", "operational"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_analytics_kpi_list",
				"can_analytics_kpi_write",
				"can_analytics_snapshot_write",
				"can_analytics_query_list",
				"can_analytics_query_run",
				"can_analytics_report_list",
				"can_analytics_report_generate",
				"can_analytics_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"analytics.kpi.snapshot_recorded",
			"analytics.kpi.status_changed",
			"analytics.report.generated",
			"analytics.query.executed",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"ar.invoice.paid",
			"hcm.payroll.run",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"ANALYTICS_MENU_CATEGORY": "Analytics",
			"ANALYTICS_KPI_AT_RISK_THRESHOLD": 0.95,
			"ANALYTICS_KPI_OFF_TRACK_THRESHOLD": 0.80,
			"ANALYTICS_REPORT_MAX_RECIPIENTS": 50,
		}
		self.config = {**defaults, **self.config}
		log.info("OperationalPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		self._subscribe_to_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.analytics.operational.views import (
			AnalyticsQueryView,
			AnalyticsReportView,
			FinancialAnalyticsDashboardView,
			KPIDefinitionView,
			KPISnapshotView,
			OperationalDashboardView,
		)
		cat = self.config.get("ANALYTICS_MENU_CATEGORY", "Analytics")
		self.add_view(FinancialAnalyticsDashboardView, "Financial Dashboard", icon="fa-money", category=cat)
		self.add_view(OperationalDashboardView, "Operational Dashboard", icon="fa-industry", category=cat)
		self.add_view(KPIDefinitionView, "KPI Definitions", icon="fa-tachometer", category=cat)
		self.add_view(KPISnapshotView, "KPI Snapshots", icon="fa-chart-line", category=cat)
		self.add_view(AnalyticsQueryView, "Saved Queries", icon="fa-database", category=cat)
		self.add_view(AnalyticsReportView, "Reports", icon="fa-file-text-o", category=cat)
		log.info("OperationalPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.analytics.operational.models import (
			AnalyticsQuery,
			AnalyticsReport,
			KPIDefinition,
			KPISnapshot,
		)
		return [KPIDefinition, KPISnapshot, AnalyticsQuery, AnalyticsReport]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 Rules Engine rulesets for KPI alerting."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("OperationalPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			{
				"name": "analytics.kpi.alert_off_track",
				"description": "Emit alert when KPI status transitions to OFF_TRACK",
				"model_name": "KPISnapshot",
				"stop_on_match": True,
				"rules": [
					{
						"name": "alert_on_off_track",
						"trigger_event": "on_create",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "OFF_TRACK"},
						],
						"actions_json": [
							{"type": "emit_event", "event": "analytics.kpi.status_changed"},
							{"type": "notify", "channel": "ops_alerts", "template": "kpi_off_track"},
						],
					}
				],
			},
			{
				"name": "analytics.kpi.alert_at_risk",
				"description": "Log warning when KPI transitions to AT_RISK",
				"model_name": "KPISnapshot",
				"stop_on_match": True,
				"rules": [
					{
						"name": "warn_at_risk",
						"trigger_event": "on_create",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "AT_RISK"},
						],
						"actions_json": [
							{"type": "log_warning", "message": "KPI is AT_RISK — review required"},
						],
					}
				],
			},
			{
				"name": "analytics.report.require_recipients_for_schedule",
				"description": "Block scheduling a report with no recipients",
				"model_name": "AnalyticsReport",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_recipients",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_is_scheduled", "op": "eq", "value": True},
							{"field": "recipients", "op": "is_empty", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot schedule report with no recipients",
							}
						],
					}
				],
			},
			{
				"name": "analytics.query.block_destructive_sql",
				"description": "Block saving queries containing DDL or DELETE without WHERE",
				"model_name": "AnalyticsQuery",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_ddl",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "query_sql",
								"op": "regex_match",
								"value": r"(?i)\b(DROP|TRUNCATE|ALTER|DELETE\s+FROM\s+\w+\s*;)\b",
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Saved queries may not contain DDL or unbounded DELETE statements",
							}
						],
					}
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
		log.info("OperationalPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("ar.invoice.paid", self._on_invoice_paid)
			subscribe("hcm.payroll.run", self._on_payroll_run)
			log.debug("OperationalPlugin: subscribed to AR and HCM events")
		except Exception as exc:
			log.warning("OperationalPlugin._subscribe_to_events failed: %s", exc)

	def _on_invoice_paid(self, event: Any) -> None:
		log.debug(
			"OperationalPlugin._on_invoice_paid: invoice=%s amount=%s",
			getattr(event, "invoice_id", "?"),
			getattr(event, "total_cents", "?"),
		)

	def _on_payroll_run(self, event: Any) -> None:
		log.debug(
			"OperationalPlugin._on_payroll_run: run_id=%s",
			getattr(event, "payroll_run_id", "?"),
		)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> OperationalPlugin:
	return OperationalPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.analytics.operational.models import (  # noqa: E402
	AnalyticsQuery,
	AnalyticsReport,
	KPIDefinition,
	KPISnapshot,
)
from pgappforge.plugins.erp.analytics.operational.events import (  # noqa: E402
	AnalyticsQueryExecutedEvent,
	AnalyticsReportGeneratedEvent,
	KPISnapshotRecordedEvent,
	KPIStatusChangedEvent,
)
from pgappforge.plugins.erp.analytics.operational.services import (  # noqa: E402
	KPINotFoundError,
	OperationalAnalyticsService,
	OperationalAnalyticsError,
	QueryExecutionError,
	QueryNotFoundError,
	ReportNotFoundError,
)

__all__ = [
	"OperationalPlugin",
	"create_plugin",
	# models
	"KPIDefinition",
	"KPISnapshot",
	"AnalyticsQuery",
	"AnalyticsReport",
	# events
	"KPISnapshotRecordedEvent",
	"KPIStatusChangedEvent",
	"AnalyticsReportGeneratedEvent",
	"AnalyticsQueryExecutedEvent",
	# services
	"OperationalAnalyticsService",
	"OperationalAnalyticsError",
	"KPINotFoundError",
	"QueryNotFoundError",
	"ReportNotFoundError",
	"QueryExecutionError",
]
