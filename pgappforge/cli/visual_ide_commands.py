"""
Visual IDE CLI Commands for PgForge.

Provides command-line interface for the Visual Development IDE,
allowing users to start the IDE, generate code, and manage projects.
"""

import os
import sys
import logging
import click
from pathlib import Path
from typing import Optional

# Import Visual IDE components
try:
    from ..visual_ide.web.ide_web_app import create_visual_ide_app, run_visual_ide_server
    from ..visual_ide.core.ide_engine import VisualIDEEngine, IDEConfiguration
    from ..visual_ide.preview.live_preview import PreviewConfiguration
    VISUAL_IDE_AVAILABLE = True
except ImportError as e:
    VISUAL_IDE_AVAILABLE = False
    IMPORT_ERROR = str(e)

logger = logging.getLogger(__name__)


def check_visual_ide_available():
    """Check if Visual IDE components are available."""
    if not VISUAL_IDE_AVAILABLE:
        click.echo(click.style("Error: Visual IDE components are not available.", fg='red'))
        click.echo(f"Import error: {IMPORT_ERROR}")
        click.echo("\nPlease ensure all Visual IDE dependencies are installed:")
        click.echo("  pip install flask-appbuilder[visual-ide]")
        sys.exit(1)


@click.group('visual-ide')
def visual_ide_group():
    """Visual Development IDE commands for PgForge."""
    check_visual_ide_available()


@visual_ide_group.command('start')
@click.argument('workspace_path', type=click.Path())
@click.option('--project', default='visual_ide_project', help='Project name')
@click.option('--host', default='localhost', help='Host to bind to')
@click.option('--port', type=int, default=5000, help='Port to listen on')
@click.option('--debug', is_flag=True, help='Enable debug mode')
@click.option('--preview-port', type=int, default=5001, help='Live preview server port')
@click.option('--auto-open', is_flag=True, help='Automatically open browser')
def start_ide(workspace_path: str, project: str, host: str, port: int, 
              debug: bool, preview_port: int, auto_open: bool):
    """
    Start the Visual Development IDE web interface.
    
    WORKSPACE_PATH: Directory where the visual IDE project will be created
    """
    workspace_path = Path(workspace_path).resolve()
    
    # Create workspace directory if it doesn't exist
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    click.echo(f"Starting PgForge Visual IDE...")
    click.echo(f"Workspace: {workspace_path}")
    click.echo(f"Project: {project}")
    click.echo(f"IDE Server: http://{host}:{port}")
    click.echo(f"Preview Server: http://{host}:{preview_port}")
    click.echo()
    
    # Setup logging
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Suppress werkzeug logs unless debug
    if not debug:
        logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    try:
        # Create and configure IDE app
        ide_app = create_visual_ide_app(
            workspace_path=str(workspace_path),
            project_name=project,
            host=host,
            port=port,
            debug=debug
        )
        
        # Auto-open browser if requested
        if auto_open:
            import webbrowser
            import threading
            import time
            
            def open_browser():
                time.sleep(2)  # Give server time to start
                webbrowser.open(f'http://{host}:{port}')
            
            threading.Thread(target=open_browser, daemon=True).start()
        
        # Run the server
        ide_app.run()
        
    except KeyboardInterrupt:
        click.echo("\nVisual IDE stopped by user")
    except Exception as e:
        click.echo(click.style(f"Error starting Visual IDE: {e}", fg='red'))
        if debug:
            raise
        sys.exit(1)


@visual_ide_group.command('create-project')
@click.argument('workspace_path', type=click.Path())
@click.argument('project_name')
@click.option('--template', default='basic', 
              type=click.Choice(['basic', 'crud', 'dashboard', 'api']),
              help='Project template to use')
