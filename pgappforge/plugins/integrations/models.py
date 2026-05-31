"""Integration Hub models."""
from __future__ import annotations
from datetime import datetime, timezone
from pgappforge import Model
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, ForeignKey,
	Integer, LargeBinary, String, Text)
from sqlalchemy.dialects.postgresql import JSONB


class Integration(Model):
	"""A configured connection to an external service."""
	__tablename__ = "pgaf_integration"
	__table_args__ = {"extend_existing": True}
	id = Column(Integer, primary_key=True)
	name = Column(String(255), nullable=False)
	connector_type = Column(String(64), nullable=False)
	# stripe / salesforce / hubspot / slack / teams / github / google / twilio / rest / graphql
	status = Column(String(20), default="inactive")
	# inactive / active / error / paused
	credential_id = Column(Integer, ForeignKey("pgaf_integration_credential.id"), nullable=True)
	config = Column(JSONB, default=dict)
	sync_enabled = Column(Boolean, default=False)
	sync_schedule = Column(String(256))  # RRULE
	last_sync_at = Column(DateTime(timezone=True))
	last_sync_status = Column(String(20))
	last_error = Column(Text)
	created_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class IntegrationCredential(Model):
	"""Encrypted credential storage for integrations."""
	__tablename__ = "pgaf_integration_credential"
	__table_args__ = {"extend_existing": True}
	id = Column(Integer, primary_key=True)
	integration_id = Column(Integer, ForeignKey("pgaf_integration.id", ondelete="CASCADE"),
		nullable=True)
	credential_type = Column(String(20), nullable=False)
	# oauth2 / api_key / basic / bearer
	encrypted_data = Column(LargeBinary, nullable=False)
	# AES-256-GCM encrypted JSON: {access_token, refresh_token, api_key, ...}
	expires_at = Column(DateTime(timezone=True))
	created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WebhookEndpoint(Model):
	"""Inbound or outbound webhook configuration."""
	__tablename__ = "pgaf_webhook"
	__table_args__ = {"extend_existing": True}
	id = Column(Integer, primary_key=True)
	direction = Column(String(10), nullable=False)  # inbound / outbound
	name = Column(String(255), nullable=False)
	description = Column(Text)
	token = Column(String(64), unique=True)  # for inbound URL
	url = Column(String(1024))               # for outbound
	secret = Column(String(256))             # HMAC signing secret
	verify_signature = Column(Boolean, default=True)
	trigger_config = Column(JSONB, default=dict)
	# Inbound: {action: rules|bpm|model_create, action_config: {...}}
	# Outbound: {events: [model_insert, model_update], model_name: str}
	payload_template = Column(Text)          # Jinja2 template for outbound
	headers_template = Column(JSONB, default=dict)
	status = Column(String(20), default="active")
	retry_count = Column(Integer, default=10)
	retry_backoff = Column(String(20), default="exponential")
	created_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class IntegrationEvent(Model):
	"""Log of inbound/outbound webhook deliveries."""
	__tablename__ = "pgaf_integration_event"
	__table_args__ = {"extend_existing": True}
	id = Column(BigInteger, primary_key=True)
	webhook_id = Column(Integer, ForeignKey("pgaf_webhook.id", ondelete="CASCADE"), index=True)
	direction = Column(String(10))
	status = Column(String(20))  # delivered / failed / retrying / pending
	attempt_count = Column(Integer, default=0)
	request_headers = Column(JSONB, default=dict)
	request_body = Column(Text)
	response_code = Column(Integer)
	response_body = Column(Text)
	error_message = Column(Text)
	created_at = Column(DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc), index=True)
	next_retry_at = Column(DateTime(timezone=True), index=True)
