"""
pgappforge/plugins/fintech/core_banking/teller.py

Teller Operations — cash management at branch level.

Models
------
  TellerVault       — branch cash vault (consolidated holding)
  TellerSession     — individual teller's daily working session
  TellerTransaction — every cash movement in/out of a teller box

Workflow
--------
  1. open_session()     : teller signs in, draws opening float from vault
  2. cash_deposit()     : customer hands teller cash → credited to customer account
  3. cash_withdrawal()  : customer withdraws → teller pays out
  4. vault_deposit()    : teller excess cash → vault (between-session rebalancing)
  5. vault_withdrawal() : teller draws more cash from vault mid-session
  6. close_session()    : teller hands back remaining cash; variance recorded

NOTE: Alembic migration required for cb_teller_vault, cb_teller_session,
cb_teller_transaction tables.  Run::

    flask db migrate -m "add teller tables"
    flask db upgrade
"""
from __future__ import annotations

import logging
import uuid
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
)
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# TellerVault — branch cash vault
# ---------------------------------------------------------------------------

class TellerVault(AuditMixin, Model):
	"""Branch cash vault — consolidated holding for a branch.

	Multiple TellerSessions draw from / deposit to the same vault.
	current_balance_cents is the authoritative vault balance; it must be
	kept in sync by TellerService (never modified directly).
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_teller_vault"
	__table_args__ = (
		Index("ix_cb_vault_branch", "branch_code"),
		Index("ix_cb_vault_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		String(36),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()::text"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	branch_code = Column(String(20), nullable=False, index=True)
	name = Column(String(100), nullable=False)
	current_balance_cents = Column(Integer, nullable=False, default=0)
	currency_code = Column(String(3), nullable=False, default="KES")
	is_active = Column(Boolean, nullable=False, default=True)
	gl_account = Column(
		String(50),
		nullable=True,
		comment="GL chart-of-accounts code for this vault (e.g. 1010-BRANCH-001)",
	)

	# Timestamps
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		onupdate=_now,
		server_default=sa.text("NOW()"),
	)

	# Relationships
	sessions: list[TellerSession] = relationship(
		"TellerSession",
		back_populates="vault",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<TellerVault branch={self.branch_code!r} "
			f"balance={self.current_balance_cents}c>"
		)


# ---------------------------------------------------------------------------
# TellerSession — one per teller per working day
# ---------------------------------------------------------------------------

class TellerSession(AuditMixin, Model):
	"""A teller's working session from sign-in to session close.

	status flow: OPEN → CLOSED (then assessed as BALANCED or UNBALANCED)

	variance_cents = closing_balance_counted_cents - closing_balance_computed_cents
	A non-zero variance triggers UNBALANCED status and an alert to branch ops.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_teller_session"
	__table_args__ = (
		Index("ix_cb_tsession_teller", "teller_id"),
		Index("ix_cb_tsession_vault", "vault_id"),
		Index("ix_cb_tsession_branch", "branch_code"),
		Index("ix_cb_tsession_status", "status"),
		Index("ix_cb_tsession_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		String(36),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()::text"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	teller_id = Column(
		String(36),
		nullable=False,
		index=True,
		comment="Soft FK to HCM employee / user ID",
	)
	vault_id = Column(
		String(36),
		ForeignKey("cb_teller_vault.id"),
		nullable=False,
		index=True,
	)
	branch_code = Column(String(20), nullable=False)
	opened_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
	)
	closed_at = Column(DateTime(timezone=True), nullable=True)
	opening_balance_cents = Column(Integer, nullable=False)
	closing_balance_counted_cents = Column(
		Integer,
		nullable=True,
		comment="Physical cash counted by teller at session close",
	)
	closing_balance_computed_cents = Column(
		Integer,
		nullable=True,
		comment="System-computed expected balance at close",
	)
	variance_cents = Column(
		Integer,
		nullable=True,
		comment="counted - computed; 0 = balanced",
	)
	status = Column(
		String(12),
		nullable=False,
		default="OPEN",
		comment="OPEN | CLOSED | BALANCED | UNBALANCED",
	)

	# Timestamps
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		onupdate=_now,
		server_default=sa.text("NOW()"),
	)

	# Relationships
	vault: TellerVault = relationship(
		"TellerVault",
		back_populates="sessions",
		lazy="select",
	)
	transactions: list[TellerTransaction] = relationship(
		"TellerTransaction",
		back_populates="session",
		lazy="select",
		order_by="TellerTransaction.created_at",
	)

	def __repr__(self) -> str:
		return (
			f"<TellerSession teller={self.teller_id!r} "
			f"status={self.status!r} "
			f"opened={self.opened_at!r}>"
		)


