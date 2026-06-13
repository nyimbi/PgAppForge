"""
pgappforge/ui/wizard.py

Multi-step wizard component for guided workflows.

Classes:
  WizardStep       — Configuration for a single wizard step.
  WorkflowWizard   — Complete wizard definition with rendering helpers.

Registry helpers:
  register_workflow  — Register a WorkflowWizard under a capability key.
  get_workflows      — Retrieve all wizards for a capability.
  get_all_workflows  — Retrieve the full registry dict.

Typical usage::

	from pgappforge.ui.wizard import WizardStep, WorkflowWizard, register_workflow

	wizard = WorkflowWizard(
		id="sacco_loan_application",
		title="Apply for a SACCO Loan",
		steps=[
			WizardStep("loan_details", "Loan Details", fields=[...]),
			WizardStep("guarantors",   "Guarantors",   fields=[...]),
		],
	)
	register_workflow("sacco.loan", wizard)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from markupsafe import Markup, escape

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WizardStep
# ---------------------------------------------------------------------------

@dataclass
class WizardStep:
	"""A single step in a guided workflow wizard.

	Attributes:
		id:               Unique slug used in URLs and session keys.
		title:            Short human title shown in the progress bar.
		description:      Longer description shown in the step header.
		icon:             Font Awesome icon class, e.g. ``"fa-user"``.
		template:         Optional Jinja2 template path for custom step content.
		                  When set, the template is rendered instead of the
		                  auto-generated field form.
		fields:           Ordered list of field descriptor dicts.  Each dict
		                  accepts keys: name, type, label, required, help,
		                  placeholder, choices, rows, accept, step.
		validation_fn:    Optional callable ``fn(data: dict) -> list[str]``
		                  returning extra validation error messages.
		is_optional:      If True, the step may be skipped.
		help_text:        Longer contextual help shown below the step title.
		estimated_minutes: Rough time estimate shown on the launcher card.
	"""

	id: str
	title: str
	description: str = ""
	icon: str = "fa-chevron-right"
	template: str | None = None
	fields: list[dict] = field(default_factory=list)
	validation_fn: Callable | None = None
	is_optional: bool = False
	help_text: str = ""
	estimated_minutes: int = 0


# ---------------------------------------------------------------------------
# WorkflowWizard
# ---------------------------------------------------------------------------

@dataclass
class WorkflowWizard:
	"""A complete guided workflow wizard with multiple steps.

	Example::

		wizard = WorkflowWizard(
			id="sacco_loan_application",
			title="Apply for a SACCO Loan",
			description="Complete the following steps to submit your loan application",
			steps=[
				WizardStep("loan_details",  "Loan Details",  fields=[...]),
				WizardStep("guarantors",    "Guarantors",    fields=[...]),
				WizardStep("declaration",   "Declaration",   fields=[...]),
			],
		)

		# In a Jinja2 template:
		#   {{ wizard.render_progress_bar(current_step_id) | safe }}
	"""

	id: str
	title: str
	description: str = ""
	icon: str = "fa-magic"
	steps: list[WizardStep] = field(default_factory=list)
	submit_label: str = "Submit"
	cancel_url: str = "/"
	success_url: str = "/"
	success_message: str = "Completed successfully"

	# ------------------------------------------------------------------
	# Navigation helpers
	# ------------------------------------------------------------------

	def get_step(self, step_id: str) -> WizardStep | None:
		"""Return the WizardStep with the given id, or None."""
		return next((s for s in self.steps if s.id == step_id), None)

	def next_step_id(self, current_step_id: str) -> str | None:
		"""Return the id of the step after *current_step_id*, or None."""
		ids = [s.id for s in self.steps]
		try:
			idx = ids.index(current_step_id)
			return ids[idx + 1] if idx + 1 < len(ids) else None
		except ValueError:
			return None

	def prev_step_id(self, current_step_id: str) -> str | None:
		"""Return the id of the step before *current_step_id*, or None."""
		ids = [s.id for s in self.steps]
		try:
			idx = ids.index(current_step_id)
			return ids[idx - 1] if idx > 0 else None
		except ValueError:
			return None

	def is_last_step(self, step_id: str) -> bool:
		"""Return True when *step_id* is the final step."""
		return bool(self.steps) and self.steps[-1].id == step_id

	def step_index(self, step_id: str) -> int:
		"""Return 0-based index of *step_id*, or -1 if not found."""
		ids = [s.id for s in self.steps]
		try:
			return ids.index(step_id)
		except ValueError:
			return -1

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def validate_step(self, step_id: str, data: dict) -> list[str]:
		"""Validate a step's submitted data.

		Runs required-field checks first, then calls the step's
		``validation_fn`` if provided.

		Returns:
			List of human-readable error messages.  Empty list means valid.
		"""
		step = self.get_step(step_id)
		if not step:
			return []

		errors: list[str] = []

		for f in step.fields:
			if f.get("required") and not data.get(f["name"]):
				label = f.get("label") or f["name"]
				errors.append(f"{label} is required.")

		if step.validation_fn:
			try:
				extra = step.validation_fn(data)
				errors.extend(extra or [])
			except Exception as exc:
				log.debug("Step validation_fn failed (%s): %s", step_id, exc)

		return errors

	# ------------------------------------------------------------------
	# HTML: Progress bar
	# ------------------------------------------------------------------

	def render_progress_bar(self, current_step_id: str) -> Markup:
		"""Render the horizontal step progress indicator.

		Args:
			current_step_id: The id of the currently active step.

		Returns:
			Markup with the ``pgaf-wizard-progress`` container.
			Emit as ``{{ wizard.render_progress_bar(step_id) | safe }}``.
		"""
		current_idx = next(
			(i for i, s in enumerate(self.steps) if s.id == current_step_id), 0
		)
		total = len(self.steps)

		items: list[str] = []
		for i, step in enumerate(self.steps):
			if i < current_idx:
				state_class = "wizard-step-completed"
				state_icon = "fa-check"
			elif i == current_idx:
				state_class = "wizard-step-active"
				state_icon = step.icon
			else:
				state_class = "wizard-step-pending"
				state_icon = step.icon

			opt_badge = (
				'<span class="wizard-optional-badge">optional</span>'
				if step.is_optional
				else ""
			)
			connector = (
				'<div class="wizard-connector" aria-hidden="true"></div>'
				if i < total - 1
				else ""
			)

			items.append(
				f'<div class="wizard-step-item {state_class}"'
				f' title="{escape(step.title)}">'
				f'  <div class="wizard-step-circle">'
				f'    <i class="fa {escape(state_icon)}" aria-hidden="true"></i>'
				f'    <span class="wizard-step-number sr-only">{i + 1}</span>'
				f"  </div>"
				f'  <div class="wizard-step-label">'
				f"    {escape(step.title)}{opt_badge}"
				f"  </div>"
				f"</div>{connector}"
			)

		pct = int((current_idx / max(total - 1, 1)) * 100) if total > 1 else 0

		return Markup(
			f'<div class="pgaf-wizard-progress"'
			f' role="progressbar"'
			f' aria-valuenow="{pct}"'
			f' aria-valuemin="0"'
			f' aria-valuemax="100"'
			f' aria-label="Step {current_idx + 1} of {total}">'
			f'  <div class="wizard-steps-track">{"".join(items)}</div>'
			f'  <div class="wizard-progress-fill" style="width:{pct}%"></div>'
			f"</div>"
		)

	# ------------------------------------------------------------------
	# HTML: Step form
	# ------------------------------------------------------------------

	def render_step_form(
		self,
		step: WizardStep,
		form_data: dict | None = None,
	) -> Markup:
		"""Render the auto-generated form for *step*.

		Supports field types: text, email, tel/phone, number, money, date,
		datetime-local, textarea, select, file, checkbox.

		Args:
			step:       The WizardStep to render.
			form_data:  Dict of previously submitted values (for re-population).

		Returns:
			Markup with the ``pgaf-wizard-step-form`` container.
		"""
		form_data = form_data or {}
		fields_html: list[str] = []

		for f in step.fields:
			fname = f.get("name", "")
			if not fname:
				continue
			ftype = f.get("type", "text")
			label = f.get("label") or fname.replace("_", " ").title()
			required = f.get("required", False)
			help_text = f.get("help", "")
			current_val = str(form_data.get(fname) or "")

			req_mark = '<span class="text-danger" aria-hidden="true">*</span>' if required else ""
			req_attr = " required" if required else ""

			input_html = self._render_input(f, fname, ftype, current_val, req_attr, form_data)

			help_html = (
				f'<small class="form-text text-muted">{escape(help_text)}</small>'
				if help_text
				else ""
			)

			fields_html.append(
				f'<div class="form-group pgaf-wizard-field" data-field="{fname}">'
				f'  <label for="wiz_{escape(fname)}">{escape(label)} {req_mark}</label>'
				f"  {input_html}"
				f"  {help_html}"
				f"</div>"
			)

		return Markup(
			f'<div class="pgaf-wizard-step-form" data-step="{escape(step.id)}">'
			f'{"".join(fields_html)}'
			f"</div>"
		)

	# ------------------------------------------------------------------
	# Internal: input renderer
	# ------------------------------------------------------------------

	def _render_input(
		self,
		f: dict,
		fname: str,
		ftype: str,
		current_val: str,
		req_attr: str,
		form_data: dict,
	) -> str:
		"""Return the HTML input element string for a single field descriptor."""

		if ftype == "select":
			choices: list = f.get("choices", [])
			opts = "".join(
				self._option(c, current_val) for c in choices
			)
			return (
				f'<select id="wiz_{escape(fname)}" name="{escape(fname)}"'
				f' class="form-control pgaf-select2"{req_attr}>'
				f'<option value="">Select...</option>'
				f"{opts}"
				f"</select>"
			)

		if ftype == "textarea":
			rows = f.get("rows", 3)
			return (
				f'<textarea id="wiz_{escape(fname)}" name="{escape(fname)}"'
				f' class="form-control" rows="{rows}"{req_attr}>'
				f"{escape(current_val)}</textarea>"
			)

		if ftype in ("date", "datetime-local"):
			return (
				f'<input type="{ftype}" id="wiz_{escape(fname)}"'
				f' name="{escape(fname)}" class="form-control"'
				f' value="{escape(current_val)}"{req_attr}>'
			)

		if ftype in ("number", "money"):
			step_attr = ' step="0.01"' if ftype == "money" else ""
			min_attr = f' min="{escape(str(f["min"]))}"' if "min" in f else ""
			max_attr = f' max="{escape(str(f["max"]))}"' if "max" in f else ""
			return (
				f'<input type="number" id="wiz_{escape(fname)}"'
				f' name="{escape(fname)}" class="form-control"'
				f' value="{escape(current_val)}"{req_attr}{step_attr}{min_attr}{max_attr}>'
			)

		if ftype in ("phone", "tel"):
			placeholder = f.get("placeholder", "+254700000000")
			return (
				f'<input type="tel" id="wiz_{escape(fname)}"'
				f' name="{escape(fname)}" class="form-control"'
				f' value="{escape(current_val)}"'
				f' placeholder="{escape(placeholder)}"{req_attr}>'
			)

		if ftype == "email":
			placeholder = f.get("placeholder", "")
			ph = f' placeholder="{escape(placeholder)}"' if placeholder else ""
			return (
				f'<input type="email" id="wiz_{escape(fname)}"'
				f' name="{escape(fname)}" class="form-control"'
				f' value="{escape(current_val)}"{ph}{req_attr}>'
			)

		if ftype == "file":
			accept = f.get("accept", "")
			accept_attr = f' accept="{escape(accept)}"' if accept else ""
			return (
				f'<input type="file" id="wiz_{escape(fname)}"'
				f' name="{escape(fname)}" class="form-control-file"{accept_attr}{req_attr}>'
			)

		if ftype == "checkbox":
			checked = " checked" if form_data.get(fname) else ""
			# Checkbox uses a label-wrapping pattern for easier click targets
			return (
				f'<div class="checkbox pgaf-checkbox">'
				f'  <label>'
				f'    <input type="checkbox" id="wiz_{escape(fname)}"'
				f'     name="{escape(fname)}" value="1"{checked}{req_attr}>'
				f'    <span class="pgaf-checkbox-label">'
				f'      {escape(f.get("label", fname))}'
				f"    </span>"
				f"  </label>"
				f"</div>"
			)

		# Default: text / password / url / etc.
		placeholder = f.get("placeholder", "")
		ph_attr = f' placeholder="{escape(placeholder)}"' if placeholder else ""
		return (
			f'<input type="{escape(ftype)}" id="wiz_{escape(fname)}"'
			f' name="{escape(fname)}" class="form-control"'
			f' value="{escape(current_val)}"{ph_attr}{req_attr}>'
		)

	@staticmethod
	def _option(choice: Any, current_val: str) -> str:
		"""Render a single <option> element."""
		if isinstance(choice, (list, tuple)):
			val = str(choice[0])
			lbl = str(choice[1]) if len(choice) > 1 else val
		else:
			val = lbl = str(choice)
		selected = " selected" if val == current_val else ""
		return f'<option value="{escape(val)}"{selected}>{escape(lbl)}</option>'

	# ------------------------------------------------------------------
	# Estimated total time
	# ------------------------------------------------------------------

	@property
	def estimated_total_minutes(self) -> int:
		"""Sum of all step estimated_minutes values."""
		return sum(s.estimated_minutes for s in self.steps)


# ---------------------------------------------------------------------------
# Workflow registry
# ---------------------------------------------------------------------------

_WORKFLOW_REGISTRY: dict[str, list[WorkflowWizard]] = {}


def register_workflow(capability: str, wizard: WorkflowWizard) -> None:
	"""Register *wizard* under *capability*.

	Capability keys use dot-notation, e.g. ``"sacco.loan"``,
	``"finance.ap"``, ``"hcm.recruiting"``.

	Idempotent: registering the same wizard id twice under the same
	capability replaces the earlier entry.
	"""
	bucket = _WORKFLOW_REGISTRY.setdefault(capability, [])
	# Replace if same id already registered
	for i, existing in enumerate(bucket):
		if existing.id == wizard.id:
			bucket[i] = wizard
			log.debug("Workflow replaced: %s / %s", capability, wizard.id)
			return
	bucket.append(wizard)
	log.debug("Workflow registered: %s / %s", capability, wizard.id)


def get_workflows(capability: str) -> list[WorkflowWizard]:
	"""Return all registered WorkflowWizards for *capability*."""
	return list(_WORKFLOW_REGISTRY.get(capability, []))


def get_all_workflows() -> dict[str, list[WorkflowWizard]]:
	"""Return a shallow copy of the full registry.

	Keys are capability strings; values are lists of WorkflowWizard.
	"""
	return {k: list(v) for k, v in _WORKFLOW_REGISTRY.items()}


def get_wizard(capability: str, wizard_id: str) -> WorkflowWizard | None:
	"""Look up a specific wizard by capability + id."""
	for w in _WORKFLOW_REGISTRY.get(capability, []):
		if w.id == wizard_id:
			return w
	return None


__all__ = [
	"WizardStep",
	"WorkflowWizard",
	"register_workflow",
	"get_workflows",
	"get_all_workflows",
	"get_wizard",
]
