"""
pgappforge/plugins/erp/platform/nlp/client.py

LiteLLM client — shared by NLP, RAG, and ML plugins.
Thin wrapper around the LiteLLM proxy (OpenAI-compatible REST API).
Falls back gracefully when not configured.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:4000/v1"
_DEFAULT_MODEL = "gpt-4o"
_DEFAULT_FAST_MODEL = "gpt-4o-mini"
_DEFAULT_EMBEDDING_MODEL = "text-embedding-ada-002"
_HEADER_UNSAFE_RE = re.compile(r"[\r\n\x00]")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,119}$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _cfg(key: str, default: Any = None) -> Any:
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except RuntimeError:
		return default


class LLMError(Exception):
	pass


class LLMConfigError(LLMError):
	"""Raised when LiteLLM client configuration is unsafe or invalid."""


class LLMResponseError(LLMError):
	"""Raised when the LiteLLM proxy returns an invalid response shape."""


class LLMClient:
	"""Thin wrapper around the LiteLLM proxy (OpenAI-compatible REST API).

	All config is read lazily from the Flask app config so it is safe to
	instantiate at module import time before the app context exists.
	"""

	@property
	def _base_url(self) -> str:
		return self._normalize_base_url(_cfg("LITELLM_URL", _DEFAULT_BASE_URL))

	@property
	def _api_key(self) -> str:
		return self._safe_header_value(_cfg("LITELLM_API_KEY", ""))

	@property
	def _model(self) -> str:
		return self._normalize_model(_cfg("LLM_MODEL", _DEFAULT_MODEL), "LLM_MODEL")

	@property
	def _fast_model(self) -> str:
		return self._normalize_model(
			_cfg("LLM_FAST_MODEL", _DEFAULT_FAST_MODEL),
			"LLM_FAST_MODEL",
		)

	@property
	def _embedding_model(self) -> str:
		return self._normalize_model(
			_cfg("LLM_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL),
			"LLM_EMBEDDING_MODEL",
		)

	def _headers(self) -> dict[str, str]:
		headers = {"Content-Type": "application/json"}
		if self._api_key:
			headers["Authorization"] = f"Bearer {self._api_key}"
		return headers

	def _post(self, path: str, body: dict, timeout: int = 30) -> dict:
		return self._request("POST", path, body=body, timeout=timeout)

	def _get(self, path: str, timeout: int = 30) -> dict:
		return self._request("GET", path, body=None, timeout=timeout)

	def _request(
		self,
		method: str,
		path: str,
		*,
		body: dict | None,
		timeout: int | float = 30,
	) -> dict:
		method = method.upper()
		if method not in {"GET", "POST"}:
			raise LLMConfigError("Unsupported LiteLLM request method")
		timeout = self._normalize_timeout(timeout)
		url = self._build_url(path)
		data = None
		if method == "POST":
			if not isinstance(body, dict):
				raise LLMConfigError("LiteLLM request body must be a dict")
			try:
				data = json.dumps(body).encode("utf-8")
			except (TypeError, ValueError) as exc:
				raise LLMConfigError(f"LiteLLM request body is not JSON serializable: {exc}") from exc
		req = urllib.request.Request(
			url,
			data=data,
			method=method,
			headers=self._headers(),
		)
		try:
			with urllib.request.urlopen(req, timeout=timeout) as resp:
				return self._read_json_response(resp.read(10 * 1024 * 1024))
		except urllib.error.HTTPError as exc:
			body_preview = exc.read(1000).decode(errors="replace")
			raise LLMError(
				f"LiteLLM HTTP {exc.code}: {body_preview[:200]}"
			) from exc
		except LLMError:
			raise
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
		messages = self._normalize_messages(messages)
		model = self._normalize_model(model or self._fast_model, "model")
		temperature = self._normalize_temperature(temperature)
		max_tokens = self._normalize_max_tokens(max_tokens)
		result = self._post(
			"/chat/completions",
			{
				"model": model,
				"messages": messages,
				"temperature": temperature,
				"max_tokens": max_tokens,
			},
		)
		choices = result.get("choices")
		if not isinstance(choices, list) or not choices:
			raise LLMResponseError("LiteLLM chat response missing choices")
		first = choices[0]
		if not isinstance(first, dict):
			raise LLMResponseError("LiteLLM chat choice must be an object")
		message = first.get("message")
		if not isinstance(message, dict):
			raise LLMResponseError("LiteLLM chat choice missing message")
		content = message.get("content")
		if not isinstance(content, str) or not content.strip():
			raise LLMResponseError("LiteLLM chat content must be a non-empty string")
		return content.strip()

	def embed(self, text: str | list[str]) -> list[list[float]]:
		"""Generate embeddings. Returns a list of float vectors."""
		inputs = self._normalize_embedding_inputs(text)
		result = self._post(
			"/embeddings",
			{"model": self._embedding_model, "input": inputs},
		)
		data = result.get("data")
		if not isinstance(data, list) or len(data) != len(inputs):
			raise LLMResponseError("LiteLLM embedding response data length mismatch")
		embeddings: list[list[float]] = []
		for item in data:
			if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
				raise LLMResponseError("LiteLLM embedding item missing vector")
			vector: list[float] = []
			for value in item["embedding"]:
				if isinstance(value, bool) or not isinstance(value, (int, float)):
					raise LLMResponseError("LiteLLM embedding vector must contain numbers")
				vector.append(float(value))
			if not vector:
				raise LLMResponseError("LiteLLM embedding vector cannot be empty")
			embeddings.append(vector)
		return embeddings

	def is_available(self) -> bool:
		"""Return True if the LiteLLM proxy is reachable."""
		try:
			self._get("/models")
			return True
		except Exception:
			return False

	def _build_url(self, path: str) -> str:
		if not isinstance(path, str) or not path.startswith("/"):
			raise LLMConfigError("LiteLLM path must start with '/'")
		parts = [part for part in path.split("/") if part]
		if any(part in {".", ".."} for part in parts):
			raise LLMConfigError("LiteLLM path cannot contain traversal segments")
		if any("?" in part or "#" in part for part in parts):
			raise LLMConfigError("LiteLLM path cannot include query or fragment text")
		return f"{self._base_url}{path}"

	@staticmethod
	def _normalize_base_url(value: Any) -> str:
		if not isinstance(value, str):
			raise LLMConfigError("LITELLM_URL must be a string")
		text = value.strip().rstrip("/")
		if not text:
			raise LLMConfigError("LITELLM_URL must be non-empty")
		parsed = urllib.parse.urlsplit(text)
		if parsed.scheme not in {"http", "https"} or not parsed.netloc:
			raise LLMConfigError("LITELLM_URL must be an absolute HTTP(S) URL")
		if parsed.username or parsed.password or parsed.query or parsed.fragment:
			raise LLMConfigError("LITELLM_URL cannot include credentials, query, or fragment")
		if parsed.scheme == "http" and parsed.hostname not in _LOCAL_HOSTS:
			raise LLMConfigError("LITELLM_URL must use HTTPS unless it targets localhost")
		path_parts = [part for part in parsed.path.split("/") if part]
		if any(part in {".", ".."} for part in path_parts):
			raise LLMConfigError("LITELLM_URL path cannot contain traversal segments")
		return urllib.parse.urlunsplit(
			(parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
		)

	@staticmethod
	def _safe_header_value(value: Any) -> str:
		if value is None:
			return ""
		if not isinstance(value, str):
			raise LLMConfigError("LITELLM_API_KEY must be a string")
		text = value.strip()
		if _HEADER_UNSAFE_RE.search(text):
			raise LLMConfigError("LITELLM_API_KEY contains unsafe header characters")
		return text

	@staticmethod
	def _normalize_model(value: Any, field_name: str) -> str:
		if not isinstance(value, str):
			raise LLMConfigError(f"{field_name} must be a string")
		text = value.strip()
		if not text or not _MODEL_RE.fullmatch(text):
			raise LLMConfigError(f"{field_name} contains an invalid model identifier")
		return text

	@staticmethod
	def _normalize_timeout(value: int | float) -> int | float:
		if isinstance(value, bool) or not isinstance(value, (int, float)):
			raise LLMConfigError("LiteLLM timeout must be numeric")
		if value < 1 or value > 120:
			raise LLMConfigError("LiteLLM timeout must be between 1 and 120 seconds")
		return value

	@staticmethod
	def _normalize_temperature(value: float) -> float:
		if isinstance(value, bool) or not isinstance(value, (int, float)):
			raise LLMConfigError("temperature must be numeric")
		if value < 0 or value > 2:
			raise LLMConfigError("temperature must be between 0 and 2")
		return float(value)

	@staticmethod
	def _normalize_max_tokens(value: int) -> int:
		if isinstance(value, bool) or not isinstance(value, int):
			raise LLMConfigError("max_tokens must be an integer")
		if value < 1 or value > 16384:
			raise LLMConfigError("max_tokens must be between 1 and 16384")
		return value

	@staticmethod
	def _normalize_messages(messages: list[dict]) -> list[dict]:
		if not isinstance(messages, list) or not messages:
			raise LLMConfigError("messages must be a non-empty list")
		if len(messages) > 100:
			raise LLMConfigError("messages cannot contain more than 100 items")
		normalized: list[dict] = []
		for index, message in enumerate(messages):
			if not isinstance(message, dict):
				raise LLMConfigError(f"messages[{index}] must be an object")
			role = message.get("role")
			content = message.get("content")
			if role not in {"system", "user", "assistant", "tool"}:
				raise LLMConfigError(f"messages[{index}].role is invalid")
			if not isinstance(content, str) or not content.strip():
				raise LLMConfigError(f"messages[{index}].content must be non-empty text")
			if "\x00" in content or len(content) > 100_000:
				raise LLMConfigError(f"messages[{index}].content is invalid")
			normalized.append({"role": role, "content": content})
		return normalized

	@staticmethod
	def _normalize_embedding_inputs(text: str | list[str]) -> list[str]:
		inputs = [text] if isinstance(text, str) else text
		if not isinstance(inputs, list) or not inputs:
			raise LLMConfigError("embedding input must be a string or non-empty list")
		if len(inputs) > 100:
			raise LLMConfigError("embedding input cannot contain more than 100 texts")
		normalized: list[str] = []
		for index, item in enumerate(inputs):
			if not isinstance(item, str) or not item.strip():
				raise LLMConfigError(f"embedding input[{index}] must be non-empty text")
			if "\x00" in item or len(item) > 20_000:
				raise LLMConfigError(f"embedding input[{index}] is invalid")
			normalized.append(item)
		return normalized

	@staticmethod
	def _read_json_response(raw: bytes) -> dict:
		try:
			data = json.loads(raw.decode("utf-8"))
		except (UnicodeDecodeError, json.JSONDecodeError) as exc:
			raise LLMResponseError("LiteLLM response was not valid JSON") from exc
		if not isinstance(data, dict):
			raise LLMResponseError("LiteLLM response must be a JSON object")
		return data


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


__all__ = [
	"LLMClient",
	"LLMError",
	"LLMConfigError",
	"LLMResponseError",
	"cosine_similarity",
]
