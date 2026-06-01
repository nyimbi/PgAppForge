"""PhoneNumberWidget — PgAppForge widget(s)."""

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

class PhoneNumberWidget(BS3TextFieldWidget):
    """
    Advanced phone number input widget with international format support.

    Features:
    - International phone number validation
    - Country code selection
    - Format validation and normalization
    - Extension support
    - Custom validation rules
    - Multiple display formats
    - Copy/paste handling
    - Accessibility support

    Database Type:
        PostgreSQL: varchar(32) or text
        SQLAlchemy: String(32) or Text

    Example Usage:
        phone = db.Column(db.String(32), nullable=True)
    """

    data_template = (
        '<div class="phone-input-container">'
        "<input %(text)s>"
        '<div class="phone-error"></div>'
        '<div class="phone-info"></div>'
        "</div>"
    )
    empty_template = (
        '<div class="phone-input-container">'
        "<input %(text)s>"
        '<div class="phone-error"></div>'
        '<div class="phone-info"></div>'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize phone widget with custom settings"""
        super().__init__(**kwargs)
        self.placeholder = kwargs.get("placeholder", "Enter phone number")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)
        self.default_country = kwargs.get("default_country", "US")
        self.preferred_countries = kwargs.get("preferred_countries", ["US", "GB", "CA"])
        self.allow_extensions = kwargs.get("allow_extensions", True)
        self.auto_format = kwargs.get("auto_format", True)
        self.national_mode = kwargs.get("national_mode", False)
        self.mobile_only = kwargs.get("mobile_only", False)
        self.error_message = kwargs.get("error_message", "Invalid phone number")
        self.custom_error_messages = kwargs.get("error_messages", {})

    def __call__(self, field, **kwargs):
        """Render the phone input widget"""
        kwargs.setdefault("type", "tel")
        kwargs.setdefault("class", "form-control phone-input" + (" is-invalid" if field.errors else ""))
        kwargs.setdefault("placeholder", self.placeholder)
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

        template = self.data_template if field.data else self.empty_template
        html = template % {"text": self.html_params(name=field.name, **kwargs)}

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
            .phone-input-container {
                position: relative;
                margin-bottom: 15px;
            }
            .phone-error {
                color: #a94442;
                font-size: 12px;
                margin-top: 5px;
                display: none;
            }
            .phone-info {
                color: #666;
                font-size: 12px;
                margin-top: 5px;
            }
            .iti {
                width: 100%;
            }
        </style>
        <script>
            (function() {
                var $input = $('#{field_id}');
                var $container = $input.closest('.phone-input-container');
                var $error = $container.find('.phone-error');
                var $info = $container.find('.phone-info');

                var iti = window.intlTelInput($input[0], {{
                    initialCountry: '{default_country}',
                    preferredCountries: {preferred_countries},
                    separateDialCode: true,
                    nationalMode: {national_mode},
                    autoPlaceholder: 'aggressive',
                    formatOnDisplay: {auto_format},
                    allowExtensions: {allow_extensions},
                    customPlaceholder: function(selectedCountryPlaceholder, selectedCountryData) {{
                        return '{placeholder}';
                    }},
                    utilsScript: "https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.8/js/utils.js"
                }});

                // Set initial value if exists
                if ($input.val()) {{
                    iti.setNumber($input.val());
                }}

                // Validation and formatting
                function validateNumber() {
                    var error_messages = {error_messages}; // Error messages from python widget

                    if ($input.val().trim()) {
                        if (iti.isValidNumber()) {
                            var numberType = iti.getNumberType();
                            var numberTypeString = intlTelInputUtils.getNumberType(numberType); // Get number type string
                            var numberTypeFormatted = numberTypeString.replace(/_/g, ' ').toLowerCase(); // Format for display
                            $info.text('Type: ' + numberTypeFormatted); // Display number type

                            if ({mobile_only} && numberType !== intlTelInputUtils.numberType.MOBILE) {
                                $error.text(error_messages['mobile_only'] || 'Mobile number required').show();
                                $input.addClass('error');
                                return false;
                            }

                            $error.hide();
                            $input.removeClass('error');

                            var formatInfo = 'Format: ' + iti.getNumber(intlTelInputUtils.numberFormat.INTERNATIONAL);
                            $info.text(formatInfo);


                            $input.val(iti.getNumber(intlTelInputUtils.numberFormat.E164)); // Save number in E164 for database
                            return true;
                        } else {
                            var errorCode = iti.getValidationError();
                            var errorMsg = error_messages[errorCode] || '{error_message}';
                            $error.text(errorMsg).show();
                            $input.addClass('error');
                            return false;
                        }
                    }
                    return true;
                }

                // Event handlers
                $input.on('blur', validateNumber);
                $input.on('change', validateNumber);
                $input.on('countrychange', function() {
                    validateNumber();
                });

                // Form submission handling
                $input.closest('form').on('submit', function(e) {
                    if (!validateNumber()) {
                        e.preventDefault();
                        $input.focus();
                    }
                });

                // Paste event handling
                $input.on('paste', function(e) {
                    setTimeout(validateNumber, 0); // Validate after paste
                });

                // Keypress handling for allowed characters
                $input.on('keypress', function(e) {
                    var allowedChars = /[0-9\\+\\-\\(\\)\\s]/;
                    var char = String.fromCharCode(e.which);
                    if (!allowedChars.test(char)) {
                        e.preventDefault();
                    }
                });
            }})();
        </script>
        """.format(
                field_id=field.id,
                default_country=self.default_country,
                preferred_countries=json.dumps(self.preferred_countries),
                national_mode=str(self.national_mode).lower(),
                auto_format=str(self.auto_format).lower(),
                allow_extensions=str(self.allow_extensions).lower(),
                mobile_only=str(self.mobile_only).lower(),
                placeholder=self.placeholder,
                error_message=self.error_message,
                error_messages=json.dumps(
                    {
                        "IS_POSSIBLE": self.custom_error_messages.get(
                            "IS_POSSIBLE", "Invalid number format"
                        ),
                        "INVALID_COUNTRY_CODE": self.custom_error_messages.get(
                            "INVALID_COUNTRY_CODE", "Invalid country code"
                        ),
                        "TOO_SHORT": self.custom_error_messages.get(
                            "TOO_SHORT", "Number too short"
                        ),
                        "TOO_LONG": self.custom_error_messages.get(
                            "TOO_LONG", "Number too long"
                        ),
                        "IS_POSSIBLE_LOCAL_ONLY": self.custom_error_messages.get(
                            "IS_POSSIBLE_LOCAL_ONLY", "Number is only valid locally"
                        ),
                        "mobile_only": self.custom_error_messages.get(
                            "mobile_only", "Mobile number required"
                        ),
                    }
                ),
            )
        )

    def pre_validate(self, form):
        """Validate phone number before form processing"""
        if self.data:
            try:
                import phonenumbers

                number = phonenumbers.parse(self.data)
                if not phonenumbers.is_valid_number(number):
                    raise ValidationError(self.error_message)

                if (
                    self.mobile_only
                    and phonenumbers.number_type(number)
                    != phonenumbers.PhoneNumberType.MOBILE
                ):
                    raise ValidationError("Mobile number required")

            except ValidationError as e:
                raise e
            except Exception as e:
                raise ValidationError(self.error_message)

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                import phonenumbers

                number = phonenumbers.parse(
                    valuelist[0], region=self.default_country
                )  # Parse with default country for better accuracy
                if not phonenumbers.is_valid_number(number):
                    self.data = None
                    raise ValueError(
                        self.error_message
                    )  # Raise exception if invalid on server side too for consistency
                self.data = phonenumbers.format_number(
                    number, phonenumbers.PhoneNumberFormat.E164
                )  # Format to E164 for storage
            except ValueError as e:
                self.data = None
                raise ValidationError(
                    "Invalid phone number: " + str(e)
                )  # Raise ValidationError for form errors
        else:
            self.data = None

    def process_data(self, value):
        """Process data from database format for display"""
        if value:
            try:
                import phonenumbers

                number = phonenumbers.parse(value)
                return phonenumbers.format_number(
                    number, phonenumbers.PhoneNumberFormat.INTERNATIONAL
                )  # Format for display
            except Exception:
                return value
        return None
