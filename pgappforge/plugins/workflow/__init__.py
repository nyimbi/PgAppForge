"""
pgappforge/plugins/workflow/__init__.py

Visual process designer plugin: drag-and-drop workflow authoring, multi-step
approval chains, and ML-triggered process transitions.

Enabling
--------
Add to your Flask config::

    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.workflow"]

Or instantiate directly::

    from pgappforge.plugins.workflow import create_plugin
    plugin = create_plugin(appbuilder, config={...})
    plugin.activate()

Config keys
-----------
WORKFLOW_MAX_CHAIN_DEPTH : int (default 10)
    Maximum number of sequential approval steps in a single chain.

WORKFLOW_INSTANCE_TTL_DAYS : int (default 90)
    Days before a completed/rejected ProcessInstance is archived.

WORKFLOW_ML_TRIGGER_ENDPOINT : str | None (default None)
    Optional HTTP endpoint called to evaluate ML-based transition conditions.
    POST body: {"instance_id": str, "trigger_key": str, "context": dict}.
    Expected response: {"proceed": bool, "confidence": float}.

WORKFLOW_ASYNC_BACKEND : "celery" | "thread" | "sync" (default "sync")
    Backend used for asynchronous step execution.
    "celery" requires the celery extra; "thread" uses concurrent.futures.

WORKFLOW_NOTIFICATION_EMAIL : bool (default True)
    Send e-mail notifications on approval task assignment and completion.
"""
from __future__ import annotations

