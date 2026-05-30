"""
CLI Commands for PgForge Enhanced Generator

Provides the `flask fab gen` command structure for generating beautiful
PgForge applications from database introspection.

Commands:
- flask fab gen model --uri <db_uri> --output models.py
- flask fab gen view --uri <db_uri> --output-dir views/
- flask fab gen app --uri <db_uri> --name MyApp --output-dir myapp/
- flask fab gen api --uri <db_uri> --output-dir api/
- flask fab gen all --uri <db_uri> --name MyApp --output-dir myapp/
"""

import logging
import os
import sys
import click
from pathlib import Path
from typing import Optional, Dict, Any

from .database_inspector import EnhancedDatabaseInspector
from .model_generator import EnhancedModelGenerator, ModelGenerationConfig
from .view_generator import BeautifulViewGenerator, ViewGenerationConfig
from .app_generator import FullAppGenerator, AppGenerationConfig
from .mobile_generator import MobileGenerator, MobileGenerationConfig

logger = logging.getLogger(__name__)


def validate_database_uri(ctx, param, value):
    """Enhanced database URI validation with connection testing."""
    if not value:
        return value

    try:
        from urllib.parse import urlparse
        from sqlalchemy import create_engine
        
        # Parse the URI
        parsed = urlparse(value)
        
        # Only PostgreSQL is supported
        pg_schemes = ('postgresql', 'postgresql+psycopg2', 'postgresql+asyncpg')
        if not parsed.scheme or not any(value.startswith(s + '://') for s in pg_schemes):
            raise click.BadParameter(
                f'Only PostgreSQL is supported. Use: postgresql://user:pass@host/dbname'
            )
        if not parsed.path or parsed.path == '/':
            raise click.BadParameter('Database name is required: postgresql://user:pass@host/dbname')

        # Test connection (optional, only with --validate-connection flag)
        if ctx and hasattr(ctx, 'params') and ctx.params.get('validate_connection'):
            click.echo('🔍 Testing database connection...')
            try:
                engine = create_engine(value, connect_args={"connect_timeout": 5})
                with engine.connect() as conn:
                    conn.execute('SELECT 1')
                click.echo('✅ Database connection successful')
                engine.dispose()
            except Exception as e:
                click.echo(f'⚠️  Database connection failed: {e}', err=True)
                if not click.confirm('Continue anyway?'):
                    raise click.BadParameter('Database connection required')
        
        return value
        
    except click.BadParameter:
        raise
    except Exception as e:
        raise click.BadParameter(f'Invalid database URI: {e}')


def validate_output_path(ctx, param, value):
    """Enhanced output path validation with security checks."""
    if not value:
        return value

    try:
        path = Path(value).resolve()
        
        # Security check: prevent path traversal
        try:
            # Check if path tries to escape outside reasonable bounds
            path.relative_to(Path.cwd().parent.parent)  # Allow up to 2 levels up
        except ValueError:
            raise click.BadParameter('Output path appears to be outside safe directory bounds')
        
        # Check for suspicious path components
        suspicious_parts = ['.ssh', '.aws', '.config', 'etc', 'var', 'usr', 'bin', 'sbin']
        path_parts = [p.lower() for p in path.parts]
        
        for suspicious in suspicious_parts:
            if suspicious in path_parts:
                if not click.confirm(f'⚠️  Path contains potentially sensitive directory "{suspicious}". Continue?'):
                    raise click.BadParameter('Output path validation cancelled')
        
        # Validate path components
        for part in path.parts:
            if not part or part in ['.', '..']:
                continue
            if any(char in part for char in ['<', '>', ':', '"', '|', '?', '*']):
                raise click.BadParameter(f'Invalid characters in path component: {part}')
        
        # Check if path exists and get information
        if path.exists():
            if path.is_file():
                raise click.BadParameter(f'Output path is an existing file: {path}')
            
            if path.is_dir():
                # Check if directory is empty
                try:
                    contents = list(path.iterdir())
                    if contents:
                        file_count = len([f for f in contents if f.is_file()])
                        dir_count = len([f for f in contents if f.is_dir()])
                        
                        if file_count > 0 or dir_count > 0:
                            if not click.confirm(
                                f'⚠️  Directory {path} is not empty ({file_count} files, {dir_count} dirs). '
                                f'Files may be overwritten. Continue?'
                            ):
                                raise click.BadParameter('Output directory must be empty or non-existent')
                except PermissionError:
                    raise click.BadParameter(f'No permission to read directory: {path}')
        
        # Check parent directory permissions
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        
        if not os.access(parent, os.W_OK):
            raise click.BadParameter(f'No write permission for directory: {parent}')
        
        # Try to create the directory structure
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise click.BadParameter(f'Cannot create output directory: {e}')
        except PermissionError:
            raise click.BadParameter(f'Permission denied creating directory: {path}')
        
        # Test write access by creating a temporary file
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(dir=path, delete=True) as tmp:
                pass  # Just testing write access
        except OSError as e:
            raise click.BadParameter(f'Cannot write to output directory: {e}')
        
        return str(path)
        
    except click.BadParameter:
        raise
    except Exception as e:
        raise click.BadParameter(f'Invalid output path: {e}')


