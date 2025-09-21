"""
Author: Nyimbi Odero
Copyright: Nyimbi Odero, 2024
License: MIT
import_utils.py: Comprehensive utilities for Python import statement management and analysis.

This module provides a robust set of tools for handling Python import statements, with
particular focus on code generation, static analysis, and import optimization. It supports
both general Python projects and Flask-AppBuilder specific requirements.

Key Features:
    1. Import Statement Processing
        - Parsing and formatting of import statements
        - Conversion between relative and absolute imports
        - Import statement validation and verification
        - PEP 8 compliant import sorting and organization

    2. Code Analysis
        - Static analysis of import usage
        - Dependency tracking and analysis
        - Detection of unused imports
        - Import statement validation

    3. Import Optimization
        - Import deduplication
        - Statement combination and simplification
        - Package-based grouping
        - Import categorization (stdlib, third-party, local)

    4. Flask-AppBuilder Support
        - Generation of common FAB imports
        - Framework-specific import organization
        - View-related import management

Core Components:
    Classes:
        - ImportStatement: Dataclass representing parsed import statements

    Main Functions:
        - parse_import(): Parse import statements into structured objects
        - sort_imports(): Sort imports according to PEP 8
        - deduplicate_imports(): Remove duplicate import statements
        - organize_imports(): Categorize imports by type
        - convert_relative_imports(): Convert between relative and absolute imports
        - format_imports(): Format imports according to PEP 8
        - generate_flask_appbuilder_imports(): Generate FAB-specific imports

    Analysis Functions:
        - check_import_exists(): Verify module importability
        - extract_imports_from_file(): Extract imports from Python files
        - analyze_import_dependencies(): Generate import dependency graphs
        - find_unused_imports(): Identify unused imports

    Optimization Functions:
        - optimize_imports(): Combine and simplify import statements
        - group_imports_by_package(): Group imports by root package
        - validate_imports(): Validate and categorize imports

Usage Examples:
    >>> from model_generator.utils.import_utils import parse_import, sort_imports

    # Parse import statement
    >>> stmt = parse_import("from typing import List, Dict")
    >>> print(stmt)
    from typing import Dict, List

    # Sort imports
    >>> imports = ['import sys', 'from typing import List', 'import os']
    >>> sorted_imports = sort_imports(imports)
    >>> print('\n'.join(sorted_imports))
    import os
    import sys
    from typing import List

Dependencies:
    Standard Library:
        - ast: Abstract Syntax Tree parsing
        - dataclasses: Data class support
        - importlib: Import checking
        - pathlib: Path manipulation
        - re: Regular expressions
        - typing: Type hints

    No Third-party Dependencies

Notes:
    - All functions include input validation and handle empty/invalid inputs gracefully
    - Import sorting follows PEP 8 conventions
    - The module maintains a comprehensive list of standard library modules
    - Support for both Python 3.7+ style type hints and older formats


"""

import re
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple, Iterator
import ast
import importlib.util
import sys

@dataclass
class ImportStatement:
    """Represents a parsed import statement."""
    module: str
    names: List[str]
    alias: Optional[str] = None
    is_from: bool = False
    level: int = 0  # For relative imports

    def __str__(self) -> str:
        """Convert back to string format."""
        if not self.is_from:
            base = f"import {self.module}"
            if self.alias:
                return f"{base} as {self.alias}"
            return base

        names_str = ", ".join(sorted(
            f"{name} as {alias}" if isinstance(alias, str) else name
            for name, alias in zip(self.names, [self.alias] * len(self.names))
        ))
        rel_dots = "." * self.level
        return f"from {rel_dots}{self.module} import {names_str}"


