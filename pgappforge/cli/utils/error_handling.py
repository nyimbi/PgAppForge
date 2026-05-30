"""
Unified Error Handling for PgForge CLI Commands

Provides consistent error handling, formatting, and user feedback across
all CLI commands to improve debugging and user experience.
"""

import sys
import traceback
import logging
from typing import Optional, Any
import click


class CLIErrorHandler:
    """Unified error handling for PgForge CLI commands."""

    @staticmethod
    def handle_validation_error(error: Exception, context: str, verbose: bool = False) -> None:
        """
        Handle validation errors consistently across CLI commands.

        Args:
            error: The validation exception
            context: Context description (e.g., "workflow file validation")
            verbose: Whether to show full traceback
        """
        click.echo(click.style(f"❌ Validation Error ({context}): {error}", fg='red'))

        if verbose:
            click.echo(click.style("Full traceback:", fg='yellow'))
            click.echo(traceback.format_exc())
        else:
            click.echo("💡 Use --verbose flag for detailed error information")

    @staticmethod
    def handle_generation_error(error: Exception, operation: str, verbose: bool = False) -> None:
        """
        Handle code generation errors consistently.

        Args:
            error: The generation exception
            operation: Operation description (e.g., "Model generation")
            verbose: Whether to show full traceback
        """
        click.echo(click.style(f"❌ {operation} failed: {error}", fg='red'))

        # Provide specific guidance based on error type
        if "No module named" in str(error):
            click.echo("💡 Missing dependency. Try: pip install -r requirements.txt")
        elif "Permission denied" in str(error):
            click.echo("💡 Check file permissions and ensure target directory is writable")
        elif "already exists" in str(error):
            click.echo("💡 Use --force flag to overwrite existing files")

        if verbose:
            click.echo(click.style("Full traceback:", fg='yellow'))
            click.echo(traceback.format_exc())

    @staticmethod
    def handle_database_error(error: Exception, verbose: bool = False) -> None:
        """
        Handle database connection and analysis errors.

        Args:
            error: The database exception
            verbose: Whether to show full traceback
        """
        click.echo(click.style(f"❌ Database Error: {error}", fg='red'))

        # Provide specific guidance based on error type
        error_str = str(error).lower()
        if "connection" in error_str or "connect" in error_str:
            click.echo("💡 Check your database URI and ensure the database server is running")
            click.echo("💡 Example URIs:")
            click.echo("   postgresql://user:pass@localhost/dbname")
            click.echo("   mysql://user:pass@localhost/dbname")
            click.echo("   sqlite:///path/to/database.db")
        elif "authentication" in error_str or "password" in error_str:
            click.echo("💡 Check your database credentials")
        elif "no such table" in error_str or "table doesn't exist" in error_str:
            click.echo("💡 Database appears to be empty or tables not found")
        elif "permission" in error_str:
            click.echo("💡 Database user may lack necessary permissions")

        if verbose:
            click.echo(click.style("Full traceback:", fg='yellow'))
            click.echo(traceback.format_exc())

    @staticmethod
    def handle_file_error(error: Exception, operation: str, file_path: str, verbose: bool = False) -> None:
        """
        Handle file operation errors consistently.

        Args:
            error: The file operation exception
            operation: Operation description (e.g., "Writing model file")
            file_path: Path to the file that caused the error
            verbose: Whether to show full traceback
        """
        click.echo(click.style(f"❌ File Error ({operation}): {error}", fg='red'))
        click.echo(f"📁 File: {file_path}")

        # Provide specific guidance based on error type
        error_str = str(error).lower()
        if "permission denied" in error_str:
            click.echo("💡 Check file permissions and ensure directory is writable")
            click.echo(f"💡 Try: chmod +w {file_path}")
        elif "no such file or directory" in error_str:
            click.echo("💡 Parent directory may not exist")
            click.echo("💡 Try creating the directory first or use --create-dirs flag")
        elif "file exists" in error_str:
            click.echo("💡 Use --force flag to overwrite existing files")

        if verbose:
            click.echo(traceback.format_exc())

    @staticmethod
    def handle_import_error(error: ImportError, module: str, verbose: bool = False) -> None:
        """
        Handle import errors with helpful dependency information.

        Args:
            error: The import exception
            module: Module that failed to import
            verbose: Whether to show full traceback
        """
        click.echo(click.style(f"❌ Import Error: Missing module '{module}'", fg='red'))

        # Provide installation guidance for common modules
        install_commands = {
            'inflect': 'pip install inflect',
            'jinja2': 'pip install jinja2',
            'sqlalchemy': 'pip install sqlalchemy',
            'click': 'pip install click',
            'yaml': 'pip install pyyaml',
            'pathlib': 'This is a built-in module (Python 3.4+)',
        }

        if module.lower() in install_commands:
            click.echo(f"💡 Install with: {install_commands[module.lower()]}")
        else:
            click.echo("💡 Install missing dependencies with: pip install -r requirements.txt")

        if verbose:
            click.echo(click.style("Full traceback:", fg='yellow'))
            click.echo(traceback.format_exc())

    @staticmethod
    def handle_general_error(error: Exception, context: str, verbose: bool = False) -> None:
        """
        Handle general errors with context information.

        Args:
            error: The exception
            context: Context description
            verbose: Whether to show full traceback
        """
        click.echo(click.style(f"❌ Error in {context}: {error}", fg='red'))

        if verbose:
            click.echo(click.style("Full traceback:", fg='yellow'))
            click.echo(traceback.format_exc())
        else:
            click.echo("💡 Use --verbose flag for detailed error information")


