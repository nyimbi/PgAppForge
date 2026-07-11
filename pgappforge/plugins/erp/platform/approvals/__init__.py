"""
pgappforge/plugins/erp/platform/approvals/__init__.py

Platform approvals plugin registration.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.platform.approvals.models import ApprovalRequest, ApprovalStep
from pgappforge.plugins.erp.platform.approvals.services import ApprovalService
from pgappforge.plugins.erp.platform.approvals.views import PendingApprovalsView

log = logging.getLogger(__name__)


class ApprovalsPlugin(BasePlugin):
	"""Multi-level ERP approval workflow routing."""

	name = "approvals"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="approvals",
			version="1.0.0",
			description="Multi-level configurable approval workflows for ERP documents",
			author="PgAppForge Contributors",
			tags=["erp", "workflow", "approvals", "routing"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_approval_submit",
				"can_approval_approve",
				"can_approval_reject",
				"can_approval_inbox",
			],
		)

	def initialize(self) -> None:
		log.info("ApprovalsPlugin initialized")

	def get_events(self) -> list[str]:
		return [
			"platform.approvals.submitted",
			"platform.approvals.step_approved",
			"platform.approvals.completed",
			"platform.approvals.rejected",
			"platform.approvals.withdrawn",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def register_models(self) -> list[type]:
		return [ApprovalRequest, ApprovalStep]

	def register_views(self) -> None:
		cat = self.config.get("APPROVALS_MENU_CATEGORY", "ERP")
		self.add_view(PendingApprovalsView, "Pending Approvals", icon="fa-check-square-o", category=cat)
		log.info("ApprovalsPlugin: views registered under %r", cat)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> ApprovalsPlugin:
	return ApprovalsPlugin(appbuilder, config=config or {})


__all__ = [
	"ApprovalRequest",
	"ApprovalService",
	"ApprovalStep",
	"ApprovalsPlugin",
	"PendingApprovalsView",
	"create_plugin",
]
