"""
pgappforge/plugins/erp/foundation/services.py

FoundationService — stateless business logic for the Foundation plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
This makes them safe to call from background jobs, CLI commands, and tests.

Monetary rules:
  - All amounts are integer cents (or kobo, fils, etc. — smallest unit).
  - get_exchange_rate() returns Decimal(20,8) — callers convert as needed.
  - convert_amount() returns int (rounds half-up).

Usage
-----
    svc = FoundationService()
    party = svc.resolve_party("Acme Corp", session, tenant_id="...")
    rate  = svc.get_exchange_rate("USD", "NGN", date.today(), session)
    ngn   = svc.convert_amount(10_000, "USD", "NGN", date.today(), session)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


class FoundationServiceError(Exception):
	"""Raised for domain-level errors in FoundationService."""


class PartyNotFoundError(FoundationServiceError):
	"""No Party matched the given identifier."""


class ExchangeRateNotFoundError(FoundationServiceError):
	"""No ExchangeRate available for the requested pair/date."""


class FoundationService:
	"""Stateless service class for Foundation domain operations.

	Instantiate once per app (or per request — it holds no state).
	All public methods accept a SQLAlchemy Session as their last positional
	argument so callers control transaction boundaries.
	"""

	# ------------------------------------------------------------------
	# Party resolution
	# ------------------------------------------------------------------

	def resolve_party(
		self,
		identifier: str,
		session: Any,
		tenant_id: str | None = None,
	) -> Any:
		"""Find a Party by name, tax_id, LEI, VAT number, or registration number.

		Tries exact matches in the following priority order:
		  1. id (UUID string)
		  2. lei
		  3. tax_id
		  4. vat_number
		  5. registration_number
		  6. legal_name (exact, case-insensitive)
		  7. name (exact, case-insensitive)

		Args:
			identifier: Any of the above fields.
			session: SQLAlchemy session.
			tenant_id: Restrict search to this tenant when provided.

		Returns:
			Party instance.

		Raises:
			PartyNotFoundError: When no party matches.
		"""
		from pgappforge.plugins.erp.foundation.models import Party

		assert identifier and identifier.strip(), "identifier must be non-empty"

		ident = identifier.strip()
		base_q = sa.select(Party).where(Party.is_active.is_(True))
		if tenant_id:
			base_q = base_q.where(Party.tenant_id == tenant_id)

		# Ordered match strategies
		strategies = [
			Party.id == ident,
			Party.lei == ident,
			Party.tax_id == ident,
			Party.vat_number == ident,
			Party.registration_number == ident,
			sa.func.lower(Party.legal_name) == ident.lower(),
			sa.func.lower(Party.name) == ident.lower(),
		]

		for predicate in strategies:
			party = session.execute(base_q.where(predicate)).scalar_one_or_none()
			if party is not None:
				return party

		raise PartyNotFoundError(
			f"No active Party found for identifier {ident!r} "
			f"(tenant={tenant_id!r})"
		)

	# ------------------------------------------------------------------
	# Party merge (deduplication)
	# ------------------------------------------------------------------

	def merge_parties(
		self,
		primary_id: str,
		duplicate_id: str,
		session: Any,
		merged_by: int | None = None,
	) -> Any:
		"""Merge *duplicate_id* into *primary_id*.

		Re-parents all child records (roles, addresses, contacts, notes,
		attachments) from the duplicate to the primary, then marks the
		duplicate inactive.  Emits a PartyMergedEvent.

		Immutable ledger rule: the duplicate Party row is NOT deleted — it is
		marked is_active=False so historical references (e.g. old invoices) remain
		valid.  Financial plugin correction entries handle re-attribution.

		Args:
			primary_id: UUID of the Party to keep.
			duplicate_id: UUID of the Party to deactivate.
			session: SQLAlchemy session (caller commits).
			merged_by: User ID performing the merge (for audit).

		Returns:
			Updated primary Party.

		Raises:
			PartyNotFoundError: If either party does not exist.
			FoundationServiceError: If primary_id == duplicate_id.
		"""
		from pgappforge.plugins.erp.foundation.models import (
			Address, Attachment, Contact, Note, Party, PartyRole,
		)
		from pgappforge.plugins.erp.foundation.events import (
			PartyMergedEvent, emit_event,
		)

		assert primary_id and duplicate_id, "Both party IDs must be provided"

		if primary_id == duplicate_id:
			raise FoundationServiceError("Cannot merge a party with itself")

		primary = session.get(Party, primary_id)
		duplicate = session.get(Party, duplicate_id)

		if primary is None:
			raise PartyNotFoundError(f"Primary party {primary_id!r} not found")
		if duplicate is None:
			raise PartyNotFoundError(f"Duplicate party {duplicate_id!r} not found")

		# Re-parent child tables
		for model_cls, fk_col in (
			(PartyRole, "party_id"),
			(Address, "party_id"),
			(Contact, "party_id"),
		):
			session.execute(
				sa.update(model_cls)
				.where(getattr(model_cls, fk_col) == duplicate_id)
				.values({fk_col: primary_id})
			)

		# Re-parent polymorphic tables (Note, Attachment) by entity_id string
		for model_cls in (Note, Attachment):
			session.execute(
				sa.update(model_cls)
				.where(model_cls.entity_type == "Party")
				.where(model_cls.entity_id == duplicate_id)
				.values(entity_id=primary_id)
			)

		# Deactivate duplicate
		duplicate.is_active = False
		duplicate.updated_at = datetime.now(timezone.utc)

		# Emit event (persisted atomically with the session)
		emit_event(
			PartyMergedEvent(
				aggregate_id=primary_id,
				aggregate_type="Party",
				tenant_id=primary.tenant_id,
				primary_id=primary_id,
				duplicate_id=duplicate_id,
			),
			session,
		)

		log.info(
			"Party merge: duplicate=%s merged into primary=%s by user=%s",
			duplicate_id, primary_id, merged_by,
		)
		return primary

	# ------------------------------------------------------------------
	# Exchange rates
	# ------------------------------------------------------------------

	def get_exchange_rate(
		self,
		from_ccy: str,
		to_ccy: str,
		rate_date: date | datetime,
		session: Any,
	) -> Decimal:
		"""Return the most recent exchange rate for (from_ccy, to_ccy) on rate_date.

		Looks for the latest row where rate_date <= requested date AND
		(expires_at IS NULL OR expires_at > NOW()).

		Identity shortcut: returns Decimal("1") when from_ccy == to_ccy.

		Args:
			from_ccy: ISO 4217 alpha-3 code.
			to_ccy: ISO 4217 alpha-3 code.
			rate_date: Date to look up (date or datetime).
			session: SQLAlchemy session.

		Returns:
			Decimal rate (20 significant digits, 8 decimal places).

		Raises:
			ExchangeRateNotFoundError: When no rate is available.
		"""
		from pgappforge.plugins.erp.foundation.models import ExchangeRate

		assert from_ccy and to_ccy, "Currency codes must be non-empty"

		if from_ccy.upper() == to_ccy.upper():
			return Decimal("1")

		# Normalise date to a timezone-aware datetime at end-of-day for comparison
		if isinstance(rate_date, date) and not isinstance(rate_date, datetime):
			cutoff = datetime(
				rate_date.year, rate_date.month, rate_date.day,
				23, 59, 59, tzinfo=timezone.utc,
			)
		else:
			cutoff = rate_date if rate_date.tzinfo else rate_date.replace(tzinfo=timezone.utc)

		now = datetime.now(timezone.utc)

		row = session.execute(
			sa.select(ExchangeRate)
			.where(ExchangeRate.from_currency == from_ccy.upper())
			.where(ExchangeRate.to_currency == to_ccy.upper())
			.where(ExchangeRate.rate_date <= cutoff)
			.where(
				sa.or_(
					ExchangeRate.expires_at.is_(None),
					ExchangeRate.expires_at > now,
				)
			)
			.order_by(sa.desc(ExchangeRate.rate_date))
			.limit(1)
		).scalar_one_or_none()

		if row is None:
			raise ExchangeRateNotFoundError(
				f"No exchange rate for {from_ccy.upper()}/{to_ccy.upper()} "
				f"on or before {rate_date}"
			)

		return Decimal(str(row.rate))

	def convert_amount(
		self,
		amount_cents: int,
		from_ccy: str,
		to_ccy: str,
		rate_date: date | datetime,
		session: Any,
	) -> int:
		"""Convert *amount_cents* from *from_ccy* to *to_ccy*.

		Uses get_exchange_rate() internally.  Result is rounded half-up to the
		nearest integer (smallest monetary unit of to_ccy).

		Args:
			amount_cents: Amount in smallest units of from_ccy (integer, no float).
			from_ccy: Source ISO 4217 code.
			to_ccy: Target ISO 4217 code.
			rate_date: Date for rate lookup.
			session: SQLAlchemy session.

		Returns:
			Converted amount in smallest units of to_ccy (integer).

		Raises:
			ExchangeRateNotFoundError: When no rate is available.
			AssertionError: When amount_cents is not an integer.
		"""
		assert isinstance(amount_cents, int), (
			f"amount_cents must be int, got {type(amount_cents).__name__}"
		)

		if from_ccy.upper() == to_ccy.upper():
			return amount_cents

		rate = self.get_exchange_rate(from_ccy, to_ccy, rate_date, session)
		converted = Decimal(amount_cents) * rate
		return int(converted.to_integral_value(rounding=ROUND_HALF_UP))

	# ------------------------------------------------------------------
	# CodeTable helpers
	# ------------------------------------------------------------------

	def get_codes(
		self,
		domain: str,
		session: Any,
		active_only: bool = True,
	) -> list[Any]:
		"""Return all CodeTable entries for *domain*, ordered by sort_order."""
		from pgappforge.plugins.erp.foundation.models import CodeTable

		q = sa.select(CodeTable).where(CodeTable.domain == domain)
		if active_only:
			q = q.where(CodeTable.is_active.is_(True))
		q = q.order_by(CodeTable.sort_order, CodeTable.label)
		return list(session.execute(q).scalars().all())

	def get_code(
		self,
		domain: str,
		code: str,
		session: Any,
	) -> Any | None:
		"""Return a single CodeTable entry or None."""
		from pgappforge.plugins.erp.foundation.models import CodeTable

		return session.execute(
			sa.select(CodeTable)
			.where(CodeTable.domain == domain)
			.where(CodeTable.code == code)
		).scalar_one_or_none()

	# ------------------------------------------------------------------
	# Seed helpers (called by FoundationPlugin.setup_seed_data)
	# ------------------------------------------------------------------

	def seed_major_currencies(self, session: Any) -> int:
		"""INSERT the G20+Africa currency set if not already present.

		Returns number of rows inserted.
		"""
		from pgappforge.plugins.erp.foundation.models import Currency

		CURRENCIES = [
			("AED", "UAE Dirham",          "د.إ", 2),
			("AUD", "Australian Dollar",   "A$",  2),
			("BRL", "Brazilian Real",       "R$",  2),
			("CAD", "Canadian Dollar",      "CA$", 2),
			("CHF", "Swiss Franc",          "Fr",  2),
			("CNY", "Chinese Yuan",         "¥",   2),
			("EGP", "Egyptian Pound",       "£",   2),
			("EUR", "Euro",                 "€",   2),
			("GBP", "British Pound",        "£",   2),
			("GHS", "Ghanaian Cedi",        "₵",   2),
			("IDR", "Indonesian Rupiah",    "Rp",  2),
			("INR", "Indian Rupee",         "₹",   2),
			("JPY", "Japanese Yen",         "¥",   0),
			("KES", "Kenyan Shilling",      "KSh", 2),
			("KRW", "South Korean Won",     "₩",   0),
			("MXN", "Mexican Peso",         "$",   2),
			("NGN", "Nigerian Naira",       "₦",   2),
			("RUB", "Russian Ruble",        "₽",   2),
			("SAR", "Saudi Riyal",          "﷼",   2),
			("TRY", "Turkish Lira",         "₺",   2),
			("USD", "US Dollar",            "$",   2),
			("ZAR", "South African Rand",   "R",   2),
		]

		inserted = 0
		for code, name, symbol, dp in CURRENCIES:
			existing = session.get(Currency, code)
			if existing is None:
				session.add(Currency(code=code, name=name, symbol=symbol, decimal_places=dp))
				inserted += 1
		return inserted

	def seed_major_countries(self, session: Any) -> int:
		"""INSERT a representative set of countries if not already present.

		Returns number of rows inserted.
		"""
		from pgappforge.plugins.erp.foundation.models import Country

		COUNTRIES = [
			("AE", "ARE", "United Arab Emirates", "+971", "AED", False),
			("AU", "AUS", "Australia",             "+61",  "AUD", False),
			("BR", "BRA", "Brazil",                "+55",  "BRL", False),
			("CA", "CAN", "Canada",                "+1",   "CAD", False),
			("CH", "CHE", "Switzerland",           "+41",  "CHF", False),
			("CN", "CHN", "China",                 "+86",  "CNY", False),
			("DE", "DEU", "Germany",               "+49",  "EUR", True),
			("EG", "EGY", "Egypt",                 "+20",  "EGP", False),
			("FR", "FRA", "France",                "+33",  "EUR", True),
			("GB", "GBR", "United Kingdom",        "+44",  "GBP", False),
			("GH", "GHA", "Ghana",                 "+233", "GHS", False),
			("ID", "IDN", "Indonesia",             "+62",  "IDR", False),
			("IN", "IND", "India",                 "+91",  "INR", False),
			("JP", "JPN", "Japan",                 "+81",  "JPY", False),
			("KE", "KEN", "Kenya",                 "+254", "KES", False),
			("KR", "KOR", "South Korea",           "+82",  "KRW", False),
			("MX", "MEX", "Mexico",                "+52",  "MXN", False),
			("NG", "NGA", "Nigeria",               "+234", "NGN", False),
			("RU", "RUS", "Russia",                "+7",   "RUB", False),
			("SA", "SAU", "Saudi Arabia",          "+966", "SAR", False),
			("TR", "TUR", "Turkey",                "+90",  "TRY", False),
			("US", "USA", "United States",         "+1",   "USD", False),
			("ZA", "ZAF", "South Africa",          "+27",  "ZAR", False),
		]

		inserted = 0
		for alpha2, alpha3, name, prefix, ccy, is_eu in COUNTRIES:
			existing = session.get(Country, alpha2)
			if existing is None:
				session.add(Country(
					iso_alpha2=alpha2,
					iso_alpha3=alpha3,
					name=name,
					phone_prefix=prefix,
					currency_code=ccy,
					is_eu=is_eu,
				))
				inserted += 1
		return inserted


__all__ = [
	"FoundationService",
	"FoundationServiceError",
	"PartyNotFoundError",
	"ExchangeRateNotFoundError",
]
