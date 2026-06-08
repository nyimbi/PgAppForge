"""
pgappforge/plugins/erp/crm/loyalty/__init__.py

LoyaltyPlugin — Customer Loyalty Engine.

Domain:    crm
Depends:   foundation

Events emitted
--------------
  crm.loyalty.customer.enrolled
  crm.loyalty.points.earned
  crm.loyalty.points.redeemed
  crm.loyalty.tier.upgraded
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class LoyaltyPlugin(BasePlugin):
	"""Customer Loyalty Engine plugin.

	Covers program definition, customer enrolment, points earning and
	redemption, automatic tier upgrades, points expiry, and liability reporting.
	"""

	name = "loyalty"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="loyalty",
			version="1.0.0",
			description=(
				"Customer Loyalty Engine — programs, points earn/redeem, "
				"tier upgrades, expiry, and outstanding liability reports."
			),
			author="PgAppForge Contributors",
			tags=["crm", "loyalty", "points", "tier", "gamification"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_loy_program_read",
				"can_loy_program_write",
				"can_loy_account_read",
				"can_loy_account_enroll",
				"can_loy_points_earn",
				"can_loy_points_redeem",
				"can_loy_expiry_run",
				"can_loy_report_liability",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"crm.loyalty.customer.enrolled",
			"crm.loyalty.points.earned",
			"crm.loyalty.points.redeemed",
			"crm.loyalty.tier.upgraded",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"LOYALTY_DEFAULT_EARN_RATE": "1.0",
			"LOYALTY_DEFAULT_EXPIRY_DAYS": 365,
		}
		self.config = {**defaults, **self.config}
		log.info("LoyaltyPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.crm.loyalty.views import (
			LoyaltyProgramView,
			LoyaltyAccountView,
			LoyaltyTransactionView,
		)
		cat = self.config.get("LOYALTY_MENU_CATEGORY", "Loyalty")
		self.add_view(LoyaltyProgramView, "Programs", icon="fa-star", category=cat)
		self.add_view(LoyaltyAccountView, "Accounts", icon="fa-user-circle", category=cat)
		self.add_view(LoyaltyTransactionView, "Transactions", icon="fa-exchange", category=cat)
		log.info("LoyaltyPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.loyalty.models import (
			LoyaltyProgram,
			LoyaltyAccount,
			LoyaltyTransaction,
		)
		return [LoyaltyProgram, LoyaltyAccount, LoyaltyTransaction]


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> LoyaltyPlugin:
	return LoyaltyPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.crm.loyalty.models import (  # noqa: E402
	LoyaltyProgram,
	LoyaltyAccount,
	LoyaltyTransaction,
)
from pgappforge.plugins.erp.crm.loyalty.events import (  # noqa: E402
	CustomerEnrolledEvent,
	PointsEarnedEvent,
	PointsRedeemedEvent,
	TierUpgradeEvent,
)
from pgappforge.plugins.erp.crm.loyalty.services import (  # noqa: E402
	LoyaltyService,
	LoyaltyServiceError,
	InsufficientPointsError,
	AccountNotFoundError,
	ProgramNotFoundError,
)

__all__ = [
	"LoyaltyPlugin",
	"create_plugin",
	"LoyaltyProgram",
	"LoyaltyAccount",
	"LoyaltyTransaction",
	"CustomerEnrolledEvent",
	"PointsEarnedEvent",
	"PointsRedeemedEvent",
	"TierUpgradeEvent",
	"LoyaltyService",
	"LoyaltyServiceError",
	"InsufficientPointsError",
	"AccountNotFoundError",
	"ProgramNotFoundError",
]
