"""
pgappforge/plugins/fintech/terminal_management/models.py

Terminal Management models — POS/ATM terminals, key injection, health events,
parameter deployment, and batch settlement.

Design rules:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - TerminalHealthEvent: ImmutableRecordMixin (insert-only, append-only log)
  - Encrypted keys stored as AES-256 ciphertext; KCV for integrity validation
  - terminal_id (TID) is 8-char per ISO 8583 convention

Table name convention: ft_terminal_*
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Terminal — POS/ATM terminal registry
# ---------------------------------------------------------------------------

class Terminal(AuditMixin, Model):
	"""A payment terminal (POS, ATM, kiosk, etc.) registered under a tenant.

	terminal_id: the 8-char TID used in ISO 8583 field 41 (POS Terminal ID).
	terminal_type: STANDALONE_POS | MPOS | SOFTPOS | ATM | KIOSK |
	               ONLINE_POS | UNATTENDED
	status flow: INACTIVE → ACTIVE (activate_terminal)
	             ACTIVE → SUSPENDED (admin)
	             ACTIVE → TAMPERED (tamper alert)
	             any   → DECOMMISSIONED (decommission)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_terminal"
	__table_args__ = (
		UniqueConstraint("terminal_id", name="uq_ft_terminal_tid"),
		Index("ix_ft_terminal_tenant", "tenant_id"),
		Index("ix_ft_terminal_merchant", "merchant_id"),
		Index("ix_ft_terminal_status", "status"),
		Index("ix_ft_terminal_type", "terminal_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Tenant scope",
	)
	terminal_id = Column(
		String(8),
		nullable=False,
		unique=True,
		comment="8-char POS Terminal ID (ISO 8583 field 41)",
	)
	terminal_type = Column(
		String(20),
		nullable=False,
		default="STANDALONE_POS",
		comment="STANDALONE_POS | MPOS | SOFTPOS | ATM | KIOSK | ONLINE_POS | UNATTENDED",
	)
	merchant_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="Owning merchant UUID",
	)
	merchant_name = Column(String(200), nullable=True)
	software_version = Column(String(20), nullable=True)
	firmware_version = Column(String(20), nullable=True)
	serial_number = Column(String(50), nullable=True)
	imei = Column(String(20), nullable=True, comment="IMEI for mPOS devices")
	ip_address = Column(String(45), nullable=True, comment="IPv4 or IPv6")
	status = Column(
		String(12),
		nullable=False,
		default="INACTIVE",
		comment="INACTIVE | ACTIVE | SUSPENDED | DECOMMISSIONED | TAMPERED",
	)
	last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
	last_transaction_at = Column(DateTime(timezone=True), nullable=True)
	pci_dss_compliant = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True when active key injection has been confirmed",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	keys: list[TerminalKey] = relationship(
		"TerminalKey",
		back_populates="terminal",
		lazy="select",
	)
	parameters: list[TerminalParameter] = relationship(
		"TerminalParameter",
		back_populates="terminal",
		lazy="select",
	)
	health_events: list[TerminalHealthEvent] = relationship(
		"TerminalHealthEvent",
		back_populates="terminal",
		lazy="select",
	)
	batches: list[TerminalBatch] = relationship(
		"TerminalBatch",
		back_populates="terminal",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Terminal {self.id!r} "
			f"tid={self.terminal_id!r} "
			f"type={self.terminal_type!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# TerminalKey — cryptographic key injection registry
# ---------------------------------------------------------------------------

class TerminalKey(Model):
	"""Encrypted cryptographic key injected into a terminal.

	key_type: TMK | TPK | TAK | ZMK | ZPK | DUKPT_BDK
	encrypted_key: AES-256 encrypted key material (stored ciphertext only).
	key_check_value: 6-hex-char KCV for integrity verification.

	Only one key per (terminal, key_type) may be active at a time.
	inject_key() deactivates the prior key before inserting a new one.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_terminal_key"
	__table_args__ = (
		Index("ix_ft_terminal_key_terminal", "terminal_id"),
		Index("ix_ft_terminal_key_type", "key_type"),
		Index("ix_ft_terminal_key_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	terminal_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_terminal.id"),
		nullable=False,
		index=True,
	)
	key_type = Column(
		String(20),
		nullable=False,
		comment="TMK | TPK | TAK | ZMK | ZPK | DUKPT_BDK",
	)
	encrypted_key = Column(
		Text,
		nullable=False,
		comment="AES-256 encrypted key material (base64-encoded ciphertext)",
	)
	key_check_value = Column(
		String(6),
		nullable=True,
		comment="6-hex-char Key Check Value for integrity verification",
	)
	valid_from = Column(DateTime(timezone=True), nullable=False)
	valid_to = Column(DateTime(timezone=True), nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)
	injected_by = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="UUID of operator who performed the injection",
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	terminal: Terminal = relationship("Terminal", back_populates="keys", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<TerminalKey {self.id!r} "
			f"type={self.key_type!r} "
			f"active={self.is_active!r}>"
		)


# ---------------------------------------------------------------------------
# TerminalParameter — terminal configuration parameter sets
# ---------------------------------------------------------------------------

class TerminalParameter(Model):
	"""Versioned parameter set deployed to a terminal.

	param_set JSONB schema (required keys):
	  accepted_cards  — list of card schemes accepted
	  currency_code   — ISO 4217 currency code (e.g. "KES")
	  floor_limit     — integer cents floor limit for offline approval
	  tid             — terminal ID (must match terminal.terminal_id)
	  mid             — merchant ID

	  Optional: batch_number, acquirer_id

	status: PENDING (created) → DEPLOYED (acknowledged by terminal)
	        → SUPERSEDED (when newer param version deployed)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_terminal_param"
	__table_args__ = (
		Index("ix_ft_terminal_param_terminal", "terminal_id"),
		Index("ix_ft_terminal_param_status", "status"),
		Index("ix_ft_terminal_param_version", "terminal_id", "param_version"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	terminal_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_terminal.id"),
		nullable=False,
		index=True,
	)
	param_version = Column(Integer, nullable=False, comment="Monotonically increasing version")
	param_set: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment=(
			"Parameter set: {accepted_cards, currency_code, floor_limit, "
			"tid, mid, batch_number, acquirer_id}"
		),
	)
	deployed_at = Column(DateTime(timezone=True), nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="PENDING",
		comment="PENDING | DEPLOYED | SUPERSEDED",
	)

	# Relationships
	terminal: Terminal = relationship("Terminal", back_populates="parameters", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<TerminalParameter {self.id!r} "
			f"version={self.param_version!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# TerminalHealthEvent — immutable terminal health/status event log
# ---------------------------------------------------------------------------

class TerminalHealthEvent(ImmutableRecordMixin, Model):
	"""Immutable event record for terminal health monitoring.

	event_type: HEARTBEAT | STARTUP | SHUTDOWN | ERROR | TAMPER_ALERT |
	            LOW_PAPER | BATTERY_LOW | NETWORK_LOST

	TAMPER_ALERT events trigger automatic terminal suspension (status=TAMPERED)
	and emit a TerminalTamperEvent.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_terminal_health"
	__table_args__ = (
		Index("ix_ft_th_terminal", "terminal_id"),
		Index("ix_ft_th_event_type", "event_type"),
		Index("ix_ft_th_occurred_at", "occurred_at"),
		Index(
			"ix_ft_th_terminal_occurred",
			"terminal_id",
			"occurred_at",
			postgresql_using="brin",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	terminal_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_terminal.id"),
		nullable=False,
		index=True,
	)
	event_type = Column(
		String(20),
		nullable=False,
		comment=(
			"HEARTBEAT | STARTUP | SHUTDOWN | ERROR | TAMPER_ALERT | "
			"LOW_PAPER | BATTERY_LOW | NETWORK_LOST"
		),
	)
	detail: dict[str, Any] | None = Column(
		JSONB,
		nullable=True,
		comment="Event-specific detail payload",
	)
	occurred_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	terminal: Terminal = relationship(
		"Terminal",
		back_populates="health_events",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<TerminalHealthEvent {self.id!r} "
			f"type={self.event_type!r} "
			f"at={self.occurred_at!r}>"
		)


# Register immutability guard
TerminalHealthEvent._register_immutability()


# ---------------------------------------------------------------------------
# TerminalBatch — end-of-day settlement batch
# ---------------------------------------------------------------------------

class TerminalBatch(Model):
	"""End-of-day settlement batch for a terminal.

	One OPEN batch per terminal at a time.
	close_batch() sets closed_at and status=CLOSED.
	status: OPEN → CLOSED → SETTLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_terminal_batch"
	__table_args__ = (
		Index("ix_ft_batch_terminal", "terminal_id"),
		Index("ix_ft_batch_status", "status"),
		Index("ix_ft_batch_number", "terminal_id", "batch_number"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	terminal_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_terminal.id"),
		nullable=False,
		index=True,
	)
	batch_number = Column(Integer, nullable=False)
	transaction_count = Column(Integer, nullable=False, default=0)
	total_sales_cents = Column(Integer, nullable=False, default=0)
	total_refunds_cents = Column(Integer, nullable=False, default=0)
	opened_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	closed_at = Column(DateTime(timezone=True), nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="OPEN",
		comment="OPEN | CLOSED | SETTLED",
	)

	# Relationships
	terminal: Terminal = relationship("Terminal", back_populates="batches", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<TerminalBatch {self.id!r} "
			f"batch={self.batch_number!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Terminal",
	"TerminalKey",
	"TerminalParameter",
	"TerminalHealthEvent",
	"TerminalBatch",
]
