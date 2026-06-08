"""
pgappforge/plugins/erp/platform/discuss/views.py

Flask views for the Discuss (team messaging) plugin.

Registered views:
  DiscussChannelView   — CRUD + archive action
  DiscussMessageView   — CRUD + reactions
  DiscussReportView    — Dashboard with KPI tiles:
                         total_channels, messages_today, active_users
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

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
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>body{padding:24px}</style>'
		f'</head><body>{body}</body></html>'
	)


# ---------------------------------------------------------------------------
# DiscussChannelView
# ---------------------------------------------------------------------------

class DiscussChannelView(BaseERPView):
	"""Team/direct messaging channel CRUD + archive.

	GET  /discuss/channels/               — list
	GET  /discuss/channels/<id>           — detail with members
	POST /discuss/channels/               — create
	PUT  /discuss/channels/<id>           — update
	POST /discuss/channels/<id>/archive   — set is_archived=True
	POST /discuss/channels/<id>/members   — add member
	"""

	route_base = "/discuss/channels"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussChannel
		session = _get_session()
		q = sa.select(DiscussChannel).where(DiscussChannel.is_archived.is_(False))
		if request.args.get("tenant_id"):
			q = q.where(DiscussChannel.tenant_id == request.args["tenant_id"])
		if request.args.get("channel_type"):
			q = q.where(DiscussChannel.channel_type == request.args["channel_type"])
		channels = session.execute(q.order_by(DiscussChannel.name).limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"channels": [
				{
					"id": c.id, "name": c.name, "channel_type": c.channel_type,
					"description": c.description, "created_by": c.created_by,
					"is_archived": c.is_archived,
					"linked_module": c.linked_module,
					"linked_record_id": c.linked_record_id,
				}
				for c in channels
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(c.name)}</td>"
			f"<td>{_he(c.channel_type)}</td>"
			f"<td>{_he(c.description or '')}</td>"
			f"<td>{_he(c.created_by)}</td>"
			f"<td><a href='/discuss/channels/{_he(c.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for c in channels
		)
		body = (
			'<h3>Discuss Channels</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Name</th><th>Type</th><th>Description</th>'
			'<th>Created By</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Discuss Channels", body), 200)

	@expose("/<string:channel_id>")
	@has_access
	def detail(self, channel_id: str):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussChannel
		session = _get_session()
		c = session.get(DiscussChannel, channel_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id,
			"name": c.name, "description": c.description,
			"channel_type": c.channel_type, "created_by": c.created_by,
			"is_archived": c.is_archived,
			"linked_module": c.linked_module, "linked_record_id": c.linked_record_id,
			"avatar_url": c.avatar_url,
			"members": [
				{
					"id": m.id, "member_id": m.member_id, "role": m.role,
					"joined_at": m.joined_at.isoformat() if m.joined_at else None,
					"is_muted": m.is_muted,
				}
				for m in c.members
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussChannel
		session = _get_session()
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "name", "created_by") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		c = DiscussChannel(
			tenant_id=data["tenant_id"],
			name=data["name"],
			description=data.get("description"),
			channel_type=data.get("channel_type", "PUBLIC"),
			created_by=data["created_by"],
			linked_module=data.get("linked_module"),
			linked_record_id=data.get("linked_record_id"),
			avatar_url=data.get("avatar_url"),
		)
		session.add(c)
		session.commit()
		return jsonify({"ok": True, "id": c.id}), 201

	@expose("/<string:channel_id>", methods=["PUT"])
	@has_access
	def update(self, channel_id: str):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussChannel
		session = _get_session()
		c = session.get(DiscussChannel, channel_id)
		if c is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "description", "avatar_url", "linked_module", "linked_record_id"):
			if f in data:
				setattr(c, f, data[f])
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:channel_id>/archive", methods=["POST"])
	@has_access
	def archive(self, channel_id: str):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussChannel
		session = _get_session()
		c = session.get(DiscussChannel, channel_id)
		if c is None:
			abort(404)
		c.is_archived = True
		session.commit()
		return jsonify({"ok": True, "is_archived": True})

	@expose("/<string:channel_id>/members", methods=["POST"])
	@has_access
	def add_member(self, channel_id: str):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussChannelMember
		session = _get_session()
		data = request.get_json(silent=True) or {}
		member_id = data.get("member_id")
		if not member_id:
			return jsonify({"ok": False, "error": "member_id required"}), 400
		m = DiscussChannelMember(
			channel_id=channel_id,
			member_id=member_id,
			role=data.get("role", "MEMBER"),
		)
		session.add(m)
		try:
			session.commit()
		except Exception as exc:
			session.rollback()
			return jsonify({"ok": False, "error": str(exc)}), 409
		return jsonify({"ok": True, "id": m.id}), 201


# ---------------------------------------------------------------------------
# DiscussMessageView
# ---------------------------------------------------------------------------

class DiscussMessageView(BaseERPView):
	"""Channel message CRUD.

	GET  /discuss/channels/<cid>/messages/        — list messages (paginated)
	POST /discuss/channels/<cid>/messages/        — post message
	POST /discuss/channels/<cid>/messages/<id>/react — toggle emoji reaction
	POST /discuss/channels/<cid>/messages/<id>/delete — soft-delete
	"""

	route_base = "/discuss/channels"
	default_view = "messages"

	@expose("/<string:channel_id>/messages/")
	@has_access
	def messages(self, channel_id: str):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussMessage
		session = _get_session()
		limit = int(request.args.get("limit", 50))
		before = request.args.get("before")  # message id for cursor pagination
		q = (
			sa.select(DiscussMessage)
			.where(
				DiscussMessage.channel_id == channel_id,
				DiscussMessage.is_deleted.is_(False),
				DiscussMessage.parent_message_id.is_(None),
			)
			.order_by(sa.desc(DiscussMessage.created_at))
			.limit(limit)
		)
		if before:
			msg = session.get(DiscussMessage, before)
			if msg:
				q = q.where(DiscussMessage.created_at < msg.created_at)
		msgs = session.execute(q).scalars().all()
		return jsonify({"messages": [
			{
				"id": m.id, "author_id": m.author_id,
				"body": m.body, "message_type": m.message_type,
				"created_at": m.created_at.isoformat() if m.created_at else None,
				"is_edited": m.is_edited, "reply_count": m.reply_count,
				"reactions": m.reactions, "attachments": m.attachments,
			}
			for m in msgs
		]})

	@expose("/<string:channel_id>/messages/", methods=["POST"])
	@has_access
	def post_message(self, channel_id: str):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussMessage
		session = _get_session()
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "author_id", "body") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		msg = DiscussMessage(
			tenant_id=data["tenant_id"],
			channel_id=channel_id,
			author_id=data["author_id"],
			body=data["body"],
			message_type=data.get("message_type", "TEXT"),
			parent_message_id=data.get("parent_message_id"),
			attachments=data.get("attachments") or [],
		)
		session.add(msg)
		# increment reply_count on parent
		if msg.parent_message_id:
			parent = session.get(DiscussMessage, msg.parent_message_id)
			if parent:
				parent.reply_count += 1
		session.commit()
		return jsonify({"ok": True, "id": msg.id}), 201

	@expose("/<string:channel_id>/messages/<string:msg_id>/react", methods=["POST"])
	@has_access
	def react(self, channel_id: str, msg_id: str):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussMessage
		session = _get_session()
		msg = session.get(DiscussMessage, msg_id)
		if msg is None or str(msg.channel_id) != channel_id:
			abort(404)
		data = request.get_json(silent=True) or {}
		emoji = data.get("emoji")
		user_id = data.get("user_id")
		if not emoji or not user_id:
			return jsonify({"ok": False, "error": "emoji and user_id required"}), 400
		reactions: dict = dict(msg.reactions or {})
		users: list = list(reactions.get(emoji, []))
		if user_id in users:
			users.remove(user_id)
		else:
			users.append(user_id)
		if users:
			reactions[emoji] = users
		else:
			reactions.pop(emoji, None)
		msg.reactions = reactions
		session.commit()
		return jsonify({"ok": True, "reactions": msg.reactions})

	@expose("/<string:channel_id>/messages/<string:msg_id>/delete", methods=["POST"])
	@has_access
	def soft_delete(self, channel_id: str, msg_id: str):
		from pgappforge.plugins.erp.platform.discuss.models import DiscussMessage
		session = _get_session()
		msg = session.get(DiscussMessage, msg_id)
		if msg is None or str(msg.channel_id) != channel_id:
			abort(404)
		msg.is_deleted = True
		msg.body = "[deleted]"
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# DiscussReportView — dashboard
# ---------------------------------------------------------------------------

class DiscussReportView(BaseERPView):
	"""Discuss dashboard.

	GET /discuss/reports/    — KPI tiles: total_channels, messages_today, active_users
	"""

	route_base = "/discuss/reports"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		"""Discuss dashboard — total channels, messages today, active users."""
		from pgappforge.plugins.erp.platform.discuss.models import DiscussChannel, DiscussMessage
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		total_channels: int = 0
		messages_today: int = 0
		active_users: int = 0

		try:
			total_channels = session.execute(
				sa.select(sa.func.count()).select_from(DiscussChannel).where(
					DiscussChannel.is_archived.is_(False),
					*([DiscussChannel.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			from datetime import date as _date
			today_start = datetime.combine(_date.today(), datetime.min.time()).replace(
				tzinfo=timezone.utc
			)
			messages_today = session.execute(
				sa.select(sa.func.count()).select_from(DiscussMessage).where(
					DiscussMessage.created_at >= today_start,
					DiscussMessage.is_deleted.is_(False),
					*([DiscussMessage.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			active_users = session.execute(
				sa.select(sa.func.count(sa.func.distinct(DiscussMessage.author_id))).where(
					DiscussMessage.created_at >= today_start,
					DiscussMessage.is_deleted.is_(False),
					*([DiscussMessage.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Total Channels", "value": total_channels, "format": "integer",
			 "color": "#1a56db", "icon": "fa-comments"},
			{"label": "Messages Today", "value": messages_today, "format": "integer",
			 "color": "#057a55", "icon": "fa-comment"},
			{"label": "Active Users", "value": active_users, "format": "integer",
			 "color": "#9061f9", "icon": "fa-users"},
		])

		if request.args.get("format") == "json":
			return jsonify({
				"total_channels": total_channels,
				"messages_today": messages_today,
				"active_users": active_users,
			})

		body = (
			"<h3>Discuss Dashboard</h3>"
			+ str(kpi_html)
			+ '<p><a href="/discuss/channels/" class="btn btn-default">All Channels</a></p>'
		)
		return make_response(_page_html("Discuss Dashboard", body), 200)


__all__ = [
	"DiscussChannelView",
	"DiscussMessageView",
	"DiscussReportView",
]
