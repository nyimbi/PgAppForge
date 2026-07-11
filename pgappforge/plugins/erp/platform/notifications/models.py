"""
pgappforge/plugins/erp/platform/notifications/models.py

Persistent KPI threshold alert rules for ERP notification dispatch.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

try:
	from uuid_extensions import uuid7str
except ImportError:
	from uuid6 import uuid7

	def uuid7str() -> str:
		return str(uuid7())


def _now() -> datetime:
	return datetime.now(timezone.utc)


class KPIAlertRule(AuditMixin, Model):
	"""Threshold rule evaluated against a named ERP KPI."""

	__allow_unmapped__ = True
	__tablename__ = "erp_kpi_alert_rules"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_erp_kpi_alert_rule_tenant_name"),
		Index("ix_erp_kpi_alert_rule_tenant_active", "tenant_id", "is_active"),
		Index("ix_erp_kpi_alert_rule_kpi_key", "tenant_id", "kpi_key"),
		{"extend_existing": True},
	)

	id: str = Column(UUID(as_uuid=False), primary_key=True, default=uuid7str)
	tenant_id: str = Column(UUID(as_uuid=False), nullable=False, index=True)
	name: str = Column(String(200), nullable=False)
	kpi_key: str = Column(
		String(100),
		nullable=False,
		comment="ar_overdue_cents|open_risks_critical|payroll_variance_pct|overdue_invoice_count|procurement_savings_pct|compliance_overdue",
	)
	condition: str = Column(
		String(10),
		nullable=False,
		comment="gt|lt|gte|lte|eq",
	)
	threshold_value: str = Column(
		String(50),
		nullable=False,
		comment="String form preserves int and float thresholds",
	)
	notification_channels: list[str] = Column(JSONB, nullable=False, default=list)
	recipients: list[str] = Column(JSONB, nullable=False, default=list)
	is_active: bool = Column(Boolean, nullable=False, default=True, server_default=sa.text("true"))
	last_triggered_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	cooldown_minutes: int = Column(Integer, nullable=False, default=60, server_default="60")
	created_at: datetime = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=sa.text("NOW()"))
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		onupdate=_now,
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return f"<KPIAlertRule {self.name!r} kpi={self.kpi_key!r} active={self.is_active}>"


__all__ = ["KPIAlertRule", "uuid7str"]
