"""
Secure import validation utilities for Flask-AppBuilder CLI.

This module provides secure import statement validation without executing code,
preventing code injection vulnerabilities.
"""

import importlib.util
import ast
import re
from typing import Tuple, List, Optional, NamedTuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

class ImportInfo(NamedTuple):
    """Information about a parsed import statement."""
    module: str
    name: Optional[str] = None
    alias: Optional[str] = None

@dataclass
class ValidationResult:
    """Standardized import validation result."""
    is_valid: bool
    imports: List[str]
    errors: List[str]
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

def parse_import(import_statement: str) -> Optional[ImportInfo]:
    """
    Parse import statement safely using AST.

    Args:
        import_statement: Import statement string to parse

    Returns:
        ImportInfo if valid, None if invalid

    Examples:
        >>> parse_import("import os")
        ImportInfo(module='os', name=None, alias=None)
        >>> parse_import("from typing import List")
        ImportInfo(module='typing', name='List', alias=None)
    """
    try:
        # Normalize whitespace
        import_statement = import_statement.strip()

        if not import_statement:
            return None

        # Basic security validation - reject obviously malicious patterns
        dangerous_patterns = [
            r'__.*__\(',     # Dunder method calls
            r'exec\(',       # Exec calls
            r'eval\(',       # Eval calls
            r'open\(',       # File operations
            r'os\.',         # OS operations
            r'subprocess',   # Process execution
            r'system\(',     # System calls
            r'compile\(',    # Code compilation
            r'globals\(',    # Globals access
            r'locals\(',     # Locals access
            r'vars\(',       # Vars access
            r'dir\(',        # Directory listing
            r'getattr\(',    # Dynamic attribute access
            r'setattr\(',    # Dynamic attribute setting
            r'delattr\(',    # Dynamic attribute deletion
            r'hasattr\(',    # Dynamic attribute checking
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, import_statement, re.IGNORECASE):
                logger.warning(f"Dangerous pattern detected in import: {import_statement}")
                return None

        # Parse using AST - safe parsing without execution
        tree = ast.parse(import_statement)

        if len(tree.body) != 1:
            return None

        stmt = tree.body[0]

        if isinstance(stmt, ast.Import):
            # Handle: import module [as alias]
            if len(stmt.names) == 1:
                alias_node = stmt.names[0]
                return ImportInfo(
                    module=alias_node.name,
                    alias=alias_node.asname
                )
        elif isinstance(stmt, ast.ImportFrom):
            # Handle: from module import name [as alias]
            if stmt.module and len(stmt.names) == 1:
                alias_node = stmt.names[0]
                return ImportInfo(
                    module=stmt.module,
                    name=alias_node.name,
                    alias=alias_node.asname
                )

        return None

    except (SyntaxError, ValueError) as e:
        logger.debug(f"Failed to parse import statement '{import_statement}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing import '{import_statement}': {e}")
        return None

def validate_imports_secure(imports: List[str]) -> ValidationResult:
    """
    Safely validate import statements without execution.

    This function replaces the dangerous exec() usage with safe validation
    using importlib.util.find_spec() to check module existence.

    Args:
        imports: List of import statement strings

    Returns:
        ValidationResult with valid imports, errors, and warnings

    Examples:
        >>> result = validate_imports_secure(['import os', 'import nonexistent'])
        >>> result.is_valid
        False
        >>> result.imports
        ['import os']
        >>> result.errors
        ['Module not found: nonexistent']
    """
    valid_imports = []
    errors = []
    warnings = []

    for imp in imports:
        # Parse the import statement
        parsed = parse_import(imp)
        if not parsed:
            errors.append(f"Invalid import syntax: {imp}")
            continue

        try:
            # Validate module exists using safe importlib method
            spec = importlib.util.find_spec(parsed.module)
            if spec is not None:
                valid_imports.append(imp)

                # Add warnings for potentially problematic imports
                if parsed.module in ['subprocess', 'os', 'sys']:
                    warnings.append(f"Potentially sensitive module: {parsed.module}")

            else:
                errors.append(f"Module not found: {parsed.module}")

        except (ImportError, ModuleNotFoundError, ValueError) as e:
            errors.append(f"Import error for {parsed.module}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error validating {parsed.module}: {e}")
            errors.append(f"Validation error for {parsed.module}: {e}")

    return ValidationResult(
        is_valid=len(errors) == 0,
        imports=valid_imports,
        errors=errors,
        warnings=warnings
    )

