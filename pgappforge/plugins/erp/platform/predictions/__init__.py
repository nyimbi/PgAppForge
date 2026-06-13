"""
pgappforge/plugins/erp/platform/predictions/__init__.py

Predictions plugin — ML-powered inline prediction columns for ERP list views.

Wraps MLPredictionService results into display-ready badge dicts
(score_pct, label, color, tooltip) consumed by list-view islands.

Prediction types
----------------
credit_score        — SACCO loan application credit score (reuses HR attrition scoring)
duplicate_invoice   — AP invoice duplicate detection (embedding similarity)
lead_score          — CRM opportunity close probability

The plugin exposes:
- PredictionsDashboardView at /platform/predictions/
- GET  /platform/predictions/api/predict   (single-record badge)
- POST /platform/predictions/api/bulk      (list-view pre-load)

Depends on: foundation, ml_predictions
"""
from __future__ import annotations

import logging

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .services import PredictionService
from .views import PredictionsDashboardView

log = logging.getLogger(__name__)

_MENU_CATEGORY = "Analytics"


class PredictionsPlugin(BasePlugin):
	"""Inline ML prediction columns plugin."""

	name	   = "predictions"
	domain	   = "platform"
	depends_on: list[str] = ["foundation", "ml_predictions"]

	metadata = PluginMetadata(
		name="predictions",
		version="1.0.0",
		description=(
			"ML-powered inline prediction columns: SACCO credit score, "
			"AP duplicate risk, CRM lead score. Displayed as colour-coded "
			"badges directly in ERP list views."
		),
		author="PgAppForge Contributors",
		tags=["platform", "ml", "predictions", "inline", "credit", "sacco"],
		priority=PluginPriority.NORMAL,
	)

	def get_events(self) -> list[str]:
		return [
			"predictions.credit_score.computed",
			"predictions.duplicate_invoice.flagged",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self, app=None) -> None:
		log.info("PredictionsPlugin initialised")

	def register_views(self) -> None:
		cat = self.config.get("PREDICTIONS_MENU_CATEGORY", _MENU_CATEGORY)
		self.add_view(
			PredictionsDashboardView,
			"Predictions",
			icon="fa-magic",
			category=cat,
		)
		log.info("PredictionsPlugin: views registered under %r", cat)

	def register_models(self) -> list[type]:
		# Reuses plat_ml_prediction — no additional model to register.
		return []


__all__ = [
	"PredictionsPlugin",
	"PredictionService",
	"PredictionsDashboardView",
]
