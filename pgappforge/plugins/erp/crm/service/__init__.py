"""
pgappforge/plugins/erp/crm/service/__init__.py

ServicePlugin — Service Cloud ERP plugin.

Depends on: foundation (Party, DomainEventLog)

Events emitted
--------------
  service.case.created
  service.case.escalated
  service.case.resolved
  service.case.closed
  service.sla.breached
  service.survey.submitted
  service.knowledge.published

Events consumed
---------------
  ar.invoice.paid       — auto-close billing-related cases
  party.updated         — sync contact info on open cases

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.crm.service",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ServicePlugin(BasePlugin):
	"""Service Cloud plugin — cases, SLA, knowledge base, CSAT surveys."""

	name = "service"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="service",
			version="1.0.0",
			description=(
				"Service Cloud — full support lifecycle: cases, SLA policies, "
				"knowledge articles, case comments, and CSAT/NPS/CES surveys."
			),
			author="PgAppForge Contributors",
			tags=["erp", "crm", "service", "support", "sla", "knowledge"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_service_case_list",
				"can_service_case_write",
				"can_service_case_escalate",
				"can_service_case_resolve",
				"can_service_case_close",
				"can_service_sla_write",
				"can_service_knowledge_write",
				"can_service_knowledge_publish",
				"can_service_survey_write",
				"can_service_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"service.case.created",
			"service.case.escalated",
			"service.case.resolved",
			"service.case.closed",
			"service.sla.breached",
			"service.survey.submitted",
			"service.knowledge.published",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"ar.invoice.paid",   # auto-close billing cases
			"party.updated",     # sync contact details
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SERVICE_MENU_CATEGORY": "Service Cloud",
			"SERVICE_DEFAULT_PRIORITY": "P3",
			"SERVICE_SLA_BREACH_CHECK_INTERVAL_MINUTES": 15,
		}
		self.config = {**defaults, **self.config}
		log.info("ServicePlugin initialised")

	def post_initialize(self) -> None:
		self._subscribe_to_upstream_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.crm.service.views import (
			CaseView,
			KnowledgeArticleView,
			SLAPolicyView,
			ServiceReportView,
		)
		cat = self.config.get("SERVICE_MENU_CATEGORY", "Service Cloud")
		self.add_view(CaseView, "Cases", icon="fa-life-ring", category=cat)
		self.add_view(SLAPolicyView, "SLA Policies", icon="fa-clock-o", category=cat)
		self.add_view(KnowledgeArticleView, "Knowledge Base", icon="fa-book", category=cat)
		self.add_view(ServiceReportView, "Service Reports", icon="fa-chart-bar", category=cat)
		log.info("ServicePlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.service.models import (
			Case,
			CaseComment,
			KnowledgeArticle,
			SLAPolicy,
			SurveyResponse,
		)
		return [SLAPolicy, Case, KnowledgeArticle, CaseComment, SurveyResponse]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 Rules Engine rulesets for Service Cloud business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("ServicePlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Auto-escalate P1 cases that breach SLA
			{
				"name": "service.case.sla_breach_escalate",
				"description": "Auto-escalate P1 cases that have breached SLA without resolution",
				"model_name": "Case",
				"stop_on_match": False,
				"rules": [
					{
						"name": "escalate_p1_sla_breach",
						"trigger_event": "on_update",
						"conditions_json": [
							{"field": "priority", "op": "eq", "value": "P1"},
							{"field": "status", "op": "not_in", "value": ["RESOLVED", "CLOSED"]},
							{"field": "sla_breach_at", "op": "lte", "value": "{{now}}"},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "P1 case SLA breached — immediate escalation required",
							}
						],
					},
				],
			},
			# 2. Block closing unresolved cases
			{
				"name": "service.case.close_guard",
				"description": "Block CLOSED transition unless case is RESOLVED first",
				"model_name": "Case",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_direct_close",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "CLOSED"},
							{"field": "status", "op": "neq", "value": "RESOLVED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cases must be RESOLVED before they can be CLOSED",
							}
						],
					},
				],
			},
			# 3. CSAT score range validation
			{
				"name": "service.survey.csat_range",
				"description": "CSAT score must be 1-5",
				"model_name": "SurveyResponse",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_csat_range",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "survey_type", "op": "eq", "value": "CSAT"},
							{"field": "score", "op": "not_in", "value": [1, 2, 3, 4, 5]},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "CSAT score must be between 1 and 5",
							}
						],
					},
				],
			},
			# 4. Knowledge article publish guard
			{
				"name": "service.knowledge.publish_guard",
				"description": "Only DRAFT or REVIEW articles can be published",
				"model_name": "KnowledgeArticle",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_invalid_publish",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "PUBLISHED"},
							{"field": "status", "op": "not_in", "value": ["DRAFT", "REVIEW"]},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Only DRAFT or REVIEW articles can be published",
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
		log.info("ServicePlugin.setup_rules: %d rulesets configured", len(RULESETS))

	def _subscribe_to_upstream_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("party.updated", self._on_party_updated)
			log.debug("ServicePlugin: subscribed to party.updated")
		except Exception as exc:
			log.warning("ServicePlugin._subscribe_to_upstream_events failed: %s", exc)

	def _on_party_updated(self, event: Any) -> None:
		log.debug("ServicePlugin._on_party_updated: party=%s", event.aggregate_id)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> ServicePlugin:
	return ServicePlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.crm.service.models import (  # noqa: E402
	Case,
	CaseComment,
	KnowledgeArticle,
	SLAPolicy,
	SurveyResponse,
)
from pgappforge.plugins.erp.crm.service.events import (  # noqa: E402
	CaseCreatedEvent,
	CaseEscalatedEvent,
	CaseResolvedEvent,
	CaseClosedEvent,
	SLABreachedEvent,
	SurveySubmittedEvent,
	KnowledgeArticlePublishedEvent,
)
from pgappforge.plugins.erp.crm.service.services import (  # noqa: E402
	ServiceCloudService,
	ServiceCloudError,
	CaseNotFoundError,
	ServiceValidationError,
)

__all__ = [
	"ServicePlugin",
	"create_plugin",
	"SLAPolicy",
	"Case",
	"KnowledgeArticle",
	"CaseComment",
	"SurveyResponse",
	"CaseCreatedEvent",
	"CaseEscalatedEvent",
	"CaseResolvedEvent",
	"CaseClosedEvent",
	"SLABreachedEvent",
	"SurveySubmittedEvent",
	"KnowledgeArticlePublishedEvent",
	"ServiceCloudService",
	"ServiceCloudError",
	"CaseNotFoundError",
	"ServiceValidationError",
]
