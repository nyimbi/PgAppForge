"""
pgappforge/plugins/erp/analytics/predictive/services.py

PredictiveAnalyticsService — ML model registry, prediction inference, anomaly detection.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() here — callers own transaction boundaries.

Key methods
-----------
  deploy_model(model_id, session) -> MLModel
      Transitions model status TRAINING→DEPLOYED; retires previous deployed version.

  retire_model(model_id, session) -> MLModel
      Transitions model to RETIRED status.

  record_prediction(model_id, entity_type, entity_id, prediction_value,
                    confidence, features_snapshot, session) -> ModelPrediction
      Inserts a new ModelPrediction row. Model must be DEPLOYED.

  detect_anomaly(metric_name, actual_value, expected_value, std_dev,
                 tenant_id, session) -> AnomalyDetection | None
      Computes z_score, derives severity, inserts row if |z| >= threshold.

  acknowledge_anomaly(anomaly_id, user_id, notes, session) -> AnomalyDetection
      Sets acknowledged_by + acknowledged_at + resolution_notes.

  compute_severity(z_score) -> str
      Pure function: LOW | MEDIUM | HIGH | CRITICAL.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.analytics.predictive.events import (
	AnomalyAcknowledgedEvent,
	AnomalyDetectedEvent,
	MLModelDeployedEvent,
	MLModelRetiredEvent,
	ModelPredictionCreatedEvent,
	emit_event,
)

log = logging.getLogger(__name__)

_ANOMALY_THRESHOLD_Z = Decimal("2.0")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PredictiveAnalyticsError(Exception):
	"""Base error for predictive analytics service layer."""


class MLModelNotFoundError(PredictiveAnalyticsError):
	pass


class MLModelNotDeployedError(PredictiveAnalyticsError):
	pass


class AnomalyNotFoundError(PredictiveAnalyticsError):
	pass


class InvalidModelTransitionError(PredictiveAnalyticsError):
	pass


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PredictiveAnalyticsService:
	"""Stateless service for ML model management and anomaly detection."""

	# ------------------------------------------------------------------
	# Status helpers
	# ------------------------------------------------------------------

	@staticmethod
	def compute_severity(z_score: Decimal) -> str:
		"""Derive severity from absolute z_score value.

		|z| < 2  → LOW
		|z| < 3  → MEDIUM
		|z| < 4  → HIGH
		|z| >= 4 → CRITICAL
		"""
		abs_z = abs(z_score)
		if abs_z < 2:
			return "LOW"
		if abs_z < 3:
			return "MEDIUM"
		if abs_z < 4:
			return "HIGH"
		return "CRITICAL"

	# ------------------------------------------------------------------
	# Model lifecycle
	# ------------------------------------------------------------------

	@staticmethod
	def deploy_model(model_id: str, session: Any) -> Any:
		"""Transition model to DEPLOYED status.

		Retires any currently DEPLOYED model with the same (tenant_id, model_name).
		Only allowed from TRAINING status.
		"""
		from pgappforge.plugins.erp.analytics.predictive.models import MLModel

		model = session.execute(
			sa.select(MLModel).where(MLModel.id == model_id)
		).scalar_one_or_none()
		if model is None:
			raise MLModelNotFoundError(f"MLModel {model_id!r} not found")
		if model.status != "TRAINING":
			raise InvalidModelTransitionError(
				f"Cannot deploy model in status {model.status!r}; must be TRAINING"
			)

		# Retire existing deployed version of same model_name within tenant
		existing_deployed = session.execute(
			sa.select(MLModel).where(
				MLModel.tenant_id == model.tenant_id,
				MLModel.model_name == model.model_name,
				MLModel.status == "DEPLOYED",
				MLModel.id != model_id,
			)
		).scalars().all()
		for prev in existing_deployed:
			prev.status = "RETIRED"
			emit_event(
				MLModelRetiredEvent(
					aggregate_id=prev.id,
					aggregate_type="MLModel",
					tenant_id=prev.tenant_id,
					model_id=prev.id,
					model_name=prev.model_name,
					version=prev.version,
				),
				session,
			)

		model.status = "DEPLOYED"
		model.deployed_at = datetime.now(timezone.utc)

		emit_event(
			MLModelDeployedEvent(
				aggregate_id=model_id,
				aggregate_type="MLModel",
				tenant_id=model.tenant_id,
				model_id=model_id,
				model_name=model.model_name,
				version=model.version,
				framework=model.framework,
			),
			session,
		)
		log.info("deploy_model: model=%s name=%s deployed", model_id, model.model_name)
		return model

	@staticmethod
	def retire_model(model_id: str, session: Any) -> Any:
		"""Transition model to RETIRED. Allowed from TRAINING or DEPLOYED."""
		from pgappforge.plugins.erp.analytics.predictive.models import MLModel

		model = session.execute(
			sa.select(MLModel).where(MLModel.id == model_id)
		).scalar_one_or_none()
		if model is None:
			raise MLModelNotFoundError(f"MLModel {model_id!r} not found")
		if model.status == "RETIRED":
			raise InvalidModelTransitionError("Model is already RETIRED")

		model.status = "RETIRED"
		emit_event(
			MLModelRetiredEvent(
				aggregate_id=model_id,
				aggregate_type="MLModel",
				tenant_id=model.tenant_id,
				model_id=model_id,
				model_name=model.model_name,
				version=model.version,
			),
			session,
		)
		log.info("retire_model: model=%s name=%s retired", model_id, model.model_name)
		return model

	# ------------------------------------------------------------------
	# Predictions
	# ------------------------------------------------------------------

	@staticmethod
	def record_prediction(
		model_id: str,
		entity_type: str,
		entity_id: str,
		prediction_value: dict[str, Any],
		session: Any,
		confidence: Decimal | None = None,
		features_snapshot: dict[str, Any] | None = None,
	) -> Any:
		"""Insert a new ModelPrediction.

		Model must have status=DEPLOYED.
		Returns the new ModelPrediction instance (not yet committed).
		"""
		from pgappforge.plugins.erp.analytics.predictive.models import MLModel, ModelPrediction

		model = session.execute(
			sa.select(MLModel).where(MLModel.id == model_id)
		).scalar_one_or_none()
		if model is None:
			raise MLModelNotFoundError(f"MLModel {model_id!r} not found")
		if model.status != "DEPLOYED":
			raise MLModelNotDeployedError(
				f"MLModel {model.model_name!r} is not DEPLOYED (status={model.status!r})"
			)

		pred = ModelPrediction(
			model_id=model_id,
			entity_type=entity_type,
			entity_id=entity_id,
			prediction_value=prediction_value,
			confidence=confidence,
			features_snapshot=features_snapshot or {},
		)
		session.add(pred)
		session.flush()  # populate pred.id

		emit_event(
			ModelPredictionCreatedEvent(
				aggregate_id=pred.id,
				aggregate_type="ModelPrediction",
				tenant_id=model.tenant_id,
				prediction_id=pred.id,
				model_id=model_id,
				entity_type=entity_type,
				entity_id=entity_id,
				confidence=str(confidence) if confidence is not None else "",
			),
			session,
		)
		return pred

	# ------------------------------------------------------------------
	# Anomaly detection
	# ------------------------------------------------------------------

	@staticmethod
	def detect_anomaly(
		metric_name: str,
		actual_value: Decimal,
		expected_value: Decimal,
		std_dev: Decimal,
		tenant_id: str,
		session: Any,
		threshold_z: Decimal = _ANOMALY_THRESHOLD_Z,
	) -> Any | None:
		"""Compute z_score and insert AnomalyDetection if |z| >= threshold.

		Returns the new AnomalyDetection row, or None if below threshold.
		std_dev must not be zero; callers should handle that case upstream.
		"""
		from pgappforge.plugins.erp.analytics.predictive.models import AnomalyDetection

		if std_dev == 0:
			log.warning("detect_anomaly: std_dev=0 for metric=%s, skipping", metric_name)
			return None

		z_score = (Decimal(str(actual_value)) - Decimal(str(expected_value))) / Decimal(str(std_dev))
		if abs(z_score) < threshold_z:
			return None

		severity = PredictiveAnalyticsService.compute_severity(z_score)

		anomaly = AnomalyDetection(
			tenant_id=tenant_id,
			metric_name=metric_name,
			expected_value=expected_value,
			actual_value=actual_value,
			z_score=z_score,
			severity=severity,
		)
		session.add(anomaly)
		session.flush()

		emit_event(
			AnomalyDetectedEvent(
				aggregate_id=anomaly.id,
				aggregate_type="AnomalyDetection",
				tenant_id=tenant_id,
				anomaly_id=anomaly.id,
				metric_name=metric_name,
				severity=severity,
				z_score=str(z_score),
				actual_value=str(actual_value),
				expected_value=str(expected_value),
			),
			session,
		)
		log.info(
			"detect_anomaly: metric=%s z=%.3f severity=%s",
			metric_name, z_score, severity,
		)
		return anomaly

	@staticmethod
	def acknowledge_anomaly(
		anomaly_id: str,
		user_id: int,
		notes: str,
		session: Any,
	) -> Any:
		"""Mark an anomaly as acknowledged with triage notes."""
		from pgappforge.plugins.erp.analytics.predictive.models import AnomalyDetection

		anomaly = session.execute(
			sa.select(AnomalyDetection).where(AnomalyDetection.id == anomaly_id)
		).scalar_one_or_none()
		if anomaly is None:
			raise AnomalyNotFoundError(f"AnomalyDetection {anomaly_id!r} not found")

		anomaly.acknowledged_by = user_id
		anomaly.acknowledged_at = datetime.now(timezone.utc)
		anomaly.resolution_notes = notes

		emit_event(
			AnomalyAcknowledgedEvent(
				aggregate_id=anomaly_id,
				aggregate_type="AnomalyDetection",
				tenant_id=anomaly.tenant_id,
				anomaly_id=anomaly_id,
				metric_name=anomaly.metric_name,
				acknowledged_by_id=user_id,
			),
			session,
		)
		return anomaly


__all__ = [
	"PredictiveAnalyticsService",
	"PredictiveAnalyticsError",
	"MLModelNotFoundError",
	"MLModelNotDeployedError",
	"AnomalyNotFoundError",
	"InvalidModelTransitionError",
]
