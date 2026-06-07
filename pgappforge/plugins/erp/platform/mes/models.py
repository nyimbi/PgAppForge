"""
pgappforge/plugins/erp/platform/mes/models.py

SQLAlchemy models for the Manufacturing Execution System (MES) plugin.

Table prefix: mes_
PostgreSQL ONLY — JSONB for telemetry schema and readings.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


ALERT_TYPE = ("DOWNTIME", "QUALITY", "MAINTENANCE", "EFFICIENCY")
ALERT_SEVERITY = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


class MachineDefinition(AuditMixin, Model):
	"""Defines a machine/asset tracked by the MES."""

	__tablename__ = "mes_machine"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	machine_code = Column(String(50), nullable=False)
	work_center_id = Column(String(36), nullable=True)

	# OPC-UA endpoint URL for direct telemetry polling
	opc_ua_endpoint = Column(Text, nullable=True)

	# JSON Schema describing expected telemetry fields
	telemetry_schema = Column(JSONB, nullable=True, default=dict)

	# Minutes of continuous downtime before alert fires
	downtime_threshold_minutes = Column(Integer, nullable=False, default=30)

	# Quality threshold: pct good parts before alert fires
	quality_threshold_pct = Column(Numeric(5, 2), nullable=False, default=95)

	is_active = Column(Boolean, nullable=False, default=True)

	# Relationships
	readings = relationship("MachineReading", back_populates="machine", lazy="select")
	alerts = relationship("ProductionAlert", back_populates="machine", lazy="select")

	__table_args__ = (
		UniqueConstraint("tenant_id", "machine_code", name="uq_mes_machine_code_tenant"),
	)

	def __repr__(self) -> str:
		return f"<MachineDefinition {self.machine_code!r}>"


class MachineReading(AuditMixin, Model):
	"""A single telemetry snapshot from a machine."""

	__tablename__ = "mes_reading"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	machine_id = Column(
		String(36),
		ForeignKey("mes_machine.id", ondelete="CASCADE"),
		nullable=False,
	)

	reading_at = Column(DateTime(timezone=True), nullable=False, default=_now)

	# Arbitrary telemetry payload: {speed_rpm, temp_c, good_parts, total_parts, ...}
	readings = Column(JSONB, nullable=False, default=dict)

	# Optional link to a production order
	production_order_id = Column(String(36), nullable=True)

	# Relationships
	machine = relationship("MachineDefinition", back_populates="readings", lazy="select")

	__table_args__ = (
		Index("ix_mes_reading_machine_time", "machine_id", "reading_at"),
	)

	def __repr__(self) -> str:
		return f"<MachineReading machine={self.machine_id} at={self.reading_at}>"


class ProductionAlert(AuditMixin, Model):
	"""An alert raised when a machine breaches a configured threshold."""

	__tablename__ = "mes_alert"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	machine_id = Column(
		String(36),
		ForeignKey("mes_machine.id", ondelete="CASCADE"),
		nullable=False,
	)

	alert_type = Column(String(20), nullable=False)    # DOWNTIME/QUALITY/MAINTENANCE/EFFICIENCY
	severity = Column(String(10), nullable=False, default="MEDIUM")

	started_at = Column(DateTime(timezone=True), nullable=False, default=_now)
	resolved_at = Column(DateTime(timezone=True), nullable=True)

	# Relationships
	machine = relationship("MachineDefinition", back_populates="alerts", lazy="select")

	__table_args__ = (
		Index("ix_mes_alert_machine_type", "machine_id", "alert_type"),
		Index("ix_mes_alert_tenant_unresolved", "tenant_id", "resolved_at"),
	)

	def __repr__(self) -> str:
		return f"<ProductionAlert {self.alert_type} [{self.severity}]>"
