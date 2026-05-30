import os

from pgappforge.const import AUTH_DB
from pgappforge.exceptions import PasswordComplexityValidationError

basedir = os.path.abspath(os.path.dirname(__file__))

CSRF_ENABLED = True
SECRET_KEY = "\2\1thisismyscretkey\1\2\e\y\y\h"

OPENID_PROVIDERS = [
    {"name": "Google", "url": "https://www.google.com/accounts/o8/id"},
    {"name": "Yahoo", "url": "https://me.yahoo.com"},
    {"name": "AOL", "url": "http://openid.aol.com/<username>"},
    {"name": "Flickr", "url": "http://www.flickr.com/<username>"},
    {"name": "MyOpenID", "url": "https://www.myopenid.com"},
]

SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(basedir, "app.db")
# SQLALCHEMY_DATABASE_URI = 'mysql://username:password@mysqlserver.local/quickhowto'
# SQLALCHEMY_DATABASE_URI = 'postgresql://scott:tiger@localhost:5432/myapp'
# SQLALCHEMY_ECHO = True
SQLALCHEMY_POOL_RECYCLE = 3

BABEL_DEFAULT_LOCALE = "en"
BABEL_DEFAULT_FOLDER = "translations"
LANGUAGES = {
    "en": {"flag": "gb", "name": "English"},
    "pt": {"flag": "pt", "name": "Portuguese"},
    "pt_BR": {"flag": "br", "name": "Pt Brazil"},
    "es": {"flag": "es", "name": "Spanish"},
    "fr": {"flag": "fr", "name": "French"},
    "de": {"flag": "de", "name": "German"},
    "zh": {"flag": "cn", "name": "Chinese"},
    "ru": {"flag": "ru", "name": "Russian"},
    "pl": {"flag": "pl", "name": "Polish"},
    "el": {"flag": "gr", "name": "Greek"},
    "ja_JP": {"flag": "jp", "name": "Japanese"},
}

PGAF_API_MAX_PAGE_SIZE = 100


def custom_password_validator(password: str) -> None:
    """
    A simplistic example for a password validator
    """
    if len(password) < 8:
        raise PasswordComplexityValidationError("Must have at least 8 characters")


# PGAF_PASSWORD_COMPLEXITY_VALIDATOR = custom_password_validator

PGAF_PASSWORD_COMPLEXITY_ENABLED = True

# ------------------------------
# GLOBALS FOR GENERAL APP's
# ------------------------------
UPLOAD_FOLDER = basedir + "/app/static/uploads/"
IMG_UPLOAD_FOLDER = basedir + "/app/static/uploads/"
IMG_UPLOAD_URL = "/static/uploads/"
AUTH_TYPE = AUTH_DB
# AUTH_LDAP_SERVER = "ldap://dc.domain.net"
AUTH_ROLE_ADMIN = "Admin"
AUTH_ROLE_PUBLIC = "Public"
APP_NAME = "F.A.B. Example"
APP_THEME = ""  # default
# APP_THEME = "cerulean.css"      # COOL
# APP_THEME = "amelia.css"
# APP_THEME = "cosmo.css"
# APP_THEME = "cyborg.css"       # COOL
# APP_THEME = "flatly.css"
# APP_THEME = "journal.css"
# APP_THEME = "readable.css"
# APP_THEME = "simplex.css"
# APP_THEME = "slate.css"          # COOL
# APP_THEME = "spacelab.css"      # NICE
# APP_THEME = "united.css"
# APP_THEME = "darkly.css"
# APP_THEME = "lumen.css"
# APP_THEME = "paper.css"
# APP_THEME = "sandstone.css"
# APP_THEME = "solar.css"
# APP_THEME = "superhero.css"


# ------------------------------
# AI MODEL CONFIGURATIONS
# ------------------------------
# PgAppForge AI features support multiple providers.
# Uncomment and configure the providers you want to use.
# You can enable multiple providers simultaneously.

# ===== MAJOR CLOUD PROVIDERS =====

