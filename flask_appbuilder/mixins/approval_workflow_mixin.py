"""
approval_workflow_mixin.py

Provides ApprovalWorkflowMixin for implementing multi-step approval workflows
in SQLAlchemy models for Flask-AppBuilder applications.

Supports parallel approvals, conditional step routing, role-based permissions,
hold/resume/cancel lifecycle, and per-step timeout configuration.

Author: Nyimbi Odero
Date: 25/08/2024
Version: 2.0
"""

from __future__ import annotations

import enum
import logging
from datetime import datetime, timedelta
from typing import Any

from flask import current_app
from flask_login import current_user
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import declared_attr, relationship

log = logging.getLogger(__name__)

# SQLAlchemy 2.x mapped_column / Mapped support with 1.x fallback
try:
	from sqlalchemy.orm import Mapped, mapped_column
	_SA2 = True
except ImportError:
	_SA2 = False

try:
	from sqlalchemy import JSON
except ImportError:
	from sqlalchemy import Text as JSON  # type: ignore[assignment]


class ApprovalStatus(enum.Enum):
	"""
	Possible states for an approval workflow record.

	DRAFT        – initial state before workflow is started
	PENDING      – submitted, awaiting first reviewer pickup
	IN_PROGRESS  – actively moving through workflow steps
	APPROVED     – all steps passed
	REJECTED     – rejected at any step
	CANCELLED    – cancelled by creator or admin before completion
	ON_HOLD      – temporarily paused at current step
	"""
	DRAFT = "Draft"
	PENDING = "Pending"
	IN_PROGRESS = "In Progress"
	APPROVED = "Approved"
	REJECTED = "Rejected"
	CANCELLED = "Cancelled"
	ON_HOLD = "On Hold"


