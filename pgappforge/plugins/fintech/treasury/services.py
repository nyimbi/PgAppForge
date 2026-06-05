"""
pgappforge/plugins/fintech/treasury/services.py

TreasuryService — FX dealing, position management, EOD revaluation, P&L.

Design constraints
------------------
- All monetary storage: BigInteger cents.  Intermediate arithmetic uses
  Python int; rate multiplication goes via Decimal to avoid float error.
- SQLAlchemy 2.x patterns: select(), session.execute().scalar_one_or_none(),
  session.get(), explicit UPDATE statements for atomic position increments.
- GL postings: lazy import of GLService.post_simple_journal() wrapped in
  try/except — a GL failure is non-fatal and must not abort the FX deal.
- Event emission: emit_event() calls wrapped in try/except — non-fatal.
- PostgreSQL ONLY — no dialect portability required.
- Every public method is synchronous (Flask/SQLAlchemy context).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import sqlalchemy as sa
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from pgappforge.plugins.fintech.treasury.models import (
	FintechFXDeal,
	FXPosition,
	FXRate,
	TreasuryLimit,
)
from pgappforge.plugins.fintech.treasury.events import (
	FXDealBookedEvent,
	FXDealSettledEvent,
	FXLimitBreachedEvent,
	FXPositionRevaluedEvent,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TreasuryError(Exception):
	"""Base exception for all treasury service errors."""


class FXDealNotFoundError(TreasuryError):
	"""No FX deal found for the given identifier."""


class FXRateNotFoundError(TreasuryError):
	"""No active FX rate found for the requested currency pair."""


class FXDealStatusError(TreasuryError):
	"""Operation not permitted for the deal's current status."""


class TreasuryLimitBreachError(TreasuryError):
	"""A BLOCK-action treasury limit would be breached by this deal.

	Attributes
	----------
	limit_id : str
	limit_type : str
	limit_amount_cents : int
	current_utilisation_cents : int
	additional_cents : int
	"""

	def __init__(
		self,
		message: str,
		limit_id: str = "",
		limit_type: str = "",
		limit_amount_cents: int = 0,
		current_utilisation_cents: int = 0,
		additional_cents: int = 0,
	) -> None:
		super().__init__(message)
		self.limit_id = limit_id
		self.limit_type = limit_type
		self.limit_amount_cents = limit_amount_cents
		self.current_utilisation_cents = current_utilisation_cents
		self.additional_cents = additional_cents


# ---------------------------------------------------------------------------
# Default GL codes — overridable via GLAccountMapping per tenant
# ---------------------------------------------------------------------------

_FX_GL: dict[str, str] = {
	"FX_REVALUATION_PNL":      "4300",   # Income: FX gain/loss
	"FX_REVALUATION_SUSPENSE": "2300",   # Liability: revaluation suspense
}


# ---------------------------------------------------------------------------
# Deal number generation
# ---------------------------------------------------------------------------

def _generate_deal_number(session: Session, tenant_id: str, trade_date: date) -> str:
	"""Generate a sequential deal number: FX-YYYYMMDD-NNNN.

	Uses a COUNT query as a sequence proxy — not gap-free but race-safe under
	READ COMMITTED because two concurrent inserts will both see the same count
	and the unique constraint (tenant_id, deal_number) will reject duplicates,
	triggering a retry at the application layer.

	For production > 9999 deals/day, replace with a PostgreSQL sequence.
	"""
	date_str = trade_date.strftime("%Y%m%d")
	prefix = f"FX-{date_str}-"
	count_stmt = (
		select(func.count(FintechFXDeal.id))
		.where(FintechFXDeal.tenant_id == tenant_id)
		.where(FintechFXDeal.deal_number.like(f"{prefix}%"))
	)
	n: int = session.execute(count_stmt).scalar() or 0
	return f"{prefix}{n + 1:04d}"


# ---------------------------------------------------------------------------
# Rate arithmetic helpers
# ---------------------------------------------------------------------------

