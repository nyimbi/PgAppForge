"""
pgappforge/plugins/erp/crm/subscriptions/services.py

SubscriptionService — all subscription lifecycle operations.

Design rules:
  - Synchronous (Flask/SQLAlchemy context — no asyncio here).
  - All monetary amounts: integer cents.
  - SQLAlchemy 2.x patterns: select() + session.execute().scalar_one_or_none().
  - Emit domain events within the same session (atomic with business mutation).
  - BPM action registrations at module level.

Billing interval → period_end computation
-----------------------------------------
  WEEKLY     : + 7 * interval_count days
  MONTHLY    : + interval_count months   (dateutil.relativedelta)
  QUARTERLY  : + 3 * interval_count months
  ANNUALLY   : + 12 * interval_count months
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SubscriptionServiceError(Exception):
	"""Base error for the subscriptions service layer."""


class SubscriptionNotFoundError(SubscriptionServiceError):
	"""Raised when a subscription cannot be located by ID + tenant."""


class SubscriptionStateError(SubscriptionServiceError):
	"""Raised when an operation is invalid given the subscription's current status."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _add_months(d: date, months: int) -> date:
	"""Add *months* calendar months to *d* without importing dateutil at module level."""
	try:
		from dateutil.relativedelta import relativedelta
		return d + relativedelta(months=months)
	except ImportError:
		# Fallback: clamp to last day of target month
		import calendar
		month = d.month - 1 + months
		year = d.year + month // 12
		month = month % 12 + 1
		day = min(d.day, calendar.monthrange(year, month)[1])
		return date(year, month, day)


def _compute_period_end(start: date, billing_interval: str, billing_interval_count: int) -> date:
	"""Compute the exclusive end date of one billing period."""
	interval = (billing_interval or "MONTHLY").upper()
	count = max(1, billing_interval_count or 1)
	if interval == "WEEKLY":
		from datetime import timedelta
		return start + timedelta(days=7 * count)
	elif interval == "MONTHLY":
		return _add_months(start, count)
	elif interval == "QUARTERLY":
		return _add_months(start, 3 * count)
	elif interval == "ANNUALLY":
		return _add_months(start, 12 * count)
	else:
		# Unknown interval — default to monthly
		log.warning("Unknown billing_interval %r — defaulting to monthly", billing_interval)
		return _add_months(start, count)


def _effective_price_cents(plan: Any, quantity: int, discount_pct: Decimal) -> int:
	"""Return the invoiceable amount in cents after quantity and discount."""
	gross = plan.base_price_cents * max(1, quantity)
	if discount_pct and discount_pct > 0:
		gross = int(gross * (1 - discount_pct / Decimal("100")))
	return max(0, gross)


def _next_invoice_ref(tenant_id: str, session: Any) -> str:
	"""Generate a sequential invoice reference: INV-{tenant_prefix}-{seq}."""
	from pgappforge.plugins.erp.crm.subscriptions.models import SubscriptionInvoice
	count = session.execute(
		sa.select(sa.func.count()).select_from(SubscriptionInvoice)
		.where(SubscriptionInvoice.tenant_id == tenant_id)
	).scalar() or 0
	prefix = str(tenant_id)[:8].upper()
	return f"INV-{prefix}-{count + 1:06d}"


# ---------------------------------------------------------------------------
# SubscriptionService
# ---------------------------------------------------------------------------

