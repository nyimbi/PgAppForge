"""
pgappforge/ai_assistant

Ollama-powered developer/admin assistant for PgAppForge applications.

Registration:
    from pgappforge.ai_assistant import DevAssistantPlugin

    # In your AppBuilder init:
    appbuilder.add_view_no_menu(DevAssistantView)

    # Or register as an addon in config:
    ADDON_MANAGERS = ["pgappforge.ai_assistant.DevAssistantPlugin"]
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from pgappforge.basemanager import BaseManager

from .views import DevAssistantView

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(
	os.environ.get("PGAF_DEV_ASSISTANT_ROOT", Path(__file__).resolve().parents[2])
).resolve()


class DevAssistantPlugin(BaseManager):
	"""FAB addon manager that registers the dev assistant view."""

	def register_views(self):
		self.appbuilder.add_view_no_menu(DevAssistantView)

	def pre_process(self):
		pass

	def post_process(self):
		"""Bootstrap DB schemas and start background embedding indexer."""
		try:
			from . import session_service
			session_service.ensure_schema()
		except Exception as exc:
			log.warning("dev_assistant: session schema setup failed: %s", exc)

		try:
			from .embeddings import ensure_schema as ensure_embed_schema, start_background_index
			ensure_embed_schema()
			start_background_index(_PROJECT_ROOT)
		except Exception as exc:
			log.warning("dev_assistant: embedding setup failed: %s", exc)


__all__ = [
	"DevAssistantPlugin",
	"DevAssistantView",
]
