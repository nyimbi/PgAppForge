"""
pgappforge/plugins/fintech/insurtech/__init__.py

InsurTechPlugin — insurance product quoting, policy issuance, premium
collection, lapse management, and claims adjudication.

Depends on: foundation, core_banking

Registers
---------
  - InsuranceProductView     (InsurTech menu)
  - InsurancePolicyView      (InsurTech menu — list/show/add)
  - InsuranceClaimView       (InsurTech menu — list/show/add)
  - InsurTechDashboardView   (/fintech/insurtech-dashboard/)

Events emitted
--------------
  insurtech.policy_issued, insurtech.premium_paid, insurtech.claim_submitted,
  insurtech.claim_approved, insurtech.claim_rejected, insurtech.policy_lapsed

BPM processes
-------------
  insurtech.issue_policy, insurtech.submit_claim, insurtech.approve_claim

Config keys
-----------
  IT_MENU_CATEGORY  — menu category label (default: "InsurTech")
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class InsurTechPlugin(BasePlugin):
	"""Insurance product quoting, policy management, and claims plugin.

	Class-level attributes used by the plugin registry:
	    name       = "insurtech"
	    domain     = "fintech"
	    depends_on = ["foundation", "core_banking"]
	"""

	name = "insurtech"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="insurtech",
			version="1.0.0",
			description=(
				"InsurTech — insurance product catalogue with configurable premium "
				"formulas, policy issuance, monthly premium scheduling, lapse/reinstate "
				"lifecycle, and full claims adjudication (submit → review → approve/reject). "
				"Covers LIFE, HEALTH, PROPERTY, MOTOR, TRAVEL, CROP, and MICROINSURANCE "
				"product lines. Depends on core_banking for customer/GL linkage."
			),
			author="PgAppForge Contributors",
			tags=[
				"fintech", "insurtech", "insurance", "claims",
				"premium", "policy", "microinsurance",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_it_product_list",
				"can_it_product_write",
				"can_it_policy_list",
				"can_it_policy_show",
				"can_it_policy_add",
				"can_it_claim_list",
				"can_it_claim_show",
				"can_it_claim_add",
				"can_it_dashboard",
			],
			safe_mode_compatible=True,
		)

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"IT_MENU_CATEGORY": "InsurTech",
			"IT_GRACE_DAYS": 30,
		}
		self.config = {**defaults, **self.config}
		log.info("InsurTechPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.fintech.insurtech.models import (
			InsuranceClaim,
			InsurancePolicy,
			InsurancePremium,
			InsuranceProduct,
			PolicyHolder,
		)
		return [InsuranceProduct, PolicyHolder, InsurancePolicy, InsurancePremium, InsuranceClaim]

	def register_views(self) -> None:
		from pgappforge.plugins.fintech.insurtech.views import (
			InsuranceClaimView,
			InsurancePolicyView,
			InsuranceProductView,
			InsurTechDashboardView,
		)

		cat = self.config.get("IT_MENU_CATEGORY", "InsurTech")

		self.add_view(
			InsuranceProductView,
			"Products",
			icon="fa-list-alt",
			category=cat,
		)
		self.add_view(
			InsurancePolicyView,
			"Policies",
			icon="fa-shield",
			category=cat,
		)
		self.add_view(
			InsuranceClaimView,
			"Claims",
			icon="fa-file-text",
			category=cat,
		)
		self.add_view(
			InsurTechDashboardView,
			"Dashboard",
			icon="fa-tachometer-alt",
			category=cat,
		)

		log.info("InsurTechPlugin: views registered under category %r", cat)

	def get_events(self) -> list[str]:
		from pgappforge.plugins.fintech.insurtech.events import ALL_IT_EVENT_TYPES
		return ALL_IT_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		return []


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> InsurTechPlugin:
	"""Construct and return an InsurTechPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return InsurTechPlugin(appbuilder, config=config or {})


from pgappforge.plugins.fintech.insurtech.models import (  # noqa: E402
	InsuranceClaim,
	InsurancePolicy,
	InsurancePremium,
	InsuranceProduct,
	PolicyHolder,
)
from pgappforge.plugins.fintech.insurtech.events import (  # noqa: E402
	ALL_IT_EVENT_TYPES,
	ClaimApprovedEvent,
	ClaimRejectedEvent,
	ClaimSubmittedEvent,
	IT_CLAIM_APPROVED,
	IT_CLAIM_REJECTED,
	IT_CLAIM_SUBMITTED,
	IT_POLICY_ISSUED,
	IT_POLICY_LAPSED,
	IT_PREMIUM_PAID,
	PolicyIssuedEvent,
	PolicyLapsedEvent,
	PremiumPaidEvent,
)
from pgappforge.plugins.fintech.insurtech.services import (  # noqa: E402
	ClaimNotFoundError,
	InsurTechError,
	InsurTechService,
	InsurTechStateError,
	InsurTechValidationError,
	PolicyNotFoundError,
	ProductNotFoundError,
)
from pgappforge.plugins.fintech.insurtech.views import (  # noqa: E402
	InsuranceClaimView,
	InsurancePolicyView,
	InsuranceProductView,
	InsurTechDashboardView,
)

__all__ = [
	# plugin
	"InsurTechPlugin",
	"create_plugin",
	# models
	"InsuranceProduct",
	"PolicyHolder",
	"InsurancePolicy",
	"InsurancePremium",
	"InsuranceClaim",
	# events — classes
	"PolicyIssuedEvent",
	"PremiumPaidEvent",
	"ClaimSubmittedEvent",
	"ClaimApprovedEvent",
	"ClaimRejectedEvent",
	"PolicyLapsedEvent",
	# events — type constants
	"IT_POLICY_ISSUED",
	"IT_PREMIUM_PAID",
	"IT_CLAIM_SUBMITTED",
	"IT_CLAIM_APPROVED",
	"IT_CLAIM_REJECTED",
	"IT_POLICY_LAPSED",
	"ALL_IT_EVENT_TYPES",
	# services
	"InsurTechService",
	"InsurTechError",
	"ProductNotFoundError",
	"PolicyNotFoundError",
	"ClaimNotFoundError",
	"InsurTechStateError",
	"InsurTechValidationError",
	# views
	"InsuranceProductView",
	"InsurancePolicyView",
	"InsuranceClaimView",
	"InsurTechDashboardView",
]
