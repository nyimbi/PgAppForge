"""Spend analytics service — mine AP data directly."""
from __future__ import annotations
from decimal import Decimal
from typing import Any

import sqlalchemy as sa


class SpendAnalyticsService:
	def compute_spend_cube(
		self,
		tenant_id: str,
		from_period: str,
		to_period: str,
		session: Any,
	) -> dict[str, Any]:
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice
		except ImportError as exc:
			raise ImportError("spend_analytics requires the 'ap' plugin") from exc
		try:
			rows = session.execute(
				sa.select(APInvoice).where(
					APInvoice.tenant_id == tenant_id,
					APInvoice.invoice_date >= from_period,
					APInvoice.invoice_date <= to_period,
				)
			).scalars().all()
		except Exception as exc:
			raise RuntimeError(f"spend_cube query failed for tenant {tenant_id}") from exc
		total = sum(getattr(r, "total_amount_cents", 0) for r in rows)
		by_supplier: dict[str, int] = {}
		for r in rows:
			sid = str(getattr(r, "vendor_id", "unknown"))
			by_supplier[sid] = by_supplier.get(sid, 0) + getattr(r, "total_amount_cents", 0)
		return {
			"tenant_id": tenant_id,
			"from_period": from_period,
			"to_period": to_period,
			"total_spent_cents": total,
			"by_supplier": by_supplier,
			"invoice_count": len(rows),
		}

	def get_tail_spend(
		self,
		tenant_id: str,
		threshold_pct: float,
		from_period: str,
		to_period: str,
		session: Any,
	) -> dict[str, Any]:
		cube = self.compute_spend_cube(tenant_id, from_period, to_period, session)
		total = cube["total_spent_cents"]
		if total == 0:
			return {"tail_suppliers": [], "tail_spend_cents": 0, "tail_pct": 0}
		threshold = Decimal(str(total)) * Decimal(str(threshold_pct)) / 100
		tail = {sid: amt for sid, amt in cube["by_supplier"].items() if amt < int(threshold)}
		tail_total = sum(tail.values())
		return {
			"tail_suppliers": list(tail.keys()),
			"tail_count": len(tail),
			"tail_spend_cents": tail_total,
			"tail_pct": round(tail_total / total * 100, 2) if total else 0,
			"consolidation_opportunity": tail_total,
		}

	def get_category_breakdown(self, tenant_id: str, session: Any) -> dict[str, int]:
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice
			rows = session.execute(
				sa.select(APInvoice).where(APInvoice.tenant_id == tenant_id)
			).scalars().all()
			by_cat: dict[str, int] = {}
			for r in rows:
				cat = str(getattr(r, "expense_category", "UNCATEGORIZED") or "UNCATEGORIZED")
				by_cat[cat] = by_cat.get(cat, 0) + getattr(r, "total_amount_cents", 0)
			return by_cat
		except Exception:
			return {}


__all__ = ["SpendAnalyticsService"]
