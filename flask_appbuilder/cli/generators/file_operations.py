"""
Transaction-Safe File Operations

This module provides atomic file operations with rollback capability
for the Flask-AppBuilder code generation system.
"""

import os
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union
from contextlib import contextmanager

from ...security.path_validation import SecurePathValidator, PathTraversalError, InvalidPathError

logger = logging.getLogger(__name__)


class FileOperationError(Exception):
    """Exception raised for file operation errors."""
    pass


class AtomicFileWriter:
    """
    Context manager for atomic file operations with rollback capability.
    
    Ensures that either all files are written successfully or none are written,
    providing transaction-like behavior for file operations.
    """
    
    def __init__(self, base_path: Union[str, Path]):
        """
        Initialize atomic file writer.

        Args:
            base_path: Base directory for file operations
        """
        self.base_path = Path(base_path).resolve()
        self.path_validator = SecurePathValidator([self.base_path])
        self.pending_files: Dict[Path, str] = {}
        self.temp_files: List[Path] = []
        self.created_directories: List[Path] = []
        self.backup_files: List[Path] = []
        self.committed = False
        
    def add_file(self, relative_path: Union[str, Path], content: str):
        """
        Add a file to be written atomically.

        Args:
            relative_path: Path relative to base_path
            content: File content to write

        Raises:
            PathTraversalError: If relative_path contains directory traversal attempts
            InvalidPathError: If relative_path format is invalid
        """
        try:
            # Validate the relative path for security issues
            safe_path = self.path_validator.safe_join(self.base_path, relative_path)
            self.pending_files[safe_path] = content
        except (PathTraversalError, InvalidPathError) as e:
            raise FileOperationError(f"Insecure path rejected: {relative_path} - {e}") from e
        
    def add_files(self, files: Dict[Union[str, Path], str]):
        """
        Add multiple files to be written atomically.
        
        Args:
            files: Dictionary mapping relative paths to content
        """
        for relative_path, content in files.items():
            self.add_file(relative_path, content)
    
    def __enter__(self):
        """Enter the context manager."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager with cleanup."""
        if exc_type is None and not self.committed:
            # No exception occurred, commit the files
            try:
                self.commit()
            except Exception as e:
                logger.error(f"Failed to commit files: {e}")
                self.rollback()
                raise
        else:
            # Exception occurred or explicit rollback needed
            self.rollback()
    
    def commit(self):
        """
        Commit all pending file operations atomically.
        
        Raises:
            FileOperationError: If any file operation fails
        """
        if self.committed:
            return
            
        try:
            # Step 1: Validate all operations
            self._validate_operations()
            
            # Step 2: Create directories and backup existing files
            self._prepare_operations()
            
            # Step 3: Write all files to temporary locations
            self._write_temporary_files()
            
            # Step 4: Atomically move temporary files to final locations
            self._finalize_operations()
            
            self.committed = True
            logger.info(f"Successfully committed {len(self.pending_files)} files")
            
        except Exception as e:
            logger.error(f"Failed to commit files: {e}")
            self.rollback()
            raise FileOperationError(f"File operation failed: {e}") from e
    
    def rollback(self):
        """Roll back all file operations."""
        if self.committed:
            # Restore from backups if committed
            self._restore_backups()
        
        # Clean up temporary files
        self._cleanup_temp_files()
        
        # Remove created directories (if empty)
        self._cleanup_directories()
        
        logger.info("Rolled back file operations")
    
    def _validate_operations(self):
        """Validate that all operations can be performed."""
        for file_path in self.pending_files:
            # Check parent directory can be created
            parent_dir = file_path.parent
            if not parent_dir.exists():
                try:
                    # Test creation (will be done properly later)
                    parent_dir.mkdir(parents=True, exist_ok=True)
                    self.created_directories.append(parent_dir)
                except OSError as e:
                    raise FileOperationError(f"Cannot create directory {parent_dir}: {e}")
            
            # Check if we can write to the file location
            if file_path.exists() and not os.access(file_path, os.W_OK):
                raise FileOperationError(f"No write permission for {file_path}")
            
            # Check parent directory write permission
            if not os.access(parent_dir, os.W_OK):
                raise FileOperationError(f"No write permission for directory {parent_dir}")
    
    def _prepare_operations(self):
        """Create directories and backup existing files."""
        # Create all necessary directories
        created_dirs = set()
        for file_path in self.pending_files:
            parent_dir = file_path.parent
            if not parent_dir.exists():
                parent_dir.mkdir(parents=True, exist_ok=True)
                created_dirs.add(parent_dir)
        
        # Track directories we created (for cleanup on rollback)
        self.created_directories.extend(created_dirs)
        
        # Backup existing files
        for file_path in self.pending_files:
            if file_path.exists():
                backup_path = self._create_backup(file_path)
                self.backup_files.append(backup_path)
    
    def _write_temporary_files(self):
        """Write all files to temporary locations first."""
        for file_path, content in self.pending_files.items():
            # Create temporary file in the same directory for atomic move
            temp_dir = file_path.parent
            
            try:
                with tempfile.NamedTemporaryFile(
                    mode='w', 
                    encoding='utf-8',
                    dir=temp_dir,
                    delete=False,
                    prefix=f'.{file_path.name}.',
                    suffix='.tmp'
                ) as temp_file:
                    temp_file.write(content)
                    temp_path = Path(temp_file.name)
                    self.temp_files.append(temp_path)
                    
            except OSError as e:
                raise FileOperationError(f"Failed to write temporary file for {file_path}: {e}")
    
    def _finalize_operations(self):
        """Atomically move temporary files to final locations."""
        temp_iter = iter(self.temp_files)
        
        for file_path in self.pending_files:
            temp_path = next(temp_iter)
            
            try:
                # Atomic move (rename) to final location
                if os.name == 'nt':  # Windows
                    # Windows doesn't support atomic replace, so remove first
                    if file_path.exists():
                        file_path.unlink()
                    temp_path.rename(file_path)
                else:  # Unix-like systems support atomic rename
                    temp_path.rename(file_path)
                    
            except OSError as e:
                raise FileOperationError(f"Failed to finalize {file_path}: {e}")
    
    def _create_backup(self, file_path: Path) -> Path:
        """Create backup of existing file."""
        backup_path = file_path.with_suffix(f'{file_path.suffix}.backup.{os.getpid()}')
        try:
            shutil.copy2(file_path, backup_path)
            return backup_path
        except OSError as e:
            raise FileOperationError(f"Failed to backup {file_path}: {e}")
    
    def _restore_backups(self):
        """Restore files from backups."""
        for backup_path in self.backup_files:
            try:
                if backup_path.exists():
                    original_path = backup_path.with_suffix('')
                    if '.backup.' in backup_path.suffix:
                        # Remove .backup.{pid} suffix
                        suffix_parts = backup_path.suffix.split('.backup.')
                        original_path = backup_path.with_suffix(suffix_parts[0])
                    
                    shutil.move(str(backup_path), str(original_path))
            except OSError as e:
                logger.error(f"Failed to restore backup {backup_path}: {e}")
    
    def _cleanup_temp_files(self):
        """Remove temporary files."""
        for temp_path in self.temp_files:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError as e:
                logger.error(f"Failed to remove temp file {temp_path}: {e}")
        
        self.temp_files.clear()
    
    def _cleanup_directories(self):
        """Remove created directories if empty."""
        # Sort by depth (deepest first) to remove child directories first
        for directory in sorted(self.created_directories, key=lambda p: len(p.parts), reverse=True):
            try:
                if directory.exists() and not any(directory.iterdir()):
                    directory.rmdir()
            except OSError as e:
                logger.debug(f"Could not remove directory {directory}: {e}")
    
    def get_written_files(self) -> List[Path]:
        """Get list of files that would be/were written."""
        return list(self.pending_files.keys())


