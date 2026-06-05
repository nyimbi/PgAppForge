"""
pgappforge/plugins/erp/platform/social/__init__.py

Platform Federated Social plugin — ActivityPub-based enterprise collaboration.

Events emitted:
  social.post.created
  social.post.boosted
  social.actor.followed
  social.follow.accepted
  social.follow.rejected
  social.reaction.added
  social.activity.federated
  social.activity.received

Events consumed:
  party.created  — auto-create a local Actor stub for new foundation Parties

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.platform.social"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PlatformSocialPlugin(BasePlugin):
	"""Platform Federated Social (ActivityPub) plugin."""

	name = "platform.social"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.social",
			version="1.0.0",
			description=(
				"ActivityPub-based federated social networking for enterprise "
				"collaboration — posts, follows, reactions, notifications, "
				"and Fediverse federation."
			),
			author="PgAppForge Contributors",
			tags=["platform", "social", "activitypub", "fediverse", "federation"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_social_posts_read",
				"can_social_posts_write",
				"can_social_actors_read",
				"can_social_actors_follow",
				"can_social_notifications_read",
				"can_social_feed_read",
				"can_social_admin",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"social.post.created",
			"social.post.boosted",
			"social.actor.followed",
			"social.follow.accepted",
			"social.follow.rejected",
			"social.reaction.added",
			"social.activity.federated",
			"social.activity.received",
		]

	def subscribe_to(self) -> list[str]:
		return ["party.created"]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SOCIAL_MENU_CATEGORY": "Social",
			"SOCIAL_DEFAULT_VISIBILITY": "PUBLIC",
			"SOCIAL_MAX_POST_LENGTH": 500,
			"SOCIAL_FEDERATION_ENABLED": True,
			"SOCIAL_WEBFINGER_TIMEOUT": 5,
		}
		self.config = {**defaults, **self.config}
		log.info("PlatformSocialPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.social.views import (
			PostView,
			FeedView,
			NotificationView,
			ActorProfileView,
			ActorSearchView,
		)
		cat = self.config.get("SOCIAL_MENU_CATEGORY", "Social")
		self.add_view(FeedView, "Social Feed", icon="fa-rss", category=cat)
		self.add_view(ActorSearchView, "Find People", icon="fa-search", category=cat)
		self.add_view_no_menu(PostView)
		self.add_view_no_menu(NotificationView)
		self.add_view_no_menu(ActorProfileView)
		log.info("PlatformSocialPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.social.models import (
			Actor,
			SocialActivity,
			Post,
			Follow,
			Reaction,
			Notification,
		)
		return [Actor, SocialActivity, Post, Follow, Reaction, Notification]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure domain invariant rulesets for social entities."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "social_actor.no_self_follow",
				"description": "An actor cannot follow itself",
				"model_name": "Follow",
				"stop_on_match": True,
				"rules": [
					{
						"name": "follower_ne_following",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "follower_id", "op": "eq", "value": "{{following_id}}"}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "An actor cannot follow itself"}
						],
					}
				],
			},
			{
				"name": "social_post.max_length",
				"description": "Post content must not exceed configured max length",
				"model_name": "Post",
				"stop_on_match": True,
				"rules": [
					{
						"name": "content_length_check",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "content", "op": "length_gt", "value": 500}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Post content exceeds maximum length"}
						],
					}
				],
			},
			{
				"name": "social_reaction.valid_type",
				"description": "Reaction type must be LIKE, BOOST, or BOOKMARK",
				"model_name": "Reaction",
				"stop_on_match": True,
				"rules": [
					{
						"name": "reaction_type_valid",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "reaction_type", "op": "not_in",
							 "value": ["LIKE", "BOOST", "BOOKMARK"]}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "reaction_type must be LIKE | BOOST | BOOKMARK"}
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
		log.info("PlatformSocialPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> PlatformSocialPlugin:
	return PlatformSocialPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.social.models import (  # noqa: E402
	Actor, SocialActivity, Post, Follow, Reaction, Notification,
)
from pgappforge.plugins.erp.platform.social.services import (  # noqa: E402
	FederatedSocialService, SocialServiceError,
	ActorNotFoundError, PostNotFoundError,
	FollowAlreadyExistsError, ReactionAlreadyExistsError,
)

__all__ = [
	"PlatformSocialPlugin",
	"create_plugin",
	# models
	"Actor",
	"SocialActivity",
	"Post",
	"Follow",
	"Reaction",
	"Notification",
	# services
	"FederatedSocialService",
	"SocialServiceError",
	"ActorNotFoundError",
	"PostNotFoundError",
	"FollowAlreadyExistsError",
	"ReactionAlreadyExistsError",
]
