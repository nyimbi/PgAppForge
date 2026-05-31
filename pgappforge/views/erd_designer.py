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
import pathlib
from flask import abort, current_app, request, jsonify, Response
from flask_login import current_user
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.widgets_postgresql._cdn import CYTOSCAPE_CDN as _CY


# ─── Security helpers ─────────────────────────────────────────────────────────

def _require_schema_admin() -> None:
	"""Abort 403 unless current user is Admin and FAB_ERD_DDL_ENABLED is True.

	Gate-keeps all mutating DDL endpoints so that:
	  - Production databases can disable the ERD DDL path entirely via config.
	  - Even with it enabled, only users with the Admin role can apply changes.
	"""
	if not current_app.config.get("FAB_ERD_DDL_ENABLED", False):
		abort(403, description=(
			"ERD schema mutations are disabled. "
			"Set FAB_ERD_DDL_ENABLED = True in your Flask config to enable."
		))
	if not current_user or not current_user.is_authenticated:
		abort(403, description="Login required.")
	if not any(
		getattr(r, "name", "") in ("Admin", "admin")
		for r in getattr(current_user, "roles", [])
	):
		abort(403, description="ERD schema mutations require the Admin role.")


def _validate_csrf() -> None:
	"""Validate CSRF token on JSON POST endpoints.

	Expects the ``X-CSRFToken`` request header (set by JS from the meta tag).
	Falls back gracefully if Flask-WTF CSRF is not configured.
	"""
	try:
		from flask_wtf.csrf import validate_csrf
		validate_csrf(request.headers.get("X-CSRFToken", ""))
	except ImportError:
		pass  # Flask-WTF not installed — skip CSRF check
	except Exception as exc:
		abort(400, description=f"CSRF validation failed: {exc}")


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
	if not str(candidate).startswith(str(root)):
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
		return self.render_template_string(_DESIGNER_HTML, domain_groups=domain_groups)

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
		return jsonify({"ok": True})

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


# ─── HTML Template ────────────────────────────────────────────────────────────

_DESIGNER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ERD Designer</title>
  <link rel="stylesheet"
    href="{{ url_for('static', filename='appbuilder/css/bootstrap.min.css') }}">
  """ + _CY + """
  <style>
    * { box-sizing: border-box; }
    body { margin:0; overflow:hidden; font-size:13px; }
    #layout { display:flex; height:100vh; }
    #sidebar { width:260px; min-width:220px; background:#2c3e50; color:#ecf0f1;
                overflow-y:auto; display:flex; flex-direction:column; }
    #sidebar-header { padding:12px; background:#1a252f; font-size:0.9em; font-weight:600; }
    #search-box { width:100%; padding:6px 10px; background:#34495e;
                  border:none; color:#ecf0f1; font-size:0.85em; outline:none; }
    #search-box::placeholder { color:#7f8c8d; }
    #module-list { flex:1; overflow-y:auto; }
    .mod-item { padding:8px 12px; cursor:pointer; border-bottom:1px solid #34495e;
                display:flex; align-items:center; gap:8px; }
    .mod-item:hover { background:#34495e; }
    .mod-dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
    .mod-label { flex:1; font-size:0.85em; }
    .mod-count { font-size:0.75em; color:#7f8c8d; }
    .domain-items { display:block; }
    .domain-items.collapsed { display:none; }
    .domain-header:hover { background:#243342 !important; }
    #toolbar { padding:8px 12px; background:#1a252f; border-top:1px solid #0d1b2a;
               display:flex; flex-direction:column; gap:6px; }
    #cy-wrap { flex:1; position:relative; background:#1a1a2e; }
    #cy { width:100%; height:100%; }
    #status-bar { position:absolute; bottom:0; left:0; right:0;
                  background:rgba(0,0,0,0.7); color:#aaa; padding:3px 8px;
                  font-size:0.75em; pointer-events:none; }
    #info-panel { position:absolute; top:8px; right:8px; background:rgba(0,0,0,0.8);
                  color:#ecf0f1; border-radius:6px; padding:10px 14px;
                  font-size:0.8em; max-width:260px; display:none;
                  max-height:300px; overflow-y:auto; }
    .btn-block { display:block; width:100%; margin-bottom:4px; text-align:left; }
    #context-menu { position:fixed; background:#2c3e50; border:1px solid #34495e;
                    border-radius:4px; z-index:9999; display:none; min-width:160px; }
    #context-menu .cm-item { padding:6px 14px; cursor:pointer; font-size:0.85em;
                              color:#ecf0f1; }
    #context-menu .cm-item:hover { background:#34495e; }
    #context-menu .cm-sep { border-top:1px solid #34495e; margin:2px 0; }
  </style>
