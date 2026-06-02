"""
pgappforge/plugins/erp/finance/treasury/services.py

TreasuryService — stateless business logic for Treasury Management.

All amounts in integer cents. Decimal arithmetic for FX rates. No float.

Public API
----------
  create_bank_account(details, session)             -> BankAccount
  book_fx_deal(details, session)                    -> FXDeal
  settle_fx_deal(deal_id, session)                  -> FXDeal
  run_bank_reconciliation(bank_account_id, statement_id, session) -> dict
  cash_flow_forecast(bank_account_id, days_ahead, session) -> list[dict]
  mark_to_market_hedges(session, tenant_id)         -> list[dict]
  get_cash_position(bank_account_id, position_date, session) -> CashPosition | None
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TreasuryServiceError(Exception):
	"""Base Treasury service error."""


class BankAccountNotFoundError(TreasuryServiceError):
	pass


class FXDealNotFoundError(TreasuryServiceError):
	pass


class FXDealStatusError(TreasuryServiceError):
	pass


# ---------------------------------------------------------------------------
# Input DTOs
# ---------------------------------------------------------------------------

@dataclass
class BankAccountDetails:
	tenant_id: str
	account_number: str
	bank_name: str
	currency_code: str
	gl_account: str
	account_type: str = "CURRENT"
	bank_bic: str | None = None
	iban: str | None = None
	overdraft_limit_cents: int | None = None
	is_default: bool = False
	metadata: dict[str, Any] | None = None


@dataclass
class FXDealDetails:
	tenant_id: str
	deal_type: str       # SPOT | FORWARD | SWAP
	buy_currency: str
	sell_currency: str
	buy_amount_cents: int
	sell_amount_cents: int
	contracted_rate: Decimal
	settlement_date: date
	counterparty_id: str | None = None
	buy_bank_account_id: str | None = None
	sell_bank_account_id: str | None = None
	hedge_designation: str = "NONE"
	hedged_item_id: str | None = None
	hedged_item_type: str | None = None
	deal_reference: str | None = None
	notes: str | None = None


# ---------------------------------------------------------------------------
# TreasuryService
# ---------------------------------------------------------------------------

class TreasuryService:
	"""Stateless Treasury service. Caller owns session transactions."""

	# ------------------------------------------------------------------ #
	# Bank Account
	# ------------------------------------------------------------------ #

	def create_bank_account(self, details: BankAccountDetails, session: Any) -> Any:
		"""Register a new bank account. Emits BankAccountCreatedEvent."""
		from pgappforge.plugins.erp.finance.treasury.models import BankAccount
		from pgappforge.plugins.erp.finance.treasury.events import BankAccountCreatedEvent, emit_event

		assert details.account_number, "account_number required"
		assert details.gl_account, "gl_account required"
		assert details.account_type in ("CURRENT", "SAVINGS", "OVERDRAFT"), \
			f"invalid account_type: {details.account_type!r}"

		acct = BankAccount(
			tenant_id=details.tenant_id,
			account_number=details.account_number,
			bank_name=details.bank_name,
			bank_bic=details.bank_bic,
			iban=details.iban,
			currency_code=details.currency_code.upper(),
			account_type=details.account_type,
			gl_account=details.gl_account,
			balance_cents=0,
			available_balance_cents=0,
			overdraft_limit_cents=details.overdraft_limit_cents,
			is_default=details.is_default,
			metadata_=details.metadata or {},
		)
		session.add(acct)
		session.flush()

		emit_event(
			BankAccountCreatedEvent(
				aggregate_id=acct.id,
				aggregate_type="BankAccount",
				tenant_id=details.tenant_id,
				bank_account_id=acct.id,
				account_number=acct.account_number,
				currency_code=acct.currency_code,
				bank_name=acct.bank_name,
			),
			session,
		)
		log.info("Created bank account %r at %r", acct.account_number, acct.bank_name)
		return acct

	# ------------------------------------------------------------------ #
	# FX Deal
	# ------------------------------------------------------------------ #

	def book_fx_deal(self, details: FXDealDetails, session: Any) -> Any:
		"""Book a new FX deal. Emits FXDealBookedEvent."""
		from pgappforge.plugins.erp.finance.treasury.models import FXDeal
		from pgappforge.plugins.erp.finance.treasury.events import FXDealBookedEvent, emit_event

		assert details.buy_amount_cents > 0, "buy_amount_cents must be positive"
		assert details.sell_amount_cents > 0, "sell_amount_cents must be positive"
		assert details.contracted_rate > 0, "contracted_rate must be positive"
		assert details.deal_type in ("SPOT", "FORWARD", "SWAP"), \
			f"invalid deal_type: {details.deal_type!r}"
		assert details.hedge_designation in ("FAIR_VALUE", "CASH_FLOW", "NET_INVESTMENT", "NONE"), \
			f"invalid hedge_designation: {details.hedge_designation!r}"

		ref = details.deal_reference or self._generate_deal_reference(session)

		deal = FXDeal(
			tenant_id=details.tenant_id,
			deal_reference=ref,
			deal_type=details.deal_type,
			buy_currency=details.buy_currency.upper(),
			sell_currency=details.sell_currency.upper(),
			buy_amount_cents=details.buy_amount_cents,
			sell_amount_cents=details.sell_amount_cents,
			contracted_rate=details.contracted_rate,
			settlement_date=details.settlement_date,
			counterparty_id=details.counterparty_id,
			buy_bank_account_id=details.buy_bank_account_id,
			sell_bank_account_id=details.sell_bank_account_id,
			hedge_designation=details.hedge_designation,
			hedged_item_id=details.hedged_item_id,
			hedged_item_type=details.hedged_item_type,
			status="OPEN",
			notes=details.notes,
		)
		session.add(deal)
		session.flush()

		emit_event(
			FXDealBookedEvent(
				aggregate_id=deal.id,
				aggregate_type="FXDeal",
				tenant_id=details.tenant_id,
				deal_id=deal.id,
				deal_reference=ref,
				deal_type=details.deal_type,
				buy_currency=details.buy_currency.upper(),
				sell_currency=details.sell_currency.upper(),
				buy_amount_cents=details.buy_amount_cents,
				sell_amount_cents=details.sell_amount_cents,
				contracted_rate=str(details.contracted_rate),
				settlement_date=str(details.settlement_date),
				hedge_designation=details.hedge_designation,
			),
			session,
		)
		log.info("FX deal booked %r %s->%s rate=%s", ref, details.sell_currency, details.buy_currency, details.contracted_rate)
		return deal

	def settle_fx_deal(self, deal_id: str, session: Any) -> Any:
		"""Mark an OPEN FX deal as SETTLED. Emits FXDealSettledEvent."""
		from pgappforge.plugins.erp.finance.treasury.models import FXDeal
		from pgappforge.plugins.erp.finance.treasury.events import FXDealSettledEvent, emit_event

		deal = session.get(FXDeal, deal_id)
		if deal is None:
			raise FXDealNotFoundError(f"FXDeal {deal_id!r} not found")
		if deal.status != "OPEN":
			raise FXDealStatusError(f"FXDeal {deal.deal_reference!r} is {deal.status!r}, not OPEN")

		deal.status = "SETTLED"
		deal.updated_at = datetime.now(timezone.utc)

		emit_event(
			FXDealSettledEvent(
				aggregate_id=deal_id,
				aggregate_type="FXDeal",
				tenant_id=deal.tenant_id,
				deal_id=deal_id,
				deal_reference=deal.deal_reference,
				settlement_date=str(deal.settlement_date),
				buy_amount_cents=deal.buy_amount_cents,
				sell_amount_cents=deal.sell_amount_cents,
			),
			session,
		)
		log.info("FX deal settled %r", deal.deal_reference)
		return deal

	# ------------------------------------------------------------------ #
	# Bank Reconciliation
	# ------------------------------------------------------------------ #

	def run_bank_reconciliation(
		self,
		bank_account_id: str,
		statement_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Auto-reconcile statement lines against book entries.

		Matching strategy (applied in order, stops at first match):
		1. Exact amount + bank_reference match against book payments/receipts.
		2. Exact amount + date proximity (±2 business days).
		3. Unmatched lines flagged as EXCEPTION for manual review.

		Returns summary dict: matched, unmatched, exception counts.

		Note: This is a simplified matching engine. Production implementations
		should integrate with the AP/AR modules for document-level matching.
		"""
		from pgappforge.plugins.erp.finance.treasury.models import (
			BankAccount, BankStatement, BankStatementLine,
		)
		from pgappforge.plugins.erp.finance.treasury.events import (
			BankReconciliationDoneEvent, emit_event,
		)

		account = session.get(BankAccount, bank_account_id)
		if account is None:
			raise BankAccountNotFoundError(f"BankAccount {bank_account_id!r} not found")

		statement = session.get(BankStatement, statement_id)
		if statement is None or statement.bank_account_id != bank_account_id:
			raise TreasuryServiceError("Statement not found or does not belong to this account")
		if statement.status == "RECONCILED":
			raise TreasuryServiceError("Statement is already reconciled")

		lines = session.execute(
			sa.select(BankStatementLine)
			.where(BankStatementLine.statement_id == statement_id)
			.where(BankStatementLine.match_status == "UNMATCHED")
		).scalars().all()

		matched = 0
		exceptions = 0

		for line in lines:
			# Simplified: flag all unmatched as EXCEPTION in this demo
			# A real implementation queries AP/AR payment tables by amount + reference
			matched_doc = self._find_matching_document(line, account, session)
			if matched_doc:
				line.match_status = "MATCHED"
				line.matched_document_type = matched_doc.get("type")
				line.matched_document_id = matched_doc.get("id")
				line.matched_at = datetime.now(timezone.utc)
				matched += 1
			else:
				line.match_status = "EXCEPTION"
				line.exception_reason = "No matching book entry found"
				exceptions += 1

		if exceptions == 0:
			statement.status = "RECONCILED"
			account.last_reconciled_date = statement.statement_date

		session.flush()

		emit_event(
			BankReconciliationDoneEvent(
				aggregate_id=statement_id,
				aggregate_type="BankStatement",
				tenant_id=account.tenant_id,
				bank_account_id=bank_account_id,
				statement_id=statement_id,
				statement_date=str(statement.statement_date),
				matched_lines=matched,
				exception_lines=exceptions,
			),
			session,
		)
		log.info(
			"Reconciliation done: account=%r stmt=%r matched=%d exceptions=%d",
			bank_account_id, statement_id, matched, exceptions,
		)
		return {
			"statement_id": statement_id,
			"total_lines": len(lines),
			"matched": matched,
			"exceptions": exceptions,
			"status": statement.status,
		}

	# ------------------------------------------------------------------ #
	# Cash Flow Forecast
	# ------------------------------------------------------------------ #

	def cash_flow_forecast(
		self,
		bank_account_id: str,
		days_ahead: int,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Generate a rolling N-day cash flow forecast.

		Uses the last confirmed CashPosition as the opening balance, then
		projects forward using pending FX settlements as the primary data source.
		In a full implementation, AP/AR due-date schedules feed additional cash flows.

		Returns list of dicts sorted by date:
		  {date, opening_cents, expected_receipts_cents, expected_payments_cents,
		   forecast_closing_cents, sources}
		"""
		from pgappforge.plugins.erp.finance.treasury.models import (
			BankAccount, CashPosition, FXDeal,
		)

		account = session.get(BankAccount, bank_account_id)
		if account is None:
			raise BankAccountNotFoundError(f"BankAccount {bank_account_id!r} not found")

		today = date.today()

		# Latest confirmed cash position
		latest_pos = session.execute(
			sa.select(CashPosition)
			.where(CashPosition.bank_account_id == bank_account_id)
			.where(CashPosition.position_date <= today)
			.order_by(sa.desc(CashPosition.position_date))
			.limit(1)
		).scalar_one_or_none()

		opening = account.balance_cents
		if latest_pos:
			opening = latest_pos.closing_balance_cents

		# Pending FX settlements in the forecast window
		horizon = today + timedelta(days=days_ahead)
		pending_deals = session.execute(
			sa.select(FXDeal)
			.where(FXDeal.buy_bank_account_id == bank_account_id)
			.where(FXDeal.status == "OPEN")
			.where(FXDeal.settlement_date > today)
			.where(FXDeal.settlement_date <= horizon)
		).scalars().all()

		# Build date-keyed receipt map from FX deals
		fx_receipts: dict[date, int] = {}
		for deal in pending_deals:
			fx_receipts[deal.settlement_date] = (
				fx_receipts.get(deal.settlement_date, 0) + deal.buy_amount_cents
			)

		forecast: list[dict[str, Any]] = []
		running_balance = opening

		for i in range(days_ahead):
			d = today + timedelta(days=i + 1)
			receipts = fx_receipts.get(d, 0)
			payments = 0   # hook for AP schedule
			closing = running_balance + receipts - payments

			forecast.append({
				"date": str(d),
				"opening_cents": running_balance,
				"expected_receipts_cents": receipts,
				"expected_payments_cents": payments,
				"forecast_closing_cents": closing,
				"sources": ["fx_settlement"] if receipts else [],
			})
			running_balance = closing

		return forecast

	# ------------------------------------------------------------------ #
	# Mark-to-Market
	# ------------------------------------------------------------------ #

	def mark_to_market_hedges(
		self,
		session: Any,
		tenant_id: str | None = None,
	) -> list[dict[str, Any]]:
		"""Revalue open FX deals using current market rates.

		Queries the latest ExchangeRate for each (sell_currency, buy_currency)
		pair and computes MTM P&L = (market_rate - contracted_rate) * notional.
		Updates FXDeal.mtm_value_cents.

		Returns list of MTM valuation dicts.
		"""
		from pgappforge.plugins.erp.finance.treasury.models import FXDeal
		from pgappforge.plugins.erp.foundation.models import ExchangeRate

		q = sa.select(FXDeal).where(FXDeal.status == "OPEN")
		if tenant_id:
			q = q.where(FXDeal.tenant_id == tenant_id)
		deals = session.execute(q).scalars().all()

		results: list[dict[str, Any]] = []

		for deal in deals:
			# Get latest market rate for this currency pair
			market_rate_row = session.execute(
				sa.select(ExchangeRate)
				.where(ExchangeRate.from_currency == deal.sell_currency)
				.where(ExchangeRate.to_currency == deal.buy_currency)
				.order_by(sa.desc(ExchangeRate.rate_date))
				.limit(1)
			).scalar_one_or_none()

			if market_rate_row is None:
				log.warning(
					"No market rate found for %s->%s on deal %r",
					deal.sell_currency, deal.buy_currency, deal.deal_reference,
				)
				continue

			current_rate = Decimal(str(market_rate_row.rate))
			contracted = Decimal(str(deal.contracted_rate))
			notional = Decimal(deal.sell_amount_cents)

			# MTM gain/loss in buy_currency cents
			# Positive = gain (market moved in our favour)
			mtm_rate_diff = current_rate - contracted
			mtm_cents = int((mtm_rate_diff * notional).to_integral_value(ROUND_HALF_UP))

			deal.mtm_value_cents = mtm_cents
			deal.market_rate = current_rate
			deal.updated_at = datetime.now(timezone.utc)

			results.append({
				"deal_id": deal.id,
				"deal_reference": deal.deal_reference,
				"contracted_rate": str(contracted),
				"market_rate": str(current_rate),
				"mtm_value_cents": mtm_cents,
				"hedge_designation": deal.hedge_designation,
			})

		session.flush()
		log.info("MTM revaluation: %d deals updated", len(results))
		return results

	# ------------------------------------------------------------------ #
	# Cash position helper
	# ------------------------------------------------------------------ #

	def get_cash_position(
		self,
		bank_account_id: str,
		position_date: date,
		session: Any,
	) -> Any | None:
		"""Retrieve the latest CashPosition for a given account and date."""
		from pgappforge.plugins.erp.finance.treasury.models import CashPosition
		return session.execute(
			sa.select(CashPosition)
			.where(CashPosition.bank_account_id == bank_account_id)
			.where(CashPosition.position_date == position_date)
			.order_by(sa.desc(CashPosition.created_at))
			.limit(1)
		).scalar_one_or_none()

	# ------------------------------------------------------------------ #
	# Internal helpers
	# ------------------------------------------------------------------ #

	def _generate_deal_reference(self, session: Any) -> str:
		from pgappforge.plugins.erp.finance.treasury.models import FXDeal
		year = date.today().year
		count = session.execute(
			sa.select(sa.func.count(FXDeal.id))
		).scalar_one()
		return f"FX-{year}-{count + 1:05d}"

	def _find_matching_document(
		self,
		line: Any,
		account: Any,
		session: Any,
	) -> dict[str, Any] | None:
		"""Attempt to match a statement line to a book entry.

		Simplified implementation — production should query AP/AR tables.
		Returns {"type": ..., "id": ...} or None.
		"""
		# Placeholder: real implementation queries payment/receipt tables
		# by amount_cents, is_debit, and date proximity
		return None


__all__ = [
	"TreasuryService",
	"TreasuryServiceError",
	"BankAccountNotFoundError",
	"FXDealNotFoundError",
	"FXDealStatusError",
	"BankAccountDetails",
	"FXDealDetails",
]
