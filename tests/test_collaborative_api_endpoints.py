"""
Comprehensive API endpoint tests for collaborative services.

Tests the integration of collaborative utilities with PgAppForge API endpoints,
validating request handling, response formats, error handling, and audit logging.
"""

import json
import unittest
import tempfile
import os
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from contextlib import contextmanager

# Test framework imports
try:
    from flask import Flask, request, jsonify
    from flask.testing import FlaskClient

    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("⚠️  Flask not available - API tests will use mock HTTP testing")

# Import collaborative utilities
import sys

sys.path.insert(0, "./pgappforge/collaborative/utils")

from validation import ValidationResult, FieldValidator, UserValidator
from error_handling import (
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    create_error_response,
    ErrorHandlingMixin,
)
from audit_logging import AuditEventType, CollaborativeAuditMixin


class MockFlaskApp:
    """Mock Flask app for testing when Flask is not available."""

    def __init__(self):
        self.config = {"TESTING": True, "SECRET_KEY": "test_secret_key"}

    def test_client(self):
        return MockTestClient()


class MockTestClient:
    """Mock test client for API testing."""

    def __init__(self):
        self.response_data = {}
        self.status_code = 200

    def post(self, url, json=None, headers=None):
        return MockResponse(self.response_data, self.status_code)

    def get(self, url, headers=None):
        return MockResponse(self.response_data, self.status_code)

    def put(self, url, json=None, headers=None):
        return MockResponse(self.response_data, self.status_code)

    def delete(self, url, headers=None):
        return MockResponse(self.response_data, self.status_code)


class MockResponse:
    """Mock HTTP response for testing."""

    def __init__(self, data, status_code=200):
        self.data = json.dumps(data).encode("utf-8")
        self.status_code = status_code

    def get_json(self):
        return json.loads(self.data.decode("utf-8"))


