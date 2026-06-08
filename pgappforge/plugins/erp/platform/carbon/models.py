from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
	BigInteger,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"EmissionFactor",
	"EmissionRecord",
	"GHGReport",
	"CarbonOffset",
]


class EmissionFactor(AuditMixin, Model):
	__tablename__ = "co2_emission_factor"
	__table_args__ = (
		Index(
			"ix_co2_emission_factor_tenant_source_effective",
			"tenant_id",
			"source_type",
			"effective_from",
		),
		Index("ix_co2_emission_factor_scope", "scope"),
	)

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
		server_default=func.gen_random_uuid(),
	)
	source_type: Mapped[str] = mapped_column(String(100), nullable=False)
	country_code: Mapped[str] = mapped_column(
		String(3), nullable=False, default="KEN"
	)
	region: Mapped[str | None] = mapped_column(String(100), nullable=True)
	co2e_per_unit: Mapped[object] = mapped_column(
		Numeric(12, 6), nullable=False
	)
	unit: Mapped[str] = mapped_column(String(30), nullable=False)
	scope: Mapped[int] = mapped_column(Integer, nullable=False)
	source: Mapped[str | None] = mapped_column(String(200), nullable=True)
	effective_from: Mapped[date] = mapped_column(Date, nullable=False)
	effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
	tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		server_default=func.now(),
	)


class EmissionRecord(AuditMixin, Model):
	__tablename__ = "co2_record"
	__table_args__ = (
		Index(
			"ix_co2_record_tenant_scope_period",
			"tenant_id",
			"scope",
			"period",
		),
		Index(
			"ix_co2_record_tenant_period_source_type",
			"tenant_id",
			"period",
			"source_type",
		),
	)

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
	)
	scope: Mapped[int] = mapped_column(Integer, nullable=False)
	source_type: Mapped[str] = mapped_column(String(100), nullable=False)
	description: Mapped[str | None] = mapped_column(Text, nullable=True)
	activity_data: Mapped[object] = mapped_column(Numeric(15, 4), nullable=False)
	unit: Mapped[str] = mapped_column(String(30), nullable=False)
	emission_factor_id: Mapped[str | None] = mapped_column(
		UUID(as_uuid=False),
		ForeignKey("co2_emission_factor.id", ondelete="SET NULL"),
		nullable=True,
	)
	co2e_kg: Mapped[object] = mapped_column(Numeric(15, 4), nullable=False)
	period: Mapped[str] = mapped_column(String(20), nullable=False)
	entity_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
	source_module: Mapped[str | None] = mapped_column(String(100), nullable=True)
	source_record_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
	tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		server_default=func.now(),
	)


class GHGReport(AuditMixin, Model):
	__tablename__ = "co2_report"
	__table_args__ = (
		Index("ix_co2_report_tenant_period", "tenant_id", "period"),
	)

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
	)
	period: Mapped[str] = mapped_column(String(20), nullable=False)
	scope1_co2e_kg: Mapped[object] = mapped_column(
		Numeric(15, 4), nullable=False, default=0
	)
	scope2_co2e_kg: Mapped[object] = mapped_column(
		Numeric(15, 4), nullable=False, default=0
	)
	scope3_co2e_kg: Mapped[object] = mapped_column(
		Numeric(15, 4), nullable=False, default=0
	)
	total_co2e_kg: Mapped[object] = mapped_column(Numeric(15, 4), nullable=False)
	methodology: Mapped[str | None] = mapped_column(Text, nullable=True)
	entity_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
	generated_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
	tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)


class CarbonOffset(AuditMixin, Model):
	__tablename__ = "co2_offset"
	__table_args__ = (
		Index("ix_co2_offset_tenant_period", "tenant_id", "period"),
	)

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
	)
	period: Mapped[str] = mapped_column(String(20), nullable=False)
	co2e_kg: Mapped[object] = mapped_column(Numeric(15, 4), nullable=False)
	offset_type: Mapped[str] = mapped_column(String(50), nullable=False)
	provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
	certificate_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
	cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
	currency_code: Mapped[str] = mapped_column(
		String(3), nullable=False, default="USD"
	)
	tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
