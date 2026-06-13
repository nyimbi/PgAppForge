"""
pgappforge/plugins/erp/platform/workflow_launcher/views.py

WorkflowLauncherView — unified UI for discovering and launching registered workflows.

Routes:
  GET  /platform/launch/
       Searchable grid of ALL registered workflows grouped by domain.

  GET  /platform/launch/wizard/<capability>/<workflow_id>
       Redirects to the first step of the wizard.

  GET  /platform/launch/wizard/<capability>/<workflow_id>/step/<step_id>
       Render a specific wizard step.

  POST /platform/launch/wizard/<capability>/<workflow_id>/step/<step_id>
       Validate submitted data, persist to session, advance or submit.

Session key: ``wizard_<capability>_<workflow_id>``
Value: dict mapping step_id → {field_name: value}
"""
from __future__ import annotations

import logging

from flask import jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup

from pgappforge.baseviews import BaseView
from pgappforge.security.decorators import has_access
from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain category metadata
# ---------------------------------------------------------------------------

_DOMAIN_META: dict[str, dict] = {
	"sacco.member":        {"label": "SACCO",      "icon": "fa-institution",  "color": "#1a56db"},
	"sacco.loan":          {"label": "SACCO",      "icon": "fa-institution",  "color": "#1a56db"},
	"finance.ap":          {"label": "Finance",    "icon": "fa-dollar",       "color": "#057a55"},
	"finance.ar":          {"label": "Finance",    "icon": "fa-dollar",       "color": "#057a55"},
	"hcm.recruiting":      {"label": "HCM",        "icon": "fa-users",        "color": "#7e3af2"},
	"crm.sales":           {"label": "CRM",        "icon": "fa-handshake-o",  "color": "#e3a008"},
	"operations.inventory":{"label": "Operations", "icon": "fa-cubes",        "color": "#ff5a1f"},
	"clubs.facility":      {"label": "Clubs",      "icon": "fa-flag-o",       "color": "#0694a2"},
}

_DEFAULT_META = {"label": "Other", "icon": "fa-cog", "color": "#6b7280"}


def _session_key(capability: str, wizard_id: str) -> str:
	return f"wizard_{capability}_{wizard_id}"


def _get_wizard_session(capability: str, wizard_id: str) -> dict:
	return session.get(_session_key(capability, wizard_id), {})


def _set_wizard_session(capability: str, wizard_id: str, data: dict) -> None:
	session[_session_key(capability, wizard_id)] = data
	session.modified = True


def _clear_wizard_session(capability: str, wizard_id: str) -> None:
	session.pop(_session_key(capability, wizard_id), None)
	session.modified = True


# ---------------------------------------------------------------------------
# WorkflowLauncherView
# ---------------------------------------------------------------------------

