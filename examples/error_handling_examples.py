"""
Examples of using PgAppForge collaborative error handling utilities.

This file demonstrates various error handling patterns and how to create
robust, user-friendly error responses in PgAppForge applications.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from flask import request, jsonify

# Import error handling utilities
from pgappforge.collaborative.utils.error_handling import (
    CollaborativeError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    ConcurrencyError,
    NetworkError,
    DatabaseError,
    ConfigurationError,
    ExternalServiceError,
    ErrorHandlingMixin,
    ErrorContext,
    ErrorCategory,
    ErrorSeverity,
    create_error_response,
    log_error_with_context,
)


# Example 1: Basic Error Creation and Handling
def demonstrate_basic_error_handling():
    """Demonstrate basic error creation and response handling."""

    print("1. Basic Error Handling Examples")
    print("-" * 40)

    # Create different types of errors
    errors = [
        ValidationError(
            "Username must be at least 3 characters", field_name="username"
        ),
        AuthenticationError("Invalid login credentials"),
        AuthorizationError(
            "User does not have admin access", required_permission="admin"
        ),
        ConcurrencyError(
            "Resource was modified by another user", conflict_type="optimistic_lock"
        ),
        NetworkError(
            "Failed to connect to external service", endpoint="https://api.example.com"
        ),
        DatabaseError("Connection timeout", operation="SELECT", table="users"),
        ConfigurationError("Missing required setting", config_key="DATABASE_URL"),
        ExternalServiceError("Payment processor unavailable", service_name="stripe"),
    ]

    # Demonstrate error responses
    for error in errors:
        response = create_error_response(error)
        print(f"✅ {error.__class__.__name__}:")
        print(f"   Code: {response['error_code']}")
        print(f"   Category: {response['category']}")
        print(f"   Message: {response['message']}")
        print(f"   Recoverable: {response['recoverable']}")
        print()


# Example 2: Service with Error Handling Mixin
class UserManagementService(ErrorHandlingMixin):
    """Example service demonstrating error handling patterns."""

    def __init__(self):
        super().__init__()
        self.users_db = {}  # Simulated user database

    def create_user(
        self, user_data: Dict[str, Any], created_by_user_id: int
    ) -> Dict[str, Any]:
        """
        Create a new user with comprehensive error handling.

        Demonstrates setting error context and handling various error scenarios.
        """

        # Set error context for debugging and audit trails
        self.set_error_context(
            user_id=created_by_user_id,
            operation="create_user",
            request_id=getattr(request, "id", None) if request else None,
        )

        try:
            # Validate required fields
            if not user_data.get("username"):
                raise ValidationError("Username is required", field_name="username")

            if not user_data.get("email"):
                raise ValidationError("Email is required", field_name="email")

            # Check for duplicate username
            if user_data["username"] in self.users_db:
                raise ValidationError(
                    "Username already exists",
                    field_name="username",
                    field_value=user_data["username"],
                )

            # Simulate external service validation
            if not self._validate_email_with_external_service(user_data["email"]):
                raise ExternalServiceError(
                    "Email validation service failed",
                    service_name="email_validator",
                    service_endpoint="/validate-email",
                )

            # Create user
            user = self._create_user_record(user_data, created_by_user_id)

            return {
                "success": True,
                "user": user,
                "message": "User created successfully",
            }

        except Exception as e:
            # Handle all errors with consistent error handling
            collaborative_error = self.handle_error(e, operation="create_user")
            return create_error_response(collaborative_error)

    def _validate_email_with_external_service(self, email: str) -> bool:
        """Simulate external email validation service."""
        # Simulate service failure for certain emails
        if email.endswith("@invalid.com"):
            raise NetworkError("Email validation service unreachable")
        return True

    def _create_user_record(
        self, user_data: Dict[str, Any], created_by: int
    ) -> Dict[str, Any]:
        """Create user record in database."""
        # Simulate database operation
        user_id = len(self.users_db) + 1
        user = {
            "id": user_id,
            "username": user_data["username"],
            "email": user_data["email"],
            "created_by": created_by,
            "created_at": datetime.now().isoformat(),
            "status": "active",
        }

        self.users_db[user_data["username"]] = user
        return user

    def update_user_permissions(
        self, user_id: int, permissions: Dict[str, Any], updated_by_user_id: int
    ) -> Dict[str, Any]:
        """
        Update user permissions with authorization checks.

        Demonstrates authorization error handling.
        """

        self.set_error_context(
            user_id=updated_by_user_id, operation="update_user_permissions"
        )

        try:
            # Check if updater has permission to modify permissions
            if not self._user_has_permission(updated_by_user_id, "manage_users"):
                raise AuthorizationError(
                    "User does not have permission to update user permissions",
                    required_permission="manage_users",
                )

            # Check if target user exists
            target_user = self._get_user_by_id(user_id)
            if not target_user:
                raise ValidationError(f"User with ID {user_id} not found")

            # Simulate concurrent modification check
            if self._user_recently_modified(user_id):
                raise ConcurrencyError(
                    "User permissions were recently modified by another administrator",
                    conflict_type="permission_modification",
                )

            # Update permissions
            updated_user = self._update_user_permissions_record(user_id, permissions)

            return {
                "success": True,
                "user": updated_user,
                "message": "User permissions updated successfully",
            }

        except Exception as e:
            collaborative_error = self.handle_error(
                e, operation="update_user_permissions"
            )
            return create_error_response(collaborative_error)

    def _user_has_permission(self, user_id: int, permission: str) -> bool:
        """Check if user has specific permission."""
        # Simulate permission check - user 1 is admin
        return user_id == 1

    def _get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        for user in self.users_db.values():
            if user["id"] == user_id:
                return user
        return None

    def _user_recently_modified(self, user_id: int) -> bool:
        """Check if user was recently modified (simulated concurrency check)."""
        # Simulate concurrency issue for user ID 999
        return user_id == 999

    def _update_user_permissions_record(
        self, user_id: int, permissions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update user permissions in database."""
        user = self._get_user_by_id(user_id)
        if user:
            user["permissions"] = permissions
            user["updated_at"] = datetime.now().isoformat()
        return user

    def bulk_import_users(
        self, users_data: list, imported_by_user_id: int
    ) -> Dict[str, Any]:
        """
        Bulk import users with comprehensive error tracking.

        Demonstrates handling multiple errors and partial success scenarios.
        """

        self.set_error_context(
            user_id=imported_by_user_id, operation="bulk_import_users"
        )

        results = {
            "total_users": len(users_data),
            "successful_imports": 0,
            "failed_imports": 0,
            "errors": [],
            "imported_users": [],
        }

        try:
            # Validate bulk operation permissions
            if not self._user_has_permission(imported_by_user_id, "bulk_import"):
                raise AuthorizationError(
                    "User does not have permission to perform bulk imports",
                    required_permission="bulk_import",
                )

            # Process each user
            for index, user_data in enumerate(users_data):
                try:
                    # Use safe_execute for individual user creation
                    user_result = self.safe_execute(
                        self._create_individual_user,
                        user_data,
                        imported_by_user_id,
                        operation=f"import_user_{index}",
                    )

                    results["successful_imports"] += 1
                    results["imported_users"].append(user_result)

                except Exception as e:
                    results["failed_imports"] += 1

                    # Convert to collaborative error for consistent handling
                    collaborative_error = self.handle_error(e, log_error=False)

                    results["errors"].append(
                        {
                            "index": index,
                            "user_data": user_data,
                            "error": create_error_response(collaborative_error),
                        }
                    )

            # Determine overall success
            success_rate = (
                results["successful_imports"] / results["total_users"]
                if results["total_users"] > 0
                else 0
            )

            return {
                "success": success_rate > 0.5,  # Consider successful if >50% succeed
                "results": results,
                "message": f"Imported {results['successful_imports']}/{results['total_users']} users successfully",
            }

        except Exception as e:
            # Handle authorization or other top-level errors
            collaborative_error = self.handle_error(e, operation="bulk_import_users")
            return create_error_response(collaborative_error)

    def _create_individual_user(
        self, user_data: Dict[str, Any], created_by: int
    ) -> Dict[str, Any]:
        """Create individual user (used in bulk operations)."""
        # This would call the same validation and creation logic as create_user
        # but without the error response formatting
        if not user_data.get("username"):
            raise ValidationError("Username is required")

        if user_data["username"] in self.users_db:
            raise ValidationError("Username already exists")

        return self._create_user_record(user_data, created_by)


