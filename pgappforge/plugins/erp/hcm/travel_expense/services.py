"""
pgappforge/plugins/erp/hcm/travel_expense/services.py

ExpenseService — stateless business logic for the HCM Travel & Expense plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

Monetary invariants:
  - All amounts stored and returned as integer cents
  - Decimal arithmetic used internally; results rounded ROUND_HALF_UP to int
  - exchange_rate columns read as Decimal(str(row.exchange_rate)) — never float

Public methods:
  submit_report(session, report_id, tenant_id)                        -> ExpenseReport
  approve_report(session, report_id, approver_id, line_overrides, tenant_id) -> ExpenseReport
  reject_report(session, report_id, approver_id, reason, tenant_id)  -> ExpenseReport
  pay_report(session, report_id, payment_ref, tenant_id)             -> ExpenseReport
  check_policy(session, line_data, employee_grade, tenant_id)        -> dict
  compute_per_diem(session, employee_id, country_code, from_date, to_date, meal_flags, tenant_id) -> dict
  request_advance(session, employee_id, amount_cents, currency_code, trip_purpose, tenant_id) -> CashAdvance
  disburse_advance(session, advance_id, disbursement_ref, tenant_id) -> CashAdvance
  settle_advance(session, advance_id, report_id, tenant_id)          -> dict
  log_mileage(session, employee_id, data, tenant_id)                 -> MileageLog
  get_expense_analytics(session, from_date, to_date, tenant_id)      -> dict
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

class ExpenseServiceError(Exception):
	"""Base domain error for T&E operations."""


class ExpenseReportNotFoundError(ExpenseServiceError):
	pass


class ExpenseLineNotFoundError(ExpenseServiceError):
	pass


class AdvanceNotFoundError(ExpenseServiceError):
	pass


class ExpenseStateError(ExpenseServiceError):
	"""Invalid state transition attempted."""


class ExpensePolicyError(ExpenseServiceError):
	"""Hard policy violation preventing action."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today() -> date:
	return datetime.now(timezone.utc).date()


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _round_cents(d: Decimal) -> int:
	return int(d.to_integral_value(rounding=ROUND_HALF_UP))


def _uuid4() -> str:
	return str(uuid.uuid4())


def _gl_post(entries: list[dict], description: str, session: Any) -> str:
	"""Post GL journal entries; returns journal_id.

	Lazy-imports the GL service to avoid hard circular dependency.
	Falls back gracefully when the GL plugin is not loaded.

	Each entry dict: {account_code: str, debit_cents: int, credit_cents: int,
	                  tenant_id: str, description: str}
	"""
	journal_id = _uuid4()
	try:
		from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore
		GLService.post_journal(
			entries=entries,
			description=description,
			journal_id=journal_id,
			session=session,
		)
	except ImportError:
		log.debug(
			"GL plugin not loaded — skipping journal post for %s (%d entries)",
			description, len(entries),
		)
	return journal_id


# ---------------------------------------------------------------------------
# GL account constants (Chart of Accounts — T&E range)
# ---------------------------------------------------------------------------

_GL_MEALS            = "6400"
_GL_ACCOMMODATION    = "6401"
_GL_TRANSPORT        = "6402"
_GL_MILEAGE          = "6403"
_GL_CONFERENCE       = "6404"
_GL_FUEL             = "6405"
_GL_ENTERTAINMENT    = "6406"
_GL_COMMUNICATION    = "6407"
_GL_OTHER_EXPENSE    = "6499"
_GL_BANK             = "1011"
_GL_ADVANCE_RECV     = "1300"
_GL_ACCOUNTS_PAYABLE = "2000"

_CATEGORY_GL: dict[str, str] = {
	"MEALS":          _GL_MEALS,
	"ACCOMMODATION":  _GL_ACCOMMODATION,
	"TRANSPORT":      _GL_TRANSPORT,
	"MILEAGE":        _GL_MILEAGE,
	"CONFERENCE":     _GL_CONFERENCE,
	"FUEL":           _GL_FUEL,
	"ENTERTAINMENT":  _GL_ENTERTAINMENT,
	"COMMUNICATION":  _GL_COMMUNICATION,
	"OTHER":          _GL_OTHER_EXPENSE,
}


# ---------------------------------------------------------------------------
# ExpenseService
# ---------------------------------------------------------------------------

