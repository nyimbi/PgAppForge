from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"ChannelCreatedEvent",
	"MessagePostedEvent",
	"MessageReactedEvent",
	"ChannelMemberAddedEvent",
	"ThreadCreatedEvent",
	"SystemNotificationPostedEvent",
]


@dataclass
class ChannelCreatedEvent(DomainEvent):
	event_type: str = "platform.discuss.channel.created"
	channel_id: str = ""
	name: str = ""
	created_by: str = ""
	tenant_id: str = ""


@dataclass
class MessagePostedEvent(DomainEvent):
	event_type: str = "platform.discuss.message.posted"
	message_id: str = ""
	channel_id: str = ""
	author_id: str = ""
	tenant_id: str = ""
	preview: str = ""


@dataclass
class MessageReactedEvent(DomainEvent):
	event_type: str = "platform.discuss.message.reacted"
	message_id: str = ""
	reactor_id: str = ""
	emoji: str = ""


@dataclass
class ChannelMemberAddedEvent(DomainEvent):
	event_type: str = "platform.discuss.member.added"
	channel_id: str = ""
	member_id: str = ""
	added_by: str = ""


@dataclass
class ThreadCreatedEvent(DomainEvent):
	event_type: str = "platform.discuss.thread.created"
	thread_id: str = ""
	parent_message_id: str = ""
	author_id: str = ""


@dataclass
class SystemNotificationPostedEvent(DomainEvent):
	event_type: str = "platform.discuss.system_notification"
	channel_id: str = ""
	notification_type: str = ""
	payload: dict[str, Any] = field(default_factory=dict)
