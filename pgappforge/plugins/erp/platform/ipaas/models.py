"""iPaaS models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class ConnectorDefinition(Model):
	__tablename__ = "platform_ipaas_connector_def"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	name = sa.Column(sa.String(100), nullable=False, unique=True)
	version = sa.Column(sa.String(20), nullable=False, default="1.0.0")
	protocol = sa.Column(sa.String(20), nullable=False, comment="REST, SOAP, DB, FILE, QUEUE")
	auth_type = sa.Column(sa.String(20), nullable=True, comment="NONE, BASIC, BEARER, OAUTH2, APIKEY")
	config_schema = sa.Column(JSONB, nullable=True, comment="JSON Schema of required config fields")
	is_builtin = sa.Column(sa.Boolean, nullable=False, default=False)


class ConnectorInstance(Model):
	__tablename__ = "platform_ipaas_connector_instance"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	definition_id = sa.Column(sa.String(36), sa.ForeignKey("platform_ipaas_connector_def.id"), nullable=False)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	config = sa.Column(JSONB, nullable=True, comment="Connector config (credentials stored as refs, not plaintext)")
	status = sa.Column(sa.String(20), nullable=False, default="ACTIVE")
	last_sync_at = sa.Column(sa.DateTime(timezone=True), nullable=True)


class IntegrationFlow(Model):
	__tablename__ = "platform_ipaas_flow"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	trigger_type = sa.Column(sa.String(20), nullable=False, comment="WEBHOOK, SCHEDULE, EVENT")
	source_connector_id = sa.Column(sa.String(36), sa.ForeignKey("platform_ipaas_connector_instance.id"), nullable=False)
	target_connector_id = sa.Column(sa.String(36), sa.ForeignKey("platform_ipaas_connector_instance.id"), nullable=False)
	mapping = sa.Column(JSONB, nullable=False, comment="[{source_field, target_field, transform?}]")
	is_active = sa.Column(sa.Boolean, nullable=False, default=True)


class IntegrationRun(Model):
	__tablename__ = "platform_ipaas_run"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	flow_id = sa.Column(sa.String(36), sa.ForeignKey("platform_ipaas_flow.id"), nullable=False, index=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	started_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
	records_processed = sa.Column(sa.Integer, nullable=False, default=0)
	errors = sa.Column(sa.Integer, nullable=False, default=0)
	status = sa.Column(sa.String(20), nullable=False, default="RUNNING")
	completed_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
	result_payload = sa.Column(JSONB, nullable=True, comment="Mapped payload produced by this run")
	error_message = sa.Column(sa.Text, nullable=True, comment="Failure reason for failed runs")
