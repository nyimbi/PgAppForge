"""
pgappforge/plugins/erp/industry/cybersecurity/__init__.py

CybersecurityPlugin — STIX 2.1 threat intelligence platform plugin.

Depends on: foundation

Events emitted
--------------
  cybersecurity.threat_actor.created
  cybersecurity.threat_actor.updated
  cybersecurity.indicator.ingested
  cybersecurity.indicator.expired
  cybersecurity.ioc.matched
  cybersecurity.ioc.false_positive
  cybersecurity.incident.opened
  cybersecurity.incident.triaged
  cybersecurity.incident.contained
  cybersecurity.incident.resolved
  cybersecurity.vulnerability.published
  cybersecurity.vulnerability.exploited_flagged

Events consumed
---------------
  foundation.party.created   — no-op stub (actor enrichment hook)

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.cybersecurity",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CybersecurityPlugin(BasePlugin):
	"""STIX 2.1 threat intelligence and incident response plugin.

	Provides:
	  - ThreatActor / Indicator / Malware / Vulnerability CRUD
	  - SecurityIncident lifecycle (open → triage → contain → resolve)
	  - IOC ingestion from STIX feeds and flat IOC lists
	  - Indicator correlation against incidents
	  - Composite risk scoring per system
	  - 30-day threat report generation
	"""

	name = "cybersecurity"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="cybersecurity",
			version="1.0.0",
			description=(
				"STIX 2.1 threat intelligence platform — threat actors, IOC indicators, "
				"malware catalogue, security incidents, indicator correlation, and "
				"vulnerability management aligned with CISA KEV."
			),
			author="PgAppForge Contributors",
			tags=["industry", "cybersecurity", "stix", "soc", "threat-intel", "siem"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_cs_threat_actor_list",
				"can_cs_threat_actor_write",
				"can_cs_indicator_list",
				"can_cs_indicator_write",
				"can_cs_indicator_ingest",
				"can_cs_malware_list",
				"can_cs_malware_write",
				"can_cs_incident_list",
				"can_cs_incident_write",
				"can_cs_incident_triage",
				"can_cs_vulnerability_list",
				"can_cs_vulnerability_write",
				"can_cs_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"cybersecurity.threat_actor.created",
			"cybersecurity.threat_actor.updated",
			"cybersecurity.indicator.ingested",
			"cybersecurity.indicator.expired",
			"cybersecurity.ioc.matched",
			"cybersecurity.ioc.false_positive",
			"cybersecurity.incident.opened",
			"cybersecurity.incident.triaged",
			"cybersecurity.incident.contained",
			"cybersecurity.incident.resolved",
			"cybersecurity.vulnerability.published",
			"cybersecurity.vulnerability.exploited_flagged",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"foundation.party.created",  # stub: actor enrichment
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CS_MENU_CATEGORY": "Security / Threat Intel",
			"CS_DEFAULT_CONFIDENCE": 50,
			"CS_FEED_TIMEOUT_SECONDS": 15,
			"CS_MAX_INDICATORS_PER_INGEST": 5000,
			"CS_RISK_SCORE_INCIDENT_WEIGHT": 0.5,
			"CS_RISK_SCORE_IOC_WEIGHT": 0.3,
			"CS_RISK_SCORE_VULN_WEIGHT": 0.2,
		}
		self.config = {**defaults, **self.config}
		log.info("CybersecurityPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		self._subscribe_to_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.cybersecurity.views import (
			IndicatorView,
			IncidentView,
			ThreatDashboard,
			VulnerabilityView,
		)

		cat = self.config.get("CS_MENU_CATEGORY", "Security / Threat Intel")
		self.add_view(IndicatorView, "IOC Indicators", icon="fa-crosshairs", category=cat)
		self.add_view(IncidentView, "Security Incidents", icon="fa-fire", category=cat)
		self.add_view(VulnerabilityView, "Vulnerabilities", icon="fa-bug", category=cat)
		self.add_view(ThreatDashboard, "Threat Dashboard", icon="fa-shield", category=cat)
		log.info("CybersecurityPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.cybersecurity.models import (
			Indicator,
			IndicatorMatch,
			Malware,
			SecurityIncident,
			ThreatActor,
			Vulnerability,
		)
		return [ThreatActor, Indicator, Malware, SecurityIncident, IndicatorMatch, Vulnerability]

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("foundation.party.created", self._on_party_created)
		except Exception as exc:
			log.warning("CybersecurityPlugin._subscribe_to_events failed: %s", exc)

	def _on_party_created(self, event: Any) -> None:
		log.debug(
			"CybersecurityPlugin._on_party_created: party=%s — enrichment hook stub",
			getattr(event, "party_id", "?"),
		)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> CybersecurityPlugin:
	"""Construct and return a CybersecurityPlugin bound to *appbuilder*."""
	return CybersecurityPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.cybersecurity.models import (  # noqa: E402
	Indicator,
	IndicatorMatch,
	Malware,
	SecurityIncident,
	ThreatActor,
	Vulnerability,
)
from pgappforge.plugins.erp.industry.cybersecurity.events import (  # noqa: E402
	FalsePositiveMarkedEvent,
	IncidentContainedEvent,
	IncidentOpenedEvent,
	IncidentResolvedEvent,
	IncidentTriagedEvent,
	IndicatorExpiredEvent,
	IndicatorIngestedEvent,
	IndicatorMatchedEvent,
	ThreatActorCreatedEvent,
	ThreatActorUpdatedEvent,
	VulnerabilityExploitedFlaggedEvent,
	VulnerabilityPublishedEvent,
)
from pgappforge.plugins.erp.industry.cybersecurity.services import (  # noqa: E402
	CybersecurityService,
	CybersecurityServiceError,
	IncidentNotFoundError,
	IndicatorNotFoundError,
	VulnerabilityNotFoundError,
)

__all__ = [
	# plugin
	"CybersecurityPlugin",
	"create_plugin",
	# models
	"ThreatActor",
	"Indicator",
	"Malware",
	"SecurityIncident",
	"IndicatorMatch",
	"Vulnerability",
	# events
	"ThreatActorCreatedEvent",
	"ThreatActorUpdatedEvent",
	"IndicatorIngestedEvent",
	"IndicatorExpiredEvent",
	"IndicatorMatchedEvent",
	"FalsePositiveMarkedEvent",
	"IncidentOpenedEvent",
	"IncidentTriagedEvent",
	"IncidentContainedEvent",
	"IncidentResolvedEvent",
	"VulnerabilityPublishedEvent",
	"VulnerabilityExploitedFlaggedEvent",
	# services
	"CybersecurityService",
	"CybersecurityServiceError",
	"IndicatorNotFoundError",
	"IncidentNotFoundError",
	"VulnerabilityNotFoundError",
]
