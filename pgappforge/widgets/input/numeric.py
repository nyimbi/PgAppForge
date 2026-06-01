"""CurrencyInputWidget, RatingWidget, DurationWidget, StarRatingWidget — PgAppForge widget(s)."""

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

class CurrencyInputWidget(BS3TextFieldWidget):
    """
    Advanced currency input widget for PgAppForge supporting international currencies.

    Features:
    - Currency selection dropdown for multiple currencies
    - Dynamic currency symbol and formatting based on selection
    - Locale-aware formatting using Intl.NumberFormat
    - Real-time validation based on currency and range
    - Precision control for different currencies
    - Customizable currency list and default currency
    - ARIA attributes for accessibility
    - Improved JavaScript error handling

    Database Type:
        PostgreSQL: numeric(precision,scale)
        SQLAlchemy: Numeric(precision,scale)

    Example Usage:
        amount = db.Column(Numeric(precision=20, scale=2))
    """

    data_template = (
        '<div class="currency-input-widget">'
        '<div class="input-group">'
        "%(currency_selector)s"  # Currency selector dropdown
        '<span class="input-group-addon currency-symbol">%(currency_symbol)s</span>'
        "<input %(text)s>"
        "</div>"
        '<div class="currency-error"></div>'
        "</div>"
    )

    empty_template = data_template

    CURRENCIES = {  # Define a list of supported currencies
        "USD": {
            "symbol": "$",
            "locale": "en-US",
            "thousands": ",",
            "decimal": ".",
            "precision": 2,
        },
        "EUR": {
            "symbol": "€",
            "locale": "en-EU",
            "thousands": ".",
            "decimal": ",",
            "precision": 2,
        },
        "GBP": {
            "symbol": "£",
            "locale": "en-GB",
            "thousands": ",",
            "decimal": ".",
            "precision": 2,
        },
        "JPY": {
            "symbol": "¥",
            "locale": "ja-JP",
            "thousands": ",",
            "decimal": ".",
            "precision": 0,
        },
        "KES": {
            "symbol": "KSh",
            "locale": "en-KE",
            "thousands": ",",
            "decimal": ".",
            "precision": 2,
        },  # Example: Kenyan Shilling
    }

    def __init__(self, **kwargs):
        """Initialize currency widget with extended settings"""
        super().__init__(**kwargs)
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)
        self.currency = kwargs.get("currency", "USD")
        if self.currency not in self.CURRENCIES:
            self.currency = "USD"  # Fallback to USD if invalid currency provided

        self.precision = self.CURRENCIES[self.currency]["precision"]
        self.min_value = kwargs.get("min_value", None)
        self.max_value = kwargs.get("max_value", None)
        self.allow_negative = kwargs.get("allow_negative", False)
        self.placeholder = kwargs.get(
            "placeholder", self.CURRENCIES[self.currency]["symbol"] + "0.00"
        )  # Placeholder based on default currency
        self.locale = self.CURRENCIES[self.currency]["locale"]
        self.thousands_sep = self.CURRENCIES[self.currency]["thousands"]
        self.decimal_sep = self.CURRENCIES[self.currency]["decimal"]
        self.symbol_position = kwargs.get("symbol_position", "prefix")
        self.available_currencies = kwargs.get(
            "available_currencies", list(self.CURRENCIES.keys())
        )  # Customizable available currencies

    def __call__(self, field, **kwargs):
        """Render the currency input widget with currency selector and dynamic formatting"""
        kwargs.setdefault("type", "text")
        kwargs.setdefault("placeholder", self.placeholder)
        kwargs.setdefault("class", "form-control currency-input" + (" is-invalid" if field.errors else ""))
        kwargs.setdefault("data-precision", self.precision)
        kwargs.setdefault("data-thousands", self.thousands_sep)
        kwargs.setdefault("data-decimal", self.decimal_sep)
        kwargs.setdefault("data-symbol-position", self.symbol_position)
        kwargs.setdefault("aria-label", field.label.text if field.label else "")
        if self.description:
            kwargs.setdefault("aria-describedby", f"{field.id}_help")
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.readonly:
            kwargs["readonly"] = True
        if self.disabled:
            kwargs["disabled"] = True

        if field.flags.required:
            kwargs["required"] = True

        currency_selector_html = self._render_currency_selector(
            field.id, self.currency
        )
        template = self.data_template if field.data else self.empty_template
        html = template % {
            "text": self.html_params(name=field.name, **kwargs),
            "currency_symbol": self.CURRENCIES[self.currency]["symbol"],
            "currency_selector": currency_selector_html,
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
            .currency-input-widget .currency-error {
                color: #a94442;
                margin-top: 5px;
                font-size: 12px;
            }
            .currency-input-widget .input-group-addon.currency-symbol {
                min-width: 40px;
                text-align: center;
            }
            .currency-input.error {
                border-color: #a94442;
            }
            .currency-selector {
                max-width: 80px; /* Adjust as needed */
            }
        </style>
        <script>
            $(document).ready(function() {
                var $input = $('#{field_id}');
                var $widget = $input.closest('.currency-input-widget');
                var $error = $widget.find('.currency-error');
                var $currencySelector = $widget.find('.currency-selector'); // Currency selector element
                var locale = '{locale}';
                var widgetCurrency = '{currency}'; // Initial widget currency


                function updateMaskMoney(currencyCode) {{
                    var currencyFormat = {currency_formats}[currencyCode];
                    if (!currencyFormat) {{
                        console.error('Currency format not found for:', currencyCode);
                        return;
                    }}

                    $widget.find('.currency-symbol').text(currencyFormat.symbol); // Update symbol

                    $input.maskMoney('destroy'); // Destroy existing mask
                    $input.maskMoney({{ // Re-initialize maskMoney with new settings
                        prefix: currencyFormat.symbol_prefix,
                        suffix: currencyFormat.symbol_suffix,
                        thousands: currencyFormat.thousands_sep,
                        decimal: currencyFormat.decimal_sep,
                        precision: currencyFormat.precision,
                        allowZero: true,
                        allowNegative: {allow_negative}
                    }});

                    $input.maskMoney('mask'); // Re-mask the input
                }}


                function formatNumber(num, precision, locale) {{
                    return new Intl.NumberFormat(locale, {{
                        minimumFractionDigits: precision,
                        maximumFractionDigits: precision
                    }}).format(num);
                }}


                function parseNumber(str) {{
                    return Number(str.replace(/[^-0-9.]/g, ''));
                }}


                // Initialize maskMoney on widget load
                updateMaskMoney(widgetCurrency);


                // Currency Selector change handler
                $currencySelector.on('change', function() {{
                    widgetCurrency = $(this).val(); // Update widget currency
                    updateMaskMoney(widgetCurrency); // Update mask and symbol
                    locale = {currency_formats}[widgetCurrency].locale; // Update locale for formatting
                    $input.trigger('keyup'); // Re-trigger validation and formatting
                }});



                $input.on('change keyup', function() {{
                    var value = parseNumber($(this).val());
                    var isValid = true;
                    var errorMsg = '';


                    // Validate min value
                    {min_check}


                    // Validate max value
                    {max_check}


                    // Update UI based on validation
                    if (!isValid) {{
                        $input.addClass('error');
                        $error.text(errorMsg);
                    }} else {{
                        $input.removeClass('error');
                        $error.text('');
                    }}
                }});


                // Initialize with existing value and trigger change to apply formatting
                if ($input.val()) {{
                    $input.trigger('change');
                }}
            }});
        </script>
        """.format(
                field_id=field.id,
                locale=self.locale,
                currency=self.currency,
                precision=self.precision,
                symbol_prefix=(
                    "'{}'".format(self.CURRENCIES[self.currency]["symbol"])
                    if self.symbol_position == "prefix"
                    else "''"
                ),
                symbol_suffix=(
                    "'{}'".format(self.CURRENCIES[self.currency]["symbol"])
                    if self.symbol_position == "suffix"
                    else "''"
                ),
                thousands_sep=self.thousands_sep,
                decimal_sep=self.decimal_sep,
                allow_negative=str(self.allow_negative).lower(),
                min_check=(
                    """
                if (value < {}) {{
                    isValid = false;
                    errorMsg = 'Value must be at least {}'.format(
                        formatNumber({}, {precision}, locale)
                    );
                }}
            """.format(self.min_value, self.min_value, precision=self.precision)
                    if self.min_value is not None
                    else ""
                ),
                max_check=(
                    """
                if (value > {}) {{
                    isValid = false;
                    errorMsg = 'Value must be at most {}'.format(
                        formatNumber({}, {precision}, locale)
                    );
                }}
            """.format(self.max_value, self.max_value, precision=self.precision)
                    if self.max_value is not None
                    else ""
                ),
                currency_formats=json.dumps(
                    self.CURRENCIES
                ),  # Pass currency formats to JS
            )
        )

    def _render_currency_selector(self, field_id, selected_currency):
        """Render the currency selector dropdown"""
        html = f'<select class="currency-selector form-control input-sm" id="{field_id}-currency-selector" aria-label="Select Currency">'
        for code, currency_data in self.CURRENCIES.items():
            selected = "selected" if code == selected_currency else ""
            html += f'<option value="{code}" {selected}>{code} ({currency_data["symbol"]})</option>'
        html += "</select>"
        return html

    def pre_validate(self, form):
        """Validate the field value before form processing"""
        value = self.data
        if value is not None:
            if self.min_value is not None and value < self.min_value:
                raise ValueError(_("Value must be at least ") + str(self.min_value))
            if self.max_value is not None and value > self.max_value:
                raise ValueError(_("Value must be at most ") + str(self.max_value))
            if not self.allow_negative and value < 0:
                raise ValueError(_("Negative values are not allowed"))

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                # Parse number using locale settings
                value = valuelist[0]
                value = value.replace(
                    self.CURRENCIES[self.currency]["symbol"], ""
                ).strip()  # Remove currency symbol
                value = value.replace(
                    self.thousands_sep, ""
                )  # Remove thousands separator
                value = value.replace(
                    self.decimal_sep, "."
                )  # Ensure decimal separator is '.' for float conversion
                value = float(value)
                return round(value, self.precision)  # Round to currency precision
            except (ValueError, TypeError) as e:
                raise ValueError(_("Invalid currency value: ") + str(e))
        return None

    def process_data(self, value):
        """Process data from database format"""
        if value is not None:
            try:
                # Format number for display based on widget locale and precision
                return "{:.{}f}".format(float(value), self.precision)
            except (ValueError, TypeError):
                return None
        return None


class RatingWidget(BS3TextFieldWidget):
    """
    Advanced rating widget supporting half-stars, custom scales, and rich interaction.

    Database Type:
        PostgreSQL: numeric(3,1) or float
        SQLAlchemy: Numeric(3,1) or Float

    Features:
    - Half-star ratings
    - Custom star counts
    - Customizable star icons (beyond Font Awesome)
    - Rating categories or dimensions (for multi-dimensional ratings)
    - Average rating display
    - Visual feedback on hover/click (e.g., animations)
    - Hover effects
    - Click feedback
    - Read-only mode
    - Clear rating option
    - Accessibility support (ARIA attributes for screen readers and keyboard)
    - Mobile touch support
    """

    data_template = (
        '<div class="rating-widget-container">'
        "<input %(hidden)s>"
        '<div id="%(field_id)s-stars" class="rating-stars" role="radiogroup" aria-label="Rating Stars"></div>'  # Added ARIA label
        '<div class="rating-hint" aria-live="polite"></div>'  # Added aria-live for dynamic hint updates
        '<div class="rating-clear" style="display:none">'
        '<button type="button" class="btn btn-xs btn-default" aria-label="Clear Rating">Clear</button>'  # Added ARIA label
        "</div>"
        '<div class="rating-average" style="display:none"></div>'  # Container for average rating display
        "</div>"
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """Initialize rating widget with custom settings"""
        super().__init__(**kwargs)
        self.placeholder = kwargs.get("placeholder", "")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)
        self.number = kwargs.get("number", 5)
        self.enable_half = kwargs.get("enable_half", True)  # Allow half stars
        self.star_on = kwargs.get("star_on", "fa fa-star")  # Icon for filled star
        self.star_off = kwargs.get("star_off", "fa fa-star-o")  # Icon for empty star
        self.star_half = kwargs.get(
            "star_half", "fa fa-star-half-o"
        )  # Icon for half star
        self.hints = kwargs.get("hints", None)  # Tooltips for each star
        self.allow_clear = kwargs.get("allow_clear", True)  # Allow clearing rating
        self.readonly = kwargs.get("readonly", False)  # Read-only mode
        self.star_color = kwargs.get("star_color", "#FFD700")  # Star color
        self.min_rating = kwargs.get("min_rating", 0)  # Minimum rating allowed
        self.step = kwargs.get(
            "step", 0.5 if self.enable_half else 1
        )  # Rating increment
        self.star_icon_classes = kwargs.get(
            "star_icon_classes", {}
        )  # New: Custom star icon classes
        self.enable_animation = kwargs.get(
            "enable_animation", True
        )  # New: Enable hover/click animations
        self.average_rating = kwargs.get(
            "average_rating", None
        )  # New: Average rating to display

    def __call__(self, field, **kwargs):
        """Render the rating widget"""
        kwargs.setdefault("type", "hidden")
        kwargs.setdefault("aria-label", field.label.text if field.label else "")
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.description:
            kwargs.setdefault("aria-describedby", f"{field.id}_help")
        if self.disabled:
            kwargs["disabled"] = True

        if field.flags.required:
            kwargs["required"] = True
            kwargs.setdefault("aria-required", "true")

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
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
            .rating-widget-container {
                position: relative;
                display: inline-block;
            }
            .rating-stars {
                font-size: 20px;
                cursor: pointer;
                display: flex; /* Enable flexbox for star icons */
            }
            .rating-stars.readonly {
                cursor: default;
            }
            .rating-stars i {
                padding: 2px;
                transition: transform 0.1s ease-out; /* Add transition for smoother animation */
            }
            .rating-stars i:hover, .rating-stars i:focus {
                transform: scale(1.2); /* Example hover/focus feedback */
            }
            .rating-hint {
                margin-top: 5px;
                font-size: 12px;
                min-height: 20px;
            }
            .rating-clear {
                margin-top: 5px;
            }
            .rating-stars .star-on {
                color: {star_color};
            }
            .rating-average {
                margin-top: 5px;
                font-size: 14px;
                font-weight: bold;
            }
        </style>
        <script>
            (function() {{
                var $container = $('#{field_id}').closest('.rating-widget-container');
                var $stars = $('#{field_id}-stars');
                var $hint = $container.find('.rating-hint');
                var $clear = $container.find('.rating-clear');
                var $average = $container.find('.rating-average'); // Average rating display container
                var hints = {hints};
                var currentRating = {score};


                function initRating() {{
                    $stars.raty({{
                        score: currentRating,
                        number: {number},
                        half: {enable_half},
                        starOn: '{star_on}',
                        starOff: '{star_off}',
                        starHalf: '{star_half}',
                        hints: hints,
                        readOnly: {readonly},
                        round: {{down: .26, full: .6, up: .76}},
                        step: {step},
                        cancelButton: {str(self.allow_clear).lower()}, // Enable clear button in Raty
                        click: function(score, evt) {{
                            currentRating = score;
                            updateRating(score);
                        }},
                        mouseover: function(score, evt) {{
                            if (!{readonly}) {{
                                showHint(score);
                            }}
                        }},
                        mouseout: function(score, evt) {{
                            if (!{readonly}) {{
                                showHint(currentRating);
                            }}
                        }},
                         starType: 'i', // Use Font Awesome icons
                         starOnClass: '{star_icon_on}', // Custom star on class
                         starOffClass: '{star_icon_off}', // Custom star off class
                         starHalfClass: '{star_icon_half}' // Custom half star class

                    }});

                    // Initialize hint and clear button
                    showHint(currentRating);
                    if ({allow_clear} && !{readonly}) {{
                        $clear.show();
                    }}

                    // Display average rating if available
                    if ({show_average}) {{
                        $average.text('Average Rating: ' + {average_rating}).show();
                    }}
                }}


                function updateRating(score) {{
                    if (score < {min_rating}) score = {min_rating};
                    $('#{field_id}').val(score).trigger('change');
                    showHint(score);
                    $clear.toggle(score > 0);
                }}

                function showHint(score) {{
                    if (!hints) return;
                    var hint = score ? hints[Math.ceil(score) - 1] : '';
                    $hint.text(hint);
                }}

                // Clear rating handler - using Raty's cancelButton feature now
                $stars.on('raty:cancel', function(evt) {{
                    currentRating = {min_rating};
                    updateRating({min_rating});
                }});


                // Initialize widget
                initRating();


                // Handle form reset
                $container.closest('form').on('reset', function() {{
                    currentRating = {min_rating};
                    updateRating({min_rating});
                    $stars.raty('score', {min_rating});
                }});
            }})();
        </script>
        """.format(
                field_id=field.id,
                score=field.data if field.data is not None else self.min_rating,
                number=self.number,
                enable_half=str(self.enable_half).lower(),
                star_on=self.star_on,
                star_off=self.star_off,
                star_half=self.star_half,
                hints=json.dumps(
                    self.hints if self.hints else ["" for _ in range(self.number)]
                ),
                readonly=str(self.readonly).lower(),
                allow_clear=str(
                    self.allow_clear
                ).lower(),  # Pass allow_clear for cancel button
                star_color=self.star_color,
                min_rating=self.min_rating,
                step=self.step,
                star_icon_on=self.star_icon_classes.get(
                    "on", "star-on"
                ),  # Get custom on class or default
                star_icon_off=self.star_icon_classes.get(
                    "off", "star-off"
                ),  # Get custom off class or default
                star_icon_half=self.star_icon_classes.get(
                    "half", "star-half"
                ),  # Get custom half class or default
                show_average=str(
                    bool(self.average_rating)
                ).lower(),  # Pass boolean for average rating display
                average_rating=self.average_rating,  # Pass average rating value
            )
        )

    def pre_validate(self, form):
        """Validate the rating value"""
        if self.data is not None:
            if self.data < self.min_rating:
                raise ValidationError(
                    f"Rating cannot be less than {self.min_rating}"
                )  # More specific error message
            if self.data > self.number:
                raise ValidationError(
                    f"Rating cannot exceed {self.number} stars"
                )  # More specific error message
            if self.enable_half and (self.data * 2) % 1 != 0:
                raise ValidationError(
                    "Rating must be a whole or half star value"
                )  # More specific error message for half-star
            if not self.enable_half and self.data % 1 != 0:
                raise ValidationError(
                    "Rating must be a whole number value"
                )  # More specific error message for whole star

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                self.data = float(valuelist[0])
            except ValueError as e:
                raise ValidationError(
                    "Invalid rating value: " + str(e)
                )  # More descriptive ValidationError
        else:
            self.data = None

    def process_data(self, value):
        """Process data from database format"""
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                return None
        return None


