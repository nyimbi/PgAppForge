"""CheckBoxWidget, SwitchWidget, ToggleButtonWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape
from wtforms import Field
from wtforms.fields import (
    BooleanField, DateField, DateTimeField, DecimalField, FileField,
    FloatField, IntegerField, PasswordField, SelectField,
    SelectMultipleField, StringField, TextAreaField,
)
from wtforms.validators import ValidationError
from wtforms.widgets import TextInput, html_params

class CheckBoxWidget(BS3TextFieldWidget):
    """
    Enhanced Checkbox Widget for PgAppForge

    Provides a feature-rich, accessible, and customizable checkbox implementation.

    Features:
        - Multiple states (checked, unchecked, indeterminate)
        - Custom styling and animations
        - Accessibility support (WCAG 2.1 AA compliant)
        - Group selection functionality
        - Mobile optimization
        - RTL support
        - Custom theming
        - Event handling
        - Validation

    Args:
        indeterminate (bool): Enable three-state checkbox
        required (bool): Make field required
        help_text (str): Help text to display below checkbox
        help_tooltip (str): Tooltip text on hover
        wrapper_class (str): Additional CSS classes for wrapper
        label_class (str): Additional CSS classes for label
        default_checked (bool): Initial checked state
        group_name (str): Group identifier for related checkboxes
        custom_icon (str): Custom icon HTML/CSS
        rtl (bool): Enable right-to-left support
        animation (bool): Enable animations
        custom_colors (dict): Custom color scheme
        validation_message (str): Custom validation message
        mobile_optimize (bool): Enable mobile optimizations
        debug (bool): Enable debug logging

    Example:
        >>> checkbox = CheckBoxWidget(
        ...     required=True,
        ...     help_text='Enable feature',
        ...     custom_colors={'checked': '#007bff'}
        ... )
    """

    template = """
        <div class="checkbox-wrapper %(wrapper_class)s">
            <div class="checkbox custom-control custom-checkbox">
                <input type="checkbox"
                       class="custom-control-input"
                       %(checkbox)s>
                <label class="custom-control-label %(label_class)s"
                       for="%(field_id)s">
                    <span class="checkbox-label">%(label)s</span>
                </label>
            </div>
            %(help_text)s
            %(error_text)s
        </div>
    """

    default_colors = {
        "checked": "#0275d8",
        "unchecked": "#6c757d",
        "disabled": "#e9ecef",
        "focus": "#80bdff",
        "error": "#dc3545",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._init_config(kwargs)
        self._init_validation(kwargs)
        self._init_styling(kwargs)

    def _init_config(self, kwargs):
        """Initialize basic configuration"""
        self.indeterminate = kwargs.get("indeterminate", False)
        self.required = kwargs.get("required", False)
        self.help_text = kwargs.get("help_text", "")
        self.help_tooltip = kwargs.get("help_tooltip", "")
        self.group_name = kwargs.get("group_name")
        self.debug = kwargs.get("debug", False)
        self.placeholder = kwargs.get("placeholder", "")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)

    def _init_validation(self, kwargs):
        """Initialize validation settings"""
        self.validation_message = kwargs.get(
            "validation_message", "This field is required"
        )

    def _init_styling(self, kwargs):
        """Initialize styling configuration"""
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.label_class = kwargs.get("label_class", "")
        self.default_checked = kwargs.get("default_checked", False)
        self.custom_icon = kwargs.get("custom_icon")
        self.rtl = kwargs.get("rtl", False)
        self.animation = kwargs.get("animation", True)
        self.mobile_optimize = kwargs.get("mobile_optimize", True)
        self.custom_colors = {**self.default_colors, **kwargs.get("custom_colors", {})}

    def __call__(self, field, **kwargs):
        """Render the checkbox widget"""
        kwargs = self._prepare_kwargs(field, kwargs)
        html = self._render_html(field, kwargs)
        return Markup(html + self._generate_assets(field))

    def _prepare_kwargs(self, field, kwargs):
        """Prepare kwargs for rendering"""
        kwargs = self._set_basic_attributes(field, kwargs)
        kwargs = self._set_aria_attributes(field, kwargs)
        kwargs = self._set_state_attributes(field, kwargs)
        return kwargs

    def _set_basic_attributes(self, field, kwargs):
        """Set basic HTML attributes"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", "checkbox")
        kwargs.setdefault("class", "custom-control-input")
        return kwargs

    def _set_aria_attributes(self, field, kwargs):
        """Set ARIA attributes for accessibility"""
        kwargs["role"] = "checkbox"
        kwargs["aria-label"] = field.label.text if field.label else ""
        kwargs["aria-checked"] = (
            "mixed"
            if self.indeterminate
            else str(getattr(field, "checked", False) or self.default_checked).lower()
        )
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.description:
            kwargs["aria-describedby"] = f"{field.id}_help"
        return kwargs

    def _set_state_attributes(self, field, kwargs):
        """Set state-related attributes"""
        if field.flags.required or self.required:
            kwargs.update(
                {
                    "required": "required",
                    "aria-required": "true",
                    "data-validation-message": self.validation_message,
                }
            )

        if field.flags.disabled:
            kwargs.update({"disabled": "disabled", "aria-disabled": "true"})

        if field.flags.readonly:
            kwargs.update(
                {
                    "readonly": "readonly",
                    "aria-readonly": "true",
                    "onclick": "return false",
                }
            )

        if field.checked or self.default_checked:
            kwargs["checked"] = "checked"

        if self.indeterminate:
            kwargs["indeterminate"] = "true"

        if self.group_name:
            kwargs["data-group"] = self.group_name

        return kwargs

    def _render_html(self, field, kwargs):
        """Render the HTML template"""
        help_attrs = (
            {
                "data-bs-toggle": "tooltip",
                "data-bs-placement": "right",
                "title": self.help_tooltip,
            }
            if self.help_tooltip
            else {}
        )

        help_text = (
            f'<div class="help-text text-muted" {self.html_params(**help_attrs)}>{escape(self.help_text)}</div>'
            if self.help_text
            else ""
        )
        if self.description:
            help_text += (
                f'<small class="form-text text-muted" id="{escape(field.id)}_help">'
                f"{escape(self.description)}</small>"
            )
        error_text = (
            (
                f'<div class="invalid-feedback" id="{escape(field.id)}_error" role="alert">'
                + "".join(f"<span>{escape(e)}</span>" for e in field.errors)
                + "</div>"
            )
            if field.errors
            else ""
        )

        return self.template % {
            "checkbox": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "label": escape(field.label.text) if field.label else "",
            "wrapper_class": self._get_wrapper_classes(field),
            "label_class": self._get_label_classes(field),
            "help_text": help_text,
            "error_text": error_text,
        }

    def _get_wrapper_classes(self, field):
        """Get CSS classes for wrapper"""
        classes = [
            self.wrapper_class,
            "has-error" if field.errors else "",
            "is-required" if field.flags.required else "",
            "is-rtl" if self.rtl else "",
            "no-animation" if not self.animation else "",
            "mobile-optimized" if self.mobile_optimize else "",
        ]
        return " ".join(filter(None, classes))

    def _get_label_classes(self, field):
        """Get CSS classes for label"""
        classes = [
            self.label_class,
            "disabled" if field.flags.disabled else "",
            "readonly" if field.flags.readonly else "",
        ]
        return " ".join(filter(None, classes))

    def _generate_assets(self, field):
        """Generate CSS and JavaScript assets"""
        return self._generate_styles() + self._generate_scripts(field)


