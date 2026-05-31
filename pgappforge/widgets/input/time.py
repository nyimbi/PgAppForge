"""TimeField, TimePickerWidget — PgAppForge widget(s)."""

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

class TimeField(Field):
    """
    A custom field for entering time.

    This field will accept input in various formats:
    - HH:MM
    - HH:MM:SS
    - HH:MM AM/PM
    - HH:MM:SS AM/PM

    It will store and return time as a Python time object.
    """

    widget = TextInput()

    def __init__(
        self,
        label=None,
        validators=None,
        format="%H:%M:%S",
        min_time=None,
        max_time=None,
        **kwargs,
    ):
        super(TimeField, self).__init__(label, validators, **kwargs)
        self.format = format
        self.min_time = min_time
        self.max_time = max_time

    def _value(self):
        if self.raw_data:
            return " ".join(self.raw_data)
        elif self.data is not None:
            return self.data.strftime(self.format)
        else:
            return ""

    def process_formdata(self, valuelist):
        if valuelist:
            time_str = " ".join(valuelist)
            try:
                self.data = self.parse_time(time_str)
            except ValueError as e:
                self.data = None
                raise ValidationError(str(e))
        else:
            self.data = None

    @staticmethod
    def parse_time(time_str):
        """Parse the time string into a time object."""
        time_str = time_str.lower().strip()

        # Try parsing with various formats
        formats = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p", "%H%M", "%H%M%S"]

        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt).time()
            except ValueError:
                pass

        # If no format matches, try a more flexible approach
        match = re.match(r"(\d{1,2}):?(\d{2})(:?(\d{2}))?\s*(am|pm)?", time_str)
        if match:
            hours, minutes, _, seconds, period = match.groups()
            hours = int(hours)
            minutes = int(minutes)
            seconds = int(seconds) if seconds else 0

            if period:
                if hours == 12:
                    hours = 0
                if period == "pm":
                    hours += 12

            if 0 <= hours <= 23 and 0 <= minutes <= 59 and 0 <= seconds <= 59:
                return time(hours, minutes, seconds)

        raise ValueError(
            _("Invalid time format. Please use HH:MM, HH:MM:SS, or HH:MM AM/PM.")
        )

    def pre_validate(self, form):
        if self.data is None:
            raise ValidationError(_("Not a valid time value"))
        if self.min_time and self.data < self.min_time:
            raise ValidationError(
                _(f"Time must be after {self.min_time.strftime('%H:%M:%S')}")
            )
        if self.max_time and self.data > self.max_time:
            raise ValidationError(
                _(f"Time must be before {self.max_time.strftime('%H:%M:%S')}")
            )

    def isoformat(self):
        """Return the time in ISO 8601 format."""
        if self.data:
            return self.data.isoformat()
        return None

    def to_12_hour(self):
        """Return the time in 12-hour format."""
        if self.data:
            return self.data.strftime("%I:%M:%S %p")
        return None

    def to_24_hour(self):
        """Return the time in 24-hour format."""
        if self.data:
            return self.data.strftime("%H:%M:%S")
        return None


