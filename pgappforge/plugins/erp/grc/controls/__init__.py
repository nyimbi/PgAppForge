"""
pgappforge/plugins/erp/grc/controls/__init__.py

GRC Controls plugin — control frameworks, control testing, and SoD enforcement.

Events emitted:
  grc.control.created / status_changed
  grc.control_test.completed / deficiency_noted
  grc.sod.conflict_detected

Events consumed:
  identity.policy.changed — trigger SoD re-evaluation on role changes
  party.created           — populate control ownership candidates

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.grc.controls"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class GRCControlsPlugin(BasePlugin):
	"""GRC Controls plugin — internal controls management and SoD enforcement."""

	name = "grc.controls"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="grc.controls",
			version="1.0.0",
			description=(
				"GRC Controls — SOX/ISO27001/NIST/GDPR/HIPAA/PCI_DSS "
				"control frameworks, periodic testing, and SoD conflict matrix."
			),
			author="PgAppForge Contributors",
			tags=["grc", "controls", "sox", "iso27001", "compliance", "sod"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_grc_frameworks_read",
				"can_grc_frameworks_write",
				"can_grc_controls_read",
				"can_grc_controls_write",
				"can_grc_tests_record",
				"can_grc_sod_read",
				"can_grc_sod_write",
				"can_grc_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"grc.control.created",
			"grc.control.status_changed",
			"grc.control_test.completed",
			"grc.control_test.deficiency_noted",
			"grc.sod.conflict_detected",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"identity.policy.changed",
			"party.created",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"GRC_CONTROLS_MENU_CATEGORY": "GRC",
			"GRC_SOD_AUTO_CHECK": True,
		}
		self.config = {**defaults, **self.config}
		log.info("GRCControlsPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.grc.controls.views import (
			ControlFrameworkView,
			ControlView,
			ControlTestView,
			SoDView,
			ControlReportView,
		)
		cat = self.config.get("GRC_CONTROLS_MENU_CATEGORY", "GRC")
		self.add_view(ControlFrameworkView, "Control Frameworks", icon="fa-sitemap", category=cat)
		self.add_view(ControlView, "Controls", icon="fa-check-square", category=cat)
		self.add_view(SoDView, "Segregation of Duties", icon="fa-random", category=cat)
		self.add_view(ControlReportView, "Controls Reports", icon="fa-bar-chart", category=cat)
		self.add_view_no_menu(ControlTestView)
		log.info("GRCControlsPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.grc.controls.models import (
			ControlFramework, Control, ControlTest, SegregationOfDuties,
		)
		return [ControlFramework, Control, ControlTest, SegregationOfDuties]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 rulesets for GRC Controls domain."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "control.type_valid",
				"description": "control_type must be PREVENTIVE|DETECTIVE|CORRECTIVE",
				"model_name": "Control",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_control_type",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "control_type", "op": "not_in",
							 "value": ["PREVENTIVE", "DETECTIVE", "CORRECTIVE"]}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "control_type must be PREVENTIVE, DETECTIVE, or CORRECTIVE"}
						],
					}
				],
			},
			{
				"name": "control_test.result_valid",
				"description": "test_result must be EFFECTIVE|INEFFECTIVE|NOT_TESTED",
				"model_name": "ControlTest",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_test_result",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "test_result", "op": "not_in",
							 "value": ["EFFECTIVE", "INEFFECTIVE", "NOT_TESTED"]}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "test_result must be EFFECTIVE, INEFFECTIVE, or NOT_TESTED"}
						],
					}
				],
			},
			{
				"name": "control_test.remediation_requires_deficiency",
				"description": "remediation_due requires deficiencies_noted to be set",
				"model_name": "ControlTest",
				"stop_on_match": True,
				"rules": [
					{
						"name": "remediation_needs_deficiency",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "remediation_due", "op": "exists", "value": True},
							{"field": "deficiencies_noted", "op": "eq", "value": None},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "remediation_due requires deficiencies_noted to be set"}
						],
					}
				],
			},
			{
				"name": "sod.bidirectional_uniqueness",
				"description": "SoD (A,B) and (B,A) are the same conflict — only one row needed",
				"model_name": "SegregationOfDuties",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_reverse_duplicate",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "role_a", "op": "eq", "value": "{{role_b}}"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "role_a and role_b cannot be the same role"}
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
		log.info("GRCControlsPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> GRCControlsPlugin:
	return GRCControlsPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.grc.controls.models import (  # noqa: E402
	ControlFramework, Control, ControlTest, SegregationOfDuties,
)
from pgappforge.plugins.erp.grc.controls.services import (  # noqa: E402
	ControlsService, ControlsServiceError, ControlNotFoundError,
	FrameworkNotFoundError, SoDConflictError,
)

__all__ = [
	"GRCControlsPlugin",
	"create_plugin",
	"ControlFramework",
	"Control",
	"ControlTest",
	"SegregationOfDuties",
	"ControlsService",
	"ControlsServiceError",
	"ControlNotFoundError",
	"FrameworkNotFoundError",
	"SoDConflictError",
]
