"""
Shared validation utilities for collaborative features.

Provides common validation patterns used across all collaborative modules,
eliminating code duplication and ensuring consistent validation behavior.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum


logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a validation operation."""

    is_valid: bool
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    @classmethod
    def success(cls) -> "ValidationResult":
        """Create a successful validation result."""
        return cls(is_valid=True)

    @classmethod
    def failure(cls, message: str, code: Optional[str] = None) -> "ValidationResult":
        """Create a failed validation result."""
        return cls(is_valid=False, error_message=message, error_code=code)


class FieldValidator:
    """Common field validation utilities."""

    @staticmethod
    def validate_required_field(value: Any, field_name: str) -> ValidationResult:
        """
        Validate that a required field is present and not None/empty.

        Args:
            value: Value to validate
            field_name: Name of the field for error messages

        Returns:
            ValidationResult
        """
        if value is None:
            return ValidationResult.failure(
                f"{field_name} is required", "FIELD_REQUIRED"
            )

        if isinstance(value, str) and not value.strip():
            return ValidationResult.failure(
                f"{field_name} cannot be empty", "FIELD_EMPTY"
            )

        if isinstance(value, (list, dict)) and len(value) == 0:
            return ValidationResult.failure(
                f"{field_name} cannot be empty", "FIELD_EMPTY"
            )

        return ValidationResult.success()

    @staticmethod
    def validate_field_type(
        value: Any, expected_type: type, field_name: str
    ) -> ValidationResult:
        """
        Validate that a field is of the expected type.

        Args:
            value: Value to validate
            expected_type: Expected type
            field_name: Name of the field for error messages

        Returns:
            ValidationResult
        """
        if not isinstance(value, expected_type):
            return ValidationResult.failure(
                f"{field_name} must be of type {expected_type.__name__}, got {type(value).__name__}",
                "INVALID_TYPE",
            )
        return ValidationResult.success()

    @staticmethod
    def validate_string_length(
        value: str,
        min_length: int = 0,
        max_length: Optional[int] = None,
        field_name: str = "field",
    ) -> ValidationResult:
        """
        Validate string length constraints.

        Args:
            value: String to validate
            min_length: Minimum allowed length
            max_length: Maximum allowed length (None for no limit)
            field_name: Name of the field for error messages

        Returns:
            ValidationResult
        """
        if len(value) < min_length:
            return ValidationResult.failure(
                f"{field_name} must be at least {min_length} characters long",
                "LENGTH_TOO_SHORT",
            )

        if max_length is not None and len(value) > max_length:
            return ValidationResult.failure(
                f"{field_name} must be at most {max_length} characters long",
                "LENGTH_TOO_LONG",
            )

        return ValidationResult.success()

    @staticmethod
    def validate_numeric_range(
        value: Union[int, float],
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
        field_name: str = "field",
    ) -> ValidationResult:
        """
        Validate numeric value range constraints.

        Args:
            value: Number to validate
            min_value: Minimum allowed value (None for no limit)
            max_value: Maximum allowed value (None for no limit)
            field_name: Name of the field for error messages

        Returns:
            ValidationResult
        """
        if min_value is not None and value < min_value:
            return ValidationResult.failure(
                f"{field_name} must be at least {min_value}", "VALUE_TOO_SMALL"
            )

        if max_value is not None and value > max_value:
            return ValidationResult.failure(
                f"{field_name} must be at most {max_value}", "VALUE_TOO_LARGE"
            )

        return ValidationResult.success()


