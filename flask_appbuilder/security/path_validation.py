"""
Secure path validation utilities for Flask-AppBuilder.

This module provides comprehensive path validation to prevent directory traversal
attacks and ensure file operations are constrained to allowed directories.
"""

import os
import logging
from pathlib import Path, PurePath
from typing import Union, List, Optional, Set
from urllib.parse import unquote
import re

logger = logging.getLogger(__name__)


class PathTraversalError(ValueError):
    """Exception raised for path traversal security violations."""
    pass


class InvalidPathError(ValueError):
    """Exception raised for invalid path formats."""
    pass


class SecurePathValidator:
    """
    Comprehensive path validation to prevent directory traversal attacks.

    This class provides multiple validation layers to ensure file paths
    are safe and constrained to allowed directories.
    """

    # Dangerous path patterns
    DANGEROUS_PATTERNS = {
        # Directory traversal patterns
        r'\.\.[\\/]',           # ../  or ..\
        r'[\\/]\.\.[\\/]',      # /../ or \..\
        r'[\\/]\.\.$',          # /.. or \.. at end
        r'^\.\.[\\/]',          # ../ or ..\ at start
        r'^\.\.?$',             # . or .. as complete path

        # URL encoded traversal patterns
        r'%2e%2e[\\/]',         # URL encoded ../
        r'%2e%2e%2f',           # URL encoded ../
        r'%2e%2e%5c',           # URL encoded ..\
        r'\.%2e[\\/]',          # Mixed encoding
        r'%2e\.[\\/]',          # Mixed encoding

        # Unicode and alternative encodings
        r'\u002e\u002e[\\/]',   # Unicode ../
        r'\uff0e\uff0e[\\/]',   # Fullwidth ../

        # Null byte injection
        r'\x00',                # Null bytes

        # Windows specific patterns
        r'[\\/]con[\\/]',       # Windows reserved CON
        r'[\\/]prn[\\/]',       # Windows reserved PRN
        r'[\\/]aux[\\/]',       # Windows reserved AUX
        r'[\\/]nul[\\/]',       # Windows reserved NUL
        r'[\\/]com[0-9][\\/]',  # Windows reserved COM ports
        r'[\\/]lpt[0-9][\\/]',  # Windows reserved LPT ports

        # UNC paths and network shares
        r'^[\\/]{2,}',          # UNC paths \\server

        # Stream names (Windows)
        r'::?\$',               # NTFS alternate data streams
    }

    # Compiled regex patterns for performance
    _compiled_patterns: Optional[List[re.Pattern]] = None

    def __init__(self, allowed_base_paths: Optional[List[Union[str, Path]]] = None):
        """
        Initialize path validator.

        Args:
            allowed_base_paths: List of allowed base directory paths
        """
        self.allowed_base_paths: Set[Path] = set()

        if allowed_base_paths:
            for base_path in allowed_base_paths:
                self.add_allowed_base_path(base_path)

        # Compile regex patterns if not already done
        if SecurePathValidator._compiled_patterns is None:
            SecurePathValidator._compiled_patterns = [
                re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                for pattern in self.DANGEROUS_PATTERNS
            ]

    def add_allowed_base_path(self, base_path: Union[str, Path]) -> None:
        """
        Add an allowed base path.

        Args:
            base_path: Base path to allow operations under
        """
        path_obj = Path(base_path).resolve()
        self.allowed_base_paths.add(path_obj)
        logger.debug(f"Added allowed base path: {path_obj}")

    def validate_path(self, path: Union[str, Path],
                     base_path: Optional[Union[str, Path]] = None,
                     allow_symlinks: bool = False) -> Path:
        """
        Validate a file path for security issues.

        Args:
            path: Path to validate
            base_path: Optional base path to constrain operations to
            allow_symlinks: Whether to allow symbolic links

        Returns:
            Validated and resolved Path object

        Raises:
            PathTraversalError: If path contains traversal attempts
            InvalidPathError: If path format is invalid
        """
        try:
            # Convert to string and normalize
            path_str = str(path)

            # URL decode if needed
            if '%' in path_str:
                path_str = unquote(path_str)

            # Normalize path separators
            path_str = self._normalize_path_separators(path_str)

            # Check for dangerous patterns
            self._check_dangerous_patterns(path_str)

            # Convert to Path object
            path_obj = Path(path_str)

            # Validate path components
            self._validate_path_components(path_obj)

            # Resolve the path - handle non-existent paths gracefully
            try:
                if path_obj.exists():
                    resolved_path = path_obj.resolve()
                else:
                    # For non-existent paths, construct the resolved path manually
                    resolved_path = (path_obj.parent.resolve() / path_obj.name) if path_obj.parent.exists() else path_obj.resolve()
            except (OSError, RuntimeError) as e:
                # Handle infinite loops or invalid paths
                raise InvalidPathError(f"Cannot resolve path: {path_str}") from e

            # Check for symlink attacks if not allowed
            if not allow_symlinks:
                self._check_symlinks(path_obj, resolved_path)

            # Validate against base path if provided
            if base_path:
                self._validate_base_path_constraint(resolved_path, base_path)
            elif self.allowed_base_paths:
                self._validate_allowed_base_paths(resolved_path)

            # Additional security checks
            self._additional_security_checks(resolved_path)

            return resolved_path

        except (PathTraversalError, InvalidPathError):
            raise
        except Exception as e:
            raise InvalidPathError(f"Path validation failed: {path}") from e

    def validate_filename(self, filename: str, allow_unicode: bool = True) -> str:
        """
        Validate a filename for security issues.

        Args:
            filename: Filename to validate
            allow_unicode: Whether to allow unicode characters

        Returns:
            Validated filename

        Raises:
            InvalidPathError: If filename is invalid
        """
        if not filename or not filename.strip():
            raise InvalidPathError("Filename cannot be empty")

        # Remove any path separators
        clean_filename = filename.replace('/', '').replace('\\', '').replace(os.sep, '')

        if clean_filename != filename:
            raise PathTraversalError(f"Filename cannot contain path separators: {filename}")

        # Check for dangerous patterns
        self._check_dangerous_patterns(clean_filename)

        # Check for reserved names (Windows)
        if self._is_reserved_filename(clean_filename):
            raise InvalidPathError(f"Filename uses reserved name: {filename}")

        # Check for control characters
        if any(ord(c) < 32 for c in clean_filename):
            raise InvalidPathError(f"Filename contains control characters: {filename}")

        # Unicode validation
        if not allow_unicode:
            if not clean_filename.isascii():
                raise InvalidPathError(f"Filename contains non-ASCII characters: {filename}")

        # Length validation
        if len(clean_filename) > 255:
            raise InvalidPathError(f"Filename too long (max 255 characters): {filename}")

        return clean_filename

    def safe_join(self, base_path: Union[str, Path],
                  *paths: Union[str, Path]) -> Path:
        """
        Safely join paths, preventing directory traversal.

        Args:
            base_path: Base directory path
            *paths: Path components to join

        Returns:
            Safely joined path

        Raises:
            PathTraversalError: If resulting path escapes base directory
        """
        # Validate base path first
        base_path_obj = Path(base_path).resolve()

        # Build the joined path component by component
        result_path = base_path_obj
        for path_component in paths:
            # Convert to string and normalize
            component_str = str(path_component)

            # Check for dangerous patterns in the full component
            self._check_dangerous_patterns(component_str)

            # Split component by path separators and validate each part
            path_parts = Path(component_str).parts

            for part in path_parts:
                if part in ('..', '.'):
                    raise PathTraversalError(f"Path contains traversal component: {part}")
                if part.startswith('.') and len(part) > 1:
                    logger.warning(f"Path contains hidden file/directory: {part}")

                # Validate part as filename
                self.validate_filename(part, allow_unicode=True)
                result_path = result_path / part

        # Final validation to ensure we're still within base path
        try:
            result_path.resolve().relative_to(base_path_obj)
        except ValueError:
            raise PathTraversalError(
                f"Joined path escapes base directory: {result_path} not under {base_path_obj}"
            )

        return result_path

    def _normalize_path_separators(self, path_str: str) -> str:
        """Normalize path separators for consistent checking."""
        # Replace Windows separators with Unix separators
        return path_str.replace('\\', '/')

    def _check_dangerous_patterns(self, path_str: str) -> None:
        """Check for dangerous patterns in path string."""
        for pattern in self._compiled_patterns:
            if pattern.search(path_str):
                raise PathTraversalError(f"Path contains dangerous pattern: {path_str}")

    def _validate_path_components(self, path_obj: Path) -> None:
        """Validate individual path components."""
        for part in path_obj.parts:
            if part in ('..', '.'):
                raise PathTraversalError(f"Path contains traversal component: {part}")

            # Check for hidden files starting with dots (security consideration)
            if part.startswith('.') and len(part) > 1:
                logger.warning(f"Path contains hidden file/directory: {part}")

    def _check_symlinks(self, original_path: Path, resolved_path: Path) -> None:
        """Check for symbolic link attacks."""
        # Only check for symlinks within user-controlled portions of the path
        # Skip system-level symlinks like /var -> /private/var on macOS
        try:
            # Check if the final target file/directory itself is a symlink
            if original_path.exists() and original_path.is_symlink():
                # Allow symlinks that point within the same directory tree
                link_target = original_path.readlink()
                if link_target.is_absolute():
                    raise PathTraversalError(f"Path contains absolute symbolic link: {original_path} -> {link_target}")

                # Resolve the symlink and check if it escapes the allowed area
                resolved_target = (original_path.parent / link_target).resolve()
                if self.allowed_base_paths:
                    # Check if symlink target is within allowed base paths
                    for allowed_base in self.allowed_base_paths:
                        try:
                            resolved_target.relative_to(allowed_base)
                            return  # Target is within allowed area
                        except ValueError:
                            continue
                    raise PathTraversalError(f"Symbolic link points outside allowed area: {original_path} -> {resolved_target}")

        except (OSError, RuntimeError):
            # Handle broken symlinks or infinite loops
            raise PathTraversalError(f"Invalid or broken symbolic link: {original_path}")

    def _validate_base_path_constraint(self, resolved_path: Path, base_path: Union[str, Path]) -> None:
        """Validate that resolved path is within base path."""
        base_path_obj = Path(base_path).resolve()

        try:
            resolved_path.relative_to(base_path_obj)
        except ValueError:
            raise PathTraversalError(
                f"Path escapes base directory: {resolved_path} not under {base_path_obj}"
            )

    def _validate_allowed_base_paths(self, resolved_path: Path) -> None:
        """Validate that resolved path is within one of the allowed base paths."""
        for allowed_base in self.allowed_base_paths:
            try:
                resolved_path.relative_to(allowed_base)
                return  # Path is under an allowed base
            except ValueError:
                continue

        raise PathTraversalError(
            f"Path not under any allowed base directory: {resolved_path}"
        )

    def _additional_security_checks(self, resolved_path: Path) -> None:
        """Additional security checks for resolved path."""
        # Check for system directories (Unix)
        system_dirs = {'/etc', '/proc', '/sys', '/dev', '/root'}
        path_str = str(resolved_path)

        for sys_dir in system_dirs:
            if path_str.startswith(sys_dir):
                logger.warning(f"Path accesses system directory: {resolved_path}")

        # Check for temp directories with additional scrutiny
        if '/tmp' in path_str or '/var/tmp' in path_str:
            logger.info(f"Path accesses temporary directory: {resolved_path}")

    def _is_reserved_filename(self, filename: str) -> bool:
        """Check if filename is a Windows reserved name."""
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }

        # Remove extension for check
        name_without_ext = filename.split('.')[0].upper()
        return name_without_ext in reserved_names


