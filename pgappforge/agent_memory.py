from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from typing import Any
import sqlalchemy as sa

log = logging.getLogger(__name__)


class AgentMemoryStore:
	"""Persistent memory store for AI agents.

	Stores facts, preferences, and context across user sessions.
	Uses pgvector for semantic retrieval of relevant memories.

	Memory types:
	- "preference": user preference ("User prefers KES currency format")
	- "fact": business fact ("Company has 3 branches: Nairobi, Mombasa, Kisumu")
	- "context": recent context ("Last discussed Q2 payroll run")
	- "decision": past decision with rationale

	Usage::

		mem = AgentMemoryStore(user_id="u123", tenant_id="t456")
		mem.remember("User prefers to see amounts in KES", memory_type="preference")
		relevant = mem.recall("salary payment")
	"""

	def __init__(self, user_id: str = "", tenant_id: str = "", session=None):
		self.user_id = user_id
		self.tenant_id = tenant_id
		self._session = session

	@property
	def session(self):
		if self._session:
			return self._session
		try:
			from flask import current_app
			return current_app.appbuilder.get_session()
		except Exception:
			return None

	def remember(
		self,
		content: str,
		*,
		memory_type: str = "fact",
		importance: float = 0.5,
		metadata: dict | None = None,
	) -> str | None:
		"""Store a new memory.

		Args:
			content: The memory content (plain text)
			memory_type: "preference" | "fact" | "context" | "decision"
			importance: 0.0-1.0 (higher = retrieved more often)

		Returns: memory ID if stored successfully
		"""
		if not self.session:
			return None

		try:
			from uuid6 import uuid7
			memory_id = str(uuid7())
			embedding = self._embed(content)

			self.session.execute(sa.text("""
				INSERT INTO pgaf_agent_memory
				(id, user_id, tenant_id, memory_type, content, importance,
				 embedding, metadata, created_at, last_accessed_at, access_count)
				VALUES
				(:id, :user_id, :tenant_id, :memory_type, :content, :importance,
				 :embedding::vector, :metadata::jsonb, :now, :now, 0)
			"""), {
				"id": memory_id,
				"user_id": self.user_id,
				"tenant_id": self.tenant_id,
				"memory_type": memory_type,
				"content": content[:2000],
				"importance": importance,
				"embedding": json.dumps(embedding) if embedding else None,
				"metadata": json.dumps(metadata or {}),
				"now": datetime.now(timezone.utc),
			})
			self.session.flush()
			log.debug("Memory stored: %s (%s)", memory_id[:8], memory_type)
			return memory_id
		except Exception as exc:
			log.debug("AgentMemoryStore.remember failed: %s", exc)
			return None

	def recall(
		self,
		query: str,
		*,
		top_k: int = 5,
		memory_types: list[str] | None = None,
	) -> list[dict]:
		"""Retrieve the most relevant memories for a query.

		Uses semantic similarity (pgvector cosine) when embeddings available,
		falls back to recent memories otherwise.

		Returns list of {id, content, memory_type, importance, relevance_score}
		"""
		if not self.session:
			return []

		try:
			query_embedding = self._embed(query)

			type_filter = ""
			params: dict = {"uid": self.user_id, "tid": self.tenant_id, "k": top_k}

			if memory_types:
				type_filter = "AND memory_type = ANY(:types)"
				params["types"] = memory_types

			if query_embedding:
				# Semantic search via pgvector
				params["emb"] = json.dumps(query_embedding)
				rows = self.session.execute(sa.text(f"""
					SELECT id, content, memory_type, importance,
					       1 - (embedding <=> :emb::vector) AS relevance_score
					FROM pgaf_agent_memory
					WHERE user_id = :uid AND tenant_id = :tid {type_filter}
					  AND embedding IS NOT NULL
					ORDER BY embedding <=> :emb::vector
					LIMIT :k
				"""), params).fetchall()
			else:
				# Fallback: most recent/important memories
				rows = self.session.execute(sa.text(f"""
					SELECT id, content, memory_type, importance, 0.5 AS relevance_score
					FROM pgaf_agent_memory
					WHERE user_id = :uid AND tenant_id = :tid {type_filter}
					ORDER BY importance DESC, created_at DESC
					LIMIT :k
				"""), params).fetchall()

			# Update access tracking
			if rows:
				ids = [r[0] for r in rows]
				self.session.execute(sa.text(
					"UPDATE pgaf_agent_memory SET last_accessed_at = NOW(), "
					"access_count = access_count + 1 WHERE id = ANY(:ids)"
				), {"ids": ids})

			return [
				{
					"id": r[0],
					"content": r[1],
					"memory_type": r[2],
					"importance": float(r[3] or 0),
					"relevance_score": float(r[4] or 0),
				}
				for r in rows
			]
		except Exception as exc:
			log.debug("AgentMemoryStore.recall failed: %s", exc)
			return []

	def build_memory_context(self, query: str) -> str:
		"""Build a context string from relevant memories for LLM prompts."""
		memories = self.recall(query, top_k=5)
		if not memories:
			return ""
		lines = ["Relevant context from memory:"]
		for m in memories:
			lines.append(f"- [{m['memory_type']}] {m['content']}")
		return "\n".join(lines)

	def forget(self, memory_id: str) -> bool:
		"""Delete a specific memory."""
		try:
			self.session.execute(
				sa.text("DELETE FROM pgaf_agent_memory WHERE id = :id AND user_id = :uid"),
				{"id": memory_id, "uid": self.user_id},
			)
			return True
		except Exception:
			return False

	def forget_all(self, memory_type: str | None = None) -> int:
		"""Delete all memories for this user (optionally filter by type)."""
		try:
			params: dict[str, Any] = {"uid": self.user_id, "tid": self.tenant_id}
			filter_clause = "WHERE user_id = :uid AND tenant_id = :tid"
			if memory_type:
				filter_clause += " AND memory_type = :type"
				params["type"] = memory_type
			result = self.session.execute(
				sa.text(f"DELETE FROM pgaf_agent_memory {filter_clause}"), params
			)
			return result.rowcount
		except Exception:
			return 0

	def _embed(self, text: str) -> list[float] | None:
		"""Generate embedding via LLM client."""
		try:
			from pgappforge.plugins.erp.platform.nlp.client import LLMClient
			client = LLMClient()
			embeddings = client.embed(text)
			return embeddings[0] if embeddings else None
		except Exception:
			return None