# OpenAI GPT Models with Whisper Speech Processing
# Supports: Chat completion, embeddings, speech-to-text, text-to-speech
# OPENAI_API_KEY = "sk-your-openai-api-key-here"
# OPENAI_MODEL = "gpt-4"  # or gpt-3.5-turbo, gpt-4-turbo, etc.
# OPENAI_API_BASE = "https://api.openai.com/v1"  # Optional: custom endpoint
# OPENAI_MAX_TOKENS = 2048
# OPENAI_TEMPERATURE = 0.7
# OPENAI_WHISPER_MODEL = "whisper-1"  # For speech-to-text
# OPENAI_TTS_VOICE = "alloy"  # alloy, echo, fable, onyx, nova, shimmer

# Anthropic Claude Models
# Supports: Chat completion
# ANTHROPIC_API_KEY = "sk-ant-your-anthropic-api-key-here"
# ANTHROPIC_MODEL = "claude-3-sonnet-20240229"  # or claude-3-opus, claude-3-haiku
# ANTHROPIC_MAX_TOKENS = 2048
# ANTHROPIC_TEMPERATURE = 0.7

# Azure OpenAI Service (Enterprise)
# Supports: Chat completion, embeddings
# AZURE_OPENAI_API_KEY = "your-azure-openai-key"
# AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com/"
# AZURE_OPENAI_DEPLOYMENT = "gpt-4"  # Your deployment name
# AZURE_OPENAI_MODEL = "gpt-4"
# AZURE_OPENAI_API_VERSION = "2024-02-15-preview"
# AZURE_OPENAI_MAX_TOKENS = 2048
# AZURE_OPENAI_TEMPERATURE = 0.7

# Google Gemini Models
# Supports: Chat completion, embeddings
# GOOGLE_API_KEY = "AIza-your-google-api-key-here"
# GOOGLE_MODEL = "gemini-1.5-pro"  # or gemini-1.5-flash, gemini-pro
# GOOGLE_PROJECT_ID = "your-gcp-project-id"  # Optional for some models
# GOOGLE_LOCATION = "us-central1"  # Optional
# GOOGLE_MAX_TOKENS = 2048
# GOOGLE_TEMPERATURE = 0.7

# ===== SPECIALIZED PROVIDERS =====

# Ollama - Local Model Server (Self-hosted)
# Supports: Chat completion, embeddings
# No API key required - runs locally
# OLLAMA_HOST = "http://localhost:11434"
# OLLAMA_MODEL = "llama2"  # or llama3, mistral, codellama, etc.
# OLLAMA_API_KEY = ""  # Optional for secured installations
# OLLAMA_MAX_TOKENS = 2048
# OLLAMA_TEMPERATURE = 0.7

# OpenRouter - AI Model Aggregator
# Supports: Chat completion, embeddings (access to 100+ models)
# OPENROUTER_API_KEY = "sk-or-your-openrouter-key-here"
# OPENROUTER_MODEL = "anthropic/claude-3-sonnet"  # or openai/gpt-4, etc.
# OPENROUTER_MAX_TOKENS = 2048
# OPENROUTER_TEMPERATURE = 0.7

# Mistral AI - European AI Models
# Supports: Chat completion, embeddings
# MISTRAL_API_KEY = "your-mistral-api-key-here"
# MISTRAL_MODEL = "mistral-large-latest"  # or mistral-medium, mistral-small
# MISTRAL_MAX_TOKENS = 2048
# MISTRAL_TEMPERATURE = 0.7

# Groq - Fast Inference Hardware
# Supports: Chat completion (optimized for speed)
# GROQ_API_KEY = "gsk-your-groq-api-key-here"
# GROQ_MODEL = "mixtral-8x7b-32768"  # or llama2-70b-4096, gemma-7b-it
# GROQ_MAX_TOKENS = 2048
# GROQ_TEMPERATURE = 0.7

# ===== INTERNATIONAL PROVIDERS =====

# Grok (xAI) - Elon Musk's AI Company
# Supports: Chat completion
# GROK_API_KEY = "xai-your-grok-api-key-here"
# GROK_MODEL = "grok-beta"
# GROK_MAX_TOKENS = 2048
# GROK_TEMPERATURE = 0.7

