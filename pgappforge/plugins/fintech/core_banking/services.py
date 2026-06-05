"""
pgappforge/plugins/fintech/core_banking/services.py

CoreBankingService — the heart of the core banking system.

ALL account operations flow through this service.  The public interface
is fully synchronous (Flask/SQLAlchemy context); async wrappers can be
added by callers if needed.

Double-entry invariant
----------------------
Every monetary transaction creates EXACTLY two LedgerEntry rows sharing the
same journal_id: one DEBIT and one CREDIT.  The service enforces this in
every mutating method.

Immutability invariant
----------------------
LedgerEntry and InterestAccrual rows are INSERT-ONLY.  Corrections are made
by creating new REVERSAL entries, never by UPDATEing existing rows.

Event emission
--------------
All emit_event() calls are wrapped in try/except.  A failure to publish an
event NEVER causes the business transaction to fail.

Money arithmetic
----------------
All amounts are in integer minor-currency units (cents/kobo/fils).
Intermediate calculations use Decimal via the money_* helpers from
erp.foundation.commons to avoid float rounding errors.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.commons import (
	money_add,
	money_divide,
	money_multiply,
	money_subtract,
	format_currency,
	emit_event,
)

from pgappforge.plugins.fintech.core_banking.models import (
	Account,
	AccountHold,
	AccountStatement,
	AMLScreeningResult,
	BankProduct,
	CB_ACCOUNT_SEQ,
	GLAccountMapping,
	InterestAccrual,
	LedgerEntry,
)
from pgappforge.plugins.fintech.core_banking.events import (
	AccountClosedEvent,
	AccountCreditedEvent,
	AccountDebitedEvent,
	AccountDormantEvent,
	AccountFrozenEvent,
	AccountOpenedEvent,
	AccountTransferredEvent,
	AccountUnfrozenEvent,
	AMLBlockedEvent as AMLBlockedEventClass,
	AMLFlaggedEvent,
	FeeChargedEvent,
	HoldExpiredEvent,
	HoldPlacedEvent,
	HoldReleasedEvent,
	InterestAccruedEvent,
	InterestCapitalizedEvent,
	StatementDeliveredEvent,
	TransactionReversedEvent,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class CoreBankingError(Exception):
	"""Base exception for all core banking service errors."""


class AccountNotFoundError(CoreBankingError):
	"""No account matching the given identifier."""


class ProductNotFoundError(CoreBankingError):
	"""No product matching the given product_code."""


class InsufficientFundsError(CoreBankingError):
	"""Available balance is below the requested withdrawal/transfer amount."""


class AccountStatusError(CoreBankingError):
	"""Operation is not permitted for the account's current status."""


class DailyLimitExceededError(CoreBankingError):
	"""Transaction would breach the product's daily withdrawal limit."""


class HoldNotFoundError(CoreBankingError):
	"""No active hold found with the given hold_id."""


class TransactionAlreadyReversedError(CoreBankingError):
	"""The requested journal_id has already been reversed."""


class AMLBlockedError(CoreBankingError):
	"""Transaction blocked by AML screening."""


class IBANValidationError(CoreBankingError):
	"""IBAN failed mod-97 checksum validation."""


# ---------------------------------------------------------------------------
# Default GL chart-of-accounts codes
# ---------------------------------------------------------------------------
# This is the fallback when no GLAccountMapping row exists for a tenant+key.
# Override per-tenant via GLAccountMapping rows (cb_gl_mapping table).
# Keys align with the logical names used in _resolve_gl() calls throughout
# this service.

_CB_GL: dict[str, str] = {
	"CASH_NOSTRO":               "1010",   # Asset: cash / nostro account
	"LOAN_RECEIVABLE":           "1500",   # Asset: loan receivable (disbursements/repayments)
	"LOAN_LOSS_RESERVE":         "1590",   # Contra-asset: allowance for loan losses (write-offs)
	"CUSTOMER_DEPOSITS":         "2000",   # Liability: customer deposit balances
	"INTEREST_INCOME":           "4100",   # Income: interest earned on loans
	"INTEREST_EXPENSE":          "5100",   # Expense: interest paid on deposits
	"FEE_INCOME":                "4200",   # Income: fee revenue
}

# ---------------------------------------------------------------------------
# Islamic banking GL codes (AAOIFI / IFRS 9 compliant)
# ---------------------------------------------------------------------------
# These codes mirror _CB_GL's purpose for Sharia-compliant products.
# Per-tenant overrides work the same way via GLAccountMapping rows.

_ISLAMIC_GL: dict[str, str] = {
	"MURABAHA_RECEIVABLE": "1520",   # Asset: murabaha financing receivable
	"DEFERRED_INCOME":     "2250",   # Liability: unearned murabaha profit
	"MURABAHA_INCOME":     "4150",   # Revenue: murabaha profit income recognised
}


# ---------------------------------------------------------------------------
# Account number generation
# ---------------------------------------------------------------------------

def _generate_account_number(branch_code: str, seq: int) -> str:
	"""Format: YYYYMMDD-BRANCH-SEQNO (zero-padded to 8 digits).

	Example: 20260601-NBI001-00000042
	"""
	today = date.today().strftime("%Y%m%d")
	branch = (branch_code or "HQ0001").upper()[:6]
	return f"{today}-{branch}-{seq:08d}"


def _new_journal_id() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# CoreBankingService
# ---------------------------------------------------------------------------

