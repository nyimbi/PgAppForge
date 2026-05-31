"""
Map Field Type for PgAppForge

Comprehensive geographic field type supporting multiple map providers,
coordinate systems, and geographic data storage with validation.
"""

import json
import logging
from typing import Dict, List, Any, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import TypeDecorator, Text, String
from sqlalchemy.ext.mutable import MutableDict
from wtforms import Field, ValidationError
from wtforms.widgets import TextArea, Input
from flask import current_app
from markupsafe import Markup
from pgappforge.fieldwidgets import BS3TextFieldWidget

log = logging.getLogger(__name__)


class MapProvider(Enum):
    """Supported map providers."""
    LEAFLET = "leaflet"
    GOOGLE_MAPS = "google_maps"
    MAPBOX = "mapbox"
    OPENSTREETMAP = "openstreetmap"
    ARCGIS = "arcgis"


class CoordinateSystem(Enum):
    """Supported coordinate systems."""
    WGS84 = "EPSG:4326"  # Standard GPS coordinates
    WEB_MERCATOR = "EPSG:3857"  # Web Mercator
    UTM = "UTM"  # Universal Transverse Mercator


@dataclass
class MapPoint:
    """Geographic point with coordinates and metadata."""
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    accuracy: Optional[float] = None
    timestamp: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'altitude': self.altitude,
            'accuracy': self.accuracy,
            'timestamp': self.timestamp,
            'properties': self.properties or {}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MapPoint':
        """Create from dictionary."""
        return cls(
            latitude=data['latitude'],
            longitude=data['longitude'],
            altitude=data.get('altitude'),
            accuracy=data.get('accuracy'),
            timestamp=data.get('timestamp'),
            properties=data.get('properties')
        )


@dataclass
class MapArea:
    """Geographic area defined by bounds or polygon."""
    bounds: Optional[Dict[str, float]] = None  # {'north': lat, 'south': lat, 'east': lng, 'west': lng}
    polygon: Optional[List[Tuple[float, float]]] = None  # [(lat, lng), ...]
    center: Optional[MapPoint] = None
    radius: Optional[float] = None  # meters
    properties: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'bounds': self.bounds,
            'polygon': self.polygon,
            'center': self.center.to_dict() if self.center else None,
            'radius': self.radius,
            'properties': self.properties or {}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MapArea':
        """Create from dictionary."""
        center_data = data.get('center')
        center = MapPoint.from_dict(center_data) if center_data else None
        
        return cls(
            bounds=data.get('bounds'),
            polygon=data.get('polygon'),
            center=center,
            radius=data.get('radius'),
            properties=data.get('properties')
        )


@dataclass
class MapRoute:
    """Geographic route with waypoints."""
    waypoints: List[MapPoint]
    route_type: str = "driving"  # driving, walking, cycling, transit
    distance: Optional[float] = None  # meters
    duration: Optional[float] = None  # seconds
    instructions: Optional[List[Dict[str, Any]]] = None
    properties: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'waypoints': [wp.to_dict() for wp in self.waypoints],
            'route_type': self.route_type,
            'distance': self.distance,
            'duration': self.duration,
            'instructions': self.instructions or [],
            'properties': self.properties or {}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MapRoute':
        """Create from dictionary."""
        waypoints = [MapPoint.from_dict(wp) for wp in data.get('waypoints', [])]
        
        return cls(
            waypoints=waypoints,
            route_type=data.get('route_type', 'driving'),
            distance=data.get('distance'),
            duration=data.get('duration'),
            instructions=data.get('instructions'),
            properties=data.get('properties')
        )


