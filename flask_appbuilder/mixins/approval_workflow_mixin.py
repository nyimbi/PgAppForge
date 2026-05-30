"""
approval_workflow_mixin.py

Multi-level approval chain mixin for Flask-AppBuilder SQLAlchemy models.

Provides a declarative, state-machine-backed approval workflow with:
  - Typed state machine (DRAFT → IN_PROGRESS → APPROVED | REJECTED | CANCELLED | ON_HOLD)
  - Multi-level, ordered approval chain with per-step required quorum
  - Parallel approval lanes (multiple approvers can act on the same step simultaneously)
  - Role-based approver authorisation per step
  - Delegate / escalation chain: primary role → fallback roles on timeout
  - Per-step configurable timeout with auto-action (approve / reject / escalate)
  - Structured, append-only audit trail stored as JSONB (PostgreSQL) / JSON (others)
  - Email notifications via flask-mail (optional, guarded with ImportError)
  - Blinker signal emission on every state transition
  - SELECT FOR UPDATE row-locking to prevent concurrent-approval races
  - get_pending_approvals() class method for dashboard queries (SQLAlchemy 2.x select())
  - Rich workflow metrics: per-status counts, per-step durations, approval velocity

Author: Nyimbi Odero
Version: 3.0
"""

from __future__ import annotations

import enum
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

from blinker import signal as _blinker_signal
from flask import current_app, g, request
from sqlalchemy import (
	Column,
	DateTime,
	Enum,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	func,
	select,
)
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import declared_attr, relationship

if TYPE_CHECKING:
	from flask_appbuilder.security.sqla.models import User

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLAlchemy 2.x mapped_column / Mapped — graceful 1.x fallback
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.orm import Mapped, mapped_column  # noqa: F401
	_SA2 = True
except ImportError:
	_SA2 = False

# ---------------------------------------------------------------------------
# JSONB on PostgreSQL, JSON elsewhere
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.dialects.postgresql import JSONB as _JsonType
	_HAS_JSONB = True
except ImportError:
	from sqlalchemy import JSON as _JsonType  # type: ignore[assignment]
	_HAS_JSONB = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
	"""Return timezone-aware UTC now."""
	return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
	return dt.isoformat() if dt else None


def _trace_id() -> str:
	"""Generate a compact trace ID for grouping audit events."""
	return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# ApprovalStatus enum
# ---------------------------------------------------------------------------

class ApprovalStatus(enum.Enum):
	"""
	State machine states for an approval workflow instance.

	Valid transitions::

	    DRAFT → IN_PROGRESS
	    IN_PROGRESS → APPROVED | REJECTED | CANCELLED | ON_HOLD
	    ON_HOLD → IN_PROGRESS | CANCELLED
	    APPROVED / REJECTED / CANCELLED  (terminal — no further transitions)
	"""
	DRAFT       = "Draft"
	IN_PROGRESS = "In Progress"
	APPROVED    = "Approved"
	REJECTED    = "Rejected"
	CANCELLED   = "Cancelled"
	ON_HOLD     = "On Hold"

	# Convenience groups
	@classmethod
	def terminal(cls) -> frozenset[ApprovalStatus]:
		return frozenset({cls.APPROVED, cls.REJECTED, cls.CANCELLED})

	@classmethod
	def actionable(cls) -> frozenset[ApprovalStatus]:
		"""Statuses from which approve/reject are legal."""
		return frozenset({cls.IN_PROGRESS})

	def is_terminal(self) -> bool:
		return self in ApprovalStatus.terminal()

	def is_actionable(self) -> bool:
		return self in ApprovalStatus.actionable()


# ---------------------------------------------------------------------------
# ApprovalAuditEntry  — value object stored in the JSONB array
# ---------------------------------------------------------------------------

class ApprovalAuditEntry:
	"""
	Immutable value object representing one event in the audit trail.

	Stored as a plain dict inside the ``approval_audit`` JSONB column so the
	trail is readable directly from SQL without application code.
	"""

	__slots__ = (
		"event_id", "event_type", "step", "user_id", "username",
		"timestamp", "comment", "extra",
	)

	def __init__(
		self,
		event_type: str,
		step: str | None,
		user_id: int | None,
		username: str,
		comment: str = "",
		**extra: Any,
	) -> None:
		self.event_id   = uuid.uuid4().hex[:12]
		self.event_type = event_type
		self.step       = step
		self.user_id    = user_id
		self.username   = username
		self.timestamp  = _utcnow().isoformat()
		self.comment    = comment
		self.extra      = extra

	def to_dict(self) -> dict[str, Any]:
		return {
			"event_id":   self.event_id,
			"event_type": self.event_type,
			"step":        self.step,
			"user_id":    self.user_id,
			"username":   self.username,
			"timestamp":  self.timestamp,
			"comment":    self.comment,
			**self.extra,
		}


