"""
pgappforge/plugins/erp/analytics/predictive/events.py

Domain events for the Predictive Analytics plugin.

Events emitted
--------------
  analytics.ml_model.deployed      — model status changed to DEPLOYED
  analytics.ml_model.retired       — model status changed to RETIRED
  analytics.prediction.created     — new ModelPrediction inserted
  analytics.anomaly.detected       — new AnomalyDetection inserted
  analytics.anomaly.acknowledged   — anomaly acknowledged by a user
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


@dataclass
class MLModelDeployedEvent(DomainEvent):
	event_type: str = "analytics.ml_model.deployed"
	model_id: str = ""
	model_name: str = ""
	version: str = ""
	framework: str = ""


@dataclass
class MLModelRetiredEvent(DomainEvent):
	event_type: str = "analytics.ml_model.retired"
	model_id: str = ""
	model_name: str = ""
	version: str = ""


@dataclass
class ModelPredictionCreatedEvent(DomainEvent):
	event_type: str = "analytics.prediction.created"
	prediction_id: str = ""
	model_id: str = ""
	entity_type: str = ""
	entity_id: str = ""
	confidence: str = ""   # Decimal as string


@dataclass
class AnomalyDetectedEvent(DomainEvent):
	event_type: str = "analytics.anomaly.detected"
	anomaly_id: str = ""
	metric_name: str = ""
	severity: str = ""
	z_score: str = ""    # Decimal as string
	actual_value: str = ""
	expected_value: str = ""


@dataclass
class AnomalyAcknowledgedEvent(DomainEvent):
	event_type: str = "analytics.anomaly.acknowledged"
	anomaly_id: str = ""
	metric_name: str = ""
	acknowledged_by_id: int = 0


__all__ = [
	"MLModelDeployedEvent",
	"MLModelRetiredEvent",
	"ModelPredictionCreatedEvent",
	"AnomalyDetectedEvent",
	"AnomalyAcknowledgedEvent",
	"emit_event",
]
