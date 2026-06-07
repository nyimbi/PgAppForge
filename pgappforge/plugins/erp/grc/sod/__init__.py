"""
pgappforge/plugins/erp/grc/sod/__init__.py

SoD Analyzer plugin — segregation-of-duties conflict detection, simulation,
bulk scanning, and risk acceptance workflow.

Events emitted:
  grc.sod.violation.detected
  grc.sod.risk.accepted
  grc.sod.bulk_scan.completed
  grc.sod.simulation.run

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.grc.sod"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SodPlugin(BasePlugin):
	"""SoD Analyzer — detects segregation-of-duties conflicts across FAB roles."""

	name = "sod"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="sod",
			version="1.0.0",
			description=(
				"Segregation-of-Duties Analyzer — 20 standard SoD conflicts across "
				"P2P, R2R, O2C, Payroll, and Access control categories. "
				"Supports bulk scanning, role-grant simulation, and risk acceptance."
			),
			author="PgAppForge Contributors",
			tags=[
				"grc", "sod", "segregation-of-duties", "sox",
				"access-control", "compliance",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_sod_conflicts_read",
				"can_sod_conflicts_write",
				"can_sod_violations_read",
				"can_sod_violations_write",
				"can_sod_bulk_scan",
				"can_sod_risk_accept",
				"can_sod_simulate",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"grc.sod.violation.detected",
			"grc.sod.risk.accepted",
			"grc.sod.bulk_scan.completed",
			"grc.sod.simulation.run",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SOD_MENU_CATEGORY": "GRC",
			"SOD_AUTO_SCAN_ON_ROLE_CHANGE": True,
		}
		self.config = {**defaults, **self.config}
		log.info("SodPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.grc.sod.models import SodConflict, SodViolation
		return [SodConflict, SodViolation]


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> SodPlugin:
	return SodPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.grc.sod.models import SodConflict, SodViolation  # noqa: E402
from pgappforge.plugins.erp.grc.sod.services import SodAnalyzerService  # noqa: E402

__all__ = [
	"SodPlugin",
	"create_plugin",
	"SodConflict",
	"SodViolation",
	"SodAnalyzerService",
]
