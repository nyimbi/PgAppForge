"""
Standard analytics cubes — seeded on AnalyticsEnginePlugin.post_initialize().
These cubes use PostgreSQL materialized views so all queries hit pre-aggregated data.
"""

from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger(__name__)

STANDARD_CUBES = [
	{
		"name": "gl_monthly_pnl",
		"description": "Monthly P&L by account class (Revenue/Expense) and dimension",
		"base_query": (
			"SELECT "
			"  date_trunc('month', je.posting_date) AS month, "
			"  ac.account_class, "
			"  ac.account_name, "
			"  ac.account_code, "
			"  je.tenant_id, "
			"  SUM(CASE WHEN je.entry_type='CREDIT' THEN je.amount_cents ELSE -je.amount_cents END) AS net_cents "
			"FROM erp_journal_entry je "
			"JOIN erp_account_code ac ON ac.code = je.account_code "
			"WHERE je.is_posted = true "
			"GROUP BY 1,2,3,4,5"
		),
		"dimensions": {"month": "date", "account_class": "string", "account_name": "string", "tenant_id": "string"},
		"measures": {"net_cents": "sum"},
		"refresh_schedule": "DAILY",
	},
	{
		"name": "ar_aging_summary",
		"description": "AR aging buckets: Current, 30d, 60d, 90d, 90d+",
		"base_query": (
			"SELECT "
			"  tenant_id, "
			"  customer_id, "
			"  CASE "
			"    WHEN days_overdue <= 0 THEN 'CURRENT' "
			"    WHEN days_overdue <= 30 THEN '1_30_DAYS' "
			"    WHEN days_overdue <= 60 THEN '31_60_DAYS' "
			"    WHEN days_overdue <= 90 THEN '61_90_DAYS' "
			"    ELSE 'OVER_90_DAYS' "
			"  END AS aging_bucket, "
			"  COUNT(*) AS invoice_count, "
			"  SUM(outstanding_amount_cents) AS outstanding_cents "
			"FROM erp_ar_invoice "
			"WHERE status IN ('OPEN','OVERDUE') "
			"GROUP BY 1,2,3"
		),
		"dimensions": {"tenant_id": "string", "customer_id": "string", "aging_bucket": "string"},
		"measures": {"invoice_count": "count", "outstanding_cents": "sum"},
		"refresh_schedule": "DAILY",
	},
	{
		"name": "hcm_headcount",
		"description": "Active headcount by department, entity, and employment type",
		"base_query": (
			"SELECT "
			"  e.tenant_id, "
			"  e.department_id, "
			"  e.entity_id, "
			"  e.employment_type, "
			"  e.gender, "
			"  COUNT(*) AS headcount, "
			"  SUM(COALESCE(c.annual_salary_cents, 0)) AS total_salary_cents "
			"FROM hcm_employee e "
			"LEFT JOIN hcm_compensation c ON c.employee_id = e.id AND c.is_current = true "
			"WHERE e.status = 'ACTIVE' "
			"GROUP BY 1,2,3,4,5"
		),
		"dimensions": {"tenant_id": "string", "department_id": "string", "entity_id": "string", "employment_type": "string", "gender": "string"},
		"measures": {"headcount": "count", "total_salary_cents": "sum"},
		"refresh_schedule": "DAILY",
	},
	{
		"name": "inventory_turnover",
		"description": "Inventory turnover: on-hand quantity, value, and movement by SKU",
		"base_query": (
			"SELECT "
			"  tenant_id, "
			"  product_id, "
			"  warehouse_id, "
			"  date_trunc('month', transaction_date) AS month, "
			"  SUM(CASE WHEN transaction_type IN ('RECEIPT','TRANSFER_IN') THEN quantity ELSE 0 END) AS receipts, "
			"  SUM(CASE WHEN transaction_type IN ('ISSUE','TRANSFER_OUT','SALE') THEN quantity ELSE 0 END) AS issues, "
			"  SUM(quantity_on_hand_after * unit_cost_cents) AS closing_value_cents "
			"FROM inv_stock_transaction "
			"GROUP BY 1,2,3,4"
		),
		"dimensions": {"tenant_id": "string", "product_id": "string", "warehouse_id": "string", "month": "date"},
		"measures": {"receipts": "sum", "issues": "sum", "closing_value_cents": "sum"},
		"refresh_schedule": "DAILY",
	},
	{
		"name": "sales_pipeline",
		"description": "CRM sales pipeline by stage, owner, and value",
		"base_query": (
			"SELECT "
			"  tenant_id, "
			"  stage, "
			"  assigned_to AS owner_id, "
			"  date_trunc('month', expected_close_date) AS expected_close_month, "
			"  COUNT(*) AS opportunity_count, "
			"  SUM(amount_cents) AS pipeline_value_cents, "
			"  SUM(amount_cents * probability_pct / 100) AS weighted_value_cents "
			"FROM crm_opportunity "
			"WHERE status NOT IN ('CLOSED_LOST','CANCELLED') "
			"GROUP BY 1,2,3,4"
		),
		"dimensions": {"tenant_id": "string", "stage": "string", "owner_id": "string", "expected_close_month": "date"},
		"measures": {"opportunity_count": "count", "pipeline_value_cents": "sum", "weighted_value_cents": "sum"},
		"refresh_schedule": "DAILY",
	},
]


def seed_standard_cubes(tenant_id: str, session: Any) -> int:
	"""Seed the 5 standard analytics cubes. Idempotent — skips existing cubes."""
	try:
		from pgappforge.plugins.erp.platform.analytics_engine.services import AnalyticsEngineService
		from pgappforge.plugins.erp.platform.analytics_engine.models import AnalyticsCube
		from sqlalchemy import select
		svc = AnalyticsEngineService()
		seeded = 0
		for cube_def in STANDARD_CUBES:
			existing = session.execute(
				select(AnalyticsCube).where(
					AnalyticsCube.tenant_id == tenant_id,
					AnalyticsCube.name == cube_def["name"],
				)
			).scalar_one_or_none()
			if existing:
				continue
			try:
				svc.define_cube(
					name=cube_def["name"],
					base_query=cube_def["base_query"],
					dimensions=cube_def["dimensions"],
					measures=cube_def["measures"],
					tenant_id=tenant_id,
					session=session,
					refresh_schedule=cube_def.get("refresh_schedule", "DAILY"),
				)
				seeded += 1
				log.info("analytics_engine: seeded cube %r for tenant %s", cube_def["name"], tenant_id)
			except Exception as exc:
				log.debug("Cube %r seed failed (non-fatal — base tables may not exist yet): %s", cube_def["name"], exc)
		return seeded
	except Exception as exc:
		log.debug("seed_standard_cubes failed: %s", exc)
		return 0


__all__ = ["STANDARD_CUBES", "seed_standard_cubes"]
