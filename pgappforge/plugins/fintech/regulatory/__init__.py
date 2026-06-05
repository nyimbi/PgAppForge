"""
pgappforge/plugins/fintech/regulatory/__init__.py

RegulatoryCompliancePlugin — Kenya fintech regulatory compliance suite.

Covers:
  - AML transaction monitoring (CBK AML Act, FATF Recommendations)
  - Suspicious Activity Reports (FRC Kenya goAML)
  - Basel III/IV capital adequacy (CBK Prudential Guideline 3)
  - IFRS 9 ECL provisioning (stage classification + ECL computation)
  - CBK prudential returns (BS1, BS3, BS6, CAR)
  - PEP register and enhanced due diligence

Depends on: core_banking, lending, payments, mobile_money, foundation

Registers
---------
  AMLRuleView          — AML Rules menu
  AMLAlertView         — AML Alerts menu
  SARView              — SAR Register menu
  CapitalAdequacyView  — Capital Adequacy menu
  IFRS9View            — IFRS 9 Provisions menu
  PEPListView          — PEP Register menu
  ComplianceDashboard  — /regulatory/dashboard/

Events emitted
--------------
  reg.aml.alert_generated, reg.aml.alert_escalated, reg.aml.alert_closed,
  reg.sar.filed, reg.sar.acknowledged,
  reg.capital.report_generated, reg.capital.breached,
  reg.ifrs9.run_completed,
  reg.pep.match_found, reg.pep.entry_added
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class RegulatoryCompliancePlugin(BasePlugin):
	"""Kenya fintech regulatory compliance plugin.

	Class-level identifiers:
	    name       = "regulatory"
	    domain     = "fintech"
	    depends_on = ["core_banking", "lending", "payments", "mobile_money", "foundation"]
	"""

	name = "regulatory"
	domain = "fintech"
	depends_on: list[str] = ["core_banking", "lending", "payments", "mobile_money", "foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="regulatory",
			version="1.0.0",
			description=(
				"Regulatory compliance suite for Kenya fintech: AML transaction monitoring, "
				"SAR filing with FRC Kenya, Basel III/IV capital adequacy, IFRS 9 ECL "
				"provisioning, CBK prudential returns, and PEP register management."
			),
			author="PgAppForge Contributors",
			tags=[
				"fintech", "regulatory", "aml", "sar", "frc-kenya",
				"basel-iii", "ifrs9", "ecl", "cbk", "pep", "fatf",
			],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_reg_aml_rule_list",
				"can_reg_aml_rule_write",
				"can_reg_aml_alert_list",
				"can_reg_aml_alert_investigate",
				"can_reg_aml_alert_escalate",
				"can_reg_sar_list",
				"can_reg_sar_file",
				"can_reg_capital_list",
				"can_reg_capital_compute",
				"can_reg_ifrs9_list",
				"can_reg_ifrs9_run",
				"can_reg_pep_list",
				"can_reg_pep_write",
				"can_reg_dashboard",
				"can_reg_cbk_returns",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		from pgappforge.plugins.fintech.regulatory.events import ALL_REG_EVENT_TYPES
		return ALL_REG_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		# Listen for new transactions to trigger AML screening
		return [
			"cb.account.credited",
			"cb.account.debited",
			"payments.payment.processed",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"REG_MENU_CATEGORY": "Regulatory Compliance",
			"REG_SEED_DEFAULT_AML_RULES": True,
			"REG_DEFAULT_CURRENCY": "KES",
			"REG_SAR_SLA_DAYS": 5,
			"REG_AML_SCREEN_ON_TRANSACTION": True,
		}
		self.config = {**defaults, **self.config}
		log.info("RegulatoryCompliancePlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		if self.config.get("REG_SEED_DEFAULT_AML_RULES", True):
			self._try_seed_aml_rules()

	def register_views(self) -> None:
		from pgappforge.plugins.fintech.regulatory.views import (
			AMLRuleView,
			AMLAlertView,
			SARView,
			CapitalAdequacyView,
			IFRS9View,
			PEPListView,
			ComplianceDashboard,
		)

		cat = self.config.get("REG_MENU_CATEGORY", "Regulatory Compliance")

		self.add_view(AMLRuleView, "AML Rules", icon="fa-shield", category=cat)
		self.add_view(AMLAlertView, "AML Alerts", icon="fa-exclamation-triangle", category=cat)
		self.add_view(SARView, "SAR Register", icon="fa-file-text", category=cat)
		self.add_view(CapitalAdequacyView, "Capital Adequacy", icon="fa-balance-scale", category=cat)
		self.add_view(IFRS9View, "IFRS 9 Provisions", icon="fa-line-chart", category=cat)
		self.add_view(PEPListView, "PEP Register", icon="fa-user-secret", category=cat)
		self.add_view(ComplianceDashboard, "Compliance Dashboard", icon="fa-tachometer", category=cat)

		log.info("RegulatoryCompliancePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.fintech.regulatory.models import (
			AMLRule,
			AMLAlert,
			SuspiciousActivityReport,
			CapitalAdequacyReport,
			IFRS9ProvisionRun,
			PEPList,
		)
		return [AMLRule, AMLAlert, SuspiciousActivityReport, CapitalAdequacyReport, IFRS9ProvisionRun, PEPList]

	# ------------------------------------------------------------------
	# Default AML rule seeding
	# ------------------------------------------------------------------

	@staticmethod
	def seed_default_aml_rules(session: Any, tenant_id: str = "default") -> int:
		"""Seed standard CBK/FATF AML rules if they don't exist.

		Inserts 6 rules covering:
		  1. AML-TH-001  THRESHOLD  KES 1,000,000 single transaction
		  2. AML-VL-001  VELOCITY   >10 transactions in 24 hours
		  3. AML-ST-001  STRUCTURING >3 sub-threshold transactions in 24h
		  4. AML-CR-001  COUNTRY_RISK FATF high-risk jurisdictions
		  5. AML-PEP-001 PEP        any transaction involving PEP
		  6. AML-HR-001  CUSTOMER_RISK high-risk customer rating ≥4

		Returns count of newly inserted rules. Idempotent.
		"""
		from sqlalchemy import select as _select
		from pgappforge.plugins.fintech.regulatory.models import AMLRule

		defaults = [
			{
				"rule_code": "AML-TH-001",
				"rule_name": "Large Cash Transaction Threshold",
				"rule_type": "THRESHOLD",
				"description": (
					"Flag any single transaction ≥ KES 1,000,000 as required by "
					"Kenya Proceeds of Crime and Anti-Money Laundering Act s.44."
				),
				"parameters": {"min_amount_cents": 100_000_000, "currency": "KES"},
				"risk_score": 70,
				"regulatory_reference": "POCAMLA s.44; FATF R.20",
			},
			{
				"rule_code": "AML-VL-001",
				"rule_name": "High Velocity Transaction Pattern",
				"rule_type": "VELOCITY",
				"description": "Flag customers with >10 debit transactions in any 24-hour window.",
				"parameters": {"max_transactions": 10, "period_hours": 24},
				"risk_score": 55,
				"regulatory_reference": "FATF R.20; CBK AML Guidelines para 4.3",
			},
			{
				"rule_code": "AML-ST-001",
				"rule_name": "Cash Structuring Detection",
				"rule_type": "STRUCTURING",
				"description": (
					"Detect smurfing: ≥3 transactions just below KES 1,000,000 "
					"reporting threshold within 24 hours."
				),
				"parameters": {
					"threshold_cents": 99_999_900,
					"window_hours": 24,
					"min_count": 3,
				},
				"risk_score": 85,
				"regulatory_reference": "POCAMLA s.3 (structuring offence); FATF R.20",
			},
			{
				"rule_code": "AML-CR-001",
				"rule_name": "High-Risk Country Transaction",
				"rule_type": "COUNTRY_RISK",
				"description": (
					"Flag transactions involving FATF-identified jurisdictions with "
					"strategic AML/CFT deficiencies (FATF black/grey list)."
				),
				"parameters": {
					"risk_countries": [
						"KP", "IR", "MM", "HT", "LA", "SY", "YE", "SD", "SS", "CF",
					],
					"action": "ALERT",
				},
				"risk_score": 90,
				"regulatory_reference": "FATF High-Risk Jurisdictions; CBK AML Guidelines para 6",
			},
			{
				"rule_code": "AML-PEP-001",
				"rule_name": "PEP Transaction Monitoring",
				"rule_type": "PEP",
				"description": (
					"Apply enhanced due diligence to all transactions involving "
					"politically exposed persons and their associates."
				),
				"parameters": {
					"pep_types": [
						"DOMESTIC_PEP", "FOREIGN_PEP",
						"INTERNATIONAL_ORGANIZATION_PEP",
						"CLOSE_ASSOCIATE", "FAMILY_MEMBER",
					]
				},
				"risk_score": 75,
				"regulatory_reference": "FATF R.12; CBK AML Guidelines para 5 (EDD for PEPs)",
			},
			{
				"rule_code": "AML-HR-001",
				"rule_name": "High Customer Risk Rating",
				"rule_type": "CUSTOMER_RISK",
				"description": "Flag any transaction from a customer with risk rating ≥4/5.",
				"parameters": {"min_risk_rating": 4},
				"risk_score": 65,
				"regulatory_reference": "CBK AML Guidelines para 3.4 (Risk-Based Approach)",
			},
		]

		inserted = 0
		for rd in defaults:
			existing = session.execute(
				_select(AMLRule).where(AMLRule.rule_code == rd["rule_code"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rule = AMLRule(
				tenant_id=tenant_id,
				rule_code=rd["rule_code"],
				rule_name=rd["rule_name"],
				rule_type=rd["rule_type"],
				description=rd["description"],
				parameters=rd["parameters"],
				risk_score=rd["risk_score"],
				regulatory_reference=rd.get("regulatory_reference"),
				is_active=True,
			)
			session.add(rule)
			inserted += 1

		if inserted:
			session.flush()
			log.info("RegulatoryCompliancePlugin: seeded %d default AML rules", inserted)
		return inserted

	def _try_seed_aml_rules(self) -> None:
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			tenant_id = self.config.get("REG_DEFAULT_TENANT_ID", "default")
			n = self.seed_default_aml_rules(session, tenant_id=tenant_id)
			if n:
				session.commit()
		except RuntimeError:
			pass  # No app context yet
		except Exception as exc:
			log.warning("RegulatoryCompliancePlugin._try_seed_aml_rules (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> RegulatoryCompliancePlugin:
	"""Construct and return a RegulatoryCompliancePlugin.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return RegulatoryCompliancePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.regulatory.models import (  # noqa: E402
	AMLRule,
	AMLAlert,
	SuspiciousActivityReport,
	CapitalAdequacyReport,
	IFRS9ProvisionRun,
	PEPList,
)
from pgappforge.plugins.fintech.regulatory.events import (  # noqa: E402
	AMLAlertGeneratedEvent,
	AMLAlertEscalatedEvent,
	AMLAlertClosedEvent,
	SARFiledEvent,
	SARAcknowledgedEvent,
	CapitalReportGeneratedEvent,
	CapitalBreachedEvent,
	IFRS9RunCompletedEvent,
	PEPMatchFoundEvent,
	PEPEntryAddedEvent,
	REG_AML_ALERT_GENERATED,
	REG_AML_ALERT_ESCALATED,
	REG_AML_ALERT_CLOSED,
	REG_SAR_FILED,
	REG_SAR_ACKNOWLEDGED,
	REG_CAPITAL_REPORT_GENERATED,
	REG_CAPITAL_BREACHED,
	REG_IFRS9_RUN_COMPLETED,
	REG_PEP_MATCH_FOUND,
	REG_PEP_ENTRY_ADDED,
	ALL_REG_EVENT_TYPES,
)
from pgappforge.plugins.fintech.regulatory.services import (  # noqa: E402
	RegulatoryComplianceService,
	RegulatoryError,
	AMLRuleNotFoundError,
	AMLAlertNotFoundError,
	SARAlreadyFiledError,
	InvalidAlertStatusError,
)
from pgappforge.plugins.fintech.regulatory.views import (  # noqa: E402
	AMLRuleView,
	AMLAlertView,
	SARView,
	CapitalAdequacyView,
	IFRS9View,
	PEPListView,
	ComplianceDashboard,
)

