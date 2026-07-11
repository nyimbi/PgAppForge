"""
pgappforge/plugins/erp/platform/workflow_designer/views.py

Visual workflow designer — drag-and-drop UI built on Drawflow (MIT).
Saves/loads workflows as YAML for PgAppForgeWorkflowEngine (Phase 1).
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import render_template, request, jsonify
from pgappforge.baseviews import expose
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class WorkflowDesignerView(BaseERPView):
	"""Visual drag-and-drop workflow designer for PgAppForge.

	Uses Drawflow (MIT) — a lightweight drag-and-drop flow editor.
	Saves workflows as YAML for the PgAppForgeWorkflowEngine.

	Routes
	------
	GET  /platform/workflow/              — workflow definition list
	GET  /platform/workflow/design        — new workflow canvas
	GET  /platform/workflow/design/<name> — edit existing workflow
	POST /platform/workflow/save          — persist designer → YAML
	POST /platform/workflow/start         — start a workflow instance
	GET  /platform/workflow/inbox         — task inbox for current user
	POST /platform/workflow/complete/<instance_id>/<step_id>
	"""

	route_base = "/platform/workflow"

	# ------------------------------------------------------------------
	# Index — list all workflow definitions
	# ------------------------------------------------------------------

	@expose("/")
	@has_access
	def index(self):
		"""List all workflow definitions found in the workflows/ directory."""
		definitions: list[dict] = []
		workflows_dir = Path("workflows")
		if workflows_dir.exists():
			for yaml_path in sorted(workflows_dir.glob("*.yaml")):
				try:
					import yaml
					data = yaml.safe_load(yaml_path.read_text()) or {}
					definitions.append({
						"name": data.get("name", yaml_path.stem),
						"description": data.get("description", ""),
						"steps": len(data.get("steps", [])),
						"file": yaml_path.name,
						"slug": yaml_path.stem,
					})
				except Exception as exc:
					log.debug("Could not parse %s: %s", yaml_path, exc)

		kpi_html = self.kpi_cards([
			{
				"label": "Workflows",
				"value": len(definitions),
				"icon": "fa-sitemap",
				"color": "#1a56db",
			},
			{
				"label": "Active Instances",
				"value": self._count_active_instances(),
				"icon": "fa-play-circle",
				"color": "#0e9f6e",
			},
			{
				"label": "Pending Tasks",
				"value": self._count_pending_tasks(),
				"icon": "fa-clock-o",
				"color": "#ff5a1f",
			},
		])

		return render_template(
			"appbuilder/workflow/designer.html",
			definitions=definitions,
			kpi_html=kpi_html,
			design_mode=False,
			workflow_data={},
			workflow_name="",
			appbuilder=self.appbuilder,
		)

	# ------------------------------------------------------------------
	# Designer canvas — new or existing workflow
	# ------------------------------------------------------------------

	@has_access
	@expose("/design")
	@expose("/design/<workflow_name>")
	@has_access
	def design(self, workflow_name: str = ""):
		"""Open the visual workflow designer for a specific workflow (or new)."""
		workflow_data: dict = {}
		if workflow_name:
			yaml_path = Path("workflows") / f"{workflow_name}.yaml"
			if yaml_path.exists():
				try:
					import yaml
					workflow_data = yaml.safe_load(yaml_path.read_text()) or {}
				except Exception as exc:
					log.warning("Could not load workflow %r: %s", workflow_name, exc)

		return render_template(
			"appbuilder/workflow/designer.html",
			definitions=[],
			kpi_html="",
			design_mode=True,
			workflow_data=workflow_data,
			workflow_name=workflow_name,
			appbuilder=self.appbuilder,
		)

	# ------------------------------------------------------------------
	# Save — designer → YAML
	# ------------------------------------------------------------------

	@expose("/save", methods=["POST"])
	@has_access
	def save_workflow(self):
		"""Save a workflow definition from the visual designer.

		Accepts the Drawflow export JSON + metadata, converts node graph
		to the PgAppForge YAML DSL, writes to workflows/<name>.yaml.

		Request JSON::

			{
				"name": "sacco_loan_approval",
				"description": "...",
				"nodes": {<drawflow node map>},
				"connections": {<drawflow connection map>}
			}

		Response JSON::

			{"success": true, "file": "workflows/sacco_loan_approval.yaml", "workflow_name": "..."}
		"""
		data = request.get_json(force=True) or {}
		raw_name = data.get("name", "").strip()
		if not raw_name:
			return jsonify({"success": False, "error": "Workflow name is required"}), 400

		workflow_name = raw_name.lower().replace(" ", "_").replace("-", "_")
		yaml_def = self._nodes_to_yaml(data, workflow_name)

		try:
			import yaml
			workflows_dir = Path("workflows")
			workflows_dir.mkdir(exist_ok=True)
			yaml_path = workflows_dir / f"{workflow_name}.yaml"
			yaml_path.write_text(
				yaml.dump(yaml_def, default_flow_style=False, allow_unicode=True),
				encoding="utf-8",
			)
			log.info("Workflow saved: %s (%d steps)", workflow_name, len(yaml_def.get("steps", [])))
			return jsonify({
				"success": True,
				"file": str(yaml_path),
				"workflow_name": workflow_name,
				"steps": len(yaml_def.get("steps", [])),
			})
		except Exception as exc:
			log.exception("save_workflow failed")
			return jsonify({"success": False, "error": str(exc)}), 500

	# ------------------------------------------------------------------
	# Start a workflow instance
	# ------------------------------------------------------------------

	@expose("/start", methods=["POST"])
	@has_access
	def start_workflow(self):
		"""Start a workflow instance from the UI.

		Request JSON::

			{"workflow_name": "sacco_loan_approval", "data": {...}}

		Response JSON::

			{"success": true, "instance_id": "...", "status": "WAITING"}
		"""
		data = request.get_json(force=True) or {}
		workflow_name = data.get("workflow_name", "").strip()
		instance_data = data.get("data") or {}

		if not workflow_name:
			return jsonify({"success": False, "error": "workflow_name is required"}), 400

		try:
			from pgappforge.workflow.engine import PgAppForgeWorkflowEngine
			engine = PgAppForgeWorkflowEngine()
			yaml_path = Path("workflows") / f"{workflow_name}.yaml"
			if yaml_path.exists():
				engine.load_yaml(yaml_path)
			else:
				return jsonify({
					"success": False,
					"error": f"Workflow file not found: {yaml_path}",
				}), 404

			session = self._session()
			tenant_id = self._tenant_id()
			instance = engine.start(workflow_name, instance_data, tenant_id, session=session)
			session.commit()

			return jsonify({
				"success": True,
				"instance_id": instance.id,
				"status": instance.status,
			})
		except Exception as exc:
			log.exception("start_workflow failed")
			return jsonify({"success": False, "error": str(exc)}), 500

	# ------------------------------------------------------------------
	# Task inbox
	# ------------------------------------------------------------------

	@expose("/inbox")
	@has_access
	def task_inbox(self):
		"""Show pending workflow tasks assigned to the current user's role."""
		from pgappforge.workflow.engine import PgAppForgeWorkflowEngine

		engine = PgAppForgeWorkflowEngine()
		session = self._session()
		tenant_id = self._tenant_id()

		user_role = ""
		try:
			from flask_login import current_user
			if current_user and current_user.is_authenticated and current_user.roles:
				user_role = current_user.roles[0].name
		except Exception:
			pass

		tasks = engine.get_pending_tasks(tenant_id, role=user_role, session=session)

		# Enrich tasks with SLA metadata
		from datetime import datetime, timezone, timedelta
		now = datetime.now(timezone.utc)
		enriched: list[dict] = []
		for t in tasks:
			created_raw = t.get("created_at")
			if created_raw and not isinstance(created_raw, datetime):
				try:
					created_raw = datetime.fromisoformat(str(created_raw))
				except Exception:
					created_raw = None

			age_hours = 0
			sla_status = "ok"
			sla_label = ""
			if created_raw:
				if created_raw.tzinfo is None:
					created_raw = created_raw.replace(tzinfo=timezone.utc)
				age_hours = (now - created_raw).total_seconds() / 3600
				if age_hours > 48:
					sla_status = "overdue"
					sla_label = f"{int(age_hours)}h overdue"
				elif age_hours > 24:
					sla_status = "warning"
					sla_label = f"{int(age_hours)}h elapsed"
				else:
					sla_status = "ok"
					sla_label = f"{int(age_hours)}h ago"

			task_data = t.get("data") or {}
			enriched.append({
				**t,
				"age_hours": round(age_hours, 1),
				"sla_status": sla_status,
				"sla_label": sla_label,
				"data_preview": _truncate_dict(task_data),
			})

		return render_template(
			"appbuilder/workflow/task_inbox.html",
			tasks=enriched,
			user_role=user_role,
			appbuilder=self.appbuilder,
		)

	# ------------------------------------------------------------------
	# Complete a task step
	# ------------------------------------------------------------------

	@expose("/complete/<instance_id>/<step_id>", methods=["POST"])
	@has_access
	def complete_task(self, instance_id: str, step_id: str):
		"""Mark a workflow task complete with form data.

		Request JSON: any key/value form fields submitted by the user.

		Response JSON::

			{
				"success": true,
				"instance_id": "...",
				"new_status": "WAITING"|"COMPLETED",
				"current_step": {...}|null
			}
		"""
		form_data = request.get_json(force=True) or {}

		try:
			from pgappforge.workflow.engine import PgAppForgeWorkflowEngine
			engine = PgAppForgeWorkflowEngine()
			session = self._session()

			completed_by = ""
			try:
				from flask_login import current_user
				if current_user and current_user.is_authenticated:
					completed_by = current_user.email or current_user.username or ""
			except Exception:
				pass

			# Re-hydrate definition from YAML so engine knows the workflow
			import sqlalchemy as sa
			try:
				row = session.execute(sa.text(
					"SELECT workflow_name FROM pgaf_workflow_instance WHERE id = :id"
				), {"id": instance_id}).fetchone()
				if row:
					wf_name = row[0]
					yaml_path = Path("workflows") / f"{wf_name}.yaml"
					if yaml_path.exists():
						engine.load_yaml(yaml_path)
			except Exception as exc:
				log.debug("Could not pre-load workflow definition: %s", exc)

			instance = engine.complete_step(
				instance_id, step_id, form_data,
				completed_by=completed_by, session=session,
			)
			session.commit()

			return jsonify({
				"success": True,
				"instance_id": instance_id,
				"new_status": instance.status,
				"current_step": engine._get_current_step(instance),
			})
		except Exception as exc:
			log.exception("complete_task failed")
			return jsonify({"success": False, "error": str(exc)}), 500

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _nodes_to_yaml(self, designer_data: dict, workflow_name: str) -> dict:
		"""Convert Drawflow node export format to PgAppForge YAML DSL.

		Drawflow export structure::

			{
				"drawflow": {
					"Home": {
						"data": {
							"<node_id>": {
								"id": <int>,
								"name": "UserTask"|"ServiceTask"|"Gateway",
								"data": {"id": "step_id", "label": "...", "role": "...",
								         "condition": "...", "sla_hours": <int>},
								"outputs": {"output_1": {"connections": [{"node": "3", ...}]}}
							}
						}
					}
				}
			}
		"""
		# Support both wrapped Drawflow export and simple flat nodes dict
		df_export = designer_data.get("drawflow", {})
		if df_export:
			home = df_export.get("Home", {})
			raw_nodes = home.get("data", {})
		else:
			raw_nodes = designer_data.get("nodes", {})

		# Build adjacency list from output connections
		next_node: dict[str, str] = {}
		for node_id, node in raw_nodes.items():
			outputs = node.get("outputs", {})
			for _out_name, out_info in outputs.items():
				for conn in (out_info.get("connections") or []):
					target_node = str(conn.get("node", ""))
					if target_node and node_id not in next_node:
						next_node[node_id] = target_node

		# Topological order: find start node (no incoming edges) then follow chain
		all_targets = set(next_node.values())
		start_candidates = [nid for nid in raw_nodes if nid not in all_targets]
		ordered_ids: list[str] = []
		visited: set[str] = set()

		def _walk(nid: str) -> None:
			if nid in visited or nid not in raw_nodes:
				return
			visited.add(nid)
			ordered_ids.append(nid)
			if nid in next_node:
				_walk(next_node[nid])

		for start_id in start_candidates:
			_walk(start_id)
		# Catch any disconnected nodes not yet visited
		for nid in raw_nodes:
			_walk(nid)

		steps: list[dict] = []
		for node_id in ordered_ids:
			node = raw_nodes[node_id]
			node_name = node.get("name", "UserTask")
			d = node.get("data") or {}
			step_id = d.get("id") or f"step_{node_id}"
			step: dict = {
				"id": step_id,
				"type": node_name,
				"label": d.get("label") or node_name,
			}
			if d.get("assignee_role") or d.get("role"):
				step["assignee_role"] = d.get("assignee_role") or d.get("role")
			if d.get("condition"):
				step["condition"] = d["condition"]
			if d.get("sla_hours"):
				try:
					step["sla_hours"] = int(d["sla_hours"])
				except (ValueError, TypeError):
					pass
			if d.get("service"):
				step["service"] = d["service"]
			steps.append(step)

		return {
			"name": workflow_name,
			"description": designer_data.get("description", ""),
			"steps": steps,
		}

	def _count_active_instances(self) -> int:
		try:
			import sqlalchemy as sa
			session = self._session()
			return session.execute(sa.text(
				"SELECT COUNT(*) FROM pgaf_workflow_instance "
				"WHERE status IN ('RUNNING','WAITING')"
			)).scalar_one() or 0
		except Exception:
			return 0

	def _count_pending_tasks(self) -> int:
		try:
			import sqlalchemy as sa
			session = self._session()
			return session.execute(sa.text(
				"SELECT COUNT(*) FROM pgaf_workflow_task WHERE status = 'PENDING'"
			)).scalar_one() or 0
		except Exception:
			return 0


def _truncate_dict(d: dict, max_keys: int = 5, max_val_len: int = 60) -> dict:
	"""Return a shallow copy of d with at most max_keys entries, values truncated."""
	out: dict = {}
	for i, (k, v) in enumerate(d.items()):
		if i >= max_keys:
			break
		s = str(v)
		out[str(k)] = s if len(s) <= max_val_len else s[:max_val_len] + "…"
	return out


__all__ = ["WorkflowDesignerView"]
