"""MapWidget — PgAppForge widget(s)."""

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

class MapWidget(BS3TextFieldWidget):
    """
    Interactive map widget using Leaflet/OpenLayers for geographical data visualization and editing.

    Features:
    - Multiple base layer support (OpenStreetMap, Google Maps, etc.)
    - Marker management (add, edit, delete)
    - Polygon/polyline drawing tools
    - GeoJSON import/export
    - Clustering for large datasets
    - Custom marker icons
    - Tooltips and popups
    - Layer controls
    - Search/geocoding
    - Distance measurement
    - Area calculation
    - Mobile touch support
    - Offline caching
    - Custom map controls
    - Multi-language support

    Database Type:
        PostgreSQL: GEOMETRY or GEOGRAPHY with PostGIS extension
        SQLAlchemy: Geometry(geometry_type='GEOMETRY', srid=4326)

    Required Dependencies:
    - Leaflet.js 1.7+
    - Leaflet.draw 1.0+
    - Leaflet.markercluster 1.5+
    - Leaflet.measure
    - Leaflet.offline
    - Leaflet.locatecontrol
    - Turf.js for calculations

    Browser Support:
    - Chrome 49+
    - Firefox 52+
    - Safari 11+
    - Edge 79+
    - Opera 36+
    - iOS Safari 10+
    - Chrome for Android 89+

    Required Permissions:
    - Geolocation access
    - Local storage for offline support
    - File system for GeoJSON import/export

    Performance Considerations:
    - Large datasets should use clustering
    - Limit concurrent markers (<1000 recommended)
    - Cache map tiles for offline use
    - Use vector tiles for better performance
    - Throttle continuous updates
    - Optimize marker icons

    Security Implications:
    - Validate GeoJSON input
    - Sanitize popup content
    - Restrict zoom levels for sensitive locations
    - Consider privacy of location data
    - Use HTTPS for tile servers
    - Implement access controls

    Best Practices:
    - Enable clustering for >100 markers
    - Cache map data when offline support needed
    - Use vector tiles when available
    - Compress GeoJSON data
    - Set reasonable zoom restrictions
    - Include fallback tile servers
    - Implement proper error handling

    Common Issues:
    - Map not displaying: Check HTTPS/permissions
    - Markers not clustering: Verify threshold settings
    - Slow performance: Enable clustering/limit markers
    - Offline mode fails: Check storage quota
    - Geolocation error: Check browser permissions
    - Drawing tools not working: Verify dependencies

    Example:
        location_map = StringField('Location',
                                 widget=MapWidget(
                                     provider='leaflet',
                                     center=[0, 0],
                                     zoom=2,
                                     draw_tools=True,
                                     cluster_markers=True,
                                     geocoding=True,
                                     offline_support=True
                                 ))
    """

    # JavaScript/CSS dependencies
    JS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
        "https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js",
        "https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js",
        "https://unpkg.com/leaflet.locatecontrol@0.74.0/dist/L.Control.Locate.min.js",
        "https://unpkg.com/leaflet-measure@2.1.7/dist/leaflet-measure.js",
        "https://unpkg.com/@turf/turf@6.5.0/turf.min.js",
        "https://unpkg.com/leaflet-offline@1.1.0/dist/leaflet-offline.min.js",
    ]

    CSS_DEPENDENCIES = [
        "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        "https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css",
        "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css",
        "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css",
        "https://unpkg.com/leaflet.locatecontrol@0.74.0/dist/L.Control.Locate.min.css",
        "https://unpkg.com/leaflet-measure@2.1.7/dist/leaflet-measure.css",
    ]

    # Default settings
    DEFAULT_CENTER = [0, 0]
    DEFAULT_ZOOM = 2
    MAX_MARKERS = 1000
    CLUSTER_THRESHOLD = 100
    DRAW_TYPES = ["marker", "circle", "rectangle", "polygon", "polyline"]

    def __init__(self, **kwargs):
        """
        Initialize MapWidget with custom settings.

        Args:
            provider (str): Map provider ('leaflet' or 'openlayers')
            center (list): Initial map center coordinates [lat, lng]
            zoom (int): Initial zoom level
            draw_tools (bool): Enable drawing tools
            cluster_markers (bool): Enable marker clustering
            geocoding (bool): Enable geocoding/search
            max_markers (int): Maximum number of markers allowed
            layers (list): List of additional map layers
            draw_types (list): Enabled drawing types
            custom_icons (dict): Custom marker icon definitions
            offline_support (bool): Enable offline support
            locate_control (bool): Enable location control
            measure_control (bool): Enable measurement tools
            min_zoom (int): Minimum zoom level
            max_zoom (int): Maximum zoom level
            cluster_threshold (int): Minimum markers for clustering
            tile_layer (str): Custom tile layer URL
            attribution (str): Map attribution text
            language (str): Interface language
        """
        super().__init__(**kwargs)
        self.provider = kwargs.get("provider", "leaflet")
        self.center = kwargs.get("center", self.DEFAULT_CENTER)
        self.zoom = kwargs.get("zoom", self.DEFAULT_ZOOM)
        self.draw_tools = kwargs.get("draw_tools", False)
        self.cluster_markers = kwargs.get("cluster_markers", True)
        self.geocoding = kwargs.get("geocoding", False)
        self.max_markers = kwargs.get("max_markers", self.MAX_MARKERS)
        self.layers = kwargs.get("layers", [])
        self.draw_types = kwargs.get("draw_types", self.DRAW_TYPES)
        self.custom_icons = kwargs.get("custom_icons", {})
        self.offline_support = kwargs.get("offline_support", False)
        self.locate_control = kwargs.get("locate_control", True)
        self.measure_control = kwargs.get("measure_control", True)
        self.min_zoom = kwargs.get("min_zoom", 0)
        self.max_zoom = kwargs.get("max_zoom", 18)
        self.cluster_threshold = kwargs.get("cluster_threshold", self.CLUSTER_THRESHOLD)
        self.tile_layer = kwargs.get(
            "tile_layer", "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        )
        self.attribution = kwargs.get("attribution", "© OpenStreetMap contributors")
        self.language = kwargs.get("language", "en")

    def render_field(self, field: Any, **kwargs) -> str:
        """Render the map widget"""
        kwargs.setdefault("type", "hidden")
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}
            <div class="map-widget" role="application" aria-label="Interactive Map">
                <div id="{field.id}-map" class="map-container"
                     style="height:400px;width:100%;"
                     data-center="{_js_json(self.center)}"
                     data-zoom="{self.zoom}"></div>
                {input_html}
                <div class="map-loading" role="status" aria-label="Loading map..."
                     style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading map...</span>
                </div>
                <div class="map-error alert alert-danger" role="alert"
                     style="display:none;"></div>
            </div>
            <script>
                $(document).ready(function() {{
                    try {{
                        const map = initializeMap('{field.id}', {{
                            provider: '{self.provider}',
                            center: {_js_json(self.center)},
                            zoom: {self.zoom},
                            drawTools: {str(self.draw_tools).lower()},
                            clusterMarkers: {str(self.cluster_markers).lower()},
                            geocoding: {str(self.geocoding).lower()},
                            maxMarkers: {self.max_markers},
                            layers: {_js_json(self.layers)},
                            drawTypes: {_js_json(self.draw_types)},
                            customIcons: {_js_json(self.custom_icons)},
                            offlineSupport: {str(self.offline_support).lower()},
                            locateControl: {str(self.locate_control).lower()},
                            measureControl: {str(self.measure_control).lower()},
                            minZoom: {self.min_zoom},
                            maxZoom: {self.max_zoom},
                            clusterThreshold: {self.cluster_threshold},
                            tileLayer: '{self.tile_layer}',
                            attribution: '{self.attribution}',
                            language: '{self.language}'
                        }});

                        // Handle map events
                        map.on('draw:created', function(e) {{
                            handleDrawCreated(e, '{field.id}');
                        }});

                        map.on('moveend', function() {{
                            handleMapMove(map, '{field.id}');
                        }});

                        // Initialize features if data exists
                        const existingData = $('#{field.id}').val();
                        if (existingData) {{
                            loadMapData(map, JSON.parse(existingData));
                        }}

                        // Error handling
                        map.on('error', function(e) {{
                            showMapError('{field.id}', e.message);
                        }});

                        // Accessibility
                        enableMapAccessibility('{field.id}-map');

                        // Mobile optimization
                        optimizeForMobile(map);

                        // Offline support
                        if ({str(self.offline_support).lower()}) {{
                            initializeOfflineSupport(map);
                        }}

                    }} catch (error) {{
                        console.error('Map initialization error:', error);
                        showMapError('{field.id}', 'Failed to initialize map');
                    }}
                }});
            </script>
        """
        )

    def _include_dependencies(self) -> str:
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{css_includes}\n{js_includes}"

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_geo_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid GeoJSON format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_geo_data(self, data):
        """Validate GeoJSON data"""
        if not isinstance(data, dict):
            raise ValueError("Invalid GeoJSON structure")

        # Validate GeoJSON type
        if "type" not in data:
            raise ValueError("Missing GeoJSON type")

        # Validate coordinates
        if "coordinates" not in data:
            raise ValueError("Missing coordinates")

        # Validate feature properties
        if data.get("type") == "Feature" and "properties" not in data:
            raise ValueError("Missing feature properties")

        # Validate coordinate bounds
        self._validate_coordinates(data.get("coordinates", []))

    def _validate_coordinates(self, coords):
        """Validate coordinate values"""
        if isinstance(coords, (list, tuple)):
            if len(coords) == 2:
                lat, lng = coords
                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    raise ValueError("Invalid coordinate values")
            else:
                for coord in coords:
                    self._validate_coordinates(coord)

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_geo_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))
