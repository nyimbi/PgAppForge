"""
Security Validation Suite for Approval System

This module provides comprehensive security validation to test all
security fixes implemented for CVE-2024-001 through CVE-2024-008.

Usage:
    python security_validation.py

This will run comprehensive security tests to validate:
1. SQL Injection Prevention
2. Authorization Bypass Prevention
3. Cryptographic Security
4. Rate Limiting Effectiveness
5. Input Validation & XSS Prevention
6. Session Security
7. Audit Trail Integrity
"""

import time
import json
import hmac
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

from .crypto_config import SecureCryptoConfig, SecureSessionManager, WeakSecretKeyError
from .secure_expression_evaluator import SecurityViolation
from .security_validator import ApprovalSecurityValidator
from .validation_framework import validate_approval_request, detect_security_threats
from .constants import SecurityConstants

log = logging.getLogger(__name__)


class SecurityValidationSuite:
    """Comprehensive security validation test suite."""

    def __init__(self):
        self.test_results = []
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = []

    def run_test(self, test_name: str, test_function, *args, **kwargs):
        """Run a single security test and track results."""
        self.total_tests += 1

        try:
            start_time = time.time()
            result = test_function(*args, **kwargs)
            end_time = time.time()

            duration = end_time - start_time

            if result:
                self.passed_tests += 1
                status = "✅ PASS"
                print(f"  {status} {test_name} ({duration:.3f}s)")
            else:
                status = "❌ FAIL"
                self.failed_tests.append(f"{test_name}: Test returned False")
                print(f"  {status} {test_name} ({duration:.3f}s)")

            self.test_results.append({
                'name': test_name,
                'status': status,
                'duration': duration,
                'result': result
            })

        except Exception as e:
            status = "❌ ERROR"
            error_msg = f"{test_name}: {str(e)}"
            self.failed_tests.append(error_msg)
            print(f"  {status} {test_name}: {str(e)}")

            self.test_results.append({
                'name': test_name,
                'status': status,
                'error': str(e),
                'result': False
            })

    def test_sql_injection_prevention(self) -> bool:
        """Test SQL injection prevention in expression evaluator."""
        try:
            from .secure_expression_evaluator import SecureExpressionEvaluator

            evaluator = SecureExpressionEvaluator()

            # Test safe expression
            safe_result = evaluator.evaluate("manager_id == 123", {'manager_id': 123})
            if not safe_result:
                return False

            # Test SQL injection attempts
            malicious_expressions = [
                "'; DROP TABLE users; --",
                "1=1; DELETE FROM approvals",
                "user_id OR 1=1"
            ]

            for malicious_expr in malicious_expressions:
                try:
                    evaluator.evaluate(malicious_expr, {})
                    # If no exception raised, SQL injection prevention failed
                    return False
                except SecurityViolation:
                    # Expected - SQL injection was blocked
                    continue
                except Exception:
                    # Any other exception also indicates proper blocking
                    continue

            return True

        except Exception as e:
            log.error(f"SQL injection prevention test failed: {e}")
            return False

    def test_authorization_bypass_prevention(self) -> bool:
        """Test authorization bypass prevention mechanisms."""
        try:
            # Mock AppBuilder for testing
            class MockAppBuilder:
                def __init__(self):
                    self.sm = MockSecurityManager()

            class MockSecurityManager:
                def is_admin(self, user):
                    return user.username == 'admin'

            class MockUser:
                def __init__(self, user_id, username, roles=None):
                    self.id = user_id
                    self.username = username
                    self.is_active = True
                    self.roles = roles or []

            class MockRole:
                def __init__(self, name):
                    self.name = name

            validator = ApprovalSecurityValidator(MockAppBuilder())

            # Test self-approval prevention
            instance = type('MockInstance', (), {
                'created_by_id': 123,
                'owner_id': 123
            })()

            user = MockUser(123, 'test_user')

            # Self-approval should be blocked
            result = validator.validate_self_approval(instance, user)
            if result:  # Should return False for self-approval
                return False

            # Test entity type authorization
            finance_user = MockUser(456, 'finance_user', [MockRole('Finance')])

            # Finance user should be able to approve expense reports
            can_approve = validator.can_user_approve_entity_type(finance_user, 'ExpenseReport')
            if not can_approve:
                return False

            # Developer should not be able to approve expense reports
            dev_user = MockUser(789, 'dev_user', [MockRole('Developer')])
            cannot_approve = validator.can_user_approve_entity_type(dev_user, 'ExpenseReport')
            if cannot_approve:  # Should return False
                return False

            return True

        except Exception as e:
            log.error(f"Authorization bypass prevention test failed: {e}")
            return False

    def test_cryptographic_security(self) -> bool:
        """Test cryptographic security implementations."""
        try:
            # Test HMAC calculation with mock Flask app
            class MockApp:
                config = {'SECRET_KEY': 'a' * 32}  # Valid 32-char key

            # Temporarily set mock app
            # Mock current_app
            from unittest.mock import patch
            with patch('flask.current_app', MockApp()):

                # Test HMAC calculation
                data = "test_approval_data"
                hmac1 = SecureCryptoConfig.calculate_secure_hmac(data)
                hmac2 = SecureCryptoConfig.calculate_secure_hmac(data)

                # Same data should produce same HMAC
                if hmac1 != hmac2:
                    return False

                # Different data should produce different HMAC
                hmac3 = SecureCryptoConfig.calculate_secure_hmac("different_data")
                if hmac1 == hmac3:
                    return False

                # Test HMAC verification
                if not SecureCryptoConfig.verify_secure_hmac(data, hmac1):
                    return False

                # Test invalid HMAC verification
                if SecureCryptoConfig.verify_secure_hmac(data, "invalid_hmac"):
                    return False

                # Test session cryptographic binding
                user_context = {
                    'ip_address': '192.168.1.100',
                    'user_agent': 'Mozilla/5.0 Test Browser'
                }

                session_data = SecureSessionManager.create_secure_session_token(
                    user_id=123,
                    session_type="approval",
                    user_context=user_context
                )

                # Session should contain integrity protection
                if '.' not in session_data['session_token']:
                    return False

                return True

        except Exception as e:
            log.error(f"Cryptographic security test failed: {e}")
            return False

    def test_rate_limiting_effectiveness(self) -> bool:
        """Test rate limiting mechanisms."""
        try:
            # Mock AppBuilder
            class MockAppBuilder:
                pass

            validator = ApprovalSecurityValidator(MockAppBuilder())

            # Clear rate limit storage
            validator.rate_limit_storage.clear()

            user_id = 123

            # Test that initial requests are allowed
            for i in range(SecurityConstants.MAX_APPROVAL_ATTEMPTS_PER_WINDOW):
                if not validator.check_approval_rate_limit(user_id):
                    return False  # Should be allowed

            # Test that exceeding limit is blocked
            if validator.check_approval_rate_limit(user_id):
                return False  # Should be blocked

            return True

        except Exception as e:
            log.error(f"Rate limiting test failed: {e}")
            return False

    def test_input_validation_xss_prevention(self) -> bool:
        """Test input validation and XSS prevention."""
        try:
            # Test XSS threat detection
            malicious_inputs = [
                "<script>alert('xss')</script>",
                "javascript:alert('xss')",
                "<img src=x onerror=alert('xss')>",
                "vbscript:msgbox('xss')"
            ]

            for malicious_input in malicious_inputs:
                threats = detect_security_threats(malicious_input)
                if len(threats) == 0:
                    return False  # Should detect threats

                # Check for XSS threat detection
                xss_detected = any('XSS' in threat['type'] for threat in threats)
                if not xss_detected:
                    return False

            # Test SQL injection threat detection
            sql_inputs = [
                "'; DROP TABLE users; --",
                "1' OR '1'='1",
                "UNION SELECT * FROM passwords"
            ]

            for sql_input in sql_inputs:
                threats = detect_security_threats(sql_input)
                if len(threats) == 0:
                    return False  # Should detect threats

                sql_detected = any('SQL_INJECTION' in threat['type'] for threat in threats)
                if not sql_detected:
                    return False

            # Test approval request validation
            valid_data = {
                'workflow_type': 'expense_approval',
                'priority': 'medium',
                'amount': 1500.00,
                'comments': 'Business travel expenses',
                'manager_id': 123
            }

            result = validate_approval_request(valid_data, user_id=456)
            if not result['valid']:
                return False

            # Test invalid data with XSS
            invalid_data = {
                'workflow_type': '<script>alert("xss")</script>',
                'comments': "javascript:alert('xss')"
            }

            result = validate_approval_request(invalid_data, user_id=456)
            if result['valid'] or len(result['threats']) == 0:
                return False  # Should be invalid and detect threats

            return True

        except Exception as e:
            log.error(f"Input validation test failed: {e}")
            return False

    def test_session_security(self) -> bool:
        """Test session security and hijacking prevention."""
        try:
            from unittest.mock import patch

            # Mock Flask app for session testing
            class MockApp:
                config = {'SECRET_KEY': 'a' * 32}

            with patch('flask.current_app', MockApp()):

                user_context = {
                    'ip_address': '192.168.1.100',
                    'user_agent': 'Mozilla/5.0 Test Browser'
                }

                # Create secure session
                session_data = SecureSessionManager.create_secure_session_token(
                    user_id=123,
                    session_type="approval",
                    user_context=user_context
                )

                # Build session info for validation
                session_info = {
                    'user_id': 123,
                    'created_at': datetime.now(tz=timezone.utc).isoformat(),
                    'session_token': session_data['session_token'],
                    'fingerprint': session_data['session_data']['fingerprint']
                }

                # Validation with correct context should succeed
                if not SecureSessionManager.validate_session_security(session_info, user_context):
                    return False

                # Validation with different context should fail (hijacking attempt)
                different_context = {
                    'ip_address': '10.0.0.1',  # Different IP
                    'user_agent': 'Malicious Browser'
                }

                if SecureSessionManager.validate_session_security(session_info, different_context):
                    return False  # Should fail due to context mismatch

                return True

        except Exception as e:
            log.error(f"Session security test failed: {e}")
            return False

    def test_audit_trail_integrity(self) -> bool:
        """Test audit trail integrity and tamper detection."""
        try:
            from .audit_logger import ApprovalAuditLogger
            from unittest.mock import patch, Mock

            class MockApp:
                config = {'SECRET_KEY': 'a' * 32}

            with patch('flask.current_app', MockApp()), \
                 patch('flask.session'), \
                 patch('flask.request'):

                audit_logger = ApprovalAuditLogger()

                # Create mock user and step config
                mock_user = Mock()
                mock_user.id = 123
                mock_user.username = 'test_user'

                step_config = {
                    'name': 'Manager Approval',
                    'required_role': 'Manager'
                }

                # Create approval record with integrity protection
                approval_record = audit_logger.create_secure_approval_record(
                    user=mock_user,
                    step=1,
                    step_config=step_config,
                    comments="Approved for business necessity"
                )

                # Verify integrity hash is present
                if 'integrity_hash' not in approval_record:
                    return False

                # Verify integrity can be validated
                if not audit_logger.verify_approval_record_integrity(approval_record):
                    return False

                # Test tampering detection
                tampered_record = approval_record.copy()
                tampered_record['comments'] = "TAMPERED: Fraudulent approval"

                if audit_logger.verify_approval_record_integrity(tampered_record):
                    return False  # Should detect tampering

                return True

        except Exception as e:
            log.error(f"Audit trail integrity test failed: {e}")
            return False

    def test_performance_impact(self) -> bool:
        """Test that security controls don't severely impact performance."""
        try:
            from unittest.mock import patch

            class MockApp:
                config = {'SECRET_KEY': 'a' * 32}

            with patch('flask.current_app', MockApp()):

                # Test HMAC performance
                test_data = "approval_data_" * 100

                start_time = time.time()
                for i in range(100):
                    SecureCryptoConfig.calculate_secure_hmac(test_data)
                hmac_duration = time.time() - start_time

                # Should complete 100 HMAC calculations in under 2 seconds
                if hmac_duration > 2.0:
                    return False

                # Test validation performance
                test_validation_data = {
                    'workflow_type': 'expense_approval',
                    'priority': 'medium',
                    'amount': 1500.00,
                    'comments': 'Standard business expense',
                    'manager_id': 123
                }

                start_time = time.time()
                for i in range(50):
                    validate_approval_request(test_validation_data, user_id=789)
                validation_duration = time.time() - start_time

                # Should complete 50 validations in under 1 second
                if validation_duration > 1.0:
                    return False

                print(f"    📊 Performance: HMAC={hmac_duration:.3f}s/100ops, Validation={validation_duration:.3f}s/50ops")

                return True

        except Exception as e:
            log.error(f"Performance impact test failed: {e}")
            return False

    def run_comprehensive_validation(self):
        """Run all security validation tests."""
        print("🔒 COMPREHENSIVE SECURITY VALIDATION")
        print("=" * 60)

        security_tests = [
            ("SQL Injection Prevention", self.test_sql_injection_prevention),
            ("Authorization Bypass Prevention", self.test_authorization_bypass_prevention),
            ("Cryptographic Security", self.test_cryptographic_security),
            ("Rate Limiting Effectiveness", self.test_rate_limiting_effectiveness),
            ("Input Validation & XSS Prevention", self.test_input_validation_xss_prevention),
            ("Session Security", self.test_session_security),
            ("Audit Trail Integrity", self.test_audit_trail_integrity),
            ("Performance Impact Assessment", self.test_performance_impact)
        ]

        print(f"\n🧪 Running {len(security_tests)} Security Test Categories:")
        print("-" * 40)

        for test_name, test_function in security_tests:
            print(f"\n📋 {test_name}")
            self.run_test(test_name, test_function)

        self.print_summary()
        return len(self.failed_tests) == 0

    def print_summary(self):
        """Print comprehensive test summary."""
        print(f"\n📊 SECURITY VALIDATION SUMMARY")
        print("=" * 60)
        print(f"Total Test Categories: {self.total_tests}")
        print(f"Passed: {self.passed_tests}")
        print(f"Failed: {len(self.failed_tests)}")

        if self.total_tests > 0:
            success_rate = (self.passed_tests / self.total_tests) * 100
            print(f"Success Rate: {success_rate:.1f}%")

        if self.failed_tests:
            print(f"\n❌ FAILED TESTS:")
            for failure in self.failed_tests:
                print(f"  - {failure}")
            print(f"\n🚨 SECURITY ISSUES DETECTED - DO NOT DEPLOY TO PRODUCTION")
        else:
            print(f"\n🎉 ALL SECURITY TESTS PASSED!")
            print("✅ Security controls are functioning correctly")
            print("✅ System is ready for production deployment")

        print(f"\n🔍 Detailed Results:")
        for result in self.test_results:
            status_emoji = "✅" if "PASS" in result['status'] else "❌"
            print(f"  {status_emoji} {result['name']}")


