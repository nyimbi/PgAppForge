"""
Tests for path validation security implementation.

These tests ensure that directory traversal attacks are prevented in file operations
and that the SecurePathValidator integration works correctly.
"""

import pytest
import tempfile
import os
from pathlib import Path

from flask_appbuilder.security.path_validation import (
    SecurePathValidator, SecureFileHandler, PathTraversalError, InvalidPathError,
    validate_safe_path, validate_safe_filename, safe_path_join
)
from flask_appbuilder.cli.generators.file_operations import (
    AtomicFileWriter, atomic_file_operations, write_files_safely, FileOperationError
)


class TestSecurePathValidator:
    """Test the SecurePathValidator class."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.validator = SecurePathValidator([self.temp_dir])

    def test_dangerous_patterns_detection(self):
        """Test detection of dangerous path patterns."""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "/../../etc/shadow",
            "\\..\\..\\boot.ini",
            "dir/../../../etc/hosts",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # URL encoded ../../../etc/passwd
            "\\u002e\\u002e/etc/passwd",  # Unicode encoded
            "\\xff0e\\xff0e/etc/passwd",  # Fullwidth encoded
            "test\x00.txt",  # Null byte injection
            "/con/test.txt",  # Windows reserved
            "/prn/test.txt",  # Windows reserved
            "//server/share/file.txt",  # UNC path
            "test::$DATA",  # NTFS stream
        ]

        for dangerous_path in dangerous_paths:
            with pytest.raises((PathTraversalError, InvalidPathError)):
                self.validator.validate_path(dangerous_path)

    def test_safe_paths_allowed(self):
        """Test that safe paths are allowed."""
        safe_paths = [
            "models.py",
            "views/user_view.py",
            "templates/base.html",
            "static/css/style.css",
            "subdirectory/file.txt",
        ]

        base_path = Path(self.temp_dir).resolve()
        for safe_path in safe_paths:
            # Use safe_join to validate path construction
            result = self.validator.safe_join(base_path, safe_path)
            # Check that the result starts with the base path (string comparison to handle symlinks)
            assert str(result).startswith(str(base_path))

    def test_validate_filename_security(self):
        """Test filename validation for security issues."""
        # Valid filenames
        valid_filenames = ["model.py", "view_test.js", "file_123.txt"]
        for filename in valid_filenames:
            result = self.validator.validate_filename(filename)
            assert result == filename

        # Invalid filenames
        invalid_filenames = [
            "../etc/passwd",
            "file/with/slash.txt",
            "file\\with\\backslash.txt",
            "file\x00.txt",  # Null byte
            "con.txt",  # Windows reserved
            "prn.log",  # Windows reserved
            "file\tcontrol.txt",  # Control character
        ]

        for filename in invalid_filenames:
            with pytest.raises((PathTraversalError, InvalidPathError)):
                self.validator.validate_filename(filename)

    def test_safe_join_prevents_traversal(self):
        """Test that safe_join prevents directory traversal."""
        base_path = Path(self.temp_dir).resolve()

        # Safe joins should work
        safe_result = self.validator.safe_join(base_path, "subdir", "file.txt")
        assert str(safe_result).startswith(str(base_path))

        # Dangerous joins should fail
        dangerous_components = [
            "../../../etc/passwd",
            "..\\..\\system32",
            "/etc/passwd",
        ]

        for component in dangerous_components:
            with pytest.raises((PathTraversalError, InvalidPathError)):
                self.validator.safe_join(base_path, component)

    def test_symlink_protection(self):
        """Test protection against symlink attacks."""
        base_path = Path(self.temp_dir)
        test_file = base_path / "test.txt"
        test_file.touch()

        # Create a symlink pointing outside base directory
        symlink_path = base_path / "evil_link.txt"
        try:
            symlink_path.symlink_to("/etc/passwd")

            # Validation should fail for symlinks by default
            with pytest.raises(PathTraversalError):
                self.validator.validate_path(symlink_path)
        except OSError:
            # Skip test if symlinks not supported (e.g., Windows without admin)
            pytest.skip("Symlinks not supported on this system")


class TestSecureFileHandler:
    """Test the SecureFileHandler class."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.handler = SecureFileHandler(self.temp_dir, allowed_extensions={'.txt', '.py'})

    def test_safe_file_operations(self):
        """Test safe file operations."""
        # Safe file creation
        with self.handler.safe_open("test.txt", "w") as f:
            f.write("test content")

        # Verify file exists and content is correct
        assert self.handler.safe_exists("test.txt")

        with self.handler.safe_open("test.txt", "r") as f:
            content = f.read()
            assert content == "test content"

        # Safe file removal
        assert self.handler.safe_remove("test.txt")
        assert not self.handler.safe_exists("test.txt")

    def test_extension_restrictions(self):
        """Test file extension restrictions."""
        # Allowed extension should work
        with self.handler.safe_open("test.txt", "w") as f:
            f.write("content")

        # Disallowed extension should fail
        with pytest.raises(InvalidPathError):
            self.handler.safe_open("malicious.exe", "w")

    def test_directory_traversal_prevention(self):
        """Test prevention of directory traversal in file operations."""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\system32\\config",
            "/etc/shadow",
        ]

        for path in dangerous_paths:
            assert not self.handler.safe_exists(path)
            assert not self.handler.safe_remove(path)

            with pytest.raises((PathTraversalError, InvalidPathError, FileOperationError)):
                self.handler.safe_open(path, "w")

    def test_list_safe_files(self):
        """Test safe file listing."""
        # Create test files
        test_files = ["file1.txt", "file2.py", "subdir/file3.txt"]
        for file_path in test_files:
            full_path = Path(self.temp_dir) / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.touch()

        # List files safely
        files = self.handler.list_safe_files()
        assert len(files) >= 2  # At least the root level files

        # List subdirectory files
        subdir_files = self.handler.list_safe_files("subdir")
        assert len(subdir_files) == 1


