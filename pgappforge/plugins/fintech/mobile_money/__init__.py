"""
pgappforge/plugins/fintech/mobile_money/__init__.py

Mobile Money + Agency Banking plugin for pgappforge fintech suite.

Covers M-Pesa-style mobile wallets, P2P transfers, USSD/STK-push flows,
C2B/B2C/B2B payments, and agent network float management — critical for
the East African market (Kenya CBK Mobile Money Regulations 2021).

Depends on: core_banking (cb_account FK), payments (optional Daraja adapter),
            erp.foundation (Party FK, commons, events)

Registration (app factory)::

    from pgappforge.plugins.fintech.mobile_money import MobileMoneyPlugin
    plugin = MobileMoneyPlugin()
    appbuilder.add_view(plugin.wallet_view, "Wallets", category="Mobile Money")
    # — or — call plugin.register_views(appbuilder) to register all views at once.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# ── Models ──────────────────────────────────────────────────────────────────
from .models import (
	Agent,
	AgentCommission,
	DisbursementBatch,
	DisbursementLine,
	FeeSchedule,
	FraudSignal,
	MMGLJournalLine,
	MerchantTill,
	MobileTransaction,
	MobileWallet,
	NotificationRequest,
	MMOutboxEvent,
	ReconciliationBreak,
	MMReconciliationRun,
	MMStandingOrder,
	WalletAuditEvent,
)

# ── Services ─────────────────────────────────────────────────────────────────
from .services import (
	AMLBlockedError,
	AMLDecision,
	FraudBlockedError,
	GLEntry,
	InsufficientFloatError,
	LimitExceededError,
	MobileMoneyError,
	MobileMoneyService,
	PINError,
	TransactionContext,
	WalletStatusError,
)

# ── Events ───────────────────────────────────────────────────────────────────
from .events import (
	AMLBlockedEvent,
	AMLReviewFlaggedEvent,
	AgentCommissionCalculatedEvent,
	AgentDepositEvent,
	AgentFloatLowEvent,
	AgentFloatToppedUpEvent,
	AgentWithdrawalEvent,
	BuyGoodsEvent,
	C2BNotificationEvent,
	DisbursementBatchCompletedEvent,
	DisbursementBatchStartedEvent,
	FeeCalculatedEvent,
	FraudBlockedEvent,
	FraudOTPRequiredEvent,
	GLJournalPostedEvent,
	IdempotentReplayEvent,
	KYCUpgradedEvent,
	MerchantSettledEvent,
	MoneyTransferredEvent,
	PayBillEvent,
	ReconciliationBreakEscalatedEvent,
	ReconciliationCompletedEvent,
	STKPushInitiatedEvent,
	StandingOrderExecutedEvent,
	StandingOrderSuspendedEvent,
	TransactionReversedEvent,
	WalletDormantEvent,
	WalletReactivatedEvent,
	WalletRegisteredEvent,
	WalletStatusChangedEvent,
	emit_mm_event,
)

# ── Views ─────────────────────────────────────────────────────────────────────
from .views import (
	AgentNetworkMapView,
	AgentView,
	FloatDashboard,
	MerchantView,
	TransactionView,
	WalletView,
)


# ── Plugin class ──────────────────────────────────────────────────────────────

class MobileMoneyPlugin:
	"""FAB plugin descriptor for Mobile Money + Agency Banking.

	Registers all views under the "Mobile Money" menu category.
	Call initialize(app, appbuilder) at startup to wire everything in.

	Example::

		plugin = MobileMoneyPlugin()
		plugin.initialize(app, appbuilder)
	"""

	name = "mobile_money"
	version = "1.0.0"

	def initialize(self, app, appbuilder) -> None:
		"""Wire plugin into the Flask app + AppBuilder."""
		log.info("MobileMoneyPlugin initializing")
		self.register_views(appbuilder)

	def register_views(self, appbuilder) -> None:
		"""Register all Mobile Money views with AppBuilder."""
		appbuilder.add_view(
			WalletView,
			"Wallets",
			icon="fa-mobile",
			category="Mobile Money",
			category_icon="fa-money",
		)
		appbuilder.add_view(
			TransactionView,
			"Transactions",
			icon="fa-list-alt",
			category="Mobile Money",
		)
		appbuilder.add_view(
			AgentView,
			"Agents",
			icon="fa-users",
			category="Mobile Money",
		)
		appbuilder.add_view(
			MerchantView,
			"Merchant Tills",
			icon="fa-shopping-cart",
			category="Mobile Money",
		)
		appbuilder.add_view(
			AgentNetworkMapView,
			"Agent Network Map",
			icon="fa-map",
			category="Mobile Money",
		)
		appbuilder.add_view(
			FloatDashboard,
			"Float Dashboard",
			icon="fa-bar-chart",
			category="Mobile Money",
		)
		log.info("MobileMoneyPlugin: registered 6 views")


# ── Public API ────────────────────────────────────────────────────────────────

__all__ = [
	# Plugin
	"MobileMoneyPlugin",
	# Models — original
	"MobileWallet",
	"MobileTransaction",
	"Agent",
	"AgentCommission",
	"MerchantTill",
	# Models — new (CRITICAL)
	"FeeSchedule",
	"MMOutboxEvent",
	"MMGLJournalLine",
	# Models — new (HIGH)
	"MMStandingOrder",
	"DisbursementBatch",
	"DisbursementLine",
	"FraudSignal",
	"NotificationRequest",
	"MMReconciliationRun",
	"ReconciliationBreak",
	"WalletAuditEvent",
	# Service + errors
	"MobileMoneyService",
	"MobileMoneyError",
	"InsufficientFloatError",
	"LimitExceededError",
	"PINError",
	"WalletStatusError",
	"AMLBlockedError",
	"FraudBlockedError",
	# Service helpers
	"AMLDecision",
	"GLEntry",
	"TransactionContext",
	# Events — original
	"WalletRegisteredEvent",
	"KYCUpgradedEvent",
	"WalletStatusChangedEvent",
	"MoneyTransferredEvent",
	"AgentDepositEvent",
	"AgentWithdrawalEvent",
	"BuyGoodsEvent",
	"PayBillEvent",
	"STKPushInitiatedEvent",
	"C2BNotificationEvent",
	"TransactionReversedEvent",
	"AgentFloatToppedUpEvent",
	"AgentFloatLowEvent",
	"AgentCommissionCalculatedEvent",
	"MerchantSettledEvent",
	# Events — new (CRITICAL)
	"FeeCalculatedEvent",
	"IdempotentReplayEvent",
	"GLJournalPostedEvent",
	# Events — new (HIGH)
	"StandingOrderExecutedEvent",
	"StandingOrderSuspendedEvent",
	"DisbursementBatchStartedEvent",
	"DisbursementBatchCompletedEvent",
	"AMLBlockedEvent",
	"AMLReviewFlaggedEvent",
	"FraudBlockedEvent",
	"FraudOTPRequiredEvent",
	"WalletDormantEvent",
	"WalletReactivatedEvent",
	"ReconciliationCompletedEvent",
	"ReconciliationBreakEscalatedEvent",
	"emit_mm_event",
	# Views
	"WalletView",
	"TransactionView",
	"AgentView",
	"MerchantView",
	"AgentNetworkMapView",
	"FloatDashboard",
]
