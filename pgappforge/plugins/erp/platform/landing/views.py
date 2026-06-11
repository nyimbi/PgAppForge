"""
pgappforge/plugins/erp/platform/landing/views.py

LandingPageView  — public-facing deployment home page.
LandingConfigView — admin-only landing page customisation.

Route map
---------
  GET  /                     — main landing page
  GET  /landing/api/stats    — JSON stats for the stats-bar island
  GET  /landing/edit         — admin config form  (requires can_edit LandingPage)
  POST /landing/edit         — save config changes (requires can_edit LandingPage)
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from flask import current_app, jsonify, redirect, render_template, request, url_for

from pgappforge import expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module registry — all ERP + fintech capabilities with routing hints
# ---------------------------------------------------------------------------
# Each entry: name, icon (Font Awesome), color (hex), url, description, domain
# ---------------------------------------------------------------------------

_MODULE_REGISTRY: list[dict[str, str]] = [
	# ── Foundation ───────────────────────────────────────────────────────────
	{
		"key": "foundation",
		"name": "Master Data",
		"icon": "fa-database",
		"color": "#6366f1",
		"url": "/erp/foundation",
		"description": "Parties, currencies, countries, code tables, addresses.",
		"domain": "platform",
	},

	# ── Platform ─────────────────────────────────────────────────────────────
	{
		"key": "platform.identity",
		"name": "Identity & Access",
		"icon": "fa-id-card",
		"color": "#8b5cf6",
		"url": "/erp/platform/identity",
		"description": "SSO, MFA, sessions, access policies.",
		"domain": "platform",
	},
	{
		"key": "platform.events",
		"name": "Event Bus",
		"icon": "fa-bolt",
		"color": "#a78bfa",
		"url": "/erp/platform/events",
		"description": "Subscriptions, delivery tracking, dead-letter queue, replay.",
		"domain": "platform",
	},
	{
		"key": "platform.ipaas",
		"name": "iPaaS Flows",
		"icon": "fa-exchange",
		"color": "#7c3aed",
		"url": "/platform_admin/ipaas-flows",
		"description": "Integration flows, connectors, transformation maps.",
		"domain": "platform",
	},
	{
		"key": "platform.documents",
		"name": "Document Store",
		"icon": "fa-folder-open",
		"color": "#5b21b6",
		"url": "/platform_docs/document-browser",
		"description": "Document management, versioning, full-text search.",
		"domain": "platform",
	},
	{
		"key": "platform.row_security",
		"name": "Row-Level Security",
		"icon": "fa-lock",
		"color": "#4c1d95",
		"url": "/platform_admin/row-security",
		"description": "Multi-tenant data isolation and policy management.",
		"domain": "platform",
	},
	{
		"key": "platform.process_mining",
		"name": "Process Mining",
		"icon": "fa-sitemap",
		"color": "#6d28d9",
		"url": "/platform/process-mining",
		"description": "Event-log analysis, bottleneck detection, conformance.",
		"domain": "platform",
	},
	{
		"key": "platform.whatsapp",
		"name": "WhatsApp Inbox",
		"icon": "fa-comments",
		"color": "#25D366",
		"url": "/platform_whatsapp/dashboard",
		"description": "Business messaging, chatbots, broadcast campaigns.",
		"domain": "platform",
	},

	# ── Finance ──────────────────────────────────────────────────────────────
	{
		"key": "finance.gl",
		"name": "General Ledger",
		"icon": "fa-book",
		"color": "#1a56db",
		"url": "/erp/finance/gl",
		"description": "Chart of accounts, journals, periods, multi-book.",
		"domain": "finance",
	},
	{
		"key": "finance.ap",
		"name": "Accounts Payable",
		"icon": "fa-file-text",
		"color": "#1c64f2",
		"url": "/finance_admin/ap",
		"description": "Supplier invoices, 3-way match, payments, statements.",
		"domain": "finance",
	},
	{
		"key": "finance.ar",
		"name": "Accounts Receivable",
		"icon": "fa-dollar",
		"color": "#0e9f6e",
		"url": "/finance_admin/ar",
		"description": "Customer invoices, receipts, dunning, aging reports.",
		"domain": "finance",
	},
	{
		"key": "finance.assets",
		"name": "Fixed Assets",
		"icon": "fa-building",
		"color": "#057a55",
		"url": "/finance_admin/assets",
		"description": "Capitalisation, depreciation schedules, disposals.",
		"domain": "finance",
	},
	{
		"key": "finance.tax",
		"name": "Tax Management",
		"icon": "fa-percent",
		"color": "#ff5a1f",
		"url": "/finance_admin/tax",
		"description": "Tax rates, transaction posting, returns, e-filing.",
		"domain": "finance",
	},
	{
		"key": "finance.treasury",
		"name": "Treasury",
		"icon": "fa-university",
		"color": "#0369a1",
		"url": "/erp/finance/treasury",
		"description": "Bank accounts, FX deals, reconciliation, cash position.",
		"domain": "finance",
	},
	{
		"key": "finance.fpa",
		"name": "FP&A",
		"icon": "fa-line-chart",
		"color": "#1d4ed8",
		"url": "/finance/fpa-dashboard",
		"description": "Budgeting, forecasting, variance analysis.",
		"domain": "finance",
	},
	{
		"key": "finance.consolidation",
		"name": "Consolidation",
		"icon": "fa-compress",
		"color": "#2563eb",
		"url": "/finance/consolidation",
		"description": "Multi-entity close, eliminations, reporting packs.",
		"domain": "finance",
	},

	# ── CRM ──────────────────────────────────────────────────────────────────
	{
		"key": "crm.sales",
		"name": "Sales Pipeline",
		"icon": "fa-bar-chart",
		"color": "#e02424",
		"url": "/crm_admin/sales-pipeline",
		"description": "Leads, opportunities, forecasting, activity tracking.",
		"domain": "crm",
	},
	{
		"key": "crm.cpq",
		"name": "Configure-Price-Quote",
		"icon": "fa-tag",
		"color": "#dc2626",
		"url": "/erp/crm/cpq",
		"description": "Guided configuration, pricing rules, approval flows.",
		"domain": "crm",
	},
	{
		"key": "crm.service",
		"name": "Service Cases",
		"icon": "fa-headphones",
		"color": "#b91c1c",
		"url": "/crm_admin/service-cases",
		"description": "Support cases, SLA tracking, knowledge base, CSAT.",
		"domain": "crm",
	},
	{
		"key": "crm.field_service",
		"name": "Field Service",
		"icon": "fa-wrench",
		"color": "#991b1b",
		"url": "/crm_admin/field-service",
		"description": "Work orders, territory management, technician dispatch.",
		"domain": "crm",
	},
	{
		"key": "crm.marketing",
		"name": "Marketing",
		"icon": "fa-bullhorn",
		"color": "#f59e0b",
		"url": "/crm_admin/marketing",
		"description": "Campaigns, customer journeys, email lists.",
		"domain": "crm",
	},
	{
		"key": "crm.commerce",
		"name": "Subscriptions",
		"icon": "fa-repeat",
		"color": "#d97706",
		"url": "/crm_subs/mrr-dashboard",
		"description": "Recurring billing, MRR dashboard, churn analysis.",
		"domain": "crm",
	},
	{
		"key": "crm.portal",
		"name": "Customer Portal",
		"icon": "fa-globe",
		"color": "#b45309",
		"url": "/crm_portal/customer-portal",
		"description": "Self-service portal, account info, support tickets.",
		"domain": "crm",
	},

	# ── Operations ───────────────────────────────────────────────────────────
	{
		"key": "operations.scm",
		"name": "Supply Chain",
		"icon": "fa-truck",
		"color": "#0891b2",
		"url": "/erp/operations/scm",
		"description": "Suppliers, purchase orders, shipments, KPI scorecards.",
		"domain": "operations",
	},
	{
		"key": "operations.inventory",
		"name": "Inventory",
		"icon": "fa-cubes",
		"color": "#0e7490",
		"url": "/erp/operations/inventory",
		"description": "Stock control, product catalogue, adjustments.",
		"domain": "operations",
	},
	{
		"key": "operations.warehouse",
		"name": "Warehouse",
		"icon": "fa-archive",
		"color": "#155e75",
		"url": "/operations_ui/warehouse-dashboard",
		"description": "WMS: pick lists, put-away, bin locations, cycle counts.",
		"domain": "operations",
	},
	{
		"key": "operations.production",
		"name": "Production",
		"icon": "fa-industry",
		"color": "#164e63",
		"url": "/operations_ui/mrp-dashboard",
		"description": "Production orders, BOM, routings, MRP forecasting.",
		"domain": "operations",
	},
	{
		"key": "operations.quality",
		"name": "Quality Control",
		"icon": "fa-check-circle",
		"color": "#0369a1",
		"url": "/erp/operations/quality",
		"description": "QC inspections, non-conformance reports, CAPA.",
		"domain": "operations",
	},
	{
		"key": "operations.fleet",
		"name": "Fleet",
		"icon": "fa-car",
		"color": "#075985",
		"url": "/operations_ui/fleet-dashboard",
		"description": "Vehicle registry, service schedules, fuel tracking.",
		"domain": "operations",
	},
	{
		"key": "operations.maintenance",
		"name": "Maintenance (EAM)",
		"icon": "fa-cogs",
		"color": "#0c4a6e",
		"url": "/operations_ui/eam-dashboard",
		"description": "Work orders, preventive maintenance, asset health.",
		"domain": "operations",
	},

	# ── HCM ──────────────────────────────────────────────────────────────────
	{
		"key": "hcm.org",
		"name": "Org Structure",
		"icon": "fa-sitemap",
		"color": "#7c3aed",
		"url": "/hcm_admin/org-structure",
		"description": "Legal entities, org units, position management.",
		"domain": "hcm",
	},
	{
		"key": "hcm.personnel",
		"name": "Employee Records",
		"icon": "fa-users",
		"color": "#6d28d9",
		"url": "/hcm_admin/employee-list",
		"description": "Employee lifecycle, assignments, compensation.",
		"domain": "hcm",
	},
	{
		"key": "hcm.time",
		"name": "Time & Attendance",
		"icon": "fa-clock-o",
		"color": "#5b21b6",
		"url": "/hcm_admin/time-attendance",
		"description": "Timesheets, clock-in/out, leave requests.",
		"domain": "hcm",
	},
	{
		"key": "hcm.payroll",
		"name": "Payroll",
		"icon": "fa-money",
		"color": "#4c1d95",
		"url": "/hcm_payroll_dash/payroll-run",
		"description": "Payroll runs, payslips, GL posting, statutory filing.",
		"domain": "hcm",
	},
	{
		"key": "hcm.talent",
		"name": "Talent & Recruiting",
		"icon": "fa-user-plus",
		"color": "#3b0764",
		"url": "/hcm_rec_full/recruiting",
		"description": "Requisitions, ATS pipeline, performance reviews.",
		"domain": "hcm",
	},
	{
		"key": "hcm.learning",
		"name": "Learning (LMS)",
		"icon": "fa-graduation-cap",
		"color": "#6b21a8",
		"url": "/hcm_lms/course-catalog",
		"description": "Course catalogue, enrolments, completions.",
		"domain": "hcm",
	},
	{
		"key": "hcm.benefits",
		"name": "Benefits",
		"icon": "fa-heart",
		"color": "#701a75",
		"url": "/hcm_benefits/enrollment",
		"description": "Benefits plans, enrolment wizard, cost allocation.",
		"domain": "hcm",
	},
	{
		"key": "hcm.skills",
		"name": "Skills Ontology",
		"icon": "fa-star",
		"color": "#7e22ce",
		"url": "/hcm_skills/explorer",
		"description": "Skill taxonomy, gap analysis, succession planning.",
		"domain": "hcm",
	},

	# ── GRC ──────────────────────────────────────────────────────────────────
	{
		"key": "grc.controls",
		"name": "Controls & SoD",
		"icon": "fa-shield",
		"color": "#b91c1c",
		"url": "/grc_admin/controls-dashboard",
		"description": "Controls testing, deficiency tracking, SoD detection.",
		"domain": "grc",
	},
	{
		"key": "grc.privacy",
		"name": "Privacy (GDPR)",
		"icon": "fa-user-secret",
		"color": "#991b1b",
		"url": "/grc_admin/privacy-dashboard",
		"description": "Consent management, data subject requests, CCPA.",
		"domain": "grc",
	},
	{
		"key": "grc.sustainability",
		"name": "ESG & Sustainability",
		"icon": "fa-leaf",
		"color": "#065f46",
		"url": "/grc_admin/sustainability",
		"description": "GHG emissions, ESG metrics, sustainability reporting.",
		"domain": "grc",
	},
	{
		"key": "grc.risk",
		"name": "Enterprise Risk (ERM)",
		"icon": "fa-exclamation-triangle",
		"color": "#7f1d1d",
		"url": "/grc/erm-dashboard",
		"description": "Risk register, heat maps, mitigation tracking.",
		"domain": "grc",
	},
	{
		"key": "grc.anti_bribery",
		"name": "Anti-Bribery",
		"icon": "fa-ban",
		"color": "#6b7280",
		"url": "/grc_antibribery/gifts-register",
		"description": "Gifts register, conflict-of-interest declarations.",
		"domain": "grc",
	},

	# ── Analytics ────────────────────────────────────────────────────────────
	{
		"key": "analytics.operational",
		"name": "KPI Dashboard",
		"icon": "fa-tachometer",
		"color": "#0f766e",
		"url": "/platform/analytics-dashboard",
		"description": "Live KPI snapshots, saved queries, scheduled reports.",
		"domain": "analytics",
	},
	{
		"key": "analytics.predictive",
		"name": "Predictive Analytics",
		"icon": "fa-magic",
		"color": "#0d9488",
		"url": "/erp/analytics/predictive",
		"description": "ML model registry, predictions, anomaly detection.",
		"domain": "analytics",
	},
	{
		"key": "analytics.cdp",
		"name": "Customer Data Platform",
		"icon": "fa-user-circle",
		"color": "#0891b2",
		"url": "/erp/analytics/cdp",
		"description": "Unified customer profiles, identity graph, segments.",
		"domain": "analytics",
	},
	{
		"key": "analytics.ai",
		"name": "AI Agents",
		"icon": "fa-android",
		"color": "#6366f1",
		"url": "/erp/analytics/ai",
		"description": "Conversational AI, action proposals, autonomous execution.",
		"domain": "analytics",
	},
	{
		"key": "analytics.anomaly",
		"name": "Anomaly Detection",
		"icon": "fa-exclamation-circle",
		"color": "#dc2626",
		"url": "/platform_anomaly/dashboard",
		"description": "Real-time anomaly alerts across all ERP domains.",
		"domain": "analytics",
	},

	# ── Fintech / Industry ───────────────────────────────────────────────────
	{
		"key": "industry.financial_services",
		"name": "FinServ / KYC",
		"icon": "fa-bank",
		"color": "#1e40af",
		"url": "/erp/industry/finserv",
		"description": "Client onboarding, KYC, accounts, holdings, sanctions.",
		"domain": "fintech",
	},
	{
		"key": "fintech.core_banking",
		"name": "Core Banking",
		"icon": "fa-credit-card",
		"color": "#1d4ed8",
		"url": "/core_banking/account-actions",
		"description": "Deposits, withdrawals, transfers, interest accrual.",
		"domain": "fintech",
	},
	{
		"key": "fintech.lending",
		"name": "Lending",
		"icon": "fa-handshake-o",
		"color": "#2563eb",
		"url": "/fintech_lending/loan-dashboard",
		"description": "Loan origination, schedules, repayments, provisioning.",
		"domain": "fintech",
	},
	{
		"key": "fintech.sacco",
		"name": "SACCO / Cooperative",
		"icon": "fa-group",
		"color": "#1e3a8a",
		"url": "/fintech_sacco/sacco-dashboard",
		"description": "Member shares, contributions, withdrawals, dividends.",
		"domain": "fintech",
	},
	{
		"key": "fintech.trade_finance",
		"name": "Trade Finance",
		"icon": "fa-ship",
		"color": "#0c4a6e",
		"url": "/erp/fintech/trade-finance",
		"description": "Letters of credit, documentary collections, guarantees.",
		"domain": "fintech",
	},
	{
		"key": "fintech.mobile_money",
		"name": "Mobile Money",
		"icon": "fa-mobile",
		"color": "#065f46",
		"url": "/erp/fintech/mobile-money",
		"description": "Wallet management, P2P transfers, bill payments.",
		"domain": "fintech",
	},
	{
		"key": "industry.health",
		"name": "Healthcare",
		"icon": "fa-medkit",
		"color": "#0e9f6e",
		"url": "/erp/industry/health",
		"description": "Patients, encounters, diagnoses, prescriptions, lab results.",
		"domain": "industry",
	},
	{
		"key": "industry.real_estate",
		"name": "Real Estate",
		"icon": "fa-home",
		"color": "#d97706",
		"url": "/re_portfolio/dashboard",
		"description": "Portfolio, rent roll, lease management, CAM reconciliation.",
		"domain": "industry",
	},
	{
		"key": "industry.projects",
		"name": "Project Management",
		"icon": "fa-tasks",
		"color": "#0369a1",
		"url": "/projects_admin/project-list",
		"description": "Projects, tasks, Gantt, time logging, billing.",
		"domain": "industry",
	},
]


def _get_deployed_modules(
	domain_filter: str | None = None,
) -> list[dict[str, str]]:
	"""Return the module registry, optionally filtered by comma-separated domains.

	The caller can further restrict to specific domains via app config
	``LANDING_MODULES_FILTER`` (comma-separated domain names).
	"""
	try:
		cfg_filter: str = current_app.config.get("LANDING_MODULES_FILTER", "") or ""
		filter_domains: set[str] = {
			d.strip().lower()
			for d in cfg_filter.split(",")
			if d.strip()
		}
		if domain_filter:
			filter_domains = {d.strip().lower() for d in domain_filter.split(",") if d.strip()}
	except RuntimeError:
		# outside app context (e.g. tests importing the module)
		filter_domains = set()

	if filter_domains:
		return [m for m in _MODULE_REGISTRY if m["domain"].lower() in filter_domains]
	return list(_MODULE_REGISTRY)


def _get_announcements() -> list[dict[str, Any]]:
	"""Return active announcements.

	Currently returns a static empty list.  Replace or extend this to pull
	from a DB model (e.g. ``LandingAnnouncement``) when needed.
	"""
	return []


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class LandingPageView(BaseERPView):
	"""Public-facing ERP deployment landing page."""

	route_base = "/"
	default_view = "index"

	# ------------------------------------------------------------------ index

	@expose("/")
	def index(self) -> str:
		"""Render the landing page."""
		modules = _get_deployed_modules()
		announcements = _get_announcements()
		return render_template(
			"appbuilder/landing/landing.html",
			modules=modules,
			announcements=announcements,
			appbuilder=self.appbuilder,
		)

	# --------------------------------------------------------- /landing/api/stats

	@expose("/landing/api/stats")
	def stats_api(self):
		"""JSON stats for the landing-page stats-bar island."""
		user_count = 0
		try:
			from pgappforge.security.sqla.models import User
			session = self._session()
			user_count = (
				session.execute(
					sa.select(sa.func.count(User.id)).where(User.active.is_(True))
				).scalar_one()
				or 0
			)
		except Exception:
			log.debug("landing stats_api: could not count users", exc_info=True)

		# Module count from registry
		module_count = len(_MODULE_REGISTRY)

		# Deployed domains
		domains = {m["domain"] for m in _MODULE_REGISTRY}

		return jsonify({
			"stats": [
				{
					"label": "Active Users",
					"value": f"{user_count:,}",
					"icon": "fa-users",
				},
				{
					"label": "ERP Modules",
					"value": f"{module_count}",
					"icon": "fa-cubes",
				},
				{
					"label": "Domains",
					"value": str(len(domains)),
					"icon": "fa-th-large",
				},
				{
					"label": "Uptime",
					"value": "99.9%",
					"icon": "fa-check-circle",
				},
			]
		})

	# --------------------------------------------------------- /landing/edit GET

	@expose("/landing/edit", methods=["GET"])
	@has_access
	def edit_landing(self) -> str:
		"""Admin form — edit landing page config."""
		config_keys: list[tuple[str, str, str]] = [
			("LANDING_TITLE",          "Page Title",                       "text"),
			("LANDING_TAGLINE",        "Tagline",                          "text"),
			("LANDING_LOGO_URL",       "Logo URL",                         "url"),
			("LANDING_ACCENT_COLOR",   "Hero Accent Colour",               "color"),
			("LANDING_ENV_LABEL",      "Environment Label (e.g. Staging)", "text"),
			("LANDING_MODULES_FILTER", "Module Domains to Show (comma-separated, blank = all)", "text"),
			("LANDING_SHOW_STATS",     "Show Stats Bar",                   "checkbox"),
		]
		current_config = {
			k: current_app.config.get(k, "")
			for k, _, _ in config_keys
		}
		return render_template(
			"appbuilder/landing/landing_edit.html",
			config_keys=config_keys,
			current_config=current_config,
			appbuilder=self.appbuilder,
		)

	# ------------------------------------------------------- /landing/edit POST

	@expose("/landing/edit", methods=["POST"])
	@has_access
	def save_landing_config(self):
		"""Persist landing config to app.config (runtime; extend to DB as needed)."""
		text_keys = [
			"LANDING_TITLE",
			"LANDING_TAGLINE",
			"LANDING_LOGO_URL",
			"LANDING_ACCENT_COLOR",
			"LANDING_ENV_LABEL",
			"LANDING_MODULES_FILTER",
		]
		for key in text_keys:
			val = request.form.get(key, "").strip()
			current_app.config[key] = val

		# checkbox → boolean string
		current_app.config["LANDING_SHOW_STATS"] = (
			"true" if request.form.get("LANDING_SHOW_STATS") else "false"
		)

		log.info("landing config updated by %s", getattr(getattr(self, 'appbuilder', None), 'sm', {}) and "admin")
		return redirect(url_for("LandingPageView.index"))


__all__ = ["LandingPageView"]
