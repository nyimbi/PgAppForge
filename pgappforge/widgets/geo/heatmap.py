"""GeographicHeatmapWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
import re
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape
from wtforms.widgets import html_params


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
		    css_class (str): Additional CSS classes on the container
		    description (str): Help text rendered below the widget
		    readonly (bool): Display-only mode (no data editing)
		    disabled (bool): Disable the hidden input
		"""
		super().__init__(**kwargs)

		# Core Settings
		self.provider = kwargs.get("provider", "osm")
		self.gradient = kwargs.get(
			"gradient",
			[
				"#313695", "#4575B4", "#74ADD1", "#ABD9E9",
				"#E0F3F8", "#FFFFBF", "#FEE090", "#FDAE61",
				"#F46D43", "#D73027", "#A50026",
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

		# Universal widget kwargs
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

		# Internal State
		self._data_cache: dict = {}
		self._worker_pool = None
		self._bounds = None

		# Validate settings
		self._validate_config()
		self._initialize_workers()

	def __call__(self, field, **kwargs):
		"""Render the heatmap widget with controls."""
		has_errors = bool(field.errors)
		label_text = str(field.label.text) if field.label else str(field.name)

		# Hidden input
		hidden_attrs: dict[str, Any] = {
			"type": "hidden",
			"id": field.id,
			"name": field.name,
			"value": field.data if isinstance(field.data, str) else (json.dumps(field.data) if field.data else ""),
		}
		if has_errors:
			hidden_attrs["aria-invalid"] = "true"
		if self.disabled:
			hidden_attrs["disabled"] = True
		input_html = f"<input {html_params(**hidden_attrs)}>"

		container_class = "geographic-heatmap-widget"
		if self.css_class:
			container_class += " " + self.css_class

		html = f"""
{self._include_dependencies()}
<div class="{escape(container_class)}" id="{field.id}-container">
  <!-- Map Container -->
  <div class="map-container" style="width:100%;max-width:100%;">
    <div id="{field.id}-map" class="heatmap" style="touch-action:pan-y;"
         role="application" aria-label="{escape(label_text)} heatmap"></div>
    <div class="map-controls" role="toolbar" aria-label="Map controls">
      <button class="btn btn-sm btn-secondary zoom-in" type="button"
              title="Zoom In" aria-label="Zoom in">+</button>
      <button class="btn btn-sm btn-secondary zoom-out" type="button"
              title="Zoom Out" aria-label="Zoom out">-</button>
      <button class="btn btn-sm btn-secondary reset-view" type="button"
              title="Reset View" aria-label="Reset map view">Reset</button>
    </div>
  </div>

  <!-- Toolbar -->
  <div class="heatmap-toolbar" role="toolbar" aria-label="Heatmap tools">
    {self._render_toolbar(field.id)}
  </div>

  <!-- Animation Controls -->
  {self._render_animation_controls(field.id) if self.animate else ''}

  <!-- Status Bar -->
  <div class="status-bar" aria-live="polite">
    <span class="point-count"></span>
    <span class="zoom-level"></span>
    <span class="coordinates"></span>
  </div>

  <!-- Loading State -->
  <div class="loading-overlay" style="display:none;" role="status">
    <div class="spinner"></div>
    <span class="visually-hidden">Loading map data...</span>
  </div>

  <!-- Error Messages -->
  <div class="alert alert-danger" style="display:none;"
       role="alert" aria-live="assertive"></div>

  {input_html}
"""

		if self.description:
			html += f'  <small class="form-text text-muted" id="{field.id}_help">{escape(self.description)}</small>\n'

		if has_errors:
			errors_html = " ".join(str(escape(e)) for e in field.errors)
			html += f'  <div class="invalid-feedback d-block" id="{field.id}_error">{errors_html}</div>\n'

		html += "</div>\n"

		# All string constructor values are emitted via _js_json to prevent JS injection
		script = """
<script>
$(document).ready(function() {{
    var fieldId = {field_id_js};
    var container = document.getElementById(fieldId + '-container');

    function showError(error) {{
        var alertEl = container.querySelector('.alert');
        if (alertEl) {{
            alertEl.textContent = error;
            alertEl.style.display = '';
            setTimeout(function() {{ alertEl.style.display = 'none'; }}, 5000);
        }}
    }}

    function toggleLoading(show) {{
        var overlay = container.querySelector('.loading-overlay');
        if (overlay) overlay.style.display = show ? '' : 'none';
    }}

    function updateStatus(data) {{
        var pcEl = container.querySelector('.point-count');
        var zlEl = container.querySelector('.zoom-level');
        var coordEl = container.querySelector('.coordinates');
        if (pcEl && data.points) pcEl.textContent = 'Points: ' + data.points.length;
        if (zlEl && data.zoom !== undefined) zlEl.textContent = 'Zoom: ' + data.zoom;
        if (coordEl && data.center) {{
            coordEl.textContent = 'Lat: ' + data.center.lat.toFixed(4) + ' Lng: ' + data.center.lng.toFixed(4);
        }}
    }}

    try {{
        var heatmap = new HeatmapWidget(fieldId, {{
            provider: {provider_js},
            gradient: {gradient_js},
            radius: {radius},
            animate: {animate},
            cluster: {cluster},
            maxZoom: {max_zoom},
            minZoom: {min_zoom},
            opacity: {opacity},
            legend: {legend_js},
            boundaries: {boundaries_js},
            timeWindow: {time_window},
            customStyles: {custom_styles_js},
            maxPoints: {max_points},
            updateInterval: {update_interval},
            offlineSupport: {offline_support},
            cacheTiles: {cache_tiles},
            workerThreads: {worker_threads},
            debugMode: {debug_mode},
            apiKeys: {api_keys_js},

            onError: function(error) {{ showError(error); }},
            onLoading: function(loading) {{ toggleLoading(loading); }},
            onChange: function(data) {{
                document.getElementById(fieldId).value = JSON.stringify(data);
                updateStatus(data);
            }}
        }});

        var existingData = document.getElementById(fieldId).value;
        if (existingData) {{
            try {{
                heatmap.setData(JSON.parse(existingData));
            }} catch (parseErr) {{
                console.warn('HeatmapWidget: could not parse existing data', parseErr);
            }}
        }}

        window.addEventListener('unload', function() {{
            heatmap.cleanup();
        }});

    }} catch (error) {{
        console.error('HeatmapWidget initialization error:', error);
        showError('Failed to initialize heatmap: ' + error.message);
    }}
}});
</script>
""".format(
			field_id_js=_js_json(field.id),
			provider_js=_js_json(self.provider),
			gradient_js=_js_json(self.gradient),
			radius=int(self.radius),
			animate=str(self.animate).lower(),
			cluster=str(self.cluster).lower(),
			max_zoom=int(self.max_zoom),
			min_zoom=int(self.min_zoom),
			opacity=float(self.opacity),
			legend_js=_js_json(self.legend),
			boundaries_js=_js_json(self.boundaries),
			time_window=int(self.time_window),
			custom_styles_js=_js_json(self.custom_styles),
			max_points=int(self.max_points),
			update_interval=int(self.update_interval),
			offline_support=str(self.offline_support).lower(),
			cache_tiles=str(self.cache_tiles).lower(),
			worker_threads=int(self.worker_threads),
			debug_mode=str(self.debug_mode).lower(),
			api_keys_js=_js_json(self.api_keys),
		)

		return Markup(html + script)

	def _render_toolbar(self, field_id: str) -> str:
		"""Render the heatmap toolbar HTML."""
		fid = str(escape(field_id))
		return f"""
<button type="button" class="btn btn-sm btn-secondary me-2"
        id="{fid}-export-png" aria-label="Export heatmap as PNG">
  <i class="fa fa-download" aria-hidden="true"></i> Export PNG
</button>
<button type="button" class="btn btn-sm btn-secondary me-2"
        id="{fid}-export-svg" aria-label="Export heatmap as SVG">
  <i class="fa fa-file-code-o" aria-hidden="true"></i> Export SVG
</button>
<button type="button" class="btn btn-sm btn-secondary"
        id="{fid}-reset-data" aria-label="Clear all heatmap data">
  <i class="fa fa-trash" aria-hidden="true"></i> Clear
</button>
"""

	def _render_animation_controls(self, field_id: str) -> str:
		"""Render animation playback controls when animate=True."""
		fid = str(escape(field_id))
		return f"""
<div class="animation-controls d-flex align-items-center gap-2" role="group" aria-label="Animation controls">
  <button type="button" class="btn btn-sm btn-secondary"
          id="{fid}-play" aria-label="Play animation">
    <i class="fa fa-play" aria-hidden="true"></i>
  </button>
  <button type="button" class="btn btn-sm btn-secondary"
          id="{fid}-pause" aria-label="Pause animation">
    <i class="fa fa-pause" aria-hidden="true"></i>
  </button>
  <button type="button" class="btn btn-sm btn-secondary"
          id="{fid}-stop" aria-label="Stop animation">
    <i class="fa fa-stop" aria-hidden="true"></i>
  </button>
  <input type="range" class="form-range flex-grow-1"
         id="{fid}-timeline" min="0" max="100" value="0"
         aria-label="Animation timeline">
</div>
"""

	def _include_dependencies(self) -> str:
		"""Include required JavaScript and CSS dependencies."""
		js_includes = "\n".join(
			[f'<script src="{escape(url)}"></script>' for url in self.JS_DEPENDENCIES]
		)
		css_includes = "\n".join(
			[f'<link rel="stylesheet" href="{escape(url)}">' for url in self.CSS_DEPENDENCIES]
		)
		return f"{css_includes}\n{js_includes}"

	def _validate_config(self):
		"""Validate widget configuration settings."""
		valid_providers = ["osm", "google", "mapbox", "here", "carto", "custom"]
		if self.provider not in valid_providers:
			raise ValueError(
				f"Invalid provider. Must be one of: {', '.join(valid_providers)}"
			)

		if not all(
			re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", color) for color in self.gradient
		):
			raise ValueError(
				"Invalid gradient colors. Must be hex colors (#RGB or #RRGGBB)"
			)

		if self.provider != "osm" and not self.api_keys.get(self.provider):
			raise ValueError(f"API key required for {self.provider}")

		if not 10 <= self.radius <= 50:
			raise ValueError("radius must be between 10 and 50")

		if not 1 <= self.min_zoom <= self.max_zoom <= 22:
			raise ValueError("Invalid zoom range")

		if not 0.1 <= self.opacity <= 1.0:
			raise ValueError("opacity must be between 0.1 and 1.0")

	def _initialize_workers(self):
		"""Initialize thread pool for data processing."""
		if not self.worker_threads:
			return
		try:
			from concurrent.futures import ThreadPoolExecutor
			self._worker_pool = ThreadPoolExecutor(max_workers=self.worker_threads)
		except Exception:
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
			if not points or not isinstance(points, list):
				raise ValueError("Invalid point data")

			original_len = len(points)
			if original_len > self.max_points:
				points = points[: self.max_points]

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
				"truncated": original_len > self.max_points,
			}

		except Exception as e:
			if self.debug_mode:
				raise
			return {"error": str(e)}

	def cleanup(self):
		"""Clean up resources and worker threads."""
		try:
			if self._worker_pool:
				self._worker_pool.shutdown(wait=True)
				self._worker_pool = None
			self._data_cache.clear()
		except Exception:
			if self.debug_mode:
				raise
