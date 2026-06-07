"""
pgappforge/plugins/erp/hcm/payroll/assembly.py

PayrollAssemblyService — orchestrates the HCM data collection step before
calculate_payrun().

Responsibilities
----------------
For each employee in the payrun's entity, this service:
  1. Loads the employee's active compensation package and allowances from
     CompensationService, translating them into payroll ``earnings`` lines.
  2. Loads pending BenefitDeduction rows for the payrun period and translates
     them into payroll ``deductions`` lines.
  3. Loads APPROVED CommissionPayout rows (variable pay) and adds them as
     commission earnings lines.
  4. Returns a list of ``employee_data`` dicts in the exact format expected
     by PayrollService.calculate_payrun().

All monetary amounts are BigInteger cents — never float.
All arithmetic uses Decimal with ROUND_HALF_UP.

Usage
-----
::

    from pgappforge.plugins.erp.hcm.payroll.assembly import PayrollAssemblyService

    assembler = PayrollAssemblyService()
    employee_data = assembler.assemble(
        payrun_id=run.id,
        entity_id=run.entity_id,
        period_start=run.period_start,
        period_end=run.period_end,
        tenant_id=run.tenant_id,
        session=session,
    )
    payroll_svc.calculate_payrun(run.id, session, employee_data=employee_data)
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

log = logging.getLogger(__name__)


class PayrollAssemblyError(Exception):
	"""Base error for payroll assembly failures."""


class PayrollAssemblyService:
	"""Stateless service that collects HCM module data into the employee_data
	format required by PayrollService.calculate_payrun().

	Each method accepts an explicit SQLAlchemy session so callers control
	transaction boundaries.
	"""

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def assemble(
		self,
		payrun_id: str,
		entity_id: str,
		period_start: date,
		period_end: date,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Build the full employee_data list for a payrun.

		Pre-loads BenefitDeduction and CommissionPayout rows for ALL employees
		in two bulk queries (avoiding N+1 per-employee queries). CompensationService
		is still called per-employee since it performs inline arithmetic.

		Returns:
		    List of employee_data dicts ready for PayrollService.calculate_payrun().
		"""
		import sqlalchemy as sa

		employee_rows = self._load_employee_ids(entity_id, tenant_id, session, sa)
		emp_ids = [r[0] for r in employee_rows]
		log.info(
			"PayrollAssemblyService.assemble: payrun=%s entity=%s employees=%d",
			payrun_id, entity_id, len(emp_ids),
		)
		if not emp_ids:
			return []

		period_str = period_start.strftime("%Y-%m")

		# Pre-load BenefitDeduction rows for ALL employees in one query
		benefit_map: dict[str, list[Any]] = {e: [] for e in emp_ids}
		try:
			from pgappforge.plugins.erp.hcm.benefits.models import BenefitDeduction  # type: ignore[import]
			bd_rows = session.execute(
				sa.select(BenefitDeduction).where(
					BenefitDeduction.tenant_id == tenant_id,
					BenefitDeduction.employee_id.in_(emp_ids),
					BenefitDeduction.period == period_str,
					BenefitDeduction.status.in_(["PENDING"]),
				)
			).scalars().all()
			for bd in bd_rows:
				benefit_map.setdefault(bd.employee_id, []).append(bd)
		except ImportError:
			log.debug("PayrollAssemblyService: benefits plugin not loaded")
		except Exception as exc:
			log.warning("PayrollAssemblyService: bulk benefits query failed: %s", exc)

		# Pre-load CommissionPayout rows for ALL employees in one query
		commission_map: dict[str, list[Any]] = {e: [] for e in emp_ids}
		try:
			from pgappforge.plugins.erp.hcm.variable_pay.models import CommissionPayout  # type: ignore[import]
			cp_rows = session.execute(
				sa.select(CommissionPayout).where(
					CommissionPayout.employee_id.in_(emp_ids),
					CommissionPayout.status == "APPROVED",
					CommissionPayout.period == period_str,
				)
			).scalars().all()
			for cp in cp_rows:
				commission_map.setdefault(cp.employee_id, []).append(cp)
		except ImportError:
			log.debug("PayrollAssemblyService: variable_pay plugin not loaded")
		except Exception as exc:
			log.warning("PayrollAssemblyService: bulk commission query failed: %s", exc)

		result: list[dict] = []
		for emp_id, bank_iban, currency_code in employee_rows:
			try:
				emp_data = self._build_employee_data(
					employee_id=emp_id,
					bank_account_iban=bank_iban or "",
					currency_code=currency_code or "KES",
					as_of_date=period_start,
					period_start=period_start,
					period_end=period_end,
					tenant_id=tenant_id,
					session=session,
					benefit_deductions=benefit_map.get(emp_id, []),
					commission_payouts=commission_map.get(emp_id, []),
				)
				result.append(emp_data)
			except Exception as exc:
				log.warning(
					"PayrollAssemblyService: skipping employee %s due to error: %s",
					emp_id, exc,
				)
		return result

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _load_employee_ids(
		self,
		entity_id: str,
		tenant_id: str,
		session: Any,
		sa: Any,
	) -> list[tuple[str, str | None, str | None]]:
		"""Return [(employee_id, bank_iban, currency_code)] for entity."""
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import Employee  # type: ignore[import]
			rows = session.execute(
				sa.select(
					Employee.id,
					Employee.bank_account_iban if hasattr(Employee, "bank_account_iban") else sa.literal(None),
					Employee.currency_code if hasattr(Employee, "currency_code") else sa.literal("KES"),
				)
				.where(
					Employee.tenant_id == tenant_id,
					Employee.entity_id == entity_id,
					Employee.employment_status == "ACTIVE",
				)
			).all()
			return [(str(r[0]), r[1], r[2]) for r in rows]
		except ImportError:
			log.debug("PayrollAssemblyService: personnel plugin not loaded")
			return []
		except Exception as exc:
			log.warning("PayrollAssemblyService._load_employee_ids failed: %s", exc)
			return []

	def _build_employee_data(
		self,
		employee_id: str,
		bank_account_iban: str,
		currency_code: str,
		as_of_date: date,
		period_start: date,
		period_end: date,
		tenant_id: str,
		session: Any,
		*,
		benefit_deductions: list[Any] | None = None,
		commission_payouts: list[Any] | None = None,
	) -> dict:
		"""Assemble the employee_data dict for one employee.

		employee_data format (matches PayrollService.calculate_payrun expectation):
		  {
		    employee_id, bank_account_iban, currency_code, payment_reference,
		    earnings: [{line_type, description, units, rate_cents, amount_cents,
		                gl_account, cost_center}],
		    deductions: [{line_type, description, amount_cents}],
		    other_deductions_cents: int,
		    tax_withholding_override_cents: int,
		  }
		"""
		earnings: list[dict] = []
		deductions: list[dict] = []
		other_deductions_cents = 0

		# ── 1. Compensation — base salary + allowances ──────────────────
		try:
			from pgappforge.plugins.erp.hcm.compensation.services import CompensationService
			comp_svc = CompensationService()
			total_pkg = comp_svc.compute_total_package(
				employee_id, as_of_date, tenant_id, session
			)
			base = int(total_pkg.get("base_salary_cents", 0))
			if base > 0:
				earnings.append({
					"line_type": "BASIC_SALARY",
					"description": "Basic Salary",
					"units": "MONTH",
					"rate_cents": base,
					"amount_cents": base,
					"gl_account": "5100",  # Salary expense
					"cost_center": "",
				})
			for alw in total_pkg.get("allowances", []):
				alw_cents = int(alw.get("amount_cents", 0))
				if alw_cents > 0:
					earnings.append({
						"line_type": "ALLOWANCE",
						"description": alw.get("name", "Allowance"),
						"units": "MONTH",
						"rate_cents": alw_cents,
						"amount_cents": alw_cents,
						"gl_account": "5110",  # Allowances expense
						"cost_center": "",
					})
			for ded in total_pkg.get("deductions", []):
				ded_cents = int(ded.get("amount_cents", 0))
				if ded_cents > 0:
					deductions.append({
						"line_type": "DEDUCTION",
						"description": ded.get("name", "Deduction"),
						"amount_cents": ded_cents,
					})
		except ImportError:
			log.debug("PayrollAssemblyService: compensation plugin not loaded for %s", employee_id)
		except Exception as exc:
			log.warning("PayrollAssemblyService: compensation failed for %s: %s", employee_id, exc)

		# ── 2. Benefits — pending deductions for this period ────────────
		# benefit_deductions pre-loaded by assemble(); fallback to per-employee query
		if benefit_deductions is not None:
			bd_list = benefit_deductions
		else:
			bd_list = []
			try:
				import sqlalchemy as sa
				from pgappforge.plugins.erp.hcm.benefits.models import BenefitDeduction  # type: ignore[import]
				bd_list = session.execute(
					sa.select(BenefitDeduction).where(
						BenefitDeduction.tenant_id == tenant_id,
						BenefitDeduction.employee_id == employee_id,
						BenefitDeduction.period == period_start.strftime("%Y-%m"),
						BenefitDeduction.status.in_(["PENDING"]),
					)
				).scalars().all()
			except ImportError:
				log.debug("PayrollAssemblyService: benefits plugin not loaded for %s", employee_id)
			except Exception as exc:
				log.warning("PayrollAssemblyService: benefits failed for %s: %s", employee_id, exc)
		for bd in bd_list:
			emp_ded = int(bd.employee_deduction_cents)
			if emp_ded > 0:
				deductions.append({
					"line_type": "BENEFIT_DEDUCTION",
					"description": f"Benefit deduction {bd.id[:8]}",
					"amount_cents": emp_ded,
				})

		# ── 3. Variable Pay — approved commission payouts ───────────────
		# commission_payouts pre-loaded by assemble(); fallback to per-employee query
		if commission_payouts is not None:
			cp_list = commission_payouts
		else:
			cp_list = []
			try:
				import sqlalchemy as sa
				from pgappforge.plugins.erp.hcm.variable_pay.models import CommissionPayout  # type: ignore[import]
				cp_list = session.execute(
					sa.select(CommissionPayout).where(
						CommissionPayout.employee_id == employee_id,
						CommissionPayout.status == "APPROVED",
						CommissionPayout.period == period_start.strftime("%Y-%m"),
					)
				).scalars().all()
			except ImportError:
				log.debug("PayrollAssemblyService: variable_pay plugin not loaded for %s", employee_id)
			except Exception as exc:
				log.warning("PayrollAssemblyService: variable_pay failed for %s: %s", employee_id, exc)
		for payout in cp_list:
			payout_cents = int(payout.amount_cents)
			if payout_cents > 0:
				earnings.append({
					"line_type": "COMMISSION",
					"description": f"Commission payout {payout.id[:8]}",
					"units": "PERIOD",
					"rate_cents": payout_cents,
					"amount_cents": payout_cents,
					"gl_account": "5120",
					"cost_center": "",
				})

		return {
			"employee_id": employee_id,
			"bank_account_iban": bank_account_iban,
			"currency_code": currency_code,
			"payment_reference": f"PAY-{employee_id[:8]}",
			"earnings": earnings,
			"deductions": deductions,
			"other_deductions_cents": other_deductions_cents,
			"tax_withholding_override_cents": 0,
		}


__all__ = ["PayrollAssemblyService", "PayrollAssemblyError"]