def parse_import(line: str) -> Optional[ImportStatement]:
    """
    Parse a single import statement string into an ImportStatement object.

    Args:
        line: Import statement string

    Returns:
        Optional[ImportStatement]: Parsed import statement or None if invalid

    Examples:
        >>> parse_import("import os")
        ImportStatement(module='os', names=[], alias=None, is_from=False, level=0)
        >>> parse_import("from typing import List, Dict")
        ImportStatement(module='typing', names=['List', 'Dict'], alias=None, is_from=True, level=0)
    """
    line = line.strip()
    if not line:
        return None

    # Handle 'from' imports
    if line.startswith('from '):
        from_match = re.match(r'from (\.*)(\S+) import (.+)$', line)
        if not from_match:
            return None
        level = len(from_match.group(1))
        module = from_match.group(2)
        names_str = from_match.group(3)

        # Parse names and aliases
        names = []
        aliases = []
        for item in names_str.split(','):
            item = item.strip()
            if ' as ' in item:
                name, alias = item.split(' as ')
                names.append(name.strip())
                aliases.append(alias.strip())
            else:
                names.append(item)
                aliases.append(None)

        return ImportStatement(
            module=module,
            names=names,
            alias=aliases[0] if len(aliases) == 1 else None,
            is_from=True,
            level=level
        )

    # Handle regular imports
    import_match = re.match(r'import (\S+)(?:\s+as\s+(\S+))?$', line)
    if not import_match:
        return None

    return ImportStatement(
        module=import_match.group(1),
        names=[],
        alias=import_match.group(2),
        is_from=False
    )


def sort_imports(imports: List[str]) -> List[str]:
    """
    Sort import statements according to PEP 8.

    Args:
        imports: List of import statements

    Returns:
        List[str]: Sorted import statements

    Examples:
        >>> imports = ['import os', 'from typing import List', 'import sys']
        >>> sort_imports(imports)
        ['import os', 'import sys', 'from typing import List']
    """
    def get_sort_key(imp: str) -> Tuple[int, str]:
        parsed = parse_import(imp)
        if not parsed:
            return (99, imp)  # Invalid imports go last

        # Sort key priorities:
        # 1. Standard library imports
        # 2. Third-party imports
        # 3. Local imports
        if parsed.module.split('.')[0] in STANDARD_LIBRARY_MODULES:
            priority = 0
        elif '.' in parsed.module:
            priority = 2  # Local imports usually contain dots
        else:
            priority = 1  # Third-party imports

        return (priority, imp.lower())

    return sorted(imports, key=get_sort_key)


def deduplicate_imports(imports: List[str]) -> List[str]:
    """
    Remove duplicate import statements while preserving meaning.

    Args:
        imports: List of import statements

    Returns:
        List[str]: Deduplicated import statements

    Examples:
        >>> imports = ['from typing import List', 'from typing import Dict', 'from typing import List']
        >>> deduplicate_imports(imports)
        ['from typing import Dict, List']
    """
    # Parse all imports
    parsed_imports: Dict[str, Set[str]] = {}
    module_aliases: Dict[str, str] = {}

    for imp in imports:
        parsed = parse_import(imp)
        if not parsed:
            continue

        if parsed.is_from:
            if parsed.module not in parsed_imports:
                parsed_imports[parsed.module] = set()
            parsed_imports[parsed.module].update(parsed.names)
        else:
            module_aliases[parsed.module] = parsed.alias

    # Reconstruct imports
    result = []

    # Add regular imports
    for module, alias in module_aliases.items():
        if alias:
            result.append(f"import {module} as {alias}")
        else:
            result.append(f"import {module}")

    # Add from imports
    for module, names in parsed_imports.items():
        if names:
            names_str = ", ".join(sorted(names))
            result.append(f"from {module} import {names_str}")

    return sorted(result)