class CLIProgressReporter:
    """Unified progress reporting for CLI operations."""

    def __init__(self):
        self.current_operation = None
        self.progress_bar = None

    def start(self, operation: str, total: Optional[int] = None):
        """Start a progress indicator for an operation."""
        self.current_operation = operation
        click.echo(f"🔄 {operation}...")

        if total:
            self.progress_bar = click.progressbar(length=total, label=operation)
            self.progress_bar.__enter__()

    def update(self, increment: int = 1):
        """Update progress if a progress bar is active."""
        if self.progress_bar:
            self.progress_bar.update(increment)

    def finish(self, success_message: str):
        """Finish the current operation."""
        if self.progress_bar:
            self.progress_bar.__exit__(None, None, None)
            self.progress_bar = None

        if success_message:
            click.echo(click.style(f"✅ {success_message}", fg='green'))

        self.current_operation = None

    def fail(self, error_message: str):
        """Mark the current operation as failed."""
        if self.progress_bar:
            self.progress_bar.__exit__(None, None, None)
            self.progress_bar = None

        click.echo(click.style(f"❌ {error_message}", fg='red'))
        self.current_operation = None


def setup_cli_logging(verbose: bool = False, log_file: Optional[str] = None):
    """
    Setup consistent logging across CLI commands.

    Args:
        verbose: Enable verbose logging
        log_file: Optional log file path
    """
    level = logging.INFO if verbose else logging.WARNING
    format_str = '%(levelname)s: %(message)s'

    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format=format_str,
        handlers=handlers
    )


def exit_with_error(message: str, exit_code: int = 1):
    """
    Exit CLI command with error message and code.

    Args:
        message: Error message to display
        exit_code: Exit code (default: 1)
    """
    click.echo(click.style(f"❌ {message}", fg='red'), err=True)
    sys.exit(exit_code)


def confirm_destructive_operation(operation: str, target: str) -> bool:
    """
    Get user confirmation for potentially destructive operations.

    Args:
        operation: Description of the operation
        target: Target of the operation (file, directory, etc.)

    Returns:
        True if user confirms, False otherwise
    """
    click.echo(click.style(f"⚠️  {operation}", fg='yellow'))
    click.echo(f"Target: {target}")
    return click.confirm("Do you want to continue?")