"""
Flask Web Application for Visual IDE.

Serves the visual development interface and integrates with the IDE engine
to provide a complete web-based development environment.
"""

import os
import logging
from pathlib import Path
from flask import Flask, render_template, send_from_directory
from werkzeug.serving import WSGIRequestHandler

from ..core.ide_engine import VisualIDEEngine, IDEConfiguration
from .ide_api import IDEWebAPI

logger = logging.getLogger(__name__)


class VisualIDEWebApp:
    """
    Flask web application for the Visual IDE.
    
    Provides a complete web interface for visual PgForge development
    including the IDE interface, API endpoints, and static file serving.
    """
    
    def __init__(self, 
                 workspace_path: str,
                 project_name: str = "visual_ide_project",
                 host: str = "localhost",
                 port: int = 5000,
                 debug: bool = True):
        
        self.workspace_path = Path(workspace_path)
        self.project_name = project_name
        self.host = host
        self.port = port
        self.debug = debug
        
        # Create Flask app
        self.app = Flask(__name__, 
                        template_folder=str(Path(__file__).parent / 'templates'),
                        static_folder=str(Path(__file__).parent / 'static'))
        
        # Configure Flask app
        self.app.config['SECRET_KEY'] = 'visual-ide-secret-key'
        self.app.config['DEBUG'] = debug
        
        # Initialize IDE engine
        self.ide_config = IDEConfiguration(
            workspace_path=str(workspace_path),
            project_name=project_name,
            enable_live_preview=True,
            enable_hot_reload=True
        )
        
        self.ide_engine = VisualIDEEngine(self.ide_config)
        
        # Initialize web API
        self.api = IDEWebAPI(self.ide_engine)
        self.app.register_blueprint(self.api.get_blueprint())
        
        # Setup routes
        self._setup_routes()
        
        logger.info(f"Visual IDE Web App initialized for project: {project_name}")
    
    def _setup_routes(self):
        """Setup Flask routes for the web application."""
        
        @self.app.route('/')
        def index():
            """Main IDE interface."""
            return render_template('visual_ide.html')
        
        @self.app.route('/health')
        def health_check():
            """Health check endpoint."""
            return {
                'status': 'healthy',
                'project': self.ide_engine.current_project.name if self.ide_engine.current_project else None,
                'views_count': len(self.ide_engine.active_views),
                'workspace': str(self.workspace_path)
            }
        
        @self.app.route('/static/visual-ide/<path:filename>')
        def serve_visual_ide_static(filename):
            """Serve Visual IDE static files."""
            static_path = Path(__file__).parent / 'static'
            return send_from_directory(str(static_path), filename)
        
        @self.app.errorhandler(404)
        def not_found(error):
            """404 error handler."""
            return render_template('visual_ide.html'), 404
        
        @self.app.errorhandler(500)
        def internal_error(error):
            """500 error handler."""
            logger.error(f"Internal server error: {error}")
            return {'error': 'Internal server error'}, 500
    
    def run(self, **kwargs):
        """
        Run the Visual IDE web application.
        
        Args:
            **kwargs: Additional arguments for Flask.run()
        """
        # Merge default config with provided kwargs
        run_config = {
            'host': self.host,
            'port': self.port,
            'debug': self.debug,
            'threaded': True,
            'use_reloader': False  # Disable reloader to prevent issues with IDE engine
        }
        run_config.update(kwargs)
        
        try:
            logger.info(f"Starting Visual IDE Web App on http://{run_config['host']}:{run_config['port']}")
            self.app.run(**run_config)
        except Exception as e:
            logger.error(f"Failed to start web application: {e}")
            raise
    
    def get_flask_app(self) -> Flask:
        """Get the Flask application instance."""
        return self.app
    
    def get_ide_engine(self) -> VisualIDEEngine:
        """Get the IDE engine instance."""
        return self.ide_engine
    
    def cleanup(self):
        """Clean up resources."""
        try:
            self.ide_engine.cleanup()
            logger.info("Visual IDE Web App cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


def create_visual_ide_app(workspace_path: str, 
                         project_name: str = "visual_ide_project",
                         **config) -> VisualIDEWebApp:
    """
    Factory function to create a Visual IDE web application.
    
    Args:
        workspace_path: Path to the workspace directory
        project_name: Name of the project
        **config: Additional configuration options
        
    Returns:
        VisualIDEWebApp instance
    """
    return VisualIDEWebApp(
        workspace_path=workspace_path,
        project_name=project_name,
        **config
    )


def run_visual_ide_server(workspace_path: str,
                         project_name: str = "visual_ide_project",
                         host: str = "localhost",
                         port: int = 5000,
                         debug: bool = True):
    """
    Convenience function to run the Visual IDE server.
    
    Args:
        workspace_path: Path to the workspace directory
        project_name: Name of the project
        host: Host to bind to
        port: Port to listen on
        debug: Enable debug mode
    """
    app = create_visual_ide_app(
        workspace_path=workspace_path,
        project_name=project_name,
        host=host,
        port=port,
        debug=debug
    )
    
    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("Visual IDE server stopped by user")
    except Exception as e:
        logger.error(f"Visual IDE server error: {e}")
    finally:
        app.cleanup()


if __name__ == '__main__':
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='PgForge Visual IDE')
    parser.add_argument('workspace', help='Path to workspace directory')
    parser.add_argument('--project', default='visual_ide_project', help='Project name')
    parser.add_argument('--host', default='localhost', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to listen on')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run the server
    run_visual_ide_server(
        workspace_path=args.workspace,
        project_name=args.project,
        host=args.host,
        port=args.port,
        debug=args.debug
    )