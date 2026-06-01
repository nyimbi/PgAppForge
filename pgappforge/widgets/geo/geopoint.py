"""GeoPointWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape
from wtforms.validators import ValidationError


class GeoPointWidget(BS3TextFieldWidget):
	"""
	Widget for geographical point selection using interactive maps.
	Designed to work with PostgreSQL's PostGIS geography/geometry types.

	Features:
	- Interactive map selection with marker, polygon, and polyline drawing
	- Supports multiple map providers (OpenStreetMap, Google Maps, Mapbox)
	- Geocoding support via Nominatim and customizable providers
	- Clustering of markers for large datasets
	- Custom marker icons and popups
	- Default location and zoom level settings
	- Customizable map styles and layers (including GeoJSON overlays)
	- Multiple coordinate formats and PostGIS compatibility
	- Enhanced search functionality with provider customization
	- Current location detection
	- Improved error handling and user feedback

	Database Type:
	    PostgreSQL: geography(GEOMETRY,4326) or geometry(GEOMETRY,4326)
	    SQLAlchemy: Geometry("POINT", srid=4326) or Geometry("GEOMETRY", srid=4326)

	Example Usage:
	    location = db.Column(Geometry("POINT", srid=4326))
	    area = db.Column(Geometry("POLYGON", srid=4326))
	    route = db.Column(Geometry("LINESTRING", srid=4326))
	"""

	def __init__(self, **kwargs):
		"""
		Initialize GeoPointWidget with extended custom settings.

		Args:
		    default_location (tuple): Default map center (lat, lng)
		    default_zoom (int): Default zoom level
		    map_provider (str): Map provider ('osm', 'google', 'mapbox')
		    api_key (str): API key for commercial map providers
		    enable_search (bool): Enable location search via Nominatim
		    search_provider (str): Custom search provider URL (if not Nominatim)
		    enable_mylocation (bool): Enable current location detection
		    marker_icon (str): Custom marker icon URL
		    map_style (dict): Custom map style configuration
		    enable_drawing (bool): Enable polygon and polyline drawing tools
		    enable_clustering (bool): Enable marker clustering for points
		    geojson_layers (list): List of GeoJSON layer configurations
		    placeholder (str): Placeholder text for the search input
		    css_class (str): Additional CSS classes for the widget container
		    description (str): Help text to display below the widget
		    readonly (bool): Render in read-only mode
		    disabled (bool): Render in disabled state
		"""
		super().__init__(**kwargs)
		self.default_location = kwargs.get("default_location", (0, 0))
		self.default_zoom = kwargs.get("default_zoom", 13)
		self.map_provider = kwargs.get("map_provider", "osm")
		self.api_key = kwargs.get("api_key", "")
		self.enable_search = kwargs.get("enable_search", True)
		self.search_provider = kwargs.get("search_provider", "nominatim")
		self.enable_mylocation = kwargs.get("enable_mylocation", True)
		self.marker_icon = kwargs.get("marker_icon", "")
		self.map_style = kwargs.get("map_style", {})
		self.enable_drawing = kwargs.get("enable_drawing", False)
		self.enable_clustering = kwargs.get("enable_clustering", False)
		self.geojson_layers = kwargs.get("geojson_layers", [])
		self.placeholder = kwargs.get("placeholder", "Search location...")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)
		# countries used by search providers (kept for API compatibility)
		self.countries = kwargs.get("countries", [])

	def __call__(self, field, **kwargs):
		"""Render the widget with Leaflet map and controls."""
		has_errors = bool(field.errors)
		container_class = "geopoint-widget"
		if self.css_class:
			container_class += " " + self.css_class

		# Hidden input for actual coordinate/GeoJSON value
		hidden_attrs: dict[str, Any] = {
			"type": "hidden",
			"id": field.id,
			"name": field.name,
		}
		if has_errors:
			hidden_attrs["aria-invalid"] = "true"
		if field.data:
			hidden_attrs["value"] = field.data if isinstance(field.data, str) else json.dumps(field.data)

		# Search input attributes
		search_attrs: dict[str, Any] = {
			"type": "text",
			"class": "form-control" + (" is-invalid" if has_errors else ""),
			"placeholder": str(escape(self.placeholder)),
			"autocomplete": "off",
			"id": f"{field.id}-search",
			"aria-label": str(field.label.text) if field.label else "Location search",
		}
		if self.description:
			search_attrs["aria-describedby"] = f"{field.id}_help"
		if has_errors:
			search_attrs["aria-invalid"] = "true"
		if self.readonly:
			search_attrs["readonly"] = True
		if self.disabled:
			search_attrs["disabled"] = True

		from wtforms.widgets import html_params
		hidden_html = f"<input {html_params(**hidden_attrs)}>"
		search_html = f"<input {html_params(**search_attrs)}>"

		# Map container uses max-width for responsiveness; height uses CSS custom property
		map_html = f"""
