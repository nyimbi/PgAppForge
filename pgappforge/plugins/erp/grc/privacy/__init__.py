"""
pgappforge/plugins/erp/grc/privacy/__init__.py

GRC Privacy plugin — GDPR consent tracking, data subject requests, and
Article 30 data processing records.

Events emitted:
  privacy.consent.granted / withdrawn
  privacy.dsr.received / completed / overdue

Events consumed:
  party.created — create default consent records for new data subjects
  party.merged  — merge consent records on party deduplication

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.grc.privacy"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class GRCPrivacyPlugin(BasePlugin):
	"""GRC Privacy plugin — GDPR compliance tooling."""

	name = "grc.privacy"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="grc.privacy",
			version="1.0.0",
			description=(
				"GDPR Privacy — consent lifecycle, data subject requests "
				"(access/erasure/portability), and Article 30 processing records."
			),
			author="PgAppForge Contributors",
			tags=["grc", "privacy", "gdpr", "dsr", "consent", "ropa"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_privacy_consent_read",
				"can_privacy_consent_write",
				"can_privacy_dsr_read",
				"can_privacy_dsr_write",
				"can_privacy_processing_records_read",
				"can_privacy_processing_records_write",
				"can_privacy_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"privacy.consent.granted",
			"privacy.consent.withdrawn",
			"privacy.dsr.received",
			"privacy.dsr.completed",
			"privacy.dsr.overdue",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"party.created",
			"party.merged",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PRIVACY_MENU_CATEGORY": "GRC",
			"PRIVACY_DSR_DEADLINE_DAYS": 30,
			"PRIVACY_CONSENT_DEFAULT_EXPIRY_DAYS": None,
		}
		self.config = {**defaults, **self.config}
		log.info("GRCPrivacyPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.grc.privacy.views import (
			ConsentView,
			DSRView,
			DataProcessingView,
			PrivacyReportView,
		)
		cat = self.config.get("PRIVACY_MENU_CATEGORY", "GRC")
		self.add_view(ConsentView, "Consent Records", icon="fa-check-circle", category=cat)
		self.add_view(DSRView, "Data Subject Requests", icon="fa-user-secret", category=cat)
		self.add_view(DataProcessingView, "Processing Records", icon="fa-database", category=cat)
		self.add_view(PrivacyReportView, "Privacy Reports", icon="fa-bar-chart", category=cat)
		log.info("GRCPrivacyPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.grc.privacy.models import (
			ConsentRecord, DataSubjectRequest, DataProcessingRecord,
		)
		return [ConsentRecord, DataSubjectRequest, DataProcessingRecord]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 rulesets for privacy domain invariants."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "consent.legal_basis_valid",
				"description": "legal_basis must be one of GDPR Article 6 bases",
				"model_name": "ConsentRecord",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_legal_basis",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "legal_basis", "op": "not_in",
							 "value": [
								 "CONSENT", "CONTRACT", "LEGAL_OBLIGATION",
								 "VITAL_INTERESTS", "PUBLIC_TASK", "LEGITIMATE_INTERESTS",
							 ]}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "legal_basis must be a valid GDPR Article 6 basis"}
						],
					}
				],
			},
			{
				"name": "consent.immutable",
				"description": "ConsentRecord rows are append-only; never update",
				"model_name": "ConsentRecord",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_consent_update",
						"trigger_event": "on_before_update",
						"conditions_json": [{"field": "id", "op": "exists", "value": True}],
						"actions_json": [
							{"type": "raise_error",
							 "message": "ConsentRecord is immutable; insert a new row for changes"}
						],
					}
				],
			},
			{
				"name": "dsr.request_type_valid",
				"description": "request_type must be a valid DSR type",
				"model_name": "DataSubjectRequest",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_dsr_type",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "request_type", "op": "not_in",
							 "value": [
								 "ACCESS", "ERASURE", "RECTIFICATION",
								 "PORTABILITY", "RESTRICTION", "OBJECTION",
							 ]}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "request_type must be a valid DSR type"}
						],
					}
				],
			},
			{
				"name": "dsr.due_date_required",
				"description": "DSR must have a due_at date set at creation",
				"model_name": "DataSubjectRequest",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_due_at",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "due_at", "op": "eq", "value": None}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "DataSubjectRequest.due_at is required"}
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
		log.info("GRCPrivacyPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> GRCPrivacyPlugin:
	return GRCPrivacyPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.grc.privacy.models import (  # noqa: E402
	ConsentRecord, DataSubjectRequest, DataProcessingRecord,
)
from pgappforge.plugins.erp.grc.privacy.services import (  # noqa: E402
	PrivacyService, PrivacyServiceError, DSRNotFoundError, DSRStatusError,
)

__all__ = [
	"GRCPrivacyPlugin",
	"create_plugin",
	"ConsentRecord",
	"DataSubjectRequest",
	"DataProcessingRecord",
	"PrivacyService",
	"PrivacyServiceError",
	"DSRNotFoundError",
	"DSRStatusError",
]
