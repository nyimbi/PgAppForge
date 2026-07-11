"""
pgappforge/plugins/erp/platform/apg_bridge/views.py

Flask-AppBuilder views for the APG bridge plugin.

  APGCapabilityCacheView   — read-only list/show for cached capability metadata
  APGBridgeDashboardView   — status dashboard + "Sync Capabilities" action
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging

from flask import jsonify, render_template, request
from pgappforge import expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPModelView, BaseERPView
from pgappforge.plugins.erp.platform.apg_bridge.models import APGCapabilityCache

log = logging.getLogger(__name__)


class APGCapabilityCacheView(BaseERPModelView):
	"""Read-only view of APG capability metadata cached from the marketplace."""

	datamodel = SQLAInterface(APGCapabilityCache)

	list_title = "APG Capabilities"
	show_title = "APG Capability Detail"

	list_columns = ["capability_id", "name", "domain", "is_active", "last_synced_at"]
	show_columns = [
		"capability_id",
		"name",
		"domain",
		"provides",
		"requires",
		"base_url",
		"is_active",
		"contract_hash",
		"last_synced_at",
		"created_at",
		"updated_at",
	]
	label_columns = {
		"capability_id": _("Capability ID"),
		"name": _("Capability Name"),
		"domain": _("Domain"),
		"provides": _("Provides"),
		"requires": _("Requires"),
		"base_url": _("Base URL"),
		"is_active": _("Active"),
		"contract_hash": _("Contract Hash"),
		"last_synced_at": _("Last Synced"),
		"created_at": _("Created"),
		"updated_at": _("Updated"),
	}

	# Read-only: no add / edit / delete
	base_permissions = ["can_list", "can_show"]

	search_columns = ["capability_id", "name", "domain"]
	page_size = 50


class APGBridgeDashboardView(BaseERPView):
	"""APG Bridge status dashboard.

	Shows:
	  - Connection status tile (connected / disconnected)
	  - Synced capability count
	  - Event forwarding state
	  - "Sync Capabilities" action button
	  - Live capability list from local cache
	"""

	route_base = "/platform/apg-bridge"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService
		from pgappforge.plugins.erp.platform.apg_bridge.models import (
			APGCapabilityCache,
			APGEventBridgeLog,
		)

		svc = APGBridgeService()
		status = svc.get_bridge_status()

		sess = self._session()
		cap_count = self._count(APGCapabilityCache, session=sess, is_active=True)
		event_total = self._count(APGEventBridgeLog, session=sess)
		event_errors = self._count(APGEventBridgeLog, session=sess, success=False)

		# Fetch first 20 cached capabilities for the table
		try:
			import sqlalchemy as sa
			caps = (
				sess.execute(
					sa.select(APGCapabilityCache)
					.where(APGCapabilityCache.is_active == True)  # noqa: E712
					.order_by(APGCapabilityCache.domain, APGCapabilityCache.name)
					.limit(20)
				)
				.scalars()
				.all()
			)
		except Exception:
			caps = []

		connected = status["apg_available"]
		kpi_html = self.kpi_cards([
			{
				"label": "APG Status",
				"value": "Connected" if connected else "Disconnected",
				"icon": "fa-link" if connected else "fa-chain-broken",
				"color": "#0e9f6e" if connected else "#9e1c00",
			},
			{
				"label": "Synced Capabilities",
				"value": cap_count,
				"icon": "fa-cubes",
				"color": "#1a56db",
			},
			{
				"label": "Events Forwarded",
				"value": event_total,
				"icon": "fa-bolt",
				"color": "#7e3af2",
			},
			{
				"label": "Forward Errors",
				"value": event_errors,
				"icon": "fa-exclamation-triangle",
				"color": "#9e1c00" if event_errors else "#0e9f6e",
			},
		])

		return self.render_template(
			"platform_admin/apg_bridge_dashboard.html",
			status=status,
			kpi_html=kpi_html,
			caps=caps,
			appbuilder=self.appbuilder,
		)

	@expose("/sync", methods=["POST"])
	@has_access
	def sync_capabilities(self):
		"""Trigger a capability sync from the APG marketplace.

		POST /platform/apg-bridge/sync
		Returns JSON: {synced: int, message: str}
		"""
		from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService

		sess = self._session()
		tenant_id = self._tenant_id()
		try:
			svc = APGBridgeService()
			n = svc.sync_capabilities_to_ipaas(tenant_id, sess)
			sess.commit()
			return jsonify({"synced": n, "message": f"Synced {n} new capabilities from APG."})
		except Exception as exc:
			log.warning("APG sync_capabilities view error: %s", exc)
			return jsonify({"synced": 0, "message": str(exc)}), 500

	@expose("/status", methods=["GET"])
	@has_access
	def bridge_status(self):
		"""Return bridge status as JSON.

		GET /platform/apg-bridge/status
		"""
		from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService
		return jsonify(APGBridgeService().get_bridge_status())


__all__ = ["APGCapabilityCacheView", "APGBridgeDashboardView"]
