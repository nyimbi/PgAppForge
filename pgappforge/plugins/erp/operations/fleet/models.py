"""
pgappforge/plugins/erp/operations/fleet/models.py

SQLAlchemy 2.x models for the Fleet Management plugin.

Design invariants:
  - ALL PKs: UUID(as_uuid=False) — gen_random_uuid() server default + Python default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - Monetary amounts: BigInteger cents (never Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - Table prefix: fleet_
  - Composite indexes for tenant + status hot paths
  - FKs within the plugin are hard constraints; cross-plugin refs are advisory UUIDs

Enum constants are plain string sets — SQLAlchemy String columns + CheckConstraints
keep the DB portable and avoid ALTER TABLE on enum changes.

KRA compliance notes:
  - VehicleDocument.doc_type includes LOGBOOK and ROAD_TAX (Kenya Revenue Authority)
  - Driver.psvb_expiry tracks PSV badge renewal (Transport Licensing Board)
  - Driver.medical_expiry tracks NTSA medical certificate
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	CheckConstraint,
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enum constant sets (used in CheckConstraints and service validation)
# ---------------------------------------------------------------------------

FUEL_TYPES = {"PETROL", "DIESEL", "ELECTRIC", "HYBRID", "LPG"}
BODY_TYPES = {"SALOON", "SUV", "PICKUP", "LORRY", "BUS", "VAN", "MOTORCYCLE"}
VEHICLE_STATUSES = {"ACTIVE", "IN_MAINTENANCE", "OUT_OF_SERVICE", "DISPOSED"}
DOC_TYPES = {"LOGBOOK", "INSURANCE", "ROAD_TAX", "INSPECTION", "DRIVING_CERT", "OTHER"}
DRIVER_STATUSES = {"ACTIVE", "SUSPENDED", "BLACKLISTED"}
TRIP_TYPES = {"OFFICIAL", "PERSONAL", "DELIVERY", "PASSENGER"}
PAYMENT_METHODS = {"CASH", "CARD", "FLEET_CARD", "ACCOUNT"}
SERVICE_TYPES = {"ROUTINE", "MAJOR", "REPAIR", "TYRES", "BATTERY", "ELECTRICAL", "BODY"}
INCIDENT_TYPES = {"ACCIDENT", "BREAKDOWN", "TRAFFIC_VIOLATION", "THEFT", "VANDALISM", "OTHER"}
INCIDENT_STATUSES = {"REPORTED", "UNDER_INVESTIGATION", "CLOSED"}
SCHEDULE_TYPES = {
	"ROUTINE_SERVICE", "OIL_CHANGE", "TYRE_ROTATION", "MAJOR_SERVICE", "INSPECTION",
}


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------

class Vehicle(AuditMixin, Model):
	"""Central vehicle register.

	reg_number is the official registration plate (e.g. KCA 123A).
	chassis_number / engine_number stored for logbook cross-verification.
	current_odometer_km is updated on every closed TripLog and FuelRecord.
	average_fuel_consumption_per_100km is a rolling average recomputed on
	each FuelRecord.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fleet_vehicle"
	__table_args__ = (
		UniqueConstraint("tenant_id", "reg_number", name="uq_fleet_veh_tenant_reg"),
		UniqueConstraint("chassis_number", name="uq_fleet_veh_chassis"),
		CheckConstraint(
			"fuel_type IN ('PETROL','DIESEL','ELECTRIC','HYBRID','LPG')",
			name="ck_fleet_veh_fuel_type",
		),
		CheckConstraint(
			"body_type IN ('SALOON','SUV','PICKUP','LORRY','BUS','VAN','MOTORCYCLE')",
			name="ck_fleet_veh_body_type",
		),
		CheckConstraint(
			"status IN ('ACTIVE','IN_MAINTENANCE','OUT_OF_SERVICE','DISPOSED')",
			name="ck_fleet_veh_status",
		),
		Index("ix_fleet_veh_tenant", "tenant_id"),
		Index("ix_fleet_veh_tenant_status", "tenant_id", "status"),
		Index("ix_fleet_veh_assigned_driver", "assigned_driver_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	reg_number = Column(String(20), nullable=False, comment="Official registration plate")
	make = Column(String(100), nullable=False)
	model = Column(String(100), nullable=False)
	year_of_manufacture = Column(Integer, nullable=False)
	chassis_number = Column(String(30), nullable=True, unique=True)
	engine_number = Column(String(30), nullable=True)
	fuel_type = Column(String(10), nullable=False, default="PETROL")
	body_type = Column(String(12), nullable=False, default="SALOON")
	colour = Column(String(50), nullable=False, default="")
	seating_capacity = Column(Integer, nullable=False, default=5)
	payload_kg = Column(Numeric(8, 2), nullable=True, comment="Payload capacity in kg (commercial vehicles)")
	acquisition_date = Column(Date, nullable=False)
	acquisition_cost_cents = Column(BigInteger, nullable=False, default=0, comment="Purchase price in cents")
	current_odometer_km = Column(Numeric(10, 2), nullable=False, default=0)
	status = Column(String(20), nullable=False, default="ACTIVE")
	assigned_driver_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="Advisory FK to fleet_driver.id")
	department_id = Column(UUID(as_uuid=False), nullable=True, comment="Advisory FK to hr department")
	gps_device_id = Column(String(50), nullable=True)
	average_fuel_consumption_per_100km = Column(
		Numeric(6, 2), nullable=True, comment="Rolling average litres/100km"
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

	documents: list[VehicleDocument] = relationship(
		"VehicleDocument", back_populates="vehicle", lazy="select", cascade="all, delete-orphan"
	)
	trips: list[TripLog] = relationship(
		"TripLog", back_populates="vehicle", lazy="select"
	)
	fuel_records: list[FuelRecord] = relationship(
		"FuelRecord", back_populates="vehicle", lazy="select"
	)
	services: list[VehicleService] = relationship(
		"VehicleService", back_populates="vehicle", lazy="select"
	)
	incidents: list[FleetIncident] = relationship(
		"FleetIncident", back_populates="vehicle", lazy="select"
	)
	maintenance_schedules: list[MaintenanceSchedule] = relationship(
		"MaintenanceSchedule", back_populates="vehicle", lazy="select", cascade="all, delete-orphan"
	)

	def __repr__(self) -> str:
		return f"<Vehicle {self.reg_number} {self.make} {self.model} [{self.status}]>"


# ---------------------------------------------------------------------------
# VehicleDocument
# ---------------------------------------------------------------------------

class VehicleDocument(AuditMixin, Model):
	"""Compliance documents attached to a vehicle.

	alert_days_before drives get_documents_expiring() — default 30 days.
	Covers KRA road tax, NTSA inspection sticker, insurance certificate, logbook.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fleet_vehicle_document"
	__table_args__ = (
		CheckConstraint(
			"doc_type IN ('LOGBOOK','INSURANCE','ROAD_TAX','INSPECTION','DRIVING_CERT','OTHER')",
			name="ck_fleet_doc_type",
		),
		Index("ix_fleet_doc_vehicle", "vehicle_id"),
		Index("ix_fleet_doc_expiry", "expiry_date"),
		Index("ix_fleet_doc_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	vehicle_id = Column(UUID(as_uuid=False), ForeignKey("fleet_vehicle.id"), nullable=False)

	doc_type = Column(String(20), nullable=False)
	document_number = Column(String(60), nullable=False)
	issuing_authority = Column(String(100), nullable=False)
	issue_date = Column(Date, nullable=False)
	expiry_date = Column(Date, nullable=True)
	cost_cents = Column(BigInteger, nullable=True)
	alert_days_before = Column(Integer, nullable=False, default=30)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	vehicle: Vehicle = relationship("Vehicle", back_populates="documents", lazy="select")

	def __repr__(self) -> str:
		return f"<VehicleDocument {self.doc_type} {self.document_number} exp={self.expiry_date}>"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class Driver(AuditMixin, Model):
	"""Fleet driver record — links an HR employee to fleet-specific attributes.

	employee_id is an advisory UUID cross-reference to the HR plugin.
	demerit_points accumulates from FleetIncident.  At >= 12 the driver is
	auto-suspended by FleetService.report_incident().
	psvb_expiry / medical_expiry track Kenya-specific compliance certificates.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fleet_driver"
	__table_args__ = (
		UniqueConstraint("tenant_id", "license_number", name="uq_fleet_drv_tenant_license"),
		UniqueConstraint("tenant_id", "employee_id", name="uq_fleet_drv_tenant_employee"),
		CheckConstraint(
			"status IN ('ACTIVE','SUSPENDED','BLACKLISTED')",
			name="ck_fleet_drv_status",
		),
		Index("ix_fleet_drv_tenant", "tenant_id"),
		Index("ix_fleet_drv_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(UUID(as_uuid=False), nullable=False, comment="Advisory FK to HR employee")
	license_number = Column(String(20), nullable=False)
	license_class = Column(String(10), nullable=False, comment="e.g. BCE, C, D — Kenya NTSA classes")
	license_expiry = Column(Date, nullable=False)
	psvb_expiry = Column(Date, nullable=True, comment="PSV badge expiry (TLB Kenya)")
	medical_expiry = Column(Date, nullable=True, comment="NTSA medical certificate expiry")
	status = Column(String(15), nullable=False, default="ACTIVE")
	demerit_points = Column(Integer, nullable=False, default=0)
	total_trips = Column(Integer, nullable=False, default=0)
	total_km = Column(Numeric(12, 2), nullable=False, default=0)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	trips: list[TripLog] = relationship("TripLog", back_populates="driver", lazy="select")
	fuel_records: list[FuelRecord] = relationship("FuelRecord", back_populates="driver", lazy="select")
	incidents: list[FleetIncident] = relationship("FleetIncident", back_populates="driver", lazy="select")

	def __repr__(self) -> str:
		return f"<Driver {self.license_number} [{self.status}] demerits={self.demerit_points}>"


# ---------------------------------------------------------------------------
# TripLog
# ---------------------------------------------------------------------------

class TripLog(AuditMixin, Model):
	"""Immutable-intent trip record — one row per vehicle movement.

	end_odometer / end_datetime / distance_km are NULL while the trip is open.
	FleetService.log_trip() closes the trip and updates vehicle + driver totals.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fleet_trip_log"
	__table_args__ = (
		CheckConstraint(
			"trip_type IN ('OFFICIAL','PERSONAL','DELIVERY','PASSENGER')",
			name="ck_fleet_trip_type",
		),
		Index("ix_fleet_trip_vehicle", "vehicle_id"),
		Index("ix_fleet_trip_driver", "driver_id"),
		Index("ix_fleet_trip_tenant_start", "tenant_id", "start_datetime"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	vehicle_id = Column(UUID(as_uuid=False), ForeignKey("fleet_vehicle.id"), nullable=False)
	driver_id = Column(UUID(as_uuid=False), ForeignKey("fleet_driver.id"), nullable=False)

	trip_purpose = Column(Text, nullable=False)
	trip_type = Column(String(15), nullable=False, default="OFFICIAL")
	start_datetime = Column(DateTime(timezone=True), nullable=False)
	end_datetime = Column(DateTime(timezone=True), nullable=True)
	start_odometer = Column(Numeric(10, 2), nullable=False)
	end_odometer = Column(Numeric(10, 2), nullable=True)
	distance_km = Column(Numeric(8, 2), nullable=True, comment="Computed on close: end_odometer - start_odometer")
	start_location = Column(String(200), nullable=False)
	end_location = Column(String(200), nullable=False, default="")
	authorized_by = Column(UUID(as_uuid=False), nullable=True, comment="Advisory FK to HR employee who authorised")
	fuel_used_litres = Column(Numeric(8, 2), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	vehicle: Vehicle = relationship("Vehicle", back_populates="trips", lazy="select")
	driver: Driver = relationship("Driver", back_populates="trips", lazy="select")

	def __repr__(self) -> str:
		return f"<TripLog vehicle={self.vehicle_id} driver={self.driver_id} start={self.start_datetime}>"


# ---------------------------------------------------------------------------
# FuelRecord
# ---------------------------------------------------------------------------

class FuelRecord(AuditMixin, Model):
	"""One fuelling transaction.

	total_cost_cents should equal litres * cost_per_litre_cents (validated in service).
	odometer_km at time of fuelling enables consumption tracking per fill-up.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fleet_fuel_record"
	__table_args__ = (
		CheckConstraint(
			"payment_method IN ('CASH','CARD','FLEET_CARD','ACCOUNT')",
			name="ck_fleet_fuel_payment",
		),
		Index("ix_fleet_fuel_vehicle", "vehicle_id"),
		Index("ix_fleet_fuel_tenant_date", "tenant_id", "fuelling_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	vehicle_id = Column(UUID(as_uuid=False), ForeignKey("fleet_vehicle.id"), nullable=False)
	driver_id = Column(UUID(as_uuid=False), ForeignKey("fleet_driver.id"), nullable=False)

	fuelling_date = Column(Date, nullable=False)
	fuel_type = Column(String(10), nullable=False)
	litres = Column(Numeric(8, 2), nullable=False)
	cost_per_litre_cents = Column(BigInteger, nullable=False)
	total_cost_cents = Column(BigInteger, nullable=False)
	odometer_km = Column(Numeric(10, 2), nullable=False)
	station_name = Column(String(100), nullable=True)
	receipt_number = Column(String(50), nullable=True)
	payment_method = Column(String(15), nullable=False, default="CASH")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	vehicle: Vehicle = relationship("Vehicle", back_populates="fuel_records", lazy="select")
	driver: Driver = relationship("Driver", back_populates="fuel_records", lazy="select")

	def __repr__(self) -> str:
		return f"<FuelRecord {self.fuelling_date} {self.litres}L vehicle={self.vehicle_id}>"


# ---------------------------------------------------------------------------
# VehicleService
# ---------------------------------------------------------------------------

class VehicleService(AuditMixin, Model):
	"""One garage/workshop service event.

	total_cost_cents = parts_cost_cents + labour_cost_cents (enforced in service layer).
	next_service_km / next_service_date feed MaintenanceSchedule updates.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fleet_vehicle_service"
	__table_args__ = (
		CheckConstraint(
			"service_type IN ('ROUTINE','MAJOR','REPAIR','TYRES','BATTERY','ELECTRICAL','BODY')",
			name="ck_fleet_svc_type",
		),
		Index("ix_fleet_svc_vehicle", "vehicle_id"),
		Index("ix_fleet_svc_tenant_date", "tenant_id", "service_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	vehicle_id = Column(UUID(as_uuid=False), ForeignKey("fleet_vehicle.id"), nullable=False)

	service_type = Column(String(15), nullable=False)
	service_date = Column(Date, nullable=False)
	odometer_km = Column(Numeric(10, 2), nullable=False)
	description = Column(Text, nullable=False)
	garage_name = Column(String(100), nullable=False)
	parts_cost_cents = Column(BigInteger, nullable=False, default=0)
	labour_cost_cents = Column(BigInteger, nullable=False, default=0)
	total_cost_cents = Column(BigInteger, nullable=False, default=0)
	invoice_number = Column(String(50), nullable=True)
	next_service_km = Column(Numeric(10, 2), nullable=True)
	next_service_date = Column(Date, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	vehicle: Vehicle = relationship("Vehicle", back_populates="services", lazy="select")

	def __repr__(self) -> str:
		return f"<VehicleService {self.service_type} {self.service_date} vehicle={self.vehicle_id}>"


# ---------------------------------------------------------------------------
# FleetIncident
# ---------------------------------------------------------------------------

class FleetIncident(AuditMixin, Model):
	"""Accident, breakdown, traffic violation, theft, or vandalism record.

	third_party_involved triggers insurance liaison workflow.
	ACCIDENT incidents apply demerit_points to the driver via service layer.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fleet_incident"
	__table_args__ = (
		CheckConstraint(
			"incident_type IN ('ACCIDENT','BREAKDOWN','TRAFFIC_VIOLATION','THEFT','VANDALISM','OTHER')",
			name="ck_fleet_inc_type",
		),
		CheckConstraint(
			"status IN ('REPORTED','UNDER_INVESTIGATION','CLOSED')",
			name="ck_fleet_inc_status",
		),
		Index("ix_fleet_inc_vehicle", "vehicle_id"),
		Index("ix_fleet_inc_driver", "driver_id"),
		Index("ix_fleet_inc_tenant_date", "tenant_id", "incident_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	vehicle_id = Column(UUID(as_uuid=False), ForeignKey("fleet_vehicle.id"), nullable=False)
	driver_id = Column(UUID(as_uuid=False), ForeignKey("fleet_driver.id"), nullable=True)

	incident_date = Column(Date, nullable=False)
	incident_type = Column(String(25), nullable=False)
	description = Column(Text, nullable=False)
	location = Column(String(200), nullable=False)
	police_report_number = Column(String(50), nullable=True)
	insurance_claim_number = Column(String(50), nullable=True)
	third_party_involved = Column(Boolean, nullable=False, default=False)
	estimated_damage_cents = Column(BigInteger, nullable=True)
	status = Column(String(25), nullable=False, default="REPORTED")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	vehicle: Vehicle = relationship("Vehicle", back_populates="incidents", lazy="select")
	driver: Driver | None = relationship("Driver", back_populates="incidents", lazy="select")

	def __repr__(self) -> str:
		return f"<FleetIncident {self.incident_type} {self.incident_date} [{self.status}]>"


# ---------------------------------------------------------------------------
# MaintenanceSchedule
# ---------------------------------------------------------------------------

class MaintenanceSchedule(AuditMixin, Model):
	"""Per-vehicle maintenance trigger definition.

	A schedule can be km-triggered, calendar-triggered, or both.
	maintenance_due_alerts() compares next_due_km vs current_odometer and
	next_due_date vs today to generate alerts.
	Updated by FleetService.record_service() when a matching service is completed.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fleet_maintenance_schedule"
	__table_args__ = (
		CheckConstraint(
			"schedule_type IN ('ROUTINE_SERVICE','OIL_CHANGE','TYRE_ROTATION','MAJOR_SERVICE','INSPECTION')",
			name="ck_fleet_sched_type",
		),
		UniqueConstraint("vehicle_id", "schedule_type", name="uq_fleet_sched_vehicle_type"),
		Index("ix_fleet_sched_vehicle", "vehicle_id"),
		Index("ix_fleet_sched_tenant", "tenant_id"),
		Index("ix_fleet_sched_next_due", "next_due_date", "next_due_km"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	vehicle_id = Column(UUID(as_uuid=False), ForeignKey("fleet_vehicle.id"), nullable=False)

	schedule_type = Column(String(20), nullable=False)
	trigger_km = Column(Numeric(10, 2), nullable=True, comment="Service interval in km (e.g. 5000 for every 5000km)")
	trigger_days = Column(Integer, nullable=True, comment="Service interval in days (e.g. 90 for every 3 months)")
	last_done_km = Column(Numeric(10, 2), nullable=True)
	last_done_date = Column(Date, nullable=True)
	next_due_km = Column(Numeric(10, 2), nullable=True)
	next_due_date = Column(Date, nullable=True)
	estimated_cost_cents = Column(BigInteger, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	vehicle: Vehicle = relationship("Vehicle", back_populates="maintenance_schedules", lazy="select")

	def __repr__(self) -> str:
		return f"<MaintenanceSchedule {self.schedule_type} vehicle={self.vehicle_id} next_km={self.next_due_km} next_date={self.next_due_date}>"


__all__ = [
	"Vehicle",
	"VehicleDocument",
	"Driver",
	"TripLog",
	"FuelRecord",
	"VehicleService",
	"FleetIncident",
	"MaintenanceSchedule",
	# enum sets (useful for validation in services / serializers)
	"FUEL_TYPES",
	"BODY_TYPES",
	"VEHICLE_STATUSES",
	"DOC_TYPES",
	"DRIVER_STATUSES",
	"TRIP_TYPES",
	"PAYMENT_METHODS",
	"SERVICE_TYPES",
	"INCIDENT_TYPES",
	"INCIDENT_STATUSES",
	"SCHEDULE_TYPES",
]
