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

	# ------------------------------------------------------------------ #
	# Bank Statement Import  (MT940 / OFX / CSV)
	# ------------------------------------------------------------------ #

	def import_bank_statement(
		self,
		file_content: str,
		file_format: str,
		bank_account_id: str,
		session: Any,
	) -> Any:
		"""Import a bank statement from MT940, OFX, or CSV content.

		Parses the file into BankStatement + BankStatementLine rows, then
		auto-runs reconciliation. Returns the created BankStatement.

		MT940: SWIFT statement format used by most African banks (KCB, Equity, NCBA).
		OFX:  Open Financial Exchange (used by US banks; Quicken format).
		CSV:  Fallback; expects columns: date, amount, reference, description.

		amount_cents in parsed dicts is signed: positive = credit, negative = debit.
		Conversion to (abs amount_cents, is_debit) happens here before DB insert.
		"""
		from pgappforge.plugins.erp.finance.treasury.models import (
			BankAccount, BankStatement, BankStatementLine, BankStatementImport,
		)

		account = session.execute(
			sa.select(BankAccount).where(BankAccount.id == bank_account_id)
		).scalar_one_or_none()
		if account is None:
			raise BankAccountNotFoundError(f"BankAccount {bank_account_id!r} not found")

		import_log = BankStatementImport(
			tenant_id=account.tenant_id,
			bank_account_id=bank_account_id,
			file_format=file_format.upper(),
			error_log=[],
		)
		session.add(import_log)

		fmt = file_format.upper()
		if fmt == "MT940":
			lines_data = self._parse_mt940(file_content, import_log)
		elif fmt == "OFX":
			lines_data = self._parse_ofx(file_content, import_log)
		elif fmt == "CSV":
			lines_data = self._parse_csv_statement(file_content, import_log)
		else:
			import_log.status = "FAILED"
			session.flush()
			raise TreasuryServiceError(
				f"Unsupported file format: {file_format!r}. Use MT940/OFX/CSV."
			)

		if not lines_data:
			import_log.status = "FAILED"
			session.flush()
			raise TreasuryServiceError(f"No transactions parsed from {file_format} file")

		# Derive statement date range from parsed lines
		dates = [ld["date"] for ld in lines_data if ld.get("date")]
		statement_date = max(dates) if dates else date.today()

		statement = BankStatement(
			tenant_id=account.tenant_id,
			bank_account_id=bank_account_id,
			statement_date=statement_date,
			# Balance totals unknown at import time; caller may update post-reconcile.
			opening_balance_cents=0,
			closing_balance_cents=0,
			status="IMPORTED",
		)
		session.add(statement)
		session.flush()  # populate statement.id

		for ld in lines_data:
			signed_cents: int = ld["amount_cents"]
			is_debit = signed_cents < 0
			abs_cents = abs(signed_cents)
			session.add(BankStatementLine(
				statement_id=statement.id,
				transaction_date=ld["date"],
				amount_cents=abs_cents,
				is_debit=is_debit,
				bank_reference=ld.get("reference", "")[:100] or None,
				description=ld.get("description", "")[:500],
				match_status="UNMATCHED",
			))

		import_log.row_count = len(lines_data)
		import_log.statement_id = statement.id
		import_log.status = "PARTIAL" if import_log.error_log else "OK"
		session.flush()

		# Auto-reconcile; non-fatal if it fails (statement is still usable)
		try:
			self.run_bank_reconciliation(bank_account_id, str(statement.id), session)
		except Exception as exc:
			log.warning("Auto-reconciliation failed after import: %s", exc)

		return statement

	def _parse_mt940(self, content: str, import_log: Any) -> list[dict]:
		"""Parse MT940 SWIFT bank statement format.

		MT940 tag :61: carries the transaction record:
		  :61: YYMMDD[MMDD](C|D|RC|RD)AMOUNT[Nxxx]//BANK_REF\\nNARRATIVE
		  C/RC = credit (money in), D/RD = debit (money out).
		  AMOUNT uses comma as decimal separator (European convention).

		Returns list of dicts with signed amount_cents (positive=credit).
		"""
		import re
		from decimal import Decimal, ROUND_HALF_UP

		lines_data: list[dict] = []

		# Match :61: tag through to next tag or end of string
		transaction_re = re.compile(
			r":61:(\d{6})(\d{4})?(C|D|RC|RD)(\d+,\d{0,2})([A-Z]{4})(.*?)(?=:\d{2}[A-Z]?:|$)",
			re.DOTALL,
		)

		for m in transaction_re.finditer(content):
			date_str, _value_date, cr_dr, amount_str, _fund_code, narrative = m.groups()
			try:
				amount_dec = Decimal(amount_str.replace(",", "."))
				amount_cents = int(
					amount_dec.quantize(Decimal("0.01"), ROUND_HALF_UP) * 100
				)
				# D/RD = debit (money leaves account) → negative
				if cr_dr in ("D", "RD"):
					amount_cents = -amount_cents

				parsed_date = date(
					2000 + int(date_str[:2]),
					int(date_str[2:4]),
					int(date_str[4:6]),
				)

				# Extract narrative from :86: tag if present in remainder
				description = ""
				narr_match = re.search(r":86:(.*?)(?=:\d{2}[A-Z]?:|$)", narrative, re.DOTALL)
				if narr_match:
					description = " ".join(narr_match.group(1).split())[:500]

				lines_data.append({
					"date": parsed_date,
					"amount_cents": amount_cents,
					"reference": (narrative.strip().splitlines()[0] if narrative.strip() else "")[:100],
					"description": description,
				})
			except Exception as exc:
				import_log.error_log.append({
					"line": m.group(0)[:80],
					"error": str(exc),
				})

		return lines_data

	def _parse_ofx(self, content: str, import_log: Any) -> list[dict]:
		"""Parse OFX (Open Financial Exchange) bank statement.

		Handles both OFX 1.x (SGML, no closing tags) and OFX 2.x (XML).
		Extracts <STMTTRN> blocks: DTPOSTED, TRNAMT, NAME/MEMO, FITID.

		TRNAMT is already signed in OFX (positive = credit, negative = debit).
		Returns list of dicts with signed amount_cents.
		"""
		import re
		from decimal import Decimal, ROUND_HALF_UP

		lines_data: list[dict] = []

		# For SGML OFX 1.x, <STMTTRN> may lack a closing tag; use lookahead
		trn_re = re.compile(
			r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|$)",
			re.DOTALL | re.IGNORECASE,
		)
		field_re = re.compile(r"<(\w+)>([^<\n\r]+)", re.IGNORECASE)

		for trn_match in trn_re.finditer(content):
			block = trn_match.group(1)
			if not block.strip():
				continue
			fields = {k.upper(): v.strip() for k, v in field_re.findall(block)}
			try:
				dt_str = fields.get("DTPOSTED", "")[:8]
				parsed_date = date(
					int(dt_str[:4]), int(dt_str[4:6]), int(dt_str[6:8])
				)
				amount_dec = Decimal(fields.get("TRNAMT", "0").strip())
				amount_cents = int(
					amount_dec.quantize(Decimal("0.01"), ROUND_HALF_UP) * 100
				)
				description = fields.get("NAME", fields.get("MEMO", ""))[:500]
				lines_data.append({
					"date": parsed_date,
					"amount_cents": amount_cents,
					"reference": fields.get("FITID", "")[:100],
					"description": description,
				})
			except Exception as exc:
				import_log.error_log.append({
					"raw": trn_match.group(0)[:80],
					"error": str(exc),
				})

		return lines_data

	def _parse_csv_statement(self, content: str, import_log: Any) -> list[dict]:
		"""Parse CSV bank statement.

		Flexible column detection (case-insensitive, stripped):
		  date          — transaction_date, value_date
		  amount        — credit_debit_indicator (already signed)
		  reference     — ref
		  description   — narration, narrative, memo

		Delimiter auto-detected: semicolon wins if it occurs more than comma.
		Amount: positive = credit, negative = debit. Commas inside numbers stripped.
		Returns list of dicts with signed amount_cents.
		"""
		import csv
		import io
		from decimal import Decimal, ROUND_HALF_UP

		lines_data: list[dict] = []
		delimiter = ";" if content.count(";") > content.count(",") else ","
		reader = csv.DictReader(io.StringIO(content.strip()), delimiter=delimiter)

		for i, row in enumerate(reader):
			try:
				keys = {k.lower().strip(): v.strip() for k, v in row.items() if k}
				date_str = (
					keys.get("date")
					or keys.get("transaction_date")
					or keys.get("value_date")
					or ""
				)
				amount_str = (
					keys.get("amount")
					or keys.get("credit_debit_indicator")
					or "0"
				).replace(",", "")
				parsed_date = date.fromisoformat(date_str.replace("/", "-"))
				amount_cents = int(
					Decimal(amount_str).quantize(Decimal("0.01"), ROUND_HALF_UP) * 100
				)
				reference = (
					keys.get("reference") or keys.get("ref") or ""
				)[:100]
				description = (
					keys.get("description")
					or keys.get("narration")
					or keys.get("narrative")
					or keys.get("memo")
					or ""
				)[:500]
				lines_data.append({
					"date": parsed_date,
					"amount_cents": amount_cents,
					"reference": reference,
					"description": description,
				})
			except Exception as exc:
				import_log.error_log.append({"row": i + 2, "error": str(exc)})

		return lines_data

	# ------------------------------------------------------------------ #
	# Bank Feed (live sync)
	# ------------------------------------------------------------------ #

	def register_feed_connection(
		self,
		bank_account_id: str,
		provider: str,
		credentials: dict,
		tenant_id: str,
		session: Any,
		*,
		sync_frequency_minutes: int = 60,
	) -> Any:
		"""Register a live bank feed connection.

		Credentials are encrypted at rest using Fernet symmetric encryption.
		If the cryptography package is unavailable, stores as JSON (log warning).

		Providers: EQUITY (Equity Bank Kenya REST API), KCB (KCB Open Banking API),
		           MPESA (Daraja API transaction history), PLAID (generic Plaid Link).
		"""
		from pgappforge.plugins.erp.finance.treasury.models import BankFeedConnection
		import json

		# Encrypt credentials using master key + tenant salt (HKDF).
		# Production: set FAB_FEED_MASTER_KEY env var to 32 random bytes (base64).
		# Without it, credentials are stored with a weak tenant-derived key — DO NOT use in production.
		try:
			from cryptography.fernet import Fernet
			import base64, hashlib, hmac as _hmac, os
			master_raw = os.environ.get("FAB_FEED_MASTER_KEY", "")
			if master_raw:
				# Proper HMAC-based key derivation: master key + tenant_id salt
				master = base64.urlsafe_b64decode(master_raw + "==")  # pad for decode safety
				key_bytes = _hmac.new(master, tenant_id.encode(), hashlib.sha256).digest()
			else:
				log.warning(
					"FAB_FEED_MASTER_KEY not set — bank credentials encrypted with tenant-derived key only. "
					"Set FAB_FEED_MASTER_KEY for production deployments."
				)
				key_bytes = hashlib.sha256(tenant_id.encode() + b"_bankfeed_v1").digest()
			key = base64.urlsafe_b64encode(key_bytes)
			f = Fernet(key)
			encrypted = {"_fernet": f.encrypt(json.dumps(credentials).encode()).decode(), "_v": 1}
		except ImportError:
			log.warning("cryptography not installed — bank feed credentials stored unencrypted")
			encrypted = credentials

		conn = BankFeedConnection(
			tenant_id=tenant_id,
			bank_account_id=bank_account_id,
			provider=provider.upper(),
			credentials_encrypted=encrypted,
			sync_frequency_minutes=sync_frequency_minutes,
		)
		session.add(conn)
		session.flush()
		return conn

	def sync_feed(
		self,
		connection_id: str,
		session: Any,
	) -> dict:
		"""Fetch transactions since last sync and import as bank statement.

		Routes to provider-specific fetcher. Parsed transactions are imported
		via import_bank_statement() and auto-reconciled.

		Returns: {connection_id, provider, transactions_fetched, statement_id, reconciled}
		"""
		from pgappforge.plugins.erp.finance.treasury.models import BankFeedConnection

		conn = session.execute(
			sa.select(BankFeedConnection).where(BankFeedConnection.id == connection_id)
		).scalar_one_or_none()
		if conn is None:
			raise TreasuryServiceError(f"BankFeedConnection {connection_id!r} not found")
		if not conn.is_active:
			raise TreasuryServiceError(f"Feed connection {connection_id!r} is inactive")

		since = conn.last_sync_at or datetime.now(timezone.utc).replace(day=1)

		try:
			if conn.provider == "EQUITY":
				raw_lines = self._fetch_equity_bank(conn, since)
			elif conn.provider == "KCB":
				raw_lines = self._fetch_kcb(conn, since)
			elif conn.provider == "MPESA":
				raw_lines = self._fetch_mpesa(conn, since)
			else:
				raw_lines = self._fetch_generic_rest(conn, since)

			if not raw_lines:
				conn.last_sync_at = datetime.now(timezone.utc)
				session.flush()
				return {
					"connection_id": connection_id,
					"provider": conn.provider,
					"transactions_fetched": 0,
					"statement_id": None,
				}

			# Format as CSV for import_bank_statement
			csv_lines = ["date,amount,reference,description"]
			for t in raw_lines:
				csv_lines.append(
					f"{t['date']},{t['amount_cents'] / 100:.2f},"
					f"{t.get('reference', '')},{t.get('description', '')}"
				)
			csv_content = "\n".join(csv_lines)

			statement = self.import_bank_statement(csv_content, "CSV", str(conn.bank_account_id), session)
			conn.last_sync_at = datetime.now(timezone.utc)
			session.flush()

			return {
				"connection_id": connection_id,
				"provider": conn.provider,
				"transactions_fetched": len(raw_lines),
				"statement_id": str(statement.id),
				"synced_at": conn.last_sync_at.isoformat(),
			}
		except Exception as exc:
			new_entry = {"ts": datetime.now(timezone.utc).isoformat(), "error": str(exc)[:200]}
			conn.error_log = ((conn.error_log or []) + [new_entry])[-50:]  # cap at 50 entries
			session.flush()
			raise

	def _fetch_equity_bank(self, conn: Any, since: Any) -> list[dict]:
		"""Fetch transactions from Equity Bank Kenya Open Banking API.

		API Reference: https://developer.equitybankgroup.com/api (REST, OAuth2)
		Endpoint: GET /v1/accounts/{accountId}/transactions?fromDate={since}
		Auth: Bearer token from OAuth2 client_credentials flow

		Credentials expected: {client_id, client_secret, account_id}

		NOTE: This is a framework stub. Implement HTTP calls when API access is provisioned.
		Returns list of {date, amount_cents, reference, description}.
		"""
		log.info("_fetch_equity_bank: stub — implement with requests library when API credentials available")
		return []

	def _fetch_kcb(self, conn: Any, since: Any) -> list[dict]:
		"""Fetch transactions from KCB Open Banking API.

		API Reference: https://developer.kcbgroup.com (REST, API Key)
		Endpoint: GET /accounts/{accountNumber}/statement?startDate={since}
		Auth: x-api-key header

		Credentials expected: {api_key, account_number}

		NOTE: Framework stub. Implement with requests library when provisioned.
		"""
		log.info("_fetch_kcb: stub — implement with requests library when API credentials available")
		return []

	def _fetch_mpesa(self, conn: Any, since: Any) -> list[dict]:
		"""Fetch M-Pesa transaction history via Safaricom Daraja API.

		API Reference: https://developer.safaricom.co.ke/APIs/MpesaExpressQuery
		Endpoint: POST /mpesa/c2b/v1/transactionstatus (Business Request)
		Auth: OAuth2 Bearer token

		Credentials expected: {consumer_key, consumer_secret, shortcode, initiator, security_credential}

		NOTE: Framework stub. Integrate with existing pswitch_adapter for live connection.
		"""
		log.info("_fetch_mpesa: stub — integrate with pswitch_adapter")
		return []

	def _fetch_generic_rest(self, conn: Any, since: Any) -> list[dict]:
		"""Generic REST bank feed fetcher (Plaid-compatible response format).

		Credentials expected: {base_url, api_key, account_id}
		Expected response: {transactions: [{date, amount, name, transaction_id}]}
		"""
		log.info("_fetch_generic_rest: stub for provider %s", conn.provider)
		return []


__all__ = [
	"TreasuryService",
	"TreasuryServiceError",
	"BankAccountNotFoundError",
	"FXDealNotFoundError",
	"FXDealStatusError",
	"BankAccountDetails",
	"FXDealDetails",
]
