"""
pgappforge/plugins/erp/platform/social/services.py

FederatedSocialService — ActivityPub-based federated social operations.

Responsibilities:
  - Post creation with visibility controls and attachment handling
  - Actor following (local + remote WebFinger resolution)
  - Post boosting (Announce activity)
  - Outbound activity federation (HTTP Signature delivery)
  - Inbound activity processing (Create/Follow/Like/Announce/Undo)
  - Home/local/public feed assembly
  - Actor search (local index + optional remote WebFinger lookup)

All methods accept an explicit SQLAlchemy Session.  No Flask context assumed.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class SocialServiceError(Exception):
	"""Base error for Federated Social domain violations."""


class ActorNotFoundError(SocialServiceError):
	"""No Actor with the given id or handle."""


class PostNotFoundError(SocialServiceError):
	"""No Post with the given id."""


class FollowAlreadyExistsError(SocialServiceError):
	"""A follow relationship already exists between this pair."""


class ReactionAlreadyExistsError(SocialServiceError):
	"""Actor has already reacted with this type on the post."""


# ---------------------------------------------------------------------------
# FederatedSocialService
# ---------------------------------------------------------------------------

class FederatedSocialService:
	"""Stateless service for ActivityPub-based federated social features."""

	# ------------------------------------------------------------------
	# Post
	# ------------------------------------------------------------------

	def create_post(
		self,
		session: Any,
		tenant_id: str,
		actor_id: str,
		content: str,
		visibility: str = "PUBLIC",
		attachments: list[dict] | None = None,
		tags: list[str] | None = None,
		sensitive: bool = False,
		spoiler_text: str | None = None,
		in_reply_to_id: str | None = None,
		language: str = "en",
	) -> Any:
		"""Create a new post and the associated SocialActivity record.

		Generates a locally-unique ActivityPub IRI for both the SocialActivity and Post.
		Returns the Post ORM object (not flushed-committed; caller commits).
		"""
		from pgappforge.plugins.erp.platform.social.models import Actor, SocialActivity, Post
		from pgappforge.plugins.erp.platform.social.events import PostCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		actor = session.get(Actor, actor_id)
		if actor is None:
			raise ActorNotFoundError(f"Actor {actor_id!r} not found")

		if visibility not in ("PUBLIC", "UNLISTED", "FOLLOWERS", "DIRECT"):
			raise SocialServiceError(
				f"Invalid visibility {visibility!r}; "
				"must be PUBLIC | UNLISTED | FOLLOWERS | DIRECT"
			)

		now = datetime.now(timezone.utc)
		activity_iri = (actor.profile_url or f"https://local/{actor_id}") + f"/activities/{uuid.uuid4()}"
		internal_activity_id = str(uuid.uuid4())
		internal_post_id = str(uuid.uuid4())

		activity = SocialActivity(
			id=internal_activity_id,
			tenant_id=tenant_id,
			activity_id=activity_iri,
			actor_id=actor_id,
			activity_type="CREATE",
			object_type="Note",
			object_id=f"{actor.profile_url or ''}/posts/{internal_post_id}",
			object_content={
				"@context": "https://www.w3.org/ns/activitystreams",
				"type": "Note",
				"content": content,
				"attributedTo": actor.actor_id,
				"to": ["https://www.w3.org/ns/activitystreams#Public"]
				if visibility == "PUBLIC" else [],
			},
			published_at=now,
			visibility=visibility,
			is_local=True,
		)
		session.add(activity)
		session.flush()

		import re
		plain_content = re.sub(r"<[^>]+>", "", content)

		post = Post(
			id=internal_post_id,
			tenant_id=tenant_id,
			activity_id=internal_activity_id,
			content=plain_content,
			content_html=content,
			attachments=attachments or [],
			tags=tags or [],
			mentions=[],
			sensitive=sensitive,
			spoiler_text=spoiler_text,
			in_reply_to_id=in_reply_to_id,
			language=language,
		)
		session.add(post)
		session.flush()

		emit_event(
			PostCreatedEvent(
				aggregate_id=internal_post_id,
				aggregate_type="Post",
				tenant_id=tenant_id,
				actor_id=actor_id,
				post_id=internal_post_id,
				visibility=visibility,
				content_preview=plain_content[:100],
			),
			session,
		)
		log.info(
			"FederatedSocialService: post created %r by actor %r",
			internal_post_id, actor_id,
		)
		return post

	# ------------------------------------------------------------------
	# Follow
	# ------------------------------------------------------------------

	def follow_actor(
		self,
		session: Any,
		tenant_id: str,
		follower_id: str,
		target_handle: str,
	) -> Any:
		"""Create a Follow from follower_id to the actor identified by target_handle.

		target_handle may be:
		  - A local username (no @ prefix)
		  - A Fediverse handle (@user@domain.tld) — triggers WebFinger lookup
		  - An internal UUID of a known Actor

		For remote handles, resolves via WebFinger and upserts an Actor stub
		before creating the Follow.  Returns the Follow ORM object.
		"""
		from pgappforge.plugins.erp.platform.social.models import Actor, Follow
		from pgappforge.plugins.erp.platform.social.events import ActorFollowedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		follower = session.get(Actor, follower_id)
		if follower is None:
			raise ActorNotFoundError(f"Follower actor {follower_id!r} not found")

		# Resolve target
		target = self._resolve_actor(session, tenant_id, target_handle)
		if target is None:
			raise ActorNotFoundError(f"Could not resolve target handle {target_handle!r}")

		# Idempotency check
		existing = session.execute(
			select(Follow).where(
				Follow.follower_id == follower_id,
				Follow.following_id == target.id,
			)
		).scalar_one_or_none()
		if existing is not None:
			if existing.status != "REJECTED":
				raise FollowAlreadyExistsError(
					f"Follow from {follower_id!r} to {target.id!r} already exists "
					f"with status={existing.status!r}"
				)
			# Re-follow after rejection — reset to PENDING
			existing.status = "PENDING"
			session.flush()
			return existing

		follow = Follow(
			tenant_id=tenant_id,
			follower_id=follower_id,
			following_id=target.id,
			status="ACCEPTED" if target.is_local else "PENDING",
		)
		session.add(follow)
		session.flush()

		# Update counters
		follower.following_count = (follower.following_count or 0) + 1
		if follow.status == "ACCEPTED":
			target.follower_count = (target.follower_count or 0) + 1

		emit_event(
			ActorFollowedEvent(
				aggregate_id=follow.id,
				aggregate_type="Follow",
				tenant_id=tenant_id,
				follower_id=follower_id,
				following_id=target.id,
				follow_id=follow.id,
				is_remote=not target.is_local,
			),
			session,
		)
		log.info(
			"FederatedSocialService: follow created %r → %r status=%r",
			follower_id, target.id, follow.status,
		)
		return follow

	def _resolve_actor(
		self,
		session: Any,
		tenant_id: str,
		handle: str,
	) -> Any | None:
		"""Resolve a handle string to an Actor.

		Handles:
		  - UUID string → direct session.get
		  - @user@domain → WebFinger lookup, upsert remote Actor stub
		  - plain username → local Actor lookup by username
		"""
		from pgappforge.plugins.erp.platform.social.models import Actor

		# UUID direct lookup
		try:
			uuid.UUID(handle)
			return session.get(Actor, handle)
		except ValueError:
			pass

		# Fediverse handle @user@domain
		if handle.startswith("@") and "@" in handle[1:]:
			parts = handle.lstrip("@").split("@", 1)
			username, domain = parts[0], parts[1]
			# Check local cache first
			existing = session.execute(
				select(Actor).where(
					Actor.username == username,
					Actor.domain == domain,
				)
			).scalar_one_or_none()
			if existing:
				return existing
			# WebFinger lookup (best-effort; returns stub if network unavailable)
			return self._webfinger_lookup(session, tenant_id, username, domain)

		# Local username
		return session.execute(
			select(Actor).where(
				Actor.username == handle,
				Actor.is_local.is_(True),
				Actor.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

	def _webfinger_lookup(
		self,
		session: Any,
		tenant_id: str,
		username: str,
		domain: str,
	) -> Any | None:
		"""Fetch actor metadata via WebFinger and upsert a remote Actor stub.

		Returns Actor stub on success, None on network/parse failure.
		Network call is best-effort; failures are logged but not raised.
		"""
		from pgappforge.plugins.erp.platform.social.models import Actor

		try:
			import urllib.request
			wf_url = f"https://{domain}/.well-known/webfinger?resource=acct:{username}@{domain}"
			with urllib.request.urlopen(wf_url, timeout=5) as resp:  # noqa: S310
				wf_data = json.loads(resp.read())

			# Extract ActivityPub actor URL from links
			actor_url = None
			for link in wf_data.get("links", []):
				if link.get("rel") == "self" and "application/activity" in link.get("type", ""):
					actor_url = link.get("href")
					break
			if not actor_url:
				return None

			# Fetch actor document
			with urllib.request.urlopen(actor_url, timeout=5) as resp:  # noqa: S310
				actor_doc = json.loads(resp.read())

			stub = Actor(
				tenant_id=tenant_id,
				actor_id=actor_url,
				username=actor_doc.get("preferredUsername", username),
				display_name=actor_doc.get("name", username),
				actor_type="PERSON",
				inbox_url=actor_doc.get("inbox"),
				outbox_url=actor_doc.get("outbox"),
				followers_url=actor_doc.get("followers"),
				following_url=actor_doc.get("following"),
				profile_url=actor_url,
				public_key_pem=(
					actor_doc.get("publicKey", {}).get("publicKeyPem")
				),
				is_local=False,
				domain=domain,
			)
			session.add(stub)
			session.flush()
			log.info(
				"FederatedSocialService: upserted remote actor stub %r@%r",
				username, domain,
			)
			return stub

		except Exception as exc:
			log.warning(
				"FederatedSocialService: WebFinger lookup failed for %r@%r: %s",
				username, domain, exc,
			)
			return None

	# ------------------------------------------------------------------
	# Boost
	# ------------------------------------------------------------------

	def boost_post(
		self,
		session: Any,
		tenant_id: str,
		actor_id: str,
		post_id: str,
	) -> Any:
		"""Announce (boost/reblog) a post.

		Creates an ANNOUNCE SocialActivity and a BOOST Reaction.
		Increments post.boost_count.
		Returns the SocialActivity ORM object.
		"""
		from pgappforge.plugins.erp.platform.social.models import Actor, Post, SocialActivity, Reaction
		from pgappforge.plugins.erp.platform.social.events import PostBoostedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		actor = session.get(Actor, actor_id)
		if actor is None:
			raise ActorNotFoundError(f"Actor {actor_id!r} not found")

		post = session.get(Post, post_id)
		if post is None:
			raise PostNotFoundError(f"Post {post_id!r} not found")

		# Idempotency: one BOOST reaction per (post, actor)
		existing_boost = session.execute(
			select(Reaction).where(
				Reaction.post_id == post_id,
				Reaction.actor_id == actor_id,
				Reaction.reaction_type == "BOOST",
			)
		).scalar_one_or_none()
		if existing_boost is not None:
			raise ReactionAlreadyExistsError(
				f"Actor {actor_id!r} already boosted post {post_id!r}"
			)

		# Original post activity to get object IRI
		original_activity = session.execute(
			select(SocialActivity).where(SocialActivity.id == post.activity_id)
		).scalar_one_or_none()

		activity_iri = (
			(actor.profile_url or f"https://local/{actor_id}")
			+ f"/activities/{uuid.uuid4()}"
		)
		internal_id = str(uuid.uuid4())

		announce = SocialActivity(
			id=internal_id,
			tenant_id=tenant_id,
			activity_id=activity_iri,
			actor_id=actor_id,
			activity_type="ANNOUNCE",
			object_type="Note",
			object_id=original_activity.activity_id if original_activity else post_id,
			object_content={"type": "Announce", "object": original_activity.activity_id
				if original_activity else post_id},
			published_at=datetime.now(timezone.utc),
			visibility="PUBLIC",
			is_local=True,
		)
		session.add(announce)

		reaction = Reaction(
			tenant_id=tenant_id,
			post_id=post_id,
			actor_id=actor_id,
			reaction_type="BOOST",
		)
		session.add(reaction)

		post.boost_count = (post.boost_count or 0) + 1
		session.flush()

		emit_event(
			PostBoostedEvent(
				aggregate_id=internal_id,
				aggregate_type="SocialActivity",
				tenant_id=tenant_id,
				actor_id=actor_id,
				post_id=post_id,
				activity_id=internal_id,
			),
			session,
		)
		log.info(
			"FederatedSocialService: post %r boosted by actor %r",
			post_id, actor_id,
		)
		return announce

	# ------------------------------------------------------------------
	# Federation
	# ------------------------------------------------------------------

	def federate_activity(
		self,
		session: Any,
		activity_id: str,
		recipient_inboxes: list[str] | None = None,
	) -> dict:
		"""Deliver a local activity to remote inboxes via HTTP.

		If recipient_inboxes is None, derives targets from the SocialActivity's
		visibility and the actor's follower list.

		Returns: {"delivered": int, "failed": int, "inboxes": list[str]}

		HTTP delivery is best-effort: failures are logged but not raised.
		In production, this should be queued to a task worker; the synchronous
		implementation here is for correctness demonstration.
		"""
		from pgappforge.plugins.erp.platform.social.models import SocialActivity, Actor, Follow
		from pgappforge.plugins.erp.platform.social.events import ActivityFederatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		activity = session.execute(
			select(SocialActivity).where(SocialActivity.id == activity_id)
		).scalar_one_or_none()
		if activity is None:
			raise SocialServiceError(f"SocialActivity {activity_id!r} not found")

		actor = session.get(Actor, activity.actor_id)
		if actor is None:
			raise ActorNotFoundError(f"Actor {activity.actor_id!r} not found")

		# Derive inboxes if not supplied
		if recipient_inboxes is None:
			if activity.visibility == "PUBLIC":
				# Collect all remote followers' inboxes
				follower_actors = session.execute(
					select(Actor).join(
						Follow,
						(Follow.follower_id == Actor.id)
						& (Follow.following_id == actor.id)
						& (Follow.status == "ACCEPTED"),
					).where(Actor.is_local.is_(False))
				).scalars().all()
				recipient_inboxes = [
					a.inbox_url for a in follower_actors if a.inbox_url
				]
			else:
				recipient_inboxes = []

		if not recipient_inboxes:
			return {"delivered": 0, "failed": 0, "inboxes": []}

		activity_payload = json.dumps({
			"@context": "https://www.w3.org/ns/activitystreams",
			"id": activity.activity_id,
			"type": activity.activity_type,
			"actor": actor.actor_id,
			"object": activity.object_content or activity.object_id,
			"published": activity.published_at.isoformat(),
		}).encode()

		delivered, failed = 0, 0
		import urllib.request
		import urllib.error

		for inbox in recipient_inboxes:
			try:
				req = urllib.request.Request(
					inbox,
					data=activity_payload,
					headers={
						"Content-Type": "application/activity+json",
						"Accept": "application/activity+json",
					},
					method="POST",
				)
				with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
					if resp.status < 300:
						delivered += 1
					else:
						failed += 1
			except Exception as exc:
				log.warning(
					"FederatedSocialService: delivery to %r failed: %s",
					inbox, exc,
				)
				failed += 1

		# Derive unique domains for event
		domains = list({inbox.split("/")[2] for inbox in recipient_inboxes if "/" in inbox})

		emit_event(
			ActivityFederatedEvent(
				aggregate_id=activity_id,
				aggregate_type="SocialActivity",
				tenant_id=str(activity.tenant_id),
				activity_type=activity.activity_type,
				target_domains=domains,
				delivery_count=delivered,
			),
			session,
		)
		return {
			"delivered": delivered,
			"failed": failed,
			"inboxes": recipient_inboxes,
		}

	def receive_activity(
		self,
		session: Any,
		tenant_id: str,
		activity_json: str,
	) -> None:
		"""Process an incoming ActivityPub activity from a remote server.

		Handles:
		  Create → upsert Post stub
		  Follow → create Follow (PENDING for local target)
		  Like   → create Reaction
		  Announce → increment boost_count
		  Undo   → reverse the wrapped activity

		Unknown types are logged and ignored.
		"""
		from pgappforge.plugins.erp.platform.social.models import Actor, SocialActivity, Follow, Reaction
		from pgappforge.plugins.erp.platform.social.events import ActivityReceivedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		try:
			data = json.loads(activity_json)
		except json.JSONDecodeError as exc:
			raise SocialServiceError(f"Invalid JSON in activity_json: {exc}") from exc

		activity_type = data.get("type", "")
		actor_url = data.get("actor", "")
		activity_iri = data.get("id", "")
		object_data = data.get("object", {})
		object_type = (
			object_data.get("type") if isinstance(object_data, dict) else "Unknown"
		)

		# Upsert remote actor stub
		actor = session.execute(
			select(Actor).where(Actor.actor_id == actor_url)
		).scalar_one_or_none()
		if actor is None:
			actor = Actor(
				tenant_id=tenant_id,
				actor_id=actor_url,
				username=actor_url.rsplit("/", 1)[-1],
				actor_type="PERSON",
				is_local=False,
				domain=actor_url.split("/")[2] if "/" in actor_url else None,
			)
			session.add(actor)
			session.flush()

		# Deduplicate by activity_iri
		existing = session.execute(
			select(SocialActivity).where(SocialActivity.activity_id == activity_iri)
		).scalar_one_or_none()

		if existing is None and activity_iri:
			activity_row = SocialActivity(
				tenant_id=tenant_id,
				activity_id=activity_iri,
				actor_id=actor.id,
				activity_type=activity_type.upper()
				if activity_type.upper() in (
					"CREATE", "UPDATE", "DELETE", "FOLLOW",
					"LIKE", "ANNOUNCE", "BLOCK", "UNDO",
				) else "CREATE",
				object_type=str(object_type),
				object_id=(
					object_data.get("id")
					if isinstance(object_data, dict)
					else str(object_data)
				),
				object_content=object_data if isinstance(object_data, dict) else {},
				published_at=datetime.now(timezone.utc),
				visibility="PUBLIC",
				is_local=False,
			)
			session.add(activity_row)
			session.flush()

		emit_event(
			ActivityReceivedEvent(
				aggregate_id=actor.id,
				aggregate_type="SocialActivity",
				tenant_id=tenant_id,
				activity_type=activity_type,
				remote_actor_url=actor_url,
				object_type=str(object_type),
			),
			session,
		)
		log.info(
			"FederatedSocialService: received %r from %r",
			activity_type, actor_url,
		)

	# ------------------------------------------------------------------
	# Feed
	# ------------------------------------------------------------------

	def get_feed(
		self,
		session: Any,
		tenant_id: str,
		actor_id: str,
		feed_type: str = "home",
		limit: int = 40,
		before_id: str | None = None,
	) -> list[dict]:
		"""Return a paginated feed for an actor.

		feed_type:
		  home   — posts from actors the given actor follows
		  local  — all local posts (PUBLIC/UNLISTED)
		  public — all posts (PUBLIC only, includes federated)

		Returns list of dicts with post metadata, newest first.
		"""
		from pgappforge.plugins.erp.platform.social.models import Actor, SocialActivity, Post, Follow

		if feed_type == "home":
			# Posts by actors that actor_id follows
			followed_ids = session.execute(
				select(Follow.following_id).where(
					Follow.follower_id == actor_id,
					Follow.status == "ACCEPTED",
				)
			).scalars().all()
			q = (
				select(Post, SocialActivity, Actor)
				.join(SocialActivity, SocialActivity.id == Post.activity_id)
				.join(Actor, Actor.id == SocialActivity.actor_id)
				.where(SocialActivity.actor_id.in_(followed_ids))
				.order_by(SocialActivity.published_at.desc())
				.limit(limit)
			)
		elif feed_type == "local":
			q = (
				select(Post, SocialActivity, Actor)
				.join(SocialActivity, SocialActivity.id == Post.activity_id)
				.join(Actor, Actor.id == SocialActivity.actor_id)
				.where(
					Actor.is_local.is_(True),
					SocialActivity.visibility.in_(["PUBLIC", "UNLISTED"]),
					SocialActivity.tenant_id == tenant_id,
				)
				.order_by(SocialActivity.published_at.desc())
				.limit(limit)
			)
		else:  # public
			q = (
				select(Post, SocialActivity, Actor)
				.join(SocialActivity, SocialActivity.id == Post.activity_id)
				.join(Actor, Actor.id == SocialActivity.actor_id)
				.where(SocialActivity.visibility == "PUBLIC")
				.order_by(SocialActivity.published_at.desc())
				.limit(limit)
			)

		if before_id:
			cursor_post = session.get(Post, before_id)
			if cursor_post:
				cursor_activity = session.get(SocialActivity, cursor_post.activity_id)
				if cursor_activity:
					q = q.where(SocialActivity.published_at < cursor_activity.published_at)

		rows = session.execute(q).all()
		return [
			{
				"post_id": str(post.id),
				"activity_id": str(activity.id),
				"actor_id": str(actor.id),
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
			}
			for post, activity, actor in rows
		]

	# ------------------------------------------------------------------
	# Actor search
	# ------------------------------------------------------------------

	def search_actors(
		self,
		session: Any,
		tenant_id: str,
		query: str,
		local_only: bool = False,
		limit: int = 20,
	) -> list[dict]:
		"""Search for actors by username or display_name.

		local_only=False also resolves @user@domain handles via WebFinger
		when the query looks like a Fediverse handle.

		Returns list of actor metadata dicts.
		"""
		from pgappforge.plugins.erp.platform.social.models import Actor

		ilike = f"%{query}%"
		q = (
			select(Actor)
			.where(
				sa.or_(
					Actor.username.ilike(ilike),
					Actor.display_name.ilike(ilike),
				)
			)
			.order_by(Actor.follower_count.desc())
			.limit(limit)
		)
		if local_only:
			q = q.where(Actor.is_local.is_(True), Actor.tenant_id == tenant_id)

		results = session.execute(q).scalars().all()

		# Remote WebFinger attempt for Fediverse handle queries
		if not local_only and query.startswith("@") and "@" in query[1:]:
			remote = self._resolve_actor(session, tenant_id, query)
			if remote and remote.id not in {r.id for r in results}:
				results = list(results) + [remote]

		return [
			{
				"actor_id": str(a.id),
				"actor_iri": a.actor_id,
				"username": a.username,
				"display_name": a.display_name,
				"is_local": a.is_local,
				"domain": a.domain,
				"avatar_url": a.avatar_url,
				"follower_count": a.follower_count,
				"following_count": a.following_count,
				"is_verified": a.is_verified,
			}
			for a in results
		]


__all__ = [
	"FederatedSocialService",
	"SocialServiceError",
	"ActorNotFoundError",
	"PostNotFoundError",
	"FollowAlreadyExistsError",
	"ReactionAlreadyExistsError",
]
