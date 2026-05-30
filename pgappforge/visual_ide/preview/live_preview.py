"""
Live Preview Engine for Visual IDE.

Provides real-time preview capabilities for visually developed applications,
allowing developers to see changes instantly as they build their views.
"""

import os
import time
import threading
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request
from werkzeug.serving import WSGIRequestHandler
from dataclasses import dataclass
import socketio
import eventlet

from ..models.project_model import ViewDefinition, IDEProject
from ..generators.code_generator import VisualCodeGenerator

logger = logging.getLogger(__name__)


@dataclass
class PreviewConfiguration:
    """Configuration for the live preview engine."""
    host: str = "localhost"
    port: int = 5001
    debug: bool = True
    auto_reload: bool = True
    enable_websockets: bool = True
    preview_theme: str = "bootstrap"
    mock_data: bool = True


class MockDataProvider:
    """Provides mock data for preview purposes."""
    
    def __init__(self):
        self.mock_datasets = {
            'users': [
                {'id': 1, 'name': 'John Doe', 'email': 'john@example.com', 'status': 'Active'},
                {'id': 2, 'name': 'Jane Smith', 'email': 'jane@example.com', 'status': 'Inactive'},
                {'id': 3, 'name': 'Bob Johnson', 'email': 'bob@example.com', 'status': 'Active'},
            ],
            'products': [
                {'id': 1, 'name': 'Product A', 'price': 29.99, 'category': 'Electronics'},
                {'id': 2, 'name': 'Product B', 'price': 49.99, 'category': 'Books'},
                {'id': 3, 'name': 'Product C', 'price': 19.99, 'category': 'Clothing'},
            ],
            'orders': [
                {'id': 1, 'customer': 'John Doe', 'total': 99.97, 'status': 'Completed'},
                {'id': 2, 'customer': 'Jane Smith', 'total': 149.98, 'status': 'Processing'},
                {'id': 3, 'customer': 'Bob Johnson', 'total': 75.50, 'status': 'Shipped'},
            ]
        }
    
    def get_mock_data(self, dataset_name: str, count: int = None) -> List[Dict[str, Any]]:
        """Get mock data for a dataset."""
        data = self.mock_datasets.get(dataset_name.lower(), [])
        if count:
            return data[:count]
        return data
    
    def generate_chart_data(self, chart_type: str) -> Dict[str, Any]:
        """Generate mock data for charts."""
        if chart_type == 'line':
            return {
                'labels': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                'datasets': [{
                    'label': 'Sample Data',
                    'data': [65, 59, 80, 81, 56, 55],
                    'borderColor': 'rgb(75, 192, 192)',
                    'backgroundColor': 'rgba(75, 192, 192, 0.2)'
                }]
            }
        elif chart_type == 'bar':
            return {
                'labels': ['Red', 'Blue', 'Yellow', 'Green', 'Purple', 'Orange'],
                'datasets': [{
                    'label': '# of Votes',
                    'data': [12, 19, 3, 5, 2, 3],
                    'backgroundColor': [
                        'rgba(255, 99, 132, 0.2)',
                        'rgba(54, 162, 235, 0.2)',
                        'rgba(255, 205, 86, 0.2)',
                        'rgba(75, 192, 192, 0.2)',
                        'rgba(153, 102, 255, 0.2)',
                        'rgba(255, 159, 64, 0.2)'
                    ]
                }]
            }
        elif chart_type == 'pie':
            return {
                'labels': ['Red', 'Blue', 'Yellow'],
                'datasets': [{
                    'data': [300, 50, 100],
                    'backgroundColor': ['#FF6384', '#36A2EB', '#FFCE56']
                }]
            }
        else:
            return {'labels': [], 'datasets': []}