@dataclass
class MapData:
    """Complete map data structure."""
    type: str  # point, area, route, multi
    points: List[MapPoint] = None
    areas: List[MapArea] = None
    routes: List[MapRoute] = None
    zoom_level: int = 10
    center: Optional[MapPoint] = None
    provider: MapProvider = MapProvider.LEAFLET
    coordinate_system: CoordinateSystem = CoordinateSystem.WGS84
    properties: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Initialize empty collections."""
        if self.points is None:
            self.points = []
        if self.areas is None:
            self.areas = []
        if self.routes is None:
            self.routes = []
        if self.properties is None:
            self.properties = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'type': self.type,
            'points': [p.to_dict() for p in self.points],
            'areas': [a.to_dict() for a in self.areas],
            'routes': [r.to_dict() for r in self.routes],
            'zoom_level': self.zoom_level,
            'center': self.center.to_dict() if self.center else None,
            'provider': self.provider.value,
            'coordinate_system': self.coordinate_system.value,
            'properties': self.properties
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MapData':
        """Create from dictionary."""
        points = [MapPoint.from_dict(p) for p in data.get('points', [])]
        areas = [MapArea.from_dict(a) for a in data.get('areas', [])]
        routes = [MapRoute.from_dict(r) for r in data.get('routes', [])]
        
        center_data = data.get('center')
        center = MapPoint.from_dict(center_data) if center_data else None
        
        provider = MapProvider(data.get('provider', MapProvider.LEAFLET.value))
        coordinate_system = CoordinateSystem(data.get('coordinate_system', CoordinateSystem.WGS84.value))
        
        return cls(
            type=data.get('type', 'point'),
            points=points,
            areas=areas,
            routes=routes,
            zoom_level=data.get('zoom_level', 10),
            center=center,
            provider=provider,
            coordinate_system=coordinate_system,
            properties=data.get('properties', {})
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'MapData':
        """Create from JSON string."""
        if not json_str:
            return cls(type='point')
        
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            log.warning(f"Failed to parse map data: {e}")
            return cls(type='point')
    
    def add_point(self, latitude: float, longitude: float, **kwargs):
        """Add a point to the map."""
        point = MapPoint(latitude=latitude, longitude=longitude, **kwargs)
        self.points.append(point)
        
        # Auto-set center if not set
        if not self.center:
            self.center = point
    
    def add_area(self, bounds: Dict[str, float] = None, 
                polygon: List[Tuple[float, float]] = None, **kwargs):
        """Add an area to the map."""
        area = MapArea(bounds=bounds, polygon=polygon, **kwargs)
        self.areas.append(area)
    
    def add_route(self, waypoints: List[Tuple[float, float]], **kwargs):
        """Add a route to the map."""
        route_points = [MapPoint(latitude=lat, longitude=lng) for lat, lng in waypoints]
        route = MapRoute(waypoints=route_points, **kwargs)
        self.routes.append(route)
    
    def get_bounds(self) -> Optional[Dict[str, float]]:
        """Calculate bounds for all map data."""
        all_points = []
        
        # Collect all points
        all_points.extend(self.points)
        
        for area in self.areas:
            if area.center:
                all_points.append(area.center)
            if area.polygon:
                all_points.extend([MapPoint(lat, lng) for lat, lng in area.polygon])
        
        for route in self.routes:
            all_points.extend(route.waypoints)
        
        if not all_points:
            return None
        
        lats = [p.latitude for p in all_points]
        lngs = [p.longitude for p in all_points]
        
        return {
            'north': max(lats),
            'south': min(lats),
            'east': max(lngs),
            'west': min(lngs)
        }


class GeographicType(TypeDecorator):
    """SQLAlchemy type for storing geographic data."""
    
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        """Convert MapData to JSON for storage."""
        if value is None:
            return None
        
        if isinstance(value, MapData):
            return value.to_json()
        elif isinstance(value, (dict, str)):
            if isinstance(value, dict):
                return json.dumps(value)
            return value
        else:
            return str(value)
    
    def process_result_value(self, value, dialect):
        """Convert JSON to MapData when loading."""
        if value is None:
            return None
        
        try:
            if isinstance(value, str):
                return MapData.from_json(value)
            elif isinstance(value, dict):
                return MapData.from_dict(value)
            else:
                return MapData(type='point')
        except Exception as e:
            log.warning(f"Failed to process geographic data: {e}")
            return MapData(type='point')


class MapWidget:
    """Widget for rendering map interface."""
    
    def __init__(self, provider: MapProvider = MapProvider.LEAFLET,
                 width: str = "100%", height: str = "400px",
                 enable_drawing: bool = True, enable_search: bool = True):
        """Initialize map widget."""
        self.provider = provider
        self.width = width
        self.height = height
        self.enable_drawing = enable_drawing
        self.enable_search = enable_search
    
    def __call__(self, field, **kwargs):
        """Render the map widget."""
        field_id = kwargs.get('id', field.id)
        field_name = kwargs.get('name', field.name)
        
        # Get current value
        current_value = field.data if field.data else MapData(type='point')
        if isinstance(current_value, str):
            current_value = MapData.from_json(current_value)
        
        # Generate unique map container ID
        map_container_id = f"map-container-{field_id}"
        map_id = f"map-{field_id}"
        
        # Hidden input to store the actual data
        hidden_input = f'''
        <input type="hidden" id="{field_id}" name="{field_name}" 
               value="{current_value.to_json()}" />
        '''
        
        # Map container
        map_container = f'''
        <div id="{map_container_id}" class="map-field-container">
            <div id="{map_id}" class="map-display" 
                 style="width: {self.width}; height: {self.height};"></div>
            <div class="map-controls">
                <div class="map-coordinates">
                    <span id="{map_id}-coordinates">Click on map to set coordinates</span>
                </div>
                <div class="map-buttons">
                    <button type="button" class="btn btn-sm btn-secondary" 
                            onclick="clearMap('{map_id}', '{field_id}')">Clear</button>
                    <button type="button" class="btn btn-sm btn-info" 
                            onclick="getCurrentLocation('{map_id}', '{field_id}')">Use Current Location</button>
                    {self._get_drawing_controls(map_id, field_id) if self.enable_drawing else ''}
                </div>
            </div>
        </div>
        '''
        
        # Include CSS and JavaScript
        css_js = self._get_css_js(map_id, field_id, current_value)
        
        return Markup(hidden_input + map_container + css_js)
    
    def _get_drawing_controls(self, map_id: str, field_id: str) -> str:
        """Get drawing control buttons."""
        return f'''
        <div class="btn-group" role="group">
            <button type="button" class="btn btn-sm btn-outline-primary" 
                    onclick="setMapMode('{map_id}', 'point')">Point</button>
            <button type="button" class="btn btn-sm btn-outline-primary" 
                    onclick="setMapMode('{map_id}', 'area')">Area</button>
            <button type="button" class="btn btn-sm btn-outline-primary" 
                    onclick="setMapMode('{map_id}', 'route')">Route</button>
        </div>
        '''
    
    def _get_css_js(self, map_id: str, field_id: str, current_value: MapData) -> str:
        """Get CSS and JavaScript for the map."""
        if self.provider == MapProvider.LEAFLET:
            return self._get_leaflet_css_js(map_id, field_id, current_value)
        elif self.provider == MapProvider.GOOGLE_MAPS:
            return self._get_google_maps_css_js(map_id, field_id, current_value)
        else:
            return self._get_leaflet_css_js(map_id, field_id, current_value)  # Default fallback
    
    def _get_leaflet_css_js(self, map_id: str, field_id: str, current_value: MapData) -> str:
        """Get Leaflet-specific CSS and JavaScript."""
        return f'''
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" 
              integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
        <link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css"/>
        
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" 
                integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
        <script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>
        
        <style>
        .map-field-container {{
            border: 1px solid #ddd;
            border-radius: 4px;
            overflow: hidden;
        }}
        .map-display {{
            position: relative;
        }}
        .map-controls {{
            padding: 10px;
            background-color: #f8f9fa;
            border-top: 1px solid #ddd;
        }}
        .map-coordinates {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 8px;
        }}
        .map-buttons {{
            display: flex;
            gap: 8px;
            align-items: center;
        }}
        </style>
        
        <script>
        (function() {{
            let map_{map_id};
            let currentMarker_{map_id};
            let drawnItems_{map_id};
            let drawControl_{map_id};
            let mapMode_{map_id} = 'point';
            
            function initMap_{map_id}() {{
                if (map_{map_id}) {{
                    map_{map_id}.remove();
                }}
                
                // Initialize map
                map_{map_id} = L.map('{map_id}').setView([40.7128, -74.0060], 10);
                
                // Add tile layer
                L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    attribution: '© OpenStreetMap contributors'
                }}).addTo(map_{map_id});
                
                // Initialize draw controls
                drawnItems_{map_id} = new L.FeatureGroup();
                map_{map_id}.addLayer(drawnItems_{map_id});
                
                {self._get_leaflet_draw_controls(map_id) if self.enable_drawing else ''}
                
                // Load existing data
                loadMapData_{map_id}();
                
                // Map click handler
                map_{map_id}.on('click', function(e) {{
                    if (mapMode_{map_id} === 'point') {{
                        setMarker_{map_id}(e.latlng.lat, e.latlng.lng);
                    }}
                }});
                
                // Update coordinates display on mouse move
                map_{map_id}.on('mousemove', function(e) {{
                    document.getElementById('{map_id}-coordinates').textContent = 
                        `Lat: ${{e.latlng.lat.toFixed(6)}}, Lng: ${{e.latlng.lng.toFixed(6)}}`;
                }});
            }}
            
            function setMarker_{map_id}(lat, lng) {{
                if (currentMarker_{map_id}) {{
                    map_{map_id}.removeLayer(currentMarker_{map_id});
                }}
                
                currentMarker_{map_id} = L.marker([lat, lng]).addTo(map_{map_id});
                updateFieldValue_{map_id}();
                
                document.getElementById('{map_id}-coordinates').textContent = 
                    `Selected: Lat: ${{lat.toFixed(6)}}, Lng: ${{lng.toFixed(6)}}`;
            }}
            
            function loadMapData_{map_id}() {{
                try {{
                    const fieldValue = document.getElementById('{field_id}').value;
                    if (!fieldValue) return;
                    
                    const mapData = JSON.parse(fieldValue);
                    
                    // Load points
                    if (mapData.points && mapData.points.length > 0) {{
                        const point = mapData.points[0];
                        setMarker_{map_id}(point.latitude, point.longitude);
                        map_{map_id}.setView([point.latitude, point.longitude], mapData.zoom_level || 10);
                    }}
                    
                    // Load center
                    if (mapData.center) {{
                        map_{map_id}.setView([mapData.center.latitude, mapData.center.longitude], 
                                           mapData.zoom_level || 10);
                    }}
                }} catch (e) {{
                    console.warn('Failed to load map data:', e);
                }}
            }}
            
            function updateFieldValue_{map_id}() {{
                const mapData = {{
                    type: mapMode_{map_id},
                    points: [],
                    areas: [],
                    routes: [],
                    zoom_level: map_{map_id}.getZoom(),
                    center: null,
                    provider: 'leaflet',
                    coordinate_system: 'EPSG:4326',
                    properties: {{}}
                }};
                
                if (currentMarker_{map_id}) {{
                    const latlng = currentMarker_{map_id}.getLatLng();
                    mapData.points.push({{
                        latitude: latlng.lat,
                        longitude: latlng.lng,
                        properties: {{}}
                    }});
                    mapData.center = {{
                        latitude: latlng.lat,
                        longitude: latlng.lng
                    }};
                }}
                
                document.getElementById('{field_id}').value = JSON.stringify(mapData);
            }}
            
            // Global functions
            window.clearMap = function(mapId, fieldId) {{
                if (mapId === '{map_id}') {{
                    if (currentMarker_{map_id}) {{
                        map_{map_id}.removeLayer(currentMarker_{map_id});
                        currentMarker_{map_id} = null;
                    }}
                    drawnItems_{map_id}.clearLayers();
                    document.getElementById(fieldId).value = '';
                    document.getElementById(mapId + '-coordinates').textContent = 
                        'Click on map to set coordinates';
                }}
            }};
            
            window.getCurrentLocation = function(mapId, fieldId) {{
                if (mapId === '{map_id}' && navigator.geolocation) {{
                    navigator.geolocation.getCurrentPosition(function(position) {{
                        const lat = position.coords.latitude;
                        const lng = position.coords.longitude;
                        setMarker_{map_id}(lat, lng);
                        map_{map_id}.setView([lat, lng], 15);
                    }}, function(error) {{
                        alert('Error getting location: ' + error.message);
                    }});
                }}
            }};
            
            window.setMapMode = function(mapId, mode) {{
                if (mapId === '{map_id}') {{
                    mapMode_{map_id} = mode;
                    // Update UI to show active mode
                    document.querySelectorAll(`[onclick*="setMapMode('${{mapId}}',"]`).forEach(btn => {{
                        btn.classList.remove('active');
                    }});
                    document.querySelector(`[onclick*="setMapMode('${{mapId}}', '${{mode}}'"]`)
                           ?.classList.add('active');
                }}
            }};
            
            // Initialize when DOM is ready
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', initMap_{map_id});
            }} else {{
                initMap_{map_id}();
            }}
        }})();
        </script>
        '''
    
    def _get_leaflet_draw_controls(self, map_id: str) -> str:
        """Get Leaflet draw controls JavaScript."""
        return f'''
        drawControl_{map_id} = new L.Control.Draw({{
            edit: {{
                featureGroup: drawnItems_{map_id}
            }},
            draw: {{
                polygon: true,
                polyline: true,
                rectangle: true,
                circle: true,
                marker: true
            }}
        }});
        map_{map_id}.addControl(drawControl_{map_id});
        
        map_{map_id}.on(L.Draw.Event.CREATED, function(event) {{
            drawnItems_{map_id}.addLayer(event.layer);
            updateFieldValue_{map_id}();
        }});
        '''
    
    def _get_google_maps_css_js(self, map_id: str, field_id: str, current_value: MapData) -> str:
        """Get Google Maps-specific CSS and JavaScript."""
        api_key = current_app.config.get('GOOGLE_MAPS_API_KEY', '')
        
        return f'''
        <style>
        .map-field-container {{
            border: 1px solid #ddd;
            border-radius: 4px;
            overflow: hidden;
        }}
        .map-display {{
            position: relative;
        }}
        .map-controls {{
            padding: 10px;
            background-color: #f8f9fa;
            border-top: 1px solid #ddd;
        }}
        </style>
        
        <script src="https://maps.googleapis.com/maps/api/js?key={api_key}&libraries=drawing"></script>
        <script>
        // Google Maps implementation would go here
        // Similar structure to Leaflet but using Google Maps API
        </script>
        '''


class MapField(Field):
    """WTForms field for map data."""
    
    widget = MapWidget()
    
    def __init__(self, label=None, validators=None, provider=MapProvider.LEAFLET,
                 default_zoom=10, enable_drawing=True, enable_search=True, **kwargs):
        """Initialize map field."""
        super().__init__(label, validators, **kwargs)
        self.provider = provider
        self.default_zoom = default_zoom
        self.enable_drawing = enable_drawing
        self.enable_search = enable_search
        
        # Set custom widget with parameters
        self.widget = MapWidget(
            provider=provider,
            enable_drawing=enable_drawing,
            enable_search=enable_search
        )
    
    def process_formdata(self, valuelist):
        """Process form data from the hidden input."""
        if valuelist:
            try:
                self.data = MapData.from_json(valuelist[0])
            except (ValueError, TypeError):
                self.data = MapData(type='point')
        else:
            self.data = MapData(type='point')
    
    def _value(self):
        """Get string representation of the field value."""
        if self.data:
            if isinstance(self.data, MapData):
                return self.data.to_json()
            return str(self.data)
        return ''


def validate_coordinates(form, field):
    """Validator for coordinate data."""
    if not field.data:
        return
    
    if isinstance(field.data, MapData):
        # Validate points
        for point in field.data.points:
            if not (-90 <= point.latitude <= 90):
                raise ValidationError(f'Invalid latitude: {point.latitude}')
            if not (-180 <= point.longitude <= 180):
                raise ValidationError(f'Invalid longitude: {point.longitude}')
        
        # Validate areas
        for area in field.data.areas:
            if area.polygon:
                for lat, lng in area.polygon:
                    if not (-90 <= lat <= 90):
                        raise ValidationError(f'Invalid latitude in polygon: {lat}')
                    if not (-180 <= lng <= 180):
                        raise ValidationError(f'Invalid longitude in polygon: {lng}')


def validate_required_location(form, field):
    """Validator to ensure at least one location is specified."""
    if not field.data:
        raise ValidationError('Location is required')
    
    if isinstance(field.data, MapData):
        if not field.data.points and not field.data.areas and not field.data.routes:
            raise ValidationError('At least one location must be specified')


# PgAppForge integration helpers
class MapFieldWidget(BS3TextFieldWidget):
    """PgAppForge widget for map fields."""
    
    def __call__(self, field, **kwargs):
        """Render map widget."""
        map_widget = MapWidget()
        return map_widget(field, **kwargs)


# Utility functions
def create_point_map(latitude: float, longitude: float, zoom: int = 10, 
                    provider: MapProvider = MapProvider.LEAFLET) -> MapData:
    """Create a simple point map."""
    map_data = MapData(type='point', zoom_level=zoom, provider=provider)
    map_data.add_point(latitude, longitude)
    return map_data


def create_area_map(bounds: Dict[str, float], zoom: int = 10,
                   provider: MapProvider = MapProvider.LEAFLET) -> MapData:
    """Create a simple area map."""
    map_data = MapData(type='area', zoom_level=zoom, provider=provider)
    map_data.add_area(bounds=bounds)
    return map_data


def create_route_map(waypoints: List[Tuple[float, float]], zoom: int = 10,
                    provider: MapProvider = MapProvider.LEAFLET) -> MapData:
    """Create a simple route map."""
    map_data = MapData(type='route', zoom_level=zoom, provider=provider)
    map_data.add_route(waypoints)
    return map_data


def calculate_distance(point1: MapPoint, point2: MapPoint) -> float:
    """Calculate distance between two points in meters using Haversine formula."""
    import math
    
    # Convert latitude and longitude from degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [point1.latitude, point1.longitude,
                                                point2.latitude, point2.longitude])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in meters
    r = 6371000
    
    return c * r


def get_center_point(points: List[MapPoint]) -> MapPoint:
    """Calculate center point of multiple locations."""
    if not points:
        return MapPoint(0, 0)
    
    if len(points) == 1:
        return points[0]
    
    # Calculate centroid
    lat_sum = sum(p.latitude for p in points)
    lng_sum = sum(p.longitude for p in points)
    
    return MapPoint(
        latitude=lat_sum / len(points),
        longitude=lng_sum / len(points)
    )