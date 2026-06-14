"""MES models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class MachineDefinition(Model):
	__tablename__ = "platform_mes_machine"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	machine_code = sa.Column(sa.String(50), nullable=False)
	work_center_id = sa.Column(sa.String(36), nullable=True, index=True)
	opc_ua_endpoint = sa.Column(sa.Text, nullable=True, comment="opc.tcp://host:port — optional")
	telemetry_schema = sa.Column(JSONB, nullable=True)
	is_active = sa.Column(sa.Boolean, nullable=False, default=True)


class MachineReading(Model):
	__tablename__ = "platform_mes_reading"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	machine_id = sa.Column(sa.String(36), sa.ForeignKey("platform_mes_machine.id"), nullable=False, index=True)
	reading_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
	readings = sa.Column(JSONB, nullable=False, comment="{speed_rpm, temp_c, power_kw, pieces_produced, rejects}")


class ProductionAlert(Model):
	__tablename__ = "platform_mes_alert"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	machine_id = sa.Column(sa.String(36), sa.ForeignKey("platform_mes_machine.id"), nullable=False, index=True)
	alert_type = sa.Column(sa.String(20), nullable=False, comment="DOWNTIME, QUALITY, MAINTENANCE")
	severity = sa.Column(sa.String(10), nullable=False, default="MEDIUM")
	started_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
	resolved_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
	description = sa.Column(sa.Text, nullable=True)
