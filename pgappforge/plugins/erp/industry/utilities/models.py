"""
pgappforge/plugins/erp/industry/utilities/models.py

Utilities / Smart Grid models — IEC CIM + Green Button AMI data.

Entities:
  GridAsset            — physical grid asset (substation/transformer/line/switch/meter/generator)
  GridTopology         — directed edge in the grid network graph
  EnergyMeter          — AMI/smart meter linked to a customer and grid asset
  IntervalData         — immutable AMI interval energy readings (Green Button ESPI)
  OutageEvent          — outage lifecycle with SAIDI/SAIFI tracking
  DemandResponseEvent  — demand response program event

Design:
  - All PKs: UUID v4
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - tenant_id on all entities
  - GeoAlchemy2 GEOMETRY(Point,4326) for GridAsset.location (fallback: Text WKT)
  - JSONB for service_address, configuration
  - UUID[] ARRAY for affected_assets and crew_ids
  - IntervalData: ImmutableRecordMixin
  - All monetary amounts: N/A for this domain
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
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
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# GeoAlchemy2 graceful fallback
# ---------------------------------------------------------------------------

try:
	from geoalchemy2 import Geometry as _Geometry
	_GEO_AVAILABLE = True
except ImportError:
	_GEO_AVAILABLE = False
	log.debug("geoalchemy2 not installed — GridAsset.location stored as Text (WKT)")


def _geo_point_column():
	if _GEO_AVAILABLE:
		from geoalchemy2 import Geometry
		return Column(Geometry("POINT", srid=4326), nullable=True)
	return Column(Text, nullable=True, comment="WKT POINT fallback (install geoalchemy2)")


# ---------------------------------------------------------------------------
# GridAsset
# ---------------------------------------------------------------------------

class GridAsset(AuditMixin, Model):
	"""Physical grid asset — any component in the distribution/transmission network.

	Aligns with IEC CIM PowerSystemResource.  asset_id is a stable external
	identifier (e.g. CIM MRID or GIS feature ID).
	voltage_kv and capacity_mva are nullable for assets where they don't apply
	(e.g. switches).
	age_years is maintained by an external process (annual update).
	"""

	__allow_unmapped__ = True
	__tablename__ = "util_grid_asset"
	__table_args__ = (
		UniqueConstraint("tenant_id", "asset_id", name="uq_util_grid_asset_tenant_id"),
		Index("ix_util_grid_asset_tenant", "tenant_id"),
		Index("ix_util_grid_asset_type", "asset_type"),
		Index("ix_util_grid_asset_status", "status"),
		Index("ix_util_grid_asset_owner", "owner_id"),
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
		String(200),
		nullable=False,
		comment="Stable external identifier (CIM MRID or GIS feature ID)",
	)
	asset_type = Column(
		String(20),
		nullable=False,
		comment="SUBSTATION | TRANSFORMER | LINE | SWITCH | METER | GENERATOR",
	)
	name = Column(String(500), nullable=False)
	location = _geo_point_column()
	voltage_kv = Column(Numeric(8, 2), nullable=True, comment="Operating voltage kV")
	capacity_mva = Column(Numeric(10, 3), nullable=True, comment="Rated capacity MVA")
	status = Column(
		String(20),
		nullable=False,
		default="IN_SERVICE",
		comment="IN_SERVICE | OUT_OF_SERVICE | MAINTENANCE",
	)
	owner_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		comment="Owning utility / organisation (erp_party)",
	)
	installation_date = Column(Date, nullable=True)
	age_years = Column(Integer, nullable=True, comment="Computed age in years")

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

	topology_from: list[GridTopology] = relationship(
		"GridTopology",
		foreign_keys="GridTopology.from_asset_id",
		back_populates="from_asset",
		lazy="select",
	)
	topology_to: list[GridTopology] = relationship(
		"GridTopology",
		foreign_keys="GridTopology.to_asset_id",
		back_populates="to_asset",
		lazy="select",
	)
	meters: list[EnergyMeter] = relationship(
		"EnergyMeter",
		back_populates="grid_asset",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<GridAsset {self.asset_id!r} type={self.asset_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# GridTopology
# ---------------------------------------------------------------------------

class GridTopology(AuditMixin, Model):
	"""Directed edge in the grid network graph.

	Represents a physical connection between two GridAssets (line, transformer
	link, or switch).  Used for network tracing and outage impact analysis.

	impedance_ohm: total series impedance for load-flow calculations (nullable
	for switches where impedance is zero / negligible).
	is_normally_open: True for tie switches that are open under normal conditions.
	"""

	__allow_unmapped__ = True
	__tablename__ = "util_grid_topology"
	__table_args__ = (
		UniqueConstraint(
			"from_asset_id", "to_asset_id", "connection_type",
			name="uq_util_topo_from_to_type",
		),
		Index("ix_util_topo_from", "from_asset_id"),
		Index("ix_util_topo_to", "to_asset_id"),
		Index("ix_util_topo_tenant", "tenant_id"),
		Index("ix_util_topo_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	from_asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("util_grid_asset.id", ondelete="CASCADE"),
		nullable=False,
	)
	to_asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("util_grid_asset.id", ondelete="CASCADE"),
		nullable=False,
	)
	connection_type = Column(
		String(20),
		nullable=False,
		comment="LINE | TRANSFORMER | SWITCH",
	)
	impedance_ohm = Column(Numeric(12, 6), nullable=True, comment="Total series impedance ohms")
	is_normally_open = Column(Boolean, nullable=False, default=False)
	is_active = Column(Boolean, nullable=False, default=True)

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

	from_asset: GridAsset = relationship(
		"GridAsset",
		foreign_keys=[from_asset_id],
		back_populates="topology_from",
		lazy="select",
	)
	to_asset: GridAsset = relationship(
		"GridAsset",
		foreign_keys=[to_asset_id],
		back_populates="topology_to",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<GridTopology {self.from_asset_id!r} -[{self.connection_type}]-> "
			f"{self.to_asset_id!r}>"
		)


# ---------------------------------------------------------------------------
# EnergyMeter
# ---------------------------------------------------------------------------

class EnergyMeter(AuditMixin, Model):
	"""AMI / smart meter registered to a customer at a service address.

	meter_id: utility billing system meter number (stable external ID).
	service_address JSONB: structured address using ADDRESS_SCHEMA.
	tariff_code: rate schedule code used for billing.
	time_of_use_enabled: True if the meter reports TOU intervals.
	"""

	__allow_unmapped__ = True
	__tablename__ = "util_energy_meter"
	__table_args__ = (
		UniqueConstraint("tenant_id", "meter_id", name="uq_util_meter_tenant_id"),
		Index("ix_util_meter_tenant", "tenant_id"),
		Index("ix_util_meter_customer", "customer_id"),
		Index("ix_util_meter_asset", "grid_asset_id"),
		Index("ix_util_meter_type", "meter_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	meter_id = Column(
		String(200),
		nullable=False,
		comment="Utility billing system meter number",
	)
	customer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
	)
	service_address: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Structured service address (ADDRESS_SCHEMA)",
	)
	meter_type = Column(
		String(10),
		nullable=False,
		comment="ANALOG | SMART | AMI",
	)
	grid_asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("util_grid_asset.id", ondelete="SET NULL"),
		nullable=True,
		comment="Grid asset (transformer/feeder) serving this meter",
	)
	tariff_code = Column(String(50), nullable=False, comment="Rate schedule / tariff code")
	time_of_use_enabled = Column(Boolean, nullable=False, default=False)
	installed_date = Column(Date, nullable=True)
	last_read_date = Column(Date, nullable=True)

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

	grid_asset: GridAsset | None = relationship(
		"GridAsset",
		back_populates="meters",
		lazy="select",
	)
	interval_data: list[IntervalData] = relationship(
		"IntervalData",
		back_populates="meter",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<EnergyMeter {self.meter_id!r} type={self.meter_type!r}>"


# ---------------------------------------------------------------------------
# IntervalData  (IMMUTABLE — Green Button ESPI interval block)
# ---------------------------------------------------------------------------

class IntervalData(ImmutableRecordMixin, Model):
	"""Immutable AMI interval energy reading — Green Button ESPI IntervalBlock.

	Each row is one interval period for one meter.
	quality_code follows ANSI C12.20 quality codes (0 = good).
	demand_kw and power_factor are nullable for legacy analog meters.

	NEVER UPDATE rows.
	"""

	__allow_unmapped__ = True
	__tablename__ = "util_interval_data"
	__table_args__ = (
		UniqueConstraint(
			"meter_id", "interval_start",
			name="uq_util_interval_meter_start",
		),
		Index("ix_util_interval_meter", "meter_id"),
		Index("ix_util_interval_start", "interval_start", postgresql_using="brin"),
		Index("ix_util_interval_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	meter_id = Column(
		UUID(as_uuid=False),
		ForeignKey("util_energy_meter.id", ondelete="RESTRICT"),
		nullable=False,
	)
	interval_start = Column(DateTime(timezone=True), nullable=False)
	interval_end = Column(DateTime(timezone=True), nullable=False)
	consumption_kwh = Column(Numeric(10, 4), nullable=False, comment="Energy consumed kWh")
	demand_kw = Column(Numeric(10, 4), nullable=True, comment="Peak demand kW in interval")
	power_factor = Column(Numeric(4, 3), nullable=True, comment="Power factor 0.000–1.000")
	quality_code = Column(
		Integer,
		nullable=False,
		default=0,
		comment="ANSI C12.20 quality code (0=good)",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	meter: EnergyMeter = relationship(
		"EnergyMeter",
		back_populates="interval_data",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<IntervalData meter={self.meter_id!r}"
			f" start={self.interval_start!r} kwh={self.consumption_kwh}>"
		)


# Register immutability guard after class definition
IntervalData._register_immutability()


# ---------------------------------------------------------------------------
# OutageEvent
# ---------------------------------------------------------------------------

class OutageEvent(AuditMixin, Model):
	"""Outage lifecycle record with SAIDI/SAIFI reliability indices.

	affected_assets: UUID[] of GridAsset.id values impacted by this outage.
	crew_ids: UUID[] of Party.id values (field crews) assigned to restoration.
	saidi_minutes: System Average Interruption Duration Index contribution.
	saifi_occurrences: System Average Interruption Frequency Index contribution.
	Restoration is recorded by setting restored_at and status='RESTORED'.
	"""

	__allow_unmapped__ = True
	__tablename__ = "util_outage_event"
	__table_args__ = (
		UniqueConstraint("tenant_id", "outage_id", name="uq_util_outage_tenant_id"),
		Index("ix_util_outage_tenant", "tenant_id"),
		Index("ix_util_outage_type", "outage_type"),
		Index("ix_util_outage_status", "status"),
		Index("ix_util_outage_reported", "reported_at"),
		Index("ix_util_outage_started", "started_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	outage_id = Column(
		String(200),
		nullable=False,
		comment="Stable OMS outage ticket number",
	)
	outage_type = Column(
		String(15),
		nullable=False,
		comment="PLANNED | UNPLANNED | EMERGENCY",
	)
	cause = Column(String(200), nullable=False)
	affected_assets: list[str] = Column(
		ARRAY(UUID(as_uuid=False)),
		nullable=False,
		server_default="{}",
		default=list,
		comment="UUID[] of GridAsset.id values affected",
	)
	affected_customers = Column(Integer, nullable=False, default=0)
	reported_at = Column(DateTime(timezone=True), nullable=False)
	started_at = Column(DateTime(timezone=True), nullable=False)
	restored_at = Column(DateTime(timezone=True), nullable=True)
	saidi_minutes = Column(
		Numeric(10, 2),
		nullable=False,
		default=0,
		comment="SAIDI contribution in customer-minutes",
	)
	saifi_occurrences = Column(
		Numeric(8, 4),
		nullable=False,
		default=0,
		comment="SAIFI contribution in customer-interruptions",
	)
	crew_ids: list[str] = Column(
		ARRAY(UUID(as_uuid=False)),
		nullable=False,
		server_default="{}",
		default=list,
		comment="UUID[] of Party.id values (field crews)",
	)
	status = Column(
		String(20),
		nullable=False,
		default="REPORTED",
		comment="REPORTED | DISPATCHED | IN_RESTORATION | RESTORED",
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
		return (
			f"<OutageEvent {self.outage_id!r} type={self.outage_type!r}"
			f" status={self.status!r} customers={self.affected_customers}>"
		)


# ---------------------------------------------------------------------------
# DemandResponseEvent
# ---------------------------------------------------------------------------

class DemandResponseEvent(AuditMixin, Model):
	"""Demand response program event — load curtailment coordination.

	Tracks target vs achieved reduction and customer participation.
	achieved_reduction_kw is updated as field telemetry is received.
	"""

	__allow_unmapped__ = True
	__tablename__ = "util_demand_response_event"
	__table_args__ = (
		Index("ix_util_dr_tenant", "tenant_id"),
		Index("ix_util_dr_status", "status"),
		Index("ix_util_dr_start", "event_start"),
		Index("ix_util_dr_program", "program_name"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	program_name = Column(String(100), nullable=False)
	event_start = Column(DateTime(timezone=True), nullable=False)
	event_end = Column(DateTime(timezone=True), nullable=False)
	target_reduction_kw = Column(
		Numeric(10, 2),
		nullable=False,
		comment="Target load reduction kW",
	)
	enrolled_customers = Column(Integer, nullable=False, default=0)
	achieved_reduction_kw = Column(
		Numeric(10, 2),
		nullable=False,
		default=0,
		comment="Measured achieved reduction kW",
	)
	status = Column(
		String(15),
		nullable=False,
		default="PLANNED",
		comment="PLANNED | ACTIVE | COMPLETED",
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
		return (
			f"<DemandResponseEvent {self.program_name!r}"
			f" target={self.target_reduction_kw}kW status={self.status!r}>"
		)


__all__ = [
	"GridAsset",
	"GridTopology",
	"EnergyMeter",
	"IntervalData",
	"OutageEvent",
	"DemandResponseEvent",
]