def validate_app_name(ctx, param, value):
    """Validate application name for safety and conventions."""
    if not value:
        return value
    
    try:
        # Check length
        if len(value) < 2:
            raise click.BadParameter('Application name must be at least 2 characters long')
        if len(value) > 50:
            raise click.BadParameter('Application name must be 50 characters or less')
        
        # Check valid characters (letters, numbers, hyphens, underscores)
        if not value.replace('_', '').replace('-', '').isalnum():
            raise click.BadParameter('Application name should only contain letters, numbers, hyphens, and underscores')
        
        # Must start with letter
        if not value[0].isalpha():
            raise click.BadParameter('Application name must start with a letter')
        
        # Avoid reserved names
        reserved_names = ['admin', 'api', 'app', 'config', 'test', 'tests', 'static', 'templates', 
                         'main', 'index', 'auth', 'login', 'logout', 'register', 'flask', 'python',
                         'con', 'prn', 'aux', 'nul']  # Including Windows reserved names
        
        if value.lower() in reserved_names:
            raise click.BadParameter(f'Application name "{value}" is reserved. Please choose a different name')
        
        # Check for Python keywords
        import keyword
        if keyword.iskeyword(value):
            raise click.BadParameter(f'Application name "{value}" is a Python keyword. Please choose a different name')
        
        return value
        
    except click.BadParameter:
        raise
    except Exception as e:
        raise click.BadParameter(f'Invalid application name: {e}')


def validate_email(ctx, param, value):
    """Validate email address format."""
    if not value:
        return value
    
    try:
        import re
        
        # Simple but comprehensive email regex
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        if not re.match(email_pattern, value):
            raise click.BadParameter('Invalid email address format')
        
        # Additional checks
        if len(value) > 254:  # RFC 5321 limit
            raise click.BadParameter('Email address is too long (max 254 characters)')
        
        local_part, domain = value.rsplit('@', 1)
        if len(local_part) > 64:  # RFC 5321 limit
            raise click.BadParameter('Email local part is too long (max 64 characters)')
        
        return value
        
    except click.BadParameter:
        raise
    except Exception as e:
        raise click.BadParameter(f'Invalid email address: {e}')


def validate_version(ctx, param, value):
    """Validate version string format (semver)."""
    if not value:
        return value
    
    try:
        import re
        
        # Semantic versioning pattern
        pattern = r'^(\d+)\.(\d+)\.(\d+)(?:-(\w+(?:\.\w+)*))?(?:\+(\w+(?:\.\w+)*))?$'
        
        if not re.match(pattern, value):
            raise click.BadParameter('Version must follow semantic versioning format (e.g., 1.0.0, 1.0.0-alpha.1)')
        
        return value
        
    except click.BadParameter:
        raise
    except Exception as e:
        raise click.BadParameter(f'Invalid version format: {e}')


@click.group()
def gen():
    """Enhanced PgForge code generation from database introspection."""
    pass


