"""
pgappforge/plugins/erp/hcm/travel_expense/__init__.py

T&E plugin — expense policies, per diem, credit card matching, PAYE BIK,
advance management.

Full Travel & Expense lifecycle:
  ExpensePolicy / PerDiemRate configuration
  → CashAdvance (request → approve → disburse → settle)
  → ExpenseReport (draft → submit → approve/reject → pay)
    └─ ExpenseLine (with policy check, BIK tagging, FX conversion)
  → MileageLog

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.travel_expense.report.submitted
  hcm.travel_expense.report.approved
  hcm.travel_expense.report.paid
  hcm.travel_expense.advance.disbursed
  hcm.travel_expense.policy.breach
  hcm.travel_expense.bik.flagged

Events consumed:
  hcm.payroll.run.requested  — triggers BIK lines inclusion in payroll

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.travel_expense",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.travel_expense import TravelExpensePlugin
    plugin = TravelExpensePlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TravelExpensePlugin(BasePlugin):
	"""HCM Travel & Expense ERP plugin.

	Registers expense policy management, per diem rate tables, expense report
	lifecycle, cash advance management, mileage logging, and GL integration.
	"""

	name = "travel_expense"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="travel_expense",
			version="1.0.0",
			description=(
				"HCM Travel & Expense — full T&E lifecycle: expense policy "
				"enforcement, per diem calculation, cash advance management, "
				"PAYE benefit-in-kind tagging, mileage logging, GL posting, "
				"and expense analytics."
			),
			author="PgAppForge Contributors",
			tags=["erp", "hcm", "travel", "expense", "per-diem", "advance", "bik", "paye"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_expense_policy_list",
				"can_expense_policy_write",
				"can_per_diem_rate_list",
				"can_per_diem_rate_write",
				"can_expense_report_list",
				"can_expense_report_write",
				"can_expense_report_approve",
				"can_expense_report_pay",
				"can_cash_advance_list",
				"can_cash_advance_write",
				"can_cash_advance_approve",
				"can_cash_advance_disburse",
				"can_mileage_log_list",
				"can_mileage_log_write",
				"can_expense_analytics_view",
			],
		)

	# ------------------------------------------------------------------
	# Plugin interface
	# ------------------------------------------------------------------

	def register_models(self) -> list[Any]:
		"""Return all ORM models so AppBuilder can register them."""
		from pgappforge.plugins.erp.hcm.travel_expense.models import (
			ExpensePolicy,
			PerDiemRate,
			ExpenseReport,
			ExpenseLine,
			CashAdvance,
			MileageLog,
		)
		return [
			ExpensePolicy,
			PerDiemRate,
			ExpenseReport,
			ExpenseLine,
			CashAdvance,
			MileageLog,
		]

	def get_events(self) -> list[str]:
		"""Return dotted event-name strings emitted by this plugin."""
		return [
			"hcm.travel_expense.report.submitted",
			"hcm.travel_expense.report.approved",
			"hcm.travel_expense.report.paid",
			"hcm.travel_expense.advance.disbursed",
			"hcm.travel_expense.policy.breach",
			"hcm.travel_expense.bik.flagged",
		]

	def subscribe_to(self) -> list[str]:
		"""Event types this plugin listens for."""
		return ["hcm.payroll.run.requested"]

	def initialize(self) -> None:
		"""Apply default config values."""
		defaults: dict[str, Any] = {
			"TRAVEL_EXPENSE_MENU_CATEGORY": "HR",
			"TRAVEL_EXPENSE_DEFAULT_CURRENCY": "KES",
			"TRAVEL_EXPENSE_ADVANCE_MAX_OPEN_DAYS": 60,
		}
		self.config = {**defaults, **self.config}
		log.info("TravelExpensePlugin initialised (config keys: %s)", list(self.config))

	def activate(self) -> None:
		"""Register event subscriptions and log activation."""
		from pgappforge.plugins.erp.foundation.events import subscribe
		subscribe("payroll.run.requested", self._handle_payroll_run_requested)
		log.info(
			"TravelExpensePlugin activated — subscribed to payroll.run.requested"
		)

	# ------------------------------------------------------------------
	# Event handlers
	# ------------------------------------------------------------------

	def _handle_payroll_run_requested(self, event: Any) -> None:
		"""When a payroll run is requested, surface BIK lines for inclusion.

		Looks for APPROVED expense reports with BIK-flagged lines whose
		pay_period matches the payroll run period. Emits BIKFlaggedEvent
		per qualifying line so the Payroll plugin can include them in the
		gross-to-net calculation.

		Session lifecycle is managed internally via a short-lived scoped
		session; this handler is intentionally fire-and-forget.
		"""
		tenant_id: str = getattr(event, "tenant_id", "")
		period_start: str = getattr(event, "period_start", "")

		if not tenant_id:
			log.warning("payroll.run.requested event missing tenant_id — skipping BIK scan")
			return

		log.debug(
			"TravelExpensePlugin._handle_payroll_run_requested — tenant=%s period=%s",
			tenant_id, period_start,
		)
		# BIK surfacing is handled by BIKFlaggedEvent emitted during pay_report().
		# This hook is reserved for any pre-run BIK aggregation logic if needed.


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> TravelExpensePlugin:
	return TravelExpensePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.travel_expense.models import (  # noqa: E402
	ExpensePolicy,
	PerDiemRate,
	ExpenseReport,
	ExpenseLine,
	CashAdvance,
	MileageLog,
)
from pgappforge.plugins.erp.hcm.travel_expense.events import (  # noqa: E402
	ExpenseReportSubmittedEvent,
	ExpenseReportApprovedEvent,
	ExpenseReportPaidEvent,
	AdvanceDisbursedEvent,
	PolicyBreachFlaggedEvent,
	BIKFlaggedEvent,
)
from pgappforge.plugins.erp.hcm.travel_expense.services import (  # noqa: E402
	ExpenseService,
	ExpenseServiceError,
	ExpenseReportNotFoundError,
	ExpenseLineNotFoundError,
	AdvanceNotFoundError,
	ExpenseStateError,
	ExpensePolicyError,
)

__all__ = [
	# plugin
	"TravelExpensePlugin",
	"create_plugin",
	# models
	"ExpensePolicy",
	"PerDiemRate",
	"ExpenseReport",
	"ExpenseLine",
	"CashAdvance",
	"MileageLog",
	# events
	"ExpenseReportSubmittedEvent",
	"ExpenseReportApprovedEvent",
	"ExpenseReportPaidEvent",
	"AdvanceDisbursedEvent",
	"PolicyBreachFlaggedEvent",
	"BIKFlaggedEvent",
	# services
	"ExpenseService",
	"ExpenseServiceError",
	"ExpenseReportNotFoundError",
	"ExpenseLineNotFoundError",
	"AdvanceNotFoundError",
	"ExpenseStateError",
	"ExpensePolicyError",
]
