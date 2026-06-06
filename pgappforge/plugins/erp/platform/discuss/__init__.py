from __future__ import annotations

from pgappforge.plugins.erp.foundation import BasePlugin

__all__ = ["DiscussPlugin"]


class DiscussPlugin(BasePlugin):
	"""Team Chat / Discuss module.

	Provides channel-based messaging, threaded replies, emoji reactions,
	and BPM-driven system notifications.  The BPM workflow engine uses
	DiscussService.post_system_notification() to fan notifications into
	channels bound to workflow instances or to a default tenant system channel.

	Subscribes to upstream events to post automatic notifications:
	  - workflow.instance.started
	  - workflow.instance.completed
	  - hcm.payroll.run.approved
	"""

	name = "discuss"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	def register(self, app_builder) -> None:  # type: ignore[override]
		app_builder.add_api(
			"pgappforge.plugins.erp.platform.discuss.views",
			tags=["platform", "discuss", "chat", "messaging", "notifications"],
		)

	def get_models(self) -> list:
		from pgappforge.plugins.erp.platform.discuss.models import (
			DiscussChannel,
			DiscussChannelMember,
			DiscussMessage,
		)
		return [DiscussChannel, DiscussChannelMember, DiscussMessage]

	def subscribe_to(self) -> list[str]:
		return [
			"workflow.instance.started",
			"workflow.instance.completed",
			"hcm.payroll.run.approved",
		]

	def on_event(self, event_type: str, event_data: dict, session) -> None:  # type: ignore[override]
		"""Handle subscribed upstream events by posting system notifications."""
		from pgappforge.plugins.erp.platform.discuss.services import DiscussService

		tenant_id = event_data.get("tenant_id", "")
		if not tenant_id:
			return

		svc = DiscussService()
		linked_module = event_data.get("aggregate_type")
		linked_record_id = event_data.get("aggregate_id")

		try:
			svc.post_system_notification(
				tenant_id=tenant_id,
				notification_type=event_type,
				payload=event_data,
				session=session,
				linked_module=linked_module,
				linked_record_id=linked_record_id,
			)
		except Exception:
			pass  # best-effort — never block the upstream transaction
