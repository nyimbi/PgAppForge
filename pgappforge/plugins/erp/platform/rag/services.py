"""
pgappforge/plugins/erp/platform/rag/services.py

RAG service: document ingestion, chunking, embedding, retrieval, Q&A.

Pipeline
--------
  ingest_document()  → hash-dedup → chunk → embed → store
  search()           → embed query → cosine similarity scan → ranked results
  ask()              → search() → build context prompt → LLM → structured answer
"""
from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.platform.nlp.client import cosine_similarity as _cosine_similarity  # shared utility


# ---------------------------------------------------------------------------
# RAGService
# ---------------------------------------------------------------------------

class RAGService:
	"""High-level interface for the RAG knowledge base."""

	# ── Ingestion ─────────────────────────────────────────────────────────────

	def ingest_document(
		self,
		title: str,
		content: str,
		source_type: str,
		tenant_id: str,
		session: Any,
		*,
		source_id: str | None = None,
		metadata: dict | None = None,
		chunk_size: int = 800,
		overlap: int = 100,
	) -> "RAGDocument":  # type: ignore[name-defined]
		"""Ingest a text document: hash-dedup, chunk, embed, persist.

		Args:
			title:       Human-readable title stored with the document.
			content:     Full text to index.
			source_type: One of the SOURCE_* constants (or any custom string).
			tenant_id:   Tenant scope for all stored rows.
			session:     Active SQLAlchemy session.
			source_id:   Optional FK string pointing to the originating ERP record.
			metadata:    Arbitrary JSONB dict (author, department, tags, version, …).
			chunk_size:  Characters per chunk.  800 chars ≈ 200 tokens.
			overlap:     Character overlap between adjacent chunks for context
			             continuity.

		Returns:
			The persisted RAGDocument (existing or newly created).
		"""
		from pgappforge.plugins.erp.platform.rag.models import RAGDocument, RAGChunk
		import sqlalchemy as sa

		content_hash = hashlib.sha256(content.encode()).hexdigest()

		# ── dedup check ───────────────────────────────────────────────────────
		existing = session.execute(
			sa.select(RAGDocument).where(
				RAGDocument.tenant_id   == tenant_id,
				RAGDocument.content_hash == content_hash,
			)
		).scalar_one_or_none()
		if existing:
			log.debug("RAG: skipping duplicate document %r (hash %s)", title, content_hash[:8])
			return existing

		# ── create document record ────────────────────────────────────────────
		doc = RAGDocument(
			tenant_id    = tenant_id,
			source_type  = source_type,
			source_id    = source_id,
			title        = title,
			content      = content,
			content_hash = content_hash,
			metadata     = metadata or {},
			is_active    = True,
		)
		session.add(doc)
		session.flush()  # materialise doc.id before FK references

		# ── chunk + embed ─────────────────────────────────────────────────────
		chunks     = self._chunk_text(content, chunk_size=chunk_size, overlap=overlap)
		embeddings = self._embed_chunks(chunks)
		doc.chunk_count = len(chunks)

		for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
			session.add(RAGChunk(
				tenant_id       = tenant_id,
				document_id     = doc.id,
				chunk_index     = i,
				content         = chunk_text,
				content_length  = len(chunk_text),
				embedding       = embedding,
				embedding_model = "text-embedding-ada-002",
			))

		doc.indexed_at = datetime.now(timezone.utc)
		session.flush()
		log.info("RAG: ingested %r (%d chunks)", title, len(chunks))
		return doc

	def ingest_erp_data(
		self,
		tenant_id: str,
		session: Any,
		*,
		sources: list[str] | None = None,
	) -> dict[str, int]:
		"""Bulk-ingest ERP data into the RAG index.

		Args:
			tenant_id: Tenant scope.
			session:   Active SQLAlchemy session.
			sources:   List of source_type strings to ingest.  Defaults to all
			           known sources: GL_ACCOUNTS, POLICIES, MANUALS.

		Returns:
			Mapping of source_type → count of documents ingested.
		"""
		all_sources = sources or ["GL_ACCOUNTS", "POLICIES", "MANUALS"]
		results: dict[str, int] = {}
		for source in all_sources:
			try:
				count = self._ingest_source(source, tenant_id, session)
				results[source] = count
			except Exception as exc:
				log.debug("RAG ingest_erp_data %r failed: %s", source, exc)
				results[source] = 0
		return results

	def _ingest_source(self, source_type: str, tenant_id: str, session: Any) -> int:
		"""Dispatch to the correct ERP-source ingestor."""
		if source_type == "GL_ACCOUNTS":
			return self._ingest_gl_accounts(tenant_id, session)
		return 0

	def _ingest_gl_accounts(self, tenant_id: str, session: Any) -> int:
		"""Ingest GL account descriptions for finance Q&A."""
		try:
			from pgappforge.plugins.erp.finance.gl.models import AccountCode
			import sqlalchemy as sa

			accounts = session.execute(
				sa.select(AccountCode).where(AccountCode.tenant_id == tenant_id)
			).scalars().all()

			ingested = 0
			for acc in accounts:
				text = (
					f"Account {acc.code}: {acc.name}. "
					f"{getattr(acc, 'description', '') or ''}"
				)
				self.ingest_document(
					title       = f"GL Account {acc.code}",
					content     = text,
					source_type = "GL_ACCOUNT",
					source_id   = str(acc.id),
					tenant_id   = tenant_id,
					session     = session,
				)
				ingested += 1
			return ingested
		except Exception as exc:
			log.debug("_ingest_gl_accounts: %s", exc)
			return 0

	# ── Retrieval ──────────────────────────────────────────────────────────────

	def search(
		self,
		query: str,
		tenant_id: str,
		session: Any,
		*,
		top_k: int = 5,
		source_types: list[str] | None = None,
	) -> list[dict]:
		"""Semantic similarity search using cosine distance over stored embeddings.

		Loads all chunk embeddings for the tenant into memory and ranks them by
		cosine similarity to the query vector.

		TODO: Replace the in-memory scan with a pgvector ANN index once the
		      plat_rag_chunk table is migrated to a VECTOR column.

		Args:
			query:        Natural-language question or search phrase.
			tenant_id:    Tenant scope.
			session:      Active SQLAlchemy session.
			top_k:        Maximum number of results to return.
			source_types: Optional whitelist of source_type values to restrict
			              the search to a subset of the knowledge base.

		Returns:
			List of result dicts, sorted by score descending::

			    [
			        {
			            "chunk_id":    str,
			            "document_id": str,
			            "title":       str,
			            "content":     str,
			            "score":       float,   # cosine similarity [0, 1]
			            "source_type": str,
			        },
			        ...
			    ]
		"""
		from pgappforge.plugins.erp.platform.rag.models import RAGChunk, RAGDocument
		import sqlalchemy as sa

		query_embeddings = self._embed_chunks([query])
		if not query_embeddings or not query_embeddings[0]:
			return []

		q_vec = query_embeddings[0]

		# Try pgvector ANN query first (sub-linear, requires `vector` extension + VECTOR column).
		# Falls back to full in-memory scan when pgvector is unavailable or column doesn't exist.
		pgvector_results = self._search_pgvector(q_vec, tenant_id, session, top_k, source_types)
		if pgvector_results is not None:
			return pgvector_results

		# In-memory cosine scan (correct, O(n) — suitable for <10K chunks per tenant).
		stmt = (
			sa.select(RAGChunk, RAGDocument)
			.join(RAGDocument, RAGDocument.id == RAGChunk.document_id)
			.where(
				RAGChunk.tenant_id      == tenant_id,
				RAGDocument.is_active.is_(True),
				RAGChunk.embedding.isnot(None),
			)
		)
		if source_types:
			stmt = stmt.where(RAGDocument.source_type.in_(source_types))

		rows = session.execute(stmt).all()

		scored: list[dict] = []
		for chunk, doc in rows:
			if not chunk.embedding:
				continue
			score = _cosine_similarity(q_vec, chunk.embedding)
			scored.append({
				"chunk_id":    chunk.id,
				"document_id": doc.id,
				"title":       doc.title,
				"content":     chunk.content,
				"score":       score,
				"source_type": doc.source_type,
			})

		scored.sort(key=lambda x: x["score"], reverse=True)
		return scored[:top_k]

	def _search_pgvector(
		self,
		q_vec: list[float],
		tenant_id: str,
		session: Any,
		top_k: int,
		source_types: list[str] | None,
	) -> list[dict] | None:
		"""Attempt ANN search using PostgreSQL pgvector extension.

		Returns ranked results if the `vector` extension is available and the
		`embedding_vector` column exists on plat_rag_chunk.  Returns None to
		signal the caller should fall back to the in-memory scan.

		Migration (run once when pgvector is installed):
		  ALTER TABLE plat_rag_chunk ADD COLUMN embedding_vector vector(1536);
		  UPDATE plat_rag_chunk SET embedding_vector = embedding::vector;
		  CREATE INDEX ON plat_rag_chunk USING ivfflat (embedding_vector vector_cosine_ops);
		"""
		try:
			import json
			vec_literal = "[" + ",".join(str(x) for x in q_vec) + "]"

			# Build the filter clause
			filter_clause = "AND d.is_active = TRUE AND c.embedding_vector IS NOT NULL"
			params: dict = {"tenant_id": tenant_id, "top_k": top_k, "vec": vec_literal}
			if source_types:
				filter_clause += " AND d.source_type = ANY(:source_types)"
				params["source_types"] = source_types

			sql = sa.text(f"""
				SELECT c.id, c.document_id, d.title, c.content, d.source_type,
				       1 - (c.embedding_vector <=> :vec::vector) AS score
				FROM plat_rag_chunk c
				JOIN plat_rag_document d ON d.id = c.document_id
				WHERE c.tenant_id = :tenant_id
				  {filter_clause}
				ORDER BY c.embedding_vector <=> :vec::vector
				LIMIT :top_k
			""")
			rows = session.execute(sql, params).fetchall()
			return [
				{
					"chunk_id":    str(r[0]),
					"document_id": str(r[1]),
					"title":       r[2] or "",
					"content":     r[3] or "",
					"source_type": r[4] or "",
					"score":       float(r[5]),
				}
				for r in rows
			]
		except Exception as exc:
			# pgvector not installed, column missing, or any DB error — use in-memory scan
			log.debug("_search_pgvector unavailable, using in-memory scan: %s", exc)
			return None

	# ── Q&A ───────────────────────────────────────────────────────────────────

	def ask(
		self,
		question: str,
		tenant_id: str,
		session: Any,
		*,
		top_k: int = 5,
		source_types: list[str] | None = None,
		system_context: str = "",
	) -> dict[str, Any]:
		"""Answer a question using retrieved context (RAG pattern).

		1. Embeds the question.
		2. Retrieves the top-k most similar chunks via cosine search.
		3. Builds a grounded prompt and calls the LLM.
		4. Returns a structured answer with cited sources.

		Args:
			question:       Natural-language question.
			tenant_id:      Tenant scope.
			session:        Active SQLAlchemy session.
			top_k:          Number of context chunks to retrieve.
			source_types:   Optional filter on source_type (see search()).
			system_context: Extra text appended to the system prompt (e.g.
			                company-specific instructions).

		Returns:
			::

			    {
			        "answer":           str,   # LLM-generated answer
			        "sources":          [      # chunks used as evidence
			            {
			                "title":   str,
			                "score":   float,
			                "excerpt": str,    # first 200 chars of chunk
			            },
			            ...
			        ],
			        "model":            str,   # model name used, or "fallback"
			        "retrieved_chunks": int,
			    }
		"""
		from pgappforge.plugins.erp.platform.nlp.client import LLMClient, LLMError

		client = LLMClient()
		chunks = self.search(
			question, tenant_id, session,
			top_k=top_k, source_types=source_types,
		)

		if not chunks:
			return {
				"answer": (
					"I don't have enough information to answer this question. "
					"No relevant documents were found."
				),
				"sources":          [],
				"model":            "none",
				"retrieved_chunks": 0,
			}

		context = "\n\n---\n".join(
			f"[{c['source_type']}] {c['title']}\n{c['content']}"
			for c in chunks
		)

		system = (
			"You are a helpful ERP assistant. "
			"Answer questions based ONLY on the provided context. "
			"If the context doesn't contain enough information, say so clearly. "
			"Be concise and accurate."
			+ (f"\n\n{system_context}" if system_context else "")
		)
		user_msg = f"Context:\n{context}\n\nQuestion: {question}"

		try:
			answer = client.chat(
				[
					{"role": "system", "content": system},
					{"role": "user",   "content": user_msg},
				],
				model      = client._model,
				max_tokens = 800,
				temperature = 0.1,
			)
			model_used = client._model
		except LLMError as exc:
			log.warning("RAG ask failed: %s", exc)
			answer     = (
				f"Unable to answer: LLM unavailable. "
				f"Top match: {chunks[0]['content'][:200]}"
			)
			model_used = "fallback"

		return {
			"answer": answer,
			"sources": [
				{
					"title":   c["title"],
					"score":   round(c["score"], 3),
					"excerpt": c["content"][:200],
				}
				for c in chunks
			],
			"model":            model_used,
			"retrieved_chunks": len(chunks),
		}

	# ── Document lifecycle ─────────────────────────────────────────────────────

	def delete_document(
		self,
		document_id: str,
		tenant_id: str,
		session: Any,
	) -> bool:
		"""Soft-delete a document by setting is_active=False.

		Chunks are retained so historical searches still return something
		until the document is hard-deleted by a cleanup job.
		"""
		from pgappforge.plugins.erp.platform.rag.models import RAGDocument
		import sqlalchemy as sa

		session.execute(
			sa.update(RAGDocument)
			.where(
				RAGDocument.id        == document_id,
				RAGDocument.tenant_id == tenant_id,
			)
			.values(is_active=False)
		)
		session.flush()
		return True

	def get_index_stats(self, tenant_id: str, session: Any) -> dict:
		"""Return a summary of RAG index size for the given tenant.

		Returns:
			{"documents": int, "chunks": int, "tenant_id": str}
		"""
		from pgappforge.plugins.erp.platform.rag.models import RAGDocument, RAGChunk
		import sqlalchemy as sa

		doc_count = session.execute(
			sa.select(sa.func.count(RAGDocument.id)).where(
				RAGDocument.tenant_id == tenant_id,
				RAGDocument.is_active.is_(True),
			)
		).scalar_one() or 0

		chunk_count = session.execute(
			sa.select(sa.func.count(RAGChunk.id)).where(
				RAGChunk.tenant_id == tenant_id,
			)
		).scalar_one() or 0

		return {
			"documents": doc_count,
			"chunks":    chunk_count,
			"tenant_id": tenant_id,
		}

	# ── Internal helpers ───────────────────────────────────────────────────────

	def _chunk_text(
		self,
		text: str,
		chunk_size: int = 800,
		overlap: int = 100,
	) -> list[str]:
		"""Split text into overlapping chunks, preferring sentence boundaries.

		Args:
			text:       Source text.
			chunk_size: Maximum characters per chunk.
			overlap:    Character overlap between successive chunks so context
			            is not lost at boundaries.

		Returns:
			Non-empty list of chunk strings.
		"""
		if len(text) <= chunk_size:
			return [text]

		chunks: list[str] = []
		start = 0
		while start < len(text):
			end = start + chunk_size
			if end < len(text):
				# Prefer to break at a sentence boundary in the second half of
				# the window to avoid very short leading chunks.
				boundary = text.rfind(". ", start + chunk_size // 2, end)
				if boundary > start:
					end = boundary + 1  # include the period

			chunks.append(text[start:end].strip())
			start = end - overlap

		return [c for c in chunks if c]

	def _embed_chunks(self, chunks: list[str]) -> list[list[float] | None]:
		"""Embed a batch of text chunks via the LiteLLM proxy.

		Returns a list of the same length as ``chunks``.  Entries are ``None``
		when embedding fails so callers can skip un-embedded chunks gracefully.
		"""
		from pgappforge.plugins.erp.platform.nlp.client import LLMClient, LLMError

		client = LLMClient()
		try:
			return client.embed(chunks)  # type: ignore[return-value]
		except LLMError as exc:
			log.debug("_embed_chunks failed: %s", exc)
			return [None] * len(chunks)


__all__ = ["RAGService"]
