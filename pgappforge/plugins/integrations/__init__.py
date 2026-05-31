"""Integration Hub for pgappforge.

Connect to external systems via OAuth 2.0, REST/GraphQL, and webhooks.
Pre-built connectors for Stripe, Salesforce, HubSpot, Slack, and more.
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)
__all__ = ["IntegrationHubPlugin"]


class IntegrationHubPlugin:
	name = "integrations"

	def initialize(self, app, appbuilder) -> None:
		log.info("IntegrationHubPlugin initialized")

	def register_views(self, appbuilder) -> None:
		from pgappforge.plugins.integrations.views import IntegrationHubView, WebhookReceiverView
		appbuilder.add_view(IntegrationHubView, "Integration Hub", icon="fa-plug", category="Tools")
		appbuilder.add_view_no_menu(WebhookReceiverView)
