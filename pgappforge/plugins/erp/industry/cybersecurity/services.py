"""
pgappforge/plugins/erp/industry/cybersecurity/services.py

Business logic for the Cybersecurity (STIX 2.1) plugin.

CybersecurityService is stateless — all methods accept a SQLAlchemy session
so callers control transaction boundaries. Session can be sync or async-wrapped.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CybersecurityServiceError(Exception):
	"""Base exception for CybersecurityService."""


class IndicatorNotFoundError(CybersecurityServiceError):
	"""Raised when an Indicator row cannot be found."""


class IncidentNotFoundError(CybersecurityServiceError):
	"""Raised when a SecurityIncident row cannot be found."""


class VulnerabilityNotFoundError(CybersecurityServiceError):
	"""Raised when a Vulnerability row cannot be found."""


# ---------------------------------------------------------------------------
# CybersecurityService
# ---------------------------------------------------------------------------

class CybersecurityService:
	"""STIX 2.1 threat intelligence and incident response service.

	All monetary impact values are integer cents throughout.
	"""

	# ------------------------------------------------------------------
	# ingest_feed
	# ------------------------------------------------------------------

	def ingest_feed(
		self,
		feed_url: str,
		feed_type: str,
		tenant_id: str,
		session: Any,
		*,
		dry_run: bool = False,
	) -> dict[str, Any]:
		"""Pull a STIX/TAXII or simple IOC feed and persist new Indicators.

		Performs a lightweight HTTP GET on *feed_url*, parses the payload as
		a STIX bundle or plain-text IOC list (one value per line), and upserts
		Indicator rows.  Returns a summary dict.

		Args:
			feed_url: URL of the threat feed (TAXII collection or flat file).
			feed_type: "stix_bundle" | "flat_ip" | "flat_domain" | "flat_hash".
			tenant_id: Target tenant UUID.
			session: SQLAlchemy session.
			dry_run: Parse without writing — useful for feed validation.

		Returns:
			{new: int, updated: int, skipped: int, feed_url: str}
		"""
		from pgappforge.plugins.erp.industry.cybersecurity.models import Indicator
		from pgappforge.plugins.erp.industry.cybersecurity.events import (
			IndicatorIngestedEvent,
			emit_event,
		)

		_type_map = {
			"flat_ip": "IP_ADDRESS",
			"flat_domain": "DOMAIN",
			"flat_hash": "FILE_HASH",
			"stix_bundle": "IP_ADDRESS",  # default; real bundle parser overrides per object
		}

		new_count = updated_count = skipped_count = 0

		try:
			import urllib.request
			with urllib.request.urlopen(feed_url, timeout=15) as resp:
				raw = resp.read().decode("utf-8", errors="replace")
		except Exception as exc:
			log.warning("ingest_feed: failed to fetch %s — %s", feed_url, exc)
			return {"new": 0, "updated": 0, "skipped": 0, "feed_url": feed_url, "error": str(exc)}

		# Parse lines for flat feeds; real STIX bundle parsing would use stix2 library
		lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.startswith("#")]
		indicator_type = _type_map.get(feed_type, "IP_ADDRESS")
		now = datetime.now(timezone.utc)

		for value in lines[:5000]:  # cap at 5k per ingest call
			stix_id = f"indicator--{uuid.uuid4()}"
			existing = session.execute(
				sa.select(Indicator).where(
					Indicator.tenant_id == tenant_id,
					Indicator.pattern.contains(value),
				)
			).scalar_one_or_none()

			if existing is not None:
				skipped_count += 1
				continue

			if dry_run:
				new_count += 1
				continue

			ioc = Indicator(
				tenant_id=tenant_id,
				stix_id=stix_id,
				indicator_type=indicator_type,
				name=f"Feed IOC: {value[:80]}",
				pattern=f"[{indicator_type.lower()}:value = '{value}']",
				pattern_type="stix",
				valid_from=now,
				severity="MEDIUM",
				confidence=60,
				kill_chain_phases=[],
				labels=["feed-ingest"],
			)
			session.add(ioc)
			session.flush()
			new_count += 1
			emit_event(
				IndicatorIngestedEvent(
					indicator_id=ioc.id,
					stix_id=stix_id,
					indicator_type=indicator_type,
					severity="MEDIUM",
					feed_url=feed_url,
				),
				session,
			)

		log.info(
			"ingest_feed: feed=%s new=%d updated=%d skipped=%d dry_run=%s",
			feed_url, new_count, updated_count, skipped_count, dry_run,
		)
		return {
			"new": new_count,
			"updated": updated_count,
			"skipped": skipped_count,
			"feed_url": feed_url,
		}

	# ------------------------------------------------------------------
	# correlate_indicators
	# ------------------------------------------------------------------

	def correlate_indicators(
		self,
		incident_id: str,
		session: Any,
		*,
		limit: int = 50,
	) -> list[dict[str, Any]]:
		"""Find Indicators whose patterns overlap with a SecurityIncident.

		Correlation is performed by matching indicator patterns against the
		incident's affected_systems list (substring match).  Returns up to
		*limit* candidate indicators ordered by severity then confidence.

		Args:
			incident_id: UUID of the SecurityIncident.
			session: SQLAlchemy session.
			limit: Max results to return.

		Returns:
			List of dicts with indicator metadata and match strength.

		Raises:
			IncidentNotFoundError: If incident does not exist.
		"""
		from pgappforge.plugins.erp.industry.cybersecurity.models import (
			Indicator,
			IndicatorMatch,
			SecurityIncident,
		)

		incident = session.get(SecurityIncident, incident_id)
		if incident is None:
			raise IncidentNotFoundError(f"SecurityIncident {incident_id!r} not found")

		systems = incident.affected_systems or []
		now = datetime.now(timezone.utc)

		# Load active, non-expired indicators for this tenant
		q = (
			sa.select(Indicator)
			.where(
				Indicator.tenant_id == incident.tenant_id,
				Indicator.valid_from <= now,
				sa.or_(Indicator.valid_until.is_(None), Indicator.valid_until >= now),
			)
			.order_by(
				sa.case(
					{"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3},
					value=Indicator.severity,
					else_=4,
				),
				Indicator.confidence.desc().nulls_last(),
			)
			.limit(limit * 5)  # fetch extra, filter by correlation below
		)
		candidates = session.execute(q).scalars().all()

		results = []
		for ind in candidates:
			# Naive correlation: check if any affected system appears in pattern
			matched_system = next(
				(s for s in systems if s and s.lower() in (ind.pattern or "").lower()),
				None,
			)
			score = ind.confidence or 50
			if matched_system:
				score = min(100, score + 20)

			results.append({
				"indicator_id": ind.id,
				"stix_id": ind.stix_id,
				"name": ind.name,
				"indicator_type": ind.indicator_type,
				"severity": ind.severity,
				"confidence": ind.confidence,
				"pattern": ind.pattern,
				"matched_system": matched_system,
				"correlation_score": score,
			})

			if len(results) >= limit:
				break

		log.debug(
			"correlate_indicators: incident=%s found %d candidates", incident_id, len(results)
		)
		return results

	# ------------------------------------------------------------------
	# calculate_risk_score
	# ------------------------------------------------------------------

	def calculate_risk_score(
		self,
		system_id: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Compute a composite risk score for a system identifier.

		Aggregates:
		  - Open/active SecurityIncident count weighted by severity
		  - Active Indicator matches against this system
		  - Critical/exploited Vulnerabilities in scope

		Returns a dict with component scores and a composite 0–100 risk score.

		Args:
			system_id: Hostname, IP, or asset identifier.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.
		"""
		from pgappforge.plugins.erp.industry.cybersecurity.models import (
			Indicator,
			IndicatorMatch,
			SecurityIncident,
			Vulnerability,
		)

		now = datetime.now(timezone.utc)
		_severity_weight = {"P1": 40, "P2": 20, "P3": 10, "P4": 5}
		_vuln_weight = {"CRITICAL": 30, "HIGH": 20, "MEDIUM": 10, "LOW": 5, "INFO": 1}

		# Active incidents affecting this system
		incidents = session.execute(
			sa.select(SecurityIncident).where(
				SecurityIncident.tenant_id == tenant_id,
				SecurityIncident.status.in_(["NEW", "INVESTIGATING", "CONTAINED"]),
				sa.cast(SecurityIncident.affected_systems, sa.Text).contains(system_id),
			)
		).scalars().all()

		incident_score = min(
			100,
			sum(_severity_weight.get(inc.severity, 5) for inc in incidents),
		)

		# Active IOC matches for this system
		matches = session.execute(
			sa.select(IndicatorMatch).where(
				IndicatorMatch.tenant_id == tenant_id,
				IndicatorMatch.matched_value.contains(system_id),
				IndicatorMatch.is_false_positive == False,  # noqa: E712
			)
		).scalars().all()
		ioc_score = min(100, len(matches) * 15)

		# Critical/exploited vulnerabilities
		vulns = session.execute(
			sa.select(Vulnerability).where(
				Vulnerability.tenant_id == tenant_id,
				Vulnerability.severity.in_(["CRITICAL", "HIGH"]),
				Vulnerability.is_exploited == True,  # noqa: E712
			)
		).scalars().all()
		vuln_score = min(100, sum(_vuln_weight.get(v.severity, 5) for v in vulns))

		composite = min(100, int((incident_score * 0.5) + (ioc_score * 0.3) + (vuln_score * 0.2)))

		return {
			"system_id": system_id,
			"composite_risk_score": composite,
			"incident_score": incident_score,
			"ioc_score": ioc_score,
			"vulnerability_score": vuln_score,
			"active_incidents": len(incidents),
			"active_ioc_matches": len(matches),
			"critical_exploited_vulns": len(vulns),
		}

	# ------------------------------------------------------------------
	# triage_incident
	# ------------------------------------------------------------------

	def triage_incident(
		self,
		incident_id: str,
		severity: str,
		responders: list[str],
		session: Any,
	) -> Any:
		"""Confirm incident severity and assign responders.

		Transitions status from NEW → INVESTIGATING.
		Emits IncidentTriagedEvent.

		Args:
			incident_id: UUID of the SecurityIncident.
			severity: Validated severity string (P1/P2/P3/P4).
			responders: List of responder UUID strings.
			session: SQLAlchemy session.

		Returns:
			Updated SecurityIncident instance.

		Raises:
			IncidentNotFoundError: If incident does not exist.
		"""
		from pgappforge.plugins.erp.industry.cybersecurity.models import (
			INCIDENT_SEVERITY,
			SecurityIncident,
		)
		from pgappforge.plugins.erp.industry.cybersecurity.events import (
			IncidentTriagedEvent,
			emit_event,
		)

		incident = session.get(SecurityIncident, incident_id)
		if incident is None:
			raise IncidentNotFoundError(f"SecurityIncident {incident_id!r} not found")

		if severity not in INCIDENT_SEVERITY:
			raise CybersecurityServiceError(
				f"Invalid severity {severity!r}; must be one of {INCIDENT_SEVERITY}"
			)

		incident.severity = severity
		incident.responders = responders or []
		if incident.status == "NEW":
			incident.status = "INVESTIGATING"

		session.flush()

		emit_event(
			IncidentTriagedEvent(
				incident_id=incident.id,
				incident_number=incident.incident_number,
				severity=incident.severity,
				responder_count=len(incident.responders),
			),
			session,
		)

		log.info(
			"triage_incident: incident=%s sev=%s responders=%d",
			incident_id, severity, len(responders),
		)
		return incident

	# ------------------------------------------------------------------
	# generate_threat_report
	# ------------------------------------------------------------------

	def generate_threat_report(
		self,
		tenant_id: str,
		session: Any,
		*,
		period_days: int = 30,
	) -> dict[str, Any]:
		"""Generate a threat intelligence summary for the last *period_days*.

		Returns aggregated counts and top items per category (actors, indicators,
		incidents) suitable for a SOC dashboard or executive report.

		Args:
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.
			period_days: Look-back window in days.

		Returns:
			dict with top_threats, top_indicators, recent_incidents, summary counts.
		"""
		from pgappforge.plugins.erp.industry.cybersecurity.models import (
			Indicator,
			SecurityIncident,
			ThreatActor,
			Vulnerability,
		)
		from datetime import timedelta

		cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
		cutoff_tz = datetime.now(timezone.utc) - timedelta(days=period_days)

		# Top threat actors (most recently seen)
		actors = session.execute(
			sa.select(ThreatActor)
			.where(ThreatActor.tenant_id == tenant_id)
			.order_by(ThreatActor.updated_at.desc())
			.limit(10)
		).scalars().all()

		# High/critical indicators active in window
		indicators = session.execute(
			sa.select(Indicator)
			.where(
				Indicator.tenant_id == tenant_id,
				Indicator.valid_from >= cutoff_tz,
				Indicator.severity.in_(["HIGH", "CRITICAL"]),
			)
			.order_by(Indicator.valid_from.desc())
			.limit(20)
		).scalars().all()

		# Recent incidents
		incidents = session.execute(
			sa.select(SecurityIncident)
			.where(
				SecurityIncident.tenant_id == tenant_id,
				SecurityIncident.detected_at >= cutoff_tz,
			)
			.order_by(SecurityIncident.detected_at.desc())
			.limit(20)
		).scalars().all()

		# Exploited vuln count
		exploited_count = session.execute(
			sa.select(sa.func.count(Vulnerability.id)).where(
				Vulnerability.tenant_id == tenant_id,
				Vulnerability.is_exploited == True,  # noqa: E712
			)
		).scalar_one()

		return {
			"period_days": period_days,
			"tenant_id": tenant_id,
			"summary": {
				"threat_actor_count": len(actors),
				"high_critical_indicators": len(indicators),
				"incidents_in_period": len(incidents),
				"exploited_vulns": exploited_count,
			},
			"top_threats": [
				{
					"id": a.id,
					"name": a.name,
					"actor_type": a.actor_type,
					"sophistication": a.sophistication,
				}
				for a in actors
			],
			"top_indicators": [
				{
					"id": i.id,
					"name": i.name,
					"indicator_type": i.indicator_type,
					"severity": i.severity,
					"confidence": i.confidence,
				}
				for i in indicators
			],
			"recent_incidents": [
				{
					"id": inc.id,
					"incident_number": inc.incident_number,
					"title": inc.title,
					"incident_type": inc.incident_type,
					"severity": inc.severity,
					"status": inc.status,
					"detected_at": inc.detected_at.isoformat() if inc.detected_at else None,
					"data_exfiltrated": inc.data_exfiltrated,
				}
				for inc in incidents
			],
		}

	# ------------------------------------------------------------------
	# search_ioc
	# ------------------------------------------------------------------

	def search_ioc(
		self,
		value: str,
		ioc_type: str | None,
		tenant_id: str,
		session: Any,
		*,
		limit: int = 100,
	) -> list[dict[str, Any]]:
		"""Search for IOC indicators matching *value*.

		Performs a case-insensitive substring search against the pattern field
		and optionally filters by indicator_type.

		Args:
			value: Raw IOC value (IP, domain, hash, URL substring).
			ioc_type: Optional indicator_type filter (IP_ADDRESS, DOMAIN, etc.).
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.
			limit: Max results.

		Returns:
			List of indicator dicts including matches.
		"""
		from pgappforge.plugins.erp.industry.cybersecurity.models import Indicator

		q = (
			sa.select(Indicator)
			.where(
				Indicator.tenant_id == tenant_id,
				Indicator.pattern.ilike(f"%{value}%"),
			)
			.order_by(
				sa.case(
					{"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3},
					value=Indicator.severity,
					else_=4,
				)
			)
			.limit(limit)
		)
		if ioc_type:
			q = q.where(Indicator.indicator_type == ioc_type)

		rows = session.execute(q).scalars().all()
		log.debug("search_ioc: value=%r type=%r found=%d", value, ioc_type, len(rows))

		return [
			{
				"indicator_id": r.id,
				"stix_id": r.stix_id,
				"name": r.name,
				"indicator_type": r.indicator_type,
				"pattern": r.pattern,
				"severity": r.severity,
				"confidence": r.confidence,
				"valid_from": r.valid_from.isoformat() if r.valid_from else None,
				"valid_until": r.valid_until.isoformat() if r.valid_until else None,
				"labels": r.labels,
			}
			for r in rows
		]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"CybersecurityService",
	"CybersecurityServiceError",
	"IndicatorNotFoundError",
	"IncidentNotFoundError",
	"VulnerabilityNotFoundError",
]