# class CheckBoxWidget(BS3TextFieldWidget):
#     """
#     Enhanced Checkbox Widget for PgAppForge

#     Provides a feature-rich, accessible, and customizable checkbox implementation.

#     Features:
#         - Multiple states (checked, unchecked, indeterminate)
#         - Custom styling and animations
#         - Accessibility support (WCAG 2.1 AA compliant)
#         - Group selection functionality
#         - Mobile optimization
#         - RTL support
#         - Custom theming
#         - Event handling
#         - Validation

#     Args:
#         indeterminate (bool): Enable three-state checkbox
#         required (bool): Make field required
#         help_text (str): Help text to display below checkbox
#         help_tooltip (str): Tooltip text on hover
#         wrapper_class (str): Additional CSS classes for wrapper
#         label_class (str): Additional CSS classes for label
#         default_checked (bool): Initial checked state
#         group_name (str): Group identifier for related checkboxes
#         custom_icon (str): Custom icon HTML/CSS
#         rtl (bool): Enable right-to-left support
#         animation (bool): Enable animations
#         custom_colors (dict): Custom color scheme
#         validation_message (str): Custom validation message
#         mobile_optimize (bool): Enable mobile optimizations
#         debug (bool): Enable debug logging
#     """

#     template = """
#         <div class="checkbox-wrapper %(wrapper_class)s">
#             <div class="checkbox custom-control custom-checkbox">
#                 <input type="checkbox"
#                        class="custom-control-input"
#                        %(checkbox)s>
#                 <label class="custom-control-label %(label_class)s"
#                        for="%(field_id)s">
#                     <span class="checkbox-label">%(label)s</span>
#                 </label>
#             </div>
#             %(help_text)s
#             %(error_text)s
#         </div>
#     """

#     default_colors = {
#         "checked": "#0275d8",
#         "unchecked": "#6c757d",
#         "disabled": "#e9ecef",
#         "focus": "#80bdff",
#         "error": "#dc3545",
#     }

#     def __init__(self, **kwargs):
#         """Initialize the checkbox widget with provided configuration."""
#         super().__init__(**kwargs)
#         self._init_config(kwargs)
#         self._init_validation(kwargs)
#         self._init_styling(kwargs)

#     def _init_config(self, kwargs):
#         """Initialize basic configuration settings."""
#         self.indeterminate = kwargs.get("indeterminate", False)
#         self.required = kwargs.get("required", False)
#         self.help_text = kwargs.get("help_text", "")
#         self.help_tooltip = kwargs.get("help_tooltip", "")
#         self.group_name = kwargs.get("group_name")
#         self.debug = kwargs.get("debug", False)

#     def _init_validation(self, kwargs):
#         """Initialize validation settings."""
#         self.validation_message = kwargs.get(
#             "validation_message", "This field is required"
#         )