@click.option('--database-url', help='Database URL for the project')
@click.option('--description', help='Project description')
def create_project(workspace_path: str, project_name: str, template: str, 
                  database_url: Optional[str], description: Optional[str]):
    """
    Create a new Visual IDE project.
    
    WORKSPACE_PATH: Directory where the project will be created
    PROJECT_NAME: Name of the new project
    """
    workspace_path = Path(workspace_path).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    click.echo(f"Creating Visual IDE project: {project_name}")
    click.echo(f"Workspace: {workspace_path}")
    click.echo(f"Template: {template}")
    
    try:
        # Initialize IDE configuration
        config = IDEConfiguration(
            workspace_path=str(workspace_path),
            project_name=project_name,
            enable_live_preview=True
        )
        
        # Create IDE engine
        ide_engine = VisualIDEEngine(config)
        
        # Update project configuration
        if ide_engine.current_project:
            if description:
                ide_engine.current_project.description = description
            
            if database_url:
                ide_engine.current_project.database_config['uri'] = database_url
            
            # Add template-specific configuration
            if template == 'crud':
                # Add sample CRUD views
                ide_engine.create_view("UserView", "ModelView")
                ide_engine.create_view("ProductView", "ModelView")
                
            elif template == 'dashboard':
                # Add dashboard components
                ide_engine.create_view("DashboardView", "BaseView")
                
            elif template == 'api':
                # Add API configuration
                ide_engine.current_project.flask_config['ENABLE_API'] = True
            
            # Save project
            ide_engine._save_project()
        
        click.echo(click.style(f"✓ Project '{project_name}' created successfully!", fg='green'))
        click.echo(f"To start editing, run:")
        click.echo(f"  flask fab visual-ide start {workspace_path} --project {project_name}")
        
    except Exception as e:
        click.echo(click.style(f"Error creating project: {e}", fg='red'))
        sys.exit(1)


@visual_ide_group.command('generate')
@click.argument('workspace_path', type=click.Path(exists=True))
@click.argument('project_name')
@click.option('--output', '-o', help='Output directory for generated code')
@click.option('--view', help='Generate code for specific view only')
@click.option('--format', default='flask-appbuilder',
              type=click.Choice(['flask-appbuilder', 'flask', 'fastapi']),
              help='Output format')
@click.option('--include-tests', is_flag=True, help='Generate test files')
@click.option('--include-docker', is_flag=True, help='Generate Docker configuration')
def generate_code(workspace_path: str, project_name: str, output: Optional[str],
                 view: Optional[str], format: str, include_tests: bool, include_docker: bool):
    """
    Generate code from Visual IDE project.
    
    WORKSPACE_PATH: Directory containing the Visual IDE project
    PROJECT_NAME: Name of the project to generate code for
    """
    workspace_path = Path(workspace_path).resolve()
    
    if not workspace_path.exists():
        click.echo(click.style(f"Error: Workspace path does not exist: {workspace_path}", fg='red'))
        sys.exit(1)
    
    # Set output directory
    if output:
        output_path = Path(output).resolve()
    else:
        output_path = workspace_path / f"{project_name}_generated"
    
    click.echo(f"Generating code for project: {project_name}")
    click.echo(f"Workspace: {workspace_path}")
    click.echo(f"Output: {output_path}")
    click.echo(f"Format: {format}")
    
    try:
        # Initialize IDE engine
        config = IDEConfiguration(
            workspace_path=str(workspace_path),
            project_name=project_name
        )
        
        ide_engine = VisualIDEEngine(config)
        
        if not ide_engine.current_project:
            click.echo(click.style(f"Error: Project '{project_name}' not found", fg='red'))
            sys.exit(1)
        
        # Generate code
        if view:
            # Generate specific view
            if view not in ide_engine.active_views:
                click.echo(click.style(f"Error: View '{view}' not found", fg='red'))
                sys.exit(1)
            
            generated_files = ide_engine.generate_code(view)
            click.echo(f"Generated code for view '{view}': {len(generated_files)} files")
            
        else:
            # Generate full application
            generated_files = ide_engine.generate_full_application()
            click.echo(f"Generated full application: {len(generated_files)} files")
        
        # Export to output directory
        success = ide_engine.export_project(str(output_path))
        
        if success:
            click.echo(click.style(f"✓ Code generated successfully!", fg='green'))
            click.echo(f"Generated files saved to: {output_path}")
            
            # List generated files
            click.echo("\nGenerated files:")
            for file_path in sorted(generated_files.keys()):
                click.echo(f"  {file_path}")
            
            # Show next steps
            click.echo(f"\nNext steps:")
            click.echo(f"  cd {output_path}")
            click.echo(f"  pip install -r requirements.txt")
            click.echo(f"  python run.py")
            
        else:
            click.echo(click.style("Error: Failed to export generated code", fg='red'))
            sys.exit(1)
        
    except Exception as e:
        click.echo(click.style(f"Error generating code: {e}", fg='red'))
        sys.exit(1)