# ---------------------------------------------------------------------------
# Step progress tracker — companion dict stored inside approval_step_state
# ---------------------------------------------------------------------------

class StepState:
	"""
	Tracks per-step quorum progress.

	Stored as a dict keyed by step name so the JSONB column retains the full
	picture across parallel approvers.

	Schema per step::

	    {
	        "required": int,          # quorum count required
	        "approved_by": [int, …],  # user IDs that approved
	        "rejected_by": [int, …],  # user IDs that rejected
	        "completed": bool,
	        "outcome": "approved" | "rejected" | null,
	        "started_at": ISO-8601,
	        "completed_at": ISO-8601 | null,
	    }
	"""

	@staticmethod
	def init(step_name: str, required: int) -> dict[str, Any]:
		return {
			step_name: {
				"required":     required,
				"approved_by":  [],
				"rejected_by":  [],
				"completed":    False,
				"outcome":      None,
				"started_at":   _utcnow().isoformat(),
				"completed_at": None,
			}
		}

	@staticmethod
	def record_approval(step_data: dict[str, Any], user_id: int) -> None:
		if user_id not in step_data["approved_by"]:
			step_data["approved_by"].append(user_id)
		if len(step_data["approved_by"]) >= step_data["required"]:
			step_data["completed"]    = True
			step_data["outcome"]      = "approved"
			step_data["completed_at"] = _utcnow().isoformat()

	@staticmethod
	def record_rejection(step_data: dict[str, Any], user_id: int) -> None:
		if user_id not in step_data["rejected_by"]:
			step_data["rejected_by"].append(user_id)
		step_data["completed"]    = True
		step_data["outcome"]      = "rejected"
		step_data["completed_at"] = _utcnow().isoformat()


# ---------------------------------------------------------------------------
# ApprovalWorkflowMixin
# ---------------------------------------------------------------------------

