"""PeriodicCameraWidget — PgAppForge widget(s)."""

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
                        processingOptions: {_js_json(self.processing_options)},
                        customTriggers: {_js_json(self.custom_triggers)},

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
