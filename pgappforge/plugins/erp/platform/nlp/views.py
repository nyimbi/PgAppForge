"""
pgappforge/plugins/erp/platform/nlp/views.py

Flask-AppBuilder views for the NLP plugin.

NLPAnalysisResultView  — paginated list of persisted analysis results.
NLPDashboardView       — usage statistics and live API test panel.
"""
from __future__ import annotations

import logging

from flask import render_template, request, jsonify
from pgappforge import expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPModelView, BaseERPView
from pgappforge.plugins.erp.platform.nlp.models import NLPAnalysisResult

log = logging.getLogger(__name__)


class NLPAnalysisResultView(BaseERPModelView):
	"""Read-only list of persisted NLP analysis results."""

	datamodel = SQLAInterface(NLPAnalysisResult)

	list_title = "NLP Analysis Results"
	list_columns = [
		"analysis_type",
		"reference_type",
		"reference_id",
		"source",
		"model_used",
		"latency_ms",
		"created_at",
	]
	show_columns = [
		"tenant_id",
		"analysis_type",
		"reference_type",
		"reference_id",
		"input_text_hash",
		"result",
		"model_used",
		"latency_ms",
		"source",
		"created_at",
	]
	label_columns = {
		"tenant_id": "Tenant",
		"analysis_type": "Analysis Type",
		"reference_type": "Reference Type",
		"reference_id": "Reference ID",
		"input_text_hash": "Input Hash",
		"result": "Result",
		"model_used": "Model Used",
		"latency_ms": "Latency ms",
		"source": "Source",
		"created_at": "Created",
	}
	search_columns = ["analysis_type", "reference_type", "reference_id", "source"]
	order_columns = ["created_at", "analysis_type"]

	add_exclude_columns = list(BaseERPModelView._AUDIT) + ["result", "input_text_hash"]
	edit_exclude_columns = list(BaseERPModelView._AUDIT) + ["result", "input_text_hash"]


class NLPDashboardView(BaseERPView):
	"""NLP usage dashboard with live API test panel."""

	route_base = "/platform/nlp"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.platform.nlp.services import NLPService
		sess = self._session()

		# KPI stats
		total = self._count(NLPAnalysisResult, session=sess)
		llm_hits = self._count(NLPAnalysisResult, session=sess, source="llm")
		cache_hits = self._count(NLPAnalysisResult, session=sess, source="cache")
		fallbacks = self._count(NLPAnalysisResult, session=sess, source="fallback")

		# Per-type breakdown
		type_counts: list[dict] = []
		try:
			import sqlalchemy as sa
			rows = sess.execute(
				sa.select(
					NLPAnalysisResult.analysis_type,
					sa.func.count().label("n"),
				).group_by(NLPAnalysisResult.analysis_type)
			).all()
			type_counts = [{"label": r.analysis_type, "value": r.n} for r in rows]
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{
				"label": "Total Analyses",
				"value": total,
				"icon": "fa-brain",
				"color": "#1a56db",
			},
			{
				"label": "LLM Hits",
				"value": llm_hits,
				"icon": "fa-bolt",
				"color": "#0e9f6e",
			},
			{
				"label": "Cache Hits",
				"value": cache_hits,
				"icon": "fa-database",
				"color": "#7e3af2",
			},
			{
				"label": "Fallbacks",
				"value": fallbacks,
				"icon": "fa-exclamation-circle",
				"color": "#e3a008",
			},
		])

		chart_html = self.chart(
			rows=type_counts,
			chart_type="doughnut",
			x_col="label",
			y_col="value",
			title="Analyses by Type",
		) if type_counts else ""

		return render_template(
			"platform/nlp_dashboard.html",
			kpi_html=kpi_html,
			chart_html=chart_html,
			appbuilder=self.appbuilder,
		)

	@expose("/test", methods=["GET"])
	@has_access
	def test_panel(self):
		"""Render the live NLP API test panel."""
		return render_template(
			"platform/nlp_test_panel.html",
			appbuilder=self.appbuilder,
		)

	@expose("/api/classify", methods=["POST"])
	@has_access
	def api_classify(self):
		"""Test endpoint: classify text.

		JSON body: {text, categories: [...], context?}
		"""
		from pgappforge.plugins.erp.platform.nlp.services import NLPService
		body = request.get_json(force=True) or {}
		text = body.get("text", "")
		categories = body.get("categories", ["POSITIVE", "NEGATIVE", "NEUTRAL"])
		context = body.get("context", "")
		if not text:
			return jsonify({"error": "text is required"}), 400
		result = NLPService().classify_text(text, categories, context=context)
		return jsonify(result)

	@expose("/api/sentiment", methods=["POST"])
	@has_access
	def api_sentiment(self):
		"""Test endpoint: sentiment analysis.

		JSON body: {text}
		"""
		from pgappforge.plugins.erp.platform.nlp.services import NLPService
		body = request.get_json(force=True) or {}
		text = body.get("text", "")
		if not text:
			return jsonify({"error": "text is required"}), 400
		result = NLPService().analyze_sentiment(text)
		return jsonify(result)

	@expose("/api/entities", methods=["POST"])
	@has_access
	def api_entities(self):
		"""Test endpoint: named entity extraction.

		JSON body: {text}
		"""
		from pgappforge.plugins.erp.platform.nlp.services import NLPService
		body = request.get_json(force=True) or {}
		text = body.get("text", "")
		if not text:
			return jsonify({"error": "text is required"}), 400
		result = NLPService().extract_entities(text)
		return jsonify(result)

	@expose("/api/summarize", methods=["POST"])
	@has_access
	def api_summarize(self):
		"""Test endpoint: text summarization.

		JSON body: {text, style?, max_sentences?}
		"""
		from pgappforge.plugins.erp.platform.nlp.services import NLPService
		body = request.get_json(force=True) or {}
		text = body.get("text", "")
		if not text:
			return jsonify({"error": "text is required"}), 400
		summary = NLPService().summarize(
			text,
			style=body.get("style", "executive"),
			max_sentences=int(body.get("max_sentences", 3)),
		)
		return jsonify({"summary": summary})

	@expose("/api/detect_language", methods=["POST"])
	@has_access
	def api_detect_language(self):
		"""Test endpoint: language detection.

		JSON body: {text}
		"""
		from pgappforge.plugins.erp.platform.nlp.services import NLPService
		body = request.get_json(force=True) or {}
		text = body.get("text", "")
		if not text:
			return jsonify({"error": "text is required"}), 400
		result = NLPService().detect_language(text)
		return jsonify(result)


__all__ = ["NLPAnalysisResultView", "NLPDashboardView"]
