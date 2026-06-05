"""
pgappforge/plugins/rules/scheduler.py

Rules Engine scheduler — fires rules on cron schedules.

Rules with trigger_type="schedule" and a schedule_cron expression are
evaluated periodically against all matching records in their target model.

Usage (in app factory):
    from pgappforge.plugins.rules.scheduler import RulesScheduler
    scheduler = RulesScheduler(app, appbuilder)
    scheduler.start()  # adds jobs for all scheduled rulesets
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

try:
	from apscheduler.schedulers.background import BackgroundScheduler
	from apscheduler.triggers.cron import CronTrigger
	_APSCHEDULER_AVAILABLE = True
except ImportError:
	_APSCHEDULER_AVAILABLE = False


class RulesScheduler:
	"""APScheduler integration that fires scheduled rulesets on cron expressions.

	Each RuleSet with trigger_type="schedule" and a non-null schedule_cron
	column gets its own BackgroundScheduler job.  The job queries ALL records
	of the ruleset's target model and calls engine.evaluate() for each one
	using the synthetic "on_schedule" event.

	Parameters
	----------
	app:
	    Flask application instance.
	appbuilder:
	    AppBuilder instance (used to obtain the SQLAlchemy session).
	"""

	def __init__(self, app: Any, appbuilder: Any) -> None:
		self._app = app
		self._appbuilder = appbuilder
		self._scheduler: Any = None  # BackgroundScheduler or None

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def start(self) -> None:
		"""Scan for scheduled rulesets and register APScheduler jobs.

		No-op (with a warning) if APScheduler is not installed.
		"""
		if not _APSCHEDULER_AVAILABLE:
			log.warning(
				"RulesScheduler: APScheduler is not installed — "
				"scheduled rules will not fire.  "
				"Install it with: pip install apscheduler"
			)
			return

		self._scheduler = BackgroundScheduler()

		rulesets = self._load_scheduled_rulesets()
		for rs in rulesets:
			self._add_job(rs)

		self._scheduler.start()
		log.info(
			"RulesScheduler: started with %d scheduled ruleset(s)",
			len(rulesets),
		)

	def stop(self) -> None:
		"""Gracefully shut down the scheduler and remove all jobs."""
		if self._scheduler is not None:
			try:
				self._scheduler.shutdown(wait=False)
				log.info("RulesScheduler: stopped")
			except Exception as exc:
				log.warning("RulesScheduler: error during shutdown: %s", exc)
			self._scheduler = None

	def update_schedule(self, ruleset_id: int) -> None:
		"""Re-sync the APScheduler job for a ruleset whose cron changed.

		Called automatically by the auto-invalidation hook when a RuleSet row
		is updated.  Removes the old job (if any) and adds a fresh one if
		the ruleset still has a valid cron expression.
		"""
		if self._scheduler is None:
			return

		job_id = self._job_id(ruleset_id)

		# Remove existing job (ignore if it was never registered)
		try:
			self._scheduler.remove_job(job_id)
			log.debug("RulesScheduler: removed stale job %r", job_id)
		except Exception:
			pass

		# Reload the ruleset and re-add if still schedulable
		rs = self._get_ruleset(ruleset_id)
		if rs is not None and getattr(rs, "schedule_cron", None) and rs.enabled:
			self._add_job(rs)
			log.info(
				"RulesScheduler: re-registered job for ruleset %r (cron=%r)",
				rs.name, rs.schedule_cron,
			)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _job_id(ruleset_id: int) -> str:
		return f"rules_scheduler_{ruleset_id}"

	def _add_job(self, ruleset: Any) -> None:
		"""Register a BackgroundScheduler job for one RuleSet."""
		if self._scheduler is None:
			return
		cron = ruleset.schedule_cron
		try:
			trigger = CronTrigger.from_crontab(cron)
		except Exception as exc:
			log.error(
				"RulesScheduler: invalid cron %r for ruleset %r — skipping: %s",
				cron, ruleset.name, exc,
			)
			return

		self._scheduler.add_job(
			func=self._run_ruleset,
			trigger=trigger,
			id=self._job_id(ruleset.id),
			args=[ruleset.id],
			replace_existing=True,
			misfire_grace_time=60,
		)
		log.info(
			"RulesScheduler: registered job for ruleset %r id=%d cron=%r",
			ruleset.name, ruleset.id, cron,
		)

	def _load_scheduled_rulesets(self) -> list:
		"""Query all enabled rulesets that have trigger_type='schedule' and a cron."""
		from .models import RuleSet
		from sqlalchemy import select

		try:
			session = self._appbuilder.get_session
			rows = session.execute(
				select(RuleSet).filter(
					RuleSet.enabled.is_(True),
					RuleSet.schedule_cron.isnot(None),
				)
			).scalars().all()
			# Restrict to those that actually have rules with trigger_type="schedule"
			# (the RuleSet itself doesn't carry trigger_type; that lives on Rule).
			# We include any ruleset that has a schedule_cron set on the ruleset row.
			return list(rows)
		except Exception as exc:
			log.error("RulesScheduler: could not load scheduled rulesets: %s", exc)
			return []

	def _get_ruleset(self, ruleset_id: int) -> Any | None:
		"""Fetch a single RuleSet by id; returns None on error."""
		from .models import RuleSet
		from sqlalchemy import select

		try:
			session = self._appbuilder.get_session
			return session.execute(
				select(RuleSet).where(RuleSet.id == ruleset_id)
			).scalar_one_or_none()
		except Exception as exc:
			log.error("RulesScheduler: _get_ruleset(%d) failed: %s", ruleset_id, exc)
			return None

	def _run_ruleset(self, ruleset_id: int) -> None:
		"""APScheduler job function.

		Loads the RuleSet, resolves its target model class, iterates ALL
		records, and calls engine.evaluate(..., "on_schedule", record) for
		each.  Updates schedule_last_run on completion.

		Runs inside the Flask application context so that Flask-SQLAlchemy
		and other extensions are available.
		"""
		with self._app.app_context():
			self._run_ruleset_inner(ruleset_id)

	def _run_ruleset_inner(self, ruleset_id: int) -> None:
		from .engine import get_rules_engine
		from .models import RuleSet
		from sqlalchemy import select

		session = self._appbuilder.get_session
		rs = session.execute(
			select(RuleSet).where(RuleSet.id == ruleset_id)
		).scalar_one_or_none()

		if rs is None:
			log.warning("RulesScheduler: ruleset id=%d not found — skipping", ruleset_id)
			return
		if not rs.enabled:
			log.debug("RulesScheduler: ruleset %r disabled — skipping", rs.name)
			return

		model_name = rs.model_name
		log.info(
			"RulesScheduler: running scheduled ruleset %r (id=%d) for model %r",
			rs.name, ruleset_id, model_name,
		)

		# Resolve the target model class
		from .engine import _resolve_model_class
		model_cls = _resolve_model_class(model_name)
		if model_cls is None:
			log.error(
				"RulesScheduler: cannot resolve model %r for ruleset %r — aborting",
				model_name, rs.name,
			)
			return

		# Query all records for the target model
		try:
			records = session.execute(select(model_cls)).scalars().all()
		except Exception as exc:
			log.error(
				"RulesScheduler: could not query model %r: %s", model_name, exc
			)
			return

		engine = get_rules_engine()
		executed = skipped = errors = 0

		for record in records:
			try:
				engine.evaluate(model_name, "on_schedule", record, session=session)
				executed += 1
			except Exception as exc:
				# RulesValidationError on a scheduled job is unexpected but non-fatal
				log.warning(
					"RulesScheduler: evaluate error for record id=%s in ruleset %r: %s",
					getattr(record, "id", "?"), rs.name, exc,
				)
				errors += 1

		# Update last-run timestamp
		try:
			rs.schedule_last_run = datetime.now(timezone.utc)
			session.flush()
		except Exception as exc:
			log.warning("RulesScheduler: could not update schedule_last_run: %s", exc)

		log.info(
			"RulesScheduler: ruleset %r done — executed=%d skipped=%d errors=%d",
			rs.name, executed, skipped, errors,
		)
