# Development Environment Setup

This guide covers setting up a development environment for PgAppForge applications with all the enhanced features including AI integration, collaborative features, and process workflows.

## Prerequisites

### System Requirements

- Python 3.9+ (3.11 recommended)
- Node.js 16+ (for frontend development)
- Git 2.30+
- Docker and Docker Compose (optional)
- Redis server (for real-time features)

### Python Environment

```bash
# Install Python 3.11 (Ubuntu/Debian)
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.11 python3.11-venv python3.11-dev

# Install Python 3.11 (macOS with Homebrew)
brew install python@3.11

# Install Python 3.11 (Windows)
# Download from python.org or use Windows Store
```

## Project Setup

### Clone and Initialize

```bash
# Clone the repository
git clone https://github.com/dpgaspar/PgAppForge.git
cd PgAppForge

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows

# Upgrade pip and install build tools
pip install --upgrade pip setuptools wheel

# Install development dependencies
pip install -e ".[mfa,export,analytics]"
```

### Development Dependencies

```bash
# Install additional development tools
pip install \
    black \
    flake8 \
    mypy \
    pytest \
    pytest-cov \
    pytest-xdist \
    pre-commit \
    jupyter \
    ipython
```

## Database Setup

### SQLite (Quick Start)

```bash
# Create SQLite database (default for development)
export FLASK_APP=examples/quickhowto/app
flask fab create-db
flask fab create-admin

# Start development server
flask run --debug --port=8080
```

### PostgreSQL (Recommended for Development)

```bash
# Install PostgreSQL (Ubuntu/Debian)
sudo apt install postgresql postgresql-contrib libpq-dev

# Install PostgreSQL (macOS)
brew install postgresql libpq
brew services start postgresql

# Create development database
sudo -u postgres createuser --interactive mydev
sudo -u postgres createdb mydev_db -O mydev

# Set password
sudo -u postgres psql
ALTER USER mydev WITH PASSWORD 'devpassword';
\q
```

```python
# examples/quickhowto/config.py - Development configuration
import os

# Database Configuration
SQLALCHEMY_DATABASE_URI = os.environ.get(
    'DEV_DATABASE_URL',
    'postgresql://mydev:devpassword@localhost/mydev_db'
)

# Development settings
DEBUG = True
SECRET_KEY = 'development-key-not-for-production'
WTF_CSRF_ENABLED = False  # Disable for easier API testing

# Enable detailed error pages
TESTING = True
PRESERVE_CONTEXT_ON_EXCEPTION = False
```

### Redis Setup

```bash
# Install Redis (Ubuntu/Debian)
sudo apt install redis-server

# Install Redis (macOS)
brew install redis
brew services start redis

# Install Redis (Windows)
# Download from https://redis.io/download or use WSL

# Test Redis connection
redis-cli ping
# Should return: PONG
```

## AI Services Configuration

### Development AI Configuration

```python
# examples/quickhowto/config.py - AI development setup
import os

# AI Provider Configuration (Development)
# Use free tier APIs or local models for development

# OpenAI (requires API key)
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = 'gpt-3.5-turbo'  # Cheaper for development
OPENAI_MAX_TOKENS = 1000  # Lower limits for development

# Anthropic (optional for development)
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
ANTHROPIC_MODEL = 'claude-3-haiku-20240307'  # Fastest/cheapest model

# Local models (recommended for development)
OLLAMA_BASE_URL = 'http://localhost:11434'
OLLAMA_MODEL = 'llama2:7b'  # Lightweight model

# Groq (free tier available)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = 'llama2-70b-4096'

# Development-specific AI settings
AI_RATE_LIMIT = 10  # requests per minute
AI_TIMEOUT = 30  # seconds
AI_RETRY_ATTEMPTS = 2
AI_CACHE_TTL = 300  # 5 minutes

# Vector Store Configuration (development)
FAISS_INDEX_PATH = './dev_data/faiss_index'
VECTOR_STORE_DIMENSION = 384  # Smaller dimension for development

# Speech Configuration (development)
SPEECH_MODEL_PATH = './dev_data/models'  # Local model storage
TTS_VOICE = 'en'
STT_LANGUAGE = 'en-US'
```

### Local AI Models Setup

```bash
# Install Ollama (for local LLM)
curl -fsSL https://ollama.ai/install.sh | sh

# Download development model
ollama pull llama2:7b

# Start Ollama service
ollama serve

# Test local model
curl http://localhost:11434/api/generate -d '{
  "model": "llama2:7b",
  "prompt": "Hello, world!"
}'
```

## Frontend Development

### Node.js Setup

```bash
# Install Node.js dependencies (if extending frontend)
npm install -g yarn

# Install frontend build tools
npm install -g webpack webpack-cli
npm install -g @babel/core @babel/cli
```

### Static Assets Development

```bash
# Watch and compile static assets during development
cd pgappforge/static/appbuilder

# Install dependencies
npm install

# Start development watcher
npm run dev

# Build for production
npm run build
```

## Development Tools

### Pre-commit Hooks

```bash
# Install pre-commit hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        args: [--config=setup.cfg]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.3.0
    hooks:
      - id: mypy
        additional_dependencies: [types-requests, types-redis]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
```

