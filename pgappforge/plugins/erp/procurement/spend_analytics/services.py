"""Spend analytics service — mine AP data directly."""
from __future__ import annotations
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa


def _dec(value: Any) -> Decimal:
	return Decimal(str(value))


def current_tenant_id() -> str | None:
	try:
		from pgappforge.multitenancy.middleware import get_current_tenant_id
		tenant_id = get_current_tenant_id()
	except Exception:
		tenant_id = None
	return str(tenant_id) if tenant_id else None


def _tenant_id(explicit_tenant_id: str | None = None) -> str:
	tenant_id = current_tenant_id()
	if tenant_id:
		if explicit_tenant_id and str(explicit_tenant_id) != tenant_id:
			raise ValueError("tenant_id does not match current tenant")
		return tenant_id
	if explicit_tenant_id:
		return str(explicit_tenant_id)
	raise ValueError("Tenant context required")


def _pct(numerator: int, denominator: int) -> Decimal:
	if denominator <= 0:
		return Decimal("0")
	return (_dec(numerator) / _dec(denominator) * Decimal("100")).quantize(
		Decimal("0.01"), rounding=ROUND_HALF_UP
	)


def _column(model: Any, *names: str) -> Any | None:
	for name in names:
		if hasattr(model, name):
			return getattr(model, name)
	return None


def _median(values: list[int]) -> int:
	if not values:
		return 0
	ordered = sorted(values)
	mid = len(ordered) // 2
	if len(ordered) % 2:
		return ordered[mid]
	return int((_dec(ordered[mid - 1]) + _dec(ordered[mid])) / Decimal("2"))