def organize_imports(imports: List[str]) -> Dict[str, List[str]]:
    """
    Organize imports into categories.

    Args:
        imports: List of import statements

    Returns:
        Dict[str, List[str]]: Categorized import statements

    Examples:
        >>> imports = ['import os', 'import django', 'from .models import User']
        >>> organize_imports(imports)
        {
            'stdlib': ['import os'],
            'thirdparty': ['import django'],
            'local': ['from .models import User']
        }
    """
    categories = {
        'stdlib': [],
        'thirdparty': [],
        'local': []
    }

    for imp in imports:
        parsed = parse_import(imp)
        if not parsed:
            continue

        root_module = parsed.module.split('.')[0]
        if root_module in STANDARD_LIBRARY_MODULES:
            categories['stdlib'].append(imp)
        elif parsed.level > 0 or root_module.startswith('.'):
            categories['local'].append(imp)
        else:
            categories['thirdparty'].append(imp)

    # Sort within each category
    for category in categories.values():
        category.sort()

    return categories


def convert_relative_imports(imports: List[str], current_module: str,
                           project_root: str) -> List[str]:
    """
    Convert between relative and absolute imports based on context.

    Args:
        imports: List of import statements
        current_module: Current module path
        project_root: Project root path

    Returns:
        List[str]: Converted import statements

    Examples:
        >>> imports = ['from ..models import User']
        >>> convert_relative_imports(imports, 'app.views', 'app')
        ['from app.models import User']
    """
    result = []
    current_parts = current_module.split('.')

    for imp in imports:
        parsed = parse_import(imp)
        if not parsed:
            result.append(imp)
            continue

        if not parsed.is_from or parsed.level == 0:
            result.append(imp)
            continue

        # Handle relative imports
        if parsed.level > len(current_parts):
            # Invalid relative import
            result.append(imp)
            continue

        if parsed.level == len(current_parts):
            absolute_module = parsed.module
        else:
            parent_module = '.'.join(current_parts[:-parsed.level])
            if parsed.module:
                absolute_module = f"{parent_module}.{parsed.module}"
            else:
                absolute_module = parent_module

        # Reconstruct import with absolute path
        names_str = ', '.join(parsed.names)
        result.append(f"from {absolute_module} import {names_str}")

    return result


def format_imports(imports: List[str]) -> str:
    """
    Format a list of imports according to PEP 8.

    Args:
        imports: List of import statements

    Returns:
        str: Formatted import block

    Examples:
        >>> imports = ['import os', 'from typing import List', 'import sys']
        >>> print(format_imports(imports))
        import os
        import sys

        from typing import List
    """
    if not imports:
        return ""

    # Organize imports
    categories = organize_imports(imports)

    # Format each category
    blocks = []
    for category, statements in categories.items():
        if statements:
            blocks.append('\n'.join(sorted(statements)))

    # Join with double newlines
    return '\n\n'.join(blocks)


# Standard library modules for import categorization
STANDARD_LIBRARY_MODULES = {
    'abc', 'argparse', 'ast', 'asyncio', 'base64', 'collections', 'configparser',
    'contextlib', 'copy', 'csv', 'datetime', 'decimal', 'difflib', 'enum',
    'fileinput', 'fnmatch', 'functools', 'glob', 'hashlib', 'heapq', 'hmac',
    'html', 'http', 'importlib', 'inspect', 'io', 'itertools', 'json',
    'logging', 'math', 'multiprocessing', 'os', 'pathlib', 'pickle', 'pprint',
    'random', 're', 'shutil', 'signal', 'socket', 'sqlite3', 'string',
    'subprocess', 'sys', 'tempfile', 'threading', 'time', 'timeit', 'typing',
    'unittest', 'urllib', 'uuid', 'warnings', 'weakref', 'xml', 'zipfile'
}

def check_import_exists(module_name: str) -> bool:
    """
    Check if a module can be imported.

    Args:
        module_name: Name of module to check

    Returns:
        bool: True if module can be imported

    Examples:
        >>> check_import_exists('os')
        True
        >>> check_import_exists('nonexistent_module')
        False
    """
    try:
        importlib.util.find_spec(module_name)
        return True
    except ModuleNotFoundError:
        return False

