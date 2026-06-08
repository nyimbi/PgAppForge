from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
	BigInteger,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"AnomalyDetectionRun",
	"Anomaly",
]


class AnomalyDetectionRun(AuditMixin, Model):
	__tablename__ = "anm_run"
	__table_args__ = (
		Index("ix_anm_run_tenant_run_type", "tenant_id", "run_type"),
	)

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
		server_default=func.gen_random_uuid(),
	)
	run_type: Mapped[str] = mapped_column(String(30), nullable=False)
	period: Mapped[str | None] = mapped_column(String(20), nullable=True)
	status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
	anomalies_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
	tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		server_default=func.now(),
	)

	anomalies: Mapped[list[Anomaly]] = relationship(
		"Anomaly",
		back_populates="run",
		cascade="all, delete-orphan",
		lazy="select",
	)


class Anomaly(AuditMixin, Model):
	__tablename__ = "anm_anomaly"
	__table_args__ = (
		Index("ix_anm_anomaly_tenant_status_severity", "tenant_id", "status", "severity"),
		Index("ix_anm_anomaly_tenant_anomaly_type", "tenant_id", "anomaly_type"),
		Index("ix_anm_anomaly_source_record_id", "source_record_id"),
	)

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
	)
	run_id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		ForeignKey("anm_run.id", ondelete="CASCADE"),
		nullable=False,
	)
	anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False)
	severity: Mapped[str] = mapped_column(String(20), nullable=False)
	source_module: Mapped[str] = mapped_column(String(50), nullable=False)
	source_record_id: Mapped[str] = mapped_column(String(50), nullable=False)
	description: Mapped[str] = mapped_column(Text, nullable=False)
	evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
	status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
	resolved_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
	resolved_at: Mapped[datetime | None] = mapped_column(
		DateTime(timezone=True), nullable=True
	)
	resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
	tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		server_default=func.now(),
	)

	run: Mapped[AnomalyDetectionRun] = relationship(
		"AnomalyDetectionRun",
		back_populates="anomalies",
	)
