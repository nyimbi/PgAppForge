"""RangeSliderWidget, SliderWidget — PgAppForge widget(s)."""

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

class RangeSliderWidget(BS3TextFieldWidget):
    """
    A widget for handling numeric range selection with a slider interface.

    Designed to work with PostgreSQL's numrange type and SQLAlchemy's RangeType.
    Provides an interactive dual-handle slider for selecting numeric ranges.

    Features:
    - Min/max value constraints
    - Step size control
    - Real-time updates
    - Tooltip display
    - Range validation
    - Customizable formatting
    - Keyboard accessibility
    - Touch device support
    - Vertical slider orientation
    - Customizable slider handle and track styling (via kwargs)

    Database Type:
        PostgreSQL: numrange
        SQLAlchemy: RangeType(Integer) or RangeType(Numeric)

    Example Usage:
        price_range = db.Column(RangeType(Numeric), nullable=True)
    """

    data_template = (
        '<div class="range-slider-container">'
        '<div class="range-slider">'
        "<input %(text)s>"
        '<div id="%(field_id)s-slider" class="slider-control"></div>'
        "</div>"
        '<div class="range-inputs">'
        '<input type="number" class="form-control input-sm min-value" placeholder="Min">'
        '<input type="number" class="form-control input-sm max-value" placeholder="Max">'
        "</div>"
        '<div class="range-labels">'
        '<span class="min-label"></span>'
        '<span class="max-label"></span>'
        "</div>"
        "</div>"
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """Initialize RangeSliderWidget with custom settings"""
        super().__init__(**kwargs)
        self.placeholder = kwargs.get("placeholder", "")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)
        self.min = kwargs.get("min", 0)
        self.max = kwargs.get("max", 100)
        self.step = kwargs.get("step", 1)
        self.format_str = kwargs.get(
            "format", "{0}"
        )  # Renamed to avoid shadowing format keyword
        self.prefix = kwargs.get("prefix", "")
        self.suffix = kwargs.get("suffix", "")
        self.tooltips = kwargs.get("tooltips", True)
        self.logarithmic = kwargs.get("logarithmic", False)
        self.reverse = kwargs.get("reverse", False)
        self.orientation = kwargs.get(
            "orientation", "horizontal"
        )  # Default orientation
        self.handle_style = kwargs.get("handle_style", None)  # Custom handle style
        self.track_style = kwargs.get("track_style", None)  # Custom track style
        self.tooltip_options = kwargs.get(
            "tooltip_options", None
        )  # Advanced tooltip options

    def __call__(self, field, **kwargs):
        """Render the range slider widget"""
        kwargs.setdefault("type", "hidden")
        kwargs.setdefault("data-slider-min", self.min)
        kwargs.setdefault("data-slider-max", self.max)
        kwargs.setdefault("data-slider-step", self.step)
        kwargs.setdefault(
            "data-slider-value",
            f"[{field.data[0] if field.data else self.min},{field.data[1] if field.data else self.max}]",
        )
        kwargs.setdefault("data-slider-tooltip", "always" if self.tooltips else "hide")
        kwargs.setdefault("data-slider-orientation", self.orientation)
        kwargs.setdefault("aria-label", field.label.text if field.label else "")
        if self.description:
            kwargs.setdefault("aria-describedby", f"{field.id}_help")
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.disabled:
            kwargs["disabled"] = True

        if self.tooltip_options:
            kwargs.setdefault(
                "data-slider-tooltip-options", json.dumps(self.tooltip_options)
            )

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "text": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        if field.errors:
            html += (
                f'<div class="invalid-feedback d-block" id="{escape(field.id)}_error">'
                + "".join(f"<span>{escape(e)}</span>" for e in field.errors)
                + "</div>"
            )
        if self.description:
            html += (
                f'<small class="form-text text-muted" id="{escape(field.id)}_help">'
                f"{escape(self.description)}</small>"
            )

        return Markup(
            html
            + """
        <style>
            .range-slider-container {
                padding: 20px 10px;
            }
            .range-slider {
                margin-bottom: 15px;
            }
            .range-inputs {
                display: flex;
                gap: 10px;
                margin-bottom: 5px;
            }
            .range-inputs input {
                width: 100px;
            }
            .range-labels {
                display: flex;
                justify-content: space-between;
                font-size: 12px;
                color: #666;
            }
            .slider-control .slider-handle {
                background: #337ab7;
                 %(handle_style)s /* Custom handle style */
            }
            .slider-control .slider-selection {
                background: #8bb4dd;
                 %(track_style)s /* Custom track style */
            }
            .slider-control .slider-track {
                background: #e9ecef;
            }
             .range-slider.slider-vertical .slider-tick-label {
                transform: rotate(-45deg); /* Adjust tick labels for vertical slider */
            }
        </style>
        <script>
            (function() {
                var $container = $('#{field_id}').closest('.range-slider-container');
                var $slider = $('#{field_id}-slider');
                var $minInput = $container.find('.min-value');
                var $maxInput = $container.find('.max-value');
                var $minLabel = $container.find('.min-label');
                var $maxLabel = $container.find('.max-label');

                function formatValue(value) {{
                    return '{prefix}' + '{format}'.replace('{{0}}', value) + '{suffix}';
                }}

                // Initialize slider
                $slider.slider({{
                    min: {min},
                    max: {max},
                    step: {step},
                    value: {value},
                    tooltip: {tooltips},
                    tooltip_split: true,
                    tooltip_format: formatValue,
                    reversed: {reverse},
                    scale: '{scale}',
                    orientation: '{orientation}' // Set orientation in options
                }});

                // Update inputs and labels
                function updateDisplay(values) {{
                    $minInput.val(values[0]);
                    $maxInput.val(values[1]);
                    $minLabel.text(formatValue(values[0]));
                    $maxLabel.text(formatValue(values[1]));
                    $('#{field_id}').val(JSON.stringify(values)); // Store as JSON array
                }}

                // Handle slider changes
                $slider.on('slide', function(ev) {{
                    updateDisplay(ev.value);
                }});

                // Handle manual input
                $minInput.on('change', function() {{
                    var values = $slider.slider('getValue');
                    var newMin = parseFloat($(this).val());
                    if (newMin >= {min} && newMin <= values[1]) {{
                        $slider.slider('setValue', [newMin, values[1]]);
                        updateDisplay([newMin, values[1]]);
                    }} else {{
                         $(this).val(values[0]); // Revert to previous valid value
                    }}
                }});

                $maxInput.on('change', function() {{
                    var values = $slider.slider('getValue');
                    var newMax = parseFloat($(this).val());
                    if (newMax <= {max} && newMax >= values[0]) {{
                        $slider.slider('setValue', [values[0], newMax]);
                        updateDisplay([values[0], newMax]);
                    }} else {{
                        $(this).val(values[1]); // Revert to previous valid value
                    }}
                }});

                // Initialize display
                updateDisplay({value});
            }})();
        </script>
        """.format(
                field_id=field.id,
                min=self.min,
                max=self.max,
                step=self.step,
                value=f"[{field.data[0] if field.data else self.min},{field.data[1] if field.data else self.max}]",
                format=self.format_str,  # Use format_str here
                prefix=self.prefix,
                suffix=self.suffix,
                tooltips=str(self.tooltips).lower(),
                reverse=str(self.reverse).lower(),
                scale="logarithmic" if self.logarithmic else "linear",
                orientation=self.orientation,  # Pass orientation to script
                handle_style=self.handle_style or "",  # Apply custom handle style
                track_style=self.track_style or "",  # Apply custom track style
            )
        )

    def process_formdata(self, valuelist):
        """Process form data to database format, returns a tuple"""
        if valuelist and valuelist[0]:
            try:
                min_val_str, max_val_str = (
                    valuelist[0].strip("[]").split(",")
                )  # Remove brackets and split
                min_val = float(min_val_str)
                max_val = float(max_val_str)

                # Basic validation - you can add more complex validation here if needed (e.g., min < max)
                if not (
                    self.min <= min_val <= self.max
                    and self.min <= max_val <= self.max
                    and min_val <= max_val
                ):
                    raise ValueError("Range values out of bounds")

                return (min_val, max_val)  # Return as a tuple
            except (ValueError, IndexError) as e:
                raise ValueError(_("Invalid range format: ") + str(e))
        return None

    def pre_validate(self, form):
        """Server-side validation to ensure data integrity"""
        if self.data:
            min_val, max_val = self.data
            if not (
                self.min <= min_val <= self.max
                and self.min <= max_val <= self.max
                and min_val <= max_val
            ):
                raise ValidationError(_("Range values out of bounds on server"))

    def process_data(self, value):
        """Process data from database format, expects a tuple or None"""
        if value:
            if isinstance(
                value, str
            ):  # Handle string format if needed, though tuple is preferred
                try:
                    value = json.loads(value)  # Try to parse if it's a JSON string
                except:
                    return None  # or handle differently if string format is not valid

            if (
                isinstance(value, (tuple, list)) and len(value) == 2
            ):  # Expecting tuple or list of length 2
                try:
                    return (
                        float(value[0]),
                        float(value[1]),
                    )  # Ensure values are floats
                except ValueError:
                    return None
        return None


