"""
pgappforge/plugins/erp/grc/ethics/__init__.py

Ethics Hotline plugin — anonymous whistleblower reporting, case management,
and compliance dashboard.

PII discipline: reporter identity never enters domain events or logs.
Tracking tokens are SHA-256 hashed server-side; raw token returned once only.

Events emitted:
  grc.ethics.report.submitted
  grc.ethics.case.opened
  grc.ethics.case.resolved
  grc.ethics.report.status.updated

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.grc.ethics"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class EthicsHotlinePlugin(BasePlugin):
	"""Ethics Hotline — anonymous whistleblower reporting with PII-safe events."""

	name = "ethics"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="ethics",
			version="1.0.0",
			description=(
				"Ethics Hotline — anonymous report submission with SHA-256 token tracking, "
				"investigation case management with confidential timeline, "
				"and compliance dashboard. PII never stored in domain events."
			),
			author="PgAppForge Contributors",
			tags=[
				"grc", "ethics", "whistleblower", "hotline",
				"anonymous-reporting", "compliance",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ethics_report_submit",
				"can_ethics_report_status",
				"can_ethics_cases_read",
				"can_ethics_cases_write",
				"can_ethics_cases_resolve",
				"can_ethics_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"grc.ethics.report.submitted",
			"grc.ethics.case.opened",
			"grc.ethics.case.resolved",
			"grc.ethics.report.status.updated",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"ETHICS_MENU_CATEGORY": "GRC",
			"ETHICS_DEFAULT_SEVERITY": "MEDIUM",
		}
		self.config = {**defaults, **self.config}
		log.info("EthicsHotlinePlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.grc.ethics.views import (
			EthicsHotlineDashboardView,
			EthicsReportView,
			EthicsCaseView,
		)
		cat = self.config.get("ETHICS_MENU_CATEGORY", "GRC")
		self.add_view(EthicsHotlineDashboardView, "Ethics Hotline", icon="fa-flag", category=cat)
		self.add_view(EthicsReportView, "Reports", icon="fa-file-text-o", category=cat)
		self.add_view(EthicsCaseView, "Cases", icon="fa-folder-open", category=cat)
		log.info("EthicsHotlinePlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.grc.ethics.models import EthicsReport, EthicsCase
		return [EthicsReport, EthicsCase]


def create_plugin(
	appbuilder: Any, config: dict[str, Any] | None = None
) -> EthicsHotlinePlugin:
	return EthicsHotlinePlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.grc.ethics.models import EthicsReport, EthicsCase  # noqa: E402
from pgappforge.plugins.erp.grc.ethics.services import EthicsHotlineService  # noqa: E402

__all__ = [
	"EthicsHotlinePlugin",
	"create_plugin",
	"EthicsReport",
	"EthicsCase",
	"EthicsHotlineService",
]