# Deepseek - Chinese AI Provider
# Supports: Chat completion
# DEEPSEEK_API_KEY = "sk-your-deepseek-api-key-here"
# DEEPSEEK_MODEL = "deepseek-chat"  # or deepseek-coder
# DEEPSEEK_MAX_TOKENS = 2048
# DEEPSEEK_TEMPERATURE = 0.7

# Kimi (Moonshot AI) - Chinese Conversational AI
# Supports: Chat completion, embeddings
# KIMI_API_KEY = "sk-your-kimi-api-key-here"
# KIMI_MODEL = "moonshot-v1-8k"  # or moonshot-v1-32k, moonshot-v1-128k
# KIMI_MAX_TOKENS = 2048
# KIMI_TEMPERATURE = 0.7

# Qwen (Alibaba) - Alibaba's AI Models
# Supports: Chat completion, embeddings
# QWEN_API_KEY = "sk-your-qwen-api-key-here"
# QWEN_MODEL = "qwen-turbo"  # or qwen-plus, qwen-max
# QWEN_MAX_TOKENS = 2048
# QWEN_TEMPERATURE = 0.7

# ===== SPEECH PROCESSING =====

# Local Speech Processing (Offline - No API Key Required)
# Uses OpenAI Whisper for speech-to-text and pyttsx3/gTTS for text-to-speech
# WHISPER_MODEL_SIZE = "base"  # tiny, base, small, medium, large, large-v1, large-v2, large-v3
# TTS_VOICE = ""  # System-specific voice name (optional)
# TTS_LANGUAGE = "en"  # Language code for TTS

# HuggingFace Transformers Speech Processing
# Uses HuggingFace models for advanced speech processing
# HF_SPEECH_MODEL = "openai/whisper-base"  # or openai/whisper-large-v3
# HF_TOKEN = "hf_your-huggingface-token"  # Optional for public models
# TTS_LANGUAGE = "en"

# ===== EXAMPLE CONFIGURATIONS =====

# Example 1: OpenAI + Local Speech (Recommended for getting started)
# OPENAI_API_KEY = "sk-your-openai-key"
# OPENAI_MODEL = "gpt-4"
# WHISPER_MODEL_SIZE = "base"  # For offline speech processing

# Example 2: Multi-provider setup (Cloud + Local)
# OPENAI_API_KEY = "sk-your-openai-key"        # Primary for chat
# ANTHROPIC_API_KEY = "sk-ant-your-claude-key" # Alternative for chat
# OLLAMA_HOST = "http://localhost:11434"       # Local models
# OLLAMA_MODEL = "llama2"
# WHISPER_MODEL_SIZE = "base"                  # Local speech processing

# Example 3: International providers
# DEEPSEEK_API_KEY = "sk-your-deepseek-key"
# KIMI_API_KEY = "sk-your-kimi-key"
# QWEN_API_KEY = "sk-your-qwen-key"

# Example 4: Speed-optimized setup
# GROQ_API_KEY = "gsk-your-groq-key"    # Fast inference
# GROQ_MODEL = "mixtral-8x7b-32768"
# OLLAMA_HOST = "http://localhost:11434"  # Local backup

# ===== CONFIGURATION NOTES =====
# 1. Environment variables take precedence over config.py settings
# 2. You can enable multiple providers - the system will auto-detect available ones
# 3. For production, use environment variables instead of hardcoding keys
# 4. Local speech processing requires: pip install openai-whisper pyttsx3
# 5. HuggingFace speech requires: pip install transformers torch librosa soundfile
# 6. Each provider has different capabilities - check documentation
# 7. API keys should have sufficient permissions for the features you want to use

# Security Recommendation: Use environment variables in production
# Example .env file:
# OPENAI_API_KEY=sk-your-actual-key
# ANTHROPIC_API_KEY=sk-ant-your-actual-key
# OLLAMA_HOST=http://localhost:11434
