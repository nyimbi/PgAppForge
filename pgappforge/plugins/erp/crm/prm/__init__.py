"""
pgappforge/plugins/erp/crm/prm/__init__.py

PRMPlugin — Partner Relationship Management.

Domain:    crm
Depends:   foundation

Events emitted
--------------
  crm.prm.partner.registered
  crm.prm.deal.registered
  crm.prm.mdf.approved
  crm.prm.deal.won
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PRMPlugin(BasePlugin):
	"""Partner Relationship Management plugin.

	Covers partner onboarding, tiered partner programs, deal registration,
	market development fund (MDF) management, and partner dashboards.
	"""

	name = "prm"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="prm",
			version="1.0.0",
			description=(
				"Partner Relationship Management — partner tiers, deal registration, "
				"MDF requests, and partner performance dashboards."
			),
			author="PgAppForge Contributors",
			tags=["crm", "prm", "channel", "partners", "deal-registration"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_prm_partner_read",
				"can_prm_partner_write",
				"can_prm_partner_delete",
				"can_prm_deal_submit",
				"can_prm_deal_approve",
				"can_prm_deal_read",
				"can_prm_mdf_submit",
				"can_prm_mdf_approve",
				"can_prm_dashboard_read",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"crm.prm.partner.registered",
			"crm.prm.deal.registered",
			"crm.prm.mdf.approved",
			"crm.prm.deal.won",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PRM_DEFAULT_TIER": "SILVER",
			"PRM_DEAL_EXPIRY_DAYS": 90,
		}
		self.config = {**defaults, **self.config}
		log.info("PRMPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.prm.models import (
			PartnerAccount,
			DealRegistration,
			MDFRequest,
		)
		return [PartnerAccount, DealRegistration, MDFRequest]


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> PRMPlugin:
	"""Factory function — preferred entry-point for plugin loader."""
	return PRMPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Convenience re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.prm.models import (  # noqa: E402
	PartnerAccount,
	DealRegistration,
	MDFRequest,
)
from pgappforge.plugins.erp.crm.prm.events import (  # noqa: E402
	PartnerRegisteredEvent,
	DealRegisteredEvent,
	MDFApprovedEvent,
	DealWonEvent,
)
from pgappforge.plugins.erp.crm.prm.services import (  # noqa: E402
	PRMService,
	PRMServiceError,
	PartnerNotFoundError,
	DealNotFoundError,
	MDFNotFoundError,
	InvalidStateError,
)

__all__ = [
	# Plugin
	"PRMPlugin",
	"create_plugin",
	# Models
	"PartnerAccount",
	"DealRegistration",
	"MDFRequest",
	# Events
	"PartnerRegisteredEvent",
	"DealRegisteredEvent",
	"MDFApprovedEvent",
	"DealWonEvent",
	# Services
	"PRMService",
	"PRMServiceError",
	"PartnerNotFoundError",
	"DealNotFoundError",
	"MDFNotFoundError",
	"InvalidStateError",
]
