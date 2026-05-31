"""QRCodeWidget — PgAppForge widget(s)."""

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
                        logo: {_js_json(self.logo)},
                        style: '{self.style}',
                        colors: {_js_json(self.colors)},
                        margin: {self.margin},
                        downloadOptions: {_js_json(self.download_options)},
                        enableScanner: {str(self.enable_scanner).lower()},
                        templates: {_js_json(self.templates)},
                        analytics: {str(self.analytics).lower()},
                        cacheGenerated: {str(self.cache_generated).lower()},
                        rateLimit: {_js_json(self.rate_limit)},

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
