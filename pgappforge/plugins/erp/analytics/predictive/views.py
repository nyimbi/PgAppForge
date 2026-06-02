"""
pgappforge/plugins/erp/analytics/predictive/views.py

Flask views for the Predictive Analytics plugin.

Route summary
-------------
MLModelView           /analytics/ml-models/
  ├─ GET  /                    — model registry (HTML)
  ├─ POST /                    — register model (JSON)
  ├─ POST /<id>/deploy         — deploy model (JSON)
  └─ POST /<id>/retire         — retire model (JSON)
ModelPredictionView   /analytics/predictions/
  ├─ GET  /entity/<type>/<id>  — predictions for entity (JSON)
  └─ POST /                    — record prediction (JSON)
AnomalyView           /analytics/anomalies/
  ├─ GET  /                    — anomaly list (HTML, last 7 days CRITICAL+HIGH)
  ├─ GET  /report              — anomaly severity report (HTML)
  └─ POST /<id>/acknowledge    — acknowledge anomaly (JSON)
"""
from __future__ import annotations

import logging
from decimal import Decimal

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


# ---------------------------------------------------------------------------
# MLModelView
# ---------------------------------------------------------------------------

class MLModelView(BaseView):
	route_base = "/analytics/ml-models"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.predictive.models import MLModel
		rows = session.execute(
			sa.select(MLModel).order_by(MLModel.model_name, MLModel.version.desc())
		).scalars().all()
		badge = {"TRAINING": "info", "DEPLOYED": "success", "RETIRED": "secondary"}
		items = [
			f"<tr><td>{_he(r.model_name)}</td><td>{_he(r.version)}</td>"
			f"<td>{_he(r.model_type)}</td><td>{_he(r.framework)}</td>"
			f"<td>{_he(r.accuracy_metric or '—')}</td>"
			f"<td><span class='badge badge-{badge.get(r.status, 'light')}'>{_he(r.status)}</span></td>"
			f"<td>{_he(r.deployed_at or '—')}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>ML Model Registry</h2>"
			"<table><thead><tr><th>Name</th><th>Version</th><th>Type</th>"
			"<th>Framework</th><th>Accuracy</th><th>Status</th><th>Deployed</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.predictive.models import MLModel
		model = MLModel(
			tenant_id=data["tenant_id"],
			model_name=data["model_name"],
			model_type=data["model_type"],
			framework=data["framework"],
			version=data.get("version", "1.0.0"),
			artifact_path=data.get("artifact_path"),
			feature_schema=data.get("feature_schema", {}),
			target_variable=data.get("target_variable"),
			accuracy_metric=data.get("accuracy_metric"),
			status="TRAINING",
		)
		session.add(model)
		session.commit()
		return jsonify({"id": model.id, "model_name": model.model_name}), 201

	@expose("/<string:model_id>/deploy", methods=["POST"])
	@has_access
	def deploy(self, model_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.predictive.services import (
			InvalidModelTransitionError,
			MLModelNotFoundError,
			PredictiveAnalyticsService,
		)
		try:
			model = PredictiveAnalyticsService.deploy_model(model_id, session)
			session.commit()
			return jsonify({"id": model.id, "status": model.status, "deployed_at": model.deployed_at.isoformat()})
		except MLModelNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404
		except InvalidModelTransitionError as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:model_id>/retire", methods=["POST"])
	@has_access
	def retire(self, model_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.predictive.services import (
			InvalidModelTransitionError,
			MLModelNotFoundError,
			PredictiveAnalyticsService,
		)
		try:
			model = PredictiveAnalyticsService.retire_model(model_id, session)
			session.commit()
			return jsonify({"id": model.id, "status": model.status})
		except MLModelNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404
		except InvalidModelTransitionError as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ModelPredictionView
# ---------------------------------------------------------------------------

class ModelPredictionView(BaseView):
	route_base = "/analytics/predictions"
	default_view = "list_by_entity"

	@expose("/entity/<string:entity_type>/<string:entity_id>", methods=["GET"])
	@has_access
	def list_by_entity(self, entity_type: str, entity_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.predictive.models import ModelPrediction
		rows = session.execute(
			sa.select(ModelPrediction)
			.where(ModelPrediction.entity_type == entity_type)
			.where(ModelPrediction.entity_id == entity_id)
			.order_by(ModelPrediction.predicted_at.desc())
			.limit(50)
		).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"model_id": r.model_id,
				"prediction_value": r.prediction_value,
				"confidence": str(r.confidence) if r.confidence is not None else None,
				"predicted_at": r.predicted_at.isoformat(),
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def record(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.predictive.services import (
			MLModelNotDeployedError,
			MLModelNotFoundError,
			PredictiveAnalyticsService,
		)
		try:
			pred = PredictiveAnalyticsService.record_prediction(
				model_id=data["model_id"],
				entity_type=data["entity_type"],
				entity_id=data["entity_id"],
				prediction_value=data["prediction_value"],
				session=session,
				confidence=Decimal(str(data["confidence"])) if data.get("confidence") else None,
				features_snapshot=data.get("features_snapshot"),
			)
			session.commit()
			return jsonify({"id": pred.id}), 201
		except (MLModelNotFoundError, MLModelNotDeployedError) as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# AnomalyView  (with anomaly severity report)
# ---------------------------------------------------------------------------

class AnomalyView(BaseView):
	route_base = "/analytics/anomalies"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		"""List recent HIGH and CRITICAL anomalies (last 7 days)."""
		session = _get_session()
		from datetime import datetime, timedelta, timezone
		from pgappforge.plugins.erp.analytics.predictive.models import AnomalyDetection
		cutoff = datetime.now(timezone.utc) - timedelta(days=7)
		rows = session.execute(
			sa.select(AnomalyDetection)
			.where(AnomalyDetection.detected_at >= cutoff)
			.where(AnomalyDetection.severity.in_(["HIGH", "CRITICAL"]))
			.order_by(AnomalyDetection.detected_at.desc())
		).scalars().all()
		sev_badge = {"LOW": "info", "MEDIUM": "warning", "HIGH": "danger", "CRITICAL": "dark"}
		items = [
			f"<tr><td>{_he(r.metric_name)}</td>"
			f"<td>{_he(r.detected_at.strftime('%Y-%m-%d %H:%M'))}</td>"
			f"<td>{_he(r.actual_value)}</td><td>{_he(r.expected_value)}</td>"
			f"<td>{_he(r.z_score)}</td>"
			f"<td><span class='badge badge-{sev_badge.get(r.severity, 'light')}'>"
			f"{_he(r.severity)}</span></td>"
			f"<td>{'Acknowledged' if r.acknowledged_by else 'Open'}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Recent Anomalies (HIGH + CRITICAL, last 7 days)</h2>"
			"<table><thead><tr><th>Metric</th><th>Detected At</th><th>Actual</th>"
			"<th>Expected</th><th>Z-Score</th><th>Severity</th><th>Status</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/report", methods=["GET"])
	@has_access
	def report(self):
		"""Anomaly severity distribution report — counts by severity and metric."""
		session = _get_session()
		from pgappforge.plugins.erp.analytics.predictive.models import AnomalyDetection
		rows = session.execute(
			sa.select(
				AnomalyDetection.severity,
				AnomalyDetection.metric_name,
				sa.func.count().label("cnt"),
			)
			.group_by(AnomalyDetection.severity, AnomalyDetection.metric_name)
			.order_by(AnomalyDetection.severity, sa.func.count().desc())
		).all()
		items = [
			f"<tr><td>{_he(r.severity)}</td><td>{_he(r.metric_name)}</td><td>{_he(r.cnt)}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Anomaly Severity Report</h2>"
			"<table><thead><tr><th>Severity</th><th>Metric</th><th>Count</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/<string:anomaly_id>/acknowledge", methods=["POST"])
	@has_access
	def acknowledge(self, anomaly_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from flask_login import current_user
		from pgappforge.plugins.erp.analytics.predictive.services import (
			AnomalyNotFoundError,
			PredictiveAnalyticsService,
		)
		try:
			user_id = getattr(current_user, "id", data.get("user_id", 0))
			anomaly = PredictiveAnalyticsService.acknowledge_anomaly(
				anomaly_id, user_id, data.get("notes", ""), session
			)
			session.commit()
			return jsonify({"id": anomaly.id, "acknowledged_by": anomaly.acknowledged_by})
		except AnomalyNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404


__all__ = [
	"MLModelView",
	"ModelPredictionView",
	"AnomalyView",
]