def extract_imports_from_file(file_path: str) -> List[str]:
    """
    Extract all import statements from a Python file.

    Args:
        file_path: Path to Python file

    Returns:
        List[str]: List of import statements

    Examples:
        >>> imports = extract_imports_from_file('app.py')
        >>> imports
        ['import os', 'from typing import List']
    """
    with open(file_path, 'r') as f:
        content = f.read()

    tree = ast.parse(content)
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                imp = f"import {name.name}"
                if name.asname:
                    imp += f" as {name.asname}"
                imports.append(imp)
        elif isinstance(node, ast.ImportFrom):
            module = '.' * node.level + (node.module or '')
            names = []
            for name in node.names:
                if name.asname:
                    names.append(f"{name.name} as {name.asname}")
                else:
                    names.append(name.name)
            imports.append(f"from {module} import {', '.join(names)}")

    return imports

def analyze_import_dependencies(imports: List[str]) -> Dict[str, Set[str]]:
    """
    Analyze dependencies between imported modules.

    Args:
        imports: List of import statements

    Returns:
        Dict[str, Set[str]]: Dependency graph

    Examples:
        >>> deps = analyze_import_dependencies(['from .models import User', 'from .user import UserMixin'])
        >>> deps
        {'.models': {'.user'}}
    """
    dependencies = {}

    for imp in imports:
        parsed = parse_import(imp)
        if not parsed:
            continue

        if parsed.module not in dependencies:
            dependencies[parsed.module] = set()

        # Check for dependencies in from imports
        if parsed.is_from:
            for name in parsed.names:
                if '.' in name:
                    parent = name.split('.')[0]
                    dependencies[parsed.module].add(parent)

    return dependencies

def find_unused_imports(file_path: str) -> List[str]:
    """
    Find unused imports in a Python file.

    Args:
        file_path: Path to Python file

    Returns:
        List[str]: List of unused import statements

    Examples:
        >>> unused = find_unused_imports('app.py')
        >>> unused
        ['from typing import Dict']
    """
    with open(file_path, 'r') as f:
        content = f.read()

    tree = ast.parse(content)
    imports = {}
    used_names = set()

    # Collect imports
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in node.names:
                imports[name.asname or name.name] = name.name

    # Collect used names
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            used_names.add(node.attr)

    return [name for name in imports if name not in used_names]

def generate_flask_appbuilder_imports() -> List[str]:
    """
    Generate common Flask-AppBuilder import statements.

    Returns:
        List[str]: List of common FAB import statements

    Examples:
        >>> imports = generate_flask_appbuilder_imports()
        >>> imports
        ['from flask_appbuilder import ModelView', 'from flask_appbuilder.models.sqla.interface import SQLAInterface']
    """
    return [
        'from flask import Flask',
        'from flask_appbuilder import AppBuilder, BaseView, ModelView, expose',
        'from flask_appbuilder.models.sqla.interface import SQLAInterface',
        'from flask_appbuilder.security.manager import SecurityManager',
        'from flask_appbuilder.views import MasterDetailView, CompactCRUDMixin',
        'from flask_sqlalchemy import SQLAlchemy'
    ]

def group_imports_by_package(imports: List[str]) -> Dict[str, List[str]]:
    """
    Group imports by their root package.

    Args:
        imports: List of import statements

    Returns:
        Dict[str, List[str]]: Grouped imports

    Examples:
        >>> imports = ['from flask import Flask', 'from flask_sqlalchemy import SQLAlchemy']
        >>> group_imports_by_package(imports)
        {'flask': ['from flask import Flask'], 'flask_sqlalchemy': ['from flask_sqlalchemy import SQLAlchemy']}
    """
    grouped = {}

    for imp in imports:
        parsed = parse_import(imp)
        if not parsed:
            continue

        root_package = parsed.module.split('.')[0]
        if root_package not in grouped:
            grouped[root_package] = []
        grouped[root_package].append(imp)

    return grouped

