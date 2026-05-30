"""
AI-powered API endpoints for Flask-AppBuilder collaborative features.

Provides REST API endpoints for chatbot interactions, RAG queries,
and knowledge base management with proper authentication and permissions.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, AsyncIterator

from flask import request, g, jsonify, Response
from flask_appbuilder.api import BaseApi, expose, protect, safe
from flask_appbuilder.security.decorators import has_access
from marshmallow import Schema, fields, ValidationError, validate
from werkzeug.exceptions import BadRequest, NotFound, Forbidden

from ..utils.async_bridge import AsyncServiceMixin
from ..utils.error_handling import ErrorHandlingMixin, CollaborativeError, ErrorType
from ..utils.audit_logging import CollaborativeAuditMixin, AuditEventType
from ..utils.validation import ValidationHelper
from ..ai.chatbot_service import ChatbotService, ChatbotConfig, ChatbotPersonality, ConversationStatus
from ..ai.knowledge_base import KnowledgeBaseManager, ContentSource
from ..ai.ai_models import ModelManager

logger = logging.getLogger(__name__)


# Request/Response Schemas
class ChatbotConfigSchema(Schema):
    """Schema for chatbot configuration."""
    personality = fields.Str(validate=validate.OneOf([p.value for p in ChatbotPersonality]))
    model_name = fields.Str(allow_none=True)
    temperature = fields.Float(validate=validate.Range(min=0.0, max=2.0))
    max_tokens = fields.Int(validate=validate.Range(min=1, max=8000))
    enable_rag = fields.Bool()
    max_context_messages = fields.Int(validate=validate.Range(min=1, max=50))
    streaming_enabled = fields.Bool()
    custom_instructions = fields.Str(allow_none=True, validate=validate.Length(max=2000))
    workspace_aware = fields.Bool()


class ConversationCreateSchema(Schema):
    """Schema for creating new conversations."""
    title = fields.Str(validate=validate.Length(max=255))
    workspace_id = fields.Int(allow_none=True)
    team_id = fields.Int(allow_none=True)
    config = fields.Nested(ChatbotConfigSchema, allow_none=True)


class MessageSendSchema(Schema):
    """Schema for sending messages."""
    message = fields.Str(required=True, validate=validate.Length(min=1, max=4000))
    streaming = fields.Bool(missing=False)


class KnowledgeBaseIndexSchema(Schema):
    """Schema for knowledge base indexing requests."""
    content_id = fields.Str(required=True)
    content_source = fields.Str(required=True, validate=validate.OneOf([s.value for s in ContentSource]))
    content_text = fields.Str(required=True, validate=validate.Length(min=1))
    metadata = fields.Dict(allow_none=True)
    force_reindex = fields.Bool(missing=False)


class KnowledgeBaseSearchSchema(Schema):
    """Schema for knowledge base search requests."""
    query = fields.Str(required=True, validate=validate.Length(min=1, max=500))
    content_sources = fields.List(
        fields.Str(validate=validate.OneOf([s.value for s in ContentSource])),
        allow_none=True
    )
    limit = fields.Int(validate=validate.Range(min=1, max=50), missing=10)


class AIApi(BaseApi, ErrorHandlingMixin, CollaborativeAuditMixin, AsyncServiceMixin):
    """
    AI-powered API endpoints for chatbot and knowledge base functionality.
    
    Provides comprehensive AI assistance including:
    - Conversational AI chatbot with multiple personalities
    - RAG-powered knowledge base queries
    - Content indexing and search capabilities
    - Real-time streaming responses
    """
    
    route_base = "/ai"
    resource_name = "ai"
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self._chatbot_service: Optional[ChatbotService] = None
        self._knowledge_base_manager: Optional[KnowledgeBaseManager] = None
        self._model_manager: Optional[ModelManager] = None
    
    @property
    def chatbot_service(self) -> ChatbotService:
        """Get chatbot service instance."""
        if self._chatbot_service is None:
            if hasattr(self.appbuilder, 'collaborative_addon_manager'):
                addon_manager = self.appbuilder.collaborative_addon_manager
                try:
                    self._chatbot_service = addon_manager.service_registry.get_service(ChatbotService)
                except Exception as e:
                    raise CollaborativeError(
                        "Chatbot service not available",
                        ErrorType.SERVICE_ERROR,
                        context={"error": str(e)}
                    )
            else:
                raise CollaborativeError(
                    "Collaborative services not initialized",
                    ErrorType.CONFIGURATION_ERROR
                )
        return self._chatbot_service
    
    @property
    def knowledge_base_manager(self) -> KnowledgeBaseManager:
        """Get knowledge base manager instance."""
        if self._knowledge_base_manager is None:
            if hasattr(self.appbuilder, 'collaborative_addon_manager'):
                addon_manager = self.appbuilder.collaborative_addon_manager
                try:
                    self._knowledge_base_manager = addon_manager.service_registry.get_service(KnowledgeBaseManager)
                except Exception as e:
                    raise CollaborativeError(
                        "Knowledge base service not available",
                        ErrorType.SERVICE_ERROR,
                        context={"error": str(e)}
                    )
            else:
                raise CollaborativeError(
                    "Collaborative services not initialized",
                    ErrorType.CONFIGURATION_ERROR
                )
        return self._knowledge_base_manager
    
    @property
    def model_manager(self) -> ModelManager:
        """Get AI model manager instance."""
        if self._model_manager is None:
            if hasattr(self.appbuilder, 'collaborative_addon_manager'):
                addon_manager = self.appbuilder.collaborative_addon_manager
                try:
                    self._model_manager = addon_manager.service_registry.get_service(ModelManager)
                except Exception as e:
                    raise CollaborativeError(
                        "AI model manager not available",
                        ErrorType.SERVICE_ERROR,
                        context={"error": str(e)}
                    )
            else:
                raise CollaborativeError(
                    "Collaborative services not initialized",
                    ErrorType.CONFIGURATION_ERROR
                )
        return self._model_manager
    
    @expose('/models', methods=['GET'])
    @protect()
    @safe
    def list_available_models(self):
        """
        List available AI models.
        
        ---
        get:
          description: Get list of available AI models and their capabilities
          responses:
            200:
              description: Available models retrieved successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      models:
                        type: array
                        items:
                          type: object
                          properties:
                            name:
                              type: string
                            provider:
                              type: string
                            capabilities:
                              type: array
                              items:
                                type: string
                            is_default:
                              type: boolean
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
        """
        try:
            available_models = self.model_manager.list_available_adapters()
            
            models_info = []
            for model_name in available_models:
                adapter = self.model_manager.get_adapter(model_name)
                models_info.append({
                    "name": model_name,
                    "provider": adapter.config.provider.value,
                    "model_id": adapter.config.model_name,
                    "capabilities": ["chat", "streaming"],
                    "is_default": model_name == self.model_manager.default_adapter
                })
            
            return self.response({
                "models": models_info,
                "total": len(models_info)
            })
            
        except CollaborativeError as e:
            self.logger.error(f"Error listing AI models: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error listing AI models: {e}")
            return self.response_500(message="Internal server error")
    
    @expose('/conversation', methods=['POST'])
    @protect()
    @safe
    def create_conversation(self):
        """
        Create a new AI conversation.
        
        ---
        post:
          description: Create a new AI chatbot conversation
          requestBody:
            required: true
            content:
              application/json:
                schema: ConversationCreateSchema
          responses:
            201:
              description: Conversation created successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      conversation_id:
                        type: string
                      title:
                        type: string
                      workspace_id:
                        type: integer
                      config:
                        type: object
                      created_at:
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
            # Validate request data
            schema = ConversationCreateSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)
            
            # Check workspace access if workspace_id provided
            workspace_id = json_data.get("workspace_id")
            if workspace_id:
                if not self.appbuilder.sm.has_access("can_read", f"workspace_{workspace_id}"):
                    self.audit_security_event(
                        AuditEventType.PERMISSION_DENIED,
                        user_id=g.user.id if g.user else None,
                        resource_type="workspace",
                        resource_id=str(workspace_id),
                        outcome="failure"
                    )
                    return self.response_403(message="Access denied to workspace")
            
            # Create chatbot config
            config = None
            if json_data.get("config"):
                config = ChatbotConfig.from_dict(json_data["config"])
            
            # Create conversation
            conversation_id = self.call_async_service(
                self.chatbot_service.create_conversation,
                user_id=g.user.id if g.user else None,
                workspace_id=workspace_id,
                team_id=json_data.get("team_id"),
                config=config,
                title=json_data.get("title")
            )
            
            # Audit conversation creation
            self.audit_user_action(
                "ai_conversation_created",
                user_id=g.user.id if g.user else None,
                resource_type="ai_conversation",
                resource_id=conversation_id,
                outcome="success"
            )
            
            response_data = {
                "conversation_id": conversation_id,
                "title": json_data.get("title", f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
                "workspace_id": workspace_id,
                "team_id": json_data.get("team_id"),
                "config": config.to_dict() if config else ChatbotConfig().to_dict(),
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
                "message": "AI conversation created successfully"
            }
            
            return self.response(response_data, 201)
            
        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in create_conversation: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in create_conversation: {e}")
            return self.response_500(message="Internal server error")
    
    @expose('/conversation/<conversation_id>/message', methods=['POST'])
    @protect()
    @safe
    def send_message(self, conversation_id: str):
        """
        Send message to AI chatbot.
        
        ---
        post:
          description: Send a message to AI chatbot and get response
          parameters:
          - in: path
            schema:
              type: string
            name: conversation_id
          requestBody:
            required: true
            content:
              application/json:
                schema: MessageSendSchema
          responses:
            200:
              description: Message sent and response received
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      message_id:
                        type: string
                      response:
                        type: string
                      model_used:
                        type: string
                      tokens_used:
                        type: integer
                      response_time:
                        type: number
                      confidence_score:
                        type: number
                      sources:
                        type: array
                        items:
                          type: object
                text/plain:
                  description: Streaming response (when streaming=true)
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            # Validate request data
            schema = MessageSendSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)
            
            # Validate conversation ID
            validation_result = ValidationHelper.validate_string_length(
                conversation_id, min_length=1, max_length=100
            )
            if not validation_result.is_valid:
                return self.response_400(message=validation_result.error_message)
            
            # Send message to chatbot
            result = self.call_async_service(
                self.chatbot_service.send_message,
                conversation_id=conversation_id,
                user_message=json_data["message"],
                user_id=g.user.id if g.user else None,
                streaming=json_data.get("streaming", False)
            )
            
            # Handle streaming response
            if result.get("streaming") and "stream_generator" in result:
                def generate():
                    try:
                        for chunk in result["stream_generator"]:
                            if chunk.get("type") == "token":
                                yield f"data: {chunk.get('content', '')}\n\n"
                            elif chunk.get("type") == "start":
                                yield f"event: start\ndata: {chunk.get('message_id', '')}\n\n"
                            elif chunk.get("type") == "end":
                                yield f"event: end\ndata: {chunk.get('message_id', '')}\n\n"
                            elif chunk.get("type") == "error":
                                yield f"event: error\ndata: {chunk.get('error', 'Unknown error')}\n\n"
                                break
                    except Exception as e:
                        yield f"event: error\ndata: {str(e)}\n\n"
                
                return Response(
                    generate(),
                    mimetype='text/plain',
                    headers={
                        'Cache-Control': 'no-cache',
                        'Connection': 'keep-alive'
                    }
                )
            
            # Handle regular response
            if "error" in result:
                return self.response_400(message=result["error"])
            
            # Audit message sent
            self.audit_user_action(
                "ai_message_sent",
                user_id=g.user.id if g.user else None,
                resource_type="ai_conversation",
                resource_id=conversation_id,
                outcome="success"
            )
            
            return self.response({
                "conversation_id": result["conversation_id"],
                "message_id": result.get("message_id"),
                "response": result.get("response", ""),
                "model_used": result.get("model_used"),
                "tokens_used": result.get("tokens_used", 0),
                "response_time": result.get("response_time", 0),
                "confidence_score": result.get("confidence_score"),
                "sources": result.get("sources", [])
            })
            
        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in send_message: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in send_message: {e}")
            return self.response_500(message="Internal server error")
    
    @expose('/knowledge/index', methods=['POST'])
    @protect()
    @safe
    def index_content(self):
        """
        Index content in knowledge base.
        
        ---
        post:
          description: Add content to the knowledge base for RAG
          requestBody:
            required: true
            content:
              application/json:
                schema: KnowledgeBaseIndexSchema
          responses:
            200:
              description: Content indexed successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      status:
                        type: string
                      chunks_created:
                        type: integer
                      message:
                        type: string
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
        """
        try:
            # Validate request data
            schema = KnowledgeBaseIndexSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)
            
            # Get workspace context from request or user context
            workspace_id = request.args.get('workspace_id', type=int)
            team_id = request.args.get('team_id', type=int)
            
            # Check workspace access if provided
            if workspace_id:
                if not self.appbuilder.sm.has_access("can_edit", f"workspace_{workspace_id}"):
                    return self.response_403(message="Access denied to workspace")
            
            # Index content
            result = self.call_async_service(
                self.knowledge_base_manager.index_content,
                content_id=json_data["content_id"],
                content_source=ContentSource(json_data["content_source"]),
                content_text=json_data["content_text"],
                workspace_id=workspace_id,
                team_id=team_id,
                user_id=g.user.id if g.user else None,
                metadata=json_data.get("metadata"),
                force_reindex=json_data.get("force_reindex", False)
            )
            
            # Audit content indexing
            self.audit_user_action(
                "knowledge_content_indexed",
                user_id=g.user.id if g.user else None,
                resource_type="knowledge_base",
                resource_id=json_data["content_id"],
                outcome="success" if result["status"] in ["success", "skipped"] else "error"
            )
            
            return self.response(result)
            
        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in index_content: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in index_content: {e}")
            return self.response_500(message="Internal server error")
    
    @expose('/knowledge/search', methods=['POST'])
    @protect()
    @safe
    def search_knowledge_base(self):
        """
        Search knowledge base content.
        
        ---
        post:
          description: Search indexed content using semantic similarity
          requestBody:
            required: true
            content:
              application/json:
                schema: KnowledgeBaseSearchSchema
          responses:
            200:
              description: Search completed successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      results:
                        type: array
                        items:
                          type: object
                      total_found:
                        type: integer
                      confidence:
                        type: number
                      query:
                        type: string
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
        """
        try:
            # Validate request data
            schema = KnowledgeBaseSearchSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)
            
            # Get workspace context
            workspace_id = request.args.get('workspace_id', type=int)
            
            # Check workspace access if provided
            if workspace_id:
                if not self.appbuilder.sm.has_access("can_read", f"workspace_{workspace_id}"):
                    return self.response_403(message="Access denied to workspace")
            
            # Convert content sources
            content_sources = None
            if json_data.get("content_sources"):
                content_sources = [ContentSource(source) for source in json_data["content_sources"]]
            
            # Search knowledge base
            result = self.call_async_service(
                self.knowledge_base_manager.search_content,
                query=json_data["query"],
                workspace_id=workspace_id,
                content_sources=content_sources,
                limit=json_data.get("limit", 10)
            )
            
            # Audit search
            self.audit_user_action(
                "knowledge_search_performed",
                user_id=g.user.id if g.user else None,
                resource_type="knowledge_base",
                outcome="success" if result["status"] == "success" else "error",
                details={"query": json_data["query"], "results_found": result.get("total_found", 0)}
            )
            
            return self.response({
                "results": result.get("results", []),
                "total_found": result.get("total_found", 0),
                "confidence": result.get("confidence", 0.0),
                "query": json_data["query"],
                "status": result.get("status", "success")
            })
            
        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in search_knowledge_base: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in search_knowledge_base: {e}")
            return self.response_500(message="Internal server error")
    
    @expose('/knowledge/stats', methods=['GET'])
    @protect()
    @safe
    def get_knowledge_base_stats(self):
        """
        Get knowledge base statistics.
        
        ---
        get:
          description: Get indexing and usage statistics for knowledge base
          parameters:
          - in: query
            name: workspace_id
            schema:
              type: integer
          responses:
            200:
              description: Statistics retrieved successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      stats:
                        type: object
                      queue_size:
                        type: integer
                      active_tasks:
                        type: integer
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
        """
        try:
            workspace_id = request.args.get('workspace_id', type=int)
            
            # Check workspace access if provided
            if workspace_id:
                if not self.appbuilder.sm.has_access("can_read", f"workspace_{workspace_id}"):
                    return self.response_403(message="Access denied to workspace")
            
            # Get statistics
            result = self.call_async_service(
                self.knowledge_base_manager.get_indexing_stats,
                workspace_id=workspace_id
            )
            
            return self.response(result)
            
        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in get_knowledge_base_stats: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in get_knowledge_base_stats: {e}")
            return self.response_500(message="Internal server error")