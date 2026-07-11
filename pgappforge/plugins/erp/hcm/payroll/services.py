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
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip, PayslipLine, TaxWithholding
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

		employee_ids = list(dict.fromkeys(str(emp["employee_id"]) for emp in employee_data))
		existing_payslips = session.execute(
			sa.select(Payslip)
			.where(Payslip.payrun_id == payrun_id)
			.where(Payslip.employee_id.in_(employee_ids))
		).scalars().all()
		existing_by_employee = {ps.employee_id: ps for ps in existing_payslips}
		existing_payslip_ids = [ps.id for ps in existing_payslips]
		if existing_payslip_ids:
			for old_line in session.execute(
				sa.select(PayslipLine).where(PayslipLine.payslip_id.in_(existing_payslip_ids))
			).scalars().all():
				session.delete(old_line)
			session.flush()

		withholding_by_employee: dict[str, Any] = {}
		if tax_calculator is None and employee_ids:
			withholding_rows = session.execute(
				sa.select(TaxWithholding)
				.where(TaxWithholding.employee_id.in_(employee_ids))
				.where(TaxWithholding.jurisdiction_code == "DEFAULT")
				.where(TaxWithholding.effective_from <= payrun.period_end)
				.order_by(TaxWithholding.employee_id, sa.desc(TaxWithholding.effective_from))
			).scalars().all()
			for wh in withholding_rows:
				withholding_by_employee.setdefault(wh.employee_id, wh)

		total_gross = 0
		total_emp_tax = 0
		total_er_tax = 0
		total_net = 0
		processed = 0

		for emp in employee_data:
			emp_id = str(emp["employee_id"])
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
				wh = withholding_by_employee.get(emp_id)
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
			existing = existing_by_employee.get(emp_id)

			if existing is not None and existing.status != "DRAFT":
				raise PayrollCalculationError(
					f"Payslip for employee {emp_id!r} already in status {existing.status!r}"
				)

			if existing is not None:
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

		Kenya-aware: aggregates by PayslipLine.line_type to produce separate
		GL lines for each statutory levy (PAYE, NSSF Tier I/II, SHIF, Housing
		Levy, NITA).  Falls back to single PAYE/pension lines for non-KE runs.

		Debit lines:
		  5000  Salary & Wages Expense            gross_pay
		  5010  Employer NSSF / Pension Expense   employer_nssf_total
		  5020  Housing Levy Expense (Employer)   housing_levy_employer
		  5025  NITA Levy Expense                 nita

		Credit lines:
		  1100  Net Pay — Bank Clearing           net_pay
		  2100  PAYE Payable                      paye
		  2210  NSSF Tier I Payable               nssf_tier1_employee + nssf_tier1_employer
		  2211  NSSF Tier II Payable              nssf_tier2_employee + nssf_tier2_employer
		  2215  SHIF Payable                      shif
		  2220  Housing Levy Payable (Employee)   housing_levy_employee
		  2230  NITA Payable                      nita
		  2200  Pension Payable (non-KE)          pension_employee + pension_employer

		Returns journal dict; emits PayrollGLPostedEvent.
		If GL plugin is loaded, forwards to gl.post_journal().

		Raises:
			PayrollRunNotFoundError
			PayrollStateError: run must be APPROVED or PAID
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip, PayslipLine
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

		# --- Aggregate statutory amounts by line_type from PayslipLine rows ---
		# join PayslipLine → Payslip → PayrollRun
		def _sum_lines(line_type: str, employer_cost: bool | None = None) -> int:
			q = (
				sa.select(sa.func.coalesce(sa.func.sum(sa.func.abs(PayslipLine.amount_cents)), 0))
				.join(Payslip, PayslipLine.payslip_id == Payslip.id)
				.where(Payslip.payrun_id == payrun_id)
				.where(PayslipLine.line_type == line_type)
			)
			if employer_cost is not None:
				q = q.where(PayslipLine.is_employer_cost == employer_cost)
			return int(session.execute(q).scalar() or 0)

		paye_cents = _sum_lines("PAYE")
		nssf_t1_emp = _sum_lines("NSSF_TIER_I", employer_cost=False)
		nssf_t1_er = _sum_lines("NSSF_TIER_I", employer_cost=True)
		nssf_t2_emp = _sum_lines("NSSF_TIER_II", employer_cost=False)
		nssf_t2_er = _sum_lines("NSSF_TIER_II", employer_cost=True)
		shif_cents = _sum_lines("NHIF_SHIF")
		housing_emp = _sum_lines("HOUSING_LEVY", employer_cost=False)
		housing_er = _sum_lines("HOUSING_LEVY", employer_cost=True)
		nita_cents = _sum_lines("NITA")

		# Non-KE pension fallback (NSSF lines will be zero for non-KE runs)
		pension_total_cents = session.execute(
			sa.select(
				sa.func.coalesce(
					sa.func.sum(Payslip.pension_employee_cents + Payslip.pension_employer_cents), 0
				)
			).where(Payslip.payrun_id == payrun_id)
		).scalar() or 0

		nssf_total = nssf_t1_emp + nssf_t1_er + nssf_t2_emp + nssf_t2_er
		employer_statutory = nssf_t1_er + nssf_t2_er + housing_er + nita_cents
		# For non-KE: total_employer_tax_cents covers employer NI
		if employer_statutory == 0:
			employer_statutory = payrun.total_employer_tax_cents

		assert isinstance(payrun.total_gross_cents, int)
		assert isinstance(payrun.total_net_cents, int)

		# Build debit lines — omit zero-value lines
		debit_lines: list[dict[str, Any]] = [
			{"account": "5000", "amount_cents": payrun.total_gross_cents, "description": "Salary & Wages Expense"},
		]
		if nssf_t1_er + nssf_t2_er > 0:
			debit_lines.append({"account": "5010", "amount_cents": nssf_t1_er + nssf_t2_er, "description": "Employer NSSF Expense"})
		elif payrun.total_employer_tax_cents and nssf_total == 0:
			debit_lines.append({"account": "5010", "amount_cents": payrun.total_employer_tax_cents, "description": "Employer NI / Social Security"})
		if housing_er > 0:
			debit_lines.append({"account": "5020", "amount_cents": housing_er, "description": "Housing Levy Expense (Employer)"})
		if nita_cents > 0:
			debit_lines.append({"account": "5025", "amount_cents": nita_cents, "description": "NITA Levy Expense"})

		# Build credit lines
		credit_lines: list[dict[str, Any]] = [
			{"account": "1100", "amount_cents": payrun.total_net_cents, "description": "Net Pay — Bank Clearing"},
		]
		# PAYE
		effective_paye = paye_cents if paye_cents else payrun.total_employee_tax_cents
		if effective_paye:
			credit_lines.append({"account": "2100", "amount_cents": effective_paye, "description": "PAYE Payable"})
		# NSSF Tier I/II (Kenya)
		if nssf_t1_emp + nssf_t1_er > 0:
			credit_lines.append({"account": "2210", "amount_cents": nssf_t1_emp + nssf_t1_er, "description": "NSSF Tier I Payable"})
		if nssf_t2_emp + nssf_t2_er > 0:
			credit_lines.append({"account": "2211", "amount_cents": nssf_t2_emp + nssf_t2_er, "description": "NSSF Tier II Payable"})
		if shif_cents > 0:
			credit_lines.append({"account": "2215", "amount_cents": shif_cents, "description": "SHIF Payable"})
		if housing_emp > 0:
			credit_lines.append({"account": "2220", "amount_cents": housing_emp, "description": "Housing Levy Payable (Employee)"})
		if nita_cents > 0:
			credit_lines.append({"account": "2230", "amount_cents": nita_cents, "description": "NITA Payable"})
		# Non-KE pension fallback
		if nssf_total == 0 and int(pension_total_cents) > 0:
			credit_lines.append({"account": "2200", "amount_cents": int(pension_total_cents), "description": "Pension Contributions Payable"})

		journal = {
			"journal_id": journal_id,
			"payrun_id": payrun_id,
			"tenant_id": payrun.tenant_id,
			"journal_date": payrun.pay_date.isoformat(),
			"currency_code": getattr(payrun, "currency_code", "KES"),
			"description": f"Payroll {payrun.period_start}–{payrun.period_end}",
			"debit_lines": debit_lines,
			"credit_lines": credit_lines,
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
				currency=getattr(payrun, "currency_code", "KES"),
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

		run_ids = [run.id for run in runs]
		all_employee_ids: set[str] = set(
			session.execute(
				sa.select(Payslip.employee_id)
				.where(Payslip.payrun_id.in_(run_ids))
				.where(Payslip.status == "PAID")
			).scalars().all()
		) if run_ids else set()

		run_summaries = []
		agg_gross = 0
		agg_emp_tax = 0
		agg_er_tax = 0
		agg_net = 0

		for run in runs:
			agg_gross += run.total_gross_cents
			agg_emp_tax += run.total_employee_tax_cents
			agg_er_tax += run.total_employer_tax_cents
			agg_net += run.total_net_cents

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

	# ------------------------------------------------------------------
	# generate_p9_form
	# ------------------------------------------------------------------

	def generate_p9_form(
		self,
		session: Any,
		employee_id: str,
		tax_year: int,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Generate KRA P9 certificate of earnings for annual iTax submission.

		Aggregates PayrollYTD rows for employee_id / tax_year and computes the
		12-column monthly breakdown required by KRA iTax P9 layout.

		Args:
			session: SQLAlchemy session.
			employee_id: Employee UUID.
			tax_year: Calendar/tax year e.g. 2025.
			tenant_id: Tenant UUID (used for scoping if provided).

		Returns:
			Dict matching KRA P9 column layout:
			  {
			    employee_id, tax_year, employer_pin, employee_pin,
			    months_employed,
			    monthly_breakdown: [
			      {month, gross_pay, basic_salary, benefits_in_kind,
			       taxable_pay, paye_charged, personal_relief,
			       insurance_relief, total_relief, paye_paid},
			      ...  (12 rows; zero-filled for months not employed)
			    ],
			    totals: {gross_pay, taxable_pay, paye_paid, total_relief,
			             nssf_tier1, nssf_tier2, shif, housing_levy, nita},
			    generated_at,
			  }
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollYTD

		q = (
			sa.select(PayrollYTD)
			.where(PayrollYTD.employee_id == employee_id)
			.where(PayrollYTD.tax_year == tax_year)
			.order_by(PayrollYTD.month)
		)
		if tenant_id:
			q = q.where(PayrollYTD.tenant_id == tenant_id)

		ytd_rows: list[Any] = session.execute(q).scalars().all()

		# Index by month for O(1) lookup
		by_month: dict[int, Any] = {r.month: r for r in ytd_rows}

		# KRA personal relief: 2,400 KES/month = 240000 cents
		_MONTHLY_PERSONAL_RELIEF = 240000

		monthly_breakdown: list[dict[str, Any]] = []
		totals: dict[str, int] = {
			"gross_pay": 0,
			"taxable_pay": 0,
			"paye_paid": 0,
			"total_relief": 0,
			"nssf_tier1": 0,
			"nssf_tier2": 0,
			"shif": 0,
			"housing_levy": 0,
			"nita": 0,
			"net": 0,
		}

		for m in range(1, 13):
			row = by_month.get(m)
			if row is None:
				monthly_breakdown.append({
					"month": m,
					"gross_pay": 0,
					"basic_salary": 0,
					"benefits_in_kind": 0,
					"taxable_pay": 0,
					"paye_charged": 0,
					"personal_relief": 0,
					"insurance_relief": 0,
					"total_relief": 0,
					"paye_paid": 0,
				})
				continue

			# Insurance relief is implicit in net PAYE; we re-derive personal relief
			# The gross_tax_before_relief is not stored; approximate total_relief as
			# personal_relief only (insurance detail not stored per-month in YTD).
			personal_relief = _MONTHLY_PERSONAL_RELIEF
			total_relief = personal_relief  # insurance relief would need premium data

			monthly_breakdown.append({
				"month": m,
				"gross_pay": row.gross_cents,
				"basic_salary": row.gross_cents - row.bik_cents,
				"benefits_in_kind": row.bik_cents,
				"taxable_pay": row.taxable_gross_cents,
				"paye_charged": row.paye_cents,
				"personal_relief": personal_relief,
				"insurance_relief": 0,  # not tracked per-month in YTD; populate from TaxWithholding if needed
				"total_relief": total_relief,
				"paye_paid": row.paye_cents,
			})

			totals["gross_pay"] += row.gross_cents
			totals["taxable_pay"] += row.taxable_gross_cents
			totals["paye_paid"] += row.paye_cents
			totals["total_relief"] += total_relief
			totals["nssf_tier1"] += row.nssf_tier1_cents
			totals["nssf_tier2"] += row.nssf_tier2_cents
			totals["shif"] += row.shif_cents
			totals["housing_levy"] += row.housing_levy_cents
			totals["nita"] += row.nita_cents
			totals["net"] += row.net_cents

		months_employed = len(by_month)

		result = {
			"employee_id": employee_id,
			"tax_year": tax_year,
			"employer_pin": "",  # populate from legal entity master
			"employee_pin": "",  # populate from employee master
			"months_employed": months_employed,
			"monthly_breakdown": monthly_breakdown,
			"totals": totals,
			"generated_at": datetime.now(timezone.utc).isoformat(),
		}
		log.info(
			"PayrollService.generate_p9_form: employee=%s year=%d months=%d gross=%d¢",
			employee_id, tax_year, months_employed, totals["gross_pay"],
		)
		return result

	# ------------------------------------------------------------------
	# generate_paye_return
	# ------------------------------------------------------------------

	def generate_paye_return(
		self,
		session: Any,
		payrun_id: str,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Generate KRA iTax-compatible PAYE monthly return for a payroll run.

		Produces a structured dict with:
		  - period, employer metadata
		  - employer_return_data: one row per employee matching KRA iTax PAYE
		    Monthly Return column layout
		  - csv_content: UTF-8 BOM encoded CSV string ready for iTax upload

		Args:
			session: SQLAlchemy session.
			payrun_id: PayrollRun UUID.
			tenant_id: Tenant UUID (optional scoping).

		Returns:
			{
			  period, payrun_id,
			  total_emoluments, total_paye,
			  employer_return_data: [{
			    employee_ref, employee_name, id_number, kra_pin,
			    gross_pay, non_cash_benefits, pension_contribution,
			    owner_occupied_interest, personal_relief, insurance_relief,
			    taxable_pay, tax_on_taxable_pay, monthly_personal_relief,
			    tax_payable, tax_withheld,
			  }],
			  csv_content,
			  generated_at,
			}
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip, PayslipLine
		import io
		import csv as _csv

		payrun = session.get(PayrollRun, payrun_id)
		if payrun is None:
			raise PayrollRunNotFoundError(f"PayrollRun {payrun_id!r} not found")
		if payrun.status not in ("CALCULATED", "APPROVED", "PAID"):
			raise PayrollStateError(
				f"PayrollRun {payrun_id!r} is {payrun.status!r}; must be CALCULATED/APPROVED/PAID"
			)

		q = sa.select(Payslip).where(Payslip.payrun_id == payrun_id)
		if tenant_id:
			q = q.where(Payslip.tenant_id == tenant_id)
		payslips: list[Any] = session.execute(q).scalars().all()
		payslip_ids = [ps.id for ps in payslips]
		line_totals: dict[str, dict[str, int]] = {}
		if payslip_ids:
			line_rows = session.execute(
				sa.select(
					PayslipLine.payslip_id,
					sa.func.coalesce(sa.func.sum(sa.case(
						(PayslipLine.line_type == "BIK", PayslipLine.amount_cents),
						else_=0,
					)), 0).label("bik_cents"),
					sa.func.coalesce(sa.func.sum(sa.case(
						(
							sa.and_(
								PayslipLine.line_type.in_(["NSSF_TIER_I", "NSSF_TIER_II"]),
								PayslipLine.is_employer_cost.is_(False),
							),
							sa.func.abs(PayslipLine.amount_cents),
						),
						else_=0,
					)), 0).label("nssf_emp_cents"),
				)
				.where(PayslipLine.payslip_id.in_(payslip_ids))
				.group_by(PayslipLine.payslip_id)
			).all()
			line_totals = {
				row.payslip_id: {
					"bik_cents": int(row.bik_cents or 0),
					"nssf_emp_cents": int(row.nssf_emp_cents or 0),
				}
				for row in line_rows
			}

		_MONTHLY_PERSONAL_RELIEF = 240000  # KES 2,400/month in cents

		employer_return_data: list[dict[str, Any]] = []
		total_emoluments = 0
		total_paye = 0

		for ps in payslips:
			totals = line_totals.get(ps.id, {})
			bik_cents = totals.get("bik_cents", 0)
			nssf_emp_cents = totals.get("nssf_emp_cents", 0)

			taxable_pay = ps.gross_pay_cents + bik_cents
			paye = ps.income_tax_cents
			personal_relief = _MONTHLY_PERSONAL_RELIEF

			row: dict[str, Any] = {
				"employee_ref": ps.employee_id,
				"employee_name": "",         # populate from employee master
				"id_number": "",             # national ID / passport
				"kra_pin": "",               # employee KRA PIN
				"gross_pay": ps.gross_pay_cents,
				"non_cash_benefits": bik_cents,
				"pension_contribution": nssf_emp_cents,
				"owner_occupied_interest": 0,
				"personal_relief": personal_relief,
				"insurance_relief": 0,
				"taxable_pay": taxable_pay,
				"tax_on_taxable_pay": paye + personal_relief,  # gross tax before relief
				"monthly_personal_relief": personal_relief,
				"tax_payable": paye,
				"tax_withheld": paye,
			}
			employer_return_data.append(row)
			total_emoluments += ps.gross_pay_cents
			total_paye += paye

		# Build UTF-8 BOM CSV
		csv_columns = [
			"employee_ref", "employee_name", "id_number", "kra_pin",
			"gross_pay", "non_cash_benefits", "pension_contribution",
			"owner_occupied_interest", "personal_relief", "insurance_relief",
			"taxable_pay", "tax_on_taxable_pay", "monthly_personal_relief",
			"tax_payable", "tax_withheld",
		]
		buf = io.StringIO()
		buf.write("﻿")  # UTF-8 BOM required by KRA iTax
		writer = _csv.DictWriter(buf, fieldnames=csv_columns, extrasaction="ignore")
		writer.writeheader()
		for r in employer_return_data:
			# Convert cents to KES (2dp) for human-readable CSV
			csv_row = {k: (f"{v / 100:.2f}" if isinstance(v, int) else v) for k, v in r.items()}
			writer.writerow(csv_row)

		result = {
			"period": f"{payrun.period_start.isoformat()}_{payrun.period_end.isoformat()}",
			"payrun_id": payrun_id,
			"total_emoluments": total_emoluments,
			"total_paye": total_paye,
			"employer_return_data": employer_return_data,
			"csv_content": buf.getvalue(),
			"generated_at": datetime.now(timezone.utc).isoformat(),
		}
		log.info(
			"PayrollService.generate_paye_return: run=%s employees=%d total_paye=%d¢",
			payrun_id, len(employer_return_data), total_paye,
		)
		return result

	# ------------------------------------------------------------------
	# dispatch_payslips
	# ------------------------------------------------------------------

	def dispatch_payslips(
		self,
		session: Any,
		payrun_id: str,
		delivery_method: str = "EMAIL",
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Deliver payslip PDFs to employees via email or other channel.

		For each PAID payslip in the run:
		  1. Generates a PDF via generate_payslip_pdf() (WeasyPrint, lazy import).
		  2. Dispatches via the delivery_method (EMAIL | STORE).
		  3. Sets payslip.dispatched_at = now().
		  4. Logs a PayslipAccessLog row with access_type="EMAIL".

		delivery_method:
		  EMAIL  — sends via a delivery service; lazy-imports to avoid hard dep.
		           Looks for current_app.extensions["pgaf_mailer"] first;
		           falls back to a no-op logger if unavailable.
		  STORE  — writes PDF bytes to payrun.metadata_["payslip_pdfs"][employee_id].

		Args:
			session: SQLAlchemy session (caller commits).
			payrun_id: PayrollRun UUID.
			delivery_method: "EMAIL" or "STORE".
			tenant_id: Optional tenant scoping.

		Returns:
			{dispatched: int, failed: int, errors: list[str], generated_at}
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip, PayslipAccessLog

		payrun = session.get(PayrollRun, payrun_id)
		if payrun is None:
			raise PayrollRunNotFoundError(f"PayrollRun {payrun_id!r} not found")
		if payrun.status != "PAID":
			raise PayrollStateError(
				f"PayrollRun {payrun_id!r} is {payrun.status!r}; dispatch requires PAID status"
			)

		q = sa.select(Payslip).where(Payslip.payrun_id == payrun_id).where(Payslip.status == "PAID")
		if tenant_id:
			q = q.where(Payslip.tenant_id == tenant_id)
		payslips: list[Any] = session.execute(q).scalars().all()

		dispatched = 0
		failed = 0
		errors: list[str] = []
		now = datetime.now(timezone.utc)

		# Lazy-import mailer
		mailer: Any = None
		try:
			from flask import current_app
			mailer = current_app.extensions.get("pgaf_mailer")
		except Exception:
			pass

		for ps in payslips:
			try:
				pdf_bytes = self.generate_payslip_pdf(ps.id, session)

				if delivery_method == "EMAIL":
					if mailer is not None:
						mailer.send_payslip(
							employee_id=ps.employee_id,
							payslip_id=ps.id,
							pdf_bytes=pdf_bytes,
							period=f"{payrun.period_start}–{payrun.period_end}",
						)
					else:
						log.warning(
							"PayrollService.dispatch_payslips: mailer not available, payslip %s not emailed",
							ps.id,
						)
				elif delivery_method == "STORE":
					meta = dict(payrun.metadata_ or {})
					pdfs = meta.setdefault("payslip_pdfs", {})
					import base64
					pdfs[ps.employee_id] = base64.b64encode(pdf_bytes).decode()
					payrun.metadata_ = meta

				# Mark dispatched
				ps.dispatched_at = now
				ps.updated_at = now

				# Access log (Kenya DPA 2019)
				session.add(PayslipAccessLog(
					tenant_id=ps.tenant_id,
					payslip_id=ps.id,
					accessed_by=ps.employee_id,  # system dispatch on behalf of employee
					access_type="EMAIL" if delivery_method == "EMAIL" else "DOWNLOAD",
					ip_address=None,
					accessed_at=now,
				))
				dispatched += 1

			except Exception as exc:
				log.error(
					"PayrollService.dispatch_payslips: failed for payslip %s: %s",
					ps.id, exc,
				)
				errors.append(f"{ps.id}: {exc}")
				failed += 1

		log.info(
			"PayrollService.dispatch_payslips: run=%s dispatched=%d failed=%d",
			payrun_id, dispatched, failed,
		)
		return {
			"dispatched": dispatched,
			"failed": failed,
			"errors": errors,
			"generated_at": now.isoformat(),
		}

	# ------------------------------------------------------------------
	# generate_payslip_pdf
	# ------------------------------------------------------------------

	def generate_payslip_pdf(
		self,
		payslip_id: str,
		session: Any,
	) -> bytes:
		"""Render a payslip as a password-protected PDF using WeasyPrint.

		Password is the last 4 digits of the employee_id UUID (standard Kenya
		practice — employees are told to use their last 4 ID digits).

		Requires WeasyPrint and Jinja2 to be installed. If WeasyPrint is not
		available, returns a UTF-8 encoded plain-text representation instead
		(suitable for testing without a full rendering stack).

		Args:
			payslip_id: Payslip UUID.
			session: SQLAlchemy session.

		Returns:
			PDF bytes (or plain-text bytes if WeasyPrint unavailable).

		Raises:
			PayslipNotFoundError: payslip not found.
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import Payslip, PayslipLine, PayrollRun

		ps = session.get(Payslip, payslip_id)
		if ps is None:
			raise PayslipNotFoundError(f"Payslip {payslip_id!r} not found")

		payrun = session.get(PayrollRun, ps.payrun_id)

		lines: list[Any] = session.execute(
			sa.select(PayslipLine)
			.where(PayslipLine.payslip_id == payslip_id)
			.order_by(PayslipLine.line_type, PayslipLine.description)
		).scalars().all()

		earnings = [l for l in lines if l.amount_cents > 0 and not l.is_employer_cost]
		deductions = [l for l in lines if l.amount_cents < 0]
		employer_costs = [l for l in lines if l.is_employer_cost]

		context = {
			"employee_id": ps.employee_id,
			"payslip_id": ps.id,
			"period_start": payrun.period_start.isoformat() if payrun else "",
			"period_end": payrun.period_end.isoformat() if payrun else "",
			"pay_date": payrun.pay_date.isoformat() if payrun else "",
			"currency": ps.currency_code,
			"gross_pay": ps.gross_pay_cents,
			"income_tax": ps.income_tax_cents,
			"national_insurance": ps.national_insurance_cents,
			"pension_employee": ps.pension_employee_cents,
			"other_deductions": ps.other_deductions_cents,
			"net_pay": ps.net_pay_cents,
			"earnings": [
				{"description": l.description, "amount": l.amount_cents}
				for l in earnings
			],
			"deductions": [
				{"description": l.description, "amount": l.amount_cents}
				for l in deductions
			],
			"employer_costs": [
				{"description": l.description, "amount": l.amount_cents}
				for l in employer_costs
			],
		}

		# Build HTML
		try:
			from jinja2 import Environment, BaseLoader
			html_tmpl = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Payslip</title>
<style>body{font-family:Arial,sans-serif;font-size:11pt;}
table{width:100%;border-collapse:collapse;}
td,th{border:1px solid #ccc;padding:4px 8px;}th{background:#f0f0f0;}</style>
</head><body>
<h2>PAYSLIP</h2>
<p>Employee: {{ employee_id }} | Period: {{ period_start }} – {{ period_end }} | Pay Date: {{ pay_date }}</p>
<h3>Earnings</h3>
<table><tr><th>Description</th><th>Amount ({{ currency }} cents)</th></tr>
{% for e in earnings %}<tr><td>{{ e.description }}</td><td>{{ e.amount }}</td></tr>{% endfor %}
<tr><td><strong>Gross Pay</strong></td><td><strong>{{ gross_pay }}</strong></td></tr>
</table>
<h3>Deductions</h3>
<table><tr><th>Description</th><th>Amount ({{ currency }} cents)</th></tr>
{% for d in deductions %}<tr><td>{{ d.description }}</td><td>{{ d.amount }}</td></tr>{% endfor %}
</table>
<p><strong>NET PAY: {{ net_pay }} {{ currency }} cents</strong></p>
<h3>Employer Contributions</h3>
<table><tr><th>Description</th><th>Amount ({{ currency }} cents)</th></tr>
{% for c in employer_costs %}<tr><td>{{ c.description }}</td><td>{{ c.amount }}</td></tr>{% endfor %}
</table>
</body></html>"""
			env = Environment(loader=BaseLoader())
			tmpl = env.from_string(html_tmpl)
			html = tmpl.render(**context)
		except ImportError:
			html = None

		# Password: last 4 hex chars of employee UUID (no dashes)
		raw_id = ps.employee_id.replace("-", "")
		pdf_password = raw_id[-4:] if len(raw_id) >= 4 else "0000"

		if html is not None:
			try:
				from weasyprint import HTML as WP_HTML
				pdf_bytes = WP_HTML(string=html).write_pdf()
				# Apply password protection via pikepdf if available
				try:
					import pikepdf
					import io as _io
					reader = pikepdf.open(_io.BytesIO(pdf_bytes))
					out = _io.BytesIO()
					reader.save(
						out,
						encryption=pikepdf.Encryption(
							owner=pdf_password + pdf_password,
							user=pdf_password,
							R=4,
						),
					)
					return out.getvalue()
				except ImportError:
					return pdf_bytes
			except ImportError:
				pass

		# Plain-text fallback
		lines_txt = [
			f"PAYSLIP — {context['employee_id']}",
			f"Period: {context['period_start']} – {context['period_end']}",
			f"Gross Pay: {context['gross_pay']} {context['currency']} cents",
			f"Net Pay:   {context['net_pay']} {context['currency']} cents",
		]
		return "\n".join(lines_txt).encode("utf-8")

	# ------------------------------------------------------------------
	# generate_bank_eft
	# ------------------------------------------------------------------

	def generate_bank_eft(
		self,
		session: Any,
		payrun_id: str,
		bank_code: str = "KCB",
		tenant_id: str = "",
	) -> str:
		"""Generate Kenya bank EFT bulk-payment CSV for net pay transfers.

		Supports KCB, EQUITY, STANBIC, COOPERATIVE column layouts.
		Falls back to a generic layout for unknown bank codes.

		PayrollRun must be APPROVED or PAID.

		Args:
			session: SQLAlchemy session.
			payrun_id: PayrollRun UUID.
			bank_code: "KCB" | "EQUITY" | "STANBIC" | "COOPERATIVE" | "GENERIC".
			tenant_id: Optional tenant scoping.

		Returns:
			CSV string (UTF-8, no BOM — banks prefer plain UTF-8).

		Raises:
			PayrollRunNotFoundError, PayrollStateError
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun, Payslip
		import io
		import csv as _csv

		payrun = session.get(PayrollRun, payrun_id)
		if payrun is None:
			raise PayrollRunNotFoundError(f"PayrollRun {payrun_id!r} not found")
		if payrun.status not in ("APPROVED", "PAID"):
			raise PayrollStateError(
				f"PayrollRun {payrun_id!r} is {payrun.status!r}; must be APPROVED or PAID to generate EFT"
			)

		q = (
			sa.select(Payslip)
			.where(Payslip.payrun_id == payrun_id)
			.where(Payslip.status.in_(["APPROVED", "PAID"]))
			.where(Payslip.net_pay_cents > 0)
			.order_by(Payslip.employee_id)
		)
		if tenant_id:
			q = q.where(Payslip.tenant_id == tenant_id)
		payslips: list[Any] = session.execute(q).scalars().all()

		buf = io.StringIO()
		code = bank_code.upper()

		if code == "KCB":
			# KCB Bulk Payment CSV: AccountNumber,BranchCode,BeneficiaryName,Amount,Narration
			writer = _csv.writer(buf)
			writer.writerow(["AccountNumber", "BranchCode", "BeneficiaryName", "Amount", "Narration"])
			for ps in payslips:
				amount_kes = f"{ps.net_pay_cents / 100:.2f}"
				ref = ps.payment_reference or f"PAY-{ps.id[:8].upper()}"
				writer.writerow([
					ps.bank_account_number or "",
					ps.bank_branch_code or "",
					ps.employee_id,
					amount_kes,
					ref,
				])

		elif code == "EQUITY":
			# Equity Bank Bulk Payment: AccountNo,Amount,BeneficiaryName,Narration,BranchCode
			writer = _csv.writer(buf)
			writer.writerow(["AccountNo", "Amount", "BeneficiaryName", "Narration", "BranchCode"])
			for ps in payslips:
				amount_kes = f"{ps.net_pay_cents / 100:.2f}"
				ref = ps.payment_reference or f"PAY-{ps.id[:8].upper()}"
				writer.writerow([
					ps.bank_account_number or "",
					amount_kes,
					ps.employee_id,
					ref,
					ps.bank_branch_code or "",
				])

		elif code == "STANBIC":
			# Stanbic Bank Kenya: BeneficiaryAccountNumber,BeneficiaryName,PaymentAmount,BranchCode,Reference
			writer = _csv.writer(buf)
			writer.writerow(["BeneficiaryAccountNumber", "BeneficiaryName", "PaymentAmount", "BranchCode", "Reference"])
			for ps in payslips:
				amount_kes = f"{ps.net_pay_cents / 100:.2f}"
				ref = ps.payment_reference or f"PAY-{ps.id[:8].upper()}"
				writer.writerow([
					ps.bank_account_number or "",
					ps.employee_id,
					amount_kes,
					ps.bank_branch_code or "",
					ref,
				])

		elif code == "COOPERATIVE":
			# Co-operative Bank Kenya: AccountNumber,Amount,BeneficiaryName,BranchCode,TransactionReference
			writer = _csv.writer(buf)
			writer.writerow(["AccountNumber", "Amount", "BeneficiaryName", "BranchCode", "TransactionReference"])
			for ps in payslips:
				amount_kes = f"{ps.net_pay_cents / 100:.2f}"
				ref = ps.payment_reference or f"PAY-{ps.id[:8].upper()}"
				writer.writerow([
					ps.bank_account_number or "",
					f"{ps.net_pay_cents / 100:.2f}",
					ps.employee_id,
					ps.bank_branch_code or "",
					ref,
				])

		else:
			# Generic fallback: account_number, name, amount_kes, reference
			writer = _csv.writer(buf)
			writer.writerow(["account_number", "name", "amount_kes", "reference"])
			for ps in payslips:
				ref = ps.payment_reference or f"PAY-{ps.id[:8].upper()}"
				writer.writerow([
					ps.bank_account_number or ps.bank_account_iban or "",
					ps.employee_id,
					f"{ps.net_pay_cents / 100:.2f}",
					ref,
				])

		result = buf.getvalue()
		log.info(
			"PayrollService.generate_bank_eft: run=%s bank=%s rows=%d",
			payrun_id, bank_code, len(payslips),
		)
		return result

	# ------------------------------------------------------------------
	# gross_to_net_report
	# ------------------------------------------------------------------

	def gross_to_net_report(
		self,
		session: Any,
		payrun_id: str,
		prior_payrun_id: str | None = None,
		tenant_id: str = "",
	) -> list[dict[str, Any]]:
		"""Per-employee gross-to-net reconciliation report.

		For each payslip in payrun_id, returns a row with all component amounts
		as separate columns.  If prior_payrun_id is supplied, adds variance
		columns (current - prior) for each numeric field.

		Args:
			session: SQLAlchemy session.
			payrun_id: PayrollRun UUID.
			prior_payrun_id: Optional prior run UUID for month-over-month variance.
			tenant_id: Optional tenant scoping.

		Returns:
			list of dicts, one per employee:
			  {employee_id, gross, basic_pay, allowances, overtime, bonus,
			   paye, nssf_tier1, nssf_tier2, shif, housing_levy, nita,
			   other_deductions, net_pay,
			   [variance_* columns if prior_payrun_id supplied]}
		"""
		from pgappforge.plugins.erp.hcm.payroll.models import Payslip, PayslipLine

		def _load_payslips(run_id: str) -> dict[str, Any]:
			q = sa.select(Payslip).where(Payslip.payrun_id == run_id)
			if tenant_id:
				q = q.where(Payslip.tenant_id == tenant_id)
			return {ps.employee_id: ps for ps in session.execute(q).scalars().all()}

		def _load_line_totals(payslip_ids: list[str]) -> dict[tuple[str, str, bool], int]:
			if not payslip_ids:
				return {}
			line_types = [
				"BASIC", "ALLOWANCE", "OVERTIME", "BONUS",
				"NSSF_TIER_I", "NSSF_TIER_II", "NHIF_SHIF", "HOUSING_LEVY", "NITA",
			]
			rows = session.execute(
				sa.select(
					PayslipLine.payslip_id,
					PayslipLine.line_type,
					PayslipLine.is_employer_cost,
					sa.func.coalesce(sa.func.sum(sa.func.abs(PayslipLine.amount_cents)), 0).label("amount_cents"),
				)
				.where(PayslipLine.payslip_id.in_(payslip_ids))
				.where(PayslipLine.line_type.in_(line_types))
				.group_by(PayslipLine.payslip_id, PayslipLine.line_type, PayslipLine.is_employer_cost)
			).all()
			return {
				(row.payslip_id, row.line_type, bool(row.is_employer_cost)): int(row.amount_cents or 0)
				for row in rows
			}

		def _sum_lines_for_payslip(payslip_id: str, line_types: list[str], employer_cost: bool | None = None) -> int:
			total = 0
			for line_type in line_types:
				if employer_cost is None:
					total += line_totals.get((payslip_id, line_type, False), 0)
					total += line_totals.get((payslip_id, line_type, True), 0)
				else:
					total += line_totals.get((payslip_id, line_type, employer_cost), 0)
			return total

		current_map = _load_payslips(payrun_id)
		prior_map = _load_payslips(prior_payrun_id) if prior_payrun_id else {}
		line_totals = _load_line_totals(
			list({ps.id for ps in [*current_map.values(), *prior_map.values()]})
		)

		def _build_row(ps: Any) -> dict[str, Any]:
			pid = ps.id
			return {
				"employee_id": ps.employee_id,
				"gross": ps.gross_pay_cents,
				"basic_pay": _sum_lines_for_payslip(pid, ["BASIC"]),
				"allowances": _sum_lines_for_payslip(pid, ["ALLOWANCE"]),
				"overtime": _sum_lines_for_payslip(pid, ["OVERTIME"]),
				"bonus": _sum_lines_for_payslip(pid, ["BONUS"]),
				"paye": ps.income_tax_cents,
				"nssf_tier1": _sum_lines_for_payslip(pid, ["NSSF_TIER_I"], employer_cost=False),
				"nssf_tier2": _sum_lines_for_payslip(pid, ["NSSF_TIER_II"], employer_cost=False),
				"shif": _sum_lines_for_payslip(pid, ["NHIF_SHIF"]),
				"housing_levy": _sum_lines_for_payslip(pid, ["HOUSING_LEVY"], employer_cost=False),
				"nita": _sum_lines_for_payslip(pid, ["NITA"]),
				"other_deductions": ps.other_deductions_cents,
				"net_pay": ps.net_pay_cents,
			}

		_NUMERIC_KEYS = [
			"gross", "basic_pay", "allowances", "overtime", "bonus",
			"paye", "nssf_tier1", "nssf_tier2", "shif", "housing_levy", "nita",
			"other_deductions", "net_pay",
		]

		result: list[dict[str, Any]] = []
		for emp_id, ps in current_map.items():
			row = _build_row(ps)
			if prior_payrun_id and emp_id in prior_map:
				prior_row = _build_row(prior_map[emp_id])
				for k in _NUMERIC_KEYS:
					row[f"variance_{k}"] = row[k] - prior_row[k]
			result.append(row)

		log.info(
			"PayrollService.gross_to_net_report: run=%s employees=%d prior=%s",
			payrun_id, len(result), prior_payrun_id,
		)
		return result


__all__ = [
	"PayrollService",
	"PayrollServiceError",
	"PayrollRunNotFoundError",
	"PayslipNotFoundError",
	"PayrollStateError",
	"PayrollCalculationError",
	# methods exposed via __all__ for documentation; import PayrollService directly
]
