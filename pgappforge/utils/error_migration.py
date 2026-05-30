"""
Error Handling Migration Utilities

This module provides utilities to help migrate existing PgAppForge code
to use the new standardized error handling patterns while maintaining
backward compatibility.
"""

import ast
import re
import os
import logging
from typing import List, Dict, Tuple, Set, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ErrorHandlingMigrator:
    """
    Utility class to help migrate existing PgAppForge code to use
    standardized error handling patterns.
    """

    def __init__(self, project_root: str):
        """
        Initialize the migrator.

        Args:
            project_root: Root directory of the PgAppForge project
        """
        self.project_root = Path(project_root)
        self.migration_report = {
            'files_analyzed': 0,
            'exceptions_found': [],
            'recommendations': [],
            'migration_opportunities': []
        }

    def analyze_project(self) -> Dict:
        """
        Analyze the entire project for error handling patterns.

        Returns:
            Dictionary containing analysis results and migration recommendations
        """
        logger.info(f"Analyzing project at {self.project_root}")

        # Find all Python files
        python_files = list(self.project_root.rglob("*.py"))
        python_files = [f for f in python_files if not self._should_skip_file(f)]

        for file_path in python_files:
            self._analyze_file(file_path)

        self._generate_recommendations()
        return self.migration_report

    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if a file should be skipped during analysis."""
        skip_patterns = [
            '__pycache__',
            '.git',
            'venv',
            'env',
            'node_modules',
            '.pytest_cache',
            'migrations',  # Skip database migrations
            'test_',       # Skip test files for now
        ]

        return any(pattern in str(file_path) for pattern in skip_patterns)

    def _analyze_file(self, file_path: Path):
        """Analyze a single Python file for error handling patterns."""
        try:
            self.migration_report['files_analyzed'] += 1

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse the AST
            try:
                tree = ast.parse(content)
            except SyntaxError as e:
                logger.warning(f"Syntax error in {file_path}: {e}")
                return

            # Analyze the AST
            analyzer = ErrorPatternAnalyzer(file_path, content)
            analyzer.visit(tree)

            # Collect results
            self.migration_report['exceptions_found'].extend(analyzer.exceptions_found)
            self.migration_report['migration_opportunities'].extend(analyzer.migration_opportunities)

        except Exception as e:
            logger.error(f"Error analyzing {file_path}: {e}")

    def _generate_recommendations(self):
        """Generate migration recommendations based on analysis results."""
        recommendations = []

        # Count exception types
        exception_counts = {}
        for exc in self.migration_report['exceptions_found']:
            exc_type = exc['exception_type']
            exception_counts[exc_type] = exception_counts.get(exc_type, 0) + 1

        # Generate specific recommendations
        if exception_counts.get('bare_except', 0) > 0:
            recommendations.append({
                'priority': 'HIGH',
                'type': 'bare_except',
                'title': 'Replace bare except clauses',
                'description': f"Found {exception_counts['bare_except']} bare except clauses. "
                              "These should be replaced with specific exception types.",
                'migration_pattern': 'Use @fab_error_handler decorator or specific exception types'
            })

        if exception_counts.get('generic_exception', 0) > 5:
            recommendations.append({
                'priority': 'MEDIUM',
                'type': 'generic_exception',
                'title': 'Use specific exception types',
                'description': f"Found {exception_counts['generic_exception']} generic Exception catches. "
                              "Consider using specific FAB exception types.",
                'migration_pattern': 'Replace with FABValidationError, FABDatabaseError, etc.'
            })

        if len(self.migration_report['migration_opportunities']) > 0:
            recommendations.append({
                'priority': 'MEDIUM',
                'type': 'decorator_opportunity',
                'title': 'Use @fab_error_handler decorator',
                'description': f"Found {len(self.migration_report['migration_opportunities'])} functions "
                              "that could benefit from standardized error handling.",
                'migration_pattern': 'Add @fab_error_handler decorator to functions with error handling'
            })

        self.migration_report['recommendations'] = recommendations

    def generate_migration_script(self, output_file: str):
        """
        Generate a migration script to help with automated migration.

        Args:
            output_file: Path to write the migration script
        """
        script_content = self._create_migration_script_content()

        with open(output_file, 'w') as f:
            f.write(script_content)

        logger.info(f"Migration script generated: {output_file}")

    def _create_migration_script_content(self) -> str:
        """Create the content for the migration script."""
        return '''#!/usr/bin/env python3
"""
Automated PgAppForge Error Handling Migration Script

This script helps migrate existing PgAppForge code to use standardized
error handling patterns.

Usage:
    python migrate_error_handling.py --project-root /path/to/project