### IDE Configuration

#### VS Code Setup

```json
// .vscode/settings.json
{
    "python.defaultInterpreterPath": "./venv/bin/python",
    "python.formatting.provider": "black",
    "python.linting.flake8Enabled": true,
    "python.linting.mypyEnabled": true,
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": [
        "tests"
    ],
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true,
        ".pytest_cache": true,
        ".mypy_cache": true
    },
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
        "source.organizeImports": true
    }
}
```

```json
// .vscode/launch.json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Flask Debug",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/venv/bin/flask",
            "args": ["run", "--debug", "--port=8080"],
            "env": {
                "FLASK_APP": "examples/quickhowto/app",
                "FLASK_ENV": "development"
            },
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}"
        },
        {
            "name": "Pytest",
            "type": "python",
            "request": "launch",
            "module": "pytest",
            "args": ["tests/", "-v"],
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}"
        }
    ]
}
```

#### PyCharm Setup

```python
# PyCharm run configuration
# Name: Flask Development Server
# Script path: [venv]/bin/flask
# Parameters: run --debug --port=8080
# Environment variables: FLASK_APP=examples/quickhowto/app
# Working directory: [project root]
```

## Testing Setup

### Test Database

```python
# tests/conftest.py
import pytest
import tempfile
import os
from flask import Flask
from pgappforge import AppBuilder, SQLA

@pytest.fixture
def app():
    """Create test application."""
    # Create temporary database
    db_fd, db_path = tempfile.mkstemp()

    app = Flask(__name__)
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret-key',
        'CACHE_TYPE': 'SimpleCache',
    })

    # Initialize extensions
    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)

    with app.app_context():
        db.create_all()

    yield app

    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)

@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """Create test runner."""
    return app.test_cli_runner()
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=pgappforge

# Run specific test file
pytest tests/test_security.py

# Run with verbose output
pytest -v

# Run tests in parallel
pytest -n auto

# Run only AI-related tests
pytest -k "ai or collaborative" -v

# Run only fast tests (skip slow integration tests)
pytest -m "not slow"
```

## Development Workflow

### Daily Development

```bash
# Morning setup
source venv/bin/activate
git pull origin main
pip install -e ".[mfa,export,analytics]"  # Update dependencies if needed

# Start services
redis-server &  # If not running as service
ollama serve &  # If using local AI models

# Start development server
export FLASK_APP=examples/quickhowto/app
flask run --debug --port=8080

# In another terminal - run tests continuously
pytest-watch
```

### Code Quality Checks

```bash
# Format code
black pgappforge tests examples

# Check style
flake8 pgappforge tests examples

# Type checking
mypy pgappforge

# Security checks
bandit -r pgappforge

# Check dependencies
safety check

# All quality checks
make quality  # If Makefile exists
```

### Docker Development

```yaml
# docker-compose.dev.yml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile.dev
    volumes:
      - .:/app
      - /app/venv  # Anonymous volume for venv
    ports:
      - "8080:8080"
    environment:
      - FLASK_ENV=development
      - DATABASE_URL=postgresql://postgres:password@db:5432/fab_dev
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=fab_dev
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
    ports:
      - "5432:5432"
    volumes:
      - postgres_dev_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama

volumes:
  postgres_dev_data:
  ollama_data:
```

```dockerfile
# Dockerfile.dev
FROM python:3.11

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements/ requirements/
RUN pip install -r requirements/dev.txt

# Copy source code
COPY . .

# Install in development mode
RUN pip install -e ".[mfa,export,analytics]"

# Create development user
RUN useradd --create-home --shell /bin/bash dev && \
    chown -R dev:dev /app
USER dev

# Start command
CMD ["flask", "run", "--debug", "--host=0.0.0.0", "--port=8080"]
```

## Environment Variables

### Development .env File

```bash
# .env.development (never commit to git)
# Copy to .env and modify as needed

# Flask Configuration
FLASK_APP=examples/quickhowto/app
FLASK_ENV=development
SECRET_KEY=development-secret-key-not-for-production

# Database
DATABASE_URL=postgresql://mydev:devpassword@localhost/mydev_db
# DATABASE_URL=sqlite:///dev.db  # Alternative for quick setup

# Cache
REDIS_URL=redis://localhost:6379/0

# AI Services (development)
OPENAI_API_KEY=sk-your-development-key-here
ANTHROPIC_API_KEY=sk-ant-your-development-key-here
GROQ_API_KEY=your-groq-development-key-here

# Local AI
OLLAMA_BASE_URL=http://localhost:11434

# Development Features
DEBUG=True
TESTING=False
WTF_CSRF_ENABLED=False

# Logging
LOG_LEVEL=DEBUG
LOG_TO_STDOUT=True

# Email (development - use MailHog or similar)
MAIL_SERVER=localhost
MAIL_PORT=1025
MAIL_USE_TLS=False
MAIL_USE_SSL=False
```

### Loading Environment Variables

