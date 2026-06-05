"""
pgappforge/plugins/erp/crm/contracts/services.py

CLMService — stateless business logic for the Contract Lifecycle Management plugin.

Key methods
-----------
  create_contract(session, data, tenant_id, template_id=None) -> Contract
  submit_for_review(session, contract_id, submitted_by, tenant_id) -> Contract
  record_approval(session, contract_id, approver_id, decision, comments, tenant_id) -> ContractApproval
  send_for_signature(session, contract_id, signatories, provider, tenant_id) -> list[ESignatureRequest]
  record_signature(session, signature_request_id, tenant_id) -> ESignatureRequest
  create_obligation(session, contract_id, data, tenant_id) -> ContractObligation
  fulfill_obligation(session, obligation_id, notes, tenant_id) -> ContractObligation
  get_overdue_obligations(session, as_of_date, tenant_id) -> list[dict]
  process_renewals(session, as_of_date, tenant_id) -> dict
  terminate_contract(session, contract_id, reason, effective_date, tenant_id) -> Contract
  calculate_lease_schedule(session, contract_id, tenant_id) -> LeaseSchedule
  amortise_rou_asset(session, contract_id, period_date, tenant_id) -> dict
  get_contract_dashboard(session, tenant_id) -> dict
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CLMError(Exception):
	"""Base exception for CLM service layer."""


class ContractNotFoundError(CLMError):
	pass


class ObligationNotFoundError(CLMError):
	pass


class SignatureRequestNotFoundError(CLMError):
	pass


class CLMValidationError(CLMError):
	"""Business rule violation."""


# ---------------------------------------------------------------------------
# Approval role sequence (configurable per-tenant in future)
# ---------------------------------------------------------------------------

_DEFAULT_APPROVAL_SEQUENCE: list[tuple[str, int]] = [
	("LEGAL", 1),
	("FINANCE", 2),
	("COMMERCIAL", 3),
	("EXECUTIVE", 4),
	("COMPLIANCE", 5),
]


# ---------------------------------------------------------------------------
# CLMService
# ---------------------------------------------------------------------------

class CLMService:
	"""Stateless business logic for Contract Lifecycle Management."""

	# ------------------------------------------------------------------
	# 1. create_contract
	# ------------------------------------------------------------------

	@staticmethod
	def create_contract(
		session: Any,
		data: dict[str, Any],
		tenant_id: str,
		template_id: str | None = None,
	) -> Any:
		"""Create a DRAFT contract, optionally seeding body from a template."""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, ContractTemplate, ContractVersion
		from pgappforge.plugins.erp.crm.contracts.events import ContractCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		body = data.get("body", "")

		if template_id:
			tmpl = session.execute(
				sa.select(ContractTemplate).where(
					ContractTemplate.id == template_id,
					ContractTemplate.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if tmpl is None:
				raise CLMValidationError(f"ContractTemplate {template_id} not found for tenant {tenant_id}")
			body = body or tmpl.template_body

		contract = Contract(
			tenant_id=tenant_id,
			contract_number=data["contract_number"],
			title=data["title"],
			template_id=template_id,
			contract_type=data.get("contract_type", "OTHER"),
			counterparty_id=data["counterparty_id"],
			internal_owner_id=data["internal_owner_id"],
			status="DRAFT",
			effective_date=data.get("effective_date"),
			expiry_date=data.get("expiry_date"),
			termination_notice_days=data.get("termination_notice_days", 30),
			auto_renew=data.get("auto_renew", False),
			renewal_notice_days=data.get("renewal_notice_days", 60),
			contract_value_cents=data.get("contract_value_cents"),
			currency_code=data.get("currency_code", "KES"),
			payment_terms_days=data.get("payment_terms_days"),
			governing_law=data.get("governing_law", "KE"),
			confidentiality_level=data.get("confidentiality_level", "INTERNAL"),
		)
		session.add(contract)
		session.flush()

		# Create v1 snapshot
		v1 = ContractVersion(
			tenant_id=tenant_id,
			contract_id=contract.id,
			version_number=1,
			body=body,
			change_summary="Initial draft",
			created_by=data.get("internal_owner_id", contract.internal_owner_id),
			status="DRAFT",
		)
		session.add(v1)
		session.flush()

		emit_event(ContractCreatedEvent(
			aggregate_id=contract.id,
			aggregate_type="Contract",
			tenant_id=tenant_id,
			contract_id=contract.id,
			contract_number=contract.contract_number,
			contract_type=contract.contract_type,
			counterparty_id=contract.counterparty_id,
			internal_owner_id=contract.internal_owner_id,
		), session)

		log.info("CLMService.create_contract: %s created", contract.contract_number)
		return contract

	# ------------------------------------------------------------------
	# 2. submit_for_review
	# ------------------------------------------------------------------

	@staticmethod
	def submit_for_review(
		session: Any,
		contract_id: str,
		submitted_by: str,
		tenant_id: str,
	) -> Any:
		"""Transition DRAFT → UNDER_REVIEW and seed default ContractApproval rows."""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, ContractApproval

		contract = session.execute(
			sa.select(Contract).where(
				Contract.id == contract_id,
				Contract.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"Contract {contract_id} not found")
		if contract.status != "DRAFT":
			raise CLMValidationError(
				f"Cannot submit a {contract.status} contract for review; must be DRAFT"
			)

		contract.status = "UNDER_REVIEW"
		session.flush()

		# Seed approval rows (one per role, in sequence)
		for role, seq in _DEFAULT_APPROVAL_SEQUENCE:
			existing = session.execute(
				sa.select(ContractApproval).where(
					ContractApproval.contract_id == contract_id,
					ContractApproval.approval_role == role,
				)
			).scalar_one_or_none()
			if existing is None:
				session.add(ContractApproval(
					tenant_id=tenant_id,
					contract_id=contract_id,
					approver_id=submitted_by,  # placeholder — caller may update
					approval_role=role,
					status="PENDING",
					sequence_order=seq,
				))
		session.flush()

		log.info(
			"CLMService.submit_for_review: contract %s moved to UNDER_REVIEW by %s",
			contract.contract_number, submitted_by,
		)
		return contract

	# ------------------------------------------------------------------
	# 3. record_approval
	# ------------------------------------------------------------------

	@staticmethod
	def record_approval(
		session: Any,
		contract_id: str,
		approver_id: str,
		decision: str,
		comments: str | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Record APPROVED/REJECTED/SKIPPED for an approver.

		If all non-SKIPPED approvals are APPROVED, contract moves to PENDING_SIGNATURE.
		"""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, ContractApproval
		from pgappforge.plugins.erp.crm.contracts.events import ContractApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		if decision not in ("APPROVED", "REJECTED", "SKIPPED"):
			raise CLMValidationError(f"Invalid decision {decision!r}; expected APPROVED/REJECTED/SKIPPED")

		approval = session.execute(
			sa.select(ContractApproval).where(
				ContractApproval.contract_id == contract_id,
				ContractApproval.approver_id == approver_id,
				ContractApproval.status == "PENDING",
			).order_by(ContractApproval.sequence_order).limit(1)
		).scalar_one_or_none()
		if approval is None:
			raise CLMValidationError(
				f"No PENDING approval for approver {approver_id} on contract {contract_id}"
			)

		now = datetime.now(timezone.utc)
		approval.status = decision
		approval.comments = comments
		approval.decided_at = now
		session.flush()

		if decision == "REJECTED":
			# Short-circuit: put contract back to NEGOTIATION
			contract = session.execute(
				sa.select(Contract).where(Contract.id == contract_id)
			).scalar_one_or_none()
			if contract:
				contract.status = "NEGOTIATION"
				session.flush()
			log.info("CLMService.record_approval: contract %s rejected by %s", contract_id, approver_id)
			return approval

		# Check if all PENDING approvals are resolved
		pending_count = session.execute(
			sa.select(sa.func.count()).select_from(ContractApproval).where(
				ContractApproval.contract_id == contract_id,
				ContractApproval.status == "PENDING",
			)
		).scalar_one()

		if pending_count == 0:
			contract = session.execute(
				sa.select(Contract).where(Contract.id == contract_id)
			).scalar_one_or_none()
			if contract and contract.status == "UNDER_REVIEW":
				contract.status = "PENDING_SIGNATURE"
				session.flush()
				emit_event(ContractApprovedEvent(
					aggregate_id=contract.id,
					aggregate_type="Contract",
					tenant_id=tenant_id or contract.tenant_id,
					contract_id=contract.id,
					contract_number=contract.contract_number,
					contract_type=contract.contract_type,
					counterparty_id=contract.counterparty_id,
				), session)
				log.info(
					"CLMService.record_approval: contract %s fully approved → PENDING_SIGNATURE",
					contract.contract_number,
				)

		return approval

	# ------------------------------------------------------------------
	# 4. send_for_signature
	# ------------------------------------------------------------------

	@staticmethod
	def send_for_signature(
		session: Any,
		contract_id: str,
		signatories: list[dict[str, Any]],
		provider: str = "LOCAL",
		tenant_id: str = "",
	) -> list[Any]:
		"""Create ESignatureRequest rows and attempt provider API call (non-fatal)."""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, ESignatureRequest

		contract = session.execute(
			sa.select(Contract).where(Contract.id == contract_id)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"Contract {contract_id} not found")
		if contract.status != "PENDING_SIGNATURE":
			raise CLMValidationError(
				f"Contract must be PENDING_SIGNATURE to send for signature; current: {contract.status}"
			)

		now = datetime.now(timezone.utc)
		requests: list[Any] = []
		for sig in signatories:
			req = ESignatureRequest(
				tenant_id=tenant_id or contract.tenant_id,
				contract_id=contract_id,
				signatory_id=sig["signatory_id"],
				signatory_name=sig["signatory_name"],
				signatory_email=sig["signatory_email"],
				signatory_role=sig.get("signatory_role", "SIGNATORY"),
				provider=provider,
				status="SENT",
				sent_at=now,
			)
			session.add(req)
			requests.append(req)
		session.flush()

		# Non-fatal provider API call
		try:
			CLMService._dispatch_to_provider(provider, contract, requests)
		except Exception as exc:
			log.warning(
				"CLMService.send_for_signature: provider=%r dispatch failed (non-fatal): %s",
				provider, exc,
			)

		log.info(
			"CLMService.send_for_signature: %d signature requests created for contract %s",
			len(requests), contract_id,
		)
		return requests

	@staticmethod
	def _dispatch_to_provider(
		provider: str,
		contract: Any,
		requests: list[Any],
	) -> None:
		"""Placeholder for external e-signature provider API integration."""
		if provider in ("DOCUSIGN", "ADOBE_SIGN"):
			log.debug(
				"CLMService._dispatch_to_provider: %s integration not yet configured for contract %s",
				provider, contract.id,
			)
		# LOCAL / MANUAL: in-app links generated elsewhere; nothing to call here

	# ------------------------------------------------------------------
	# 5. record_signature
	# ------------------------------------------------------------------

	@staticmethod
	def record_signature(
		session: Any,
		signature_request_id: str,
		tenant_id: str = "",
	) -> Any:
		"""Mark a signature request SIGNED. If all signatories have signed: ACTIVE."""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, ESignatureRequest
		from pgappforge.plugins.erp.crm.contracts.events import ContractSignedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		req = session.execute(
			sa.select(ESignatureRequest).where(ESignatureRequest.id == signature_request_id)
		).scalar_one_or_none()
		if req is None:
			raise SignatureRequestNotFoundError(f"ESignatureRequest {signature_request_id} not found")

		now = datetime.now(timezone.utc)
		req.status = "SIGNED"
		req.signed_at = now
		session.flush()

		# Check if all signature requests for this contract are SIGNED
		pending_sigs = session.execute(
			sa.select(sa.func.count()).select_from(ESignatureRequest).where(
				ESignatureRequest.contract_id == req.contract_id,
				ESignatureRequest.status.notin_(["SIGNED", "DECLINED", "EXPIRED"]),
			)
		).scalar_one()

		if pending_sigs == 0:
			contract = session.execute(
				sa.select(Contract).where(Contract.id == req.contract_id)
			).scalar_one_or_none()
			if contract:
				contract.status = "ACTIVE"
				contract.signed_at = now
				session.flush()
				emit_event(ContractSignedEvent(
					aggregate_id=contract.id,
					aggregate_type="Contract",
					tenant_id=tenant_id or contract.tenant_id,
					contract_id=contract.id,
					contract_number=contract.contract_number,
					contract_type=contract.contract_type,
					counterparty_id=contract.counterparty_id,
					signed_at=now.isoformat(),
				), session)
				log.info(
					"CLMService.record_signature: all signed — contract %s now ACTIVE",
					contract.contract_number,
				)

		return req

	# ------------------------------------------------------------------
	# 6. create_obligation
	# ------------------------------------------------------------------

	@staticmethod
	def create_obligation(
		session: Any,
		contract_id: str,
		data: dict[str, Any],
		tenant_id: str,
	) -> Any:
		"""Add a ContractObligation to an existing contract."""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, ContractObligation

		contract = session.execute(
			sa.select(Contract).where(
				Contract.id == contract_id,
				Contract.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"Contract {contract_id} not found")

		obligation = ContractObligation(
			tenant_id=tenant_id,
			contract_id=contract_id,
			obligation_type=data["obligation_type"],
			description=data["description"],
			due_date=data.get("due_date"),
			recurring_rule=data.get("recurring_rule"),
			amount_cents=data.get("amount_cents"),
			responsible_party=data.get("responsible_party", "OUR_COMPANY"),
			status="PENDING",
			alert_days_before=data.get("alert_days_before", 14),
		)
		session.add(obligation)
		session.flush()

		log.info(
			"CLMService.create_obligation: %s obligation created for contract %s",
			obligation.obligation_type, contract_id,
		)
		return obligation

	# ------------------------------------------------------------------
	# 7. fulfill_obligation
	# ------------------------------------------------------------------

	@staticmethod
	def fulfill_obligation(
		session: Any,
		obligation_id: str,
		notes: str | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Mark an obligation FULFILLED."""
		from pgappforge.plugins.erp.crm.contracts.models import ContractObligation
		from pgappforge.plugins.erp.crm.contracts.events import ObligationFulfilledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		obligation = session.execute(
			sa.select(ContractObligation).where(ContractObligation.id == obligation_id)
		).scalar_one_or_none()
		if obligation is None:
			raise ObligationNotFoundError(f"ContractObligation {obligation_id} not found")
		if obligation.status in ("FULFILLED", "WAIVED"):
			raise CLMValidationError(f"Obligation already {obligation.status}")

		now = datetime.now(timezone.utc)
		obligation.status = "FULFILLED"
		obligation.fulfilled_at = now
		if notes:
			obligation.description = f"{obligation.description}\n\nFulfilment notes: {notes}"
		session.flush()

		emit_event(ObligationFulfilledEvent(
			aggregate_id=obligation.id,
			aggregate_type="ContractObligation",
			tenant_id=tenant_id or obligation.tenant_id,
			obligation_id=obligation.id,
			contract_id=obligation.contract_id,
			obligation_type=obligation.obligation_type,
			fulfilled_at=now.isoformat(),
		), session)

		log.info("CLMService.fulfill_obligation: obligation %s fulfilled", obligation_id)
		return obligation

	# ------------------------------------------------------------------
	# 8. get_overdue_obligations
	# ------------------------------------------------------------------

	@staticmethod
	def get_overdue_obligations(
		session: Any,
		as_of_date: date | None = None,
		tenant_id: str = "",
	) -> list[dict[str, Any]]:
		"""Return PENDING obligations whose due_date < as_of_date."""
		from pgappforge.plugins.erp.crm.contracts.models import ContractObligation, Contract

		ref = as_of_date or date.today()

		stmt = (
			sa.select(ContractObligation, Contract.contract_number)
			.join(Contract, Contract.id == ContractObligation.contract_id)
			.where(
				ContractObligation.status == "PENDING",
				ContractObligation.due_date < ref,
			)
		)
		if tenant_id:
			stmt = stmt.where(ContractObligation.tenant_id == tenant_id)

		rows = session.execute(stmt).all()

		result: list[dict[str, Any]] = []
		for obl, contract_number in rows:
			days_overdue = (ref - obl.due_date).days if obl.due_date else 0
			result.append({
				"obligation_id": obl.id,
				"contract_id": obl.contract_id,
				"contract_number": contract_number,
				"obligation_type": obl.obligation_type,
				"description": obl.description,
				"due_date": obl.due_date.isoformat() if obl.due_date else None,
				"days_overdue": days_overdue,
				"amount_cents": obl.amount_cents,
				"responsible_party": obl.responsible_party,
			})

		log.info(
			"CLMService.get_overdue_obligations: %d overdue as of %s",
			len(result), ref,
		)
		return result

	# ------------------------------------------------------------------
	# 9. process_renewals
	# ------------------------------------------------------------------

	@staticmethod
	def process_renewals(
		session: Any,
		as_of_date: date,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Process upcoming expirations.

		Contracts where expiry_date <= as_of_date + renewal_notice_days:
		  - auto_renew=True:  extend expiry by lease_term or 1 year, create RENEWAL obligation, emit ContractSignedEvent stub
		  - auto_renew=False: emit ContractRenewalAlertEvent
		"""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, ContractObligation
		from pgappforge.plugins.erp.crm.contracts.events import ContractRenewalAlertEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		import datetime as dt

		stmt = sa.select(Contract).where(
			Contract.status == "ACTIVE",
			Contract.expiry_date.isnot(None),
		)
		if tenant_id:
			stmt = stmt.where(Contract.tenant_id == tenant_id)

		contracts = session.execute(stmt).scalars().all()

		auto_renewed: list[str] = []
		alerts_sent: list[str] = []

		for contract in contracts:
			if contract.expiry_date is None:
				continue
			days_to_expiry = (contract.expiry_date - as_of_date).days
			if days_to_expiry > contract.renewal_notice_days:
				continue

			if contract.auto_renew:
				# Extend expiry by 1 year (365 days)
				new_expiry = contract.expiry_date + dt.timedelta(days=365)
				contract.expiry_date = new_expiry
				session.flush()

				# Create a RENEWAL obligation
				renewal_obl = ContractObligation(
					tenant_id=contract.tenant_id,
					contract_id=contract.id,
					obligation_type="RENEWAL",
					description=f"Auto-renewal processed: new expiry {new_expiry.isoformat()}",
					due_date=new_expiry,
					responsible_party="OUR_COMPANY",
					status="PENDING",
					alert_days_before=contract.renewal_notice_days,
				)
				session.add(renewal_obl)
				session.flush()
				auto_renewed.append(contract.contract_number)

				log.info(
					"CLMService.process_renewals: auto-renewed %s → new expiry %s",
					contract.contract_number, new_expiry,
				)
			else:
				emit_event(ContractRenewalAlertEvent(
					aggregate_id=contract.id,
					aggregate_type="Contract",
					tenant_id=contract.tenant_id,
					contract_id=contract.id,
					contract_number=contract.contract_number,
					expiry_date=contract.expiry_date.isoformat(),
					days_to_expiry=days_to_expiry,
				), session)
				alerts_sent.append(contract.contract_number)

				log.info(
					"CLMService.process_renewals: alert sent for %s, expiry in %d days",
					contract.contract_number, days_to_expiry,
				)

		return {
			"as_of_date": as_of_date.isoformat(),
			"auto_renewed": auto_renewed,
			"renewal_alerts": alerts_sent,
			"auto_renewed_count": len(auto_renewed),
			"alerts_count": len(alerts_sent),
		}

	# ------------------------------------------------------------------
	# 10. terminate_contract
	# ------------------------------------------------------------------

	@staticmethod
	def terminate_contract(
		session: Any,
		contract_id: str,
		reason: str,
		effective_date: date,
		tenant_id: str,
	) -> Any:
		"""Terminate a contract; valid from any active or suspended status."""
		from pgappforge.plugins.erp.crm.contracts.models import Contract
		from pgappforge.plugins.erp.crm.contracts.events import ContractTerminatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		contract = session.execute(
			sa.select(Contract).where(
				Contract.id == contract_id,
				Contract.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"Contract {contract_id} not found")
		if contract.status in ("TERMINATED", "CANCELLED"):
			raise CLMValidationError(f"Contract is already {contract.status}")

		now = datetime.now(timezone.utc)
		contract.status = "TERMINATED"
		contract.terminated_at = now
		contract.termination_reason = reason
		session.flush()

		emit_event(ContractTerminatedEvent(
			aggregate_id=contract.id,
			aggregate_type="Contract",
			tenant_id=tenant_id,
			contract_id=contract.id,
			contract_number=contract.contract_number,
			reason=reason,
			effective_date=effective_date.isoformat(),
		), session)

		log.info(
			"CLMService.terminate_contract: %s terminated, effective %s",
			contract.contract_number, effective_date,
		)
		return contract

	# ------------------------------------------------------------------
	# 11. calculate_lease_schedule
	# ------------------------------------------------------------------

	@staticmethod
	def calculate_lease_schedule(
		session: Any,
		contract_id: str,
		tenant_id: str,
	) -> Any:
		"""Compute IFRS 16 present value and post GL recognition entries.

		IFRS 16 present value of lease payments:
		  PV = P × [1 - (1 + r)^(-n)] / r
		  where:
		    P = monthly_payment_cents
		    r = discount_rate_pa / 12   (monthly rate)
		    n = lease_term_months

		ROU asset = PV (initial direct costs assumed zero).
		Lease liability = PV.

		GL entries at recognition:
		  DR  Right-of-use asset  "1600"   PV
		  CR  Lease liability     "2500"   PV

		All arithmetic performed in Decimal to satisfy IFRS precision requirements.
		"""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, LeaseSchedule
		from pgappforge.plugins.erp.crm.contracts.events import LeaseRecognisedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		contract = session.execute(
			sa.select(Contract).where(
				Contract.id == contract_id,
				Contract.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"Contract {contract_id} not found")
		if contract.contract_type != "LEASE":
			raise CLMValidationError(
				f"Contract {contract_id} is type {contract.contract_type!r}; LEASE required"
			)

		data = contract.__dict__  # for convenience below; fields come from caller-supplied lease data
		# Lease parameters must be supplied via caller; we look for them on the contract
		# or fall back to a partially-created LeaseSchedule row passed via session.
		# In practice the caller must have added a LeaseSchedule stub first.
		existing = session.execute(
			sa.select(LeaseSchedule).where(LeaseSchedule.contract_id == contract_id)
		).scalar_one_or_none()
		if existing is None:
			raise CLMValidationError(
				f"No LeaseSchedule stub found for contract {contract_id}; "
				"create one with commencement_date, lease_term_months, "
				"monthly_payment_cents, and discount_rate_pa before calling this method."
			)

		ls = existing

		# --- IFRS 16 PV calculation (Decimal arithmetic) ---
		P = Decimal(str(ls.monthly_payment_cents))
		rate_pa = Decimal(str(ls.discount_rate_pa))
		r = rate_pa / Decimal("12")  # monthly rate
		n = Decimal(str(ls.lease_term_months))

		if r == Decimal("0"):
			# Zero-rate edge case: PV = P × n
			pv = P * n
		else:
			# PV annuity formula
			discount_factor = (Decimal("1") - (Decimal("1") + r) ** (-n)) / r
			pv = P * discount_factor

		pv_cents = int(pv.to_integral_value(rounding=ROUND_HALF_UP))

		ls.rou_asset_cents = pv_cents
		ls.lease_liability_cents = pv_cents
		ls.initial_recognition_date = ls.commencement_date
		session.flush()

		# Post GL recognition entries (lazy import; non-fatal if GL not available)
		try:
			from pgappforge.plugins.erp.foundation.gl import post_journal_entry  # type: ignore[import]
			post_journal_entry(
				session=session,
				tenant_id=tenant_id,
				description=f"IFRS 16 initial recognition — {contract.contract_number}",
				lines=[
					{"account": "1600", "debit_cents": pv_cents, "credit_cents": 0,
					 "narration": "Right-of-use asset"},
					{"account": "2500", "debit_cents": 0, "credit_cents": pv_cents,
					 "narration": "Lease liability"},
				],
				reference=contract.contract_number,
				period_date=ls.commencement_date,
			)
		except Exception as exc:
			log.warning(
				"CLMService.calculate_lease_schedule: GL post skipped (non-fatal): %s", exc
			)

		emit_event(LeaseRecognisedEvent(
			aggregate_id=contract.id,
			aggregate_type="Contract",
			tenant_id=tenant_id,
			contract_id=contract.id,
			contract_number=contract.contract_number,
			lease_type=ls.lease_type,
			rou_asset_cents=pv_cents,
			lease_liability_cents=pv_cents,
			recognition_date=ls.commencement_date.isoformat(),
		), session)

		log.info(
			"CLMService.calculate_lease_schedule: contract %s — PV=%d cents, "
			"ROU=%d, liability=%d",
			contract.contract_number, pv_cents, ls.rou_asset_cents, ls.lease_liability_cents,
		)
		return ls

	# ------------------------------------------------------------------
	# 12. amortise_rou_asset
	# ------------------------------------------------------------------

	@staticmethod
	def amortise_rou_asset(
		session: Any,
		contract_id: str,
		period_date: date,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Compute and post one month's IFRS 16 amortisation / interest / principal entries.

		Monthly calculations:
		  depreciation  = rou_asset_cents / lease_term_months   (straight-line)
		  interest      = lease_liability_cents × monthly_rate
		  principal     = monthly_payment_cents - interest
		  new ROU carrying = rou_asset_cents - depreciation
		  new liability    = lease_liability_cents - principal

		GL entries:
		  DR  Depreciation expense  "5200"   depreciation_cents
		  CR  Accumulated depr      "1610"   depreciation_cents

		  DR  Interest expense      "5100"   interest_cents
		  CR  Lease liability       "2500"   interest_cents

		  DR  Lease liability       "2500"   principal_cents  (total payment = interest+principal)
		  CR  Bank / cash           "1011"   monthly_payment_cents

		All Decimal arithmetic; returns cents dict.
		"""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, LeaseSchedule

		contract = session.execute(
			sa.select(Contract).where(
				Contract.id == contract_id,
				Contract.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"Contract {contract_id} not found")

		ls = session.execute(
			sa.select(LeaseSchedule).where(LeaseSchedule.contract_id == contract_id)
		).scalar_one_or_none()
		if ls is None:
			raise CLMValidationError(
				f"No LeaseSchedule found for contract {contract_id}; "
				"run calculate_lease_schedule first."
			)

		P = Decimal(str(ls.monthly_payment_cents))
		rate_pa = Decimal(str(ls.discount_rate_pa))
		r = rate_pa / Decimal("12")
		n = Decimal(str(ls.lease_term_months))
		rou = Decimal(str(ls.rou_asset_cents))
		liability = Decimal(str(ls.lease_liability_cents))

		# Straight-line depreciation
		depreciation = (rou / n).to_integral_value(rounding=ROUND_HALF_UP)

		# Effective interest on opening liability
		interest = (liability * r).to_integral_value(rounding=ROUND_HALF_UP)

		# Principal repayment
		principal = (P - interest).to_integral_value(rounding=ROUND_HALF_UP)

		new_rou = int(rou - depreciation)
		new_liability = int(liability - principal)

		# Update schedule
		ls.rou_asset_cents = new_rou
		ls.lease_liability_cents = max(new_liability, 0)
		session.flush()

		depreciation_cents = int(depreciation)
		interest_cents = int(interest)
		principal_cents = int(principal)
		payment_cents = int(P)

		# Post GL (non-fatal)
		try:
			from pgappforge.plugins.erp.foundation.gl import post_journal_entry  # type: ignore[import]
			ref = f"{contract.contract_number}/{period_date.isoformat()}"
			# Entry 1: depreciation
			post_journal_entry(
				session=session,
				tenant_id=tenant_id,
				description=f"IFRS 16 ROU depreciation — {ref}",
				lines=[
					{"account": "5200", "debit_cents": depreciation_cents, "credit_cents": 0,
					 "narration": "Depreciation expense"},
					{"account": "1610", "debit_cents": 0, "credit_cents": depreciation_cents,
					 "narration": "Accumulated depreciation — ROU asset"},
				],
				reference=ref,
				period_date=period_date,
			)
			# Entry 2: interest accrual
			post_journal_entry(
				session=session,
				tenant_id=tenant_id,
				description=f"IFRS 16 interest expense — {ref}",
				lines=[
					{"account": "5100", "debit_cents": interest_cents, "credit_cents": 0,
					 "narration": "Interest expense on lease liability"},
					{"account": "2500", "debit_cents": 0, "credit_cents": interest_cents,
					 "narration": "Lease liability — interest accrual"},
				],
				reference=ref,
				period_date=period_date,
			)
			# Entry 3: payment (principal + interest clears liability, bank credited)
			post_journal_entry(
				session=session,
				tenant_id=tenant_id,
				description=f"IFRS 16 lease payment — {ref}",
				lines=[
					{"account": "2500", "debit_cents": payment_cents, "credit_cents": 0,
					 "narration": "Lease liability — payment"},
					{"account": "1011", "debit_cents": 0, "credit_cents": payment_cents,
					 "narration": "Bank — lease payment"},
				],
				reference=ref,
				period_date=period_date,
			)
		except Exception as exc:
			log.warning("CLMService.amortise_rou_asset: GL post skipped (non-fatal): %s", exc)

		result = {
			"period_date": period_date.isoformat(),
			"depreciation_cents": depreciation_cents,
			"interest_cents": interest_cents,
			"principal_cents": principal_cents,
			"payment_cents": payment_cents,
			"rou_carrying_cents": new_rou,
			"liability_cents": max(new_liability, 0),
		}

		log.info(
			"CLMService.amortise_rou_asset: contract %s period %s — "
			"depr=%d interest=%d principal=%d",
			contract.contract_number, period_date,
			depreciation_cents, interest_cents, principal_cents,
		)
		return result

	# ------------------------------------------------------------------
	# 13. get_contract_dashboard
	# ------------------------------------------------------------------

	@staticmethod
	def get_contract_dashboard(
		session: Any,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Aggregate KPIs for the CLM dashboard.

		Returns:
		  active_count           — ACTIVE contracts
		  expiring_30d           — ACTIVE contracts expiring within 30 days
		  expiring_90d           — ACTIVE contracts expiring within 90 days
		  overdue_obligations    — PENDING obligations past due date
		  total_value_cents      — sum of contract_value_cents for ACTIVE contracts
		  by_type                — dict[contract_type, count]
		  by_status              — dict[status, count]
		"""
		from pgappforge.plugins.erp.crm.contracts.models import Contract, ContractObligation
		import datetime as dt

		today = date.today()
		d30 = today + dt.timedelta(days=30)
		d90 = today + dt.timedelta(days=90)

		# Active count
		active_count: int = session.execute(
			sa.select(sa.func.count()).select_from(Contract).where(
				Contract.tenant_id == tenant_id,
				Contract.status == "ACTIVE",
			)
		).scalar_one()

		# Expiring within 30 days
		expiring_30d: int = session.execute(
			sa.select(sa.func.count()).select_from(Contract).where(
				Contract.tenant_id == tenant_id,
				Contract.status == "ACTIVE",
				Contract.expiry_date.isnot(None),
				Contract.expiry_date <= d30,
				Contract.expiry_date >= today,
			)
		).scalar_one()

		# Expiring within 90 days
		expiring_90d: int = session.execute(
			sa.select(sa.func.count()).select_from(Contract).where(
				Contract.tenant_id == tenant_id,
				Contract.status == "ACTIVE",
				Contract.expiry_date.isnot(None),
				Contract.expiry_date <= d90,
				Contract.expiry_date >= today,
			)
		).scalar_one()

		# Overdue obligations
		overdue_obligations: int = session.execute(
			sa.select(sa.func.count()).select_from(ContractObligation).where(
				ContractObligation.tenant_id == tenant_id,
				ContractObligation.status == "PENDING",
				ContractObligation.due_date < today,
			)
		).scalar_one()

		# Total contract value (ACTIVE)
		total_value_cents = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(Contract.contract_value_cents), 0)).where(
				Contract.tenant_id == tenant_id,
				Contract.status == "ACTIVE",
			)
		).scalar_one() or 0

		# By type
		type_rows = session.execute(
			sa.select(Contract.contract_type, sa.func.count())
			.where(Contract.tenant_id == tenant_id)
			.group_by(Contract.contract_type)
		).all()
		by_type = {row[0]: row[1] for row in type_rows}

		# By status
		status_rows = session.execute(
			sa.select(Contract.status, sa.func.count())
			.where(Contract.tenant_id == tenant_id)
			.group_by(Contract.status)
		).all()
		by_status = {row[0]: row[1] for row in status_rows}

		return {
			"active_count": active_count,
			"expiring_30d": expiring_30d,
			"expiring_90d": expiring_90d,
			"overdue_obligations": overdue_obligations,
			"total_value_cents": int(total_value_cents),
			"by_type": by_type,
			"by_status": by_status,
		}


__all__ = [
	"CLMService",
	"CLMError",
	"ContractNotFoundError",
	"ObligationNotFoundError",
	"SignatureRequestNotFoundError",
	"CLMValidationError",
]