class ApprovalWorkflowMixin:
	"""
	Mixin that adds multi-step, role-gated approval workflow to a FAB model.

	Subclasses MUST define:

	  __approval_workflow__: dict
	    {
	      'start': 'first_step_name',
	      'steps': {
	          'step_name': 'next_step_name'  # simple linear
	          OR
	          'step_name': {                  # conditional branching
	              'python_expression': 'next_step_name',
	              ...
	          }
	          OR
	          'step_name': None               # terminal step
	      }
	    }

	  __approval_roles__: dict[str, str]
	    Maps each step name to the FAB role name required to act on it.
	    {'step_name': 'RoleName'}

	Optional class attributes:

	  __timeout_config__: dict[str, int]
	    Per-step timeout in hours.  {'step_name': 48}

	  __auto_actions__: dict[str, str]
	    Action taken on timeout: 'approve' | 'reject' | 'escalate'.
	    {'step_name': 'escalate'}
	"""

	# ------------------------------------------------------------------
	# Declared columns
	# ------------------------------------------------------------------

	@declared_attr
	def approval_status(cls) -> Column:
		return Column(
			"approval_status",
			Enum(ApprovalStatus, name="approval_status_enum"),
			default=ApprovalStatus.DRAFT,
			nullable=False,
			index=True,
			comment="Current status in approval workflow",
		)

	@declared_attr
	def current_step(cls) -> Column:
		return Column(
			"current_step",
			String(100),
			nullable=True,
			index=True,
			comment="Current step name in approval workflow",
		)

	@declared_attr
	def approval_history(cls) -> Column:
		return Column(
			"approval_history",
			MutableDict.as_mutable(JSON),
			default=dict,
			nullable=False,
			comment="JSON history of all approval workflow actions",
		)

	@declared_attr
	def last_action_date(cls) -> Column:
		return Column(
			"last_action_date",
			DateTime,
			default=datetime.utcnow,
			onupdate=datetime.utcnow,
			nullable=False,
			index=True,
		)

	@declared_attr
	def created_by_id(cls) -> Column:
		return Column(
			Integer,
			ForeignKey("ab_user.id"),
			nullable=False,
			index=True,
		)

	@declared_attr
	def created_by(cls):
		return relationship(
			"User",
			foreign_keys=[cls.created_by_id],
			backref=f"{cls.__name__.lower()}_created",
		)

	# ------------------------------------------------------------------
	# Declaration-time validation
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Validate required class attributes when SQLAlchemy finalises the mapper."""
		if not hasattr(cls, "__approval_workflow__"):
			raise ValueError(f"__approval_workflow__ must be defined on {cls.__name__}")
		if not hasattr(cls, "__approval_roles__"):
			raise ValueError(f"__approval_roles__ must be defined on {cls.__name__}")

		wf = cls.__approval_workflow__
		if "start" not in wf:
			raise ValueError(f"{cls.__name__}.__approval_workflow__ must define 'start'")
		if "steps" not in wf:
			raise ValueError(f"{cls.__name__}.__approval_workflow__ must define 'steps'")

		for step in wf["steps"]:
			if step not in cls.__approval_roles__:
				raise ValueError(
					f"{cls.__name__}.__approval_roles__ missing mapping for step '{step}'"
				)

	# ------------------------------------------------------------------
	# Public lifecycle API
	# ------------------------------------------------------------------

	def initiate_approval_process(self) -> None:
		"""
		Transition from DRAFT → IN_PROGRESS and set the first step.

		Raises:
		    RuntimeError: Instance has not been flushed/saved yet (no id).
		    ValueError:   Workflow already initiated.
		"""
		if not self.id:
			raise RuntimeError("Instance must be saved before initiating approval")
		if self.approval_status != ApprovalStatus.DRAFT:
			raise ValueError(
				f"Approval process already initiated (status={self.approval_status.value})"
			)

		self.approval_status = ApprovalStatus.IN_PROGRESS
		self.current_step = self.__approval_workflow__["start"]
		self.approval_history = {}
		self.last_action_date = datetime.utcnow()

		self._db_commit("initiate approval")

	def approve_step(self, user: Any, comment: str = "") -> bool:
		"""
		Approve the current workflow step.

		Advances to the next step (or marks APPROVED if terminal).

		Args:
		    user:    FAB User instance performing the approval.
		    comment: Optional free-text comment recorded in history.

		Returns:
		    True on success.

		Raises:
		    ValueError:   Unauthorised user or invalid workflow state.
		    RuntimeError: Database commit failure.
		"""
		self._assert_user(user)
		self._assert_actionable_status()
		self._assert_can_approve(user)

		self._record_approval(user, comment)
		next_step = self._get_next_step()

		if next_step:
			self.current_step = next_step
			self.approval_status = ApprovalStatus.IN_PROGRESS
		else:
			self.current_step = None
			self.approval_status = ApprovalStatus.APPROVED

		self.last_action_date = datetime.utcnow()
		self._db_commit("approve step")
		return True

	def reject_step(self, user: Any, reason: str) -> bool:
		"""
		Reject the current workflow step, terminating the workflow.

		Args:
		    user:   FAB User instance performing the rejection.
		    reason: Required reason string recorded in history.

		Returns:
		    True on success.

		Raises:
		    ValueError:   Missing reason, unauthorised, or invalid state.
		    RuntimeError: Database commit failure.
		"""
		self._assert_user(user)
		if not reason or not reason.strip():
			raise ValueError("Reason is required for rejection")
		self._assert_actionable_status()
		self._assert_can_approve(user)

		self._record_rejection(user, reason)
		self.current_step = None
		self.approval_status = ApprovalStatus.REJECTED
		self.last_action_date = datetime.utcnow()
		self._db_commit("reject step")
		return True

	def cancel_workflow(self, user: Any, reason: str) -> None:
		"""
		Cancel the workflow before it completes (creator or Admin only).

		Args:
		    user:   FAB User performing the cancellation.
		    reason: Required reason string.

		Raises:
		    ValueError: Unauthorised or workflow already terminal.
		"""
		if not self._can_cancel(user):
			raise ValueError("User not authorised to cancel workflow")
		if self.approval_status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
			raise ValueError("Cannot cancel an already-completed workflow")
		if not reason or not reason.strip():
			raise ValueError("Reason is required for cancellation")

		self.approval_status = ApprovalStatus.CANCELLED
		self.current_step = None
		self._record_cancellation(user, reason)
		self.last_action_date = datetime.utcnow()
		self._db_commit("cancel workflow")

	def put_on_hold(self, user: Any, reason: str) -> None:
		"""
		Pause an IN_PROGRESS workflow at the current step.

		Args:
		    user:   FAB User authorised for the current step.
		    reason: Required reason string.

		Raises:
		    ValueError: Unauthorised or workflow not in progress.
		"""
		self._assert_can_approve(user)
		if self.approval_status != ApprovalStatus.IN_PROGRESS:
			raise ValueError("Can only hold workflows that are IN_PROGRESS")
		if not reason or not reason.strip():
			raise ValueError("Reason is required to put workflow on hold")

		self.approval_status = ApprovalStatus.ON_HOLD
		self._record_hold(user, reason)
		self.last_action_date = datetime.utcnow()
		self._db_commit("put on hold")

	def resume_workflow(self, user: Any, comment: str = "") -> None:
		"""
		Resume a workflow that was put ON_HOLD.

		Args:
		    user:    FAB User authorised for the current step.
		    comment: Optional comment.

		Raises:
		    ValueError: Unauthorised or workflow not on hold.
		"""
		self._assert_can_approve(user)
		if self.approval_status != ApprovalStatus.ON_HOLD:
			raise ValueError("Can only resume workflows that are ON_HOLD")

		self.approval_status = ApprovalStatus.IN_PROGRESS
		self._record_resume(user, comment)
		self.last_action_date = datetime.utcnow()
		self._db_commit("resume workflow")

	# ------------------------------------------------------------------
	# Timeout helpers
	# ------------------------------------------------------------------

	def is_step_overdue(self) -> bool:
		"""Return True if the current step has exceeded its configured timeout."""
		timeout_config: dict[str, int] = getattr(self, "__timeout_config__", {})
		if not self.current_step or self.current_step not in timeout_config:
			return False
		timeout_hours: int = timeout_config[self.current_step]
		deadline = self.last_action_date + timedelta(hours=timeout_hours)
		return datetime.utcnow() > deadline

	def handle_timeout(self, admin_user: Any) -> str | None:
		"""
		Execute the configured auto-action for an overdue step.

		Args:
		    admin_user: User object used to record the automated action.

		Returns:
		    The action taken ('approve', 'reject', 'escalate') or None.
		"""
		if not self.is_step_overdue():
			return None

		auto_actions: dict[str, str] = getattr(self, "__auto_actions__", {})
		action = auto_actions.get(self.current_step)

		if action == "approve":
			self._record_approval(admin_user, "Auto-approved: step timeout exceeded")
			next_step = self._get_next_step()
			if next_step:
				self.current_step = next_step
				self.approval_status = ApprovalStatus.IN_PROGRESS
			else:
				self.current_step = None
				self.approval_status = ApprovalStatus.APPROVED
			self.last_action_date = datetime.utcnow()
			self._db_commit("timeout auto-approve")

		elif action == "reject":
			self._record_rejection(admin_user, "Auto-rejected: step timeout exceeded")
			self.current_step = None
			self.approval_status = ApprovalStatus.REJECTED
			self.last_action_date = datetime.utcnow()
			self._db_commit("timeout auto-reject")

		elif action == "escalate":
			# Record escalation event; actual routing is application-specific
			step_key = f"{self.current_step}_escalation"
			if self.approval_history is None:
				self.approval_history = {}
			self.approval_history[step_key] = {
				"status": "escalated",
				"user_id": getattr(admin_user, "id", None),
				"username": getattr(admin_user, "username", "system"),
				"timestamp": datetime.utcnow().isoformat(),
				"reason": "Step timeout exceeded",
			}
			self.last_action_date = datetime.utcnow()
			self._db_commit("timeout escalate")

		return action

	# ------------------------------------------------------------------
	# Status / reporting API
	# ------------------------------------------------------------------

	def get_approval_status(self) -> dict[str, Any]:
		"""
		Return a serialisable snapshot of the current workflow state.

		Returns:
		    dict with keys: status, current_step, last_action, history,
		    created_by, is_overdue.
		"""
		return {
			"status": self.approval_status.value,
			"current_step": self.current_step,
			"last_action": self.last_action_date.isoformat() if self.last_action_date else None,
			"history": self.approval_history or {},
			"created_by": {
				"id": self.created_by_id,
				"username": getattr(self.created_by, "username", None),
			},
			"is_overdue": self.is_step_overdue(),
		}

	@classmethod
	def get_pending_approvals(cls, user: Any) -> list[Any]:
		"""
		Return all instances where the given user can act on the current step.

		Args:
		    user: FAB User whose roles are checked against step requirements.

		Returns:
		    List of model instances awaiting action by this user.
		"""
		if not user or not hasattr(user, "roles"):
			return []

		user_roles: set[str] = {role.name for role in user.roles}

		from sqlalchemy import select
		stmt = select(cls).where(
			cls.approval_status.in_([ApprovalStatus.IN_PROGRESS, ApprovalStatus.PENDING])
		)
		rows = current_app.db.session.execute(stmt).scalars().all()

		return [
			inst for inst in rows
			if cls.__approval_roles__.get(inst.current_step) in user_roles
		]

	@classmethod
	def get_approval_metrics(
		cls,
		start_date: datetime | None = None,
		end_date: datetime | None = None,
	) -> dict[str, Any]:
		"""
		Compute workflow metrics over an optional date window.

		Args:
		    start_date: Inclusive lower bound on last_action_date.
		    end_date:   Inclusive upper bound on last_action_date.

		Returns:
		    dict with total count, per-status counts, and average duration
		    (seconds) for completed workflows.
		"""
		from sqlalchemy import select
		stmt = select(cls)
		if start_date:
			stmt = stmt.where(cls.last_action_date >= start_date)
		if end_date:
			stmt = stmt.where(cls.last_action_date <= end_date)

		results = current_app.db.session.execute(stmt).scalars().all()

		status_counts: dict[str, int] = {s.value: 0 for s in ApprovalStatus}
		for row in results:
			status_counts[row.approval_status.value] += 1

		durations: list[float] = []
		for row in results:
			if row.approval_status not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
				continue
			history = row.approval_history or {}
			if len(history) < 2:
				continue
			try:
				timestamps = [
					datetime.fromisoformat(entry["timestamp"])
					for entry in history.values()
					if isinstance(entry, dict) and "timestamp" in entry
				]
				if len(timestamps) >= 2:
					durations.append((max(timestamps) - min(timestamps)).total_seconds())
			except (KeyError, ValueError):
				pass

		avg_duration = sum(durations) / len(durations) if durations else None

		return {
			"total": len(results),
			"status_counts": status_counts,
			"avg_duration_seconds": avg_duration,
		}

	# ------------------------------------------------------------------
	# Internal authorisation helpers
	# ------------------------------------------------------------------

	def _can_approve(self, user: Any) -> bool:
		"""Return True if user holds the role required for the current step."""
		if not user or not hasattr(user, "roles"):
			return False
		required_role = self.__approval_roles__.get(self.current_step)
		if not required_role:
			return False
		return required_role in {role.name for role in user.roles}

	def _can_cancel(self, user: Any) -> bool:
		"""Return True if user is the creator or holds the configured admin role."""
		if user.id == self.created_by_id:
			return True
		admin_role: str = current_app.config.get("APPROVAL_ADMIN_ROLE", "Admin")
		return admin_role in {role.name for role in user.roles}

	# ------------------------------------------------------------------
	# Internal assertion helpers
	# ------------------------------------------------------------------

	def _assert_user(self, user: Any) -> None:
		if not user or not getattr(user, "id", None):
			raise ValueError("Valid authenticated user is required")

	def _assert_actionable_status(self) -> None:
		if self.approval_status not in (ApprovalStatus.IN_PROGRESS, ApprovalStatus.PENDING):
			raise ValueError(
				f"Cannot act on workflow in status '{self.approval_status.value}'"
			)

	def _assert_can_approve(self, user: Any) -> None:
		if not self._can_approve(user):
			raise ValueError(
				f"User '{getattr(user, 'username', user)}' is not authorised "
				f"for step '{self.current_step}'"
			)

	# ------------------------------------------------------------------
	# Internal history recorders
	# ------------------------------------------------------------------

	def _history_entry(self, user: Any, status: str, **extra: Any) -> dict[str, Any]:
		return {
			"status": status,
			"user_id": user.id,
			"username": getattr(user, "username", str(user.id)),
			"timestamp": datetime.utcnow().isoformat(),
			**extra,
		}

	def _ensure_history(self) -> None:
		if self.approval_history is None:
			self.approval_history = {}

	def _record_approval(self, user: Any, comment: str) -> None:
		self._ensure_history()
		self.approval_history[self.current_step] = self._history_entry(
			user, "approved", comment=comment or ""
		)

	def _record_rejection(self, user: Any, reason: str) -> None:
		self._ensure_history()
		self.approval_history[self.current_step] = self._history_entry(
			user, "rejected", reason=reason
		)

	def _record_cancellation(self, user: Any, reason: str) -> None:
		self._ensure_history()
		self.approval_history["cancelled"] = self._history_entry(
			user, "cancelled", reason=reason
		)

	def _record_hold(self, user: Any, reason: str) -> None:
		self._ensure_history()
		key = f"{self.current_step}_hold"
		self.approval_history[key] = self._history_entry(user, "on_hold", reason=reason)

	def _record_resume(self, user: Any, comment: str) -> None:
		self._ensure_history()
		key = f"{self.current_step}_resume"
		self.approval_history[key] = self._history_entry(
			user, "resumed", comment=comment or ""
		)

	# ------------------------------------------------------------------
	# Workflow step routing
	# ------------------------------------------------------------------

	def _get_next_step(self) -> str | None:
		"""
		Resolve the next workflow step from __approval_workflow__['steps'].

		Handles three forms:
		  - None       → terminal step, workflow ends
		  - str        → unconditional next step
		  - dict       → evaluated condition dict; first truthy key wins
		"""
		step_config = self.__approval_workflow__["steps"].get(self.current_step)

		if step_config is None:
			return None

		if isinstance(step_config, str):
			return step_config

		if isinstance(step_config, dict):
			for condition, next_step in step_config.items():
				try:
					if self._evaluate_condition(condition):
						return next_step
				except Exception as exc:
					log.error(
						"Error evaluating workflow condition '%s' on %s pk=%s: %s",
						condition,
						type(self).__name__,
						getattr(self, "id", "?"),
						exc,
					)

		return None

	def _evaluate_condition(self, condition: str) -> bool:
		"""
		Evaluate a workflow branch condition expression.

		The expression runs in a restricted namespace containing only:
		  - self      → the model instance
		  - datetime  → datetime class
		  - timedelta → timedelta class

		Args:
		    condition: Python expression string.

		Returns:
		    bool result of the expression.

		Raises:
		    ValueError: Expression is syntactically or semantically invalid.
		"""
		safe_globals: dict[str, Any] = {"__builtins__": {}}
		safe_locals: dict[str, Any] = {
			"self": self,
			"datetime": datetime,
			"timedelta": timedelta,
		}
		try:
			return bool(eval(condition, safe_globals, safe_locals))  # noqa: S307
		except Exception as exc:
			raise ValueError(
				f"Invalid workflow condition '{condition}': {exc}"
			) from exc

	# ------------------------------------------------------------------
	# Database helper
	# ------------------------------------------------------------------

	def _db_commit(self, operation: str) -> None:
		"""Commit the current session, rolling back and re-raising on failure."""
		try:
			current_app.db.session.commit()
		except Exception as exc:
			current_app.db.session.rollback()
			raise RuntimeError(
				f"Database error during '{operation}': {exc}"
			) from exc
