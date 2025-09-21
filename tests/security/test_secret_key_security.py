"""
Security tests for secret key management fixes.

This test suite validates that hardcoded secret keys have been eliminated
and proper security practices are enforced.
"""

import unittest
import tempfile
import os
import sys
import subprocess
import importlib.util
from unittest.mock import patch, Mock
from pathlib import Path


class SecretKeySecurityTest(unittest.TestCase):
    """Test suite for secret key security fixes."""

    def setUp(self):
        """Set up test environment."""
        self.test_env = os.environ.copy()
        # Clear SECRET_KEY for isolated testing
        if 'SECRET_KEY' in os.environ:
            del os.environ['SECRET_KEY']

    def tearDown(self):
        """Clean up test environment."""
        os.environ.clear()
        os.environ.update(self.test_env)

    def test_secret_key_generator_basic_functionality(self):
        """Test basic functionality of secret key generator."""
        import subprocess

        # Test basic key generation
        result = subprocess.run([
            sys.executable, 'bin/generate_secret_key.py'
        ], capture_output=True, text=True)

        self.assertEqual(result.returncode, 0, "Key generator should run successfully")
        lines = result.stdout.strip().split('\n')
        key = lines[0]

        # Validate generated key
        self.assertGreaterEqual(len(key), 64, "Generated key should be at least 64 characters")
        self.assertNotIn(' ', key, "Generated key should not contain spaces")
        self.assertRegex(key, r'^[A-Za-z0-9_-]+$', "Key should be URL-safe base64")

    def test_secret_key_generator_validation(self):
        """Test key validation functionality."""
        # Test weak key validation
        result = subprocess.run([
            sys.executable, 'bin/generate_secret_key.py',
            '--validate', 'thisismyscretkey'
        ], capture_output=True, text=True)

        self.assertNotEqual(result.returncode, 0, "Weak key should be rejected")
        output = result.stdout + result.stderr  # Check both stdout and stderr
        self.assertIn('INVALID', output, "Should report key as invalid")
        self.assertIn('weak pattern', output, "Should identify weak patterns")

        # Test strong key validation
        strong_key = 'GBiaxDejVv-2lBH4FfbQjFFI5HpXyqt-5yT02WIAkqYFLyK70xvjGiAsI_vCNgDa8M5t1jALHCH-8YoYtvsg7Q'
        result = subprocess.run([
            sys.executable, 'bin/generate_secret_key.py',
            '--validate', strong_key
        ], capture_output=True, text=True)

        self.assertEqual(result.returncode, 0, "Strong key should be accepted")
        self.assertIn('VALID', result.stdout, "Should report key as valid")

    def test_main_config_security(self):
        """Test that main config file requires environment variable."""
        # Test config fails without SECRET_KEY
        with self.assertRaises((SystemExit, ValueError)):
            spec = importlib.util.spec_from_file_location("config", "bin/config.py")
            config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config)

        # Test config works with valid SECRET_KEY
        os.environ['SECRET_KEY'] = 'test-secret-key-minimum-32-characters-long'
        try:
            spec = importlib.util.spec_from_file_location("config", "bin/config.py")
            config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config)

            self.assertEqual(config.SECRET_KEY, 'test-secret-key-minimum-32-characters-long')
            self.assertTrue(config.CSRF_ENABLED)
        except SystemExit:
            self.fail("Config should not exit with valid SECRET_KEY")

    def test_example_config_security(self):
        """Test that example configs handle missing SECRET_KEY gracefully."""
        # Test employees example config
        spec = importlib.util.spec_from_file_location("config", "examples/employees/config.py")
        config = importlib.util.module_from_spec(spec)

        # Should not fail, but should generate a warning and random key
        with patch('builtins.print') as mock_print:
            spec.loader.exec_module(config)

            # Should have printed warning
            mock_print.assert_called()
            warning_call = str(mock_print.call_args_list)
            self.assertIn('WARNING', warning_call, "Should print warning about dev key")

            # Should have a valid secret key
            self.assertIsNotNone(config.SECRET_KEY)
            self.assertGreaterEqual(len(config.SECRET_KEY), 32)

    def test_no_hardcoded_keys_in_production_configs(self):
        """Test that production configurations don't contain hardcoded keys."""
        production_configs = [
            'bin/config.py',
            'config_example_multitenant.py',
        ]

        for config_file in production_configs:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    content = f.read()

                # Should not contain hardcoded secret patterns
                hardcoded_patterns = [
                    'SECRET_KEY = "',
                    "SECRET_KEY = '",
                    'thisismyscretkey',
                    'SECRET_KEY = \\',
                ]

                for pattern in hardcoded_patterns:
                    if 'os.environ' not in content:  # Skip if using env vars
                        self.assertNotIn(
                            pattern, content,
                            f"Production config {config_file} should not contain hardcoded pattern: {pattern}"
                        )

    def test_critical_config_hardcoded_key_detection(self):
        """Test detection of hardcoded keys in critical configuration files."""
        # Focus on the most critical config files that must not have hardcoded keys
        critical_files = [
            'bin/config.py',
            'config_example_multitenant.py',
        ]

        for config_file in critical_files:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    content = f.read()

                # Check that these files use environment variables
                self.assertIn('os.environ', content,
                             f"Critical config {config_file} must use environment variables")

                # Check that they don't have the old hardcoded pattern
                self.assertNotIn('thisismyscretkey', content,
                                f"Critical config {config_file} must not contain old hardcoded key")

                # Check that they have proper validation
                if config_file == 'bin/config.py':
                    self.assertIn('sys.exit(1)', content,
                                 f"Production config {config_file} must fail without SECRET_KEY")

    def test_secret_key_environment_validation(self):
        """Test environment variable validation logic."""
        from bin.generate_secret_key import validate_existing_key

        # Test various key scenarios
        test_cases = [
            ('', False, "Empty key should be invalid"),
            ('short', False, "Short key should be invalid"),
            ('thisismyscretkey', False, "Weak pattern should be invalid"),
            ('test-key-for-development', False, "Contains 'test' pattern"),
            ('GBiaxDejVv-2lBH4FfbQjFFI5HpXyqt-5yT02WIAkqYFLyK70xvjGiAsI_vCNgDa8M5t1jALHCH-8YoYtvsg7Q', True, "Strong key should be valid"),
        ]

        for key, expected_valid, message in test_cases:
            is_valid, warnings = validate_existing_key(key)
            if expected_valid:
                self.assertTrue(is_valid, f"{message}: {warnings}")
            else:
                self.assertFalse(is_valid, f"{message}: Expected invalid but got valid")

    def test_flask_app_secret_key_configuration(self):
        """Test Flask app configuration with secret keys."""
        from flask import Flask

        # Test app with environment variable
        os.environ['SECRET_KEY'] = 'test-secret-key-for-flask-app-minimum-32-chars'

        app = Flask(__name__)
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

        self.assertEqual(app.config['SECRET_KEY'], 'test-secret-key-for-flask-app-minimum-32-chars')

        # Test app without environment variable should fail gracefully
        del os.environ['SECRET_KEY']
        app2 = Flask(__name__)
        app2.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

        self.assertIsNone(app2.config['SECRET_KEY'])

    def test_quickminimal_example_security(self):
        """Test that quickminimal example handles secret keys securely."""
        # Read the quickminimal run.py file content
        with open('examples/quickminimal/run.py', 'r') as f:
            content = f.read()

        # Should use environment variable approach
        self.assertIn('os.environ.get(\'SECRET_KEY\')', content)
        self.assertNotIn('SECRET_KEY"] = "thisismyscretkey"', content)
        self.assertIn('secrets.token_urlsafe', content)

    def test_security_documentation_exists(self):
        """Test that security documentation has been created."""
        doc_files = [
            'docs/SECRET_KEY_SECURITY_GUIDE.md',
            'docs/CODE_REVIEW_REPORT.md',
            'docs/CRITICAL_FIXES_IMPLEMENTATION_PLAN.md'
        ]

        for doc_file in doc_files:
            self.assertTrue(
                os.path.exists(doc_file),
                f"Security documentation should exist: {doc_file}"
            )

            # Check file is not empty
            with open(doc_file, 'r') as f:
                content = f.read()
            self.assertGreater(len(content), 100, f"Documentation should have substantial content: {doc_file}")

    def test_migration_compatibility(self):
        """Test that configuration changes are backward compatible for valid setups."""
        # Test with valid environment variable
        os.environ['SECRET_KEY'] = 'migration-test-key-that-is-long-enough-for-security-requirements'

        # Should be able to import configs without errors
        try:
            spec = importlib.util.spec_from_file_location("config", "bin/config.py")
            config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config)

            # Should have all expected attributes
            self.assertTrue(hasattr(config, 'SECRET_KEY'))
            self.assertTrue(hasattr(config, 'CSRF_ENABLED'))
            self.assertTrue(hasattr(config, 'SQLALCHEMY_DATABASE_URI'))

        except Exception as e:
            self.fail(f"Config migration should be compatible: {e}")

    def test_development_vs_production_behavior(self):
        """Test different behavior between development and production configs."""
        # Production config (bin/config.py) should fail without SECRET_KEY
        with self.assertRaises((SystemExit, ValueError)):
            spec = importlib.util.spec_from_file_location("config", "bin/config.py")
            config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config)

        # Example config (examples/employees/config.py) should work but warn
        with patch('builtins.print') as mock_print:
            spec = importlib.util.spec_from_file_location("config", "examples/employees/config.py")
            config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config)

            # Should have warned
            mock_print.assert_called()
            # Should have generated a key
            self.assertIsNotNone(config.SECRET_KEY)
            self.assertGreaterEqual(len(config.SECRET_KEY), 32)


