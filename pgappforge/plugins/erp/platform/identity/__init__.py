"""
pgappforge/plugins/erp/platform/identity/__init__.py

Platform Identity plugin — SSO providers, session management, MFA devices,
and fine-grained access policies.

Events emitted:
  identity.provider.created / deactivated
  identity.session.started / expired
  identity.mfa.device_verified / challenge_failed
  identity.policy.created / changed

Events consumed:
  (none — identity is foundational, consumed by downstream plugins)

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.platform.identity"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PlatformIdentityPlugin(BasePlugin):
	"""Platform Identity & Access Management plugin."""

	name = "platform.identity"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.identity",
			version="1.0.0",
			description=(
				"Identity & Access Management — SSO providers, user sessions, "
				"MFA devices, and fine-grained access policies."
			),
			author="PgAppForge Contributors",
			tags=["platform", "identity", "iam", "mfa", "sso", "rbac"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_identity_providers_read",
				"can_identity_providers_write",
				"can_identity_sessions_read",
				"can_identity_sessions_write",
				"can_identity_mfa_manage",
				"can_identity_policies_read",
				"can_identity_policies_write",
				"can_identity_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"identity.provider.created",
			"identity.provider.deactivated",
			"identity.session.started",
			"identity.session.expired",
			"identity.mfa.device_verified",
			"identity.mfa.challenge_failed",
			"identity.policy.created",
			"identity.policy.changed",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"IDENTITY_MENU_CATEGORY": "Security",
			"IDENTITY_DEFAULT_SESSION_HOURS": 8,
			"IDENTITY_MFA_REQUIRED_DEFAULT": False,
		}
		self.config = {**defaults, **self.config}
		log.info("PlatformIdentityPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.identity.views import (
			IdentityProviderView,
			UserSessionView,
			MFADeviceView,
			AccessPolicyView,
			IdentityReportView,
		)
		cat = self.config.get("IDENTITY_MENU_CATEGORY", "Security")
		self.add_view(IdentityProviderView, "Identity Providers", icon="fa-id-card", category=cat)
		self.add_view(AccessPolicyView, "Access Policies", icon="fa-shield", category=cat)
		self.add_view(IdentityReportView, "Identity Reports", icon="fa-bar-chart", category=cat)
		self.add_view_no_menu(UserSessionView)
		self.add_view_no_menu(MFADeviceView)
		log.info("PlatformIdentityPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.identity.models import (
			IdentityProvider,
			UserSession,
			MFADevice,
			AccessPolicy,
		)
		return [IdentityProvider, UserSession, MFADevice, AccessPolicy]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 rulesets for IAM domain invariants."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "identity_provider.single_default",
				"description": "Only one identity provider may be the default per tenant",
				"model_name": "IdentityProvider",
				"stop_on_match": True,
				"rules": [
					{
						"name": "enforce_single_default",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "is_default", "op": "eq", "value": True}
						],
						"actions_json": [
							{"type": "service_call",
							 "method": "clear_existing_defaults"}
						],
					}
				],
			},
			{
				"name": "user_session.expiry_required",
				"description": "Session must have a future expires_at",
				"model_name": "UserSession",
				"stop_on_match": True,
				"rules": [
					{
						"name": "expires_at_in_future",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "expires_at", "op": "lte", "value": "{{now}}"}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Session expires_at must be in the future"}
						],
					}
				],
			},
			{
				"name": "mfa_device.single_primary",
				"description": "Only one MFA device may be primary per user",
				"model_name": "MFADevice",
				"stop_on_match": True,
				"rules": [
					{
						"name": "enforce_single_primary",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "is_primary", "op": "eq", "value": True}
						],
						"actions_json": [
							{"type": "service_call", "method": "demote_existing_primary"}
						],
					}
				],
			},
			{
				"name": "access_policy.deny_overrides_allow",
				"description": "DENY effect supersedes ALLOW for same principal+resource",
				"model_name": "AccessPolicy",
				"stop_on_match": False,
				"rules": [
					{
						"name": "effect_must_be_valid",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "effect", "op": "not_in",
							 "value": ["ALLOW", "DENY"]}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "AccessPolicy.effect must be ALLOW or DENY"}
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
		log.info("PlatformIdentityPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> PlatformIdentityPlugin:
	return PlatformIdentityPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.identity.models import (  # noqa: E402
	IdentityProvider, UserSession, MFADevice, AccessPolicy,
)
from pgappforge.plugins.erp.platform.identity.services import (  # noqa: E402
	IdentityService, IdentityServiceError,
	ProviderNotFoundError, SessionNotFoundError, SessionExpiredError,
)

__all__ = [
	"PlatformIdentityPlugin",
	"create_plugin",
	"IdentityProvider",
	"UserSession",
	"MFADevice",
	"AccessPolicy",
	"IdentityService",
	"IdentityServiceError",
	"ProviderNotFoundError",
	"SessionNotFoundError",
	"SessionExpiredError",
]