IMPORTANT:
- Create a backup of your project before running this script
- Review all changes carefully before committing
- Run tests after migration to ensure functionality is preserved
"""

import argparse
import os
import re
import shutil
from pathlib import Path

def backup_project(project_root: str, backup_dir: str):
    """Create a backup of the project before migration."""
    print(f"Creating backup at {backup_dir}")
    shutil.copytree(project_root, backup_dir, ignore=shutil.ignore_patterns(
        '__pycache__', '*.pyc', '.git', 'venv', 'env', 'node_modules'
    ))

def migrate_imports(file_path: Path):
    """Migrate exception imports to use standardized exceptions."""
    with open(file_path, 'r') as f:
        content = f.read()

    original_content = content

    # Add import for standardized exceptions
    if 'from pgappforge.exceptions' in content:
        # Update existing imports
        content = re.sub(
            r'from pgappforge\\.exceptions import ([^\\n]+)',
            r'from pgappforge.exceptions import \\1, fab_error_handler, ErrorCategory, ErrorSeverity',
            content
        )
    elif 'from pgappforge' in content and 'import' in content:
        # Add new import line
        lines = content.split('\\n')
        import_line_added = False
        for i, line in enumerate(lines):
            if line.startswith('from pgappforge') and 'import' in line:
                lines.insert(i + 1, 'from pgappforge.exceptions import fab_error_handler, ErrorCategory, ErrorSeverity')
                import_line_added = True
                break
        if import_line_added:
            content = '\\n'.join(lines)

    # Save if changed
    if content != original_content:
        with open(file_path, 'w') as f:
            f.write(content)
        print(f"Updated imports in {file_path}")

def migrate_exception_handling(file_path: Path):
    """Migrate exception handling patterns."""
    with open(file_path, 'r') as f:
        content = f.read()

    original_content = content

    # Replace bare except clauses
    content = re.sub(
        r'except:\\s*\\n',
        r'except Exception as e:\\n        # TODO: Replace with specific exception type\\n',
        content
    )

    # Suggest decorator usage for functions with try/except
    function_pattern = r'def\\s+(\\w+)\\s*\\([^)]*\\):[^\\n]*\\n(?:[^\\n]*\\n)*?\\s*try:'
    matches = re.finditer(function_pattern, content, re.MULTILINE)

    for match in matches:
        func_name = match.group(1)
        # Add comment suggesting decorator
        content = content.replace(
            match.group(0),
            f"# TODO: Consider adding @fab_error_handler decorator\\n{match.group(0)}"
        )

    # Save if changed
    if content != original_content:
        with open(file_path, 'w') as f:
            f.write(content)
        print(f"Updated exception handling in {file_path}")

def main():
    parser = argparse.ArgumentParser(description='Migrate PgAppForge error handling')
    parser.add_argument('--project-root', required=True, help='Project root directory')
    parser.add_argument('--backup', action='store_true', help='Create backup before migration')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without making changes')

    args = parser.parse_args()

    project_root = Path(args.project_root)
    if not project_root.exists():
        print(f"Error: Project root {project_root} does not exist")
        return

    if args.backup:
        backup_dir = project_root.parent / f"{project_root.name}_backup"
        backup_project(str(project_root), str(backup_dir))

    # Find Python files
    python_files = list(project_root.rglob("*.py"))
    python_files = [f for f in python_files if '__pycache__' not in str(f)]

    print(f"Found {len(python_files)} Python files to migrate")

    if args.dry_run:
        print("DRY RUN - No changes will be made")
        return

    # Migrate each file
    for file_path in python_files:
        try:
            migrate_imports(file_path)
            migrate_exception_handling(file_path)
        except Exception as e:
            print(f"Error migrating {file_path}: {e}")

    print("Migration complete!")
    print("\\nNext steps:")
    print("1. Review all changes carefully")
    print("2. Run your test suite")
    print("3. Update functions to use @fab_error_handler decorator")
    print("4. Replace generic exceptions with specific FAB exception types")

if __name__ == '__main__':
    main()
'''


class ErrorPatternAnalyzer(ast.NodeVisitor):
    """AST visitor to analyze error handling patterns in Python code."""

    def __init__(self, file_path: Path, content: str):
        self.file_path = file_path
        self.content = content
        self.lines = content.split('\n')
        self.exceptions_found = []
        self.migration_opportunities = []

    def visit_ExceptHandler(self, node):
        """Visit except handlers to analyze exception patterns."""
        line_num = node.lineno
        line_content = self.lines[line_num - 1] if line_num <= len(self.lines) else ""

        exception_info = {
            'file': str(self.file_path),
            'line': line_num,
            'line_content': line_content.strip(),
            'exception_type': None
        }

        if node.type is None:
            # Bare except clause
            exception_info['exception_type'] = 'bare_except'
            exception_info['recommendation'] = 'Replace with specific exception type or use @fab_error_handler'
        elif isinstance(node.type, ast.Name) and node.type.id == 'Exception':
            # Generic Exception catch
            exception_info['exception_type'] = 'generic_exception'
            exception_info['recommendation'] = 'Use specific FAB exception types'
        elif isinstance(node.type, ast.Name):
            # Specific exception type
            exception_info['exception_type'] = 'specific_exception'
            exception_info['exception_name'] = node.type.id

        self.exceptions_found.append(exception_info)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        """Visit function definitions to identify migration opportunities."""
        # Check if function has try/except blocks
        has_try_except = any(isinstance(child, ast.Try) for child in ast.walk(node))

        if has_try_except:
            # Check if function already has error handling decorator
            has_error_decorator = any(
                isinstance(decorator, ast.Name) and 'error' in decorator.id.lower()
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Name)
            )

            if not has_error_decorator:
                self.migration_opportunities.append({
                    'file': str(self.file_path),
                    'function': node.name,
                    'line': node.lineno,
                    'recommendation': 'Consider adding @fab_error_handler decorator'
                })

        self.generic_visit(node)


# Migration examples and patterns

MIGRATION_PATTERNS = {
    'bare_except': {
        'before': '''
try:
    risky_operation()
except:
    log.error("Something went wrong")
    return None
        ''',
        'after': '''
from pgappforge.exceptions import fab_error_handler, ErrorCategory

@fab_error_handler(category=ErrorCategory.SYSTEM)
def safe_operation():
    return risky_operation()
        '''
    },

    'generic_exception': {
        'before': '''
try:
    user = create_user(data)
except Exception as e:
    log.error(f"User creation failed: {e}")
    raise
        ''',
        'after': '''
from pgappforge.exceptions import FABValidationError, FABDatabaseError

try:
    user = create_user(data)
except ValueError as e:
    raise FABValidationError(f"Invalid user data: {e}")
except DatabaseError as e:
    raise FABDatabaseError(f"Database error during user creation: {e}")
        '''
    },

    'api_error_handling': {
        'before': '''
def api_endpoint():
    try:
        result = process_request()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        ''',
        'after': '''
from pgappforge.exceptions import fab_error_handler, ErrorCategory

@fab_error_handler(category=ErrorCategory.API)
def api_endpoint():
    result = process_request()
    return jsonify(result)
        '''
    }
}


def get_migration_examples() -> Dict[str, Dict[str, str]]:
    """Get migration pattern examples."""
    return MIGRATION_PATTERNS


def print_migration_guide():
    """Print a comprehensive migration guide."""
    guide = """