@gen.command('model')
@click.option(
    '--uri', '-u',
    required=True,
    callback=validate_database_uri,
    help='Database connection URI (e.g., postgresql://user:pass@host:port/db)'
)
@click.option(
    '--output', '-o',
    default='models.py',
    callback=validate_output_path,
    help='Output file path for generated models'
)
@click.option(
    '--config', '-c',
    type=click.Path(exists=True),
    help='Configuration file path (YAML or JSON)'
)
@click.option(
    '--include-pydantic/--no-pydantic',
    default=True,
    help='Generate Pydantic models for API serialization'
)
@click.option(
    '--include-validation/--no-validation',
    default=True,
    help='Generate validation methods'
)
@click.option(
    '--include-hybrid-properties/--no-hybrid-properties',
    default=True,
    help='Generate hybrid properties'
)
@click.option(
    '--include-event-listeners/--no-event-listeners',
    default=True,
    help='Generate event listeners'
)
@click.option(
    '--security-features/--no-security',
    default=True,
    help='Include security features'
)
@click.option(
    '--performance-optimizations/--no-performance',
    default=True,
    help='Include performance optimizations'
)
@click.option(
    '--custom-base-class',
    help='Custom base class for models'
)
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def generate_models(
    uri: str,
    output: str,
    config: Optional[str],
    include_pydantic: bool,
    include_validation: bool,
    include_hybrid_properties: bool,
    include_event_listeners: bool,
    security_features: bool,
    performance_optimizations: bool,
    custom_base_class: Optional[str],
    verbose: bool
):
    """Generate enhanced SQLAlchemy models from database schema."""
    if verbose:
        logging.basicConfig(level=logging.INFO)

    try:
        click.echo("🔍 Connecting to database and analyzing schema...")

        from .file_operations import GenerationTransaction

        with EnhancedDatabaseInspector(uri) as inspector:
            model_config = ModelGenerationConfig(
                generate_pydantic=include_pydantic,
                generate_validation=include_validation,
                generate_hybrid_properties=include_hybrid_properties,
                generate_event_listeners=include_event_listeners,
                security_features=security_features,
                performance_optimizations=performance_optimizations,
                custom_base_class=custom_base_class,
            )

            generator = EnhancedModelGenerator(inspector, model_config)
            click.echo("🏗️ Generating enhanced models...")
            models = generator.generate_all_models()

            output_path = Path(output)
            with GenerationTransaction(output_path.parent, "Model Generation") as transaction:
                transaction.add_file('models.py', models['models.py'])
                if models.get('schemas.py') and include_pydantic:
                    transaction.add_file('schemas.py', models['schemas.py'])
                if models.get('validators.py') and include_validation:
                    transaction.add_file('validators.py', models['validators.py'])

            files_written = [str(f) for f in transaction.file_writer.get_written_files()]

        click.echo("✅ Model generation complete!")
        click.echo(f"📁 Generated {len(files_written)} files:")
        for file_path in files_written:
            click.echo(f"   • {file_path}")
        click.echo("\n📋 Next steps:")
        click.echo("1. Review generated models")
        click.echo("2. Customize validation rules as needed")
        click.echo("3. Add custom business logic")
        click.echo("4. Run database migrations: flask db migrate")

    except Exception as e:
        click.echo(f"❌ Error generating models: {e}", err=True)
        sys.exit(1)


