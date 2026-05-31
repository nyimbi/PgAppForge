"""
Ergonomic ERD Designer for pgappforge.

Handles hundreds of tables without chaos via:
- Module grouping (Cytoscape.js compound nodes)
- Double-click to fold/unfold any module
- Left panel: ERP module palette + search
- Mini-map navigator (bottom-right)
- Semantic zoom (far=modules, close=columns)
- Right-click context menu per table/module
- Full bidirectional editing via ERDSchemaManager

ERP Templates included:
  AP, AR, CRM, HR, INV, GL, PROJ, PROC

Usage::

    from pgappforge.views.erd_designer import ERDDesignerView
    appbuilder.add_view(ERDDesignerView, 'ERD Designer',
                        icon='fa-sitemap', category='Tools')
"""
from __future__ import annotations

import json
import json as _json
import pathlib
import threading as _threading
import queue as _queue
from flask import abort, current_app, request, jsonify, Response, make_response
from flask_login import current_user

_SSE_CLIENTS: dict = {}
_SSE_LOCK = _threading.Lock()
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.widgets_postgresql._cdn import (
	CYTOSCAPE_CDN as _CY,
	CYTOSCAPE_FCOSE_CDN as _FCOSE,
	CYTOSCAPE_DAGRE_CDN as _DAGRE,
	CYTOSCAPE_EDGEHANDLES_CDN as _EDGEHANDLES,
	CYTOSCAPE_NAVIGATOR_CDN as _NAVIGATOR,
)

# Combined extension CDN block injected into _DESIGNER_HTML
_CYTOSCAPE_EXTENSIONS_CDN = _FCOSE + _DAGRE + _EDGEHANDLES + _NAVIGATOR


# ─── Security helpers ─────────────────────────────────────────────────────────

def _require_schema_admin() -> None:
	"""Abort 403 unless current user is Admin and FAB_ERD_DDL_ENABLED is True.

	Gate-keeps all mutating DDL endpoints so that:
	  - Production databases can disable the ERD DDL path entirely via config.
	  - Even with it enabled, only users with the Admin role can apply changes.
	Returns JSON 403 responses instead of HTML error pages.
	"""
	if not current_app.config.get("FAB_ERD_DDL_ENABLED", False):
		abort(make_response(jsonify({
			"ok": False,
			"error": "ERD schema mutations are disabled.",
			"hint": "Set FAB_ERD_DDL_ENABLED = True in Flask config.",
			"code": "ddl_disabled",
		}), 403))
	if not current_user or not current_user.is_authenticated:
		abort(make_response(jsonify({"ok": False, "error": "Login required.", "code": "login_required"}), 403))
	roles = [getattr(r, "name", "") for r in getattr(current_user, "roles", [])]
	if not any(r in ("Admin", "admin") for r in roles):
		abort(make_response(jsonify({"ok": False, "error": "Admin role required.", "code": "admin_required"}), 403))


def _validate_csrf() -> None:
	"""Validate CSRF token on JSON POST endpoints.

	Expects the ``X-CSRFToken`` request header (set by JS from the meta tag).
	Fails closed if Flask-WTF is not installed.
	"""
	try:
		from flask_wtf.csrf import validate_csrf, ValidationError
	except ImportError:
		abort(500, description="CSRF protection requires flask-wtf. Install it or set FAB_ERD_DDL_ENABLED=False.")
	token = request.headers.get("X-CSRFToken") or request.form.get("csrf_token", "")
	try:
		validate_csrf(token)
	except Exception:
		abort(400, description="CSRF validation failed")


def _safe_output_dir(raw: str | None, app_name: str) -> pathlib.Path:
	"""Resolve and validate an output directory for code generation.

	All paths must be under FAB_CODEGEN_OUTPUT_ROOT (default /tmp/pgaf_generated)
	to prevent path traversal attacks.
	"""
	root = pathlib.Path(
		current_app.config.get("FAB_CODEGEN_OUTPUT_ROOT", "/tmp/pgaf_generated")
	).resolve()
	if raw:
		candidate = pathlib.Path(raw).resolve()
	else:
		safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in app_name.lower())
		candidate = (root / safe_name).resolve()
	try:
		candidate.relative_to(root)
	except ValueError:
		abort(400, description=f"output_dir must be under {root}")
	return candidate

# ─── ERP Module Templates ────────────────────────────────────────────────────

ERP_MODULES: dict[str, dict] = {
	"AP": {
		"label": "Accounts Payable",
		"color": "#e74c3c",
		"icon": "fa-file-invoice-dollar",
		"description": "Vendor management, purchase orders, payables",
		"tables": {
			"vendors": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "name", "type": "VARCHAR(255)", "nullable": False},
				{"name": "tax_id", "type": "VARCHAR(50)"},
				{"name": "payment_terms", "type": "VARCHAR(50)"},
				{"name": "email", "type": "VARCHAR(320)"},
				{"name": "phone", "type": "VARCHAR(30)"},
				{"name": "address", "type": "TEXT"},
				{"name": "is_active", "type": "BOOLEAN", "default": "true"},
				{"name": "created_at", "type": "TIMESTAMPTZ", "default": "NOW()"},
			],
			"purchase_orders": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "vendor_id", "type": "INTEGER", "fk": "vendors.id", "nullable": False},
				{"name": "po_number", "type": "VARCHAR(50)", "unique": True},
				{"name": "status", "type": "VARCHAR(20)", "default": "'draft'"},
				{"name": "order_date", "type": "DATE"},
				{"name": "expected_date", "type": "DATE"},
				{"name": "total_amount", "type": "NUMERIC(19,4)"},
				{"name": "currency", "type": "CHAR(3)", "default": "'USD'"},
				{"name": "notes", "type": "TEXT"},
				{"name": "created_at", "type": "TIMESTAMPTZ", "default": "NOW()"},
			],
			"ap_invoices": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "po_id", "type": "INTEGER", "fk": "purchase_orders.id"},
				{"name": "vendor_id", "type": "INTEGER", "fk": "vendors.id", "nullable": False},
				{"name": "invoice_number", "type": "VARCHAR(100)"},
				{"name": "invoice_date", "type": "DATE"},
				{"name": "due_date", "type": "DATE"},
				{"name": "amount", "type": "NUMERIC(19,4)"},
				{"name": "status", "type": "VARCHAR(20)", "default": "'pending'"},
				{"name": "paid_at", "type": "TIMESTAMPTZ"},
			],
			"ap_payments": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "invoice_id", "type": "INTEGER", "fk": "ap_invoices.id"},
				{"name": "amount", "type": "NUMERIC(19,4)"},
				{"name": "payment_date", "type": "DATE"},
				{"name": "method", "type": "VARCHAR(50)"},
				{"name": "reference", "type": "VARCHAR(255)"},
			],
			"payment_terms": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "name", "type": "VARCHAR(100)", "unique": True},
				{"name": "net_days", "type": "INTEGER"},
				{"name": "discount_pct", "type": "NUMERIC(5,2)"},
				{"name": "discount_days", "type": "INTEGER"},
			],
		},
	},
	"AR": {
		"label": "Accounts Receivable",
		"color": "#3498db",
		"icon": "fa-receipt",
		"description": "Customer billing, invoicing, collections",
		"tables": {
			"customers": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "name", "type": "VARCHAR(255)", "nullable": False},
				{"name": "email", "type": "VARCHAR(320)", "unique": True},
				{"name": "phone", "type": "VARCHAR(30)"},
				{"name": "credit_limit", "type": "NUMERIC(19,4)"},
				{"name": "payment_terms_id", "type": "INTEGER"},
				{"name": "created_at", "type": "TIMESTAMPTZ", "default": "NOW()"},
			],
			"sales_orders": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "customer_id", "type": "INTEGER", "fk": "customers.id"},
				{"name": "order_number", "type": "VARCHAR(50)", "unique": True},
				{"name": "status", "type": "VARCHAR(20)", "default": "'draft'"},
				{"name": "order_date", "type": "DATE"},
				{"name": "total_amount", "type": "NUMERIC(19,4)"},
			],
			"ar_invoices": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "customer_id", "type": "INTEGER", "fk": "customers.id"},
				{"name": "so_id", "type": "INTEGER", "fk": "sales_orders.id"},
				{"name": "invoice_number", "type": "VARCHAR(100)", "unique": True},
				{"name": "invoice_date", "type": "DATE"},
				{"name": "due_date", "type": "DATE"},
				{"name": "amount", "type": "NUMERIC(19,4)"},
				{"name": "status", "type": "VARCHAR(20)", "default": "'draft'"},
			],
			"ar_payments": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "invoice_id", "type": "INTEGER", "fk": "ar_invoices.id"},
				{"name": "amount", "type": "NUMERIC(19,4)"},
				{"name": "received_at", "type": "TIMESTAMPTZ"},
				{"name": "method", "type": "VARCHAR(50)"},
			],
			"credit_notes": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "invoice_id", "type": "INTEGER", "fk": "ar_invoices.id"},
				{"name": "amount", "type": "NUMERIC(19,4)"},
				{"name": "reason", "type": "TEXT"},
				{"name": "issued_at", "type": "TIMESTAMPTZ"},
			],
		},
	},
	"CRM": {
		"label": "Customer Relations",
		"color": "#9b59b6",
		"icon": "fa-handshake",
		"description": "Contacts, leads, opportunities, pipeline",
		"tables": {
			"companies": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "name", "type": "VARCHAR(255)", "nullable": False},
				{"name": "domain", "type": "VARCHAR(255)"},
				{"name": "industry", "type": "VARCHAR(100)"},
				{"name": "size", "type": "VARCHAR(50)"},
				{"name": "country", "type": "CHAR(2)"},
			],
			"contacts": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "company_id", "type": "INTEGER", "fk": "companies.id"},
				{"name": "first_name", "type": "VARCHAR(100)"},
				{"name": "last_name", "type": "VARCHAR(100)"},
				{"name": "email", "type": "VARCHAR(320)", "unique": True},
				{"name": "phone", "type": "VARCHAR(30)"},
				{"name": "title", "type": "VARCHAR(100)"},
			],
			"leads": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "contact_id", "type": "INTEGER", "fk": "contacts.id"},
				{"name": "source", "type": "VARCHAR(100)"},
				{"name": "status", "type": "VARCHAR(50)"},
				{"name": "score", "type": "INTEGER", "default": "0"},
				{"name": "assigned_to_id", "type": "INTEGER"},
				{"name": "created_at", "type": "TIMESTAMPTZ", "default": "NOW()"},
			],
			"opportunities": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "contact_id", "type": "INTEGER", "fk": "contacts.id"},
				{"name": "name", "type": "VARCHAR(255)"},
				{"name": "stage", "type": "VARCHAR(100)"},
				{"name": "probability_pct", "type": "INTEGER"},
				{"name": "amount", "type": "NUMERIC(19,4)"},
				{"name": "close_date", "type": "DATE"},
				{"name": "owner_id", "type": "INTEGER"},
			],
			"activities": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "contact_id", "type": "INTEGER", "fk": "contacts.id"},
				{"name": "opportunity_id", "type": "INTEGER", "fk": "opportunities.id"},
				{"name": "type", "type": "VARCHAR(50)"},
				{"name": "subject", "type": "VARCHAR(255)"},
				{"name": "due_at", "type": "TIMESTAMPTZ"},
				{"name": "completed_at", "type": "TIMESTAMPTZ"},
				{"name": "notes", "type": "TEXT"},
			],
		},
	},
	"HR": {
		"label": "Human Resources",
		"color": "#27ae60",
		"icon": "fa-users",
		"description": "Employees, payroll, attendance, positions",
		"tables": {
			"departments": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "name", "type": "VARCHAR(200)", "nullable": False},
				{"name": "code", "type": "VARCHAR(20)", "unique": True},
				{"name": "manager_id", "type": "INTEGER"},
				{"name": "parent_id", "type": "INTEGER", "fk": "departments.id"},
			],
			"positions": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "title", "type": "VARCHAR(200)"},
				{"name": "department_id", "type": "INTEGER", "fk": "departments.id"},
				{"name": "salary_grade", "type": "VARCHAR(20)"},
				{"name": "is_active", "type": "BOOLEAN", "default": "true"},
			],
			"employees": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "first_name", "type": "VARCHAR(100)", "nullable": False},
				{"name": "last_name", "type": "VARCHAR(100)", "nullable": False},
				{"name": "email", "type": "VARCHAR(320)", "unique": True},
				{"name": "department_id", "type": "INTEGER", "fk": "departments.id"},
				{"name": "position_id", "type": "INTEGER", "fk": "positions.id"},
				{"name": "manager_id", "type": "INTEGER", "fk": "employees.id"},
				{"name": "hire_date", "type": "DATE"},
				{"name": "salary", "type": "NUMERIC(15,4)"},
				{"name": "status", "type": "VARCHAR(30)", "default": "'active'"},
			],
			"payroll_runs": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "period_start", "type": "DATE"},
				{"name": "period_end", "type": "DATE"},
				{"name": "status", "type": "VARCHAR(30)"},
				{"name": "total_gross", "type": "NUMERIC(19,4)"},
				{"name": "total_net", "type": "NUMERIC(19,4)"},
			],
			"time_attendance": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "employee_id", "type": "INTEGER", "fk": "employees.id"},
				{"name": "clock_in", "type": "TIMESTAMPTZ"},
				{"name": "clock_out", "type": "TIMESTAMPTZ"},
				{"name": "hours_worked", "type": "NUMERIC(5,2)"},
				{"name": "date", "type": "DATE"},
			],
		},
	},
	"INV": {
		"label": "Inventory",
		"color": "#f39c12",
		"icon": "fa-boxes",
		"description": "Products, warehouses, stock movements",
		"tables": {
			"product_categories": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "name", "type": "VARCHAR(200)"},
				{"name": "parent_id", "type": "INTEGER", "fk": "product_categories.id"},
			],
			"products": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "sku", "type": "VARCHAR(100)", "unique": True},
				{"name": "name", "type": "VARCHAR(255)", "nullable": False},
				{"name": "category_id", "type": "INTEGER", "fk": "product_categories.id"},
				{"name": "unit_price", "type": "NUMERIC(19,4)"},
				{"name": "unit_of_measure", "type": "VARCHAR(30)"},
				{"name": "is_active", "type": "BOOLEAN", "default": "true"},
			],
			"warehouses": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "code", "type": "VARCHAR(20)", "unique": True},
				{"name": "name", "type": "VARCHAR(200)"},
				{"name": "address", "type": "TEXT"},
				{"name": "is_active", "type": "BOOLEAN", "default": "true"},
			],
			"stock_levels": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "product_id", "type": "INTEGER", "fk": "products.id"},
				{"name": "warehouse_id", "type": "INTEGER", "fk": "warehouses.id"},
				{"name": "quantity", "type": "NUMERIC(15,4)", "default": "0"},
				{"name": "reorder_point", "type": "NUMERIC(15,4)"},
				{"name": "updated_at", "type": "TIMESTAMPTZ", "default": "NOW()"},
			],
			"stock_movements": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "product_id", "type": "INTEGER", "fk": "products.id"},
				{"name": "warehouse_id", "type": "INTEGER", "fk": "warehouses.id"},
				{"name": "movement_type", "type": "VARCHAR(30)"},
				{"name": "quantity", "type": "NUMERIC(15,4)"},
				{"name": "moved_at", "type": "TIMESTAMPTZ", "default": "NOW()"},
				{"name": "reference", "type": "VARCHAR(100)"},
			],
		},
	},
	"GL": {
		"label": "General Ledger",
		"color": "#1abc9c",
		"icon": "fa-book",
		"description": "Chart of accounts, journal entries, budgets",
		"tables": {
			"chart_of_accounts": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "code", "type": "VARCHAR(20)", "unique": True},
				{"name": "name", "type": "VARCHAR(255)"},
				{"name": "account_type", "type": "VARCHAR(30)"},
				{"name": "parent_id", "type": "INTEGER", "fk": "chart_of_accounts.id"},
				{"name": "is_active", "type": "BOOLEAN", "default": "true"},
			],
			"fiscal_periods": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "name", "type": "VARCHAR(100)"},
				{"name": "start_date", "type": "DATE"},
				{"name": "end_date", "type": "DATE"},
				{"name": "is_closed", "type": "BOOLEAN", "default": "false"},
			],
			"journal_entries": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "period_id", "type": "INTEGER", "fk": "fiscal_periods.id"},
				{"name": "entry_date", "type": "DATE"},
				{"name": "reference", "type": "VARCHAR(100)"},
				{"name": "description", "type": "TEXT"},
				{"name": "is_posted", "type": "BOOLEAN", "default": "false"},
				{"name": "created_at", "type": "TIMESTAMPTZ", "default": "NOW()"},
			],
			"journal_lines": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "entry_id", "type": "INTEGER", "fk": "journal_entries.id"},
				{"name": "account_id", "type": "INTEGER", "fk": "chart_of_accounts.id"},
				{"name": "debit", "type": "NUMERIC(19,4)", "default": "0"},
				{"name": "credit", "type": "NUMERIC(19,4)", "default": "0"},
				{"name": "description", "type": "VARCHAR(255)"},
			],
			"budgets": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "period_id", "type": "INTEGER", "fk": "fiscal_periods.id"},
				{"name": "account_id", "type": "INTEGER", "fk": "chart_of_accounts.id"},
				{"name": "amount", "type": "NUMERIC(19,4)"},
			],
		},
	},
	"PROJ": {
		"label": "Projects",
		"color": "#e67e22",
		"icon": "fa-project-diagram",
		"description": "Projects, tasks, milestones, time logs",
		"tables": {
			"projects": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "name", "type": "VARCHAR(255)", "nullable": False},
				{"name": "code", "type": "VARCHAR(50)", "unique": True},
				{"name": "status", "type": "VARCHAR(30)", "default": "'planning'"},
				{"name": "start_date", "type": "DATE"},
				{"name": "end_date", "type": "DATE"},
				{"name": "budget", "type": "NUMERIC(19,4)"},
				{"name": "owner_id", "type": "INTEGER"},
			],
			"project_tasks": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "project_id", "type": "INTEGER", "fk": "projects.id"},
				{"name": "parent_id", "type": "INTEGER", "fk": "project_tasks.id"},
				{"name": "name", "type": "VARCHAR(255)"},
				{"name": "status", "type": "VARCHAR(30)", "default": "'todo'"},
				{"name": "assignee_id", "type": "INTEGER"},
				{"name": "start_date", "type": "DATE"},
				{"name": "due_date", "type": "DATE"},
				{"name": "pct_complete", "type": "INTEGER", "default": "0"},
			],
			"milestones": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "project_id", "type": "INTEGER", "fk": "projects.id"},
				{"name": "name", "type": "VARCHAR(255)"},
				{"name": "due_date", "type": "DATE"},
				{"name": "status", "type": "VARCHAR(30)"},
			],
			"time_logs": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "task_id", "type": "INTEGER", "fk": "project_tasks.id"},
				{"name": "user_id", "type": "INTEGER"},
				{"name": "hours", "type": "NUMERIC(6,2)"},
				{"name": "logged_date", "type": "DATE"},
				{"name": "description", "type": "TEXT"},
			],
			"project_expenses": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "project_id", "type": "INTEGER", "fk": "projects.id"},
				{"name": "description", "type": "VARCHAR(255)"},
				{"name": "amount", "type": "NUMERIC(19,4)"},
				{"name": "expense_date", "type": "DATE"},
				{"name": "category", "type": "VARCHAR(100)"},
			],
		},
	},
	"PROC": {
		"label": "Procurement",
		"color": "#95a5a6",
		"icon": "fa-shopping-cart",
		"description": "Suppliers, RFQs, purchase orders, receipts",
		"tables": {
			"suppliers": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "name", "type": "VARCHAR(255)", "nullable": False},
				{"name": "code", "type": "VARCHAR(50)", "unique": True},
				{"name": "email", "type": "VARCHAR(320)"},
				{"name": "phone", "type": "VARCHAR(30)"},
				{"name": "country", "type": "CHAR(2)"},
				{"name": "rating", "type": "INTEGER"},
			],
			"rfq_headers": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "rfq_number", "type": "VARCHAR(50)", "unique": True},
				{"name": "supplier_id", "type": "INTEGER", "fk": "suppliers.id"},
				{"name": "issued_date", "type": "DATE"},
				{"name": "response_due", "type": "DATE"},
				{"name": "status", "type": "VARCHAR(30)"},
			],
			"po_headers": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "po_number", "type": "VARCHAR(50)", "unique": True},
				{"name": "supplier_id", "type": "INTEGER", "fk": "suppliers.id"},
				{"name": "rfq_id", "type": "INTEGER", "fk": "rfq_headers.id"},
				{"name": "status", "type": "VARCHAR(30)"},
				{"name": "total_amount", "type": "NUMERIC(19,4)"},
				{"name": "order_date", "type": "DATE"},
			],
			"po_lines": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "po_id", "type": "INTEGER", "fk": "po_headers.id"},
				{"name": "description", "type": "VARCHAR(255)"},
				{"name": "quantity", "type": "NUMERIC(15,4)"},
				{"name": "unit_price", "type": "NUMERIC(19,4)"},
				{"name": "line_total", "type": "NUMERIC(19,4)"},
			],
			"goods_receipts": [
				{"name": "id", "type": "SERIAL", "pk": True},
				{"name": "po_id", "type": "INTEGER", "fk": "po_headers.id"},
				{"name": "received_date", "type": "DATE"},
				{"name": "notes", "type": "TEXT"},
			],
		},
	},
}


