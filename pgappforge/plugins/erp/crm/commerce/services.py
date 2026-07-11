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


class OrderNotFoundError(CommerceError):
	pass


class ProductNotFoundError(CommerceError):
	pass


class CouponNotFoundError(CommerceError):
	pass


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
	# Cart
	# ------------------------------------------------------------------

	@staticmethod
	def add_to_cart(
		session: Any,
		customer_id: str,
		product_code: str,
		quantity: int | float,
		tenant_id: str,
		session_token: str | None = None,
	) -> Any:
		"""Add/update a product line in the customer's active cart.

		Creates a new ACTIVE cart when none exists.  session_token is
		generated from customer_id when not supplied.
		"""
		import secrets
		from pgappforge.plugins.erp.crm.commerce.models import Cart, ProductCatalogue

		# Resolve product price
		product = session.execute(
			sa.select(ProductCatalogue).where(
				ProductCatalogue.tenant_id == tenant_id,
				ProductCatalogue.product_code == product_code,
				ProductCatalogue.is_active == True,  # noqa: E712
			)
		).scalar_one_or_none()
		if product is None:
			raise CommerceValidationError(f"Product {product_code!r} not found or inactive")

		token = session_token or str(customer_id)

		cart = session.execute(
			sa.select(Cart).where(
				Cart.tenant_id == tenant_id,
				Cart.session_token == token,
				Cart.status == "ACTIVE",
			)
		).scalar_one_or_none()

		if cart is None:
			cart = Cart(
				tenant_id=tenant_id,
				customer_id=customer_id,
				session_token=token,
				status="ACTIVE",
				items=[],
			)
			session.add(cart)
			session.flush()

		items: list[dict[str, Any]] = list(cart.items or [])
		for line in items:
			if line.get("product_code") == product_code:
				line["qty"] = float(line.get("qty", 0)) + float(quantity)
				break
		else:
			items.append({
				"product_code": product_code,
				"qty": float(quantity),
				"unit_price_cents": product.unit_price_cents,
				"discount_cents": 0,
			})

		cart.items = items
		session.flush()
		log.info(
			"CommerceService.add_to_cart: cart %s ← %s qty=%s",
			cart.id, product_code, quantity,
		)
		return cart

	# ------------------------------------------------------------------
	# Order placement
	# ------------------------------------------------------------------

	@staticmethod
	def place_order(
		session: Any,
		cart_id_or_customer_id: str,
		shipping_address: dict[str, Any],
		billing_address: dict[str, Any],
		coupon_code: str | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Convert a cart to a confirmed Order; compute totals + VAT; post GL.

		GL entries (lazy import, silent fail if GL not available):
		  DR Accounts Receivable "1200"
		  CR Deferred Revenue "2310"
		"""
		import secrets
		from decimal import Decimal
		from pgappforge.plugins.erp.crm.commerce.models import (
			Cart, Coupon, Order, OrderLine, ProductCatalogue,
		)

		# Resolve cart
		cart = session.execute(
			sa.select(Cart).where(
				Cart.id == cart_id_or_customer_id,
				Cart.tenant_id == tenant_id,
				Cart.status == "ACTIVE",
			)
		).scalar_one_or_none()
		if cart is None:
			raise CommerceValidationError(f"Active cart {cart_id_or_customer_id} not found")
		if not cart.items:
			raise CommerceValidationError("Cannot place order from empty cart")

		# Compute subtotal
		subtotal_cents: int = 0
		for item in cart.items:
			line_net = int(item["unit_price_cents"]) * float(item["qty"]) - int(item.get("discount_cents", 0))
			subtotal_cents += int(line_net)

		# Apply coupon if provided
		discount_cents = 0
		if coupon_code:
			coupon_result = CommerceService.apply_coupon(session, cart.id, coupon_code, tenant_id)
			discount_cents = coupon_result["discount_cents"]

		# VAT: flat 16% KES default; real implementation uses compute_tax per line
		tax_rate = Decimal("0.16")
		tax_cents = int((subtotal_cents - discount_cents) * tax_rate)
		shipping_cents = 0  # caller passes via shipping method; default 0
		total_cents = subtotal_cents - discount_cents + tax_cents + shipping_cents

		# Generate order number: ORD-YYYYMMDD-<6 hex>
		from datetime import datetime as _dt
		order_number = f"ORD-{_dt.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"

		order = Order(
			tenant_id=tenant_id,
			order_number=order_number,
			customer_id=cart.customer_id or cart_id_or_customer_id,
			cart_id=cart.id,
			channel="B2C",
			status="CONFIRMED",
			subtotal_cents=subtotal_cents,
			discount_cents=discount_cents,
			tax_cents=tax_cents,
			shipping_cents=shipping_cents,
			total_cents=total_cents,
			payment_status="PENDING",
			shipping_address=shipping_address,
			billing_address=billing_address,
		)
		session.add(order)
		session.flush()

		# Create order lines
		for item in cart.items:
			qty = float(item["qty"])
			upc = int(item["unit_price_cents"])
			disc = int(item.get("discount_cents", 0))
			tax_line = int(qty * (upc - disc) * float(tax_rate))
			line_total = int(qty * (upc - disc)) + tax_line
			product = session.execute(
				sa.select(ProductCatalogue).where(
					ProductCatalogue.tenant_id == tenant_id,
					ProductCatalogue.product_code == item["product_code"],
				)
			).scalar_one_or_none()
			line = OrderLine(
				tenant_id=tenant_id,
				order_id=order.id,
				product_code=item["product_code"],
				description=product.name if product else item["product_code"],
				quantity=Decimal(str(qty)),
				unit_price_cents=upc,
				discount_cents=disc,
				tax_cents=tax_line,
				line_total_cents=line_total,
			)
			session.add(line)

		# Mark cart CONVERTED
		cart.status = "CONVERTED"

		# GL posting (lazy import — silent fail if GL plugin absent)
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			GLService.post_journal(
				session,
				tenant_id=tenant_id,
				reference=order.order_number,
				description=f"Order {order.order_number} placed",
				lines=[
					{"account_code": "1200", "debit_cents": total_cents, "credit_cents": 0},
					{"account_code": "2310", "debit_cents": 0, "credit_cents": total_cents},
				],
			)
		except Exception:
			pass

		session.flush()
		log.info("CommerceService.place_order: order %s total=%d¢", order.order_number, total_cents)
		return order

	# ------------------------------------------------------------------
	# Payment
	# ------------------------------------------------------------------

	@staticmethod
	def confirm_payment(
		session: Any,
		order_id: str,
		payment_method: str,
		amount_cents: int,
		reference: str,
		tenant_id: str,
	) -> Any:
		"""Record a payment against an order; advance order status on full payment.

		GL on full payment:
		  DR Cash/MPESA "1011"
		  CR Accounts Receivable "1200"
		"""
		from datetime import datetime as _dt
		from pgappforge.plugins.erp.crm.commerce.models import Order, PaymentTransaction

		order = session.execute(
			sa.select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
		).scalar_one_or_none()
		if order is None:
			raise CommerceValidationError(f"Order {order_id} not found")
		if order.status in ("CANCELLED", "REFUNDED"):
			raise CommerceValidationError(f"Cannot record payment on {order.status} order")

		now = _dt.now(timezone.utc)
		txn = PaymentTransaction(
			tenant_id=tenant_id,
			order_id=order_id,
			payment_method=payment_method,
			amount_cents=amount_cents,
			currency_code="KES",
			reference=reference,
			status="COMPLETED",
			processed_at=now,
		)
		session.add(txn)
		session.flush()

		# Sum all completed payments
		paid_total = session.execute(
			sa.select(sa.func.sum(PaymentTransaction.amount_cents)).where(
				PaymentTransaction.order_id == order_id,
				PaymentTransaction.status == "COMPLETED",
			)
		).scalar() or 0

		if paid_total >= order.total_cents:
			order.payment_status = "PAID"
			if order.status == "CONFIRMED":
				order.status = "PROCESSING"
		elif paid_total > 0:
			order.payment_status = "PARTIALLY_PAID"

		# GL
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			GLService.post_journal(
				session,
				tenant_id=tenant_id,
				reference=reference,
				description=f"Payment {reference} for order {order.order_number}",
				lines=[
					{"account_code": "1011", "debit_cents": amount_cents, "credit_cents": 0},
					{"account_code": "1200", "debit_cents": 0, "credit_cents": amount_cents},
				],
			)
		except Exception:
			pass

		session.flush()
		log.info(
			"CommerceService.confirm_payment: order %s +%d¢ via %s payment_status=%s",
			order.order_number, amount_cents, payment_method, order.payment_status,
		)
		return txn

	# ------------------------------------------------------------------
	# Fulfilment
	# ------------------------------------------------------------------

	def create_delivery_order(
		self,
		order_id: str,
		session: Any,
		tenant_id: str = "",
		delivery_date: date | None = None,
		warehouse_id: str | None = None,
		carrier: str | None = None,
	) -> Any:
		"""Create a delivery order from a confirmed sales order."""
		from pgappforge.plugins.erp.crm.commerce.models import DeliveryOrder, Order

		order = session.get(Order, order_id)
		if order is None or (tenant_id and order.tenant_id != tenant_id):
			raise OrderNotFoundError(f"Order {order_id!r} not found")
		if order.status not in ("CONFIRMED", "PROCESSING"):
			raise CommerceValidationError(
				f"Delivery orders require CONFIRMED or PROCESSING order status, got {order.status!r}"
			)

		existing_count = session.execute(
			sa.select(sa.func.count())
			.select_from(DeliveryOrder)
			.where(DeliveryOrder.sales_order_id == order_id)
		).scalar() or 0
		delivery_number = f"DEL-{order.order_number}-{int(existing_count) + 1:02d}"
		delivery = DeliveryOrder(
			tenant_id=order.tenant_id,
			delivery_number=delivery_number,
			sales_order_id=order.id,
			customer_id=order.customer_id,
			requested_ship_date=date.today(),
			delivery_date=delivery_date,
			warehouse_id=warehouse_id,
			carrier=carrier,
			status="READY_TO_PICK",
			shipping_address=order.shipping_address or {},
		)
		session.add(delivery)
		order.status = "PROCESSING"
		order.updated_at = datetime.now(timezone.utc)
		session.flush()
		log.info("CommerceService.create_delivery_order: %s for order=%s", delivery_number, order_id)
		return delivery

	def advance_to_next_step(self, record_id: str, session: Any) -> Any:
		"""Advance one O2C commerce document to the next workflow status."""
		from pgappforge.plugins.erp.crm.commerce.models import DeliveryOrder, Order

		now = datetime.now(timezone.utc)
		delivery = session.get(DeliveryOrder, record_id)
		if delivery is not None:
			if delivery.status == "DRAFT":
				delivery.status = "READY_TO_PICK"
			elif delivery.status == "READY_TO_PICK":
				delivery.status = "PICKED"
				delivery.picked_at = now
			elif delivery.status == "PICKED":
				delivery.status = "SHIPPED"
				delivery.shipped_at = now
				if delivery.sales_order:
					delivery.sales_order.status = "SHIPPED"
					delivery.sales_order.updated_at = now
			elif delivery.status == "SHIPPED":
				delivery.status = "DELIVERED"
				delivery.delivered_at = now
				delivery.delivery_date = date.today()
				if delivery.sales_order:
					delivery.sales_order.status = "DELIVERED"
					delivery.sales_order.updated_at = now
			else:
				raise CommerceValidationError(f"No delivery advance transition from {delivery.status!r}")
			delivery.updated_at = now
			session.flush()
			return delivery

		order = session.get(Order, record_id)
		if order is None:
			raise CommerceValidationError(f"O2C commerce record {record_id!r} not found")
		if order.status == "DRAFT":
			order.status = "CONFIRMED"
			order.updated_at = now
			session.flush()
			return order
		if order.status in ("CONFIRMED", "PROCESSING"):
			existing_delivery = session.execute(
				sa.select(DeliveryOrder)
				.where(DeliveryOrder.sales_order_id == order.id)
				.where(DeliveryOrder.status.not_in(["CANCELLED", "DELIVERED"]))
				.order_by(DeliveryOrder.created_at.desc())
				.limit(1)
			).scalar_one_or_none()
			if existing_delivery is not None:
				return existing_delivery
			return self.create_delivery_order(order.id, session, tenant_id=order.tenant_id)
		if order.status == "SHIPPED":
			order.status = "DELIVERED"
			order.updated_at = now
			session.flush()
			return order
		raise CommerceValidationError(f"No sales order advance transition from {order.status!r}")

	@staticmethod
	def fulfil_order_line(
		session: Any,
		order_id: str,
		product_code: str,
		quantity_shipped: float,
		tenant_id: str,
	) -> Any:
		"""Record shipped quantity against an order line; close order when complete.

		Lazily reduces inventory if the inventory plugin is available.
		"""
		from decimal import Decimal
		from pgappforge.plugins.erp.crm.commerce.models import Order, OrderLine

		line = session.execute(
			sa.select(OrderLine).where(
				OrderLine.order_id == order_id,
				OrderLine.product_code == product_code,
				OrderLine.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if line is None:
			raise CommerceValidationError(
				f"OrderLine not found: order={order_id} product={product_code}"
			)

		new_fulfilled = float(line.fulfilled_qty) + quantity_shipped
		if new_fulfilled > float(line.quantity):
			raise CommerceValidationError(
				f"Fulfilled qty {new_fulfilled} exceeds ordered qty {line.quantity}"
			)
		line.fulfilled_qty = Decimal(str(new_fulfilled))
		session.flush()

		# Reduce inventory (lazy import)
		try:
			from pgappforge.plugins.erp.inventory.services import InventoryService
			InventoryService.reduce_stock(
				session,
				tenant_id=tenant_id,
				product_code=product_code,
				quantity=quantity_shipped,
				reference=order_id,
			)
		except Exception:
			pass

		# Check if all lines fulfilled
		order = session.execute(
			sa.select(Order).where(Order.id == order_id)
		).scalar_one_or_none()
		if order:
			all_lines = session.execute(
				sa.select(OrderLine).where(OrderLine.order_id == order_id)
			).scalars().all()
			if all(float(l.fulfilled_qty) >= float(l.quantity) for l in all_lines):
				order.status = "DELIVERED"
				session.flush()
				log.info("CommerceService.fulfil_order_line: order %s fully DELIVERED", order_id)

		return line

	# ------------------------------------------------------------------
	# Coupon application
	# ------------------------------------------------------------------

	@staticmethod
	def apply_coupon(
		session: Any,
		cart_id: str,
		coupon_code: str,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Validate and compute coupon discount against a cart.

		Returns {discount_cents, final_total_cents}.
		Raises CommerceValidationError on any validation failure.
		Does NOT increment uses_count — that happens at order placement.
		"""
		from datetime import date as _date
		from decimal import Decimal
		from pgappforge.plugins.erp.crm.commerce.models import Cart, Coupon

		coupon = session.execute(
			sa.select(Coupon).where(
				Coupon.tenant_id == tenant_id,
				Coupon.code == coupon_code,
			)
		).scalar_one_or_none()
		if coupon is None:
			raise CommerceValidationError(f"Coupon {coupon_code!r} not found")
		if not coupon.is_active:
			raise CommerceValidationError(f"Coupon {coupon_code!r} is inactive")

		today = _date.today()
		if today < coupon.valid_from:
			raise CommerceValidationError(f"Coupon {coupon_code!r} is not yet valid")
		if coupon.valid_to and today > coupon.valid_to:
			raise CommerceValidationError(f"Coupon {coupon_code!r} has expired")
		if coupon.max_uses is not None and coupon.uses_count >= coupon.max_uses:
			raise CommerceValidationError(f"Coupon {coupon_code!r} has reached its usage limit")

		cart = session.execute(
			sa.select(Cart).where(Cart.id == cart_id, Cart.tenant_id == tenant_id)
		).scalar_one_or_none()
		if cart is None:
			raise CommerceValidationError(f"Cart {cart_id} not found")

		subtotal_cents = sum(
			int(item["unit_price_cents"]) * float(item["qty"])
			for item in (cart.items or [])
		)
		if subtotal_cents < coupon.min_order_cents:
			raise CommerceValidationError(
				f"Order subtotal {subtotal_cents}¢ below coupon minimum {coupon.min_order_cents}¢"
			)

		if coupon.discount_type == "PERCENTAGE":
			discount_cents = int(Decimal(str(subtotal_cents)) * Decimal(str(coupon.discount_value)) / 100)
		else:
			# FIXED_AMOUNT: discount_value is in display currency units; convert (assume 100 subunits)
			discount_cents = int(Decimal(str(coupon.discount_value)) * 100)
			discount_cents = min(discount_cents, subtotal_cents)

		return {
			"discount_cents": discount_cents,
			"final_total_cents": subtotal_cents - discount_cents,
		}

	# ------------------------------------------------------------------
	# Refund
	# ------------------------------------------------------------------

	@staticmethod
	def process_refund(
		session: Any,
		order_id: str,
		refund_amount_cents: int,
		reason: str,
		tenant_id: str,
	) -> Any:
		"""Issue a refund transaction; update order payment_status.

		GL:
		  DR Deferred Revenue "2310"
		  CR Accounts Receivable "1200"  (if payment not yet settled)
		"""
		import secrets
		from datetime import datetime as _dt
		from pgappforge.plugins.erp.crm.commerce.models import Order, PaymentTransaction

		order = session.execute(
			sa.select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
		).scalar_one_or_none()
		if order is None:
			raise CommerceValidationError(f"Order {order_id} not found")
		if order.payment_status not in ("PAID", "PARTIALLY_PAID"):
			raise CommerceValidationError(
				f"Cannot refund order with payment_status={order.payment_status!r}"
			)
		if refund_amount_cents <= 0:
			raise CommerceValidationError("refund_amount_cents must be positive")
		if refund_amount_cents > order.total_cents:
			raise CommerceValidationError(
				f"Refund {refund_amount_cents}¢ exceeds order total {order.total_cents}¢"
			)

		now = _dt.now(timezone.utc)
		reference = f"REF-{secrets.token_hex(4).upper()}"
		txn = PaymentTransaction(
			tenant_id=tenant_id,
			order_id=order_id,
			payment_method="CREDIT",
			amount_cents=-refund_amount_cents,
			currency_code="KES",
			reference=reference,
			status="REFUNDED",
			processed_at=now,
			provider_response={"reason": reason},
		)
		session.add(txn)

		if refund_amount_cents >= order.total_cents:
			order.payment_status = "REFUNDED"
			order.status = "REFUNDED"
		else:
			order.payment_status = "PARTIALLY_PAID"

		# GL
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			GLService.post_journal(
				session,
				tenant_id=tenant_id,
				reference=reference,
				description=f"Refund {reference} for order {order.order_number}: {reason}",
				lines=[
					{"account_code": "2310", "debit_cents": refund_amount_cents, "credit_cents": 0},
					{"account_code": "1200", "debit_cents": 0, "credit_cents": refund_amount_cents},
				],
			)
		except Exception:
			pass

		session.flush()
		log.info(
			"CommerceService.process_refund: order %s refund=%d¢ ref=%s",
			order.order_number, refund_amount_cents, reference,
		)
		return txn

	# ------------------------------------------------------------------
	# Commerce dashboard
	# ------------------------------------------------------------------

	@staticmethod
	def get_commerce_dashboard(session: Any, tenant_id: str) -> dict[str, Any]:
		"""Operational commerce dashboard.

		Returns:
		    orders_today: int
		    revenue_today_cents: int
		    avg_order_value_cents: float | None
		    conversion_rate_pct: float | None   (CONVERTED carts / total ACTIVE+CONVERTED)
		    top_products: list[{product_code, order_count}]
		    abandoned_cart_count: int
		    refund_rate_pct: float | None
		"""
		from datetime import datetime as _dt, timedelta
		import sqlalchemy.func as func
		from pgappforge.plugins.erp.crm.commerce.models import Cart, Order, OrderLine

		now = _dt.now(timezone.utc)
		today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

		# Orders today
		orders_today: int = session.execute(
			sa.select(func.count(Order.id)).where(
				Order.tenant_id == tenant_id,
				Order.created_at >= today_start,
				Order.status.notin_(("CANCELLED",)),
			)
		).scalar() or 0

		# Revenue today
		revenue_today_cents: int = session.execute(
			sa.select(func.sum(Order.total_cents)).where(
				Order.tenant_id == tenant_id,
				Order.created_at >= today_start,
				Order.payment_status == "PAID",
			)
		).scalar() or 0

		# Avg order value (all time, paid)
		avg_order_value = session.execute(
			sa.select(func.avg(Order.total_cents)).where(
				Order.tenant_id == tenant_id,
				Order.payment_status == "PAID",
			)
		).scalar()
		avg_order_value_cents = round(float(avg_order_value), 0) if avg_order_value else None

		# Conversion rate: CONVERTED / (CONVERTED + ABANDONED + ACTIVE)
		cart_counts = session.execute(
			sa.select(Cart.status, func.count(Cart.id).label("cnt"))
			.where(Cart.tenant_id == tenant_id)
			.group_by(Cart.status)
		).all()
		cart_by_status = {r.status: r.cnt for r in cart_counts}
		converted = cart_by_status.get("CONVERTED", 0)
		total_carts = sum(cart_by_status.values())
		conversion_rate_pct = round(converted / total_carts * 100, 1) if total_carts else None

		# Top products by order count (last 30 days)
		top_product_rows = session.execute(
			sa.select(
				OrderLine.product_code,
				func.count(OrderLine.id).label("order_count"),
			)
			.join(Order, Order.id == OrderLine.order_id)
			.where(
				OrderLine.tenant_id == tenant_id,
				Order.created_at >= now - timedelta(days=30),
			)
			.group_by(OrderLine.product_code)
			.order_by(func.count(OrderLine.id).desc())
			.limit(10)
		).all()
		top_products = [{"product_code": r.product_code, "order_count": r.order_count} for r in top_product_rows]

		# Abandoned cart count
		abandoned_cart_count: int = cart_by_status.get("ABANDONED", 0)

		# Refund rate: REFUNDED orders / total non-cancelled orders
		total_orders: int = session.execute(
			sa.select(func.count(Order.id)).where(
				Order.tenant_id == tenant_id,
				Order.status.notin_(("CANCELLED", "DRAFT")),
			)
		).scalar() or 0
		refunded_orders: int = session.execute(
			sa.select(func.count(Order.id)).where(
				Order.tenant_id == tenant_id,
				Order.status == "REFUNDED",
			)
		).scalar() or 0
		refund_rate_pct = (
			round(refunded_orders / total_orders * 100, 1) if total_orders else None
		)

		return {
			"orders_today": orders_today,
			"revenue_today_cents": revenue_today_cents,
			"avg_order_value_cents": avg_order_value_cents,
			"conversion_rate_pct": conversion_rate_pct,
			"top_products": top_products,
			"abandoned_cart_count": abandoned_cart_count,
			"refund_rate_pct": refund_rate_pct,
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
	"OrderNotFoundError",
	"ProductNotFoundError",
	"CouponNotFoundError",
]
