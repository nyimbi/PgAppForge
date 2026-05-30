"""
Communication API endpoints for Flask-AppBuilder collaborative features.

Provides RESTful APIs for chat, comments, notifications, and other
communication features within collaborative workspaces.
"""

import logging
from typing import Any, Dict, List, Optional
from flask import request, jsonify, g
from flask_appbuilder import expose
from flask_appbuilder.api import BaseApi, safe
from flask_appbuilder.security.decorators import protect
from marshmallow import Schema, fields, ValidationError
from datetime import datetime, timezone

from ..interfaces.base_interfaces import ICommunicationService
from ..communication.notification_manager import NotificationType, NotificationPriority
from ..utils.validation import ValidationHelper, ValidationResult
from ..utils.error_handling import CollaborativeError, ErrorType, ErrorHandlingMixin
from ..utils.audit_logging import CollaborativeAuditMixin, AuditEventType
from ..utils.async_bridge import AsyncServiceMixin


class ChatMessageSchema(Schema):
    """Schema for sending chat messages."""
    channel_id = fields.Int(required=True, validate=ValidationHelper.validate_channel_id)
    content = fields.Str(required=True, validate=ValidationHelper.validate_message_content)
    message_type = fields.Str(missing="text", validate=lambda x: x in ["text", "image", "file", "code"])
    metadata = fields.Dict(missing=dict)


class ChatChannelSchema(Schema):
    """Schema for creating chat channels."""
    workspace_id = fields.Int(required=True, validate=ValidationHelper.validate_workspace_id)
    name = fields.Str(required=True, validate=ValidationHelper.validate_channel_name)
    description = fields.Str(missing="")
    is_private = fields.Bool(missing=False)
    settings = fields.Dict(missing=dict)


class CommentThreadSchema(Schema):
    """Schema for creating comment threads."""
    workspace_id = fields.Int(required=True, validate=ValidationHelper.validate_workspace_id)
    commentable_type = fields.Str(required=True, validate=lambda x: x in ["document", "task", "resource", "general"])
    commentable_id = fields.Str(required=True, validate=ValidationHelper.validate_resource_id)
    initial_comment = fields.Str(required=True, validate=ValidationHelper.validate_message_content)
    metadata = fields.Dict(missing=dict)


class CommentReplySchema(Schema):
    """Schema for adding comment replies."""
    content = fields.Str(required=True, validate=ValidationHelper.validate_message_content)
    parent_comment_id = fields.Int()
    metadata = fields.Dict(missing=dict)


class NotificationSchema(Schema):
    """Schema for sending notifications."""
    user_id = fields.Int(required=True, validate=ValidationHelper.validate_user_id)
    notification_type = fields.Str(required=True, validate=lambda x: x in [t.value for t in NotificationType])
    title = fields.Str(required=True, validate=lambda x: len(x.strip()) >= 1 and len(x) <= 100)
    message = fields.Str(required=True, validate=ValidationHelper.validate_message_content)
    priority = fields.Str(missing="normal", validate=lambda x: x in [p.value for p in NotificationPriority])
    metadata = fields.Dict(missing=dict)


