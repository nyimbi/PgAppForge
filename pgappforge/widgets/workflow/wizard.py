"""StepWizardWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms import Field
from wtforms.fields import (
    BooleanField, DateField, DateTimeField, DecimalField, FileField,
    FloatField, IntegerField, PasswordField, SelectField,
    SelectMultipleField, StringField, TextAreaField,
)
from wtforms.validators import ValidationError
from wtforms.widgets import TextInput, html_params

class StepWizardWidget(BS3TextFieldWidget):
    """
    Multi-step wizard widget for guiding users through complex processes.
    Stores wizard state and data as JSONB in PostgreSQL.

    Features:
    - Linear/non-linear navigation with validation
    - Progress tracking and persistence
    - Conditional branching and dependencies
    - Save/resume functionality
    - Mobile-responsive design
    - Full accessibility support
    - Custom transitions and animations
    - Analytics tracking
    - Error handling and recovery
    - Form autosave
    - Input validation
    - File upload support
    - Payment integration
    - Custom layouts and theming

    Step Types:
    - Form: Input collection
    - Confirmation: Review/approve
    - Upload: File handling
    - Payment: Transaction processing
    - Summary: Results display
    - Custom: User-defined steps

    Database Type:
        PostgreSQL: JSONB for storing wizard state and data
        SQLAlchemy: JSON type with schema validation

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47
    - Mobile browsers

    Required Permissions:
    - LocalStorage access
    - File system for uploads
    - Payment API access
    - Analytics endpoints

    Performance Considerations:
    - Lazy loading of steps
    - Debounced validation
    - Optimized file uploads
    - Cached templates
    - Memory management

    Security:
    - CSRF protection
    - Input validation
    - File upload scanning
    - Payment data handling
    - Session management

    Best Practices:
    - Define clear step flow
    - Validate all inputs
    - Handle errors gracefully
    - Save progress frequently
    - Test edge cases
    - Monitor analytics

    Required Dependencies:
    - jQuery Steps
    - FormValidation
    - DropzoneJS
    - Stripe/Payment APIs
    - Analytics libraries
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jquery-steps/1.1.0/jquery.steps.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/formvalidation/0.6.2-dev/js/formValidation.min.js",
        "https://unpkg.com/dropzone@5/dist/min/dropzone.min.js",
        "https://js.stripe.com/v3/",
        "/static/js/wizard-widget.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jquery-steps/1.1.0/jquery.steps.min.css",
        "https://cdnjs.cloudflare.com/ajax/libs/formvalidation/0.6.2-dev/css/formValidation.min.css",
        "https://unpkg.com/dropzone@5/dist/min/dropzone.min.css",
        "/static/css/wizard-widget.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize StepWizardWidget with custom settings.

        Args:
            steps (list): Step definitions and config
            validation (bool): Enable input validation
            save_state (bool): Enable progress saving
            linear (bool): Enforce linear progression
            transitions (dict): Custom transition effects
            templates (dict): Step templates
            dependencies (dict): Step dependencies
            branching (dict): Conditional branching rules
            analytics (bool): Enable usage tracking
            custom_layouts (dict): Custom step layouts
            persistence (str): State storage method
            autosave (bool): Enable auto-saving
            payment_config (dict): Payment processing settings
            upload_config (dict): File upload settings
        """
        super().__init__(**kwargs)

        # Core Settings
        self.steps = kwargs.get("steps", [])
        self.validation = kwargs.get("validation", True)
        self.save_state = kwargs.get("save_state", True)
        self.linear = kwargs.get("linear", True)

        # Advanced Settings
        self.transitions = kwargs.get("transitions", {})
        self.templates = kwargs.get("templates", {})
        self.dependencies = kwargs.get("dependencies", {})
        self.branching = kwargs.get("branching", {})
        self.analytics = kwargs.get("analytics", False)
        self.custom_layouts = kwargs.get("custom_layouts", {})
        self.persistence = kwargs.get("persistence", "local")

        # Additional Features
        self.autosave = kwargs.get("autosave", True)
        self.payment_config = kwargs.get("payment_config", {})
        self.upload_config = kwargs.get("upload_config", {})

        # Internal State
        self._current_step = 0
        self._data = {}
        self._errors = []
        self._autosave_timer = None

        # Validation
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the wizard widget with all steps and controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="wizard-widget" id="{field.id}-wizard">
                <!-- Steps Container -->
                <div class="wizard-steps">
                    {self._render_steps(field.id)}
                </div>

                <!-- Progress Bar -->
                <div class="progress-bar" role="progressbar">
                    <div class="progress"></div>
                </div>

                <!-- Navigation -->
                <div class="wizard-nav">
                    <button class="btn btn-default prev-step" disabled>Previous</button>
                    <button class="btn btn-primary next-step">Next</button>
                    <button class="btn btn-success finish-wizard" style="display:none">Finish</button>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none" role="alert"></div>

                <!-- Loading Indicator -->
                <div class="loading-overlay">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading...</span>
                </div>

                {input_html}
            </div>

            <script>
            $(document).ready(function() {{
                const wizard = new WizardWidget('{field.id}', {{
                    steps: {_js_json(self.steps)},
                    validation: {str(self.validation).lower()},
                    saveState: {str(self.save_state).lower()},
                    linear: {str(self.linear).lower()},
                    transitions: {_js_json(self.transitions)},
                    templates: {_js_json(self.templates)},
                    dependencies: {_js_json(self.dependencies)},
                    branching: {_js_json(self.branching)},
                    analytics: {str(self.analytics).lower()},
                    customLayouts: {_js_json(self.custom_layouts)},
                    persistence: '{self.persistence}',
                    autosave: {str(self.autosave).lower()},
                    paymentConfig: {_js_json(self.payment_config)},
                    uploadConfig: {_js_json(self.upload_config)},

                    onStepChange: function(step) {{
                        updateProgress(step);
                        trackProgress(step);
                    }},

                    onValidationError: function(errors) {{
                        showErrors(errors);
                    }},

                    onSave: function(success) {{
                        updateSaveStatus(success);
                    }}
                }});

                function updateProgress(step) {{
                    const percent = ((step + 1) / wizard.steps.length) * 100;
                    $('.progress').css('width', percent + '%');
                }};

                function showErrors(errors) {{
                    const alert = $('.wizard-widget .alert');
                    alert.html(errors.join('<br>')).show();
                    setTimeout(() => alert.fadeOut(), 5000);
                }};

                function updateSaveStatus(success) {{
                    // Handle save status updates
                }};

                // Initialize with existing data
                const existingData = $('#{field.id}').val();
                if (existingData) {{
                    wizard.loadState(JSON.parse(existingData));
                }}

                // Cleanup on unload
                window.addEventListener('unload', function() {{
                    wizard.cleanup();
                }});
            }});
            </script>
        """
        )

    def validate_step(self, step_id: str, data: dict) -> dict:
        """
        Validate step data before progression.

        Args:
            step_id: Current step identifier
            data: Step data to validate

        Returns:
            dict: Validation results with errors
        """
        try:
            # Get step validation rules
            rules = self.steps[step_id].get("validation", {})

            errors = []
            validated = {}

            # Validate required fields
            for field, value in data.items():
                if field in rules.get("required", []) and not value:
                    errors.append(f"{field} is required")

                # Type validation
                field_type = rules.get("types", {}).get(field)
                if field_type and not isinstance(value, field_type):
                    errors.append(f"{field} must be type {field_type.__name__}")

                # Custom validation
                validator = rules.get("custom", {}).get(field)
                if validator and not validator(value):
                    errors.append(f"{field} failed validation")

                validated[field] = value

            return {"valid": len(errors) == 0, "errors": errors, "data": validated}

        except Exception as e:
            return {"valid": False, "errors": [str(e)], "data": {}}

    def save_progress(self, step_id: str, data: dict) -> bool:
        """
        Save current wizard progress.

        Args:
            step_id: Current step identifier
            data: Step data to save

        Returns:
            bool: Save operation success status
        """
        try:
            # Validate data first
            validation = self.validate_step(step_id, data)
            if not validation["valid"]:
                return False

            # Save to selected persistence method
            if self.persistence == "local":
                self._save_local(step_id, validation["data"])
            elif self.persistence == "session":
                self._save_session(step_id, validation["data"])
            elif self.persistence == "database":
                self._save_database(step_id, validation["data"])

            self._data[step_id] = validation["data"]
            return True

        except Exception:
            return False

    def get_next_step(self, current_step: str, data: dict) -> str:
        """
        Determine next step based on current data and branching rules.

        Args:
            current_step: Current step identifier
            data: Current wizard data

        Returns:
            str: Next step identifier
        """
        try:
            # Check dependencies
            for step, deps in self.dependencies.items():
                if all(self._check_dependency(d, data) for d in deps):
                    return step

            # Check branching rules
            if current_step in self.branching:
                for condition, next_step in self.branching[current_step].items():
                    if self._evaluate_condition(condition, data):
                        return next_step

            # Default to next sequential step
            current_idx = self.steps.index(current_step)
            if current_idx < len(self.steps) - 1:
                return self.steps[current_idx + 1]

            return "finish"

        except Exception:
            # On error, return first step
            return self.steps[0]

    def track_progress(self, step_id: str, action: str) -> None:
        """
        Track wizard progress for analytics.

        Args:
            step_id: Current step identifier
            action: User action to track
        """
        if not self.analytics:
            return

        try:
            # Track step change
            if action == "change":
                self._track_event(
                    "step_change",
                    {
                        "step": step_id,
                        "direction": (
                            "forward" if step_id > self._current_step else "back"
                        ),
                    },
                )

            # Track validations
            elif action == "validate":
                self._track_event(
                    "validation", {"step": step_id, "success": len(self._errors) == 0}
                )

            # Track completion
            elif action == "complete":
                self._track_event(
                    "complete",
                    {
                        "steps": len(self.steps),
                        "duration": time.time() - self._start_time,
                    },
                )

        except Exception as e:
            if self.debug:
                print(f"Analytics error: {e}")

    def cleanup(self):
        """Clean up timers and event listeners"""
        try:
            if self._autosave_timer:
                clearTimeout(self._autosave_timer)

            # Clear stored data
            if self.persistence == "local":
                localStorage.removeItem(self._storage_key)

        except Exception as e:
            if self.debug:
                print(f"Cleanup error: {e}")
