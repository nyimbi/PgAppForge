"""
pgappforge/plugins/fintech/payments/scheduler.py

Standing Order Scheduler — batch runner for due StandingOrders.

Intended to be called from APScheduler, Celery beat, or any cron-like
mechanism.  Designed to be idempotent and safe under concurrent workers:
uses FOR UPDATE SKIP LOCKED to prevent double-execution.

Usage
-----
	from pgappforge.plugins.fintech.payments.scheduler import run_due_standing_orders

	# From an APScheduler job or Celery task:
	with db.session.begin():
		result = run_due_standing_orders(db.session, tenant_id="acme")
		# result = {"executed": N, "failed": M, "expired": K}
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def run_due_standing_orders(
	session: Session,
	tenant_id: str,
	event_bus: Callable[[Any], None] | None = None,
	as_of_date: date | None = None,
) -> dict[str, int]:
	"""Execute all ACTIVE StandingOrders whose next_execution_date <= as_of_date.

	Uses FOR UPDATE SKIP LOCKED so multiple workers can run concurrently
	without double-executing the same order.

	Parameters
	----------
	session:
		SQLAlchemy Session; caller owns commit/rollback.
	tenant_id:
		Multi-tenant discriminator; only processes orders for this tenant.
	event_bus:
		Optional callable forwarded to PaymentsService for event emission.
	as_of_date:
		Date to evaluate against; defaults to today.

	Returns
	-------
	dict with keys: executed, failed, expired.
	"""
	from .models import PayStandingOrder
	from .services import PaymentsService

	today = as_of_date or date.today()
	svc = PaymentsService(session, tenant_id=tenant_id, event_bus=event_bus)

	# Select due orders with row-level lock (SKIP LOCKED = safe for parallel workers)
	due_orders = session.execute(
		sa.select(PayStandingOrder)
		.where(
			PayStandingOrder.tenant_id == tenant_id,
			PayStandingOrder.status == "ACTIVE",
			PayStandingOrder.next_execution_date <= today,
		)
		.with_for_update(skip_locked=True)
	).scalars().all()

	executed = 0
	failed = 0
	expired = 0

	for so in due_orders:
		# Check expiry first
		if so.end_date and so.next_execution_date > so.end_date:
			session.execute(
				sa.update(PayStandingOrder)
				.where(PayStandingOrder.id == so.id)
				.values(status="EXPIRED")
			)
			session.flush()
			expired += 1
			log.info(
				"run_due_standing_orders: %s expired (end_date=%s)",
				so.reference_number, so.end_date,
			)
			continue

		try:
			svc.execute_standing_order(str(so.id), execution_date=today)
			executed += 1
			log.info(
				"run_due_standing_orders: executed %s on %s",
				so.reference_number, today,
			)
		except Exception as exc:
			failed += 1
			log.warning(
				"run_due_standing_orders: execution failed for %s: %s",
				so.reference_number, exc,
			)

			# Increment failure counter
			new_total_failed = (so.total_failed or 0) + 1
			session.execute(
				sa.update(PayStandingOrder)
				.where(PayStandingOrder.id == so.id)
				.values(total_failed=new_total_failed)
			)
			session.flush()

			# Emit failure event
			try:
				from .events import StandingOrderFailedEvent
				if event_bus is not None:
					event_bus(StandingOrderFailedEvent(
						tenant_id=tenant_id,
						standing_order_id=str(so.id),
						reference_number=so.reference_number,
						execution_date=str(today),
						amount_cents=so.amount_cents,
						failure_reason=str(exc),
						total_failed=new_total_failed,
						will_retry=True,
					))
			except Exception as emit_exc:
				log.warning(
					"run_due_standing_orders: event emit failed (non-fatal): %s", emit_exc
				)

		# Check if next execution date would be past end_date → expire
		if so.end_date:
			# Re-read updated next_execution_date after execute_standing_order
			session.expire(so)
			refreshed = session.get(PayStandingOrder, so.id)
			if refreshed and refreshed.next_execution_date and refreshed.next_execution_date > refreshed.end_date:
				session.execute(
					sa.update(PayStandingOrder)
					.where(PayStandingOrder.id == so.id)
					.values(status="EXPIRED")
				)
				session.flush()
				expired += 1
				log.info(
					"run_due_standing_orders: %s expired after execution (end_date=%s)",
					so.reference_number, so.end_date,
				)

	log.info(
		"run_due_standing_orders: tenant=%s date=%s executed=%d failed=%d expired=%d",
		tenant_id, today, executed, failed, expired,
	)
	return {"executed": executed, "failed": failed, "expired": expired}


__all__ = ["run_due_standing_orders"]