class WorkflowLauncherView(BaseERPView):
	"""Unified UI for discovering and launching all registered guided workflows."""

	route_base = "/platform/launch"
	default_view = "index"

	# ------------------------------------------------------------------
	# Launcher grid
	# ------------------------------------------------------------------

	@expose("/")
	@has_access
	def index(self):
		"""GET /platform/launch/ — searchable grid of all registered workflows."""
		from pgappforge.ui.wizard import get_all_workflows

		registry = get_all_workflows()

		# Build a flat list of card descriptors for the template
		cards: list[dict] = []
		domain_labels: set[str] = set()

		for capability, wizards in sorted(registry.items()):
			meta = _DOMAIN_META.get(capability, _DEFAULT_META)
			domain_labels.add(meta["label"])
			for wiz in wizards:
				total_mins = wiz.estimated_total_minutes
				time_label = (
					f"{total_mins} min" if total_mins else ""
				)
				step_count = len(wiz.steps)
				cards.append({
					"capability":  capability,
					"wizard_id":   wiz.id,
					"title":       wiz.title,
					"description": wiz.description,
					"icon":        wiz.icon,
					"domain":      meta["label"],
					"domain_icon": meta["icon"],
					"color":       meta["color"],
					"time_label":  time_label,
					"step_count":  step_count,
					"launch_url":  url_for(
						"WorkflowLauncherView.start_wizard",
						capability=capability,
						workflow_id=wiz.id,
					),
				})

		domains = sorted(domain_labels)

		return render_template(
			"appbuilder/workflow/launcher.html",
			cards=cards,
			domains=domains,
			page_title="Workflow Launcher",
		)

	# ------------------------------------------------------------------
	# Wizard entry point
	# ------------------------------------------------------------------

	@expose("/wizard/<string:capability>/<string:workflow_id>")
	@has_access
	def start_wizard(self, capability: str, workflow_id: str):
		"""GET — redirect to the wizard's first step."""
		from pgappforge.ui.wizard import get_wizard

		wiz = get_wizard(capability, workflow_id)
		if wiz is None or not wiz.steps:
			return self._not_found(f"Wizard {workflow_id!r} not found.")

		first_step_id = wiz.steps[0].id
		_clear_wizard_session(capability, workflow_id)  # fresh start

		return redirect(url_for(
			"WorkflowLauncherView.wizard_step",
			capability=capability,
			workflow_id=workflow_id,
			step_id=first_step_id,
		))

	# ------------------------------------------------------------------
	# Step: GET
	# ------------------------------------------------------------------

	@expose("/wizard/<string:capability>/<string:workflow_id>/step/<string:step_id>")
	@has_access
	def wizard_step(self, capability: str, workflow_id: str, step_id: str):
		"""GET — render a specific wizard step."""
		from pgappforge.ui.wizard import get_wizard

		wiz = get_wizard(capability, workflow_id)
		if wiz is None:
			return self._not_found(f"Wizard {workflow_id!r} not found.")

		step = wiz.get_step(step_id)
		if step is None:
			return self._not_found(f"Step {step_id!r} not found in wizard {workflow_id!r}.")

		wizard_data = _get_wizard_session(capability, workflow_id)
		step_data = wizard_data.get(step_id, {})

		progress_html: Markup = wiz.render_progress_bar(step_id)
		step_form_html: Markup | None = None

		if not step.template:
			step_form_html = wiz.render_step_form(step, form_data=step_data)

		# Navigation URLs
		prev_id = wiz.prev_step_id(step_id)
		next_id = wiz.next_step_id(step_id)
		is_last = wiz.is_last_step(step_id)

		prev_url = (
			url_for(
				"WorkflowLauncherView.wizard_step",
				capability=capability,
				workflow_id=workflow_id,
				step_id=prev_id,
			)
			if prev_id
			else None
		)

		post_url = url_for(
			"WorkflowLauncherView.wizard_step_post",
			capability=capability,
			workflow_id=workflow_id,
			step_id=step_id,
		)

		cancel_url = wiz.cancel_url or url_for("WorkflowLauncherView.index")

		step_index = wiz.step_index(step_id)

		return render_template(
			"appbuilder/workflow/wizard_base.html",
			wizard=wiz,
			step=step,
			step_index=step_index,
			total_steps=len(wiz.steps),
			progress_html=progress_html,
			step_form_html=step_form_html,
			post_url=post_url,
			prev_url=prev_url,
			cancel_url=cancel_url,
			is_last=is_last,
			submit_label=wiz.submit_label,
			errors=[],
			page_title=f"{wiz.title} — {step.title}",
		)

	# ------------------------------------------------------------------
	# Step: POST
	# ------------------------------------------------------------------

	@expose(
		"/wizard/<string:capability>/<string:workflow_id>/step/<string:step_id>",
		methods=["POST"],
	)
	@has_access
	def wizard_step_post(self, capability: str, workflow_id: str, step_id: str):
		"""POST — validate submitted step data, persist to session, advance."""
		from pgappforge.ui.wizard import get_wizard

		wiz = get_wizard(capability, workflow_id)
		if wiz is None:
			return self._not_found(f"Wizard {workflow_id!r} not found.")

		step = wiz.get_step(step_id)
		if step is None:
			return self._not_found(f"Step {step_id!r} not found.")

		form_data = dict(request.form)

		# Flatten single-value lists (ImmutableMultiDict → plain dict)
		flat_data: dict[str, str] = {
			k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
			for k, v in form_data.items()
		}

		errors = wiz.validate_step(step_id, flat_data)

		if errors:
			# Re-render the step with validation errors
			wizard_data = _get_wizard_session(capability, workflow_id)
			progress_html = wiz.render_progress_bar(step_id)
			step_form_html = wiz.render_step_form(step, form_data=flat_data)

			prev_id = wiz.prev_step_id(step_id)
			prev_url = (
				url_for(
					"WorkflowLauncherView.wizard_step",
					capability=capability,
					workflow_id=workflow_id,
					step_id=prev_id,
				)
				if prev_id
				else None
			)
			post_url = url_for(
				"WorkflowLauncherView.wizard_step_post",
				capability=capability,
				workflow_id=workflow_id,
				step_id=step_id,
			)
			cancel_url = wiz.cancel_url or url_for("WorkflowLauncherView.index")
			is_last = wiz.is_last_step(step_id)

			return render_template(
				"appbuilder/workflow/wizard_base.html",
				wizard=wiz,
				step=step,
				step_index=wiz.step_index(step_id),
				total_steps=len(wiz.steps),
				progress_html=progress_html,
				step_form_html=step_form_html,
				post_url=post_url,
				prev_url=prev_url,
				cancel_url=cancel_url,
				is_last=is_last,
				submit_label=wiz.submit_label,
				errors=errors,
				page_title=f"{wiz.title} — {step.title}",
			), 422

		# Persist step data to session
		wizard_data = _get_wizard_session(capability, workflow_id)
		wizard_data[step_id] = flat_data
		_set_wizard_session(capability, workflow_id, wizard_data)

		# Advance or complete
		if wiz.is_last_step(step_id):
			return self._complete_wizard(wiz, capability, wizard_id=workflow_id)

		next_id = wiz.next_step_id(step_id)
		return redirect(url_for(
			"WorkflowLauncherView.wizard_step",
			capability=capability,
			workflow_id=workflow_id,
			step_id=next_id,
		))

	# ------------------------------------------------------------------
	# Wizard completion
	# ------------------------------------------------------------------

	def _complete_wizard(
		self,
		wiz,
		capability: str,
		wizard_id: str,
	):
		"""Handle final step submission.

		Current behaviour: flash success, clear session, redirect to launcher.
		Override this method in a subclass to add persistence logic.
		"""
		from flask import flash
		collected = _get_wizard_session(capability, wizard_id)
		_clear_wizard_session(capability, wizard_id)

		log.info(
			"Wizard completed: capability=%s wizard=%s steps=%d",
			capability,
			wizard_id,
			len(collected),
		)

		flash(wiz.success_message or "Workflow completed.", "success")
		return redirect(url_for("WorkflowLauncherView.index"))

	# ------------------------------------------------------------------
	# AJAX: search cards
	# ------------------------------------------------------------------

	@expose("/search")
	@has_access
	def search(self):
		"""GET /platform/launch/search?q=... — returns filtered card JSON."""
		from pgappforge.ui.wizard import get_all_workflows

		q = (request.args.get("q") or "").lower().strip()
		registry = get_all_workflows()
		results: list[dict] = []

		for capability, wizards in registry.items():
			meta = _DOMAIN_META.get(capability, _DEFAULT_META)
			for wiz in wizards:
				if q and q not in wiz.title.lower() and q not in wiz.description.lower():
					continue
				results.append({
					"capability":  capability,
					"wizard_id":   wiz.id,
					"title":       wiz.title,
					"description": wiz.description,
					"domain":      meta["label"],
					"icon":        wiz.icon,
					"color":       meta["color"],
				})

		return jsonify({"results": results})

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _not_found(msg: str):
		from flask import abort
		log.warning("WorkflowLauncherView: %s", msg)
		abort(404)


__all__ = ["WorkflowLauncherView"]
