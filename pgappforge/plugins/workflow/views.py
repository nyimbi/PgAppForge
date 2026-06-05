"""
pgappforge/plugins/workflow/views.py

FAB views for the BPM system.

Views
-----
ProcessDefinitionView   — CRUD for process definitions + steps
ProcessInstanceView     — read-only list of all running/completed instances
ProcessDashboardView    — /bpm/          summary cards + my queue + overdue table
ProcessTimelineView     — /bpm/timeline/<id>   per-instance visual timeline
ProcessQueueView        — /bpm/queue/          "my work queue" with inline actions
DelegationView          — /bpm/delegations/    CRUD for UserDelegation records
BPMNDesignerView        — /bpm/designer/       BPMN 2.0 visual process designer

API Blueprint (registered separately)
--------------------------------------
POST /bpm/api/advance/<instance_id>
POST /bpm/api/reject/<instance_id>
POST /bpm/api/cancel/<instance_id>
POST /bpm/api/form-time
GET  /bpm/api/instance/<model>/<record_id>
POST /bpm/api/bulk-action              (GAP 7)
"""
from __future__ import annotations

import logging
from typing import Any

from flask import (
	Blueprint,
	current_app,
	g,
	jsonify,
	redirect,
	request,
	session as flask_session,
	url_for,
)
from flask_babel import lazy_gettext as _

from pgappforge import ModelView, expose, has_access
from pgappforge.baseviews import BaseView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access_api

from .engine import WorkflowEngine
from .models import ProcessDefinition, ProcessEvent, ProcessInstance, ProcessStep, UserDelegation

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session():
	"""Obtain the Flask-SQLAlchemy db.session."""
	try:
		from pgappforge import db  # type: ignore[attr-defined]
		return db.session
	except Exception:
		from flask_sqlalchemy import SQLAlchemy  # type: ignore[import]
		db: SQLAlchemy = current_app.extensions["sqlalchemy"]
		return db.session


def _engine() -> WorkflowEngine:
	return WorkflowEngine(_get_session())


def _current_user_id() -> int | None:
	try:
		from flask_login import current_user
		uid = getattr(current_user, "id", None)
		return int(uid) if uid is not None else None
	except Exception:
		return None


def _current_user_roles() -> list[str]:
	try:
		from flask_login import current_user
		return [r.name for r in getattr(current_user, "roles", [])]
	except Exception:
		return []


def _render(template_string: str, **ctx: Any) -> str:
	"""Render an inline Bootstrap 3 template via Flask's Jinja."""
	from flask import render_template_string
	return render_template_string(_BASE_LAYOUT + template_string, **ctx)


# ---------------------------------------------------------------------------
# Shared Bootstrap 3 layout
# ---------------------------------------------------------------------------

_BASE_LAYOUT = """
{% macro status_badge(status) %}
  {% if status == 'active' %}<span class="label label-primary">Active</span>
  {% elif status == 'completed' %}<span class="label label-success">Completed</span>
  {% elif status == 'cancelled' %}<span class="label label-default">Cancelled</span>
  {% elif status == 'error' %}<span class="label label-danger">Error</span>
  {% else %}<span class="label label-info">{{ status }}</span>{% endif %}
{% endmacro %}
"""

_DASHBOARD_TMPL = """
<!DOCTYPE html><html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>BPM Dashboard</title>
  <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.4.1/css/bootstrap.min.css">
  <style>
    body{padding-top:70px}
    .stat-card .panel-body{font-size:2.4em;font-weight:700;text-align:center}
    .overdue{background:#fff3cd}
    .table>tbody>tr.overdue-row>td{background:#fff3cd}
  </style>
</head>
<body>
<nav class="navbar navbar-default navbar-fixed-top">
  <div class="container-fluid">
    <div class="navbar-header"><a class="navbar-brand" href="{{ bpm_url }}">BPM</a></div>
    <ul class="nav navbar-nav">
      <li class="{{ 'active' if active_tab=='dashboard' }}">
        <a href="{{ bpm_url }}">Dashboard</a></li>
      <li class="{{ 'active' if active_tab=='queue' }}">
        <a href="{{ queue_url }}">My Queue
          {% if my_queue_count %}<span class="badge">{{ my_queue_count }}</span>{% endif %}
        </a></li>
      <li><a href="{{ definitions_url }}">Definitions</a></li>
      <li><a href="{{ instances_url }}">All Instances</a></li>
    </ul>
  </div>
</nav>
<div class="container-fluid">
  <h2>BPM Dashboard</h2>
  <div class="row">
    <div class="col-md-3 stat-card">
      <div class="panel panel-primary">
        <div class="panel-heading">Active Processes</div>
        <div class="panel-body">{{ stats.active_count }}</div>
      </div>
    </div>
    <div class="col-md-3 stat-card">
      <div class="panel panel-danger">
        <div class="panel-heading">Overdue</div>
        <div class="panel-body">{{ stats.overdue_count }}</div>
      </div>
    </div>
    <div class="col-md-3 stat-card">
      <div class="panel panel-success">
        <div class="panel-heading">Completed Today</div>
        <div class="panel-body">{{ stats.completed_today }}</div>
      </div>
    </div>
    <div class="col-md-3 stat-card">
      <div class="panel panel-info">
        <div class="panel-heading">Active Definitions</div>
        <div class="panel-body">{{ stats.total_definitions }}</div>
      </div>
    </div>
  </div>

  <div class="row">
    <div class="col-md-6">
      <div class="panel panel-default">
        <div class="panel-heading"><strong>My Pending Tasks</strong></div>
        <div class="panel-body" style="padding:0">
          {% if my_queue %}
          <table class="table table-condensed table-hover" style="margin:0">
            <thead><tr><th>#</th><th>Record</th><th>Step</th><th>Hrs at Step</th><th></th></tr></thead>
            <tbody>
            {% for inst in my_queue %}
            <tr class="{{ 'overdue-row' if inst.is_overdue }}">
              <td>{{ inst.id }}</td>
              <td>{{ inst.model_name }}#{{ inst.record_id }}</td>
              <td>{{ inst.current_step.name if inst.current_step else '—' }}</td>
              <td>{{ '%.1f'|format(inst.hours_at_current_step) }}</td>
              <td>
                <a href="{{ url_for('ProcessTimelineView.index', instance_id=inst.id) }}"
                   class="btn btn-xs btn-default">Timeline</a>
              </td>
            </tr>
            {% endfor %}
            </tbody>
          </table>
          {% else %}
          <p class="text-muted" style="padding:12px">No pending tasks.</p>
          {% endif %}
        </div>
      </div>
    </div>

    <div class="col-md-6">
      <div class="panel panel-danger">
        <div class="panel-heading"><strong>Overdue Instances</strong></div>
        <div class="panel-body" style="padding:0">
          {% if overdue %}
          <table class="table table-condensed table-hover" style="margin:0">
            <thead><tr><th>#</th><th>Record</th><th>Step</th><th>Hrs Overdue</th><th></th></tr></thead>
            <tbody>
            {% for inst in overdue %}
            <tr>
              <td>{{ inst.id }}</td>
              <td>{{ inst.model_name }}#{{ inst.record_id }}</td>
              <td>{{ inst.current_step.name if inst.current_step else '—' }}</td>
              <td class="text-danger"><strong>{{ '%.1f'|format(inst.hours_at_current_step) }}</strong></td>
              <td>
                <a href="{{ url_for('ProcessTimelineView.index', instance_id=inst.id) }}"
                   class="btn btn-xs btn-warning">View</a>
              </td>
            </tr>
            {% endfor %}
            </tbody>
          </table>
          {% else %}
          <p class="text-muted" style="padding:12px">No overdue instances.</p>
          {% endif %}
        </div>
      </div>
    </div>
  </div>
</div>
<script src="https://code.jquery.com/jquery-1.12.4.min.js"></script>
<script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.4.1/js/bootstrap.min.js"></script>
</body></html>
"""

