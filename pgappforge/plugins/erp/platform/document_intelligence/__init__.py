from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .services import DocumentIntelligenceService, create_document_extraction_table

if TYPE_CHECKING:
	pass

log = logging.getLogger(__name__)

_MENU_CATEGORY = "Document Intelligence"

__all__ = [
	"DocumentIntelligencePlugin",
	"DocumentIntelligenceService",
	"create_document_extraction_table",
]


class DocumentIntelligencePlugin(BasePlugin):
	"""Invoice OCR + KYC document extraction via LLM vision."""

	domain = "platform"
	depends_on: list[str] = ["foundation"]

	metadata = PluginMetadata(
		name="document_intelligence",
		version="1.0.0",
		description=(
			"Extract structured data from business documents using LLM vision. "
			"Supports invoices, national IDs, payslips, and bank statements. "
			"Persists results to pgaf_document_extraction for audit trail."
		),
		author="PgAppForge Contributors",
		tags=[
			"platform",
			"document-intelligence",
			"ocr",
			"kyc",
			"invoice",
			"ai",
			"vision",
		],
		priority=PluginPriority.NORMAL,
	)

	def get_events(self) -> list[type]:
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self, app=None) -> None:
		log.info("DocumentIntelligencePlugin initialized")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.document_intelligence.views import (
			DocumentIntelligenceView,
		)
		cat = self.config.get("DOCUMENT_INTELLIGENCE_MENU_CATEGORY", _MENU_CATEGORY)
		self.add_view(
			DocumentIntelligenceView,
			"Document Intelligence",
			icon="fa-file-text-o",
			category=cat,
		)
		log.info("DocumentIntelligencePlugin: views registered under %r", cat)

	def register_models(self) -> list[type]:
		return []

	def setup_tables(self, engine) -> None:
		"""Create pgaf_document_extraction table. Call once at app startup."""
		try:
			create_document_extraction_table(engine)
			log.info("DocumentIntelligencePlugin: tables ready")
		except Exception as exc:
			log.debug("DocumentIntelligencePlugin: table setup skipped: %s", exc)
