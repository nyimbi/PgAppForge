"""
Example implementation of a collaborative service using all shared utilities.

This example demonstrates how to build a comprehensive service that leverages
validation, error handling, audit logging, and transaction management.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from flask import request, current_app

# Import collaborative utilities
from pgappforge.collaborative.interfaces.base_interfaces import (
    BaseCollaborativeService,
)
from pgappforge.collaborative.utils.validation import (
    ValidationResult,
    FieldValidator,
    UserValidator,
    DataValidator,
    validate_complete_message,
)
from pgappforge.collaborative.utils.error_handling import (
    ErrorHandlingMixin,
    ValidationError,
    AuthorizationError,
    ConcurrencyError,
    create_error_response,
)
from pgappforge.collaborative.utils.audit_logging import (
    CollaborativeAuditMixin,
    AuditEventType,
)
from pgappforge.collaborative.utils.transaction_manager import (
    TransactionMixin,
    TransactionScope,
    transaction_required,
)


class ProjectCollaborationService(
    BaseCollaborativeService,
    ErrorHandlingMixin,
    CollaborativeAuditMixin,
    TransactionMixin,
):
    """
    Example service for managing project collaboration.

    Demonstrates integration of all collaborative utilities in a real-world scenario.
    """

    def initialize(self):
        """Initialize the service."""
        self.audit_service_event("started")

    def cleanup(self):
        """Cleanup service resources."""
        self.audit_service_event("stopped")

    def create_project(
        self, project_data: Dict[str, Any], created_by_user_id: int
    ) -> Dict[str, Any]:
        """
        Create a new collaborative project.

        Args:
            project_data: Project information
            created_by_user_id: ID of user creating the project

        Returns:
            Project creation result with success/error information
        """
        # Set error and audit context
        self.set_error_context(user_id=created_by_user_id, operation="create_project")

        self.audit_logger.set_context(
            user_id=created_by_user_id,
            session_id=request.session.get("session_id") if request else None,
            ip_address=request.remote_addr if request else None,
        )

        try:
            # Validate input data
            validation_result = self._validate_project_data(
                project_data, created_by_user_id
            )
            if not validation_result.is_valid:
                raise ValidationError(
                    validation_result.error_message,
                    error_code=validation_result.error_code,
                )

            # Create project with transaction management
            project = self._create_project_with_transaction(
                project_data, created_by_user_id
            )

            # Log successful creation
            self.audit_event(
                AuditEventType.WORKSPACE_CREATED,
                resource_type="project",
                resource_id=str(project["id"]),
                details={
                    "project_name": project_data.get("name"),
                    "project_type": project_data.get("type", "standard"),
                },
            )

            return {
                "success": True,
                "project": project,
                "message": "Project created successfully",
            }

        except Exception as e:
            # Handle errors with unified error handling
            collaborative_error = self.handle_error(e, operation="create_project")

            # Log error for audit
            self.audit_security_event(
                AuditEventType.SERVICE_ERROR,
                outcome="failure",
                details={"operation": "create_project", "error": str(e)},
            )

            return create_error_response(collaborative_error)

    def _validate_project_data(
        self, project_data: Dict[str, Any], user_id: int
    ) -> ValidationResult:
        """Validate project creation data."""

        # Validate user
        user_result = UserValidator.validate_user_id(user_id)
        if not user_result.is_valid:
            return user_result

        # Validate required fields
        required_fields = ["name", "description"]
        for field in required_fields:
            field_result = FieldValidator.validate_required_field(
                project_data.get(field), field
            )
            if not field_result.is_valid:
                return field_result

        # Validate project name length
        name_result = FieldValidator.validate_string_length(
            project_data["name"],
            min_length=3,
            max_length=100,
            field_name="project name",
        )
        if not name_result.is_valid:
            return name_result

        # Validate description length
        desc_result = FieldValidator.validate_string_length(
            project_data["description"],
            min_length=10,
            max_length=1000,
            field_name="project description",
        )
        if not desc_result.is_valid:
            return desc_result

        # Validate JSON serializable data
        data_result = DataValidator.validate_json_serializable(
            project_data, "project_data"
        )
        if not data_result.is_valid:
            return data_result

        # Validate optional settings
        if "settings" in project_data:
            settings_result = DataValidator.validate_dictionary_structure(
                project_data["settings"],
                required_keys=[],
                optional_keys=["visibility", "collaboration_mode", "notifications"],
                field_name="project settings",
            )
            if not settings_result.is_valid:
                return settings_result

        return ValidationResult.success()

    @transaction_required(scope=TransactionScope.READ_WRITE, retry_on_deadlock=True)
    def _create_project_with_transaction(
        self, project_data: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """Create project within a transaction with automatic deadlock retry."""

        # Simulate project creation (in real implementation, this would interact with database)
        project = {
            "id": f"proj_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "name": project_data["name"],
            "description": project_data["description"],
            "created_by": user_id,
            "created_at": datetime.now().isoformat(),
            "status": "active",
            "settings": project_data.get("settings", {}),
        }

        # Set up initial permissions using savepoint
        with self.with_savepoint("project_permissions"):
            try:
                project["permissions"] = [
                    {
                        "user_id": user_id,
                        "role": "owner",
                        "granted_at": datetime.now().isoformat(),
                    }
                ]
            except Exception:
                # If permission setup fails, continue without it
                project["permissions"] = []

        return project

    def add_project_member(
        self, project_id: str, user_id: int, role: str, added_by_user_id: int
    ) -> Dict[str, Any]:
        """
        Add a member to a project.

        Args:
            project_id: Project identifier
            user_id: User to add to project
            role: Role to assign (viewer, editor, admin)
            added_by_user_id: User performing the action

        Returns:
            Operation result
        """
        # Set context
        self.set_error_context(user_id=added_by_user_id, operation="add_project_member")

        self.audit_logger.set_context(
            user_id=added_by_user_id,
            session_id=request.session.get("session_id") if request else None,
        )

        try:
            # Validate inputs
            user_result = UserValidator.validate_user_id(user_id)
            if not user_result.is_valid:
                raise ValidationError(user_result.error_message)

            adder_result = UserValidator.validate_user_id(added_by_user_id)
            if not adder_result.is_valid:
                raise ValidationError(adder_result.error_message)

            # Validate role
            valid_roles = ["viewer", "editor", "admin"]
            if role not in valid_roles:
                raise ValidationError(
                    f"Invalid role. Must be one of: {', '.join(valid_roles)}"
                )

            # Check permissions (example business logic)
            if not self._user_can_add_members(project_id, added_by_user_id):
                raise AuthorizationError(
                    "User does not have permission to add members to this project",
                    required_permission="project.add_members",
                )

            # Add member with transaction management
            result = self._add_member_with_transaction(
                project_id, user_id, role, added_by_user_id
            )

            # Log successful addition
            self.audit_event(
                AuditEventType.TEAM_MEMBER_ADDED,
                resource_type="project",
                resource_id=project_id,
                details={
                    "added_user_id": user_id,
                    "role": role,
                    "added_by": added_by_user_id,
                },
            )

            return {
                "success": True,
                "member": result,
                "message": f"User {user_id} added to project with role {role}",
            }

        except Exception as e:
            collaborative_error = self.handle_error(e, operation="add_project_member")

            self.audit_security_event(
                AuditEventType.AUTHORIZATION_FAILED
                if isinstance(e, AuthorizationError)
                else AuditEventType.SERVICE_ERROR,
                outcome="failure",
                details={
                    "operation": "add_project_member",
                    "project_id": project_id,
                    "target_user_id": user_id,
                },
            )

            return create_error_response(collaborative_error)

    def _user_can_add_members(self, project_id: str, user_id: int) -> bool:
        """Check if user has permission to add members to project."""
        # Example permission check - in real implementation,
        # this would check database permissions
        return True  # Simplified for example

    @transaction_required(scope=TransactionScope.READ_WRITE)
    def _add_member_with_transaction(
        self, project_id: str, user_id: int, role: str, added_by_user_id: int
    ) -> Dict[str, Any]:
        """Add project member within transaction."""

        # Check for existing membership (prevent duplicates)
        # In real implementation, this would be a database query

        # Simulate adding member
        member = {
            "user_id": user_id,
            "project_id": project_id,
            "role": role,
            "added_by": added_by_user_id,
            "added_at": datetime.now().isoformat(),
            "status": "active",
        }

        return member

    def send_project_message(
        self, project_id: str, sender_id: int, message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a message within a project.

        Demonstrates message validation using the collaborative utilities.

        Args:
            project_id: Project identifier
            sender_id: User sending the message
            message_data: Message content and metadata

        Returns:
            Message sending result
        """
        # Set context
        self.set_error_context(user_id=sender_id, operation="send_project_message")

        try:
            # Create message object for validation
            message = self._create_message_object(project_id, sender_id, message_data)

            # Validate message using collaborative utilities
            message_result = validate_complete_message(message)
            if not message_result.is_valid:
                raise ValidationError(message_result.error_message)

            # Check sending permissions
            if not self._user_can_send_messages(project_id, sender_id):
                raise AuthorizationError("User cannot send messages in this project")

            # Send message (example implementation)
            sent_message = self._send_message_with_transaction(message)

            # Log message sending
            self.audit_event(
                AuditEventType.MESSAGE_SENT,
                resource_type="project",
                resource_id=project_id,
                details={
                    "message_id": sent_message["id"],
                    "message_type": message_data.get("type", "text"),
                    "recipient_count": len(sent_message.get("recipients", [])),
                },
            )

            return {
                "success": True,
                "message": sent_message,
                "message": "Message sent successfully",
            }

        except Exception as e:
            collaborative_error = self.handle_error(e, operation="send_project_message")

            self.audit_security_event(
                AuditEventType.SERVICE_ERROR,
                outcome="failure",
                details={"operation": "send_project_message", "project_id": project_id},
            )

            return create_error_response(collaborative_error)

    def _create_message_object(
        self, project_id: str, sender_id: int, message_data: Dict[str, Any]
    ) -> Any:
        """Create message object for validation."""

        class ProjectMessage:
            def __init__(self):
                self.message_type = message_data.get("type", "text")
                self.message_id = f"msg_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                self.sender_id = sender_id
                self.data = {
                    "content": message_data.get("content", ""),
                    "project_id": project_id,
                    "metadata": message_data.get("metadata", {}),
                }
                self.timestamp = datetime.now()

        return ProjectMessage()

    def _user_can_send_messages(self, project_id: str, user_id: int) -> bool:
        """Check if user can send messages in project."""
        return True  # Simplified for example

    @transaction_required(scope=TransactionScope.READ_WRITE)
    def _send_message_with_transaction(self, message) -> Dict[str, Any]:
        """Send message within transaction."""

        # Simulate message sending
        sent_message = {
            "id": message.message_id,
            "type": message.message_type,
            "sender_id": message.sender_id,
            "content": message.data["content"],
            "project_id": message.data["project_id"],
            "sent_at": message.timestamp.isoformat(),
            "recipients": ["user_1", "user_2", "user_3"],  # Example recipients
            "status": "delivered",
        }

        return sent_message

    def get_project_analytics(
        self, project_id: str, requested_by_user_id: int
    ) -> Dict[str, Any]:
        """
        Get project analytics with comprehensive error handling.

        Demonstrates read-only operations with validation and audit logging.
        """
        # Set context
        self.set_error_context(
            user_id=requested_by_user_id, operation="get_project_analytics"
        )

        try:
            # Validate user
            user_result = UserValidator.validate_user_id(requested_by_user_id)
            if not user_result.is_valid:
                raise ValidationError(user_result.error_message)

            # Check permissions
            if not self._user_can_view_analytics(project_id, requested_by_user_id):
                raise AuthorizationError("User cannot view project analytics")

            # Get analytics with read-only transaction
            with self.with_transaction(TransactionScope.READ_ONLY):
                analytics = self._get_analytics_data(project_id)

            # Log analytics access
            self.audit_event(
                AuditEventType.USER_ACTION,
                resource_type="project",
                resource_id=project_id,
                details={"action": "view_analytics"},
            )

            return {"success": True, "analytics": analytics}

        except Exception as e:
            collaborative_error = self.handle_error(
                e, operation="get_project_analytics"
            )

            if isinstance(e, AuthorizationError):
                self.audit_security_event(
                    AuditEventType.AUTHORIZATION_FAILED,
                    outcome="failure",
                    details={"project_id": project_id, "requested_analytics": True},
                )

            return create_error_response(collaborative_error)

    def _user_can_view_analytics(self, project_id: str, user_id: int) -> bool:
        """Check if user can view project analytics."""
        return True  # Simplified for example

    def _get_analytics_data(self, project_id: str) -> Dict[str, Any]:
        """Get project analytics data."""
        # Example analytics data
        return {
            "total_members": 5,
            "messages_this_week": 23,
            "active_sessions": 2,
            "last_activity": datetime.now().isoformat(),
            "popular_features": ["chat", "file_sharing", "task_management"],
        }