_TIMELINE_TMPL = """
<!DOCTYPE html><html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Process Timeline #{{ instance.id }}</title>
  <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.4.1/css/bootstrap.min.css">
  <style>
    body{padding-top:70px}
    .timeline{position:relative;padding-left:40px}
    .timeline::before{content:'';position:absolute;left:18px;top:0;bottom:0;width:3px;background:#ddd}
    .tl-item{position:relative;margin-bottom:20px}
    .tl-dot{position:absolute;left:-30px;top:4px;width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 2px #aaa}
    .tl-dot.completed{background:#5cb85c;box-shadow:0 0 0 2px #5cb85c}
    .tl-dot.current{background:#337ab7;box-shadow:0 0 0 2px #337ab7}
    .tl-dot.escalation{background:#d9534f;box-shadow:0 0 0 2px #d9534f}
    .tl-dot.reject{background:#f0ad4e;box-shadow:0 0 0 2px #f0ad4e}
    .tl-dot.start{background:#5bc0de;box-shadow:0 0 0 2px #5bc0de}
    .tl-dot.pending{background:#ccc}
    .tl-body{background:#f9f9f9;border:1px solid #e3e3e3;border-radius:4px;padding:10px 14px}
    .tl-meta{font-size:11px;color:#999;margin-top:4px}
    .step-future{opacity:.45}
  </style>
</head>
<body>
<nav class="navbar navbar-default navbar-fixed-top">
  <div class="container-fluid">
    <div class="navbar-header">
      <a class="navbar-brand" href="{{ url_for('ProcessDashboardView.index') }}">BPM</a>
    </div>
    <ul class="nav navbar-nav">
      <li><a href="{{ url_for('ProcessQueueView.index') }}">My Queue</a></li>
    </ul>
  </div>
</nav>
<div class="container">
  <h3>
    Process Timeline
    <small>{{ instance.model_name }}#{{ instance.record_id }} &mdash;
      {{ instance.definition.name if instance.definition else '?' }}
    </small>
    {{ status_badge(instance.status) }}
  </h3>

  {# Step-progress bar #}
  {% if instance.definition and instance.definition.steps %}
  <div class="well well-sm">
    <strong>Steps:</strong>
    {% for step in instance.definition.steps %}
      {% set is_current = (step.id == instance.current_step_id) %}
      {% set is_done = (loop.index0 < current_step_index) %}
      <span class="label {{ 'label-success' if is_done else ('label-primary' if is_current else 'label-default') }}">
        {{ loop.index }}. {{ step.name }}
      </span>
      {% if not loop.last %}&rarr;{% endif %}
    {% endfor %}
  </div>
  {% endif %}

  {# Timeline events #}
  <div class="timeline">
    {% for ev in timeline %}
    <div class="tl-item">
      <div class="tl-dot {{ ev.event_type }}"></div>
      <div class="tl-body">
        <strong>{{ ev.event_type | title }}</strong>
        {% if ev.from_step and ev.to_step %}
          <span class="text-muted">{{ ev.from_step }} &rarr; {{ ev.to_step }}</span>
        {% elif ev.to_step %}
          <span class="text-muted">to {{ ev.to_step }}</span>
        {% endif %}
        {% if ev.comment %}
        <br><em>{{ ev.comment }}</em>
        {% endif %}
        <div class="tl-meta">
          {{ ev.occurred_at }}
          {% if ev.actor_id %}&mdash; actor #{{ ev.actor_id }}{% endif %}
          {% if ev.duration_seconds is not none %}
            &mdash; form time: {{ ev.duration_seconds }}s
          {% endif %}
          {% if ev.step_duration_seconds is not none %}
            &mdash; +{{ ev.step_duration_seconds }}s since previous
          {% endif %}
        </div>
      </div>
    </div>
    {% else %}
    <p class="text-muted">No events recorded yet.</p>
    {% endfor %}
  </div>

  <a href="{{ url_for('ProcessDashboardView.index') }}" class="btn btn-default">
    &larr; Dashboard
  </a>
</div>
<script src="https://code.jquery.com/jquery-1.12.4.min.js"></script>
<script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.4.1/js/bootstrap.min.js"></script>
</body></html>
"""

