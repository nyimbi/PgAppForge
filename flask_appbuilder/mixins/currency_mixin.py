"""
currency_mixin.py

CurrencyMixin and ExchangeRate model for Flask-AppBuilder applications.

Provides precise monetary amount storage with multi-currency support,
exchange rate tracking, arithmetic operators, and locale-aware formatting.

Dependencies:
	- SQLAlchemy 2.x (with 1.x compat shim)
	- Flask-AppBuilder Model base
	- requests (exchange rate API)
	- babel (currency formatting)

Author: Nyimbi Odero
Date: 25/08/2024
Version: 2.0 (SQLAlchemy 2.x, Python 3.12)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

import requests
from babel.numbers import format_currency, parse_decimal
from flask_appbuilder import Model
from sqlalchemy import (
	CheckConstraint,
	DateTime,
	Index,
	Integer,
	Numeric,
	String,
	select,
	or_,
)
from sqlalchemy.ext.mutable import MutableDict

# SQLAlchemy 2.x preferred; fall back to 1.x patterns gracefully
try:
	from sqlalchemy.orm import mapped_column, Mapped, DeclarativeBase
	_SA2 = True
except ImportError:
	_SA2 = False

try:
	from sqlalchemy.dialects.postgresql import JSONB as _JSONB
	_HAS_JSONB = True
except ImportError:
	from sqlalchemy import JSON as _JSONB
	_HAS_JSONB = False

from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship, validates, Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Currency registry
# ---------------------------------------------------------------------------

SUPPORTED_CURRENCIES: dict[str, dict[str, Any]] = {
	"USD": {"decimal_places": 2, "symbol": "$"},
	"EUR": {"decimal_places": 2, "symbol": "€"},
	"GBP": {"decimal_places": 2, "symbol": "£"},
	"JPY": {"decimal_places": 0, "symbol": "¥"},
	"CHF": {"decimal_places": 2, "symbol": "Fr"},
	"CAD": {"decimal_places": 2, "symbol": "CA$"},
	"AUD": {"decimal_places": 2, "symbol": "A$"},
	"CNY": {"decimal_places": 2, "symbol": "¥"},
	"HKD": {"decimal_places": 2, "symbol": "HK$"},
	"SGD": {"decimal_places": 2, "symbol": "S$"},
	"KES": {"decimal_places": 2, "symbol": "KSh"},
	"NGN": {"decimal_places": 2, "symbol": "₦"},
	"ZAR": {"decimal_places": 2, "symbol": "R"},
	"GHS": {"decimal_places": 2, "symbol": "₵"},
}


class InvalidCurrencyError(ValueError):
	"""Raised when an unsupported or malformed currency code is used."""
	pass


# ---------------------------------------------------------------------------
# CurrencyMixin
# ---------------------------------------------------------------------------

class CurrencyMixin:
	"""
	SQLAlchemy mixin for monetary amount fields with full currency support.

	Adds three columns to any model:
	  - amount   : NUMERIC(18, 6) — stored with full precision
	  - currency : CHAR(3)        — ISO 4217 code, validated on assignment
	  - metadata_: JSONB/JSON     — extensible per-record currency metadata

	Class-level configuration (override on the concrete model or via env):
	  __default_currency__              — ISO code, default "USD"
	  __exchange_rate_api_key__         — openexchangerates.org app_id
	  __exchange_rate_api_url__         — exchange rate endpoint
	  __exchange_rate_cache_duration__  — seconds before cache expires (int)

	Features:
	  - Precise storage via NUMERIC(18, 6)
	  - Currency validation on ORM assignment
	  - Live exchange rates with LRU cache + TTL invalidation
	  - Historical rate lookup via ExchangeRate model
	  - Arithmetic operators (+, -, *, /) with auto-conversion
	  - Locale-aware formatting via Babel
	  - Currency-standard rounding (ROUND_HALF_UP)
	  - Table-level CHECK constraints and index on currency column
	"""

	__default_currency__: str = os.getenv("DEFAULT_CURRENCY", "USD")
	__exchange_rate_api_key__: str = os.getenv(
		"EXCHANGE_RATE_API_KEY", "your_api_key_here"
	)
	__exchange_rate_api_url__: str = os.getenv(
		"EXCHANGE_RATE_API_URL",
		"https://openexchangerates.org/api/latest.json",
	)
	__exchange_rate_cache_duration__: int = int(
		os.getenv("EXCHANGE_RATE_CACHE_DURATION", "3600")
	)

	# ------------------------------------------------------------------
	# Declared columns
	# ------------------------------------------------------------------

	@declared_attr
	def amount(cls):
		"""Precise monetary amount — NUMERIC(18, 6), never NULL."""
		return _make_column(
			Numeric(precision=18, scale=6),
			nullable=False,
			default=Decimal("0.00"),
			server_default="0",
		)

	@declared_attr
	def currency(cls):
		"""ISO 4217 currency code — CHAR(3), validated on assignment."""
		return _make_column(
			String(3),
			nullable=False,
			default=cls.__default_currency__,
			server_default=cls.__default_currency__,
		)

	@declared_attr
	def metadata_(cls):
		"""Per-record currency metadata stored as JSONB (or JSON on non-PG)."""
		return _make_column(
			"metadata",
			MutableDict.as_mutable(_JSONB()),
			nullable=True,
			default=dict,
			server_default="{}",
		)

	@declared_attr
	def __table_args__(cls):
		"""Database-enforced currency validity, non-negative amount, and lookup index."""
		currency_list = list(SUPPORTED_CURRENCIES.keys())
		return (
			CheckConstraint(
				f"currency IN ({', '.join(repr(c) for c in currency_list)})",
				name=f"valid_currency_{cls.__tablename__}",
			),
			CheckConstraint(
				"amount >= 0",
				name=f"positive_amount_{cls.__tablename__}",
			),
			Index(f"ix_{cls.__tablename__}_currency", "currency"),
		)

	# ------------------------------------------------------------------
	# Class lifecycle
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Validate class-level currency configuration after mapper setup."""
		if not hasattr(cls, "__default_currency__"):
			raise ValueError(
				f"__default_currency__ must be defined on {cls.__name__}"
			)
		if cls.__default_currency__ not in SUPPORTED_CURRENCIES:
			raise InvalidCurrencyError(
				f"Invalid default currency '{cls.__default_currency__}' on {cls.__name__}; "
				f"supported: {sorted(SUPPORTED_CURRENCIES)}"
			)

	# ------------------------------------------------------------------
	# ORM validators
	# ------------------------------------------------------------------

	@validates("currency")
	def validate_currency(self, key: str, value: str) -> str:
		"""Reject unknown ISO codes before they reach the database."""
		if value not in SUPPORTED_CURRENCIES:
			raise InvalidCurrencyError(
				f"Unsupported currency '{value}'; "
				f"supported: {sorted(SUPPORTED_CURRENCIES)}"
			)
		return value.upper()

	@validates("amount")
	def validate_amount(self, key: str, value: Any) -> Decimal:
		"""Coerce and normalise monetary input to Decimal."""
		try:
			if isinstance(value, str):
				# Babel's parse_decimal handles locale-formatted strings
				value = parse_decimal(value)
			return Decimal(str(value)).normalize()
		except (InvalidOperation, TypeError) as exc:
			raise ValueError(f"Invalid monetary amount: {value!r}") from exc

	# ------------------------------------------------------------------
	# Exchange rate access
	# ------------------------------------------------------------------

	# Module-level cache: maps (api_url, api_key) -> (rates_dict, fetched_at)
	_rate_cache: dict[tuple[str, str], tuple[dict[str, Decimal], datetime]] = {}

	@classmethod
	def get_exchange_rates(cls) -> dict[str, Decimal] | None:
		"""
		Return current exchange rates, refreshing when the TTL has elapsed.

		Rates are keyed by ISO currency code and expressed relative to USD
		(the API base currency).  Only currencies in SUPPORTED_CURRENCIES
		are retained.

		Returns None on network / API error — callers must handle this.
		"""
		cache_key = (cls.__exchange_rate_api_url__, cls.__exchange_rate_api_key__)
		now = datetime.utcnow()
		ttl = timedelta(seconds=cls.__exchange_rate_cache_duration__)

		cached = cls._rate_cache.get(cache_key)
		if cached is not None:
			rates, fetched_at = cached
			if now - fetched_at < ttl:
				return rates

		try:
			response = requests.get(
				cls.__exchange_rate_api_url__,
				params={"app_id": cls.__exchange_rate_api_key__},
				timeout=10,
			)
			response.raise_for_status()
			raw = response.json().get("rates", {})
			rates = {
				k: Decimal(str(v))
				for k, v in raw.items()
				if k in SUPPORTED_CURRENCIES
			}
			cls._rate_cache[cache_key] = (rates, now)
			return rates
		except Exception as exc:
			logger.error("Failed to fetch exchange rates: %s", exc)
			# Return stale cache rather than None if available
			if cached is not None:
				logger.warning("Returning stale exchange rate cache")
				return cached[0]
			return None

	@classmethod
	def invalidate_rate_cache(cls) -> None:
		"""Force the next get_exchange_rates() call to re-fetch."""
		cls._rate_cache.clear()

	# ------------------------------------------------------------------
	# Currency conversion
	# ------------------------------------------------------------------

	def convert_to(
		self,
		target_currency: str,
		rate_date: datetime | None = None,
		session: Session | None = None,
	) -> Decimal:
		"""
		Convert self.amount to target_currency.

		Resolution order:
		  1. Historical ExchangeRate row (when rate_date + session provided)
		  2. Live rates from API / cache
		  3. Raises ValueError if neither is available

		Conversion always triangulates through USD as the base currency.

		Args:
			target_currency: ISO 4217 destination code.
			rate_date:       Look up a historical rate valid at this datetime.
			session:         SQLAlchemy session required for historical lookup.

		Returns:
			Converted Decimal amount (not rounded to currency decimals yet).

		Raises:
			InvalidCurrencyError: Unknown target currency.
			ValueError:           Rate unavailable.
		"""
		target_currency = target_currency.upper()
		if target_currency not in SUPPORTED_CURRENCIES:
			raise InvalidCurrencyError(
				f"Invalid target currency: {target_currency}"
			)
		if self.currency == target_currency:
			return self.amount

		# 1. Historical lookup
		if rate_date is not None and session is not None:
			try:
				rate = ExchangeRate.get_rate(
					self.currency, target_currency, rate_date, session=session
				)
				if rate is not None:
					return (self.amount * rate).normalize()
			except Exception as exc:
				logger.warning("Historical rate lookup failed: %s", exc)

		# 2. Live / cached rates
		rates = self.get_exchange_rates()
		if not rates:
			raise ValueError(
				"Exchange rates unavailable and no historical rate found"
			)

		if self.currency not in rates:
			raise ValueError(
				f"No exchange rate available for source currency {self.currency}"
			)
		if target_currency not in rates:
			raise ValueError(
				f"No exchange rate available for target currency {target_currency}"
			)

		# Triangulate through USD
		usd_amount = self.amount / rates[self.currency]
		converted = usd_amount * rates[target_currency]
		return converted.normalize()

	# ------------------------------------------------------------------
	# Formatting
	# ------------------------------------------------------------------

	def format(
		self,
		locale: str = "en_US",
		decimal_places: int | None = None,
	) -> str:
		"""
		Return a locale-formatted currency string via Babel.

		Args:
			locale:         BCP 47 locale tag (e.g. "en_US", "de_DE").
			decimal_places: Override the currency-standard decimal places.

		Returns:
			Formatted string such as "$1,234.56" or "¥1,235".
			Falls back to "{CURRENCY} {amount}" on Babel errors.
		"""
		try:
			if decimal_places is None:
				decimal_places = SUPPORTED_CURRENCIES[self.currency]["decimal_places"]
			quantised = self.amount.quantize(
				Decimal(10) ** -decimal_places, rounding=ROUND_HALF_UP
			)
			return format_currency(quantised, self.currency, locale=locale)
		except Exception as exc:
			logger.error("Currency formatting failed: %s", exc)
			return f"{self.currency} {self.amount}"

	# ------------------------------------------------------------------
	# Arithmetic operators
	# ------------------------------------------------------------------

	def __add__(self, other: CurrencyMixin) -> CurrencyMixin:
		"""Add two monetary values, converting other to self.currency if needed."""
		_assert_same_type(self, other, "add")
		try:
			other_amount = (
				other.amount if self.currency == other.currency
				else other.convert_to(self.currency)
			)
			return type(self)(amount=self.amount + other_amount, currency=self.currency)
		except Exception as exc:
			raise ValueError(f"Addition failed: {exc}") from exc

	def __sub__(self, other: CurrencyMixin) -> CurrencyMixin:
		"""Subtract two monetary values, converting other to self.currency if needed."""
		_assert_same_type(self, other, "subtract")
		try:
			other_amount = (
				other.amount if self.currency == other.currency
				else other.convert_to(self.currency)
			)
			return type(self)(amount=self.amount - other_amount, currency=self.currency)
		except Exception as exc:
			raise ValueError(f"Subtraction failed: {exc}") from exc

	def __mul__(self, factor: int | float | Decimal) -> CurrencyMixin:
		"""Scale a monetary amount by a dimensionless factor."""
		try:
			return type(self)(
				amount=self.amount * Decimal(str(factor)),
				currency=self.currency,
			)
		except Exception as exc:
			raise ValueError(f"Multiplication failed: {exc}") from exc

	def __truediv__(self, divisor: int | float | Decimal) -> CurrencyMixin:
		"""Divide a monetary amount by a dimensionless divisor."""
		try:
			d = Decimal(str(divisor))
			if d == 0:
				raise ValueError("Division by zero")
			return type(self)(amount=self.amount / d, currency=self.currency)
		except ValueError:
			raise
		except Exception as exc:
			raise ValueError(f"Division failed: {exc}") from exc

	def __repr__(self) -> str:
		return f"<{type(self).__name__} amount={self.amount} currency={self.currency}>"

	# ------------------------------------------------------------------
	# Rounding
	# ------------------------------------------------------------------

	def round(self, places: int | None = None) -> CurrencyMixin:
		"""
		Return a new instance rounded to the currency-standard (or given) decimal places.

		Args:
			places: Decimal places; None uses the currency registry default.

		Returns:
			New instance of the same concrete type with rounded amount.
		"""
		try:
			if places is None:
				places = SUPPORTED_CURRENCIES[self.currency]["decimal_places"]
			rounded = self.amount.quantize(
				Decimal(10) ** -places, rounding=ROUND_HALF_UP
			)
			return type(self)(amount=rounded, currency=self.currency)
		except Exception as exc:
			raise ValueError(f"Rounding failed: {exc}") from exc

	# ------------------------------------------------------------------
	# Serialisation helpers
	# ------------------------------------------------------------------

	def to_dict(self) -> dict[str, Any]:
		"""Return a JSON-serialisable dict representation."""
		return {
			"amount": str(self.amount),
			"currency": self.currency,
			"formatted": self.format(),
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> CurrencyMixin:
		"""Reconstruct a (detached) mixin instance from to_dict() output."""
		return cls(
			amount=Decimal(data["amount"]),
			currency=data["currency"],
		)


# ---------------------------------------------------------------------------
# ExchangeRate model
# ---------------------------------------------------------------------------

class ExchangeRate(Model):
	"""
	Persistent store for historical and current exchange rates.

	Supports multiple rate sources, validity windows, and atomic bulk updates.

	Columns:
	  id            — PK
	  from_currency — ISO source code
	  to_currency   — ISO target code
	  rate          — NUMERIC(18, 6) multiplier (from → to)
	  date          — timestamp the rate was fetched / recorded
	  valid_from    — start of validity window
	  valid_to      — end of validity window (NULL = still valid)
	  source        — origin tag e.g. "api", "manual", "import"
	  metadata      — JSONB extension blob
	  created_at    — insert timestamp
	  updated_at    — last-update timestamp (auto via onupdate)
	"""

	__tablename__ = "nx_exchange_rates"
	__table_args__ = (
		CheckConstraint("rate > 0", name="positive_rate"),
		Index(
			"ix_exchange_rates_lookup",
			"from_currency", "to_currency", "date",
		),
	)

	id = _make_column(Integer, primary_key=True)
	from_currency = _make_column(String(3), nullable=False)
	to_currency = _make_column(String(3), nullable=False)
	rate = _make_column(Numeric(precision=18, scale=6), nullable=False)
	date = _make_column(DateTime, default=datetime.utcnow, nullable=False)
	valid_from = _make_column(DateTime, nullable=False)
	valid_to = _make_column(DateTime, nullable=True)
	source = _make_column(String(50), nullable=False, default="api")
	metadata = _make_column(
		MutableDict.as_mutable(_JSONB()),
		nullable=True,
		default=dict,
		server_default="{}",
	)
	created_at = _make_column(DateTime, nullable=False, default=datetime.utcnow)
	updated_at = _make_column(DateTime, onupdate=datetime.utcnow)

	# ------------------------------------------------------------------
	# Queries
	# ------------------------------------------------------------------

	@classmethod
	def get_rate(
		cls,
		from_currency: str,
		to_currency: str,
		date: datetime | None = None,
		session: Session | None = None,
	) -> Decimal | None:
		"""
		Retrieve an exchange rate from the database.

		Args:
			from_currency: Source ISO code.
			to_currency:   Target ISO code.
			date:          If given, return the rate valid at that datetime.
			session:       SQLAlchemy 2.x Session; falls back to legacy
			               cls.query when not provided.

		Returns:
			Decimal rate or None if no matching row exists.
		"""
		if from_currency.upper() == to_currency.upper():
			return Decimal("1.0")

		fc = from_currency.upper()
		tc = to_currency.upper()

		if session is not None:
			stmt = (
				select(cls)
				.where(cls.from_currency == fc, cls.to_currency == tc)
				.order_by(cls.date.desc())
				.limit(1)
			)
			if date is not None:
				stmt = stmt.where(
					cls.valid_from <= date,
					or_(cls.valid_to.is_(None), cls.valid_to >= date),
				)
			row = session.execute(stmt).scalar_one_or_none()
		else:
			# Legacy Flask-AppBuilder / SQLAlchemy 1.x path
			query = cls.query.filter_by(from_currency=fc, to_currency=tc)
			if date is not None:
				query = query.filter(
					cls.valid_from <= date,
					or_(cls.valid_to.is_(None), cls.valid_to >= date),
				)
			row = query.order_by(cls.date.desc()).first()

		return row.rate if row else None

	@classmethod
	def update_rates(
		cls,
		rates: dict[str, float | Decimal],
		session: Session,
	) -> None:
		"""
		Atomically replace live exchange rates in the database.

		Steps:
		  1. Expire all rows whose valid_to is NULL (mark end of validity).
		  2. Insert fresh rows for every supported currency in `rates`.
		  3. Commit; rollback on any error.

		Args:
			rates:   Dict mapping ISO code → rate relative to USD.
			session: Active SQLAlchemy session (2.x preferred).

		Raises:
			Re-raises any database exception after rollback.
		"""
		try:
			now = datetime.utcnow()

			# Expire current live rates
			live = session.execute(
				select(cls).where(cls.valid_to.is_(None))
			).scalars().all()
			for row in live:
				row.valid_to = now
				row.updated_at = now

			# Insert new rates
			for currency, rate in rates.items():
				if currency == "USD" or currency not in SUPPORTED_CURRENCIES:
					continue
				session.add(
					cls(
						from_currency="USD",
						to_currency=currency,
						rate=Decimal(str(rate)),
						date=now,
						valid_from=now,
						valid_to=None,
						source="api",
						metadata={
							"source_timestamp": now.isoformat(),
							"update_type": "api",
						},
					)
				)

			session.commit()
			logger.info("Exchange rates updated: %d currencies", len(rates))
		except Exception as exc:
			session.rollback()
			logger.error("Failed to update exchange rates: %s", exc)
			raise

	def __repr__(self) -> str:
		return (
			f"<ExchangeRate {self.from_currency}->{self.to_currency} "
			f"rate={self.rate} valid_from={self.valid_from}>"
		)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_column(type_or_name: Any, *args: Any, **kwargs: Any):
	"""
	Thin wrapper that delegates to sqlalchemy.Column.

	Accepts both positional-type and name+type signatures, mirroring the
	Column() call signatures used throughout the module.
	"""
	from sqlalchemy import Column
	return Column(type_or_name, *args, **kwargs)


def _assert_same_type(a: Any, b: Any, op: str) -> None:
	"""Raise TypeError if b is not an instance of a's concrete class."""
	if not isinstance(b, type(a)):
		raise TypeError(
			f"Cannot {op} {type(a).__name__!r} and {type(b).__name__!r}"
		)
