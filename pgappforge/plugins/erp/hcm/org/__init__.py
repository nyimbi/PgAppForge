"""
pgappforge/plugins/erp/hcm/org/__init__.py

OrgPlugin — HCM Org Management ERP plugin.

Entities managed:
  LegalEntity → OrgUnit (hierarchy) → Position
  JobCatalog  → CompensationGrade (effective-dated bands)

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.org.legal_entity.created
  hcm.org.legal_entity.deactivated
  hcm.org.unit.created
  hcm.org.unit.restructured
  hcm.org.position.created
  hcm.org.position.filled
  hcm.org.position.vacated
  hcm.org.job_catalog.created
  hcm.org.compensation_grade.published

Events consumed:
  hcm.personnel.employee.assigned    — fill position
  hcm.personnel.employee.terminated  — vacate position

Usage::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.org",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class OrgPlugin(BasePlugin):
	"""HCM Org Management plugin.

	Registers 6 view groups (LegalEntity, OrgUnit, Position, JobCatalog,
	CompensationGrade, OrgReports).
	Pre-configures 3 Rules Engine rulesets on first run.
	"""

	name = "hcm.org"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="hcm.org",
			version="1.0.0",
			description=(
				"HCM Org Management — legal entities, org chart hierarchy, "
				"budgeted positions, job catalog, and effective-dated compensation grades."
			),
			author="PgAppForge Contributors",
			tags=["erp", "hcm", "org", "positions", "jobs", "compensation"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_hcm_org_entity_list",
				"can_hcm_org_entity_write",
				"can_hcm_org_unit_list",
				"can_hcm_org_unit_write",
				"can_hcm_org_position_list",
				"can_hcm_org_position_write",
				"can_hcm_org_position_fill",
				"can_hcm_org_job_list",
				"can_hcm_org_job_write",
				"can_hcm_org_grade_list",
				"can_hcm_org_grade_publish",
				"can_hcm_org_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.org.legal_entity.created",
			"hcm.org.legal_entity.deactivated",
			"hcm.org.unit.created",
			"hcm.org.unit.restructured",
			"hcm.org.position.created",
			"hcm.org.position.filled",
			"hcm.org.position.vacated",
			"hcm.org.job_catalog.created",
			"hcm.org.compensation_grade.published",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.personnel.employee.assigned",
			"hcm.personnel.employee.terminated",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"HCM_ORG_MENU_CATEGORY": "HCM — Organisation",
		}
		self.config = {**defaults, **self.config}
		log.info("OrgPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.org.views import (
			LegalEntityView,
			OrgUnitView,
			PositionView,
			JobCatalogView,
			CompensationGradeView,
			OrgReportView,
		)

		cat = self.config.get("HCM_ORG_MENU_CATEGORY", "HCM — Organisation")

		self.add_view(LegalEntityView, "Legal Entities", icon="fa-building", category=cat)
		self.add_view(OrgUnitView, "Org Units", icon="fa-sitemap", category=cat)
		self.add_view(PositionView, "Positions", icon="fa-user-plus", category=cat)
		self.add_view(JobCatalogView, "Job Catalog", icon="fa-briefcase", category=cat)
		self.add_view(CompensationGradeView, "Compensation Grades", icon="fa-dollar", category=cat)
		self.add_view(OrgReportView, "Org Reports", icon="fa-bar-chart", category=cat)

		log.info("OrgPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.org.models import (
			LegalEntity,
			OrgUnit,
			JobCatalog,
			CompensationGrade,
			Position,
		)
		return [LegalEntity, OrgUnit, JobCatalog, CompensationGrade, Position]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 3 Rules Engine rulesets for HCM Org domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("OrgPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "hcm.org.position.salary_within_grade",
				"description": "Position graded salary must fall within the comp grade band",
				"model_name": "Position",
				"stop_on_match": True,
				"rules": [
					{
						"name": "min_within_grade_max",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "graded_salary_min_cents", "op": "gt", "value": "graded_salary_max_cents"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Position graded_salary_min_cents must be <= graded_salary_max_cents"}
						],
					},
				],
			},
			{
				"name": "hcm.org.position.no_fill_inactive",
				"description": "Cannot fill an inactive position",
				"model_name": "Position",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_fill_inactive_position",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "is_filled", "op": "eq", "value": True},
							{"field": "is_active", "op": "eq", "value": False},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Cannot fill an inactive position — activate it first"}
						],
					},
				],
			},
			{
				"name": "hcm.org.compensation_grade.positive_amounts",
				"description": "Comp grade min/mid/max must all be positive integers",
				"model_name": "CompensationGrade",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_grade_amounts",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "min_cents", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "CompensationGrade min_cents must be > 0"}
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
		log.info("OrgPlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> OrgPlugin:
	"""Construct an OrgPlugin without activating it."""
	return OrgPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.org.models import (  # noqa: E402
	LegalEntity,
	OrgUnit,
	JobCatalog,
	CompensationGrade,
	Position,
)
from pgappforge.plugins.erp.hcm.org.events import (  # noqa: E402
	LegalEntityCreatedEvent,
	LegalEntityDeactivatedEvent,
	OrgUnitCreatedEvent,
	OrgUnitRestructuredEvent,
	PositionCreatedEvent,
	PositionFilledEvent,
	PositionVacatedEvent,
	JobCatalogCreatedEvent,
	CompensationGradePublishedEvent,
)
from pgappforge.plugins.erp.hcm.org.services import (  # noqa: E402
	OrgService,
	OrgServiceError,
	LegalEntityNotFoundError,
	OrgUnitNotFoundError,
	PositionNotFoundError,
	PositionAlreadyFilledError,
)

__all__ = [
	# plugin
	"OrgPlugin",
	"create_plugin",
	# models
	"LegalEntity",
	"OrgUnit",
	"JobCatalog",
	"CompensationGrade",
	"Position",
	# events
	"LegalEntityCreatedEvent",
	"LegalEntityDeactivatedEvent",
	"OrgUnitCreatedEvent",
	"OrgUnitRestructuredEvent",
	"PositionCreatedEvent",
	"PositionFilledEvent",
	"PositionVacatedEvent",
	"JobCatalogCreatedEvent",
	"CompensationGradePublishedEvent",
	# services
	"OrgService",
	"OrgServiceError",
	"LegalEntityNotFoundError",
	"OrgUnitNotFoundError",
	"PositionNotFoundError",
	"PositionAlreadyFilledError",
]
