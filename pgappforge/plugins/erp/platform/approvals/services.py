"""
pgappforge/plugins/erp/platform/approvals/services.py

Configurable multi-step approval service for ERP documents.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event
from pgappforge.plugins.erp.platform.approvals.models import ApprovalRequest, ApprovalStep

log = logging.getLogger(__name__)


APPROVAL_CHAINS: dict[str, list[dict[str, Any]]] = {
	"purchase_requisition": [
		{"role": "dept_manager", "threshold_cents": 0},
		{"role": "finance_manager", "threshold_cents": 100000},
		{"role": "cfo", "threshold_cents": 1000000},
	],
	"expense_report": [
		{"role": "line_manager", "threshold_cents": 0},
		{"role": "finance_manager", "threshold_cents": 500000},
	],
	"leave_request": [
		{"role": "line_manager", "threshold_cents": 0},
	],
	"purchase_order": [
		{"role": "procurement_manager", "threshold_cents": 0},
		{"role": "finance_manager", "threshold_cents": 500000},
		{"role": "cfo", "threshold_cents": 2000000},
	],
}


class ApprovalServiceError(Exception):
	"""Raised when an approval action is invalid."""


class ApprovalNotFoundError(ApprovalServiceError):
	"""Approval request was not found."""


class ApprovalStateError(ApprovalServiceError):
	"""Approval request is not in the required lifecycle state."""


class ApprovalAuthorizationError(ApprovalServiceError):
	"""Actor is not permitted to perform the approval action."""


@dataclass
class ApprovalSubmittedEvent(DomainEvent):
	event_type: str = "platform.approvals.submitted"
	approval_request_id: str = ""
	document_type: str = ""
	document_id: str = ""
	requester_id: str = ""
	amount_cents: int = 0
	first_approver_role: str = ""


@dataclass
class ApprovalStepApprovedEvent(DomainEvent):
	event_type: str = "platform.approvals.step_approved"
	approval_request_id: str = ""
	document_type: str = ""
	document_id: str = ""
	step_number: int = 0
	approver_id: str = ""


@dataclass
class ApprovalCompletedEvent(DomainEvent):
	event_type: str = "platform.approvals.completed"
	approval_request_id: str = ""
	document_type: str = ""
	document_id: str = ""
	requester_id: str = ""
	amount_cents: int = 0


@dataclass
class ApprovalRejectedEvent(DomainEvent):
	event_type: str = "platform.approvals.rejected"
	approval_request_id: str = ""
	document_type: str = ""
	document_id: str = ""
	requester_id: str = ""
	rejected_by: str = ""
	reason: str = ""


@dataclass
class ApprovalWithdrawnEvent(DomainEvent):
	event_type: str = "platform.approvals.withdrawn"
	approval_request_id: str = ""
	document_type: str = ""
	document_id: str = ""
	requester_id: str = ""


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _role_key(value: object) -> str:
	return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _notify(recipient_id: str, subject: str, body: str, metadata: dict[str, Any]) -> None:
	try:
		from pgappforge.plugins.erp.platform.notifications.event_dispatcher import _notify as send_notification
		send_notification(recipient_id=recipient_id, subject=subject, body=body, metadata=metadata)
	except Exception as exc:
		log.info("Approval notification fallback: recipient=%s subject=%s error=%s", recipient_id, subject, exc)


def _emit(event: DomainEvent, session: Any) -> None:
	try:
		emit_event(event, session)
	except Exception as exc:
		log.debug("Approval event emit failed for %s: %s", event.event_type, exc)


class ApprovalService:
	"""Submit and route ERP documents through configurable approval chains."""

	chains = APPROVAL_CHAINS

	def submit_for_approval(
		self,
		document_type: str,
		document_id: str,
		requester_id: str,
		amount_cents: int,
		tenant_id: str,
		session: Any,
	) -> ApprovalRequest:
		document_type = _role_key(document_type)
		amount_cents = max(int(amount_cents or 0), 0)
		chain = self.chains.get(document_type)
		if chain is None:
			raise ApprovalServiceError(f"No approval chain configured for {document_type!r}")
		applicable = [step for step in chain if int(step.get("threshold_cents", 0)) <= amount_cents]
		if not applicable:
			raise ApprovalServiceError(f"No approval steps apply to {document_type!r} amount {amount_cents}")

		approval = ApprovalRequest(
			tenant_id=tenant_id,
			document_type=document_type,
			document_id=document_id,
			current_step=1,
			total_steps=len(applicable),
			status="pending",
			requester_id=requester_id,
			amount_cents=amount_cents,
		)
		session.add(approval)
		session.flush()

		for step_number, entry in enumerate(applicable, start=1):
			session.add(ApprovalStep(
				request_id=approval.id,
				step_number=step_number,
				approver_role=_role_key(entry["role"]),
				approver_id=entry.get("approver_id"),
				status="pending",
			))

		first_role = _role_key(applicable[0]["role"])
		_emit(
			ApprovalSubmittedEvent(
				aggregate_id=approval.id,
				aggregate_type="ApprovalRequest",
				tenant_id=tenant_id,
				approval_request_id=approval.id,
				document_type=document_type,
				document_id=document_id,
				requester_id=requester_id,
				amount_cents=amount_cents,
				first_approver_role=first_role,
			),
			session,
		)
		self._notify_approver(approval, first_role)
		log.info("Approval submitted: request=%s document=%s:%s first_role=%s", approval.id, document_type, document_id, first_role)
		return approval

	def approve(
		self,
		approval_request_id: str,
		approver_id: str,
		comments: str | None,
		session: Any,
	) -> ApprovalRequest:
		approval = self._get_pending_request(approval_request_id, session)
		step = self._current_step(approval, session)
		if step is None:
			raise ApprovalStateError(f"Approval request {approval_request_id!r} has no pending current step")
		if not self._actor_can_approve(step, approver_id, session):
			raise ApprovalAuthorizationError(f"Approver {approver_id!r} cannot approve step {step.step_number}")

		step.status = "approved"
		step.approver_id = step.approver_id or approver_id
		step.comments = comments
		step.decision_at = _now()
		approval.updated_at = _now()

		_emit(
			ApprovalStepApprovedEvent(
				aggregate_id=approval.id,
				aggregate_type="ApprovalRequest",
				tenant_id=approval.tenant_id,
				approval_request_id=approval.id,
				document_type=approval.document_type,
				document_id=approval.document_id,
				step_number=step.step_number,
				approver_id=approver_id,
			),
			session,
		)

		if step.step_number >= approval.total_steps:
			approval.status = "approved"
			_emit(
				ApprovalCompletedEvent(
					aggregate_id=approval.id,
					aggregate_type="ApprovalRequest",
					tenant_id=approval.tenant_id,
					approval_request_id=approval.id,
					document_type=approval.document_type,
					document_id=approval.document_id,
					requester_id=approval.requester_id,
					amount_cents=approval.amount_cents,
				),
				session,
			)
			_notify(
				approval.requester_id,
				"Approval completed",
				f"{approval.document_type} {approval.document_id} has been approved.",
				{"approval_request_id": approval.id, "document_type": approval.document_type},
			)
		else:
			approval.current_step = step.step_number + 1
			next_step = self._current_step(approval, session)
			if next_step is not None:
				self._notify_approver(approval, next_step.approver_id or next_step.approver_role)
		return approval

	def reject(
		self,
		approval_request_id: str,
		approver_id: str,
		reason: str,
		session: Any,
	) -> ApprovalRequest:
		approval = self._get_pending_request(approval_request_id, session)
		step = self._current_step(approval, session)
		if step is None:
			raise ApprovalStateError(f"Approval request {approval_request_id!r} has no pending current step")
		if not self._actor_can_approve(step, approver_id, session):
			raise ApprovalAuthorizationError(f"Approver {approver_id!r} cannot reject step {step.step_number}")

		step.status = "rejected"
		step.approver_id = step.approver_id or approver_id
		step.comments = reason
		step.decision_at = _now()
		approval.status = "rejected"
		approval.updated_at = _now()
		_emit(
			ApprovalRejectedEvent(
				aggregate_id=approval.id,
				aggregate_type="ApprovalRequest",
				tenant_id=approval.tenant_id,
				approval_request_id=approval.id,
				document_type=approval.document_type,
				document_id=approval.document_id,
				requester_id=approval.requester_id,
				rejected_by=approver_id,
				reason=reason,
			),
			session,
		)
		_notify(
			approval.requester_id,
			"Approval rejected",
			f"{approval.document_type} {approval.document_id} was rejected: {reason}",
			{"approval_request_id": approval.id, "document_type": approval.document_type},
		)
		return approval

	def withdraw(self, approval_request_id: str, requester_id: str, session: Any) -> ApprovalRequest:
		approval = self._get_request(approval_request_id, session)
		if approval.status != "pending":
			raise ApprovalStateError(f"Only pending approvals can be withdrawn; got {approval.status!r}")
		if str(approval.requester_id) != str(requester_id):
			raise ApprovalAuthorizationError("Only the requester can withdraw this approval")
		approval.status = "withdrawn"
		approval.updated_at = _now()
		_emit(
			ApprovalWithdrawnEvent(
				aggregate_id=approval.id,
				aggregate_type="ApprovalRequest",
				tenant_id=approval.tenant_id,
				approval_request_id=approval.id,
				document_type=approval.document_type,
				document_id=approval.document_id,
				requester_id=requester_id,
			),
			session,
		)
		return approval

	def get_pending_approvals(self, approver_id: str, tenant_id: str, session: Any) -> list[dict]:
		roles = self._approver_roles(approver_id, session)
		step_match = [ApprovalStep.approver_id == approver_id]
		if roles:
			step_match.append(ApprovalStep.approver_role.in_(sorted(roles)))

		query = (
			sa.select(ApprovalRequest, ApprovalStep)
			.join(ApprovalStep, ApprovalStep.request_id == ApprovalRequest.id)
			.where(
				ApprovalRequest.tenant_id == tenant_id,
				ApprovalRequest.status == "pending",
				ApprovalStep.status == "pending",
				ApprovalStep.step_number == ApprovalRequest.current_step,
				sa.or_(*step_match),
			)
			.order_by(ApprovalRequest.created_at)
		)
		return [
			self._row_dict(approval, step)
			for approval, step in session.execute(query).all()
		]

	def _get_request(self, approval_request_id: str, session: Any) -> ApprovalRequest:
		approval = session.execute(
			sa.select(ApprovalRequest).where(ApprovalRequest.id == approval_request_id)
		).scalar_one_or_none()
		if approval is None:
			raise ApprovalNotFoundError(f"ApprovalRequest {approval_request_id!r} not found")
		return approval

	def _get_pending_request(self, approval_request_id: str, session: Any) -> ApprovalRequest:
		approval = self._get_request(approval_request_id, session)
		if approval.status != "pending":
			raise ApprovalStateError(f"Approval request {approval_request_id!r} is {approval.status!r}")
		return approval

	def _current_step(self, approval: ApprovalRequest, session: Any) -> ApprovalStep | None:
		return session.execute(
			sa.select(ApprovalStep).where(
				ApprovalStep.request_id == approval.id,
				ApprovalStep.step_number == approval.current_step,
			)
		).scalar_one_or_none()

	def _actor_can_approve(self, step: ApprovalStep, approver_id: str, session: Any) -> bool:
		if step.approver_id and str(step.approver_id) == str(approver_id):
			return True
		return _role_key(step.approver_role) in self._approver_roles(approver_id, session)

	def _approver_roles(self, approver_id: str, session: Any) -> set[str]:
		roles: set[str] = {_role_key(approver_id)}
		try:
			from flask_login import current_user
			if current_user and getattr(current_user, "is_authenticated", False):
				user_id = str(getattr(current_user, "id", ""))
				username = str(getattr(current_user, "username", ""))
				email = str(getattr(current_user, "email", ""))
				if str(approver_id) in {user_id, username, email}:
					for role in getattr(current_user, "roles", []) or []:
						roles.add(_role_key(getattr(role, "name", role)))
		except Exception:
			pass
		return {role for role in roles if role}

	def _notify_approver(self, approval: ApprovalRequest, recipient_id: str) -> None:
		_notify(
			recipient_id,
			"Approval required",
			f"{approval.document_type} {approval.document_id} is awaiting your approval.",
			{
				"approval_request_id": approval.id,
				"document_type": approval.document_type,
				"document_id": approval.document_id,
				"amount_cents": approval.amount_cents,
			},
		)

	def _row_dict(self, approval: ApprovalRequest, step: ApprovalStep) -> dict[str, Any]:
		return {
			"id": approval.id,
			"tenant_id": approval.tenant_id,
			"document_type": approval.document_type,
			"document_id": approval.document_id,
			"current_step": approval.current_step,
			"total_steps": approval.total_steps,
			"status": approval.status,
			"requester_id": approval.requester_id,
			"amount_cents": approval.amount_cents,
			"created_at": approval.created_at.isoformat() if approval.created_at else None,
			"approver_role": step.approver_role,
			"approver_id": step.approver_id,
		}


__all__ = [
	"APPROVAL_CHAINS",
	"ApprovalAuthorizationError",
	"ApprovalCompletedEvent",
	"ApprovalNotFoundError",
	"ApprovalRejectedEvent",
	"ApprovalService",
	"ApprovalServiceError",
	"ApprovalStateError",
	"ApprovalStepApprovedEvent",
	"ApprovalSubmittedEvent",
	"ApprovalWithdrawnEvent",
]
