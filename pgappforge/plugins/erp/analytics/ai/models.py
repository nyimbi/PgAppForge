"""
pgappforge/plugins/erp/analytics/ai/models.py

SQLAlchemy models for the AI Agents plugin.

Tables
------
analytics_ai_agent          — agent registry (type, model, system_prompt, guardrails)
analytics_agent_conversation — session-scoped conversation with an agent
analytics_agent_message     — individual messages within a conversation
analytics_agent_action      — proposed/executed actions with approval workflow

Design rules
  - All PKs: UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - tenant_id UUID NOT NULL on all mutable entities + AuditMixin
  - tokens_used, latency_ms: INTEGER — counts, never float
  - rating: INTEGER (1–5 stars)
  - tools_config, guardrails, tool_calls, tool_results, parameters, result: JSONB
  - AgentMessage: immutable append-only log — never UPDATE rows
  - AgentAction: status lifecycle PROPOSED→APPROVED/REJECTED→EXECUTED/FAILED
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# AIAgent
# ---------------------------------------------------------------------------

class AIAgent(AuditMixin, Model):
	"""Registry of AI agent definitions.

	agent_type:
	  ASSISTANT   — conversational Q&A and guidance (no side-effects)
	  ANALYST     — data analysis, report generation (read-only actions)
	  EXECUTOR    — can write/update records (requires action approval)
	  ORCHESTRATOR — delegates to sub-agents; coordinates multi-agent workflows

	model_id: model identifier string e.g. "claude-sonnet-4-5", "gpt-4o".
	system_prompt TEXT: the agent's instruction prompt (may be long).
	tools_config JSONB: list of tool definitions the agent can invoke:
	  [{"name": "run_sql", "description": "...", "parameters": {...}}]
	guardrails JSONB: safety configuration:
	  {"max_tokens": 4096, "forbidden_topics": [...], "require_approval_for": [...]}
	is_active: only active agents can start new conversations.
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_ai_agent"
	__table_args__ = (
		sa.UniqueConstraint("tenant_id", "agent_name", name="uq_analytics_ai_agent_tenant_name"),
		Index("ix_analytics_ai_agent_tenant", "tenant_id"),
		Index("ix_analytics_ai_agent_type", "agent_type"),
		Index("ix_analytics_ai_agent_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	agent_name = Column(String(200), nullable=False)
	agent_type = Column(
		String(20),
		nullable=False,
		default="ASSISTANT",
		comment="ASSISTANT | ANALYST | EXECUTOR | ORCHESTRATOR",
	)
	model_id = Column(
		String(100),
		nullable=False,
		comment="Model identifier e.g. claude-sonnet-4-5 | gpt-4o",
	)
	system_prompt = Column(Text, nullable=True)
	tools_config: list[dict] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{name, description, parameters}] — Anthropic tool-use format",
	)
	guardrails: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment='{"max_tokens": 4096, "forbidden_topics": [], "require_approval_for": []}',
	)
	is_active = Column(Boolean, nullable=False, default=True)
	created_by = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	conversations: list[AgentConversation] = sa.orm.relationship(
		"AgentConversation",
		back_populates="agent",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AIAgent {self.agent_name!r} type={self.agent_type!r} "
			f"model={self.model_id!r} active={self.is_active!r}>"
		)


# ---------------------------------------------------------------------------
# AgentConversation
# ---------------------------------------------------------------------------