class SliderWidget(BS3TextFieldWidget):
    """
    Advanced slider widget for numerical input with visual feedback, tooltips and enhanced styling.

    Features:
        - Vertical and horizontal orientation
        - Tick marks and labels for value indicators
        - Tooltips showing value on drag
        - Range validation (min/max values)
        - Step increments for discrete value changes
        - Real-time value display, optionally formatted
        - Smooth transition animations
        - Keyboard accessibility and focus styling
        - Touch device support and responsiveness
        - Customizable styles for track, handle, and ticks
        - Error handling for invalid input

    Database Type:
        PostgreSQL: numeric(precision,scale) or integer
        SQLAlchemy: Numeric(precision,scale) or Integer

    Example Usage:
        volume = db.Column(db.Integer, nullable=False, default=50,
                         info={'widget': SliderWidget(
                             orientation='vertical',  # Render slider vertically
                             show_ticks=True,         # Display tick marks
                             ticks_interval=10,      # Ticks every 10 units
                             tooltips=True,           # Show tooltips on handle drag
                             format='{{0}}%'          # Format value as percentage
                         )})
    """

    data_template = (
        '<div class="slider-widget %(orientation)s">'
        '<div class="slider-label">%(label)s</div>'
        '<div class="slider-container">'
        "<input %(range)s>"
        '<output for="%(field_id)s" id="%(field_id)s-output"></output>'
        "</div>"
        '<div class="slider-error"></div>'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize slider widget with extended settings for tooltips, ticks, and styling."""
        super().__init__(**kwargs)
        self.placeholder = kwargs.get("placeholder", "")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)
        self.min_value = kwargs.get("min_value", 0)
        self.max_value = kwargs.get("max_value", 100)
        self.step = kwargs.get("step", 1)
        self.default_value = kwargs.get("default_value", None)
        self.orientation = kwargs.get(
            "orientation", "horizontal"
        )  # 'horizontal' or 'vertical'
        self.formatter = kwargs.get("formatter", None)
        self.show_value = kwargs.get("show_value", True)
        self.show_ticks = kwargs.get(
            "show_ticks", False
        )  # Display tick marks along the slider
        self.ticks_interval = kwargs.get(
            "ticks_interval", None
        )  # Interval for tick marks
        self.tooltips = kwargs.get(
            "tooltips", True
        )  # Enable tooltips to display value on drag
        self.animate = kwargs.get("animate", True)  # Enable animated transitions

    def __call__(self, field, **kwargs):
        """Render the slider widget with added tooltips, tick marks, and vertical orientation support."""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", "range")
        kwargs.setdefault("min", self.min_value)
        kwargs.setdefault("max", self.max_value)
        kwargs.setdefault("step", self.step)
        kwargs.setdefault("aria-label", field.label.text if field.label else "")
        if self.description:
            kwargs.setdefault("aria-describedby", f"{field.id}_help")
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.disabled:
            kwargs["disabled"] = True
        if self.readonly:
            kwargs["readonly"] = True

        if field.data is not None:
            initial_value = field.data
        elif self.default_value is not None:
            initial_value = self.default_value
        else:
            initial_value = self.min_value
        kwargs.setdefault("value", initial_value)

        if initial_value < self.min_value:
            initial_value = self.min_value
        elif initial_value > self.max_value:
            initial_value = self.max_value

        if field.flags.required:
            kwargs["required"] = True

        html = self.data_template % {
            "range": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "orientation": self.orientation,
            "label": escape(field.label.text) if field.label else "",
        }

        if field.errors:
            html += (
                f'<div class="invalid-feedback d-block" id="{escape(field.id)}_error">'
                + "".join(f"<span>{escape(e)}</span>" for e in field.errors)
                + "</div>"
            )
        if self.description:
            html += (
                f'<small class="form-text text-muted" id="{escape(field.id)}_help">'
                f"{escape(self.description)}</small>"
            )

        return Markup(
            html
            + """
        <style>
            /* Enhanced CSS for tooltips, vertical slider, and tick marks */
            .slider-widget { margin-bottom: 1rem; }
            .slider-widget.vertical { height: 200px; } /* Vertical orientation height */
            .slider-widget .slider-label { margin-bottom: 0.5rem; display: block; font-weight: bold; } /* Label style */
            .slider-widget .slider-container { display: flex; align-items: center; gap: 10px; position: relative; } /* Container for slider and output */
            .slider-widget input[type="range"] { flex: 1; -webkit-appearance: none; width: 100%; height: 8px; border-radius: 4px; background: #ddd; outline: none; } /* Base slider styling */
            .slider-widget input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none; width: 20px; height: 20px; border-radius: 50%; background: #007bff; cursor: pointer; transition: all .2s ease-in-out; } /* Slider handle */
            .slider-widget input[type="range"]::-webkit-slider-thumb:hover { transform: scale(1.1); } /* Handle hover effect */
            .slider-widget output { min-width: 40px; padding: 2px 5px; text-align: center; background: #f8f9fa; border-radius: 3px; } /* Output display style */
            .slider-widget.vertical .slider-container { flex-direction: column-reverse; height: 100%; } /* Vertical slider container */
            .slider-widget.vertical input[type="range"] { writing-mode: bt-lr; -webkit-appearance: slider-vertical; height: 100%; width: 8px; } /* Vertical slider input */
            .slider-widget .slider-error { color: #dc3545; font-size: 80%; margin-top: 0.25rem; display: none; } /* Error message style */


            /* Tooltip Styles */
            .slider-widget .slider-container output[data-tooltip]:after {
                position: absolute; content: attr(data-tooltip); padding: 4px 8px; background: rgba(0,0,0,0.7); color: white; border-radius: 4px; bottom: 100%; left: 50%; transform: translateX(-50%); white-space: nowrap;
                margin-bottom: 5px; opacity: 0; visibility: hidden; transition: opacity 0.3s, visibility 0.3s;
            }
            .slider-widget .slider-container input[type="range"]:hover + output[data-tooltip]:after,
            .slider-widget .slider-container input[type="range"]:active + output[data-tooltip]:after,
            .slider-widget .slider-container output[data-tooltip]:hover:after { visibility: visible; opacity: 1; } /* Show tooltip on hover/active */


            %(tick_style)s /* Inject tick mark styles */
        </style>
        <script>
            (function() {
                var slider = document.getElementById('{field_id}');
                var output = document.getElementById('{field_id}-output');
                var $error = $(slider).siblings('.slider-error');


                function formatValue(value) { // Value formatting function, same as before
                    %(formatter)s
                    return value;
                }


                function updateDisplay(value) { // Update display value and tooltip
                    var formattedValue = formatValue(value);
                    if (%(show_value)s) { output.innerHTML = formattedValue; }
                    if (%(tooltips)s) { output.setAttribute('data-tooltip', formattedValue); } // Set tooltip attribute
                }


                updateDisplay(slider.value); // Initialize display


                slider.addEventListener('input', function() { // Input event handler
                    if (%(animate)s) { $(this).addClass('sliding'); }
                    updateDisplay(this.value);
                });


                slider.addEventListener('change', function() { // Change event handler with validation
                    $(this).removeClass('sliding');
                    var value = parseFloat(this.value);
                    if (value < {min_value} || value > {max_value}) {
                        $error.text('Value must be between {min_value} and {max_value}').show();
                        this.value = Math.min(Math.max(value, {min_value}), {max_value});
                        updateDisplay(this.value);
                    } else { $error.hide(); }
                });


                slider.closest('form').addEventListener('reset', function() { // Form reset handler
                    setTimeout(function() {
                        slider.value = {default_value};
                        updateDisplay(slider.value);
                        $error.hide();
                    }, 0);
                });


                %(ticks_script)s // Tick mark script injection
                accessibilityEnhancements(); // Initialize accessibility features


                // --- Accessibility Enhancements ---
                function accessibilityEnhancements() {
                    slider.setAttribute('role', 'slider'); // ARIA role
                    output.setAttribute('role', 'status'); // ARIA status for screen readers
                    slider.setAttribute('aria-valuemin', {min_value}); // ARIA min value
                    slider.setAttribute('aria-valuemax', {max_value}); // ARIA max value
                    updateAriaValue(slider.value); // Initialize ARIA value
                    slider.addEventListener('input', function() { updateAriaValue(this.value); }); // Update ARIA on input
                }


                function updateAriaValue(value) {
                    slider.setAttribute('aria-valuenow', value);
                    slider.setAttribute('aria-valuetext', formatValue(value)); // Use formatted value for ARIA text
                }
            })();
        </script>
        """.format(
                field_id=field.id,
                min_value=self.min_value,
                max_value=self.max_value,
                default_value=(
                    self.default_value
                    if self.default_value is not None
                    else self.min_value
                ),
                show_value=str(self.show_value).lower(),
                animate=str(self.animate).lower(),
                formatter=self._get_formatter_code(),
                tick_style=self._get_ticks_style() if self.show_ticks else "",
                ticks_script=self._get_ticks_script() if self.show_ticks else "",
                tooltips=str(self.tooltips).lower(),  # Pass tooltips config to JS
                orientation=self.orientation,  # Pass orientation to CSS and JS
            )
        )

    def _get_formatter_code(self):
        """Generate value formatter code"""  # Remains same
        if callable(self.formatter):
            return f"return ({self.formatter})(value);"
        return "return value;"

    def _get_ticks_style(self):
        """Generate style for tick marks"""  # Remains same
        if not self.show_ticks:
            return ""  # Return empty string if ticks are disabled

        interval = self.ticks_interval or (self.max_value - self.min_value) / 10
        return """
            .slider-widget input[type="range"] {
                --tick-count: %d;
                background: linear-gradient(to right,
                    transparent var(--tick-offset, 0%%),
                    #aaa var(--tick-offset, 0%%), /* Changed tick color to #aaa for better visibility */
                    #aaa calc(var(--tick-offset, 0%%) + 1px), /* Slightly thinner ticks */
                    transparent calc(var(--tick-offset, 0%%) + 1px)
                ) repeat-x;
                background-size: calc(100%% / var(--tick-count) - 1px) 8px, 100%% 100%%; /* Adjusted background size */
                background-position: center bottom;
            }
            .slider-widget.vertical input[type="range"] {
                background: linear-gradient(to bottom,
                    transparent var(--tick-offset, 0%%),
                    #aaa var(--tick-offset, 0%%), /* Consistent tick color for vertical */
                    #aaa calc(var(--tick-offset, 0%%) + 1px),
                    transparent calc(var(--tick-offset, 0%%) + 1px)
                ) repeat-y;
                background-size: 8px calc(100%% / var(--tick-count) - 1px), 100%% 100%%; /* Adjusted background size for vertical */
                background-position: left center;
            }
        """ % int((self.max_value - self.min_value) / interval)

    def _get_ticks_script(self):
        """Generate script for tick marks"""  # Remains same, now functional
        if not self.show_ticks:
            return ""

        interval = self.ticks_interval or (self.max_value - self.min_value) / 10
        return """
            var interval = %f;
            var tickCount = parseInt((%f - %f) / interval); // Parse to integer for discrete ticks
            slider.style.setProperty('--tick-count', tickCount.toString());


        """ % (
            interval,
            self.max_value,
            self.min_value,
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""  # Remains same
        if valuelist:
            try:
                self.data = float(valuelist[0])
                if self.data < self.min_value:
                    self.data = self.min_value
                elif self.data > self.max_value:
                    self.data = self.max_value
            except ValueError:
                self.data = self.default_value or self.min_value
                raise ValidationError("Invalid slider value, please enter a number")
        else:
            self.data = self.default_value or self.min_value

    def pre_validate(self, form):
        """Enhanced pre_validate to check for valid numeric types and ranges"""  # Enhanced validation
        if form.flags.required and self.data is None:
            raise ValidationError("This field is required")
        if self.data is not None:
            if not isinstance(self.data, (int, float)):  # Ensure data is numeric
                raise ValidationError(
                    "Invalid data type for slider, numeric value required"
                )
            if (
                self.data < self.min_value or self.data > self.max_value
            ):  # Range validation
                raise ValidationError(
                    f"Value must be between {self.min_value} and {self.max_value}"
                )
