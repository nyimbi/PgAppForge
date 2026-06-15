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

from pgappforge.basemanager import BaseManager

from .views import DevAssistantView


class DevAssistantPlugin(BaseManager):
	"""FAB addon manager that registers the dev assistant view."""

	def register_views(self):
		self.appbuilder.add_view_no_menu(DevAssistantView)

	def pre_process(self):
		pass

	def post_process(self):
		pass


__all__ = [
	"DevAssistantPlugin",
	"DevAssistantView",
]