class SecureFileHandler:
    """
    Secure file handler with path validation and additional safety measures.
    """

    def __init__(self, base_directory: Union[str, Path],
                 allowed_extensions: Optional[Set[str]] = None):
        """
        Initialize secure file handler.

        Args:
            base_directory: Base directory for file operations
            allowed_extensions: Set of allowed file extensions (with dots)
        """
        self.validator = SecurePathValidator([base_directory])
        self.base_directory = Path(base_directory).resolve()
        self.allowed_extensions = allowed_extensions or set()

    def safe_open(self, relative_path: Union[str, Path], mode: str = 'r', **kwargs):
        """
        Safely open a file with path validation.

        Args:
            relative_path: Relative path to file
            mode: File open mode
            **kwargs: Additional arguments for open()

        Returns:
            File object

        Raises:
            PathTraversalError: If path validation fails
        """
        # Validate and construct safe path
        safe_path = self.validator.safe_join(self.base_directory, relative_path)

        # Validate file extension if restrictions are set
        if self.allowed_extensions and safe_path.suffix.lower() not in self.allowed_extensions:
            raise InvalidPathError(f"File extension not allowed: {safe_path.suffix}")

        # Additional checks for write modes
        if 'w' in mode or 'a' in mode:
            # Ensure parent directory exists
            safe_path.parent.mkdir(parents=True, exist_ok=True)

        return open(safe_path, mode, **kwargs)

    def safe_exists(self, relative_path: Union[str, Path]) -> bool:
        """
        Safely check if file exists.

        Args:
            relative_path: Relative path to check

        Returns:
            True if file exists, False otherwise
        """
        try:
            safe_path = self.validator.safe_join(self.base_directory, relative_path)
            return safe_path.exists()
        except (PathTraversalError, InvalidPathError):
            return False

    def safe_remove(self, relative_path: Union[str, Path]) -> bool:
        """
        Safely remove a file.

        Args:
            relative_path: Relative path to file

        Returns:
            True if file was removed, False otherwise
        """
        try:
            safe_path = self.validator.safe_join(self.base_directory, relative_path)
            if safe_path.exists() and safe_path.is_file():
                safe_path.unlink()
                return True
        except (PathTraversalError, InvalidPathError, OSError):
            pass
        return False

    def list_safe_files(self, relative_path: Union[str, Path] = '.') -> List[Path]:
        """
        Safely list files in directory.

        Args:
            relative_path: Relative directory path

        Returns:
            List of safe file paths
        """
        try:
            safe_path = self.validator.safe_join(self.base_directory, relative_path)
            if safe_path.is_dir():
                return [
                    file_path.relative_to(self.base_directory)
                    for file_path in safe_path.iterdir()
                    if file_path.is_file()
                ]
        except (PathTraversalError, InvalidPathError, OSError):
            pass
        return []


# Convenience functions for quick validation
def validate_safe_path(path: Union[str, Path],
                      base_path: Optional[Union[str, Path]] = None) -> Path:
    """
    Quick path validation function.

    Args:
        path: Path to validate
        base_path: Optional base path constraint

    Returns:
        Validated Path object
    """
    validator = SecurePathValidator()
    return validator.validate_path(path, base_path=base_path)


def validate_safe_filename(filename: str) -> str:
    """
    Quick filename validation function.

    Args:
        filename: Filename to validate

    Returns:
        Validated filename
    """
    validator = SecurePathValidator()
    return validator.validate_filename(filename)


def safe_path_join(base_path: Union[str, Path], *paths: Union[str, Path]) -> Path:
    """
    Quick safe path joining function.

    Args:
        base_path: Base directory path
        *paths: Path components to join

    Returns:
        Safely joined path
    """
    validator = SecurePathValidator()
    return validator.safe_join(base_path, *paths)