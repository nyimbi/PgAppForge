"""
pgappforge/plugins/erp/platform/landing/__init__.py

Landing page plugin — registers LandingPageView with AppBuilder.

Usage::

    from pgappforge.plugins.erp.platform.landing import LandingPlugin
    LandingPlugin(appbuilder).activate()
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class LandingPlugin:
	"""Registers the LandingPageView (home + stats API + admin edit) with AppBuilder."""

	def __init__(self, appbuilder: Any, config: dict[str, Any] | None = None) -> None:
		self.appbuilder = appbuilder
		self.config: dict[str, Any] = config or {}

	def activate(self) -> bool:
		"""Register views and return True on success."""
		try:
			from pgappforge.plugins.erp.platform.landing.views import LandingPageView

			# Apply any caller-supplied config overrides
			for k, v in self.config.items():
				self.appbuilder.app.config.setdefault(k, v)

			self.appbuilder.add_view_no_menu(LandingPageView)
			log.info("LandingPlugin: LandingPageView registered at /")
			return True
		except Exception as exc:
			log.error("LandingPlugin: activation failed — %s", exc, exc_info=True)
			return False


__all__ = ["LandingPlugin"]
