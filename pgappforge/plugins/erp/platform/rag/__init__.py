"""
pgappforge/plugins/erp/platform/rag/__init__.py

RAGPlugin — Retrieval-Augmented Generation for ERP knowledge bases.

Domain:    platform
Depends:   foundation, nlp

Events emitted
--------------
  (none — RAG is a query-time service; ingestion is synchronous)
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class RAGPlugin(BasePlugin):
	"""RAG plugin.

	Provides document ingestion (chunking + embedding via LiteLLM), semantic
	similarity search using cosine distance over JSONB-stored vectors, and a
	grounded Q&A endpoint that answers natural-language questions from ERP
	data.

	The embedding store is PostgreSQL-only (JSONB for portability; can be
	migrated to pgvector VECTOR once the extension is available).
	"""

	name      = "rag"
	domain    = "platform"
	depends_on: list[str] = ["foundation", "nlp"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name        = "rag",
			version     = "1.0.0",
			description = (
				"RAG — document ingestion, chunk embeddings, cosine-similarity "
				"search, and grounded LLM question-answering over ERP data."
			),
			author = "PgAppForge Contributors",
			tags   = [
				"platform", "rag", "embeddings", "nlp", "search",
				"question-answering", "llm", "litellm",
			],
			priority = PluginPriority.NORMAL,
			permissions = [
				"can_rag_document_read",
				"can_rag_document_write",
				"can_rag_document_delete",
				"can_rag_search",
				"can_rag_ask",
				"can_rag_ingest",
				"can_rag_stats",
			],
			safe_mode_compatible = True,
		)

	def get_events(self) -> list[str]:
		# RAG is stateless at the event level; ingestion callers emit their own
		# domain events (e.g. finance.gl.journal.posted).
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"RAG_CHUNK_SIZE":    800,
			"RAG_CHUNK_OVERLAP": 100,
			"RAG_TOP_K":         5,
		}
		self.config = {**defaults, **self.config}
		log.info("RAGPlugin initialised (chunk_size=%d, overlap=%d, top_k=%d)",
			self.config["RAG_CHUNK_SIZE"],
			self.config["RAG_CHUNK_OVERLAP"],
			self.config["RAG_TOP_K"],
		)

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.rag.views import (
			RAGDocumentView,
			RAGDashboardView,
		)
		cat = self.config.get("RAG_MENU_CATEGORY", "AI / RAG")
		self.add_view(
			RAGDashboardView, "RAG Dashboard",
			icon="fa-search", category=cat,
		)
		self.add_view(
			RAGDocumentView, "RAG Documents",
			icon="fa-file-text-o", category=cat,
		)
		log.info("RAGPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.rag.models import RAGDocument, RAGChunk
		return [RAGDocument, RAGChunk]


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> RAGPlugin:
	return RAGPlugin(appbuilder, config=config or {})


# Convenience re-exports so callers can do:
#   from pgappforge.plugins.erp.platform.rag import RAGDocument, RAGService
from pgappforge.plugins.erp.platform.rag.models import (  # noqa: E402
	RAGDocument,
	RAGChunk,
	SOURCE_ERP_GL_ENTRY,
	SOURCE_POLICY,
	SOURCE_MANUAL,
	SOURCE_FAQ,
	SOURCE_CONTRACT,
	SOURCE_TICKET,
	SOURCE_GL_ACCOUNT,
)
from pgappforge.plugins.erp.platform.rag.services import RAGService  # noqa: E402

__all__ = [
	"RAGPlugin",
	"create_plugin",
	"RAGDocument",
	"RAGChunk",
	"RAGService",
	"SOURCE_ERP_GL_ENTRY",
	"SOURCE_POLICY",
	"SOURCE_MANUAL",
	"SOURCE_FAQ",
	"SOURCE_CONTRACT",
	"SOURCE_TICKET",
	"SOURCE_GL_ACCOUNT",
]
