"""
pgappforge/plugins/fintech/swift/events.py

SWIFT domain events emitted by SWIFTService.

All events inherit from DomainEvent (dataclass-based, persisted to
DomainEventLog atomically with the business mutation). Event emission
is always wrapped in try/except in services.py — never causes service failure.

Event catalogue
---------------
  swift.message.sent          — outbound SWIFT message queued / transmitted
  swift.message.received      — inbound SWIFT message parsed and persisted
  swift.gpi.updated           — gpi Tracker status update received
  swift.nostro.debit_confirmed — MT900 processed, nostro debit matched
  swift.nostro.credit_confirmed — MT910 processed, nostro credit matched
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Event type string constants
# ---------------------------------------------------------------------------

SWIFT_MESSAGE_SENT = "swift.message.sent"
SWIFT_MESSAGE_RECEIVED = "swift.message.received"
SWIFT_GPI_UPDATED = "swift.gpi.updated"
SWIFT_NOSTRO_DEBIT_CONFIRMED = "swift.nostro.debit_confirmed"
SWIFT_NOSTRO_CREDIT_CONFIRMED = "swift.nostro.credit_confirmed"

ALL_SWIFT_EVENT_TYPES: tuple[str, ...] = (
	SWIFT_MESSAGE_SENT,
	SWIFT_MESSAGE_RECEIVED,
	SWIFT_GPI_UPDATED,
	SWIFT_NOSTRO_DEBIT_CONFIRMED,
	SWIFT_NOSTRO_CREDIT_CONFIRMED,
)


# ---------------------------------------------------------------------------
# SWIFTMessageSentEvent
# ---------------------------------------------------------------------------

@dataclass
class SWIFTMessageSentEvent(DomainEvent):
	"""Emitted when an outbound SWIFT message is persisted and queued for transmission.

	Downstream consumers:
	  - SWIFT bureau adapter (picks up DRAFT → SENT transition)
	  - Compliance/AML screening trigger
	  - Nostro position pre-advice updater
	"""
	event_type: str = SWIFT_MESSAGE_SENT
	message_id: str = ""
	message_ref: str = ""
	message_type: str = ""			# MT103 | MT202
	sender_bic: str = ""
	receiver_bic: str = ""
	value_date: str = ""			# ISO date string YYYY-MM-DD
	currency_code: str = ""
	amount_cents: int = 0
	uetr: str = ""					# empty string if not applicable
	gl_journal_id: str = ""


# ---------------------------------------------------------------------------
# SWIFTMessageReceivedEvent
# ---------------------------------------------------------------------------

@dataclass
class SWIFTMessageReceivedEvent(DomainEvent):
	"""Emitted when an inbound SWIFT FIN message is parsed and persisted.

	Downstream consumers:
	  - Core banking credit processor (MT103 inbound → credit beneficiary)
	  - Nostro reconciliation engine (MT900/MT910)
	  - Compliance screening (beneficiary / ordering customer check)
	"""
	event_type: str = SWIFT_MESSAGE_RECEIVED
	message_id: str = ""
	message_ref: str = ""
	message_type: str = ""			# MT103 | MT202 | MT900 | MT910
	sender_bic: str = ""
	receiver_bic: str = ""
	value_date: str = ""
	currency_code: str = ""
	amount_cents: int = 0
	uetr: str = ""
	ordering_customer: str = ""
	beneficiary_customer: str = ""


# ---------------------------------------------------------------------------
# SWIFTGpiUpdatedEvent
# ---------------------------------------------------------------------------

@dataclass
class SWIFTGpiUpdatedEvent(DomainEvent):
	"""Emitted when a gpi Tracker status update is received and persisted.

	Downstream consumers:
	  - Payment status API (real-time status push to originating customer)
	  - SLA monitoring (ACCC within 24h target)
	  - Exception management (RJCT → create return payment workflow)
	"""
	event_type: str = SWIFT_GPI_UPDATED
	gpi_status_id: str = ""
	message_id: str = ""
	uetr: str = ""
	status_code: str = ""			# ACSP | ACCC | RJCT | PDNG
	agent_bic: str = ""
	status_reason: str = ""			# empty if not RJCT
	event_timestamp: str = ""		# ISO datetime string
	is_final: bool = False			# True when status_code is ACCC or RJCT


# ---------------------------------------------------------------------------
# SWIFTNostroDebitConfirmedEvent
# ---------------------------------------------------------------------------

@dataclass
class SWIFTNostroDebitConfirmedEvent(DomainEvent):
	"""Emitted when an MT900 (Confirmation of Debit) is processed.

	MT900 is sent by the correspondent bank confirming a debit to our nostro
	account. This triggers nostro reconciliation matching against pending
	outbound MT103/MT202 items.

	Downstream consumers:
	  - Nostro reconciliation engine (match against outbound SWIFT messages)
	  - Treasury position updater (nostro balance decrement)
	  - GL auto-posting for confirmed debit
	"""
	event_type: str = SWIFT_NOSTRO_DEBIT_CONFIRMED
	message_id: str = ""
	message_ref: str = ""
	sender_bic: str = ""			# correspondent bank that sent the MT900
	value_date: str = ""
	currency_code: str = ""
	amount_cents: int = 0
	related_ref: str = ""			# :21: field — reference of the debit transaction


@dataclass
class SWIFTNostroCreditConfirmedEvent(DomainEvent):
	"""Emitted when an MT910 (Confirmation of Credit) is processed.

	MT910 is sent by the correspondent confirming a credit to our nostro.
	Triggers nostro reconciliation matching against expected inbound credits.

	Downstream consumers:
	  - Nostro reconciliation engine (match against expected credits)
	  - Treasury position updater (nostro balance increment)
	  - GL auto-posting for confirmed credit
	"""
	event_type: str = SWIFT_NOSTRO_CREDIT_CONFIRMED
	message_id: str = ""
	message_ref: str = ""
	sender_bic: str = ""
	value_date: str = ""
	currency_code: str = ""
	amount_cents: int = 0
	related_ref: str = ""			# :21: field — reference of the credit transaction


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"SWIFTMessageSentEvent",
	"SWIFTMessageReceivedEvent",
	"SWIFTGpiUpdatedEvent",
	"SWIFTNostroDebitConfirmedEvent",
	"SWIFTNostroCreditConfirmedEvent",
	# type string constants
	"ALL_SWIFT_EVENT_TYPES",
	"SWIFT_MESSAGE_SENT",
	"SWIFT_MESSAGE_RECEIVED",
	"SWIFT_GPI_UPDATED",
	"SWIFT_NOSTRO_DEBIT_CONFIRMED",
	"SWIFT_NOSTRO_CREDIT_CONFIRMED",
]
