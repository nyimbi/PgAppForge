"""
pgappforge/plugins/erp/platform/credentials/__init__.py

Platform Digital Credentials plugin — W3C Verifiable Credentials + Open Badges 3.0.

Events emitted:
  credentials.schema.published
  credentials.credential.issued
  credentials.credential.revoked
  credentials.credential.verified
  credentials.credential.shared
  credentials.bulk_issue.completed

Events consumed:
  party.created  — seed issuer record if party_type == ORGANISATION

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.platform.credentials"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PlatformCredentialsPlugin(BasePlugin):
	"""Platform Digital Credentials plugin."""

	name = "platform.credentials"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.credentials",
			version="1.0.0",
			description=(
				"W3C Verifiable Credentials and Open Badges 3.0 — issue, verify, "
				"revoke, and share digital certificates, badges, licenses, and degrees."
			),
			author="PgAppForge Contributors",
			tags=[
				"platform", "credentials", "w3c", "open-badges",
				"verifiable-credentials", "certificates",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_credentials_schemas_read",
				"can_credentials_schemas_write",
				"can_credentials_issue",
				"can_credentials_revoke",
				"can_credentials_view",
				"can_credentials_bulk_issue",
				"can_credentials_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"credentials.schema.published",
			"credentials.credential.issued",
			"credentials.credential.revoked",
			"credentials.credential.verified",
			"credentials.credential.shared",
			"credentials.bulk_issue.completed",
		]

	def subscribe_to(self) -> list[str]:
		return ["party.created"]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CREDENTIALS_MENU_CATEGORY": "Credentials",
			"CREDENTIALS_BASE_URL": "https://credentials.example.com",
			"CREDENTIALS_DEFAULT_EXPIRY_DAYS": None,
			"CREDENTIALS_LINKEDIN_SHARE_ENABLED": True,
			"CREDENTIALS_QR_SIZE": 250,
		}
		self.config = {**defaults, **self.config}
		log.info("PlatformCredentialsPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.credentials.views import (
			CredentialSchemaView,
			IssuedCredentialView,
			VerificationPortalView,
			BulkIssueView,
			TranscriptView,
		)
		cat = self.config.get("CREDENTIALS_MENU_CATEGORY", "Credentials")
		self.add_view(CredentialSchemaView, "Credential Schemas", icon="fa-id-card", category=cat)
		self.add_view(IssuedCredentialView, "Issued Credentials", icon="fa-certificate", category=cat)
		self.add_view(BulkIssueView, "Bulk Issue", icon="fa-upload", category=cat)
		self.add_view_no_menu(VerificationPortalView)
		self.add_view_no_menu(TranscriptView)
		log.info("PlatformCredentialsPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.credentials.models import (
			CredentialSchema,
			IssuedCredential,
			CredentialShare,
			CredentialVerification,
		)
		return [CredentialSchema, IssuedCredential, CredentialShare, CredentialVerification]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure domain invariant rulesets for credentials."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "credential.immutable_after_issue",
				"description": "Issued credentials cannot have issuance fields mutated",
				"model_name": "IssuedCredential",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_recipient_change",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "recipient_id", "op": "changed", "value": True}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "recipient_id is immutable after issuance"}
						],
					},
					{
						"name": "block_schema_change",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "schema_id", "op": "changed", "value": True}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "schema_id is immutable after issuance"}
						],
					},
				],
			},
			{
				"name": "credential_schema.type_valid",
				"description": "credential_type must be a recognised value",
				"model_name": "CredentialSchema",
				"stop_on_match": True,
				"rules": [
					{
						"name": "type_in_allowed",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "credential_type",
								"op": "not_in",
								"value": [
									"CERTIFICATE", "BADGE", "LICENSE",
									"DEGREE", "MEMBERSHIP", "AWARD",
								],
							}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "credential_type must be one of: "
							            "CERTIFICATE BADGE LICENSE DEGREE MEMBERSHIP AWARD"}
						],
					}
				],
			},
			{
				"name": "credential_share.token_unique",
				"description": "share_token must be unique across all shares",
				"model_name": "CredentialShare",
				"stop_on_match": True,
				"rules": [
					{
						"name": "share_token_length",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "share_token", "op": "length_lt", "value": 64}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "share_token must be exactly 64 hex characters"}
						],
					}
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
		log.info(
			"PlatformCredentialsPlugin.setup_rules: %d rulesets configured",
			len(RULESETS),
		)


def create_plugin(
	appbuilder: Any, config: dict[str, Any] | None = None
) -> PlatformCredentialsPlugin:
	return PlatformCredentialsPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.credentials.models import (  # noqa: E402
	CredentialSchema, IssuedCredential, CredentialShare, CredentialVerification,
)
from pgappforge.plugins.erp.platform.credentials.services import (  # noqa: E402
	CredentialsService, CredentialsServiceError,
	SchemaNotFoundError, CredentialNotFoundError,
	CredentialAlreadyRevokedError, CredentialImmutableError,
)

__all__ = [
	"PlatformCredentialsPlugin",
	"create_plugin",
	# models
	"CredentialSchema",
	"IssuedCredential",
	"CredentialShare",
	"CredentialVerification",
	# services
	"CredentialsService",
	"CredentialsServiceError",
	"SchemaNotFoundError",
	"CredentialNotFoundError",
	"CredentialAlreadyRevokedError",
	"CredentialImmutableError",
]
