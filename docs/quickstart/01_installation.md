# Installation Guide

Complete installation guide for PgAppForge v4.8.0-enhanced with all advanced features including AI integration, collaborative tools, and process automation.

## 🎯 Quick Start

Get up and running in 5 minutes with the basic installation:

```bash
# Create virtual environment
python -m venv fab-env
source fab-env/bin/activate  # On Windows: fab-env\Scripts\activate

# Install PgAppForge Enhanced
pip install flask-appbuilder[mfa,export,analytics]

# Create your first app
fab create-app MyApp
cd MyApp

# Initialize database and run
export FLASK_APP=app.py
flask fab create-admin
flask run
```

Visit `http://localhost:5000` to see your application!

## 📋 System Requirements

### Minimum Requirements

- **Python**: 3.8+
- **Operating System**: Linux, macOS, Windows
- **Memory**: 2GB RAM minimum, 4GB recommended
- **Storage**: 1GB free space

### Recommended for Production

- **Python**: 3.11+
- **Memory**: 8GB+ RAM
- **CPU**: 4+ cores
- **Storage**: SSD with 10GB+ free space
- **Database**: PostgreSQL 13+ or MySQL 8+

## 🚀 Installation Options

### Option 1: Basic Installation

For simple applications without advanced features:

```bash
pip install flask-appbuilder
```

### Option 2: Enhanced Installation (Recommended)

Includes all advanced features:

```bash
pip install flask-appbuilder[mfa,export,analytics]
```

### Option 3: Feature-Specific Installation

Install only specific feature sets:

```bash
# Multi-factor authentication features
pip install flask-appbuilder[mfa]

# Export features (Excel, PDF)
pip install flask-appbuilder[export]

# Analytics and dashboard features
pip install flask-appbuilder[analytics]

# Security and authentication features
pip install flask-appbuilder[mfa,oauth,openid,talisman]

# Everything
pip install flask-appbuilder[all]
```

### Option 4: Development Installation

For contributors and advanced developers:

```bash
# Clone repository
git clone https://github.com/dpgaspar/PgAppForge.git
cd PgAppForge

# Create development environment
python -m venv venv
source venv/bin/activate

# Install in development mode
pip install -e .[mfa,export,analytics]
```

## 🔧 Feature Dependencies

### AI Features

```bash
# For AI model integration
pip install openai anthropic google-generativeai

# For local AI models
pip install ollama-python transformers torch

# For speech processing
pip install openai-whisper pyttsx3 gTTS librosa soundfile

# For vector search (optional but recommended)
pip install faiss-cpu  # or faiss-gpu for GPU acceleration
```

### Collaboration Features

```bash
# For real-time collaboration
pip install socketio redis celery

# For file processing
pip install pillow python-magic

# For document processing
pip install python-docx PyPDF2 markdown
```

### Process Automation

```bash
# For workflow engine
pip install celery redis

# For rule engine
pip install jsonpath-ng jinja2

# For notifications
pip install sendgrid twilio slack-sdk
```

### Security Features

```bash
# For advanced authentication
pip install flask-oauthlib authlib

# For MFA support
pip install pyotp qrcode cryptography

# For WebAuthn/Passkeys
pip install webauthn
```

### Database Support

```bash
# PostgreSQL (recommended)
pip install psycopg2-binary

# MySQL
pip install mysqlclient

# SQLite (included with Python)
# No additional dependencies needed

# MongoDB (optional)
pip install mongoengine
```

## 🔨 Development Tools

### Optional Development Dependencies

```bash
# Code formatting and linting
pip install black flake8 isort mypy

# Testing tools
pip install pytest pytest-cov pytest-mock

# Documentation tools
pip install sphinx sphinx-rtd-theme

# Performance monitoring
pip install py-spy memory-profiler
```

## 🐳 Docker Installation

### Quick Docker Setup

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install PgAppForge Enhanced
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "5000:5000"
    environment:
      - FLASK_ENV=production
      - DATABASE_URL=postgresql://user:password@db:5432/myapp
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis

  db:
    image: postgres:13
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

### Docker Commands

```bash
# Build and run with Docker Compose
docker-compose up -d

# Run database migrations
docker-compose exec web flask db upgrade

# Create admin user
docker-compose exec web flask fab create-admin

# View logs
docker-compose logs -f web
```

## 🌟 Feature Verification

### Verify Basic Installation

