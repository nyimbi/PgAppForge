"""
PgAppForge Configuration for Getting Started Tutorial

This configuration demonstrates best practices for a production-ready
PgAppForge application with AI and collaborative features.
"""

import os
from pgappforge.security.manager import AUTH_DB

# =============================================================================
# Flask Core Configuration
# =============================================================================

# SECURITY WARNING: Generate a strong secret key for production!
# python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# Database Configuration
SQLALCHEMY_DATABASE_URI = os.environ.get(
    'DATABASE_URL', 
    'sqlite:///tutorial_app.db'
)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# =============================================================================
# PgAppForge Configuration
# =============================================================================

# Authentication Configuration
AUTH_TYPE = AUTH_DB
AUTH_ROLE_ADMIN = 'Admin'
AUTH_ROLE_PUBLIC = 'Public'

# Application Branding
APP_NAME = "Task Manager Tutorial"
APP_THEME = "bootstrap-theme.css"
APP_ICON = "static/img/logo.jpg"

# Security Configuration
WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = None

# =============================================================================
# AI Configuration
# =============================================================================

# Enable AI Features
ENABLE_AI_FEATURES = True

# Default AI Provider
AI_DEFAULT_PROVIDER = os.environ.get('AI_DEFAULT_PROVIDER', 'openai')

# AI Provider Fallback Chain
AI_FALLBACK_PROVIDERS = ['anthropic', 'groq', 'ollama']

# OpenAI Configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4')
OPENAI_MAX_TOKENS = int(os.environ.get('OPENAI_MAX_TOKENS', '2000'))
OPENAI_TEMPERATURE = float(os.environ.get('OPENAI_TEMPERATURE', '0.7'))

# Anthropic Configuration
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
ANTHROPIC_MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-3-sonnet-20240229')
ANTHROPIC_MAX_TOKENS = int(os.environ.get('ANTHROPIC_MAX_TOKENS', '2000'))

# Groq Configuration (Fast Inference)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'mixtral-8x7b-32768')

# Google Gemini Configuration
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')
GOOGLE_MODEL = os.environ.get('GOOGLE_MODEL', 'gemini-pro')

# =============================================================================
# Collaborative Features Configuration
# =============================================================================

# Enable Collaborative Features
ENABLE_COLLABORATIVE_EDITING = True
ENABLE_REAL_TIME_NOTIFICATIONS = True

# Redis Configuration
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# WebSocket Configuration
WEBSOCKET_URL = os.environ.get('WEBSOCKET_URL', 'ws://localhost:8080')
SOCKETIO_ASYNC_MODE = 'threading'
SOCKETIO_LOGGER = False
SOCKETIO_ENGINEIO_LOGGER = False

# Cache Configuration
CACHE_TYPE = 'RedisCache' if os.environ.get('REDIS_URL') else 'SimpleCache'
CACHE_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/1')
CACHE_DEFAULT_TIMEOUT = 300

# =============================================================================
# Performance Configuration
# =============================================================================

# Pagination
PGAF_ADMIN_SWATCH = 'united'
PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# File Upload
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
IMG_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'images')
IMG_SIZE = (150, 150, True)

# =============================================================================
# Security Configuration
# =============================================================================

# Password Policy
AUTH_PASSWORD_COMPLEXITY_ENABLED = True
AUTH_PASSWORD_MIN_LENGTH = 8

# Session Configuration
PERMANENT_SESSION_LIFETIME = 1800  # 30 minutes

# CSRF Protection
WTF_CSRF_ENABLED = True

# =============================================================================
# Email Configuration (Optional)
# =============================================================================

# SMTP Configuration for notifications
MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', '1', 'yes']
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')

# =============================================================================
# Logging Configuration
# =============================================================================

# Application Logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

# =============================================================================
# Feature Validation Functions
# =============================================================================

def validate_ai_configuration():
    """Validate AI provider configuration."""
    providers = {}
    
    if OPENAI_API_KEY:
        providers['openai'] = '✅ Configured'
    else:
        providers['openai'] = '❌ API Key Missing'
    
    if ANTHROPIC_API_KEY:
        providers['anthropic'] = '✅ Configured'
    else:
        providers['anthropic'] = '❌ API Key Missing'
    
    if GROQ_API_KEY:
        providers['groq'] = '✅ Configured'
    else:
        providers['groq'] = '❌ API Key Missing'
        
    return providers

def validate_redis_configuration():
    """Validate Redis connection."""
    try:
        import redis
        r = redis.from_url(REDIS_URL)
        r.ping()
        return '✅ Connected'
    except Exception as e:
        return f'❌ Error: {str(e)}'

def validate_database_configuration():
    """Validate database configuration."""
    try:
        from sqlalchemy import create_engine
        engine = create_engine(SQLALCHEMY_DATABASE_URI)
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        return '✅ Connected'
    except Exception as e:
        return f'❌ Error: {str(e)}'

# =============================================================================
# Development Configuration Overrides
# =============================================================================

if os.environ.get('FLASK_ENV') == 'development':
    # Development-specific settings
    DEBUG = True
    TESTING = False
    
    # Relaxed security for development
    WTF_CSRF_ENABLED = False
    
    # Verbose logging for development
    SQLALCHEMY_ECHO = False
    SOCKETIO_LOGGER = True
    SOCKETIO_ENGINEIO_LOGGER = True

# =============================================================================
# Production Configuration Overrides
# =============================================================================

if os.environ.get('FLASK_ENV') == 'production':
    # Production-specific settings
    DEBUG = False
    TESTING = False
    
    # Enhanced security for production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Strict CSRF protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour
    
    # Performance optimizations
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }