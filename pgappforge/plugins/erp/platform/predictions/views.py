"""
pgappforge/plugins/erp/platform/predictions/views.py

PredictionsDashboardView — metrics dashboard + JSON API for inline list-view
prediction badges.

Routes
------
GET  /platform/predictions/           — prediction metrics dashboard
GET  /platform/predictions/api/predict — single-record prediction JSON
     ?type=credit_score|duplicate_invoice|lead_score&id=<record_id>
POST /platform/predictions/api/bulk   — bulk predictions for a page of records
     {"type": "...", "ids": [...], "tenant_id": "..."}
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import render_template, request, jsonify
from pgappforge.baseviews import expose
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)

# Prediction type → friendly name map used in the dashboard
_TYPE_LABELS: dict[str, str] = {
	"HR_ATTRITION":    "Credit Score (SACCO Loan)",
	"AP_DUPLICATE":    "Invoice Duplicate Risk",
	"LEAD_SCORE":      "CRM Lead Score",
	"GL_ANOMALY":      "GL Anomaly",
	"DEMAND_FORECAST": "Demand Forecast",
}


class PredictionsDashboardView(BaseERPView):
	"""Inline-prediction metrics dashboard + JSON API.

	The dashboard shows aggregate statistics by prediction type and label.
	The /api/predict and /api/bulk endpoints are consumed by list-view islands
	to render prediction badge columns without page reloads.
	"""

	route_base = "/platform/predictions"

	# ------------------------------------------------------------------
	# Dashboard
	# ------------------------------------------------------------------

	@expose("/")
	@has_access
	def index(self):
		"""Prediction metrics dashboard — counts by type and label."""
		from pgappforge.plugins.erp.platform.ml_predictions.models import MLPrediction

		sess  = self._session()
		total = self._count(MLPrediction, session=sess)

		# Counts per prediction type
		type_counts: list[dict] = []
		label_counts: list[dict] = []
		recent_high: list[dict] = []

		try:
			rows = sess.execute(
				sa.select(
					MLPrediction.prediction_type,
					sa.func.count().label("n"),
				).group_by(MLPrediction.prediction_type)
			).all()
			type_counts = [
				{
					"label": _TYPE_LABELS.get(r.prediction_type, r.prediction_type),
					"value": r.n,
				}
				for r in rows
			]
		except Exception:
			pass

		try:
			rows2 = sess.execute(
				sa.select(
					MLPrediction.label,
					sa.func.count().label("n"),
				).where(MLPrediction.label.isnot(None))
				.group_by(MLPrediction.label)
			).all()
			label_counts = [{"label": r.label, "value": r.n} for r in rows2]
		except Exception:
			pass

		# Most recent HIGH-risk or DUPLICATE records
		try:
			recent_rows = sess.execute(
				sa.select(MLPrediction).where(
					MLPrediction.label.in_(["HIGH", "DUPLICATE", "ANOMALY"])
				).order_by(MLPrediction.created_at.desc()).limit(10)
			).scalars().all()
			for r in recent_rows:
				recent_high.append({
					"type":         _TYPE_LABELS.get(r.prediction_type, r.prediction_type),
					"reference_id": r.reference_id,
					"label":        r.label,
					"score_pct":    int(float(r.score or 0) * 100),
					"created_at":   str(r.created_at)[:16] if r.created_at else "—",
				})
		except Exception:
			pass

		high_risk  = self._count(MLPrediction, session=sess, label="HIGH")
		duplicates = self._count(MLPrediction, session=sess, label="DUPLICATE")
		anomalies  = self._count(MLPrediction, session=sess, label="ANOMALY")

		kpi_html = self.kpi_cards([
			{
				"label": "Total Predictions",
				"value": total,
				"icon":  "fa-brain",
				"color": "#1a56db",
			},
			{
				"label": "High Risk",
				"value": high_risk,
				"icon":  "fa-exclamation-triangle",
				"color": "#e02424",
			},
			{
				"label": "Duplicate Invoices",
				"value": duplicates,
				"icon":  "fa-copy",
				"color": "#e3a008",
			},
			{
				"label": "GL Anomalies",
				"value": anomalies,
				"icon":  "fa-bolt",
				"color": "#ff5a1f",
			},
		])

		type_chart_html = self.chart(
			rows=type_counts,
			chart_type="doughnut",
			x_col="label",
			y_col="value",
			title="Predictions by Type",
		) if type_counts else ""

		label_chart_html = self.chart(
			rows=label_counts,
			chart_type="bar",
			x_col="label",
			y_col="value",
			title="Predictions by Label",
		) if label_counts else ""

		return render_template(
			"platform/predictions_dashboard.html",
			kpi_html=kpi_html,
			type_chart_html=type_chart_html,
			label_chart_html=label_chart_html,
			recent_high=recent_high,
			total=total,
			appbuilder=self.appbuilder,
		)

	# ------------------------------------------------------------------
	# API — single-record prediction
	# ------------------------------------------------------------------

	@expose("/api/predict")
	@has_access
	def api_predict(self):
		"""Return a prediction badge for a single record.

		Query params
		------------
		type : str
		    Prediction type. One of ``credit_score`` | ``duplicate_invoice``
		    | ``lead_score``.
		id   : str
		    Primary-key string of the target record.

		Response
		--------
		JSON: ``{score_pct, label, color, tooltip, from_cache}``
		"""
		from pgappforge.plugins.erp.platform.predictions.services import PredictionService

		pred_type = request.args.get("type", "").strip()
		record_id = request.args.get("id", "").strip()

		if not pred_type or not record_id:
			return jsonify({"error": "type and id query params are required"}), 400

		sess      = self._session()
		tenant_id = self._tenant_id()
		svc       = PredictionService()

		if pred_type == "credit_score":
			result = svc.predict_loan_credit_score(record_id, tenant_id, sess)
		elif pred_type == "duplicate_invoice":
			result = svc.predict_invoice_duplicate_risk(record_id, tenant_id, sess)
		elif pred_type == "lead_score":
			result = svc.predict_lead_score(record_id, tenant_id, sess)
		else:
			return jsonify({"error": f"Unknown prediction type: {pred_type!r}"}), 400

		return jsonify(result)

	# ------------------------------------------------------------------
	# API — bulk predictions for a list-view page
	# ------------------------------------------------------------------

	@expose("/api/bulk", methods=["POST"])
	@has_access
	def api_bulk(self):
		"""Return predictions for multiple records (list-view pre-load).

		Request JSON
		------------
		::

			{
				"type":      "credit_score",
				"ids":       ["id1", "id2", ...],
				"tenant_id": "..."     // optional; defaults to app tenant
			}

		Response JSON
		-------------
		::

			{
				"results": {
					"id1": {score_pct, label, color, tooltip, from_cache},
					"id2": {...},
					...
				}
			}
		"""
		from pgappforge.plugins.erp.platform.predictions.services import PredictionService

		body      = request.get_json(force=True) or {}
		pred_type = body.get("type", "").strip()
		ids       = body.get("ids") or []
		tenant_id = body.get("tenant_id") or self._tenant_id()

		if not pred_type:
			return jsonify({"error": "type is required"}), 400
		if not isinstance(ids, list):
			return jsonify({"error": "ids must be a list"}), 400

		sess    = self._session()
		results = PredictionService().get_bulk_predictions(pred_type, ids, tenant_id, sess)
		return jsonify({"results": results})


__all__ = ["PredictionsDashboardView"]
