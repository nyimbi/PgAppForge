# AI API Reference

Complete API documentation for PgAppForge's AI system.

## 📚 Module Overview

| Module | Description | Location |
|--------|-------------|----------|
| `ai_models` | Core AI adapters and model management | `pgappforge.collaborative.ai.ai_models` |
| `chatbot_service` | High-level chatbot service | `pgappforge.collaborative.ai.chatbot_service` |
| `knowledge_base` | Knowledge management system | `pgappforge.collaborative.ai.knowledge_base` |
| `rag_engine` | Retrieval-Augmented Generation | `pgappforge.collaborative.ai.rag_engine` |
| `ai_views` | Web interface views | `pgappforge.collaborative.views.ai_views` |

## 🏗️ Core Classes

### ModelManager

Central orchestrator for all AI operations.

```python
class ModelManager:
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        app: Optional[Flask] = None,
        session_factory: Optional[Callable] = None
    ):
```

**Methods:**

#### `register_adapter(name: str, adapter: AIModelAdapter, is_default: bool = False) -> None`

Register an AI provider adapter.

```python
model_manager = ModelManager(app=app)
model_manager.register_adapter('openai', openai_adapter, is_default=True)
```

**Parameters:**
- `name` - Unique identifier for the adapter
- `adapter` - Instance of AIModelAdapter
- `is_default` - Whether this is the default provider

#### `generate_response(messages: List[ChatMessage], provider: Optional[str] = None, **kwargs) -> ModelResponse`

Generate AI response from messages.

```python
response = await model_manager.generate_response(
    messages=[ChatMessage(role="user", content="Hello")],
    provider="openai",
    max_tokens=1000,
    temperature=0.7
)
```

**Parameters:**
- `messages` - List of conversation messages
- `provider` - Provider name (uses default if None)
- `**kwargs` - Provider-specific parameters

**Returns:** `ModelResponse` object with content and metadata

#### `generate_stream(messages: List[ChatMessage], provider: Optional[str] = None, **kwargs) -> AsyncIterator[str]`

Generate streaming AI response.

```python
async for chunk in model_manager.generate_stream(messages):
    print(chunk, end='', flush=True)
```

#### `generate_embeddings(texts: List[str], provider: Optional[str] = None, **kwargs) -> List[List[float]]`

Generate text embeddings.

```python
embeddings = await model_manager.generate_embeddings([
    "First document",
    "Second document"
])
```

#### `get_available_models() -> Dict[str, Dict[str, Any]]`

Get information about all registered providers.

```python
models = model_manager.get_available_models()
for provider, info in models.items():
    print(f"{provider}: {info['model']} - {info['capabilities']}")
```

#### `get_provider_capabilities(provider: str) -> Dict[str, bool]`

Get capabilities for a specific provider.

```python
caps = model_manager.get_provider_capabilities('openai')
# Returns: {'chat': True, 'streaming': True, 'embeddings': True, ...}
```

### AIModelAdapter

Abstract base class for all AI provider adapters.

```python
class AIModelAdapter(ABC):
    def __init__(self, config: ModelConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
```

**Abstract Methods:**

#### `generate_response(messages: List[ChatMessage], **kwargs) -> ModelResponse`

Generate response from messages.

#### `generate_stream(messages: List[ChatMessage], **kwargs) -> AsyncIterator[str]`

Generate streaming response.

#### `generate_embeddings(texts: List[str], **kwargs) -> List[List[float]]`

Generate text embeddings (optional).

#### `speech_to_text(audio_data: bytes, **kwargs) -> str`

Convert speech to text (optional).

#### `text_to_speech(text: str, **kwargs) -> bytes`

Convert text to speech (optional).

### ModelConfig

Configuration class for AI models.

```python
@dataclass
class ModelConfig:
    provider: ModelProvider
    model_name: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout: int = 30

    # Provider-specific fields
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    api_version: Optional[str] = None
    ollama_host: Optional[str] = None
    google_project_id: Optional[str] = None
    # ... additional provider-specific fields
```

### ChatMessage

Standardized message format.

```python
@dataclass
class ChatMessage:
    role: str  # 'user', 'assistant', 'system'
    content: str
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
```

**Example:**
```python
message = ChatMessage(
    role="user",
    content="Explain quantum computing",
    metadata={"source": "web_ui"}
)
```

### ModelResponse

Standardized response format.

```python
@dataclass
class ModelResponse:
    content: str
    model: str
    provider: ModelProvider
    usage: Optional[Dict[str, int]] = None
    metadata: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
```

## 🤖 Chatbot Service

High-level service for chatbot functionality.

### ChatbotService

```python
class ChatbotService:
    def __init__(
        self,
        model_manager: ModelManager,
        rag_engine: Optional[RAGEngine] = None,
        communication_service: Optional[CommunicationService] = None,
        session_factory: Optional[Callable] = None
    ):
```

