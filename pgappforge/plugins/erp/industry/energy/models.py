"""
pgappforge/plugins/erp/industry/energy/models.py

SQLAlchemy models for the Energy plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid()
  - ALL monetary amounts: Integer cents (NEVER float)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - Meter readings and bills are IMMUTABLE once issued
  - NUMERIC(15,4) for consumption values
  - lazy='select' throughout

Table prefix: en_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

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


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Meter
# ---------------------------------------------------------------------------

class Meter(AuditMixin, Model):
	"""Utility meter — gas, electric, or water.

	service_address JSONB: {line1, line2, city, state, postal_code, country}
	tariff_code links to the billing tariff master (app-managed).
	customer_id links to foundation.Party for the account holder.
	"""

	__allow_unmapped__ = True
	__tablename__ = "en_meter"
	__table_args__ = (
		Index("ix_en_meter_tenant", "tenant_id"),
		Index("ix_en_meter_customer", "customer_id"),
		Index("ix_en_meter_tenant_type", "tenant_id", "meter_type"),
		UniqueConstraint("tenant_id", "meter_number", name="uq_en_meter_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	meter_number = Column(String(50), nullable=False, comment="Physical meter serial number; unique per tenant")
	customer_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation Party (account holder)")
	customer_account_number = Column(String(50), nullable=True, comment="Denormalized billing account number")

	meter_type = Column(
		String(10),
		nullable=False,
		comment="GAS|ELECTRIC|WATER|HEAT|STEAM",
	)
	smart_meter = Column(Boolean, nullable=False, default=False, comment="AMI/smart meter with remote reading capability")
	tariff_code = Column(String(50), nullable=True, comment="Billing tariff / rate schedule code")
	service_address = Column(JSONB, nullable=False, default=dict, comment="{line1, line2, city, state, postal_code, country}")
	geo_location = Column(JSONB, nullable=True, comment="{lat, lng}")

	installation_date = Column(Date, nullable=True)
	last_calibration_date = Column(Date, nullable=True)
	multiplier = Column(Numeric(10, 4), nullable=False, default=1, comment="CT/PT ratio or meter multiplier")
	unit = Column(String(20), nullable=False, default="kWh", comment="kWh|m³|CCF|MWh|gal")

	status = Column(String(20), nullable=False, default="ACTIVE", comment="ACTIVE|INACTIVE|FAULTY|REPLACED|REMOVED")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	readings: list[MeterReading] = relationship("MeterReading", back_populates="meter", lazy="select")
	bills: list[EnergyBill] = relationship("EnergyBill", back_populates="meter", lazy="select")

	def __repr__(self) -> str:
		return f"<Meter {self.meter_number!r} type={self.meter_type!r} smart={self.smart_meter}>"


# ---------------------------------------------------------------------------
# MeterReading
# ---------------------------------------------------------------------------

class MeterReading(AuditMixin, Model):
	"""Meter reading record — actual, estimated, or customer-submitted.

	IMMUTABLE once created.  To correct a reading, mark status=SUPERSEDED
	and insert a new corrected reading with read_type=CORRECTED.

	consumption_kwh is the calculated delta from the previous reading,
	normalised to kWh (or m³/CCF for gas/water — same column, label
	differs per meter_type).
	"""

	__allow_unmapped__ = True
	__tablename__ = "en_meter_reading"
	__table_args__ = (
		Index("ix_en_reading_meter", "meter_id"),
		Index("ix_en_reading_tenant", "tenant_id"),
		Index("ix_en_reading_read_date", "read_date"),
		Index("ix_en_reading_meter_date", "meter_id", "read_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	meter_id = Column(UUID(as_uuid=False), ForeignKey("en_meter.id"), nullable=False, index=True)

	read_date = Column(Date, nullable=False)
	read_at = Column(DateTime(timezone=True), nullable=True, comment="Exact timestamp for smart meter reads")
	read_value = Column(Numeric(15, 4), nullable=False, comment="Register/odometer reading in meter units")
	previous_read_value = Column(Numeric(15, 4), nullable=True)
	consumption_kwh = Column(Numeric(10, 2), nullable=True, comment="Delta consumption normalised to kWh/m³")

	read_type = Column(
		String(10),
		nullable=False,
		comment="ACTUAL|ESTIMATE|CUSTOMER|CORRECTED|AMR",
	)
	read_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user (field reader)")
	photo_url = Column(String(500), nullable=True, comment="Photo of meter face for validation")

	status = Column(String(20), nullable=False, default="VALID", comment="VALID|ESTIMATED|SUPERSEDED|DISPUTED|REJECTED")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	meter: Meter = relationship("Meter", back_populates="readings", lazy="select")

	def __repr__(self) -> str:
		return f"<MeterReading meter={self.meter_id!r} date={self.read_date} val={self.read_value} type={self.read_type!r}>"


# ---------------------------------------------------------------------------
# EnergyBill
# ---------------------------------------------------------------------------

class EnergyBill(AuditMixin, Model):
	"""Utility bill for a meter covering a billing period.

	IMMUTABLE once status=ISSUED.  To correct an issued bill, void it
	(status=VOIDED) and issue a credit/debit adjustment bill.

	amount_cents covers the full bill amount — integer cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "en_energy_bill"
	__table_args__ = (
		Index("ix_en_bill_meter", "meter_id"),
		Index("ix_en_bill_tenant", "tenant_id"),
		Index("ix_en_bill_tenant_status", "tenant_id", "status"),
		Index("ix_en_bill_period_start", "billing_period_start"),
		UniqueConstraint("tenant_id", "bill_number", name="uq_en_bill_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	bill_number = Column(String(50), nullable=False, comment="Unique bill reference per tenant")
	meter_id = Column(UUID(as_uuid=False), ForeignKey("en_meter.id"), nullable=False, index=True)
	customer_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation Party (denormalized from meter)")

	billing_period_start = Column(Date, nullable=False)
	billing_period_end = Column(Date, nullable=False)
	issue_date = Column(Date, nullable=True)
	due_date = Column(Date, nullable=True)

	consumption_kwh = Column(Numeric(10, 2), nullable=False, comment="Total consumption for the period")
	opening_read = Column(Numeric(15, 4), nullable=True)
	closing_read = Column(Numeric(15, 4), nullable=True)

	# Amounts — integer cents
	energy_charge_cents = Column(Integer, nullable=False, default=0)
	network_charge_cents = Column(Integer, nullable=False, default=0)
	standing_charge_cents = Column(Integer, nullable=False, default=0)
	tax_cents = Column(Integer, nullable=False, default=0)
	amount_cents = Column(Integer, nullable=False, comment="Total bill amount; immutable once ISSUED")
	paid_cents = Column(Integer, nullable=False, default=0, comment="Cumulative payments; add-only")
	currency_code = Column(String(3), nullable=False, default="USD")

	tariff_code = Column(String(50), nullable=True)
	bill_breakdown = Column(JSONB, nullable=False, default=dict, comment="Itemised charge breakdown")

	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|ISSUED|PARTIALLY_PAID|PAID|OVERDUE|DISPUTED|VOIDED",
	)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	meter: Meter = relationship("Meter", back_populates="bills", lazy="select")

	def __repr__(self) -> str:
		return f"<EnergyBill {self.bill_number!r} meter={self.meter_id!r} amount={self.amount_cents}¢ status={self.status!r}>"


# ---------------------------------------------------------------------------
# RenewableAttribute
# ---------------------------------------------------------------------------

class RenewableAttribute(AuditMixin, Model):
	"""Renewable Energy Certificate (REC / REGO / GO) or attribute.

	Represents a certificate issued by a renewable energy registry
	(ERCOT, I-REC, EKO, RECS International, etc.) for verified
	renewable generation.

	IMMUTABLE once retired=True — certificates cannot be un-retired.
	generation_mwh: NUMERIC(15,4) MWh generated for this certificate.
	"""

	__allow_unmapped__ = True
	__tablename__ = "en_renewable_attribute"
	__table_args__ = (
		Index("ix_en_rac_tenant", "tenant_id"),
		Index("ix_en_rac_energy_type", "energy_type"),
		Index("ix_en_rac_generation_date", "generation_date"),
		Index("ix_en_rac_registry", "registry_id"),
		Index("ix_en_rac_retired", "retired"),
		UniqueConstraint("tenant_id", "certificate_id", name="uq_en_rac_tenant_cert"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	certificate_id = Column(String(100), nullable=False, comment="Registry-issued certificate ID; unique per tenant")

	energy_type = Column(
		String(20),
		nullable=False,
		comment="SOLAR|WIND|HYDRO|GEOTHERMAL|BIOMASS|TIDAL|OTHER",
	)
	generation_mwh = Column(Numeric(15, 4), nullable=False, comment="MWh of renewable energy represented")
	generation_date = Column(Date, nullable=False, comment="Date of generation")
	generation_facility_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to generation facility")
	generation_facility_name = Column(String(255), nullable=True, comment="Denormalized facility name")
	generation_country = Column(String(3), nullable=True, comment="ISO 3166-1 alpha-3 country code")

	registry_id = Column(String(100), nullable=True, index=True, comment="Issuing registry transaction ID")
	registry_name = Column(String(100), nullable=True, comment="ERCOT|I-REC|RECS|GO|REGO|EKO")

	issued_date = Column(Date, nullable=True)
	expiry_date = Column(Date, nullable=True)
	retired = Column(Boolean, nullable=False, default=False, comment="True = certificate consumed; IMMUTABLE once True")
	retired_at = Column(DateTime(timezone=True), nullable=True)
	retired_by_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	retirement_purpose = Column(String(100), nullable=True, comment="VOLUNTARY|COMPLIANCE|RESALE|AUDIT")

	holder_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to foundation Party (current certificate holder)")
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<RenewableAttribute cert={self.certificate_id!r} type={self.energy_type!r} mwh={self.generation_mwh} retired={self.retired}>"


__all__ = [
	"Meter",
	"MeterReading",
	"EnergyBill",
	"RenewableAttribute",
]