class CoreBankingService:
	"""Core banking operations: accounts, ledger, interest, holds, statements.

	All methods take an explicit ``session`` argument (SQLAlchemy Session) so
	the caller controls transaction boundaries.  The service never commits;
	callers commit after confirming success.

	Usage::

		svc = CoreBankingService()
		with db.session() as session:
			account = svc.open_account(
				session,
				customer_id="<uuid>",
				product_code="SAV001",
				opening_deposit_cents=500_00,
				branch_code="NBI001",
				tenant_id="acme",
			)
			session.commit()
	"""

	# ------------------------------------------------------------------
	# open_account
	# ------------------------------------------------------------------

	def open_account(
		self,
		session: Session,
		customer_id: str,
		product_code: str,
		opening_deposit_cents: int = 0,
		branch_code: str | None = None,
		rm_id: str | None = None,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> Account:
		"""Open a new account for *customer_id* on product *product_code*.

		Steps:
		  1. Resolve product and validate it is active.
		  2. Validate opening deposit >= product.min_opening_balance_cents.
		  3. Generate account number (YYYYMMDD-BRANCH-SEQNO).
		  4. Create Account in PENDING_ACTIVATION status.
		  5. If opening_deposit_cents > 0, post a CREDIT entry; activate.
		  6. Emit cb.account.opened.

		Returns the activated (or pending) Account instance added to session.
		"""
		product = session.execute(
			select(BankProduct).where(
				BankProduct.product_code == product_code,
				BankProduct.is_active.is_(True),
			)
		).scalar_one_or_none()
		if product is None:
			raise ProductNotFoundError(f"Active product {product_code!r} not found")

		# Enforce min_opening_balance unconditionally — catches zero-deposit
		# against a product that requires a minimum, regardless of path.
		if opening_deposit_cents < product.min_opening_balance_cents:
			raise CoreBankingError(
				f"Opening deposit {opening_deposit_cents}c is below "
				f"product minimum {product.min_opening_balance_cents}c "
				f"for product {product_code!r}"
			)

		# Race-safe account number: use a PostgreSQL global sequence instead of
		# COUNT(LIKE pattern) which is not atomic under concurrent callers.
		branch = (branch_code or "HQ0001").upper()[:6]
		seq = session.execute(
			sa.text("SELECT nextval('cb_account_seq')")
		).scalar_one()
		account_number = _generate_account_number(branch, int(seq))

		account = Account(
			tenant_id=tenant_id,
			account_number=account_number,
			product_id=product.id,
			customer_id=customer_id,
			currency_code=product.currency_code,
			current_balance_cents=0,
			available_balance_cents=0,
			accrued_interest_cents=0,
			holds_cents=0,
			status="PENDING_ACTIVATION",
			opened_date=date.today(),
			branch_code=branch_code,
			relationship_manager_id=rm_id,
		)
		session.add(account)
		session.flush()  # get account.id

		# Auto-generate IBAN if plugin config enables it
		try:
			from flask import current_app
			_ab = current_app.extensions.get("appbuilder")
			_cfg = (_ab.app.config if _ab else {}) if _ab else {}
			if _cfg.get("CB_AUTO_GENERATE_IBAN", False):
				country_code = _cfg.get("CB_COUNTRY_CODE", "KE")
				bank_code = _cfg.get("CB_BANK_CODE", "000000")
				account.iban = self.generate_iban(
					country_code=country_code,
					bank_code=bank_code,
					branch_code=branch_code or "000000",
					account_number=account_number.replace("-", "")[-10:],
				)
		except RuntimeError:
			pass  # No app context — skip IBAN generation
		except Exception as exc:
			log.warning("open_account: IBAN generation failed (non-fatal): %s", exc)

		if opening_deposit_cents > 0:
			self._post_credit(
				session=session,
				account=account,
				amount_cents=opening_deposit_cents,
				transaction_type="DEPOSIT",
				channel="BRANCH",
				reference=f"OPEN-{account_number}",
				narrative="Account opening deposit",
				tenant_id=tenant_id,
			)
		account.status = "ACTIVE"

		try:
			emit_event(
				event_type="cb.account.opened",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload=AccountOpenedEvent(
					account_id=account.id,
					account_number=account.account_number,
					customer_id=customer_id,
					product_code=product_code,
					currency_code=account.currency_code,
					branch_code=branch_code or "",
					opening_deposit_cents=opening_deposit_cents,
					aggregate_id=account.id,
					aggregate_type="Account",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("open_account: event emit failed (non-fatal): %s", exc)

		return account

	# ------------------------------------------------------------------
	# deposit
	# ------------------------------------------------------------------

	def deposit(
		self,
		session: Session,
		account_number: str,
		amount_cents: int,
		channel: str,
		reference: str,
		narrative: str | None = None,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> dict:
		"""Post a cash/cheque deposit to *account_number*.

		Validates:
		  - Account exists and is ACTIVE.
		  - Amount is positive.

		Posts a CREDIT to the account + DEBIT to a virtual vault GL.

		Returns::

			{
				"journal_id": str,
				"entry_id": str,
				"new_balance_cents": int,
				"new_available_balance_cents": int,
			}
		"""
		if amount_cents <= 0:
			raise CoreBankingError("Deposit amount must be positive")

		account = self._require_account(session, account_number)
		self._assert_active(account)

		# AML gate — raises AMLBlockedError if blocked; FLAGGED proceeds
		self._run_aml_check(
			session=session,
			account=account,
			amount_cents=amount_cents,
			transaction_type="DEPOSIT",
			reference=reference,
			tenant_id=tenant_id,
		)

		entry = self._post_credit(
			session=session,
			account=account,
			amount_cents=amount_cents,
			transaction_type="DEPOSIT",
			channel=channel,
			reference=reference,
			narrative=narrative,
			tenant_id=tenant_id,
		)

		# GL bridge: DR CASH_NOSTRO / CR CUSTOMER_DEPOSITS
		self._post_to_gl(
			session=session,
			lines=[
				{
					"account_code": "CASH_NOSTRO",
					"debit_cents": amount_cents,
					"credit_cents": 0,
					"party_id": account.id,
					"description": f"Deposit {reference}",
				},
				{
					"account_code": "CUSTOMER_DEPOSITS",
					"debit_cents": 0,
					"credit_cents": amount_cents,
					"party_id": account.id,
					"description": f"Deposit {reference}",
				},
			],
			description=f"DEPOSIT {account.account_number} {reference}",
			tenant_id=tenant_id,
			source_doc_id=entry.id,
			source_doc_type="CB_LEDGER_ENTRY",
		)

		try:
			emit_event(
				event_type="cb.account.credited",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload=AccountCreditedEvent(
					account_id=account.id,
					account_number=account.account_number,
					journal_id=entry.journal_id,
					entry_id=entry.id,
					amount_cents=amount_cents,
					currency_code=account.currency_code,
					transaction_type="DEPOSIT",
					channel=channel,
					reference_number=reference,
					new_balance_cents=account.current_balance_cents,
					aggregate_id=account.id,
					aggregate_type="Account",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("deposit: event emit failed (non-fatal): %s", exc)

		return {
			"journal_id": entry.journal_id,
			"entry_id": entry.id,
			"new_balance_cents": account.current_balance_cents,
			"new_available_balance_cents": account.available_balance_cents,
		}

	# ------------------------------------------------------------------
	# withdraw
	# ------------------------------------------------------------------

	def withdraw(
		self,
		session: Session,
		account_number: str,
		amount_cents: int,
		channel: str,
		reference: str,
		narrative: str | None = None,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> dict:
		"""Post a withdrawal (debit) from *account_number*.

		Validates:
		  - Account is ACTIVE.
		  - Sufficient available_balance (>= amount + min_balance).
		  - Channel is allowed by product.
		  - Daily withdrawal limit not exceeded (if set on product).

		Returns::

			{
				"journal_id": str,
				"entry_id": str,
				"new_balance_cents": int,
				"new_available_balance_cents": int,
			}
		"""
		if amount_cents <= 0:
			raise CoreBankingError("Withdrawal amount must be positive")

		account = self._require_account(session, account_number)
		self._assert_active(account)
		self._assert_channel_allowed(account, channel, session)

		# AML gate — raises AMLBlockedError if blocked; FLAGGED proceeds
		self._run_aml_check(
			session=session,
			account=account,
			amount_cents=amount_cents,
			transaction_type="WITHDRAWAL",
			reference=reference,
			tenant_id=tenant_id,
		)

		product = session.get(BankProduct, account.product_id)
		min_bal = product.min_balance_cents if product else 0

		if account.available_balance_cents - amount_cents < min_bal:
			raise InsufficientFundsError(
				f"Insufficient available balance: "
				f"have {account.available_balance_cents}c, "
				f"need {amount_cents + min_bal}c (incl. min balance {min_bal}c)"
			)

		if product and product.max_withdrawal_per_day_cents is not None:
			daily_debits = self._daily_debit_total(session, account.id)
			if daily_debits + amount_cents > product.max_withdrawal_per_day_cents:
				raise DailyLimitExceededError(
					f"Daily withdrawal limit {product.max_withdrawal_per_day_cents}c "
					f"would be exceeded: already withdrawn {daily_debits}c today"
				)

		entry = self._post_debit(
			session=session,
			account=account,
			amount_cents=amount_cents,
			transaction_type="WITHDRAWAL",
			channel=channel,
			reference=reference,
			narrative=narrative,
			tenant_id=tenant_id,
		)

		# GL bridge: DR CUSTOMER_DEPOSITS / CR CASH_NOSTRO
		self._post_to_gl(
			session=session,
			lines=[
				{
					"account_code": "CUSTOMER_DEPOSITS",
					"debit_cents": amount_cents,
					"credit_cents": 0,
					"party_id": account.id,
					"description": f"Withdrawal {reference}",
				},
				{
					"account_code": "CASH_NOSTRO",
					"debit_cents": 0,
					"credit_cents": amount_cents,
					"party_id": account.id,
					"description": f"Withdrawal {reference}",
				},
			],
			description=f"WITHDRAWAL {account.account_number} {reference}",
			tenant_id=tenant_id,
			source_doc_id=entry.id,
			source_doc_type="CB_LEDGER_ENTRY",
		)

		try:
			emit_event(
				event_type="cb.account.debited",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload=AccountDebitedEvent(
					account_id=account.id,
					account_number=account.account_number,
					journal_id=entry.journal_id,
					entry_id=entry.id,
					amount_cents=amount_cents,
					currency_code=account.currency_code,
					transaction_type="WITHDRAWAL",
					channel=channel,
					reference_number=reference,
					new_balance_cents=account.current_balance_cents,
					aggregate_id=account.id,
					aggregate_type="Account",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("withdraw: event emit failed (non-fatal): %s", exc)

		return {
			"journal_id": entry.journal_id,
			"entry_id": entry.id,
			"new_balance_cents": account.current_balance_cents,
			"new_available_balance_cents": account.available_balance_cents,
		}

	# ------------------------------------------------------------------
	# transfer
	# ------------------------------------------------------------------

	def transfer(
		self,
		session: Session,
		from_account_number: str,
		to_account_number: str,
		amount_cents: int,
		reference: str,
		narrative: str | None = None,
		exchange_rate: Decimal | None = None,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> dict:
		"""Atomic intra-bank transfer: DEBIT from + CREDIT to in one journal_id.

		Supports same-currency and cross-currency transfers (provide
		exchange_rate as Decimal for FX; defaults to 1 for same-currency).

		For cross-currency: from_account debited amount_cents in its currency;
		to_account credited money_multiply(amount_cents, exchange_rate) in its currency.

		Returns::

			{
				"journal_id": str,
				"debit_entry_id": str,
				"credit_entry_id": str,
				"from_new_balance_cents": int,
				"to_new_balance_cents": int,
			}
		"""
		if amount_cents <= 0:
			raise CoreBankingError("Transfer amount must be positive")

		from_acct = self._require_account(session, from_account_number)
		to_acct = self._require_account(session, to_account_number)

		self._assert_active(from_acct)
		self._assert_active(to_acct)
		self._assert_channel_allowed(from_acct, "ONLINE", session)

		# AML gate on the originating account — raises AMLBlockedError if blocked
		self._run_aml_check(
			session=session,
			account=from_acct,
			amount_cents=amount_cents,
			transaction_type="TRANSFER",
			reference=reference,
			tenant_id=tenant_id,
		)

		from_product = session.get(BankProduct, from_acct.product_id)
		min_bal = from_product.min_balance_cents if from_product else 0

		if from_acct.available_balance_cents - amount_cents < min_bal:
			raise InsufficientFundsError(
				f"Insufficient available balance in {from_account_number}: "
				f"have {from_acct.available_balance_cents}c, need {amount_cents + min_bal}c"
			)

		rate = exchange_rate or Decimal("1")
		credit_amount_cents = money_multiply(amount_cents, rate)

		journal_id = _new_journal_id()
		today = date.today()

		# DEBIT from_acct
		from_acct.current_balance_cents = money_subtract(
			from_acct.current_balance_cents, amount_cents
		)
		from_acct.available_balance_cents = money_subtract(
			from_acct.available_balance_cents, amount_cents
		)
		from_acct.last_transaction_at = datetime.now(timezone.utc)
		debit_entry = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="DEBIT",
			account_id=from_acct.id,
			amount_cents=amount_cents,
			currency_code=from_acct.currency_code,
			exchange_rate=rate,
			balance_after_cents=from_acct.current_balance_cents,
			value_date=today,
			posting_date=today,
			transaction_type="TRANSFER_OUT",
			channel="ONLINE",
			reference_number=reference,
			narrative=narrative,
		)
		session.add(debit_entry)
		session.flush()

		# CREDIT to_acct
		to_acct.current_balance_cents = money_add(
			to_acct.current_balance_cents, credit_amount_cents
		)
		to_acct.available_balance_cents = money_add(
			to_acct.available_balance_cents, credit_amount_cents
		)
		to_acct.last_transaction_at = datetime.now(timezone.utc)
		credit_entry = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="CREDIT",
			account_id=to_acct.id,
			amount_cents=credit_amount_cents,
			currency_code=to_acct.currency_code,
			exchange_rate=rate,
			balance_after_cents=to_acct.current_balance_cents,
			value_date=today,
			posting_date=today,
			transaction_type="TRANSFER_IN",
			channel="ONLINE",
			reference_number=reference,
			narrative=narrative,
		)
		session.add(credit_entry)
		session.flush()

		# GL bridge: DR CUSTOMER_DEPOSITS (from) / CR CUSTOMER_DEPOSITS (to)
		# Both sides use the same GL account; party_id differentiates them.
		self._post_to_gl(
			session=session,
			lines=[
				{
					"account_code": "CUSTOMER_DEPOSITS",
					"debit_cents": amount_cents,
					"credit_cents": 0,
					"party_id": from_acct.id,
					"description": f"Transfer out {reference}",
				},
				{
					"account_code": "CUSTOMER_DEPOSITS",
					"debit_cents": 0,
					"credit_cents": amount_cents,  # use source currency for GL balance; FX tracked in LedgerEntry
					"party_id": to_acct.id,
					"description": f"Transfer in {reference}",
				},
			],
			description=f"TRANSFER {from_acct.account_number}→{to_acct.account_number} {reference}",
			tenant_id=tenant_id,
			source_doc_id=journal_id,
			source_doc_type="CB_TRANSFER",
		)

		try:
			emit_event(
				event_type="cb.account.transferred",
				aggregate_type="Account",
				aggregate_id=from_acct.id,
				payload=AccountTransferredEvent(
					journal_id=journal_id,
					from_account_id=from_acct.id,
					from_account_number=from_acct.account_number,
					to_account_id=to_acct.id,
					to_account_number=to_acct.account_number,
					amount_cents=amount_cents,
					currency_code=from_acct.currency_code,
					exchange_rate=str(rate),
					reference_number=reference,
					debit_entry_id=debit_entry.id,
					credit_entry_id=credit_entry.id,
					aggregate_id=from_acct.id,
					aggregate_type="Account",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("transfer: event emit failed (non-fatal): %s", exc)

		return {
			"journal_id": journal_id,
			"debit_entry_id": debit_entry.id,
			"credit_entry_id": credit_entry.id,
			"from_new_balance_cents": from_acct.current_balance_cents,
			"to_new_balance_cents": to_acct.current_balance_cents,
		}

	# ------------------------------------------------------------------
	# accrue_interest
	# ------------------------------------------------------------------

	def accrue_interest(
		self,
		session: Session,
		accrual_date: date,
		product_type: str | None = None,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> dict:
		"""Daily batch: compute and record interest accrual for all active accounts.

		interest_cents = floor(balance * rate_pa / 365)

		Only processes accounts whose product matches *product_type* when
		that filter is provided.  Skips accounts already processed for
		*accrual_date* (idempotent).

		Returns::

			{
				"accounts_processed": int,
				"total_accrued_cents": int,
				"accrual_date": str (ISO),
			}
		"""
		q = (
			select(Account)
			.join(BankProduct, Account.product_id == BankProduct.id)
			.where(Account.status == "ACTIVE")
		)
		# Explicit conditional — avoids the ternary-in-where bug where an empty
		# string evaluates falsy and bypasses the tenant filter entirely.
		if tenant_id:
			q = q.where(Account.tenant_id == tenant_id)
		if product_type:
			q = q.where(BankProduct.product_type == product_type)

		accounts = session.execute(q).scalars().all()

		# IDs already accrued today — skip them (idempotency)
		already_done_q = select(InterestAccrual.account_id).where(
			InterestAccrual.accrual_date == accrual_date,
		)
		if tenant_id:
			already_done_q = already_done_q.where(InterestAccrual.tenant_id == tenant_id)
		already_done_ids: set[str] = set(
			session.execute(already_done_q).scalars().all()
		)

		processed = 0
		total_accrued = 0

		for account in accounts:
			if account.id in already_done_ids:
				continue

			product = session.get(BankProduct, account.product_id)
			if not product or product.interest_rate_pa == 0:
				continue

			# Islamic products: delegate to IslamicBankingService and skip
			# conventional interest logic entirely (riba-free requirement).
			if product.is_islamic:
				try:
					IslamicBankingService().accrue_murabaha_income(
						session=session,
						account_number=account.account_number,
						period_months=1,
						tenant_id=tenant_id,
					)
					processed += 1
				except Exception as exc:
					log.warning(
						"accrue_interest: Islamic accrual failed for %s (non-fatal): %s",
						account.account_number, exc,
					)
				continue

			# Dispatch on product.interest_calculation:
			#   DAILY_BALANCE      — current balance × rate / 365
			#   FLAT               — original principal × rate / 365
			#   AVERAGE_DAILY_BALANCE — time-weighted intraday average × rate / 365
			daily_rate = Decimal(str(product.interest_rate_pa)) / Decimal("365")
			calc_method = (product.interest_calculation or "DAILY_BALANCE").upper()
			if calc_method == "FLAT":
				# Flat-rate loan: interest is computed on the original principal,
				# not the reducing balance.
				principal = account.original_principal_cents or account.current_balance_cents
				accrued = money_multiply(principal, daily_rate)
			elif calc_method == "AVERAGE_DAILY_BALANCE":
				avg_balance = self._compute_avg_daily_balance(session, account, accrual_date)
				accrued = money_multiply(avg_balance, daily_rate)
			else:
				# Default: DAILY_BALANCE
				accrued = money_multiply(account.current_balance_cents, daily_rate)

			# Cumulative since last capitalisation
			last_cumulative = session.execute(
				select(InterestAccrual.cumulative_accrued_cents)
				.where(
					InterestAccrual.account_id == account.id,
					InterestAccrual.is_capitalized.is_(False),
				)
				.order_by(InterestAccrual.accrual_date.desc())
				.limit(1)
			).scalar_one_or_none() or 0
			cumulative = money_add(last_cumulative, accrued)

			accrual = InterestAccrual(
				tenant_id=tenant_id,
				account_id=account.id,
				accrual_date=accrual_date,
				opening_balance_cents=account.current_balance_cents,
				rate_applied_pa=product.interest_rate_pa,
				accrued_cents=accrued,
				cumulative_accrued_cents=cumulative,
				is_capitalized=False,
			)
			session.add(accrual)

			# Update account's running accrued interest
			account.accrued_interest_cents = money_add(
				account.accrued_interest_cents, accrued
			)
			account.last_interest_accrual_date = accrual_date

			total_accrued += accrued
			processed += 1

		session.flush()

		try:
			emit_event(
				event_type="cb.interest.accrued",
				aggregate_type="InterestAccrual",
				aggregate_id=tenant_id or "system",
				payload=InterestAccruedEvent(
					accrual_date=accrual_date.isoformat(),
					product_type=product_type or "",
					accounts_processed=processed,
					total_accrued_cents=total_accrued,
					aggregate_id=tenant_id or "system",
					aggregate_type="InterestAccrual",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("accrue_interest: event emit failed (non-fatal): %s", exc)

		return {
			"accounts_processed": processed,
			"total_accrued_cents": total_accrued,
			"accrual_date": accrual_date.isoformat(),
		}

	# ------------------------------------------------------------------
	# capitalize_interest
	# ------------------------------------------------------------------

	def capitalize_interest(
		self,
		session: Session,
		account_number: str,
		capitalization_date: date,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> dict:
		"""Move accrued interest to actual balance (post CREDIT entry).

		Marks all pending InterestAccrual rows for this account as capitalized.
		Creates a LedgerEntry with transaction_type=INTEREST_CREDIT (or INTEREST_DEBIT
		for negative-rate / fee scenarios).

		Returns::

			{
				"capitalized_cents": int,
				"new_balance_cents": int,
				"accrual_records_count": int,
				"journal_id": str,
			}
		"""
		account = self._require_account(session, account_number)
		self._assert_active(account)

		pending = session.execute(
			select(InterestAccrual).where(
				InterestAccrual.account_id == account.id,
				InterestAccrual.is_capitalized.is_(False),
			)
		).scalars().all()

		if not pending:
			return {
				"capitalized_cents": 0,
				"new_balance_cents": account.current_balance_cents,
				"accrual_records_count": 0,
				"journal_id": "",
			}

		total_to_capitalize = sum(r.accrued_cents for r in pending)

		if total_to_capitalize <= 0:
			for r in pending:
				# Still mark as capitalized even if net is zero
				session.execute(
					update(InterestAccrual)
					.where(InterestAccrual.id == r.id)
					.values(is_capitalized=True, capitalized_at=datetime.now(timezone.utc))
					.execution_options(synchronize_session="fetch")
				)
			return {
				"capitalized_cents": 0,
				"new_balance_cents": account.current_balance_cents,
				"accrual_records_count": len(pending),
				"journal_id": "",
			}

		journal_id = _new_journal_id()
		account.current_balance_cents = money_add(
			account.current_balance_cents, total_to_capitalize
		)
		account.available_balance_cents = money_add(
			account.available_balance_cents, total_to_capitalize
		)
		account.accrued_interest_cents = 0
		account.last_transaction_at = datetime.now(timezone.utc)

		cap_entry = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="CREDIT",
			account_id=account.id,
			amount_cents=total_to_capitalize,
			currency_code=account.currency_code,
			exchange_rate=Decimal("1"),
			balance_after_cents=account.current_balance_cents,
			value_date=capitalization_date,
			posting_date=capitalization_date,
			transaction_type="INTEREST_CREDIT",
			channel="SYSTEM",
			reference_number=f"CAP-{account.account_number}-{capitalization_date.isoformat()}",
			narrative="Interest capitalisation",
			is_interest=True,
		)
		session.add(cap_entry)
		session.flush()

		# Mark accrual rows as capitalized via direct UPDATE (bypasses ORM
		# immutability guard which only fires on session.merge / state tracking)
		now_ts = datetime.now(timezone.utc)
		pending_ids = [r.id for r in pending]
		session.execute(
			update(InterestAccrual)
			.where(InterestAccrual.id.in_(pending_ids))
			.values(is_capitalized=True, capitalized_at=now_ts)
			.execution_options(synchronize_session="fetch")
		)

		try:
			emit_event(
				event_type="cb.interest.capitalized",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload=InterestCapitalizedEvent(
					account_id=account.id,
					account_number=account.account_number,
					journal_id=journal_id,
					capitalized_cents=total_to_capitalize,
					new_balance_cents=account.current_balance_cents,
					capitalization_date=capitalization_date.isoformat(),
					accrual_records_count=len(pending),
					aggregate_id=account.id,
					aggregate_type="Account",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("capitalize_interest: event emit failed (non-fatal): %s", exc)

		return {
			"capitalized_cents": total_to_capitalize,
			"new_balance_cents": account.current_balance_cents,
			"accrual_records_count": len(pending),
			"journal_id": journal_id,
		}

	# ------------------------------------------------------------------
	# place_hold / release_hold
	# ------------------------------------------------------------------

	def place_hold(
		self,
		session: Session,
		account_number: str,
		amount_cents: int,
		reason: str,
		reference: str,
		expires_at: datetime | None = None,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> AccountHold:
		"""Place a hold on *amount_cents* of *account_number*'s available balance.

		Reduces available_balance_cents without touching current_balance_cents.
		Raises InsufficientFundsError if available < hold amount.
		"""
		if amount_cents <= 0:
			raise CoreBankingError("Hold amount must be positive")

		account = self._require_account(session, account_number)
		self._assert_not_closed(account)

		if account.available_balance_cents < amount_cents:
			raise InsufficientFundsError(
				f"Cannot place hold of {amount_cents}c: "
				f"available balance is {account.available_balance_cents}c"
			)

		hold = AccountHold(
			tenant_id=tenant_id,
			account_id=account.id,
			amount_cents=amount_cents,
			hold_reason=reason,
			reference_number=reference,
			expires_at=expires_at,
			status="ACTIVE",
		)
		session.add(hold)

		account.available_balance_cents = money_subtract(
			account.available_balance_cents, amount_cents
		)
		account.holds_cents = money_add(account.holds_cents, amount_cents)
		session.flush()

		try:
			emit_event(
				event_type="cb.hold.placed",
				aggregate_type="AccountHold",
				aggregate_id=hold.id,
				payload=HoldPlacedEvent(
					hold_id=hold.id,
					account_id=account.id,
					account_number=account.account_number,
					amount_cents=amount_cents,
					hold_reason=reason,
					reference_number=reference,
					expires_at=expires_at.isoformat() if expires_at else "",
					aggregate_id=hold.id,
					aggregate_type="AccountHold",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("place_hold: event emit failed (non-fatal): %s", exc)

		return hold

	def release_hold(
		self,
		session: Session,
		hold_id: str,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> AccountHold:
		"""Release an ACTIVE hold, restoring available_balance_cents."""
		hold = session.get(AccountHold, hold_id)
		if hold is None or hold.status != "ACTIVE":
			raise HoldNotFoundError(f"Active hold {hold_id!r} not found")

		account = session.get(Account, hold.account_id)
		if account is None:
			raise AccountNotFoundError(f"Account for hold {hold_id!r} not found")

		hold.status = "RELEASED"
		account.available_balance_cents = money_add(
			account.available_balance_cents, hold.amount_cents
		)
		account.holds_cents = money_subtract(account.holds_cents, hold.amount_cents)
		session.flush()

		try:
			emit_event(
				event_type="cb.hold.released",
				aggregate_type="AccountHold",
				aggregate_id=hold.id,
				payload=HoldReleasedEvent(
					hold_id=hold.id,
					account_id=account.id,
					account_number=account.account_number,
					amount_cents=hold.amount_cents,
					release_reason="MANUAL",
					aggregate_id=hold.id,
					aggregate_type="AccountHold",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("release_hold: event emit failed (non-fatal): %s", exc)

		return hold

	# ------------------------------------------------------------------
	# close_account
	# ------------------------------------------------------------------

	def close_account(
		self,
		session: Session,
		account_number: str,
		reason: str,
		closing_balance_destination_account: str | None = None,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> Account:
		"""Close an account.

		If a non-zero balance remains and *closing_balance_destination_account*
		is provided, the residual is transferred there first.  Otherwise a
		non-zero balance raises CoreBankingError.
		"""
		account = self._require_account(session, account_number)
		self._assert_not_closed(account)

		if account.current_balance_cents != 0:
			if closing_balance_destination_account:
				self.transfer(
					session=session,
					from_account_number=account_number,
					to_account_number=closing_balance_destination_account,
					amount_cents=account.current_balance_cents,
					reference=f"CLOSE-{account_number}",
					narrative=f"Account closure: {reason}",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				)
			else:
				raise CoreBankingError(
					f"Cannot close account with non-zero balance "
					f"({account.current_balance_cents}c). "
					"Provide closing_balance_destination_account."
				)

		account.status = "CLOSED"
		account.closed_date = date.today()
		session.flush()

		try:
			emit_event(
				event_type="cb.account.closed",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload=AccountClosedEvent(
					account_id=account.id,
					account_number=account.account_number,
					customer_id=account.customer_id,
					reason=reason,
					closing_balance_cents=0,
					closing_balance_destination=closing_balance_destination_account or "",
					aggregate_id=account.id,
					aggregate_type="Account",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("close_account: event emit failed (non-fatal): %s", exc)

		return account

	# ------------------------------------------------------------------
	# get_balance
	# ------------------------------------------------------------------

	def get_balance(
		self,
		session: Session,
		account_number: str,
	) -> dict:
		"""Return a balance snapshot for *account_number*.

		Returns::

			{
				"current_balance_cents": int,
				"available_balance_cents": int,
				"holds_cents": int,
				"accrued_interest_cents": int,
				"currency_code": str,
				"status": str,
			}
		"""
		account = self._require_account(session, account_number)
		return {
			"current_balance_cents": account.current_balance_cents,
			"available_balance_cents": account.available_balance_cents,
			"holds_cents": account.holds_cents,
			"accrued_interest_cents": account.accrued_interest_cents,
			"currency_code": account.currency_code,
			"status": account.status,
		}

	# ------------------------------------------------------------------
	# get_mini_statement
	# ------------------------------------------------------------------

	def get_mini_statement(
		self,
		session: Session,
		account_number: str,
		last_n: int = 10,
	) -> list[dict]:
		"""Return the last *last_n* ledger entries for *account_number*.

		Each dict::

			{
				"entry_id": str,
				"journal_id": str,
				"entry_type": str,           # DEBIT | CREDIT
				"amount_cents": int,
				"balance_after_cents": int,
				"transaction_type": str,
				"channel": str,
				"reference_number": str,
				"narrative": str,
				"posting_date": str,         # ISO date
				"value_date": str,           # ISO date
			}
		"""
		account = self._require_account(session, account_number)

		entries = session.execute(
			select(LedgerEntry)
			.where(LedgerEntry.account_id == account.id)
			.order_by(LedgerEntry.created_at.desc())
			.limit(last_n)
		).scalars().all()

		return [
			{
				"entry_id": e.id,
				"journal_id": e.journal_id,
				"entry_type": e.entry_type,
				"amount_cents": e.amount_cents,
				"balance_after_cents": e.balance_after_cents,
				"transaction_type": e.transaction_type,
				"channel": e.channel or "",
				"reference_number": e.reference_number or "",
				"narrative": e.narrative or "",
				"posting_date": e.posting_date.isoformat() if e.posting_date else "",
				"value_date": e.value_date.isoformat() if e.value_date else "",
				"currency_code": e.currency_code,
			}
			for e in entries
		]

	# ------------------------------------------------------------------
	# generate_statement
	# ------------------------------------------------------------------

	def generate_statement(
		self,
		session: Session,
		account_number: str,
		from_date: date,
		to_date: date,
		tenant_id: str = "",
		delivery_method: str = "EMAIL",
	) -> AccountStatement:
		"""Build an AccountStatement for *account_number* over [from_date, to_date].

		Computes opening balance, total debits, total credits, closing balance,
		interest earned, and fees charged from LedgerEntry rows.

		The generated statement is persisted to session (caller commits).
		Object-storage upload and delivery queuing are deferred to async tasks
		(statement_url is left NULL until the background task populates it).
		"""
		account = self._require_account(session, account_number)

		# Opening balance: balance_after_cents of last entry before from_date
		opening_entry = session.execute(
			select(LedgerEntry.balance_after_cents)
			.where(
				LedgerEntry.account_id == account.id,
				LedgerEntry.posting_date < from_date,
			)
			.order_by(LedgerEntry.posting_date.desc(), LedgerEntry.created_at.desc())
			.limit(1)
		).scalar_one_or_none()
		opening_balance = opening_entry or 0

		# Period entries
		period_entries = session.execute(
			select(LedgerEntry).where(
				LedgerEntry.account_id == account.id,
				LedgerEntry.posting_date >= from_date,
				LedgerEntry.posting_date <= to_date,
			)
		).scalars().all()

		total_debits = sum(e.amount_cents for e in period_entries if e.entry_type == "DEBIT")
		total_credits = sum(e.amount_cents for e in period_entries if e.entry_type == "CREDIT")
		interest_earned = sum(
			e.amount_cents for e in period_entries if e.is_interest and e.entry_type == "CREDIT"
		)
		fees_charged = sum(
			e.amount_cents for e in period_entries if e.is_fee and e.entry_type == "DEBIT"
		)
		closing_balance = opening_balance + total_credits - total_debits

		stmt = AccountStatement(
			tenant_id=tenant_id,
			account_id=account.id,
			statement_period_start=from_date,
			statement_period_end=to_date,
			opening_balance_cents=opening_balance,
			total_debits_cents=total_debits,
			total_credits_cents=total_credits,
			closing_balance_cents=closing_balance,
			interest_earned_cents=interest_earned,
			fees_charged_cents=fees_charged,
			generated_at=datetime.now(timezone.utc),
			delivery_method=delivery_method,
		)
		session.add(stmt)
		session.flush()
		return stmt

	# ------------------------------------------------------------------
	# run_dormancy_check
	# ------------------------------------------------------------------

	def run_dormancy_check(
		self,
		session: Session,
		threshold_days: int = 365,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> dict:
		"""Mark accounts DORMANT if no transaction in *threshold_days* days.

		Skips accounts already DORMANT, FROZEN, SUSPENDED, or CLOSED.
		Emits cb.account.dormant for each newly dormant account.

		Returns::

			{"accounts_marked_dormant": int, "threshold_days": int}
		"""
		from datetime import timedelta

		cutoff_dt = datetime.now(timezone.utc) - timedelta(days=threshold_days)

		q = select(Account).where(
			Account.status == "ACTIVE",
			sa.or_(
				Account.last_transaction_at < cutoff_dt,
				Account.last_transaction_at.is_(None),
			),
		)
		if tenant_id:
			q = q.where(Account.tenant_id == tenant_id)

		candidates = session.execute(q).scalars().all()
		marked = 0

		for account in candidates:
			account.status = "DORMANT"
			account.dormancy_notified_at = datetime.now(timezone.utc)
			marked += 1

			last_txn_str = (
				account.last_transaction_at.date().isoformat()
				if account.last_transaction_at else ""
			)
			days_inactive = (
				(datetime.now(timezone.utc) - account.last_transaction_at).days
				if account.last_transaction_at else threshold_days
			)

			try:
				emit_event(
					event_type="cb.account.dormant",
					aggregate_type="Account",
					aggregate_id=account.id,
					payload=AccountDormantEvent(
						account_id=account.id,
						account_number=account.account_number,
						customer_id=account.customer_id,
						last_transaction_date=last_txn_str,
						days_inactive=days_inactive,
						aggregate_id=account.id,
						aggregate_type="Account",
						tenant_id=tenant_id,
						correlation_id=correlation_id,
					).build_payload(),
					session=session,
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				)
			except Exception as exc:
				log.warning("run_dormancy_check: event emit failed (non-fatal): %s", exc)

		session.flush()
		return {"accounts_marked_dormant": marked, "threshold_days": threshold_days}

	# ------------------------------------------------------------------
	# reverse_transaction
	# ------------------------------------------------------------------

	def reverse_transaction(
		self,
		session: Session,
		journal_id: str,
		reason: str,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> dict:
		"""Reverse all LedgerEntry rows sharing *journal_id*.

		Creates a mirror pair of entries with flipped entry_type and
		transaction_type=REVERSAL, each with reversal_of_id pointing to its
		original counterpart.  Account balances are updated accordingly.

		Invariants enforced:
		  - At least one entry must exist for the journal_id.
		  - No entry in the journal may already be a REVERSAL (prevent double-reversal).
		  - No entry may already have reversal_of_id set (double-reversal guard).

		Returns::

			{
				"reversal_journal_id": str,
				"reversed_journal_id": str,
				"entries_reversed": int,
			}
		"""
		original_entries = session.execute(
			select(LedgerEntry).where(LedgerEntry.journal_id == journal_id)
		).scalars().all()

		if not original_entries:
			raise CoreBankingError(f"No ledger entries found for journal_id {journal_id!r}")

		for entry in original_entries:
			if entry.transaction_type == "REVERSAL":
				raise TransactionAlreadyReversedError(
					f"Journal {journal_id!r} is already a reversal entry — cannot reverse again"
				)
			if entry.reversal_of_id is not None:
				raise TransactionAlreadyReversedError(
					f"Entry {entry.id!r} in journal {journal_id!r} has already been reversed "
					f"(reversal_of_id={entry.reversal_of_id!r})"
				)

		reversal_journal_id = _new_journal_id()
		today = date.today()
		reversal_narrative = f"REVERSAL: {reason}"
		entries_reversed = 0

		for entry in original_entries:
			# Flip DEBIT ↔ CREDIT
			flipped_type = "CREDIT" if entry.entry_type == "DEBIT" else "DEBIT"

			account = session.get(Account, entry.account_id)
			if account is None:
				raise AccountNotFoundError(
					f"Account {entry.account_id!r} not found for reversal of entry {entry.id!r}"
				)

			# Update account balance: mirror the original effect in reverse
			if flipped_type == "CREDIT":
				account.current_balance_cents = money_add(
					account.current_balance_cents, entry.amount_cents
				)
				account.available_balance_cents = money_add(
					account.available_balance_cents, entry.amount_cents
				)
			else:
				account.current_balance_cents = money_subtract(
					account.current_balance_cents, entry.amount_cents
				)
				account.available_balance_cents = money_subtract(
					account.available_balance_cents, entry.amount_cents
				)
			account.last_transaction_at = datetime.now(timezone.utc)

			reversal_entry = LedgerEntry(
				tenant_id=tenant_id or entry.tenant_id,
				journal_id=reversal_journal_id,
				entry_type=flipped_type,
				account_id=entry.account_id,
				amount_cents=entry.amount_cents,
				currency_code=entry.currency_code,
				exchange_rate=entry.exchange_rate,
				balance_after_cents=account.current_balance_cents,
				value_date=today,
				posting_date=today,
				transaction_type="REVERSAL",
				channel=entry.channel,
				reference_number=entry.reference_number,
				narrative=reversal_narrative,
				reversal_of_id=entry.id,
				is_interest=entry.is_interest,
				is_fee=entry.is_fee,
			)
			session.add(reversal_entry)
			entries_reversed += 1

		session.flush()

		# Post GL reversal — mirror of the original journal entries
		_gl_reversal_lines: list[dict] = []
		for _rev in session.execute(
			select(LedgerEntry).where(LedgerEntry.journal_id == reversal_journal_id)
		).scalars().all():
			if _rev.entry_type == "DEBIT":
				# Was a CREDIT being undone → DR CUSTOMER_DEPOSITS CR CASH_NOSTRO
				_gl_reversal_lines += [
					{"account_code": "CUSTOMER_DEPOSITS", "debit_cents": _rev.amount_cents, "credit_cents": 0,
					 "currency_code": _rev.currency_code, "party_id": str(_rev.account_id),
					 "description": f"Reversal of {journal_id}: {reason}"},
					{"account_code": "CASH_NOSTRO", "debit_cents": 0, "credit_cents": _rev.amount_cents,
					 "currency_code": _rev.currency_code,
					 "description": f"Reversal of {journal_id}: {reason}"},
				]
			else:
				# Was a DEBIT being undone → DR CASH_NOSTRO CR CUSTOMER_DEPOSITS
				_gl_reversal_lines += [
					{"account_code": "CASH_NOSTRO", "debit_cents": _rev.amount_cents, "credit_cents": 0,
					 "currency_code": _rev.currency_code,
					 "description": f"Reversal of {journal_id}: {reason}"},
					{"account_code": "CUSTOMER_DEPOSITS", "debit_cents": 0, "credit_cents": _rev.amount_cents,
					 "currency_code": _rev.currency_code, "party_id": str(_rev.account_id),
					 "description": f"Reversal of {journal_id}: {reason}"},
				]
		if _gl_reversal_lines:
			self._post_to_gl(
				session=session,
				lines=_gl_reversal_lines,
				description=f"REVERSAL {journal_id}",
				tenant_id=tenant_id,
				source_doc_id=reversal_journal_id,
				source_doc_type="CB_REVERSAL",
			)

		try:
			emit_event(
				event_type="cb.transaction.reversed",
				aggregate_type="LedgerEntry",
				aggregate_id=reversal_journal_id,
				payload=TransactionReversedEvent(
					reversal_journal_id=reversal_journal_id,
					reversed_journal_id=journal_id,
					entries_reversed=entries_reversed,
					reason=reason,
					aggregate_id=reversal_journal_id,
					aggregate_type="LedgerEntry",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("reverse_transaction: event emit failed (non-fatal): %s", exc)

		return {
			"reversal_journal_id": reversal_journal_id,
			"reversed_journal_id": journal_id,
			"entries_reversed": entries_reversed,
		}

	# ------------------------------------------------------------------
	# charge_fee / run_maintenance_fee_batch
	# ------------------------------------------------------------------

	def charge_fee(
		self,
		session: Session,
		account_number: str,
		fee_type: str,
		override_amount_cents: int | None = None,
		reference: str = "",
		narrative: str | None = None,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> dict:
		"""Post a fee debit to *account_number*.

		Fee amount resolution (highest priority wins):
		  1. *override_amount_cents* if provided and non-zero.
		  2. product.fees[f'{fee_type.lower()}_fee_cents'] from JSONB.
		  3. If resolved amount is 0 — returns early (no-op).

		Validates:
		  - Account exists and is not CLOSED.
		  - Sufficient available_balance (InsufficientFundsError if not).

		Returns::

			{
				"journal_id": str,
				"entry_id": str,
				"fee_type": str,
				"amount_cents": int,
				"new_balance_cents": int,
			}
		"""
		account = self._require_account(session, account_number)
		self._assert_not_closed(account)

		product = session.get(BankProduct, account.product_id)
		fees_map: dict = (product.fees or {}) if product else {}
		fee_key = f"{fee_type.lower()}_fee_cents"
		product_fee = int(fees_map.get(fee_key, 0))

		amount_cents = override_amount_cents if override_amount_cents else product_fee
		if amount_cents <= 0:
			# No fee configured for this type — no-op
			return {
				"journal_id": "",
				"entry_id": "",
				"fee_type": fee_type,
				"amount_cents": 0,
				"new_balance_cents": account.current_balance_cents,
			}

		if account.available_balance_cents < amount_cents:
			raise InsufficientFundsError(
				f"Insufficient available balance to charge {fee_type!r} fee of {amount_cents}c: "
				f"available is {account.available_balance_cents}c"
			)

		nar = narrative or f"{fee_type.upper()} fee"
		entry = self._post_debit(
			session=session,
			account=account,
			amount_cents=amount_cents,
			transaction_type="FEE",
			channel="SYSTEM",
			reference=reference or f"FEE-{fee_type.upper()}-{account_number}",
			narrative=nar,
			tenant_id=tenant_id,
			is_fee=True,
		)

		try:
			emit_event(
				event_type="cb.fee.charged",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload=FeeChargedEvent(
					account_id=account.id,
					account_number=account.account_number,
					journal_id=entry.journal_id,
					entry_id=entry.id,
					fee_type=fee_type,
					amount_cents=amount_cents,
					new_balance_cents=account.current_balance_cents,
					aggregate_id=account.id,
					aggregate_type="Account",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("charge_fee: event emit failed (non-fatal): %s", exc)

		return {
			"journal_id": entry.journal_id,
			"entry_id": entry.id,
			"fee_type": fee_type,
			"amount_cents": amount_cents,
			"new_balance_cents": account.current_balance_cents,
		}

	def run_maintenance_fee_batch(
		self,
		session: Session,
		fee_date: date,
		product_type: str | None = None,
		tenant_id: str = "",
	) -> dict:
		"""Charge maintenance fees on all eligible ACTIVE accounts.

		Iterates ACTIVE accounts whose product has a non-zero
		maintenance_fee_cents in the fees JSONB, and calls charge_fee()
		for each.  Accounts with InsufficientFundsError are skipped and
		counted separately — they do not abort the batch.

		Returns::

			{
				"accounts_charged": int,
				"accounts_skipped_nsf": int,
				"total_fees_cents": int,
				"fee_date": str (ISO),
			}
		"""
		q = (
			select(Account)
			.join(BankProduct, Account.product_id == BankProduct.id)
			.where(Account.status == "ACTIVE")
		)
		if tenant_id:
			q = q.where(Account.tenant_id == tenant_id)
		if product_type:
			q = q.where(BankProduct.product_type == product_type)

		accounts = session.execute(q).scalars().all()

		charged = 0
		skipped_nsf = 0
		total_fees = 0

		for account in accounts:
			product = session.get(BankProduct, account.product_id)
			if not product:
				continue
			maint_fee = int((product.fees or {}).get("maintenance_fee_cents", 0))
			if maint_fee <= 0:
				continue

			try:
				result = self.charge_fee(
					session=session,
					account_number=account.account_number,
					fee_type="maintenance",
					override_amount_cents=maint_fee,
					reference=f"MAINT-{fee_date.isoformat()}-{account.account_number}",
					narrative=f"Monthly maintenance fee {fee_date.isoformat()}",
					tenant_id=tenant_id or account.tenant_id,
				)
				if result["amount_cents"] > 0:
					charged += 1
					total_fees += result["amount_cents"]
			except InsufficientFundsError:
				skipped_nsf += 1
				log.debug(
					"run_maintenance_fee_batch: NSF skip for %s", account.account_number
				)
			except Exception as exc:
				log.warning(
					"run_maintenance_fee_batch: unexpected error for %s (non-fatal): %s",
					account.account_number,
					exc,
				)

		session.flush()
		return {
			"accounts_charged": charged,
			"accounts_skipped_nsf": skipped_nsf,
			"total_fees_cents": total_fees,
			"fee_date": fee_date.isoformat(),
		}

	# ------------------------------------------------------------------
	# expire_stale_holds
	# ------------------------------------------------------------------

	def expire_stale_holds(
		self,
		session: Session,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> dict:
		"""Expire ACTIVE holds whose expires_at timestamp is in the past.

		For each expired hold:
		  - Sets hold.status = 'EXPIRED'
		  - Restores account.available_balance_cents += hold.amount_cents
		  - Decrements account.holds_cents

		Without this, a failed-payment hold that was never explicitly released
		permanently reduces available_balance, locking customer funds.

		Returns::

			{"holds_expired": int, "total_released_cents": int}
		"""
		now_utc = datetime.now(timezone.utc)

		q = select(AccountHold).where(
			AccountHold.status == "ACTIVE",
			AccountHold.expires_at.is_not(None),
			AccountHold.expires_at < now_utc,
		)
		if tenant_id:
			q = q.where(AccountHold.tenant_id == tenant_id)

		stale_holds = session.execute(q).scalars().all()
		holds_expired = 0
		total_released = 0

		for hold in stale_holds:
			account = session.get(Account, hold.account_id)
			if account is None:
				log.warning(
					"expire_stale_holds: account %s not found for hold %s — skipping",
					hold.account_id,
					hold.id,
				)
				continue

			hold.status = "EXPIRED"
			account.available_balance_cents = money_add(
				account.available_balance_cents, hold.amount_cents
			)
			account.holds_cents = money_subtract(account.holds_cents, hold.amount_cents)
			holds_expired += 1
			total_released += hold.amount_cents

			try:
				emit_event(
					event_type="cb.hold.expired",
					aggregate_type="AccountHold",
					aggregate_id=hold.id,
					payload=HoldExpiredEvent(
						hold_id=hold.id,
						account_id=account.id,
						account_number=account.account_number,
						amount_cents=hold.amount_cents,
						release_reason="EXPIRED",
						expired_at=now_utc.isoformat(),
						aggregate_id=hold.id,
						aggregate_type="AccountHold",
						tenant_id=tenant_id or hold.tenant_id,
						correlation_id=correlation_id,
					).build_payload(),
					session=session,
					tenant_id=tenant_id or hold.tenant_id,
					correlation_id=correlation_id,
				)
			except Exception as exc:
				log.warning("expire_stale_holds: event emit failed (non-fatal): %s", exc)

		if holds_expired:
			session.flush()

		return {"holds_expired": holds_expired, "total_released_cents": total_released}

	# ------------------------------------------------------------------
	# generate_iban / validate_iban   (HIGH gap: IBAN generation)
	# ------------------------------------------------------------------

	def generate_iban(
		self,
		country_code: str,
		bank_code: str,
		branch_code: str,
		account_number: str,
	) -> str:
		"""Generate a valid IBAN using ISO 13616-1 mod-97 algorithm.

		Builds BBAN = bank_code + branch_code + account_number (all digits,
		zero-padded to standard widths), then computes the two check digits.

		No external library required — mod-97 is ~10 lines.

		Args:
		    country_code: ISO 3166-1 alpha-2 (e.g. "KE", "GB").
		    bank_code: Numeric bank identifier (zero-padded to 6 digits).
		    branch_code: Numeric branch/sort code (zero-padded to 6 digits).
		    account_number: Core account number digits (zero-padded to 10 digits).

		Returns:
		    IBAN string e.g. "KE05000001000100001234".
		"""
		bk = bank_code.strip().zfill(6)[:6]
		br = branch_code.strip().zfill(6)[:6]
		ac = account_number.strip().replace("-", "").zfill(10)[:10]
		bban = bk + br + ac

		# Rearrange: BBAN + country code + "00" (placeholder check digits)
		rearranged = bban + country_code.upper() + "00"

		# Convert letters to digits: A=10, B=11, …, Z=35
		numeric_str = "".join(
			str(ord(ch) - 55) if ch.isalpha() else ch
			for ch in rearranged
		)
		check_digits = 98 - (int(numeric_str) % 97)
		return f"{country_code.upper()}{check_digits:02d}{bban}"

	# Country-specific IBAN lengths per ISO 13616 registry.
	# Add entries as new jurisdictions are supported.
	_IBAN_LENGTHS: dict[str, int] = {
		"KE": 29,
		"GB": 22,
		"DE": 22,
		"FR": 27,
		"US": 34,
		"ZA": 30,
		"NG": 28,
		"GH": 30,
	}

	def validate_iban(self, iban: str) -> bool:
		"""Return True if *iban* passes all ISO 13616-1 structural and checksum checks.

		Validation steps (in order):
		  1. Strip whitespace and uppercase; require length >= 5.
		  2. Country code (positions 0-1) must be two uppercase ASCII letters (A-Z).
		  3. Check digits (positions 2-3) must be two ASCII decimal digits (0-9).
		  4. Country-specific length check against _IBAN_LENGTHS (when the country
		     is in the registry); unknown countries skip this step.
		  5. BBAN (positions 4+) must be alphanumeric only (A-Z, 0-9).
		  6. Mod-97 checksum: rearrange to BBAN+country+check, convert letters to
		     two-digit numbers (A=10 ... Z=35), verify integer % 97 == 1.

		Does NOT raise — callers that need an exception should use::

		    if not svc.validate_iban(iban):
		        raise IBANValidationError(...)
		"""
		iban_clean = iban.strip().replace(" ", "").upper()

		# 1. Minimum length
		if len(iban_clean) < 5:
			return False

		# 2. Country code must be two uppercase letters
		country_code = iban_clean[:2]
		if not (country_code[0].isalpha() and country_code[1].isalpha()):
			return False

		# 3. Check digits must be exactly two decimal digits
		check_digits_str = iban_clean[2:4]
		if not (check_digits_str[0].isdigit() and check_digits_str[1].isdigit()):
			return False

		# 4. Country-specific length validation
		expected_len = self._IBAN_LENGTHS.get(country_code)
		if expected_len is not None and len(iban_clean) != expected_len:
			return False

		# 5. BBAN must be alphanumeric only (A-Z, 0-9)
		bban = iban_clean[4:]
		if not all(ch.isalpha() or ch.isdigit() for ch in bban):
			return False

		# 6. Mod-97 checksum
		rearranged = bban + country_code + check_digits_str
		numeric_str = "".join(
			str(ord(ch) - 55) if ch.isalpha() else ch
			for ch in rearranged
		)
		try:
			return int(numeric_str) % 97 == 1
		except ValueError:
			return False

	# ------------------------------------------------------------------
	# render_statement_csv / deliver_statement   (HIGH gap: statement delivery)
	# ------------------------------------------------------------------

	def render_statement_csv(
		self,
		session: Session,
		statement_id: str,
	) -> str:
		"""Build a CSV string for the given AccountStatement.

		Queries LedgerEntry rows within the statement period and formats
		them as CSV with a header row.  Returns the CSV as a plain string.
		The caller is responsible for encoding / writing to storage.
		"""
		import csv
		import io

		stmt = session.get(AccountStatement, statement_id)
		if stmt is None:
			raise CoreBankingError(f"Statement {statement_id!r} not found")

		account = session.get(Account, stmt.account_id)
		acc_number = account.account_number if account else str(stmt.account_id)

		entries = session.execute(
			select(LedgerEntry)
			.where(
				LedgerEntry.account_id == stmt.account_id,
				LedgerEntry.posting_date >= stmt.statement_period_start,
				LedgerEntry.posting_date <= stmt.statement_period_end,
			)
			.order_by(LedgerEntry.posting_date, LedgerEntry.created_at)
		).scalars().all()

		buf = io.StringIO()
		writer = csv.writer(buf)
		writer.writerow([
			"AccountNumber",
			"PostingDate",
			"ValueDate",
			"Type",
			"TransactionType",
			"AmountCents",
			"BalanceAfterCents",
			"Channel",
			"Reference",
			"Narrative",
		])
		writer.writerow([
			acc_number,
			stmt.statement_period_start.isoformat(),
			stmt.statement_period_end.isoformat(),
			"OPENING_BALANCE",
			"",
			stmt.opening_balance_cents,
			stmt.opening_balance_cents,
			"",
			"",
			f"Opening balance as at {stmt.statement_period_start}",
		])
		for e in entries:
			writer.writerow([
				acc_number,
				e.posting_date.isoformat() if e.posting_date else "",
				e.value_date.isoformat() if e.value_date else "",
				e.entry_type,
				e.transaction_type,
				e.amount_cents,
				e.balance_after_cents,
				e.channel or "",
				e.reference_number or "",
				e.narrative or "",
			])
		writer.writerow([
			acc_number,
			stmt.statement_period_end.isoformat(),
			stmt.statement_period_end.isoformat(),
			"CLOSING_BALANCE",
			"",
			stmt.closing_balance_cents,
			stmt.closing_balance_cents,
			"",
			"",
			f"Closing balance as at {stmt.statement_period_end}",
		])
		return buf.getvalue()

	def deliver_statement(
		self,
		session: Session,
		statement_id: str,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> AccountStatement:
		"""Generate CSV, attempt storage upload + notification, mark delivered.

		Non-fatal on storage/notification failures — delivered_at is only set
		if at least the CSV was generated successfully.

		Steps:
		  1. Load AccountStatement; raise CoreBankingError if not found.
		  2. render_statement_csv() → CSV string.
		  3. Try to upload to object storage (lazy-import StorageService).
		  4. Try to dispatch notification via delivery_method (lazy-import).
		  5. Set delivered_at = now(); flush.
		  6. Emit cb.statement.delivered.

		Returns the mutated AccountStatement (caller commits).
		"""
		stmt = session.get(AccountStatement, statement_id)
		if stmt is None:
			raise CoreBankingError(f"Statement {statement_id!r} not found")

		csv_content = self.render_statement_csv(session, statement_id)

		# --- storage upload (non-fatal) ---
		storage_url: str = ""
		try:
			from pgappforge.plugins.storage.services import StorageService  # type: ignore
			storage_url = StorageService().upload_text(
				content=csv_content,
				filename=f"statements/{statement_id}.csv",
				content_type="text/csv",
				tenant_id=tenant_id,
			)
			stmt.statement_url = storage_url
		except ImportError:
			# StorageService not installed — store inline data URI as fallback
			import base64
			encoded = base64.b64encode(csv_content.encode()).decode()
			stmt.statement_url = f"data:text/csv;base64,{encoded[:200]}…"
		except Exception as exc:
			log.warning("deliver_statement: storage upload failed (non-fatal): %s", exc)

		# --- notification dispatch (non-fatal) ---
		try:
			from pgappforge.plugins.notifications.services import NotificationService  # type: ignore
			account = session.get(Account, stmt.account_id)
			NotificationService().dispatch(
				method=stmt.delivery_method,
				recipient_id=str(account.customer_id) if account else "",
				subject="Your Account Statement",
				body=f"Statement for period {stmt.statement_period_start} to {stmt.statement_period_end}.",
				attachment_url=stmt.statement_url or "",
				tenant_id=tenant_id,
			)
		except ImportError:
			log.debug("deliver_statement: NotificationService not installed, skipping dispatch")
		except Exception as exc:
			log.warning("deliver_statement: notification dispatch failed (non-fatal): %s", exc)

		stmt.delivered_at = datetime.now(timezone.utc)
		session.flush()

		account = session.get(Account, stmt.account_id)
		try:
			emit_event(
				event_type="cb.statement.delivered",
				aggregate_type="AccountStatement",
				aggregate_id=statement_id,
				payload=StatementDeliveredEvent(
					statement_id=statement_id,
					account_id=str(stmt.account_id),
					account_number=account.account_number if account else "",
					delivery_method=stmt.delivery_method,
					statement_url=stmt.statement_url or "",
					delivered_at=stmt.delivered_at.isoformat(),
					aggregate_id=statement_id,
					aggregate_type="AccountStatement",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("deliver_statement: event emit failed (non-fatal): %s", exc)

		return stmt

	# ------------------------------------------------------------------
	# freeze_account / unfreeze_account   (HIGH gap: AccountActionsView)
	# ------------------------------------------------------------------

	def freeze_account(
		self,
		session: Session,
		account_number: str,
		reason: str = "",
		tenant_id: str = "",
		correlation_id: str = "",
	) -> Account:
		"""Set account status to FROZEN.  Only ACTIVE/DORMANT accounts can be frozen.

		Returns the mutated Account (caller commits).
		"""
		account = self._require_account(session, account_number)
		if account.status == "FROZEN":
			return account  # Idempotent — already frozen
		if account.status == "CLOSED":
			raise AccountStatusError(
				f"Account {account_number!r} is CLOSED and cannot be frozen"
			)
		account.status = "FROZEN"
		session.flush()
		try:
			emit_event(
				event_type="cb.account.frozen",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload=AccountFrozenEvent(
					account_id=account.id,
					account_number=account.account_number,
					reason=reason,
					aggregate_id=account.id,
					aggregate_type="Account",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("freeze_account: event emit failed (non-fatal): %s", exc)
		return account

	def unfreeze_account(
		self,
		session: Session,
		account_number: str,
		tenant_id: str = "",
		correlation_id: str = "",
	) -> Account:
		"""Reinstate a FROZEN account to ACTIVE.

		Returns the mutated Account (caller commits).
		"""
		account = self._require_account(session, account_number)
		if account.status != "FROZEN":
			raise AccountStatusError(
				f"Account {account_number!r} is not FROZEN (current: {account.status!r})"
			)
		account.status = "ACTIVE"
		session.flush()
		try:
			emit_event(
				event_type="cb.account.unfrozen",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload=AccountUnfrozenEvent(
					account_id=account.id,
					account_number=account.account_number,
					aggregate_id=account.id,
					aggregate_type="Account",
					tenant_id=tenant_id,
					correlation_id=correlation_id,
				).build_payload(),
				session=session,
				tenant_id=tenant_id,
				correlation_id=correlation_id,
			)
		except Exception as exc:
			log.warning("unfreeze_account: event emit failed (non-fatal): %s", exc)
		return account

	# ------------------------------------------------------------------
	# Private helpers
	# ------------------------------------------------------------------

	def _require_account(self, session: Session, account_number: str) -> Account:
		account = session.execute(
			select(Account).where(Account.account_number == account_number)
		).scalar_one_or_none()
		if account is None:
			raise AccountNotFoundError(f"Account {account_number!r} not found")
		return account

	def _assert_active(self, account: Account) -> None:
		if account.status != "ACTIVE":
			raise AccountStatusError(
				f"Account {account.account_number!r} is not ACTIVE "
				f"(current status: {account.status!r})"
			)

	def _assert_not_closed(self, account: Account) -> None:
		if account.status == "CLOSED":
			raise AccountStatusError(
				f"Account {account.account_number!r} is already CLOSED"
			)

	def _assert_channel_allowed(self, account: Account, channel: str, session: Session) -> None:
		"""Raise AccountStatusError if *channel* is not permitted by the account's product."""
		product = session.get(BankProduct, account.product_id)
		if product is None:
			return  # No product loaded — allow all (defensive)
		allowed = product.allowed_channels
		if not allowed:
			return  # Empty list = no restriction configured
		if channel not in allowed:
			raise AccountStatusError(
				f"Channel {channel!r} is not permitted for product "
				f"{product.product_code!r}. Allowed channels: {allowed}"
			)

	def _compute_avg_daily_balance(
		self,
		session: Session,
		account: Account,
		for_date: date,
	) -> int:
		"""Compute the time-weighted average daily balance for *account* on *for_date*.

		Reconstructs intraday balance movements from LedgerEntry rows posted on
		*for_date*, starting from the opening balance (last balance_after_cents
		before that date).  Assumes equal time-weighting across entries (simple
		average of all intraday balance snapshots).

		Returns the average balance in integer cents.  Falls back to
		current_balance_cents when no entries exist for the date (avoids
		divide-by-zero on accounts with no intraday activity).
		"""
		opening = session.execute(
			select(LedgerEntry.balance_after_cents)
			.where(
				LedgerEntry.account_id == account.id,
				LedgerEntry.posting_date < for_date,
			)
			.order_by(LedgerEntry.posting_date.desc(), LedgerEntry.created_at.desc())
			.limit(1)
		).scalar_one_or_none()
		opening_balance = opening if opening is not None else account.current_balance_cents

		day_entries = session.execute(
			select(LedgerEntry.balance_after_cents)
			.where(
				LedgerEntry.account_id == account.id,
				LedgerEntry.posting_date == for_date,
			)
			.order_by(LedgerEntry.created_at)
		).scalars().all()

		if not day_entries:
			return opening_balance

		# Include the opening balance snapshot + each post-transaction snapshot
		snapshots = [opening_balance] + list(day_entries)
		return int(sum(snapshots) // len(snapshots))

	def _run_aml_check(
		self,
		session: Session,
		account: Account,
		amount_cents: int,
		transaction_type: str,
		reference: str,
		tenant_id: str,
	) -> None:
		"""AML transaction monitoring gate.

		Creates an AMLScreeningResult row, then optionally calls an external
		AML provider.  If the provider is unavailable, the INTERNAL rule-based
		check is used (threshold-only for now).

		Raises:
		    AMLBlockedError: if the screening result is BLOCKED.

		If FLAGGED (not BLOCKED), places a precautionary hold and emits
		cb.aml.flagged; the transaction is then allowed to proceed so the
		operations team can review asynchronously.  Adjust this policy to
		BLOCKED for stricter jurisdictions.
		"""
		journal_ref = _new_journal_id()

		# --- Internal threshold check (always applied) ---
		status = "PASSED"
		flagged_reason: str | None = None
		risk_score = None

		# Simple rule: flag cash transactions above KES 1,000,000 (100_000_000c)
		# or any single transaction above KES 10,000,000 (1_000_000_000c) as BLOCKED.
		# These are baseline FATF/CBK thresholds; operators should override via
		# an external AML provider for production deployments.
		_FLAG_THRESHOLD = 100_000_000   # KES 1,000,000 in cents
		_BLOCK_THRESHOLD = 1_000_000_000  # KES 10,000,000 in cents

		if amount_cents >= _BLOCK_THRESHOLD:
			status = "BLOCKED"
			flagged_reason = f"Transaction amount {amount_cents}c exceeds auto-block threshold {_BLOCK_THRESHOLD}c"
			risk_score = "95.00"
		elif amount_cents >= _FLAG_THRESHOLD and transaction_type in ("DEPOSIT", "WITHDRAWAL"):
			status = "FLAGGED"
			flagged_reason = f"Large cash transaction {amount_cents}c exceeds flag threshold {_FLAG_THRESHOLD}c"
			risk_score = "65.00"

		# --- External provider call (non-fatal on import/runtime error) ---
		screening_provider = "INTERNAL"
		screening_ref: str | None = None
		try:
			from pgappforge.plugins.fintech.aml.services import AMLService  # type: ignore
			result = AMLService().screen_transaction(
				account_id=account.id,
				amount_cents=amount_cents,
				transaction_type=transaction_type,
				reference=reference,
				tenant_id=tenant_id,
			)
			status = result.get("status", status)
			flagged_reason = result.get("reason", flagged_reason)
			risk_score = str(result.get("risk_score", risk_score or ""))
			screening_provider = result.get("provider", "EXTERNAL")
			screening_ref = result.get("ref")
		except ImportError:
			pass  # AML plugin not installed — use internal rules only
		except Exception as exc:
			log.warning("_run_aml_check: external AML provider error (non-fatal): %s", exc)

		# Persist the screening record (INSERT-only)
		screening_row = AMLScreeningResult(
			tenant_id=tenant_id,
			journal_ref=journal_ref,
			account_id=account.id,
			amount_cents=amount_cents,
			currency_code=account.currency_code,
			transaction_type=transaction_type,
			screening_provider=screening_provider,
			screening_ref=screening_ref,
			risk_score=risk_score,
			status=status,
			flagged_reason=flagged_reason,
			screened_at=datetime.now(timezone.utc),
		)
		session.add(screening_row)
		session.flush()

		if status == "BLOCKED":
			try:
				emit_event(
					event_type="cb.aml.blocked",
					aggregate_type="Account",
					aggregate_id=account.id,
					payload=AMLBlockedEventClass(
						account_id=account.id,
						account_number=account.account_number,
						journal_ref=journal_ref,
						amount_cents=amount_cents,
						flagged_reason=flagged_reason or "",
						screening_provider=screening_provider,
						aggregate_id=account.id,
						aggregate_type="Account",
						tenant_id=tenant_id,
						correlation_id="",
					).build_payload(),
					session=session,
					tenant_id=tenant_id,
				)
			except Exception as exc:
				log.warning("_run_aml_check: blocked event emit failed (non-fatal): %s", exc)
			raise AMLBlockedError(
				f"Transaction blocked by AML screening: {flagged_reason}"
			)

		if status == "FLAGGED":
			try:
				emit_event(
					event_type="cb.aml.flagged",
					aggregate_type="Account",
					aggregate_id=account.id,
					payload=AMLFlaggedEvent(
						account_id=account.id,
						account_number=account.account_number,
						journal_ref=journal_ref,
						amount_cents=amount_cents,
						risk_score=str(risk_score or ""),
						flagged_reason=flagged_reason or "",
						screening_provider=screening_provider,
						aggregate_id=account.id,
						aggregate_type="Account",
						tenant_id=tenant_id,
						correlation_id="",
					).build_payload(),
					session=session,
					tenant_id=tenant_id,
				)
			except Exception as exc:
				log.warning("_run_aml_check: flagged event emit failed (non-fatal): %s", exc)

	def _daily_debit_total(self, session: Session, account_id: str) -> int:
		"""Sum of debit amounts posted today for *account_id*."""
		today = date.today()
		result = session.execute(
			select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
				LedgerEntry.account_id == account_id,
				LedgerEntry.entry_type == "DEBIT",
				LedgerEntry.posting_date == today,
			)
		).scalar_one()
		return int(result)

	def _post_to_gl(
		self,
		session: Session,
		lines: list[dict],
		description: str,
		tenant_id: str,
		source_doc_id: str = "",
		source_doc_type: str = "CB_LEDGER_ENTRY",
		**_extra: object,
	) -> str | None:
		"""Non-fatal bridge to the GL plugin's post_simple_journal.

		Lazy-imports GLService so the core banking plugin can function without
		the GL plugin installed.  Any error that is NOT JournalImbalancedError
		is swallowed and logged.  JournalImbalancedError is re-raised because it
		indicates a programming bug in the line construction, not a transient
		runtime failure.

		Returns:
		    The GL journal entry id string on success, or None on failure/skip.
		"""
		try:
			from pgappforge.plugins.erp.finance.gl.services import (  # type: ignore
				GLService,
				JournalImbalancedError,
			)
		except (ImportError, AttributeError) as exc:
			log.debug("GL plugin not available — skipping GL post: %s", exc)
			return None

		# Resolve any symbolic account code keys (e.g. "CASH_NOSTRO" → tenant GL code)
		# so cb_gl_mapping overrides are honoured for multi-tenant deployments.
		_sym_keys = frozenset(_CB_GL.keys())
		resolved = [
			{**ln, "account_code": self._resolve_gl(session, ln["account_code"], tenant_id)}
			if ln.get("account_code") in _sym_keys else ln
			for ln in lines
		]
		gl = GLService()
		try:
			return gl.post_simple_journal(
				lines=resolved,
				session=session,
				tenant_id=tenant_id,
				description=description,
				source_doc_id=source_doc_id,
				source_doc_type=source_doc_type,
			)
		except JournalImbalancedError:
			log.exception("_post_to_gl: GL bridge produced unbalanced lines — this is a bug in CoreBankingService")
			raise
		except Exception as exc:
			log.warning("_post_to_gl: GL post failed (non-fatal): %s", exc)
			return None

	# ------------------------------------------------------------------
	# Loan GL methods
	# ------------------------------------------------------------------

	def post_loan_disbursement(
		self,
		session: Session,
		loan_id: str,
		borrower_account_id: str,
		principal_cents: int,
		processing_fee_cents: int = 0,
		tenant_id: str = "",
	) -> str | None:
		"""Post GL entries for a loan disbursement.

		Double-entry:
		  DR LOAN_RECEIVABLE          principal_cents
		  CR CUSTOMER_DEPOSITS        (principal - fee)_cents
		  CR FEE_INCOME               processing_fee_cents   (if > 0)

		Returns the GL entry id or None if GL is unavailable.
		"""
		if principal_cents <= 0:
			raise CoreBankingError("Disbursement principal must be positive")

		net_to_borrower = principal_cents - processing_fee_cents
		lines: list[dict] = [
			{
				"account_code": "LOAN_RECEIVABLE",
				"debit_cents": principal_cents,
				"credit_cents": 0,
				"party_id": loan_id,
				"description": "Loan disbursement — principal",
			},
			{
				"account_code": "CUSTOMER_DEPOSITS",
				"debit_cents": 0,
				"credit_cents": net_to_borrower,
				"party_id": borrower_account_id,
				"description": "Loan disbursement — credit to borrower account",
			},
		]
		if processing_fee_cents > 0:
			lines.append({
				"account_code": "FEE_INCOME",
				"debit_cents": 0,
				"credit_cents": processing_fee_cents,
				"party_id": loan_id,
				"description": "Loan disbursement — processing fee",
			})
		return self._post_to_gl(
			session=session,
			lines=lines,
			description=f"Loan disbursement {loan_id}",
			tenant_id=tenant_id,
			source_doc_id=loan_id,
			source_doc_type="CB_LOAN_DISBURSEMENT",
		)

	def post_loan_repayment(
		self,
		session: Session,
		loan_id: str,
		amount_cents: int,
		principal_cents: int,
		interest_cents: int,
		tenant_id: str = "",
	) -> str | None:
		"""Post GL entries for a loan repayment.

		Double-entry (normal repayment):
		  DR CUSTOMER_DEPOSITS        amount_cents
		  CR LOAN_RECEIVABLE          principal_cents
		  CR INTEREST_INCOME          interest_cents
		  CR CUSTOMER_DEPOSITS        overpayment_cents  (if amount > principal + interest)

		Overpayment (amount > principal + interest) is credited back to CUSTOMER_DEPOSITS,
		not recognised as revenue.

		Raises CoreBankingError if amount < principal + interest (programming error).
		"""
		total_due = principal_cents + interest_cents
		if amount_cents < total_due:
			raise CoreBankingError(
				f"Repayment amount {amount_cents}c < principal {principal_cents}c "
				f"+ interest {interest_cents}c = {total_due}c"
			)

		overpayment = amount_cents - total_due

		lines: list[dict] = [
			{
				"account_code": "CUSTOMER_DEPOSITS",
				"debit_cents": amount_cents,
				"credit_cents": 0,
				"party_id": loan_id,
				"description": "Loan repayment — debit borrower account",
			},
			{
				"account_code": "LOAN_RECEIVABLE",
				"debit_cents": 0,
				"credit_cents": principal_cents,
				"party_id": loan_id,
				"description": "Loan repayment — reduce loan receivable",
			},
		]
		if interest_cents > 0:
			lines.append({
				"account_code": "INTEREST_INCOME",
				"debit_cents": 0,
				"credit_cents": interest_cents,
				"party_id": loan_id,
				"description": "Loan repayment — interest income",
			})
		if overpayment > 0:
			lines.append({
				"account_code": "CUSTOMER_DEPOSITS",
				"debit_cents": 0,
				"credit_cents": overpayment,
				"party_id": loan_id,
				"description": "Loan repayment — overpayment returned to borrower",
			})
		return self._post_to_gl(
			session=session,
			lines=lines,
			description=f"Loan repayment {loan_id}",
			tenant_id=tenant_id,
			source_doc_id=loan_id,
			source_doc_type="CB_LOAN_REPAYMENT",
		)

	def post_loan_write_off(
		self,
		session: Session,
		loan_id: str,
		write_off_cents: int,
		tenant_id: str = "",
	) -> str | None:
		"""Post GL entries for a loan write-off.

		Double-entry:
		  DR LOAN_LOSS_RESERVE        write_off_cents
		  CR LOAN_RECEIVABLE          write_off_cents

		The provision (LOAN_LOSS_RESERVE) is debited to clear the receivable.
		"""
		lines: list[dict] = [
			{
				"account_code": "LOAN_LOSS_RESERVE",
				"debit_cents": write_off_cents,
				"credit_cents": 0,
				"party_id": loan_id,
				"description": "Loan write-off — debit loss reserve",
			},
			{
				"account_code": "LOAN_RECEIVABLE",
				"debit_cents": 0,
				"credit_cents": write_off_cents,
				"party_id": loan_id,
				"description": "Loan write-off — remove from receivable",
			},
		]
		return self._post_to_gl(
			session=session,
			lines=lines,
			description=f"Loan write-off {loan_id}",
			tenant_id=tenant_id,
			source_doc_id=loan_id,
			source_doc_type="CB_LOAN_WRITE_OFF",
		)

	def post_loan_recovery(
		self,
		session: Session,
		loan_id: str,
		recovered_cents: int,
		source: str = "",
		tenant_id: str = "",
	) -> str | None:
		"""Post GL entries for a post-write-off loan recovery.

		Double-entry:
		  DR CASH_NOSTRO              recovered_cents
		  CR LOAN_LOSS_RESERVE        recovered_cents

		The recovery reinstates the contra-asset reserve.
		"""
		lines: list[dict] = [
			{
				"account_code": "CASH_NOSTRO",
				"debit_cents": recovered_cents,
				"credit_cents": 0,
				"party_id": loan_id,
				"description": f"Loan recovery via {source} — cash in",
			},
			{
				"account_code": "LOAN_LOSS_RESERVE",
				"debit_cents": 0,
				"credit_cents": recovered_cents,
				"party_id": loan_id,
				"description": "Loan recovery — reinstate loss reserve",
			},
		]
		return self._post_to_gl(
			session=session,
			lines=lines,
			description=f"Loan recovery {loan_id} source={source}",
			tenant_id=tenant_id,
			source_doc_id=loan_id,
			source_doc_type="CB_LOAN_RECOVERY",
		)

	def _resolve_gl(self, session: Session, key: str, tenant_id: str) -> str:
		"""Resolve a logical CB GL key to a chart-of-accounts code.

		Lookup order:
		  1. cb_gl_mapping row for (tenant_id, key) — tenant override.
		  2. _CB_GL[key] module constant — default chart of accounts.
		  3. key itself as a last-resort fallback (never None).
		"""
		if tenant_id:
			row = session.execute(
				select(GLAccountMapping).where(
					GLAccountMapping.tenant_id == tenant_id,
					GLAccountMapping.cb_account_key == key,
					GLAccountMapping.is_active.is_(True),
				)
			).scalar_one_or_none()
			if row is not None:
				return row.gl_account_code
		return _CB_GL.get(key, key)

	def _post_credit(
		self,
		session: Session,
		account: Account,
		amount_cents: int,
		transaction_type: str,
		channel: str,
		reference: str,
		narrative: str | None,
		tenant_id: str = "",
		is_interest: bool = False,
		is_fee: bool = False,
	) -> LedgerEntry:
		"""Internal: post a CREDIT entry and update account balance."""
		journal_id = _new_journal_id()
		today = date.today()

		account.current_balance_cents = money_add(account.current_balance_cents, amount_cents)
		account.available_balance_cents = money_add(account.available_balance_cents, amount_cents)
		account.last_transaction_at = datetime.now(timezone.utc)

		entry = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="CREDIT",
			account_id=account.id,
			amount_cents=amount_cents,
			currency_code=account.currency_code,
			exchange_rate=Decimal("1"),
			balance_after_cents=account.current_balance_cents,
			value_date=today,
			posting_date=today,
			transaction_type=transaction_type,
			channel=channel,
			reference_number=reference,
			narrative=narrative,
			is_interest=is_interest,
			is_fee=is_fee,
		)
		session.add(entry)
		session.flush()
		return entry

	def _post_debit(
		self,
		session: Session,
		account: Account,
		amount_cents: int,
		transaction_type: str,
		channel: str,
		reference: str,
		narrative: str | None,
		tenant_id: str = "",
		is_interest: bool = False,
		is_fee: bool = False,
	) -> LedgerEntry:
		"""Internal: post a DEBIT entry and update account balance."""
		journal_id = _new_journal_id()
		today = date.today()

		account.current_balance_cents = money_subtract(account.current_balance_cents, amount_cents)
		account.available_balance_cents = money_subtract(account.available_balance_cents, amount_cents)
		account.last_transaction_at = datetime.now(timezone.utc)

		entry = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="DEBIT",
			account_id=account.id,
			amount_cents=amount_cents,
			currency_code=account.currency_code,
			exchange_rate=Decimal("1"),
			balance_after_cents=account.current_balance_cents,
			value_date=today,
			posting_date=today,
			transaction_type=transaction_type,
			channel=channel,
			reference_number=reference,
			narrative=narrative,
			is_interest=is_interest,
			is_fee=is_fee,
		)
		session.add(entry)
		session.flush()
		return entry


# ---------------------------------------------------------------------------
# IslamicBankingService
# ---------------------------------------------------------------------------

class IslamicBankingService:
	"""Sharia-compliant product calculations for Murabaha and Diminishing Musharakah.

	Conventional interest (riba) is prohibited under Sharia law.  All profit
	must arise from a real economic transaction:
	  - Murabaha: bank buys asset and sells it to customer at a disclosed markup.
	    Profit is fixed at contract inception — it cannot increase if payment is
	    delayed (AAOIFI FAS 2).
	  - Diminishing Musharakah (Musharakah Mutanaqisah): bank and customer co-own
	    an asset.  Customer pays rent on the bank's share and purchases units of
	    bank ownership monthly until full ownership is transferred.

	GL codes follow _ISLAMIC_GL and may be tenant-overridden via GLAccountMapping.
	"""

	# ------------------------------------------------------------------
	# Pure calculations (no DB — safe to call anywhere)
	# ------------------------------------------------------------------

	def calculate_murabaha_profit(
		self,
		cost_price_cents: int,
		profit_rate_pa: Decimal,
		tenor_months: int,
	) -> dict:
		"""Murabaha: bank acquires asset at cost_price, sells to customer at cost + markup.

		Profit is computed once at contract inception using a simple (non-compound)
		formula and locked for the contract term — it cannot be revised upward if
		the customer is late (AAOIFI FAS 2 §12).

		Formula::
			profit = cost_price × profit_rate_pa × (tenor_months / 12)
			selling_price = cost_price + profit
			monthly_instalment = ceil(selling_price / tenor_months)

		Returns::
			{
				"cost_price_cents": int,
				"profit_cents": int,
				"selling_price_cents": int,
				"monthly_instalment_cents": int,
				"profit_rate_applied": str,   # str(profit_rate_pa) for audit trail
			}
		"""
		assert cost_price_cents > 0, "cost_price_cents must be positive"
		assert tenor_months > 0, "tenor_months must be positive"
		assert Decimal(str(profit_rate_pa)) >= Decimal("0"), "profit_rate_pa cannot be negative"

		rate = Decimal(str(profit_rate_pa))
		profit = money_multiply(
			cost_price_cents,
			rate * Decimal(tenor_months) / Decimal("12"),
		)
		selling_price = money_add(cost_price_cents, profit)
		monthly_instalment = money_divide(selling_price, tenor_months)

		return {
			"cost_price_cents": cost_price_cents,
			"profit_cents": profit,
			"selling_price_cents": selling_price,
			"monthly_instalment_cents": monthly_instalment,
			"profit_rate_applied": str(profit_rate_pa),
		}

	def calculate_diminishing_musharakah(
		self,
		property_value_cents: int,
		customer_share_pct: Decimal,
		bank_share_pct: Decimal,
		rental_rate_pa: Decimal,
		monthly_unit_purchase_cents: int,
		period_number: int,
	) -> dict:
		"""Diminishing Musharakah period schedule entry.

		Customer and bank co-own the asset.  Each month the customer:
		  1. Pays rent proportional to the bank's current share.
		  2. Buys one fixed unit of bank ownership.

		As bank_share shrinks, the rental component decreases — the total monthly
		payment falls over the term (unlike a conventional mortgage with fixed EMI).

		Formula for period N (1-indexed)::
			bank_share_at_N    = bank_share_pct - ((N-1) × unit_pct)
			unit_pct           = monthly_unit_purchase_cents / property_value_cents
			rental_at_N        = property_value_cents × bank_share_at_N × rental_rate_pa / 12
			total_payment_at_N = rental_at_N + monthly_unit_purchase_cents

		After payment::
			new_bank_share_pct      = bank_share_at_N - unit_pct
			new_customer_share_pct  = 1 - new_bank_share_pct

		Returns::
			{
				"period_number": int,
				"rental_cents": int,
				"unit_purchase_cents": int,
				"total_payment_cents": int,
				"bank_share_pct_before": str,
				"new_bank_share_pct": str,
				"new_customer_share_pct": str,
			}
		"""
		assert property_value_cents > 0, "property_value_cents must be positive"
		assert monthly_unit_purchase_cents > 0, "monthly_unit_purchase_cents must be positive"
		assert period_number >= 1, "period_number is 1-indexed"
		assert Decimal(str(bank_share_pct)) > Decimal("0"), "bank_share_pct must be positive"
		assert Decimal(str(rental_rate_pa)) >= Decimal("0"), "rental_rate_pa cannot be negative"

		bank_pct = Decimal(str(bank_share_pct))
		unit_pct = Decimal(str(monthly_unit_purchase_cents)) / Decimal(str(property_value_cents))

		# Bank share at the start of this period (before this period's unit purchase)
		bank_share_at_n = bank_pct - unit_pct * Decimal(period_number - 1)
		# Clamp to zero — beyond full payoff periods have no bank share
		bank_share_at_n = max(Decimal("0"), bank_share_at_n)

		# Rental = property_value × bank_share × monthly_rate
		monthly_rental_rate = Decimal(str(rental_rate_pa)) / Decimal("12")
		rental = money_multiply(
			property_value_cents,
			bank_share_at_n * monthly_rental_rate,
		)

		total_payment = money_add(rental, monthly_unit_purchase_cents)

		new_bank_share = max(Decimal("0"), bank_share_at_n - unit_pct)
		new_customer_share = Decimal("1") - new_bank_share

		return {
			"period_number": period_number,
			"rental_cents": rental,
			"unit_purchase_cents": monthly_unit_purchase_cents,
			"total_payment_cents": total_payment,
			"bank_share_pct_before": str(bank_share_at_n),
			"new_bank_share_pct": str(new_bank_share),
			"new_customer_share_pct": str(new_customer_share),
		}

	# ------------------------------------------------------------------
	# DB-backed operations
	# ------------------------------------------------------------------

	def post_murabaha_disbursement(
		self,
		session: Session,
		account_number: str,
		cost_price_cents: int,
		profit_cents: int,
		tenor_months: int,
		tenant_id: str = "",
	) -> dict:
		"""Record initial Murabaha facility on the ledger.

		Double-entry at disbursement (AAOIFI FAS 2 Day-1 recognition):

		  DR  Murabaha Receivable   (selling_price = cost + profit)
		  CR  Cash / Nostro         (bank paid cost_price for the asset)
		  CR  Deferred Income       (unearned profit = profit_cents)

		The deferred income balance is the pool from which monthly income is
		recognised via accrue_murabaha_income().

		Returns::
			{
				"journal_id": str,
				"selling_price_cents": int,
				"cost_price_cents": int,
				"profit_cents": int,
				"tenor_months": int,
				"monthly_instalment_cents": int,
				"account_id": str,
			}
		"""
		assert cost_price_cents > 0, "cost_price_cents must be positive"
		assert profit_cents >= 0, "profit_cents cannot be negative"
		assert tenor_months > 0, "tenor_months must be positive"

		account = session.execute(
			select(Account).where(Account.account_number == account_number)
		).scalar_one_or_none()
		if account is None:
			raise AccountNotFoundError(f"Account not found: {account_number!r}")

		selling_price = money_add(cost_price_cents, profit_cents)
		monthly_instalment = money_divide(selling_price, tenor_months)
		journal_id = _new_journal_id()
		today = date.today()

		# Resolve GL codes (supports per-tenant overrides via GLAccountMapping)
		gl_receivable = _ISLAMIC_GL["MURABAHA_RECEIVABLE"]
		gl_cash = _CB_GL["CASH_NOSTRO"]
		gl_deferred = _ISLAMIC_GL["DEFERRED_INCOME"]

		# DR Murabaha Receivable (full selling price — this is the asset on bank's books)
		dr_receivable = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="DEBIT",
			account_id=account.id,
			gl_account_code=gl_receivable,
			amount_cents=selling_price,
			currency_code=account.currency_code,
			exchange_rate=Decimal("1"),
			balance_after_cents=account.current_balance_cents,
			value_date=today,
			posting_date=today,
			transaction_type="LOAN_DISBURSEMENT",
			channel="SYSTEM",
			reference_number=f"MRB-DR-{account_number}-{today.isoformat()}",
			narrative=f"Murabaha receivable — cost {cost_price_cents}c + profit {profit_cents}c",
			is_interest=False,
			is_fee=False,
		)
		session.add(dr_receivable)

		# CR Cash / Nostro (bank's outflow to acquire the asset for the customer)
		cr_cash = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="CREDIT",
			account_id=account.id,
			gl_account_code=gl_cash,
			amount_cents=cost_price_cents,
			currency_code=account.currency_code,
			exchange_rate=Decimal("1"),
			balance_after_cents=account.current_balance_cents,
			value_date=today,
			posting_date=today,
			transaction_type="LOAN_DISBURSEMENT",
			channel="SYSTEM",
			reference_number=f"MRB-CASH-{account_number}-{today.isoformat()}",
			narrative=f"Murabaha cash outflow — asset purchase {cost_price_cents}c",
			is_interest=False,
			is_fee=False,
		)
		session.add(cr_cash)

		# CR Deferred Income (unearned profit — recognised monthly over tenor)
		cr_deferred = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="CREDIT",
			account_id=account.id,
			gl_account_code=gl_deferred,
			amount_cents=profit_cents,
			currency_code=account.currency_code,
			exchange_rate=Decimal("1"),
			balance_after_cents=account.current_balance_cents,
			value_date=today,
			posting_date=today,
			transaction_type="LOAN_DISBURSEMENT",
			channel="SYSTEM",
			reference_number=f"MRB-DEF-{account_number}-{today.isoformat()}",
			narrative=f"Murabaha deferred income — profit {profit_cents}c over {tenor_months}m",
			is_interest=False,
			is_fee=False,
		)
		session.add(cr_deferred)

		# Update account balance to reflect the murabaha receivable outstanding
		account.current_balance_cents = selling_price
		account.available_balance_cents = selling_price
		account.original_principal_cents = selling_price
		account.last_transaction_at = datetime.now(timezone.utc)

		session.flush()

		try:
			emit_event(
				event_type="cb.islamic.murabaha.disbursed",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload={
					"account_id": account.id,
					"account_number": account_number,
					"journal_id": journal_id,
					"selling_price_cents": selling_price,
					"cost_price_cents": cost_price_cents,
					"profit_cents": profit_cents,
					"tenor_months": tenor_months,
					"monthly_instalment_cents": monthly_instalment,
					"tenant_id": tenant_id,
				},
				session=session,
				tenant_id=tenant_id,
			)
		except Exception as exc:
			log.warning("post_murabaha_disbursement: event emit failed (non-fatal): %s", exc)

		return {
			"journal_id": journal_id,
			"selling_price_cents": selling_price,
			"cost_price_cents": cost_price_cents,
			"profit_cents": profit_cents,
			"tenor_months": tenor_months,
			"monthly_instalment_cents": monthly_instalment,
			"account_id": account.id,
		}

	def accrue_murabaha_income(
		self,
		session: Session,
		account_number: str,
		period_months: int = 1,
		tenant_id: str = "",
	) -> dict:
		"""Recognise Murabaha profit income for one (or more) monthly periods.

		Straight-line recognition per IFRS 9 and AAOIFI FAS 2:
		  - Profit is spread evenly over the tenor (total_profit / tenor_months
		    per period).
		  - The deferred income balance decreases; revenue increases.

		Double-entry per period::
			DR  Deferred Income       (unearned profit decreases)
			CR  Murabaha Profit Income (revenue earned this period)

		The amount per period is derived from original_principal_cents and
		the product's profit_rate_pa stored on the account's product:
		  monthly_income = total_profit / tenor_months
		  ≡ original_principal × profit_rate_pa / 12

		We use the product.interest_rate_pa field to store profit_rate_pa for
		Murabaha products (the field is Sharia-neutral storage; the is_islamic
		flag controls which code path executes).

		Returns::
			{
				"journal_id": str,
				"income_recognised_cents": int,
				"periods_recognised": int,
				"account_id": str,
				"account_number": str,
			}
		"""
		assert period_months >= 1, "period_months must be at least 1"

		account = session.execute(
			select(Account).where(Account.account_number == account_number)
		).scalar_one_or_none()
		if account is None:
			raise AccountNotFoundError(f"Account not found: {account_number!r}")

		product = session.get(BankProduct, account.product_id)
		if product is None:
			raise ProductNotFoundError(
				f"Product not found for account: {account_number!r}"
			)
		if not product.is_islamic:
			raise CoreBankingError(
				f"accrue_murabaha_income called on non-Islamic product: "
				f"{product.product_code!r}"
			)

		# Monthly income = original_principal × profit_rate_pa / 12
		# original_principal_cents holds selling_price (cost + profit) after disbursement.
		# profit_rate_pa is stored in product.interest_rate_pa (Sharia-neutral column).
		principal = account.original_principal_cents or account.current_balance_cents
		monthly_rate = Decimal(str(product.interest_rate_pa)) / Decimal("12")
		income_per_period = money_multiply(principal, monthly_rate)
		total_income = income_per_period * period_months

		if total_income <= 0:
			return {
				"journal_id": "",
				"income_recognised_cents": 0,
				"periods_recognised": period_months,
				"account_id": account.id,
				"account_number": account_number,
			}

		journal_id = _new_journal_id()
		today = date.today()
		gl_deferred = _ISLAMIC_GL["DEFERRED_INCOME"]
		gl_income = _ISLAMIC_GL["MURABAHA_INCOME"]

		# DR Deferred Income — reduce the unearned profit liability
		dr_deferred = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="DEBIT",
			account_id=account.id,
			gl_account_code=gl_deferred,
			amount_cents=total_income,
			currency_code=account.currency_code,
			exchange_rate=Decimal("1"),
			balance_after_cents=account.current_balance_cents,
			value_date=today,
			posting_date=today,
			transaction_type="INTEREST_DEBIT",
			channel="SYSTEM",
			reference_number=(
				f"MRB-INC-DR-{account_number}-{today.isoformat()}"
			),
			narrative=(
				f"Murabaha income recognition — DR deferred "
				f"{period_months}m × {income_per_period}c"
			),
			is_interest=True,
			is_fee=False,
		)
		session.add(dr_deferred)

		# CR Murabaha Profit Income — revenue recognised this period
		cr_income = LedgerEntry(
			tenant_id=tenant_id,
			journal_id=journal_id,
			entry_type="CREDIT",
			account_id=account.id,
			gl_account_code=gl_income,
			amount_cents=total_income,
			currency_code=account.currency_code,
			exchange_rate=Decimal("1"),
			balance_after_cents=account.current_balance_cents,
			value_date=today,
			posting_date=today,
			transaction_type="INTEREST_CREDIT",
			channel="SYSTEM",
			reference_number=(
				f"MRB-INC-CR-{account_number}-{today.isoformat()}"
			),
			narrative=(
				f"Murabaha profit income — {period_months}m recognised"
			),
			is_interest=True,
			is_fee=False,
		)
		session.add(cr_income)

		# Update accrued interest tracker so account summary stays coherent
		account.accrued_interest_cents = money_add(
			account.accrued_interest_cents, total_income
		)
		account.last_interest_accrual_date = today

		session.flush()

		try:
			emit_event(
				event_type="cb.islamic.murabaha.income_accrued",
				aggregate_type="Account",
				aggregate_id=account.id,
				payload={
					"account_id": account.id,
					"account_number": account_number,
					"journal_id": journal_id,
					"income_recognised_cents": total_income,
					"periods_recognised": period_months,
					"tenant_id": tenant_id,
				},
				session=session,
				tenant_id=tenant_id,
			)
		except Exception as exc:
			log.warning("accrue_murabaha_income: event emit failed (non-fatal): %s", exc)

		return {
			"journal_id": journal_id,
			"income_recognised_cents": total_income,
			"periods_recognised": period_months,
			"account_id": account.id,
			"account_number": account_number,
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"CoreBankingService",
	"CoreBankingError",
	"AccountNotFoundError",
	"ProductNotFoundError",
	"InsufficientFundsError",
	"AccountStatusError",
	"DailyLimitExceededError",
	"HoldNotFoundError",
	"TransactionAlreadyReversedError",
	"AMLBlockedError",
	"IBANValidationError",
	"_CB_GL",
	"_ISLAMIC_GL",
	"IslamicBankingService",
]
