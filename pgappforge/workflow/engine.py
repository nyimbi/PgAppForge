"""
pgappforge/workflow/engine.py

PgAppForgeWorkflowEngine — YAML-defined workflow engine.

Phase 1: YAML DSL with sequential steps, user tasks, and service tasks.
Phase 3 (future): Full BPMN 2.0 via SpiffWorkflow import.

Usage::

    engine = PgAppForgeWorkflowEngine()
    engine.load_yaml("workflows/sacco_loan_approval.yaml")
    instance = engine.start(
        "sacco_loan_approval",
        {"application_id": "app-123"},
        tenant_id="t1",
    )
    engine.complete_step(instance.id, "loan_officer_review", {"recommendation": "APPROVE"})
    pending = engine.get_pending_tasks("t1", role="Loan Officer")
"""
from __future__ import annotations

import copy
import json
import logging
import threading
import sqlalchemy as sa
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import WorkflowDefinition, WorkflowInstance

log = logging.getLogger(__name__)


class PgAppForgeWorkflowEngine:
	"""YAML-defined sequential workflow engine.

	Instance is designed to be used as a singleton per application — call
	``load_yaml`` / ``load_dict`` at startup, then ``start`` / ``complete_step``
	at runtime.

	Thread safety: _definitions is write-once at startup; _instances is an
	in-process cache.  For multi-process deployments, rely on the DB-backed
	methods (pass ``session=`` to every call).
	"""

	def __init__(self) -> None:
		# name → WorkflowDefinition
		self._definitions: dict[str, WorkflowDefinition] = {}
		# instance_id → WorkflowInstance (in-process cache)
		self._instances: dict[str, WorkflowInstance] = {}

	# ------------------------------------------------------------------
	# Loading definitions
	# ------------------------------------------------------------------

	def load_yaml(self, yaml_path: str | Path) -> WorkflowDefinition:
		"""Load a YAML workflow definition from a file."""
		from .yaml_dsl import parse_yaml_file
		data = parse_yaml_file(yaml_path)
		return self._load_data(data, source=str(yaml_path))

	def load_yaml_string(self, yaml_text: str, source: str = "<string>") -> WorkflowDefinition:
		"""Load a workflow definition from a YAML string."""
		from .yaml_dsl import parse_yaml_string
		data = parse_yaml_string(yaml_text, source=source)
		return self._load_data(data, source=source)

	def load_dict(self, data: dict) -> WorkflowDefinition:
		"""Load a workflow from an already-parsed dict."""
		return self._load_data(data)

	def load_all_from_directory(self, directory: str | Path) -> int:
		"""Load all *.yaml workflow files from a directory (non-recursive).

		Returns the number of successfully loaded definitions.
		"""
		from .yaml_dsl import load_directory
		count = 0
		for workflow_data in load_directory(directory):
			try:
				self._load_data(workflow_data, source=str(directory))
				count += 1
			except Exception as exc:
				log.warning("load_all_from_directory: skipping %r: %s", workflow_data.get("name"), exc)
		return count

	def _load_data(self, data: dict, source: str = "") -> WorkflowDefinition:
		definition = WorkflowDefinition(
			name=data["name"],
			steps=data.get("steps", []),
			trigger=data.get("trigger") or {},
			description=data.get("description", ""),
			yaml_source=source,
			on_complete=data.get("on_complete") or {},
			on_decline=data.get("on_decline") or {},
			on_error=data.get("on_error") or {},
		)
		self._definitions[definition.name] = definition
		log.info("Workflow loaded: %s (%d steps)", definition.name, len(definition.steps))
		return definition

	# ------------------------------------------------------------------
	# Runtime
	# ------------------------------------------------------------------

	def start(
		self,
		workflow_name: str,
		data: dict,
		tenant_id: str,
		session=None,
		parent_instance_id: str | None = None,
	) -> WorkflowInstance:
		"""Start a new workflow instance.

		Args:
			workflow_name: Name of a previously loaded workflow definition.
			data: Initial context data dict (merged with step outputs as the
			      workflow progresses).
			tenant_id: Tenant identifier for multi-tenant isolation.
			session: Optional SQLAlchemy session for DB persistence.

		Returns:
			WorkflowInstance with status RUNNING or WAITING (if first step
			is a UserTask) or COMPLETED (if all steps are automated).

		Raises:
			ValueError: If workflow_name is not loaded.
		"""
		if workflow_name not in self._definitions:
			loaded = sorted(self._definitions.keys())
			raise ValueError(
				f"Workflow {workflow_name!r} not found. Loaded: {loaded}"
			)

		definition = self._definitions[workflow_name]
		instance = WorkflowInstance(
			definition=definition,
			data=dict(data),
			tenant_id=tenant_id,
		)
		if parent_instance_id:
			instance.data["_parent_instance_id"] = parent_instance_id
		self._instances[instance.id] = instance

		if session:
			self._persist_instance(instance, session)

		log.info("Workflow started: %s instance=%s", workflow_name, instance.id[:8])

		# Auto-advance through automated steps
		self._advance(instance, session)

		return instance

	def complete_step(
		self,
		instance_id: str,
		step_id: str,
		form_data: dict,
		completed_by: str = "",
		session=None,
	) -> WorkflowInstance:
		"""Mark a UserTask step as complete with form data.

		Args:
			instance_id: Workflow instance ID.
			step_id: The step being completed (must match the current waiting step).
			form_data: Form field values submitted by the user.
			completed_by: Username or user ID of the actor.
			session: Optional SQLAlchemy session.

		Raises:
			ValueError: If instance not found or step_id does not match current step.
		"""
		instance = self._get_instance(instance_id, session)

		current = self._get_current_step(instance)
		if current and current.get("id") != step_id:
			raise ValueError(
				f"Current step is {current['id']!r}, not {step_id!r}"
			)

		# Record step completion
		instance.step_history.append({
			"step_id": step_id,
			"completed_by": completed_by,
			"form_data": form_data,
			"completed_at": datetime.now(timezone.utc).isoformat(),
		})

		# Merge form data into instance data
		instance.data.update(form_data)
		# Also key by step_id so conditions like "loan_officer_review.recommendation" work
		instance.data[step_id] = form_data

		# Mark task record complete in DB
		if session:
			try:
				session.execute(sa.text("""
					UPDATE pgaf_workflow_task
					SET status = 'COMPLETED', completed_at = NOW(), completed_by = :by
					WHERE instance_id = :iid AND current_step_id = :sid AND status = 'PENDING'
				"""), {"iid": instance_id, "sid": step_id, "by": completed_by})
			except Exception as exc:
				log.debug("complete_step task update failed: %s", exc)

		# Advance to next step
		instance.current_step_index += 1
		self._advance(instance, session)

		if session:
			self._update_instance(instance, session)

		return instance

	def cancel(self, instance_id: str, reason: str = "", session=None) -> WorkflowInstance:
		"""Cancel a running workflow instance."""
		instance = self._get_instance(instance_id, session)
		instance.status = "CANCELLED"
		instance.data["_cancel_reason"] = reason
		if session:
			self._update_instance(instance, session)
		return instance

	def get_pending_tasks(
		self,
		tenant_id: str,
		role: str = "",
		session=None,
	) -> list[dict[str, Any]]:
		"""Get all workflow steps waiting for user action.

		Queries the DB first (for multi-process correctness), then supplements
		with any in-memory instances not yet persisted.
		"""
		results: list[dict[str, Any]] = []
		seen_instances: set[str] = set()

		if session:
			try:
				rows = session.execute(sa.text("""
					SELECT instance_id, workflow_name, current_step_id,
					       step_label, assigned_role, data, created_at
					FROM pgaf_workflow_task
					WHERE tenant_id = :tid AND status = 'PENDING'
					  AND (:role = '' OR assigned_role = :role)
					ORDER BY created_at ASC
				"""), {"tid": tenant_id, "role": role}).fetchall()
				for r in rows:
					row_dict = dict(zip(r.keys(), r))
					results.append(row_dict)
					seen_instances.add(row_dict["instance_id"])
			except Exception as exc:
				log.debug("get_pending_tasks DB query failed: %s", exc)

		# Supplement with in-memory instances
		for instance in self._instances.values():
			if instance.tenant_id != tenant_id:
				continue
			if instance.id in seen_instances:
				continue
			step = self._get_current_step(instance)
			if step and step.get("type") == "UserTask":
				if not role or step.get("assignee_role") == role:
					results.append({
						"instance_id": instance.id,
						"workflow_name": instance.definition.name,
						"current_step_id": step["id"],
						"step_label": step.get("label", step["id"]),
						"assigned_role": step.get("assignee_role", ""),
						"data": instance.data,
					})

		return results

	def list_definitions(self) -> list[str]:
		"""Return names of all loaded workflow definitions."""
		return sorted(self._definitions.keys())

	def get_definition(self, name: str) -> WorkflowDefinition | None:
		return self._definitions.get(name)

	# ------------------------------------------------------------------
	# Internal step execution
	# ------------------------------------------------------------------

	def _get_current_step(self, instance: WorkflowInstance) -> dict[str, Any] | None:
		"""Return current step, skipping steps whose condition is False."""
		while instance.current_step_index < len(instance.definition.steps):
			step = instance.definition.steps[instance.current_step_index]
			condition = step.get("condition", "")
			if condition and not self._evaluate_condition(condition, instance.data):
				log.debug(
					"Skipping step %r (condition False): %s",
					step.get("id"), condition,
				)
				instance.current_step_index += 1
				continue
			return step
		return None

	def _advance(self, instance: WorkflowInstance, session=None) -> None:
		"""Advance through automated steps until a UserTask or end."""
		while True:
			step = self._get_current_step(instance)
			if step is None:
				instance.status = "COMPLETED"
				self._emit_completion_events(instance, session)
				break

			step_type = step.get("type", "UserTask")

			if step_type == "UserTask":
				instance.status = "WAITING"
				if session:
					self._create_task_record(instance, step, session)
				break

			elif step_type == "ServiceTask":
				self._execute_service_task(step, instance, session)
				instance.current_step_index += 1

			elif step_type == "ScriptTask":
				self._execute_script_task(step, instance)
				instance.current_step_index += 1

			elif step_type == "call_workflow":
				sub_instance = self._execute_call_workflow(step, instance, session)
				step_id = step.get("id", f"step_{instance.current_step_index}")
				instance.data[f"_sub_instance_{step_id}"] = sub_instance.id
				# Map declared outputs from the sub-instance data into this instance
				for out_key, src_path in (step.get("outputs") or {}).items():
					# src_path like "kyc_result.status" — resolve from sub-instance data
					parts = src_path.split(".", 1) if isinstance(src_path, str) and "." in src_path else [src_path]
					val = sub_instance.data.get(parts[0])
					if isinstance(val, dict) and len(parts) == 2:
						val = val.get(parts[1])
					instance.data[out_key] = val
				instance.current_step_index += 1

			elif step_type == "parallel":
				self._execute_parallel_step(step, instance, session)
				instance.current_step_index += 1

			else:
				# Unknown / gateway — advance past it
				log.debug("Skipping unhandled step type %r for step %r", step_type, step.get("id"))
				instance.current_step_index += 1

	def _evaluate_condition(self, condition: str, data: dict) -> bool:
		"""Evaluate a simple Python-like condition string safely.

		The expression has access to all keys in ``data``.  Dot-access on
		nested dicts (e.g. ``loan_officer_review.recommendation``) is
		resolved by flattening nested dicts into the eval namespace.
		"""
		namespace: dict[str, Any] = {}
		for key, val in data.items():
			namespace[key] = val
			# Expose nested dicts as attribute-accessible proxies
			if isinstance(val, dict):
				namespace[key] = _AttrDict(val)
		try:
			return bool(eval(condition, {"__builtins__": {}}, namespace))  # noqa: S307
		except Exception as exc:
			log.debug("Condition eval error (%r): %s — defaulting to True", condition, exc)
			return True

	def _execute_service_task(
		self, step: dict, instance: WorkflowInstance, session=None
	) -> None:
		service = step.get("service", "")
		log.info("Workflow service task: %r for instance %s", service, instance.id[:8])
		try:
			from pgappforge.plugins.workflow.engine import BPMActionRegistry
			input_map = step.get("input_map", {})
			resolved = self._resolve_input_map(input_map, instance)
			result = BPMActionRegistry.execute(service, resolved, session)
			instance.data[step["id"]] = result
		except Exception as exc:
			log.warning("Service task %r failed: %s", service, exc)
			instance.data[step["id"]] = {"status": "error", "message": str(exc)}

	def _execute_script_task(self, step: dict, instance: WorkflowInstance) -> None:
		script = step.get("script", "")
		if not script:
			return
		try:
			exec(script, {"__builtins__": {}}, instance.data)  # noqa: S102
		except Exception as exc:
			log.warning("ScriptTask %r failed: %s", step.get("id"), exc)

	def _execute_call_workflow(
		self, step: dict, instance: WorkflowInstance, session=None
	) -> "WorkflowInstance":
		"""Execute a call_workflow step — start a named sub-workflow.

		Resolves ``inputs`` values using ``{{variable}}`` template substitution
		against the current instance's data, then calls ``start()`` with
		``parent_instance_id`` set to the calling instance's ID.

		The sub-instance is returned; the caller is responsible for storing its
		ID and mapping declared ``outputs`` back into the parent instance data.
		"""
		workflow_name = step.get("workflow", "")
		if not workflow_name:
			raise ValueError(
				f"call_workflow step {step.get('id')!r} missing 'workflow' field"
			)

		# Resolve inputs: support $field and {{field}} notation
		raw_inputs: dict[str, Any] = step.get("inputs") or {}
		resolved_inputs: dict[str, Any] = {}
		import re as _re_local
		for key, val in raw_inputs.items():
			if isinstance(val, str):
				if val.startswith("$"):
					resolved_inputs[key] = instance.data.get(val[1:])
				elif "{{" in val:
					def _sub(m: Any, _data: dict = instance.data) -> str:
						return str(_data.get(m.group(1), ""))
					resolved_inputs[key] = _re_local.sub(r"\{\{(\w+)\}\}", _sub, val)
				else:
					resolved_inputs[key] = val
			else:
				resolved_inputs[key] = val

		log.info(
			"call_workflow: launching %r from parent=%s step=%r",
			workflow_name, instance.id[:8], step.get("id"),
		)
		sub_instance = self.start(
			workflow_name,
			resolved_inputs,
			instance.tenant_id,
			session=session,
			parent_instance_id=instance.id,
		)
		return sub_instance

	def _execute_parallel_step(
		self, step: dict, instance: WorkflowInstance, session=None
	) -> None:
		"""Execute a parallel step — run named branches concurrently.

		Each branch gets a deep copy of ``instance.data`` to prevent data
		races.  After all branches finish (join='all') or the first succeeds
		(join='any'), branch results are merged back as
		``instance.data[branch_name]``.

		Step YAML shape::

		    - type: parallel
		      id: parallel_checks
		      timeout_seconds: 60   # per-branch wall-clock limit (default 60)
		      join: all             # 'all' or 'any' (default 'all')
		      branches:
		        credit_check:
		          steps:
		            - type: action
		              action: crm.cpq.credit_check
		        kyc_check:
		          steps:
		            - type: action
		              action: grc.kyc.verify

		On branch failure:
		- join=all  → raises RuntimeError, marking the parallel step as failed
		- join=any  → logs the failure and continues as long as one branch succeeds
		"""
		raw_branches = step.get("branches") or {}
		# Accept list of step-lists [[steps_a], [steps_b]] or dict {name: {steps: [...]}}
		if isinstance(raw_branches, list):
			branches: dict[str, dict] = {
				f"branch_{i}": {"steps": b if isinstance(b, list) else b.get("steps", [])}
				for i, b in enumerate(raw_branches)
			}
		else:
			branches = raw_branches
		if not branches:
			log.warning("parallel step %r has no branches — skipping", step.get("id"))
			return

		join_mode: str = step.get("join", "all")
		timeout_seconds: int = int(step.get("timeout_seconds", 60))

		branch_results: dict[str, Any] = {}
		branch_errors: dict[str, str] = {}
		lock = threading.Lock()

		def _run_branch(branch_name: str, branch_def: dict) -> None:
			"""Target for each worker thread."""
			branch_data = copy.deepcopy(instance.data)
			branch_steps: list[dict] = branch_def.get("steps") or []
			try:
				# Build a minimal WorkflowDefinition + WorkflowInstance for this branch
				from .models import WorkflowDefinition, WorkflowInstance as _WFI
				branch_defn = WorkflowDefinition(
					name=f"{instance.definition.name}.__branch__.{branch_name}",
					steps=branch_steps,
				)
				branch_inst = _WFI(
					definition=branch_defn,
					data=branch_data,
					tenant_id=instance.tenant_id,
				)
				self._advance(branch_inst, session=None)  # no DB in branches
				with lock:
					branch_results[branch_name] = branch_inst.data
				log.debug(
					"parallel branch %r completed (parent=%s)",
					branch_name, instance.id[:8],
				)
			except Exception as exc:
				log.warning(
					"parallel branch %r failed (parent=%s): %s",
					branch_name, instance.id[:8], exc,
				)
				with lock:
					branch_errors[branch_name] = str(exc)

		threads = {
			name: threading.Thread(
				target=_run_branch,
				args=(name, defn),
				name=f"wf-branch-{name}",
				daemon=True,
			)
			for name, defn in branches.items()
		}

		for t in threads.values():
			t.start()

		if join_mode == "any":
			# Poll until one branch finishes successfully or all are done
			import time as _time
			deadline = _time.monotonic() + timeout_seconds
			while _time.monotonic() < deadline:
				with lock:
					if branch_results:
						break
					all_done = all(not t.is_alive() for t in threads.values())
					if all_done:
						break
				_time.sleep(0.05)
			# Cancel remaining (daemon threads will die naturally)
		else:
			# join=all — wait for every branch up to timeout
			for t in threads.values():
				t.join(timeout=timeout_seconds)
			# Check for timed-out threads
			for name, t in threads.items():
				if t.is_alive():
					branch_errors[name] = f"timed out after {timeout_seconds}s"
					log.warning(
						"parallel branch %r timed out (parent=%s)",
						name, instance.id[:8],
					)

		# Merge results back into instance data, keyed by the parallel step id
		with lock:
			step_output: dict[str, Any] = {}
			for branch_name, result_data in branch_results.items():
				step_output[branch_name] = result_data
			instance.data[step["id"]] = step_output

		# Error handling
		if branch_errors:
			if join_mode == "all":
				failed = sorted(branch_errors)
				detail = "; ".join(f"{n}: {e}" for n, e in branch_errors.items())
				raise RuntimeError(
					f"parallel step {step.get('id')!r}: branches failed: {failed} — {detail}"
				)
			else:
				# join=any: succeed if at least one branch finished
				if not branch_results:
					detail = "; ".join(f"{n}: {e}" for n, e in branch_errors.items())
					raise RuntimeError(
						f"parallel step {step.get('id')!r}: all branches failed — {detail}"
					)
				log.info(
					"parallel step %r: join=any — %d succeeded, %d failed",
					step.get("id"), len(branch_results), len(branch_errors),
				)

	def _resolve_input_map(
		self, input_map: dict[str, str], instance: WorkflowInstance
	) -> dict[str, Any]:
		"""Resolve input_map values like 'application.phone_number' from instance.data."""
		resolved: dict[str, Any] = {}
		for out_key, src_expr in input_map.items():
			if isinstance(src_expr, str) and "." in src_expr:
				parts = src_expr.split(".", 1)
				root = instance.data.get(parts[0], {})
				if isinstance(root, dict):
					resolved[out_key] = root.get(parts[1], src_expr)
				else:
					resolved[out_key] = src_expr
			else:
				resolved[out_key] = instance.data.get(str(src_expr), src_expr)
		return resolved

	def _emit_completion_events(
		self, instance: WorkflowInstance, session=None
	) -> None:
		event_name = (
			instance.definition.on_complete.get("emit_event")
			or f"workflow.{instance.definition.name}.completed"
		)
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
			emit_event(event_name, instance.data)
			log.debug("Emitted completion event %r for instance %s", event_name, instance.id[:8])
		except Exception:
			log.debug("emit_completion_events skipped (event bus unavailable)")

	# ------------------------------------------------------------------
	# Persistence helpers
	# ------------------------------------------------------------------

	def _get_instance(self, instance_id: str, session=None) -> WorkflowInstance:
		if instance_id in self._instances:
			return self._instances[instance_id]

		if session:
			try:
				row = session.execute(sa.text(
					"SELECT * FROM pgaf_workflow_instance WHERE id = :id"
				), {"id": instance_id}).fetchone()
				if row:
					rdict = dict(zip(row.keys(), row))
					defn = self._definitions.get(rdict["workflow_name"])
					if defn:
						inst = WorkflowInstance(
							definition=defn,
							data=json.loads(rdict.get("data") or "{}"),
							tenant_id=rdict["tenant_id"],
						)
						inst.id = instance_id
						inst.status = rdict["status"]
						inst.current_step_index = int(rdict.get("current_step_index") or 0)
						self._instances[instance_id] = inst
						return inst
			except Exception as exc:
				log.debug("Load instance from DB failed: %s", exc)

		raise ValueError(f"Workflow instance {instance_id!r} not found")

	def _persist_instance(self, instance: WorkflowInstance, session) -> None:
		try:
			session.execute(sa.text("""
				INSERT INTO pgaf_workflow_instance
				(id, workflow_name, tenant_id, status, data, current_step_index, created_at)
				VALUES (:id, :name, :tid, :status, :data::jsonb, :step_idx, :now)
			"""), {
				"id": instance.id,
				"name": instance.definition.name,
				"tid": instance.tenant_id,
				"status": instance.status,
				"data": json.dumps(instance.data),
				"step_idx": instance.current_step_index,
				"now": instance.created_at,
			})
		except Exception as exc:
			log.debug("_persist_instance failed: %s", exc)

	def _update_instance(self, instance: WorkflowInstance, session) -> None:
		try:
			session.execute(sa.text("""
				UPDATE pgaf_workflow_instance
				SET status = :status, data = :data::jsonb,
				    current_step_index = :step_idx, updated_at = NOW()
				WHERE id = :id
			"""), {
				"id": instance.id,
				"status": instance.status,
				"data": json.dumps(instance.data),
				"step_idx": instance.current_step_index,
			})
		except Exception as exc:
			log.debug("_update_instance failed: %s", exc)

	def _create_task_record(
		self, instance: WorkflowInstance, step: dict, session
	) -> None:
		try:
			from uuid6 import uuid7
			session.execute(sa.text("""
				INSERT INTO pgaf_workflow_task
				(id, instance_id, workflow_name, tenant_id, current_step_id,
				 step_label, assigned_role, data, status, created_at)
				VALUES (:id, :inst_id, :wf_name, :tid, :step_id,
				        :label, :role, :data::jsonb, 'PENDING', NOW())
				ON CONFLICT (instance_id, current_step_id) DO NOTHING
			"""), {
				"id": str(uuid7()),
				"inst_id": instance.id,
				"wf_name": instance.definition.name,
				"tid": instance.tenant_id,
				"step_id": step["id"],
				"label": step.get("label", step["id"]),
				"role": step.get("assignee_role", ""),
				"data": json.dumps(instance.data),
			})
		except Exception as exc:
			log.debug("_create_task_record failed: %s", exc)


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

