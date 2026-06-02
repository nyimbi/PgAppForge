"""
pgappforge/plugins/erp/hcm/payroll/services.py

PayrollService — stateless business logic for the HCM Payroll plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents
  - Decimal arithmetic used internally; results rounded half-up to int
  - exchange_rate columns read as Decimal(str(row.exchange_rate)) — never float

Public methods:
  calculate_payrun(payrun_id, session)              -> PayrollRun
  approve_payrun(payrun_id, approver_id, session)   -> PayrollRun
  mark_paid(payrun_id, session)                     -> PayrollRun
  generate_bank_file(payrun_id, session)            -> str   (ISO 20022 PAIN.001 XML)
  post_to_gl(payrun_id, session)                    -> dict
  reverse_payslip(payslip_id, reason, session)      -> Payslip  (new reversal row)
  get_active_tax_withholding(employee_id, jurisdiction_code, as_of, session)
                                                    -> TaxWithholding | None
  statutory_report(entity_id, year, session)        -> dict
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PayrollServiceError(Exception):
	"""Base domain error for payroll operations."""


class PayrollRunNotFoundError(PayrollServiceError):
	pass


class PayslipNotFoundError(PayrollServiceError):
	pass


class PayrollStateError(PayrollServiceError):
	"""Invalid state transition."""


class PayrollCalculationError(PayrollServiceError):
	"""Business rule violation during gross→net calculation."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today() -> date:
	return datetime.now(timezone.utc).date()


def _round_cents(d: Decimal) -> int:
	return int(d.to_integral_value(rounding=ROUND_HALF_UP))


def _iso20022_pain001_payroll(payrun: Any, payslips: list[Any]) -> str:
	"""Generate ISO 20022 pain.001.001.03 XML for payroll net-pay transfers.

	Structural skeleton — production use requires a certified library
	(e.g. schwifty + lxml) and bank-specific customisations.
	Each Payslip becomes one CdtTrfTxInf element.
	"""
	now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
	total_net = sum(p.net_pay_cents for p in payslips)
	total_net_dec = Decimal(total_net) / 100

	lines: list[str] = [
		'<?xml version="1.0" encoding="UTF-8"?>',
		'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">',
		'  <CstmrCdtTrfInitn>',
		'    <GrpHdr>',
		f'      <MsgId>PAYROLL-{payrun.id[:8].upper()}</MsgId>',
		f'      <CreDtTm>{now_str}</CreDtTm>',
		f'      <NbOfTxs>{len(payslips)}</NbOfTxs>',
		f'      <CtrlSum>{total_net_dec:.2f}</CtrlSum>',
		'      <InitgPty><Nm>PgAppForge Payroll</Nm></InitgPty>',
		'    </GrpHdr>',
		'    <PmtInf>',
		f'      <PmtInfId>PAY-{payrun.id[:8].upper()}</PmtInfId>',
		'      <PmtMtd>TRF</PmtMtd>',
		f'      <ReqdExctnDt>{payrun.pay_date.isoformat()}</ReqdExctnDt>',
		'      <DbtrAcct><Id><Othr><Id>COMPANY-PAYROLL</Id></Othr></Id></DbtrAcct>',
	]

	for ps in payslips:
		if not ps.net_pay_cents or ps.net_pay_cents <= 0:
			continue
		amount_dec = Decimal(ps.net_pay_cents) / 100
		ref = ps.payment_reference or str(uuid.uuid4())
		iban = ps.bank_account_iban or "NOTPROVIDED"
		lines += [
			'      <CdtTrfTxInf>',
			'        <PmtId>',
			f'          <EndToEndId>{ref}</EndToEndId>',
			'        </PmtId>',
			'        <Amt>',
			f'          <InstdAmt Ccy="{ps.currency_code}">{amount_dec:.2f}</InstdAmt>',
			'        </Amt>',
			'        <CdtrAcct>',
			f'          <Id><IBAN>{iban}</IBAN></Id>',
			'        </CdtrAcct>',
			f'        <RmtInf><Ustrd>{ref}</Ustrd></RmtInf>',
			'      </CdtTrfTxInf>',
		]

	lines += [
		'    </PmtInf>',
		'  </CstmrCdtTrfInitn>',
		'</Document>',
	]
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# PayrollService
# ---------------------------------------------------------------------------

