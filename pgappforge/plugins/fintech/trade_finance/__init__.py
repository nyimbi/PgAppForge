"""
pgappforge/plugins/fintech/trade_finance/__init__.py

Trade Finance plugin for pgappforge fintech suite.

Depends on:
  - pgappforge.plugins.fintech.core_banking  (account holds, CB accounts)
  - pgappforge.plugins.fintech.payments       (settlement execution)
  - pgappforge.plugins.erp.foundation         (Party, commons, view_helpers, events)

Lazy cross-plugin imports:
  - pgappforge.plugins.erp.finance.gl         (GL journal posting — optional)
  - pgappforge.plugins.fintech.core_banking   (account hold/release — optional)

Coverage:
  Letters of Credit (LC)        — SIGHT/USANCE/TRANSFERABLE/BACK_TO_BACK/STANDBY/RED_CLAUSE/GREEN_CLAUSE
  LC Presentations               — UCP 600 document examination, compliant/discrepant flow
  Bank Guarantees                — BID_BOND/PERFORMANCE/ADVANCE_PAYMENT/PAYMENT/RETENTION/CUSTOMS
  Documentary Collections        — D/P and D/A (SWIFT MT400/MT410)
  Supply Chain Finance           — buyer-anchored reverse factoring (SCF programme + receivables)

East Africa focus:
  - SGR goods imports through Mombasa (import LCs)
  - Agricultural exports: tea, coffee, flowers (export LCs/collections)
  - Government tenders: bid bonds, performance guarantees (KES-denominated)
  - Oil import financing (USD LCs, multi-bank syndication)
  - FMCG supply chain early payment (SCF programmes)
"""
from __future__ import annotations

from pgappforge.plugins.fintech.trade_finance.models import (
	BankGuarantee,
	DocumentaryCollection,
	LetterOfCredit,
	LCPresentation,
	SCFReceivable,
	SupplyChainFinanceProgram,
)
from pgappforge.plugins.fintech.trade_finance.events import (
	# LC events
	LCIssuedEvent,
	LCAmendedEvent,
	LCPresentationReceivedEvent,
	LCPresentationCompliantEvent,
	LCPresentationDiscrepantEvent,
	LCPresentationAcceptedEvent,
	LCPresentationRejectedEvent,
	LCSettledEvent,
	LCExpiredEvent,
	# Guarantee events
	GuaranteeIssuedEvent,
	GuaranteeExtendedEvent,
	GuaranteeClaimedEvent,
	GuaranteeExpiredEvent,
	# Collection events
	CollectionReceivedEvent,
	CollectionPresentedEvent,
	CollectionPaidEvent,
	CollectionAcceptedEvent,
	CollectionProtestedEvent,
	# SCF events
	SCFReceivableFundedEvent,
	SCFReceivableRepaidEvent,
	# type string constants
	ALL_TF_EVENT_TYPES,
	TF_LC_ISSUED,
	TF_LC_AMENDED,
	TF_LC_PRESENTATION_RECEIVED,
	TF_LC_PRESENTATION_COMPLIANT,
	TF_LC_PRESENTATION_DISCREPANT,
	TF_LC_PRESENTATION_ACCEPTED,
	TF_LC_PRESENTATION_REJECTED,
	TF_LC_SETTLED,
	TF_LC_EXPIRED,
	TF_GUARANTEE_ISSUED,
	TF_GUARANTEE_EXTENDED,
	TF_GUARANTEE_CLAIMED,
	TF_GUARANTEE_EXPIRED,
	TF_COLLECTION_RECEIVED,
	TF_COLLECTION_PRESENTED,
	TF_COLLECTION_PAID,
	TF_COLLECTION_ACCEPTED,
	TF_COLLECTION_PROTESTED,
	TF_SCF_RECEIVABLE_FUNDED,
	TF_SCF_RECEIVABLE_REPAID,
)
from pgappforge.plugins.fintech.trade_finance.services import TradeFinanceService

# Views require flask_appbuilder — import lazily so models/services remain
# importable in headless / test environments where FAB is not on sys.path.
try:
	from pgappforge.plugins.fintech.trade_finance.views import (
		CollectionView,
		GuaranteeView,
		LCPresentationView,
		LCView,
		SCFProgramView,
		SCFReceivableView,
		TradeDashboard,
	)
	_VIEWS_AVAILABLE = True
except ImportError:
	_VIEWS_AVAILABLE = False
	CollectionView = None  # type: ignore[assignment,misc]
	GuaranteeView = None  # type: ignore[assignment,misc]
	LCPresentationView = None  # type: ignore[assignment,misc]
	LCView = None  # type: ignore[assignment,misc]
	SCFProgramView = None  # type: ignore[assignment,misc]
	SCFReceivableView = None  # type: ignore[assignment,misc]
	TradeDashboard = None  # type: ignore[assignment,misc]

__all__ = [
	# models
	"LetterOfCredit",
	"LCPresentation",
	"BankGuarantee",
	"DocumentaryCollection",
	"SupplyChainFinanceProgram",
	"SCFReceivable",
	# services
	"TradeFinanceService",
	# views
	"LCView",
	"LCPresentationView",
	"GuaranteeView",
	"CollectionView",
	"SCFProgramView",
	"SCFReceivableView",
	"TradeDashboard",
	# LC events
	"LCIssuedEvent",
	"LCAmendedEvent",
	"LCPresentationReceivedEvent",
	"LCPresentationCompliantEvent",
	"LCPresentationDiscrepantEvent",
	"LCPresentationAcceptedEvent",
	"LCPresentationRejectedEvent",
	"LCSettledEvent",
	"LCExpiredEvent",
	# guarantee events
	"GuaranteeIssuedEvent",
	"GuaranteeExtendedEvent",
	"GuaranteeClaimedEvent",
	"GuaranteeExpiredEvent",
	# collection events
	"CollectionReceivedEvent",
	"CollectionPresentedEvent",
	"CollectionPaidEvent",
	"CollectionAcceptedEvent",
	"CollectionProtestedEvent",
	# SCF events
	"SCFReceivableFundedEvent",
	"SCFReceivableRepaidEvent",
	# event type constants
	"ALL_TF_EVENT_TYPES",
	"TF_LC_ISSUED",
	"TF_LC_AMENDED",
	"TF_LC_PRESENTATION_RECEIVED",
	"TF_LC_PRESENTATION_COMPLIANT",
	"TF_LC_PRESENTATION_DISCREPANT",
	"TF_LC_PRESENTATION_ACCEPTED",
	"TF_LC_PRESENTATION_REJECTED",
	"TF_LC_SETTLED",
	"TF_LC_EXPIRED",
	"TF_GUARANTEE_ISSUED",
	"TF_GUARANTEE_EXTENDED",
	"TF_GUARANTEE_CLAIMED",
	"TF_GUARANTEE_EXPIRED",
	"TF_COLLECTION_RECEIVED",
	"TF_COLLECTION_PRESENTED",
	"TF_COLLECTION_PAID",
	"TF_COLLECTION_ACCEPTED",
	"TF_COLLECTION_PROTESTED",
	"TF_SCF_RECEIVABLE_FUNDED",
	"TF_SCF_RECEIVABLE_REPAID",
]
