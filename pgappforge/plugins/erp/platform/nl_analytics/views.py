"""
pgappforge/plugins/erp/platform/nl_analytics/views.py

NLAnalyticsDashboardView — Flask-AppBuilder view for the NL-to-SQL analytics
interface.

Routes
------
GET  /platform/nl-analytics/          → analytics query interface (HTML)
POST /platform/nl-analytics/api/query → {question, tenant_id} → JSON result
GET  /platform/nl-analytics/schema    → JSON dump of current schema context

Permissions
-----------
  can_ai_query_data  — required for GET / and POST /api/query
  can_view_nl_schema — required for GET /schema

Both decorators are applied; the view degrades gracefully when the NL
analytics service or LLM proxy is unavailable.
"""
from __future__ import annotations

import logging

from flask import jsonify, render_template, request
from pgappforge.baseviews import expose
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class NLAnalyticsDashboardView(BaseERPView):
	"""Natural language analytics query interface.

	Provides a browser-based text input where users type plain-English
	questions.  The server converts them to SQL via LLM, executes the
	query, and streams back a structured result (SQL + tabular rows).

	The interface also surfaces the SQL generated so analysts can review,
	copy, and refine it.
	"""

	route_base = "/platform/nl-analytics"
	default_view = "index"

	# ── GET / ────────────────────────────────────────────────────────

	@expose("/")
	@has_access
	def index(self):
		"""Render the NL analytics query interface."""
		return render_template(
			"appbuilder/platform/nl_analytics.html",
			appbuilder=self.appbuilder,
			title="Natural Language Analytics",
		)

	# ── POST /api/query ──────────────────────────────────────────────

	@expose("/api/query", methods=["POST"])
	@has_access
	def api_query(self):
		"""Execute a natural language analytics query.

		Request body (JSON)::

			{
				"question":  "How many active SACCO members are there?",
				"tenant_id": "default"          // optional
			}

		Response (JSON)::

			{
				"sql":       "SELECT COUNT(*) ...",
				"results":   [{"count": 4218}],
				"columns":   ["count"],
				"row_count": 1,
				"error":     null,
				"cached":    false
			}
		"""
		payload = request.get_json(silent=True) or {}
		question = (payload.get("question") or "").strip()
		tenant_id = (payload.get("tenant_id") or "default").strip()

		if not question:
			return jsonify({"error": "question is required"}), 400

		# Hard cap: question length
		if len(question) > 1000:
			return jsonify({"error": "question must be ≤ 1000 characters"}), 400

		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService
		session = self._session()
		svc = NLAnalyticsService()

		result = svc.query(question, session, tenant_id=tenant_id)
		return jsonify(result)

	# ── GET /schema ──────────────────────────────────────────────────

	@expose("/schema", methods=["GET"])
	@has_access
	def schema(self):
		"""Return the current schema context string as JSON.

		Useful for administrators to verify what the LLM sees.
		"""
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService
		session = self._session()
		svc = NLAnalyticsService()
		ctx = svc.get_schema_context(session)
		return jsonify({"schema_context": ctx, "char_count": len(ctx)})
