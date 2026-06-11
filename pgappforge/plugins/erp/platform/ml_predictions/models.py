"""
pgappforge/plugins/erp/platform/ml_predictions/models.py

SQLAlchemy 2.x models for ML prediction results and model configuration.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Boolean, Column, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model


def _uuid4() -> str:
	return str(uuid.uuid4())


class MLPrediction(Model):
	"""Persisted ML prediction result.

	Covers all five prediction types:
	  AP_DUPLICATE  — AP invoice duplicate detection
	  HR_ATTRITION  — employee attrition risk
	  LEAD_SCORE    — CRM opportunity lead score
	  GL_ANOMALY    — GL journal entry anomaly
	  DEMAND_FORECAST — inventory demand forecast
	"""

	__tablename__ = "plat_ml_prediction"
	__table_args__ = (
		Index("ix_plat_ml_pred_lookup", "tenant_id", "prediction_type", "reference_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# AP_DUPLICATE / HR_ATTRITION / LEAD_SCORE / GL_ANOMALY / DEMAND_FORECAST
	prediction_type = Column(String(30), nullable=False)

	# Back-reference to originating business record
	reference_type = Column(String(50), nullable=True)   # e.g. "APInvoice"
	reference_id   = Column(String(100), nullable=True)  # PK of that record

	# 0.0 – 1.0 probability or normalised score
	score = Column(Numeric(7, 4), nullable=False)

	# e.g. "HIGH_RISK" / "DUPLICATE" / "ANOMALY"
	label = Column(String(30), nullable=True)

	# Confidence of the prediction (optional)
	confidence = Column(Numeric(7, 4), nullable=True)

	# Which features contributed — persisted for explainability
	features_used = Column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'"))

	model_version = Column(String(20), nullable=False, default="1.0")
	explanation   = Column(String(2000), nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)


class MLModelConfig(Model):
	"""Per-tenant ML model configuration — thresholds and feature weights.

	One row per (tenant_id, prediction_type) pair.
	"""

	__tablename__ = "plat_ml_model_config"
	__table_args__ = (
		UniqueConstraint("tenant_id", "prediction_type", name="uq_plat_ml_cfg_tenant_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id       = Column(UUID(as_uuid=False), nullable=False, index=True)
	prediction_type = Column(String(30), nullable=False)

	# {"high": 0.8, "medium": 0.5, "low": 0.2}
	thresholds = Column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'"))

	# Per-feature importance weights
	feature_weights = Column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'"))

	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=True,
		onupdate=lambda: datetime.now(timezone.utc),
	)


__all__ = ["MLPrediction", "MLModelConfig"]
