"""
pgappforge/plugins/erp/finance/tax/services.py

TaxService — stateless business logic for Tax Management.

All tax amounts in integer cents. Rates are Decimal (NUMERIC(7,4)).
No float arithmetic anywhere.

Public API
----------
  determine_tax(amount_cents, jurisdiction_code, tax_code_str, session, tenant_id) -> int
  post_tax_transaction(details, session) -> TaxTransaction
  generate_vat_return(jurisdiction_id, period_start, period_end, session) -> TaxReturn
  file_return(return_id, reference_number, filing_date, session) -> TaxReturn
  pay_return(return_id, payment_reference, payment_date, session) -> TaxReturn
  get_applicable_tax_code(jurisdiction_code, code, as_of_date, tenant_id, session) -> TaxCode | None
  get_period_transactions(jurisdiction_id, period_start, period_end, session) -> list[TaxTransaction]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TaxServiceError(Exception):
	"""Base Tax service error."""


class TaxCodeNotFoundError(TaxServiceError):
	"""No active tax code found for the given jurisdiction and code."""


class TaxReturnNotFoundError(TaxServiceError):
	pass


class TaxReturnStatusError(TaxServiceError):
	"""Operation not permitted in the current return status."""


# ---------------------------------------------------------------------------
# Input DTOs
# ---------------------------------------------------------------------------

@dataclass
class TaxTransactionDetails:
	tenant_id: str
	tax_code_id: str
	source_document_type: str
	source_document_id: str
	taxable_amount_cents: int
	posting_date: date
	currency_code: str = "NGN"
	is_recoverable: bool = True
	tax_period: str | None = None       # e.g. "2026-01"; None = auto-derive
	exchange_rate: Decimal | None = None
	reporting_tax_amount_cents: int | None = None
	is_reversal: bool = False
	reversal_of_id: str | None = None


# ---------------------------------------------------------------------------
# TaxService
# ---------------------------------------------------------------------------

class TaxService:
	"""Stateless Tax service. Caller owns session transactions."""

	# ------------------------------------------------------------------ #
	# Determine Tax
	# ------------------------------------------------------------------ #

	def determine_tax(
		self,
		amount_cents: int,
		jurisdiction_code: str,
		tax_code_str: str,
		session: Any,
		tenant_id: str | None = None,
		as_of_date: date | None = None,
	) -> int:
		"""Calculate tax amount for a given taxable amount.

		Args:
			amount_cents:      Net taxable amount in integer cents.
			jurisdiction_code: Jurisdiction code e.g. "NG-FIRS".
			tax_code_str:      Tax code within jurisdiction e.g. "STD".
			session:           SQLAlchemy session.
			tenant_id:         Tenant scope. None = any tenant.
			as_of_date:        Rate lookup date. None = today.

		Returns:
			Tax amount in integer cents (rounded half-up).

		Raises:
			TaxCodeNotFoundError if no active rate found.
		"""
		assert amount_cents >= 0, "amount_cents must be non-negative"

		d = as_of_date or date.today()
		tax_code = self.get_applicable_tax_code(
			jurisdiction_code, tax_code_str, d, tenant_id, session
		)
		if tax_code is None:
			raise TaxCodeNotFoundError(
				f"No active tax code {tax_code_str!r} in jurisdiction {jurisdiction_code!r} "
				f"as of {d}"
			)

		if tax_code.is_exempt:
			return 0
		if tax_code.is_zero_rated:
			return 0

		rate = Decimal(str(tax_code.rate))  # e.g. Decimal("7.5000")
		tax = (Decimal(amount_cents) * rate / Decimal("100")).to_integral_value(ROUND_HALF_UP)
		return int(tax)

	# ------------------------------------------------------------------ #
	# Post Tax Transaction
	# ------------------------------------------------------------------ #

	def post_tax_transaction(
		self,
		details: TaxTransactionDetails,
		session: Any,
	) -> Any:
		"""Create an immutable TaxTransaction line.

		Calculates tax_amount_cents from the tax code rate if not pre-supplied.
		Derives tax_period from posting_date if not provided.
		Emits TaxTransactionPostedEvent.
		"""
		from pgappforge.plugins.erp.finance.tax.models import TaxCode, TaxTransaction
		from pgappforge.plugins.erp.finance.tax.events import TaxTransactionPostedEvent, emit_event

		assert details.taxable_amount_cents >= 0 or details.is_reversal, \
			"taxable_amount_cents must be non-negative unless reversal"

		tax_code = session.get(TaxCode, details.tax_code_id)
		if tax_code is None:
			raise TaxCodeNotFoundError(f"TaxCode {details.tax_code_id!r} not found")

		# Calculate tax amount
		if details.is_reversal:
			# For reversals, invert the taxable amount sign
			taxable = details.taxable_amount_cents  # caller supplies negative value
		else:
			taxable = details.taxable_amount_cents

		rate = Decimal(str(tax_code.rate))
		tax_cents: int
		if tax_code.is_exempt or tax_code.is_zero_rated:
			tax_cents = 0
		else:
			tax_cents = int(
				(Decimal(taxable) * rate / Decimal("100")).to_integral_value(ROUND_HALF_UP)
			)
			if details.is_reversal:
				tax_cents = -abs(tax_cents)

		# Derive tax period
		tax_period = details.tax_period or details.posting_date.strftime("%Y-%m")

		txn = TaxTransaction(
			tenant_id=details.tenant_id,
			tax_code_id=details.tax_code_id,
			source_document_type=details.source_document_type,
			source_document_id=details.source_document_id,
			taxable_amount_cents=taxable,
			tax_amount_cents=tax_cents,
			is_recoverable=details.is_recoverable,
			posting_date=details.posting_date,
			tax_period=tax_period,
			currency_code=details.currency_code,
			exchange_rate=details.exchange_rate,
			reporting_tax_amount_cents=details.reporting_tax_amount_cents,
			is_reversal=details.is_reversal,
			reversal_of_id=details.reversal_of_id,
		)
		session.add(txn)
		session.flush()

		emit_event(
			TaxTransactionPostedEvent(
				aggregate_id=txn.id,
				aggregate_type="TaxTransaction",
				tenant_id=details.tenant_id,
				tax_transaction_id=txn.id,
				tax_code_id=details.tax_code_id,
				source_document_type=details.source_document_type,
				source_document_id=details.source_document_id,
				taxable_amount_cents=taxable,
				tax_amount_cents=tax_cents,
				posting_date=str(details.posting_date),
				is_recoverable=details.is_recoverable,
			),
			session,
		)
		log.info(
			"Tax txn posted: code=%r taxable=%d tax=%d src=%s/%s",
			details.tax_code_id, taxable, tax_cents,
			details.source_document_type, details.source_document_id,
		)
		return txn

	# ------------------------------------------------------------------ #
	# Generate VAT Return
	# ------------------------------------------------------------------ #

	def generate_vat_return(
		self,
		jurisdiction_id: str,
		period_start: date,
		period_end: date,
		session: Any,
		tenant_id: str | None = None,
	) -> Any:
		"""Aggregate TaxTransactions into a draft TaxReturn for the period.

		Aggregates:
		  output_tax_cents  = sum of non-recoverable tax_amount_cents where
		                       tax_code.is_output_tax = True
		  input_tax_cents   = sum of is_recoverable tax_amount_cents where
		                       tax_code.is_input_tax = True
		  net_tax_cents     = output - input

		An existing DRAFT return for the same period is replaced (idempotent).
		Emits TaxReturnGeneratedEvent.
		"""
		from pgappforge.plugins.erp.finance.tax.models import (
			TaxCode, TaxJurisdiction, TaxReturn, TaxTransaction,
		)
		from pgappforge.plugins.erp.finance.tax.events import TaxReturnGeneratedEvent, emit_event

		jurisdiction = session.get(TaxJurisdiction, jurisdiction_id)
		if jurisdiction is None:
			raise TaxServiceError(f"TaxJurisdiction {jurisdiction_id!r} not found")

		# Aggregate output tax (charged on sales)
		output_q = (
			sa.select(sa.func.coalesce(sa.func.sum(TaxTransaction.tax_amount_cents), 0))
			.join(TaxCode, TaxTransaction.tax_code_id == TaxCode.id)
			.where(TaxCode.jurisdiction_id == jurisdiction_id)
			.where(TaxCode.is_output_tax.is_(True))
			.where(TaxTransaction.posting_date >= period_start)
			.where(TaxTransaction.posting_date <= period_end)
		)
		if tenant_id:
			output_q = output_q.where(TaxTransaction.tenant_id == tenant_id)
		output_cents: int = session.execute(output_q).scalar_one()

		# Aggregate input tax (recoverable on purchases)
		input_q = (
			sa.select(sa.func.coalesce(sa.func.sum(TaxTransaction.tax_amount_cents), 0))
			.join(TaxCode, TaxTransaction.tax_code_id == TaxCode.id)
			.where(TaxCode.jurisdiction_id == jurisdiction_id)
			.where(TaxCode.is_input_tax.is_(True))
			.where(TaxTransaction.is_recoverable.is_(True))
			.where(TaxTransaction.posting_date >= period_start)
			.where(TaxTransaction.posting_date <= period_end)
		)
		if tenant_id:
			input_q = input_q.where(TaxTransaction.tenant_id == tenant_id)
		input_cents: int = session.execute(input_q).scalar_one()

		# Aggregate taxable supplies value
		supply_q = (
			sa.select(sa.func.coalesce(sa.func.sum(TaxTransaction.taxable_amount_cents), 0))
			.join(TaxCode, TaxTransaction.tax_code_id == TaxCode.id)
			.where(TaxCode.jurisdiction_id == jurisdiction_id)
			.where(TaxCode.is_output_tax.is_(True))
			.where(TaxTransaction.posting_date >= period_start)
			.where(TaxTransaction.posting_date <= period_end)
		)
		if tenant_id:
			supply_q = supply_q.where(TaxTransaction.tenant_id == tenant_id)
		taxable_supplies: int = session.execute(supply_q).scalar_one()

		net_cents = output_cents - input_cents

		# Check for existing DRAFT return and update it (idempotent)
		_t_id = tenant_id
		existing_q = (
			sa.select(TaxReturn)
			.where(TaxReturn.jurisdiction_id == jurisdiction_id)
			.where(TaxReturn.period_start == period_start)
			.where(TaxReturn.period_end == period_end)
			.where(TaxReturn.status == "DRAFT")
		)
		if _t_id:
			existing_q = existing_q.where(TaxReturn.tenant_id == _t_id)
		existing = session.execute(existing_q).scalar_one_or_none()

		if existing:
			existing.output_tax_cents = output_cents
			existing.input_tax_cents = input_cents
			existing.net_tax_cents = net_cents
			existing.taxable_supplies_cents = taxable_supplies
			existing.updated_at = datetime.now(timezone.utc)
			ret = existing
		else:
			ret = TaxReturn(
				tenant_id=tenant_id or "",
				jurisdiction_id=jurisdiction_id,
				period_start=period_start,
				period_end=period_end,
				output_tax_cents=output_cents,
				input_tax_cents=input_cents,
				net_tax_cents=net_cents,
				taxable_supplies_cents=taxable_supplies,
				status="DRAFT",
			)
			session.add(ret)

		session.flush()

		emit_event(
			TaxReturnGeneratedEvent(
				aggregate_id=ret.id,
				aggregate_type="TaxReturn",
				tenant_id=tenant_id or "",
				tax_return_id=ret.id,
				jurisdiction_id=jurisdiction_id,
				period_start=str(period_start),
				period_end=str(period_end),
				output_tax_cents=output_cents,
				input_tax_cents=input_cents,
				net_tax_cents=net_cents,
			),
			session,
		)
		log.info(
			"VAT return generated: jurisdiction=%r period=%s→%s "
			"output=%d input=%d net=%d",
			jurisdiction_id, period_start, period_end,
			output_cents, input_cents, net_cents,
		)
		return ret

	# ------------------------------------------------------------------ #
	# File Return
	# ------------------------------------------------------------------ #

	def file_return(
		self,
		return_id: str,
		reference_number: str,
		session: Any,
		filing_date: date | None = None,
	) -> Any:
		"""Mark a DRAFT return as FILED. Emits TaxReturnFiledEvent."""
		from pgappforge.plugins.erp.finance.tax.models import TaxReturn
		from pgappforge.plugins.erp.finance.tax.events import TaxReturnFiledEvent, emit_event

		ret = session.get(TaxReturn, return_id)
		if ret is None:
			raise TaxReturnNotFoundError(f"TaxReturn {return_id!r} not found")
		if ret.status != "DRAFT":
			raise TaxReturnStatusError(f"Return is {ret.status!r}, must be DRAFT to file")

		d = filing_date or date.today()
		ret.status = "FILED"
		ret.filing_date = d
		ret.reference_number = reference_number
		ret.updated_at = datetime.now(timezone.utc)

		emit_event(
			TaxReturnFiledEvent(
				aggregate_id=return_id,
				aggregate_type="TaxReturn",
				tenant_id=ret.tenant_id,
				tax_return_id=return_id,
				jurisdiction_id=ret.jurisdiction_id,
				reference_number=reference_number,
				filing_date=str(d),
				net_tax_cents=ret.net_tax_cents,
			),
			session,
		)
		log.info("Tax return %r filed ref=%r", return_id, reference_number)
		return ret

	# ------------------------------------------------------------------ #
	# Pay Return
	# ------------------------------------------------------------------ #

	def pay_return(
		self,
		return_id: str,
		payment_reference: str,
		session: Any,
		payment_date: date | None = None,
	) -> Any:
		"""Mark a FILED return as PAID. Emits TaxReturnPaidEvent."""
		from pgappforge.plugins.erp.finance.tax.models import TaxReturn
		from pgappforge.plugins.erp.finance.tax.events import TaxReturnPaidEvent, emit_event

		ret = session.get(TaxReturn, return_id)
		if ret is None:
			raise TaxReturnNotFoundError(f"TaxReturn {return_id!r} not found")
		if ret.status != "FILED":
			raise TaxReturnStatusError(f"Return is {ret.status!r}, must be FILED to mark paid")
		if ret.net_tax_cents <= 0:
			raise TaxReturnStatusError("Return has no net payable amount — use REFUND_CLAIMED instead")

		d = payment_date or date.today()
		ret.status = "PAID"
		ret.payment_reference = payment_reference
		ret.payment_date = d
		ret.updated_at = datetime.now(timezone.utc)

		emit_event(
			TaxReturnPaidEvent(
				aggregate_id=return_id,
				aggregate_type="TaxReturn",
				tenant_id=ret.tenant_id,
				tax_return_id=return_id,
				jurisdiction_id=ret.jurisdiction_id,
				payment_reference=payment_reference,
				payment_date=str(d),
				amount_paid_cents=ret.net_tax_cents,
			),
			session,
		)
		log.info("Tax return %r paid ref=%r amount=%d", return_id, payment_reference, ret.net_tax_cents)
		return ret

	# ------------------------------------------------------------------ #
	# Lookup helpers
	# ------------------------------------------------------------------ #

	def get_applicable_tax_code(
		self,
		jurisdiction_code: str,
		code: str,
		as_of_date: date,
		tenant_id: str | None,
		session: Any,
	) -> Any | None:
		"""Retrieve the effective TaxCode for a jurisdiction + code + date.

		Returns the most recently effective row where:
		  effective_from <= as_of_date AND (effective_to IS NULL OR effective_to >= as_of_date)
		"""
		from pgappforge.plugins.erp.finance.tax.models import TaxCode, TaxJurisdiction

		q = (
			sa.select(TaxCode)
			.join(TaxJurisdiction, TaxCode.jurisdiction_id == TaxJurisdiction.id)
			.where(TaxJurisdiction.code == jurisdiction_code)
			.where(TaxCode.code == code)
			.where(TaxCode.effective_from <= as_of_date)
			.where(
				sa.or_(
					TaxCode.effective_to.is_(None),
					TaxCode.effective_to >= as_of_date,
				)
			)
			.where(TaxCode.is_active.is_(True))
			.order_by(sa.desc(TaxCode.effective_from))
			.limit(1)
		)
		if tenant_id:
			q = q.where(TaxCode.tenant_id == tenant_id)
		return session.execute(q).scalar_one_or_none()

	def get_period_transactions(
		self,
		jurisdiction_id: str,
		period_start: date,
		period_end: date,
		session: Any,
		tenant_id: str | None = None,
	) -> list[Any]:
		"""Return all TaxTransactions for a jurisdiction in a date range."""
		from pgappforge.plugins.erp.finance.tax.models import TaxCode, TaxTransaction

		q = (
			sa.select(TaxTransaction)
			.join(TaxCode, TaxTransaction.tax_code_id == TaxCode.id)
			.where(TaxCode.jurisdiction_id == jurisdiction_id)
			.where(TaxTransaction.posting_date >= period_start)
			.where(TaxTransaction.posting_date <= period_end)
			.order_by(TaxTransaction.posting_date, TaxTransaction.created_at)
		)
		if tenant_id:
			q = q.where(TaxTransaction.tenant_id == tenant_id)
		return session.execute(q).scalars().all()


__all__ = [
	"TaxService",
	"TaxServiceError",
	"TaxCodeNotFoundError",
	"TaxReturnNotFoundError",
	"TaxReturnStatusError",
	"TaxTransactionDetails",
]