class DurationWidget(BS3TextFieldWidget):
    """
    Advanced duration input widget for PgAppForge with PostgreSQL interval support.

    Features:
    - Granular unit controls with separate inputs for days, hours, minutes, seconds
    - Duration calculations (add, subtract) via buttons or custom input
    - Multiple display formats (verbose, short, ISO 8601) with format conversion
    - Real-time validation and error messages for duration ranges and formats
    - PostgreSQL interval and timedelta compatibility for database storage
    - Accessibility support and improved user feedback

    Database Type:
        PostgreSQL: interval
        SQLAlchemy: Interval

    Example Usage:
        duration = db.Column(Interval)
    """

    data_template = (
        '<div class="duration-widget">'
        "<input %(hidden)s>"
        '<div class="duration-inputs">'
        ' <input type="number" class="form-control duration-days" placeholder="Days" aria-label="Days">'
        ' <input type="number" class="form-control duration-hours" placeholder="Hours" aria-label="Hours">'
        ' <input type="number" class="form-control duration-minutes" placeholder="Minutes" aria-label="Minutes">'
        ' <input type="number" class="form-control duration-seconds" placeholder="Seconds" aria-label="Seconds" style="display:%(show_seconds_style)s;">'
        "</div>"
        '<div class="duration-controls">'
        '    <button type="button" class="btn btn-default btn-sm calculate-duration" aria-label="Calculate Duration">Calculate</button>'
        '    <div class="duration-preview"></div>'
        "</div>"
        '<div class="duration-error"></div>'
        "</div>"
    )

    empty_template = data_template

    def __init__(self, **kwargs):
        """Initialize duration widget with extended settings for granular control and formatting"""
        super().__init__(**kwargs)
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)
        self.show_seconds = kwargs.get("show_seconds", True)
        self.show_days = kwargs.get("show_days", True)
        self.show_microseconds = kwargs.get("show_microseconds", False)
        self.min_duration = kwargs.get("min_duration", None)
        self.max_duration = kwargs.get("max_duration", None)
        self.step = kwargs.get("step", 1)
        self.format = kwargs.get("format", "verbose")  # 'verbose', 'short', or 'iso'
        self.required = kwargs.get("required", False)
        self.display_format = kwargs.get(
            "display_format", "%H:%M:%S"
        )  # Default display format for preview
        self.enable_calculations = kwargs.get(
            "enable_calculations", False
        )  # Enable duration calculation button

    def __call__(self, field, **kwargs):
        """Render the duration input widget with granular controls and enhanced UI"""
        kwargs.setdefault("type", "text")
        kwargs.setdefault("placeholder", self.placeholder)
        kwargs.setdefault("autocomplete", "off")
        kwargs.setdefault("aria-label", field.label.text if field.label else "")
        if self.description:
            kwargs.setdefault("aria-describedby", f"{field.id}_help")
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.readonly:
            kwargs["readonly"] = True
        if self.disabled:
            kwargs["disabled"] = True

        if self.required:
            kwargs["required"] = True

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "text": self.html_params(name=field.name, **kwargs),
            "show_seconds_style": "block" if self.show_seconds else "none",
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
            .duration-widget {
                position: relative;
                margin-bottom: 15px;
            }
            .duration-inputs {
                display: flex;
                gap: 5px; /* Reduced gap for better alignment */
            }
            .duration-inputs input {
                width: auto; /* Adjust width as needed, or use fixed widths */
                flex-grow: 1;
                text-align: center;
            }
            .duration-controls {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-top: 5px;
            }
            .duration-preview {
                color: #666;
                font-size: 14px;
            }
            .duration-error {
                color: #a94442;
                margin-top: 5px;
                font-size: 12px;
                display: none;
            }
        </style>
        <script>
            $(document).ready(function() {
                var $widget = $('#{field_id}').closest('.duration-widget');
                var $input = $('#{field_id}'); // Hidden input
                var $inputs = $widget.find('.duration-inputs input'); // All unit inputs
                var $preview = $widget.find('.duration-preview');
                var $error = $widget.find('.duration-error');
                var $calculateButton = $widget.find('.calculate-duration'); // Calculate button


                function getDurationFromInputs() {
                    var days = parseInt($widget.find('.duration-days').val()) || 0;
                    var hours = parseInt($widget.find('.duration-hours').val()) || 0;
                    var minutes = parseInt($widget.find('.duration-minutes').val()) || 0;
                    var seconds = parseInt($widget.find('.duration-seconds').val()) || 0;
                    return moment.duration({{ days: days, hours: hours, minutes: minutes, seconds: seconds }});
                }


                function updateHiddenInput(duration) {
                    var isoDuration = duration.toISOString(); // Store duration in ISO format
                    $input.val(isoDuration);
                }


                function updatePreview(duration) {{
                    if (!duration) {{
                        $preview.text('');
                        return;
                    }}
                    var formatted = formatDuration(duration);
                    $preview.text(formatted);
                }}


                function formatDuration(duration) {{
                    if ('{format}' === 'iso') {{
                        return duration.toISOString();
                    }}
                    if ('{format}' === 'short') {{
                        return duration.humanize(); // Using moment.js humanize for short format
                    }}
                    // Verbose format (default)
                    let parts = [];
                    if (duration.days() > 0) parts.push(duration.days() + ' days');
                    if (duration.hours() > 0) parts.push(duration.hours() + ' hours');
                    if (duration.minutes() > 0) parts.push(duration.minutes() + ' minutes');
                    if ({show_seconds} && duration.seconds() > 0) parts.push(duration.seconds() + ' seconds');
                    return parts.join(', ') || '0 seconds';
                }}


                function setInputValues(duration) {{
                    $widget.find('.duration-days').val(duration.days());
                    $widget.find('.duration-hours').val(duration.hours());
                    $widget.find('.duration-minutes').val(duration.minutes());
                    $widget.find('.duration-seconds').val(duration.seconds());
                }}


                function validateDuration(duration) {
                    var isValid = true;
                    var errors = [];

                    let seconds = duration.asSeconds(); // Validate against total seconds for simplicity
                    if ({min_duration} !== null && seconds < {min_duration}) {{
                        isValid = false;
                        errors.push('Duration must be at least ' + formatDuration(moment.duration({seconds: {min_duration}})));
                    }}
                    if ({max_duration} !== null && seconds > {max_duration}) {{
                        isValid = false;
                        errors.push('Duration must not exceed ' + formatDuration(moment.duration({seconds: {max_duration}})));
                    }}


                    if (!isValid) {{
                        $error.text(errors.join('. ')).show();
                        $input.addClass('error');
                    }} else {{
                        $error.hide();
                        $input.removeClass('error');
                    }}
                    return isValid;
                }}


                // Calculate Duration Button Handler
                $calculateButton.click(function(e) {{
                    e.preventDefault();
                    var duration = getDurationFromInputs();
                    if (validateDuration(duration)) {{
                        updateHiddenInput(duration);
                        updatePreview(duration);
                    }}
                }});


                // Initialize with existing value from hidden input
                if ($input.val()) {{
                    try {{
                        var initialDuration = moment.duration($input.val()); // Parse ISO duration
                        setInputValues(initialDuration);
                        updatePreview(initialDuration);
                        validateDuration(initialDuration.asSeconds()); // Validate initial value
                    }} catch (e) {{
                        console.error('Error parsing duration:', e);
                        $error.text('Invalid duration format in saved data.').show();
                    }}
                }}


                // Form reset handler
                $input.closest('form').on('reset', function() {{
                    setTimeout(function() {{
                        setInputValues(moment.duration(0)); // Reset input fields to zero
                        updateHiddenInput(moment.duration(0)); // Reset hidden input to zero duration
                        updatePreview(moment.duration(0)); // Clear preview
                        $error.hide(); // Hide error message
                        $input.removeClass('error'); // Remove error class
                    }}, 0);
                }});
            }})();
        </script>
        """.format(
                field_id=field.id,
                show_seconds=str(self.show_seconds).lower(),
                show_days=str(self.show_days).lower(),
                show_microseconds=str(self.show_microseconds).lower(),
                step=self.step,
                min_duration=self.min_duration
                if self.min_duration is not None
                else "null",
                max_duration=self.max_duration
                if self.max_duration is not None
                else "null",
                format=self.format,
            )
        )

    def process_formdata(self, valuelist):
        """Process form data to database format (interval)"""
        if valuelist:
            try:
                from datetime import timedelta

                time_str = valuelist[
                    0
                ]  # Expecting ISO 8601 duration string from widget
                duration = moment.duration(
                    time_str
                )  # Parse ISO duration string using moment.js
                return timedelta(
                    seconds=duration.asSeconds()
                )  # Convert to timedelta for SQLAlchemy Interval
            except ValueError as e:
                raise ValidationError(
                    "Invalid duration format: " + str(e)
                ) from e  # More specific error message
        return None

    def process_data(self, value):
        """Process data from database format to widget (ISO 8601)"""
        if value is not None:
            try:
                if isinstance(value, str):
                    return value  # If already ISO string, return as is
                return moment.duration(
                    value.total_seconds(), "seconds"
                ).toISOString()  # Convert timedelta to ISO string
            except (ValueError, TypeError, AttributeError) as e:
                return None  # Handle cases where conversion fails
        return None

    def pre_validate(self, form):
        """Validate the duration value before form processing"""
        if self.data is not None:
            from datetime import timedelta

            if self.min_duration is not None and self.data < timedelta(
                seconds=self.min_duration
            ):
                raise ValidationError(
                    f"Duration must be at least {self.min_duration} seconds"
                )  # User-friendly error message
            if self.max_duration is not None and self.data > timedelta(
                seconds=self.max_duration
            ):
                raise ValidationError(
                    f"Duration must not exceed {self.max_duration} seconds"
                )  # User-friendly error message


class StarRatingWidget(BS3TextFieldWidget):
    """
    Advanced star rating widget for PgAppForge with customizable features.

    Features:
    - Configurable number of stars
    - Half-star ratings support
    - Customizable star shapes (FontAwesome icons, custom images, or Unicode characters)
    - Dynamic hint text display based on rating value
    - Rating breakdown visualization (display distribution of ratings)
    - Integration with backend for storing individual ratings and average rating calculation
    - Customizable colors and sizes
    - Read-only mode
    - Clear rating option
    - Hover effects and animation
    - Accessibility support (ARIA attributes, keyboard navigation)
    - Touch device support

    Database Type:
        PostgreSQL: numeric(3,1) or float
        SQLAlchemy: Numeric(3,1) or Float

    Example Usage:
        rating = db.Column(Numeric(3,1), nullable=True, default=0,
                         info={'widget': StarRatingWidget(
                             max_stars=10,
                             enable_half=True,
                             star_color='#ffb300',
                             star_shape='★', # Unicode star character
                             hints=['Awful', 'Poor', 'Fair', 'Good', 'Excellent'],
                             show_distribution=True # Enable rating distribution display
                         )})
    """

    data_template = (
        '<div class="star-rating-container">'
        "<input %(hidden)s>"
        '<div id="%(field_id)s-stars" class="rating-stars"></div>'
        '<div class="rating-hint"></div>'
        '<div class="rating-value"></div>'
        '<div class="rating-distribution" style="display:none;"></div>'  # Added distribution container
        '<div class="rating-clear" style="display:none">Clear</div>'
        '<div class="rating-error"></div>'
        "</div>"
    )
    empty_template = data_template  # Inherit from data_template for empty state

    def __init__(self, **kwargs):
        """Initialize star rating widget with extended custom settings including shape, hints, and distribution."""
        super().__init__(**kwargs)
        self.placeholder = kwargs.get("placeholder", "")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.disabled = kwargs.get("disabled", False)
        self.max_stars = kwargs.get("max_stars", 5)
        # Aliases used internally by pre_validate / process_formdata
        self.number = self.max_stars
        self.min_rating = kwargs.get("min_rating", 0)
        self.step = kwargs.get("step", 0.5)
        self.enable_half = kwargs.get("enable_half", True)
        self.star_size = kwargs.get("star_size", 25)
        self.readonly = kwargs.get("readonly", False)
        self.required = kwargs.get("required", False)
        self.show_value = kwargs.get("show_value", True)
        self.show_clear = kwargs.get("show_clear", True)
        self.animate = kwargs.get("animate", True)
        self.star_color = kwargs.get("star_color", "#FFD700")
        self.star_empty_color = kwargs.get("star_empty_color", "#ccc")
        self.custom_shape = kwargs.get("custom_shape", None)
        self.hints = kwargs.get("hints", None)
        self.show_distribution = kwargs.get("show_distribution", False)

    def __call__(self, field, **kwargs):
        """Render the star rating widget with enhanced features like custom shapes, dynamic hints, and distribution."""
        kwargs.setdefault("type", "hidden")
        kwargs.setdefault("aria-label", field.label.text if field.label else "")
        if self.description:
            kwargs.setdefault("aria-describedby", f"{field.id}_help")
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.disabled:
            kwargs["disabled"] = True

        if self.required:
            kwargs["required"] = "required"
            kwargs["min"] = self.min_rating

        if self.readonly:
            kwargs["readonly"] = "readonly"

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
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
            /* Styles remain largely the same, adjust for distribution if needed */
            .star-rating-container { display: inline-block; position: relative; margin-bottom: 1em; }
            .rating-stars { font-size: %(star_size)spx; line-height: 1; cursor: pointer; }
            .rating-stars.readonly { cursor: default; }
            .rating-stars i { padding: 2px; }
            .rating-hint, .rating-value, .rating-clear { margin-top: 5px; font-size: 0.9em; color: #666; min-height: 20px; }
            .rating-clear { font-size: 0.8em; color: #999; cursor: pointer; }
            .rating-error { color: #dc3545; font-size: 0.8em; margin-top: 5px; display: none; }
            .rating-stars .star-on { color: {star_color}; }
            .rating-distribution { margin-top: 10px; font-size: 0.8em; color: #777; } /* Style for distribution area */


        </style>
        <script>
            (function() {
                var $container = $('#%(field_id)s').closest('.star-rating-container');
                var $stars = $('#%(field_id)s-stars');
                var $input = $('#%(field_id)s');
                var $hint = $container.find('.rating-hint');
                var $value = $container.find('.rating-value');
                var $distribution = $container.find('.rating-distribution'); // Distribution element
                var $clear = $container.find('.rating-clear');
                var $error = $container.find('.rating-error');
                var hints = %(hints)s; // Hints configuration passed from Python
                var currentRating = %(initial_rating)s;


                function initRating() {
                    $stars.raty({
                        score: currentRating,
                        number: %(max_stars)s,
                        half: {enable_half},
                        starOn: '{star_on}', // Default star icons remain, can be overridden
                        starOff: '{star_off}',
                        starHalf: '{star_half}',
                        hints: hints,
                        readOnly: {readonly},
                        round: { down: .26, full: .6, up: .76 },
                        step: {step},
                        click: function(score, evt) {
                            currentRating = score;
                            updateRating(score);
                        },
                        mouseover: function(score, evt) { if (!{readonly}) { showHint(score); } },
                        mouseout: function(score, evt) { if (!{readonly}) { showHint(currentRating); } }
                    });


                    showHint(currentRating); // Initial hint display
                    if ({allow_clear} && !{readonly}) { $clear.show(); }
                    if ({show_distribution}) { loadRatingDistribution(); } // Load distribution on init if enabled
                }


                function updateRating(score) {
                    if (score < {min_rating}) score = {min_rating};
                    $('#{field_id}').val(score).trigger('change');
                    showHint(score);
                    $clear.toggle(score > 0);
                    if ({show_distribution}) { updateRatingDistribution(score); } // Update distribution on rating change
                }


                function showHint(score) { // Dynamic hint display
                    var hintText = score && hints && hints[Math.ceil(score) - 1] ? hints[Math.ceil(score) - 1] : '';
                    $hint.text(hintText);
                }


                // Clear rating handler - remains the same
                $clear.find('button').on('click', function(e) {
                    e.preventDefault();
                    currentRating = {min_rating};
                    updateRating({min_rating});
                    $stars.raty('score', {min_rating});
                });


                // Rating distribution functions - new functionality for distribution display
                function loadRatingDistribution() {
                    // Placeholder for backend integration - replace with AJAX call to fetch distribution data
                    var distributionData = { 1: 5, 2: 10, 3: 25, 4: 30, 5: 50 }; // Example data
                    displayRatingDistribution(distributionData);
                }


                function updateRatingDistribution(score) {
                    // Placeholder for backend integration - replace with AJAX call to update and fetch distribution
                    loadRatingDistribution(); // Re-fetch and re-display distribution after rating
                }


                function displayRatingDistribution(data) {
                    $distribution.empty().show();
                    $distribution.append('<p><b>Rating Distribution:</b></p>');
                    var list = $('<ul></ul>').appendTo($distribution);
                    for (var star in data) {
                        $('<li></li>').text(star + ' Stars: ' + data[star] + ' votes').appendTo(list);
                    }
                }


                // Initialize widget - remains the same
                initRating();


                // Form reset handler - remains the same
                $container.closest('form').on('reset', function() {
                    setTimeout(function() {
                        currentRating = {min_rating};
                        updateRating({min_rating});
                        $stars.raty('score', {min_rating});
                    }, 0);
                });
            })();
        </script>
        """.format(
                field_id=field.id,
                initial_rating=float(field.data or 0),
                star_size=self.star_size,
                max_stars=self.max_stars,
                min_rating=self.min_rating,
                star_color=self.star_color,
                star_empty_color=self.star_empty_color,
                readonly=str(self.readonly).lower(),
                required=str(self.required).lower(),
                use_full_stars=str(self.step == 1).lower(),
                step=self.step,
                custom_shape=f"'{self.custom_shape}'"
                if self.custom_shape
                else "null",  # Pass custom shape config
                animation_speed=0 if not self.animate else 100,
                show_value=str(self.show_value).lower(),
                show_clear=str(self.show_clear).lower(),
                hints=json.dumps(self.hints)
                if self.hints
                else "null",  # Pass hints config
                show_distribution=str(
                    self.show_distribution
                ).lower(),  # Pass distribution config
            )
        )

    def pre_validate(self, form):
        """Enhanced validation with min/max and step validation"""
        if self.data is not None:
            if self.data < self.min_rating:
                raise ValidationError(f"Rating cannot be less than {self.min_rating}")
            if self.data > self.number:
                raise ValidationError(f"Rating cannot exceed {self.number} stars")
            if self.enable_half:
                if not isinstance(self.data, float) and not isinstance(self.data, int):
                    raise ValidationError("Rating must be a number")
                if (
                    self.data * 2
                ) % 1 != 0:  # Check for valid half-star value when enabled
                    raise ValidationError("Invalid half-star rating value")
            elif not isinstance(self.data, int):
                raise ValidationError(
                    "Rating must be a whole number"
                )  # Enforce whole numbers when half-stars are disabled

    def process_formdata(self, valuelist):
        """Process form data to database format, handles potential ValueError"""  # Enhanced error handling
        if valuelist:
            try:
                self.data = float(valuelist[0])
                if self.data < self.min_rating:
                    self.data = self.min_rating
                elif self.data > self.number:
                    self.data = self.number
            except ValueError:
                self.data = None
                raise ValidationError(
                    "Invalid rating, please enter a valid number"
                )  # More user-friendly error message
        else:
            self.data = None
