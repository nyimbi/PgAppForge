"""
pgappforge/plugins/erp/platform/apg_bridge/client.py

APG HTTP client — JWT auth, capability calls, marketplace discovery.

Authentication priority:
  1. APG_STATIC_TOKEN  — pre-issued JWT, used as-is
  2. APG_AUTH_EMAIL + APG_AUTH_PASSWORD — POST /api/auth/login, cache token
  3. No auth — development / local APG with auth disabled

All public methods are non-fatal: return None/[] on connection failure or
when APG_ENABLED=False.  Callers must handle None returns gracefully.
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

_APG_DEFAULT_BASE_URL = "http://localhost:5000"
_APG_DEFAULT_MARKETPLACE_URL = "http://localhost:8000"
_MAX_TIMEOUT_SECONDS = 120
_MIN_TIMEOUT_SECONDS = 1
_SAFE_HEADER_VALUE_RE = re.compile(r"^[^\r\n]+$")
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled", ""}


def _cfg(key: str, default: Any = None) -> Any:
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except RuntimeError:
		return default


def _cfg_bool(key: str, default: bool = False) -> bool:
	value = _cfg(key, default)
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		text = value.strip().lower()
		if text in _TRUE_VALUES:
			return True
		if text in _FALSE_VALUES:
			return False
	return bool(value)


def _cfg_timeout() -> int:
	try:
		timeout = int(_cfg("APG_TIMEOUT", 15))
	except (TypeError, ValueError):
		return 15
	return max(_MIN_TIMEOUT_SECONDS, min(timeout, _MAX_TIMEOUT_SECONDS))


def _normalise_base_url(value: Any, default: str) -> str:
	text = str(value or default).strip()
	parsed = urllib.parse.urlsplit(text)
	if (
		parsed.scheme not in {"http", "https"}
		or not parsed.netloc
		or parsed.username is not None
		or parsed.password is not None
	):
		log.warning("Invalid APG base URL %r; falling back to %s", text, default)
		text = default
		parsed = urllib.parse.urlsplit(text)
	path = parsed.path.rstrip("/")
	return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _safe_header_value(value: Any) -> str | None:
	text = str(value or "").strip()
	if not text or not _SAFE_HEADER_VALUE_RE.fullmatch(text):
		return None
	return text


def _safe_path_segment(value: Any, field_name: str) -> str | None:
	text = str(value or "").strip()
	if not _SAFE_PATH_SEGMENT_RE.fullmatch(text):
		log.debug("Invalid APG %s path segment: %r", field_name, value)
		return None
	return urllib.parse.quote(text, safe="_.:-")


class APGError(Exception):
	"""Base exception for APG bridge errors."""


class APGAuthError(APGError):
	"""Raised when JWT authentication fails."""


class APGCapabilityError(APGError):
	"""Raised when a capability call returns an error response."""


class APGClient:
	"""Thin HTTP client for APG capability REST APIs and FastAPI marketplace.

	Never raises on network failures — callers decide how to handle None returns.
	Token is cached per-instance; call invalidate_token() to force re-login.
	"""

	_token: str | None = None

	# ── Config properties ──────────────────────────────────────────────────

	@property
	def _enabled(self) -> bool:
		return _cfg_bool("APG_ENABLED", False)

	@property
	def _base_url(self) -> str:
		return _normalise_base_url(_cfg("APG_BASE_URL", _APG_DEFAULT_BASE_URL), _APG_DEFAULT_BASE_URL)

	@property
	def _marketplace_url(self) -> str:
		return _normalise_base_url(
			_cfg("APG_MARKETPLACE_URL", _APG_DEFAULT_MARKETPLACE_URL),
			_APG_DEFAULT_MARKETPLACE_URL,
		)

	@property
	def _timeout(self) -> int:
		return _cfg_timeout()

	# ── Auth ───────────────────────────────────────────────────────────────

	def _get_token(self) -> str | None:
		"""Return JWT token from config or via login.  Returns None if unavailable."""
		static = _safe_header_value(_cfg("APG_STATIC_TOKEN", ""))
		if static:
			return static
		if self._token:
			return self._token
		email = str(_cfg("APG_AUTH_EMAIL", "") or "").strip()
		password = str(_cfg("APG_AUTH_PASSWORD", "") or "")
		if not (email and password):
			return None
		try:
			body = json.dumps({"email": email, "password": password}).encode()
			req = urllib.request.Request(
				f"{self._base_url}/api/auth/login",
				data=body,
				method="POST",
				headers={"Content-Type": "application/json"},
			)
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				data = self._read_json_response(resp)
				if not isinstance(data, dict):
					return None
				self._token = _safe_header_value(data.get("access_token", "")) or None
				return self._token
		except Exception as exc:
			log.debug("APGClient._get_token failed: %s", exc)
			return None

	def invalidate_token(self) -> None:
		"""Force re-authentication on the next request."""
		self._token = None

	def _headers(self) -> dict[str, str]:
		headers: dict[str, str] = {
			"Content-Type": "application/json",
			"Accept": "application/json",
		}
		token = self._get_token()
		if token:
			headers["Authorization"] = f"Bearer {token}"
		return headers

	# ── Low-level transport ────────────────────────────────────────────────

	def _build_url(self, path: str, *, marketplace: bool = False) -> str | None:
		if not isinstance(path, str) or not path.startswith("/"):
			log.debug("APGClient rejected invalid path: %r", path)
			return None
		parsed = urllib.parse.urlsplit(path)
		if parsed.scheme or parsed.netloc or "\\" in path or "\r" in path or "\n" in path:
			log.debug("APGClient rejected unsafe path: %r", path)
			return None
		base = self._marketplace_url if marketplace else self._base_url
		return f"{base}{path}"

	@staticmethod
	def _read_json_response(resp: Any) -> Any:
		raw = resp.read()
		if not raw:
			return {}
		try:
			if isinstance(raw, bytes):
				raw = raw.decode("utf-8")
			return json.loads(raw)
		except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
			log.debug("APGClient received invalid JSON response: %s", exc)
			return None

	def _get(self, path: str, *, marketplace: bool = False) -> Any | None:
		if not self._enabled:
			return None
		url = self._build_url(path, marketplace=marketplace)
		if url is None:
			return None
		req = urllib.request.Request(url, headers=self._headers())
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				return self._read_json_response(resp)
		except Exception as exc:
			log.debug("APGClient.GET %s failed: %s", path, exc)
			return None

	def _post(self, path: str, body: dict, *, marketplace: bool = False) -> Any | None:
		if not self._enabled:
			return None
		url = self._build_url(path, marketplace=marketplace)
		if url is None or not isinstance(body, dict):
			return None
		try:
			data = json.dumps(body).encode()
		except (TypeError, ValueError) as exc:
			log.debug("APGClient.POST %s rejected non-JSON body: %s", path, exc)
			return None
		req = urllib.request.Request(
			url, data=data, method="POST", headers=self._headers()
		)
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				return self._read_json_response(resp)
		except Exception as exc:
			log.debug("APGClient.POST %s failed: %s", path, exc)
			return None

	# ── Capability contract ────────────────────────────────────────────────

	def get_contract(self, capability_prefix: str) -> dict | None:
		"""Fetch APG capability contract (provides, requires, streaming, rules).

		GET /<capability_prefix>/contract
		"""
		prefix = _safe_path_segment(capability_prefix, "capability_prefix")
		if prefix is None:
			return None
		result = self._get(f"/{prefix}/contract")
		return result if isinstance(result, dict) else None

	def evaluate(self, capability_prefix: str, payload: dict) -> dict | None:
		"""POST /<capability_prefix>/evaluate — rule/workflow evaluation."""
		prefix = _safe_path_segment(capability_prefix, "capability_prefix")
		if prefix is None:
			return None
		result = self._post(f"/{prefix}/evaluate", payload)
		return result if isinstance(result, dict) else None

	def health_check(self, capability_prefix: str) -> bool:
		"""Return True if APG reports status=ok for the given capability."""
		prefix = _safe_path_segment(capability_prefix, "capability_prefix")
		if prefix is None:
			return False
		result = self._get(f"/{prefix}/health")
		return isinstance(result, dict) and result.get("status") == "ok"

	# ── Marketplace (FastAPI at APG_MARKETPLACE_URL) ───────────────────────

	def list_capabilities(self, domain: str | None = None) -> list[dict]:
		"""GET /capabilities[?domain=<domain>] — all available capabilities."""
		params = f"?{urllib.parse.urlencode({'domain': domain})}" if domain else ""
		result = self._get(f"/capabilities{params}", marketplace=True)
		if result is None:
			return []
		if isinstance(result, list):
			return result
		if isinstance(result, dict):
			return result.get("capabilities", [])
		return []

	def search_capabilities(self, query: str) -> list[dict]:
		"""POST /search — full-text search over capability registry."""
		query = str(query or "").strip()
		if not query:
			return []
		result = self._post("/search", {"query": query}, marketplace=True)
		if result is None:
			return []
		if isinstance(result, list):
			return result
		if isinstance(result, dict):
			return result.get("results", [])
		return []

	def get_capability_metadata(self, capability_id: str) -> dict | None:
		"""GET /capabilities/<capability_id> — detailed capability metadata."""
		capability_id = _safe_path_segment(capability_id, "capability_id")
		if capability_id is None:
			return None
		result = self._get(f"/capabilities/{capability_id}", marketplace=True)
		return result if isinstance(result, dict) else None

	# ── Event forwarding (Bytewax streams) ────────────────────────────────

	def emit_event(self, stream: str, event_type: str, payload: dict) -> bool:
		"""Forward a PgAppForge domain event to an APG Bytewax stream.

		Stream naming convention: apg.<domain>.<capability>.<lifecycle>
		Derived endpoint: POST /<domain>-<capability>/events

		Returns True if APG accepted the event; False otherwise.
		APG_EVENT_FORWARD=False short-circuits without logging noise.
		"""
		if not _cfg_bool("APG_EVENT_FORWARD", True):
			return False
		event_type = str(event_type or "").strip()
		if not event_type or not isinstance(payload, dict):
			return False
		# "apg.fintech.remittance.lifecycle" → "fintech-remittance"
		stream = str(stream or "").strip()
		parts = stream.split(".")
		if len(parts) >= 3:
			prefix = f"{parts[1]}-{parts[2]}"
		else:
			prefix = stream.replace(".", "-")
		prefix = _safe_path_segment(prefix, "stream")
		if prefix is None:
			return False
		body = {"event_type": event_type, "stream": stream, "payload": payload}
		result = self._post(f"/{prefix}/events", body)
		return result is not None

	# ── Connectivity ───────────────────────────────────────────────────────

	def is_available(self) -> bool:
		"""True if APG_ENABLED and the root /health endpoint responds."""
		if not self._enabled:
			return False
		result = self._get("/health")
		return result is not None


__all__ = ["APGClient", "APGError", "APGAuthError", "APGCapabilityError"]
