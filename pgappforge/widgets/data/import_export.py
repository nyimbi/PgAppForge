"""DataImportExportWidget — PgAppForge widget(s)."""

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
                        formats: {_js_json(self.formats)},
                        validate: {str(self.validate).lower()},
                        templates: {str(self.templates).lower()},
                        batchSize: {self.batch_size},
                        mappings: {_js_json(self.mappings)},
                        transformations: {_js_json(self.transformations)},
                        errorThreshold: {self.error_threshold},
                        previewRows: {self.preview_rows},
                        allowSchedule: {str(self.allow_schedule).lower()},
                        trackHistory: {str(self.track_history).lower()},
                        cacheTemplates: {str(self.cache_templates).lower()},
                        socketUrl: '{self.socket_url}',
                        customValidators: {_js_json(self.custom_validators)},
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