class LivePreviewEngine:
    """
    Real-time preview engine for visual development.
    
    Runs a separate Flask application that serves live previews of views
    being developed in the visual IDE. Updates in real-time as components
    are added, modified, or removed.
    """
    
    def __init__(self, config: Optional[PreviewConfiguration] = None):
        self.config = config or PreviewConfiguration()
        self.preview_app: Optional[Flask] = None
        self.socketio: Optional[socketio.Server] = None
        self.server_thread: Optional[threading.Thread] = None
        self.is_running = False
        
        # Preview state
        self.current_views: Dict[str, ViewDefinition] = {}
        self.current_project: Optional[IDEProject] = None
        self.code_generator: Optional[VisualCodeGenerator] = None
        self.mock_data_provider = MockDataProvider()
        
        # WebSocket clients
        self.connected_clients: Set[str] = set()
        
        logger.info("Live preview engine initialized")
    
    def start_server(self, port: Optional[int] = None) -> bool:
        """
        Start the live preview server.
        
        Args:
            port: Port to run the server on
            
        Returns:
            True if server started successfully
        """
        if self.is_running:
            logger.warning("Preview server is already running")
            return True
        
        try:
            if port:
                self.config.port = port
            
            # Create Flask app for preview
            self._create_preview_app()
            
            # Start server in separate thread
            self.server_thread = threading.Thread(
                target=self._run_server,
                daemon=True
            )
            self.server_thread.start()
            
            # Wait a moment for server to start
            time.sleep(1)
            
            self.is_running = True
            logger.info(f"Live preview server started on http://{self.config.host}:{self.config.port}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start preview server: {e}")
            return False
    
    def stop_server(self) -> bool:
        """
        Stop the live preview server.
        
        Returns:
            True if server stopped successfully
        """
        if not self.is_running:
            return True
        
        try:
            self.is_running = False
            
            # Notify connected clients
            if self.socketio:
                self.socketio.emit('server_shutdown', broadcast=True)
            
            logger.info("Live preview server stopped")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop preview server: {e}")
            return False
    
    def _create_preview_app(self):
        """Create the Flask application for live preview."""
        self.preview_app = Flask(__name__, 
                                template_folder='templates',
                                static_folder='static')
        
        # Configure app
        self.preview_app.config['DEBUG'] = self.config.debug
        self.preview_app.config['SECRET_KEY'] = 'preview-secret-key'
        
        # Initialize SocketIO for real-time updates
        if self.config.enable_websockets:
            self.socketio = socketio.Server(cors_allowed_origins="*")
            self.preview_app.wsgi_app = socketio.WSGIApp(self.socketio, self.preview_app.wsgi_app)
            self._setup_socketio_handlers()
        
        # Setup routes
        self._setup_routes()
        
        logger.info("Preview Flask application created")
    
    def _setup_routes(self):
        """Setup Flask routes for the preview server."""
        
        @self.preview_app.route('/')
        def index():
            """Main preview index page."""
            return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>PgForge Visual IDE - Live Preview</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-3 bg-light">
                <h4>Views</h4>
                <div id="view-list">
                    {% for view_name in views %}
                    <div class="list-group-item">
                        <a href="/preview/{{ view_name }}">{{ view_name }}</a>
                    </div>
                    {% endfor %}
                </div>
            </div>
            <div class="col-md-9">
                <div id="preview-content">
                    <div class="text-center mt-5">
                        <h2>Select a view to preview</h2>
                        <p class="text-muted">Choose a view from the sidebar to see the live preview</p>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const socket = io();
        
        socket.on('view_updated', function(data) {
            if (window.location.pathname === `/preview/${data.view_name}`) {
                location.reload();
            } else {
                // Update view list if needed
                updateViewList();
            }
        });
        
        socket.on('project_updated', function(data) {
            updateViewList();
        });
        
        function updateViewList() {
            fetch('/api/views')
                .then(response => response.json())
                .then(data => {
                    const viewList = document.getElementById('view-list');
                    viewList.innerHTML = '';
                    data.views.forEach(viewName => {
                        const item = document.createElement('div');
                        item.className = 'list-group-item';
                        item.innerHTML = `<a href="/preview/${viewName}">${viewName}</a>`;
                        viewList.appendChild(item);
                    });
                });
        }
    </script>
