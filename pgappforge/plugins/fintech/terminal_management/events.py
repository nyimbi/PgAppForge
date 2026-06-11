"""
pgappforge/plugins/fintech/terminal_management/events.py

Terminal Management domain events.

All events extend DomainEvent from erp.foundation.events.
They are emitted by TerminalManagementService and should be persisted
atomically within the same SQLAlchemy session as the triggering operation.

Event catalogue
---------------
  terminal.provisioned     — new terminal registered (INACTIVE)
  terminal.activated       — terminal status transitions INACTIVE → ACTIVE
  terminal.key_injected    — cryptographic key successfully injected
  terminal.tamper_alert    — tamper event detected; terminal auto-suspended
  terminal.batch_closed    — end-of-day batch closed for a terminal
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Terminal lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class TerminalProvisionedEvent(DomainEvent):
	"""Emitted when a new terminal is registered in the system."""
	event_type: str = "terminal.provisioned"
	terminal_db_id: str = ""
	terminal_id: str = ""        # 8-char TID
	terminal_type: str = ""
	merchant_id: str = ""
	merchant_name: str = ""


@dataclass
class TerminalActivatedEvent(DomainEvent):
	"""Emitted when a terminal transitions INACTIVE → ACTIVE."""
	event_type: str = "terminal.activated"
	terminal_db_id: str = ""
	terminal_id: str = ""
	pci_dss_compliant: bool = False
	activated_at: str = ""       # ISO datetime string


@dataclass
class KeyInjectedEvent(DomainEvent):
	"""Emitted when a cryptographic key is successfully injected into a terminal."""
	event_type: str = "terminal.key_injected"
	terminal_db_id: str = ""
	terminal_id: str = ""
	key_type: str = ""           # TMK | TPK | TAK | ZMK | ZPK | DUKPT_BDK
	key_check_value: str = ""
	injected_by: str = ""


@dataclass
class TerminalTamperEvent(DomainEvent):
	"""Emitted when a TAMPER_ALERT health event is received; terminal auto-suspended."""
	event_type: str = "terminal.tamper_alert"
	terminal_db_id: str = ""
	terminal_id: str = ""
	detail: dict = field(default_factory=dict)
	occurred_at: str = ""        # ISO datetime string


@dataclass
class BatchClosedEvent(DomainEvent):
	"""Emitted when an end-of-day settlement batch is closed for a terminal."""
	event_type: str = "terminal.batch_closed"
	batch_id: str = ""
	terminal_db_id: str = ""
	terminal_id: str = ""
	batch_number: int = 0
	transaction_count: int = 0
	total_sales_cents: int = 0
	total_refunds_cents: int = 0
	closed_at: str = ""          # ISO datetime string


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

TM_TERMINAL_PROVISIONED = "terminal.provisioned"
TM_TERMINAL_ACTIVATED = "terminal.activated"
TM_KEY_INJECTED = "terminal.key_injected"
TM_TAMPER_ALERT = "terminal.tamper_alert"
TM_BATCH_CLOSED = "terminal.batch_closed"

ALL_TM_EVENT_TYPES: list[str] = [
	TM_TERMINAL_PROVISIONED,
	TM_TERMINAL_ACTIVATED,
	TM_KEY_INJECTED,
	TM_TAMPER_ALERT,
	TM_BATCH_CLOSED,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"TerminalProvisionedEvent",
	"TerminalActivatedEvent",
	"KeyInjectedEvent",
	"TerminalTamperEvent",
	"BatchClosedEvent",
	# event type constants
	"TM_TERMINAL_PROVISIONED",
	"TM_TERMINAL_ACTIVATED",
	"TM_KEY_INJECTED",
	"TM_TAMPER_ALERT",
	"TM_BATCH_CLOSED",
	"ALL_TM_EVENT_TYPES",
]
