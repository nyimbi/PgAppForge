"""
tests/ci/test_ui_wizard_fk.py

CI tests for:
  - pgappforge.ui.fk_widgets   (FKSelectWidget, auto_fk_widget)
  - pgappforge.ui.wizard       (WizardStep, WorkflowWizard, registry)
  - pgappforge.ui.capability_workflows (register_all_capability_workflows)
  - pgappforge.plugins.erp.platform.workflow_launcher.views (WorkflowLauncherView)
"""
from __future__ import annotations

import pytest
from markupsafe import Markup

from pgappforge.ui.fk_widgets import FKSelectWidget, auto_fk_widget
from pgappforge.ui.wizard import (
	WizardStep,
	WorkflowWizard,
	get_all_workflows,
	get_wizard,
	get_workflows,
	register_workflow,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
	"""Isolate registry mutations between tests."""
	import pgappforge.ui.wizard as wiz_mod
	original = dict(wiz_mod._WORKFLOW_REGISTRY)
	yield
	wiz_mod._WORKFLOW_REGISTRY.clear()
	wiz_mod._WORKFLOW_REGISTRY.update(original)


@pytest.fixture
def sacco_member_wiz():
	from pgappforge.ui.capability_workflows import register_all_capability_workflows
	register_all_capability_workflows()
	return get_wizard("sacco.member", "new_member_registration")


@pytest.fixture
def loan_wiz():
	from pgappforge.ui.capability_workflows import register_all_capability_workflows
	register_all_capability_workflows()
	return get_wizard("sacco.loan", "loan_application")


# ---------------------------------------------------------------------------
# capability_workflows
# ---------------------------------------------------------------------------

class TestCapabilityWorkflows:
	def test_registration_count(self):
		from pgappforge.ui.capability_workflows import register_all_capability_workflows
		n = register_all_capability_workflows()
		# 1 sacco.member + 1 sacco.loan + 2 finance + 1 hcm + 1 crm + 1 inventory + 1 clubs = 8
		assert n == 8

	def test_all_capability_keys_present(self):
		from pgappforge.ui.capability_workflows import register_all_capability_workflows
		register_all_capability_workflows()
		registry = get_all_workflows()
		expected = {
			"sacco.member", "sacco.loan", "finance.ap", "finance.ar",
			"hcm.recruiting", "crm.sales", "operations.inventory", "clubs.facility",
		}
		assert expected.issubset(registry.keys())

	def test_idempotent_re_registration(self):
		from pgappforge.ui.capability_workflows import register_all_capability_workflows
		register_all_capability_workflows()
		register_all_capability_workflows()
		registry = get_all_workflows()
		# No duplicates
		for key, wizards in registry.items():
			ids = [w.id for w in wizards]
			assert len(ids) == len(set(ids)), f"Duplicates in {key}: {ids}"


# ---------------------------------------------------------------------------
# WorkflowWizard — navigation
# ---------------------------------------------------------------------------

class TestWizardNavigation:
	def test_step_count(self, sacco_member_wiz):
		assert len(sacco_member_wiz.steps) == 5

	def test_first_and_last_ids(self, sacco_member_wiz):
		assert sacco_member_wiz.steps[0].id == "personal_info"
		assert sacco_member_wiz.steps[-1].id == "review"

	def test_next_step(self, sacco_member_wiz):
		assert sacco_member_wiz.next_step_id("personal_info") == "employment"
		assert sacco_member_wiz.next_step_id("employment") == "membership_type"

	def test_next_step_at_end_returns_none(self, sacco_member_wiz):
		assert sacco_member_wiz.next_step_id("review") is None

	def test_prev_step(self, sacco_member_wiz):
		assert sacco_member_wiz.prev_step_id("employment") == "personal_info"

	def test_prev_step_at_start_returns_none(self, sacco_member_wiz):
		assert sacco_member_wiz.prev_step_id("personal_info") is None

	def test_is_last_step(self, sacco_member_wiz):
		assert sacco_member_wiz.is_last_step("review")
		assert not sacco_member_wiz.is_last_step("personal_info")

	def test_step_index(self, sacco_member_wiz):
		assert sacco_member_wiz.step_index("personal_info") == 0
		assert sacco_member_wiz.step_index("employment") == 1
		assert sacco_member_wiz.step_index("nonexistent") == -1

	def test_get_step_returns_correct_object(self, sacco_member_wiz):
		step = sacco_member_wiz.get_step("employment")
		assert step is not None
		assert step.title == "Employment Details"

	def test_get_step_unknown_returns_none(self, sacco_member_wiz):
		assert sacco_member_wiz.get_step("does_not_exist") is None

	def test_estimated_total_minutes(self, sacco_member_wiz):
		assert sacco_member_wiz.estimated_total_minutes == 5 + 3 + 2 + 5 + 2


# ---------------------------------------------------------------------------
# WorkflowWizard — validation
# ---------------------------------------------------------------------------

class TestWizardValidation:
	def test_missing_required_fields_returns_errors(self, sacco_member_wiz):
		errors = sacco_member_wiz.validate_step("personal_info", {})
		required = {f["name"] for f in sacco_member_wiz.steps[0].fields if f.get("required")}
		assert len(errors) == len(required)

	def test_all_required_present_returns_empty(self, sacco_member_wiz):
		errors = sacco_member_wiz.validate_step("personal_info", {
			"full_name": "Alice Wanjiku",
			"national_id": "12345678",
			"date_of_birth": "1990-01-01",
			"gender": "F",
			"phone": "+254700000000",
		})
		assert errors == []

	def test_unknown_step_returns_empty(self, sacco_member_wiz):
		assert sacco_member_wiz.validate_step("nonexistent", {"x": "y"}) == []

	def test_custom_validation_fn_errors_appended(self):
		def fail_always(data):
			return ["Always fails."]

		wiz = WorkflowWizard(
			id="test_custom_val",
			title="Test",
			steps=[
				WizardStep(
					id="s1", title="Step 1",
					fields=[{"name": "x", "type": "text", "required": True}],
					validation_fn=fail_always,
				)
			],
		)
		errors = wiz.validate_step("s1", {"x": "provided"})
		assert "Always fails." in errors

	def test_optional_step_flag(self, loan_wiz):
		collateral = loan_wiz.get_step("collateral")
		assert collateral is not None
		assert collateral.is_optional


# ---------------------------------------------------------------------------
# WorkflowWizard — rendering
# ---------------------------------------------------------------------------

class TestWizardRendering:
	def test_progress_bar_returns_markup(self, sacco_member_wiz):
		html = sacco_member_wiz.render_progress_bar("personal_info")
		assert isinstance(html, Markup)

	def test_progress_bar_contains_expected_classes(self, sacco_member_wiz):
		html = str(sacco_member_wiz.render_progress_bar("personal_info"))
		assert "pgaf-wizard-progress" in html
		assert "wizard-step-active" in html
		assert "wizard-step-pending" in html

	def test_progress_bar_completed_class_on_prior_steps(self, sacco_member_wiz):
		html = str(sacco_member_wiz.render_progress_bar("employment"))
		assert "wizard-step-completed" in html

	def test_step_form_returns_markup(self, sacco_member_wiz):
		step = sacco_member_wiz.get_step("personal_info")
		html = sacco_member_wiz.render_step_form(step)
		assert isinstance(html, Markup)

	def test_step_form_xss_escaping(self, sacco_member_wiz):
		step = sacco_member_wiz.get_step("personal_info")
		payload = '<script>alert(1)</script>'
		html = str(sacco_member_wiz.render_step_form(step, form_data={"full_name": payload}))
		assert "<script>" not in html
		assert "alert" in html  # text content present but tags escaped

	def test_step_form_repopulates_value(self, sacco_member_wiz):
		step = sacco_member_wiz.get_step("personal_info")
		html = str(sacco_member_wiz.render_step_form(step, form_data={"full_name": "Alice"}))
		assert "Alice" in html

	def test_step_form_required_attr(self, sacco_member_wiz):
		step = sacco_member_wiz.get_step("personal_info")
		html = str(sacco_member_wiz.render_step_form(step))
		assert "required" in html

	def test_step_form_select_field(self, sacco_member_wiz):
		step = sacco_member_wiz.get_step("personal_info")
		html = str(sacco_member_wiz.render_step_form(step))
		assert "<select" in html  # gender is a select

	def test_step_form_file_field(self, sacco_member_wiz):
		step = sacco_member_wiz.get_step("documents")
		html = str(sacco_member_wiz.render_step_form(step))
		assert 'type="file"' in html
		assert "accept=" in html

	def test_step_form_checkbox_field(self, loan_wiz):
		step = loan_wiz.get_step("declaration")
		html = str(loan_wiz.render_step_form(step))
		assert 'type="checkbox"' in html

	def test_step_form_phone_field_type(self, sacco_member_wiz):
		step = sacco_member_wiz.get_step("personal_info")
		html = str(sacco_member_wiz.render_step_form(step))
		assert 'type="tel"' in html

	def test_option_helper_selected(self):
		opt = WorkflowWizard._option(("v", "Label"), "v")
		assert "selected" in opt
		assert "Label" in opt

	def test_option_helper_not_selected(self):
		opt = WorkflowWizard._option(("v", "Label"), "other")
		assert "selected" not in opt

	def test_option_helper_xss(self):
		opt = WorkflowWizard._option(("<xss>", "<bad>"), "other")
		assert "<xss>" not in opt
		assert "<bad>" not in opt


# ---------------------------------------------------------------------------
# FKSelectWidget — rendering
# ---------------------------------------------------------------------------

class TestFKSelectWidget:
	@pytest.fixture
	def widget(self):
		return FKSelectWidget(related_model=None, use_select2=False)

	def test_render_html_returns_markup(self, widget):
		html = widget.render_html("field", None, [("1", "One"), ("2", "Two")])
		assert isinstance(html, Markup)

	def test_render_html_contains_options(self, widget):
		html = str(widget.render_html("field", None, [("1", "One"), ("2", "Two")]))
		assert "One" in html
		assert "Two" in html

	def test_render_html_selected_option(self, widget):
		html = str(widget.render_html("field", "2", [("1", "One"), ("2", "Two")]))
		assert "selected" in html

	def test_render_html_xss_in_choices(self, widget):
		html = str(widget.render_html("f", None, [("<xss>", "<script>evil()</script>")]))
		assert "<script>" not in html
		assert "<xss>" not in html

	def test_render_html_required_attr(self, widget):
		html = str(widget.render_html("f", None, [], required=True))
		assert "required" in html

	def test_render_html_empty_option_when_allow_empty(self):
		w = FKSelectWidget(related_model=None, use_select2=False, allow_empty=True)
		html = str(w.render_html("f", None, [("1", "One")]))
		# empty value option is present
		assert 'value=""' in html

	def test_render_html_no_empty_option_when_not_allowed(self):
		w = FKSelectWidget(related_model=None, use_select2=False, allow_empty=False)
		html = str(w.render_html("f", None, [("1", "One")]))
		assert 'value=""' not in html

	def test_render_html_grouped_optgroup(self, widget):
		html = str(widget.render_html("f", None, choices=[],
			grouped={"Grp A": [("1", "X")], "Grp B": [("2", "Y")]}))
		assert "<optgroup" in html
		assert "Grp A" in html
		assert "Grp B" in html

	def test_render_html_select2_js_emitted(self):
		w = FKSelectWidget(related_model=None, use_select2=True)
		html = str(w.render_html("f", None, []))
		assert "select2" in html.lower()

	def test_get_choices_empty_on_no_session(self, widget):
		"""get_choices with a bad session should return graceful fallback."""
		choices = widget.get_choices(session=None)
		# Should return the placeholder-only list, not raise
		assert isinstance(choices, list)
		assert choices[0] == ("", widget.placeholder)

	def test_display_label_str_fallback(self):
		class FakeRow:
			id = "abc"
			def __str__(self): return "Fake Row"

		w = FKSelectWidget(
			related_model=None,
			display_fields=["nonexistent", "__str__"],
		)
		label = w._get_display_label(FakeRow())
		assert label == "Fake Row"

	def test_display_label_first_match_wins(self):
		class FakeRow:
			name = "Alice"
			code = "A001"
			id = "x"

		w = FKSelectWidget(related_model=None, display_fields=["name", "code", "__str__"])
		assert w._get_display_label(FakeRow()) == "Alice"


# ---------------------------------------------------------------------------
# WorkflowLauncherView
# ---------------------------------------------------------------------------

class TestWorkflowLauncherView:
	def test_route_base(self):
		from pgappforge.plugins.erp.platform.workflow_launcher.views import WorkflowLauncherView
		assert WorkflowLauncherView.route_base == "/platform/launch"

	def test_default_view(self):
		from pgappforge.plugins.erp.platform.workflow_launcher.views import WorkflowLauncherView
		assert WorkflowLauncherView.default_view == "index"

	def test_domain_meta_covers_all_capabilities(self):
		from pgappforge.plugins.erp.platform.workflow_launcher.views import _DOMAIN_META
		expected = {
			"sacco.member", "sacco.loan", "finance.ap", "finance.ar",
			"hcm.recruiting", "crm.sales", "operations.inventory", "clubs.facility",
		}
		assert expected.issubset(_DOMAIN_META.keys())
