"""
pgappforge/plugins/erp/finance/grants/__init__.py

GrantsPlugin — Grant/Fund Accounting ERP plugin.

Full fund accounting lifecycle:
  Fund → Grant → GrantExpenditure → FundBalance → Utilization Reports

Supports FASB/GASB-aligned fund types (UNRESTRICTED, TEMP_RESTRICTED,
PERM_RESTRICTED), indirect cost rate calculation, GL dimension posting,
and close-out reporting.  Suitable for nonprofits, NGOs, governments,
and any entity managing restricted grant funds (Intacct-equivalent).

Domain: finance
Depends on: foundation

Events emitted:
  finance.grants.fund.created
  finance.grants.grant.awarded
  finance.grants.expenditure.recorded
  finance.grants.balance.updated
  finance.grants.closed_out
  finance.grants.report.generated

Events consumed:
  finance.gl.journal.posted  (informational — no action required)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",
        "pgappforge.plugins.erp.finance.grants",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.finance.grants import GrantsPlugin
    plugin = GrantsPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class GrantsPlugin(BasePlugin):
	"""Grant/Fund Accounting ERP plugin.

	Registers fund, grant, expenditure, and balance views.
	Exposes 2 BPM actions for workflow integration.
	Subscribes to finance.gl.journal.posted for cross-plugin audit.
	"""

	name = "grants"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="grants",
			version="1.0.0",
			description=(
				"Grant/Fund Accounting — full restricted fund lifecycle: "
				"fund master, grant award, expenditure recording with indirect "
				"cost calculation, GL dimension posting, fund balance tracking, "
				"utilization reporting, and close-out. "
				"FASB/GASB-aligned. Intacct Grant Management equivalent."
			),
			author="PgAppForge Contributors",
			tags=[
				"finance",
				"grants",
				"fund-accounting",
				"nonprofit",
				"restricted-funds",
				"intacct",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_grants_fund_list",
				"can_grants_fund_write",
				"can_grants_grant_list",
				"can_grants_grant_write",
				"can_grants_grant_approve",
				"can_grants_expenditure_list",
				"can_grants_expenditure_write",
				"can_grants_expenditure_approve",
				"can_grants_balance_list",
				"can_grants_reports",
				"can_grants_closeout",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"finance.grants.fund.created",
			"finance.grants.grant.awarded",
			"finance.grants.expenditure.recorded",
			"finance.grants.balance.updated",
			"finance.grants.closed_out",
			"finance.grants.report.generated",
		]

	def subscribe_to(self) -> list[str]:
		return ["finance.gl.journal.posted"]

	def _on_finance_gl_journal_posted(self, event: Any) -> None:
		"""Informational handler — logs GL journal postings for grant audit trail.

		In a full implementation this would reconcile grant expenditures against
		GL journal entries and flag discrepancies.
		"""
		log.debug(
			"GrantsPlugin: GL journal posted — event_id=%s",
			getattr(event, "event_id", "?"),
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"GRANTS_MENU_CATEGORY": "Grant Accounting",
			"GRANTS_DEFAULT_CURRENCY": "KES",
			"GRANTS_INDIRECT_COST_ACCOUNT": "5200",
			"GRANTS_EXPENSE_ACCOUNT": "5100",
			"GRANTS_BANK_ACCOUNT": "1000",
		}
		self.config = {**defaults, **self.config}
		# Ensure BPM registrations are imported
		try:
			import pgappforge.plugins.erp.finance.grants.services  # noqa: F401
		except Exception as exc:
			log.debug("GrantsPlugin.initialize: services import warning: %s", exc)
		log.info("GrantsPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.grants.models import (
			Fund,
			FundBalance,
			Grant,
			GrantExpenditure,
		)
		return [Fund, Grant, FundBalance, GrantExpenditure]

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.finance.grants.views import (
				FundView,
				GrantView,
				GrantExpenditureView,
			)
		except ImportError:
			log.warning("GrantsPlugin.register_views: views module not available — skipping.")
			return
		cat = self.config.get("GRANTS_MENU_CATEGORY", "Grant Accounting")
		self.add_view(FundView, "Funds", icon="fa-archive", category=cat)
		self.add_view(GrantView, "Grants", icon="fa-certificate", category=cat)
		self.add_view(GrantExpenditureView, "Expenditures", icon="fa-credit-card", category=cat)
		log.info("GrantsPlugin: views registered under %r", cat)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> GrantsPlugin:
	"""Construct a GrantsPlugin without activating it."""
	return GrantsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.grants.models import (  # noqa: E402
	Fund,
	FundBalance,
	Grant,
	GrantExpenditure,
)
from pgappforge.plugins.erp.finance.grants.events import (  # noqa: E402
	FundBalanceUpdatedEvent,
	FundCreatedEvent,
	GrantAwardedEvent,
	GrantCloseOutEvent,
	GrantExpenditureRecordedEvent,
	GrantReportGeneratedEvent,
)
from pgappforge.plugins.erp.finance.grants.services import GrantService  # noqa: E402

__all__ = [
	# plugin
	"GrantsPlugin",
	"create_plugin",
	# models
	"Fund",
	"Grant",
	"FundBalance",
	"GrantExpenditure",
	# events
	"FundCreatedEvent",
	"GrantAwardedEvent",
	"GrantExpenditureRecordedEvent",
	"FundBalanceUpdatedEvent",
	"GrantCloseOutEvent",
	"GrantReportGeneratedEvent",
	# services
	"GrantService",
]