#     def _init_styling(self, kwargs):
#         """Initialize styling configuration."""
#         self.wrapper_class = kwargs.get("wrapper_class", "")
#         self.label_class = kwargs.get("label_class", "")
#         self.default_checked = kwargs.get("default_checked", False)
#         self.custom_icon = kwargs.get("custom_icon")
#         self.rtl = kwargs.get("rtl", False)
#         self.animation = kwargs.get("animation", True)
#         self.mobile_optimize = kwargs.get("mobile_optimize", True)
#         self.custom_colors = {**self.default_colors, **kwargs.get("custom_colors", {})}

#     def _generate_styles(self):
#         """Generate CSS styles for the checkbox widget."""
#         return """
#         <style>
#             .checkbox-wrapper {
#                 position: relative;
#                 margin-bottom: 1rem;
#             }

#             .checkbox-wrapper .custom-control {
#                 position: relative;
#                 min-height: 1.5rem;
#                 padding-left: 1.5rem;
#             }

#             .checkbox-wrapper .custom-control-input {
#                 position: absolute;
#                 z-index: -1;
#                 opacity: 0;
#             }

#             .checkbox-wrapper .custom-control-label {
#                 position: relative;
#                 margin-bottom: 0;
#                 vertical-align: top;
#                 cursor: pointer;
#             }

#             .checkbox-wrapper .custom-control-label::before {
#                 position: absolute;
#                 top: 0.25rem;
#                 left: -1.5rem;
#                 display: block;
#                 width: 1rem;
#                 height: 1rem;
#                 content: "";
#                 background-color: %(unchecked_color)s;
#                 border: 1px solid rgba(0, 0, 0, 0.25);
#                 border-radius: 0.25rem;
#                 transition: all 0.15s ease-in-out;
#             }

#             .checkbox-wrapper .custom-control-input:checked ~ .custom-control-label::before {
#                 background-color: %(checked_color)s;
#                 border-color: %(checked_color)s;
#             }

#             .checkbox-wrapper .custom-control-input:disabled ~ .custom-control-label::before {
#                 background-color: %(disabled_color)s;
#             }

#             .checkbox-wrapper .custom-control-input:focus ~ .custom-control-label::before {
#                 box-shadow: 0 0 0 0.2rem %(focus_color)s;
#             }

#             .checkbox-wrapper.has-error .custom-control-label::before {
#                 border-color: %(error_color)s;
#             }

#             .checkbox-wrapper .help-text {
#                 margin-top: 0.25rem;
#                 font-size: 0.875rem;
#             }

#             .checkbox-wrapper .invalid-feedback {
#                 display: none;
#                 color: %(error_color)s;
#                 font-size: 0.875rem;
#             }

#             .checkbox-wrapper.has-error .invalid-feedback {
#                 display: block;
#             }

#             %(custom_icon_style)s
#             %(animation_style)s
#             %(mobile_style)s

#             /* RTL Support */
#             .checkbox-wrapper.is-rtl .custom-control {
#                 padding-right: 1.5rem;
#                 padding-left: 0;
#             }

#             .checkbox-wrapper.is-rtl .custom-control-label::before {
#                 right: -1.5rem;
#                 left: auto;
#             }
#         </style>
#         """ % {
#             "checked_color": self.custom_colors["checked"],
#             "unchecked_color": self.custom_colors["unchecked"],
#             "disabled_color": self.custom_colors["disabled"],
#             "focus_color": self.custom_colors["focus"],
#             "error_color": self.custom_colors["error"],
#             "custom_icon_style": self._generate_custom_icon_style(),
#             "animation_style": self._generate_animation_style(),
#             "mobile_style": self._generate_mobile_style(),
#         }

#     def _generate_custom_icon_style(self):
#         """Generate custom icon styles if specified."""
#         if not self.custom_icon:
#             return ""
#         return (
#             """
#             .checkbox-wrapper .custom-control-label::after {
#                 background-image: url(%s);
#             }
#         """
#             % self.custom_icon
#         )

#     def _generate_animation_style(self):
#         """Generate animation styles if enabled."""
#         if not self.animation:
#             return ""
#         return """
#             .checkbox-wrapper:not(.no-animation) .custom-control-label::before,
#             .checkbox-wrapper:not(.no-animation) .custom-control-label::after {
#                 transition: all 0.15s ease-in-out;
#             }
#         """

#     def _generate_mobile_style(self):
#         """Generate mobile optimization styles if enabled."""
#         if not self.mobile_optimize:
#             return ""
#         return """
#             @media (max-width: 768px) {
#                 .checkbox-wrapper.mobile-optimized .custom-control-label {
#                     min-height: 44px;
#                     line-height: 44px;
#                     padding-left: 2.5rem;
#                 }

#                 .checkbox-wrapper.mobile-optimized .custom-control-label::before,
#                 .checkbox-wrapper.mobile-optimized .custom-control-label::after {
#                     top: 50%;
#                     transform: translateY(-50%);
#                     width: 1.5rem;
#                     height: 1.5rem;
#                 }
#             }
#         """

#     def _generate_scripts(self, field):
#         """Generate JavaScript functionality for the checkbox widget."""
#         return """
#         <script>
#             (function() {
#                 'use strict';

