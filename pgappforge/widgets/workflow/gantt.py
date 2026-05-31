"""GanttChartWidget — PgAppForge widget(s)."""

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
