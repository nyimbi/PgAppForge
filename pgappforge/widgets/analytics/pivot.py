"""PivotTableWidget — PgAppForge widget(s)."""

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
                        rows: {_js_json(self.rows)},
                        cols: {_js_json(self.cols)},
                        aggregator: '{self.aggregator}',
                        renderer: '{self.renderer}',
                        filters: {_js_json(self.filters)},
                        sorters: {_js_json(self.sorters)},
                        savedViews: {_js_json(self.saved_views)},
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
