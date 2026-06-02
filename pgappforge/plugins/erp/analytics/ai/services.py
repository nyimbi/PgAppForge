"""
pgappforge/plugins/erp/analytics/ai/services.py

AIAgentService — business logic for AI agent conversations and action approval.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() here — callers own transaction boundaries.

Key methods
-----------
  start_conversation(agent_id, user_id, session_id, session) -> AgentConversation
      Creates a new conversation. Agent must be active.

  end_conversation(conversation_id, outcome, rating, session) -> AgentConversation
      Closes conversation, sets ended_at, emits ConversationEndedEvent.

  append_message(conversation_id, role, content, session, **kwargs) -> AgentMessage
      Appends an immutable AgentMessage; increments conversation.message_count.
      Emits AgentMessageSentEvent.

  propose_action(conversation_id, action_type, parameters, session,
                 target_entity_type, target_entity_id) -> AgentAction
      Records a PROPOSED action. Emits ActionProposedEvent.

  approve_action(action_id, approver_id, session) -> AgentAction
      Transitions action PROPOSED→APPROVED. Emits ActionApprovedEvent.

  reject_action(action_id, session) -> AgentAction
      Transitions action PROPOSED→REJECTED. Emits ActionRejectedEvent.

  execute_action(action_id, executor_fn, session) -> AgentAction
      Calls executor_fn(action) and transitions APPROVED→EXECUTED or FAILED.
      executor_fn must be a callable(AgentAction) -> dict result.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

import sqlalchemy as sa

from pgappforge.plugins.erp.analytics.ai.events import (
	ActionApprovedEvent,
	ActionExecutedEvent,
	ActionFailedEvent,
	ActionProposedEvent,
	ActionRejectedEvent,
	AgentMessageSentEvent,
	ConversationEndedEvent,
	ConversationStartedEvent,
	emit_event,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AIAgentError(Exception):
	"""Base error for AI agent service layer."""


class AgentNotFoundError(AIAgentError):
	pass


class AgentInactiveError(AIAgentError):
	pass


class ConversationNotFoundError(AIAgentError):
	pass


class ActionNotFoundError(AIAgentError):
	pass


class InvalidActionTransitionError(AIAgentError):
	pass


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AIAgentService:
	"""Stateless service for AI agent conversations and action lifecycle."""

	# ------------------------------------------------------------------
	# Conversations
	# ------------------------------------------------------------------

	@staticmethod
	def start_conversation(
		agent_id: str,
		session: Any,
		user_id: int | None = None,
		session_id: str | None = None,
	) -> Any:
		"""Create a new AgentConversation. Agent must be active."""
		from pgappforge.plugins.erp.analytics.ai.models import AIAgent, AgentConversation

		agent = session.execute(
			sa.select(AIAgent).where(AIAgent.id == agent_id)
		).scalar_one_or_none()
		if agent is None:
			raise AgentNotFoundError(f"AIAgent {agent_id!r} not found")
		if not agent.is_active:
			raise AgentInactiveError(f"AIAgent {agent.agent_name!r} is not active")

		conv = AgentConversation(
			tenant_id=agent.tenant_id,
			agent_id=agent_id,
			user_id=user_id,
			session_id=session_id,
			message_count=0,
		)
		session.add(conv)
		session.flush()

		emit_event(
			ConversationStartedEvent(
				aggregate_id=conv.id,
				aggregate_type="AgentConversation",
				tenant_id=agent.tenant_id,
				conversation_id=conv.id,
				agent_id=agent_id,
				agent_name=agent.agent_name,
				user_id=user_id or 0,
			),
			session,
		)
		log.info("start_conversation: agent=%s conv=%s user=%s", agent_id, conv.id, user_id)
		return conv

	@staticmethod
	def end_conversation(
		conversation_id: str,
		session: Any,
		outcome: str = "",
		rating: int | None = None,
	) -> Any:
		"""Close an AgentConversation. Idempotent if already ended."""
		from pgappforge.plugins.erp.analytics.ai.models import AgentConversation

		conv = session.execute(
			sa.select(AgentConversation).where(AgentConversation.id == conversation_id)
		).scalar_one_or_none()
		if conv is None:
			raise ConversationNotFoundError(f"AgentConversation {conversation_id!r} not found")

		if conv.ended_at is not None:
			return conv  # already ended — idempotent

		conv.ended_at = datetime.now(timezone.utc)
		conv.outcome = outcome
		if rating is not None:
			conv.rating = max(1, min(5, rating))

		emit_event(
			ConversationEndedEvent(
				aggregate_id=conversation_id,
				aggregate_type="AgentConversation",
				tenant_id=conv.tenant_id,
				conversation_id=conversation_id,
				agent_id=conv.agent_id,
				message_count=conv.message_count,
				rating=conv.rating,
				outcome=outcome,
			),
			session,
		)
		return conv

	# ------------------------------------------------------------------
	# Messages (append-only)
	# ------------------------------------------------------------------

	@staticmethod
	def append_message(
		conversation_id: str,
		role: str,
		content: str,
		session: Any,
		tool_calls: list[dict] | None = None,
		tool_results: list[dict] | None = None,
		tokens_used: int | None = None,
		model_used: str | None = None,
		latency_ms: int | None = None,
	) -> Any:
		"""Append an immutable AgentMessage to a conversation.

		Increments conversation.message_count.
		Emits AgentMessageSentEvent.
		"""
		from pgappforge.plugins.erp.analytics.ai.models import AgentConversation, AgentMessage

		conv = session.execute(
			sa.select(AgentConversation).where(AgentConversation.id == conversation_id)
		).scalar_one_or_none()
		if conv is None:
			raise ConversationNotFoundError(f"AgentConversation {conversation_id!r} not found")

		msg = AgentMessage(
			conversation_id=conversation_id,
			role=role,
			content=content,
			tool_calls=tool_calls,
			tool_results=tool_results,
			tokens_used=tokens_used,
			model_used=model_used,
			latency_ms=latency_ms,
		)
		session.add(msg)
		conv.message_count += 1
		session.flush()

		emit_event(
			AgentMessageSentEvent(
				aggregate_id=msg.id,
				aggregate_type="AgentMessage",
				tenant_id=conv.tenant_id,
				message_id=msg.id,
				conversation_id=conversation_id,
				role=role,
				tokens_used=tokens_used or 0,
				latency_ms=latency_ms or 0,
			),
			session,
		)
		return msg

	# ------------------------------------------------------------------
	# Actions
	# ------------------------------------------------------------------

	@staticmethod
	def propose_action(
		conversation_id: str,
		action_type: str,
		parameters: dict[str, Any],
		session: Any,
		target_entity_type: str = "",
		target_entity_id: str = "",
	) -> Any:
		"""Record a PROPOSED action from an EXECUTOR agent."""
		from pgappforge.plugins.erp.analytics.ai.models import AgentAction, AgentConversation

		conv = session.execute(
			sa.select(AgentConversation).where(AgentConversation.id == conversation_id)
		).scalar_one_or_none()
		if conv is None:
			raise ConversationNotFoundError(f"AgentConversation {conversation_id!r} not found")

		action = AgentAction(
			conversation_id=conversation_id,
			action_type=action_type,
			target_entity_type=target_entity_type or None,
			target_entity_id=target_entity_id or None,
			parameters=parameters,
			status="PROPOSED",
		)
		session.add(action)
		session.flush()

		emit_event(
			ActionProposedEvent(
				aggregate_id=action.id,
				aggregate_type="AgentAction",
				tenant_id=conv.tenant_id,
				action_id=action.id,
				conversation_id=conversation_id,
				action_type=action_type,
				target_entity_type=target_entity_type,
				target_entity_id=target_entity_id,
			),
			session,
		)
		return action

	@staticmethod
	def approve_action(action_id: str, approver_id: int, session: Any) -> Any:
		"""Transition action PROPOSED→APPROVED."""
		from pgappforge.plugins.erp.analytics.ai.models import AgentAction, AgentConversation

		action = session.execute(
			sa.select(AgentAction).where(AgentAction.id == action_id)
		).scalar_one_or_none()
		if action is None:
			raise ActionNotFoundError(f"AgentAction {action_id!r} not found")
		if action.status != "PROPOSED":
			raise InvalidActionTransitionError(
				f"Cannot approve action in status {action.status!r}"
			)

		action.status = "APPROVED"
		action.approved_by = approver_id

		conv = session.get(AgentConversation, action.conversation_id)
		tenant_id = conv.tenant_id if conv else ""

		emit_event(
			ActionApprovedEvent(
				aggregate_id=action_id,
				aggregate_type="AgentAction",
				tenant_id=tenant_id,
				action_id=action_id,
				conversation_id=action.conversation_id,
				approved_by_id=approver_id,
			),
			session,
		)
		return action

	@staticmethod
	def reject_action(action_id: str, session: Any) -> Any:
		"""Transition action PROPOSED→REJECTED."""
		from pgappforge.plugins.erp.analytics.ai.models import AgentAction, AgentConversation

		action = session.execute(
			sa.select(AgentAction).where(AgentAction.id == action_id)
		).scalar_one_or_none()
		if action is None:
			raise ActionNotFoundError(f"AgentAction {action_id!r} not found")
		if action.status != "PROPOSED":
			raise InvalidActionTransitionError(
				f"Cannot reject action in status {action.status!r}"
			)

		action.status = "REJECTED"
		conv = session.get(AgentConversation, action.conversation_id)
		tenant_id = conv.tenant_id if conv else ""

		emit_event(
			ActionRejectedEvent(
				aggregate_id=action_id,
				aggregate_type="AgentAction",
				tenant_id=tenant_id,
				action_id=action_id,
				conversation_id=action.conversation_id,
			),
			session,
		)
		return action

	@staticmethod
	def execute_action(
		action_id: str,
		executor_fn: Callable,
		session: Any,
	) -> Any:
		"""Execute an APPROVED action via executor_fn(action) -> dict.

		On success: status→EXECUTED, result=return value.
		On failure: status→FAILED, result={"error": str(exc)}.
		"""
		from pgappforge.plugins.erp.analytics.ai.models import AgentAction, AgentConversation

		action = session.execute(
			sa.select(AgentAction).where(AgentAction.id == action_id)
		).scalar_one_or_none()
		if action is None:
			raise ActionNotFoundError(f"AgentAction {action_id!r} not found")
		if action.status != "APPROVED":
			raise InvalidActionTransitionError(
				f"Cannot execute action in status {action.status!r}; must be APPROVED"
			)

		conv = session.get(AgentConversation, action.conversation_id)
		tenant_id = conv.tenant_id if conv else ""

		now = datetime.now(timezone.utc)
		try:
			result = executor_fn(action)
			action.status = "EXECUTED"
			action.executed_at = now
			action.result = result or {}
			emit_event(
				ActionExecutedEvent(
					aggregate_id=action_id,
					aggregate_type="AgentAction",
					tenant_id=tenant_id,
					action_id=action_id,
					conversation_id=action.conversation_id,
					action_type=action.action_type,
				),
				session,
			)
			log.info("execute_action: action=%s type=%s EXECUTED", action_id, action.action_type)
		except Exception as exc:
			action.status = "FAILED"
			action.executed_at = now
			action.result = {"error": str(exc)}
			emit_event(
				ActionFailedEvent(
					aggregate_id=action_id,
					aggregate_type="AgentAction",
					tenant_id=tenant_id,
					action_id=action_id,
					conversation_id=action.conversation_id,
					error=str(exc),
				),
				session,
			)
			log.warning("execute_action: action=%s FAILED: %s", action_id, exc)

		return action


__all__ = [
	"AIAgentService",
	"AIAgentError",
	"AgentNotFoundError",
	"AgentInactiveError",
	"ConversationNotFoundError",
	"ActionNotFoundError",
	"InvalidActionTransitionError",
]