```python
# test_installation.py
import pgappforge

print(f"PgAppForge version: {pgappforge.__version__}")

# Test basic imports
from pgappforge import AppBuilder, ModelView
from pgappforge.models.sqla import Model

print("✅ Basic installation verified")
```

### Verify AI Features

```python
# test_ai_features.py
try:
    from pgappforge.collaborative.ai.ai_models import ModelManager
    from pgappforge.collaborative.ai.chatbot_service import ChatbotService
    print("✅ AI features available")
except ImportError as e:
    print(f"❌ AI features not available: {e}")
    print("Install with: pip install flask-appbuilder[mfa]")
```

### Verify Collaboration Features

```python
# test_collaboration.py
try:
    from pgappforge.collaborative.realtime.websocket_manager import WebSocketManager
    from pgappforge.collaborative.core.team_manager import TeamManager
    print("✅ Collaboration features available")
except ImportError as e:
    print(f"❌ Collaboration features not available: {e}")
    print("Install with: pip install flask-appbuilder[collaboration]")
```

### Verify Process Features

```python
# test_process_features.py
try:
    from pgappforge.process.engine import ProcessEngine
    from pgappforge.process.workflow import WorkflowBuilder
    print("✅ Process automation features available")
except ImportError as e:
    print(f"❌ Process features not available: {e}")
    print("Install with: pip install flask-appbuilder[analytics]")
```

## 🔧 Configuration

### Basic Configuration

Create `config.py`:

```python
import os
from pgappforge.security.manager import AUTH_DB

basedir = os.path.abspath(os.path.dirname(__file__))

# Basic Flask Configuration
SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
    f'sqlite:///{os.path.join(basedir, "app.db")}'

# PgAppForge Configuration
AUTH_TYPE = AUTH_DB
AUTH_ROLE_ADMIN = 'Admin'
AUTH_ROLE_PUBLIC = 'Public'
APP_NAME = "My PgAppForge App"
APP_THEME = ""  # Default Bootstrap theme

# Upload Configuration
UPLOAD_FOLDER = os.path.join(basedir, "app/static/uploads/")
IMG_UPLOAD_FOLDER = os.path.join(basedir, "app/static/uploads/")
IMG_UPLOAD_URL = "/static/uploads/"

# Security
CSRF_ENABLED = True
```

### Enhanced Features Configuration

```python
# AI Configuration (optional)
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

# Collaboration Configuration (optional)
REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
WEBSOCKET_ENABLED = True

# Process Engine Configuration (optional)
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or 'redis://localhost:6379/1'
PROCESS_ENGINE_ENABLED = True

# Security Features (optional)
MFA_ENABLED = False
WEBAUTHN_ENABLED = False
```

## 🚀 Quick Application Setup

### Create Basic App

```python
# app.py
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.models.sqla import Model
from sqlalchemy import Column, Integer, String

# Create Flask app
app = Flask(__name__)
app.config.from_object('config')

# Initialize database
db = SQLA(app)

# Create a simple model
class Contact(Model):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    email = Column(String(120), nullable=False)

    def __repr__(self):
        return self.name

# Initialize AppBuilder
appbuilder = AppBuilder(app, db.session)

# Import views after AppBuilder initialization
from app import views
```

### Create Views

```python
# views.py
from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface
from app import appbuilder, db
from .models import Contact

class ContactModelView(ModelView):
    datamodel = SQLAInterface(Contact)
    list_columns = ['name', 'email']

# Register view
appbuilder.add_view(
    ContactModelView,
    "List Contacts",
    icon="fa-envelope-o",
    category="Contacts"
)
```

### Initialize Database

```bash
# Initialize database
flask db init
flask db migrate -m "Initial migration"
flask db upgrade

# Create admin user
flask fab create-admin
# Username: admin
# Email: admin@admin.com
# Password: admin
```

## 🔍 Troubleshooting

### Common Installation Issues

#### 1. Permission Errors

```bash
# On macOS/Linux, use --user flag
pip install --user flask-appbuilder[mfa,export,analytics]

# Or fix permissions
sudo chown -R $(whoami) /usr/local/lib/python*/site-packages
```

#### 2. Compilation Errors

```bash
# Install build tools on Ubuntu/Debian
sudo apt-get install build-essential python3-dev libffi-dev

# On CentOS/RHEL
sudo yum install gcc python3-devel libffi-devel

# On macOS, install Xcode command line tools
xcode-select --install
```