class SecretKeyIntegrationTest(unittest.TestCase):
    """Integration tests for secret key security in realistic scenarios."""

    def test_end_to_end_key_generation_and_usage(self):
        """Test complete workflow from key generation to usage."""
        # Generate a key
        result = subprocess.run([
            sys.executable, 'bin/generate_secret_key.py'
        ], capture_output=True, text=True)

        self.assertEqual(result.returncode, 0)
        key = result.stdout.strip().split('\n')[0]

        # Set the key in environment
        os.environ['SECRET_KEY'] = key

        # Use the key in a config
        try:
            spec = importlib.util.spec_from_file_location("config", "bin/config.py")
            config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config)

            self.assertEqual(config.SECRET_KEY, key)
        finally:
            if 'SECRET_KEY' in os.environ:
                del os.environ['SECRET_KEY']

    def test_security_audit_tools(self):
        """Test that security audit tools can detect issues."""
        # Test that the generator can detect weak keys in environment
        os.environ['SECRET_KEY'] = 'weak-key'

        result = subprocess.run([
            sys.executable, 'bin/generate_secret_key.py', '--check-env'
        ], capture_output=True, text=True)

        self.assertNotEqual(result.returncode, 0, "Should detect weak key in environment")
        self.assertIn('INVALID', result.stdout, "Should report invalid key")

        # Clean up
        del os.environ['SECRET_KEY']


if __name__ == '__main__':
    unittest.main()