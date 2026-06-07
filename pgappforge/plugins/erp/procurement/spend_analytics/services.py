"""
pgappforge/plugins/erp/procurement/spend_analytics/services.py

SpendAnalyticsService — spend cube computation, tail-spend analysis,
and savings opportunity identification.

Data sourced from APInvoice (finance.ap) and HSCodeMapping (trade_compliance)
for category grouping. All monetary values in integer cents.

BPM actions:
  procurement.spend.compute_cube — Compute procurement spend analytics cube
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("SpendAnalyticsService: emit suppressed: %s", exc)


# ---------------------------------------------------------------------------
# SpendAnalyticsService
# ---------------------------------------------------------------------------

class SpendAnalyticsService:
	"""Stateless spend analytics service."""

	# ------------------------------------------------------------------
	# compute_spend_cube
	# ------------------------------------------------------------------

	def compute_spend_cube(
		self,
		tenant_id: str,
		from_period: str,
		to_period: str,
		session: Any,
	) -> dict[str, Any]:
		"""Aggregate AP invoices into a spend cube for the given period range.

		period format: "YYYY-MM" (e.g. "2024-01").
		Returns top-20 suppliers by spend, plus totals and supplier count.
		Emits SpendCubeComputedEvent.
		"""
		from pgappforge.plugins.erp.procurement.spend_analytics.events import SpendCubeComputedEvent

		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice

			from_year, from_month = int(from_period[:4]), int(from_period[5:7])
			to_year, to_month = int(to_period[:4]), int(to_period[5:7])
			from_date = date(from_year, from_month, 1)
			# End of to_period: first day of next month
			if to_month == 12:
				to_date = date(to_year + 1, 1, 1)
			else:
				to_date = date(to_year, to_month + 1, 1)

			rows = session.execute(
				sa.select(
					APInvoice.supplier_id,
					sa.func.sum(APInvoice.total_cents).label("total"),
					sa.func.count().label("cnt"),
				).where(
					APInvoice.tenant_id == tenant_id,
					APInvoice.invoice_date >= from_date,
					APInvoice.invoice_date < to_date,
				).group_by(APInvoice.supplier_id)
			).all()

		except Exception as exc:
			log.warning("compute_spend_cube: AP query failed: %s", exc)
			rows = []

		total = sum(r.total or 0 for r in rows)
		supplier_count = len(rows)
		by_supplier = [
			{
				"supplier_id": r.supplier_id,
				"amount_cents": r.total or 0,
				"invoice_count": r.cnt,
			}
			for r in sorted(rows, key=lambda x: -(x.total or 0))[:20]
		]

		_emit(
			SpendCubeComputedEvent(
				aggregate_id=tenant_id,
				aggregate_type="Tenant",
				tenant_id=tenant_id,
				period=f"{from_period} to {to_period}",
				total_cents=total,
				supplier_count=supplier_count,
			),
			session,
		)

		return {
			"total_spent_cents": total,
			"supplier_count": supplier_count,
			"by_supplier": by_supplier,
			"period_range": f"{from_period} to {to_period}",
		}

	# ------------------------------------------------------------------
	# get_tail_spend
	# ------------------------------------------------------------------

	def get_tail_spend(
		self,
		tenant_id: str,
		threshold_pct: float,
		period: str,
		session: Any,
	) -> dict[str, Any]:
		"""Identify tail-spend suppliers below threshold_pct of total spend.

		threshold_pct: e.g. 2.0 means suppliers each below 2% of total spend.
		Returns consolidation opportunity metrics + supplier list.
		"""
		cube = self.compute_spend_cube(tenant_id, period, period, session)
		threshold_cents = cube["total_spent_cents"] * threshold_pct / 100
		all_suppliers = cube["by_supplier"]
		tail = [s for s in all_suppliers if s["amount_cents"] < threshold_cents]

		return {
			"tail_suppliers": len(tail),
			"tail_spend_cents": sum(s["amount_cents"] for s in tail),
			"consolidation_opportunity_pct": (
				Decimal(str(len(tail)))
				/ Decimal(str(max(1, len(all_suppliers))))
				* Decimal("100")
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
			"suppliers": tail,
		}

	# ------------------------------------------------------------------
	# get_savings_opportunities
	# ------------------------------------------------------------------

	def get_savings_opportunities(
		self,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Identify suppliers priced >20% above category peers.

		Method:
		1. Pull AP invoices with >=3 invoices per supplier.
		2. Attempt category lookup via HSCodeMapping if supplier_product_code available.
		3. Compute avg unit price per category across suppliers.
		4. Flag any supplier whose avg is >20% above category average.
		5. Emit SavingsOpportunityIdentifiedEvent per finding.

		Returns list of {supplier_id, category, current_avg_cents,
		market_avg_cents, potential_savings_pct}.
		"""
		from pgappforge.plugins.erp.procurement.spend_analytics.events import (
			SavingsOpportunityIdentifiedEvent,
		)

		opportunities: list[dict[str, Any]] = []

		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice

			rows = session.execute(
				sa.select(
					APInvoice.supplier_id,
					sa.func.sum(APInvoice.total_cents).label("total"),
					sa.func.count().label("cnt"),
					sa.func.avg(APInvoice.total_cents).label("avg_inv"),
				).where(
					APInvoice.tenant_id == tenant_id,
				).group_by(APInvoice.supplier_id)
				.having(sa.func.count() >= 3)
			).all()

		except Exception as exc:
			log.warning("get_savings_opportunities: AP query failed: %s", exc)
			rows = []

		if not rows:
			return opportunities

		# Build category map: try to get category from HS codes
		# Fallback: group all suppliers into "UNCATEGORIZED"
		supplier_avgs: dict[str, dict[str, Any]] = {}
		for r in rows:
			supplier_avgs[r.supplier_id] = {
				"avg_inv_cents": int(r.avg_inv or 0),
				"total_cents": int(r.total or 0),
				"invoice_count": r.cnt,
				"category": "UNCATEGORIZED",
			}

		# Attempt category enrichment via HS code mappings
		try:
			from pgappforge.plugins.erp.procurement.trade_compliance.models import HSCodeMapping

			hs_rows = session.execute(
				sa.select(
					HSCodeMapping.product_code,
					HSCodeMapping.hs_code,
					HSCodeMapping.description,
				).where(HSCodeMapping.tenant_id == tenant_id)
			).all()

			# Build hs_code -> category label from first 4 digits (HS chapter)
			hs_categories: dict[str, str] = {
				r.product_code: f"HS-{r.hs_code[:4]}"
				for r in hs_rows
				if r.hs_code
			}
		except Exception:
			hs_categories = {}

		# Group by category
		category_groups: dict[str, list[int]] = {}
		for supplier_id, data in supplier_avgs.items():
			cat = hs_categories.get(supplier_id, "UNCATEGORIZED")
			data["category"] = cat
			category_groups.setdefault(cat, []).append(data["avg_inv_cents"])

		# Compute category averages
		cat_avg: dict[str, Decimal] = {
			cat: Decimal(str(sum(vals))) / Decimal(str(len(vals)))
			for cat, vals in category_groups.items()
			if vals
		}

		# Flag outliers: suppliers >20% above category avg
		for supplier_id, data in supplier_avgs.items():
			cat = data["category"]
			market_avg = cat_avg.get(cat, Decimal("0"))
			if market_avg <= 0:
				continue
			current = Decimal(str(data["avg_inv_cents"]))
			if current > market_avg * Decimal("1.20"):
				savings_pct = (
					(current - market_avg) / market_avg * Decimal("100")
				).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
				potential_savings_cents = int(
					(current - market_avg)
					* Decimal(str(data["invoice_count"]))
				)
				opp = {
					"supplier_id": supplier_id,
					"category": cat,
					"current_avg_cents": int(current),
					"market_avg_cents": int(market_avg),
					"potential_savings_pct": float(savings_pct),
					"potential_savings_cents": potential_savings_cents,
				}
				opportunities.append(opp)
				_emit(
					SavingsOpportunityIdentifiedEvent(
						aggregate_id=supplier_id,
						aggregate_type="Supplier",
						tenant_id=tenant_id,
						supplier_id=supplier_id,
						potential_savings_cents=potential_savings_cents,
						reason=f"Price {savings_pct}% above {cat} category average",
					),
					session,
				)

		return sorted(opportunities, key=lambda x: -x["potential_savings_cents"])


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"procurement.spend.compute_cube",
	"Compute procurement spend analytics cube",
)
def _bpm_compute_cube(
	record_ctx: dict,
	session: Any,
	from_period: str = "",
	to_period: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.procurement.spend_analytics.services import (
			SpendAnalyticsService,
		)
	except ImportError:
		return {"status": "error", "message": "spend_analytics plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		result = SpendAnalyticsService().compute_spend_cube(
			tenant_id=tenant_id,
			from_period=from_period,
			to_period=to_period,
			session=session,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm procurement.spend.compute_cube failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = ["SpendAnalyticsService"]
