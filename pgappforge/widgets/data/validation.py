"""DataValidationRulesBuilder — PgAppForge widget(s)."""

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

class DataValidationRulesBuilder(BS3TextFieldWidget):
    """
    Widget for building complex data validation rules through a visual interface.

    Features:
    - Rule chain building with drag-and-drop
    - Custom functions with syntax highlighting
    - Regular expressions with testing
    - Cross-field validation with dependency tracking
    - Conditional logic with visual flow builder
    - Template library with version control
    - Import/Export rules in multiple formats (JSON, YAML, XML)
    - Interactive testing interface with sample data
    - Custom error messages with templating
    - Rule groups with nesting support
    - Dependency checking with cycle detection
    - Version control with diff view
    - Performance metrics and optimization hints
    - Rule documentation with markdown support
    - Mobile-first responsive design
    - Accessibility compliance (WCAG 2.1)
    - Undo/redo support
    - Rule sharing and collaboration
    - Bulk operations
    - API integration

    Database Type:
        PostgreSQL: JSONB for storing complex rule structures
        SQLAlchemy: JSON type with validation

    Required Dependencies:
    - JsonLogic.js v2.0+ (rule evaluation)
    - ACE Editor v1.4+ (code editing)
    - jQuery QueryBuilder v2.6+ (visual rule building)
    - JSON5 v2.0+ (enhanced JSON parsing)
    - Lodash v4.17+ (utilities)
    - DOMPurify v2.3+ (XSS prevention)

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - LocalStorage (template saving)
    - Clipboard (rule copying)
    - File system (import/export)

    Performance Considerations:
    - Lazy load components
    - Debounce validation
    - Cache rule evaluations
    - Optimize large rulesets
    - Background validation
    - Memory management

    Security Implications:
    - Sanitize custom functions
    - Validate rule complexity
    - Prevent infinite loops
    - Rate limit validation
    - Escape user input
    - CSRF protection

    Example:
        validation_rules = db.Column(db.JSON,
            info={'widget': DataValidationRulesBuilder(
                available_rules=['required', 'regex', 'custom'],
                templates=True,
                testing=True,
                cross_field=True,
                custom_functions={
                    'isValidEmail': 'function(x) { return /\\S+@\\S+\\.\\S+/.test(x); }'
                },
                error_messages={
                    'required': 'This field is required',
                    'regex': 'Invalid format'
                }
            )})
    """

    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/json-logic-js/2.0.2/json-logic.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/ace/1.4.12/ace.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jQuery-QueryBuilder/2.6.2/js/query-builder.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/json5/2.2.0/index.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/dompurify/2.3.3/purify.min.js",
        "/static/js/validation-rules-builder.js",
    ]

    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jQuery-QueryBuilder/2.6.2/css/query-builder.default.min.css",
        "https://cdnjs.cloudflare.com/ajax/libs/ace/1.4.12/ace.min.css",
        "/static/css/validation-rules-builder.css",
    ]

    DEFAULT_RULES = {
        "required": {"type": "boolean", "label": "Required"},
        "regex": {"type": "string", "label": "Regular Expression"},
        "min": {"type": "number", "label": "Minimum Value"},
        "max": {"type": "number", "label": "Maximum Value"},
        "length": {"type": "number", "label": "Length"},
        "email": {"type": "boolean", "label": "Email"},
        "url": {"type": "boolean", "label": "URL"},
        "date": {"type": "boolean", "label": "Date"},
        "numeric": {"type": "boolean", "label": "Numeric"},
    }

    def __init__(self, **kwargs):
        """
        Initialize DataValidationRulesBuilder with custom settings.

        Args:
            available_rules (list): Available validation rules
            templates (bool): Enable rule templates
            testing (bool): Enable rule testing
            cross_field (bool): Enable cross-field validation
            custom_functions (dict): Custom validation functions
            error_messages (dict): Custom error messages
            rule_groups (list): Predefined rule groups
            max_complexity (int): Maximum rule complexity
            auto_validate (bool): Enable real-time validation
            cache_timeout (int): Cache timeout in seconds
            debug_mode (bool): Enable debug logging
            theme (str): UI theme (light/dark)
            locale (str): Interface language
            api_endpoint (str): Remote validation API
            performance_mode (bool): Enable performance optimizations
        """
        super().__init__(**kwargs)

        # Core Features
        self.available_rules = kwargs.get(
            "available_rules", list(self.DEFAULT_RULES.keys())
        )
        self.templates = kwargs.get("templates", True)
        self.testing = kwargs.get("testing", True)
        self.cross_field = kwargs.get("cross_field", False)
        self.custom_functions = kwargs.get("custom_functions", {})
        self.error_messages = kwargs.get("error_messages", {})
        self.rule_groups = kwargs.get("rule_groups", [])
        self.max_complexity = kwargs.get("max_complexity", 100)

        # Advanced Settings
        self.auto_validate = kwargs.get("auto_validate", True)
        self.cache_timeout = kwargs.get("cache_timeout", 3600)
        self.debug_mode = kwargs.get("debug_mode", False)
        self.theme = kwargs.get("theme", "light")
        self.locale = kwargs.get("locale", "en")
        self.api_endpoint = kwargs.get("api_endpoint", None)
        self.performance_mode = kwargs.get("performance_mode", False)

    def render_field(self, field, **kwargs):
        """Render the validation rules builder widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="validation-rules-builder" id="{field.id}-container">
                <!-- Rule Builder -->
                <div class="rule-builder"
                     role="application"
                     aria-label="Validation Rules Builder">
                    <div id="{field.id}-builder"></div>
                </div>

                <!-- Testing Panel -->
                {self._render_test_panel(field.id) if self.testing else ''}

                <!-- Template Library -->
                {self._render_template_library(field.id) if self.templates else ''}

                <!-- Function Editor -->
                <div class="function-editor" style="display:none;">
                    <div id="{field.id}-editor"></div>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;" role="alert" aria-busy="true">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const builder = new ValidationRulesBuilder('{field.id}', {{
                        rules: {_js_json(self.available_rules)},
                        templates: {str(self.templates).lower()},
                        testing: {str(self.testing).lower()},
                        crossField: {str(self.cross_field).lower()},
                        customFunctions: {_js_json(self.custom_functions)},
                        errorMessages: {_js_json(self.error_messages)},
                        ruleGroups: {_js_json(self.rule_groups)},
                        maxComplexity: {self.max_complexity},
                        autoValidate: {str(self.auto_validate).lower()},
                        cacheTimeout: {self.cache_timeout},
                        debugMode: {str(self.debug_mode).lower()},
                        theme: '{self.theme}',
                        locale: '{self.locale}',
                        apiEndpoint: {f"'{self.api_endpoint}'" if self.api_endpoint else 'null'},
                        performanceMode: {str(self.performance_mode).lower()},

                        onChange: function(rules) {{
                            $('#{field.id}').val(JSON.stringify(rules));
                            validateRules(rules);
                        }},

                        onError: function(error) {{
                            showError(error);
                        }},

                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }}
                    }});

                    function validateRules(rules) {{
                        if ({str(self.auto_validate).lower()}) {{
                            builder.validateRules(rules).catch(showError);
                        }}
                    }}

                    function showError(error) {{
                        const alert = $('.validation-rules-builder .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Initialize with existing data
                    const existingRules = $('#{field.id}').val();
                    if (existingRules) {{
                        builder.setRules(JSON.parse(existingRules));
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        builder.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES
        )
        css_includes = "\n".join(
            f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES
        )
        return f"{css_includes}\n{js_includes}"

    def _render_test_panel(self, field_id):
        """Render testing interface"""
        return f"""
            <div class="test-panel">
                <h5>Test Rules</h5>
                <div class="test-input">
                    <textarea id="{field_id}-test-input"
                            class="form-control"
                            placeholder="Enter test data (JSON format)"></textarea>
                </div>
                <button type="button" class="btn btn-primary mt-2" id="{field_id}-test">
                    Run Test
                </button>
                <div class="test-results mt-2"></div>
            </div>
        """

    def _render_template_library(self, field_id):
        """Render template library interface"""
        return f"""
            <div class="template-library">
                <h5>Templates</h5>
                <div class="template-list"></div>
                <button type="button" class="btn btn-secondary mt-2" id="{field_id}-save-template">
                    Save as Template
                </button>
            </div>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_rules(data)
                self.data = data
            except json.JSONDecodeError:
                raise ValueError("Invalid validation rules format")
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_rules(self, rules):
        """Validate rule structure and complexity"""
        if not isinstance(rules, dict):
            raise ValueError("Invalid rules structure")

        required_keys = ["rules", "valid", "condition"]
        if not all(key in rules for key in required_keys):
            raise ValueError("Missing required rule keys")

        if (
            self.max_complexity
            and self._calculate_complexity(rules) > self.max_complexity
        ):
            raise ValueError(
                f"Rules exceed maximum complexity of {self.max_complexity}"
            )

        # Validate custom functions
        for rule in rules.get("rules", []):
            if (
                rule.get("type") == "custom"
                and rule.get("value") not in self.custom_functions
            ):
                raise ValueError(f"Unknown custom function: {rule.get('value')}")

    def _calculate_complexity(self, rules):
        """Calculate rule complexity score"""
        score = 0
        for rule in rules.get("rules", []):
            score += 1
            if "rules" in rule:
                score += self._calculate_complexity(rule)
        return score

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_rules(self.data)
            except ValueError as e:
                raise ValueError(str(e))