_QUEUE_TMPL = """
<!DOCTYPE html><html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>My Work Queue</title>
  <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.4.1/css/bootstrap.min.css">
  <style>body{padding-top:70px}.overdue-row td{background:#fff3cd}</style>
</head>
<body>
<nav class="navbar navbar-default navbar-fixed-top">
  <div class="container-fluid">
    <div class="navbar-header">
      <a class="navbar-brand" href="{{ url_for('ProcessDashboardView.index') }}">BPM</a>
    </div>
    <ul class="nav navbar-nav">
      <li class="active"><a href="{{ url_for('ProcessQueueView.index') }}">My Queue</a></li>
      <li><a href="{{ url_for('ProcessDashboardView.index') }}">Dashboard</a></li>
    </ul>
  </div>
</nav>
<div class="container-fluid">
  <h3>My Work Queue
    <small>{{ queue | length }} item{{ 's' if queue | length != 1 }}</small>
  </h3>
  {% if flash_msg %}
  <div class="alert alert-{{ flash_msg.cat }}">{{ flash_msg.text }}</div>
  {% endif %}
  <table class="table table-bordered table-hover">
    <thead>
      <tr>
        <th>#</th><th>Definition</th><th>Record</th>
        <th>Current Step</th><th>Assigned Role</th>
        <th>Hrs at Step</th><th>Status</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>
    {% for inst in queue %}
    <tr class="{{ 'overdue-row' if inst.is_overdue }}">
      <td>{{ inst.id }}</td>
      <td>{{ inst.definition.name if inst.definition else '?' }}</td>
      <td>{{ inst.model_name }}#{{ inst.record_id }}</td>
      <td>{{ inst.current_step.name if inst.current_step else '—' }}</td>
      <td>{{ inst.current_step.assigned_role if inst.current_step else '—' }}</td>
      <td>
        {% set h = inst.hours_at_current_step %}
        <span class="{{ 'text-danger' if inst.is_overdue else '' }}">
          {{ '%.1f'|format(h) }}h
          {% if inst.is_overdue %}<span class="label label-danger">OVERDUE</span>{% endif %}
        </span>
      </td>
      <td>{{ status_badge(inst.status) }}</td>
      <td>
        <form method="POST" action="{{ url_for('ProcessQueueView.action') }}"
              style="display:inline" onsubmit="return confirm('Advance this instance?')">
          <input type="hidden" name="instance_id" value="{{ inst.id }}">
          <input type="hidden" name="action" value="advance">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
          <button type="submit" class="btn btn-xs btn-success">Approve</button>
        </form>
        <form method="POST" action="{{ url_for('ProcessQueueView.action') }}"
              style="display:inline" onsubmit="return confirm('Reject this instance?')">
          <input type="hidden" name="instance_id" value="{{ inst.id }}">
          <input type="hidden" name="action" value="reject">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
          <button type="submit" class="btn btn-xs btn-warning">Reject</button>
        </form>
        <a href="{{ url_for('ProcessTimelineView.index', instance_id=inst.id) }}"
           class="btn btn-xs btn-default">Timeline</a>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="8" class="text-center text-muted">No items in your queue.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>
<script src="https://code.jquery.com/jquery-1.12.4.min.js"></script>
<script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.4.1/js/bootstrap.min.js"></script>
</body></html>
"""


# ---------------------------------------------------------------------------
# ModelView: ProcessDefinition CRUD
# ---------------------------------------------------------------------------

class ProcessDefinitionView(ModelView):
	"""CRUD management for ProcessDefinition and its steps."""

	datamodel = SQLAInterface(ProcessDefinition)
	route_base = "/bpm/definitions"

	list_title = "Process Definitions"
	show_title = "Process Definition"
	add_title = "Add Process Definition"
	edit_title = "Edit Process Definition"

	list_columns = ["name", "description", "is_active", "created_at"]
	show_columns = ["name", "description", "is_active", "config", "created_at"]
	add_columns = ["name", "description", "is_active", "config"]
	edit_columns = ["name", "description", "is_active", "config"]

	search_columns = ["name", "description"]
	label_columns = {
		"name": "Name",
		"description": "Description",
		"is_active": "Active",
		"config": "Configuration (JSON)",
		"created_at": "Created",
	}

	base_order = ("name", "asc")


class ProcessStepView(ModelView):
	"""Inline CRUD for process steps — typically embedded, not in the menu."""

	datamodel = SQLAInterface(ProcessStep)
	route_base = "/bpm/steps"

	list_columns = ["definition_id", "name", "order_num", "assigned_role", "timeout_hours", "escalate_to_role"]
	add_columns = ["definition_id", "name", "order_num", "assigned_role", "timeout_hours", "escalate_to_role", "actions"]
	edit_columns = ["name", "order_num", "assigned_role", "timeout_hours", "escalate_to_role", "actions"]

	base_order = ("order_num", "asc")


class ProcessInstanceView(ModelView):
	"""Read-only list of all process instances."""

	datamodel = SQLAInterface(ProcessInstance)
	route_base = "/bpm/instances"

	list_title = "Process Instances"
	show_title = "Process Instance"

	list_columns = [
		"id", "definition_id", "model_name", "record_id",
		"current_step_id", "status", "started_at", "completed_at",
	]
	show_columns = [
		"id", "definition_id", "model_name", "record_id",
		"current_step_id", "status", "started_at", "completed_at",
		"started_by_id", "step_entered_at",
	]

	# No add/edit — instances are created by the engine only
	base_permissions = ["can_list", "can_show"]
	base_order = ("started_at", "desc")


# ---------------------------------------------------------------------------
# Dashboard view
# ---------------------------------------------------------------------------

