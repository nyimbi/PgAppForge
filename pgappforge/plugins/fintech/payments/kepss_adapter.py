"""
pgappforge/plugins/fintech/payments/kepss_adapter.py

KEPSS — Kenya Electronic Payment and Settlement System (CBK RTGS).

Handles submission of ISO 20022 PAIN.001 XML batches to the CBK clearing
gateway, status polling, and ingestion of pacs.002 settlement reports.

Config keys (all in Flask app.config):
  KEPSS_BASE_URL      — default "https://kepss.cbk.go.ke/api/v1"
  KEPSS_MEMBER_BIC    — member bank BIC registered with CBK
  KEPSS_MEMBER_CODE   — CBK-assigned member code
  KEPSS_ENABLED       — bool, default False (mock mode when False)
"""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
import urllib.parse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

_PACS002_NS = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.03"

# Status mapping: ISO 20022 TxSts → internal PaymentOrder status
_PACS002_STATUS_MAP: dict[str, str] = {
	"ACSC": "SETTLED",   # AcceptedSettlementCompleted
	"RJCT": "RETURNED",  # Rejected
	"ACCP": "PROCESSING",  # AcceptedCustomerProfile
	"ACSP": "PROCESSING",  # AcceptedSettlementInProcess
	"PDNG": "PROCESSING",  # Pending
}


class KEPSSError(Exception):
	"""Raised when KEPSS API returns an error or is misconfigured."""
	pass


