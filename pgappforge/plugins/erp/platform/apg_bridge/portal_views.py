"""
pgappforge/plugins/erp/platform/apg_bridge/portal_views.py

APGCapabilityPortalView — render APG capability UIs natively within PgAppForge.

Routes
------
  GET  /platform/apg/                                  capability browser
  GET  /platform/apg/capability/<prefix>               capability dashboard
  GET  /platform/apg/capability/<prefix>/actions       actions panel
  POST /platform/apg/capability/<prefix>/evaluate      JSON evaluate endpoint
  GET  /platform/apg/status                            bridge status JSON
"""
from __future__ import annotations

import logging

from flask import abort, jsonify, render_template, request

from pgappforge import expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.apg_bridge.client import APGClient
from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService

log = logging.getLogger(__name__)


class APGCapabilityPortalView(BaseERPView):
	"""Portal for browsing and interacting with APG capabilities.

	Renders APG capability dashboards natively within PgAppForge's UI.
	Each APG capability's dict view model is translated into ERP-design-system
	components: KPI tiles, key-value tables, action panels, and route lists.
	"""

	route_base = "/platform/apg"

	# ── Capability browser ─────────────────────────────────────────────────

	@expose("/")
	@has_access
	def index(self):
		"""APG capability browser — lists all available capabilities."""
		client = APGClient()
		capabilities = client.list_capabilities() if client.is_available() else []

		cap_cards: list[dict] = []
		for cap in capabilities:
			cap_id = str(cap.get("id") or cap.get("name") or "")
			if not cap_id:
				continue
			prefix = cap_id.replace("_", "-")
			contract = client.get_contract(prefix) or {}
			cap_cards.append({
				"id": cap_id,
				"prefix": prefix,
				"display_name": contract.get(
					"display_name",
					cap_id.replace("_", " ").title(),
				),
				"domain": cap.get("domain", contract.get("domain", "")),
				"provides": contract.get("provides", []),
				"is_healthy": client.health_check(prefix),
				"theme": contract.get("theme", {}),
				"routes": contract.get("ui", {}).get("routes", []),
			})

		kpi_html = self.kpi_cards([
			{
				"label": "Available Capabilities",
				"value": len(cap_cards),
				"icon": "fa-cubes",
				"color": "#1a56db",
			},
			{
				"label": "Healthy",
				"value": sum(1 for c in cap_cards if c["is_healthy"]),
				"icon": "fa-check-circle",
				"color": "#0e9f6e",
			},
			{
				"label": "APG Status",
				"value": "Connected" if client.is_available() else "Offline",
				"icon": "fa-plug",
				"color": "#0e9f6e" if client.is_available() else "#e02424",
			},
		])

		return render_template(
			"appbuilder/apg/portal.html",
			capabilities=cap_cards,
			kpi_html=kpi_html,
			apg_enabled=client._enabled,
			apg_available=client.is_available(),
			appbuilder=self.appbuilder,
		)

	# ── Capability dashboard ───────────────────────────────────────────────

	@expose("/capability/<capability_prefix>")
	@has_access
	def capability_dashboard(self, capability_prefix: str):
		"""Render an APG capability's dashboard view model."""
		client = APGClient()
		contract = client.get_contract(capability_prefix)
		if contract is None:
			abort(404)

		dashboard_data: dict = {}
		try:
			result = client.evaluate(capability_prefix, {
				"action": "dashboard",
				"view": "dashboard_model",
				"tenant_id": self._tenant_id(),
			})
			if result:
				dashboard_data = result
		except Exception as exc:
			log.debug("APG dashboard fetch failed for %r: %s", capability_prefix, exc)

		return render_template(
			"appbuilder/apg/capability_dashboard.html",
			capability_prefix=capability_prefix,
			contract=contract,
			dashboard_data=dashboard_data,
			provides=contract.get("provides", []),
			requires=contract.get("requires", []),
			routes=contract.get("ui", {}).get("routes", []),
			theme=contract.get("theme", {}),
			appbuilder=self.appbuilder,
		)

	# ── Actions panel ──────────────────────────────────────────────────────

	@expose("/capability/<capability_prefix>/actions")
	@has_access
	def capability_actions(self, capability_prefix: str):
		"""Show APG capability actions panel (PROVIDES list with input forms)."""
		client = APGClient()
		contract = client.get_contract(capability_prefix)
		if contract is None:
			abort(404)

		provides = contract.get("provides", [])
		rules = contract.get("rule_engine", {}).get("rules", [])[:5]

		return render_template(
			"appbuilder/apg/capability_actions.html",
			capability_prefix=capability_prefix,
			contract=contract,
			provides=provides,
			rules=rules,
			appbuilder=self.appbuilder,
		)

	# ── Evaluate JSON endpoint ─────────────────────────────────────────────

	@expose("/capability/<capability_prefix>/evaluate", methods=["POST"])
	@has_access
	def evaluate_action(self, capability_prefix: str):
		"""JSON API: evaluate an APG capability action. Used by the actions panel.

		POST body:
		  { "action": "<action_name>", ...extra payload... }

		Returns:
		  { "success": bool, "result": dict|null, "error": str|null }
		"""
		data = request.get_json(force=True) or {}
		result = APGBridgeService().call_capability(
			capability_prefix,
			data.get("action", ""),
			data,
			self._tenant_id(),
		)
		return jsonify(result)

	# ── Bridge status ──────────────────────────────────────────────────────

	@expose("/status")
	@has_access
	def status(self):
		"""Return bridge status as JSON.

		GET /platform/apg/status
		"""
		return jsonify(APGBridgeService().get_bridge_status())


__all__ = ["APGCapabilityPortalView"]