class AgentConversation(AuditMixin, Model):
	"""A single user session with an AIAgent.

	session_id: opaque token (browser session, API request ID, etc.).
	message_count: denormalised count updated on each message insert.
	outcome TEXT: free-text summary of what the conversation achieved.
	rating INTEGER: 1–5 stars from user feedback (nullable if not rated).
	ended_at NULL = conversation still open.
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_agent_conversation"
	__table_args__ = (
		Index("ix_analytics_agent_conv_agent", "agent_id"),
		Index("ix_analytics_agent_conv_user", "user_id"),
		Index("ix_analytics_agent_conv_session", "session_id"),
		Index("ix_analytics_agent_conv_started", "started_at", postgresql_using="brin"),
		Index("ix_analytics_agent_conv_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	agent_id = Column(
		UUID(as_uuid=False),
		ForeignKey("analytics_ai_agent.id", ondelete="CASCADE"),
		nullable=False,
	)
	user_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)
	session_id = Column(String(200), nullable=True)
	started_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	ended_at = Column(DateTime(timezone=True), nullable=True)
	message_count = Column(Integer, nullable=False, default=0)
	outcome = Column(Text, nullable=True)
	rating = Column(Integer, nullable=True, comment="User rating 1–5; NULL if not rated")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	agent: AIAgent = sa.orm.relationship(
		"AIAgent",
		back_populates="conversations",
		lazy="select",
	)
	messages: list[AgentMessage] = sa.orm.relationship(
		"AgentMessage",
		back_populates="conversation",
		cascade="all, delete-orphan",
		lazy="select",
	)
	actions: list[AgentAction] = sa.orm.relationship(
		"AgentAction",
		back_populates="conversation",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AgentConversation {self.id!r} agent={self.agent_id!r} "
			f"msgs={self.message_count!r}>"
		)


# ---------------------------------------------------------------------------
# AgentMessage
# ---------------------------------------------------------------------------

class AgentMessage(Model):
	"""Immutable record of a single turn in an AgentConversation.

	Append-only: NEVER update or delete existing rows.
	To correct a message, add a new SYSTEM message with correction context.

	role: USER | ASSISTANT | TOOL
	tool_calls JSONB: Anthropic tool_use blocks (role=ASSISTANT with tool invocations).
	tool_results JSONB: tool_result blocks (role=TOOL).
	tokens_used: total token count for this turn (input+output combined).
	latency_ms: time from request to first token received (wall clock).
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_agent_message"
	__table_args__ = (
		Index("ix_analytics_agent_msg_conv", "conversation_id"),
		Index("ix_analytics_agent_msg_role", "role"),
		Index("ix_analytics_agent_msg_sent", "sent_at", postgresql_using="brin"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	conversation_id = Column(
		UUID(as_uuid=False),
		ForeignKey("analytics_agent_conversation.id", ondelete="CASCADE"),
		nullable=False,
	)
	role = Column(
		String(20),
		nullable=False,
		comment="USER | ASSISTANT | TOOL",
	)
	content = Column(Text, nullable=False)
	tool_calls: list[dict] | None = Column(
		JSONB,
		nullable=True,
		comment="Anthropic tool_use blocks when role=ASSISTANT",
	)
	tool_results: list[dict] | None = Column(
		JSONB,
		nullable=True,
		comment="tool_result blocks when role=TOOL",
	)
	tokens_used = Column(
		Integer,
		nullable=True,
		comment="Total tokens for this turn (input + output)",
	)
	model_used = Column(
		String(100),
		nullable=True,
		comment="Actual model that served this turn",
	)
	latency_ms = Column(
		Integer,
		nullable=True,
		comment="Wall-clock ms from request to first token",
	)
	sent_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	conversation: AgentConversation = sa.orm.relationship(
		"AgentConversation",
		back_populates="messages",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AgentMessage {self.id!r} role={self.role!r} "
			f"conv={self.conversation_id!r} tokens={self.tokens_used!r}>"
		)


# ---------------------------------------------------------------------------
# AgentAction
# ---------------------------------------------------------------------------

class AgentAction(Model):
	"""A side-effecting action proposed or executed by an EXECUTOR agent.

	status lifecycle:
	  PROPOSED  — agent has suggested the action; awaiting human approval
	  APPROVED  — human approver approved (approved_by set)
	  REJECTED  — human approver rejected; no further transitions
	  EXECUTED  — action ran successfully; result populated
	  FAILED    — action attempted but raised an error; result has error detail

	target_entity_type + target_entity_id: the record the action acts upon.
	parameters JSONB: action-specific input (e.g. field values to set).
	result JSONB: action output or error payload.
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_agent_action"
	__table_args__ = (
		Index("ix_analytics_agent_action_conv", "conversation_id"),
		Index("ix_analytics_agent_action_status", "status"),
		Index("ix_analytics_agent_action_entity", "target_entity_type", "target_entity_id"),
		Index("ix_analytics_agent_action_executed", "executed_at", postgresql_using="brin"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	conversation_id = Column(
		UUID(as_uuid=False),
		ForeignKey("analytics_agent_conversation.id", ondelete="CASCADE"),
		nullable=False,
	)
	action_type = Column(
		String(100),
		nullable=False,
		comment="e.g. update_record | send_email | run_query | create_ticket",
	)
	target_entity_type = Column(String(100), nullable=True)
	target_entity_id = Column(String(64), nullable=True)
	parameters: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Action-specific input parameters",
	)
	status = Column(
		String(20),
		nullable=False,
		default="PROPOSED",
		comment="PROPOSED | APPROVED | EXECUTED | REJECTED | FAILED",
	)
	approved_by = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)
	executed_at = Column(DateTime(timezone=True), nullable=True)
	result: dict[str, Any] | None = Column(
		JSONB,
		nullable=True,
		comment="Action output or error payload",
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	conversation: AgentConversation = sa.orm.relationship(
		"AgentConversation",
		back_populates="actions",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AgentAction {self.id!r} type={self.action_type!r} "
			f"status={self.status!r} entity={self.target_entity_type!r}/{self.target_entity_id!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"AIAgent",
	"AgentConversation",
	"AgentMessage",
	"AgentAction",
]