class KEPSSAdapter:
	"""Adapter for the CBK KEPSS RTGS clearing gateway.

	All HTTP calls use urllib (stdlib only — no extra dependencies).
	When KEPSS_ENABLED is False the adapter runs in mock mode, returning
	deterministic stub responses so the rest of the payment pipeline can be
	tested without a live CBK connection.
	"""

	# ── Config ─────────────────────────────────────────────────────────────────

	def _get_config(self) -> dict[str, Any]:
		"""Read Flask app.config; fall back to empty dict outside app context."""
		try:
			from flask import current_app
			return current_app.config  # type: ignore[return-value]
		except RuntimeError:
			return {}

	# ── Public API ──────────────────────────────────────────────────────────────

	def submit_rtgs(
		self,
		batch_id: str,
		pain001_xml: str,
		session: Any,
	) -> dict[str, Any]:
		"""Submit a PAIN.001 XML batch to KEPSS for RTGS settlement.

		Args:
			batch_id:    PaymentBatch.id (UUID string) — used as correlation key.
			pain001_xml: Fully-formed ISO 20022 PAIN.001.001.03 XML string.
			session:     SQLAlchemy session (reserved for future audit writes).

		Returns:
			dict with keys: status, submission_ref, timestamp (ISO-8601), kepss_enabled.

		# NOTE: The production CBK KEPSS gateway uses SWIFTNet FIN-Copy, not REST/HTTP.
		# This adapter implements an HTTP POST interface suitable for CBK's REST-based
		# sandbox/test environment or an institution's own KEPSS gateway proxy.
		# For production connectivity, configure a SWIFTNet Alliance adapter.
		"""
		cfg = self._get_config()
		enabled: bool = bool(cfg.get("KEPSS_ENABLED", False))

		if not enabled:
			log.info("KEPSSAdapter.submit_rtgs: mock mode — batch_id=%s", batch_id)
			return {
				"status": "MOCK_ACCEPTED",
				"submission_ref": "MOCK-" + batch_id[:8],
				"timestamp": _utcnow_iso(),
				"kepss_enabled": False,
			}

		base_url: str = cfg.get("KEPSS_BASE_URL", "https://kepss.cbk.go.ke/api/v1")
		member_bic: str = cfg.get("KEPSS_MEMBER_BIC", "")
		member_code: str = cfg.get("KEPSS_MEMBER_CODE", "")

		url = f"{base_url.rstrip('/')}/submissions"
		body = pain001_xml.encode("utf-8")

		req = urllib.request.Request(
			url,
			data=body,
			method="POST",
			headers={
				"Content-Type": "application/xml; charset=utf-8",
				"X-KEPSS-Member-BIC": member_bic,
				"X-KEPSS-Member-Code": member_code,
				"X-Batch-Id": batch_id,
			},
		)

		try:
			with urllib.request.urlopen(req, timeout=30) as resp:
				raw = resp.read().decode("utf-8", errors="replace")
				status_code = resp.status
		except urllib.error.HTTPError as exc:
			raw = exc.read().decode("utf-8", errors="replace")
			raise KEPSSError(
				f"KEPSS submission failed HTTP {exc.code} for batch {batch_id}: {raw}"
			) from exc
		except urllib.error.URLError as exc:
			raise KEPSSError(
				f"KEPSS connection error for batch {batch_id}: {exc.reason}"
			) from exc

		try:
			payload = json.loads(raw)
		except json.JSONDecodeError:
			payload = {"raw_response": raw}

		log.info(
			"KEPSSAdapter.submit_rtgs: HTTP %s batch_id=%s ref=%s",
			status_code,
			batch_id,
			payload.get("submission_ref", "—"),
		)

		return {
			"status": payload.get("status", "ACCEPTED"),
			"submission_ref": payload.get("submission_ref", ""),
			"timestamp": payload.get("timestamp", _utcnow_iso()),
			"kepss_enabled": True,
		}

	def query_status(self, submission_ref: str) -> dict[str, Any]:
		"""Poll KEPSS for the settlement status of a prior submission.

		Args:
			submission_ref: Reference returned by :meth:`submit_rtgs`.

		Returns:
			dict with keys: submission_ref, status, timestamp, kepss_enabled.
		"""
		cfg = self._get_config()
		enabled: bool = bool(cfg.get("KEPSS_ENABLED", False))

		if not enabled:
			log.debug("KEPSSAdapter.query_status: mock mode ref=%s", submission_ref)
			return {
				"submission_ref": submission_ref,
				"status": "MOCK_SETTLED",
				"timestamp": _utcnow_iso(),
				"kepss_enabled": False,
			}

		base_url: str = cfg.get("KEPSS_BASE_URL", "https://kepss.cbk.go.ke/api/v1")
		member_bic: str = cfg.get("KEPSS_MEMBER_BIC", "")
		member_code: str = cfg.get("KEPSS_MEMBER_CODE", "")

		url = f"{base_url.rstrip('/')}/submissions/{urllib.parse.quote(submission_ref, safe='')}"
		req = urllib.request.Request(
			url,
			method="GET",
			headers={
				"Accept": "application/json",
				"X-KEPSS-Member-BIC": member_bic,
				"X-KEPSS-Member-Code": member_code,
			},
		)

		try:
			with urllib.request.urlopen(req, timeout=30) as resp:
				raw = resp.read().decode("utf-8", errors="replace")
				status_code = resp.status
		except urllib.error.HTTPError as exc:
			raw = exc.read().decode("utf-8", errors="replace")
			raise KEPSSError(
				f"KEPSS status query failed HTTP {exc.code} ref={submission_ref}: {raw}"
			) from exc
		except urllib.error.URLError as exc:
			raise KEPSSError(
				f"KEPSS connection error querying {submission_ref}: {exc.reason}"
			) from exc

		try:
			payload = json.loads(raw)
		except json.JSONDecodeError:
			payload = {"raw_response": raw}

		log.debug(
			"KEPSSAdapter.query_status: HTTP %s ref=%s status=%s",
			status_code,
			submission_ref,
			payload.get("status", "—"),
		)

		return {
			"submission_ref": submission_ref,
			"status": payload.get("status", "UNKNOWN"),
			"timestamp": payload.get("timestamp", _utcnow_iso()),
			"kepss_enabled": True,
		}

	def ingest_settlement_report(
		self,
		report_xml: str,
		session: Any,
	) -> dict[str, int]:
		"""Parse a pacs.002 settlement report and update PaymentOrder records.

		Each TxInfAndSts element maps OrgnlEndToEndId → TxSts.  Matched orders
		are updated in the current SQLAlchemy session (caller must commit).

		Args:
			report_xml: Raw pacs.002.001.03 XML string from CBK.
			session:    Active SQLAlchemy session.

		Returns:
			dict with keys: matched (int), unmatched (int), rejected (int).
		"""
		from pgappforge.plugins.fintech.payments.models import PaymentOrder, PaymentStatusEvent  # local import avoids circular

		try:
			root = ET.fromstring(report_xml)
		except ET.ParseError as exc:
			raise KEPSSError(f"Invalid pacs.002 XML: {exc}") from exc

		# Detect namespace from root.tag to handle both versioned and bare XML gracefully
		ns_match = re.search(r'\{([^}]+)\}', root.tag or '')
		ns = '{' + ns_match.group(1) + '}' if ns_match else ''

		# pacs.002 structure: Document/FIToFIPmtStsRpt/TxInfAndSts (repeated)
		tx_elements = root.findall(f".//{ns}TxInfAndSts")

		matched = 0
		unmatched = 0
		rejected = 0

		for tx in tx_elements:
			end_to_end_id = _find_text(tx, f"{ns}OrgnlEndToEndId")
			tx_sts = _find_text(tx, f"{ns}TxSts")

			if not end_to_end_id or not tx_sts:
				log.warning("KEPSSAdapter.ingest_settlement_report: skipping element missing OrgnlEndToEndId or TxSts")
				unmatched += 1
				continue

			new_status = _PACS002_STATUS_MAP.get(tx_sts.upper())
			if new_status is None:
				log.warning(
					"KEPSSAdapter.ingest_settlement_report: unknown TxSts=%r for EndToEndId=%r",
					tx_sts, end_to_end_id,
				)
				unmatched += 1
				continue

			order = (
				session.query(PaymentOrder)
				.filter(PaymentOrder.payment_reference == end_to_end_id)
				.first()
			)
			if order is None:
				log.warning(
					"KEPSSAdapter.ingest_settlement_report: no PaymentOrder for reference=%r",
					end_to_end_id,
				)
				unmatched += 1
				continue

			prev_status = order.status
			session.execute(
				sa.update(PaymentOrder)
				.where(PaymentOrder.id == order.id)
				.values(status=new_status)
			)
			session.add(PaymentStatusEvent(
				tenant_id=order.tenant_id,
				payment_order_id=order.id,
				from_status=prev_status,
				to_status=new_status,
				actor_id="kepss_settlement",
			))
			session.flush()

			log.info(
				"KEPSSAdapter.ingest_settlement_report: %r %s → %s",
				end_to_end_id, prev_status, new_status,
			)
			matched += 1
			if new_status == "RETURNED":
				rejected += 1

		log.info(
			"KEPSSAdapter.ingest_settlement_report: matched=%d unmatched=%d rejected=%d",
			matched, unmatched, rejected,
		)
		return {"matched": matched, "unmatched": unmatched, "rejected": rejected}


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _utcnow_iso() -> str:
	return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_text(element: ET.Element, tag: str) -> str | None:
	"""Return .text of the first matching child element, or None."""
	child = element.find(tag)
	if child is not None and child.text:
		return child.text.strip()
	return None


__all__ = ["KEPSSAdapter", "KEPSSError"]
