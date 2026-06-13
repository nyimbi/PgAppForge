"""
pgappforge/plugins/erp/platform/audit_viewer/__init__.py

AuditViewerPlugin — read-only browser for the platform audit log.

Provides a secured web UI at ``/platform/audit/`` and a JSON query API at
``/platform/audit/api/query`` that expose the contents of ``pgaf_audit_log``
to authorised users.

Events emitted:  (none — read-only)
Events consumed: (none)

Depends on:      foundation (for the event bus), audit table existing in DB.

Usage
-----
Add to ``PGAPPFORGE_PLUGINS`` in your app config::

    PGAPPFORGE_PLUGINS = [
        ...
        "pgappforge.plugins.erp.platform.audit_viewer",
    ]

Or activate directly::

    from pgappforge.plugins.erp.platform.audit_viewer import AuditViewerPlugin
    plugin = AuditViewerPlugin(appbuilder)
    plugin.activate()

Permissions required
--------------------
- ``can_audit_log_index`` on ``AuditLogView``  — browse the UI
- ``can_audit_log_query_api`` on ``AuditLogView`` — call the JSON API

Grant these to the ``Admin`` role (and any Compliance / Internal Audit role)
during app bootstrap.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AuditViewerPlugin(BasePlugin):
	"""Read-only audit log browser plugin for the platform domain.

	Registers :class:`~pgappforge.plugins.erp.platform.audit_viewer.views.AuditLogView`
	under the *Platform* menu category so compliance and operations teams can
	inspect the immutable audit trail without direct database access.
	"""

	name       = "audit_viewer"
	domain     = "platform"
	depends_on = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="audit_viewer",
			version="1.0.0",
			description=(
				"Platform audit log viewer — read-only browser for pgaf_audit_log. "
				"Satisfies SOC2, CBK, SASRA, ISO 27001, GDPR Art. 30 audit trail requirements."
			),
			author="PgAppForge Contributors",
			tags=["platform", "audit", "compliance", "security", "grc"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_audit_log_index",
				"can_audit_log_query_api",
			],
			safe_mode_compatible=True,
		)

	def initialize(self) -> None:
		"""No-op: views are registered lazily in register_views()."""

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def register_views(self) -> None:
		"""Register AuditLogView with PgAppForge under Platform → Audit Log."""
		try:
			from pgappforge.plugins.erp.platform.audit_viewer.views import AuditLogView
			self.appbuilder.add_view(
				AuditLogView,
				"Audit Log",
				icon="fa-shield",
				category="Platform",
				category_icon="fa-cogs",
			)
			log.info("AuditViewerPlugin: AuditLogView registered at /platform/audit/")
		except Exception as exc:
			log.error("AuditViewerPlugin: failed to register views — %s", exc)
			raise


__all__ = ["AuditViewerPlugin"]
