"""
pgappforge/plugins/erp/platform/report_builder/__init__.py

No-Code Report Builder plugin — ReportBro integration for PDF/Excel reports.

Provides:
  - Browser-based report designer (ReportBro JS, MIT license)
  - Server-side PDF rendering via reportbro-lib
  - SavedReport model (pgaf_report table, JSONB definition)
  - Tenant-scoped report gallery with template support

pip install reportbro-lib   # optional — enables PDF generation
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.platform.report_builder.models import SavedReport
from pgappforge.plugins.erp.platform.report_builder.services import (
	ReportBuilderService,
	create_report_tables,
)

if TYPE_CHECKING:
	pass

log = logging.getLogger(__name__)

_MENU_CATEGORY = "Reports"

__all__ = [
	"ReportBuilderPlugin",
	"ReportBuilderService",
	"SavedReport",
	"create_report_tables",
]


class ReportBuilderPlugin(BasePlugin):
	"""No-code PDF report designer powered by ReportBro (MIT).

	Activate in your app factory::

		from pgappforge.plugins.erp.platform.report_builder import ReportBuilderPlugin
		plugin = ReportBuilderPlugin(appbuilder)
		plugin.activate()

	Config keys (all optional):
		REPORT_BUILDER_MENU_CATEGORY   -- menu category label (default: "Reports")
	"""

	domain = "platform"
	name = "report_builder"
	depends_on: list[str] = ["foundation"]

	metadata = PluginMetadata(
		name="report_builder",
		version="1.0.0",
		description=(
			"No-code PDF report designer using ReportBro (MIT). "
			"Design reports in the browser, render PDFs server-side, "
			"query any SQL data source."
		),
		author="PgAppForge Contributors",
		tags=["platform", "reports", "pdf", "reportbro", "no-code"],
		priority=PluginPriority.NORMAL,
	)

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self, app=None) -> None:
		log.info("ReportBuilderPlugin initialized")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.report_builder.views import ReportBuilderView
		cat = self.config.get("REPORT_BUILDER_MENU_CATEGORY", _MENU_CATEGORY)
		self.add_view(
			ReportBuilderView,
			"Report Builder",
			icon="fa-file-pdf-o",
			category=cat,
		)
		log.info("ReportBuilderPlugin: views registered under %r", cat)

	def register_models(self) -> list[type]:
		return [SavedReport]

	def setup_tables(self, engine) -> None:
		"""Create pgaf_report table.  Call once at app startup."""
		try:
			create_report_tables(engine)
			log.info("ReportBuilderPlugin: tables ready")
		except Exception as exc:
			log.debug("ReportBuilderPlugin: table setup skipped: %s", exc)
