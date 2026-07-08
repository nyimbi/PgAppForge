"""
pgappforge/plugins/erp/platform/apg_bridge/services.py

APGBridgeService — capability discovery, event forwarding, BPM proxy.

Three integration modes
-----------------------
1. API proxy       — call any APG capability's /evaluate endpoint from
                     PgAppForge workflows via call_capability().
2. Capability sync — sync_capabilities_to_ipaas() registers all APG
                     marketplace capabilities as iPaaS ConnectorDefinitions.
3. Event bridge    — forward_event_to_apg() / register_event_bridge()
                     translate PgAppForge domain events into APG Bytewax
                     stream events.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.erp.platform.apg_bridge.client import APGClient

log = logging.getLogger(__name__)
_client = APGClient()
_MAX_ACTION_LENGTH = 128
_MAX_TENANT_ID_LENGTH = 64


def _required_text(value: Any, field_name: str, *, max_length: int) -> str:
	text = str(value or "").strip()
	if not text:
		raise ValueError(f"{field_name} is required")
	if len(text) > max_length:
		raise ValueError(f"{field_name} cannot exceed {max_length} characters")
	return text


class APGBridgeService:
	"""PgAppForge ↔ APG interoperability service."""

	# ── API Proxy ──────────────────────────────────────────────────────────

	def call_capability(
		self,
		capability_prefix: str,
		action: str,
		payload: dict,
		tenant_id: str,
	) -> dict:
		"""Call an APG capability action via its POST /evaluate endpoint.

		Args:
			capability_prefix: URL prefix, e.g. "fintech-remittance"
			action:            APG PROVIDES action, e.g. "remittance_quote_lifecycle"
			payload:           Input data for the action
			tenant_id:         Calling tenant — injected into the evaluate body

		Returns:
			{success: bool, result: dict|None, error: str|None}
		"""
		if not isinstance(payload, dict):
			return {"success": False, "error": "payload must be an object", "result": None}
		try:
			action = _required_text(action, "action", max_length=_MAX_ACTION_LENGTH)
			tenant_id = _required_text(
				tenant_id,
				"tenant_id",
				max_length=_MAX_TENANT_ID_LENGTH,
			)
		except ValueError as exc:
			return {"success": False, "error": str(exc), "result": None}
		body = {**payload, "action": action, "tenant_id": tenant_id}
		result = _client.evaluate(capability_prefix, body)
		if result is None:
			return {
				"success": False,
				"error": "APG capability unavailable or APG_ENABLED=False",
				"result": None,
			}
		return {"success": True, "result": result, "error": None}

	def get_capability_contract(self, capability_prefix: str) -> dict | None:
		"""Return the raw APG contract dict for a capability prefix."""
		return _client.get_contract(capability_prefix)

	# ── Capability Discovery + iPaaS sync ─────────────────────────────────

	def sync_capabilities_to_ipaas(self, tenant_id: str, session: Any) -> int:
		"""Register all APG marketplace capabilities as iPaaS ConnectorDefinitions.

		Each APG capability becomes a ConnectorDefinition with:
		  - name:     "APG:<capability_id>"
		  - protocol: REST
		  - auth_type: BEARER
		  - config_schema: JSON Schema with base_url / capability_prefix / action

		Skips capabilities already registered.  Returns the count of new registrations.
		"""
		try:
			from pgappforge.plugins.erp.platform.ipaas.models import ConnectorDefinition
			import sqlalchemy as sa
			import uuid as _uuid

			capabilities = _client.list_capabilities()
			registered = 0
			for cap in capabilities:
				cap_id = (
					cap.get("id")
					or cap.get("capability_id")
					or cap.get("name", "")
				)
				if not cap_id:
					continue
				connector_name = f"APG:{cap_id}"

				existing = session.execute(
					sa.select(ConnectorDefinition).where(
						ConnectorDefinition.name == connector_name,
					)
				).scalar_one_or_none()
				if existing:
					continue

				session.add(ConnectorDefinition(
					id=str(_uuid.uuid4()),
					tenant_id=tenant_id,
					name=connector_name,
					version="1.0",
					protocol="REST",
					auth_type="BEARER",
					config_schema={
						"type": "object",
						"properties": {
							"base_url": {
								"type": "string",
								"default": _client._base_url,
							},
							"capability_prefix": {
								"type": "string",
								"default": cap_id.replace("_", "-"),
							},
							"action": {"type": "string"},
						},
						"required": ["action"],
					},
				))
				registered += 1

			session.flush()
			log.info("APGBridgeService: synced %d capabilities to iPaaS", registered)
			return registered
		except Exception as exc:
			log.warning("sync_capabilities_to_ipaas failed: %s", exc)
			return 0

	# ── BPM Action Proxy ───────────────────────────────────────────────────

	def register_apg_bpm_actions(
		self,
		capabilities: list[str] | None = None,
	) -> int:
		"""Register BPM actions for APG capabilities.

		Each APG PROVIDES action becomes:
		  "apg.<capability_id>.<action>" → APGBridgeService.call_capability()

		Args:
			capabilities: Optional list of capability_id strings.
			              Defaults to all capabilities from the marketplace.

		Returns count of successfully registered BPM actions.
		"""
		try:
			from pgappforge.plugins.workflow.engine import BPMActionRegistry
		except ImportError:
			return 0

		raw_caps: list[Any] = (
			[{"id": c} for c in capabilities]
			if capabilities
			else _client.list_capabilities()
		)
		registered = 0

		for cap in raw_caps:
			cap_id = str(cap.get("id") or cap.get("name") or cap)
			prefix = cap_id.replace("_", "-")

			contract = _client.get_contract(prefix)
			if not contract:
				continue
			provides: list[str] = contract.get("provides", [])

			for action in provides:
				action_key = f"apg.{cap_id}.{action}"

				def _make_handler(cap_prefix: str, act: str):
					def _handler(
						record_ctx: dict,
						session: Any,
						**kw: Any,
					) -> dict:
						return APGBridgeService().call_capability(
							cap_prefix,
							act,
							kw,
							record_ctx.get("tenant_id", ""),
						)
					_handler.__name__ = f"_apg_{cap_prefix}_{act}"
					return _handler

				try:
					BPMActionRegistry.register(
						action_key,
						f"APG: {cap_id} — {action}",
					)(_make_handler(prefix, action))
					registered += 1
				except Exception:
					pass

		log.info("APGBridgeService: registered %d APG BPM actions", registered)
		return registered

	# ── Event Bridge ───────────────────────────────────────────────────────

	def forward_event_to_apg(
		self,
		event_type: str,
		payload: dict,
		apg_stream: str,
	) -> bool:
		"""Forward a PgAppForge domain event to an APG Bytewax stream.

		Returns True if APG accepted; False on any failure or if
		APG_EVENT_FORWARD=False.
		"""
		return _client.emit_event(apg_stream, event_type, payload)

	def register_event_bridge(self) -> int:
		"""Subscribe to PgAppForge events and auto-forward to APG streams.

		PgAppForge event_type → APG Bytewax stream name mapping:

		  finance.ap.invoice.created        → apg.fintech.payments.lifecycle
		  hcm.payroll.run.finalized         → apg.hcm.payroll.lifecycle
		  lending.loan.approved             → apg.fintech.lending.lifecycle
		  club.member.approved              → apg.crm.membership.lifecycle
		  sacco.member.approved             → apg.fintech.sacco.lifecycle
		  remittance.transfer.initiated     → apg.fintech.remittance.lifecycle
		  bnpl.application.approved         → apg.fintech.bnpl.lifecycle

		Returns count of successfully registered subscriptions.
		"""
		_EVENT_MAP: dict[str, str] = {
			"finance.ap.invoice.created":     "apg.fintech.payments.lifecycle",
			"hcm.payroll.run.finalized":      "apg.hcm.payroll.lifecycle",
			"lending.loan.approved":          "apg.fintech.lending.lifecycle",
			"club.member.approved":           "apg.crm.membership.lifecycle",
			"sacco.member.approved":          "apg.fintech.sacco.lifecycle",
			"remittance.transfer.initiated":  "apg.fintech.remittance.lifecycle",
			"bnpl.application.approved":      "apg.fintech.bnpl.lifecycle",
		}
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
		except ImportError:
			return 0

		registered = 0
		svc = APGBridgeService()

		for event_type, stream in _EVENT_MAP.items():
			def _make_forwarder(et: str, s: str):
				def handler(event: Any) -> None:
					payload: dict[str, Any] = {}
					for attr in ("aggregate_id", "aggregate_type", "tenant_id"):
						val = getattr(event, attr, None)
						if val is not None:
							payload[attr] = str(val)
					svc.forward_event_to_apg(et, payload, s)
				return handler

			try:
				subscribe(event_type, _make_forwarder(event_type, stream))
				registered += 1
			except Exception:
				pass

		log.info("APGBridgeService: registered %d event bridge subscriptions", registered)
		return registered

	# ── Status ─────────────────────────────────────────────────────────────

	def get_bridge_status(self) -> dict:
		"""Return current APG bridge runtime status dict."""
		return {
			"apg_enabled": bool(_client._enabled),
			"apg_available": _client.is_available(),
			"apg_base_url": _client._base_url,
			"marketplace_url": _client._marketplace_url,
			"event_forwarding": bool(_client._enabled),
		}


# ---------------------------------------------------------------------------
# Module-level BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register(
		"apg.bridge.call_capability",
		"Call any APG capability action via its /evaluate endpoint",
	)
	def _bpm_call_capability(
		record_ctx: dict,
		session: Any,
		capability_prefix: str = "",
		action: str = "",
		**kw: Any,
	) -> dict:
		return APGBridgeService().call_capability(
			capability_prefix,
			action,
			kw,
			record_ctx.get("tenant_id", ""),
		)

	@_BPMReg.register(
		"apg.bridge.sync_capabilities",
		"Sync APG marketplace capabilities to PgAppForge iPaaS ConnectorDefinitions",
	)
	def _bpm_sync_capabilities(
		record_ctx: dict,
		session: Any,
		**kw: Any,
	) -> dict:
		n = APGBridgeService().sync_capabilities_to_ipaas(
			record_ctx.get("tenant_id", ""),
			session,
		)
		return {"synced": n}

except (ImportError, Exception):
	pass


__all__ = ["APGBridgeService"]
