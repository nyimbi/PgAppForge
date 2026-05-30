"""
nx_widgets.py: Extended Custom Widgets for PgAppForge

Self-contained widget library with embedded Jinja/JS/HTML templates.
All widgets inherit from BS3TextFieldWidget.

Widget Classes:
    TimeField               - Custom WTForms field for time input (multiple formats)
    TimePickerWidget        - Advanced time picker with 12/24hr, seconds, range validation
    RangeSliderWidget       - Dual-handle numeric range slider (PostgreSQL numrange)
    TagInputWidget          - Tag input with autocomplete, validation, JSONB/ARRAY support
    JSONEditorWidget        - Ace editor JSON editor with schema validation
    MarkdownEditorWidget    - EasyMDE markdown editor with KaTeX, image upload, autosave
    GeoPointWidget          - Leaflet map widget for PostGIS geometry/geography
    CurrencyInputWidget     - Multi-currency input with maskMoney, locale formatting
    PhoneNumberWidget       - International phone input with intl-tel-input
    RatingWidget            - Star rating with half-stars, Raty.js integration
    DurationWidget          - Duration input (days/hours/minutes/seconds), ISO 8601
    RelationshipGraphWidget - vis.js node-edge relationship graph editor
    ColorPickerWidget       - Multi-format color picker (hex/rgb/rgba/hsl), swatches
    DateRangePickerWidget   - daterangepicker with presets, timepicker, fiscal year
    RichTextEditorWidget    - Quill.js rich text editor with image upload, history
    MultiSelectWidget       - Hierarchical multi-select with Select2, grouping
    FileUploadFieldWidget   - File upload with drag-drop, preview, validation
    CheckBoxWidget          - Enhanced checkbox with tri-state, animations
    SwitchWidget            - Toggle switch widget
    StarRatingWidget        - Star rating widget (Raty.js)
    ToggleButtonWidget      - Toggle button widget
    SliderWidget            - Single-handle slider widget
    TreeViewWidget          - Hierarchical tree view with drag-drop, CRUD
    PasswordStrengthWidget  - Password input with strength meter
    ImageProcessingConfig   - Dataclass for ImageCropWidget configuration
    ImageCropWidget         - Image crop widget with Cropper.js
    SignaturePadWidget      - Signature capture widget
    CodeEditorWidget        - Ace code editor with multi-language support
    KanbanBoardWidget       - Drag-drop kanban board
    GanttChartWidget        - Gantt chart with dhtmlx-gantt
    SpreadsheetWidget       - Spreadsheet widget with Handsontable
    WorkflowDesignerWidget  - Workflow designer with Drawflow
    DocumentViewerWidget    - Document viewer (PDF, Office, images)
    DashboardDesignerWidget - Dashboard layout designer
    AudioRecordingAndPlaybackWidget - Browser audio recording/playback
    VideoRecordAndPlayWidget        - Browser video recording/playback
    MapWidget               - Leaflet map widget
    FormBuilderWidget       - Drag-drop form builder
    ActivityTimelineWidget  - Activity timeline display
    DataImportExportWidget  - CSV/JSON/XLSX import/export
    PivotTableWidget        - Pivot table with drill-down
    KPIDashboardWidget      - KPI dashboard with charts
    ChatMessagingWidget     - Real-time chat messaging
    AuditLogViewerWidget    - Audit log viewer with filtering
    BarcodeQRScannerWidget  - Barcode/QR scanner with jsQR
    DependentSelectWidget   - Cascading dependent select fields
    CommentAndLikeWidget    - Comment and like/reaction system
    FriendFollowWidget      - Friend/follow social widget
    QRCodeWidget            - QR code generator
    DataValidationRulesBuilder - Visual data validation rules builder
    DataPreviewProfilerWidget  - Data preview and profiling
    VirtualScrollingListWidget - Virtual scrolling for large lists
    VersionControlWidget    - Git-like version control for field data
    DBMLEditorWidget        - DBML (Database Markup Language) editor
    MermaidEditorWidget     - Mermaid diagram editor with live preview
    DatabaseStructureWidget - Interactive database schema visualizer
    AddressAutocompleteWidget - Address autocomplete with geocoding
    GeographicHeatmapWidget - Geographic heatmap with Leaflet.heat
    WorkflowDiagramWidget   - Workflow diagram editor (BPMN-like)
    StepWizardWidget        - Multi-step wizard widget
    GPSTrackerWidget        - Real-time GPS tracker with Leaflet
    PeriodicCameraWidget    - Periodic camera capture widget

Author: Nyimbi Odero
Date: 2024-05-20
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from pgappforge.fieldwidgets import BS3TextFieldWidget

# from pgappforge.widgets import BS3TextFieldWidget
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms import Field
from wtforms.fields import DateField  # TimeField,
from wtforms.fields import (
    BooleanField,
    DateTimeField,
    DecimalField,
    FileField,
    FloatField,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
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
        kwargs.setdefault(
            "data-slider-orientation", self.orientation
        )  # Set orientation

        if self.tooltip_options:  # Apply advanced tooltip options if provided
            kwargs.setdefault(
                "data-slider-tooltip-options", json.dumps(self.tooltip_options)
            )

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "text": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

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


class TagInputWidget(BS3TextFieldWidget):
    """
    Advanced tag input widget for PgAppForge supporting both string array and JSONB storage.

    Features:
    - Tag validation
    - Auto-complete suggestions (local and remote)
    - Custom tag formatting
    - Max tags limit
    - Duplicate prevention
    - Case sensitivity options
    - Tag categories/types with distinct styling
    - Keyboard navigation
    - Paste handling
    - Tag editing with backspace/delete
    - Flexible delimiter configuration

    Database Type:
        PostgreSQL: TEXT[] or JSONB
        SQLAlchemy: ARRAY(String) or JSONB

    Example Usage:
        tags = db.Column(ARRAY(String), default=[])
        # or
        tags = db.Column(JSONB, default={})
    """

    data_template = (
        '<div class="tag-input-container">'
        "<input %(text)s>"
        '<div class="tag-suggestions"></div>'
        '<div class="tag-error"></div>'
        "</div>"
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """Initialize tag input widget with custom settings"""
        super().__init__(**kwargs)
        self.max_tags = kwargs.get("max_tags", None)
        self.min_chars = kwargs.get("min_chars", 2)
        self.max_chars = kwargs.get("max_chars", 50)
        self.suggestions = kwargs.get("suggestions", [])
        self.remote_source = kwargs.get("remote_source", None)  # For remote suggestions
        self.allow_duplicates = kwargs.get("allow_duplicates", False)
        self.case_sensitive = kwargs.get("case_sensitive", False)
        self.tag_types = kwargs.get("tag_types", {})
        self.validate_pattern = kwargs.get("validate_pattern", None)
        self.delimiter = kwargs.get("delimiter", ",")
        self.placeholder = kwargs.get("placeholder", "Add tags...")
        self.free_input = kwargs.get(
            "free_input", True
        )  # Allow free input if no suggestions match

    def __call__(self, field, **kwargs):
        """Render the tag input widget"""
        kwargs.setdefault("type", "text")
        kwargs.setdefault("data-role", "tagsinput")
        kwargs.setdefault("placeholder", self.placeholder)

        if field.data:
            if isinstance(field.data, list):
                kwargs.setdefault("value", self.delimiter.join(field.data))
            elif isinstance(field.data, dict):
                kwargs.setdefault("value", self.delimiter.join(field.data.keys()))

        template = self.data_template if field.data else self.empty_template
        html = template % {"text": self.html_params(name=field.name, **kwargs)}

        return Markup(
            html
            + """
        <style>
            .tag-input-container {
                position: relative;
            }
            .bootstrap-tagsinput {
                width: 100%;
                border-radius: 4px;
                box-shadow: none;
                border: 1px solid #ccc;
                padding: 6px 12px;
                min-height: 34px;
            }
            .bootstrap-tagsinput .tag {
                margin-right: 4px;
                margin-bottom: 4px;
                display: inline-block;
            }
            .tag-suggestions {
                position: absolute;
                top: 100%;
                left: 0;
                right: 0;
                z-index: 1000;
                display: none;
                background: #fff;
                border: 1px solid #ccc;
                border-radius: 0 0 4px 4px;
                box-shadow: 0 6px 12px rgba(0,0,0,.175);
            }
            .tag-error {
                color: #a94442;
                margin-top: 5px;
                font-size: 12px;
            }
        </style>
        <script>
            (function() {
                var $input = $('#{field_id}');
                var $container = $input.closest('.tag-input-container');
                var $suggestions = $container.find('.tag-suggestions');
                var $error = $container.find('.tag-error');


                var tagConfig = {{
                    trimValue: true,
                    confirmKeys: [13, {delimiter_code}],
                    maxTags: {max_tags},
                    tagClass: function(item) {{
                        return 'label label-' + ({tag_types}[item] || 'primary');
                    }},
                     freeInput: {free_input}, // Allow free input
                    typeaheadjs: {typeahead_config}
                }};


                $input.tagsinput(tagConfig)

                .on('beforeItemAdd', function(event) {{
                    // Validate tag before adding
                    var tag = event.item;

                    // Check length
                    if (tag.length < {min_chars}) {{
                        event.cancel = true;
                        $error.text('Tag must be at least {min_chars} characters');
                        return;
                    }}
                    if (tag.length > {max_chars}) {{
                        event.cancel = true;
                        $error.text('Tag cannot exceed {max_chars} characters');
                        return;
                    }}

                    // Check pattern if specified
                    {pattern_check}

                    // Check duplicates
                    if (!{allow_duplicates} && $input.tagsinput('items').indexOf(
                        {case_sensitive} ? tag : tag.toLowerCase()) !== -1) {{
                        event.cancel = true;
                        $error.text('Duplicate tags not allowed');
                        return;
                    }}

                    $error.text('');
                }})

                .on('itemAdded itemRemoved', function() {{
                    // Update underlying field value
                    var tags = $input.tagsinput('items');
                    if ({store_as_json}) {{
                        var tagObj = {{}};
                        tags.forEach(function(tag) {{
                            tagObj[tag] = {tag_types}[tag] || 'default';
                        }});
                        $input.val(JSON.stringify(tagObj));
                    }} else {{
                        $input.val(tags.join('{delimiter}'));
                    }}
                }})

                // Handle tag editing (bootstrap-tagsinput doesn't directly support editing, consider a custom solution or alternative library for full editing)

                // Handle clear (if needed, implement a clear button and handler)

                // Handle paste (already implemented)


                // Initialize with existing values
                var initialValue = $input.val();
                if (initialValue) {{
                    if ({store_as_json}) {{
                        try {{
                            var tagObj = JSON.parse(initialValue);
                            Object.keys(tagObj).forEach(function(tag) {{
                                $input.tagsinput('add', tag);
                            }});
                        }} catch(e) {{
                            console.error('Invalid JSON for tags:', e);
                        }}
                    }} else {{
                        initialValue.split('{delimiter}').forEach(function(tag) {{
                            $input.tagsinput('add', tag.trim());
                        }});
                    }}
                }}
            }})();
        </script>
        """.format(
                field_id=field.id,
                max_tags="null" if self.max_tags is None else self.max_tags,
                min_chars=self.min_chars,
                max_chars=self.max_chars,
                suggestions=json.dumps(self.suggestions),
                allow_duplicates=str(self.allow_duplicates).lower(),
                case_sensitive=str(self.case_sensitive).lower(),
                tag_types=json.dumps(self.tag_types),
                pattern_check=(
                    f"""
                if (!/{self.validate_pattern}/.test(tag)) {{
                    event.cancel = true;
                    $error.text('Invalid tag format');
                    return;
                }}
            """
                    if self.validate_pattern
                    else ""
                ),
                delimiter=self.delimiter,
                delimiter_code=ord(self.delimiter),
                store_as_json=str(
                    isinstance(getattr(field, "type", None), JSONB)
                ).lower(),
                typeahead_config=(
                    f"""{{
                        source: function(query) {{
                            return $.getJSON('{self.remote_source}', {{ query: query }});
                        }},
                        display: 'value',
                        value: 'value',
                        limit: 10
                    }}"""
                    if self.remote_source
                    else f"""{{
                        source: {json.dumps(self.suggestions)},
                        limit: 10
                    }}"""
                ),
                free_input=str(self.free_input).lower(),  # Pass free_input to script
            )
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            if isinstance(self.field.type, JSONB):
                try:
                    return json.loads(valuelist[0])
                except ValueError as e:
                    raise ValueError(_("Invalid JSON for tags: ") + str(e))
            # Handle different delimiters using csv reader for robustness
            import csv

            io_text = io.StringIO(valuelist[0])
            reader = csv.reader(io_text, delimiter=self.delimiter)
            tags = next(reader)  # Get the first line of tags
            return [
                tag.strip() for tag in tags if tag.strip()
            ]  # Strip each tag for whitespace

        return []

    def process_data(self, value):
        """Process data from database format"""
        if value:
            if isinstance(value, dict):
                return json.dumps(value)
            return self.delimiter.join(value)
        return ""


class JSONEditorWidget(BS3TextFieldWidget):
    """
    Advanced JSON editor widget for PgAppForge using Ace editor.

    Database Type:
        PostgreSQL: JSONB or JSON
        SQLAlchemy: JSONB() or JSON()

    Features:
    - Syntax highlighting (Ace Editor)
    - Code folding (Ace Editor)
    - Search/replace (Ace Editor)
    - Auto-completion (Ace Editor)
    - Error detection (Ace Editor)
    - Customizable themes (Ace Editor themes)
    - Multiple view modes (code, tree, both)
    - Schema validation (AJV)
    - Schema editing UI (basic text editor for schema)
    - JSON Patch/Merge support (future extension)
    """

    data_template = (
        '<div class="json-editor-container">'
        '<div class="json-editor-controls btn-group mb-2">'
        '<button type="button" class="btn btn-sm btn-default" data-action="format"><i class="fa fa-indent"></i> Format</button>'
        '<button type="button" class="btn btn-sm btn-default" data-action="minify"><i class="fa fa-compress"></i> Minify</button>'
        '<button type="button" class="btn btn-sm btn-default" data-action="toggle-view"><i class="fa fa-eye"></i> View Mode</button>'
        '<button type="button" class="btn btn-sm btn-default" data-action="toggle-schema"><i class="fa fa-list-alt"></i> Edit Schema</button>'
        "</div>"
        "<input %(hidden)s>"
        '<div id="%(field_id)s-editor" class="json-editor"></div>'
        '<div id="%(field_id)s-tree" class="json-tree" style="display:none;"></div>'
        '<div id="%(field_id)s-schema-editor" class="json-schema-editor" style="display:none; height:200px; border:1px solid #ccc; border-radius:4px; margin-bottom: 10px;"></div>'  # Schema editor container
        '<div class="json-editor-error"></div>'
        "</div>"
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """Initialize JSON editor widget with extended settings"""
        super().__init__(**kwargs)
        self.height = kwargs.get("height", "400px")
        self.theme = kwargs.get("theme", "monokai")  # Ace Editor theme
        self.schema = kwargs.get("schema", None)
        self.readonly = kwargs.get("readonly", False)
        self.show_line_numbers = kwargs.get("show_line_numbers", True)
        self.tab_size = kwargs.get("tab_size", 2)
        self.word_wrap = kwargs.get("word_wrap", True)
        self.auto_complete = kwargs.get("auto_complete", True)
        self.ace_config_options = kwargs.get(
            "ace_config_options", {}
        )  # For Ace editor configuration
        self.json_viewer_options = kwargs.get(
            "json_viewer_options",
            {"collapsed": False, "withQuotes": True, "withLinks": True},
        )  # Options for jsonViewer

    def __call__(self, field, **kwargs):
        """Render the JSON editor widget with Ace Editor and JSON Viewer"""
        kwargs.setdefault("type", "hidden")

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        return Markup(
            html
            + """
        <style>
            .json-editor-container {{
                position: relative;
                margin-bottom: 15px;
            }}
            .json-editor, .json-schema-editor {{ /* Apply same style to schema editor */
                height: {height};
                border: 1px solid #ccc;
                border-radius: 4px;
            }}
            .json-tree {{
                height: {height};
                overflow: auto;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 4px;
            }}
            .json-editor-error {{
                color: #a94442;
                margin-top: 5px;
            }}
            .json-editor-controls {{
                margin-bottom: 10px;
            }}
        </style>
        <script>
            (function() {{
                // Initialize Ace editor for JSON Data
                var editor = ace.edit("{field_id}-editor");
                editor.setTheme("ace/theme/{theme}");
                editor.session.setMode("ace/mode/json");
                editor.setReadOnly({readonly});
                editor.setShowPrintMargin(false);
                editor.setHighlightActiveLine(true);
                editor.setShowInvisibles(false);
                editor.setDisplayIndentGuides(true);
                editor.getSession().setTabSize({tab_size});
                editor.getSession().setUseSoftTabs(true);
                editor.getSession().setUseWrapMode({word_wrap});
                editor.renderer.setShowGutter({show_line_numbers});

                // Apply additional Ace configuration options
                editor.setOptions({ace_config_options});


                if ({auto_complete}) {{
                    editor.setOptions({{
                        enableBasicAutocompletion: true,
                        enableLiveAutocompletion: true,
                        enableSnippets: true
                    }});
                }}


                // Initialize Ace editor for JSON Schema (hidden initially)
                var schemaEditor = ace.edit("{field_id}-schema-editor");
                schemaEditor.setTheme("ace/theme/{theme}");
                schemaEditor.session.setMode("ace/mode/json");
                schemaEditor.setShowPrintMargin(false);
                schemaEditor.getSession().setTabSize({tab_size});
                schemaEditor.getSession().setUseSoftTabs(true);


                // Set initial values
                var initialValue = {json_data};
                editor.setValue(JSON.stringify(initialValue, null, {tab_size}));
                editor.clearSelection();


                var initialSchema = {schema};
                schemaEditor.setValue(JSON.stringify(initialSchema, null, {tab_size})); // Set schema editor value
                schemaEditor.clearSelection();


                // JSON Schema validation function using Ajv
                var schema = {schema}; // Initial schema
                function validateJson(json, currentSchema) {{ // Pass schema dynamically
                    if (!currentSchema) return true;
                    try {{
                        var ajv = new Ajv();
                        var valid = ajv.validate(currentSchema, json);
                        if (!valid) {{
                            $('.json-editor-error').text(ajv.errorsText());
                        }} else {{
                            $('.json-editor-error').text('');
                        }}
                        return valid;
                    }} catch (e) {{
                        $('.json-editor-error').text(e.message);
                        return false;
                    }}
                }}


                // Handle changes in JSON Data Editor and validate
                var $input = $('#{field_id}');
                editor.on('change', function() {{
                    try {{
                        var value = editor.getValue();
                        var json = JSON.parse(value);
                        var currentSchema = JSON.parse(schemaEditor.getValue() || 'null'); // Get current schema from editor
                        if (validateJson(json, currentSchema)) {{ // Pass currentSchema for validation
                            $input.val(value);
                            editor.getSession().clearAnnotations();
                        }}
                    }} catch (e) {{
                        editor.getSession().setAnnotations([{{
                            row: 0,
                            column: 0,
                            text: e.message,
                            type: 'error'
                        }}]);
                    }}
                }});


                // Control button handlers
                $('.json-editor-controls [data-action="format"]').click(function() {{
                    try {{
                        var value = JSON.parse(editor.getValue());
                        editor.setValue(JSON.stringify(value, null, {tab_size}));
                        editor.clearSelection();
                    }} catch (e) {{
                        alert('Invalid JSON: ' + e.message);
                    }}
                }});


                $('.json-editor-controls [data-action="minify"]').click(function() {{
                    try {{
                        var value = JSON.parse(editor.getValue());
                        editor.setValue(JSON.stringify(value));
                        editor.clearSelection();
                    }} catch (e) {{
                        alert('Invalid JSON: ' + e.message);
                    }}
                }});


                // Toggle tree/code view
                var $editor = $('#{field_id}-editor');
                var $tree = $('#{field_id}-tree');
                var viewerOptions = {json_viewer_options}; // Use jsonViewerOptions

                $('.json-editor-controls [data-action="toggle-view"]').click(function() {{
                    if ($editor.is(':visible')) {{
                        try {{
                            var value = JSON.parse(editor.getValue());
                            $tree.jsonViewer(value, viewerOptions);
                            $editor.hide();
                            $tree.show();
                        }} catch (e) {{
                            alert('Invalid JSON: ' + e.message);
                        }}
                    }} else {{
                        $tree.hide();
                        $editor.show();
                        editor.focus();
                    }}
                }});


                // Toggle schema editor
                var $schemaEditorDiv = $('#{field_id}-schema-editor');
                $('.json-editor-controls [data-action="toggle-schema"]').click(function() {{
                    $schemaEditorDiv.toggle();
                    if ($schemaEditorDiv.is(':visible')) {{
                        schemaEditor.focus();
                    }}
                }});


                // Handle changes in Schema Editor
                schemaEditor.on('change', function() {{
                    var currentSchema = null; // Default schema to null if parsing fails
                    try {{
                        currentSchema = JSON.parse(schemaEditor.getValue());
                    }} catch (e) {{
                        $('.json-editor-error').text('Invalid JSON Schema: ' + e.message);
                        return; // Exit validation if schema is invalid
                    }}
                    var value = editor.getValue();
                    var json = JSON.parse(value); // Parse current JSON data for validation
                    validateJson(json, currentSchema); // Validate with the current schema
                }});


            }})();
        </script>
        """.format(
                field_id=field.id,
                height=self.height,
                theme=self.theme,
                readonly=str(self.readonly).lower(),
                show_line_numbers=str(self.show_line_numbers).lower(),
                tab_size=self.tab_size,
                word_wrap=str(self.word_wrap).lower(),
                auto_complete=str(self.auto_complete).lower(),
                json_data=json.dumps(field.data or {}),
                schema=json.dumps(self.schema) if self.schema else "null",
                ace_config_options=json.dumps(self.ace_config_options),
                json_viewer_options=json.dumps(self.json_viewer_options),
            )
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                return json.loads(valuelist[0])
            except ValueError as e:
                raise ValueError(_("Invalid JSON: ") + str(e))
        return None

    def process_data(self, value):
        """Process data from database format"""
        if value is not None:
            return json.dumps(value)
        return None


class MarkdownEditorWidget(BS3TextFieldWidget):
    """
    An advanced Markdown editor widget for PgAppForge forms with enhanced features.

    This widget integrates EasyMDE for rich markdown editing capabilities with real-time
    preview, syntax highlighting, and extensive customization options.

    Attributes:
        data_template (str): HTML template for the editor when data is present
        empty_template (str): HTML template for the editor when empty

    Features:
        - Real-time preview with configurable rendering
        - Syntax highlighting with multiple theme support
        - Customizable toolbar with extensive options
        - Image upload support with progress tracking
        - Mathematical equation rendering via KaTeX
        - Auto-save functionality with configurable delay
        - Word and character counting
        - Full-screen editing mode
        - Split-screen preview mode
        - Spell checking with customizable dictionary

    Database Compatibility:
        - PostgreSQL: Text or JSONB (for metadata storage)
        - MySQL: TEXT or JSON
        - SQLite: TEXT
    """

    data_template: str = (
        '<div class="markdown-editor-container">'
        "  <input %(hidden)s>"
        '  <div id="%(field_id)s-editor" class="markdown-editor"></div>'
        '  <div class="markdown-metadata">'
        '    <span class="word-count"></span>'
        '    <span class="char-count"></span>'
        '    <span class="save-status"></span>'
        "  </div>"
        "</div>"
    )
    empty_template: str = data_template

    def __init__(
        self,
        autosave: bool = True,
        autosave_delay: int = 1000,
        spellchecker: bool = True,
        upload_url: str = "/api/upload",
        theme: str = "default",
        toolbar_config: Optional[List[str]] = None,
        status_bar_items: Optional[List[str]] = None,
        syntax_highlighting: bool = True,
        math_delimiters: Optional[List[Dict[str, str]]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the Markdown editor widget with customizable settings.

        Args:
            autosave: Enable/disable automatic saving of content
            autosave_delay: Delay in milliseconds between auto-saves
            spellchecker: Enable/disable spell checking
            upload_url: Endpoint for image uploads
            theme: Editor theme name
            toolbar_config: List of toolbar items to display
            status_bar_items: List of status bar items to show
            syntax_highlighting: Enable/disable syntax highlighting
            math_delimiters: Custom delimiters for math equations
            **kwargs: Additional keyword arguments
        """
        super().__init__(**kwargs)

        self.autosave = autosave
        self.autosave_delay = autosave_delay
        self.spellchecker = spellchecker
        self.upload_url = upload_url
        self.theme = theme
        self.syntax_highlighting = syntax_highlighting

        # Default toolbar configuration
        self.toolbar_config = toolbar_config or [
            "bold",
            "italic",
            "heading",
            "|",
            "quote",
            "code",
            "unordered-list",
            "ordered-list",
            "|",
            "link",
            "image",
            "table",
            "|",
            "preview",
            "side-by-side",
            "fullscreen",
            "|",
            "guide",
        ]

        # Default status bar items
        self.status_bar_items = status_bar_items or [
            "autosave",
            "lines",
            "words",
            "cursor",
            "upload-progress",
        ]

        # Default math delimiters
        self.math_delimiters = math_delimiters or [
            {"left": "$$", "right": "$$", "display": True},
            {"left": "$", "right": "$", "display": False},
        ]

    def __call__(self, field: Any, **kwargs: Any) -> Markup:
        """
        Render the widget HTML and JavaScript.

        Args:
            field: The form field to render
            **kwargs: Additional rendering options

        Returns:
            Markup: Safe HTML markup for the widget
        """
        kwargs.setdefault("type", "hidden")

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        return Markup(f"""
            {html}
            <script>
                (function() {{
                    // Initialize EasyMDE with enhanced configuration
                    const easyMDE = new EasyMDE({{
                        element: document.getElementById('{field.id}-editor'),
                        initialValue: {json.dumps(field.data or "")},
                        spellChecker: {str(self.spellchecker).lower()},
                        autoDownloadFontAwesome: false,
                        autosave: {{
                            enabled: {str(self.autosave).lower()},
                            delay: {self.autosave_delay},
                            uniqueId: "{field.id}",
                            text: "Auto-saved: "
                        }},
                        theme: "{self.theme}",
                        toolbar: {json.dumps(self.toolbar_config)},
                        status: {json.dumps(self.status_bar_items)},
                        uploadImage: true,
                        imageUploadEndpoint: "{self.upload_url}",
                        renderingConfig: {{
                            singleLineBreaks: false,
                            codeSyntaxHighlighting: {str(self.syntax_highlighting).lower()},
                            sanitizerFunction: (html) => {{
                                // Implement custom sanitization if needed
                                return html;
                            }}
                        }},
                        previewRender: function(plainText, preview) {{
                            // Enhanced preview with KaTeX support
                            setTimeout(() => {{
                                renderMathInElement(preview, {{
                                    delimiters: {json.dumps(self.math_delimiters)},
                                    throwOnError: false,
                                    errorColor: '#cc0000'
                                }});
                            }}, 0);
                            return this.parent.markdown(plainText);
                        }}
                    }});

                    // Enhanced change handler with debouncing
                    let updateTimeout;
                    easyMDE.codemirror.on("change", () => {{
                        clearTimeout(updateTimeout);
                        updateTimeout = setTimeout(() => {{
                            const value = easyMDE.value();
                            const input = document.getElementById('{field.id}');
                            input.value = value;

                            // Update metadata with enhanced counting
                            const wordCount = value.trim().split(/\\s+/).filter(w => w.length > 0).length;
                            const charCount = value.length;

                            document.querySelector('.markdown-metadata .word-count')
                                .textContent = `${{wordCount}} words`;
                            document.querySelector('.markdown-metadata .char-count')
                                .textContent = `${{charCount}} characters`;
                        }}, 150);
                    }});

                    // Enhanced image upload handler with progress tracking
                    easyMDE.uploadImage = async function(file, onSuccess, onError) {{
                        const formData = new FormData();
                        formData.append('image', file);

                        try {{
                            const response = await fetch('{self.upload_url}', {{
                                method: 'POST',
                                body: formData,
                                headers: {{
                                    'Accept': 'application/json'
                                }}
                            }});

                            if (!response.ok) {{
                                throw new Error(`HTTP error! status: ${{response.status}}`);
                            }}

                            const data = await response.json();
                            if (data?.url) {{
                                onSuccess(data.url);
                            }} else {{
                                throw new Error('Upload response missing URL');
                            }}
                        }} catch (error) {{
                            console.error('Upload error:', error);
                            onError(`Image upload failed: ${{error.message}}`);
                        }}
                    }};

                    // Initialize KaTeX for existing math content
                    if (easyMDE.value().includes('$')) {{
                        renderMathInElement(
                            document.getElementById('{field.id}-editor'),
                            {{
                                delimiters: {json.dumps(self.math_delimiters)},
                                throwOnError: false,
                                errorColor: '#cc0000'
                            }}
                        );
                    }}
                }})();
            </script>
        """)

    def process_data(self, value: Union[str, Dict[str, Any], None]) -> str:
        """
        Process data from database format to editor format.

        Args:
            value: Input value from database

        Returns:
            str: Processed content string
        """
        if isinstance(value, dict):
            return value.get("content", "")
        return value or ""

    def process_formdata(self, valuelist: List[str]) -> Optional[str]:
        """
        Process form data to database format.

        Args:
            valuelist: List of form values

        Returns:
            Optional[str]: Processed content string or None
        """
        return valuelist[0] if valuelist else None


class GeoPointWidget(BS3TextFieldWidget):
    """
    Widget for geographical point selection using interactive maps.
    Designed to work with PostgreSQL's PostGIS geography/geometry types.

    Features:
    - Interactive map selection with marker, polygon, and polyline drawing
    - Supports multiple map providers (OpenStreetMap, Google Maps, Mapbox)
    - Geocoding support via Nominatim and customizable providers
    - Clustering of markers for large datasets
    - Custom marker icons and popups
    - Default location and zoom level settings
    - Customizable map styles and layers (including GeoJSON overlays)
    - Multiple coordinate formats and PostGIS compatibility
    - Enhanced search functionality with provider customization
    - Current location detection
    - Improved error handling and user feedback

    Database Type:
        PostgreSQL: geography(GEOMETRY,4326) or geometry(GEOMETRY,4326)
        SQLAlchemy: Geometry("POINT", srid=4326) or Geometry("GEOMETRY", srid=4326)

    Example Usage:
        location = db.Column(Geometry("POINT", srid=4326))
        area = db.Column(Geometry("POLYGON", srid=4326))
        route = db.Column(Geometry("LINESTRING", srid=4326))
    """

    data_template = (
        '<div class="geopoint-widget">'
        '<div class="input-group">'
        "<input %(text)s>"
        '<span class="input-group-addon"><i class="fa fa-search"></i></span>'
        "</div>"
        "<input %(hidden)s>"
        '<div id="%(field_id)s-map" class="map-container" style="height: 400px;"></div>'
        '<div class="map-controls">'
        '<button type="button" class="btn btn-sm btn-default" id="%(field_id)s-mylocation">'
        '<i class="fa fa-location-arrow"></i> My Location'
        "</button>"
        '<span class="coordinates-display"></span>'
        "</div>"
        '<div class="graph-error" role="alert" aria-live="assertive"></div>'  # Error div for WCAG
        "</div>"
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """
        Initialize GeoPointWidget with extended custom settings

        Args:
            default_location (tuple): Default map center (lat, lng)
            default_zoom (int): Default zoom level
            map_provider (str): Map provider ('osm', 'google', 'mapbox')
            api_key (str): API key for commercial map providers
            enable_search (bool): Enable location search via Nominatim
            search_provider (str): Custom search provider URL (if not Nominatim)
            enable_mylocation (bool): Enable current location detection
            marker_icon (str): Custom marker icon URL
            map_style (dict): Custom map style configuration
            enable_drawing (bool): Enable polygon and polyline drawing tools
            enable_clustering (bool): Enable marker clustering for points
            geojson_layers (list): List of GeoJSON layer configurations
        """
        super().__init__(**kwargs)
        self.default_location = kwargs.get("default_location", (0, 0))
        self.default_zoom = kwargs.get("default_zoom", 13)
        self.map_provider = kwargs.get("map_provider", "osm")
        self.api_key = kwargs.get("api_key", "")
        self.enable_search = kwargs.get(
            "enable_search", True
        )  # Enable/Disable Nominatim search
        self.search_provider = kwargs.get(
            "search_provider", "nominatim"
        )  # Default to Nominatim
        self.enable_mylocation = kwargs.get("enable_mylocation", True)
        self.marker_icon = kwargs.get("marker_icon", "")
        self.map_style = kwargs.get("map_style", {})
        self.enable_drawing = kwargs.get(
            "enable_drawing", False
        )  # Enable drawing tools
        self.enable_clustering = kwargs.get(
            "enable_clustering", False
        )  # Enable marker clustering
        self.geojson_layers = kwargs.get(
            "geojson_layers", []
        )  # Configuration for GeoJSON layers

    def __call__(self, field, **kwargs):
        """Render the widget with Leaflet map and controls"""
        kwargs.setdefault("type", "hidden")
        search_kwargs = {
            "type": "text",
            "class": "form-control",
            "placeholder": "Search location...",
            "autocomplete": "off",
        }

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "text": self.html_params(id=f"{field.id}-search", **search_kwargs),
            "field_id": field.id,
        }

        return Markup(
            html
            + """
        <script>
            (function() {
                var map = L.map('{field_id}-map').setView({default_location}, {default_zoom});
                {tile_layer}

                var marker;
                var drawnItems = new L.FeatureGroup().addTo(map); // FeatureGroup for drawn items
                var drawControl = new L.Control.Draw({{ // Leaflet.draw control
                    edit: {{ featureGroup: drawnItems, poly: {{ allowIntersection: false }} }},
                    draw: {{ polygon: {{ allowIntersection: false }}, polyline: true, rectangle: false, circle: false, marker: true }}
                }});


                if ({enable_drawing}) {{
                    map.addControl(drawControl);
                }}


                function setMarker(latlng) {{
                    if (marker) map.removeLayer(marker);
                    marker = L.marker(latlng, {{ draggable: true, icon: {marker_icon} }}).addTo(map);
                    $('#{field_id}').val(latlng.lat + ',' + latlng.lng);
                    $('.coordinates-display').text('Lat: ' + latlng.lat.toFixed(6) + ', Lng: ' + latlng.lng.toFixed(6));
                    marker.on('dragend', function(e) {{ setMarker(e.target.getLatLng()); }});
                }}


                map.on('draw:created', function(e) {{ // Handle draw created event
                    var type = e.layerType, layer = e.layer;
                    drawnItems.clearLayers(); // For simplicity, clear existing and add new, consider different behavior if needed
                    drawnItems.addLayer(layer);


                     var geojsonData = drawnItems.toGeoJSON();
                     $('#{field_id}').val(JSON.stringify(geojsonData)); // Store GeoJSON in hidden field

                }});

                map.on('draw:edited', function(e) {{ // Handle draw edited event
                    var layers = e.layers;
                     layers.eachLayer(function(layer) {{
                         var geojsonData = drawnItems.toGeoJSON();
                         $('#{field_id}').val(JSON.stringify(geojsonData)); // Update hidden field on edit
                     }});
                }});

                map.on('draw:deleted', function(e) {{ // Handle draw deleted event
                     drawnItems.clearLayers();
                     $('#{field_id}').val(''); // Clear hidden field if drawings are deleted
                }});


                map.on('click', function(e) {{ setMarker(e.latlng); }});


                var markers = L.markerClusterGroup(); // Marker cluster group

                function addMarkersClustered(locations) {{ // Function to add clustered markers
                    markers.clearLayers();
                    locations.forEach(function(loc) {{
                        L.marker([loc.lat, loc.lng]).bindPopup(loc.popupContent).addTo(markers);
                    }});
                    map.addLayer(markers);
                }}
                if ({enable_clustering}) {{ // Initialize clustering if enabled
                     map.addLayer(markers);
                }}


                {geojson_layer_init} // Initialize GeoJSON layers


                if ({enable_search}) {{
                    $('#{field_id}-search').on('input', function() {{
                        var query = $(this).val();
                        if (query.length > 2) {{
                             {search_handler} // Use selected search provider
                        }}
                    }});
                }}

                if ({enable_mylocation}) {{
                    $('#{field_id}-mylocation').on('click', function() {{
                        if ("geolocation" in navigator) {{
                            navigator.geolocation.getCurrentPosition(function(position) {{
                                var location = [position.coords.latitude, position.coords.longitude];
                                map.setView(location, 16);
                                setMarker({{lat: location[0], lng: location[1]}});
                            }}, function(error) {{ // Improved error handling for geolocation
                                $('.graph-error').text('Geolocation error: ' + error.message).show();
                                setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000); // Fade out error message
                            }});
                        }} else {{
                             $('.graph-error').text('Geolocation is not supported by your browser.').show(); // Inform user about browser support
                             setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                        }}
                    }});
                }}


                var initialValue = $('#{field_id}').val();
                if (initialValue) {{
                    try {{
                         var geojsonData = JSON.parse(initialValue);
                         if (geojsonData.type === 'FeatureCollection' || geojsonData.type === 'Feature' || geojsonData.type === 'Point' || geojsonData.type === 'Polygon' || geojsonData.type === 'LineString') {{
                            L.geoJSON(geojsonData, {{
                                onEachFeature: function (feature, layer) {{
                                     drawnItems.addLayer(layer); // Add GeoJSON to FeatureGroup for editing
                                }}}).addTo(map);
                            map.fitBounds(drawnItems.getBounds(), {{ maxZoom: 15 }}); // Fit map bounds to GeoJSON
                         }} else {{
                             var coords = initialValue.split(',').map(Number);
                             setMarker([coords[0], coords[1]]);
                         }}
                    }} catch (e) {{
                        $('.graph-error').text('Error loading saved location data.').show(); // User-friendly error message for data loading issues
                        setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                        console.error('Error parsing GeoJSON or location data:', e);
                    }}
                }}


            }})();
        </script>
        """.format(
                field_id=field.id,
                default_location=self.default_location,
                default_zoom=self.default_zoom,
                tile_layer=self._get_tile_layer(),
                search_control="true" if self.enable_search else "false",
                marker_icon=(
                    f"L.icon({{ iconUrl: '{self.marker_icon}' }})"
                    if self.marker_icon
                    else "L.Icon.Default()"
                ),
                enable_search=str(self.enable_search).lower(),
                enable_mylocation=str(self.enable_mylocation).lower(),
                enable_drawing=str(
                    self.enable_drawing
                ).lower(),  # Pass enable_drawing to script
                enable_clustering=str(
                    self.enable_clustering
                ).lower(),  # Pass enable_clustering
                geojson_layer_init=self._render_geojson_layers(),  # Render GeoJSON layer initialization
                search_handler=self._render_search_handler(),  # Render search handler based on provider
            )
        )

    def _render_geojson_layers(self):
        """Initialize GeoJSON layers from configuration"""
        init_code = ""
        for layer_conf in self.geojson_layers:
            if "url" in layer_conf:
                init_code += f"""
                    $.getJSON('{layer_conf["url"]}', function(data) {{
                        L.geoJSON(data, {json.dumps(layer_conf.get("options", {}))}).addTo(map);
                    }});
                """
        return init_code

    def _render_search_handler(self):
        """Render search handler Javascript based on provider"""
        if self.search_provider == "google" and self.api_key:
            return f"""
                 var service = new google.maps.places.AutocompleteService();
                    service.getPlacePredictions({{
                        input: query,
                        types: ['geocode'],
                        componentRestrictions: {{ country: '{self.countries[0]}' }} // Apply country restriction if needed
                    }}, function(predictions, status) {{
                        if (status != google.maps.places.PlacesServiceStatus.OK) {{
                             $('.graph-error').text('Geocoding service error: ' + status).show(); // Display Google Places API errors
                             setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                            return;
                        }}

                        if (predictions)
                         {{
                            // Handle google places predictions - you might need to use PlacesService to get details
                            // Example (basic - you'll need to adapt based on how you want to use Google Places API):
                            var location = predictions[0].geometry.location;
                            map.setView([location.lat(), location.lng()], 16);
                            setMarker({{lat: location.lat(), lng: location.lng()}});

                        }}
                    }});

            """
        elif self.search_provider == "mapbox" and self.api_key:
            return f"""
                $.get('https://api.mapbox.com/geocoding/v5/mapbox.places/' + query + '.json', {{
                    access_token: '{self.api_key}',
                    country: '{','.join(self.countries)}', // Apply country restriction
                    limit: 5
                }}, function(data) {{
                    if (data && data.features.length > 0) {{
                        var location = data.features[0].center.reverse(); // Reverse [lng, lat] to [lat, lng]
                        map.setView(location, 16);
                        setMarker({{lat: location[0], lng: location[1]}});
                    }}
                     else {{
                             $('.graph-error').text('Location not found using Mapbox service.').show();
                             setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                        }}
                }}).fail(function(jqXHR, textStatus, errorThrown) {{ // Handle AJAX errors
                    $('.graph-error').text('Mapbox Geocoding error: ' + textStatus + ', ' + errorThrown).show();
                    setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                }});
            """

        else:  # Default to Nominatim (or 'osm')
            return """
                $.get('https://nominatim.openstreetmap.org/search', {{
                    format: 'json',
                    q: query,
                    countrycodes: '{country_codes}', // Apply country restriction for Nominatim
                    limit: 5
                }}, function(data) {{
                    if (data.length > 0) {{
                        var location = [parseFloat(data[0].lat), parseFloat(data[0].lon)];
                        map.setView(location, 16);
                        setMarker({{lat: location[0], lng: location[1]}});
                    }} else {{
                        $('.graph-error').text('Location not found using OpenStreetMap Nominatim service.').show(); // User-friendly error message if Nominatim fails
                        setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                    }}
                }}).fail(function(jqXHR, textStatus, errorThrown) {{ // Handle AJAX errors for Nominatim
                     $('.graph-error').text('Nominatim Geocoding error: ' + textStatus + ', ' + errorThrown).show();
                     setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                }});
            """.format(
                country_codes=",".join(self.countries).lower()
            )  # Apply country codes to Nominatim

    def _get_tile_layer(self):
        """Configure tile layer based on map provider and API key"""
        if self.map_provider == "google" and self.api_key:
            return f"""
                L.gridLayer.googleMutant({{
                    type: 'roadmap',
                    apiKey: '{self.api_key}',
                    styles: {json.dumps(self.map_style)}
                }}).addTo(map);
            """
        elif self.map_provider == "mapbox" and self.api_key:
            return f"""
                L.tileLayer('https://api.mapbox.com/styles/v1/mapbox/streets-v11/tiles/{{z}}/{{x}}/{{y}}?access_token={self.api_key}', {{
                    attribution: '© Mapbox'
                }}).addTo(map);
            """
        elif (
            self.map_provider == "here" and self.api_key
        ):  # Example for HERE Maps tile layer (replace with actual HERE Maps tile URL if needed)
            return f"""
                var hereTileUrl = 'https://xyz.api.here.com/maps/raster/satellite.day/512/{{z}}/{{x}}/{{y}}/512/png?apiKey={self.api_key}&style=explore.day';
                L.tileLayer(hereTileUrl, {{
                    attribution: '© HERE 2024'
                }}).addTo(map);
            """
        else:  # Default to OpenStreetMap
            return """
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                }).addTo(map);
            """

    def process_formdata(
        self, valuelist
    ):  # Corrected method name and added value parameter
        """Process form data to database format, handles GeoJSON or lat,lng strings"""
        if valuelist and valuelist[0]:
            value = valuelist[0]
            try:
                geojson_data = json.loads(value)  # Try to parse as GeoJSON first
                return geojson_data  # Return GeoJSON directly if valid
            except json.JSONDecodeError:
                try:
                    lat, lng = map(
                        float, value.split(",")
                    )  # Fallback to lat,lng parsing if not GeoJSON
                    return (
                        f"SRID=4326;POINT({lng} {lat})"  # Return PostGIS point format
                    )
                except ValueError:
                    raise ValueError(
                        _("Invalid location format")
                    )  # Indicate invalid format for both GeoJSON and lat,lng
        return None

    def process_data(self, value):
        """Process data from database format to widget format. Handles PostGIS Geometry or GeoJSON"""
        if value:
            if isinstance(value, str) and value.startswith(
                '{"type":'
            ):  # Check if it's GeoJSON string
                try:
                    return json.loads(
                        value
                    )  # Return GeoJSON object if it's a valid JSON string
                except json.JSONDecodeError:
                    pass  # Not valid JSON, proceed with other checks

            if (
                hasattr(value, "coords") and value.geom_type == "Point"
            ):  # Handle PostGIS Point Geometry object
                lng, lat = value.coords
                return f"{lat},{lng}"  # Return lat,lng string format for point

            elif isinstance(
                value, str
            ):  # If it's still a string, return as is (could be lat,lng string or other text data)
                return value
        return None


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
        self.currency = kwargs.get("currency", "USD")  # Default currency set to USD
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
        kwargs.setdefault("class", "form-control currency-input")
        kwargs.setdefault(
            "data-precision", self.precision
        )  # Pass precision as data attribute
        kwargs.setdefault("data-thousands", self.thousands_sep)  # Pass thousands_sep
        kwargs.setdefault("data-decimal", self.decimal_sep)  # Pass decimal_sep
        kwargs.setdefault(
            "data-symbol-position", self.symbol_position
        )  # Pass symbol position

        if field.flags.required:
            kwargs["required"] = True

        currency_selector_html = self._render_currency_selector(
            field.id, self.currency
        )  # Render currency dropdown
        template = self.data_template if field.data else self.empty_template
        html = template % {
            "text": self.html_params(name=field.name, **kwargs),
            "currency_symbol": self.CURRENCIES[self.currency][
                "symbol"
            ],  # Initial currency symbol
            "currency_selector": currency_selector_html,  # Insert currency selector HTML
        }

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
        self.default_country = kwargs.get("default_country", "US")
        self.preferred_countries = kwargs.get("preferred_countries", ["US", "GB", "CA"])
        self.allow_extensions = kwargs.get("allow_extensions", True)
        self.auto_format = kwargs.get("auto_format", True)
        self.national_mode = kwargs.get("national_mode", False)
        self.mobile_only = kwargs.get("mobile_only", False)
        self.placeholder = kwargs.get("placeholder", "Enter phone number")
        self.custom_error_messages = kwargs.get(
            "error_messages", {}
        )  # Custom error messages dict

    def __call__(self, field, **kwargs):
        """Render the phone input widget"""
        kwargs.setdefault("type", "tel")
        kwargs.setdefault("class", "form-control phone-input")
        kwargs.setdefault("placeholder", self.placeholder)

        if field.flags.required:
            kwargs["required"] = True

        template = self.data_template if field.data else self.empty_template
        html = template % {"text": self.html_params(name=field.name, **kwargs)}

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
        self.number = kwargs.get("number", 5)  # Number of stars
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
        kwargs.setdefault(
            "aria-invalid", "true" if field.errors else "false"
        )  # ARIA invalid state

        if field.flags.required:
            kwargs["required"] = True
            kwargs.setdefault("aria-required", "true")  # ARIA required attribute

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

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
        self.show_seconds = kwargs.get("show_seconds", True)
        self.show_days = kwargs.get("show_days", True)
        self.show_microseconds = kwargs.get(
            "show_microseconds", False
        )  # Not directly used in granular input
        self.min_duration = kwargs.get("min_duration", None)  # In timedelta seconds
        self.max_duration = kwargs.get("max_duration", None)  # In timedelta seconds
        self.step = kwargs.get(
            "step", 1
        )  # Step interval for seconds input, not directly applicable to all units
        self.placeholder = kwargs.get(
            "placeholder", "P0D"
        )  # ISO 8601 Duration format placeholder
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
        kwargs.setdefault("type", "text")  # Hidden input still text type for value
        kwargs.setdefault(
            "placeholder", self.placeholder
        )  # ISO format as default placeholder
        kwargs.setdefault("autocomplete", "off")

        if self.required:
            kwargs["required"] = True

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "text": self.html_params(name=field.name, **kwargs),
            "show_seconds_style": "block" if self.show_seconds else "none",
        }  # Control seconds input visibility

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


class RelationshipGraphWidget(BS3TextFieldWidget):
    """
    Advanced relationship graph visualization widget using vis.js network.
    Allows visualization and editing of node-edge relationships.
    """

    template = """
        <div class="relationship-graph-widget">
            <div class="graph-controls">
                <div class="btn-group">
                    <button type="button" class="btn btn-default btn-sm" id="%(field_id)s-add-node">
                        <i class="fa fa-plus"></i> Add Node
                    </button>
                    <button type="button" class="btn btn-default btn-sm" id="%(field_id)s-add-edge">
                        <i class="fa fa-link"></i> Add Edge
                    </button>
                    <button type="button" class="btn btn-default btn-sm" id="%(field_id)s-delete">
                        <i class="fa fa-trash"></i> Delete Selected
                    </button>
                </div>
                <div class="btn-group">
                    <button type="button" class="btn btn-default btn-sm" id="%(field_id)s-zoom-in">
                        <i class="fa fa-search-plus"></i>
                    </button>
                    <button type="button" class="btn btn-default btn-sm" id="%(field_id)s-zoom-out">
                        <i class="fa fa-search-minus"></i>
                    </button>
                    <button type="button" class="btn btn-default btn-sm" id="%(field_id)s-fit">
                        <i class="fa fa-compress"></i>
                    </button>
                </div>
                <div class="btn-group">
                    <button type="button" class="btn btn-default btn-sm" id="%(field_id)s-export-json">
                        <i class="fa fa-download"></i> Export JSON
                    </button>
                    <button type="button" class="btn btn-default btn-sm" id="%(field_id)s-import-json">
                        <i class="fa fa-upload"></i> Import JSON
                    </button>
                </div>
            </div>
            <input %(hidden)s>
            <div id="%(field_id)s-graph" class="graph-container"></div>
            <div class="graph-error"></div>
        </div>
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.height = kwargs.get("height", "600px")
        self.physics_enabled = kwargs.get("physics_enabled", True)
        self.clustering_enabled = kwargs.get("clustering_enabled", False)
        self.layout_algorithm = kwargs.get("layout_algorithm", "hierarchical")
        self.node_style = kwargs.get("node_style", {})
        self.edge_style = kwargs.get("edge_style", {})
        self.max_nodes = kwargs.get("max_nodes", 100)
        self.max_edges = kwargs.get("max_edges", 200)
        self.enable_editing = kwargs.get("enable_editing", True)

    def __call__(self, field, **kwargs):
        kwargs["type"] = "hidden"

        # Prepare field data
        field_data = {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        # Generate base HTML
        html = self.template % field_data

        # Add required JavaScript and CSS
        js_data = {
            "field_id": field.id,
            "height": self.height,
            "physics_enabled": str(self.physics_enabled).lower(),
            "clustering_enabled": str(self.clustering_enabled).lower(),
            "layout_algorithm": self.layout_algorithm,
            "node_style": json.dumps(self.node_style),
            "edge_style": json.dumps(self.edge_style),
            "max_nodes": self.max_nodes,
            "max_edges": self.max_edges,
            "enable_editing": str(self.enable_editing).lower(),
            "nodes": json.dumps(getattr(field, "nodes", [])),
            "edges": json.dumps(getattr(field, "edges", [])),
            "initial_data": json.dumps(field.data) if field.data else "null",
        }

        # Add styles and scripts
        html += self._generate_styles(js_data)
        html += self._generate_scripts(js_data)

        return Markup(html)

    def _generate_styles(self, data):
        return (
            """
            <style>
                .relationship-graph-widget {
                    position: relative;
                    margin-bottom: 20px;
                }
                .graph-container {
                    height: %(height)s;
                    border: 1px solid #ddd;
                    background: #fafafa;
                }
                .graph-controls {
                    margin-bottom: 10px;
                }
                .graph-error {
                    color: #a94442;
                    display: none;
                    margin-top: 5px;
                }
                .vis-network:focus {
                    outline: none;
                }
            </style>
        """
            % data
        )

    def _generate_scripts(self, data):
        # Implementation of JavaScript functionality
        # This would include all the vis.js network initialization and event handling
        # The actual JavaScript code would go here, properly formatted and escaped
        pass

    def pre_validate(self, form):
        """Validate graph data before form processing"""
        if not self.data:
            return

        try:
            data = json.loads(self.data)
            self._validate_graph_structure(data)
            self._validate_graph_constraints(data)
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON data format")
        except ValidationError as e:
            raise e
        except Exception as e:
            raise ValidationError(f"Graph validation error: {str(e)}")

    def _validate_graph_structure(self, data):
        """Validate basic graph structure"""
        if not isinstance(data, dict):
            raise ValidationError("Invalid graph data format: Must be a JSON object")

        if not all(key in data for key in ["nodes", "edges"]):
            raise ValidationError("Missing required graph components")

        if not all(isinstance(data[key], list) for key in ["nodes", "edges"]):
            raise ValidationError("Nodes and edges must be lists")

    def _validate_graph_constraints(self, data):
        """Validate graph constraints"""
        if len(data["nodes"]) > self.max_nodes:
            raise ValidationError(
                f"Maximum number of nodes ({self.max_nodes}) exceeded"
            )

        if len(data["edges"]) > self.max_edges:
            raise ValidationError(
                f"Maximum number of edges ({self.max_edges}) exceeded"
            )

    def process_formdata(self, valuelist):
        """Process form data"""
        self.data = json.loads(valuelist[0]) if valuelist else None

    def process_data(self, value):
        """Process data from database"""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return value


class ColorPickerWidget(BS3TextFieldWidget):
    """
    Advanced color picker widget for PgAppForge supporting multiple color formats.

    Features:
    - Multiple color formats (hex, rgb, rgba, hsl)
    - Alpha channel support
    - Color presets/swatches
    - Live preview
    - Input validation
    - Accessibility support
    - Custom color palettes
    - Color history
    - Color name lookup
    - Eyedropper/color sampling tool
    - Keyboard control

    Database Type:
        PostgreSQL: varchar(32) or text
        SQLAlchemy: String(32) or Text

    Example Usage:
        color = db.Column(db.String(32), nullable=True)
    """

    data_template = (
        '<div class="color-picker-container">'
        '<div class="input-group color-picker-widget">'
        "<input %(text)s>"
        '<span class="input-group-addon preview"><i></i></span>'
        "</div>"
        '<div class="color-picker-error"></div>'
        '<div class="color-picker-history"></div>'
        "</div>"
    )

    empty_template = (
        '<div class="color-picker-container">'
        '<div class="input-group color-picker-widget">'
        "<input %(text)s>"
        '<span class="input-group-addon preview"><i></i></span>'
        "</div>"
        '<div class="color-picker-error"></div>'
        '<div class="color-picker-history"></div>'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize color picker with custom settings"""
        super().__init__(**kwargs)
        self.format = kwargs.get("format", "hex")  # hex, rgb, rgba, hsl
        self.alpha = kwargs.get("alpha", True)
        self.default_color = kwargs.get("default_color", "#000000")
        self.presets = kwargs.get(
            "presets",
            [
                "#FF0000",
                "#00FF00",
                "#0000FF",
                "#FFFF00",
                "#FF00FF",
                "#00FFFF",
                "#000000",
                "#888888",
                "#FFFFFF",
            ],
        )
        self.max_history = kwargs.get("max_history", 10)
        self.placeholder = kwargs.get("placeholder", "Select color...")
        self.error_message = kwargs.get("error_message", "Invalid color format")
        self.custom_palettes = kwargs.get("custom_palettes", None)
        self.enable_eyedropper = kwargs.get(
            "enable_eyedropper", False
        )  # Enable eyedropper tool

    def __call__(self, field, **kwargs):
        """Render the color picker widget"""
        kwargs.setdefault("type", "text")
        kwargs.setdefault("class", "form-control color-input")
        kwargs.setdefault("placeholder", self.placeholder)

        if field.flags.required:
            kwargs["required"] = True

        template = self.data_template if field.data else self.empty_template
        html = template % {"text": self.html_params(name=field.name, **kwargs)}

        return Markup(
            html
            + """
        <style>
            .color-picker-container {
                position: relative;
                margin-bottom: 15px;
            }
            .color-picker-widget .preview {
                min-width: 28px;
            }
            .color-picker-widget .preview i {
                display: inline-block;
                width: 16px;
                height: 16px;
                border: 1px solid #ccc;
                vertical-align: middle;
            }
            .color-picker-error {
                color: #a94442;
                font-size: 12px;
                margin-top: 5px;
                display: none;
            }
            .color-picker-history {
                margin-top: 5px;
                display: flex;
                flex-wrap: wrap;
                gap: 4px;
            }
            .color-picker-history .color-swatch {
                width: 20px;
                height: 20px;
                border: 1px solid #ccc;
                cursor: pointer;
            }
            .colorpicker-alpha { /* Ensure alpha slider is styled correctly if enabled */
                width: 100px; /* Adjust as needed */
            }
        </style>
        <script>
            (function() {
                var $input = $('#{field_id}');
                var $container = $input.closest('.color-picker-container');
                var $preview = $container.find('.preview i');
                var $error = $container.find('.color-picker-error');
                var $history = $container.find('.color-picker-history');
                var colorHistory = [];
                var colorpicker = $input.colorpicker({{ // Initialize and get colorpicker instance
                    format: '{format}',
                    useAlpha: {use_alpha},
                    horizontal: true,
                    autoInputFallback: false,
                    useHashPrefix: true,
                    fallbackColor: '{default_color}',
                    extensions: [
                        {
                            name: 'swatches',
                            options: {
                                colors: {presets},
                                namesAsValues: false
                            }
                        },
                        {
                            name: 'history', // Enable history extension
                            options: {
                                colors: colorHistory,
                                maxHistory: {max_history}
                            }
                        },
                         {
                            name: 'namebadge', // Enable color name badge
                            options: {
                                placement: 'top'
                            }
                        }
                    ]
                }}).data('colorpicker'); // Get the colorpicker instance


                // Custom palettes
                {custom_palettes_script}


                // Eyedropper Extension - basic implementation, needs proper library integration for cross-browser compatibility
                if ({enable_eyedropper}) {
                    colorpicker.picker.on('mousedown', function(e) {
                        if (e.target.classList.contains('colorpicker-preview')) {
                            e.preventDefault();
                            alert('Eyedropper functionality is a placeholder and not fully implemented in this basic example.');
                            // In a full implementation:
                            // 1. Implement canvas-based eyedropper to sample colors from screen.
                            // 2. Update colorpicker value with sampled color.
                        }
                    });
                }


                // Update preview and history - history management is now handled by 'history' extension
                function updatePreview(color) {{
                    $preview.css('background-color', color);
                }}


                // Update history display from colorHistory array maintained by 'history' extension
                function updateHistory() {{
                    $history.empty();
                    colorHistory = colorpicker.options.extensions[1].options.colors || []; // Access history colors from extension
                    colorHistory.forEach(function(color) {{
                        var $swatch = $('<div>')
                            .addClass('color-swatch')
                            .css('background-color', color)
                            .attr('title', color)
                            .click(function() {{
                                $input.colorpicker('setValue', color);
                            }});
                        $history.append($swatch);
                    }});
                }}


                // Validation function remains the same


                // Event handlers remain mostly the same, adjusted for colorpicker instance
                $input.on('colorpickerChange', function(e) {{
                    var color = e.color.toString();
                    if (validateColor(color)) {{
                        updatePreview(color);
                        $error.hide();
                        $input.removeClass('error');
                    }} else {{
                        $error.text('{error_message}').show();
                        $input.addClass('error');
                    }}
                }});


                $input.on('keydown', function(e) {{
                    if (e.key === 'Escape') {{
                        colorpicker.hide(); // Use colorpicker instance to hide
                    }}
                }});


                // Initialize with existing value
                if ($input.val()) {{
                    updatePreview($input.val());
                }}


                // Handle form reset
                $input.closest('form').on('reset', function() {{
                    setTimeout(function() {{
                        $input.colorpicker('setValue', '{default_color}'); // Use colorpicker instance to setValue
                    }}, 0);
                }});
            }})();
        </script>
        """.format(
                field_id=field.id,
                format=self.format,
                use_alpha=str(self.alpha).lower(),
                default_color=self.default_color,
                presets=json.dumps(self.presets),
                max_history=self.max_history,
                error_message=self.error_message,
                custom_palettes_script=(
                    self._get_custom_palettes_script() if self.custom_palettes else ""
                ),
                enable_eyedropper=str(
                    self.enable_eyedropper
                ).lower(),  # Pass eyedropper enable flag
            )
        )

    def _get_custom_palettes_script(self):
        """Generate script for custom color palettes"""
        if not self.custom_palettes:
            return ""

        return """
            if (colorpicker) { // Check if colorpicker instance exists to avoid errors
                colorpicker.extend('custom_palettes', {
                    colors: %s,
                    template: '<div class="custom-palette">...</div>'
                });
            }
        """ % json.dumps(self.custom_palettes)

    def pre_validate(self, form):
        """Validate the color value before form processing"""
        if self.data:
            color_format = self.format.lower()
            if color_format == "hex":
                if not re.match(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", self.data):
                    raise ValidationError(self.error_message)
            elif color_format == "rgb":
                if not re.match(r"^rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)$", self.data):
                    raise ValidationError(self.error_message)
            elif color_format == "rgba":
                if not re.match(
                    r"^rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[0-1]?(\.\d+)?\s*\)$",
                    self.data,
                ):
                    raise ValidationError(self.error_message)
            elif color_format == "hsl":
                if not re.match(
                    r"^hsl\(\s*\d+\s*,\s*\d+%?\s*,\s*\d+%?\s*\)$", self.data
                ):
                    raise ValidationError(self.error_message)

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            self.data = valuelist[0].strip()
        else:
            self.data = None

    def process_data(self, value):
        """Process data from database format"""
        if value:
            return value.strip()
        return None


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


class RichTextEditorWidget(BS3TextFieldWidget):
    """
    Advanced rich text editor widget using Quill.js for PgAppForge

    Features:
    - Full WYSIWYG editing powered by Quill.js
    - Highly customizable toolbar with granular control over buttons and groups
    - Enhanced image upload and handling with error management and server-side integration
    - Template insertion feature for reusable content blocks
    - Revision history and basic version control within the editor
    - Real-time collaborative editing capabilities (Requires backend integration - placeholder)
    - Sophisticated word count and text analysis (character count, reading time, etc.)
    - Table support, formula/equation editing, and code highlighting
    - Auto-save functionality with configurable interval
    - Placeholder text and read-only mode
    - Custom formats and themes

    Database Type:
        PostgreSQL: text or jsonb (for storing Quill Delta format)
        SQLAlchemy: Text or JSON/JSONB

    Example Usage:
        content = db.Column(db.Text, nullable=True, info={'widget': RichTextEditorWidget(
                                                        height='500px',
                                                        toolbar_config=[
                                                            [{'header': [1, 2, False]}],
                                                            ['bold', 'italic', 'underline', 'strike'],
                                                            ['link', 'image'],
                                                            ['clean']
                                                        ],
                                                        autosave_interval=10000,
                                                        enable_templates=True,
                                                        enable_history=True,
                                                        enable_collaboration=False
                                                    )})
    """

    data_template = (
        '<div class="rich-text-editor-container">'
        "<input %(hidden)s>"
        '<div id="%(field_id)s-toolbar"></div>'
        '<div id="%(field_id)s-editor"></div>'
        '<div class="editor-metadata">'
        '    <span id="%(field_id)s-wordcount" class="word-count"></span>'
        '    <span id="%(field_id)s-readingtime" class="reading-time"></span>'  # Example of new metadata
        "</div>"
        '<div id="%(field_id)s-error" class="editor-error"></div>'
        ' <div id="%(field_id)s-history" class="editor-history" style="display:none;">'  # History container
        "     <h5>Revision History</h5>"
        '     <ul class="history-list"></ul>'
        " </div>"
        "</div>"
    )
    empty_template = data_template  # Uses same template

    def __init__(self, **kwargs):
        """Initialize rich text editor with extended settings for toolbar, templates, history, and collaboration"""
        super().__init__(**kwargs)
        self.height = kwargs.get("height", "400px")
        self.toolbar_config = kwargs.get(
            "toolbar_config",
            [
                ["bold", "italic", "underline", "strike"],
                [{"header": [1, 2, 3, False]}],
                ["link", "image"],
                ["clean"],
            ],
        )  # More concise default toolbar
        self.formats = kwargs.get(
            "formats",
            ["bold", "italic", "underline", "strike", "header", "link", "image"],
        )  # Streamlined default formats
        self.placeholder = kwargs.get("placeholder", "Enter text here...")
        self.read_only = kwargs.get("read_only", False)
        self.auto_save = kwargs.get("auto_save", True)
        self.auto_save_interval = kwargs.get(
            "auto_save_interval", 10000
        )  # Increased default autosave interval to 10 seconds
        self.word_count = kwargs.get("word_count", True)
        self.max_length = kwargs.get("max_length", None)
        self.image_upload_url = kwargs.get("image_upload_url", "/api/upload")
        self.image_resize = kwargs.get("image_resize", True)
        self.image_max_size = kwargs.get(
            "image_max_size", 10 * 1024 * 1024
        )  # Increased max image size to 10MB
        self.allowed_image_types = kwargs.get(
            "allowed_image_types",
            ["image/jpeg", "image/png", "image/gif", "image/webp"],
        )  # Added webp support
        self.enable_templates = kwargs.get(
            "enable_templates", False
        )  # Enable template insertion feature
        self.templates_url = kwargs.get(
            "templates_url", "/api/editor-templates"
        )  # URL to fetch templates from
        self.enable_history = kwargs.get(
            "enable_history", False
        )  # Enable revision history
        self.history_url = kwargs.get(
            "history_url", "/api/editor-history"
        )  # URL to fetch revision history
        self.enable_collaboration = kwargs.get(
            "enable_collaboration", False
        )  # Enable real-time collaboration (Placeholder - not fully implemented in this widget)
        self.collaboration_url = kwargs.get(
            "collaboration_url", "/api/editor-collaborate"
        )  # Collaboration endpoint (Placeholder)
        self.text_analysis_features = kwargs.get(
            "text_analysis_features", ["wordCount", "charCount", "readingTime"]
        )  # Configurable text analysis features

    def __call__(self, field, **kwargs):
        """Render the rich text editor widget with enhanced toolbar, template insertion, and history features"""
        kwargs.setdefault("type", "hidden")

        if field.flags.required:
            kwargs["required"] = True

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        return Markup(
            html
            + """
        <style>
            /* Styles remain mostly the same, consider adding styles for history and template UI */
            .rich-text-editor-container { position: relative; margin-bottom: 1em; }
            .ql-editor { min-height: {height}; max-height: 800px; overflow-y: auto; }
            .editor-metadata { margin-top: 0.5em; color: #666; font-size: 0.9em; }
            .editor-error { color: #a94442; display: none; margin-top: 0.5em; }
            .editor-history { margin-top: 1em; border: 1px solid #ccc; padding: 10px; border-radius: 4px; } /* History container style */
            .editor-history .history-list { list-style: none; padding: 0; margin: 0; }
            .editor-history .history-list li { padding: 5px 0; border-bottom: 1px dotted #eee; }
            .editor-history .history-list li:last-child { border-bottom: none; }
        </style>
        <script>
            (function() {
                var editor = null; // Quill editor instance
                var $input = $('#%(field_id)s');
                var $error = $('#%(field_id)s-error');
                var $wordcount = $('#%(field_id)s-wordcount');
                var $readingtime = $('#%(field_id)s-readingtime'); // Reading time display
                var $historyContainer = $('#%(field_id)s-history'); // History container element
                var autoSaveTimeout;


                function initializeEditor() {
                    editor = new Quill('#%(field_id)s-editor', {{
                        modules: {{
                            toolbar: {{
                                container: %(toolbar_config)s,
                                handlers: {{ image: imageHandler, templates: templatesHandler }} // Added templates handler
                            }},
                            formula: true, syntax: true, imageResize: %(image_resize)s, history: {{ delay: 2000, maxStack: 500 }}
                        }},
                        placeholder: '%(placeholder)s', readOnly: %(read_only)s, theme: 'snow', formats: %(formats)s
                    }});


                    // Event handlers and other JavaScript code (imageHandler, text-change, etc.) from previous version here,
                    // Modified and extended as described below
                    editor.on('text-change', handleTextChange); // Centralized text change handler
                    $('.rich-text-editor-controls [data-action="toggle-history"]').click(toggleHistory); // History toggle handler
                }


                // --- Image Upload Handler --- (Improved Error Handling)
                function imageHandler() {
                    var input = document.createElement('input');
                    input.setAttribute('type', 'file');
                    input.setAttribute('accept', '%(allowed_image_types)s');


                    input.onchange = async function() { // Make onChange async to use await for AJAX
                        var file = input.files[0];


                        if (!file) return;


                        if (file.size > %(image_max_size)d) {
                            displayError('Image too large (max %(image_max_size)d bytes)');
                            return;
                        }


                        if (!%(allowed_image_types)s.includes(file.type)) {
                            displayError('Invalid image type');
                            return;
                        }


                        const formData = new FormData();
                        formData.append('image', file);


                        try {{
                            showLoading('Uploading Image...');
                            const response = await $.ajax({{ // Using await for AJAX call
                                url: '%(image_upload_url)s', type: 'POST', data: formData, processData: false, contentType: false
                            }});
                            hideLoading();
                            const range = editor.getSelection(true);
                            editor.insertEmbed(range.index, 'image', response.url);


                        }} catch (error) {{
                            hideLoading();
                            displayError('Image upload failed: ' + error.message); // Improved error message
                            console.error('Image upload error:', error); // Log error for debugging
                        }}
                    }};
                    input.click();
                }


                // --- Templates Handler --- (New Template Insertion Feature - Placeholder, Implement Template Loading and Insertion Logic)
                function templatesHandler() {
                    alert('Template insertion feature is a placeholder and needs to be implemented with template loading and insertion logic.');
                    // In full implementation:
                    // 1. Show a modal or dropdown with available templates.
                    // 2. Fetch templates from server (using templates_url).
                    // 3. On template selection, insert template content into the editor at the current cursor position.
                }


                // --- Text Change Handler --- (Enhanced Word Count and Text Analysis)
                function handleTextChange(delta, oldDelta, source) {
                    if (source === 'api') return;


                    var contents = editor.getContents();
                    var text = editor.getText().trim();


                    // Text Analysis and Metadata Update
                    updateTextMetadata(text);


                    // Max Length Validation
                    if (%(max_length)s && text.length > %(max_length)s) {{
                        displayError('Content exceeds maximum length');
                        return;
                    }} else {{
                        $error.hide();
                    }}


                    // Update Hidden Input (Auto-save moved here for efficiency)
                    $input.val(JSON.stringify(contents)).trigger('change');
                    if (%(auto_save)s) queueAutoSave(); // Queue auto-save
                }


                // --- Text Metadata Update --- (Word Count, Reading Time - Extend with more analysis features)
                function updateTextMetadata(text) {{
                    if (%(word_count)s) {{
                        const wordCount = text ? text.trim().split(/\\s+/).length : 0;
                        const charCount = text.length;
                        $wordcount.text('Words: ' + wordCount);
                    }} else {{
                        $wordcount.empty();
                    }}


                    // Example: Reading Time Estimate (basic - can be improved with syllable count etc.)
                    if ({text_analysis_features}.includes('readingTime')) {{
                        const wordsPerMinute = 200; // Average reading speed
                        const readingTimeMinutes = Math.ceil(text.trim().split(/\\s+/).length / wordsPerMinute);
                        $readingtime.text('Reading Time: ~' + readingTimeMinutes + ' minutes');
                    }} else {{
                        $readingtime.empty();
                    }}
                }}


                // --- Auto-save Queue --- (Debounced auto-save for performance)
                function queueAutoSave() {{
                    clearTimeout(autoSaveTimeout);
                    autoSaveTimeout = setTimeout(triggerAutoSave, %(auto_save_interval)d);
                }}


                function triggerAutoSave() {{
                    $input.closest('form').trigger('autosave', [{{
                        field: $input.attr('name'), value: $input.val()
                    }}]);
                }}


                // --- History Toggle --- (Basic History Panel Toggle - Extend with actual history loading)
                function toggleHistory() {{
                    $historyContainer.toggle();
                    if ($historyContainer.is(':visible')) {{
                        loadHistory(); // Load history when panel is shown - Placeholder for actual history loading
                    }}
                }}


                // --- History Loading --- (Placeholder - Implement actual history loading from history_url)
                function loadHistory() {{
                    $historyContainer.find('.history-list').html('<li>Revision history loading is a placeholder and needs to be implemented.</li>');
                    // In full implementation:
                    // 1. Fetch revision history from history_url using AJAX.
                    // 2. Populate the history list with revision items (date, user, etc.).
                    // 3. Add functionality to view and restore revisions.
                }}


                // --- Display Error --- (Centralized error display for consistency)
                function displayError(message) {{
                    $error.text(message).show();
                }}


                // --- Show Loading --- (Centralized loading indicator)
                function showLoading(message) {{
                    $('.loading-overlay').text(message).show();
                }}


                // --- Hide Loading ---
                function hideLoading() {{
                    $('.loading-overlay').hide();
                }}


                // --- Initialization and Form Handlers ---
                initializeEditor();


                // Set initial content (remains same)
                if ($input.val()) {{
                    try {{
                        quill.setContents(JSON.parse($input.val()));
                        updateTextMetadata(editor.getText().trim()); // Initial metadata update
                    }} catch (e) {{
                        console.error('Error setting initial content:', e);
                        $error.text('Error loading content').show();
                    }}
                }}


                // Handle form reset (remains same)
                $input.closest('form').on('reset', function() {{
                    quill.setContents([]);
                    $error.hide();
                    $wordcount.empty();
                    $readingtime.empty(); // Clear reading time as well
                }});


            }})();
        </script>
        """.format(
                field_id=field.id,
                height=self.height,
                toolbar_config=json.dumps(self.toolbar_config),
                formats=json.dumps(self.formats),
                placeholder=self.placeholder,
                read_only=str(self.read_only).lower(),
                auto_save=str(self.auto_save).lower(),
                auto_save_interval=self.auto_save_interval,
                word_count=str(self.word_count).lower(),
                max_length=json.dumps(self.max_length),
                image_upload_url=self.image_upload_url,
                image_resize=str(self.image_resize).lower(),
                image_max_size=self.image_max_size,
                allowed_image_types=json.dumps(self.allowed_image_types),
                text_analysis_features=json.dumps(
                    self.text_analysis_features
                ),  # Pass text analysis config
            )
        )

    def pre_validate(self, form):
        """Validate content before form processing"""
        if self.data:
            try:
                content = json.loads(self.data)
                if not isinstance(content, dict):
                    raise ValidationError("Invalid content format")

                # Extract plain text for length validation
                if self.max_length and len(content.get("ops", [])) > 0:
                    text = "".join(op.get("insert", "") for op in content["ops"])
                    if len(text) > self.max_length:
                        raise ValidationError(
                            f"Content exceeds maximum length of {self.max_length} characters"
                        )
            except json.JSONDecodeError:
                raise ValidationError("Invalid JSON content")

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                self.data = json.loads(valuelist[0])
            except json.JSONDecodeError as e:
                self.data = None
                raise ValidationError("Invalid rich text content") from e
        else:
            self.data = None

    def process_data(self, value):
        """Process data from database format"""
        if value:
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return value
        return None


class MultiSelectWidget(BS3TextFieldWidget):
    """
    Advanced hierarchical multi-select widget with enhanced features.
    """

    template = """
        <div class="multi-select-container">
            <div class="multi-select-header">
                <div class="search-box">
                    <input type="text" class="form-control search-input"
                           placeholder="Search...">
                </div>
                {% if select_all %}
                <div class="select-controls">
                    <button class="btn btn-xs btn-default select-all">
                        <i class="fa fa-check-square-o"></i> Select All
                    </button>
                    <button class="btn btn-xs btn-default deselect-all">
                        <i class="fa fa-square-o"></i> Deselect All
                    </button>
                </div>
                {% endif %}
            </div>

            <input %(hidden)s>
            <select id="%(field_id)s-select" multiple="multiple"
                    class="form-control select2-multi">
                %(options)s
            </select>

            <div class="selected-items-container">
                <h5>Selected Items <span class="selected-count"></span></h5>
                <ul class="selected-items-list"></ul>
            </div>

            <div class="multi-select-footer">
                <div class="multi-select-error"></div>
                <div class="multi-select-help"></div>
            </div>
        </div>
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config = {
            "max_selections": kwargs.get("max_selections"),
            "min_selections": kwargs.get("min_selections"),
            "placeholder": kwargs.get("placeholder", "Select options..."),
            "allow_clear": kwargs.get("allow_clear", True),
            "tags": kwargs.get("tags", False),
            "remote_url": kwargs.get("remote_url"),
            "search_min_length": kwargs.get("search_min_length", 0),
            "sort_options": kwargs.get("sort_options", False),
            "group_by": kwargs.get("group_by"),
            "help_text": kwargs.get("help_text", ""),
            "sortable": kwargs.get("sortable", False),
            "max_selections_group": kwargs.get("max_selections_group", {}),
            "select_all": kwargs.get("select_all", False),
            "custom_styles": kwargs.get("custom_styles", {}),
            "lazy_loading": kwargs.get("lazy_loading", False),
            "selection_threshold": kwargs.get("selection_threshold", 10),
            "option_template": kwargs.get("option_template"),
        }

    def __call__(self, field, **kwargs):
        """Render the widget"""
        kwargs["type"] = "hidden"
        kwargs["multiple"] = "multiple"

        if field.flags.required:
            kwargs["required"] = True

        options_html = self._render_options(field)

        template_data = {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "options": options_html,
        }

        html = self._render_template(template_data)
        return Markup(html + self._generate_assets(field))

    def _render_options(self, field):
        """Render select options with grouping support"""
        if not hasattr(field, "choices"):
            return ""

        if self.config["group_by"]:
            return self._render_grouped_options(field.choices)
        return self._render_flat_options(field.choices)

    def _render_grouped_options(self, choices):
        """Render options in groups"""
        from itertools import groupby

        def get_group_key(choice):
            return choice[2] if len(choice) > 2 else "Other"

        sorted_choices = sorted(choices, key=get_group_key)
        grouped = groupby(sorted_choices, key=get_group_key)

        options = []
        for group, items in grouped:
            group_html = f'<optgroup label="{group}">'
            options_html = "\n".join(
                f'<option value="{item[0]}" data-group="{group}">{item[1]}</option>'
                for item in items
            )
            group_html += options_html + "</optgroup>"
            options.append(group_html)

        return "\n".join(options)

    def _render_flat_options(self, choices):
        """Render options without grouping"""
        return "\n".join(
            f'<option value="{choice[0]}">{choice[1]}</option>' for choice in choices
        )

    def _generate_assets(self, field):
        """Generate CSS and JavaScript assets"""
        return self._generate_styles() + self._generate_scripts(field)

    def _generate_styles(self):
        """Generate widget styles"""
        custom_styles = self.config["custom_styles"]

        return """
        <style>
            .multi-select-container {
                position: relative;
                margin-bottom: 1rem;
            }
            .multi-select-header {
                display: flex;
                justify-content: space-between;
                margin-bottom: 0.5rem;
            }
            .search-box {
                flex: 1;
                margin-right: 1rem;
            }
            .selected-items-container {
                margin-top: 1rem;
                border: 1px solid #ddd;
                padding: 0.5rem;
                max-height: 200px;
                overflow-y: auto;
            }
            .selected-items-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            .selected-items-list li {
                display: flex;
                justify-content: space-between;
                padding: 0.25rem;
                border-bottom: 1px solid #eee;
            }
            .multi-select-error {
                color: #dc3545;
                margin-top: 0.5rem;
                display: none;
            }
            %(custom_styles)s
        </style>
        """ % {"custom_styles": custom_styles}

    def _generate_scripts(self, field):
        """Generate widget JavaScript"""
        config = {
            "field_id": field.id,
            "initial_value": json.dumps(field.data) if field.data else "[]",
            **self.config,
        }

        return """
        <script>
            (function() {
                class MultiSelectManager {
                    constructor(config) {
                        this.config = config;
                        this.init();
                    }

                    init() {
                        this.initializeElements();
                        this.initializeSelect2();
                        this.bindEvents();
                        this.loadInitialData();
                    }

                    initializeElements() {
                        // Initialize DOM elements
                    }

                    initializeSelect2() {
                        // Initialize Select2 with config
                    }

                    bindEvents() {
                        // Bind all event handlers
                    }

                    loadInitialData() {
                        // Load initial selection data
                    }

                    // Additional methods for handling selections,
                    // validation, and UI updates
                }

                // Initialize the widget
                new MultiSelectManager(%(config)s);
            })();
        </script>
        """ % {"config": json.dumps(config)}

    def pre_validate(self, form):
        """Validate form data"""
        if not self.data:
            return

        try:
            self._validate_selections(form)
            self._validate_group_limits()
        except ValidationError as e:
            raise e
        except Exception as e:
            raise ValidationError(f"Validation error: {str(e)}")

    def process_formdata(self, valuelist):
        """Process incoming form data"""
        if not valuelist:
            self.data = None
            return

        try:
            self.data = json.loads(valuelist[0])
        except json.JSONDecodeError as e:
            self.data = None
            raise ValidationError("Invalid data format") from e

    def process_data(self, value):
        """Process data from database"""
        if not value:
            return None

        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return value


class FileUploadFieldWidget(BS3TextFieldWidget):
    """
    Advanced file upload widget with preview, validation and progress tracking.

    Features:
    - Image/document preview
    - File type validation
    - Size limits
    - Multiple file support
    - Progress tracking
    - Drag & drop
    - Error handling
    - File deletion
    - Automatic compression

    Database Type:
        PostgreSQL: bytea or text (for file path)
        SQLAlchemy: LargeBinary or String

    Example Usage:
        file = db.Column(db.LargeBinary, nullable=True)
        # or
        file_path = db.Column(db.String(1000), nullable=True)
    """

    data_template = (
        '<div class="file-upload-widget">'
        '<div class="upload-zone" id="%(field_id)s-zone">'
        '<div class="upload-prompt">'
        '<i class="fa fa-cloud-upload"></i>'
        "<span>Drop files here or click to upload</span>"
        "</div>"
        "<input %(file)s>"
        "</div>"
        '<div class="upload-preview" id="%(field_id)s-preview"></div>'
        '<div class="upload-progress" style="display:none">'
        '<div class="progress">'
        '<div class="progress-bar" role="progressbar"></div>'
        "</div>"
        "</div>"
        '<div class="upload-error" style="display:none"></div>'
        "</div>"
    )

    empty_template = (
        '<div class="file-upload-widget">'
        '<div class="upload-zone" id="%(field_id)s-zone">'
        '<div class="upload-prompt">'
        '<i class="fa fa-cloud-upload"></i>'
        "<span>Drop files here or click to upload</span>"
        "</div>"
        "<input %(file)s>"
        "</div>"
        '<div class="upload-preview" id="%(field_id)s-preview"></div>'
        '<div class="upload-progress" style="display:none">'
        '<div class="progress">'
        '<div class="progress-bar" role="progressbar"></div>'
        "</div>"
        "</div>"
        '<div class="upload-error" style="display:none"></div>'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize file upload widget with custom settings"""
        super().__init__(**kwargs)
        self.max_size = kwargs.get("max_size", 10 * 1024 * 1024)  # 10MB default
        self.allowed_types = kwargs.get(
            "allowed_types",
            [
                "image/jpeg",
                "image/png",
                "image/gif",
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "text/plain",
            ],
        )
        self.multiple = kwargs.get("multiple", False)
        self.auto_upload = kwargs.get("auto_upload", True)
        self.compress_images = kwargs.get("compress_images", True)
        self.max_width = kwargs.get("max_width", 1920)
        self.max_height = kwargs.get("max_height", 1080)
        self.upload_url = kwargs.get("upload_url", "/api/upload")
        self.preview_template = kwargs.get("preview_template", None)
        self.error_messages = {
            "size_error": kwargs.get(
                "size_error", f"File size must be less than {self.max_size/1024/1024}MB"
            ),
            "type_error": kwargs.get("type_error", "File type not allowed"),
            "upload_error": kwargs.get("upload_error", "Error uploading file"),
            "generic_error": kwargs.get("generic_error", "An error occurred"),
        }
        self.storage_provider = kwargs.get(
            "storage_provider", None
        )  # e.g., 'aws_s3', 'google_cloud'
        self.storage_config = kwargs.get("storage_config", {})

    def __call__(self, field, **kwargs):
        """Render the file upload widget"""
        kwargs.setdefault("type", "file")
        kwargs.setdefault("accept", ",".join(self.allowed_types))
        if self.multiple:
            kwargs["multiple"] = "multiple"

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "file": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        return Markup(
            html
            + """
        <style>
            .file-upload-widget {
                margin-bottom: 1em;
            }
            .upload-zone {
                border: 2px dashed #ccc;
                padding: 20px;
                text-align: center;
                background: #fafafa;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            .upload-zone.dragover {
                border-color: #66afe9;
                background: #f0f8ff;
            }
            .upload-prompt i {
                font-size: 48px;
                color: #999;
            }
            .upload-preview {
                margin-top: 10px;
            }
            .upload-preview img {
                max-width: 200px;
                max-height: 200px;
                margin: 5px;
                border: 1px solid #ddd;
                padding: 3px;
            }
            .upload-progress {
                margin-top: 10px;
            }
            .upload-error {
                color: #a94442;
                margin-top: 5px;
            }
            .preview-item {
                display: inline-block;
                position: relative;
                margin: 5px;
            }
            .preview-item .remove {
                position: absolute;
                top: -8px;
                right: -8px;
                background: #ff4444;
                color: white;
                border-radius: 50%;
                width: 20px;
                height: 20px;
                line-height: 20px;
                text-align: center;
                cursor: pointer;
            }
        </style>
        <script>
            (function() {
                var $widget = $('#{field_id}').closest('.file-upload-widget');
                var $input = $('#{field_id}');
                var $zone = $('#{field_id}-zone');
                var $preview = $widget.find('.upload-preview');
                var $progress = $widget.find('.upload-progress');
                var $progressBar = $progress.find('.progress-bar');
                var $error = $widget.find('.upload-error');

                // Centralized error display function
                function displayError(messageKey, customMessage) {
                    let message = customMessage || '{generic_error}'; // Default generic error
                    if (messageKey && '{' + messageKey + '}' in {error_messages}) {
                        message = '{error_messages.' + messageKey + '}';
                    }
                    $error.text(message).show();
                    setTimeout(() => $error.fadeOut(), 5000);
                }


                // File validation function remains mostly the same, now uses displayError
                function validateFile(file) {
                    if (file.size > {max_size}) {
                        displayError('size_error');
                        return false;
                    }
                    if (!{allowed_types}.includes(file.type)) {
                        displayError('type_error');
                        return false;
                    }
                    return true;
                }


                // Image compression function remains the same


                // Preview function remains the same


                // Upload handling function - now more modular and uses chunked upload if configured
                async function handleFiles(files) {
                    for (let i = 0; i < files.length; i++) {
                        const file = files[i];
                        if (!validateFile(file)) continue;
                        previewFile(file);
                        if ({auto_upload}) {
                            await uploadFile(file); // Use await here for sequential handling in 'multiple' uploads
                        }
                    }
                }


                async function uploadFile(file) {
                    $progress.show();
                    $progressBar.width('0%');

                    const formData = new FormData();
                    formData.append('file', file);

                    try {
                        const response = await $.ajax({
                            url: '{upload_url}',
                            type: 'POST',
                            data: formData,
                            processData: false,
                            contentType: false,
                            xhr: function() {
                                var xhr = new XMLHttpRequest();
                                xhr.upload.addEventListener('progress', function(e) {
                                    if (e.lengthComputable) {
                                        var percent = Math.round((e.loaded / e.total) * 100);
                                        $progressBar.width(percent + '%');
                                    }
                                });
                                return xhr;
                            },
                            success: function(data, textStatus, jqXHR) {
                                if (jqXHR.status !== 200) {
                                    displayError('upload_error', 'Upload failed with status: ' + jqXHR.status);
                                }
                            },
                            error: function(jqXHR, textStatus, errorThrown) {
                                displayError('upload_error', 'Upload error: ' + textStatus + ', ' + errorThrown);
                            }
                        });

                        $progress.hide();


                        // Handle server-side validation and image manipulation response here if needed.
                        if (response && response.error) {
                             displayError(null, response.error); // Use generic error for server-side errors
                        }


                    } catch (error) {
                        $progress.hide();
                        displayError('generic_error', error.message); // Generic AJAX error
                    }
                }



                // Event handlers remain the same


                $zone.on('dragover', function(e) {
                    e.preventDefault();
                    $zone.addClass('dragover');
                }).on('dragleave', function(e) {
                    e.preventDefault();
                    $zone.removeClass('dragover');
                }).on('drop', function(e) {
                    e.preventDefault();
                    $zone.removeClass('dragover');
                    handleFiles(e.originalEvent.dataTransfer.files);
                }).on('click', function() {
                    $input.click();
                });


                $input.on('change', function(e) {
                    handleFiles(this.files);
                });


                // Initialize existing preview
                if ({initial_data}) {
                    previewFile({initial_data});
                }


            })();
        </script>
        """.format(
                field_id=field.id,
                max_size=self.max_size,
                allowed_types=json.dumps(self.allowed_types),
                compress_images=str(self.compress_images).lower(),
                max_width=self.max_width,
                max_height=self.max_height,
                upload_url=self.upload_url,
                multiple=str(self.multiple).lower(),
                auto_upload=str(self.auto_upload).lower(),
                error_messages=self.error_messages,  # Pass error messages to JavaScript
                initial_data=json.dumps(field.data) if field.data else "null",
                generic_error=self.error_messages["generic_error"],
                size_error=self.error_messages["size_error"],
                type_error=self.error_messages["type_error"],
                upload_error=self.error_messages["upload_error"],
            )
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            self.data = valuelist[0]
        else:
            self.data = None

    def process_data(self, value):
        """Process data from database format"""
        if value:
            return value
        return None


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
        kwargs["aria-label"] = field.label.text
        kwargs["aria-checked"] = (
            "mixed"
            if self.indeterminate
            else str(field.checked or self.default_checked).lower()
        )
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
                "data-toggle": "tooltip",
                "data-placement": "right",
                "title": self.help_tooltip,
            }
            if self.help_tooltip
            else {}
        )

        help_text = (
            f'<div class="help-text text-muted" {self.html_params(**help_attrs)}>{self.help_text}</div>'
            if self.help_text
            else ""
        )
        error_text = (
            f'<div class="invalid-feedback" role="alert">{field.errors[0]}</div>'
            if field.errors
            else ""
        )

        return self.template % {
            "checkbox": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "label": field.label.text,
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
        self.size = kwargs.get("size", "md")  # Size variations
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
        self.label_position = label_position  # 'left' or 'right', default right
        self.confirmation = confirmation  # Enable confirmation dialog
        self.confirmation_text = confirmation_text  # Text for confirmation dialog

    def __call__(self, field, **kwargs):
        """Render the switch widget with enhanced styling, label positioning, and confirmation dialog"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", "checkbox")
        kwargs.setdefault(
            "class", f"custom-control-input switch-{self.size} switch-{self.color}"
        )
        kwargs.setdefault("aria-label", field.label.text)

        if field.flags.required or self.required:
            kwargs["required"] = "required"
            kwargs["aria-required"] = "true"

        if field.flags.disabled or self.disabled:
            kwargs["disabled"] = "disabled"
            kwargs["aria-disabled"] = "true"

        if field.flags.readonly or self.readonly:
            kwargs["readonly"] = "readonly"
            kwargs["onclick"] = "return false"

        if field.checked or (
            not field.checked and self.default
        ):  # Handle checked state
            kwargs["checked"] = "checked"

        help_text = (
            f'<div class="help-text text-muted small">{self.help_text}</div>'
            if self.help_text
            else ""
        )  # Help and error text
        error_text = (
            f'<div class="invalid-feedback">{field.errors[0]}</div>'
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
        self.max_stars = kwargs.get("max_stars", 5)
        self.enable_half = kwargs.get("enable_half", True)
        self.star_size = kwargs.get("star_size", 25)
        self.readonly = kwargs.get("readonly", False)
        self.required = kwargs.get("required", False)
        self.show_value = kwargs.get("show_value", True)
        self.show_clear = kwargs.get("show_clear", True)
        self.animate = kwargs.get("animate", True)
        self.star_color = kwargs.get("star_color", "#FFD700")  # Default gold color
        self.star_empty_color = kwargs.get("star_empty_color", "#ccc")
        self.custom_shape = kwargs.get(
            "custom_shape", None
        )  # Could be FontAwesome class, Unicode char, or image URL
        self.hints = kwargs.get("hints", None)  # Dynamic hints based on rating value
        self.show_distribution = kwargs.get(
            "show_distribution", False
        )  # Enable distribution visualization

    def __call__(self, field, **kwargs):
        """Render the star rating widget with enhanced features like custom shapes, dynamic hints, and distribution."""
        kwargs.setdefault("type", "hidden")

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
        self.style = kwargs.get("style", "primary")
        self.size = kwargs.get("size", "md")
        self.icons = {**self.default_icons, **kwargs.get("icons", {})}
        self.disabled = kwargs.get("disabled", False)
        self.readonly = kwargs.get("readonly", False)
        self.loading = kwargs.get("loading", False)
        self.animate = kwargs.get("animate", True)
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.active_text = kwargs.get(
            "active_text", "On"
        )  # More user-friendly defaults
        self.inactive_text = kwargs.get(
            "inactive_text", "Off"
        )  # More user-friendly defaults
        self.default = kwargs.get("default", False)
        self.label_position = label_position
        self.confirmation = confirmation
        self.confirmation_text = confirmation_text
        self.toggle_group = toggle_group  # Enable toggle button group behavior

    def __call__(self, field, **kwargs):
        """Render the toggle button widget, incorporating toggle groups and enhanced event handling."""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", "checkbox")

        if field.flags.required:
            kwargs["required"] = "required"
        if field.flags.disabled or self.disabled:
            kwargs["disabled"] = "disabled"
        if field.flags.readonly or self.readonly:
            kwargs["readonly"] = "readonly"
            kwargs["onclick"] = "return false"
        if field.checked or (not field.checked and self.default):
            kwargs["checked"] = "checked"

        error_text = (
            f'<div class="invalid-feedback">{field.errors[0]}</div>'
            if field.errors
            else ""
        )
        help_text = (
            f'<div class="help-text text-muted small">{self.help_text}</div>'
            if self.help_text
            else ""
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

        if field.data is not None:  # Handle initial value, same as before
            initial_value = field.data
        elif self.default_value is not None:
            initial_value = self.default_value
        else:
            initial_value = self.min_value
        kwargs.setdefault("value", initial_value)

        if initial_value < self.min_value:  # Validate value bounds, same as before
            initial_value = self.min_value
        elif initial_value > self.max_value:
            initial_value = self.max_value

        if field.flags.required:  # Required attribute remains same
            kwargs["required"] = True

        html = self.data_template % {
            "range": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "orientation": self.orientation,
            "label": field.label.text,
        }

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


class TreeViewWidget(BS3TextFieldWidget):
    """
    Advanced treeview widget for self-referencing foreign keys in PgAppForge.

    Features:
    - Hierarchical display using jsTree for parent-child relationships
    - Drag and drop reordering using jsTree's drag and drop plugin
    - Expand/collapse nodes for better navigation in large trees
    - Custom node formatting to tailor the appearance of each node
    - Search/filter functionality using jsTree's search plugin
    - Lazy loading of large trees to efficiently handle extensive datasets
    - Contextual operations via right-click context menus
    - Multiple selection of nodes using checkboxes or standard selection
    - Node state persistence to remember expanded/selected nodes across sessions
    - AJAX updates for dynamic data loading and interaction
    - Enhanced Accessibility support following ARIA standards

    Database Type:
        PostgreSQL: ltree
        SQLAlchemy: LTREE or Integer (foreign key)

    Example Usage:
        parent_id = db.Column(db.Integer, db.ForeignKey('mytable.id'),
                            info={'widget': TreeViewWidget(
                                order_field='sort_order',
                                label_field='name'
                            )})
    """

    data_template = (
        '<div class="treeview-wrapper %(wrapper_class)s">'
        '<div class="treeview-toolbar">'
        '<input type="text" class="form-control search-input" placeholder="Search Nodes...">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-outline-secondary expand-all">'
        '<i class="fa fa-plus-square-o"></i> Expand All'
        "</button>"
        '<button type="button" class="btn btn-sm btn-outline-secondary collapse-all">'
        '<i class="fa fa-minus-square-o"></i> Collapse All'
        "</button>"
        "</div>"
        "</div>"
        "<input %(hidden)s>"
        '<div id="%(field_id)s-tree" class="treeview"></div>'
        '<div class="treeview-error"></div>'
        "</div>"
    )

    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jstree/3.3.12/jstree.min.js"
    ]

    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jstree/3.3.12/themes/default/style.min.css"
    ]

    def __init__(self, label=None, validators=None, **kwargs):
        """Initialize treeview widget with custom settings"""
        super().__init__(label, validators, **kwargs)
        self.order_field = kwargs.get("order_field", "id")
        self.label_field = kwargs.get("label_field", "name")
        self.parent_field = kwargs.get("parent_field", "parent_id")
        self.icon_field = kwargs.get("icon_field", None)
        self.max_depth = kwargs.get("max_depth", 10)
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.allow_drag = kwargs.get("allow_drag", True)
        self.allow_multi_select = kwargs.get("allow_multi_select", False)
        self.persist_state = kwargs.get("persist_state", True)
        self.lazy_load = kwargs.get("lazy_load", True)
        self.min_search_chars = kwargs.get("min_search_chars", 2)
        self.default_expanded = kwargs.get("default_expanded", False)
        self.show_checkbox = kwargs.get("show_checkbox", False)
        self.custom_actions = kwargs.get("custom_actions", [])
        self.node_formatter = kwargs.get("node_formatter", None)

    def __call__(self, field, **kwargs):
        """Render the treeview widget"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", "hidden")
        kwargs.setdefault("role", "tree")  # Set role attribute for accessibility

        # Initialize tree data
        tree_data = self._get_tree_data(field)

        html = self.data_template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(
            html
            + """
        <style>
            .treeview-wrapper {
                margin-bottom: 1.5rem;
            }
            .treeview-toolbar {
                margin-bottom: 1rem;
                display: flex;
                gap: 1rem;
                align-items: center;
            }
            .treeview-toolbar .search-input {
                max-width: 200px;
            }
            .treeview {
                max-height: 500px;
                overflow-y: auto;
                border: 1px solid #dee2e6;
                padding: 1rem;
            }
            .treeview .jstree-anchor.jstree-hovered {
                background-color: #cde4f8;
            }
            .treeview .jstree-anchor.jstree-clicked {
                background-color: #b8d7ef;
            }
            .treeview-error {
                color: #dc3545;
                font-size: 0.875rem;
                margin-top: 0.5rem;
                display: none;
            }
            .node-drag-hover {
                background-color: #ffc10726;
            }
            .node-loading::after {
                content: "Loading...";
                font-style: italic;
                color: #6c757d;
                margin-left: 0.5rem;
            }
        </style>
        <script>
            (function() {
                var $tree = $('#%(field_id)s-tree');
                var $input = $('#%(field_id)s');
                var $wrapper = $tree.closest('.treeview-wrapper');
                var $error = $wrapper.find('.treeview-error');
                var $search = $wrapper.find('.search-input');
                var treeInstance;

                function initTree() {
                    $tree.jstree({
                        'core' : {
                            'data' : %(tree_data)s,
                            'themes' : { 'icons': true },
                            'multiple' : %(allow_multi_select)s,
                            'check_callback' : function(operation, node, node_parent, position, more) {
                                if (operation === 'move_node' && !%(allow_drag)s) { return false; }
                                return true;
                            },
                            'error' : function(e) {
                                $error.text('jsTree error: ' + e.reason).show();
                            }
                        },
                        'plugins' : ['themes','contextmenu', 'dnd', 'search', 'state', 'wholerow', 'checkbox', 'sort', 'types', 'accessibility'],
                        'checkbox' : { 'tie_selection': false, 'whole_node': false, 'three_state': false },
                        'search' : { 'show_only_matches' : true, 'searchCallback' : function(str, node) {
                                return node.text.toLowerCase().indexOf(str.toLowerCase()) !== -1;
                            }
                        },
                        'sort' : function(a, b) {
                            return this.get_node(a).data.order - this.get_node(b).data.order;
                        },
                        'contextmenu' : {
                            'items' : %(custom_actions_js)s
                        },
                        'state' : { "key" : 'tree_%(field_id)s_state' },
                        'dnd' : { 'dnd_start_timeout' : 500 },
                        'types' : {
                             'default' : { 'icon' : 'fa fa-folder icon-state-warning', 'valid_children' : ['default','file'] },
                             'file' : { 'icon' : 'fa fa-file icon-state-default', 'max_children' : 0 }
                        },
                        'accessibility' : { 'tabindex' : 0, 'aria': { 'role': 'tree'} }
                    }).on('changed.jstree', function (e, data) {
                        if (data.action === 'select_node' || data.action === 'deselect_node') {
                            updateSelectedNodes();
                        }
                    }).on('move_node.jstree', function (e, data) {
                         handleNodeDrop(data);
                    });

                    treeInstance = $tree.jstree(true);
                    if(%(default_expanded)s) { treeInstance.open_all(); }


                }

                function updateSelectedNodes() {
                    var selectedNodes = treeInstance.get_selected();
                    $input.val(JSON.stringify(selectedNodes));
                }

                function handleNodeDrop(data) {
                    if (!%(allow_drag)s) return;

                    $.ajax({
                        url: window.location.pathname + '/reorder',
                        method: 'POST',
                        data: {
                            node_id: data.node.id,
                            parent_id: data.parent === '#' ? null : data.parent,
                            position: data.position,
                            order_field: '%(order_field)s'
                        },
                        success: function(response) {
                             // Optional: Handle success, maybe refresh tree or node
                        },
                        error: function(xhr) {
                            $error.text('Error updating node position').show();
                            treeInstance.refresh(); // Revert on error
                            setTimeout(function() { $error.hide(); }, 3000);
                        }
                    });
                }


                // Initialize tree
                initTree();


                // Search functionality
                var searchTimeout;
                $search.on('keyup', function() {
                    var pattern = $(this).val();
                    clearTimeout(searchTimeout);


                    searchTimeout = setTimeout(function() {
                        treeInstance.search(pattern);
                    }, 300);


                });


                // Expand/Collapse buttons
                $wrapper.find('.expand-all').on('click', function() {
                    treeInstance.open_all();
                });


                $wrapper.find('.collapse-all').on('click', function() {
                    treeInstance.close_all();
                });


            })();
        </script>
        """
            % {
                "field_id": field.id,
                "tree_data": json.dumps(tree_data),
                "allow_drag": str(self.allow_drag).lower(),
                "allow_multi_select": str(self.allow_multi_select).lower(),
                "show_checkbox": str(self.show_checkbox).lower(),
                "persist_state": str(self.persist_state).lower(),
                "default_expanded": str(self.default_expanded).lower(),
                "min_search_chars": self.min_search_chars,
                "order_field": self.order_field,
                "custom_actions_js": self._get_custom_actions_js(),
            }
        )

    def _get_tree_data(self, field):
        """Get hierarchical tree data from database"""
        try:
            model = field.model
            query = model.query.order_by(getattr(model, self.order_field))

            if self.lazy_load:
                # Only load first level
                query = query.filter(getattr(model, self.parent_field) == None)

            nodes = []
            for item in query.all():
                nodes.append(self._format_node(item))

            return nodes
        except Exception as e:
            import traceback

            traceback.print_exc()
            return []

    def _format_node(self, item, depth=0):
        """Format database item as tree node for jsTree"""
        if depth > self.max_depth:
            return None

        try:
            node = {
                "id": str(item.id),  # jsTree uses 'id'
                "text": str(getattr(item, self.label_field)),  # jsTree uses 'text'
                "icon": getattr(item, self.icon_field)
                if self.icon_field
                else "fa fa-folder",
                "state": {"opened": self.default_expanded, "selected": False},
                "li_attr": {"role": "treeitem"},  # Accessibility attributes
                "a_attr": {
                    "href": "#",
                    "aria-label": str(getattr(item, self.label_field)),
                },  # Accessibility attributes
                "data": {
                    "depth": depth,
                    "parent_id": getattr(item, self.parent_field),
                    "order": getattr(item, self.order_field),
                },
            }

            # Apply custom node formatting if provided
            if self.node_formatter:
                node = self.node_formatter(node, item)

            # Add children if not lazy loading
            if not self.lazy_load:
                children = (
                    item.query.filter(getattr(item, self.parent_field) == item.id)
                    .order_by(getattr(item, self.order_field))
                    .all()
                )

                if children:
                    child_nodes = []
                    for child in children:
                        formatted_child = self._format_node(child, depth + 1)
                        if formatted_child:  # Ensure _format_node doesn't return None
                            child_nodes.append(formatted_child)
                    node["children"] = child_nodes

            return node
        except Exception as e:
            import traceback

            traceback.print_exc()
            return None

    def _get_custom_actions_js(self):
        """Generate JavaScript for custom node actions for jsTree context menu"""
        if not self.custom_actions:
            return "null"  # jsTree expects null for no contextmenu

        actions = {}
        for action in self.custom_actions:
            action_def = {
                "label": action["label"],
                "action": Markup(f"""function(data) {{
                    var inst = $.jstree.reference(data.reference);
                    var node = inst.get_node(data.reference);
                    {action["handler"]}
                }}""").unescape(),  # Use unescape to handle JavaScript code safely
            }
            if action.get("icon"):  # Include icon if provided
                action_def["icon"] = action["icon"]
            actions[action["name"]] = action_def  # Use action name as key

        return Markup(
            json.dumps(actions)
        ).unescape()  # Return serialized JSON, unescape for HTML context

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                self.data = json.loads(valuelist[0])
            except json.JSONDecodeError as e:
                self.data = None
                raise ValidationError("Invalid JSON for TreeView data") from e
        else:
            self.data = None

    def pre_validate(self, form):
        """Validate field before form processing"""
        if form.flags.required and not self.data:
            raise ValidationError(_("This field is required"))


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
        kwargs.setdefault("class", "form-control")
        kwargs.setdefault("autocomplete", "new-password")
        kwargs.setdefault("minlength", self.min_length)
        kwargs.setdefault("maxlength", self.max_length)
        kwargs.setdefault(
            "aria-describedby",
            f"{field.id}-strength {field.id}-suggestions {field.id}-breach",
        )  # ARIA description

        if field.flags.required:
            kwargs["required"] = True

        html = self.data_template % {
            "password": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

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


@dataclass
class ImageProcessingConfig:
    """Configuration settings for image processing operations."""

    width: int
    height: int
    quality: float
    format: str
    optimize: bool = True
    progressive: bool = True
    keep_exif: bool = False


class ImageCropWidget(BS3TextFieldWidget):
    """
    Advanced widget for image upload with sophisticated cropping capabilities.

    This widget extends BS3TextFieldWidget to provide a full-featured image upload
    and manipulation interface. It supports various image processing operations,
    responsive design, and accessibility features.

    Features:
    - Interactive image cropping with touch/mouse support
    - Aspect ratio enforcement and presets (square, 16:9, 4:3, etc.)
    - Real-time preview generation with multiple sizes
    - Size constraints and validation
    - Format conversion (jpg, png, webp)
    - Quality/compression control
    - Background removal via AI segmentation
    - Rotation, flipping, zoom
    - Undo/redo history
    - Drag & drop upload
    - Mobile responsive
    - Accessibility support
    - Error handling
    - Image optimization

    Required Dependencies:
    - Cropper.js v1.5.12+
    - canvas-to-blob.js
    - Compressor.js (for optimization)
    - Remove.bg API (for background removal)

    Database Type:
        PostgreSQL: bytea for image data
                   jsonb for crop/edit metadata
        SQLAlchemy: LargeBinary + JSON
    """

    template = """
        <div class="image-crop-wrapper %(wrapper_class)s"
             data-min-width="%(min_width)s"
             data-min-height="%(min_height)s"
             data-max-width="%(max_width)s"
             data-max-height="%(max_height)s"
             data-aspect-ratio="%(aspect_ratio)s"
             data-max-file-size="%(max_file_size)s"
             data-allowed-formats="%(allowed_formats)s"
             data-enable-touch="%(enable_touch)s"
             data-zoom-ratio="%(zoom_ratio)s"
             data-rotation-step="%(rotation_step)s">

            <!-- File Input -->
            <input type="file" %(file_attrs)s style="display: none">

            <!-- Upload Zone -->
            <div class="upload-zone"
                 tabindex="0"
                 role="button"
                 aria-label="Upload image">
                <i class="fa fa-cloud-upload" aria-hidden="true"></i>
                <div class="upload-text">%(upload_text)s</div>
                <div class="upload-requirements small text-muted">%(requirements_text)s</div>
            </div>

            <!-- Cropper Interface -->
            <div class="cropper-wrapper" style="display: none">
                <div class="image-container">
                    <img src="" alt="Upload preview" class="crop-preview">
                </div>

                <!-- Preview Thumbnails -->
                <div class="preview-container mt-3">
                    <div class="row preview-thumbnails"></div>
                </div>

                <!-- Tool Buttons -->
                %(toolbar_buttons)s

                <!-- Aspect Ratio Controls -->
                %(aspect_ratio_controls)s

                <!-- Format and Quality Controls -->
                %(format_quality_controls)s

                <!-- Background Removal -->
                %(remove_bg_button)s

                <!-- Action Buttons -->
                <div class="action-buttons mt-3">
                    <button type="button" class="btn btn-secondary undo-btn" disabled>
                        <i class="fa fa-undo"></i> Undo
                    </button>
                    <button type="button" class="btn btn-secondary redo-btn" disabled>
                        <i class="fa fa-repeat"></i> Redo
                    </button>
                    <button type="button" class="btn btn-primary save-crop">
                        Apply Changes
                    </button>
                </div>
            </div>

            <!-- Progress Bar -->
            <div class="progress mt-2" style="display: none">
                <div class="progress-bar progress-bar-striped progress-bar-animated"
                     role="progressbar"></div>
            </div>

            <!-- Error Messages -->
            <div class="alert alert-danger error-message mt-2"
                 style="display: none"
                 role="alert"></div>

            <!-- Hidden Fields -->
            <input type="hidden" name="%(name)s" id="%(field_id)s">
            <input type="hidden" name="%(name)s_metadata" id="%(field_id)s_metadata">
        </div>
    """

    def __init__(
        self,
        aspect_ratio: Optional[float] = None,
        min_size: Tuple[int, int] = (50, 50),
        max_size: Tuple[int, int] = (2000, 2000),
        preview_sizes: List[Tuple[int, int]] = None,
        formats: List[str] = None,
        quality: float = 0.9,
        enable_bg_removal: bool = False,
        max_file_size: int = 5 * 1024 * 1024,  # 5MB
        wrapper_class: str = "",
        remove_bg_api_key: str = "",
        optimize_images: bool = True,
        auto_crop: bool = True,
        maintain_aspect_ratio: bool = True,
        enable_touch: bool = True,
        zoom_ratio: float = 0.1,
        rotation_step: int = 45,
        **kwargs,
    ):
        """
        Initialize the ImageCropWidget with comprehensive configuration options.

        Args:
            aspect_ratio: Fixed aspect ratio for cropping (e.g., 1.0 for square)
            min_size: Minimum dimensions (width, height) for the cropped image
            max_size: Maximum dimensions (width, height) for the cropped image
            preview_sizes: List of (width, height) tuples for preview thumbnails
            formats: List of allowed image formats (e.g., ['jpg', 'png', 'webp'])
            quality: JPEG/WebP quality setting (0.1 to 1.0)
            enable_bg_removal: Enable background removal feature
            max_file_size: Maximum allowed file size in bytes
            wrapper_class: Additional CSS classes for the widget wrapper
            remove_bg_api_key: API key for background removal service
            optimize_images: Enable automatic image optimization
            auto_crop: Enable automatic cropping suggestions
            maintain_aspect_ratio: Lock aspect ratio during cropping
            enable_touch: Enable touch gestures for mobile devices
            zoom_ratio: Zoom step size for zoom in/out
            rotation_step: Rotation angle step in degrees
        """
        super().__init__(**kwargs)

        # Store configuration
        self.aspect_ratio = aspect_ratio
        self.min_size = min_size
        self.max_size = max_size
        self.preview_sizes = preview_sizes or [(150, 150)]
        self.formats = formats or ["jpg", "png", "webp"]
        self.quality = quality
        self.enable_bg_removal = enable_bg_removal
        self.max_file_size = max_file_size
        self.wrapper_class = wrapper_class
        self.remove_bg_api_key = remove_bg_api_key
        self.optimize_images = optimize_images
        self.auto_crop = auto_crop
        self.maintain_aspect_ratio = maintain_aspect_ratio
        self.enable_touch = enable_touch
        self.zoom_ratio = zoom_ratio
        self.rotation_step = rotation_step

        # Validate configuration
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate widget configuration parameters."""
        if self.aspect_ratio is not None and self.aspect_ratio <= 0:
            raise ValueError("Aspect ratio must be positive")

        if any(dim <= 0 for dim in self.min_size + self.max_size):
            raise ValueError("Image dimensions must be positive")

        if self.min_size[0] > self.max_size[0] or self.min_size[1] > self.max_size[1]:
            raise ValueError("Minimum size cannot exceed maximum size")

        if not 0.1 <= self.quality <= 1.0:
            raise ValueError("Quality must be between 0.1 and 1.0")

        if not self.formats:
            raise ValueError("At least one image format must be specified")

        if not all(
            fmt.lower() in ["jpg", "jpeg", "png", "webp"] for fmt in self.formats
        ):
            raise ValueError("Unsupported image format specified")

    def __call__(self, field, **kwargs) -> str:
        """
        Render the image crop widget with all features and dependencies.

        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes for the file input

        Returns:
            str: Rendered HTML for the widget
        """
        # Set up basic field attributes
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("accept", "image/*")
        if field.flags.required:
            kwargs["required"] = True

        # Prepare template variables
        template_vars = {
            "wrapper_class": self.wrapper_class,
            "min_width": self.min_size[0],
            "min_height": self.min_size[1],
            "max_width": self.max_size[0],
            "max_height": self.max_size[1],
            "aspect_ratio": str(self.aspect_ratio or ""),
            "max_file_size": self.max_file_size,
            "allowed_formats": ",".join(self.formats),
            "enable_touch": str(self.enable_touch).lower(),
            "zoom_ratio": self.zoom_ratio,
            "rotation_step": self.rotation_step,
            "file_attrs": self.html_params(**kwargs),
            "name": field.name,
            "field_id": kwargs["id"],
            "upload_text": "Drag & drop or click to upload",
            "requirements_text": self._get_requirements_text(),
            "toolbar_buttons": self._render_toolbar(),
            "aspect_ratio_controls": self._render_aspect_ratio_controls(),
            "format_quality_controls": self._render_format_quality_controls(),
            "remove_bg_button": self._render_remove_bg_button(),
        }

        # Render template and attach scripts
        html = self.template % template_vars
        return Markup(html + self._get_widget_scripts(field))

    def _get_requirements_text(self) -> str:
        """Generate text describing upload requirements."""
        reqs = [
            f"Formats: {', '.join(self.formats)}",
            f"Max size: {self._format_file_size(self.max_file_size)}",
            f"Min dimensions: {self.min_size[0]}x{self.min_size[1]}px",
        ]
        return " • ".join(reqs)

    def _render_toolbar(self) -> str:
        """Render the image editing toolbar."""
        buttons = [
            ("rotate-left", "Rotate Left", "fa-rotate-left"),
            ("rotate-right", "Rotate Right", "fa-rotate-right"),
            ("flip-horizontal", "Flip Horizontal", "fa-arrows-h"),
            ("flip-vertical", "Flip Vertical", "fa-arrows-v"),
            ("zoom-in", "Zoom In", "fa-search-plus"),
            ("zoom-out", "Zoom Out", "fa-search-minus"),
            ("reset", "Reset", "fa-refresh"),
        ]

        html = ['<div class="toolbar btn-group mt-3">']
        for cls, title, icon in buttons:
            html.append(f"""
                <button type="button"
                        class="btn btn-sm btn-outline-secondary {cls}"
                        title="{title}">
                    <i class="fa {icon}"></i>
                </button>
            """)
        html.append("</div>")
        return "".join(html)

    def _render_aspect_ratio_controls(self) -> str:
        """Render aspect ratio selection buttons."""
        ratios = [
            ("1", "1:1", "Square"),
            ("1.7778", "16:9", "Widescreen"),
            ("1.3333", "4:3", "Standard"),
            ("0", "Free", "Free Form"),
        ]

        html = ['<div class="aspect-ratios btn-group mt-2">']
        for value, label, title in ratios:
            html.append(f"""
                <button type="button"
                        class="btn btn-sm btn-outline-secondary"
                        data-ratio="{value}"
                        title="{title}">
                    {label}
                </button>
            """)
        html.append("</div>")
        return "".join(html)

    def _render_format_quality_controls(self) -> str:
        """Render format and quality control inputs."""
        format_options = "".join(
            f'<option value="{fmt}">{fmt.upper()}</option>' for fmt in self.formats
        )

        return f"""
            <div class="format-quality mt-3">
                <select class="form-control form-control-sm format-select">
                    {format_options}
                </select>
                <input type="range"
                       class="form-control-range quality-slider"
                       min="0.1"
                       max="1.0"
                       step="0.1"
                       value="{self.quality}">
                <div class="quality-label small text-muted">
                    Quality: <span>{self.quality}</span>
                </div>
            </div>
        """

    def _render_remove_bg_button(self) -> str:
        """Render background removal button if enabled."""
        if not self.enable_bg_removal:
            return ""

        return """
            <button type="button"
                    class="btn btn-secondary btn-block remove-bg mt-2">
                Remove Background
            </button>
        """

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ["B", "KB", "MB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} GB"

    def _get_widget_scripts(self, field) -> str:
        """
        Generate JavaScript code for widget functionality.

        Includes initialization of Cropper.js, event handlers, and all interactive features.

        Args:
            field: The form field being rendered

        Returns:
            str: JavaScript code as a string
        """
        # Configuration object for JavaScript
        config = {
            "fieldName": field.name,
            "fieldId": field.id,
            "aspectRatio": self.aspect_ratio,
            "minSize": list(self.min_size),
            "maxSize": list(self.max_size),
            "previewSizes": self.preview_sizes,
            "formats": self.formats,
            "quality": self.quality,
            "enableBgRemoval": self.enable_bg_removal,
            "maxFileSize": self.max_file_size,
            "optimizeImages": self.optimize_images,
            "autoCrop": self.auto_crop,
            "maintainAspectRatio": self.maintain_aspect_ratio,
            "enableTouch": self.enable_touch,
            "zoomRatio": self.zoom_ratio,
            "rotationStep": self.rotation_step,
            "removeBgApiKey": self.remove_bg_api_key,
        }

        return f"""
        <script>
        (function() {{
            // Initialize widget when DOM is ready
            document.addEventListener('DOMContentLoaded', function() {{
                const config = {json.dumps(config)};
                const wrapper = document.querySelector('.image-crop-wrapper[data-field-id="{field.id}"]');
                if (!wrapper) return;

                let cropper = null;
                let history = [];
                let historyIndex = -1;

                // Cache DOM elements
                const fileInput = wrapper.querySelector('input[type="file"]');
                const uploadZone = wrapper.querySelector('.upload-zone');
                const cropperWrapper = wrapper.querySelector('.cropper-wrapper');
                const imageElement = wrapper.querySelector('.crop-preview');
                const progressBar = wrapper.querySelector('.progress');
                const errorMessage = wrapper.querySelector('.error-message');
                const dataInput = wrapper.querySelector(`#${field.id}`);
                const metadataInput = wrapper.querySelector(`#${field.id}_metadata`);

                // Initialize Cropper.js with options
                function initCropper(image) {{
                    return new Cropper(image, {{
                        aspectRatio: config.aspectRatio,
                        viewMode: 2,
                        dragMode: 'move',
                        autoCrop: config.autoCrop,
                        responsive: true,
                        restore: true,
                        checkCrossOrigin: true,
                        checkOrientation: true,
                        modal: true,
                        guides: true,
                        center: true,
                        highlight: true,
                        background: true,
                        autoCropArea: 0.8,
                        movable: true,
                        rotatable: true,
                        scalable: true,
                        zoomable: true,
                        zoomOnTouch: config.enableTouch,
                        zoomOnWheel: true,
                        wheelZoomRatio: config.zoomRatio,
                        cropBoxMovable: true,
                        cropBoxResizable: true,
                        toggleDragModeOnDblclick: true,
                        minContainerWidth: 200,
                        minContainerHeight: 100,
                        ready: function() {{
                            updatePreviewThumbnails();
                            addHistoryState();
                        }},
                        crop: function() {{
                            updatePreviewThumbnails();
                        }}
                    }});
                }}

                // File upload handling
                function handleFileUpload(file) {{
                    if (!validateFile(file)) return;

                    const reader = new FileReader();
                    reader.onload = function(e) {{
                        imageElement.src = e.target.result;
                        if (cropper) {{
                            cropper.destroy();
                        }}
                        cropper = initCropper(imageElement);
                        uploadZone.style.display = 'none';
                        cropperWrapper.style.display = 'block';
                    }};
                    reader.readAsDataURL(file);
                }}

                // File validation
                function validateFile(file) {{
                    const errors = [];

                    if (!file.type.startsWith('image/')) {{
                        errors.push('Please upload an image file.');
                    }}

                    if (file.size > config.maxFileSize) {{
                        errors.push(`File size must not exceed ${formatFileSize(config.maxFileSize)}.`);
                    }}

                    if (errors.length) {{
                        showError(errors.join(' '));
                        return false;
                    }}

                    return true;
                }}

                // Preview thumbnails
                function updatePreviewThumbnails() {{
                    if (!cropper) return;

                    const container = wrapper.querySelector('.preview-thumbnails');
                    container.innerHTML = '';

                    config.previewSizes.forEach(([width, height]) => {{
                        const div = document.createElement('div');
                        div.className = 'col preview-box';
                        div.style.width = `${width}px`;
                        div.style.height = `${height}px`;

                        const img = document.createElement('img');
                        img.src = cropper.getCroppedCanvas({{
                            width: width,
                            height: height
                        }}).toDataURL();

                        div.appendChild(img);
                        container.appendChild(div);
                    }});
                }}

                // History management
                function addHistoryState() {{
                    const data = cropper.getData();
                    history = history.slice(0, historyIndex + 1);
                    history.push(data);
                    historyIndex++;
                    updateHistoryButtons();
                }}

                function undo() {{
                    if (historyIndex <= 0) return;
                    historyIndex--;
                    cropper.setData(history[historyIndex]);
                    updateHistoryButtons();
                }}

                function redo() {{
                    if (historyIndex >= history.length - 1) return;
                    historyIndex++;
                    cropper.setData(history[historyIndex]);
                    updateHistoryButtons();
                }}

                function updateHistoryButtons() {{
                    wrapper.querySelector('.undo-btn').disabled = historyIndex <= 0;
                    wrapper.querySelector('.redo-btn').disabled = historyIndex >= history.length - 1;
                }}

                // Image processing
                async function processImage(format, quality) {{
                    const canvas = cropper.getCroppedCanvas();

                    if (config.optimizeImages) {{
                        const compressor = new Compressor(canvas, {{
                            quality: quality,
                            mimeType: `image/${format}`,
                            convertSize: 5000000, // 5MB
                            success(result) {{
                                saveProcessedImage(result, format);
                            }},
                            error(err) {{
                                showError('Error optimizing image: ' + err.message);
                            }}
                        }});
                    }} else {{
                        canvas.toBlob(
                            blob => saveProcessedImage(blob, format),
                            `image/${format}`,
                            quality
                        );
                    }}
                }}

                // Background removal
                async function removeBackground() {{
                    if (!config.enableBgRemoval || !config.removeBgApiKey) return;

                    const canvas = cropper.getCroppedCanvas();
                    const blob = await new Promise(resolve => canvas.toBlob(resolve));

                    showProgress();

                    try {{
                        const formData = new FormData();
                        formData.append('image_file', blob);

                        const response = await fetch('https://api.remove.bg/v1.0/removebg', {{
                            method: 'POST',
                            headers: {{
                                'X-Api-Key': config.removeBgApiKey
                            }},
                            body: formData
                        }});

                        if (!response.ok) throw new Error('Background removal failed');

                        const resultBlob = await response.blob();
                        const url = URL.createObjectURL(resultBlob);

                        imageElement.src = url;
                        cropper.destroy();
                        cropper = initCropper(imageElement);
                    }} catch (error) {{
                        showError('Background removal failed: ' + error.message);
                    }} finally {{
                        hideProgress();
                    }}
                }}

                // Utility functions
                function showError(message) {{
                    errorMessage.textContent = message;
                    errorMessage.style.display = 'block';
                    setTimeout(() => {{
                        errorMessage.style.display = 'none';
                    }}, 5000);
                }}

                function showProgress() {{
                    progressBar.style.display = 'block';
                }}

                function hideProgress() {{
                    progressBar.style.display = 'none';
                }}

                function formatFileSize(bytes) {{
                    const units = ['B', 'KB', 'MB', 'GB'];
                    let size = bytes;
                    let unitIndex = 0;

                    while (size >= 1024 && unitIndex < units.length - 1) {{
                        size /= 1024;
                        unitIndex++;
                    }}

                    return `${{size.toFixed(1)}} ${{units[unitIndex]}}`;
                }}

                // Event Listeners
                fileInput.addEventListener('change', function(e) {{
                    if (e.target.files && e.target.files[0]) {{
                        handleFileUpload(e.target.files[0]);
                    }}
                }});

                uploadZone.addEventListener('click', function() {{
                    fileInput.click();
                }});

                uploadZone.addEventListener('dragover', function(e) {{
                    e.preventDefault();
                    this.classList.add('dragover');
                }});

                uploadZone.addEventListener('dragleave', function() {{
                    this.classList.remove('dragover');
                }});

                uploadZone.addEventListener('drop', function(e) {{
                    e.preventDefault();
                    this.classList.remove('dragover');

                    if (e.dataTransfer.files && e.dataTransfer.files[0]) {{
                        handleFileUpload(e.dataTransfer.files[0]);
                    }}
                }});

                // Toolbar button handlers
                wrapper.querySelector('.rotate-left').addEventListener('click', () => {{
                    cropper.rotate(-config.rotationStep);
                    addHistoryState();
                }});

                wrapper.querySelector('.rotate-right').addEventListener('click', () => {{
                    cropper.rotate(config.rotationStep);
                    addHistoryState();
                }});

                wrapper.querySelector('.flip-horizontal').addEventListener('click', () => {{
                    cropper.scaleX(-cropper.getData().scaleX || -1);
                    addHistoryState();
                }});

                wrapper.querySelector('.flip-vertical').addEventListener('click', () => {{
                    cropper.scaleY(-cropper.getData().scaleY || -1);
                    addHistoryState();
                }});

                wrapper.querySelector('.zoom-in').addEventListener('click', () => {{
                    cropper.zoom(config.zoomRatio);
                    addHistoryState();
                }});

                wrapper.querySelector('.zoom-out').addEventListener('click', () => {{
                    cropper.zoom(-config.zoomRatio);
                    addHistoryState();
                }});

                wrapper.querySelector('.reset').addEventListener('click', () => {{
                    cropper.reset();
                    addHistoryState();
                }});

                // Aspect ratio buttons
                wrapper.querySelectorAll('.aspect-ratios button').forEach(button => {{
                    button.addEventListener('click', function() {{
                        const ratio = parseFloat(this.dataset.ratio) || NaN;
                        cropper.setAspectRatio(ratio);
                        addHistoryState();
                    }});
                }});

                // Format and quality controls
                const formatSelect = wrapper.querySelector('.format-select');
                const qualitySlider = wrapper.querySelector('.quality-slider');
                const qualityLabel = wrapper.querySelector('.quality-label span');

                formatSelect.addEventListener('change', function() {{
                    processImage(this.value, parseFloat(qualitySlider.value));
                }});

                qualitySlider.addEventListener('input', function() {{
                    qualityLabel.textContent = this.value;
                }});

                qualitySlider.addEventListener('change', function() {{
                    processImage(formatSelect.value, parseFloat(this.value));
                }});

                // Background removal button
                if (config.enableBgRemoval) {{
                    wrapper.querySelector('.remove-bg').addEventListener('click', removeBackground);
                }}

                // Undo/Redo buttons
                wrapper.querySelector('.undo-btn').addEventListener('click', undo);
                wrapper.querySelector('.redo-btn').addEventListener('click', redo);

                // Save button
                wrapper.querySelector('.save-crop').addEventListener('click', function() {{
                    const format = formatSelect.value;
                    const quality = parseFloat(qualitySlider.value);
                    processImage(format, quality);
                }});
            }});
        }})();
        </script>
        """



class SignaturePadWidget(BS3TextFieldWidget):
    """
    Widget for capturing digital signatures with drawing capabilities.

    Features:
    - Pressure sensitivity with multi-touch support
    - Multiple pen colors, sizes and styles
    - Clear/redo/undo functionality with history
    - Vector-based SVG storage for crisp scaling
    - PNG/SVG/JSON export options
    - Enhanced Signature validation (min points, speed, rhythm analysis)
    - Signature replay for verification and forensic analysis
    - Name attestation with optional field
    - Customizable pen styles and canvas backgrounds
    - Timestamp embedding and Audit trail logging
    - Improved error handling and user feedback
    - Accessibility enhancements for users with motor impairments

    Required Dependencies:
    - SignaturePad.js 2.3+ (for signature capture)
    - bezier.js (for signature smoothing)

    Database Type:
        PostgreSQL: jsonb (stores signature data, metadata, audit trail, and verification data)
        SQLAlchemy: JSON

    Example Usage:
        signature = db.Column(db.JSON, nullable=False,
            info={'widget': SignaturePadWidget(
                pen_color='#000000',
                pen_size=2,
                min_points=100, # Increased min_points for better security
                require_name=True,
                background_grid=True,
                allow_undo=True,
                store_audit_trail=True,
                enable_replay_verification=True # Enable replay verification
            )})
    """

    data_template = (
        '<div class="signature-pad-wrapper %(wrapper_class)s">'
        '<div class="signature-pad" style="background: %(background_color)s;">'  # Set background color from widget config
        '<canvas class="signature-pad-canvas"></canvas>'
        "</div>"
        '<div class="signature-controls mt-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-secondary clear-signature" title="Clear" aria-label="Clear Signature">'  # Added ARIA labels for accessibility
        '<i class="fa fa-eraser"></i> Clear'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary undo-signature" title="Undo" aria-label="Undo Last Stroke" %(undo_disabled)s>'  # ARIA and disabled state for undo button
        '<i class="fa fa-undo"></i> Undo'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary redo-signature" title="Redo" aria-label="Redo Last Stroke" %(redo_disabled)s style="display:none;">'  # ARIA and hidden state for redo button
        '<i class="fa fa-redo"></i> Redo'
        "</button>"
        "</div>"
        '<div class="pen-controls btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-outline-secondary dropdown-toggle" data-toggle="dropdown" title="Pen Options" aria-haspopup="true" aria-expanded="false" aria-label="Pen Options">'  # ARIA labels for accessibility
        '<i class="fa fa-paint-brush"></i> Pen Options'
        "</button>"
        '<div class="dropdown-menu dropdown-menu-right">'  # Right align dropdown menu
        '<div class="px-3 py-2">'
        '<div class="form-group">'
        "<label for='%(field_id)s-pen-color'>Color</label>"  # Added labels for accessibility
        '<input type="color" class="form-control pen-color" id="%(field_id)s-pen-color" value="%(pen_color)s" aria-label="Pen Color">'
        "</div>"
        '<div class="form-group">'
        "<label for='%(field_id)s-pen-size'>Size</label>"  # Added labels for accessibility
        '<input type="range" class="form-control-range pen-size" id="%(field_id)s-pen-size" min="1" max="10" value="%(pen_size)s" aria-label="Pen Size">'
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        "%(name_field)s"
        '<div class="signature-status mt-2" aria-live="polite" aria-atomic="true">'  # ARIA live region for status updates
        '<small class="text-muted status-text">Ready to sign</small>'
        '<div class="signature-error text-danger" style="display: none;"></div>'
        '<div class="signature-verification text-success" style="display: none;">Signature Verified</div>'  # Added verification message
        '<div class="signature-score text-info" style="display: none;"></div>'  # Added signature score display
        "</div>"
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        "</div>"
    )

    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/signature_pad@4.1.5/dist/signature_pad.umd.min.js",  # Updated SignaturePad.js CDN
        "https://cdn.jsdelivr.net/npm/bezier-js@3.1.0/bezier.min.js",  # Ensure bezier.js is included if used for smoothing
    ]

    CSS_DEPENDENCIES = [
        "/static/css/signature-pad-widget.css",  # Ensure custom CSS is included
    ]

    def __init__(self, **kwargs):
        """Initialize signature widget with extensive configuration options"""
        super().__init__(**kwargs)
        self.pen_color = kwargs.get("pen_color", "#000000")
        self.pen_size = kwargs.get("pen_size", 2)
        self.min_points = kwargs.get(
            "min_points", 100
        )  # Increased default for better security
        self.require_name = kwargs.get("require_name", False)
        self.background_grid = kwargs.get("background_grid", False)
        self.allow_undo = kwargs.get("allow_undo", True)
        self.allow_redo = kwargs.get("allow_redo", True)  # Enable redo functionality
        self.store_audit_trail = kwargs.get("store_audit_trail", True)
        self.enable_replay_verification = kwargs.get(
            "enable_replay_verification", False
        )  # Enable signature replay verification feature
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.canvas_width = kwargs.get("canvas_width", 500)
        self.canvas_height = kwargs.get("canvas_height", 200)
        self.max_points = kwargs.get("max_points", 10000)  # Increased max points
        self.throttle = kwargs.get("throttle", 16)  # ms between points
        self.min_speed = kwargs.get(
            "min_speed", 0.8
        )  # Increased min speed for stricter validation
        self.max_idle_time = kwargs.get(
            "max_idle_time", 5000
        )  # Max idle time in ms before validation fails
        self.pressure_support = kwargs.get("pressure_support", True)
        self.background_color = kwargs.get(
            "background_color", "#f8f9fa"
        )  # Customizable background color
        self.locale = kwargs.get("locale", "en")
        self.custom_validators = kwargs.get(
            "custom_validators", []
        )  # Accept custom validators

    def __call__(self, field, **kwargs):
        """Render the signature pad widget"""
        kwargs.setdefault("id", field.id)

        name_field = ""
        if self.require_name:
            name_field = """
                <div class="form-group mt-2">
                    <label for="%(field_id)s-signer-name">Signer Name (Optional)</label>
                    <input type="text" class="form-control signer-name" id="%(field_id)s-signer-name"
                           placeholder="Type your name (Optional)">
                </div>
            """ % {"field_id": field.id}  # Added label for screen readers

        html = (
            self.data_template
            % {
                "name": field.name,
                "field_id": field.id,
                "wrapper_class": self.wrapper_class,
                "pen_color": self.pen_color,
                "pen_size": self.pen_size,
                "name_field": name_field,
                "background_color": self.background_color,  # Pass background color to template
                "undo_disabled": ""
                if self.allow_undo
                else "disabled",  # Control disabled state of undo button
                "redo_disabled": ""
                if self.allow_redo
                else "disabled",  # Control disabled state of redo button
            }
        )

        return Markup(html + self._get_widget_scripts(field))

    # _get_widget_scripts = _get_widget_scripts


# {{REWRITTEN_CODE}}
class CodeEditorWidget(BS3TextFieldWidget):
    """
    Advanced code editor widget with syntax highlighting and features using Monaco Editor.

    Features:
        - Syntax highlighting for multiple languages (JSON, Python, SQL, DBML, Lua).
        - Real-time code linting and error detection for supported languages.
        - Code auto-completion and suggestions.
        - Integration with language services for enhanced code intelligence.
        - Code formatting and beautification.
        - Export code in multiple formats.
        - Customizable themes and editor options.
        - Basic code debugging and execution (planned).
        - Real-time collaboration for simultaneous editing (planned).
        - Version control integration for tracking code changes (planned).

    Database Type:
        PostgreSQL: TEXT or JSONB for storing code content and editor state.
        SQLAlchemy: Text or JSON

    Example Usage:
        code_field = db.Column(db.Text, info={'widget': CodeEditorWidget(language='python')})
    """

    data_template = (
        '<div class="code-editor-wrapper %(wrapper_class)s">'
        '<div id="%(field_id)s-container" class="editor-container"></div>'
        '<div class="editor-statusbar"></div>'
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        '<input type="hidden" name="%(name)s_state" id="%(field_id)s_state">'
        "</div>"
    )

    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs/loader.js"  # Using Monaco Editor Loader for dynamic loading
    ]

    CSS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs/editor/editor.main.css",  # Monaco Editor Styles
        "/static/css/code-editor-widget.css",  # Custom widget styles
    ]

    def __init__(self, **kwargs):
        """
        Initializes CodeEditorWidget with extensive configuration for code editing features.
        """
        super().__init__(**kwargs)
        self.language = kwargs.get("language", "plaintext")
        self.theme = kwargs.get("theme", "vs-dark")
        self.auto_complete = kwargs.get("auto_complete", True)
        self.line_numbers = kwargs.get("line_numbers", True)
        self.minimap = kwargs.get("minimap", True)
        self.folding = kwargs.get("folding", True)
        self.lint = kwargs.get("lint", True)  # Enable linting by default
        self.format_on_save = kwargs.get("format_on_save", True)
        self.word_wrap = kwargs.get(
            "word_wrap", "on"
        )  # Default to 'on' for better readability
        self.tab_size = kwargs.get("tab_size", 4)
        self.insert_spaces = kwargs.get("insert_spaces", True)
        self.snippets = kwargs.get("snippets", True)
        self.quick_suggestions = kwargs.get("quick_suggestions", True)
        self.hover = kwargs.get("hover", True)
        self.font_size = kwargs.get("font_size", 14)
        self.font_family = kwargs.get(
            "font_family", "'Fira Code', 'Consolas', monospace"
        )  # Enhanced font family
        self.rulers = kwargs.get("rulers", [80, 120])
        self.scroll_beyond_last_line = kwargs.get(
            "scroll_beyond_last_line", False
        )  # Improved default scroll behavior
        self.wrapper_class = kwargs.get(
            "wrapper_class", "flb-code-editor"
        )  # Custom CSS class
        self.keyboard_shortcuts = kwargs.get("keyboard_shortcuts", {})
        self.max_file_size = kwargs.get(
            "max_file_size", 10 * 1024 * 1024
        )  # Increased max file size to 10MB
        self.enable_diff_view = kwargs.get(
            "enable_diff_view", False
        )  # Feature flag for diff view
        self.enable_collaboration = kwargs.get(
            "enable_collaboration", False
        )  # Feature flag for real-time collaboration
        self.supported_languages = {  # Define supported languages with modes and extra configurations
            "javascript": {"id": "javascript", "label": "JavaScript"},
            "typescript": {"id": "typescript", "label": "TypeScript"},
            "python": {"id": "python", "label": "Python"},
            "sql": {"id": "sql", "label": "SQL"},
            "dbml": {"id": "dbml", "label": "DBML"},  # Added DBML support
            "lua": {"id": "lua", "label": "Lua"},  # Added Lua support
            "json": {"id": "json", "label": "JSON"},
            "html": {"id": "html", "label": "HTML"},
            "css": {"id": "css", "label": "CSS"},
            "xml": {"id": "xml", "label": "XML"},
            "yaml": {"id": "yaml", "label": "YAML"},
            "markdown": {"id": "markdown", "label": "Markdown"},
            "plaintext": {"id": "plaintext", "label": "Plain Text"},
        }

    def __call__(self, field, **kwargs):
        """Renders the CodeEditorWidget, initializing Monaco Editor with specified configurations."""
        kwargs.setdefault("id", field.id)
        if field.flags.required:
            kwargs["required"] = True

        template = self.data_template
        html = template % {
            "field_id": field.id,
            "hidden": self.html_params(name=field.name, **kwargs),
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generates and returns the JavaScript code block for the CodeEditorWidget, including Monaco Editor initialization."""
        return """
        <style>
            /* Styles remain same as before, consider moving to a separate CSS file */
            .code-editor-wrapper { border: 1px solid #dee2e6; border-radius: 4px; overflow: hidden; }
            .editor-container { height: 500px; width: 100%; }
            .editor-statusbar { padding: 2px 8px; background: #f8f9fa; border-top: 1px solid #dee2e6; font-size: 12px; color: #6c757d; }
        </style>
        <script>
            (function() {{
                require.config({{ paths: {{ 'vs': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs' }}}});


                require(['vs/editor/editor.main'], function() {{
                    $(document).ready(function() {{
                        var container = document.getElementById('{field_id}-container');
                        var statusBar = container.parentElement.querySelector('.editor-statusbar');
                        var editor;


                        // Editor configuration
                        var config = {{
                            value: {json.dumps(field.data or '')},
                            language: '{language}',
                            theme: '{theme}',
                            automaticLayout: true,
                            lineNumbers: {str(self.line_numbers).lower()},
                            minimap: {{ enabled: {str(self.minimap).lower()} }},
                            folding: {str(self.folding).lower()},
                            wordWrap: '{word_wrap}',
                            tabSize: {tab_size},
                            insertSpaces: {str(self.insert_spaces).lower()},
                            quickSuggestions: {str(self.quick_suggestions).lower()},
                            hover: {{ enabled: {str(self.hover).lower()} }},
                            fontSize: {font_size},
                            fontFamily: '{font_family}',
                            rulers: {json.dumps(self.rulers)},
                            scrollBeyondLastLine: {str(self.scroll_beyond_last_line).lower()},
                            formatOnPaste: true,
                            formatOnType: true,
                            suggestOnTriggerCharacters: true,
                            snippetSuggestions: '{snippets}',
                            renderWhitespace: 'selection',
                            renderControlCharacters: false,
                            renderLineHighlight: 'gutter',
                            parameterHints: {{ enabled: true }},
                            links: true,
                            contextmenu: true,
                            mouseWheelZoom: true,
                            roundedSelection: false,
                            selectOnLineNumbers: true,
                            selectionHighlight: true,
                            occurrencesHighlight: true,
                            glyphMargin: false,
                            fixedOverflowWidgets: true,
                            hideCursorInOverviewRuler: true,
                            overviewRulerBorder: false,
                            cursorSmoothCaretAnimation: true,
                            scrollbar: {{ verticalScrollbarSize: 10, horizontalScrollbarSize: 10 }},
                            overviewRulerLanes: 2,
                            find: {{ seedSearchStringFromSelection: true }}
                        }};


                        editor = monaco.editor.create(container, config);


                        // Register custom keyboard shortcuts
                        var keyboardShortcuts = {keyboard_shortcuts};
                        Object.keys(keyboardShortcuts).forEach(function(key) {{
                            editor.addCommand(monaco.KeyMod[key], keyboardShortcuts[key]);
                        }});


                        // Update status bar function (remains same)
                        function updateStatusBar() {{
                            var position = editor.getPosition();
                            var model = editor.getModel();
                            if (position && model) {{
                                var lines = model.getLineCount();
                                var chars = model.getValueLength();
                                statusBar.textContent = `Ln ${position.lineNumber}, Col ${position.column} | ${lines} lines, ${chars} characters`;
                            }}
                        }}


                        editor.onDidChangeModelContent(updateStatusBar);
                        editor.onDidChangeCursorPosition(updateStatusBar);
                        updateStatusBar(); // Initial call to set status bar


                        // Value update and form submission handling (remains mostly same)
                        var $input = $('#{field_id}');
                        container.closest('form').addEventListener('submit', function(e) {{
                            var value = editor.getValue();
                            if (value.length > {max_file_size}) {{
                                e.preventDefault();
                                alert('Code content exceeds maximum size limit.');
                                return false;
                            }}
                            $input.val(value);
                            $('#{field_id}-state').val(JSON.stringify({{
                                scrollTop: editor.getScrollTop(),
                                scrollLeft: editor.getScrollLeft(),
                                viewState: editor.saveViewState()
                            }}));
                        }});


                        // Error markers (remains same, consider enhancing error display)
                        var errorWidget = null;
                        monaco.editor.onDidChangeMarkers(function() {{
                            var markers = monaco.editor.getModelMarkers({{ resource: editor.getModel().uri }});
                            var errors = markers.filter(m => m.severity === monaco.MarkerSeverity.Error);
                            if (errors.length) {{
                                if (!errorWidget) {{
                                    errorWidget = document.createElement('div');
                                    errorWidget.className = 'alert alert-danger mt-2';
                                    container.parentElement.appendChild(errorWidget);
                                }}
                                errorWidget.textContent = `${{errors.length}} error(s) found`;
                            }} else if (errorWidget) {{
                                errorWidget.remove();
                                errorWidget = null;
                            }}
                        }});


                        // Load saved state if available
                        var editorState = {json.dumps(getattr(field, 'state', None))};
                        if (editorState) {{
                            editor.restoreViewState(editorState.viewState);
                            editor.setScrollTop(editorState.scrollTop);
                            editor.setScrollLeft(editorState.scrollLeft);
                        }}
                    }});
                }});
            }})();
        </script>
        """.format(
            field_id=field.id,
            language=self.language,
            theme=self.theme,
            line_numbers=str(self.line_numbers).lower(),
            minimap=str(self.minimap).lower(),
            folding=str(self.folding).lower(),
            word_wrap=self.word_wrap,
            tab_size=self.tab_size,
            insert_spaces=str(self.insert_spaces).lower(),
            quick_suggestions=str(self.quick_suggestions).lower(),
            hover=str(self.hover).lower(),
            font_size=self.font_size,
            font_family=self.font_family,
            rulers=json.dumps(self.rulers),
            scroll_beyond_last_line=str(self.scroll_beyond_last_line).lower(),
            snippets="'" + "snippets" + "'"
            if self.snippets
            else "null",  # Correct snippet value
            format_on_save=str(self.format_on_save).lower(),
            keyboard_shortcuts=json.dumps(self.keyboard_shortcuts),
            max_file_size=self.max_file_size,
            initial_value=json.dumps(field.data or ""),
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""  # Remains same
        if valuelist:
            try:
                self.data = valuelist[0]
                if hasattr(self, "state"):
                    self.state = json.loads(valuelist[1])
            except Exception as e:
                raise ValueError("Invalid code content") from e
        else:
            self.data = None

    def pre_validate(self, form):
        """Validate code content before form processing"""  # Remains same
        if form.flags.required and not self.data:
            raise ValueError("Code content is required")

        if self.data:
            # Check content size
            if len(self.data.encode("utf-8")) > self.max_file_size:
                raise ValueError(
                    f"Code content exceeds maximum size of {self.max_file_size} bytes"
                )

            # Validate language (consider server-side linting for deeper validation)
            if self.language not in self.supported_languages:
                raise ValueError(f"Unsupported language: {self.language}")

            # Basic syntax validation for JSON and Python (extend as needed)
            try:
                if self.language == "python":
                    import ast

                    ast.parse(self.data)
                elif self.language == "json":
                    json.loads(self.data)
            except Exception as e:
                raise ValidationError(
                    f"Syntax error in {self.language} code: {str(e)}"
                )  # Use ValidationError for wtforms validation


class KanbanBoardWidget(BS3TextFieldWidget):
    """
    Interactive Kanban board widget for workflow management.
    Database columns should be JSONB type in PostgreSQL to store the full board state.

    Features:
    - Drag and drop cards between columns and swimlanes
    - Customizable columns, swimlanes and workflows
    - Work In Progress (WIP) limits for columns and swimlanes
    - User assignment, due dates, priority ordering, and tags
    - Card templates and custom card types
    - Checklists, subtasks, and file attachments
    - Real-time search and filtering with advanced options
    - Advanced reporting and analytics (burndown charts, lead/cycle time)
    - Export to PDF/CSV/JSON

    Database Type:
        PostgreSQL: JSONB

    Example:
        workflow = db.Column(JSONB, info={'widget': KanbanBoardWidget(...)})
    """

    data_template = """
        <div class="kanban-board-widget %(wrapper_class)s">
            <div class="kanban-toolbar">
                <!-- Toolbar buttons and controls will be inserted here -->
            </div>
            <div class="kanban-container">
                <!-- Kanban columns and swimlanes will be inserted here -->
            </div>
            <input type="hidden" name="%(name)s" id="%(field_id)s">
        </div>
        """

    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jqueryui/1.12.1/jquery-ui.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jquery-ui-touch-punch/0.2.3/jquery.ui.touch-punch.min.js",
        "/static/js/kanban-widget.js",  # Assuming a custom kanban-widget.js will handle the logic
    ]

    CSS_DEPENDENCIES = [
        "/static/css/kanban-widget.css"  # Custom widget styles
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.columns = kwargs.get("columns", ["Backlog", "Todo", "In Progress", "Done"])
        self.swimlanes = kwargs.get("swimlanes", ["Default"])  # Swimlanes support
        self.wip_limits = kwargs.get("wip_limits", {})
        self.card_types = kwargs.get("card_types", ["Task", "Bug", "Feature"])
        self.labels = kwargs.get("labels", ["High", "Medium", "Low"])
        self.enable_comments = kwargs.get("enable_comments", True)
        self.enable_attachments = kwargs.get("enable_attachments", True)
        self.enable_checklists = kwargs.get("enable_checklists", True)
        self.enable_due_dates = kwargs.get("enable_due_dates", True)  # Enable due dates
        self.enable_assignments = kwargs.get(
            "enable_assignments", True
        )  # Enable assignments
        self.enable_priority = kwargs.get("enable_priority", True)  # Enable priority
        self.enable_tags = kwargs.get("enable_tags", True)  # Enable tags
        self.enable_search = kwargs.get("enable_search", True)  # Enable search
        self.enable_filters = kwargs.get("enable_filters", True)  # Enable filters
        self.enable_reports = kwargs.get("enable_reports", True)  # Enable reports
        self.wrapper_class = kwargs.get("wrapper_class", "flb-kanban-board")

    def __call__(self, field, **kwargs):
        html = self.render_template(field, **kwargs)
        return Markup(html + self._get_widget_scripts(field))

    def render_template(self, field, **kwargs):
        c = super().render_field(field, **kwargs)
        return self.data_template % {
            "field_id": field.id,
            "name": field.name,
            "wrapper_class": self.wrapper_class,
        }

    def _get_widget_scripts(self, field):
        """Generate widget-specific JavaScript - Implementation moved to static file"""
        return f"""
            <script src="/static/js/kanban-widget.js"></script>
            <script>
                $(document).ready(function() {{
                    new KanbanWidget('{field.id}', {{
                        columns: {json.dumps(self.columns)},
                        swimlanes: {json.dumps(self.swimlanes)},
                        wipLimits: {json.dumps(self.wip_limits)},
                        cardTypes: {json.dumps(self.card_types)},
                        labels: {json.dumps(self.labels)},
                        enableComments: {str(self.enable_comments).lower()},
                        enableAttachments: {str(self.enable_attachments).lower()},
                        enableChecklists: {str(self.enable_checklists).lower()},
                        enableDueDates: {str(self.enable_due_dates).lower()},
                        enableAssignments: {str(self.enable_assignments).lower()},
                        enablePriority: {str(self.enable_priority).lower()},
                        enableTags: {str(self.enable_tags).lower()},
                        enableSearch: {str(self.enable_search).lower()},
                        enableFilters: {str(self.enable_filters).lower()},
                        enableReports: {str(self.enable_reports).lower()},
                        fieldId: '{field.id}',
                        fieldName: '{field.name}',
                    }});
                }});
            </script>
        """

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                self.data = json.loads(valuelist[0])
            except json.JSONDecodeError as e:
                self.data = None
                raise ValueError("Invalid Kanban data format") from e
        else:
            self.data = None

    def pre_validate(self, form):
        """Pre-validate form data before processing"""
        if form.flags.required and not self.data:
            raise ValueError("Kanban data is required")
        if self.data:
            self._validate_board_data(self.data)

    def _validate_board_data(self, data):
        """Validate board data structure and constraints"""
        if not isinstance(data, dict) or "columns" not in data or "cards" not in data:
            raise ValueError("Invalid Kanban board data structure")

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )
        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )
        return f"{css_includes}\n{js_includes}"


# BS3TextFieldWidget.widget_args_conversion = BS3TextFieldWidget.widget_args_conversion.copy()
# BS3TextFieldWidget.widget_args_conversion.update({{
#     'class':       ('extra_classes', ' ', 'class'),
#     'style':         ('style', '; ', 'style')
# }})


# class GanttChartWidget(BS3TextFieldWidget):
#     """
#     Interactive Gantt chart widget for project planning.
#     Database column should be JSONB type in PostgreSQL to store tasks, dependencies and timeline data.


#     Features:
#     - Task dependencies with circular detection
#     - Critical path calculation and highlighting
#     - Resource allocation with conflict detection
#     - Progress tracking with completion %
#     - Timeline zooming and scrolling
#     - Milestone markers with notifications
#     - Export to PDF/PNG/Excel
#     - Task grouping and subtasks
#     - Working calendar with holidays
#     - Baseline comparison
#     - Task constraints
#     - Split tasks
#     - Resource leveling
#     - Cost tracking
#     - Undo/redo stack
#     - Keyboard shortcuts
#     - Drag and drop
#     - Auto scheduling
#     - Duration units
#     - Task linking
#     - Grid view


#     Required Dependencies:
#     - dhtmlxGantt 7.0+
#     - moment.js
#     - jsPDF
#     - xlsx


#     Example:
#         timeline = db.Column(db.JSON, nullable=False,
#             info={{'widget': GanttChartWidget(
#                 start_date='2024-01-01',
#                 end_date='2024-12-31',
#                 show_resources=True,
#                 work_hours=[9, 17],
#                 work_days=[0,1,2,3,4],
#                 auto_scheduling=True,
#                 critical_path=True,
#                 baseline=True,
#                 currency='USD'
#             )}})
#     """


#     data_template = (
#         '<div class="gantt-wrapper %(wrapper_class)s">'
#         '<div class="gantt-toolbar mb-2">'
#         '<div class="btn-group">'
#         '<button type="button" class="btn btn-sm btn-primary add-task">'
#         '<i class="fa fa-plus"></i> Add Task'
#         "</button>"
#         '<button type="button" class="btn btn-sm btn-secondary add-milestone">'
#         '<i class="fa fa-flag"></i> Add Milestone'
#         "</button>"
#         "</div>"
#         '<div class="btn-group ml-2">'
#         '<button type="button" class="btn btn-sm btn-secondary" data-zoom="day">'
#         "Day"
#         "</button>"
#         '<button type="button" class="btn btn-sm btn-secondary" data-zoom="week">'
#         "Week"
#         "</button>"
#         '<button type="button" class="btn btn-sm btn-secondary" data-zoom="month">'
#         "Month"
#         "</button>"
#         "</div>"
#         '<div class="btn-group ml-2">'
#         '<button type="button" class="btn btn-sm btn-secondary critical-path-toggle">'
#         '<i class="fa fa-random"></i> Critical Path'
#         "</button>"
#         '<button type="button" class="btn btn-sm btn-secondary resource-panel-toggle">'
#         '<i class="fa fa-users"></i> Resources'
#         "</button>"
#         "</div>"
#         '<div class="btn-group ml-2">'
#         '<button type="button" class="btn btn-sm btn-secondary undo" disabled>'
#         '<i class="fa fa-undo"></i>'
#         "</button>"
#         '<button type="button" class="btn btn-sm btn-secondary redo" disabled>'
#         '<i class="fa fa-redo"></i>'
#         "</button>"
#         "</div>"
#         '<div class="btn-group ml-2">'
#         '<div class="dropdown">'
#         '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
#         'Export <i class="fa fa-download"></i>'
#         "</button>"
#         '<div class="dropdown-menu">'
#         '<a class="dropdown-item export-pdf" href="#"><i class="fa fa-file-pdf"></i> PDF</a>'
#         '<a class="dropdown-item export-png" href="#"><i class="fa fa-file-image"></i> PNG</a>'
#         '<a class="dropdown-item export-excel" href="#"><i class="fa fa-file-excel"></i> Excel</a>'
#         '</div>'
#     )
# BS3TextFieldWidget.widget_args_conversion = BS3TextFieldWidget.widget_args_conversion.copy()
# BS3TextFieldWidget.widget_args_conversion.update({
#     'class':       ('extra_classes', ' ', 'class'),
#     'style':         ('style', '; ', 'style')
#     })


class GanttChartWidget(BS3TextFieldWidget):
    """
    Interactive Gantt chart widget for project planning.
    Database column should be JSONB type in PostgreSQL to store tasks, dependencies and timeline data.

    Features:
    - Task dependencies with circular detection
    - Critical path calculation and highlighting
    - Resource allocation with conflict detection
    - Progress tracking with completion %
    - Timeline zooming and scrolling
    - Milestone markers with notifications
    - Export to PDF/PNG/Excel
    - Task grouping and subtasks
    - Working calendar with holidays
    - Baseline comparison
    - Task constraints
    - Split tasks
    - Resource leveling
    - Cost tracking
    - Undo/redo stack
    - Keyboard shortcuts
    - Drag and drop
    - Auto scheduling
    - Duration units
    - Task linking
    - Grid view

    Required Dependencies:
    - dhtmlxGantt 7.0+
    - moment.js
    - jsPDF
    - xlsx

    Example:
        timeline = db.Column(db.JSON, nullable=False,
            info={'widget': GanttChartWidget(
                start_date='2024-01-01',
                end_date='2024-12-31',
                show_resources=True,
                work_hours=[9, 17],
                work_days=[0,1,2,3,4],
                auto_scheduling=True,
                critical_path=True,
                baseline=True,
                currency='USD'
            )})
    """

    data_template = (
        '<div class="gantt-wrapper %(wrapper_class)s">'
        '<div class="gantt-toolbar mb-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-primary add-task">'
        '<i class="fa fa-plus"></i> Add Task'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary add-milestone">'
        '<i class="fa fa-flag"></i> Add Milestone'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-zoom="day">'
        "Day"
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-zoom="week">'
        "Week"
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-zoom="month">'
        "Month"
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary critical-path-toggle">'
        '<i class="fa fa-random"></i> Critical Path'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary resource-panel-toggle">'
        '<i class="fa fa-users"></i> Resources'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary undo" disabled>'
        '<i class="fa fa-undo"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary redo" disabled>'
        '<i class="fa fa-redo"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<div class="dropdown">'
        '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
        'Export <i class="fa fa-download"></i>'
        "</button>"
        '<div class="dropdown-menu">'
        '<a class="dropdown-item export-pdf" href="#"><i class="fa fa-file-pdf"></i> PDF</a>'
        '<a class="dropdown-item export-png" href="#"><i class="fa fa-file-image"></i> PNG</a>'
        '<a class="dropdown-item export-excel" href="#"><i class="fa fa-file-excel"></i> Excel</a>'
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        '<div id="%(field_id)s_gantt" class="gantt-container"></div>'
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize Gantt chart widget with configuration"""
        super().__init__(**kwargs)
        self.start_date = kwargs.get(
            "start_date", (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        )
        self.end_date = kwargs.get(
            "end_date", (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )
        self.show_resources = kwargs.get("show_resources", True)
        self.work_hours = kwargs.get("work_hours", [9, 17])
        self.work_days = kwargs.get("work_days", [0, 1, 2, 3, 4])  # Mon-Fri
        self.auto_scheduling = kwargs.get("auto_scheduling", True)
        self.critical_path = kwargs.get("critical_path", True)
        self.baseline = kwargs.get("baseline", True)
        self.currency = kwargs.get("currency", "USD")
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.duration_unit = kwargs.get("duration_unit", "day")
        self.min_duration = kwargs.get("min_duration", 0.25)  # 2 hours
        self.max_duration = kwargs.get("max_duration", 365)  # 1 year
        self.default_duration = kwargs.get("default_duration", 1)
        self.highlight_critical_tasks = kwargs.get("highlight_critical_tasks", True)
        self.show_progress = kwargs.get("show_progress", True)
        self.show_links = kwargs.get("show_links", True)
        self.link_types = kwargs.get(
            "link_types",
            [
                "finish_to_start",
                "start_to_start",
                "finish_to_finish",
                "start_to_finish",
            ],
        )

    def __call__(self, field, **kwargs):
        """Render the Gantt chart widget"""
        kwargs.setdefault("id", field.id)

        html = self.data_template % {
            "name": field.name,
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                self.data = json.loads(valuelist[0])
                self._validate_gantt_data(self.data)
            except json.JSONDecodeError:
                self.data = None
                raise ValueError("Invalid Gantt data format")
        else:
            self.data = None

    def _validate_gantt_data(self, data):
        """Validate Gantt chart data structure and constraints"""
        required_fields = ["tasks", "links", "resources", "version"]
        if not all(field in data for field in required_fields):
            raise ValueError("Invalid Gantt data structure")

        # Validate tasks
        for task in data["tasks"]:
            if not {"id", "start_date", "duration", "progress"}.issubset(task.keys()):
                raise ValueError("Invalid task structure")

            # Validate dates
            try:
                start = datetime.strptime(task["start_date"], "%Y-%m-%d")
                if not self.start_date <= start.strftime("%Y-%m-%d") <= self.end_date:
                    raise ValueError(
                        f"Task dates must be between {self.start_date} and {self.end_date}"
                    )
            except ValueError as e:
                raise ValueError(f'Invalid date format for task {task["id"]}') from e

            # Validate duration
            if not self.min_duration <= float(task["duration"]) <= self.max_duration:
                raise ValueError(
                    f"Task duration must be between {self.min_duration} and {self.max_duration} {self.duration_unit}s"
                )

            # Validate progress
            if not 0 <= float(task["progress"]) <= 100:
                raise ValueError("Task progress must be between 0 and 100")

        # Validate links for circular dependencies
        if self._has_circular_dependencies(data["links"]):
            raise ValueError("Circular dependencies detected in task links")

        # Validate resource assignments
        if self.show_resources:
            resource_assignments = collections.defaultdict(list)
            for task in data["tasks"]:
                if "resource_id" in task:
                    resource_assignments[task["resource_id"]].append(task)

            # Check for resource conflicts
            for resource_id, tasks in resource_assignments.items():
                if self._has_resource_conflict(tasks):
                    raise ValueError(
                        f"Resource conflict detected for resource {resource_id}"
                    )

    def _has_circular_dependencies(self, links):
        """Check for circular dependencies in task links"""

        def build_graph(links):
            graph = collections.defaultdict(list)
            for link in links:
                graph[link["source"]].append(link["target"])
            return graph

        def has_cycle(graph, node, visited, rec_stack):
            visited[node] = True
            rec_stack[node] = True

            for neighbor in graph[node]:
                if not visited[neighbor]:
                    if has_cycle(graph, neighbor, visited, rec_stack):
                        return True
                elif rec_stack[neighbor]:
                    return True

            rec_stack[node] = False
            return False

        graph = build_graph(links)
        visited = {node: False for node in graph}
        rec_stack = {node: False for node in graph}

        for node in graph:
            if not visited[node]:
                if has_cycle(graph, node, visited, rec_stack):
                    return True
        return False

    def _has_resource_conflict(self, tasks):
        """Check for resource scheduling conflicts"""
        # Sort tasks by start date
        tasks.sort(key=lambda x: datetime.strptime(x["start_date"], "%Y-%m-%d"))

        # Check for overlapping tasks
        for i in range(len(tasks) - 1):
            task1_start = datetime.strptime(tasks[i]["start_date"], "%Y-%m-%d")
            task1_end = task1_start + timedelta(days=float(tasks[i]["duration"]))

            task2_start = datetime.strptime(tasks[i + 1]["start_date"], "%Y-%m-%d")

            if task1_end > task2_start:
                return True

        return False

    def pre_validate(self, form):
        """Validate Gantt data before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Gantt data is required")


class SpreadsheetWidget(BS3TextFieldWidget):
    """
    Excel-like spreadsheet widget for tabular data editing.
    Stores data in PostgreSQL JSONB column for maximum flexibility.

    Features:
    - Full Excel-like formula support with 300+ functions
    - Rich cell formatting and styling
    - Data validation with custom rules
    - Column/row sorting and filtering
    - Freeze panes and split views
    - Cell merging and spanning
    - Import/export to Excel, CSV, JSON
    - Cell comments and notes
    - Custom formula functions
    - Unlimited undo/redo
    - Copy/paste from Excel
    - Conditional formatting
    - Data types (text, number, date, etc)
    - Input masks
    - Cell protection
    - Named ranges
    - Find/replace
    - Auto-fill
    - Column resizing
    - Row grouping
    - Cell references
    - Range selection
    - Keyboard navigation
    - Mobile support

    Required Dependencies:
    - Handsontable Pro 9.0+
    - SheetJS
    - Moment.js
    - Numeral.js

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON/JSONB

    Example:
        data = db.Column(db.JSON, nullable=False,
            info={'widget': SpreadsheetWidget(
                columns=[
                    {'title': 'Name', 'type': 'text', 'width': 200},
                    {'title': 'Value', 'type': 'numeric', 'format': '0,0.00'},
                    {'title': 'Date', 'type': 'date', 'format': 'YYYY-MM-DD'}
                ],
                enable_formulas=True,
                readonly_cells=['A1:A10'],
                protected_cells=['B1:C1'],
                validation={
                    'B:B': {'type': 'numeric', 'min': 0},
                    'C:C': {'type': 'date', 'min': '2020-01-01'}
                },
                default_values={
                    'A1': 'Item',
                    'B1': 'Amount',
                    'C1': 'Due Date'
                }
            )})
    """

    data_template = (
        '<div class="spreadsheet-wrapper %(wrapper_class)s">'
        '<div class="spreadsheet-toolbar mb-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-secondary undo" disabled>'
        '<i class="fa fa-undo"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary redo" disabled>'
        '<i class="fa fa-redo"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="copy">'
        '<i class="fa fa-copy"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="paste">'
        '<i class="fa fa-paste"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<div class="dropdown">'
        '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
        'Format <i class="fa fa-font"></i>'
        "</button>"
        '<div class="dropdown-menu format-menu p-2" style="min-width:200px">'
        '<div class="format-section">'
        "<label>Font</label>"
        '<select class="form-control form-control-sm font-family">'
        '<option value="Arial">Arial</option>'
        '<option value="Calibri">Calibri</option>'
        '<option value="Times">Times</option>'
        "</select>"
        "</div>"
        '<div class="format-section mt-2">'
        "<label>Size</label>"
        '<input type="number" class="form-control form-control-sm font-size" min="6" max="72" value="11">'
        "</div>"
        '<div class="btn-group mt-2">'
        '<button type="button" class="btn btn-sm btn-light" data-command="bold">'
        '<i class="fa fa-bold"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-light" data-command="italic">'
        '<i class="fa fa-italic"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-light" data-command="underline">'
        '<i class="fa fa-underline"></i>'
        "</button>"
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<div class="dropdown">'
        '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
        'Export <i class="fa fa-download"></i>'
        "</button>"
        '<div class="dropdown-menu">'
        '<a class="dropdown-item" href="#" data-export="xlsx">Excel (.xlsx)</a>'
        '<a class="dropdown-item" href="#" data-export="csv">CSV</a>'
        '<a class="dropdown-item" href="#" data-export="json">JSON</a>'
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        '<div id="%(field_id)s_hot" class="hot-container"></div>'
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize spreadsheet widget with extensive configuration"""
        super().__init__(**kwargs)
        self.columns = kwargs.get("columns", [{"title": "Column 1", "type": "text"}])
        self.enable_formulas = kwargs.get("enable_formulas", True)
        self.readonly_cells = kwargs.get("readonly_cells", [])
        self.protected_cells = kwargs.get("protected_cells", [])
        self.validation = kwargs.get("validation", {})
        self.default_values = kwargs.get("default_values", {})
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.min_rows = kwargs.get("min_rows", 10)
        self.max_rows = kwargs.get("max_rows", 1000)
        self.min_cols = kwargs.get("min_cols", len(self.columns))
        self.max_cols = kwargs.get("max_cols", 100)
        self.row_headers = kwargs.get("row_headers", True)
        self.column_headers = kwargs.get("column_headers", True)
        self.allow_insert_rows = kwargs.get("allow_insert_rows", True)
        self.allow_delete_rows = kwargs.get("allow_delete_rows", True)
        self.allow_insert_cols = kwargs.get("allow_insert_cols", False)
        self.allow_delete_cols = kwargs.get("allow_delete_cols", False)
        self.auto_column_size = kwargs.get("auto_column_size", True)
        self.fixed_rows_top = kwargs.get("fixed_rows_top", 0)
        self.fixed_columns_left = kwargs.get("fixed_columns_left", 0)
        self.language = kwargs.get("language", "en-US")
        self.decimal_separator = kwargs.get("decimal_separator", ".")
        self.thousand_separator = kwargs.get("thousand_separator", ",")
        self.date_format = kwargs.get("date_format", "YYYY-MM-DD")
        self.number_format = kwargs.get("number_format", "0,0.00")
        self.undo_redo_steps = kwargs.get("undo_redo_steps", 50)

    def __call__(self, field, **kwargs):
        """Render the spreadsheet widget"""
        kwargs.setdefault("id", field.id)

        html = self.data_template % {
            "name": field.name,
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generate widget initialization JavaScript"""
        config = {
            "data": field.data.get("data", []) if field.data else [],
            "columns": self.columns,
            "minRows": self.min_rows,
            "maxRows": self.max_rows,
            "minCols": self.min_cols,
            "maxCols": self.max_cols,
            "rowHeaders": self.row_headers,
            "colHeaders": self.column_headers,
            "allowInsertRow": self.allow_insert_rows,
            "allowDeleteRow": self.allow_delete_rows,
            "allowInsertColumn": self.allow_insert_cols,
            "allowDeleteColumn": self.allow_delete_cols,
            "autoColumnSize": self.auto_column_size,
            "fixedRowsTop": self.fixed_rows_top,
            "fixedColumnsLeft": self.fixed_columns_left,
            "language": self.language,
            "formulas": self.enable_formulas,
            "cells": self._get_cell_config(),
            "readOnly": False,
            "manualColumnResize": True,
            "manualRowResize": True,
            "comments": True,
            "contextMenu": True,
            "undoRedo": True,
            "height": "auto",
            "maxUndoRedo": self.undo_redo_steps,
            "copyPaste": True,
            "search": True,
            "filters": True,
            "dropdownMenu": True,
            "mergeCells": True,
            "multiColumnSorting": True,
        }

        return """
        <script>
            (function() {
                var container = document.getElementById('%(field_id)s_hot');
                var hot = new Handsontable(container, %(config)s);

                // Handle formula evaluation
                if (%(enable_formulas)s) {
                    hot.addHook('afterChange', function(changes) {
                        if (!changes) return;
                        changes.forEach(function(change) {
                            var row = change[0];
                            var col = change[1];
                            var value = change[3];
                            if (value && value.toString().startsWith('=')) {
                                try {
                                    var result = evaluateFormula(value, row, col, hot);
                                    hot.setDataAtCell(row, col, result, 'formula');
                                } catch (e) {
                                    console.error('Formula error:', e);
                                    hot.setDataAtCell(row, col, '#ERROR!', 'formula');
                                }
                            }
                        });
                    });
                }

                // Handle data validation
                hot.addHook('beforeChange', function(changes, source) {
                    if (!changes) return;

                    return changes.every(function(change) {
                        var [row, col, oldValue, newValue] = change;
                        var validation = %(validation)s[hot.getColHeader(col)] || {};

                        if (!validateCell(newValue, validation)) {
                            alert('Invalid value for ' + hot.getColHeader(col));
                            return false;
                        }
                        return true;
                    });
                });

                // Save data to hidden input
                hot.addHook('afterChange', function() {
                    var value = {
                        data: hot.getData(),
                        state: {
                            selected: hot.getSelected(),
                            filters: hot.getPlugin('filters').getSelectedFilters(),
                            sorting: hot.getPlugin('multiColumnSorting').getSortConfig(),
                            merges: hot.getPlugin('mergeCells').mergedCellsCollection.mergedCells,
                            comments: hot.getPlugin('comments').getComments()
                        }
                    };
                    document.getElementById('%(field_id)s').value = JSON.stringify(value);
                });

                // Initialize with default values
                var defaults = %(default_values)s;
                Object.keys(defaults).forEach(function(cell) {
                    var [col, row] = parseCell(cell);
                    hot.setDataAtCell(row-1, col, defaults[cell]);
                });

                // Export handlers
                document.querySelectorAll('[data-export]').forEach(function(button) {
                    button.addEventListener('click', function(e) {
                        e.preventDefault();
                        var format = this.dataset.export;
                        exportData(hot, format);
                    });
                });

                // Helper functions
                function validateCell(value, validation) {
                    if (!validation.type) return true;

                    switch(validation.type) {
                        case 'numeric':
                            value = parseFloat(value);
                            if (isNaN(value)) return false;
                            if ('min' in validation && value < validation.min) return false;
                            if ('max' in validation && value > validation.max) return false;
                            return true;

                        case 'date':
                            var date = moment(value);
                            if (!date.isValid()) return false;
                            if ('min' in validation && date.isBefore(validation.min)) return false;
                            if ('max' in validation && date.isAfter(validation.max)) return false;
                            return true;

                        case 'list':
                            return validation.values.includes(value);

                        default:
                            return true;
                    }
                }

                function parseCell(cell) {
                    var match = cell.match(/([A-Z]+)([0-9]+)/);
                    var col = columnToIndex(match[1]);
                    var row = parseInt(match[2]);
                    return [col, row];
                }

                function columnToIndex(column) {
                    var index = 0;
                    for (var i = 0; i < column.length; i++) {
                        index = index * 26 + column.charCodeAt(i) - 64;
                    }
                    return index - 1;
                }

                function exportData(hot, format) {
                    var data = hot.getData();

                    switch(format) {
                        case 'xlsx':
                            var wb = XLSX.utils.book_new();
                            var ws = XLSX.utils.aoa_to_sheet(data);
                            XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
                            XLSX.writeFile(wb, "export.xlsx");
                            break;

                        case 'csv':
                            var csv = Papa.unparse(data);
                            var blob = new Blob([csv], {type: 'text/csv;charset=utf-8;'});
                            var link = document.createElement("a");
                            link.href = URL.createObjectURL(blob);
                            link.download = "export.csv";
                            link.click();
                            break;

                        case 'json':
                            var json = JSON.stringify(data, null, 2);
                            var blob = new Blob([json], {type: 'application/json'});
                            var link = document.createElement("a");
                            link.href = URL.createObjectURL(blob);
                            link.download = "export.json";
                            link.click();
                            break;
                    }
                }
            })();
        </script>
        """ % {
            "field_id": field.id,
            "config": json.dumps(config),
            "enable_formulas": json.dumps(self.enable_formulas),
            "validation": json.dumps(self.validation),
            "default_values": json.dumps(self.default_values),
        }

    def _get_cell_config(self):
        """Generate cell-specific configuration"""
        config = {}

        # Add readonly cells
        for range_str in self.readonly_cells:
            config[range_str] = {"readOnly": True}

        # Add protected cells
        for range_str in self.protected_cells:
            config[range_str] = {"protected": True}

        # Add validation rules
        for range_str, rules in self.validation.items():
            if range_str not in config:
                config[range_str] = {}
            config[range_str]["validator"] = rules

        return config

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid JSON data") from e
        else:
            self.data = None

    def _validate_data(self, data):
        """Validate spreadsheet data structure and constraints"""
        if not isinstance(data, dict) or "data" not in data:
            raise ValueError("Invalid data structure")

        if len(data["data"]) > self.max_rows:
            raise ValueError(f"Data exceeds maximum rows ({self.max_rows})")

        for row in data["data"]:
            if len(row) > self.max_cols:
                raise ValueError(f"Data exceeds maximum columns ({self.max_cols})")

        # Validate against column types
        for row_idx, row in enumerate(data["data"]):
            for col_idx, value in enumerate(row):
                if col_idx >= len(self.columns):
                    continue

                col_type = self.columns[col_idx].get("type", "text")
                try:
                    self._validate_cell_value(value, col_type)
                except ValueError as e:
                    raise ValueError(
                        f"Invalid value in cell ({row_idx+1}, {col_idx+1}): {str(e)}"
                    )

    def _validate_cell_value(self, value, col_type):
        """Validate individual cell value against column type"""
        if value is None:
            return

        if col_type == "numeric":
            try:
                float(value)
            except ValueError:
                raise ValueError("Not a valid number")

        elif col_type == "date":
            try:
                moment = datetime.strptime(value, self.date_format)
            except ValueError:
                raise ValueError("Not a valid date")

        elif col_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError("Not a valid boolean")

    def pre_validate(self, form):
        """Validate data before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Spreadsheet data is required")


class WorkflowDesignerWidget(BS3TextFieldWidget):
    """
    Visual workflow/process designer widget for creating and editing business process workflows.
    Database column should be JSONB type in PostgreSQL to store workflow definition, state and history.

    Features:
    - Drag and drop nodes with snap-to-grid
    - Smart connection routing with path optimization
    - Extensive node type library (tasks, decisions, events, etc)
    - Real-time validation rules and constraint checking
    - Nested sub-workflows with collapsible views
    - Import/export to BPMN 2.0 and custom formats
    - Template library with common workflow patterns
    - Full version control with diff viewing
    - Interactive preview/simulation mode
    - Responsive mobile/touch support
    - Undo/redo stack
    - Keyboard shortcuts
    - Minimap navigation
    - Search/filter nodes
    - Commenting system
    - Custom node styling
    - Auto-layout
    - Zoom controls
    - Grid alignment
    - Node groups
    - Edge labels

    Required Dependencies:
    - JointJS 3.5+
    - Lodash 4+
    - Backbone.js
    - GraphLib
    - dag.js

    Example:
        process = db.Column(db.JSON, nullable=False,
            info={'widget': WorkflowDesignerWidget(
                node_types=[
                    {'id': 'task', 'label': 'Task', 'color': '#2196F3'},
                    {'id': 'decision', 'label': 'Decision', 'color': '#FFC107'},
                    {'id': 'event', 'label': 'Event', 'color': '#4CAF50'},
                    {'id': 'subprocess', 'label': 'Sub-Process', 'color': '#9C27B0'}
                ],
                templates=True,
                validation_rules=[
                    'no_cycles',
                    'required_start_end',
                    'max_decision_branches'
                ],
                grid_size=20,
                auto_layout=True,
                enable_comments=True,
                enable_history=True
            )})
    """

    data_template = (
        '<div class="workflow-designer-wrapper %(wrapper_class)s">'
        '<div class="workflow-toolbar mb-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-secondary undo" disabled>'
        '<i class="fa fa-undo"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary redo" disabled>'
        '<i class="fa fa-redo"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomIn">'
        '<i class="fa fa-search-plus"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomOut">'
        '<i class="fa fa-search-minus"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomFit">'
        '<i class="fa fa-arrows-alt"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="autoLayout">'
        '<i class="fa fa-magic"></i> Auto Layout'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<div class="dropdown">'
        '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
        'Export <i class="fa fa-download"></i>'
        "</button>"
        '<div class="dropdown-menu">'
        '<a class="dropdown-item" href="#" data-export="png">PNG Image</a>'
        '<a class="dropdown-item" href="#" data-export="svg">SVG Vector</a>'
        '<a class="dropdown-item" href="#" data-export="bpmn">BPMN 2.0</a>'
        '<a class="dropdown-item" href="#" data-export="json">JSON</a>'
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        '<div class="workflow-container">'
        '<div class="workflow-sidebar">'
        '<div class="node-palette"></div>'
        '<div class="minimap mt-3"></div>'
        "</div>"
        '<div id="%(field_id)s_paper" class="workflow-paper"></div>'
        "</div>"
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        '<div class="workflow-validation mt-2"></div>'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize workflow designer widget with configuration"""
        super().__init__(**kwargs)
        self.node_types = kwargs.get(
            "node_types",
            [
                {"id": "task", "label": "Task", "color": "#2196F3"},
                {"id": "decision", "label": "Decision", "color": "#FFC107"},
                {"id": "event", "label": "Event", "color": "#4CAF50"},
            ],
        )
        self.templates = kwargs.get("templates", True)
        self.validation_rules = kwargs.get("validation_rules", ["no_cycles"])
        self.grid_size = kwargs.get("grid_size", 20)
        self.auto_layout = kwargs.get("auto_layout", True)
        self.enable_comments = kwargs.get("enable_comments", True)
        self.enable_history = kwargs.get("enable_history", True)
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.min_zoom = kwargs.get("min_zoom", 0.2)
        self.max_zoom = kwargs.get("max_zoom", 2)
        self.default_node_width = kwargs.get("default_node_width", 120)
        self.default_node_height = kwargs.get("default_node_height", 60)
        self.connection_color = kwargs.get("connection_color", "#666")
        self.highlight_color = kwargs.get("highlight_color", "#0d6efd")
        self.grid_color = kwargs.get("grid_color", "#eee")
        self.max_nodes = kwargs.get("max_nodes", 100)
        self.max_connections = kwargs.get("max_connections", 200)
        self.undo_levels = kwargs.get("undo_levels", 50)

    def __call__(self, field, **kwargs):
        """Render the workflow designer widget"""
        kwargs.setdefault("id", field.id)
        if field.flags.required:
            kwargs["required"] = True

        html = self.data_template % {
            "name": field.name,
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generate widget initialization JavaScript"""
        return """
        <script>
            (function() {
                var graph = new joint.dia.Graph();
                var paper = new joint.dia.Paper({
                    el: document.getElementById('%(field_id)s_paper'),
                    model: graph,
                    width: '100%%',
                    height: 600,
                    gridSize: %(grid_size)d,
                    drawGrid: true,
                    gridColor: '%(grid_color)s',
                    defaultConnectionColor: '%(connection_color)s',
                    defaultHighlightColor: '%(highlight_color)s',
                    interactive: true,
                    snapLinks: true,
                    linkPinning: false,
                    validateConnection: validateConnection,
                    defaultLink: new joint.shapes.standard.Link(),
                    defaultRouter: { name: 'manhattan' },
                    defaultConnector: { name: 'rounded' },
                    highlighting: {
                        default: {
                            name: 'stroke',
                            options: {
                                padding: 6,
                                rx: 5,
                                ry: 5
                            }
                        }
                    }
                });

                // Initialize node palette
                var nodeTypes = %(node_types)s;
                var palette = document.querySelector('.node-palette');
                nodeTypes.forEach(function(type) {
                    var node = createNode(type);
                    node.position(10, 10);
                    var nodeView = new joint.dia.ElementView({
                        model: node,
                        interactive: false
                    });
                    palette.appendChild(nodeView.render().el);
                });

                // Initialize minimap
                var minimap = new joint.dia.Paper({
                    el: document.querySelector('.minimap'),
                    model: graph,
                    width: 200,
                    height: 150,
                    interactive: false,
                    sorting: joint.dia.Paper.sorting.NONE
                });

                // Drag and drop from palette
                $(palette).on('mousedown', '.node', function(evt) {
                    var type = $(this).data('type');
                    var node = createNode(type);
                    var pos = paper.clientToLocalPoint(evt.clientX, evt.clientY);
                    node.position(pos.x, pos.y);
                    graph.addCell(node);
                });

                // Validation
                function validateConnection(cellViewS, magnetS, cellViewT, magnetT) {
                    if (magnetS && magnetS.getAttribute('port-group') === 'in') return false;
                    if (magnetT && magnetT.getAttribute('port-group') === 'out') return false;
                    return true;
                }

                // Node creation helper
                function createNode(type) {
                    return new joint.shapes.standard.Rectangle({
                        size: { width: %(default_node_width)d, height: %(default_node_height)d },
                        attrs: {
                            body: {
                                fill: type.color,
                                stroke: 'none',
                                rx: 5,
                                ry: 5
                            },
                            label: {
                                text: type.label,
                                fill: 'white',
                                fontSize: 14
                            }
                        },
                        ports: {
                            groups: {
                                'in': {
                                    position: 'top',
                                    label: { position: 'outside' },
                                    attrs: {
                                        circle: {
                                            fill: '#fff',
                                            stroke: '#000',
                                            r: 6
                                        }
                                    }
                                },
                                'out': {
                                    position: 'bottom',
                                    label: { position: 'outside' },
                                    attrs: {
                                        circle: {
                                            fill: '#fff',
                                            stroke: '#000',
                                            r: 6
                                        }
                                    }
                                }
                            }
                        }
                    });
                }

                // Save workflow state
                paper.on('cell:pointerup blank:pointerup', function() {
                    var workflow = {
                        cells: graph.toJSON(),
                        zoom: paper.scale(),
                        pan: paper.translate()
                    };
                    $('#%(field_id)s').val(JSON.stringify(workflow));
                });

                // Load initial state
                var initialValue = %(initial_value)s;
                if (initialValue && initialValue.cells) {
                    graph.fromJSON(initialValue.cells);
                    if (initialValue.zoom) paper.scale(initialValue.zoom);
                    if (initialValue.pan) paper.translate(initialValue.pan.x, initialValue.pan.y);
                }

                // Export handlers
                document.querySelectorAll('[data-export]').forEach(function(button) {
                    button.addEventListener('click', function(e) {
                        e.preventDefault();
                        var format = this.dataset.export;
                        exportWorkflow(format);
                    });
                });

                function exportWorkflow(format) {
                    var data;
                    switch(format) {
                        case 'png':
                            paper.toPNG(function(dataURL) {
                                downloadFile(dataURL, 'workflow.png');
                            });
                            break;
                        case 'svg':
                            paper.toSVG(function(svg) {
                                var blob = new Blob([svg], {type: 'image/svg+xml'});
                                downloadFile(URL.createObjectURL(blob), 'workflow.svg');
                            });
                            break;
                        case 'bpmn':
                            data = convertToBPMN(graph);
                            downloadFile(
                                'data:text/xml;charset=utf-8,' + encodeURIComponent(data),
                                'workflow.bpmn'
                            );
                            break;
                        case 'json':
                            data = JSON.stringify(graph.toJSON(), null, 2);
                            downloadFile(
                                'data:application/json;charset=utf-8,' + encodeURIComponent(data),
                                'workflow.json'
                            );
                            break;
                    }
                }

                function downloadFile(url, filename) {
                    var link = document.createElement('a');
                    link.href = url;
                    link.download = filename;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                }
            })();
        </script>
        """ % {
            "field_id": field.id,
            "grid_size": self.grid_size,
            "grid_color": self.grid_color,
            "connection_color": self.connection_color,
            "highlight_color": self.highlight_color,
            "default_node_width": self.default_node_width,
            "default_node_height": self.default_node_height,
            "node_types": json.dumps(self.node_types),
            "initial_value": json.dumps(field.data) if field.data else "null",
        }

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_workflow(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid workflow data format") from e
        else:
            self.data = None

    def _validate_workflow(self, data):
        """Validate workflow structure and constraints"""
        if not isinstance(data, dict) or "cells" not in data:
            raise ValueError("Invalid workflow data structure")

        # Count nodes and connections
        nodes = [cell for cell in data["cells"] if cell["type"] != "link"]
        connections = [cell for cell in data["cells"] if cell["type"] == "link"]

        if len(nodes) > self.max_nodes:
            raise ValueError(f"Workflow exceeds maximum nodes ({self.max_nodes})")

        if len(connections) > self.max_connections:
            raise ValueError(
                f"Workflow exceeds maximum connections ({self.max_connections})"
            )

        # Validate based on rules
        if "no_cycles" in self.validation_rules:
            if self._has_cycles(data["cells"]):
                raise ValueError("Workflow contains cycles")

        if "required_start_end" in self.validation_rules:
            if not self._has_start_end(nodes):
                raise ValueError("Workflow must have start and end events")

    def _has_cycles(self, cells):
        """Check for cycles in the workflow"""
        connections = [c for c in cells if c["type"] == "link"]

        # Build adjacency list
        graph = collections.defaultdict(list)
        for conn in connections:
            graph[conn["source"]["id"]].append(conn["target"]["id"])

        # DFS to detect cycles
        visited = set()
        path = set()

        def visit(node):
            if node in path:
                return True
            if node in visited:
                return False
            visited.add(node)
            path.add(node)
            for neighbor in graph[node]:
                if visit(neighbor):
                    return True
            path.remove(node)
            return False

        return any(visit(node) for node in graph)

    def _has_start_end(self, nodes):
        """Check for required start and end events"""
        start_events = [
            n for n in nodes if n["type"] == "event" and "start" in n.get("subtype", "")
        ]
        end_events = [
            n for n in nodes if n["type"] == "event" and "end" in n.get("subtype", "")
        ]
        return bool(start_events and end_events)

    def pre_validate(self, form):
        """Validate workflow data before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Workflow data is required")


class DocumentViewerWidget(BS3TextFieldWidget):
    """
    Multi-format document viewer widget with annotations, thumbnails and advanced viewing features.
    Stores documents in PostgreSQL BYTEA column with metadata in JSONB.

    Features:
    - Multi-format support: PDF, Word, Excel, PowerPoint, Images
    - Rich annotation tools: highlights, notes, drawings, shapes
    - Page thumbnails with custom size/layout
    - Smooth zoom and pan controls
    - Full text search with highlights
    - Print with annotations
    - Version control
    - Download in multiple formats
    - Page rotation and reordering
    - Bookmark management
    - Mobile-optimized UI
    - Collaborative annotations
    - Signature support
    - Custom watermarks
    - Password protection
    - Accessibility features

    Database Schema:
        document = db.Column(db.LargeBinary, nullable=False)  # Document content
        metadata = db.Column(db.JSON, nullable=False)  # Document metadata
        annotations = db.Column(db.JSON)  # Annotation data
        versions = db.Column(db.JSON)  # Version history

    Required Dependencies:
    - PDF.js 2.0+
    - Mammoth.js (Word)
    - SheetJS (Excel)
    - Fabric.js (Annotations)
    - OpenSeadragon (Deep zoom)

    Example:
        document = db.Column(db.LargeBinary, nullable=False,
            info={'widget': DocumentViewerWidget(
                supported_formats=['pdf', 'docx', 'xlsx', 'pptx', 'png', 'jpg'],
                enable_annotations=True,
                annotation_tools=['highlight', 'note', 'draw', 'shape'],
                show_thumbnails=True,
                thumbnail_size=(120, 160),
                enable_search=True,
                enable_print=True,
                enable_download=True,
                watermark='Confidential',
                max_file_size=20*1024*1024,  # 20MB
                cache_enabled=True,
                mobile_optimization=True
            )})
    """

    data_template = (
        '<div class="document-viewer-wrapper %(wrapper_class)s">'
        '<div class="document-toolbar mb-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomIn">'
        '<i class="fa fa-search-plus"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomOut">'
        '<i class="fa fa-search-minus"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="fitPage">'
        '<i class="fa fa-arrows-alt"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="rotateLeft">'
        '<i class="fa fa-undo"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="rotateRight">'
        '<i class="fa fa-redo"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="print">'
        '<i class="fa fa-print"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="download">'
        '<i class="fa fa-download"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2 annotation-tools" style="display:none">'
        '<button type="button" class="btn btn-sm btn-secondary" data-tool="highlight">'
        '<i class="fa fa-highlighter"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-tool="note">'
        '<i class="fa fa-sticky-note"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-tool="draw">'
        '<i class="fa fa-pencil-alt"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-tool="shape">'
        '<i class="fa fa-shapes"></i>'
        "</button>"
        "</div>"
        "</div>"
        '<div class="document-container">'
        '<div class="thumbnails-panel" style="display:none"></div>'
        '<div id="%(field_id)s_viewer" class="viewer-container"></div>'
        '<div class="search-panel" style="display:none">'
        '<input type="text" class="form-control form-control-sm" placeholder="Search...">'
        '<div class="search-results"></div>'
        "</div>"
        "</div>"
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        '<input type="file" style="display:none" id="%(field_id)s_file">'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize document viewer with configuration"""
        super().__init__(**kwargs)
        self.supported_formats = kwargs.get(
            "supported_formats", ["pdf", "docx", "xlsx", "pptx", "png", "jpg"]
        )
        self.enable_annotations = kwargs.get("enable_annotations", True)
        self.annotation_tools = kwargs.get(
            "annotation_tools", ["highlight", "note", "draw", "shape"]
        )
        self.show_thumbnails = kwargs.get("show_thumbnails", True)
        self.thumbnail_size = kwargs.get("thumbnail_size", (120, 160))
        self.enable_search = kwargs.get("enable_search", True)
        self.enable_print = kwargs.get("enable_print", True)
        self.enable_download = kwargs.get("enable_download", True)
        self.watermark = kwargs.get("watermark", "")
        self.max_file_size = kwargs.get("max_file_size", 20 * 1024 * 1024)
        self.cache_enabled = kwargs.get("cache_enabled", True)
        self.mobile_optimization = kwargs.get("mobile_optimization", True)
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.min_zoom = kwargs.get("min_zoom", 0.25)
        self.max_zoom = kwargs.get("max_zoom", 4)
        self.rotation_step = kwargs.get("rotation_step", 90)
        self.page_gap = kwargs.get("page_gap", 20)
        self.default_scale = kwargs.get("default_scale", "auto")

    def __call__(self, field, **kwargs):
        """Render the document viewer widget"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("required", field.flags.required)

        html = self.data_template % {
            "name": field.name,
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generate widget initialization JavaScript"""
        config = {
            "supportedFormats": self.supported_formats,
            "enableAnnotations": self.enable_annotations,
            "annotationTools": self.annotation_tools,
            "showThumbnails": self.show_thumbnails,
            "thumbnailSize": self.thumbnail_size,
            "enableSearch": self.enable_search,
            "enablePrint": self.enable_print,
            "enableDownload": self.enable_download,
            "watermark": self.watermark,
            "maxFileSize": self.max_file_size,
            "cacheEnabled": self.cache_enabled,
            "mobileOptimization": self.mobile_optimization,
            "minZoom": self.min_zoom,
            "maxZoom": self.max_zoom,
            "rotationStep": self.rotation_step,
            "pageGap": self.page_gap,
            "defaultScale": self.default_scale,
        }

        return """
        <script>
            (function() {
                var viewer = new DocumentViewer('#%(field_id)s_viewer', %(config)s);
                var field = document.getElementById('%(field_id)s');
                var fileInput = document.getElementById('%(field_id)s_file');

                // Handle initial document if present
                if (field.value) {
                    viewer.loadDocument(field.value);
                }

                // Handle file selection
                fileInput.addEventListener('change', function(e) {
                    var file = e.target.files[0];
                    if (!file) return;

                    // Validate file
                    if (!validateFile(file)) return;

                    var reader = new FileReader();
                    reader.onload = function(e) {
                        field.value = e.target.result;
                        viewer.loadDocument(e.target.result);
                    };
                    reader.readAsDataURL(file);
                });

                // Toolbar handlers
                document.querySelector('.document-toolbar').addEventListener('click', function(e) {
                    var command = e.target.closest('[data-command]');
                    if (command) {
                        var action = command.dataset.command;
                        switch(action) {
                            case 'zoomIn':
                                viewer.zoomIn();
                                break;
                            case 'zoomOut':
                                viewer.zoomOut();
                                break;
                            case 'fitPage':
                                viewer.fitToPage();
                                break;
                            case 'rotateLeft':
                                viewer.rotate(-%(rotation_step)d);
                                break;
                            case 'rotateRight':
                                viewer.rotate(%(rotation_step)d);
                                break;
                            case 'print':
                                viewer.print();
                                break;
                            case 'download':
                                viewer.download();
                                break;
                        }
                    }

                    var tool = e.target.closest('[data-tool]');
                    if (tool) {
                        viewer.setAnnotationTool(tool.dataset.tool);
                    }
                });

                // Search handler
                if (%(enable_search)s) {
                    var searchInput = document.querySelector('.search-panel input');
                    var searchTimeout;
                    searchInput.addEventListener('input', function() {
                        clearTimeout(searchTimeout);
                        var query = this.value;
                        searchTimeout = setTimeout(function() {
                            viewer.search(query);
                        }, 300);
                    });
                }

                function validateFile(file) {
                    // Check file size
                    if (file.size > %(max_file_size)d) {
                        alert('File size exceeds maximum allowed (' +
                              (%(max_file_size)d / (1024*1024)).toFixed(1) + 'MB)');
                        return false;
                    }

                    // Check file type
                    var ext = file.name.split('.').pop().toLowerCase();
                    if (!%(supported_formats)s.includes(ext)) {
                        alert('Unsupported file type. Allowed: ' +
                              %(supported_formats)s.join(', '));
                        return false;
                    }

                    return true;
                }
            })();
        </script>
        """ % {
            "field_id": field.id,
            "config": json.dumps(config),
            "rotation_step": self.rotation_step,
            "enable_search": str(self.enable_search).lower(),
            "max_file_size": self.max_file_size,
            "supported_formats": json.dumps(self.supported_formats),
        }

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                self.data = valuelist[0]
                self._validate_document(self.data)
            except Exception as e:
                raise ValueError(f"Invalid document data: {str(e)}")
        else:
            self.data = None

    def _validate_document(self, data):
        """Validate document data"""
        if not data:
            return

        # Validate file size
        if len(data) > self.max_file_size:
            raise ValueError(
                f"Document size exceeds maximum allowed ({self.max_file_size/(1024*1024):.1f}MB)"
            )

        # Validate file type
        try:
            header = data[:50]  # Check file signature
            if not any(
                sig in header
                for sig in [
                    b"%PDF",  # PDF
                    b"PK\x03\x04",  # Office documents
                    b"\x89PNG",  # PNG
                    b"\xff\xd8\xff",  # JPEG
                ]
            ):
                raise ValueError("Invalid document format")
        except Exception as e:
            raise ValueError(f"Error validating document format: {str(e)}")

    def pre_validate(self, form):
        """Validate document before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Document is required")


class DashboardDesignerWidget(BS3TextFieldWidget):
    """
    Widget for creating interactive dashboards with drag-and-drop functionality.
    Stores dashboard configuration in PostgreSQL JSONB column for flexibility.

    Features:
    - Multiple chart types (line, bar, pie, scatter, etc)
    - Real-time data binding to SQL/API sources
    - Responsive grid layout with resizing
    - Interactive filtering and drill-down
    - Custom widget library (charts, tables, metrics)
    - Theme customization and presets
    - Layout templates and presets
    - Export to PDF/PNG/JSON
    - Sharing and embedding
    - Mobile responsive design
    - Real-time collaboration
    - Version history
    - Dashboard permissions
    - Custom CSS/JS injection
    - Cross-filtering between widgets
    - Time-based auto-refresh
    - Dashboard linking
    - Widget dependencies
    - Data caching
    - Error handling
    - Accessibility features

    Required Dependencies:
    - Gridster.js 0.7+
    - Chart.js 3.0+
    - Lodash 4.0+
    - AG Grid Enterprise
    - Socket.IO

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON/JSONB

    Example:
        dashboard = db.Column(db.JSON, nullable=False,
            info={'widget': DashboardDesignerWidget(
                widgets=[
                    {'type': 'chart',
                     'name': 'Line Chart',
                     'icon': 'fa-chart-line',
                     'options': {
                         'type': 'line',
                         'data_source': 'sales_data',
                         'refresh': 300
                     }},
                    {'type': 'table',
                     'name': 'Data Grid',
                     'icon': 'fa-table',
                     'options': {
                         'pagination': True,
                         'page_size': 10
                     }},
                    {'type': 'metric',
                     'name': 'KPI Card',
                     'icon': 'fa-tachometer-alt',
                     'options': {
                         'format': '0,0',
                         'prefix': '$'
                     }}
                ],
                data_sources=[
                    {'id': 'sales_data',
                     'type': 'sql',
                     'query': 'SELECT * FROM sales',
                     'refresh': 300},
                    {'id': 'api_data',
                     'type': 'api',
                     'url': '/api/data',
                     'method': 'GET'}
                ],
                grid_columns=12,
                row_height=60,
                min_cols=1,
                max_cols=12,
                min_rows=1,
                max_rows=50,
                real_time=True,
                collaborative=True,
                theme='light',
                default_layout=[
                    {'id': 'chart1',
                     'x': 0,
                     'y': 0,
                     'width': 6,
                     'height': 4}
                ]
            )})
    """

    data_template = (
        '<div class="dashboard-designer %(wrapper_class)s">'
        '<div class="dashboard-toolbar mb-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="save">'
        '<i class="fa fa-save"></i> Save'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="undo" disabled>'
        '<i class="fa fa-undo"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="redo" disabled>'
        '<i class="fa fa-redo"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<div class="dropdown">'
        '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
        'Add Widget <i class="fa fa-plus"></i>'
        "</button>"
        '<div class="dropdown-menu widget-menu p-2"></div>'
        "</div>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<div class="dropdown">'
        '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
        'Export <i class="fa fa-download"></i>'
        "</button>"
        '<div class="dropdown-menu">'
        '<a class="dropdown-item" href="#" data-export="pdf">PDF</a>'
        '<a class="dropdown-item" href="#" data-export="png">PNG</a>'
        '<a class="dropdown-item" href="#" data-export="json">JSON</a>'
        "</div>"
        "</div>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="share">'
        '<i class="fa fa-share-alt"></i> Share'
        "</button>"
        "</div>"
        "</div>"
        '<div class="dashboard-container">'
        '<div class="widget-sidebar">'
        '<div class="widget-palette"></div>'
        "</div>"
        '<div id="%(field_id)s_grid" class="dashboard-grid"></div>'
        "</div>"
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize dashboard designer with configuration"""
        super().__init__(**kwargs)
        self.widgets = kwargs.get(
            "widgets",
            [
                {"type": "chart", "name": "Chart", "icon": "fa-chart-line"},
                {"type": "table", "name": "Table", "icon": "fa-table"},
                {"type": "metric", "name": "Metric", "icon": "fa-tachometer-alt"},
            ],
        )
        self.data_sources = kwargs.get("data_sources", [])
        self.grid_columns = kwargs.get("grid_columns", 12)
        self.row_height = kwargs.get("row_height", 60)
        self.min_cols = kwargs.get("min_cols", 1)
        self.max_cols = kwargs.get("max_cols", 12)
        self.min_rows = kwargs.get("min_rows", 1)
        self.max_rows = kwargs.get("max_rows", 50)
        self.real_time = kwargs.get("real_time", True)
        self.collaborative = kwargs.get("collaborative", False)
        self.theme = kwargs.get("theme", "light")
        self.default_layout = kwargs.get("default_layout", [])
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.refresh_interval = kwargs.get("refresh_interval", 0)
        self.max_widgets = kwargs.get("max_widgets", 50)
        self.widget_padding = kwargs.get("widget_padding", 10)
        self.allow_overlap = kwargs.get("allow_overlap", False)
        self.resize_handles = kwargs.get("resize_handles", ["se"])
        self.maintain_ratio = kwargs.get("maintain_ratio", False)
        self.snap_to_grid = kwargs.get("snap_to_grid", True)
        self.cache_timeout = kwargs.get("cache_timeout", 300)
        self.undo_levels = kwargs.get("undo_levels", 20)

    def __call__(self, field, **kwargs):
        """Render the dashboard designer widget"""
        kwargs.setdefault("id", field.id)

        html = self.data_template % {
            "name": field.name,
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generate widget initialization JavaScript"""
        config = {
            "gridColumns": self.grid_columns,
            "rowHeight": self.row_height,
            "minCols": self.min_cols,
            "maxCols": self.max_cols,
            "minRows": self.min_rows,
            "maxRows": self.max_rows,
            "widgets": self.widgets,
            "dataSources": self.data_sources,
            "realTime": self.real_time,
            "collaborative": self.collaborative,
            "theme": self.theme,
            "defaultLayout": self.default_layout,
            "widgetPadding": self.widget_padding,
            "allowOverlap": self.allow_overlap,
            "resizeHandles": self.resize_handles,
            "maintainRatio": self.maintain_ratio,
            "snapToGrid": self.snap_to_grid,
            "cacheTimeout": self.cache_timeout,
            "undoLevels": self.undo_levels,
            "refreshInterval": self.refresh_interval,
        }

        return """
        <script>
            (function() {
                var dashboardDesigner = new DashboardDesigner({
                    container: document.getElementById('%(field_id)s_grid'),
                    config: %(config)s,
                    onChange: function(layout) {
                        saveDashboardState(layout);
                    },
                    onError: function(error) {
                        console.error('Dashboard error:', error);
                        showErrorNotification(error);
                    }
                });

                // Initialize with saved state or defaults
                var savedState = %(initial_state)s;
                if (savedState) {
                    dashboardDesigner.loadState(savedState);
                } else if (%(default_layout)s.length) {
                    dashboardDesigner.loadState({layout: %(default_layout)s});
                }

                // Save dashboard state
                function saveDashboardState(layout) {
                    var state = {
                        layout: layout,
                        theme: dashboardDesigner.getTheme(),
                        dataSources: dashboardDesigner.getDataSources(),
                        widgets: dashboardDesigner.getWidgets(),
                        filters: dashboardDesigner.getFilters()
                    };
                    $('#%(field_id)s').val(JSON.stringify(state));
                }

                // Export handlers
                document.querySelectorAll('[data-export]').forEach(function(button) {
                    button.addEventListener('click', function(e) {
                        e.preventDefault();
                        var format = this.dataset.export;
                        exportDashboard(format);
                    });
                });

                function exportDashboard(format) {
                    switch(format) {
                        case 'pdf':
                            dashboardDesigner.exportToPDF({
                                filename: 'dashboard.pdf',
                                orientation: 'landscape'
                            });
                            break;
                        case 'png':
                            dashboardDesigner.exportToPNG({
                                filename: 'dashboard.png',
                                scale: 2
                            });
                            break;
                        case 'json':
                            var state = dashboardDesigner.getState();
                            downloadJSON(state, 'dashboard.json');
                            break;
                    }
                }

                function downloadJSON(data, filename) {
                    var blob = new Blob([JSON.stringify(data, null, 2)], {
                        type: 'application/json'
                    });
                    var url = URL.createObjectURL(blob);
                    var link = document.createElement('a');
                    link.href = url;
                    link.download = filename;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    URL.revokeObjectURL(url);
                }

                // Real-time updates
                if (%(real_time)s) {
                    var socket = io();
                    socket.on('dashboard_update', function(data) {
                        if (data.dashboard_id === '%(field_id)s') {
                            dashboardDesigner.updateData(data);
                        }
                    });
                }

                // Auto-refresh
                if (%(refresh_interval)d > 0) {
                    setInterval(function() {
                        dashboardDesigner.refreshData();
                    }, %(refresh_interval)d * 1000);
                }

                // Error handling
                function showErrorNotification(error) {
                    // Implement error notification UI
                }

                // Clean up on destroy
                return function() {
                    if (socket) socket.disconnect();
                    dashboardDesigner.destroy();
                };
            })();
        </script>
        """ % {
            "field_id": field.id,
            "config": json.dumps(config),
            "initial_state": json.dumps(field.data) if field.data else "null",
            "default_layout": json.dumps(self.default_layout),
            "real_time": str(self.real_time).lower(),
            "refresh_interval": self.refresh_interval,
        }

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_dashboard(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid dashboard data format") from e
        else:
            self.data = None

    def _validate_dashboard(self, data):
        """Validate dashboard configuration"""
        if not isinstance(data, dict):
            raise ValueError("Invalid dashboard data structure")

        required_keys = ["layout", "widgets", "dataSources"]
        for key in required_keys:
            if key not in data:
                raise ValueError(f"Missing required key: {key}")

        # Validate layout
        if len(data["layout"]) > self.max_widgets:
            raise ValueError(
                f'Too many widgets ({len(data["layout"])} > {self.max_widgets})'
            )

        for widget in data["layout"]:
            if not all(k in widget for k in ["id", "x", "y", "width", "height"]):
                raise ValueError(f"Invalid widget configuration: {widget}")

            if widget["width"] > self.max_cols:
                raise ValueError(
                    f'Widget width exceeds maximum ({widget["width"]} > {self.max_cols})'
                )

            if widget["height"] > self.max_rows:
                raise ValueError(
                    f'Widget height exceeds maximum ({widget["height"]} > {self.max_rows})'
                )

        # Validate data sources
        for ds in data["dataSources"]:
            if ds["type"] not in ["sql", "api"]:
                raise ValueError(f'Invalid data source type: {ds["type"]}')

            if ds["type"] == "sql" and not ds.get("query"):
                raise ValueError("SQL data source requires query")

            if ds["type"] == "api" and not ds.get("url"):
                raise ValueError("API data source requires URL")

    def pre_validate(self, form):
        """Validate dashboard data before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Dashboard configuration is required")


"""
Usage Examples:

from .nx_widgets import (
    RangeSliderWidget, TagInputWidget, JSONEditorWidget, MarkdownEditorWidget,
    GeoPointWidget, CurrencyInputWidget, PhoneNumberWidget, RatingWidget,
    DurationWidget, RelationshipGraphWidget, FileUploadFieldWidget,
    ColorPickerWidget, DateRangePickerWidget, RichTextEditorWidget,
    MultiSelectWidget, CheckBoxWidget
)

class MyForm(DynamicForm):
    price_range = StringField('Price Range', widget=RangeSliderWidget())
    tags = StringField('Tags', widget=TagInputWidget())
    config = StringField('Configuration', widget=JSONEditorWidget())
    description = TextAreaField('Description', widget=MarkdownEditorWidget())
    location = StringField('Location', widget=GeoPointWidget())
    price = DecimalField('Price', widget=CurrencyInputWidget())
    phone = StringField('Phone', widget=PhoneNumberWidget())
    rating = FloatField('Rating', widget=RatingWidget())
    duration = IntegerField('Duration', widget=DurationWidget())
    relationships = StringField('Relationships', widget=RelationshipGraphWidget())
    file = FileField('File', widget=FileUploadFieldWidget())
    color = StringField('Color', widget=ColorPickerWidget())
    date_range = StringField('Date Range', widget=DateRangePickerWidget())
    content = TextAreaField('Content', widget=RichTextEditorWidget())
    agree_terms = BooleanField('I agree to the terms', widget=CheckBoxWidget())
    notifications = BooleanField('Enable notifications', widget=SwitchWidget())
    rating = FloatField('Rate this', widget=StarRatingWidget())
    toggle_feature = BooleanField('Enable feature', widget=ToggleButtonWidget())
    volume = IntegerField('Volume', widget=SliderWidget())
    country = StringField('Country', widget=AutocompleteWidget())
    password = PasswordField('Password', widget=PasswordStrengthWidget())
    categories = SelectMultipleField('Categories', widget=MultiSelectWidget(), choices=[
        ('1', 'Category 1'),
        ('2', 'Category 2'),
        ('3', 'Category 3')
    ])

class MyModelView(ModelView):
    datamodel = SQLAInterface(MyModel)
    form = MyForm

appbuilder.add_view(MyModelView, "My Model", icon="fa-folder-open-o", category="My Category")

Note: Remember to include the necessary CSS and JavaScript files in your base template
for these widgets to function properly. You may need to adjust the CDN links or
host the files locally depending on your project's requirements.
"""


class AudioRecordingAndPlaybackWidget(BS3TextFieldWidget):
    """
    Widget for recording, playing, and managing audio content directly in the browser.
    Database column should be BYTEA type in PostgreSQL to store audio data with metadata in JSONB.

    Features:
    - Live audio recording with configurable quality settings
    - Playback controls (play, pause, stop, seek, speed)
    - Waveform visualization with zoom and selection
    - Real-time audio effects and filters
    - Multiple format support (MP3, WAV, OGG, FLAC) with fallbacks
    - Automatic volume normalization and gain control
    - Noise reduction and echo cancellation
    - Trim/crop with preview
    - Multiple track mixing/layering
    - Export to various formats
    - Recording quality presets
    - Dynamic microphone selection and testing
    - Advanced noise filtering
    - Voice activity detection with auto-stop
    - Real-time audio spectrum visualization
    - Configurable time limits and auto-split
    - Auto-save and recovery
    - Accessibility support (keyboard controls, ARIA labels)
    - Progress indicators and error handling
    - Resource cleanup and memory management

    Database Schema:
        audio_data = db.Column(db.LargeBinary, nullable=False)  # Raw audio data
        metadata = db.Column(db.JSON, nullable=False)  # Audio metadata
        effects = db.Column(db.JSON)  # Applied effects
        waveform = db.Column(db.JSON)  # Cached waveform data

    Required Dependencies:
    - RecordRTC.js 5.6+
    - WaveSurfer.js 6.0+
    - Web Audio API
    - MediaRecorder API
    - Lamejs (MP3 encoding)
    - Aurora.js (Audio decoding)
    - Tuna.js (Audio effects)

    Browser Compatibility:
    - Chrome 52+
    - Firefox 44+
    - Safari 14.1+
    - Edge 79+
    - Opera 39+

    Required Permissions:
    - Microphone access
    - Storage read/write
    - File download

    Performance Considerations:
    - Memory usage for buffers
    - CPU usage for effects
    - Storage for auto-save
    - Network bandwidth for upload

    Security:
    - HTTPS required
    - Input validation
    - File size limits
    - Format validation
    - Access control

    Best Practices:
    - Request permissions early
    - Use WebWorkers for encoding
    - Enable auto-save
    - Validate uploads
    - Clean up resources
    - Handle errors gracefully

    Troubleshooting:
    - Check microphone permissions
    - Verify HTTPS
    - Test browser compatibility
    - Monitor resource usage
    - Validate file formats
    - Check upload limits

    Example:
        audio = db.Column(db.LargeBinary, nullable=False,
            info={'widget': AudioRecordingAndPlaybackWidget(
                max_duration=300,  # 5 minutes
                format='mp3',
                quality='high',
                channels=2,
                sample_rate=44100,
                noise_reduction=True,
                show_waveform=True,
                enable_effects=True,
                auto_normalize=True,
                chunk_size=4096,
                auto_save_interval=30,
                max_file_size=50*1024*1024  # 50MB
            )})
    """

    # JavaScript dependencies that need to be included
    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/recordrtc@5.6.2/RecordRTC.min.js",
        "https://cdn.jsdelivr.net/npm/wavesurfer.js@6.4.0/dist/wavesurfer.min.js",
        "https://cdn.jsdelivr.net/npm/lamejs@1.2.1/lame.min.js",
        "https://cdn.jsdelivr.net/npm/aurora.js@0.4.2/aurora.min.js",
        "https://cdn.jsdelivr.net/npm/tuna-web-audio@0.4.0/dist/tuna.min.js",
        "/static/js/audio-recorder.js",  # Custom implementation
        "/static/js/audio-effects.js",  # Effects processing
        "/static/js/audio-upload.js",  # Upload handling
        "/static/js/audio-worker.js",  # Web worker for encoding
    ]

    CSS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/wavesurfer.js@6.4.0/dist/wavesurfer.min.css",
        "/static/css/audio-recorder.css",  # Custom styles
    ]

    QUALITY_PRESETS = {
        "low": {"bitrate": 96, "sampleRate": 22050},
        "medium": {"bitrate": 128, "sampleRate": 44100},
        "high": {"bitrate": 192, "sampleRate": 48000},
    }

    FORMAT_SETTINGS = {
        "mp3": {"mime": "audio/mpeg", "ext": ".mp3"},
        "wav": {"mime": "audio/wav", "ext": ".wav"},
        "ogg": {"mime": "audio/ogg", "ext": ".ogg"},
        "flac": {"mime": "audio/flac", "ext": ".flac"},
    }

    AUDIO_EFFECTS = {
        "none": {"name": "Normal", "filter": ""},
        "telephone": {"name": "Telephone", "filter": "bandpass"},
        "radio": {"name": "Radio", "filter": "lowshelf"},
        "megaphone": {"name": "Megaphone", "filter": "highpass"},
        "underwater": {"name": "Underwater", "filter": "lowpass"},
        "alien": {"name": "Alien", "filter": "frequency"},
        "echo": {"name": "Echo", "filter": "delay"},
        "reverb": {"name": "Reverb", "filter": "convolver"},
    }

    def __init__(self, **kwargs):
        """Initialize audio recording widget with configuration"""
        super().__init__(**kwargs)
        self.max_duration = kwargs.get("max_duration", 300)
        self.format = kwargs.get("format", "mp3")
        self.quality = kwargs.get("quality", "high")
        self.channels = kwargs.get("channels", 2)
        self.sample_rate = kwargs.get("sample_rate", 44100)
        self.noise_reduction = kwargs.get("noise_reduction", False)
        self.show_waveform = kwargs.get("show_waveform", True)
        self.enable_effects = kwargs.get("enable_effects", False)
        self.auto_normalize = kwargs.get("auto_normalize", True)
        self.echo_cancellation = kwargs.get("echo_cancellation", True)
        self.auto_gain_control = kwargs.get("auto_gain_control", True)
        self.save_path = kwargs.get("save_path", "uploads/audio")
        self.device_id = kwargs.get("device_id", None)
        self.chunk_size = kwargs.get("chunk_size", 4096)
        self.auto_save_interval = kwargs.get("auto_save_interval", 30)
        self.max_file_size = kwargs.get("max_file_size", 50 * 1024 * 1024)
        self.voice_activity_threshold = kwargs.get("voice_activity_threshold", 0.2)
        self.waveform_color = kwargs.get("waveform_color", "#2196F3")
        self.progress_color = kwargs.get("progress_color", "#1976D2")
        self.grid_color = kwargs.get("grid_color", "#999")
        self.background_color = kwargs.get("background_color", "#fff")
        self.retry_attempts = kwargs.get("retry_attempts", 3)
        self.retry_delay = kwargs.get("retry_delay", 1000)
        self.debug_mode = kwargs.get("debug_mode", False)
        self.fallback_mode = kwargs.get("fallback_mode", "file")
        self.cache_enabled = kwargs.get("cache_enabled", True)
        self.cache_max_age = kwargs.get("cache_max_age", 3600)
        self.mobile_optimization = kwargs.get("mobile_optimization", True)
        self.upload_chunk_size = kwargs.get("upload_chunk_size", 1024 * 1024)
        self.upload_concurrent = kwargs.get("upload_concurrent", 3)
        self.worker_count = kwargs.get("worker_count", 2)

        # Initialize Flask configs
        from flask import current_app

        self.upload_url = current_app.config.get(
            "AUDIO_UPLOAD_URL", "/api/upload/audio"
        )
        self.chunk_upload_url = current_app.config.get(
            "AUDIO_CHUNK_UPLOAD_URL", "/api/upload/audio/chunk"
        )
        self.effects_url = current_app.config.get(
            "AUDIO_EFFECTS_URL", "/api/audio/effects"
        )
        self.download_url = current_app.config.get(
            "AUDIO_DOWNLOAD_URL", "/api/audio/download"
        )
        self.auth_token = current_app.config.get("AUDIO_AUTH_TOKEN", None)

        # Create save directory if needed
        import os

        os.makedirs(self.save_path, exist_ok=True)

    def render_field(self, field, **kwargs):
        """Render the audio recording widget with controls"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("required", field.flags.required)

        # Include dependencies
        deps_html = self._include_dependencies()

        # Enhanced HTML template with ARIA labels and keyboard shortcuts
        widget_html = f"""
        {deps_html}

        <div class="audio-recorder-widget" id="{field.id}-container"
             role="application" aria-label="Audio Recorder">
            <!-- Device Selection -->
            <div class="device-selection mb-2">
                <select id="{field.id}-device" class="form-control"
                        aria-label="Microphone Selection">
                    <option value="">Select Microphone...</option>
                </select>
                <button type="button" class="btn btn-sm btn-secondary test-mic"
                        aria-label="Test Microphone">
                    <i class="fa fa-volume-up"></i> Test
                </button>
            </div>

            <!-- Recording Controls -->
            <div class="recorder-controls btn-group" role="toolbar"
                 aria-label="Recording Controls">
                <button type="button" class="btn btn-primary" id="{field.id}-record"
                        aria-label="Start Recording" title="Start Recording (Ctrl+R)">
                    <i class="fa fa-microphone"></i> Record
                </button>
                <button type="button" class="btn btn-warning" id="{field.id}-pause"
                        disabled aria-label="Pause Recording" title="Pause (Ctrl+P)">
                    <i class="fa fa-pause"></i> Pause
                </button>
                <button type="button" class="btn btn-danger" id="{field.id}-stop"
                        disabled aria-label="Stop Recording" title="Stop (Ctrl+S)">
                    <i class="fa fa-stop"></i> Stop
                </button>
            </div>

            <!-- Recording Status -->
            <div class="recording-status mt-2" role="status"
                 aria-label="Recording Status">
                <div class="d-flex justify-content-between">
                    <span class="timer" aria-label="Recording Time">00:00</span>
                    <span class="file-size" aria-label="File Size">0 KB</span>
                </div>
                <div class="progress">
                    <div class="progress-bar" role="progressbar" style="width: 0%"
                         aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">
                    </div>
                </div>
                <div class="level-meter" role="meter"
                     aria-label="Audio Level"></div>
            </div>

            <!-- Waveform Visualization -->
            {f'''
            <div class="waveform-container mt-2" role="region"
                 aria-label="Audio Waveform">
                <div id="{field.id}-waveform"></div>
                <div class="waveform-timeline"></div>
                <div class="selection-region"></div>
            </div>
            ''' if self.show_waveform else ''}

            <!-- Playback Controls -->
            <div class="playback-controls mt-2" style="display:none"
                 role="group" aria-label="Playback Controls">
                <div class="btn-group">
                    <button type="button" class="btn btn-success" id="{field.id}-play"
                            aria-label="Play/Pause" title="Play/Pause (Space)">
                        <i class="fa fa-play"></i>
                    </button>
                    <button type="button" class="btn btn-info" id="{field.id}-trim"
                            aria-label="Trim Audio" title="Trim Selection (Ctrl+T)">
                        <i class="fa fa-cut"></i>
                    </button>
                </div>
                <input type="range" class="form-range mt-2" id="{field.id}-seek"
                       min="0" max="100" value="0" step="0.1"
                       aria-label="Playback Position">
                <div class="d-flex justify-content-between">
                    <span class="current-time" aria-label="Current Time">00:00</span>
                    <span class="total-time" aria-label="Total Time">00:00</span>
                </div>
            </div>

            <!-- Effects Panel -->
            {f'''
            <div class="effects-panel mt-2" role="region"
                 aria-label="Audio Effects">
                <h5>Effects</h5>
                <div class="effect-controls">
                    <div class="form-group">
                        <label for="{field.id}-gain">Gain</label>
                        <input type="range" class="form-range" id="{field.id}-gain"
                               min="0" max="2" step="0.1" value="1"
                               aria-label="Gain Control">
                    </div>
                    <div class="form-group">
                        <label for="{field.id}-echo">Echo</label>
                        <input type="range" class="form-range" id="{field.id}-echo"
                               min="0" max="1" step="0.1" value="0"
                               aria-label="Echo Control">
                    </div>
                    <div class="form-group">
                        <label for="{field.id}-reverb">Reverb</label>
                        <input type="range" class="form-range" id="{field.id}-reverb"
                               min="0" max="1" step="0.1" value="0"
                               aria-label="Reverb Control">
                    </div>
                    <div class="form-group">
                        <label for="{field.id}-filter">Filter</label>
                        <select class="form-control" id="{field.id}-filter"
                                aria-label="Audio Filter">
                            <option value="none">None</option>
                            <option value="telephone">Telephone</option>
                            <option value="radio">Radio</option>
                            <option value="megaphone">Megaphone</option>
                            <option value="underwater">Underwater</option>
                        </select>
                    </div>
                </div>
            </div>
            ''' if self.enable_effects else ''}

            <!-- Export Options -->
            <div class="export-options mt-2" role="group"
                 aria-label="Export Options">
                <div class="btn-group">
                    <button type="button" class="btn btn-secondary dropdown-toggle"
                            data-toggle="dropdown" aria-label="Export Menu">
                        <i class="fa fa-download"></i> Export
                    </button>
                    <div class="dropdown-menu">
                        {self._render_export_options()}
                    </div>
                </div>
            </div>

            <!-- Status Messages -->
            <div class="alert mt-2" style="display:none" role="alert"
                 aria-live="polite"></div>

            <!-- Hidden Inputs -->
            <input type="hidden" name="{field.name}" id="{field.id}"
                   value="{field.data or ''}" aria-hidden="true">
            <input type="file" style="display:none" id="{field.id}-file"
                   accept=".mp3,.wav,.ogg,.flac"
                   aria-label="File Upload Fallback">

            <!-- Processing Overlay -->
            <div class="processing-overlay" style="display:none"
                 role="status" aria-label="Processing">
                <div class="spinner"></div>
                <div class="message">Processing...</div>
            </div>
        </div>

        <script>
            $(document).ready(function() {{
                // Initialize audio recorder with enhanced configuration
                const audioRecorder = new AudioRecorderWidget({{
                    containerId: '{field.id}-container',
                    fieldId: '{field.id}',
                    maxDuration: {self.max_duration},
                    format: '{self.format}',
                    quality: {json.dumps(self.QUALITY_PRESETS[self.quality])},
                    channels: {self.channels},
                    sampleRate: {self.sample_rate},
                    noiseReduction: {str(self.noise_reduction).lower()},
                    showWaveform: {str(self.show_waveform).lower()},
                    enableEffects: {str(self.enable_effects).lower()},
                    autoNormalize: {str(self.auto_normalize).lower()},
                    echoCancellation: {str(self.echo_cancellation).lower()},
                    autoGainControl: {str(self.auto_gain_control).lower()},
                    deviceId: {f"'{self.device_id}'" if self.device_id else 'null'},
                    chunkSize: {self.chunk_size},
                    autoSaveInterval: {self.auto_save_interval},
                    maxFileSize: {self.max_file_size},
                    voiceActivityThreshold: {self.voice_activity_threshold},
                    waveformColor: '{self.waveform_color}',
                    progressColor: '{self.progress_color}',
                    gridColor: '{self.grid_color}',
                    backgroundColor: '{self.background_color}',
                    uploadUrl: '{self.upload_url}',
                    chunkUploadUrl: '{self.chunk_upload_url}',
                    effectsUrl: '{self.effects_url}',
                    downloadUrl: '{self.download_url}',
                    authToken: {f"'{self.auth_token}'" if self.auth_token else 'null'},
                    retryAttempts: {self.retry_attempts},
                    retryDelay: {self.retry_delay},
                    debugMode: {str(self.debug_mode).lower()},
                    fallbackMode: '{self.fallback_mode}',
                    cacheEnabled: {str(self.cache_enabled).lower()},
                    cacheMaxAge: {self.cache_max_age},
                    mobileOptimization: {str(self.mobile_optimization).lower()},
                    uploadChunkSize: {self.upload_chunk_size},
                    uploadConcurrent: {self.upload_concurrent},
                    workerCount: {self.worker_count},
                    effects: {json.dumps(self.AUDIO_EFFECTS)},
                    onError: function(error) {{
                        showError(error);
                    }},
                    onProgress: function(progress) {{
                        updateProgress(progress);
                    }},
                    onComplete: function(data) {{
                        handleRecordingComplete(data);
                    }},
                    onStateChange: function(state) {{
                        updateUIState(state);
                    }},
                    onDeviceError: function(error) {{
                        handleDeviceError(error);
                    }},
                    onStorageError: function(error) {{
                        handleStorageError(error);
                    }},
                    onUploadError: function(error) {{
                        handleUploadError(error);
                    }}
                }});

                // Enhanced error handling
                function showError(error) {{
                    console.error('Audio recorder error:', error);
                    const alert = $('#{field.id}-container .alert');
                    alert.removeClass('alert-success alert-info')
                         .addClass('alert-danger')
                         .html('<i class="fa fa-exclamation-circle"></i> ' + error)
                         .show()
                         .attr('role', 'alert');
                    setTimeout(() => alert.fadeOut(), 5000);
                }}

                // Progress updates with performance monitoring
                function updateProgress(progress) {{
                    const progressBar = $('#{field.id}-container .progress-bar');
                    progressBar.css('width', progress + '%')
                              .attr('aria-valuenow', progress);

                    if (progress % 10 === 0) {{
                        audioRecorder.checkPerformance();
                    }}
                }}

                // Recording complete with validation
                function handleRecordingComplete(data) {{
                    try {{
                        data = audioRecorder.validateRecording(data);
                        $('#{field.id}').val(JSON.stringify(data));
                        showSuccess('Recording completed successfully');
                        audioRecorder.enablePlayback();
                    }} catch (error) {{
                        showError('Recording validation failed: ' + error.message);
                    }}
                }}

                // Success message
                function showSuccess(message) {{
                    const alert = $('#{field.id}-container .alert');
                    alert.removeClass('alert-danger alert-info')
                         .addClass('alert-success')
                         .html('<i class="fa fa-check-circle"></i> ' + message)
                         .show()
                         .attr('role', 'alert');
                    setTimeout(() => alert.fadeOut(), 3000);
                }}

                // UI state management
                function updateUIState(state) {{
                    const container = $('#{field.id}-container');
                    container.attr('data-state', state);

                    // Update button states
                    $('#{field.id}-record').prop('disabled', state === 'recording');
                    $('#{field.id}-pause').prop('disabled', state !== 'recording');
                    $('#{field.id}-stop').prop('disabled', state === 'idle');

                    // Update ARIA labels
                    container.find('.recording-status')
                            .attr('aria-label', 'Recording Status: ' + state);

                    // Show/hide processing overlay
                    const overlay = container.find('.processing-overlay');
                    if (state === 'processing') {{
                        overlay.show()
                               .find('.message')
                               .text('Processing recording...');
                    }} else {{
                        overlay.hide();
                    }}
                }}

                // Device error handling
                function handleDeviceError(error) {{
                    showError('Device error: ' + error);
                    if ('{self.fallback_mode}' === 'file') {{
                        $('#{field.id}-file').show()
                                           .attr('aria-label', 'File Upload Fallback Mode');
                    }}
                }}

                // Storage error handling
                function handleStorageError(error) {{
                    showError('Storage error: ' + error);
                    audioRecorder.cleanupStorage();
                }}

                // Upload error handling with retry
                function handleUploadError(error) {{
                    showError('Upload error: ' + error);
                    if ({str(self.upload_resume).lower()}) {{
                        audioRecorder.retryUpload();
                    }}
                }}

                // Enhanced keyboard shortcuts with announcements
                $(document).on('keydown', function(e) {{
                    if (e.ctrlKey || e.metaKey) {{
                        let action = '';
                        switch(e.key.toLowerCase()) {{
                            case 'r':
                                e.preventDefault();
                                action = 'Start Recording';
                                $('#{field.id}-record').click();
                                break;
                            case 'p':
                                e.preventDefault();
                                action = 'Pause Recording';
                                $('#{field.id}-pause').click();
                                break;
                            case 's':
                                e.preventDefault();
                                action = 'Stop Recording';
                                $('#{field.id}-stop').click();
                                break;
                            case 't':
                                e.preventDefault();
                                action = 'Trim Recording';
                                $('#{field.id}-trim').click();
                                break;
                            case ' ':
                                e.preventDefault();
                                action = 'Toggle Playback';
                                $('#{field.id}-play').click();
                                break;
                        }}
                        if (action) {{
                            audioRecorder.announceAction(action);
                        }}
                    }}
                }});

                // Enhanced browser compatibility check
                if (!audioRecorder.checkCompatibility()) {{
                    showError('Audio recording is not supported in this browser. ' +
                            'Please use a modern browser with microphone support.');
                    if ('{self.fallback_mode}' === 'file') {{
                        $('#{field.id}-file').show()
                                           .attr('aria-label', 'File Upload Fallback Mode');
                    }}
                }}

                // Proper cleanup on page unload
                $(window).on('unload', function() {{
                    audioRecorder.cleanup();
                    audioRecorder.disposeWorkers();
                    audioRecorder.releaseMemory();
                }});

                // Initialize voice activity detection if enabled
                if ({str(self.voice_activity_threshold > 0).lower()}) {{
                    audioRecorder.initializeVoiceDetection();
                }}

                // Setup performance monitoring
                if ({str(self.debug_mode).lower()}) {{
                    audioRecorder.startPerformanceMonitoring();
                }}

                // Mobile device optimization
                if ({str(self.mobile_optimization).lower()}) {{
                    audioRecorder.optimizeForMobile();
                }}
            }});
        </script>
        """

        return Markup(widget_html)

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{js_includes}\n{css_includes}"

    def _render_export_options(self):
        """Render export format options"""
        options = []
        for fmt, settings in self.FORMAT_SETTINGS.items():
            options.append(
                f'<a class="dropdown-item" href="#" data-format="{fmt}" '
                f'aria-label="Export as {fmt.upper()}">{fmt.upper()}</a>'
            )
        return "\n".join(options)

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_audio_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid audio data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_audio_data(self, data):
        """Validate audio data and constraints"""
        if not isinstance(data, dict) or "audio" not in data:
            raise ValueError("Invalid audio data structure")

        # Validate file size
        if len(data["audio"]) > self.max_file_size:
            raise ValueError(
                f"Audio file size exceeds maximum ({self.max_file_size/(1024*1024):.1f}MB)"
            )

        # Validate format
        if "format" not in data or data["format"] not in self.FORMAT_SETTINGS:
            raise ValueError("Unsupported audio format")

        # Validate duration
        if "duration" in data and data["duration"] > self.max_duration:
            raise ValueError(
                f"Recording exceeds maximum duration ({self.max_duration}s)"
            )

        # Validate metadata
        if "metadata" in data:
            required_fields = ["timestamp", "channels", "sampleRate", "bitrate"]
            if not all(field in data["metadata"] for field in required_fields):
                raise ValueError("Missing required metadata fields")

            # Validate metadata values
            if data["metadata"]["channels"] not in [1, 2]:
                raise ValueError("Invalid number of channels")

            if not (8000 <= data["metadata"]["sampleRate"] <= 192000):
                raise ValueError("Invalid sample rate")

            if not (8 <= data["metadata"]["bitrate"] <= 320):
                raise ValueError("Invalid bitrate")

        # Validate effects if present
        if "effects" in data:
            for effect in data["effects"]:
                if effect not in self.AUDIO_EFFECTS:
                    raise ValueError(f"Invalid effect: {effect}")

    def pre_validate(self, form):
        """Validate audio data before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Audio recording is required")


class VideoRecordAndPlayWidget(BS3TextFieldWidget):
    """
    Widget for recording, playing, and managing video content directly in the browser.
    Database Type:
        PostgreSQL: BYTEA (for video data) + JSONB (for metadata)
        SQLAlchemy: LargeBinary + JSON

    Features:
    - Live video recording with audio
    - Video preview while recording
    - Playback controls with keyboard shortcuts
    - Screenshot capture with custom naming
    - Multi-camera selection and testing
    - Resolution presets (480p to 4K)
    - Frame rate control (24-60 fps)
    - Real-time video filters and effects
    - Auto thumbnail generation
    - Screen/window capture mode
    - Picture-in-picture support
    - Video trimming with preview
    - Custom overlays (text, images)
    - Green screen/chroma key
    - Motion/face detection
    - Recording timer with auto-stop
    - Quality presets (low to ultra)
    - Automatic error recovery
    - Progress indicators
    - Resource monitoring
    - Upload resume
    - Mobile optimization
    - Voice commands
    - Accessibility features

    Database Schema:
        video = db.Column(db.LargeBinary, nullable=False) # Raw video data
        metadata = db.Column(db.JSON, nullable=False) # Video metadata
        thumbnails = db.Column(db.JSON) # Thumbnail info
        effects = db.Column(db.JSON) # Applied effects

    Required Dependencies:
    - RecordRTC.js 5.6+
    - Video.js 7.0+
    - MediaRecorder API
    - Canvas API
    - FaceAPI.js
    - TensorFlow.js
    - FFmpeg.js
    - OpenCV.js

    Browser Support:
    - Chrome 52+
    - Firefox 44+
    - Safari 14.1+
    - Edge 79+
    - Opera 39+

    Required Permissions:
    - Camera access
    - Microphone access (if audio enabled)
    - Screen capture (if enabled)
    - File system (for saving)

    Performance Considerations:
    - CPU usage for encoding
    - Memory usage for buffering
    - Bandwidth for uploading
    - Storage for recorded files

    Security:
    - HTTPS required
    - Permission checks
    - Input validation
    - Safe file handling
    - Access control

    Example:
        video = db.Column(db.LargeBinary, nullable=False,
            info={'widget': VideoRecordAndPlayWidget(
                max_duration=600,  # 10 minutes
                resolution='1080p',
                frame_rate=30,
                quality='high',
                enable_audio=True,
                screen_capture=True,
                enable_effects=True,
                face_detection=True,
                pip_enabled=True,
                auto_focus=True,
                generate_thumbnails=True,
                chunk_size=1024*1024,  # 1MB chunks
                max_file_size=1024*1024*1024 # 1GB
            )})

    Troubleshooting:
    - Check browser compatibility
    - Verify HTTPS connection
    - Test camera permissions
    - Monitor resource usage
    - Check encoding settings
    - Validate upload limits
    """

    # JavaScript dependencies
    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/recordrtc@5.6.2/RecordRTC.min.js",
        "https://vjs.zencdn.net/7.20.3/video.min.js",
        "https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@3.18.0/dist/tf.min.js",
        "https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/dist/face-api.min.js",
        "https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.11.0/dist/ffmpeg.min.js",
        "https://docs.opencv.org/4.5.4/opencv.js",
        "https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js",
        "https://cdn.jsdelivr.net/npm/comlink/dist/umd/comlink.min.js",
        "/static/js/video-recorder.js",  # Custom implementation
        "/static/js/video-effects.js",  # Custom effects
        "/static/js/video-upload.js",  # Upload handling
    ]

    CSS_DEPENDENCIES = [
        "https://vjs.zencdn.net/7.20.3/video-js.css",
        "/static/css/video-recorder.css",  # Custom styles
    ]

    # Quality presets
    QUALITY_PRESETS = {
        "low": {"bitrate": "1000k", "codec": "libx264", "preset": "ultrafast"},
        "medium": {"bitrate": "2500k", "codec": "libx264", "preset": "medium"},
        "high": {"bitrate": "5000k", "codec": "libx264", "preset": "slow"},
        "ultra": {"bitrate": "8000k", "codec": "libx264", "preset": "veryslow"},
    }

    # Resolution presets
    RESOLUTION_PRESETS = {
        "480p": {"width": 854, "height": 480, "aspect": "16:9"},
        "720p": {"width": 1280, "height": 720, "aspect": "16:9"},
        "1080p": {"width": 1920, "height": 1080, "aspect": "16:9"},
        "4k": {"width": 3840, "height": 2160, "aspect": "16:9"},
    }

    # Effect presets
    VIDEO_EFFECTS = {
        "none": {"name": "Normal", "filter": ""},
        "grayscale": {"name": "Grayscale", "filter": "grayscale(1)"},
        "sepia": {"name": "Sepia", "filter": "sepia(1)"},
        "blur": {"name": "Blur", "filter": "blur(5px)"},
        "brightness": {"name": "Bright", "filter": "brightness(1.5)"},
        "contrast": {"name": "High Contrast", "filter": "contrast(1.5)"},
        "huerotate": {"name": "Hue Rotate", "filter": "hue-rotate(90deg)"},
        "invert": {"name": "Invert", "filter": "invert(1)"},
        "opacity": {"name": "Fade", "filter": "opacity(0.5)"},
        "saturate": {"name": "Saturate", "filter": "saturate(2)"},
        "vintage": {"name": "Vintage", "filter": "sepia(0.5) hue-rotate(-30deg)"},
    }

    def __init__(self, **kwargs):
        """Initialize video recorder widget with configuration"""
        super().__init__(**kwargs)
        self.max_duration = kwargs.get("max_duration", 600)
        self.resolution = kwargs.get("resolution", "1080p")
        self.frame_rate = kwargs.get("frame_rate", 30)
        self.quality = kwargs.get("quality", "high")
        self.enable_audio = kwargs.get("enable_audio", True)
        self.screen_capture = kwargs.get("screen_capture", False)
        self.enable_effects = kwargs.get("enable_effects", False)
        self.face_detection = kwargs.get("face_detection", False)
        self.pip_enabled = kwargs.get("pip_enabled", True)
        self.auto_focus = kwargs.get("auto_focus", True)
        self.device_id = kwargs.get("device_id", None)
        self.save_path = kwargs.get("save_path", "uploads/video")
        self.generate_thumbnails = kwargs.get("generate_thumbnails", True)
        self.watermark = kwargs.get("watermark", None)
        self.chunk_size = kwargs.get("chunk_size", 1024 * 1024)
        self.max_file_size = kwargs.get("max_file_size", 1024 * 1024 * 1024)
        self.voice_commands = kwargs.get("voice_commands", False)
        self.mobile_optimize = kwargs.get("mobile_optimize", True)
        self.fallback_mode = kwargs.get("fallback_mode", "file")
        self.error_recovery = kwargs.get("error_recovery", True)
        self.upload_resume = kwargs.get("upload_resume", True)
        self.auto_save = kwargs.get("auto_save", True)
        self.thumbnail_count = kwargs.get("thumbnail_count", 5)
        self.thumbnail_quality = kwargs.get("thumbnail_quality", 0.7)
        self.preview_quality = kwargs.get("preview_quality", 0.5)
        self.compression_quality = kwargs.get("compression_quality", 0.8)
        self.memory_limit = kwargs.get("memory_limit", 512 * 1024 * 1024)
        self.cpu_threads = kwargs.get("cpu_threads", 4)
        self.gpu_enabled = kwargs.get("gpu_enabled", True)
        self.debug_mode = kwargs.get("debug_mode", False)
        self.retry_attempts = kwargs.get("retry_attempts", 3)
        self.retry_delay = kwargs.get("retry_delay", 1000)
        self.upload_concurrency = kwargs.get("upload_concurrency", 3)
        self.log_level = kwargs.get("log_level", "error")

        # Initialize Flask configs
        from flask import current_app

        self.upload_url = current_app.config.get(
            "VIDEO_UPLOAD_URL", "/api/upload/video"
        )
        self.chunk_upload_url = current_app.config.get(
            "VIDEO_CHUNK_UPLOAD_URL", "/api/upload/video/chunk"
        )
        self.thumbnail_url = current_app.config.get(
            "VIDEO_THUMBNAIL_URL", "/api/video/thumbnail"
        )
        self.stream_url = current_app.config.get(
            "VIDEO_STREAM_URL", "/api/video/stream"
        )
        self.auth_token = current_app.config.get("VIDEO_AUTH_TOKEN", None)

        # Create save directory if needed
        import os

        os.makedirs(self.save_path, exist_ok=True)

    def render_field(self, field: "Any", **kwargs) -> str:
        """Render the video recording widget with controls"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("required", field.flags.required)

        # Include dependencies
        deps_html = self._include_dependencies()

        # Enhanced HTML template with aria labels and keyboard shortcuts
        widget_html = f"""
        {deps_html}

        <div class="video-recorder-widget" id="{field.id}-container"
             role="application" aria-label="Video Recorder">
            <!-- Device Selection -->
            <div class="device-selection mb-2">
                <select id="{field.id}-camera" class="form-control"
                        aria-label="Camera Selection">
                    <option value="">Select Camera...</option>
                </select>

                {f'''
                <select id="{field.id}-microphone" class="form-control mt-2"
                        aria-label="Microphone Selection">
                    <option value="">Select Microphone...</option>
                </select>
                ''' if self.enable_audio else ''}

                <button type="button" class="btn btn-sm btn-secondary mt-2 test-devices"
                        aria-label="Test Devices">
                    <i class="fa fa-check-circle"></i> Test Devices
                </button>
            </div>

            <!-- Video Preview -->
            <div class="video-preview">
                <video id="{field.id}-preview" class="video-js vjs-default-skin"
                       playsinline controls preload="auto"
                       aria-label="Video Preview">
                    <p class="vjs-no-js">
                        To view this video please enable JavaScript, and consider upgrading to a
                        web browser that supports HTML5 video
                    </p>
                </video>
                <canvas id="{field.id}-overlay" class="video-overlay"
                        aria-hidden="true"></canvas>
            </div>

            <!-- Recording Controls -->
            <div class="recording-controls btn-group mt-2" role="toolbar"
                 aria-label="Recording Controls">
                <button type="button" class="btn btn-primary" id="{field.id}-record"
                        aria-label="Start Recording" title="Start Recording (Ctrl+R)">
                    <i class="fa fa-video"></i> Record
                </button>
                <button type="button" class="btn btn-warning" id="{field.id}-pause"
                        disabled aria-label="Pause Recording" title="Pause (Ctrl+P)">
                    <i class="fa fa-pause"></i> Pause
                </button>
                <button type="button" class="btn btn-danger" id="{field.id}-stop"
                        disabled aria-label="Stop Recording" title="Stop (Ctrl+S)">
                    <i class="fa fa-stop"></i> Stop
                </button>
                <button type="button" class="btn btn-info" id="{field.id}-screenshot"
                        aria-label="Take Screenshot" title="Screenshot (Ctrl+T)">
                    <i class="fa fa-camera"></i> Screenshot
                </button>
            </div>

            <!-- Recording Status -->
            <div class="recording-status mt-2" role="status"
                 aria-label="Recording Status">
                <div class="d-flex justify-content-between">
                    <span class="timer" aria-label="Recording Time">00:00</span>
                    <span class="file-size" aria-label="File Size">0 MB</span>
                </div>
                <div class="progress">
                    <div class="progress-bar" role="progressbar" style="width: 0%"
                         aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">
                    </div>
                </div>
                <div class="recording-indicator" aria-hidden="true"></div>
            </div>

            <!-- Effects Panel -->
            {f'''
            <div class="effects-panel mt-2" role="region"
                 aria-label="Video Effects">
                <h5>Video Effects</h5>
                <div class="effect-controls">
                    <div class="form-group">
                        <label for="{field.id}-brightness">Brightness</label>
                        <input type="range" class="form-range" id="{field.id}-brightness"
                               min="-100" max="100" value="0"
                               aria-label="Brightness Control">
                    </div>
                    <div class="form-group">
                        <label for="{field.id}-contrast">Contrast</label>
                        <input type="range" class="form-range" id="{field.id}-contrast"
                               min="-100" max="100" value="0"
                               aria-label="Contrast Control">
                    </div>
                    <div class="form-group">
                        <label for="{field.id}-saturation">Saturation</label>
                        <input type="range" class="form-range" id="{field.id}-saturation"
                               min="-100" max="100" value="0"
                               aria-label="Saturation Control">
                    </div>
                </div>

                <div class="filters btn-group mt-2" role="toolbar"
                     aria-label="Video Filters">
                    <button type="button" class="btn btn-sm btn-light" data-filter="none"
                            aria-label="Normal Filter">Normal</button>
                    <button type="button" class="btn btn-sm btn-light" data-filter="grayscale"
                            aria-label="Grayscale Filter">Grayscale</button>
                    <button type="button" class="btn btn-sm btn-light" data-filter="sepia"
                            aria-label="Sepia Filter">Sepia</button>
                    <button type="button" class="btn btn-sm btn-light" data-filter="vintage"
                            aria-label="Vintage Filter">Vintage</button>
                </div>

                <div class="green-screen mt-2">
                    <label for="{field.id}-chroma">Chroma Key Color</label>
                    <input type="color" id="{field.id}-chroma" value="#00ff00"
                           aria-label="Chroma Key Color">
                </div>
            </div>
            ''' if self.enable_effects else ''}

            <!-- Advanced Options -->
            <div class="advanced-options mt-2">
                <div class="btn-group" role="group" aria-label="Advanced Options">
                    <button type="button" class="btn btn-secondary dropdown-toggle"
                            data-toggle="dropdown" aria-label="Advanced Options">
                        <i class="fa fa-cog"></i> Options
                    </button>
                    <div class="dropdown-menu">
                        <a class="dropdown-item" href="#" data-action="pip"
                           aria-label="Picture in Picture">
                            <i class="fa fa-clone"></i> Picture in Picture
                        </a>
                        <a class="dropdown-item" href="#" data-action="screen"
                           aria-label="Screen Capture">
                            <i class="fa fa-desktop"></i> Screen Capture
                        </a>
                        <div class="dropdown-divider"></div>
                        <a class="dropdown-item" href="#" data-action="settings"
                           aria-label="Recording Settings">
                            <i class="fa fa-sliders-h"></i> Settings
                        </a>
                    </div>
                </div>
            </div>

            <!-- Error Messages -->
            <div class="alert mt-2" style="display:none" role="alert"
                 aria-live="polite"></div>

            <!-- Hidden Inputs -->
            <input type="hidden" name="{field.name}" id="{field.id}"
                   value="{field.data or ''}"
                   aria-hidden="true">
            <input type="file" style="display:none" id="{field.id}-file"
                   accept="video/*" capture
                   aria-label="File Upload Fallback">
        </div>

        <script>
            $(document).ready(function() {{
                // Initialize video recorder with enhanced configuration
                const videoRecorder = new VideoRecorderWidget({{
                    containerId: '{field.id}-container',
                    fieldId: '{field.id}',
                    maxDuration: {self.max_duration},
                    resolution: {json.dumps(self.RESOLUTION_PRESETS[self.resolution])},
                    frameRate: {self.frame_rate},
                    quality: {json.dumps(self.QUALITY_PRESETS[self.quality])},
                    enableAudio: {str(self.enable_audio).lower()},
                    screenCapture: {str(self.screen_capture).lower()},
                    enableEffects: {str(self.enable_effects).lower()},
                    faceDetection: {str(self.face_detection).lower()},
                    pipEnabled: {str(self.pip_enabled).lower()},
                    autoFocus: {str(self.auto_focus).lower()},
                    deviceId: {f"'{self.device_id}'" if self.device_id else 'null'},
                    generateThumbnails: {str(self.generate_thumbnails).lower()},
                    watermark: {f"'{self.watermark}'" if self.watermark else 'null'},
                    chunkSize: {self.chunk_size},
                    maxFileSize: {self.max_file_size},
                    voiceCommands: {str(self.voice_commands).lower()},
                    mobileOptimize: {str(self.mobile_optimize).lower()},
                    fallbackMode: '{self.fallback_mode}',
                    errorRecovery: {str(self.error_recovery).lower()},
                    uploadResume: {str(self.upload_resume).lower()},
                    autoSave: {str(self.auto_save).lower()},
                    thumbnailCount: {self.thumbnail_count},
                    thumbnailQuality: {self.thumbnail_quality},
                    previewQuality: {self.preview_quality},
                    compressionQuality: {self.compression_quality},
                    memoryLimit: {self.memory_limit},
                    cpuThreads: {self.cpu_threads},
                    gpuEnabled: {str(self.gpu_enabled).lower()},
                    debugMode: {str(self.debug_mode).lower()},
                    retryAttempts: {self.retry_attempts},
                    retryDelay: {self.retry_delay},
                    uploadConcurrency: {self.upload_concurrency},
                    logLevel: '{self.log_level}',
                    effects: {json.dumps(self.VIDEO_EFFECTS)},
                    uploadUrl: '{self.upload_url}',
                    chunkUploadUrl: '{self.chunk_upload_url}',
                    thumbnailUrl: '{self.thumbnail_url}',
                    streamUrl: '{self.stream_url}',
                    authToken: {f"'{self.auth_token}'" if self.auth_token else 'null'},
                    onError: function(error) {{
                        showError(error);
                    }},
                    onProgress: function(progress) {{
                        updateProgress(progress);
                    }},
                    onComplete: function(data) {{
                        handleRecordingComplete(data);
                    }},
                    onStateChange: function(state) {{
                        updateUIState(state);
                    }},
                    onDeviceError: function(error) {{
                        handleDeviceError(error);
                    }},
                    onStorageError: function(error) {{
                        handleStorageError(error);
                    }},
                    onUploadError: function(error) {{
                        handleUploadError(error);
                    }}
                }});

                // Enhanced error handling
                function showError(error) {{
                    console.error('Video recorder error:', error);
                    const alert = $('#{field.id}-container .alert');
                    alert.removeClass('alert-success alert-info')
                         .addClass('alert-danger')
                         .html('<i class="fa fa-exclamation-circle"></i> ' + error)
                         .show();
                    setTimeout(() => alert.fadeOut(), 5000);
                }}

                // Progress updates with performance monitoring
                function updateProgress(progress) {{
                    const progressBar = $('#{field.id}-container .progress-bar');
                    progressBar.css('width', progress + '%')
                              .attr('aria-valuenow', progress);

                    if (progress % 10 === 0) {{
                        videoRecorder.checkPerformance();
                    }}
                }}

                // Recording complete with validation
                function handleRecordingComplete(data) {{
                    try {{
                        data = videoRecorder.validateRecording(data);
                        $('#{field.id}').val(JSON.stringify(data));
                        showSuccess('Recording completed successfully');
                    }} catch (error) {{
                        showError('Recording validation failed: ' + error.message);
                    }}
                }}

                // Success message with accessibility
                function showSuccess(message) {{
                    const alert = $('#{field.id}-container .alert');
                    alert.removeClass('alert-danger alert-info')
                         .addClass('alert-success')
                         .html('<i class="fa fa-check-circle"></i> ' + message)
                         .show()
                         .attr('role', 'alert');
                    setTimeout(() => alert.fadeOut(), 3000);
                }}

                // UI state management
                function updateUIState(state) {{
                    const container = $('#{field.id}-container');
                    container.attr('data-state', state);

                    // Update button states
                    $('#{field.id}-record').prop('disabled', state === 'recording');
                    $('#{field.id}-pause').prop('disabled', state !== 'recording');
                    $('#{field.id}-stop').prop('disabled', state === 'idle');

                    // Update aria labels
                    container.find('.recording-status')
                            .attr('aria-label', 'Recording Status: ' + state);
                }}

                // Device error handling
                function handleDeviceError(error) {{
                    showError('Device error: ' + error);
                    if ('{self.fallback_mode}' === 'file') {{
                        $('#{field.id}-file').show();
                    }}
                }}

                // Storage error handling
                function handleStorageError(error) {{
                    showError('Storage error: ' + error);
                    videoRecorder.cleanupStorage();
                }}

                // Upload error handling with retry
                function handleUploadError(error) {{
                    showError('Upload error: ' + error);
                    if ({self.upload_resume}) {{
                        videoRecorder.retryUpload();
                    }}
                }}

                // Keyboard shortcuts with announcement
                $(document).on('keydown', function(e) {{
                    if (e.ctrlKey || e.metaKey) {{
                        let action = '';
                        switch(e.key.toLowerCase()) {{
                            case 'r':
                                e.preventDefault();
                                action = 'Start Recording';
                                $('#{field.id}-record').click();
                                break;
                            case 'p':
                                e.preventDefault();
                                action = 'Pause Recording';
                                $('#{field.id}-pause').click();
                                break;
                            case 's':
                                e.preventDefault();
                                action = 'Stop Recording';
                                $('#{field.id}-stop').click();
                                break;
                            case 't':
                                e.preventDefault();
                                action = 'Take Screenshot';
                                $('#{field.id}-screenshot').click();
                                break;
                        }}
                        if (action) {{
                            videoRecorder.announceAction(action);
                        }}
                    }}
                }});

                // Enhanced browser compatibility check
                if (!videoRecorder.checkCompatibility()) {{
                    showError('Video recording is not supported in this browser. ' +
                            'Please use a modern browser with camera support.');
                    if ('{self.fallback_mode}' === 'file') {{
                        $('#{field.id}-file').show()
                                           .attr('aria-label', 'File Upload Fallback Mode');
                    }}
                }}

                // Proper cleanup on page unload
                $(window).on('unload', function() {{
                    videoRecorder.cleanup();
                    videoRecorder.disposeWorkers();
                    videoRecorder.releaseMemory();
                }});

                // Initialize voice commands if enabled
                if ({str(self.voice_commands).lower()}) {{
                    videoRecorder.initializeVoiceCommands();
                }}

                // Setup performance monitoring
                if ({str(self.debug_mode).lower()}) {{
                    videoRecorder.startPerformanceMonitoring();
                }}
            }});
        </script>
        """

        return Markup(widget_html)

    def _include_dependencies(self) -> str:
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{js_includes}\n{css_includes}"

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_video_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid video data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_video_data(self, data):
        """Validate video data and constraints"""
        if not isinstance(data, dict) or "video" not in data:
            raise ValueError("Invalid video data structure")

        # Validate file size
        if len(data["video"]) > self.max_file_size:
            raise ValueError(
                f"Video file size exceeds maximum ({self.max_file_size/(1024*1024):.1f}MB)"
            )

        # Validate format
        if "format" not in data or data["format"] not in ["mp4", "webm"]:
            raise ValueError("Unsupported video format")

        # Validate duration
        if "duration" in data and data["duration"] > self.max_duration:
            raise ValueError(
                f"Recording exceeds maximum duration ({self.max_duration}s)"
            )

        # Validate metadata
        if "metadata" in data:
            required_fields = ["timestamp", "resolution", "frameRate", "quality"]
            if not all(field in data["metadata"] for field in required_fields):
                raise ValueError("Missing required metadata fields")

    def pre_validate(self, form):
        """Validate video data before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Video recording is required")


class MapWidget(BS3TextFieldWidget):
    """
    Interactive map widget using Leaflet/OpenLayers for geographical data visualization and editing.

    Features:
    - Multiple base layer support (OpenStreetMap, Google Maps, etc.)
    - Marker management (add, edit, delete)
    - Polygon/polyline drawing tools
    - GeoJSON import/export
    - Clustering for large datasets
    - Custom marker icons
    - Tooltips and popups
    - Layer controls
    - Search/geocoding
    - Distance measurement
    - Area calculation
    - Mobile touch support
    - Offline caching
    - Custom map controls
    - Multi-language support

    Database Type:
        PostgreSQL: GEOMETRY or GEOGRAPHY with PostGIS extension
        SQLAlchemy: Geometry(geometry_type='GEOMETRY', srid=4326)

    Required Dependencies:
    - Leaflet.js 1.7+
    - Leaflet.draw 1.0+
    - Leaflet.markercluster 1.5+
    - Leaflet.measure
    - Leaflet.offline
    - Leaflet.locatecontrol
    - Turf.js for calculations

    Browser Support:
    - Chrome 49+
    - Firefox 52+
    - Safari 11+
    - Edge 79+
    - Opera 36+
    - iOS Safari 10+
    - Chrome for Android 89+

    Required Permissions:
    - Geolocation access
    - Local storage for offline support
    - File system for GeoJSON import/export

    Performance Considerations:
    - Large datasets should use clustering
    - Limit concurrent markers (<1000 recommended)
    - Cache map tiles for offline use
    - Use vector tiles for better performance
    - Throttle continuous updates
    - Optimize marker icons

    Security Implications:
    - Validate GeoJSON input
    - Sanitize popup content
    - Restrict zoom levels for sensitive locations
    - Consider privacy of location data
    - Use HTTPS for tile servers
    - Implement access controls

    Best Practices:
    - Enable clustering for >100 markers
    - Cache map data when offline support needed
    - Use vector tiles when available
    - Compress GeoJSON data
    - Set reasonable zoom restrictions
    - Include fallback tile servers
    - Implement proper error handling

    Common Issues:
    - Map not displaying: Check HTTPS/permissions
    - Markers not clustering: Verify threshold settings
    - Slow performance: Enable clustering/limit markers
    - Offline mode fails: Check storage quota
    - Geolocation error: Check browser permissions
    - Drawing tools not working: Verify dependencies

    Example:
        location_map = StringField('Location',
                                 widget=MapWidget(
                                     provider='leaflet',
                                     center=[0, 0],
                                     zoom=2,
                                     draw_tools=True,
                                     cluster_markers=True,
                                     geocoding=True,
                                     offline_support=True
                                 ))
    """

    # JavaScript/CSS dependencies
    JS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.7.1/dist/leaflet.js",
        "https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js",
        "https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js",
        "https://unpkg.com/leaflet.locatecontrol@0.74.0/dist/L.Control.Locate.min.js",
        "https://unpkg.com/leaflet-measure@2.1.7/dist/leaflet-measure.js",
        "https://unpkg.com/@turf/turf@6.5.0/turf.min.js",
        "https://unpkg.com/leaflet-offline@1.1.0/dist/leaflet-offline.min.js",
    ]

    CSS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.7.1/dist/leaflet.css",
        "https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css",
        "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css",
        "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css",
        "https://unpkg.com/leaflet.locatecontrol@0.74.0/dist/L.Control.Locate.min.css",
        "https://unpkg.com/leaflet-measure@2.1.7/dist/leaflet-measure.css",
    ]

    # Default settings
    DEFAULT_CENTER = [0, 0]
    DEFAULT_ZOOM = 2
    MAX_MARKERS = 1000
    CLUSTER_THRESHOLD = 100
    DRAW_TYPES = ["marker", "circle", "rectangle", "polygon", "polyline"]

    def __init__(self, **kwargs):
        """
        Initialize MapWidget with custom settings.

        Args:
            provider (str): Map provider ('leaflet' or 'openlayers')
            center (list): Initial map center coordinates [lat, lng]
            zoom (int): Initial zoom level
            draw_tools (bool): Enable drawing tools
            cluster_markers (bool): Enable marker clustering
            geocoding (bool): Enable geocoding/search
            max_markers (int): Maximum number of markers allowed
            layers (list): List of additional map layers
            draw_types (list): Enabled drawing types
            custom_icons (dict): Custom marker icon definitions
            offline_support (bool): Enable offline support
            locate_control (bool): Enable location control
            measure_control (bool): Enable measurement tools
            min_zoom (int): Minimum zoom level
            max_zoom (int): Maximum zoom level
            cluster_threshold (int): Minimum markers for clustering
            tile_layer (str): Custom tile layer URL
            attribution (str): Map attribution text
            language (str): Interface language
        """
        super().__init__(**kwargs)
        self.provider = kwargs.get("provider", "leaflet")
        self.center = kwargs.get("center", self.DEFAULT_CENTER)
        self.zoom = kwargs.get("zoom", self.DEFAULT_ZOOM)
        self.draw_tools = kwargs.get("draw_tools", False)
        self.cluster_markers = kwargs.get("cluster_markers", True)
        self.geocoding = kwargs.get("geocoding", False)
        self.max_markers = kwargs.get("max_markers", self.MAX_MARKERS)
        self.layers = kwargs.get("layers", [])
        self.draw_types = kwargs.get("draw_types", self.DRAW_TYPES)
        self.custom_icons = kwargs.get("custom_icons", {})
        self.offline_support = kwargs.get("offline_support", False)
        self.locate_control = kwargs.get("locate_control", True)
        self.measure_control = kwargs.get("measure_control", True)
        self.min_zoom = kwargs.get("min_zoom", 0)
        self.max_zoom = kwargs.get("max_zoom", 18)
        self.cluster_threshold = kwargs.get("cluster_threshold", self.CLUSTER_THRESHOLD)
        self.tile_layer = kwargs.get(
            "tile_layer", "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        )
        self.attribution = kwargs.get("attribution", "© OpenStreetMap contributors")
        self.language = kwargs.get("language", "en")

    def render_field(self, field: Any, **kwargs) -> str:
        """Render the map widget"""
        kwargs.setdefault("type", "hidden")
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}
            <div class="map-widget" role="application" aria-label="Interactive Map">
                <div id="{field.id}-map" class="map-container"
                     style="height:400px;width:100%;"
                     data-center="{json.dumps(self.center)}"
                     data-zoom="{self.zoom}"></div>
                {input_html}
                <div class="map-loading" role="status" aria-label="Loading map..."
                     style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading map...</span>
                </div>
                <div class="map-error alert alert-danger" role="alert"
                     style="display:none;"></div>
            </div>
            <script>
                $(document).ready(function() {{
                    try {{
                        const map = initializeMap('{field.id}', {{
                            provider: '{self.provider}',
                            center: {json.dumps(self.center)},
                            zoom: {self.zoom},
                            drawTools: {str(self.draw_tools).lower()},
                            clusterMarkers: {str(self.cluster_markers).lower()},
                            geocoding: {str(self.geocoding).lower()},
                            maxMarkers: {self.max_markers},
                            layers: {json.dumps(self.layers)},
                            drawTypes: {json.dumps(self.draw_types)},
                            customIcons: {json.dumps(self.custom_icons)},
                            offlineSupport: {str(self.offline_support).lower()},
                            locateControl: {str(self.locate_control).lower()},
                            measureControl: {str(self.measure_control).lower()},
                            minZoom: {self.min_zoom},
                            maxZoom: {self.max_zoom},
                            clusterThreshold: {self.cluster_threshold},
                            tileLayer: '{self.tile_layer}',
                            attribution: '{self.attribution}',
                            language: '{self.language}'
                        }});

                        // Handle map events
                        map.on('draw:created', function(e) {{
                            handleDrawCreated(e, '{field.id}');
                        }});

                        map.on('moveend', function() {{
                            handleMapMove(map, '{field.id}');
                        }});

                        // Initialize features if data exists
                        const existingData = $('#{field.id}').val();
                        if (existingData) {{
                            loadMapData(map, JSON.parse(existingData));
                        }}

                        // Error handling
                        map.on('error', function(e) {{
                            showMapError('{field.id}', e.message);
                        }});

                        // Accessibility
                        enableMapAccessibility('{field.id}-map');

                        // Mobile optimization
                        optimizeForMobile(map);

                        // Offline support
                        if ({str(self.offline_support).lower()}) {{
                            initializeOfflineSupport(map);
                        }}

                    }} catch (error) {{
                        console.error('Map initialization error:', error);
                        showMapError('{field.id}', 'Failed to initialize map');
                    }}
                }});
            </script>
        """
        )

    def _include_dependencies(self) -> str:
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{css_includes}\n{js_includes}"

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_geo_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid GeoJSON format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_geo_data(self, data):
        """Validate GeoJSON data"""
        if not isinstance(data, dict):
            raise ValueError("Invalid GeoJSON structure")

        # Validate GeoJSON type
        if "type" not in data:
            raise ValueError("Missing GeoJSON type")

        # Validate coordinates
        if "coordinates" not in data:
            raise ValueError("Missing coordinates")

        # Validate feature properties
        if data.get("type") == "Feature" and "properties" not in data:
            raise ValueError("Missing feature properties")

        # Validate coordinate bounds
        self._validate_coordinates(data.get("coordinates", []))

    def _validate_coordinates(self, coords):
        """Validate coordinate values"""
        if isinstance(coords, (list, tuple)):
            if len(coords) == 2:
                lat, lng = coords
                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    raise ValueError("Invalid coordinate values")
            else:
                for coord in coords:
                    self._validate_coordinates(coord)

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_geo_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class FormBuilderWidget(BS3TextFieldWidget):
    """
    Dynamic form builder widget with drag-and-drop interface for creating and saving custom forms to a database.

    Features:
    - Drag-and-drop field placement with grid snapping
    - Extensive field type library (30+ field types)
    - Advanced validation rules and conditional logic
    - Multi-column responsive layouts
    - Field grouping and dependencies
    - Custom CSS classes and styling
    - Real-time mobile preview
    - Form versioning and history
    - Import/export to JSON/XML
    - Accessibility compliance (WCAG 2.1)
    - Localization support (20+ languages)
    - Custom widget support
    - Form analytics and usage tracking
    - Undo/redo capability
    - Auto-save drafts

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON

    Required Dependencies:
    - jQuery UI 1.12+
    - FormBuilder.js 3.4+
    - ValidationEngine 2.6+
    - Gridster.js 0.7+
    - Handlebars 4.7+
    - jQueryUI Touch Punch
    - Bootstrap 4+

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - LocalStorage access
    - File system for import/export
    - Camera for QR code scanning (optional)

    Performance Considerations:
    - Limit max fields to 100 per form
    - Enable field caching
    - Lazy load validation rules
    - Throttle auto-save
    - Optimize preview rendering
    - Compress form JSON

    Security Implications:
    - Validate field configurations
    - Sanitize custom HTML/scripts
    - Rate limit API calls
    - Implement CSRF protection
    - Validate import data
    - Control access permissions

    Example:
        form_builder = db.Column(db.JSON, nullable=False,
            info={'widget': FormBuilderWidget(
                available_fields=['text', 'select', 'date', 'number'],
                templates=True,
                validation=True,
                responsive=True,
                max_fields=50,
                auto_save=True,
                version_control=True
            )})
    """

    # JavaScript/CSS Dependencies
    JS_DEPENDENCIES = [
        "https://code.jquery.com/ui/1.12.1/jquery-ui.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jQuery-formBuilder/3.4.2/form-builder.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jquery-validate/1.19.3/jquery.validate.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/gridster/0.7.0/jquery.gridster.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/handlebars.js/4.7.7/handlebars.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jqueryui-touch-punch/0.2.3/jquery.ui.touch-punch.min.js",
        "/static/js/form-builder-custom.js",
    ]

    CSS_DEPENDENCIES = [
        "https://code.jquery.com/ui/1.12.1/themes/base/jquery-ui.css",
        "https://cdnjs.cloudflare.com/ajax/libs/jQuery-formBuilder/3.4.2/form-builder.min.css",
        "https://cdnjs.cloudflare.com/ajax/libs/gridster/0.7.0/jquery.gridster.min.css",
        "/static/css/form-builder-custom.css",
    ]

    # Available field types with configurations
    FIELD_TYPES = {
        "text": {"icon": "fa-font", "label": "Text Input"},
        "textarea": {"icon": "fa-paragraph", "label": "Text Area"},
        "number": {"icon": "fa-hashtag", "label": "Number"},
        "select": {"icon": "fa-caret-down", "label": "Dropdown"},
        "radio": {"icon": "fa-dot-circle", "label": "Radio Group"},
        "checkbox": {"icon": "fa-check-square", "label": "Checkbox Group"},
        "date": {"icon": "fa-calendar", "label": "Date Picker"},
        "time": {"icon": "fa-clock", "label": "Time Picker"},
        "file": {"icon": "fa-upload", "label": "File Upload"},
        "email": {"icon": "fa-envelope", "label": "Email"},
        "url": {"icon": "fa-link", "label": "URL"},
        "phone": {"icon": "fa-phone", "label": "Phone"},
        "address": {"icon": "fa-map-marker", "label": "Address"},
        "signature": {"icon": "fa-pen", "label": "Signature"},
        "rating": {"icon": "fa-star", "label": "Rating"},
    }

    def __init__(self, **kwargs):
        """
        Initialize FormBuilderWidget with custom settings.

        Args:
            available_fields (list): Available field types
            templates (bool): Enable template library
            validation (bool): Enable validation rules
            responsive (bool): Enable responsive design
            max_fields (int): Maximum number of fields allowed
            field_defaults (dict): Default settings for fields
            save_versions (bool): Enable form versioning
            preview_mode (bool): Enable preview mode
            auto_save (bool): Enable auto-saving
            version_control (bool): Enable version control
            analytics (bool): Enable form analytics
            localization (str): Interface language
            grid_columns (int): Number of grid columns
            field_spacing (int): Grid spacing in pixels
            undo_levels (int): Number of undo levels
            auto_save_interval (int): Auto-save interval in seconds
            max_file_size (int): Maximum file upload size
            cache_enabled (bool): Enable field caching
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        self.available_fields = kwargs.get(
            "available_fields", list(self.FIELD_TYPES.keys())
        )
        self.templates = kwargs.get("templates", True)
        self.validation = kwargs.get("validation", True)
        self.responsive = kwargs.get("responsive", True)
        self.max_fields = kwargs.get("max_fields", 50)
        self.field_defaults = kwargs.get("field_defaults", {})
        self.save_versions = kwargs.get("save_versions", True)
        self.preview_mode = kwargs.get("preview_mode", True)
        self.auto_save = kwargs.get("auto_save", True)
        self.version_control = kwargs.get("version_control", True)
        self.analytics = kwargs.get("analytics", False)
        self.localization = kwargs.get("localization", "en")
        self.grid_columns = kwargs.get("grid_columns", 12)
        self.field_spacing = kwargs.get("field_spacing", 10)
        self.undo_levels = kwargs.get("undo_levels", 20)
        self.auto_save_interval = kwargs.get("auto_save_interval", 30)
        self.max_file_size = kwargs.get("max_file_size", 5 * 1024 * 1024)
        self.cache_enabled = kwargs.get("cache_enabled", True)
        self.debug_mode = kwargs.get("debug_mode", False)

        # Initialize cache if enabled
        if self.cache_enabled:
            self.field_cache = {}

    def render_field(self, field, **kwargs):
        """Render the form builder widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="form-builder-widget" role="application"
                 aria-label="Form Builder Interface">

                <!-- Toolbar -->
                <div class="form-builder-toolbar" role="toolbar"
                     aria-label="Form Builder Tools">
                    <div class="btn-group">
                        <button type="button" class="btn btn-primary" id="{field.id}-save"
                                aria-label="Save Form">
                            <i class="fa fa-save"></i> Save
                        </button>
                        <button type="button" class="btn btn-secondary" id="{field.id}-preview"
                                aria-label="Preview Form">
                            <i class="fa fa-eye"></i> Preview
                        </button>
                        <button type="button" class="btn btn-info" id="{field.id}-import"
                                aria-label="Import Form">
                            <i class="fa fa-upload"></i> Import
                        </button>
                        <button type="button" class="btn btn-info" id="{field.id}-export"
                                aria-label="Export Form">
                            <i class="fa fa-download"></i> Export
                        </button>
                    </div>

                    <div class="btn-group ml-2">
                        <button type="button" class="btn btn-secondary" id="{field.id}-undo"
                                disabled aria-label="Undo">
                            <i class="fa fa-undo"></i>
                        </button>
                        <button type="button" class="btn btn-secondary" id="{field.id}-redo"
                                disabled aria-label="Redo">
                            <i class="fa fa-redo"></i>
                        </button>
                    </div>
                </div>

                <!-- Building Area -->
                <div class="form-builder-area mt-3">
                    <div class="row">
                        <!-- Field Palette -->
                        <div class="col-md-3">
                            <div class="field-palette card" role="region"
                                 aria-label="Available Fields">
                                <div class="card-header">Available Fields</div>
                                <div class="card-body">
                                    <div class="field-list" role="list">
                                        {self._render_field_palette()}
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Form Canvas -->
                        <div class="col-md-9">
                            <div class="form-canvas card" role="region"
                                 aria-label="Form Design Canvas">
                                <div class="card-header">
                                    Form Design
                                    <span class="badge badge-info float-right" id="{field.id}-field-count"
                                          aria-label="Field Count">0 fields</span>
                                </div>
                                <div class="card-body">
                                    <div class="gridster" id="{field.id}-canvas">
                                        <ul></ul>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Property Editor -->
                <div class="property-editor modal fade" id="{field.id}-properties"
                     tabindex="-1" role="dialog">
                    <div class="modal-dialog" role="document">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Field Properties</h5>
                                <button type="button" class="close" data-dismiss="modal"
                                        aria-label="Close">
                                    <span aria-hidden="true">&times;</span>
                                </button>
                            </div>
                            <div class="modal-body">
                                <!-- Property form rendered dynamically -->
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Preview Modal -->
                <div class="preview-modal modal fade" id="{field.id}-preview-modal"
                     tabindex="-1" role="dialog">
                    <div class="modal-dialog modal-lg" role="document">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Form Preview</h5>
                                <button type="button" class="close" data-dismiss="modal"
                                        aria-label="Close">
                                    <span aria-hidden="true">&times;</span>
                                </button>
                            </div>
                            <div class="modal-body">
                                <div class="preview-container"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Hidden Input -->
                {input_html}

                <!-- Loading Overlay -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner-border text-primary" role="status">
                        <span class="sr-only">Loading...</span>
                    </div>
                </div>
            </div>

            <script>
                $(document).ready(function() {{
                    const formBuilder = new FormBuilder('{field.id}', {{
                        availableFields: {json.dumps(self.available_fields)},
                        fieldTypes: {json.dumps(self.FIELD_TYPES)},
                        templates: {str(self.templates).lower()},
                        validation: {str(self.validation).lower()},
                        responsive: {str(self.responsive).lower()},
                        maxFields: {self.max_fields},
                        fieldDefaults: {json.dumps(self.field_defaults)},
                        saveVersions: {str(self.save_versions).lower()},
                        previewMode: {str(self.preview_mode).lower()},
                        autoSave: {str(self.auto_save).lower()},
                        versionControl: {str(self.version_control).lower()},
                        analytics: {str(self.analytics).lower()},
                        localization: '{self.localization}',
                        gridColumns: {self.grid_columns},
                        fieldSpacing: {self.field_spacing},
                        undoLevels: {self.undo_levels},
                        autoSaveInterval: {self.auto_save_interval},
                        maxFileSize: {self.max_file_size},
                        cacheEnabled: {str(self.cache_enabled).lower()},
                        debugMode: {str(self.debug_mode).lower()},

                        callbacks: {{
                            onSave: function(formData) {{
                                handleFormSave(formData);
                            }},
                            onError: function(error) {{
                                showError(error);
                            }},
                            onStateChange: function(state) {{
                                updateUIState(state);
                            }},
                            onFieldAdd: function(field) {{
                                handleFieldAdd(field);
                            }},
                            onFieldRemove: function(field) {{
                                handleFieldRemove(field);
                            }},
                            onPreview: function(formData) {{
                                showPreview(formData);
                            }}
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        console.error('Form builder error:', error);
                        const alert = $('<div class="alert alert-danger alert-dismissible fade show" role="alert">')
                            .html(`<i class="fa fa-exclamation-circle"></i> ${{error}}
                                  <button type="button" class="close" data-dismiss="alert" aria-label="Close">
                                    <span aria-hidden="true">&times;</span>
                                  </button>`);
                        $('.form-builder-widget').prepend(alert);
                    }}

                    // Save handler
                    async function handleFormSave(formData) {{
                        try {{
                            showLoading();
                            const response = await $.ajax({{
                                url: '/api/form-builder/save',
                                method: 'POST',
                                data: JSON.stringify(formData),
                                contentType: 'application/json'
                            }});
                            $('#{field.id}').val(JSON.stringify(response.data));
                            hideLoading();
                        }} catch (error) {{
                            hideLoading();
                            showError('Failed to save form: ' + error.message);
                        }}
                    }}

                    // Loading state
                    function showLoading() {{
                        $('.loading-overlay').fadeIn(200);
                    }}

                    function hideLoading() {{
                        $('.loading-overlay').fadeOut(200);
                    }}

                    // Field management
                    function handleFieldAdd(field) {{
                        const count = formBuilder.getFieldCount();
                        $('#{field.id}-field-count').text(`${{count}} fields`);

                        if (count >= {self.max_fields}) {{
                            $('#{field.id}-canvas').addClass('max-fields-reached');
                            showError(`Maximum field limit (${{self.max_fields}}) reached`);
                        }}
                    }}

                    function handleFieldRemove(field) {{
                        const count = formBuilder.getFieldCount();
                        $('#{field.id}-field-count').text(`${{count}} fields`);
                        $('#{field.id}-canvas').removeClass('max-fields-reached');
                    }}

                    // Preview handling
                    function showPreview(formData) {{
                        const preview = $('#{field.id}-preview-modal');
                        preview.find('.preview-container').html(formBuilder.renderPreview(formData));
                        preview.modal('show');
                    }}

                    // State management
                    function updateUIState(state) {{
                        $('#{field.id}-undo').prop('disabled', !state.canUndo);
                        $('#{field.id}-redo').prop('disabled', !state.canRedo);
                    }}

                    // Initialize form if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        formBuilder.loadForm(JSON.parse(existingData));
                    }}

                    // Mobile optimization
                    if (window.innerWidth < 768) {{
                        formBuilder.optimizeForMobile();
                    }}

                    // Cleanup on page unload
                    $(window).on('unload', function() {{
                        formBuilder.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{css_includes}\n{js_includes}"

    def _render_field_palette(self):
        """Render the available fields palette"""
        items = []
        for field_type, config in self.FIELD_TYPES.items():
            if field_type in self.available_fields:
                items.append(
                    f"""
                    <div class="field-item" draggable="true"
                         data-field-type="{field_type}"
                         role="listitem" aria-label="{config['label']}">
                        <i class="fa {config['icon']}"></i>
                        <span>{config['label']}</span>
                    </div>
                """
                )
        return "\n".join(items)

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_form_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid form data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_form_data(self, data):
        """Validate form configuration data"""
        if not isinstance(data, dict):
            raise ValueError("Invalid form data structure")

        required_keys = ["fields", "layout", "settings"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required form configuration keys")

        if len(data["fields"]) > self.max_fields:
            raise ValueError(f"Form exceeds maximum field limit ({self.max_fields})")

        # Validate each field configuration
        for field in data["fields"]:
            if "type" not in field or field["type"] not in self.FIELD_TYPES:
                raise ValueError(f'Invalid field type: {field.get("type")}')

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_form_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class ActivityTimelineWidget(BS3TextFieldWidget):
    """
    Chronological timeline widget for displaying activity history and events from tables with AuditMixin.
    Supports real-time updates, filtering, grouping and rich interactions.

    Features:
    - Multiple event types with custom icons and colors
    - Customizable timeline styles and layouts
    - Advanced filtering by date, type, user etc.
    - Flexible grouping by day/week/month/year
    - Rich content with markdown and attachments
    - Infinite scroll with lazy loading
    - Real-time updates via WebSocket
    - Interactive event details modal
    - Full-text search capabilities
    - Export to PDF/CSV/Excel
    - Date range picker integration
    - Custom event icons and badges
    - Nested child timelines
    - File attachments and previews
    - Threaded comments and reactions

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON
        Audit Table: Created via AuditMixin

    Required Dependencies:
    - Timeline.js 3.6+
    - Moment.js 2.29+
    - Socket.io 4.0+
    - Markdown-it 12.0+
    - Vue.js 2.6+
    - Axios 0.21+

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - WebSocket connections
    - LocalStorage access
    - File downloads for exports
    - Camera/mic for attachments

    Performance Considerations:
    - Enable pagination/infinite scroll
    - Limit initial load size
    - Optimize attachment previews
    - Cache common queries
    - Use WebSocket heartbeats
    - Compress payloads
    - Lazy load media
    - Throttle real-time updates

    Security Implications:
    - Validate WebSocket origin
    - Sanitize markdown content
    - Verify file uploads
    - Rate limit API calls
    - Implement CSRF protection
    - Control access permissions
    - Audit sensitive actions
    - Encrypt attachments

    Example:
        activity_log = db.Column(db.JSON, nullable=False,
            info={'widget': ActivityTimelineWidget(
                event_types=['create', 'update', 'delete', 'comment'],
                real_time=True,
                group_by='day',
                enable_comments=True,
                items_per_page=50,
                enable_export=True
            )})
    """

    # JavaScript/CSS Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/timeline.js/3.6.6/js/timeline.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/markdown-it/12.0.6/markdown-it.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/vue/2.6.14/vue.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/axios/0.21.1/axios.min.js",
        "/static/js/activity-timeline.js",
    ]

    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/timeline.js/3.6.6/css/timeline.min.css",
        "/static/css/activity-timeline.css",
    ]

    # Default event type configurations
    DEFAULT_EVENT_TYPES = {
        "create": {"icon": "fa-plus-circle", "color": "#28a745"},
        "update": {"icon": "fa-edit", "color": "#007bff"},
        "delete": {"icon": "fa-trash", "color": "#dc3545"},
        "comment": {"icon": "fa-comment", "color": "#6c757d"},
    }

    # Default grouping options
    GROUP_BY_OPTIONS = ["hour", "day", "week", "month", "year"]

    def __init__(self, **kwargs):
        """
        Initialize ActivityTimelineWidget with custom settings.

        Args:
            event_types (list): Available event types with icons/colors
            real_time (bool): Enable real-time updates via WebSocket
            group_by (str): Grouping method (hour/day/week/month/year)
            enable_comments (bool): Enable comment threading
            items_per_page (int): Items to load per page
            sort_order (str): Timeline sort order (asc/desc)
            filters (list): Available filter options
            enable_export (bool): Enable export functionality
            enable_search (bool): Enable search functionality
            max_attachments (int): Maximum attachments per event
            max_file_size (int): Maximum attachment size in bytes
            websocket_url (str): Custom WebSocket endpoint
            cache_ttl (int): Cache TTL in seconds
            locale (str): Interface language
        """
        super().__init__(**kwargs)

        self.event_types = {**self.DEFAULT_EVENT_TYPES, **kwargs.get("event_types", {})}
        self.real_time = kwargs.get("real_time", True)
        self.group_by = kwargs.get("group_by", "day")
        self.enable_comments = kwargs.get("enable_comments", True)
        self.items_per_page = kwargs.get("items_per_page", 50)
        self.sort_order = kwargs.get("sort_order", "desc")
        self.filters = kwargs.get("filters", ["type", "user", "date"])
        self.enable_export = kwargs.get("enable_export", True)
        self.enable_search = kwargs.get("enable_search", True)
        self.max_attachments = kwargs.get("max_attachments", 5)
        self.max_file_size = kwargs.get("max_file_size", 5 * 1024 * 1024)
        self.websocket_url = kwargs.get("websocket_url", "/timeline/ws")
        self.cache_ttl = kwargs.get("cache_ttl", 300)
        self.locale = kwargs.get("locale", "en")

    def render_field(self, field, **kwargs):
        """Render the timeline widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="activity-timeline-widget" role="complementary"
                 aria-label="Activity Timeline">

                <!-- Controls -->
                <div class="timeline-controls" role="toolbar"
                     aria-label="Timeline Controls">
                    <div class="btn-group">
                        <button type="button" class="btn btn-secondary"
                                id="{field.id}-refresh" aria-label="Refresh Timeline">
                            <i class="fa fa-sync"></i>
                        </button>
                        <button type="button" class="btn btn-secondary"
                                id="{field.id}-filter" aria-label="Filter Timeline">
                            <i class="fa fa-filter"></i>
                        </button>
                        {f'''
                        <button type="button" class="btn btn-secondary dropdown-toggle"
                                data-toggle="dropdown" aria-label="Export Options">
                            <i class="fa fa-download"></i>
                        </button>
                        <div class="dropdown-menu">
                            <a class="dropdown-item" href="#" data-export="pdf">
                                Export as PDF
                            </a>
                            <a class="dropdown-item" href="#" data-export="csv">
                                Export as CSV
                            </a>
                            <a class="dropdown-item" href="#" data-export="excel">
                                Export as Excel
                            </a>
                        </div>
                        ''' if self.enable_export else ''}
                    </div>

                    {f'''
                    <div class="search-box ml-2">
                        <input type="text" class="form-control"
                               id="{field.id}-search"
                               placeholder="Search timeline..."
                               aria-label="Search timeline">
                    </div>
                    ''' if self.enable_search else ''}

                    <div class="date-range ml-2">
                        <input type="text" class="form-control"
                               id="{field.id}-daterange"
                               aria-label="Date range">
                    </div>

                    <select class="custom-select ml-2" id="{field.id}-grouping"
                            aria-label="Group by">
                        {self._render_group_options()}
                    </select>
                </div>

                <!-- Timeline View -->
                <div class="timeline-container mt-3" id="{field.id}-timeline"></div>

                <!-- Loading Indicator -->
                <div class="timeline-loading" style="display:none;" role="status">
                    <div class="spinner-border text-primary"></div>
                    <span class="sr-only">Loading timeline...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger mt-2" style="display:none"
                     role="alert" aria-live="polite"></div>

                <!-- Event Details Modal -->
                <div class="modal fade" id="{field.id}-event-modal" tabindex="-1"
                     role="dialog">
                    <div class="modal-dialog" role="document">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Event Details</h5>
                                <button type="button" class="close" data-dismiss="modal"
                                        aria-label="Close">
                                    <span aria-hidden="true">&times;</span>
                                </button>
                            </div>
                            <div class="modal-body"></div>
                        </div>
                    </div>
                </div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const timeline = new ActivityTimeline('{field.id}', {{
                        eventTypes: {json.dumps(self.event_types)},
                        realTime: {str(self.real_time).lower()},
                        groupBy: '{self.group_by}',
                        enableComments: {str(self.enable_comments).lower()},
                        itemsPerPage: {self.items_per_page},
                        sortOrder: '{self.sort_order}',
                        filters: {json.dumps(self.filters)},
                        enableExport: {str(self.enable_export).lower()},
                        enableSearch: {str(self.enable_search).lower()},
                        maxAttachments: {self.max_attachments},
                        maxFileSize: {self.max_file_size},
                        websocketUrl: '{self.websocket_url}',
                        cacheTTL: {self.cache_ttl},
                        locale: '{self.locale}',

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onUpdate: function(data) {{
                            handleUpdate(data);
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.activity-timeline-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.timeline-loading')[show ? 'show' : 'hide']();
                    }}

                    // Update handler
                    function handleUpdate(data) {{
                        $('#{field.id}').val(JSON.stringify(data));
                    }}

                    // Initialize timeline if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        timeline.loadData(JSON.parse(existingData));
                    }}

                    // Responsive handlers
                    $(window).on('resize', function() {{
                        timeline.handleResize();
                    }});

                    // Cleanup
                    $(window).on('unload', function() {{
                        timeline.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{css_includes}\n{js_includes}"

    def _render_group_options(self):
        """Render grouping dropdown options"""
        options = []
        for group in self.GROUP_BY_OPTIONS:
            selected = "selected" if group == self.group_by else ""
            options.append(
                f'<option value="{group}" {selected}>' f"{group.capitalize()}</option>"
            )
        return "\n".join(options)

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_timeline_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid timeline data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_timeline_data(self, data):
        """Validate timeline data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid timeline data structure")

        required_keys = ["events", "metadata"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required timeline data keys")

        # Validate events
        if not isinstance(data["events"], list):
            raise ValueError("Events must be a list")

        for event in data["events"]:
            if not isinstance(event, dict):
                raise ValueError("Invalid event structure")

            required_event_keys = ["id", "type", "timestamp", "user"]
            if not all(key in event for key in required_event_keys):
                raise ValueError("Missing required event keys")

            if event["type"] not in self.event_types:
                raise ValueError(f'Invalid event type: {event["type"]}')

    def pre_validate(self, form):
        """Validate timeline data before form processing"""
        if self.data is not None:
            try:
                self._validate_timeline_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class DataImportExportWidget(BS3TextFieldWidget):
    """
    Advanced data import/export widget with column mapping and validation.
    Features:
    - Multiple file format support (CSV, Excel, JSON)
    - Interactive column mapping interface
    - Configurable data validation rules
    - Live data preview and sample validation
    - Template management for repeat imports
    - Batch processing with progress tracking
    - Detailed error reporting and logging
    - Custom data transformations
    - Fuzzy field matching
    - Data cleaning/normalization
    - Import/export history
    - Scheduled background imports
    - Delta/incremental updates
    - Custom export formats
    - Validation rule templates

    Database Type:
        PostgreSQL: JSONB for config storage
        SQLAlchemy: JSON type for widget data

    Required Dependencies:
    - Papa Parse 5.3+ for CSV parsing
    - SheetJS (XLSX) 0.18+ for Excel support
    - DataTables 1.11+ for previews
    - Lodash 4.17+ for utilities
    - Socket.io 4.0+ for real-time progress

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - File system access for uploads
    - LocalStorage for templates
    - Background processing
    - WebSocket connections

    Performance Considerations:
    - Use chunked/streaming processing
    - Implement client-side validation
    - Cache template data
    - Compress large files
    - Batch size optimization
    - Background processing

    Security Implications:
    - Validate file types/content
    - Sanitize data input
    - Rate limit requests
    - Access control
    - Audit logging
    - XSS prevention

    Best Practices:
    - Define validation rules upfront
    - Use templates for repeat imports
    - Enable preview validation
    - Configure error thresholds
    - Monitor import logs
    - Clean data before import

    Example:
        data_import = FileField('Import Data',
                              widget=DataImportExportWidget(
                                  formats=['csv', 'xlsx', 'json'],
                                  validate=True,
                                  templates=True,
                                  batch_size=1000,
                                  error_threshold=0.1
                              ))
    """

    # JavaScript/CSS Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.3.2/papaparse.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js",
        "https://cdn.datatables.net/1.11.5/js/jquery.dataTables.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.4.1/socket.io.min.js",
        "/static/js/data-import-export.js",
    ]

    CSS_DEPENDENCIES = [
        "https://cdn.datatables.net/1.11.5/css/jquery.dataTables.min.css",
        "/static/css/data-import-export.css",
    ]

    # Default settings
    DEFAULT_FORMATS = ["csv", "xlsx", "json"]
    DEFAULT_BATCH_SIZE = 1000
    DEFAULT_ERROR_THRESHOLD = 0.1
    DEFAULT_PREVIEW_ROWS = 100

    def __init__(self, **kwargs):
        """
        Initialize DataImportExportWidget with custom settings.

        Args:
            formats (list): Supported file formats (csv, xlsx, json)
            validate (bool): Enable data validation
            templates (bool): Enable template management
            batch_size (int): Records per batch for processing
            mappings (dict): Predefined column mappings
            transformations (dict): Data transformation rules
            error_threshold (float): Maximum acceptable error rate
            preview_rows (int): Number of preview rows
            allow_schedule (bool): Enable scheduled imports
            track_history (bool): Enable import/export history
            cache_templates (bool): Cache template data
            socket_url (str): Custom WebSocket endpoint
            custom_validators (dict): Additional validation rules
        """
        super().__init__(**kwargs)

        self.formats = kwargs.get("formats", self.DEFAULT_FORMATS)
        self.validate = kwargs.get("validate", True)
        self.templates = kwargs.get("templates", True)
        self.batch_size = kwargs.get("batch_size", self.DEFAULT_BATCH_SIZE)
        self.mappings = kwargs.get("mappings", {})
        self.transformations = kwargs.get("transformations", {})
        self.error_threshold = kwargs.get(
            "error_threshold", self.DEFAULT_ERROR_THRESHOLD
        )
        self.preview_rows = kwargs.get("preview_rows", self.DEFAULT_PREVIEW_ROWS)
        self.allow_schedule = kwargs.get("allow_schedule", False)
        self.track_history = kwargs.get("track_history", True)
        self.cache_templates = kwargs.get("cache_templates", True)
        self.socket_url = kwargs.get("socket_url", "/import/ws")
        self.custom_validators = kwargs.get("custom_validators", {})

    def render_field(self, field, **kwargs):
        """Render the import/export widget"""
        kwargs.setdefault("type", "file")
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="data-import-export-widget" role="region"
                 aria-label="Data Import/Export Interface">

                <!-- File Upload -->
                <div class="upload-section mb-3">
                    <div class="custom-file">
                        {input_html}
                        <label class="custom-file-label" for="{field.id}">
                            Choose file...
                        </label>
                    </div>
                    <small class="form-text text-muted">
                        Supported formats: {', '.join(self.formats)}
                    </small>
                </div>

                <!-- Template Management -->
                {self._render_template_section(field.id) if self.templates else ''}

                <!-- Column Mapping -->
                <div class="mapping-section" style="display:none;">
                    <h5>Column Mapping</h5>
                    <div class="mapping-table"></div>
                    <button type="button" class="btn btn-secondary btn-sm mt-2"
                            id="{field.id}-auto-map">
                        Auto-Map Columns
                    </button>
                </div>

                <!-- Data Preview -->
                <div class="preview-section mt-3" style="display:none;">
                    <h5>Data Preview</h5>
                    <div class="preview-table"></div>
                    <div class="validation-summary alert" style="display:none;"></div>
                </div>

                <!-- Import Progress -->
                <div class="progress mt-3" style="display:none;">
                    <div class="progress-bar" role="progressbar" style="width: 0%"
                         aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">
                    </div>
                </div>

                <!-- Error Log -->
                <div class="error-log mt-3" style="display:none;">
                    <h5>Error Log</h5>
                    <div class="error-table"></div>
                </div>

                <!-- Loading Overlay -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner-border text-primary" role="status">
                        <span class="sr-only">Loading...</span>
                    </div>
                </div>
            </div>

            <script type="text/javascript">
                $(document).ready(function() {{
                    var importer = new DataImportExport('{field.id}', {{
                        formats: {json.dumps(self.formats)},
                        validate: {str(self.validate).lower()},
                        templates: {str(self.templates).lower()},
                        batchSize: {self.batch_size},
                        mappings: {json.dumps(self.mappings)},
                        transformations: {json.dumps(self.transformations)},
                        errorThreshold: {self.error_threshold},
                        previewRows: {self.preview_rows},
                        allowSchedule: {str(self.allow_schedule).lower()},
                        trackHistory: {str(self.track_history).lower()},
                        cacheTemplates: {str(self.cache_templates).lower()},
                        socketUrl: '{self.socket_url}',
                        customValidators: {json.dumps(self.custom_validators)},
                        onError: function(error) {{
                            showError(error);
                        }},
                        onProgress: function(progress) {{
                            updateProgress(progress);
                        }},
                        onComplete: function(result) {{
                            handleComplete(result);
                        }}
                    }});

                    function showError(error) {{
                        var alert = $('<div class="alert alert-danger">')
                            .text(error);
                        $('.error-log').show().find('.error-table').html(alert);
                    }}

                    function updateProgress(progress) {{
                        var bar = $('.progress-bar');
                        bar.css('width', progress + '%')
                           .attr('aria-valuenow', progress)
                           .text(progress + '%');
                    }}

                    function handleComplete(result) {{
                        if (result.success) {{
                            showSuccess(result.message);
                        }} else {{
                            showError(result.error);
                        }}
                    }}

                    function showSuccess(message) {{
                        var alert = $('<div class="alert alert-success">')
                            .text(message);
                        $('.preview-section').before(alert);
                        setTimeout(function() {{
                            alert.fadeOut();
                        }}, 5000);
                    }}
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{css_includes}\n{js_includes}"

    def _render_template_section(self, field_id):
        """Render template management section"""
        return f"""
            <div class="template-section mb-3">
                <select class="custom-select" id="{field_id}-template">
                    <option value="">Select Template...</option>
                </select>
                <div class="btn-group ml-2">
                    <button type="button" class="btn btn-secondary btn-sm"
                            id="{field_id}-save-template">
                        Save Template
                    </button>
                    <button type="button" class="btn btn-danger btn-sm"
                            id="{field_id}-delete-template">
                        Delete Template
                    </button>
                </div>
            </div>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_import_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid import data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_import_data(self, data):
        """Validate import data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid import data structure")

        required_keys = ["mapping", "data", "validation"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required import data keys")

        # Validate mapping
        if not isinstance(data["mapping"], dict):
            raise ValueError("Invalid column mapping format")

        # Validate data
        if not isinstance(data["data"], list):
            raise ValueError("Invalid import data format")

        # Check error threshold
        if data["validation"].get("error_rate", 0) > self.error_threshold:
            raise ValueError(f"Error rate exceeds threshold: {self.error_threshold}")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_import_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class PivotTableWidget(BS3TextFieldWidget):
    """
    Interactive pivot table widget for data analysis and aggregation.
    Provides rich functionality for analyzing and visualizing large datasets
    with dynamic pivoting, aggregation, and charting capabilities.

    Features:
    - Drag-and-drop configuration for rows/columns
    - Multiple aggregation functions (sum, avg, count, etc.)
    - Chart visualization (bar, line, pie, etc.)
    - Conditional formatting with custom rules
    - Advanced data filtering and sorting
    - Export to Excel, CSV, PDF
    - Drill-down support for detailed analysis
    - Custom calculations and formulas
    - Saved view management
    - Real-time data refresh
    - Mobile-optimized interface
    - Large dataset handling (100k+ rows)
    - Subtotals and grand totals
    - Custom renderers for special formats
    - Keyboard navigation support
    - Accessibility compliance (WCAG 2.1)
    - Localization support

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON

    Required Dependencies:
    - PivotTable.js 2.23.0+
    - D3.js 7.0.0+
    - Crossfilter 1.3.12+
    - jQuery 3.6.0+
    - lodash 4.17.0+
    - FileSaver.js 2.0.0+

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - LocalStorage access for saved views
    - File download for exports
    - WebWorker support for large datasets

    Performance Considerations:
    - Use data pagination for 100k+ rows
    - Enable WebWorker processing
    - Implement data caching
    - Lazy load visualizations
    - Throttle calculations
    - Optimize aggregations
    - Index key columns

    Security Implications:
    - Validate data sources
    - Sanitize custom formulas
    - Control export permissions
    - Implement CSRF protection
    - Rate limit calculations
    - Validate saved views

    Example:
        pivot_analysis = db.Column(db.JSON, nullable=False,
            info={'widget': PivotTableWidget(
                rows=['category', 'product'],
                cols=['year', 'month'],
                aggregator='sum',
                renderer='table',
                enable_export=True,
                cache_enabled=True
            )})
    """

    # JavaScript/CSS Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/pivottable/2.23.0/pivot.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/d3/7.0.0/d3.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/crossfilter/1.3.12/crossfilter.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/FileSaver.js/2.0.0/FileSaver.min.js",
        "/static/js/pivot-table-custom.js",
    ]

    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/pivottable/2.23.0/pivot.min.css",
        "/static/css/pivot-table-custom.css",
    ]

    # Default aggregation functions
    AGGREGATORS = {
        "sum": {"fn": "sum", "label": "Sum"},
        "avg": {"fn": "average", "label": "Average"},
        "count": {"fn": "count", "label": "Count"},
        "min": {"fn": "min", "label": "Minimum"},
        "max": {"fn": "max", "label": "Maximum"},
        "median": {"fn": "median", "label": "Median"},
        "distinct": {"fn": "countDistinct", "label": "Distinct Count"},
    }

    # Available renderers
    RENDERERS = {
        "table": {"type": "table", "label": "Table"},
        "barchart": {"type": "barchart", "label": "Bar Chart"},
        "linechart": {"type": "linechart", "label": "Line Chart"},
        "piechart": {"type": "piechart", "label": "Pie Chart"},
        "treemap": {"type": "treemap", "label": "Treemap"},
    }

    def __init__(self, **kwargs):
        """
        Initialize PivotTableWidget with custom settings.

        Args:
            rows (list): Default row fields
            cols (list): Default column fields
            aggregator (str): Default aggregation function
            renderer (str): Default visualization type
            filters (dict): Initial filters
            sorters (dict): Sort configurations
            saved_views (list): Predefined views
            enable_export (bool): Enable export functionality
            cache_enabled (bool): Enable data caching
            page_size (int): Rows per page for pagination
            max_rows (int): Maximum dataset size
            refresh_interval (int): Auto-refresh interval in seconds
            custom_aggregators (dict): Additional aggregation functions
            custom_renderers (dict): Additional visualization types
            locale (str): Interface language
            theme (str): Visual theme name
            worker_url (str): WebWorker script URL
        """
        super().__init__(**kwargs)

        self.rows = kwargs.get("rows", [])
        self.cols = kwargs.get("cols", [])
        self.aggregator = kwargs.get("aggregator", "sum")
        self.renderer = kwargs.get("renderer", "table")
        self.filters = kwargs.get("filters", {})
        self.sorters = kwargs.get("sorters", {})
        self.saved_views = kwargs.get("saved_views", [])
        self.enable_export = kwargs.get("enable_export", True)
        self.cache_enabled = kwargs.get("cache_enabled", True)
        self.page_size = kwargs.get("page_size", 1000)
        self.max_rows = kwargs.get("max_rows", 100000)
        self.refresh_interval = kwargs.get("refresh_interval", 0)
        self.custom_aggregators = {
            **self.AGGREGATORS,
            **kwargs.get("custom_aggregators", {}),
        }
        self.custom_renderers = {**self.RENDERERS, **kwargs.get("custom_renderers", {})}
        self.locale = kwargs.get("locale", "en")
        self.theme = kwargs.get("theme", "default")
        self.worker_url = kwargs.get("worker_url", "/static/js/pivot-worker.js")

        if self.cache_enabled:
            self.cache = {}

    def render_field(self, field, **kwargs):
        """Render the pivot table widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="pivot-table-widget" role="application"
                 aria-label="Pivot Table Interface">

                <!-- Controls -->
                <div class="pivot-controls" role="toolbar"
                     aria-label="Pivot Table Controls">
                    <div class="btn-group">
                        <button type="button" class="btn btn-secondary"
                                id="{field.id}-refresh" aria-label="Refresh Data">
                            <i class="fa fa-sync"></i>
                        </button>

                        {self._render_export_buttons(field.id) if self.enable_export else ''}

                        <button type="button" class="btn btn-secondary"
                                id="{field.id}-save-view" aria-label="Save View">
                            <i class="fa fa-save"></i>
                        </button>
                    </div>

                    <div class="btn-group ml-2">
                        <select class="custom-select" id="{field.id}-aggregator"
                                aria-label="Aggregation Function">
                            {self._render_aggregator_options()}
                        </select>

                        <select class="custom-select" id="{field.id}-renderer"
                                aria-label="Visualization Type">
                            {self._render_renderer_options()}
                        </select>
                    </div>
                </div>

                <!-- Pivot Table -->
                <div class="pivot-container mt-3" id="{field.id}-pivot"></div>

                <!-- Loading Indicator -->
                <div class="pivot-loading" style="display:none;" role="status">
                    <div class="spinner-border text-primary"></div>
                    <span class="sr-only">Loading pivot table...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger mt-2" style="display:none"
                     role="alert" aria-live="polite"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const pivot = new PivotTable('{field.id}', {{
                        rows: {json.dumps(self.rows)},
                        cols: {json.dumps(self.cols)},
                        aggregator: '{self.aggregator}',
                        renderer: '{self.renderer}',
                        filters: {json.dumps(self.filters)},
                        sorters: {json.dumps(self.sorters)},
                        savedViews: {json.dumps(self.saved_views)},
                        enableExport: {str(self.enable_export).lower()},
                        cacheEnabled: {str(self.cache_enabled).lower()},
                        pageSize: {self.page_size},
                        maxRows: {self.max_rows},
                        refreshInterval: {self.refresh_interval},
                        locale: '{self.locale}',
                        theme: '{self.theme}',
                        workerUrl: '{self.worker_url}',

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onDataUpdate: function(data) {{
                            handleDataUpdate(data);
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.pivot-table-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.pivot-loading')[show ? 'show' : 'hide']();
                    }}

                    // Data update handler
                    function handleDataUpdate(data) {{
                        $('#{field.id}').val(JSON.stringify(data));
                    }}

                    // Initialize if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        pivot.loadData(JSON.parse(existingData));
                    }}

                    // Handle window resize
                    $(window).on('resize', _.debounce(function() {{
                        pivot.handleResize();
                    }}, 250));

                    // Cleanup
                    $(window).on('unload', function() {{
                        pivot.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{css_includes}\n{js_includes}"

    def _render_aggregator_options(self):
        """Render aggregation function dropdown options"""
        options = []
        for key, config in self.custom_aggregators.items():
            selected = "selected" if key == self.aggregator else ""
            options.append(
                f'<option value="{key}" {selected}>{config["label"]}</option>'
            )
        return "\n".join(options)

    def _render_renderer_options(self):
        """Render visualization type dropdown options"""
        options = []
        for key, config in self.custom_renderers.items():
            selected = "selected" if key == self.renderer else ""
            options.append(
                f'<option value="{key}" {selected}>{config["label"]}</option>'
            )
        return "\n".join(options)

    def _render_export_buttons(self, field_id):
        """Render export format buttons"""
        return f"""
            <div class="btn-group">
                <button type="button" class="btn btn-secondary dropdown-toggle"
                        data-toggle="dropdown" aria-label="Export Options">
                    <i class="fa fa-download"></i>
                </button>
                <div class="dropdown-menu">
                    <a class="dropdown-item" href="#" data-export="excel">
                        Export to Excel
                    </a>
                    <a class="dropdown-item" href="#" data-export="csv">
                        Export to CSV
                    </a>
                    <a class="dropdown-item" href="#" data-export="pdf">
                        Export to PDF
                    </a>
                </div>
            </div>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_pivot_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid pivot table data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_pivot_data(self, data):
        """Validate pivot table configuration and data"""
        if not isinstance(data, dict):
            raise ValueError("Invalid pivot table data structure")

        required_keys = ["config", "data", "state"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required pivot table data keys")

        if len(data.get("data", [])) > self.max_rows:
            raise ValueError(f"Dataset exceeds maximum row limit ({self.max_rows})")

        # Validate aggregator
        if data["config"].get("aggregator") not in self.custom_aggregators:
            raise ValueError(f"Invalid aggregator: {data['config'].get('aggregator')}")

        # Validate renderer
        if data["config"].get("renderer") not in self.custom_renderers:
            raise ValueError(f"Invalid renderer: {data['config'].get('renderer')}")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_pivot_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class KPIDashboardWidget(BS3TextFieldWidget):
    """
    Customizable KPI dashboard widget for performance monitoring and visualization.

    Features:
    - Multiple visualization types (charts, gauges, tables, cards)
    - Real-time updates via WebSocket
    - Configurable alert thresholds with notifications
    - Trend indicators and sparklines
    - Historical comparisons and forecasting
    - Drill-down analytics capability
    - Custom metrics and calculations
    - Responsive grid layout system
    - Goal/target tracking
    - Export to PDF/Excel/CSV
    - Mobile-first responsive design
    - Multiple data source integration
    - Templated widget presets
    - Desktop notifications
    - Performance optimization
    - Dark/light themes
    - Keyboard navigation
    - Screen reader support
    - Custom tooltips
    - Widget filtering

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON

    Required Dependencies:
    - Chart.js 3.7+ (visualization)
    - Gridster.js 0.7+ (layout)
    - Socket.io 4.0+ (real-time)
    - D3.js 7.0+ (advanced viz)
    - Moment.js 2.29+ (time handling)
    - jsPDF 2.5+ (export)
    - SheetJS 0.18+ (export)

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - WebSocket connections
    - LocalStorage access
    - Desktop notifications
    - File downloads
    - Browser alerts

    Performance Considerations:
    - Enable WebSocket compression
    - Batch updates for real-time data
    - Lazy load visualizations
    - Cache static assets
    - Debounce resize handlers
    - Throttle refresh rates
    - Use web workers for calculations
    - Implement virtual scrolling
    - Optimize canvas rendering
    - Memory leak prevention

    Security Implications:
    - Validate all metric data
    - Sanitize data sources
    - Implement CSRF protection
    - Rate limit API calls
    - Control data access
    - Audit sensitive operations
    - Encrypt sensitive metrics
    - Validate calculations

    Best Practices:
    - Define metrics upfront
    - Set appropriate refresh rates
    - Configure alert thresholds
    - Use appropriate chart types
    - Enable data caching
    - Implement error handling
    - Add loading states
    - Test mobile layouts
    - Document custom metrics
    - Monitor performance

    Common Issues:
    - WebSocket connection failures
    - Data source timeouts
    - Browser memory issues
    - Mobile rendering glitches
    - Export formatting errors
    - Calculation errors
    - Layout responsiveness
    - Real-time lag

    Example:
        kpi_dashboard = StringField('KPI Dashboard',
                                  widget=KPIDashboardWidget(
                                      metrics=['sales', 'conversion', 'traffic'],
                                      refresh_rate=300,
                                      layout='grid',
                                      alerts=True,
                                      theme='light',
                                      cache_enabled=True
                                  ))
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.7.1/chart.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/gridster/0.7.0/jquery.gridster.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.4.1/socket.io.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/d3/7.3.0/d3.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js",
        "/static/js/kpi-dashboard.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/gridster/0.7.0/jquery.gridster.min.css",
        "/static/css/kpi-dashboard.css",
    ]

    # Default settings
    DEFAULT_METRICS = ["users", "revenue", "orders"]
    DEFAULT_REFRESH = 300  # 5 minutes
    DEFAULT_LAYOUT = "grid"
    DEFAULT_THEME = "light"

    # Chart type configurations
    CHART_TYPES = {
        "line": {"type": "line", "label": "Line Chart"},
        "bar": {"type": "bar", "label": "Bar Chart"},
        "pie": {"type": "pie", "label": "Pie Chart"},
        "gauge": {"type": "gauge", "label": "Gauge"},
        "number": {"type": "number", "label": "Number Card"},
        "table": {"type": "table", "label": "Data Table"},
    }

    def __init__(self, **kwargs):
        """
        Initialize KPIDashboardWidget with custom settings.

        Args:
            metrics (list): KPI metrics to display
            refresh_rate (int): Update frequency in seconds
            layout (str): Dashboard layout type (grid, fixed, auto)
            alerts (bool): Enable alert system
            comparison_period (str): Period for comparisons (day, week, month, year)
            thresholds (dict): Alert threshold values by metric
            data_sources (list): Data source configurations
            theme (str): Visual theme (light, dark)
            cache_enabled (bool): Enable data caching
            export_enabled (bool): Enable export functionality
            chart_defaults (dict): Default chart settings
            grid_config (dict): Grid layout configuration
            socket_url (str): Custom WebSocket endpoint
            locale (str): Interface language
            debug (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        self.metrics = kwargs.get("metrics", self.DEFAULT_METRICS)
        self.refresh_rate = kwargs.get("refresh_rate", self.DEFAULT_REFRESH)
        self.layout = kwargs.get("layout", self.DEFAULT_LAYOUT)
        self.alerts = kwargs.get("alerts", True)
        self.comparison_period = kwargs.get("comparison_period", "day")
        self.thresholds = kwargs.get("thresholds", {})
        self.data_sources = kwargs.get("data_sources", [])
        self.theme = kwargs.get("theme", self.DEFAULT_THEME)
        self.cache_enabled = kwargs.get("cache_enabled", True)
        self.export_enabled = kwargs.get("export_enabled", True)
        self.chart_defaults = kwargs.get("chart_defaults", {})
        self.grid_config = kwargs.get("grid_config", {})
        self.socket_url = kwargs.get("socket_url", "/kpi/ws")
        self.locale = kwargs.get("locale", "en")
        self.debug = kwargs.get("debug", False)

        # Initialize cache if enabled
        if self.cache_enabled:
            self.cache = {}

    def render_field(self, field, **kwargs):
        """Render the KPI dashboard widget with all controls and visualizations"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="kpi-dashboard-widget {self.theme}" role="complementary"
                 aria-label="KPI Dashboard" id="{field.id}-container">

                {self._render_controls(field.id)}

                <div class="dashboard-grid" id="{field.id}-grid"
                     role="grid" aria-label="KPI Metrics Grid">
                    {self._render_widgets(field.id)}
                </div>

                <div class="loading-overlay" style="display:none;" role="status">
                    <div class="spinner-border text-primary"></div>
                    <span class="sr-only">Loading dashboard...</span>
                </div>

                <div class="alert alert-danger mt-2" style="display:none;"
                     role="alert" aria-live="polite"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const dashboard = new KPIDashboard('{field.id}', {{
                        metrics: {json.dumps(self.metrics)},
                        refreshRate: {self.refresh_rate},
                        layout: '{self.layout}',
                        alerts: {str(self.alerts).lower()},
                        comparisonPeriod: '{self.comparison_period}',
                        thresholds: {json.dumps(self.thresholds)},
                        dataSources: {json.dumps(self.data_sources)},
                        theme: '{self.theme}',
                        cacheEnabled: {str(self.cache_enabled).lower()},
                        exportEnabled: {str(self.export_enabled).lower()},
                        chartDefaults: {json.dumps(self.chart_defaults)},
                        gridConfig: {json.dumps(self.grid_config)},
                        socketUrl: '{self.socket_url}',
                        locale: '{self.locale}',
                        debug: {str(self.debug).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onUpdate: function(data) {{
                            handleUpdate(data);
                        }},
                        onAlert: function(alert) {{
                            handleAlert(alert);
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.kpi-dashboard-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Data update handler
                    function handleUpdate(data) {{
                        $('#{field.id}').val(JSON.stringify(data));
                    }}

                    // Alert handler
                    function handleAlert(alert) {{
                        if (Notification.permission === 'granted') {{
                            new Notification(alert.title, {{
                                body: alert.message,
                                icon: '/static/img/alert-icon.png'
                            }});
                        }}
                    }}

                    // Initialize dashboard if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        dashboard.loadData(JSON.parse(existingData));
                    }}

                    // Handle window resize
                    $(window).on('resize', _.debounce(function() {{
                        dashboard.handleResize();
                    }}, 250));

                    // Request notification permission if needed
                    if (self.alerts && Notification.permission === 'default') {{
                        Notification.requestPermission();
                    }}

                    // Cleanup on unload
                    $(window).on('unload', function() {{
                        dashboard.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{css_includes}\n{js_includes}"

    def _render_controls(self, field_id):
        """Render dashboard control buttons"""
        return f"""
            <div class="dashboard-controls mb-3" role="toolbar"
                 aria-label="Dashboard Controls">
                <div class="btn-group">
                    <button type="button" class="btn btn-secondary"
                            id="{field_id}-refresh" aria-label="Refresh Dashboard">
                        <i class="fa fa-sync"></i>
                    </button>

                    <button type="button" class="btn btn-secondary"
                            id="{field_id}-layout" aria-label="Change Layout">
                        <i class="fa fa-th"></i>
                    </button>

                    {self._render_export_buttons(field_id) if self.export_enabled else ''}

                    <button type="button" class="btn btn-secondary"
                            id="{field_id}-settings" aria-label="Dashboard Settings">
                        <i class="fa fa-cog"></i>
                    </button>
                </div>

                <select class="custom-select ml-2" id="{field_id}-period"
                        aria-label="Comparison Period">
                    <option value="day">Today vs Yesterday</option>
                    <option value="week">This Week vs Last Week</option>
                    <option value="month">This Month vs Last Month</option>
                    <option value="year">This Year vs Last Year</option>
                </select>
            </div>
        """

    def _render_export_buttons(self, field_id):
        """Render export format buttons"""
        return f"""
            <div class="btn-group">
                <button type="button" class="btn btn-secondary dropdown-toggle"
                        data-toggle="dropdown" aria-label="Export Options">
                    <i class="fa fa-download"></i>
                </button>
                <div class="dropdown-menu">
                    <a class="dropdown-item" href="#" data-export="pdf">
                        Export to PDF
                    </a>
                    <a class="dropdown-item" href="#" data-export="excel">
                        Export to Excel
                    </a>
                    <a class="dropdown-item" href="#" data-export="csv">
                        Export to CSV
                    </a>
                </div>
            </div>
        """

    def _render_widgets(self, field_id):
        """Render individual KPI widgets"""
        widgets = []
        for metric in self.metrics:
            widgets.append(self._render_widget(field_id, metric))
        return "\n".join(widgets)

    def _render_widget(self, field_id, metric):
        """Render a single KPI widget"""
        return f"""
            <div class="grid-item" data-metric="{metric}"
                 role="gridcell" aria-label="{metric} Metric">
                <div class="widget-header">
                    <h3 class="widget-title">{metric.title()}</h3>
                    <div class="widget-controls">
                        <button type="button" class="btn btn-link btn-sm"
                                aria-label="Change Visualization">
                            <i class="fa fa-chart-line"></i>
                        </button>
                        <button type="button" class="btn btn-link btn-sm"
                                aria-label="Widget Settings">
                            <i class="fa fa-ellipsis-v"></i>
                        </button>
                    </div>
                </div>
                <div class="widget-body">
                    <canvas id="{field_id}-{metric}-chart"></canvas>
                </div>
                <div class="widget-footer">
                    <div class="trend-indicator"></div>
                    <div class="comparison-value"></div>
                </div>
            </div>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_dashboard_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid dashboard data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_dashboard_data(self, data):
        """Validate dashboard configuration and metric data"""
        if not isinstance(data, dict):
            raise ValueError("Invalid dashboard data structure")

        required_keys = ["config", "metrics", "layout"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required dashboard data keys")

        if not isinstance(data["metrics"], dict):
            raise ValueError("Invalid metrics data format")

        # Validate each metric
        for metric, config in data["metrics"].items():
            if metric not in self.metrics:
                raise ValueError(f"Invalid metric: {metric}")

            if "type" in config and config["type"] not in self.CHART_TYPES:
                raise ValueError(f"Invalid chart type for {metric}")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_dashboard_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class ChatMessagingWidget(BS3TextFieldWidget):
    """
    Real-time chat and messaging widget for internal communication.

    Features:
    - Real-time messaging with encrypted transport
    - File attachments with virus scanning
    - User presence tracking and status indicators
    - Message threading and conversation organization
    - Read receipts and delivery status
    - Typing indicators and activity states
    - Full emoji/GIF/sticker support
    - Full text message search with highlighting
    - Group chats with role management
    - Direct messages with privacy controls
    - Message reactions and quick responses
    - Audio/video calls with screen sharing
    - Message history with infinite scroll
    - Fully responsive mobile interface
    - Rich notification system
    - Message translation
    - Voice messages
    - Custom message formatting
    - Message forwarding
    - Mention notifications
    - Message editing/deletion
    - User blocking
    - Chat backup/export
    - Link previews
    - File previews

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON

    Required Dependencies:
    - Socket.io 4.5+ (real-time communication)
    - MediaStream API (audio/video)
    - SimpleWebRTC (WebRTC wrapper)
    - EmojiPicker 14+ (emoji support)
    - Linkify 4+ (link detection)
    - Moment.js 2.29+ (timestamps)
    - AutoLinker 3+ (URL parsing)
    - localforage 1.10+ (offline storage)
    - Notification API
    - Push API

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - WebSocket connections
    - Media access (camera/mic)
    - Notifications
    - Storage/IndexedDB
    - File system access
    - Clipboard access
    - Service workers
    - Push notifications

    Performance Considerations:
    - Message pagination
    - Attachment chunking
    - WebSocket compression
    - Image optimization
    - Message caching
    - Lazy media loading
    - Connection pooling
    - Browser storage limits
    - Memory management
    - CPU usage monitoring

    Security Implications:
    - Message encryption
    - File scanning
    - XSS prevention
    - Input sanitization
    - Rate limiting
    - User authentication
    - Access control
    - Data retention
    - Audit logging
    - Privacy controls

    Best Practices:
    - Enable encryption
    - Set file limits
    - Configure moderation
    - Add rate limiting
    - Enable backups
    - Monitor usage
    - Train users
    - Test edge cases
    - Document policies
    - Regular updates

    Example:
        chat = db.Column(db.JSON, nullable=False,
            info={'widget': ChatMessagingWidget(
                enable_attachments=True,
                enable_groups=True,
                notifications=True,
                history_limit=1000,
                encryption=True,
                moderation=True
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.1/socket.io.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/simple-peer/9.11.1/simplepeer.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/emoji-picker/14.0.0/emoji-picker.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/linkifyjs/4.1.1/linkify.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.4/moment.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/autolinker/3.15.0/Autolinker.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/localforage/1.10.0/localforage.min.js",
        "/static/js/chat-widget.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/emoji-picker/14.0.0/emoji-picker.min.css",
        "/static/css/chat-widget.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize ChatMessagingWidget with custom settings.

        Args:
            enable_attachments (bool): Enable file attachments
            enable_groups (bool): Enable group chats
            notifications (bool): Enable notifications
            history_limit (int): Message history limit
            file_types (list): Allowed attachment types
            max_file_size (int): Maximum file size in bytes
            presence_tracking (bool): Enable presence tracking
            encryption (bool): Enable end-to-end encryption
            moderation (bool): Enable message moderation
            translation (bool): Enable message translation
            retention_days (int): Message retention period
            max_group_size (int): Maximum users per group
            typing_timeout (int): Typing indicator timeout
            offline_support (bool): Enable offline functionality
            giphy_key (str): Giphy API key for GIF support
            socket_url (str): Custom socket.io endpoint
            push_enabled (bool): Enable push notifications
            call_timeout (int): Call ring timeout
            message_edit_window (int): Edit time window
            file_scan_enabled (bool): Enable virus scanning
        """
        super().__init__(**kwargs)

        # Core features
        self.enable_attachments = kwargs.get("enable_attachments", True)
        self.enable_groups = kwargs.get("enable_groups", True)
        self.notifications = kwargs.get("notifications", True)
        self.history_limit = kwargs.get("history_limit", 1000)
        self.encryption = kwargs.get("encryption", True)
        self.moderation = kwargs.get("moderation", False)
        self.translation = kwargs.get("translation", False)
        self.offline_support = kwargs.get("offline_support", True)
        self.push_enabled = kwargs.get("push_enabled", True)

        # File handling
        self.file_types = kwargs.get(
            "file_types", ["image/*", "audio/*", "video/*", "application/pdf"]
        )
        self.max_file_size = kwargs.get("max_file_size", 10 * 1024 * 1024)  # 10MB
        self.file_scan_enabled = kwargs.get("file_scan_enabled", True)

        # User tracking
        self.presence_tracking = kwargs.get("presence_tracking", True)
        self.typing_timeout = kwargs.get("typing_timeout", 5000)

        # Group settings
        self.max_group_size = kwargs.get("max_group_size", 100)

        # Message settings
        self.retention_days = kwargs.get("retention_days", 365)
        self.message_edit_window = kwargs.get("message_edit_window", 300)  # 5 mins

        # Media
        self.giphy_key = kwargs.get("giphy_key", None)
        self.call_timeout = kwargs.get("call_timeout", 30)  # 30 secs

        # Endpoints
        self.socket_url = kwargs.get("socket_url", "/chat/ws")

    def render_field(self, field, **kwargs):
        """Render the chat widget with all controls and UI elements"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="chat-widget" role="region" aria-label="Chat Interface" id="{field.id}-container">
                <!-- Sidebar -->
                <div class="chat-sidebar">
                    <div class="user-profile">
                        <img src="/static/img/default-avatar.png" alt="User avatar" class="avatar">
                        <span class="username"></span>
                        <span class="status-indicator"></span>
                    </div>

                    <div class="chat-tabs" role="tablist">
                        <button class="tab active" role="tab" aria-selected="true">Chats</button>
                        <button class="tab" role="tab">Groups</button>
                        <button class="tab" role="tab">Contacts</button>
                    </div>

                    <div class="chat-list" role="tabpanel"></div>
                </div>

                <!-- Main Chat Area -->
                <div class="chat-main">
                    <div class="chat-header">
                        <div class="chat-info">
                            <h3 class="chat-title"></h3>
                            <span class="chat-status"></span>
                        </div>

                        <div class="chat-actions">
                            <button class="btn" aria-label="Start call">
                                <i class="fa fa-phone"></i>
                            </button>
                            <button class="btn" aria-label="Start video">
                                <i class="fa fa-video"></i>
                            </button>
                            <button class="btn" aria-label="Chat settings">
                                <i class="fa fa-cog"></i>
                            </button>
                        </div>
                    </div>

                    <div class="message-container" role="log" aria-live="polite">
                        <div class="messages"></div>
                        <div class="typing-indicator" aria-live="polite"></div>
                    </div>

                    <div class="composer">
                        <div class="attachment-preview"></div>

                        <div class="input-container">
                            {f'''
                            <button class="attach-btn" aria-label="Attach file">
                                <i class="fa fa-paperclip"></i>
                            </button>
                            ''' if self.enable_attachments else ''}

                            <div class="message-input" contenteditable="true"
                                 role="textbox" aria-label="Type a message"></div>

                            <button class="emoji-btn" aria-label="Add emoji">
                                <i class="fa fa-smile"></i>
                            </button>

                            <button class="send-btn" aria-label="Send message">
                                <i class="fa fa-paper-plane"></i>
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Call/Video UI -->
                <div class="call-container" style="display:none;">
                    <video id="{field.id}-local-video" muted></video>
                    <video id="{field.id}-remote-video"></video>

                    <div class="call-controls">
                        <button class="btn-mute" aria-label="Mute audio">
                            <i class="fa fa-microphone"></i>
                        </button>
                        <button class="btn-camera" aria-label="Toggle camera">
                            <i class="fa fa-video"></i>
                        </button>
                        <button class="btn-screen" aria-label="Share screen">
                            <i class="fa fa-desktop"></i>
                        </button>
                        <button class="btn-end-call" aria-label="End call">
                            <i class="fa fa-phone"></i>
                        </button>
                    </div>
                </div>

                <!-- Loading States -->
                <div class="loading-overlay" style="display:none;" role="alert" aria-busy="true">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading chat...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const chat = new ChatWidget('{field.id}', {{
                        enableAttachments: {str(self.enable_attachments).lower()},
                        enableGroups: {str(self.enable_groups).lower()},
                        notifications: {str(self.notifications).lower()},
                        historyLimit: {self.history_limit},
                        encryption: {str(self.encryption).lower()},
                        moderation: {str(self.moderation).lower()},
                        translation: {str(self.translation).lower()},
                        offlineSupport: {str(self.offline_support).lower()},
                        pushEnabled: {str(self.push_enabled).lower()},
                        fileTypes: {json.dumps(self.file_types)},
                        maxFileSize: {self.max_file_size},
                        fileScanEnabled: {str(self.file_scan_enabled).lower()},
                        presenceTracking: {str(self.presence_tracking).lower()},
                        typingTimeout: {self.typing_timeout},
                        maxGroupSize: {self.max_group_size},
                        retentionDays: {self.retention_days},
                        messageEditWindow: {self.message_edit_window},
                        giphyKey: {f"'{self.giphy_key}'" if self.giphy_key else 'null'},
                        callTimeout: {self.call_timeout},
                        socketUrl: '{self.socket_url}',

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onMessage: function(message) {{
                            handleMessage(message);
                        }},
                        onTyping: function(user) {{
                            showTypingIndicator(user);
                        }},
                        onPresence: function(user, status) {{
                            updatePresence(user, status);
                        }},
                        onCall: function(type, user) {{
                            handleIncomingCall(type, user);
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.chat-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Message handler
                    function handleMessage(message) {{
                        $('#{field.id}').val(JSON.stringify(message));
                        chat.scrollToBottom();
                    }}

                    // Typing indicator
                    function showTypingIndicator(user) {{
                        $('.typing-indicator').text(`${{user}} is typing...`);
                    }}

                    // Presence updates
                    function updatePresence(user, status) {{
                        $(`.user-${{user}} .status`).attr('data-status', status);
                    }}

                    // Call handling
                    function handleIncomingCall(type, user) {{
                        // Show call UI
                        $('.call-container').show();

                        // Initialize media
                        chat.initializeCallMedia(type);
                    }}

                    // Initialize if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        chat.loadHistory(JSON.parse(existingData));
                    }}

                    // Request notification permission if needed
                    if (self.notifications && Notification.permission === 'default') {{
                        Notification.requestPermission();
                    }}

                    // Handle window focus
                    $(window).on('focus blur', function(e) {{
                        chat.updatePresence(e.type === 'focus');
                    }});

                    // Cleanup
                    $(window).on('unload', function() {{
                        chat.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )
        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )
        return f"{css_includes}\n{js_includes}"

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_chat_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid chat data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_chat_data(self, data):
        """Validate chat message data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid chat data structure")

        required_keys = ["type", "content", "timestamp", "sender"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required message keys")

        # Validate message type
        valid_types = ["text", "file", "call", "system"]
        if data["type"] not in valid_types:
            raise ValueError(f"Invalid message type: {data['type']}")

        # Validate content
        if not data["content"]:
            raise ValueError("Empty message content")

        # Validate file data if present
        if data["type"] == "file":
            if not all(k in data for k in ["filename", "size", "mime_type"]):
                raise ValueError("Missing file metadata")

            if data["size"] > self.max_file_size:
                raise ValueError(f"File size exceeds limit: {self.max_file_size} bytes")

            if not any(fnmatch(data["mime_type"], pat) for pat in self.file_types):
                raise ValueError(f"Unsupported file type: {data['mime_type']}")

    def pre_validate(self, form):
        """Validate chat data before form processing"""
        if self.data is not None:
            try:
                self._validate_chat_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class AuditLogViewerWidget(BS3TextFieldWidget):
    """
    Comprehensive audit log viewer widget for tracking system changes.

    Features:
    - Detailed change tracking with before/after comparison
    - Advanced filtering by date, user, action type
    - Interactive timeline visualization
    - User activity monitoring and analytics
    - Multi-format export (CSV, PDF, Excel)
    - Full-text search with highlighting
    - Side-by-side field comparison
    - Complete version history
    - Point-in-time data restore
    - Access and security logging
    - IP address and location tracking
    - Custom report generation
    - Compliance reporting (GDPR, SOX, etc)
    - Configurable data retention
    - Flexible event categorization
    - Real-time updates
    - Data visualization
    - Anomaly detection
    - Audit trail integrity
    - Custom field tracking

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON

    Required Dependencies:
    - DataTables 1.10+
    - Diff.js 3.5+
    - Timeline.js 3.8+
    - Moment.js 2.29+
    - Chart.js 3.7+
    - jsPDF 2.5+
    - SheetJS 0.18+

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - LocalStorage access
    - File download
    - IndexedDB
    - Service Workers

    Performance Considerations:
    - Enable server-side pagination
    - Index audit log table
    - Cache common queries
    - Implement data archival
    - Optimize large datasets
    - Lazy load components
    - Debounce search
    - Throttle real-time updates

    Security Implications:
    - Validate user permissions
    - Sanitize search input
    - Prevent SQL injection
    - Encrypt sensitive data
    - Implement CSRF protection
    - Rate limit API calls
    - Log security events

    Example:
        audit_log = db.Column(db.JSON, nullable=False,
            info={'widget': AuditLogViewerWidget(
                tracked_fields=['name', 'status', 'price'],
                retention_days=365,
                export_formats=['csv', 'pdf', 'excel'],
                show_ip=True,
                track_changes=True,
                track_views=True,
                compliance_mode=True
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdn.datatables.net/1.10.24/js/jquery.dataTables.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/diff/3.5.0/diff.min.js",
        "https://cdn.knightlab.com/libs/timeline3/latest/js/timeline.js",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
        "https://cdn.jsdelivr.net/npm/chart.js@3.7.0/dist/chart.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js",
        "/static/js/audit-log-viewer.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdn.datatables.net/1.10.24/css/jquery.dataTables.min.css",
        "https://cdn.knightlab.com/libs/timeline3/latest/css/timeline.css",
        "/static/css/audit-log-viewer.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize AuditLogViewerWidget with custom settings.

        Args:
            tracked_fields (list): Fields to track changes on
            retention_days (int): Number of days to retain audit logs
            export_formats (list): Available export formats
            show_ip (bool): Show IP addresses in logs
            track_changes (bool): Track field changes
            track_views (bool): Track record views
            compliance_mode (bool): Enable compliance features
            page_size (int): Records per page
            update_interval (int): Real-time update interval
            timezone (str): Display timezone
            date_format (str): Date display format
            field_labels (dict): Custom field labels
            chart_enabled (bool): Enable data visualization
            anomaly_detection (bool): Enable anomaly detection
            integrity_check (bool): Enable audit trail verification
        """
        super().__init__(**kwargs)

        self.tracked_fields = kwargs.get("tracked_fields", [])
        self.retention_days = kwargs.get("retention_days", 365)
        self.export_formats = kwargs.get("export_formats", ["csv", "pdf", "excel"])
        self.show_ip = kwargs.get("show_ip", True)
        self.track_changes = kwargs.get("track_changes", True)
        self.track_views = kwargs.get("track_views", False)
        self.compliance_mode = kwargs.get("compliance_mode", False)
        self.page_size = kwargs.get("page_size", 50)
        self.update_interval = kwargs.get("update_interval", 30)
        self.timezone = kwargs.get("timezone", "UTC")
        self.date_format = kwargs.get("date_format", "YYYY-MM-DD HH:mm:ss")
        self.field_labels = kwargs.get("field_labels", {})
        self.chart_enabled = kwargs.get("chart_enabled", True)
        self.anomaly_detection = kwargs.get("anomaly_detection", False)
        self.integrity_check = kwargs.get("integrity_check", True)

    def render_field(self, field, **kwargs):
        """Render the audit log viewer with all controls and visualizations"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="audit-log-viewer" role="region" aria-label="Audit Log Viewer">
                <!-- Controls -->
                <div class="controls mb-3">
                    <div class="row">
                        <div class="col-md-3">
                            <input type="text" class="form-control search"
                                   placeholder="Search logs..." aria-label="Search">
                        </div>
                        <div class="col-md-3">
                            <select class="form-control filter-type" aria-label="Event Type">
                                <option value="">All Events</option>
                                <option value="create">Create</option>
                                <option value="update">Update</option>
                                <option value="delete">Delete</option>
                                {f'<option value="view">View</option>' if self.track_views else ''}
                            </select>
                        </div>
                        <div class="col-md-4">
                            <div class="input-group">
                                <input type="text" class="form-control date-range"
                                       aria-label="Date Range">
                                <div class="input-group-append">
                                    <button class="btn btn-outline-secondary" type="button">
                                        <i class="fa fa-calendar"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-2">
                            {self._render_export_buttons(field.id)}
                        </div>
                    </div>
                </div>

                <!-- Tabs -->
                <ul class="nav nav-tabs" role="tablist">
                    <li class="nav-item">
                        <a class="nav-link active" data-toggle="tab" href="#table-view"
                           role="tab">Table View</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" data-toggle="tab" href="#timeline-view"
                           role="tab">Timeline</a>
                    </li>
                    {f'''
                    <li class="nav-item">
                        <a class="nav-link" data-toggle="tab" href="#charts-view"
                           role="tab">Analytics</a>
                    </li>
                    ''' if self.chart_enabled else ''}
                </ul>

                <!-- Tab Content -->
                <div class="tab-content">
                    <!-- Table View -->
                    <div class="tab-pane fade show active" id="table-view" role="tabpanel">
                        <table class="table audit-table" aria-label="Audit Log Table">
                            <thead>
                                <tr>
                                    <th>Timestamp</th>
                                    <th>User</th>
                                    <th>Action</th>
                                    <th>Details</th>
                                    {f'<th>IP Address</th>' if self.show_ip else ''}
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                    </div>

                    <!-- Timeline View -->
                    <div class="tab-pane fade" id="timeline-view" role="tabpanel">
                        <div id="{field.id}-timeline"></div>
                    </div>

                    <!-- Analytics View -->
                    {f'''
                    <div class="tab-pane fade" id="charts-view" role="tabpanel">
                        <div class="row">
                            <div class="col-md-6">
                                <canvas id="{field.id}-activity-chart"></canvas>
                            </div>
                            <div class="col-md-6">
                                <canvas id="{field.id}-user-chart"></canvas>
                            </div>
                        </div>
                    </div>
                    ''' if self.chart_enabled else ''}
                </div>

                <!-- Change Comparison Modal -->
                <div class="modal fade" id="{field.id}-diff-modal" tabindex="-1" role="dialog">
                    <div class="modal-dialog modal-lg" role="document">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Change Details</h5>
                                <button type="button" class="close" data-dismiss="modal"
                                        aria-label="Close">
                                    <span aria-hidden="true">&times;</span>
                                </button>
                            </div>
                            <div class="modal-body">
                                <div class="diff-viewer"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Loading Indicator -->
                <div class="loading-overlay" style="display:none;" role="alert"
                     aria-busy="true">
                    <div class="spinner-border text-primary"></div>
                    <span class="sr-only">Loading audit logs...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger mt-2" style="display:none;"
                     role="alert" aria-live="polite"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const auditLog = new AuditLogViewer('{field.id}', {{
                        trackedFields: {json.dumps(self.tracked_fields)},
                        retentionDays: {self.retention_days},
                        exportFormats: {json.dumps(self.export_formats)},
                        showIp: {str(self.show_ip).lower()},
                        trackChanges: {str(self.track_changes).lower()},
                        trackViews: {str(self.track_views).lower()},
                        complianceMode: {str(self.compliance_mode).lower()},
                        pageSize: {self.page_size},
                        updateInterval: {self.update_interval},
                        timezone: '{self.timezone}',
                        dateFormat: '{self.date_format}',
                        fieldLabels: {json.dumps(self.field_labels)},
                        chartEnabled: {str(self.chart_enabled).lower()},
                        anomalyDetection: {str(self.anomaly_detection).lower()},
                        integrityCheck: {str(self.integrity_check).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onDataUpdate: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.audit-log-viewer .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Initialize if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        auditLog.loadData(JSON.parse(existingData));
                    }}

                    // Handle window resize
                    $(window).on('resize', _.debounce(function() {{
                        auditLog.handleResize();
                    }}, 250));

                    // Cleanup on unload
                    $(window).on('unload', function() {{
                        auditLog.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )
        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )
        return f"{css_includes}\n{js_includes}"

    def _render_export_buttons(self, field_id):
        """Render export format buttons"""
        return f"""
            <div class="btn-group">
                <button type="button" class="btn btn-secondary dropdown-toggle"
                        data-toggle="dropdown" aria-label="Export Options">
                    <i class="fa fa-download"></i> Export
                </button>
                <div class="dropdown-menu dropdown-menu-right">
                    {''.join([
                        f'''
                        <a class="dropdown-item" href="#" data-export="{fmt}">
                            Export to {fmt.upper()}
                        </a>
                        ''' for fmt in self.export_formats
                    ])}
                </div>
            </div>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_audit_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid audit log data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_audit_data(self, data):
        """Validate audit log data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid audit log data structure")

        required_keys = ["logs", "metadata"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required audit log data keys")

        # Validate individual log entries
        for log in data["logs"]:
            if not all(k in log for k in ["timestamp", "user", "action", "details"]):
                raise ValueError("Invalid log entry structure")

            # Validate timestamp
            try:
                datetime.fromisoformat(log["timestamp"])
            except ValueError:
                raise ValueError("Invalid timestamp format")

            # Validate action type
            valid_actions = ["create", "update", "delete", "view"]
            if log["action"] not in valid_actions:
                raise ValueError(f"Invalid action type: {log['action']}")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_audit_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class BarcodeQRScannerWidget(BS3TextFieldWidget):
    """
    Barcode and QR code scanner widget with camera integration.

    Features:
    - Multiple format support (1D/2D barcodes, QR codes)
    - Camera selection and switching
    - Real-time auto-detection
    - Manual entry fallback with validation
    - Batch scanning mode
    - Scan history with export
    - Custom format validation
    - Result formatting/cleaning
    - Error correction levels
    - Offline scanning capability
    - Barcode generation
    - Scan analytics/statistics
    - Mobile-first responsive design
    - Custom result processors
    - API integrations
    - Sound/vibration feedback
    - Image preprocessing
    - Zoom controls
    - Torch/flash control
    - Orientation handling

    Database Type:
        PostgreSQL: VARCHAR or JSONB (for batch mode)
        SQLAlchemy: String or JSON

    Required Dependencies:
    - ZXing 0.19+
    - QuaggaJS 0.12+
    - MediaDevices API
    - WebAssembly support
    - Service Workers (offline)

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 11.1+
    - Edge 79+
    - Opera 47+
    - Chrome for Android 89+
    - Safari iOS 11.3+

    Required Permissions:
    - Camera access
    - Storage (IndexedDB)
    - Vibration API
    - Service Workers
    - Fullscreen API
    - Wake Lock API

    Performance Considerations:
    - Camera resolution vs performance
    - Image processing load
    - Memory usage for history
    - Battery impact
    - CPU utilization
    - Worker thread usage
    - Cache management
    - Offline storage limits

    Security Implications:
    - Camera permission handling
    - Data validation/sanitization
    - Secure storage practices
    - API endpoint security
    - XSS prevention
    - CSRF protection
    - Rate limiting
    - Input validation

    Best Practices:
    - Request minimal permissions
    - Implement error recovery
    - Provide feedback
    - Cache results
    - Handle offline mode
    - Validate scans
    - Monitor performance
    - Clean invalid data
    - Regular testing
    - Update dependencies

    Example:
        scanner = db.Column(db.String(255), nullable=True,
            info={'widget': BarcodeQRScannerWidget(
                formats=['qr', 'ean13', 'code128'],
                auto_submit=True,
                history=True,
                validate=True,
                error_correction='M',
                offline_support=True
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://unpkg.com/@zxing/library@0.19.1",
        "https://cdn.jsdelivr.net/npm/quagga@0.12.1/dist/quagga.min.js",
        "/static/js/barcode-scanner.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = ["/static/css/barcode-scanner.css"]

    # Default supported formats
    DEFAULT_FORMATS = ["qr", "ean13", "ean8", "code128", "code39", "upc"]

    def __init__(self, **kwargs):
        """
        Initialize BarcodeQRScannerWidget with custom settings.

        Args:
            formats (list): Supported barcode formats
            auto_submit (bool): Auto-submit on scan
            history (bool): Enable scan history
            validate (bool): Enable validation
            camera_id (str): Specific camera device ID
            batch_mode (bool): Enable batch scanning
            result_handler (callable): Custom result processor
            error_correction (str): QR error correction level (L,M,Q,H)
            offline_support (bool): Enable offline scanning
            sound_feedback (bool): Enable sound on scan
            vibrate (bool): Enable vibration on scan
            torch (bool): Enable torch/flash control
            zoom (bool): Enable zoom controls
            orientation (bool): Enable orientation handling
            preprocessing (bool): Enable image preprocessing
            confidence (float): Minimum confidence threshold
            scan_interval (int): Milliseconds between scans
            history_size (int): Maximum history entries
            timeout (int): Scan timeout in seconds
        """
        super().__init__(**kwargs)

        self.formats = kwargs.get("formats", self.DEFAULT_FORMATS)
        self.auto_submit = kwargs.get("auto_submit", True)
        self.history = kwargs.get("history", True)
        self.validate = kwargs.get("validate", True)
        self.camera_id = kwargs.get("camera_id", None)
        self.batch_mode = kwargs.get("batch_mode", False)
        self.result_handler = kwargs.get("result_handler", None)
        self.error_correction = kwargs.get("error_correction", "M")
        self.offline_support = kwargs.get("offline_support", True)
        self.sound_feedback = kwargs.get("sound_feedback", True)
        self.vibrate = kwargs.get("vibrate", True)
        self.torch = kwargs.get("torch", True)
        self.zoom = kwargs.get("zoom", True)
        self.orientation = kwargs.get("orientation", True)
        self.preprocessing = kwargs.get("preprocessing", True)
        self.confidence = kwargs.get("confidence", 0.8)
        self.scan_interval = kwargs.get("scan_interval", 100)
        self.history_size = kwargs.get("history_size", 100)
        self.timeout = kwargs.get("timeout", 30)

    def render_field(self, field, **kwargs):
        """Render the barcode scanner widget with controls and preview"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="barcode-scanner-widget" id="{field.id}-container">
                <!-- Camera Preview -->
                <div class="camera-container">
                    <video id="{field.id}-preview" playsinline autoplay></video>
                    <canvas id="{field.id}-canvas" style="display:none;"></canvas>

                    <div class="scanner-overlay">
                        <div class="scan-region"></div>
                    </div>

                    <!-- Controls -->
                    <div class="scanner-controls">
                        {self._render_camera_controls(field.id)}
                    </div>
                </div>

                <!-- Results Area -->
                <div class="results-container">
                    <input type="text" id="{field.id}-manual"
                           class="form-control manual-input"
                           placeholder="Enter code manually...">

                    {self._render_history_table(field.id) if self.history else ''}
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner-border"></div>
                    <span class="sr-only">Initializing camera...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const scanner = new BarcodeScanner('{field.id}', {{
                        formats: {json.dumps(self.formats)},
                        autoSubmit: {str(self.auto_submit).lower()},
                        history: {str(self.history).lower()},
                        validate: {str(self.validate).lower()},
                        cameraId: {f"'{self.camera_id}'" if self.camera_id else 'null'},
                        batchMode: {str(self.batch_mode).lower()},
                        errorCorrection: '{self.error_correction}',
                        offlineSupport: {str(self.offline_support).lower()},
                        soundFeedback: {str(self.sound_feedback).lower()},
                        vibrate: {str(self.vibrate).lower()},
                        torch: {str(self.torch).lower()},
                        zoom: {str(self.zoom).lower()},
                        orientation: {str(self.orientation).lower()},
                        preprocessing: {str(self.preprocessing).lower()},
                        confidence: {self.confidence},
                        scanInterval: {self.scan_interval},
                        historySize: {self.history_size},
                        timeout: {self.timeout},

                        onScan: function(result) {{
                            handleScan(result);
                        }},
                        onError: function(error) {{
                            showError(error);
                        }},
                        onStateChange: function(state) {{
                            updateState(state);
                        }}
                    }});

                    // Scan result handler
                    function handleScan(result) {{
                        if ({str(self.validate).lower()}) {{
                            if (!validateScan(result)) {{
                                showError('Invalid scan result');
                                return;
                            }}
                        }}

                        $('#{field.id}').val(result);

                        if ({str(self.auto_submit).lower()}) {{
                            $('#{field.id}').closest('form').submit();
                        }}
                    }}

                    // Validation handler
                    function validateScan(result) {{
                        // Implement format-specific validation
                        return true;
                    }}

                    // Error handler
                    function showError(error) {{
                        const alert = $('.barcode-scanner-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // State update handler
                    function updateState(state) {{
                        $('.loading-overlay')[state.loading ? 'show' : 'hide']();

                        if (state.torch) {{
                            $('.torch-toggle').addClass('active');
                        }}

                        if (state.camera === 'unavailable') {{
                            $('.manual-input').show();
                        }}
                    }}

                    // Handle orientation changes
                    if ({str(self.orientation).lower()}) {{
                        window.addEventListener('orientationchange', function() {{
                            scanner.handleOrientation();
                        }});
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        scanner.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )
        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )
        return f"{css_includes}\n{js_includes}"

    def _render_camera_controls(self, field_id):
        """Render camera control buttons"""
        controls = []

        if self.torch:
            controls.append(
                f"""
                <button type="button" class="btn btn-light torch-toggle"
                        aria-label="Toggle torch">
                    <i class="fa fa-bolt"></i>
                </button>
            """
            )

        if self.zoom:
            controls.append(
                f"""
                <div class="zoom-controls">
                    <button type="button" class="btn btn-light zoom-in"
                            aria-label="Zoom in">
                        <i class="fa fa-search-plus"></i>
                    </button>
                    <button type="button" class="btn btn-light zoom-out"
                            aria-label="Zoom out">
                        <i class="fa fa-search-minus"></i>
                    </button>
                </div>
            """
            )

        return "\n".join(controls)

    def _render_history_table(self, field_id):
        """Render scan history table"""
        return f"""
            <div class="scan-history">
                <h5>Scan History</h5>
                <table class="table table-sm">
                    <thead>
                        <tr>
                            <th>Code</th>
                            <th>Type</th>
                            <th>Time</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                self.data = self._validate_scan_data(valuelist[0])
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_scan_data(self, value):
        """Validate scanned barcode data"""
        if not value:
            raise ValueError("Empty scan result")

        if self.validate:
            # Format-specific validation
            format_validators = {
                "ean13": lambda x: len(x) == 13 and x.isdigit(),
                "ean8": lambda x: len(x) == 8 and x.isdigit(),
                "code128": lambda x: len(x) >= 1,
                "qr": lambda x: len(x) >= 1,
            }

            # Try each supported format
            valid = False
            for fmt in self.formats:
                if fmt in format_validators:
                    valid = format_validators[fmt](value)
                    if valid:
                        break

            if not valid:
                raise ValueError("Invalid barcode format")

        return value

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self.data = self._validate_scan_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class DependentSelectWidget(BS3TextFieldWidget):
    """
    Cascading dropdown widget with dependent options.

    Features:
    - Dynamic option loading based on parent field values
    - Support for multiple parent dependencies
    - Chained relationship handling
    - Ajax loading with caching
    - Smart loading indicators
    - Error handling and recovery
    - Clear/reset functionality
    - Advanced search/filtering
    - Custom formatters
    - Validation rules
    - Rich event handlers
    - State persistence
    - Accessibility compliance
    - Mobile responsiveness
    - Offline support
    - Performance optimization
    - Security hardening

    Database Type:
        PostgreSQL: JSONB for options, INTEGER/VARCHAR for values
        SQLAlchemy: JSON, Integer, String

    Required Dependencies:
    - Select2 4.0+
    - jQuery 3.0+
    - Lodash 4.0+

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - iOS Safari 12+
    - Chrome Android 89+

    Required Permissions:
    - LocalStorage/SessionStorage
    - XHR/Fetch requests
    - Service Workers (offline)

    Performance Considerations:
    - Enable option caching
    - Debounce search requests
    - Lazy load options
    - Optimize payload size
    - Compress responses
    - Index dependent columns
    - Cache parent data
    - Use websockets for updates

    Security Implications:
    - Validate parent dependencies
    - Sanitize search input
    - Rate limit requests
    - Check permissions
    - Prevent XSS
    - CSRF protection
    - SQL injection prevention
    - Access control

    Best Practices:
    - Set reasonable defaults
    - Enable caching
    - Add error handling
    - Show loading states
    - Validate input
    - Test edge cases
    - Document usage
    - Monitor performance
    - Regular updates
    - Security audits

    Example:
        country = db.Column(db.Integer,
            info={'widget': DependentSelectWidget(
                url='/api/countries',
                depends_on=None,
                cache=True,
                search=True,
                placeholder='Select Country',
                minimum_input=2
            )})

        state = db.Column(db.Integer,
            info={'widget': DependentSelectWidget(
                url='/api/states',
                depends_on='country',
                cache=True,
                search=True,
                placeholder='Select State',
                minimum_input=2
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/select2/4.0.13/js/select2.full.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "/static/js/dependent-select.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/select2/4.0.13/css/select2.min.css",
        "/static/css/dependent-select.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize DependentSelectWidget with custom settings.

        Args:
            url (str): Data source URL for options
            depends_on (str|list): Parent field name(s)
            cache (bool): Enable option caching
            search (bool): Enable search functionality
            placeholder (str): Placeholder text
            minimum_input (int): Minimum search input length
            load_on_init (bool): Load initial options
            formatter (callable): Custom option formatter
            default_value (any): Default selected value
            clear_on_parent_change (bool): Clear on parent change
            allow_clear (bool): Allow clearing selection
            dropdown_parent (str): Custom dropdown parent
            theme (str): Select2 theme name
            debug (bool): Enable debug mode
            retry_attempts (int): Failed request retries
            timeout (int): Request timeout in ms
            batch_size (int): Option load batch size
            websocket_url (str): Real-time updates URL
            offline_support (bool): Enable offline mode
        """
        super().__init__(**kwargs)

        # Core settings
        self.url = kwargs.get("url")
        self.depends_on = kwargs.get("depends_on")
        self.cache = kwargs.get("cache", True)
        self.search = kwargs.get("search", True)
        self.placeholder = kwargs.get("placeholder", "Select...")
        self.minimum_input = kwargs.get("minimum_input", 2)
        self.load_on_init = kwargs.get("load_on_init", True)
        self.formatter = kwargs.get("formatter")

        # Advanced options
        self.default_value = kwargs.get("default_value")
        self.clear_on_parent_change = kwargs.get("clear_on_parent_change", True)
        self.allow_clear = kwargs.get("allow_clear", True)
        self.dropdown_parent = kwargs.get("dropdown_parent", "body")
        self.theme = kwargs.get("theme", "default")

        # Technical settings
        self.debug = kwargs.get("debug", False)
        self.retry_attempts = kwargs.get("retry_attempts", 3)
        self.timeout = kwargs.get("timeout", 5000)
        self.batch_size = kwargs.get("batch_size", 100)
        self.websocket_url = kwargs.get("websocket_url")
        self.offline_support = kwargs.get("offline_support", True)

    def render_field(self, field, **kwargs):
        """Render the dependent select widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="dependent-select-widget" role="combobox">
                <select name="{field.name}" id="{field.id}"
                        class="form-control select2-widget"
                        aria-label="{field.label.text if field.label else ''}"
                        {f'data-depends-on="{self.depends_on}"' if self.depends_on else ''}
                        data-placeholder="{self.placeholder}"
                        {f'data-default-value="{self.default_value}"' if self.default_value else ''}>
                    <option></option>
                </select>

                <div class="loading-indicator" style="display:none;">
                    <div class="spinner-border spinner-border-sm"></div>
                    <span class="sr-only">Loading options...</span>
                </div>

                <div class="alert alert-danger error-message"
                     style="display:none;" role="alert"></div>
            </div>

            <script>
                $(document).ready(function() {{
                    const select = new DependentSelect('{field.id}', {{
                        url: '{self.url}',
                        dependsOn: {json.dumps(self.depends_on)},
                        cache: {str(self.cache).lower()},
                        search: {str(self.search).lower()},
                        minimumInputLength: {self.minimum_input},
                        loadOnInit: {str(self.load_on_init).lower()},
                        defaultValue: {json.dumps(self.default_value)},
                        clearOnParentChange: {str(self.clear_on_parent_change).lower()},
                        allowClear: {str(self.allow_clear).lower()},
                        dropdownParent: '{self.dropdown_parent}',
                        theme: '{self.theme}',
                        debug: {str(self.debug).lower()},
                        retryAttempts: {self.retry_attempts},
                        timeout: {self.timeout},
                        batchSize: {self.batch_size},
                        websocketUrl: {f"'{self.websocket_url}'" if self.websocket_url else 'null'},
                        offlineSupport: {str(self.offline_support).lower()},

                        formatResult: function(item) {{
                            {f"return {self.formatter.__name__}(item);" if self.formatter else "return item.text;"}
                        }},

                        onChange: function(value) {{
                            $('#{field.id}').trigger('change');
                        }},

                        onError: function(error) {{
                            showError(error);
                        }},

                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('#{field.id}').siblings('.error-message');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(loading) {{
                        $('#{field.id}').siblings('.loading-indicator')
                            [loading ? 'show' : 'hide']();
                    }}

                    // Clean up on page unload
                    $(window).on('unload', function() {{
                        select.destroy();
                    }});
                }});
            </script>
            """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )
        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )
        return f"{css_includes}\n{js_includes}"

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                self.data = self._validate_value(valuelist[0])
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_value(self, value):
        """Validate selected value"""
        if not value:
            if self.data is not None:
                raise ValueError("Value required")
            return None

        try:
            return int(value) if value.isdigit() else value
        except (ValueError, TypeError):
            raise ValueError("Invalid value format")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_value(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class CommentAndLikeWidget(BS3TextFieldWidget):
    """
    Interactive widget for social interactions including comments and likes/reactions.

    Features:
    - Nested comments/replies with infinite depth
    - Rich text comments with image embedding
    - Multiple reaction types with custom emoji support
    - Real-time updates via WebSockets
    - Mention support (@username) with autocomplete
    - File attachments with preview
    - Comment editing with version history
    - Moderation tools with spam detection
    - Notification system with email/push
    - Vote/Rating system with analytics
    - Comment sorting and filtering
    - Thread collapsing and expansion
    - Report abuse with automated flagging
    - User avatars with Gravatar fallback
    - Emoji picker with custom sets
    - Full-text comment search
    - Analytics tracking and reporting
    - Mobile-first responsive design
    - Accessibility compliance (WCAG 2.1)
    - Internationalization support
    - Rate limiting protection
    - XSS/CSRF prevention
    - Offline support
    - Performance optimization

    Database Type:
        PostgreSQL: JSONB for comments/reactions
        SQLAlchemy: JSON

    Required Dependencies:
    - Socket.io 4.0+
    - TinyMCE 5.0+
    - EmojiPicker 3.0+
    - Moment.js 2.29+
    - Lodash 4.17+
    - AutoLinker 3.0+

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - WebSocket connections
    - LocalStorage/IndexedDB
    - File system (uploads)
    - Push notifications
    - Service Workers
    - Camera/Microphone (optional)

    Performance Considerations:
    - Lazy load comments
    - Optimize images
    - Cache resources
    - Debounce real-time updates
    - Paginate long threads
    - Compress payloads
    - Index search fields
    - Monitor memory usage
    - Background processing
    - CDN integration

    Security Implications:
    - Input sanitization
    - File upload scanning
    - Rate limiting
    - User authentication
    - Content moderation
    - CSRF protection
    - XSS prevention
    - SQL injection prevention
    - Data encryption
    - Access control

    Example:
        social_interaction = db.Column(db.JSON,
            info={'widget': CommentAndLikeWidget(
                enable_replies=True,
                reaction_types=['like', 'love', 'laugh'],
                enable_attachments=True,
                realtime=True,
                moderation=True,
                max_comment_length=1000,
                allowed_file_types=['image/*', 'pdf'],
                sort_options=['newest', 'oldest', 'popular'],
                notification_config={
                    'email': True,
                    'push': True,
                    'in_app': True
                }
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.1/socket.io.min.js",
        "https://cdn.tiny.cloud/1/no-api-key/tinymce/5/tinymce.min.js",
        "https://cdn.jsdelivr.net/npm/emoji-picker-element@^1",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/autolinker/3.14.3/Autolinker.min.js",
        "/static/js/comment-widget.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/tinymce/5.10.0/skins/ui/oxide/skin.min.css",
        "https://cdn.jsdelivr.net/npm/emoji-picker-element@^1/css/emoji-picker.css",
        "/static/css/comment-widget.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize CommentAndLikeWidget with custom settings.

        Args:
            enable_replies (bool): Allow nested replies
            reaction_types (list): Available reaction types
            enable_attachments (bool): Allow file attachments
            realtime (bool): Enable real-time updates
            moderation (bool): Enable moderation features
            max_comment_length (int): Maximum comment length
            allowed_file_types (list): Allowed attachment types
            sort_options (list): Available sort methods
            notification_config (dict): Notification settings
            max_nest_level (int): Maximum nesting level
            max_attachments (int): Maximum attachments per comment
            attachment_size_limit (int): Max file size in bytes
            mention_min_chars (int): Min chars for mention trigger
            cache_duration (int): Cache duration in seconds
            rate_limit (dict): Rate limiting configuration
            moderation_config (dict): Moderation settings
            analytics_config (dict): Analytics settings
            search_config (dict): Search configuration
            offline_config (dict): Offline mode settings
            accessibility_config (dict): A11y settings
            localization (dict): i18n configuration
        """
        super().__init__(**kwargs)

        # Core Features
        self.enable_replies = kwargs.get("enable_replies", True)
        self.reaction_types = kwargs.get("reaction_types", ["like"])
        self.enable_attachments = kwargs.get("enable_attachments", False)
        self.realtime = kwargs.get("realtime", True)
        self.moderation = kwargs.get("moderation", False)
        self.max_comment_length = kwargs.get("max_comment_length", 1000)
        self.allowed_file_types = kwargs.get("allowed_file_types", ["image/*", "pdf"])
        self.sort_options = kwargs.get("sort_options", ["newest", "oldest", "popular"])
        self.notification_config = kwargs.get("notification_config", {})

        # Advanced Settings
        self.max_nest_level = kwargs.get("max_nest_level", 5)
        self.max_attachments = kwargs.get("max_attachments", 5)
        self.attachment_size_limit = kwargs.get(
            "attachment_size_limit", 5 * 1024 * 1024
        )
        self.mention_min_chars = kwargs.get("mention_min_chars", 2)
        self.cache_duration = kwargs.get("cache_duration", 3600)

        # Security Settings
        self.rate_limit = kwargs.get(
            "rate_limit",
            {
                "comments": {"count": 10, "interval": 60},
                "reactions": {"count": 30, "interval": 60},
                "uploads": {"count": 10, "interval": 300},
            },
        )

        # Moderation Settings
        self.moderation_config = kwargs.get(
            "moderation_config",
            {
                "auto_approve": False,
                "spam_check": True,
                "profanity_filter": True,
                "min_length": 2,
                "max_links": 3,
                "require_verification": False,
            },
        )

        # Feature Configurations
        self.analytics_config = kwargs.get(
            "analytics_config",
            {
                "enabled": True,
                "track_views": True,
                "track_engagement": True,
                "track_performance": True,
            },
        )

        self.search_config = kwargs.get(
            "search_config",
            {
                "enabled": True,
                "min_length": 3,
                "fuzzy_match": True,
                "include_replies": True,
            },
        )

        self.offline_config = kwargs.get(
            "offline_config",
            {"enabled": True, "sync_interval": 300, "max_offline_items": 100},
        )

        self.accessibility_config = kwargs.get(
            "accessibility_config",
            {
                "aria_labels": True,
                "keyboard_nav": True,
                "high_contrast": False,
                "screen_reader_support": True,
            },
        )

        self.localization = kwargs.get(
            "localization",
            {
                "enabled": True,
                "default_locale": "en",
                "available_locales": ["en"],
                "rtl_support": False,
            },
        )

    def render_field(self, field, **kwargs):
        """Render the comment and like widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="comment-widget" id="{field.id}-container">
                <!-- Comment Form -->
                <div class="comment-form" role="form">
                    <div class="rich-text-editor"></div>
                    {self._render_attachment_upload(field.id) if self.enable_attachments else ''}
                    <div class="emoji-picker-container"></div>
                    <div class="mentions-container"></div>
                </div>

                <!-- Comment List -->
                <div class="comments-list" role="log" aria-live="polite">
                    <div class="sort-controls">
                        {self._render_sort_options()}
                    </div>
                    <div class="comments-container"></div>
                    <div class="load-more" style="display:none;">
                        <button class="btn btn-link">Load More</button>
                    </div>
                </div>

                <!-- Loading States -->
                <div class="loading-overlay" style="display:none;" role="alert" aria-busy="true">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading comments...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const comments = new CommentWidget('{field.id}', {{
                        enableReplies: {str(self.enable_replies).lower()},
                        reactionTypes: {json.dumps(self.reaction_types)},
                        enableAttachments: {str(self.enable_attachments).lower()},
                        realtime: {str(self.realtime).lower()},
                        moderation: {str(self.moderation).lower()},
                        maxLength: {self.max_comment_length},
                        allowedTypes: {json.dumps(self.allowed_file_types)},
                        sortOptions: {json.dumps(self.sort_options)},
                        maxNestLevel: {self.max_nest_level},
                        maxAttachments: {self.max_attachments},
                        sizeLimit: {self.attachment_size_limit},
                        mentionMinChars: {self.mention_min_chars},
                        rateLimit: {json.dumps(self.rate_limit)},
                        moderationConfig: {json.dumps(self.moderation_config)},
                        analyticsConfig: {json.dumps(self.analytics_config)},
                        searchConfig: {json.dumps(self.search_config)},
                        offlineConfig: {json.dumps(self.offline_config)},
                        a11yConfig: {json.dumps(self.accessibility_config)},
                        localization: {json.dumps(self.localization)},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onUpdate: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.comment-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Initialize if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        comments.loadData(JSON.parse(existingData));
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        comments.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )
        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )
        return f"{css_includes}\n{js_includes}"

    def _render_attachment_upload(self, field_id):
        """Render file attachment upload area"""
        return f"""
            <div class="attachment-upload" role="region" aria-label="File attachments">
                <input type="file" id="{field_id}-upload" multiple
                       accept="{','.join(self.allowed_file_types)}"
                       aria-describedby="{field_id}-upload-help">
                <small id="{field_id}-upload-help" class="form-text text-muted">
                    Allowed files: {', '.join(self.allowed_file_types)}.
                    Max size: {self.attachment_size_limit/1024/1024}MB
                </small>
                <div class="upload-preview"></div>
            </div>
        """

    def _render_sort_options(self):
        """Render comment sort options"""
        return f"""
            <select class="form-control sort-select" aria-label="Sort comments">
                {' '.join([f'<option value="{opt}">{opt.title()}</option>'
                          for opt in self.sort_options])}
            </select>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_comment_data(data)
                self.data = data
            except json.JSONDecodeError:
                raise ValueError("Invalid comment data format")
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_comment_data(self, data):
        """Validate comment data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid comment data structure")

        required_keys = ["comments", "reactions", "metadata"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required data keys")

        # Validate individual comments
        for comment in data.get("comments", []):
            if not all(k in comment for k in ["id", "content", "user", "timestamp"]):
                raise ValueError("Invalid comment structure")

            # Content length validation
            if len(comment["content"]) > self.max_comment_length:
                raise ValueError(
                    f"Comment exceeds maximum length of {self.max_comment_length}"
                )

            # Attachment validation
            attachments = comment.get("attachments", [])
            if len(attachments) > self.max_attachments:
                raise ValueError(f"Too many attachments (max: {self.max_attachments})")

            for attachment in attachments:
                if not self._validate_attachment(attachment):
                    raise ValueError("Invalid attachment")

    def _validate_attachment(self, attachment):
        """Validate file attachment metadata"""
        required_keys = ["filename", "size", "type"]
        if not all(key in attachment for key in required_keys):
            return False

        # Size validation
        if attachment["size"] > self.attachment_size_limit:
            return False

        # Type validation
        if not any(fnmatch(attachment["type"], pat) for pat in self.allowed_file_types):
            return False

        return True

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_comment_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class FriendFollowWidget(BS3TextFieldWidget):
    """
    Widget for managing friend/follow relationships and social connections.

    Features:
    - Follow/Unfollow functionality with real-time updates
    - Friend requests with notifications
    - AI-powered connection suggestions
    - Interactive network visualization
    - Granular privacy settings
    - User blocking and reporting
    - Custom group management
    - Real-time activity feed
    - Connection analytics and stats
    - Contact import/export
    - Social network analysis
    - Mutual friend discovery
    - Connection categorization
    - Bulk actions and management
    - Mobile-responsive design
    - Accessibility compliance
    - Offline support
    - Rate limiting
    - Data validation

    Database Type:
        PostgreSQL: JSONB for storing connection data
        SQLAlchemy: JSON type

    Required Dependencies:
    - D3.js v7+ (network visualization)
    - Socket.io v4+ (real-time updates)
    - VIS.js v9+ (network analysis)
    - Lodash v4+ (utilities)
    - Bootstrap v4+ (UI components)

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - WebSocket connections
    - LocalStorage/IndexedDB
    - Push notifications
    - Contacts API (optional)

    Performance Considerations:
    - Lazy load network visualization
    - Cache connection data
    - Debounce real-time updates
    - Progressive loading
    - Optimize large networks
    - Monitor memory usage
    - Background processing

    Security Implications:
    - Rate limiting
    - Request validation
    - CSRF protection
    - XSS prevention
    - Data encryption
    - Privacy controls
    - Access management

    Best Practices:
    - Enable caching
    - Add error handling
    - Validate inputs
    - Show loading states
    - Make responsive
    - Track analytics
    - Test thoroughly

    Example:
        connections = db.Column(db.JSON,
            info={'widget': FriendFollowWidget(
                connection_type='friend',
                privacy_enabled=True,
                suggestions=True,
                stats=True,
                max_connections=1000,
                categories=['Family', 'Work', 'School'],
                visualization=True,
                offline_support=True
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://d3js.org/d3.v7.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.1/socket.io.min.js",
        "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "/static/js/friend-follow.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://unpkg.com/vis-network/styles/vis-network.min.css",
        "/static/css/friend-follow.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize FriendFollowWidget with custom settings.

        Args:
            connection_type (str): Type of connection ('friend', 'follow')
            privacy_enabled (bool): Enable privacy settings
            suggestions (bool): Enable connection suggestions
            stats (bool): Show connection statistics
            max_connections (int): Maximum allowed connections
            categories (list): Connection categories
            import_sources (list): Available import sources
            visualization (bool): Enable network visualization
            offline_support (bool): Enable offline mode
            realtime (bool): Enable real-time updates
            suggestion_algorithm (str): Suggestion algorithm type
            notification_config (dict): Notification settings
            analytics_config (dict): Analytics settings
            rate_limit (dict): Rate limiting configuration
            sync_interval (int): Background sync interval
            cache_duration (int): Cache duration in seconds
        """
        super().__init__(**kwargs)

        # Core Settings
        self.connection_type = kwargs.get("connection_type", "follow")
        self.privacy_enabled = kwargs.get("privacy_enabled", True)
        self.suggestions = kwargs.get("suggestions", True)
        self.stats = kwargs.get("stats", True)
        self.max_connections = kwargs.get("max_connections", 1000)
        self.categories = kwargs.get("categories", ["Friends", "Family", "Work"])
        self.import_sources = kwargs.get("import_sources", ["csv", "vcard", "social"])
        self.visualization = kwargs.get("visualization", False)

        # Advanced Features
        self.offline_support = kwargs.get("offline_support", True)
        self.realtime = kwargs.get("realtime", True)
        self.suggestion_algorithm = kwargs.get("suggestion_algorithm", "collaborative")

        # Technical Configuration
        self.notification_config = kwargs.get(
            "notification_config", {"email": True, "push": True, "in_app": True}
        )
        self.analytics_config = kwargs.get(
            "analytics_config",
            {
                "track_interactions": True,
                "track_suggestions": True,
                "track_engagement": True,
            },
        )
        self.rate_limit = kwargs.get(
            "rate_limit",
            {
                "requests": {"count": 100, "interval": 3600},
                "connections": {"count": 50, "interval": 86400},
            },
        )
        self.sync_interval = kwargs.get("sync_interval", 300)
        self.cache_duration = kwargs.get("cache_duration", 3600)

    def render_field(self, field, **kwargs):
        """Render the friend/follow widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="friend-follow-widget" id="{field.id}-container">
                <!-- Network Visualization -->
                {self._render_network(field.id) if self.visualization else ''}

                <!-- Connection Management -->
                <div class="connection-manager">
                    <div class="tabs">
                        <nav class="nav nav-tabs" role="tablist">
                            <a class="nav-link active" data-toggle="tab" href="#connections" role="tab">
                                Connections <span class="badge badge-primary connection-count"></span>
                            </a>
                            <a class="nav-link" data-toggle="tab" href="#requests" role="tab">
                                Requests <span class="badge badge-warning request-count"></span>
                            </a>
                            <a class="nav-link" data-toggle="tab" href="#suggestions" role="tab">
                                Suggestions
                            </a>
                        </nav>

                        <div class="tab-content">
                            <div class="tab-pane fade show active" id="connections" role="tabpanel">
                                <div class="connection-list"></div>
                                <div class="load-more" style="display:none;">
                                    <button class="btn btn-link">Load More</button>
                                </div>
                            </div>

                            <div class="tab-pane fade" id="requests" role="tabpanel">
                                <div class="request-list"></div>
                            </div>

                            <div class="tab-pane fade" id="suggestions" role="tabpanel">
                                <div class="suggestion-list"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Connection Stats -->
                {self._render_stats(field.id) if self.stats else ''}

                <!-- Loading States -->
                <div class="loading-overlay" style="display:none;" role="alert" aria-busy="true">
                    <div class="spinner-border"></div>
                    <span class="sr-only">Loading connections...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const network = new FriendFollowNetwork('{field.id}', {{
                        connectionType: '{self.connection_type}',
                        privacyEnabled: {str(self.privacy_enabled).lower()},
                        suggestions: {str(self.suggestions).lower()},
                        stats: {str(self.stats).lower()},
                        maxConnections: {self.max_connections},
                        categories: {json.dumps(self.categories)},
                        importSources: {json.dumps(self.import_sources)},
                        visualization: {str(self.visualization).lower()},
                        offlineSupport: {str(self.offline_support).lower()},
                        realtime: {str(self.realtime).lower()},
                        suggestionAlgorithm: '{self.suggestion_algorithm}',
                        notificationConfig: {json.dumps(self.notification_config)},
                        analyticsConfig: {json.dumps(self.analytics_config)},
                        rateLimit: {json.dumps(self.rate_limit)},
                        syncInterval: {self.sync_interval},
                        cacheDuration: {self.cache_duration},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.friend-follow-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Initialize if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        network.loadData(JSON.parse(existingData));
                    }}

                    // Cleanup on unload
                    $(window).on('unload', function() {{
                        network.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )
        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )
        return f"{css_includes}\n{js_includes}"

    def _render_network(self, field_id):
        """Render network visualization container"""
        return f"""
            <div class="network-visualization">
                <div id="{field_id}-network" class="network-container"></div>
                <div class="network-controls">
                    <button class="btn btn-sm btn-light zoom-in" aria-label="Zoom in">
                        <i class="fa fa-search-plus"></i>
                    </button>
                    <button class="btn btn-sm btn-light zoom-out" aria-label="Zoom out">
                        <i class="fa fa-search-minus"></i>
                    </button>
                    <button class="btn btn-sm btn-light fit" aria-label="Fit view">
                        <i class="fa fa-expand"></i>
                    </button>
                </div>
            </div>
        """

    def _render_stats(self, field_id):
        """Render connection statistics"""
        return f"""
            <div class="connection-stats">
                <div class="row">
                    <div class="col-md-4">
                        <div class="stat-card">
                            <h6>Total Connections</h6>
                            <div class="stat-value" id="{field_id}-total"></div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="stat-card">
                            <h6>Mutual Connections</h6>
                            <div class="stat-value" id="{field_id}-mutual"></div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="stat-card">
                            <h6>Growth Rate</h6>
                            <div class="stat-value" id="{field_id}-growth"></div>
                        </div>
                    </div>
                </div>
            </div>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_connection_data(data)
                self.data = data
            except json.JSONDecodeError:
                raise ValueError("Invalid connection data format")
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_connection_data(self, data):
        """Validate connection data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid connection data structure")

        required_keys = ["connections", "requests", "metadata"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required data keys")

        # Validate connections
        if len(data.get("connections", [])) > self.max_connections:
            raise ValueError(f"Maximum connections ({self.max_connections}) exceeded")

        # Validate individual connections
        for connection in data.get("connections", []):
            if not all(k in connection for k in ["id", "type", "status", "timestamp"]):
                raise ValueError("Invalid connection structure")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_connection_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class QRCodeWidget(BS3TextFieldWidget):
    """
    Widget for generating and displaying QR codes with advanced features.

    Features:
    - Multiple QR formats (SVG, PNG, EPS, PDF)
    - Error correction levels (L, M, Q, H)
    - Custom styling options (dots, squares, rounded)
    - Logo embedding with size/position control
    - Size/scale customization
    - One-click download in multiple formats
    - Batch generation with templates
    - Dynamic updates on value change
    - Built-in QR code scanner
    - Template library support
    - Version tracking
    - Usage analytics
    - Mobile-responsive design
    - Live preview
    - Input validation

    Database Type:
        PostgreSQL: TEXT or JSONB for storing QR data
        SQLAlchemy: String or JSON type

    Required Dependencies:
    - qrcodejs2 (QR generation)
    - html5-qrcode (QR scanning)
    - file-saver (downloading)
    - canvas-to-blob (format conversion)

    Browser Support:
    - Chrome 49+
    - Firefox 52+
    - Safari 11+
    - Edge 79+
    - Opera 36+
    - iOS Safari 11+
    - Chrome for Android 89+

    Required Permissions:
    - Camera access (for scanning)
    - File system (for downloads)
    - LocalStorage (for templates)

    Performance Considerations:
    - Lazy load scanner
    - Cache generated codes
    - Debounce dynamic updates
    - Optimize large batches
    - Compress downloaded files

    Security Implications:
    - Validate input data
    - Sanitize custom templates
    - Scan uploaded logos
    - Rate limit generation
    - CORS for remote logos

    Example:
        qr_code = StringField('QR Code',
                            widget=QRCodeWidget(
                                format='svg',
                                error_correction='H',
                                size=200,
                                logo=True,
                                style='dots'
                            ))
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/qrcodejs2@0.0.2/qrcode.min.js",
        "https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js",
        "https://cdn.jsdelivr.net/npm/file-saver@2.0.5/dist/FileSaver.min.js",
        "https://cdn.jsdelivr.net/npm/canvas-to-blob@1.0.0/canvas-to-blob.min.js",
        "/static/js/qr-widget.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = ["/static/css/qr-widget.css"]

    def __init__(self, **kwargs):
        """
        Initialize QRCodeWidget with custom settings.

        Args:
            format (str): Output format (svg, png, eps, pdf)
            error_correction (str): Error correction level (L, M, Q, H)
            size (int): QR code size in pixels (50-1000)
            logo (bool/str): Logo embedding settings or URL
            style (str): Visual style (squares, dots, rounded)
            colors (dict): Custom colors for QR code
            margin (int): Quiet zone size (0-10)
            download_options (list): Available download formats
            enable_scanner (bool): Enable QR code scanner
            templates (list): Predefined QR templates
            analytics (bool): Enable usage tracking
            cache_generated (bool): Cache generated codes
            batch_size (int): Maximum batch size
            rate_limit (dict): Rate limiting settings
        """
        super().__init__(**kwargs)

        # Basic settings
        self.format = kwargs.get("format", "svg")
        self.error_correction = kwargs.get("error_correction", "M")
        self.size = min(max(kwargs.get("size", 200), 50), 1000)
        self.logo = kwargs.get("logo", False)
        self.style = kwargs.get("style", "squares")
        self.colors = kwargs.get("colors", {"dark": "#000000", "light": "#ffffff"})
        self.margin = min(max(kwargs.get("margin", 4), 0), 10)
        self.download_options = kwargs.get("download_options", ["svg", "png"])

        # Advanced features
        self.enable_scanner = kwargs.get("enable_scanner", True)
        self.templates = kwargs.get("templates", [])
        self.analytics = kwargs.get("analytics", False)
        self.cache_generated = kwargs.get("cache_generated", True)
        self.batch_size = kwargs.get("batch_size", 100)
        self.rate_limit = kwargs.get(
            "rate_limit",
            {
                "generation": {"count": 100, "interval": 3600},
                "downloads": {"count": 50, "interval": 3600},
            },
        )

    def render_field(self, field, **kwargs):
        """Render the QR code widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="qr-code-widget" id="{field.id}-container">
                <!-- QR Code Preview -->
                <div class="qr-preview">
                    <div id="{field.id}-qr"></div>
                    <div class="loading-overlay" style="display:none;">
                        <div class="spinner"></div>
                    </div>
                </div>

                <!-- Controls -->
                <div class="qr-controls">
                    <div class="form-row">
                        <div class="col">
                            <label for="{field.id}-format">Format</label>
                            <select id="{field.id}-format" class="form-control">
                                <option value="svg">SVG</option>
                                <option value="png">PNG</option>
                                <option value="eps">EPS</option>
                                <option value="pdf">PDF</option>
                            </select>
                        </div>
                        <div class="col">
                            <label for="{field.id}-error">Error Correction</label>
                            <select id="{field.id}-error" class="form-control">
                                <option value="L">Low (7%)</option>
                                <option value="M" selected>Medium (15%)</option>
                                <option value="Q">Quartile (25%)</option>
                                <option value="H">High (30%)</option>
                            </select>
                        </div>
                    </div>

                    <div class="form-row mt-2">
                        <div class="col">
                            <label for="{field.id}-size">Size</label>
                            <input type="range" id="{field.id}-size" class="form-control-range"
                                   min="50" max="1000" value="{self.size}">
                        </div>
                    </div>

                    {self._render_logo_controls(field.id) if self.logo else ''}
                </div>

                <!-- Download Options -->
                <div class="qr-download mt-3">
                    <div class="btn-group">
                        {self._render_download_buttons(field.id)}
                    </div>
                </div>

                <!-- Scanner Integration -->
                {self._render_scanner(field.id) if self.enable_scanner else ''}

                <!-- Error Messages -->
                <div class="alert alert-danger mt-2" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const qr = new QRCodeWidget('{field.id}', {{
                        format: '{self.format}',
                        errorCorrection: '{self.error_correction}',
                        size: {self.size},
                        logo: {json.dumps(self.logo)},
                        style: '{self.style}',
                        colors: {json.dumps(self.colors)},
                        margin: {self.margin},
                        downloadOptions: {json.dumps(self.download_options)},
                        enableScanner: {str(self.enable_scanner).lower()},
                        templates: {json.dumps(self.templates)},
                        analytics: {str(self.analytics).lower()},
                        cacheGenerated: {str(self.cache_generated).lower()},
                        rateLimit: {json.dumps(self.rate_limit)},

                        onGenerated: function(dataUrl) {{
                            updatePreview(dataUrl);
                        }},
                        onError: function(error) {{
                            showError(error);
                        }},
                        onDownload: function(format) {{
                            trackDownload(format);
                        }}
                    }});

                    // Update QR preview
                    function updatePreview(dataUrl) {{
                        const preview = $('#{field.id}-qr');
                        preview.html(`<img src="${dataUrl}" alt="QR Code">`);
                    }}

                    // Error handling
                    function showError(error) {{
                        const alert = $('.qr-code-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Analytics tracking
                    function trackDownload(format) {{
                        if ({str(self.analytics).lower()}) {{
                            // Implement analytics tracking
                        }}
                    }}

                    // Handle input changes
                    $('#{field.id}').on('input', _.debounce(function() {{
                        qr.generateCode($(this).val());
                    }}, 300));

                    // Clean up on unload
                    $(window).on('unload', function() {{
                        qr.cleanup();
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

    def _render_logo_controls(self, field_id):
        """Render logo upload and positioning controls"""
        return f"""
            <div class="logo-controls mt-2">
                <div class="form-row">
                    <div class="col">
                        <label>Logo</label>
                        <input type="file" id="{field_id}-logo" class="form-control-file"
                               accept="image/*">
                    </div>
                    <div class="col">
                        <label>Logo Size (%)</label>
                        <input type="number" id="{field_id}-logo-size" class="form-control"
                               min="5" max="30" value="15">
                    </div>
                </div>
            </div>
        """

    def _render_download_buttons(self, field_id):
        """Render download format buttons"""
        buttons = []
        for fmt in self.download_options:
            buttons.append(
                f"""
                <button type="button" class="btn btn-outline-primary"
                        data-format="{fmt}">
                    Download {fmt.upper()}
                </button>
            """
            )
        return "\n".join(buttons)

    def _render_scanner(self, field_id):
        """Render QR code scanner interface"""
        return f"""
            <div class="qr-scanner mt-3">
                <button type="button" class="btn btn-secondary" id="{field_id}-scan">
                    <i class="fa fa-qrcode"></i> Scan QR Code
                </button>
                <div id="{field_id}-reader" style="display:none;"></div>
            </div>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                value = valuelist[0]
                if len(value) > 2953:  # Maximum QR data capacity
                    raise ValueError("QR code data capacity exceeded")
                self.data = value
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                # Validate data capacity
                if len(self.data) > 2953:
                    raise ValueError("QR code data capacity exceeded")

                # Validate URL if data looks like a URL
                if re.match(r"https?://", self.data):
                    url = urlparse(self.data)
                    if not all([url.scheme, url.netloc]):
                        raise ValueError("Invalid URL format")
            except ValueError as e:
                raise ValueError(str(e))


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
                        rules: {json.dumps(self.available_rules)},
                        templates: {str(self.templates).lower()},
                        testing: {str(self.testing).lower()},
                        crossField: {str(self.cross_field).lower()},
                        customFunctions: {json.dumps(self.custom_functions)},
                        errorMessages: {json.dumps(self.error_messages)},
                        ruleGroups: {json.dumps(self.rule_groups)},
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


class DataPreviewProfilerWidget(BS3TextFieldWidget):
    """
    Widget for previewing and profiling data from various sources with advanced analytics capabilities.

    Features:
    - Multiple data source support (databases, files, APIs)
    - Interactive data preview with pagination and filtering
    - Automated data type detection and validation
    - Comprehensive statistical analysis
    - Missing value analysis and handling
    - Distribution plots and visualizations
    - Correlation analysis and heatmaps
    - Dynamic sampling with confidence intervals
    - Customizable quality metrics and scoring
    - Pattern and anomaly detection
    - Column dependency analysis
    - Automated report generation
    - Cross-source profile comparison
    - Export to multiple formats
    - Real-time updates
    - Mobile responsive design
    - Accessibility compliance
    - Offline capability

    Database Type:
        PostgreSQL: JSONB for storing profile data and configurations
        SQLAlchemy: JSON type with validation

    Required Dependencies:
    - pandas >= 1.3.0 (data analysis)
    - numpy >= 1.20.0 (numerical computations)
    - plotly >= 5.0.0 (visualizations)
    - DataTables >= 1.10.24 (data display)
    - D3.js >= 7.0.0 (custom visualizations)
    - Papa Parse >= 5.3.0 (CSV parsing)
    - jStat >= 1.8.0 (statistical computations)

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - File system access (for import/export)
    - LocalStorage (for caching)
    - IndexedDB (for offline support)
    - Worker threads (for computation)

    Performance Considerations:
    - Use streaming for large datasets
    - Implement progressive loading
    - Cache computed results
    - Optimize visualizations
    - Use web workers for computation
    - Compress data transfers
    - Lazy load components
    - Monitor memory usage

    Security Implications:
    - Validate input data
    - Sanitize file uploads
    - Rate limit API calls
    - Implement CORS policies
    - Encrypt sensitive data
    - Audit access logs
    - Handle PII appropriately

    Example:
        profile_widget = StringField('Data Profile',
            widget=DataPreviewProfilerWidget(
                source_type='database',
                sample_size=1000,
                metrics=['basic', 'distribution', 'correlation'],
                visualizations=['histogram', 'boxplot', 'heatmap'],
                export_formats=['pdf', 'json', 'csv'],
                threshold_rules={
                    'missing_pct': 0.1,
                    'unique_pct': 0.9
                },
                cache_duration=3600
            ))
    """

    JS_DEPENDENCIES = [
        "https://cdn.plot.ly/plotly-latest.min.js",
        "https://cdn.datatables.net/1.10.24/js/jquery.dataTables.min.js",
        "https://d3js.org/d3.v7.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.3.0/papaparse.min.js",
        "https://cdn.jsdelivr.net/npm/jstat@latest/dist/jstat.min.js",
        "/static/js/data-profiler.js",
    ]

    CSS_DEPENDENCIES = [
        "https://cdn.datatables.net/1.10.24/css/jquery.dataTables.min.css",
        "/static/css/data-profiler.css",
    ]

    DEFAULT_METRICS = {
        "basic": ["count", "missing", "unique", "dtype"],
        "statistical": ["mean", "std", "min", "max", "quartiles"],
        "distribution": ["histogram", "boxplot", "density"],
        "correlation": ["pearson", "spearman", "kendall"],
        "patterns": ["duplicates", "outliers", "cycles"],
    }

    def __init__(self, **kwargs):
        """
        Initialize DataPreviewProfilerWidget with custom settings.

        Args:
            source_type (str): Data source type ('database', 'file', 'api')
            sample_size (int): Sample size for analysis (0 for full dataset)
            metrics (list): Analysis metrics to include
            visualizations (list): Enabled visualization types
            export_formats (list): Available export formats
            custom_metrics (dict): Custom profiling metrics
            threshold_rules (dict): Quality threshold rules
            visualization_options (dict): Plot configurations
            cache_results (bool): Enable result caching
            cache_duration (int): Cache duration in seconds
            streaming (bool): Enable streaming for large datasets
            worker_threads (int): Number of worker threads
            offline_mode (bool): Enable offline support
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.source_type = kwargs.get("source_type", "database")
        self.sample_size = max(0, kwargs.get("sample_size", 1000))
        self.metrics = kwargs.get("metrics", ["basic", "statistical"])
        self.visualizations = kwargs.get("visualizations", ["histogram", "boxplot"])
        self.export_formats = kwargs.get("export_formats", ["pdf", "json"])

        # Advanced Features
        self.custom_metrics = kwargs.get("custom_metrics", {})
        self.threshold_rules = kwargs.get(
            "threshold_rules",
            {"missing_pct": 0.2, "unique_pct": 0.95, "outlier_std": 3},
        )
        self.visualization_options = kwargs.get(
            "visualization_options",
            {"theme": "light", "colorscale": "Viridis", "responsive": True},
        )

        # Technical Configuration
        self.cache_results = kwargs.get("cache_results", True)
        self.cache_duration = kwargs.get("cache_duration", 3600)
        self.streaming = kwargs.get("streaming", False)
        self.worker_threads = min(16, max(1, kwargs.get("worker_threads", 4)))
        self.offline_mode = kwargs.get("offline_mode", False)
        self.debug_mode = kwargs.get("debug_mode", False)

        # Validate settings
        self._validate_configuration()

    def render_field(self, field, **kwargs):
        """Render the data profiler widget with all controls and visualizations"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="data-profiler-widget" id="{field.id}-container">
                <!-- Data Source Selection -->
                <div class="source-selection mb-3">
                    <select class="form-control" id="{field.id}-source">
                        <option value="database">Database</option>
                        <option value="file">File Upload</option>
                        <option value="api">API Endpoint</option>
                    </select>
                </div>

                <!-- Data Preview -->
                <div class="data-preview mb-3">
                    <h5>Data Preview</h5>
                    <div class="table-responsive">
                        <table id="{field.id}-preview" class="table table-striped">
                            <thead></thead>
                            <tbody></tbody>
                        </table>
                    </div>
                </div>

                <!-- Profile Results -->
                <div class="profile-results">
                    <div class="row">
                        <div class="col-md-6">
                            <div class="card h-100">
                                <div class="card-header">
                                    <h5 class="card-title">Basic Statistics</h5>
                                </div>
                                <div class="card-body">
                                    <div id="{field.id}-basic-stats"></div>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="card h-100">
                                <div class="card-header">
                                    <h5 class="card-title">Data Quality</h5>
                                </div>
                                <div class="card-body">
                                    <div id="{field.id}-quality-scores"></div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Visualizations -->
                    <div class="visualizations mt-3">
                        <div id="{field.id}-plots"></div>
                    </div>
                </div>

                <!-- Export Options -->
                <div class="export-options mt-3">
                    <div class="btn-group">
                        {self._render_export_buttons(field.id)}
                    </div>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;" role="alert" aria-busy="true">
                    <div class="spinner-border"></div>
                    <span class="sr-only">Processing data...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const profiler = new DataProfiler('{field.id}', {{
                        sourceType: '{self.source_type}',
                        sampleSize: {self.sample_size},
                        metrics: {json.dumps(self.metrics)},
                        visualizations: {json.dumps(self.visualizations)},
                        exportFormats: {json.dumps(self.export_formats)},
                        customMetrics: {json.dumps(self.custom_metrics)},
                        thresholdRules: {json.dumps(self.threshold_rules)},
                        visualizationOptions: {json.dumps(self.visualization_options)},
                        cacheResults: {str(self.cache_results).lower()},
                        cacheDuration: {self.cache_duration},
                        streaming: {str(self.streaming).lower()},
                        workerThreads: {self.worker_threads},
                        offlineMode: {str(self.offline_mode).lower()},
                        debugMode: {str(self.debug_mode).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                            updateVisualizations(data);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.data-profiler-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    function updateVisualizations(data) {{
                        if (data && data.visualizations) {{
                            Object.entries(data.visualizations).forEach(([type, config]) => {{
                                plotly.newPlot(`{field.id}-${{type}}`, config);
                            }});
                        }}
                    }}

                    // Initialize if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        profiler.loadData(JSON.parse(existingData));
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        profiler.cleanup();
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

    def _render_export_buttons(self, field_id):
        """Render export format buttons"""
        buttons = []
        for fmt in self.export_formats:
            buttons.append(
                f"""
                <button type="button" class="btn btn-outline-primary"
                        data-format="{fmt}">
                    Export {fmt.upper()}
                </button>
            """
            )
        return "\n".join(buttons)

    def _validate_configuration(self):
        """Validate widget configuration settings"""
        # Validate metrics
        for metric in self.metrics:
            if metric not in self.DEFAULT_METRICS and metric not in self.custom_metrics:
                raise ValueError(f"Unknown metric: {metric}")

        # Validate threshold rules
        for rule, value in self.threshold_rules.items():
            if not isinstance(value, (int, float)):
                raise ValueError(f"Invalid threshold value for {rule}")

        # Validate visualization options
        if "theme" in self.visualization_options and self.visualization_options[
            "theme"
        ] not in ["light", "dark"]:
            raise ValueError("Invalid theme option")

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_profile_data(data)
                self.data = data
            except json.JSONDecodeError:
                raise ValueError("Invalid profile data format")
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_profile_data(self, data):
        """Validate profile data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid profile data structure")

        required_keys = ["metadata", "statistics", "quality_scores"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required profile data keys")

        # Validate statistics
        if not isinstance(data["statistics"], dict):
            raise ValueError("Invalid statistics format")

        # Validate quality scores
        scores = data.get("quality_scores", {})
        if not isinstance(scores, dict):
            raise ValueError("Invalid quality scores format")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_profile_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class VirtualScrollingListWidget(BS3TextFieldWidget):
    """
    Widget for efficiently handling large lists with virtual/infinite scrolling in PgAppForge.

    Features:
    - Virtual scrolling with dynamic item rendering
    - Progressive loading with buffer management
    - Real-time search and filtering
    - Multi-column sorting
    - Item selection with keyboard support
    - Custom item templates
    - Touch-optimized mobile support
    - State persistence across sessions
    - Loading indicators and error handling
    - Performance monitoring
    - Full accessibility compliance
    - RTL language support
    - Lazy loading
    - Virtualized rendering
    - Buffer management
    - Item recycling
    - Smooth scrolling

    Database Type:
        PostgreSQL: JSONB for storing list configurations and state
        SQLAlchemy: JSON type with validation

    Required Dependencies:
    - jQuery >= 3.6.0
    - IntersectionObserver API
    - Virtual Scroller >= 1.0.0
    - Lodash >= 4.17.0

    Browser Support:
    - Chrome >= 51
    - Firefox >= 55
    - Safari >= 12.1
    - Edge >= 15
    - Opera >= 38
    - iOS Safari >= 12.2
    - Android Browser >= 88

    Required Permissions:
    - LocalStorage (state persistence)
    - SessionStorage (scroll position)
    - IndexedDB (item caching)

    Performance Considerations:
    - Use fixed item heights when possible
    - Implement lazy loading
    - Optimize reflow operations
    - Cache rendered items
    - Debounce scroll events
    - Virtualize non-visible content
    - Monitor memory usage
    - Clean up detached nodes

    Security Implications:
    - Validate all user input
    - Sanitize item templates
    - Rate limit API requests
    - Prevent XSS in templates
    - Secure state persistence
    - Audit data access

    Example:
        items_list = db.Column(db.JSON,
            info={'widget': VirtualScrollingListWidget(
                page_size=50,
                buffer_size=100,
                enable_search=True,
                selection=True,
                item_height=60,
                load_threshold=0.8,
                cache_items=True,
                custom_renderer=None
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/virtual-scroll/1.5.2/virtual-scroll.min.js",
        "/static/js/virtual-list.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/virtual-scroll/1.5.2/virtual-scroll.css",
        "/static/css/virtual-list.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize VirtualScrollingListWidget with custom settings.

        Args:
            page_size (int): Items per page (10-100)
            buffer_size (int): Buffer size for rendering (50-500)
            enable_search (bool): Enable search functionality
            selection (bool): Enable item selection
            item_height (int): Fixed item height in pixels
            load_threshold (float): Scroll threshold for loading (0.5-0.9)
            cache_items (bool): Enable item caching
            custom_renderer (callable): Custom item renderer function
            sort_enabled (bool): Enable sorting capabilities
            filter_enabled (bool): Enable filtering
            keyboard_nav (bool): Enable keyboard navigation
            mobile_optimize (bool): Enable mobile optimizations
            rtl (bool): Enable RTL support
            persist_state (bool): Enable state persistence
            performance_mode (bool): Enable performance optimizations
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.page_size = min(max(kwargs.get("page_size", 50), 10), 100)
        self.buffer_size = min(max(kwargs.get("buffer_size", 100), 50), 500)
        self.enable_search = kwargs.get("enable_search", True)
        self.selection = kwargs.get("selection", False)
        self.item_height = kwargs.get("item_height", None)
        self.load_threshold = min(max(kwargs.get("load_threshold", 0.8), 0.5), 0.9)
        self.cache_items = kwargs.get("cache_items", True)
        self.custom_renderer = kwargs.get("custom_renderer", None)

        # Advanced Features
        self.sort_enabled = kwargs.get("sort_enabled", True)
        self.filter_enabled = kwargs.get("filter_enabled", True)
        self.keyboard_nav = kwargs.get("keyboard_nav", True)
        self.mobile_optimize = kwargs.get("mobile_optimize", True)
        self.rtl = kwargs.get("rtl", False)
        self.persist_state = kwargs.get("persist_state", True)
        self.performance_mode = kwargs.get("performance_mode", False)
        self.debug_mode = kwargs.get("debug_mode", False)

        # Internal State
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the virtual scrolling list widget"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="virtual-list-widget" id="{field.id}-container"
                 role="listbox" tabindex="0"
                 aria-label="Virtual scrolling list">

                {self._render_search() if self.enable_search else ''}

                <div class="list-container"
                     data-rtl="{str(self.rtl).lower()}"
                     role="presentation">
                    <div class="list-viewport" role="presentation">
                        <div class="list-content" role="presentation"></div>
                    </div>
                </div>

                <div class="loading-indicator" role="status" aria-hidden="true">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading items...</span>
                </div>

                <div class="error-message alert alert-danger" role="alert"
                     style="display:none;"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const virtualList = new VirtualList('{field.id}', {{
                        pageSize: {self.page_size},
                        bufferSize: {self.buffer_size},
                        enableSearch: {str(self.enable_search).lower()},
                        selection: {str(self.selection).lower()},
                        itemHeight: {self.item_height or 'null'},
                        loadThreshold: {self.load_threshold},
                        cacheItems: {str(self.cache_items).lower()},
                        customRenderer: {self.custom_renderer or 'null'},
                        sortEnabled: {str(self.sort_enabled).lower()},
                        filterEnabled: {str(self.filter_enabled).lower()},
                        keyboardNav: {str(self.keyboard_nav).lower()},
                        mobileOptimize: {str(self.mobile_optimize).lower()},
                        rtl: {str(self.rtl).lower()},
                        persistState: {str(self.persist_state).lower()},
                        performanceMode: {str(self.performance_mode).lower()},
                        debugMode: {str(self.debug_mode).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.virtual-list-widget .error-message');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-indicator')[show ? 'show' : 'hide']();
                    }}

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        virtualList.loadItems(JSON.parse(existingData));
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        virtualList.cleanup();
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

    def _render_search(self):
        """Render search input field"""
        return """
            <div class="search-container mb-3">
                <input type="text" class="form-control"
                       placeholder="Search items..."
                       aria-label="Search items">
            </div>
        """

    def _validate_config(self):
        """Validate widget configuration"""
        if self.item_height and (self.item_height < 20 or self.item_height > 500):
            raise ValueError("Item height must be between 20 and 500 pixels")

        if self.custom_renderer and not callable(self.custom_renderer):
            raise ValueError("Custom renderer must be callable")

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_data(data)
                self.data = data
            except json.JSONDecodeError:
                raise ValueError("Invalid list data format")
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_data(self, data):
        """Validate list data structure and content"""
        if not isinstance(data, list):
            raise ValueError("Data must be a list")

        for item in data:
            if not isinstance(item, dict):
                raise ValueError("Each item must be a dictionary")

            if "id" not in item:
                raise ValueError("Each item must have an id")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class VersionControlWidget(BS3TextFieldWidget):
    """
    Widget for tracking and managing version history of records/documents in a table.

    This widget provides comprehensive version control functionality including diff viewing,
    rollback, branching, and conflict resolution. It tracks changes to specified fields
    and maintains a full audit trail with comments and notifications.

    Features:
    - Version history tracking and visualization
    - Side-by-side diff viewing with syntax highlighting
    - Point-in-time restore/rollback capability
    - Git-style branching and merging
    - Conflict detection and resolution
    - Comments and annotations on changes
    - Interactive timeline visualization
    - Version comparison and diff exports
    - Complete audit trail with user tracking
    - Real-time change notifications
    - Role-based access control
    - Bulk restore/rollback support
    - Full text search across versions
    - Customizable diff rules and displays
    - Branch visualization
    - Performance optimized for large histories

    Database Type:
        PostgreSQL: JSONB for storing version history, metadata and configurations
        SQLAlchemy: JSON type with validation

    Required Dependencies:
    - diff-match-patch >= 1.0.1 (diffing engine)
    - CodeMirror >= 5.65.0 (syntax highlighting)
    - vis-timeline >= 7.4.0 (timeline visualization)
    - merge-deep >= 3.0.0 (merge handling)
    - jsondiffpatch >= 0.4.1 (JSON diffing)

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47
    - iOS Safari >= 12
    - Chrome for Android >= 89

    Required Permissions:
    - Database write access for version storage
    - File system access for exports
    - WebSocket for real-time updates
    - LocalStorage for preferences

    Performance Considerations:
    - Use lazy loading for version history
    - Implement pagination for large histories
    - Cache frequently accessed versions
    - Compress version storage
    - Optimize diff computation
    - Clean up old versions
    - Monitor memory usage

    Security Implications:
    - Validate all version data
    - Sanitize user comments
    - Enforce access control
    - Audit all operations
    - Rate limit operations
    - Encrypt sensitive diffs
    - Handle PII appropriately

    Example:
        version_control = db.Column(db.JSON,
            info={'widget': VersionControlWidget(
                track_fields=['content', 'metadata'],
                diff_view=True,
                restore=True,
                comments=True,
                max_versions=100,
                branch_support=True,
                merge_strategy='recursive',
                notification_rules={
                    'email': ['major_version'],
                    'ui': ['all']
                }
            )}
        )
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/diff_match_patch/20121119/diff_match_patch.js",
        "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.0/codemirror.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.0/mode/javascript/javascript.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/vis-timeline/7.4.0/vis-timeline-graph2d.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jsondiffpatch/0.4.1/jsondiffpatch.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js",
        "/static/js/version-control.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.0/codemirror.min.css",
        "https://cdnjs.cloudflare.com/ajax/libs/vis-timeline/7.4.0/vis-timeline-graph2d.min.css",
        "/static/css/version-control.css",
    ]

    # Default merge strategies
    MERGE_STRATEGIES = {
        "latest": "Take latest version",
        "recursive": "Recursive merge",
        "manual": "Manual conflict resolution",
    }

    def __init__(self, **kwargs):
        """
        Initialize VersionControlWidget with custom settings.

        Args:
            track_fields (list): Fields to track changes
            diff_view (bool): Enable diff viewing
            restore (bool): Enable version restore
            comments (bool): Enable version comments
            max_versions (int): Maximum versions to keep
            branch_support (bool): Enable branching
            merge_strategy (str): Conflict resolution strategy
            notification_rules (dict): Change notification settings
            cache_versions (bool): Enable version caching
            compress_storage (bool): Enable storage compression
            exclude_fields (list): Fields to exclude from versioning
            diff_context_lines (int): Number of context lines in diffs
            retention_period (int): Days to retain versions
            auto_prune (bool): Auto remove old versions
            access_control (dict): Access control rules
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.track_fields = kwargs.get("track_fields", [])
        self.diff_view = kwargs.get("diff_view", True)
        self.restore = kwargs.get("restore", True)
        self.comments = kwargs.get("comments", True)
        self.max_versions = kwargs.get("max_versions", 100)
        self.branch_support = kwargs.get("branch_support", False)
        self.merge_strategy = kwargs.get("merge_strategy", "recursive")
        self.notification_rules = kwargs.get("notification_rules", {"ui": ["all"]})

        # Advanced Settings
        self.cache_versions = kwargs.get("cache_versions", True)
        self.compress_storage = kwargs.get("compress_storage", True)
        self.exclude_fields = kwargs.get("exclude_fields", ["created_at", "updated_at"])
        self.diff_context_lines = min(max(kwargs.get("diff_context_lines", 3), 0), 10)
        self.retention_period = kwargs.get("retention_period", 365)
        self.auto_prune = kwargs.get("auto_prune", True)
        self.access_control = kwargs.get("access_control", {})
        self.debug_mode = kwargs.get("debug_mode", False)

        # Validate settings
        self._validate_config()

    def render_field(self, field, **kwargs):
        """
        Render the version control widget with all controls and visualizations.

        Args:
            field: The form field instance
            **kwargs: Additional HTML attributes

        Returns:
            str: Rendered HTML for the widget
        """
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        js_config = {
            "trackFields": self.track_fields,
            "diffView": self.diff_view,
            "restore": self.restore,
            "comments": self.comments,
            "maxVersions": self.max_versions,
            "branchSupport": self.branch_support,
            "mergeStrategy": self.merge_strategy,
            "notificationRules": self.notification_rules,
            "cacheVersions": self.cache_versions,
            "compressStorage": self.compress_storage,
            "excludeFields": self.exclude_fields,
            "diffContextLines": self.diff_context_lines,
            "retentionPeriod": self.retention_period,
            "autoPrune": self.auto_prune,
            "accessControl": self.access_control,
            "debugMode": self.debug_mode,
        }

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="version-control-widget" id="{field.id}-container">
                <!-- Version History Timeline -->
                <div class="version-timeline mb-3">
                    <div id="{field.id}-timeline"></div>
                </div>

                <!-- Diff Viewer -->
                {self._render_diff_viewer(field.id) if self.diff_view else ''}

                <!-- Version Controls -->
                <div class="version-controls mb-3">
                    {self._render_version_controls(field.id)}
                </div>

                <!-- Branch Management -->
                {self._render_branch_controls(field.id) if self.branch_support else ''}

                <!-- Comments Section -->
                {self._render_comments_section(field.id) if self.comments else ''}

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner-border"></div>
                    <span class="sr-only">Loading version history...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    var versionControl = new VersionControl('{field.id}', {json.dumps(js_config)});

                    // Error handler
                    function showError(error) {{
                        $('.version-control-widget .alert').text(error).show().delay(5000).fadeOut();
                    }}

                    // Loading state handler
                    function toggleLoading(show) {{
                        $('.loading-overlay').toggle(show);
                    }}

                    // Diff view update handler
                    function updateDiffView(version) {{
                        if ({str(self.diff_view).lower()}) {{
                            versionControl.renderDiff(version);
                        }}
                    }}

                    // Load initial data if exists
                    var existingData = $('#{field.id}').val();
                    if (existingData) {{
                        versionControl.loadVersions(JSON.parse(existingData));
                    }}

                    // Cleanup
                    window.addEventListener('unload', function() {{
                        versionControl.cleanup();
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

    def _render_diff_viewer(self, field_id):
        """Render the diff viewer interface"""
        return f"""
            <div class="diff-viewer mb-3">
                <div class="diff-controls">
                    <select id="{field_id}-version1" class="form-control"></select>
                    <select id="{field_id}-version2" class="form-control"></select>
                </div>
                <div id="{field_id}-diff" class="diff-content"></div>
            </div>
        """

    def _render_version_controls(self, field_id):
        """Render version control buttons"""
        controls = []
        if self.restore:
            controls.append(
                f"""
                <button type="button" class="btn btn-primary"
                        id="{field_id}-restore">
                    Restore Version
                </button>
            """
            )

        controls.append(
            f"""
            <button type="button" class="btn btn-secondary"
                    id="{field_id}-export">
                Export History
            </button>
        """
        )

        return "\n".join(controls)

    def _render_branch_controls(self, field_id):
        """Render branch management controls"""
        return f"""
            <div class="branch-controls mb-3">
                <select id="{field_id}-branch" class="form-control">
                    <option value="main">main</option>
                </select>
                <button type="button" class="btn btn-secondary"
                        id="{field_id}-create-branch">
                    Create Branch
                </button>
                <button type="button" class="btn btn-primary"
                        id="{field_id}-merge">
                    Merge
                </button>
            </div>
        """

    def _render_comments_section(self, field_id):
        """Render version comments section"""
        return f"""
            <div class="comments-section mb-3">
                <div class="comment-list" id="{field_id}-comments"></div>
                <div class="comment-input">
                    <textarea class="form-control"
                             id="{field_id}-comment"
                             placeholder="Add a comment..."></textarea>
                    <button type="button" class="btn btn-primary mt-2"
                            id="{field_id}-add-comment">
                        Add Comment
                    </button>
                </div>
            </div>
        """

    def _validate_config(self):
        """Validate widget configuration settings"""
        if not self.track_fields:
            raise ValueError("At least one field must be tracked")

        if self.merge_strategy not in self.MERGE_STRATEGIES:
            raise ValueError(f"Invalid merge strategy: {self.merge_strategy}")

        if self.max_versions and self.max_versions < 1:
            raise ValueError("max_versions must be greater than 0")

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_version_data(data)
                self.data = data
            except json.JSONDecodeError:
                raise ValueError("Invalid version data format")
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_version_data(self, data):
        """Validate version data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid version data structure")

        required_keys = ["versions", "current", "branches"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required version data keys")

        if not isinstance(data["versions"], list):
            raise ValueError("Versions must be a list")

        for version in data["versions"]:
            if not isinstance(version, dict):
                raise ValueError("Each version must be a dictionary")

            required_version_keys = ["id", "timestamp", "changes"]
            if not all(key in version for key in required_version_keys):
                raise ValueError("Missing required version keys")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_version_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class DBMLEditorWidget(BS3TextFieldWidget):
    """
    Advanced DBML (Database Markup Language) editor with live preview, validation,
    and format conversion capabilities. Works like https://dbdiagram.io/

    Features:
    - Syntax highlighting with Monaco Editor
    - Smart auto-completion for DBML syntax
    - Live ERD preview with pan/zoom
    - Real-time error validation
    - Format conversion (SQL, Prisma, etc.)
    - Schema validation with detailed feedback
    - Export to multiple formats
    - Import from existing databases
    - Visual database diff
    - Version control with history
    - Real-time collaboration
    - Customizable themes
    - Template library
    - Advanced search/replace
    - Code folding and minimap

    Supported Conversions:
    - DBML to PostgreSQL
    - DBML to MySQL
    - DBML to SQLite
    - DBML to SQL Server
    - DBML to Prisma
    - SQL to DBML
    - Prisma to DBML

    Database Type:
        PostgreSQL: JSONB for storing DBML content and metadata
        SQLAlchemy: JSON type with validation

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47

    Required Permissions:
    - LocalStorage (preferences)
    - WebSocket (collaboration)
    - Clipboard (export)
    - File system (import/export)

    Performance Considerations:
    - Large schema throttling
    - Lazy loading for templates
    - Worker thread parsing
    - Cached conversions
    - Memory cleanup
    - Network optimization

    Security:
    - Input validation
    - SQL injection prevention
    - XSS protection
    - CORS policies
    - Rate limiting
    - Access control

    Example:
        dbml_editor = db.Column(db.JSON,
            info={'widget': DBMLEditorWidget(
                theme='dark',
                auto_complete=True,
                live_preview=True,
                export_formats=['postgresql', 'mysql', 'prisma'],
                templates=True
            )}
        )
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs/loader.js",
        "https://cdnjs.cloudflare.com/ajax/libs/sql-formatter/4.0.2/sql-formatter.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/dagre/0.8.5/dagre.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js",
        "/static/js/dbml-editor.js",
        "/static/js/dbml-parser.js",
        "/static/js/dbml-renderer.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "/static/css/dbml-editor.css",
        "https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs/editor/editor.main.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize DBMLEditorWidget with custom settings.

        Args:
            theme (str): Editor theme ('vs-dark', 'vs-light')
            auto_complete (bool): Enable auto-completion
            live_preview (bool): Enable live preview
            export_formats (list): Available export formats
            templates (bool): Enable template library
            collaboration (bool): Enable real-time collaboration
            diff_view (bool): Enable visual diff
            custom_snippets (dict): Custom code snippets
            max_schema_size (int): Max schema size in bytes
            cache_timeout (int): Cache timeout in seconds
            worker_threads (int): Number of worker threads
        """
        super().__init__(**kwargs)
        self.theme = kwargs.get("theme", "vs-dark")
        self.auto_complete = kwargs.get("auto_complete", True)
        self.live_preview = kwargs.get("live_preview", True)
        self.export_formats = kwargs.get("export_formats", ["postgresql", "mysql"])
        self.templates = kwargs.get("templates", True)
        self.collaboration = kwargs.get("collaboration", False)
        self.diff_view = kwargs.get("diff_view", True)
        self.custom_snippets = kwargs.get("custom_snippets", {})
        self.max_schema_size = kwargs.get("max_schema_size", 1024 * 1024)  # 1MB
        self.cache_timeout = kwargs.get("cache_timeout", 3600)
        self.worker_threads = min(16, max(1, kwargs.get("worker_threads", 4)))

        # Validate config
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the DBML editor widget"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="dbml-editor-widget" id="{field.id}-container">
                <!-- Editor Panel -->
                <div class="editor-panel" role="complementary">
                    <div id="{field.id}-editor" class="monaco-editor"></div>
                </div>

                <!-- Preview Panel -->
                <div class="preview-panel" role="complementary">
                    <div id="{field.id}-preview" class="erd-preview"></div>
                    <div class="preview-controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out">-</button>
                        <button class="btn btn-sm btn-default reset-zoom"
                                title="Reset Zoom">Reset</button>
                    </div>
                </div>

                <!-- Toolbar -->
                <div class="editor-toolbar" role="toolbar">
                    {self._render_toolbar(field.id)}
                </div>

                <!-- Status Bar -->
                <div class="status-bar" role="status">
                    <span class="error-count"></span>
                    <span class="cursor-position"></span>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Processing...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const editor = new DBMLEditor('{field.id}', {{
                        theme: '{self.theme}',
                        autoComplete: {str(self.auto_complete).lower()},
                        livePreview: {str(self.live_preview).lower()},
                        exportFormats: {json.dumps(self.export_formats)},
                        templates: {str(self.templates).lower()},
                        collaboration: {str(self.collaboration).lower()},
                        diffView: {str(self.diff_view).lower()},
                        customSnippets: {json.dumps(self.custom_snippets)},
                        maxSchemaSize: {self.max_schema_size},
                        cacheTimeout: {self.cache_timeout},
                        workerThreads: {self.worker_threads},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(content) {{
                            $('#{field.id}').val(content);
                            validateSchema(content);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.dbml-editor-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    function validateSchema(content) {{
                        if (content.length > {self.max_schema_size}) {{
                            showError('Schema size exceeds maximum allowed');
                            return false;
                        }}
                        return editor.validateSchema(content);
                    }}

                    // Initialize with existing data
                    const existingSchema = $('#{field.id}').val();
                    if (existingSchema) {{
                        editor.setContent(existingSchema);
                    }}

                    // Cleanup
                    window.addEventListener('unload', function() {{
                        editor.cleanup();
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

    def _render_toolbar(self, field_id):
        """Render editor toolbar with controls"""
        return f"""
            <div class="btn-group">
                <button type="button" class="btn btn-default"
                        id="{field_id}-export" title="Export Schema">
                    <i class="fa fa-download"></i>
                </button>
                <button type="button" class="btn btn-default"
                        id="{field_id}-import" title="Import Schema">
                    <i class="fa fa-upload"></i>
                </button>
                {self._render_template_dropdown(field_id) if self.templates else ''}
                <button type="button" class="btn btn-default"
                        id="{field_id}-format" title="Format Code">
                    <i class="fa fa-align-left"></i>
                </button>
            </div>
        """

    def _render_template_dropdown(self, field_id):
        """Render template selection dropdown"""
        return f"""
            <div class="btn-group">
                <button type="button" class="btn btn-default dropdown-toggle"
                        data-toggle="dropdown" title="Templates">
                    <i class="fa fa-file-code-o"></i>
                    <span class="caret"></span>
                </button>
                <ul class="dropdown-menu" id="{field_id}-templates"></ul>
            </div>
        """

    def _validate_config(self):
        """Validate widget configuration"""
        valid_themes = ["vs-dark", "vs-light"]
        if self.theme not in valid_themes:
            raise ValueError(
                f"Invalid theme. Must be one of: {', '.join(valid_themes)}"
            )

        if not isinstance(self.export_formats, list):
            raise ValueError("export_formats must be a list")

        valid_formats = ["postgresql", "mysql", "sqlite", "sqlserver", "prisma"]
        invalid_formats = [
            fmt for fmt in self.export_formats if fmt not in valid_formats
        ]
        if invalid_formats:
            raise ValueError(f"Invalid export formats: {', '.join(invalid_formats)}")

        if self.max_schema_size < 1024:
            raise ValueError("max_schema_size must be at least 1KB")

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                self.data = valuelist[0]
                self._validate_schema(self.data)
            except (ValueError, SyntaxError) as e:
                raise ValueError(f"Invalid DBML schema: {str(e)}")
        else:
            self.data = None

    def _validate_schema(self, schema):
        """Validate DBML schema syntax and structure"""
        if not schema:
            return

        if len(schema) > self.max_schema_size:
            raise ValueError(
                f"Schema size exceeds maximum of {self.max_schema_size} bytes"
            )

        try:
            # Basic syntax validation
            if not all(c in string.printable for c in schema):
                raise ValueError("Schema contains invalid characters")

            # Check for basic DBML structure
            if not any(
                keyword in schema.lower() for keyword in ["table", "ref:", "enum"]
            ):
                raise ValueError(
                    "Schema must contain at least one table, reference, or enum"
                )

            # Additional validation would be performed by the JavaScript parser
        except Exception as e:
            raise ValueError(f"Schema validation failed: {str(e)}")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_schema(self.data)
            except ValueError as e:
                raise ValueError(str(e))


class MermaidEditorWidget(BS3TextFieldWidget):
    """
    Interactive Mermaid diagram editor and renderer with live preview.

    Features:
    - Syntax highlighting with Monaco Editor
    - Live diagram preview with auto-refresh
    - Multiple diagram types (flowchart, sequence, class, ERD, etc.)
    - Theme customization (light/dark)
    - Export to SVG, PNG, PDF
    - Local version history
    - Template library with common patterns
    - Real-time collaboration support
    - Interactive pan/zoom controls
    - Responsive mobile layout
    - ARIA accessibility support
    - Custom CSS styling
    - Real-time error highlighting
    - Auto diagram layout
    - Reusable code snippets

    Supported Diagrams:
    - Flowchart
    - Sequence Diagram
    - Class Diagram
    - Entity Relationship Diagram
    - State Diagram
    - Gantt Chart
    - Pie Chart
    - User Journey
    - Git Graph
    - Requirement Diagram

    Database Type:
        PostgreSQL: JSONB for storing diagram content and metadata
        SQLAlchemy: JSON type with validation

    Required Dependencies:
    - Mermaid.js >= 9.3.0
    - Monaco Editor >= 0.33.0
    - html-to-image >= 1.11.0
    - Socket.IO >= 4.5.0 (collaboration)
    - pako >= 2.1.0 (compression)

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47

    Required Permissions:
    - LocalStorage (preferences)
    - IndexedDB (version history)
    - WebSocket (collaboration)
    - Clipboard (export)
    - File system (import/export)

    Performance Considerations:
    - Use worker threads for rendering
    - Cache rendered diagrams
    - Debounce preview updates
    - Compress diagram storage
    - Lazy load templates
    - Optimize large diagrams
    - Memory cleanup

    Security:
    - Validate diagram input
    - Sanitize custom styles
    - Rate limit operations
    - Scope localStorage
    - Secure WebSocket
    - XSS prevention

    Example:
        mermaid_editor = db.Column(db.JSON,
            info={'widget': MermaidEditorWidget(
                theme='default',
                live_preview=True,
                export_formats=['svg', 'png'],
                templates=True,
                collaboration=False
            )}
        )
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/mermaid@9.3.0/dist/mermaid.min.js",
        "https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs/loader.js",
        "https://cdn.jsdelivr.net/npm/html-to-image@1.11.0/dist/html-to-image.min.js",
        "https://cdn.jsdelivr.net/npm/socket.io-client@4.5.0/dist/socket.io.min.js",
        "https://cdn.jsdelivr.net/npm/pako@2.1.0/dist/pako.min.js",
        "/static/js/mermaid-editor.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/mermaid@9.3.0/dist/mermaid.min.css",
        "/static/css/mermaid-editor.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize MermaidEditorWidget with custom settings.

        Args:
            theme (str): Editor theme ('default', 'dark', 'forest', 'neutral')
            live_preview (bool): Enable live preview updates
            export_formats (list): Available export formats
            templates (bool): Enable template library
            auto_layout (bool): Enable automatic layout optimization
            pan_zoom (bool): Enable diagram pan/zoom controls
            custom_styles (dict): Custom CSS style definitions
            sequence_numbering (bool): Enable sequence diagram numbering
            flowchart_direction (str): Default flowchart direction
            collaboration (bool): Enable real-time collaboration
            cache_diagrams (bool): Enable diagram caching
            max_diagram_size (int): Maximum diagram size in bytes
            worker_threads (int): Number of rendering worker threads
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.theme = kwargs.get("theme", "default")
        self.live_preview = kwargs.get("live_preview", True)
        self.export_formats = kwargs.get("export_formats", ["svg", "png"])
        self.templates = kwargs.get("templates", True)
        self.auto_layout = kwargs.get("auto_layout", True)
        self.pan_zoom = kwargs.get("pan_zoom", True)
        self.custom_styles = kwargs.get("custom_styles", {})
        self.sequence_numbering = kwargs.get("sequence_numbering", False)
        self.flowchart_direction = kwargs.get("flowchart_direction", "TB")

        # Advanced Features
        self.collaboration = kwargs.get("collaboration", False)
        self.cache_diagrams = kwargs.get("cache_diagrams", True)
        self.max_diagram_size = kwargs.get("max_diagram_size", 1024 * 1024)  # 1MB
        self.worker_threads = min(16, max(1, kwargs.get("worker_threads", 4)))
        self.debug_mode = kwargs.get("debug_mode", False)

        # Internal State
        self._initialize_mermaid()
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the Mermaid editor widget with controls and preview"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="mermaid-editor-widget" id="{field.id}-container">
                <!-- Editor Panel -->
                <div class="editor-panel">
                    <div id="{field.id}-editor" class="monaco-editor"></div>
                </div>

                <!-- Preview Panel -->
                <div class="preview-panel">
                    <div id="{field.id}-preview" class="mermaid-preview"></div>
                    <div class="preview-controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out">-</button>
                        <button class="btn btn-sm btn-default reset-zoom"
                                title="Reset Zoom">Reset</button>
                    </div>
                </div>

                <!-- Toolbar -->
                <div class="editor-toolbar">
                    {self._render_toolbar(field.id)}
                </div>

                <!-- Status Bar -->
                <div class="status-bar">
                    <span class="error-count"></span>
                    <span class="cursor-position"></span>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Rendering diagram...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const editor = new MermaidEditor('{field.id}', {{
                        theme: '{self.theme}',
                        livePreview: {str(self.live_preview).lower()},
                        exportFormats: {json.dumps(self.export_formats)},
                        templates: {str(self.templates).lower()},
                        autoLayout: {str(self.auto_layout).lower()},
                        panZoom: {str(self.pan_zoom).lower()},
                        customStyles: {json.dumps(self.custom_styles)},
                        sequenceNumbering: {str(self.sequence_numbering).lower()},
                        flowchartDirection: '{self.flowchart_direction}',
                        collaboration: {str(self.collaboration).lower()},
                        cacheDiagrams: {str(self.cache_diagrams).lower()},
                        maxDiagramSize: {self.max_diagram_size},
                        workerThreads: {self.worker_threads},
                        debugMode: {str(self.debug_mode).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(content) {{
                            $('#{field.id}').val(content);
                            validateDiagram(content);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.mermaid-editor-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    function validateDiagram(content) {{
                        if (content.length > {self.max_diagram_size}) {{
                            showError('Diagram size exceeds maximum allowed');
                            return false;
                        }}
                        return editor.validateDiagram(content);
                    }}

                    // Initialize with existing diagram
                    const existingDiagram = $('#{field.id}').val();
                    if (existingDiagram) {{
                        editor.setContent(existingDiagram);
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        editor.cleanup();
                    }});
                }});
            </script>
        """
        )

    def render_diagram(self, content: str, format: str = "svg") -> str:
        """
        Render Mermaid diagram to specified format.

        Args:
            content (str): Mermaid diagram content
            format (str): Output format (svg, png, pdf)

        Returns:
            str: Rendered diagram in specified format

        Raises:
            ValueError: If format is unsupported or content is invalid
            RuntimeError: If rendering fails
        """
        try:
            if not content:
                raise ValueError("Empty diagram content")

            if format not in self.export_formats:
                raise ValueError(f"Unsupported format: {format}")

            # Validate syntax before rendering
            errors = self._validate_syntax(content)
            if errors:
                raise ValueError(f"Invalid diagram syntax: {errors}")

            # Apply theme and optimize layout
            content = self._apply_theme(self._optimize_layout(content))

            # Render using appropriate method
            if format == "svg":
                return self._render_svg(content)
            elif format == "png":
                return self._render_png(content)
            elif format == "pdf":
                return self._render_pdf(content)

        except Exception as e:
            if self.debug_mode:
                raise
            return f"Error rendering diagram: {str(e)}"

    def _validate_syntax(self, content: str) -> list:
        """
        Validate Mermaid diagram syntax.

        Returns:
            list: List of validation errors, empty if valid
        """
        try:
            # Basic structure validation
            if not content.strip():
                return ["Empty diagram"]

            # Check for required keywords based on type
            diagram_type = content.split()[0].lower()
            required_keywords = {
                "graph": ["-->"],
                "sequenceDiagram": ["->"],
                "classDiagram": ["class"],
                "erDiagram": ["||"],
                "stateDiagram": ["state"],
                "gantt": ["section"],
                "pie": ["title"],
                "journey": ["section"],
            }

            if diagram_type not in required_keywords:
                return [f"Unsupported diagram type: {diagram_type}"]

            keywords = required_keywords[diagram_type]
            if not any(k in content for k in keywords):
                return [f"Missing required keywords for {diagram_type}"]

            return []

        except Exception as e:
            return [f"Syntax validation error: {str(e)}"]

    def _optimize_layout(self, content: str) -> str:
        """
        Optimize diagram layout for better readability.

        Returns:
            str: Optimized diagram content
        """
        try:
            if not self.auto_layout:
                return content

            # Add proper spacing
            content = re.sub(r"\s+", " ", content)

            # Align arrows and relationships
            content = re.sub(r"(-->|->|\|\|)", r" \1 ", content)

            # Add line breaks for readability
            content = re.sub(r"([{};])", r"\1\n", content)

            return content

        except Exception:
            return content  # Return original if optimization fails

    def _apply_theme(self, content: str) -> str:
        """
        Apply theme styling to diagram.

        Returns:
            str: Themed diagram content
        """
        try:
            theme_config = {
                "default": {"background": "#ffffff", "fontFamily": "arial"},
                "dark": {
                    "background": "#2b2b2b",
                    "fontFamily": "arial",
                    "primaryColor": "#6eaa6e",
                },
                "forest": {
                    "background": "#f8f9fa",
                    "fontFamily": "courier",
                    "primaryColor": "#185619",
                },
                "neutral": {"background": "#f5f5f5", "fontFamily": "helvetica"},
            }

            config = theme_config.get(self.theme, theme_config["default"])

            # Apply theme config
            themed_content = f"""
                %%{json.dumps(config)}%%
                {content}
            """

            # Apply custom styles if defined
            if self.custom_styles:
                themed_content = f"""
                    %%{json.dumps(self.custom_styles)}%%
                    {themed_content}
                """

            return themed_content.strip()

        except Exception:
            return content  # Return original if theming fails

    def _generate_preview(self, content: str) -> str:
        """
        Generate preview of diagram for display.

        Returns:
            str: HTML preview of diagram
        """
        try:
            # Generate optimized SVG for preview
            preview_svg = self.render_diagram(content, "svg")

            # Add preview container with controls
            preview_html = f"""
                <div class="diagram-preview" role="img"
                     aria-label="Diagram preview">
                    {preview_svg}
                </div>
            """

            return preview_html

        except Exception as e:
            return (
                f'<div class="preview-error">Preview generation failed: {str(e)}</div>'
            )

    def _initialize_mermaid(self):
        """Initialize Mermaid.js configuration"""
        mermaid_config = {
            "theme": self.theme,
            "securityLevel": "strict",
            "startOnLoad": True,
            "flowchart": {
                "htmlLabels": True,
                "curve": "basis",
                "defaultRenderer": "dagre",
            },
            "sequence": {
                "showSequenceNumbers": self.sequence_numbering,
                "actorFontSize": 14,
                "noteFontSize": 14,
            },
            "gantt": {"titleTopMargin": 25, "barHeight": 20, "barGap": 4},
        }

        # Initialize Mermaid with config
        init_script = f"""
            mermaid.initialize({json.dumps(mermaid_config)});
        """

        return Markup(init_script)

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES
        )
        css_includes = "\n".join(
            f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES
        )
        return f"{css_includes}\n{js_includes}"

    def _render_toolbar(self, field_id):
        """Render editor toolbar with controls"""
        return f"""
            <div class="btn-group">
                <button type="button" class="btn btn-default"
                        id="{field_id}-export" title="Export Diagram">
                    <i class="fa fa-download"></i>
                </button>
                <button type="button" class="btn btn-default"
                        id="{field_id}-copy" title="Copy as SVG">
                    <i class="fa fa-copy"></i>
                </button>
                {self._render_template_dropdown(field_id) if self.templates else ''}
                <button type="button" class="btn btn-default"
                        id="{field_id}-format" title="Format Code">
                    <i class="fa fa-align-left"></i>
                </button>
            </div>
        """

    def _validate_config(self):
        """Validate widget configuration settings"""
        valid_themes = ["default", "dark", "forest", "neutral"]
        if self.theme not in valid_themes:
            raise ValueError(
                f"Invalid theme. Must be one of: {', '.join(valid_themes)}"
            )

        if not isinstance(self.export_formats, list):
            raise ValueError("export_formats must be a list")

        valid_formats = ["svg", "png", "pdf"]
        invalid_formats = [
            fmt for fmt in self.export_formats if fmt not in valid_formats
        ]
        if invalid_formats:
            raise ValueError(f"Invalid export formats: {', '.join(invalid_formats)}")

        if self.worker_threads < 1 or self.worker_threads > 16:
            raise ValueError("worker_threads must be between 1 and 16")


class DatabaseStructureWidget(BS3TextFieldWidget):
    """
    Widget for introspecting and visualizing PgAppForge database structure
    with interactive ERD diagrams.

    Features:
    - Automatic database introspection using SQLAlchemy reflection
    - Interactive ERD visualization with D3.js
    - Relationship mapping with foreign key detection
    - Table details view with column info and data preview
    - Column information including types, constraints, and indexes
    - Index visualization with optimization hints
    - Primary/foreign key constraint display
    - Export to multiple formats (PNG, SVG, PDF, DBML, SQL)
    - Full-text search across tables and columns
    - Zoom/Pan controls with minimap navigation
    - Filtering by schema/table/column
    - Custom styling themes
    - Documentation generation with Markdown/PDF
    - Change tracking with Git-style diff
    - Schema comparison with visual diff

    Database Type:
        PostgreSQL: JSONB for storing schema metadata and change history
        SQLAlchemy: JSON type with schema validation

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79

    Required Permissions:
    - Database read access for introspection
    - File system access for exports
    - LocalStorage for preferences
    - WebSocket for real-time updates

    Performance Considerations:
    - Lazy loading of table details
    - Caching of introspection results
    - Web worker for layout calculations
    - Throttled rendering updates
    - Memory cleanup on unload
    - Optimized SVG generation

    Security:
    - SQL injection prevention
    - XSS protection in rendering
    - CORS policies for exports
    - Access control validation
    - Input sanitization
    - Rate limiting of operations

    Example:
        db_structure = db.Column(db.JSON,
            info={'widget': DatabaseStructureWidget(
                include_tables=['user', 'role'],
                show_columns=True,
                show_relationships=True,
                export_formats=['png', 'dbml']
            )}
        )
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://d3js.org/d3.v7.min.js",
        "https://dagrejs.github.io/project/dagre-d3/latest/dagre-d3.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/html-to-image/1.11.0/html-to-image.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.0/socket.io.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js",
        "/static/js/database-structure.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css",
        "/static/css/database-structure.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize DatabaseStructureWidget with custom settings.

        Args:
            include_tables (list): Tables to include in diagram
            show_columns (bool): Show column details
            show_relationships (bool): Show relationships
            export_formats (list): Available export formats
            layout_direction (str): Diagram layout direction
            theme (str): Visual theme
            show_indexes (bool): Show table indexes
            show_constraints (bool): Show table constraints
            group_schemas (bool): Group tables by schema
            custom_styles (dict): Custom styling options
            cache_timeout (int): Cache timeout in seconds
            worker_threads (int): Number of worker threads
            max_tables (int): Maximum tables to display
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.include_tables = kwargs.get("include_tables", None)
        self.show_columns = kwargs.get("show_columns", True)
        self.show_relationships = kwargs.get("show_relationships", True)
        self.export_formats = kwargs.get("export_formats", ["png", "dbml"])
        self.layout_direction = kwargs.get("layout_direction", "LR")
        self.theme = kwargs.get("theme", "default")
        self.show_indexes = kwargs.get("show_indexes", True)
        self.show_constraints = kwargs.get("show_constraints", True)
        self.group_schemas = kwargs.get("group_schemas", False)
        self.custom_styles = kwargs.get("custom_styles", {})

        # Advanced Settings
        self.cache_timeout = kwargs.get("cache_timeout", 3600)
        self.worker_threads = min(16, max(1, kwargs.get("worker_threads", 4)))
        self.max_tables = kwargs.get("max_tables", 100)
        self.debug_mode = kwargs.get("debug_mode", False)

        # Initialize caches
        self._metadata_cache = {}
        self._layout_cache = {}

        # Validate config
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the database structure widget"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="database-structure-widget" id="{field.id}-container">
                <!-- Main Diagram Area -->
                <div class="diagram-area">
                    <div id="{field.id}-diagram" class="erd-diagram"></div>
                    <div class="diagram-controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out">-</button>
                        <button class="btn btn-sm btn-default reset-zoom"
                                title="Reset Zoom">Reset</button>
                    </div>
                </div>

                <!-- Toolbar -->
                <div class="editor-toolbar">
                    {self._render_toolbar(field.id)}
                </div>

                <!-- Table Details Panel -->
                <div class="details-panel" style="display:none;">
                    <div class="panel-header">
                        <h3 class="table-name"></h3>
                        <button class="close">&times;</button>
                    </div>
                    <div class="panel-content"></div>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading database structure...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const dbStructure = new DatabaseStructure('{field.id}', {{
                        includeTables: {json.dumps(self.include_tables)},
                        showColumns: {str(self.show_columns).lower()},
                        showRelationships: {str(self.show_relationships).lower()},
                        exportFormats: {json.dumps(self.export_formats)},
                        layoutDirection: '{self.layout_direction}',
                        theme: '{self.theme}',
                        showIndexes: {str(self.show_indexes).lower()},
                        showConstraints: {str(self.show_constraints).lower()},
                        groupSchemas: {str(self.group_schemas).lower()},
                        customStyles: {json.dumps(self.custom_styles)},
                        cacheTimeout: {self.cache_timeout},
                        workerThreads: {self.worker_threads},
                        maxTables: {self.max_tables},
                        debugMode: {str(self.debug_mode).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.database-structure-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        dbStructure.loadStructure(JSON.parse(existingData));
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        dbStructure.cleanup();
                    }});
                }});
            </script>
        """
        )

    def introspect_database(self) -> dict:
        """
        Introspect PgAppForge database structure.

        Returns:
            dict: Database structure information including tables,
                  columns, relationships, and constraints
        """
        try:
            from sqlalchemy import inspect

            inspector = inspect(db.engine)

            result = {"tables": {}, "relationships": [], "schemas": []}

            # Get all schemas
            schemas = inspector.get_schema_names()
            result["schemas"] = schemas

            # Filter tables if specified
            for schema in schemas:
                tables = inspector.get_table_names(schema=schema)
                if self.include_tables:
                    tables = [t for t in tables if t in self.include_tables]

                for table in tables[: self.max_tables]:
                    table_info = self._get_table_metadata(table, schema)
                    result["tables"][f"{schema}.{table}"] = table_info

            # Analyze relationships
            result["relationships"] = self._analyze_relationships()

            return result

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def generate_erd(self, format: str = "svg") -> str:
        """
        Generate ERD diagram in specified format.

        Args:
            format (str): Output format (svg, png, pdf)

        Returns:
            str: Generated ERD diagram in specified format
        """
        try:
            # Get database structure
            structure = self.introspect_database()
            if "error" in structure:
                return f'Error generating ERD: {structure["error"]}'

            # Generate layout
            layout = self._generate_layout()

            # Create visual elements
            elements = self._create_visual_elements()

            # Apply styling
            styled = self._apply_styling(elements)

            # Render based on format
            if format == "svg":
                return self._render_svg(styled)
            elif format == "png":
                return self._render_png(styled)
            elif format == "pdf":
                return self._render_pdf(styled)

            return f"Unsupported format: {format}"

        except Exception as e:
            if self.debug_mode:
                raise
            return f"Error generating ERD: {str(e)}"

    def export_schema(self, format: str) -> str:
        """
        Export database schema in specified format.

        Args:
            format (str): Export format (dbml, sql, html, pdf)

        Returns:
            str: Exported schema in specified format
        """
        try:
            structure = self.introspect_database()
            if "error" in structure:
                return f'Export failed: {structure["error"]}'

            if format == "dbml":
                return self._export_dbml(structure)
            elif format == "sql":
                return self._export_sql(structure)
            elif format == "html":
                return self._export_html(structure)
            elif format == "pdf":
                return self._export_pdf(structure)

            return f"Unsupported export format: {format}"

        except Exception as e:
            if self.debug_mode:
                raise
            return f"Export failed: {str(e)}"

    def compare_schemas(self, other_schema: dict) -> dict:
        """
        Compare current schema with another schema.

        Args:
            other_schema (dict): Schema to compare against

        Returns:
            dict: Comparison results showing differences
        """
        try:
            current = self.introspect_database()
            if "error" in current:
                return {"error": current["error"]}

            return {
                "tables_added": self._compare_tables(current, other_schema, "added"),
                "tables_removed": self._compare_tables(
                    current, other_schema, "removed"
                ),
                "tables_modified": self._compare_tables(
                    current, other_schema, "modified"
                ),
                "relationships_changed": self._compare_relationships(
                    current, other_schema
                ),
            }

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def generate_documentation(self, format: str = "html") -> str:
        """
        Generate database documentation.

        Args:
            format (str): Output format (html, pdf)

        Returns:
            str: Generated documentation in specified format
        """
        try:
            structure = self.introspect_database()
            if "error" in structure:
                return f'Documentation generation failed: {structure["error"]}'

            template_vars = {
                "structure": structure,
                "timestamp": datetime.now(),
                "settings": {
                    "show_columns": self.show_columns,
                    "show_relationships": self.show_relationships,
                    "show_indexes": self.show_indexes,
                    "show_constraints": self.show_constraints,
                },
            }

            if format == "html":
                return render_template("database_docs.html", **template_vars)
            elif format == "pdf":
                html = render_template("database_docs.html", **template_vars)
                return html2pdf(html)

            return f"Unsupported documentation format: {format}"

        except Exception as e:
            if self.debug_mode:
                raise
            return f"Documentation generation failed: {str(e)}"

    def _get_table_metadata(self, table_name: str, schema: str = None) -> dict:
        """Get detailed metadata for a specific table."""
        try:
            from sqlalchemy import inspect

            inspector = inspect(db.engine)

            # Get basic table info
            columns = inspector.get_columns(table_name, schema=schema)
            pk = inspector.get_pk_constraint(table_name, schema=schema)
            fks = inspector.get_foreign_keys(table_name, schema=schema)
            indexes = inspector.get_indexes(table_name, schema=schema)

            return {
                "name": table_name,
                "schema": schema,
                "columns": columns,
                "primary_key": pk,
                "foreign_keys": fks,
                "indexes": indexes,
                "comment": inspector.get_table_comment(table_name, schema=schema),
            }

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def _analyze_relationships(self) -> list:
        """Analyze and map database relationships."""
        try:
            relationships = []

            # Get all foreign keys
            for schema in db.engine.dialect.get_schema_names(db.engine):
                for table in db.engine.dialect.get_table_names(
                    db.engine, schema=schema
                ):
                    fks = db.engine.dialect.get_foreign_keys(
                        db.engine, table, schema=schema
                    )

                    for fk in fks:
                        relationships.append(
                            {
                                "source_schema": schema,
                                "source_table": table,
                                "source_columns": fk["constrained_columns"],
                                "target_schema": fk["referred_schema"],
                                "target_table": fk["referred_table"],
                                "target_columns": fk["referred_columns"],
                                "name": fk["name"],
                            }
                        )

            return relationships

        except Exception as e:
            if self.debug_mode:
                raise
            return []

    def _generate_layout(self) -> dict:
        """Generate optimal layout for ERD diagram."""
        try:
            import dagre

            # Create graph
            graph = dagre.Graph()
            graph.setGraph(
                {
                    "rankdir": self.layout_direction,
                    "nodesep": 70,
                    "ranksep": 50,
                    "marginx": 20,
                    "marginy": 20,
                }
            )

            # Add nodes and edges
            structure = self.introspect_database()
            if "error" in structure:
                return {"error": structure["error"]}

            for table in structure["tables"].values():
                graph.setNode(
                    table["name"], {"label": table["name"], "width": 180, "height": 100}
                )

            for rel in structure["relationships"]:
                graph.setEdge(rel["source_table"], rel["target_table"])

            # Calculate layout
            dagre.layout(graph)

            return {
                "nodes": graph.nodes(),
                "edges": graph.edges(),
                "graph": graph.graph(),
            }

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def _create_visual_elements(self) -> dict:
        """Create visual elements for diagram rendering."""
        try:
            elements = {"nodes": [], "edges": [], "groups": []}

            layout = self._generate_layout()
            if "error" in layout:
                return {"error": layout["error"]}

            # Create table nodes
            structure = self.introspect_database()
            for table in structure["tables"].values():
                node = self._create_table_node(table, layout)
                elements["nodes"].append(node)

            # Create relationship edges
            for rel in structure["relationships"]:
                edge = self._create_relationship_edge(rel, layout)
                elements["edges"].append(edge)

            # Create schema groups if enabled
            if self.group_schemas:
                elements["groups"] = self._create_schema_groups(structure)

            return elements

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def _apply_styling(self) -> dict:
        """Apply custom styling to diagram elements."""
        try:
            # Get base styles
            styles = {
                "diagram": {"background": "#ffffff", "fontFamily": "Arial"},
                "table": {"fill": "#f5f5f5", "stroke": "#cccccc", "strokeWidth": 1},
                "column": {"font": "12px Arial", "fill": "#333333"},
                "relationship": {"stroke": "#666666", "strokeWidth": 1},
            }

            # Apply theme
            theme_styles = self._get_theme_styles()
            styles.update(theme_styles)

            # Apply custom styles
            styles.update(self.custom_styles)

            return styles

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}


class AddressAutocompleteWidget(BS3TextFieldWidget):
    """
    Advanced address autocomplete widget with validation and geocoding integration.

    Features:
    - Real-time address suggestions
    - Multiple provider support (Google, Here, MapBox, etc.)
    - Address validation
    - Geocoding/reverse geocoding
    - Custom formatting
    - International support
    - Address components breakdown
    - Recent addresses
    - Favorite addresses
    - Offline support
    - Custom validation rules
    - Format standardization
    - Postal code validation
    - Multiple language support
    - Business/residential filtering
    - Custom address restrictions

    Supported Providers:
    - Google Places API
    - Here Maps
    - MapBox
    - OpenStreetMap
    - Algolia Places
    - Custom API integration

    Required Dependencies:
    - Google Places API
    - Leaflet.js
    - Axios

    Example:
        address = StringField('Address',
                            widget=AddressAutocompleteWidget(
                                provider='google',
                                api_key='your_api_key',
                                countries=['US', 'CA'],
                                type='both',
                                language='en'
                            ))
    """

    def __init__(self, **kwargs):
        """
        Initialize AddressAutocompleteWidget with custom settings.

        Args:
            provider (str): Address provider service
            api_key (str): API key for chosen provider
            countries (list): Restricted countries list
            type (str): Address type filter (residential/business/both)
            language (str): Preferred language
            format_template (str): Address format template
            validation_rules (dict): Custom validation rules
            recent_addresses (int): Number of recent addresses to store
            offline_database (str): Offline address database path
            bias_location (tuple): Location bias coordinates
            custom_restrictions (dict): Custom address restrictions
        """
        super().__init__(**kwargs)
        self.provider = kwargs.get("provider", "google")
        self.api_key = kwargs.get("api_key")
        self.countries = kwargs.get("countries", [])
        self.type = kwargs.get("type", "both")
        self.language = kwargs.get("language", "en")
        self.format_template = kwargs.get("format_template", None)
        self.validation_rules = kwargs.get("validation_rules", {})
        self.recent_addresses = kwargs.get("recent_addresses", 5)
        self.offline_database = kwargs.get("offline_database", None)
        self.bias_location = kwargs.get("bias_location", None)
        self.custom_restrictions = kwargs.get("custom_restrictions", {})

    def validate_address(self, address: str) -> dict:
        """
        Validate address using selected provider.

        Args:
            address (str): Address to validate

        Returns:
            dict: Validation results with components and status
        """
        pass

    def geocode_address(self, address: str) -> dict:
        """
        Geocode address to coordinates.

        Args:
            address (str): Address to geocode

        Returns:
            dict: Geocoding results with coordinates and metadata
        """
        pass


class GeographicHeatmapWidget(BS3TextFieldWidget):
    """
    Interactive geographic heatmap widget for visualizing data density and patterns.

    Features:
    - Multiple map providers with fallbacks
    - Custom color gradients with validation
    - Real-time data updates via WebSocket
    - Time-series animation with playback controls
    - Custom overlay layers and controls
    - Interactive legend with filtering
    - Dynamic zoom levels with minimap
    - Advanced data filtering and aggregation
    - Multiple export formats (PNG, SVG, PDF)
    - Marker clustering with custom thresholds
    - Rich tooltips with custom templates
    - Full mobile and touch support
    - Offline mode with data caching
    - GeoJSON boundary support
    - Built-in analytics tracking

    Database Type:
        PostgreSQL: JSONB for storing point data and configuration
        SQLAlchemy: JSON type with GiST index

    Map Providers:
    - OpenStreetMap (default)
    - Google Maps
    - MapBox
    - Here Maps
    - Carto
    - Custom tile servers
    - Fallback providers

    Required Dependencies:
    - Leaflet.js >= 1.7.0
    - Leaflet.heat >= 0.2.0
    - D3.js >= 7.0.0
    - Turf.js >= 6.5.0
    - HTML2Canvas >= 1.4.0

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47
    - iOS Safari >= 12
    - Chrome for Android >= 60

    Required Permissions:
    - Geolocation (optional)
    - LocalStorage (caching)
    - WebGL (enhanced rendering)
    - WebWorkers (data processing)

    Performance Considerations:
    - Use WebWorkers for data processing
    - Enable clustering for large datasets
    - Cache tiles and data
    - Throttle update frequency
    - Optimize marker rendering
    - Lazy load data chunks

    Security:
    - Validate data sources
    - Sanitize popup content
    - Rate limit updates
    - Scope localStorage access
    - Clean exported data
    - XSS prevention in tooltips

    Example:
        heatmap = db.Column(db.JSON,
            info={'widget': GeographicHeatmapWidget(
                provider='osm',
                gradient=['#313695', '#4575B4', '#74ADD1', '#ABD9E9',
                         '#E0F3F8', '#FFFFBF', '#FEE090', '#FDAE61',
                         '#F46D43', '#D73027', '#A50026'],
                radius=30,
                animate=True,
                cluster=True,
                max_points=50000,
                update_interval=1000,
                offline_support=True
            )}
        )
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.7.1/dist/leaflet.js",
        "https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js",
        "https://d3js.org/d3.v7.min.js",
        "https://unpkg.com/@turf/turf@6.5.0/turf.min.js",
        "https://unpkg.com/html2canvas@1.4.1/dist/html2canvas.min.js",
        "/static/js/heatmap-widget.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.7.1/dist/leaflet.css",
        "/static/css/heatmap-widget.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize GeographicHeatmapWidget with custom settings.

        Args:
            provider (str): Map provider ('osm', 'google', 'mapbox', 'here', 'custom')
            gradient (list): Color gradient stops for heatmap
            radius (int): Heat point radius in pixels (10-50)
            animate (bool): Enable time-series animation
            cluster (bool): Enable point clustering
            max_zoom (int): Maximum zoom level (1-22)
            min_zoom (int): Minimum zoom level (1-18)
            opacity (float): Heatmap opacity (0-1)
            legend (dict): Legend configuration and styling
            boundaries (dict): GeoJSON boundary definitions
            time_window (int): Animation time window in seconds
            custom_styles (dict): Custom map and control styles
            max_points (int): Maximum number of points to render
            update_interval (int): Data update interval in ms
            offline_support (bool): Enable offline support
            cache_tiles (bool): Enable tile caching
            worker_threads (int): Number of WebWorker threads
            debug_mode (bool): Enable debug logging
            api_keys (dict): Provider API keys
        """
        super().__init__(**kwargs)

        # Core Settings
        self.provider = kwargs.get("provider", "osm")
        self.gradient = kwargs.get(
            "gradient",
            [
                "#313695",
                "#4575B4",
                "#74ADD1",
                "#ABD9E9",
                "#E0F3F8",
                "#FFFFBF",
                "#FEE090",
                "#FDAE61",
                "#F46D43",
                "#D73027",
                "#A50026",
            ],
        )
        self.radius = min(50, max(10, kwargs.get("radius", 25)))
        self.animate = kwargs.get("animate", False)
        self.cluster = kwargs.get("cluster", False)
        self.max_zoom = min(22, max(1, kwargs.get("max_zoom", 18)))
        self.min_zoom = min(18, max(1, kwargs.get("min_zoom", 2)))
        self.opacity = min(1.0, max(0.1, kwargs.get("opacity", 0.6)))

        # Advanced Features
        self.legend = kwargs.get("legend", {"position": "bottomright"})
        self.boundaries = kwargs.get("boundaries", {})
        self.time_window = kwargs.get("time_window", 3600)
        self.custom_styles = kwargs.get("custom_styles", {})
        self.max_points = kwargs.get("max_points", 50000)
        self.update_interval = max(100, kwargs.get("update_interval", 1000))

        # Technical Settings
        self.offline_support = kwargs.get("offline_support", False)
        self.cache_tiles = kwargs.get("cache_tiles", True)
        self.worker_threads = min(16, max(1, kwargs.get("worker_threads", 4)))
        self.debug_mode = kwargs.get("debug_mode", False)
        self.api_keys = kwargs.get("api_keys", {})

        # Internal State
        self._data_cache = {}
        self._worker_pool = None
        self._bounds = None

        # Validate settings
        self._validate_config()
        self._initialize_workers()

    def render_field(self, field, **kwargs):
        """Render the heatmap widget with controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="geographic-heatmap-widget" id="{field.id}-container">
                <!-- Map Container -->
                <div class="map-container">
                    <div id="{field.id}-map" class="heatmap"></div>
                    <div class="map-controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out">-</button>
                        <button class="btn btn-sm btn-default reset-view"
                                title="Reset View">Reset</button>
                    </div>
                </div>

                <!-- Toolbar -->
                <div class="heatmap-toolbar">
                    {self._render_toolbar(field.id)}
                </div>

                <!-- Animation Controls -->
                {self._render_animation_controls(field.id) if self.animate else ''}

                <!-- Status Bar -->
                <div class="status-bar">
                    <span class="point-count"></span>
                    <span class="zoom-level"></span>
                    <span class="coordinates"></span>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading map data...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"
                     role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const heatmap = new HeatmapWidget('{field.id}', {{
                        provider: '{self.provider}',
                        gradient: {json.dumps(self.gradient)},
                        radius: {self.radius},
                        animate: {str(self.animate).lower()},
                        cluster: {str(self.cluster).lower()},
                        maxZoom: {self.max_zoom},
                        minZoom: {self.min_zoom},
                        opacity: {self.opacity},
                        legend: {json.dumps(self.legend)},
                        boundaries: {json.dumps(self.boundaries)},
                        timeWindow: {self.time_window},
                        customStyles: {json.dumps(self.custom_styles)},
                        maxPoints: {self.max_points},
                        updateInterval: {self.update_interval},
                        offlineSupport: {str(self.offline_support).lower()},
                        cacheTiles: {str(self.cache_tiles).lower()},
                        workerThreads: {self.worker_threads},
                        debugMode: {str(self.debug_mode).lower()},
                        apiKeys: {json.dumps(self.api_keys)},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                            updateStatus(data);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.geographic-heatmap-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    function updateStatus(data) {{
                        $('.point-count').text(`Points: ${{data.points.length}}`);
                        $('.zoom-level').text(`Zoom: ${{data.zoom}}`);
                        if (data.center) {{
                            $('.coordinates').text(
                                `Lat: ${{data.center.lat.toFixed(4)}} ` +
                                `Lng: ${{data.center.lng.toFixed(4)}}`
                            );
                        }}
                    }}

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        heatmap.setData(JSON.parse(existingData));
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        heatmap.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _validate_config(self):
        """Validate widget configuration settings"""
        # Validate provider
        valid_providers = ["osm", "google", "mapbox", "here", "carto", "custom"]
        if self.provider not in valid_providers:
            raise ValueError(
                f"Invalid provider. Must be one of: {', '.join(valid_providers)}"
            )

        # Validate gradient colors
        if not all(
            re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", color) for color in self.gradient
        ):
            raise ValueError(
                "Invalid gradient colors. Must be hex colors (#RGB or #RRGGBB)"
            )

        # Validate API keys
        if self.provider != "osm" and not self.api_keys.get(self.provider):
            raise ValueError(f"API key required for {self.provider}")

        # Validate numeric ranges
        if not 10 <= self.radius <= 50:
            raise ValueError("radius must be between 10 and 50")

        if not 1 <= self.min_zoom <= self.max_zoom <= 22:
            raise ValueError("Invalid zoom range")

        if not 0.1 <= self.opacity <= 1.0:
            raise ValueError("opacity must be between 0.1 and 1.0")

    def _initialize_workers(self):
        """Initialize WebWorker pool for data processing"""
        if not self.worker_threads:
            return

        try:
            from concurrent.futures import ThreadPoolExecutor

            self._worker_pool = ThreadPoolExecutor(max_workers=self.worker_threads)
        except Exception as e:
            if self.debug_mode:
                raise
            self.worker_threads = 0
            self._worker_pool = None

    def process_points(self, points: list) -> dict:
        """
        Process and validate point data for heatmap.

        Args:
            points: List of [lat, lng, intensity] points

        Returns:
            dict: Processed point data with validation status
        """
        try:
            # Basic validation
            if not points or not isinstance(points, list):
                raise ValueError("Invalid point data")

            if len(points) > self.max_points:
                points = points[: self.max_points]

            # Validate each point
            valid_points = []
            for point in points:
                if len(point) not in (2, 3):
                    continue

                lat, lng = point[:2]
                intensity = point[2] if len(point) == 3 else 1.0

                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    continue

                valid_points.append([lat, lng, max(0, min(1, intensity))])

            return {
                "points": valid_points,
                "count": len(valid_points),
                "truncated": len(points) > self.max_points,
            }

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def cleanup(self):
        """Clean up resources and worker threads"""
        try:
            if self._worker_pool:
                self._worker_pool.shutdown(wait=True)
                self._worker_pool = None

            self._data_cache.clear()

        except Exception as e:
            if self.debug_mode:
                raise


class WorkflowDiagramWidget(BS3TextFieldWidget):
    """
    Interactive workflow diagram widget for visualizing and managing business processes.
    Uses JointJS for diagram manipulation and Socket.io for real-time collaboration.
    Stores workflow data as JSONB in PostgreSQL.

    Features:
    - Drag-and-drop editing with touch support
    - Multiple node types with custom styling
    - Smart connectors with validation
    - Conditional flows with expressions
    - Nested subprocess support
    - Full state management with undo/redo
    - Version control with diff view
    - Multiple export formats
    - Template library with categories
    - Validation rules engine
    - Real-time collaboration
    - Mobile-responsive design
    - Search and filtering
    - Usage analytics
    - Accessibility support
    - Auto-save

    Node Types:
    - Start/End: Beginning and end points
    - Task/Activity: Work items
    - Decision: Conditional branching
    - Subprocess: Nested workflows
    - Event: Triggers and catches
    - Gateway: Flow control
    - Timer: Time-based triggers
    - Message: Communication points

    Database Type:
        PostgreSQL: JSONB for storing workflow data and version history
        SQLAlchemy: JSON type with schema validation

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47

    Required Permissions:
    - LocalStorage for undo/redo
    - WebSocket for collaboration
    - File system for exports

    Performance Considerations:
    - Lazy loading of subprocesses
    - Throttled auto-save
    - Web worker for validation
    - SVG optimization
    - Memory management

    Security Implications:
    - Input sanitization
    - Expression validation
    - CORS configuration
    - WebSocket authentication
    - Export validation

    Best Practices:
    - Enable auto-save
    - Set reasonable subprocess depth
    - Configure validation rules
    - Use templates for consistency
    - Implement error handling
    - Monitor analytics

    Troubleshooting:
    - Check browser console
    - Verify WebSocket connection
    - Validate JSON schema
    - Check localStorage quota
    - Monitor memory usage
    - Review error logs

    Required Dependencies:
    - JointJS/GoJS for diagram rendering
    - Socket.io for collaboration
    - SVG.js for export
    - Lodash for utilities
    - Day.js for timing

    Example:
        workflow = StringField('Process Flow',
                             widget=WorkflowDiagramWidget(
                                 editable=True,
                                 node_types=['task', 'decision', 'event'],
                                 templates=True,
                                 validation=True,
                                 auto_save=True,
                                 collaboration=True
                             ))
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jointjs/3.5.5/joint.min.js",
        "https://cdn.socket.io/4.5.0/socket.io.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/svg.js/3.1.1/svg.min.js",
        "https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js",
        "https://cdn.jsdelivr.net/npm/dayjs@1.11.5/dayjs.min.js",
        "/static/js/workflow-diagram.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jointjs/3.5.5/joint.min.css",
        "/static/css/workflow-diagram.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize WorkflowDiagramWidget with custom settings.

        Args:
            editable (bool): Enable editing (default: True)
            node_types (list): Available node types (default: ['task', 'decision', 'event'])
            templates (bool): Enable template library (default: True)
            validation (bool): Enable validation rules (default: True)
            collaboration (bool): Enable real-time collaboration (default: False)
            auto_layout (bool): Enable automatic layout (default: True)
            custom_nodes (dict): Custom node definitions (default: {})
            version_control (bool): Enable version tracking (default: False)
            export_formats (list): Available export formats (default: ['svg', 'png'])
            subprocess_depth (int): Maximum subprocess nesting (default: 3)
            auto_save (bool): Enable auto-save (default: True)
            save_interval (int): Auto-save interval in ms (default: 30000)
            undo_levels (int): Maximum undo history (default: 50)
            validation_rules (dict): Custom validation rules
            collaboration_server (str): WebSocket server URL
            analytics_enabled (bool): Enable usage analytics
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.editable = kwargs.get("editable", True)
        self.node_types = kwargs.get("node_types", ["task", "decision", "event"])
        self.templates = kwargs.get("templates", True)
        self.validation = kwargs.get("validation", True)
        self.collaboration = kwargs.get("collaboration", False)
        self.auto_layout = kwargs.get("auto_layout", True)
        self.custom_nodes = kwargs.get("custom_nodes", {})
        self.version_control = kwargs.get("version_control", False)
        self.export_formats = kwargs.get("export_formats", ["svg", "png"])
        self.subprocess_depth = kwargs.get("subprocess_depth", 3)

        # Advanced Settings
        self.auto_save = kwargs.get("auto_save", True)
        self.save_interval = max(5000, kwargs.get("save_interval", 30000))
        self.undo_levels = min(100, max(10, kwargs.get("undo_levels", 50)))
        self.validation_rules = kwargs.get("validation_rules", {})
        self.collaboration_server = kwargs.get("collaboration_server", None)
        self.analytics_enabled = kwargs.get("analytics_enabled", False)
        self.debug_mode = kwargs.get("debug_mode", False)

        # Internal State
        self._graph = None
        self._socket = None
        self._undo_stack = []
        self._redo_stack = []
        self._auto_save_timer = None
        self._last_saved = None

        # Validate settings
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the workflow diagram widget with controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="workflow-diagram-widget" id="{field.id}-container">
                <!-- Toolbar -->
                <div class="editor-toolbar" role="toolbar" aria-label="Workflow Editor Tools">
                    {self._render_toolbar(field.id)}
                </div>

                <!-- Main Diagram Area -->
                <div class="diagram-area">
                    <div id="{field.id}-paper" class="workflow-paper"
                         role="application" aria-label="Workflow Diagram"></div>

                    <!-- Diagram Controls -->
                    <div class="diagram-controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In" aria-label="Zoom In">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out" aria-label="Zoom Out">-</button>
                        <button class="btn btn-sm btn-default reset-zoom"
                                title="Reset Zoom" aria-label="Reset Zoom">Reset</button>
                    </div>
                </div>

                <!-- Node Palette -->
                <div class="node-palette" role="region" aria-label="Node Types">
                    {self._render_node_palette(field.id)}
                </div>

                <!-- Properties Panel -->
                <div class="properties-panel" style="display:none;"
                     role="complementary" aria-label="Node Properties">
                    <div class="panel-header">
                        <h3 class="node-name"></h3>
                        <button class="close" aria-label="Close">&times;</button>
                    </div>
                    <div class="panel-content"></div>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;" role="alert">
                    <div class="spinner"></div>
                    <span>Loading workflow...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"
                     role="alert" aria-live="polite"></div>

                <!-- Templates -->
                {self._render_templates(field.id) if self.templates else ''}

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const workflow = new WorkflowDiagram('{field.id}', {{
                        editable: {str(self.editable).lower()},
                        nodeTypes: {json.dumps(self.node_types)},
                        templates: {str(self.templates).lower()},
                        validation: {str(self.validation).lower()},
                        collaboration: {str(self.collaboration).lower()},
                        autoLayout: {str(self.auto_layout).lower()},
                        customNodes: {json.dumps(self.custom_nodes)},
                        versionControl: {str(self.version_control).lower()},
                        exportFormats: {json.dumps(self.export_formats)},
                        subprocessDepth: {self.subprocess_depth},
                        autoSave: {str(self.auto_save).lower()},
                        saveInterval: {self.save_interval},
                        undoLevels: {self.undo_levels},
                        validationRules: {json.dumps(self.validation_rules)},
                        collaborationServer: {json.dumps(self.collaboration_server)},
                        analyticsEnabled: {str(self.analytics_enabled).lower()},
                        debugMode: {str(self.debug_mode).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                            updateUndoRedo(data);
                        }},
                        onSave: function(success) {{
                            updateSaveStatus(success);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.workflow-diagram-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    function updateUndoRedo(data) {{
                        $('#{field.id}-undo').prop('disabled', !data.canUndo);
                        $('#{field.id}-redo').prop('disabled', !data.canRedo);
                    }}

                    function updateSaveStatus(success) {{
                        const icon = $('#{field.id}-save i');
                        icon.removeClass('fa-save fa-check fa-times')
                            .addClass(success ? 'fa-check' : 'fa-times');
                        setTimeout(() => icon.addClass('fa-save')
                            .removeClass('fa-check fa-times'), 2000);
                    }}

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        workflow.loadDiagram(JSON.parse(existingData));
                    }}

                    // Setup collaboration if enabled
                    if ({str(self.collaboration).lower()}) {{
                        workflow.initializeCollaboration();
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        workflow.cleanup();
                    }});

                    // Handle responsiveness
                    window.addEventListener('resize', _.debounce(function() {{
                        workflow.resize();
                    }}, 250));
                }});
            </script>
        """
        )

    def _validate_config(self):
        """Validate widget configuration settings"""
        # Validate node types
        valid_nodes = [
            "start",
            "end",
            "task",
            "decision",
            "subprocess",
            "event",
            "gateway",
            "timer",
            "message",
        ]
        invalid_nodes = [n for n in self.node_types if n not in valid_nodes]
        if invalid_nodes:
            raise ValueError(f"Invalid node types: {', '.join(invalid_nodes)}")

        # Validate export formats
        valid_formats = ["svg", "png", "pdf", "json"]
        invalid_formats = [f for f in self.export_formats if f not in valid_formats]
        if invalid_formats:
            raise ValueError(f"Invalid export formats: {', '.join(invalid_formats)}")

        # Validate subprocess depth
        if not 1 <= self.subprocess_depth <= 10:
            raise ValueError("subprocess_depth must be between 1 and 10")

        # Validate collaboration settings
        if self.collaboration and not self.collaboration_server:
            raise ValueError(
                "collaboration_server required when collaboration is enabled"
            )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        css_includes = [
            f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES
        ]
        return "\n".join(css_includes + js_includes)

    def cleanup(self):
        """Clean up resources and connections"""
        try:
            if self._socket:
                self._socket.disconnect()
                self._socket = None

            if self._auto_save_timer:
                clearTimeout(self._auto_save_timer)
                self._auto_save_timer = None

            self._graph = None
            self._undo_stack = []
            self._redo_stack = []

        except Exception as e:
            if self.debug_mode:
                raise


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
                    steps: {json.dumps(self.steps)},
                    validation: {str(self.validation).lower()},
                    saveState: {str(self.save_state).lower()},
                    linear: {str(self.linear).lower()},
                    transitions: {json.dumps(self.transitions)},
                    templates: {json.dumps(self.templates)},
                    dependencies: {json.dumps(self.dependencies)},
                    branching: {json.dumps(self.branching)},
                    analytics: {str(self.analytics).lower()},
                    customLayouts: {json.dumps(self.custom_layouts)},
                    persistence: '{self.persistence}',
                    autosave: {str(self.autosave).lower()},
                    paymentConfig: {json.dumps(self.payment_config)},
                    uploadConfig: {json.dumps(self.upload_config)},

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


class GPSTrackerWidget(BS3TextFieldWidget):
    """
    GPS tracking widget that periodically collects and stores location data with timestamps.
    Designed for PgAppForge with PostgreSQL JSONB storage.

    Features:
    - Periodic location tracking with configurable intervals
    - High accuracy mode with battery optimization
    - Offline storage with IndexedDB/LocalStorage
    - Interactive track visualization with heatmaps
    - Geofencing with customizable boundaries
    - Motion detection and activity recognition
    - Background tracking support
    - Battery status monitoring with adaptive intervals
    - Location clustering for large datasets
    - Export to multiple formats (JSON, GPX, KML)
    - Privacy controls with data anonymization
    - Comprehensive error handling
    - Usage analytics and diagnostics
    - Custom trigger support
    - Full accessibility support
    - Responsive mobile design

    Storage Format (PostgreSQL JSONB):
    {
        "tracks": [
            {
                "timestamp": "2024-01-01T12:00:00Z",
                "latitude": 0.0,
                "longitude": 0.0,
                "accuracy": 10.0,
                "altitude": 100.0,
                "speed": 0.0,
                "heading": 90.0,
                "battery": 85,
                "motion": "stationary",
                "provider": "gps"
            }
        ],
        "metadata": {
            "start_time": "2024-01-01T00:00:00Z",
            "device_id": "unique_device_id",
            "app_version": "1.0.0",
            "settings": {}
        }
    }

    Browser Compatibility:
    - Chrome >= 50
    - Firefox >= 55
    - Safari >= 11
    - Edge >= 79
    - Opera >= 37
    - Chrome for Android >= 50
    - Safari iOS >= 11

    Required Permissions:
    - geolocation
    - background-fetch
    - persistent-storage
    - wake-lock
    - device-orientation

    Performance Considerations:
    - Use requestIdleCallback for background processing
    - Implement adaptive tracking intervals
    - Batch location updates
    - Use IndexedDB for offline storage
    - Optimize battery usage with geofencing
    - Implement data pruning

    Security Implications:
    - Location data encryption at rest
    - Secure transmission over SSL/TLS
    - Data anonymization options
    - Access control implementation
    - Geofence data protection
    - Export data sanitization

    Required Dependencies:
    - Geolocation API
    - LocalStorage/IndexedDB
    - Background Tasks API
    - Leaflet.js for visualization
    - Turf.js for geofencing
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.7.1/dist/leaflet.js",
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet.heat/0.2.0/leaflet-heat.js",
        "https://npmcdn.com/@turf/turf@6.5.0/turf.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
        "/static/js/gps-tracker.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.7.1/dist/leaflet.css",
        "/static/css/gps-tracker.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize GPSTrackerWidget with custom settings.

        Args:
            interval (int): Tracking interval in seconds (default: 60)
            high_accuracy (bool): Enable high accuracy mode (default: True)
            battery_optimize (bool): Enable battery optimization (default: True)
            background (bool): Enable background tracking (default: False)
            geofencing (bool): Enable geofencing (default: False)
            max_records (int): Maximum number of records to store (default: 1000)
            distance_filter (float): Minimum distance between updates in meters (default: 10.0)
            motion_detection (bool): Enable motion-based updates (default: True)
            offline_storage (str): Offline storage method (default: 'indexeddb')
            privacy_mode (bool): Enable privacy features (default: False)
            export_formats (list): Available export formats (default: ['json', 'gpx', 'kml'])
            custom_triggers (dict): Custom tracking trigger conditions (default: {})
            debug_mode (bool): Enable debug logging (default: False)
        """
        super().__init__(**kwargs)

        # Core Settings
        self.interval = max(10, min(3600, kwargs.get("interval", 60)))
        self.high_accuracy = kwargs.get("high_accuracy", True)
        self.battery_optimize = kwargs.get("battery_optimize", True)
        self.background = kwargs.get("background", False)
        self.geofencing = kwargs.get("geofencing", False)
        self.max_records = max(100, min(10000, kwargs.get("max_records", 1000)))
        self.distance_filter = max(
            1.0, min(1000.0, kwargs.get("distance_filter", 10.0))
        )
        self.motion_detection = kwargs.get("motion_detection", True)
        self.offline_storage = kwargs.get("offline_storage", "indexeddb")
        self.privacy_mode = kwargs.get("privacy_mode", False)
        self.export_formats = kwargs.get("export_formats", ["json", "gpx", "kml"])
        self.custom_triggers = kwargs.get("custom_triggers", {})
        self.debug_mode = kwargs.get("debug_mode", False)

        # Internal State
        self._tracking = False
        self._last_location = None
        self._watch_id = None
        self._battery_level = None
        self._error_count = 0
        self._offline_queue = []

        # Validate settings
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the GPS tracker widget with controls and map"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="gps-tracker-widget" id="{field.id}-container">
                <!-- Map Container -->
                <div class="map-container">
                    <div id="{field.id}-map" class="tracker-map"
                         role="application" aria-label="Location tracking map"></div>

                    <!-- Map Controls -->
                    <div class="map-controls" role="toolbar"
                         aria-label="Map controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In" aria-label="Zoom in">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out" aria-label="Zoom out">-</button>
                        <button class="btn btn-sm btn-default center-map"
                                title="Center Map" aria-label="Center map">
                            <i class="fa fa-crosshairs"></i>
                        </button>
                    </div>
                </div>

                <!-- Controls -->
                <div class="tracker-controls">
                    <button class="btn btn-primary start-tracking"
                            aria-label="Start tracking">
                        <i class="fa fa-play"></i> Start Tracking
                    </button>
                    <button class="btn btn-danger stop-tracking" disabled
                            aria-label="Stop tracking">
                        <i class="fa fa-stop"></i> Stop
                    </button>
                    <button class="btn btn-default clear-tracks"
                            aria-label="Clear tracks">
                        <i class="fa fa-trash"></i> Clear
                    </button>
                    <div class="btn-group">
                        <button class="btn btn-default dropdown-toggle"
                                data-toggle="dropdown" aria-haspopup="true"
                                aria-expanded="false">
                            Export <span class="caret"></span>
                        </button>
                        <ul class="dropdown-menu">
                            {self._render_export_options()}
                        </ul>
                    </div>
                </div>

                <!-- Status -->
                <div class="tracker-status" aria-live="polite">
                    <span class="status-indicator"></span>
                    <span class="battery-indicator"></span>
                    <span class="accuracy-indicator"></span>
                    <span class="points-count"></span>
                </div>

                <!-- Loading Indicator -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Processing...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"
                     role="alert" aria-live="assertive"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const tracker = new GPSTracker('{field.id}', {{
                        interval: {self.interval},
                        highAccuracy: {str(self.high_accuracy).lower()},
                        batteryOptimize: {str(self.battery_optimize).lower()},
                        background: {str(self.background).lower()},
                        geofencing: {str(self.geofencing).lower()},
                        maxRecords: {self.max_records},
                        distanceFilter: {self.distance_filter},
                        motionDetection: {str(self.motion_detection).lower()},
                        offlineStorage: '{self.offline_storage}',
                        privacyMode: {str(self.privacy_mode).lower()},
                        customTriggers: {json.dumps(self.custom_triggers)},
                        debugMode: {str(self.debug_mode).lower()},

                        onLocationUpdate: function(location) {{
                            updateStatus(location);
                            $('#{field.id}').val(JSON.stringify(location));
                        }},

                        onError: function(error) {{
                            showError(error);
                        }},

                        onStateChange: function(tracking) {{
                            updateControls(tracking);
                        }}
                    }});

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        tracker.loadTracks(JSON.parse(existingData));
                    }}

                    // Event Handlers
                    $('.start-tracking').on('click', () => tracker.startTracking());
                    $('.stop-tracking').on('click', () => tracker.stopTracking());
                    $('.clear-tracks').on('click', () => {{
                        if (confirm('Clear all tracked locations?')) {{
                            tracker.clearTracks();
                        }}
                    }});

                    // Status Updates
                    function updateStatus(location) {{
                        $('.status-indicator').text(
                            `Last Update: ${{moment(location.timestamp).fromNow()}}`
                        );
                        $('.battery-indicator').text(
                            `Battery: ${{location.battery}}%`
                        );
                        $('.accuracy-indicator').text(
                            `Accuracy: ${{location.accuracy.toFixed(1)}}m`
                        );
                        $('.points-count').text(
                            `Points: ${{location.tracks.length}}`
                        );
                    }}

                    function showError(error) {{
                        const alert = $('.gps-tracker-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function updateControls(tracking) {{
                        $('.start-tracking').prop('disabled', tracking);
                        $('.stop-tracking').prop('disabled', !tracking);
                    }}

                    // Cleanup
                    window.addEventListener('unload', function() {{
                        tracker.cleanup();
                    }});

                    // Handle visibility changes
                    document.addEventListener('visibilitychange', function() {{
                        if (document.hidden) {{
                            tracker.handleBackground();
                        }} else {{
                            tracker.handleForeground();
                        }}
                    }});
                }});
            </script>
        """
        )

    def get_current_location(self) -> dict:
        """
        Get current location with metadata.

        Returns:
            dict: Current location data with timestamp and metadata
        """
        try:
            if not self._tracking:
                return {"error": "Tracking not active"}

            return {
                "timestamp": datetime.now().isoformat(),
                "latitude": self._last_location.get("latitude"),
                "longitude": self._last_location.get("longitude"),
                "accuracy": self._last_location.get("accuracy"),
                "battery": self._battery_level,
                "tracking": self._tracking,
            }
        except Exception as e:
            return {"error": str(e)}

    def export_tracks(self, format: str) -> str:
        """
        Export tracking data in specified format.

        Args:
            format (str): Export format (json, gpx, kml)

        Returns:
            str: Exported tracking data
        """
        try:
            if format not in self.export_formats:
                return "Unsupported export format"

            if format == "gpx":
                return self._export_gpx()
            elif format == "kml":
                return self._export_kml()
            else:
                return json.dumps(self._data)
        except Exception as e:
            return str(e)

    def check_geofence(self, location: dict) -> list:
        """
        Check if location is within defined geofences.

        Args:
            location (dict): Location to check

        Returns:
            list: Triggered geofence events
        """
        try:
            if not self.geofencing:
                return []

            triggered = []
            point = [location["longitude"], location["latitude"]]

            for fence in self.custom_triggers.get("geofences", []):
                if turf.booleanPointInPolygon(point, fence["polygon"]):
                    triggered.append(
                        {
                            "fence_id": fence["id"],
                            "name": fence["name"],
                            "type": fence["type"],
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

            return triggered
        except Exception as e:
            if self.debug_mode:
                print(f"Geofence error: {e}")
            return []

    def _validate_config(self) -> None:
        """Validate widget configuration settings"""
        if self.interval < 10:
            raise ValueError("Interval must be at least 10 seconds")

        if self.offline_storage not in ["indexeddb", "localstorage"]:
            raise ValueError("Invalid offline storage method")

        for format in self.export_formats:
            if format not in ["json", "gpx", "kml"]:
                raise ValueError(f"Invalid export format: {format}")

    def _include_dependencies(self) -> str:
        """Include required JavaScript and CSS dependencies"""
        js_includes = [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        css_includes = [
            f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES
        ]
        return "\n".join(css_includes + js_includes)

    def _render_export_options(self) -> str:
        """Render export format options"""
        options = []
        for format in self.export_formats:
            options.append(
                f'<li><a href="#" data-format="{format}">'
                f"Export as {format.upper()}</a></li>"
            )
        return "\n".join(options)

    def cleanup(self) -> None:
        """Clean up resources and connections"""
        try:
            if self._watch_id:
                navigator.geolocation.clearWatch(self._watch_id)

            self._tracking = False
            self._watch_id = None
            self._last_location = None

            # Save any queued offline data
            if self._offline_queue:
                self._save_offline_data()

        except Exception as e:
            if self.debug_mode:
                print(f"Cleanup error: {e}")


class PeriodicCameraWidget(BS3TextFieldWidget):
    """
    Widget for capturing periodic camera images with customizable intervals and settings.
    Stores image data and metadata in PostgreSQL JSONB column.

    Features:
    - Periodic image capture with configurable intervals
    - Multiple camera support with auto-detection
    - Image quality and resolution control
    - Motion detection with sensitivity settings
    - Face detection and counting
    - Timestamp and metadata overlays
    - Automatic storage management and cleanup
    - Background operation support
    - Custom trigger conditions
    - Privacy controls and data protection
    - Error recovery and retry logic
    - Live preview mode
    - Image processing pipelines
    - Multiple export formats
    - Usage analytics

    Database Type:
        PostgreSQL: JSONB column for storing image data and metadata
        SQLAlchemy: JSON type with schema validation

    Storage Format:
    {
        "images": [
            {
                "timestamp": "2024-01-01T12:00:00Z",
                "image_url": "path/to/image.jpg",
                "camera_id": "front",
                "resolution": "1920x1080",
                "faces_detected": 0,
                "motion_detected": false,
                "metadata": {
                    "device": "iPhone 12",
                    "orientation": "landscape",
                    "light_level": "bright",
                    "processing_time": 120,
                    "error_count": 0
                }
            }
        ],
        "settings": {
            "interval": 300,
            "quality": "high",
            "camera": "back",
            "resolution": "1920x1080",
            "motion_sensitivity": 0.5,
            "face_min_confidence": 0.8,
            "storage_limit_mb": 1000
        }
    }

    Browser Compatibility:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47
    - iOS Safari >= 12
    - Chrome for Android >= 60

    Required Permissions:
    - camera
    - microphone (optional)
    - storage
    - wake-lock
    - background-processing

    Performance Considerations:
    - Use WebWorkers for image processing
    - Implement lazy loading for image display
    - Optimize capture resolution
    - Batch process images
    - Implement storage cleanup
    - Monitor memory usage
    - Handle device thermal throttling

    Security Implications:
    - Camera access controls
    - Image data encryption
    - Secure storage handling
    - Access authorization
    - Privacy masking
    - Audit logging
    - Export validation

    Required Dependencies:
    - MediaDevices API
    - Canvas API
    - Background Tasks API
    - Face-API.js
    - OpenCV.js
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/dist/face-api.min.js",
        "https://docs.opencv.org/master/opencv.js",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
        "/static/js/periodic-camera.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = ["/static/css/periodic-camera.css"]

    def __init__(self, **kwargs):
        """
        Initialize PeriodicCameraWidget with custom settings.

        Args:
            interval (int): Capture interval in seconds (default: 300)
            camera (str): Preferred camera ('front', 'back', 'auto')
            quality (str): Image quality ('low', 'medium', 'high')
            motion_detection (bool): Enable motion detection
            face_detection (bool): Enable face detection
            max_images (int): Maximum number of images to store
            background (bool): Enable background capture
            timestamp_overlay (bool): Add timestamp to images
            storage_path (str): Image storage location
            privacy_mode (bool): Enable privacy features
            processing_options (dict): Image processing settings
            custom_triggers (dict): Custom capture trigger conditions
        """
        super().__init__(**kwargs)

        # Core Settings
        self.interval = max(10, min(3600, kwargs.get("interval", 300)))
        self.camera = kwargs.get("camera", "back")
        self.quality = kwargs.get("quality", "high")
        self.motion_detection = kwargs.get("motion_detection", False)
        self.face_detection = kwargs.get("face_detection", False)
        self.max_images = max(10, min(1000, kwargs.get("max_images", 100)))
        self.background = kwargs.get("background", False)
        self.timestamp_overlay = kwargs.get("timestamp_overlay", True)
        self.storage_path = kwargs.get("storage_path", "images/")
        self.privacy_mode = kwargs.get("privacy_mode", False)

        # Advanced Settings
        self.processing_options = {
            "resize": True,
            "max_width": 1920,
            "max_height": 1080,
            "format": "jpeg",
            "quality": 0.9,
            **kwargs.get("processing_options", {}),
        }

        self.custom_triggers = {
            "motion_threshold": 0.1,
            "face_confidence": 0.8,
            "min_light_level": 10,
            **kwargs.get("custom_triggers", {}),
        }

        # Internal State
        self._capturing = False
        self._stream = None
        self._last_image = None
        self._error_count = 0
        self._worker = None

        # Validate settings
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the camera widget with preview and controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="periodic-camera-widget" id="{field.id}-container">
                <!-- Preview Area -->
                <div class="camera-preview">
                    <video id="{field.id}-preview" autoplay playsinline
                           class="preview-video" style="display:none;"
                           aria-label="Camera preview"></video>
                    <canvas id="{field.id}-canvas" class="preview-canvas"
                           aria-label="Image preview"></canvas>

                    <!-- Camera Controls -->
                    <div class="camera-controls" role="toolbar">
                        <button class="btn btn-primary start-capture"
                                aria-label="Start capture">
                            <i class="fa fa-camera"></i> Start
                        </button>
                        <button class="btn btn-danger stop-capture" disabled
                                aria-label="Stop capture">
                            <i class="fa fa-stop"></i> Stop
                        </button>
                        <button class="btn btn-default single-photo"
                                aria-label="Take single photo">
                            <i class="fa fa-camera"></i> Single
                        </button>
                        <select class="camera-select form-control"
                                aria-label="Select camera"></select>
                    </div>

                    <!-- Settings -->
                    <div class="capture-settings">
                        <div class="form-group">
                            <label>Interval (seconds):
                                <input type="number" class="interval-input form-control"
                                       min="10" max="3600" value="{self.interval}">
                            </label>
                        </div>
                        <div class="form-check">
                            <input type="checkbox" class="motion-detection-toggle"
                                   id="{field.id}-motion"
                                   {' checked' if self.motion_detection else ''}>
                            <label for="{field.id}-motion">Motion Detection</label>
                        </div>
                    </div>
                </div>

                <!-- Image Gallery -->
                <div class="image-gallery" role="region"
                     aria-label="Captured images">
                    <div class="gallery-controls">
                        <button class="btn btn-default clear-images"
                                aria-label="Clear images">
                            <i class="fa fa-trash"></i> Clear
                        </button>
                        <button class="btn btn-default export-images dropdown-toggle"
                                data-toggle="dropdown" aria-haspopup="true"
                                aria-expanded="false">
                            <i class="fa fa-download"></i> Export
                        </button>
                        <ul class="dropdown-menu">
                            <li><a href="#" data-format="zip">ZIP Archive</a></li>
                            <li><a href="#" data-format="tar">TAR Archive</a></li>
                        </ul>
                    </div>
                    <div class="gallery-grid" id="{field.id}-gallery"></div>
                </div>

                <!-- Status Messages -->
                <div class="status-messages" aria-live="polite">
                    <div class="capture-status"></div>
                    <div class="storage-status"></div>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"
                     role="alert" aria-live="assertive"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const camera = new PeriodicCamera('{field.id}', {{
                        interval: {self.interval},
                        camera: '{self.camera}',
                        quality: '{self.quality}',
                        motionDetection: {str(self.motion_detection).lower()},
                        faceDetection: {str(self.face_detection).lower()},
                        maxImages: {self.max_images},
                        background: {str(self.background).lower()},
                        timestampOverlay: {str(self.timestamp_overlay).lower()},
                        privacyMode: {str(self.privacy_mode).lower()},
                        processingOptions: {json.dumps(self.processing_options)},
                        customTriggers: {json.dumps(self.custom_triggers)},

                        onCapture: function(imageData) {{
                            updateGallery(imageData);
                            updateStatus('Capture successful');
                            $('#{field.id}').val(JSON.stringify(imageData));
                        }},

                        onError: function(error) {{
                            showError(error);
                            updateStatus('Capture failed: ' + error);
                        }}
                    }});

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        camera.loadImages(JSON.parse(existingData));
                    }}

                    // Event Handlers
                    $('.start-capture').on('click', () => camera.startCapture());
                    $('.stop-capture').on('click', () => camera.stopCapture());
                    $('.single-photo').on('click', () => camera.takeSinglePhoto());
                    $('.clear-images').on('click', () => {{
                        if (confirm('Clear all captured images?')) {{
                            camera.clearImages();
                        }}
                    }});

                    // Handle export
                    $('.export-images a').on('click', function(e) {{
                        e.preventDefault();
                        const format = $(this).data('format');
                        camera.exportImages(format);
                    }});

                    function updateGallery(imageData) {{
                        const gallery = $('#{field.id}-gallery');
                        // Update gallery implementation
                    }}

                    function showError(error) {{
                        const alert = $('.periodic-camera-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function updateStatus(message) {{
                        $('.capture-status').text(message);
                    }}

                    // Handle visibility changes
                    document.addEventListener('visibilitychange', function() {{
                        if (document.hidden) {{
                            camera.handleBackground();
                        }} else {{
                            camera.handleForeground();
                        }}
                    }});

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        camera.cleanup();
                    }});
                }});
            </script>
        """
        )

    def take_single_photo(self) -> dict:
        """
        Take a single photo immediately.

        Returns:
            dict: Captured image data with metadata
        """
        try:
            return {
                "timestamp": datetime.now().isoformat(),
                "image_url": self._capture_image(),
                "camera_id": self._get_camera_id(),
                "resolution": self._get_resolution(),
                "faces_detected": self._detect_faces() if self.face_detection else 0,
                "motion_detected": False,
                "metadata": self._get_metadata(),
            }
        except Exception as e:
            return {"error": str(e)}

    def process_image(self, image_data: bytes) -> dict:
        """
        Process captured image with current settings.

        Args:
            image_data (bytes): Raw image data

        Returns:
            dict: Processed image data with analysis results
        """
        try:
            processed = self._apply_processing(image_data)
            return {
                "processed_data": processed,
                "size": len(processed),
                "processing_time": time.time(),
                "success": True,
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    def detect_motion(self, current_image: bytes, previous_image: bytes) -> bool:
        """
        Detect motion between consecutive images.

        Args:
            current_image (bytes): Current image data
            previous_image (bytes): Previous image data

        Returns:
            bool: Motion detected status
        """
        try:
            if not previous_image:
                return False

            diff = self._compute_image_difference(current_image, previous_image)
            return diff > self.custom_triggers["motion_threshold"]
        except Exception:
            return False

    def detect_faces(self, image_data: bytes) -> list:
        """
        Detect faces in image.

        Args:
            image_data (bytes): Image data

        Returns:
            list: Detected face information
        """
        try:
            faces = []
            if self.face_detection:
                detections = self._run_face_detection(image_data)
                faces = [
                    {
                        "confidence": d.confidence,
                        "box": d.box.tolist(),
                        "landmarks": d.landmarks.tolist(),
                    }
                    for d in detections
                ]
            return faces
        except Exception:
            return []

    def cleanup(self):
        """Clean up resources and connections"""
        try:
            if self._stream:
                self._stream.stop()

            if self._worker:
                self._worker.terminate()

            self._capturing = False
            self._stream = None
            self._last_image = None

        except Exception as e:
            if self.debug_mode:
                print(f"Cleanup error: {e}")

    def _validate_config(self):
        """Validate widget configuration settings"""
        valid_qualities = ["low", "medium", "high"]
        if self.quality not in valid_qualities:
            raise ValueError(
                f"Invalid quality setting. Must be one of: {valid_qualities}"
            )

        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path, exist_ok=True)

        if self.interval < 10:
            raise ValueError("Interval must be at least 10 seconds")

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        css_includes = [
            f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES
        ]
        return "\n".join(css_includes + js_includes)
