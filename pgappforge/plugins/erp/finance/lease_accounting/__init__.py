"""
pgappforge/plugins/erp/finance/lease_accounting/__init__.py

IFRS 16 / ASC 842 Lease Accounting plugin for PgAppForge ERP.

Entities:  Lease, LeasePaymentSchedule, RouAsset, LeaseModification
Service:   LeaseService
Events:    lease_accounting.lease_created, .lease_commenced, .lease_modified,
           .lease_terminated, .payment_posted, .rou_depreciated

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.lease_accounting",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class LeaseAccountingPlugin(BasePlugin):
	"""IFRS 16 / ASC 842 Lease Accounting plugin.

	Provides: lease contract registration, amortisation schedule generation
	(effective-interest method), right-of-use asset tracking, period payment
	posting, ROU depreciation, lease modification / remeasurement, and
	early termination with gain/loss recognition.
	"""

	name = "lease_accounting"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="lease_accounting",
			version="1.0.0",
			description=(
				"IFRS 16 / ASC 842 Lease Accounting — lease contract management, "
				"PV-based amortisation schedules (effective-interest method), "
				"right-of-use asset creation and straight-line depreciation, "
				"periodic payment posting, lease modification remeasurement, "
				"and early termination with gain/loss recognition."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "lease", "ifrs16", "asc842", "rou"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_lease_read",
				"can_lease_write",
				"can_lease_commence",
				"can_lease_modify",
				"can_lease_terminate",
				"can_lease_payment_post",
				"can_lease_depreciation_post",
				"can_lease_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"lease_accounting.lease_created",
			"lease_accounting.lease_commenced",
			"lease_accounting.lease_modified",
			"lease_accounting.lease_terminated",
			"lease_accounting.payment_posted",
			"lease_accounting.rou_depreciated",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"accounting_period.closing",  # trigger period-end depreciation runs
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"LEASE_MENU_CATEGORY": "Lease Accounting",
			"LEASE_DEFAULT_CURRENCY": "KES",
			"LEASE_DEFAULT_STANDARD": "IFRS16",
		}
		self.config = {**defaults, **self.config}
		log.info("LeaseAccountingPlugin initialised")

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.finance.lease_accounting.views import (
				LeaseView,
				LeasePaymentScheduleView,
			)
		except ImportError:
			log.warning("LeaseAccountingPlugin.register_views: views module not available — skipping.")
			return
		cat = self.config.get("LEASE_MENU_CATEGORY", "Lease Accounting")
		self.add_view(LeaseView, "Leases", icon="fa-building-o", category=cat)
		self.add_view(LeasePaymentScheduleView, "Payment Schedule", icon="fa-calendar", category=cat)
		log.info("LeaseAccountingPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.lease_accounting.models import (
			Lease, LeasePaymentSchedule, RouAsset, LeaseModification,
		)
		return [Lease, LeasePaymentSchedule, RouAsset, LeaseModification]


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> LeaseAccountingPlugin:
	return LeaseAccountingPlugin(appbuilder, config=config or {})


# Public re-exports
from pgappforge.plugins.erp.finance.lease_accounting.models import (  # noqa: E402
	Lease,
	LeasePaymentSchedule,
	RouAsset,
	LeaseModification,
)
from pgappforge.plugins.erp.finance.lease_accounting.services import (  # noqa: E402
	LeaseService,
	LeaseServiceError,
	LeaseNotFoundError,
	LeaseStatusError,
	LeaseScheduleError,
	LeaseDetails,
	LeaseModificationDetails,
)
from pgappforge.plugins.erp.finance.lease_accounting.events import (  # noqa: E402
	LeaseCreatedEvent,
	LeaseCommencedEvent,
	LeaseModifiedEvent,
	LeaseTerminatedEvent,
	LeasePaymentPostedEvent,
	RouDepreciatedEvent,
)

__all__ = [
	"LeaseAccountingPlugin",
	"create_plugin",
	# models
	"Lease",
	"LeasePaymentSchedule",
	"RouAsset",
	"LeaseModification",
	# services
	"LeaseService",
	"LeaseServiceError",
	"LeaseNotFoundError",
	"LeaseStatusError",
	"LeaseScheduleError",
	"LeaseDetails",
	"LeaseModificationDetails",
	# events
	"LeaseCreatedEvent",
	"LeaseCommencedEvent",
	"LeaseModifiedEvent",
	"LeaseTerminatedEvent",
	"LeasePaymentPostedEvent",
	"RouDepreciatedEvent",
]