class PayrollService:
	"""Stateless payroll domain service.

	Instantiate once per application (no instance state).
	All public methods accept a SQLAlchemy Session as an explicit argument.

	Calculation model (simplified):
	  gross_pay = sum of BASIC + OVERTIME + BONUS + COMMISSION + ALLOWANCE lines
	  income_tax = derived from TaxWithholding (bracket lookup or flat rate)
	  ni_employee = gross * NI_RATE (jurisdiction-specific; default 12%)
	  pension_employee = gross * PENSION_EMPLOYEE_RATE (default 5%)
	  pension_employer = gross * PENSION_EMPLOYER_RATE (default 3%)
	  net_pay = gross - income_tax - ni_employee - pension_employee - other_deductions

	Production deployments must inject a jurisdiction-specific tax engine via
	calculate_payrun()'s tax_calculator kwarg.
	"""

	# Default statutory rates — override via app config or tax_calculator injection
	DEFAULT_NI_EMPLOYEE_RATE = Decimal("0.12")
	DEFAULT_PENSION_EMPLOYEE_RATE = Decimal("0.05")
	DEFAULT_PENSION_EMPLOYER_RATE = Decimal("0.03")
	DEFAULT_INCOME_TAX_RATE = Decimal("0.20")  # Flat fallback; real engine replaces this

	# ------------------------------------------------------------------
	# calculate_payrun
	# ------------------------------------------------------------------

	def calculate_payrun(
		self,
		payrun_id: str,
		session: Any,
		*,
		employee_data: list[dict] | None = None,
		tax_calculator: Any | None = None,
	) -> Any:
		"""Compute gross→net for all employees and create/update Payslips.

		For each employee dict in employee_data (or pre-existing Payslips in DRAFT),
		this method:
		  1. Sums earnings lines → gross_pay_cents
		  2. Calls tax_calculator.compute() if provided, else applies flat rates
		  3. Creates PayslipLine rows for each component
		  4. Creates/updates Payslip with final amounts
		  5. Updates PayrollRun aggregate counters
		  6. Sets status = CALCULATED, calculated_at = now()
		  7. Emits PayrollRunCalculatedEvent

		employee_data format:
		  [{
		    "employee_id": str,
		    "bank_account_iban": str,
		    "currency_code": str,  # default "USD"
		    "payment_reference": str,
		    "earnings": [
		      {"line_type": str, "description": str, "units": str, "rate_cents": int, "amount_cents": int,
		       "gl_account": str, "cost_center": str},
		    ],
		    "deductions": [   # optional pre-computed deductions
		      {"line_type": "DEDUCTION", "description": str, "amount_cents": int},
		    ],
		    "other_deductions_cents": int,  # loan repayments etc.
		    "tax_withholding_override_cents": int,  # manual override
		  }]

		If employee_data is None, expects Payslips already present with status=DRAFT.

		Args:
			payrun_id: UUID of the PayrollRun.
			session: SQLAlchemy session (caller commits).
			employee_data: List of employee earning dicts (see above).
			tax_calculator: Optional callable(gross_cents, employee_id, session) -> dict
			                returning {income_tax_cents, ni_employee_cents, pension_employee_cents,
			                           pension_employer_cents}.

		Returns:
			Updated PayrollRun.

		Raises:
			PayrollRunNotFoundError: PayrollRun not found.
			PayrollStateError: PayrollRun not in DRAFT status.
			PayrollCalculationError: Any per-employee calculation error.
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip, PayslipLine
		from pgappforge.plugins.erp.hcm.payroll.events import PayrollRunCalculatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		payrun = session.get(PayrollRun, payrun_id)
		if payrun is None:
			raise PayrollRunNotFoundError(f"PayrollRun {payrun_id!r} not found")
		if payrun.status != "DRAFT":
			raise PayrollStateError(
				f"PayrollRun {payrun_id!r} is {payrun.status!r}; can only calculate DRAFT runs"
			)

		assert employee_data is not None, "employee_data must be provided to calculate_payrun"

		total_gross = 0
		total_emp_tax = 0
		total_er_tax = 0
		total_net = 0
		processed = 0

		for emp in employee_data:
			emp_id = emp["employee_id"]
			currency = emp.get("currency_code", "USD")

			# --- Gross pay from earnings lines ---
			gross_cents = 0
			earnings_lines: list[PayslipLine] = []
			for el in emp.get("earnings", []):
				amt = int(el["amount_cents"])
				assert isinstance(amt, int), f"amount_cents must be int, got {type(amt)}"
				gross_cents += amt
				earnings_lines.append(PayslipLine(
					tenant_id=payrun.tenant_id,
					line_type=el.get("line_type", "BASIC"),
					description=el["description"],
					units=Decimal(str(el.get("units", 1))),
					rate_cents=int(el.get("rate_cents", amt)),
					amount_cents=amt,
					is_employer_cost=False,
					gl_account=el.get("gl_account"),
					cost_center=el.get("cost_center"),
				))

			# --- Tax computation ---
			if tax_calculator is not None:
				tax_result = tax_calculator.compute(gross_cents, emp_id, session)
				income_tax = int(tax_result["income_tax_cents"])
				ni_emp = int(tax_result.get("ni_employee_cents", 0))
				pension_emp = int(tax_result.get("pension_employee_cents", 0))
				pension_er = int(tax_result.get("pension_employer_cents", 0))
			else:
				# Check for TaxWithholding override
				wh = self.get_active_tax_withholding(emp_id, "DEFAULT", payrun.period_end, session)
				if wh is not None:
					# Flat rate + additional withholding
					income_tax = _round_cents(
						Decimal(gross_cents) * self.DEFAULT_INCOME_TAX_RATE
					) + wh.additional_withholding_cents
				else:
					income_tax = _round_cents(Decimal(gross_cents) * self.DEFAULT_INCOME_TAX_RATE)

				ni_emp = _round_cents(Decimal(gross_cents) * self.DEFAULT_NI_EMPLOYEE_RATE)
				pension_emp = _round_cents(Decimal(gross_cents) * self.DEFAULT_PENSION_EMPLOYEE_RATE)
				pension_er = _round_cents(Decimal(gross_cents) * self.DEFAULT_PENSION_EMPLOYER_RATE)

			# User-supplied override
			if emp.get("tax_withholding_override_cents") is not None:
				income_tax = int(emp["tax_withholding_override_cents"])

			other_deductions = int(emp.get("other_deductions_cents", 0))
			net_pay = gross_cents - income_tax - ni_emp - pension_emp - other_deductions
			assert isinstance(net_pay, int), "net_pay must be int"

			# --- Create/update Payslip ---
			existing = session.execute(
				sa.select(Payslip)
				.where(Payslip.payrun_id == payrun_id)
				.where(Payslip.employee_id == emp_id)
			).scalar_one_or_none()

			if existing is not None and existing.status != "DRAFT":
				raise PayrollCalculationError(
					f"Payslip for employee {emp_id!r} already in status {existing.status!r}"
				)

			if existing is not None:
				# Clear existing lines before recalculating
				for old_line in list(existing.lines):
					session.delete(old_line)
				session.flush()
				ps = existing
			else:
				ps = Payslip(
					tenant_id=payrun.tenant_id,
					payrun_id=payrun_id,
					employee_id=emp_id,
					currency_code=currency,
				)
				session.add(ps)
				session.flush()

			ps.gross_pay_cents = gross_cents
			ps.income_tax_cents = income_tax
			ps.national_insurance_cents = ni_emp
			ps.pension_employee_cents = pension_emp
			ps.pension_employer_cents = pension_er
			ps.other_deductions_cents = other_deductions
			ps.net_pay_cents = net_pay
			ps.bank_account_iban = emp.get("bank_account_iban")
			ps.payment_reference = emp.get("payment_reference") or f"PAY-{ps.id[:8].upper()}"
			ps.status = "CALCULATED"

			# Attach lines
			for line in earnings_lines:
				line.payslip_id = ps.id
				session.add(line)

			# Tax deduction lines
			tax_lines = [
				("TAX", "Income Tax", income_tax),
				("TAX", "National Insurance (Employee)", ni_emp),
				("DEDUCTION", "Pension (Employee)", pension_emp),
			]
			for lt, desc, amt in tax_lines:
				if amt:
					session.add(PayslipLine(
						tenant_id=payrun.tenant_id,
						payslip_id=ps.id,
						line_type=lt,
						description=desc,
						units=Decimal("1"),
						rate_cents=amt,
						amount_cents=-amt,  # deductions are negative
						is_employer_cost=False,
					))

			# Employer pension (cost only — not deducted from net)
			if pension_er:
				session.add(PayslipLine(
					tenant_id=payrun.tenant_id,
					payslip_id=ps.id,
					line_type="DEDUCTION",
					description="Pension (Employer)",
					units=Decimal("1"),
					rate_cents=pension_er,
					amount_cents=pension_er,
					is_employer_cost=True,
				))

			# Other deductions (loan etc.)
			for od in emp.get("deductions", []):
				amt = int(od["amount_cents"])
				session.add(PayslipLine(
					tenant_id=payrun.tenant_id,
					payslip_id=ps.id,
					line_type=od.get("line_type", "DEDUCTION"),
					description=od["description"],
					units=Decimal("1"),
					rate_cents=amt,
					amount_cents=-amt,
					is_employer_cost=False,
				))

			total_gross += gross_cents
			total_emp_tax += income_tax + ni_emp
			total_er_tax += pension_er
			total_net += net_pay
			processed += 1

		assert isinstance(total_gross, int)
		assert isinstance(total_net, int)

		payrun.employee_count = processed
		payrun.total_gross_cents = total_gross
		payrun.total_employee_tax_cents = total_emp_tax
		payrun.total_employer_tax_cents = total_er_tax
		payrun.total_net_cents = total_net
		payrun.status = "CALCULATED"
		payrun.calculated_at = datetime.now(timezone.utc)
		payrun.updated_at = datetime.now(timezone.utc)

		emit_event(
			PayrollRunCalculatedEvent(
				aggregate_id=payrun_id,
				aggregate_type="PayrollRun",
				tenant_id=payrun.tenant_id,
				payrun_id=payrun_id,
				entity_id=payrun.entity_id,
				period_start=payrun.period_start.isoformat(),
				period_end=payrun.period_end.isoformat(),
				pay_date=payrun.pay_date.isoformat(),
				payroll_type=payrun.payroll_type,
				employee_count=processed,
				total_gross_cents=total_gross,
				total_employee_tax_cents=total_emp_tax,
				total_employer_tax_cents=total_er_tax,
				total_net_cents=total_net,
				currency="USD",
			),
			session,
		)

		log.info(
			"PayrollService.calculate_payrun: run=%s employees=%d gross=%d¢ net=%d¢",
			payrun_id, processed, total_gross, total_net,
		)
		return payrun

	# ------------------------------------------------------------------
	# approve_payrun
	# ------------------------------------------------------------------

	def approve_payrun(
		self,
		payrun_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Approve a CALCULATED payroll run.

		Transitions: CALCULATED → APPROVED
		Sets approved_by, approved_at, updates all Payslips to APPROVED.

		Raises:
			PayrollRunNotFoundError
			PayrollStateError: not in CALCULATED status
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip
		from pgappforge.plugins.erp.hcm.payroll.events import PayrollRunApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		payrun = session.get(PayrollRun, payrun_id)
		if payrun is None:
			raise PayrollRunNotFoundError(f"PayrollRun {payrun_id!r} not found")
		if payrun.status != "CALCULATED":
			raise PayrollStateError(
				f"PayrollRun {payrun_id!r} is {payrun.status!r}; must be CALCULATED to approve"
			)

		now = datetime.now(timezone.utc)
		payrun.approved_by = approver_id
		payrun.approved_at = now
		payrun.status = "APPROVED"
		payrun.updated_at = now

		# Bulk update payslips
		session.execute(
			sa.update(Payslip)
			.where(Payslip.payrun_id == payrun_id)
			.where(Payslip.status == "CALCULATED")
			.values(status="APPROVED", updated_at=now)
		)

		emit_event(
			PayrollRunApprovedEvent(
				aggregate_id=payrun_id,
				aggregate_type="PayrollRun",
				tenant_id=payrun.tenant_id,
				payrun_id=payrun_id,
				entity_id=payrun.entity_id,
				approved_by=approver_id,
				total_net_cents=payrun.total_net_cents,
				pay_date=payrun.pay_date.isoformat(),
			),
			session,
		)
		log.info("PayrollService.approve_payrun: run=%s approved_by=%s", payrun_id, approver_id)
		return payrun

	# ------------------------------------------------------------------
	# mark_paid
	# ------------------------------------------------------------------

	def mark_paid(self, payrun_id: str, session: Any, bank_file_ref: str = "") -> Any:
		"""Mark an APPROVED payroll run as PAID after bank confirmation.

		Transitions: APPROVED → PAID
		Sets paid_at, updates all Payslips to PAID.

		Raises:
			PayrollRunNotFoundError
			PayrollStateError: not in APPROVED status
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip
		from pgappforge.plugins.erp.hcm.payroll.events import PayrollRunPaidEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		payrun = session.get(PayrollRun, payrun_id)
		if payrun is None:
			raise PayrollRunNotFoundError(f"PayrollRun {payrun_id!r} not found")
		if payrun.status != "APPROVED":
			raise PayrollStateError(
				f"PayrollRun {payrun_id!r} is {payrun.status!r}; must be APPROVED to mark paid"
			)

		now = datetime.now(timezone.utc)
		payrun.paid_at = now
		payrun.status = "PAID"
		payrun.updated_at = now
		if bank_file_ref:
			payrun.metadata_ = {**payrun.metadata_, "bank_file_ref": bank_file_ref}

		session.execute(
			sa.update(Payslip)
			.where(Payslip.payrun_id == payrun_id)
			.where(Payslip.status == "APPROVED")
			.values(status="PAID", updated_at=now)
		)

		emit_event(
			PayrollRunPaidEvent(
				aggregate_id=payrun_id,
				aggregate_type="PayrollRun",
				tenant_id=payrun.tenant_id,
				payrun_id=payrun_id,
				entity_id=payrun.entity_id,
				pay_date=payrun.pay_date.isoformat(),
				total_net_cents=payrun.total_net_cents,
				employee_count=payrun.employee_count,
				currency="USD",
				bank_file_ref=bank_file_ref,
			),
			session,
		)
		log.info("PayrollService.mark_paid: run=%s net=%d¢", payrun_id, payrun.total_net_cents)
		return payrun

	# ------------------------------------------------------------------
	# generate_bank_file
	# ------------------------------------------------------------------

	def generate_bank_file(self, payrun_id: str, session: Any) -> str:
		"""Generate ISO 20022 PAIN.001 XML for net-pay transfers.

		PayrollRun must be APPROVED or PAID.
		Returns the XML string; caller is responsible for writing to disk /
		object-store and updating payrun.metadata_['bank_file_ref'].

		Args:
			payrun_id: UUID of PayrollRun.
			session: SQLAlchemy session.

		Returns:
			ISO 20022 pain.001.001.03 XML string.

		Raises:
			PayrollRunNotFoundError
			PayrollStateError: run not in APPROVED or PAID
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip

		payrun = session.get(PayrollRun, payrun_id)
		if payrun is None:
			raise PayrollRunNotFoundError(f"PayrollRun {payrun_id!r} not found")
		if payrun.status not in ("APPROVED", "PAID"):
			raise PayrollStateError(
				f"PayrollRun {payrun_id!r} is {payrun.status!r}; must be APPROVED or PAID to generate bank file"
			)

		payslips = session.execute(
			sa.select(Payslip)
			.where(Payslip.payrun_id == payrun_id)
			.where(Payslip.status.in_(["APPROVED", "PAID"]))
			.order_by(Payslip.employee_id)
		).scalars().all()

		xml = _iso20022_pain001_payroll(payrun, payslips)
		log.info(
			"PayrollService.generate_bank_file: run=%s payslips=%d",
			payrun_id, len(payslips),
		)
		return xml

	# ------------------------------------------------------------------
	# post_to_gl
	# ------------------------------------------------------------------

	def post_to_gl(self, payrun_id: str, session: Any) -> dict[str, Any]:
		"""Create double-entry GL journal for a payroll run.

		Journal:
		  DR  Salary Expense (5000)         total_gross_cents
		  CR  Bank / Net Pay Clearing (1100) total_net_cents
		  CR  PAYE Tax Payable (2100)        total_employee_tax_cents
		  CR  Pension Payable (2200)         pension_employee + pension_employer

		Returns journal dict; emits PayrollGLPostedEvent.
		If GL plugin is loaded, forwards to gl.post_journal().

		Raises:
			PayrollRunNotFoundError
			PayrollStateError: run must be APPROVED or PAID
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun
		from pgappforge.plugins.erp.hcm.payroll.events import PayrollGLPostedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		payrun = session.get(PayrollRun, payrun_id)
		if payrun is None:
			raise PayrollRunNotFoundError(f"PayrollRun {payrun_id!r} not found")
		if payrun.status not in ("APPROVED", "PAID"):
			raise PayrollStateError(
				f"PayrollRun {payrun_id!r} is {payrun.status!r}; must be APPROVED or PAID for GL posting"
			)

		journal_id = str(uuid.uuid4())

		# Calculate pension total from payslips
		from pgappforge.plugins.erp.hcm.payroll.models import Payslip
		pension_total = session.execute(
			sa.select(
				sa.func.coalesce(
					sa.func.sum(Payslip.pension_employee_cents + Payslip.pension_employer_cents), 0
				)
			).where(Payslip.payrun_id == payrun_id)
		).scalar() or 0

		assert isinstance(payrun.total_gross_cents, int)
		assert isinstance(payrun.total_net_cents, int)
		assert isinstance(payrun.total_employee_tax_cents, int)

		journal = {
			"journal_id": journal_id,
			"payrun_id": payrun_id,
			"tenant_id": payrun.tenant_id,
			"journal_date": payrun.pay_date.isoformat(),
			"description": f"Payroll {payrun.period_start}–{payrun.period_end}",
			"debit_lines": [
				{
					"account": "5000",
					"amount_cents": payrun.total_gross_cents,
					"description": "Salary & Wages Expense",
				},
				{
					"account": "5010",
					"amount_cents": payrun.total_employer_tax_cents,
					"description": "Employer NI / Social Security",
				},
			],
			"credit_lines": [
				{
					"account": "1100",
					"amount_cents": payrun.total_net_cents,
					"description": "Net Pay — Bank Clearing",
				},
				{
					"account": "2100",
					"amount_cents": payrun.total_employee_tax_cents,
					"description": "PAYE / Income Tax Payable",
				},
				{
					"account": "2200",
					"amount_cents": int(pension_total),
					"description": "Pension Contributions Payable",
				},
			],
		}

		# Best-effort GL plugin forward
		try:
			from flask import current_app
			gl = current_app.extensions.get("pgaf_gl")
			if gl is not None:
				gl.post_journal(journal)
		except Exception as exc:
			log.debug("PayrollService.post_to_gl: GL plugin not available (%s)", exc)

		payrun.gl_journal_id = journal_id
		payrun.updated_at = datetime.now(timezone.utc)

		emit_event(
			PayrollGLPostedEvent(
				aggregate_id=payrun_id,
				aggregate_type="PayrollRun",
				tenant_id=payrun.tenant_id,
				payrun_id=payrun_id,
				journal_id=journal_id,
				salary_expense_account="5000",
				bank_account="1100",
				tax_payable_account="2100",
				total_gross_cents=payrun.total_gross_cents,
				total_net_cents=payrun.total_net_cents,
				currency="USD",
			),
			session,
		)
		log.info(
			"PayrollService.post_to_gl: run=%s journal=%s gross=%d¢",
			payrun_id, journal_id, payrun.total_gross_cents,
		)
		return journal

	# ------------------------------------------------------------------
	# reverse_payslip
	# ------------------------------------------------------------------

	def reverse_payslip(
		self,
		payslip_id: str,
		reason: str,
		session: Any,
	) -> Any:
		"""Create a reversal Payslip with negated amounts.

		The original Payslip is marked REVERSED.  A new Payslip row is created
		in the SAME payrun with all amounts negated (immutable ledger pattern).
		The reversal Payslip also gets PayslipLine rows with negated amounts.

		Raises:
			PayslipNotFoundError
			PayrollStateError: only PAID payslips can be reversed
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import Payslip, PayslipLine
		from pgappforge.plugins.erp.hcm.payroll.events import PayslipReversedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		original = session.get(Payslip, payslip_id)
		if original is None:
			raise PayslipNotFoundError(f"Payslip {payslip_id!r} not found")
		if original.status != "PAID":
			raise PayrollStateError(
				f"Payslip {payslip_id!r} is {original.status!r}; only PAID payslips can be reversed"
			)

		now = datetime.now(timezone.utc)

		# New reversal payslip
		reversal = Payslip(
			tenant_id=original.tenant_id,
			payrun_id=original.payrun_id,
			employee_id=original.employee_id,
			gross_pay_cents=-original.gross_pay_cents,
			income_tax_cents=-original.income_tax_cents,
			national_insurance_cents=-original.national_insurance_cents,
			pension_employee_cents=-original.pension_employee_cents,
			pension_employer_cents=-original.pension_employer_cents,
			other_deductions_cents=-original.other_deductions_cents,
			net_pay_cents=-original.net_pay_cents,
			bank_account_iban=original.bank_account_iban,
			currency_code=original.currency_code,
			payment_reference=f"REV-{original.payment_reference or original.id[:8].upper()}",
			status="REVERSED",
		)
		session.add(reversal)
		session.flush()

		# Negate all original lines
		for orig_line in original.lines:
			session.add(PayslipLine(
				tenant_id=orig_line.tenant_id,
				payslip_id=reversal.id,
				line_type=orig_line.line_type,
				description=f"[REVERSAL] {orig_line.description}",
				units=orig_line.units,
				rate_cents=orig_line.rate_cents,
				amount_cents=-orig_line.amount_cents,
				is_employer_cost=orig_line.is_employer_cost,
				gl_account=orig_line.gl_account,
				cost_center=orig_line.cost_center,
			))

		original.status = "REVERSED"
		original.updated_at = now

		emit_event(
			PayslipReversedEvent(
				aggregate_id=reversal.id,
				aggregate_type="Payslip",
				tenant_id=original.tenant_id,
				payslip_id=reversal.id,
				original_payslip_id=payslip_id,
				employee_id=original.employee_id,
				payrun_id=original.payrun_id,
				net_pay_cents=reversal.net_pay_cents,
				reason=reason,
			),
			session,
		)
		log.info(
			"PayrollService.reverse_payslip: original=%s reversal=%s employee=%s",
			payslip_id, reversal.id, original.employee_id,
		)
		return reversal

	# ------------------------------------------------------------------
	# get_active_tax_withholding
	# ------------------------------------------------------------------

	def get_active_tax_withholding(
		self,
		employee_id: str,
		jurisdiction_code: str,
		as_of: date,
		session: Any,
	) -> Any | None:
		"""Return the effective TaxWithholding row for employee/jurisdiction/date.

		Selects the row with the latest effective_from <= as_of.

		Returns None if no configuration found.
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import TaxWithholding

		return session.execute(
			sa.select(TaxWithholding)
			.where(TaxWithholding.employee_id == employee_id)
			.where(TaxWithholding.jurisdiction_code == jurisdiction_code)
			.where(TaxWithholding.effective_from <= as_of)
			.order_by(sa.desc(TaxWithholding.effective_from))
			.limit(1)
		).scalar_one_or_none()

	# ------------------------------------------------------------------
	# statutory_report
	# ------------------------------------------------------------------

	def statutory_report(
		self,
		entity_id: str,
		year: int,
		session: Any,
	) -> dict[str, Any]:
		"""Generate annual statutory payroll summary for government submission.

		Aggregates all PAID payroll runs for entity_id in the given year.

		Returns:
		  {
		    entity_id, year,
		    total_employees,
		    total_gross_cents,
		    total_income_tax_cents,
		    total_ni_employee_cents,
		    total_pension_employee_cents,
		    total_pension_employer_cents,
		    total_net_cents,
		    payroll_runs: [{payrun_id, period_start, period_end, employee_count,
		                    gross_cents, net_cents}],
		    generated_at: ISO datetime,
		  }
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip

		start_date = date(year, 1, 1)
		end_date = date(year, 12, 31)

		runs = session.execute(
			sa.select(PayrollRun)
			.where(PayrollRun.entity_id == entity_id)
			.where(PayrollRun.status == "PAID")
			.where(PayrollRun.period_start >= start_date)
			.where(PayrollRun.period_end <= end_date)
			.order_by(PayrollRun.period_start)
		).scalars().all()

		run_summaries = []
		agg_gross = 0
		agg_emp_tax = 0
		agg_er_tax = 0
		agg_net = 0
		all_employee_ids: set[str] = set()

		for run in runs:
			agg_gross += run.total_gross_cents
			agg_emp_tax += run.total_employee_tax_cents
			agg_er_tax += run.total_employer_tax_cents
			agg_net += run.total_net_cents

			employee_ids = session.execute(
				sa.select(Payslip.employee_id)
				.where(Payslip.payrun_id == run.id)
				.where(Payslip.status == "PAID")
			).scalars().all()
			all_employee_ids.update(employee_ids)

			run_summaries.append({
				"payrun_id": run.id,
				"period_start": run.period_start.isoformat(),
				"period_end": run.period_end.isoformat(),
				"pay_date": run.pay_date.isoformat(),
				"payroll_type": run.payroll_type,
				"employee_count": run.employee_count,
				"gross_cents": run.total_gross_cents,
				"employee_tax_cents": run.total_employee_tax_cents,
				"net_cents": run.total_net_cents,
			})

		# Pension breakdown from payslips
		pension_totals = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(Payslip.pension_employee_cents), 0).label("emp"),
				sa.func.coalesce(sa.func.sum(Payslip.pension_employer_cents), 0).label("er"),
				sa.func.coalesce(sa.func.sum(Payslip.national_insurance_cents), 0).label("ni"),
				sa.func.coalesce(sa.func.sum(Payslip.income_tax_cents), 0).label("tax"),
			)
			.join(PayrollRun, Payslip.payrun_id == PayrollRun.id)
			.where(PayrollRun.entity_id == entity_id)
			.where(PayrollRun.status == "PAID")
			.where(PayrollRun.period_start >= start_date)
			.where(PayrollRun.period_end <= end_date)
			.where(Payslip.status == "PAID")
		).one()

		assert isinstance(int(agg_gross), int)

		result = {
			"entity_id": entity_id,
			"year": year,
			"total_employees": len(all_employee_ids),
			"total_gross_cents": agg_gross,
			"total_income_tax_cents": int(pension_totals.tax),
			"total_ni_employee_cents": int(pension_totals.ni),
			"total_pension_employee_cents": int(pension_totals.emp),
			"total_pension_employer_cents": int(pension_totals.er),
			"total_net_cents": agg_net,
			"payroll_runs": run_summaries,
			"generated_at": datetime.now(timezone.utc).isoformat(),
		}
		log.info(
			"PayrollService.statutory_report: entity=%s year=%d runs=%d employees=%d gross=%d¢",
			entity_id, year, len(runs), len(all_employee_ids), agg_gross,
		)
		return result


__all__ = [
	"PayrollService",
	"PayrollServiceError",
	"PayrollRunNotFoundError",
	"PayslipNotFoundError",
	"PayrollStateError",
	"PayrollCalculationError",
]
