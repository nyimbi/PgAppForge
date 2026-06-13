"""
tests/ci/test_workflow_engine.py

CI tests for the YAML workflow engine:
  - yaml_dsl: parsing + validation
  - engine: definition loading, instance lifecycle, step advance, conditions
  - workflow tables DDL
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pgappforge.workflow.yaml_dsl import (
	WorkflowDSLError,
	parse_yaml_string,
	validate_and_normalise,
	load_directory,
)
from pgappforge.workflow.engine import (
	PgAppForgeWorkflowEngine,
	create_workflow_tables,
)
from pgappforge.workflow.models import WorkflowDefinition, WorkflowInstance


# ---------------------------------------------------------------------------
# Sample YAML fixtures
# ---------------------------------------------------------------------------

_SIMPLE_YAML = textwrap.dedent("""
	name: test_simple
	description: "Two-step approval"
	steps:
	  - id: manager_review
	    type: UserTask
	    label: "Manager Review"
	    assignee_role: "Manager"
	    form_fields:
	      - name: decision
	        type: choice
	        choices: [APPROVE, REJECT]
	  - id: notify
	    type: ServiceTask
	    label: "Send notification"
	    service: "notify.email"
""")

_CONDITIONAL_YAML = textwrap.dedent("""
	name: test_conditional
	steps:
	  - id: step_a
	    type: UserTask
	    assignee_role: "Role A"
	    form_fields:
	      - name: result
	        type: choice
	        choices: [YES, NO]
	  - id: step_b
	    type: UserTask
	    condition: "step_a['result'] == 'YES'"
	    assignee_role: "Role B"
	    form_fields:
	      - name: note
	        type: text
	  - id: done
	    type: ServiceTask
	    service: "noop"
