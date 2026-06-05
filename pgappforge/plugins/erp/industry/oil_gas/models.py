"""
pgappforge/plugins/erp/industry/oil_gas/models.py

SQLAlchemy models for the Oil & Gas plugin (ISO 15926-based plant lifecycle).

Design invariants:
  - All PKs:         UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps:  DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - All models:      tenant_id UUID NOT NULL
  - All amounts:     Integer cents (INTEGER) — NEVER float or Numeric
  - FKs:             UUID strings (as_uuid=False)
  - Arrays:          ARRAY(UUID) for assigned_crew_ids
  - Geometry:        GeoAlchemy2 POINT 4326 for facility location
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
# Facility
# ---------------------------------------------------------------------------

class Facility(AuditMixin, Model):
	"""Top-level production or processing facility.

	facility_type covers the full O&G value chain: upstream wells/pads,
	midstream gathering/transport, downstream processing, refineries, and
	LNG terminals.  location is a PostGIS Point (WGS84) for GIS integration.
	"""

	__allow_unmapped__ = True
	__tablename__ = "og_facility"
	__table_args__ = (
		UniqueConstraint("tenant_id", "facility_code", name="uq_og_facility_tenant_code"),
		Index("ix_og_facility_tenant", "tenant_id"),
		Index("ix_og_facility_type", "facility_type"),
		Index("ix_og_facility_status", "status"),
		Index("ix_og_facility_operator", "operator_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	facility_code = Column(
		String(50),
		nullable=False,
		comment="Unique business code, e.g. FLD-001-A",
	)
	name = Column(String(255), nullable=False)
	facility_type = Column(
		String(30),
		nullable=False,
		comment="UPSTREAM|MIDSTREAM|DOWNSTREAM|REFINERY|LNG",
	)
	# Stored as WKT string when GeoAlchemy2 not available; use Geometry when it is.
	location = Column(
		Text,
		nullable=True,
		comment="WKT Point(lon lat) SRID 4326, e.g. POINT(36.8219 -1.2921)",
	)
	country_code = Column(String(2), nullable=False, comment="ISO 3166-1 alpha-2")
	operator_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="FK → foundation.Party (operator company)",
	)
	design_capacity = Column(
		Numeric(15, 2),
		nullable=True,
		comment="Nameplate design capacity in capacity_unit",
	)
	capacity_unit = Column(String(20), nullable=True, comment="e.g. bbl/d, MMscfd, t/y")
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE|MAINTENANCE|SHUTDOWN|DECOMMISSIONED",
	)
	commissioning_date = Column(Date, nullable=True)
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

	assets: list[Asset] = relationship(
		"Asset",
		back_populates="facility",
		lazy="select",
		foreign_keys="Asset.facility_id",
	)
	production_records: list[ProductionRecord] = relationship(
		"ProductionRecord",
		back_populates="facility",
		lazy="select",
	)
	incident_reports: list[IncidentReport] = relationship(
		"IncidentReport",
		back_populates="facility",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Facility {self.facility_code!r} {self.name!r} type={self.facility_type!r}>"


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------

class Asset(AuditMixin, Model):
	"""Physical asset / equipment item within a facility.

	tag_number follows ISA-5.1 / ISO 15926-2 naming conventions.
	criticality A/B/C maps to: A=safety-critical, B=production-critical, C=general.
	Supports equipment hierarchies via parent_asset_id self-FK.
	"""

	__allow_unmapped__ = True
	__tablename__ = "og_asset"
	__table_args__ = (
		UniqueConstraint("tenant_id", "tag_number", name="uq_og_asset_tenant_tag"),
		Index("ix_og_asset_facility", "facility_id"),
		Index("ix_og_asset_tenant", "tenant_id"),
		Index("ix_og_asset_status", "status"),
		Index("ix_og_asset_criticality", "criticality"),
		Index("ix_og_asset_parent", "parent_asset_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	tag_number = Column(
		String(100),
		nullable=False,
		comment="ISO 15926-2 tag, e.g. 101-P-001A",
	)
	facility_id = Column(
		UUID(as_uuid=False),
		ForeignKey("og_facility.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	asset_class = Column(
		String(100),
		nullable=False,
		comment="RDL class, e.g. CentrifugalPump, HeatExchanger",
	)
	description = Column(Text, nullable=True)
	manufacturer = Column(String(200), nullable=True)
	model = Column(String(100), nullable=True)
	serial_number = Column(String(100), nullable=True)
	installation_date = Column(Date, nullable=True)
	design_pressure_bar = Column(Numeric(8, 2), nullable=True)
	design_temperature_c = Column(Numeric(6, 2), nullable=True)
	criticality = Column(
		String(1),
		nullable=False,
		default="C",
		comment="A=safety-critical | B=production-critical | C=general",
	)
	status = Column(
		String(20),
		nullable=False,
		default="OPERATIONAL",
		comment="OPERATIONAL|STANDBY|MAINTENANCE|FAILED|DECOMMISSIONED",
	)
	parent_asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("og_asset.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
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

	facility: Facility = relationship(
		"Facility",
		back_populates="assets",
		lazy="select",
		foreign_keys=[facility_id],
	)
	parent: Asset = relationship(
		"Asset",
		remote_side="Asset.id",
		foreign_keys=[parent_asset_id],
		lazy="select",
	)
	children: list[Asset] = relationship(
		"Asset",
		foreign_keys=[parent_asset_id],
		back_populates="parent",
		lazy="select",
	)
	maintenance_works: list[MaintenanceWork] = relationship(
		"MaintenanceWork",
		back_populates="asset",
		lazy="select",
	)
	hazop_reviews: list[HAZOPReview] = relationship(
		"HAZOPReview",
		back_populates="asset",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Asset {self.tag_number!r} class={self.asset_class!r} "
			f"crit={self.criticality!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# MaintenanceWork
# ---------------------------------------------------------------------------

class MaintenanceWork(AuditMixin, Model):
	"""Work order for asset maintenance activities.

	All cost amounts are integer cents.
	assigned_crew_ids is a PostgreSQL UUID[] array of person Party IDs.
	safety_requirements carries JSONB: permits, PPE, isolation procedures.
	"""

	__allow_unmapped__ = True
	__tablename__ = "og_maintenance_work"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "work_order_number",
			name="uq_og_maint_tenant_wo",
		),
		Index("ix_og_maint_asset", "asset_id"),
		Index("ix_og_maint_tenant", "tenant_id"),
		Index("ix_og_maint_status", "status"),
		Index("ix_og_maint_scheduled_start", "scheduled_start"),
		Index("ix_og_maint_contractor", "assigned_contractor_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	work_order_number = Column(String(50), nullable=False)
	asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("og_asset.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	work_type = Column(
		String(20),
		nullable=False,
		comment="PREVENTIVE|CORRECTIVE|CONDITION_BASED|TURNAROUND",
	)
	description = Column(Text, nullable=False)
	scheduled_start = Column(DateTime(timezone=True), nullable=False)
	scheduled_end = Column(DateTime(timezone=True), nullable=False)
	actual_start = Column(DateTime(timezone=True), nullable=True)
	actual_end = Column(DateTime(timezone=True), nullable=True)
	assigned_contractor_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	assigned_crew_ids = Column(
		ARRAY(UUID(as_uuid=False)),
		nullable=False,
		default=list,
		server_default="{}",
		comment="Array of Party UUIDs (individual crew members)",
	)
	estimated_cost_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Estimated cost in integer cents",
	)
	actual_cost_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Actual cost in integer cents",
	)
	status = Column(
		String(20),
		nullable=False,
		default="PLANNED",
		comment="PLANNED|APPROVED|IN_PROGRESS|COMPLETED|CANCELLED",
	)
	safety_requirements = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Permits, PPE, isolation certs, JSA references",
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

	asset: Asset = relationship(
		"Asset",
		back_populates="maintenance_works",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<MaintenanceWork {self.work_order_number!r} type={self.work_type!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ProductionRecord
# ---------------------------------------------------------------------------

class ProductionRecord(AuditMixin, Model):
	"""Daily production record for a facility.

	quantity is Numeric(15,4) — stored in the unit specified by unit column.
	quality_parameters carries JSONB: API gravity, H2S ppm, GOR, etc.
	downtime_hours tracks production loss time.
	"""

	__allow_unmapped__ = True
	__tablename__ = "og_production_record"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "facility_id", "production_date", "product_type",
			name="uq_og_prod_facility_date_product",
		),
		Index("ix_og_prod_facility", "facility_id"),
		Index("ix_og_prod_tenant", "tenant_id"),
		Index("ix_og_prod_date", "production_date"),
		Index("ix_og_prod_type", "product_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	facility_id = Column(
		UUID(as_uuid=False),
		ForeignKey("og_facility.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	production_date = Column(Date, nullable=False)
	product_type = Column(
		String(20),
		nullable=False,
		comment="CRUDE_OIL|GAS|LNG|REFINED_PRODUCT|NGL",
	)
	quantity = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Gross production in unit",
	)
	unit = Column(
		String(20),
		nullable=False,
		comment="e.g. bbl, Mscf, t, m3",
	)
	quality_parameters = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="API gravity, BS&W, H2S ppm, GCV, etc.",
	)
	downtime_hours = Column(
		Numeric(5, 2),
		nullable=False,
		default=0,
	)
	downtime_reason = Column(String(200), nullable=True)
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

	facility: Facility = relationship(
		"Facility",
		back_populates="production_records",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ProductionRecord facility={self.facility_id!r} "
			f"date={self.production_date!r} product={self.product_type!r} "
			f"qty={self.quantity}>"
		)


# ---------------------------------------------------------------------------
# HAZOPReview
# ---------------------------------------------------------------------------

class HAZOPReview(AuditMixin, Model):
	"""Hazard and Operability Study record for an asset node.

	findings and action_items stored as JSONB arrays of structured objects.
	Status lifecycle: DRAFT → COMPLETED → CLOSED.
	"""

	__allow_unmapped__ = True
	__tablename__ = "og_hazop_review"
	__table_args__ = (
		Index("ix_og_hazop_asset", "asset_id"),
		Index("ix_og_hazop_tenant", "tenant_id"),
		Index("ix_og_hazop_status", "status"),
		Index("ix_og_hazop_review_date", "review_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("og_asset.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	review_date = Column(Date, nullable=False)
	review_leader_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="FK → foundation.Party (study leader)",
	)
	scope = Column(Text, nullable=False)
	findings = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{node, deviation, cause, consequence, safeguard, risk_rank}]",
	)
	action_items = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{action, responsible_party, due_date, status}]",
	)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|COMPLETED|CLOSED",
	)
	next_review_date = Column(Date, nullable=True)
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

	asset: Asset = relationship(
		"Asset",
		back_populates="hazop_reviews",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<HAZOPReview asset={self.asset_id!r} date={self.review_date!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# IncidentReport
# ---------------------------------------------------------------------------

class IncidentReport(AuditMixin, Model):
	"""HSE incident record.

	Covers TIER1/TIER2/TIER3 severity per IOGP definitions.
	corrective_actions JSONB: [{action, owner, due_date, closed_at}].
	reported_to_regulator tracks regulatory notification obligation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "og_incident_report"
	__table_args__ = (
		Index("ix_og_incident_facility", "facility_id"),
		Index("ix_og_incident_tenant", "tenant_id"),
		Index("ix_og_incident_type", "incident_type"),
		Index("ix_og_incident_severity", "severity"),
		Index("ix_og_incident_occurred", "occurred_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	facility_id = Column(
		UUID(as_uuid=False),
		ForeignKey("og_facility.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	incident_type = Column(
		String(20),
		nullable=False,
		comment="SPILL|FIRE|EXPLOSION|INJURY|NEAR_MISS|ENVIRONMENTAL",
	)
	severity = Column(
		String(10),
		nullable=False,
		comment="TIER1|TIER2|TIER3 (IOGP classification)",
	)
	reported_at = Column(DateTime(timezone=True), nullable=False)
	occurred_at = Column(DateTime(timezone=True), nullable=False)
	description = Column(Text, nullable=False)
	location_detail = Column(String(255), nullable=True)
	casualties = Column(Integer, nullable=False, default=0)
	injuries = Column(Integer, nullable=False, default=0)
	root_cause = Column(Text, nullable=True)
	corrective_actions = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{action, owner, due_date, closed_at}]",
	)
	reported_to_regulator = Column(Boolean, nullable=False, default=False)
	status = Column(
		String(20),
		nullable=False,
		default="OPEN",
		comment="OPEN|UNDER_INVESTIGATION|CLOSED",
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

	facility: Facility = relationship(
		"Facility",
		back_populates="incident_reports",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<IncidentReport {self.incident_type!r} sev={self.severity!r} "
			f"facility={self.facility_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Facility",
	"Asset",
	"MaintenanceWork",
	"ProductionRecord",
	"HAZOPReview",
	"IncidentReport",
]
