"""
pgappforge/plugins/erp/crm/commerce/services.py

CommerceService — stateless business logic for the Commerce plugin.

Key methods
-----------
  create_subscription(data, session) -> Subscription
      Creates an ACTIVE (or TRIALING) subscription from a plan; validates plan exists.

  cancel_subscription(subscription_id, reason, session) -> Subscription
      Marks subscription CANCELLED; records cancellation_reason; emits event.

  pause_subscription(subscription_id, session) -> Subscription
      Moves ACTIVE → PAUSED (billing paused; next_billing_date cleared).

  resume_subscription(subscription_id, new_billing_date, session) -> Subscription
      Moves PAUSED → ACTIVE; sets next_billing_date.

  process_renewal(subscription_id, session) -> Subscription
      Advances next_billing_date by plan interval; emits SubscriptionRenewedEvent.
      Callers (billing plugin / scheduler) integrate with payment gateway before calling.

  mark_past_due(subscription_id, session) -> Subscription
      Moves ACTIVE → PAST_DUE; emits SubscriptionPastDueEvent.

  apply_shipping_cost(order_subtotal_cents, shipping_method_id, session) -> int
      Returns shipping cost in cents (0 if free threshold met).

  compute_tax(subtotal_cents, jurisdiction_code, product_category, session) -> dict
      Returns tax_cents and effective_rate for a line.

  subscription_revenue_report(tenant_id, session) -> dict
      MRR, ARR, subscriber counts by status.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CommerceError(Exception):
	"""Base exception for Commerce service layer."""


class SubscriptionNotFoundError(CommerceError):
	pass


class PlanNotFoundError(CommerceError):
	pass


class ShippingMethodNotFoundError(CommerceError):
	pass


class CommerceValidationError(CommerceError):
	"""Business rule violation."""


# ---------------------------------------------------------------------------
# CommerceService
# ---------------------------------------------------------------------------

class CommerceService:
	"""Stateless business logic for Commerce."""

	@staticmethod
	def create_subscription(data: dict[str, Any], session: Any) -> Any:
		"""Create a new subscription from a plan.

		data keys: tenant_id, customer_id, plan_id, start_date (date),
		           payment_method_id (optional), billing_interval (optional override)
		"""
		from pgappforge.plugins.erp.crm.commerce.models import Subscription, SubscriptionPlan
		from pgappforge.plugins.erp.crm.commerce.events import SubscriptionActivatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		tenant_id = data["tenant_id"]
		plan_id = data["plan_id"]

		plan = session.execute(
			sa.select(SubscriptionPlan).where(
				SubscriptionPlan.id == plan_id,
				SubscriptionPlan.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if plan is None:
			raise PlanNotFoundError(f"SubscriptionPlan {plan_id} not found")

		start_date = data.get("start_date") or date.today()
		if isinstance(start_date, str):
			start_date = date.fromisoformat(start_date)

		# Trial logic
		if plan.trial_days > 0:
			status = "TRIALING"
			next_billing_date = start_date + timedelta(days=plan.trial_days)
		else:
			status = "ACTIVE"
			next_billing_date = CommerceService._advance_date(start_date, plan.interval_months)

		billing_interval = data.get("billing_interval") or CommerceService._months_to_interval(plan.interval_months)

		sub = Subscription(
			tenant_id=tenant_id,
			customer_id=data["customer_id"],
			plan_id=plan_id,
			status=status,
			start_date=start_date,
			next_billing_date=next_billing_date,
			billing_interval=billing_interval,
			amount_cents=plan.amount_cents,
			currency_code=plan.currency_code,
			payment_method_id=data.get("payment_method_id"),
		)
		session.add(sub)
		session.flush()

		emit_event(SubscriptionActivatedEvent(
			aggregate_id=sub.id,
			aggregate_type="Subscription",
			tenant_id=tenant_id,
			subscription_id=sub.id,
			customer_id=sub.customer_id,
			plan_id=plan_id,
			plan_name=plan.name,
			amount_cents=sub.amount_cents,
			currency_code=sub.currency_code,
			billing_interval=sub.billing_interval,
			start_date=start_date.isoformat(),
			next_billing_date=next_billing_date.isoformat() if next_billing_date else "",
		), session)

		log.info(
			"CommerceService.create_subscription: sub %s created for customer %s plan %r",
			sub.id, sub.customer_id, plan.name,
		)
		return sub

	@staticmethod
	def cancel_subscription(subscription_id: str, reason: str, session: Any) -> Any:
		"""Cancel a subscription; idempotent if already CANCELLED."""
		from pgappforge.plugins.erp.crm.commerce.models import Subscription
		from pgappforge.plugins.erp.crm.commerce.events import SubscriptionCancelledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == subscription_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {subscription_id} not found")
		if sub.status == "CANCELLED":
			return sub  # idempotent

		now = datetime.now(timezone.utc)
		sub.status = "CANCELLED"
		sub.cancelled_at = now
		sub.cancellation_reason = reason
		sub.next_billing_date = None
		session.flush()

		emit_event(SubscriptionCancelledEvent(
			aggregate_id=sub.id,
			aggregate_type="Subscription",
			tenant_id=sub.tenant_id,
			subscription_id=sub.id,
			customer_id=sub.customer_id,
			plan_id=sub.plan_id,
			cancelled_at=now.isoformat(),
			cancellation_reason=reason,
		), session)

		log.info("CommerceService.cancel_subscription: %s cancelled (%s)", subscription_id, reason)
		return sub

	@staticmethod
	def pause_subscription(subscription_id: str, session: Any) -> Any:
		"""Pause an ACTIVE subscription (billing suspended)."""
		from pgappforge.plugins.erp.crm.commerce.models import Subscription

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == subscription_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {subscription_id} not found")
		if sub.status != "ACTIVE":
			raise CommerceValidationError(f"Can only pause ACTIVE subscriptions, got {sub.status!r}")

		sub.status = "PAUSED"
		sub.next_billing_date = None
		session.flush()
		log.info("CommerceService.pause_subscription: %s paused", subscription_id)
		return sub

	@staticmethod
	def resume_subscription(subscription_id: str, new_billing_date: date, session: Any) -> Any:
		"""Resume a PAUSED subscription."""
		from pgappforge.plugins.erp.crm.commerce.models import Subscription

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == subscription_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {subscription_id} not found")
		if sub.status != "PAUSED":
			raise CommerceValidationError(f"Can only resume PAUSED subscriptions, got {sub.status!r}")

		sub.status = "ACTIVE"
		sub.next_billing_date = new_billing_date
		session.flush()
		log.info("CommerceService.resume_subscription: %s resumed → billing %s", subscription_id, new_billing_date)
		return sub

	@staticmethod
	def process_renewal(subscription_id: str, session: Any) -> Any:
		"""Advance billing date and emit SubscriptionRenewedEvent.

		Caller is responsible for payment capture before calling this.
		"""
		from pgappforge.plugins.erp.crm.commerce.models import Subscription, SubscriptionPlan
		from pgappforge.plugins.erp.crm.commerce.events import SubscriptionRenewedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == subscription_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {subscription_id} not found")
		if sub.status not in ("ACTIVE", "TRIALING", "PAST_DUE"):
			raise CommerceValidationError(f"Cannot renew {sub.status!r} subscription")

		plan = session.execute(
			sa.select(SubscriptionPlan).where(SubscriptionPlan.id == sub.plan_id)
		).scalar_one_or_none()
		if plan is None:
			raise PlanNotFoundError(f"Plan {sub.plan_id} not found")

		billed_date = sub.next_billing_date or date.today()
		next_date = CommerceService._advance_date(billed_date, plan.interval_months)

		sub.status = "ACTIVE"
		sub.next_billing_date = next_date
		session.flush()

		emit_event(SubscriptionRenewedEvent(
			aggregate_id=sub.id,
			aggregate_type="Subscription",
			tenant_id=sub.tenant_id,
			subscription_id=sub.id,
			customer_id=sub.customer_id,
			plan_id=sub.plan_id,
			amount_cents=sub.amount_cents,
			currency_code=sub.currency_code,
			billed_date=billed_date.isoformat(),
			next_billing_date=next_date.isoformat(),
		), session)

		log.info("CommerceService.process_renewal: %s renewed → next %s", subscription_id, next_date)
		return sub

	@staticmethod
	def mark_past_due(subscription_id: str, session: Any) -> Any:
		"""Move subscription to PAST_DUE after a failed billing attempt."""
		from pgappforge.plugins.erp.crm.commerce.models import Subscription
		from pgappforge.plugins.erp.crm.commerce.events import SubscriptionPastDueEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == subscription_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {subscription_id} not found")

		failed_date = sub.next_billing_date or date.today()
		sub.status = "PAST_DUE"
		session.flush()

		emit_event(SubscriptionPastDueEvent(
			aggregate_id=sub.id,
			aggregate_type="Subscription",
			tenant_id=sub.tenant_id,
			subscription_id=sub.id,
			customer_id=sub.customer_id,
			plan_id=sub.plan_id,
			amount_cents=sub.amount_cents,
			currency_code=sub.currency_code,
			failed_billing_date=failed_date.isoformat(),
		), session)

		log.info("CommerceService.mark_past_due: %s → PAST_DUE", subscription_id)
		return sub

	@staticmethod
	def apply_shipping_cost(
		order_subtotal_cents: int,
		shipping_method_id: str,
		session: Any,
	) -> int:
		"""Return applicable shipping cost in cents; 0 if free threshold met."""
		from pgappforge.plugins.erp.crm.commerce.models import ShippingMethod

		method = session.execute(
			sa.select(ShippingMethod).where(
				ShippingMethod.id == shipping_method_id,
				ShippingMethod.is_active == True,  # noqa: E712
			)
		).scalar_one_or_none()
		if method is None:
			raise ShippingMethodNotFoundError(f"ShippingMethod {shipping_method_id} not found or inactive")

		if method.free_threshold_cents is not None and order_subtotal_cents >= method.free_threshold_cents:
			return 0
		return method.cost_cents

	@staticmethod
	def compute_tax(
		subtotal_cents: int,
		jurisdiction_code: str,
		product_category: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return tax_cents and effective_rate for a line item.

		Looks up TaxRule by jurisdiction + product_category; falls back to
		wildcard category '*'.  Returns zero tax if no rule found.
		"""
		from pgappforge.plugins.erp.crm.commerce.models import TaxRule

		# Exact match first, then wildcard
		rule = session.execute(
			sa.select(TaxRule).where(
				TaxRule.jurisdiction_code == jurisdiction_code,
				TaxRule.product_category == product_category,
			)
		).scalar_one_or_none()

		if rule is None:
			rule = session.execute(
				sa.select(TaxRule).where(
					TaxRule.jurisdiction_code == jurisdiction_code,
					TaxRule.product_category == "*",
				)
			).scalar_one_or_none()

		if rule is None:
			return {"tax_cents": 0, "tax_rate": Decimal("0"), "tax_name": None, "is_inclusive": False}

		rate = Decimal(str(rule.tax_rate))
		if rule.is_inclusive:
			# Tax already baked into price: tax = subtotal * rate / (1 + rate)
			tax_cents = int(subtotal_cents * rate / (1 + rate))
		else:
			tax_cents = int(subtotal_cents * rate)

		return {
			"tax_cents": tax_cents,
			"tax_rate": rate,
			"tax_name": rule.tax_name,
			"is_inclusive": rule.is_inclusive,
		}

	@staticmethod
	def subscription_revenue_report(tenant_id: str, session: Any) -> dict[str, Any]:
		"""MRR, ARR, and subscriber counts by status."""
		from pgappforge.plugins.erp.crm.commerce.models import Subscription
		import sqlalchemy.func as func

		rows = session.execute(
			sa.select(
				Subscription.status,
				Subscription.billing_interval,
				func.count(Subscription.id).label("cnt"),
				func.sum(Subscription.amount_cents).label("total_amount_cents"),
			)
			.where(Subscription.tenant_id == tenant_id)
			.group_by(Subscription.status, Subscription.billing_interval)
		).all()

		mrr_cents = 0
		by_status: dict[str, int] = {}
		for row in rows:
			by_status[row.status] = by_status.get(row.status, 0) + row.cnt
			if row.status == "ACTIVE" and row.total_amount_cents:
				# Normalise to monthly
				if row.billing_interval == "MONTHLY":
					mrr_cents += row.total_amount_cents
				elif row.billing_interval == "ANNUAL":
					mrr_cents += row.total_amount_cents // 12
				elif row.billing_interval == "QUARTERLY":
					mrr_cents += row.total_amount_cents // 3
				elif row.billing_interval == "WEEKLY":
					mrr_cents += row.total_amount_cents * 4

		return {
			"mrr_cents": mrr_cents,
			"arr_cents": mrr_cents * 12,
			"by_status": by_status,
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _advance_date(from_date: date, months: int) -> date:
		"""Add *months* months to *from_date*, clamping to end of month."""
		month = from_date.month - 1 + months
		year = from_date.year + month // 12
		month = month % 12 + 1
		import calendar
		day = min(from_date.day, calendar.monthrange(year, month)[1])
		return date(year, month, day)

	@staticmethod
	def _months_to_interval(months: int) -> str:
		"""Map interval_months to billing_interval enum string."""
		return {1: "MONTHLY", 3: "QUARTERLY", 12: "ANNUAL"}.get(months, "MONTHLY")


__all__ = [
	"CommerceService",
	"CommerceError",
	"SubscriptionNotFoundError",
	"PlanNotFoundError",
	"ShippingMethodNotFoundError",
	"CommerceValidationError",
]
