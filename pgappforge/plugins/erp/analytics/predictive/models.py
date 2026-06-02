"""
pgappforge/plugins/erp/analytics/predictive/models.py

SQLAlchemy models for the Predictive Analytics / ML plugin.

Tables
------
analytics_ml_model         — trained model registry (artifact_path, feature schema, accuracy)
analytics_model_prediction — per-entity predictions with confidence and feature snapshot
analytics_anomaly          — detected anomalies with z-score, severity, acknowledgement

Design rules
  - All PKs: UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All mutable entities: tenant_id UUID NOT NULL + AuditMixin
  - accuracy_metric, confidence, z_score: Numeric only — never float
  - JSONB for feature_schema, prediction_value, features_snapshot
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
# MLModel
# ---------------------------------------------------------------------------

class MLModel(AuditMixin, Model):
	"""Registry entry for a trained machine learning model.

	artifact_path: path or URI to the serialised model (S3, GCS, local FS).
	feature_schema JSONB: describes input features:
	  {"feature_name": {"dtype": "float", "description": "..."}}
	accuracy_metric NUMERIC(5,4): primary accuracy measure (0.0000–1.0000).
	  The metric semantics depend on model_type (accuracy, RMSE, silhouette, F1…).

	status lifecycle: TRAINING → DEPLOYED → RETIRED
	Only one model per (tenant_id, model_name) should be DEPLOYED at a time;
	enforced in the service layer, not via DB constraint (allows blue/green swap).
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_ml_model"
	__table_args__ = (
		UniqueConstraint("tenant_id", "model_name", "version", name="uq_analytics_ml_model_name_ver"),
		Index("ix_analytics_ml_model_tenant", "tenant_id"),
		Index("ix_analytics_ml_model_type", "model_type"),
		Index("ix_analytics_ml_model_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	model_name = Column(String(200), nullable=False)
	model_type = Column(
		String(20),
		nullable=False,
		comment="CLASSIFICATION | REGRESSION | CLUSTERING | NLP",
	)
	framework = Column(
		String(20),
		nullable=False,
		comment="SKLEARN | PYTORCH | TENSORFLOW | ANTHROPIC",
	)
	version = Column(String(20), nullable=False, default="1.0.0")
	artifact_path = Column(
		Text,
		nullable=True,
		comment="URI to serialised model artifact (S3 / GCS / local)",
	)
	feature_schema: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment='{"feature_name": {"dtype": "float", "description": "..."}}',
	)
	target_variable = Column(
		String(200),
		nullable=True,
		comment="Output variable name for supervised models",
	)
	accuracy_metric = Column(
		Numeric(5, 4),
		nullable=True,
		comment="Primary accuracy score 0.0000–1.0000 (model-type dependent)",
	)
	trained_at = Column(DateTime(timezone=True), nullable=True)
	deployed_at = Column(DateTime(timezone=True), nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="TRAINING",
		comment="TRAINING | DEPLOYED | RETIRED",
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

	predictions: list[ModelPrediction] = sa.orm.relationship(
		"ModelPrediction",
		back_populates="model",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<MLModel {self.model_name!r} v{self.version!r} "
			f"type={self.model_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ModelPrediction
# ---------------------------------------------------------------------------

class ModelPrediction(Model):
	"""Single prediction output from a deployed MLModel.

	entity_type + entity_id: polymorphic reference to the entity being predicted
	  (e.g. entity_type="Party", entity_id="<uuid>").

	prediction_value JSONB: raw model output — structure depends on model_type:
	  CLASSIFICATION: {"label": "CHURN", "probabilities": {"CHURN": 0.82, "RETAIN": 0.18}}
	  REGRESSION:     {"value": 4250.00}
	  CLUSTERING:     {"cluster_id": 3, "distance": 0.12}

	features_snapshot JSONB: the feature vector used at prediction time (for
	  explainability and drift detection).

	Immutable: do NOT update existing rows. Re-run the model to get a new prediction.
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_model_prediction"
	__table_args__ = (
		Index("ix_analytics_pred_model", "model_id"),
		Index("ix_analytics_pred_entity", "entity_type", "entity_id"),
		Index("ix_analytics_pred_predicted_at", "predicted_at", postgresql_using="brin"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	model_id = Column(
		UUID(as_uuid=False),
		ForeignKey("analytics_ml_model.id", ondelete="CASCADE"),
		nullable=False,
	)
	entity_type = Column(String(100), nullable=False)
	entity_id = Column(String(64), nullable=False)
	prediction_value: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Raw model output; structure depends on model_type",
	)
	confidence = Column(
		Numeric(5, 4),
		nullable=True,
		comment="Top-class confidence or prediction interval coverage 0–1",
	)
	predicted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	features_snapshot: dict[str, Any] = Column(
		JSONB,
		nullable=True,
		comment="Feature vector used at inference time",
	)

	model: MLModel = sa.orm.relationship(
		"MLModel",
		back_populates="predictions",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ModelPrediction {self.id!r} model={self.model_id!r} "
			f"entity={self.entity_type!r}/{self.entity_id!r}>"
		)


# ---------------------------------------------------------------------------
# AnomalyDetection
# ---------------------------------------------------------------------------

class AnomalyDetection(AuditMixin, Model):
	"""Detected anomaly in a monitored metric.

	z_score: number of standard deviations from the rolling mean.
	severity is derived from |z_score|:
	  LOW < 2 | MEDIUM < 3 | HIGH < 4 | CRITICAL >= 4
	  (service layer computes this; stored for fast filtering)

	acknowledged_by / resolution_notes: manual triage workflow.
	Immutable insert pattern: insert new row rather than updating to correct.
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_anomaly"
	__table_args__ = (
		Index("ix_analytics_anomaly_metric", "metric_name"),
		Index("ix_analytics_anomaly_detected_at", "detected_at", postgresql_using="brin"),
		Index("ix_analytics_anomaly_severity", "severity"),
		Index("ix_analytics_anomaly_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	metric_name = Column(
		String(200),
		nullable=False,
		comment="Dotted metric key e.g. sales.revenue.daily",
	)
	detected_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	expected_value = Column(Numeric(20, 4), nullable=False)
	actual_value = Column(Numeric(20, 4), nullable=False)
	z_score = Column(
		Numeric(7, 3),
		nullable=False,
		comment="Signed z-score; |z|>=2 triggers LOW severity",
	)
	severity = Column(
		String(20),
		nullable=False,
		default="LOW",
		comment="LOW | MEDIUM | HIGH | CRITICAL",
	)
	acknowledged_by = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)
	acknowledged_at = Column(DateTime(timezone=True), nullable=True)
	resolution_notes = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<AnomalyDetection {self.id!r} metric={self.metric_name!r} "
			f"z={self.z_score!r} sev={self.severity!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"MLModel",
	"ModelPrediction",
	"AnomalyDetection",
]