</head>
<body>
<div id="layout">
  <!-- Left sidebar -->
  <div id="sidebar">
    <div id="sidebar-header">&#9673; ERD Designer</div>
    <input id="search-box" placeholder="Search tables..." oninput="filterModules(this.value)">
    <div style="padding:8px 12px;font-size:0.75em;color:#7f8c8d;border-bottom:1px solid #34495e">
      ERP TEMPLATES — click to add to canvas
    </div>
    <div id="module-list">
      {% for domain, items in domain_groups.items() %}
      <div class="domain-group">
        <div class="domain-header" onclick="toggleDomain(this)"
             style="padding:5px 12px;background:#1a252f;font-size:0.75em;
                    color:#7f8c8d;letter-spacing:0.05em;cursor:pointer;
                    display:flex;align-items:center;justify-content:space-between;
                    border-top:1px solid #0d1b2a;user-select:none">
          <span>{{ domain | upper }}</span>
          <span style="font-size:0.8em">{{ items|length }} ▾</span>
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
      <div style="font-size:0.75em;color:#7f8c8d;margin-bottom:4px">CANVAS</div>
      <button class="btn btn-xs btn-default btn-block" onclick="loadLiveSchema()">
        &#9654; Load live DB schema
      </button>
      <button class="btn btn-xs btn-default btn-block" onclick="cy.fit()">
        &#9636; Fit all
      </button>
      <button class="btn btn-xs btn-default btn-block" onclick="relayout()">
        &#8853; Re-layout
      </button>
      <button class="btn btn-xs btn-default btn-block" onclick="cy.elements().remove()">
        &#215; Clear canvas
      </button>
      <div style="font-size:0.75em;color:#7f8c8d;margin:8px 0 4px">EXPORT</div>
      <button class="btn btn-xs btn-default btn-block"
              onclick="window.open('/erd-designer/api/export/mermaid')">
        &#10515; Mermaid
      </button>
      <div style="font-size:0.75em;color:#7f8c8d;margin:8px 0 4px">GENERATE APP</div>
      <input id="gen-name" class="form-control input-sm" placeholder="App name" value="MyApp"
             style="margin-bottom:4px;background:#34495e;border-color:#4a6278;color:#ecf0f1">
      <button class="btn btn-xs btn-success btn-block" onclick="generateApp()">
        &#9654;&#9654; Generate App
      </button>
    </div>
  </div>

  <!-- Canvas -->
  <div id="cy-wrap">
    <div id="cy"></div>
    <div id="status-bar">
      Click a module in the sidebar to add it. Double-click a module group to fold/unfold.
      Right-click any node for options.
    </div>
    <div id="info-panel"></div>
  </div>
</div>

<!-- Context menu -->
<div id="context-menu">
  <div class="cm-item" id="cm-fold">&#9654; Fold module</div>
  <div class="cm-item" id="cm-remove">&#215; Remove</div>
  <div class="cm-sep"></div>
  <div class="cm-item" id="cm-fit-sel">&#9636; Fit to selection</div>
</div>

