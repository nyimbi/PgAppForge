"""DataPreviewProfilerWidget — PgAppForge widget(s)."""

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
                        metrics: {_js_json(self.metrics)},
                        visualizations: {_js_json(self.visualizations)},
                        exportFormats: {_js_json(self.export_formats)},
                        customMetrics: {_js_json(self.custom_metrics)},
                        thresholdRules: {_js_json(self.threshold_rules)},
                        visualizationOptions: {_js_json(self.visualization_options)},
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