**Methods:**

#### `start_conversation(user_id: int, personality: str = 'assistant', **kwargs) -> Conversation`

Start a new conversation.

```python
conversation = await chatbot.start_conversation(
    user_id=123,
    personality='technical',
    title="API Help Session"
)
```

#### `send_message(conversation_id: str, message: str, use_knowledge_base: bool = True, **kwargs) -> ChatMessage`

Send message and get AI response.

```python
response = await chatbot.send_message(
    conversation_id=conversation.id,
    message="How do I set up authentication?",
    use_knowledge_base=True
)
```

#### `get_conversation_history(conversation_id: str, limit: int = 50) -> List[ChatMessage]`

Get conversation message history.

```python
history = await chatbot.get_conversation_history(conversation.id)
for message in history:
    print(f"{message.role}: {message.content}")
```

#### `get_user_conversations(user_id: int, limit: int = 20) -> List[Conversation]`

Get user's conversations.

```python
conversations = await chatbot.get_user_conversations(user_id=123)
```

### Conversation

Conversation model.

```python
@dataclass
class Conversation:
    id: str
    user_id: int
    title: str
    personality: str
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    metadata: Optional[Dict[str, Any]] = None
```

## 🧠 Knowledge Base

Knowledge management and RAG system.

### KnowledgeBaseManager

```python
class KnowledgeBaseManager:
    def __init__(
        self,
        rag_engine: RAGEngine,
        model_manager: ModelManager,
        session_factory: Callable,
        max_concurrent_tasks: int = 5,
        auto_indexing_enabled: bool = True
    ):
```

**Methods:**

#### `index_content(content_id: str, content: str, source: str, metadata: Dict[str, Any] = None) -> bool`

Index content for search.

```python
success = await kb_manager.index_content(
    content_id="doc_123",
    content="PgAppForge is a rapid application development framework...",
    source="documentation",
    metadata={
        "title": "PgAppForge Overview",
        "author": "admin",
        "tags": ["flask", "python", "web"]
    }
)
```

#### `search_similar_content(query: str, limit: int = 10, similarity_threshold: float = 0.7) -> List[ContentMatch]`

Search for similar content.

```python
results = await kb_manager.search_similar_content(
    query="How to configure database connections?",
    limit=5,
    similarity_threshold=0.8
)

for result in results:
    print(f"Score: {result.score:.3f} - {result.content[:100]}...")
```

#### `get_stats() -> Dict[str, Any]`

Get knowledge base statistics.

```python
stats = kb_manager.get_stats()
print(f"Total documents: {stats['total_documents']}")
print(f"Total chunks: {stats['total_chunks']}")
```

### RAGEngine

Retrieval-Augmented Generation engine.

```python
class RAGEngine:
    def __init__(
        self,
        vector_store: VectorStore,
        model_manager: ModelManager,
        chunk_size: int = 512,
        chunk_overlap: int = 50
    ):
```

**Methods:**

#### `index_content(content_id: str, content: str, metadata: Dict[str, Any] = None) -> bool`

Index content with automatic chunking.

```python
await rag_engine.index_content(
    content_id="user_manual",
    content=long_document_text,
    metadata={"type": "manual", "version": "2.0"}
)
```

#### `retrieve_context(query: str, top_k: int = 5, similarity_threshold: float = 0.7) -> List[ContentChunk]`

Retrieve relevant context for a query.

```python
context = await rag_engine.retrieve_context(
    query="authentication setup",
    top_k=3
)
```

#### `generate_response_with_context(query: str, messages: List[ChatMessage] = None, **kwargs) -> ModelResponse`

Generate AI response with relevant context.

```python
response = await rag_engine.generate_response_with_context(
    query="How do I set up OAuth authentication?",
    provider="openai"
)
```

## 🌐 Web Views

PgAppForge views for AI features.

### AIChatView

Main AI chat interface.

```python
class AIChatView(BaseView):
    route_base = "/ai-chat"
```

**Endpoints:**

#### `GET /ai-chat/`

Main chat interface.

#### `GET /ai-chat/conversations`

List user conversations.

#### `GET /ai-chat/conversation/<conversation_id>`

View specific conversation.

#### `GET /ai-chat/settings`

AI assistant settings.

### AIKnowledgeBaseView

Knowledge base management interface.

```python
class AIKnowledgeBaseView(BaseView):
    route_base = "/ai-knowledge"
```

**Endpoints:**

#### `GET /ai-knowledge/`

Knowledge base dashboard.

#### `GET /ai-knowledge/search`

Search interface.

#### `POST /ai-knowledge/index-content`

Manual content indexing.

### AIAdminView

AI system administration.

```python
class AIAdminView(BaseView):
    route_base = "/ai-admin"
```

**Endpoints:**

