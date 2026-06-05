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

	# ------------------------------------------------------------------ #
	# Apply Tax (compute + post TaxTransaction in one call)
	# ------------------------------------------------------------------ #

	def apply_tax(
		self,
		session: Any,
		taxable_amount_cents: int,
		tax_code: str,
		source_doc_type: str,
		source_doc_id: str,
		period_month: date,
		tenant_id: str,
		jurisdiction_code: str | None = None,
	) -> Any:
		"""Compute and persist a TaxTransaction for a source document line.

		Args:
			taxable_amount_cents: Net amount on which tax is levied.
			tax_code:             Tax code string e.g. 'STD', 'WHT15'.
			source_doc_type:      'INVOICE' | 'PURCHASE' | 'PAYROLL' | any.
			source_doc_id:        UUID of the source document.
			period_month:         Any date within the tax period (used as posting_date).
			tenant_id:            Tenant scope.
			jurisdiction_code:    Required when tax_code is ambiguous across jurisdictions.
		                          If None, looks up by code alone (first active match).

		Returns:
			TaxTransaction (flushed, not committed).

		Raises:
			TaxCodeNotFoundError if the code is not active on period_month.
		"""
		from pgappforge.plugins.erp.finance.tax.models import TaxCode, TaxJurisdiction, TaxTransaction

		assert taxable_amount_cents >= 0, "taxable_amount_cents must be non-negative"

		# Resolve tax code object
		if jurisdiction_code:
			tax_code_obj = self.get_applicable_tax_code(
				jurisdiction_code, tax_code, period_month, tenant_id, session
			)
		else:
			# Fallback: match by code + tenant, take most recently effective
			q = (
				sa.select(TaxCode)
				.where(TaxCode.code == tax_code)
				.where(TaxCode.tenant_id == tenant_id)
				.where(TaxCode.effective_from <= period_month)
				.where(
					sa.or_(
						TaxCode.effective_to.is_(None),
						TaxCode.effective_to >= period_month,
					)
				)
				.where(TaxCode.is_active.is_(True))
				.order_by(sa.desc(TaxCode.effective_from))
				.limit(1)
			)
			tax_code_obj = session.execute(q).scalar_one_or_none()

		if tax_code_obj is None:
			raise TaxCodeNotFoundError(
				f"No active tax code {tax_code!r} for tenant {tenant_id!r} "
				f"as of {period_month}"
			)

		rate = Decimal(str(tax_code_obj.rate))
		if tax_code_obj.is_exempt or tax_code_obj.is_zero_rated:
			tax_amount_cents = 0
		else:
			tax_amount_cents = int(
				(Decimal(taxable_amount_cents) * rate / Decimal("100"))
				.to_integral_value(ROUND_HALF_UP)
			)

		tax_period = period_month.strftime("%Y-%m")

		txn = TaxTransaction(
			tenant_id=tenant_id,
			tax_code_id=tax_code_obj.id,
			source_document_type=source_doc_type,
			source_document_id=source_doc_id,
			taxable_amount_cents=taxable_amount_cents,
			tax_amount_cents=tax_amount_cents,
			is_recoverable=tax_code_obj.is_input_tax,
			posting_date=period_month,
			tax_period=tax_period,
		)
		session.add(txn)
		session.flush()

		# Post GL entries if GL service is available
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore[import]
			gl = GLService()
			gl.post_journal_entry(
				session=session,
				tenant_id=tenant_id,
				description=f"Tax: {source_doc_type} {source_doc_id}",
				lines=[
					{"account": "tax_expense", "debit_cents": tax_amount_cents, "credit_cents": 0},
					{"account": tax_code_obj.gl_account, "debit_cents": 0, "credit_cents": tax_amount_cents},
				],
				source_doc_type=source_doc_type,
				source_doc_id=source_doc_id,
			)
		except (ImportError, Exception) as _gl_err:  # noqa: BLE001
			log.debug("GL posting skipped: %s", _gl_err)

		log.info(
			"apply_tax: code=%r taxable=%d tax=%d period=%s src=%s/%s",
			tax_code, taxable_amount_cents, tax_amount_cents,
			tax_period, source_doc_type, source_doc_id,
		)
		return txn

	# ------------------------------------------------------------------ #
	# Generate WHT Return
	# ------------------------------------------------------------------ #

	def generate_wht_return(
		self,
		session: Any,
		period_month: date,
		tenant_id: str,
		jurisdiction_id: str | None = None,
	) -> dict:
		"""Aggregate WHT TaxTransactions for period_month into a summary dict.

		Returns a structured report matching KRA WHT return requirements:
		{
		    "period":              "YYYY-MM",
		    "total_gross_cents":   int,
		    "total_wht_cents":     int,
		    "payee_count":         int,
		    "by_income_type":      {income_type: {"gross": int, "wht": int, "count": int}},
		    "wht_certificates":    [{"cert_number", "payee_id", "payee_pin",
		                             "gross", "wht", "net", "income_type"}],
		    "tax_return":          TaxReturn (or None if no amounts),
		}
		"""
		from pgappforge.plugins.erp.finance.tax.models import (
			TaxCode, TaxJurisdiction, TaxReturn, TaxTransaction, WHTCertificate,
		)

		period_str = period_month.strftime("%Y-%m")
		period_start = period_month.replace(day=1)
		# last day of month
		import calendar
		last_day = calendar.monthrange(period_month.year, period_month.month)[1]
		period_end = period_month.replace(day=last_day)

		# Fetch WHT transactions for the period — tax codes in WHT jurisdictions
		wht_txn_q = (
			sa.select(TaxTransaction)
			.join(TaxCode, TaxTransaction.tax_code_id == TaxCode.id)
			.join(TaxJurisdiction, TaxCode.jurisdiction_id == TaxJurisdiction.id)
			.where(TaxJurisdiction.tax_type == "WHT")
			.where(TaxTransaction.tenant_id == tenant_id)
			.where(TaxTransaction.posting_date >= period_start)
			.where(TaxTransaction.posting_date <= period_end)
		)
		if jurisdiction_id:
			wht_txn_q = wht_txn_q.where(TaxJurisdiction.id == jurisdiction_id)
		txns = session.execute(wht_txn_q).scalars().all()

		total_gross = sum(t.taxable_amount_cents for t in txns)
		total_wht = sum(t.tax_amount_cents for t in txns)

		# Fetch WHT certificates for period (more precise payee-level breakdown)
		cert_q = (
			sa.select(WHTCertificate)
			.where(WHTCertificate.tenant_id == tenant_id)
			.where(WHTCertificate.payment_date >= period_start)
			.where(WHTCertificate.payment_date <= period_end)
			.where(WHTCertificate.voided_at.is_(None))
		)
		certs = session.execute(cert_q).scalars().all()

		by_income_type: dict[str, dict] = {}
		payee_ids: set[str] = set()
		for c in certs:
			payee_ids.add(str(c.payee_id))
			bucket = by_income_type.setdefault(
				c.income_type,
				{"gross": 0, "wht": 0, "count": 0},
			)
			bucket["gross"] += c.gross_amount_cents
			bucket["wht"] += c.wht_amount_cents
			bucket["count"] += 1

		# Upsert or create a DRAFT TaxReturn for WHT
		ret: Any = None
		if total_wht:
			existing_q = (
				sa.select(TaxReturn)
				.where(TaxReturn.tenant_id == tenant_id)
				.where(TaxReturn.period_start == period_start)
				.where(TaxReturn.period_end == period_end)
				.where(TaxReturn.status == "DRAFT")
				.where(TaxReturn.notes == "WHT")  # discriminate from VAT
			)
			if jurisdiction_id:
				existing_q = existing_q.where(TaxReturn.jurisdiction_id == jurisdiction_id)
			existing = session.execute(existing_q).scalar_one_or_none()

			if existing:
				existing.net_tax_cents = total_wht
				existing.taxable_supplies_cents = total_gross
				existing.output_tax_cents = total_wht
				existing.updated_at = datetime.now(timezone.utc)
				ret = existing
			else:
				ret = TaxReturn(
					tenant_id=tenant_id,
					jurisdiction_id=jurisdiction_id or "",
					period_start=period_start,
					period_end=period_end,
					output_tax_cents=total_wht,
					input_tax_cents=0,
					net_tax_cents=total_wht,
					taxable_supplies_cents=total_gross,
					status="DRAFT",
					notes="WHT",
				)
				session.add(ret)
			session.flush()

		return {
			"period": period_str,
			"total_gross_cents": total_gross,
			"total_wht_cents": total_wht,
			"payee_count": len(payee_ids),
			"by_income_type": by_income_type,
			"wht_certificates": [
				{
					"cert_number": c.cert_number,
					"payee_id": str(c.payee_id),
					"payee_pin": c.payee_pin,
					"gross": c.gross_amount_cents,
					"wht": c.wht_amount_cents,
					"net": c.net_amount_cents,
					"income_type": c.income_type,
				}
				for c in certs
			],
			"tax_return": ret,
		}

	# ------------------------------------------------------------------ #
	# Issue WHT Certificate
	# ------------------------------------------------------------------ #

	def issue_wht_certificate(
		self,
		session: Any,
		payee_id: str,
		payment_date: date,
		gross_amount_cents: int,
		wht_rate_pct: Decimal | float | str,
		income_type: str,
		issued_by: str,
		tenant_id: str,
		payee_pin: str = "",
	) -> Any:
		"""Issue a WHT Certificate and return it.

		cert_number is auto-generated as WHT-YYYY-NNNNNN (sequential per tenant per year).
		wht_amount_cents = gross × rate / 100 (rounded half-up).
		net_amount_cents = gross - wht.

		Args:
			payee_id:            UUID of the payee party.
			payment_date:        Date of the underlying gross payment.
			gross_amount_cents:  Payment amount before WHT.
			wht_rate_pct:        Withholding rate as a percentage e.g. Decimal('5.0000').
			income_type:         Income classification for the certificate.
			issued_by:           UUID of the issuing employee/user.
			tenant_id:           Tenant scope.
			payee_pin:           Payee's tax PIN/TIN (optional if not yet known).

		Returns:
			WHTCertificate (flushed, not committed).
		"""
		from pgappforge.plugins.erp.finance.tax.models import WHTCertificate

		assert gross_amount_cents > 0, "gross_amount_cents must be positive"

		rate = Decimal(str(wht_rate_pct))
		wht_amount_cents = int(
			(Decimal(gross_amount_cents) * rate / Decimal("100"))
			.to_integral_value(ROUND_HALF_UP)
		)
		net_amount_cents = gross_amount_cents - wht_amount_cents

		# Generate sequential cert number: WHT-YYYY-NNNNNN
		year = payment_date.year
		count_q = sa.select(sa.func.count()).select_from(WHTCertificate).where(
			WHTCertificate.tenant_id == tenant_id,
			WHTCertificate.cert_number.like(f"WHT-{year}-%"),
		)
		seq = session.execute(count_q).scalar_one() + 1
		cert_number = f"WHT-{year}-{seq:06d}"

		cert = WHTCertificate(
			tenant_id=tenant_id,
			cert_number=cert_number,
			payee_id=payee_id,
			payee_pin=payee_pin,
			payment_date=payment_date,
			gross_amount_cents=gross_amount_cents,
			wht_rate_pct=rate,
			wht_amount_cents=wht_amount_cents,
			net_amount_cents=net_amount_cents,
			income_type=income_type,
			issued_by=issued_by,
		)
		session.add(cert)
		session.flush()

		log.info(
			"WHT certificate issued: %s payee=%s gross=%d wht=%d rate=%s",
			cert_number, payee_id, gross_amount_cents, wht_amount_cents, rate,
		)
		return cert

	# ------------------------------------------------------------------ #
	# File Tax Return (simplified period_month variant)
	# ------------------------------------------------------------------ #

	def file_tax_return(
		self,
		session: Any,
		return_id: str,
		kra_reference: str,
		filed_by: str,
		tenant_id: str,
	) -> Any:
		"""File a DRAFT TaxReturn and post the GL clearing entry.

		Status: DRAFT → FILED.  Sets filed_at + kra_reference on the return.
		Posts GL: DR tax_payable CR bank (when net_tax_cents > 0).

		Args:
			return_id:      UUID of the TaxReturn to file.
			kra_reference:  Authority confirmation reference (e.g. KRA iTax ref).
			filed_by:       UUID of the user submitting the return.
			tenant_id:      Tenant scope (ownership check).

		Returns:
			TaxReturn with status FILED.

		Raises:
			TaxReturnNotFoundError / TaxReturnStatusError.
		"""
		from pgappforge.plugins.erp.finance.tax.models import TaxReturn

		ret = session.get(TaxReturn, return_id)
		if ret is None:
			raise TaxReturnNotFoundError(f"TaxReturn {return_id!r} not found")
		if str(ret.tenant_id) != str(tenant_id):
			raise TaxReturnStatusError("TaxReturn does not belong to this tenant")
		if ret.status != "DRAFT":
			raise TaxReturnStatusError(
				f"Return is {ret.status!r}; must be DRAFT to file"
			)

		ret.status = "FILED"
		ret.filing_date = date.today()
		ret.reference_number = kra_reference
		if hasattr(ret, "updated_at"):
			ret.updated_at = datetime.now(timezone.utc)

		# Post GL clearing if payable
		if ret.net_tax_cents > 0:
			try:
				from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore[import]
				gl = GLService()
				gl.post_journal_entry(
					session=session,
					tenant_id=tenant_id,
					description=f"Tax return filing {kra_reference}",
					lines=[
						{"account": "tax_payable", "debit_cents": ret.net_tax_cents, "credit_cents": 0},
						{"account": "bank", "debit_cents": 0, "credit_cents": ret.net_tax_cents},
					],
					source_doc_type="TaxReturn",
					source_doc_id=return_id,
				)
			except (ImportError, Exception) as _gl_err:  # noqa: BLE001
				log.debug("GL posting skipped: %s", _gl_err)

		session.flush()
		log.info(
			"TaxReturn %r filed by %r kra_ref=%r net=%d",
			return_id, filed_by, kra_reference, ret.net_tax_cents,
		)
		return ret

	# ------------------------------------------------------------------ #
	# Tax Calendar
	# ------------------------------------------------------------------ #

	def get_tax_calendar(
		self,
		session: Any,
		fiscal_year: int,
		tenant_id: str,
	) -> list[dict]:
		"""Return all statutory tax filing deadlines for fiscal_year.

		Kenya-centric schedule (overridable by jurisdiction config):
		  VAT   — 20th of following month (monthly filers)
		  WHT   — 20th of following month
		  PAYE  — 9th of following month
		  NSSF  — 9th of following month
		  NHIF  — 9th of following month

		Each entry: {
		    "obligation": str,
		    "period":     "YYYY-MM",
		    "due_date":   date,
		    "status":     "OVERDUE" | "DUE_SOON" | "UPCOMING",
		    "days_until": int,          # negative = overdue
		}

		Returns all 12 periods × 5 obligations = 60 entries, sorted by due_date.
		"""
		today = date.today()

		# (obligation_name, due_day, month_offset)
		# month_offset=1 means due in the month following the obligation period
		obligations = [
			("VAT",  20, 1),
			("WHT",  20, 1),
			("PAYE",  9, 1),
			("NSSF",  9, 1),
			("NHIF",  9, 1),
		]

		calendar_entries: list[dict] = []
		import calendar as _cal

		for month in range(1, 13):
			period_str = f"{fiscal_year}-{month:02d}"
			for obligation, due_day, month_offset in obligations:
				due_month = month + month_offset
				due_year = fiscal_year
				if due_month > 12:
					due_month -= 12
					due_year += 1
				# Clamp to valid day (e.g. Feb has no 30th)
				max_day = _cal.monthrange(due_year, due_month)[1]
				effective_day = min(due_day, max_day)
				due_date = date(due_year, due_month, effective_day)

				delta = (due_date - today).days
				if delta < 0:
					status = "OVERDUE"
				elif delta <= 7:
					status = "DUE_SOON"
				else:
					status = "UPCOMING"

				calendar_entries.append({
					"obligation": obligation,
					"period": period_str,
					"due_date": due_date,
					"status": status,
					"days_until": delta,
				})

		calendar_entries.sort(key=lambda e: e["due_date"])
		return calendar_entries

	# ------------------------------------------------------------------ #
	# Tax Dashboard
	# ------------------------------------------------------------------ #

	def get_tax_dashboard(
		self,
		session: Any,
		tenant_id: str,
	) -> dict:
		"""Return a high-level tax dashboard summary for the tenant.

		Returns:
		{
		    "pending_returns":          int,   # DRAFT returns not yet filed
		    "overdue_returns":          int,   # DRAFT returns past due_date
		    "ytd_vat_payable_cents":    int,   # net VAT owed YTD (output - input)
		    "ytd_wht_withheld_cents":   int,   # total WHT deducted YTD from WHTCertificates
		    "next_filing_deadline":     dict | None,  # nearest upcoming calendar entry
		}
		"""
		from pgappforge.plugins.erp.finance.tax.models import (
			TaxCode, TaxJurisdiction, TaxReturn, TaxTransaction, WHTCertificate,
		)

		today = date.today()
		year_start = date(today.year, 1, 1)

		# Pending (DRAFT) returns
		pending_q = (
			sa.select(sa.func.count())
			.select_from(TaxReturn)
			.where(TaxReturn.tenant_id == tenant_id)
			.where(TaxReturn.status == "DRAFT")
		)
		pending_count: int = session.execute(pending_q).scalar_one()

		# Overdue: DRAFT and due_date < today
		overdue_q = (
			sa.select(sa.func.count())
			.select_from(TaxReturn)
			.where(TaxReturn.tenant_id == tenant_id)
			.where(TaxReturn.status == "DRAFT")
			.where(TaxReturn.due_date < today)
			.where(TaxReturn.due_date.isnot(None))
		)
		overdue_count: int = session.execute(overdue_q).scalar_one()

		# YTD VAT: sum output minus sum input from VAT jurisdiction transactions
		vat_output_q = (
			sa.select(sa.func.coalesce(sa.func.sum(TaxTransaction.tax_amount_cents), 0))
			.join(TaxCode, TaxTransaction.tax_code_id == TaxCode.id)
			.join(TaxJurisdiction, TaxCode.jurisdiction_id == TaxJurisdiction.id)
			.where(TaxTransaction.tenant_id == tenant_id)
			.where(TaxJurisdiction.tax_type == "VAT")
			.where(TaxCode.is_output_tax.is_(True))
			.where(TaxTransaction.posting_date >= year_start)
		)
		ytd_output: int = session.execute(vat_output_q).scalar_one()

		vat_input_q = (
			sa.select(sa.func.coalesce(sa.func.sum(TaxTransaction.tax_amount_cents), 0))
			.join(TaxCode, TaxTransaction.tax_code_id == TaxCode.id)
			.join(TaxJurisdiction, TaxCode.jurisdiction_id == TaxJurisdiction.id)
			.where(TaxTransaction.tenant_id == tenant_id)
			.where(TaxJurisdiction.tax_type == "VAT")
			.where(TaxCode.is_input_tax.is_(True))
			.where(TaxTransaction.is_recoverable.is_(True))
			.where(TaxTransaction.posting_date >= year_start)
		)
		ytd_input: int = session.execute(vat_input_q).scalar_one()

		# YTD WHT: sum from WHTCertificates
		wht_q = (
			sa.select(sa.func.coalesce(sa.func.sum(WHTCertificate.wht_amount_cents), 0))
			.where(WHTCertificate.tenant_id == tenant_id)
			.where(WHTCertificate.payment_date >= year_start)
			.where(WHTCertificate.voided_at.is_(None))
		)
		ytd_wht: int = session.execute(wht_q).scalar_one()

		# Next filing deadline from calendar
		calendar = self.get_tax_calendar(session, today.year, tenant_id)
		upcoming = [e for e in calendar if e["status"] in ("DUE_SOON", "UPCOMING")]
		next_deadline = upcoming[0] if upcoming else None

		return {
			"pending_returns": pending_count,
			"overdue_returns": overdue_count,
			"ytd_vat_payable_cents": ytd_output - ytd_input,
			"ytd_wht_withheld_cents": ytd_wht,
			"next_filing_deadline": next_deadline,
		}


__all__ = [
	"TaxService",
	"TaxServiceError",
	"TaxCodeNotFoundError",
	"TaxReturnNotFoundError",
	"TaxReturnStatusError",
	"TaxTransactionDetails",
	# Methods on TaxService (documented here for discoverability):
	# apply_tax, generate_vat_return, generate_wht_return,
	# issue_wht_certificate, file_tax_return, file_return, pay_return,
	# get_tax_calendar, get_tax_dashboard,
	# get_applicable_tax_code, get_period_transactions, determine_tax
]