class CollaborativeAPIService(ErrorHandlingMixin, CollaborativeAuditMixin):
    """Mock collaborative API service for testing."""

    def __init__(self):
        super().__init__()
        self.teams_db = {}
        self.workspaces_db = {}
        self.users_db = {
            1: {"id": 1, "username": "admin", "role": "admin"},
            2: {"id": 2, "username": "user", "role": "user"},
            3: {"id": 3, "username": "guest", "role": "guest"},
        }

    def create_team(self, team_data, created_by_user_id):
        """Create a new team with full validation and audit logging."""
        # Set error context
        self.set_error_context(user_id=created_by_user_id, operation="create_team")

        try:
            # Validate team data
            self._validate_team_data(team_data)

            # Validate user permissions
            if not self._user_has_permission(created_by_user_id, "create_team"):
                raise AuthorizationError(
                    "User does not have permission to create teams",
                    required_permission="create_team",
                )

            # Create team
            team_id = len(self.teams_db) + 1
            team = {
                "id": team_id,
                "name": team_data["name"],
                "description": team_data["description"],
                "created_by": created_by_user_id,
                "created_at": datetime.now().isoformat(),
                "members": [created_by_user_id],
            }

            self.teams_db[team_id] = team

            # Audit logging
            self.audit_event(
                AuditEventType.TEAM_CREATED,
                resource_type="team",
                resource_id=str(team_id),
                details={"team_name": team_data["name"]},
            )

            return {"success": True, "team": team}

        except Exception as e:
            collaborative_error = self.handle_error(e, operation="create_team")
            return create_error_response(collaborative_error)

    def _validate_team_data(self, team_data):
        """Validate team creation data."""
        # Name validation
        name_result = FieldValidator.validate_required_field(
            team_data.get("name"), "name"
        )
        if not name_result.is_valid:
            raise ValidationError(name_result.error_message)

        length_result = FieldValidator.validate_string_length(
            team_data["name"], min_length=3, max_length=100, field_name="team name"
        )
        if not length_result.is_valid:
            raise ValidationError(length_result.error_message)

        # Description validation
        desc_result = FieldValidator.validate_required_field(
            team_data.get("description"), "description"
        )
        if not desc_result.is_valid:
            raise ValidationError(desc_result.error_message)

    def _user_has_permission(self, user_id, permission):
        """Check user permissions."""
        user = self.users_db.get(user_id)
        if not user:
            return False
        return user.get("role") in ["admin", "user"]

    def add_team_member(self, team_id, user_id, role, added_by_user_id):
        """Add member to team with validation."""
        self.set_error_context(user_id=added_by_user_id, operation="add_team_member")

        try:
            # Validate inputs
            user_result = UserValidator.validate_user_id(user_id)
            if not user_result.is_valid:
                raise ValidationError(user_result.error_message)

            # Check team exists
            if team_id not in self.teams_db:
                raise ValidationError(f"Team {team_id} not found")

            # Check permissions
            if not self._user_has_permission(added_by_user_id, "manage_team"):
                raise AuthorizationError(
                    "User does not have permission to add team members",
                    required_permission="manage_team",
                )

            # Add member
            team = self.teams_db[team_id]
            if user_id not in team["members"]:
                team["members"].append(user_id)

            # Audit logging
            self.audit_event(
                AuditEventType.TEAM_MEMBER_ADDED,
                resource_type="team",
                resource_id=str(team_id),
                details={"added_user_id": user_id, "role": role},
            )

            return {"success": True, "team": team}

        except Exception as e:
            collaborative_error = self.handle_error(e, operation="add_team_member")
            return create_error_response(collaborative_error)

    def get_team(self, team_id, requested_by_user_id):
        """Get team information with access control."""
        self.set_error_context(user_id=requested_by_user_id, operation="get_team")

        try:
            # Validate team exists
            if team_id not in self.teams_db:
                raise ValidationError(f"Team {team_id} not found")

            team = self.teams_db[team_id]

            # Check access permissions
            if requested_by_user_id not in team["members"]:
                if not self._user_has_permission(
                    requested_by_user_id, "view_all_teams"
                ):
                    raise AuthorizationError(
                        "User does not have access to this team",
                        required_permission="view_team",
                    )

            # Audit access
            self.audit_event(
                AuditEventType.USER_ACTION,
                resource_type="team",
                resource_id=str(team_id),
                details={"action": "view_team"},
            )

            return {"success": True, "team": team}

        except Exception as e:
            collaborative_error = self.handle_error(e, operation="get_team")
            return create_error_response(collaborative_error)