<div class="{escape(container_class)}">
  <div class="input-group">
    {search_html}
    <span class="input-group-addon"><i class="fa fa-search" aria-hidden="true"></i></span>
  </div>
  {hidden_html}
  <div id="{field.id}-map" class="map-container" style="height:400px;width:100%;max-width:100%;touch-action:pan-y;" role="application" aria-label="Interactive map for {escape(field.label.text) if field.label else 'location'} selection"></div>
  <div class="map-controls" style="margin-top:4px;">
    <button type="button" class="btn btn-sm btn-secondary" id="{field.id}-mylocation" aria-label="Use my current location">
      <i class="fa fa-location-arrow" aria-hidden="true"></i> My Location
    </button>
    <span class="coordinates-display" aria-live="polite"></span>
  </div>
  <div class="graph-error" role="alert" aria-live="assertive" style="display:none;"></div>
"""

		if self.description:
			map_html += f'  <small class="form-text text-muted" id="{field.id}_help">{escape(self.description)}</small>\n'

		if has_errors:
			errors_html = " ".join(str(escape(e)) for e in field.errors)
			map_html += f'  <div class="invalid-feedback d-block" id="{field.id}_error">{errors_html}</div>\n'

		map_html += "</div>"

		# Safely build JS config using _js_json for all non-numeric values
		marker_icon_js = (
			f"L.icon({{ iconUrl: {_js_json(self.marker_icon)} }})"
			if self.marker_icon
			else "new L.Icon.Default()"
		)

		script = """
