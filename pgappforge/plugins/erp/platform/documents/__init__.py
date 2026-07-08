"""
pgappforge/plugins/erp/platform/documents/__init__.py

Platform Documents plugin — Document Management System (DMS).

Features:
  - Upload, version, and archive documents
  - Per-document ACL (VIEW / COMMENT / EDIT / ADMIN) for users and roles
  - Hierarchical folder tree with materialised path strings
  - PostgreSQL full-text search via tsvector / plainto_tsquery
  - JSONB tag index for fast containment queries
  - Cross-plugin attachment: bind any document to any module's record
  - BPM action hooks: attach document, request e-signature

Events emitted:
  platform.documents.uploaded
  platform.documents.version_created
  platform.documents.tagged
  platform.documents.shared
  platform.documents.archived
  platform.documents.signature.requested

Events consumed:
  (none — documents is a leaf plugin consumed by upstream workflows)

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.platform.documents"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class DocumentsPlugin(BasePlugin):
	"""Platform Document Management System plugin."""

	name = "documents"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.documents",
			version="1.0.0",
			description=(
				"Document Management System — upload, version, tag, share, "
				"archive documents with PostgreSQL full-text search."
			),
			author="PgAppForge Contributors",
			tags=["platform", "dms", "documents", "full-text-search"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_documents_create",
				"can_documents_read",
				"can_documents_edit",
				"can_documents_delete",
				"can_documents_archive",
				"can_documents_share",
				"can_documents_version_create",
				"can_documents_version_read",
				"can_documents_folder_create",
				"can_documents_folder_edit",
				"can_documents_folder_delete",
				"can_documents_access_manage",
				"can_documents_signature_request",
				"can_documents_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.documents.uploaded",
			"platform.documents.version_created",
			"platform.documents.tagged",
			"platform.documents.shared",
			"platform.documents.archived",
			"platform.documents.signature.requested",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"DOCUMENTS_MENU_CATEGORY": "Documents",
			"DOCUMENTS_STORAGE_PATH": "/var/app/uploads/documents",
		}
		self.config = {**defaults, **self.config}
		log.info("DocumentsPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.documents.models import (
			Document,
			DocumentAccess,
			DocumentFolder,
			DocumentVersion,
		)
		return [Document, DocumentVersion, DocumentFolder, DocumentAccess]

	def register_views(self) -> None:
		"""Views registration — stub; concrete views to be added in a follow-up."""
		log.info("DocumentsPlugin: no views registered (stub)")

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 2 rulesets for DMS domain invariants.

		1. documents.access.deny_deleted  — block access to DELETED documents
		2. documents.version.require_change_summary_on_major — enforce change_summary
		   when version_number is a round multiple of 10 (major milestone versions)
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.warning("DocumentsPlugin.setup_rules: rules plugin not available; skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "documents.access.deny_deleted",
				"description": (
					"Block any read or write operation on a Document whose "
					"status is DELETED."
				),
				"model_name": "Document",
				"stop_on_match": True,
				"rules": [
					{
						"name": "deny_deleted_document_access",
						"trigger_event": "on_before_read",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "DELETED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Access denied: document has been deleted"
								),
							}
						],
					},
					{
						"name": "deny_deleted_document_write",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "DELETED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Write denied: document has been deleted"
								),
							}
						],
					},
				],
			},
			{
				"name": "documents.version.require_change_summary_on_major",
				"description": (
					"Require a non-empty change_summary on DocumentVersion rows "
					"whose version_number is a multiple of 10 (major milestones)."
				),
				"model_name": "DocumentVersion",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_change_summary_major",
						"trigger_event": "on_before_create",
						"conditions_json": [
							# version_number % 10 == 0  →  major milestone
							{"field": "version_number", "op": "modulo_eq", "value": [10, 0]},
							{"field": "change_summary", "op": "is_blank", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"change_summary is required for major version milestones "
									"(version_number divisible by 10)"
								),
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

		log.info(
			"DocumentsPlugin.setup_rules: %d rulesets configured",
			len(RULESETS),
		)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> DocumentsPlugin:
	return DocumentsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Convenience re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.platform.documents.models import (  # noqa: E402
	Document,
	DocumentAccess,
	DocumentFolder,
	DocumentVersion,
)
from pgappforge.plugins.erp.platform.documents.services import (  # noqa: E402
	DocumentService,
	DocumentServiceError,
	DocumentValidationError,
	DocumentNotFoundError,
	DocumentAccessError,
	DocumentStateError,
)
from pgappforge.plugins.erp.platform.documents.events import (  # noqa: E402
	DocumentArchivedEvent,
	DocumentSharedEvent,
	DocumentSignatureRequestedEvent,
	DocumentTaggedEvent,
	DocumentUploadedEvent,
	DocumentVersionCreatedEvent,
)

__all__ = [
	# Plugin class
	"DocumentsPlugin",
	"create_plugin",
	# Models
	"Document",
	"DocumentVersion",
	"DocumentFolder",
	"DocumentAccess",
	# Service
	"DocumentService",
	"DocumentServiceError",
	"DocumentValidationError",
	"DocumentNotFoundError",
	"DocumentAccessError",
	"DocumentStateError",
	# Events
	"DocumentUploadedEvent",
	"DocumentVersionCreatedEvent",
	"DocumentTaggedEvent",
	"DocumentSharedEvent",
	"DocumentArchivedEvent",
	"DocumentSignatureRequestedEvent",
]