<script src="{{ url_for('static', filename='appbuilder/js/jquery-latest.js') }}"></script>
<script>
/* ── Cytoscape init ── */
var cy = cytoscape({
  container: document.getElementById('cy'),
  style: [
    { selector: 'node[type="module"]',
      style: { 'label': 'data(label)', 'text-halign': 'center', 'text-valign': 'top',
               'font-size': '13px', 'font-weight': 'bold', 'color': '#ecf0f1',
               'text-margin-y': -6,
               'background-color': 'data(color)', 'background-opacity': 0.15,
               'border-width': 2, 'border-color': 'data(color)',
               'padding': '14px', 'shape': 'round-rectangle' } },
    { selector: 'node[type="table"]',
      style: { 'label': 'data(label)', 'text-halign': 'center', 'text-valign': 'center',
               'font-size': '11px', 'color': '#ecf0f1',
               'background-color': '#2c3e50', 'border-width': 1.5,
               'border-color': 'data(color)', 'width': 110, 'height': 40,
               'shape': 'rectangle' } },
    { selector: 'node[type="table"]:selected',
      style: { 'background-color': '#34495e', 'border-width': 3 } },
    { selector: 'edge[type="fk"]',
      style: { 'curve-style': 'bezier', 'target-arrow-shape': 'triangle',
               'line-color': '#555', 'target-arrow-color': '#555',
               'width': 1.5, 'label': 'data(label)',
               'font-size': '9px', 'color': '#777', 'text-background-opacity': 0 } },
  ],
  layout: { name: 'cose', animate: false },
  wheelSensitivity: 0.2,
});

/* Collapsed module tracking */
var collapsed = {};

function _collapseModule(modId) {
  var children = cy.nodes('[parent="' + modId + '"]');
  if (collapsed[modId]) {
    children.style({ 'display': 'element' });
    cy.edges().style({ 'display': 'element' });
    collapsed[modId] = false;
  } else {
    children.style({ 'display': 'none' });
    cy.edges('[source][target]').forEach(function(e) {
      if (children.map(function(n){return n.id();}).indexOf(e.data('source')) >= 0 ||
          children.map(function(n){return n.id();}).indexOf(e.data('target')) >= 0) {
        e.style({ 'display': 'none' });
      }
    });
    collapsed[modId] = true;
  }
}

cy.on('dblclick', 'node[type="module"]', function(e) {
  _collapseModule(e.target.id());
});

/* XSS-safe HTML escape — used wherever user-controlled data enters innerHTML */
function _esc(s) {
  return String(s||'').replace(/[&<>"']/g, function(m) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];
  });
}

cy.on('tap', 'node[type="table"]', function(e) {
  var d = e.target.data();
  var cols = (d.columns || []).slice(0, 12).map(function(c) {
    var color = c.pk ? '#f39c12' : c.fk ? '#3498db' : '#aaa';
    return '<span style="color:' + color + '">' + _esc(c.name) +
           '</span> <small>' + _esc(c.type || '') + '</small>';
  }).join('<br>');
  document.getElementById('info-panel').innerHTML =
    '<b>' + _esc(d.label) + '</b><br><hr style="margin:4px 0">' + cols;
  document.getElementById('info-panel').style.display = 'block';
});

cy.on('tap', function(e) {
  if (e.target === cy) {
    document.getElementById('info-panel').style.display = 'none';
    hideContextMenu();
  }
});

/* ── Context menu ── */
var _ctxTarget = null;
cy.on('cxttap', 'node', function(e) {
  _ctxTarget = e.target;
  var cm = document.getElementById('context-menu');
  cm.style.display = 'block';
  cm.style.left = e.originalEvent.clientX + 'px';
  cm.style.top = e.originalEvent.clientY + 'px';
  document.getElementById('cm-fold').textContent =
    e.target.data('type') === 'module'
      ? (collapsed[e.target.id()] ? '&#9660; Unfold module' : '&#9654; Fold module')
      : '&#9654; Fold parent';
});

