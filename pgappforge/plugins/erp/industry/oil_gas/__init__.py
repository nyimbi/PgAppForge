"""
pgappforge/plugins/erp/industry/oil_gas/__init__.py

OilGasPlugin — ISO 15926-based plant lifecycle management plugin.

Provides:
  - Facility management (upstream/midstream/downstream/refinery/LNG)
  - Asset register with ISO 15926-2 tag numbering and equipment hierarchy
  - Maintenance work orders (PM/CM/CBM/turnaround) with cost tracking
  - Daily production records per facility and product type
  - HAZOP review lifecycle management
  - HSE incident reporting (IOGP TIER1/2/3 classification)

Business services:
  - calculate_oee()                     — OEE for a facility over rolling period
  - schedule_preventive_maintenance()   — generate PM work order series
  - record_production()                 — write daily production record
  - assess_criticality()                — score asset criticality + maintenance priority
  - generate_maintenance_backlog()      — open/overdue WO list for a facility
  - calculate_hse_kpis()                — TRIR, LTIR, spill/near-miss counts

Events emitted:
  - oil_gas.maintenance.scheduled
  - oil_gas.maintenance.completed
  - oil_gas.production.recorded
  - oil_gas.incident.reported
  - oil_gas.hazop.completed
  - oil_gas.facility.status_changed

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.oil_gas",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class OilGasPlugin(BasePlugin):
	"""ISO 15926-based Oil & Gas plant lifecycle management plugin.

	Class-level routing metadata:
	    name       = "oil_gas"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "oil_gas"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="oil_gas",
			version="1.0.0",
			description=(
				"ISO 15926-based Oil & Gas plant lifecycle management — "
				"facilities, assets, maintenance work orders, production records, "
				"HAZOP reviews, and HSE incident reporting with TRIR/LTIR KPIs."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "oil-gas", "iso15926", "hse", "maintenance"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_og_facility_read",
				"can_og_facility_write",
				"can_og_asset_read",
				"can_og_asset_write",
				"can_og_maintenance_read",
				"can_og_maintenance_write",
				"can_og_maintenance_approve",
				"can_og_maintenance_complete",
				"can_og_production_read",
				"can_og_production_write",
				"can_og_hazop_read",
				"can_og_hazop_write",
				"can_og_incident_read",
				"can_og_incident_write",
				"can_og_reports",
				"can_og_dashboard",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events emitted by this plugin."""
		return [
			"oil_gas.maintenance.scheduled",
			"oil_gas.maintenance.completed",
			"oil_gas.production.recorded",
			"oil_gas.incident.reported",
			"oil_gas.hazop.completed",
			"oil_gas.facility.status_changed",
		]

	def subscribe_to(self) -> list[str]:
		"""Events consumed by this plugin (v1: none)."""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"OG_MENU_CATEGORY": "Oil & Gas",
			"OG_DEFAULT_CAPACITY_UNIT": "bbl/d",
			"OG_HSE_HEADCOUNT_ASSUMPTION": 50,
			"OG_PM_DEFAULT_HORIZON_DAYS": 365,
		}
		self.config = {**defaults, **self.config}
		log.info("OilGasPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		"""Register O&G views under the configured menu category."""
		from pgappforge.plugins.erp.industry.oil_gas.views import (
			FacilityView,
			AssetView,
			MaintenanceWorkView,
			ProductionRecordView,
			HAZOPReviewView,
			IncidentReportView,
			OilGasDashboardView,
		)

		cat = self.config.get("OG_MENU_CATEGORY", "Oil & Gas")

		self.add_view(FacilityView, "Facilities", icon="fa-industry", category=cat)
		self.add_view(AssetView, "Assets", icon="fa-cogs", category=cat)
		self.add_view(
			MaintenanceWorkView, "Maintenance Orders",
			icon="fa-wrench", category=cat,
		)
		self.add_view(
			ProductionRecordView, "Production",
			icon="fa-tachometer", category=cat,
		)
		self.add_view(HAZOPReviewView, "HAZOP Reviews", icon="fa-shield", category=cat)
		self.add_view(
			IncidentReportView, "Incidents",
			icon="fa-exclamation-triangle", category=cat,
		)
		self.add_view(
			OilGasDashboardView, "O&G Dashboard",
			icon="fa-dashboard", category=cat,
		)

		log.info("OilGasPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.oil_gas.models import (
			Facility,
			Asset,
			MaintenanceWork,
			ProductionRecord,
			HAZOPReview,
			IncidentReport,
		)
		return [
			Facility,
			Asset,
			MaintenanceWork,
			ProductionRecord,
			HAZOPReview,
			IncidentReport,
		]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> OilGasPlugin:
	"""Construct and return an OilGasPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return OilGasPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.oil_gas.models import (  # noqa: E402
	Facility,
	Asset,
	MaintenanceWork,
	ProductionRecord,
	HAZOPReview,
	IncidentReport,
)
from pgappforge.plugins.erp.industry.oil_gas.events import (  # noqa: E402
	MaintenanceScheduledEvent,
	MaintenanceCompletedEvent,
	ProductionRecordedEvent,
	IncidentReportedEvent,
	HAZOPCompletedEvent,
	FacilityStatusChangedEvent,
	emit_event,
)
from pgappforge.plugins.erp.industry.oil_gas.services import (  # noqa: E402
	OilGasService,
	OilGasServiceError,
	FacilityNotFoundError,
	AssetNotFoundError,
	InvalidProductTypeError,
)

__all__ = [
	# plugin
	"OilGasPlugin",
	"create_plugin",
	# models
	"Facility",
	"Asset",
	"MaintenanceWork",
	"ProductionRecord",
	"HAZOPReview",
	"IncidentReport",
	# events
	"MaintenanceScheduledEvent",
	"MaintenanceCompletedEvent",
	"ProductionRecordedEvent",
	"IncidentReportedEvent",
	"HAZOPCompletedEvent",
	"FacilityStatusChangedEvent",
	"emit_event",
	# services
	"OilGasService",
	"OilGasServiceError",
	"FacilityNotFoundError",
	"AssetNotFoundError",
	"InvalidProductTypeError",
]
