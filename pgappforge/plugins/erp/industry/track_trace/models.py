"""
pgappforge/plugins/erp/industry/track_trace/models.py

SQLAlchemy models for the Track & Trace plugin (GS1 EPCIS 2.0).

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid()
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL models: tenant_id UUID NOT NULL
  - EPCISEvent is IMMUTABLE — append-only supply chain event ledger
  - ColdChainRecord: high-volume IoT append-only sensor data
  - PostGIS GEOMETRY(Point,4326) used for ColdChainRecord.location

Table prefix: tt_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# TraceableItem
# ---------------------------------------------------------------------------

class TraceableItem(AuditMixin, Model):
	"""Serialized traceable item identified by an EPC URI.

	epc is the canonical GS1 EPC URI (e.g. urn:epc:id:sgtin:0614141.107346.2017).
	item_type maps to GS1 EPC scheme: SGTIN/SSCC/SGLN/GRAI/GIAI.
	current_location JSONB: {gln, name, address, geo_lat, geo_lng}.
	is_recalled is set by RecallEvent processing.

	product_id FK references inventory.Product (nullable — not all items
	are in the local product catalogue).
	current_owner_id FK references foundation.Party.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tt_traceable_item"
	__table_args__ = (
		Index("ix_tt_item_tenant", "tenant_id"),
		Index("ix_tt_item_type", "item_type"),
		Index("ix_tt_item_gtin", "gtin"),
		Index("ix_tt_item_lot", "lot_number"),
		Index("ix_tt_item_owner", "current_owner_id"),
		Index("ix_tt_item_recalled", "is_recalled"),
		UniqueConstraint("epc", name="uq_tt_item_epc"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	epc = Column(String(200), nullable=False, unique=True, comment="GS1 EPC URI (urn:epc:id:...)")
	item_type = Column(
		String(10),
		nullable=False,
		comment="SGTIN|SSCC|SGLN|GRAI|GIAI",
	)

	gtin = Column(String(14), nullable=True, index=True, comment="GTIN-14")
	serial_number = Column(String(50), nullable=True)
	lot_number = Column(String(50), nullable=True, index=True)
	expiry_date = Column(Date, nullable=True)

	product_id = Column(
		UUID(as_uuid=False), nullable=True,
		comment="FK to inventory.Product (nullable)",
	)
	current_owner_id = Column(
		UUID(as_uuid=False), nullable=False, index=True,
		comment="FK to foundation.Party (current custodian)",
	)

	current_location = Column(
		JSONB, nullable=False, default=dict,
		comment="{gln, name, address, geo_lat, geo_lng}",
	)

	is_recalled = Column(Boolean, nullable=False, default=False, server_default="false")

	def __init__(self, **kwargs):
		kwargs.setdefault("current_location", {})
		kwargs.setdefault("is_recalled", False)
		super().__init__(**kwargs)

	created_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return f"<TraceableItem epc={self.epc!r} type={self.item_type!r} recalled={self.is_recalled}>"


# ---------------------------------------------------------------------------
# EPCISEvent  (IMMUTABLE)
# ---------------------------------------------------------------------------

class EPCISEvent(ImmutableRecordMixin, AuditMixin, Model):
	"""GS1 EPCIS 2.0 supply chain event — append-only ledger.

	Captures the five W's: What (epc_list), Where (read_point/biz_location),
	When (event_time), Why (biz_step/disposition), How (sensor_element_list).

	IMMUTABLE: rows are never updated.  Corrections use a new event with
	action=DELETE followed by action=ADD (EPCIS 2.0 correction pattern).

	event_id: globally unique EPCIS eventID (assigned by capturing application).
	epc_list: JSONB array of EPC URI strings involved in this event.
	quantity_list: [{epcClass, quantity, uom}] for class-level items.
	biz_transaction_list: [{type, bizTransaction}] references.
	source_list / destination_list: [{type, source/destination}] party refs.
	sensor_element_list: [{sensorMetadata, sensorReport[]}] IoT sensor data.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tt_epcis_event"
	__table_args__ = (
		Index("ix_tt_epcis_tenant", "tenant_id"),
		Index("ix_tt_epcis_event_type", "event_type"),
		Index("ix_tt_epcis_action", "action"),
		Index("ix_tt_epcis_event_time", "event_time"),
		Index("ix_tt_epcis_biz_step", "biz_step"),
		UniqueConstraint("event_id", name="uq_tt_epcis_event_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	event_id = Column(
		String(200), nullable=False, unique=True,
		comment="EPCIS 2.0 globally unique eventID",
	)
	event_type = Column(
		String(20),
		nullable=False,
		comment="OBJECT|AGGREGATION|TRANSACTION|TRANSFORMATION",
	)
	action = Column(
		String(10),
		nullable=False,
		comment="ADD|OBSERVE|DELETE",
	)

	event_time = Column(DateTime(timezone=True), nullable=False, index=True)
	record_time = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	biz_step = Column(
		String(100), nullable=True,
		comment="GS1 CBV business step URI (e.g. cbv:BizStep-shipping)",
	)
	disposition = Column(
		String(100), nullable=True,
		comment="GS1 CBV disposition URI (e.g. cbv:Disp-in_transit)",
	)

	read_point = Column(
		JSONB, nullable=True,
		comment="{id: GLN/EPC URI} — physical read point",
	)
	biz_location = Column(
		JSONB, nullable=True,
		comment="{id: GLN/EPC URI} — business location",
	)

	epc_list = Column(
		JSONB, nullable=False, default=list,
		comment="Array of EPC URI strings (what was observed)",
	)
	quantity_list = Column(
		JSONB, nullable=False, default=list,
		comment="[{epcClass, quantity, uom}] for class-level tracking",
	)
	biz_transaction_list = Column(
		JSONB, nullable=False, default=list,
		comment="[{type: cbv:BTT-po, bizTransaction: urn:...}]",
	)
	source_list = Column(
		JSONB, nullable=False, default=list,
		comment="[{type, source}] owning/possessing party before event",
	)
	destination_list = Column(
		JSONB, nullable=False, default=list,
		comment="[{type, destination}] owning/possessing party after event",
	)
	sensor_element_list = Column(
		JSONB, nullable=False, default=list,
		comment="[{sensorMetadata, sensorReport[]}] IoT sensor readings",
	)

	def __init__(self, **kwargs):
		kwargs.setdefault("epc_list", [])
		kwargs.setdefault("quantity_list", [])
		kwargs.setdefault("biz_transaction_list", [])
		kwargs.setdefault("source_list", [])
		kwargs.setdefault("destination_list", [])
		kwargs.setdefault("sensor_element_list", [])
		super().__init__(**kwargs)

	# IMMUTABLE — no updated_at
	created_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<EPCISEvent id={self.event_id!r} type={self.event_type!r} "
			f"action={self.action!r} step={self.biz_step!r}>"
		)


# ---------------------------------------------------------------------------
# ColdChainRecord  (append-only IoT sensor data)
# ---------------------------------------------------------------------------

class ColdChainRecord(Model):
	"""Cold chain temperature/humidity sensor record.

	High-volume append-only IoT data.  No AuditMixin (no created_by/updated_by
	overhead on sensor rows).

	location uses PostGIS GEOMETRY(Point,4326) for spatial queries.
	If PostGIS is unavailable, location stores as JSONB {lat, lng}.

	is_excursion=True when temperature_c falls outside the permitted range
	for this item (range stored on product master or configuration).
	excursion_duration_minutes accumulates while excursion is active.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tt_cold_chain_record"
	__table_args__ = (
		Index("ix_tt_cold_item_epc", "item_epc"),
		Index("ix_tt_cold_measured_at", "measured_at"),
		Index("ix_tt_cold_excursion", "is_excursion"),
		Index("ix_tt_cold_device", "device_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)

	item_epc = Column(String(200), nullable=False, index=True, comment="EPC URI of the tracked item")
	measured_at = Column(DateTime(timezone=True), nullable=False, index=True)

	temperature_c = Column(Numeric(5, 2), nullable=False, comment="Temperature in Celsius")
	humidity_pct = Column(Numeric(5, 2), nullable=True, comment="Relative humidity %")

	# PostGIS point — falls back gracefully if extension absent
	# Declared as generic Text; migration adds proper GEOMETRY type
	location = Column(
		JSONB, nullable=True,
		comment="GEOMETRY(Point,4326) stored as JSONB {lat, lng} fallback",
	)

	device_id = Column(String(100), nullable=False, index=True, comment="IoT sensor device identifier")

	is_excursion = Column(Boolean, nullable=False, default=False, server_default="false")
	excursion_duration_minutes = Column(Integer, nullable=False, default=0, server_default="0")

	def __init__(self, **kwargs):
		kwargs.setdefault("is_excursion", False)
		kwargs.setdefault("excursion_duration_minutes", 0)
		super().__init__(**kwargs)

	def __repr__(self) -> str:
		return (
			f"<ColdChainRecord epc={self.item_epc!r} "
			f"t={self.temperature_c}°C excursion={self.is_excursion}>"
		)


# ---------------------------------------------------------------------------
# RecallEvent
# ---------------------------------------------------------------------------

class RecallEvent(AuditMixin, Model):
	"""Product recall event record.

	initiated_by FK references foundation.Party (recall initiating organization).
	affected_lots is a JSONB array of lot number strings.
	affected_date_range JSONB: {from_date, to_date} ISO date strings.
	scope governs geographic reach of the recall.
	items_identified / items_recovered are running counters updated by recall
	processing workflows.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tt_recall_event"
	__table_args__ = (
		Index("ix_tt_recall_tenant", "tenant_id"),
		Index("ix_tt_recall_status", "status"),
		Index("ix_tt_recall_gtin", "affected_gtin"),
		Index("ix_tt_recall_initiated_by", "initiated_by"),
		UniqueConstraint("recall_id", name="uq_tt_recall_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	recall_id = Column(
		String(100), nullable=False, unique=True,
		comment="Unique recall reference number",
	)
	initiated_by = Column(
		UUID(as_uuid=False), nullable=False, index=True,
		comment="FK to foundation.Party (recall initiating organization)",
	)
	initiated_at = Column(DateTime(timezone=True), nullable=False)

	reason = Column(Text, nullable=False)
	affected_gtin = Column(String(14), nullable=False, index=True, comment="GTIN-14 of affected product")
	affected_lots = Column(
		JSONB, nullable=False, default=list,
		comment="Array of lot number strings subject to recall",
	)
	affected_date_range = Column(
		JSONB, nullable=False, default=dict,
		comment="{from_date, to_date} ISO date strings for production date range",
	)

	scope = Column(
		String(10),
		nullable=False,
		default="LOCAL",
		comment="LOCAL|NATIONAL|GLOBAL",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE|COMPLETED|CANCELLED",
	)

	items_identified = Column(Integer, nullable=False, default=0, server_default="0")
	items_recovered = Column(Integer, nullable=False, default=0, server_default="0")

	created_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __init__(self, **kwargs):
		kwargs.setdefault("items_identified", 0)
		kwargs.setdefault("items_recovered", 0)
		kwargs.setdefault("status", "ACTIVE")
		kwargs.setdefault("scope", "NATIONAL")
		kwargs.setdefault("affected_lots", [])
		kwargs.setdefault("affected_date_range", {})
		super().__init__(**kwargs)

	def __repr__(self) -> str:
		return (
			f"<RecallEvent {self.recall_id!r} gtin={self.affected_gtin!r} "
			f"status={self.status!r} scope={self.scope!r}>"
		)


# Register immutability guard
EPCISEvent._register_immutability()


__all__ = [
	"TraceableItem",
	"EPCISEvent",
	"ColdChainRecord",
	"RecallEvent",
]
