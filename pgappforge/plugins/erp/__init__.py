"""
pgappforge/plugins/erp/__init__.py

ERP Plugin Registry — composability framework, metadata catalogue, and
``install_all()`` orchestration helper.

Usage
-----
Register every ERP plugin in one call::

    from pgappforge.plugins.erp import install_all
    install_all(appbuilder)

Or cherry-pick a group::

    from pgappforge.plugins.erp import ERP_GROUPS
    for entry in ERP_GROUPS["finance"]["plugins"]:
        entry["plugin_class"](appbuilder).activate()

Plugin Groups
-------------
  foundation          — shared master-data (Party, Currency, Country, …)
  platform.identity   — SSO providers, MFA, session mgmt, access policies
  platform.events     — event bus: subscriptions, delivery, dead-letter queue
  finance.gl          — General Ledger
  finance.ap          — Accounts Payable
  finance.ar          — Accounts Receivable
  finance.assets      — Fixed Assets & depreciation
  finance.tax         — Tax management & filing
  finance.treasury    — Cash, FX deals, bank reconciliation
  crm.sales           — Leads, opportunities, forecasting
  crm.cpq             — Configure-Price-Quote
  crm.service         — Cases, SLA, knowledge base
  crm.field_service   — Work orders, territories, appointments
  crm.marketing       — Campaigns, journeys, lists
  crm.commerce        — Subscriptions, shipping, tax rules
  operations.scm      — Supply-chain: suppliers, shipments
  operations.inventory— Stock control, product catalogue
  operations.warehouse— WMS: picklists, put-away, stock counts
  operations.production— Production orders, BOM, scheduling
  operations.quality  — QC inspections, NCRs
  hcm.org             — Legal entities, org units, positions
  hcm.personnel       — Employee records, compensation
  hcm.time            — Timesheets, attendance, leave
  hcm.payroll         — Payroll runs, payslips, statutory filing
  hcm.talent          — Recruitment, performance, training
  grc.controls        — Controls testing, SoD conflict detection
  grc.privacy         — GDPR/CCPA consent, DSR management
  grc.sustainability  — ESG metrics, emissions, reporting
  analytics.operational— KPIs, snapshots, scheduled reports
  analytics.predictive — ML models, anomaly detection
  analytics.cdp       — Customer Data Platform
  analytics.ai        — AI agents, conversations, actions
  industry.financial_services — FinServ: KYC, accounts, holdings
  industry.health     — Healthcare: patients, encounters, Rx

Composability Map
-----------------
The COMPOSABILITY_MAP dict documents every cross-plugin event wire:

    COMPOSABILITY_MAP[event_name] = {
        "emitted_by": [plugin_key, ...],
        "consumed_by": [plugin_key, ...],
    }

Use it for dependency-ordering at runtime or to visualise data flows.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plugin group registry
# ---------------------------------------------------------------------------
# Each entry has:
#   module_path   — importable path to the sub-plugin package
#   plugin_class  — class name inside that package (lazy-resolved in install_all)
#   domain        — logical domain label
#   depends_on    — list of plugin_key strings that must be activated first
#   description   — one-liner
# ---------------------------------------------------------------------------

ERP_GROUPS: dict[str, dict[str, Any]] = {
	# ── Foundation (root — no dependencies) ─────────────────────────────────
	"foundation": {
		"description": "Shared master-data entities used by all ERP plugins.",
		"domain": "platform",
		"depends_on": [],
		"plugins": [
			{
				"key": "foundation",
				"module": "pgappforge.plugins.erp.foundation",
				"class_name": "FoundationPlugin",
				"description": "Party, Currency, Country, CodeTable, Address, Contact, Note, Attachment, DomainEventLog",
			},
		],
	},

	# ── Platform ─────────────────────────────────────────────────────────────
	"platform": {
		"description": "Cross-cutting platform services: identity and event bus.",
		"domain": "platform",
		"depends_on": ["foundation"],
		"plugins": [
			{
				"key": "platform.identity",
				"module": "pgappforge.plugins.erp.platform.identity",
				"class_name": "PlatformIdentityPlugin",
				"description": "SSO providers, MFA devices, sessions, access policies.",
			},
			{
				"key": "platform.events",
				"module": "pgappforge.plugins.erp.platform.events",
				"class_name": "PlatformEventsPlugin",
				"description": "Event subscriptions, delivery tracking, dead-letter queue, replay.",
			},
			{
				"key": "platform.pdl_designer",
				"module": "pgappforge.pdl",
				"class_name": "PDLPlugin",
				"description": "Visual PDL entity designer — draw schemas, import capabilities, generate code.",
			},
		],
	},

	# ── Finance ──────────────────────────────────────────────────────────────
	"finance": {
		"description": "Full financial management suite.",
		"domain": "finance",
		"depends_on": ["foundation"],
		"plugins": [
			{
				"key": "finance.gl",
				"module": "pgappforge.plugins.erp.finance.gl",
				"class_name": "GLPlugin",
				"description": "General Ledger: chart of accounts, journals, periods, budgets.",
			},
			{
				"key": "finance.ap",
				"module": "pgappforge.plugins.erp.finance.ap",
				"class_name": "APPlugin",
				"description": "Accounts Payable: invoices, 3-way match, payments, supplier statements.",
			},
			{
				"key": "finance.ar",
				"module": "pgappforge.plugins.erp.finance.ar",
				"class_name": "ARPlugin",
				"description": "Accounts Receivable: invoices, receipts, dunning, aging.",
			},
			{
				"key": "finance.assets",
				"module": "pgappforge.plugins.erp.finance.assets",
				"class_name": "AssetsPlugin",
				"description": "Fixed Assets: capitalisation, depreciation, disposal, impairment.",
			},
			{
				"key": "finance.tax",
				"module": "pgappforge.plugins.erp.finance.tax",
				"class_name": "TaxPlugin",
				"description": "Tax management: rates, transaction posting, returns, filing.",
			},
			{
				"key": "finance.treasury",
				"module": "pgappforge.plugins.erp.finance.treasury",
				"class_name": "TreasuryPlugin",
				"description": "Treasury: bank accounts, FX deals, reconciliation, cash position.",
			},
		],
	},

	# ── CRM ──────────────────────────────────────────────────────────────────
	"crm": {
		"description": "Customer relationship management suite.",
		"domain": "crm",
		"depends_on": ["foundation", "finance"],
		"plugins": [
			{
				"key": "crm.sales",
				"module": "pgappforge.plugins.erp.crm.sales",
				"class_name": "SalesPlugin",
				"description": "Leads, opportunities, pipeline, forecasting, activity tracking.",
			},
			{
				"key": "crm.cpq",
				"module": "pgappforge.plugins.erp.crm.cpq",
				"class_name": "CPQPlugin",
				"description": "Configure-Price-Quote: quotes, approval workflows, versioning.",
			},
			{
				"key": "crm.service",
				"module": "pgappforge.plugins.erp.crm.service",
				"class_name": "ServicePlugin",
				"description": "Cases, SLA, knowledge base, CSAT surveys.",
			},
			{
				"key": "crm.field_service",
				"module": "pgappforge.plugins.erp.crm.field_service",
				"class_name": "FieldServicePlugin",
				"description": "Work orders, territories, technician appointments.",
			},
			{
				"key": "crm.marketing",
				"module": "pgappforge.plugins.erp.crm.marketing",
				"class_name": "MarketingPlugin",
				"description": "Campaigns, customer journeys, lists, email templates.",
			},
			{
				"key": "crm.commerce",
				"module": "pgappforge.plugins.erp.crm.commerce",
				"class_name": "CommercePlugin",
				"description": "Subscriptions, shipping rules, recurring billing.",
			},
		],
	},

	# ── Operations ───────────────────────────────────────────────────────────
	"operations": {
		"description": "Supply-chain, manufacturing, and warehouse operations.",
		"domain": "operations",
		"depends_on": ["foundation", "finance"],
		"plugins": [
			{
				"key": "operations.scm",
				"module": "pgappforge.plugins.erp.operations.scm",
				"class_name": "SCMPlugin",
				"description": "Suppliers, purchase orders, shipments, supplier KPIs.",
			},
			{
				"key": "operations.inventory",
				"module": "pgappforge.plugins.erp.operations.inventory",
				"class_name": "InventoryPlugin",
				"description": "Stock control, product catalogue, adjustments, cycle counts.",
			},
			{
				"key": "operations.warehouse",
				"module": "pgappforge.plugins.erp.operations.warehouse",
				"class_name": "WarehousePlugin",
				"description": "WMS: pick lists, put-away, bin locations, stock counts.",
			},
			{
				"key": "operations.production",
				"module": "pgappforge.plugins.erp.operations.production",
				"class_name": "PPPlugin",
				"description": "Production orders, BOM, routings, MRP forecasting.",
			},
			{
				"key": "operations.quality",
				"module": "pgappforge.plugins.erp.operations.quality",
				"class_name": "QCPlugin",
				"description": "QC inspections, non-conformance reports, CAPA.",
			},
		],
	},

	# ── HCM ──────────────────────────────────────────────────────────────────
	"hcm": {
		"description": "Human Capital Management suite.",
		"domain": "hcm",
		"depends_on": ["foundation"],
		"plugins": [
			{
				"key": "hcm.org",
				"module": "pgappforge.plugins.erp.hcm.org",
				"class_name": "OrgPlugin",
				"description": "Legal entities, org units, positions, job catalogue, grade structures.",
			},
			{
				"key": "hcm.personnel",
				"module": "pgappforge.plugins.erp.hcm.personnel",
				"class_name": "PersonnelPlugin",
				"description": "Employee lifecycle, assignments, compensation, documents.",
			},
			{
				"key": "hcm.time",
				"module": "pgappforge.plugins.erp.hcm.time",
				"class_name": "TimePlugin",
				"description": "Timesheets, attendance clock, leave requests.",
			},
			{
				"key": "hcm.payroll",
				"module": "pgappforge.plugins.erp.hcm.payroll",
				"class_name": "PayrollPlugin",
				"description": "Payroll runs, payslips, GL posting, statutory filing.",
			},
			{
				"key": "hcm.talent",
				"module": "pgappforge.plugins.erp.hcm.talent",
				"class_name": "TalentPlugin",
				"description": "Recruitment, performance reviews, training records.",
			},
		],
	},

	# ── GRC ──────────────────────────────────────────────────────────────────
	"grc": {
		"description": "Governance, Risk & Compliance suite.",
		"domain": "grc",
		"depends_on": ["foundation", "platform"],
		"plugins": [
			{
				"key": "grc.controls",
				"module": "pgappforge.plugins.erp.grc.controls",
				"class_name": "GRCControlsPlugin",
				"description": "Controls, control tests, deficiency tracking, SoD conflict detection.",
			},
			{
				"key": "grc.privacy",
				"module": "pgappforge.plugins.erp.grc.privacy",
				"class_name": "GRCPrivacyPlugin",
				"description": "GDPR/CCPA consent management, data subject requests.",
			},
			{
				"key": "grc.sustainability",
				"module": "pgappforge.plugins.erp.grc.sustainability",
				"class_name": "GRCSustainabilityPlugin",
				"description": "ESG metrics, GHG emissions, sustainability reporting.",
			},
		],
	},

	# ── Analytics ────────────────────────────────────────────────────────────
	"analytics": {
		"description": "Analytics, ML, CDP, and AI-agent suite.",
		"domain": "analytics",
		"depends_on": ["foundation"],
		"plugins": [
			{
				"key": "analytics.operational",
				"module": "pgappforge.plugins.erp.analytics.operational",
				"class_name": "OperationalPlugin",
				"description": "KPI snapshots, saved queries, scheduled reports.",
			},
			{
				"key": "analytics.predictive",
				"module": "pgappforge.plugins.erp.analytics.predictive",
				"class_name": "PredictivePlugin",
				"description": "ML model registry, predictions, anomaly detection.",
			},
			{
				"key": "analytics.cdp",
				"module": "pgappforge.plugins.erp.analytics.cdp",
				"class_name": "CDPPlugin",
				"description": "Unified customer profiles, identity graph, segment activation.",
			},
			{
				"key": "analytics.ai",
				"module": "pgappforge.plugins.erp.analytics.ai",
				"class_name": "AIPlugin",
				"description": "AI agents, conversation threads, action proposals and execution.",
			},
		],
	},

	# ── Industry verticals ───────────────────────────────────────────────────
	"industry": {
		"description": "Optional industry-vertical extension plugins.",
		"domain": "industry",
		"depends_on": ["foundation"],
		"plugins": [
			{
				"key": "industry.financial_services",
				"module": "pgappforge.plugins.erp.industry.financial_services",
				"class_name": "FinancialServicesPlugin",
				"description": "FinServ: client onboarding, KYC, accounts, holdings, sanctions screening.",
			},
			{
				"key": "industry.health",
				"module": "pgappforge.plugins.erp.industry.health",
				"class_name": "HealthPlugin",
				"description": "Healthcare: patients, encounters, diagnoses, prescriptions, lab results.",
			},
		],
	},
}

# ---------------------------------------------------------------------------
# Flat index: plugin_key -> registry entry (for O(1) lookups)
# ---------------------------------------------------------------------------

PLUGIN_REGISTRY: dict[str, dict[str, Any]] = {}
for _group in ERP_GROUPS.values():
	for _entry in _group["plugins"]:
		PLUGIN_REGISTRY[_entry["key"]] = _entry

# ---------------------------------------------------------------------------
# Composability map
# Derived from get_events() / subscribe_to() introspection of every plugin.
# Format:
#   COMPOSABILITY_MAP[event] = {"emitted_by": [key, ...], "consumed_by": [key, ...]}
# ---------------------------------------------------------------------------

_RAW_EVENTS: dict[str, dict[str, list[str]]] = {
	# foundation
	"party.created":                       {"emitted_by": ["foundation"],              "consumed_by": ["finance.ar", "finance.treasury", "crm.marketing", "grc.controls", "grc.privacy", "industry.financial_services", "industry.health"]},
	"party.updated":                       {"emitted_by": ["foundation"],              "consumed_by": ["finance.ar", "crm.service"]},
	"party.merged":                        {"emitted_by": ["foundation"],              "consumed_by": ["grc.privacy"]},
	"exchange_rate.updated":               {"emitted_by": ["foundation"],              "consumed_by": ["finance.assets", "finance.tax", "finance.treasury"]},

	# platform.identity
	"identity.provider.created":           {"emitted_by": ["platform.identity"],       "consumed_by": []},
	"identity.provider.deactivated":       {"emitted_by": ["platform.identity"],       "consumed_by": []},
	"identity.session.started":            {"emitted_by": ["platform.identity"],       "consumed_by": []},
	"identity.session.expired":            {"emitted_by": ["platform.identity"],       "consumed_by": []},
	"identity.mfa.device_verified":        {"emitted_by": ["platform.identity"],       "consumed_by": []},
	"identity.mfa.challenge_failed":       {"emitted_by": ["platform.identity"],       "consumed_by": []},
	"identity.policy.created":             {"emitted_by": ["platform.identity"],       "consumed_by": []},
	"identity.policy.changed":             {"emitted_by": ["platform.identity"],       "consumed_by": ["grc.controls"]},

	# platform.events
	"event.subscription.created":          {"emitted_by": ["platform.events"],         "consumed_by": []},
	"event.subscription.deactivated":      {"emitted_by": ["platform.events"],         "consumed_by": []},
	"event.delivery.failed":               {"emitted_by": ["platform.events"],         "consumed_by": []},
	"event.delivery.dead_lettered":        {"emitted_by": ["platform.events"],         "consumed_by": []},
	"event.replayed":                      {"emitted_by": ["platform.events"],         "consumed_by": []},

	# finance.gl
	"gl.journal.posted":                   {"emitted_by": ["finance.gl"],              "consumed_by": []},
	"gl.batch.posted":                     {"emitted_by": ["finance.gl"],              "consumed_by": []},
	"gl.journal.reversed":                 {"emitted_by": ["finance.gl"],              "consumed_by": []},
	"gl.period.closed":                    {"emitted_by": ["finance.gl"],              "consumed_by": []},

	# finance.ap
	"ap.invoice.matched":                  {"emitted_by": ["finance.ap"],              "consumed_by": ["operations.inventory"]},
	"ap.invoice.approved":                 {"emitted_by": ["finance.ap"],              "consumed_by": ["operations.scm"]},
	"ap.invoice.posted_to_gl":             {"emitted_by": ["finance.ap"],              "consumed_by": []},
	"ap.invoice.disputed":                 {"emitted_by": ["finance.ap"],              "consumed_by": []},
	"ap.payment.initiated":                {"emitted_by": ["finance.ap"],              "consumed_by": []},
	"ap.payment.confirmed":                {"emitted_by": ["finance.ap"],              "consumed_by": []},
	"ap.payment.failed":                   {"emitted_by": ["finance.ap"],              "consumed_by": []},
	"ap.supplier.statement_reconciled":    {"emitted_by": ["finance.ap"],              "consumed_by": []},
	"ap.supplier.approved":                {"emitted_by": ["finance.ap"],              "consumed_by": []},

	# finance.ar
	"ar.invoice.issued":                   {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.invoice.paid":                     {"emitted_by": ["finance.ar"],              "consumed_by": ["analytics.operational", "analytics.cdp", "crm.sales", "crm.cpq", "crm.service", "crm.commerce", "crm.marketing"]},
	"ar.invoice.written_off":              {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.invoice.disputed":                 {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.payment.received":                 {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.payment.allocated":                {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.customer.overdue":                 {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.customer.credit_hold_placed":      {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.customer.credit_hold_released":    {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.credit_note.issued":               {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.dunning.run_completed":            {"emitted_by": ["finance.ar"],              "consumed_by": []},
	"ar.aging.snapshot_created":           {"emitted_by": ["finance.ar"],              "consumed_by": []},

	# finance.assets
	"asset.capitalised":                   {"emitted_by": ["finance.assets"],          "consumed_by": []},
	"asset.depreciation_run":              {"emitted_by": ["finance.assets"],          "consumed_by": []},
	"asset.disposed":                      {"emitted_by": ["finance.assets"],          "consumed_by": []},
	"asset.impaired":                      {"emitted_by": ["finance.assets"],          "consumed_by": []},
	"asset.impairment_reversed":           {"emitted_by": ["finance.assets"],          "consumed_by": []},

	# finance.tax
	"tax.transaction_posted":              {"emitted_by": ["finance.tax"],             "consumed_by": []},
	"tax.return_generated":                {"emitted_by": ["finance.tax"],             "consumed_by": []},
	"tax.return_filed":                    {"emitted_by": ["finance.tax"],             "consumed_by": []},
	"tax.return_paid":                     {"emitted_by": ["finance.tax"],             "consumed_by": []},
	"tax.rate_expired":                    {"emitted_by": ["finance.tax"],             "consumed_by": []},

	# finance.treasury
	"treasury.bank_account_created":       {"emitted_by": ["finance.treasury"],        "consumed_by": []},
	"treasury.fx_deal_booked":             {"emitted_by": ["finance.treasury"],        "consumed_by": []},
	"treasury.fx_deal_settled":            {"emitted_by": ["finance.treasury"],        "consumed_by": []},
	"treasury.bank_reconciliation_done":   {"emitted_by": ["finance.treasury"],        "consumed_by": []},
	"treasury.cash_position_updated":      {"emitted_by": ["finance.treasury"],        "consumed_by": []},

	# crm.sales
	"crm.lead.created":                    {"emitted_by": ["crm.sales"],               "consumed_by": []},
	"crm.lead.scored":                     {"emitted_by": ["crm.sales"],               "consumed_by": []},
	"crm.lead.qualified":                  {"emitted_by": ["crm.sales"],               "consumed_by": []},
	"crm.lead.converted":                  {"emitted_by": ["crm.sales"],               "consumed_by": []},
	"crm.lead.disqualified":               {"emitted_by": ["crm.sales"],               "consumed_by": []},
	"crm.opportunity.created":             {"emitted_by": ["crm.sales"],               "consumed_by": []},
	"crm.opportunity.stage_advanced":      {"emitted_by": ["crm.sales"],               "consumed_by": []},
	"crm.opportunity.won":                 {"emitted_by": ["crm.sales"],               "consumed_by": ["crm.cpq", "analytics.cdp"]},
	"crm.opportunity.lost":                {"emitted_by": ["crm.sales"],               "consumed_by": []},
	"crm.activity.logged":                 {"emitted_by": ["crm.sales"],               "consumed_by": []},
	"crm.forecast.submitted":              {"emitted_by": ["crm.sales"],               "consumed_by": []},

	# crm.cpq
	"crm.quote.created":                   {"emitted_by": ["crm.cpq"],                 "consumed_by": []},
	"crm.quote.sent":                      {"emitted_by": ["crm.cpq"],                 "consumed_by": []},
	"crm.quote.accepted":                  {"emitted_by": ["crm.cpq"],                 "consumed_by": ["crm.sales"]},
	"crm.quote.rejected":                  {"emitted_by": ["crm.cpq"],                 "consumed_by": []},
	"crm.quote.expired":                   {"emitted_by": ["crm.cpq"],                 "consumed_by": []},
	"crm.quote.approval_requested":        {"emitted_by": ["crm.cpq"],                 "consumed_by": []},
	"crm.quote.approved":                  {"emitted_by": ["crm.cpq"],                 "consumed_by": []},
	"crm.quote.approval_rejected":         {"emitted_by": ["crm.cpq"],                 "consumed_by": []},

	# crm.service
	"service.case.created":                {"emitted_by": ["crm.service"],             "consumed_by": ["crm.field_service"]},
	"service.case.escalated":              {"emitted_by": ["crm.service"],             "consumed_by": ["crm.field_service"]},
	"service.case.resolved":               {"emitted_by": ["crm.service"],             "consumed_by": []},
	"service.case.closed":                 {"emitted_by": ["crm.service"],             "consumed_by": []},
	"service.sla.breached":                {"emitted_by": ["crm.service"],             "consumed_by": []},
	"service.survey.submitted":            {"emitted_by": ["crm.service"],             "consumed_by": []},
	"service.knowledge.published":         {"emitted_by": ["crm.service"],             "consumed_by": []},

	# crm.field_service
	"field_service.work_order.created":    {"emitted_by": ["crm.field_service"],       "consumed_by": []},
	"field_service.work_order.scheduled":  {"emitted_by": ["crm.field_service"],       "consumed_by": []},
	"field_service.work_order.completed":  {"emitted_by": ["crm.field_service"],       "consumed_by": []},
	"field_service.appointment.confirmed": {"emitted_by": ["crm.field_service"],       "consumed_by": []},
	"field_service.appointment.cancelled": {"emitted_by": ["crm.field_service"],       "consumed_by": []},

	# crm.marketing
	"marketing.campaign.activated":        {"emitted_by": ["crm.marketing"],           "consumed_by": []},
	"marketing.campaign.completed":        {"emitted_by": ["crm.marketing"],           "consumed_by": []},
	"marketing.lead.responded":            {"emitted_by": ["crm.marketing"],           "consumed_by": ["crm.commerce"]},
	"marketing.member.unsubscribed":       {"emitted_by": ["crm.marketing"],           "consumed_by": []},
	"marketing.journey.step_executed":     {"emitted_by": ["crm.marketing"],           "consumed_by": []},

	# crm.commerce
	"commerce.subscription.activated":     {"emitted_by": ["crm.commerce"],            "consumed_by": []},
	"commerce.subscription.renewed":       {"emitted_by": ["crm.commerce"],            "consumed_by": []},
	"commerce.subscription.cancelled":     {"emitted_by": ["crm.commerce"],            "consumed_by": []},
	"commerce.subscription.past_due":      {"emitted_by": ["crm.commerce"],            "consumed_by": []},

	# operations.scm
	"scm.supplier.created":                {"emitted_by": ["operations.scm"],          "consumed_by": []},
	"scm.supplier.approved":               {"emitted_by": ["operations.scm"],          "consumed_by": []},
	"scm.supplier.kpi_updated":            {"emitted_by": ["operations.scm"],          "consumed_by": []},
	"scm.supplier_product.created":        {"emitted_by": ["operations.scm"],          "consumed_by": []},
	"scm.shipment.created":                {"emitted_by": ["operations.scm"],          "consumed_by": []},
	"scm.shipment.status_changed":         {"emitted_by": ["operations.scm"],          "consumed_by": []},
	"scm.shipment.delivered":              {"emitted_by": ["operations.scm"],          "consumed_by": ["operations.production", "operations.quality"]},
	"scm.shipment.exception":              {"emitted_by": ["operations.scm"],          "consumed_by": []},

	# operations.inventory
	"inventory.stock.received":            {"emitted_by": ["operations.inventory"],    "consumed_by": ["operations.warehouse"]},
	"inventory.stock.issued":              {"emitted_by": ["operations.inventory"],    "consumed_by": []},
	"inventory.stock.transferred":         {"emitted_by": ["operations.inventory"],    "consumed_by": []},
	"inventory.stock.adjusted":            {"emitted_by": ["operations.inventory"],    "consumed_by": []},
	"inventory.stock.count_approved":      {"emitted_by": ["operations.inventory"],    "consumed_by": []},
	"inventory.stock.low":                 {"emitted_by": ["operations.inventory"],    "consumed_by": ["operations.warehouse"]},
	"inventory.product.created":           {"emitted_by": ["operations.inventory"],    "consumed_by": []},
	"inventory.product.deactivated":       {"emitted_by": ["operations.inventory"],    "consumed_by": []},

	# operations.warehouse
	"wms.picklist.created":                {"emitted_by": ["operations.warehouse"],    "consumed_by": []},
	"wms.picklist.completed":              {"emitted_by": ["operations.warehouse"],    "consumed_by": []},
	"wms.putaway.completed":               {"emitted_by": ["operations.warehouse"],    "consumed_by": []},
	"wms.stock_count.started":             {"emitted_by": ["operations.warehouse"],    "consumed_by": []},
	"wms.stock_count.ready":               {"emitted_by": ["operations.warehouse"],    "consumed_by": []},

	# operations.production
	"pp.bom.activated":                    {"emitted_by": ["operations.production"],   "consumed_by": []},
	"pp.bom.obsoleted":                    {"emitted_by": ["operations.production"],   "consumed_by": []},
	"pp.production_order.released":        {"emitted_by": ["operations.production"],   "consumed_by": ["operations.scm"]},
	"pp.production_order.started":         {"emitted_by": ["operations.production"],   "consumed_by": []},
	"pp.production_order.completed":       {"emitted_by": ["operations.production"],   "consumed_by": ["operations.quality", "grc.sustainability"]},
	"pp.production_order.cancelled":       {"emitted_by": ["operations.production"],   "consumed_by": []},
	"pp.component.issued":                 {"emitted_by": ["operations.production"],   "consumed_by": []},
	"pp.operation.completed":              {"emitted_by": ["operations.production"],   "consumed_by": []},
	"pp.forecast.updated":                 {"emitted_by": ["operations.production"],   "consumed_by": []},

	# operations.quality
	"qc.inspection.created":               {"emitted_by": ["operations.quality"],      "consumed_by": []},
	"qc.inspection.started":               {"emitted_by": ["operations.quality"],      "consumed_by": []},
	"qc.inspection.passed":                {"emitted_by": ["operations.quality"],      "consumed_by": []},
	"qc.inspection.failed":                {"emitted_by": ["operations.quality"],      "consumed_by": ["operations.production", "operations.scm"]},
	"qc.ncr.opened":                       {"emitted_by": ["operations.quality"],      "consumed_by": []},
	"qc.ncr.analysis_started":             {"emitted_by": ["operations.quality"],      "consumed_by": []},
	"qc.ncr.correction_issued":            {"emitted_by": ["operations.quality"],      "consumed_by": []},
	"qc.ncr.closed":                       {"emitted_by": ["operations.quality"],      "consumed_by": []},
	"qc.ncr.reopened":                     {"emitted_by": ["operations.quality"],      "consumed_by": []},

	# hcm.org
	"hcm.org.legal_entity.created":        {"emitted_by": ["hcm.org"],                "consumed_by": []},
	"hcm.org.legal_entity.deactivated":    {"emitted_by": ["hcm.org"],                "consumed_by": []},
	"hcm.org.unit.created":                {"emitted_by": ["hcm.org"],                "consumed_by": []},
	"hcm.org.unit.restructured":           {"emitted_by": ["hcm.org"],                "consumed_by": []},
	"hcm.org.position.created":            {"emitted_by": ["hcm.org"],                "consumed_by": ["hcm.personnel"]},
	"hcm.org.position.filled":             {"emitted_by": ["hcm.org"],                "consumed_by": []},
	"hcm.org.position.vacated":            {"emitted_by": ["hcm.org"],                "consumed_by": []},
	"hcm.org.job_catalog.created":         {"emitted_by": ["hcm.org"],                "consumed_by": []},
	"hcm.org.compensation_grade.published":{"emitted_by": ["hcm.org"],                "consumed_by": []},

	# hcm.personnel
	"hcm.personnel.employee.hired":        {"emitted_by": ["hcm.personnel"],           "consumed_by": ["hcm.time"]},
	"hcm.personnel.employee.assigned":     {"emitted_by": ["hcm.personnel"],           "consumed_by": ["hcm.org"]},
	"hcm.personnel.employee.transferred":  {"emitted_by": ["hcm.personnel"],           "consumed_by": []},
	"hcm.personnel.employee.terminated":   {"emitted_by": ["hcm.personnel"],           "consumed_by": ["hcm.org", "hcm.time"]},
	"hcm.personnel.employee.rehired":      {"emitted_by": ["hcm.personnel"],           "consumed_by": []},
	"hcm.personnel.compensation.changed":  {"emitted_by": ["hcm.personnel"],           "consumed_by": []},
	"hcm.personnel.document.verified":     {"emitted_by": ["hcm.personnel"],           "consumed_by": []},
	"hcm.personnel.document.expiring":     {"emitted_by": ["hcm.personnel"],           "consumed_by": []},

	# hcm.time
	"hcm.time.attendance.clocked_in":      {"emitted_by": ["hcm.time"],               "consumed_by": []},
	"hcm.time.attendance.clocked_out":     {"emitted_by": ["hcm.time"],               "consumed_by": []},
	"hcm.time.leave_request.submitted":    {"emitted_by": ["hcm.time"],               "consumed_by": []},
	"hcm.time.leave_request.approved":     {"emitted_by": ["hcm.time"],               "consumed_by": []},
	"hcm.time.leave_request.rejected":     {"emitted_by": ["hcm.time"],               "consumed_by": []},
	"hcm.time.leave_request.cancelled":    {"emitted_by": ["hcm.time"],               "consumed_by": []},
	"hcm.time.timesheet.submitted":        {"emitted_by": ["hcm.time"],               "consumed_by": []},
	"hcm.time.timesheet.approved":         {"emitted_by": ["hcm.time"],               "consumed_by": ["hcm.personnel"]},
	"hcm.time.timesheet.rejected":         {"emitted_by": ["hcm.time"],               "consumed_by": []},

	# hcm.payroll
	"hcm.payroll.run.calculated":          {"emitted_by": ["hcm.payroll"],             "consumed_by": []},
	"hcm.payroll.run.approved":            {"emitted_by": ["hcm.payroll"],             "consumed_by": []},
	"hcm.payroll.run.paid":                {"emitted_by": ["hcm.payroll"],             "consumed_by": ["hcm.talent", "analytics.operational"]},
	"hcm.payroll.payslip.reversed":        {"emitted_by": ["hcm.payroll"],             "consumed_by": []},
	"hcm.payroll.gl.posted":               {"emitted_by": ["hcm.payroll"],             "consumed_by": []},
	"hcm.payroll.statutory.filed":         {"emitted_by": ["hcm.payroll"],             "consumed_by": []},

	# hcm.talent
	"hcm.talent.requisition.approved":     {"emitted_by": ["hcm.talent"],              "consumed_by": []},
	"hcm.talent.requisition.filled":       {"emitted_by": ["hcm.talent"],              "consumed_by": []},
	"hcm.talent.application.stage_changed":{"emitted_by": ["hcm.talent"],              "consumed_by": []},
	"hcm.talent.offer.sent":               {"emitted_by": ["hcm.talent"],              "consumed_by": []},
	"hcm.talent.offer.accepted":           {"emitted_by": ["hcm.talent"],              "consumed_by": []},
	"hcm.talent.offer.declined":           {"emitted_by": ["hcm.talent"],              "consumed_by": []},
	"hcm.talent.review.finalised":         {"emitted_by": ["hcm.talent"],              "consumed_by": []},
	"hcm.talent.training.completed":       {"emitted_by": ["hcm.talent"],              "consumed_by": []},

	# grc.controls
	"grc.control.created":                 {"emitted_by": ["grc.controls"],            "consumed_by": []},
	"grc.control.status_changed":          {"emitted_by": ["grc.controls"],            "consumed_by": []},
	"grc.control_test.completed":          {"emitted_by": ["grc.controls"],            "consumed_by": []},
	"grc.control_test.deficiency_noted":   {"emitted_by": ["grc.controls"],            "consumed_by": []},
	"grc.sod.conflict_detected":           {"emitted_by": ["grc.controls"],            "consumed_by": []},

	# grc.privacy
	"privacy.consent.granted":             {"emitted_by": ["grc.privacy"],             "consumed_by": []},
	"privacy.consent.withdrawn":           {"emitted_by": ["grc.privacy"],             "consumed_by": []},
	"privacy.dsr.received":                {"emitted_by": ["grc.privacy"],             "consumed_by": []},
	"privacy.dsr.completed":               {"emitted_by": ["grc.privacy"],             "consumed_by": []},
	"privacy.dsr.overdue":                 {"emitted_by": ["grc.privacy"],             "consumed_by": []},

	# grc.sustainability
	"sustainability.emission.recorded":    {"emitted_by": ["grc.sustainability"],      "consumed_by": []},
	"sustainability.emission.verified":    {"emitted_by": ["grc.sustainability"],      "consumed_by": []},
	"sustainability.esg_metric.target_set":{"emitted_by": ["grc.sustainability"],      "consumed_by": []},
	"sustainability.esg_snapshot.captured":{"emitted_by": ["grc.sustainability"],      "consumed_by": []},
	"sustainability.esg_snapshot.target_missed":{"emitted_by": ["grc.sustainability"], "consumed_by": []},

	# analytics.operational
	"analytics.kpi.snapshot_recorded":     {"emitted_by": ["analytics.operational"],  "consumed_by": []},
	"analytics.kpi.status_changed":        {"emitted_by": ["analytics.operational"],  "consumed_by": ["analytics.predictive", "analytics.ai"]},
	"analytics.report.generated":          {"emitted_by": ["analytics.operational"],  "consumed_by": []},
	"analytics.query.executed":            {"emitted_by": ["analytics.operational"],  "consumed_by": []},

	# analytics.predictive
	"analytics.ml_model.deployed":         {"emitted_by": ["analytics.predictive"],   "consumed_by": []},
	"analytics.ml_model.retired":          {"emitted_by": ["analytics.predictive"],   "consumed_by": []},
	"analytics.prediction.created":        {"emitted_by": ["analytics.predictive"],   "consumed_by": ["analytics.cdp"]},
	"analytics.anomaly.detected":          {"emitted_by": ["analytics.predictive"],   "consumed_by": ["analytics.ai"]},
	"analytics.anomaly.acknowledged":      {"emitted_by": ["analytics.predictive"],   "consumed_by": []},

	# analytics.cdp
	"analytics.cdp.profile_computed":      {"emitted_by": ["analytics.cdp"],          "consumed_by": ["analytics.predictive"]},
	"analytics.cdp.segment_computed":      {"emitted_by": ["analytics.cdp"],          "consumed_by": []},
	"analytics.cdp.identity_resolved":     {"emitted_by": ["analytics.cdp"],          "consumed_by": []},
	"analytics.cdp.segment_activated":     {"emitted_by": ["analytics.cdp"],          "consumed_by": []},
	"analytics.cdp.event_stream_ingested": {"emitted_by": ["analytics.cdp"],          "consumed_by": []},

	# analytics.ai
	"analytics.ai.conversation_started":   {"emitted_by": ["analytics.ai"],           "consumed_by": []},
	"analytics.ai.conversation_ended":     {"emitted_by": ["analytics.ai"],           "consumed_by": []},
	"analytics.ai.message_sent":           {"emitted_by": ["analytics.ai"],           "consumed_by": []},
	"analytics.ai.action_proposed":        {"emitted_by": ["analytics.ai"],           "consumed_by": []},
	"analytics.ai.action_approved":        {"emitted_by": ["analytics.ai"],           "consumed_by": []},
	"analytics.ai.action_rejected":        {"emitted_by": ["analytics.ai"],           "consumed_by": []},
	"analytics.ai.action_executed":        {"emitted_by": ["analytics.ai"],           "consumed_by": []},
	"analytics.ai.action_failed":          {"emitted_by": ["analytics.ai"],           "consumed_by": []},

	# industry.financial_services
	"finserv.client.onboarded":            {"emitted_by": ["industry.financial_services"], "consumed_by": []},
	"finserv.client.kyc_status_changed":   {"emitted_by": ["industry.financial_services"], "consumed_by": []},
	"finserv.client.risk_profile_changed": {"emitted_by": ["industry.financial_services"], "consumed_by": []},
	"finserv.account.opened":              {"emitted_by": ["industry.financial_services"], "consumed_by": []},
	"finserv.account.status_changed":      {"emitted_by": ["industry.financial_services"], "consumed_by": []},
	"finserv.account.balance_updated":     {"emitted_by": ["industry.financial_services"], "consumed_by": []},
	"finserv.holding.revalued":            {"emitted_by": ["industry.financial_services"], "consumed_by": []},
	"finserv.sanctions.screening_completed":{"emitted_by": ["industry.financial_services"],"consumed_by": []},
	"finserv.sanctions.match_cleared":     {"emitted_by": ["industry.financial_services"], "consumed_by": []},

	# industry.health
	"health.patient.registered":           {"emitted_by": ["industry.health"],         "consumed_by": []},
	"health.patient.updated":              {"emitted_by": ["industry.health"],         "consumed_by": []},
	"health.encounter.started":            {"emitted_by": ["industry.health"],         "consumed_by": []},
	"health.encounter.completed":          {"emitted_by": ["industry.health"],         "consumed_by": []},
	"health.diagnosis.confirmed":          {"emitted_by": ["industry.health"],         "consumed_by": []},
	"health.prescription.issued":          {"emitted_by": ["industry.health"],         "consumed_by": []},
	"health.prescription.discontinued":    {"emitted_by": ["industry.health"],         "consumed_by": []},
	"health.lab.resulted":                 {"emitted_by": ["industry.health"],         "consumed_by": []},
	"health.lab.critical_value":           {"emitted_by": ["industry.health"],         "consumed_by": []},
}

COMPOSABILITY_MAP: dict[str, dict[str, list[str]]] = _RAW_EVENTS

# ---------------------------------------------------------------------------
# Topological install order
# Respects group-level depends_on; within a group order is declaration order.
# ---------------------------------------------------------------------------

_GROUP_ORDER: list[str] = [
	"foundation",
	"platform",
	"finance",
	"operations",
	"crm",
	"hcm",
	"grc",
	"analytics",
	"industry",
]

# Flat ordered list of all plugin entries for install_all()
_INSTALL_ORDER: list[dict[str, Any]] = []
for _gk in _GROUP_ORDER:
	_INSTALL_ORDER.extend(ERP_GROUPS[_gk]["plugins"])


# ---------------------------------------------------------------------------
# install_all — primary public API
# ---------------------------------------------------------------------------

def install_all(
	appbuilder: Any,
	*,
	groups: list[str] | None = None,
	skip: list[str] | None = None,
	config_overrides: dict[str, dict[str, Any]] | None = None,
	strict: bool = False,
) -> dict[str, bool]:
	"""Register every ERP plugin with *appbuilder*.

	Parameters
	----------
	appbuilder:
	    PgAppForge / Flask-AppBuilder ``AppBuilder`` instance.
	groups:
	    If given, only plugins belonging to these group keys are activated.
	    E.g. ``groups=["finance", "crm"]``.
	skip:
	    Plugin keys to exclude even if their group is selected.
	    E.g. ``skip=["industry.health"]``.
	config_overrides:
	    Per-plugin config dicts keyed by plugin key.
	    E.g. ``config_overrides={"finance.gl": {"GL_MENU_CATEGORY": "Ledger"}}``.
	strict:
	    If ``True``, raise on first activation failure instead of logging and
	    continuing.

	Returns
	-------
	dict[str, bool]
	    Mapping of plugin key -> activation success flag.
	"""
	skip_set: set[str] = set(skip or [])
	config_overrides = config_overrides or {}
	results: dict[str, bool] = {}

	# Resolve candidate set
	if groups is not None:
		candidates: list[dict[str, Any]] = []
		for gk in _GROUP_ORDER:
			if gk in groups:
				candidates.extend(ERP_GROUPS[gk]["plugins"])
	else:
		candidates = list(_INSTALL_ORDER)

	for entry in candidates:
		key: str = entry["key"]
		if key in skip_set:
			log.debug("install_all: skipping %s (in skip list)", key)
			results[key] = False
			continue

		module_path: str = entry["module"]
		class_name: str = entry["class_name"]
		cfg: dict[str, Any] = config_overrides.get(key, {})

		try:
			import importlib
			mod = importlib.import_module(module_path)
			plugin_cls = getattr(mod, class_name)
			plugin = plugin_cls(appbuilder, config=cfg)
			ok = plugin.activate()
			results[key] = ok
			if not ok and strict:
				raise RuntimeError(f"ERP plugin '{key}' failed to activate")
			log.info("install_all: %s -> %s", key, "OK" if ok else "FAILED")
		except Exception as exc:
			log.error("install_all: error activating %s: %s", key, exc)
			results[key] = False
			if strict:
				raise

	return results


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------

def list_plugins(group: str | None = None) -> list[dict[str, Any]]:
	"""Return plugin metadata entries, optionally filtered by *group*."""
	if group is not None:
		return list(ERP_GROUPS.get(group, {}).get("plugins", []))
	return list(_INSTALL_ORDER)


def event_consumers(event: str) -> list[str]:
	"""Return plugin keys that subscribe to *event*."""
	return COMPOSABILITY_MAP.get(event, {}).get("consumed_by", [])


def event_emitters(event: str) -> list[str]:
	"""Return plugin keys that emit *event*."""
	return COMPOSABILITY_MAP.get(event, {}).get("emitted_by", [])


def plugins_for_domain(domain: str) -> list[str]:
	"""Return plugin keys belonging to *domain* (e.g. ``"finance"``)."""
	keys: list[str] = []
	for group in ERP_GROUPS.values():
		if group["domain"] == domain:
			keys.extend(p["key"] for p in group["plugins"])
	return keys


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
	# data
	"ERP_GROUPS",
	"PLUGIN_REGISTRY",
	"COMPOSABILITY_MAP",
	# helpers
	"install_all",
	"list_plugins",
	"event_consumers",
	"event_emitters",
	"plugins_for_domain",
]