def check_import_exists_secure(module_name: str) -> bool:
    """
    Securely check if a module can be imported without executing it.

    Args:
        module_name: Name of module to check

    Returns:
        True if module exists and can be imported safely

    Examples:
        >>> check_import_exists_secure('os')
        True
        >>> check_import_exists_secure('nonexistent_module')
        False
    """
    try:
        # Use importlib.util.find_spec for safe checking
        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
    except Exception as e:
        logger.error(f"Error checking module {module_name}: {e}")
        return False

def validate_import_security(import_statement: str) -> Tuple[bool, str]:
    """
    Check if an import statement contains security risks.

    Args:
        import_statement: Import statement to validate

    Returns:
        Tuple of (is_safe, reason)

    Examples:
        >>> validate_import_security("import os")
        (True, "Safe import")
        >>> validate_import_security("exec('malicious')")
        (False, "Contains dangerous function call: exec")
    """
    # List of dangerous patterns that should never appear in imports
    dangerous_functions = [
        'exec', 'eval', 'compile', '__import__',
        'globals', 'locals', 'vars', 'dir',
        'getattr', 'setattr', 'delattr', 'hasattr'
    ]

    dangerous_modules = [
        'subprocess', 'os.system', 'commands'
    ]

    # Check for dangerous function calls
    for func in dangerous_functions:
        if f'{func}(' in import_statement:
            return False, f"Contains dangerous function call: {func}"

    # Check for system access patterns
    system_patterns = [
        r'system\(',
        r'popen\(',
        r'spawn\(',
        r'exec[lv]p?\(',
        r'subprocess\.call\(',
        r'subprocess\.run\(',
        r'subprocess\.Popen\(',
    ]

    for pattern in system_patterns:
        if re.search(pattern, import_statement):
            return False, f"Contains system access pattern: {pattern}"

    # Check for code injection patterns
    injection_patterns = [
        r'["\'][^"\']*[;&|][^"\']*["\']',  # Command injection in strings
        r'__.*__\(',                       # Dunder method access
        r'\$\{.*\}',                       # Variable substitution
    ]

    for pattern in injection_patterns:
        if re.search(pattern, import_statement):
            return False, f"Contains injection pattern: {pattern}"

    return True, "Safe import"

# Secure replacement for the dangerous validate_imports function
def validate_imports(imports: List[str]) -> Tuple[List[str], List[str]]:
    """
    SECURE REPLACEMENT for the dangerous exec()-based validation.

    This function replaces the critical security vulnerability where exec()
    was used to validate imports, which allowed arbitrary code execution.

    Args:
        imports: List of import statements to validate

    Returns:
        Tuple of (valid_imports, invalid_imports)

    Security Notes:
        - Uses AST parsing instead of exec() for safety
        - Validates using importlib.util.find_spec()
        - Includes security checks for malicious patterns
        - Logs security violations for monitoring
    """
    valid = []
    invalid = []

    for imp in imports:
        # First check for security violations
        is_safe, reason = validate_import_security(imp)
        if not is_safe:
            logger.warning(f"Security violation in import '{imp}': {reason}")
            invalid.append(imp)
            continue

        # Parse the import statement safely
        parsed = parse_import(imp)
        if not parsed:
            invalid.append(imp)
            continue

        # Validate module exists without executing
        try:
            if parsed.name:
                # For "from module import name" statements
                spec = importlib.util.find_spec(parsed.module)
                if spec is not None:
                    valid.append(imp)
                else:
                    invalid.append(imp)
            else:
                # For "import module" statements
                if check_import_exists_secure(parsed.module):
                    valid.append(imp)
                else:
                    invalid.append(imp)

        except Exception as e:
            logger.error(f"Error validating import '{imp}': {e}")
            invalid.append(imp)

    return valid, invalid