class ExpenseService:
	"""Stateless service — all methods are classmethods; no instance state."""

	# ------------------------------------------------------------------
	# 1. submit_report
	# ------------------------------------------------------------------

	@classmethod
	def submit_report(
		cls,
		session: Any,
		report_id: str,
		tenant_id: str,
	):
		"""Validate lines, run policy check per line, compute reimbursement.

		Transitions: DRAFT → SUBMITTED

		Steps:
		 1. Load report + lines; assert DRAFT status.
		 2. Recompute total_claimed_cents from lines (base_amount_cents sum).
		 3. Per-line policy check — mark policy_breach + breach_reason.
		 4. reimbursement_due = total_claimed - advance_received.
		 5. Set status=SUBMITTED, submitted_at=now().
		 6. Emit ExpenseReportSubmittedEvent.

		Returns the mutated ExpenseReport (caller owns flush/commit).
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import (
			ExpenseReport, ExpenseLine,
		)
		from pgappforge.plugins.erp.hcm.travel_expense.events import (
			ExpenseReportSubmittedEvent, PolicyBreachFlaggedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		report: ExpenseReport | None = session.execute(
			sa.select(ExpenseReport).where(
				ExpenseReport.id == report_id,
				ExpenseReport.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if report is None:
			raise ExpenseReportNotFoundError(f"ExpenseReport {report_id!r} not found")

		if report.status != "DRAFT":
			raise ExpenseStateError(
				f"Cannot submit report in status {report.status!r}; must be DRAFT"
			)

		lines: list[ExpenseLine] = session.execute(
			sa.select(ExpenseLine).where(ExpenseLine.report_id == report_id)
		).scalars().all()

		if not lines:
			raise ExpensePolicyError("Cannot submit report with no expense lines")

		# Recompute total from lines — prevents client-side tampering
		total = 0
		breach_count = 0

		# Attempt to resolve employee grade for policy checks (best-effort)
		employee_grade = cls._resolve_employee_grade(session, report.employee_id, tenant_id)

		for line in lines:
			total += line.base_amount_cents

			# Run policy check
			policy_result = cls.check_policy(
				session=session,
				line_data={
					"expense_category": line.expense_category,
					"amount_cents": line.base_amount_cents,
					"expense_date": line.expense_date,
					"receipt_url": line.receipt_url,
				},
				employee_grade=employee_grade,
				tenant_id=tenant_id,
			)

			if not policy_result["compliant"]:
				line.policy_breach = True
				line.breach_reason = policy_result["reason"]
				breach_count += 1
				emit_event(
					PolicyBreachFlaggedEvent(
						aggregate_id=line.id,
						aggregate_type="ExpenseLine",
						tenant_id=tenant_id,
						report_id=report_id,
						line_id=line.id,
						employee_id=str(report.employee_id),
						expense_category=line.expense_category,
						amount_cents=line.base_amount_cents,
						limit_cents=policy_result.get("limit_cents", 0),
						breach_amount_cents=policy_result.get("breach_amount_cents", 0),
						policy_applied=policy_result.get("policy_applied", ""),
						reason=policy_result["reason"],
					),
					session,
				)
			else:
				line.policy_breach = False
				line.breach_reason = None

		report.total_claimed_cents = total
		report.reimbursement_due_cents = total - report.advance_received_cents
		report.status = "SUBMITTED"
		report.submitted_at = _now()

		emit_event(
			ExpenseReportSubmittedEvent(
				aggregate_id=report.id,
				aggregate_type="ExpenseReport",
				tenant_id=tenant_id,
				report_id=report.id,
				employee_id=str(report.employee_id),
				title=report.title,
				destination=report.destination or "",
				trip_start=str(report.trip_start or ""),
				trip_end=str(report.trip_end or ""),
				total_claimed_cents=report.total_claimed_cents,
				advance_received_cents=report.advance_received_cents,
				reimbursement_due_cents=report.reimbursement_due_cents,
				currency_code=report.currency_code,
				line_count=len(lines),
				breach_count=breach_count,
			),
			session,
		)

		log.info(
			"ExpenseReport %s submitted — claimed=%d breach_lines=%d",
			report_id, total, breach_count,
		)
		return report

	# ------------------------------------------------------------------
	# 2. approve_report
	# ------------------------------------------------------------------

	@classmethod
	def approve_report(
		cls,
		session: Any,
		report_id: str,
		approver_id: str,
		line_overrides: dict | None = None,
		tenant_id: str = "",
	):
		"""Approve report; optionally override per-line approved amounts.

		line_overrides: {line_id: approved_amount_cents} — partial override OK.
		Lines without an override default to their full base_amount_cents.
		Transitions: SUBMITTED | UNDER_REVIEW → APPROVED

		Returns mutated ExpenseReport.
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import (
			ExpenseReport, ExpenseLine,
		)
		from pgappforge.plugins.erp.hcm.travel_expense.events import (
			ExpenseReportApprovedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		report: ExpenseReport | None = session.execute(
			sa.select(ExpenseReport).where(
				ExpenseReport.id == report_id,
				ExpenseReport.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if report is None:
			raise ExpenseReportNotFoundError(f"ExpenseReport {report_id!r} not found")

		if report.status not in ("SUBMITTED", "UNDER_REVIEW"):
			raise ExpenseStateError(
				f"Cannot approve report in status {report.status!r}"
			)

		overrides = line_overrides or {}
		lines: list[ExpenseLine] = session.execute(
			sa.select(ExpenseLine).where(ExpenseLine.report_id == report_id)
		).scalars().all()

		total_approved = 0
		bik_cents = 0

		for line in lines:
			if line.id in overrides:
				approved = int(overrides[line.id])
			else:
				approved = line.base_amount_cents
			line.approved_amount_cents = approved
			total_approved += approved
			if line.is_paye_bik:
				bik_cents += approved

		report.total_approved_cents = total_approved
		# Recompute reimbursement against approved (not claimed)
		report.reimbursement_due_cents = total_approved - report.advance_received_cents
		report.status = "APPROVED"
		report.approved_by = approver_id
		report.approved_at = _now()

		emit_event(
			ExpenseReportApprovedEvent(
				aggregate_id=report.id,
				aggregate_type="ExpenseReport",
				tenant_id=tenant_id,
				report_id=report.id,
				employee_id=str(report.employee_id),
				approved_by=approver_id,
				total_approved_cents=total_approved,
				reimbursement_due_cents=report.reimbursement_due_cents,
				currency_code=report.currency_code,
				bik_cents=bik_cents,
			),
			session,
		)

		log.info(
			"ExpenseReport %s approved by %s — approved=%d reimbursement=%d",
			report_id, approver_id, total_approved, report.reimbursement_due_cents,
		)
		return report

	# ------------------------------------------------------------------
	# 3. reject_report
	# ------------------------------------------------------------------

	@classmethod
	def reject_report(
		cls,
		session: Any,
		report_id: str,
		approver_id: str,
		reason: str,
		tenant_id: str,
	):
		"""Reject an expense report, recording reason in metadata.

		Transitions: SUBMITTED | UNDER_REVIEW → REJECTED

		Returns mutated ExpenseReport.
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import ExpenseReport

		report: ExpenseReport | None = session.execute(
			sa.select(ExpenseReport).where(
				ExpenseReport.id == report_id,
				ExpenseReport.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if report is None:
			raise ExpenseReportNotFoundError(f"ExpenseReport {report_id!r} not found")

		if report.status not in ("SUBMITTED", "UNDER_REVIEW", "DRAFT"):
			raise ExpenseStateError(
				f"Cannot reject report in status {report.status!r}"
			)

		report.status = "REJECTED"
		report.approved_by = approver_id
		report.approved_at = _now()
		meta = dict(report.metadata_ or {})
		meta["rejection_reason"] = reason
		meta["rejected_by"] = approver_id
		meta["rejected_at"] = _now().isoformat()
		report.metadata_ = meta

		log.info("ExpenseReport %s rejected by %s — reason: %s", report_id, approver_id, reason)
		return report

	# ------------------------------------------------------------------
	# 4. pay_report
	# ------------------------------------------------------------------

	@classmethod
	def pay_report(
		cls,
		session: Any,
		report_id: str,
		payment_ref: str,
		tenant_id: str,
	):
		"""Disburse reimbursement and post GL entries.

		GL postings per expense category:
		  DR  6400-6499 (expense account by category)
		  CR  1011      (bank / cash)

		If advance outstanding > 0 on linked advance, settle it:
		  DR  2000 (accounts payable)
		  CR  1300 (advance receivable)

		BIK-flagged lines emit BIKFlaggedEvent for payroll ingestion.
		Transitions: APPROVED → PAID

		Returns mutated ExpenseReport.
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import (
			ExpenseReport, ExpenseLine, CashAdvance,
		)
		from pgappforge.plugins.erp.hcm.travel_expense.events import (
			ExpenseReportPaidEvent, BIKFlaggedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		report: ExpenseReport | None = session.execute(
			sa.select(ExpenseReport).where(
				ExpenseReport.id == report_id,
				ExpenseReport.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if report is None:
			raise ExpenseReportNotFoundError(f"ExpenseReport {report_id!r} not found")

		if report.status != "APPROVED":
			raise ExpenseStateError(
				f"Cannot pay report in status {report.status!r}; must be APPROVED"
			)

		lines: list[ExpenseLine] = session.execute(
			sa.select(ExpenseLine).where(ExpenseLine.report_id == report_id)
		).scalars().all()

		# Build GL debit entries by category
		gl_entries: list[dict] = []
		bik_cents = 0
		reimbursement = report.reimbursement_due_cents

		for line in lines:
			approved = line.approved_amount_cents if line.approved_amount_cents is not None else line.base_amount_cents
			account = _CATEGORY_GL.get(line.expense_category, _GL_OTHER_EXPENSE)
			gl_entries.append({
				"account_code": account,
				"debit_cents": approved,
				"credit_cents": 0,
				"tenant_id": tenant_id,
				"description": f"Expense {line.expense_category} — report {report_id[:8]}",
			})
			if line.is_paye_bik:
				bik_cents += approved
				emit_event(
					BIKFlaggedEvent(
						aggregate_id=line.id,
						aggregate_type="ExpenseLine",
						tenant_id=tenant_id,
						report_id=report_id,
						line_id=line.id,
						employee_id=str(report.employee_id),
						bik_amount_cents=approved,
						currency_code=line.currency_code,
						expense_category=line.expense_category,
					),
					session,
				)

		# CR bank for total reimbursement
		if reimbursement > 0:
			gl_entries.append({
				"account_code": _GL_BANK,
				"debit_cents": 0,
				"credit_cents": reimbursement,
				"tenant_id": tenant_id,
				"description": f"Expense reimbursement — report {report_id[:8]}",
			})

		journal_id = _gl_post(
			gl_entries,
			f"Travel & Expense reimbursement — report {report_id[:8]}",
			session,
		)

		# Flush so the advance query sees all pending session state
		session.flush()

		# Settle any linked advance with outstanding balance
		linked_advances: list[CashAdvance] = session.execute(
			sa.select(CashAdvance).where(
				CashAdvance.linked_report_id == report_id,
				CashAdvance.outstanding_cents > 0,
				CashAdvance.tenant_id == tenant_id,
			)
		).scalars().all()

		for advance in linked_advances:
			settle_amount = advance.outstanding_cents
			adv_gl = [
				{
					"account_code": _GL_ACCOUNTS_PAYABLE,
					"debit_cents": settle_amount,
					"credit_cents": 0,
					"tenant_id": tenant_id,
					"description": f"Advance settlement — advance {advance.id[:8]}",
				},
				{
					"account_code": _GL_ADVANCE_RECV,
					"debit_cents": 0,
					"credit_cents": settle_amount,
					"tenant_id": tenant_id,
					"description": f"Advance settlement — advance {advance.id[:8]}",
				},
			]
			_gl_post(adv_gl, f"Advance settlement for report {report_id[:8]}", session)
			advance.outstanding_cents = 0
			advance.status = "SETTLED"

		report.status = "PAID"
		report.paid_at = _now()
		report.payment_ref = payment_ref
		meta = dict(report.metadata_ or {})
		meta["gl_journal_id"] = journal_id
		report.metadata_ = meta

		emit_event(
			ExpenseReportPaidEvent(
				aggregate_id=report.id,
				aggregate_type="ExpenseReport",
				tenant_id=tenant_id,
				report_id=report.id,
				employee_id=str(report.employee_id),
				reimbursement_due_cents=reimbursement,
				payment_ref=payment_ref,
				currency_code=report.currency_code,
				gl_journal_id=journal_id,
				bik_cents=bik_cents,
			),
			session,
		)

		log.info(
			"ExpenseReport %s paid — ref=%s reimbursement=%d bik=%d",
			report_id, payment_ref, reimbursement, bik_cents,
		)
		return report

	# ------------------------------------------------------------------
	# 5. check_policy
	# ------------------------------------------------------------------

	@classmethod
	def check_policy(
		cls,
		session: Any,
		line_data: dict,
		employee_grade: str,
		tenant_id: str,
	) -> dict:
		"""Evaluate expense line against active policies.

		Lookup priority:
		  1. Grade-specific policy for this category
		  2. Catch-all policy (grade_code IS NULL) for this category
		  3. No policy found → compliant by default

		Returns:
		  {
		    compliant: bool,
		    policy_applied: str,   # policy name or "" if none
		    limit_cents: int,      # 0 if no limit
		    breach_amount_cents: int,
		    reason: str,
		  }
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import ExpensePolicy

		category = line_data.get("expense_category", "OTHER")
		amount_cents = int(line_data.get("amount_cents", 0))
		receipt_url = line_data.get("receipt_url")

		# Grade-specific first, then catch-all
		policies: list[ExpensePolicy] = session.execute(
			sa.select(ExpensePolicy).where(
				ExpensePolicy.tenant_id == tenant_id,
				ExpensePolicy.expense_category == category,
				ExpensePolicy.is_active == True,  # noqa: E712
			)
		).scalars().all()

		# Pick grade-specific match first, then catch-all (grade_code IS NULL).
		# Python-side sort avoids NULLS LAST which is unsupported on SQLite.
		policy = None
		for p in policies:
			if p.grade_code == employee_grade:
				policy = p
				break
		if policy is None:
			for p in policies:
				if p.grade_code is None:
					policy = p
					break

		if policy is None:
			return {
				"compliant": True,
				"policy_applied": "",
				"limit_cents": 0,
				"breach_amount_cents": 0,
				"reason": "",
			}

		# Receipt threshold check
		if (
			policy.requires_receipt_above_cents > 0
			and amount_cents > policy.requires_receipt_above_cents
			and not receipt_url
		):
			return {
				"compliant": False,
				"policy_applied": policy.name,
				"limit_cents": policy.requires_receipt_above_cents,
				"breach_amount_cents": amount_cents - policy.requires_receipt_above_cents,
				"reason": (
					f"Receipt required for {category} amounts above "
					f"{policy.requires_receipt_above_cents}c "
					f"(policy: {policy.name!r})"
				),
			}

		# Amount limit check
		if policy.single_limit_cents and amount_cents > policy.single_limit_cents:
			breach = amount_cents - policy.single_limit_cents
			return {
				"compliant": False,
				"policy_applied": policy.name,
				"limit_cents": policy.single_limit_cents,
				"breach_amount_cents": breach,
				"reason": (
					f"{category} amount {amount_cents}c exceeds policy limit "
					f"{policy.single_limit_cents}c by {breach}c "
					f"(policy: {policy.name!r})"
				),
			}

		return {
			"compliant": True,
			"policy_applied": policy.name,
			"limit_cents": policy.single_limit_cents or 0,
			"breach_amount_cents": 0,
			"reason": "",
		}

	# ------------------------------------------------------------------
	# 6. compute_per_diem
	# ------------------------------------------------------------------

	@classmethod
	def compute_per_diem(
		cls,
		session: Any,
		employee_id: str,
		country_code: str,
		from_date: date,
		to_date: date,
		meal_flags: dict,
		tenant_id: str,
	) -> dict:
		"""Compute per diem entitlement for a trip leg.

		meal_flags example:
		  {"breakfast": True, "lunch": True, "dinner": False,
		   "accommodation": True, "incidentals": True}

		Rate lookup: city-level rows override country-level rows.
		If no rate found for a given day, that day's amounts are 0 (logged).

		Returns:
		  {
		    days: int,
		    currency_code: str,
		    per_day_breakdown: [{date, breakfast, lunch, dinner,
		                         accommodation, incidentals, day_total}],
		    total_cents: int,
		  }
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import PerDiemRate

		from datetime import timedelta

		assert from_date <= to_date, "from_date must be <= to_date"

		meal_keys = ["breakfast", "lunch", "dinner", "accommodation", "incidentals"]
		include = {k: meal_flags.get(k, True) for k in meal_keys}

		# Load all potentially applicable rates for the date range
		rates: list[PerDiemRate] = session.execute(
			sa.select(PerDiemRate).where(
				PerDiemRate.tenant_id == tenant_id,
				PerDiemRate.country_code == country_code,
				PerDiemRate.from_date <= to_date,
				sa.or_(
					PerDiemRate.to_date >= from_date,
					PerDiemRate.to_date.is_(None),
				),
			).order_by(
				# city-specific first (not null), then country-wide
				sa.nulls_last(PerDiemRate.city_code.asc()),
				PerDiemRate.from_date.desc(),
			)
		).scalars().all()

		breakdown = []
		total = 0
		currency = "KES"
		current = from_date
		days = (to_date - from_date).days + 1

		while current <= to_date:
			# Pick most-specific applicable rate for this day
			rate = None
			for r in rates:
				r_from = r.from_date
				r_to = r.to_date
				if r_from <= current and (r_to is None or r_to >= current):
					rate = r
					break  # already ordered city-first, date-desc

			if rate is None:
				log.warning(
					"No per diem rate for %s/%s on %s (tenant=%s)",
					country_code, "any", current, tenant_id,
				)
				day_amounts = {k: 0 for k in meal_keys}
			else:
				currency = rate.currency_code
				day_amounts = {
					"breakfast":    rate.breakfast_cents if include["breakfast"] else 0,
					"lunch":        rate.lunch_cents if include["lunch"] else 0,
					"dinner":       rate.dinner_cents if include["dinner"] else 0,
					"accommodation": rate.accommodation_cents if include["accommodation"] else 0,
					"incidentals":  rate.incidentals_cents if include["incidentals"] else 0,
				}

			day_total = sum(day_amounts.values())
			total += day_total
			breakdown.append({"date": str(current), **day_amounts, "day_total": day_total})
			current += timedelta(days=1)

		return {
			"employee_id": employee_id,
			"country_code": country_code,
			"from_date": str(from_date),
			"to_date": str(to_date),
			"days": days,
			"currency_code": currency,
			"meal_flags": include,
			"per_day_breakdown": breakdown,
			"total_cents": total,
		}

	# ------------------------------------------------------------------
	# 7. request_advance
	# ------------------------------------------------------------------

	@classmethod
	def request_advance(
		cls,
		session: Any,
		employee_id: str,
		amount_cents: int,
		currency_code: str,
		trip_purpose: str,
		tenant_id: str,
	):
		"""Create a new CashAdvance in REQUESTED status.

		Returns the persisted CashAdvance (caller owns flush/commit).
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import CashAdvance

		if amount_cents <= 0:
			raise ExpensePolicyError("Advance amount must be positive")

		advance = CashAdvance(
			id=_uuid4(),
			tenant_id=tenant_id,
			employee_id=employee_id,
			request_date=_today(),
			trip_purpose=trip_purpose,
			amount_cents=amount_cents,
			currency_code=currency_code,
			status="REQUESTED",
			outstanding_cents=amount_cents,
		)
		session.add(advance)
		log.info(
			"CashAdvance requested — employee=%s amount=%d %s",
			employee_id, amount_cents, currency_code,
		)
		return advance

	# ------------------------------------------------------------------
	# 8. disburse_advance
	# ------------------------------------------------------------------

	@classmethod
	def disburse_advance(
		cls,
		session: Any,
		advance_id: str,
		disbursement_ref: str,
		tenant_id: str,
	):
		"""Disburse approved advance; post GL DR advance_receivable CR bank.

		GL:
		  DR 1300 (Advance Receivable) — amount_cents
		  CR 1011 (Bank)               — amount_cents

		Transitions: APPROVED → DISBURSED

		Returns mutated CashAdvance.
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import CashAdvance
		from pgappforge.plugins.erp.hcm.travel_expense.events import AdvanceDisbursedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		advance: CashAdvance | None = session.execute(
			sa.select(CashAdvance).where(
				CashAdvance.id == advance_id,
				CashAdvance.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if advance is None:
			raise AdvanceNotFoundError(f"CashAdvance {advance_id!r} not found")

		if advance.status != "APPROVED":
			raise ExpenseStateError(
				f"Cannot disburse advance in status {advance.status!r}; must be APPROVED"
			)

		gl_entries = [
			{
				"account_code": _GL_ADVANCE_RECV,
				"debit_cents": advance.amount_cents,
				"credit_cents": 0,
				"tenant_id": tenant_id,
				"description": f"Cash advance disbursement — advance {advance_id[:8]}",
			},
			{
				"account_code": _GL_BANK,
				"debit_cents": 0,
				"credit_cents": advance.amount_cents,
				"tenant_id": tenant_id,
				"description": f"Cash advance disbursement — advance {advance_id[:8]}",
			},
		]
		journal_id = _gl_post(
			gl_entries,
			f"Cash advance disbursement {advance_id[:8]}",
			session,
		)

		advance.status = "DISBURSED"
		advance.disbursed_at = _now()
		advance.disbursement_ref = disbursement_ref
		advance.outstanding_cents = advance.amount_cents

		emit_event(
			AdvanceDisbursedEvent(
				aggregate_id=advance.id,
				aggregate_type="CashAdvance",
				tenant_id=tenant_id,
				advance_id=advance.id,
				employee_id=str(advance.employee_id),
				amount_cents=advance.amount_cents,
				currency_code=advance.currency_code,
				disbursement_ref=disbursement_ref,
				gl_journal_id=journal_id,
			),
			session,
		)

		log.info(
			"CashAdvance %s disbursed — ref=%s amount=%d",
			advance_id, disbursement_ref, advance.amount_cents,
		)
		return advance

	# ------------------------------------------------------------------
	# 9. settle_advance
	# ------------------------------------------------------------------

	@classmethod
	def settle_advance(
		cls,
		session: Any,
		advance_id: str,
		report_id: str,
		tenant_id: str,
	) -> dict:
		"""Link advance to expense report and reconcile balances.

		Scenarios:
		  A. advance == approved:  outstanding=0, no refund
		  B. advance >  approved:  outstanding>0, employee owes refund
		  C. advance <  approved:  outstanding=0, reimbursement top-up required

		GL for settlement:
		  DR  2000 (AP / Employee Payable)  — advance.amount_cents
		  CR  1300 (Advance Receivable)     — advance.amount_cents

		Returns dict with settlement details.
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import (
			CashAdvance, ExpenseReport,
		)

		advance: CashAdvance | None = session.execute(
			sa.select(CashAdvance).where(
				CashAdvance.id == advance_id,
				CashAdvance.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if advance is None:
			raise AdvanceNotFoundError(f"CashAdvance {advance_id!r} not found")

		if advance.status != "DISBURSED":
			raise ExpenseStateError(
				f"Cannot settle advance in status {advance.status!r}; must be DISBURSED"
			)

		report: ExpenseReport | None = session.execute(
			sa.select(ExpenseReport).where(
				ExpenseReport.id == report_id,
				ExpenseReport.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if report is None:
			raise ExpenseReportNotFoundError(f"ExpenseReport {report_id!r} not found")

		if report.status not in ("APPROVED", "PAID"):
			raise ExpenseStateError(
				f"Cannot settle advance against report in status {report.status!r}"
			)

		approved_total = report.total_approved_cents
		advance_amount = advance.amount_cents
		outstanding = max(0, advance_amount - approved_total)
		refund_due = outstanding > 0
		top_up_due_cents = max(0, approved_total - advance_amount)

		# GL: clear advance receivable against AP
		gl_entries = [
			{
				"account_code": _GL_ACCOUNTS_PAYABLE,
				"debit_cents": advance_amount,
				"credit_cents": 0,
				"tenant_id": tenant_id,
				"description": f"Advance settlement — report {report_id[:8]}",
			},
			{
				"account_code": _GL_ADVANCE_RECV,
				"debit_cents": 0,
				"credit_cents": advance_amount,
				"tenant_id": tenant_id,
				"description": f"Advance settlement — report {report_id[:8]}",
			},
		]
		_gl_post(gl_entries, f"Advance settlement — report {report_id[:8]}", session)

		advance.linked_report_id = report_id
		advance.outstanding_cents = outstanding
		advance.status = "SETTLED" if outstanding == 0 else "DISBURSED"

		# Adjust report's advance_received_cents for accurate reimbursement calc
		report.advance_received_cents = advance_amount
		report.reimbursement_due_cents = approved_total - advance_amount

		result = {
			"advance_id": advance_id,
			"report_id": report_id,
			"advance_amount_cents": advance_amount,
			"approved_total_cents": approved_total,
			"outstanding_cents": outstanding,
			"refund_due": refund_due,
			"refund_cents": outstanding if refund_due else 0,
			"top_up_due_cents": top_up_due_cents,
			"settled": outstanding == 0,
		}

		log.info(
			"CashAdvance %s settled against report %s — outstanding=%d refund=%s",
			advance_id, report_id, outstanding, refund_due,
		)
		return result

	# ------------------------------------------------------------------
	# 10. log_mileage
	# ------------------------------------------------------------------

	@classmethod
	def log_mileage(
		cls,
		session: Any,
		employee_id: str,
		data: dict,
		tenant_id: str,
	):
		"""Create a MileageLog entry; optionally attach to an expense report.

		data keys:
		  log_date: date
		  from_location: str
		  to_location: str
		  purpose: str
		  distance_km: Decimal | float | str
		  rate_per_km_cents: int
		  project_id: str | None
		  report_id: str | None   — if set, also creates MILEAGE ExpenseLine

		total_cents = ROUND_HALF_UP(distance_km × rate_per_km_cents)

		Returns MileageLog.
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import (
			MileageLog, ExpenseLine, ExpenseReport,
		)

		distance = Decimal(str(data["distance_km"]))
		rate = int(data["rate_per_km_cents"])
		total = _round_cents(distance * Decimal(rate))

		ml = MileageLog(
			id=_uuid4(),
			tenant_id=tenant_id,
			employee_id=employee_id,
			log_date=data["log_date"],
			from_location=data["from_location"],
			to_location=data["to_location"],
			purpose=data["purpose"],
			distance_km=distance,
			rate_per_km_cents=rate,
			total_cents=total,
			project_id=data.get("project_id"),
			report_id=data.get("report_id"),
		)
		session.add(ml)

		# If linked to an expense report, auto-create a MILEAGE line
		report_id = data.get("report_id")
		if report_id:
			report: ExpenseReport | None = session.execute(
				sa.select(ExpenseReport).where(
					ExpenseReport.id == report_id,
					ExpenseReport.tenant_id == tenant_id,
				)
			).scalar_one_or_none()

			if report and report.status == "DRAFT":
				line = ExpenseLine(
					id=_uuid4(),
					tenant_id=tenant_id,
					report_id=report_id,
					expense_date=data["log_date"],
					expense_category="MILEAGE",
					description=f"Mileage: {data['from_location']} → {data['to_location']} ({distance} km)",
					amount_cents=total,
					currency_code=report.currency_code,
					exchange_rate=Decimal("1"),
					base_amount_cents=total,
					is_billable_to_client=False,
					project_id=data.get("project_id"),
				)
				session.add(line)
				# Update report total
				report.total_claimed_cents += total

		log.info(
			"MileageLog created — employee=%s distance=%s km total=%d cents",
			employee_id, distance, total,
		)
		return ml

	# ------------------------------------------------------------------
	# 11. get_expense_analytics
	# ------------------------------------------------------------------

	@classmethod
	def get_expense_analytics(
		cls,
		session: Any,
		from_date: date,
		to_date: date,
		tenant_id: str,
	) -> dict:
		"""Aggregate expense analytics for a date range.

		Returns:
		  {
		    period: {from_date, to_date},
		    by_category: {
		      <category>: {
		        total_claimed_cents: int,
		        total_approved_cents: int,
		        line_count: int,
		        breach_count: int,
		        breach_rate: float,   # 0.0–1.0
		      }
		    },
		    top_spenders: [
		      {employee_id, total_claimed_cents, report_count}, ...
		    ],   # top 10
		    summary: {
		      total_reports: int,
		      paid_reports: int,
		      rejected_reports: int,
		      total_claimed_cents: int,
		      total_approved_cents: int,
		      total_advance_disbursed_cents: int,
		      overall_breach_rate: float,
		    }
		  }
		"""
		from pgappforge.plugins.erp.hcm.travel_expense.models import (
			ExpenseReport, ExpenseLine, CashAdvance,
		)

		# --------------- by-category aggregation ---------------
		cat_rows = session.execute(
			sa.select(
				ExpenseLine.expense_category,
				sa.func.sum(ExpenseLine.base_amount_cents).label("total_claimed"),
				sa.func.sum(
					sa.case(
						(ExpenseLine.approved_amount_cents.isnot(None), ExpenseLine.approved_amount_cents),
						else_=ExpenseLine.base_amount_cents,
					)
				).label("total_approved"),
				sa.func.count(ExpenseLine.id).label("line_count"),
				sa.func.sum(
					sa.cast(ExpenseLine.policy_breach, sa.Integer)
				).label("breach_count"),
			)
			.join(ExpenseReport, ExpenseLine.report_id == ExpenseReport.id)
			.where(
				ExpenseLine.tenant_id == tenant_id,
				ExpenseReport.trip_start >= from_date,
				ExpenseReport.trip_start <= to_date,
				ExpenseReport.status.in_(["APPROVED", "PAID"]),
			)
			.group_by(ExpenseLine.expense_category)
		).all()

		by_category: dict[str, dict] = {}
		total_claimed_all = 0
		total_approved_all = 0
		total_lines = 0
		total_breaches = 0

		for row in cat_rows:
			claimed = int(row.total_claimed or 0)
			approved = int(row.total_approved or 0)
			lines_n = int(row.line_count or 0)
			breaches = int(row.breach_count or 0)
			breach_rate = round(breaches / lines_n, 4) if lines_n else 0.0

			by_category[row.expense_category] = {
				"total_claimed_cents": claimed,
				"total_approved_cents": approved,
				"line_count": lines_n,
				"breach_count": breaches,
				"breach_rate": breach_rate,
			}
			total_claimed_all += claimed
			total_approved_all += approved
			total_lines += lines_n
			total_breaches += breaches

		# --------------- top spenders ---------------
		spender_rows = session.execute(
			sa.select(
				ExpenseReport.employee_id,
				sa.func.sum(ExpenseReport.total_claimed_cents).label("total_claimed"),
				sa.func.count(ExpenseReport.id).label("report_count"),
			)
			.where(
				ExpenseReport.tenant_id == tenant_id,
				ExpenseReport.trip_start >= from_date,
				ExpenseReport.trip_start <= to_date,
				ExpenseReport.status.in_(["APPROVED", "PAID"]),
			)
			.group_by(ExpenseReport.employee_id)
			.order_by(sa.desc("total_claimed"))
			.limit(10)
		).all()

		top_spenders = [
			{
				"employee_id": str(row.employee_id),
				"total_claimed_cents": int(row.total_claimed or 0),
				"report_count": int(row.report_count or 0),
			}
			for row in spender_rows
		]

		# --------------- summary counts ---------------
		summary_rows = session.execute(
			sa.select(
				ExpenseReport.status,
				sa.func.count(ExpenseReport.id).label("count"),
			)
			.where(
				ExpenseReport.tenant_id == tenant_id,
				ExpenseReport.trip_start >= from_date,
				ExpenseReport.trip_start <= to_date,
			)
			.group_by(ExpenseReport.status)
		).all()

		status_counts: dict[str, int] = {row.status: int(row.count) for row in summary_rows}
		total_reports = sum(status_counts.values())

		advance_total = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(CashAdvance.amount_cents), 0))
			.where(
				CashAdvance.tenant_id == tenant_id,
				CashAdvance.request_date >= from_date,
				CashAdvance.request_date <= to_date,
				CashAdvance.status.in_(["DISBURSED", "SETTLED"]),
			)
		).scalar() or 0

		overall_breach_rate = round(total_breaches / total_lines, 4) if total_lines else 0.0

		return {
			"period": {"from_date": str(from_date), "to_date": str(to_date)},
			"by_category": by_category,
			"top_spenders": top_spenders,
			"summary": {
				"total_reports": total_reports,
				"paid_reports": status_counts.get("PAID", 0),
				"rejected_reports": status_counts.get("REJECTED", 0),
				"total_claimed_cents": total_claimed_all,
				"total_approved_cents": total_approved_all,
				"total_advance_disbursed_cents": int(advance_total),
				"overall_breach_rate": overall_breach_rate,
			},
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _resolve_employee_grade(session: Any, employee_id: str, tenant_id: str) -> str:
		"""Best-effort lookup of employee grade code for policy matching.

		Falls back to "" (matches catch-all policies only) if the HCM
		employee model is not available or the field is absent.
		"""
		try:
			from pgappforge.plugins.erp.hcm.core.models import Employee  # type: ignore
			emp = session.execute(
				sa.select(Employee).where(
					Employee.id == employee_id,
					Employee.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			return getattr(emp, "grade_code", "") or ""
		except ImportError:
			return ""


__all__ = [
	"ExpenseService",
	"ExpenseServiceError",
	"ExpenseReportNotFoundError",
	"ExpenseLineNotFoundError",
	"AdvanceNotFoundError",
	"ExpenseStateError",
	"ExpensePolicyError",
]