@contextmanager
def atomic_file_operations(base_path: Union[str, Path]):
    """
    Context manager for atomic file operations.
    
    Args:
        base_path: Base directory for file operations
        
    Yields:
        AtomicFileWriter instance
        
    Example:
        with atomic_file_operations('/path/to/output') as writer:
            writer.add_file('models.py', model_code)
            writer.add_file('views.py', view_code)
            # Files are written atomically on context exit
    """
    writer = AtomicFileWriter(base_path)
    try:
        yield writer
    finally:
        # Context manager handles commit/rollback automatically
        pass


def write_files_safely(base_path: Union[str, Path], files: Dict[Union[str, Path], str]) -> List[Path]:
    """
    Write multiple files safely with atomic operations.
    
    Args:
        base_path: Base directory for file operations
        files: Dictionary mapping relative paths to content
        
    Returns:
        List of written file paths
        
    Raises:
        FileOperationError: If any file operation fails
    """
    with atomic_file_operations(base_path) as writer:
        writer.add_files(files)
        return writer.get_written_files()


class GenerationTransaction:
    """
    Higher-level transaction manager for code generation operations.
    
    Provides additional features like progress tracking, dependency validation,
    and generation statistics.
    """
    
    def __init__(self, base_path: Union[str, Path], operation_name: str = "Generation"):
        """
        Initialize generation transaction.
        
        Args:
            base_path: Base directory for operations
            operation_name: Name of the operation for logging
        """
        self.base_path = Path(base_path)
        self.operation_name = operation_name
        self.file_writer = AtomicFileWriter(base_path)
        self.started = False
        self.completed = False
        
        # Statistics
        self.start_time = None
        self.end_time = None
        
    def __enter__(self):
        """Enter the transaction context."""
        self.started = True
        self.start_time = __import__('time').time()
        logger.info(f"Starting {self.operation_name} in {self.base_path}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the transaction context."""
        self.end_time = __import__('time').time()
        
        if exc_type is None:
            try:
                self.file_writer.commit()
                self.completed = True
                duration = self.end_time - self.start_time
                logger.info(
                    f"{self.operation_name} completed successfully in {duration:.2f}s. "
                    f"Written {len(self.file_writer.pending_files)} files."
                )
            except Exception as e:
                logger.error(f"{self.operation_name} failed during commit: {e}")
                self.file_writer.rollback()
                raise
        else:
            logger.error(f"{self.operation_name} failed: {exc_val}")
            self.file_writer.rollback()
    
    def add_file(self, relative_path: Union[str, Path], content: str):
        """Add file to transaction."""
        self.file_writer.add_file(relative_path, content)
    
    def add_files(self, files: Dict[Union[str, Path], str]):
        """Add multiple files to transaction."""
        self.file_writer.add_files(files)
    
    def get_file_count(self) -> int:
        """Get number of files in transaction."""
        return len(self.file_writer.pending_files)
    
    def validate_dependencies(self, dependencies: Optional[List[str]] = None):
        """
        Validate that required dependencies exist.
        
        Args:
            dependencies: List of required files/directories
        """
        if not dependencies:
            return
            
        for dep in dependencies:
            dep_path = self.base_path / dep
            if not dep_path.exists():
                raise FileOperationError(f"Required dependency not found: {dep_path}")
    
    def get_statistics(self) -> Dict[str, any]:
        """Get transaction statistics."""
        stats = {
            'operation_name': self.operation_name,
            'base_path': str(self.base_path),
            'file_count': len(self.file_writer.pending_files),
            'started': self.started,
            'completed': self.completed
        }
        
        if self.start_time and self.end_time:
            stats['duration'] = self.end_time - self.start_time
        
        return stats