"""
pgappforge/ai_assistant/views.py

Flask views for the Ollama-backed dev assistant.

Routes:
  GET  /dev-assistant/       — main chat UI
  POST /dev-assistant/chat   — SSE stream (text/event-stream)
  GET  /dev-assistant/models — JSON list of available Ollama models
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests as _req
from flask import Response, make_response, request, stream_with_context

from pgappforge import expose
from pgappforge.baseviews import BaseView
from pgappforge.security.decorators import has_access

from .agent import _DEFAULT_MODEL, _DEFAULT_OLLAMA_URL, run_agent_stream
from .context import build_system_prompt
from .tools import build_tool_registry

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(os.environ.get("PGAF_DEV_ASSISTANT_ROOT", Path(__file__).resolve().parents[2]))
_MAX_HISTORY_TURNS = 40


def _get_user_roles() -> set[str]:
	"""Extract current user's role names from Flask-Login / FAB security."""
	try:
		from flask_login import current_user
		if current_user and current_user.is_authenticated:
			return {r.name for r in getattr(current_user, "roles", [])}
	except Exception:
		pass
	return set()


def _get_ollama_models(ollama_url: str) -> list[str]:
	"""Return list of model name strings from Ollama, or empty list on failure."""
	try:
		resp = _req.get(f"{ollama_url}/api/tags", timeout=3)
		resp.raise_for_status()
		return [m["name"] for m in resp.json().get("models", [])]
	except Exception:
		return []


class DevAssistantView(BaseView):
	"""Developer / Admin AI assistant powered by a local Ollama model.

	Write tools (write_file, run_tests) are only exposed to Developer and Admin roles.
	Read-only tools are available to all authenticated users.
	"""

	route_base = "/dev-assistant"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""Render the main chat interface."""
		default_model = os.environ.get("DEV_ASSISTANT_MODEL", _DEFAULT_MODEL)
		user_roles = _get_user_roles()
		has_write = bool(user_roles & {"Admin", "Developer"})

		return self.render_template(
			"dev_assistant/index.html",
			default_model=default_model,
			has_write=has_write,
			user_roles=sorted(user_roles),
		)

	@expose("/chat", methods=["POST"])
	@has_access
	def chat(self):
		"""SSE endpoint: POST JSON {message, model?, history?} → text/event-stream.

		History is client-owned (sent in the request body) to support multi-tab
		and stateless deployments. Trimmed to _MAX_HISTORY_TURNS server-side.
		"""
		try:
			body = request.get_json(force=True) or {}
		except Exception:
			return make_response("Invalid JSON", 400)

		user_message = str(body.get("message", "")).strip()
		if not user_message:
			return make_response("message is required", 400)

		model = str(body.get("model", os.environ.get("DEV_ASSISTANT_MODEL", _DEFAULT_MODEL)))
		ollama_url = os.environ.get("OLLAMA_URL", _DEFAULT_OLLAMA_URL)

		history: list[dict] = body.get("history", [])
		if not isinstance(history, list):
			history = []
		history = history[-_MAX_HISTORY_TURNS:]

		user_roles = _get_user_roles()
		tool_schemas, tool_registry = build_tool_registry(user_roles)

		try:
			system_prompt = build_system_prompt(_PROJECT_ROOT)
		except Exception as exc:
			log.warning("dev_assistant: system prompt build failed: %s", exc)
			system_prompt = "You are a developer assistant for this application."

		def generate():
			yield from run_agent_stream(
				user_message=user_message,
				tool_schemas=tool_schemas,
				tool_registry=tool_registry,
				system_prompt=system_prompt,
				history=history,
				model=model,
				ollama_url=ollama_url,
			)

		resp = Response(
			stream_with_context(generate()),
			mimetype="text/event-stream",
		)
		resp.headers["Cache-Control"] = "no-cache"
		resp.headers["X-Accel-Buffering"] = "no"
		resp.headers["Connection"] = "keep-alive"
		return resp

	@expose("/models")
	@has_access
	def models(self):
		"""Return JSON list of available Ollama models."""
		ollama_url = os.environ.get("OLLAMA_URL", _DEFAULT_OLLAMA_URL)
		model_names = _get_ollama_models(ollama_url)
		return make_response(
			json.dumps({"models": model_names}),
			200,
			{"Content-Type": "application/json"},
		)


__all__ = ["DevAssistantView"]