class ProcessDashboardView(BaseView):
	"""
	/bpm/ — summary cards + my queue + overdue table.
	"""

	route_base = "/bpm"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		eng = _engine()
		stats = eng.dashboard_stats()
		user_roles = _current_user_roles()

		# My queue — union of queues for all roles the current user holds
		my_queue: list[ProcessInstance] = []
		seen_ids: set[int] = set()
		for role in user_roles:
			for inst in eng.get_queue(role):
				if inst.id not in seen_ids:
					my_queue.append(inst)
					seen_ids.add(inst.id)

		# Overdue instances (all active, filter in Python — engine already does this)
		from sqlalchemy import select
		active_instances: list[ProcessInstance] = list(
			eng.session.execute(
				select(ProcessInstance).where(ProcessInstance.status == "active")
			).scalars()
		)
		overdue = [i for i in active_instances if i.is_overdue]

		# Store queue count in flask session for navbar badge
		flask_session["bpm_my_queue_count"] = len(my_queue)

		try:
			bpm_url = url_for("ProcessDashboardView.index")
		except Exception:
			bpm_url = "/bpm/"
		try:
			queue_url = url_for("ProcessQueueView.index")
		except Exception:
			queue_url = "/bpm/queue/"
		try:
			definitions_url = url_for("ProcessDefinitionView.list")
		except Exception:
			definitions_url = "/bpm/definitions/list"
		try:
			instances_url = url_for("ProcessInstanceView.list")
		except Exception:
			instances_url = "/bpm/instances/list"

		from flask import render_template_string
		return render_template_string(
			_BASE_LAYOUT + _DASHBOARD_TMPL,
			stats=stats,
			my_queue=my_queue,
			my_queue_count=len(my_queue),
			overdue=overdue,
			active_tab="dashboard",
			bpm_url=bpm_url,
			queue_url=queue_url,
			definitions_url=definitions_url,
			instances_url=instances_url,
		)


# ---------------------------------------------------------------------------
# Timeline view
# ---------------------------------------------------------------------------

class ProcessTimelineView(BaseView):
	"""
	/bpm/timeline/<instance_id> — visual step-by-step timeline.

	Color coding:
	  green  = completed step
	  blue   = current step
	  grey   = pending step
	  red    = escalation event
	  amber  = rejection event
	"""

	route_base = "/bpm/timeline"
	default_view = "index"

	@expose("/<int:instance_id>")
	@has_access
	def index(self, instance_id: int):
		session = _get_session()
		inst: ProcessInstance | None = session.get(ProcessInstance, instance_id)
		if inst is None:
			from flask import abort
			abort(404)

		eng = WorkflowEngine(session)
		timeline = eng.timeline(instance_id)

		# Compute index of current step among definition steps
		current_step_index = 0
		if inst.definition and inst.current_step_id:
			for i, s in enumerate(inst.definition.steps):
				if s.id == inst.current_step_id:
					current_step_index = i
					break

		from flask import render_template_string
		return render_template_string(
			_BASE_LAYOUT + _TIMELINE_TMPL,
			instance=inst,
			timeline=timeline,
			current_step_index=current_step_index,
		)


# ---------------------------------------------------------------------------
# Queue view
# ---------------------------------------------------------------------------

class ProcessQueueView(BaseView):
	"""
	/bpm/queue/ — "my work queue" with inline approve/reject actions.
	"""

	route_base = "/bpm/queue"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		eng = _engine()
		user_roles = _current_user_roles()
		user_id = _current_user_id()

		queue: list[ProcessInstance] = []
		seen_ids: set[int] = set()
		for role in user_roles:
			for inst in eng.get_queue(role):
				if inst.id not in seen_ids:
					queue.append(inst)
					seen_ids.add(inst.id)

		# Consume one-time flash message from session
		flash_msg = flask_session.pop("bpm_flash", None)

		from flask import render_template_string
		return render_template_string(
			_BASE_LAYOUT + _QUEUE_TMPL,
			queue=queue,
			flash_msg=flash_msg,
		)

	@expose("/action", methods=("POST",))
	@has_access
	def action(self):
		"""Handle inline approve / reject from the queue table."""
		instance_id_raw = request.form.get("instance_id", "")
		action_name = request.form.get("action", "")
		comment = request.form.get("comment", "")
		user_id = _current_user_id()

		try:
			instance_id = int(instance_id_raw)
		except (TypeError, ValueError):
			flask_session["bpm_flash"] = {"cat": "danger", "text": "Invalid instance ID."}
			return redirect(url_for("ProcessQueueView.index"))

		eng = _engine()
		try:
			if action_name == "advance":
				eng.advance(instance_id, actor_id=user_id, comment=comment or "Approved")
				eng.session.commit()
				flask_session["bpm_flash"] = {
					"cat": "success",
					"text": f"Instance #{instance_id} advanced successfully.",
				}
			elif action_name == "reject":
				eng.reject(instance_id, actor_id=user_id, comment=comment or "Rejected")
				eng.session.commit()
				flask_session["bpm_flash"] = {
					"cat": "warning",
					"text": f"Instance #{instance_id} sent back.",
				}
			else:
				flask_session["bpm_flash"] = {"cat": "danger", "text": f"Unknown action: {action_name!r}"}
		except Exception as exc:
			log.exception("ProcessQueueView.action failed")
			eng.session.rollback()
			flask_session["bpm_flash"] = {"cat": "danger", "text": str(exc)}

		return redirect(url_for("ProcessQueueView.index"))

	@expose("/bulk-action", methods=("POST",))
	@has_access
	def bulk_action(self):
		"""
		POST /bpm/queue/bulk-action

		JSON body:
		  {
		    "action":       "advance" | "reject",
		    "instance_ids": [1, 2, 3],
		    "comment":      "optional comment"
		  }

		Returns:
		  {
		    "succeeded": [1, 3],
		    "failed":    {2: "error message"}
		  }
		"""
		body: dict = request.get_json(silent=True) or {}
		action_name: str = body.get("action", "")
		raw_ids = body.get("instance_ids", [])
		comment: str = body.get("comment", "")
		user_id = _current_user_id()

		if action_name not in ("advance", "reject"):
			return jsonify({"error": f"Unknown action: {action_name!r}. Must be 'advance' or 'reject'."}), 400

		try:
			instance_ids: list[int] = [int(i) for i in raw_ids]
		except (TypeError, ValueError) as exc:
			return jsonify({"error": f"Invalid instance_ids: {exc}"}), 400

		if not instance_ids:
			return jsonify({"error": "instance_ids must be a non-empty list"}), 400

		eng = _engine()
		try:
			if action_name == "advance":
				result = eng.bulk_advance(instance_ids, actor_id=user_id, comment=comment)
			else:
				result = eng.bulk_reject(instance_ids, actor_id=user_id, comment=comment)
			eng.session.commit()
		except Exception as exc:
			log.exception("ProcessQueueView.bulk_action failed")
			eng.session.rollback()
			return jsonify({"error": "Internal error", "detail": str(exc)}), 500

		return jsonify({
			"succeeded": result["succeeded"],
			"failed": {str(k): v for k, v in result["failed"].items()},
		})