""")


# ---------------------------------------------------------------------------
# yaml_dsl tests
# ---------------------------------------------------------------------------

class TestYamlDsl:

	def test_parse_simple_yaml(self):
		data = parse_yaml_string(_SIMPLE_YAML)
		assert data["name"] == "test_simple"
		assert len(data["steps"]) == 2
		assert data["steps"][0]["id"] == "manager_review"
		assert data["steps"][1]["type"] == "ServiceTask"

	def test_default_step_type_is_user_task(self):
		yaml = textwrap.dedent("""
			name: defaults
			steps:
			  - id: my_step
			    assignee_role: "Anyone"
		""")
		data = parse_yaml_string(yaml)
		assert data["steps"][0]["type"] == "UserTask"

	def test_default_label_from_id(self):
		yaml = textwrap.dedent("""
			name: label_test
			steps:
			  - id: loan_officer_review
		""")
		data = parse_yaml_string(yaml)
		assert data["steps"][0]["label"] == "Loan Officer Review"

	def test_missing_name_raises(self):
		with pytest.raises(WorkflowDSLError, match="missing required keys"):
			parse_yaml_string("steps: []")

	def test_missing_steps_raises(self):
		with pytest.raises(WorkflowDSLError, match="missing required keys"):
			parse_yaml_string("name: foo")

	def test_duplicate_step_ids_raise(self):
		yaml = textwrap.dedent("""
			name: dup
			steps:
			  - id: step_a
			  - id: step_a
		""")
		with pytest.raises(WorkflowDSLError, match="duplicate step id"):
			parse_yaml_string(yaml)

	def test_step_missing_id_raises(self):
		yaml = textwrap.dedent("""
			name: no_id
			steps:
			  - type: UserTask
			    label: "No ID"
		""")
		with pytest.raises(WorkflowDSLError, match="missing required 'id'"):
			parse_yaml_string(yaml)

	def test_unknown_step_type_warns_and_defaults(self, caplog):
		import logging
		yaml = textwrap.dedent("""
			name: weird_type
			steps:
			  - id: my_step
			    type: AncientRitual
		""")
		with caplog.at_level(logging.WARNING):
			data = parse_yaml_string(yaml)
		assert data["steps"][0]["type"] == "UserTask"
		assert "AncientRitual" in caplog.text

	def test_load_directory(self, tmp_path):
		(tmp_path / "wf1.yaml").write_text("name: wf1\nsteps:\n  - id: s1\n")
		(tmp_path / "wf2.yaml").write_text("name: wf2\nsteps:\n  - id: s2\n")
		(tmp_path / "not_yaml.txt").write_text("ignore me")

		results = load_directory(tmp_path)
		assert len(results) == 2
		names = {r["name"] for r in results}
		assert names == {"wf1", "wf2"}

	def test_load_directory_skips_invalid(self, tmp_path):
		(tmp_path / "good.yaml").write_text("name: good\nsteps:\n  - id: s1\n")
		(tmp_path / "bad.yaml").write_text("steps: []")  # missing name

		results = load_directory(tmp_path)
		assert len(results) == 1
		assert results[0]["name"] == "good"


# ---------------------------------------------------------------------------
# WorkflowDefinition model tests
# ---------------------------------------------------------------------------

class TestWorkflowDefinition:

	def test_step_by_id_found(self):
		defn = WorkflowDefinition(name="x", steps=[
			{"id": "alpha", "type": "UserTask"},
			{"id": "beta", "type": "ServiceTask"},
		])
		step = defn.step_by_id("beta")
		assert step is not None
		assert step["type"] == "ServiceTask"

	def test_step_by_id_not_found_returns_none(self):
		defn = WorkflowDefinition(name="x", steps=[{"id": "alpha"}])
		assert defn.step_by_id("missing") is None

	def test_empty_name_raises(self):
		with pytest.raises(ValueError, match="name must not be empty"):
			WorkflowDefinition(name="", steps=[])

	def test_repr(self):
		defn = WorkflowDefinition(name="my_wf", steps=[{"id": "s1"}])
		assert "my_wf" in repr(defn)
		assert "1" in repr(defn)


# ---------------------------------------------------------------------------
# PgAppForgeWorkflowEngine tests
# ---------------------------------------------------------------------------

class TestWorkflowEngine:

	def _engine_with_simple(self) -> PgAppForgeWorkflowEngine:
		eng = PgAppForgeWorkflowEngine()
		eng.load_yaml_string(_SIMPLE_YAML)
		return eng

	def test_load_yaml_string(self):
		eng = PgAppForgeWorkflowEngine()
		defn = eng.load_yaml_string(_SIMPLE_YAML)
		assert defn.name == "test_simple"
		assert "test_simple" in eng.list_definitions()

	def test_load_dict(self):
		eng = PgAppForgeWorkflowEngine()
		defn = eng.load_dict({
			"name": "dict_wf",
			"steps": [{"id": "s1", "type": "UserTask"}],
		})
		assert defn.name == "dict_wf"

	def test_start_unknown_workflow_raises(self):
		eng = PgAppForgeWorkflowEngine()
		with pytest.raises(ValueError, match="not found"):
			eng.start("nonexistent", {}, tenant_id="t1")

	def test_start_waits_at_first_user_task(self):
		eng = self._engine_with_simple()
		instance = eng.start("test_simple", {}, tenant_id="t1")
		assert instance.status == "WAITING"
		assert instance.current_step_index == 0

	def test_complete_step_advances(self):
		eng = self._engine_with_simple()
		instance = eng.start("test_simple", {}, tenant_id="t1")
		assert instance.status == "WAITING"

		with patch.object(eng, "_execute_service_task"):
			instance = eng.complete_step(
				instance.id, "manager_review", {"decision": "APPROVE"}, completed_by="alice"
			)

		assert instance.status == "COMPLETED"
		assert instance.data["manager_review"]["decision"] == "APPROVE"
		assert len(instance.step_history) == 1
		assert instance.step_history[0]["completed_by"] == "alice"

	def test_complete_wrong_step_raises(self):
		eng = self._engine_with_simple()
		instance = eng.start("test_simple", {}, tenant_id="t1")
		with pytest.raises(ValueError, match="Current step is"):
			eng.complete_step(instance.id, "wrong_step_id", {})

	def test_cancel_sets_status(self):
		eng = self._engine_with_simple()
		instance = eng.start("test_simple", {}, tenant_id="t1")
		cancelled = eng.cancel(instance.id, reason="duplicate request")
		assert cancelled.status == "CANCELLED"
		assert cancelled.data["_cancel_reason"] == "duplicate request"

	def test_load_all_from_directory(self, tmp_path):
		(tmp_path / "wf1.yaml").write_text("name: wf_dir_1\nsteps:\n  - id: s1\n")
		(tmp_path / "wf2.yaml").write_text("name: wf_dir_2\nsteps:\n  - id: s1\n")
		eng = PgAppForgeWorkflowEngine()
		count = eng.load_all_from_directory(tmp_path)
		assert count == 2
		assert "wf_dir_1" in eng.list_definitions()
		assert "wf_dir_2" in eng.list_definitions()


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

class TestConditionEval:

	def _eng(self):
		eng = PgAppForgeWorkflowEngine()
		eng.load_yaml_string(_CONDITIONAL_YAML)
		return eng

	def test_step_skipped_when_condition_false(self):
		"""step_b has condition step_a['result'] == 'YES'; if NO, skip to done."""
		eng = self._eng()
		instance = eng.start("test_conditional", {}, tenant_id="t1")
		# step_a is UserTask — should be WAITING
		assert instance.status == "WAITING"
		step = instance.current_step()
		assert step["id"] == "step_a"

		with patch.object(eng, "_execute_service_task"):
			instance = eng.complete_step(instance.id, "step_a", {"result": "NO"})

		# step_b condition is False → skipped → done ServiceTask → COMPLETED
		assert instance.status == "COMPLETED"

	def test_step_executed_when_condition_true(self):
		"""step_b condition True when result == YES — should stop at step_b."""
		eng = self._eng()
		instance = eng.start("test_conditional", {}, tenant_id="t1")
		instance = eng.complete_step(instance.id, "step_a", {"result": "YES"})
		# step_b condition is now True — should be WAITING at step_b
		assert instance.status == "WAITING"
		assert instance.current_step()["id"] == "step_b"

	def test_malformed_condition_defaults_to_true(self):
		eng = PgAppForgeWorkflowEngine()
		instance_mock = MagicMock()
		instance_mock.data = {}
		result = eng._evaluate_condition("invalid python !!!", {})
		assert result is True


# ---------------------------------------------------------------------------
# Real YAML example files
# ---------------------------------------------------------------------------

class TestExampleYamlFiles:

	def _workflows_dir(self) -> Path:
		return Path(__file__).parent.parent.parent / "workflows"

	def test_sacco_loan_approval_parses(self):
		path = self._workflows_dir() / "sacco_loan_approval.yaml"
		if not path.exists():
			pytest.skip("workflows/ directory not present")
		data = parse_yaml_string(path.read_text())
		assert data["name"] == "sacco_loan_approval"
		step_ids = [s["id"] for s in data["steps"]]
		assert "loan_officer_review" in step_ids
		assert "disburse" in step_ids

	def test_purchase_order_approval_parses(self):
		path = self._workflows_dir() / "purchase_order_approval.yaml"
		if not path.exists():
			pytest.skip("workflows/ directory not present")
		data = parse_yaml_string(path.read_text())
		assert data["name"] == "purchase_order_approval"
		step_ids = [s["id"] for s in data["steps"]]
		assert "department_head_review" in step_ids
		assert "issue_lpo" in step_ids

	def test_leave_request_parses(self):
		path = self._workflows_dir() / "leave_request.yaml"
		if not path.exists():
			pytest.skip("workflows/ directory not present")
		data = parse_yaml_string(path.read_text())
		assert data["name"] == "leave_request"
		step_ids = [s["id"] for s in data["steps"]]
		assert "line_manager_approval" in step_ids
		assert "update_leave_records" in step_ids


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

class TestCreateWorkflowTables:

	def test_ddl_executes_without_error(self):
		mock_engine = MagicMock()
		mock_conn = MagicMock()
		mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
		mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

		create_workflow_tables(mock_engine)
		mock_conn.execute.assert_called_once()
		ddl_text = str(mock_conn.execute.call_args[0][0])
		assert "pgaf_workflow_instance" in ddl_text
		assert "pgaf_workflow_task" in ddl_text

	def test_get_pending_tasks_empty_without_session(self):
		eng = PgAppForgeWorkflowEngine()
		eng.load_yaml_string(_SIMPLE_YAML)
		instance = eng.start("test_simple", {}, tenant_id="t42")
		tasks = eng.get_pending_tasks("t42")
		assert len(tasks) >= 1
		assert tasks[0]["workflow_name"] == "test_simple"
		assert tasks[0]["current_step_id"] == "manager_review"
