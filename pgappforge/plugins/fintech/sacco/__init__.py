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

# -- Views (lazy — only importable when flask_appbuilder is installed) --------
# Import views on demand to avoid hard dependency on flask_appbuilder at
# module load time.  Use:
#   from pgappforge.plugins.fintech.sacco.views import SACCOView
# or call pgappforge.plugins.fintech.sacco.get_views() at app init time.

def get_views():
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
	# Views
	"SACCOView",
	"MemberView",
	"SACCOLoanProductView",
	"DividendView",
	"ChamaView",
	"ChamaMemberView",
	"SACCODashboardView",
]