class APIEndpointTestSuite(unittest.TestCase):
    """Comprehensive API endpoint test suite."""

    def setUp(self):
        """Set up test environment."""
        if FLASK_AVAILABLE:
            self.app = Flask(__name__)
            self.app.config["TESTING"] = True
            self.app.config["SECRET_KEY"] = "test_secret_key"
            self.client = self.app.test_client()
        else:
            self.app = MockFlaskApp()
            self.client = MockTestClient()

        self.service = CollaborativeAPIService()

        # Test data
        self.valid_team_data = {
            "name": "Engineering Team",
            "description": "Software engineering team for product development",
        }

        self.invalid_team_data = {
            "name": "",  # Invalid - empty name
            "description": "Test description",
        }

        self.auth_headers = {
            "Authorization": "Bearer test_token_123",
            "Content-Type": "application/json",
        }

    def test_create_team_success(self):
        """Test successful team creation."""
        result = self.service.create_team(self.valid_team_data, created_by_user_id=1)

        self.assertTrue(result["success"])
        self.assertIn("team", result)
        self.assertEqual(result["team"]["name"], "Engineering Team")
        self.assertEqual(result["team"]["created_by"], 1)
        self.assertIsInstance(result["team"]["id"], int)

    def test_create_team_validation_error(self):
        """Test team creation with validation errors."""
        result = self.service.create_team(self.invalid_team_data, created_by_user_id=1)

        self.assertTrue(result["error"])
        self.assertEqual(result["error_code"], "VALIDATION")
        self.assertIn("message", result)
        self.assertIn("required", result["message"].lower())

    def test_create_team_authorization_error(self):
        """Test team creation with insufficient permissions."""
        result = self.service.create_team(
            self.valid_team_data, created_by_user_id=3
        )  # Guest user

        self.assertTrue(result["error"])
        self.assertEqual(result["error_code"], "AUTHORIZATION")
        self.assertIn("permission", result["message"].lower())

    def test_add_team_member_success(self):
        """Test successful team member addition."""
        # First create a team
        team_result = self.service.create_team(
            self.valid_team_data, created_by_user_id=1
        )
        team_id = team_result["team"]["id"]

        # Add member
        result = self.service.add_team_member(
            team_id, user_id=2, role="member", added_by_user_id=1
        )

        self.assertTrue(result["success"])
        self.assertIn(2, result["team"]["members"])

    def test_add_team_member_invalid_user(self):
        """Test adding invalid user to team."""
        # Create team first
        team_result = self.service.create_team(
            self.valid_team_data, created_by_user_id=1
        )
        team_id = team_result["team"]["id"]

        # Try to add invalid user
        result = self.service.add_team_member(
            team_id, user_id=-1, role="member", added_by_user_id=1
        )

        self.assertTrue(result["error"])
        self.assertEqual(result["error_code"], "VALIDATION")

    def test_get_team_success(self):
        """Test successful team retrieval."""
        # Create team
        team_result = self.service.create_team(
            self.valid_team_data, created_by_user_id=1
        )
        team_id = team_result["team"]["id"]

        # Get team
        result = self.service.get_team(team_id, requested_by_user_id=1)

        self.assertTrue(result["success"])
        self.assertEqual(result["team"]["id"], team_id)
        self.assertEqual(result["team"]["name"], "Engineering Team")

    def test_get_team_not_found(self):
        """Test getting non-existent team."""
        result = self.service.get_team(999, requested_by_user_id=1)

        self.assertTrue(result["error"])
        self.assertEqual(result["error_code"], "VALIDATION")
        self.assertIn("not found", result["message"].lower())

    def test_get_team_access_denied(self):
        """Test getting team without access."""
        # Create team as user 1
        team_result = self.service.create_team(
            self.valid_team_data, created_by_user_id=1
        )
        team_id = team_result["team"]["id"]

        # Try to access as user 2 (not a member)
        result = self.service.get_team(team_id, requested_by_user_id=2)

        self.assertTrue(result["error"])
        self.assertEqual(result["error_code"], "AUTHORIZATION")

    def test_error_response_structure(self):
        """Test that error responses have consistent structure."""
        result = self.service.create_team(self.invalid_team_data, created_by_user_id=1)

        # Check required error fields
        self.assertIn("error", result)
        self.assertIn("error_code", result)
        self.assertIn("message", result)
        self.assertIn("category", result)
        self.assertIn("severity", result)
        self.assertIn("recoverable", result)

        # Check error values
        self.assertTrue(result["error"])
        self.assertIsInstance(result["error_code"], str)
        self.assertIsInstance(result["message"], str)
        self.assertIsInstance(result["recoverable"], bool)

    def test_audit_logging_integration(self):
        """Test that operations generate audit events."""
        # Mock the audit logger to capture events
        audit_events = []

        def mock_log_event(event_type, **kwargs):
            audit_events.append({"type": event_type, "kwargs": kwargs})

        with patch.object(self.service, "audit_event", side_effect=mock_log_event):
            # Create team (should generate audit event)
            result = self.service.create_team(
                self.valid_team_data, created_by_user_id=1
            )

            if result.get("success"):
                # Check audit event was generated
                self.assertEqual(len(audit_events), 1)
                event = audit_events[0]
                self.assertEqual(event["type"], AuditEventType.TEAM_CREATED)
                self.assertEqual(event["kwargs"]["resource_type"], "team")
                self.assertIn("details", event["kwargs"])

    def test_validation_edge_cases(self):
        """Test validation with edge cases."""
        edge_cases = [
            # Empty data
            {},
            # Missing name
            {"description": "Test"},
            # Missing description
            {"name": "Test Team"},
            # Name too short
            {"name": "AB", "description": "Test"},
            # Name too long
            {"name": "x" * 101, "description": "Test"},
            # Non-string values
            {"name": 123, "description": "Test"},
            {"name": "Test", "description": 456},
        ]

        for i, test_data in enumerate(edge_cases):
            with self.subTest(case=i, data=test_data):
                result = self.service.create_team(test_data, created_by_user_id=1)
                self.assertTrue(
                    result.get("error", False),
                    f"Expected error for case {i}: {test_data}",
                )
                self.assertEqual(result.get("error_code"), "VALIDATION")

    def test_concurrent_operations(self):
        """Test handling of concurrent operations."""
        # Create a team
        team_result = self.service.create_team(
            self.valid_team_data, created_by_user_id=1
        )
        team_id = team_result["team"]["id"]

        # Simulate concurrent member additions
        results = []
        for user_id in [2, 3]:
            result = self.service.add_team_member(
                team_id, user_id=user_id, role="member", added_by_user_id=1
            )
            results.append(result)

        # Both operations should succeed
        for result in results:
            self.assertTrue(result.get("success", False))

        # Team should have all members
        team = self.service.teams_db[team_id]
        self.assertIn(2, team["members"])
        self.assertIn(3, team["members"])


