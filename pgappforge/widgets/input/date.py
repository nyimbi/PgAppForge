"""DateRangePickerWidget — PgAppForge widget(s)."""

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

class DateRangePickerWidget(BS3TextFieldWidget):
    """
    Advanced date range picker widget supporting multiple date formats and ranges.

    Features:
    - Preset date ranges, including customizable and fiscal year ranges
    - Custom date format support
    - Min/max date constraints, and disabling specific dates/ranges
    - Single date or range selection
    - Time picker integration with customizable formats (12/24 hour)
    - Localization support
    - Custom styling via CSS classes
    - Range validation with server-side checks
    - Mobile-friendly and accessibility support

    Database Type:
        PostgreSQL: tstzrange
        SQLAlchemy: TypeDecorator with Range(DateTime)

    Example Usage:
        date_range = db.Column(
            TSRangeType,
            nullable=True,
            info={'widget': DateRangePickerWidget(format='%Y/%m/%d',
                                                    default_ranges={'Custom Range': ['moment().subtract(1, "week")', 'moment()']},
                                                    fiscal_year_ranges=True,
                                                    disabled_dates=['2024-12-25'],
                                                    theme_classes='picker-custom-style')}
        )
    """

    data_template = (
        '<div class="input-group date-range-picker-widget">'
        "<input %(text)s>"
        '<span class="input-group-addon"><i class="fa fa-calendar"></i></span>'
        "</div>"
        '<div class="date-range-error"></div>'
        '<div class="date-range-preview"></div>'
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """Initialize date range picker with extended settings including fiscal year, disabled dates, and theming"""
        super().__init__(**kwargs)
        self.format = kwargs.get("format", "YYYY-MM-DD")
        self.separator = kwargs.get("separator", " - ")
        self.min_date = kwargs.get("min_date", None)
        self.max_date = kwargs.get("max_date", None)
        self.show_dropdowns = kwargs.get("show_dropdowns", True)
        self.show_week_numbers = kwargs.get("show_week_numbers", False)
        self.show_iso_weeks = kwargs.get("show_iso_weeks", False)
        self.time_picker = kwargs.get("time_picker", False)
        self.time_picker_24hour = kwargs.get("time_picker_24hour", True)
        self.time_picker_seconds = kwargs.get("time_picker_seconds", False)
        self.time_picker_increment = kwargs.get("time_picker_increment", 15)
        self.locale = kwargs.get("locale", "en")
        self.auto_apply = kwargs.get("auto_apply", True)
        self.linked_calendars = kwargs.get("linked_calendars", True)
        self.show_custom_range_label = kwargs.get("show_custom_range_label", True)
        self.always_show_calendars = kwargs.get("always_show_calendars", True)
        self.opens = kwargs.get("opens", "right")
        self.drops = kwargs.get("drops", "down")
        self.button_classes = kwargs.get("button_classes", "btn btn-sm")
        self.apply_button_classes = kwargs.get("apply_button_classes", "btn-primary")
        self.cancel_button_classes = kwargs.get("cancel_button_classes", "btn-default")
        self.default_ranges = kwargs.get(
            "default_ranges",
            {
                "Today": ["moment()", "moment()"],
                "Yesterday": [
                    'moment().subtract(1, "days")',
                    'moment().subtract(1, "days")',
                ],
                "Last 7 Days": ['moment().subtract(6, "days")', "moment()"],
                "Last 30 Days": ['moment().subtract(29, "days")', "moment()"],
                "This Month": ['moment().startOf("month")', 'moment().endOf("month")'],
                "Last Month": [
                    'moment().subtract(1, "month").startOf("month")',
                    'moment().subtract(1, "month").endOf("month")',
                ],
            },
        )
        self.fiscal_year_ranges = kwargs.get(
            "fiscal_year_ranges", False
        )  # Enable fiscal year ranges
        self.disabled_dates = kwargs.get("disabled_dates", [])  # List of disabled dates
        self.disabled_ranges = kwargs.get(
            "disabled_ranges", []
        )  # List of disabled date ranges
        self.theme_classes = kwargs.get("theme_classes", "")  # Custom CSS theme classes

    def __call__(self, field, **kwargs):
        kwargs.setdefault("type", "text")
        kwargs.setdefault("class", "form-control")
        kwargs.setdefault("data-format", self.format)
        kwargs.setdefault("data-separator", self.separator)

        if self.theme_classes:  # Add custom theme classes
            kwargs.setdefault(
                "class", kwargs.get("class", "") + " " + self.theme_classes
            )

        template = self.data_template if field.data else self.empty_template
        html = template % {"text": self.html_params(name=field.name, **kwargs)}

        # Prepare ranges including fiscal year ranges if enabled
        ranges = self.default_ranges.copy()
        if self.fiscal_year_ranges:
            ranges.update(
                {
                    "Fiscal Year to Date": [
                        f'moment().startOf("fiscalYear").fiscalStart()',
                        "moment()",
                    ],
                    "Last Fiscal Year": [
                        f'moment().subtract(1, "fiscalYear").startOf("fiscalYear").fiscalStart()',
                        f'moment().subtract(1, "fiscalYear").fiscalEndOf("fiscalYear").fiscalEnd()',
                    ],
                }
            )

        return Markup(
            html
            + """
        <script>
            $(function() {{
                var ranges = %(ranges)s; // Ranges from Python config, includes fiscal year
                var drp = $('#{field_id}').daterangepicker({{
                    startDate: moment().subtract(29, 'days'),
                    endDate: moment(),
                    format: '%(format)s',
                    separator: '%(separator)s',
                    minDate: %(min_date)s,
                    maxDate: %(max_date)s,
                    showDropdowns: %(show_dropdowns)s,
                    showWeekNumbers: %(show_week_numbers)s,
                    showISOWeekNumbers: %(show_iso_weeks)s,
                    timePicker: %(time_picker)s,
                    timePicker24Hour: %(time_picker_24hour)s,
                    timePickerSeconds: %(time_picker_seconds)s,
                    timePickerIncrement: %(time_picker_increment)s,
                    locale: %(locale)s,
                    autoApply: %(auto_apply)s,
                    linkedCalendars: %(linked_calendars)s,
                    showCustomRangeLabel: %(show_custom_range_label)s,
                    alwaysShowCalendars: %(always_show_calendars)s,
                    opens: '%(opens)s',
                    drops: '%(drops)s',
                    buttonClasses: '%(button_classes)s',
                    applyButtonClasses: '%(apply_button_classes)s',
                    cancelButtonClasses: '%(cancel_button_classes)s',
                    ranges: ranges,
                    isInvalidDate: function(date) { # Implement disabled dates/ranges
                        var disabledDates = %(disabled_dates)s;
                        if (disabledDates && disabledDates.includes(date.format('%(format)s'))) {
                            return true;
                        }
                        var disabledRanges = %(disabled_ranges)s;
                        for (var i = 0; i < disabledRanges.length; i++) {
                            if (date >= moment(disabledRanges[i][0]) && date <= moment(disabledRanges[i][1])) {
                                return true;
                            }
                        }
                        return false;
                    }
                }}, function(start, end, label) {{
                    console.log("New date range selected: " + label + " = " + start.format('%(format)s') + ' to ' + end.format('%(format)s'));
                }});
            }});
        </script>
        """.format(
                field_id=field.id,
                format=self.format,
                separator=self.separator,
                min_date=f"'{self.min_date}'" if self.min_date else "null",
                max_date=f"'{self.max_date}'" if self.max_date else "null",
                show_dropdowns=str(self.show_dropdowns).lower(),
                show_week_numbers=str(self.show_week_numbers).lower(),
                show_iso_weeks=str(self.show_iso_weeks).lower(),
                time_picker=str(self.time_picker).lower(),
                time_picker_24hour=str(self.time_picker_24hour).lower(),
                time_picker_seconds=str(self.time_picker_seconds).lower(),
                time_picker_increment=self.time_picker_increment,
                locale=json.dumps(self.locale),
                auto_apply=str(self.auto_apply).lower(),
                linked_calendars=str(self.linked_calendars).lower(),
                show_custom_range_label=str(self.show_custom_range_label).lower(),
                always_show_calendars=str(self.always_show_calendars).lower(),
                opens=self.opens,
                drops=self.drops,
                button_classes=self.button_classes,
                apply_button_classes=self.apply_button_classes,
                cancel_button_classes=self.cancel_button_classes,
                ranges=json.dumps(
                    ranges
                ),  # Pass ranges including fiscal year ranges to template
                disabled_dates=json.dumps(
                    self.disabled_dates
                ),  # Pass disabled dates to template
                disabled_ranges=json.dumps(
                    self.disabled_ranges
                ),  # Pass disabled ranges to template
            )
        )
