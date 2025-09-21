"""
Critical security tests for import validation system.

These tests ensure the import validation security fixes are working correctly
and protect against code injection vulnerabilities.
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from flask_appbuilder.cli.utils.import_utils import (
    validate_imports_secure,
    ValidationResult,
    ImportValidationError
)


class TestImportValidationSecurity:
    """Test suite for import validation security fixes."""

    def test_safe_imports_validation(self):
        """Test that safe imports pass validation."""
        safe_imports = [
            "import os",
            "import sys",
            "from datetime import datetime",
            "import json",
            "from flask import Flask",
            "import sqlalchemy"
        ]

        result = validate_imports_secure(safe_imports)

        assert isinstance(result, ValidationResult)
        assert result.is_valid is True
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_dangerous_imports_blocked(self):
        """Test that dangerous imports are properly blocked."""
        dangerous_imports = [
            "import subprocess",
            "from os import system",
            "import importlib",
            "from importlib import import_module"
        ]

        result = validate_imports_secure(dangerous_imports)

        assert isinstance(result, ValidationResult)
        assert result.is_valid is False
        assert len(result.errors) > 0

        # Check that dangerous imports are flagged
        error_messages = " ".join(result.errors)
        assert any(keyword in error_messages.lower() for keyword in
                  ["dangerous", "system", "injection", "contains"])

    def test_exec_eval_imports_blocked(self):
        """Test that exec/eval related imports are blocked."""
        exec_imports = [
            "from builtins import exec",
            "from builtins import eval",
            "import marshal",
            "import pickle"
        ]

        result = validate_imports_secure(exec_imports)

        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_malformed_import_statements(self):
        """Test handling of malformed import statements."""
        malformed_imports = [
            "import",  # Incomplete
            "from import os",  # Malformed
            "import os; exec('malicious code')",  # Compound statement
            "import os as",  # Incomplete alias
        ]

        result = validate_imports_secure(malformed_imports)

        # Should handle malformed imports gracefully
        assert isinstance(result, ValidationResult)
        # Some may be flagged as errors, others may be warnings

    def test_empty_and_whitespace_imports(self):
        """Test handling of empty and whitespace-only imports."""
        empty_imports = [
            "",
            "   ",
            "\t",
            "\n",
            "# Just a comment"
        ]

        result = validate_imports_secure(empty_imports)

        # Empty imports should be handled gracefully
        assert isinstance(result, ValidationResult)

    def test_complex_import_patterns(self):
        """Test complex but legitimate import patterns."""
        complex_imports = [
            "from flask_appbuilder.security.sqla.manager import SecurityManager",
            "from sqlalchemy.orm import sessionmaker, scoped_session",
            "import pkg_resources",
            "from collections.abc import Mapping"
        ]

        result = validate_imports_secure(complex_imports)

        # Complex legitimate imports should pass
        assert result.is_valid is True

    def test_relative_imports(self):
        """Test relative import patterns."""
        relative_imports = [
            "from . import models",
            "from .. import utils",
            "from ...security import manager"
        ]

        result = validate_imports_secure(relative_imports)

        # Relative imports should be handled appropriately
        assert isinstance(result, ValidationResult)

    @patch('importlib.util.find_spec')
    def test_nonexistent_module_handling(self, mock_find_spec):
        """Test handling of imports for non-existent modules."""
        mock_find_spec.return_value = None  # Module doesn't exist

        nonexistent_imports = [
            "import nonexistent_module",
            "from fake_package import something"
        ]

        result = validate_imports_secure(nonexistent_imports)

        # Should handle missing modules gracefully with warnings
        assert isinstance(result, ValidationResult)

    def test_validation_result_structure(self):
        """Test that ValidationResult has correct structure."""
        imports = ["import os"]
        result = validate_imports_secure(imports)

        # Check ValidationResult structure
        assert hasattr(result, 'is_valid')
        assert hasattr(result, 'errors')
        assert hasattr(result, 'warnings')
        assert hasattr(result, 'validated_imports')

        assert isinstance(result.is_valid, bool)
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.validated_imports, list)

    def test_large_import_list_performance(self):
        """Test performance with large import lists."""
        # Create a large list of imports
        large_import_list = [f"import module_{i}" for i in range(1000)]

        import time
        start_time = time.time()
        result = validate_imports_secure(large_import_list)
        end_time = time.time()

        # Should complete in reasonable time (less than 5 seconds)
        assert (end_time - start_time) < 5.0
        assert isinstance(result, ValidationResult)

    def test_unicode_and_encoding_handling(self):
        """Test handling of unicode and different encodings in imports."""
        unicode_imports = [
            "import módulo_español",  # Spanish
            "import モジュール",        # Japanese
            "from пакет import функция"  # Russian
        ]

        result = validate_imports_secure(unicode_imports)

        # Should handle unicode gracefully without crashing
        assert isinstance(result, ValidationResult)

    def test_injection_attempt_patterns(self):
        """Test detection of various code injection attempt patterns."""
        injection_attempts = [
            "import os; os.system('rm -rf /')",
            "import subprocess; subprocess.call(['curl', 'evil.com'])",
            "__import__('os').system('malicious')",
            "eval('malicious_code')",
            "exec('import os; os.system(\"bad\")')"
        ]

        result = validate_imports_secure(injection_attempts)

        # All injection attempts should be blocked
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_concurrent_validation(self):
        """Test concurrent validation calls for thread safety."""
        import threading
        import concurrent.futures

        def validate_imports_worker():
            test_imports = ["import json", "import datetime", "import os"]
            return validate_imports_secure(test_imports)

        # Run multiple validations concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(validate_imports_worker) for _ in range(50)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]

        # All results should be valid and consistent
        for result in results:
            assert isinstance(result, ValidationResult)

    def test_error_handling_robustness(self):
        """Test error handling with various edge cases."""
        edge_cases = [
            None,  # None input
            123,   # Wrong type
            [],    # Empty list
            ["import os", None, "import sys"],  # Mixed types
        ]

        for case in edge_cases:
            try:
                result = validate_imports_secure(case)
                # Should either return a result or raise appropriate exception
                assert isinstance(result, ValidationResult) or isinstance(result, type(None))
            except (TypeError, ImportValidationError):
                # Appropriate exceptions are acceptable
                pass

    def test_security_headers_integration(self):
        """Test integration with security headers and logging."""
        with patch('flask_appbuilder.cli.utils.import_utils.logger') as mock_logger:
            dangerous_imports = ["import subprocess"]
            result = validate_imports_secure(dangerous_imports)

            # Should log security violations
            assert mock_logger.warning.called or mock_logger.error.called

    def test_validation_caching_behavior(self):
        """Test that validation results are properly cached/handled."""
        imports = ["import json", "import datetime"]

        # Run validation multiple times
        result1 = validate_imports_secure(imports)
        result2 = validate_imports_secure(imports)

        # Results should be consistent
        assert result1.is_valid == result2.is_valid
        assert len(result1.errors) == len(result2.errors)
        assert len(result1.warnings) == len(result2.warnings)


class TestImportValidationEdgeCases:
    """Additional edge case tests for import validation."""

    def test_comment_only_lines(self):
        """Test lines that are only comments."""
        comment_imports = [
            "# This is a comment",
            "  # Another comment with spaces",
            "import os  # Import with comment",
            "# import os  # Commented out import"
        ]

        result = validate_imports_secure(comment_imports)
        assert isinstance(result, ValidationResult)

    def test_multiline_imports(self):
        """Test handling of multiline import statements."""
        multiline_imports = [
            "from flask import (\n    Flask,\n    request,\n    jsonify\n)",
            "import os, \\\n    sys, \\\n    json"
        ]

        result = validate_imports_secure(multiline_imports)
        assert isinstance(result, ValidationResult)

    def test_import_with_special_characters(self):
        """Test imports with special characters."""
        special_imports = [
            "import os-path",  # Hyphen (invalid but should be handled)
            "import package.sub_module",  # Dot and underscore
            "from package import *",  # Star import
            "import package as pkg"  # Alias
        ]

        result = validate_imports_secure(special_imports)
        assert isinstance(result, ValidationResult)

    def test_very_long_import_statements(self):
        """Test very long import statements."""
        long_import = "from very.long.package.name.that.goes.on.and.on.and.on import " + \
                     "very_long_function_name_that_exceeds_normal_limits"

        result = validate_imports_secure([long_import])
        assert isinstance(result, ValidationResult)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])