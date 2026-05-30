"""
workflow_mixin.py

Provides WorkflowMixin for state-machine workflow capabilities on SQLAlchemy models
in PgAppForge applications.

Supports:
- Declarative state/transition definitions via class attributes
- Guarded transitions with pre/post hooks via _on_transition_from_X_to_Y naming
- Full state-change history persisted to nx_workflow_state_history
- Workflow graph export as DOT string (graphviz optional) or adjacency dict
- SQLAlchemy 2.x (Mapped / mapped_column) with 1.x fallback

Author: Nyimbi Odero
Date: 2024-08-25 / modernised 2026-05-30
Version: 2.0
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

try:
	from sqlalchemy.orm import mapped_column, Mapped, relationship, declared_attr
	from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, event
	_SQLA2 = True
except ImportError:
	from sqlalchemy import Column as mapped_column, String, Integer, DateTime, ForeignKey, Text, event  # type: ignore[assignment]
	from sqlalchemy.orm import relationship, declared_attr  # type: ignore[assignment]
	_SQLA2 = False

from pgappforge import Model

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# History model
# ---------------------------------------------------------------------------

class WorkflowStateHistory(Model):
	"""Persisted record of every workflow state transition on any WorkflowMixin model."""

	__tablename__ = "nx_workflow_state_history"

	if _SQLA2:
		id: Mapped[int] = mapped_column(Integer, primary_key=True)
		model_type: Mapped[str] = mapped_column(String(100), nullable=False)
		model_id: Mapped[int] = mapped_column(Integer, nullable=False)
		old_state: Mapped[str] = mapped_column(String(50), nullable=False)
		new_state: Mapped[str] = mapped_column(String(50), nullable=False)
		user_id: Mapped[int | None] = mapped_column(
			Integer, ForeignKey("ab_user.id"), nullable=True
		)
		timestamp: Mapped[datetime] = mapped_column(
			DateTime(timezone=True),
			default=lambda: datetime.now(timezone.utc),
			nullable=False,
		)
		comment: Mapped[str | None] = mapped_column(Text, nullable=True)
	else:
		id = mapped_column(Integer, primary_key=True)
		model_type = mapped_column(String(100), nullable=False)
		model_id = mapped_column(Integer, nullable=False)
		old_state = mapped_column(String(50), nullable=False)
		new_state = mapped_column(String(50), nullable=False)
		user_id = mapped_column(Integer, ForeignKey("ab_user.id"), nullable=True)
		timestamp = mapped_column(
			DateTime,
			default=lambda: datetime.now(timezone.utc),
			nullable=False,
		)
		comment = mapped_column(Text, nullable=True)

	def __repr__(self) -> str:
		return (
			f"<WorkflowStateHistory {self.model_type}#{self.model_id} "
			f"{self.old_state!r} -> {self.new_state!r} @ {self.timestamp}>"
		)


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class WorkflowMixin:
	"""
	Add declarative state-machine workflow to any PgAppForge Model subclass.

	Usage::

		class Invoice(WorkflowMixin, Model):
			__tablename__ = "invoice"
			id = Column(Integer, primary_key=True)

			__workflow_states__ = {
				"draft":     "Not yet submitted",
				"submitted": "Awaiting approval",
				"approved":  "Approved for payment",
				"rejected":  "Returned for correction",
				"paid":      "Payment complete",
			}
			__workflow_transitions__ = {
				"draft":     ["submitted"],
				"submitted": ["approved", "rejected"],
				"approved":  ["paid"],
				"rejected":  ["draft"],
				"paid":      [],
			}
			__workflow_initial_state__ = "draft"

			# Optional hook – must match _on_transition_from_<OLD>_to_<NEW>
			def _on_transition_from_submitted_to_approved(self) -> None:
				send_approval_email(self)

	Class Attributes:
		__workflow_states__       : dict[str, str] – state name -> human description
		__workflow_transitions__  : dict[str, list[str]] – state -> reachable states
		__workflow_initial_state__: str – state assigned on first INSERT
	"""

	__workflow_states__: dict[str, str] = {}
	__workflow_transitions__: dict[str, list[str]] = {}
	__workflow_initial_state__: str | None = None

	# ------------------------------------------------------------------
	# Declared columns / relationships
	# ------------------------------------------------------------------

	@declared_attr
	def current_state(cls):  # noqa: N805
		if _SQLA2:
			return mapped_column(String(50), nullable=False, default="")
		return mapped_column(String(50), nullable=False, default="")

	@declared_attr
	def state_history(cls):  # noqa: N805
		# Generic relationship via primaryjoin expression using model_type + model_id.
		# Because WorkflowStateHistory uses a discriminator column (model_type / model_id)
		# rather than individual FK columns per model, we use a dynamic query instead of
		# a SA relationship (which would require per-model FKs).  The property below
		# provides the same interface consumers expect.
		return None  # replaced by the property below; declared_attr is ignored for None

	@property  # type: ignore[override]
	def state_history(self):  # type: ignore[override]
		"""Lazy-fetch all history rows for this instance from the session."""
		from sqlalchemy import select
		from pgappforge.models.sqla import db  # type: ignore[import]

		model_type = type(self).__name__
		try:
			pk = self.id  # type: ignore[attr-defined]
		except AttributeError:
			return []

		stmt = (
			select(WorkflowStateHistory)
			.where(
				WorkflowStateHistory.model_type == model_type,
				WorkflowStateHistory.model_id == pk,
			)
			.order_by(WorkflowStateHistory.timestamp)
		)
		session = db.session
		return session.execute(stmt).scalars().all()

	# ------------------------------------------------------------------
	# SQLAlchemy lifecycle
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Validate class-level workflow config and register before_insert listener."""
		if not cls.__workflow_states__:
			raise ValueError(
				f"{cls.__name__}.__workflow_states__ must be a non-empty dict"
			)
		if not cls.__workflow_transitions__:
			raise ValueError(
				f"{cls.__name__}.__workflow_transitions__ must be a non-empty dict"
			)
		if not cls.__workflow_initial_state__:
			raise ValueError(
				f"{cls.__name__}.__workflow_initial_state__ must be set"
			)
		if cls.__workflow_initial_state__ not in cls.__workflow_states__:
			raise ValueError(
				f"{cls.__name__}.__workflow_initial_state__ "
				f"{cls.__workflow_initial_state__!r} is not in __workflow_states__"
			)

		event.listen(cls, "before_insert", cls._set_initial_state)

	@staticmethod
	def _set_initial_state(mapper: Any, connection: Any, target: WorkflowMixin) -> None:
		"""Set initial state before first INSERT if not already set."""
		if not target.current_state:
			target.current_state = target.__workflow_initial_state__  # type: ignore[assignment]

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def change_state(
		self,
		new_state: str,
		user_id: int | None = None,
		comment: str | None = None,
	) -> None:
		"""
		Transition to *new_state*, record history, fire hook.

		Args:
			new_state: Target state – must be in __workflow_states__ and reachable
			           from current_state via __workflow_transitions__.
			user_id:  Optional FAB user id attributing the change.
			comment:  Free-text annotation stored in history.

		Raises:
			ValueError: Unknown state or disallowed transition.
		"""
		if new_state not in self.__workflow_states__:
			raise ValueError(
				f"Unknown workflow state {new_state!r} for {type(self).__name__}. "
				f"Valid: {list(self.__workflow_states__)}"
			)

		allowed = self.__workflow_transitions__.get(self.current_state, [])
		if new_state not in allowed:
			raise ValueError(
				f"Transition {self.current_state!r} -> {new_state!r} is not allowed "
				f"for {type(self).__name__}. Allowed from here: {allowed}"
			)

		old_state = self.current_state
		self.current_state = new_state

		self._record_history(old_state, new_state, user_id, comment)
		self._trigger_transition_action(old_state, new_state)

		log.debug(
			"%s#%s transitioned %r -> %r",
			type(self).__name__,
			getattr(self, "id", "?"),
			old_state,
			new_state,
		)

	def _record_history(
		self,
		old_state: str,
		new_state: str,
		user_id: int | None,
		comment: str | None,
	) -> None:
		"""Persist a WorkflowStateHistory row to the current session."""
		from pgappforge.models.sqla import db  # type: ignore[import]

		entry = WorkflowStateHistory(
			model_type=type(self).__name__,
			model_id=getattr(self, "id", None),
			old_state=old_state,
			new_state=new_state,
			user_id=user_id,
			comment=comment,
			timestamp=datetime.now(timezone.utc),
		)
		db.session.add(entry)

	def _trigger_transition_action(self, old_state: str, new_state: str) -> None:
		"""
		Call ``_on_transition_from_<old>_to_<new>`` if defined on the subclass.

		The hook receives no arguments beyond *self*; it runs synchronously before
		the session is committed, so it may mutate model state freely.
		"""
		hook_name = f"_on_transition_from_{old_state}_to_{new_state}"
		hook = getattr(self, hook_name, None)
		if callable(hook):
			hook()

	def can_transition_to(self, state: str) -> bool:
		"""Return True if *state* is reachable from the current state."""
		return state in self.__workflow_transitions__.get(self.current_state, [])

	def get_available_transitions(self) -> list[str]:
		"""Return all states reachable from the current state."""
		return list(self.__workflow_transitions__.get(self.current_state, []))

	# ------------------------------------------------------------------
	# Introspection / visualisation
	# ------------------------------------------------------------------

	@classmethod
	def get_workflow_as_dict(cls) -> dict[str, Any]:
		"""
		Return the full workflow definition as a plain dict – JSON-serialisable.

		Example output::

			{
				"states": {"draft": "Not yet submitted", ...},
				"transitions": {"draft": ["submitted"], ...},
				"initial_state": "draft"
			}
		"""
		return {
			"states": dict(cls.__workflow_states__),
			"transitions": {k: list(v) for k, v in cls.__workflow_transitions__.items()},
			"initial_state": cls.__workflow_initial_state__,
		}

	@classmethod
	def get_workflow_dot(cls) -> str:
		"""
		Return a Graphviz DOT string for the workflow graph.

		No graphviz Python package required – the DOT source is built with stdlib
		string formatting.  Render with::

			import subprocess
			subprocess.run(["dot", "-Tpng", "-o", "workflow.png"],
			               input=Task.get_workflow_dot(), text=True)

		Or pass the result to graphviz.Source() if the package is installed.
		"""
		lines: list[str] = [
			f'digraph "{cls.__name__}_workflow" {{',
			"\trankdir=LR;",
			'\tnode [shape=box style=rounded fontname="Helvetica"];',
			f'\t"{cls.__workflow_initial_state__}" [shape=ellipse];',
		]

		# Terminal states (no outgoing transitions) get double border
		terminal = {
			s for s, targets in cls.__workflow_transitions__.items() if not targets
		}
		for state in terminal:
			lines.append(f'\t"{state}" [shape=doublecircle];')

		# Nodes with descriptions as labels
		for state, desc in cls.__workflow_states__.items():
			if state not in terminal and state != cls.__workflow_initial_state__:
				label = f"{state}\\n{desc}" if desc else state
				lines.append(f'\t"{state}" [label="{label}"];')

		# Edges
		for from_state, to_states in cls.__workflow_transitions__.items():
			for to_state in to_states:
				lines.append(f'\t"{from_state}" -> "{to_state}";')

		lines.append("}")
		return "\n".join(lines)

	@classmethod
	def get_workflow_graph(cls):
		"""
		Return a graphviz.Digraph if the *graphviz* package is installed,
		otherwise return the DOT source string.

		Preserves backward-compatible call sites that render via
		``graph.render(...)``.
		"""
		dot_source = cls.get_workflow_dot()
		try:
			import graphviz  # type: ignore[import]
			return graphviz.Source(dot_source)
		except ImportError:
			log.warning(
				"graphviz package not installed; returning DOT string. "
				"Install with: pip install graphviz"
			)
			return dot_source

	def get_state_description(self) -> str:
		"""Return the human-readable description of the current state."""
		return self.__workflow_states__.get(self.current_state, self.current_state)

	def get_history_as_dicts(self) -> list[dict[str, Any]]:
		"""
		Return state history as a list of plain dicts (JSON-serialisable).

		Each dict has keys: old_state, new_state, timestamp (ISO-8601), user_id, comment.
		"""
		result = []
		for entry in self.state_history:
			ts = entry.timestamp
			result.append({
				"old_state": entry.old_state,
				"new_state": entry.new_state,
				"timestamp": ts.isoformat() if ts else None,
				"user_id": entry.user_id,
				"comment": entry.comment,
			})
		return result


__all__ = ["WorkflowMixin", "WorkflowStateHistory"]
