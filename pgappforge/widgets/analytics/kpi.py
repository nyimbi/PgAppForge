"""KPIDashboardWidget — PgAppForge widget(s)."""

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
                        metrics: {_js_json(self.metrics)},
                        refreshRate: {self.refresh_rate},
                        layout: '{self.layout}',
                        alerts: {str(self.alerts).lower()},
                        comparisonPeriod: '{self.comparison_period}',
                        thresholds: {_js_json(self.thresholds)},
                        dataSources: {_js_json(self.data_sources)},
                        theme: '{self.theme}',
                        cacheEnabled: {str(self.cache_enabled).lower()},
                        exportEnabled: {str(self.export_enabled).lower()},
                        chartDefaults: {_js_json(self.chart_defaults)},
                        gridConfig: {_js_json(self.grid_config)},
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
