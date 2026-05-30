# AI Provider Configuration

Complete guide to configuring and using all 12+ AI providers supported by Flask-AppBuilder.

## 🌍 Overview

Flask-AppBuilder supports a comprehensive range of AI providers, from major cloud services to local models, enabling you to choose the best solution for your needs.

## 🔧 Configuration Methods

### 1. Environment Variables (Recommended)

The most secure approach for production deployments:

```bash
# .env file
OPENAI_API_KEY=sk-your-openai-api-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
OLLAMA_HOST=http://localhost:11434
```

### 2. Flask Configuration

Direct configuration in your Flask app config:

```python
# config.py
OPENAI_API_KEY = "sk-your-openai-api-key"
ANTHROPIC_API_KEY = "sk-ant-your-anthropic-key"
OLLAMA_HOST = "http://localhost:11434"
```

### 3. Runtime Configuration

Dynamic configuration at runtime:

```python
from flask_appbuilder.collaborative.ai.ai_models import create_model_adapter, ModelConfig, ModelProvider

config = ModelConfig(
    provider=ModelProvider.OPENAI,
    model_name="gpt-4",
    api_key="sk-your-api-key",
    max_tokens=2048,
    temperature=0.7
)

adapter = create_model_adapter(config)
```

## 🏢 Major Cloud Providers

### OpenAI GPT Models

**Capabilities:** Chat completion, embeddings, speech-to-text, text-to-speech, function calling

```python
# Configuration
OPENAI_API_KEY = "sk-your-openai-api-key-here"
OPENAI_MODEL = "gpt-4"  # or gpt-3.5-turbo, gpt-4-turbo
OPENAI_API_BASE = "https://api.openai.com/v1"  # Optional: custom endpoint
OPENAI_MAX_TOKENS = 2048
OPENAI_TEMPERATURE = 0.7

# Speech features
OPENAI_WHISPER_MODEL = "whisper-1"  # For speech-to-text
OPENAI_TTS_VOICE = "alloy"  # alloy, echo, fable, onyx, nova, shimmer
```

**Example Usage:**
```python
from flask_appbuilder.collaborative.ai.ai_models import ModelManager

model_manager = ModelManager(app=app)
response = await model_manager.generate_response(
    messages=[{"role": "user", "content": "Hello!"}],
    provider="openai"
)
```

### Anthropic Claude Models

**Capabilities:** Advanced reasoning, long context, constitutional AI

```python
# Configuration
ANTHROPIC_API_KEY = "sk-ant-your-anthropic-api-key-here"
ANTHROPIC_MODEL = "claude-3-sonnet-20240229"  # or claude-3-opus, claude-3-haiku
ANTHROPIC_MAX_TOKENS = 2048
ANTHROPIC_TEMPERATURE = 0.7
```

**Available Models:**
- `claude-3-opus-20240229` - Most capable, best for complex tasks
- `claude-3-sonnet-20240229` - Balanced performance and speed
- `claude-3-haiku-20240307` - Fastest, best for simple tasks

### Azure OpenAI Service

**Capabilities:** Enterprise OpenAI with compliance and security

```python
# Configuration
AZURE_OPENAI_API_KEY = "your-azure-openai-key"
AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com/"
AZURE_OPENAI_DEPLOYMENT = "gpt-4"  # Your deployment name
AZURE_OPENAI_MODEL = "gpt-4"
AZURE_OPENAI_API_VERSION = "2024-02-15-preview"
AZURE_OPENAI_MAX_TOKENS = 2048
AZURE_OPENAI_TEMPERATURE = 0.7
```

**Setup Guide:**
1. Create Azure OpenAI resource
2. Deploy your chosen model
3. Get endpoint and API key
4. Configure deployment name

### Google Gemini Models

**Capabilities:** Multimodal AI, long context, code generation

```python
# Configuration
GOOGLE_API_KEY = "AIza-your-google-api-key-here"
GOOGLE_MODEL = "gemini-1.5-pro"  # or gemini-1.5-flash, gemini-pro
GOOGLE_PROJECT_ID = "your-gcp-project-id"  # Optional for some models
GOOGLE_LOCATION = "us-central1"  # Optional
GOOGLE_MAX_TOKENS = 2048
GOOGLE_TEMPERATURE = 0.7
```

**Available Models:**
- `gemini-1.5-pro` - Most capable, 2M token context
- `gemini-1.5-flash` - Fast and efficient
- `gemini-pro` - Production-ready model

## 🚀 Specialized Providers

### Ollama (Local Models)

