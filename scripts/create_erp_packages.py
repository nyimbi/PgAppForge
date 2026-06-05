#!/usr/bin/env python3
"""
scripts/create_erp_packages.py

Generates standalone PyPI package scaffolding for all pgappforge ERP plugins
under packages/pgappforge_erp_<slug>/.

Each package is a thin re-export wrapper that makes the plugin installable as
`pip install pgappforge-erp-<slug>` with entry-point auto-discovery.

Run from repo root:
    python scripts/create_erp_packages.py
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Plugin registry
# slug -> (source_module, PluginClass, domain, description, extra_deps, features)
# ---------------------------------------------------------------------------

MIT_TEXT = """\
MIT License

Copyright (c) 2024 Nyimbi Odero

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

PLUGINS: list[dict] = [
	{
		"slug": "foundation",
		"source_module": "pgappforge.plugins.erp.foundation",
		"plugin_class": "FoundationPlugin",
		"domain": "platform",
		"description": "ERP Foundation — shared master-data entities (Party, Currency, Country, CodeTable) used by all ERP plugins",
		"keywords": ["foundation", "master-data", "party", "currency"],
		"extra_deps": [],
		"features": [
			"Party and PartyRole master data",
			"Currency and exchange rate management",
			"Country and CodeTable reference data",
			"Address, Contact, Note, Attachment entities",
			"Domain event log",
		],
	},
	{
		"slug": "gl",
		"source_module": "pgappforge.plugins.erp.finance.gl",
		"plugin_class": "GLPlugin",
		"domain": "finance",
		"description": "General Ledger — chart of accounts, fiscal years, double-entry journal, period balances, budgets",
		"keywords": ["gl", "general-ledger", "finance", "journal", "accounting"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0"],
		"features": [
			"Chart of Accounts with IFRS/GAAP concept mapping",
			"Fiscal years and accounting periods",
			"Double-entry journal batches and lines",
			"Period account balance snapshots",
			"Budget vs actual tracking",
			"Cost centre dimension",
		],
	},
	{
		"slug": "ar",
		"source_module": "pgappforge.plugins.erp.finance.ar",
		"plugin_class": "ARPlugin",
		"domain": "finance",
		"description": "Accounts Receivable — customer invoicing, receipts, credit notes, aging, collections",
		"keywords": ["ar", "accounts-receivable", "finance", "invoicing", "collections"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-gl>=0.1.0"],
		"features": [
			"Customer invoice lifecycle management",
			"Payment receipts and allocation",
			"Credit note processing",
			"Aging analysis and collections",
			"GL integration for automatic journal posting",
		],
	},
	{
		"slug": "ap",
		"source_module": "pgappforge.plugins.erp.finance.ap",
		"plugin_class": "APPlugin",
		"domain": "finance",
		"description": "Accounts Payable — supplier invoices, payment runs, three-way matching, aging",
		"keywords": ["ap", "accounts-payable", "finance", "supplier", "payments"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-gl>=0.1.0"],
		"features": [
			"Supplier invoice processing and approval",
			"Payment run generation",
			"Three-way matching (PO / GR / invoice)",
			"Aging analysis and cash-flow forecasting",
			"GL integration for automatic journal posting",
		],
	},
	{
		"slug": "assets",
		"source_module": "pgappforge.plugins.erp.finance.assets",
		"plugin_class": "AssetsPlugin",
		"domain": "finance",
		"description": "Fixed Assets — asset register, depreciation schedules, disposals, impairment",
		"keywords": ["assets", "fixed-assets", "depreciation", "finance"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-gl>=0.1.0"],
		"features": [
			"Asset register with lifecycle tracking",
			"Multiple depreciation methods (SL, DB, UOP)",
			"Asset disposal and write-off processing",
			"Impairment testing support",
			"GL integration for depreciation journals",
		],
	},
	{
		"slug": "treasury",
		"source_module": "pgappforge.plugins.erp.finance.treasury",
		"plugin_class": "TreasuryPlugin",
		"domain": "finance",
		"description": "Treasury — cash management, bank reconciliation, FX exposure, investments, debt",
		"keywords": ["treasury", "cash-management", "bank-reconciliation", "finance"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-gl>=0.1.0"],
		"features": [
			"Cash position and forecasting",
			"Bank statement import and reconciliation",
			"FX exposure management",
			"Investment portfolio tracking",
			"Debt and facility management",
		],
	},
	{
		"slug": "tax",
		"source_module": "pgappforge.plugins.erp.finance.tax",
		"plugin_class": "TaxPlugin",
		"domain": "finance",
		"description": "Tax Management — tax codes, VAT/GST calculation, returns, withholding tax",
		"keywords": ["tax", "vat", "gst", "withholding", "finance"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-gl>=0.1.0"],
		"features": [
			"Multi-jurisdiction tax code configuration",
			"VAT/GST automatic calculation",
			"Tax return preparation and filing",
			"Withholding tax management",
			"GL integration for tax postings",
		],
	},
	{
		"slug": "inventory",
		"source_module": "pgappforge.plugins.erp.operations.inventory",
		"plugin_class": "InventoryPlugin",
		"domain": "operations",
		"description": "Inventory Management — items, stock levels, valuation, movements, lot/serial tracking",
		"keywords": ["inventory", "stock", "valuation", "operations"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0"],
		"features": [
			"Item master with UOM and category management",
			"Real-time stock level tracking",
			"FIFO/LIFO/Average cost valuation",
			"Inventory movement and adjustment journal",
			"Lot and serial number tracking",
		],
	},
	{
		"slug": "warehouse",
		"source_module": "pgappforge.plugins.erp.operations.warehouse",
		"plugin_class": "WarehousePlugin",
		"domain": "operations",
		"description": "Warehouse Management — locations, putaway, pick/pack/ship, cycle counts",
		"keywords": ["warehouse", "wms", "pick-pack-ship", "operations"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-inventory>=0.1.0"],
		"features": [
			"Multi-warehouse and location hierarchy",
			"Putaway and picking rules",
			"Pick/pack/ship workflow",
			"Cycle count and full physical inventory",
			"Barcode and RFID integration hooks",
		],
	},
	{
		"slug": "production",
		"source_module": "pgappforge.plugins.erp.operations.production",
		"plugin_class": "PPPlugin",
		"domain": "operations",
		"description": "Production Planning — BOMs, work orders, routing, capacity, shop-floor control",
		"keywords": ["production", "manufacturing", "bom", "work-orders", "operations"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-inventory>=0.1.0"],
		"features": [
			"Bill of Materials (multi-level)",
			"Production work order lifecycle",
			"Routing and work centre management",
			"Capacity planning and scheduling",
			"Shop-floor data collection",
		],
	},
	{
		"slug": "scm",
		"source_module": "pgappforge.plugins.erp.operations.scm",
		"plugin_class": "SCMPlugin",
		"domain": "operations",
		"description": "Supply Chain Management — procurement, purchase orders, goods receipt, supplier management",
		"keywords": ["scm", "procurement", "purchase-orders", "supply-chain", "operations"],
		"extra_deps": [
			"pgappforge-erp-foundation>=0.1.0",
			"pgappforge-erp-inventory>=0.1.0",
			"pgappforge-erp-ap>=0.1.0",
		],
		"features": [
			"Procurement request and approval workflow",
			"Purchase order management",
			"Goods receipt and quality inspection",
			"Supplier performance tracking",
			"Demand-driven replenishment",
		],
	},
	{
		"slug": "quality",
		"source_module": "pgappforge.plugins.erp.operations.quality",
		"plugin_class": "QCPlugin",
		"domain": "operations",
		"description": "Quality Control — inspection plans, non-conformance, CAPA, certifications",
		"keywords": ["quality", "qc", "inspection", "ncr", "capa", "operations"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-inventory>=0.1.0"],
		"features": [
			"Inspection plan configuration",
			"Non-conformance report (NCR) management",
			"Corrective and preventive actions (CAPA)",
			"Quality certificate management",
			"Statistical process control charts",
		],
	},
	{
		"slug": "hr_org",
		"source_module": "pgappforge.plugins.erp.hcm.org",
		"plugin_class": "OrgPlugin",
		"domain": "hcm",
		"description": "HR Organisation — org chart, positions, job grades, cost centres",
		"keywords": ["hr", "org-chart", "positions", "job-grades", "hcm"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0"],
		"features": [
			"Organisation hierarchy and org chart",
			"Position and headcount management",
			"Job family and grade structure",
			"Cost centre assignment",
			"Reporting-line management",
		],
	},
	{
		"slug": "hr_personnel",
		"source_module": "pgappforge.plugins.erp.hcm.personnel",
		"plugin_class": "PersonnelPlugin",
		"domain": "hcm",
		"description": "HR Personnel — employee lifecycle, contracts, absences, documents",
		"keywords": ["hr", "personnel", "employees", "contracts", "hcm"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-hr-org>=0.1.0"],
		"features": [
			"Employee record and lifecycle management",
			"Employment contract management",
			"Absence and leave management",
			"Employee document vault",
			"Probation and confirmation tracking",
		],
	},
	{
		"slug": "hr_time",
		"source_module": "pgappforge.plugins.erp.hcm.time",
		"plugin_class": "TimePlugin",
		"domain": "hcm",
		"description": "Time & Attendance — timesheets, shift schedules, overtime, attendance rules",
		"keywords": ["hr", "time", "timesheets", "attendance", "hcm"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-hr-personnel>=0.1.0"],
		"features": [
			"Timesheet entry and approval",
			"Shift schedule management",
			"Overtime calculation rules",
			"Attendance and absence reconciliation",
			"Integration with payroll for gross pay",
		],
	},
	{
		"slug": "payroll",
		"source_module": "pgappforge.plugins.erp.hcm.payroll",
		"plugin_class": "PayrollPlugin",
		"domain": "hcm",
		"description": "Payroll — pay runs, gross-to-net, statutory deductions, payslips, GL posting",
		"keywords": ["payroll", "pay-run", "gross-to-net", "hcm"],
		"extra_deps": [
			"pgappforge-erp-foundation>=0.1.0",
			"pgappforge-erp-hr-personnel>=0.1.0",
			"pgappforge-erp-hr-time>=0.1.0",
			"pgappforge-erp-gl>=0.1.0",
		],
		"features": [
			"Pay run processing (gross-to-net)",
			"Statutory deduction calculation (PAYE, NI, pension)",
			"Payslip generation and distribution",
			"GL posting for payroll journals",
			"Multi-currency payroll support",
		],
	},
	{
		"slug": "talent",
		"source_module": "pgappforge.plugins.erp.hcm.talent",
		"plugin_class": "TalentPlugin",
		"domain": "hcm",
		"description": "Talent Management — recruitment, performance reviews, learning, succession planning",
		"keywords": ["talent", "recruitment", "performance", "learning", "hcm"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-hr-personnel>=0.1.0"],
		"features": [
			"Recruitment and applicant tracking",
			"Performance review cycles",
			"Learning and development plans",
			"Succession planning and talent pools",
			"Skills inventory",
		],
	},
	{
		"slug": "sales",
		"source_module": "pgappforge.plugins.erp.crm.sales",
		"plugin_class": "SalesPlugin",
		"domain": "crm",
		"description": "Sales — leads, opportunities, pipeline, quotes, orders, forecasting",
		"keywords": ["sales", "crm", "pipeline", "opportunities", "forecasting"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-ar>=0.1.0"],
		"features": [
			"Lead and opportunity management",
			"Sales pipeline and stage tracking",
			"Quote and proposal generation",
			"Sales order processing",
			"Revenue forecasting",
		],
	},
	{
		"slug": "cpq",
		"source_module": "pgappforge.plugins.erp.crm.cpq",
		"plugin_class": "CPQPlugin",
		"domain": "crm",
		"description": "Configure Price Quote — product configurator, pricing rules, discount approvals",
		"keywords": ["cpq", "configure-price-quote", "pricing", "crm"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-sales>=0.1.0"],
		"features": [
			"Product configuration rules engine",
			"Dynamic pricing and discount tiers",
			"Approval workflow for non-standard discounts",
			"Quote PDF generation",
			"Integration with sales order",
		],
	},
	{
		"slug": "service",
		"source_module": "pgappforge.plugins.erp.crm.service",
		"plugin_class": "ServicePlugin",
		"domain": "crm",
		"description": "Customer Service — cases, SLA, knowledge base, escalation, satisfaction surveys",
		"keywords": ["service", "crm", "cases", "sla", "helpdesk"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-sales>=0.1.0"],
		"features": [
			"Case and ticket management",
			"SLA definition and breach alerting",
			"Knowledge base articles",
			"Escalation rules and routing",
			"Customer satisfaction (CSAT) surveys",
		],
	},
	{
		"slug": "field_service",
		"source_module": "pgappforge.plugins.erp.crm.field_service",
		"plugin_class": "FieldServicePlugin",
		"domain": "crm",
		"description": "Field Service — work orders, scheduling, dispatching, mobile workforce, parts",
		"keywords": ["field-service", "work-orders", "scheduling", "crm"],
		"extra_deps": [
			"pgappforge-erp-foundation>=0.1.0",
			"pgappforge-erp-service>=0.1.0",
			"pgappforge-erp-inventory>=0.1.0",
		],
		"features": [
			"Field work order lifecycle",
			"Technician scheduling and dispatch",
			"Parts reservation and consumption",
			"Mobile check-in and signature capture",
			"SLA-driven priority queuing",
		],
	},
	{
		"slug": "marketing",
		"source_module": "pgappforge.plugins.erp.crm.marketing",
		"plugin_class": "MarketingPlugin",
		"domain": "crm",
		"description": "Marketing — campaigns, segments, email journeys, lead capture, attribution",
		"keywords": ["marketing", "campaigns", "email", "crm", "attribution"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-sales>=0.1.0"],
		"features": [
			"Campaign planning and execution",
			"Audience segmentation",
			"Multi-channel journey builder",
			"Lead capture forms and scoring",
			"Attribution and ROI reporting",
		],
	},
	{
		"slug": "commerce",
		"source_module": "pgappforge.plugins.erp.crm.commerce",
		"plugin_class": "CommercePlugin",
		"domain": "crm",
		"description": "Commerce — product catalogue, storefronts, cart, checkout, promotions",
		"keywords": ["commerce", "ecommerce", "catalogue", "crm"],
		"extra_deps": [
			"pgappforge-erp-foundation>=0.1.0",
			"pgappforge-erp-sales>=0.1.0",
			"pgappforge-erp-inventory>=0.1.0",
		],
		"features": [
			"Product catalogue management",
			"Multi-storefront configuration",
			"Cart and checkout workflow",
			"Promotions and coupon engine",
			"Order fulfilment integration",
		],
	},
	{
		"slug": "analytics",
		"source_module": "pgappforge.plugins.erp.analytics.operational",
		"plugin_class": "OperationalPlugin",
		"domain": "analytics",
		"description": "Operational Analytics — KPI dashboards, cross-module reporting, data extracts",
		"keywords": ["analytics", "kpi", "dashboards", "reporting"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0"],
		"features": [
			"Pre-built KPI dashboards per domain",
			"Cross-module consolidated reports",
			"Scheduled data extract and export",
			"Drill-down from summary to transaction",
			"Export to CSV, Excel, PDF",
		],
	},
	{
		"slug": "predictive",
		"source_module": "pgappforge.plugins.erp.analytics.predictive",
		"plugin_class": "PredictivePlugin",
		"domain": "analytics",
		"description": "Predictive Analytics — demand forecasting, churn prediction, anomaly detection",
		"keywords": ["predictive", "forecasting", "ml", "analytics"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-analytics>=0.1.0"],
		"features": [
			"Demand forecasting (statistical + ML)",
			"Customer churn prediction",
			"Anomaly detection on financial data",
			"Model training pipeline hooks",
			"Forecast accuracy tracking",
		],
	},
	{
		"slug": "cdp",
		"source_module": "pgappforge.plugins.erp.analytics.cdp",
		"plugin_class": "CDPPlugin",
		"domain": "analytics",
		"description": "Customer Data Platform — unified customer profiles, identity resolution, segmentation",
		"keywords": ["cdp", "customer-data", "identity-resolution", "analytics"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-analytics>=0.1.0"],
		"features": [
			"Unified customer profile stitching",
			"Identity resolution across channels",
			"Real-time segmentation engine",
			"Profile enrichment and scoring",
			"Activation to marketing and sales",
		],
	},
	{
		"slug": "ai",
		"source_module": "pgappforge.plugins.erp.analytics.ai",
		"plugin_class": "AIPlugin",
		"domain": "analytics",
		"description": "AI Insights — LLM-powered summaries, copilot queries, anomaly narratives",
		"keywords": ["ai", "llm", "copilot", "insights", "analytics"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0", "pgappforge-erp-analytics>=0.1.0"],
		"features": [
			"Natural language query interface",
			"LLM-powered anomaly narratives",
			"AI-driven period close commentary",
			"Intelligent data entry suggestions",
			"Configurable LLM provider backend",
		],
	},
	{
		"slug": "platform_events",
		"source_module": "pgappforge.plugins.erp.platform.events",
		"plugin_class": "PlatformEventsPlugin",
		"domain": "platform",
		"description": "Platform Events — event bus, pub/sub routing, webhook delivery, audit log",
		"keywords": ["events", "event-bus", "webhooks", "platform"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0"],
		"features": [
			"In-process pub/sub event bus",
			"Webhook endpoint registration and delivery",
			"Event replay and dead-letter queue",
			"Per-event audit log",
			"Schema versioning for event payloads",
		],
	},
	{
		"slug": "identity",
		"source_module": "pgappforge.plugins.erp.platform.identity",
		"plugin_class": "PlatformIdentityPlugin",
		"domain": "platform",
		"description": "Identity & Access — RBAC, API keys, MFA, SSO/OIDC integration, audit",
		"keywords": ["identity", "rbac", "mfa", "sso", "platform"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0"],
		"features": [
			"Role-based access control (RBAC)",
			"API key management",
			"Multi-factor authentication (MFA)",
			"SSO/OIDC integration hooks",
			"Access audit trail",
		],
	},
	{
		"slug": "grc_controls",
		"source_module": "pgappforge.plugins.erp.grc.controls",
		"plugin_class": "GRCControlsPlugin",
		"domain": "grc",
		"description": "GRC Controls — control library, risk register, assessments, SOX/ISO compliance",
		"keywords": ["grc", "controls", "risk", "compliance", "sox"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0"],
		"features": [
			"Internal control library",
			"Risk register and risk scoring",
			"Control assessment and testing",
			"SOX and ISO 27001 mapping",
			"Remediation tracking",
		],
	},
	{
		"slug": "privacy",
		"source_module": "pgappforge.plugins.erp.grc.privacy",
		"plugin_class": "GRCPrivacyPlugin",
		"domain": "grc",
		"description": "Privacy Management — data inventory, DSAR, consent, GDPR/CCPA compliance",
		"keywords": ["privacy", "gdpr", "ccpa", "dsar", "grc"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0"],
		"features": [
			"Personal data inventory and lineage",
			"DSAR (Data Subject Access Request) workflow",
			"Consent record management",
			"GDPR/CCPA impact assessment",
			"Breach notification workflow",
		],
	},
	{
		"slug": "sustainability",
		"source_module": "pgappforge.plugins.erp.grc.sustainability",
		"plugin_class": "GRCSustainabilityPlugin",
		"domain": "grc",
		"description": "Sustainability — ESG data collection, carbon accounting, scope 1/2/3, reporting",
		"keywords": ["sustainability", "esg", "carbon", "scope3", "grc"],
		"extra_deps": ["pgappforge-erp-foundation>=0.1.0"],
		"features": [
			"ESG data collection templates",
			"Carbon footprint accounting (scope 1/2/3)",
			"Emission factor library",
			"GHG Protocol compliant reporting",
			"Science-based targets tracking",
		],
	},
	{
		"slug": "finserv",
		"source_module": "pgappforge.plugins.erp.industry.financial_services",
		"plugin_class": "FinancialServicesPlugin",
		"domain": "industry",
		"description": "Financial Services vertical — instruments, positions, regulatory capital, AML",
		"keywords": ["finserv", "financial-services", "instruments", "aml", "industry"],
		"extra_deps": [
			"pgappforge-erp-foundation>=0.1.0",
			"pgappforge-erp-gl>=0.1.0",
			"pgappforge-erp-grc-controls>=0.1.0",
		],
		"features": [
			"Financial instrument register",
			"Position and portfolio management",
			"Regulatory capital calculation hooks",
			"AML/KYC workflow",
			"IFRS 9 / CECL provisioning support",
		],
	},
	{
		"slug": "health",
		"source_module": "pgappforge.plugins.erp.industry.health",
		"plugin_class": "HealthPlugin",
		"domain": "industry",
		"description": "Healthcare vertical — patient registry, episodes, clinical encounters, billing",
		"keywords": ["health", "healthcare", "patient", "clinical", "industry"],
		"extra_deps": [
			"pgappforge-erp-foundation>=0.1.0",
			"pgappforge-erp-ar>=0.1.0",
			"pgappforge-erp-privacy>=0.1.0",
		],
		"features": [
			"Patient and demographic registry",
			"Clinical episode and encounter management",
			"Diagnosis and procedure coding (ICD/CPT)",
			"Healthcare billing and claims",
			"HIPAA-compliant access controls",
		],
	},
]

# ---------------------------------------------------------------------------
# Entry-point key derivation
# (PyPI name uses dashes; entry-point key uses underscores, no package prefix)
# ---------------------------------------------------------------------------

def pypi_name(slug: str) -> str:
	"""pgappforge-erp-<slug-with-dashes>"""
	return "pgappforge-erp-" + slug.replace("_", "-")


def entry_key(slug: str) -> str:
	"""erp_<slug>"""
	return "erp_" + slug


# ---------------------------------------------------------------------------
# File generators
# ---------------------------------------------------------------------------

def make_pyproject(plugin: dict) -> str:
	slug = plugin["slug"]
	name = pypi_name(slug)
	cls = plugin["plugin_class"]
	src = plugin["source_module"]
	desc = plugin["description"]
	domain = plugin["domain"]
	kws = plugin["keywords"]
	extra = plugin["extra_deps"]

	dep_lines = ['    "pgappforge>=0.90.0",']
	for dep in extra:
		dep_lines.append(f'    "{dep}",')
	deps_block = "\n".join(dep_lines)

	kw_list = ", ".join(f'"{k}"' for k in ["pgappforge", "erp"] + kws)
	ekey = entry_key(slug)

	return f"""\
[project]
name = "{name}"
version = "0.1.0"
description = "{desc}"
requires-python = ">=3.12"
license = {{text = "MIT"}}
authors = [{{name = "Nyimbi Odero", email = "nyimbi+pgaf@gmail.com"}}]
readme = "README.md"
keywords = [{kw_list}]
classifiers = [
    "Development Status :: 4 - Beta",
    "Framework :: Flask",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Office/Business",
]
dependencies = [
{deps_block}
]

[project.entry-points."pgappforge.plugins"]
{ekey} = "{src}:{cls}"

[project.urls]
Homepage = "https://github.com/pgappforge/pgappforge"
Documentation = "https://pgappforge.dev/plugins/erp/{slug}"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[tool.setuptools.packages.find]
where = ["src"]
"""


def make_init(plugin: dict) -> str:
	slug = plugin["slug"]
	cls = plugin["plugin_class"]
	src = plugin["source_module"]
	name_display = cls.replace("Plugin", "")
	pip_name = slug.replace("_", "-")

	docstring = (
		'"""\n'
		f"pgappforge ERP {name_display} plugin.\n"
		"\n"
		"Standalone PyPI package — install with:\n"
		f"    pip install pgappforge-erp-{pip_name}\n"
		"\n"
		"Auto-discovered by pgappforge via entry points when installed.\n"
		"\n"
		"Quick start::\n"
		"\n"
		f"    from pgappforge_erp_{slug} import {cls}\n"
		f"    plugin = {cls}(appbuilder)\n"
		"    plugin.activate()\n"
		'"""\n'
	)

	return (
		docstring
		+ f"from {src} import {cls} as _Plugin\n"
		+ f"from {src}.models import *  # noqa: F401, F403\n"
		+ f"from {src}.services import *  # noqa: F401, F403\n"
		+ f"from {src}.events import *  # noqa: F401, F403\n"
		+ "\n"
		+ f"# Canonical re-export\n"
		+ f"{cls} = _Plugin\n"
		+ "\n"
		+ '__version__ = "0.1.0"\n'
		+ f'__all__ = ["{cls}", "__version__"]\n'
	)


def make_readme(plugin: dict) -> str:
	slug = plugin["slug"]
	cls = plugin["plugin_class"]
	desc = plugin["description"]
	features = plugin["features"]
	pkg_name = pypi_name(slug)
	import_slug = slug  # Python package name

	bullet_lines = "\n".join(f"- {f}" for f in features)

	return f"""\
# {pkg_name}

**{desc}**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge {pkg_name}
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_{import_slug} import {cls}

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = {cls}(appbuilder)
plugin.activate()
```

## Features

{bullet_lines}

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
	repo_root = Path(__file__).parent.parent
	packages_dir = repo_root / "packages"
	packages_dir.mkdir(exist_ok=True)

	created_files: list[Path] = []
	workspace_members: list[str] = []

	for plugin in PLUGINS:
		slug = plugin["slug"]
		pkg_dir_name = f"pgappforge_erp_{slug}"
		pkg_dir = packages_dir / pkg_dir_name
		src_pkg_dir = pkg_dir / "src" / pkg_dir_name

		# Create directory tree
		src_pkg_dir.mkdir(parents=True, exist_ok=True)

		# pyproject.toml
		pyproject_path = pkg_dir / "pyproject.toml"
		pyproject_path.write_text(make_pyproject(plugin))
		created_files.append(pyproject_path)

		# LICENSE
		license_path = pkg_dir / "LICENSE"
		license_path.write_text(MIT_TEXT)
		created_files.append(license_path)

		# README.md
		readme_path = pkg_dir / "README.md"
		readme_path.write_text(make_readme(plugin))
		created_files.append(readme_path)

		# src/<pkg>/__init__.py
		init_path = src_pkg_dir / "__init__.py"
		init_path.write_text(make_init(plugin))
		created_files.append(init_path)

		workspace_members.append(f'  "packages/{pkg_dir_name}",')
		print(f"  created  packages/{pkg_dir_name}/  ({len(created_files)} files so far)")

	# ------------------------------------------------------------------
	# Patch root pyproject.toml — add [tool.uv.workspace] if absent
	# ------------------------------------------------------------------
	root_pyproject = repo_root / "pyproject.toml"
	workspace_block = (
		"\n[tool.uv.workspace]\nmembers = [\n"
		+ "\n".join(workspace_members)
		+ "\n]\n"
	)

	if root_pyproject.exists():
		content = root_pyproject.read_text()
		if "[tool.uv.workspace]" not in content:
			root_pyproject.write_text(content + workspace_block)
			print(f"\nPatched root pyproject.toml with [tool.uv.workspace] ({len(PLUGINS)} members)")
		else:
			print("\nroot pyproject.toml already has [tool.uv.workspace] — skipped")
	else:
		root_pyproject.write_text(workspace_block)
		print("\nCreated root pyproject.toml with [tool.uv.workspace]")

	print(f"\nDone. {len(created_files)} files created across {len(PLUGINS)} packages.")


if __name__ == "__main__":
	main()