def create_memory_tables(engine) -> None:
	"""Create pgaf_agent_memory table with pgvector support."""
	with engine.begin() as conn:
		# Create pgvector extension if not exists
		try:
			conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
		except Exception:
			pass

		conn.execute(sa.text("""
		CREATE TABLE IF NOT EXISTS pgaf_agent_memory (
			id               VARCHAR(36)   PRIMARY KEY,
			user_id          VARCHAR(36)   NOT NULL,
			tenant_id        VARCHAR(36)   NOT NULL,
			memory_type      VARCHAR(20)   NOT NULL DEFAULT 'fact',
			content          TEXT          NOT NULL,
			importance       NUMERIC(4,3)  NOT NULL DEFAULT 0.5,
			embedding        VECTOR(1536),
			metadata         JSONB         NOT NULL DEFAULT '{}',
			created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
			last_accessed_at TIMESTAMPTZ,
			access_count     INTEGER       NOT NULL DEFAULT 0
		);
		CREATE INDEX IF NOT EXISTS ix_pgaf_memory_user
			ON pgaf_agent_memory(user_id, tenant_id);
		CREATE INDEX IF NOT EXISTS ix_pgaf_memory_type
			ON pgaf_agent_memory(memory_type);
		"""))


__all__ = ["AgentMemoryStore", "create_memory_tables"]