class SpendAnalyticsService:
	def compute_spend_cube(
		self,
		tenant_id: str,
		from_period: str,
		to_period: str,
		session: Any,
	) -> dict[str, Any]:
		tenant_id = _tenant_id(tenant_id)
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice
		except ImportError as exc:
			raise ImportError("spend_analytics requires the 'ap' plugin") from exc
		total_column = _column(APInvoice, "total_amount_cents", "total_cents")
		supplier_column = _column(APInvoice, "vendor_id", "supplier_id")
		if total_column is None or supplier_column is None:
			return {
				"tenant_id": tenant_id,
				"from_period": from_period,
				"to_period": to_period,
				"total_spent_cents": 0,
				"by_supplier": {},
				"invoice_count": 0,
			}
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
		total = sum(int(getattr(r, "total_amount_cents", getattr(r, "total_cents", 0)) or 0) for r in rows)
		by_supplier: dict[str, int] = {}
		for r in rows:
			sid = str(getattr(r, "vendor_id", getattr(r, "supplier_id", "unknown")))
			by_supplier[sid] = by_supplier.get(sid, 0) + int(
				getattr(r, "total_amount_cents", getattr(r, "total_cents", 0)) or 0
			)
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
		threshold_pct: Decimal | int | str,
		from_period: str,
		to_period: str,
		session: Any,
	) -> dict[str, Any]:
		cube = self.compute_spend_cube(tenant_id, from_period, to_period, session)
		total = cube["total_spent_cents"]
		if total == 0:
			return {"tail_suppliers": [], "tail_spend_cents": 0, "tail_pct": Decimal("0")}
		threshold = _dec(total) * _dec(threshold_pct) / Decimal("100")
		tail = {sid: amt for sid, amt in cube["by_supplier"].items() if amt < int(threshold)}
		tail_total = sum(tail.values())
		return {
			"tail_suppliers": list(tail.keys()),
			"tail_count": len(tail),
			"tail_spend_cents": tail_total,
			"tail_pct": _pct(tail_total, total),
			"consolidation_opportunity": tail_total,
		}

	def get_category_breakdown(self, tenant_id: str, session: Any) -> dict[str, int]:
		tenant_id = _tenant_id(tenant_id)
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice
			rows = session.execute(
				sa.select(APInvoice).where(APInvoice.tenant_id == tenant_id)
			).scalars().all()
			by_cat: dict[str, int] = {}
			for r in rows:
				cat = str(getattr(r, "expense_category", "UNCATEGORIZED") or "UNCATEGORIZED")
				by_cat[cat] = by_cat.get(cat, 0) + int(
					getattr(r, "total_amount_cents", getattr(r, "total_cents", 0)) or 0
				)
			return by_cat
		except Exception:
			return {}

	def get_savings_opportunities(self, tenant_id: str, session: Any) -> list[dict[str, Any]]:
		"""Find suppliers with repeated invoice-line prices above category median."""
		tenant_id = _tenant_id(tenant_id)
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice, APInvoiceLine, APSupplier
		except ImportError:
			# TODO: wire procurement spend opportunities to the active invoice model when AP is absent.
			return []

		unit_column = _column(APInvoiceLine, "unit_price_cents", "unit_cost_cents")
		category_column = _column(APInvoiceLine, "expense_category", "gl_expense_account")
		if unit_column is None or category_column is None:
			# TODO: AP invoice lines need unit price and category fields for opportunity mining.
			return []

		cutoff = date.today() - timedelta(days=365)
		rows = session.execute(
			sa.select(
				APInvoice.supplier_id,
				APSupplier.name,
				category_column,
				unit_column,
				APInvoice.id,
			)
			.join(APInvoiceLine, APInvoiceLine.invoice_id == APInvoice.id)
			.join(APSupplier, APSupplier.id == APInvoice.supplier_id)
			.where(
				APInvoice.tenant_id == tenant_id,
				APInvoiceLine.tenant_id == tenant_id,
				APSupplier.tenant_id == tenant_id,
				APInvoice.invoice_date >= cutoff,
				unit_column.is_not(None),
			)
		).all()

		category_prices: dict[str, list[int]] = {}
		supplier_category: dict[tuple[str, str], dict[str, Any]] = {}
		for supplier_id, supplier_name, category, unit_cents, invoice_id in rows:
			cat = str(category or "UNCATEGORIZED")
			price = int(unit_cents or 0)
			if price <= 0:
				continue
			category_prices.setdefault(cat, []).append(price)
			key = (str(supplier_id), cat)
			bucket = supplier_category.setdefault(
				key,
				{
					"supplier_id": str(supplier_id),
					"supplier_name": supplier_name,
					"category": cat,
					"prices": [],
					"invoice_ids": set(),
				},
			)
			bucket["prices"].append(price)
			bucket["invoice_ids"].add(str(invoice_id))

		median_by_category = {
			category: _median(prices)
			for category, prices in category_prices.items()
		}

		results: list[dict[str, Any]] = []
		for bucket in supplier_category.values():
			invoice_count = len(bucket["invoice_ids"])
			if invoice_count < 3:
				continue
			avg_price = int(_dec(sum(bucket["prices"])) / _dec(len(bucket["prices"])))
			median_price = median_by_category.get(bucket["category"], 0)
			if median_price <= 0:
				continue
			opportunity_pct = _pct(avg_price - median_price, median_price)
			if opportunity_pct <= Decimal("10"):
				continue
			results.append({
				"supplier_id": bucket["supplier_id"],
				"supplier_name": bucket["supplier_name"],
				"category": bucket["category"],
				"avg_price_cents": avg_price,
				"median_price_cents": median_price,
				"opportunity_pct": opportunity_pct,
				"invoice_count": invoice_count,
			})

		return sorted(results, key=lambda row: row["opportunity_pct"], reverse=True)

	def get_maverick_spend(self, tenant_id: str, session: Any) -> dict[str, Any]:
		"""Report spend from AP suppliers that have no Supplier Portal profile."""
		tenant_id = _tenant_id(tenant_id)
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice, APInvoiceLine, APSupplier
			from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile
		except ImportError:
			return {
				"total_maverick_cents": 0,
				"maverick_pct_of_total": Decimal("0"),
				"maverick_suppliers": [],
				"top_10_offending_departments": [],
			}

		total_column = _column(APInvoice, "total_amount_cents", "total_cents")
		if total_column is None:
			return {
				"total_maverick_cents": 0,
				"maverick_pct_of_total": Decimal("0"),
				"maverick_suppliers": [],
				"top_10_offending_departments": [],
			}

		portal_exists = sa.exists().where(
			SupplierProfile.tenant_id == tenant_id,
			SupplierProfile.tenant_id == APInvoice.tenant_id,
			sa.or_(
				SupplierProfile.id == APInvoice.supplier_id,
				sa.and_(
					APSupplier.account_number.is_not(None),
					APSupplier.account_number != "",
					SupplierProfile.supplier_ref == APSupplier.account_number,
				),
				sa.and_(
					APSupplier.tax_id.is_not(None),
					APSupplier.tax_id != "",
					SupplierProfile.tax_id == APSupplier.tax_id,
				),
				sa.and_(
					APSupplier.contact_email.is_not(None),
					APSupplier.contact_email != "",
					SupplierProfile.contact_email == APSupplier.contact_email,
				),
			),
		)

		total_spend = int(session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(total_column), 0)).where(
				APInvoice.tenant_id == tenant_id,
			)
		).scalar() or 0)
		maverick_total = int(session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(total_column), 0))
			.join(APSupplier, APSupplier.id == APInvoice.supplier_id)
			.where(
				APInvoice.tenant_id == tenant_id,
				APSupplier.tenant_id == tenant_id,
				~portal_exists,
			)
		).scalar() or 0)
		supplier_rows = session.execute(
			sa.select(
				APInvoice.supplier_id,
				APSupplier.name,
				sa.func.coalesce(sa.func.sum(total_column), 0),
			)
			.join(APSupplier, APSupplier.id == APInvoice.supplier_id)
			.where(
				APInvoice.tenant_id == tenant_id,
				APSupplier.tenant_id == tenant_id,
				~portal_exists,
			)
			.group_by(APInvoice.supplier_id, APSupplier.name)
			.order_by(sa.desc(sa.func.coalesce(sa.func.sum(total_column), 0)))
			.limit(10)
		).all()

		department_rows = []
		if hasattr(APInvoiceLine, "cost_center"):
			department_rows = session.execute(
				sa.select(
					APInvoiceLine.cost_center,
					sa.func.coalesce(sa.func.sum(APInvoiceLine.line_amount_cents), 0),
				)
				.join(APInvoice, APInvoice.id == APInvoiceLine.invoice_id)
				.join(APSupplier, APSupplier.id == APInvoice.supplier_id)
				.where(
					APInvoice.tenant_id == tenant_id,
					APInvoiceLine.tenant_id == tenant_id,
					APSupplier.tenant_id == tenant_id,
					~portal_exists,
				)
				.group_by(APInvoiceLine.cost_center)
				.order_by(sa.desc(sa.func.coalesce(sa.func.sum(APInvoiceLine.line_amount_cents), 0)))
				.limit(10)
			).all()

		return {
			"total_maverick_cents": maverick_total,
			"maverick_pct_of_total": _pct(maverick_total, total_spend),
			"maverick_suppliers": [
				{
					"supplier_id": str(supplier_id),
					"supplier_name": supplier_name,
					"maverick_spend_cents": int(amount or 0),
				}
				for supplier_id, supplier_name, amount in supplier_rows
			],
			"top_10_offending_departments": [
				{
					"department": department or "UNASSIGNED",
					"maverick_spend_cents": int(amount or 0),
				}
				for department, amount in department_rows
			],
		}

	def benchmark_category(self, tenant_id: str, category: str, session: Any) -> dict[str, Any]:
		"""Benchmark unit prices for a category using PostgreSQL percentile_cont."""
		tenant_id = _tenant_id(tenant_id)
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice, APInvoiceLine
		except ImportError:
			return {
				"category": category,
				"our_avg_price_cents": 0,
				"supplier_count": 0,
				"price_range": {"min_cents": 0, "max_cents": 0, "p25_cents": 0, "p75_cents": 0},
			}

		unit_column = _column(APInvoiceLine, "unit_price_cents", "unit_cost_cents")
		category_column = _column(APInvoiceLine, "expense_category", "gl_expense_account")
		if unit_column is None or category_column is None:
			return {
				"category": category,
				"our_avg_price_cents": 0,
				"supplier_count": 0,
				"price_range": {"min_cents": 0, "max_cents": 0, "p25_cents": 0, "p75_cents": 0},
			}

		stmt = (
			sa.select(
				sa.func.avg(unit_column),
				sa.func.count(sa.distinct(APInvoice.supplier_id)),
				sa.func.min(unit_column),
				sa.func.max(unit_column),
				sa.func.percentile_cont(Decimal("0.25")).within_group(unit_column),
				sa.func.percentile_cont(Decimal("0.75")).within_group(unit_column),
			)
			.join(APInvoice, APInvoice.id == APInvoiceLine.invoice_id)
			.where(
				APInvoice.tenant_id == tenant_id,
				APInvoiceLine.tenant_id == tenant_id,
				category_column == category,
				unit_column.is_not(None),
			)
		)
		avg_price, supplier_count, min_price, max_price, p25, p75 = session.execute(stmt).one()
		return {
			"category": category,
			"our_avg_price_cents": int(avg_price or 0),
			"supplier_count": int(supplier_count or 0),
			"price_range": {
				"min_cents": int(min_price or 0),
				"max_cents": int(max_price or 0),
				"p25_cents": int(p25 or 0),
				"p75_cents": int(p75 or 0),
			},
		}


__all__ = ["SpendAnalyticsService"]
