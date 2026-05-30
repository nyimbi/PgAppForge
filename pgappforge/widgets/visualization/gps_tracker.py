"""
GPS Tracker Widget for PgForge

Provides real-time GPS tracking capabilities with interactive map display,
location history, geofencing, and route planning.
"""

from markupsafe import Markup
from wtforms.widgets import Input
from flask_babel import gettext as _


class GPSTrackerWidget(Input):
    """Advanced GPS tracker widget with real-time location tracking and mapping."""

    def __init__(self, map_provider='openstreetmap', enable_tracking=True,
                 enable_geofencing=True, enable_routes=True, enable_offline=True,
                 update_interval=5000, accuracy_threshold=10, battery_optimization=True,
                 enable_compass=True, enable_altitude=True, enable_speed=True,
                 center_lat=40.7128, center_lng=-74.0060, initial_zoom=13,
                 enable_clustering=True, max_history_points=1000, **kwargs):
        """
        Initialize GPS tracker widget.

        Args:
            map_provider: Map provider ('openstreetmap', 'google', 'mapbox')
            enable_tracking: Enable real-time GPS tracking
            enable_geofencing: Enable geofencing capabilities
            enable_routes: Enable route planning and navigation
            enable_offline: Enable offline map caching
            update_interval: GPS update interval in milliseconds
            accuracy_threshold: Minimum accuracy in meters
            battery_optimization: Enable battery optimization features
            enable_compass: Show compass/heading information
            enable_altitude: Track and display altitude
            enable_speed: Track and display speed
            center_lat: Initial map center latitude
            center_lng: Initial map center longitude
            initial_zoom: Initial map zoom level
            enable_clustering: Enable location point clustering
            max_history_points: Maximum location history points to store
        """
        super().__init__(**kwargs)
        self.map_provider = map_provider
        self.enable_tracking = enable_tracking
        self.enable_geofencing = enable_geofencing
        self.enable_routes = enable_routes
        self.enable_offline = enable_offline
        self.update_interval = update_interval
        self.accuracy_threshold = accuracy_threshold
        self.battery_optimization = battery_optimization
        self.enable_compass = enable_compass
        self.enable_altitude = enable_altitude
        self.enable_speed = enable_speed
        self.center_lat = center_lat
        self.center_lng = center_lng
        self.initial_zoom = initial_zoom
        self.enable_clustering = enable_clustering
        self.max_history_points = max_history_points

        # Map provider configurations
        self.map_configs = {
            'openstreetmap': {
                'tile_url': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                'attribution': '© OpenStreetMap contributors',
                'max_zoom': 19
            },
            'google': {
                'api_key_required': True,
                'max_zoom': 21
            },
            'mapbox': {
                'api_key_required': True,
                'tile_url': 'https://api.mapbox.com/styles/v1/{id}/tiles/{z}/{x}/{y}?access_token={accessToken}',
                'max_zoom': 22
            }
        }

        # Default geofences
        self.default_geofences = [
            {
                'id': 'office',
                'name': _('Office'),
                'type': 'circle',
                'center': [40.7589, -73.9851],
                'radius': 100,
                'color': '#007bff',
                'notifications': True
            },
            {
                'id': 'home',
                'name': _('Home'),
                'type': 'circle',
                'center': [40.7505, -73.9934],
                'radius': 50,
                'color': '#28a745',
                'notifications': True
            }
        ]

    def __call__(self, field, **kwargs):
        """Render the GPS tracker widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)

        tracker_id = f"gps_tracker_{field.id}"

        # Generate CSS styles
        css_styles = self._generate_css(tracker_id)

        # Generate controls panel
        controls_html = self._generate_controls(tracker_id)

        # Generate map container
        map_html = self._generate_map_container(tracker_id)

        # Generate info panels
        info_panels_html = self._generate_info_panels(tracker_id)

        # Generate modals
        modals_html = self._generate_modals(tracker_id)

        # Generate JavaScript
        javascript = self._generate_javascript(tracker_id)

        return Markup(f"""
        {css_styles}
        <div id="{tracker_id}" class="gps-tracker-container"
             data-provider="{self.map_provider}"
             data-tracking="{str(self.enable_tracking).lower()}"
             data-center="{self.center_lat},{self.center_lng}"
             data-zoom="{self.initial_zoom}">

            <!-- Tracker Header -->
            <div class="tracker-header">
                <div class="header-info">
                    <h5><i class="fas fa-map-marker-alt"></i> {_('GPS Tracker')}</h5>
                    <div class="status-indicators">
                        <span class="gps-status" id="{tracker_id}_gps_status">
                            <i class="fas fa-satellite-dish"></i> {_('Connecting...')}
                        </span>
                        <span class="accuracy" id="{tracker_id}_accuracy">
                            <i class="fas fa-crosshairs"></i> --m
                        </span>
                    </div>
                </div>
                <div class="header-actions">
                    <button class="btn btn-success" id="{tracker_id}_start_btn" onclick="startTracking('{tracker_id}')">
                        <i class="fas fa-play"></i> {_('Start')}
                    </button>
                    <button class="btn btn-danger" id="{tracker_id}_stop_btn" onclick="stopTracking('{tracker_id}')" style="display: none;">
                        <i class="fas fa-stop"></i> {_('Stop')}
                    </button>
                    <button class="btn btn-outline-secondary" onclick="centerOnLocation('{tracker_id}')">
                        <i class="fas fa-crosshairs"></i>
                    </button>
                </div>
            </div>

            <!-- Main Content -->
            <div class="tracker-main">
                <!-- Controls Panel -->
                {controls_html}

                <!-- Map Container -->
                {map_html}

                <!-- Info Panels -->
                {info_panels_html}
            </div>

            <!-- Status Bar -->
            <div class="tracker-status">
                <div class="status-info">
                    <span class="location-count" id="{tracker_id}_location_count">
                        <i class="fas fa-map-pin"></i> 0 {_('points')}
                    </span>
                    <span class="distance-traveled" id="{tracker_id}_distance">
                        <i class="fas fa-route"></i> 0 km
                    </span>
                    <span class="tracking-duration" id="{tracker_id}_duration">
                        <i class="fas fa-clock"></i> 00:00:00
                    </span>
                </div>
                <div class="status-actions">
                    <button class="btn btn-sm btn-outline-info" onclick="exportTrack('{tracker_id}')">
                        <i class="fas fa-download"></i> {_('Export')}
                    </button>
                    <button class="btn btn-sm btn-outline-warning" onclick="clearTrack('{tracker_id}')">
                        <i class="fas fa-trash"></i> {_('Clear')}
                    </button>
                </div>
            </div>

            <!-- Hidden input for form data -->
            <input type="hidden" id="{kwargs['id']}" name="{kwargs['name']}"
                   value="" data-gps-data="">
        </div>

        {modals_html}
        {javascript}
        """)

    def _generate_controls(self, tracker_id):
        """Generate the controls panel HTML."""
        tracking_controls = ""
        if self.enable_tracking:
            tracking_controls = f"""
            <div class="control-section">
                <h6><i class="fas fa-satellite"></i> {_('Tracking')}</h6>
                <div class="control-group">
                    <label>{_('Update Interval')}</label>
                    <select class="form-control" id="{tracker_id}_interval" onchange="updateInterval('{tracker_id}')">
                        <option value="1000">{_('1 second')}</option>
                        <option value="5000" selected>{_('5 seconds')}</option>
                        <option value="10000">{_('10 seconds')}</option>
                        <option value="30000">{_('30 seconds')}</option>
                        <option value="60000">{_('1 minute')}</option>
                    </select>
                </div>
                <div class="control-group">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="{tracker_id}_high_accuracy"
                               checked onchange="toggleHighAccuracy('{tracker_id}')">
                        <label class="form-check-label">{_('High Accuracy')}</label>
                    </div>
                </div>
                <div class="control-group">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="{tracker_id}_battery_save"
                               {'checked' if self.battery_optimization else ''} onchange="toggleBatterySave('{tracker_id}')">
                        <label class="form-check-label">{_('Battery Save')}</label>
                    </div>
                </div>
            </div>
            """

        geofencing_controls = ""
        if self.enable_geofencing:
            geofencing_controls = f"""
            <div class="control-section">
                <h6><i class="fas fa-shield-alt"></i> {_('Geofencing')}</h6>
                <div class="geofence-list" id="{tracker_id}_geofences">
                    <!-- Geofences will be populated here -->
                </div>
                <button class="btn btn-outline-primary btn-sm" onclick="addGeofence('{tracker_id}')">
                    <i class="fas fa-plus"></i> {_('Add Geofence')}
                </button>
            </div>
            """

        routes_controls = ""
        if self.enable_routes:
            routes_controls = f"""
            <div class="control-section">
                <h6><i class="fas fa-route"></i> {_('Routes')}</h6>
                <div class="route-controls">
                    <button class="btn btn-outline-info btn-sm" onclick="planRoute('{tracker_id}')">
                        <i class="fas fa-map-signs"></i> {_('Plan Route')}
                    </button>
                    <button class="btn btn-outline-success btn-sm" onclick="startNavigation('{tracker_id}')">
                        <i class="fas fa-directions"></i> {_('Navigate')}
                    </button>
                </div>
                <div class="route-info" id="{tracker_id}_route_info" style="display: none;">
                    <div class="route-distance">Distance: <span>--</span></div>
                    <div class="route-duration">Duration: <span>--</span></div>
                </div>
            </div>
            """

        return f"""
        <div class="tracker-controls">
            {tracking_controls}

            <div class="control-section">
                <h6><i class="fas fa-layer-group"></i> {_('Map Layers')}</h6>
                <div class="layer-controls">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="{tracker_id}_satellite"
                               onchange="toggleLayer('{tracker_id}', 'satellite')">
                        <label class="form-check-label">{_('Satellite')}</label>
                    </div>
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="{tracker_id}_traffic"
                               onchange="toggleLayer('{tracker_id}', 'traffic')">
                        <label class="form-check-label">{_('Traffic')}</label>
                    </div>
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="{tracker_id}_terrain"
                               onchange="toggleLayer('{tracker_id}', 'terrain')">
                        <label class="form-check-label">{_('Terrain')}</label>
                    </div>
                </div>
            </div>

            {geofencing_controls}
            {routes_controls}
        </div>
        """

    def _generate_map_container(self, tracker_id):
        """Generate the map container HTML."""
        return f"""
        <div class="map-container">
            <div id="{tracker_id}_map" class="gps-map"></div>

            <!-- Map overlays -->
            <div class="map-overlays">
                <!-- Compass -->
                <div class="compass" id="{tracker_id}_compass" style="{'display: block' if self.enable_compass else 'display: none'}">
                    <div class="compass-needle" id="{tracker_id}_needle"></div>
                    <div class="compass-text">N</div>
                </div>

                <!-- Speed indicator -->
                <div class="speed-indicator" id="{tracker_id}_speed" style="{'display: block' if self.enable_speed else 'display: none'}">
                    <div class="speed-value">0</div>
                    <div class="speed-unit">km/h</div>
                </div>

                <!-- Altitude indicator -->
                <div class="altitude-indicator" id="{tracker_id}_altitude" style="{'display: block' if self.enable_altitude else 'display: none'}">
                    <div class="altitude-value">--</div>
                    <div class="altitude-unit">m</div>
                </div>
            </div>

            <!-- Map controls -->
            <div class="map-controls">
                <button class="map-btn" onclick="zoomIn('{tracker_id}')" title="{_('Zoom In')}">
                    <i class="fas fa-plus"></i>
                </button>
                <button class="map-btn" onclick="zoomOut('{tracker_id}')" title="{_('Zoom Out')}">
                    <i class="fas fa-minus"></i>
                </button>
                <button class="map-btn" onclick="toggleFullscreen('{tracker_id}')" title="{_('Fullscreen')}">
                    <i class="fas fa-expand"></i>
                </button>
            </div>
        </div>
        """

    def _generate_info_panels(self, tracker_id):
        """Generate the info panels HTML."""
        return f"""
        <div class="tracker-info">
            <!-- Current Location -->
            <div class="info-panel">
                <h6><i class="fas fa-map-marker-alt"></i> {_('Current Location')}</h6>
                <div class="location-info" id="{tracker_id}_current_location">
                    <div class="coordinates">
                        <div>Lat: <span id="{tracker_id}_lat">--</span></div>
                        <div>Lng: <span id="{tracker_id}_lng">--</span></div>
                    </div>
                    <div class="address" id="{tracker_id}_address">{_('Getting address...')}</div>
                    <div class="timestamp" id="{tracker_id}_timestamp">--</div>
                </div>
            </div>

            <!-- Statistics -->
            <div class="info-panel">
                <h6><i class="fas fa-chart-line"></i> {_('Statistics')}</h6>
                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-label">{_('Max Speed')}</div>
                        <div class="stat-value" id="{tracker_id}_max_speed">0 km/h</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">{_('Avg Speed')}</div>
                        <div class="stat-value" id="{tracker_id}_avg_speed">0 km/h</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">{_('Total Distance')}</div>
                        <div class="stat-value" id="{tracker_id}_total_distance">0 km</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">{_('Points Recorded')}</div>
                        <div class="stat-value" id="{tracker_id}_points_count">0</div>
                    </div>
                </div>
            </div>

            <!-- Recent Locations -->
            <div class="info-panel">
                <h6><i class="fas fa-history"></i> {_('Recent Locations')}</h6>
                <div class="location-history" id="{tracker_id}_history">
                    <div class="no-history">{_('No location history yet')}</div>
                </div>
            </div>
        </div>
        """

    def _generate_modals(self, tracker_id):
        """Generate modal dialogs."""
        return f"""
        <!-- Geofence Modal -->
        <div class="modal fade" id="{tracker_id}_geofence_modal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">{_('Add Geofence')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <form id="{tracker_id}_geofence_form">
                            <div class="form-group">
                                <label>{_('Name')}</label>
                                <input type="text" class="form-control" name="name" required>
                            </div>
                            <div class="form-group">
                                <label>{_('Type')}</label>
                                <select class="form-control" name="type">
                                    <option value="circle">{_('Circle')}</option>
                                    <option value="polygon">{_('Polygon')}</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>{_('Radius (meters)')}</label>
                                <input type="number" class="form-control" name="radius" value="100" min="10" max="10000">
                            </div>
                            <div class="form-group">
                                <label>{_('Color')}</label>
                                <input type="color" class="form-control" name="color" value="#007bff">
                            </div>
                            <div class="form-check">
                                <input class="form-check-input" type="checkbox" name="notifications" checked>
                                <label class="form-check-label">{_('Enable Notifications')}</label>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">{_('Cancel')}</button>
                        <button type="button" class="btn btn-primary" onclick="saveGeofence('{tracker_id}')">{_('Save')}</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Route Planning Modal -->
        <div class="modal fade" id="{tracker_id}_route_modal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">{_('Route Planning')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="route-planning">
                            <div class="form-group">
                                <label>{_('Start Location')}</label>
                                <input type="text" class="form-control" id="{tracker_id}_route_start"
                                       placeholder="{_('Enter start address or use current location')}">
                            </div>
                            <div class="form-group">
                                <label>{_('End Location')}</label>
                                <input type="text" class="form-control" id="{tracker_id}_route_end"
                                       placeholder="{_('Enter destination address')}">
                            </div>
                            <div class="form-group">
                                <label>{_('Route Type')}</label>
                                <select class="form-control" id="{tracker_id}_route_type">
                                    <option value="fastest">{_('Fastest Route')}</option>
                                    <option value="shortest">{_('Shortest Route')}</option>
                                    <option value="avoid_highways">{_('Avoid Highways')}</option>
                                    <option value="avoid_tolls">{_('Avoid Tolls')}</option>
                                </select>
                            </div>
                            <div class="route-preview" id="{tracker_id}_route_preview">
                                <!-- Route preview will be shown here -->
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">{_('Cancel')}</button>
                        <button type="button" class="btn btn-info" onclick="calculateRoute('{tracker_id}')">{_('Calculate Route')}</button>
                        <button type="button" class="btn btn-primary" onclick="startRouteNavigation('{tracker_id}')">{_('Start Navigation')}</button>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_css(self, tracker_id):
        """Generate CSS styles for the GPS tracker widget."""
        return f"""
        <style>
        #{tracker_id}.gps-tracker-container {{
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            height: 600px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}

        #{tracker_id} .tracker-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
        }}

        #{tracker_id} .header-info h5 {{
            margin: 0;
            font-size: 16px;
            font-weight: 600;
            color: #495057;
        }}

        #{tracker_id} .status-indicators {{
            display: flex;
            gap: 16px;
            margin-top: 4px;
        }}

        #{tracker_id} .gps-status {{
            font-size: 12px;
            color: #6c757d;
        }}

        #{tracker_id} .gps-status.connected {{
            color: #28a745;
        }}

        #{tracker_id} .accuracy {{
            font-size: 12px;
            color: #6c757d;
        }}

        #{tracker_id} .header-actions {{
            display: flex;
            gap: 8px;
        }}

        #{tracker_id} .tracker-main {{
            display: flex;
            flex: 1;
            min-height: 0;
        }}

        #{tracker_id} .tracker-controls {{
            width: 280px;
            border-right: 1px solid #dee2e6;
            background: #fafafa;
            overflow-y: auto;
            padding: 16px;
        }}

        #{tracker_id} .control-section {{
            margin-bottom: 24px;
        }}

        #{tracker_id} .control-section h6 {{
            margin: 0 0 12px 0;
            font-size: 12px;
            font-weight: 600;
            color: #495057;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        #{tracker_id} .control-group {{
            margin-bottom: 12px;
        }}

        #{tracker_id} .control-group label {{
            display: block;
            font-size: 12px;
            font-weight: 500;
            color: #495057;
            margin-bottom: 4px;
        }}

        #{tracker_id} .form-control {{
            width: 100%;
            padding: 6px 10px;
            border: 1px solid #ced4da;
            border-radius: 4px;
            font-size: 13px;
            background: #fff;
            color: #495057;
        }}

        #{tracker_id} .form-check {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        #{tracker_id} .map-container {{
            flex: 2;
            position: relative;
            background: #e9ecef;
        }}

        #{tracker_id} .gps-map {{
            width: 100%;
            height: 100%;
        }}

        #{tracker_id} .map-overlays {{
            position: absolute;
            top: 16px;
            left: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            pointer-events: none;
        }}

        #{tracker_id} .compass {{
            width: 60px;
            height: 60px;
            background: rgba(255,255,255,0.9);
            border: 2px solid #007bff;
            border-radius: 50%;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        #{tracker_id} .compass-needle {{
            width: 2px;
            height: 20px;
            background: #dc3545;
            position: absolute;
            top: 8px;
            border-radius: 1px;
            transform-origin: bottom center;
            transition: transform 0.3s ease;
        }}

        #{tracker_id} .compass-text {{
            font-size: 10px;
            font-weight: bold;
            color: #007bff;
            position: absolute;
            top: 2px;
        }}

        #{tracker_id} .speed-indicator,
        #{tracker_id} .altitude-indicator {{
            background: rgba(0,0,0,0.8);
            color: white;
            padding: 8px 12px;
            border-radius: 6px;
            text-align: center;
            min-width: 60px;
        }}

        #{tracker_id} .speed-value,
        #{tracker_id} .altitude-value {{
            font-size: 18px;
            font-weight: bold;
            line-height: 1;
        }}

        #{tracker_id} .speed-unit,
        #{tracker_id} .altitude-unit {{
            font-size: 10px;
            opacity: 0.8;
        }}

        #{tracker_id} .map-controls {{
            position: absolute;
            top: 16px;
            right: 16px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}

        #{tracker_id} .map-btn {{
            width: 36px;
            height: 36px;
            background: rgba(255,255,255,0.9);
            border: 1px solid #dee2e6;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s ease;
        }}

        #{tracker_id} .map-btn:hover {{
            background: #fff;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        #{tracker_id} .tracker-info {{
            width: 280px;
            border-left: 1px solid #dee2e6;
            background: #fafafa;
            overflow-y: auto;
            padding: 16px;
        }}

        #{tracker_id} .info-panel {{
            margin-bottom: 20px;
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 12px;
        }}

        #{tracker_id} .info-panel h6 {{
            margin: 0 0 12px 0;
            font-size: 12px;
            font-weight: 600;
            color: #495057;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        #{tracker_id} .coordinates {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            font-family: monospace;
            color: #6c757d;
            margin-bottom: 8px;
        }}

        #{tracker_id} .address {{
            font-size: 13px;
            color: #495057;
            margin-bottom: 8px;
            line-height: 1.4;
        }}

        #{tracker_id} .timestamp {{
            font-size: 11px;
            color: #6c757d;
        }}

        #{tracker_id} .stats-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }}

        #{tracker_id} .stat-item {{
            text-align: center;
        }}

        #{tracker_id} .stat-label {{
            font-size: 10px;
            color: #6c757d;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }}

        #{tracker_id} .stat-value {{
            font-size: 14px;
            font-weight: 600;
            color: #495057;
        }}

        #{tracker_id} .location-history {{
            max-height: 200px;
            overflow-y: auto;
        }}

        #{tracker_id} .history-item {{
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            border-bottom: 1px solid #f1f3f4;
            font-size: 12px;
        }}

        #{tracker_id} .history-time {{
            color: #6c757d;
        }}

        #{tracker_id} .no-history {{
            text-align: center;
            color: #6c757d;
            font-style: italic;
            padding: 20px 0;
        }}

        #{tracker_id} .tracker-status {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 16px;
            background: #f8f9fa;
            border-top: 1px solid #dee2e6;
            font-size: 12px;
        }}

        #{tracker_id} .status-info {{
            display: flex;
            gap: 16px;
            color: #6c757d;
        }}

        #{tracker_id} .status-actions {{
            display: flex;
            gap: 8px;
        }}

        #{tracker_id} .btn {{
            padding: 4px 8px;
            font-size: 12px;
            border-radius: 4px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}

        #{tracker_id} .btn-success {{
            background: #28a745;
            color: white;
            border-color: #28a745;
        }}

        #{tracker_id} .btn-danger {{
            background: #dc3545;
            color: white;
            border-color: #dc3545;
        }}

        #{tracker_id} .btn-outline-secondary {{
            color: #6c757d;
            border-color: #6c757d;
            background: transparent;
        }}

        #{tracker_id} .btn-outline-primary {{
            color: #007bff;
            border-color: #007bff;
            background: transparent;
        }}

        #{tracker_id} .btn-outline-info {{
            color: #17a2b8;
            border-color: #17a2b8;
            background: transparent;
        }}

        #{tracker_id} .geofence-list {{
            margin-bottom: 12px;
        }}

        #{tracker_id} .geofence-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px;
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            margin-bottom: 6px;
        }}

        #{tracker_id} .geofence-info {{
            flex: 1;
        }}

        #{tracker_id} .geofence-name {{
            font-size: 13px;
            font-weight: 500;
            color: #495057;
        }}

        #{tracker_id} .geofence-details {{
            font-size: 11px;
            color: #6c757d;
        }}

        #{tracker_id} .geofence-color {{
            width: 16px;
            height: 16px;
            border-radius: 50%;
            margin-right: 8px;
        }}

        /* Responsive design */
        @media (max-width: 768px) {{
            #{tracker_id} .tracker-main {{
                flex-direction: column;
            }}

            #{tracker_id} .tracker-controls,
            #{tracker_id} .tracker-info {{
                width: 100%;
                border: none;
                border-bottom: 1px solid #dee2e6;
                max-height: 150px;
            }}

            #{tracker_id} .map-container {{
                height: 300px;
            }}
        }}
        </style>
        """

    def _generate_javascript(self, tracker_id):
        """Generate JavaScript for GPS tracker functionality."""
        import json
        map_config = self.map_configs.get(self.map_provider, self.map_configs['openstreetmap'])
        geofences_json = json.dumps(self.default_geofences)

        return f"""
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script>
        (function() {{
            // GPS tracker state
            let gpsTrackerState = {{
                map: null,
                tracking: false,
                watchId: null,
                currentPosition: null,
                locationHistory: [],
                geofences: {geofences_json},
                route: null,
                startTime: null,
                stats: {{
                    totalDistance: 0,
                    maxSpeed: 0,
                    avgSpeed: 0
                }}
            }};

            // Initialize GPS tracker
            function initializeGPSTracker() {{
                // Initialize map
                const mapContainer = document.getElementById('{tracker_id}_map');
                gpsTrackerState.map = L.map(mapContainer).setView([{self.center_lat}, {self.center_lng}], {self.initial_zoom});

                // Add tile layer
                L.tileLayer('{map_config.get("tile_url", "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png")}', {{
                    attribution: '{map_config.get("attribution", "© OpenStreetMap contributors")}',
                    maxZoom: {map_config.get("max_zoom", 19)}
                }}).addTo(gpsTrackerState.map);

                // Initialize geofences
                initializeGeofences();

                // Check GPS availability
                checkGPSAvailability();

                // Update UI
                updateUI();
            }}

            // Check GPS availability
            function checkGPSAvailability() {{
                if ('geolocation' in navigator) {{
                    updateGPSStatus('available', '{_("GPS Available")}');
                }} else {{
                    updateGPSStatus('unavailable', '{_("GPS Not Available")}');
                }}
            }}

            // Start tracking
            window.startTracking = function(trackerId) {{
                if (trackerId !== '{tracker_id}') return;

                if (!navigator.geolocation) {{
                    alert('{_("GPS not supported by this browser")}');
                    return;
                }}

                const options = {{
                    enableHighAccuracy: document.getElementById('{tracker_id}_high_accuracy').checked,
                    timeout: 10000,
                    maximumAge: 0
                }};

                gpsTrackerState.watchId = navigator.geolocation.watchPosition(
                    onLocationUpdate,
                    onLocationError,
                    options
                );

                gpsTrackerState.tracking = true;
                gpsTrackerState.startTime = new Date();
                updateGPSStatus('tracking', '{_("Tracking Active")}');
                updateUI();
            }};

            // Stop tracking
            window.stopTracking = function(trackerId) {{
                if (trackerId !== '{tracker_id}') return;

                if (gpsTrackerState.watchId) {{
                    navigator.geolocation.clearWatch(gpsTrackerState.watchId);
                    gpsTrackerState.watchId = null;
                }}

                gpsTrackerState.tracking = false;
                updateGPSStatus('stopped', '{_("Tracking Stopped")}');
                updateUI();
            }};

            // Handle location updates
            function onLocationUpdate(position) {{
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                const accuracy = position.coords.accuracy;
                const speed = position.coords.speed || 0;
                const heading = position.coords.heading;
                const altitude = position.coords.altitude;

                // Update current position
                gpsTrackerState.currentPosition = {{
                    lat: lat,
                    lng: lng,
                    accuracy: accuracy,
                    speed: speed,
                    heading: heading,
                    altitude: altitude,
                    timestamp: new Date()
                }};

                // Add to history
                if (accuracy <= {self.accuracy_threshold}) {{
                    addLocationToHistory(gpsTrackerState.currentPosition);
                }}

                // Update map
                updateMapLocation(lat, lng, accuracy);

                // Update UI elements
                updateLocationDisplay();
                updateCompass(heading);
                updateSpeedDisplay(speed);
                updateAltitudeDisplay(altitude);
                updateAccuracy(accuracy);

                // Check geofences
                checkGeofences(lat, lng);

                // Update statistics
                updateStatistics();

                // Update form data
                updateFormData();
            }}

            // Handle location errors
            function onLocationError(error) {{
                let message = '';
                switch (error.code) {{
                    case error.PERMISSION_DENIED:
                        message = '{_("GPS access denied")}';
                        break;
                    case error.POSITION_UNAVAILABLE:
                        message = '{_("GPS position unavailable")}';
                        break;
                    case error.TIMEOUT:
                        message = '{_("GPS request timeout")}';
                        break;
                    default:
                        message = '{_("Unknown GPS error")}';
                        break;
                }}

                updateGPSStatus('error', message);
                console.error('GPS Error:', error);
            }}

            // Add location to history
            function addLocationToHistory(location) {{
                gpsTrackerState.locationHistory.push(location);

                // Limit history size
                if (gpsTrackerState.locationHistory.length > {self.max_history_points}) {{
                    gpsTrackerState.locationHistory.shift();
                }}

                // Update history display
                updateLocationHistory();
            }}

            // Update map with current location
            function updateMapLocation(lat, lng, accuracy) {{
                // Remove existing markers
                gpsTrackerState.map.eachLayer(layer => {{
                    if (layer instanceof L.CircleMarker && layer.options.isCurrentLocation) {{
                        gpsTrackerState.map.removeLayer(layer);
                    }}
                }});

                // Add current position marker
                L.circleMarker([lat, lng], {{
                    color: '#007bff',
                    fillColor: '#007bff',
                    fillOpacity: 0.7,
                    radius: 8,
                    isCurrentLocation: true
                }}).addTo(gpsTrackerState.map);

                // Add accuracy circle
                L.circle([lat, lng], {{
                    color: '#007bff',
                    fillColor: '#007bff',
                    fillOpacity: 0.1,
                    radius: accuracy,
                    isCurrentLocation: true
                }}).addTo(gpsTrackerState.map);

                // Draw track if history exists
                if (gpsTrackerState.locationHistory.length > 1) {{
                    const trackPoints = gpsTrackerState.locationHistory.map(loc => [loc.lat, loc.lng]);

                    // Remove existing track
                    gpsTrackerState.map.eachLayer(layer => {{
                        if (layer instanceof L.Polyline && layer.options.isTrack) {{
                            gpsTrackerState.map.removeLayer(layer);
                        }}
                    }});

                    // Add new track
                    L.polyline(trackPoints, {{
                        color: '#dc3545',
                        weight: 3,
                        opacity: 0.8,
                        isTrack: true
                    }}).addTo(gpsTrackerState.map);
                }}
            }}

            // Update location display
            function updateLocationDisplay() {{
                const pos = gpsTrackerState.currentPosition;
                if (!pos) return;

                document.getElementById('{tracker_id}_lat').textContent = pos.lat.toFixed(6);
                document.getElementById('{tracker_id}_lng').textContent = pos.lng.toFixed(6);
                document.getElementById('{tracker_id}_timestamp').textContent = pos.timestamp.toLocaleString();

                // Reverse geocoding for address
                reverseGeocode(pos.lat, pos.lng);
            }}

            // Reverse geocoding
            function reverseGeocode(lat, lng) {{
                fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${{lat}}&lon=${{lng}}`)
                    .then(response => response.json())
                    .then(data => {{
                        const address = data.display_name || '{_("Address not found")}';
                        document.getElementById('{tracker_id}_address').textContent = address;
                    }})
                    .catch(() => {{
                        document.getElementById('{tracker_id}_address').textContent = '{_("Address lookup failed")}';
                    }});
            }}

            // Update compass
            function updateCompass(heading) {{
                if (heading !== null && heading !== undefined) {{
                    const needle = document.getElementById('{tracker_id}_needle');
                    if (needle) {{
                        needle.style.transform = `rotate(${{heading}}deg)`;
                    }}
                }}
            }}

            // Update speed display
            function updateSpeedDisplay(speed) {{
                const speedKmh = (speed || 0) * 3.6; // Convert m/s to km/h
                const speedElement = document.querySelector('#{tracker_id} .speed-value');
                if (speedElement) {{
                    speedElement.textContent = Math.round(speedKmh);
                }}
            }}

            // Update altitude display
            function updateAltitudeDisplay(altitude) {{
                const altElement = document.querySelector('#{tracker_id} .altitude-value');
                if (altElement) {{
                    altElement.textContent = altitude ? Math.round(altitude) : '--';
                }}
            }}

            // Update accuracy display
            function updateAccuracy(accuracy) {{
                const accuracyElement = document.getElementById('{tracker_id}_accuracy');
                if (accuracyElement) {{
                    accuracyElement.innerHTML = `<i class="fas fa-crosshairs"></i> ${{Math.round(accuracy)}}m`;
                }}
            }}

            // Update GPS status
            function updateGPSStatus(status, message) {{
                const statusElement = document.getElementById('{tracker_id}_gps_status');
                if (statusElement) {{
                    statusElement.innerHTML = `<i class="fas fa-satellite-dish"></i> ${{message}}`;
                    statusElement.className = `gps-status ${{status}}`;
                }}
            }}

            // Update UI state
            function updateUI() {{
                const startBtn = document.getElementById('{tracker_id}_start_btn');
                const stopBtn = document.getElementById('{tracker_id}_stop_btn');

                if (gpsTrackerState.tracking) {{
                    startBtn.style.display = 'none';
                    stopBtn.style.display = 'inline-flex';
                }} else {{
                    startBtn.style.display = 'inline-flex';
                    stopBtn.style.display = 'none';
                }}
            }}

            // Initialize geofences
            function initializeGeofences() {{
                gpsTrackerState.geofences.forEach(geofence => {{
                    addGeofenceToMap(geofence);
                }});

                updateGeofenceList();
            }}

            // Add geofence to map
            function addGeofenceToMap(geofence) {{
                if (geofence.type === 'circle') {{
                    L.circle(geofence.center, {{
                        color: geofence.color,
                        fillColor: geofence.color,
                        fillOpacity: 0.2,
                        radius: geofence.radius,
                        geofenceId: geofence.id
                    }}).addTo(gpsTrackerState.map);
                }}
            }}

            // Check geofences
            function checkGeofences(lat, lng) {{
                gpsTrackerState.geofences.forEach(geofence => {{
                    if (geofence.type === 'circle') {{
                        const distance = calculateDistance(
                            lat, lng,
                            geofence.center[0], geofence.center[1]
                        );

                        if (distance <= geofence.radius && geofence.notifications) {{
                            showGeofenceNotification(geofence, 'entered');
                        }}
                    }}
                }});
            }}

            // Calculate distance between two points
            function calculateDistance(lat1, lng1, lat2, lng2) {{
                const R = 6371000; // Earth's radius in meters
                const dLat = (lat2 - lat1) * Math.PI / 180;
                const dLng = (lng2 - lng1) * Math.PI / 180;
                const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                          Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                          Math.sin(dLng/2) * Math.sin(dLng/2);
                const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                return R * c;
            }}

            // Show geofence notification
            function showGeofenceNotification(geofence, action) {{
                // Implementation for geofence notifications
                console.log(`${{action}} geofence: ${{geofence.name}}`);
            }}

            // Update statistics
            function updateStatistics() {{
                if (gpsTrackerState.locationHistory.length < 2) return;

                const history = gpsTrackerState.locationHistory;
                const latest = history[history.length - 1];
                const previous = history[history.length - 2];

                // Calculate distance
                const distance = calculateDistance(
                    previous.lat, previous.lng,
                    latest.lat, latest.lng
                );

                gpsTrackerState.stats.totalDistance += distance / 1000; // Convert to km

                // Update speed statistics
                const currentSpeed = (latest.speed || 0) * 3.6; // Convert to km/h
                if (currentSpeed > gpsTrackerState.stats.maxSpeed) {{
                    gpsTrackerState.stats.maxSpeed = currentSpeed;
                }}

                // Calculate average speed
                const timeDiff = (latest.timestamp - gpsTrackerState.startTime) / 1000 / 3600; // hours
                gpsTrackerState.stats.avgSpeed = gpsTrackerState.stats.totalDistance / timeDiff;

                // Update displays
                updateStatsDisplay();
            }}

            // Update statistics display
            function updateStatsDisplay() {{
                const stats = gpsTrackerState.stats;

                document.getElementById('{tracker_id}_max_speed').textContent = `${{Math.round(stats.maxSpeed)}} km/h`;
                document.getElementById('{tracker_id}_avg_speed').textContent = `${{Math.round(stats.avgSpeed)}} km/h`;
                document.getElementById('{tracker_id}_total_distance').textContent = `${{stats.totalDistance.toFixed(2)}} km`;
                document.getElementById('{tracker_id}_points_count').textContent = gpsTrackerState.locationHistory.length;

                // Update status bar
                document.getElementById('{tracker_id}_location_count').innerHTML =
                    `<i class="fas fa-map-pin"></i> ${{gpsTrackerState.locationHistory.length}} {_("points")}`;
                document.getElementById('{tracker_id}_distance').innerHTML =
                    `<i class="fas fa-route"></i> ${{stats.totalDistance.toFixed(1)}} km`;

                // Update duration
                if (gpsTrackerState.startTime) {{
                    const duration = new Date() - gpsTrackerState.startTime;
                    const hours = Math.floor(duration / 3600000);
                    const minutes = Math.floor((duration % 3600000) / 60000);
                    const seconds = Math.floor((duration % 60000) / 1000);
                    document.getElementById('{tracker_id}_duration').innerHTML =
                        `<i class="fas fa-clock"></i> ${{hours.toString().padStart(2, '0')}}:${{minutes.toString().padStart(2, '0')}}:${{seconds.toString().padStart(2, '0')}}`;
                }}
            }}

            // Update location history display
            function updateLocationHistory() {{
                const historyContainer = document.getElementById('{tracker_id}_history');

                if (gpsTrackerState.locationHistory.length === 0) {{
                    historyContainer.innerHTML = '<div class="no-history">{_("No location history yet")}</div>';
                    return;
                }}

                const recentLocations = gpsTrackerState.locationHistory.slice(-10).reverse();
                const historyHtml = recentLocations.map(location => {{
                    return `
                        <div class="history-item">
                            <div>${{location.lat.toFixed(4)}}, ${{location.lng.toFixed(4)}}</div>
                            <div class="history-time">${{location.timestamp.toLocaleTimeString()}}</div>
                        </div>
                    `;
                }}).join('');

                historyContainer.innerHTML = historyHtml;
            }}

            // Update geofence list
            function updateGeofenceList() {{
                const container = document.getElementById('{tracker_id}_geofences');

                const geofenceHtml = gpsTrackerState.geofences.map(geofence => {{
                    return `
                        <div class="geofence-item">
                            <div class="geofence-color" style="background-color: ${{geofence.color}}"></div>
                            <div class="geofence-info">
                                <div class="geofence-name">${{geofence.name}}</div>
                                <div class="geofence-details">${{geofence.type}} - ${{geofence.radius}}m</div>
                            </div>
                            <button class="btn btn-sm btn-outline-danger" onclick="removeGeofence('${{geofence.id}}')">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    `;
                }}).join('');

                container.innerHTML = geofenceHtml;
            }}

            // Center map on current location
            window.centerOnLocation = function(trackerId) {{
                if (trackerId !== '{tracker_id}') return;

                if (gpsTrackerState.currentPosition) {{
                    gpsTrackerState.map.setView([
                        gpsTrackerState.currentPosition.lat,
                        gpsTrackerState.currentPosition.lng
                    ], 16);
                }}
            }};

            // Update form data
            function updateFormData() {{
                const input = document.querySelector('#{tracker_id} input[data-gps-data]');
                if (input) {{
                    const data = {{
                        tracking: gpsTrackerState.tracking,
                        currentPosition: gpsTrackerState.currentPosition,
                        locationHistory: gpsTrackerState.locationHistory,
                        stats: gpsTrackerState.stats
                    }};
                    input.value = JSON.stringify(data);
                }}
            }}

            // Initialize when page loads
            document.addEventListener('DOMContentLoaded', initializeGPSTracker);
        }})();
        </script>
        """