class CommunicationApi(BaseApi, ErrorHandlingMixin, CollaborativeAuditMixin, AsyncServiceMixin):
    """
    RESTful API for communication features.
    
    Provides endpoints for chat, comments, notifications, and other
    communication capabilities within collaborative workspaces.
    """

    resource_name = "communication"
    datamodel = None  # No direct model binding for communication API
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(f'{self.__class__.__module__}.{self.__class__.__name__}')
        self._communication_service: Optional[ICommunicationService] = None

    @property
    def communication_service(self) -> ICommunicationService:
        """Get communication service from addon manager."""
        if self._communication_service is None:
            if hasattr(self.appbuilder, 'collaborative_services'):
                try:
                    self._communication_service = self.appbuilder.collaborative_services.get_service(ICommunicationService)
                except Exception as e:
                    raise CollaborativeError(
                        "Communication service not available",
                        ErrorType.SERVICE_ERROR,
                        context={"error": str(e)}
                    )
            else:
                raise CollaborativeError(
                    "Collaborative services not initialized",
                    ErrorType.CONFIGURATION_ERROR
                )
        return self._communication_service

    @expose('/chat/message', methods=['POST'])
    @protect()
    @safe
    def send_chat_message(self):
        """
        Send a chat message to a channel.
        
        ---
        post:
          description: >-
            Send a chat message to a specific channel
          requestBody:
            required: true
            content:
              application/json:
                schema: ChatMessageSchema
          responses:
            201:
              description: Message sent successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      message_id:
                        type: integer
                      channel_id:
                        type: integer
                      sender_id:
                        type: integer
                      content:
                        type: string
                      sent_at:
                        type: string
                        format: date-time
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            # Validate request data
            schema = ChatMessageSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            channel_id = json_data["channel_id"]
            
            # Check if user has access to send messages in this channel
            # This would need to be implemented in the communication service
            # if not self.communication_service.can_send_message(g.user.id, channel_id):
            #     return self.response_403(message="Access denied to send messages in this channel")

            # Send chat message
            message = self.call_async_service(
                self.communication_service.send_chat_message,
                channel_id=channel_id,
                sender_id=g.user.id if g.user else None,
                content=json_data["content"],
                message_type=json_data.get("message_type", "text"),
                metadata=json_data.get("metadata", {})
            )

            if not message:
                return self.response_400(message="Failed to send message")

            # Audit message sending
            self.audit_user_action(
                "chat_message_sent",
                user_id=g.user.id if g.user else None,
                resource_type="chat_channel",
                resource_id=str(channel_id),
                outcome="success"
            )

            response_data = {
                "message_id": message.id if hasattr(message, 'id') else None,
                "channel_id": channel_id,
                "sender_id": g.user.id if g.user else None,
                "content": json_data["content"],
                "message_type": json_data.get("message_type", "text"),
                "sent_at": datetime.now(tz=timezone.utc).isoformat(),
                "message": "Message sent successfully"
            }

            return self.response(response_data, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in send_chat_message: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in send_chat_message: {e}")
            return self.response_500(message="Internal server error")

    @expose('/chat/channel', methods=['POST'])
    @protect()
    @safe
    def create_chat_channel(self):
        """
        Create a new chat channel.
        
        ---
        post:
          description: >-
            Create a new chat channel in a workspace
          requestBody:
            required: true
            content:
              application/json:
                schema: ChatChannelSchema
          responses:
            201:
              description: Channel created successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      channel_id:
                        type: integer
                      name:
                        type: string
                      workspace_id:
                        type: integer
                      created_by:
                        type: integer
                      created_at:
                        type: string
                        format: date-time
                      member_count:
                        type: integer
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
        """
        try:
            # Validate request data
            schema = ChatChannelSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            workspace_id = json_data["workspace_id"]

            # Check if user has permission to create channels in this workspace
            if not self.appbuilder.sm.has_access("can_create_channel", f"workspace_{workspace_id}"):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="workspace",
                    resource_id=str(workspace_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to create channels in this workspace")

            # Create chat channel
            channel = self.call_async_service(
                self.communication_service.create_chat_channel,
                workspace_id=workspace_id,
                name=json_data["name"],
                description=json_data.get("description", ""),
                created_by_id=g.user.id if g.user else None,
                is_private=json_data.get("is_private", False),
                settings=json_data.get("settings", {})
            )

            if not channel:
                return self.response_400(message="Failed to create chat channel")

            # Audit channel creation
            self.audit_user_action(
                "chat_channel_created",
                user_id=g.user.id if g.user else None,
                resource_type="chat_channel",
                resource_id=str(channel.id) if hasattr(channel, 'id') else None,
                outcome="success"
            )

            response_data = {
                "channel_id": channel.id if hasattr(channel, 'id') else None,
                "name": json_data["name"],
                "workspace_id": workspace_id,
                "created_by": g.user.id if g.user else None,
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
                "member_count": 1,  # Creator is automatically a member
                "message": "Chat channel created successfully"
            }

            return self.response(response_data, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in create_chat_channel: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in create_chat_channel: {e}")
            return self.response_500(message="Internal server error")

    @expose('/comment/thread', methods=['POST'])
    @protect()
    @safe
    def create_comment_thread(self):
        """
        Create a new comment thread.
        
        ---
        post:
          description: >-
            Create a new comment thread for a specific resource
          requestBody:
            required: true
            content:
              application/json:
                schema: CommentThreadSchema
          responses:
            201:
              description: Comment thread created successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      thread_id:
                        type: integer
                      workspace_id:
                        type: integer
                      commentable_type:
                        type: string
                      commentable_id:
                        type: string
                      created_by:
                        type: integer
                      created_at:
                        type: string
                        format: date-time
                      comment_count:
                        type: integer
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
        """
        try:
            # Validate request data
            schema = CommentThreadSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            workspace_id = json_data["workspace_id"]

            # Check if user has permission to comment in this workspace
            if not self.appbuilder.sm.has_access("can_comment", f"workspace_{workspace_id}"):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="workspace",
                    resource_id=str(workspace_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to comment in this workspace")

            # Create comment thread
            thread = self.call_async_service(
                self.communication_service.create_comment_thread,
                workspace_id=workspace_id,
                commentable_type=json_data["commentable_type"],
                commentable_id=json_data["commentable_id"],
                created_by_id=g.user.id if g.user else None,
                initial_comment=json_data["initial_comment"],
                metadata=json_data.get("metadata", {})
            )

            if not thread:
                return self.response_400(message="Failed to create comment thread")

            # Audit thread creation
            self.audit_user_action(
                "comment_thread_created",
                user_id=g.user.id if g.user else None,
                resource_type="comment_thread",
                resource_id=str(thread.id) if hasattr(thread, 'id') else None,
                outcome="success"
            )

            response_data = {
                "thread_id": thread.id if hasattr(thread, 'id') else None,
                "workspace_id": workspace_id,
                "commentable_type": json_data["commentable_type"],
                "commentable_id": json_data["commentable_id"],
                "created_by": g.user.id if g.user else None,
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
                "comment_count": 1,  # Initial comment
                "message": "Comment thread created successfully"
            }

            return self.response(response_data, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in create_comment_thread: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in create_comment_thread: {e}")
            return self.response_500(message="Internal server error")

    @expose('/comment/thread/<int:thread_id>/reply', methods=['POST'])
    @protect()
    @safe
    def add_comment_reply(self, thread_id: int):
        """
        Add a reply to a comment thread.
        
        ---
        post:
          description: >-
            Add a reply to an existing comment thread
          parameters:
          - in: path
            schema:
              type: integer
            name: thread_id
          requestBody:
            required: true
            content:
              application/json:
                schema: CommentReplySchema
          responses:
            201:
              description: Reply added successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      comment_id:
                        type: integer
                      thread_id:
                        type: integer
                      author_id:
                        type: integer
                      content:
                        type: string
                      created_at:
                        type: string
                        format: date-time
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            # Validate request data
            schema = CommentReplySchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            # Check if user has permission to reply to this thread
            # This would need to be implemented in the communication service
            # if not self.communication_service.can_reply_to_thread(g.user.id, thread_id):
            #     return self.response_403(message="Access denied to reply to this thread")

            # Add comment reply
            comment = self.call_async_service(
                self.communication_service.add_comment_reply,
                thread_id=thread_id,
                author_id=g.user.id if g.user else None,
                content=json_data["content"],
                parent_comment_id=json_data.get("parent_comment_id"),
                metadata=json_data.get("metadata", {})
            )

            if not comment:
                return self.response_400(message="Failed to add comment reply")

            # Audit comment reply
            self.audit_user_action(
                "comment_reply_added",
                user_id=g.user.id if g.user else None,
                resource_type="comment_thread",
                resource_id=str(thread_id),
                outcome="success"
            )

            response_data = {
                "comment_id": comment.id if hasattr(comment, 'id') else None,
                "thread_id": thread_id,
                "author_id": g.user.id if g.user else None,
                "content": json_data["content"],
                "parent_comment_id": json_data.get("parent_comment_id"),
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
                "message": "Reply added successfully"
            }

            return self.response(response_data, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in add_comment_reply: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in add_comment_reply: {e}")
            return self.response_500(message="Internal server error")

    @expose('/notification', methods=['POST'])
    @protect()
    @safe
    def send_notification(self):
        """
        Send a notification to a user.
        
        ---
        post:
          description: >-
            Send a notification to a specific user
          requestBody:
            required: true
            content:
              application/json:
                schema: NotificationSchema
          responses:
            201:
              description: Notification sent successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      notification_id:
                        type: integer
                      user_id:
                        type: integer
                      notification_type:
                        type: string
                      title:
                        type: string
                      sent_at:
                        type: string
                        format: date-time
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
        """
        try:
            # Check if user has permission to send notifications
            if not self.appbuilder.sm.has_access("can_send_notification", "Notification"):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="notification",
                    resource_id=None,
                    outcome="failure"
                )
                return self.response_403(message="Access denied to send notifications")

            # Validate request data
            schema = NotificationSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            # Send notification
            notification = self.call_async_service(
                self.communication_service.send_notification,
                user_id=json_data["user_id"],
                notification_type=NotificationType(json_data["notification_type"]),
                title=json_data["title"],
                message=json_data["message"],
                priority=NotificationPriority(json_data.get("priority", "normal")),
                sender_id=g.user.id if g.user else None,
                metadata=json_data.get("metadata", {})
            )

            if not notification:
                return self.response_400(message="Failed to send notification")

            # Audit notification sending
            self.audit_user_action(
                "notification_sent",
                user_id=g.user.id if g.user else None,
                resource_type="notification",
                resource_id=str(notification.id) if hasattr(notification, 'id') else None,
                outcome="success",
                target_user_id=json_data["user_id"]
            )

            response_data = {
                "notification_id": notification.id if hasattr(notification, 'id') else None,
                "user_id": json_data["user_id"],
                "notification_type": json_data["notification_type"],
                "title": json_data["title"],
                "priority": json_data.get("priority", "normal"),
                "sent_at": datetime.now(tz=timezone.utc).isoformat(),
                "message": "Notification sent successfully"
            }

            return self.response(response_data, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in send_notification: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in send_notification: {e}")
            return self.response_500(message="Internal server error")

    @expose('/chat/channel/<int:channel_id>/messages', methods=['GET'])
    @protect()
    @safe
    def get_chat_messages(self, channel_id: int):
        """
        Get chat messages from a channel.
        
        ---
        get:
          description: >-
            Get chat messages from a specific channel
          parameters:
          - in: path
            schema:
              type: integer
            name: channel_id
          - in: query
            name: page
            schema:
              type: integer
              default: 1
          - in: query
            name: page_size
            schema:
              type: integer
              default: 50
          - in: query
            name: since
            schema:
              type: string
              format: date-time
          responses:
            200:
              description: Chat messages retrieved successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      channel_id:
                        type: integer
                      messages:
                        type: array
                        items:
                          type: object
                      total:
                        type: integer
                      page:
                        type: integer
                      page_size:
                        type: integer
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
        """
        try:
            # Check if user has access to read messages from this channel
            # This would need to be implemented in the communication service
            # if not self.communication_service.can_read_channel(g.user.id, channel_id):
            #     return self.response_403(message="Access denied to read messages from this channel")

            # Get pagination parameters
            page = request.args.get('page', 1, type=int)
            page_size = min(request.args.get('page_size', 50, type=int), 100)
            since = request.args.get('since')

            # Get messages (this would need to be implemented in the service)
            # messages = self.call_async_service(
                # self.communication_service.get_chat_messages,
            #     channel_id=channel_id,
            #     page=page,
            #     page_size=page_size,
            #     since=since
            # )

            # Placeholder response
            response_data = {
                "channel_id": channel_id,
                "messages": [],  # Would contain actual messages
                "total": 0,
                "page": page,
                "page_size": page_size,
                "total_pages": 0
            }

            return self.response(response_data)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in get_chat_messages: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in get_chat_messages: {e}")
            return self.response_500(message="Internal server error")

    @expose('/workspace/<int:workspace_id>/summary', methods=['GET'])
    @protect()
    @safe
    def get_communication_summary(self, workspace_id: int):
        """
        Get communication activity summary for a workspace.
        
        ---
        get:
          description: >-
            Get communication activity summary for a workspace
          parameters:
          - in: path
            schema:
              type: integer
            name: workspace_id
          - in: query
            name: days
            schema:
              type: integer
              default: 7
          responses:
            200:
              description: Communication summary retrieved successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      workspace_id:
                        type: integer
                      period_days:
                        type: integer
                      chat_messages:
                        type: integer
                      comment_threads:
                        type: integer
                      notifications_sent:
                        type: integer
                      active_users:
                        type: integer
                      summary_generated_at:
                        type: string
                        format: date-time
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
        """
        try:
            # Check if user has access to this workspace
            if not self.appbuilder.sm.has_access("can_read", f"workspace_{workspace_id}"):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="workspace",
                    resource_id=str(workspace_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to workspace communication summary")

            # Get parameters
            days = min(request.args.get('days', 7, type=int), 90)  # Max 90 days

            # Get communication summary
            summary = self.call_async_service(
                self.communication_service.get_communication_summary,
                workspace_id=workspace_id,
                user_id=g.user.id if g.user else None,
                days=days
            )

            if not summary:
                return self.response_404(message="Workspace not found or no communication data")

            return self.response(summary)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in get_communication_summary: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in get_communication_summary: {e}")
            return self.response_500(message="Internal server error")