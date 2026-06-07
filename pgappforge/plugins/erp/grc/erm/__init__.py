"""
pgappforge/plugins/erp/grc/erm/__init__.py

Enterprise Risk Management plugin — risk register, heat map, mitigation actions,
and KRI threshold monitoring.

Events emitted:
  grc.erm.risk.created
  grc.erm.risk.score.updated
  grc.erm.kri.breach
  grc.erm.treatment.updated

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.grc.erm"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ErmPlugin(BasePlugin):
	"""Enterprise Risk Management — ISO 31000-aligned risk register with KRI monitoring."""

	name = "erm"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="erm",
			version="1.0.0",
			description=(
				"Enterprise Risk Management — 5×5 heat map, likelihood/impact scoring, "
				"mitigation action tracking, and KRI threshold alerting. "
				"Aligned with ISO 31000 risk treatment vocabulary."
			),
			author="PgAppForge Contributors",
			tags=[
				"grc", "erm", "enterprise-risk", "risk-register",
				"kri", "iso31000",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_erm_risks_read",
				"can_erm_risks_write",
				"can_erm_mitigations_read",
				"can_erm_mitigations_write",
				"can_erm_kri_read",
				"can_erm_kri_write",
				"can_erm_heat_map",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"grc.erm.risk.created",
			"grc.erm.risk.score.updated",
			"grc.erm.kri.breach",
			"grc.erm.treatment.updated",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"ERM_MENU_CATEGORY": "GRC",
			"ERM_KRI_MONITOR_INTERVAL_MINUTES": 60,
		}
		self.config = {**defaults, **self.config}
		log.info("ErmPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.grc.erm.models import (
			RiskRegister,
			RiskMitigationAction,
			KeyRiskIndicator,
		)
		return [RiskRegister, RiskMitigationAction, KeyRiskIndicator]


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> ErmPlugin:
	return ErmPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.grc.erm.models import (  # noqa: E402
	RiskRegister,
	RiskMitigationAction,
	KeyRiskIndicator,
)
from pgappforge.plugins.erp.grc.erm.services import ErmService  # noqa: E402

__all__ = [
	"ErmPlugin",
	"create_plugin",
	"RiskRegister",
	"RiskMitigationAction",
	"KeyRiskIndicator",
	"ErmService",
]
