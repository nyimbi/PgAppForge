"""
pgappforge/plugins/fintech/payments/__init__.py

Payments plugin — SWIFT/RTGS/PESALINK/ACH payment rails, standing orders,
direct debits, ISO 20022 PAIN.001 batch files, sanctions pre-screening,
and clearing house reconciliation.

Depends on:
  - pgappforge.plugins.fintech.core_banking
  - pgappforge.plugins.erp.foundation

Sub-modules:
  models   — PaymentOrder, PaymentBatch, PayStandingOrder, PaymentRail,
             PaymentStatusEvent
  services — PaymentsService
  events   — PaymentInitiatedEvent, PaymentSettledEvent, BatchCreatedEvent,
             StandingOrderCreatedEvent, InboundPaymentReceivedEvent,
             ReconciliationCompleteEvent, ...
  views    — PaymentOrderView, PaymentBatchView, StandingOrderView,
             PaymentRailView, PaymentsDashboard

Usage::

	from pgappforge.plugins.fintech.payments import (
		PaymentOrder, PaymentBatch, PayStandingOrder, PaymentRail,
		PaymentStatusEvent,
		PaymentsService,
		PaymentInitiatedEvent, PaymentSettledEvent,
	)
"""
from __future__ import annotations

from pgappforge.plugins.fintech.payments.models import (
	PaymentOrder,
	PaymentBatch,
	PayStandingOrder,
	PaymentRail,
	PaymentStatusEvent,
)

from pgappforge.plugins.fintech.payments.services import (
	PaymentsService,
	PaymentsError,
	PaymentNotFoundError,
	InsufficientFundsError,
	RailNotAvailableError,
	PaymentImmutableError,
	SanctionsHitError,
)

from pgappforge.plugins.fintech.payments.events import (
	PaymentInitiatedEvent,
	PaymentValidatedEvent,
	PaymentAuthorizedEvent,
	PaymentSubmittedEvent,
	PaymentSettledEvent,
	PaymentRejectedEvent,
	PaymentReturnedEvent,
	PaymentCancelledEvent,
	BatchCreatedEvent,
	BatchSubmittedEvent,
	BatchSettledEvent,
	BatchPartiallySettledEvent,
	StandingOrderCreatedEvent,
	StandingOrderExecutedEvent,
	StandingOrderFailedEvent,
	StandingOrderCancelledEvent,
	InboundPaymentReceivedEvent,
	ReconciliationCompleteEvent,
	ALL_PY_EVENT_TYPES,
)

from pgappforge.plugins.fintech.payments.views import (
	PaymentOrderView,
	PaymentBatchView,
	StandingOrderView,
	PaymentRailView,
	PaymentsDashboard,
)

__all__ = [
	# models
	"PaymentOrder",
	"PaymentBatch",
	"PayStandingOrder",
	"PaymentRail",
	"PaymentStatusEvent",
	# services
	"PaymentsService",
	"PaymentsError",
	"PaymentNotFoundError",
	"InsufficientFundsError",
	"RailNotAvailableError",
	"PaymentImmutableError",
	"SanctionsHitError",
	# events
	"PaymentInitiatedEvent",
	"PaymentValidatedEvent",
	"PaymentAuthorizedEvent",
	"PaymentSubmittedEvent",
	"PaymentSettledEvent",
	"PaymentRejectedEvent",
	"PaymentReturnedEvent",
	"PaymentCancelledEvent",
	"BatchCreatedEvent",
	"BatchSubmittedEvent",
	"BatchSettledEvent",
	"BatchPartiallySettledEvent",
	"StandingOrderCreatedEvent",
	"StandingOrderExecutedEvent",
	"StandingOrderFailedEvent",
	"StandingOrderCancelledEvent",
	"InboundPaymentReceivedEvent",
	"ReconciliationCompleteEvent",
	"ALL_PY_EVENT_TYPES",
	# views
	"PaymentOrderView",
	"PaymentBatchView",
	"StandingOrderView",
	"PaymentRailView",
	"PaymentsDashboard",
]
