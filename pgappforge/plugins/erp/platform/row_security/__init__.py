from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .events import (
	RowSecurityPolicyCreatedEvent,
	RowSecurityPolicyUpdatedEvent,
	SecurityContextComputedEvent,
)
from .models import RowSecurityPolicy, SecurityContext
from .services import RowSecurityService

if TYPE_CHECKING:
	from sqlalchemy.orm import Session

__all__ = [
	"RowSecurityPlugin",
	"RowSecurityService",
	"RowSecurityPolicy",
	"SecurityContext",
	"RowSecurityPolicyCreatedEvent",
	"RowSecurityPolicyUpdatedEvent",
	"SecurityContextComputedEvent",
]

log = logging.getLogger(__name__)


class RowSecurityPlugin(BasePlugin):
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	metadata = PluginMetadata(
		name="row_security",
		version="1.0.0",
		description=(
			"Row-level security framework: policy definition per FAB role + entity type, "
			"per-user scope caching, and SQLAlchemy statement filter injection. "
			"Workday/Oracle-style data access control without Postgres RLS DDL."
		),
		author="PgAppForge Contributors",
		tags=[
			"platform",
			"security",
			"row-level",
			"rbac",
			"workday",
			"data-access",
		],
		priority=PluginPriority.HIGH,
	)

	def get_events(self) -> list[type]:
		return [
			RowSecurityPolicyCreatedEvent,
			RowSecurityPolicyUpdatedEvent,
			SecurityContextComputedEvent,
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self, app=None) -> None:
		log.info("RowSecurityPlugin initialized")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.row_security.views import (
			RowSecurityAdminView,
			RowSecurityPolicyView,
			SecurityContextView,
		)
		cat = self.config.get("ROW_SECURITY_MENU_CATEGORY", "Platform Admin")
		self.add_view(RowSecurityAdminView, "Row Security", icon="fa-shield", category=cat)
		self.add_view(RowSecurityPolicyView, "Policies", icon="fa-lock", category=cat)
		self.add_view(SecurityContextView, "Security Contexts", icon="fa-user-secret", category=cat)
		log.info("RowSecurityPlugin: views registered under %r", cat)

	def register_models(self) -> list[type]:
		return [RowSecurityPolicy, SecurityContext]
