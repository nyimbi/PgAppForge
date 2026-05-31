"""GeoPointWidget — PgAppForge widget(s)."""

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

    data_template = (
        '<div class="geopoint-widget">'
        '<div class="input-group">'
        "<input %(text)s>"
        '<span class="input-group-addon"><i class="fa fa-search"></i></span>'
        "</div>"
        "<input %(hidden)s>"
        '<div id="%(field_id)s-map" class="map-container" style="height: 400px;"></div>'
        '<div class="map-controls">'
        '<button type="button" class="btn btn-sm btn-default" id="%(field_id)s-mylocation">'
        '<i class="fa fa-location-arrow"></i> My Location'
        "</button>"
        '<span class="coordinates-display"></span>'
        "</div>"
        '<div class="graph-error" role="alert" aria-live="assertive"></div>'  # Error div for WCAG
        "</div>"
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """
        Initialize GeoPointWidget with extended custom settings

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
        """
        super().__init__(**kwargs)
        self.default_location = kwargs.get("default_location", (0, 0))
        self.default_zoom = kwargs.get("default_zoom", 13)
        self.map_provider = kwargs.get("map_provider", "osm")
        self.api_key = kwargs.get("api_key", "")
        self.enable_search = kwargs.get(
            "enable_search", True
        )  # Enable/Disable Nominatim search
        self.search_provider = kwargs.get(
            "search_provider", "nominatim"
        )  # Default to Nominatim
        self.enable_mylocation = kwargs.get("enable_mylocation", True)
        self.marker_icon = kwargs.get("marker_icon", "")
        self.map_style = kwargs.get("map_style", {})
        self.enable_drawing = kwargs.get(
            "enable_drawing", False
        )  # Enable drawing tools
        self.enable_clustering = kwargs.get(
            "enable_clustering", False
        )  # Enable marker clustering
        self.geojson_layers = kwargs.get(
            "geojson_layers", []
        )  # Configuration for GeoJSON layers

    def __call__(self, field, **kwargs):
        """Render the widget with Leaflet map and controls"""
        kwargs.setdefault("type", "hidden")
        search_kwargs = {
            "type": "text",
            "class": "form-control",
            "placeholder": "Search location...",
            "autocomplete": "off",
        }

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "text": self.html_params(id=f"{field.id}-search", **search_kwargs),
            "field_id": field.id,
        }

        return Markup(
            html
            + """
        <script>
            (function() {
                var map = L.map('{field_id}-map').setView({default_location}, {default_zoom});
                {tile_layer}

                var marker;
                var drawnItems = new L.FeatureGroup().addTo(map); // FeatureGroup for drawn items
                var drawControl = new L.Control.Draw({{ // Leaflet.draw control
                    edit: {{ featureGroup: drawnItems, poly: {{ allowIntersection: false }} }},
                    draw: {{ polygon: {{ allowIntersection: false }}, polyline: true, rectangle: false, circle: false, marker: true }}
                }});


                if ({enable_drawing}) {{
                    map.addControl(drawControl);
                }}


                function setMarker(latlng) {{
                    if (marker) map.removeLayer(marker);
                    marker = L.marker(latlng, {{ draggable: true, icon: {marker_icon} }}).addTo(map);
                    $('#{field_id}').val(latlng.lat + ',' + latlng.lng);
                    $('.coordinates-display').text('Lat: ' + latlng.lat.toFixed(6) + ', Lng: ' + latlng.lng.toFixed(6));
                    marker.on('dragend', function(e) {{ setMarker(e.target.getLatLng()); }});
                }}


                map.on('draw:created', function(e) {{ // Handle draw created event
                    var type = e.layerType, layer = e.layer;
                    drawnItems.clearLayers(); // For simplicity, clear existing and add new, consider different behavior if needed
                    drawnItems.addLayer(layer);


                     var geojsonData = drawnItems.toGeoJSON();
                     $('#{field_id}').val(JSON.stringify(geojsonData)); // Store GeoJSON in hidden field

                }});

                map.on('draw:edited', function(e) {{ // Handle draw edited event
                    var layers = e.layers;
                     layers.eachLayer(function(layer) {{
                         var geojsonData = drawnItems.toGeoJSON();
                         $('#{field_id}').val(JSON.stringify(geojsonData)); // Update hidden field on edit
                     }});
                }});

                map.on('draw:deleted', function(e) {{ // Handle draw deleted event
                     drawnItems.clearLayers();
                     $('#{field_id}').val(''); // Clear hidden field if drawings are deleted
                }});


                map.on('click', function(e) {{ setMarker(e.latlng); }});


                var markers = L.markerClusterGroup(); // Marker cluster group

                function addMarkersClustered(locations) {{ // Function to add clustered markers
                    markers.clearLayers();
                    locations.forEach(function(loc) {{
                        L.marker([loc.lat, loc.lng]).bindPopup(loc.popupContent).addTo(markers);
                    }});
                    map.addLayer(markers);
                }}
                if ({enable_clustering}) {{ // Initialize clustering if enabled
                     map.addLayer(markers);
                }}


                {geojson_layer_init} // Initialize GeoJSON layers


                if ({enable_search}) {{
                    $('#{field_id}-search').on('input', function() {{
                        var query = $(this).val();
                        if (query.length > 2) {{
                             {search_handler} // Use selected search provider
                        }}
                    }});
                }}

                if ({enable_mylocation}) {{
                    $('#{field_id}-mylocation').on('click', function() {{
                        if ("geolocation" in navigator) {{
                            navigator.geolocation.getCurrentPosition(function(position) {{
                                var location = [position.coords.latitude, position.coords.longitude];
                                map.setView(location, 16);
                                setMarker({{lat: location[0], lng: location[1]}});
                            }}, function(error) {{ // Improved error handling for geolocation
                                $('.graph-error').text('Geolocation error: ' + error.message).show();
                                setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000); // Fade out error message
                            }});
                        }} else {{
                             $('.graph-error').text('Geolocation is not supported by your browser.').show(); // Inform user about browser support
                             setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                        }}
                    }});
                }}


                var initialValue = $('#{field_id}').val();
                if (initialValue) {{
                    try {{
                         var geojsonData = JSON.parse(initialValue);
                         if (geojsonData.type === 'FeatureCollection' || geojsonData.type === 'Feature' || geojsonData.type === 'Point' || geojsonData.type === 'Polygon' || geojsonData.type === 'LineString') {{
                            L.geoJSON(geojsonData, {{
                                onEachFeature: function (feature, layer) {{
                                     drawnItems.addLayer(layer); // Add GeoJSON to FeatureGroup for editing
                                }}}).addTo(map);
                            map.fitBounds(drawnItems.getBounds(), {{ maxZoom: 15 }}); // Fit map bounds to GeoJSON
                         }} else {{
                             var coords = initialValue.split(',').map(Number);
                             setMarker([coords[0], coords[1]]);
                         }}
                    }} catch (e) {{
                        $('.graph-error').text('Error loading saved location data.').show(); // User-friendly error message for data loading issues
                        setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                        console.error('Error parsing GeoJSON or location data:', e);
                    }}
                }}


            }})();
        </script>
        """.format(
                field_id=field.id,
                default_location=self.default_location,
                default_zoom=self.default_zoom,
                tile_layer=self._get_tile_layer(),
                search_control="true" if self.enable_search else "false",
                marker_icon=(
                    f"L.icon({{ iconUrl: '{self.marker_icon}' }})"
                    if self.marker_icon
                    else "L.Icon.Default()"
                ),
                enable_search=str(self.enable_search).lower(),
                enable_mylocation=str(self.enable_mylocation).lower(),
                enable_drawing=str(
                    self.enable_drawing
                ).lower(),  # Pass enable_drawing to script
                enable_clustering=str(
                    self.enable_clustering
                ).lower(),  # Pass enable_clustering
                geojson_layer_init=self._render_geojson_layers(),  # Render GeoJSON layer initialization
                search_handler=self._render_search_handler(),  # Render search handler based on provider
            )
        )

    def _render_geojson_layers(self):
        """Initialize GeoJSON layers from configuration"""
        init_code = ""
        for layer_conf in self.geojson_layers:
            if "url" in layer_conf:
                init_code += f"""
                    $.getJSON('{layer_conf["url"]}', function(data) {{
                        L.geoJSON(data, {_js_json(layer_conf.get("options", {}))}).addTo(map);
                    }});
                """
        return init_code

    def _render_search_handler(self):
        """Render search handler Javascript based on provider"""
        if self.search_provider == "google" and self.api_key:
            return f"""
                 var service = new google.maps.places.AutocompleteService();
                    service.getPlacePredictions({{
                        input: query,
                        types: ['geocode'],
                        componentRestrictions: {{ country: '{self.countries[0]}' }} // Apply country restriction if needed
                    }}, function(predictions, status) {{
                        if (status != google.maps.places.PlacesServiceStatus.OK) {{
                             $('.graph-error').text('Geocoding service error: ' + status).show(); // Display Google Places API errors
                             setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                            return;
                        }}

                        if (predictions)
                         {{
                            // Handle google places predictions - you might need to use PlacesService to get details
                            // Example (basic - you'll need to adapt based on how you want to use Google Places API):
                            var location = predictions[0].geometry.location;
                            map.setView([location.lat(), location.lng()], 16);
                            setMarker({{lat: location.lat(), lng: location.lng()}});

                        }}
                    }});

            """
        elif self.search_provider == "mapbox" and self.api_key:
            return f"""
                $.get('https://api.mapbox.com/geocoding/v5/mapbox.places/' + query + '.json', {{
                    access_token: '{self.api_key}',
                    country: '{','.join(self.countries)}', // Apply country restriction
                    limit: 5
                }}, function(data) {{
                    if (data && data.features.length > 0) {{
                        var location = data.features[0].center.reverse(); // Reverse [lng, lat] to [lat, lng]
                        map.setView(location, 16);
                        setMarker({{lat: location[0], lng: location[1]}});
                    }}
                     else {{
                             $('.graph-error').text('Location not found using Mapbox service.').show();
                             setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                        }}
                }}).fail(function(jqXHR, textStatus, errorThrown) {{ // Handle AJAX errors
                    $('.graph-error').text('Mapbox Geocoding error: ' + textStatus + ', ' + errorThrown).show();
                    setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                }});
            """

        else:  # Default to Nominatim (or 'osm')
            return """
                $.get('https://nominatim.openstreetmap.org/search', {{
                    format: 'json',
                    q: query,
                    countrycodes: '{country_codes}', // Apply country restriction for Nominatim
                    limit: 5
                }}, function(data) {{
                    if (data.length > 0) {{
                        var location = [parseFloat(data[0].lat), parseFloat(data[0].lon)];
                        map.setView(location, 16);
                        setMarker({{lat: location[0], lng: location[1]}});
                    }} else {{
                        $('.graph-error').text('Location not found using OpenStreetMap Nominatim service.').show(); // User-friendly error message if Nominatim fails
                        setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                    }}
                }}).fail(function(jqXHR, textStatus, errorThrown) {{ // Handle AJAX errors for Nominatim
                     $('.graph-error').text('Nominatim Geocoding error: ' + textStatus + ', ' + errorThrown).show();
                     setTimeout(function() {{ $('.graph-error').fadeOut(); }}, 5000);
                }});
            """.format(
                country_codes=",".join(self.countries).lower()
            )  # Apply country codes to Nominatim

    def _get_tile_layer(self):
        """Configure tile layer based on map provider and API key"""
        if self.map_provider == "google" and self.api_key:
            return f"""
                L.gridLayer.googleMutant({{
                    type: 'roadmap',
                    apiKey: '{self.api_key}',
                    styles: {_js_json(self.map_style)}
                }}).addTo(map);
            """
        elif self.map_provider == "mapbox" and self.api_key:
            return f"""
                L.tileLayer('https://api.mapbox.com/styles/v1/mapbox/streets-v11/tiles/{{z}}/{{x}}/{{y}}?access_token={self.api_key}', {{
                    attribution: '© Mapbox'
                }}).addTo(map);
            """
        elif (
            self.map_provider == "here" and self.api_key
        ):  # Example for HERE Maps tile layer (replace with actual HERE Maps tile URL if needed)
            return f"""
                var hereTileUrl = 'https://xyz.api.here.com/maps/raster/satellite.day/512/{{z}}/{{x}}/{{y}}/512/png?apiKey={self.api_key}&style=explore.day';
                L.tileLayer(hereTileUrl, {{
                    attribution: '© HERE 2024'
                }}).addTo(map);
            """
        else:  # Default to OpenStreetMap
            return """
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                }).addTo(map);
            """

    def process_formdata(
        self, valuelist
    ):  # Corrected method name and added value parameter
        """Process form data to database format, handles GeoJSON or lat,lng strings"""
        if valuelist and valuelist[0]:
            value = valuelist[0]
            try:
                geojson_data = json.loads(value)  # Try to parse as GeoJSON first
                return geojson_data  # Return GeoJSON directly if valid
            except json.JSONDecodeError:
                try:
                    lat, lng = map(
                        float, value.split(",")
                    )  # Fallback to lat,lng parsing if not GeoJSON
                    return (
                        f"SRID=4326;POINT({lng} {lat})"  # Return PostGIS point format
                    )
                except ValueError:
                    raise ValueError(
                        _("Invalid location format")
                    )  # Indicate invalid format for both GeoJSON and lat,lng
        return None

    def process_data(self, value):
        """Process data from database format to widget format. Handles PostGIS Geometry or GeoJSON"""
        if value:
            if isinstance(value, str) and value.startswith(
                '{"type":'
            ):  # Check if it's GeoJSON string
                try:
                    return json.loads(
                        value
                    )  # Return GeoJSON object if it's a valid JSON string
                except json.JSONDecodeError:
                    pass  # Not valid JSON, proceed with other checks

            if (
                hasattr(value, "coords") and value.geom_type == "Point"
            ):  # Handle PostGIS Point Geometry object
                lng, lat = value.coords
                return f"{lat},{lng}"  # Return lat,lng string format for point

            elif isinstance(
                value, str
            ):  # If it's still a string, return as is (could be lat,lng string or other text data)
                return value
        return None
