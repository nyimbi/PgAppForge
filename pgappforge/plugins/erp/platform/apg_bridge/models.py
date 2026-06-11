"""
pgappforge/plugins/erp/platform/apg_bridge/models.py

SQLAlchemy models for APG bridge state.

Table prefix: plat_apg_
PostgreSQL ONLY — JSONB for contract data and event payloads.

  APGCapabilityCache   — cached APG capability metadata (mutable, refreshable)
  APGEventBridgeLog    — immutable log of events forwarded to APG streams
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	Index,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from pgappforge.models.sqla import Model
from pgappforge.models.mixins import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


class APGCapabilityCache(AuditMixin, Model):
	"""Cached snapshot of an APG capability's marketplace metadata.

	Refreshed by APGBridgeService.sync_capabilities_to_ipaas().
	contract_hash (SHA-256 hex) lets the sync skip unchanged entries.
	"""

	__tablename__ = "plat_apg_capability"

	id = Column(String(36), primary_key=True, default=_uuid4)

	# Canonical identifier returned by APG marketplace
	capability_id = Column(String(100), nullable=False)

	name = Column(String(200), nullable=True)
	domain = Column(String(50), nullable=True, index=True)

	# APG contract fields
	provides = Column(JSONB, nullable=False, default=list)
	requires = Column(JSONB, nullable=False, default=list)

	# SHA-256 of the serialised contract — used to skip unchanged capabilities
	contract_hash = Column(String(64), nullable=True)

	base_url = Column(String(300), nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)

	last_synced_at = Column(DateTime(timezone=True), nullable=True)
	created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		onupdate=_now,
	)

	__table_args__ = (
		UniqueConstraint("capability_id", name="uq_plat_apg_capability_id"),
		Index("ix_plat_apg_cap_domain_active", "domain", "is_active"),
	)

	def __repr__(self) -> str:
		return f"<APGCapabilityCache {self.capability_id!r} active={self.is_active}>"


class APGEventBridgeLog(ImmutableRecordMixin, Model):
	"""Immutable log of PgAppForge domain events forwarded to APG Bytewax streams.

	One row per forwarding attempt.  success=False rows capture the error_message
	for alerting / retry logic.

	Insert-only — never updated.  Corrections are new rows.
	"""

	__tablename__ = "plat_apg_event_log"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	source_event_type = Column(String(100), nullable=True)
	apg_stream = Column(String(200), nullable=True)

	# Full event payload as forwarded to APG
	payload = Column(JSONB, nullable=True, default=dict)

	forwarded_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
	)

	success = Column(Boolean, nullable=False, default=True)
	error_message = Column(Text, nullable=True)

	__table_args__ = (
		Index("ix_plat_apg_log_tenant_fwd", "tenant_id", "forwarded_at"),
		Index("ix_plat_apg_log_stream", "apg_stream"),
		Index("ix_plat_apg_log_success", "success"),
	)

	def __repr__(self) -> str:
		return (
			f"<APGEventBridgeLog {self.source_event_type!r}"
			f" → {self.apg_stream!r} ok={self.success}>"
		)


# Register immutability constraint for APGEventBridgeLog
APGEventBridgeLog._register_immutability()


__all__ = ["APGCapabilityCache", "APGEventBridgeLog"]