# ---------------------------------------------------------------------------
# DelegationView — CRUD for bpm_user_delegation
# ---------------------------------------------------------------------------

class DelegationView(ModelView):
	"""
	/bpm/delegations/ — manage out-of-office task delegation records.

	A delegation record means: while the delegation is active, any task
	assigned to *delegator* is also visible and actionable by *delegate*.
	"""

	datamodel = SQLAInterface(UserDelegation)
	route_base = "/bpm/delegations"

	list_title = "Task Delegations"
	show_title = "Delegation Detail"
	add_title  = "Add Delegation"
	edit_title = "Edit Delegation"

	list_columns = [
		"delegator_id", "delegate_id",
		"start_date", "end_date",
		"is_active", "reason",
	]
	show_columns = [
		"delegator_id", "delegate_id",
		"start_date", "end_date",
		"is_active", "reason", "roles_included",
		"created_at",
	]
	add_columns = [
		"delegator_id", "delegate_id",
		"start_date", "end_date",
		"is_active", "reason", "roles_included",
	]
	edit_columns = [
		"delegator_id", "delegate_id",
		"start_date", "end_date",
		"is_active", "reason", "roles_included",
	]

	search_columns = ["delegator_id", "delegate_id", "is_active"]

	label_columns = {
		"delegator_id":    "Delegating User",
		"delegate_id":     "Acting User (Delegate)",
		"start_date":      "Start Date",
		"end_date":        "End Date (blank = indefinite)",
		"is_active":       "Active",
		"reason":          "Reason",
		"roles_included":  "Roles Covered (JSON, empty = all)",
		"created_at":      "Created",
	}

	base_order = ("created_at", "desc")


# ---------------------------------------------------------------------------
# REST API blueprint
# ---------------------------------------------------------------------------

bpm_api = Blueprint("bpm_api", __name__, url_prefix="/bpm/api")


@bpm_api.route("/advance/<int:instance_id>", methods=("POST",))
@has_access_api
def api_advance(instance_id: int):
	"""
	POST /bpm/api/advance/<instance_id>

	Body (JSON, optional):
	  {"comment": "Looks good"}

	Returns the created transition event as JSON.
	"""
	body: dict = request.get_json(silent=True) or {}
	comment: str = body.get("comment", "")
	user_id = _current_user_id()

	eng = _engine()
	try:
		evt = eng.advance(instance_id, actor_id=user_id, comment=comment)
		eng.session.commit()
	except ValueError as exc:
		return jsonify({"error": str(exc)}), 400
	except Exception as exc:
		log.exception("api_advance failed")
		eng.session.rollback()
		return jsonify({"error": "Internal error", "detail": str(exc)}), 500

	return jsonify({
		"ok": True,
		"event_id": evt.id,
		"event_type": evt.event_type,
		"instance_id": evt.instance_id,
		"to_step": evt.to_step.name if evt.to_step else None,
		"occurred_at": evt.occurred_at.isoformat() if evt.occurred_at else None,
	})


@bpm_api.route("/reject/<int:instance_id>", methods=("POST",))
@has_access_api
def api_reject(instance_id: int):
	"""
	POST /bpm/api/reject/<instance_id>

	Body (JSON, optional):
	  {"comment": "Needs revision"}
	"""
	body: dict = request.get_json(silent=True) or {}
	comment: str = body.get("comment", "")
	user_id = _current_user_id()

	eng = _engine()
	try:
		evt = eng.reject(instance_id, actor_id=user_id, comment=comment)
		eng.session.commit()
	except ValueError as exc:
		return jsonify({"error": str(exc)}), 400
	except Exception as exc:
		log.exception("api_reject failed")
		eng.session.rollback()
		return jsonify({"error": "Internal error", "detail": str(exc)}), 500

	return jsonify({
		"ok": True,
		"event_id": evt.id,
		"event_type": evt.event_type,
		"instance_id": evt.instance_id,
		"to_step": evt.to_step.name if evt.to_step else None,
		"occurred_at": evt.occurred_at.isoformat() if evt.occurred_at else None,
	})


@bpm_api.route("/cancel/<int:instance_id>", methods=("POST",))
@has_access_api
def api_cancel(instance_id: int):
	"""POST /bpm/api/cancel/<instance_id>"""
	body: dict = request.get_json(silent=True) or {}
	comment: str = body.get("comment", "")
	user_id = _current_user_id()

	eng = _engine()
	try:
		inst = eng.cancel(instance_id, actor_id=user_id, comment=comment)
		eng.session.commit()
	except ValueError as exc:
		return jsonify({"error": str(exc)}), 400
	except Exception as exc:
		log.exception("api_cancel failed")
		eng.session.rollback()
		return jsonify({"error": "Internal error", "detail": str(exc)}), 500

	return jsonify({"ok": True, "instance_id": inst.id, "status": inst.status})


