"""
pgappforge/plugins/erp/platform/social/events.py

Federated Social plugin domain events.

Events emitted:
  social.post.created
  social.post.boosted
  social.actor.followed
  social.follow.accepted
  social.follow.rejected
  social.reaction.added
  social.activity.federated
  social.activity.received
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class PostCreatedEvent(DomainEvent):
	event_type: str = "social.post.created"
	actor_id: str = ""
	post_id: str = ""
	visibility: str = ""
	content_preview: str = ""


@dataclass
class PostBoostedEvent(DomainEvent):
	event_type: str = "social.post.boosted"
	actor_id: str = ""
	post_id: str = ""
	activity_id: str = ""


@dataclass
class ActorFollowedEvent(DomainEvent):
	event_type: str = "social.actor.followed"
	follower_id: str = ""
	following_id: str = ""
	follow_id: str = ""
	is_remote: bool = False


@dataclass
class FollowAcceptedEvent(DomainEvent):
	event_type: str = "social.follow.accepted"
	follower_id: str = ""
	following_id: str = ""
	follow_id: str = ""


@dataclass
class FollowRejectedEvent(DomainEvent):
	event_type: str = "social.follow.rejected"
	follower_id: str = ""
	following_id: str = ""
	follow_id: str = ""


@dataclass
class ReactionAddedEvent(DomainEvent):
	event_type: str = "social.reaction.added"
	actor_id: str = ""
	post_id: str = ""
	reaction_type: str = ""


@dataclass
class ActivityFederatedEvent(DomainEvent):
	event_type: str = "social.activity.federated"
	activity_type: str = ""
	target_domains: list = field(default_factory=list)
	delivery_count: int = 0


@dataclass
class ActivityReceivedEvent(DomainEvent):
	event_type: str = "social.activity.received"
	activity_type: str = ""
	remote_actor_url: str = ""
	object_type: str = ""


__all__ = [
	"PostCreatedEvent",
	"PostBoostedEvent",
	"ActorFollowedEvent",
	"FollowAcceptedEvent",
	"FollowRejectedEvent",
	"ReactionAddedEvent",
	"ActivityFederatedEvent",
	"ActivityReceivedEvent",
]
