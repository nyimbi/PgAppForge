"""
pgappforge/plugins/erp/platform/document_management/__init__.py

ERP document attachment plugin.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.platform.document_management.models import Attachment
from pgappforge.plugins.erp.platform.document_management.services import AttachmentService
from pgappforge.plugins.erp.platform.document_management.views import AttachmentView

log = logging.getLogger(__name__)


class DocumentManagementPlugin(BasePlugin):
	"""ERP entity attachment endpoints."""

	name = "platform.document_management"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.document_management",
			version="1.0.0",
			description="Document attachments for ERP entities",
			author="PgAppForge Contributors",
			tags=["erp", "platform", "attachments", "documents"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_attachment_upload",
				"can_attachment_download",
				"can_attachment_delete",
			],
			safe_mode_compatible=True,
		)

	def initialize(self) -> None:
		log.info("DocumentManagementPlugin initialised")

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def register_models(self) -> list[type]:
		return [Attachment]

	def register_views(self) -> None:
		self.add_view_no_menu(AttachmentView)
		log.info("DocumentManagementPlugin: AttachmentView registered")


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> DocumentManagementPlugin:
	return DocumentManagementPlugin(appbuilder, config=config or {})


__all__ = [
	"Attachment",
	"AttachmentService",
	"AttachmentView",
	"DocumentManagementPlugin",
	"create_plugin",
]
