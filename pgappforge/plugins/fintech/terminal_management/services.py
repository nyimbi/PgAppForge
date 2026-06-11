"""
pgappforge/plugins/fintech/terminal_management/services.py

TerminalManagementService — terminal lifecycle, key injection, parameter
deployment, health monitoring, and batch settlement.

Design principles:
  - Stateless service; all methods receive an explicit SQLAlchemy session.
  - Transaction boundaries owned by the caller.
  - All monetary amounts in integer cents.
  - terminal_id lookup: accepts either the terminal DB UUID or the 8-char TID.
  - Key encryption is the caller's responsibility; this service persists the
    provided encrypted_key ciphertext verbatim.

Public methods:
  provision_terminal(...)      -> Terminal
  activate_terminal(...)       -> Terminal
  inject_key(...)              -> TerminalKey
  deploy_parameters(...)       -> TerminalParameter
  record_health_event(...)     -> TerminalHealthEvent
  record_heartbeat(...)        -> None
  get_compliance_status(...)   -> dict
  open_batch(...)              -> TerminalBatch
  close_batch(...)             -> TerminalBatch
  decommission(...)            -> Terminal
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.fintech.terminal_management.events import (
	BatchClosedEvent,
	KeyInjectedEvent,
	TerminalActivatedEvent,
	TerminalProvisionedEvent,
	TerminalTamperEvent,
)
from pgappforge.plugins.fintech.terminal_management.models import (
	Terminal,
	TerminalBatch,
	TerminalHealthEvent,
	TerminalKey,
	TerminalParameter,
)

log = logging.getLogger(__name__)

_REQUIRED_PARAM_KEYS = {"accepted_cards", "currency_code", "floor_limit", "tid", "mid"}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TerminalManagementError(Exception):
	"""Base domain error for terminal management operations."""


class TerminalNotFoundError(TerminalManagementError):
	pass


class TerminalStateError(TerminalManagementError):
	"""Invalid state transition."""


class TerminalValidationError(TerminalManagementError):
	"""Validation failure (e.g. bad terminal_id format)."""


class BatchError(TerminalManagementError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _emit(event: Any) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _ev
		_ev(event, None)
	except Exception:
		pass


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _resolve_terminal(terminal_id_or_tid: str, tenant_id: str, session: Any) -> Terminal:
	"""Resolve by DB UUID first, then fall back to 8-char TID lookup."""
	# Try DB UUID
	row = session.execute(
		select(Terminal).where(
			Terminal.id == terminal_id_or_tid,
			Terminal.tenant_id == tenant_id,
		)
	).scalar_one_or_none()
	if row:
		return row
	# Try TID
	row = session.execute(
		select(Terminal).where(
			Terminal.terminal_id == terminal_id_or_tid,
			Terminal.tenant_id == tenant_id,
		)
	).scalar_one_or_none()
	if not row:
		raise TerminalNotFoundError(
			f"Terminal not found: {terminal_id_or_tid!r} (tenant={tenant_id!r})"
		)
	return row


# ---------------------------------------------------------------------------
# BPM process registration
# ---------------------------------------------------------------------------

def _register_bpm() -> None:
	try:
		from pgappforge.plugins.bpm import register

		@register("terminal.provision", "Provision a new payment terminal")
		def _bpm_provision(
			terminal_id: str,
			terminal_type: str,
			merchant_id: str,
			merchant_name: str,
			tenant_id: str,
			session: Any,
		) -> dict:
			svc = TerminalManagementService()
			t = svc.provision_terminal(
				terminal_id=terminal_id,
				terminal_type=terminal_type,
				merchant_id=merchant_id,
				merchant_name=merchant_name,
				tenant_id=tenant_id,
				session=session,
			)
			return {"terminal_db_id": t.id, "terminal_id": t.terminal_id, "status": t.status}

		@register("terminal.record_health_event", "Record a terminal health/status event")
		def _bpm_health(
			terminal_id_or_tid: str,
			event_type: str,
			tenant_id: str,
			session: Any,
			detail: dict | None = None,
		) -> dict:
			svc = TerminalManagementService()
			ev = svc.record_health_event(
				terminal_id_or_tid=terminal_id_or_tid,
				event_type=event_type,
				tenant_id=tenant_id,
				session=session,
				detail=detail,
			)
			return {"health_event_id": ev.id, "event_type": ev.event_type}

	except ImportError:
		log.debug(
			"TerminalManagementService: BPM plugin not available, "
			"skipping process registration"
		)


# ---------------------------------------------------------------------------
# TerminalManagementService
# ---------------------------------------------------------------------------

class TerminalManagementService:
	"""Stateless service for POS/ATM terminal lifecycle management.

	All methods receive an explicit SQLAlchemy session and do not call
	session.commit() — the caller owns transaction boundaries.
	"""

	# ------------------------------------------------------------------
	# Provisioning
	# ------------------------------------------------------------------

	def provision_terminal(
		self,
		terminal_id: str,
		terminal_type: str,
		merchant_id: str,
		merchant_name: str,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	) -> Terminal:
		"""Register a new terminal with INACTIVE status.

		Args:
			terminal_id:    8-char POS TID (ISO 8583 field 41). Must be exactly 8 chars.
			terminal_type:  STANDALONE_POS | MPOS | SOFTPOS | ATM | KIOSK |
			                ONLINE_POS | UNATTENDED
			merchant_id:    UUID of the owning merchant.
			merchant_name:  Display name of the merchant.
			tenant_id:      Tenant scope UUID.
			session:        SQLAlchemy session.
			**kwargs:       Optional: software_version, firmware_version, serial_number,
			                imei, ip_address.

		Returns:
			Terminal with status=INACTIVE.

		Raises:
			TerminalValidationError: if terminal_id is not exactly 8 characters.
		"""
		assert session is not None, "session required"
		assert tenant_id, "tenant_id required"

		if len(terminal_id) != 8:
			raise TerminalValidationError(
				f"terminal_id must be exactly 8 characters, got {len(terminal_id)!r}: "
				f"{terminal_id!r}"
			)

		terminal = Terminal(
			tenant_id=tenant_id,
			terminal_id=terminal_id,
			terminal_type=terminal_type,
			merchant_id=merchant_id,
			merchant_name=merchant_name,
			status="INACTIVE",
			pci_dss_compliant=False,
			software_version=kwargs.get("software_version"),
			firmware_version=kwargs.get("firmware_version"),
			serial_number=kwargs.get("serial_number"),
			imei=kwargs.get("imei"),
			ip_address=kwargs.get("ip_address"),
		)
		session.add(terminal)
		session.flush()

		_emit(TerminalProvisionedEvent(
			aggregate_type="Terminal",
			aggregate_id=terminal.id,
			tenant_id=tenant_id,
			terminal_db_id=terminal.id,
			terminal_id=terminal_id,
			terminal_type=terminal_type,
			merchant_id=str(merchant_id),
			merchant_name=merchant_name,
		))
		log.info("Terminal provisioned: tid=%r db_id=%r tenant=%r", terminal_id, terminal.id, tenant_id)
		return terminal

	# ------------------------------------------------------------------
	# Activation
	# ------------------------------------------------------------------

	def activate_terminal(
		self,
		terminal_id_or_tid: str,
		tenant_id: str,
		session: Any,
	) -> Terminal:
		"""Transition terminal INACTIVE → ACTIVE.

		Sets pci_dss_compliant=True if the terminal has at least one active key.

		Args:
			terminal_id_or_tid: DB UUID or 8-char TID.
			tenant_id:          Tenant scope UUID.
			session:            SQLAlchemy session.

		Returns:
			Updated Terminal.

		Raises:
			TerminalStateError: if terminal is not in INACTIVE status.
		"""
		terminal = _resolve_terminal(terminal_id_or_tid, tenant_id, session)
		if terminal.status != "INACTIVE":
			raise TerminalStateError(
				f"Terminal {terminal.terminal_id!r} must be INACTIVE to activate "
				f"(current: {terminal.status!r})"
			)

		# Check if any active keys exist
		key_count = session.execute(
			select(sa.func.count(TerminalKey.id)).where(
				TerminalKey.terminal_id == terminal.id,
				TerminalKey.is_active == sa.true(),
			)
		).scalar_one()

		terminal.status = "ACTIVE"
		terminal.pci_dss_compliant = key_count > 0
		terminal.updated_at = _now()
		session.flush()

		_emit(TerminalActivatedEvent(
			aggregate_type="Terminal",
			aggregate_id=terminal.id,
			tenant_id=tenant_id,
			terminal_db_id=terminal.id,
			terminal_id=terminal.terminal_id,
			pci_dss_compliant=terminal.pci_dss_compliant,
			activated_at=_now().isoformat(),
		))
		log.info(
			"Terminal activated: tid=%r pci_dss=%r",
			terminal.terminal_id,
			terminal.pci_dss_compliant,
		)
		return terminal

	# ------------------------------------------------------------------
	# Key injection
	# ------------------------------------------------------------------

	def inject_key(
		self,
		terminal_db_id: str,
		key_type: str,
		encrypted_key: str,
		tenant_id: str,
		session: Any,
		*,
		key_check_value: str | None = None,
		valid_to: datetime | None = None,
		injected_by: str | None = None,
	) -> TerminalKey:
		"""Inject an encrypted cryptographic key into a terminal.

		Deactivates any existing active key of the same type before creating
		the new key record.

		Args:
			terminal_db_id:  Terminal DB UUID.
			key_type:        TMK | TPK | TAK | ZMK | ZPK | DUKPT_BDK
			encrypted_key:   AES-256 encrypted key material (ciphertext, caller's responsibility).
			tenant_id:       Tenant scope UUID.
			session:         SQLAlchemy session.
			key_check_value: Optional 6-hex-char KCV for integrity verification.
			valid_to:        Optional expiry for this key.
			injected_by:     UUID of the operator performing the injection.

		Returns:
			Newly created TerminalKey (is_active=True).
		"""
		assert terminal_db_id, "terminal_db_id required"
		assert encrypted_key, "encrypted_key required"

		# Deactivate existing active keys of same type
		session.execute(
			sa.update(TerminalKey)
			.where(
				TerminalKey.terminal_id == terminal_db_id,
				TerminalKey.key_type == key_type,
				TerminalKey.is_active == sa.true(),
			)
			.values(is_active=False)
		)

		key = TerminalKey(
			tenant_id=tenant_id,
			terminal_id=terminal_db_id,
			key_type=key_type,
			encrypted_key=encrypted_key,
			key_check_value=key_check_value,
			valid_from=_now(),
			valid_to=valid_to,
			is_active=True,
			injected_by=injected_by,
		)
		session.add(key)
		session.flush()

		# Resolve TID for event
		terminal = session.get(Terminal, terminal_db_id)
		tid = terminal.terminal_id if terminal else terminal_db_id

		_emit(KeyInjectedEvent(
			aggregate_type="Terminal",
			aggregate_id=terminal_db_id,
			tenant_id=tenant_id,
			terminal_db_id=terminal_db_id,
			terminal_id=tid,
			key_type=key_type,
			key_check_value=key_check_value or "",
			injected_by=str(injected_by) if injected_by else "",
		))
		log.info(
			"Key injected: terminal_db_id=%r type=%r kcv=%r",
			terminal_db_id,
			key_type,
			key_check_value,
		)
		return key

	# ------------------------------------------------------------------
	# Parameter deployment
	# ------------------------------------------------------------------

	def deploy_parameters(
		self,
		terminal_db_id: str,
		param_set: dict[str, Any],
		tenant_id: str,
		session: Any,
	) -> TerminalParameter:
		"""Deploy a new parameter set to a terminal.

		Marks the previous active parameter record as SUPERSEDED, then creates
		a new TerminalParameter with status=DEPLOYED. Validates that param_set
		contains all required keys.

		Args:
			terminal_db_id: Terminal DB UUID.
			param_set:      Dict containing at minimum: accepted_cards, currency_code,
			                floor_limit, tid, mid.
			tenant_id:      Tenant scope UUID.
			session:        SQLAlchemy session.

		Returns:
			Newly created TerminalParameter (status=DEPLOYED).

		Raises:
			TerminalValidationError: if required param_set keys are missing.
		"""
		missing = _REQUIRED_PARAM_KEYS - set(param_set.keys())
		if missing:
			raise TerminalValidationError(
				f"param_set missing required keys: {sorted(missing)}"
			)

		# Supersede existing non-superseded params
		session.execute(
			sa.update(TerminalParameter)
			.where(
				TerminalParameter.terminal_id == terminal_db_id,
				TerminalParameter.status.in_(["PENDING", "DEPLOYED"]),
			)
			.values(status="SUPERSEDED")
		)

		# Determine next version
		max_version = session.execute(
			select(sa.func.coalesce(sa.func.max(TerminalParameter.param_version), 0)).where(
				TerminalParameter.terminal_id == terminal_db_id,
			)
		).scalar_one()

		param = TerminalParameter(
			tenant_id=tenant_id,
			terminal_id=terminal_db_id,
			param_version=max_version + 1,
			param_set=param_set,
			deployed_at=_now(),
			status="DEPLOYED",
		)
		session.add(param)
		session.flush()
		log.info(
			"Parameters deployed: terminal_db_id=%r version=%r",
			terminal_db_id,
			param.param_version,
		)
		return param

	# ------------------------------------------------------------------
	# Health event recording
	# ------------------------------------------------------------------

	def record_health_event(
		self,
		terminal_id_or_tid: str,
		event_type: str,
		tenant_id: str,
		session: Any,
		*,
		detail: dict | None = None,
	) -> TerminalHealthEvent:
		"""Record a terminal health event.

		TAMPER_ALERT events automatically suspend the terminal (status=TAMPERED)
		and emit a TerminalTamperEvent domain event.

		Args:
			terminal_id_or_tid: DB UUID or 8-char TID.
			event_type:         HEARTBEAT | STARTUP | SHUTDOWN | ERROR |
			                    TAMPER_ALERT | LOW_PAPER | BATTERY_LOW | NETWORK_LOST
			tenant_id:          Tenant scope UUID.
			session:            SQLAlchemy session.
			detail:             Optional event-specific payload dict.

		Returns:
			Newly created TerminalHealthEvent.
		"""
		terminal = _resolve_terminal(terminal_id_or_tid, tenant_id, session)
		now = _now()

		health_event = TerminalHealthEvent(
			tenant_id=tenant_id,
			terminal_id=terminal.id,
			event_type=event_type,
			detail=detail,
			occurred_at=now,
		)
		session.add(health_event)

		if event_type == "TAMPER_ALERT":
			terminal.status = "TAMPERED"
			terminal.updated_at = now
			session.flush()
			_emit(TerminalTamperEvent(
				aggregate_type="Terminal",
				aggregate_id=terminal.id,
				tenant_id=tenant_id,
				terminal_db_id=terminal.id,
				terminal_id=terminal.terminal_id,
				detail=detail or {},
				occurred_at=now.isoformat(),
			))
			log.warning(
				"TAMPER ALERT — terminal suspended: tid=%r db_id=%r",
				terminal.terminal_id,
				terminal.id,
			)
		else:
			session.flush()

		log.info(
			"Health event recorded: tid=%r type=%r",
			terminal.terminal_id,
			event_type,
		)
		return health_event

	# ------------------------------------------------------------------
	# Heartbeat
	# ------------------------------------------------------------------

	def record_heartbeat(
		self,
		terminal_id_or_tid: str,
		tenant_id: str,
		session: Any,
	) -> None:
		"""Update terminal.last_heartbeat_at to now via a targeted UPDATE.

		Uses sa.update() to avoid loading the full Terminal object for this
		high-frequency operation.

		Args:
			terminal_id_or_tid: DB UUID or 8-char TID.
			tenant_id:          Tenant scope UUID.
			session:            SQLAlchemy session.
		"""
		terminal = _resolve_terminal(terminal_id_or_tid, tenant_id, session)
		now = _now()
		session.execute(
			sa.update(Terminal)
			.where(Terminal.id == terminal.id)
			.values(last_heartbeat_at=now, updated_at=now)
		)

	# ------------------------------------------------------------------
	# Compliance status
	# ------------------------------------------------------------------

	def get_compliance_status(
		self,
		terminal_db_id: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Return a compliance summary for the terminal.

		Returns:
			dict with keys:
			  terminal_id       — 8-char TID
			  has_active_keys   — bool
			  key_types_present — list of active key types
			  params_deployed   — bool
			  pci_dss_compliant — bool
			  last_heartbeat    — ISO datetime string or None
		"""
		terminal = session.execute(
			select(Terminal).where(
				Terminal.id == terminal_db_id,
				Terminal.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not terminal:
			raise TerminalNotFoundError(
				f"Terminal not found: {terminal_db_id!r} (tenant={tenant_id!r})"
			)

		active_keys = session.execute(
			select(TerminalKey.key_type).where(
				TerminalKey.terminal_id == terminal_db_id,
				TerminalKey.is_active == sa.true(),
			)
		).scalars().all()

		deployed_count = session.execute(
			select(sa.func.count(TerminalParameter.id)).where(
				TerminalParameter.terminal_id == terminal_db_id,
				TerminalParameter.status == "DEPLOYED",
			)
		).scalar_one()

		return {
			"terminal_id": terminal.terminal_id,
			"has_active_keys": len(active_keys) > 0,
			"key_types_present": list(active_keys),
			"params_deployed": deployed_count > 0,
			"pci_dss_compliant": terminal.pci_dss_compliant,
			"last_heartbeat": (
				terminal.last_heartbeat_at.isoformat()
				if terminal.last_heartbeat_at else None
			),
		}

	# ------------------------------------------------------------------
	# Batch management
	# ------------------------------------------------------------------

	def open_batch(
		self,
		terminal_db_id: str,
		tenant_id: str,
		session: Any,
	) -> TerminalBatch:
		"""Open a new settlement batch for the terminal.

		Args:
			terminal_db_id: Terminal DB UUID.
			tenant_id:      Tenant scope UUID.
			session:        SQLAlchemy session.

		Returns:
			Newly created TerminalBatch (status=OPEN).

		Raises:
			BatchError: if the terminal already has an OPEN batch.
		"""
		# Guard: no existing OPEN batch
		existing = session.execute(
			select(TerminalBatch).where(
				TerminalBatch.terminal_id == terminal_db_id,
				TerminalBatch.status == "OPEN",
			)
		).scalar_one_or_none()
		if existing:
			raise BatchError(
				f"Terminal {terminal_db_id!r} already has an OPEN batch "
				f"(batch_id={existing.id!r}, batch_number={existing.batch_number!r})"
			)

		max_batch = session.execute(
			select(
				sa.func.coalesce(sa.func.max(TerminalBatch.batch_number), 0)
			).where(TerminalBatch.terminal_id == terminal_db_id)
		).scalar_one()

		batch = TerminalBatch(
			tenant_id=tenant_id,
			terminal_id=terminal_db_id,
			batch_number=max_batch + 1,
			transaction_count=0,
			total_sales_cents=0,
			total_refunds_cents=0,
			opened_at=_now(),
			status="OPEN",
		)
		session.add(batch)
		session.flush()
		log.info(
			"Batch opened: terminal_db_id=%r batch_number=%r",
			terminal_db_id,
			batch.batch_number,
		)
		return batch

	def close_batch(
		self,
		batch_id: str,
		tenant_id: str,
		session: Any,
	) -> TerminalBatch:
		"""Close an open settlement batch.

		Args:
			batch_id:   TerminalBatch DB UUID.
			tenant_id:  Tenant scope UUID.
			session:    SQLAlchemy session.

		Returns:
			Updated TerminalBatch (status=CLOSED, closed_at set).

		Raises:
			BatchError: if the batch is not in OPEN status.
		"""
		batch = session.execute(
			select(TerminalBatch).where(
				TerminalBatch.id == batch_id,
				TerminalBatch.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not batch:
			raise BatchError(f"Batch not found: {batch_id!r}")
		if batch.status != "OPEN":
			raise BatchError(
				f"Batch {batch_id!r} is not OPEN (current: {batch.status!r})"
			)

		now = _now()
		batch.closed_at = now
		batch.status = "CLOSED"
		session.flush()

		terminal = session.get(Terminal, batch.terminal_id)
		tid = terminal.terminal_id if terminal else str(batch.terminal_id)

		_emit(BatchClosedEvent(
			aggregate_type="TerminalBatch",
			aggregate_id=batch.id,
			tenant_id=tenant_id,
			batch_id=batch.id,
			terminal_db_id=str(batch.terminal_id),
			terminal_id=tid,
			batch_number=batch.batch_number,
			transaction_count=batch.transaction_count,
			total_sales_cents=batch.total_sales_cents,
			total_refunds_cents=batch.total_refunds_cents,
			closed_at=now.isoformat(),
		))
		log.info(
			"Batch closed: batch_id=%r terminal=%r batch_number=%r txn_count=%r",
			batch_id,
			tid,
			batch.batch_number,
			batch.transaction_count,
		)
		return batch

	# ------------------------------------------------------------------
	# Decommission
	# ------------------------------------------------------------------

	def decommission(
		self,
		terminal_db_id: str,
		reason: str,
		tenant_id: str,
		session: Any,
	) -> Terminal:
		"""Permanently decommission a terminal.

		Sets status=DECOMMISSIONED regardless of current status.

		Args:
			terminal_db_id: Terminal DB UUID.
			reason:         Human-readable decommission reason (stored in updated audit).
			tenant_id:      Tenant scope UUID.
			session:        SQLAlchemy session.

		Returns:
			Updated Terminal (status=DECOMMISSIONED).
		"""
		terminal = session.execute(
			select(Terminal).where(
				Terminal.id == terminal_db_id,
				Terminal.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not terminal:
			raise TerminalNotFoundError(
				f"Terminal not found: {terminal_db_id!r} (tenant={tenant_id!r})"
			)

		terminal.status = "DECOMMISSIONED"
		terminal.updated_at = _now()
		session.flush()

		log.info(
			"Terminal decommissioned: tid=%r db_id=%r reason=%r",
			terminal.terminal_id,
			terminal_db_id,
			reason,
		)
		return terminal


# ---------------------------------------------------------------------------
# Register BPM processes at module load
# ---------------------------------------------------------------------------

_register_bpm()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"TerminalManagementService",
	"TerminalManagementError",
	"TerminalNotFoundError",
	"TerminalStateError",
	"TerminalValidationError",
	"BatchError",
]