@gen.command('view')
@click.option(
    '--uri', '-u',
    required=True,
    callback=validate_database_uri,
    help='Database connection URI'
)
@click.option(
    '--output-dir', '-o',
    required=True,
    callback=validate_output_path,
    help='Output directory for generated views'
)
@click.option(
    '--config', '-c',
    type=click.Path(exists=True),
    help='Configuration file path'
)
@click.option(
    '--modern-widgets/--basic-widgets',
    default=True,
    help='Use modern widget system'
)
@click.option(
    '--include-api/--no-api',
    default=True,
    help='Generate API views'
)
@click.option(
    '--include-charts/--no-charts',
    default=True,
    help='Generate chart views'
)
@click.option(
    '--include-calendar/--no-calendar',
    default=True,
    help='Generate calendar views'
)
@click.option(
    '--include-master-detail/--no-master-detail',
    default=True,
    help='Generate master-detail views with inline formsets'
)
@click.option(
    '--include-lookup-views/--no-lookup-views',
    default=True,
    help='Generate lookup views for tables with multiple foreign keys'
)
@click.option(
    '--include-reference-views/--no-reference-views',
    default=True,
    help='Generate reference views for relationship navigation'
)
@click.option(
    '--include-relationship-views/--no-relationship-views',
    default=True,
    help='Generate relationship navigation dashboard views'
)
@click.option(
    '--inline-form-layout',
    default='stacked',
    type=click.Choice(['stacked', 'tabular', 'accordion']),
    help='Default layout for inline formsets'
)
@click.option(
    '--max-inline-forms',
    default=50,
    type=int,
    help='Maximum number of inline forms per formset'
)
@click.option(
    '--enable-realtime/--no-realtime',
    default=True,
    help='Enable real-time features'
)
@click.option(
    '--theme',
    default='modern',
    type=click.Choice(['modern', 'classic', 'minimal']),
    help='UI theme'
)
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def generate_views(
    uri: str,
    output_dir: str,
    config: Optional[str],
    modern_widgets: bool,
    include_api: bool,
    include_charts: bool,
    include_calendar: bool,
    include_master_detail: bool,
    include_lookup_views: bool,
    include_reference_views: bool,
    include_relationship_views: bool,
    inline_form_layout: str,
    max_inline_forms: int,
    enable_realtime: bool,
    theme: str,
    verbose: bool
):
    """Generate beautiful PgForge views with modern widgets and relationship support."""
    if verbose:
        logging.basicConfig(level=logging.INFO)

    try:
        click.echo("🔍 Analyzing database schema for view generation...")

        # Initialize database inspector with context management
        with EnhancedDatabaseInspector(uri) as inspector:

            # Create view generation configuration
            view_config = ViewGenerationConfig(
                use_modern_widgets=modern_widgets,
                generate_api_views=include_api,
                generate_chart_views=include_charts,
                generate_calendar_views=include_calendar,
                generate_master_detail_views=include_master_detail,
                generate_lookup_views=include_lookup_views,
                generate_reference_views=include_reference_views,
                generate_relationship_views=include_relationship_views,
                enable_inline_formsets=include_master_detail,
                max_inline_forms=max_inline_forms,
                inline_form_layouts=[inline_form_layout],
                enable_real_time=enable_realtime,
                theme=theme
            )

            # Initialize view generator
            generator = BeautifulViewGenerator(inspector, view_config)

            click.echo("🎨 Generating beautiful views...")

            # Generate views
            result = generator.generate_all_views(output_dir)

            click.echo("✅ View generation complete!")
            click.echo(f"📁 Generated {len(result['generated_files'])} files in {output_dir}")

            # Show detailed statistics
            click.echo("\n📊 Generation Statistics:")
            total_views = sum(stats['view_count'] for stats in result['view_statistics'].values())
            click.echo(f"   • Total tables processed: {len(result['view_statistics'])}")
            click.echo(f"   • Total views generated: {total_views}")
            
            # Master-detail statistics
            if result['master_detail_patterns']:
                master_detail_count = sum(len(patterns) for patterns in result['master_detail_patterns'].values())
                click.echo(f"   • Master-detail patterns found: {master_detail_count}")
                
                if verbose:
                    click.echo("\n🔗 Master-Detail Patterns:")
                    for table, patterns in result['master_detail_patterns'].items():
                        for pattern in patterns:
                            click.echo(f"     • {table} → {pattern['child_table']} ({pattern['layout']} layout)")
            
            # Relationship view statistics  
            if result['relationship_views']:
                relationship_view_count = sum(
                    len([v for views in variations.values() for v in views if views]) 
                    for variations in result['relationship_views'].values()
                )
                click.echo(f"   • Relationship views generated: {relationship_view_count}")

            # Show feature summary
            click.echo("\n🌟 Generated features:")
            if modern_widgets:
                click.echo("   • Modern widget system with enhanced UX")
            if include_api:
                click.echo("   • RESTful API views with OpenAPI documentation")
            if include_charts:
                click.echo("   • Interactive chart views")
            if include_calendar:
                click.echo("   • Calendar views for date-based data")
            if include_master_detail:
                click.echo(f"   • Master-detail views with {inline_form_layout} inline formsets")
            if include_lookup_views:
                click.echo("   • Advanced lookup views for complex filtering")
            if include_reference_views:
                click.echo("   • Reference views for relationship navigation")
            if include_relationship_views:
                click.echo("   • Relationship dashboard views")
            if enable_realtime:
                click.echo("   • Real-time updates with WebSocket support")

            click.echo(f"\n🎨 Theme: {theme}")
            
            # Show errors if any
            if result['errors']:
                click.echo(f"\n⚠️  {len(result['errors'])} errors occurred:")
                for error in result['errors']:
                    click.echo(f"   • {error}")

            # Show next steps
            click.echo(f"\n📋 Next steps:")
            click.echo(f"   1. Add generated views to your PgForge app")
            click.echo(f"   2. Import the view registry: from {output_dir}.views import *")
            click.echo(f"   3. Register views with appbuilder.add_view()")
            if include_master_detail:
                click.echo(f"   4. Ensure inline formset templates are in your templates directory")

    except Exception as e:
        click.echo(f"❌ Error generating views: {e}", err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@gen.command('app')
@click.option(
    '--uri', '-u',
    required=True,
    callback=validate_database_uri,
    help='Database connection URI'
)
@click.option(
    '--name', '-n',
    required=True,
    help='Application name'
)
@click.option(
    '--output-dir', '-o',
    required=True,
    callback=validate_output_path,
    help='Output directory for generated application'
)
@click.option(
    '--title',
    help='Application title (defaults to name)'
)
@click.option(
    '--description',
    help='Application description'
)
@click.option(
    '--author',
    help='Author name'
)
@click.option(
    '--email',
    help='Author email'
)
@click.option(
    '--version',
    default='1.0.0',
    help='Application version'
)
@click.option(
    '--enable-auth/--no-auth',
    default=True,
    help='Enable authentication system'
)
@click.option(
    '--enable-api/--no-api',
    default=True,
    help='Enable REST API'
)
@click.option(
    '--enable-websockets/--no-websockets',
    default=True,
    help='Enable WebSocket support'
)
@click.option(
    '--enable-docker/--no-docker',
    default=True,
    help='Generate Docker configuration'
)
@click.option(
    '--enable-testing/--no-testing',
    default=True,
    help='Generate testing framework'
)
@click.option(
    '--security-level',
    default='medium',
    type=click.Choice(['basic', 'medium', 'high']),
    help='Security level'
)
@click.option(
    '--database-type',
    default='postgresql',
    type=click.Choice(['postgresql']),
    help='Database type'
)
@click.option(
    '--theme',
    default='modern',
    type=click.Choice(['modern', 'classic', 'minimal']),
    help='UI theme'
)
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def generate_app(
    uri: str,
    name: str,
    output_dir: str,
    title: Optional[str],
    description: Optional[str],
    author: Optional[str],
    email: Optional[str],
    version: str,
    enable_auth: bool,
    enable_api: bool,
    enable_websockets: bool,
    enable_docker: bool,
    enable_testing: bool,
    security_level: str,
    database_type: str,
    theme: str,
    verbose: bool
):
    """Generate complete PgForge application from database schema."""
    if verbose:
        logging.basicConfig(level=logging.INFO)

    try:
        click.echo("🚀 Starting complete application generation...")
        click.echo(f"📦 Application: {title or name}")
        click.echo(f"🗄️ Database: {database_type}")
        click.echo(f"🔐 Security: {security_level}")

        # Initialize database inspector with context management
        with EnhancedDatabaseInspector(uri) as inspector:
            # Create app generation configuration
            app_config = AppGenerationConfig(
                app_name=name,
                app_title=title or name,
                app_description=description or f"Generated PgForge application: {name}",
                author_name=author or "Generated",
                author_email=email or "generated@example.com",
                version=version,
                enable_auth=enable_auth,
                enable_api=enable_api,
                enable_websockets=enable_websockets,
                enable_docker=enable_docker,
                enable_testing=enable_testing,
                security_level=security_level,
                database_type=database_type,
                theme=theme
            )

            # Initialize app generator
            generator = FullAppGenerator(inspector, app_config, output_dir)

            click.echo("🏗️ Generating application structure...")

            # Generate complete application
            result = generator.generate_complete_app()

            if result['status'] == 'success':
                click.echo("✅ Application generation complete!")
                click.echo(f"📁 Generated {result['files_generated']} files")
                click.echo(f"📂 Output directory: {result['output_dir']}")

                # Show feature summary
                click.echo("\n🌟 Generated features:")
                if enable_auth:
                    click.echo("   • Authentication & authorization system")
                if enable_api:
                    click.echo("   • RESTful API with OpenAPI documentation")
                if enable_websockets:
                    click.echo("   • Real-time features with WebSocket support")
                if enable_docker:
                    click.echo("   • Docker & Docker Compose configuration")
                if enable_testing:
                    click.echo("   • Comprehensive testing framework")

                # Show next steps
                click.echo("\n📋 Next steps:")
                for step in result['next_steps']:
                    if step.strip():
                        click.echo(f"   {step}")
            else:
                click.echo("❌ Application generation failed", err=True)
                sys.exit(1)

    except Exception as e:
        click.echo(f"❌ Error generating application: {e}", err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@gen.command('api')
@click.option(
    '--uri', '-u',
    required=True,
    callback=validate_database_uri,
    help='Database connection URI'
)
@click.option(
    '--output-dir', '-o',
    required=True,
    callback=validate_output_path,
    help='Output directory for API files'
)
@click.option(
    '--include-auth/--no-auth',
    default=True,
    help='Include API authentication'
)
@click.option(
    '--include-swagger/--no-swagger',
    default=True,
    help='Generate Swagger/OpenAPI documentation'
)
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def generate_api(
    uri: str,
    output_dir: str,
    include_auth: bool,
    include_swagger: bool,
    verbose: bool
):
    """Generate REST API from database schema."""
    if verbose:
        logging.basicConfig(level=logging.INFO)

    try:
        click.echo("🌐 Generating REST API from database schema...")

        # Initialize components
        inspector = EnhancedDatabaseInspector(uri)
        view_config = ViewGenerationConfig(generate_api_views=True)
        generator = BeautifulViewGenerator(inspector, view_config)

        # Generate API views
        result = generator.generate_all_views()

        # Extract only API views
        api_files = {}
        for table_name, table_views in result['views'].items():
            if 'api_view' in table_views:
                api_files[f"{table_name}_api.py"] = table_views['api_view']

        # Write API files using transaction-safe operations
        from .file_operations import GenerationTransaction
        
        output_path = Path(output_dir)
        
        with GenerationTransaction(output_path, "API Generation") as transaction:
            transaction.add_files(api_files)
        
        files_written = [str(f) for f in transaction.file_writer.get_written_files()]

        click.echo("✅ API generation complete!")
        click.echo(f"📁 Generated {len(files_written)} API files")

        if include_swagger:
            click.echo("📚 Swagger documentation available at: /swagger-ui")

    except Exception as e:
        click.echo(f"❌ Error generating API: {e}", err=True)
        sys.exit(1)


@gen.command('all')
@click.option(
    '--uri', '-u',
    required=True,
    callback=validate_database_uri,
    help='Database connection URI'
)
@click.option(
    '--name', '-n',
    required=True,
    help='Application name'
)
@click.option(
    '--output-dir', '-o',
    required=True,
    callback=validate_output_path,
    help='Output directory for generated application'
)
@click.option(
    '--title',
    help='Application title'
)
@click.option(
    '--author',
    help='Author name'
)
@click.option(
    '--email',
    help='Author email'
)
@click.option(
    '--platform', '-p',
    default='web',
    show_default=True,
    help=(
        'Comma-separated platforms to generate. '
        'Choices: web, desktop, mobile, all. '
        'Examples: web,desktop  |  all'
    ),
)
@click.option('--desktop-target', default='pywebview',
              type=click.Choice(['pywebview', 'pyside6', 'both']),
              show_default=True,
              help='Desktop wrapper target (used when platform includes desktop)')
@click.option('--api-url', default='http://localhost:8080/api/v1', show_default=True,
              help='API base URL for mobile app (used when platform includes mobile)')
@click.option('--app-id', default=None,
              help='Bundle ID for mobile/desktop (e.g. com.company.myapp)')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def generate_all(
    uri: str,
    name: str,
    output_dir: str,
    title: Optional[str],
    author: Optional[str],
    email: Optional[str],
    platform: str,
    desktop_target: str,
    api_url: str,
    app_id: Optional[str],
    verbose: bool
):
    """Generate a complete application across web, desktop, and mobile platforms.

    \b
    Examples:
      # Web only (default)
      flask forge gen all --uri postgresql://... --name MyApp --output-dir ./app

      # Web + desktop wrapper
      flask forge gen all --uri postgresql://... --name MyApp --output-dir ./app \\
        --platform web,desktop

      # All three platforms
      flask forge gen all --uri postgresql://... --name MyApp --output-dir ./app \\
        --platform all --app-id com.example.myapp --api-url https://api.example.com
    """
    if verbose:
        logging.basicConfig(level=logging.INFO)

    # Normalise platform list
    _p = {p.strip().lower() for p in platform.split(',') if p.strip()}
    if 'all' in _p:
        _p = {'web', 'desktop', 'mobile'}
    do_web = 'web' in _p or not _p          # web is always the default
    do_desktop = 'desktop' in _p
    do_mobile = 'mobile' in _p

    resolved_id = app_id or f"com.pgappforge.{name.lower().replace(' ', '')}"
    output_path = Path(output_dir)

    try:
        # ── Web ──────────────────────────────────────────────────────────────
        if do_web:
            click.echo("🌐 Generating web application...")
            from click.testing import CliRunner
            runner = CliRunner()
            cmd_args = [
                '--uri', uri, '--name', name, '--output-dir', output_dir,
                '--enable-auth', '--enable-api', '--enable-websockets',
                '--enable-docker', '--enable-testing',
                '--security-level', 'high', '--theme', 'modern',
            ]
            if title:
                cmd_args.extend(['--title', title])
            if author:
                cmd_args.extend(['--author', author])
            if email:
                cmd_args.extend(['--email', email])
            if verbose:
                cmd_args.append('--verbose')

            result = runner.invoke(generate_app, cmd_args, catch_exceptions=False)
            if result.exit_code != 0:
                click.echo("❌ Web generation failed", err=True)
                sys.exit(1)
            click.echo("   ✓ Web application generated")

        # ── Desktop ───────────────────────────────────────────────────────────
        if do_desktop:
            click.echo(f"🖥  Generating desktop wrapper ({desktop_target})...")
            from .desktop_generator import DesktopGenerator, DesktopConfig
            desktop_config = DesktopConfig(
                app_name=name,
                app_id=resolved_id,
                target=desktop_target,
            )
            DesktopGenerator(desktop_config, output_path).generate()
            click.echo("   ✓ Desktop wrapper generated")

        # ── Mobile ────────────────────────────────────────────────────────────
        if do_mobile:
            click.echo("📱 Generating mobile app (Expo)...")
            mobile_out = output_path / f"{name.lower().replace(' ', '_')}-mobile"
            with EnhancedDatabaseInspector(uri) as inspector:
                mobile_config = MobileGenerationConfig(
                    app_name=name,
                    app_id=resolved_id,
                    framework="expo",
                    api_base_url=api_url,
                )
                MobileGenerator(inspector, mobile_config, mobile_out).generate_complete_app()
            click.echo(f"   ✓ Mobile app generated → {mobile_out}")

        # ── Summary ───────────────────────────────────────────────────────────
        click.echo("\n🎉 Generation complete!")
        if do_web:
            click.echo(f"   Web    → {output_dir}/")
        if do_desktop:
            click.echo(f"   Desktop→ {output_dir}/run_desktop.py  (python run_desktop.py)")
        if do_mobile:
            click.echo(f"   Mobile → {mobile_out}/  (cd {mobile_out} && npm i && npx expo start)")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


# Helper commands for development and debugging
@gen.command('inspect')
@click.option(
    '--uri', '-u',
    required=True,
    callback=validate_database_uri,
    help='Database connection URI'
)
@click.option(
    '--table',
    help='Specific table to inspect (optional)'
)
@click.option(
    '--format',
    default='table',
    type=click.Choice(['table', 'json', 'yaml']),
    help='Output format'
)
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def inspect_database(
    uri: str,
    table: Optional[str],
    format: str,
    verbose: bool
):
    """Inspect database schema without generating code."""
    if verbose:
        logging.basicConfig(level=logging.INFO)

    try:
        click.echo("🔍 Inspecting database schema...")

        inspector = EnhancedDatabaseInspector(uri)
        analysis = inspector.analyze_database()

        if table:
            if table in analysis['tables']:
                table_info = analysis['tables'][table]
                click.echo(f"\n📊 Table: {table}")
                click.echo(f"Category: {table_info.category}")
                click.echo(f"Columns: {len(table_info.columns)}")
                click.echo(f"Relationships: {len(table_info.relationships)}")
                click.echo(f"Estimated rows: {table_info.estimated_rows}")
                click.echo(f"Security level: {table_info.security_level}")

                click.echo("\n📋 Columns:")
                for col in table_info.columns:
                    click.echo(f"   • {col.name} ({col.category.value}) - {col.description}")

                if table_info.relationships:
                    click.echo("\n🔗 Relationships:")
                    for rel in table_info.relationships:
                        click.echo(f"   • {rel.name}: {rel.cardinality_description} to {rel.remote_table}")
            else:
                click.echo(f"❌ Table '{table}' not found")
                sys.exit(1)
        else:
            # Show database summary
            click.echo(f"\n📊 Database: {analysis['database_info']['name']}")
            click.echo(f"Tables: {analysis['statistics']['regular_tables']}")
            click.echo(f"Association tables: {analysis['statistics']['association_tables']}")

            click.echo("\n📋 Tables:")
            for table_name, table_info in analysis['tables'].items():
                icon = "🔗" if table_info.is_association_table else "📄"
                click.echo(f"   {icon} {table_name} ({table_info.category}) - {len(table_info.columns)} columns")

    except Exception as e:
        click.echo(f"❌ Error inspecting database: {e}", err=True)
        sys.exit(1)


@gen.command('mobile')
@click.option(
    '--uri', '-u',
    required=True,
    callback=validate_database_uri,
    help='Database connection URI (postgresql://...)'
)
@click.option(
    '--name', '-n',
    required=True,
    callback=validate_app_name,
    help='Application display name (e.g. "MyApp")'
)
@click.option(
    '--app-id',
    default=None,
    help='Bundle / package identifier (e.g. com.company.myapp). Defaults to com.example.<name>.'
)
@click.option(
    '--output-dir', '-o',
    required=True,
    callback=validate_output_path,
    help='Output directory for the generated mobile app'
)
@click.option(
    '--framework',
    default='expo',
    type=click.Choice(['expo', 'pwa']),
    show_default=True,
    help='Mobile framework target'
)
@click.option(
    '--api-url',
    default='http://localhost:8080/api/v1',
    show_default=True,
    help='Base URL of the pgappforge REST API'
)
@click.option(
    '--primary-color',
    default='#007bff',
    show_default=True,
    help='Brand primary color (hex)'
)
@click.option(
    '--features',
    default='auth,list,detail,create,edit',
    show_default=True,
    help='Comma-separated feature set to generate'
)
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def generate_mobile(
    uri: str,
    name: str,
    app_id: Optional[str],
    output_dir: str,
    framework: str,
    api_url: str,
    primary_color: str,
    features: str,
    verbose: bool,
):
    """Generate a complete React Native (Expo) mobile app from database schema.

    \b
    Example:
      flask forge gen mobile \\
        --uri postgresql://user:pass@localhost/mydb \\
        --name MyApp --app-id com.example.myapp \\
        --output-dir ./my-mobile-app
    """
    if verbose:
        logging.basicConfig(level=logging.INFO)

    resolved_app_id = app_id or f"com.example.{name.lower()}"
    feature_list = [f.strip() for f in features.split(',') if f.strip()]

    click.echo(f"📱 Generating {framework} mobile app: {name}")
    click.echo(f"   Bundle ID : {resolved_app_id}")
    click.echo(f"   API URL   : {api_url}")
    click.echo(f"   Features  : {', '.join(feature_list)}")
    click.echo(f"   Output    : {output_dir}")

    try:
        with EnhancedDatabaseInspector(uri) as inspector:
            mobile_config = MobileGenerationConfig(
                app_name=name,
                app_id=resolved_app_id,
                framework=framework,
                api_base_url=api_url,
                primary_color=primary_color,
                features=feature_list,
            )
            generator = MobileGenerator(inspector, mobile_config, output_dir)

            click.echo("🔍 Introspecting database schema...")
            files = generator.generate_complete_app()

        click.echo(f"✅ Mobile app generated — {len(files)} files written to {output_dir}")
        click.echo("\n📋 Next steps:")
        click.echo("   1. cd into the output directory")
        click.echo("   2. Copy .env.example to .env and set EXPO_PUBLIC_API_BASE_URL")
        click.echo("   3. npm install")
        click.echo("   4. npx expo start")

    except Exception as e:
        click.echo(f"❌ Mobile generation failed: {e}", err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@gen.command('desktop')
@click.option('--name', '-n', required=True, help='Application display name')
@click.option('--output-dir', '-o', required=True, callback=validate_output_path,
              help='Output directory (should be the generated Flask app root)')
@click.option('--app-id', default=None,
              help='Bundle identifier, e.g. com.company.myapp')
@click.option('--version', default='0.1.0', show_default=True,
              help='Application version')
@click.option('--target', default='pywebview',
              type=click.Choice(['pywebview', 'pyside6', 'both']), show_default=True,
              help='Desktop wrapper target')
@click.option('--port', default=5000, show_default=True,
              help='Port for embedded Flask server')
@click.option('--width', default=1280, show_default=True, help='Window width')
@click.option('--height', default=800, show_default=True, help='Window height')
@click.option('--icon', default='', help='Path to app icon (.ico/.icns/.png)')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def generate_desktop(
    name: str,
    output_dir: str,
    app_id: Optional[str],
    version: str,
    target: str,
    port: int,
    width: int,
    height: int,
    icon: str,
    verbose: bool,
):
    """Generate a desktop wrapper for a pgappforge Flask app.

    \b
    Wraps the generated Flask application in a native OS window.
    Two targets are supported:

      pywebview  — system WebView, ~10 MB binary (recommended)
      pyside6    — Qt WebEngine, ~150 MB binary (richer native APIs)
      both       — generate both wrappers

    \b
    Example:
      flask forge gen desktop \\
        --name MyApp --output-dir ./myapp \\
        --target pywebview
    """
    from .desktop_generator import DesktopGenerator, DesktopConfig

    if verbose:
        logging.basicConfig(level=logging.INFO)

    resolved_id = app_id or f"com.pgappforge.{name.lower().replace(' ', '')}"

    click.echo(f"🖥  Generating desktop wrapper: {name}")
    click.echo(f"   Target    : {target}")
    click.echo(f"   Bundle ID : {resolved_id}")
    click.echo(f"   Output    : {output_dir}")

    try:
        config = DesktopConfig(
            app_name=name,
            app_id=resolved_id,
            version=version,
            flask_port=port,
            window_width=width,
            window_height=height,
            icon_path=icon,
            target=target,
        )
        generator = DesktopGenerator(config, output_dir)
        files = generator.generate()

        click.echo(f"✅ Desktop wrapper generated — {len(files)} files written to {output_dir}")
        click.echo("\n📋 Next steps:")
        if target in ("pywebview", "both"):
            click.echo("   Pywebview:  pip install pywebview && python run_desktop.py")
            click.echo("   Package:    pip install pyinstaller && make -C desktop dist")
        if target in ("pyside6", "both"):
            click.echo("   PySide6:    pip install PySide6 PySide6-WebEngine && python run_desktop_qt.py")
            click.echo("   Package:    make -C desktop dist-qt")

    except Exception as e:
        click.echo(f"❌ Desktop generation failed: {e}", err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


def register_commands(app):
    """Register generation commands with Flask CLI."""
    app.cli.add_command(gen)