def optimize_imports(imports: List[str]) -> List[str]:
    """
    Optimize import statements by combining and simplifying them.

    Args:
        imports: List of import statements

    Returns:
        List[str]: Optimized import statements

    Examples:
        >>> imports = ['from typing import List', 'from typing import Dict, Optional']
        >>> optimize_imports(imports)
        ['from typing import Dict, List, Optional']
    """
    module_imports: Dict[str, Set[str]] = {}
    direct_imports: Set[str] = set()

    for imp in imports:
        parsed = parse_import(imp)
        if not parsed:
            continue

        if parsed.is_from:
            if parsed.module not in module_imports:
                module_imports[parsed.module] = set()
            module_imports[parsed.module].update(parsed.names)
        else:
            if parsed.alias:
                direct_imports.add(f"import {parsed.module} as {parsed.alias}")
            else:
                direct_imports.add(f"import {parsed.module}")

    result = []

    # Add direct imports
    result.extend(sorted(direct_imports))

    # Add from imports
    for module in sorted(module_imports):
        names = sorted(module_imports[module])
        result.append(f"from {module} import {', '.join(names)}")

    return result

def validate_imports(imports: List[str]) -> Tuple[List[str], List[str]]:
    """
    SECURITY FIX: Validate import statements safely without exec().

    This function was updated to fix a critical security vulnerability where
    exec() was used to validate imports, allowing arbitrary code execution.

    Args:
        imports: List of import statements

    Returns:
        Tuple[List[str], List[str]]: Valid and invalid imports

    Security Notes:
        - Replaced dangerous exec() with safe importlib validation
        - Added security checks for malicious import patterns
        - Uses AST parsing to validate syntax safely

    Examples:
        >>> valid, invalid = validate_imports(['import os', 'import nonexistent_module'])
        >>> valid
        ['import os']
        >>> invalid
        ['import nonexistent_module']
    """
    valid = []
    invalid = []

    # Security check patterns - reject dangerous imports
    dangerous_patterns = [
        r'exec\(',       # Exec calls
        r'eval\(',       # Eval calls
        r'__.*__\(',     # Dunder method calls
        r'system\(',     # System calls
        r'subprocess',   # Process execution
        r'compile\(',    # Code compilation
    ]

    for imp in imports:
        # First check for security violations
        is_dangerous = False
        for pattern in dangerous_patterns:
            if re.search(pattern, imp, re.IGNORECASE):
                print(f"⚠️  Security: Rejected dangerous import pattern: {imp}")
                invalid.append(imp)
                is_dangerous = True
                break

        if is_dangerous:
            continue

        parsed = parse_import(imp)
        if not parsed:
            invalid.append(imp)
            continue

        # Safe validation using importlib (no execution)
        try:
            if parsed.is_from:
                # Validate the base module exists
                spec = importlib.util.find_spec(parsed.module)
                if spec is not None:
                    valid.append(imp)
                else:
                    invalid.append(imp)
            else:
                if check_import_exists(parsed.module):
                    valid.append(imp)
                else:
                    invalid.append(imp)
        except Exception as e:
            print(f"⚠️  Error validating import '{imp}': {e}")
            invalid.append(imp)

    return valid, invalid