</body>
</html>
            """, views=list(self.current_views.keys()))
        
        @self.preview_app.route('/preview/<view_name>')
        def preview_view(view_name):
            """Preview a specific view."""
            if view_name not in self.current_views:
                return f"View '{view_name}' not found", 404
            
            view_def = self.current_views[view_name]
            
            # Generate HTML for the view
            html_content = self._generate_preview_html(view_def)
            
            return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>{{ view_name }} - Preview</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .preview-header {
            background: #f8f9fa;
            padding: 1rem;
            border-bottom: 1px solid #dee2e6;
            margin-bottom: 1rem;
        }
        {{ custom_css | safe }}
    </style>
</head>
<body>
    <div class="preview-header">
        <div class="row align-items-center">
            <div class="col">
                <h4 class="mb-0">{{ view_name }} <span class="badge bg-secondary">Preview</span></h4>
                <small class="text-muted">{{ view_type }}</small>
            </div>
            <div class="col-auto">
                <a href="/" class="btn btn-outline-secondary btn-sm">← Back to Index</a>
            </div>
        </div>
    </div>
    
    <div class="container-fluid">
        {{ html_content | safe }}
    </div>
    
    <script>
        const socket = io();
        
        socket.on('view_updated', function(data) {
            if (data.view_name === '{{ view_name }}') {
                location.reload();
            }
        });
        
        // Initialize any charts
        {{ chart_js | safe }}
    </script>
</body>
</html>
            """, 
            view_name=view_name,
            view_type=view_def.view_type.value,
            html_content=html_content,
            custom_css=self._generate_preview_css(view_def),
            chart_js=self._generate_preview_js(view_def)
            )
        
        @self.preview_app.route('/api/views')
        def api_views():
            """API endpoint to get available views."""
            return jsonify({
                'views': list(self.current_views.keys()),
                'project': self.current_project.name if self.current_project else None
            })
        
        @self.preview_app.route('/api/mock-data/<dataset>')
        def api_mock_data(dataset):
            """API endpoint to get mock data."""
            count = request.args.get('count', type=int)
            data = self.mock_data_provider.get_mock_data(dataset, count)
            return jsonify({'data': data})
        
        @self.preview_app.route('/api/chart-data/<chart_type>')
        def api_chart_data(chart_type):
            """API endpoint to get mock chart data."""
            data = self.mock_data_provider.generate_chart_data(chart_type)
            return jsonify(data)
    
    def _setup_socketio_handlers(self):
        """Setup SocketIO event handlers."""
        
        @self.socketio.event
        def connect(sid, environ):
            """Handle client connection."""
            self.connected_clients.add(sid)
            logger.info(f"Client {sid} connected to live preview")
        
        @self.socketio.event
        def disconnect(sid):
            """Handle client disconnection."""
            self.connected_clients.discard(sid)
            logger.info(f"Client {sid} disconnected from live preview")
    
    def _run_server(self):
        """Run the preview server."""
        try:
            if self.config.enable_websockets:
                # Run with SocketIO support
                eventlet.wsgi.server(
                    eventlet.listen((self.config.host, self.config.port)),
                    self.preview_app,
                    log_output=False
                )
            else:
                # Run standard Flask server
                self.preview_app.run(
                    host=self.config.host,
                    port=self.config.port,
                    debug=self.config.debug,
                    use_reloader=False,
                    threaded=True
                )
        except Exception as e:
            logger.error(f"Preview server error: {e}")
            self.is_running = False
    
    # View Management
    def update_view(self, view_name: str, view_definition: ViewDefinition):
        """
        Update a view in the live preview.
        
        Args:
            view_name: Name of the view to update
            view_definition: Updated view definition
        """
        self.current_views[view_name] = view_definition
        
        # Notify connected clients
        if self.socketio and self.connected_clients:
            self.socketio.emit('view_updated', {
                'view_name': view_name,
                'timestamp': time.time()
            })
        
        logger.info(f"Updated view in live preview: {view_name}")
    
    def remove_view(self, view_name: str):
        """
        Remove a view from the live preview.
        
        Args:
            view_name: Name of the view to remove
        """
        if view_name in self.current_views:
            del self.current_views[view_name]
            
            # Notify connected clients
            if self.socketio and self.connected_clients:
                self.socketio.emit('view_removed', {
                    'view_name': view_name,
                    'timestamp': time.time()
                })
            
            logger.info(f"Removed view from live preview: {view_name}")
    
    def update_project(self, project: IDEProject):
        """
        Update the entire project in the live preview.
        
        Args:
            project: Updated project definition
        """
        self.current_project = project
        self.current_views = project.views.copy()
        
        # Notify connected clients
        if self.socketio and self.connected_clients:
            self.socketio.emit('project_updated', {
                'project_name': project.name,
                'view_count': len(project.views),
                'timestamp': time.time()
            })
        
        logger.info(f"Updated project in live preview: {project.name}")
    
    # HTML Generation for Preview
    def _generate_preview_html(self, view_definition: ViewDefinition) -> str:
        """Generate HTML content for view preview."""
        if not self.code_generator:
            self.code_generator = VisualCodeGenerator(Path('/tmp/preview_gen'))
        
        try:
            # Generate component HTML similar to code generator
            html_parts = []
            
            # Add layout container
            if view_definition.layout.layout_type == "grid":
                html_parts.append('<div class="container-fluid">')
            
            # Generate root components
            for component_id in view_definition.root_components:
                component = view_definition.get_component(component_id)
                if component:
                    component_html = self._generate_component_preview_html(component, view_definition)
                    html_parts.append(component_html)
            
            if view_definition.layout.layout_type == "grid":
                html_parts.append('</div>')
            
            return '\n'.join(html_parts)
            
        except Exception as e:
            logger.error(f"Failed to generate preview HTML: {e}")
            return f"<div class='alert alert-danger'>Error generating preview: {e}</div>"
    
    def _generate_component_preview_html(self, component, view_definition) -> str:
        """Generate preview HTML for a single component with mock data."""
        from ..components.component_library import ComponentType
        
        # Handle different component types with mock data
        if component.component_type == ComponentType.DATA_TABLE:
            return self._generate_table_preview(component)
        elif component.component_type == ComponentType.CHART:
            return self._generate_chart_preview(component)
        elif component.component_type == ComponentType.CARD:
            return self._generate_card_preview(component, view_definition)
        elif component.component_type == ComponentType.TEXT_FIELD:
            return self._generate_text_field_preview(component)
        elif component.component_type == ComponentType.BUTTON:
            return self._generate_button_preview(component)
        else:
            return f'<div class="alert alert-info">Component: {component.component_type.value} (ID: {component.component_id})</div>'
    
    def _generate_table_preview(self, component) -> str:
        """Generate preview HTML for data table."""
        mock_data = self.mock_data_provider.get_mock_data('users', 5)
        
        html = ['<div class="table-responsive">']
        html.append('<table class="table table-striped table-hover">')
        
        # Header
        if mock_data:
            html.append('<thead><tr>')
            for key in mock_data[0].keys():
                html.append(f'<th>{key.title()}</th>')
            html.append('</tr></thead>')
            
            # Data rows
            html.append('<tbody>')
            for row in mock_data:
                html.append('<tr>')
                for value in row.values():
                    html.append(f'<td>{value}</td>')
                html.append('</tr>')
            html.append('</tbody>')
        
        html.append('</table></div>')
        return '\n'.join(html)
    
    def _generate_chart_preview(self, component) -> str:
        """Generate preview HTML for chart."""
        chart_type = component.properties.get('chart_type', 'line')
        width = component.properties.get('width', '100%')
        height = component.properties.get('height', '400px')
        
        return f"""
<div class="chart-container mb-3" style="width: {width}; height: {height};">
    <canvas id="chart-{component.component_id}"></canvas>
</div>
<script>
document.addEventListener('DOMContentLoaded', function() {{
    fetch('/api/chart-data/{chart_type}')
        .then(response => response.json())
        .then(data => {{
            const ctx = document.getElementById('chart-{component.component_id}');
            new Chart(ctx, {{
                type: '{chart_type}',
                data: data,
                options: {{
                    responsive: true,
                    maintainAspectRatio: false
                }}
            }});
        }});
}});
</script>
"""
    
    def _generate_card_preview(self, component, view_definition) -> str:
        """Generate preview HTML for card."""
        title = component.properties.get('title', component.label or 'Card')
        
        html = [f'<div class="card mb-3">']
        if component.properties.get('show_header', True):
            html.append(f'<div class="card-header"><h5>{title}</h5></div>')
        
        html.append('<div class="card-body">')
        
        # Generate children
        for child_id in component.children:
            child = view_definition.get_component(child_id)
            if child:
                child_html = self._generate_component_preview_html(child, view_definition)
                html.append(child_html)
        
        if not component.children:
            html.append('<p class="card-text">This is a sample card with some content.</p>')
        
        html.append('</div>')
        html.append('</div>')
        
        return '\n'.join(html)
    
    def _generate_text_field_preview(self, component) -> str:
        """Generate preview HTML for text field."""
        label = component.label or 'Text Field'
        placeholder = component.placeholder or 'Enter text...'
        required = 'required' if component.validation.required else ''
        
        return f"""
<div class="form-group mb-3">
    <label class="form-label">{label}</label>
    <input type="text" class="form-control" placeholder="{placeholder}" {required}>
</div>
"""
    
    def _generate_button_preview(self, component) -> str:
        """Generate preview HTML for button."""
        text = component.properties.get('text', component.label or 'Button')
        variant = component.properties.get('variant', 'primary')
        size = component.properties.get('size', 'md')
        
        size_class = f'btn-{size}' if size != 'md' else ''
        
        return f"""
<button type="button" class="btn btn-{variant} {size_class} mb-2" 
        onclick="alert('Button clicked in preview mode')">{text}</button>
"""
    
    def _generate_preview_css(self, view_definition: ViewDefinition) -> str:
        """Generate CSS for the preview."""
        css_parts = []
        
        for component in view_definition.components.values():
            if component.style.custom_css:
                css_parts.append(f"#{component.component_id} {{")
                for prop, value in component.style.custom_css.items():
                    css_parts.append(f"  {prop}: {value};")
                css_parts.append("}")
        
        return '\n'.join(css_parts)
    
    def _generate_preview_js(self, view_definition: ViewDefinition) -> str:
        """Generate JavaScript for the preview."""
        js_parts = []
        
        # Add chart initialization
        for component in view_definition.components.values():
            from ..components.component_library import ComponentType
            if component.component_type == ComponentType.CHART:
                # Chart JS is handled in the HTML template
                pass
        
        return '\n'.join(js_parts)
    
    # Status and Information
    def get_status(self) -> Dict[str, Any]:
        """Get current preview server status."""
        return {
            'running': self.is_running,
            'host': self.config.host,
            'port': self.config.port,
            'connected_clients': len(self.connected_clients),
            'views_count': len(self.current_views),
            'project': self.current_project.name if self.current_project else None,
            'websockets_enabled': self.config.enable_websockets
        }
    
    def get_preview_url(self, view_name: Optional[str] = None) -> str:
        """Get the preview URL for a view or the main index."""
        base_url = f"http://{self.config.host}:{self.config.port}"
        if view_name:
            return f"{base_url}/preview/{view_name}"
        return base_url