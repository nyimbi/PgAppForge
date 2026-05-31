"""Audit Trail models."""
from __future__ import annotations
from datetime import datetime, timezone
from pgappforge import Model
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, ForeignKey,
	Integer, String, Index)
from sqlalchemy.dialects.postgresql import INET, JSONB


class AuditLog(Model):
	"""Append-only, cryptographically chained audit log entry."""
	__tablename__ = "pgaf_audit_log"
	__table_args__ = (
		Index("ix_pgaf_audit_model_entity", "model_name", "entity_id"),
		Index("ix_pgaf_audit_created_brin", "created_at", postgresql_using="brin"),
		{"extend_existing": True},
	)
	id = Column(BigInteger, primary_key=True, autoincrement=True)
	model_name = Column(String(255), nullable=False)
	entity_id = Column(String(64), nullable=False)
	operation = Column(String(10), nullable=False)  # INSERT/UPDATE/DELETE
	actor_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
	actor_role = Column(String(128))
	actor_sub_role = Column(String(128))
	ip_address = Column(INET)
	user_agent = Column(String(512))
	field_diffs = Column(JSONB, nullable=False, default=dict)
	row_hash = Column(String(64), nullable=False)
	prev_hash = Column(String(64))
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)


class AuditRetentionPolicy(Model):
	"""Per-model data retention configuration."""
	__tablename__ = "pgaf_audit_retention"
	__table_args__ = {"extend_existing": True}
	id = Column(Integer, primary_key=True)
	model_name = Column(String(255), nullable=False, unique=True)
	retain_days = Column(Integer, nullable=False, default=730)  # 2 years
	archive_before_delete = Column(Boolean, default=True)
	archive_destination = Column(String(512))
	pii_fields = Column(JSONB, default=list)
	created_at = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
	)