#### `GET /ai-admin/`

Admin dashboard.

#### `GET /ai-admin/models`

Model configuration.

#### `GET|POST /ai-admin/system-config`

System configuration.

## 🔌 REST API

Complete REST API for external integrations.

### Chat API

#### `POST /api/v1/ai/chat`

Generate AI response.

**Request:**
```json
{
  "messages": [
    {"role": "user", "content": "Hello"}
  ],
  "provider": "openai",
  "model": "gpt-4",
  "max_tokens": 1000,
  "temperature": 0.7
}
```

**Response:**
```json
{
  "content": "Hello! How can I help you today?",
  "model": "gpt-4",
  "provider": "openai",
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 12,
    "total_tokens": 22
  },
  "finish_reason": "stop"
}
```

#### `POST /api/v1/ai/chat/stream`

Generate streaming response.

**Request:** Same as `/chat`

**Response:** Server-Sent Events stream

### Conversations API

#### `POST /api/v1/ai/conversations`

Start new conversation.

**Request:**
```json
{
  "title": "Help Session",
  "personality": "technical"
}
```

#### `GET /api/v1/ai/conversations`

List conversations.

#### `POST /api/v1/ai/conversations/{id}/messages`

Send message to conversation.

### Knowledge Base API

#### `POST /api/v1/ai/knowledge/index`

Index content.

**Request:**
```json
{
  "content": "Document content here...",
  "metadata": {
    "title": "Document Title",
    "source": "api",
    "tags": ["tag1", "tag2"]
  }
}
```

#### `GET /api/v1/ai/knowledge/search`

Search knowledge base.

**Parameters:**
- `q` - Search query
- `limit` - Number of results (default: 10)
- `threshold` - Similarity threshold (default: 0.7)

### Models API

#### `GET /api/v1/ai/models`

List available models.

**Response:**
```json
{
  "openai": {
    "model": "gpt-4",
    "capabilities": ["chat", "streaming", "embeddings"],
    "status": "active"
  },
  "anthropic": {
    "model": "claude-3-sonnet",
    "capabilities": ["chat", "streaming"],
    "status": "active"
  }
}
```

#### `POST /api/v1/ai/models/test`

Test model connection.

## 🔧 Utility Functions

### Configuration Loading

```python
def load_model_configs_from_app(app: Flask) -> Dict[str, ModelConfig]:
    """Load model configurations from Flask app config."""
```

### Model Adapter Creation

```python
def create_model_adapter(config: ModelConfig) -> AIModelAdapter:
    """Create appropriate adapter for given configuration."""
```

### Connection Testing

```python
async def test_provider_connection(provider: str, config: ModelConfig = None) -> ConnectionResult:
    """Test connection to AI provider."""
```

## 🔄 Async Utilities

### AsyncBridge

Bridge between async AI services and sync Flask views.

```python
class AsyncBridge:
    @classmethod
    def run_async(cls, coro: Awaitable[T]) -> T:
        """Run async coroutine from sync context."""

    @classmethod
    def sync_wrapper(cls, async_func: Callable[..., Awaitable[T]]) -> Callable[..., T]:
        """Convert async function to sync."""
```

**Usage:**
```python
from pgappforge.collaborative.utils.async_bridge import AsyncBridge

# In sync view method
result = AsyncBridge.run_async(
    model_manager.generate_response(messages)
)
```

## 📊 Monitoring & Analytics

### Provider Health Monitoring

```python
async def get_provider_health() -> Dict[str, ProviderHealth]:
    """Get health status for all providers."""
```

### Usage Analytics

```python
async def get_usage_stats(timeframe: str = '24h') -> UsageStats:
    """Get usage statistics for AI services."""
```

## 🚨 Error Handling

### Custom Exceptions

```python
class AIServiceError(Exception):
    """Base exception for AI services."""

class ProviderError(AIServiceError):
    """Provider-specific error."""

class RateLimitError(AIServiceError):
    """Rate limit exceeded."""

class AuthenticationError(AIServiceError):
    """Authentication failed."""
```

### Error Response Format

```json
{
  "error": {
    "type": "ProviderError",
    "message": "Rate limit exceeded",
    "provider": "openai",
    "code": "rate_limit_exceeded",
    "retry_after": 60
  }
}
```

## 📝 Type Hints

Complete type definitions for all AI system components.

```python
from typing import (
    Any, Dict, List, Optional, Union, AsyncIterator,
    Callable, Awaitable, TYPE_CHECKING
)

if TYPE_CHECKING:
    from flask import Flask
    from pgappforge.collaborative.ai.ai_models import ModelManager
```

For more detailed examples and tutorials, see:
- [AI Architecture](ai_architecture.md)
- [Provider Configuration](ai_providers.md)
- [AI Chat Tutorial](../tutorials/ai_chatbot.md)