import enum
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from flask import render_template_string, url_for
from pgappforge import expose
from pgappforge.security.decorators import has_access
from sqlalchemy import (
	Column,
	DateTime,
	Enum as SAEnum,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.base_plugin import (
	BasePlugin,
	PluginMetadata,
	PluginPriority,
)

if TYPE_CHECKING:
	from pgappforge import AppBuilder

# ---------------------------------------------------------------------------
# Optional heavy-dep guards
# ---------------------------------------------------------------------------

try:
	from celery import Celery as _Celery  # noqa: F401
	HAS_CELERY = True
except ImportError:
	HAS_CELERY = False

try:
	import redis as _redis  # noqa: F401
	HAS_REDIS = True
except ImportError:
	HAS_REDIS = False

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain enumerations
# ---------------------------------------------------------------------------


class ProcessStatus(str, enum.Enum):
	DRAFT = "draft"
	ACTIVE = "active"
	SUSPENDED = "suspended"
	ARCHIVED = "archived"


class InstanceStatus(str, enum.Enum):
	PENDING = "pending"
	RUNNING = "running"
	AWAITING_APPROVAL = "awaiting_approval"
	COMPLETED = "completed"
	REJECTED = "rejected"
	CANCELLED = "cancelled"
	ERROR = "error"


class TaskStatus(str, enum.Enum):
	PENDING = "pending"
	ASSIGNED = "assigned"
	APPROVED = "approved"
	REJECTED = "rejected"
	DELEGATED = "delegated"
	EXPIRED = "expired"


class TriggerType(str, enum.Enum):
	RECORD_SAVE = "record_save"
	RECORD_DELETE = "record_delete"
	USER_LOGIN = "user_login"
	SCHEDULED = "scheduled"
	ML_SCORE = "ml_score"
	MANUAL = "manual"
	WEBHOOK = "webhook"


# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------


class ProcessDefinition(Model):
	__allow_unmapped__ = True
	"""
	Authored workflow template.  Stores the drag-and-drop canvas state as JSONB
	so the front-end designer can round-trip arbitrary node/edge payloads without
	a schema migration every time a new node type is introduced.
	"""

	__tablename__ = "wf_process_definition"
	__table_args__ = (
		Index("ix_wf_procdef_name", "name"),
		Index("ix_wf_procdef_status", "status"),
		{"extend_existing": True},
	)

	id = Column(Integer, primary_key=True, autoincrement=True)
	name = Column(String(255), nullable=False, unique=True)
	description = Column(Text, nullable=True)
	version = Column(Integer, nullable=False, default=1)
	status = Column(
		SAEnum(ProcessStatus, name="process_status_enum"),
		nullable=False,
		default=ProcessStatus.DRAFT,
	)

	# Canvas state: nodes, edges, layout positions, custom properties.
	canvas_data: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	# Approval chain config: ordered list of step descriptors.
	# Each step: {"role": str, "timeout_hours": int, "auto_approve_on_timeout": bool}
	approval_chain: list[dict[str, Any]] = Column(JSONB, nullable=False, default=list)

	# Arbitrary plugin-level metadata (tags, SLA, cost-centre codes, etc.)
	meta: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	created_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
	changed_on = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)
	created_by_fk = Column(Integer, ForeignKey("ab_user.id"), nullable=True)

	# Relationships
	instances: list[ProcessInstance] = relationship(
		"ProcessInstance",
		back_populates="definition",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)
	triggers: list[WorkflowTrigger] = relationship(
		"WorkflowTrigger",
		back_populates="definition",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	def __repr__(self) -> str:
		return f"<ProcessDefinition {self.name!r} v{self.version} [{self.status.value}]>"


class ProcessInstance(Model):
	__allow_unmapped__ = True
	"""
	A single execution of a ProcessDefinition, created when a trigger fires or
	a user manually starts a process.  Carries the live execution context (current
	step index, runtime variables) and links to all approval tasks for this run.
	"""

	__tablename__ = "wf_process_instance"
	__table_args__ = (
		Index("ix_wf_procinst_def", "definition_id"),
		Index("ix_wf_procinst_status", "status"),
		Index("ix_wf_procinst_initiator", "initiated_by_fk"),
		{"extend_existing": True},
	)

	id = Column(Integer, primary_key=True, autoincrement=True)
	definition_id = Column(
		Integer,
		ForeignKey("wf_process_definition.id", ondelete="CASCADE"),
		nullable=False,
	)
	status = Column(
		SAEnum(InstanceStatus, name="instance_status_enum"),
		nullable=False,
		default=InstanceStatus.PENDING,
	)

	# Index of the currently active step in definition.approval_chain.
	current_step = Column(Integer, nullable=False, default=0)

	# Runtime variables mutated as steps execute: form values, computed scores, etc.
	context: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	# Append-only execution log for auditability.
	execution_log: list[dict[str, Any]] = Column(JSONB, nullable=False, default=list)

	initiated_by_fk = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	started_at = Column(DateTime(timezone=True), nullable=True)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	created_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

	# Relationships
	definition: ProcessDefinition = relationship(
		"ProcessDefinition",
		back_populates="instances",
	)
	tasks: list[ApprovalTask] = relationship(
		"ApprovalTask",
		back_populates="instance",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	def __repr__(self) -> str:
		return f"<ProcessInstance #{self.id} def={self.definition_id} [{self.status.value}]>"


class ApprovalTask(Model):
	__allow_unmapped__ = True
	"""
	One human-review step within a ProcessInstance.  Created when execution
	reaches an approval node; resolved by an approver acting via the dashboard.
	"""

	__tablename__ = "wf_approval_task"
	__table_args__ = (
		Index("ix_wf_task_instance", "instance_id"),
		Index("ix_wf_task_assignee", "assignee_fk"),
		Index("ix_wf_task_status", "status"),
		{"extend_existing": True},
	)

	id = Column(Integer, primary_key=True, autoincrement=True)
	instance_id = Column(
		Integer,
		ForeignKey("wf_process_instance.id", ondelete="CASCADE"),
		nullable=False,
	)

	# Step index within the parent definition's approval_chain.
	step_index = Column(Integer, nullable=False, default=0)
	step_label = Column(String(255), nullable=True)

	status = Column(
		SAEnum(TaskStatus, name="task_status_enum"),
		nullable=False,
		default=TaskStatus.PENDING,
	)

	assignee_fk = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	delegated_to_fk = Column(Integer, ForeignKey("ab_user.id"), nullable=True)

	# Approver's free-text decision rationale.
	comment = Column(Text, nullable=True)

	# Structured decision payload (e.g. ML confidence scores, form overrides).
	decision_data: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	due_at = Column(DateTime(timezone=True), nullable=True)
	assigned_at = Column(DateTime(timezone=True), nullable=True)
	resolved_at = Column(DateTime(timezone=True), nullable=True)
	created_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

	# Relationships
	instance: ProcessInstance = relationship("ProcessInstance", back_populates="tasks")

	def __repr__(self) -> str:
		return f"<ApprovalTask #{self.id} instance={self.instance_id} step={self.step_index} [{self.status.value}]>"


class WorkflowTrigger(Model):
	__allow_unmapped__ = True
	"""
	Declarative rule that auto-starts a ProcessDefinition when a system event
	matches a configured predicate.  Supports ORM hooks, schedules, ML scores,
	and inbound webhooks.
	"""

	__tablename__ = "wf_workflow_trigger"
	__table_args__ = (
		Index("ix_wf_trigger_def", "definition_id"),
		Index("ix_wf_trigger_type", "trigger_type"),
		Index("ix_wf_trigger_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(Integer, primary_key=True, autoincrement=True)
	definition_id = Column(
		Integer,
		ForeignKey("wf_process_definition.id", ondelete="CASCADE"),
		nullable=False,
	)

	trigger_type = Column(
		SAEnum(TriggerType, name="trigger_type_enum"),
		nullable=False,
	)

	# Predicate evaluated against the triggering event payload.
	# Format depends on trigger_type:
	#   record_save / record_delete: {"model": "MyModel", "condition": {"field": "status", "eq": "submitted"}}
	#   scheduled: {"cron": "0 9 * * 1"}
	#   ml_score:  {"endpoint_override": "https://...", "threshold": 0.85}
	#   webhook:   {"secret": "...", "path": "/hooks/my-flow"}
	predicate: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	# Initial context variables injected into every ProcessInstance started by
	# this trigger.  May reference Jinja-style template expressions evaluated at
	# trigger time: {"owner": "{{ record.created_by }}"}
	initial_context: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	is_active = Column(Integer, nullable=False, default=1)  # 1=active, 0=disabled
	description = Column(Text, nullable=True)
	created_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

	# Relationships
	definition: ProcessDefinition = relationship(
		"ProcessDefinition",
		back_populates="triggers",
	)

	def __repr__(self) -> str:
		return f"<WorkflowTrigger #{self.id} type={self.trigger_type.value} def={self.definition_id}>"


# ---------------------------------------------------------------------------
# Shared Bootstrap 3 stub template
# ---------------------------------------------------------------------------

_STUB_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} — pgAppForge</title>
  <link rel="stylesheet"
        href="https://maxcdn.bootstrapcdn.com/bootstrap/3.4.1/css/bootstrap.min.css">
  <style>
    body { padding-top: 70px; }
    .plugin-badge { font-size: 12px; vertical-align: middle; }
    .feature-list li { margin-bottom: 6px; }
    .hero { background: #f5f5f5; border-radius: 6px; padding: 30px 40px; margin-bottom: 30px; }
  </style>
</head>
<body>
  <nav class="navbar navbar-default navbar-fixed-top">
    <div class="container-fluid">
      <div class="navbar-header">
        <span class="navbar-brand">pgAppForge Workflow</span>
      </div>
      <ul class="nav navbar-nav">
        <li><a href="{{ designer_url }}">Process Designer</a></li>
        <li><a href="{{ dashboard_url }}">Approval Dashboard</a></li>
        <li><a href="{{ monitor_url }}">Process Monitor</a></li>
      </ul>
      <ul class="nav navbar-nav navbar-right">
        <span class="navbar-text">
          <span class="label label-success plugin-badge">Plugin Active</span>
        </span>
      </ul>
    </div>
  </nav>

  <div class="container">
    <div class="hero">
      <h2>{{ title }}</h2>
      <p class="lead text-muted">{{ subtitle }}</p>
    </div>
    <div class="row">
      {% for card in cards %}
      <div class="col-md-4">
        <div class="panel panel-default">
          <div class="panel-heading"><strong>{{ card.heading }}</strong></div>
          <div class="panel-body">{{ card.body }}</div>
        </div>
      </div>
      {% endfor %}
    </div>
    <div class="alert alert-info">
      <strong>Workflow plugin v0.1.0</strong> is active.
      Configure via <code>PGAPPFORGE_PLUGINS</code> in your Flask config.
    </div>
  </div>
</body>
</html>
"""


def _stub_response(
	title: str,
	subtitle: str,
	cards: list[dict[str, str]],
) -> str:
	"""Render a Bootstrap 3 stub page. Avoids importing Jinja2 directly."""
	try:
		designer_url = url_for("ProcessDesignerView.index")
	except Exception:
		designer_url = "#"
	try:
		dashboard_url = url_for("ApprovalDashboardView.index")
	except Exception:
		dashboard_url = "#"
	try:
		monitor_url = url_for("ProcessMonitorView.index")
	except Exception:
		monitor_url = "#"

	return render_template_string(
		_STUB_TEMPLATE,
		title=title,
		subtitle=subtitle,
		cards=cards,
		designer_url=designer_url,
		dashboard_url=dashboard_url,
		monitor_url=monitor_url,
	)


# ---------------------------------------------------------------------------
# Stub views
# ---------------------------------------------------------------------------


class ProcessDesignerView:
	"""
	Drag-and-drop process designer.

	Presents a canvas (React-Flow or jsPlumb in production) where operators
	author ProcessDefinition nodes and edges, set approval chain steps, and
	attach WorkflowTrigger rules — all without writing Python.

	Full implementation wires a FAB ModelView for CRUD on ProcessDefinition,
	plus a blueprint serving the SPA canvas at /workflow/designer/<id>.
	"""

	default_view = "index"

	@expose("/")
	@has_access
	def index(self) -> str:
		return _stub_response(
			title="Process Designer",
			subtitle="Author drag-and-drop workflows, approval chains, and transition rules.",
			cards=[
				{
					"heading": "Canvas",
					"body": (
						"Node palette with Start, End, Approval Step, Script Task, "
						"Conditional Gateway, and ML Trigger node types. "
						"Drag to compose; edges carry guard expressions."
					),
				},
				{
					"heading": "Approval Chains",
					"body": (
						"Ordered step list with per-step role assignment, timeout "
						"(hours), auto-approve-on-timeout flag, and optional "
						"delegation rules stored as JSONB."
					),
				},
				{
					"heading": "Triggers",
					"body": (
						"Bind a ProcessDefinition to ORM events (record_save, "
						"record_delete), cron schedules, ML score thresholds, or "
						"inbound webhooks from the trigger configuration panel."
					),
				},
			],
		)


class ApprovalDashboardView:
	"""
	Personal approval queue for the current user.

	Lists all ApprovalTask rows assigned to request.user, ordered by due_at.
	Provides approve / reject / delegate actions that advance the parent
	ProcessInstance to its next step or mark it rejected.

	Full implementation uses a FAB ModelView + custom actions, wired to the
	on_record_save hook to trigger e-mail notifications when tasks are created.
	"""

	default_view = "index"

	@expose("/")
	@has_access
	def index(self) -> str:
		return _stub_response(
			title="Approval Dashboard",
			subtitle="Review and act on approval tasks assigned to you.",
			cards=[
				{
					"heading": "My Queue",
					"body": (
						"Filterable list of pending ApprovalTask rows sorted by "
						"due date. Overdue tasks are highlighted in amber; "
						"expired tasks shown in red."
					),
				},
				{
					"heading": "Actions",
					"body": (
						"Approve, Reject, or Delegate each task. "
						"Comments are stored on ApprovalTask.comment. "
						"Approval advances ProcessInstance.current_step; "
						"rejection sets status=REJECTED and fires on_record_save."
					),
				},
				{
					"heading": "Notifications",
					"body": (
						"E-mail sent on assignment when WORKFLOW_NOTIFICATION_EMAIL "
						"is True. Badge count in the top-nav reflects your pending "
						"queue depth (populated by a before_request hook)."
					),
				},
			],
		)


class ProcessMonitorView:
	"""
	Operational dashboard for all running and recently completed process instances.

	Displays a timeline of ProcessInstance rows with status filters, a drill-down
	view of the execution_log JSONB array, and links to re-open stalled instances.
	Integrates with the ML trigger endpoint to surface confidence scores inline.
	"""

	default_view = "index"

	@expose("/")
	@has_access
	def index(self) -> str:
		return _stub_response(
			title="Process Monitor",
			subtitle="Observe live and historical process execution across all definitions.",
			cards=[
				{
					"heading": "Instance List",
					"body": (
						"All ProcessInstance rows with status pill filter "
						"(running / awaiting_approval / completed / error). "
						"Sortable by started_at; filterable by definition and initiator."
					),
				},
				{
					"heading": "Execution Timeline",
					"body": (
						"Drill-down view renders ProcessInstance.execution_log as a "
						"vertical timeline: each log entry shows timestamp, step label, "
						"actor, and decision rationale from ApprovalTask.comment."
					),
				},
				{
					"heading": "ML Trigger Insights",
					"body": (
						"For instances started by ml_score triggers, displays the "
						"confidence score returned by WORKFLOW_ML_TRIGGER_ENDPOINT "
						"alongside the threshold that was crossed."
					),
				},
			],
		)


# ---------------------------------------------------------------------------
# WorkflowPlugin
# ---------------------------------------------------------------------------


class WorkflowPlugin(BasePlugin):
	"""
	Visual process designer plugin for pgAppForge.

	Registers three views (ProcessDesignerView, ApprovalDashboardView,
	ProcessMonitorView) and four SQLAlchemy models.  Hooks into on_record_save
	to evaluate WorkflowTrigger predicates and on_user_login to push a pending
	approval-task count into the session.
	"""

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="workflow",
			version="0.1.0",
			description=(
				"Visual process designer: drag-and-drop workflows, "
				"approval chains, and ML-triggered transitions."
			),
			author="pgAppForge Contributors",
			tags=["workflow", "bpm", "approval", "ml-trigger"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_workflow_design",
				"can_workflow_approve",
				"can_workflow_monitor",
			],
			safe_mode_compatible=True,
			example_config={
				"WORKFLOW_MAX_CHAIN_DEPTH": 10,
				"WORKFLOW_INSTANCE_TTL_DAYS": 90,
				"WORKFLOW_ML_TRIGGER_ENDPOINT": None,
				"WORKFLOW_ASYNC_BACKEND": "sync",
				"WORKFLOW_NOTIFICATION_EMAIL": True,
			},
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""
		Called by activate() after status transitions to INITIALIZING.

		Connects hook receivers so record-save and login events are
		observed without importing appbuilder internals at import time.
		"""
		hooks = getattr(self.appbuilder, "hooks", None)
		if hooks is not None:
			hooks.on_record_save.connect(self._on_record_save)
			hooks.on_user_login.connect(self._on_user_login)
			log.debug("WorkflowPlugin: hook receivers connected")
		else:
			log.warning(
				"WorkflowPlugin: appbuilder.hooks not present — "
				"hook receivers not connected.  Ensure HookRegistry.init_app() "
				"has been called before plugin activation."
			)

	def configure(self, config: dict[str, Any]) -> None:
		"""Merge new config values and re-validate."""
		self.config.update(config)
		self._validate_config()

	def activate(self) -> bool:
		"""Full lifecycle: LOADING → INITIALIZING → register views → ACTIVE."""
		return super().activate()

	def deactivate(self) -> bool:
		"""Disconnect hooks and mark UNLOADED."""
		hooks = getattr(self.appbuilder, "hooks", None)
		if hooks is not None:
			hooks.on_record_save.disconnect(self._on_record_save)
			hooks.on_user_login.disconnect(self._on_user_login)
		return super().deactivate()

	# ------------------------------------------------------------------
	# View registration
	# ------------------------------------------------------------------

	def register_views(self) -> None:
		"""Register the three workflow views into pgAppForge's menu."""
		self.add_view(
			ProcessDesignerView,
			"Process Designer",
			icon="fa-sitemap",
			category="Workflow",
			category_icon="fa-cogs",
		)
		self.add_view(
			ApprovalDashboardView,
			"Approval Dashboard",
			icon="fa-check-square-o",
			category="Workflow",
		)
		self.add_view(
			ProcessMonitorView,
			"Process Monitor",
			icon="fa-bar-chart",
			category="Workflow",
		)
		log.info("WorkflowPlugin: views registered")

	# ------------------------------------------------------------------
	# Model registration
	# ------------------------------------------------------------------

	def register_models(self) -> list:
		"""
		Return all SQLAlchemy Model classes contributed by this plugin.

		The list is consumed by Alembic autogenerate so that workflow tables
		appear in migrations without manual metadata stitching.
		"""
		return [
			ProcessDefinition,
			ProcessInstance,
			ApprovalTask,
			WorkflowTrigger,
		]

	# ------------------------------------------------------------------
	# Hook overrides
	# ------------------------------------------------------------------

	def on_record_save(self, model_class: type, record: Any, is_new: bool) -> None:
		"""
		Evaluate all active WorkflowTrigger rules of type RECORD_SAVE against
		the saved record.  When a predicate matches, a new ProcessInstance is
		created and execution begins.

		This override is called by the PluginManager; the _on_record_save
		receiver below is connected directly to the HookRegistry signal so
		both paths work regardless of PluginManager version.
		"""
		self._evaluate_record_triggers(model_class, record, is_new)

	def on_user_login(self, user: Any) -> None:
		"""
		Cache the current user's pending approval-task count so the navbar
		badge can display it without an extra query per request.
		"""
		self._cache_pending_task_count(user)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _on_record_save(self, model_class: type, record: Any, is_new: bool) -> None:
		"""HookRegistry signal receiver — delegates to on_record_save."""
		try:
			self.on_record_save(model_class, record, is_new)
		except Exception:
			log.exception("WorkflowPlugin._on_record_save raised unexpectedly")

	def _on_user_login(self, user: Any) -> None:
		"""HookRegistry signal receiver — delegates to on_user_login."""
		try:
			self.on_user_login(user)
		except Exception:
			log.exception("WorkflowPlugin._on_user_login raised unexpectedly")

	def _evaluate_record_triggers(
		self,
		model_class: type,
		record: Any,
		is_new: bool,
	) -> None:
		"""
		Query active RECORD_SAVE triggers whose predicate.model matches
		model_class.__name__ and whose condition (if any) the record satisfies.

		Stub: logs intent; full implementation queries WorkflowTrigger, evaluates
		predicate conditions, and calls _start_instance().
		"""
		model_name = getattr(model_class, "__name__", str(model_class))
		log.debug(
			"WorkflowPlugin: evaluating record triggers for %s (is_new=%s)",
			model_name,
			is_new,
		)
		# Full implementation:
		#   session = self.appbuilder.get_session
		#   triggers = (
		#       session.execute(
		#           select(WorkflowTrigger)
		#           .where(WorkflowTrigger.trigger_type == TriggerType.RECORD_SAVE)
		#           .where(WorkflowTrigger.is_active == 1)
		#       ).scalars().all()
		#   )
		#   for trigger in triggers:
		#       pred = trigger.predicate
		#       if pred.get("model") != model_name:
		#           continue
		#       if _matches_condition(pred.get("condition", {}), record):
		#           self._start_instance(trigger, context={"record_id": record.id})

	def _cache_pending_task_count(self, user: Any) -> None:
		"""
		Store pending task count in the Flask session for badge rendering.

		Stub: logs intent; full implementation queries ApprovalTask filtered by
		assignee_fk == user.id and status == TaskStatus.ASSIGNED.
		"""
		user_id = getattr(user, "id", None)
		log.debug(
			"WorkflowPlugin: caching pending task count for user_id=%s", user_id
		)
		# Full implementation:
		#   from flask import session as flask_session
		#   session = self.appbuilder.get_session
		#   count = session.execute(
		#       select(func.count()).select_from(ApprovalTask)
		#       .where(ApprovalTask.assignee_fk == user_id)
		#       .where(ApprovalTask.status == TaskStatus.ASSIGNED)
		#   ).scalar_one()
		#   flask_session["wf_pending_task_count"] = count

	def _start_instance(
		self,
		trigger: WorkflowTrigger,
		context: dict[str, Any] | None = None,
	) -> ProcessInstance:
		"""
		Create a ProcessInstance for *trigger*'s definition and begin execution.

		The initial context is the merge of trigger.initial_context and any
		caller-supplied *context* dict.  The async backend (sync / thread /
		celery) is selected from WORKFLOW_ASYNC_BACKEND config.
		"""
		merged_context: dict[str, Any] = {**trigger.initial_context, **(context or {})}
		backend = self.config.get("WORKFLOW_ASYNC_BACKEND", "sync")

		log.info(
			"WorkflowPlugin: starting ProcessInstance for definition_id=%s "
			"via trigger #%s backend=%s",
			trigger.definition_id,
			trigger.id,
			backend,
		)

		if backend == "celery" and not HAS_CELERY:
			log.warning(
				"WorkflowPlugin: WORKFLOW_ASYNC_BACKEND='celery' but celery is "
				"not installed — falling back to 'sync'"
			)

		instance = ProcessInstance(
			definition_id=trigger.definition_id,
			status=InstanceStatus.PENDING,
			context=merged_context,
			execution_log=[],
			started_at=datetime.now(timezone.utc),
		)
		return instance

	# ------------------------------------------------------------------
	# Config schema
	# ------------------------------------------------------------------

	def get_config_schema(self) -> dict:
		"""
		JSON Schema for this plugin's configuration keys.

		Used by the admin UI to render a typed settings form with validation.
		"""
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
					"description": "Maximum sequential approval steps per chain.",
				},
				"WORKFLOW_INSTANCE_TTL_DAYS": {
					"type": "integer",
					"minimum": 1,
					"default": 90,
					"description": "Days before completed/rejected instances are archived.",
				},
				"WORKFLOW_ML_TRIGGER_ENDPOINT": {
					"type": ["string", "null"],
					"format": "uri",
					"default": None,
					"description": (
						"HTTP endpoint for ML-based transition evaluation. "
						"POST receives {instance_id, trigger_key, context}; "
						"response must include {proceed: bool, confidence: float}."
					),
				},
				"WORKFLOW_ASYNC_BACKEND": {
					"type": "string",
					"enum": ["sync", "thread", "celery"],
					"default": "sync",
					"description": "Backend for asynchronous step execution.",
				},
				"WORKFLOW_NOTIFICATION_EMAIL": {
					"type": "boolean",
					"default": True,
					"description": "Send e-mail on approval task assignment and resolution.",
				},
			},
		}

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
				"not installed.  Install it with: pip install celery"
			)

		if backend in ("celery", "thread") and not HAS_REDIS:
			log.debug(
				"WorkflowPlugin: redis not installed — result backend will "
				"fall back to in-process store for async tasks"
			)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_plugin(
	appbuilder: AppBuilder,
	config: dict[str, Any] | None = None,
) -> WorkflowPlugin:
	"""
	Instantiate and return a WorkflowPlugin bound to *appbuilder*.

	The returned plugin is NOT yet activated.  Call ``plugin.activate()`` to
	progress through the full lifecycle (LOADING → INITIALIZING → ACTIVE).

	Example::

		from pgappforge.plugins.workflow import create_plugin

		plugin = create_plugin(appbuilder, config={
		    "WORKFLOW_ASYNC_BACKEND": "celery",
		    "WORKFLOW_NOTIFICATION_EMAIL": True,
		})
		plugin.activate()

	Args:
		appbuilder: Initialised pgAppForge / AppBuilder instance.
		config:     Optional mapping of WORKFLOW_* config keys.  Values here
		            override anything already in appbuilder.app.config.

	Returns:
		Unactivated WorkflowPlugin instance.
	"""
	# Merge app-level config first so explicit kwargs win.
	merged: dict[str, Any] = {}
	app = getattr(appbuilder, "get_app", None) or getattr(appbuilder, "app", None)
	if app is not None:
		for key in (
			"WORKFLOW_MAX_CHAIN_DEPTH",
			"WORKFLOW_INSTANCE_TTL_DAYS",
			"WORKFLOW_ML_TRIGGER_ENDPOINT",
			"WORKFLOW_ASYNC_BACKEND",
			"WORKFLOW_NOTIFICATION_EMAIL",
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
	# Models
	"ProcessDefinition",
	"ProcessInstance",
	"ApprovalTask",
	"WorkflowTrigger",
	# Enumerations
	"ProcessStatus",
	"InstanceStatus",
	"TaskStatus",
	"TriggerType",
	# Views
	"ProcessDesignerView",
	"ApprovalDashboardView",
	"ProcessMonitorView",
]
