"""
pgappforge/plugins/erp/industry/track_trace/__init__.py

TrackTracePlugin — GS1 EPCIS 2.0 Track & Trace ERP plugin.

Provides:
  - TraceableItem    (EPC-identified serialized items; SGTIN/SSCC/SGLN/GRAI/GIAI)
  - EPCISEvent       (immutable GS1 EPCIS 2.0 supply chain event ledger)
  - ColdChainRecord  (high-volume IoT temperature/humidity sensor data)
  - RecallEvent      (product recall lifecycle: ACTIVE → COMPLETED/CANCELLED)

Business rules enforced:
  - EPCISEvent rows are NEVER updated (EPCIS 2.0 correction pattern: DELETE + ADD)
  - Recalls immediately flag all matching TraceableItems as is_recalled=True
  - Cold chain excursions auto-emit ColdChainExcursionEvent for alerting
  - EPCIS document import supports both XML (EPCIS 2.0 schema) and JSON-LD

Events emitted:
  track_trace.epcis.event_recorded
  track_trace.cold_chain.excursion
  track_trace.recall.initiated
  track_trace.recall.item_identified
  track_trace.recall.completed

Events consumed:
  (none — track_trace plugin is currently event-source only)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.track_trace",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TrackTracePlugin(BasePlugin):
	"""GS1 EPCIS 2.0 Track & Trace ERP plugin.

	Class-level routing metadata:
	    name       = "track_trace"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "track_trace"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="track_trace",
			version="1.0.0",
			description=(
				"GS1 EPCIS 2.0 Track & Trace — serialized item tracking with EPC URIs, "
				"immutable supply chain event ledger, cold chain integrity monitoring, "
				"product recall management, and EPCIS document import (XML + JSON-LD). "
				"Supports EU FMD, DSCSA, and FDA FSMA 204 compliance."
			),
			author="PgAppForge Contributors",
			tags=[
				"erp", "industry", "gs1", "epcis", "track-trace",
				"supply-chain", "cold-chain", "recall", "pharma", "food-safety",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_tt_item_read",
				"can_tt_item_write",
				"can_tt_event_read",
				"can_tt_event_write",
				"can_tt_event_import",
				"can_tt_cold_chain_read",
				"can_tt_cold_chain_write",
				"can_tt_recall_read",
				"can_tt_recall_write",
				"can_tt_recall_initiate",
				"can_tt_recall_close",
				"can_tt_provenance_read",
				"can_tt_dashboard",
				"can_tt_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"track_trace.epcis.event_recorded",
			"track_trace.cold_chain.excursion",
			"track_trace.recall.initiated",
			"track_trace.recall.item_identified",
			"track_trace.recall.completed",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"TT_MENU_CATEGORY": "Track & Trace",
			"TT_COLD_CHAIN_MIN_TEMP_C": 2.0,
			"TT_COLD_CHAIN_MAX_TEMP_C": 8.0,
			"TT_DEFAULT_RECALL_SCOPE": "NATIONAL",
			"TT_EPCIS_SCHEMA_VALIDATION": False,  # set True for strict EPCIS 2.0 schema validation
		}
		self.config = {**defaults, **self.config}
		log.info("TrackTracePlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		"""Register Track & Trace views under the configured menu category."""
		from pgappforge.plugins.erp.industry.track_trace.views import (
			ItemView,
			EventView,
			ColdChainView,
			RecallDashboard,
			ProvenanceView,
		)

		cat = self.config.get("TT_MENU_CATEGORY", "Track & Trace")

		self.add_view(
			ItemView,
			"Traceable Items",
			icon="fa-barcode",
			category=cat,
		)
		self.add_view(
			EventView,
			"EPCIS Events",
			icon="fa-exchange",
			category=cat,
		)
		self.add_view(
			ColdChainView,
			"Cold Chain",
			icon="fa-thermometer-half",
			category=cat,
		)
		self.add_view(
			RecallDashboard,
			"Recall Management",
			icon="fa-exclamation-triangle",
			category=cat,
		)
		self.add_view(
			ProvenanceView,
			"Provenance Chain",
			icon="fa-sitemap",
			category=cat,
		)

		log.info("TrackTracePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.track_trace.models import (
			TraceableItem,
			EPCISEvent,
			ColdChainRecord,
			RecallEvent,
		)
		return [TraceableItem, EPCISEvent, ColdChainRecord, RecallEvent]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> TrackTracePlugin:
	return TrackTracePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.track_trace.models import (  # noqa: E402
	TraceableItem,
	EPCISEvent,
	ColdChainRecord,
	RecallEvent,
)
from pgappforge.plugins.erp.industry.track_trace.events import (  # noqa: E402
	EPCISEventRecordedEvent,
	ColdChainExcursionEvent,
	RecallInitiatedEvent,
	RecallItemIdentifiedEvent,
	RecallCompletedEvent,
)
from pgappforge.plugins.erp.industry.track_trace.services import (  # noqa: E402
	TrackTraceService,
	TrackTraceError,
	ItemNotFoundError,
	RecallNotFoundError,
	EPCISValidationError,
	ColdChainError,
)

__all__ = [
	# plugin
	"TrackTracePlugin",
	"create_plugin",
	# models
	"TraceableItem",
	"EPCISEvent",
	"ColdChainRecord",
	"RecallEvent",
	# events
	"EPCISEventRecordedEvent",
	"ColdChainExcursionEvent",
	"RecallInitiatedEvent",
	"RecallItemIdentifiedEvent",
	"RecallCompletedEvent",
	# services
	"TrackTraceService",
	"TrackTraceError",
	"ItemNotFoundError",
	"RecallNotFoundError",
	"EPCISValidationError",
	"ColdChainError",
]