```python
# config_dev.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv('.env.development')

class DevelopmentConfig:
    """Development configuration."""

    # Flask
    DEBUG = True
    TESTING = False
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///dev.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = True  # Log SQL queries

    # Cache
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    CACHE_DEFAULT_TIMEOUT = 60  # Short timeout for development

    # Security (relaxed for development)
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False

    # AI Configuration
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')

    # Development-specific settings
    PRESERVE_CONTEXT_ON_EXCEPTION = False
    EXPLAIN_TEMPLATE_LOADING = True
```

## Debugging

### Application Debugging

```python
# Debug configuration in app.py
import logging
from flask import Flask
from pgappforge import AppBuilder

# Configure logging for development
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
logging.getLogger('pgappforge').setLevel(logging.DEBUG)

app = Flask(__name__)
app.config.from_object('config_dev.DevelopmentConfig')

# Enable detailed error pages
if app.debug:
    from werkzeug.debug import DebuggedApplication
    app.wsgi_app = DebuggedApplication(app.wsgi_app, evalex=True)

# Initialize PgAppForge
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

if __name__ == '__main__':
    app.run(debug=True, port=8080, host='0.0.0.0')
```

### Database Debugging

```python
# Enable SQL query logging
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

# Add query debugging to models
from sqlalchemy import event
from sqlalchemy.engine import Engine
import time

@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.time()

@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total = time.time() - context._query_start_time
    if total > 0.1:  # Log queries taking >100ms
        print(f"Slow Query ({total:.2f}s): {statement[:100]}...")
```

### AI Service Debugging

```python
# AI debugging utilities
import logging
from pgappforge.collaborative.ai.ai_models import AIModelManager

# Enable detailed AI logging
logging.getLogger('pgappforge.collaborative.ai').setLevel(logging.DEBUG)

# Debug AI responses
def debug_ai_call(prompt, model_provider=None):
    """Debug AI calls with detailed logging."""
    manager = AIModelManager()

    try:
        response = manager.generate_text(
            prompt=prompt,
            model_provider=model_provider,
            max_tokens=100,
            temperature=0.1
        )
        print(f"AI Response: {response}")
        return response
    except Exception as e:
        print(f"AI Error: {e}")
        import traceback
        traceback.print_exc()

# Test AI connectivity
def test_ai_providers():
    """Test all configured AI providers."""
    from pgappforge.collaborative.ai.ai_models import ModelProvider

    manager = AIModelManager()
    test_prompt = "Hello, world!"

    for provider in ModelProvider:
        try:
            response = manager.generate_text(
                prompt=test_prompt,
                model_provider=provider,
                max_tokens=20
            )
            print(f"{provider.value}: ✓ {response[:50]}...")
        except Exception as e:
            print(f"{provider.value}: ✗ {e}")
```

## Performance Profiling

### Application Profiling

```python
# profiling.py
from werkzeug.middleware.profiler import ProfilerMiddleware
from flask import Flask

def enable_profiling(app: Flask):
    """Enable request profiling for development."""
    if app.debug:
        app.wsgi_app = ProfilerMiddleware(
            app.wsgi_app,
            stream=open('profile_output.txt', 'w'),
            restrictions=[30]  # Show top 30 functions
        )

# Memory profiling
from memory_profiler import profile

@profile
def memory_intensive_function():
    """Profile memory usage of function."""
    pass

# Line profiling
from line_profiler import LineProfiler

def profile_lines():
    """Profile line-by-line execution."""
    profiler = LineProfiler()
    profiler.add_function(your_function)
    profiler.enable_by_count()
    # Your code here
    profiler.print_stats()
```

### Database Performance

```bash
# PostgreSQL query analysis
export PGPASSWORD=devpassword
psql -h localhost -U mydev -d mydev_db

-- Enable query timing
\timing on

-- Analyze slow queries
SELECT query, mean_time, calls
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;

-- Check index usage
SELECT schemaname, tablename, attname, n_distinct, correlation
FROM pg_stats
WHERE tablename = 'your_table';
```

## Troubleshooting Common Issues

### Import Errors

```bash
# Reinstall in development mode
pip uninstall flask-appbuilder
pip install -e ".[mfa,export,analytics]"

# Check Python path
python -c "import sys; print('\n'.join(sys.path))"

# Verify installation
python -c "import pgappforge; print(pgappforge.__version__)"
```

### Database Issues

```bash
# Reset development database
flask fab reset-db
flask fab create-admin

# Check database connection
python -c "
from sqlalchemy import create_engine
engine = create_engine('your-database-url')
print(engine.execute('SELECT 1').scalar())
"
```

### Redis Connection Issues

```bash
# Test Redis connection
redis-cli ping

# Check Redis configuration
redis-cli CONFIG GET "*"

# Monitor Redis operations
redis-cli MONITOR
```

### AI Service Issues

```python
# Test AI service connectivity
import requests

# Test OpenAI
headers = {'Authorization': 'Bearer your-api-key'}
response = requests.get('https://api.openai.com/v1/models', headers=headers)
print(response.status_code, response.json())

# Test Ollama
response = requests.get('http://localhost:11434/api/tags')
print(response.status_code, response.json())
```

This development setup guide provides comprehensive instructions for setting up a productive development environment for PgAppForge with all enhanced features.