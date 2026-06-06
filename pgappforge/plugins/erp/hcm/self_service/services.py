from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from pgappforge.plugins.workflow.engine import BPMActionRegistry

from .events import (
	AnnouncementPublishedEvent,
	LeaveRequestApprovedEvent,
	LeaveRequestRejectedEvent,
	LeaveRequestSubmittedEvent,
	ProfileUpdateRequestedEvent,
)
from .models import (
	Announcement,
	EssDocument,
	LeaveBalance,
	LeaveRequest,
	ProfileUpdateRequest,
)

__all__ = [
	"EssServiceError",
	"LeaveRequestError",
	"LeaveBalanceError",
	"SelfServiceService",
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EssServiceError(Exception):
	"""Base error for ESS service operations."""


class LeaveRequestError(EssServiceError):
	"""Raised when a leave request operation is invalid."""


class LeaveBalanceError(EssServiceError):
	"""Raised when a leave balance check fails."""


# ---------------------------------------------------------------------------
# Default entitlements by leave type
# ---------------------------------------------------------------------------

_DEFAULT_ENTITLEMENTS: dict[str, float] = {
	"ANNUAL": 21.0,
	"SICK": 10.0,
	"MATERNITY": 90.0,
	"PATERNITY": 14.0,
	"COMPASSIONATE": 5.0,
	"STUDY": 10.0,
	"UNPAID": 0.0,
}


def _count_business_days(start: date, end: date) -> float:
	"""Count Mon-Fri business days between start and end inclusive."""
	if end < start:
		raise LeaveRequestError(f"end_date {end} is before start_date {start}")
	total = 0.0
	current = start
	while current <= end:
		if current.weekday() < 5:  # 0=Mon … 4=Fri
			total += 1.0
		from datetime import timedelta
		current += timedelta(days=1)
	return total


def _now_utc() -> datetime:
	return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SelfServiceService:
	"""Employee Self-Service and Manager Self-Service operations."""

	def __init__(self) -> None:
		pass

	# ------------------------------------------------------------------
	# Leave management
	# ------------------------------------------------------------------

	def submit_leave_request(
		self,
		employee_id: str,
		leave_type: str,
		start_date: date,
		end_date: date,
		tenant_id: str,
		session: Session,
		*,
		reason: str | None = None,
		handover_notes: str | None = None,
		entity_id: str | None = None,
	) -> LeaveRequest:
		assert employee_id, "employee_id is required"
		assert leave_type in LeaveRequest.VALID_LEAVE_TYPES, (
			f"Invalid leave_type '{leave_type}'. Valid: {sorted(LeaveRequest.VALID_LEAVE_TYPES)}"
		)
		assert tenant_id, "tenant_id is required"

		days = _count_business_days(start_date, end_date)
		if days <= 0:
			raise LeaveRequestError("Leave request must span at least one business day")

		year = start_date.year
		balance = self.get_leave_balance(employee_id, leave_type, year, tenant_id, session)
		available = float(balance.balance_days)
		if leave_type != "UNPAID" and available < days:
			raise LeaveBalanceError(
				f"Insufficient {leave_type} balance: {available:.1f} days available, "
				f"{days:.1f} days requested"
			)

		req = LeaveRequest(
			tenant_id=tenant_id,
			employee_id=employee_id,
			leave_type=leave_type,
			start_date=start_date,
			end_date=end_date,
			days_requested=days,
			status="PENDING",
			reason=reason,
			handover_notes=handover_notes,
			entity_id=entity_id,
		)
		session.add(req)
		session.flush()

		assert req.id, "LeaveRequest must have an id after flush"

		self._bus.emit(
			LeaveRequestSubmittedEvent(
				request_id=req.id,
				employee_id=employee_id,
				leave_type=leave_type,
				start_date=str(start_date),
				end_date=str(end_date),
				days=days,
			)
		)
		return req

	@BPMActionRegistry.register(
		"hcm.self_service.approve_leave",
		"Approve employee leave request",
	)
	def approve_leave(
		self,
		request_id: str,
		approver_id: str,
		session: Session,
	) -> LeaveRequest:
		assert request_id, "request_id is required"
		assert approver_id, "approver_id is required"

		req = session.execute(
			sa.select(LeaveRequest).where(LeaveRequest.id == request_id)
		).scalar_one_or_none()
		if req is None:
			raise LeaveRequestError(f"LeaveRequest {request_id!r} not found")
		if req.status != "PENDING":
			raise LeaveRequestError(
				f"Cannot approve leave request in status '{req.status}'; must be PENDING"
			)

		req.status = "APPROVED"
		req.approved_by = approver_id
		req.approved_at = _now_utc()

		# Deduct from balance
		year = req.start_date.year
		balance = self.get_leave_balance(
			req.employee_id, req.leave_type, year, req.tenant_id, session
		)
		balance.used_days = float(balance.used_days) + float(req.days_requested)
		balance.recompute_balance()

		session.flush()

		self._bus.emit(
			LeaveRequestApprovedEvent(
				request_id=req.id,
				employee_id=req.employee_id,
				approved_by=approver_id,
			)
		)
		return req

	def reject_leave(
		self,
		request_id: str,
		rejector_id: str,
		reason: str,
		session: Session,
	) -> LeaveRequest:
		assert request_id, "request_id is required"
		assert rejector_id, "rejector_id is required"
		assert reason, "reason is required for rejection"

		req = session.execute(
			sa.select(LeaveRequest).where(LeaveRequest.id == request_id)
		).scalar_one_or_none()
		if req is None:
			raise LeaveRequestError(f"LeaveRequest {request_id!r} not found")
		if req.status != "PENDING":
			raise LeaveRequestError(
				f"Cannot reject leave request in status '{req.status}'; must be PENDING"
			)

		req.status = "REJECTED"
		req.rejected_by = rejector_id
		req.rejection_reason = reason
		session.flush()

		self._bus.emit(
			LeaveRequestRejectedEvent(
				request_id=req.id,
				employee_id=req.employee_id,
				rejected_by=rejector_id,
				reason=reason,
			)
		)
		return req

	def cancel_leave(
		self,
		request_id: str,
		employee_id: str,
		session: Session,
	) -> LeaveRequest:
		assert request_id, "request_id is required"
		assert employee_id, "employee_id is required"

		req = session.execute(
			sa.select(LeaveRequest).where(LeaveRequest.id == request_id)
		).scalar_one_or_none()
		if req is None:
			raise LeaveRequestError(f"LeaveRequest {request_id!r} not found")
		if req.employee_id != employee_id:
			raise LeaveRequestError(
				f"Employee {employee_id!r} cannot cancel request belonging to {req.employee_id!r}"
			)
		if req.status not in ("PENDING", "APPROVED"):
			raise LeaveRequestError(
				f"Cannot cancel leave request in status '{req.status}'"
			)

		was_approved = req.status == "APPROVED"
		req.status = "CANCELLED"

		if was_approved:
			# Restore balance
			year = req.start_date.year
			balance = self.get_leave_balance(
				req.employee_id, req.leave_type, year, req.tenant_id, session
			)
			balance.used_days = max(
				0.0,
				float(balance.used_days) - float(req.days_requested),
			)
			balance.recompute_balance()

		session.flush()
		return req

	# ------------------------------------------------------------------
	# Leave balances
	# ------------------------------------------------------------------

	def get_leave_balance(
		self,
		employee_id: str,
		leave_type: str,
		year: int,
		tenant_id: str,
		session: Session,
	) -> LeaveBalance:
		assert employee_id, "employee_id is required"
		assert leave_type, "leave_type is required"
		assert year > 0, "year must be positive"
		assert tenant_id, "tenant_id is required"

		balance = session.execute(
			sa.select(LeaveBalance).where(
				LeaveBalance.tenant_id == tenant_id,
				LeaveBalance.employee_id == employee_id,
				LeaveBalance.leave_type == leave_type,
				LeaveBalance.year == year,
			)
		).scalar_one_or_none()

		if balance is None:
			entitled = _DEFAULT_ENTITLEMENTS.get(leave_type, 0.0)
			balance = LeaveBalance(
				tenant_id=tenant_id,
				employee_id=employee_id,
				leave_type=leave_type,
				year=year,
				entitled_days=entitled,
				used_days=0.0,
				carried_over_days=0.0,
				balance_days=entitled,
			)
			session.add(balance)
			session.flush()

		assert balance.id, "LeaveBalance must have an id after flush"
		return balance

	# ------------------------------------------------------------------
	# Profile update requests
	# ------------------------------------------------------------------

	def submit_profile_update(
		self,
		employee_id: str,
		changes_dict: dict[str, Any],
		tenant_id: str,
		session: Session,
	) -> ProfileUpdateRequest:
		assert employee_id, "employee_id is required"
		assert changes_dict, "changes_dict must be non-empty"
		assert tenant_id, "tenant_id is required"

		req = ProfileUpdateRequest(
			tenant_id=tenant_id,
			employee_id=employee_id,
			requested_changes=changes_dict,
			status="PENDING",
			submitted_at=_now_utc(),
		)
		session.add(req)
		session.flush()

		assert req.id, "ProfileUpdateRequest must have an id after flush"

		self._bus.emit(
			ProfileUpdateRequestedEvent(
				request_id=req.id,
				employee_id=employee_id,
				fields_changed=list(changes_dict.keys()),
			)
		)
		return req

	def approve_profile_update(
		self,
		request_id: str,
		reviewer_id: str,
		session: Session,
		*,
		notes: str | None = None,
	) -> ProfileUpdateRequest:
		assert request_id, "request_id is required"
		assert reviewer_id, "reviewer_id is required"

		req = session.execute(
			sa.select(ProfileUpdateRequest).where(ProfileUpdateRequest.id == request_id)
		).scalar_one_or_none()
		if req is None:
			raise EssServiceError(f"ProfileUpdateRequest {request_id!r} not found")
		if req.status != "PENDING":
			raise EssServiceError(
				f"Cannot approve profile update request in status '{req.status}'"
			)

		req.status = "APPROVED"
		req.reviewed_by = reviewer_id
		req.reviewed_at = _now_utc()
		if notes:
			req.notes = notes
		session.flush()
		return req

	def reject_profile_update(
		self,
		request_id: str,
		reviewer_id: str,
		session: Session,
		*,
		notes: str | None = None,
	) -> ProfileUpdateRequest:
		assert request_id, "request_id is required"
		assert reviewer_id, "reviewer_id is required"

		req = session.execute(
			sa.select(ProfileUpdateRequest).where(ProfileUpdateRequest.id == request_id)
		).scalar_one_or_none()
		if req is None:
			raise EssServiceError(f"ProfileUpdateRequest {request_id!r} not found")
		if req.status != "PENDING":
			raise EssServiceError(
				f"Cannot reject profile update request in status '{req.status}'"
			)

		req.status = "REJECTED"
		req.reviewed_by = reviewer_id
		req.reviewed_at = _now_utc()
		if notes:
			req.notes = notes
		session.flush()
		return req

	# ------------------------------------------------------------------
	# Dashboards
	# ------------------------------------------------------------------

	def get_employee_dashboard(
		self,
		employee_id: str,
		tenant_id: str,
		session: Session,
	) -> dict[str, Any]:
		assert employee_id, "employee_id is required"
		assert tenant_id, "tenant_id is required"

		current_year = date.today().year

		# All leave balances for this employee this year
		leave_balances_rows = session.execute(
			sa.select(LeaveBalance).where(
				LeaveBalance.tenant_id == tenant_id,
				LeaveBalance.employee_id == employee_id,
				LeaveBalance.year == current_year,
			)
		).scalars().all()

		# Last 3 payslips visible to the employee
		recent_payslips = session.execute(
			sa.select(EssDocument)
			.where(
				EssDocument.tenant_id == tenant_id,
				EssDocument.employee_id == employee_id,
				EssDocument.document_type == "PAYSLIP",
				EssDocument.is_visible.is_(True),
			)
			.order_by(EssDocument.period.desc())
			.limit(3)
		).scalars().all()

		# Open leave requests
		pending_requests = session.execute(
			sa.select(LeaveRequest).where(
				LeaveRequest.tenant_id == tenant_id,
				LeaveRequest.employee_id == employee_id,
				LeaveRequest.status.in_(("PENDING", "APPROVED")),
			).order_by(LeaveRequest.start_date.asc())
		).scalars().all()

		# Active, non-expired announcements ordered by priority desc then published_at desc
		now = _now_utc()
		priority_order = sa.case(
			{"URGENT": 4, "HIGH": 3, "NORMAL": 2, "LOW": 1},
			value=Announcement.priority,
			else_=0,
		)
		announcements = session.execute(
			sa.select(Announcement)
			.where(
				Announcement.tenant_id == tenant_id,
				Announcement.published_at.isnot(None),
				Announcement.published_at <= now,
				sa.or_(
					Announcement.expires_at.is_(None),
					Announcement.expires_at > now,
				),
			)
			.order_by(priority_order.desc(), Announcement.published_at.desc())
		).scalars().all()

		return {
			"leave_balances": leave_balances_rows,
			"recent_payslips": list(recent_payslips),
			"pending_requests": list(pending_requests),
			"announcements": list(announcements),
		}

	def get_manager_dashboard(
		self,
		manager_id: str,
		tenant_id: str,
		session: Session,
		*,
		report_employee_ids: list[str] | None = None,
	) -> dict[str, Any]:
		"""Return manager dashboard data.

		report_employee_ids: list of direct reports. If None or empty, returns
		all pending requests tenant-wide (caller should filter upstream).
		"""
		assert manager_id, "manager_id is required"
		assert tenant_id, "tenant_id is required"

		now = _now_utc()
		today = now.date()

		# Pending leave requests for direct reports (or all if no reports supplied)
		pending_stmt = sa.select(LeaveRequest).where(
			LeaveRequest.tenant_id == tenant_id,
			LeaveRequest.status == "PENDING",
		)
		if report_employee_ids:
			pending_stmt = pending_stmt.where(
				LeaveRequest.employee_id.in_(report_employee_ids)
			)
		pending_stmt = pending_stmt.order_by(LeaveRequest.start_date.asc())

		pending_leave_requests = session.execute(pending_stmt).scalars().all()

		# Team members currently on approved leave today
		on_leave_stmt = sa.select(LeaveRequest).where(
			LeaveRequest.tenant_id == tenant_id,
			LeaveRequest.status == "APPROVED",
			LeaveRequest.start_date <= today,
			LeaveRequest.end_date >= today,
		)
		if report_employee_ids:
			on_leave_stmt = on_leave_stmt.where(
				LeaveRequest.employee_id.in_(report_employee_ids)
			)

		team_on_leave_today = session.execute(on_leave_stmt).scalars().all()

		# Active announcements
		priority_order = sa.case(
			{"URGENT": 4, "HIGH": 3, "NORMAL": 2, "LOW": 1},
			value=Announcement.priority,
			else_=0,
		)
		announcements = session.execute(
			sa.select(Announcement)
			.where(
				Announcement.tenant_id == tenant_id,
				Announcement.published_at.isnot(None),
				Announcement.published_at <= now,
				sa.or_(
					Announcement.expires_at.is_(None),
					Announcement.expires_at > now,
				),
			)
			.order_by(priority_order.desc(), Announcement.published_at.desc())
		).scalars().all()

		return {
			"pending_leave_requests": list(pending_leave_requests),
			"team_on_leave_today": list(team_on_leave_today),
			"announcements": list(announcements),
		}

	# ------------------------------------------------------------------
	# Announcements
	# ------------------------------------------------------------------

	def publish_announcement(
		self,
		title: str,
		body: str,
		author_id: str,
		tenant_id: str,
		session: Session,
		*,
		audience_roles: list[str] | None = None,
		expires_at: datetime | None = None,
		priority: str = "NORMAL",
		entity_id: str | None = None,
		is_pinned: bool = False,
	) -> Announcement:
		assert title, "title is required"
		assert body, "body is required"
		assert author_id, "author_id is required"
		assert tenant_id, "tenant_id is required"
		assert priority in Announcement.VALID_PRIORITIES, (
			f"Invalid priority '{priority}'. Valid: {sorted(Announcement.VALID_PRIORITIES)}"
		)

		now = _now_utc()
		ann = Announcement(
			tenant_id=tenant_id,
			title=title,
			body=body,
			author_id=author_id,
			published_at=now,
			expires_at=expires_at,
			audience_roles=audience_roles or [],
			is_pinned=is_pinned,
			priority=priority,
			entity_id=entity_id,
		)
		session.add(ann)
		session.flush()

		assert ann.id, "Announcement must have an id after flush"

		self._bus.emit(
			AnnouncementPublishedEvent(
				announcement_id=ann.id,
				title=title,
				audience_roles=audience_roles or [],
			)
		)
		return ann
