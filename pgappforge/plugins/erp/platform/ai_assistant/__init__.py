"""
pgappforge/plugins/erp/platform/ai_assistant/__init__.py

Platform AI assistant plugin.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AIAssistantPlugin(BasePlugin):
	"""Platform AI assistant administration plugin."""

	name = "platform.ai_assistant"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.ai_assistant",
			version="1.0.0",
			description="AI assistant tool registry, audit trail, and session persistence.",
			author="PgAppForge Contributors",
			tags=["platform", "ai", "assistant", "audit"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"ai_assistant.write",
				"can_ai_audit_trail_list",
				"can_ai_audit_trail_show",
			],
			safe_mode_compatible=True,
		)

	def initialize(self) -> None:
		self.config = {
			"AI_ASSISTANT_MENU_CATEGORY": "Platform",
			**self.config,
		}
		log.info("AIAssistantPlugin initialised")

	def post_initialize(self) -> None:
		super().post_initialize()
		try:
			from .models import ensure_schema
			ensure_schema(self.appbuilder.get_session)
		except Exception as exc:
			log.debug("AIAssistantPlugin: schema setup skipped: %s", exc)

	def register_views(self) -> None:
		from .views import AIAuditTrailView
		category = self.config.get("AI_ASSISTANT_MENU_CATEGORY", "Platform")
		self.add_view(
			AIAuditTrailView,
			"AI Audit Trail",
			icon="fa-shield",
			category=category,
			category_icon="fa-cogs",
		)
		log.info("AIAssistantPlugin: AIAuditTrailView registered under %r", category)

	def register_models(self) -> list[type]:
		from .models import AuditLog, ConversationMessage, ConversationSession
		return [AuditLog, ConversationSession, ConversationMessage]

	def setup_tables(self, engine: Any) -> None:
		from .models import ensure_schema
		ensure_schema(engine)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> AIAssistantPlugin:
	return AIAssistantPlugin(appbuilder, config=config or {})


from .models import AuditLog, ConversationMessage, ConversationSession  # noqa: E402
from .services import AIAssistantService  # noqa: E402
from .tools import (  # noqa: E402
	READ_TOOL_NAMES,
	TOOL_SCHEMAS,
	WRITE_TOOL_NAMES,
	build_tool_registry,
	create_purchase_requisition,
	get_compliance_overdue,
	get_employee_leave_balance,
	get_procurement_savings_ytd,
	get_project_status,
	get_risk_heatmap_summary,
	get_vendor_risk_score,
	log_risk,
	schedule_compliance_check,
)
from .views import AIAuditTrailView  # noqa: E402

__all__ = [
	"AIAssistantPlugin",
	"AIAssistantService",
	"AIAuditTrailView",
	"AuditLog",
	"ConversationSession",
	"ConversationMessage",
	"create_plugin",
	"get_project_status",
	"get_vendor_risk_score",
	"get_employee_leave_balance",
	"get_procurement_savings_ytd",
	"get_compliance_overdue",
	"get_risk_heatmap_summary",
	"create_purchase_requisition",
	"log_risk",
	"schedule_compliance_check",
	"TOOL_SCHEMAS",
	"READ_TOOL_NAMES",
	"WRITE_TOOL_NAMES",
	"build_tool_registry",
]
