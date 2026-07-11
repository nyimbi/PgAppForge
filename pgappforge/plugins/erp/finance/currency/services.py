"""
pgappforge/plugins/erp/finance/currency/services.py

Exchange-rate management and Decimal-safe conversion helpers.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa


class CurrencyServiceError(Exception):
	"""Base error for finance currency operations."""


class CurrencyRateNotFoundError(CurrencyServiceError):
	"""No exchange rate is available for the requested pair/date."""


class ExchangeRateService:
	"""Tenant-scoped exchange-rate lookup and conversion service."""

	def set_rate(
		self,
		tenant_id: str,
		from_currency: str,
		to_currency: str,
		rate: Decimal | str | int,
		effective_date: date,
		source: str,
		session: Any,
	) -> Any:
		"""Create an ExchangeRate row and return it."""
		from pgappforge.plugins.erp.finance.currency.models import ExchangeRate

		from_ccy = self._currency_code(from_currency)
		to_ccy = self._currency_code(to_currency)
		rate_value = self._rate_decimal(rate)
		eff_date = self._date(effective_date)

		row = ExchangeRate(
			tenant_id=str(tenant_id),
			from_currency=from_ccy,
			to_currency=to_ccy,
			rate=rate_value,
			effective_date=eff_date,
			source=(source or "manual"),
		)
		session.add(row)
		session.flush()
		return row

	def get_rate(
		self,
		tenant_id: str,
		from_currency: str,
		to_currency: str,
		as_of_date: date,
		session: Any,
	) -> Decimal:
		"""Return the latest rate effective on or before as_of_date."""
		from pgappforge.plugins.erp.finance.currency.models import ExchangeRate

		from_ccy = self._currency_code(from_currency)
		to_ccy = self._currency_code(to_currency)
		if from_ccy == to_ccy:
			return Decimal("1")

		cutoff = self._date(as_of_date)
		row = session.execute(
			sa.select(ExchangeRate)
			.where(ExchangeRate.tenant_id == str(tenant_id))
			.where(ExchangeRate.from_currency == from_ccy)
			.where(ExchangeRate.to_currency == to_ccy)
			.where(ExchangeRate.effective_date <= cutoff)
			.order_by(sa.desc(ExchangeRate.effective_date), sa.desc(ExchangeRate.created_at))
			.limit(1)
		).scalar_one_or_none()

		if row is None:
			raise CurrencyRateNotFoundError(
				f"No exchange rate for {from_ccy}/{to_ccy} on or before {cutoff}"
			)
		return Decimal(str(row.rate))

	def convert(
		self,
		amount_cents: int,
		from_currency: str,
		to_currency: str,
		as_of_date: date,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Convert integer cents into target-currency cents."""
		if not isinstance(amount_cents, int) or isinstance(amount_cents, bool):
			raise TypeError("amount_cents must be int")

		from_ccy = self._currency_code(from_currency)
		to_ccy = self._currency_code(to_currency)
		if from_ccy == to_ccy:
			return amount_cents

		rate = self.get_rate(tenant_id, from_ccy, to_ccy, as_of_date, session)
		converted = Decimal(amount_cents) * rate
		return int(converted.to_integral_value(rounding=ROUND_HALF_UP))

	def get_rate_history(
		self,
		tenant_id: str,
		from_currency: str,
		to_currency: str,
		session: Any,
		days: int = 90,
	) -> list[Any]:
		"""Return recent rates for trend display."""
		from pgappforge.plugins.erp.finance.currency.models import ExchangeRate

		from_ccy = self._currency_code(from_currency)
		to_ccy = self._currency_code(to_currency)
		days_int = max(1, int(days))
		start_date = datetime.now(timezone.utc).date() - timedelta(days=days_int)

		return list(
			session.execute(
				sa.select(ExchangeRate)
				.where(ExchangeRate.tenant_id == str(tenant_id))
				.where(ExchangeRate.from_currency == from_ccy)
				.where(ExchangeRate.to_currency == to_ccy)
				.where(ExchangeRate.effective_date >= start_date)
				.order_by(sa.desc(ExchangeRate.effective_date), sa.desc(ExchangeRate.created_at))
			).scalars().all()
		)

	@staticmethod
	def _currency_code(value: str) -> str:
		code = str(value or "").strip().upper()
		if len(code) != 3 or not code.isalpha():
			raise ValueError(f"Currency code must be a 3-character ISO code: {value!r}")
		return code

	@staticmethod
	def _date(value: date) -> date:
		if isinstance(value, datetime):
			return value.date()
		if not isinstance(value, date):
			raise TypeError("date value must be a date")
		return value

	@staticmethod
	def _rate_decimal(value: Decimal | str | int) -> Decimal:
		rate = value if isinstance(value, Decimal) else Decimal(str(value))
		if rate <= Decimal("0"):
			raise ValueError("rate must be greater than zero")
		return rate


__all__ = [
	"CurrencyRateNotFoundError",
	"CurrencyServiceError",
	"ExchangeRateService",
]