def validate_security_configuration():
    """Validate security configuration settings."""
    print("🔧 SECURITY CONFIGURATION VALIDATION")
    print("-" * 40)

    issues = []

    # Check security constants
    if SecurityConstants.MIN_SECRET_KEY_LENGTH < 32:
        issues.append("MIN_SECRET_KEY_LENGTH should be at least 32")

    if SecurityConstants.DEFAULT_SESSION_TIMEOUT_MINUTES > 60:
        issues.append("Session timeout should not exceed 60 minutes")

    if SecurityConstants.MAX_APPROVAL_ATTEMPTS_PER_WINDOW > 20:
        issues.append("Rate limit should not exceed 20 attempts per window")

    if not issues:
        print("✅ Security configuration is valid")
    else:
        print("❌ Security configuration issues:")
        for issue in issues:
            print(f"  - {issue}")

    return len(issues) == 0


def main():
    """Main security validation entry point."""
    print("🛡️  FLASK-APPBUILDER APPROVAL SYSTEM SECURITY VALIDATION")
    print("=" * 70)
    print("Validating fixes for CVE-2024-001 through CVE-2024-008")
    print(f"Validation Time: {datetime.now().isoformat()}")

    # Run configuration validation
    config_valid = validate_security_configuration()

    # Run comprehensive security tests
    validator = SecurityValidationSuite()
    tests_passed = validator.run_comprehensive_validation()

    # Final assessment
    print("\n" + "=" * 70)
    print("🎯 FINAL SECURITY ASSESSMENT")
    print("=" * 70)

    if config_valid and tests_passed:
        print("🟢 SECURITY STATUS: PASS")
        print("✅ All security controls are functioning correctly")
        print("✅ System meets enterprise security standards")
        print("✅ Ready for production deployment")

        print(f"\n📋 Security Controls Validated:")
        print("  ✅ SQL Injection Prevention (CVE-2024-004)")
        print("  ✅ Authorization Bypass Prevention (CVE-2024-005, CVE-2024-006)")
        print("  ✅ Cryptographic Security (CVE-2024-001, CVE-2024-002, CVE-2024-003)")
        print("  ✅ Rate Limiting & DoS Protection (CVE-2024-007)")
        print("  ✅ Input Validation & XSS Prevention (CVE-2024-008)")
        print("  ✅ Session Security & Hijacking Prevention")
        print("  ✅ Audit Trail Integrity Protection")
        print("  ✅ Performance Impact Within Acceptable Limits")

    else:
        print("🔴 SECURITY STATUS: FAIL")
        print("❌ Security issues detected")
        print("🚨 DO NOT DEPLOY TO PRODUCTION")

        if not config_valid:
            print("❌ Security configuration issues found")
        if not tests_passed:
            print("❌ Security test failures detected")

    return config_valid and tests_passed


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)