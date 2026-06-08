"""
pgappforge/plugins/erp/grc/anti_bribery/__init__.py

Anti-Bribery & Corruption plugin — gift/entertainment logging with configurable
thresholds, approval workflow, and conflict-of-interest declarations.

Regulatory alignment: FCPA, UK Bribery Act 2010, ISO 37001.

Events emitted:
  grc.anti_bribery.gift.logged
  grc.anti_bribery.gift.approval_required
  grc.anti_bribery.coi.submitted

Config keys (Flask app.config):
  GIFT_THRESHOLD_CENTS       — general gift threshold (default 50000 = $500)
  GOVT_GIFT_THRESHOLD_CENTS  — government official threshold (default 0 = any gift)

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.grc.anti_bribery"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AntiBriberyPlugin(BasePlugin):
	"""Anti-Bribery & Corruption — FCPA/UK Bribery Act gift logging and COI management."""

	name = "anti_bribery"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="anti_bribery",
			version="1.0.0",
			description=(
				"Anti-Bribery & Corruption — gift and entertainment logging with "
				"configurable FCPA/UK Bribery Act thresholds, government-official "
				"zero-tolerance enforcement, approval workflow, and COI declaration management."
			),
			author="PgAppForge Contributors",
			tags=[
				"grc", "anti-bribery", "fcpa", "uk-bribery-act",
				"gifts", "coi", "compliance",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ab_gifts_read",
				"can_ab_gifts_write",
				"can_ab_gifts_approve",
				"can_ab_coi_read",
				"can_ab_coi_write",
				"can_ab_coi_review",
				"can_ab_risk_exposure",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"grc.anti_bribery.gift.logged",
			"grc.anti_bribery.gift.approval_required",
			"grc.anti_bribery.coi.submitted",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"AB_MENU_CATEGORY": "GRC",
			"GIFT_THRESHOLD_CENTS": 500_00,
			"GOVT_GIFT_THRESHOLD_CENTS": 0,
		}
		self.config = {**defaults, **self.config}
		log.info("AntiBriberyPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.grc.anti_bribery.views import (
			GiftsRegisterDashboardView,
			GiftEntertainmentLogView,
			ConflictOfInterestDeclarationView,
		)
		cat = self.config.get("AB_MENU_CATEGORY", "GRC")
		self.add_view(GiftsRegisterDashboardView, "Gifts Register", icon="fa-gift", category=cat)
		self.add_view(GiftEntertainmentLogView, "Gift & Entertainment Log", icon="fa-list", category=cat)
		self.add_view(ConflictOfInterestDeclarationView, "COI Declarations", icon="fa-user-times", category=cat)
		log.info("AntiBriberyPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.grc.anti_bribery.models import (
			GiftEntertainmentLog,
			ConflictOfInterestDeclaration,
		)
		return [GiftEntertainmentLog, ConflictOfInterestDeclaration]


def create_plugin(
	appbuilder: Any, config: dict[str, Any] | None = None
) -> AntiBriberyPlugin:
	return AntiBriberyPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.grc.anti_bribery.models import (  # noqa: E402
	GiftEntertainmentLog,
	ConflictOfInterestDeclaration,
)
from pgappforge.plugins.erp.grc.anti_bribery.services import AntiBriberyService  # noqa: E402

__all__ = [
	"AntiBriberyPlugin",
	"create_plugin",
	"GiftEntertainmentLog",
	"ConflictOfInterestDeclaration",
	"AntiBriberyService",
]