class SubscriptionService:
	"""All subscription lifecycle operations.

	Every method takes an explicit SQLAlchemy *session* — no global scoped
	session.  Callers are responsible for commit/rollback.

	Methods never commit; they session.add() and session.flush() so that
	emitted events include the PK of the newly created row.
	"""

	# ------------------------------------------------------------------ #
	# create_subscription                                                  #
	# ------------------------------------------------------------------ #

	def create_subscription(
		self,
		customer_id: str,
		plan_id: str,
		tenant_id: str,
		session: Any,
		*,
		quantity: int = 1,
		trial_override_days: int | None = None,
		discount_pct: Decimal = Decimal("0"),
		entity_id: str | None = None,
	) -> Any:
		"""Create and persist a new Subscription.

		If the plan has trial_days > 0 (or trial_override_days is set), the
		subscription starts in TRIALING status and the trial_end date is set.
		Otherwise it starts ACTIVE and current_period_end is computed from
		the billing interval.

		Returns the persisted Subscription instance (not yet committed).
		"""
		from pgappforge.plugins.erp.crm.subscriptions.models import Subscription, SubscriptionPlan
		from pgappforge.plugins.erp.crm.subscriptions.events import SubscriptionCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		plan = session.execute(
			sa.select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
		).scalar_one_or_none()
		if plan is None:
			raise SubscriptionNotFoundError(f"SubscriptionPlan {plan_id!r} not found")
		if not plan.is_active:
			raise SubscriptionStateError(f"Plan {plan.plan_code!r} is not active")

		today = date.today()
		trial_days = trial_override_days if trial_override_days is not None else plan.trial_days

		if trial_days and trial_days > 0:
			from datetime import timedelta
			trial_end = today + timedelta(days=trial_days)
			current_period_start = today
			current_period_end = trial_end
			status = "TRIALING"
		else:
			trial_end = None
			current_period_start = today
			current_period_end = _compute_period_end(
				today, plan.billing_interval, plan.billing_interval_count
			)
			status = "ACTIVE"

		sub = Subscription(
			id=_uuid4(),
			tenant_id=tenant_id,
			customer_id=customer_id,
			plan_id=plan_id,
			status=status,
			current_period_start=current_period_start,
			current_period_end=current_period_end,
			trial_end=trial_end,
			cancel_at_period_end=False,
			quantity=max(1, quantity),
			discount_pct=discount_pct,
			entity_id=entity_id,
		)
		session.add(sub)
		session.flush()

		emit_event(
			SubscriptionCreatedEvent(
				aggregate_id=sub.id,
				aggregate_type="Subscription",
				tenant_id=tenant_id,
				sub_id=sub.id,
				customer_id=customer_id,
				plan_id=plan_id,
			),
			session,
		)
		log.info(
			"Subscription created id=%s customer=%s plan=%s status=%s",
			sub.id, customer_id, plan.plan_code, status,
		)
		return sub

	# ------------------------------------------------------------------ #
	# activate_subscription                                                #
	# ------------------------------------------------------------------ #

	def activate_subscription(self, sub_id: str, session: Any) -> Any:
		"""Transition a TRIALING subscription to ACTIVE.

		Computes a fresh current_period_end from the plan's billing interval
		starting from today (the activation date).

		Raises SubscriptionStateError if the subscription is not in TRIALING.
		"""
		from pgappforge.plugins.erp.crm.subscriptions.models import Subscription, SubscriptionPlan
		from pgappforge.plugins.erp.crm.subscriptions.events import SubscriptionActivatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == sub_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {sub_id!r} not found")
		if sub.status != "TRIALING":
			raise SubscriptionStateError(
				f"activate_subscription requires TRIALING status; got {sub.status!r}"
			)

		plan = session.execute(
			sa.select(SubscriptionPlan).where(SubscriptionPlan.id == sub.plan_id)
		).scalar_one_or_none()

		today = date.today()
		sub.current_period_start = today
		if plan is not None:
			sub.current_period_end = _compute_period_end(
				today, plan.billing_interval, plan.billing_interval_count
			)
		else:
			# Plan was deleted; fallback to one month
			sub.current_period_end = _add_months(today, 1)

		sub.status = "ACTIVE"
		session.flush()

		emit_event(
			SubscriptionActivatedEvent(
				aggregate_id=sub.id,
				aggregate_type="Subscription",
				tenant_id=str(sub.tenant_id),
				sub_id=sub.id,
				customer_id=sub.customer_id,
				current_period_end=sub.current_period_end.isoformat(),
			),
			session,
		)
		log.info("Subscription %s activated; period_end=%s", sub.id, sub.current_period_end)
		return sub

	# ------------------------------------------------------------------ #
	# renew_subscription                                                   #
	# ------------------------------------------------------------------ #

	def renew_subscription(self, sub_id: str, session: Any) -> Any:
		"""Renew a single ACTIVE subscription.

		Steps:
		  1. Load subscription + plan.
		  2. If cancel_at_period_end is True → set CANCELLED and return.
		  3. Attempt to "charge" — in the absence of a payment gateway the
		     service always succeeds here; integrate payment by overriding
		     _attempt_charge().
		  4. If charge succeeds: advance period, create SubscriptionInvoice,
		     emit SubscriptionRenewedEvent + InvoiceGeneratedEvent.
		  5. If charge fails: set PAST_DUE, emit SubscriptionPastDueEvent.

		Raises SubscriptionStateError if status != ACTIVE.
		"""
		from pgappforge.plugins.erp.crm.subscriptions.models import (
			Subscription, SubscriptionPlan, SubscriptionInvoice,
		)
		from pgappforge.plugins.erp.crm.subscriptions.events import (
			SubscriptionRenewedEvent, InvoiceGeneratedEvent, SubscriptionPastDueEvent,
			SubscriptionCancelledEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == sub_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {sub_id!r} not found")
		if sub.status != "ACTIVE":
			raise SubscriptionStateError(
				f"renew_subscription requires ACTIVE status; got {sub.status!r}"
			)

		# Handle scheduled cancellation
		if sub.cancel_at_period_end:
			sub.status = "CANCELLED"
			sub.cancelled_at = datetime.now(timezone.utc)
			session.flush()
			emit_event(
				SubscriptionCancelledEvent(
					aggregate_id=sub.id,
					aggregate_type="Subscription",
					tenant_id=str(sub.tenant_id),
					sub_id=sub.id,
					customer_id=sub.customer_id,
					cancel_reason=sub.cancel_reason or "cancel_at_period_end",
				),
				session,
			)
			log.info("Subscription %s cancelled at period end", sub.id)
			return sub

		plan = session.execute(
			sa.select(SubscriptionPlan).where(SubscriptionPlan.id == sub.plan_id)
		).scalar_one_or_none()

		amount_cents = (
			_effective_price_cents(plan, sub.quantity, sub.discount_pct)
			if plan is not None
			else 0
		)

		# Attempt payment (extensible — override _attempt_charge for real gateway)
		charge_ok = self._attempt_charge(sub, plan, amount_cents, session)

		if not charge_ok:
			sub.status = "PAST_DUE"
			session.flush()
			emit_event(
				SubscriptionPastDueEvent(
					aggregate_id=sub.id,
					aggregate_type="Subscription",
					tenant_id=str(sub.tenant_id),
					sub_id=sub.id,
					customer_id=sub.customer_id,
					amount_owed_cents=amount_cents,
				),
				session,
			)
			log.warning("Subscription %s renewal failed — set PAST_DUE", sub.id)
			return sub

		# Advance billing period
		old_period_end = sub.current_period_end
		if plan is not None:
			new_period_end = _compute_period_end(
				old_period_end, plan.billing_interval, plan.billing_interval_count
			)
		else:
			new_period_end = _add_months(old_period_end, 1)

		sub.current_period_start = old_period_end
		sub.current_period_end = new_period_end
		session.flush()

		# Create invoice
		invoice_ref = _next_invoice_ref(str(sub.tenant_id), session)
		invoice = SubscriptionInvoice(
			id=_uuid4(),
			tenant_id=sub.tenant_id,
			subscription_id=sub.id,
			customer_id=sub.customer_id,
			invoice_ref=invoice_ref,
			amount_cents=amount_cents,
			currency_code=plan.currency_code if plan else "KES",
			status="OPEN",
			due_date=old_period_end,
			period_start=sub.current_period_start,
			period_end=sub.current_period_end,
			line_items=[
				{
					"description": f"{plan.name if plan else 'Subscription'} — {old_period_end} to {new_period_end}",
					"quantity": sub.quantity,
					"unit_price_cents": plan.base_price_cents if plan else 0,
					"total_cents": amount_cents,
				}
			],
		)
		session.add(invoice)
		session.flush()

		# Mirror to AR sub-ledger so aging, dunning, credit exposure are updated
		try:
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice
			ar_inv = ARInvoice(
				tenant_id=sub.tenant_id,
				customer_id=sub.customer_id,
				invoice_number=invoice_ref,
				invoice_type="SUBSCRIPTION",
				invoice_date=date.today(),
				due_date=old_period_end,
				subtotal_cents=amount_cents,
				tax_cents=0,
				total_cents=amount_cents,
				balance_due_cents=amount_cents,
				status="ISSUED",
				currency_code=plan.currency_code if plan else "KES",
				description=f"Subscription renewal {invoice_ref}",
			)
			session.add(ar_inv)
			session.flush()
		except ImportError:
			log.debug("renew_subscription: AR plugin not loaded; AR invoice skipped")
		except Exception as ar_exc:
			log.warning("renew_subscription: AR invoice creation failed: %s", ar_exc)

		emit_event(
			SubscriptionRenewedEvent(
				aggregate_id=sub.id,
				aggregate_type="Subscription",
				tenant_id=str(sub.tenant_id),
				sub_id=sub.id,
				customer_id=sub.customer_id,
				amount_cents=amount_cents,
				period_end=new_period_end.isoformat(),
			),
			session,
		)
		emit_event(
			InvoiceGeneratedEvent(
				aggregate_id=invoice.id,
				aggregate_type="SubscriptionInvoice",
				tenant_id=str(sub.tenant_id),
				invoice_id=invoice.id,
				sub_id=sub.id,
				amount_cents=amount_cents,
				due_date=invoice.due_date.isoformat(),
			),
			session,
		)
		log.info(
			"Subscription %s renewed; new period_end=%s invoice=%s amount=%d",
			sub.id, new_period_end, invoice_ref, amount_cents,
		)
		return sub

	def _attempt_charge(
		self,
		sub: Any,
		plan: Any,
		amount_cents: int,
		session: Any,
	) -> bool:
		"""Attempt to charge for renewal.

		Default implementation always returns True (no payment gateway wired).
		Override this method or register a payment handler via subscribe() on
		the crm.subscriptions.charge_requested event to integrate a gateway.
		"""
		return True

	# ------------------------------------------------------------------ #
	# change_plan                                                          #
	# ------------------------------------------------------------------ #

	def change_plan(
		self,
		sub_id: str,
		new_plan_id: str,
		session: Any,
		*,
		prorate: bool = True,
	) -> Any:
		"""Change a subscription's plan.

		Determines whether the change is an upgrade or downgrade by comparing
		monthly-equivalent prices.  If prorate=True, computes a credit for the
		remaining days of the current billing period and creates a credit invoice.

		The subscription's plan_id is updated immediately (mid-cycle change).
		"""
		from pgappforge.plugins.erp.crm.subscriptions.models import (
			Subscription, SubscriptionPlan, SubscriptionInvoice,
		)
		from pgappforge.plugins.erp.crm.subscriptions.events import (
			SubscriptionUpgradedEvent, SubscriptionDowngradedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == sub_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {sub_id!r} not found")
		if sub.status not in ("ACTIVE", "TRIALING", "PAST_DUE"):
			raise SubscriptionStateError(
				f"change_plan is not allowed in status {sub.status!r}"
			)

		old_plan_id = str(sub.plan_id) if sub.plan_id else ""
		if old_plan_id == new_plan_id:
			raise SubscriptionServiceError("New plan is the same as current plan")

		old_plan = session.execute(
			sa.select(SubscriptionPlan).where(SubscriptionPlan.id == old_plan_id)
		).scalar_one_or_none() if old_plan_id else None

		new_plan = session.execute(
			sa.select(SubscriptionPlan).where(SubscriptionPlan.id == new_plan_id)
		).scalar_one_or_none()
		if new_plan is None:
			raise SubscriptionNotFoundError(f"SubscriptionPlan {new_plan_id!r} not found")
		if not new_plan.is_active:
			raise SubscriptionStateError(f"Plan {new_plan.plan_code!r} is not active")

		old_monthly = old_plan.monthly_equivalent_cents() if old_plan else 0
		new_monthly = new_plan.monthly_equivalent_cents()
		is_upgrade = new_monthly > old_monthly

		# Proration: credit for remaining days in current period
		if prorate and old_plan is not None:
			today = date.today()
			period_end = sub.current_period_end
			period_start = sub.current_period_start
			total_days = max(1, (period_end - period_start).days)
			remaining_days = max(0, (period_end - today).days)
			old_period_price = _effective_price_cents(old_plan, sub.quantity, sub.discount_pct)
			credit_cents = int(old_period_price * remaining_days / total_days)

			if credit_cents > 0:
				invoice_ref = _next_invoice_ref(str(sub.tenant_id), session)
				credit_invoice = SubscriptionInvoice(
					id=_uuid4(),
					tenant_id=sub.tenant_id,
					subscription_id=sub.id,
					customer_id=sub.customer_id,
					invoice_ref=invoice_ref,
					amount_cents=-credit_cents,   # negative = credit
					currency_code=old_plan.currency_code,
					status="OPEN",
					due_date=today,
					period_start=today,
					period_end=period_end,
					line_items=[
						{
							"description": f"Proration credit: {old_plan.name} unused {remaining_days} days",
							"quantity": 1,
							"unit_price_cents": -credit_cents,
							"total_cents": -credit_cents,
						}
					],
				)
				session.add(credit_invoice)

		sub.plan_id = new_plan_id
		session.flush()

		event_kwargs = dict(
			aggregate_id=sub.id,
			aggregate_type="Subscription",
			tenant_id=str(sub.tenant_id),
			sub_id=sub.id,
			customer_id=sub.customer_id,
			old_plan_id=old_plan_id,
			new_plan_id=new_plan_id,
		)
		if is_upgrade:
			emit_event(SubscriptionUpgradedEvent(**event_kwargs), session)
			log.info("Subscription %s upgraded %s → %s", sub.id, old_plan_id, new_plan_id)
		else:
			emit_event(SubscriptionDowngradedEvent(**event_kwargs), session)
			log.info("Subscription %s downgraded %s → %s", sub.id, old_plan_id, new_plan_id)

		return sub

	# ------------------------------------------------------------------ #
	# cancel_subscription                                                  #
	# ------------------------------------------------------------------ #

	def cancel_subscription(
		self,
		sub_id: str,
		session: Any,
		*,
		cancel_reason: str = "",
		immediate: bool = False,
	) -> Any:
		"""Cancel a subscription.

		immediate=False (default): sets cancel_at_period_end=True; the
		subscription remains ACTIVE until the next renewal run cancels it.

		immediate=True: sets status=CANCELLED and cancelled_at=now().

		Raises SubscriptionStateError if the subscription is already CANCELLED
		or EXPIRED.
		"""
		from pgappforge.plugins.erp.crm.subscriptions.models import Subscription
		from pgappforge.plugins.erp.crm.subscriptions.events import SubscriptionCancelledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == sub_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {sub_id!r} not found")
		if sub.status in ("CANCELLED", "EXPIRED"):
			raise SubscriptionStateError(
				f"Subscription {sub_id!r} is already {sub.status}"
			)

		sub.cancel_reason = cancel_reason or sub.cancel_reason

		if immediate:
			sub.status = "CANCELLED"
			sub.cancelled_at = datetime.now(timezone.utc)
			sub.cancel_at_period_end = False
		else:
			sub.cancel_at_period_end = True

		session.flush()

		emit_event(
			SubscriptionCancelledEvent(
				aggregate_id=sub.id,
				aggregate_type="Subscription",
				tenant_id=str(sub.tenant_id),
				sub_id=sub.id,
				customer_id=sub.customer_id,
				cancel_reason=cancel_reason,
			),
			session,
		)
		mode = "immediate" if immediate else "at_period_end"
		log.info("Subscription %s cancelled (%s) reason=%r", sub.id, mode, cancel_reason)
		return sub

	# ------------------------------------------------------------------ #
	# process_renewals                                                     #
	# ------------------------------------------------------------------ #

	def process_renewals(
		self,
		session: Any,
		*,
		tenant_id: str | None = None,
	) -> dict[str, Any]:
		"""Batch renewal job — renew all ACTIVE subscriptions due today.

		Finds every ACTIVE subscription where current_period_end <= today,
		then calls renew_subscription() for each.  Errors per subscription
		are caught and collected rather than aborting the entire batch.

		Returns:
		  {
		    "renewed": N,       # successfully renewed
		    "past_due": M,      # payment failed → PAST_DUE
		    "cancelled": K,     # cancel_at_period_end hit
		    "errors": [...],    # list of {sub_id, error} dicts
		  }
		"""
		from pgappforge.plugins.erp.crm.subscriptions.models import Subscription

		today = date.today()
		query = (
			sa.select(Subscription)
			.where(Subscription.status == "ACTIVE")
			.where(Subscription.current_period_end <= today)
		)
		if tenant_id:
			query = query.where(Subscription.tenant_id == tenant_id)

		subs = session.execute(query).scalars().all()
		renewed = 0
		past_due = 0
		cancelled = 0
		errors: list[dict] = []

		for sub in subs:
			try:
				self.renew_subscription(sub.id, session)
				# sub is already mutated in-session by renew_subscription — no extra query
				if sub.status == "PAST_DUE":
					past_due += 1
				elif sub.status == "CANCELLED":
					cancelled += 1
				else:
					renewed += 1
			except Exception as exc:
				log.error("process_renewals: error on sub %s: %s", sub.id, exc)
				errors.append({"sub_id": sub.id, "error": str(exc)})

		log.info(
			"process_renewals: renewed=%d past_due=%d cancelled=%d errors=%d",
			renewed, past_due, cancelled, len(errors),
		)
		return {"renewed": renewed, "past_due": past_due, "cancelled": cancelled, "errors": errors}

	# ------------------------------------------------------------------ #
	# get_mrr                                                              #
	# ------------------------------------------------------------------ #

	def get_mrr(self, tenant_id: str, session: Any) -> dict[str, Any]:
		"""Compute MRR (Monthly Recurring Revenue) for the tenant.

		Iterates all ACTIVE subscriptions and converts each plan's price to a
		monthly equivalent using the billing interval.

		Returns:
		  {
		    "mrr_cents": int,               total monthly recurring revenue
		    "arr_cents": int,               annualised (mrr * 12)
		    "subscription_count": int,      active subscription count
		    "churn_rate_pct": Decimal,      CANCELLED in last 30 days / start-of-month active
		    "new_mrr_cents": int,           subs created in last 30 days
		    "expansion_mrr_cents": int,     subs upgraded in last 30 days (placeholder)
		  }
		"""
		from pgappforge.plugins.erp.crm.subscriptions.models import Subscription, SubscriptionPlan

		rows = session.execute(
			sa.select(Subscription, SubscriptionPlan)
			.outerjoin(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
			.where(Subscription.tenant_id == tenant_id)
			.where(Subscription.status == "ACTIVE")
		).all()

		mrr_cents = 0
		for sub, plan in rows:
			if plan is None:
				continue
			monthly = plan.monthly_equivalent_cents()
			# Apply quantity and discount
			monthly_effective = _effective_price_cents(plan, sub.quantity, sub.discount_pct)
			# Scale monthly_effective to per-month equivalent
			interval = (plan.billing_interval or "MONTHLY").upper()
			count = max(1, plan.billing_interval_count or 1)
			if interval == "WEEKLY":
				mrr_cents += int(Fraction(monthly_effective * 52, 12 * count))
			elif interval == "MONTHLY":
				mrr_cents += monthly_effective // count
			elif interval == "QUARTERLY":
				mrr_cents += monthly_effective // (3 * count)
			elif interval == "ANNUALLY":
				mrr_cents += monthly_effective // (12 * count)
			else:
				mrr_cents += monthly_effective

		sub_count = len(rows)
		arr_cents = mrr_cents * 12

		# Churn: subscriptions cancelled in last 30 days / active count at start of window
		from datetime import timedelta
		thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
		cancelled_count = session.execute(
			sa.select(sa.func.count())
			.select_from(Subscription)
			.where(Subscription.tenant_id == tenant_id)
			.where(Subscription.status == "CANCELLED")
			.where(Subscription.cancelled_at >= thirty_days_ago)
		).scalar() or 0

		# Active count 30 days ago (approximation: current active + recently cancelled)
		base_count = sub_count + cancelled_count
		churn_rate_pct = (
			Decimal(str(round(cancelled_count / base_count * 100, 2)))
			if base_count > 0
			else Decimal("0")
		)

		# New MRR: subscriptions created in last 30 days (uses created_on from AuditMixin)
		new_subs = session.execute(
			sa.select(Subscription, SubscriptionPlan)
			.outerjoin(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
			.where(Subscription.tenant_id == tenant_id)
			.where(Subscription.status == "ACTIVE")
			.where(Subscription.created_on >= thirty_days_ago)
		).all()
		new_mrr_cents = 0
		for sub, plan in new_subs:
			if plan:
				new_mrr_cents += _effective_price_cents(plan, sub.quantity, sub.discount_pct)

		return {
			"mrr_cents": mrr_cents,
			"arr_cents": arr_cents,
			"subscription_count": sub_count,
			"churn_rate_pct": churn_rate_pct,
			"new_mrr_cents": new_mrr_cents,
			"expansion_mrr_cents": 0,  # populated by analytics plugin when available
		}

	# ------------------------------------------------------------------ #
	# record_usage                                                         #
	# ------------------------------------------------------------------ #

	def record_usage(
		self,
		sub_id: str,
		metric_name: str,
		quantity: Decimal | int | float,
		period: str,
		session: Any,
	) -> Any:
		"""Upsert a metered usage record for (subscription, metric, period).

		If a record already exists it is incremented by *quantity*; otherwise a
		new row is created.  Returns the SubscriptionUsage row.

		quantity should be a Decimal for precision; int/float are accepted and
		coerced.
		"""
		from pgappforge.plugins.erp.crm.subscriptions.models import Subscription, SubscriptionUsage

		sub = session.execute(
			sa.select(Subscription).where(Subscription.id == sub_id)
		).scalar_one_or_none()
		if sub is None:
			raise SubscriptionNotFoundError(f"Subscription {sub_id!r} not found")

		qty = Decimal(str(quantity))

		existing = session.execute(
			sa.select(SubscriptionUsage)
			.where(SubscriptionUsage.subscription_id == sub_id)
			.where(SubscriptionUsage.metric_name == metric_name)
			.where(SubscriptionUsage.period == period)
		).scalar_one_or_none()

		if existing is not None:
			existing.quantity = existing.quantity + qty
			existing.recorded_at = datetime.now(timezone.utc)
			session.flush()
			return existing

		usage = SubscriptionUsage(
			id=_uuid4(),
			tenant_id=sub.tenant_id,
			subscription_id=sub_id,
			metric_name=metric_name,
			period=period,
			quantity=qty,
			recorded_at=datetime.now(timezone.utc),
		)
		session.add(usage)
		session.flush()
		return usage

	# ------------------------------------------------------------------ #
	# get_customer_subscriptions                                           #
	# ------------------------------------------------------------------ #

	def get_customer_subscriptions(
		self,
		customer_id: str,
		tenant_id: str,
		session: Any,
	) -> list[Any]:
		"""Return all subscriptions for a customer within a tenant, newest first."""
		from pgappforge.plugins.erp.crm.subscriptions.models import Subscription

		rows = session.execute(
			sa.select(Subscription)
			.where(Subscription.customer_id == customer_id)
			.where(Subscription.tenant_id == tenant_id)
			.order_by(Subscription.current_period_start.desc())
		).scalars().all()
		return list(rows)


# ---------------------------------------------------------------------------
# BPM Action Registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register(
		"crm.subscriptions.create",
		"Create subscription from workflow",
	)
	def _bpm_create_subscription(
		record_ctx: dict,
		session: Any,
		customer_id: str = "",
		plan_id: str = "",
		tenant_id: str = "",
		quantity: int = 1,
		trial_override_days: int | None = None,
		discount_pct: str = "0",
		entity_id: str | None = None,
		**kw: Any,
	) -> dict:
		_tenant = tenant_id or record_ctx.get("tenant_id", "")
		try:
			svc = SubscriptionService()
			sub = svc.create_subscription(
				customer_id=customer_id,
				plan_id=plan_id,
				tenant_id=_tenant,
				session=session,
				quantity=quantity,
				trial_override_days=trial_override_days,
				discount_pct=Decimal(discount_pct),
				entity_id=entity_id,
			)
			return {"status": "ok", "sub_id": sub.id, "sub_status": sub.status}
		except Exception as exc:
			log.warning("bpm crm.subscriptions.create failed: %s", exc)
			return {"status": "error", "message": str(exc)}

	@_BPMReg.register(
		"crm.subscriptions.cancel",
		"Cancel subscription from workflow",
	)
	def _bpm_cancel_subscription(
		record_ctx: dict,
		session: Any,
		sub_id: str = "",
		cancel_reason: str = "",
		immediate: bool = False,
		**kw: Any,
	) -> dict:
		try:
			svc = SubscriptionService()
			sub = svc.cancel_subscription(
				sub_id=sub_id,
				session=session,
				cancel_reason=cancel_reason,
				immediate=immediate,
			)
			return {"status": "ok", "sub_id": sub.id, "sub_status": sub.status}
		except Exception as exc:
			log.warning("bpm crm.subscriptions.cancel failed: %s", exc)
			return {"status": "error", "message": str(exc)}

	@_BPMReg.register(
		"crm.subscriptions.change_plan",
		"Change subscription plan from workflow",
	)
	def _bpm_change_plan(
		record_ctx: dict,
		session: Any,
		sub_id: str = "",
		new_plan_id: str = "",
		prorate: bool = True,
		**kw: Any,
	) -> dict:
		try:
			svc = SubscriptionService()
			sub = svc.change_plan(
				sub_id=sub_id,
				new_plan_id=new_plan_id,
				session=session,
				prorate=prorate,
			)
			return {"status": "ok", "sub_id": sub.id, "plan_id": str(sub.plan_id)}
		except Exception as exc:
			log.warning("bpm crm.subscriptions.change_plan failed: %s", exc)
			return {"status": "error", "message": str(exc)}

except ImportError:
	log.debug(
		"pgappforge.plugins.workflow not available — "
		"crm.subscriptions BPM actions not registered"
	)


__all__ = [
	"SubscriptionService",
	"SubscriptionServiceError",
	"SubscriptionNotFoundError",
	"SubscriptionStateError",
]
