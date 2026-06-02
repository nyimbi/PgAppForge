"""
pgappforge/plugins/erp/analytics/predictive/__init__.py

PredictivePlugin — ML model registry, inference, anomaly detection.

Domain: analytics
Depends on: foundation

Events emitted
--------------
  analytics.ml_model.deployed      — model promoted to DEPLOYED
  analytics.ml_model.retired       — model retired
  analytics.prediction.created     — prediction recorded
  analytics.anomaly.detected       — anomaly above z-score threshold
  analytics.anomaly.acknowledged   — anomaly triaged

Events consumed
---------------
  analytics.kpi.status_changed  — trigger anomaly check on KPI status change
  analytics.cdp.profile_computed — run churn prediction on new profile

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.analytics.operational",
        "pgappforge.plugins.erp.analytics.predictive",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PredictivePlugin(BasePlugin):
	"""Predictive Analytics ERP plugin.

	ML model registry with TRAINING→DEPLOYED→RETIRED lifecycle,
	per-entity prediction storage with confidence and feature snapshots,
	and statistical anomaly detection with z-score severity classification.

	Pre-configures 4 Rules Engine rulesets for model governance and anomaly routing.

	Class-level attributes:
	    name       = "analytics.predictive"
	    domain     = "analytics"
	    depends_on = ["foundation"]
	"""

	name = "analytics.predictive"
	domain = "analytics"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="analytics.predictive",
			version="1.0.0",
			description=(
				"Predictive Analytics — ML model registry (SKLEARN/PYTORCH/TENSORFLOW/ANTHROPIC), "
				"per-entity prediction storage, and statistical anomaly detection."
			),
			author="PgAppForge Contributors",
			tags=["erp", "analytics", "ml", "ai", "anomaly", "prediction"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_analytics_ml_model_list",
				"can_analytics_ml_model_write",
				"can_analytics_ml_model_deploy",
				"can_analytics_ml_model_retire",
				"can_analytics_prediction_list",
				"can_analytics_prediction_write",
				"can_analytics_anomaly_list",
				"can_analytics_anomaly_acknowledge",
				"can_analytics_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"analytics.ml_model.deployed",
			"analytics.ml_model.retired",
			"analytics.prediction.created",
			"analytics.anomaly.detected",
			"analytics.anomaly.acknowledged",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"analytics.kpi.status_changed",
			"analytics.cdp.profile_computed",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PREDICTIVE_MENU_CATEGORY": "Analytics",
			"PREDICTIVE_ANOMALY_Z_THRESHOLD": 2.0,
			"PREDICTIVE_ANOMALY_ALERT_SEVERITIES": ["HIGH", "CRITICAL"],
		}
		self.config = {**defaults, **self.config}
		log.info("PredictivePlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		self._subscribe_to_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.analytics.predictive.views import (
			AnomalyView,
			MLModelView,
			ModelPredictionView,
		)
		cat = self.config.get("PREDICTIVE_MENU_CATEGORY", "Analytics")
		self.add_view(MLModelView, "ML Models", icon="fa-brain", category=cat)
		self.add_view(ModelPredictionView, "Predictions", icon="fa-magic", category=cat)
		self.add_view(AnomalyView, "Anomalies", icon="fa-exclamation-triangle", category=cat)
		log.info("PredictivePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.analytics.predictive.models import (
			AnomalyDetection,
			MLModel,
			ModelPrediction,
		)
		return [MLModel, ModelPrediction, AnomalyDetection]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 Rules Engine rulesets for ML governance and anomaly routing."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("PredictivePlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			{
				"name": "analytics.ml_model.require_accuracy_before_deploy",
				"description": "Block deployment if accuracy_metric < 0.60",
				"model_name": "MLModel",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_low_accuracy_deploy",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "DEPLOYED"},
							{"field": "accuracy_metric", "op": "lt", "value": 0.60},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot deploy model with accuracy_metric < 0.60",
							}
						],
					}
				],
			},
			{
				"name": "analytics.ml_model.single_deployed_per_name",
				"description": "Warn when more than one DEPLOYED version of same model_name exists",
				"model_name": "MLModel",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_dual_deployed",
						"trigger_event": "on_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "DEPLOYED"},
							{"field": "_deployed_sibling_count", "op": "gt", "value": 0},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Multiple DEPLOYED versions of the same model detected",
							}
						],
					}
				],
			},
			{
				"name": "analytics.anomaly.escalate_critical",
				"description": "Escalate CRITICAL anomalies to on-call channel",
				"model_name": "AnomalyDetection",
				"stop_on_match": True,
				"rules": [
					{
						"name": "escalate_critical",
						"trigger_event": "on_create",
						"conditions_json": [
							{"field": "severity", "op": "eq", "value": "CRITICAL"},
						],
						"actions_json": [
							{"type": "notify", "channel": "oncall_alerts", "template": "anomaly_critical"},
						],
					}
				],
			},
			{
				"name": "analytics.anomaly.auto_acknowledge_low",
				"description": "Auto-acknowledge LOW severity anomalies after 24 hours",
				"model_name": "AnomalyDetection",
				"stop_on_match": True,
				"rules": [
					{
						"name": "auto_ack_low",
						"trigger_event": "on_read",
						"conditions_json": [
							{"field": "severity", "op": "eq", "value": "LOW"},
							{"field": "acknowledged_by", "op": "is_null", "value": True},
							{"field": "_hours_since_detected", "op": "gte", "value": 24},
						],
						"actions_json": [
							{"type": "set_field", "field": "resolution_notes", "value": "Auto-acknowledged (LOW, 24h)"},
						],
					}
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("PredictivePlugin.setup_rules: %d rulesets configured", len(RULESETS))

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("analytics.kpi.status_changed", self._on_kpi_status_changed)
			subscribe("analytics.cdp.profile_computed", self._on_profile_computed)
			log.debug("PredictivePlugin: subscribed to analytics events")
		except Exception as exc:
			log.warning("PredictivePlugin._subscribe_to_events failed: %s", exc)

	def _on_kpi_status_changed(self, event: Any) -> None:
		log.debug(
			"PredictivePlugin._on_kpi_status_changed: kpi=%s %s→%s",
			getattr(event, "kpi_code", "?"),
			getattr(event, "previous_status", "?"),
			getattr(event, "new_status", "?"),
		)

	def _on_profile_computed(self, event: Any) -> None:
		log.debug(
			"PredictivePlugin._on_profile_computed: party=%s",
			getattr(event, "party_id", "?"),
		)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> PredictivePlugin:
	return PredictivePlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.analytics.predictive.models import (  # noqa: E402
	AnomalyDetection,
	MLModel,
	ModelPrediction,
)
from pgappforge.plugins.erp.analytics.predictive.events import (  # noqa: E402
	AnomalyAcknowledgedEvent,
	AnomalyDetectedEvent,
	MLModelDeployedEvent,
	MLModelRetiredEvent,
	ModelPredictionCreatedEvent,
)
from pgappforge.plugins.erp.analytics.predictive.services import (  # noqa: E402
	AnomalyNotFoundError,
	InvalidModelTransitionError,
	MLModelNotDeployedError,
	MLModelNotFoundError,
	PredictiveAnalyticsError,
	PredictiveAnalyticsService,
)

__all__ = [
	"PredictivePlugin",
	"create_plugin",
	# models
	"MLModel",
	"ModelPrediction",
	"AnomalyDetection",
	# events
	"MLModelDeployedEvent",
	"MLModelRetiredEvent",
	"ModelPredictionCreatedEvent",
	"AnomalyDetectedEvent",
	"AnomalyAcknowledgedEvent",
	# services
	"PredictiveAnalyticsService",
	"PredictiveAnalyticsError",
	"MLModelNotFoundError",
	"MLModelNotDeployedError",
	"AnomalyNotFoundError",
	"InvalidModelTransitionError",
]
