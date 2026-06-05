"""
pgappforge/plugins/erp/industry/cybersecurity/models.py

SQLAlchemy models for the Cybersecurity (STIX 2.1) plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY
  - AuditMixin on all mutable entities
  - ARRAY columns via postgresql ARRAY type
  - JSONB for structured/variable data

Table name convention: cs_<entity>
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations (module-level constants used by services/views)
# ---------------------------------------------------------------------------

ACTOR_TYPE = ("NATION_STATE", "CRIMINAL", "HACKTIVIST", "INSIDER", "UNKNOWN")
SOPHISTICATION = ("NONE", "MINIMAL", "INTERMEDIATE", "ADVANCED", "EXPERT", "INNOVATOR")
RESOURCE_LEVEL = ("INDIVIDUAL", "CLUB", "CONTEST", "TEAM", "ORGANIZATION", "GOVERNMENT")

INDICATOR_TYPE = ("MALICIOUS_URL", "FILE_HASH", "IP_ADDRESS", "DOMAIN", "EMAIL")
SEVERITY = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

INCIDENT_TYPE = ("BREACH", "PHISHING", "RANSOMWARE", "DDoS", "INSIDER", "APT", "OTHER")
INCIDENT_SEVERITY = ("P1", "P2", "P3", "P4")
INCIDENT_STATUS = ("NEW", "INVESTIGATING", "CONTAINED", "RESOLVED", "CLOSED")

VULN_SEVERITY = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")


# ---------------------------------------------------------------------------
# ThreatActor
# ---------------------------------------------------------------------------

class ThreatActor(AuditMixin, Model):
	"""STIX 2.1 threat-actor SDO.

	actor_type maps to STIX threat-actor-type OV.
	sophistication and resource_level use STIX attack-resource-level / sophistication OVs.
	motivation TEXT[] stores STIX attack-motivation OV values.
	aliases TEXT[] lists alternative vendor names for cross-referencing.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cs_threat_actor"
	__table_args__ = (
		UniqueConstraint("stix_id", name="uq_cs_threat_actor_stix_id"),
		Index("ix_cs_threat_actor_tenant", "tenant_id"),
		Index("ix_cs_threat_actor_type", "actor_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	stix_id = Column(
		String(100),
		nullable=False,
		unique=True,
		comment="STIX 2.1 identifier e.g. threat-actor--<UUID>",
	)
	name = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)

	actor_type = Column(
		String(20),
		nullable=False,
		default="UNKNOWN",
		comment="NATION_STATE/CRIMINAL/HACKTIVIST/INSIDER/UNKNOWN",
	)
	sophistication = Column(
		String(20),
		nullable=True,
		comment="NONE/MINIMAL/INTERMEDIATE/ADVANCED/EXPERT/INNOVATOR",
	)
	resource_level = Column(
		String(20),
		nullable=True,
		comment="INDIVIDUAL/CLUB/CONTEST/TEAM/ORGANIZATION/GOVERNMENT",
	)
	motivation = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
		comment="STIX attack-motivation OV values",
	)
	aliases = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
		comment="Alternative names across vendor intel feeds",
	)
	first_seen = Column(Date, nullable=True)
	last_seen = Column(Date, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return f"<ThreatActor {self.name!r} type={self.actor_type!r}>"


# ---------------------------------------------------------------------------
# Indicator
# ---------------------------------------------------------------------------

class Indicator(AuditMixin, Model):
	"""STIX 2.1 indicator SDO.

	pattern holds a STIX PATTERNING expression (or YARA/Sigma/Snort rule).
	kill_chain_phases JSONB: [{kill_chain_name, phase_name}, ...]
	confidence: 0–100 (100 = high certainty).
	valid_until NULL = indefinitely active.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cs_indicator"
	__table_args__ = (
		UniqueConstraint("stix_id", name="uq_cs_indicator_stix_id"),
		Index("ix_cs_indicator_tenant", "tenant_id"),
		Index("ix_cs_indicator_type", "indicator_type"),
		Index("ix_cs_indicator_severity", "severity"),
		Index("ix_cs_indicator_valid_from", "valid_from"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	stix_id = Column(String(100), nullable=False, unique=True)
	indicator_type = Column(
		String(20),
		nullable=False,
		comment="MALICIOUS_URL/FILE_HASH/IP_ADDRESS/DOMAIN/EMAIL",
	)
	pattern = Column(Text, nullable=False, comment="STIX PATTERNING or YARA/Sigma expression")
	pattern_type = Column(String(20), nullable=False, default="stix", server_default="stix")
	name = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)

	confidence = Column(
		Integer,
		nullable=True,
		comment="0–100; CHECK enforced at DB level",
	)
	valid_from = Column(DateTime(timezone=True), nullable=False)
	valid_until = Column(DateTime(timezone=True), nullable=True, comment="NULL = indefinite")

	kill_chain_phases = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{kill_chain_name, phase_name}]",
	)
	labels = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
	)
	severity = Column(
		String(10),
		nullable=False,
		default="MEDIUM",
		comment="LOW/MEDIUM/HIGH/CRITICAL",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	matches: list[IndicatorMatch] = relationship(
		"IndicatorMatch",
		back_populates="indicator",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Indicator {self.name!r} type={self.indicator_type!r} sev={self.severity!r}>"


# ---------------------------------------------------------------------------
# Malware
# ---------------------------------------------------------------------------

class Malware(AuditMixin, Model):
	"""STIX 2.1 malware SDO.

	malware_type TEXT[]: STIX malware-type OV (ransomware, dropper, trojan, etc.)
	capabilities TEXT[]: STIX malware-capabilities OV.
	os_execution_envs TEXT[]: operating systems the malware targets.
	architecture_execution_envs TEXT[]: CPU architectures (x86, x86-64, ARM, etc.)
	"""

	__allow_unmapped__ = True
	__tablename__ = "cs_malware"
	__table_args__ = (
		UniqueConstraint("stix_id", name="uq_cs_malware_stix_id"),
		Index("ix_cs_malware_tenant", "tenant_id"),
		Index("ix_cs_malware_family", "is_family"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	stix_id = Column(String(100), nullable=False, unique=True)
	name = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)

	malware_type = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
		comment="STIX malware-type OV values",
	)
	is_family = Column(Boolean, nullable=False, default=False, server_default="false")

	capabilities = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
		comment="STIX malware-capabilities OV values",
	)
	os_execution_envs = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
	)
	architecture_execution_envs = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return f"<Malware {self.name!r} family={self.is_family}>"


# ---------------------------------------------------------------------------
# SecurityIncident
# ---------------------------------------------------------------------------

class SecurityIncident(AuditMixin, Model):
	"""Security incident record.

	affected_systems TEXT[]: hostnames/IPs involved.
	responders UUID[]: IDs of responding analysts/engineers.
	estimated_impact_cents: financial impact in integer cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cs_security_incident"
	__table_args__ = (
		UniqueConstraint("tenant_id", "incident_number", name="uq_cs_incident_tenant_num"),
		Index("ix_cs_incident_tenant", "tenant_id"),
		Index("ix_cs_incident_status", "status"),
		Index("ix_cs_incident_severity", "severity"),
		Index("ix_cs_incident_detected", "detected_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	incident_number = Column(String(50), nullable=False, comment="Unique per tenant, e.g. INC-2024-0001")
	title = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)

	incident_type = Column(
		String(20),
		nullable=False,
		comment="BREACH/PHISHING/RANSOMWARE/DDoS/INSIDER/APT/OTHER",
	)
	severity = Column(
		String(5),
		nullable=False,
		default="P3",
		comment="P1/P2/P3/P4",
	)
	status = Column(
		String(20),
		nullable=False,
		default="NEW",
		server_default="NEW",
		comment="NEW/INVESTIGATING/CONTAINED/RESOLVED/CLOSED",
	)

	detected_at = Column(DateTime(timezone=True), nullable=False)
	contained_at = Column(DateTime(timezone=True), nullable=True)
	resolved_at = Column(DateTime(timezone=True), nullable=True)

	affected_systems = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
	)
	data_exfiltrated = Column(Boolean, nullable=False, default=False, server_default="false")
	estimated_impact_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Estimated financial impact in integer cents",
	)
	responders = Column(
		ARRAY(UUID(as_uuid=False)),
		nullable=False,
		default=list,
		server_default="{}",
		comment="UUIDs of assigned responders",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	matches: list[IndicatorMatch] = relationship(
		"IndicatorMatch",
		back_populates="incident",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SecurityIncident {self.incident_number!r} sev={self.severity!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# IndicatorMatch
# ---------------------------------------------------------------------------

class IndicatorMatch(AuditMixin, Model):
	"""Junction — an Indicator matched against an event or SecurityIncident.

	incident_id nullable: a match may be detected before an incident is opened.
	matched_value: the raw value that triggered the match (e.g. the IP or hash).
	confidence: match-specific confidence, may differ from indicator-level confidence.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cs_indicator_match"
	__table_args__ = (
		Index("ix_cs_ioc_match_indicator", "indicator_id"),
		Index("ix_cs_ioc_match_incident", "incident_id"),
		Index("ix_cs_ioc_match_tenant", "tenant_id"),
		Index("ix_cs_ioc_match_fp", "is_false_positive"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	indicator_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cs_indicator.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	incident_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cs_security_incident.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)

	matched_at = Column(DateTime(timezone=True), nullable=False)
	matched_value = Column(Text, nullable=False, comment="Raw value that triggered this match")
	source_system = Column(String(100), nullable=False)
	confidence = Column(Integer, nullable=True, comment="0–100")
	is_false_positive = Column(Boolean, nullable=False, default=False, server_default="false")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	indicator: Indicator = relationship("Indicator", back_populates="matches", lazy="select")
	incident: SecurityIncident | None = relationship(
		"SecurityIncident", back_populates="matches", lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<IndicatorMatch indicator={self.indicator_id!r} "
			f"fp={self.is_false_positive} conf={self.confidence}>"
		)


# ---------------------------------------------------------------------------
# Vulnerability
# ---------------------------------------------------------------------------

class Vulnerability(AuditMixin, Model):
	"""CVE-anchored vulnerability record.

	cvss_score: NUMERIC(4,2) — e.g. 9.80.
	affected_products JSONB: [{vendor, product, version_range}, ...]
	is_exploited: known-exploited-in-the-wild flag (CISA KEV catalogue).
	"""

	__allow_unmapped__ = True
	__tablename__ = "cs_vulnerability"
	__table_args__ = (
		UniqueConstraint("cve_id", name="uq_cs_vuln_cve_id"),
		Index("ix_cs_vuln_tenant", "tenant_id"),
		Index("ix_cs_vuln_severity", "severity"),
		Index("ix_cs_vuln_exploited", "is_exploited"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	cve_id = Column(
		String(20),
		nullable=False,
		unique=True,
		comment="CVE-YYYY-NNNNN format",
	)
	title = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)

	cvss_score = Column(
		Numeric(4, 2),
		nullable=True,
		comment="CVSS base score 0.00–10.00",
	)
	cvss_vector = Column(String(100), nullable=True, comment="CVSS vector string")
	severity = Column(
		String(10),
		nullable=False,
		default="MEDIUM",
		comment="CRITICAL/HIGH/MEDIUM/LOW/INFO",
	)

	affected_products = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{vendor, product, version_range}]",
	)

	published_at = Column(Date, nullable=True)
	modified_at = Column(Date, nullable=True)

	is_exploited = Column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
		comment="Known-exploited-in-the-wild (CISA KEV)",
	)
	patch_available = Column(Boolean, nullable=False, default=False, server_default="false")
	patch_url = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return f"<Vulnerability {self.cve_id!r} sev={self.severity!r} cvss={self.cvss_score}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ThreatActor",
	"Indicator",
	"Malware",
	"SecurityIncident",
	"IndicatorMatch",
	"Vulnerability",
	"ACTOR_TYPE",
	"SOPHISTICATION",
	"RESOURCE_LEVEL",
	"INDICATOR_TYPE",
	"SEVERITY",
	"INCIDENT_TYPE",
	"INCIDENT_SEVERITY",
	"INCIDENT_STATUS",
	"VULN_SEVERITY",
]
