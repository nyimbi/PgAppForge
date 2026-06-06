"""
pgappforge/plugins/erp/crm/sign/__init__.py

SignPlugin — E-Sign Portal plugin.

Self-contained e-signature workflow: create requests, manage sequential or
parallel signing flows, capture drawn signatures, full audit trail,
and BPM integration for workflow-driven signing.

Depends on: foundation

Events emitted
--------------
  crm.sign.request.created
  crm.sign.signature.signed
  crm.sign.request.completed
  crm.sign.signature.declined
  crm.sign.request.expired

Events consumed
---------------
  workflow.instance.awaiting_signature
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SignPlugin(BasePlugin):
	"""E-Sign Portal plugin.

	Provides end-to-end e-signature capabilities: document signing request
	lifecycle, sequential/parallel signatory flows, access-token-based external
	signer links, signature image capture, tamper-evident audit log, expiry
	processing, and BPM action hooks for workflow integration.
	"""

	name = "sign"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="sign",
			version="1.0.0",
			description=(
				"E-Sign Portal — multi-party e-signature request lifecycle, "
				"sequential/parallel flows, audit trail, and BPM integration."
			),
			author="PgAppForge Contributors",
			tags=["crm", "e-sign", "signature", "contracts", "bpm"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_sign_request_create",
				"can_sign_request_view",
				"can_sign_request_send",
				"can_sign_request_cancel",
				"can_sign_audit_view",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"crm.sign.request.created",
			"crm.sign.signature.signed",
			"crm.sign.request.completed",
			"crm.sign.signature.declined",
			"crm.sign.request.expired",
		]

	def subscribe_to(self) -> list[str]:
		return ["workflow.instance.awaiting_signature"]

	def activate(self) -> None:
		"""Alias for initialize() — satisfies plugin protocol variants."""
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SIGN_MENU_CATEGORY": "Documents",
			"SIGN_DEFAULT_EXPIRY_DAYS": 30,
			"SIGN_ACCESS_TOKEN_BYTES": 32,
		}
		self.config = {**defaults, **self.config}
		log.info("SignPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.sign.models import (
			SignatureRequest,
			SignatureSignatory,
			SignatureAuditLog,
		)
		return [
			SignatureRequest,
			SignatureSignatory,
			SignatureAuditLog,
		]

	def register_views(self) -> None:
		log.info("SignPlugin: no views registered (views.py not yet implemented)")

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for sign business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("SignPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			{
				"name": "crm.sign.prevent_sign_on_non_pending",
				"description": "Signing is only allowed when signatory status is PENDING",
				"model_name": "SignatureSignatory",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_sign_wrong_status",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_status_new", "op": "eq", "value": "SIGNED"},
							{"field": "_status_old", "op": "neq", "value": "PENDING"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot sign: signatory is not in PENDING status",
							}
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("SignPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> SignPlugin:
	return SignPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Convenience re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.sign.models import (  # noqa: E402
	SignatureRequest,
	SignatureSignatory,
	SignatureAuditLog,
)
from pgappforge.plugins.erp.crm.sign.events import (  # noqa: E402
	SignatureRequestCreatedEvent,
	SignatureRequestSignedEvent,
	SignatureRequestCompletedEvent,
	SignatureRequestDeclinedEvent,
	SignatureRequestExpiredEvent,
)
from pgappforge.plugins.erp.crm.sign.services import (  # noqa: E402
	SignatureService,
	SignServiceError,
	SignNotFoundError,
	SignStateError,
)

__all__ = [
	# Plugin
	"SignPlugin",
	"create_plugin",
	# Models
	"SignatureRequest",
	"SignatureSignatory",
	"SignatureAuditLog",
	# Events
	"SignatureRequestCreatedEvent",
	"SignatureRequestSignedEvent",
	"SignatureRequestCompletedEvent",
	"SignatureRequestDeclinedEvent",
	"SignatureRequestExpiredEvent",
	# Services / Exceptions
	"SignatureService",
	"SignServiceError",
	"SignNotFoundError",
	"SignStateError",
]
