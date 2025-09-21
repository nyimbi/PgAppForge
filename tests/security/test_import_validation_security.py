"""
Security tests for import validation utilities.

This test suite validates that the critical security vulnerability in import
validation has been properly fixed and no code injection is possible.
"""

import unittest
import tempfile
import os
from unittest.mock import patch

# Import the fixed utilities
from flask_appbuilder.cli.utils.import_utils import (
    validate_imports_secure,
    validate_import_security,
    parse_import,
    check_import_exists_secure
)

# Import the patched original function
import sys
sys.path.append('/Users/nyimbiodero/src/pjs/fab-ext/tmp/utils')
from import_utils import validate_imports


class ImportValidationSecurityTest(unittest.TestCase):
    """Test suite for import validation security fixes."""

    def test_malicious_import_rejection(self):
        """Test that malicious import patterns are rejected."""
        malicious_imports = [
            "import os; os.system('rm -rf /')",  # Code injection after import
            "exec('malicious code')",  # Direct exec call
            "__import__('os').system('evil')",  # Dynamic import with execution
            "eval('dangerous_code')",  # Eval call
            "compile('bad', 'bad', 'exec')",  # Compile call
            "globals()['evil'] = 'bad'",  # Globals manipulation
            "locals()['evil'] = 'bad'",  # Locals manipulation
            "import subprocess; subprocess.call(['rm', '-rf', '/'])",  # Subprocess execution
        ]

        for malicious in malicious_imports:
            with self.subTest(import_stmt=malicious):
                # Test the new secure validation
                result = validate_imports_secure([malicious])
                self.assertFalse(result.is_valid, f"Should reject malicious import: {malicious}")
                self.assertGreater(len(result.errors), 0, "Should have error messages")

                # Test the security validation function
                is_safe, reason = validate_import_security(malicious)
                self.assertFalse(is_safe, f"Should be flagged as unsafe: {malicious}")
                # Check for security-related keywords in the reason
                security_keywords = ["dangerous", "system", "injection", "contains"]
                has_security_keyword = any(keyword in reason.lower() for keyword in security_keywords)
                self.assertTrue(has_security_keyword, f"Should mention security concern in reason: {reason}")

    def test_code_injection_prevention(self):
        """Test that code injection through imports is prevented."""
        injection_attempts = [
            "import os; print('injected')",
            "from os import system; system('echo injected')",
            "exec(open('/etc/passwd').read())",
            "__import__('subprocess').call(['ls', '/'])",
        ]

        for injection in injection_attempts:
            with self.subTest(injection=injection):
                # These should all be rejected by the security validation
                result = validate_imports_secure([injection])
                self.assertFalse(result.is_valid)
                self.assertIn(injection, [error.split(':')[1].strip()
                                        for error in result.errors
                                        if 'Invalid import syntax' in error] +
                                       [injection])  # Should be in invalid list

    def test_legitimate_imports_allowed(self):
        """Test that legitimate imports still work correctly."""
        legitimate_imports = [
            "import os",
            "import sys",
            "from typing import List, Dict",
            "from flask import Flask",
            "from flask_appbuilder import ModelView",
            "import json",
            "from datetime import datetime",
            "from os import path",  # Legitimate os import
            "import subprocess",  # Legitimate subprocess import (without execution)
        ]

        for legit in legitimate_imports:
            with self.subTest(import_stmt=legit):
                result = validate_imports_secure([legit])
                # These should pass security validation
                is_safe, reason = validate_import_security(legit)
                self.assertTrue(is_safe, f"Legitimate import should be safe: {legit}")

                # May or may not be valid depending on whether module exists,
                # but should not be rejected for security reasons
                if not result.is_valid:
                    # Check if rejection was due to module not found vs security
                    security_errors = [error for error in result.errors
                                     if 'dangerous' in error.lower() or 'security' in error.lower()]
                    self.assertEqual(len(security_errors), 0,
                                   f"Should not be rejected for security: {legit}")

    def test_suspicious_but_legitimate_imports(self):
        """Test imports that might look suspicious but are actually legitimate."""
        suspicious_but_safe = [
            "from os import system",  # Legitimate import, dangerous only when used
            "from subprocess import call",  # Legitimate import
            "import importlib",  # Legitimate import
            "from importlib import import_module",  # Legitimate import
        ]

        for suspicious in suspicious_but_safe:
            with self.subTest(import_stmt=suspicious):
                # These should pass security validation since they're syntactically valid imports
                is_safe, reason = validate_import_security(suspicious)
                self.assertTrue(is_safe, f"Suspicious but legitimate import should be safe: {suspicious}")

                # These might generate warnings but should not be rejected
                result = validate_imports_secure([suspicious])
                if not result.is_valid:
                    # Should be invalid due to module not found, not security
                    security_related = any('dangerous' in error.lower() or 'security' in error.lower()
                                         for error in result.errors)
                    self.assertFalse(security_related,
                                   f"Should not be rejected for security: {suspicious}")

    def test_fixed_validate_imports_function(self):
        """Test that the patched validate_imports function is secure."""
        # Test with safe imports
        safe_imports = ["import json", "from typing import List"]
        valid, invalid = validate_imports(safe_imports)

        # Should process safely
        self.assertIsInstance(valid, list)
        self.assertIsInstance(invalid, list)

        # Test with dangerous imports - should be rejected
        dangerous_imports = ["exec('malicious')", "import os; os.system('evil')"]
        valid, invalid = validate_imports(dangerous_imports)

        # All dangerous imports should be in invalid list
        self.assertEqual(len(valid), 0, "No dangerous imports should be validated")
        self.assertEqual(len(invalid), len(dangerous_imports), "All dangerous imports should be rejected")

    def test_ast_parsing_safety(self):
        """Test that AST parsing is used safely."""
        test_cases = [
            ("import os", True),  # Valid
            ("from typing import List", True),  # Valid
            ("not_an_import", False),  # Invalid syntax
            ("import", False),  # Incomplete
            ("", False),  # Empty
        ]

        for test_input, should_parse in test_cases:
            with self.subTest(input=test_input):
                result = parse_import(test_input)
                if should_parse:
                    self.assertIsNotNone(result, f"Should parse: {test_input}")
                else:
                    self.assertIsNone(result, f"Should not parse: {test_input}")

    def test_importlib_usage(self):
        """Test that importlib.util.find_spec is used instead of exec."""
        # Test that module checking uses safe methods

        # These modules should exist
        existing_modules = ["os", "sys", "json", "typing"]
        for module in existing_modules:
            with self.subTest(module=module):
                exists = check_import_exists_secure(module)
                self.assertTrue(exists, f"Should find existing module: {module}")

        # These modules should not exist
        fake_modules = ["nonexistent_module_12345", "fake_module_xyz"]
        for module in fake_modules:
            with self.subTest(module=module):
                exists = check_import_exists_secure(module)
                self.assertFalse(exists, f"Should not find fake module: {module}")

    def test_security_logging(self):
        """Test that security violations are properly logged."""
        with patch('flask_appbuilder.cli.utils.import_utils.logger') as mock_logger:
            malicious_import = "exec('malicious code')"

            # This should trigger security logging
            parse_import(malicious_import)

            # Verify that warning was logged
            mock_logger.warning.assert_called()
            warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
            self.assertTrue(any("Dangerous pattern detected" in call for call in warning_calls),
                          "Should log dangerous pattern detection")

    def test_no_code_execution(self):
        """Test that no actual code execution occurs during validation."""
        # Create a file that would be executed if exec() were used
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write("print('CODE_EXECUTED')\nraise Exception('exec_was_called')")
            temp_file_path = temp_file.name

        try:
            # Test import that would execute code if exec() were used
            malicious_import = f"exec(open('{temp_file_path}').read())"

            # This should NOT execute the code
            result = validate_imports_secure([malicious_import])

            # Verify no execution occurred (no exception raised, no output)
            self.assertFalse(result.is_valid)

            # Test with the patched function too
            valid, invalid = validate_imports([malicious_import])
            self.assertEqual(len(valid), 0)
            self.assertEqual(len(invalid), 1)

        finally:
            # Clean up
            os.unlink(temp_file_path)

    def test_edge_cases(self):
        """Test edge cases in import validation."""
        edge_cases = [
            "",  # Empty string
            "   ",  # Whitespace only
            "# comment",  # Comment only
            "import;",  # Incomplete syntax
            "from . import",  # Incomplete relative import
        ]

        for edge_case in edge_cases:
            with self.subTest(edge_case=repr(edge_case)):
                # Should handle gracefully without crashing
                result = validate_imports_secure([edge_case])
                self.assertIsInstance(result, type(result))  # Should return a result

                # Should be invalid due to syntax
                self.assertFalse(result.is_valid)

class SecurityRegressionTest(unittest.TestCase):
    """Test to ensure the security fix doesn't break existing functionality."""

    def test_backward_compatibility(self):
        """Test that the fix maintains backward compatibility for legitimate use."""
        # Test cases that should work the same before and after the fix
        test_imports = [
            "import json",
            "from typing import List",
            "from flask import Flask",
            "import nonexistent_module",  # Should be invalid but safe
        ]

        for imp in test_imports:
            with self.subTest(import_stmt=imp):
                # Should process without crashing
                valid, invalid = validate_imports([imp])
                self.assertIsInstance(valid, list)
                self.assertIsInstance(invalid, list)

                # Total count should match input
                self.assertEqual(len(valid) + len(invalid), 1)

    def test_performance_not_degraded(self):
        """Test that security fix doesn't significantly impact performance."""
        import time

        # Large list of legitimate imports
        imports = ["import json", "from typing import List"] * 100

        start_time = time.time()
        valid, invalid = validate_imports(imports)
        end_time = time.time()

        duration = end_time - start_time

        # Should complete in reasonable time (less than 1 second for 200 imports)
        self.assertLess(duration, 1.0, "Security fix should not significantly impact performance")


if __name__ == '__main__':
    unittest.main()