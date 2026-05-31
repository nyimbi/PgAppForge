"""KanbanBoardWidget — PgAppForge widget(s)."""

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
                        columns: {_js_json(self.columns)},
                        swimlanes: {_js_json(self.swimlanes)},
                        wipLimits: {_js_json(self.wip_limits)},
                        cardTypes: {_js_json(self.card_types)},
                        labels: {_js_json(self.labels)},
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
