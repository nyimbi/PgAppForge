"""GeographicHeatmapWidget — PgAppForge widget(s)."""

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

class GeographicHeatmapWidget(BS3TextFieldWidget):
    """
    Interactive geographic heatmap widget for visualizing data density and patterns.

    Features:
    - Multiple map providers with fallbacks
    - Custom color gradients with validation
    - Real-time data updates via WebSocket
    - Time-series animation with playback controls
    - Custom overlay layers and controls
    - Interactive legend with filtering
    - Dynamic zoom levels with minimap
    - Advanced data filtering and aggregation
    - Multiple export formats (PNG, SVG, PDF)
    - Marker clustering with custom thresholds
    - Rich tooltips with custom templates
    - Full mobile and touch support
    - Offline mode with data caching
    - GeoJSON boundary support
    - Built-in analytics tracking

    Database Type:
        PostgreSQL: JSONB for storing point data and configuration
        SQLAlchemy: JSON type with GiST index

    Map Providers:
    - OpenStreetMap (default)
    - Google Maps
    - MapBox
    - Here Maps
    - Carto
    - Custom tile servers
    - Fallback providers

    Required Dependencies:
    - Leaflet.js >= 1.7.0
    - Leaflet.heat >= 0.2.0
    - D3.js >= 7.0.0
    - Turf.js >= 6.5.0
    - HTML2Canvas >= 1.4.0

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47
    - iOS Safari >= 12
    - Chrome for Android >= 60

    Required Permissions:
    - Geolocation (optional)
    - LocalStorage (caching)
    - WebGL (enhanced rendering)
    - WebWorkers (data processing)

    Performance Considerations:
    - Use WebWorkers for data processing
    - Enable clustering for large datasets
    - Cache tiles and data
    - Throttle update frequency
    - Optimize marker rendering
    - Lazy load data chunks

    Security:
    - Validate data sources
    - Sanitize popup content
    - Rate limit updates
    - Scope localStorage access
    - Clean exported data
    - XSS prevention in tooltips

    Example:
        heatmap = db.Column(db.JSON,
            info={'widget': GeographicHeatmapWidget(
                provider='osm',
                gradient=['#313695', '#4575B4', '#74ADD1', '#ABD9E9',
                         '#E0F3F8', '#FFFFBF', '#FEE090', '#FDAE61',
                         '#F46D43', '#D73027', '#A50026'],
                radius=30,
                animate=True,
                cluster=True,
                max_points=50000,
                update_interval=1000,
                offline_support=True
            )}
        )
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
        "https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js",
        "https://d3js.org/d3.v7.min.js",
        "https://unpkg.com/@turf/turf@6.5.0/turf.min.js",
        "https://unpkg.com/html2canvas@1.4.1/dist/html2canvas.min.js",
        "/static/js/heatmap-widget.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        "/static/css/heatmap-widget.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize GeographicHeatmapWidget with custom settings.

        Args:
            provider (str): Map provider ('osm', 'google', 'mapbox', 'here', 'custom')
            gradient (list): Color gradient stops for heatmap
            radius (int): Heat point radius in pixels (10-50)
            animate (bool): Enable time-series animation
            cluster (bool): Enable point clustering
            max_zoom (int): Maximum zoom level (1-22)
            min_zoom (int): Minimum zoom level (1-18)
            opacity (float): Heatmap opacity (0-1)
            legend (dict): Legend configuration and styling
            boundaries (dict): GeoJSON boundary definitions
            time_window (int): Animation time window in seconds
            custom_styles (dict): Custom map and control styles
            max_points (int): Maximum number of points to render
            update_interval (int): Data update interval in ms
            offline_support (bool): Enable offline support
            cache_tiles (bool): Enable tile caching
            worker_threads (int): Number of WebWorker threads
            debug_mode (bool): Enable debug logging
            api_keys (dict): Provider API keys
        """
        super().__init__(**kwargs)

        # Core Settings
        self.provider = kwargs.get("provider", "osm")
        self.gradient = kwargs.get(
            "gradient",
            [
                "#313695",
                "#4575B4",
                "#74ADD1",
                "#ABD9E9",
                "#E0F3F8",
                "#FFFFBF",
                "#FEE090",
                "#FDAE61",
                "#F46D43",
                "#D73027",
                "#A50026",
            ],
        )
        self.radius = min(50, max(10, kwargs.get("radius", 25)))
        self.animate = kwargs.get("animate", False)
        self.cluster = kwargs.get("cluster", False)
        self.max_zoom = min(22, max(1, kwargs.get("max_zoom", 18)))
        self.min_zoom = min(18, max(1, kwargs.get("min_zoom", 2)))
        self.opacity = min(1.0, max(0.1, kwargs.get("opacity", 0.6)))

        # Advanced Features
        self.legend = kwargs.get("legend", {"position": "bottomright"})
        self.boundaries = kwargs.get("boundaries", {})
        self.time_window = kwargs.get("time_window", 3600)
        self.custom_styles = kwargs.get("custom_styles", {})
        self.max_points = kwargs.get("max_points", 50000)
        self.update_interval = max(100, kwargs.get("update_interval", 1000))

        # Technical Settings
        self.offline_support = kwargs.get("offline_support", False)
        self.cache_tiles = kwargs.get("cache_tiles", True)
        self.worker_threads = min(16, max(1, kwargs.get("worker_threads", 4)))
        self.debug_mode = kwargs.get("debug_mode", False)
        self.api_keys = kwargs.get("api_keys", {})

        # Internal State
        self._data_cache = {}
        self._worker_pool = None
        self._bounds = None

        # Validate settings
        self._validate_config()
        self._initialize_workers()

    def render_field(self, field, **kwargs):
        """Render the heatmap widget with controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="geographic-heatmap-widget" id="{field.id}-container">
                <!-- Map Container -->
                <div class="map-container">
                    <div id="{field.id}-map" class="heatmap"></div>
                    <div class="map-controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out">-</button>
                        <button class="btn btn-sm btn-default reset-view"
                                title="Reset View">Reset</button>
                    </div>
                </div>

                <!-- Toolbar -->
                <div class="heatmap-toolbar">
                    {self._render_toolbar(field.id)}
                </div>

                <!-- Animation Controls -->
                {self._render_animation_controls(field.id) if self.animate else ''}

                <!-- Status Bar -->
                <div class="status-bar">
                    <span class="point-count"></span>
                    <span class="zoom-level"></span>
                    <span class="coordinates"></span>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading map data...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"
                     role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const heatmap = new HeatmapWidget('{field.id}', {{
                        provider: '{self.provider}',
                        gradient: {_js_json(self.gradient)},
                        radius: {self.radius},
                        animate: {str(self.animate).lower()},
                        cluster: {str(self.cluster).lower()},
                        maxZoom: {self.max_zoom},
                        minZoom: {self.min_zoom},
                        opacity: {self.opacity},
                        legend: {_js_json(self.legend)},
                        boundaries: {_js_json(self.boundaries)},
                        timeWindow: {self.time_window},
                        customStyles: {_js_json(self.custom_styles)},
                        maxPoints: {self.max_points},
                        updateInterval: {self.update_interval},
                        offlineSupport: {str(self.offline_support).lower()},
                        cacheTiles: {str(self.cache_tiles).lower()},
                        workerThreads: {self.worker_threads},
                        debugMode: {str(self.debug_mode).lower()},
                        apiKeys: {_js_json(self.api_keys)},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                            updateStatus(data);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.geographic-heatmap-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    function updateStatus(data) {{
                        $('.point-count').text(`Points: ${{data.points.length}}`);
                        $('.zoom-level').text(`Zoom: ${{data.zoom}}`);
                        if (data.center) {{
                            $('.coordinates').text(
                                `Lat: ${{data.center.lat.toFixed(4)}} ` +
                                `Lng: ${{data.center.lng.toFixed(4)}}`
                            );
                        }}
                    }}

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        heatmap.setData(JSON.parse(existingData));
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        heatmap.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _validate_config(self):
        """Validate widget configuration settings"""
        # Validate provider
        valid_providers = ["osm", "google", "mapbox", "here", "carto", "custom"]
        if self.provider not in valid_providers:
            raise ValueError(
                f"Invalid provider. Must be one of: {', '.join(valid_providers)}"
            )

        # Validate gradient colors
        if not all(
            re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", color) for color in self.gradient
        ):
            raise ValueError(
                "Invalid gradient colors. Must be hex colors (#RGB or #RRGGBB)"
            )

        # Validate API keys
        if self.provider != "osm" and not self.api_keys.get(self.provider):
            raise ValueError(f"API key required for {self.provider}")

        # Validate numeric ranges
        if not 10 <= self.radius <= 50:
            raise ValueError("radius must be between 10 and 50")

        if not 1 <= self.min_zoom <= self.max_zoom <= 22:
            raise ValueError("Invalid zoom range")

        if not 0.1 <= self.opacity <= 1.0:
            raise ValueError("opacity must be between 0.1 and 1.0")

    def _initialize_workers(self):
        """Initialize WebWorker pool for data processing"""
        if not self.worker_threads:
            return

        try:
            from concurrent.futures import ThreadPoolExecutor

            self._worker_pool = ThreadPoolExecutor(max_workers=self.worker_threads)
        except Exception as e:
            if self.debug_mode:
                raise
            self.worker_threads = 0
            self._worker_pool = None

    def process_points(self, points: list) -> dict:
        """
        Process and validate point data for heatmap.

        Args:
            points: List of [lat, lng, intensity] points

        Returns:
            dict: Processed point data with validation status
        """
        try:
            # Basic validation
            if not points or not isinstance(points, list):
                raise ValueError("Invalid point data")

            if len(points) > self.max_points:
                points = points[: self.max_points]

            # Validate each point
            valid_points = []
            for point in points:
                if len(point) not in (2, 3):
                    continue

                lat, lng = point[:2]
                intensity = point[2] if len(point) == 3 else 1.0

                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    continue

                valid_points.append([lat, lng, max(0, min(1, intensity))])

            return {
                "points": valid_points,
                "count": len(valid_points),
                "truncated": len(points) > self.max_points,
            }

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def cleanup(self):
        """Clean up resources and worker threads"""
        try:
            if self._worker_pool:
                self._worker_pool.shutdown(wait=True)
                self._worker_pool = None

            self._data_cache.clear()

        except Exception as e:
            if self.debug_mode:
                raise
