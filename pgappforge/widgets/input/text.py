"""PasswordStrengthWidget — PgAppForge widget(s)."""

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

class PasswordStrengthWidget(BS3TextFieldWidget):
    """
    Advanced password strength meter widget for PgAppForge.

    Features:
    - Real-time strength assessment
    - Multiple validation criteria (length, special chars, numbers, case)
    - Visual feedback with Bootstrap styling
    - Configurable password requirements
    - Password generator/suggestion feature
    - Breach checking via HaveIBeenPwned API
    - Custom validation messages
    - Password complexity score display
    - Integration with password managers (basic)
    - Accessibility support (ARIA attributes, contrast)

    Database Type:
        PostgreSQL: varchar(255) ENCRYPTED
        SQLAlchemy: String(255)

    Example Usage:
        password = db.Column(db.String(255), nullable=False,
                           info={'widget': PasswordStrengthWidget(
                               min_length=12,
                               require_special=True,
                               check_breaches=True,
                               error_messages={'length': 'Password too short'} # Custom error message
                           )})
    """

    data_template = (
        '<div class="password-strength-wrapper %(wrapper_class)s">'
        '<div class="input-group">'
        "<input %(password)s>"
        '<div class="input-group-append">'
        '<button type="button" class="btn btn-outline-secondary toggle-password" title="Show/Hide Password">'
        '<i class="fa fa-eye"></i>'
        "</button>"
        '<button type="button" class="btn btn-outline-secondary generate-password" title="Generate Strong Password">'
        '<i class="fa fa-key"></i>'
        "</button>"
        "</div>"
        "</div>"
        '<div class="password-strength-meter mt-2" aria-live="polite" aria-atomic="true">'  # Added ARIA live region
        '<div class="progress">'
        '<div id="%(field_id)s-meter" class="progress-bar" role="progressbar"></div>'
        "</div>"
        '<div id="%(field_id)s-strength" class="password-strength-text mt-1"></div>'
        '<div id="%(field_id)s-suggestions" class="password-suggestions mt-1 small"></div>'
        '<div id="%(field_id)s-breach" class="password-breach mt-1 small text-danger"></div>'
        "</div>"
        "</div>"
    )

    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.1.1/crypto-js.min.js"  # Added CryptoJS CDN
    ]

    def __init__(self, **kwargs):
        """Initialize password widget with extensive configuration"""
        super().__init__(**kwargs)
        self.placeholder = kwargs.get("placeholder", "")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)
        self.min_length = kwargs.get("min_length", 8)
        self.max_length = kwargs.get("max_length", 100)
        self.require_special = kwargs.get("require_special", True)
        self.require_numbers = kwargs.get("require_numbers", True)
        self.require_uppercase = kwargs.get("require_uppercase", True)
        self.require_lowercase = kwargs.get("require_lowercase", True)
        self.check_breaches = kwargs.get("check_breaches", False)
        self.show_suggestions = kwargs.get("show_suggestions", True)
        self.custom_validators = kwargs.get("custom_validators", [])
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.strength_texts = kwargs.get(
            "strength_texts",
            {
                0: _("Too Weak"),
                1: _("Weak"),
                2: _("Medium"),
                3: _("Strong"),
                4: _("Very Strong"),
            },  # Using Flask-Babel's lazy_gettext
        )
        self.strength_colors = kwargs.get(
            "strength_colors",
            {
                0: "#dc3545",  # red
                1: "#ffc107",  # yellow
                2: "#fd7e14",  # orange
                3: "#28a745",  # green
                4: "#20c997",  # teal
            },
        )
        self.error_messages = kwargs.get(
            "error_messages",
            {  # Customizable error messages
                "length": _(
                    "Password must be at least %(min_length)s characters long."
                ),
                "special": _("Password must contain special characters."),
                "numbers": _("Password must contain numbers."),
                "uppercase": _("Password must contain uppercase letters."),
                "lowercase": _("Password must contain lowercase letters."),
                "breach": _(
                    "This password has been exposed in data breaches, please choose a different one."
                ),
            },
        )

    def __call__(self, field, **kwargs):
        """Render the password strength widget"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", "password")
        kwargs.setdefault("class", "form-control" + (" is-invalid" if field.errors else ""))
        kwargs.setdefault("autocomplete", "new-password")
        kwargs.setdefault("minlength", self.min_length)
        kwargs.setdefault("maxlength", self.max_length)
        kwargs.setdefault(
            "aria-describedby",
            f"{field.id}-strength {field.id}-suggestions {field.id}-breach",
        )
        kwargs.setdefault("aria-label", field.label.text if field.label else "")
        if field.errors:
            kwargs["aria-invalid"] = "true"
        if self.placeholder:
            kwargs.setdefault("placeholder", self.placeholder)
        if self.readonly:
            kwargs["readonly"] = True
        if self.disabled:
            kwargs["disabled"] = True

        if field.flags.required:
            kwargs["required"] = True

        html = self.data_template % {
            "password": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        # Append server-side error feedback
        if field.errors:
            error_html = (
                f'<div class="invalid-feedback" id="{escape(field.id)}_error">'
                + "".join(f"<span>{escape(e)}</span>" for e in field.errors)
                + "</div>"
            )
            html += error_html

        # Append help text
        if self.description:
            html += (
                f'<small class="form-text text-muted" id="{escape(field.id)}_help">'
                f"{escape(self.description)}</small>"
            )

        return Markup(
            html
            + """
        <style>
            .password-strength-wrapper { margin-bottom: 1.5rem; }
            .password-strength-meter .progress { height: 5px; }
            .password-strength-text { font-size: 0.875rem; }
            .password-suggestions { color: #6c757d; }
            .show-password .fa-eye { color: #007bff; }
            @keyframes shake {
                0%, 100% { transform: translateX(0); }
                25% { transform: translateX(-5px); }
                75% { transform: translateX(5px); }
            }
            .password-error { animation: shake 0.2s ease-in-out 0s 2; }
            .generate-password-btn { cursor: pointer; } /* Style for password generate button */
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.1.1/crypto-js.min.js"></script> <!-- Ensure CryptoJS is included -->
        <script>
            (function() {
                var $input = $('#{field_id}');
                var $wrapper = $input.closest('.password-strength-wrapper');
                var $meter = $wrapper.find('#{field_id}-meter');
                var $strength = $wrapper.find('#{field_id}-strength');
                var $suggestions = $wrapper.find('#{field_id}-suggestions');
                var $breach = $wrapper.find('#{field_id}-breach');
                var $toggle = $wrapper.find('.toggle-password');
                var $generateBtn = $wrapper.find('.generate-password'); // Button for password generation
                var requirements = {requirements};
                var strengthTexts = {strength_texts};
                var strengthColors = {strength_colors};
                var errorMessages = {error_messages}; // Use error messages from widget config
                var breachTimeout;


                function calculateStrength(password) {{ // Strength calculation function
                    if (!password) return 0;


                    var strength = 0;
                    var suggestions = [];


                    if (password.length >= requirements.min_length) { strength += 1; }
                    else { suggestions.push(errorMessages.length.replace('%(min_length)s', requirements.min_length)); } // Use errorMessages


                    if (requirements.require_lowercase && password.match(/[a-z]+/)) { strength += 1; }
                    else if (requirements.require_lowercase) { suggestions.push(errorMessages.lowercase); }


                    if (requirements.require_uppercase && password.match(/[A-Z]+/)) { strength += 1; }
                    else if (requirements.require_uppercase) { suggestions.push(errorMessages.uppercase); }


                    if (requirements.require_numbers && password.match(/[0-9]+/)) { strength += 1; }
                    else if (requirements.require_numbers) { suggestions.push(errorMessages.numbers); }


                    if (requirements.require_special && password.match(/[^A-Za-z0-9]+/)) { strength += 1; }
                    else if (requirements.require_special) { suggestions.push(errorMessages.special); }


                    var score = Math.min(4, Math.floor((strength / 5) * 4));
                    $meter.css({{ 'width': ((score + 1) * 20) + '%', 'background-color': strengthColors[score] }});
                    $strength.text(strengthTexts[score]).css('color', strengthColors[score]);


                    if ({show_suggestions}) { $suggestions.html(suggestions.length ? suggestions.map(s => '<div>• ' + s + '</div>').join('') : ''); }
                    return score;
                }


                function checkBreaches(password) {{ // Breach check function
                    if (!{check_breaches} || !password) return;


                    clearTimeout(breachTimeout);
                    breachTimeout = setTimeout(function() {{
                        var sha1 = CryptoJS.SHA1(password).toString().toUpperCase();
                        var prefix = sha1.substring(0, 5);
                        var suffix = sha1.substring(5);


                        $.ajax({{
                            url: 'https://api.pwnedpasswords.com/range/' + prefix,
                            method: 'GET',
                            success: function(data) {{
                                var matches = data.split('\\n');
                                var found = matches.find(m => m.split(':')[0] === suffix);
                                if (found) {{
                                    var count = found.split(':')[1];
                                    $breach.text(errorMessages.breach).show(); // Use breach error message
                                }} else {{
                                    $breach.hide();
                                }}
                            }}
                        }});
                    }}, 500);
                }}


                function generatePassword(length = requirements.min_length) {{ // Password generation function
                    const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_+~`|}{[]\\:;?><,./-=";
                    let password = "";
                    for (let i = 0; i < length; i++) {{
                        const randomIndex = Math.floor(Math.random() * charset.length);
                        password += charset.charAt(randomIndex);
                    }}
                    return password;
                }}


                // Handlers - Input, Toggle, Generate, Form Submit
                $input.on('input', function() { // Input handler
                    var password = $(this).val();
                    calculateStrength(password);
                    checkBreaches(password);
                });


                $toggle.on('click', function() { // Toggle password visibility
                    var type = $input.attr('type') === 'password' ? 'text' : 'password';
                    $input.attr('type', type);
                    $(this).find('i').toggleClass('fa-eye fa-eye-slash');
                });


                $generateBtn.on('click', function(e) {{ // Generate password button handler
                    e.preventDefault();
                    const generatedPassword = generatePassword();
                    $input.val(generatedPassword).trigger('input'); // Set generated password and trigger strength check
                }});


                $input.closest('form').on('submit', function(e) { // Form submit handler
                    var password = $input.val();
                    var strength = calculateStrength(password);


                    if (password && strength < 2) {{
                        e.preventDefault();
                        $wrapper.addClass('password-error');
                        $('.json-editor-error').text('Password is too weak').show(); // Generic error display for password
                        setTimeout(function() { $wrapper.removeClass('password-error'); }, 500);
                        return false;
                    }}
                });
            }})();
        </script>
        """.format(
                field_id=field.id,
                requirements=json.dumps(
                    {
                        "min_length": self.min_length,
                        "require_special": self.require_special,
                        "require_numbers": self.require_numbers,
                        "require_uppercase": self.require_uppercase,
                        "require_lowercase": self.require_lowercase,
                    }
                ),
                min_length=self.min_length,
                require_special=str(self.require_special).lower(),
                require_numbers=str(self.require_numbers).lower(),
                require_uppercase=str(self.require_uppercase).lower(),
                require_lowercase=str(self.require_lowercase).lower(),
                check_breaches=str(self.check_breaches).lower(),
                show_suggestions=str(self.show_suggestions).lower(),
                strength_texts=json.dumps(self.strength_texts),
                strength_colors=json.dumps(self.strength_colors),
                error_messages=json.dumps(
                    self.error_messages, ensure_ascii=False
                ),  # Pass error messages to JS, ensure non-ascii chars are handled
            )
        )

    def process_formdata(self, valuelist):
        """Process form data with validation"""  # Remains same
        if valuelist:
            self.data = valuelist[0]
            if len(self.data) < self.min_length:
                raise ValueError(
                    f"Password must be at least {self.min_length} characters"
                )
            if len(self.data) > self.max_length:
                raise ValueError(
                    f"Password must be at most {self.max_length} characters"
                )
            if self.require_lowercase and not re.search(r"[a-z]", self.data):
                raise ValueError("Password must contain lowercase letters")
            if self.require_uppercase and not re.search(r"[A-Z]", self.data):
                raise ValueError("Password must contain uppercase letters")
            if self.require_numbers and not re.search(r"\d", self.data):
                raise ValueError("Password must contain numbers")
            if self.require_special and not re.search(r"[^A-Za-z0-9]", self.data):
                raise ValueError("Password must contain special characters")
        else:
            self.data = None

    def pre_validate(self, form):
        """Validate password before form processing"""  # Remains same
        if form.flags.required and not self.data:
            raise ValueError("Password is required")

        # Run custom validators if any
        for validator in self.custom_validators:
            validator(self.data)
