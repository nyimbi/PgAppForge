"""
pgappforge/plugins/erp/analytics/ai/events.py

Domain events for the AI Agents plugin.

Events emitted
--------------
  analytics.ai.conversation_started   — new AgentConversation opened
  analytics.ai.conversation_ended     — AgentConversation closed
  analytics.ai.message_sent           — AgentMessage appended
  analytics.ai.action_proposed        — AgentAction proposed by agent
  analytics.ai.action_approved        — AgentAction approved by human
  analytics.ai.action_rejected        — AgentAction rejected
  analytics.ai.action_executed        — AgentAction executed successfully
  analytics.ai.action_failed          — AgentAction execution failed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


@dataclass
class ConversationStartedEvent(DomainEvent):
	event_type: str = "analytics.ai.conversation_started"
	conversation_id: str = ""
	agent_id: str = ""
	agent_name: str = ""
	user_id: int = 0


@dataclass
class ConversationEndedEvent(DomainEvent):
	event_type: str = "analytics.ai.conversation_ended"
	conversation_id: str = ""
	agent_id: str = ""
	message_count: int = 0
	rating: int | None = None
	outcome: str = ""


@dataclass
class AgentMessageSentEvent(DomainEvent):
	event_type: str = "analytics.ai.message_sent"
	message_id: str = ""
	conversation_id: str = ""
	role: str = ""
	tokens_used: int = 0
	latency_ms: int = 0


@dataclass
class ActionProposedEvent(DomainEvent):
	event_type: str = "analytics.ai.action_proposed"
	action_id: str = ""
	conversation_id: str = ""
	action_type: str = ""
	target_entity_type: str = ""
	target_entity_id: str = ""


@dataclass
class ActionApprovedEvent(DomainEvent):
	event_type: str = "analytics.ai.action_approved"
	action_id: str = ""
	conversation_id: str = ""
	approved_by_id: int = 0


@dataclass
class ActionRejectedEvent(DomainEvent):
	event_type: str = "analytics.ai.action_rejected"
	action_id: str = ""
	conversation_id: str = ""


@dataclass
class ActionExecutedEvent(DomainEvent):
	event_type: str = "analytics.ai.action_executed"
	action_id: str = ""
	conversation_id: str = ""
	action_type: str = ""


@dataclass
class ActionFailedEvent(DomainEvent):
	event_type: str = "analytics.ai.action_failed"
	action_id: str = ""
	conversation_id: str = ""
	error: str = ""


__all__ = [
	"ConversationStartedEvent",
	"ConversationEndedEvent",
	"AgentMessageSentEvent",
	"ActionProposedEvent",
	"ActionApprovedEvent",
	"ActionRejectedEvent",
	"ActionExecutedEvent",
	"ActionFailedEvent",
	"emit_event",
]
