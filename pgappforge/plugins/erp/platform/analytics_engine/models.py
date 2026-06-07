"""
pgappforge/plugins/erp/platform/analytics_engine/models.py

SQLAlchemy models for the Analytics Engine plugin.

Table prefix: anl_
PostgreSQL ONLY — JSONB dimensions/measures/filters, materialized views.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
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


class AnalyticsCube(AuditMixin, Model):
	"""Defines an analytics cube backed by a PostgreSQL materialized view."""

	__tablename__ = "anl_cube"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	name = Column(String(200), nullable=False)
	base_query = Column(Text, nullable=False)

	# CRON-style or named schedule: DAILY / HOURLY / WEEKLY
	refresh_schedule = Column(String(50), nullable=False, default="DAILY")
	last_refreshed = Column(DateTime(timezone=True), nullable=True)

	# JSONB lists of dimension/measure names
	dimensions = Column(JSONB, nullable=False, default=list)
	measures = Column(JSONB, nullable=False, default=list)

	# Name of the PostgreSQL materialized view
	materialized_view_name = Column(String(100), nullable=False)

	is_active = Column(Boolean, nullable=False, default=True)

	# Relationships
	reports = relationship("AnalyticsReport", back_populates="cube", lazy="select")

	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_anl_cube_name_tenant"),
		UniqueConstraint("materialized_view_name", name="uq_anl_cube_view_name"),
	)

	def __repr__(self) -> str:
		return f"<AnalyticsCube {self.name!r} view={self.materialized_view_name!r}>"


class AnalyticsReport(AuditMixin, Model):
	"""A saved report definition that queries a specific cube."""

	__tablename__ = "anl_report"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	cube_id = Column(
		String(36),
		ForeignKey("anl_cube.id", ondelete="CASCADE"),
		nullable=False,
	)
	name = Column(String(200), nullable=False)

	# Filters: [{field, op, value}]
	filters = Column(JSONB, nullable=True, default=list)
	# Group-by field names
	group_by = Column(JSONB, nullable=True, default=list)
	limit_rows = Column(Integer, nullable=False, default=1000)

	# Relationships
	cube = relationship("AnalyticsCube", back_populates="reports", lazy="select")
	cache_entries = relationship("ReportCache", back_populates="report", lazy="select")

	__table_args__ = (
		UniqueConstraint("cube_id", "name", name="uq_anl_report_name_cube"),
		Index("ix_anl_report_tenant", "tenant_id"),
	)

	def __repr__(self) -> str:
		return f"<AnalyticsReport {self.name!r}>"


class ReportCache(AuditMixin, Model):
	"""Cached query result for an AnalyticsReport with TTL."""

	__tablename__ = "anl_report_cache"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	report_id = Column(
		String(36),
		ForeignKey("anl_report.id", ondelete="CASCADE"),
		nullable=False,
	)

	result_json = Column(JSONB, nullable=False, default=list)
	cached_at = Column(DateTime(timezone=True), nullable=False, default=_now)
	expires_at = Column(DateTime(timezone=True), nullable=False)

	# Relationships
	report = relationship("AnalyticsReport", back_populates="cache_entries", lazy="select")

	__table_args__ = (
		Index("ix_anl_cache_report_expires", "report_id", "expires_at"),
	)

	def __repr__(self) -> str:
		return f"<ReportCache report={self.report_id} expires={self.expires_at}>"