class TimePickerWidget(BS3TextFieldWidget):
    """
    Advanced time picker widget for PgAppForge forms.
    Handles time input with support for multiple formats and validation.

    Database Type:
        PostgreSQL: TIME or TIMETZ
        SQLAlchemy: Time() or DateTime()

    Features:
    - 12/24 hour format support
    - Seconds precision
    - Minute/second step intervals
    - Time range validation
    - Keyboard navigation (WCAG compliant)
    - Clear button (WCAG compliant)
    - Custom time formats
    - Timezone support
    - Option to integrate with DatePicker for DateTime input
    """

    data_template = (
        '<div class="input-group time-picker-widget">'
        "<input %(text)s>"
        '<span class="input-group-addon"><i class="fa fa-clock-o" aria-hidden="true"></i></span>'
        '<span class="input-group-btn">'
        '<button class="btn btn-default clear-time" type="button" aria-label="Clear time">'
        '<i class="fa fa-times" aria-hidden="true"></i>'
        "</button>"
        "</span>"
        "</div>"
        '<div class="time-error" role="alert"></div>'
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """Initialize time picker with custom settings"""
        super().__init__(**kwargs)
        self.format_24hr = kwargs.get("format_24hr", True)
        self.show_seconds = kwargs.get("show_seconds", True)
        self.minute_step = kwargs.get("minute_step", 1)
        self.second_step = kwargs.get("second_step", 1)
        self.min_time = kwargs.get("min_time", None)
        self.max_time = kwargs.get("max_time", None)
        self.default_time = kwargs.get("default_time", None)
        self.show_meridian = not self.format_24hr
        self.timezone = kwargs.get("timezone", None)
        self.integrate_date_picker = kwargs.get(
            "integrate_date_picker", False
        )  # Option to integrate datepicker

    def __call__(self, field, **kwargs):
        """Render the time picker widget"""
        kwargs.setdefault("type", "text")
        kwargs.setdefault("data-role", "timepicker")
        kwargs.setdefault("autocomplete", "off")
        kwargs.setdefault("data-template", "dropdown")
        kwargs.setdefault("data-show-seconds", str(self.show_seconds).lower())
        kwargs.setdefault(
            "data-default-time",
            str(self.default_time).lower() if self.default_time else "false",
        )
        kwargs.setdefault("data-show-meridian", str(self.show_meridian).lower())
        kwargs.setdefault("data-minute-step", self.minute_step)
        kwargs.setdefault("data-second-step", self.second_step)
        kwargs["aria-describedby"] = (
            f"{field.id}-error"  # WCAG association for error message
        )
        kwargs["aria-live"] = "assertive"  # WCAG live region for error announcement

        if field.flags.required:
            kwargs["required"] = True
            kwargs["aria-required"] = "true"  # WCAG required attribute

        template = self.data_template if field.data else self.empty_template
        html = template % {"text": self.html_params(name=field.name, **kwargs)}

        return Markup(
            html
            + """
        <style>
            .time-picker-widget .bootstrap-timepicker-widget table td input {
                width: 40px;
                padding: 4px;
                border: 1px solid #ccc;
                border-radius: 4px;
            }
            .time-error {
                color: #a94442;
                margin-top: 5px;
                font-size: 12px;
            }
        </style>
        <div id="%(field_id)s-error" class="time-error" role="alert" aria-live="assertive"></div>
        <script>
            $(document).ready(function() {
                var $input = $('#%(field_id)s');
                var $widget = $input.closest('.time-picker-widget');
                var $error = $('#%(field_id)s-error');


                // Initialize timepicker
                $input.timepicker({
                    template: 'dropdown',
                    showSeconds: %(show_seconds)s,
                    showMeridian: %(show_meridian)s,
                    defaultTime: %(default_time)s,
                    minuteStep: %(minute_step)d,
                    secondStep: %(second_step)d,
                    showInputs: true,
                    disableFocus: false, // WCAG: focus management
                    modalBackdrop: true,
                    keyboardNavigation: true // WCAG: keyboard access
                });

                // Time validation function
                function validateTime(timeStr) {
                    if (!timeStr) return true;


                    try {
                        var parsedTime = $input.timepicker('getTime'); // Get Date object
                        if (!parsedTime) {
                            $error.text('Invalid time format');
                            return false;
                        }

                        // Validate min time
                        %(min_time_check)s

                        // Validate max time
                        %(max_time_check)s


                        $error.text('');
                        return true;


                    } catch (e) {
                        $error.text('Invalid time format');
                        return false;
                    }
                }

                // Handle changes
                $input.on('changeTime.timepicker', function(e) {
                    validateTime($input.val());
                });

                // Clear button handler
                $widget.find('.clear-time').click(function() {
                    $input.timepicker('setTime', null);
                    $input.val('');
                    $error.text('');
                });

                // Initialize with existing value
                if ($input.val()) {
                    validateTime($input.val());
                }
            });
        </script>
        """
            % {
                "field_id": field.id,
                "show_seconds": str(self.show_seconds).lower(),
                "show_meridian": str(self.show_meridian).lower(),
                "default_time": (
                    f"'{self.default_time}'" if self.default_time else "false"
                ),
                "minute_step": self.minute_step,
                "second_step": self.second_step,
                "min_time_check": (
                    f"""
                var minTime = new Date('1970/01/01 {self.min_time}');
                if (parsedTime < minTime) {{
                    $error.text('Time must be after {self.min_time}');
                    return false;
                }}
            """
                    if self.min_time
                    else ""
                ),
                "max_time_check": (
                    f"""
                var maxTime = new Date('1970/01/01 {self.max_time}');
                if (parsedTime > maxTime) {{
                    $error.text('Time must be before {self.max_time}');
                    return false;
                }}
            """
                    if self.max_time
                    else ""
                ),
            }
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                time_str = valuelist[0]
                parsed_time = CustomTimeField.parse_time(
                    time_str
                )  # Use CustomTimeField for parsing
                if self.timezone:
                    # Timezone handling - store in UTC
                    utc_timezone = pytz.utc
                    local_timezone = pytz.timezone(self.timezone)
                    combined_datetime = datetime.combine(
                        datetime.today(), parsed_time
                    )  # Combine with today's date for datetime object
                    local_datetime = local_timezone.localize(combined_datetime)
                    utc_datetime = local_datetime.astimezone(utc_timezone)
                    return utc_datetime.time()  # Store time in UTC
                return parsed_time
            except ValueError as e:
                raise ValueError(_("Invalid time format: ") + str(e))
        return None

    def process_data(self, value):
        """Process data from database format"""
        if value:
            if isinstance(value, str):
                return value  # Assume already formatted string
            if self.timezone and isinstance(value, time):
                # Convert UTC time to local timezone for display
                utc_timezone = pytz.utc
                local_timezone = pytz.timezone(self.timezone)
                combined_datetime = datetime.combine(datetime.today(), value).replace(
                    tzinfo=utc_timezone
                )  # Combine with today's date
                local_datetime = combined_datetime.astimezone(local_timezone)
                return local_datetime.strftime(
                    "%H:%M:%S"
                )  # Format for display in local time
            return value.strftime("%H:%M:%S")  # Format time object to string
        return None
