"""
Examples of using PgAppForge collaborative validation utilities.

This file demonstrates various validation patterns and how to integrate
them into PgAppForge applications for robust input validation.
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from flask import request, jsonify

# Import validation utilities
from pgappforge.collaborative.utils.validation import (
    ValidationResult,
    FieldValidator,
    UserValidator,
    TokenValidator,
    TimestampValidator,
    DataValidator,
    MessageValidator,
    validate_complete_message,
)


# Example 1: Basic Field Validation
def validate_user_registration(form_data: Dict[str, Any]) -> ValidationResult:
    """
    Example: Validate user registration form data.

    Demonstrates basic field validation patterns.
    """

    # Check required fields
    required_fields = ["username", "email", "password"]
    for field in required_fields:
        result = FieldValidator.validate_required_field(form_data.get(field), field)
        if not result.is_valid:
            return result

    # Validate username constraints
    username_result = FieldValidator.validate_string_length(
        form_data["username"], min_length=3, max_length=50, field_name="username"
    )
    if not username_result.is_valid:
        return username_result

    # Validate email format (basic validation)
    email = form_data["email"]
    if "@" not in email or "." not in email:
        return ValidationResult.failure("Invalid email format", "INVALID_EMAIL")

    # Validate password strength
    password = form_data["password"]
    password_result = FieldValidator.validate_string_length(
        password, min_length=8, max_length=128, field_name="password"
    )
    if not password_result.is_valid:
        return password_result

    # Additional password complexity checks
    if not any(c.isupper() for c in password):
        return ValidationResult.failure(
            "Password must contain uppercase letter", "PASSWORD_WEAK"
        )

    if not any(c.isdigit() for c in password):
        return ValidationResult.failure(
            "Password must contain a number", "PASSWORD_WEAK"
        )

    return ValidationResult.success()


# Example 2: User Object Validation
def validate_team_assignment(
    user_obj: Any, team_data: Dict[str, Any]
) -> ValidationResult:
    """
    Example: Validate team assignment operation.

    Demonstrates user object validation.
    """

    # Validate user object
    user_result = UserValidator.validate_user_object(user_obj)
    if not user_result.is_valid:
        return user_result

    # Validate team data structure
    team_structure_result = DataValidator.validate_dictionary_structure(
        team_data,
        required_keys=["team_id", "role"],
        optional_keys=["department", "start_date"],
        field_name="team assignment data",
    )
    if not team_structure_result.is_valid:
        return team_structure_result

    # Validate role
    valid_roles = ["member", "admin", "owner"]
    if team_data["role"] not in valid_roles:
        return ValidationResult.failure(
            f"Invalid role. Must be one of: {', '.join(valid_roles)}", "INVALID_ROLE"
        )

    # Validate team ID format
    team_id_result = FieldValidator.validate_numeric_range(
        team_data["team_id"], min_value=1, field_name="team ID"
    )
    if not team_id_result.is_valid:
        return team_id_result

    return ValidationResult.success()


# Example 3: Token Validation for API Endpoints
def validate_api_request(
    headers: Dict[str, str], payload: Dict[str, Any]
) -> ValidationResult:
    """
    Example: Validate API request with token authentication.

    Demonstrates token validation for API security.
    """

    # Check for authorization header
    auth_header = headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return ValidationResult.failure(
            "Missing or invalid authorization header", "AUTH_REQUIRED"
        )

    # Extract token
    token = auth_header[7:]  # Remove 'Bearer ' prefix

    # Validate token format
    token_result = TokenValidator.validate_token_format(token, min_length=32)
    if not token_result.is_valid:
        return token_result

    # Validate payload size and structure
    payload_result = DataValidator.validate_data_size(
        payload,
        max_size_bytes=10 * 1024 * 1024,  # 10MB limit
        field_name="request payload",
    )
    if not payload_result.is_valid:
        return payload_result

    # Validate JSON serializability
    json_result = DataValidator.validate_json_serializable(payload, "request payload")
    if not json_result.is_valid:
        return json_result

    return ValidationResult.success()


# Example 4: Message Validation for Chat/Communication
class ChatMessage:
    """Example message class for demonstration."""

    def __init__(self, message_type, message_id, sender_id, content, timestamp=None):
        self.message_type = message_type
        self.message_id = message_id
        self.sender_id = sender_id
        self.data = {"content": content}
        self.timestamp = timestamp or datetime.now()


def validate_chat_message(
    message_data: Dict[str, Any], sender_user_id: int
) -> ValidationResult:
    """
    Example: Validate chat message before sending.

    Demonstrates message validation patterns.
    """

    # Validate sender
    sender_result = UserValidator.validate_user_id(sender_user_id)
    if not sender_result.is_valid:
        return sender_result

    # Create message object
    try:
        message = ChatMessage(
            message_type=message_data.get("type", "text"),
            message_id=message_data.get(
                "id", f"msg_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            ),
            sender_id=sender_user_id,
            content=message_data.get("content", ""),
            timestamp=datetime.now(),
        )
    except Exception as e:
        return ValidationResult.failure(
            f"Invalid message structure: {str(e)}", "INVALID_MESSAGE"
        )

    # Validate message using comprehensive validation
    message_result = validate_complete_message(
        message,
        user_field="sender_id",
        max_data_size=1024 * 50,  # 50KB limit for chat messages
        max_age_hours=1,
    )
    if not message_result.is_valid:
        return message_result

    # Validate content length for chat
    content = message_data.get("content", "")
    content_result = FieldValidator.validate_string_length(
        content, min_length=1, max_length=5000, field_name="message content"
    )
    if not content_result.is_valid:
        return content_result

    # Validate message type
    valid_types = ["text", "image", "file", "system"]
    if message.message_type not in valid_types:
        return ValidationResult.failure(
            f"Invalid message type. Must be one of: {', '.join(valid_types)}",
            "INVALID_MESSAGE_TYPE",
        )

    return ValidationResult.success()


# Example 5: Complex Data Structure Validation
def validate_project_configuration(config_data: Dict[str, Any]) -> ValidationResult:
    """
    Example: Validate complex project configuration.

    Demonstrates nested data structure validation.
    """

    # Validate top-level structure
    structure_result = DataValidator.validate_dictionary_structure(
        config_data,
        required_keys=["name", "settings"],
        optional_keys=["description", "tags", "metadata"],
        strict=True,
        field_name="project configuration",
    )
    if not structure_result.is_valid:
        return structure_result

    # Validate project name
    name_result = FieldValidator.validate_string_length(
        config_data["name"], min_length=3, max_length=100, field_name="project name"
    )
    if not name_result.is_valid:
        return name_result

    # Validate settings structure
    settings = config_data["settings"]
    settings_result = DataValidator.validate_dictionary_structure(
        settings,
        required_keys=["visibility"],
        optional_keys=["collaboration_mode", "notifications", "security"],
        field_name="project settings",
    )
    if not settings_result.is_valid:
        return settings_result

    # Validate visibility setting
    visibility = settings["visibility"]
    valid_visibility = ["public", "private", "internal"]
    if visibility not in valid_visibility:
        return ValidationResult.failure(
            f"Invalid visibility. Must be one of: {', '.join(valid_visibility)}",
            "INVALID_VISIBILITY",
        )

    # Validate optional collaboration mode
    if "collaboration_mode" in settings:
        collab_mode = settings["collaboration_mode"]
        valid_modes = ["real_time", "asynchronous", "hybrid"]
        if collab_mode not in valid_modes:
            return ValidationResult.failure(
                f"Invalid collaboration mode. Must be one of: {', '.join(valid_modes)}",
                "INVALID_COLLABORATION_MODE",
            )

    # Validate optional tags
    if "tags" in config_data:
        tags = config_data["tags"]
        if not isinstance(tags, list):
            return ValidationResult.failure("Tags must be a list", "INVALID_TAGS_TYPE")

        # Validate each tag
        for i, tag in enumerate(tags):
            tag_result = FieldValidator.validate_string_length(
                tag, min_length=1, max_length=50, field_name=f"tag {i+1}"
            )
            if not tag_result.is_valid:
                return tag_result

    return ValidationResult.success()


# Example 6: Flask Route Integration
def create_flask_validation_decorators():
    """
    Example: Create Flask route decorators using validation utilities.

    Shows how to integrate validation into PgAppForge views.
    """
    from functools import wraps
    from flask import request, jsonify

    def validate_json_request(validation_func):
        """Decorator to validate JSON request data."""

        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if not request.is_json:
                    return (
                        jsonify(
                            {
                                "error": True,
                                "message": "Request must be JSON",
                                "error_code": "INVALID_CONTENT_TYPE",
                            }
                        ),
                        400,
                    )

                try:
                    data = request.get_json()
                except Exception:
                    return (
                        jsonify(
                            {
                                "error": True,
                                "message": "Invalid JSON in request body",
                                "error_code": "INVALID_JSON",
                            }
                        ),
                        400,
                    )

                # Run validation
                result = validation_func(data)
                if not result.is_valid:
                    return (
                        jsonify(
                            {
                                "error": True,
                                "message": result.error_message,
                                "error_code": result.error_code,
                            }
                        ),
                        400,
                    )

                return f(*args, **kwargs)

            return decorated_function

        return decorator

    def validate_auth_token():
        """Decorator to validate authentication token."""

        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                # Validate API request
                result = validate_api_request(
                    dict(request.headers), request.get_json() or {}
                )

                if not result.is_valid:
                    return (
                        jsonify(
                            {
                                "error": True,
                                "message": result.error_message,
                                "error_code": result.error_code,
                            }
                        ),
                        401,
                    )

                return f(*args, **kwargs)

            return decorated_function

        return decorator

    return validate_json_request, validate_auth_token


# Example 7: Batch Validation
def validate_bulk_user_import(users_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Example: Validate bulk user import data.

    Demonstrates batch validation with detailed error reporting.
    """

    validation_results = {
        "total_users": len(users_data),
        "valid_users": 0,
        "invalid_users": 0,
        "errors": [],
    }

    # Validate overall data structure
    if not isinstance(users_data, list):
        return {
            "error": True,
            "message": "Users data must be a list",
            "error_code": "INVALID_DATA_TYPE",
        }

    # Check batch size limits
    max_batch_size = 1000
    if len(users_data) > max_batch_size:
        return {
            "error": True,
            "message": f"Batch size too large. Maximum {max_batch_size} users allowed",
            "error_code": "BATCH_TOO_LARGE",
        }

    # Validate each user
    for index, user_data in enumerate(users_data):
        result = validate_user_registration(user_data)

        if result.is_valid:
            validation_results["valid_users"] += 1
        else:
            validation_results["invalid_users"] += 1
            validation_results["errors"].append(
                {
                    "index": index,
                    "user_data": user_data,
                    "error_message": result.error_message,
                    "error_code": result.error_code,
                }
            )

    # Add summary
    validation_results["success_rate"] = (
        validation_results["valid_users"] / validation_results["total_users"] * 100
        if validation_results["total_users"] > 0
        else 0
    )

    return validation_results