#### 3. Database Connection Issues

```python
# Test database connection
from sqlalchemy import create_engine
engine = create_engine('your-database-url')
connection = engine.connect()
print("✅ Database connection successful")
connection.close()
```

#### 4. Redis Connection Issues

```python
# Test Redis connection
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
r.ping()
print("✅ Redis connection successful")
```

#### 5. Import Errors

```bash
# Clear Python cache
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} +

# Reinstall clean
pip uninstall flask-appbuilder
pip install flask-appbuilder[mfa,export,analytics]
```

### Environment-Specific Issues

#### Windows

```bash
# Install Microsoft C++ Build Tools
# Download from: https://visualstudio.microsoft.com/visual-cpp-build-tools/

# Alternative: Use conda
conda install flask-appbuilder
```

#### macOS with Apple Silicon

```bash
# For native Apple Silicon performance
pip install --upgrade pip
pip install flask-appbuilder[mfa,export,analytics]

# If you encounter issues with some dependencies
arch -arm64 pip install flask-appbuilder[mfa,export,analytics]
```

#### Linux (Ubuntu/Debian)

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    redis-server \
    postgresql

# Install PgAppForge
pip install flask-appbuilder[mfa,export,analytics]
```

## 📊 Performance Optimization

### Production Optimizations

```python
# config_production.py
import os

# Use environment variables
SECRET_KEY = os.environ['SECRET_KEY']
SQLALCHEMY_DATABASE_URI = os.environ['DATABASE_URL']

# Performance settings
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_size': 20,
    'max_overflow': 30
}

# Caching (if using Redis)
CACHE_TYPE = 'RedisCache'
CACHE_REDIS_URL = os.environ.get('REDIS_URL')

# Security settings
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# AI Features optimization
AI_MODEL_CACHE_SIZE = 100
AI_REQUEST_TIMEOUT = 30

# Collaboration optimization
WEBSOCKET_MAX_CONNECTIONS = 1000
PRESENCE_UPDATE_INTERVAL = 30
```

### WSGI Server Setup

```bash
# Install production WSGI server
pip install gunicorn

# Run with Gunicorn
gunicorn --bind 0.0.0.0:8000 --workers 4 --worker-class gevent app:app

# Or with uWSGI
pip install uwsgi
uwsgi --http :8000 --wsgi-file app.py --callable app --processes 4
```

## 🔐 Security Considerations

### Environment Variables

```bash
# .env file (never commit to version control)
SECRET_KEY=your-super-secret-key-here
DATABASE_URL=postgresql://user:password@localhost/myapp
REDIS_URL=redis://localhost:6379/0

# AI API Keys
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key

# External Service Keys
SENDGRID_API_KEY=your-sendgrid-key
SLACK_API_TOKEN=your-slack-token
```

### Security Checklist

- [ ] Change default SECRET_KEY
- [ ] Use environment variables for sensitive data
- [ ] Enable HTTPS in production
- [ ] Configure secure session cookies
- [ ] Set up proper database permissions
- [ ] Enable audit logging
- [ ] Configure rate limiting
- [ ] Set up monitoring and alerting

## 🚀 Next Steps

1. **Complete Basic Setup** - Finish the [First App Tutorial](02_first_app.md)
2. **Configure Authentication** - Set up [Authentication Guide](03_authentication.md)
3. **Build CRUD Views** - Create [CRUD Interfaces](04_crud_views.md)
4. **Add AI Features** - Integrate [AI Capabilities](../tutorials/ai_chatbot.md)
5. **Enable Collaboration** - Set up [Real-time Features](../tutorials/realtime_dashboard.md)

### Useful Resources

- [Official Documentation](https://flask-appbuilder.readthedocs.io/)
- [GitHub Repository](https://github.com/dpgaspar/PgAppForge)
- [Community Examples](../examples/)
- [API Reference](../api/)

## 💡 Tips and Best Practices

1. **Start Simple** - Begin with basic features and add advanced ones as needed
2. **Use Virtual Environments** - Always isolate your dependencies
3. **Version Control** - Use Git from the beginning
4. **Environment Configuration** - Separate development and production configs
5. **Database Backups** - Set up regular backups early
6. **Monitoring** - Add logging and monitoring from day one
7. **Documentation** - Document your customizations and configurations

---

**Next:** [Creating Your First Application](02_first_app.md)