def _build_cytoscape_elements(modules: dict | None = None) -> list[dict]:
	"""Convert a modules dict to Cytoscape.js compound node elements."""
	if modules is None:
		modules = ERP_MODULES
	elements = []
	for mod_key, mod in modules.items():
		color = mod["color"]
		elements.append({"data": {
			"id": f"mod_{mod_key}",
			"label": mod["label"],
			"type": "module",
			"color": color,
			"icon": mod.get("icon", "fa-database"),
		}})
		for tname, cols in mod["tables"].items():
			col_summary = ", ".join(c["name"] for c in cols[:4])
			if len(cols) > 4:
				col_summary += f" +{len(cols)-4}"
			elements.append({"data": {
				"id": tname,
				"parent": f"mod_{mod_key}",
				"label": tname,
				"type": "table",
				"columns": cols,
				"col_summary": col_summary,
				"color": color,
			}})
			for col in cols:
				if col.get("fk") and "." in col["fk"]:
					ref_table = col["fk"].split(".")[0]
					elements.append({"data": {
						"id": f"e_{tname}_{col['name']}",
						"source": tname,
						"target": ref_table,
						"label": col["name"],
						"type": "fk",
					}})
	return elements


class ERDDesignerView(BaseView):
	"""Ergonomic ERD Designer with ERP templates and bidirectional schema editing."""

	route_base = "/erd-designer"
	default_view = "index"

	def _schema_manager(self):
		from pgappforge.views.erd_schema_manager import ERDSchemaManager
		engine = self.appbuilder.get_session.bind
		return ERDSchemaManager(engine)

	@expose("/")
	@has_access
	def index(self):
		# Built-in ERP modules grouped as "ERP Templates"
		erp_items = [
			{"key": k, "label": v["label"], "color": v["color"],
			 "icon": v.get("icon", "fa-database"),
			 "table_count": len(v["tables"]), "description": v.get("description", "")}
			for k, v in ERP_MODULES.items()
		]
		# Domain-grouped templates from registry
		domain_groups = {"ERP Templates": erp_items}
		try:
			from pgappforge.templates.registry import TemplateRegistry
			by_domain = TemplateRegistry().load_by_domain()
			for domain, items in by_domain.items():
				domain_groups[domain] = items
		except Exception:
			pass
		# Build ERD_CONFIG for the static JS file
		from flask_wtf.csrf import generate_csrf
		try:
			csrf_token = generate_csrf()
		except Exception:
			csrf_token = ""
		erd_config = {
			"apiBase":       "/erd-designer",
			"csrfToken":     csrf_token,
			"ddlEnabled":    current_app.config.get("FAB_ERD_DDL_ENABLED", False),
			"isAdmin":       any(getattr(r, "name", "") in ("Admin", "admin")
			                     for r in getattr(current_user, "roles", [])),
			"currentUser":   getattr(current_user, "username", ""),
			"designId":      None,   # populated when a saved design is opened
		}
		import json as _json
		return self.render_template_string(
			_DESIGNER_HTML,
			domain_groups=domain_groups,
			erd_config_json=_json.dumps(erd_config),
		)

	@expose("/api/live-schema")
	@has_access
	def api_live_schema(self):
		"""Return current DB tables as Cytoscape compound nodes."""
		try:
			mgr = self._schema_manager()
			schema = mgr.get_schema()
		except Exception as exc:
			return jsonify({"elements": [], "error": str(exc)})

		elements: list[dict] = []
		# All live tables go into a "Live DB" compound node
		elements.append({"data": {"id": "mod_LIVE", "label": "Live Database",
		                          "type": "module", "color": "#2c3e50"}})
		for tbl in schema.get("tables", []):
			tname = tbl["name"]
			col_summary = ", ".join(c["name"] for c in tbl["columns"][:4])
			elements.append({"data": {
				"id": tname, "parent": "mod_LIVE", "label": tname,
				"type": "table", "col_summary": col_summary, "color": "#2c3e50",
				"columns": tbl["columns"],
			}})
		for rel in schema.get("relationships", []):
			ft = rel.get("from_table")
			tt = rel.get("to_table")
			if ft and tt:
				elements.append({"data": {
					"id": f"e_{ft}_{tt}", "source": ft, "target": tt,
					"label": rel.get("from_col", ""), "type": "fk",
				}})
		return jsonify({"elements": elements})

	@expose("/api/module/<string:key>")
	@has_access
	def api_module(self, key: str):
		"""Return ERP template tables as Cytoscape nodes."""
		if key not in ERP_MODULES:
			return jsonify({"error": f"Unknown module: {key}"}), 404
		return jsonify({"elements": _build_cytoscape_elements()[:0] or [], "module_key": key})

	@expose("/api/all-templates")
	@has_access
	def api_all_templates(self):
		"""Return all ERP template modules (built-in + installed) as Cytoscape elements."""
		# Start with built-in ERP modules
		all_modules = dict(ERP_MODULES)
		# Merge installed templates from registry
		try:
			from pgappforge.templates import TemplateRegistry
			registered = TemplateRegistry().load_all()
			for k, v in registered.items():
				if k not in all_modules:  # don't override built-ins
					all_modules[k] = v
		except Exception:
			pass
		elements = _build_cytoscape_elements(all_modules)
		return jsonify({"elements": elements})

	@expose("/api/apply-module/<string:key>", methods=["POST"])
	@has_access
	def api_apply_module(self, key: str):
		"""CREATE TABLE SQL for all tables in an ERP module.

		Requires Admin role + FAB_ERD_DDL_ENABLED=True.
		FK columns are now forwarded so foreign key constraints are emitted.
		"""
		_require_schema_admin()
		_validate_csrf()
		if key not in ERP_MODULES:
			return jsonify({"error": f"Unknown module: {key}"}), 404
		mod = ERP_MODULES[key]
		ops = []
		for tname, cols in mod["tables"].items():
			pg_cols = []
			for c in cols:
				pg_cols.append({
					"name":     c["name"],
					"type":     c.get("type", "TEXT"),
					"pk":       c.get("pk", False),
					"nullable": c.get("nullable", True),
					"default":  c.get("default"),
					"unique":   c.get("unique", False),
					"fk":       c.get("fk"),      # ← was stripped before; now forwarded
				})
			ops.append({"op": "create_table", "table": tname, "columns": pg_cols})
		try:
			mgr    = self._schema_manager()
			uid    = getattr(current_user, "id", None)
			result = mgr.apply_changes(ops, user_id=uid)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/api/schema/apply", methods=["POST"])
	@has_access
	def api_schema_apply(self):
		"""Apply schema operations from the ERD canvas.

		Requires Admin role + FAB_ERD_DDL_ENABLED=True.
		Add ``?dry_run=1`` to preview SQL without executing.
		"""
		_require_schema_admin()
		_validate_csrf()
		ops      = request.get_json() or []
		dry_run  = request.args.get("dry_run", "0").strip() in ("1", "true", "yes")
		uid      = getattr(current_user, "id", None)
		try:
			mgr    = self._schema_manager()
			result = mgr.apply_changes(ops, dry_run=dry_run, user_id=uid)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/api/export/mermaid")
	@has_access
	def api_export_mermaid(self):
		"""Export current DB schema as Mermaid erDiagram."""
		try:
			mgr = self._schema_manager()
			mermaid = mgr.to_mermaid()
		except Exception as exc:
			mermaid = f"erDiagram\n%% Error: {exc}"
		return Response(mermaid, mimetype="text/plain",
		                headers={"Content-Disposition": "attachment; filename=schema.mmd"})

	@expose("/api/generate-app", methods=["POST"])
	@has_access
	def api_generate_app(self):
		"""Trigger pgappforge codegen on the current schema.

		Requires Admin role + FAB_ERD_DDL_ENABLED=True.
		Output path is validated against FAB_CODEGEN_OUTPUT_ROOT to prevent
		path traversal (all paths must be under the configured root).
		"""
		_require_schema_admin()
		_validate_csrf()
		body     = request.get_json() or {}
		app_name = body.get("app_name", "GeneratedApp")
		try:
			output_dir = _safe_output_dir(body.get("output_dir"), app_name)
		except Exception as exc:
			return jsonify({"status": "error", "error": str(exc)}), 400
		try:
			mgr    = self._schema_manager()
			result = mgr.generate_app(str(output_dir), app_name)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"status": "error", "error": str(exc)}), 500


	# ── Design CRUD — persisted canvas state ──────────────────────────────────

	def _db_session(self):
		"""Return the SQLAlchemy session for design persistence."""
		return self.appbuilder.get_session

	@expose("/api/designs", methods=["GET"])
	@has_access
	def api_designs_list(self):
		"""List all designs visible to the current user (own + public)."""
		from pgappforge.models.erd_models import ErdDesign
		import sqlalchemy as sa
		session = self._db_session()
		uid = getattr(current_user, "id", None)
		designs = session.execute(
			sa.select(ErdDesign).where(
				sa.or_(ErdDesign.owner_id == uid, ErdDesign.is_public == True)
			).order_by(ErdDesign.changed_on.desc()).limit(100)
		).scalars().all()
		return jsonify({"designs": [
			{"id": d.id, "name": d.name, "description": d.description,
			 "is_public": d.is_public, "changed_on": str(d.changed_on)}
			for d in designs
		]})

	@expose("/api/designs", methods=["POST"])
	@has_access
	def api_designs_create(self):
		"""Create a new saved design. Body: {name, canvas_json, schema_json}."""
		from pgappforge.models.erd_models import ErdDesign
		data   = request.get_json(silent=True) or {}
		name   = (data.get("name") or "Untitled Design").strip()
		session = self._db_session()
		design = ErdDesign(
			name=name,
			description=data.get("description", ""),
			canvas_json=data.get("canvas_json", {}),
			schema_json=data.get("schema_json", {}),
			is_public=bool(data.get("is_public", False)),
			owner_id=getattr(current_user, "id", None),
		)
		session.add(design)
		session.commit()
		return jsonify({"ok": True, "id": design.id, "name": design.name})

	@expose("/api/designs/<int:design_id>", methods=["GET"])
	@has_access
	def api_designs_get(self, design_id: int):
		"""Load a saved design (canvas_json + schema_json)."""
		from pgappforge.models.erd_models import ErdDesign
		import sqlalchemy as sa
		session = self._db_session()
		uid = getattr(current_user, "id", None)
		d = session.get(ErdDesign, design_id)
		if d is None:
			return jsonify({"error": "Design not found"}), 404
		if d.owner_id != uid and not d.is_public:
			return jsonify({"error": "Access denied"}), 403
		return jsonify({
			"id": d.id, "name": d.name, "description": d.description,
			"canvas_json": d.canvas_json, "schema_json": d.schema_json,
			"is_public": d.is_public, "changed_on": str(d.changed_on),
		})

	@expose("/api/designs/<int:design_id>", methods=["PUT"])
	@has_access
	def api_designs_update(self, design_id: int):
		"""Auto-save a design. Body: {name?, canvas_json?, schema_json?, is_public?}."""
		from pgappforge.models.erd_models import ErdDesign
		from sqlalchemy.orm.attributes import flag_modified
		data    = request.get_json(silent=True) or {}
		session = self._db_session()
		d       = session.get(ErdDesign, design_id)
		if d is None:
			return jsonify({"error": "Design not found"}), 404
		uid = getattr(current_user, "id", None)
		if d.owner_id != uid:
			return jsonify({"error": "Access denied"}), 403
		if "name"        in data: d.name        = data["name"]
		if "description" in data: d.description = data["description"]
		if "is_public"   in data: d.is_public   = bool(data["is_public"])
		if "canvas_json" in data:
			d.canvas_json = data["canvas_json"]
			flag_modified(d, "canvas_json")
		if "schema_json" in data:
			d.schema_json = data["schema_json"]
			flag_modified(d, "schema_json")
		session.commit()
		# Broadcast canvas update to other SSE clients for this design
		if "canvas_json" in data:
			self._sse_broadcast(design_id, {
				"type": "update",
				"user": getattr(current_user, "username", ""),
				"canvas_json": data["canvas_json"],
			})
		return jsonify({"ok": True})

	def _sse_broadcast(self, design_id: int, payload: dict) -> None:
		"""Broadcast a JSON payload to all SSE listeners for *design_id*."""
		msg = _json.dumps(payload)
		import time
		now = time.monotonic()
		with _SSE_LOCK:
			clients = list(_SSE_CLIENTS.get(design_id, []))
		for q in clients:
			if (now - getattr(q, "_last_active", now)) > 120:
				with _SSE_LOCK:
					lst = _SSE_CLIENTS.get(design_id, [])
					if q in lst:
						lst.remove(q)
				continue
			try:
				q.put_nowait(msg)
			except Exception:
				with _SSE_LOCK:
					lst = _SSE_CLIENTS.get(design_id, [])
					if q in lst:
						lst.remove(q)

	@expose("/api/designs/<int:design_id>", methods=["DELETE"])
	@has_access
	def api_designs_delete(self, design_id: int):
		"""Delete a saved design (owner only)."""
		from pgappforge.models.erd_models import ErdDesign
		session = self._db_session()
		d       = session.get(ErdDesign, design_id)
		if d is None:
			return jsonify({"error": "Design not found"}), 404
		if d.owner_id != getattr(current_user, "id", None):
			return jsonify({"error": "Access denied"}), 403
		session.delete(d)
		session.commit()
		return jsonify({"ok": True})

	@expose("/api/migration-log")
	@has_access
	def api_migration_log(self):
		"""Return the last 50 DDL migration log entries (Admin only)."""
		_require_schema_admin()
		from pgappforge.models.erd_models import ErdMigrationLog
		import sqlalchemy as sa
		session = self._db_session()
		entries = session.execute(
			sa.select(ErdMigrationLog)
			.order_by(ErdMigrationLog.applied_at.desc())
			.limit(50)
		).scalars().all()
		return jsonify({"entries": [
			{"id": e.id, "applied_at": str(e.applied_at), "status": e.status,
			 "sql": e.sql_json, "rollback_sql": e.rollback_sql, "error": e.error}
			for e in entries
		]})

	@expose("/api/migration-log/<int:entry_id>/rollback", methods=["POST"])
	@has_access
	def api_migration_rollback(self, entry_id: int):
		"""Execute the rollback SQL for a migration log entry."""
		_require_schema_admin()
		_validate_csrf()
		from pgappforge.models.erd_models import ErdMigrationLog
		import sqlalchemy as sa
		session = self._db_session()
		entry = session.get(ErdMigrationLog, entry_id)
		if not entry:
			return jsonify({"ok": False, "error": "Entry not found"}), 404
		rollback_stmts = entry.rollback_sql or []
		if not rollback_stmts:
			return jsonify({"ok": False, "error": "No rollback SQL available for this migration"})
		mgr = self._schema_manager()
		try:
			from sqlalchemy import text
			with mgr.engine.begin() as conn:
				for stmt in rollback_stmts:
					conn.execute(text(stmt))
		except Exception as exc:
			return jsonify({"ok": False, "error": str(exc)})
		return jsonify({"ok": True})

	# ── Phase 4: Schema diff ───────────────────────────────────────────────────

	@expose("/api/schema/diff", methods=["POST"])
	@has_access
	def api_schema_diff(self):
		"""Compute diff between proposed ops and live DB. Returns SQL + changed entities."""
		data = request.get_json(silent=True) or {}
		ops  = data.get("ops", [])
		try:
			mgr    = self._schema_manager()
			result = mgr.apply_changes(ops, dry_run=True)
			schema = mgr.get_schema()
			live_tables = {t["name"] for t in schema.get("tables", [])}
			tables_added   = [op["table"] for op in ops if op.get("op") == "create_table"]
			tables_dropped = [op["table"] for op in ops if op.get("op") == "drop_table"]
			tables_altered = [op["table"] for op in ops
			                  if op.get("op") in ("add_column", "drop_column", "alter_column")]
			return jsonify({
				"sql":            result.get("sql", []),
				"tables_added":   tables_added,
				"tables_dropped": tables_dropped,
				"tables_altered": list(set(tables_altered)),
				"dry_run":        True,
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	# ── Phase 4: Alembic migration export ─────────────────────────────────────

	@expose("/api/export/alembic")
	@has_access
	def api_export_alembic(self):
		"""Generate an Alembic migration script from pending ops in session."""
		from pgappforge.views.erd_schema_manager import _generate_rollback
		ops = request.args.get("ops")
		if ops:
			import json as _json
			try:
				ops_list = _json.loads(ops)
			except Exception:
				ops_list = []
		else:
			ops_list = []
		try:
			mgr       = self._schema_manager()
			result    = mgr.apply_changes(ops_list, dry_run=True)
			sql_stmts = result.get("sql", [])
			rollback  = _generate_rollback(ops_list, sql_stmts)
		except Exception as exc:
			sql_stmts, rollback = [], []
		upgrade_body   = "\n    ".join(
			f"op.execute({_json.dumps(s)})"
			for s in sql_stmts
		) or "    pass"
		downgrade_body = "\n    ".join(
			f"op.execute({_json.dumps(s)})"
			for s in rollback
		) or "    pass"
		from datetime import datetime
		ts = datetime.now().strftime("%Y%m%d_%H%M%S")
		script = f'''"""Auto-generated ERD migration — {ts}

Revision ID: {ts}
Created: {datetime.now().isoformat(timespec="seconds")}
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    {upgrade_body}


def downgrade() -> None:
    {downgrade_body}
'''
		filename = f"migrate_{ts}.py"
		return Response(
			script, mimetype="text/plain",
			headers={"Content-Disposition": f'attachment; filename="{filename}"'},
		)

	# ── Phase 7: ORM model code export ────────────────────────────────────────

	@expose("/api/export/orm")
	@has_access
	def api_export_orm(self):
		"""Export current DB schema as ORM model code (sqlalchemy | django | prisma)."""
		fmt = request.args.get("format", "sqlalchemy").lower()
		schema_name = request.args.get("schema", "public")
		try:
			mgr    = self._schema_manager()
			schema = mgr.get_schema()
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

		lines: list[str] = []
		if fmt == "sqlalchemy":
			lines.append("from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Numeric, ForeignKey")
			lines.append("from sqlalchemy.dialects.postgresql import JSONB, UUID")
			lines.append("from sqlalchemy.orm import DeclarativeBase, relationship\n")
			lines.append("class Base(DeclarativeBase): pass\n")
			for tbl in schema.get("tables", []):
				lines.append(f"class {tbl['name'].title().replace('_','')}(Base):")
				lines.append(f"    __tablename__ = {tbl['name']!r}")
				for col in tbl.get("columns", []):
					sa_type = _pg_to_sa_type(col.get("type", "TEXT"))
					pk = ", primary_key=True" if col.get("pk") else ""
					null = ", nullable=False" if not col.get("nullable", True) else ""
					fk = f', ForeignKey("{col["fk"]}")' if col.get("fk") else ""
					lines.append(f"    {col['name']} = Column({sa_type}{fk}{pk}{null})")
				lines.append("")
		elif fmt == "django":
			lines.append("from django.db import models\n")
			for tbl in schema.get("tables", []):
				lines.append(f"class {tbl['name'].title().replace('_','')}(models.Model):")
				for col in tbl.get("columns", []):
					if col.get("pk"):
						continue
					dj_type = _pg_to_django_type(col.get("type", "TEXT"))
					lines.append(f"    {col['name']} = {dj_type}")
				lines.append("    class Meta:")
				lines.append(f"        db_table = {tbl['name']!r}")
				lines.append("")
		elif fmt == "prisma":
			lines.append('datasource db { provider = "postgresql"; url = env("DATABASE_URL") }')
			lines.append('generator client { provider = "prisma-client-js" }\n')
			for tbl in schema.get("tables", []):
				lines.append(f"model {tbl['name'].title().replace('_','')} {{")
				for col in tbl.get("columns", []):
					prisma_type = _pg_to_prisma_type(col.get("type", "String"))
					decorators = ""
					if col.get("pk"):  decorators += " @id @default(autoincrement())"
					if col.get("unique"): decorators += " @unique"
					lines.append(f"  {col['name']}  {prisma_type}{decorators}")
				lines.append(f"  @@map({tbl['name']!r})")
				lines.append("}\n")

		code = "\n".join(lines)
		return Response(
			code, mimetype="text/plain",
			headers={"Content-Disposition": f'attachment; filename="models_{fmt}.py"'},
		)

	# ── Phase 5: Intelligence endpoints ───────────────────────────────────────

	@expose("/api/ai/generate-schema", methods=["POST"])
	@has_access
	def api_ai_generate_schema(self):
		"""Generate create_table ops from a business description via Ollama."""
		data = request.get_json(silent=True) or {}
		desc = (data.get("description") or "").strip()
		if not desc:
			return jsonify({"error": "description is required"}), 400
		try:
			from pgappforge.plugins.reports.ai_augment import augment_text
			import json as _json
			prompt = (
				f"Generate a PostgreSQL database schema for: {desc}\n\n"
				"Return a JSON array of create_table operations with this EXACT format — no markdown:\n"
				'[{"op":"create_table","table":"table_name","columns":['
				'{"name":"id","type":"SERIAL","pk":true},'
				'{"name":"col","type":"TEXT","nullable":true,"fk":"other_table.id"}]}]\n'
				"Include realistic FK relationships. Use SERIAL PKs. Return ONLY the JSON array."
			)
			result = augment_text(prompt, {}, current_app, max_tokens=3000)
			if result.startswith("Error:"):
				return jsonify({"error": result}), 500
			# Strip markdown fences
			import re as _re
			result = _re.sub(r"^```\w*\n?|```$", "", result.strip(), flags=_re.MULTILINE).strip()
			ops = _json.loads(result)
			# Validate each op's table/column names through _qi for safety
			from pgappforge.views.erd_schema_manager import _qi
			for op in ops:
				_qi(op.get("table", ""))
			return jsonify({"ops": ops, "count": len(ops)})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/api/ai/suggest-fks")
	@has_access
	def api_suggest_fks(self):
		"""Suggest FK relationships from _id column naming conventions."""
		try:
			mgr    = self._schema_manager()
			schema = mgr.get_schema()
		except Exception as exc:
			return jsonify({"suggestions": [], "error": str(exc)})

		tables = {t["name"] for t in schema.get("tables", [])}
		suggestions = []
		for tbl in schema.get("tables", []):
			existing_fks = {rel["column"] for rel in schema.get("relationships", [])
			                if rel.get("table") == tbl["name"]}
			for col in tbl.get("columns", []):
				name = col.get("name", "")
				if not name.endswith("_id"):
					continue
				if name in existing_fks:
					continue
				prefix = name[:-3]
				for candidate in (prefix + "s", prefix, prefix + "es"):
					if candidate in tables:
						suggestions.append({
							"op":         "add_fk",
							"table":      tbl["name"],
							"column":     name,
							"ref_table":  candidate,
							"ref_column": "id",
							"confidence": "high" if candidate == prefix + "s" else "medium",
						})
						break
		return jsonify({"suggestions": suggestions})

	@expose("/api/analysis/normalize")
	@has_access
	def api_analysis_normalize(self):
		"""Detect potential normalization issues in the live schema."""
		try:
			mgr    = self._schema_manager()
			schema = mgr.get_schema()
		except Exception as exc:
			return jsonify({"warnings": [], "error": str(exc)})

		warnings: list[dict] = []
		col_registry: dict[str, list[str]] = {}  # col_name → [table, ...]

		for tbl in schema.get("tables", []):
			cols = tbl.get("columns", [])
			has_pk = any(c.get("pk") for c in cols)
			if not has_pk:
				warnings.append({"level": "1NF", "table": tbl["name"],
				                 "message": "No primary key defined.",
				                 "suggestion": "Add an id SERIAL PRIMARY KEY column."})
			for col in cols:
				cname = col.get("name", "")
				# Flag generic column names
				if cname in ("data", "info", "value", "field", "col") or \
				   cname.startswith("col") and cname[3:].isdigit():
					warnings.append({"level": "1NF", "table": tbl["name"],
					                 "message": f"Generic column name: {cname!r}",
					                 "suggestion": "Use a descriptive column name."})
				# Track repeated column names for 2NF analysis
				col_registry.setdefault(cname, []).append(tbl["name"])

		# Flag columns that appear in >3 tables (potential 2NF violation)
		for cname, tbls in col_registry.items():
			if len(tbls) > 3 and cname not in ("id", "created_at", "updated_at",
			                                    "created_on", "changed_on", "is_active"):
				warnings.append({"level": "2NF",
				                 "table": tbls[0],
				                 "message": f"Column {cname!r} appears in {len(tbls)} tables.",
				                 "suggestion": f"Consider extracting {cname!r} into a separate reference table."})

		return jsonify({"warnings": warnings})

	@expose("/api/analysis/recommend-indexes")
	@has_access
	def api_recommend_indexes(self):
		"""Recommend missing indexes based on FK columns and naming conventions."""
		import sqlalchemy as sa
		try:
			mgr    = self._schema_manager()
			schema = mgr.get_schema()
			engine = self._schema_manager().engine
		except Exception as exc:
			return jsonify({"recommendations": [], "error": str(exc)})

		# Get existing indexes from PostgreSQL
		try:
			with engine.connect() as conn:
				existing_idx = conn.execute(sa.text(
					"SELECT tablename, indexname, indexdef FROM pg_indexes "
					"WHERE schemaname = 'public'"
				)).fetchall()
			indexed_cols: set[tuple[str, str]] = set()
			for row in existing_idx:
				import re as _re
				cols = _re.findall(r'\(([^)]+)\)', row[2])
				for c in cols:
					for col in c.split(","):
						indexed_cols.add((row[0], col.strip().strip('"')))
		except Exception:
			indexed_cols = set()

		recommendations = []
		_idx_keywords = ("_at", "_date", "_status", "_created", "_updated",
		                 "_type", "_state", "_code", "_key", "_ref")

		for tbl in schema.get("tables", []):
			tname = tbl["name"]
			for col in tbl.get("columns", []):
				cname = col.get("name", "")
				if col.get("pk") or (tname, cname) in indexed_cols:
					continue
				# FK columns should always be indexed
				if col.get("fk") or cname.endswith("_id"):
					recommendations.append({
						"op": "add_index", "table": tname, "columns": [cname],
						"unique": False,
						"reason": "FK column — improves JOIN performance",
					})
					continue
				# Common query-target naming patterns
				if any(cname.endswith(k) for k in _idx_keywords):
					recommendations.append({
						"op": "add_index", "table": tname, "columns": [cname],
						"unique": False,
						"reason": f"Likely WHERE/ORDER BY target (ends in {cname.split('_')[-1]!r})",
					})

		return jsonify({"recommendations": recommendations})

	# ── Phase 6: Collaboration ─────────────────────────────────────────────────

	@expose("/api/events/<int:design_id>")
	@has_access
	def api_sse_events(self, design_id: int):
		"""Server-Sent Events stream for real-time collaborative canvas updates."""
		from pgappforge.models.erd_models import ErdDesign
		from flask import stream_with_context
		session = self._db_session()
		d = session.get(ErdDesign, design_id)
		if d is None:
			return jsonify({"error": "Design not found"}), 404
		uid = getattr(current_user, "id", None)
		if d.owner_id != uid and not d.is_public:
			return jsonify({"error": "Access denied"}), 403

		import time
		q: _queue.Queue = _queue.Queue(maxsize=50)
		q._last_active = time.monotonic()
		with _SSE_LOCK:
			_SSE_CLIENTS.setdefault(design_id, []).append(q)

		def event_generator():
			try:
				yield f"data: {_json.dumps({'type': 'connected', 'design_id': design_id})}\n\n"
				while True:
					try:
						msg = q.get(timeout=25)
						q._last_active = time.monotonic()
						yield f"data: {msg}\n\n"
					except _queue.Empty:
						yield "data: {\"type\":\"ping\"}\n\n"
			finally:
				with _SSE_LOCK:
					lst = _SSE_CLIENTS.get(design_id, [])
					if q in lst:
						lst.remove(q)
					if not lst:
						_SSE_CLIENTS.pop(design_id, None)

		return Response(
			stream_with_context(event_generator()),
			mimetype="text/event-stream",
			headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
		)

	@expose("/api/designs/<int:design_id>/share", methods=["POST"])
	@has_access
	def api_share_design(self, design_id: int):
		"""Create a read-only share link for a saved design."""
		_validate_csrf()
		from pgappforge.plugins.reports.acl import generate_token
		from pgappforge.models.erd_models import ErdDesign
		session = self._db_session()
		design  = session.get(ErdDesign, design_id)
		if design is None:
			return jsonify({"error": "Design not found"}), 404
		uid = getattr(current_user, "id", None)
		if design.owner_id != uid and not design.is_public:
			return jsonify({"error": "Access denied"}), 403
		data    = request.get_json(silent=True) or {}
		expires = int(data.get("expires_hours", 48))
		tok     = generate_token(
			session, report_id=0, created_by=getattr(current_user, "id", None),
			max_uses=data.get("max_uses"),
			expires_hours=expires,
			params={"erd_design_id": design_id},
		)
		url = f"/erd-designer/view/{tok}"
		return jsonify({"ok": True, "url": url, "expires_hours": expires})

	@expose("/view/<token>")
	def api_view_shared(self, token: str):
		"""Read-only shared view of a saved ERD design (no login required)."""
		from pgappforge.plugins.reports.acl import check_token as _check_token
		from pgappforge.models.erd_models import ErdDesign
		session = self._db_session()
		try:
			_report, params = _check_token(token, session)
		except Exception:
			return Response("Link expired or invalid.", status=403)
		design_id = params.get("erd_design_id")
		if not design_id:
			return Response("No design ID in token.", status=400)
		design = session.get(ErdDesign, int(design_id))
		if design is None:
			return Response("Design not found.", status=404)
		import json as _json2
		canvas_json_safe = _json2.dumps(design.canvas_json or {}).replace("</", "<\\/")
		from markupsafe import escape as _html_escape
		design_name_safe = str(_html_escape(design.name or ""))
		return Response(
			f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{design_name_safe} — ERD View (read-only)</title>
<link rel="stylesheet" href="/static/appbuilder/css/bootstrap.min.css">
{_CY}</head>
<body style="margin:0;background:#1a1a2e">
<div id="cy" style="width:100vw;height:100vh"></div>
<script>
var cy = cytoscape({{container:document.getElementById('cy'),
  style:[{{selector:'node[type="table"]',style:{{'label':'data(label)','background-color':'#2c3e50','color':'#ecf0f1','font-size':'11px','border-width':1.5,'border-color':'data(color)','width':110,'height':40,'shape':'rectangle'}}}},
  {{selector:'edge[type="fk"]',style:{{'curve-style':'bezier','target-arrow-shape':'triangle','line-color':'#555','width':1.5}}}}],
  layout:{{name:'cose',animate:false}}
}});
var data = {canvas_json_safe};
if (data && data.elements) cy.json(data); else if (Array.isArray(data)) cy.add(data);
cy.fit();
</script>
</body></html>""",
			mimetype="text/html",
		)

	# ── Phase 7: pg_dump import ────────────────────────────────────────────────

	@expose("/api/schema/import-sql", methods=["POST"])
	@has_access
	def api_import_sql(self):
		"""Import DDL from a SQL file (supports pg_dump output format)."""
		_require_schema_admin()
		_validate_csrf()
		data    = request.get_json(silent=True) or {}
		sql     = (data.get("sql") or "").strip()
		dry_run = bool(data.get("dry_run", False))
		if not sql:
			return jsonify({"error": "sql is required"}), 400
		mgr    = self._schema_manager()
		result = mgr.import_sql(sql)
		return jsonify(result)

	# ── Trigger/Function panel ─────────────────────────────────────────────────

	@expose("/api/triggers/templates")
	@has_access
	def api_trigger_templates(self):
		"""List all available trigger/function templates with metadata."""
		from pgappforge.views.erd_schema_manager import TriggerProcedureManager
		mgr = TriggerProcedureManager(self._schema_manager().engine)
		return jsonify({"templates": mgr.list_templates()})

	@expose("/api/triggers/list")
	@has_access
	def api_trigger_list(self):
		"""List all triggers in the live database, optionally filtered by table."""
		from pgappforge.views.erd_schema_manager import TriggerProcedureManager
		table  = request.args.get("table")
		mgr    = TriggerProcedureManager(self._schema_manager().engine)
		result = mgr.list_triggers(table=table)
		return jsonify({"triggers": result})

	@expose("/api/functions/list")
	@has_access
	def api_function_list(self):
		"""List all user-defined functions/procedures."""
		from pgappforge.views.erd_schema_manager import TriggerProcedureManager
		schema = request.args.get("schema", "public")
		mgr    = TriggerProcedureManager(self._schema_manager().engine)
		return jsonify({"functions": mgr.list_functions(schema=schema)})

	@expose("/api/functions/source")
	@has_access
	def api_function_source(self):
		"""Return the source code of a function."""
		from pgappforge.views.erd_schema_manager import TriggerProcedureManager
		name   = request.args.get("name", "")
		schema = request.args.get("schema", "public")
		if not name:
			return jsonify({"error": "name required"}), 400
		mgr = TriggerProcedureManager(self._schema_manager().engine)
		src = mgr.get_function_source(name, schema)
		return jsonify({"source": src or ""})

	@expose("/api/triggers/apply-template", methods=["POST"])
	@has_access
	def api_trigger_apply_template(self):
		"""Apply a trigger template with given parameters."""
		_require_schema_admin()
		_validate_csrf()
		from pgappforge.views.erd_schema_manager import TriggerProcedureManager
		data         = request.get_json(silent=True) or {}
		template_key = data.get("template_key", "")
		params       = {k: v for k, v in data.items() if k != "template_key"}
		if not template_key:
			return jsonify({"error": "template_key required"}), 400
		try:
			mgr    = TriggerProcedureManager(self._schema_manager().engine)
			result = mgr.apply_template(template_key, **params)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/api/triggers/drop", methods=["POST"])
	@has_access
	def api_trigger_drop(self):
		"""Drop a trigger from a table."""
		_require_schema_admin()
		_validate_csrf()
		from pgappforge.views.erd_schema_manager import TriggerProcedureManager
		data         = request.get_json(silent=True) or {}
		table        = data.get("table", "")
		trigger_name = data.get("trigger_name", "")
		if not table or not trigger_name:
			return jsonify({"error": "table and trigger_name required"}), 400
		try:
			mgr    = TriggerProcedureManager(self._schema_manager().engine)
			result = mgr.drop_trigger(table, trigger_name)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/api/functions/create", methods=["POST"])
	@has_access
	def api_function_create(self):
		"""Create or replace a custom function/procedure."""
		_require_schema_admin()
		_validate_csrf()
		from pgappforge.views.erd_schema_manager import TriggerProcedureManager
		data   = request.get_json(silent=True) or {}
		name   = data.get("name", "")
		body   = data.get("body", "")
		args   = data.get("args", "")
		ret    = data.get("returns", "void")
		lang   = data.get("language", "plpgsql")
		schema = data.get("schema", "public")
		if not name or not body:
			return jsonify({"error": "name and body required"}), 400
		if lang not in ("plpgsql", "sql"):
			return jsonify({"error": f"language must be plpgsql or sql"}), 400
		try:
			mgr    = TriggerProcedureManager(self._schema_manager().engine)
			result = mgr.create_function(name, args=args, returns=ret,
			                             body=body, language=lang, schema=schema)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/api/functions/drop", methods=["POST"])
	@has_access
	def api_function_drop(self):
		"""Drop a function/procedure."""
		_require_schema_admin()
		_validate_csrf()
		from pgappforge.views.erd_schema_manager import TriggerProcedureManager
		data   = request.get_json(silent=True) or {}
		name   = data.get("name", "")
		args   = data.get("args", "")
		schema = data.get("schema", "public")
		if not name:
			return jsonify({"error": "name required"}), 400
		try:
			mgr    = TriggerProcedureManager(self._schema_manager().engine)
			result = mgr.drop_function(name, args=args, schema=schema)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	# ── Database Objects panel (Domains, Views, Mat.Views, Policies, Event Triggers)

	def _object_manager(self):
		from pgappforge.views.erd_object_manager import DatabaseObjectManager
		return DatabaseObjectManager(self._schema_manager().engine)

	@expose("/api/objects/templates")
	@has_access
	def api_object_templates(self):
		"""List all database-object templates, optionally filtered by type."""
		from pgappforge.views.erd_object_manager import DatabaseObjectManager
		obj_type = request.args.get("type")
		mgr = self._object_manager()
		return jsonify({"templates": mgr.list_object_templates(obj_type or None)})

	@expose("/api/objects/apply-template", methods=["POST"])
	@has_access
	def api_object_apply_template(self):
		"""Apply a database-object template."""
		_require_schema_admin()
		_validate_csrf()
		data         = request.get_json(silent=True) or {}
		template_key = data.pop("template_key", "")
		if not template_key:
			return jsonify({"error": "template_key required"}), 400
		try:
			mgr    = self._object_manager()
			result = mgr.apply_object_template(template_key, **data)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	# Domains
	@expose("/api/domains/list")
	@has_access
	def api_domains_list(self):
		schema = request.args.get("schema", "public")
		return jsonify({"domains": self._object_manager().list_domains(schema)})

	@expose("/api/domains/drop", methods=["POST"])
	@has_access
	def api_domains_drop(self):
		_require_schema_admin(); _validate_csrf()
		d = request.get_json(silent=True) or {}
		try:
			r = self._object_manager().drop_domain(d["name"], d.get("schema","public"), d.get("cascade",False))
			return jsonify(r)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	# Event triggers
	@expose("/api/event-triggers/list")
	@has_access
	def api_event_trigger_list(self):
		return jsonify({"event_triggers": self._object_manager().list_event_triggers()})

	@expose("/api/event-triggers/drop", methods=["POST"])
	@has_access
	def api_event_trigger_drop(self):
		_require_schema_admin(); _validate_csrf()
		d    = request.get_json(silent=True) or {}
		name = d.get("name", "")
		if not name:
			return jsonify({"error": "name required"}), 400
		return jsonify(self._object_manager().drop_event_trigger(name))

	@expose("/api/event-triggers/toggle", methods=["POST"])
	@has_access
	def api_event_trigger_toggle(self):
		_require_schema_admin(); _validate_csrf()
		d = request.get_json(silent=True) or {}
		return jsonify(self._object_manager().toggle_event_trigger(d.get("name",""), bool(d.get("enable",True))))

	# Materialized views
	@expose("/api/matviews/list")
	@has_access
	def api_matview_list(self):
		schema = request.args.get("schema", "public")
		return jsonify({"mat_views": self._object_manager().list_mat_views(schema)})

	@expose("/api/matviews/refresh", methods=["POST"])
	@has_access
	def api_matview_refresh(self):
		_require_schema_admin(); _validate_csrf()
		d = request.get_json(silent=True) or {}
		return jsonify(self._object_manager().refresh_mat_view(
			d.get("name",""), d.get("schema","public"), d.get("concurrently", True)
		))

	@expose("/api/matviews/drop", methods=["POST"])
	@has_access
	def api_matview_drop(self):
		_require_schema_admin(); _validate_csrf()
		d = request.get_json(silent=True) or {}
		return jsonify(self._object_manager().drop_view(d.get("name",""), d.get("schema","public"), materialized=True))

	# Views
	@expose("/api/views/list")
	@has_access
	def api_view_list(self):
		schema = request.args.get("schema", "public")
		return jsonify({"views": self._object_manager().list_views(schema)})

	@expose("/api/views/definition")
	@has_access
	def api_view_definition(self):
		name   = request.args.get("name", "")
		schema = request.args.get("schema", "public")
		mat    = request.args.get("materialized","0") in ("1","true")
		defn   = self._object_manager().get_view_definition(name, schema, mat)
		return jsonify({"definition": defn})

	@expose("/api/views/create", methods=["POST"])
	@has_access
	def api_view_create(self):
		_require_schema_admin(); _validate_csrf()
		d = request.get_json(silent=True) or {}
		try:
			r = self._object_manager().create_view(
				d.get("name",""), d.get("query",""),
				d.get("schema","public"), bool(d.get("materialized",False))
			)
			return jsonify(r)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/api/views/drop", methods=["POST"])
	@has_access
	def api_view_drop(self):
		_require_schema_admin(); _validate_csrf()
		d = request.get_json(silent=True) or {}
		return jsonify(self._object_manager().drop_view(
			d.get("name",""), d.get("schema","public"), bool(d.get("materialized",False))
		))

	# Policies
	@expose("/api/policies/list")
	@has_access
	def api_policy_list(self):
		table  = request.args.get("table")
		schema = request.args.get("schema", "public")
		return jsonify({"policies": self._object_manager().list_policies(table, schema)})

	@expose("/api/policies/create", methods=["POST"])
	@has_access
	def api_policy_create(self):
		_require_schema_admin(); _validate_csrf()
		d = request.get_json(silent=True) or {}
		try:
			r = self._object_manager().create_policy(
				d.get("table",""), d.get("name",""), d.get("using_expr",""),
				d.get("command","ALL"), d.get("check_expr"),
				d.get("schema","public"),
			)
			return jsonify(r)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/api/policies/drop", methods=["POST"])
	@has_access
	def api_policy_drop(self):
		_require_schema_admin(); _validate_csrf()
		d = request.get_json(silent=True) or {}
		return jsonify(self._object_manager().drop_policy(
			d.get("table",""), d.get("name",""), d.get("schema","public")
		))

	# ── Phase 5: Schema namespace list ────────────────────────────────────────

	@expose("/api/schema-list")
	@has_access
	def api_schema_list(self):
		"""Return list of PostgreSQL schemas accessible to the current connection."""
		try:
			import sqlalchemy as sa
			engine  = self._schema_manager().engine
			with engine.connect() as conn:
				rows = conn.execute(sa.text(
					"SELECT schema_name FROM information_schema.schemata "
					"WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast') "
					"ORDER BY schema_name"
				)).fetchall()
			schemas = [r[0] for r in rows]
		except Exception:
			schemas = ["public"]
		return jsonify({"schemas": schemas})


# ORM type helpers live in erd_schema_manager — import from canonical location
from pgappforge.views.erd_schema_manager import (
	_pg_to_sa_type, _pg_to_django_type, _pg_to_prisma_type,
)


# ─── HTML Template ────────────────────────────────────────────────────────────

_DESIGNER_HTML = ("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ERD Designer</title>
  <link rel="stylesheet"
    href="{{ url_for('static', filename='appbuilder/css/bootstrap.min.css') }}">
  """ + _CY + """
  """ + _CYTOSCAPE_EXTENSIONS_CDN + """
  <style>
    :root {
      --bg:#1a1a2e; --sidebar-bg:#2c3e50; --sidebar-hdr:#1a252f;
      --cy-bg:#1a1a2e; --node-bg:#2c3e50; --text:#ecf0f1;
      --border:#34495e; --muted:#7f8c8d;
    }
    [data-theme="light"] {
      --bg:#f0f2f5; --sidebar-bg:#2c3e50; --sidebar-hdr:#1a252f;
      --cy-bg:#f9fafb; --node-bg:#ffffff; --text:#2c3e50;
      --border:#dce0e6; --muted:#888;
    }
    * { box-sizing:border-box; }
    body { margin:0; overflow:hidden; font-size:13px; background:var(--bg); }
    #layout { display:flex; height:100vh; }
    /* Sidebar */
    #sidebar { width:260px; min-width:220px; background:var(--sidebar-bg);
               color:var(--text); overflow-y:auto; display:flex; flex-direction:column; }
    #sidebar-header { padding:10px 12px; background:var(--sidebar-hdr);
                      font-size:.9em; font-weight:600; display:flex;
                      align-items:center; justify-content:space-between; }
    #search-box { width:100%; padding:6px 10px; background:#34495e;
                  border:none; color:#ecf0f1; font-size:.85em; outline:none; }
    #search-box::placeholder { color:var(--muted); }
    #canvas-search { width:100%; padding:4px 8px; background:#34495e; border:none;
                     color:#ecf0f1; font-size:.8em; outline:none; border-top:1px solid var(--border); }
    #module-list { flex:1; overflow-y:auto; }
    .mod-item { padding:7px 12px; cursor:pointer; border-bottom:1px solid var(--border);
                display:flex; align-items:center; gap:8px; }
    .mod-item:hover { background:#34495e; }
    .mod-dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
    .mod-label { flex:1; font-size:.85em; }
    .mod-count { font-size:.75em; color:var(--muted); }
    .domain-items { display:block; }
    .domain-items.collapsed { display:none; }
    .domain-header:hover { background:#243342 !important; }
    /* Toolbar */
    #toolbar { padding:8px 10px; background:var(--sidebar-hdr);
               border-top:1px solid #0d1b2a; display:flex; flex-direction:column; gap:4px; }
    .tb-sect { font-size:.72em; color:var(--muted); margin:6px 0 2px; letter-spacing:.04em; }
    .tb-row  { display:flex; gap:4px; }
    .tb-row button { flex:1; }
    /* Canvas */
    #cy-wrap { flex:1; position:relative; background:var(--cy-bg); }
    #cy { width:100%; height:100%; }
    #cy-nav { position:absolute; bottom:28px; right:8px; width:180px; height:120px;
              border:1px solid var(--border); border-radius:4px; overflow:hidden; z-index:5; }
    #status-bar { position:absolute; bottom:0; left:0; right:0;
                  background:rgba(0,0,0,.65); color:#aaa; padding:3px 8px;
                  font-size:.75em; pointer-events:none; }
    /* Info panel */
    #info-panel { position:absolute; top:8px; right:8px; background:rgba(20,30,50,.92);
                  color:#ecf0f1; border-radius:8px; padding:10px 14px; font-size:.8em;
                  max-width:270px; display:none; max-height:340px; overflow-y:auto;
                  box-shadow:0 4px 16px rgba(0,0,0,.4); }
    .ip-title { font-weight:700; font-size:.95em; margin-bottom:6px; color:#3498db; }
    .col-row  { display:flex; align-items:center; gap:4px; padding:2px 0;
                border-bottom:1px solid rgba(255,255,255,.06); }
    .col-badge { font-size:.65em; padding:1px 4px; border-radius:3px; font-weight:700; }
    .col-badge.pk { background:#f39c12; color:#000; }
    .col-badge.fk { background:#3498db; color:#fff; }
    .col-badge.uq { background:#27ae60; color:#fff; }
    .col-name  { flex:1; }
    .col-type  { color:var(--muted); font-size:.85em; }
    .ip-actions { margin-top:6px; }
    .ip-btn { font-size:.75em; padding:2px 8px; }
    /* Context menu */
    #context-menu { position:fixed; background:#2c3e50; border:1px solid var(--border);
                    border-radius:6px; z-index:9999; display:none; min-width:160px;
                    box-shadow:0 4px 12px rgba(0,0,0,.4); }
    .cm-item { padding:7px 14px; cursor:pointer; font-size:.85em; color:#ecf0f1; }
    .cm-item:hover { background:#34495e; }
    .cm-sep { border-top:1px solid var(--border); margin:2px 0; }
    /* Generic modals */
    .erd-modal { position:fixed; inset:0; background:rgba(0,0,0,.6);
                 display:none; align-items:center; justify-content:center; z-index:10000; }
    .erd-modal-box { background:#1e2a3a; border-radius:10px; padding:24px;
                     min-width:340px; max-width:640px; width:90%; color:#ecf0f1;
                     max-height:80vh; overflow-y:auto;
                     box-shadow:0 8px 32px rgba(0,0,0,.6); }
    .erd-modal-box h5 { margin:0 0 14px; font-size:1em; color:#3498db; }
    .erd-modal-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; }
    /* Column editor table */
    #col-editor-rows td { padding:2px 3px; }
    #col-editor-rows input[type=text],
    #col-editor-rows input:not([type]) { background:#253545; border:1px solid #445566;
      color:#ecf0f1; padding:2px 6px; border-radius:3px; width:100%; font-size:.8em; }
    .del-btn { background:#c0392b; color:#fff; border:none; border-radius:3px;
               padding:1px 5px; cursor:pointer; font-size:.8em; }
    /* Diff badges */
    .diff-legend { display:flex; gap:12px; font-size:.8em; margin-bottom:8px; }
    .diff-dot { width:12px; height:12px; border-radius:50%; display:inline-block; }
    /* Analysis warning nodes */
    .analysis-warn { border-color:#e67e22 !important; border-width:4px !important; }
    /* Undo/redo */
    #btn-undo:disabled, #btn-redo:disabled { opacity:.4; }
    /* Trigger panel */
    .tpanel { min-height:200px; }
    .tpl-card { background:#253545; border:1px solid #34495e; border-radius:6px;
                padding:10px; cursor:pointer; transition:border-color .2s; }
    .tpl-card:hover { border-color:#3498db; }
    .tpl-card h6 { margin:0 0 4px; font-size:.82em; color:#3498db; }
    .tpl-card p  { margin:0; font-size:.74em; color:#7f8c8d; line-height:1.3; }
    .tpl-card.selected { border-color:#27ae60; background:#1e3a2f; }
    .tcat.active { background:#3498db; border-color:#3498db; color:#fff; }
    .trigger-row { padding:5px 8px; border-bottom:1px solid #253545; display:flex;
                   align-items:center; justify-content:space-between; font-size:.8em; }
    .trigger-row b { color:#e67e22; }
    .fn-row { padding:5px 8px; border-bottom:1px solid #253545; cursor:pointer;
              font-size:.8em; display:flex; align-items:center; justify-content:space-between; }
    .fn-row:hover { background:#1e2a3a; }
    /* pg types datalist */
    #pg-types-list { display:none; }
    button { cursor:pointer; }
  </style>
</head>
<body>
<div id="layout">
  <!-- Left sidebar -->
  <div id="sidebar">
    <div id="sidebar-header">
      <span>&#9673; ERD Designer</span>
      <button id="btn-theme" onclick="applyTheme(_theme==='dark'?'light':'dark')"
              style="background:none;border:none;color:#ecf0f1;cursor:pointer;font-size:.8em">
        ☀ Light
      </button>
    </div>
    <input id="search-box" placeholder="&#128270; Filter modules…" oninput="filterModules(this.value)">
    <input id="canvas-search" placeholder="&#128270; Search canvas…" oninput="canvasSearch(this.value)">
    <div style="padding:6px 12px;font-size:.72em;color:#7f8c8d;border-bottom:1px solid #34495e;letter-spacing:.04em">
      ERP TEMPLATES — click to add
    </div>
    <div id="module-list">
      {% for domain, items in domain_groups.items() %}
      <div class="domain-group">
        <div class="domain-header" onclick="toggleDomain(this)"
             style="padding:5px 12px;background:#1a252f;font-size:.72em;
                    color:#7f8c8d;letter-spacing:.05em;cursor:pointer;
                    display:flex;align-items:center;justify-content:space-between;
                    border-top:1px solid #0d1b2a;user-select:none">
          <span>{{ domain | upper }}</span>
          <span>{{ items|length }} ▾</span>
        </div>
        <div class="domain-items">
          {% for m in items %}
          <div class="mod-item" onclick="addModule('{{ m.key }}')"
               data-label="{{ m.label }}" data-domain="{{ domain }}"
               title="{{ m.description }}">
            <div class="mod-dot" style="background:{{ m.color }}"></div>
            <span class="mod-label">{{ m.label }}</span>
            <span class="mod-count">{{ m.table_count }}t</span>
          </div>
          {% endfor %}
        </div>
      </div>
      {% endfor %}
    </div>

    <div id="toolbar">
      <!-- Schema -->
      <div class="tb-sect">SCHEMA</div>
      <select id="schema-switcher" onchange="loadLiveSchema(this.value)"
              style="background:#34495e;border:1px solid #4a6278;color:#ecf0f1;
                     padding:3px;font-size:.8em;width:100%;margin-bottom:2px">
        <option value="public">public</option>
      </select>
      <button class="btn btn-xs btn-default btn-block" onclick="loadLiveSchema()">
        &#9654; Load live DB schema
      </button>
      <!-- Canvas controls -->
      <div class="tb-sect">CANVAS</div>
      <div class="tb-row">
        <button class="btn btn-xs btn-default" onclick="cy.fit()" title="Fit all (Ctrl+Shift+F)">&#9636;</button>
        <button class="btn btn-xs btn-default" onclick="relayout()" title="Re-layout">&#8853;</button>
        <button id="btn-undo" class="btn btn-xs btn-default" onclick="undoAction()" title="Undo (Ctrl+Z)" disabled>&#8630;</button>
        <button id="btn-redo" class="btn btn-xs btn-default" onclick="redoAction()" title="Redo (Ctrl+Y)" disabled>&#8631;</button>
        <button class="btn btn-xs btn-danger" onclick="if(confirm('Clear canvas?'))cy.elements().remove()" title="Clear">&#215;</button>
      </div>
      <!-- Export -->
      <div class="tb-sect">EXPORT</div>
      <div class="tb-row">
        <button class="btn btn-xs btn-default" onclick="window.open('/erd-designer/api/export/mermaid')">Mermaid</button>
        <button class="btn btn-xs btn-default" onclick="exportCanvas('png')">PNG</button>
        <button class="btn btn-xs btn-default" onclick="exportCanvas('svg')">SVG</button>
      </div>
      <div class="tb-row">
        <button class="btn btn-xs btn-default" onclick="window.open('/erd-designer/api/export/alembic')">Alembic</button>
        <button class="btn btn-xs btn-default" onclick="window.open('/erd-designer/api/export/orm?format=sqlalchemy')">ORM</button>
      </div>
      <!-- Save / Load designs -->
      <div class="tb-sect">DESIGN</div>
      <div class="tb-row">
        <button class="btn btn-xs btn-primary" onclick="saveCurrentDesign()" title="Save (Ctrl+Shift+S)">&#128190; Save</button>
        <button class="btn btn-xs btn-default" onclick="document.getElementById('design-load-modal').style.display='flex'">&#128193; Load</button>
      </div>
      <!-- Analysis -->
      <div class="tb-sect">ANALYSIS</div>
      <div class="tb-row">
        <button class="btn btn-xs btn-default" onclick="suggestFKs()" title="Suggest FK from _id columns">FK Hints</button>
        <button class="btn btn-xs btn-default" onclick="runNormalizationAnalysis()">Normalize</button>
      </div>
      <div class="tb-row">
        <button class="btn btn-xs btn-default" onclick="recommendIndexes()">&#9660; Indexes</button>
        <button class="btn btn-xs btn-info"    onclick="aiGenerateSchema()">&#129302; AI Gen</button>
      </div>
      <!-- Database Objects -->
      <div class="tb-sect">DATABASE OBJECTS</div>
      <div class="tb-row">
        <button class="btn btn-xs btn-default" onclick="openTriggerPanel('templates')"    title="Trigger templates">&#9889; Triggers</button>
        <button class="btn btn-xs btn-default" onclick="openTriggerPanel('functions')"    title="Browse functions">&#402; Fns</button>
        <button class="btn btn-xs btn-primary" onclick="openTriggerPanel('editor')"       title="Function editor">&#9998; Edit</button>
      </div>
      <div class="tb-row">
        <button class="btn btn-xs btn-default" onclick="openTriggerPanel('domains')"      title="Domains">&#127358; Domains</button>
        <button class="btn btn-xs btn-default" onclick="openTriggerPanel('views')"        title="Views">&#128065; Views</button>
        <button class="btn btn-xs btn-default" onclick="openTriggerPanel('policies')"     title="RLS Policies">&#128274; RLS</button>
      </div>
      <div class="tb-row">
        <button class="btn btn-xs btn-default" onclick="openTriggerPanel('matviews')"     title="Materialized views">&#8635; MatViews</button>
        <button class="btn btn-xs btn-default" onclick="openTriggerPanel('evtrig')"       title="Event triggers">&#9889; EvTrig</button>
        <button class="btn btn-xs btn-warning" onclick="openTriggerPanel('objtpl')"       title="All 43 templates">&#128230; All Tpl</button>
      </div>
      <!-- Diff -->
      <div class="tb-sect">MIGRATION</div>
      <button class="btn btn-xs btn-warning btn-block" onclick="showDiff([])">Preview Diff</button>
      <button class="btn btn-xs btn-default btn-block" onclick="document.getElementById('mig-log-modal').style.display='flex'">Migration Log</button>
      <!-- Generate app -->
      <div class="tb-sect">GENERATE APP</div>
      <input id="gen-name" class="form-control input-sm" placeholder="App name" value="MyApp"
             style="margin-bottom:4px;background:#34495e;border-color:#4a6278;color:#ecf0f1">
      <button class="btn btn-xs btn-success btn-block" onclick="generateApp()">&#9654;&#9654; Generate</button>
    </div>
  </div>

  <!-- Canvas -->
  <div id="cy-wrap">
    <div id="cy"></div>
    <div id="cy-nav"></div>
    <div id="status-bar">
      Click a module to add it. Double-click a table to edit columns. Drag from a node handle to create a FK.
      Right-click for context menu. Ctrl+Z undo.
    </div>
    <div id="info-panel"></div>
  </div>
</div>

<!-- Context menu -->
<div id="context-menu">
  <div class="cm-item" id="cm-fold">&#9654; Fold module</div>
  <div class="cm-item" id="cm-remove">&#215; Remove</div>
  <div class="cm-sep"></div>
  <div class="cm-item" id="cm-fit-sel">&#9636; Fit selection</div>
  <div class="cm-item" id="cm-mn" style="display:none">&#8853; Create M:N junction</div>
</div>

<!-- FK modal -->
<div id="fk-modal" class="erd-modal">
  <div class="erd-modal-box" style="max-width:420px">
    <h5>&#128279; Create Foreign Key</h5>
    <p style="font-size:.85em;color:#aaa">
      <b id="fk-src-table"></b> → <b id="fk-tgt-table"></b>
    </p>
    <div style="display:flex;gap:12px">
      <div style="flex:1">
        <label style="font-size:.8em">Source column</label>
        <select id="fk-src-col" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566"></select>
      </div>
      <div style="flex:1">
        <label style="font-size:.8em">References column</label>
        <select id="fk-tgt-col" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566"></select>
      </div>
    </div>
    <div class="erd-modal-actions">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('fk-modal').style.display='none'">Cancel</button>
      <button class="btn btn-sm btn-primary" id="fk-ok">Add FK</button>
    </div>
  </div>
</div>

<!-- Column editor modal -->
<div id="col-editor-modal" class="erd-modal">
  <div class="erd-modal-box" style="max-width:680px">
    <h5>&#9998; Edit Columns: <span id="col-editor-title"></span></h5>
    <div style="overflow-x:auto">
      <table class="table table-condensed" style="font-size:.8em;color:#ecf0f1">
        <thead style="color:#7f8c8d">
          <tr><th>Name</th><th>Type</th><th>PK</th><th>UQ</th><th>NN</th><th>Default</th><th></th></tr>
        </thead>
        <tbody id="col-editor-rows"></tbody>
      </table>
    </div>
    <!-- PG type autocomplete list -->
    <datalist id="pg-types-list">
      <option>SERIAL</option><option>BIGSERIAL</option><option>INTEGER</option>
      <option>BIGINT</option><option>TEXT</option><option>VARCHAR(255)</option>
      <option>BOOLEAN</option><option>NUMERIC(10,2)</option><option>DATE</option>
      <option>TIMESTAMPTZ</option><option>UUID</option><option>JSONB</option>
      <option>INET</option><option>BYTEA</option>
    </datalist>
    <button id="col-editor-add" class="btn btn-xs btn-default">+ Add column</button>
    <div class="erd-modal-actions">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('col-editor-modal').style.display='none'">Cancel</button>
      <button class="btn btn-sm btn-primary" id="col-editor-save">&#10003; Save</button>
    </div>
  </div>
</div>

<!-- AI schema generation modal -->
<div id="ai-gen-modal" class="erd-modal">
  <div class="erd-modal-box" style="max-width:500px">
    <h5>&#129302; AI Schema Generator</h5>
    <p style="font-size:.85em;color:#aaa">Describe your system and AI will design the schema.</p>
    <textarea id="ai-gen-desc" class="form-control" rows="4"
      style="background:#253545;color:#ecf0f1;border-color:#445566"
      placeholder="e.g. Hospital appointment system with doctors, patients, specialties and appointments"></textarea>
    <div class="erd-modal-actions">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('ai-gen-modal').style.display='none'">Cancel</button>
      <button class="btn btn-sm btn-info" id="ai-gen-go">&#9654; Generate</button>
    </div>
    <div id="ai-gen-preview" style="margin-top:10px;font-size:.8em;color:#aaa"></div>
    <button id="ai-gen-confirm" class="btn btn-sm btn-success" style="display:none;margin-top:8px">&#10003; Apply to Database</button>
  </div>
</div>

<!-- FK suggestion modal -->
<div id="fk-suggest-modal" class="erd-modal">
  <div class="erd-modal-box">
    <h5>&#128279; Suggested Foreign Keys</h5>
    <p style="font-size:.8em;color:#aaa">These FK relationships were detected from column naming conventions.</p>
    <ul id="fk-suggest-list" style="font-size:.85em;list-style:none;padding:0;max-height:300px;overflow-y:auto"></ul>
    <div class="erd-modal-actions">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('fk-suggest-modal').style.display='none'">Cancel</button>
      <button class="btn btn-sm btn-primary" id="fk-suggest-apply">&#10003; Apply Selected</button>
    </div>
  </div>
</div>

<!-- Normalization analysis modal -->
<div id="analysis-modal" class="erd-modal">
  <div class="erd-modal-box">
    <h5>&#9888; Normalization Analysis</h5>
    <ul id="analysis-list" style="font-size:.85em;max-height:350px;overflow-y:auto;padding-left:18px"></ul>
    <div class="erd-modal-actions">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('analysis-modal').style.display='none';clearDiff()">Close</button>
    </div>
  </div>
</div>

<!-- Index recommendation modal -->
<div id="index-rec-modal" class="erd-modal">
  <div class="erd-modal-box">
    <h5>&#9660; Recommended Indexes</h5>
    <ul id="index-rec-list" style="font-size:.85em;list-style:none;padding:0;max-height:320px;overflow-y:auto"></ul>
    <div class="erd-modal-actions">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('index-rec-modal').style.display='none'">Cancel</button>
      <button class="btn btn-sm btn-primary" id="index-rec-apply">&#10003; Apply Selected</button>
    </div>
  </div>
</div>

<!-- Diff preview modal -->
<div id="diff-modal" class="erd-modal">
  <div class="erd-modal-box" style="max-width:600px">
    <h5>&#9651; Schema Diff Preview</h5>
    <div class="diff-legend">
      <span><span class="diff-dot" style="background:#2ecc71"></span> New</span>
      <span><span class="diff-dot" style="background:#e74c3c"></span> Dropped</span>
      <span><span class="diff-dot" style="background:#f39c12"></span> Altered</span>
    </div>
    <pre id="diff-sql-preview" style="background:#111;padding:10px;font-size:.75em;
         max-height:300px;overflow:auto;color:#00ff99;border-radius:4px"></pre>
    <div class="erd-modal-actions">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('diff-modal').style.display='none';clearDiff()">Close</button>
    </div>
  </div>
</div>

<!-- Design load modal -->
<div id="design-load-modal" class="erd-modal">
  <div class="erd-modal-box" style="max-width:500px">
    <h5>&#128193; Load Saved Design</h5>
    <div id="design-list" style="max-height:300px;overflow-y:auto;font-size:.85em">
      <div style="color:#7f8c8d">Loading…</div>
    </div>
    <div class="erd-modal-actions">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('design-load-modal').style.display='none'">Cancel</button>
    </div>
  </div>
</div>

<!-- ─── Trigger / Function panel modal ─────────────────────────────── -->
<div id="trigger-modal" class="erd-modal">
  <div class="erd-modal-box" style="max-width:820px;width:96vw">
    <h5 style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">
      <span>&#9889; Database Objects</span>
      <div style="display:flex;gap:4px;flex-wrap:wrap">
        <!-- Row 1: Triggers & Functions -->
        <button class="btn btn-xs btn-default" id="tab-templates" onclick="switchTriggerTab('templates')">Triggers</button>
        <button class="btn btn-xs btn-default" id="tab-live"      onclick="switchTriggerTab('live')">Live Triggers</button>
        <button class="btn btn-xs btn-default" id="tab-functions"  onclick="switchTriggerTab('functions')">Functions</button>
        <button class="btn btn-xs btn-primary" id="tab-editor"    onclick="switchTriggerTab('editor')">&#9998; Fn Editor</button>
        <span style="border-left:1px solid #34495e;margin:0 2px"></span>
        <!-- Row 2: New object types -->
        <button class="btn btn-xs btn-default" id="tab-domains"   onclick="switchTriggerTab('domains')">&#127358; Domains</button>
        <button class="btn btn-xs btn-default" id="tab-evtrig"    onclick="switchTriggerTab('evtrig')">&#9889; Evt Triggers</button>
        <button class="btn btn-xs btn-default" id="tab-matviews"  onclick="switchTriggerTab('matviews')">&#128193; Mat.Views</button>
        <button class="btn btn-xs btn-default" id="tab-views"     onclick="switchTriggerTab('views')">&#128065; Views</button>
        <button class="btn btn-xs btn-default" id="tab-policies"  onclick="switchTriggerTab('policies')">&#128274; Policies</button>
        <button class="btn btn-xs btn-warning" id="tab-objtpl"    onclick="switchTriggerTab('objtpl')">&#128230; All Templates</button>
      </div>
    </h5>

    <!-- TEMPLATES tab -->
    <div id="tpanel-templates" class="tpanel">
      <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap" id="tpl-category-filters">
        <button class="btn btn-xs btn-default tcat active" onclick="filterTplCategory('all')" data-cat="all">All</button>
        <button class="btn btn-xs btn-default tcat" onclick="filterTplCategory('timestamps')" data-cat="timestamps">Timestamps</button>
        <button class="btn btn-xs btn-default tcat" onclick="filterTplCategory('audit')" data-cat="audit">Audit</button>
        <button class="btn btn-xs btn-default tcat" onclick="filterTplCategory('validation')" data-cat="validation">Validation</button>
        <button class="btn btn-xs btn-default tcat" onclick="filterTplCategory('search')" data-cat="search">Search</button>
        <button class="btn btn-xs btn-default tcat" onclick="filterTplCategory('security')" data-cat="security">Security</button>
        <button class="btn btn-xs btn-default tcat" onclick="filterTplCategory('workflow')" data-cat="workflow">Workflow</button>
        <button class="btn btn-xs btn-default tcat" onclick="filterTplCategory('finance')" data-cat="finance">Finance</button>
        <button class="btn btn-xs btn-default tcat" onclick="filterTplCategory('performance')" data-cat="performance">Performance</button>
      </div>
      <div id="tpl-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;max-height:50vh;overflow-y:auto">
        <div style="color:#7f8c8d;font-size:.85em">Loading templates…</div>
      </div>
    </div>

    <!-- LIVE TRIGGERS tab -->
    <div id="tpanel-live" class="tpanel" style="display:none">
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <input id="trigger-table-filter" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566;max-width:200px"
               placeholder="Filter by table…" oninput="loadLiveTriggers()">
        <button class="btn btn-xs btn-default" onclick="loadLiveTriggers()">&#8635; Refresh</button>
      </div>
      <div id="live-triggers-list" style="max-height:50vh;overflow-y:auto;font-size:.8em">
        <div style="color:#7f8c8d">Loading…</div>
      </div>
    </div>

    <!-- FUNCTIONS tab -->
    <div id="tpanel-functions" class="tpanel" style="display:none">
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <select id="fn-schema-filter" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566;max-width:150px" onchange="loadFunctions()">
          <option>public</option>
        </select>
        <button class="btn btn-xs btn-default" onclick="loadFunctions()">&#8635; Refresh</button>
      </div>
      <div id="functions-list" style="max-height:50vh;overflow-y:auto;font-size:.8em">
        <div style="color:#7f8c8d">Loading…</div>
      </div>
      <!-- Function source viewer -->
      <div id="fn-source-view" style="display:none;margin-top:10px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <b id="fn-source-name" style="font-size:.85em;color:#3498db"></b>
          <button class="btn btn-xs btn-danger" id="fn-drop-btn">Drop Function</button>
        </div>
        <pre id="fn-source-code" style="background:#0d1b2a;padding:10px;font-size:.72em;max-height:240px;overflow:auto;color:#00ff99;border-radius:4px"></pre>
      </div>
    </div>

    <!-- FUNCTION EDITOR tab -->
    <div id="tpanel-editor" class="tpanel" style="display:none">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:6px">
        <div>
          <label style="font-size:.75em;color:#7f8c8d">Function name</label>
          <input id="fn-edit-name" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566" placeholder="my_function">
        </div>
        <div>
          <label style="font-size:.75em;color:#7f8c8d">Schema</label>
          <input id="fn-edit-schema" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566" value="public">
        </div>
        <div>
          <label style="font-size:.75em;color:#7f8c8d">Arguments</label>
          <input id="fn-edit-args" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566" placeholder="p_id INTEGER">
        </div>
        <div>
          <label style="font-size:.75em;color:#7f8c8d">Returns</label>
          <input id="fn-edit-returns" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566" value="TRIGGER">
        </div>
      </div>
      <label style="font-size:.75em;color:#7f8c8d">Function body (PL/pgSQL)</label>
      <textarea id="fn-edit-body" style="width:100%;height:220px;background:#0d1b2a;color:#00ff99;border:1px solid #445566;border-radius:4px;padding:8px;font-family:monospace;font-size:.8em;resize:vertical"
        placeholder="BEGIN&#10;  -- your logic here&#10;  RETURN NEW;&#10;END;"></textarea>
      <div class="erd-modal-actions">
        <button class="btn btn-sm btn-default" onclick="clearFunctionEditor()">Clear</button>
        <button class="btn btn-sm btn-primary" onclick="submitCustomFunction()">&#10003; Create / Replace</button>
      </div>
    </div>

    <!-- DOMAINS tab -->
    <div id="tpanel-domains" class="tpanel" style="display:none">
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <select id="dom-schema" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566;max-width:150px" onchange="loadDomains()"><option>public</option></select>
        <button class="btn btn-xs btn-default" onclick="loadDomains()">&#8635;</button>
        <button class="btn btn-xs btn-info" onclick="switchTriggerTab('objtpl');filterObjType('domain')">+ New from template</button>
      </div>
      <div id="domains-list" style="max-height:46vh;overflow-y:auto;font-size:.8em"><div style="color:#7f8c8d">Loading…</div></div>
    </div>

    <!-- EVENT TRIGGERS tab -->
    <div id="tpanel-evtrig" class="tpanel" style="display:none">
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <button class="btn btn-xs btn-default" onclick="loadEventTriggers()">&#8635; Refresh</button>
        <button class="btn btn-xs btn-info" onclick="switchTriggerTab('objtpl');filterObjType('event_trigger')">+ New from template</button>
      </div>
      <div id="evtrig-list" style="max-height:46vh;overflow-y:auto;font-size:.8em"><div style="color:#7f8c8d">Loading…</div></div>
    </div>

    <!-- MATERIALIZED VIEWS tab -->
    <div id="tpanel-matviews" class="tpanel" style="display:none">
      <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap">
        <select id="mv-schema" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566;max-width:150px" onchange="loadMatViews()"><option>public</option></select>
        <button class="btn btn-xs btn-default" onclick="loadMatViews()">&#8635;</button>
        <button class="btn btn-xs btn-info" onclick="switchTriggerTab('objtpl');filterObjType('materialized_view')">+ New template</button>
        <button class="btn btn-xs btn-warning" onclick="showViewEditor(true)">&#9998; Custom</button>
      </div>
      <div id="matviews-list" style="max-height:40vh;overflow-y:auto;font-size:.8em"><div style="color:#7f8c8d">Loading…</div></div>
      <div id="matview-def" style="display:none;margin-top:8px">
        <b id="matview-def-name" style="font-size:.8em;color:#3498db"></b>
        <pre id="matview-def-sql" style="background:#0d1b2a;padding:8px;font-size:.72em;color:#00ff99;max-height:160px;overflow:auto;border-radius:4px"></pre>
      </div>
    </div>

    <!-- VIEWS tab -->
    <div id="tpanel-views" class="tpanel" style="display:none">
      <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap">
        <select id="view-schema" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566;max-width:150px" onchange="loadViews()"><option>public</option></select>
        <button class="btn btn-xs btn-default" onclick="loadViews()">&#8635;</button>
        <button class="btn btn-xs btn-info" onclick="switchTriggerTab('objtpl');filterObjType('view')">+ New template</button>
        <button class="btn btn-xs btn-warning" onclick="showViewEditor(false)">&#9998; Custom</button>
      </div>
      <div id="views-list" style="max-height:36vh;overflow-y:auto;font-size:.8em"><div style="color:#7f8c8d">Loading…</div></div>
      <!-- Inline view editor -->
      <div id="view-editor" style="display:none;margin-top:10px">
        <label style="font-size:.75em;color:#7f8c8d">View / Materialized View SQL query</label>
        <input id="view-edit-name" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566;margin-bottom:4px" placeholder="view_name">
        <textarea id="view-edit-sql" style="width:100%;height:140px;background:#0d1b2a;color:#00ff99;border:1px solid #445566;border-radius:4px;padding:8px;font-family:monospace;font-size:.78em;resize:vertical"
          placeholder="SELECT * FROM orders WHERE ..."></textarea>
        <div style="display:flex;gap:6px;margin-top:6px;align-items:center">
          <label style="font-size:.75em;color:#7f8c8d"><input type="checkbox" id="view-edit-mat"> Materialized</label>
          <button class="btn btn-xs btn-primary" onclick="submitCustomView()">&#10003; Create / Replace</button>
          <button class="btn btn-xs btn-default" onclick="document.getElementById('view-editor').style.display='none'">Cancel</button>
        </div>
      </div>
    </div>

    <!-- POLICIES tab -->
    <div id="tpanel-policies" class="tpanel" style="display:none">
      <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap">
        <input id="pol-table" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566;max-width:160px" placeholder="Table (optional)" oninput="loadPolicies()">
        <button class="btn btn-xs btn-default" onclick="loadPolicies()">&#8635;</button>
        <button class="btn btn-xs btn-info" onclick="switchTriggerTab('objtpl');filterObjType('policy')">+ New template</button>
        <button class="btn btn-xs btn-warning" onclick="document.getElementById('policy-editor').style.display=''">&#9998; Custom</button>
      </div>
      <div id="policies-list" style="max-height:30vh;overflow-y:auto;font-size:.8em"><div style="color:#7f8c8d">Loading…</div></div>
      <!-- Custom policy editor -->
      <div id="policy-editor" style="display:none;margin-top:10px;background:#0d1b2a;padding:10px;border-radius:6px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px">
          <div><label style="font-size:.72em;color:#7f8c8d">Table</label>
            <input id="pol-tbl" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566"></div>
          <div><label style="font-size:.72em;color:#7f8c8d">Policy name</label>
            <input id="pol-name" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566" value="my_policy"></div>
          <div><label style="font-size:.72em;color:#7f8c8d">Command</label>
            <select id="pol-cmd" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566">
              <option>ALL</option><option>SELECT</option><option>INSERT</option><option>UPDATE</option><option>DELETE</option>
            </select></div>
          <div><label style="font-size:.72em;color:#7f8c8d">USING expression</label>
            <input id="pol-using" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566" placeholder="tenant_id = current_tenant()"></div>
          <div style="grid-column:span 2"><label style="font-size:.72em;color:#7f8c8d">WITH CHECK (optional)</label>
            <input id="pol-check" class="form-control input-sm" style="background:#253545;color:#ecf0f1;border-color:#445566"></div>
        </div>
        <div style="display:flex;gap:6px">
          <button class="btn btn-xs btn-primary" onclick="submitCustomPolicy()">&#10003; Create Policy</button>
          <button class="btn btn-xs btn-default" onclick="document.getElementById('policy-editor').style.display='none'">Cancel</button>
        </div>
      </div>
    </div>

    <!-- ALL OBJECT TEMPLATES tab (domains + views + policies + event triggers) -->
    <div id="tpanel-objtpl" class="tpanel" style="display:none">
      <div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap" id="obj-type-filters">
        <button class="btn btn-xs btn-default obj-tcat active" onclick="filterObjType('all')" data-type="all">All</button>
        <button class="btn btn-xs btn-default obj-tcat" onclick="filterObjType('domain')" data-type="domain">Domains</button>
        <button class="btn btn-xs btn-default obj-tcat" onclick="filterObjType('event_trigger')" data-type="event_trigger">Event Triggers</button>
        <button class="btn btn-xs btn-default obj-tcat" onclick="filterObjType('materialized_view')" data-type="materialized_view">Mat.Views</button>
        <button class="btn btn-xs btn-default obj-tcat" onclick="filterObjType('view')" data-type="view">Views</button>
        <button class="btn btn-xs btn-default obj-tcat" onclick="filterObjType('policy')" data-type="policy">Policies</button>
      </div>
      <div id="obj-tpl-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px;max-height:46vh;overflow-y:auto">
        <div style="color:#7f8c8d">Loading…</div>
      </div>
    </div>

    <!-- Object template parameter form -->
    <div id="obj-tpl-params-form" style="display:none;margin-top:12px;padding:12px;background:#0d1b2a;border-radius:6px">
      <h6 id="obj-tpl-params-title" style="margin:0 0 8px;color:#e67e22"></h6>
      <p id="obj-tpl-params-desc" style="font-size:.8em;color:#7f8c8d;margin-bottom:8px"></p>
      <div id="obj-tpl-params-fields" style="display:grid;grid-template-columns:1fr 1fr;gap:8px"></div>
      <div style="margin-top:8px;font-size:.75em;color:#7f8c8d">
        <b>Preview SQL:</b>
        <pre id="obj-tpl-sql-preview" style="background:#111;padding:6px;font-size:.82em;color:#f0c040;max-height:120px;overflow:auto;border-radius:3px;margin:4px 0 0"></pre>
      </div>
      <div class="erd-modal-actions">
        <button class="btn btn-sm btn-default" onclick="document.getElementById('obj-tpl-params-form').style.display='none'">Cancel</button>
        <button class="btn btn-sm btn-warning" onclick="previewObjectTemplate()">Preview SQL</button>
        <button class="btn btn-sm btn-success" id="obj-tpl-apply-btn">&#9658; Apply to Database</button>
      </div>
    </div>

    <!-- Template parameter form (shown when a template is selected) -->
    <div id="tpl-params-form" style="display:none;margin-top:12px;padding:12px;background:#0d1b2a;border-radius:6px">
      <h6 id="tpl-params-title" style="margin:0 0 10px;color:#3498db"></h6>
      <p id="tpl-params-desc" style="font-size:.8em;color:#7f8c8d;margin-bottom:10px"></p>
      <div id="tpl-params-fields" style="display:grid;grid-template-columns:1fr 1fr;gap:8px"></div>
      <div style="margin-top:8px;font-size:.75em;color:#7f8c8d">
        <b>Preview SQL:</b>
        <pre id="tpl-sql-preview" style="background:#111;padding:6px;font-size:.85em;color:#00ff99;max-height:140px;overflow:auto;border-radius:3px;margin:4px 0 0"></pre>
      </div>
      <div class="erd-modal-actions">
        <button class="btn btn-sm btn-default" onclick="document.getElementById('tpl-params-form').style.display='none'">Cancel</button>
        <button class="btn btn-sm btn-warning" onclick="previewTriggerTemplate()">Preview SQL</button>
        <button class="btn btn-sm btn-success" id="tpl-apply-btn">&#9889; Apply to Database</button>
      </div>
    </div>

    <div class="erd-modal-actions" style="margin-top:8px">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('trigger-modal').style.display='none'">Close</button>
    </div>
  </div>
</div>
<!-- ─── end trigger modal ──────────────────────────────────────────── -->

<!-- Migration log modal -->
<div id="mig-log-modal" class="erd-modal">
  <div class="erd-modal-box" style="max-width:680px">
    <h5>&#128196; Migration Log</h5>
    <div id="mig-log-list" style="max-height:380px;overflow-y:auto;font-size:.8em">
      Loading…
    </div>
    <div class="erd-modal-actions">
      <button class="btn btn-sm btn-default" onclick="document.getElementById('mig-log-modal').style.display='none'">Close</button>
    </div>
  </div>
</div>

<script src="{{ url_for('static', filename='appbuilder/js/jquery-latest.js') }}"></script>
<!-- Dynamic config: API base, CSRF token, user context -->
<script>
window.ERD_CONFIG = {{ erd_config_json | tojson | safe }};
</script>
<script src="{{ url_for('static', filename='appbuilder/js/erd_designer.js') }}"></script>
<script>
/* ── Design load modal populate ── */
document.addEventListener('DOMContentLoaded', function() {
  var m = document.getElementById('design-load-modal');
  if (m) {
    m.addEventListener('show', function() { loadDesignList(); }, false);
  }
  // Populate when the modal is opened
  document.getElementById('design-load-modal').__origDisplay = 'none';
  var origShowFn = Object.getOwnPropertyDescriptor(CSSStyleDeclaration.prototype, 'display');
  // Simpler: load on first interaction via button click override
  var loadBtn = document.querySelector('[onclick*="design-load-modal"]');
  if (loadBtn) {
    var orig = loadBtn.getAttribute('onclick');
    loadBtn.setAttribute('onclick', orig + '; loadDesignList();');
  }
});

function loadDesignList() {
  var el = document.getElementById('design-list');
  if (!el) return;
  apiFetch('GET', '/api/designs').then(function(d) {
    var designs = d.designs || [];
    if (!designs.length) { el.innerHTML = '<div style="color:#7f8c8d">No saved designs.</div>'; return; }
    el.innerHTML = designs.map(function(ds) {
      return '<div style="padding:6px;border-bottom:1px solid #34495e;cursor:pointer" onclick="loadDesign(' + ds.id + ');document.getElementById(\'design-load-modal\').style.display=\'none\'">' +
        '<b>' + _esc(ds.name) + '</b>' +
        '<span style="color:#7f8c8d;font-size:.8em;margin-left:8px">' + _esc(ds.changed_on || '') + '</span>' +
        '</div>';
    }).join('');
  });
}

/* ── Migration log populate ── */
function loadMigrationLog() {
  var el = document.getElementById('mig-log-list');
  if (!el) return;
  apiFetch('GET', '/api/migration-log').then(function(d) {
    var entries = d.entries || [];
    if (!entries.length) { el.innerHTML = '<div style="color:#7f8c8d">No migrations yet.</div>'; return; }
    el.innerHTML = entries.map(function(e) {
      var statusColor = e.status === 'success' ? '#2ecc71' : '#e74c3c';
      return '<div style="padding:6px;border-bottom:1px solid #2c3e50">' +
        '<span style="color:' + statusColor + ';font-weight:700">' + _esc(e.status) + '</span> ' +
        '<span style="color:#7f8c8d">' + _esc(e.applied_at || '') + '</span>' +
        '<details><summary style="cursor:pointer;color:#7f8c8d;font-size:.8em">' +
        (e.sql || []).length + ' statements</summary>' +
        '<pre style="background:#111;padding:4px;font-size:.7em;color:#0f0;max-height:100px;overflow:auto">' +
        _esc((e.sql || []).join('\n')) + '</pre>' +
        (e.rollback_sql && e.rollback_sql.length ? '<button class="btn btn-xs btn-danger" onclick="rollbackMigration(' + e.id + ')">↩ Rollback</button>' : '') +
        '</details></div>';
    }).join('');
  }).catch(function(){ el.innerHTML = '<div style="color:#e74c3c">Admin access required.</div>'; });
}

var migLogModal = document.getElementById('mig-log-modal');
if (migLogModal) {
  migLogModal.addEventListener('transitionend', loadMigrationLog);
}
// Override migration log button to also load data
document.addEventListener('DOMContentLoaded', function() {
  var logBtn = document.querySelector('[onclick*="mig-log-modal"]');
  if (logBtn) logBtn.setAttribute('onclick', logBtn.getAttribute('onclick') + '; loadMigrationLog();');
});

function rollbackMigration(id) {
  if (!confirm('Roll back this migration? This will execute the inverse DDL.')) return;
  apiFetch('POST', '/api/migration-log/' + id + '/rollback').then(function(d) {
    setStatus(d.ok ? '↩ Rollback applied' : '✗ Rollback failed: ' + (d.error || ''));
    if (d.ok) refreshCanvas();
  });
}
</script>

</body>
</html>
""")
