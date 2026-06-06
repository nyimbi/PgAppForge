from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.hcm.lunch.events import (
	LunchOrderCancelledEvent,
	LunchOrderPlacedEvent,
	LunchSubsidyAppliedEvent,
	LunchSupplierDeliveredEvent,
)
from pgappforge.plugins.erp.hcm.lunch.models import (
	LunchMenu,
	LunchOrder,
	LunchSubsidyPolicy,
	LunchSupplier,
)
from pgappforge.plugins.workflow.engine import BPMActionRegistry

_log = logging.getLogger(__name__)

__all__ = [
	"LunchServiceError",
	"LunchNotFoundError",
	"LunchStateError",
	"LunchService",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LunchServiceError(Exception):
	"""Base error for the Lunch Management domain."""


class LunchNotFoundError(LunchServiceError):
	"""Raised when a requested lunch resource does not exist."""


class LunchStateError(LunchServiceError):
	"""Raised when an operation is invalid for the current state."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
	return datetime.now(tz=timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	"""Fire-and-forget event emission. Swallows if no bus is wired."""
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception:  # noqa: BLE001
		_log.debug("Event bus unavailable; event %s not published", type(event).__name__)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LunchService:
	"""Stateless service layer for HCM Lunch Management.

	Every method accepts ``session`` as a positional argument so callers
	can pass the SQLAlchemy session explicitly.
	"""

	# ------------------------------------------------------------------
	# Menu lifecycle
	# ------------------------------------------------------------------

	def publish_menu(
		self,
		menu_id: str,
		session: Session,
	) -> LunchMenu:
		"""Transition a DRAFT menu to PUBLISHED.

		Raises ``LunchStateError`` if menu is not in DRAFT or has no items.
		"""
		assert menu_id, "menu_id is required"

		menu = session.execute(
			select(LunchMenu).where(LunchMenu.id == menu_id)
		).scalar_one_or_none()

		if menu is None:
			raise LunchNotFoundError(f"LunchMenu {menu_id} not found.")

		if menu.status != "DRAFT":
			raise LunchStateError(
				f"Cannot publish menu {menu_id}: expected DRAFT, got {menu.status}."
			)

		if not menu.items:
			raise LunchStateError(
				f"Cannot publish menu {menu_id}: menu has no items."
			)

		menu.status = "PUBLISHED"
		session.flush()
		_log.info("LunchMenu published: id=%s date=%s", menu_id, menu.menu_date)
		return menu

	# ------------------------------------------------------------------
	# Order lifecycle
	# ------------------------------------------------------------------

	def place_order(
		self,
		employee_id: str,
		menu_id: str,
		items: list[dict[str, Any]],
		session: Session,
		*,
		tenant_id: str,
		special_instructions: str | None = None,
	) -> LunchOrder:
		"""Validate items against published menu, apply subsidy, and place order.

		``items`` is a list of ``{item_id, qty}`` dicts.  Name and unit price
		are resolved from the menu definition.

		Raises ``LunchNotFoundError`` if menu is not found.
		Raises ``LunchStateError`` if menu is not PUBLISHED or an item_id is invalid.
		"""
		assert employee_id, "employee_id is required"
		assert menu_id, "menu_id is required"
		assert tenant_id, "tenant_id is required"
		assert items, "items must not be empty"

		menu = session.execute(
			select(LunchMenu).where(
				LunchMenu.id == menu_id,
				LunchMenu.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if menu is None:
			raise LunchNotFoundError(f"LunchMenu {menu_id} not found for tenant {tenant_id}.")

		if menu.status != "PUBLISHED":
			raise LunchStateError(
				f"Cannot order from menu {menu_id}: status is {menu.status}, expected PUBLISHED."
			)

		# Build lookup by item id
		menu_items_by_id: dict[str, dict[str, Any]] = {
			str(mi["id"]): mi for mi in (menu.items or [])
		}

		resolved_items: list[dict[str, Any]] = []
		subtotal_cents = 0

		for line in items:
			item_id = str(line.get("item_id", ""))
			qty = int(line.get("qty", 1))
			mi = menu_items_by_id.get(item_id)
			if mi is None:
				raise LunchStateError(
					f"Item {item_id!r} not found in menu {menu_id}."
				)
			if not mi.get("available", True):
				raise LunchStateError(
					f"Item {mi.get('name', item_id)!r} is not available."
				)
			unit_price_cents = int(mi.get("price_cents", 0))
			line_total = unit_price_cents * qty
			subtotal_cents += line_total
			resolved_items.append({
				"item_id": item_id,
				"name": mi.get("name", ""),
				"qty": qty,
				"unit_price_cents": unit_price_cents,
			})

		# Apply subsidy
		subsidy_cents = self._compute_subsidy(
			employee_id=employee_id,
			tenant_id=tenant_id,
			subtotal_cents=subtotal_cents,
			order_date=menu.menu_date,
			session=session,
		)
		employee_pays_cents = max(0, subtotal_cents - subsidy_cents)

		order = LunchOrder(
			tenant_id=tenant_id,
			employee_id=employee_id,
			menu_id=menu_id,
			order_date=menu.menu_date,
			items=resolved_items,
			subtotal_cents=subtotal_cents,
			subsidy_cents=subsidy_cents,
			employee_pays_cents=employee_pays_cents,
			status="PLACED",
			placed_at=_now_utc(),
			special_instructions=special_instructions,
		)
		session.add(order)
		session.flush()

		_emit(
			LunchOrderPlacedEvent(
				order_id=order.id,
				employee_id=employee_id,
				menu_date=str(menu.menu_date),
				items=resolved_items,
				total_cents=subtotal_cents,
			)
		)

		if subsidy_cents > 0:
			_emit(
				LunchSubsidyAppliedEvent(
					order_id=order.id,
					employee_id=employee_id,
					subsidy_cents=subsidy_cents,
				)
			)

		_log.info(
			"LunchOrder placed: id=%s employee=%s menu=%s subtotal_cents=%d subsidy_cents=%d",
			order.id, employee_id, menu_id, subtotal_cents, subsidy_cents,
		)
		return order

	def cancel_order(
		self,
		order_id: str,
		employee_id: str,
		session: Session,
		*,
		reason: str = "",
	) -> LunchOrder:
		"""Cancel a DRAFT or PLACED order.

		Raises ``LunchNotFoundError`` if order not found.
		Raises ``LunchStateError`` if order is not in a cancellable state.
		"""
		assert order_id, "order_id is required"
		assert employee_id, "employee_id is required"

		order = session.execute(
			select(LunchOrder).where(LunchOrder.id == order_id)
		).scalar_one_or_none()

		if order is None:
			raise LunchNotFoundError(f"LunchOrder {order_id} not found.")

		if order.employee_id != employee_id:
			raise LunchStateError(
				f"Order {order_id} does not belong to employee {employee_id}."
			)

		if order.status not in {"DRAFT", "PLACED"}:
			raise LunchStateError(
				f"Cannot cancel order {order_id}: status is {order.status}. "
				"Only DRAFT and PLACED orders can be cancelled."
			)

		order.status = "CANCELLED"
		session.flush()

		_emit(
			LunchOrderCancelledEvent(
				order_id=order_id,
				employee_id=employee_id,
				reason=reason,
			)
		)

		_log.info(
			"LunchOrder cancelled: id=%s employee=%s reason=%s",
			order_id, employee_id, reason,
		)
		return order

	# ------------------------------------------------------------------
	# Queries
	# ------------------------------------------------------------------

	def get_menu_for_date(
		self,
		menu_date: date,
		tenant_id: str,
		session: Session,
	) -> LunchMenu | None:
		"""Return the PUBLISHED menu for a given date and tenant, or None."""
		assert menu_date, "menu_date is required"
		assert tenant_id, "tenant_id is required"

		return session.execute(
			select(LunchMenu).where(
				LunchMenu.tenant_id == tenant_id,
				LunchMenu.menu_date == menu_date,
				LunchMenu.status == "PUBLISHED",
			)
		).scalar_one_or_none()

	def get_employee_orders(
		self,
		employee_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
		session: Session,
	) -> list[dict[str, Any]]:
		"""List orders for an employee within a date range, with totals.

		Returns a list of dicts with order summary data.
		"""
		assert employee_id, "employee_id is required"
		assert tenant_id, "tenant_id is required"

		orders = session.execute(
			select(LunchOrder).where(
				LunchOrder.tenant_id == tenant_id,
				LunchOrder.employee_id == employee_id,
				LunchOrder.order_date >= from_date,
				LunchOrder.order_date <= to_date,
			).order_by(LunchOrder.order_date.desc())
		).scalars().all()

		return [
			{
				"order_id": o.id,
				"order_date": str(o.order_date),
				"menu_id": o.menu_id,
				"status": o.status,
				"subtotal_cents": o.subtotal_cents,
				"subsidy_cents": o.subsidy_cents,
				"employee_pays_cents": o.employee_pays_cents,
				"items_count": len(o.items or []),
			}
			for o in orders
		]

	def get_daily_summary(
		self,
		menu_date: date,
		tenant_id: str,
		session: Session,
	) -> dict[str, Any]:
		"""Return aggregated daily summary: orders by item, revenue, subsidy total.

		Keys: ``orders_count``, ``total_revenue_cents``, ``total_subsidy_cents``,
		``employee_revenue_cents``, ``items_summary`` (list of {item_id, name, qty, revenue_cents}).
		"""
		assert menu_date, "menu_date is required"
		assert tenant_id, "tenant_id is required"

		orders = session.execute(
			select(LunchOrder).where(
				LunchOrder.tenant_id == tenant_id,
				LunchOrder.order_date == menu_date,
				LunchOrder.status.notin_(["CANCELLED", "DRAFT"]),
			)
		).scalars().all()

		total_revenue_cents = sum(o.subtotal_cents for o in orders)
		total_subsidy_cents = sum(o.subsidy_cents for o in orders)
		employee_revenue_cents = sum(o.employee_pays_cents for o in orders)

		# Aggregate by item
		item_agg: dict[str, dict[str, Any]] = {}
		for order in orders:
			for line in order.items or []:
				item_id = str(line.get("item_id", ""))
				if item_id not in item_agg:
					item_agg[item_id] = {
						"item_id": item_id,
						"name": line.get("name", ""),
						"qty": 0,
						"revenue_cents": 0,
					}
				item_agg[item_id]["qty"] += int(line.get("qty", 0))
				item_agg[item_id]["revenue_cents"] += (
					int(line.get("qty", 0)) * int(line.get("unit_price_cents", 0))
				)

		return {
			"orders_count": len(orders),
			"total_revenue_cents": total_revenue_cents,
			"total_subsidy_cents": total_subsidy_cents,
			"employee_revenue_cents": employee_revenue_cents,
			"items_summary": sorted(item_agg.values(), key=lambda x: x["qty"], reverse=True),
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _compute_subsidy(
		self,
		employee_id: str,
		tenant_id: str,
		subtotal_cents: int,
		order_date: date,
		session: Session,
	) -> int:
		"""Resolve the active subsidy policy and compute subsidy amount in cents."""
		policy = session.execute(
			select(LunchSubsidyPolicy).where(
				LunchSubsidyPolicy.tenant_id == tenant_id,
				LunchSubsidyPolicy.is_active.is_(True),
				LunchSubsidyPolicy.effective_from <= order_date,
				(LunchSubsidyPolicy.effective_to.is_(None))
				| (LunchSubsidyPolicy.effective_to >= order_date),
			).order_by(
				# entity-specific policies take priority over general ones
				LunchSubsidyPolicy.entity_id.desc().nulls_last()
			)
		).scalar_one_or_none()

		if policy is None:
			return 0

		if policy.subsidy_type == "FIXED":
			subsidy = int(policy.fixed_amount_cents)
		elif policy.subsidy_type == "PERCENTAGE":
			subsidy = int(Decimal(str(subtotal_cents)) * Decimal(str(policy.percentage)) / 100)
		elif policy.subsidy_type == "CAPPED":
			pct_amount = int(Decimal(str(subtotal_cents)) * Decimal(str(policy.percentage)) / 100)
			subsidy = min(pct_amount, int(policy.fixed_amount_cents or pct_amount))
		else:
			subsidy = 0

		if policy.max_daily_cents is not None:
			subsidy = min(subsidy, int(policy.max_daily_cents))

		return max(0, min(subsidy, subtotal_cents))


# ---------------------------------------------------------------------------
# BPM Action Registry
# ---------------------------------------------------------------------------


@BPMActionRegistry.register("hcm.lunch.place_order", "Place lunch order for employee")
def _bpm_place_order(
	record_ctx: Any,
	session: Session,
	employee_id: str,
	menu_id: str,
	items: list[dict[str, Any]],
	tenant_id: str,
	**kw: Any,
) -> LunchOrder:
	svc = LunchService()
	return svc.place_order(
		employee_id,
		menu_id,
		items,
		session,
		tenant_id=tenant_id,
		special_instructions=kw.get("special_instructions"),
	)