def create_workflow_tables(engine) -> None:
	"""Create workflow persistence tables (idempotent)."""
	with engine.begin() as conn:
		conn.execute(sa.text("""
		CREATE TABLE IF NOT EXISTS pgaf_workflow_instance (
			id                  VARCHAR(36)  PRIMARY KEY,
			workflow_name       VARCHAR(100) NOT NULL,
			tenant_id           VARCHAR(36)  NOT NULL,
			status              VARCHAR(15)  NOT NULL DEFAULT 'RUNNING',
			data                JSONB        NOT NULL DEFAULT '{}',
			current_step_index  INTEGER      NOT NULL DEFAULT 0,
			created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
			updated_at          TIMESTAMPTZ
		);
		CREATE TABLE IF NOT EXISTS pgaf_workflow_task (
			id              VARCHAR(36)  PRIMARY KEY,
			instance_id     VARCHAR(36)  NOT NULL REFERENCES pgaf_workflow_instance(id),
			workflow_name   VARCHAR(100) NOT NULL,
			tenant_id       VARCHAR(36)  NOT NULL,
			current_step_id VARCHAR(100) NOT NULL,
			step_label      VARCHAR(200),
			assigned_role   VARCHAR(100),
			data            JSONB        NOT NULL DEFAULT '{}',
			status          VARCHAR(15)  NOT NULL DEFAULT 'PENDING',
			created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
			completed_at    TIMESTAMPTZ,
			completed_by    VARCHAR(255),
			UNIQUE(instance_id, current_step_id)
		);
		CREATE INDEX IF NOT EXISTS ix_pgaf_wf_instance_tenant
			ON pgaf_workflow_instance(tenant_id, status);
		CREATE INDEX IF NOT EXISTS ix_pgaf_wf_task_tenant
			ON pgaf_workflow_task(tenant_id, status);
		CREATE INDEX IF NOT EXISTS ix_pgaf_wf_task_role
			ON pgaf_workflow_task(assigned_role, status);
		"""))


# ---------------------------------------------------------------------------
# Attribute-dict helper for condition evaluation
# ---------------------------------------------------------------------------

class _AttrDict(dict):
	"""Dict subclass that allows attribute-style access for condition eval."""

	def __getattr__(self, item: str) -> Any:
		try:
			return self[item]
		except KeyError:
			raise AttributeError(item)


__all__ = [
	"PgAppForgeWorkflowEngine",
	"WorkflowDefinition",
	"WorkflowInstance",
	"create_workflow_tables",
]
