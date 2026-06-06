"""
pgappforge/plugins/erp/platform/whatsapp/__init__.py

WhatsApp Business API integration plugin.

Full messaging lifecycle:
  WhatsAppTemplate (approval management)
  → WhatsAppMessage (outbound/inbound, delivery tracking)
  → WhatsAppConversation (thread aggregation, agent assignment)
  → WhatsAppWebhookLog (raw webhook audit trail)

Domain: platform
Depends on: foundation

Events emitted:
  platform.whatsapp.message.sent
  platform.whatsapp.message.delivered
  platform.whatsapp.message.read
  platform.whatsapp.inbound
  platform.whatsapp.template.approved
  platform.whatsapp.conversation.started

Events consumed:
  workflow.notification.send     (trigger outbound template messages)
  crm.marketing.email.sent       (cross-channel campaign attribution)

BPM actions registered:
  platform.whatsapp.send_template  — Send WhatsApp template message from workflow
  platform.whatsapp.send_text      — Send WhatsApp text message from workflow

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.platform.whatsapp",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.platform.whatsapp import WhatsAppPlugin
    plugin = WhatsAppPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)

# E.164 pattern: +<country_code><number>, 8–15 digits after '+'
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class WhatsAppPlugin(BasePlugin):
	"""WhatsApp Business API integration ERP plugin.

	Registers templates, message outbox, conversation threading,
	and webhook audit log.  Pre-configures two Rules Engine rulesets
	on first activate(): template approval guard and E.164 phone validation.
	"""

	name = "whatsapp"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="whatsapp",
			version="1.0.0",
			description=(
				"WhatsApp Business API integration — template messages, "
				"inbound handling, delivery tracking, BPM notifications"
			),
			author="PgAppForge Contributors",
			tags=["platform", "whatsapp", "messaging", "notifications", "chatbot"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_whatsapp_message_send",
				"can_whatsapp_message_list",
				"can_whatsapp_message_view",
				"can_whatsapp_webhook_receive",
				"can_whatsapp_webhook_log_view",
				"can_whatsapp_template_list",
				"can_whatsapp_template_write",
				"can_whatsapp_template_approve",
				"can_whatsapp_conversation_list",
				"can_whatsapp_conversation_assign",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"platform.whatsapp.message.sent",
			"platform.whatsapp.message.delivered",
			"platform.whatsapp.message.read",
			"platform.whatsapp.inbound",
			"platform.whatsapp.template.approved",
			"platform.whatsapp.conversation.started",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"workflow.notification.send",
			"crm.marketing.email.sent",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"WHATSAPP_MENU_CATEGORY": "WhatsApp",
			"WHATSAPP_PHONE_NUMBER_ID": "",      # Meta Cloud API phone number ID
			"WHATSAPP_API_VERSION": "v18.0",     # Meta Graph API version
		}
		self.config = {**defaults, **self.config}
		log.info("WhatsAppPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.whatsapp.models import (
			WhatsAppTemplate,
			WhatsAppMessage,
			WhatsAppConversation,
			WhatsAppWebhookLog,
		)
		return [
			WhatsAppTemplate,
			WhatsAppMessage,
			WhatsAppConversation,
			WhatsAppWebhookLog,
		]

	def register_views(self) -> None:
		# Views are registered lazily to avoid circular imports at plugin load time.
		try:
			from pgappforge.plugins.erp.platform.whatsapp.views import (  # type: ignore
				WhatsAppTemplateView,
				WhatsAppMessageView,
				WhatsAppConversationView,
				WhatsAppWebhookLogView,
			)
		except ImportError:
			log.debug(
				"WhatsAppPlugin.register_views: views module not yet created; skipping"
			)
			return

		cat = self.config.get("WHATSAPP_MENU_CATEGORY", "WhatsApp")

		self.add_view(
			WhatsAppTemplateView, "Templates", icon="fa-file-text-o", category=cat
		)
		self.add_view(
			WhatsAppMessageView, "Messages", icon="fa-comments", category=cat
		)
		self.add_view(
			WhatsAppConversationView, "Conversations", icon="fa-comment", category=cat
		)
		self.add_view(
			WhatsAppWebhookLogView, "Webhook Log", icon="fa-bolt", category=cat
		)

		log.info("WhatsAppPlugin: views registered under category %r", cat)

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for the WhatsApp domain.

		Idempotent — skips rulesets that already exist.

		Rulesets:
		  1. whatsapp.message.template_approved_only
		       Blocks outbound TEMPLATE messages that reference a non-APPROVED template.
		  2. whatsapp.message.valid_phone
		       Validates that to_phone matches the E.164 pattern before create.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug(
				"WhatsAppPlugin.setup_rules: rules plugin not available, skipping"
			)
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "whatsapp.message.template_approved_only",
				"description": (
					"Only APPROVED templates can be used for outbound template messages"
				),
				"model_name": "WhatsAppMessage",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_non_approved_template",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "message_type", "op": "eq", "value": "TEMPLATE"},
							{"field": "_template_status", "op": "neq", "value": "APPROVED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot send a template message: "
									"template must be in APPROVED status"
								),
							},
						],
					},
				],
			},
			{
				"name": "whatsapp.message.valid_phone",
				"description": (
					"to_phone must be a valid E.164 number "
					"(+<country_code><number>, 8–15 digits)"
				),
				"model_name": "WhatsAppMessage",
				"stop_on_match": True,
				"rules": [
					{
						"name": "e164_format_check",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "to_phone",
								"op": "not_matches_regex",
								"value": r"^\+[1-9]\d{7,14}$",
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"to_phone must be a valid E.164 number "
									"(e.g. +254712345678)"
								),
							},
						],
					},
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
		log.info(
			"WhatsAppPlugin.setup_rules: %d rulesets configured", len(RULESETS)
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> WhatsAppPlugin:
	return WhatsAppPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.platform.whatsapp.models import (  # noqa: E402
	WhatsAppTemplate,
	WhatsAppMessage,
	WhatsAppConversation,
	WhatsAppWebhookLog,
)
from pgappforge.plugins.erp.platform.whatsapp.events import (  # noqa: E402
	WhatsAppMessageSentEvent,
	WhatsAppMessageDeliveredEvent,
	WhatsAppMessageReadEvent,
	WhatsAppInboundMessageEvent,
	WhatsAppTemplateApprovedEvent,
	WhatsAppConversationStartedEvent,
)
from pgappforge.plugins.erp.platform.whatsapp.services import (  # noqa: E402
	WhatsAppService,
	WhatsAppServiceError,
	WhatsAppTemplateNotFoundError,
	WhatsAppMessageNotFoundError,
	WhatsAppStateError,
)

__all__ = [
	# plugin
	"WhatsAppPlugin",
	"create_plugin",
	# models
	"WhatsAppTemplate",
	"WhatsAppMessage",
	"WhatsAppConversation",
	"WhatsAppWebhookLog",
	# events
	"WhatsAppMessageSentEvent",
	"WhatsAppMessageDeliveredEvent",
	"WhatsAppMessageReadEvent",
	"WhatsAppInboundMessageEvent",
	"WhatsAppTemplateApprovedEvent",
	"WhatsAppConversationStartedEvent",
	# service + exceptions
	"WhatsAppService",
	"WhatsAppServiceError",
	"WhatsAppTemplateNotFoundError",
	"WhatsAppMessageNotFoundError",
	"WhatsAppStateError",
]