@bpm_api.route("/form-time", methods=("POST",))
@has_access_api
def api_form_time():
	"""
	POST /bpm/api/form-time

	JS telemetry endpoint. Body:
	  {"instance_id": 42, "seconds": 97}
	"""
	body: dict = request.get_json(silent=True) or {}
	try:
		instance_id = int(body["instance_id"])
		seconds = int(body["seconds"])
	except (KeyError, TypeError, ValueError) as exc:
		return jsonify({"error": f"Bad request: {exc}"}), 400

	user_id = _current_user_id()
	eng = _engine()
	try:
		evt = eng.form_time_event(instance_id, actor_id=user_id, seconds=seconds)
		eng.session.commit()
	except ValueError as exc:
		return jsonify({"error": str(exc)}), 400
	except Exception as exc:
		log.exception("api_form_time failed")
		eng.session.rollback()
		return jsonify({"error": "Internal error", "detail": str(exc)}), 500

	return jsonify({"ok": True, "event_id": evt.id, "seconds": seconds})


@bpm_api.route("/instance/<string:model_name>/<int:record_id>", methods=("GET",))
@has_access_api
def api_instance(model_name: str, record_id: int):
	"""
	GET /bpm/api/instance/<model>/<record_id>

	Returns the active process instance state for a specific record.
	"""
	eng = _engine()
	inst = eng.get_instance_for_record(model_name, record_id)
	if inst is None:
		return jsonify({"instance": None})

	return jsonify({
		"instance": {
			"id": inst.id,
			"definition_id": inst.definition_id,
			"definition_name": inst.definition.name if inst.definition else None,
			"model_name": inst.model_name,
			"record_id": inst.record_id,
			"status": inst.status,
			"current_step_id": inst.current_step_id,
			"current_step_name": inst.current_step.name if inst.current_step else None,
			"assigned_role": inst.current_step.assigned_role if inst.current_step else None,
			"hours_at_current_step": inst.hours_at_current_step,
			"is_overdue": inst.is_overdue,
			"started_at": inst.started_at.isoformat() if inst.started_at else None,
			"total_elapsed_hours": inst.total_elapsed_hours,
		}
	})


@bpm_api.route("/timeline/<int:instance_id>", methods=("GET",))
@has_access_api
def api_timeline(instance_id: int):
	"""GET /bpm/api/timeline/<instance_id> — full event timeline as JSON."""
	eng = _engine()
	return jsonify({"timeline": eng.timeline(instance_id)})


@bpm_api.route("/stats", methods=("GET",))
@has_access_api
def api_stats():
	"""GET /bpm/api/stats — dashboard aggregate counts."""
	return jsonify(_engine().dashboard_stats())


@bpm_api.route("/bulk-action", methods=("POST",))
@has_access_api
def api_bulk_action():
	"""
	POST /bpm/api/bulk-action   (GAP 7)

	JSON body:
	  {
	    "action":       "advance" | "reject",
	    "instance_ids": [1, 2, 3],
	    "comment":      "optional"
	  }

	Returns:
	  {
	    "succeeded": [1, 3],
	    "failed":    {"2": "error message"}
	  }
	"""
	body: dict = request.get_json(silent=True) or {}
	action_name: str = body.get("action", "")
	raw_ids = body.get("instance_ids", [])
	comment: str = body.get("comment", "")
	user_id = _current_user_id()

	if action_name not in ("advance", "reject"):
		return jsonify({"error": f"Unknown action: {action_name!r}. Must be 'advance' or 'reject'."}), 400

	try:
		instance_ids: list[int] = [int(i) for i in raw_ids]
	except (TypeError, ValueError) as exc:
		return jsonify({"error": f"Invalid instance_ids: {exc}"}), 400

	if not instance_ids:
		return jsonify({"error": "instance_ids must be a non-empty list"}), 400

	eng = _engine()
	try:
		if action_name == "advance":
			result = eng.bulk_advance(instance_ids, actor_id=user_id, comment=comment)
		else:
			result = eng.bulk_reject(instance_ids, actor_id=user_id, comment=comment)
		eng.session.commit()
	except Exception as exc:
		log.exception("api_bulk_action failed")
		eng.session.rollback()
		return jsonify({"error": "Internal error", "detail": str(exc)}), 500

	return jsonify({
		"succeeded": result["succeeded"],
		"failed": {str(k): v for k, v in result["failed"].items()},
	})


# ---------------------------------------------------------------------------
# BPMNDesignerView — /bpm/designer/   (GAP 8)
# ---------------------------------------------------------------------------