# Example 3: Flask Route Error Handling
class FlaskRouteExamples:
    """Examples of integrating error handling with Flask routes."""

    @staticmethod
    def create_error_handling_decorator():
        """Create a decorator for consistent API error handling."""
        from functools import wraps

        def handle_api_errors(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                try:
                    return f(*args, **kwargs)

                except CollaborativeError as e:
                    # Collaborative errors are already well-formed
                    response = create_error_response(e, include_debug=current_app.debug)
                    status_code = FlaskRouteExamples._get_status_code_for_error(e)
                    return jsonify(response), status_code

                except Exception as e:
                    # Handle unexpected errors
                    logger = logging.getLogger(__name__)
                    logger.exception("Unexpected error in API endpoint")

                    # Create generic error response
                    error = CollaborativeError(
                        message="An unexpected error occurred",
                        category=ErrorCategory.SYSTEM,
                        severity=ErrorSeverity.HIGH,
                    )

                    response = create_error_response(
                        error, include_debug=current_app.debug
                    )
                    return jsonify(response), 500

            return decorated_function

        return handle_api_errors

    @staticmethod
    def _get_status_code_for_error(error: CollaborativeError) -> int:
        """Map error types to HTTP status codes."""
        status_map = {
            ValidationError: 400,
            AuthenticationError: 401,
            AuthorizationError: 403,
            ConcurrencyError: 409,
            NetworkError: 502,
            DatabaseError: 503,
            ConfigurationError: 500,
            ExternalServiceError: 502,
        }

        return status_map.get(type(error), 500)


# Example 4: Advanced Error Context Management
class AdvancedErrorHandlingService(ErrorHandlingMixin):
    """Service demonstrating advanced error context management."""

    def process_complex_workflow(
        self, workflow_data: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """
        Process a complex workflow with nested error contexts.

        Demonstrates managing error context across multiple operations.
        """

        # Set initial context
        self.set_error_context(
            user_id=user_id,
            operation="process_complex_workflow",
            workflow_id=workflow_data.get("id"),
            workflow_type=workflow_data.get("type"),
        )

        try:
            # Step 1: Validate workflow
            with self._error_context_step("validate_workflow"):
                self._validate_workflow(workflow_data)

            # Step 2: Process data
            with self._error_context_step("process_data"):
                processed_data = self._process_workflow_data(workflow_data)

            # Step 3: Execute workflow
            with self._error_context_step("execute_workflow"):
                result = self._execute_workflow(processed_data)

            return {
                "success": True,
                "result": result,
                "message": "Workflow processed successfully",
            }

        except Exception as e:
            collaborative_error = self.handle_error(e)
            return create_error_response(collaborative_error)

    def _error_context_step(self, step_name: str):
        """Context manager for managing error context during workflow steps."""
        from contextlib import contextmanager

        @contextmanager
        def step_context():
            # Save current context
            original_operation = (
                self._error_context.operation if self._error_context else None
            )

            try:
                # Update context for this step
                if self._error_context:
                    self._error_context.operation = f"{original_operation}.{step_name}"

                yield

            finally:
                # Restore original context
                if self._error_context and original_operation:
                    self._error_context.operation = original_operation

        return step_context()

    def _validate_workflow(self, workflow_data: Dict[str, Any]) -> None:
        """Validate workflow data."""
        if not workflow_data.get("steps"):
            raise ValidationError("Workflow must have at least one step")

        if len(workflow_data["steps"]) > 100:
            raise ValidationError("Workflow cannot have more than 100 steps")

    def _process_workflow_data(self, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process workflow data."""
        # Simulate processing
        processed = {
            "id": workflow_data.get("id"),
            "processed_steps": len(workflow_data.get("steps", [])),
            "processing_time": datetime.now().isoformat(),
        }

        return processed

    def _execute_workflow(self, processed_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the workflow."""
        # Simulate execution
        return {
            "execution_id": f"exec_{processed_data['id']}",
            "status": "completed",
            "executed_at": datetime.now().isoformat(),
        }


# Example usage and testing
def run_error_handling_examples():
    """Run examples to demonstrate error handling utilities."""

    print("🚨 PgAppForge Collaborative Error Handling Examples")
    print("=" * 65)

    # Basic error handling
    demonstrate_basic_error_handling()

    # Service with error handling
    print("\n2. Service Error Handling Examples")
    print("-" * 40)

    service = UserManagementService()

    # Test successful user creation
    result1 = service.create_user(
        {"username": "john_doe", "email": "john@example.com"}, created_by_user_id=1
    )

    print(f"✅ User creation success: {result1.get('success', False)}")

    # Test validation error
    result2 = service.create_user(
        {"username": "", "email": "john@example.com"}, created_by_user_id=1  # Invalid
    )

    print(f"❌ User creation validation error: {result2.get('error_code', 'N/A')}")
    print(f"   Message: {result2.get('message', 'N/A')}")

    # Test duplicate username error
    result3 = service.create_user(
        {"username": "john_doe", "email": "john2@example.com"},  # Duplicate
        created_by_user_id=1,
    )

    print(f"❌ Duplicate username error: {result3.get('error_code', 'N/A')}")

    # Test external service error
    result4 = service.create_user(
        {
            "username": "invalid_user",
            "email": "test@invalid.com",  # Triggers external service error
        },
        created_by_user_id=1,
    )

    print(f"❌ External service error: {result4.get('error_code', 'N/A')}")

    # Test authorization error
    result5 = service.update_user_permissions(
        user_id=1, permissions={"admin": True}, updated_by_user_id=2  # Non-admin user
    )

    print(f"❌ Authorization error: {result5.get('error_code', 'N/A')}")

    # Test concurrency error
    result6 = service.update_user_permissions(
        user_id=999,  # Triggers concurrency check
        permissions={"admin": True},
        updated_by_user_id=1,
    )

    print(f"❌ Concurrency error: {result6.get('error_code', 'N/A')}")

    # Test bulk import with mixed results
    print("\n3. Bulk Import with Error Handling")
    print("-" * 40)

    bulk_users = [
        {"username": "user1", "email": "user1@example.com"},
        {"username": "", "email": "invalid@example.com"},  # Invalid
        {"username": "user3", "email": "user3@example.com"},
        {"username": "john_doe", "email": "duplicate@example.com"},  # Duplicate
    ]

    bulk_result = service.bulk_import_users(bulk_users, imported_by_user_id=1)

    if bulk_result.get("success"):
        results = bulk_result["results"]
        print(
            f"📊 Bulk import: {results['successful_imports']}/{results['total_users']} succeeded"
        )
        print(f"   Errors: {results['failed_imports']}")

        if results["errors"]:
            first_error = results["errors"][0]["error"]
            print(
                f"   First error: {first_error['error_code']} - {first_error['message']}"
            )
    else:
        print(f"❌ Bulk import failed: {bulk_result.get('message', 'Unknown error')}")

    print("\n🎉 Error handling examples completed!")


if __name__ == "__main__":
    # Set up logging for examples
    logging.basicConfig(level=logging.INFO)

    run_error_handling_examples()
