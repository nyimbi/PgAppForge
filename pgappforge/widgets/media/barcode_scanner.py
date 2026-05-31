"""BarcodeQRScannerWidget — PgAppForge widget(s)."""

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
                        formats: {_js_json(self.formats)},
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
