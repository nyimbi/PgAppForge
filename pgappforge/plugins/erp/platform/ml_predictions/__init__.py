"""
pgappforge/plugins/erp/platform/ml_predictions/__init__.py

ML Predictions plugin — five ML-powered predictions wired into the ERP platform:
  • AP duplicate invoice detection  (embedding cosine-similarity)
  • HR attrition risk               (rule-based + LLM explanation)
  • CRM lead scoring                (stage/signal heuristics + LLM action)
  • GL anomaly detection            (z-score)
  • Sales / inventory demand forecast (moving average)
"""
from __future__ import annotations

import logging

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .models import MLModelConfig, MLPrediction
from .services import MLPredictionService

log = logging.getLogger(__name__)

_MENU_CATEGORY = "ML Predictions"

__all__ = [
	"MLPredictionsPlugin",
	"MLPredictionService",
	"MLPrediction",
	"MLModelConfig",
]


class MLPredictionsPlugin(BasePlugin):
	"""ML Predictions platform plugin."""

	name       = "ml_predictions"
	domain     = "platform"
	depends_on: list[str] = ["foundation", "nlp"]

	metadata = PluginMetadata(
		name="ml_predictions",
		version="1.0.0",
		description=(
			"ML predictions: AP duplicate detection, HR attrition, "
			"lead scoring, GL anomaly detection, demand forecasting"
		),
		author="PgAppForge Contributors",
		tags=["platform", "ml", "predictions", "ai", "anomaly", "forecast"],
		priority=PluginPriority.NORMAL,
	)

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self, app=None) -> None:
		log.info("MLPredictionsPlugin initialized")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.ml_predictions.views import (
			MLPredictionsDashboardView,
			MLPredictionView,
		)
		cat = self.config.get("ML_MENU_CATEGORY", _MENU_CATEGORY)
		self.add_view(
			MLPredictionsDashboardView,
			"ML Dashboard",
			icon="fa-brain",
			category=cat,
		)
		self.add_view(
			MLPredictionView,
			"Predictions Log",
			icon="fa-list",
			category=cat,
		)
		log.info("MLPredictionsPlugin: views registered under %r", cat)

	def register_models(self) -> list[type]:
		return [MLPrediction, MLModelConfig]
