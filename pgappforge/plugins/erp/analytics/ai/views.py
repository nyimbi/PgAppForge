"""
pgappforge/plugins/erp/analytics/ai/views.py

Flask views for the AI Agents plugin.

Route summary
-------------
AIAgentView           /analytics/ai/agents/
  ├─ GET  /                         — agent registry (HTML)
  ├─ POST /                         — create agent (JSON)
  └─ PUT  /<id>                     — update agent (JSON)
ConversationView      /analytics/ai/conversations/
  ├─ GET  /                         — recent conversations (HTML)
  ├─ POST /                         — start conversation (JSON)
  ├─ POST /<id>/message             — append message (JSON)
  └─ POST /<id>/end                 — end conversation (JSON)
ActionView            /analytics/ai/actions/
  ├─ GET  /pending                  — pending actions requiring approval (HTML)
  ├─ POST /<id>/approve             — approve action (JSON)
  ├─ POST /<id>/reject              — reject action (JSON)
  └─ POST /<id>/execute             — execute action (JSON)
AIReportView          /analytics/ai/reports/
  ├─ GET  /agent_usage              — agent usage summary (HTML)
  └─ GET  /token_spend              — token spend by model (JSON)
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
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


# ---------------------------------------------------------------------------
# AIAgentView
# ---------------------------------------------------------------------------

class AIAgentView(BaseView):
	route_base = "/analytics/ai/agents"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.ai.models import AIAgent
		rows = session.execute(
			sa.select(AIAgent).order_by(AIAgent.agent_type, AIAgent.agent_name)
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.agent_name)}</td><td>{_he(r.agent_type)}</td>"
			f"<td>{_he(r.model_id)}</td>"
			f"<td>{'Active' if r.is_active else 'Inactive'}</td>"
			f"<td>{_he(len(r.tools_config or []))}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>AI Agents</h2>"
			"<table><thead><tr><th>Name</th><th>Type</th>"
			"<th>Model</th><th>Status</th><th>Tools</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from flask_login import current_user
		from pgappforge.plugins.erp.analytics.ai.models import AIAgent
		agent = AIAgent(
			tenant_id=data["tenant_id"],
			agent_name=data["agent_name"],
			agent_type=data.get("agent_type", "ASSISTANT"),
			model_id=data["model_id"],
			system_prompt=data.get("system_prompt"),
			tools_config=data.get("tools_config", []),
			guardrails=data.get("guardrails", {}),
			is_active=data.get("is_active", True),
			created_by=getattr(current_user, "id", None),
		)
		session.add(agent)
		session.commit()
		return jsonify({"id": agent.id, "agent_name": agent.agent_name}), 201


# ---------------------------------------------------------------------------
# ConversationView
# ---------------------------------------------------------------------------

class ConversationView(BaseView):
	route_base = "/analytics/ai/conversations"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.ai.models import AgentConversation
		rows = session.execute(
			sa.select(AgentConversation)
			.order_by(AgentConversation.started_at.desc())
			.limit(100)
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.agent_id)}</td>"
			f"<td>{_he(r.started_at.strftime('%Y-%m-%d %H:%M'))}</td>"
			f"<td>{_he(r.ended_at.strftime('%H:%M') if r.ended_at else 'Open')}</td>"
			f"<td>{_he(r.message_count)}</td>"
			f"<td>{_he(r.rating or '—')}</td>"
			f"<td>{_he((r.outcome or '')[:60])}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Agent Conversations</h2>"
			"<table><thead><tr><th>Agent</th><th>Started</th><th>Ended</th>"
			"<th>Messages</th><th>Rating</th><th>Outcome</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/", methods=["POST"])
	@has_access
	def start(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from flask_login import current_user
		from pgappforge.plugins.erp.analytics.ai.services import (
			AgentInactiveError,
			AgentNotFoundError,
			AIAgentService,
		)
		try:
			conv = AIAgentService.start_conversation(
				agent_id=data["agent_id"],
				session=session,
				user_id=getattr(current_user, "id", data.get("user_id")),
				session_id=data.get("session_id"),
			)
			session.commit()
			return jsonify({"id": conv.id, "started_at": conv.started_at.isoformat()}), 201
		except AgentNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404
		except AgentInactiveError as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:conv_id>/message", methods=["POST"])
	@has_access
	def message(self, conv_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.ai.services import (
			AIAgentService,
			ConversationNotFoundError,
		)
		try:
			msg = AIAgentService.append_message(
				conversation_id=conv_id,
				role=data["role"],
				content=data["content"],
				session=session,
				tool_calls=data.get("tool_calls"),
				tool_results=data.get("tool_results"),
				tokens_used=data.get("tokens_used"),
				model_used=data.get("model_used"),
				latency_ms=data.get("latency_ms"),
			)
			session.commit()
			return jsonify({"id": msg.id, "sent_at": msg.sent_at.isoformat()}), 201
		except ConversationNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/<string:conv_id>/end", methods=["POST"])
	@has_access
	def end(self, conv_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.ai.services import (
			AIAgentService,
			ConversationNotFoundError,
		)
		try:
			conv = AIAgentService.end_conversation(
				conversation_id=conv_id,
				session=session,
				outcome=data.get("outcome", ""),
				rating=data.get("rating"),
			)
			session.commit()
			return jsonify({"id": conv.id, "ended_at": conv.ended_at.isoformat() if conv.ended_at else None})
		except ConversationNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# ActionView
# ---------------------------------------------------------------------------

class ActionView(BaseView):
	route_base = "/analytics/ai/actions"
	default_view = "pending"

	@expose("/pending", methods=["GET"])
	@has_access
	def pending(self):
		"""List all PROPOSED actions awaiting human approval."""
		session = _get_session()
		from pgappforge.plugins.erp.analytics.ai.models import AgentAction
		rows = session.execute(
			sa.select(AgentAction)
			.where(AgentAction.status == "PROPOSED")
			.order_by(AgentAction.created_at.asc())
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.id)}</td><td>{_he(r.action_type)}</td>"
			f"<td>{_he(r.target_entity_type or '—')}</td>"
			f"<td>{_he(r.target_entity_id or '—')}</td>"
			f"<td>{_he(r.created_at.strftime('%Y-%m-%d %H:%M'))}</td>"
			f"<td>"
			f"<form method='post' action='/analytics/ai/actions/{_he(r.id)}/approve'>"
			f"<button type='submit'>Approve</button></form> "
			f"<form method='post' action='/analytics/ai/actions/{_he(r.id)}/reject'>"
			f"<button type='submit'>Reject</button></form>"
			f"</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Pending Agent Actions</h2>"
			"<table><thead><tr><th>ID</th><th>Action Type</th><th>Entity Type</th>"
			"<th>Entity ID</th><th>Proposed At</th><th>Actions</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/<string:action_id>/approve", methods=["POST"])
	@has_access
	def approve(self, action_id: str):
		session = _get_session()
		from flask_login import current_user
		from pgappforge.plugins.erp.analytics.ai.services import (
			ActionNotFoundError,
			AIAgentService,
			InvalidActionTransitionError,
		)
		try:
			approver_id = getattr(current_user, "id", 0)
			action = AIAgentService.approve_action(action_id, approver_id, session)
			session.commit()
			return jsonify({"id": action.id, "status": action.status})
		except ActionNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404
		except InvalidActionTransitionError as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:action_id>/reject", methods=["POST"])
	@has_access
	def reject(self, action_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.ai.services import (
			ActionNotFoundError,
			AIAgentService,
			InvalidActionTransitionError,
		)
		try:
			action = AIAgentService.reject_action(action_id, session)
			session.commit()
			return jsonify({"id": action.id, "status": action.status})
		except ActionNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404
		except InvalidActionTransitionError as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# AIReportView
# ---------------------------------------------------------------------------

class AIReportView(BaseView):
	"""AI agent analytics reports.

	GET /analytics/ai/reports/agent_usage   — conversations + messages per agent (HTML)
	GET /analytics/ai/reports/token_spend   — token spend by model (JSON)
	"""

	route_base = "/analytics/ai/reports"
	default_view = "agent_usage"

	@expose("/agent_usage", methods=["GET"])
	@has_access
	def agent_usage(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.ai.models import AIAgent, AgentConversation, AgentMessage
		rows = session.execute(
			sa.select(
				AIAgent.agent_name,
				AIAgent.agent_type,
				sa.func.count(AgentConversation.id.distinct()).label("conv_count"),
				sa.func.coalesce(sa.func.sum(AgentConversation.message_count), 0).label("total_messages"),
				sa.func.avg(AgentConversation.rating).label("avg_rating"),
			)
			.outerjoin(AgentConversation, AgentConversation.agent_id == AIAgent.id)
			.group_by(AIAgent.id, AIAgent.agent_name, AIAgent.agent_type)
			.order_by(sa.func.count(AgentConversation.id.distinct()).desc())
		).all()
		items = [
			f"<tr><td>{_he(r.agent_name)}</td><td>{_he(r.agent_type)}</td>"
			f"<td>{_he(r.conv_count)}</td><td>{_he(r.total_messages)}</td>"
			f"<td>{round(float(r.avg_rating), 2) if r.avg_rating else '—'}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>AI Agent Usage Report</h2>"
			"<table><thead><tr><th>Agent</th><th>Type</th>"
			"<th>Conversations</th><th>Messages</th><th>Avg Rating</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/token_spend", methods=["GET"])
	@has_access
	def token_spend(self):
		"""Token spend grouped by model_used."""
		session = _get_session()
		from pgappforge.plugins.erp.analytics.ai.models import AgentMessage
		rows = session.execute(
			sa.select(
				AgentMessage.model_used,
				sa.func.count().label("message_count"),
				sa.func.coalesce(sa.func.sum(AgentMessage.tokens_used), 0).label("total_tokens"),
				sa.func.avg(AgentMessage.latency_ms).label("avg_latency_ms"),
			)
			.where(AgentMessage.model_used.isnot(None))
			.group_by(AgentMessage.model_used)
			.order_by(sa.func.sum(AgentMessage.tokens_used).desc())
		).all()
		return jsonify([
			{
				"model": r.model_used,
				"message_count": r.message_count,
				"total_tokens": r.total_tokens,
				"avg_latency_ms": round(float(r.avg_latency_ms), 1) if r.avg_latency_ms else None,
			}
			for r in rows
		])


__all__ = [
	"AIAgentView",
	"ConversationView",
	"ActionView",
	"AIReportView",
]
