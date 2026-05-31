"""
ReportForge scheduled dispatch runner.

Processes ReportDispatch rows with status='scheduled' whose scheduled_at
has passed. Call this from a Celery beat task, a cron job, or pgappforge's
built-in job runner.

Usage (Celery)::

    from pgappforge.plugins.reports.scheduler import process_scheduled_dispatches

    @celery.task
    def reportforge_scheduled():
        from flask import current_app
        with current_app.app_context():
            count = process_scheduled_dispatches()
            return f"Processed {count} dispatches"

Usage (simple cron / Flask CLI)::

    # In your app factory or CLI command:
    from pgappforge.plugins.reports.scheduler import process_scheduled_dispatches
    count = process_scheduled_dispatches()

Usage (Flask CLI command added automatically by the plugin)::

    flask reportforge run-scheduled
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def process_scheduled_dispatches(
	session=None,
	app: Any = None,
	limit: int = 50,
) -> int:
	"""
	Find and send all scheduled ReportDispatch rows whose time has arrived.

	Args:
	    session: SQLAlchemy session. If None, obtained from Flask app context.
	    app: Flask app instance. If None, obtained from Flask current_app.
	    limit: Maximum dispatches to process in one call (prevents runaway).

	Returns:
	    Number of dispatches attempted (sent + failed).
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
			report  = d.report
			engine  = ReportEngine(session)
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
		except Exception as exc:
			log.exception("ReportForge scheduler: dispatch id=%s failed: %s", d.id, exc)
		processed += 1

	return processed
