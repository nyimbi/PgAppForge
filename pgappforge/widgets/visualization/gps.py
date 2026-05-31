"""GPSTrackerWidget — PgAppForge widget(s)."""

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

class GPSTrackerWidget(BS3TextFieldWidget):
    """
    GPS tracking widget that periodically collects and stores location data with timestamps.
    Designed for PgAppForge with PostgreSQL JSONB storage.

    Features:
    - Periodic location tracking with configurable intervals
    - High accuracy mode with battery optimization
    - Offline storage with IndexedDB/LocalStorage
    - Interactive track visualization with heatmaps
    - Geofencing with customizable boundaries
    - Motion detection and activity recognition
    - Background tracking support
    - Battery status monitoring with adaptive intervals
    - Location clustering for large datasets
    - Export to multiple formats (JSON, GPX, KML)
    - Privacy controls with data anonymization
    - Comprehensive error handling
    - Usage analytics and diagnostics
    - Custom trigger support
    - Full accessibility support
    - Responsive mobile design

    Storage Format (PostgreSQL JSONB):
    {
        "tracks": [
            {
                "timestamp": "2024-01-01T12:00:00Z",
                "latitude": 0.0,
                "longitude": 0.0,
                "accuracy": 10.0,
                "altitude": 100.0,
                "speed": 0.0,
                "heading": 90.0,
                "battery": 85,
                "motion": "stationary",
                "provider": "gps"
            }
        ],
        "metadata": {
            "start_time": "2024-01-01T00:00:00Z",
            "device_id": "unique_device_id",
            "app_version": "1.0.0",
            "settings": {}
        }
    }

    Browser Compatibility:
    - Chrome >= 50
    - Firefox >= 55
    - Safari >= 11
    - Edge >= 79
    - Opera >= 37
    - Chrome for Android >= 50
    - Safari iOS >= 11

    Required Permissions:
    - geolocation
    - background-fetch
    - persistent-storage
    - wake-lock
    - device-orientation

    Performance Considerations:
    - Use requestIdleCallback for background processing
    - Implement adaptive tracking intervals
    - Batch location updates
    - Use IndexedDB for offline storage
    - Optimize battery usage with geofencing
    - Implement data pruning

    Security Implications:
    - Location data encryption at rest
    - Secure transmission over SSL/TLS
    - Data anonymization options
    - Access control implementation
    - Geofence data protection
    - Export data sanitization

    Required Dependencies:
    - Geolocation API
    - LocalStorage/IndexedDB
    - Background Tasks API
    - Leaflet.js for visualization
    - Turf.js for geofencing
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet.heat/0.2.0/leaflet-heat.js",
        "https://npmcdn.com/@turf/turf@6.5.0/turf.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
        "/static/js/gps-tracker.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        "/static/css/gps-tracker.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize GPSTrackerWidget with custom settings.

        Args:
            interval (int): Tracking interval in seconds (default: 60)
            high_accuracy (bool): Enable high accuracy mode (default: True)
            battery_optimize (bool): Enable battery optimization (default: True)
            background (bool): Enable background tracking (default: False)
            geofencing (bool): Enable geofencing (default: False)
            max_records (int): Maximum number of records to store (default: 1000)
            distance_filter (float): Minimum distance between updates in meters (default: 10.0)
            motion_detection (bool): Enable motion-based updates (default: True)
            offline_storage (str): Offline storage method (default: 'indexeddb')
            privacy_mode (bool): Enable privacy features (default: False)
            export_formats (list): Available export formats (default: ['json', 'gpx', 'kml'])
            custom_triggers (dict): Custom tracking trigger conditions (default: {})
            debug_mode (bool): Enable debug logging (default: False)
        """
        super().__init__(**kwargs)

        # Core Settings
        self.interval = max(10, min(3600, kwargs.get("interval", 60)))
        self.high_accuracy = kwargs.get("high_accuracy", True)
        self.battery_optimize = kwargs.get("battery_optimize", True)
        self.background = kwargs.get("background", False)
        self.geofencing = kwargs.get("geofencing", False)
        self.max_records = max(100, min(10000, kwargs.get("max_records", 1000)))
        self.distance_filter = max(
            1.0, min(1000.0, kwargs.get("distance_filter", 10.0))
        )
        self.motion_detection = kwargs.get("motion_detection", True)
        self.offline_storage = kwargs.get("offline_storage", "indexeddb")
        self.privacy_mode = kwargs.get("privacy_mode", False)
        self.export_formats = kwargs.get("export_formats", ["json", "gpx", "kml"])
        self.custom_triggers = kwargs.get("custom_triggers", {})
        self.debug_mode = kwargs.get("debug_mode", False)

        # Internal State
        self._tracking = False
        self._last_location = None
        self._watch_id = None
        self._battery_level = None
        self._error_count = 0
        self._offline_queue = []

        # Validate settings
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the GPS tracker widget with controls and map"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="gps-tracker-widget" id="{field.id}-container">
                <!-- Map Container -->
                <div class="map-container">
                    <div id="{field.id}-map" class="tracker-map"
                         role="application" aria-label="Location tracking map"></div>

                    <!-- Map Controls -->
                    <div class="map-controls" role="toolbar"
                         aria-label="Map controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In" aria-label="Zoom in">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out" aria-label="Zoom out">-</button>
                        <button class="btn btn-sm btn-default center-map"
                                title="Center Map" aria-label="Center map">
                            <i class="fa fa-crosshairs"></i>
                        </button>
                    </div>
                </div>

                <!-- Controls -->
                <div class="tracker-controls">
                    <button class="btn btn-primary start-tracking"
                            aria-label="Start tracking">
                        <i class="fa fa-play"></i> Start Tracking
                    </button>
                    <button class="btn btn-danger stop-tracking" disabled
                            aria-label="Stop tracking">
                        <i class="fa fa-stop"></i> Stop
                    </button>
                    <button class="btn btn-default clear-tracks"
                            aria-label="Clear tracks">
                        <i class="fa fa-trash"></i> Clear
                    </button>
                    <div class="btn-group">
                        <button class="btn btn-default dropdown-toggle"
                                data-toggle="dropdown" aria-haspopup="true"
                                aria-expanded="false">
                            Export <span class="caret"></span>
                        </button>
                        <ul class="dropdown-menu">
                            {self._render_export_options()}
                        </ul>
                    </div>
                </div>

                <!-- Status -->
                <div class="tracker-status" aria-live="polite">
                    <span class="status-indicator"></span>
                    <span class="battery-indicator"></span>
                    <span class="accuracy-indicator"></span>
                    <span class="points-count"></span>
                </div>

                <!-- Loading Indicator -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Processing...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"
                     role="alert" aria-live="assertive"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const tracker = new GPSTracker('{field.id}', {{
                        interval: {self.interval},
                        highAccuracy: {str(self.high_accuracy).lower()},
                        batteryOptimize: {str(self.battery_optimize).lower()},
                        background: {str(self.background).lower()},
                        geofencing: {str(self.geofencing).lower()},
                        maxRecords: {self.max_records},
                        distanceFilter: {self.distance_filter},
                        motionDetection: {str(self.motion_detection).lower()},
                        offlineStorage: '{self.offline_storage}',
                        privacyMode: {str(self.privacy_mode).lower()},
                        customTriggers: {_js_json(self.custom_triggers)},
                        debugMode: {str(self.debug_mode).lower()},

                        onLocationUpdate: function(location) {{
                            updateStatus(location);
                            $('#{field.id}').val(JSON.stringify(location));
                        }},

                        onError: function(error) {{
                            showError(error);
                        }},

                        onStateChange: function(tracking) {{
                            updateControls(tracking);
                        }}
                    }});

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        tracker.loadTracks(JSON.parse(existingData));
                    }}

                    // Event Handlers
                    $('.start-tracking').on('click', () => tracker.startTracking());
                    $('.stop-tracking').on('click', () => tracker.stopTracking());
                    $('.clear-tracks').on('click', () => {{
                        if (confirm('Clear all tracked locations?')) {{
                            tracker.clearTracks();
                        }}
                    }});

                    // Status Updates
                    function updateStatus(location) {{
                        $('.status-indicator').text(
                            `Last Update: ${{moment(location.timestamp).fromNow()}}`
                        );
                        $('.battery-indicator').text(
                            `Battery: ${{location.battery}}%`
                        );
                        $('.accuracy-indicator').text(
                            `Accuracy: ${{location.accuracy.toFixed(1)}}m`
                        );
                        $('.points-count').text(
                            `Points: ${{location.tracks.length}}`
                        );
                    }}

                    function showError(error) {{
                        const alert = $('.gps-tracker-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function updateControls(tracking) {{
                        $('.start-tracking').prop('disabled', tracking);
                        $('.stop-tracking').prop('disabled', !tracking);
                    }}

                    // Cleanup
                    window.addEventListener('unload', function() {{
                        tracker.cleanup();
                    }});

                    // Handle visibility changes
                    document.addEventListener('visibilitychange', function() {{
                        if (document.hidden) {{
                            tracker.handleBackground();
                        }} else {{
                            tracker.handleForeground();
                        }}
                    }});
                }});
            </script>
        """
        )

    def get_current_location(self) -> dict:
        """
        Get current location with metadata.

        Returns:
            dict: Current location data with timestamp and metadata
        """
        try:
            if not self._tracking:
                return {"error": "Tracking not active"}

            return {
                "timestamp": datetime.now().isoformat(),
                "latitude": self._last_location.get("latitude"),
                "longitude": self._last_location.get("longitude"),
                "accuracy": self._last_location.get("accuracy"),
                "battery": self._battery_level,
                "tracking": self._tracking,
            }
        except Exception as e:
            return {"error": str(e)}

    def export_tracks(self, format: str) -> str:
        """
        Export tracking data in specified format.

        Args:
            format (str): Export format (json, gpx, kml)

        Returns:
            str: Exported tracking data
        """
        try:
            if format not in self.export_formats:
                return "Unsupported export format"

            if format == "gpx":
                return self._export_gpx()
            elif format == "kml":
                return self._export_kml()
            else:
                return json.dumps(self._data)
        except Exception as e:
            return str(e)

    def check_geofence(self, location: dict) -> list:
        """
        Check if location is within defined geofences.

        Args:
            location (dict): Location to check

        Returns:
            list: Triggered geofence events
        """
        try:
            if not self.geofencing:
                return []

            triggered = []
            point = [location["longitude"], location["latitude"]]

            for fence in self.custom_triggers.get("geofences", []):
                if turf.booleanPointInPolygon(point, fence["polygon"]):
                    triggered.append(
                        {
                            "fence_id": fence["id"],
                            "name": fence["name"],
                            "type": fence["type"],
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

            return triggered
        except Exception as e:
            if self.debug_mode:
                print(f"Geofence error: {e}")
            return []

    def _validate_config(self) -> None:
        """Validate widget configuration settings"""
        if self.interval < 10:
            raise ValueError("Interval must be at least 10 seconds")

        if self.offline_storage not in ["indexeddb", "localstorage"]:
            raise ValueError("Invalid offline storage method")

        for format in self.export_formats:
            if format not in ["json", "gpx", "kml"]:
                raise ValueError(f"Invalid export format: {format}")

    def _include_dependencies(self) -> str:
        """Include required JavaScript and CSS dependencies"""
        js_includes = [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        css_includes = [
            f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES
        ]
        return "\n".join(css_includes + js_includes)

    def _render_export_options(self) -> str:
        """Render export format options"""
        options = []
        for format in self.export_formats:
            options.append(
                f'<li><a href="#" data-format="{format}">'
                f"Export as {format.upper()}</a></li>"
            )
        return "\n".join(options)

    def cleanup(self) -> None:
        """Clean up resources and connections"""
        try:
            if self._watch_id:
                navigator.geolocation.clearWatch(self._watch_id)

            self._tracking = False
            self._watch_id = None
            self._last_location = None

            # Save any queued offline data
            if self._offline_queue:
                self._save_offline_data()

        except Exception as e:
            if self.debug_mode:
                print(f"Cleanup error: {e}")
