"""
ReportForge scheduled dispatch runner.

Processes:
1. One-shot ReportDispatch rows with status='scheduled' whose scheduled_at has passed.
2. Recurring dispatches: after a successful send, if recurrence_rule (RRULE) is set,
   computes next_run_at and re-queues with status='scheduled'.
3. ReportSubscription rows (via subscriptions.process_subscriptions).

Usage (Celery)::

    from pgappforge.plugins.reports.scheduler import run_all

    @celery.task
    def reportforge_tick():
        from flask import current_app
        with current_app.app_context():
            count = run_all()
            return f"Processed {count} items"

Usage (simple cron / Flask CLI)::

    from pgappforge.plugins.reports.scheduler import run_all
    count = run_all()

Usage (Flask CLI)::

    flask reportforge run-scheduled
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


from ._recurrence import next_occurrence as _compute_next_rrule


def process_scheduled_dispatches(
	session=None,
	app: Any = None,
	limit: int = 50,
) -> int:
	"""
	Find and send all scheduled ReportDispatch rows whose time has arrived.

	After a successful send:
	- If dispatch.recurrence_rule is set, computes next_run_at via RRULE and
	  re-queues the same dispatch row with status=SCHEDULED.
	- Otherwise sets status=SENT (already done by dispatch_now).

	Returns number of dispatches attempted.
	"""
	from .models import ReportDispatch, DispatchStatus

	if session is None:
		from flask import current_app
		appbuilder = current_app.extensions.get("appbuilder")
		if not appbuilder:
			log.error("ReportForge scheduler: appbuilder not found")
			return 0
		session = appbuilder.session

	if app is None:
		from flask import current_app
		app = current_app._get_current_object()

	import sqlalchemy as sa
	now = datetime.now(timezone.utc)
	due: list[ReportDispatch] = (
		session.execute(
			sa.select(ReportDispatch)
			.where(ReportDispatch.status == DispatchStatus.SCHEDULED)
			.where(ReportDispatch.scheduled_at <= now)
			.order_by(ReportDispatch.scheduled_at)
			.limit(limit)
		).scalars().all()
	)

	if not due:
		log.debug("ReportForge scheduler: no dispatches due at %s", now)
		return 0

	log.info("ReportForge scheduler: %d dispatches due", len(due))
	from .dispatch import dispatch_now
	from .engine import ReportEngine
	processed = 0

	for d in due:
		try:
			report = d.report
			engine = ReportEngine(session)
			dispatch_now(
				report=report,
				to_email=d.to_email,
				subject=d.subject,
				body_text=d.body_text or "",
				export_format=d.export_format or "pdf",
				params=d.params_json or {},
				engine=engine,
				session=session,
				app=app,
			)
			log.info("ReportForge scheduler: sent dispatch id=%s to %s", d.id, d.to_email)

			# ── RRULE recurrence: re-queue if rule defined ────────────────
			if d.recurrence_rule:
				after = d.scheduled_at or datetime.now(timezone.utc)
				next_dt = _compute_next_rrule(d.recurrence_rule, after)
				if next_dt:
					d.scheduled_at = next_dt
					d.next_run_at  = next_dt
					d.status       = DispatchStatus.SCHEDULED
					d.sent_at      = None
					d.error_message = None
					session.commit()
					log.info(
						"ReportForge scheduler: re-queued dispatch id=%s next=%s",
						d.id, next_dt,
					)
				else:
					log.info(
						"ReportForge scheduler: RRULE exhausted for dispatch id=%s", d.id
					)

		except Exception as exc:
			log.exception("ReportForge scheduler: dispatch id=%s failed: %s", d.id, exc)
		processed += 1

	return processed


def run_all(session=None, app: Any = None) -> int:
	"""
	Run the full scheduler tick:
	1. process_scheduled_dispatches
	2. subscriptions.process_subscriptions

	Call this once per scheduler tick (e.g. every 5 minutes from Celery beat).
	"""
	count = 0
	count += process_scheduled_dispatches(session=session, app=app)
	from .subscriptions import process_subscriptions
	count += process_subscriptions(session=session, app=app)
	return count
