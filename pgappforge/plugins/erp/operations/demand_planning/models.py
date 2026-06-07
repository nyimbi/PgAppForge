"""
pgappforge/plugins/erp/operations/demand_planning/models.py

SQLAlchemy models for the Demand Planning plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - PostgreSQL only — JSONB, UUID, gen_random_uuid()
  - Quantities: Numeric(15,4) — fractional UOMs supported
  - Forecast periods stored as JSONB list of period snapshots

Table prefix: dp_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	CheckConstraint,
	Column,
	DateTime,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# DemandForecast
# ---------------------------------------------------------------------------

class DemandForecast(AuditMixin, Model):
	"""Demand forecast for a single product over a planning horizon.

	periods JSONB holds the per-period forecast data:
	  [
	    {
	      "period": "2025-01",
	      "forecast_qty": "120.0000",
	      "lower_bound": "95.0000",
	      "upper_bound": "145.0000"
	    },
	    ...
	  ]

	All qty values in periods are stored as Decimal strings — never float.
	accuracy_mape is populated after the period closes via compute_accuracy().

	Lifecycle:
	  DRAFT     → APPROVED (planner signs off)
	            → SUPERSEDED (replaced by a newer forecast for same product/period)

	Only one APPROVED forecast per product/base_period should exist per tenant.
	"""

	__allow_unmapped__ = True
	__tablename__ = "dp_forecast"
	__table_args__ = (
		Index("ix_dp_forecast_tenant_product_status", "tenant_id", "product_id", "status"),
		Index("ix_dp_forecast_tenant_period", "tenant_id", "base_period"),
		CheckConstraint(
			"forecast_method IN ('MOVING_AVERAGE','EXPONENTIAL_SMOOTHING','HOLT_WINTERS','MANUAL')",
			name="ck_dp_forecast_method",
		),
		CheckConstraint(
			"status IN ('DRAFT','APPROVED','SUPERSEDED')",
			name="ck_dp_forecast_status",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Product reference (soft FK — cross-module)
	product_id = Column(
		String(50),
		nullable=False,
		comment="Soft FK to inv_product.id or product catalogue ID",
	)

	# Forecast configuration
	forecast_method = Column(
		String(30),
		nullable=False,
		comment="MOVING_AVERAGE | EXPONENTIAL_SMOOTHING | HOLT_WINTERS | MANUAL",
	)
	base_period = Column(
		String(20),
		nullable=False,
		comment="Last historical period used as base — e.g. '2025-05'",
	)
	horizon_periods = Column(
		Integer,
		nullable=False,
		default=12,
		comment="Number of forward periods to forecast",
	)

	# Lifecycle
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | APPROVED | SUPERSEDED",
	)

	# Forecast data — list of {period, forecast_qty, lower_bound, upper_bound}
	periods = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default=sa.text("'[]'::jsonb"),
		comment="Per-period forecast snapshots — qty values as Decimal strings",
	)

	# Accuracy KPI — populated post-hoc
	accuracy_mape = Column(
		Numeric(8, 4),
		nullable=True,
		comment="Mean Absolute Percentage Error % — populated by compute_accuracy()",
	)

	# Approval
	approved_by = Column(String(50), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)

	# Optional entity scope
	entity_id = Column(String(50), nullable=True, index=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<DemandForecast product={self.product_id!r} "
			f"method={self.forecast_method!r} base={self.base_period!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# DemandHistory
# ---------------------------------------------------------------------------

class DemandHistory(AuditMixin, Model):
	"""Actual demand (sales) history per product per period.

	Populated by record_actual() — an upsert keyed on (tenant_id, product_id,
	period).  Used as training data for forecast generation.

	source indicates origin of the actuals:
	  SALES_ORDER — pulled from closed SO lines
	  MANUAL      — manually entered by planner
	  ADJUSTED    — sales actuals adjusted for known anomalies (promotions, etc.)
	"""

	__allow_unmapped__ = True
	__tablename__ = "dp_history"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "product_id", "period",
			name="uq_dp_history_tenant_product_period",
		),
		Index("ix_dp_history_product_period", "product_id", "period"),
		Index("ix_dp_history_tenant_period", "tenant_id", "period"),
		CheckConstraint(
			"source IN ('SALES_ORDER','MANUAL','ADJUSTED')",
			name="ck_dp_history_source",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	product_id = Column(
		String(50),
		nullable=False,
		comment="Soft FK to inv_product.id or product catalogue ID",
	)
	period = Column(
		String(20),
		nullable=False,
		comment="Period label — e.g. '2025-01' for monthly, 'W04-2025' for weekly",
	)
	actual_qty = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Actual demand quantity for the period",
	)
	source = Column(
		String(30),
		nullable=False,
		default="SALES_ORDER",
		comment="SALES_ORDER | MANUAL | ADJUSTED",
	)
	notes = Column(
		Text,
		nullable=True,
		comment="Planner notes — e.g. reason for ADJUSTED records",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<DemandHistory product={self.product_id!r} "
			f"period={self.period!r} qty={self.actual_qty} source={self.source!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"DemandForecast",
	"DemandHistory",
]