# Example usage
def example_usage():
    """Example of how to use the ProjectCollaborationService."""

    # Initialize service (normally done by PgAppForge)
    service = ProjectCollaborationService(app_builder=None, service_registry=None)
    service.initialize()

    # Example project data
    project_data = {
        "name": "AI Research Project",
        "description": "Collaborative research on machine learning algorithms",
        "type": "research",
        "settings": {
            "visibility": "private",
            "collaboration_mode": "real_time",
            "notifications": True,
        },
    }

    # Create project
    result = service.create_project(project_data, created_by_user_id=123)
    if result.get("success"):
        project_id = result["project"]["id"]
        print(f"✅ Project created: {project_id}")

        # Add member
        member_result = service.add_project_member(
            project_id=project_id, user_id=456, role="editor", added_by_user_id=123
        )

        if member_result.get("success"):
            print("✅ Member added successfully")

        # Send message
        message_data = {
            "type": "text",
            "content": "Welcome to the AI Research Project!",
            "metadata": {"priority": "normal"},
        }

        message_result = service.send_project_message(
            project_id=project_id, sender_id=123, message_data=message_data
        )

        if message_result.get("success"):
            print("✅ Message sent successfully")

        # Get analytics
        analytics_result = service.get_project_analytics(
            project_id=project_id, requested_by_user_id=123
        )

        if analytics_result.get("success"):
            print(
                f"✅ Analytics: {analytics_result['analytics']['total_members']} members"
            )

    else:
        print(f"❌ Project creation failed: {result.get('message', 'Unknown error')}")

    # Cleanup
    service.cleanup()


if __name__ == "__main__":
    example_usage()
