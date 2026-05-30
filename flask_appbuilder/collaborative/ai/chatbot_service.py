"""
AI Chatbot service for Flask-AppBuilder collaborative features.

Provides intelligent conversational AI that can answer questions about workspace
content, assist with tasks, and provide contextual help using RAG capabilities.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, AsyncIterator, Callable

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey, JSON
from sqlalchemy.orm import relationship
from flask_appbuilder.models.sqla import Model
from flask_appbuilder.models.mixins import AuditMixin

from .ai_models import AIModelAdapter, ChatMessage, ModelResponse, ModelManager
from .types import DocumentType
from .rag_engine import RAGEngine
from .security import get_security_manager, SecurityError, RateLimitError
from ..communication.communication_service import CommunicationService
from ..utils.validation import ValidationHelper

logger = logging.getLogger(__name__)


class ChatbotPersonality(Enum):
    """Different chatbot personalities for different contexts."""
    
    ASSISTANT = "assistant"  # Helpful general assistant
    TECHNICAL = "technical"  # Technical documentation helper
    CREATIVE = "creative"    # Creative writing assistant
    ANALYST = "analyst"      # Data analysis helper
    MENTOR = "mentor"        # Learning and guidance focused


class ConversationStatus(Enum):
    """Status of chatbot conversations."""
    
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass
class ChatbotConfig:
    """Configuration for chatbot behavior."""
    
    personality: ChatbotPersonality = ChatbotPersonality.ASSISTANT
    model_name: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    enable_rag: bool = True
    max_context_messages: int = 10
    response_timeout: int = 30
    streaming_enabled: bool = True
    custom_instructions: Optional[str] = None
    workspace_aware: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "personality": self.personality.value,
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "enable_rag": self.enable_rag,
            "max_context_messages": self.max_context_messages,
            "response_timeout": self.response_timeout,
            "streaming_enabled": self.streaming_enabled,
            "custom_instructions": self.custom_instructions,
            "workspace_aware": self.workspace_aware
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatbotConfig":
        """Create from dictionary."""
        return cls(
            personality=ChatbotPersonality(data.get("personality", "assistant")),
            model_name=data.get("model_name"),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 2048),
            enable_rag=data.get("enable_rag", True),
            max_context_messages=data.get("max_context_messages", 10),
            response_timeout=data.get("response_timeout", 30),
            streaming_enabled=data.get("streaming_enabled", True),
            custom_instructions=data.get("custom_instructions"),
            workspace_aware=data.get("workspace_aware", True)
        )


class ChatbotConversation(Model, AuditMixin):
    """Chatbot conversation storage with Flask-AppBuilder integration."""
    
    __tablename__ = "fab_chatbot_conversations"
    
    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Context information
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"))
    team_id = Column(Integer, ForeignKey("fab_teams.id"))
    user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    
    # Conversation metadata
    title = Column(String(255))
    status = Column(String(20), default=ConversationStatus.ACTIVE.value)
    config = Column(JSON)  # ChatbotConfig as JSON
    
    # Statistics
    message_count = Column(Integer, default=0)
    last_activity = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    messages = relationship("ChatbotMessage", back_populates="conversation", cascade="all, delete-orphan")
    
    def get_config(self) -> ChatbotConfig:
        """Get conversation configuration."""
        if self.config:
            return ChatbotConfig.from_dict(self.config)
        return ChatbotConfig()
    
    def set_config(self, config: ChatbotConfig):
        """Set conversation configuration."""
        self.config = config.to_dict()


class ChatbotMessage(Model, AuditMixin):
    """Individual chatbot messages with Flask-AppBuilder integration."""
    
    __tablename__ = "fab_chatbot_messages"
    
    id = Column(Integer, primary_key=True)
    message_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Message identification
    conversation_id = Column(Integer, ForeignKey("fab_chatbot_conversations.id"), nullable=False)
    sequence_number = Column(Integer, nullable=False)
    
    # Message content
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    meta_data = Column(JSON)  # Additional message metadata
    
    # AI generation info
    model_used = Column(String(100))
    tokens_used = Column(Integer)
    response_time = Column(Float)  # seconds
    
    # RAG information
    rag_enabled = Column(Boolean, default=False)
    sources_used = Column(JSON)  # Sources used for RAG
    confidence_score = Column(Float)
    
    # Relations
    conversation = relationship("ChatbotConversation", back_populates="messages")
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get message metadata."""
        return self.meta_data or {}
    
    def get_sources_used(self) -> List[Dict[str, Any]]:
        """Get RAG sources used."""
        return self.sources_used or []


