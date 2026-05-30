"""
pgappforge/plugins/billing/engine.py

BillingEngine — the stateless service layer for the billing plugin.

All public methods accept a SQLAlchemy session as their first argument so they
compose cleanly with Flask-SQLAlchemy's scoped session, background workers, and
test fixtures without coupling to the request context.

Dunning schedule (days after first failure): 1, 3, 7, 14 → cancel.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .models import (
	Coupon,
	DiscountType,
	DunningAttempt,
	DunningStatus,
	Invoice,
	InvoiceItem,
	InvoiceStatus,
	Payment,
	PaymentStatus,
	Plan,
	Subscription,
	SubscriptionStatus,
	UsageRecord,
)

log = logging.getLogger(__name__)

# Dunning retry offsets from the day of the first failure
_DUNNING_SCHEDULE: dict[int, int] = {1: 1, 2: 3, 3: 7, 4: 14}
_DUNNING_MAX_ATTEMPTS: int = 4
# Warn about trial expiry when this many days remain
_TRIAL_WARN_DAYS: int = 3


class BillingError(Exception):
	"""Base exception for billing engine errors."""


class SubscriptionNotFound(BillingError):
	pass


class PlanNotFound(BillingError):
	pass


class CouponError(BillingError):
	pass


class BillingEngine:
	"""
	Stateless billing service.  Instantiate once and call methods with an
	explicit SQLAlchemy ``Session``.

	Args:
		stripe_secret_key: Optional Stripe secret key.  When provided and the
		    ``stripe`` package is available, methods that touch Stripe will make
		    live API calls; otherwise they operate in local-only mode.
		default_currency: ISO-4217 code, e.g. ``"USD"``.
	"""

	def __init__(
		self,
		stripe_secret_key: str | None = None,
		default_currency: str = "USD",
	) -> None:
		self._default_currency = default_currency.upper()
		self._stripe: Any = None

		if stripe_secret_key:
			try:
				import stripe as _stripe_mod
				_stripe_mod.api_key = stripe_secret_key
				self._stripe = _stripe_mod
				log.info("BillingEngine: Stripe client configured")
			except ImportError:
				log.warning(
					"BillingEngine: stripe_secret_key provided but `stripe` package "
					"is not installed — operating in local-only mode.  "
					"Install with: pip install stripe"
				)

	# ------------------------------------------------------------------
	# Subscription lifecycle
	# ------------------------------------------------------------------

	def start_trial(
		self,
		session: Session,
		tenant_id: int,
		plan_id: int,
		trial_days: int | None = None,
	) -> Subscription:
		"""
		Create a TRIALING subscription for a tenant.

		If *trial_days* is None the plan's ``trial_days`` value is used.
		Raises ``PlanNotFound`` if the plan does not exist or is inactive.
		"""
		plan = session.get(Plan, plan_id)
		if plan is None or not plan.is_active:
			raise PlanNotFound(f"Plan {plan_id} not found or inactive")

		days = trial_days if trial_days is not None else plan.trial_days
		now = datetime.now(timezone.utc)
		trial_end = now + timedelta(days=days) if days > 0 else None

		sub = Subscription(
			tenant_id=tenant_id,
			plan_id=plan_id,
			status=SubscriptionStatus.TRIALING.value,
			current_period_start=now,
			current_period_end=trial_end,
			trial_end=trial_end,
		)
		session.add(sub)
		session.flush()

		log.info(
			"BillingEngine.start_trial: tenant=%s plan=%s trial_days=%s sub=%s",
			tenant_id, plan_id, days, sub.id,
		)
		return sub

	def activate_subscription(
		self,
		session: Session,
		tenant_id: int,
		plan_id: int,
		payment_method_id: str,
	) -> Subscription:
		"""
		Create or transition an existing subscription to ACTIVE status.

		If a TRIALING subscription exists for the tenant+plan it is promoted;
		otherwise a fresh ACTIVE subscription is created.  ``payment_method_id``
		is forwarded to Stripe when the client is configured.
		"""
		plan = session.get(Plan, plan_id)
		if plan is None or not plan.is_active:
			raise PlanNotFound(f"Plan {plan_id} not found or inactive")

		# Promote existing trial if one exists
		existing = session.execute(
			select(Subscription).where(
				Subscription.tenant_id == tenant_id,
				Subscription.plan_id == plan_id,
				Subscription.status == SubscriptionStatus.TRIALING.value,
			)
		).scalar_one_or_none()

		now = datetime.now(timezone.utc)
		if plan.interval == "monthly":
			period_end = now + timedelta(days=30)
		elif plan.interval == "annual":
			period_end = now + timedelta(days=365)
		else:
			period_end = now + timedelta(days=30)

		if existing is not None:
			existing.status = SubscriptionStatus.ACTIVE.value
			existing.current_period_start = now
			existing.current_period_end = period_end
			existing.trial_end = None
			sub = existing
		else:
			sub = Subscription(
				tenant_id=tenant_id,
				plan_id=plan_id,
				status=SubscriptionStatus.ACTIVE.value,
				current_period_start=now,
				current_period_end=period_end,
			)
			session.add(sub)

		session.flush()

		# Stripe integration — attach payment method and create subscription
		if self._stripe is not None and plan.stripe_price_id:
			try:
				self._stripe_create_subscription(
					sub, plan.stripe_price_id, payment_method_id
				)
				session.flush()
			except Exception as exc:
				log.error("BillingEngine: Stripe subscription creation failed: %s", exc)

		log.info(
			"BillingEngine.activate_subscription: tenant=%s plan=%s sub=%s",
			tenant_id, plan_id, sub.id,
		)
		return sub

	def cancel_subscription(
		self,
		session: Session,
		subscription_id: int,
		at_period_end: bool = True,
	) -> Subscription:
		"""
		Cancel a subscription.

		When ``at_period_end=True`` (default) the subscription stays ACTIVE until
		``current_period_end`` and the ``cancel_at_period_end`` flag is set.
		When ``at_period_end=False`` the status is immediately set to CANCELED.
		"""
		sub = self._require_subscription(session, subscription_id)

		if at_period_end:
			sub.cancel_at_period_end = True
			log.info(
				"BillingEngine.cancel_subscription: sub=%s scheduled at period end",
				subscription_id,
			)
		else:
			sub.status = SubscriptionStatus.CANCELED.value
			sub.cancel_at_period_end = False
			log.info(
				"BillingEngine.cancel_subscription: sub=%s canceled immediately",
				subscription_id,
			)

		if self._stripe is not None and sub.stripe_subscription_id:
			try:
				self._stripe.Subscription.modify(
					sub.stripe_subscription_id,
					cancel_at_period_end=at_period_end,
				)
			except Exception as exc:
				log.error("BillingEngine: Stripe cancel failed: %s", exc)

		session.flush()
		return sub

	def pause_subscription(
		self,
		session: Session,
		subscription_id: int,
	) -> Subscription:
		"""Set subscription status to PAUSED.  Invoicing stops until resumed."""
		sub = self._require_subscription(session, subscription_id)
		sub.status = SubscriptionStatus.PAUSED.value
		session.flush()

		if self._stripe is not None and sub.stripe_subscription_id:
			try:
				self._stripe.Subscription.modify(
					sub.stripe_subscription_id,
					pause_collection={"behavior": "void"},
				)
			except Exception as exc:
				log.error("BillingEngine: Stripe pause failed: %s", exc)

		log.info("BillingEngine.pause_subscription: sub=%s paused", subscription_id)
		return sub

	def resume_subscription(
		self,
		session: Session,
		subscription_id: int,
	) -> Subscription:
		"""Resume a PAUSED subscription, restoring it to ACTIVE."""
		sub = self._require_subscription(session, subscription_id)
		if sub.status != SubscriptionStatus.PAUSED.value:
			raise BillingError(
				f"Subscription {subscription_id} is not paused (status={sub.status!r})"
			)

		sub.status = SubscriptionStatus.ACTIVE.value
		session.flush()

		if self._stripe is not None and sub.stripe_subscription_id:
			try:
				self._stripe.Subscription.modify(
					sub.stripe_subscription_id,
					pause_collection="",
				)
			except Exception as exc:
				log.error("BillingEngine: Stripe resume failed: %s", exc)

		log.info("BillingEngine.resume_subscription: sub=%s resumed", subscription_id)
		return sub

	# ------------------------------------------------------------------
	# Usage metering
	# ------------------------------------------------------------------

	def record_usage(
		self,
		session: Session,
		subscription_id: int,
		metric_name: str,
		quantity: float,
		metadata: dict[str, Any] | None = None,
	) -> UsageRecord:
		"""
		Record a metered usage event.

		``quantity`` is additive — callers record deltas, not running totals.
		``metadata`` is persisted as-is for audit; use it for request IDs,
		source endpoints, or any dimension useful for reconciliation.
		"""
		sub = self._require_subscription(session, subscription_id)
		record = UsageRecord(
			subscription_id=sub.id,
			metric_name=metric_name,
			quantity=quantity,
			recorded_at=datetime.now(timezone.utc),
			metadata=metadata or {},
		)
		session.add(record)
		session.flush()

		# Optionally forward to Stripe Metered Billing
		if (
			self._stripe is not None
			and sub.stripe_subscription_id
			and sub.plan
			and sub.plan.interval == "usage"
		):
			try:
				self._stripe.SubscriptionItem.create_usage_record(
					sub.stripe_subscription_id,
					quantity=int(quantity),
					timestamp=int(record.recorded_at.timestamp()),
					action="increment",
				)
			except Exception as exc:
				log.warning("BillingEngine: Stripe usage report failed: %s", exc)

		log.debug(
			"BillingEngine.record_usage: sub=%s metric=%r qty=%s",
			subscription_id, metric_name, quantity,
		)
		return record

	def get_usage_for_period(
		self,
		session: Session,
		subscription_id: int,
		metric_name: str,
		period_start: datetime | None = None,
		period_end: datetime | None = None,
	) -> float:
		"""
		Return the summed quantity of *metric_name* for the given period.

		If *period_start* / *period_end* are omitted the subscription's current
		billing period is used.
		"""
		sub = self._require_subscription(session, subscription_id)

		start = period_start or sub.current_period_start or datetime.min.replace(tzinfo=timezone.utc)
		end = period_end or sub.current_period_end or datetime.now(timezone.utc)

		result = session.execute(
			select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
				UsageRecord.subscription_id == subscription_id,
				UsageRecord.metric_name == metric_name,
				UsageRecord.recorded_at >= start,
				UsageRecord.recorded_at <= end,
			)
		).scalar()

		return float(result or 0)

	# ------------------------------------------------------------------
	# Invoicing
	# ------------------------------------------------------------------

	def generate_invoice(
		self,
		session: Session,
		subscription_id: int,
	) -> Invoice:
		"""
		Generate (or regenerate) the invoice for the current billing period.

		For fixed-interval plans a single line item is created for the plan price.
		For usage-based plans usage records in the current period are aggregated
		per metric and billed at the rate stored in ``plan.features["rates"]``
		(dict of metric → unit_price_cents).

		Returns the persisted Invoice in OPEN status.
		"""
		sub = self._require_subscription(session, subscription_id)
		plan: Plan = sub.plan

		# Void any existing DRAFT invoice for this period to avoid duplicates
		existing_draft = session.execute(
			select(Invoice).where(
				Invoice.subscription_id == subscription_id,
				Invoice.status == InvoiceStatus.DRAFT.value,
			)
		).scalar_one_or_none()
		if existing_draft is not None:
			existing_draft.status = InvoiceStatus.VOID.value

		now = datetime.now(timezone.utc)
		invoice = Invoice(
			subscription_id=subscription_id,
			status=InvoiceStatus.OPEN.value,
			currency=plan.currency if plan else self._default_currency,
			due_date=now + timedelta(days=14),
		)
		session.add(invoice)
		session.flush()  # get invoice.id

		total_cents = 0

		if plan and plan.interval != "usage":
			# Fixed-price line item
			item = InvoiceItem(
				invoice_id=invoice.id,
				description=f"{plan.name} ({plan.interval})",
				quantity=1,
				unit_price_cents=plan.price_cents,
				amount_cents=plan.price_cents,
			)
			session.add(item)
			total_cents += plan.price_cents
		elif plan and plan.interval == "usage":
			# Aggregate usage per metric and apply rates
			rates: dict[str, int] = (plan.features or {}).get("rates", {})
			period_start = sub.current_period_start or now
			period_end = sub.current_period_end or now

			# Get distinct metrics
			metrics = session.execute(
				select(UsageRecord.metric_name).where(
					UsageRecord.subscription_id == subscription_id,
					UsageRecord.recorded_at >= period_start,
					UsageRecord.recorded_at <= period_end,
				).distinct()
			).scalars().all()

			for metric in metrics:
				qty = self.get_usage_for_period(
					session, subscription_id, metric, period_start, period_end
				)
				unit_price = rates.get(metric, 0)
				amount = int(qty * unit_price)
				item = InvoiceItem(
					invoice_id=invoice.id,
					description=f"{metric} usage ({qty:.4g} units @ {unit_price/100:.4f}/unit)",
					quantity=int(qty),
					unit_price_cents=unit_price,
					amount_cents=amount,
				)
				session.add(item)
				total_cents += amount

		invoice.amount_cents = total_cents
		session.flush()

		log.info(
			"BillingEngine.generate_invoice: sub=%s invoice=%s amount=%s",
			subscription_id, invoice.id, total_cents,
		)
		return invoice

	# ------------------------------------------------------------------
	# Dunning
	# ------------------------------------------------------------------

	def process_dunning(self, session: Session) -> list[DunningAttempt]:
		"""
		Process the dunning queue: retry failed payments for PAST_DUE subscriptions.

		Schedule (days from first failure): 1 → 3 → 7 → 14 → cancel.

		Returns the list of DunningAttempt rows created or updated in this run.
		"""
		now = datetime.now(timezone.utc)

		# Subscriptions that are past-due and have overdue dunning steps
		due_attempts = session.execute(
			select(DunningAttempt).where(
				DunningAttempt.status == DunningStatus.PENDING.value,
				DunningAttempt.next_attempt_at <= now,
			)
		).scalars().all()

		processed: list[DunningAttempt] = []

		for attempt in due_attempts:
			sub = attempt.subscription
			if sub is None:
				sub = session.get(Subscription, attempt.subscription_id)

			if sub is None or sub.status != SubscriptionStatus.PAST_DUE.value:
				attempt.status = DunningStatus.SKIPPED.value
				processed.append(attempt)
				continue

			# Find the latest open invoice
			invoice = session.execute(
				select(Invoice).where(
					Invoice.subscription_id == sub.id,
					Invoice.status == InvoiceStatus.OPEN.value,
				).order_by(Invoice.created_at.desc())
			).scalar_one_or_none()

			success = False
			failure_reason: str | None = None

			if invoice is not None:
				success, failure_reason = self._attempt_payment(session, invoice)

			if success:
				attempt.status = DunningStatus.SENT.value
				sub.status = SubscriptionStatus.ACTIVE.value
				log.info(
					"BillingEngine.process_dunning: payment recovered sub=%s attempt=%s",
					sub.id, attempt.attempt_number,
				)
			else:
				attempt.status = DunningStatus.FAILED.value
				attempt.failure_reason = failure_reason

				next_attempt_number = attempt.attempt_number + 1
				if next_attempt_number <= _DUNNING_MAX_ATTEMPTS:
					days_offset = _DUNNING_SCHEDULE[next_attempt_number]
					first_failure = sub.updated_at or now
					next_at = first_failure + timedelta(days=days_offset)

					next_attempt = DunningAttempt(
						subscription_id=sub.id,
						attempt_number=next_attempt_number,
						attempted_at=now,
						status=DunningStatus.PENDING.value,
						next_attempt_at=next_at,
					)
					session.add(next_attempt)
					log.info(
						"BillingEngine.process_dunning: scheduled attempt %s for sub=%s at %s",
						next_attempt_number, sub.id, next_at,
					)
				else:
					# Exhausted retries — cancel the subscription
					sub.status = SubscriptionStatus.CANCELED.value
					log.warning(
						"BillingEngine.process_dunning: sub=%s canceled after %s failed attempts",
						sub.id, _DUNNING_MAX_ATTEMPTS,
					)

			attempt.attempted_at = now
			processed.append(attempt)

		session.flush()
		return processed

	def _attempt_payment(
		self, session: Session, invoice: Invoice
	) -> tuple[bool, str | None]:
		"""
		Attempt to charge the invoice.  Returns (success, failure_reason).

		In local-only mode this always returns (False, "no payment provider").
		When Stripe is configured it tries to confirm the PaymentIntent or
		create a new one for the invoice.
		"""
		payment = Payment(
			invoice_id=invoice.id,
			amount_cents=invoice.amount_cents,
			method="card",
			status=PaymentStatus.PENDING.value,
			attempted_at=datetime.now(timezone.utc),
		)
		session.add(payment)
		session.flush()

		if self._stripe is None:
			payment.status = PaymentStatus.FAILED.value
			payment.failure_reason = "no payment provider configured"
			return False, payment.failure_reason

		try:
			if invoice.stripe_invoice_id:
				result = self._stripe.Invoice.pay(invoice.stripe_invoice_id)
				succeeded = result.get("status") == "paid"
			else:
				# Attempt via PaymentIntent
				pi = self._stripe.PaymentIntent.create(
					amount=invoice.amount_cents,
					currency=invoice.currency.lower(),
					confirm=True,
				)
				succeeded = pi.get("status") == "succeeded"
				payment.stripe_payment_intent_id = pi.get("id")

			if succeeded:
				payment.status = PaymentStatus.SUCCEEDED.value
				invoice.status = InvoiceStatus.PAID.value
				invoice.paid_at = datetime.now(timezone.utc)
				return True, None
			else:
				payment.status = PaymentStatus.FAILED.value
				payment.failure_reason = "payment not confirmed by Stripe"
				return False, payment.failure_reason

		except Exception as exc:
			reason = str(exc)
			payment.status = PaymentStatus.FAILED.value
			payment.failure_reason = reason
			log.warning("BillingEngine._attempt_payment: Stripe error: %s", reason)
			return False, reason

	# ------------------------------------------------------------------
	# Coupons
	# ------------------------------------------------------------------

	def apply_coupon(
		self,
		session: Session,
		subscription_id: int,
		code: str,
	) -> dict[str, Any]:
		"""
		Validate and apply a coupon to the subscription's next invoice.

		Returns a dict with keys:
		  ``valid`` (bool), ``discount_cents`` (int), ``message`` (str).

		Does not persist anything — the discount_cents should be applied when
		generating the next invoice.
		"""
		sub = self._require_subscription(session, subscription_id)

		coupon = session.execute(
			select(Coupon).where(Coupon.code == code)
		).scalar_one_or_none()

		if coupon is None:
			return {"valid": False, "discount_cents": 0, "message": f"Coupon {code!r} not found"}

		if not coupon.is_valid:
			return {"valid": False, "discount_cents": 0, "message": "Coupon is expired or exhausted"}

		plan_name = sub.plan.name if sub.plan else ""
		if not coupon.applies_to_plan(plan_name):
			return {
				"valid": False,
				"discount_cents": 0,
				"message": f"Coupon {code!r} does not apply to plan {plan_name!r}",
			}

		# Find the latest OPEN invoice to compute discount
		invoice = session.execute(
			select(Invoice).where(
				Invoice.subscription_id == subscription_id,
				Invoice.status == InvoiceStatus.OPEN.value,
			).order_by(Invoice.created_at.desc())
		).scalar_one_or_none()

		base_amount = invoice.amount_cents if invoice else (sub.plan.price_cents if sub.plan else 0)
		discount = coupon.compute_discount_cents(base_amount)

		coupon.times_redeemed += 1
		session.flush()

		log.info(
			"BillingEngine.apply_coupon: sub=%s code=%r discount=%s cents",
			subscription_id, code, discount,
		)
		return {
			"valid": True,
			"discount_cents": discount,
			"message": f"Applied {code!r}: {discount/100:.2f} {sub.plan.currency if sub.plan else 'USD'} off",
		}

	# ------------------------------------------------------------------
	# Trial expiry warnings
	# ------------------------------------------------------------------

	def check_trial_expiry(
		self,
		session: Session,
		warn_days: int = _TRIAL_WARN_DAYS,
	) -> list[Subscription]:
		"""
		Return subscriptions whose trial ends within *warn_days* days.

		Callers are responsible for emitting notifications — this method only
		queries and returns the at-risk subscriptions.
		"""
		now = datetime.now(timezone.utc)
		cutoff = now + timedelta(days=warn_days)

		expiring = session.execute(
			select(Subscription).where(
				Subscription.status == SubscriptionStatus.TRIALING.value,
				Subscription.trial_end != None,  # noqa: E711
				Subscription.trial_end > now,
				Subscription.trial_end <= cutoff,
			)
		).scalars().all()

		log.debug(
			"BillingEngine.check_trial_expiry: %s subscriptions expiring within %s days",
			len(expiring), warn_days,
		)
		return list(expiring)

	# ------------------------------------------------------------------
	# Feature access
	# ------------------------------------------------------------------

	def check_feature_access(
		self,
		session: Session,
		subscription_id: int,
		feature_name: str,
	) -> bool:
		"""
		Return True if the subscription's plan grants access to *feature_name*.

		Checks ``plan.features[feature_name]``; returns False for inactive or
		non-existent subscriptions.
		"""
		sub = session.get(Subscription, subscription_id)
		if sub is None or not sub.is_active:
			return False
		plan = sub.plan
		if plan is None:
			return False
		return plan.has_feature(feature_name)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _require_subscription(self, session: Session, subscription_id: int) -> Subscription:
		sub = session.get(Subscription, subscription_id)
		if sub is None:
			raise SubscriptionNotFound(f"Subscription {subscription_id} not found")
		return sub

	def _stripe_create_subscription(
		self,
		sub: Subscription,
		stripe_price_id: str,
		payment_method_id: str,
	) -> None:
		"""Create a Stripe Subscription and store the ID on the local record."""
		assert self._stripe is not None
		result = self._stripe.Subscription.create(
			customer=None,  # caller should pre-create Stripe customer
			items=[{"price": stripe_price_id}],
			default_payment_method=payment_method_id,
			expand=["latest_invoice.payment_intent"],
		)
		sub.stripe_subscription_id = result["id"]


__all__ = [
	"BillingEngine",
	"BillingError",
	"SubscriptionNotFound",
	"PlanNotFound",
	"CouponError",
]
