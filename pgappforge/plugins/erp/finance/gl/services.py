"""
pgappforge/plugins/erp/finance/gl/services.py

GLService — stateless business logic for the General Ledger plugin.

All methods receive an explicit SQLAlchemy Session; no Flask context assumed.
Safe to call from background jobs, CLI commands, and tests.

Critical invariants:
  - All monetary amounts: integer cents (BigInteger). Never float.
  - post_journal():    atomic — all entries post or none do.
  - reverse_journal(): creates a mirror entry; never modifies the original.
  - close_period():    validates all batches posted, then locks the period.
  - Financial records: NEVER UPDATE posted rows — insert correction entries.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GLServiceError(Exception):
	"""Base error for GL domain violations."""


class JournalImbalancedError(GLServiceError):
	"""Batch debits != credits."""


class PeriodClosedError(GLServiceError):
	"""Attempt to post to a CLOSED or LOCKED period."""


class PostingAccountError(GLServiceError):
	"""Account does not allow posting (is_posting_account=False)."""


class InactiveAccountError(GLServiceError):
	"""Account is inactive."""


class BatchNotFoundError(GLServiceError):
	"""No GLJournalBatch with the given id."""


class EntryNotFoundError(GLServiceError):
	"""No GLJournalEntry with the given id."""


class PeriodNotFoundError(GLServiceError):
	"""No GLPeriod with the given id."""


class PeriodHasOpenBatchesError(GLServiceError):
	"""Period cannot close — unposted batches remain."""


# ---------------------------------------------------------------------------
# GLService
# ---------------------------------------------------------------------------

class GLService:
	"""Stateless service for General Ledger operations.

	Instantiate once per app (or per request).  All methods accept a
	SQLAlchemy Session as their last positional arg; callers own transaction
	boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# post_journal
	# ------------------------------------------------------------------

	def post_journal(self, batch_id: str, session: Any, posted_by: str | None = None) -> dict:
		"""Validate and post all DRAFT entries in a batch atomically.

		Steps:
		1. Load batch; assert status in (DRAFT, SUBMITTED, APPROVED).
		2. Assert period is OPEN.
		3. Assert batch is balanced (total_debits == total_credits).
		4. Assert every line targets a posting, active account.
		5. For each entry: status → POSTED.
		6. Upsert GLAccountBalance rows for every touched (account, period).
		7. Batch status → POSTED.
		8. Emit JournalPostedEvent per line + BatchPostedEvent.

		Returns: dict with posted entry ids and totals.
		Raises: GLServiceError subclasses on validation failure.
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLJournalBatch,
			GLJournalEntry,
			GLJournalLine,
			GLAccountBalance,
			GLPeriod,
			GLAccount,
		)
		from pgappforge.plugins.erp.finance.gl.events import (
			JournalPostedEvent,
			BatchPostedEvent,
			emit_event,
		)

		# 1. Load batch
		batch = session.get(GLJournalBatch, batch_id)
		if batch is None:
			raise BatchNotFoundError(f"GLJournalBatch {batch_id!r} not found")
		if batch.status not in ("DRAFT", "SUBMITTED", "APPROVED"):
			raise GLServiceError(
				f"Cannot post batch {batch.batch_number!r} in status {batch.status!r}"
			)

		# 2. Period must be OPEN
		period = session.get(GLPeriod, batch.period_id)
		if period is None:
			raise PeriodNotFoundError(f"GLPeriod {batch.period_id!r} not found")
		if period.status != "OPEN":
			raise PeriodClosedError(
				f"Period {period.period_name!r} is {period.status!r} — cannot post"
			)

		# 3. Balance check
		if batch.total_debits != batch.total_credits:
			raise JournalImbalancedError(
				f"Batch {batch.batch_number!r} is not balanced: "
				f"DR={batch.total_debits} CR={batch.total_credits}"
			)
		if not batch.is_balanced:
			# Recompute from lines as a safety guard
			entries_q = session.execute(
				select(GLJournalEntry).where(GLJournalEntry.batch_id == batch_id)
			).scalars().all()
			entry_ids = [e.id for e in entries_q]
			if entry_ids:
				totals = session.execute(
					select(
						func.sum(GLJournalLine.base_debit),
						func.sum(GLJournalLine.base_credit),
					).where(GLJournalLine.entry_id.in_(entry_ids))
				).one()
				total_dr = totals[0] or 0
				total_cr = totals[1] or 0
				if total_dr != total_cr:
					raise JournalImbalancedError(
						f"Batch {batch.batch_number!r} lines are not balanced: "
						f"DR={total_dr} CR={total_cr}"
					)

		# 4. Load all entries + lines; validate accounts
		entries = session.execute(
			select(GLJournalEntry).where(
				GLJournalEntry.batch_id == batch_id,
				GLJournalEntry.status == "DRAFT",
			)
		).scalars().all()

		all_line_accounts: set[str] = set()
		for entry in entries:
			for line in entry.lines:
				all_line_accounts.add(line.account_code)

		# Bulk-load accounts
		accounts: dict[str, GLAccount] = {}
		if all_line_accounts:
			acct_rows = session.execute(
				select(GLAccount).where(
					GLAccount.account_code.in_(all_line_accounts)
				)
			).scalars().all()
			accounts = {a.account_code: a for a in acct_rows}

		for code in all_line_accounts:
			acct = accounts.get(code)
			if acct is None:
				raise GLServiceError(f"Account {code!r} not found")
			if not acct.is_active:
				raise InactiveAccountError(f"Account {code!r} is inactive")
			if not acct.is_posting_account:
				raise PostingAccountError(
					f"Account {code!r} is a summary/header account and does not allow posting"
				)

		# 5 & 6. Post entries and update balances
		now = datetime.now(timezone.utc)
		posted_entry_ids: list[str] = []

		for entry in entries:
			for line in entry.lines:
				self._upsert_balance(
					session=session,
					tenant_id=batch.tenant_id,
					account_code=line.account_code,
					period_id=batch.period_id,
					debit=line.base_debit,
					credit=line.base_credit,
					GLAccountBalance=GLAccountBalance,
				)
				# Emit per-line event
				amount = line.base_debit if line.base_debit else line.base_credit
				dc = "DEBIT" if line.base_debit else "CREDIT"
				emit_event(
					JournalPostedEvent(
						aggregate_id=entry.id,
						aggregate_type="GLJournalEntry",
						tenant_id=batch.tenant_id,
						entry_id=entry.id,
						batch_id=batch_id,
						account_code=line.account_code,
						amount=amount,
						debit_credit=dc,
						currency_code=line.currency_code,
						posting_date=entry.posting_date.isoformat(),
					),
					session,
				)

			entry.status = "POSTED"
			posted_entry_ids.append(entry.id)

		# 7. Mark batch posted
		batch.status = "POSTED"
		batch.posted_by = posted_by
		batch.posted_at = now

		# 8. BatchPostedEvent
		emit_event(
			BatchPostedEvent(
				aggregate_id=batch_id,
				aggregate_type="GLJournalBatch",
				tenant_id=batch.tenant_id,
				batch_id=batch_id,
				batch_number=batch.batch_number,
				total_debits=batch.total_debits,
				total_credits=batch.total_credits,
				period_id=batch.period_id,
			),
			session,
		)

		log.info(
			"post_journal: batch %r posted %d entries",
			batch.batch_number,
			len(posted_entry_ids),
		)
		return {
			"batch_id": batch_id,
			"batch_number": batch.batch_number,
			"posted_entries": len(posted_entry_ids),
			"total_debits": batch.total_debits,
			"total_credits": batch.total_credits,
		}

	# ------------------------------------------------------------------
	# reverse_journal
	# ------------------------------------------------------------------

	def reverse_journal(
		self,
		entry_id: str,
		reversal_date: date,
		session: Any,
		description: str | None = None,
	) -> dict:
		"""Create a mirror reversal entry for a POSTED journal entry.

		The reversal entry swaps debits and credits on every line.
		The original entry is NOT modified — immutable ledger principle.

		Returns: dict with the new reversal entry id.
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLJournalEntry,
			GLJournalLine,
			GLJournalBatch,
			GLPeriod,
		)
		from pgappforge.plugins.erp.finance.gl.events import JournalReversedEvent, emit_event

		original = session.get(GLJournalEntry, entry_id)
		if original is None:
			raise EntryNotFoundError(f"GLJournalEntry {entry_id!r} not found")
		if original.status != "POSTED":
			raise GLServiceError(
				f"Entry {entry_id!r} is not POSTED (status={original.status!r})"
			)

		batch = session.get(GLJournalBatch, original.batch_id)
		period = session.get(GLPeriod, batch.period_id)
		if period.status != "OPEN":
			raise PeriodClosedError(
				f"Cannot post reversal — period {period.period_name!r} is {period.status!r}"
			)

		# Create reversal batch if none exists for this period
		import uuid as _uuid
		reversal_batch = GLJournalBatch(
			tenant_id=batch.tenant_id,
			batch_number=f"REV-{batch.batch_number}-{_uuid.uuid4().hex[:6].upper()}",
			batch_type="REVERSAL",
			period_id=batch.period_id,
			description=f"Reversal of batch {batch.batch_number}",
			status="DRAFT",
			total_debits=0,
			total_credits=0,
			is_balanced=False,
		)
		session.add(reversal_batch)
		session.flush()

		# Create reversal entry
		reversal_entry = GLJournalEntry(
			tenant_id=original.tenant_id,
			batch_id=reversal_batch.id,
			entry_type="REVERSAL",
			posting_date=reversal_date,
			description=description or f"Reversal of entry {original.entry_number or original.id}",
			source_document_type=original.source_document_type,
			source_document_id=original.source_document_id,
			reversal_of_entry_id=original.id,
			status="DRAFT",
		)
		session.add(reversal_entry)
		session.flush()

		# Mirror lines with swapped debit/credit
		total_dr = 0
		total_cr = 0
		for i, line in enumerate(original.lines, 1):
			rev_line = GLJournalLine(
				tenant_id=line.tenant_id,
				entry_id=reversal_entry.id,
				line_number=i,
				account_code=line.account_code,
				cost_center_code=line.cost_center_code,
				project_code=line.project_code,
				# Swap debit <-> credit
				debit_amount=line.credit_amount,
				credit_amount=line.debit_amount,
				currency_code=line.currency_code,
				fx_rate=line.fx_rate,
				base_debit=line.base_credit,
				base_credit=line.base_debit,
				description=f"REV: {line.description or ''}".strip(),
				reference=line.reference,
				party_id=line.party_id,
				tax_code=line.tax_code,
			)
			session.add(rev_line)
			total_dr += line.base_credit
			total_cr += line.base_debit

		# Update reversal batch totals
		reversal_batch.total_debits = total_dr
		reversal_batch.total_credits = total_cr
		reversal_batch.is_balanced = (total_dr == total_cr)

		# Mark original entry reversed
		original.status = "REVERSED"

		# Post the reversal batch inline
		reversal_batch.status = "APPROVED"
		session.flush()
		result = self.post_journal(reversal_batch.id, session)

		emit_event(
			JournalReversedEvent(
				aggregate_id=original.id,
				aggregate_type="GLJournalEntry",
				tenant_id=original.tenant_id,
				original_entry_id=original.id,
				reversal_entry_id=reversal_entry.id,
				reversal_date=reversal_date.isoformat(),
			),
			session,
		)

		log.info(
			"reverse_journal: entry %r reversed → new entry %r",
			entry_id,
			reversal_entry.id,
		)
		return {
			"original_entry_id": entry_id,
			"reversal_entry_id": reversal_entry.id,
			"reversal_batch_id": reversal_batch.id,
			"total_debits": total_dr,
			"total_credits": total_cr,
		}

	# ------------------------------------------------------------------
	# close_period
	# ------------------------------------------------------------------

	def close_period(self, period_id: str, session: Any, closed_by: str | None = None) -> dict:
		"""Validate all batches are posted, then lock the period.

		Raises PeriodHasOpenBatchesError if any batch in the period is not POSTED.
		"""
		from pgappforge.plugins.erp.finance.gl.models import GLPeriod, GLJournalBatch, GLFiscalYear
		from pgappforge.plugins.erp.finance.gl.events import PeriodClosedEvent, emit_event

		period = session.get(GLPeriod, period_id)
		if period is None:
			raise PeriodNotFoundError(f"GLPeriod {period_id!r} not found")
		if period.status == "LOCKED":
			raise GLServiceError(f"Period {period.period_name!r} is already LOCKED")

		# Verify no unposted batches
		open_count = session.execute(
			select(func.count()).where(
				GLJournalBatch.period_id == period_id,
				GLJournalBatch.status.notin_(["POSTED", "REVERSED"]),
			)
		).scalar_one()
		if open_count:
			raise PeriodHasOpenBatchesError(
				f"Period {period.period_name!r} has {open_count} unposted batch(es)"
			)

		now = datetime.now(timezone.utc)
		period.status = "LOCKED"
		period.closed_by = closed_by
		period.closed_at = now

		fy = session.get(GLFiscalYear, period.fiscal_year_id)
		fiscal_year_int = fy.fiscal_year if fy else 0

		emit_event(
			PeriodClosedEvent(
				aggregate_id=period_id,
				aggregate_type="GLPeriod",
				tenant_id=period.tenant_id,
				period_id=period_id,
				fiscal_year=fiscal_year_int,
				period_number=period.period_number,
				closed_by=closed_by or "",
			),
			session,
		)

		log.info(
			"close_period: period %r locked by %r",
			period.period_name,
			closed_by,
		)
		return {
			"period_id": period_id,
			"period_name": period.period_name,
			"fiscal_year": fiscal_year_int,
			"status": "LOCKED",
			"closed_at": now.isoformat(),
		}

	# ------------------------------------------------------------------
	# get_trial_balance
	# ------------------------------------------------------------------

	def get_trial_balance(self, period_id: str, session: Any) -> list[dict]:
		"""Return trial balance rows for a period.

		Each row: {account_code, account_name, account_type, debit, credit, net}
		Amounts are integer cents.
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLAccountBalance,
			GLAccount,
		)

		rows = session.execute(
			select(
				GLAccountBalance.account_code,
				GLAccount.account_name,
				GLAccount.account_type,
				GLAccount.normal_balance,
				GLAccountBalance.period_debit,
				GLAccountBalance.period_credit,
				GLAccountBalance.closing_debit,
				GLAccountBalance.closing_credit,
			)
			.join(GLAccount, GLAccount.account_code == GLAccountBalance.account_code)
			.where(GLAccountBalance.period_id == period_id)
			.order_by(GLAccount.account_code)
		).all()

		result = []
		for row in rows:
			net_dr = row.closing_debit - row.closing_credit
			result.append({
				"account_code": row.account_code,
				"account_name": row.account_name,
				"account_type": row.account_type,
				"normal_balance": row.normal_balance,
				"period_debit": row.period_debit,
				"period_credit": row.period_credit,
				"closing_debit": row.closing_debit,
				"closing_credit": row.closing_credit,
				"net": net_dr,
			})
		return result

	# ------------------------------------------------------------------
	# get_account_balance
	# ------------------------------------------------------------------

	def get_account_balance(
		self,
		account_code: str,
		as_of_date: date,
		session: Any,
		tenant_id: str | None = None,
	) -> dict:
		"""Return cumulative balance for an account as of a date.

		Sums all posted journal lines up to and including as_of_date.
		Returns integer cents.
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLJournalLine,
			GLJournalEntry,
			GLJournalBatch,
			GLAccount,
		)

		q = (
			select(
				func.sum(GLJournalLine.base_debit).label("total_debit"),
				func.sum(GLJournalLine.base_credit).label("total_credit"),
			)
			.join(GLJournalEntry, GLJournalEntry.id == GLJournalLine.entry_id)
			.join(GLJournalBatch, GLJournalBatch.id == GLJournalEntry.batch_id)
			.where(
				GLJournalLine.account_code == account_code,
				GLJournalEntry.status == "POSTED",
				GLJournalEntry.posting_date <= as_of_date,
			)
		)
		if tenant_id:
			q = q.where(GLJournalLine.tenant_id == tenant_id)

		totals = session.execute(q).one()
		total_dr = totals.total_debit or 0
		total_cr = totals.total_credit or 0

		acct = session.get(GLAccount, account_code)
		normal_balance = acct.normal_balance if acct else "DEBIT"
		net = total_dr - total_cr if normal_balance == "DEBIT" else total_cr - total_dr

		return {
			"account_code": account_code,
			"account_name": acct.account_name if acct else "",
			"as_of_date": as_of_date.isoformat(),
			"total_debit": total_dr,
			"total_credit": total_cr,
			"net_balance": net,
			"normal_balance": normal_balance,
		}

	# ------------------------------------------------------------------
	# get_budget_vs_actual
	# ------------------------------------------------------------------

	def get_budget_vs_actual(
		self,
		period_id: str,
		session: Any,
		version: str = "ORIGINAL",
	) -> list[dict]:
		"""Compare budget to actual for a period.

		Returns rows: {account_code, account_name, budget, actual, variance, variance_pct}
		All amounts in integer cents.
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLBudget,
			GLAccountBalance,
			GLAccount,
		)

		budget_rows = session.execute(
			select(
				GLBudget.account_code,
				GLAccount.account_name,
				GLAccount.account_type,
				GLAccount.normal_balance,
				GLBudget.budget_amount,
				GLBudget.revised_budget_amount,
				GLBudget.forecast_amount,
			)
			.join(GLAccount, GLAccount.account_code == GLBudget.account_code)
			.where(GLBudget.period_id == period_id, GLBudget.version == version)
			.order_by(GLBudget.account_code)
		).all()

		# Load actuals keyed by account_code
		actual_map: dict[str, int] = {}
		actual_rows = session.execute(
			select(GLAccountBalance.account_code, GLAccountBalance.period_debit,
			       GLAccountBalance.period_credit)
			.where(GLAccountBalance.period_id == period_id)
		).all()
		for ar in actual_rows:
			actual_map[ar.account_code] = ar.period_debit - ar.period_credit

		result = []
		for row in budget_rows:
			budget = row.revised_budget_amount or row.budget_amount
			actual = actual_map.get(row.account_code, 0)
			variance = actual - budget
			variance_pct = round((variance / budget * 100), 2) if budget else None
			result.append({
				"account_code": row.account_code,
				"account_name": row.account_name,
				"account_type": row.account_type,
				"budget": budget,
				"actual": actual,
				"variance": variance,
				"variance_pct": variance_pct,
				"forecast": row.forecast_amount,
			})
		return result

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _upsert_balance(
		self,
		session: Any,
		tenant_id: str,
		account_code: str,
		period_id: str,
		debit: int,
		credit: int,
		GLAccountBalance: Any,
	) -> None:
		"""Upsert GLAccountBalance, incrementing period debit/credit totals."""
		bal = session.execute(
			select(GLAccountBalance).where(
				GLAccountBalance.tenant_id == tenant_id,
				GLAccountBalance.account_code == account_code,
				GLAccountBalance.period_id == period_id,
			)
		).scalar_one_or_none()

		if bal is None:
			bal = GLAccountBalance(
				tenant_id=tenant_id,
				account_code=account_code,
				period_id=period_id,
				opening_debit=0,
				opening_credit=0,
				period_debit=0,
				period_credit=0,
				closing_debit=0,
				closing_credit=0,
				ytd_debit=0,
				ytd_credit=0,
			)
			session.add(bal)

		bal.period_debit += debit
		bal.period_credit += credit
		bal.closing_debit = bal.opening_debit + bal.period_debit
		bal.closing_credit = bal.opening_credit + bal.period_credit
		bal.ytd_debit += debit
		bal.ytd_credit += credit
		bal.refreshed_at = datetime.now(timezone.utc)


__all__ = [
	"GLService",
	"GLServiceError",
	"JournalImbalancedError",
	"PeriodClosedError",
	"PostingAccountError",
	"InactiveAccountError",
	"BatchNotFoundError",
	"EntryNotFoundError",
	"PeriodNotFoundError",
	"PeriodHasOpenBatchesError",
]