class UserValidator:
    """User-related validation utilities."""

    @staticmethod
    def validate_user_id(user_id: Any) -> ValidationResult:
        """
        Validate user ID format and value.

        Args:
            user_id: User ID to validate

        Returns:
            ValidationResult
        """
        # Check if user_id is provided
        if user_id is None:
            return ValidationResult.failure("User ID is required", "USER_ID_REQUIRED")

        # Check if user_id is integer
        if not isinstance(user_id, int):
            return ValidationResult.failure(
                "User ID must be an integer", "INVALID_USER_ID_TYPE"
            )

        # Check if user_id is positive
        if user_id <= 0:
            return ValidationResult.failure(
                "User ID must be positive", "INVALID_USER_ID_VALUE"
            )

        return ValidationResult.success()

    @staticmethod
    def validate_user_object(user: Any) -> ValidationResult:
        """
        Validate user object has required attributes.

        Args:
            user: User object to validate

        Returns:
            ValidationResult
        """
        if user is None:
            return ValidationResult.failure("User object is required", "USER_REQUIRED")

        # Check for common user attributes
        if not hasattr(user, "id"):
            return ValidationResult.failure(
                "User object missing 'id' attribute", "USER_MISSING_ID"
            )

        # Validate user ID if present
        if hasattr(user, "id"):
            return UserValidator.validate_user_id(user.id)

        return ValidationResult.success()


class TokenValidator:
    """Token validation utilities."""

    @staticmethod
    def validate_token_format(token: str, min_length: int = 32) -> ValidationResult:
        """
        Validate basic token format requirements.

        Args:
            token: Token string to validate
            min_length: Minimum token length

        Returns:
            ValidationResult
        """
        if not token:
            return ValidationResult.failure("Token is required", "TOKEN_REQUIRED")

        if not isinstance(token, str):
            return ValidationResult.failure(
                "Token must be a string", "INVALID_TOKEN_TYPE"
            )

        if len(token) < min_length:
            return ValidationResult.failure(
                f"Token must be at least {min_length} characters long",
                "TOKEN_TOO_SHORT",
            )

        return ValidationResult.success()

    @staticmethod
    def validate_jwt_token(
        token: str,
        secret_key: str,
        algorithms: List[str] = None,
        required_claims: List[str] = None,
    ) -> ValidationResult:
        """
        Validate JWT token structure and signature.

        Args:
            token: JWT token to validate
            secret_key: Secret key for verification
            algorithms: Allowed algorithms (default: ['HS256'])
            required_claims: Required claims in payload

        Returns:
            ValidationResult with decoded payload in success case
        """
        if algorithms is None:
            algorithms = ["HS256"]
        if required_claims is None:
            required_claims = ["user_id", "exp", "iat"]

        # Basic format validation
        format_result = TokenValidator.validate_token_format(token)
        if not format_result.is_valid:
            return format_result

        try:
            import jwt
            from jwt.exceptions import (
                InvalidTokenError,
                ExpiredSignatureError,
                DecodeError,
            )

            # Decode and validate JWT token
            payload = jwt.decode(
                token,
                secret_key,
                algorithms=algorithms,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "require": required_claims,
                },
            )

            # Validate required claims are present
            for claim in required_claims:
                if claim not in payload:
                    return ValidationResult.failure(
                        f"JWT token missing required claim: {claim}",
                        "JWT_MISSING_CLAIM",
                    )

            # Store payload for access
            result = ValidationResult.success()
            result.payload = payload
            return result

        except ExpiredSignatureError:
            return ValidationResult.failure("JWT token has expired", "JWT_EXPIRED")
        except DecodeError:
            return ValidationResult.failure("JWT token is malformed", "JWT_MALFORMED")
        except InvalidTokenError as e:
            return ValidationResult.failure(
                f"JWT token validation failed: {str(e)}", "JWT_INVALID"
            )
        except ImportError:
            return ValidationResult.failure(
                "JWT library not available", "JWT_LIBRARY_MISSING"
            )


