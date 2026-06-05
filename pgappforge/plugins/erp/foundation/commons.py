"""
Shared utilities for all pgappforge ERP plugins.

Import pattern:
	from pgappforge.plugins.erp.foundation.commons import (
		ERPBaseMixin, SoftDeleteMixin, ImmutableRecordMixin,
		money_add, money_subtract, money_multiply, money_divide,
		percent_of, cents_to_display, format_currency,
		validate_iban, validate_bic, validate_email, validate_isin, validate_lei,
		mask_national_id, hash_sensitive,
		address_column, contact_column, money_column, tenant_column,
		emit_event, status_badge,
		ADDRESS_SCHEMA, CONTACT_SCHEMA, BANKING_SCHEMA, STATUS_COLORS,
	)
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


# ── JSONB schema constants (shared across all plugins) ─────────────────────

ADDRESS_SCHEMA: dict = {
	"line1": "", "line2": "", "city": "", "state": "",
	"postal_code": "", "country_code": "KE", "geo_lat": None, "geo_lng": None,
}

CONTACT_SCHEMA: dict = {
	"email": "", "phone": "", "mobile": "", "fax": "", "website": "",
}

BANKING_SCHEMA: dict = {
	"iban": "", "bic": "", "account_name": "", "bank_name": "",
	"sort_code": "", "routing_number": "",
}


# ── Money utilities (always integer cents) ─────────────────────────────────

def money_add(a: int, b: int) -> int:
	"""Add two cent values. Both must be int. Never float."""
	return int(a) + int(b)


def money_subtract(a: int, b: int) -> int:
	"""Subtract cent values. Returns 0 if result would be negative (guard)."""
	return max(0, int(a) - int(b))


def money_multiply(cents: int, rate: Decimal | float | str) -> int:
	"""Multiply cents by a rate, round half-up to nearest cent."""
	return int(
		(Decimal(str(cents)) * Decimal(str(rate))).quantize(
			Decimal("1"), rounding=ROUND_HALF_UP
		)
	)


def money_divide(cents: int, divisor: Decimal | float | str) -> int:
	"""Divide cents by divisor, round half-up."""
	return int(
		(Decimal(str(cents)) / Decimal(str(divisor))).quantize(
			Decimal("1"), rounding=ROUND_HALF_UP
		)
	)


def cents_to_display(cents: int, decimal_places: int = 2) -> Decimal:
	"""Convert integer cents to display Decimal. 100 → Decimal('1.00')"""
	factor = Decimal(10) ** decimal_places
	return Decimal(cents) / factor


def format_currency(cents: int, currency_code: str = "USD", decimal_places: int = 2) -> str:
	"""Format cents as human-readable currency string. 100_00 → 'USD 100.00'"""
	amount = cents_to_display(cents, decimal_places)
	return f"{currency_code} {amount:,.{decimal_places}f}"


def percent_of(base_cents: int, pct: Decimal | float | str) -> int:
	"""Calculate percentage of a cent value. percent_of(10000, 2.5) → 250"""
	return money_multiply(base_cents, Decimal(str(pct)) / Decimal("100"))


# ── Validators ─────────────────────────────────────────────────────────────

_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{1,30}$")
_BIC_RE = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_LEI_RE = re.compile(r"^[A-Z0-9]{18}\d{2}$")


def validate_iban(iban: str) -> bool:
	s = re.sub(r"\s", "", (iban or "").upper())
	return bool(_IBAN_RE.match(s))


def validate_bic(bic: str) -> bool:
	return bool(_BIC_RE.match((bic or "").upper()))


def validate_email(email: str) -> bool:
	return bool(_EMAIL_RE.match(email or ""))


def validate_isin(isin: str) -> bool:
	return bool(_ISIN_RE.match((isin or "").upper()))


def validate_lei(lei: str) -> bool:
	return bool(_LEI_RE.match((lei or "").upper()))


def mask_national_id(national_id: str) -> str:
	"""Mask all but last 4 chars: '12345678' → '****5678'"""
	if not national_id or len(national_id) <= 4:
		return "****"
	return "*" * (len(national_id) - 4) + national_id[-4:]


def hash_sensitive(value: str) -> str:
	"""SHA-256 hash for sensitivity-preserving storage."""
	return hashlib.sha256((value or "").encode()).hexdigest()


# ── SQLAlchemy column helpers ──────────────────────────────────────────────

def address_column(comment: str = "Structured address JSONB"):
	"""Standard JSONB address column using shared ADDRESS_SCHEMA default."""
	from sqlalchemy import Column
	from sqlalchemy.dialects.postgresql import JSONB
	return Column(JSONB, nullable=False, default=dict, server_default="{}", comment=comment)


def contact_column(comment: str = "Structured contact JSONB"):
	"""Standard JSONB contact column."""
	from sqlalchemy import Column
	from sqlalchemy.dialects.postgresql import JSONB
	return Column(JSONB, nullable=False, default=dict, server_default="{}", comment=comment)


def money_column(comment: str = "", nullable: bool = False, default: int = 0):
	"""Integer cents column. Add a non-negative CHECK constraint via __table_args__."""
	from sqlalchemy import Column, Integer
	return Column(Integer, nullable=nullable, default=default, comment=comment)


def tenant_column():
	"""Standard tenant_id column."""
	from sqlalchemy import Column, String
	return Column(String(64), nullable=False, index=True, comment="Tenant identifier")


# ── SQLAlchemy model mixins ────────────────────────────────────────────────

class ERPBaseMixin:
	"""All ERP models should include this mixin.

	Does not define columns directly (SQLAlchemy declarative inheritance
	quirks); subclasses declare tenant_id and audit columns themselves.
	Provides a hook for future cross-cutting concerns (e.g. soft-delete
	query helpers, event firing).
	"""

	@classmethod
	def __init_subclass__(cls, **kwargs: Any) -> None:
		super().__init_subclass__(**kwargs)


class SoftDeleteMixin:
	"""Adds logical-delete semantics.

	Declare ``deleted_at`` on the concrete model::

		deleted_at = Column(DateTime(timezone=True), nullable=True)

	Then filter active records with::

		session.execute(select(MyModel).where(MyModel.deleted_at.is_(None)))
	"""
	pass


class ImmutableRecordMixin:
	"""Mark a model as insert-only (financial ledger entries, audit records).

	Wire up by calling ``cls._register_immutability()`` once after the model
	class is fully defined (e.g. in a module-level block or plugin initialise).

	Raises RuntimeError on any SQLAlchemy before_update event for that mapper.
	"""

	_immutable: bool = True

	@classmethod
	def _register_immutability(cls) -> None:
		from sqlalchemy import event as _sa_event

		@_sa_event.listens_for(cls, "before_update")
		def _block_update(mapper, connection, target):
			if getattr(target, "_immutable", False):
				raise RuntimeError(
					f"{cls.__name__} is an immutable ledger record. "
					"Create a correction entry instead of updating."
				)


# ── Event emission helper ──────────────────────────────────────────────────

def emit_event(
	event_type: str,
	aggregate_type: str,
	aggregate_id: str,
	payload: dict,
	session: Any,
	tenant_id: str = "",
	correlation_id: str = "",
) -> None:
	"""Convenience wrapper — constructs a DomainEvent and delegates to events.emit_event.

	Swallows all exceptions so event emission never breaks business logic.
	Preferred over calling events.emit_event directly when you only need the
	simple dict-payload form (no typed event subclass).
	"""
	try:
		from pgappforge.plugins.erp.foundation.events import DomainEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit
		ev = DomainEvent(
			event_type=event_type,
			aggregate_type=aggregate_type,
			aggregate_id=str(aggregate_id),
			tenant_id=tenant_id,
			correlation_id=correlation_id,
			payload=payload,
		)
		_emit(ev, session)
	except Exception:
		pass


# ── Status helpers ─────────────────────────────────────────────────────────

STATUS_COLORS: dict[str, str] = {
	# Finance
	"DRAFT": "secondary",
	"ISSUED": "primary",
	"PARTIAL": "warning",
	"PAID": "success",
	"OVERDUE": "danger",
	"CANCELLED": "dark",
	"APPROVED": "success",
	"REJECTED": "danger",
	"PENDING": "warning",
	# Ops
	"OPEN": "primary",
	"IN_PROGRESS": "info",
	"COMPLETED": "success",
	"CLOSED": "secondary",
	"ACTIVE": "success",
	"INACTIVE": "secondary",
	# HCM
	"SUBMITTED": "info",
	"POSTED": "success",
	"REVERSED": "warning",
}


def status_badge(status: str) -> str:
	"""Return Bootstrap badge HTML for a status value."""
	color = STATUS_COLORS.get((status or "").upper(), "secondary")
	return f'<span class="badge bg-{color}">{status}</span>'


# ── Public API ─────────────────────────────────────────────────────────────

__all__ = [
	# JSONB schemas
	"ADDRESS_SCHEMA",
	"CONTACT_SCHEMA",
	"BANKING_SCHEMA",
	# money
	"money_add",
	"money_subtract",
	"money_multiply",
	"money_divide",
	"percent_of",
	"cents_to_display",
	"format_currency",
	# validators
	"validate_iban",
	"validate_bic",
	"validate_email",
	"validate_isin",
	"validate_lei",
	"mask_national_id",
	"hash_sensitive",
	# column helpers
	"address_column",
	"contact_column",
	"money_column",
	"tenant_column",
	# mixins
	"ERPBaseMixin",
	"SoftDeleteMixin",
	"ImmutableRecordMixin",
	# event helper
	"emit_event",
	# status
	"STATUS_COLORS",
	"status_badge",
]
