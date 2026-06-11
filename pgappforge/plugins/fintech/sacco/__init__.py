"""
pgappforge/plugins/fintech/sacco

SACCO / MFI / Chama plugin for pgappforge fintech suite.

Provides:
  - SACCO institution management (registration, regulatory tracking)
  - Member lifecycle (registration, contributions, exit)
  - SACCO-specific loan products with savings-multiplier eligibility
  - Dividend declaration and distribution (immutable ledger)
  - Chama savings groups (merry-go-round, table banking, investment clubs)
  - KPI dashboard (savings, loan book, NPL, capital adequacy, liquidity)

Event subscriptions
-------------------
hcm.payroll.run.finalized
    Triggers automatic SACCO contribution processing for members with
    payroll_deduction_enabled = True.  The handler is intentionally
    non-fatal — a payroll deduction failure for one member must never
    fail the overall payroll run.

Depends on:
  pgappforge.plugins.fintech.core_banking  (account management, GL posting)
  pgappforge.plugins.fintech.lending        (loan origination + management)
  pgappforge.plugins.erp.foundation         (Party, commons, events)

Usage::

	from pgappforge.plugins.fintech.sacco import (
		# Models
		SACCO, Member, SACCOLoanProduct, Dividend, Chama, ChamaMember,
		# Services
		SACCOService, ChamaService,
		# Events
		MemberRegisteredEvent, DividendDeclaredEvent, MerryGoRoundDisbursedEvent,
		# Views
		SACCOView, MemberView, SACCODashboardView,
	)
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# -- Models ------------------------------------------------------------------
from pgappforge.plugins.fintech.sacco.models import (
	SACCO,
	Member,
	SACCOLoanProduct,
	Dividend,
	Chama,
	ChamaMember,
)

# -- Services ----------------------------------------------------------------
from pgappforge.plugins.fintech.sacco.services import (
	SACCOService,
	ChamaService,
)

# -- Events ------------------------------------------------------------------
from pgappforge.plugins.fintech.sacco.events import (
	MemberRegisteredEvent,
	MemberContributionPostedEvent,
	MemberExitCalculatedEvent,
	SACCOLoanApplicationCreatedEvent,
	SACCOLoanApprovedEvent,
	DividendDeclaredEvent,
	DividendPaidEvent,
	ChamaCreatedEvent,
	ChamaContributionPostedEvent,
	MerryGoRoundDisbursedEvent,
	TableBankingLoanCreatedEvent,
)


# ---------------------------------------------------------------------------
# HCM payroll deduction handler
# ---------------------------------------------------------------------------

def subscribe_to() -> list[str]:
	"""Return the list of event topics this plugin handles.

	Called by the event bus at app-init time to register subscriptions.
	"""
	return [
		"hcm.payroll.run.finalized",
	]


def _on_hcm_payroll_run_finalized(event: object) -> None:
	"""Auto-process SACCO contributions for members with payroll_deduction enabled.

	Triggered when HCM payroll finalises a pay run.  Iterates all ACTIVE
	SACCO members who have payroll_deduction_enabled = True and calls
	SACCOService.process_monthly_contribution() for each.

	Failures per-member are caught and logged so one bad member record
	cannot abort the rest of the batch.

	Expected event attributes:
	  tenant_id (str) — multi-tenant scope
	  period   (str) — pay-period identifier e.g. "2026-06"
	"""
	try:
		from flask import current_app
		import sqlalchemy as sa2

		session = current_app.appbuilder.get_session()
		tenant_id = str(getattr(event, "tenant_id", ""))
		period = str(getattr(event, "period", ""))

		if not (tenant_id and period):
			log.warning(
				"_on_hcm_payroll_run_finalized: missing tenant_id or period in event — skipped"
			)
			return

		# Convert "YYYY-MM" period to a date object for contribution_date
		from datetime import date as _date
		try:
			_year, _month = period.split("-")
			contrib_date = _date(int(_year), int(_month), 1)
		except Exception:
			contrib_date = _date.today()

		# Find members with payroll deduction enabled for this tenant
		payroll_members = session.execute(
			sa2.select(Member).where(
				Member.tenant_id == tenant_id,
				Member.membership_status == "ACTIVE",
				Member.payroll_deduction_enabled.is_(True),
			)
		).scalars().all()

		if not payroll_members:
			log.debug(
				"_on_hcm_payroll_run_finalized: no payroll-deduction members for tenant=%s period=%s",
				tenant_id, period,
			)
			return

		svc = SACCOService()
		processed = 0
		failed = 0

		for member in payroll_members:
			if not member.monthly_contribution_cents or member.monthly_contribution_cents <= 0:
				continue
			try:
				svc.process_monthly_contribution(
					session=session,
					member_id=str(member.id),
					amount_cents=member.monthly_contribution_cents,
					contribution_date=contrib_date,
				)
				processed += 1
			except Exception as exc:
				failed += 1
				log.warning(
					"Payroll deduction failed for member %s (tenant=%s period=%s): %s",
					member.id, tenant_id, period, exc,
				)

		try:
			session.commit()
		except Exception as exc:
			log.error(
				"_on_hcm_payroll_run_finalized: commit failed for tenant=%s period=%s: %s",
				tenant_id, period, exc,
			)
			session.rollback()
			return

		log.info(
			"SACCO payroll deduction: %d contributions processed, %d failed for period %s tenant=%s",
			processed, failed, period, tenant_id,
		)

	except Exception as exc:
		log.warning("_on_hcm_payroll_run_finalized failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Event dispatch table — consumed by the event bus router
# ---------------------------------------------------------------------------

EVENT_HANDLERS: dict[str, object] = {
	"hcm.payroll.run.finalized": _on_hcm_payroll_run_finalized,
}


# -- Views (lazy — only importable when flask_appbuilder is installed) --------
# Import views on demand to avoid hard dependency on flask_appbuilder at
# module load time.  Use:
#   from pgappforge.plugins.fintech.sacco.views import SACCOView
# or call pgappforge.plugins.fintech.sacco.get_views() at app init time.

def get_views() -> dict:
	"""Return all FAB view classes. Requires flask_appbuilder to be installed."""
	from pgappforge.plugins.fintech.sacco.views import (  # noqa: PLC0415
		SACCOView,
		MemberView,
		SACCOLoanProductView,
		DividendView,
		ChamaView,
		ChamaMemberView,
		SACCODashboardView,
	)
	return {
		"SACCOView": SACCOView,
		"MemberView": MemberView,
		"SACCOLoanProductView": SACCOLoanProductView,
		"DividendView": DividendView,
		"ChamaView": ChamaView,
		"ChamaMemberView": ChamaMemberView,
		"SACCODashboardView": SACCODashboardView,
	}


try:
	from pgappforge.plugins.fintech.sacco.views import (
		SACCOView,
		MemberView,
		SACCOLoanProductView,
		DividendView,
		ChamaView,
		ChamaMemberView,
		SACCODashboardView,
	)
	_VIEWS_AVAILABLE = True
except ModuleNotFoundError:
	_VIEWS_AVAILABLE = False


__all__ = [
	# Models
	"SACCO",
	"Member",
	"SACCOLoanProduct",
	"Dividend",
	"Chama",
	"ChamaMember",
	# Services
	"SACCOService",
	"ChamaService",
	# Events
	"MemberRegisteredEvent",
	"MemberContributionPostedEvent",
	"MemberExitCalculatedEvent",
	"SACCOLoanApplicationCreatedEvent",
	"SACCOLoanApprovedEvent",
	"DividendDeclaredEvent",
	"DividendPaidEvent",
	"ChamaCreatedEvent",
	"ChamaContributionPostedEvent",
	"MerryGoRoundDisbursedEvent",
	"TableBankingLoanCreatedEvent",
	# Event wiring
	"subscribe_to",
	"EVENT_HANDLERS",
	# Views
	"SACCOView",
	"MemberView",
	"SACCOLoanProductView",
	"DividendView",
	"ChamaView",
	"ChamaMemberView",
	"SACCODashboardView",
]
