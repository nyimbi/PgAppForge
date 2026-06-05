"""
BPM Action Registry — platform-wide capability registrations.

This module wires every major service operation into the BPMActionRegistry so
that workflow step on_enter/on_exit blocks can invoke them by name:

    {"type": "call_capability",
     "capability": "fintech.core_banking.deposit",
     "params": {"account_number": "$account_number",
                "amount_cents": "$amount_cents",
                "channel": "WORKFLOW",
                "reference": "$workflow_id"}}

Import ordering: this module is imported by pgappforge/plugins/__init__.py via
a guarded try/except so missing optional plugins never block startup.

Adding new registrations
------------------------
1. Pick a dotted name following the existing hierarchy (domain.subdomain.verb).
2. Decorate a function with @BPMActionRegistry.register("the.name", "Short description").
3. Lazy-import the service inside the function body; wrap in try/except ImportError
   so the registration still exists even if the plugin is not installed.
4. Accept (record_ctx, session, **kwargs) — callers resolve $field references before
   the call, so kwargs contain plain values.
5. Return {"status": "ok", ...} or {"status": "error", "message": "..."}.
"""

from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


# ── Fintech — Core Banking ───────────────────────────────────────────────────

@BPMActionRegistry.register("fintech.core_banking.deposit", "Post a cash/cheque deposit")
def _cb_deposit(
	record_ctx: dict,
	session: Any,
	account_number: str = "",
	amount_cents: int = 0,
	channel: str = "WORKFLOW",
	reference: str = "",
	narrative: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
	except ImportError:
		return {"status": "error", "message": "core_banking plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = CoreBankingService()
		result = svc.deposit(
			session,
			account_number=account_number,
			amount_cents=amount_cents,
			channel=channel,
			reference=reference,
			narrative=narrative,
			tenant_id=tenant_id,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm cb.deposit failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.core_banking.withdraw", "Post a withdrawal from an account")
def _cb_withdraw(
	record_ctx: dict,
	session: Any,
	account_number: str = "",
	amount_cents: int = 0,
	channel: str = "WORKFLOW",
	reference: str = "",
	narrative: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
	except ImportError:
		return {"status": "error", "message": "core_banking plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = CoreBankingService()
		result = svc.withdraw(
			session,
			account_number=account_number,
			amount_cents=amount_cents,
			channel=channel,
			reference=reference,
			narrative=narrative,
			tenant_id=tenant_id,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm cb.withdraw failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.core_banking.transfer", "Atomic intra-bank transfer")
def _cb_transfer(
	record_ctx: dict,
	session: Any,
	from_account_number: str = "",
	to_account_number: str = "",
	amount_cents: int = 0,
	reference: str = "",
	narrative: str | None = None,
	exchange_rate: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
	except ImportError:
		return {"status": "error", "message": "core_banking plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		from decimal import Decimal
		svc = CoreBankingService()
		result = svc.transfer(
			session,
			from_account_number=from_account_number,
			to_account_number=to_account_number,
			amount_cents=amount_cents,
			reference=reference,
			narrative=narrative,
			exchange_rate=Decimal(exchange_rate) if exchange_rate else None,
			tenant_id=tenant_id,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm cb.transfer failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.core_banking.place_hold", "Place a hold on available balance")
def _cb_place_hold(
	record_ctx: dict,
	session: Any,
	account_number: str = "",
	amount_cents: int = 0,
	reason: str = "",
	reference: str = "",
	expires_at: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
	except ImportError:
		return {"status": "error", "message": "core_banking plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		from datetime import datetime, timezone
		svc = CoreBankingService()
		exp = datetime.fromisoformat(expires_at) if expires_at else None
		hold = svc.place_hold(
			session,
			account_number=account_number,
			amount_cents=amount_cents,
			reason=reason,
			reference=reference,
			expires_at=exp,
			tenant_id=tenant_id,
		)
		return {"status": "ok", "hold_id": hold.id, "amount_cents": hold.amount_cents}
	except Exception as exc:
		log.warning("bpm cb.place_hold failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.core_banking.release_hold", "Release an active balance hold")
def _cb_release_hold(
	record_ctx: dict,
	session: Any,
	hold_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
	except ImportError:
		return {"status": "error", "message": "core_banking plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = CoreBankingService()
		hold = svc.release_hold(session, hold_id=hold_id, tenant_id=tenant_id)
		return {"status": "ok", "hold_id": hold.id, "released_amount_cents": hold.amount_cents}
	except Exception as exc:
		log.warning("bpm cb.release_hold failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.core_banking.freeze_account", "Freeze an account (ACTIVE→FROZEN)")
def _cb_freeze_account(
	record_ctx: dict,
	session: Any,
	account_number: str = "",
	reason: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
	except ImportError:
		return {"status": "error", "message": "core_banking plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = CoreBankingService()
		account = svc.freeze_account(
			session,
			account_number=account_number,
			reason=reason,
			tenant_id=tenant_id,
		)
		return {"status": "ok", "account_number": account.account_number, "account_status": account.status}
	except Exception as exc:
		log.warning("bpm cb.freeze_account failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── Fintech — Lending ────────────────────────────────────────────────────────

@BPMActionRegistry.register("fintech.lending.approve_application", "Record final loan approval decision")
def _ln_approve(
	record_ctx: dict,
	session: Any,
	application_id: str = "",
	approver_id: str = "",
	approved_amount_cents: int = 0,
	approved_tenor_months: int = 0,
	approved_rate_pa: str = "0",
	conditions: list | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.lending.services import LoanOriginationService
	except ImportError:
		return {"status": "error", "message": "lending plugin not installed"}
	try:
		from decimal import Decimal
		svc = LoanOriginationService()
		app = svc.approve(
			session,
			application_id=application_id,
			approver_id=approver_id,
			approved_amount_cents=approved_amount_cents,
			approved_tenor_months=approved_tenor_months,
			approved_rate_pa=Decimal(approved_rate_pa),
			conditions=conditions,
		)
		return {"status": "ok", "application_id": app.id, "loan_status": app.status}
	except Exception as exc:
		log.warning("bpm ln.approve failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.lending.reject_application", "Record loan rejection decision")
def _ln_reject(
	record_ctx: dict,
	session: Any,
	application_id: str = "",
	reason: str = "",
	decision_by: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.lending.services import LoanOriginationService
	except ImportError:
		return {"status": "error", "message": "lending plugin not installed"}
	try:
		svc = LoanOriginationService()
		app = svc.reject(session, application_id=application_id, reason=reason, decision_by=decision_by)
		return {"status": "ok", "application_id": app.id, "loan_status": app.status}
	except Exception as exc:
		log.warning("bpm ln.reject failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.lending.disburse_loan", "Disburse an approved loan")
def _ln_disburse(
	record_ctx: dict,
	session: Any,
	application_id: str = "",
	disbursement_account_id: str = "",
	disbursement_date: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.lending.services import LoanOriginationService
	except ImportError:
		return {"status": "error", "message": "lending plugin not installed"}
	try:
		from datetime import date
		svc = LoanOriginationService()
		dis_date = date.fromisoformat(disbursement_date) if disbursement_date else None
		loan = svc.disburse(
			session,
			application_id=application_id,
			disbursement_account_id=disbursement_account_id,
			disbursement_date=dis_date,
		)
		return {"status": "ok", "loan_id": loan.id, "loan_number": loan.loan_number}
	except Exception as exc:
		log.warning("bpm ln.disburse failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.lending.apply_repayment", "Apply a repayment (penalty→interest→principal)")
def _ln_repayment(
	record_ctx: dict,
	session: Any,
	loan_id: str = "",
	amount_cents: int = 0,
	source: str = "WORKFLOW",
	reference: str | None = None,
	payment_date: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.lending.services import LoanManagementService
	except ImportError:
		return {"status": "error", "message": "lending plugin not installed"}
	try:
		from datetime import date
		svc = LoanManagementService()
		pay_date = date.fromisoformat(payment_date) if payment_date else None
		result = svc.apply_repayment(
			session,
			loan_id=loan_id,
			amount_cents=amount_cents,
			source=source,
			reference=reference,
			payment_date=pay_date,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm ln.apply_repayment failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.lending.write_off", "Write off a non-performing loan")
def _ln_write_off(
	record_ctx: dict,
	session: Any,
	loan_id: str = "",
	reason: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.lending.services import LoanManagementService
	except ImportError:
		return {"status": "error", "message": "lending plugin not installed"}
	try:
		svc = LoanManagementService()
		loan = svc.write_off(session, loan_id=loan_id, reason=reason)
		return {"status": "ok", "loan_id": loan.id, "loan_status": loan.status}
	except Exception as exc:
		log.warning("bpm ln.write_off failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── Fintech — Payments ───────────────────────────────────────────────────────

@BPMActionRegistry.register("fintech.payments.validate_payment", "Run sanctions+AML pre-check on a payment order")
def _pay_validate(
	record_ctx: dict,
	session: Any,
	payment_order_id: str = "",
	actor_id: str = "system",
	skip_sanctions: bool = False,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.payments.services import PaymentsService
	except ImportError:
		return {"status": "error", "message": "payments plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = PaymentsService(session=session, tenant_id=tenant_id)
		order = svc.validate_payment(
			payment_order_id,
			actor_id=actor_id,
			skip_sanctions=skip_sanctions,
		)
		return {"status": "ok", "payment_order_id": str(order.id), "order_status": order.status}
	except Exception as exc:
		log.warning("bpm pay.validate failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.payments.cancel_payment", "Cancel a PENDING or VALIDATED payment order")
def _pay_cancel(
	record_ctx: dict,
	session: Any,
	payment_order_id: str = "",
	cancelled_by: str = "system",
	cancellation_reason: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.payments.services import PaymentsService
	except ImportError:
		return {"status": "error", "message": "payments plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = PaymentsService(session=session, tenant_id=tenant_id)
		order = svc.cancel_payment(
			payment_order_id,
			cancelled_by=cancelled_by,
			cancellation_reason=cancellation_reason,
		)
		return {"status": "ok", "payment_order_id": str(order.id), "order_status": order.status}
	except Exception as exc:
		log.warning("bpm pay.cancel failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("fintech.payments.return_payment", "Process a bank-to-bank return of a settled payment")
def _pay_return(
	record_ctx: dict,
	session: Any,
	payment_order_id: str = "",
	return_reason_code: str = "",
	return_reason: str = "",
	actor_id: str = "system",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.payments.services import PaymentsService
	except ImportError:
		return {"status": "error", "message": "payments plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = PaymentsService(session=session, tenant_id=tenant_id)
		order = svc.return_payment(
			payment_order_id,
			return_reason_code=return_reason_code,
			return_reason=return_reason,
			actor_id=actor_id,
		)
		return {"status": "ok", "payment_order_id": str(order.id), "order_status": order.status}
	except Exception as exc:
		log.warning("bpm pay.return failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── ERP Finance — Accounts Payable ──────────────────────────────────────────

@BPMActionRegistry.register("erp.finance.ap.approve_invoice", "Record an AP invoice approval decision")
def _ap_approve_invoice(
	record_ctx: dict,
	session: Any,
	invoice_id: str = "",
	approver_id: str = "",
	comments: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.finance.ap.services import APService
	except ImportError:
		return {"status": "error", "message": "erp.finance.ap plugin not installed"}
	try:
		svc = APService()
		invoice = svc.approve_invoice(
			invoice_id=invoice_id,
			approver_id=approver_id,
			session=session,
			comments=comments,
		)
		return {"status": "ok", "invoice_id": invoice.id, "invoice_status": invoice.status}
	except Exception as exc:
		log.warning("bpm ap.approve_invoice failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("erp.finance.ap.pay_invoice", "Create a payment run for approved AP invoices")
def _ap_pay_invoice(
	record_ctx: dict,
	session: Any,
	supplier_ids: list | None = None,
	value_date: str = "",
	bank_account: str = "",
	bic: str = "",
	currency_code: str = "USD",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.finance.ap.services import APService
	except ImportError:
		return {"status": "error", "message": "erp.finance.ap plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		from datetime import date
		svc = APService()
		vdate = date.fromisoformat(value_date) if value_date else date.today()
		run = svc.create_payment_run(
			supplier_ids=supplier_ids or [],
			value_date=vdate,
			session=session,
			tenant_id=tenant_id,
			bank_account=bank_account,
			bic=bic,
			currency_code=currency_code,
		)
		return {"status": "ok", "payment_run_id": run.id, "run_status": run.status}
	except Exception as exc:
		log.warning("bpm ap.pay_invoice failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── ERP Finance — General Ledger ─────────────────────────────────────────────

@BPMActionRegistry.register("erp.finance.gl.post_journal", "Create and immediately post a balanced GL journal")
def _gl_post_journal(
	record_ctx: dict,
	session: Any,
	lines: list | None = None,
	description: str = "",
	source_doc_id: str = "",
	source_doc_type: str = "BPM_ACTION",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.finance.gl.services import GLService
	except ImportError:
		return {"status": "error", "message": "erp.finance.gl plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = GLService()
		journal_id = svc.post_simple_journal(
			lines=lines or [],
			session=session,
			tenant_id=tenant_id,
			description=description,
			source_doc_id=source_doc_id,
			source_doc_type=source_doc_type,
		)
		return {"status": "ok", "journal_id": journal_id}
	except Exception as exc:
		log.warning("bpm gl.post_journal failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── ERP HCM — Personnel ──────────────────────────────────────────────────────

@BPMActionRegistry.register("hcm.personnel.start_probation", "Hire an employee and begin probation period")
def _hcm_start_probation(
	record_ctx: dict,
	session: Any,
	tenant_id: str = "",
	entity_id: str = "",
	start_date: str = "",
	probation_end_date: str | None = None,
	employment_type: str = "FULL_TIME",
	**kw: Any,
) -> dict:
	"""Maps to PersonnelService.hire_employee() which creates the employee in
	ACTIVE status with probation_end_date set — i.e. the employee commences
	probation at the point of hire."""
	try:
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService
	except ImportError:
		return {"status": "error", "message": "hcm.personnel plugin not installed"}
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		data: dict[str, Any] = {
			"tenant_id": _tenant_id,
			"entity_id": entity_id or record_ctx.get("entity_id", ""),
			"start_date": start_date,
			"employment_type": employment_type,
			"probation_end_date": probation_end_date,
			**{k: v for k, v in kw.items() if k not in ("record_ctx", "session")},
		}
		svc = PersonnelService()
		employee = svc.hire_employee(data=data, session=session)
		return {"status": "ok", "employee_id": employee.id, "employee_number": employee.employee_number}
	except Exception as exc:
		log.warning("bpm hcm.start_probation failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("hcm.personnel.confirm_employment", "Record probation outcome and confirm/extend/fail")
def _hcm_confirm_employment(
	record_ctx: dict,
	session: Any,
	employee_id: str = "",
	confirmed: bool = True,
	extension_days: int | None = None,
	confirmed_date: str | None = None,
	notes: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService
	except ImportError:
		return {"status": "error", "message": "hcm.personnel plugin not installed"}
	try:
		data: dict[str, Any] = {
			"confirmed": confirmed,
			"notes": notes,
		}
		if extension_days is not None:
			data["extension_days"] = extension_days
		if confirmed_date:
			data["confirmed_date"] = confirmed_date
		svc = PersonnelService()
		employee = svc.confirm_probation(employee_id=employee_id, data=data, session=session)
		return {"status": "ok", "employee_id": employee.id, "employment_status": employee.employment_status}
	except Exception as exc:
		log.warning("bpm hcm.confirm_employment failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("hcm.personnel.terminate_employee", "Terminate an employee engagement")
def _hcm_terminate(
	record_ctx: dict,
	session: Any,
	employee_id: str = "",
	termination_type: str = "VOLUNTARY",
	termination_reason: str = "",
	termination_date: str | None = None,
	rehire_eligible: bool = True,
	notice_waived: bool = False,
	notice_waiver_reason: str = "",
	disciplinary_bypass_reason: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService
	except ImportError:
		return {"status": "error", "message": "hcm.personnel plugin not installed"}
	try:
		data: dict[str, Any] = {
			"termination_type": termination_type,
			"termination_reason": termination_reason,
			"rehire_eligible": rehire_eligible,
			"notice_waived": notice_waived,
		}
		if termination_date:
			data["termination_date"] = termination_date
		if notice_waiver_reason:
			data["notice_waiver_reason"] = notice_waiver_reason
		if disciplinary_bypass_reason:
			data["disciplinary_bypass_reason"] = disciplinary_bypass_reason
		svc = PersonnelService()
		employee = svc.terminate_employee(employee_id=employee_id, data=data, session=session)
		return {"status": "ok", "employee_id": employee.id, "employment_status": employee.employment_status}
	except Exception as exc:
		log.warning("bpm hcm.terminate_employee failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("hcm.personnel.create_onboarding_plan", "Create an onboarding plan for a new employee")
def _hcm_onboarding_plan(
	record_ctx: dict,
	session: Any,
	employee_id: str = "",
	checklist_items: list | None = None,
	template_id: str | None = None,
	assigned_buddy_id: str | None = None,
	induction_date: str | None = None,
	target_completion_date: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.hcm.personnel.services import PersonnelService
	except ImportError:
		return {"status": "error", "message": "hcm.personnel plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		data: dict[str, Any] = {
			"tenant_id": tenant_id,
			"checklist_items": checklist_items or [],
		}
		if template_id:
			data["template_id"] = template_id
		if assigned_buddy_id:
			data["assigned_buddy_id"] = assigned_buddy_id
		if induction_date:
			data["induction_date"] = induction_date
		if target_completion_date:
			data["target_completion_date"] = target_completion_date
		svc = PersonnelService()
		plan = svc.create_onboarding_plan(employee_id=employee_id, data=data, session=session)
		return {"status": "ok", "plan_id": plan.id, "employee_id": employee_id}
	except Exception as exc:
		log.warning("bpm hcm.create_onboarding_plan failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── ERP HCM — Payroll ────────────────────────────────────────────────────────

@BPMActionRegistry.register("hcm.payroll.run_payroll", "Calculate gross→net for a PayrollRun")
def _hcm_run_payroll(
	record_ctx: dict,
	session: Any,
	payrun_id: str = "",
	employee_data: list | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.hcm.payroll.services import PayrollService
	except ImportError:
		return {"status": "error", "message": "hcm.payroll plugin not installed"}
	try:
		svc = PayrollService()
		payrun = svc.calculate_payrun(
			payrun_id=payrun_id,
			session=session,
			employee_data=employee_data,
		)
		return {"status": "ok", "payrun_id": payrun.id, "payrun_status": payrun.status}
	except Exception as exc:
		log.warning("bpm hcm.run_payroll failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── ERP CRM — Contracts ──────────────────────────────────────────────────────

@BPMActionRegistry.register(
	"erp.crm.contracts.activate_contract",
	"Activate a contract by recording the final signatory signature",
)
def _clm_activate_contract(
	record_ctx: dict,
	session: Any,
	signature_request_id: str = "",
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	"""Activation flows through CLMService.record_signature(): when all
	required signatories have signed the contract status advances to ACTIVE
	automatically.  Pass the last pending ESignatureRequest id."""
	try:
		from pgappforge.plugins.erp.crm.contracts.services import CLMService
	except ImportError:
		return {"status": "error", "message": "erp.crm.contracts plugin not installed"}
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		contract = CLMService.record_signature(
			session=session,
			signature_request_id=signature_request_id,
			tenant_id=_tenant_id,
		)
		return {
			"status": "ok",
			"contract_id": contract.id if contract else None,
			"contract_status": contract.status if contract else "PENDING_SIGNATURES",
		}
	except Exception as exc:
		log.warning("bpm clm.activate_contract failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("erp.crm.contracts.terminate_contract", "Terminate a contract")
def _clm_terminate_contract(
	record_ctx: dict,
	session: Any,
	contract_id: str = "",
	reason: str = "",
	effective_date: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.crm.contracts.services import CLMService
	except ImportError:
		return {"status": "error", "message": "erp.crm.contracts plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		from datetime import date
		eff = date.fromisoformat(effective_date) if effective_date else date.today()
		contract = CLMService.terminate_contract(
			session=session,
			contract_id=contract_id,
			reason=reason,
			effective_date=eff,
			tenant_id=tenant_id,
		)
		return {"status": "ok", "contract_id": contract.id, "contract_status": contract.status}
	except Exception as exc:
		log.warning("bpm clm.terminate_contract failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── ERP CRM — Sales / Opportunities ─────────────────────────────────────────

@BPMActionRegistry.register("erp.crm.sales.qualify_lead", "Advance an opportunity to a new pipeline stage")
def _crm_qualify_lead(
	record_ctx: dict,
	session: Any,
	opportunity_id: str = "",
	new_stage: str = "QUALIFIED",
	reason: str = "",
	competitor: str = "",
	**kw: Any,
) -> dict:
	"""Maps to SalesService.advance_stage() — 'qualify' is the transition from
	LEAD/PROSPECT to QUALIFIED stage in the pipeline."""
	try:
		from pgappforge.plugins.erp.crm.sales.services import SalesService
	except ImportError:
		return {"status": "error", "message": "erp.crm.sales plugin not installed"}
	try:
		svc = SalesService()
		opp = svc.advance_stage(
			opportunity_id=opportunity_id,
			new_stage=new_stage,
			session=session,
			reason=reason,
			competitor=competitor,
		)
		return {"status": "ok", "opportunity_id": opp.id, "stage": opp.stage}
	except Exception as exc:
		log.warning("bpm crm.qualify_lead failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── ERP Projects ─────────────────────────────────────────────────────────────

@BPMActionRegistry.register("erp.projects.approve_change_order", "Approve a project change order")
def _proj_approve_co(
	record_ctx: dict,
	session: Any,
	co_id: str = "",
	approved_by: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.projects.services import ProjectService
	except ImportError:
		return {"status": "error", "message": "erp.projects plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		co = ProjectService.approve_change_order(
			session=session,
			co_id=co_id,
			approved_by=approved_by,
			tenant_id=tenant_id,
		)
		return {"status": "ok", "change_order_id": co.id, "co_status": co.status}
	except Exception as exc:
		log.warning("bpm proj.approve_change_order failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("erp.projects.log_time", "Log a timesheet entry on a project")
def _proj_log_time(
	record_ctx: dict,
	session: Any,
	employee_id: str = "",
	project_id: str = "",
	wbs_id: str | None = None,
	work_date: str = "",
	hours: str = "0",
	description: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.projects.services import ProjectService
	except ImportError:
		return {"status": "error", "message": "erp.projects plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		from datetime import date
		from decimal import Decimal
		wdate = date.fromisoformat(work_date) if work_date else date.today()
		entry = ProjectService.log_time(
			session=session,
			employee_id=employee_id,
			project_id=project_id,
			wbs_id=wbs_id,
			work_date=wdate,
			hours=Decimal(hours),
			description=description,
			tenant_id=tenant_id,
		)
		return {"status": "ok", "timesheet_id": entry.id, "entry_status": entry.status}
	except Exception as exc:
		log.warning("bpm proj.log_time failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── ERP Operations — SCM ─────────────────────────────────────────────────────

@BPMActionRegistry.register(
	"erp.operations.scm.approve_purchase_order",
	"Approve a purchase requisition (SUBMITTED→APPROVED)",
)
def _scm_approve_po(
	record_ctx: dict,
	session: Any,
	req_id: str = "",
	approver_id: str = "",
	**kw: Any,
) -> dict:
	"""Maps to SCMService.approve_requisition() — the approval step that gates
	conversion from a requisition to a confirmed purchase order."""
	try:
		from pgappforge.plugins.erp.operations.scm.services import SCMService
	except ImportError:
		return {"status": "error", "message": "erp.operations.scm plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = SCMService()
		req = svc.approve_requisition(
			session=session,
			req_id=req_id,
			approver_id=approver_id,
			tenant_id=tenant_id,
		)
		return {"status": "ok", "requisition_id": req.id, "req_status": req.status}
	except Exception as exc:
		log.warning("bpm scm.approve_purchase_order failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ── ERP Operations — Quality ─────────────────────────────────────────────────

@BPMActionRegistry.register("erp.operations.quality.raise_ncr", "Raise a Non-Conformance Report against an inspection lot")
def _qc_raise_ncr(
	record_ctx: dict,
	session: Any,
	lot_id: str = "",
	description: str = "",
	severity: str = "MAJOR",
	raised_by: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.operations.quality.services import QCService
	except ImportError:
		return {"status": "error", "message": "erp.operations.quality plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = QCService()
		ncr = svc.raise_ncr(
			session=session,
			lot_id=lot_id,
			description=description,
			severity=severity,
			raised_by=raised_by,
			tenant_id=tenant_id,
		)
		return {"status": "ok", "ncr_id": ncr.id, "ncr_number": ncr.ncr_number, "severity": ncr.severity}
	except Exception as exc:
		log.warning("bpm qc.raise_ncr failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = ["BPMActionRegistry"]