#                 const config = {
#                     fieldId: '%(field_id)s',
#                     indeterminate: %(indeterminate)s,
#                     defaultChecked: %(default_checked)s,
#                     debug: %(debug)s
#                 };

#                 class CheckboxManager {
#                     constructor(config) {
#                         this.config = config;
#                         this.checkbox = document.getElementById(config.fieldId);
#                         this.wrapper = this.checkbox.closest('.checkbox-wrapper');
#                         this.init();
#                     }

#                     init() {
#                         this.initializeState();
#                         this.bindEvents();
#                         this.initializeAccessibility();
#                         this.initializeTooltips();
#                         this.log('Initialized');
#                     }

#                     initializeState() {
#                         if (this.config.indeterminate) {
#                             this.checkbox.indeterminate = true;
#                             this.log('Set initial indeterminate state');
#                         }
#                     }

#                     bindEvents() {
#                         this.checkbox.addEventListener('change', this.handleChange.bind(this));
#                         this.checkbox.addEventListener('keydown', this.handleKeydown.bind(this));

#                         const form = this.wrapper.closest('form');
#                         if (form) {
#                             form.addEventListener('reset', this.handleFormReset.bind(this));
#                             if (this.checkbox.required) {
#                                 form.addEventListener('submit', this.handleFormSubmit.bind(this));
#                             }
#                         }
#                     }

#                     handleChange(event) {
#                         const checked = this.checkbox.checked;
#                         const indeterminate = this.checkbox.indeterminate;

#                         this.log(`State changed: Checked=${checked}, Indeterminate=${indeterminate}`);

#                         this.checkbox.setAttribute('aria-checked',
#                             indeterminate ? 'mixed' : checked.toString());

#                         this.wrapper.classList.remove('has-error');

#                         if (this.checkbox.dataset.group) {
#                             this.handleGroupChange(checked);
#                         }

#                         // Trigger custom event
#                         const customEvent = new CustomEvent('checkbox:changed', {
#                             detail: { checked, indeterminate }
#                         });
#                         this.checkbox.dispatchEvent(customEvent);
#                     }

#                     handleKeydown(event) {
#                         if (event.key === ' ' || event.key === 'Enter') {
#                             event.preventDefault();
#                             this.checkbox.click();
#                         }
#                     }

#                     handleFormSubmit(event) {
#                         if (!this.checkbox.checked) {
#                             event.preventDefault();
#                             this.wrapper.classList.add('has-error');
#                             this.log('Validation failed');
#                         }
#                     }

#                     handleFormReset() {
#                         setTimeout(() => {
#                             this.checkbox.checked = this.config.defaultChecked;
#                             this.checkbox.indeterminate = this.config.indeterminate;
#                             this.checkbox.dispatchEvent(new Event('change'));
#                             this.wrapper.classList.remove('has-error');
#                             this.log('Form reset handled');
#                         }, 0);
#                     }

#                     handleGroupChange(checked) {
#                         if (checked) {
#                             const group = this.checkbox.dataset.group;
#                             document.querySelectorAll(`[data-group="${group}"]`)
#                                 .forEach(checkbox => {
#                                     if (checkbox !== this.checkbox) {
#                                         checkbox.checked = false;
#                                         checkbox.dispatchEvent(new Event('change'));
#                                     }
#                                 });
#                         }
#                     }

#                     initializeAccessibility() {
#                         this.enhanceLabels();
#                         this.improveScreenReaderOutput();
#                     }

#                     enhanceLabels() {
#                         const label = this.wrapper.querySelector('.checkbox-label');
#                         if (label && !this.checkbox.getAttribute('aria-labelledby')) {
#                             label.id = `${this.config.fieldId}-label`;
#                             this.checkbox.setAttribute('aria-labelledby', label.id);
#                         }
#                     }

#                     improveScreenReaderOutput() {
#                         if (this.config.indeterminate) {
#                             this.checkbox.setAttribute('aria-label',
#                                 `${this.checkbox.getAttribute('aria-label')} (Indeterminate)`);
#                         }
#                     }

#                     initializeTooltips() {
#                         const tooltip = this.wrapper.querySelector('[data-toggle="tooltip"]');
#                         if (tooltip && typeof $ !== 'undefined') {
#                             $(tooltip).tooltip();
#                         }
#                     }

#                     log(message) {
#                         if (this.config.debug) {
#                             console.log(`[CheckboxWidget] ${message}`);
#                         }
#                     }
#                 }

#                 // Initialize the checkbox manager
#                 new CheckboxManager(config);

#             })();
#         </script>
#         """ % {
#             "field_id": field.id,
#             "indeterminate": str(self.indeterminate).lower(),
#             "default_checked": str(self.default_checked).lower(),
#             "debug": str(self.debug).lower(),
#         }

#     def process_formdata(self, valuelist):
#         """Process form data into Python boolean."""
#         try:
#             self.data = bool(valuelist[0]) if valuelist else False
#         except (ValueError, TypeError) as e:
#             self.data = False
#             raise ValidationError("Invalid boolean value") from e

