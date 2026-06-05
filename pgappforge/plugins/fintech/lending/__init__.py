"""
pgappforge/plugins/fintech/lending/__init__.py

Lending plugin — Loan Origination System (LOS) + Loan Management System (LMS).

Depends on:
  - pgappforge.plugins.fintech.core_banking  (lazy — non-fatal if absent)
  - pgappforge.plugins.erp.foundation

Sub-modules:
  models   — LoanProduct, LoanApplication, Collateral, Loan,
             RepaymentSchedule, LoanRepayment
  services — LoanOriginationService, LoanManagementService
  events   — ApplicationSubmittedEvent, LoanApprovedEvent, LoanRejectedEvent,
             LoanDisbursedEvent, RepaymentReceivedEvent, LoanOverdueEvent,
             LoanNpaClassifiedEvent, LoanWrittenOffEvent, LoanSettledEvent,
             LoanRestructuredEvent
  views    — LoanApplicationView, LoanView, RepaymentScheduleView,
             LoanPortfolioDashboard, CreditScorecardView, CollectionsDashboard

Usage::

	from pgappforge.plugins.fintech.lending import (
		LoanProduct, LoanApplication, Collateral, Loan,
		RepaymentSchedule, LoanRepayment,
		LoanOriginationService, LoanManagementService,
		ApplicationSubmittedEvent, LoanApprovedEvent, LoanRejectedEvent,
		LoanDisbursedEvent, RepaymentReceivedEvent, LoanOverdueEvent,
		LoanNpaClassifiedEvent, LoanWrittenOffEvent, LoanSettledEvent,
		LoanRestructuredEvent,
		LoanApplicationView, LoanView, RepaymentScheduleView,
		LoanPortfolioDashboard, CreditScorecardView, CollectionsDashboard,
	)
"""

from pgappforge.plugins.fintech.lending.models import (
	LoanProduct,
	LoanApplication,
	Collateral,
	Loan,
	RepaymentSchedule,
	LoanRepayment,
	# CRITICAL additions
	LnGLJournalEntry,
	LoanFee,
	LoanFeeCharge,
	InterestAccrualEntry,
	# HIGH additions
	StandingOrder,
	BatchJobRun,
	CreditFacility,
	LnOutboxEvent,
	LoanNotification,
	LnAMLScreeningResult,
	LnFraudSignal,
)

from pgappforge.plugins.fintech.lending.services import (
	LoanOriginationService,
	LoanManagementService,
	LimitExceededError,
	AMLBlockedError,
)

from pgappforge.plugins.fintech.lending.events import (
	ApplicationSubmittedEvent,
	LoanApprovedEvent,
	LoanRejectedEvent,
	LoanDisbursedEvent,
	RepaymentReceivedEvent,
	LoanOverdueEvent,
	LoanNpaClassifiedEvent,
	LoanWrittenOffEvent,
	LoanSettledEvent,
	LoanRestructuredEvent,
)

from pgappforge.plugins.fintech.lending.views import (
	LoanApplicationView,
	LoanView,
	RepaymentScheduleView,
	LoanPortfolioDashboard,
	CreditScorecardView,
	CollectionsDashboard,
)

__all__ = [
	# models — original
	"LoanProduct",
	"LoanApplication",
	"Collateral",
	"Loan",
	"RepaymentSchedule",
	"LoanRepayment",
	# models — CRITICAL additions
	"LnGLJournalEntry",
	"LoanFee",
	"LoanFeeCharge",
	"InterestAccrualEntry",
	# models — HIGH additions
	"StandingOrder",
	"BatchJobRun",
	"CreditFacility",
	"LnOutboxEvent",
	"LoanNotification",
	"LnAMLScreeningResult",
	"LnFraudSignal",
	# services
	"LoanOriginationService",
	"LoanManagementService",
	"LimitExceededError",
	# events
	"ApplicationSubmittedEvent",
	"LoanApprovedEvent",
	"LoanRejectedEvent",
	"LoanDisbursedEvent",
	"RepaymentReceivedEvent",
	"LoanOverdueEvent",
	"LoanNpaClassifiedEvent",
	"LoanWrittenOffEvent",
	"LoanSettledEvent",
	"LoanRestructuredEvent",
	# views
	"LoanApplicationView",
	"LoanView",
	"RepaymentScheduleView",
	"LoanPortfolioDashboard",
	"CreditScorecardView",
	"CollectionsDashboard",
]
