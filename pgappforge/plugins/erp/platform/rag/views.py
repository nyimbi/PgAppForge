"""
pgappforge/plugins/erp/platform/rag/views.py

Flask-AppBuilder views for the RAG plugin.

Views
-----
  RAGDocumentView    — ModelView CRUD for RAGDocument records.
  RAGDashboardView   — Live stats dashboard + POST /platform/rag/ask endpoint.
"""
from __future__ import annotations

import logging

from flask import jsonify, render_template, request
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPModelView, BaseERPView
from pgappforge.plugins.erp.platform.rag.models import RAGDocument

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document list view
# ---------------------------------------------------------------------------

class RAGDocumentView(BaseERPModelView):
	"""CRUD view for documents indexed in the RAG knowledge base."""

	datamodel = SQLAInterface(RAGDocument)

	list_title  = "RAG Documents"
	show_title  = "Document"
	add_title   = "Index Document"
	edit_title  = "Edit Document"

	list_columns = [
		"title",
		"source_type",
		"chunk_count",
		"indexed_at",
		"is_active",
	]
	show_columns = [
		"title",
		"source_type",
		"source_id",
		"content",
		"language",
		"metadata",
		"chunk_count",
		"indexed_at",
		"is_active",
		"created_at",
		"updated_at",
	]
	add_columns = [
		"title",
		"source_type",
		"source_id",
		"content",
		"language",
		"metadata",
		"is_active",
	]
	edit_columns = [
		"title",
		"source_type",
		"source_id",
		"language",
		"metadata",
		"is_active",
	]

	search_columns = ["title", "source_type", "source_id", "language"]
	label_columns = {
		"source_type":  "Source Type",
		"source_id":    "Source ID",
		"chunk_count":  "Chunks",
		"indexed_at":   "Indexed At",
		"is_active":    "Active",
		"created_at":   "Created",
		"updated_at":   "Updated",
	}


# ---------------------------------------------------------------------------
# Dashboard + ask endpoint
# ---------------------------------------------------------------------------

class RAGDashboardView(BaseERPView):
	"""Live RAG stats dashboard and question-answering endpoint.

	GET  /platform/rag/         — stats dashboard page
	POST /platform/rag/ask      — JSON Q&A endpoint
	"""

	route_base = "/platform/rag"

	@expose("/")
	@has_access
	def index(self):
		"""Render the RAG index stats dashboard."""
		try:
			from pgappforge.plugins.erp.platform.rag.services import RAGService
			sess      = self._session()
			tenant_id = self._tenant_id()
			stats     = RAGService().get_index_stats(tenant_id, sess)
			doc_count   = stats.get("documents", 0)
			chunk_count = stats.get("chunks", 0)
		except Exception as exc:
			log.debug("RAGDashboardView.index stats failed: %s", exc)
			doc_count = chunk_count = 0

		# Count distinct source types for the third KPI tile
		try:
			import sqlalchemy as sa
			from pgappforge.plugins.erp.platform.rag.models import RAGDocument as _Doc
			source_count = (
				sess.execute(
					sa.select(sa.func.count(sa.distinct(_Doc.source_type))).where(
						_Doc.tenant_id == tenant_id,
						_Doc.is_active.is_(True),
					)
				).scalar_one()
				or 0
			)
		except Exception:
			source_count = 0

		kpi_html = self.kpi_cards([
			{
				"label": "Documents Indexed",
				"value": doc_count,
				"icon":  "fa-file-text-o",
				"color": "#1a56db",
			},
			{
				"label": "Total Chunks",
				"value": chunk_count,
				"icon":  "fa-puzzle-piece",
				"color": "#0e9f6e",
			},
			{
				"label": "Source Types",
				"value": source_count,
				"icon":  "fa-tags",
				"color": "#7e3af2",
			},
		])

		return render_template(
			"platform/rag_dashboard.html",
			kpi_html   = kpi_html,
			appbuilder = self.appbuilder,
		)

	@expose("/ask", methods=["POST"])
	@has_access
	def ask(self):
		"""Answer a natural-language question using the RAG knowledge base.

		Request body (JSON)::

		    {
		        "question":     str,            # required
		        "top_k":        int,            # optional, default 5
		        "source_types": list[str],      # optional filter
		        "system_context": str           # optional extra system prompt
		    }

		Response (JSON)::

		    {
		        "answer":           str,
		        "sources":          [{title, score, excerpt}, ...],
		        "model":            str,
		        "retrieved_chunks": int
		    }
		"""
		from pgappforge.plugins.erp.platform.rag.services import RAGService

		payload = request.get_json(silent=True) or {}
		question = (payload.get("question") or "").strip()

		if not question:
			return jsonify({"error": "question is required"}), 400

		try:
			result = RAGService().ask(
				question       = question,
				tenant_id      = self._tenant_id(),
				session        = self._session(),
				top_k          = int(payload.get("top_k", 5)),
				source_types   = payload.get("source_types") or None,
				system_context = payload.get("system_context", ""),
			)
			return jsonify(result)
		except Exception as exc:
			log.exception("RAGDashboardView.ask unhandled error")
			return jsonify({"error": str(exc)}), 500


__all__ = [
	"RAGDocumentView",
	"RAGDashboardView",
]
