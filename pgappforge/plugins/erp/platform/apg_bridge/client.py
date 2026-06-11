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
		return bool(_cfg("APG_ENABLED", False))

	@property
	def _base_url(self) -> str:
		return _cfg("APG_BASE_URL", "http://localhost:5000").rstrip("/")

	@property
	def _marketplace_url(self) -> str:
		return _cfg("APG_MARKETPLACE_URL", "http://localhost:8000").rstrip("/")

	@property
	def _timeout(self) -> int:
		return int(_cfg("APG_TIMEOUT", 15))

	# ── Auth ───────────────────────────────────────────────────────────────

	def _get_token(self) -> str | None:
		"""Return JWT token from config or via login.  Returns None if unavailable."""
		static = _cfg("APG_STATIC_TOKEN", "")
		if static:
			return static
		if self._token:
			return self._token
		email = _cfg("APG_AUTH_EMAIL", "")
		password = _cfg("APG_AUTH_PASSWORD", "")
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
				data = json.loads(resp.read())
				self._token = data.get("access_token", "") or None
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

	def _get(self, path: str, *, marketplace: bool = False) -> dict | None:
		if not self._enabled:
			return None
		base = self._marketplace_url if marketplace else self._base_url
		url = f"{base}{path}"
		req = urllib.request.Request(url, headers=self._headers())
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				return json.loads(resp.read())
		except Exception as exc:
			log.debug("APGClient.GET %s failed: %s", path, exc)
			return None

	def _post(self, path: str, body: dict, *, marketplace: bool = False) -> dict | None:
		if not self._enabled:
			return None
		base = self._marketplace_url if marketplace else self._base_url
		url = f"{base}{path}"
		data = json.dumps(body).encode()
		req = urllib.request.Request(
			url, data=data, method="POST", headers=self._headers()
		)
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				return json.loads(resp.read())
		except Exception as exc:
			log.debug("APGClient.POST %s failed: %s", path, exc)
			return None

	# ── Capability contract ────────────────────────────────────────────────

	def get_contract(self, capability_prefix: str) -> dict | None:
		"""Fetch APG capability contract (provides, requires, streaming, rules).

		GET /<capability_prefix>/contract
		"""
		return self._get(f"/{capability_prefix}/contract")

	def evaluate(self, capability_prefix: str, payload: dict) -> dict | None:
		"""POST /<capability_prefix>/evaluate — rule/workflow evaluation."""
		return self._post(f"/{capability_prefix}/evaluate", payload)

	def health_check(self, capability_prefix: str) -> bool:
		"""Return True if APG reports status=ok for the given capability."""
		result = self._get(f"/{capability_prefix}/health")
		return result is not None and result.get("status") == "ok"

	# ── Marketplace (FastAPI at APG_MARKETPLACE_URL) ───────────────────────

	def list_capabilities(self, domain: str | None = None) -> list[dict]:
		"""GET /capabilities[?domain=<domain>] — all available capabilities."""
		params = f"?domain={domain}" if domain else ""
		result = self._get(f"/capabilities{params}", marketplace=True)
		if result is None:
			return []
		return result if isinstance(result, list) else result.get("capabilities", [])

	def search_capabilities(self, query: str) -> list[dict]:
		"""POST /search — full-text search over capability registry."""
		result = self._post("/search", {"query": query}, marketplace=True)
		if result is None:
			return []
		return result if isinstance(result, list) else result.get("results", [])

	def get_capability_metadata(self, capability_id: str) -> dict | None:
		"""GET /capabilities/<capability_id> — detailed capability metadata."""
		return self._get(f"/capabilities/{capability_id}", marketplace=True)

	# ── Event forwarding (Bytewax streams) ────────────────────────────────

	def emit_event(self, stream: str, event_type: str, payload: dict) -> bool:
		"""Forward a PgAppForge domain event to an APG Bytewax stream.

		Stream naming convention: apg.<domain>.<capability>.<lifecycle>
		Derived endpoint: POST /<domain>-<capability>/events

		Returns True if APG accepted the event; False otherwise.
		APG_EVENT_FORWARD=False short-circuits without logging noise.
		"""
		if not _cfg("APG_EVENT_FORWARD", True):
			return False
		# "apg.fintech.remittance.lifecycle" → "fintech-remittance"
		parts = stream.split(".")
		if len(parts) >= 3:
			prefix = f"{parts[1]}-{parts[2]}"
		else:
			prefix = stream.replace(".", "-")
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
