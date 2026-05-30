"""
AI Model adapters for different providers (OpenAI, Anthropic, local models).

Provides a unified interface for interacting with various AI models
while handling provider-specific authentication and API differences.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, AsyncIterator, AsyncGenerator, Callable
import json

logger = logging.getLogger(__name__)


class ModelProvider(Enum):
    """Supported AI model providers."""
    
    # Major cloud providers
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"  # Gemini
    AZURE_OPENAI = "azure_openai"
    
    # Specialized providers
    OLLAMA = "ollama"  # Local models
    OPENROUTER = "openrouter"  # Model aggregator
    MISTRAL = "mistral"
    GROQ = "groq"  # Fast inference
    
    # International providers
    GROK = "grok"  # xAI
    DEEPSEEK = "deepseek"
    KIMI = "kimi"  # Moonshot AI
    QWEN = "qwen"  # Alibaba
    
    # Speech processing providers
    LOCAL_SPEECH = "local_speech"  # Local Whisper + TTS
    HUGGINGFACE_SPEECH = "huggingface_speech"  # HF Transformers
    
    # Legacy/fallback
    HUGGINGFACE = "huggingface"
    LOCAL = "local"


@dataclass
class ChatMessage:
    """Standardized chat message format."""
    
    role: str  # 'user', 'assistant', 'system'
    content: str
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None


@dataclass
class ModelResponse:
    """Standardized model response format."""
    
    content: str
    model: str
    provider: ModelProvider
    usage: Optional[Dict[str, int]] = None
    metadata: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None


@dataclass
class ModelConfig:
    """Model configuration and parameters."""
    
    provider: ModelProvider
    model_name: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    
    # Common parameters
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout: int = 30
    
    # Provider-specific parameters
    # Azure OpenAI
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    api_version: Optional[str] = None
    
    # Ollama
    ollama_host: Optional[str] = None  # Default: http://localhost:11434
    
    # Google (Gemini)
    google_project_id: Optional[str] = None
    google_location: Optional[str] = None
    
    # Groq
    groq_model_type: Optional[str] = None  # chat, completion, embedding
    
    # Speech processing
    whisper_model_size: str = "base"  # tiny, base, small, medium, large
    tts_voice: Optional[str] = None
    tts_language: str = "en"
    
    # Generic extra parameters for any provider
    extra_params: Optional[Dict[str, Any]] = None
    
    # Stop sequences for text generation
    stop_sequences: Optional[List[str]] = None
    
    def get_api_base_url(self) -> str:
        """Get the appropriate API base URL for the provider."""
        if self.api_base:
            return self.api_base
            
        # Default API endpoints for each provider
        defaults = {
            ModelProvider.OPENAI: "https://api.openai.com/v1",
            ModelProvider.ANTHROPIC: "https://api.anthropic.com",
            ModelProvider.GOOGLE: "https://generativelanguage.googleapis.com/v1",
            ModelProvider.OLLAMA: self.ollama_host or "http://localhost:11434",
            ModelProvider.OPENROUTER: "https://openrouter.ai/api/v1",
            ModelProvider.MISTRAL: "https://api.mistral.ai/v1",
            ModelProvider.GROQ: "https://api.groq.com/openai/v1",
            ModelProvider.GROK: "https://api.x.ai/v1",
            ModelProvider.DEEPSEEK: "https://api.deepseek.com/v1",
            ModelProvider.KIMI: "https://api.moonshot.cn/v1",
            ModelProvider.QWEN: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        }
        
        return defaults.get(self.provider, "")
    
    def get_headers(self) -> Dict[str, str]:
        """Get provider-specific headers."""
        headers = {"Content-Type": "application/json"}
        
        if self.provider in [ModelProvider.OPENAI, ModelProvider.OPENROUTER, 
                           ModelProvider.MISTRAL, ModelProvider.GROQ, 
                           ModelProvider.GROK, ModelProvider.DEEPSEEK,
                           ModelProvider.KIMI, ModelProvider.QWEN]:
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                
        elif self.provider == ModelProvider.ANTHROPIC:
            if self.api_key:
                headers["x-api-key"] = self.api_key
                headers["anthropic-version"] = "2023-06-01"
                
        elif self.provider == ModelProvider.GOOGLE:
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                
        elif self.provider == ModelProvider.AZURE_OPENAI:
            if self.api_key:
                headers["api-key"] = self.api_key
                
        return headers


class AIModelAdapter(ABC):
    """Abstract base class for AI model adapters."""
    
    def __init__(self, config: ModelConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @abstractmethod
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion."""
        pass
    
    @abstractmethod
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens."""
        pass
    
    @abstractmethod
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for texts."""
        pass
    
    # Speech processing methods (optional implementation)
    async def speech_to_text(self, audio_data: bytes, **kwargs) -> str:
        """Convert speech to text (optional)."""
        raise NotImplementedError(f"Speech-to-text not supported by {self.config.provider.value}")
    
    async def text_to_speech(self, text: str, **kwargs) -> bytes:
        """Convert text to speech audio (optional)."""
        raise NotImplementedError(f"Text-to-speech not supported by {self.config.provider.value}")
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the model is available."""
        pass
    
    def supports_speech_to_text(self) -> bool:
        """Check if adapter supports speech-to-text."""
        return False
        
    def supports_text_to_speech(self) -> bool:
        """Check if adapter supports text-to-speech."""
        return False


class OpenAIAdapter(AIModelAdapter):
    """OpenAI API adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize OpenAI client."""
        try:
            import openai
            self.client = openai.AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.api_base,
                timeout=self.config.timeout
            )
            self.logger.info("OpenAI client initialized")
        except ImportError:
            self.logger.error("OpenAI package not available. Install with: pip install openai")
        except Exception as e:
            self.logger.error(f"Failed to initialize OpenAI client: {e}")
    
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion using OpenAI API."""
        if not self.client:
            raise RuntimeError("OpenAI client not available")
        
        try:
            # Convert messages to OpenAI format
            openai_messages = [
                {"role": msg.role, "content": msg.content} 
                for msg in messages
            ]
            
            # Merge config with kwargs
            params = {
                "model": self.config.model_name,
                "messages": openai_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "frequency_penalty": self.config.frequency_penalty,
                "presence_penalty": self.config.presence_penalty,
                **kwargs
            }
            
            response = await self.client.chat.completions.create(**params)
            
            return ModelResponse(
                content=response.choices[0].message.content,
                model=response.model,
                provider=ModelProvider.OPENAI,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                } if response.usage else None,
                finish_reason=response.choices[0].finish_reason
            )
            
        except Exception as e:
            self.logger.error(f"OpenAI chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens."""
        if not self.client:
            raise RuntimeError("OpenAI client not available")
        
        try:
            openai_messages = [
                {"role": msg.role, "content": msg.content} 
                for msg in messages
            ]
            
            params = {
                "model": self.config.model_name,
                "messages": openai_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "stream": True,
                **kwargs
            }
            
            stream = await self.client.chat.completions.create(**params)
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            self.logger.error(f"OpenAI streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using OpenAI API."""
        if not self.client:
            raise RuntimeError("OpenAI client not available")
        
        try:
            response = await self.client.embeddings.create(
                model="text-embedding-ada-002",
                input=texts
            )
            
            return [embedding.embedding for embedding in response.data]
            
        except Exception as e:
            self.logger.error(f"OpenAI embeddings failed: {e}")
            raise

    async def speech_to_text(self, audio_data: bytes, **kwargs) -> str:
        """Convert speech to text using OpenAI Whisper API."""
        if not self.client:
            raise RuntimeError("OpenAI client not available")
        
        try:
            # Create a temporary file-like object from audio data
            import io
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"  # OpenAI API requires a filename
            
            response = await self.client.audio.transcriptions.create(
                model=kwargs.get("model", "whisper-1"),
                file=audio_file,
                language=kwargs.get("language", self.config.tts_language),
                response_format=kwargs.get("response_format", "text")
            )
            
            return response.text if hasattr(response, 'text') else str(response)
            
        except Exception as e:
            self.logger.error(f"OpenAI speech-to-text failed: {e}")
            raise
    
    async def text_to_speech(self, text: str, **kwargs) -> bytes:
        """Convert text to speech using OpenAI TTS API."""
        if not self.client:
            raise RuntimeError("OpenAI client not available")
        
        try:
            response = await self.client.audio.speech.create(
                model=kwargs.get("model", "tts-1"),
                voice=kwargs.get("voice", self.config.tts_voice or "alloy"),
                input=text,
                response_format=kwargs.get("response_format", "mp3")
            )
            
            return response.content
            
        except Exception as e:
            self.logger.error(f"OpenAI text-to-speech failed: {e}")
            raise
    
    def supports_speech_to_text(self) -> bool:
        """OpenAI supports speech-to-text via Whisper."""
        return True
        
    def supports_text_to_speech(self) -> bool:
        """OpenAI supports text-to-speech."""
        return True
    
    def is_available(self) -> bool:
        """Check if OpenAI is available."""
        return self.client is not None and self.config.api_key is not None


class AnthropicAdapter(AIModelAdapter):
    """Anthropic Claude API adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Anthropic client."""
        try:
            import anthropic
            self.client = anthropic.AsyncAnthropic(
                api_key=self.config.api_key,
                timeout=self.config.timeout
            )
            self.logger.info("Anthropic client initialized")
        except ImportError:
            self.logger.error("Anthropic package not available. Install with: pip install anthropic")
        except Exception as e:
            self.logger.error(f"Failed to initialize Anthropic client: {e}")
    
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion using Anthropic API."""
        if not self.client:
            raise RuntimeError("Anthropic client not available")
        
        try:
            # Convert messages to Anthropic format
            anthropic_messages = []
            system_message = None
            
            for msg in messages:
                if msg.role == "system":
                    system_message = msg.content
                else:
                    anthropic_messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })
            
            params = {
                "model": self.config.model_name,
                "messages": anthropic_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                **kwargs
            }
            
            if system_message:
                params["system"] = system_message
            
            response = await self.client.messages.create(**params)
            
            return ModelResponse(
                content=response.content[0].text,
                model=response.model,
                provider=ModelProvider.ANTHROPIC,
                usage={
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens
                } if response.usage else None,
                finish_reason=response.stop_reason
            )
            
        except Exception as e:
            self.logger.error(f"Anthropic chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens."""
        if not self.client:
            raise RuntimeError("Anthropic client not available")
        
        try:
            anthropic_messages = []
            system_message = None
            
            for msg in messages:
                if msg.role == "system":
                    system_message = msg.content
                else:
                    anthropic_messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })
            
            params = {
                "model": self.config.model_name,
                "messages": anthropic_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "stream": True,
                **kwargs
            }
            
            if system_message:
                params["system"] = system_message
            
            stream = await self.client.messages.create(**params)
            
            async for chunk in stream:
                if chunk.type == "content_block_delta" and chunk.delta.text:
                    yield chunk.delta.text
                    
        except Exception as e:
            self.logger.error(f"Anthropic streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings (not directly supported by Anthropic)."""
        # Anthropic doesn't provide embeddings API, fallback to other providers
        raise NotImplementedError("Anthropic doesn't provide embeddings API")
    
    def is_available(self) -> bool:
        """Check if Anthropic is available."""
        return self.client is not None and self.config.api_key is not None

class OllamaAdapter(AIModelAdapter):
    """Ollama local model adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.base_url = config.get_api_base_url()
        
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion using Ollama API."""
        try:
            import aiohttp
            
            ollama_messages = [
                {"role": msg.role, "content": msg.content} 
                for msg in messages
            ]
            
            payload = {
                "model": self.config.model_name,
                "messages": ollama_messages,
                "options": {
                    "temperature": self.config.temperature,
                    "top_p": self.config.top_p,
                    "num_predict": self.config.max_tokens,
                },
                "stream": False,
                **kwargs
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(f"Ollama API error: {response.status}")
                    
                    result = await response.json()
                    
                    return ModelResponse(
                        content=result["message"]["content"],
                        model=self.config.model_name,
                        provider=ModelProvider.OLLAMA,
                        usage=result.get("usage"),
                        finish_reason=result.get("done_reason")
                    )
                    
        except ImportError:
            self.logger.error("aiohttp package required for Ollama. Install with: pip install aiohttp")
            raise
        except Exception as e:
            self.logger.error(f"Ollama chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens from Ollama."""
        try:
            import aiohttp
            import json as json_lib
            
            ollama_messages = [
                {"role": msg.role, "content": msg.content} 
                for msg in messages
            ]
            
            payload = {
                "model": self.config.model_name,
                "messages": ollama_messages,
                "options": {
                    "temperature": self.config.temperature,
                    "top_p": self.config.top_p,
                    "num_predict": self.config.max_tokens,
                },
                "stream": True,
                **kwargs
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(f"Ollama API error: {response.status}")
                    
                    async for line in response.content:
                        if line:
                            try:
                                chunk = json_lib.loads(line.decode('utf-8'))
                                if chunk.get("message", {}).get("content"):
                                    yield chunk["message"]["content"]
                            except json_lib.JSONDecodeError:
                                continue
                                
        except ImportError:
            self.logger.error("aiohttp package required for Ollama. Install with: pip install aiohttp")
            raise
        except Exception as e:
            self.logger.error(f"Ollama streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using Ollama."""
        try:
            import aiohttp
            
            embeddings = []
            
            async with aiohttp.ClientSession() as session:
                for text in texts:
                    payload = {
                        "model": self.config.model_name,
                        "prompt": text
                    }
                    
                    async with session.post(
                        f"{self.base_url}/api/embeddings",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                    ) as response:
                        if response.status != 200:
                            raise RuntimeError(f"Ollama embeddings error: {response.status}")
                        
                        result = await response.json()
                        embeddings.append(result["embedding"])
            
            return embeddings
            
        except Exception as e:
            self.logger.error(f"Ollama embeddings failed: {e}")
            raise
    
    def is_available(self) -> bool:
        """Check if Ollama is available."""
        try:
            import aiohttp
            return True
        except ImportError:
            return False


class OpenRouterAdapter(AIModelAdapter):
    """OpenRouter aggregator adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize OpenRouter client (OpenAI-compatible)."""
        try:
            import openai
            self.client = openai.AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.get_api_base_url(),
                timeout=self.config.timeout
            )
            self.logger.info("OpenRouter client initialized")
        except ImportError:
            self.logger.error("OpenAI package required for OpenRouter. Install with: pip install openai")
        except Exception as e:
            self.logger.error(f"Failed to initialize OpenRouter client: {e}")
    
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion using OpenRouter API."""
        if not self.client:
            raise RuntimeError("OpenRouter client not available")
        
        try:
            openai_messages = [
                {"role": msg.role, "content": msg.content} 
                for msg in messages
            ]
            
            params = {
                "model": self.config.model_name,
                "messages": openai_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                **kwargs
            }
            
            response = await self.client.chat.completions.create(**params)
            
            return ModelResponse(
                content=response.choices[0].message.content,
                model=response.model,
                provider=ModelProvider.OPENROUTER,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                } if response.usage else None,
                finish_reason=response.choices[0].finish_reason
            )
            
        except Exception as e:
            self.logger.error(f"OpenRouter chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens from OpenRouter."""
        if not self.client:
            raise RuntimeError("OpenRouter client not available")
        
        try:
            openai_messages = [
                {"role": msg.role, "content": msg.content} 
                for msg in messages
            ]
            
            params = {
                "model": self.config.model_name,
                "messages": openai_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "stream": True,
                **kwargs
            }
            
            stream = await self.client.chat.completions.create(**params)
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            self.logger.error(f"OpenRouter streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using OpenRouter."""
        if not self.client:
            raise RuntimeError("OpenRouter client not available")
        
        try:
            response = await self.client.embeddings.create(
                model=self.config.model_name,
                input=texts
            )
            
            return [embedding.embedding for embedding in response.data]
            
        except Exception as e:
            self.logger.error(f"OpenRouter embeddings failed: {e}")
            raise
    
    def is_available(self) -> bool:
        """Check if OpenRouter is available."""
        return self.client is not None and self.config.api_key is not None


class GoogleGeminiAdapter(AIModelAdapter):
    """Google Gemini API adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Google AI client."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.config.api_key)
            self.client = genai
            self.logger.info("Google Gemini client initialized")
        except ImportError:
            self.logger.error("Google AI package required. Install with: pip install google-generativeai")
        except Exception as e:
            self.logger.error(f"Failed to initialize Google client: {e}")
    
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion using Google Gemini API."""
        if not self.client:
            raise RuntimeError("Google Gemini client not available")
        
        try:
            # Convert messages to Gemini format
            gemini_messages = []
            for msg in messages:
                role = "user" if msg.role == "user" else "model"
                gemini_messages.append({
                    "role": role,
                    "parts": [{"text": msg.content}]
                })
            
            model = self.client.GenerativeModel(self.config.model_name)
            
            generation_config = {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "max_output_tokens": self.config.max_tokens,
            }
            
            response = await model.generate_content_async(
                gemini_messages,
                generation_config=generation_config,
                **kwargs
            )
            
            return ModelResponse(
                content=response.text,
                model=self.config.model_name,
                provider=ModelProvider.GOOGLE,
                usage=response.usage_metadata._asdict() if hasattr(response, 'usage_metadata') else None,
                finish_reason=response.candidates[0].finish_reason.name if response.candidates else None
            )
            
        except Exception as e:
            self.logger.error(f"Google Gemini chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens from Google Gemini."""
        if not self.client:
            raise RuntimeError("Google Gemini client not available")
        
        try:
            gemini_messages = []
            for msg in messages:
                role = "user" if msg.role == "user" else "model"
                gemini_messages.append({
                    "role": role,
                    "parts": [{"text": msg.content}]
                })
            
            model = self.client.GenerativeModel(self.config.model_name)
            
            generation_config = {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "max_output_tokens": self.config.max_tokens,
            }
            
            response = await model.generate_content_async(
                gemini_messages,
                generation_config=generation_config,
                stream=True,
                **kwargs
            )
            
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            self.logger.error(f"Google Gemini streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using Google AI."""
        if not self.client:
            raise RuntimeError("Google Gemini client not available")
        
        try:
            embeddings = []
            for text in texts:
                result = self.client.embed_content(
                    model="models/embedding-001",
                    content=text,
                    task_type="retrieval_document"
                )
                embeddings.append(result["embedding"])
            
            return embeddings
            
        except Exception as e:
            self.logger.error(f"Google Gemini embeddings failed: {e}")
            raise
    
    def is_available(self) -> bool:
        """Check if Google Gemini is available."""
        return self.client is not None and self.config.api_key is not None


class MistralAdapter(AIModelAdapter):
    """Mistral AI adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Mistral client."""
        try:
            from mistralai.async_client import MistralAsyncClient
            self.client = MistralAsyncClient(
                api_key=self.config.api_key,
                timeout=self.config.timeout
            )
            self.logger.info("Mistral client initialized")
        except ImportError:
            self.logger.error("Mistral package required. Install with: pip install mistralai")
        except Exception as e:
            self.logger.error(f"Failed to initialize Mistral client: {e}")
    
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion using Mistral API."""
        if not self.client:
            raise RuntimeError("Mistral client not available")
        
        try:
            from mistralai.models.chat_completion import ChatMessage as MistralChatMessage
            
            mistral_messages = [
                MistralChatMessage(role=msg.role, content=msg.content)
                for msg in messages
            ]
            
            response = await self.client.chat(
                model=self.config.model_name,
                messages=mistral_messages,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                max_tokens=self.config.max_tokens,
                **kwargs
            )
            
            return ModelResponse(
                content=response.choices[0].message.content,
                model=response.model,
                provider=ModelProvider.MISTRAL,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                } if response.usage else None,
                finish_reason=response.choices[0].finish_reason
            )
            
        except Exception as e:
            self.logger.error(f"Mistral chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens from Mistral."""
        if not self.client:
            raise RuntimeError("Mistral client not available")
        
        try:
            from mistralai.models.chat_completion import ChatMessage as MistralChatMessage
            
            mistral_messages = [
                MistralChatMessage(role=msg.role, content=msg.content)
                for msg in messages
            ]
            
            response = await self.client.chat_stream(
                model=self.config.model_name,
                messages=mistral_messages,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                max_tokens=self.config.max_tokens,
                **kwargs
            )
            
            async for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            self.logger.error(f"Mistral streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using Mistral."""
        if not self.client:
            raise RuntimeError("Mistral client not available")
        
        try:
            response = await self.client.embeddings(
                model="mistral-embed",
                input=texts
            )
            
            return [embedding.embedding for embedding in response.data]
            
        except Exception as e:
            self.logger.error(f"Mistral embeddings failed: {e}")
            raise
    
    def is_available(self) -> bool:
        """Check if Mistral is available."""
        return self.client is not None and self.config.api_key is not None


class GroqAdapter(AIModelAdapter):
    """Groq AI model adapter for fast inference."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Groq client."""
        try:
            from groq import AsyncGroq
            
            if not self.config.api_key:
                self.logger.warning("Groq API key not provided")
                return
                
            self.client = AsyncGroq(
                api_key=self.config.api_key,
                timeout=self.config.timeout
            )
            self.logger.info("Groq client initialized successfully")
            
        except ImportError:
            self.logger.error("groq package not installed. Install with: pip install groq")
        except Exception as e:
            self.logger.error(f"Failed to initialize Groq client: {e}")
    
    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """Generate chat completion using Groq."""
        if not self.client:
            raise RuntimeError("Groq client not initialized")
        
        try:
            # Prepare parameters
            params = {
                "model": self.config.model_name,
                "messages": [
                    {"role": msg.role, "content": msg.content} 
                    for msg in messages
                ],
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "stop": kwargs.get("stop", self.config.stop_sequences),
                "stream": False
            }
            
            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}
            
            response = await self.client.chat.completions.create(**params)
            

            return ModelResponse(
                content=response.choices[0].message.content,
                model=response.model,
                provider=ModelProvider.GROQ,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                },
                finish_reason=response.choices[0].finish_reason
            )
            
        except Exception as e:
            self.logger.error(f"Groq chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(self, messages: List[ChatMessage], **kwargs) -> AsyncIterator[str]:
        """Stream chat completion from Groq."""
        if not self.client:
            raise RuntimeError("Groq client not initialized")
        
        try:
            # Prepare parameters
            params = {
                "model": self.config.model_name,
                "messages": [
                    {"role": msg.role, "content": msg.content} 
                    for msg in messages
                ],
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "stop": kwargs.get("stop", self.config.stop_sequences),
                "stream": True
            }
            
            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}
            
            stream = await self.client.chat.completions.create(**params)
            
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, 'content') and delta.content:
                        yield delta.content
                        
        except Exception as e:
            self.logger.error(f"Groq streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str], **kwargs) -> List[List[float]]:
        """Generate embeddings using Groq."""
        # Note: Groq primarily focuses on fast inference for language models
        # Embedding support may be limited - check their API documentation
        raise NotImplementedError("Groq embeddings not yet supported - check API documentation for availability")
    
    def is_available(self) -> bool:
        """Check if Groq is available."""
        return self.client is not None and self.config.api_key is not None


class GrokAdapter(AIModelAdapter):
    """Grok (xAI) model adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Grok client."""
        try:
            import httpx
            
            if not self.config.api_key:
                self.logger.warning("Grok API key not provided")
                return
            
            # Grok uses OpenAI-compatible API format
            self.client = httpx.AsyncClient(
                base_url="https://api.x.ai/v1",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=self.config.timeout
            )
            self.logger.info("Grok client initialized successfully")
            
        except ImportError:
            self.logger.error("httpx package not installed. Install with: pip install httpx")
        except Exception as e:
            self.logger.error(f"Failed to initialize Grok client: {e}")
    
    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """Generate chat completion using Grok."""
        if not self.client:
            raise RuntimeError("Grok client not initialized")
        
        try:
            # Prepare payload for Grok API (OpenAI-compatible)
            payload = {
                "model": self.config.model_name or "grok-beta",
                "messages": [
                    {"role": msg.role, "content": msg.content} 
                    for msg in messages
                ],
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "stop": kwargs.get("stop", self.config.stop_sequences),
                "stream": False
            }
            
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}
            
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            
            data = response.json()
            choice = data["choices"][0]
            
            return {
                "content": choice["message"]["content"],
                "usage": data.get("usage", {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }),
                "model": data.get("model", self.config.model_name),
                "finish_reason": choice.get("finish_reason")
            }
            
        except Exception as e:
            self.logger.error(f"Grok chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(self, messages: List[ChatMessage], **kwargs) -> AsyncIterator[str]:
        """Stream chat completion from Grok."""
        if not self.client:
            raise RuntimeError("Grok client not initialized")
        
        try:
            # Prepare payload for streaming
            payload = {
                "model": self.config.model_name or "grok-beta",
                "messages": [
                    {"role": msg.role, "content": msg.content} 
                    for msg in messages
                ],
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "stop": kwargs.get("stop", self.config.stop_sequences),
                "stream": True
            }
            
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}
            
            async with self.client.stream("POST", "/chat/completions", json=payload) as stream:
                stream.raise_for_status()
                async for line in stream.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        if data_str.strip() == "[DONE]":
                            break
                        
                        try:
                            import json
                            chunk_data = json.loads(data_str)
                            if chunk_data.get("choices") and len(chunk_data["choices"]) > 0:
                                delta = chunk_data["choices"][0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    yield {
                                        "content": delta["content"],
                                        "finish_reason": chunk_data["choices"][0].get("finish_reason"),
                                        "model": chunk_data.get("model")
                                    }
                        except json.JSONDecodeError:
                            continue  # Skip invalid JSON chunks
                            
        except Exception as e:
            self.logger.error(f"Grok streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str], **kwargs) -> List[List[float]]:
        """Generate embeddings using Grok."""
        raise NotImplementedError("Grok embeddings not currently supported")
    
    def is_available(self) -> bool:
        """Check if Grok is available."""
        return self.client is not None and self.config.api_key is not None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()


class DeepseekAdapter(AIModelAdapter):
    """Deepseek AI model adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Deepseek client."""
        try:
            import httpx
            
            if not self.config.api_key:
                self.logger.warning("Deepseek API key not provided")
                return
            
            # Deepseek uses OpenAI-compatible API format
            self.client = httpx.AsyncClient(
                base_url="https://api.deepseek.com/v1",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=self.config.timeout
            )
            self.logger.info("Deepseek client initialized successfully")
            
        except ImportError:
            self.logger.error("httpx package not installed. Install with: pip install httpx")
        except Exception as e:
            self.logger.error(f"Failed to initialize Deepseek client: {e}")
    
    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """Generate chat completion using Deepseek."""
        if not self.client:
            raise RuntimeError("Deepseek client not initialized")
        
        try:
            # Prepare payload for Deepseek API (OpenAI-compatible)
            payload = {
                "model": self.config.model_name or "deepseek-chat",
                "messages": [
                    {"role": msg.role, "content": msg.content} 
                    for msg in messages
                ],
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "stop": kwargs.get("stop", self.config.stop_sequences),
                "stream": False
            }
            
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}
            
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            
            data = response.json()
            choice = data["choices"][0]
            
            return {
                "content": choice["message"]["content"],
                "usage": data.get("usage", {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }),
                "model": data.get("model", self.config.model_name),
                "finish_reason": choice.get("finish_reason")
            }
            
        except Exception as e:
            self.logger.error(f"Deepseek chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(self, messages: List[ChatMessage], **kwargs) -> AsyncIterator[str]:
        """Stream chat completion from Deepseek."""
        if not self.client:
            raise RuntimeError("Deepseek client not initialized")
        
        try:
            # Prepare payload for streaming
            payload = {
                "model": self.config.model_name or "deepseek-chat",
                "messages": [
                    {"role": msg.role, "content": msg.content} 
                    for msg in messages
                ],
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "stop": kwargs.get("stop", self.config.stop_sequences),
                "stream": True
            }
            
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}
            
            async with self.client.stream("POST", "/chat/completions", json=payload) as stream:
                stream.raise_for_status()
                async for line in stream.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        if data_str.strip() == "[DONE]":
                            break
                        
                        try:
                            import json
                            chunk_data = json.loads(data_str)
                            if chunk_data.get("choices") and len(chunk_data["choices"]) > 0:
                                delta = chunk_data["choices"][0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    yield {
                                        "content": delta["content"],
                                        "finish_reason": chunk_data["choices"][0].get("finish_reason"),
                                        "model": chunk_data.get("model")
                                    }
                        except json.JSONDecodeError:
                            continue  # Skip invalid JSON chunks
                            
        except Exception as e:
            self.logger.error(f"Deepseek streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str], **kwargs) -> List[List[float]]:
        """Generate embeddings using Deepseek."""
        # Deepseek may not support embeddings - check their API documentation
        raise NotImplementedError("Deepseek embeddings not currently supported - check API documentation")
    
    def is_available(self) -> bool:
        """Check if Deepseek is available."""
        return self.client is not None and self.config.api_key is not None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()


class KimiAdapter(AIModelAdapter):
    """Kimi (Moonshot AI) model adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Kimi client."""
        try:
            import httpx
            
            if not self.config.api_key:
                self.logger.warning("Kimi API key not provided")
                return
            
            # Kimi uses OpenAI-compatible API format
            self.client = httpx.AsyncClient(
                base_url="https://api.moonshot.cn/v1",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=self.config.timeout
            )
            self.logger.info("Kimi client initialized successfully")
            
        except ImportError:
            self.logger.error("httpx package not installed. Install with: pip install httpx")
        except Exception as e:
            self.logger.error(f"Failed to initialize Kimi client: {e}")
    
    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """Generate chat completion using Kimi."""
        if not self.client:
            raise RuntimeError("Kimi client not initialized")
        
        try:
            # Prepare payload for Kimi API (OpenAI-compatible)
            payload = {
                "model": self.config.model_name or "moonshot-v1-8k",
                "messages": [
                    {"role": msg.role, "content": msg.content} 
                    for msg in messages
                ],
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "stop": kwargs.get("stop", self.config.stop_sequences),
                "stream": False
            }
            
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}
            
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            
            data = response.json()
            choice = data["choices"][0]
            
            return {
                "content": choice["message"]["content"],
                "usage": data.get("usage", {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }),
                "model": data.get("model", self.config.model_name),
                "finish_reason": choice.get("finish_reason")
            }
            
        except Exception as e:
            self.logger.error(f"Kimi chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(self, messages: List[ChatMessage], **kwargs) -> AsyncIterator[str]:
        """Stream chat completion from Kimi."""
        if not self.client:
            raise RuntimeError("Kimi client not initialized")
        
        try:
            # Prepare payload for streaming
            payload = {
                "model": self.config.model_name or "moonshot-v1-8k",
                "messages": [
                    {"role": msg.role, "content": msg.content} 
                    for msg in messages
                ],
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "stop": kwargs.get("stop", self.config.stop_sequences),
                "stream": True
            }
            
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}
            
            async with self.client.stream("POST", "/chat/completions", json=payload) as stream:
                stream.raise_for_status()
                async for line in stream.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        if data_str.strip() == "[DONE]":
                            break
                        
                        try:
                            import json
                            chunk_data = json.loads(data_str)
                            if chunk_data.get("choices") and len(chunk_data["choices"]) > 0:
                                delta = chunk_data["choices"][0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    yield {
                                        "content": delta["content"],
                                        "finish_reason": chunk_data["choices"][0].get("finish_reason"),
                                        "model": chunk_data.get("model")
                                    }
                        except json.JSONDecodeError:
                            continue  # Skip invalid JSON chunks
                            
        except Exception as e:
            self.logger.error(f"Kimi streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str], **kwargs) -> List[List[float]]:
        """Generate embeddings using Kimi."""
        if not self.client:
            raise RuntimeError("Kimi client not initialized")
        
        try:
            embeddings = []
            
            for text in texts:
                payload = {
                    "model": "moonshot-embedding-v1",
                    "input": text
                }
                
                response = await self.client.post("/embeddings", json=payload)
                response.raise_for_status()
                
                data = response.json()
                embedding = data["data"][0]["embedding"]
                embeddings.append(embedding)
            
            return embeddings
            
        except Exception as e:
            self.logger.error(f"Kimi embeddings failed: {e}")
            raise
    
    def is_available(self) -> bool:
        """Check if Kimi is available."""
        return self.client is not None and self.config.api_key is not None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()


class QwenAdapter(AIModelAdapter):
    """Qwen (Alibaba) model adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Qwen client."""
        try:
            import httpx
            
            if not self.config.api_key:
                self.logger.warning("Qwen API key not provided")
                return
            
            # Qwen uses DashScope API
            self.client = httpx.AsyncClient(
                base_url="https://dashscope.aliyuncs.com/api/v1",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=self.config.timeout
            )
            self.logger.info("Qwen client initialized successfully")
            
        except ImportError:
            self.logger.error("httpx package not installed. Install with: pip install httpx")
        except Exception as e:
            self.logger.error(f"Failed to initialize Qwen client: {e}")
    
    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """Generate chat completion using Qwen."""
        if not self.client:
            raise RuntimeError("Qwen client not initialized")
        
        try:
            # Prepare payload for Qwen API (DashScope format)
            payload = {
                "model": self.config.model_name or "qwen-turbo",
                "input": {
                    "messages": messages
                },
                "parameters": {
                    "temperature": kwargs.get("temperature", self.config.temperature),
                    "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                    "top_p": kwargs.get("top_p", self.config.top_p),
                    "stop": kwargs.get("stop", self.config.stop_sequences),
                    "incremental_output": False
                }
            }
            
            # Remove None values from parameters
            payload["parameters"] = {k: v for k, v in payload["parameters"].items() if v is not None}
            
            response = await self.client.post("/services/aigc/text-generation/generation", json=payload)
            response.raise_for_status()
            
            data = response.json()
            output = data["output"]
            
            return {
                "content": output["text"],
                "usage": data.get("usage", {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0
                }),
                "model": self.config.model_name,
                "finish_reason": output.get("finish_reason")
            }
            
        except Exception as e:
            self.logger.error(f"Qwen chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(self, messages: List[ChatMessage], **kwargs) -> AsyncIterator[str]:
        """Stream chat completion from Qwen."""
        if not self.client:
            raise RuntimeError("Qwen client not initialized")
        
        try:
            # Prepare payload for streaming
            payload = {
                "model": self.config.model_name or "qwen-turbo",
                "input": {
                    "messages": messages
                },
                "parameters": {
                    "temperature": kwargs.get("temperature", self.config.temperature),
                    "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                    "top_p": kwargs.get("top_p", self.config.top_p),
                    "stop": kwargs.get("stop", self.config.stop_sequences),
                    "incremental_output": True
                }
            }
            
            # Remove None values from parameters
            payload["parameters"] = {k: v for k, v in payload["parameters"].items() if v is not None}
            
            async with self.client.stream("POST", "/services/aigc/text-generation/generation", json=payload) as stream:
                stream.raise_for_status()
                async for line in stream.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()  # Remove "data:" prefix
                        if not data_str or data_str == "[DONE]":
                            break
                        
                        try:
                            import json
                            chunk_data = json.loads(data_str)
                            if "output" in chunk_data:
                                output = chunk_data["output"]
                                if "text" in output and output["text"]:
                                    yield {
                                        "content": output["text"],
                                        "finish_reason": output.get("finish_reason"),
                                        "model": self.config.model_name
                                    }
                        except json.JSONDecodeError:
                            continue  # Skip invalid JSON chunks
                            
        except Exception as e:
            self.logger.error(f"Qwen streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str], **kwargs) -> List[List[float]]:
        """Generate embeddings using Qwen."""
        if not self.client:
            raise RuntimeError("Qwen client not initialized")
        
        try:
            # Qwen embeddings use a different API endpoint
            embeddings = []
            
            for text in texts:
                payload = {
                    "model": "text-embedding-v1",
                    "input": {
                        "texts": [text]
                    }
                }
                
                response = await self.client.post("/services/embeddings/text-embedding/text-embedding", json=payload)
                response.raise_for_status()
                
                data = response.json()
                embedding = data["output"]["embeddings"][0]["embedding"]
                embeddings.append(embedding)
            
            return embeddings
            
        except Exception as e:
            self.logger.error(f"Qwen embeddings failed: {e}")
            raise
    
    def is_available(self) -> bool:
        """Check if Qwen is available."""
        return self.client is not None and self.config.api_key is not None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()



class AzureOpenAIAdapter(AIModelAdapter):
    """Azure OpenAI API adapter."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Azure OpenAI client."""
        try:
            import openai
            self.client = openai.AsyncAzureOpenAI(
                api_key=self.config.api_key,
                azure_endpoint=self.config.azure_endpoint,
                azure_deployment=self.config.azure_deployment,
                api_version=self.config.api_version or "2024-02-15-preview",
                timeout=self.config.timeout
            )
            self.logger.info("Azure OpenAI client initialized")
        except ImportError:
            self.logger.error("OpenAI package not available. Install with: pip install openai")
        except Exception as e:
            self.logger.error(f"Failed to initialize Azure OpenAI client: {e}")
    
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion using Azure OpenAI API."""
        if not self.client:
            raise RuntimeError("Azure OpenAI client not available")
        
        try:
            # Convert messages to OpenAI format
            openai_messages = [
                {"role": msg.role, "content": msg.content} 
                for msg in messages
            ]
            
            # Merge config with kwargs
            params = {
                "model": self.config.azure_deployment or self.config.model_name,
                "messages": openai_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "frequency_penalty": self.config.frequency_penalty,
                "presence_penalty": self.config.presence_penalty,
                **kwargs
            }
            
            response = await self.client.chat.completions.create(**params)
            
            return ModelResponse(
                content=response.choices[0].message.content,
                model=response.model,
                provider=ModelProvider.AZURE_OPENAI,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                } if response.usage else None,
                finish_reason=response.choices[0].finish_reason
            )
            
        except Exception as e:
            self.logger.error(f"Azure OpenAI chat completion failed: {e}")
            raise
    
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens."""
        if not self.client:
            raise RuntimeError("Azure OpenAI client not available")
        
        try:
            openai_messages = [
                {"role": msg.role, "content": msg.content} 
                for msg in messages
            ]
            
            params = {
                "model": self.config.azure_deployment or self.config.model_name,
                "messages": openai_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "stream": True,
                **kwargs
            }
            
            stream = await self.client.chat.completions.create(**params)
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            self.logger.error(f"Azure OpenAI streaming failed: {e}")
            raise
    
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using Azure OpenAI API."""
        if not self.client:
            raise RuntimeError("Azure OpenAI client not available")
        
        try:
            response = await self.client.embeddings.create(
                model=self.config.azure_deployment or "text-embedding-ada-002",
                input=texts
            )
            
            return [embedding.embedding for embedding in response.data]
            
        except Exception as e:
            self.logger.error(f"Azure OpenAI embeddings failed: {e}")
            raise

    async def speech_to_text(self, audio_data: bytes, **kwargs) -> str:
        """Convert speech to text using Azure OpenAI Whisper API."""
        if not self.client:
            raise RuntimeError("Azure OpenAI client not available")
        
        try:
            # Create a temporary file-like object from audio data
            import io
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"  # Azure OpenAI API requires a filename
            
            response = await self.client.audio.transcriptions.create(
                model=kwargs.get("model", "whisper-1"),
                file=audio_file,
                language=kwargs.get("language", self.config.tts_language),
                response_format=kwargs.get("response_format", "text")
            )
            
            return response.text if hasattr(response, 'text') else str(response)
            
        except Exception as e:
            self.logger.error(f"Azure OpenAI speech-to-text failed: {e}")
            raise
    
    async def text_to_speech(self, text: str, **kwargs) -> bytes:
        """Convert text to speech using Azure OpenAI TTS API."""
        if not self.client:
            raise RuntimeError("Azure OpenAI client not available")
        
        try:
            response = await self.client.audio.speech.create(
                model=kwargs.get("model", "tts-1"),
                voice=kwargs.get("voice", self.config.tts_voice or "alloy"),
                input=text,
                response_format=kwargs.get("response_format", "mp3")
            )
            
            return response.content
            
        except Exception as e:
            self.logger.error(f"Azure OpenAI text-to-speech failed: {e}")
            raise
    
    def supports_speech_to_text(self) -> bool:
        """Azure OpenAI supports speech-to-text via Whisper."""
        return True
        
    def supports_text_to_speech(self) -> bool:
        """Azure OpenAI supports text-to-speech."""
        return True
    
    def is_available(self) -> bool:
        """Check if Azure OpenAI is available."""
        return self.client is not None and self.config.api_key is not None and self.config.azure_endpoint is not None


class LocalAdapter(AIModelAdapter):
    """
    Local AI model adapter placeholder for local/offline models.
    
    This adapter is designed for future implementation of local models
    using libraries like transformers, llama.cpp, or similar.
    Currently provides graceful error handling for production safety.
    """
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.model = None
        self._available = False
        self._error_message = "Local adapter not yet implemented"
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize local model when implementation is ready."""
        try:
            # Future implementation would load local model here
            # Examples:
            # - self.model = transformers.AutoModelForCausalLM.from_pretrained(model_name)
            # - self.model = llama_cpp.Llama(model_path=model_path)
            # - self.model = your_local_model_loader(config)
            
            self.logger.info("LocalAdapter: Placeholder implementation - no local model loaded")
            self._error_message = "LocalAdapter is a placeholder - configure a different provider"
            
        except Exception as e:
            self.logger.error(f"Failed to initialize local model: {e}")
            self._error_message = f"Local model initialization failed: {e}"
    
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion using local model."""
        self.logger.error("LocalAdapter: chat_completion called but no implementation available")
        
        # Return a graceful error response instead of crashing
        return ModelResponse(
            content=f"Error: {self._error_message}. Please configure OpenAI, Anthropic, or another supported provider.",
            model="local-placeholder",
            provider=self.config.provider,
            usage=None,
            finish_reason="error"
        )
    
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens from local model."""
        self.logger.error("LocalAdapter: stream_chat_completion called but no implementation available")
        
        # Return a single error message instead of crashing
        yield f"Error: {self._error_message}. Please configure OpenAI, Anthropic, or another supported provider."
    
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using local model."""
        self.logger.error("LocalAdapter: generate_embeddings called but no implementation available")
        
        # Return empty embeddings instead of crashing
        # This allows the system to continue functioning even if embeddings fail
        return [[0.0] * 768 for _ in texts]  # Return standard embedding dimension
    
    def is_available(self) -> bool:
        """Check if local model is available."""
        return self._available
    
    def get_error_message(self) -> str:
        """Get current error message for diagnostics."""
        return self._error_message
    
    def supports_streaming(self) -> bool:
        """LocalAdapter placeholder does not support streaming."""
        return False
    
    def supports_embeddings(self) -> bool:
        """LocalAdapter placeholder does not support embeddings."""
        return False

class LocalSpeechAdapter(AIModelAdapter):
    """Local speech processing adapter using open source models."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.whisper_model = None
        self.tts_engine = None
        self._initialize_speech_models()
    
    def _initialize_speech_models(self):
        """Initialize local speech models."""
        # Initialize local Whisper model
        try:
            import whisper
            
            model_size = self.config.whisper_model_size or "base"
            self.whisper_model = whisper.load_model(model_size)
            self.logger.info(f"Local Whisper model '{model_size}' loaded successfully")
            
        except ImportError:
            self.logger.warning("whisper package not installed. Install with: pip install openai-whisper")
        except Exception as e:
            self.logger.error(f"Failed to load Whisper model: {e}")
        
        # Initialize TTS engine
        try:
            import pyttsx3
            
            self.tts_engine = pyttsx3.init()
            
            # Configure TTS settings
            if self.config.tts_voice:
                voices = self.tts_engine.getProperty('voices')
                for voice in voices:
                    if self.config.tts_voice.lower() in voice.name.lower():
                        self.tts_engine.setProperty('voice', voice.id)
                        break
            
            # Set speech rate and volume
            self.tts_engine.setProperty('rate', 150)  # Speed of speech
            self.tts_engine.setProperty('volume', 0.9)  # Volume level (0.0 to 1.0)
            
            self.logger.info("Local TTS engine initialized successfully")
            
        except ImportError:
            self.logger.warning("pyttsx3 package not installed. Install with: pip install pyttsx3")
        except Exception as e:
            self.logger.error(f"Failed to initialize TTS engine: {e}")
    
    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """LocalSpeechAdapter doesn't support chat completion."""
        raise NotImplementedError("LocalSpeechAdapter is specialized for speech processing only")
    
    async def stream_chat_completion(self, messages: List[ChatMessage], **kwargs) -> AsyncIterator[str]:
        """LocalSpeechAdapter doesn't support streaming chat."""
        raise NotImplementedError("LocalSpeechAdapter is specialized for speech processing only")
    
    async def generate_embeddings(self, texts: List[str], **kwargs) -> List[List[float]]:
        """LocalSpeechAdapter doesn't support embeddings."""
        raise NotImplementedError("LocalSpeechAdapter is specialized for speech processing only")
    
    async def speech_to_text(self, audio_data: bytes, **kwargs) -> str:
        """Convert speech to text using local Whisper model."""
        if not self.whisper_model:
            raise RuntimeError("Local Whisper model not available")
        
        try:
            import tempfile
            import os
            import numpy as np
            from pydub import AudioSegment
            
            # Create temporary file for audio data
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name
            
            try:
                # Load audio and transcribe
                result = self.whisper_model.transcribe(
                    temp_path,
                    language=kwargs.get("language", self.config.tts_language or "en"),
                    task=kwargs.get("task", "transcribe"),  # or "translate"
                    fp16=kwargs.get("fp16", True),
                    verbose=kwargs.get("verbose", False)
                )
                
                return result["text"].strip()

            finally:
                # Clean up temporary file - ensure cleanup even on exceptions
                import time
                cleanup_attempts = 3
                for attempt in range(cleanup_attempts):
                    try:
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                            break
                    except OSError as cleanup_error:
                        if attempt == cleanup_attempts - 1:
                            self.logger.error(f"Failed to clean up temporary file after {cleanup_attempts} attempts: {cleanup_error}")
                        else:
                            time.sleep(0.1)  # Brief delay before retry
                    
        except ImportError as e:
            missing_pkg = str(e).split("'")[1] if "'" in str(e) else "required package"
            self.logger.error(f"Missing dependency for local speech processing: {missing_pkg}")
            self.logger.error("Install with: pip install openai-whisper pydub")
            raise RuntimeError(f"Missing dependency: {missing_pkg}")
        except Exception as e:
            self.logger.error(f"Local speech-to-text failed: {e}")
            raise
    
    async def text_to_speech(self, text: str, **kwargs) -> bytes:
        """Convert text to speech using local TTS engine."""
        if not self.tts_engine:
            raise RuntimeError("Local TTS engine not available")
        
        try:
            import tempfile
            import os
            from concurrent.futures import ThreadPoolExecutor
            import asyncio
            
            # Create temporary file for audio output
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_path = temp_file.name
            
            try:
                # Run TTS in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                
                def _generate_speech():
                    # Save speech to file
                    self.tts_engine.save_to_file(text, temp_path)
                    self.tts_engine.runAndWait()
                
                with ThreadPoolExecutor() as executor:
                    await loop.run_in_executor(executor, _generate_speech)
                
                # Read generated audio file
                with open(temp_path, "rb") as audio_file:
                    audio_data = audio_file.read()
                
                return audio_data

            finally:
                # Clean up temporary file - ensure cleanup even on exceptions
                import time
                cleanup_attempts = 3
                for attempt in range(cleanup_attempts):
                    try:
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                            break
                    except OSError as cleanup_error:
                        if attempt == cleanup_attempts - 1:
                            self.logger.error(f"Failed to clean up temporary file after {cleanup_attempts} attempts: {cleanup_error}")
                        else:
                            time.sleep(0.1)  # Brief delay before retry
                    
        except Exception as e:
            self.logger.error(f"Local text-to-speech failed: {e}")
            raise
    
    async def text_to_speech_gtts(self, text: str, **kwargs) -> bytes:
        """Alternative TTS using Google Text-to-Speech (requires internet)."""
        try:
            from gtts import gTTS
            import io
            
            # Create gTTS object
            tts = gTTS(
                text=text,
                lang=kwargs.get("language", self.config.tts_language or "en"),
                slow=kwargs.get("slow", False)
            )
            
            # Save to bytes buffer
            audio_buffer = io.BytesIO()
            tts.write_to_fp(audio_buffer)
            audio_buffer.seek(0)
            
            return audio_buffer.read()
            
        except ImportError:
            self.logger.error("gTTS package not installed. Install with: pip install gtts")
            raise RuntimeError("gTTS package not available")
        except Exception as e:
            self.logger.error(f"gTTS text-to-speech failed: {e}")
            raise
    
    def supports_speech_to_text(self) -> bool:
        """Check if local speech-to-text is available."""
        return self.whisper_model is not None
        
    def supports_text_to_speech(self) -> bool:
        """Check if local text-to-speech is available."""
        return self.tts_engine is not None
    
    def is_available(self) -> bool:
        """Check if local speech processing is available."""
        return self.whisper_model is not None or self.tts_engine is not None
    
    def get_available_whisper_models(self) -> List[str]:
        """Get list of available Whisper model sizes."""
        return ["tiny", "base", "small", "medium", "large", "large-v1", "large-v2", "large-v3"]
    
    def get_available_languages(self) -> List[str]:
        """Get list of supported languages for speech processing."""
        # Whisper supported languages
        return [
            "en", "zh", "de", "es", "ru", "ko", "fr", "ja", "pt", "tr", "pl", "ca", "nl", 
            "ar", "sv", "it", "id", "hi", "fi", "vi", "he", "uk", "el", "ms", "cs", "ro", 
            "da", "hu", "ta", "no", "th", "ur", "hr", "bg", "lt", "la", "mi", "ml", "cy", 
            "sk", "te", "fa", "lv", "bn", "sr", "az", "sl", "kn", "et", "mk", "br", "eu", 
            "is", "hy", "ne", "mn", "bs", "kk", "sq", "sw", "gl", "mr", "pa", "si", "km", 
            "sn", "yo", "so", "af", "oc", "ka", "be", "tg", "sd", "gu", "am", "yi", "lo", 
            "uz", "fo", "ht", "ps", "tk", "nn", "mt", "sa", "lb", "my", "bo", "tl", "mg", 
            "as", "tt", "haw", "ln", "ha", "ba", "jw", "su"
        ]


class HuggingFaceSpeechAdapter(AIModelAdapter):
    """HuggingFace speech processing adapter using transformers."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self.speech_model = None
        self.tts_model = None
        self.processor = None
        self._initialize_models()
    
    def _initialize_models(self):
        """Initialize HuggingFace speech models."""
        try:
            from transformers import WhisperProcessor, WhisperForConditionalGeneration
            import torch
            
            # Initialize Whisper model for STT
            model_name = self.config.model_name or "openai/whisper-base"
            self.processor = WhisperProcessor.from_pretrained(model_name)
            self.speech_model = WhisperForConditionalGeneration.from_pretrained(model_name)
            
            # Move to GPU if available
            if torch.cuda.is_available():
                self.speech_model = self.speech_model.to("cuda")
                self.logger.info("Using GPU for speech processing")
            
            self.logger.info(f"HuggingFace Whisper model '{model_name}' loaded successfully")
            
        except ImportError:
            self.logger.warning("transformers package not installed. Install with: pip install transformers torch")
        except Exception as e:
            self.logger.error(f"Failed to load HuggingFace models: {e}")
    
    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """HuggingFaceSpeechAdapter doesn't support chat completion."""
        raise NotImplementedError("HuggingFaceSpeechAdapter is specialized for speech processing only")
    
    async def stream_chat_completion(self, messages: List[ChatMessage], **kwargs) -> AsyncIterator[str]:
        """HuggingFaceSpeechAdapter doesn't support streaming chat."""
        raise NotImplementedError("HuggingFaceSpeechAdapter is specialized for speech processing only")
    
    async def generate_embeddings(self, texts: List[str], **kwargs) -> List[List[float]]:
        """HuggingFaceSpeechAdapter doesn't support embeddings."""
        raise NotImplementedError("HuggingFaceSpeechAdapter is specialized for speech processing only")
    
    async def speech_to_text(self, audio_data: bytes, **kwargs) -> str:
        """Convert speech to text using HuggingFace Whisper."""
        if not self.speech_model or not self.processor:
            raise RuntimeError("HuggingFace speech models not available")
        
        try:
            import torch
            import librosa
            import numpy as np
            import io
            from concurrent.futures import ThreadPoolExecutor
            import asyncio
            
            def _process_audio():
                # Convert audio bytes to numpy array
                audio_io = io.BytesIO(audio_data)
                
                # Load audio with librosa
                audio_array, sample_rate = librosa.load(audio_io, sr=16000)  # Whisper expects 16kHz
                
                # Process with HuggingFace processor
                input_features = self.processor(
                    audio_array, 
                    sampling_rate=sample_rate, 
                    return_tensors="pt"
                ).input_features
                
                # Move to GPU if available
                if torch.cuda.is_available():
                    input_features = input_features.to("cuda")
                
                # Generate transcription
                with torch.no_grad():
                    predicted_ids = self.speech_model.generate(input_features)
                
                # Decode the transcription
                transcription = self.processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
                return transcription.strip()
            
            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, _process_audio)
            
            return result
            
        except ImportError as e:
            missing_pkg = str(e).split("'")[1] if "'" in str(e) else "required package"
            self.logger.error(f"Missing dependency: {missing_pkg}")
            self.logger.error("Install with: pip install transformers torch librosa")
            raise RuntimeError(f"Missing dependency: {missing_pkg}")
        except Exception as e:
            self.logger.error(f"HuggingFace speech-to-text failed: {e}")
            raise
    
    async def text_to_speech(self, text: str, **kwargs) -> bytes:
        """Text-to-speech using HuggingFace models (placeholder - requires specific TTS model)."""
        try:
            from transformers import SpeechT5Processor, SpeechT5ForTextToSpeech, SpeechT5HifiGan
            import torch
            import numpy as np
            import soundfile as sf
            import io
            from concurrent.futures import ThreadPoolExecutor
            import asyncio
            
            def _generate_speech():
                # Initialize TTS models if not already done
                if not hasattr(self, '_tts_processor'):
                    self._tts_processor = SpeechT5Processor.from_pretrained("microsoft/speecht5_tts")
                    self._tts_model = SpeechT5ForTextToSpeech.from_pretrained("microsoft/speecht5_tts")
                    self._vocoder = SpeechT5HifiGan.from_pretrained("microsoft/speecht5_hifigan")
                
                # Process text
                inputs = self._tts_processor(text=text, return_tensors="pt")
                
                # Generate speech
                with torch.no_grad():
                    # Note: SpeechT5 requires speaker embeddings - using default
                    speaker_embeddings = torch.zeros((1, 512))  # Default speaker embedding
                    speech = self._tts_model.generate_speech(inputs["input_ids"], speaker_embeddings, vocoder=self._vocoder)
                
                # Convert to audio bytes
                audio_buffer = io.BytesIO()
                sf.write(audio_buffer, speech.numpy(), 16000, format='WAV')
                audio_buffer.seek(0)
                
                return audio_buffer.read()
            
            # Run in thread pool
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, _generate_speech)
            
            return result
            
        except ImportError as e:
            missing_pkg = str(e).split("'")[1] if "'" in str(e) else "required package"
            self.logger.error(f"Missing dependency: {missing_pkg}")
            self.logger.error("Install with: pip install transformers torch soundfile")
            raise RuntimeError(f"Missing dependency: {missing_pkg}")
        except Exception as e:
            self.logger.error(f"HuggingFace text-to-speech failed: {e}")
            raise
    
    def supports_speech_to_text(self) -> bool:
        """Check if speech-to-text is available."""
        return self.speech_model is not None and self.processor is not None
        
    def supports_text_to_speech(self) -> bool:
        """Check if text-to-speech is available."""
        return True  # Can initialize TTS models on demand
    
    def is_available(self) -> bool:
        """Check if HuggingFace models are available."""
        return self.speech_model is not None and self.processor is not None

class ModelManager:
    """Manager for multiple AI model adapters."""
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        app: Optional['Flask'] = None,
        session_factory: Optional[Callable] = None
    ):
        """
        Initialize ModelManager with optional configuration and dependencies.
        
        Args:
            config: Optional configuration dictionary
            app: Optional Flask app instance for loading configurations
            session_factory: Optional session factory for database operations
        """
        self.adapters: Dict[str, AIModelAdapter] = {}
        self.default_adapter: Optional[str] = None
        self.config = config or {}
        self.session_factory = session_factory
        self.logger = logging.getLogger(__name__)
        
        # Auto-initialize from Flask app if provided
        if app:
            self._initialize_from_app(app)

    def _initialize_from_app(self, app: 'Flask') -> None:
        """
        Initialize model adapters from Flask app configuration.
        
        Args:
            app: Flask application instance
        """
        try:
            # Load configurations from app
            configs = load_model_configs_from_app(app)
            
            # Create and register adapters
            for name, config in configs.items():
                try:
                    adapter = create_model_adapter(config)
                    is_default = (name == 'openai')  # Default to OpenAI as primary
                    self.register_adapter(name, adapter, is_default=is_default)
                    self.logger.debug(f"Registered AI adapter from app config: {name}")
                except Exception as e:
                    self.logger.warning(f"Failed to create adapter {name} from app config: {e}")
                    
        except Exception as e:
            self.logger.error(f"Failed to initialize adapters from app: {e}")
    
    def register_adapter(self, name: str, adapter: AIModelAdapter, is_default: bool = False):
        """Register an AI model adapter."""
        self.adapters[name] = adapter
        if is_default or not self.default_adapter:
            self.default_adapter = name
        self.logger.info(f"Registered AI model adapter: {name}")
    
    def get_adapter(self, name: Optional[str] = None) -> AIModelAdapter:
        """Get AI model adapter by name or default."""
        adapter_name = name or self.default_adapter
        if not adapter_name or adapter_name not in self.adapters:
            raise ValueError(f"AI model adapter '{adapter_name}' not found")
        
        adapter = self.adapters[adapter_name]
        if not adapter.is_available():
            raise RuntimeError(f"AI model adapter '{adapter_name}' is not available")
        
        return adapter
    
    def list_available_adapters(self) -> List[str]:
        """List all available AI model adapters."""
        return [name for name, adapter in self.adapters.items() if adapter.is_available()]
    
    async def chat_completion(
        self, 
        messages: List[ChatMessage], 
        model: Optional[str] = None,
        **kwargs
    ) -> ModelResponse:
        """Generate chat completion using specified or default model."""
        adapter = self.get_adapter(model)
        return await adapter.chat_completion(messages, **kwargs)
    
    async def stream_chat_completion(
        self, 
        messages: List[ChatMessage], 
        model: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat completion using specified or default model."""
        adapter = self.get_adapter(model)
        async for token in adapter.stream_chat_completion(messages, **kwargs):
            yield token

    async def generate_embeddings(
        self, 
        texts: List[str], 
        model: Optional[str] = None,
        **kwargs
    ) -> List[List[float]]:
        """Generate embeddings using specified or default model."""
        adapter = self.get_adapter(model)
        return await adapter.generate_embeddings(texts, **kwargs)
    
    def get_embedding_capable_adapters(self) -> List[str]:
        """Get list of adapter names that support embeddings."""
        capable_adapters = []
        
        for name, adapter in self.adapters.items():
            # Check if the adapter supports embeddings
            try:
                # Look for methods that don't raise NotImplementedError
                if hasattr(adapter, 'generate_embeddings'):
                    # Check if it's a real implementation or just raises NotImplementedError
                    import inspect
                    source = inspect.getsource(adapter.generate_embeddings)
                    if 'NotImplementedError' not in source:
                        capable_adapters.append(name)
            except Exception:
                continue
        
        return capable_adapters
    
    def get_provider_capabilities(self) -> Dict[str, Dict[str, bool]]:
        """Get capabilities matrix for all registered providers."""
        capabilities = {}
        
        for name, adapter in self.adapters.items():
            provider_caps = {
                'chat_completion': True,  # All adapters support this
                'streaming': hasattr(adapter, 'stream_chat_completion'),
                'embeddings': self._supports_embeddings(adapter),
                'speech_to_text': self._supports_speech_to_text(adapter),
                'text_to_speech': self._supports_text_to_speech(adapter)
            }
            capabilities[name] = provider_caps
        
        return capabilities
    
    def _supports_embeddings(self, adapter: AIModelAdapter) -> bool:
        """Check if adapter supports embeddings."""
        if not hasattr(adapter, 'generate_embeddings'):
            return False
        
        try:
            import inspect
            source = inspect.getsource(adapter.generate_embeddings)
            return 'NotImplementedError' not in source
        except Exception:
            return False
    
    def _supports_speech_to_text(self, adapter: AIModelAdapter) -> bool:
        """Check if adapter supports speech-to-text."""
        if hasattr(adapter, 'supports_speech_to_text'):
            return adapter.supports_speech_to_text()
        return False
    
    def _supports_text_to_speech(self, adapter: AIModelAdapter) -> bool:
        """Check if adapter supports text-to-speech."""
        if hasattr(adapter, 'supports_text_to_speech'):
            return adapter.supports_text_to_speech()
        return False
    
    def recommend_embedding_provider(self) -> Optional[str]:
        """Recommend a provider that supports embeddings."""
        embedding_adapters = self.get_embedding_capable_adapters()
        
        if not embedding_adapters:
            return None
        
        # Prefer certain providers for embeddings
        preferred_order = ['openai', 'azure_openai', 'mistral', 'kimi', 'qwen', 'openrouter']
        
        for preferred in preferred_order:
            if preferred in embedding_adapters:
                return preferred
        
        # Return first available if no preferred found
        return embedding_adapters[0]


def create_model_adapter(config: ModelConfig) -> AIModelAdapter:
    """
    Factory function to create the appropriate AI model adapter.
    
    Args:
        config: ModelConfig instance with provider and settings
        
    Returns:
        Initialized AIModelAdapter instance
        
    Raises:
        ValueError: If provider is not supported
        RuntimeError: If adapter initialization fails
    """
    provider_map = {
        ModelProvider.OPENAI: OpenAIAdapter,
        ModelProvider.ANTHROPIC: AnthropicAdapter,
        ModelProvider.AZURE_OPENAI: AzureOpenAIAdapter,
        ModelProvider.GOOGLE: GoogleGeminiAdapter,
        ModelProvider.OLLAMA: OllamaAdapter,
        ModelProvider.OPENROUTER: OpenRouterAdapter,
        ModelProvider.MISTRAL: MistralAdapter,
        ModelProvider.GROQ: GroqAdapter,
        ModelProvider.GROK: GrokAdapter,
        ModelProvider.DEEPSEEK: DeepseekAdapter,
        ModelProvider.KIMI: KimiAdapter,
        ModelProvider.QWEN: QwenAdapter,
        ModelProvider.LOCAL_SPEECH: LocalSpeechAdapter,
        ModelProvider.HUGGINGFACE_SPEECH: HuggingFaceSpeechAdapter,
        # Add legacy/fallback providers as they get implemented
        ModelProvider.HUGGINGFACE: LocalAdapter,  # Placeholder
        ModelProvider.LOCAL: LocalAdapter  # Placeholder
    }
    
    if config.provider not in provider_map:
        raise ValueError(f"Unsupported provider: {config.provider}")
    
    adapter_class = provider_map[config.provider]
    
    try:
        adapter = adapter_class(config)
        
        # Validate adapter availability
        if not adapter.is_available():
            raise RuntimeError(f"Adapter for {config.provider.value} is not available - check configuration and dependencies")
        
        return adapter
        
    except Exception as e:
        raise RuntimeError(f"Failed to create adapter for {config.provider.value}: {e}") from e


def load_model_configs_from_app(app) -> Dict[str, ModelConfig]:
    """Load AI model configurations from Flask app config with secure credential handling."""
    configs = {}
    
    def _get_secure_credential(key: str, default: Optional[str] = None) -> Optional[str]:
        """Securely retrieve API credentials with proper validation."""
        # First try environment variables (more secure)
        import os
        env_value = os.environ.get(key)
        if env_value:
            # Validate credential format
            if key.endswith('_API_KEY') and len(env_value) < 10:
                logging.warning(f"API key {key} appears to be too short")
                return None
            return env_value
        
        # Fallback to app config (for development)
        config_value = app.config.get(key, default)
        if config_value and key.endswith('_API_KEY'):
            if len(config_value) < 10:
                logging.warning(f"API key {key} from config appears to be too short")
                return None
            # Mask the key for logging
            masked_key = config_value[:8] + "..." + config_value[-4:] if len(config_value) > 12 else "***"
            logging.info(f"Loaded {key}: {masked_key}")
        
        return config_value

    # OpenAI configuration with secure credential loading
    openai_api_key = _get_secure_credential('OPENAI_API_KEY')
    if openai_api_key:
        configs['openai'] = ModelConfig(
            provider=ModelProvider.OPENAI,
            model_name=_get_secure_credential('OPENAI_MODEL', 'gpt-4'),
            api_key=openai_api_key,
            api_base=_get_secure_credential('OPENAI_API_BASE'),
            max_tokens=int(_get_secure_credential('OPENAI_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('OPENAI_TEMPERATURE', '0.7')),
            whisper_model_size=_get_secure_credential('OPENAI_WHISPER_MODEL', 'base'),
            tts_voice=_get_secure_credential('OPENAI_TTS_VOICE', 'alloy')
        )

    # Anthropic configuration with secure credential loading
    anthropic_api_key = _get_secure_credential('ANTHROPIC_API_KEY')
    if anthropic_api_key:
        configs['anthropic'] = ModelConfig(
            provider=ModelProvider.ANTHROPIC,
            model_name=_get_secure_credential('ANTHROPIC_MODEL', 'claude-3-sonnet-20240229'),
            api_key=anthropic_api_key,
            max_tokens=int(_get_secure_credential('ANTHROPIC_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('ANTHROPIC_TEMPERATURE', '0.7'))
        )

    # Azure OpenAI configuration with secure credential loading
    azure_api_key = _get_secure_credential('AZURE_OPENAI_API_KEY')
    azure_endpoint = _get_secure_credential('AZURE_OPENAI_ENDPOINT')
    if azure_api_key and azure_endpoint:
        configs['azure_openai'] = ModelConfig(
            provider=ModelProvider.AZURE_OPENAI,
            model_name=_get_secure_credential('AZURE_OPENAI_MODEL', 'gpt-4'),
            api_key=azure_api_key,
            azure_endpoint=azure_endpoint,
            azure_deployment=_get_secure_credential('AZURE_OPENAI_DEPLOYMENT'),
            api_version=_get_secure_credential('AZURE_OPENAI_API_VERSION', '2024-02-15-preview'),
            max_tokens=int(_get_secure_credential('AZURE_OPENAI_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('AZURE_OPENAI_TEMPERATURE', '0.7'))
        )

    # Google Gemini configuration
    google_api_key = _get_secure_credential('GOOGLE_API_KEY')
    if google_api_key:
        configs['google'] = ModelConfig(
            provider=ModelProvider.GOOGLE,
            model_name=_get_secure_credential('GOOGLE_MODEL', 'gemini-1.5-pro'),
            api_key=google_api_key,
            google_project_id=_get_secure_credential('GOOGLE_PROJECT_ID'),
            google_location=_get_secure_credential('GOOGLE_LOCATION', 'us-central1'),
            max_tokens=int(_get_secure_credential('GOOGLE_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('GOOGLE_TEMPERATURE', '0.7'))
        )

    # Ollama configuration (local server)
    ollama_host = _get_secure_credential('OLLAMA_HOST', 'http://localhost:11434')
    if ollama_host:
        configs['ollama'] = ModelConfig(
            provider=ModelProvider.OLLAMA,
            model_name=_get_secure_credential('OLLAMA_MODEL', 'llama2'),
            api_key=_get_secure_credential('OLLAMA_API_KEY'),  # Optional for Ollama
            ollama_host=ollama_host,
            max_tokens=int(_get_secure_credential('OLLAMA_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('OLLAMA_TEMPERATURE', '0.7'))
        )

    # OpenRouter configuration
    openrouter_api_key = _get_secure_credential('OPENROUTER_API_KEY')
    if openrouter_api_key:
        configs['openrouter'] = ModelConfig(
            provider=ModelProvider.OPENROUTER,
            model_name=_get_secure_credential('OPENROUTER_MODEL', 'anthropic/claude-3-sonnet'),
            api_key=openrouter_api_key,
            max_tokens=int(_get_secure_credential('OPENROUTER_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('OPENROUTER_TEMPERATURE', '0.7'))
        )

    # Mistral configuration
    mistral_api_key = _get_secure_credential('MISTRAL_API_KEY')
    if mistral_api_key:
        configs['mistral'] = ModelConfig(
            provider=ModelProvider.MISTRAL,
            model_name=_get_secure_credential('MISTRAL_MODEL', 'mistral-large-latest'),
            api_key=mistral_api_key,
            max_tokens=int(_get_secure_credential('MISTRAL_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('MISTRAL_TEMPERATURE', '0.7'))
        )

    # Groq configuration
    groq_api_key = _get_secure_credential('GROQ_API_KEY')
    if groq_api_key:
        configs['groq'] = ModelConfig(
            provider=ModelProvider.GROQ,
            model_name=_get_secure_credential('GROQ_MODEL', 'mixtral-8x7b-32768'),
            api_key=groq_api_key,
            max_tokens=int(_get_secure_credential('GROQ_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('GROQ_TEMPERATURE', '0.7'))
        )

    # Grok (xAI) configuration
    grok_api_key = _get_secure_credential('GROK_API_KEY')
    if grok_api_key:
        configs['grok'] = ModelConfig(
            provider=ModelProvider.GROK,
            model_name=_get_secure_credential('GROK_MODEL', 'grok-beta'),
            api_key=grok_api_key,
            max_tokens=int(_get_secure_credential('GROK_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('GROK_TEMPERATURE', '0.7'))
        )

    # Deepseek configuration
    deepseek_api_key = _get_secure_credential('DEEPSEEK_API_KEY')
    if deepseek_api_key:
        configs['deepseek'] = ModelConfig(
            provider=ModelProvider.DEEPSEEK,
            model_name=_get_secure_credential('DEEPSEEK_MODEL', 'deepseek-chat'),
            api_key=deepseek_api_key,
            max_tokens=int(_get_secure_credential('DEEPSEEK_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('DEEPSEEK_TEMPERATURE', '0.7'))
        )

    # Kimi (Moonshot AI) configuration
    kimi_api_key = _get_secure_credential('KIMI_API_KEY')
    if kimi_api_key:
        configs['kimi'] = ModelConfig(
            provider=ModelProvider.KIMI,
            model_name=_get_secure_credential('KIMI_MODEL', 'moonshot-v1-8k'),
            api_key=kimi_api_key,
            max_tokens=int(_get_secure_credential('KIMI_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('KIMI_TEMPERATURE', '0.7'))
        )

    # Qwen (Alibaba) configuration
    qwen_api_key = _get_secure_credential('QWEN_API_KEY')
    if qwen_api_key:
        configs['qwen'] = ModelConfig(
            provider=ModelProvider.QWEN,
            model_name=_get_secure_credential('QWEN_MODEL', 'qwen-turbo'),
            api_key=qwen_api_key,
            max_tokens=int(_get_secure_credential('QWEN_MAX_TOKENS', '2048')),
            temperature=float(_get_secure_credential('QWEN_TEMPERATURE', '0.7'))
        )

    # Local Speech configuration (no API key required)
    whisper_model_size = _get_secure_credential('WHISPER_MODEL_SIZE', 'base')
    tts_voice = _get_secure_credential('TTS_VOICE')
    if whisper_model_size or tts_voice:
        configs['local_speech'] = ModelConfig(
            provider=ModelProvider.LOCAL_SPEECH,
            model_name='local-speech',
            whisper_model_size=whisper_model_size,
            tts_voice=tts_voice,
            tts_language=_get_secure_credential('TTS_LANGUAGE', 'en')
        )

    # HuggingFace Speech configuration (no API key required)
    hf_model_name = _get_secure_credential('HF_SPEECH_MODEL', 'openai/whisper-base')
    if hf_model_name:
        configs['huggingface_speech'] = ModelConfig(
            provider=ModelProvider.HUGGINGFACE_SPEECH,
            model_name=hf_model_name,
            api_key=_get_secure_credential('HF_TOKEN'),  # Optional for public models
            whisper_model_size='base',
            tts_language=_get_secure_credential('TTS_LANGUAGE', 'en')
        )

    # Security validation
    if not configs:
        logging.warning("No AI model configurations loaded - check your environment variables or app config")
    else:
        # Don't log actual credentials, just count
        logging.getLogger(__name__).info(f"Securely loaded {len(configs)} AI model configurations")
    
    return configs