"""
pgappforge/plugins/erp/analytics/ai/__init__.py

AIPlugin — AI agent registry, conversation management, action approval workflow.

Domain: analytics
Depends on: foundation

Events emitted
--------------
  analytics.ai.conversation_started   — new conversation opened
  analytics.ai.conversation_ended     — conversation closed
  analytics.ai.message_sent           — message appended
  analytics.ai.action_proposed        — action proposed by EXECUTOR agent
  analytics.ai.action_approved        — action approved by human
  analytics.ai.action_rejected        — action rejected
  analytics.ai.action_executed        — action executed successfully
  analytics.ai.action_failed          — action execution failed

Events consumed
---------------
  analytics.anomaly.detected      — create AI conversation to investigate anomaly
  analytics.kpi.status_changed    — optionally trigger AI analyst agent

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.analytics.ai",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AIPlugin(BasePlugin):
	"""AI Agents ERP plugin.

	Agent registry with four types (ASSISTANT/ANALYST/EXECUTOR/ORCHESTRATOR),
	conversation lifecycle management, append-only message log, and a human-in-
	the-loop action approval workflow for EXECUTOR agents.

	Pre-configures 4 Rules Engine rulesets for agent governance and action safety.

	Class-level attributes:
	    name       = "analytics.ai"
	    domain     = "analytics"
	    depends_on = ["foundation"]
	"""

	name = "analytics.ai"
	domain = "analytics"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="analytics.ai",
			version="1.0.0",
			description=(
				"AI Agents — agent registry (ASSISTANT/ANALYST/EXECUTOR/ORCHESTRATOR), "
				"conversation and message management, and PROPOSED→APPROVED→EXECUTED "
				"action approval workflow with full audit trail."
			),
			author="PgAppForge Contributors",
			tags=["erp", "analytics", "ai", "agents", "llm", "anthropic", "automation"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_analytics_ai_agent_list",
				"can_analytics_ai_agent_write",
				"can_analytics_ai_conversation_list",
				"can_analytics_ai_conversation_write",
				"can_analytics_ai_action_list",
				"can_analytics_ai_action_approve",
				"can_analytics_ai_action_reject",
				"can_analytics_ai_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"analytics.ai.conversation_started",
			"analytics.ai.conversation_ended",
			"analytics.ai.message_sent",
			"analytics.ai.action_proposed",
			"analytics.ai.action_approved",
			"analytics.ai.action_rejected",
			"analytics.ai.action_executed",
			"analytics.ai.action_failed",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"analytics.anomaly.detected",
			"analytics.kpi.status_changed",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"AI_MENU_CATEGORY": "Analytics",
			"AI_DEFAULT_MODEL": "claude-sonnet-4-5",
			"AI_ACTION_REQUIRE_APPROVAL": True,
			"AI_MAX_CONVERSATION_MESSAGES": 200,
		}
		self.config = {**defaults, **self.config}
		log.info("AIPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		self._subscribe_to_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.analytics.ai.views import (
			AIAgentView,
			AIReportView,
			ActionView,
			ConversationView,
		)
		cat = self.config.get("AI_MENU_CATEGORY", "Analytics")
		self.add_view(AIAgentView, "AI Agents", icon="fa-robot", category=cat)
		self.add_view(ConversationView, "Conversations", icon="fa-comments", category=cat)
		self.add_view(ActionView, "Pending Actions", icon="fa-check-circle", category=cat)
		self.add_view(AIReportView, "AI Reports", icon="fa-bar-chart", category=cat)
		log.info("AIPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.analytics.ai.models import (
			AIAgent,
			AgentAction,
			AgentConversation,
			AgentMessage,
		)
		return [AIAgent, AgentConversation, AgentMessage, AgentAction]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 Rules Engine rulesets for AI agent governance."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("AIPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			{
				"name": "analytics.ai.block_executor_without_guardrails",
				"description": "Block creating EXECUTOR agent without guardrails config",
				"model_name": "AIAgent",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_guardrails",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "agent_type", "op": "eq", "value": "EXECUTOR"},
							{"field": "guardrails", "op": "is_empty", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "EXECUTOR agents must have guardrails configured",
							}
						],
					}
				],
			},
			{
				"name": "analytics.ai.require_approval_for_executor_actions",
				"description": "EXECUTOR agent actions must be APPROVED before execution",
				"model_name": "AgentAction",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_unapproved_execute",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "EXECUTED"},
							{"field": "status", "op": "ne", "value": "APPROVED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "AgentAction must be APPROVED before EXECUTED",
							}
						],
					}
				],
			},
			{
				"name": "analytics.ai.max_message_count",
				"description": "Warn when conversation exceeds 200 messages",
				"model_name": "AgentConversation",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_long_conversation",
						"trigger_event": "on_update",
						"conditions_json": [
							{"field": "message_count", "op": "gte", "value": 200},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Conversation has exceeded 200 messages — consider summarising",
							}
						],
					}
				],
			},
			{
				"name": "analytics.ai.block_inactive_agent_conversation",
				"description": "Block starting conversation with inactive agent",
				"model_name": "AgentConversation",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_inactive",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "_agent_is_active", "op": "eq", "value": False},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot start conversation with an inactive agent",
							}
						],
					}
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("AIPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("analytics.anomaly.detected", self._on_anomaly_detected)
			subscribe("analytics.kpi.status_changed", self._on_kpi_status_changed)
			log.debug("AIPlugin: subscribed to analytics events")
		except Exception as exc:
			log.warning("AIPlugin._subscribe_to_events failed: %s", exc)

	def _on_anomaly_detected(self, event: Any) -> None:
		log.debug(
			"AIPlugin._on_anomaly_detected: anomaly=%s metric=%s sev=%s",
			getattr(event, "anomaly_id", "?"),
			getattr(event, "metric_name", "?"),
			getattr(event, "severity", "?"),
		)

	def _on_kpi_status_changed(self, event: Any) -> None:
		log.debug(
			"AIPlugin._on_kpi_status_changed: kpi=%s %s→%s",
			getattr(event, "kpi_code", "?"),
			getattr(event, "previous_status", "?"),
			getattr(event, "new_status", "?"),
		)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> AIPlugin:
	return AIPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.analytics.ai.models import (  # noqa: E402
	AIAgent,
	AgentAction,
	AgentConversation,
	AgentMessage,
)
from pgappforge.plugins.erp.analytics.ai.events import (  # noqa: E402
	ActionApprovedEvent,
	ActionExecutedEvent,
	ActionFailedEvent,
	ActionProposedEvent,
	ActionRejectedEvent,
	AgentMessageSentEvent,
	ConversationEndedEvent,
	ConversationStartedEvent,
)
from pgappforge.plugins.erp.analytics.ai.services import (  # noqa: E402
	AIAgentError,
	AIAgentService,
	ActionNotFoundError,
	AgentInactiveError,
	AgentNotFoundError,
	ConversationNotFoundError,
	InvalidActionTransitionError,
)

__all__ = [
	"AIPlugin",
	"create_plugin",
	# models
	"AIAgent",
	"AgentConversation",
	"AgentMessage",
	"AgentAction",
	# events
	"ConversationStartedEvent",
	"ConversationEndedEvent",
	"AgentMessageSentEvent",
	"ActionProposedEvent",
	"ActionApprovedEvent",
	"ActionRejectedEvent",
	"ActionExecutedEvent",
	"ActionFailedEvent",
	# services
	"AIAgentService",
	"AIAgentError",
	"AgentNotFoundError",
	"AgentInactiveError",
	"ConversationNotFoundError",
	"ActionNotFoundError",
	"InvalidActionTransitionError",
]