function hideContextMenu() { document.getElementById('context-menu').style.display='none'; }
document.getElementById('cm-fold').onclick = function() {
  if (_ctxTarget) {
    var mid = _ctxTarget.data('type') === 'module' ? _ctxTarget.id() : _ctxTarget.data('parent');
    if (mid) _collapseModule(mid);
  }
  hideContextMenu();
};
document.getElementById('cm-remove').onclick = function() {
  if (_ctxTarget) {
    if (_ctxTarget.data('type') === 'module') {
      var modId = _ctxTarget.id();
      cy.nodes('[parent="' + modId + '"]').remove();
      // Remove only edges connected to nodes in this module (not all edges)
      cy.edges().filter(function(e) {
        return e.source().data('parent') === modId ||
               e.target().data('parent') === modId;
      }).remove();
    }
    _ctxTarget.remove();
  }
  hideContextMenu();
};
document.getElementById('cm-fit-sel').onclick = function() {
  var sel = cy.$(':selected');
  if (sel.length) cy.fit(sel, 40);
  hideContextMenu();
};
document.addEventListener('click', hideContextMenu);

/* ── Status bar ── */
function setStatus(msg) { document.getElementById('status-bar').textContent = msg; }

/* ── Load ERP module onto canvas ── */
var _loadedModules = {};

function addModule(key) {
  setStatus('Loading ' + key + '…');
  fetch('/erd-designer/api/all-templates')
    .then(function(r){return r.json();})
    .then(function(d) {
      var filtered = d.elements.filter(function(el) {
        return el.data.id === 'mod_' + key
            || el.data.parent === 'mod_' + key
            || (el.data.source && el.data.target && (
               (cy.getElementById(el.data.source).length && cy.getElementById(el.data.target).length)
               || (!cy.getElementById(el.data.source).length && !cy.getElementById(el.data.target).length)
            ));
      });
      // Only add elements not already on canvas
      var toAdd = filtered.filter(function(el){ return !cy.getElementById(el.data.id).length; });
      cy.add(toAdd);
      relayout();
      _loadedModules[key] = true;
      setStatus('Added module: ' + key + ' | Nodes: ' + cy.nodes().length + ' | Edges: ' + cy.edges().length);
    });
}

/* ── Load live schema ── */
function loadLiveSchema() {
  setStatus('Loading live database schema…');
  fetch('/erd-designer/api/live-schema')
    .then(function(r){return r.json();})
    .then(function(d) {
      if (d.error) { setStatus('Error: ' + d.error); return; }
      var toAdd = (d.elements||[]).filter(function(el){ return !cy.getElementById(el.data.id).length; });
      cy.add(toAdd);
      relayout();
      setStatus('Live schema: ' + cy.nodes().length + ' nodes, ' + cy.edges().length + ' edges');
    });
}

/* ── Layout ── */
function relayout() {
  cy.layout({ name: 'cose', animate: true, animationDuration: 500,
               nodeRepulsion: 8000, idealEdgeLength: 80, edgeElasticity: 32 }).run();
}

/* ── Search/filter ── */
function toggleDomain(header) {
  var items = header.nextElementSibling;
  items.classList.toggle('collapsed');
  var arrow = header.querySelector('span:last-child');
  if (arrow) arrow.textContent = items.classList.contains('collapsed') ? '▸' : '▾';
}

function filterModules(q) {
  var lq = q.toLowerCase();
  document.querySelectorAll('.mod-item').forEach(function(el) {
    var match = (el.dataset.label || '').toLowerCase().includes(lq)
             || (el.dataset.domain || '').toLowerCase().includes(lq);
    el.style.display = match ? '' : 'none';
  });
  // Show domain groups that have visible items
  document.querySelectorAll('.domain-group').forEach(function(g) {
    var visible = g.querySelectorAll('.mod-item:not([style*="none"])').length;
    g.style.display = visible > 0 ? '' : 'none';
    if (q && visible > 0) g.querySelector('.domain-items').classList.remove('collapsed');
  });
}

/* ── Generate app ── */
function generateApp() {
  var name = document.getElementById('gen-name').value.trim() || 'GeneratedApp';
  setStatus('Generating app…');
  fetch('/erd-designer/api/generate-app', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({app_name: name, output_dir: '/tmp/' + name.toLowerCase()})
  }).then(function(r){return r.json();}).then(function(d) {
    setStatus((d.status === 'success')
      ? '✓ App generated: ' + d.files_generated + ' files → ' + d.output_dir
      : '✗ ' + d.error);
  });
}
</script>
</body>
</html>
"""
