"""
ReportForge subscription runner.

Processes ReportSubscription rows where next_run_at <= now and is_active=True.
Each subscription gets its own personalised copy of the report delivered by email.

Called from scheduler.run_all().
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


from ._recurrence import next_occurrence as _next_occurrence


def _subscriber_email(user) -> str | None:
	"""Extract primary email from a FAB User object."""
	return getattr(user, "email", None)


def process_subscriptions(
	session=None,
	app: Any = None,
	limit: int = 100,
) -> int:
	"""
	Find all due ReportSubscription rows and send personalised reports.

	After a successful send, computes the next occurrence and updates
	next_run_at.  Deactivated subscriptions (is_active=False) are skipped.

	Returns number of subscriptions processed.
	"""
	from .models import ReportSubscription

	if session is None:
		from flask import current_app
		appbuilder = current_app.extensions.get("appbuilder")
		if not appbuilder:
			log.error("ReportForge subscriptions: appbuilder not found")
			return 0
		session = appbuilder.session

	if app is None:
		from flask import current_app
		app = current_app._get_current_object()

	import sqlalchemy as sa
	now = datetime.now(timezone.utc)

	due = session.execute(
		sa.select(ReportSubscription)
		.where(ReportSubscription.is_active == True)
		.where(ReportSubscription.next_run_at <= now)
		.order_by(ReportSubscription.next_run_at)
		.limit(limit)
	).scalars().all()

	if not due:
		log.debug("ReportForge subscriptions: nothing due at %s", now)
		return 0

	log.info("ReportForge subscriptions: %d due", len(due))
	from .dispatch import send_report_email, dispatch_now
	from .engine import ReportEngine
	from .models import ReportDispatch, DispatchStatus
	processed = 0

	for sub in due:
		try:
			report = sub.report
			user   = sub.user
			email  = _subscriber_email(user)
			if not email:
				log.warning("ReportForge subscriptions: sub id=%s — user has no email", sub.id)
				_advance(sub, now, session)
				continue

			params = sub.params_json or {}
			engine = ReportEngine(session)

			# Create a transient dispatch record for audit trail
			d = ReportDispatch(
				report_id=report.id,
				to_email=email,
				subject=f"Scheduled Report: {report.name}",
				export_format=sub.format or "pdf",
				params_json=params,
				status=DispatchStatus.PENDING,
				created_by=sub.user_id,
			)
			session.add(d)
			session.flush()

			dispatch_now(
				report=report,
				to_email=email,
				subject=d.subject,
				body_text=(
					f"Hi {getattr(user, 'first_name', '') or getattr(user, 'username', 'there')},\n\n"
					f"Please find your scheduled report '{report.name}' attached.\n\n"
					f"To unsubscribe, visit /reports/unsubscribe/{sub.id}."
				),
				export_format=sub.format or "pdf",
				params=params,
				engine=engine,
				session=session,
				app=app,
			)
			log.info(
				"ReportForge subscriptions: sent sub id=%s report=%r to %s",
				sub.id, report.name, email,
			)
		except Exception as exc:
			log.exception(
				"ReportForge subscriptions: sub id=%s failed: %s", sub.id, exc
			)
		finally:
			_advance(sub, now, session)
			processed += 1

	return processed


def _advance(sub, after_dt: datetime, session) -> None:
	"""Update sub.next_run_at to the next RRULE occurrence."""
	try:
		nxt = _next_occurrence(sub.frequency, after_dt)
		if nxt:
			sub.next_run_at = nxt
		else:
			# Rule exhausted — deactivate to avoid repeated processing
			sub.is_active = False
			log.info("ReportForge subscriptions: sub id=%s exhausted, deactivated", sub.id)
		session.commit()
	except Exception as exc:
		log.warning("ReportForge subscriptions: advance failed for sub id=%s: %s", sub.id, exc)
