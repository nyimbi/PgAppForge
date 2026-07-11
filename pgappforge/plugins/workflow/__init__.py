"""
pgappforge/plugins/workflow/__init__.py

Business Process Management (BPM) plugin for pgAppForge.

Enabling
--------
Add to your Flask config::

    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.workflow"]

Or instantiate directly::

    from pgappforge.plugins.workflow import create_plugin
    plugin = create_plugin(appbuilder)
    plugin.activate()

Config keys
-----------
WORKFLOW_MAX_CHAIN_DEPTH    : int  (default 10)
    Maximum sequential steps allowed in a single process definition.

WORKFLOW_INSTANCE_TTL_DAYS  : int  (default 90)
    Days before completed/cancelled instances are archived.

WORKFLOW_ASYNC_BACKEND      : "sync" | "thread" | "celery"  (default "sync")
    Backend for running escalation checks.
    "celery" requires the celery package; "thread" uses concurrent.futures.

WORKFLOW_NOTIFICATION_EMAIL : bool  (default True)
    Send e-mail notifications on step assignment and completion.

WORKFLOW_ESCALATION_CHECK_INTERVAL : int  (default 3600)
    Seconds between automatic escalation sweeps (thread / APScheduler backend).

Public surface
--------------
WorkflowPlugin, create_plugin          — plugin lifecycle
WorkflowEngine                          — core state machine
WorkflowMixin                           — model mixin
ProcessDefinition, ProcessStep,
ProcessInstance, ProcessEvent           — SQLAlchemy models
bpm_api                                 — Flask Blueprint with REST API
ProcessDefinitionView, ProcessStepView,
ProcessInstanceView, ProcessDashboardView,
ProcessTimelineView, ProcessQueueView   — FAB views
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .engine import WorkflowEngine
from .mixin import WorkflowMixin
from .models import ProcessDefinition, ProcessEvent, ProcessInstance, ProcessStep
# Views imported lazily inside register_views() to avoid circular import at collection time

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy-dep guards
# ---------------------------------------------------------------------------

try:
	from celery import Celery as _Celery  # noqa: F401
	HAS_CELERY = True
except ImportError:
	HAS_CELERY = False


# ---------------------------------------------------------------------------
# WorkflowPlugin
# ---------------------------------------------------------------------------


class WorkflowPlugin(BasePlugin):
	"""
	Full BPM plugin for pgAppForge.

	Lifecycle
	---------
	1. initialize()   — connect on_record_save hook; optionally start escalation timer
	2. register_views() — mount all views and the REST API blueprint under "Workflows"
	3. deactivate()   — disconnect hooks, stop background timer

	on_record_save hook
	-------------------
	When a model that has WorkflowMixin.WORKFLOW_DEFINITION set is saved for the
	first time (is_new=True) and has no active instance, the plugin automatically
	starts the named process.  This enables zero-code workflow triggering — just
	add the mixin and set WORKFLOW_DEFINITION on your model class.
	"""

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="workflow",
			version="1.0.0",
			description=(
				"Full BPM system: process definitions, step tracking, "
				"time/escalation, handoff audit trail, form analytics, "
				"dashboard, queue, and REST API."
			),
			author="pgAppForge Contributors",
			tags=["bpm", "workflow", "approval", "process", "escalation"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_workflow_design",
				"can_workflow_approve",
				"can_workflow_monitor",
				"can_workflow_admin",
			],
			safe_mode_compatible=True,
			example_config={
				"WORKFLOW_MAX_CHAIN_DEPTH": 10,
				"WORKFLOW_INSTANCE_TTL_DAYS": 90,
				"WORKFLOW_ASYNC_BACKEND": "sync",
				"WORKFLOW_NOTIFICATION_EMAIL": True,
				"WORKFLOW_ESCALATION_CHECK_INTERVAL": 3600,
			},
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Connect hook receivers and optionally start the escalation timer."""
		hooks = getattr(self.appbuilder, "hooks", None)
		if hooks is not None:
			if hasattr(hooks, "on_record_save"):
				hooks.on_record_save.connect(self._on_record_save)
			if hasattr(hooks, "on_user_login"):
				hooks.on_user_login.connect(self._on_user_login)
			log.debug("WorkflowPlugin: hook receivers connected")
		else:
			log.warning(
				"WorkflowPlugin: appbuilder.hooks not present — "
				"automatic workflow triggering disabled. "
				"Call engine.start_process() explicitly."
			)

		backend = self.config.get("WORKFLOW_ASYNC_BACKEND", "sync")
		if backend == "thread":
			self._start_escalation_thread()
		elif backend == "celery":
			log.info(
				"WorkflowPlugin: using Celery backend — register "
				"workflow.tasks.escalate_overdue_task as a beat task."
			)

	def configure(self, config: dict[str, Any]) -> None:
		self.config.update(config)
		self._validate_config()

	def deactivate(self) -> bool:
		"""Disconnect hooks and stop background timer."""
		hooks = getattr(self.appbuilder, "hooks", None)
		if hooks is not None:
			if hasattr(hooks, "on_record_save"):
				try:
					hooks.on_record_save.disconnect(self._on_record_save)
				except Exception:
					pass
			if hasattr(hooks, "on_user_login"):
				try:
					hooks.on_user_login.disconnect(self._on_user_login)
				except Exception:
					pass

		self._stop_escalation_thread()
		return super().deactivate()

	# ------------------------------------------------------------------
	# View registration
	# ------------------------------------------------------------------

	def register_views(self) -> None:
		"""Mount all BPM views and the REST API blueprint."""
		from .views import (
			ProcessDashboardView,
			ProcessDefinitionView,
			ProcessInstanceView,
			ProcessQueueView,
			ProcessStepView,
			ProcessTimelineView,
			bpm_api,
		)
		category = "Workflows"
		category_icon = "fa-sitemap"

		self.add_view(
			ProcessDashboardView,
			"BPM Dashboard",
			icon="fa-dashboard",
			category=category,
			category_icon=category_icon,
		)
		self.add_view(
			ProcessQueueView,
			"My Queue",
			icon="fa-inbox",
			category=category,
		)
		self.add_view(
			ProcessDefinitionView,
			"Process Definitions",
			icon="fa-cogs",
			category=category,
		)
		self.add_view(
			ProcessStepView,
			"Process Steps",
			icon="fa-list-ol",
			category=category,
		)
		self.add_view(
			ProcessInstanceView,
			"All Instances",
			icon="fa-tasks",
			category=category,
		)
		# Timeline is navigated to via links; no menu entry needed
		self.add_view_no_menu(ProcessTimelineView)

		# Register the REST API blueprint
		try:
			app = getattr(self.appbuilder, "get_app", None) or getattr(self.appbuilder, "app", None)
			if app is not None:
				app.register_blueprint(bpm_api)
				log.info("WorkflowPlugin: bpm_api blueprint registered at /bpm/api")
			else:
				log.warning("WorkflowPlugin: could not resolve Flask app to register bpm_api blueprint")
		except Exception as exc:
			log.error("WorkflowPlugin: failed to register bpm_api blueprint: %s", exc)

		log.info("WorkflowPlugin: all views registered")

	# ------------------------------------------------------------------
	# Model registration (for Alembic autogenerate)
	# ------------------------------------------------------------------

	def register_models(self) -> list:
		return [ProcessDefinition, ProcessStep, ProcessInstance, ProcessEvent]

	# ------------------------------------------------------------------
	# Hook overrides
	# ------------------------------------------------------------------

	def on_record_save(self, model_class: type, record: Any, is_new: bool) -> None:
		"""
		Auto-start a workflow when a WorkflowMixin model is first saved and
		WORKFLOW_DEFINITION is set on the class.
		"""
		from .mixin import WorkflowMixin as _WFMixin
		if not isinstance(record, _WFMixin):
			return
		defn_name: str | None = getattr(model_class, "WORKFLOW_DEFINITION", None)
		if not defn_name:
			return
		if not is_new:
			return

		record_id = getattr(record, "id", None)
		if record_id is None:
			log.warning(
				"WorkflowPlugin.on_record_save: %s has no 'id' after save — "
				"cannot start workflow automatically.",
				model_class.__name__,
			)
			return

		try:
			session = self._get_session()
			eng = WorkflowEngine(session)

			# Don't start a second instance if one already exists
			existing = eng.get_instance_for_record(model_class.__name__, record_id)
			if existing is not None:
				return

			from sqlalchemy import select as _select
			defn = session.execute(
				_select(ProcessDefinition).where(ProcessDefinition.name == defn_name)
			).scalar_one_or_none()
			if defn is None:
				log.warning(
					"WorkflowPlugin.on_record_save: ProcessDefinition %r not found — "
					"skipping auto-start for %s#%s.",
					defn_name, model_class.__name__, record_id,
				)
				return

			inst = eng.start_process(
				definition_id=defn.id,
				model_name=model_class.__name__,
				record_id=record_id,
			)
			session.commit()
			log.info(
				"WorkflowPlugin: auto-started ProcessInstance #%d for %s#%s (def=%r)",
				inst.id, model_class.__name__, record_id, defn_name,
			)
		except Exception:
			log.exception(
				"WorkflowPlugin.on_record_save: unhandled error for %s#%s",
				model_class.__name__, record_id,
			)

	def on_user_login(self, user: Any) -> None:
		"""Cache pending queue depth in the Flask session for navbar badge."""
		try:
			from flask import session as flask_session
			eng = WorkflowEngine(self._get_session())
			roles: list[str] = [r.name for r in getattr(user, "roles", [])]
			count = 0
			seen: set[int] = set()
			for role in roles:
				for inst in eng.get_queue(role):
					if inst.id not in seen:
						count += 1
						seen.add(inst.id)
			flask_session["bpm_my_queue_count"] = count
		except Exception:
			log.debug("WorkflowPlugin.on_user_login: could not cache queue count", exc_info=True)

	# ------------------------------------------------------------------
	# Config schema
	# ------------------------------------------------------------------

	def get_config_schema(self) -> dict:
		return {
			"$schema": "https://json-schema.org/draft/2020-12/schema",
			"title": "WorkflowPlugin Configuration",
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"WORKFLOW_MAX_CHAIN_DEPTH": {
					"type": "integer",
					"minimum": 1,
					"maximum": 100,
					"default": 10,
					"description": "Maximum sequential steps per process definition.",
				},
				"WORKFLOW_INSTANCE_TTL_DAYS": {
					"type": "integer",
					"minimum": 1,
					"default": 90,
					"description": "Days before completed/cancelled instances are archived.",
				},
				"WORKFLOW_ASYNC_BACKEND": {
					"type": "string",
					"enum": ["sync", "thread", "celery"],
					"default": "sync",
					"description": "Backend for escalation sweeps.",
				},
				"WORKFLOW_NOTIFICATION_EMAIL": {
					"type": "boolean",
					"default": True,
					"description": "Send e-mail on step assignment and completion.",
				},
				"WORKFLOW_ESCALATION_CHECK_INTERVAL": {
					"type": "integer",
					"minimum": 60,
					"default": 3600,
					"description": "Seconds between escalation sweeps (thread backend).",
				},
			},
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _on_record_save(self, model_class: type, record: Any, is_new: bool) -> None:
		try:
			self.on_record_save(model_class, record, is_new)
		except Exception:
			log.exception("WorkflowPlugin._on_record_save raised unexpectedly")

	def _on_user_login(self, user: Any) -> None:
		try:
			self.on_user_login(user)
		except Exception:
			log.exception("WorkflowPlugin._on_user_login raised unexpectedly")

	def _get_session(self):
		"""Resolve the SQLAlchemy session from the appbuilder or Flask-SQLAlchemy."""
		# AppBuilder exposes get_session as a property in FAB
		sess = getattr(self.appbuilder, "get_session", None)
		if sess is not None:
			return sess
		try:
			from pgappforge import db  # type: ignore[attr-defined]
			return db.session
		except Exception:
			pass
		try:
			from flask import current_app
			db = current_app.extensions["sqlalchemy"]
			return db.session
		except Exception as exc:
			raise RuntimeError(
				"WorkflowPlugin: cannot resolve SQLAlchemy session"
			) from exc

	def _start_escalation_thread(self) -> None:
		"""Start a background thread that calls escalate_overdue() periodically."""
		import threading

		interval = int(self.config.get("WORKFLOW_ESCALATION_CHECK_INTERVAL", 3600))
		self._escalation_stop = threading.Event()

		def _loop() -> None:
			log.info("WorkflowPlugin: escalation thread started (interval=%ds)", interval)
			while not self._escalation_stop.wait(timeout=interval):
				try:
					app = (
						getattr(self.appbuilder, "get_app", None)
						or getattr(self.appbuilder, "app", None)
					)
					ctx = app.app_context() if app else None
					if ctx:
						with ctx:
							eng = WorkflowEngine(self._get_session())
							events = eng.escalate_overdue()
							if events:
								eng.session.commit()
								log.info(
									"WorkflowPlugin: escalation sweep created %d event(s)",
									len(events),
								)
					else:
						eng = WorkflowEngine(self._get_session())
						events = eng.escalate_overdue()
						if events:
							eng.session.commit()
				except Exception:
					log.exception("WorkflowPlugin: escalation sweep failed")
			log.info("WorkflowPlugin: escalation thread stopped")

		self._escalation_thread = threading.Thread(target=_loop, daemon=True, name="bpm-escalation")
		self._escalation_thread.start()

	def _stop_escalation_thread(self) -> None:
		stop_event = getattr(self, "_escalation_stop", None)
		if stop_event is not None:
			stop_event.set()

	def _validate_config(self) -> None:
		depth = self.config.get("WORKFLOW_MAX_CHAIN_DEPTH", 10)
		if not isinstance(depth, int) or depth < 1:
			raise ValueError("WORKFLOW_MAX_CHAIN_DEPTH must be a positive integer")

		backend = self.config.get("WORKFLOW_ASYNC_BACKEND", "sync")
		if backend not in ("sync", "thread", "celery"):
			raise ValueError(
				f"WORKFLOW_ASYNC_BACKEND must be 'sync', 'thread', or 'celery', got {backend!r}"
			)

		if backend == "celery" and not HAS_CELERY:
			log.warning(
				"WorkflowPlugin: WORKFLOW_ASYNC_BACKEND='celery' but celery is "
				"not installed — install it with: pip install celery"
			)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_plugin(
	appbuilder,
	config: dict[str, Any] | None = None,
) -> WorkflowPlugin:
	"""
	Instantiate and return a WorkflowPlugin bound to *appbuilder*.

	The returned plugin is NOT yet activated.  Call ``plugin.activate()``
	to progress through the full lifecycle (LOADING → INITIALIZING → ACTIVE).

	Example::

	    from pgappforge.plugins.workflow import create_plugin
	    plugin = create_plugin(appbuilder, config={"WORKFLOW_ASYNC_BACKEND": "thread"})
	    plugin.activate()
	"""
	merged: dict[str, Any] = {}
	app = getattr(appbuilder, "get_app", None) or getattr(appbuilder, "app", None)
	if app is not None:
		for key in (
			"WORKFLOW_MAX_CHAIN_DEPTH",
			"WORKFLOW_INSTANCE_TTL_DAYS",
			"WORKFLOW_ASYNC_BACKEND",
			"WORKFLOW_NOTIFICATION_EMAIL",
			"WORKFLOW_ESCALATION_CHECK_INTERVAL",
		):
			if key in app.config:
				merged[key] = app.config[key]

	if config:
		merged.update(config)

	return WorkflowPlugin(appbuilder, merged)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Plugin
	"WorkflowPlugin",
	"create_plugin",
	# Engine
	"WorkflowEngine",
	# Mixin
	"WorkflowMixin",
	# Models
	"ProcessDefinition",
	"ProcessStep",
	"ProcessInstance",
	"ProcessEvent",
	# Views
	"ProcessDashboardView",
	"ProcessDefinitionView",
	"ProcessStepView",
	"ProcessInstanceView",
	"ProcessQueueView",
	"ProcessTimelineView",
	# API Blueprint
	"bpm_api",
]