<script>
(function() {{
    var fieldId = {field_id_js};
    var mapEl = document.getElementById(fieldId + '-map');
    if (!mapEl) return;

    var map = L.map(fieldId + '-map').setView({default_location}, {default_zoom});
    {tile_layer}

    var marker;
    var drawnItems = new L.FeatureGroup().addTo(map);
    var drawControl = new L.Control.Draw({{
        edit: {{ featureGroup: drawnItems, poly: {{ allowIntersection: false }} }},
        draw: {{
            polygon: {{ allowIntersection: false }},
            polyline: true,
            rectangle: false,
            circle: false,
            marker: true
        }}
    }});

    if ({enable_drawing}) {{
        map.addControl(drawControl);
    }}

    function setMarker(latlng) {{
        if (marker) map.removeLayer(marker);
        marker = L.marker(latlng, {{ draggable: true, icon: {marker_icon} }}).addTo(map);
        document.getElementById(fieldId).value = latlng.lat + ',' + latlng.lng;
        var dispEl = mapEl.closest('.geopoint-widget').querySelector('.coordinates-display');
        if (dispEl) dispEl.textContent = 'Lat: ' + latlng.lat.toFixed(6) + ', Lng: ' + latlng.lng.toFixed(6);
        marker.on('dragend', function(e) {{ setMarker(e.target.getLatLng()); }});
    }}

    function showError(msg) {{
        var errEl = mapEl.closest('.geopoint-widget').querySelector('.graph-error');
        if (!errEl) return;
        errEl.textContent = msg;
        errEl.style.display = '';
        setTimeout(function() {{ errEl.style.display = 'none'; }}, 5000);
    }}

    map.on('draw:created', function(e) {{
        drawnItems.clearLayers();
        drawnItems.addLayer(e.layer);
        document.getElementById(fieldId).value = JSON.stringify(drawnItems.toGeoJSON());
    }});

    map.on('draw:edited', function(e) {{
        document.getElementById(fieldId).value = JSON.stringify(drawnItems.toGeoJSON());
    }});

    map.on('draw:deleted', function() {{
        drawnItems.clearLayers();
        document.getElementById(fieldId).value = '';
    }});

    map.on('click', function(e) {{ setMarker(e.latlng); }});

    var clusterGroup = L.markerClusterGroup ? L.markerClusterGroup() : null;
    if ({enable_clustering} && clusterGroup) {{
        map.addLayer(clusterGroup);
    }}

    {geojson_layer_init}

    if ({enable_search}) {{
        var searchEl = document.getElementById(fieldId + '-search');
        if (searchEl) {{
            searchEl.addEventListener('input', function() {{
                var query = searchEl.value;
                if (query.length > 2) {{
                    {search_handler}
                }}
            }});
        }}
    }}

    if ({enable_mylocation}) {{
        var myLocBtn = document.getElementById(fieldId + '-mylocation');
        if (myLocBtn) {{
            myLocBtn.addEventListener('click', function() {{
                if ('geolocation' in navigator) {{
                    navigator.geolocation.getCurrentPosition(
                        function(position) {{
                            var loc = [position.coords.latitude, position.coords.longitude];
                            map.setView(loc, 16);
                            setMarker({{lat: loc[0], lng: loc[1]}});
                        }},
                        function(error) {{
                            showError('Geolocation error: ' + error.message);
                        }}
                    );
                }} else {{
                    showError('Geolocation is not supported by your browser.');
                }}
            }});
        }}
    }}

    var initialValue = document.getElementById(fieldId).value;
    if (initialValue) {{
        try {{
            var geojsonData = JSON.parse(initialValue);
            var gtype = geojsonData.type;
            if (gtype === 'FeatureCollection' || gtype === 'Feature' ||
                gtype === 'Point' || gtype === 'Polygon' || gtype === 'LineString') {{
                L.geoJSON(geojsonData, {{
                    onEachFeature: function(feature, layer) {{
                        drawnItems.addLayer(layer);
                    }}
                }}).addTo(map);
                if (drawnItems.getBounds().isValid()) {{
                    map.fitBounds(drawnItems.getBounds(), {{ maxZoom: 15 }});
                }}
            }} else {{
                var coords = initialValue.split(',').map(Number);
                if (coords.length === 2 && !isNaN(coords[0]) && !isNaN(coords[1])) {{
                    setMarker({{lat: coords[0], lng: coords[1]}});
                }}
            }}
        }} catch (e) {{
            var parts = initialValue.split(',').map(Number);
            if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {{
                setMarker({{lat: parts[0], lng: parts[1]}});
            }} else {{
                showError('Error loading saved location data.');
                console.error('GeoPoint parse error:', e);
            }}
        }}
    }}
}})();
</script>
""".format(
			field_id_js=_js_json(field.id),
			default_location=_js_json(list(self.default_location)),
			default_zoom=int(self.default_zoom),
			tile_layer=self._get_tile_layer(),
			marker_icon=marker_icon_js,
			enable_search=str(self.enable_search).lower(),
			enable_mylocation=str(self.enable_mylocation).lower(),
			enable_drawing=str(self.enable_drawing).lower(),
			enable_clustering=str(self.enable_clustering).lower(),
			geojson_layer_init=self._render_geojson_layers(),
			search_handler=self._render_search_handler(),
		)

		return Markup(map_html + script)

	def _render_geojson_layers(self) -> str:
		"""Initialize GeoJSON layers from configuration."""
		init_code = ""
		for layer_conf in self.geojson_layers:
			if "url" in layer_conf:
				url_js = _js_json(layer_conf["url"])
				opts_js = _js_json(layer_conf.get("options", {}))
				init_code += f"""
                    $.getJSON({url_js}, function(data) {{
                        L.geoJSON(data, {opts_js}).addTo(map);
                    }});
				"""
		return init_code

	def _render_search_handler(self) -> str:
		"""Render search handler JavaScript based on provider."""
		if self.search_provider == "google" and self.api_key:
			# country restriction is safe via _js_json
			country = _js_json(self.countries[0] if self.countries else "")
			return f"""
                var service = new google.maps.places.AutocompleteService();
                service.getPlacePredictions({{
                    input: query,
                    types: ['geocode'],
                    componentRestrictions: {{ country: {country} }}
                }}, function(predictions, status) {{
                    if (status !== google.maps.places.PlacesServiceStatus.OK || !predictions) {{
                        showError('Geocoding service error: ' + status);
                        return;
                    }}
                    if (predictions.length > 0) {{
                        var loc = predictions[0].geometry.location;
                        map.setView([loc.lat(), loc.lng()], 16);
                        setMarker({{lat: loc.lat(), lng: loc.lng()}});
                    }}
                }});
			"""
		elif self.search_provider == "mapbox" and self.api_key:
			token_js = _js_json(self.api_key)
			countries_js = _js_json(",".join(self.countries))
			return f"""
                fetch('https://api.mapbox.com/geocoding/v5/mapbox.places/' + encodeURIComponent(query) + '.json?access_token=' + {token_js} + '&country=' + {countries_js} + '&limit=5')
                    .then(function(r) {{ return r.json(); }})
                    .then(function(data) {{
                        if (data && data.features && data.features.length > 0) {{
                            var center = data.features[0].center;
                            map.setView([center[1], center[0]], 16);
                            setMarker({{lat: center[1], lng: center[0]}});
                        }} else {{
                            showError('Location not found using Mapbox service.');
                        }}
                    }})
                    .catch(function(err) {{
                        showError('Mapbox Geocoding error: ' + err.message);
                    }});
			"""
		else:
			# Default to Nominatim — country codes via _js_json
			country_codes_js = _js_json(",".join(self.countries).lower())
			return f"""
                fetch('https://nominatim.openstreetmap.org/search?format=json&limit=5&countrycodes=' + {country_codes_js} + '&q=' + encodeURIComponent(query))
                    .then(function(r) {{ return r.json(); }})
                    .then(function(data) {{
                        if (data.length > 0) {{
                            var loc = [parseFloat(data[0].lat), parseFloat(data[0].lon)];
                            map.setView(loc, 16);
                            setMarker({{lat: loc[0], lng: loc[1]}});
                        }} else {{
                            showError('Location not found via OpenStreetMap Nominatim.');
                        }}
                    }})
                    .catch(function(err) {{
                        showError('Nominatim Geocoding error: ' + err.message);
                    }});
			"""

	def _get_tile_layer(self) -> str:
		"""Configure tile layer based on map provider and API key."""
		if self.map_provider == "google" and self.api_key:
			return f"""
                L.gridLayer.googleMutant({{
                    type: 'roadmap',
                    apiKey: {_js_json(self.api_key)},
                    styles: {_js_json(self.map_style)}
                }}).addTo(map);
			"""
		elif self.map_provider == "mapbox" and self.api_key:
			token_js = _js_json(self.api_key)
			return f"""
                L.tileLayer('https://api.mapbox.com/styles/v1/mapbox/streets-v11/tiles/{{z}}/{{x}}/{{y}}?access_token=' + {token_js}, {{
                    attribution: '© Mapbox'
                }}).addTo(map);
			"""
		elif self.map_provider == "here" and self.api_key:
			key_js = _js_json(self.api_key)
			return f"""
                var hereTileUrl = 'https://xyz.api.here.com/maps/raster/satellite.day/512/{{z}}/{{x}}/{{y}}/512/png?apiKey=' + {key_js} + '&style=explore.day';
                L.tileLayer(hereTileUrl, {{
                    attribution: '© HERE 2024'
                }}).addTo(map);
			"""
		else:
			return """
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                }).addTo(map);
			"""

	def process_formdata(self, valuelist):
		"""Process form data to database format; handles GeoJSON or lat,lng strings."""
		if valuelist and valuelist[0]:
			value = valuelist[0]
			try:
				geojson_data = json.loads(value)
				return geojson_data
			except json.JSONDecodeError:
				try:
					lat, lng = map(float, value.split(","))
					return f"SRID=4326;POINT({lng} {lat})"
				except ValueError:
					raise ValueError(_("Invalid location format"))
		return None

	def process_data(self, value):
		"""Process data from database format to widget format."""
		if value:
			if isinstance(value, str) and value.startswith('{"type":'):
				try:
					return json.loads(value)
				except json.JSONDecodeError:
					pass

			if hasattr(value, "coords") and value.geom_type == "Point":
				lng, lat = value.coords
				return f"{lat},{lng}"

			elif isinstance(value, str):
				return value
		return None