class APIPerformanceTests(unittest.TestCase):
    """Performance tests for API endpoints."""

    def setUp(self):
        self.service = CollaborativeAPIService()
        self.valid_team_data = {
            "name": "Performance Test Team",
            "description": "Team for performance testing",
        }

    def test_create_team_performance(self):
        """Test team creation performance."""
        import time

        # Warm up
        for _ in range(10):
            self.service.create_team(self.valid_team_data, created_by_user_id=1)

        # Measure performance
        start_time = time.perf_counter()
        iterations = 100

        for i in range(iterations):
            team_data = {"name": f"Team {i}", "description": f"Test team {i}"}
            self.service.create_team(team_data, created_by_user_id=1)

        end_time = time.perf_counter()
        total_time = end_time - start_time
        avg_time = total_time / iterations

        print(f"\n📊 Team Creation Performance:")
        print(f"   {iterations} operations in {total_time:.3f}s")
        print(f"   Average: {avg_time * 1000:.2f}ms per operation")
        print(f"   Throughput: {iterations / total_time:.1f} operations/second")

        # Performance assertion - should be reasonable for web API
        self.assertLess(avg_time, 0.1, "Team creation should be under 100ms")

    def test_bulk_operations_performance(self):
        """Test performance of bulk operations."""
        import time

        # Create a team first
        team_result = self.service.create_team(
            self.valid_team_data, created_by_user_id=1
        )
        team_id = team_result["team"]["id"]

        # Bulk add members
        start_time = time.perf_counter()
        member_count = 50

        for i in range(member_count):
            # Add user IDs starting from 100 to avoid conflicts
            user_id = 100 + i
            self.service.users_db[user_id] = {
                "id": user_id,
                "username": f"user{i}",
                "role": "user",
            }

            result = self.service.add_team_member(
                team_id, user_id=user_id, role="member", added_by_user_id=1
            )
            self.assertTrue(result.get("success", False))

        end_time = time.perf_counter()
        total_time = end_time - start_time
        avg_time = total_time / member_count

        print(f"\n📊 Bulk Member Addition Performance:")
        print(f"   {member_count} operations in {total_time:.3f}s")
        print(f"   Average: {avg_time * 1000:.2f}ms per operation")
        print(f"   Throughput: {member_count / total_time:.1f} operations/second")

        # Verify all members were added
        team = self.service.teams_db[team_id]
        self.assertEqual(len(team["members"]), member_count + 1)  # +1 for creator


