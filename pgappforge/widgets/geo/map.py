"""MapWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape
from wtforms.validators import ValidationError


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
		    placeholder (str): Not used for map widget; accepted for API consistency
		    css_class (str): Additional CSS classes on the container
		    description (str): Help text rendered below the widget
		    readonly (bool): Render map in read-only/display mode
		    disabled (bool): Disable the hidden input
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
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

	def __call__(self, field, **kwargs):
		"""Render the map widget."""
		has_errors = bool(field.errors)

		# Hidden input carries the serialised GeoJSON value
		from wtforms.widgets import html_params
		hidden_extra: dict[str, Any] = {}
		if has_errors:
			hidden_extra["aria-invalid"] = "true"
		if self.disabled:
			hidden_extra["disabled"] = True
		input_html = f'<input {html_params(type="hidden", id=field.id, name=field.name, value=field.data or "", **hidden_extra)}>'

		container_class = "map-widget"
		if self.css_class:
			container_class += " " + self.css_class

		label_text = str(field.label.text) if field.label else "Map"

		html = f"""
{self._include_dependencies()}
<div class="{escape(container_class)}" role="application" aria-label="{escape(label_text)}">
  <div id="{field.id}-map" class="map-container"
       style="height:400px;width:100%;max-width:100%;touch-action:pan-y;"
       aria-label="{escape(label_text)} interactive map"
       data-center="{escape(str(_js_json(self.center)))}"
       data-zoom="{int(self.zoom)}"></div>
  {input_html}
  <div class="map-loading" role="status" aria-label="Loading map..." style="display:none;">
    <div class="spinner"></div>
    <span class="visually-hidden">Loading map...</span>
  </div>
  <div class="map-error alert alert-danger" role="alert" aria-live="assertive" style="display:none;"></div>
"""

		if self.description:
			html += f'  <small class="form-text text-muted" id="{field.id}_help">{escape(self.description)}</small>\n'

		if has_errors:
			errors_html = " ".join(str(escape(e)) for e in field.errors)
			html += f'  <div class="invalid-feedback d-block" id="{field.id}_error">{errors_html}</div>\n'

		html += "</div>\n"

		# All string constructor values go through _js_json to prevent JS injection
		script = """
<script>
$(document).ready(function() {{
    try {{
        var fieldId = {field_id_js};
        var map = initializeMap(fieldId, {{
            provider: {provider_js},
            center: {center_js},
            zoom: {zoom},
            drawTools: {draw_tools},
            clusterMarkers: {cluster_markers},
            geocoding: {geocoding},
            maxMarkers: {max_markers},
            layers: {layers_js},
            drawTypes: {draw_types_js},
            customIcons: {custom_icons_js},
            offlineSupport: {offline_support},
            locateControl: {locate_control},
            measureControl: {measure_control},
            minZoom: {min_zoom},
            maxZoom: {max_zoom},
            clusterThreshold: {cluster_threshold},
            tileLayer: {tile_layer_js},
            attribution: {attribution_js},
            language: {language_js}
        }});

        map.on('draw:created', function(e) {{
            handleDrawCreated(e, fieldId);
        }});

        map.on('moveend', function() {{
            handleMapMove(map, fieldId);
        }});

        var existingData = document.getElementById(fieldId).value;
        if (existingData) {{
            try {{
                loadMapData(map, JSON.parse(existingData));
            }} catch (parseErr) {{
                console.warn('MapWidget: could not parse existing data', parseErr);
            }}
        }}

        map.on('error', function(e) {{
            showMapError(fieldId, e.message);
        }});

        enableMapAccessibility(fieldId + '-map');
        optimizeForMobile(map);

        if ({offline_support}) {{
            initializeOfflineSupport(map);
        }}

    }} catch (error) {{
        console.error('Map initialization error:', error);
        var errEl = document.querySelector('#' + {field_id_js} + '-map')
            .closest('.map-widget').querySelector('.map-error');
        if (errEl) {{
            errEl.textContent = 'Failed to initialize map: ' + error.message;
            errEl.style.display = '';
        }}
    }}
}});
</script>
""".format(
			field_id_js=_js_json(field.id),
			provider_js=_js_json(self.provider),
			center_js=_js_json(self.center),
			zoom=int(self.zoom),
			draw_tools=str(self.draw_tools).lower(),
			cluster_markers=str(self.cluster_markers).lower(),
			geocoding=str(self.geocoding).lower(),
			max_markers=int(self.max_markers),
			layers_js=_js_json(self.layers),
			draw_types_js=_js_json(self.draw_types),
			custom_icons_js=_js_json(self.custom_icons),
			offline_support=str(self.offline_support).lower(),
			locate_control=str(self.locate_control).lower(),
			measure_control=str(self.measure_control).lower(),
			min_zoom=int(self.min_zoom),
			max_zoom=int(self.max_zoom),
			cluster_threshold=int(self.cluster_threshold),
			tile_layer_js=_js_json(self.tile_layer),
			attribution_js=_js_json(self.attribution),
			language_js=_js_json(self.language),
		)

		return Markup(html + script)

	def _include_dependencies(self) -> str:
		"""Include required JavaScript and CSS dependencies."""
		js_includes = "\n".join(
			[f'<script src="{escape(url)}"></script>' for url in self.JS_DEPENDENCIES]
		)
		css_includes = "\n".join(
			[f'<link rel="stylesheet" href="{escape(url)}">' for url in self.CSS_DEPENDENCIES]
		)
		return f"{css_includes}\n{js_includes}"

	def process_formdata(self, valuelist):
		"""Process form data to database format."""
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
		"""Validate GeoJSON data."""
		if not isinstance(data, dict):
			raise ValueError("Invalid GeoJSON structure")

		if "type" not in data:
			raise ValueError("Missing GeoJSON type")

		if "coordinates" not in data:
			raise ValueError("Missing coordinates")

		if data.get("type") == "Feature" and "properties" not in data:
			raise ValueError("Missing feature properties")

		self._validate_coordinates(data.get("coordinates", []))

	def _validate_coordinates(self, coords):
		"""Validate coordinate values."""
		if isinstance(coords, (list, tuple)):
			if len(coords) == 2:
				lat, lng = coords
				if not (-90 <= lat <= 90 and -180 <= lng <= 180):
					raise ValueError("Invalid coordinate values")
			else:
				for coord in coords:
					self._validate_coordinates(coord)

	def pre_validate(self, form):
		"""Validate before form processing."""
		if self.data is not None:
			try:
				self._validate_geo_data(self.data)
			except ValueError as e:
				raise ValueError(str(e))
