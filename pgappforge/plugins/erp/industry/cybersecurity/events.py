"""
pgappforge/plugins/erp/industry/cybersecurity/events.py

Domain events for the Cybersecurity (STIX 2.1) plugin.

Payloads carry only identifiers and classification codes — raw IOC values
and incident details must be fetched from the service layer to avoid leaking
sensitive threat intelligence data into the event log.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# Threat actor lifecycle
# ---------------------------------------------------------------------------

@dataclass
class ThreatActorCreatedEvent(DomainEvent):
	"""New threat actor profile ingested."""
	event_type: str = "cybersecurity.threat_actor.created"
	actor_id: str = ""
	stix_id: str = ""
	actor_type: str = ""


@dataclass
class ThreatActorUpdatedEvent(DomainEvent):
	"""Threat actor enriched with new intelligence."""
	event_type: str = "cybersecurity.threat_actor.updated"
	actor_id: str = ""
	stix_id: str = ""
	changed_fields: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Indicator lifecycle
# ---------------------------------------------------------------------------

@dataclass
class IndicatorIngestedEvent(DomainEvent):
	"""New IOC ingested from a threat feed."""
	event_type: str = "cybersecurity.indicator.ingested"
	indicator_id: str = ""
	stix_id: str = ""
	indicator_type: str = ""
	severity: str = ""
	feed_url: str = ""


@dataclass
class IndicatorExpiredEvent(DomainEvent):
	"""Indicator passed its valid_until timestamp."""
	event_type: str = "cybersecurity.indicator.expired"
	indicator_id: str = ""
	stix_id: str = ""
	indicator_type: str = ""


# ---------------------------------------------------------------------------
# IOC match events
# ---------------------------------------------------------------------------

@dataclass
class IndicatorMatchedEvent(DomainEvent):
	"""An indicator was matched against live traffic or a log source."""
	event_type: str = "cybersecurity.ioc.matched"
	match_id: str = ""
	indicator_id: str = ""
	incident_id: str = ""   # empty string if no incident opened yet
	severity: str = ""
	source_system: str = ""
	confidence: int = 0


@dataclass
class FalsePositiveMarkedEvent(DomainEvent):
	"""An IndicatorMatch was marked as a false positive."""
	event_type: str = "cybersecurity.ioc.false_positive"
	match_id: str = ""
	indicator_id: str = ""
	marked_by: str = ""


# ---------------------------------------------------------------------------
# Security incident lifecycle
# ---------------------------------------------------------------------------

@dataclass
class IncidentOpenedEvent(DomainEvent):
	"""New security incident opened."""
	event_type: str = "cybersecurity.incident.opened"
	incident_id: str = ""
	incident_number: str = ""
	incident_type: str = ""
	severity: str = ""


@dataclass
class IncidentTriagedEvent(DomainEvent):
	"""Incident severity confirmed and responders assigned."""
	event_type: str = "cybersecurity.incident.triaged"
	incident_id: str = ""
	incident_number: str = ""
	severity: str = ""
	responder_count: int = 0


@dataclass
class IncidentContainedEvent(DomainEvent):
	"""Incident moved to CONTAINED status."""
	event_type: str = "cybersecurity.incident.contained"
	incident_id: str = ""
	incident_number: str = ""
	data_exfiltrated: bool = False


@dataclass
class IncidentResolvedEvent(DomainEvent):
	"""Incident fully resolved."""
	event_type: str = "cybersecurity.incident.resolved"
	incident_id: str = ""
	incident_number: str = ""
	estimated_impact_cents: int = 0


# ---------------------------------------------------------------------------
# Vulnerability events
# ---------------------------------------------------------------------------

@dataclass
class VulnerabilityPublishedEvent(DomainEvent):
	"""New vulnerability record created (CVE published)."""
	event_type: str = "cybersecurity.vulnerability.published"
	vulnerability_id: str = ""
	cve_id: str = ""
	severity: str = ""
	cvss_score: float = 0.0


@dataclass
class VulnerabilityExploitedFlaggedEvent(DomainEvent):
	"""Vulnerability marked as known-exploited-in-the-wild (CISA KEV)."""
	event_type: str = "cybersecurity.vulnerability.exploited_flagged"
	vulnerability_id: str = ""
	cve_id: str = ""
	severity: str = ""


__all__ = [
	"emit_event",
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
]