class BPMNDesignerView(BaseView):
	"""
	/bpm/designer/<definition_id>

	Full-page BPMN 2.0 process designer backed by bpmn-js (CDN).

	Endpoints
	---------
	GET  /bpm/designer/<definition_id>          — render designer.html
	GET  /bpm/designer/<definition_id>?xml_only=1 — return saved XML as JSON
	POST /bpm/designer/save                     — persist bpmn_xml in definition.config
	POST /bpm/designer/sync-steps               — parse XML → upsert ProcessStep rows
	"""

	route_base = "/bpm/designer"
	default_view = "designer"

	# ------------------------------------------------------------------
	# GET /bpm/designer/<definition_id>
	# ------------------------------------------------------------------

	@expose("/<int:definition_id>")
	@has_access
	def designer(self, definition_id: int):
		from sqlalchemy import select as _select
		from flask import render_template, request as _req

		session = _get_session()
		defn: ProcessDefinition | None = session.get(ProcessDefinition, definition_id)
		if defn is None:
			from flask import abort
			abort(404)

		# ?xml_only=1 — lightweight JSON endpoint used by the toolbar "Load" button
		if _req.args.get("xml_only") == "1":
			saved_xml = (defn.config or {}).get("bpmn_xml", "")
			return jsonify({"bpmn_xml": saved_xml})

		saved_xml: str = (defn.config or {}).get("bpmn_xml", "")

		return render_template(
			"appbuilder/workflow/designer.html",
			definition=defn,
			saved_xml=saved_xml,
		)

	# ------------------------------------------------------------------
	# POST /bpm/designer/save
	# ------------------------------------------------------------------

	@expose("/save", methods=("POST",))
	@has_access
	def save(self):
		"""
		Persist bpmn_xml into ProcessDefinition.config['bpmn_xml'].

		JSON body:
		  {
		    "definition_id": 1,
		    "bpmn_xml":      "<?xml ...",
		    "ext_data":      {elementId: {role, timeout, conditions}, ...}
		  }
		"""
		body: dict = request.get_json(silent=True) or {}
		try:
			definition_id = int(body["definition_id"])
		except (KeyError, TypeError, ValueError) as exc:
			return jsonify({"error": f"definition_id required: {exc}"}), 400

		bpmn_xml: str = body.get("bpmn_xml", "").strip()
		if not bpmn_xml:
			return jsonify({"error": "bpmn_xml is required"}), 400

		ext_data: dict = body.get("ext_data", {})

		session = _get_session()
		defn: ProcessDefinition | None = session.get(ProcessDefinition, definition_id)
		if defn is None:
			return jsonify({"error": f"ProcessDefinition #{definition_id} not found"}), 404

		cfg: dict = dict(defn.config or {})
		cfg["bpmn_xml"] = bpmn_xml
		cfg["bpmn_ext_data"] = ext_data
		defn.config = cfg

		try:
			session.commit()
		except Exception as exc:
			log.exception("BPMNDesignerView.save failed")
			session.rollback()
			return jsonify({"error": "DB error", "detail": str(exc)}), 500

		log.info("BPMNDesignerView: saved BPMN XML for definition #%d (%d bytes)", definition_id, len(bpmn_xml))
		return jsonify({"ok": True, "definition_id": definition_id, "bytes": len(bpmn_xml)})

	# ------------------------------------------------------------------
	# POST /bpm/designer/sync-steps
	# ------------------------------------------------------------------

	@expose("/sync-steps", methods=("POST",))
	@has_access
	def sync_steps(self):
		"""
		Parse BPMN 2.0 XML and upsert ProcessStep + ProcessTransition rows.

		Mapping
		-------
		bpmn:Task / bpmn:UserTask / bpmn:ServiceTask  → step_type=TASK
		bpmn:StartEvent                               → step_type=START
		bpmn:EndEvent                                 → step_type=END
		bpmn:ParallelGateway                          → AND_SPLIT (first) / AND_JOIN (second)
		bpmn:ExclusiveGateway                         → XOR_SPLIT
		bpmn:InclusiveGateway                         → XOR_SPLIT (treated equivalently)
		bpmn:SequenceFlow                             → ProcessTransition

		ext_data (from the properties panel) supplies:
		  role, timeout, conditions per element ID.

		JSON body:
		  {
		    "definition_id": 1,
		    "bpmn_xml":      "<?xml ...",
		    "ext_data":      {elementId: {role, timeout, conditions}, ...}
		  }
		"""
		import xml.etree.ElementTree as ET
		from sqlalchemy import select as _select

		body: dict = request.get_json(silent=True) or {}
		try:
			definition_id = int(body["definition_id"])
		except (KeyError, TypeError, ValueError) as exc:
			return jsonify({"error": f"definition_id required: {exc}"}), 400

		bpmn_xml: str = body.get("bpmn_xml", "").strip()
		if not bpmn_xml:
			return jsonify({"error": "bpmn_xml is required"}), 400

		ext_data: dict[str, dict] = body.get("ext_data", {})

		session = _get_session()
		defn: ProcessDefinition | None = session.get(ProcessDefinition, definition_id)
		if defn is None:
			return jsonify({"error": f"ProcessDefinition #{definition_id} not found"}), 404

		# Parse XML --------------------------------------------------------
		try:
			root = ET.fromstring(bpmn_xml)
		except ET.ParseError as exc:
			return jsonify({"error": f"XML parse error: {exc}"}), 400

		NS = {
			"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
			"bpmn2": "http://www.omg.org/spec/BPMN/20100524/MODEL",
		}

		# Collect elements from all <bpmn:process> children
		elements: list[dict] = []   # {bpmn_id, name, tag, type}
		flows:    list[dict] = []   # {bpmn_id, name, source, target, label}

		def _localname(tag: str) -> str:
			"""Strip namespace URI: '{ns}Tag' → 'Tag'"""
			return tag.split("}")[-1] if "}" in tag else tag

		def _step_type_for(local_tag: str, gateway_seen: dict) -> str:
			"""Map BPMN element local tag → ProcessStep step_type."""
			if local_tag in ("Task", "UserTask", "ServiceTask", "ScriptTask", "BusinessRuleTask", "CallActivity", "SubProcess"):
				return "TASK"
			if local_tag == "StartEvent":
				return "START"
			if local_tag == "EndEvent":
				return "END"
			if local_tag == "ParallelGateway":
				gw_id = gateway_seen.get("parallel_count", 0)
				gateway_seen["parallel_count"] = gw_id + 1
				return "AND_JOIN" if gw_id > 0 else "AND_SPLIT"
			if local_tag in ("ExclusiveGateway", "InclusiveGateway", "ComplexGateway"):
				return "XOR_SPLIT"
			return "TASK"

		gw_seen: dict = {"parallel_count": 0}

		for proc_el in root.iter():
			local = _localname(proc_el.tag)
			if local != "process":
				continue
			order = 0
			for child in list(proc_el):
				child_local = _localname(child.tag)
				if child_local == "sequenceFlow":
					flows.append({
						"bpmn_id": child.get("id", ""),
						"name":    child.get("name", "") or "",
						"source":  child.get("sourceRef", ""),
						"target":  child.get("targetRef", ""),
					})
				elif child_local in (
					"task", "userTask", "serviceTask", "scriptTask",
					"businessRuleTask", "callActivity", "subProcess",
					"startEvent", "endEvent",
					"parallelGateway", "exclusiveGateway",
					"inclusiveGateway", "complexGateway",
					# capitalised variants
					"Task", "UserTask", "ServiceTask", "ScriptTask",
					"BusinessRuleTask", "CallActivity", "SubProcess",
					"StartEvent", "EndEvent",
					"ParallelGateway", "ExclusiveGateway",
					"InclusiveGateway", "ComplexGateway",
				):
					# Normalise to title-case for step_type lookup
					cap = child_local[0].upper() + child_local[1:]
					elements.append({
						"bpmn_id":   child.get("id", ""),
						"name":      child.get("name", "") or cap,
						"tag":       cap,
						"step_type": _step_type_for(cap, gw_seen),
						"order":     order,
					})
					order += 1

		if not elements:
			return jsonify({"error": "No BPMN flow elements found in the XML"}), 400

		# Build bpmn_id → existing ProcessStep mapping -----------------
		existing_steps: list[ProcessStep] = list(
			session.execute(
				_select(ProcessStep).where(ProcessStep.definition_id == definition_id)
			).scalars()
		)
		# We store the BPMN element ID in the step name after a separator so we
		# can look it up on re-sync.  Format: "<human name> [bpmn:<id>]"
		def _bpmn_id_from_step(step: ProcessStep) -> str | None:
			if step.name and "[bpmn:" in step.name:
				try:
					return step.name.split("[bpmn:")[1].rstrip("]")
				except IndexError:
					pass
			return None

		step_by_bpmn: dict[str, ProcessStep] = {}
		for s in existing_steps:
			bid = _bpmn_id_from_step(s)
			if bid:
				step_by_bpmn[bid] = s

		# Collect existing transitions for this definition
		from .models import ProcessTransition
		existing_trans: list[ProcessTransition] = list(
			session.execute(
				_select(ProcessTransition).where(ProcessTransition.definition_id == definition_id)
			).scalars()
		)
		# Key: (from_step_id, to_step_id) → transition
		trans_by_pair: dict[tuple[int, int], ProcessTransition] = {
			(t.from_step_id, t.to_step_id): t for t in existing_trans if t.from_step_id and t.to_step_id
		}

		steps_upserted = 0
		new_step_by_bpmn: dict[str, ProcessStep] = {}

		for idx, el in enumerate(elements):
			bpmn_id: str = el["bpmn_id"]
			if not bpmn_id:
				continue

			ext = ext_data.get(bpmn_id, {})
			role: str | None = ext.get("role") or None
			try:
				timeout_h: int = int(ext.get("timeout") or 24)
			except (TypeError, ValueError):
				timeout_h = 24

			human_name: str = el["name"] or bpmn_id
			stored_name = f"{human_name} [bpmn:{bpmn_id}]"

			if bpmn_id in step_by_bpmn:
				# Update existing
				step = step_by_bpmn[bpmn_id]
				step.name          = stored_name
				step.order_num     = idx
				step.step_type     = el["step_type"]
				step.assigned_role = role or step.assigned_role
				step.timeout_hours = timeout_h
			else:
				# Insert new
				step = ProcessStep(
					definition_id=definition_id,
					name=stored_name,
					order_num=idx,
					step_type=el["step_type"],
					assigned_role=role,
					timeout_hours=timeout_h,
					escalate_to_role=None,
					actions={},
				)
				session.add(step)

			new_step_by_bpmn[bpmn_id] = step
			steps_upserted += 1

		session.flush()  # populate IDs for new steps

		# Upsert transitions from SequenceFlow elements ----------------
		trans_upserted = 0
		for flow in flows:
			src_bpmn = flow["source"]
			tgt_bpmn = flow["target"]
			src_step = new_step_by_bpmn.get(src_bpmn)
			tgt_step = new_step_by_bpmn.get(tgt_bpmn)
			if src_step is None or tgt_step is None:
				continue
			if src_step.id is None or tgt_step.id is None:
				continue

			# Parse conditions from ext_data of the flow element
			flow_ext = ext_data.get(flow["bpmn_id"], {})
			conditions_raw: str = flow_ext.get("conditions", "") or ""
			import json as _json
			try:
				conditions_list = _json.loads(conditions_raw) if conditions_raw.strip() else []
			except _json.JSONDecodeError:
				conditions_list = []

			pair_key = (src_step.id, tgt_step.id)
			if pair_key in trans_by_pair:
				trans = trans_by_pair[pair_key]
				trans.label          = flow["name"] or trans.label
				trans.conditions_json = conditions_list if conditions_list else trans.conditions_json
			else:
				trans = ProcessTransition(
					definition_id=definition_id,
					from_step_id=src_step.id,
					to_step_id=tgt_step.id,
					label=flow["name"] or None,
					conditions_json=conditions_list,
					priority=0,
					is_default=not bool(conditions_list),
				)
				session.add(trans)
				trans_by_pair[pair_key] = trans
			trans_upserted += 1

		try:
			session.commit()
		except Exception as exc:
			log.exception("BPMNDesignerView.sync_steps failed")
			session.rollback()
			return jsonify({"error": "DB error", "detail": str(exc)}), 500

		log.info(
			"BPMNDesignerView: sync_steps definition #%d — %d steps, %d transitions upserted",
			definition_id, steps_upserted, trans_upserted,
		)
		return jsonify({
			"ok": True,
			"definition_id": definition_id,
			"steps_upserted": steps_upserted,
			"transitions_upserted": trans_upserted,
		})


__all__ = [
	# ModelViews
	"ProcessDefinitionView",
	"ProcessStepView",
	"ProcessInstanceView",
	"DelegationView",
	# Custom views
	"ProcessDashboardView",
	"ProcessTimelineView",
	"ProcessQueueView",
	"BPMNDesignerView",
	# API
	"bpm_api",
]