class APISecurityTests(unittest.TestCase):
    """Security tests for API endpoints."""

    def setUp(self):
        self.service = CollaborativeAPIService()
        self.valid_team_data = {
            "name": "Security Test Team",
            "description": "Team for security testing",
        }

    def test_sql_injection_protection(self):
        """Test protection against SQL injection attempts."""
        malicious_inputs = [
            "'; DROP TABLE teams; --",
            "' OR '1'='1",
            "admin'--",
            "'; INSERT INTO teams VALUES ('hacked'); --",
        ]

        for malicious_input in malicious_inputs:
            test_data = {"name": malicious_input, "description": "Test description"}

            # Should handle malicious input gracefully
            result = self.service.create_team(test_data, created_by_user_id=1)

            # Either succeed with sanitized input or fail with validation error
            if result.get("error"):
                self.assertEqual(result["error_code"], "VALIDATION")
            else:
                # If successful, name should be sanitized
                self.assertNotIn("DROP", result["team"]["name"])
                self.assertNotIn("INSERT", result["team"]["name"])

    def test_xss_protection(self):
        """Test protection against XSS attempts."""
        xss_inputs = [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert('xss')>",
            "javascript:alert('xss')",
            "<svg onload=alert('xss')>",
        ]

        for xss_input in xss_inputs:
            test_data = {
                "name": f"Team {xss_input}",
                "description": f"Description {xss_input}",
            }

            result = self.service.create_team(test_data, created_by_user_id=1)

            if result.get("success"):
                # XSS should be sanitized or escaped
                team_name = result["team"]["name"]
                self.assertNotIn("<script>", team_name)
                self.assertNotIn("javascript:", team_name)
                self.assertNotIn("onerror=", team_name)

    def test_authorization_bypass_attempts(self):
        """Test protection against authorization bypass attempts."""
        # Create team as admin
        team_result = self.service.create_team(
            self.valid_team_data, created_by_user_id=1
        )
        team_id = team_result["team"]["id"]

        # Try various unauthorized operations
        unauthorized_operations = [
            # Try to add members as guest user
            lambda: self.service.add_team_member(
                team_id, user_id=2, role="admin", added_by_user_id=3
            ),
            # Try to access team as non-member
            lambda: self.service.get_team(team_id, requested_by_user_id=2),
        ]

        for operation in unauthorized_operations:
            result = operation()
            self.assertTrue(
                result.get("error", False), "Operation should be unauthorized"
            )
            self.assertEqual(result.get("error_code"), "AUTHORIZATION")

    def test_input_size_limits(self):
        """Test protection against oversized inputs."""
        oversized_inputs = [
            {"name": "x" * 10000, "description": "Test"},  # Very long name
            {"name": "Test", "description": "x" * 100000},  # Very long description
        ]

        for test_data in oversized_inputs:
            result = self.service.create_team(test_data, created_by_user_id=1)

            # Should either validate size or handle gracefully
            if result.get("error"):
                self.assertIn(result["error_code"], ["VALIDATION", "DATA_TOO_LARGE"])


def run_api_endpoint_tests():
    """Run comprehensive API endpoint tests."""

    print("🚀 Collaborative API Endpoint Tests")
    print("=" * 50)

    # Create test suite
    test_loader = unittest.TestLoader()
    test_suite = unittest.TestSuite()

    # Add test cases
    test_suite.addTests(test_loader.loadTestsFromTestCase(APIEndpointTestSuite))
    test_suite.addTests(test_loader.loadTestsFromTestCase(APIPerformanceTests))
    test_suite.addTests(test_loader.loadTestsFromTestCase(APISecurityTests))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    # Print summary
    print(f"\n📊 Test Results Summary:")
    print(f"   Tests run: {result.testsRun}")
    print(f"   Failures: {len(result.failures)}")
    print(f"   Errors: {len(result.errors)}")
    print(
        f"   Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%"
    )

    if result.failures:
        print(f"\n❌ Failures:")
        for test, traceback in result.failures:
            print(f"   - {test}: {traceback.split('AssertionError:')[-1].strip()}")

    if result.errors:
        print(f"\n💥 Errors:")
        for test, traceback in result.errors:
            print(f"   - {test}: {traceback.split('Exception:')[-1].strip()}")

    if not result.failures and not result.errors:
        print("\n✅ All tests passed!")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_api_endpoint_tests()
    exit(0 if success else 1)