class TestAtomicFileWriterSecurity:
    """Test security integration in AtomicFileWriter."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()

    def test_secure_file_addition(self):
        """Test that AtomicFileWriter validates paths securely."""
        with AtomicFileWriter(self.temp_dir) as writer:
            # Safe path should work
            writer.add_file("safe_file.py", "# Safe content")

        # Verify file was created
        safe_file = Path(self.temp_dir) / "safe_file.py"
        assert safe_file.exists()
        assert safe_file.read_text() == "# Safe content"

    def test_dangerous_path_rejection(self):
        """Test that dangerous paths are rejected."""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\system32\\config",
            "/etc/shadow",
            "test\x00.txt",
            "../outside.txt",
        ]

        with AtomicFileWriter(self.temp_dir) as writer:
            for dangerous_path in dangerous_paths:
                with pytest.raises(FileOperationError) as exc_info:
                    writer.add_file(dangerous_path, "malicious content")
                assert "Insecure path rejected" in str(exc_info.value)

    def test_atomic_operations_with_security(self):
        """Test that atomic operations maintain security."""
        files = {
            "model.py": "class Model: pass",
            "view.py": "class View: pass",
            "subdir/helper.py": "def helper(): return True"
        }

        # Should work with safe paths
        written_files = write_files_safely(self.temp_dir, files)
        assert len(written_files) == 3

        # Verify all files exist
        for rel_path in files.keys():
            full_path = Path(self.temp_dir) / rel_path
            assert full_path.exists()

    def test_atomic_operations_security_failure(self):
        """Test that insecure paths cause atomic operations to fail."""
        files = {
            "safe_file.py": "# Safe content",
            "../../../etc/passwd": "malicious content",
            "another_safe.py": "# More safe content"
        }

        # Should fail due to dangerous path
        with pytest.raises(FileOperationError):
            write_files_safely(self.temp_dir, files)

        # Verify no files were created (atomic failure)
        safe_file = Path(self.temp_dir) / "safe_file.py"
        another_safe = Path(self.temp_dir) / "another_safe.py"
        assert not safe_file.exists()
        assert not another_safe.exists()


class TestConvenienceFunctions:
    """Test convenience functions for path validation."""

    def test_validate_safe_path_function(self):
        """Test the validate_safe_path convenience function."""
        # Should work with safe paths
        safe_path = validate_safe_path("./safe/path/file.txt")
        assert isinstance(safe_path, Path)

        # Should fail with dangerous paths
        with pytest.raises((PathTraversalError, InvalidPathError)):
            validate_safe_path("../../../etc/passwd")

    def test_validate_safe_filename_function(self):
        """Test the validate_safe_filename convenience function."""
        # Safe filename
        safe_name = validate_safe_filename("safe_file.txt")
        assert safe_name == "safe_file.txt"

        # Dangerous filename
        with pytest.raises((PathTraversalError, InvalidPathError)):
            validate_safe_filename("../dangerous.txt")

    def test_safe_path_join_function(self):
        """Test the safe_path_join convenience function."""
        temp_dir = tempfile.mkdtemp()

        # Safe join
        safe_path = safe_path_join(temp_dir, "subdir", "file.txt")
        assert str(safe_path).startswith(str(Path(temp_dir).resolve()))

        # Dangerous join
        with pytest.raises((PathTraversalError, InvalidPathError)):
            safe_path_join(temp_dir, "../../../etc", "passwd")


class TestRegressionTests:
    """Regression tests for previously vulnerable code patterns."""

    def test_cli_generator_security(self):
        """Test that CLI generators are secured against directory traversal."""
        temp_dir = tempfile.mkdtemp()

        # Test patterns that were previously vulnerable
        with AtomicFileWriter(temp_dir) as writer:
            # These should work
            writer.add_file("views/user.py", "class UserView: pass")
            writer.add_file("models/user.py", "class User: pass")

            # These should fail
            dangerous_paths = [
                "../../../root/.ssh/authorized_keys",
                "..\\..\\windows\\system32\\drivers\\etc\\hosts",
                "/etc/passwd",
            ]

            for path in dangerous_paths:
                with pytest.raises(FileOperationError):
                    writer.add_file(path, "malicious")

    def test_workflow_command_security(self):
        """Test that workflow commands validate paths securely."""
        # Test relative path validation (what would be used in CLI)

        # Safe relative paths should validate
        safe_relative_path = validate_safe_path("./workflow.yaml")
        assert isinstance(safe_relative_path, Path)

        # Dangerous paths should be rejected
        with pytest.raises((PathTraversalError, InvalidPathError)):
            validate_safe_path("../../../etc/passwd")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])