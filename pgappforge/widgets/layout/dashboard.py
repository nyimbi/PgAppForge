"""DashboardDesignerWidget — PgAppForge widget(s)."""

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