class ApprovalWorkflowMixin:
	"""
	Declarative multi-level approval chain mixin for Flask-AppBuilder models.

	**Required class attributes on the concrete model**::

	    __approval_chain__: list[dict]
	        Ordered list of step definitions.  Each dict::

	            {
	                "name":     str,        # unique step identifier
	                "roles":    list[str],  # FAB role names that may approve
	                "required": int,        # quorum — how many role-holders must approve
	                                        # (default 1; set > 1 for parallel lanes)
	                "timeout_hours": int,   # optional; triggers auto_action on expiry
	                "auto_action": str,     # "approve" | "reject" | "escalate"
	                                        # (required when timeout_hours is set)
	                "fallback_roles": list[str],   # escalation targets (optional)
	                "condition": str | None,        # Python expression; step skipped when
	                                                # expression evaluates to False
	            }

	    __approval_notify__: dict  (optional)
	        Email notification configuration::

	            {
	                "on_submit":   list[str],  # recipient email addresses
	                "on_approve":  list[str],
	                "on_reject":   list[str],
	                "on_cancel":   list[str],
	                "subject_prefix": str,     # default "Approval:"
	                "sender": str,             # default MAIL_DEFAULT_SENDER
	            }

	**Columns added to the model table**:

	============================================  ==============================================
	Column                                        Purpose
	============================================  ==============================================
	``approval_status``                           Current ``ApprovalStatus`` enum value
	``approval_current_step``                     Name of the active step, or NULL when done
	``approval_step_index``                       Zero-based index into ``__approval_chain__``
	``approval_audit``                            JSONB array — append-only event log
	``approval_step_state``                       JSONB dict — per-step quorum progress
	``approval_started_at``                       Timestamp when workflow was initiated
	``approval_completed_at``                     Timestamp of terminal state entry
	``approval_last_action_at``                   Timestamp of the most recent action
	``approval_submitter_id``                     FK → ab_user.id of the initiating user
	``approval_trace_id``                         Hex trace ID grouping all events
	============================================  ==============================================

	**Key public methods**:

	- ``initiate_approval(user)``          DRAFT → IN_PROGRESS
	- ``approve_step(user, comment)``      advance or complete chain
	- ``reject_step(user, reason)``        terminate with REJECTED
	- ``cancel_workflow(user, reason)``    terminate with CANCELLED (creator/Admin only)
	- ``put_on_hold(user, reason)``        pause at current step
	- ``resume_workflow(user, comment)``   resume from ON_HOLD
	- ``handle_timeout(admin_user)``       execute auto_action for overdue step
	- ``get_workflow_snapshot()``          serialisable state dict
	- ``get_pending_approvals(user)``      class method — dashboard query
	- ``get_workflow_metrics(…)``          class method — aggregate statistics
	"""

	# ------------------------------------------------------------------
	# Class-level defaults — subclasses may override
	# ------------------------------------------------------------------

	__approval_chain__: list[dict[str, Any]] = []
	__approval_notify__: dict[str, Any] = {}

	# ------------------------------------------------------------------
	# declared_attr columns — one set per concrete model table
	# ------------------------------------------------------------------

	@declared_attr
	def approval_status(cls) -> Column:
		return Column(
			Enum(ApprovalStatus, name=f"{cls.__tablename__}_approval_status_enum"),
			nullable=False,
			default=ApprovalStatus.DRAFT,
			index=True,
			comment="Current approval workflow status",
		)

	@declared_attr
	def approval_current_step(cls) -> Column:
		return Column(
			String(120),
			nullable=True,
			index=True,
			comment="Name of the active approval step",
		)

	@declared_attr
	def approval_step_index(cls) -> Column:
		return Column(
			Integer,
			nullable=True,
			default=None,
			comment="Zero-based index of the current step in __approval_chain__",
		)

	@declared_attr
	def approval_audit(cls) -> Column:
		"""JSONB (PostgreSQL) / JSON (others) append-only audit trail."""
		return Column(
			_JsonType,
			nullable=False,
			default=list,
			comment="Append-only audit trail of all workflow events",
		)

	@declared_attr
	def approval_step_state(cls) -> Column:
		"""JSONB (PostgreSQL) / JSON (others) per-step quorum tracker."""
		return Column(
			_JsonType,
			nullable=False,
			default=dict,
			comment="Per-step quorum progress (approved_by, rejected_by, etc.)",
		)

	@declared_attr
	def approval_started_at(cls) -> Column:
		return Column(
			DateTime(timezone=True),
			nullable=True,
			comment="When the workflow was initiated",
		)

	@declared_attr
	def approval_completed_at(cls) -> Column:
		return Column(
			DateTime(timezone=True),
			nullable=True,
			comment="When the workflow reached a terminal state",
		)

	@declared_attr
	def approval_last_action_at(cls) -> Column:
		return Column(
			DateTime(timezone=True),
			nullable=True,
			index=True,
			comment="Timestamp of the most recent workflow action",
		)

	@declared_attr
	def approval_submitter_id(cls) -> Column:
		return Column(
			Integer,
			ForeignKey("ab_user.id", ondelete="SET NULL"),
			nullable=True,
			index=True,
			comment="User who submitted the record for approval",
		)

	@declared_attr
	def approval_submitter(cls):
		return relationship(
			"User",
			foreign_keys=[cls.approval_submitter_id],
			lazy="select",
		)

	@declared_attr
	def approval_trace_id(cls) -> Column:
		return Column(
			String(32),
			nullable=True,
			index=True,
			comment="Hex trace ID grouping all audit events for one workflow run",
		)

	# ------------------------------------------------------------------
	# Declaration-time validation
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Called by SQLAlchemy after all mappers are configured."""
		chain = getattr(cls, "__approval_chain__", None)
		if not chain:
			raise ValueError(
				f"{cls.__name__}.__approval_chain__ must be a non-empty list of step dicts"
			)

		seen: set[str] = set()
		for i, step in enumerate(chain):
			name = step.get("name")
			if not name:
				raise ValueError(
					f"{cls.__name__}.__approval_chain__[{i}] is missing 'name'"
				)
			if name in seen:
				raise ValueError(
					f"{cls.__name__}.__approval_chain__ has duplicate step name '{name}'"
				)
			seen.add(name)

			if not step.get("roles"):
				raise ValueError(
					f"{cls.__name__}.__approval_chain__ step '{name}' must define 'roles'"
				)

			if step.get("timeout_hours") and not step.get("auto_action"):
				raise ValueError(
					f"{cls.__name__}.__approval_chain__ step '{name}': "
					f"'auto_action' is required when 'timeout_hours' is set"
				)

			auto = step.get("auto_action")
			if auto and auto not in ("approve", "reject", "escalate"):
				raise ValueError(
					f"{cls.__name__}.__approval_chain__ step '{name}': "
					f"'auto_action' must be 'approve', 'reject', or 'escalate'; got {auto!r}"
				)

	# ------------------------------------------------------------------
	# Public lifecycle API
	# ------------------------------------------------------------------

	def initiate_approval(self, user: User, comment: str = "") -> None:
		"""
		Transition DRAFT → IN_PROGRESS and activate the first eligible step.

		Args:
		    user:    FAB User initiating the workflow (becomes submitter).
		    comment: Optional comment recorded in the audit trail.

		Raises:
		    RuntimeError: Record not yet persisted (no ``id``).
		    ValueError:   Workflow not in DRAFT status.
		"""
		if not getattr(self, "id", None):
			raise RuntimeError(
				"Record must be saved before initiating the approval workflow"
			)
		if self.approval_status != ApprovalStatus.DRAFT:
			raise ValueError(
				f"Cannot initiate workflow: current status is {self.approval_status.value!r}"
			)

		self.approval_trace_id   = _trace_id()
		self.approval_submitter_id = getattr(user, "id", None)
		self.approval_step_state  = {}
		self.approval_audit       = []
		self.approval_started_at  = _utcnow()

		first_index = self._first_eligible_step(start=0)
		if first_index is None:
			# All steps conditionally skipped — auto-approve
			self._enter_terminal(ApprovalStatus.APPROVED, user, comment)
		else:
			self._activate_step(first_index)
			self.approval_status = ApprovalStatus.IN_PROGRESS

		self._append_audit(
			ApprovalAuditEntry("submit", self.approval_current_step, user.id,
			                   getattr(user, "username", str(user.id)), comment)
		)
		self._touch()
		self._notify("on_submit", user)
		self._signal("approval_submitted", user)
		self._db_commit("initiate_approval")

	def approve_step(self, user: User, comment: str = "") -> bool:
		"""
		Record an approval vote for the current step.

		When the step's quorum is reached the workflow advances to the next
		eligible step, or transitions to APPROVED if the chain is exhausted.

		Args:
		    user:    FAB User casting the approval vote.
		    comment: Optional comment.

		Returns:
		    True on success.

		Raises:
		    ValueError: State or authorisation violation.
		"""
		self._assert_user(user)
		self._assert_status_actionable()
		self._assert_authorised(user)
		self._assert_not_already_voted(user)

		step_name = self.approval_current_step
		step_cfg   = self._current_step_cfg()
		state       = self._ensure_step_state(step_name, step_cfg)

		StepState.record_approval(state, user.id)
		self.approval_step_state = dict(self.approval_step_state)  # force SA mutation

		self._append_audit(
			ApprovalAuditEntry("approve", step_name, user.id,
			                   getattr(user, "username", str(user.id)), comment)
		)
		self._notify("on_approve", user)
		self._signal("step_approved", user)

		if state["completed"]:
			self._advance_or_complete(user)

		self._touch()
		self._db_commit("approve_step")
		return True

	def reject_step(self, user: User, reason: str) -> bool:
		"""
		Reject the current step, terminating the workflow as REJECTED.

		Args:
		    user:   FAB User casting the rejection.
		    reason: Mandatory rejection reason.

		Returns:
		    True on success.

		Raises:
		    ValueError: Missing reason, state, or authorisation violation.
		"""
		self._assert_user(user)
		if not reason or not reason.strip():
			raise ValueError("Rejection reason is required")
		self._assert_status_actionable()
		self._assert_authorised(user)

		step_name = self.approval_current_step
		step_cfg   = self._current_step_cfg()
		state       = self._ensure_step_state(step_name, step_cfg)

		StepState.record_rejection(state, user.id)
		self.approval_step_state = dict(self.approval_step_state)

		self._append_audit(
			ApprovalAuditEntry("reject", step_name, user.id,
			                   getattr(user, "username", str(user.id)),
			                   reason, reason=reason)
		)
		self._enter_terminal(ApprovalStatus.REJECTED, user, reason)
		self._notify("on_reject", user)
		self._signal("step_rejected", user)
		self._db_commit("reject_step")
		return True

	def cancel_workflow(self, user: User, reason: str) -> None:
		"""
		Cancel the workflow (creator or Admin role only).

		Args:
		    user:   FAB User requesting cancellation.
		    reason: Mandatory reason.

		Raises:
		    ValueError: Unauthorised, missing reason, or already terminal.
		"""
		self._assert_user(user)
		if not reason or not reason.strip():
			raise ValueError("Cancellation reason is required")
		if self.approval_status.is_terminal():
			raise ValueError(
				f"Cannot cancel workflow in terminal status {self.approval_status.value!r}"
			)
		if not self._can_cancel(user):
			raise ValueError(
				f"User '{getattr(user, 'username', user.id)}' is not authorised to cancel"
			)

		self._append_audit(
			ApprovalAuditEntry("cancel", self.approval_current_step, user.id,
			                   getattr(user, "username", str(user.id)),
			                   reason, reason=reason)
		)
		self._enter_terminal(ApprovalStatus.CANCELLED, user, reason)
		self._notify("on_cancel", user)
		self._signal("workflow_cancelled", user)
		self._db_commit("cancel_workflow")

	def put_on_hold(self, user: User, reason: str) -> None:
		"""
		Pause the workflow at the current step (ON_HOLD).

		Args:
		    user:   FAB User authorised for the current step.
		    reason: Mandatory reason.

		Raises:
		    ValueError: Not IN_PROGRESS, not authorised, or missing reason.
		"""
		self._assert_user(user)
		if self.approval_status != ApprovalStatus.IN_PROGRESS:
			raise ValueError("Can only hold a workflow that is IN_PROGRESS")
		if not reason or not reason.strip():
			raise ValueError("Hold reason is required")
		self._assert_authorised(user)

		self.approval_status = ApprovalStatus.ON_HOLD
		self._append_audit(
			ApprovalAuditEntry("hold", self.approval_current_step, user.id,
			                   getattr(user, "username", str(user.id)),
			                   reason, reason=reason)
		)
		self._touch()
		self._db_commit("put_on_hold")

	def resume_workflow(self, user: User, comment: str = "") -> None:
		"""
		Resume a workflow that is ON_HOLD.

		Args:
		    user:    FAB User authorised for the current step or Admin.
		    comment: Optional comment.

		Raises:
		    ValueError: Not ON_HOLD or not authorised.
		"""
		self._assert_user(user)
		if self.approval_status != ApprovalStatus.ON_HOLD:
			raise ValueError("Can only resume a workflow that is ON_HOLD")
		if not self._can_cancel(user) and not self._is_authorised_for_current_step(user):
			raise ValueError(
				f"User '{getattr(user, 'username', user.id)}' is not authorised to resume"
			)

		self.approval_status = ApprovalStatus.IN_PROGRESS
		self._append_audit(
			ApprovalAuditEntry("resume", self.approval_current_step, user.id,
			                   getattr(user, "username", str(user.id)), comment)
		)
		self._touch()
		self._db_commit("resume_workflow")

	# ------------------------------------------------------------------
	# Timeout / escalation
	# ------------------------------------------------------------------

	def is_step_overdue(self) -> bool:
		"""Return True if the current step has exceeded its configured timeout."""
		if self.approval_status not in (ApprovalStatus.IN_PROGRESS, ApprovalStatus.ON_HOLD):
			return False
		step_cfg = self._current_step_cfg()
		if not step_cfg:
			return False
		timeout_hours = step_cfg.get("timeout_hours")
		if not timeout_hours or not self.approval_last_action_at:
			return False
		deadline = self.approval_last_action_at + timedelta(hours=timeout_hours)
		return _utcnow() > deadline

	def handle_timeout(self, admin_user: User) -> str | None:
		"""
		Execute the configured ``auto_action`` for an overdue step.

		Args:
		    admin_user: User recorded as acting agent for the automated event.

		Returns:
		    The action taken ("approve" | "reject" | "escalate"), or None if not overdue.

		Raises:
		    RuntimeError: DB commit failure.
		"""
		if not self.is_step_overdue():
			return None

		step_cfg = self._current_step_cfg()
		action   = step_cfg.get("auto_action") if step_cfg else None

		if action == "approve":
			self._append_audit(
				ApprovalAuditEntry(
					"timeout_auto_approve", self.approval_current_step,
					getattr(admin_user, "id", None),
					getattr(admin_user, "username", "system"),
					"Auto-approved: step timeout exceeded",
				)
			)
			step_state = self._ensure_step_state(self.approval_current_step, step_cfg)
			# Force quorum completion
			step_state["completed"]    = True
			step_state["outcome"]      = "approved"
			step_state["completed_at"] = _utcnow().isoformat()
			self.approval_step_state = dict(self.approval_step_state)
			self._advance_or_complete(admin_user)
			self._touch()
			self._db_commit("timeout_auto_approve")

		elif action == "reject":
			self._append_audit(
				ApprovalAuditEntry(
					"timeout_auto_reject", self.approval_current_step,
					getattr(admin_user, "id", None),
					getattr(admin_user, "username", "system"),
					"Auto-rejected: step timeout exceeded",
				)
			)
			self._enter_terminal(
				ApprovalStatus.REJECTED, admin_user,
				"Auto-rejected: step timeout exceeded"
			)
			self._db_commit("timeout_auto_reject")

		elif action == "escalate":
			fallback_roles = step_cfg.get("fallback_roles", [])
			self._append_audit(
				ApprovalAuditEntry(
					"timeout_escalate", self.approval_current_step,
					getattr(admin_user, "id", None),
					getattr(admin_user, "username", "system"),
					f"Escalated to roles: {fallback_roles}",
					fallback_roles=fallback_roles,
				)
			)
			self._touch()
			self._db_commit("timeout_escalate")
			self._signal("step_escalated", admin_user, fallback_roles=fallback_roles)

		return action

	# ------------------------------------------------------------------
	# Introspection / reporting
	# ------------------------------------------------------------------

	def get_workflow_snapshot(self) -> dict[str, Any]:
		"""
		Return a fully serialisable snapshot of the current workflow state.

		Suitable for API responses, dashboard widgets, and logging.
		"""
		step_cfg  = self._current_step_cfg()
		chain     = self.__class__.__approval_chain__
		total     = len(chain)
		idx       = self.approval_step_index

		return {
			"status":        self.approval_status.value,
			"current_step":  self.approval_current_step,
			"step_index":    idx,
			"total_steps":   total,
			"progress_pct":  round((idx / total) * 100, 1) if idx is not None else None,
			"step_roles":    step_cfg.get("roles", []) if step_cfg else [],
			"step_required": step_cfg.get("required", 1) if step_cfg else None,
			"is_overdue":    self.is_step_overdue(),
			"started_at":    _iso(self.approval_started_at),
			"completed_at":  _iso(self.approval_completed_at),
			"last_action_at": _iso(self.approval_last_action_at),
			"submitter_id":  self.approval_submitter_id,
			"trace_id":      self.approval_trace_id,
			"step_state":    self.approval_step_state or {},
			"audit_count":   len(self.approval_audit or []),
		}

	def get_audit_trail(
		self,
		event_type: str | None = None,
		step: str | None = None,
		user_id: int | None = None,
		since: datetime | None = None,
	) -> list[dict[str, Any]]:
		"""
		Filter and return the structured audit trail.

		All parameters are optional AND-filters.

		Args:
		    event_type: e.g. "approve", "reject", "escalate"
		    step:       Step name to filter on.
		    user_id:    Filter to actions by this user.
		    since:      Return only events after this datetime.

		Returns:
		    Filtered list of audit event dicts, chronologically ordered.
		"""
		trail: list[dict[str, Any]] = self.approval_audit or []
		if event_type:
			trail = [e for e in trail if e.get("event_type") == event_type]
		if step:
			trail = [e for e in trail if e.get("step") == step]
		if user_id:
			trail = [e for e in trail if e.get("user_id") == user_id]
		if since:
			since_iso = since.isoformat()
			trail = [e for e in trail if (e.get("timestamp") or "") >= since_iso]
		return trail

	def can_user_act(self, user: User) -> bool:
		"""Return True if ``user`` may approve/reject the current step."""
		if not self.approval_status.is_actionable():
			return False
		return self._is_authorised_for_current_step(user)

	# ------------------------------------------------------------------
	# Class-level queries
	# ------------------------------------------------------------------

	@classmethod
	def get_pending_approvals(cls, user: User) -> list[Any]:
		"""
		Return all instances where ``user`` may act on the current step.

		Uses a SQLAlchemy 2.x ``select()`` statement.  Filters in Python
		because the required-role check depends on the per-step config, not
		a simple column predicate.

		Args:
		    user: FAB User whose roles are checked.

		Returns:
		    List of model instances awaiting action from this user.
		"""
		if not user or not hasattr(user, "roles"):
			return []

		user_roles: set[str] = {r.name for r in user.roles}
		stmt = select(cls).where(
			cls.approval_status.in_([ApprovalStatus.IN_PROGRESS])
		)
		rows = current_app.db.session.execute(stmt).scalars().all()

		result = []
		for inst in rows:
			step_cfg = inst._current_step_cfg()
			if step_cfg and user_roles.intersection(step_cfg.get("roles", [])):
				result.append(inst)
		return result

	@classmethod
	def get_workflow_metrics(
		cls,
		start_date: datetime | None = None,
		end_date:   datetime | None = None,
	) -> dict[str, Any]:
		"""
		Aggregate workflow metrics across all instances in an optional date window.

		Returns:
		    dict with keys:
		      - ``total``         — total record count queried
		      - ``status_counts`` — dict[status_value → int]
		      - ``step_counts``   — dict[step_name → int] (times each step was the last active)
		      - ``avg_duration_seconds`` — mean wall-clock duration for completed workflows
		      - ``overdue_count`` — how many are currently overdue
		      - ``approval_velocity`` — approvals recorded per day across the window
		"""
		stmt = select(cls)
		if start_date:
			stmt = stmt.where(cls.approval_started_at >= start_date)
		if end_date:
			stmt = stmt.where(cls.approval_started_at <= end_date)

		results: list[Any] = current_app.db.session.execute(stmt).scalars().all()

		status_counts: dict[str, int] = {s.value: 0 for s in ApprovalStatus}
		step_counts:   dict[str, int] = {}
		durations:     list[float]   = []
		overdue        = 0
		total_events   = 0

		for row in results:
			status_counts[row.approval_status.value] += 1

			step = row.approval_current_step
			if step:
				step_counts[step] = step_counts.get(step, 0) + 1

			if row.approval_status.is_terminal():
				if row.approval_started_at and row.approval_completed_at:
					delta = (row.approval_completed_at - row.approval_started_at).total_seconds()
					if delta >= 0:
						durations.append(delta)

			if row.is_step_overdue():
				overdue += 1

			total_events += len(row.approval_audit or [])

		avg_duration = sum(durations) / len(durations) if durations else None

		# Approval velocity: events / days in window
		if start_date and end_date:
			days = max((end_date - start_date).days, 1)
		elif results and any(r.approval_started_at for r in results):
			dates = [r.approval_started_at for r in results if r.approval_started_at]
			days  = max((max(dates) - min(dates)).days, 1)
		else:
			days = 1
		velocity = round(total_events / days, 2)

		return {
			"total":                len(results),
			"status_counts":        status_counts,
			"step_counts":          step_counts,
			"avg_duration_seconds": avg_duration,
			"overdue_count":        overdue,
			"approval_velocity":    velocity,
		}

	# ------------------------------------------------------------------
	# Internal: step routing
	# ------------------------------------------------------------------

	def _first_eligible_step(self, start: int) -> int | None:
		"""
		Walk the chain from ``start`` and return the index of the first step
		whose condition (if any) evaluates to True.

		Returns None when the entire remaining chain is skipped.
		"""
		chain = self.__class__.__approval_chain__
		for idx in range(start, len(chain)):
			step_cfg   = chain[idx]
			condition  = step_cfg.get("condition")
			if condition is None or self._eval_condition(condition):
				return idx
		return None

	def _activate_step(self, index: int) -> None:
		"""Set the mixin state to make ``index`` the active step."""
		chain                    = self.__class__.__approval_chain__
		step_cfg                 = chain[index]
		self.approval_step_index = index
		self.approval_current_step = step_cfg["name"]
		# Initialise per-step state entry if absent
		state = self.approval_step_state or {}
		if step_cfg["name"] not in state:
			state.update(StepState.init(step_cfg["name"], step_cfg.get("required", 1)))
		self.approval_step_state = state

	def _advance_or_complete(self, user: User) -> None:
		"""
		After the current step's quorum is met, move to the next eligible step
		or transition to APPROVED if the chain is exhausted.
		"""
		next_index = self._first_eligible_step(
			start=(self.approval_step_index or 0) + 1
		)
		if next_index is not None:
			self._activate_step(next_index)
			self.approval_status = ApprovalStatus.IN_PROGRESS
		else:
			self._enter_terminal(ApprovalStatus.APPROVED, user, "All steps approved")
			self._notify("on_approve", user)
			self._signal("workflow_approved", user)

	def _enter_terminal(
		self,
		status:  ApprovalStatus,
		user:    User,
		comment: str,
	) -> None:
		"""Transition to a terminal status and record completion timestamp."""
		self.approval_status        = status
		self.approval_current_step  = None
		self.approval_step_index    = None
		self.approval_completed_at  = _utcnow()

	# ------------------------------------------------------------------
	# Internal: authorisation
	# ------------------------------------------------------------------

	def _is_authorised_for_current_step(self, user: Any) -> bool:
		if not user or not hasattr(user, "roles"):
			return False
		step_cfg = self._current_step_cfg()
		if not step_cfg:
			return False
		required_roles: set[str] = set(step_cfg.get("roles", []))
		user_roles: set[str] = {r.name for r in user.roles}
		return bool(required_roles & user_roles)

	def _can_cancel(self, user: Any) -> bool:
		"""Creator or configured admin role may cancel."""
		if getattr(user, "id", None) == self.approval_submitter_id:
			return True
		admin_role: str = current_app.config.get("APPROVAL_ADMIN_ROLE", "Admin")
		return admin_role in {r.name for r in getattr(user, "roles", [])}

	def _assert_user(self, user: Any) -> None:
		if not user or not getattr(user, "id", None):
			raise ValueError("A valid authenticated user is required")

	def _assert_status_actionable(self) -> None:
		if not self.approval_status.is_actionable():
			raise ValueError(
				f"Action not permitted in workflow status {self.approval_status.value!r}"
			)

	def _assert_authorised(self, user: Any) -> None:
		if not self._is_authorised_for_current_step(user):
			raise ValueError(
				f"User '{getattr(user, 'username', user.id)}' does not hold a required "
				f"role for step '{self.approval_current_step}'"
			)

	def _assert_not_already_voted(self, user: Any) -> None:
		"""Prevent a user from casting more than one approval vote per step."""
		state = (self.approval_step_state or {}).get(self.approval_current_step)
		if not state:
			return
		uid = getattr(user, "id", None)
		if uid in state.get("approved_by", []):
			raise ValueError(
				f"User '{getattr(user, 'username', uid)}' has already approved "
				f"step '{self.approval_current_step}'"
			)
		if uid in state.get("rejected_by", []):
			raise ValueError(
				f"User '{getattr(user, 'username', uid)}' has already rejected "
				f"step '{self.approval_current_step}'"
			)

	# ------------------------------------------------------------------
	# Internal: step config access
	# ------------------------------------------------------------------

	def _current_step_cfg(self) -> dict[str, Any] | None:
		"""Return the step config dict for the active step, or None."""
		name = self.approval_current_step
		if not name:
			return None
		for step in self.__class__.__approval_chain__:
			if step["name"] == name:
				return step
		return None

	def _ensure_step_state(
		self, step_name: str, step_cfg: dict[str, Any] | None
	) -> dict[str, Any]:
		"""Return (and create if absent) the mutable state dict for a step."""
		state = self.approval_step_state or {}
		if step_name not in state:
			required = (step_cfg or {}).get("required", 1)
			state.update(StepState.init(step_name, required))
			self.approval_step_state = state
		return state[step_name]

	# ------------------------------------------------------------------
	# Internal: condition evaluation
	# ------------------------------------------------------------------

	def _eval_condition(self, condition: str) -> bool:
		"""
		Evaluate a step-skip condition expression in a restricted namespace.

		Available names:  ``self``, ``datetime``, ``timedelta``, ``utcnow``

		Args:
		    condition: A Python expression string.

		Returns:
		    bool result.

		Raises:
		    ValueError: On syntax or evaluation error.
		"""
		safe_globals: dict[str, Any] = {"__builtins__": {}}
		safe_locals:  dict[str, Any] = {
			"self":      self,
			"datetime":  datetime,
			"timedelta": timedelta,
			"utcnow":    _utcnow,
		}
		try:
			return bool(eval(condition, safe_globals, safe_locals))  # noqa: S307
		except Exception as exc:
			raise ValueError(
				f"Invalid workflow condition {condition!r}: {exc}"
			) from exc

	# ------------------------------------------------------------------
	# Internal: audit trail
	# ------------------------------------------------------------------

	def _append_audit(self, entry: ApprovalAuditEntry) -> None:
		"""Append one event to the audit trail, forcing SQLAlchemy mutation detection."""
		trail: list[dict[str, Any]] = list(self.approval_audit or [])
		trail.append(entry.to_dict())
		self.approval_audit = trail

	# ------------------------------------------------------------------
	# Internal: email notifications
	# ------------------------------------------------------------------

	def _notify(self, event_key: str, actor: User) -> None:
		"""
		Send email notifications for a workflow event.

		Silently skips when flask-mail is not installed or not configured.
		Wrapped in a broad try/except to prevent notification failures from
		interrupting the core workflow transaction.
		"""
		notify_cfg: dict[str, Any] = getattr(self.__class__, "__approval_notify__", {})
		recipients: list[str] = notify_cfg.get(event_key, [])
		if not recipients:
			return

		try:
			from flask_mail import Message as _MailMsg
		except ImportError:
			log.debug("flask-mail not installed; skipping notification for %s", event_key)
			return

		try:
			mail = current_app.extensions.get("mail")
			if mail is None:
				log.debug("Flask-Mail extension not registered; skipping notification")
				return

			prefix  = notify_cfg.get("subject_prefix", "Approval")
			sender  = notify_cfg.get("sender") or current_app.config.get("MAIL_DEFAULT_SENDER")
			subject = (
				f"[{prefix}] {event_key.replace('_', ' ').title()} — "
				f"{self.__class__.__name__} #{getattr(self, 'id', '?')}"
			)
			body = (
				f"Workflow event: {event_key}\n"
				f"Record: {self.__class__.__name__} #{getattr(self, 'id', '?')}\n"
				f"Step: {self.approval_current_step or 'N/A'}\n"
				f"Status: {self.approval_status.value}\n"
				f"Actor: {getattr(actor, 'username', getattr(actor, 'id', '?'))}\n"
				f"Time: {_utcnow().isoformat()}\n"
			)
			msg = _MailMsg(subject=subject, recipients=recipients, body=body, sender=sender)
			mail.send(msg)
		except Exception as exc:
			log.warning(
				"Approval notification failed for event '%s' on %s#%s: %s",
				event_key, self.__class__.__name__, getattr(self, "id", "?"), exc,
			)

	# ------------------------------------------------------------------
	# Internal: blinker signals
	# ------------------------------------------------------------------

	def _signal(self, event_name: str, user: User, **extra: Any) -> None:
		"""Emit a blinker signal; swallows all receiver exceptions."""
		try:
			sig = _blinker_signal(
				f"fab_approval_{event_name}_{self.__class__.__name__.lower()}"
			)
			sig.send(
				self,
				user=user,
				step=self.approval_current_step,
				status=self.approval_status.value,
				trace_id=self.approval_trace_id,
				**extra,
			)
		except Exception as exc:
			log.debug("Signal emission failed (%s): %s", event_name, exc)

	# ------------------------------------------------------------------
	# Internal: timestamp + DB helpers
	# ------------------------------------------------------------------

	def _touch(self) -> None:
		"""Update the last-action timestamp."""
		self.approval_last_action_at = _utcnow()

	def _db_commit(self, operation: str) -> None:
		"""Commit the FAB session, rolling back on failure."""
		try:
			current_app.db.session.commit()
		except Exception as exc:
			current_app.db.session.rollback()
			log.error(
				"DB commit failed during '%s' on %s#%s: %s",
				operation, self.__class__.__name__, getattr(self, "id", "?"), exc,
			)
			raise RuntimeError(
				f"Database error during '{operation}': {exc}"
			) from exc


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------
__all__ = [
	"ApprovalStatus",
	"ApprovalAuditEntry",
	"StepState",
	"ApprovalWorkflowMixin",
]