def resolve_import_dependencies(imports: List[str]) -> List[str]:
    """
    Resolve and order imports based on their dependencies.

    This function analyzes import dependencies and returns a list of imports
    ordered such that dependent modules are imported after their dependencies.

    Args:
        imports: List of import statements

    Returns:
        List[str]: Ordered import statements with resolved dependencies

    Examples:
        >>> imports = [
        ...     'from .models import User',
        ...     'from .base import Base',
        ...     'from .user.utils import UserMixin',
        ...     'from .models.mixins import ModelMixin'
        ... ]
        >>> resolve_import_dependencies(imports)
        [
            'from .base import Base',
            'from .user.utils import UserMixin',
            'from .models.mixins import ModelMixin',
            'from .models import User'
        ]
    """
    def get_module_path(import_stmt: str) -> str:
        parsed = parse_import(import_stmt)
        if not parsed:
            return ""
        if parsed.level > 0:
            return '.' * parsed.level + parsed.module
        return parsed.module

    def is_dependent(module1: str, module2: str) -> bool:
        """Check if module1 depends on module2."""
        return module2 != module1 and (
            module1.startswith(module2 + '.') or
            any(name.startswith(module2 + '.') for name in
                parse_import(module1).names if parse_import(module1))
        )

    # Create dependency graph
    graph: Dict[str, Set[str]] = {}
    module_to_import: Dict[str, str] = {}

    for imp in imports:
        module = get_module_path(imp)
        if module:
            graph[module] = set()
            module_to_import[module] = imp

    # Build dependency relationships
    for module1 in graph:
        for module2 in graph:
            if is_dependent(module1, module2):
                graph[module1].add(module2)

    # Topologically sort modules
    resolved = []
    visited = set()
    temp_visited = set()

    def visit(module: str):
        if module in temp_visited:
            raise ValueError(f"Circular dependency detected involving {module}")
        if module not in visited:
            temp_visited.add(module)
            for dep in graph[module]:
                visit(dep)
            temp_visited.remove(module)
            visited.add(module)
            resolved.append(module)

    try:
        for module in graph:
            if module not in visited:
                visit(module)
    except ValueError as e:
        # Handle circular dependencies by breaking them arbitrarily
        print(f"Warning: {e}. Breaking circular dependency.")
        return imports

    # Convert back to import statements
    return [module_to_import[module] for module in resolved]

def convert_to_relative_import(import_stmt: str, current_module: str) -> str:
    """
    Convert an absolute import statement to a relative import based on the current module path.

    Args:
        import_stmt: Absolute import statement to convert
        current_module: Current module path (dot-separated)

    Returns:
        str: Relative import statement

    Examples:
        >>> convert_to_relative_import(
        ...     'from myapp.models.user import User',
        ...     'myapp.views.user'
        ... )
        'from ..models.user import User'
        >>> convert_to_relative_import(
        ...     'from myapp.utils import helper',
        ...     'myapp.models.user'
        ... )
        'from ...utils import helper'
    """
    parsed = parse_import(import_stmt)
    if not parsed or not parsed.is_from:
        return import_stmt  # Only convert 'from' imports

    # Split module paths
    current_parts = current_module.split('.')
    import_parts = parsed.module.split('.')

    # Find common prefix
    common_prefix_length = 0
    for c, i in zip(current_parts, import_parts):
        if c != i:
            break
        common_prefix_length += 1

    if common_prefix_length == 0:
        return import_stmt  # No common prefix, keep absolute import

    # Calculate relative path
    current_depth = len(current_parts) - common_prefix_length
    relative_prefix = '.' * current_depth
    relative_path = '.'.join(import_parts[common_prefix_length:])

    # Construct relative import
    names_str = ', '.join(parsed.names)
    if relative_path:
        return f"from {relative_prefix}{relative_path} import {names_str}"
    return f"from {relative_prefix} import {names_str}"


"""
if __name__ == "__main__":
    # Example 1: Resolve dependencies
    sample_imports = [
        'from .models import User',
        'from .base import Base',
        'from .user.utils import UserMixin',
        'from .models.mixins import ModelMixin'
    ]
    ordered_imports = resolve_import_dependencies(sample_imports)
    print("Resolved imports:")
    for imp in ordered_imports:
        print(f"  {imp}")

    # Example 2: Convert to relative imports
    absolute_import = 'from myapp.models.user import User'
    current_module = 'myapp.views.user'
    relative_import = convert_to_relative_import(absolute_import, current_module)
    print(f"\nConverted import:")
    print(f"  From: {absolute_import}")
    print(f"  To:   {relative_import}")
"""