@visual_ide_group.command('list-projects')
@click.argument('workspace_path', type=click.Path(exists=True))
def list_projects(workspace_path: str):
    """
    List all Visual IDE projects in a workspace.
    
    WORKSPACE_PATH: Directory to search for Visual IDE projects
    """
    workspace_path = Path(workspace_path).resolve()
    
    click.echo(f"Searching for Visual IDE projects in: {workspace_path}")
    click.echo()
    
    found_projects = []
    
    # Search for project.json files
    for project_file in workspace_path.rglob('project.json'):
        try:
            project_dir = project_file.parent
            project_name = project_dir.name
            
            # Try to load project info
            import json
            with open(project_file, 'r') as f:
                project_data = json.load(f)
            
            found_projects.append({
                'name': project_data.get('name', project_name),
                'path': project_dir,
                'description': project_data.get('description', ''),
                'views_count': len(project_data.get('views', {})),
                'created_at': project_data.get('created_at', ''),
                'version': project_data.get('version', '1.0.0')
            })
            
        except Exception as e:
            logger.debug(f"Error reading project file {project_file}: {e}")
            continue
    
    if found_projects:
        click.echo(f"Found {len(found_projects)} Visual IDE projects:")
        click.echo()
        
        for project in sorted(found_projects, key=lambda p: p['name']):
            click.echo(f"📁 {project['name']}")
            click.echo(f"   Path: {project['path']}")
            if project['description']:
                click.echo(f"   Description: {project['description']}")
            click.echo(f"   Views: {project['views_count']} • Version: {project['version']}")
            if project['created_at']:
                click.echo(f"   Created: {project['created_at']}")
            click.echo()
            
    else:
        click.echo("No Visual IDE projects found in the specified workspace.")
        click.echo("To create a new project, run:")
        click.echo(f"  flask fab visual-ide create-project {workspace_path} my-project")


@visual_ide_group.command('backup')
@click.argument('workspace_path', type=click.Path(exists=True))
@click.argument('project_name')
@click.option('--output', '-o', help='Backup output file')
@click.option('--description', help='Backup description')
def backup_project(workspace_path: str, project_name: str, 
                  output: Optional[str], description: Optional[str]):
    """
    Create a backup of a Visual IDE project.
    
    WORKSPACE_PATH: Directory containing the Visual IDE project
    PROJECT_NAME: Name of the project to backup
    """
    workspace_path = Path(workspace_path).resolve()
    
    click.echo(f"Creating backup for project: {project_name}")
    
    try:
        # Initialize IDE engine
        config = IDEConfiguration(
            workspace_path=str(workspace_path),
            project_name=project_name
        )
        
        ide_engine = VisualIDEEngine(config)
        
        if not ide_engine.current_project:
            click.echo(click.style(f"Error: Project '{project_name}' not found", fg='red'))
            sys.exit(1)
        
        # Create backup
        backup_info = ide_engine.file_manager.create_backup(description or f"CLI backup of {project_name}")
        
        if backup_info:
            click.echo(click.style(f"✓ Backup created successfully!", fg='green'))
            click.echo(f"Backup ID: {backup_info.backup_id}")
            click.echo(f"Files: {backup_info.files_count}")
            click.echo(f"Size: {backup_info.backup_size} bytes")
            click.echo(f"Location: {backup_info.backup_path}")
            
            # Copy to custom location if specified
            if output:
                import shutil
                shutil.copy2(backup_info.backup_path, output)
                click.echo(f"Backup copied to: {output}")
                
        else:
            click.echo(click.style("Error: Failed to create backup", fg='red'))
            sys.exit(1)
    
    except Exception as e:
        click.echo(click.style(f"Error creating backup: {e}", fg='red'))
        sys.exit(1)


@visual_ide_group.command('version')
def show_version():
    """Show Visual IDE version information."""
    try:
        from .. import __version__ as fab_version
    except ImportError:
        fab_version = "unknown"
    
    click.echo(f"PgForge: {fab_version}")
    click.echo(f"Visual IDE: 1.0.0")
    click.echo(f"Python: {sys.version}")
    
    # Check optional dependencies
    optional_deps = {
        'socketio': 'Real-time updates',
        'eventlet': 'WebSocket server',
        'jinja2': 'Template engine',
        'watchdog': 'File watching'
    }
    
    click.echo("\nOptional dependencies:")
    for dep, description in optional_deps.items():
        try:
            __import__(dep)
            status = click.style("✓", fg='green')
        except ImportError:
            status = click.style("✗", fg='red')
        
        click.echo(f"  {status} {dep}: {description}")


# Register commands with the main PgForge CLI
def register_visual_ide_commands(cli_group):
    """Register Visual IDE commands with PgForge CLI."""
    cli_group.add_command(visual_ide_group)