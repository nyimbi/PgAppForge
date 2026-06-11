"""
pgappforge/plugins/erp/platform/nlp/client.py

LiteLLM client — shared by NLP, RAG, and ML plugins.
Thin wrapper around the LiteLLM proxy (OpenAI-compatible REST API).
Falls back gracefully when not configured.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)


def _cfg(key: str, default: Any = None) -> Any:
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except RuntimeError:
		return default


class LLMError(Exception):
	pass


class LLMClient:
	"""Thin wrapper around the LiteLLM proxy (OpenAI-compatible REST API).

	All config is read lazily from the Flask app config so it is safe to
	instantiate at module import time before the app context exists.
	"""

	@property
	def _base_url(self) -> str:
		return _cfg("LITELLM_URL", "http://84.247.181.100:4000/v1").rstrip("/")

	@property
	def _api_key(self) -> str:
		return _cfg("LITELLM_API_KEY", "sk-pjs-litellm-master-key")

	@property
	def _model(self) -> str:
		return _cfg("LLM_MODEL", "gpt-4o")

	@property
	def _fast_model(self) -> str:
		return _cfg("LLM_FAST_MODEL", "gpt-4o-mini")

	@property
	def _embedding_model(self) -> str:
		return _cfg("LLM_EMBEDDING_MODEL", "text-embedding-ada-002")

	def _headers(self) -> dict[str, str]:
		return {
			"Content-Type": "application/json",
			"Authorization": f"Bearer {self._api_key}",
		}

	def _post(self, path: str, body: dict, timeout: int = 30) -> dict:
		url = f"{self._base_url}{path}"
		data = json.dumps(body).encode()
		req = urllib.request.Request(url, data=data, method="POST", headers=self._headers())
		try:
			with urllib.request.urlopen(req, timeout=timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			raise LLMError(
				f"LiteLLM HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}"
			) from exc
		except Exception as exc:
			raise LLMError(f"LiteLLM request failed: {exc}") from exc

	def chat(
		self,
		messages: list[dict],
		*,
		model: str | None = None,
		temperature: float = 0.0,
		max_tokens: int = 500,
	) -> str:
		"""Send a chat completion. Returns the content string."""
		result = self._post(
			"/chat/completions",
			{
				"model": model or self._fast_model,
				"messages": messages,
				"temperature": temperature,
				"max_tokens": max_tokens,
			},
		)
		return result["choices"][0]["message"]["content"].strip()

	def embed(self, text: str | list[str]) -> list[list[float]]:
		"""Generate embeddings. Returns a list of float vectors."""
		inputs = [text] if isinstance(text, str) else text
		result = self._post(
			"/embeddings",
			{"model": self._embedding_model, "input": inputs},
		)
		return [item["embedding"] for item in result["data"]]

	def is_available(self) -> bool:
		"""Return True if the LiteLLM proxy is reachable."""
		try:
			self._post("/models", {})
			return True
		except Exception:
			return False


def cosine_similarity(a: list[float], b: list[float]) -> float:
	"""Cosine similarity between two equal-length float vectors. Returns 0.0 on any error."""
	if not a or not b or len(a) != len(b):
		return 0.0
	import math
	dot = sum(x * y for x, y in zip(a, b))
	norm_a = math.sqrt(sum(x * x for x in a))
	norm_b = math.sqrt(sum(x * x for x in b))
	if norm_a == 0.0 or norm_b == 0.0:
		return 0.0
	return dot / (norm_a * norm_b)


__all__ = ["LLMClient", "LLMError", "cosine_similarity"]
