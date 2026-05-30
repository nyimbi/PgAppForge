"""
Application event hooks for pgappforge plugins.

Plugins subscribe to hooks declared here. The hook dispatcher is attached to
the AppBuilder instance as ``appbuilder.hooks`` and called from views, models,
security manager, and CLI commands at the defined extension points.

Usage in a plugin::

    class MyPlugin(BasePlugin):
        def initialize(self):
            self.appbuilder.hooks.on_record_save.connect(self._on_save)

        def _on_save(self, model_class, record, is_new):
            ...  # react to any record being saved

Alternatively, override hook methods on BasePlugin:

    class MyPlugin(BasePlugin):
        def on_record_save(self, model_class, record, is_new): ...
        def on_user_login(self, user): ...
"""
from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

log = logging.getLogger(__name__)


class _Signal:
	"""Minimal blinker-style signal. Calls all connected receivers."""

	def __init__(self, name: str) -> None:
		self.name = name
		self._receivers: list[Callable] = []

	def connect(self, fn: Callable) -> Callable:
		"""Register a receiver. Returns the function (decorator-friendly)."""
		self._receivers.append(fn)
		return fn

	def disconnect(self, fn: Callable) -> None:
		self._receivers = [r for r in self._receivers if r is not fn]

	def send(self, *args, **kwargs) -> None:
		"""Fire all receivers. Exceptions are caught and logged."""
		for fn in self._receivers:
			try:
				fn(*args, **kwargs)
			except Exception as exc:
				log.exception("Hook %s receiver %s raised: %s", self.name, fn, exc)


class HookRegistry:
	"""Central registry of all pgappforge application hooks.

	Attached to ``AppBuilder`` as ``appbuilder.hooks`` during ``init_app()``.

	Extension points::

	    hooks.on_app_ready          — app fully configured, before first request
	    hooks.on_user_login         — after successful authentication
	    hooks.on_user_logout        — after user logout
	    hooks.on_record_save        — after create OR update of any Model record
	    hooks.on_record_create      — after creation only
	    hooks.on_record_update      — after update only
	    hooks.on_record_delete      — before deletion
	    hooks.on_request_start      — before each HTTP request (after routing)
	    hooks.on_request_end        — after each HTTP response is sent
	    hooks.on_permission_denied  — when access is denied
	    hooks.on_api_call           — after each REST API response
	    hooks.on_cli_command        — after each CLI command execution
	"""

	def __init__(self) -> None:
		# Application lifecycle
		self.on_app_ready = _Signal("on_app_ready")

		# Authentication
		self.on_user_login = _Signal("on_user_login")
		self.on_user_logout = _Signal("on_user_logout")

		# CRUD
		self.on_record_save = _Signal("on_record_save")
		self.on_record_create = _Signal("on_record_create")
		self.on_record_update = _Signal("on_record_update")
		self.on_record_delete = _Signal("on_record_delete")

		# HTTP
		self.on_request_start = _Signal("on_request_start")
		self.on_request_end = _Signal("on_request_end")

		# Security
		self.on_permission_denied = _Signal("on_permission_denied")

		# API
		self.on_api_call = _Signal("on_api_call")

		# CLI
		self.on_cli_command = _Signal("on_cli_command")

	def init_app(self, app: "Flask") -> None:
		"""Attach Flask before/after_request hooks to fire the relevant signals."""
		from flask import request, g
		import time

		@app.before_request
		def _before():
			g._hook_start = time.monotonic()
			self.on_request_start.send(request=request)

		@app.after_request
		def _after(response):
			duration_ms = int((time.monotonic() - getattr(g, "_hook_start", 0)) * 1000)
			self.on_request_end.send(request=request, response=response, duration_ms=duration_ms)
			return response
