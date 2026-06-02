"""
pgappforge/plugins/erp/grc/sustainability/__init__.py

GRC Sustainability plugin — GHG emissions tracking (GHG Protocol Scopes 1/2/3)
and ESG metric management (GRI/SASB/TCFD/CDP frameworks).

Events emitted:
  sustainability.emission.recorded / verified
  sustainability.esg_metric.target_set
  sustainability.esg_snapshot.captured / target_missed

Events consumed:
  operations.production.completed — auto-record scope 1 emissions from production
  finance.ap.invoice_approved     — capture scope 3 spend-based emissions

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.grc.sustainability"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class GRCSustainabilityPlugin(BasePlugin):
	"""GRC Sustainability plugin — ESG / GHG emissions management."""

	name = "grc.sustainability"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="grc.sustainability",
			version="1.0.0",
			description=(
				"ESG & Sustainability — GHG Protocol Scopes 1/2/3 emission tracking, "
				"ESG metric management (GRI/SASB/TCFD/CDP), and annual snapshot reporting."
			),
			author="PgAppForge Contributors",
			tags=["grc", "esg", "sustainability", "ghg", "emissions", "climate"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_sustainability_sources_read",
				"can_sustainability_sources_write",
				"can_sustainability_records_read",
				"can_sustainability_records_write",
				"can_sustainability_records_verify",
				"can_sustainability_metrics_read",
				"can_sustainability_metrics_write",
				"can_sustainability_snapshots_read",
				"can_sustainability_snapshots_write",
				"can_sustainability_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"sustainability.emission.recorded",
			"sustainability.emission.verified",
			"sustainability.esg_metric.target_set",
			"sustainability.esg_snapshot.captured",
			"sustainability.esg_snapshot.target_missed",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"operations.production.completed",
			"finance.ap.invoice_approved",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SUSTAINABILITY_MENU_CATEGORY": "GRC",
			"SUSTAINABILITY_DEFAULT_DATA_QUALITY": "MEDIUM",
		}
		self.config = {**defaults, **self.config}
		log.info("GRCSustainabilityPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.grc.sustainability.views import (
			EmissionSourceView,
			EmissionRecordView,
			ESGMetricView,
			ESGSnapshotView,
			SustainabilityReportView,
		)
		cat = self.config.get("SUSTAINABILITY_MENU_CATEGORY", "GRC")
		self.add_view(EmissionSourceView, "Emission Sources", icon="fa-leaf", category=cat)
		self.add_view(EmissionRecordView, "Emission Records", icon="fa-cloud", category=cat)
		self.add_view(ESGMetricView, "ESG Metrics", icon="fa-line-chart", category=cat)
		self.add_view(ESGSnapshotView, "ESG Snapshots", icon="fa-camera", category=cat)
		self.add_view(
			SustainabilityReportView, "Sustainability Reports",
			icon="fa-bar-chart", category=cat,
		)
		log.info("GRCSustainabilityPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.grc.sustainability.models import (
			EmissionSource, EmissionRecord, ESGMetric, ESGSnapshot,
		)
		return [EmissionSource, EmissionRecord, ESGMetric, ESGSnapshot]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 rulesets for sustainability domain invariants."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "emission_source.scope_valid",
				"description": "Scope must be 1, 2, or 3 (GHG Protocol)",
				"model_name": "EmissionSource",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_ghg_scope",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "scope", "op": "not_in", "value": [1, 2, 3]}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "scope must be 1, 2, or 3 (GHG Protocol)"}
						],
					}
				],
			},
			{
				"name": "emission_source.positive_factor",
				"description": "emission_factor must be positive",
				"model_name": "EmissionSource",
				"stop_on_match": True,
				"rules": [
					{
						"name": "positive_emission_factor",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "emission_factor", "op": "lte", "value": 0}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "emission_factor must be positive"}
						],
					}
				],
			},
			{
				"name": "emission_record.verified_immutable",
				"description": "Verified emission records cannot be modified; insert a correction",
				"model_name": "EmissionRecord",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_verified_update",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_verified", "op": "eq", "value": True}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Verified EmissionRecord is immutable; insert a correction record"}
						],
					}
				],
			},
			{
				"name": "esg_snapshot.unique_per_year",
				"description": "Only one ESGSnapshot per metric per year",
				"model_name": "ESGSnapshot",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_duplicate_snapshot",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "_duplicate_exists", "op": "eq", "value": True}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "ESGSnapshot already exists for this metric and year"}
						],
					}
				],
			},
			{
				"name": "esg_metric.pillar_valid",
				"description": "pillar must be ENVIRONMENTAL|SOCIAL|GOVERNANCE",
				"model_name": "ESGMetric",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_pillar",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "pillar", "op": "not_in",
							 "value": ["ENVIRONMENTAL", "SOCIAL", "GOVERNANCE"]}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "pillar must be ENVIRONMENTAL, SOCIAL, or GOVERNANCE"}
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
		log.info("GRCSustainabilityPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(
	appbuilder: Any, config: dict[str, Any] | None = None
) -> GRCSustainabilityPlugin:
	return GRCSustainabilityPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.grc.sustainability.models import (  # noqa: E402
	EmissionSource, EmissionRecord, ESGMetric, ESGSnapshot,
)
from pgappforge.plugins.erp.grc.sustainability.services import (  # noqa: E402
	SustainabilityService, SustainabilityServiceError,
	EmissionSourceNotFoundError, ESGMetricNotFoundError,
	ESGSnapshotExistsError, VerifiedRecordError,
)

__all__ = [
	"GRCSustainabilityPlugin",
	"create_plugin",
	"EmissionSource",
	"EmissionRecord",
	"ESGMetric",
	"ESGSnapshot",
	"SustainabilityService",
	"SustainabilityServiceError",
	"EmissionSourceNotFoundError",
	"ESGMetricNotFoundError",
	"ESGSnapshotExistsError",
	"VerifiedRecordError",
]
