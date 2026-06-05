"""
pgappforge/plugins/erp/platform/social/views.py

Flask views for the Federated Social plugin.

Endpoints:
  PostView            POST   /social/posts/                    create post
                      GET    /social/posts/<id>                get post
  FeedView            GET    /social/feed/                     home/local/public feed
  NotificationView    GET    /social/notifications/            list notifications
                      POST   /social/notifications/<id>/read   mark read
                      POST   /social/notifications/read-all    mark all read
  ActorProfileView    GET    /social/actors/<id>               actor profile
                      GET    /social/actors/<id>/followers     follower list
                      GET    /social/actors/<id>/following     following list
                      POST   /social/actors/<id>/follow        follow actor
                      POST   /social/posts/<id>/boost          boost post
                      GET    /social/search/actors             actor search
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	rich_text_widget,
	file_widget,
	select2_widget,
	chart_widget,
)

log = logging.getLogger(__name__)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.platform.social.services import FederatedSocialService
	return FederatedSocialService()


def _tenant_id():
	"""Extract tenant_id from request JSON, args, or default."""
	return (
		(request.get_json(silent=True) or {}).get("tenant_id")
		or request.args.get("tenant_id")
		or "default"
	)


# ---------------------------------------------------------------------------
# PostView
# ---------------------------------------------------------------------------

class PostView(BaseView):
	"""Create and retrieve posts.

	Widget hints (consumed by form builder):
	  content      → RichTextEditorWidget
	  attachments  → FileUploadWidget (multiple=True)
	  tags         → TagInputWidget (via Select2ManyWidget)
	  visibility   → Select2Widget
	"""

	route_base = "/social/posts"
	default_view = "create"

	# Widget config exposed for form builder integration
	form_widget_args = {
		"content": rich_text_widget(height=300),
		"attachments": file_widget(
			multiple=True,
			types=["jpg", "jpeg", "png", "gif", "webp", "mp4", "mp3", "pdf"],
		),
		"tags": select2_widget(),
		"visibility": select2_widget(
			choices=["PUBLIC", "UNLISTED", "FOLLOWERS", "DIRECT"]
		),
	}

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Create a new post.

		Body (JSON):
		  tenant_id  str  required
		  actor_id   str  required  (internal UUID of the posting actor)
		  content    str  required  (HTML or plain text)
		  visibility str  optional  PUBLIC | UNLISTED | FOLLOWERS | DIRECT
		  attachments list optional
		  tags       list optional
		  sensitive  bool optional
		  spoiler_text str optional
		  in_reply_to_id str optional
		  language   str  optional  BCP 47 tag default 'en'
		"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		missing = [f for f in ("tenant_id", "actor_id", "content") if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			post = _svc().create_post(
				session=session,
				tenant_id=data["tenant_id"],
				actor_id=data["actor_id"],
				content=data["content"],
				visibility=data.get("visibility", "PUBLIC"),
				attachments=data.get("attachments"),
				tags=data.get("tags"),
				sensitive=data.get("sensitive", False),
				spoiler_text=data.get("spoiler_text"),
				in_reply_to_id=data.get("in_reply_to_id"),
				language=data.get("language", "en"),
			)
			session.commit()
			return jsonify({
				"post_id": post.id,
				"activity_id": post.activity_id,
				"content": post.content,
				"visibility": data.get("visibility", "PUBLIC"),
				"language": post.language,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:post_id>")
	@has_access
	def get(self, post_id: str):
		"""Retrieve a single post by id."""
		from pgappforge.plugins.erp.platform.social.models import Post, Activity, Actor
		session = _get_session()
		row = session.execute(
			sa.select(Post, Activity, Actor)
			.join(Activity, Activity.id == Post.activity_id)
			.join(Actor, Actor.id == Activity.actor_id)
			.where(Post.id == post_id)
		).first()
		if row is None:
			abort(404, f"Post {post_id!r} not found")
		post, activity, actor = row
		return jsonify({
			"post_id": str(post.id),
			"actor_username": actor.username,
			"actor_display_name": actor.display_name,
			"content": post.content,
			"content_html": post.content_html,
			"visibility": activity.visibility,
			"published_at": activity.published_at.isoformat(),
			"boost_count": post.boost_count,
			"reaction_count": post.reaction_count,
			"reply_count": post.reply_count,
			"sensitive": post.sensitive,
			"spoiler_text": post.spoiler_text,
			"language": post.language,
			"tags": post.tags or [],
			"attachments": post.attachments or [],
		})

	@expose("/<string:post_id>/boost", methods=["POST"])
	@has_access
	def boost(self, post_id: str):
		"""Boost (Announce) a post."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("actor_id"):
			return jsonify({"error": "actor_id required"}), 400
		try:
			activity = _svc().boost_post(
				session=session,
				tenant_id=data.get("tenant_id", "default"),
				actor_id=data["actor_id"],
				post_id=post_id,
			)
			session.commit()
			return jsonify({"activity_id": activity.id, "status": "boosted"}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# FeedView
# ---------------------------------------------------------------------------

class FeedView(BaseView):
	"""Aggregated social feed.

	Widget hints:
	  chart → AdvancedChartsWidget for engagement analytics
	"""

	route_base = "/social/feed"
	default_view = "index"

	form_widget_args = {
		"engagement_chart": chart_widget("line"),
	}

	@expose("/")
	@has_access
	def index(self):
		"""Return home/local/public feed for an actor.

		Query params:
		  actor_id   str   required for feed_type=home
		  tenant_id  str   required for feed_type=local
		  feed_type  str   home | local | public  (default: home)
		  limit      int   max posts to return     (default: 40)
		  before_id  str   pagination cursor post id
		"""
		session = _get_session()
		args = request.args
		feed_type = args.get("feed_type", "home")
		actor_id = args.get("actor_id", "")
		tenant_id = args.get("tenant_id", "default")

		if feed_type == "home" and not actor_id:
			return jsonify({"error": "actor_id required for home feed"}), 400

		try:
			limit = int(args.get("limit", 40))
		except ValueError:
			limit = 40

		items = _svc().get_feed(
			session=session,
			tenant_id=tenant_id,
			actor_id=actor_id,
			feed_type=feed_type,
			limit=limit,
			before_id=args.get("before_id"),
		)
		return jsonify({"feed_type": feed_type, "count": len(items), "items": items})


# ---------------------------------------------------------------------------
# NotificationView
# ---------------------------------------------------------------------------

class NotificationView(BaseView):
	"""Per-actor notification inbox."""

	route_base = "/social/notifications"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		"""List notifications for an actor.

		Query params:
		  actor_id   str   required
		  unread_only bool  default false
		  limit      int   default 50
		"""
		from pgappforge.plugins.erp.platform.social.models import Notification, Activity
		session = _get_session()
		args = request.args
		actor_id = args.get("actor_id")
		if not actor_id:
			return jsonify({"error": "actor_id required"}), 400

		unread_only = args.get("unread_only", "false").lower() == "true"
		limit = min(int(args.get("limit", 50)), 200)

		q = (
			sa.select(Notification, Activity)
			.join(Activity, Activity.id == Notification.activity_id)
			.where(Notification.recipient_id == actor_id)
			.order_by(Notification.created_at.desc())
			.limit(limit)
		)
		if unread_only:
			q = q.where(Notification.is_read.is_(False))

		rows = session.execute(q).all()
		return jsonify([
			{
				"notification_id": str(n.id),
				"notification_type": n.notification_type,
				"activity_type": a.activity_type,
				"actor_id": str(a.actor_id),
				"is_read": n.is_read,
				"created_at": n.created_at.isoformat(),
			}
			for n, a in rows
		])

	@expose("/<string:notification_id>/read", methods=["POST"])
	@has_access
	def mark_read(self, notification_id: str):
		"""Mark a single notification as read."""
		from pgappforge.plugins.erp.platform.social.models import Notification
		session = _get_session()
		notif = session.get(Notification, notification_id)
		if notif is None:
			abort(404, f"Notification {notification_id!r} not found")
		notif.is_read = True
		session.commit()
		return jsonify({"notification_id": notification_id, "is_read": True})

	@expose("/read-all", methods=["POST"])
	@has_access
	def read_all(self):
		"""Mark all notifications for an actor as read.

		Body: {"actor_id": str}
		"""
		from pgappforge.plugins.erp.platform.social.models import Notification
		session = _get_session()
		data = request.get_json(force=True) or {}
		actor_id = data.get("actor_id")
		if not actor_id:
			return jsonify({"error": "actor_id required"}), 400
		result = session.execute(
			sa.update(Notification)
			.where(
				Notification.recipient_id == actor_id,
				Notification.is_read.is_(False),
			)
			.values(is_read=True)
		)
		session.commit()
		return jsonify({"marked_read": result.rowcount})


# ---------------------------------------------------------------------------
# ActorProfileView
# ---------------------------------------------------------------------------

class ActorProfileView(BaseView):
	"""Actor profile, follower/following lists, and actor search."""

	route_base = "/social/actors"
	default_view = "profile"

	@expose("/<string:actor_id>")
	@has_access
	def profile(self, actor_id: str):
		"""Return public actor profile metadata."""
		from pgappforge.plugins.erp.platform.social.models import Actor
		session = _get_session()
		actor = session.get(Actor, actor_id)
		if actor is None:
			abort(404, f"Actor {actor_id!r} not found")
		return jsonify({
			"actor_id": str(actor.id),
			"actor_iri": actor.actor_id,
			"username": actor.username,
			"display_name": actor.display_name,
			"actor_type": actor.actor_type,
			"bio": actor.bio,
			"avatar_url": actor.avatar_url,
			"banner_url": actor.banner_url,
			"profile_url": actor.profile_url,
			"is_local": actor.is_local,
			"domain": actor.domain,
			"is_verified": actor.is_verified,
			"follower_count": actor.follower_count,
			"following_count": actor.following_count,
		})

	@expose("/<string:actor_id>/followers")
	@has_access
	def followers(self, actor_id: str):
		"""List actors following this actor (ACCEPTED follows)."""
		from pgappforge.plugins.erp.platform.social.models import Follow, Actor
		session = _get_session()
		limit = min(int(request.args.get("limit", 50)), 200)
		rows = session.execute(
			sa.select(Actor)
			.join(Follow, Follow.follower_id == Actor.id)
			.where(
				Follow.following_id == actor_id,
				Follow.status == "ACCEPTED",
			)
			.limit(limit)
		).scalars().all()
		return jsonify([
			{
				"actor_id": str(a.id),
				"username": a.username,
				"display_name": a.display_name,
				"avatar_url": a.avatar_url,
				"is_local": a.is_local,
			}
			for a in rows
		])

	@expose("/<string:actor_id>/following")
	@has_access
	def following(self, actor_id: str):
		"""List actors this actor follows (ACCEPTED follows)."""
		from pgappforge.plugins.erp.platform.social.models import Follow, Actor
		session = _get_session()
		limit = min(int(request.args.get("limit", 50)), 200)
		rows = session.execute(
			sa.select(Actor)
			.join(Follow, Follow.following_id == Actor.id)
			.where(
				Follow.follower_id == actor_id,
				Follow.status == "ACCEPTED",
			)
			.limit(limit)
		).scalars().all()
		return jsonify([
			{
				"actor_id": str(a.id),
				"username": a.username,
				"display_name": a.display_name,
				"avatar_url": a.avatar_url,
				"is_local": a.is_local,
			}
			for a in rows
		])

	@expose("/<string:follower_id>/follow", methods=["POST"])
	@has_access
	def follow(self, follower_id: str):
		"""Create a follow from follower_id to a target actor.

		Body: {"target_handle": str, "tenant_id": str}
		"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("target_handle"):
			return jsonify({"error": "target_handle required"}), 400
		try:
			follow = _svc().follow_actor(
				session=session,
				tenant_id=data.get("tenant_id", "default"),
				follower_id=follower_id,
				target_handle=data["target_handle"],
			)
			session.commit()
			return jsonify({
				"follow_id": follow.id,
				"follower_id": str(follow.follower_id),
				"following_id": str(follow.following_id),
				"status": follow.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


class ActorSearchView(BaseView):
	"""Actor search endpoint."""

	route_base = "/social/search"
	default_view = "actors"

	@expose("/actors")
	@has_access
	def actors(self):
		"""Search actors.

		Query params:
		  q           str   required  search term or @user@domain handle
		  tenant_id   str   optional
		  local_only  bool  default false
		  limit       int   default 20
		"""
		session = _get_session()
		args = request.args
		q = args.get("q", "").strip()
		if not q:
			return jsonify({"error": "q (search query) required"}), 400
		limit = min(int(args.get("limit", 20)), 100)
		local_only = args.get("local_only", "false").lower() == "true"
		results = _svc().search_actors(
			session=session,
			tenant_id=args.get("tenant_id", "default"),
			query=q,
			local_only=local_only,
			limit=limit,
		)
		return jsonify({"count": len(results), "actors": results})


__all__ = [
	"PostView",
	"FeedView",
	"NotificationView",
	"ActorProfileView",
	"ActorSearchView",
]