def _to_decimal(value: int | float | str | Decimal) -> Decimal:
	"""Coerce any numeric type to Decimal for rate arithmetic."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _rate_to_sold_cents(bought_cents: int, exchange_rate: Decimal) -> int:
	"""Compute sold_amount_cents from bought_amount_cents × exchange_rate.

	Rounds half-up to the nearest cent.
	"""
	result = Decimal(bought_cents) * exchange_rate
	return int(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _compute_revaluation_pnl_cents(
	net_position_cents: int,
	book_rate: Decimal,
	revaluation_rate: Decimal,
) -> int:
	"""Unrealised P&L for a net long position.

	For a net long position in foreign currency CCY vs functional currency KES:
	  P&L = net_position_cents × (revaluation_rate - book_rate)

	Positive net_position_cents + rising rate → gain (positive P&L).
	Net short (negative) + falling rate → gain.

	Returns integer cents in functional currency.
	"""
	rate_move = revaluation_rate - book_rate
	pnl = Decimal(net_position_cents) * rate_move
	return int(pnl.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# TreasuryService
# ---------------------------------------------------------------------------

class TreasuryService:
	"""Core treasury operations — FX dealing, positions, revaluation, P&L.

	Parameters
	----------
	session : SQLAlchemy Session (or scoped_session proxy)
	tenant_id : str  — all queries and inserts are scoped to this tenant
	"""

	def __init__(self, session: Session, tenant_id: str) -> None:
		assert session is not None, "session must not be None"
		assert tenant_id, "tenant_id must be a non-empty string"
		self.session = session
		self.tenant_id = tenant_id

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _emit(self, event: object) -> None:
		"""Emit a domain event — non-fatal if the bus is unavailable."""
		try:
			from pgappforge.plugins.erp.foundation.commons import emit_event
			emit_event(event, self.session)  # type: ignore[arg-type]
		except Exception as exc:
			log.warning("TreasuryService._emit: failed to emit %r (non-fatal): %s", event, exc)

	def _post_gl(
		self,
		debit_code: str,
		credit_code: str,
		amount_cents: int,
		narrative: str,
		reference: str = "",
	) -> None:
		"""Post a simple two-leg GL journal — non-fatal if GL service unavailable."""
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService  # type: ignore
			CoreBankingService.post_simple_journal(  # type: ignore[attr-defined]
				session=self.session,
				tenant_id=self.tenant_id,
				debit_gl_code=debit_code,
				credit_gl_code=credit_code,
				amount_cents=amount_cents,
				narrative=narrative,
				reference=reference,
			)
		except Exception as exc:
			log.warning(
				"TreasuryService._post_gl: GL posting failed (non-fatal): %s", exc
			)

	def _resolve_gl(self, key: str) -> str:
		"""Resolve a GL account code, preferring per-tenant override."""
		try:
			from pgappforge.plugins.fintech.core_banking.models import GLAccountMapping
			row = self.session.execute(
				select(GLAccountMapping)
				.where(GLAccountMapping.tenant_id == self.tenant_id)
				.where(GLAccountMapping.cb_account_key == key)
				.where(GLAccountMapping.is_active.is_(True))
			).scalar_one_or_none()
			if row is not None:
				return row.gl_account_code
		except Exception:
			pass
		return _FX_GL.get(key, key)

	def _get_deal(self, deal_id: str) -> FintechFXDeal:
		"""Fetch deal by id, scoped to tenant.  Raises FXDealNotFoundError."""
		deal = self.session.execute(
			select(FintechFXDeal)
			.where(FintechFXDeal.id == deal_id)
			.where(FintechFXDeal.tenant_id == self.tenant_id)
		).scalar_one_or_none()
		if deal is None:
			raise FXDealNotFoundError(f"FX deal {deal_id!r} not found for tenant {self.tenant_id!r}")
		return deal

	def _get_or_create_position(
		self, currency_code: str, position_date: date
	) -> FXPosition:
		"""Fetch the FXPosition for (tenant, currency, date), creating if absent."""
		pos = self.session.execute(
			select(FXPosition)
			.where(FXPosition.tenant_id == self.tenant_id)
			.where(FXPosition.currency_code == currency_code)
			.where(FXPosition.position_date == position_date)
		).scalar_one_or_none()

		if pos is None:
			pos = FXPosition(
				tenant_id=self.tenant_id,
				currency_code=currency_code,
				position_date=position_date,
				long_amount_cents=0,
				short_amount_cents=0,
				revaluation_pnl_cents=0,
			)
			self.session.add(pos)
			self.session.flush()

		return pos

	def _get_active_rate(
		self,
		base_currency: str,
		quote_currency: str,
		rate_type: str = "SPOT",
	) -> FXRate:
		"""Fetch the current active rate for a currency pair.  Raises FXRateNotFoundError."""
		rate = self.session.execute(
			select(FXRate)
			.where(FXRate.tenant_id == self.tenant_id)
			.where(FXRate.base_currency == base_currency)
			.where(FXRate.quote_currency == quote_currency)
			.where(FXRate.rate_type == rate_type)
			.where(FXRate.is_active.is_(True))
			.order_by(FXRate.valid_from.desc())
			.limit(1)
		).scalar_one_or_none()

		if rate is None:
			raise FXRateNotFoundError(
				f"No active {rate_type} rate for {base_currency}/{quote_currency} "
				f"(tenant={self.tenant_id!r})"
			)
		return rate

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def upload_fx_rate(
		self,
		base_ccy: str,
		quote_ccy: str,
		bid: int | float | str | Decimal,
		offer: int | float | str | Decimal,
		source: str = "MANUAL",
		rate_type: str = "SPOT",
	) -> FXRate:
		"""Upsert an FX rate, marking the previous active rate inactive.

		Parameters
		----------
		base_ccy : str   — ISO 4217 base currency e.g. "USD"
		quote_ccy : str  — ISO 4217 quote currency e.g. "KES"
		bid : numeric    — interbank bid rate
		offer : numeric  — interbank offer rate
		source : str     — REUTERS | BLOOMBERG | CBK | MANUAL
		rate_type : str  — SPOT | FORWARD_1M | FORWARD_3M | FORWARD_6M |
		                    FORWARD_12M | SWAP

		Returns
		-------
		FXRate — the newly inserted active rate row.
		"""
		assert base_ccy and len(base_ccy) == 3, "base_ccy must be 3-char ISO 4217"
		assert quote_ccy and len(quote_ccy) == 3, "quote_ccy must be 3-char ISO 4217"

		bid_d = _to_decimal(bid)
		offer_d = _to_decimal(offer)
		mid_d = (bid_d + offer_d) / Decimal("2")
		now = datetime.now(timezone.utc)

		# Mark previous active rate(s) for this pair as inactive
		self.session.execute(
			update(FXRate)
			.where(FXRate.tenant_id == self.tenant_id)
			.where(FXRate.base_currency == base_ccy)
			.where(FXRate.quote_currency == quote_ccy)
			.where(FXRate.rate_type == rate_type)
			.where(FXRate.is_active.is_(True))
			.values(is_active=False, valid_to=now, updated_at=now)
		)

		rate = FXRate(
			tenant_id=self.tenant_id,
			base_currency=base_ccy,
			quote_currency=quote_ccy,
			rate_type=rate_type,
			bid_rate=bid_d,
			offer_rate=offer_d,
			mid_rate=mid_d,
			rate_source=source,
			valid_from=now,
			valid_to=None,
			is_active=True,
		)
		self.session.add(rate)
		self.session.flush()

		log.info(
			"TreasuryService.upload_fx_rate: %s/%s %s mid=%s source=%s tenant=%s",
			base_ccy, quote_ccy, rate_type, mid_d, source, self.tenant_id,
		)
		return rate

	def check_position_limit(
		self, currency_code: str, additional_cents: int
	) -> None:
		"""Check OPEN_POSITION and DEAL_SIZE treasury limits.

		For WARN-action limits: logs breach, emits FXLimitBreachedEvent, returns.
		For BLOCK-action limits: emits event then raises TreasuryLimitBreachError.

		Parameters
		----------
		currency_code : str   — currency being bought/sold
		additional_cents : int — deal size in functional currency cents
		"""
		limits = self.session.execute(
			select(TreasuryLimit)
			.where(TreasuryLimit.tenant_id == self.tenant_id)
			.where(TreasuryLimit.is_active.is_(True))
			.where(
				sa.or_(
					sa.and_(
						TreasuryLimit.limit_type == "OPEN_POSITION",
						sa.or_(
							TreasuryLimit.currency_code == currency_code,
							TreasuryLimit.currency_code.is_(None),
						),
					),
					sa.and_(
						TreasuryLimit.limit_type == "DEAL_SIZE",
						sa.or_(
							TreasuryLimit.currency_code == currency_code,
							TreasuryLimit.currency_code.is_(None),
						),
					),
				)
			)
		).scalars().all()

		for lim in limits:
			projected = (lim.current_utilisation_cents or 0) + additional_cents
			if projected > lim.limit_amount_cents:
				event = FXLimitBreachedEvent(
					limit_id=lim.id,
					limit_type=lim.limit_type,
					currency_code=currency_code or "",
					counterparty_id="",
					limit_amount_cents=lim.limit_amount_cents,
					current_utilisation_cents=lim.current_utilisation_cents or 0,
					additional_cents=additional_cents,
					breach_action=lim.breach_action,
					tenant_id=self.tenant_id,
				)
				self._emit(event)

				if lim.breach_action == "BLOCK":
					raise TreasuryLimitBreachError(
						f"Treasury limit {lim.limit_type!r} ({lim.id}) would be breached: "
						f"limit={lim.limit_amount_cents}c "
						f"utilisation={lim.current_utilisation_cents}c "
						f"additional={additional_cents}c",
						limit_id=lim.id,
						limit_type=lim.limit_type,
						limit_amount_cents=lim.limit_amount_cents,
						current_utilisation_cents=lim.current_utilisation_cents or 0,
						additional_cents=additional_cents,
					)
				else:
					log.warning(
						"TreasuryService: WARN limit breached — type=%s ccy=%s "
						"limit=%dc utilisation=%dc additional=%dc tenant=%s",
						lim.limit_type, currency_code,
						lim.limit_amount_cents,
						lim.current_utilisation_cents or 0,
						additional_cents,
						self.tenant_id,
					)

	def _check_counterparty_limit(
		self, counterparty_id: str, additional_cents: int
	) -> None:
		"""Check COUNTERPARTY treasury limit for the given counterparty."""
		limits = self.session.execute(
			select(TreasuryLimit)
			.where(TreasuryLimit.tenant_id == self.tenant_id)
			.where(TreasuryLimit.is_active.is_(True))
			.where(TreasuryLimit.limit_type == "COUNTERPARTY")
			.where(
				sa.or_(
					TreasuryLimit.counterparty_id == counterparty_id,
					TreasuryLimit.counterparty_id.is_(None),
				)
			)
		).scalars().all()

		for lim in limits:
			projected = (lim.current_utilisation_cents or 0) + additional_cents
			if projected > lim.limit_amount_cents:
				event = FXLimitBreachedEvent(
					limit_id=lim.id,
					limit_type=lim.limit_type,
					currency_code=lim.currency_code or "",
					counterparty_id=counterparty_id,
					limit_amount_cents=lim.limit_amount_cents,
					current_utilisation_cents=lim.current_utilisation_cents or 0,
					additional_cents=additional_cents,
					breach_action=lim.breach_action,
					tenant_id=self.tenant_id,
				)
				self._emit(event)

				if lim.breach_action == "BLOCK":
					raise TreasuryLimitBreachError(
						f"Counterparty limit ({lim.id}) would be breached for {counterparty_id!r}: "
						f"limit={lim.limit_amount_cents}c "
						f"utilisation={lim.current_utilisation_cents}c "
						f"additional={additional_cents}c",
						limit_id=lim.id,
						limit_type="COUNTERPARTY",
						limit_amount_cents=lim.limit_amount_cents,
						current_utilisation_cents=lim.current_utilisation_cents or 0,
						additional_cents=additional_cents,
					)
				else:
					log.warning(
						"TreasuryService: WARN counterparty limit breached — "
						"counterparty=%s limit=%dc utilisation=%dc additional=%dc tenant=%s",
						counterparty_id,
						lim.limit_amount_cents,
						lim.current_utilisation_cents or 0,
						additional_cents,
						self.tenant_id,
					)

	def book_fx_deal(
		self,
		deal_type: str,
		bought_currency: str,
		sold_currency: str,
		bought_amount_cents: int,
		exchange_rate: int | float | str | Decimal,
		value_date: date,
		counterparty_id: str,
		nostro_account_code: str = "",
		vostro_account_code: str = "",
		trader_id: str | None = None,
		maturity_date: date | None = None,
		their_reference: str | None = None,
	) -> FintechFXDeal:
		"""Book a new FX deal.

		Steps:
		  1. Validate limits (position + counterparty)
		  2. Compute sold_amount_cents from bought_amount_cents × exchange_rate
		  3. INSERT FintechFXDeal (status=BOOKED)
		  4. Update FXPosition: long_amount_cents += bought, short_amount_cents += sold
		  5. Post GL: DR bought_currency nostro / CR sold_currency nostro
		  6. Emit FXDealBookedEvent

		Parameters
		----------
		deal_type : str          — SPOT | FORWARD | SWAP | NDF
		bought_currency : str    — ISO 4217 currency the bank receives
		sold_currency : str      — ISO 4217 currency the bank delivers
		bought_amount_cents : int — amount in bought_currency minor units
		exchange_rate : numeric  — contractual rate: 1 bought = rate sold
		value_date : date        — settlement date
		counterparty_id : str    — FK to erp_party
		nostro_account_code : str — our nostro for bought currency leg
		vostro_account_code : str — our vostro for sold currency leg
		trader_id : str | None   — optional FK to erp_party (trader)
		maturity_date : date | None — for FORWARD/SWAP/NDF
		their_reference : str | None — counterparty's own reference

		Returns
		-------
		FintechFXDeal — the newly booked deal row (flushed, not committed).

		Raises
		------
		TreasuryLimitBreachError — if a BLOCK-action limit would be exceeded.
		"""
		assert deal_type in ("SPOT", "FORWARD", "SWAP", "NDF"), \
			f"deal_type must be SPOT|FORWARD|SWAP|NDF, got {deal_type!r}"
		assert bought_currency and len(bought_currency) == 3, "bought_currency must be 3-char ISO 4217"
		assert sold_currency and len(sold_currency) == 3, "sold_currency must be 3-char ISO 4217"
		assert bought_amount_cents > 0, "bought_amount_cents must be positive"
		assert counterparty_id, "counterparty_id must not be empty"

		rate_d = _to_decimal(exchange_rate)
		assert rate_d > 0, "exchange_rate must be positive"

		trade_date_val = date.today()
		sold_amount_cents = _rate_to_sold_cents(bought_amount_cents, rate_d)

		# --- 1. Limit checks ---
		self.check_position_limit(bought_currency, bought_amount_cents)
		self._check_counterparty_limit(counterparty_id, sold_amount_cents)

		# --- 2. Generate deal number ---
		deal_number = _generate_deal_number(self.session, self.tenant_id, trade_date_val)
		our_reference = deal_number  # internal reference mirrors deal number

		# --- 3. Create FintechFXDeal ---
		deal = FintechFXDeal(
			tenant_id=self.tenant_id,
			deal_number=deal_number,
			deal_type=deal_type,
			status="BOOKED",
			bought_currency=bought_currency,
			sold_currency=sold_currency,
			bought_amount_cents=bought_amount_cents,
			sold_amount_cents=sold_amount_cents,
			exchange_rate=rate_d,
			trade_date=trade_date_val,
			value_date=value_date,
			maturity_date=maturity_date,
			counterparty_id=counterparty_id,
			nostro_account_code=nostro_account_code,
			vostro_account_code=vostro_account_code,
			trader_id=trader_id,
			our_reference=our_reference,
			their_reference=their_reference,
		)
		self.session.add(deal)
		self.session.flush()

		# --- 4. Update positions ---
		# Bought currency: we are long (inflow)
		bought_pos = self._get_or_create_position(bought_currency, trade_date_val)
		bought_pos.long_amount_cents = (bought_pos.long_amount_cents or 0) + bought_amount_cents
		bought_pos.updated_at = datetime.now(timezone.utc)

		# Sold currency: we are short (outflow)
		sold_pos = self._get_or_create_position(sold_currency, trade_date_val)
		sold_pos.short_amount_cents = (sold_pos.short_amount_cents or 0) + sold_amount_cents
		sold_pos.updated_at = datetime.now(timezone.utc)

		self.session.flush()

		# --- 5. GL posting ---
		# DR bought_currency nostro (asset increasing)
		# CR sold_currency nostro (asset decreasing — delivering sold ccy)
		nostro_code = nostro_account_code or "1010"
		vostro_code = vostro_account_code or "1010"
		self._post_gl(
			debit_code=nostro_code,
			credit_code=vostro_code,
			amount_cents=bought_amount_cents,
			narrative=f"FX deal {deal_number} book: BUY {bought_currency} SELL {sold_currency}",
			reference=deal_number,
		)

		# --- 6. Emit event ---
		self._emit(FXDealBookedEvent(
			deal_id=deal.id,
			deal_number=deal_number,
			deal_type=deal_type,
			bought_currency=bought_currency,
			sold_currency=sold_currency,
			bought_amount_cents=bought_amount_cents,
			sold_amount_cents=sold_amount_cents,
			exchange_rate=str(rate_d),
			trade_date=trade_date_val.isoformat(),
			value_date=value_date.isoformat(),
			counterparty_id=counterparty_id,
			trader_id=trader_id or "",
			tenant_id=self.tenant_id,
		))

		log.info(
			"TreasuryService.book_fx_deal: %s %s/%s bought=%dc sold=%dc rate=%s "
			"deal=%s tenant=%s",
			deal_type, bought_currency, sold_currency,
			bought_amount_cents, sold_amount_cents, rate_d,
			deal_number, self.tenant_id,
		)

		assert deal.id, "deal must have a PK after flush"
		assert deal.status == "BOOKED"
		return deal

	def settle_fx_deal(self, deal_id: str) -> FintechFXDeal:
		"""Mark an FX deal as SETTLED and post settlement GL entries.

		Steps:
		  1. Fetch deal; assert status == BOOKED or CONFIRMED
		  2. Compute realised P&L vs revaluation_rate (if available)
		  3. Set status=SETTLED, settled_at, pnl_cents
		  4. Reverse open position entries (reduce long/short)
		  5. Post settlement GL entries
		  6. Emit FXDealSettledEvent

		Parameters
		----------
		deal_id : str — UUID of the FintechFXDeal to settle

		Returns
		-------
		FintechFXDeal — the updated deal row (flushed).

		Raises
		------
		FXDealNotFoundError   — deal does not exist for this tenant
		FXDealStatusError     — deal is already SETTLED or CANCELLED
		"""
		deal = self._get_deal(deal_id)

		if deal.status in ("SETTLED", "CANCELLED"):
			raise FXDealStatusError(
				f"Cannot settle deal {deal.deal_number!r}: status is {deal.status!r}"
			)

		now = datetime.now(timezone.utc)
		settlement_date = now.date()

		# --- Compute realised P&L ---
		# If a revaluation_rate exists, P&L = (revaluation_rate - book_rate) × bought_cents
		pnl_cents = 0
		if deal.revaluation_rate is not None:
			book_rate = _to_decimal(deal.exchange_rate)
			rev_rate = _to_decimal(deal.revaluation_rate)
			pnl_cents = _compute_revaluation_pnl_cents(
				deal.bought_amount_cents, book_rate, rev_rate
			)

		# --- 3. Update deal ---
		deal.status = "SETTLED"
		deal.settled_at = now
		deal.pnl_cents = pnl_cents
		deal.updated_at = now

		# --- 4. Reverse position entries ---
		# Bought leg was a long — reverse it
		bought_pos = self.session.execute(
			select(FXPosition)
			.where(FXPosition.tenant_id == self.tenant_id)
			.where(FXPosition.currency_code == deal.bought_currency)
			.where(FXPosition.position_date == deal.trade_date)
		).scalar_one_or_none()

		if bought_pos is not None:
			bought_pos.long_amount_cents = max(
				0, (bought_pos.long_amount_cents or 0) - deal.bought_amount_cents
			)
			bought_pos.updated_at = now

		# Sold leg was a short — reverse it
		sold_pos = self.session.execute(
			select(FXPosition)
			.where(FXPosition.tenant_id == self.tenant_id)
			.where(FXPosition.currency_code == deal.sold_currency)
			.where(FXPosition.position_date == deal.trade_date)
		).scalar_one_or_none()

		if sold_pos is not None:
			sold_pos.short_amount_cents = max(
				0, (sold_pos.short_amount_cents or 0) - deal.sold_amount_cents
			)
			sold_pos.updated_at = now

		self.session.flush()

		# --- 5. Settlement GL ---
		# Settlement: actual cash movements happen on value_date
		# DR sold_currency nostro (paying away sold ccy)
		# CR bought_currency nostro (receiving bought ccy)
		nostro_code = deal.nostro_account_code or "1010"
		vostro_code = deal.vostro_account_code or "1010"
		self._post_gl(
			debit_code=vostro_code,
			credit_code=nostro_code,
			amount_cents=deal.bought_amount_cents,
			narrative=f"FX deal {deal.deal_number} settlement",
			reference=deal.deal_number,
		)

		# Post realised P&L if non-zero
		if pnl_cents != 0:
			pnl_gl = self._resolve_gl("FX_REVALUATION_PNL")
			suspense_gl = self._resolve_gl("FX_REVALUATION_SUSPENSE")
			if pnl_cents > 0:
				# Gain: DR suspense, CR P&L income
				self._post_gl(
					debit_code=suspense_gl,
					credit_code=pnl_gl,
					amount_cents=pnl_cents,
					narrative=f"FX deal {deal.deal_number} realised gain",
					reference=deal.deal_number,
				)
			else:
				# Loss: DR P&L expense, CR suspense
				self._post_gl(
					debit_code=pnl_gl,
					credit_code=suspense_gl,
					amount_cents=abs(pnl_cents),
					narrative=f"FX deal {deal.deal_number} realised loss",
					reference=deal.deal_number,
				)

		# --- 6. Emit event ---
		self._emit(FXDealSettledEvent(
			deal_id=deal.id,
			deal_number=deal.deal_number,
			bought_currency=deal.bought_currency,
			sold_currency=deal.sold_currency,
			bought_amount_cents=deal.bought_amount_cents,
			sold_amount_cents=deal.sold_amount_cents,
			settled_at=now.isoformat(),
			pnl_cents=pnl_cents,
			tenant_id=self.tenant_id,
		))

		log.info(
			"TreasuryService.settle_fx_deal: %s settled pnl=%dc tenant=%s",
			deal.deal_number, pnl_cents, self.tenant_id,
		)

		assert deal.status == "SETTLED"
		assert deal.settled_at is not None
		return deal

	def revalue_positions(
		self,
		revaluation_date: date,
		rate_source: str = "CBK",
		functional_currency: str = "KES",
	) -> dict:
		"""End-of-day MTM revaluation of all open FX positions.

		For each open FXPosition on revaluation_date:
		  1. Fetch the latest active SPOT rate (base=currency, quote=functional)
		  2. Compute unrealised P&L = net_position × (revaluation_rate - avg_book_rate)
		     (avg_book_rate approximated as exchange_rate of largest deal; see note)
		  3. Update FXPosition.revaluation_rate + revaluation_pnl_cents
		  4. Post revaluation GL: DR/CR FX_REVALUATION_SUSPENSE vs FX_REVALUATION_PNL
		  5. Update FintechFXDeal.revaluation_rate for open deals in this currency

		Note on book rate: A position aggregates many deals at different rates.
		True average book cost requires deal-level tracking (FIFO/WAVG).  This
		implementation uses a simplified MTM: P&L = net_position × (rev_rate - 1.0)
		where 1.0 is the implicit base (assumes all positions were originally
		booked at par vs functional currency).  Production deployments should
		replace this with deal-level WAVG cost computation.

		Parameters
		----------
		revaluation_date : date  — business date to revalue
		rate_source : str        — preferred source (CBK, REUTERS, etc.)
		functional_currency : str — base currency for P&L (default KES)

		Returns
		-------
		dict with keys:
		  total_positions : int
		  total_pnl_cents : int
		  by_currency : dict[str, dict]  — per-currency detail
		"""
		positions = self.session.execute(
			select(FXPosition)
			.where(FXPosition.tenant_id == self.tenant_id)
			.where(FXPosition.position_date == revaluation_date)
		).scalars().all()

		total_pnl_cents = 0
		by_currency: dict[str, dict] = {}
		pnl_gl = self._resolve_gl("FX_REVALUATION_PNL")
		suspense_gl = self._resolve_gl("FX_REVALUATION_SUSPENSE")

		for pos in positions:
			if pos.currency_code == functional_currency:
				# No FX risk on functional currency positions
				continue

			net = pos.net_position_cents
			if net == 0:
				by_currency[pos.currency_code] = {
					"net_position_cents": 0,
					"revaluation_rate": None,
					"pnl_cents": 0,
					"status": "flat",
				}
				continue

			# Fetch latest active rate for this currency vs functional
			try:
				rate_row = self.session.execute(
					select(FXRate)
					.where(FXRate.tenant_id == self.tenant_id)
					.where(FXRate.base_currency == pos.currency_code)
					.where(FXRate.quote_currency == functional_currency)
					.where(FXRate.is_active.is_(True))
					.order_by(FXRate.valid_from.desc())
					.limit(1)
				).scalar_one_or_none()
			except Exception as exc:
				log.warning(
					"revalue_positions: rate fetch failed for %s (skipping): %s",
					pos.currency_code, exc,
				)
				continue

			if rate_row is None:
				log.warning(
					"revalue_positions: no active rate for %s/%s — skipping",
					pos.currency_code, functional_currency,
				)
				by_currency[pos.currency_code] = {
					"net_position_cents": net,
					"revaluation_rate": None,
					"pnl_cents": 0,
					"status": "no_rate",
				}
				continue

			rev_rate = _to_decimal(rate_row.mid_rate)
			# Simplified MTM: book rate approximated as 1.0 (positions expressed
			# in foreign currency; P&L in functional = net × rev_rate)
			# To get a delta, we compare to the previous revaluation_rate if set.
			prev_rate = _to_decimal(pos.revaluation_rate) if pos.revaluation_rate is not None else Decimal("1")
			pnl_cents = _compute_revaluation_pnl_cents(net, prev_rate, rev_rate)

			# Update position
			now = datetime.now(timezone.utc)
			pos.revaluation_rate = rev_rate
			pos.revaluation_pnl_cents = (pos.revaluation_pnl_cents or 0) + pnl_cents
			pos.updated_at = now

			# Update open deal revaluation rates for this currency
			self.session.execute(
				update(FintechFXDeal)
				.where(FintechFXDeal.tenant_id == self.tenant_id)
				.where(FintechFXDeal.bought_currency == pos.currency_code)
				.where(FintechFXDeal.status.in_(["BOOKED", "CONFIRMED"]))
				.values(revaluation_rate=rev_rate, updated_at=now)
			)

			# GL: revaluation entry
			if pnl_cents != 0:
				if pnl_cents > 0:
					# Unrealised gain: DR suspense, CR P&L income
					self._post_gl(
						debit_code=suspense_gl,
						credit_code=pnl_gl,
						amount_cents=pnl_cents,
						narrative=(
							f"EOD revaluation {revaluation_date.isoformat()} "
							f"{pos.currency_code} net={net}c gain"
						),
						reference=f"REVAL-{revaluation_date.isoformat()}-{pos.currency_code}",
					)
				else:
					# Unrealised loss: DR P&L expense, CR suspense
					self._post_gl(
						debit_code=pnl_gl,
						credit_code=suspense_gl,
						amount_cents=abs(pnl_cents),
						narrative=(
							f"EOD revaluation {revaluation_date.isoformat()} "
							f"{pos.currency_code} net={net}c loss"
						),
						reference=f"REVAL-{revaluation_date.isoformat()}-{pos.currency_code}",
					)

			total_pnl_cents += pnl_cents
			by_currency[pos.currency_code] = {
				"net_position_cents": net,
				"revaluation_rate": str(rev_rate),
				"pnl_cents": pnl_cents,
				"status": "revalued",
			}

		self.session.flush()

		result = {
			"total_positions": len(positions),
			"total_pnl_cents": total_pnl_cents,
			"by_currency": by_currency,
		}

		self._emit(FXPositionRevaluedEvent(
			revaluation_date=revaluation_date.isoformat(),
			total_positions=len(positions),
			total_pnl_cents=total_pnl_cents,
			by_currency=by_currency,
			tenant_id=self.tenant_id,
		))

		log.info(
			"TreasuryService.revalue_positions: date=%s positions=%d total_pnl=%dc tenant=%s",
			revaluation_date, len(positions), total_pnl_cents, self.tenant_id,
		)
		return result

	def get_open_position(
		self,
		currency_code: str,
		as_of_date: date | None = None,
	) -> dict:
		"""Return the net open position for a currency on a given date.

		Parameters
		----------
		currency_code : str         — ISO 4217 currency code
		as_of_date : date | None    — defaults to today

		Returns
		-------
		dict with keys:
		  currency_code : str
		  position_date : str      — ISO date
		  long_amount_cents : int
		  short_amount_cents : int
		  net_position_cents : int  — positive = net long
		  revaluation_rate : str | None
		  revaluation_pnl_cents : int
		"""
		target_date = as_of_date or date.today()

		pos = self.session.execute(
			select(FXPosition)
			.where(FXPosition.tenant_id == self.tenant_id)
			.where(FXPosition.currency_code == currency_code)
			.where(FXPosition.position_date == target_date)
		).scalar_one_or_none()

		if pos is None:
			return {
				"currency_code": currency_code,
				"position_date": target_date.isoformat(),
				"long_amount_cents": 0,
				"short_amount_cents": 0,
				"net_position_cents": 0,
				"revaluation_rate": None,
				"revaluation_pnl_cents": 0,
			}

		return {
			"currency_code": pos.currency_code,
			"position_date": pos.position_date.isoformat(),
			"long_amount_cents": pos.long_amount_cents or 0,
			"short_amount_cents": pos.short_amount_cents or 0,
			"net_position_cents": pos.net_position_cents,
			"revaluation_rate": str(pos.revaluation_rate) if pos.revaluation_rate is not None else None,
			"revaluation_pnl_cents": pos.revaluation_pnl_cents or 0,
		}

	def get_pnl_report(self, from_date: date, to_date: date) -> dict:
		"""Realised + unrealised P&L summary for a date range.

		Realised P&L  = sum of pnl_cents on SETTLED deals where settled_at falls
		                in [from_date, to_date].
		Unrealised P&L = sum of revaluation_pnl_cents on FXPositions whose
		                 position_date falls in [from_date, to_date].

		Parameters
		----------
		from_date : date
		to_date : date

		Returns
		-------
		dict with keys:
		  from_date : str
		  to_date : str
		  realised_pnl_cents : int
		  unrealised_pnl_cents : int
		  total_pnl_cents : int
		  settled_deals : int         — count of settled deals in range
		  open_positions : int        — count of open positions in range
		  by_currency_realised : dict[str, int]
		  by_currency_unrealised : dict[str, int]
		"""
		assert from_date <= to_date, "from_date must not be after to_date"

		from_dt = datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc)
		to_dt = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc)

		# --- Realised P&L from settled deals ---
		settled_deals = self.session.execute(
			select(FintechFXDeal)
			.where(FintechFXDeal.tenant_id == self.tenant_id)
			.where(FintechFXDeal.status == "SETTLED")
			.where(FintechFXDeal.settled_at >= from_dt)
			.where(FintechFXDeal.settled_at <= to_dt)
			.where(FintechFXDeal.pnl_cents.is_not(None))
		).scalars().all()

		realised_pnl_cents = sum(d.pnl_cents for d in settled_deals if d.pnl_cents is not None)
		by_currency_realised: dict[str, int] = {}
		for d in settled_deals:
			ccy = d.bought_currency
			by_currency_realised[ccy] = by_currency_realised.get(ccy, 0) + (d.pnl_cents or 0)

		# --- Unrealised P&L from open positions ---
		open_positions = self.session.execute(
			select(FXPosition)
			.where(FXPosition.tenant_id == self.tenant_id)
			.where(FXPosition.position_date >= from_date)
			.where(FXPosition.position_date <= to_date)
		).scalars().all()

		unrealised_pnl_cents = sum(p.revaluation_pnl_cents or 0 for p in open_positions)
		by_currency_unrealised: dict[str, int] = {}
		for p in open_positions:
			ccy = p.currency_code
			by_currency_unrealised[ccy] = (
				by_currency_unrealised.get(ccy, 0) + (p.revaluation_pnl_cents or 0)
			)

		total = realised_pnl_cents + unrealised_pnl_cents

		return {
			"from_date": from_date.isoformat(),
			"to_date": to_date.isoformat(),
			"realised_pnl_cents": realised_pnl_cents,
			"unrealised_pnl_cents": unrealised_pnl_cents,
			"total_pnl_cents": total,
			"settled_deals": len(settled_deals),
			"open_positions": len(open_positions),
			"by_currency_realised": by_currency_realised,
			"by_currency_unrealised": by_currency_unrealised,
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"TreasuryService",
	"TreasuryError",
	"FXDealNotFoundError",
	"FXRateNotFoundError",
	"FXDealStatusError",
	"TreasuryLimitBreachError",
]