#     def process_data(self, value):
#         """Process data from Python/database format."""
#         try:
#             self.data = bool(value) if value is not None else False
#         except (ValueError, TypeError) as e:
#             self.data = False
#             raise ValidationError("Invalid database value") from e

#     def pre_validate(self, form):
#         """Perform validation before form processing."""
#         if self.required and not self.data:
#             raise ValidationError(self.validation_message)


class SwitchWidget(BS3TextFieldWidget):
    """
    Enhanced switch/toggle widget for PgAppForge with advanced styling and functionality.

    Features:
    - Custom switch styles and animations
    - Support for disabled/readonly states
    - Indeterminate state support
    - Loading state
    - Custom colors/sizes
    - Validation states
    - Event handling with confirmation dialog
    - Accessibility support (ARIA labels, keyboard navigation)
    - Help text and error messages
    - Customizable label position (left or right) and switch sizes/styles

    Database Type:
        PostgreSQL: boolean
        SQLAlchemy: Boolean

    Example Usage:
        enabled = db.Column(db.Boolean, nullable=False, default=False,
                          info={'widget': SwitchWidget(
                              label_position='left', # Example: label on the left
                              size='lg', # Example: large size switch
                              confirmation=True, # Enable confirmation dialog
                              confirmation_text='Are you sure you want to change this setting?',
                              wrapper_class='text-right' # Example: Right-align the whole wrapper
                          )})
    """

    data_template = (
        '<div class="switch-wrapper %(wrapper_class)s">'
        '<div class="custom-control custom-switch %(size_class)s">'
        '<input type="checkbox" class="custom-control-input" %(checkbox)s>'
        '<label class="custom-control-label %(label_position_class)s" for="%(field_id)s">'
        '<span class="switch-label">%(label)s</span>'
        "</label>"
        "</div>"
        "%(help_text)s"
        "%(error_text)s"
        "</div>"
    )

    def __init__(
        self,
        label_position="right",
        confirmation=False,
        confirmation_text="Are you sure?",
        **kwargs,
    ):
        """Initialize switch widget with extended settings including label position and confirmation"""
        super().__init__(**kwargs)
        self.placeholder = kwargs.get("placeholder", "")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.size = kwargs.get("size", "md")
        self.color = kwargs.get("color", "primary")
        self.help_text = kwargs.get("help_text", "")
        self.loading_text = kwargs.get("loading_text", "Loading...")
        self.on_text = kwargs.get("on_text", "")
        self.off_text = kwargs.get("off_text", "")
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.indeterminate = kwargs.get("indeterminate", False)
        self.disabled = kwargs.get("disabled", False)
        self.readonly = kwargs.get("readonly", False)
        self.required = kwargs.get("required", False)
        self.default = kwargs.get("default", False)
        self.label_position = label_position
        self.confirmation = confirmation
        self.confirmation_text = confirmation_text

    def __call__(self, field, **kwargs):
        """Render the switch widget with enhanced styling, label positioning, and confirmation dialog"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", "checkbox")
        kwargs.setdefault(
            "class", f"custom-control-input switch-{self.size} switch-{self.color}"
        )
        kwargs.setdefault("aria-label", field.label.text if field.label else "")
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.description:
            kwargs.setdefault("aria-describedby", f"{field.id}_help")

        if field.flags.required or self.required:
            kwargs["required"] = "required"
            kwargs["aria-required"] = "true"

        if field.flags.disabled or self.disabled:
            kwargs["disabled"] = "disabled"
            kwargs["aria-disabled"] = "true"

        if field.flags.readonly or self.readonly:
            kwargs["readonly"] = "readonly"
            kwargs["onclick"] = "return false"

        if getattr(field, "checked", False) or (
            not getattr(field, "checked", False) and self.default
        ):
            kwargs["checked"] = "checked"

        help_text = (
            f'<div class="help-text text-muted small">{escape(self.help_text)}</div>'
            if self.help_text
            else ""
        )
        if self.description:
            help_text += (
                f'<small class="form-text text-muted" id="{escape(field.id)}_help">'
                f"{escape(self.description)}</small>"
            )
        error_text = (
            (
                f'<div class="invalid-feedback" id="{escape(field.id)}_error">'
                + "".join(f"<span>{escape(e)}</span>" for e in field.errors)
                + "</div>"
            )
            if field.errors
            else ""
        )

        html = (
            self.data_template
            % {
                "checkbox": self.html_params(name=field.name, **kwargs),
                "field_id": field.id,
                "label": field.label.text,
                "wrapper_class": " ".join(
                    filter(
                        None,
                        [
                            self.wrapper_class,
                            "has-error" if field.errors else "",
                            "is-loading" if self.loading_text else "",
                            "is-required" if self.required else "",
                            f"switch-{self.size}",
                            f"switch-{self.color}",
                            "label-" + self.label_position,
                        ],
                    )
                ),
                "help_text": help_text,
                "error_text": error_text,
                "size_class": f"switch-{self.size}",  # Size variation class
                "label_position_class": f"label-position-{self.label_position}",  # Label position class
            }
        )

        return Markup(
            html
            + """
        <style>
            /* Basic styles remain the same, extended for label positioning and sizes */
            .switch-wrapper { margin-bottom: 1rem; display: inline-block; }
            .switch-wrapper .custom-control-input:checked ~ .custom-control-label::before { background-color: var(--%(color)s); border-color: var(--%(color)s); }
            /* Size variations */
            .switch-wrapper.switch-sm .custom-control-input ~ .custom-control-label::before { height: 1rem; width: 1.75rem; }
            .switch-wrapper.switch-lg .custom-control-input ~ .custom-control-label::before { height: 1.5rem; width: 2.5rem; }
            /* Loading state style remains the same */
            .switch-wrapper.is-loading .switch-label::after { content: " %(loading_text)s"; font-style: italic; color: #66757d; }
            /* Label positioning styles */
            .switch-wrapper .custom-control-label.label-position-left { padding-left: 0; padding-right: 1.75rem; }
            .switch-wrapper .custom-control-label.label-position-left::before,
            .switch-wrapper .custom-control-label.label-position-left::after { left: auto; right: -1.75rem; }


            .switch-wrapper .on-text, .switch-wrapper .off-text { display: none; } // On/Off text styles remain same
            .switch-wrapper .custom-control-input:checked ~ .custom-control-label .on-text { display: inline; }
            .switch-wrapper .custom-control-input:not(:checked) ~ .custom-control-label .off-text { display: inline; }
            .switch-wrapper.has-error .custom-control-input ~ .custom-control-label::before { border-color: #dc3545; } // Error state style remains same
            .switch-wrapper .invalid-feedback { display: block; } // Invalid feedback style remains same


        </style>
        <script>
            (function() {
                var switchEl = document.getElementById('%(field_id)s');
                if (switchEl) {
                    // Indeterminate state handling remains same
                    if (%(indeterminate)s) { switchEl.indeterminate = true; }


                    // Clear error state on change remains same
                    switchEl.addEventListener('change', function() { this.closest('.switch-wrapper').classList.remove('has-error'); });


                    // Enhanced event handler with confirmation dialog
                    switchEl.addEventListener('change', function(e) {
                        var detail = {detail: { checked: this.checked }};
                        if (%(confirmation)s) {
                            e.preventDefault(); // Stop default action
                            var confirmed = confirm('%(confirmation_text)s');
                            if (confirmed) {
                                dispatchChangeEvent.call(this, detail); // Dispatch event if confirmed
                            } else {
                                this.checked = !this.checked; // Revert UI if not confirmed
                            }
                        } else {
                            dispatchChangeEvent.call(this, detail); // Dispatch event directly if no confirmation
                        }
                    });


                    // Dispatch change event function - factored out for conditional confirmation
                    function dispatchChangeEvent(detail) {
                        var event = new CustomEvent('switch:change', detail);
                        this.dispatchEvent(event);
                    }
                }
            })();
        </script>
        """
            % {
                "field_id": field.id,
                "color": self.color,
                "loading_text": self.loading_text,
                "indeterminate": str(self.indeterminate).lower(),
                "confirmation": str(
                    self.confirmation
                ).lower(),  # Pass confirmation flag to JS
                "confirmation_text": self.confirmation_text,  # Pass confirmation text to JS
            }
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""  # Remains the same
        self.data = bool(valuelist)

    def process_data(self, value):
        """Process data from database format"""  # Remains the same
        self.data = bool(value) if value is not None else False


class ToggleButtonWidget(BS3TextFieldWidget):
    """
    Advanced toggle button widget for boolean fields with customizable styling and enhanced interactivity.

    Features:
    - Toggle Button Groups: Supports grouping toggle buttons for mutually exclusive selections.
    - Loading State: Visual loading state with customizable text feedback during async operations.
    - Confirmation Dialog: Optional confirmation dialog to prevent accidental toggling of critical settings.
    - Enhanced Animations: More sophisticated CSS transitions for visual appeal.
    - Customizable Styling: Extends Bootstrap styling with options for custom colors, sizes, and icons.
    - Accessibility: ARIA attributes and improved keyboard navigation for accessibility compliance.
    - Event Handling: More robust JavaScript click handler and custom event triggering.

    Database Type:
        PostgreSQL: boolean
        SQLAlchemy: Boolean

    Example Usage:
        feature_toggle = BooleanField('Feature Enabled',
                                    widget=ToggleButtonWidget(
                                        style='success', # Apply a 'success' (green) style
                                        size='lg', # Use a larger toggle button
                                        animate=True, # Enable enhanced animations
                                        active_text='Enabled', # Custom text for active (on) state
                                        inactive_text='Disabled', # Custom text for inactive (off) state
                                        loading_text='Updating...', # Custom text for loading state
                                        icons={'on': 'fa fa-toggle-on', 'off': 'fa fa-toggle-off', 'loading': 'fa fa-spinner fa-pulse'}, # Custom icons
                                        confirmation=True, # Enable confirmation dialog on toggle
                                        confirmation_text='Are you sure you want to toggle this feature?', # Confirmation dialog text
                                        wrapper_class='mb-3 d-flex justify-content-start', # Custom wrapper class for layout
                                    ))
    """

    data_template = (
        '<div class="toggle-btn-wrapper %(wrapper_class)s">'
        "<input %(checkbox)s>"
        '<label for="%(field_id)s" class="btn %(btn_class)s" role="button">'  # Added role="button" for accessibility
        '<i class="fa %(icon)s"></i> '
        '<span class="toggle-label"><span class="on-text">%(active_text)s</span><span class="off-text">%(inactive_text)s</span></span>'  # Added on-text and off-text spans
        "</label>"
        "%(help_text)s"
        "%(error_text)s"
        "</div>"
    )

    default_icons = {
        "on": "fa fa-check",
        "off": "fa fa-times",
        "loading": "fa fa-spinner fa-spin",
    }

    def __init__(
        self,
        label_position="right",
        confirmation=False,
        confirmation_text="Are you sure?",
        toggle_group=False,
        **kwargs,
    ):
        """
        Initialize toggle button widget with extended settings, including toggle groups, confirmation, and label positioning.
        """
        super().__init__(**kwargs)
        self.placeholder = kwargs.get("placeholder", "")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.style = kwargs.get("style", "primary")
        self.color = kwargs.get("color", self.style)
        self.size = kwargs.get("size", "md")
        self.icons = {**self.default_icons, **kwargs.get("icons", {})}
        self.disabled = kwargs.get("disabled", False)
        self.readonly = kwargs.get("readonly", False)
        self.loading = kwargs.get("loading", False)
        self.loading_text = kwargs.get("loading_text", "Loading...")
        self.help_text = kwargs.get("help_text", "")
        self.animate = kwargs.get("animate", True)
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.active_text = kwargs.get("active_text", "On")
        self.inactive_text = kwargs.get("inactive_text", "Off")
        self.default = kwargs.get("default", False)
        self.label_position = label_position
        self.confirmation = confirmation
        self.confirmation_text = confirmation_text
        self.toggle_group = toggle_group

    def __call__(self, field, **kwargs):
        """Render the toggle button widget, incorporating toggle groups and enhanced event handling."""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", "checkbox")
        kwargs.setdefault("aria-label", field.label.text if field.label else "")
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.description:
            kwargs.setdefault("aria-describedby", f"{field.id}_help")

        if field.flags.required:
            kwargs["required"] = "required"
        if field.flags.disabled or self.disabled:
            kwargs["disabled"] = "disabled"
        if field.flags.readonly or self.readonly:
            kwargs["readonly"] = "readonly"
            kwargs["onclick"] = "return false"
        if getattr(field, "checked", False) or (not getattr(field, "checked", False) and self.default):
            kwargs["checked"] = "checked"

        error_text = (
            (
                f'<div class="invalid-feedback" id="{escape(field.id)}_error">'
                + "".join(f"<span>{escape(e)}</span>" for e in field.errors)
                + "</div>"
            )
            if field.errors
            else ""
        )
        help_text = (
            f'<div class="help-text text-muted small">{escape(self.help_text)}</div>'
            if self.help_text
            else ""
        )
        if self.description:
            help_text += (
                f'<small class="form-text text-muted" id="{escape(field.id)}_help">'
                f"{escape(self.description)}</small>"
            )

        btn_classes = [
            "btn",
            f"btn-{self.style}",
            f"btn-{self.size}",
            "disabled" if self.disabled else "",
            "loading" if self.loading else "",
        ]
        wrapper_classes = [
            self.wrapper_class,
            "has-error" if field.errors else "",
            "is-loading" if self.loading else "",
            "is-disabled" if self.disabled else "",
            "is-readonly" if self.readonly else "",
            f"label-position-{self.label_position}",
            f"switch-{self.size}",
        ]
        icon_class = (
            self.icons["loading"]
            if self.loading
            else (self.icons["on"] if field.data else self.icons["off"])
        )

        html = self.data_template % {
            "checkbox": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "btn_class": " ".join(filter(None, btn_classes)),
            "wrapper_class": " ".join(filter(None, wrapper_classes)),
            "icon": icon_class,
            "label": field.label.text,
            "error_text": error_text,
            "active_text": self.active_text,  # Use configurable active text
            "inactive_text": self.inactive_text,  # Use configurable inactive text
            "loading_text": self.loading_text,  # Loading text for display
            "size_class": f"switch-{self.size}",
            "label_position_class": f"label-position-{self.label_position}",
        }

        return Markup(
            html
            + """
        <style>
            /* Enhanced CSS for transitions, label positioning, and visual states */
            .toggle-btn-wrapper { display: inline-block; margin-bottom: 1rem; }
            .toggle-btn-wrapper input[type="checkbox"] { display: none; }
            .toggle-btn-wrapper .btn { position: relative; min-width: 80px; text-align: center; transition: background-color 0.3s, border-color 0.3s, color 0.3s, transform 0.2s ease-in-out; } /* Smooth transition */
            .toggle-btn-wrapper .btn.loading { opacity: 0.7; cursor: wait; } /* Loading state opacity */
            .toggle-btn-wrapper.has-error .btn { border-color: #dc3545; }
            .toggle-btn-wrapper .invalid-feedback { display: block; }
            .toggle-btn-wrapper input[type="checkbox"]:checked + .btn { opacity: 1; }
            .toggle-btn-wrapper .toggle-label { display: inline-block; } /* Ensure label is inline block for proper spacing */


            /* Size Variations */
            .switch-wrapper.switch-sm .custom-control-input ~ .custom-control-label::before { height: 1rem; width: 1.75rem; }
            .switch-wrapper.switch-lg .custom-control-input ~ .custom-control-label::before { height: 1.5rem; width: 2.5rem; }


            /* Label Positioning */
            .switch-wrapper.label-position-left .custom-control-label { padding-left: 0; padding-right: 1.75rem; } /* Left label position */
            .switch-wrapper.label-position-left .custom-control-label::before,
            .switch-wrapper.label-position-left .custom-control-label::after { left: auto; right: -1.75rem; } /* Adjust pseudo-elements for left label */


            .toggle-btn-wrapper .on-text, .toggle-btn-wrapper .off-text { display: none; }
            .toggle-btn-wrapper .custom-control-input:checked ~ .custom-control-label .on-text { display: inline; }
            .toggle-btn-wrapper .custom-control-input:not(:checked) ~ .custom-control-label .off-text { display: inline; }


            %(animation_css)s /* Include animation CSS */
        </style>
        <script>
            (function() {
                var $wrapper = $('#%(field_id)s').closest('.toggle-btn-wrapper');
                var $input = $('#%(field_id)s');
                var $btn = $wrapper.find('.btn');


                // Click handler with confirmation and toggle group support
                $btn.on('click', function(e) {
                    if ($input.prop('readonly') || $input.prop('disabled') || $wrapper.hasClass('is-loading')) { e.preventDefault(); return; } // Prevent click if readonly, disabled or loading
                    if (%(confirmation)s) {
                        e.preventDefault();
                        if (!confirm('%(confirmation_text)s')) { return; } // Confirmation dialog
                    }


                    $wrapper.addClass('is-loading'); // Show loading state


                    $input.prop('checked', !$input.prop('checked')); // Toggle input state


                    if (%(animate)s) { // Animation handling
                        $btn.addClass('clicked').delay(200).queue(function() { $(this).removeClass('clicked').dequeue(); });
                    }


                    var isChecked = $input.prop('checked');
                    $btn.find('.fa').removeClass().addClass('fa ' + (isChecked ? '%(on_icon)s' : '%(off_icon)s')); // Update icon
                    $btn.find('.toggle-label .on-text').toggle(isChecked); // Toggle visibility of on/off text spans
                    $btn.find('.toggle-label .off-text').toggle(!isChecked);


                    // Toggle group logic
                    if (%(toggle_group)s) {
                        var groupName = '%(toggle_group)s';
                        $('input[type="checkbox"].custom-control-input[data-toggle-group="' + groupName + '"]').not($input).each(function() {
                            $(this).prop('checked', false).closest('.toggle-btn-wrapper').removeClass('is-loading') // Ensure other toggles in group are not loading
                                .find('.btn').removeClass('active').find('.toggle-label .on-text, .toggle-label .off-text').toggle(false); // Deactivate other toggles in group visually and textually
                                $(this).trigger('change'); // Trigger change event for other toggles in group to update their icons and states
                        });
                         $btn.addClass('active'); // Set current button active state for toggle group
                    }


                    // Simulate async action, replace with your actual async logic
                    setTimeout(function() {
                        $wrapper.removeClass('is-loading'); // Hide loading state after "async" action
                        $input.trigger('change'); // Trigger change event after timeout to finalize state change
                    }, 500); // Simulate async action, adjust timeout as needed


                });


                // Form reset handler remains the same, adjust for text labels
                $input.closest('form').on('reset', function() {
                    setTimeout(function() {
                        var defaultChecked = %(default)s;
                        $input.prop('checked', defaultChecked);
                        $btn.find('.fa').removeClass().addClass('fa ' + (defaultChecked ? '%(on_icon)s' : '%(off_icon)s'));
                        $btn.find('.toggle-label .on-text').toggle(defaultChecked); // Update text labels on reset
                        $btn.find('.toggle-label .off-text').toggle(!defaultChecked);
                    }, 0);
                });
            })();
        </script>
        """
            % {
                "field_id": field.id,
                "animation_css": (
                    """
                .toggle-btn-wrapper .btn.clicked {
                    transform: scale(0.95);
                    transition: transform 0.1s ease-in-out;
                }
            """
                    if self.animate
                    else ""
                ),
                "animate": str(self.animate).lower(),
                "on_icon": self.icons["on"],
                "off_icon": self.icons["off"],
                "active_text": self.active_text,
                "inactive_text": self.inactive_text,
                "default": str(self.default).lower(),
                "confirmation": str(
                    self.confirmation
                ).lower(),  # Pass confirmation to JS
                "confirmation_text": self.confirmation_text,  # Pass confirmation text to JS
                "color": self.color,
                "loading_text": self.loading_text,
                "toggle_group": self.toggle_group,  # Pass toggle_group to JS
            }
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""  # Remains same
        self.data = bool(valuelist)

    def process_data(self, value):
        """Process data from database format"""  # Remains same
        self.data = bool(value) if value is not None else False

    def pre_validate(self, form):
        """Validate field before form processing"""  # Remains same
        if form.flags.required and not self.data:
            raise ValidationError("This field is required")