**Capabilities:** Privacy-focused local AI, no API key required

```python
# Configuration
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama2"  # or llama3, mistral, codellama, etc.
OLLAMA_API_KEY = ""  # Optional for secured installations
OLLAMA_MAX_TOKENS = 2048
OLLAMA_TEMPERATURE = 0.7
```

**Setup Guide:**
1. Install Ollama: `curl -fsSL https://ollama.ai/install.sh | sh`
2. Pull a model: `ollama pull llama2`
3. Start server: `ollama serve`
4. Configure Flask-AppBuilder to use local endpoint

**Popular Models:**
- `llama2` - Meta's open-source model
- `llama3` - Latest Meta model
- `mistral` - Mistral AI's efficient model
- `codellama` - Code-specialized model
- `vicuna` - Chat-optimized model

### OpenRouter (Model Aggregator)

**Capabilities:** Access to 100+ models through single API

```python
# Configuration
OPENROUTER_API_KEY = "sk-or-your-openrouter-key-here"
OPENROUTER_MODEL = "anthropic/claude-3-sonnet"  # or openai/gpt-4, etc.
OPENROUTER_MAX_TOKENS = 2048
OPENROUTER_TEMPERATURE = 0.7
```

**Popular Model Routes:**
- `openai/gpt-4` - OpenAI GPT-4
- `anthropic/claude-3-sonnet` - Anthropic Claude
- `google/gemini-pro` - Google Gemini
- `meta-llama/llama-3-70b` - Meta Llama
- `mistralai/mistral-large` - Mistral Large

### Mistral AI

**Capabilities:** European AI, efficient models, strong reasoning

```python
# Configuration
MISTRAL_API_KEY = "your-mistral-api-key-here"
MISTRAL_MODEL = "mistral-large-latest"  # or mistral-medium, mistral-small
MISTRAL_MAX_TOKENS = 2048
MISTRAL_TEMPERATURE = 0.7
```

**Available Models:**
- `mistral-large-latest` - Most capable
- `mistral-medium-latest` - Balanced performance
- `mistral-small-latest` - Fast and efficient

### Groq (Fast Inference)

**Capabilities:** Ultra-fast inference, optimized hardware

```python
# Configuration
GROQ_API_KEY = "gsk-your-groq-api-key-here"
GROQ_MODEL = "mixtral-8x7b-32768"  # or llama2-70b-4096, gemma-7b-it
GROQ_MAX_TOKENS = 2048
GROQ_TEMPERATURE = 0.7
```

**Available Models:**
- `mixtral-8x7b-32768` - Mistral's mixture of experts
- `llama2-70b-4096` - Meta's Llama 2 70B
- `gemma-7b-it` - Google's Gemma

## 🌏 International Providers

### Grok (xAI)

**Capabilities:** Real-time information, conversational AI

```python
# Configuration
GROK_API_KEY = "xai-your-grok-api-key-here"
GROK_MODEL = "grok-beta"
GROK_MAX_TOKENS = 2048
GROK_TEMPERATURE = 0.7
```

### Deepseek

**Capabilities:** Chinese AI provider, code generation

```python
# Configuration
DEEPSEEK_API_KEY = "sk-your-deepseek-api-key-here"
DEEPSEEK_MODEL = "deepseek-chat"  # or deepseek-coder
DEEPSEEK_MAX_TOKENS = 2048
DEEPSEEK_TEMPERATURE = 0.7
```

### Kimi (Moonshot AI)

**Capabilities:** Long context, conversational AI

```python
# Configuration
KIMI_API_KEY = "sk-your-kimi-api-key-here"
KIMI_MODEL = "moonshot-v1-8k"  # or moonshot-v1-32k, moonshot-v1-128k
KIMI_MAX_TOKENS = 2048
KIMI_TEMPERATURE = 0.7
```

### Qwen (Alibaba)

**Capabilities:** Multilingual, enterprise features

```python
# Configuration
QWEN_API_KEY = "sk-your-qwen-api-key-here"
QWEN_MODEL = "qwen-turbo"  # or qwen-plus, qwen-max
QWEN_MAX_TOKENS = 2048
QWEN_TEMPERATURE = 0.7
```

## 🎙️ Speech Processing

### OpenAI Whisper (Cloud)

**Capabilities:** High-accuracy speech-to-text, 99 languages

```python
# Uses OpenAI API key and configuration
# Automatic when OpenAI is configured
```

### Local Speech Processing

**Capabilities:** Offline speech processing, privacy-focused