# ---------------------------------------------------------------------------
# TellerTransaction — every cash movement
# ---------------------------------------------------------------------------

class TellerTransaction(AuditMixin, Model):
	"""Granular record of every cash movement within a teller session.

	transaction_type:
	  CASH_DEPOSIT      — customer deposits cash; teller box increases
	  CASH_WITHDRAWAL   — customer withdraws cash; teller box decreases
	  VAULT_DEPOSIT     — teller deposits surplus to vault; box decreases
	  VAULT_WITHDRAWAL  — teller draws from vault to replenish box; box increases
	  INTER_TELLER      — cash transfer between tellers (future use)
	  ADJUSTMENT        — manual override by branch ops / supervisor

	running_balance_cents is the teller box balance AFTER this transaction.
	gl_journal_id links to the LedgerEntry journal posted to the customer account.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_teller_transaction"
	__table_args__ = (
		Index("ix_cb_ttxn_session", "session_id"),
		Index("ix_cb_ttxn_account", "account_number"),
		Index("ix_cb_ttxn_reference", "reference"),
		Index("ix_cb_ttxn_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		String(36),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()::text"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	session_id = Column(
		String(36),
		ForeignKey("cb_teller_session.id"),
		nullable=False,
		index=True,
	)
	transaction_type = Column(
		String(20),
		nullable=False,
		comment=(
			"CASH_DEPOSIT | CASH_WITHDRAWAL | VAULT_DEPOSIT | "
			"VAULT_WITHDRAWAL | INTER_TELLER | ADJUSTMENT"
		),
	)
	account_number = Column(
		String(30),
		nullable=True,
		comment="Customer account number (NULL for vault movements)",
	)
	amount_cents = Column(Integer, nullable=False)
	running_balance_cents = Column(
		Integer,
		nullable=False,
		comment="Teller box balance after this transaction",
	)
	reference = Column(String(50), nullable=False)
	channel = Column(String(20), nullable=False, default="TELLER")
	gl_journal_id = Column(
		String(50),
		nullable=True,
		comment="LedgerEntry journal_id posted to the customer account",
	)

	# Timestamp (insert-only; teller transactions should not be updated)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		server_default=sa.text("NOW()"),
	)

	# Relationships
	session: TellerSession = relationship(
		"TellerSession",
		back_populates="transactions",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<TellerTransaction {self.transaction_type!r} "
			f"amount={self.amount_cents}c "
			f"running={self.running_balance_cents}c>"
		)


# ---------------------------------------------------------------------------
# TellerService
# ---------------------------------------------------------------------------

class TellerService:
	"""Teller operations: session lifecycle, cash deposits/withdrawals, vault movements.

	All methods accept an explicit SQLAlchemy *session*; the caller controls
	commit/rollback.  The service never commits.

	CoreBankingService is imported lazily (try/except ImportError) so this
	module can be used independently of the full core banking stack in tests.

	Usage::

		svc = TellerService()
		ts = svc.open_session(teller_id, vault_id, 50_000_00, tenant_id, session)
		result = svc.cash_deposit(ts.id, "20260601-NBI001-00000001", 5_000_00, "REF001", tenant_id, session)
		svc.close_session(ts.id, 45_000_00, tenant_id, session)
	"""

	# ------------------------------------------------------------------
	# Session lifecycle
	# ------------------------------------------------------------------

	def open_session(
		self,
		teller_id: str,
		vault_id: str,
		opening_balance_cents: int,
		tenant_id: str,
		session: Any,
	) -> TellerSession:
		"""Open a new teller session.

		Validates no existing OPEN session for this teller exists.
		Draws opening_balance_cents from the vault.

		Raises ValueError if teller already has an open session or the vault
		has insufficient funds.
		"""
		# Guard: no duplicate open sessions
		existing = session.execute(
			sa.select(TellerSession).where(
				TellerSession.teller_id == teller_id,
				TellerSession.tenant_id == tenant_id,
				TellerSession.status == "OPEN",
			)
		).scalar_one_or_none()
		if existing is not None:
			raise ValueError(
				f"Teller {teller_id!r} already has an open session {existing.id!r}. "
				"Close it before opening a new one."
			)

		# Validate vault
		vault = session.execute(
			sa.select(TellerVault).where(
				TellerVault.id == vault_id,
				TellerVault.tenant_id == tenant_id,
				TellerVault.is_active.is_(True),
			)
		).scalar_one_or_none()
		if vault is None:
			raise ValueError(f"TellerVault {vault_id!r} not found or inactive for tenant {tenant_id!r}")
		if vault.current_balance_cents < opening_balance_cents:
			raise ValueError(
				f"Vault {vault_id!r} has insufficient funds "
				f"({vault.current_balance_cents}c available, {opening_balance_cents}c requested)"
			)

		# Create session
		ts = TellerSession(
			tenant_id=tenant_id,
			teller_id=teller_id,
			vault_id=vault_id,
			branch_code=vault.branch_code,
			opened_at=_now(),
			opening_balance_cents=opening_balance_cents,
			status="OPEN",
		)
		session.add(ts)
		session.flush()

		# Deduct from vault
		vault.current_balance_cents -= opening_balance_cents

		# Record the vault withdrawal
		session.add(TellerTransaction(
			tenant_id=tenant_id,
			session_id=ts.id,
			transaction_type="VAULT_WITHDRAWAL",
			amount_cents=opening_balance_cents,
			running_balance_cents=opening_balance_cents,
			reference=f"OPEN-{ts.id[:8]}",
			channel="TELLER",
		))
		session.flush()
		log.info(
			"TellerService.open_session: session %s opened for teller %s, float=%dc",
			ts.id, teller_id, opening_balance_cents,
		)
		return ts

	# ------------------------------------------------------------------
	# Customer cash deposit
	# ------------------------------------------------------------------

	def cash_deposit(
		self,
		teller_session_id: str,
		account_number: str,
		amount_cents: int,
		reference: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Accept cash from customer and credit their account.

		Returns::

			{
			    "account_number": str,
			    "new_balance_cents": int,
			    "teller_balance_cents": int,
			    "gl_journal_id": str,
			}
		"""
		ts = self._get_open_session(teller_session_id, tenant_id, session)
		teller_balance = self.get_teller_balance(teller_session_id, tenant_id, session)

		# Post to customer account via CoreBankingService
		gl_journal_id: str | None = None
		new_balance: int = 0
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			cb_svc = CoreBankingService()
			account, entry = cb_svc.deposit(
				session=session,
				account_number=account_number,
				amount_cents=amount_cents,
				channel="TELLER",
				reference=reference,
				narrative=f"Cash deposit via teller session {teller_session_id[:8]}",
				tenant_id=tenant_id,
			)
			gl_journal_id = entry.journal_id
			new_balance = account.current_balance_cents
		except ImportError:
			# Standalone mode — just track teller-side movements
			log.warning(
				"TellerService.cash_deposit: CoreBankingService unavailable; "
				"teller-side recorded only for account %s",
				account_number,
			)

		new_teller_balance = teller_balance + amount_cents

		session.add(TellerTransaction(
			tenant_id=tenant_id,
			session_id=ts.id,
			transaction_type="CASH_DEPOSIT",
			account_number=account_number,
			amount_cents=amount_cents,
			running_balance_cents=new_teller_balance,
			reference=reference,
			channel="TELLER",
			gl_journal_id=gl_journal_id,
		))
		session.flush()
		log.info(
			"TellerService.cash_deposit: %dc → account %s (teller balance now %dc)",
			amount_cents, account_number, new_teller_balance,
		)
		return {
			"account_number": account_number,
			"new_balance_cents": new_balance,
			"teller_balance_cents": new_teller_balance,
			"gl_journal_id": gl_journal_id,
		}

	# ------------------------------------------------------------------
	# Customer cash withdrawal
	# ------------------------------------------------------------------

	def cash_withdrawal(
		self,
		teller_session_id: str,
		account_number: str,
		amount_cents: int,
		reference: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Pay out cash to customer by debiting their account.

		Validates the teller has sufficient cash before proceeding.

		Returns::

			{
			    "account_number": str,
			    "new_balance_cents": int,
			    "teller_balance_cents": int,
			    "gl_journal_id": str,
			}
		"""
		ts = self._get_open_session(teller_session_id, tenant_id, session)  # noqa: F841
		teller_balance = self.get_teller_balance(teller_session_id, tenant_id, session)

		if teller_balance < amount_cents:
			raise ValueError(
				f"Teller session {teller_session_id!r} has insufficient cash "
				f"({teller_balance}c available, {amount_cents}c requested). "
				"Request a vault withdrawal first."
			)

		gl_journal_id: str | None = None
		new_balance: int = 0
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			cb_svc = CoreBankingService()
			account, entry = cb_svc.withdraw(
				session=session,
				account_number=account_number,
				amount_cents=amount_cents,
				channel="TELLER",
				reference=reference,
				narrative=f"Cash withdrawal via teller session {teller_session_id[:8]}",
				tenant_id=tenant_id,
			)
			gl_journal_id = entry.journal_id
			new_balance = account.current_balance_cents
		except ImportError:
			log.warning(
				"TellerService.cash_withdrawal: CoreBankingService unavailable; "
				"teller-side recorded only for account %s",
				account_number,
			)

		new_teller_balance = teller_balance - amount_cents

		session.add(TellerTransaction(
			tenant_id=tenant_id,
			session_id=teller_session_id,
			transaction_type="CASH_WITHDRAWAL",
			account_number=account_number,
			amount_cents=amount_cents,
			running_balance_cents=new_teller_balance,
			reference=reference,
			channel="TELLER",
			gl_journal_id=gl_journal_id,
		))
		session.flush()
		log.info(
			"TellerService.cash_withdrawal: %dc from account %s (teller balance now %dc)",
			amount_cents, account_number, new_teller_balance,
		)
		return {
			"account_number": account_number,
			"new_balance_cents": new_balance,
			"teller_balance_cents": new_teller_balance,
			"gl_journal_id": gl_journal_id,
		}

	# ------------------------------------------------------------------
	# Vault movements
	# ------------------------------------------------------------------

	def vault_deposit(
		self,
		teller_session_id: str,
		amount_cents: int,
		tenant_id: str,
		session: Any,
	) -> TellerTransaction:
		"""Teller deposits surplus cash to the branch vault.

		Reduces teller box balance, increases vault balance.
		Used when teller accumulates excess cash mid-session.
		"""
		ts = self._get_open_session(teller_session_id, tenant_id, session)
		teller_balance = self.get_teller_balance(teller_session_id, tenant_id, session)

		if teller_balance < amount_cents:
			raise ValueError(
				f"Teller session {teller_session_id!r} has only {teller_balance}c; "
				f"cannot deposit {amount_cents}c to vault."
			)

		vault = session.execute(
			sa.select(TellerVault).where(TellerVault.id == ts.vault_id)
		).scalar_one()
		vault.current_balance_cents += amount_cents

		new_teller_balance = teller_balance - amount_cents
		txn = TellerTransaction(
			tenant_id=tenant_id,
			session_id=teller_session_id,
			transaction_type="VAULT_DEPOSIT",
			amount_cents=amount_cents,
			running_balance_cents=new_teller_balance,
			reference=f"VDEP-{teller_session_id[:8]}-{_uuid4()[:4]}",
			channel="TELLER",
		)
		session.add(txn)
		session.flush()
		log.info(
			"TellerService.vault_deposit: %dc from session %s → vault %s",
			amount_cents, teller_session_id, ts.vault_id,
		)
		return txn

	def vault_withdrawal(
		self,
		teller_session_id: str,
		amount_cents: int,
		tenant_id: str,
		session: Any,
	) -> TellerTransaction:
		"""Teller draws additional cash from vault to replenish box.

		Increases teller box balance, reduces vault balance.
		Raises ValueError if vault has insufficient funds.
		"""
		ts = self._get_open_session(teller_session_id, tenant_id, session)
		teller_balance = self.get_teller_balance(teller_session_id, tenant_id, session)

		vault = session.execute(
			sa.select(TellerVault).where(TellerVault.id == ts.vault_id)
		).scalar_one()

		if vault.current_balance_cents < amount_cents:
			raise ValueError(
				f"Vault {ts.vault_id!r} has insufficient funds "
				f"({vault.current_balance_cents}c available, {amount_cents}c requested)"
			)

		vault.current_balance_cents -= amount_cents
		new_teller_balance = teller_balance + amount_cents

		txn = TellerTransaction(
			tenant_id=tenant_id,
			session_id=teller_session_id,
			transaction_type="VAULT_WITHDRAWAL",
			amount_cents=amount_cents,
			running_balance_cents=new_teller_balance,
			reference=f"VWDL-{teller_session_id[:8]}-{_uuid4()[:4]}",
			channel="TELLER",
		)
		session.add(txn)
		session.flush()
		log.info(
			"TellerService.vault_withdrawal: %dc from vault %s → session %s",
			amount_cents, ts.vault_id, teller_session_id,
		)
		return txn

	# ------------------------------------------------------------------
	# Session close
	# ------------------------------------------------------------------

	def close_session(
		self,
		teller_session_id: str,
		counted_balance_cents: int,
		tenant_id: str,
		session: Any,
	) -> TellerSession:
		"""Close the teller session and reconcile cash.

		Computes the expected balance from all transactions, records
		the physical count, and marks the session BALANCED or UNBALANCED.
		Remaining cash (computed balance) is deposited back to the vault.

		Returns the updated TellerSession.
		"""
		ts = self._get_open_session(teller_session_id, tenant_id, session)
		computed_balance = self.get_teller_balance(teller_session_id, tenant_id, session)

		variance = counted_balance_cents - computed_balance

		ts.closing_balance_counted_cents = counted_balance_cents
		ts.closing_balance_computed_cents = computed_balance
		ts.variance_cents = variance
		ts.closed_at = _now()
		ts.status = "BALANCED" if variance == 0 else "UNBALANCED"

		# Return computed (system-expected) cash to vault
		if computed_balance > 0:
			vault = session.execute(
				sa.select(TellerVault).where(TellerVault.id == ts.vault_id)
			).scalar_one()
			vault.current_balance_cents += computed_balance

			session.add(TellerTransaction(
				tenant_id=tenant_id,
				session_id=teller_session_id,
				transaction_type="VAULT_DEPOSIT",
				amount_cents=computed_balance,
				running_balance_cents=0,
				reference=f"CLOSE-{teller_session_id[:8]}",
				channel="TELLER",
			))

		session.flush()
		log.info(
			"TellerService.close_session: session %s closed, status=%s, variance=%dc",
			teller_session_id, ts.status, variance,
		)
		return ts

	# ------------------------------------------------------------------
	# Balance query
	# ------------------------------------------------------------------

	def get_teller_balance(
		self,
		teller_session_id: str,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Compute current teller box balance from transaction history.

		Formula:
		  opening_balance
		  + SUM(CASH_DEPOSIT amounts)
		  - SUM(CASH_WITHDRAWAL amounts)
		  - SUM(VAULT_DEPOSIT amounts)
		  + SUM(VAULT_WITHDRAWAL amounts)
		"""
		ts = session.execute(
			sa.select(TellerSession).where(
				TellerSession.id == teller_session_id,
				TellerSession.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if ts is None:
			raise ValueError(f"TellerSession {teller_session_id!r} not found")

		rows = session.execute(
			sa.select(
				TellerTransaction.transaction_type,
				sa.func.sum(TellerTransaction.amount_cents).label("total"),
			).where(
				TellerTransaction.session_id == teller_session_id,
				TellerTransaction.tenant_id == tenant_id,
			).group_by(TellerTransaction.transaction_type)
		).all()

		totals: dict[str, int] = {row.transaction_type: (row.total or 0) for row in rows}

		balance = (
			ts.opening_balance_cents
			+ totals.get("CASH_DEPOSIT", 0)
			- totals.get("CASH_WITHDRAWAL", 0)
			- totals.get("VAULT_DEPOSIT", 0)
			+ totals.get("VAULT_WITHDRAWAL", 0)
		)
		# Subtract the opening VAULT_WITHDRAWAL which was already included in opening_balance_cents
		# via open_session() — avoid double-counting
		# (opening balance IS the first VAULT_WITHDRAWAL; subsequent ones are replenishments)
		# Adjust: only count VAULT_WITHDRAWAL txns AFTER the opening one
		first_vault_wdl = session.execute(
			sa.select(TellerTransaction).where(
				TellerTransaction.session_id == teller_session_id,
				TellerTransaction.transaction_type == "VAULT_WITHDRAWAL",
			).order_by(TellerTransaction.created_at).limit(1)
		).scalar_one_or_none()

		if first_vault_wdl is not None:
			# Deduct the opening draw (already baked into opening_balance_cents)
			balance -= first_vault_wdl.amount_cents

		return balance

	# ------------------------------------------------------------------
	# Session summary
	# ------------------------------------------------------------------

	def get_session_summary(
		self,
		teller_session_id: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return a summary dict for a teller session.

		Shape::

			{
			    "session_id": str,
			    "teller_id": str,
			    "branch_code": str,
			    "opened_at": str (ISO),
			    "closed_at": str|None,
			    "status": str,
			    "opening_balance_cents": int,
			    "total_cash_deposits_cents": int,
			    "total_cash_withdrawals_cents": int,
			    "total_vault_deposits_cents": int,
			    "total_vault_withdrawals_cents": int,
			    "current_balance_cents": int,
			    "closing_balance_counted_cents": int|None,
			    "variance_cents": int|None,
			    "transaction_count": int,
			}
		"""
		ts = session.execute(
			sa.select(TellerSession).where(
				TellerSession.id == teller_session_id,
				TellerSession.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if ts is None:
			raise ValueError(f"TellerSession {teller_session_id!r} not found")

		rows = session.execute(
			sa.select(
				TellerTransaction.transaction_type,
				sa.func.sum(TellerTransaction.amount_cents).label("total"),
				sa.func.count().label("count"),
			).where(
				TellerTransaction.session_id == teller_session_id,
				TellerTransaction.tenant_id == tenant_id,
			).group_by(TellerTransaction.transaction_type)
		).all()

		totals: dict[str, int] = {}
		counts: dict[str, int] = {}
		for row in rows:
			totals[row.transaction_type] = row.total or 0
			counts[row.transaction_type] = row.count or 0

		current_balance = (
			ts.closing_balance_computed_cents
			if ts.status != "OPEN"
			else self.get_teller_balance(teller_session_id, tenant_id, session)
		)

		return {
			"session_id": ts.id,
			"teller_id": ts.teller_id,
			"branch_code": ts.branch_code,
			"opened_at": ts.opened_at.isoformat() if ts.opened_at else None,
			"closed_at": ts.closed_at.isoformat() if ts.closed_at else None,
			"status": ts.status,
			"opening_balance_cents": ts.opening_balance_cents,
			"total_cash_deposits_cents": totals.get("CASH_DEPOSIT", 0),
			"total_cash_withdrawals_cents": totals.get("CASH_WITHDRAWAL", 0),
			"total_vault_deposits_cents": totals.get("VAULT_DEPOSIT", 0),
			"total_vault_withdrawals_cents": totals.get("VAULT_WITHDRAWAL", 0),
			"current_balance_cents": current_balance,
			"closing_balance_counted_cents": ts.closing_balance_counted_cents,
			"variance_cents": ts.variance_cents,
			"transaction_count": sum(counts.values()),
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _get_open_session(
		self,
		teller_session_id: str,
		tenant_id: str,
		session: Any,
	) -> TellerSession:
		"""Fetch and validate an OPEN TellerSession; raise ValueError if not found or closed."""
		ts = session.execute(
			sa.select(TellerSession).where(
				TellerSession.id == teller_session_id,
				TellerSession.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if ts is None:
			raise ValueError(f"TellerSession {teller_session_id!r} not found")
		if ts.status != "OPEN":
			raise ValueError(
				f"TellerSession {teller_session_id!r} is not OPEN (status={ts.status!r})"
			)
		return ts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = ["TellerService", "TellerVault", "TellerSession", "TellerTransaction"]
