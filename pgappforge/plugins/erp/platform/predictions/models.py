"""
pgappforge/plugins/erp/platform/predictions/models.py

SQLAlchemy models for the Predictions plugin.

PredictionCache — short-lived result cache keyed by (prediction_type, reference_id,
tenant_id).  Results older than 24 hours are considered stale and recomputed.
Backed by plat_ml_prediction (shared with ml_predictions plugin) — no new table
needed.  This module provides the ORM model alias used by PredictionService queries.
"""
from __future__ import annotations

from pgappforge.plugins.erp.platform.ml_predictions.models import (
	MLPrediction as PredictionCache,
	MLModelConfig,
)

__all__ = ["PredictionCache", "MLModelConfig"]
