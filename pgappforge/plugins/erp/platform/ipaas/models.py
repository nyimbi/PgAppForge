"""
pgappforge/plugins/erp/platform/ipaas/models.py

SQLAlchemy models for the iPaaS (Integration Platform as a Service) plugin.

Table prefix: ips_
PostgreSQL ONLY — JSONB for config, mapping, and auth schemas.
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


PROTOCOL = ("REST", "DB", "FILE", "EMAIL", "QUEUE", "GRPC", "SOAP")
TRIGGER_TYPE = ("WEBHOOK", "SCHEDULE", "EVENT", "MANUAL")
RUN_STATUS = ("RUNNING", "SUCCESS", "FAILED", "PARTIAL")


class ConnectorDefinition(AuditMixin, Model):
	"""Defines a reusable connector type (e.g. REST API, PostgreSQL, S3, SMTP)."""

	__tablename__ = "ips_connector_definition"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	name = Column(String(200), nullable=False)
	version = Column(String(20), nullable=False, default="1.0.0")

	protocol = Column(String(10), nullable=False)    # REST/DB/FILE/EMAIL/QUEUE/GRPC/SOAP
	auth_type = Column(String(50), nullable=False, default="NONE")  # NONE/API_KEY/OAUTH2/BASIC

	# JSON Schema describing configuration fields for this connector type
	config_schema = Column(JSONB, nullable=False, default=dict)

	is_active = Column(Boolean, nullable=False, default=True)

	# Relationships
	instances = relationship("ConnectorInstance", back_populates="definition", lazy="select")

	__table_args__ = (
		UniqueConstraint("tenant_id", "name", "version", name="uq_ips_connector_def_name_ver"),
	)

	def __repr__(self) -> str:
		return f"<ConnectorDefinition {self.name!r} v{self.version}>"


class ConnectorInstance(AuditMixin, Model):
	"""A configured, deployable instance of a ConnectorDefinition."""

	__tablename__ = "ips_connector_instance"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	definition_id = Column(
		String(36),
		ForeignKey("ips_connector_definition.id", ondelete="CASCADE"),
		nullable=False,
	)
	name = Column(String(200), nullable=False)

	# Encrypted connection config (url, credentials, etc.) — encrypted at rest
	config_encrypted = Column(JSONB, nullable=False, default=dict)

	status = Column(String(20), nullable=False, default="ACTIVE")  # ACTIVE/INACTIVE/ERROR
	last_sync_at = Column(DateTime(timezone=True), nullable=True)

	# Relationships
	definition = relationship("ConnectorDefinition", back_populates="instances", lazy="select")
	source_flows = relationship(
		"IntegrationFlow",
		foreign_keys="IntegrationFlow.source_connector_id",
		back_populates="source_connector",
		lazy="select",
	)
	target_flows = relationship(
		"IntegrationFlow",
		foreign_keys="IntegrationFlow.target_connector_id",
		back_populates="target_connector",
		lazy="select",
	)

	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_ips_instance_name_tenant"),
	)

	def __repr__(self) -> str:
		return f"<ConnectorInstance {self.name!r} [{self.status}]>"


class IntegrationFlow(AuditMixin, Model):
	"""Defines an integration flow: source → transform → target."""

	__tablename__ = "ips_flow"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	name = Column(String(200), nullable=False)
	trigger_type = Column(String(20), nullable=False, default="MANUAL")  # WEBHOOK/SCHEDULE/EVENT/MANUAL

	source_connector_id = Column(
		String(36),
		ForeignKey("ips_connector_instance.id", ondelete="SET NULL"),
		nullable=True,
	)
	target_connector_id = Column(
		String(36),
		ForeignKey("ips_connector_instance.id", ondelete="SET NULL"),
		nullable=True,
	)

	# Field mapping: [{source_field, target_field, transform?}]
	mapping = Column(JSONB, nullable=False, default=list)

	is_active = Column(Boolean, nullable=False, default=True)

	# Relationships
	source_connector = relationship(
		"ConnectorInstance",
		foreign_keys=[source_connector_id],
		back_populates="source_flows",
		lazy="select",
	)
	target_connector = relationship(
		"ConnectorInstance",
		foreign_keys=[target_connector_id],
		back_populates="target_flows",
		lazy="select",
	)
	runs = relationship("IntegrationRun", back_populates="flow", lazy="select")

	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_ips_flow_name_tenant"),
		Index("ix_ips_flow_tenant_active", "tenant_id", "is_active"),
	)

	def __repr__(self) -> str:
		return f"<IntegrationFlow {self.name!r} [{self.trigger_type}]>"


class IntegrationRun(AuditMixin, Model):
	"""Execution record for a single flow run."""

	__tablename__ = "ips_run"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	flow_id = Column(
		String(36),
		ForeignKey("ips_flow.id", ondelete="CASCADE"),
		nullable=False,
	)

	started_at = Column(DateTime(timezone=True), nullable=False, default=_now)
	completed_at = Column(DateTime(timezone=True), nullable=True)

	records_processed = Column(Integer, nullable=False, default=0)
	errors_count = Column(Integer, nullable=False, default=0)
	status = Column(String(20), nullable=False, default="RUNNING")  # RUNNING/SUCCESS/FAILED/PARTIAL

	# Relationships
	flow = relationship("IntegrationFlow", back_populates="runs", lazy="select")

	__table_args__ = (
		Index("ix_ips_run_flow_started", "flow_id", "started_at"),
		Index("ix_ips_run_tenant_status", "tenant_id", "status"),
	)

	def __repr__(self) -> str:
		return f"<IntegrationRun flow={self.flow_id} [{self.status}]>"
