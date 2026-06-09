"""
pgappforge/plugins/erp/industry/real_estate/commercial/__init__.py

CommercialREPlugin — commercial leasing, CAM reconciliation, LOI management.

Depends on: foundation, real_estate

Events emitted
--------------
  re_com.lease.signed      — commercial lease activated
  re_com.cam.reconciled    — CAM reconciliation finalised
  re_com.loi.accepted      — letter of intent accepted
  re_com.space.vacated     — space unit vacated

Events consumed
---------------
  (none — standalone sub-plugin; extend subscribe_to() if cross-plugin triggers needed)

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.real_estate",
        "pgappforge.plugins.erp.industry.real_estate.commercial",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CommercialREPlugin(BasePlugin):
	"""Commercial Real Estate sub-plugin.

	Provides space unit management, commercial lease lifecycle (NNN / Modified
	Gross / Full Service / Gross), CAM budgeting and reconciliation, lease
	abstracts, and letter-of-intent (LOI) workflow.

	Class-level attributes:
	    name       = "commercial_re"
	    domain     = "industry"
	    depends_on = ["foundation", "real_estate"]
	"""

	name = "commercial_re"
	domain = "industry"
	depends_on: list[str] = ["foundation", "real_estate"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="commercial_re",
			version="1.0.0",
			description=(
				"Commercial Real Estate sub-plugin — space units, NNN/MG/FS/Gross leases, "
				"CAM budgeting and reconciliation, lease abstracts, and LOI workflow."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "real-estate", "commercial", "cam", "nnn", "loi"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_re_com_space_list",
				"can_re_com_space_write",
				"can_re_com_lease_list",
				"can_re_com_lease_write",
				"can_re_com_lease_terminate",
				"can_re_com_cam_budget",
				"can_re_com_cam_actual",
				"can_re_com_cam_reconcile",
				"can_re_com_loi_list",
				"can_re_com_loi_submit",
				"can_re_com_loi_accept",
				"can_re_com_abstract_read",
				"can_re_com_abstract_write",
				"can_re_com_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"re_com.lease.signed",
			"re_com.cam.reconciled",
			"re_com.loi.accepted",
			"re_com.space.vacated",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"RE_COM_MENU_CATEGORY": "Commercial RE",
			"RE_COM_DEFAULT_CURRENCY": "USD",
			"RE_COM_DEFAULT_LEASE_TYPE": "NNN",
		}
		self.config = {**defaults, **self.config}
		log.info("CommercialREPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		pass

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.real_estate.commercial.views import (
			SpaceUnitView,
			CommercialLeaseView,
			CAMReconciliationView,
			LOIView,
			LeaseAbstractView,
			CommercialREDashboardView,
		)

		cat = self.config.get("RE_COM_MENU_CATEGORY", "Commercial RE")

		self.add_view(CommercialREDashboardView, "Dashboard", icon="fa-building", category=cat)
		self.add_view(SpaceUnitView, "Space Units", icon="fa-th-large", category=cat)
		self.add_view(CommercialLeaseView, "Leases", icon="fa-file-text-o", category=cat)
		self.add_view(LOIView, "Letters of Intent", icon="fa-handshake-o", category=cat)
		self.add_view(CAMReconciliationView, "CAM Reconciliation", icon="fa-calculator", category=cat)
		self.add_view(LeaseAbstractView, "Lease Abstracts", icon="fa-list-alt", category=cat)

		log.info("CommercialREPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.real_estate.commercial.models import (
			SpaceUnit,
			CommercialLease,
			CAMBudget,
			CAMActual,
			CAMReconciliation,
			LeaseAbstract,
			LOI,
		)
		return [
			SpaceUnit,
			CommercialLease,
			CAMBudget,
			CAMActual,
			CAMReconciliation,
			LeaseAbstract,
			LOI,
		]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> CommercialREPlugin:
	"""Construct and return a CommercialREPlugin bound to *appbuilder*."""
	return CommercialREPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.real_estate.commercial.models import (  # noqa: E402
	SpaceUnit,
	CommercialLease,
	CAMBudget,
	CAMActual,
	CAMReconciliation,
	LeaseAbstract,
	LOI,
)
from pgappforge.plugins.erp.industry.real_estate.commercial.events import (  # noqa: E402
	CommercialLeaseSignedEvent,
	CAMReconciliationFinalizedEvent,
	LOIAcceptedEvent,
	SpaceVacatedEvent,
)
from pgappforge.plugins.erp.industry.real_estate.commercial.services import (  # noqa: E402
	CommercialLeaseService,
	CommercialREServiceError,
	SpaceNotFoundError,
	LeaseNotFoundError,
	LOINotFoundError,
	CommercialREValidationError,
)

__all__ = [
	# plugin
	"CommercialREPlugin",
	"create_plugin",
	# models
	"SpaceUnit",
	"CommercialLease",
	"CAMBudget",
	"CAMActual",
	"CAMReconciliation",
	"LeaseAbstract",
	"LOI",
	# events
	"CommercialLeaseSignedEvent",
	"CAMReconciliationFinalizedEvent",
	"LOIAcceptedEvent",
	"SpaceVacatedEvent",
	# services
	"CommercialLeaseService",
	"CommercialREServiceError",
	"SpaceNotFoundError",
	"LeaseNotFoundError",
	"LOINotFoundError",
	"CommercialREValidationError",
]