class TimestampValidator:
    """Timestamp validation utilities."""

    @staticmethod
    def validate_timestamp_type(
        timestamp: Any, field_name: str = "timestamp"
    ) -> ValidationResult:
        """
        Validate that timestamp is a datetime object.

        Args:
            timestamp: Timestamp to validate
            field_name: Name of the field for error messages

        Returns:
            ValidationResult
        """
        if timestamp is None:
            return ValidationResult.failure(
                f"{field_name} is required", "TIMESTAMP_REQUIRED"
            )

        if not isinstance(timestamp, datetime):
            return ValidationResult.failure(
                f"{field_name} must be a datetime object", "INVALID_TIMESTAMP_TYPE"
            )

        return ValidationResult.success()

    @staticmethod
    def validate_timestamp_range(
        timestamp: datetime,
        max_age_hours: int = 1,
        max_future_hours: int = 1,
        field_name: str = "timestamp",
    ) -> ValidationResult:
        """
        Validate that timestamp is within reasonable range.

        Args:
            timestamp: Timestamp to validate
            max_age_hours: Maximum age in hours (past)
            max_future_hours: Maximum future time in hours
            field_name: Name of the field for error messages

        Returns:
            ValidationResult
        """
        now = datetime.now()
        time_diff = now - timestamp

        # Check if too old
        if time_diff > timedelta(hours=max_age_hours):
            return ValidationResult.failure(
                f"{field_name} is too old (more than {max_age_hours} hours)",
                "TIMESTAMP_TOO_OLD",
            )

        # Check if too far in future
        if time_diff < timedelta(hours=-max_future_hours):
            return ValidationResult.failure(
                f"{field_name} is too far in the future (more than {max_future_hours} hours)",
                "TIMESTAMP_TOO_FUTURE",
            )

        return ValidationResult.success()


class DataValidator:
    """Data structure validation utilities."""

    @staticmethod
    def validate_json_serializable(
        data: Any, field_name: str = "data"
    ) -> ValidationResult:
        """
        Validate that data is JSON serializable.

        Args:
            data: Data to validate
            field_name: Name of the field for error messages

        Returns:
            ValidationResult
        """
        try:
            json.dumps(data)
            return ValidationResult.success()
        except (TypeError, ValueError) as e:
            return ValidationResult.failure(
                f"{field_name} contains non-serializable content: {str(e)}",
                "DATA_NOT_SERIALIZABLE",
            )

    @staticmethod
    def validate_data_size(
        data: Any, max_size_bytes: int = 1024 * 1024, field_name: str = "data"
    ) -> ValidationResult:
        """
        Validate data size limits.

        Args:
            data: Data to validate
            max_size_bytes: Maximum size in bytes
            field_name: Name of the field for error messages

        Returns:
            ValidationResult
        """
        try:
            data_json = json.dumps(data)
            data_size = len(data_json.encode("utf-8"))

            if data_size > max_size_bytes:
                return ValidationResult.failure(
                    f"{field_name} too large: {data_size} bytes (max: {max_size_bytes})",
                    "DATA_TOO_LARGE",
                )

            return ValidationResult.success()

        except (TypeError, ValueError):
            return ValidationResult.failure(
                f"{field_name} is not serializable for size check",
                "DATA_SIZE_CHECK_FAILED",
            )

    @staticmethod
    def validate_dictionary_structure(
        data: Dict[str, Any],
        required_keys: List[str] = None,
        optional_keys: List[str] = None,
        strict: bool = False,
        field_name: str = "data",
    ) -> ValidationResult:
        """
        Validate dictionary structure and keys.

        Args:
            data: Dictionary to validate
            required_keys: Keys that must be present
            optional_keys: Keys that are allowed but optional
            strict: If True, only required and optional keys are allowed
            field_name: Name of the field for error messages

        Returns:
            ValidationResult
        """
        if not isinstance(data, dict):
            return ValidationResult.failure(
                f"{field_name} must be a dictionary", "INVALID_DATA_TYPE"
            )

        if required_keys:
            for key in required_keys:
                if key not in data:
                    return ValidationResult.failure(
                        f"{field_name} missing required key: {key}",
                        "MISSING_REQUIRED_KEY",
                    )

        if strict and (required_keys or optional_keys):
            allowed_keys = set(required_keys or []) | set(optional_keys or [])
            extra_keys = set(data.keys()) - allowed_keys
            if extra_keys:
                return ValidationResult.failure(
                    f"{field_name} contains unexpected keys: {', '.join(extra_keys)}",
                    "UNEXPECTED_KEYS",
                )

        return ValidationResult.success()


