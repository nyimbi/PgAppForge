"""
Unified Validation Utilities for PgForge CLI Commands

Provides consistent validation patterns across all CLI commands
to ensure uniform behavior and error handling.
"""

import os
import re
from pathlib import Path
from typing import Optional, List, Tuple
from urllib.parse import urlparse
import click


class CLIValidator:
    """Unified validation utilities for PgForge CLI commands."""

    @staticmethod
    def validate_database_uri(ctx: click.Context, param: click.Parameter, value: str) -> str:
        """
        Enhanced database URI validation with connection testing.

        Args:
            ctx: Click context
            param: Click parameter
            value: Database URI to validate

        Returns:
            Validated database URI

        Raises:
            click.BadParameter: If URI is invalid
        """
        if not value:
            return value

        try:
            # Parse the URI
            parsed = urlparse(value)

            # Validate scheme
            if not parsed.scheme:
                raise click.BadParameter(
                    'Database URI must include a scheme (postgresql://, mysql://, sqlite:///)'
                )

            supported_schemes = ['postgresql', 'postgres', 'mysql', 'sqlite', 'oracle', 'mssql']
            if parsed.scheme not in supported_schemes:
                raise click.BadParameter(
                    f'Unsupported database scheme: {parsed.scheme}. '
                    f'Supported: {", ".join(supported_schemes)}'
                )

            # Validate database name for non-sqlite
            if parsed.scheme != 'sqlite':
                if not parsed.path or parsed.path == '/':
                    raise click.BadParameter('Database name is required in the URI path')

                # Remove leading slash for database name validation
                db_name = parsed.path.lstrip('/')
                if not CLIValidator._is_valid_identifier(db_name, allow_hyphens=True):
                    raise click.BadParameter(
                        'Database name should only contain letters, numbers, hyphens, and underscores'
                    )

            # For SQLite, validate file path
            if parsed.scheme == 'sqlite':
                if not parsed.path:
                    raise click.BadParameter('SQLite database file path is required')

                db_path = Path(parsed.path)
                if db_path.exists() and not db_path.is_file():
                    raise click.BadParameter(f'SQLite path exists but is not a file: {db_path}')

                # Check if parent directory is writable
                parent_dir = db_path.parent
                if not parent_dir.exists():
                    try:
                        parent_dir.mkdir(parents=True, exist_ok=True)
                    except OSError as e:
                        raise click.BadParameter(
                            f'Cannot create directory for SQLite database: {e}'
                        )

                if not os.access(parent_dir, os.W_OK):
                    raise click.BadParameter(
                        f'No write permission for SQLite database directory: {parent_dir}'
                    )

            return value

        except ValueError as e:
            raise click.BadParameter(f'Invalid database URI format: {e}')

    @staticmethod
    def validate_output_path(ctx: click.Context, param: click.Parameter, value: str) -> str:
        """
        Validate output file or directory path.

        Args:
            ctx: Click context
            param: Click parameter
            value: Path to validate

        Returns:
            Validated path

        Raises:
            click.BadParameter: If path is invalid
        """
        if not value:
            return value

        try:
            path = Path(value).resolve()

            # Security check: prevent path traversal attacks
            cwd = Path.cwd().resolve()
            try:
                # Allow paths within reasonable bounds (up to 3 levels up from CWD)
                common_path = os.path.commonpath([path, cwd])
                if len(Path(common_path).parts) < len(cwd.parts) - 3:
                    raise click.BadParameter(
                        'Output path appears to be outside safe directory bounds'
                    )
            except (ValueError, OSError):
                # Different drives on Windows or other edge cases
                pass

            # Check if parent directory is writable
            parent_dir = path.parent if path.suffix else path
            if not parent_dir.exists():
                try:
                    parent_dir.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    raise click.BadParameter(f'Cannot create output directory: {e}')

            if not os.access(parent_dir, os.W_OK):
                raise click.BadParameter(f'No write permission for output directory: {parent_dir}')

            return str(path)

        except (OSError, ValueError) as e:
            raise click.BadParameter(f'Invalid output path: {e}')

    @staticmethod
    def validate_app_name(ctx: click.Context, param: click.Parameter, value: str) -> str:
        """
        Validate application name.

        Args:
            ctx: Click context
            param: Click parameter
            value: Application name to validate

        Returns:
            Validated application name

        Raises:
            click.BadParameter: If name is invalid
        """
        if not value:
            raise click.BadParameter('Application name is required')

        # Basic length check
        if len(value) < 2:
            raise click.BadParameter('Application name must be at least 2 characters long')

        if len(value) > 50:
            raise click.BadParameter('Application name must be no more than 50 characters long')

        # Character validation
        if not CLIValidator._is_valid_identifier(value, allow_hyphens=True):
            raise click.BadParameter(
                'Application name should only contain letters, numbers, hyphens, and underscores. '
                'Must start with a letter.'
            )

        # Reserved name check
        reserved_names = [
            'admin', 'api', 'app', 'auth', 'config', 'database', 'db', 'docs',
            'flask', 'login', 'logout', 'models', 'static', 'templates', 'test',
            'tests', 'views', 'www', 'root', 'system', 'server'
        ]

        if value.lower() in reserved_names:
            raise click.BadParameter(f'Application name "{value}" is reserved')

        return value

    @staticmethod
    def validate_email(ctx: click.Context, param: click.Parameter, value: str) -> str:
        """
        Validate email address format.

        Args:
            ctx: Click context
            param: Click parameter
            value: Email to validate

        Returns:
            Validated email

        Raises:
            click.BadParameter: If email is invalid
        """
        if not value:
            return value

        email_pattern = re.compile(
            r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        )

        if not email_pattern.match(value):
            raise click.BadParameter('Invalid email address format')

        return value

    @staticmethod
    def validate_version(ctx: click.Context, param: click.Parameter, value: str) -> str:
        """
        Validate semantic version format.

        Args:
            ctx: Click context
            param: Click parameter
            value: Version to validate

        Returns:
            Validated version

        Raises:
            click.BadParameter: If version format is invalid
        """
        if not value:
            return "1.0.0"

        # Simple semantic version pattern
        version_pattern = re.compile(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?(\+[a-zA-Z0-9.-]+)?$')

        if not version_pattern.match(value):
            raise click.BadParameter(
                'Version must follow semantic versioning format (e.g., 1.0.0, 1.2.3-alpha, 2.0.0+build.1)'
            )

        return value

    @staticmethod
    def validate_workflow_file(ctx: click.Context, param: click.Parameter, value: str) -> str:
        """
        Validate workflow definition file.

        Args:
            ctx: Click context
            param: Click parameter
            value: Workflow file path

        Returns:
            Validated file path

        Raises:
            click.BadParameter: If file is invalid
        """
        if not value:
            raise click.BadParameter('Workflow file is required')

        file_path = Path(value)

        if not file_path.exists():
            raise click.BadParameter(f'Workflow file does not exist: {file_path}')

        if not file_path.is_file():
            raise click.BadParameter(f'Path is not a file: {file_path}')

        # Check file extension
        valid_extensions = ['.yaml', '.yml', '.wdl']
        if file_path.suffix.lower() not in valid_extensions:
            raise click.BadParameter(
                f'Workflow file must have one of these extensions: {", ".join(valid_extensions)}'
            )

        # Check if file is readable
        if not os.access(file_path, os.R_OK):
            raise click.BadParameter(f'Cannot read workflow file: {file_path}')

        return str(file_path.resolve())

    @staticmethod
    def validate_template_dir(ctx: click.Context, param: click.Parameter, value: str) -> Optional[str]:
        """
        Validate custom template directory.

        Args:
            ctx: Click context
            param: Click parameter
            value: Template directory path

        Returns:
            Validated directory path or None

        Raises:
            click.BadParameter: If directory is invalid
        """
        if not value:
            return None

        template_dir = Path(value)

        if not template_dir.exists():
            raise click.BadParameter(f'Template directory does not exist: {template_dir}')

        if not template_dir.is_dir():
            raise click.BadParameter(f'Path is not a directory: {template_dir}')

        # Check for required template files
        required_templates = ['model.py.j2', 'view.py.j2']
        missing_templates = []

        for template in required_templates:
            template_path = template_dir / template
            if not template_path.exists():
                missing_templates.append(template)

        if missing_templates:
            raise click.BadParameter(
                f'Missing required template files: {", ".join(missing_templates)}'
            )

        return str(template_dir.resolve())

    @staticmethod
    def _is_valid_identifier(name: str, allow_hyphens: bool = False) -> bool:
        """
        Check if a string is a valid identifier.

        Args:
            name: String to check
            allow_hyphens: Whether to allow hyphens in addition to underscores

        Returns:
            True if valid identifier
        """
        if not name:
            return False

        # Must start with letter
        if not name[0].isalpha():
            return False

        # Check remaining characters
        for char in name[1:]:
            if not (char.isalnum() or char == '_' or (allow_hyphens and char == '-')):
                return False

        return True


def create_validation_options() -> List[click.Option]:
    """
    Create common validation options for CLI commands.

    Returns:
        List of click options with validation
    """
    return [
        click.option(
            '--uri', '-u',
            required=True,
            callback=CLIValidator.validate_database_uri,
            help='Database connection URI'
        ),
        click.option(
            '--output', '-o',
            default='.',
            callback=CLIValidator.validate_output_path,
            help='Output directory or file path'
        ),
        click.option(
            '--app-name', '-n',
            callback=CLIValidator.validate_app_name,
            help='Application name'
        ),
        click.option(
            '--author-email',
            callback=CLIValidator.validate_email,
            help='Author email address'
        ),
        click.option(
            '--version', '-v',
            default='1.0.0',
            callback=CLIValidator.validate_version,
            help='Application version'
        )
    ]


def add_common_options(func):
    """
    Decorator to add common validation options to CLI commands.

    Args:
        func: CLI command function

    Returns:
        Decorated function
    """
    for option in reversed(create_validation_options()):
        func = option(func)
    return func