```python
# Configuration
WHISPER_MODEL_SIZE = "base"  # tiny, base, small, medium, large, large-v2, large-v3
TTS_VOICE = ""  # System-specific voice name (optional)
TTS_LANGUAGE = "en"  # Language code for TTS
```

**Setup:**
```bash
pip install openai-whisper pyttsx3
```

### HuggingFace Speech

**Capabilities:** Advanced transformer models, custom models

```python
# Configuration
HF_SPEECH_MODEL = "openai/whisper-base"  # or openai/whisper-large-v3
HF_TOKEN = "hf_your-huggingface-token"  # Optional for public models
TTS_LANGUAGE = "en"
```

**Setup:**
```bash
pip install transformers torch librosa soundfile
```

## 🔄 Multi-Provider Setup

### Configuration Examples

**Example 1: Cloud + Local Hybrid**
```python
# Primary cloud providers with local fallback
OPENAI_API_KEY = "sk-your-openai-key"
ANTHROPIC_API_KEY = "sk-ant-your-claude-key"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama2"
```

**Example 2: International Multi-Provider**
```python
# Multiple international providers
DEEPSEEK_API_KEY = "sk-your-deepseek-key"
KIMI_API_KEY = "sk-your-kimi-key"
QWEN_API_KEY = "sk-your-qwen-key"
```

**Example 3: Speed-Optimized**
```python
# Focus on fast inference
GROQ_API_KEY = "gsk-your-groq-key"
GROQ_MODEL = "mixtral-8x7b-32768"
OLLAMA_HOST = "http://localhost:11434"  # Local backup
```

### Provider Priority

The system automatically detects configured providers and sets priorities:

```python
# Explicit priority configuration
from flask_appbuilder.collaborative.ai.ai_models import ModelManager

model_manager = ModelManager(app=app)
model_manager.set_provider_priority([
    'openai',      # Primary
    'anthropic',   # Secondary
    'ollama'       # Local fallback
])
```

## 🔍 Provider Capabilities

| Provider | Chat | Streaming | Embeddings | Speech-to-Text | Text-to-Speech | Function Calling |
|----------|------|-----------|------------|----------------|----------------|------------------|
| OpenAI | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Anthropic | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Azure OpenAI | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Google Gemini | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Ollama | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| OpenRouter | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Mistral | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Groq | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Grok | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Deepseek | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Kimi | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Qwen | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Local Speech | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |
| HF Speech | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |

## 🔧 Troubleshooting

### Common Issues

**1. API Key Not Working**
```python
# Test API key validity
from flask_appbuilder.collaborative.ai.ai_models import test_provider_connection

result = await test_provider_connection('openai')
if not result.success:
    print(f"Connection failed: {result.error}")
```

**2. Local Models Not Starting**
```bash
# Check Ollama status
ollama ps
ollama pull llama2  # Pull model if missing
```

**3. Rate Limiting**
```python
# Configure rate limiting
OPENAI_RATE_LIMIT_RPM = 500  # Requests per minute
OPENAI_RATE_LIMIT_TPM = 100000  # Tokens per minute
```

**4. Timeout Issues**
```python
# Increase timeout for slow providers
OPENAI_TIMEOUT = 60  # seconds
OLLAMA_TIMEOUT = 120  # Local models may be slower
```

### Monitoring Provider Health

```python
# Get provider status
status = await model_manager.get_provider_status()
for provider, health in status.items():
    print(f"{provider}: {health.status} - {health.latency}ms")
```

## 📊 Cost Optimization

### Provider Cost Comparison

| Provider | Model | Cost per 1K tokens (input) | Cost per 1K tokens (output) |
|----------|-------|----------------------------|------------------------------|
| OpenAI | GPT-4 | $0.03 | $0.06 |
| OpenAI | GPT-3.5-turbo | $0.001 | $0.002 |
| Anthropic | Claude-3-Sonnet | $0.003 | $0.015 |
| Google | Gemini Pro | $0.001 | $0.002 |
| Ollama | Local | Free | Free |
| OpenRouter | Various | Variable | Variable |

### Cost Optimization Strategies

1. **Use local models for development**
2. **Implement response caching**
3. **Set token limits appropriately**
4. **Use cheaper models for simple tasks**
5. **Monitor usage with built-in analytics**

## 🚀 Next Steps

1. Choose your providers based on requirements
2. Set up API keys securely
3. Configure provider priorities
4. Test connections
5. Monitor usage and performance

For implementation examples, see [AI Tutorials](../tutorials/ai_chatbot.md).