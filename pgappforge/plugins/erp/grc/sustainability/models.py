"""
pgappforge/plugins/erp/grc/sustainability/models.py

ESG / Sustainability models — emission sources, activity records, ESG metrics
and annual snapshots.

Entities:
  EmissionSource    — activity type + emission factor master (GHG Protocol)
  EmissionRecord    — measured/calculated activity-based emission entry
  ESGMetric         — metric definition with framework mapping and target
  ESGSnapshot       — annual actual vs target capture per metric

Design:
  - EmissionRecord.co2e_tonnes: NUMERIC(15,4) — never float
  - emission_factor: NUMERIC(15,8) to preserve precision (kgCO2e per unit)
  - scope: INTEGER 1/2/3 (GHG Protocol scopes)
  - All PKs: UUID v4; all timestamps: TIMESTAMPTZ DEFAULT NOW()
  - tenant_id on all entities
  - EmissionRecord: immutable after verification; insert correction rows
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# EmissionSource
# ---------------------------------------------------------------------------

class EmissionSource(AuditMixin, Model):
	"""Emission factor master record per activity type and GHG scope.

	emission_factor: kg CO2-equivalent emitted per unit of activity.
	  Stored as NUMERIC(15,8) — never float.
	emission_factor_source: e.g. 'IPCC_AR6', 'DEFRA_2024', 'EPA_2024'.
	effective_from: date from which this factor is valid; use the most
	  recent row with effective_from <= activity date for calculations.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_emission_source"
	__table_args__ = (
		Index("ix_erp_emsrc_tenant", "tenant_id"),
		Index("ix_erp_emsrc_scope", "scope"),
		Index("ix_erp_emsrc_category", "emission_category"),
		Index("ix_erp_emsrc_effective", "effective_from"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	source_name = Column(String(300), nullable=False)
	scope = Column(
		Integer,
		nullable=False,
		comment="GHG Protocol scope: 1 (direct), 2 (purchased energy), 3 (value chain)",
	)
	emission_category = Column(
		String(200),
		nullable=False,
		comment=(
			"e.g. 'Stationary Combustion', 'Mobile Combustion',"
			" 'Purchased Electricity', 'Business Travel'"
		),
	)
	activity_type = Column(
		String(200),
		nullable=False,
		comment="e.g. 'natural_gas_combustion', 'electricity_consumption'",
	)
	unit_of_measure = Column(
		String(50),
		nullable=False,
		comment="Unit of activity e.g. 'kWh', 'litres', 'km', 'tonne'",
	)
	emission_factor = Column(
		Numeric(15, 8),
		nullable=False,
		comment="kgCO2e per unit of activity (never float)",
	)
	emission_factor_source = Column(
		String(200),
		nullable=False,
		comment="e.g. 'IPCC_AR6', 'DEFRA_2024', 'EPA_2024'",
	)
	effective_from = Column(
		Date,
		nullable=False,
		comment="Use the most recent factor with effective_from <= activity date",
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

	records: list[EmissionRecord] = relationship(
		"EmissionRecord",
		back_populates="source",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<EmissionSource {self.source_name!r}"
			f" scope={self.scope} factor={self.emission_factor}>"
		)


# ---------------------------------------------------------------------------
# EmissionRecord
# ---------------------------------------------------------------------------

class EmissionRecord(AuditMixin, Model):
	"""Activity-based GHG emission entry.

	co2e_tonnes: computed result stored as NUMERIC(15,4).
	  Calculation: activity_quantity * emission_factor / 1000
	  (factor is kgCO2e; result is tCO2e).

	method:
	  CALCULATED — derived from activity_quantity × emission_factor
	  MEASURED   — direct measurement (e.g. continuous monitoring)
	  ESTIMATED  — proxy or engineering estimate

	verified: True once an external verifier has signed off.
	Immutable after verification — insert a correction row for adjustments.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_emission_record"
	__table_args__ = (
		Index("ix_erp_emrec_source", "source_id"),
		Index("ix_erp_emrec_tenant", "tenant_id"),
		Index("ix_erp_emrec_period", "period_date", postgresql_using="brin"),
		Index("ix_erp_emrec_verified", "verified"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	source_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_emission_source.id", ondelete="RESTRICT"),
		nullable=False,
	)
	period_date = Column(Date, nullable=False, comment="Activity period (month-start recommended)")
	activity_quantity = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Measured activity quantity in source unit_of_measure",
	)
	uom = Column(
		String(50),
		nullable=False,
		comment="Unit of measure at time of recording (copied from source)",
	)
	co2e_tonnes = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Calculated or measured tCO2e (never float)",
	)
	method = Column(
		String(15),
		nullable=False,
		default="CALCULATED",
		comment="CALCULATED | MEASURED | ESTIMATED",
	)
	verified = Column(Boolean, nullable=False, default=False)
	verified_by = Column(
		String(200),
		nullable=True,
		comment="Verifier name or organisation",
	)
	data_quality = Column(
		String(6),
		nullable=False,
		default="MEDIUM",
		comment="HIGH | MEDIUM | LOW",
	)
	notes = Column(Text, nullable=True)

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

	source: EmissionSource = relationship(
		"EmissionSource",
		back_populates="records",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<EmissionRecord {self.id!r} source={self.source_id!r}"
			f" period={self.period_date!r} co2e={self.co2e_tonnes}t"
			f" verified={self.verified}>"
		)


# ---------------------------------------------------------------------------
# ESGMetric
# ---------------------------------------------------------------------------

class ESGMetric(AuditMixin, Model):
	"""ESG metric definition with framework alignment and target.

	metric_code: unique per tenant (e.g. 'GHG_INTENSITY', 'WATER_USE',
	  'BOARD_DIVERSITY_PCT', 'LOST_TIME_INJURY_RATE').
	pillar: ENVIRONMENTAL | SOCIAL | GOVERNANCE
	reporting_framework: GRI | SASB | TCFD | CDP
	target_value + target_year: the aspirational goal.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_esg_metric"
	__table_args__ = (
		UniqueConstraint("tenant_id", "metric_code",
		                 name="uq_erp_esgmetric_tenant_code"),
		Index("ix_erp_esgmetric_tenant", "tenant_id"),
		Index("ix_erp_esgmetric_pillar", "pillar"),
		Index("ix_erp_esgmetric_framework", "reporting_framework"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	metric_code = Column(String(100), nullable=False)
	metric_name = Column(String(300), nullable=False)
	pillar = Column(
		String(15),
		nullable=False,
		comment="ENVIRONMENTAL | SOCIAL | GOVERNANCE",
	)
	unit = Column(String(100), nullable=False, comment="e.g. 'tCO2e', '%', 'kWh/unit'")
	target_value = Column(
		Numeric(20, 4),
		nullable=True,
		comment="Target value (same unit as metric)",
	)
	target_year = Column(Integer, nullable=True)
	reporting_framework = Column(
		String(10),
		nullable=False,
		comment="GRI | SASB | TCFD | CDP",
	)
	description = Column(Text, nullable=True)

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

	snapshots: list[ESGSnapshot] = relationship(
		"ESGSnapshot",
		back_populates="metric",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ESGMetric {self.metric_code!r} pillar={self.pillar!r}"
			f" framework={self.reporting_framework!r}>"
		)


# ---------------------------------------------------------------------------
# ESGSnapshot
# ---------------------------------------------------------------------------

class ESGSnapshot(AuditMixin, Model):
	"""Annual ESG actual vs target capture.

	improvement_pct: (actual - prior_year_actual) / prior_year_actual × 100.
	  Stored as NUMERIC(7,2) for reporting; computed by service layer.
	verified_by / verified_at: third-party assurance details.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_esg_snapshot"
	__table_args__ = (
		UniqueConstraint("tenant_id", "metric_id", "snapshot_year",
		                 name="uq_erp_esgsnap_tenant_metric_year"),
		Index("ix_erp_esgsnap_metric", "metric_id"),
		Index("ix_erp_esgsnap_tenant", "tenant_id"),
		Index("ix_erp_esgsnap_year", "snapshot_year"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	metric_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_esg_metric.id", ondelete="RESTRICT"),
		nullable=False,
	)
	snapshot_year = Column(Integer, nullable=False)
	actual_value = Column(Numeric(20, 4), nullable=False)
	target_value = Column(
		Numeric(20, 4),
		nullable=True,
		comment="Target at time of snapshot (may differ from metric.target_value)",
	)
	improvement_pct = Column(
		Numeric(7, 2),
		nullable=True,
		comment="YoY improvement %; positive = better, negative = worse",
	)
	notes = Column(Text, nullable=True)
	verified_by = Column(String(200), nullable=True)
	verified_at = Column(DateTime(timezone=True), nullable=True)

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

	metric: ESGMetric = relationship(
		"ESGMetric",
		back_populates="snapshots",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ESGSnapshot {self.id!r} metric={self.metric_id!r}"
			f" year={self.snapshot_year} actual={self.actual_value}>"
		)


__all__ = [
	"EmissionSource",
	"EmissionRecord",
	"ESGMetric",
	"ESGSnapshot",
]