# Example usage and testing
def run_validation_examples():
    """Run examples to demonstrate validation utilities."""

    print("🔍 PgAppForge Collaborative Validation Examples")
    print("=" * 60)

    # Example 1: User registration validation
    print("\n1. User Registration Validation")
    valid_registration = {
        "username": "john_doe",
        "email": "john@example.com",
        "password": "SecurePass123",
    }

    invalid_registration = {
        "username": "jo",  # Too short
        "email": "invalid-email",
        "password": "weak",  # No uppercase, too short
    }

    result1 = validate_user_registration(valid_registration)
    print(f"✅ Valid registration: {result1.is_valid}")

    result2 = validate_user_registration(invalid_registration)
    print(f"❌ Invalid registration: {result2.is_valid} - {result2.error_message}")

    # Example 2: Chat message validation
    print("\n2. Chat Message Validation")
    valid_message = {
        "type": "text",
        "content": "Hello, this is a valid message!",
        "id": "msg_123",
    }

    result3 = validate_chat_message(valid_message, sender_user_id=123)
    print(f"✅ Valid message: {result3.is_valid}")

    invalid_message = {
        "type": "invalid_type",
        "content": "",  # Empty content
    }

    result4 = validate_chat_message(invalid_message, sender_user_id=123)
    print(f"❌ Invalid message: {result4.is_valid} - {result4.error_message}")

    # Example 3: Project configuration validation
    print("\n3. Project Configuration Validation")
    valid_config = {
        "name": "My Project",
        "settings": {
            "visibility": "private",
            "collaboration_mode": "real_time",
            "notifications": True,
        },
        "tags": ["research", "ai", "collaboration"],
    }

    result5 = validate_project_configuration(valid_config)
    print(f"✅ Valid config: {result5.is_valid}")

    invalid_config = {
        "name": "A",  # Too short
        "settings": {"visibility": "invalid_visibility"},  # Invalid value
    }

    result6 = validate_project_configuration(invalid_config)
    print(f"❌ Invalid config: {result6.is_valid} - {result6.error_message}")

    # Example 4: Bulk validation
    print("\n4. Bulk User Import Validation")
    bulk_users = [
        {"username": "user1", "email": "user1@example.com", "password": "ValidPass123"},
        {"username": "u", "email": "invalid", "password": "weak"},  # Invalid
        {
            "username": "user3",
            "email": "user3@example.com",
            "password": "AnotherValid123",
        },
    ]

    bulk_result = validate_bulk_user_import(bulk_users)
    print(
        f"📊 Bulk validation: {bulk_result['valid_users']}/{bulk_result['total_users']} valid"
    )
    print(f"   Success rate: {bulk_result['success_rate']:.1f}%")

    if bulk_result["errors"]:
        print(f"   First error: {bulk_result['errors'][0]['error_message']}")

    print("\n🎉 Validation examples completed!")


if __name__ == "__main__":
    run_validation_examples()