class MessageValidator:
    """Message validation utilities combining multiple validation patterns."""

    @staticmethod
    def validate_message_base_fields(
        message: Any, required_fields: List[str] = None
    ) -> ValidationResult:
        """
        Validate basic message fields that are common across message types.

        Args:
            message: Message object to validate
            required_fields: List of required field names

        Returns:
            ValidationResult
        """
        if required_fields is None:
            required_fields = ["message_type", "message_id"]

        for field in required_fields:
            if not hasattr(message, field):
                return ValidationResult.failure(
                    f"Message missing required field: {field}", "MISSING_MESSAGE_FIELD"
                )

            value = getattr(message, field)
            field_result = FieldValidator.validate_required_field(value, field)
            if not field_result.is_valid:
                return field_result

        return ValidationResult.success()

    @staticmethod
    def validate_message_with_user(
        message: Any, user_field: str = "sender_id"
    ) -> ValidationResult:
        """
        Validate message with user-related fields.

        Args:
            message: Message object to validate
            user_field: Name of the user field to validate

        Returns:
            ValidationResult
        """
        # Validate base fields first
        base_result = MessageValidator.validate_message_base_fields(message)
        if not base_result.is_valid:
            return base_result

        # Validate user field if present
        if hasattr(message, user_field):
            user_id = getattr(message, user_field)
            if user_id is not None:
                user_result = UserValidator.validate_user_id(user_id)
                if not user_result.is_valid:
                    return user_result

        return ValidationResult.success()

    @staticmethod
    def validate_message_with_data(
        message: Any, max_data_size: int = 1024 * 1024
    ) -> ValidationResult:
        """
        Validate message with data payload.

        Args:
            message: Message object to validate
            max_data_size: Maximum data size in bytes

        Returns:
            ValidationResult
        """
        # Validate base fields first
        base_result = MessageValidator.validate_message_base_fields(message)
        if not base_result.is_valid:
            return base_result

        # Validate data field if present
        if hasattr(message, "data") and message.data is not None:
            # Check data type
            type_result = FieldValidator.validate_field_type(message.data, dict, "data")
            if not type_result.is_valid:
                return type_result

            # Check data serializability
            serial_result = DataValidator.validate_json_serializable(
                message.data, "data"
            )
            if not serial_result.is_valid:
                return serial_result

            # Check data size
            size_result = DataValidator.validate_data_size(
                message.data, max_data_size, "data"
            )
            if not size_result.is_valid:
                return size_result

        return ValidationResult.success()

    @staticmethod
    def validate_message_with_timestamp(
        message: Any, max_age_hours: int = 1
    ) -> ValidationResult:
        """
        Validate message with timestamp field.

        Args:
            message: Message object to validate
            max_age_hours: Maximum age in hours

        Returns:
            ValidationResult
        """
        # Validate base fields first
        base_result = MessageValidator.validate_message_base_fields(message)
        if not base_result.is_valid:
            return base_result

        # Validate timestamp if present
        if hasattr(message, "timestamp") and message.timestamp is not None:
            # Check timestamp type
            type_result = TimestampValidator.validate_timestamp_type(message.timestamp)
            if not type_result.is_valid:
                return type_result

            # Check timestamp range
            range_result = TimestampValidator.validate_timestamp_range(
                message.timestamp, max_age_hours=max_age_hours
            )
            if not range_result.is_valid:
                return range_result

        return ValidationResult.success()


# Convenience function for comprehensive message validation
def validate_complete_message(
    message: Any,
    user_field: str = "sender_id",
    max_data_size: int = 1024 * 1024,
    max_age_hours: int = 1,
) -> ValidationResult:
    """
    Perform comprehensive validation on a message object.

    Args:
        message: Message object to validate
        user_field: Name of the user field to validate
        max_data_size: Maximum data size in bytes
        max_age_hours: Maximum timestamp age in hours

    Returns:
        ValidationResult
    """
    # Validate all aspects of the message
    validators = [
        lambda: MessageValidator.validate_message_with_user(message, user_field),
        lambda: MessageValidator.validate_message_with_data(message, max_data_size),
        lambda: MessageValidator.validate_message_with_timestamp(
            message, max_age_hours
        ),
    ]

    for validator in validators:
        result = validator()
        if not result.is_valid:
            return result

    return ValidationResult.success()