class ChatbotService:
    """Main chatbot service integrating AI models and RAG."""
    
    def __init__(
        self,
        model_manager: ModelManager,
        rag_engine: Optional[RAGEngine] = None,
        communication_service: Optional[CommunicationService] = None,
        session_factory: Optional[Callable] = None
    ):
        self.model_manager = model_manager
        self.rag_engine = rag_engine
        self.communication_service = communication_service
        self.session_factory = session_factory
        self.logger = logging.getLogger(__name__)
        
        # Personality prompts
        self.personality_prompts = {
            ChatbotPersonality.ASSISTANT: self._get_assistant_prompt(),
            ChatbotPersonality.TECHNICAL: self._get_technical_prompt(),
            ChatbotPersonality.CREATIVE: self._get_creative_prompt(),
            ChatbotPersonality.ANALYST: self._get_analyst_prompt(),
            ChatbotPersonality.MENTOR: self._get_mentor_prompt()
        }
    
    async def create_conversation(
        self,
        user_id: int,
        workspace_id: Optional[int] = None,
        team_id: Optional[int] = None,
        config: Optional[ChatbotConfig] = None,
        title: Optional[str] = None
    ) -> str:
        """Create a new chatbot conversation."""
        try:
            if not self.session_factory:
                raise RuntimeError("Database session factory not available")
            
            session = self.session_factory()
            config = config or ChatbotConfig()
            
            conversation = ChatbotConversation(
                workspace_id=workspace_id,
                team_id=team_id,
                user_id=user_id,
                title=title or f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                created_by_user_id=user_id
            )
            conversation.set_config(config)
            
            session.add(conversation)
            session.commit()
            
            conversation_id = conversation.conversation_id
            session.close()
            
            self.logger.info(f"Created chatbot conversation {conversation_id} for user {user_id}")
            return conversation_id
            
        except Exception as e:
            if 'session' in locals():
                session.rollback()
                session.close()
            self.logger.error(f"Failed to create chatbot conversation: {e}")
            raise
    
    async def send_message(
        self,
        conversation_id: str,
        user_message: str,
        user_id: int,
        streaming: bool = False
    ) -> Dict[str, Any]:
        """Send message to chatbot and get response."""
        try:
            # Get conversation
            conversation = await self._get_conversation(conversation_id, user_id)
            if not conversation:
                raise ValueError(f"Conversation {conversation_id} not found")
            
            config = conversation.get_config()
            
            # Secure validation and sanitization of user message
            security_manager = get_security_manager()

            try:
                # Validate and sanitize prompt for security
                prompt_result = security_manager.validate_and_sanitize_prompt(
                    user_message, user_id=user_id
                )

                if not prompt_result.is_valid:
                    self.logger.warning(
                        f"Invalid prompt from user {user_id}: {prompt_result.violations}"
                    )
                    raise ValueError("Message contains unsafe content or format")

                # Use sanitized prompt
                user_message = prompt_result.sanitized_prompt

                # Log security warnings if any
                if prompt_result.violations:
                    self.logger.warning(
                        f"Prompt security warnings for user {user_id}: {prompt_result.violations}"
                    )

            except RateLimitError as e:
                self.logger.warning(f"Rate limit exceeded for user {user_id}: {e}")
                raise ValueError("Too many requests. Please wait before sending another message.")
            except SecurityError as e:
                self.logger.error(f"Security error for user {user_id}: {e}")
                raise ValueError("Message rejected due to security policy")

            # Additional length validation (after sanitization)
            validation_result = ValidationHelper.validate_string_length(
                user_message, min_length=1, max_length=4000
            )
            if not validation_result.is_valid:
                raise ValueError(validation_result.error_message)
            
            # Store user message
            await self._store_message(
                conversation.id, "user", user_message, user_id
            )
            
            # Build conversation context
            context_messages = await self._build_context_messages(
                conversation.id, config.max_context_messages
            )
            
            # Add user message to context
            context_messages.append(ChatMessage(
                role="user",
                content=user_message
            ))
            
            if streaming:
                # Return streaming response
                return {
                    "conversation_id": conversation_id,
                    "streaming": True,
                    "stream_generator": self._stream_response(
                        conversation, context_messages, user_id, config
                    )
                }
            else:
                # Generate complete response
                response_data = await self._generate_response(
                    conversation, context_messages, user_id, config
                )
                
                return {
                    "conversation_id": conversation_id,
                    "message_id": response_data["message_id"],
                    "response": response_data["content"],
                    "model_used": response_data["model_used"],
                    "tokens_used": response_data["tokens_used"],
                    "response_time": response_data["response_time"],
                    "confidence_score": response_data.get("confidence_score"),
                    "sources": response_data.get("sources", []),
                    "streaming": False
                }
        
        except Exception as e:
            self.logger.error(f"Failed to send message to chatbot: {e}")
            return {
                "conversation_id": conversation_id,
                "error": str(e),
                "response": "I'm sorry, I encountered an error processing your message. Please try again."
            }
    
    async def _stream_response(
        self,
        conversation: ChatbotConversation,
        context_messages: List[ChatMessage],
        user_id: int,
        config: ChatbotConfig
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chatbot response tokens."""
        try:
            start_time = datetime.now()
            accumulated_content = ""
            
            # Prepare messages with system prompt
            messages = await self._prepare_messages_for_generation(
                context_messages, conversation, config
            )
            
            # Get AI model
            model = self.model_manager.get_adapter(config.model_name)
            
            # Generate message ID for streaming response
            message_id = str(uuid.uuid4())
            
            # Yield start of stream
            yield {
                "type": "start",
                "message_id": message_id,
                "model": model.config.model_name
            }
            
            # Stream tokens
            async for token in model.stream_chat_completion(
                messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens
            ):
                accumulated_content += token
                yield {
                    "type": "token",
                    "content": token
                }
            
            # Calculate response time
            response_time = (datetime.now() - start_time).total_seconds()
            
            # Store assistant message
            await self._store_message(
                conversation.id,
                "assistant", 
                accumulated_content,
                user_id,
                model_used=model.config.model_name,
                response_time=response_time,
                message_id=message_id
            )
            
            # Yield end of stream
            yield {
                "type": "end",
                "message_id": message_id,
                "total_tokens": len(accumulated_content.split()),  # Rough estimate
                "response_time": response_time
            }
            
        except Exception as e:
            self.logger.error(f"Streaming response failed: {e}")
            yield {
                "type": "error",
                "error": str(e)
            }
    
    async def _generate_response(
        self,
        conversation: ChatbotConversation,
        context_messages: List[ChatMessage],
        user_id: int,
        config: ChatbotConfig
    ) -> Dict[str, Any]:
        """Generate complete chatbot response."""
        start_time = datetime.now()
        
        try:
            # Prepare messages for generation
            messages = await self._prepare_messages_for_generation(
                context_messages, conversation, config
            )
            
            # Get AI model
            model = self.model_manager.get_adapter(config.model_name)
            
            # Generate response
            response = await model.chat_completion(
                messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens
            )
            
            response_time = (datetime.now() - start_time).total_seconds()
            
            # Store assistant message
            message_id = await self._store_message(
                conversation.id,
                "assistant",
                response.content,
                user_id,
                model_used=response.model,
                tokens_used=response.usage.get("total_tokens") if response.usage else None,
                response_time=response_time
            )
            
            return {
                "message_id": message_id,
                "content": response.content,
                "model_used": response.model,
                "tokens_used": response.usage.get("total_tokens") if response.usage else 0,
                "response_time": response_time
            }
            
        except Exception as e:
            self.logger.error(f"Response generation failed: {e}")
            # Store error message
            message_id = await self._store_message(
                conversation.id,
                "assistant",
                "I'm sorry, I encountered an error while processing your request. Please try again.",
                user_id,
                metadata={"error": str(e)}
            )
            
            return {
                "message_id": message_id,
                "content": "I'm sorry, I encountered an error while processing your request. Please try again.",
                "error": str(e)
            }
    
    async def _prepare_messages_for_generation(
        self,
        context_messages: List[ChatMessage],
        conversation: ChatbotConversation,
        config: ChatbotConfig
    ) -> List[ChatMessage]:
        """Prepare messages for AI model generation."""
        messages = []
        
        # Add system prompt based on personality
        system_prompt = self.personality_prompts[config.personality]
        
        # Add workspace context if enabled
        if config.workspace_aware and conversation.workspace_id:
            workspace_context = await self._get_workspace_context(conversation.workspace_id)
            if workspace_context:
                system_prompt += f"\n\nWorkspace Context:\n{workspace_context}"
        
        # Add custom instructions
        if config.custom_instructions:
            system_prompt += f"\n\nAdditional Instructions:\n{config.custom_instructions}"
        
        messages.append(ChatMessage(
            role="system",
            content=system_prompt
        ))
        
        # Add context messages
        messages.extend(context_messages)
        
        # If RAG is enabled and we have a recent user message, enhance it
        if config.enable_rag and self.rag_engine and context_messages:
            last_message = context_messages[-1]
            if last_message.role == "user":
                rag_context = await self._get_rag_context(
                    last_message.content, conversation.workspace_id
                )
                if rag_context:
                    # Replace the last user message with RAG-enhanced version
                    enhanced_content = f"{last_message.content}\n\nRelevant Information:\n{rag_context}"
                    messages[-1] = ChatMessage(
                        role="user",
                        content=enhanced_content
                    )
        
        return messages
    
    async def _get_rag_context(self, query: str, workspace_id: Optional[int]) -> Optional[str]:
        """Get RAG context for query."""
        if not self.rag_engine or not workspace_id:
            return None
        
        try:
            rag_result = await self.rag_engine.query(
                query=query,
                workspace_id=workspace_id,
                max_results=3,
                include_sources=False
            )
            
            # Extract context from retrieved chunks
            if rag_result.get("sources"):
                context_parts = []
                for source in rag_result["sources"][:3]:  # Top 3 sources
                    context_parts.append(source["content_preview"])
                
                return "\n\n".join(context_parts)
            
        except Exception as e:
            self.logger.error(f"Failed to get RAG context: {e}")
        
        return None
    
    async def _get_workspace_context(self, workspace_id: int) -> Optional[str]:
        """Get general workspace context information."""
        # This would integrate with workspace service to get basic info
        return f"You are assisting in workspace ID {workspace_id}. Focus on being helpful with workspace-related questions and tasks."
    
    async def _build_context_messages(
        self, 
        conversation_db_id: int, 
        max_messages: int
    ) -> List[ChatMessage]:
        """Build context messages from conversation history."""
        try:
            if not self.session_factory:
                return []
            
            session = self.session_factory()
            
            # Get recent messages
            messages = session.query(ChatbotMessage).filter_by(
                conversation_id=conversation_db_id
            ).order_by(
                ChatbotMessage.sequence_number.desc()
            ).limit(max_messages).all()
            
            session.close()
            
            # Convert to ChatMessage objects, reverse to chronological order
            context_messages = []
            for msg in reversed(messages):
                context_messages.append(ChatMessage(
                    role=msg.role,
                    content=msg.content,
                    metadata=msg.get_metadata()
                ))
            
            return context_messages
            
        except Exception as e:
            self.logger.error(f"Failed to build context messages: {e}")
            return []
    
    async def _store_message(
        self,
        conversation_db_id: int,
        role: str,
        content: str,
        user_id: int,
        model_used: Optional[str] = None,
        tokens_used: Optional[int] = None,
        response_time: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None
    ) -> str:
        """Store message in database."""
        try:
            if not self.session_factory:
                raise RuntimeError("Database session factory not available")
            
            session = self.session_factory()
            
            # Get next sequence number
            last_message = session.query(ChatbotMessage).filter_by(
                conversation_id=conversation_db_id
            ).order_by(ChatbotMessage.sequence_number.desc()).first()
            
            sequence_number = (last_message.sequence_number + 1) if last_message else 1
            
            message = ChatbotMessage(
                message_id=message_id or str(uuid.uuid4()),
                conversation_id=conversation_db_id,
                sequence_number=sequence_number,
                role=role,
                content=content,
                model_used=model_used,
                tokens_used=tokens_used,
                response_time=response_time,
                metadata=metadata,
                created_by_user_id=user_id
            )
            
            session.add(message)
            
            # Update conversation stats
            conversation = session.query(ChatbotConversation).get(conversation_db_id)
            if conversation:
                conversation.message_count = sequence_number
                conversation.last_activity = datetime.now(tz=timezone.utc)
            
            session.commit()
            stored_message_id = message.message_id
            session.close()
            
            return stored_message_id
            
        except Exception as e:
            if 'session' in locals():
                session.rollback()
                session.close()
            self.logger.error(f"Failed to store message: {e}")
            raise
    
    async def _get_conversation(
        self, 
        conversation_id: str, 
        user_id: int
    ) -> Optional[ChatbotConversation]:
        """Get conversation by ID and user."""
        try:
            if not self.session_factory:
                return None
            
            session = self.session_factory()
            
            conversation = session.query(ChatbotConversation).filter_by(
                conversation_id=conversation_id,
                user_id=user_id
            ).first()
            
            session.close()
            return conversation
            
        except Exception as e:
            self.logger.error(f"Failed to get conversation: {e}")
            return None
    
    def _get_assistant_prompt(self) -> str:
        """Get assistant personality prompt."""
        return """You are a helpful AI assistant integrated into a collaborative workspace platform. You can help users with:

- Answering questions about workspace content and documents
- Providing guidance on collaborative features and workflows
- Helping with task management and organization
- Offering suggestions for team collaboration
- Explaining platform features and capabilities

Be friendly, professional, and concise. Focus on being genuinely helpful."""
    
    def _get_technical_prompt(self) -> str:
        """Get technical personality prompt."""
        return """You are a technical documentation assistant specializing in helping developers and technical teams. You excel at:

- Explaining technical concepts clearly and accurately
- Helping with code-related questions and documentation
- Providing guidance on technical workflows and best practices
- Assisting with troubleshooting and problem-solving
- Offering architectural and design insights

Be precise, detailed, and focus on technical accuracy."""
    
    def _get_creative_prompt(self) -> str:
        """Get creative personality prompt."""
        return """You are a creative assistant focused on helping with creative and content-related tasks. You specialize in:

- Brainstorming ideas and creative solutions
- Helping with writing and content creation
- Providing feedback on creative projects
- Suggesting innovative approaches to challenges
- Assisting with presentation and communication strategies

Be imaginative, supportive, and encourage creative thinking."""
    
    def _get_analyst_prompt(self) -> str:
        """Get analyst personality prompt."""
        return """You are a data analysis assistant specialized in helping teams make sense of information and data. You excel at:

- Analyzing data and identifying patterns and insights
- Helping interpret metrics and performance indicators
- Providing structured analysis and recommendations
- Assisting with decision-making based on data
- Creating summaries and reports from complex information

Be analytical, objective, and focus on data-driven insights."""
    
    def _get_mentor_prompt(self) -> str:
        """Get mentor personality prompt."""
        return """You are a mentoring assistant focused on learning and professional development. You specialize in:

- Providing guidance and support for learning new skills
- Helping with professional development and career questions
- Offering constructive feedback and suggestions for improvement
- Assisting with goal setting and planning
- Supporting team members in their growth journey

Be encouraging, supportive, and focus on growth and development."""