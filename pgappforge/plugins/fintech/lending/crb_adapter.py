"""
pgappforge/plugins/fintech/lending/crb_adapter.py

Kenya Credit Reference Bureau (CRB) integration adapter.

Providers supported:
	- TransUnion KE  (HMAC-SHA256 signed REST)
	- Metropol       (OAuth2 client_credentials REST)
	- Mock           (deterministic, no network)

Config keys read from Flask app config:
	CRB_PROVIDER      — "TRANSUNION" | "METROPOL" | "MOCK"  (default: MOCK)
	CRB_API_KEY       — provider key / client_id
	CRB_API_SECRET    — provider secret
	CRB_BASE_URL      — base URL override (optional)
	CRB_TIMEOUT_SECS  — int, default 10
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CRBError(Exception):
	"""Base exception for all CRB adapter failures."""


class CRBUnavailableError(CRBError):
	"""Bureau service is unreachable or returned an unexpected HTTP status."""


class CRBIdentityNotFoundError(CRBError):
	"""The requested identity (ID number) was not found in the bureau database."""


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class CRBResponse:
	provider: str
	reference: str
	score: int
	default_probability_pct: Decimal
	active_facilities: int
	npas: int
	delinquent_accounts: int
	total_outstanding_cents: int
	listed_negative: bool
	raw_response: dict
	checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

	def to_dict(self) -> dict[str, Any]:
		return {
			"provider": self.provider,
			"reference": self.reference,
			"score": self.score,
			"default_probability_pct": str(self.default_probability_pct),
			"active_facilities": self.active_facilities,
			"npas": self.npas,
			"delinquent_accounts": self.delinquent_accounts,
			"total_outstanding_cents": self.total_outstanding_cents,
			"listed_negative": self.listed_negative,
			"checked_at": self.checked_at.isoformat(),
		}


# ---------------------------------------------------------------------------
# TransUnion KE adapter
# ---------------------------------------------------------------------------

class TransUnionKEAdapter:
	"""TransUnion Kenya CRB adapter.

	Auth: HMAC-SHA256 signature over f"{timestamp}\\n{nonce}\\n{sha256_body_hex}"
	Authorization header format:
		TransUnion apikey=...,timestamp=...,nonce=...,signature=...
	"""

	_PROVIDER = "TRANSUNION_KE"

	def __init__(
		self,
		api_key: str,
		api_secret: str,
		base_url: str = "",
		timeout: int = 10,
	) -> None:
		self._api_key = api_key
		self._api_secret = api_secret
		self._base_url = base_url.rstrip("/")
		self._timeout = timeout

	def _sign(self, body_bytes: bytes) -> tuple[str, str, str]:
		"""Return (timestamp, nonce, signature) for the given body."""
		timestamp = str(int(time.time()))
		nonce = secrets.token_hex(16)
		body_hash = hashlib.sha256(body_bytes).hexdigest()
		message = f"{timestamp}\n{nonce}\n{body_hash}"
		signature = hmac.new(
			self._api_secret.encode("utf-8"),
			message.encode("utf-8"),
			hashlib.sha256,
		).hexdigest()
		return timestamp, nonce, signature

	def inquire(
		self,
		id_number: str,
		id_type: str = "NATIONAL_ID",
		full_name: str = "",
		phone_msisdn: str = "",
	) -> CRBResponse:
		"""POST an inquiry to TransUnion KE and return a CRBResponse."""
		payload = {
			"id_number": id_number,
			"id_type": id_type,
			"full_name": full_name,
			"phone": phone_msisdn,
		}
		body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
		timestamp, nonce, signature = self._sign(body_bytes)

		auth_header = (
			f"TransUnion apikey={self._api_key},"
			f"timestamp={timestamp},"
			f"nonce={nonce},"
			f"signature={signature}"
		)

		url = self._base_url + "/inquiries"
		req = urllib.request.Request(
			url,
			data=body_bytes,
			method="POST",
			headers={
				"Content-Type": "application/json",
				"Authorization": auth_header,
			},
		)

		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				raw = json.loads(resp.read().decode("utf-8"))
		except urllib.error.HTTPError as exc:
			body = ""
			try:
				body = exc.read().decode("utf-8", errors="replace")
			except Exception:
				pass
			if exc.code == 404:
				raise CRBIdentityNotFoundError(
					f"TransUnion KE: identity not found for id_number={id_number!r}"
				) from exc
			raise CRBUnavailableError(
				f"TransUnion KE HTTP {exc.code}: {body[:200]}"
			) from exc
		except Exception as exc:
			raise CRBUnavailableError(f"TransUnion KE request failed: {exc}") from exc

		# NOTE: Response schema below is based on TransUnion KE's documented API format.
		# Keys: score.value (int), score.pd_pct (Decimal str), credit_summary.active_accounts (int),
		# credit_summary.npa_count (int), credit_summary.delinquent_count (int),
		# credit_summary.total_outstanding_kes (float str), negative_listing (bool).
		# Verify against current TransUnion KE Developer Portal before going live.
		try:
			score = int(raw["score"]["value"])
			pd_pct = Decimal(str(raw["score"]["pd_pct"]))
			summary = raw["credit_summary"]
			active_facilities = int(summary["active_accounts"])
			npas = int(summary["npa_count"])
			delinquent_accounts = int(summary["delinquent_count"])
			total_outstanding_cents = int(float(summary["total_outstanding_kes"]) * 100)
			listed_negative = bool(raw.get("negative_listing", False))
			reference = str(raw.get("reference", ""))
		except (KeyError, TypeError, ValueError) as exc:
			raise CRBError(f"TransUnion KE: unexpected response structure: {exc}") from exc

		return CRBResponse(
			provider=self._PROVIDER,
			reference=reference,
			score=score,
			default_probability_pct=pd_pct,
			active_facilities=active_facilities,
			npas=npas,
			delinquent_accounts=delinquent_accounts,
			total_outstanding_cents=total_outstanding_cents,
			listed_negative=listed_negative,
			raw_response=raw,
		)


# ---------------------------------------------------------------------------
# Metropol adapter
# ---------------------------------------------------------------------------

class MetropolAdapter:
	"""Metropol Kenya CRB adapter.

	Auth: OAuth2 client_credentials.  Token cached until expiry.
	"""
	# NOTE: Metropol's production API uses HMAC-SHA256 signing with X-API-KEY and
	# X-METROPOL-REST-API-PUBLIC-KEY headers, NOT OAuth2. This adapter implements
	# an OAuth2-compatible flow for testing. Replace with Metropol's actual HMAC
	# signing per https://metropol.co.ke/api-docs before going live.

	_PROVIDER = "METROPOL_KE"
	_TOKEN_URL = "https://api.metropol.co.ke/oauth/token"

	def __init__(
		self,
		api_key: str,
		api_secret: str,
		base_url: str = "",
		timeout: int = 10,
	) -> None:
		self._client_id = api_key
		self._client_secret = api_secret
		self._base_url = base_url.rstrip("/")
		self._timeout = timeout
		self._token: str | None = None
		self._token_expires_at: float = 0.0

	def _ensure_token(self) -> str:
		"""Return a valid bearer token, refreshing if necessary."""
		now = time.time()
		if self._token and now < self._token_expires_at - 30:
			return self._token

		body = urllib.parse.urlencode({
			"grant_type": "client_credentials",
			"client_id": self._client_id,
			"client_secret": self._client_secret,
		}).encode("utf-8")

		req = urllib.request.Request(
			self._TOKEN_URL,
			data=body,
			method="POST",
			headers={"Content-Type": "application/x-www-form-urlencoded"},
		)
		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				token_data = json.loads(resp.read().decode("utf-8"))
		except Exception as exc:
			raise CRBUnavailableError(f"Metropol token fetch failed: {exc}") from exc

		self._token = token_data["access_token"]
		expires_in = int(token_data.get("expires_in", 3600))
		self._token_expires_at = now + expires_in
		return self._token

	def inquire(
		self,
		id_number: str,
		id_type: str = "NATIONAL_ID",
		full_name: str = "",
		phone_msisdn: str = "",
	) -> CRBResponse:
		"""POST an inquiry to Metropol and return a CRBResponse."""
		token = self._ensure_token()

		payload = {
			"identity_number": id_number,
			"identity_type": id_type,
			"full_name": full_name,
			"mobile_number": phone_msisdn,
		}
		body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

		url = self._base_url + "/report"
		req = urllib.request.Request(
			url,
			data=body_bytes,
			method="POST",
			headers={
				"Content-Type": "application/json",
				"Authorization": f"Bearer {token}",
			},
		)

		try:
			with urllib.request.urlopen(req, timeout=self._timeout) as resp:
				raw = json.loads(resp.read().decode("utf-8"))
		except urllib.error.HTTPError as exc:
			body = ""
			try:
				body = exc.read().decode("utf-8", errors="replace")
			except Exception:
				pass
			if exc.code == 404:
				raise CRBIdentityNotFoundError(
					f"Metropol: identity not found for id_number={id_number!r}"
				) from exc
			raise CRBUnavailableError(
				f"Metropol HTTP {exc.code}: {body[:200]}"
			) from exc
		except Exception as exc:
			raise CRBUnavailableError(f"Metropol request failed: {exc}") from exc

		try:
			cs = raw["credit_score"]
			score = int(cs["score"])
			pd_pct = Decimal(str(cs.get("pd_pct", "0")))
			acct = raw["account_summary"]
			active_facilities = int(acct.get("active_accounts", 0))
			npas = int(acct.get("npa_count", 0))
			delinquent_accounts = int(acct.get("delinquent_count", 0))
			total_outstanding_cents = int(float(acct.get("total_outstanding_kes", 0)) * 100)
			listed_negative = bool(raw.get("negative_listing", False))
			reference = str(raw.get("report_reference", raw.get("reference", "")))
		except (KeyError, TypeError, ValueError) as exc:
			raise CRBError(f"Metropol: unexpected response structure: {exc}") from exc

		return CRBResponse(
			provider=self._PROVIDER,
			reference=reference,
			score=score,
			default_probability_pct=pd_pct,
			active_facilities=active_facilities,
			npas=npas,
			delinquent_accounts=delinquent_accounts,
			total_outstanding_cents=total_outstanding_cents,
			listed_negative=listed_negative,
			raw_response=raw,
		)


# ---------------------------------------------------------------------------
# Mock adapter
# ---------------------------------------------------------------------------

class MockCRBAdapter:
	"""Deterministic mock CRB adapter — no network calls.

	Score = 400 + (first 4 hex chars of SHA-256(id_number) as int) % 500
	Range: [400, 899]
	"""

	_PROVIDER = "MOCK"

	def inquire(
		self,
		id_number: str,
		id_type: str = "NATIONAL_ID",
		full_name: str = "",
		phone_msisdn: str = "",
	) -> CRBResponse:
		digest = hashlib.sha256(id_number.encode("utf-8")).hexdigest()
		score = 400 + (int(digest[:4], 16) % 500)

		default_probability_pct = (
			Decimal("2.0") if score >= 750
			else Decimal("8.0") if score >= 650
			else Decimal("20.0") if score >= 550
			else Decimal("45.0")
		)

		return CRBResponse(
			provider=self._PROVIDER,
			reference=f"MOCK-{digest[:12].upper()}",
			score=score,
			default_probability_pct=default_probability_pct,
			active_facilities=1,
			npas=0,
			delinquent_accounts=0,
			total_outstanding_cents=0,
			listed_negative=False,
			raw_response={
				"mock": True,
				"id_number": id_number,
				"score": score,
			},
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_crb_adapter() -> TransUnionKEAdapter | MetropolAdapter | MockCRBAdapter:
	"""Return the configured CRB adapter.

	Reads from Flask app config (CRB_PROVIDER, CRB_API_KEY, CRB_API_SECRET,
	CRB_BASE_URL, CRB_TIMEOUT_SECS).

	Falls back to MockCRBAdapter when:
	- No Flask application context is available (RuntimeError on import).
	- CRB_PROVIDER is "MOCK" or absent.
	- CRB_API_KEY is empty or missing.
	"""
	try:
		from flask import current_app
		cfg = current_app.config
	except RuntimeError:
		log.debug("get_crb_adapter: no Flask context — using MockCRBAdapter")
		return MockCRBAdapter()

	provider = str(cfg.get("CRB_PROVIDER", "MOCK")).upper()
	api_key = str(cfg.get("CRB_API_KEY", "") or "")
	api_secret = str(cfg.get("CRB_API_SECRET", "") or "")
	base_url = str(cfg.get("CRB_BASE_URL", "") or "")
	timeout = int(cfg.get("CRB_TIMEOUT_SECS", 10))

	if not api_key or provider == "MOCK":
		return MockCRBAdapter()

	if provider == "TRANSUNION":
		return TransUnionKEAdapter(
			api_key=api_key,
			api_secret=api_secret,
			base_url=base_url,
			timeout=timeout,
		)

	if provider == "METROPOL":
		return MetropolAdapter(
			api_key=api_key,
			api_secret=api_secret,
			base_url=base_url,
			timeout=timeout,
		)

	log.warning("Unknown CRB_PROVIDER %r — falling back to MockCRBAdapter", provider)
	return MockCRBAdapter()


__all__ = [
	"CRBError",
	"CRBUnavailableError",
	"CRBIdentityNotFoundError",
	"CRBResponse",
	"TransUnionKEAdapter",
	"MetropolAdapter",
	"MockCRBAdapter",
	"get_crb_adapter",
]