class ValidationHelper:
    """Convenience helper class for common validation operations."""
    
    @staticmethod
    def validate_string_length(
        value: str, 
        min_length: int = 1, 
        max_length: int = 255, 
        field_name: str = "value"
    ) -> ValidationResult:
        """Validate string length constraints."""
        return StringValidator.validate_string_length(value, min_length, max_length, field_name)
    
    @staticmethod  
    def validate_user_id(user_id: Any) -> ValidationResult:
        """Validate user ID."""
        return UserValidator.validate_user_id(user_id)
    
    @staticmethod
    def validate_workspace_id(workspace_id: Any) -> ValidationResult:
        """Validate workspace ID."""
        if not isinstance(workspace_id, (int, str)):
            return ValidationResult.failure("Workspace ID must be an integer or string", "INVALID_WORKSPACE_ID_TYPE")
        
        if isinstance(workspace_id, str):
            try:
                workspace_id = int(workspace_id)
            except ValueError:
                return ValidationResult.failure("Workspace ID must be a valid integer", "INVALID_WORKSPACE_ID")
        
        if workspace_id <= 0:
            return ValidationResult.failure("Workspace ID must be positive", "INVALID_WORKSPACE_ID")
        
        return ValidationResult.success()
    
    @staticmethod
    def validate_resource_id(resource_id: Any) -> ValidationResult:
        """Validate resource ID."""
        if not isinstance(resource_id, (int, str)):
            return ValidationResult.failure("Resource ID must be an integer or string", "INVALID_RESOURCE_ID_TYPE")
        
        if isinstance(resource_id, str):
            try:
                resource_id = int(resource_id)
            except ValueError:
                return ValidationResult.failure("Resource ID must be a valid integer", "INVALID_RESOURCE_ID")
        
        if resource_id <= 0:
            return ValidationResult.failure("Resource ID must be positive", "INVALID_RESOURCE_ID")
        
        return ValidationResult.success()
    
    @staticmethod
    def validate_session_id(session_id: str) -> ValidationResult:
        """Validate session ID format."""
        return StringValidator.validate_string_length(session_id, min_length=10, max_length=255, field_name="session_id")
    
    @staticmethod
    def validate_team_name(name: str) -> ValidationResult:
        """Validate team name."""
        return StringValidator.validate_string_length(name, min_length=2, max_length=100, field_name="team_name")
    
    @staticmethod
    def validate_workspace_name(name: str) -> ValidationResult:
        """Validate workspace name."""
        return StringValidator.validate_string_length(name, min_length=2, max_length=200, field_name="workspace_name")
    
    @staticmethod
    def validate_channel_name(name: str) -> ValidationResult:
        """Validate channel name."""
        return StringValidator.validate_string_length(name, min_length=2, max_length=100, field_name="channel_name")
    
    @staticmethod
    def validate_channel_id(channel_id: Any) -> ValidationResult:
        """Validate channel ID."""
        if not isinstance(channel_id, (int, str)):
            return ValidationResult.failure("Channel ID must be an integer or string", "INVALID_CHANNEL_ID_TYPE")
        
        if isinstance(channel_id, str):
            try:
                channel_id = int(channel_id)
            except ValueError:
                return ValidationResult.failure("Channel ID must be a valid integer", "INVALID_CHANNEL_ID")
        
        if channel_id <= 0:
            return ValidationResult.failure("Channel ID must be positive", "INVALID_CHANNEL_ID")
        
        return ValidationResult.success()
    
    @staticmethod
    def validate_message_content(content: str) -> ValidationResult:
        """Validate message content."""
        return StringValidator.validate_string_length(content, min_length=1, max_length=4000, field_name="message_content")
    
    @staticmethod
    def generate_slug(name: str) -> str:
        """Generate a URL-friendly slug from a name."""
        import re
        # Convert to lowercase and replace spaces/special chars with hyphens
        slug = re.sub(r'[^\w\s-]', '', name.lower())
        slug = re.sub(r'[\s_-]+', '-', slug)
        return slug.strip('-')