PgAppForge Standardized Error Handling Migration Guide

1. PREPARATION
   - Create a backup of your project
   - Run existing tests to establish baseline
   - Review current error handling patterns

2. IMPORT UPDATES
   Add standardized exception imports:

   from pgappforge.exceptions import (
       fab_error_handler, ErrorCategory, ErrorSeverity,
       FABValidationError, FABDatabaseError, FABSecurityError
   )

3. DECORATOR USAGE
   Add error handling decorators to functions:

   @fab_error_handler(category=ErrorCategory.DATABASE)
   def create_user(self, user_data):
       # Function implementation
       pass

4. SPECIFIC EXCEPTIONS
   Replace generic exceptions with specific types:

   # Before
   raise Exception("Invalid data")

   # After
   raise FABValidationError("Invalid user data format", field_name="email")

5. ERROR CONTEXT
   Add context information for better debugging:

   from pgappforge.exceptions import ErrorContext, get_request_context

   context = get_request_context()
   context.operation = "user_creation"
   raise FABDatabaseError("Connection failed", context=context)

6. TESTING
   Update tests to expect new exception types:

   with pytest.raises(FABValidationError):
       invalid_operation()

7. MONITORING
   Use error statistics for monitoring:

   from pgappforge.exceptions import get_error_stats
   stats = get_error_stats()

8. GRADUAL MIGRATION
   - Start with new code using standardized patterns
   - Gradually migrate existing code
   - Use migration script for bulk updates
   - Maintain backward compatibility during transition

For detailed examples, see the migration patterns in error_migration.py
    """
    print(guide)


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 2:
        print("Usage: python error_migration.py <project_root>")
        print_migration_guide()
        sys.exit(1)

    project_root = sys.argv[1]
    migrator = ErrorHandlingMigrator(project_root)
    report = migrator.analyze_project()

    print(f"Analysis complete. Files analyzed: {report['files_analyzed']}")
    print(f"Exceptions found: {len(report['exceptions_found'])}")
    print(f"Migration opportunities: {len(report['migration_opportunities'])}")

    # Generate migration script
    migrator.generate_migration_script("migrate_error_handling.py")
    print("Migration script generated: migrate_error_handling.py")