"""
pgappforge/workflow/yaml_dsl.py

YAML workflow definition language parser.

Parses YAML workflow definitions into dicts compatible with
PgAppForgeWorkflowEngine.load_dict().

Supported YAML format::

    name: sacco_loan_approval
    description: "SACCO loan application approval workflow"
    trigger:
      event: "sacco.loan.application.created"
      condition: "amount_cents > 0"

    steps:
      - id: loan_officer_review
        type: UserTask
        label: "Loan Officer Review"
        assignee_role: "Loan Officer"
        form_fields:
          - name: recommendation
            type: choice
            choices: [APPROVE, DECLINE, REQUEST_MORE_INFO]
          - name: notes
            type: text
        sla_hours: 48

      - id: credit_committee_vote
        type: UserTask
        label: "Credit Committee Vote"
        condition: "loan_officer_review.recommendation == 'APPROVE'"
        assignee_role: "Credit Committee"
        form_fields:
          - name: vote
            type: choice
            choices: [APPROVED, DECLINED]
        sla_hours: 72

      - id: disburse
        type: ServiceTask
        label: "Disburse via M-Pesa"
        service: "mpesa.disburse"
        input_map:
          msisdn: "application.phone_number"
          amount_cents: "application.amount_cents"
          reference: "workflow.instance_id"

    on_complete:
      emit_event: "sacco.loan.disbursed"

    on_decline:
      emit_event: "sacco.loan.declined"
      notify_applicant: true
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Required top-level keys
_REQUIRED_KEYS = {"name", "steps"}

# Valid step types
_VALID_STEP_TYPES = {"UserTask", "ServiceTask", "ScriptTask", "GatewayXOR", "GatewayAND"}


class WorkflowDSLError(ValueError):
	"""Raised when a YAML workflow definition is invalid."""


def parse_yaml_file(path: str | Path) -> dict[str, Any]:
	"""Parse a YAML workflow definition file into a validated dict.

	Args:
		path: Path to the .yaml file.

	Returns:
		Parsed and validated workflow dict, ready for WorkflowEngine.load_dict().

	Raises:
		WorkflowDSLError: If the definition is structurally invalid.
		FileNotFoundError: If the file does not exist.
	"""
	try:
		import yaml
	except ImportError:
		raise RuntimeError("PyYAML not installed. pip install pyyaml")

	path = Path(path)
	raw = yaml.safe_load(path.read_text(encoding="utf-8"))
	return validate_and_normalise(raw, source=str(path))


def parse_yaml_string(yaml_text: str, source: str = "<string>") -> dict[str, Any]:
	"""Parse a YAML workflow definition string.

	Args:
		yaml_text: Raw YAML text.
		source: Label for error messages.

	Returns:
		Parsed and validated workflow dict.
	"""
	try:
		import yaml
	except ImportError:
		raise RuntimeError("PyYAML not installed. pip install pyyaml")

	raw = yaml.safe_load(yaml_text)
	return validate_and_normalise(raw, source=source)


def validate_and_normalise(data: Any, source: str = "<unknown>") -> dict[str, Any]:
	"""Validate and normalise a raw parsed workflow dict.

	Normalisation:
	- Ensures all steps have a ``type`` (defaults to ``UserTask``).
	- Ensures all steps have an ``id`` and a ``label``.
	- Strips unknown top-level keys (forward-compatible).

	Raises:
		WorkflowDSLError: On structural violations.
	"""
	if not isinstance(data, dict):
		raise WorkflowDSLError(f"{source}: top-level must be a YAML mapping, got {type(data).__name__}")

	missing = _REQUIRED_KEYS - data.keys()
	if missing:
		raise WorkflowDSLError(f"{source}: missing required keys: {sorted(missing)}")

	name = data["name"]
	if not isinstance(name, str) or not name.strip():
		raise WorkflowDSLError(f"{source}: 'name' must be a non-empty string")

	steps_raw = data.get("steps", [])
	if not isinstance(steps_raw, list):
		raise WorkflowDSLError(f"{source}: 'steps' must be a YAML list")

	steps: list[dict[str, Any]] = []
	seen_ids: set[str] = set()
	for i, step in enumerate(steps_raw):
		if not isinstance(step, dict):
			raise WorkflowDSLError(f"{source}: step[{i}] must be a mapping")

		step_id = step.get("id")
		if not step_id:
			raise WorkflowDSLError(f"{source}: step[{i}] missing required 'id'")

		if step_id in seen_ids:
			raise WorkflowDSLError(f"{source}: duplicate step id {step_id!r}")
		seen_ids.add(step_id)

		step_type = step.get("type", "UserTask")
		if step_type not in _VALID_STEP_TYPES:
			log.warning("%s: step %r has unknown type %r — treating as UserTask", source, step_id, step_type)
			step_type = "UserTask"

		normalised: dict[str, Any] = {
			"id": step_id,
			"type": step_type,
			"label": step.get("label", step_id.replace("_", " ").title()),
		}
		# Copy all other keys through unchanged (condition, assignee_role, form_fields, etc.)
		for key, val in step.items():
			if key not in normalised:
				normalised[key] = val

		steps.append(normalised)

	return {
		"name": name.strip(),
		"description": str(data.get("description", "")),
		"trigger": data.get("trigger") or {},
		"steps": steps,
		"on_complete": data.get("on_complete") or {},
		"on_decline": data.get("on_decline") or {},
		"on_error": data.get("on_error") or {},
	}


def load_directory(directory: str | Path) -> list[dict[str, Any]]:
	"""Parse all *.yaml files in a directory (non-recursive).

	Returns list of validated workflow dicts. Files that fail parsing are
	logged at WARNING and skipped.
	"""
	directory = Path(directory)
	results: list[dict[str, Any]] = []
	for yaml_file in sorted(directory.glob("*.yaml")):
		try:
			results.append(parse_yaml_file(yaml_file))
		except Exception as exc:
			log.warning("Skipping workflow file %s: %s", yaml_file, exc)
	return results


__all__ = [
	"WorkflowDSLError",
	"parse_yaml_file",
	"parse_yaml_string",
	"validate_and_normalise",
	"load_directory",
]
