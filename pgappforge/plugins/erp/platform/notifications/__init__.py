"""
pgappforge/plugins/erp/platform/notifications/__init__.py

Notification Dispatcher plugin — bridges ERP domain events to the alerting
notification service so staff receive timely alerts for key business activity.

Events consumed (all opt-in via Flask config flags):
  lending.loan.approved          → borrower alert       (NOTIFY_LOAN_APPROVED)
  finance.ap.invoice.created     → AP team alert        (NOTIFY_INVOICE_CREATED)
  hcm.payroll.payslip.created    → employee alert       (NOTIFY_PAYROLL_PROCESSED)
  club.member.approved           → member welcome       (NOTIFY_MEMBER_APPROVED)
  sacco.member.approved          → member welcome       (NOTIFY_MEMBER_APPROVED)
  inventory.stock.reorder_point  → procurement alert    (NOTIFY_LOW_STOCK)
  finance.payment.failed         → finance manager      (always on)
  club.member.charged            → member charge notice (NOTIFY_MEMBER_CHARGES, opt-in)

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.platform.notifications"]

    # Channel selection (default: email only)
    NOTIFY_CHANNELS = ["email", "sms"]

    # Per-event toggles (all True by default unless noted)
    NOTIFY_LOAN_APPROVED    = True
    NOTIFY_INVOICE_CREATED  = True
    NOTIFY_PAYROLL_PROCESSED = True
    NOTIFY_MEMBER_APPROVED  = True
    NOTIFY_LOW_STOCK        = True
    NOTIFY_MEMBER_CHARGES   = False   # opt-in
"""

from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class NotificationDispatcherPlugin(BasePlugin):
	"""Wires ERP domain events to the alerting notification service."""

	name = "platform.notifications"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.notifications",
			version="1.0.0",
			description=(
				"Event-driven notification dispatcher — subscribes to key ERP domain "
				"events and delivers alerts via email, SMS, WhatsApp, or push channels."
			),
			author="PgAppForge Contributors",
			tags=["platform", "notifications", "alerts", "events", "erp"],
			priority=PluginPriority.NORMAL,
			permissions=[],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		"""This plugin emits no events of its own."""
		return []

	def subscribe_to(self) -> list[str]:
		"""
		Declare the event types this plugin handles.

		post_initialize() in BasePlugin auto-wires _on_<event> methods; we skip
		that mechanism here because event_dispatcher.register_all_subscriptions()
		handles bulk registration more cleanly for this cross-cutting concern.
		"""
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"NOTIFY_CHANNELS": ["email"],
			"NOTIFY_LOAN_APPROVED": True,
			"NOTIFY_INVOICE_CREATED": True,
			"NOTIFY_PAYROLL_PROCESSED": True,
			"NOTIFY_MEMBER_APPROVED": True,
			"NOTIFY_LOW_STOCK": True,
			"NOTIFY_MEMBER_CHARGES": False,
		}
		self.config = {**defaults, **self.config}
		log.info("NotificationDispatcherPlugin initialised")

	def post_initialize(self) -> None:
		"""Register all event-to-notification subscriptions after initialisation."""
		# BasePlugin.post_initialize wires _on_* methods; call it first so any
		# future handler methods added to this class are auto-wired as well.
		super().post_initialize()

		from pgappforge.plugins.erp.platform.notifications.event_dispatcher import (
			register_all_subscriptions,
		)
		count = register_all_subscriptions()
		log.info(
			"NotificationDispatcherPlugin: %d event subscription(s) registered",
			count,
		)

	def register_views(self) -> None:
		"""No views — this plugin is pure infrastructure."""
		pass

	def register_models(self) -> list:
		"""No models — notifications are stateless dispatches."""
		return []