__all__ = [
	# plugin
	"RegulatoryCompliancePlugin",
	"create_plugin",
	# models
	"AMLRule",
	"AMLAlert",
	"SuspiciousActivityReport",
	"CapitalAdequacyReport",
	"IFRS9ProvisionRun",
	"PEPList",
	# events — classes
	"AMLAlertGeneratedEvent",
	"AMLAlertEscalatedEvent",
	"AMLAlertClosedEvent",
	"SARFiledEvent",
	"SARAcknowledgedEvent",
	"CapitalReportGeneratedEvent",
	"CapitalBreachedEvent",
	"IFRS9RunCompletedEvent",
	"PEPMatchFoundEvent",
	"PEPEntryAddedEvent",
	# events — type constants
	"REG_AML_ALERT_GENERATED",
	"REG_AML_ALERT_ESCALATED",
	"REG_AML_ALERT_CLOSED",
	"REG_SAR_FILED",
	"REG_SAR_ACKNOWLEDGED",
	"REG_CAPITAL_REPORT_GENERATED",
	"REG_CAPITAL_BREACHED",
	"REG_IFRS9_RUN_COMPLETED",
	"REG_PEP_MATCH_FOUND",
	"REG_PEP_ENTRY_ADDED",
	"ALL_REG_EVENT_TYPES",
	# services
	"RegulatoryComplianceService",
	"RegulatoryError",
	"AMLRuleNotFoundError",
	"AMLAlertNotFoundError",
	"SARAlreadyFiledError",
	"InvalidAlertStatusError",
	# views
	"AMLRuleView",
	"AMLAlertView",
	"SARView",
	"CapitalAdequacyView",
	"IFRS9View",
	"PEPListView",
	"ComplianceDashboard",
]
