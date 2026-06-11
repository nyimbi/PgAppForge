"""
pgappforge/plugins/fintech/terminal_management/views.py

Terminal Management views: terminal list/admin, health event log (read-only),
and a KPI dashboard.

Security posture:
  - TerminalView: full CRUD for terminal administrators
  - TerminalHealthView: list/show only (immutable audit log)
  - TerminalDashboardView: read-only KPI dashboard with _count() helpers
"""
from __future__ import annotations

import logging
from typing import Any

from flask import current_app
from flask_appbuilder import expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.erp.base_view import BaseERPModelView, BaseERPView
from pgappforge.plugins.fintech.terminal_management.models import (
	Terminal,
	TerminalBatch,
	TerminalHealthEvent,
	TerminalKey,
	TerminalParameter,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TerminalView — terminal registry management
# ---------------------------------------------------------------------------

class TerminalView(BaseERPModelView):
	"""Payment terminal registry — CRUD for terminal administrators."""

	datamodel = SQLAInterface(Terminal)
	route_base = "/fintech/terminals"

	list_title = "Terminals"
	show_title = "Terminal Details"
	add_title = "Add Terminal"
	edit_title = "Edit Terminal"

	list_columns = [
		"terminal_id",
		"terminal_type",
		"merchant_name",
		"status",
		"pci_dss_compliant",
		"last_heartbeat_at",
	]

	show_fieldsets = [
		("Identity", {
			"fields": [
				"terminal_id", "terminal_type", "merchant_id", "merchant_name",
				"serial_number", "imei", "ip_address",
			]
		}),
		("Software", {
			"fields": ["software_version", "firmware_version"]
		}),
		("Status", {
			"fields": [
				"status", "pci_dss_compliant",
				"last_heartbeat_at", "last_transaction_at",
			]
		}),
		("Audit", {
			"fields": ["created_at", "updated_at"]
		}),
	]
	add_fieldsets = [
		("Identity", {
			"fields": [
				"terminal_id", "terminal_type", "merchant_id", "merchant_name",
				"serial_number", "imei", "ip_address",
			]
		}),
		("Software", {
			"fields": ["software_version", "firmware_version"]
		}),
	]
	edit_fieldsets = add_fieldsets

	label_columns = {
		"terminal_id": "TID",
		"terminal_type": "Type",
		"merchant_name": "Merchant",
		"pci_dss_compliant": "PCI DSS",
		"last_heartbeat_at": "Last Heartbeat",
		"last_transaction_at": "Last Transaction",
		"ip_address": "IP Address",
		"software_version": "SW Version",
		"firmware_version": "FW Version",
		"serial_number": "Serial No.",
	}

	search_columns = ["terminal_id", "merchant_name", "status", "terminal_type"]
	base_order = ("created_at", "desc")

	formatters_columns: dict[str, Any] = {
		"status": lambda v: {
			"ACTIVE": '<span class="badge bg-success">ACTIVE</span>',
			"INACTIVE": '<span class="badge bg-secondary">INACTIVE</span>',
			"SUSPENDED": '<span class="badge bg-warning text-dark">SUSPENDED</span>',
			"TAMPERED": '<span class="badge bg-danger">TAMPERED</span>',
			"DECOMMISSIONED": '<span class="badge bg-dark">DECOMM.</span>',
		}.get(v or "", f'<span class="badge bg-light text-dark">{v}</span>'),
		"pci_dss_compliant": lambda v: (
			'<span class="badge bg-success">YES</span>'
			if v else
			'<span class="badge bg-danger">NO</span>'
		),
	}


# ---------------------------------------------------------------------------
# TerminalHealthView — read-only immutable health event log
# ---------------------------------------------------------------------------

class TerminalHealthView(BaseERPModelView):
	"""Terminal health event log — read-only, append-only."""

	datamodel = SQLAInterface(TerminalHealthEvent)
	route_base = "/fintech/terminal-health"

	list_title = "Terminal Health Events"
	show_title = "Health Event Details"

	base_permissions = ["can_list", "can_show"]

	list_columns = ["terminal_id", "event_type", "occurred_at"]
	show_fieldsets = [
		("Event", {
			"fields": ["terminal_id", "event_type", "detail", "occurred_at"]
		}),
	]

	label_columns = {
		"terminal_id": "Terminal",
		"event_type": "Event Type",
		"occurred_at": "Occurred At",
	}

	search_columns = ["event_type"]
	base_order = ("occurred_at", "desc")

	formatters_columns: dict[str, Any] = {
		"event_type": lambda v: {
			"TAMPER_ALERT": '<span class="badge bg-danger">TAMPER</span>',
			"HEARTBEAT": '<span class="badge bg-success">HB</span>',
			"ERROR": '<span class="badge bg-warning text-dark">ERROR</span>',
			"STARTUP": '<span class="badge bg-info">STARTUP</span>',
			"SHUTDOWN": '<span class="badge bg-secondary">SHUTDOWN</span>',
			"LOW_PAPER": '<span class="badge bg-warning text-dark">LOW PAPER</span>',
			"BATTERY_LOW": '<span class="badge bg-warning text-dark">BATTERY</span>',
			"NETWORK_LOST": '<span class="badge bg-danger">NET LOST</span>',
		}.get(v or "", f'<span class="badge bg-light text-dark">{v}</span>'),
	}


# ---------------------------------------------------------------------------
# TerminalDashboardView — KPI overview
# ---------------------------------------------------------------------------

class TerminalDashboardView(BaseERPView):
	"""Terminal management KPI dashboard."""

	route_base = "/fintech/terminals-dashboard"
	default_view = "index"

	# ------------------------------------------------------------------
	# Private count helpers
	# ------------------------------------------------------------------

	def _count(self, session: Any, **filters: Any) -> int:
		"""Count Terminal rows matching the given status/column filters."""
		q = select(sa.func.count(Terminal.id))
		for col, val in filters.items():
			q = q.where(getattr(Terminal, col) == val)
		return session.execute(q).scalar_one()

	def _count_pending_params(self, session: Any) -> int:
		"""Count terminals that have no DEPLOYED parameter set."""
		has_deployed = (
			select(TerminalParameter.terminal_id)
			.where(TerminalParameter.status == "DEPLOYED")
			.distinct()
			.scalar_subquery()
		)
		result = session.execute(
			select(sa.func.count(Terminal.id)).where(
				Terminal.id.notin_(has_deployed)
			)
		).scalar_one()
		return result

	# ------------------------------------------------------------------
	# View
	# ------------------------------------------------------------------

	@expose("/")
	@has_access
	def index(self):
		try:
			from flask_appbuilder.models.sqla.interface import SQLAInterface
			session = SQLAInterface(Terminal).session

			active = self._count(session, status="ACTIVE")
			inactive = self._count(session, status="INACTIVE")
			tampered = self._count(session, status="TAMPERED")
			suspended = self._count(session, status="SUSPENDED")
			decommissioned = self._count(session, status="DECOMMISSIONED")
			pending_params = self._count_pending_params(session)

			kpi_html = self.kpi_cards([
				{
					"label": "Active Terminals",
					"value": active,
					"format": "integer",
					"color": "#1a56db",
					"icon": "fa-desktop",
				},
				{
					"label": "Inactive",
					"value": inactive,
					"format": "integer",
					"color": "#6b7280",
					"icon": "fa-pause-circle",
				},
				{
					"label": "Tampered",
					"value": tampered,
					"format": "integer",
					"color": "#dc2626",
					"icon": "fa-exclamation-triangle",
				},
				{
					"label": "Suspended",
					"value": suspended,
					"format": "integer",
					"color": "#d97706",
					"icon": "fa-ban",
				},
				{
					"label": "Pending Params",
					"value": pending_params,
					"format": "integer",
					"color": "#7c3aed",
					"icon": "fa-cog",
				},
				{
					"label": "Decommissioned",
					"value": decommissioned,
					"format": "integer",
					"color": "#374151",
					"icon": "fa-trash",
				},
			])
		except Exception as exc:
			log.warning("TerminalDashboardView: failed to load KPIs: %s", exc)
			kpi_html = ""

		return self.render_template(
			"appbuilder/general/model/list.html",
			kpi_html=kpi_html,
			title="Terminal Management Dashboard",
			appbuilder=self.appbuilder,
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"TerminalView",
	"TerminalHealthView",
	"TerminalDashboardView",
]
