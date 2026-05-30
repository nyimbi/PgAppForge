# Production Deployment Guide

This guide covers deploying PgAppForge applications to production environments with proper security, scalability, and monitoring.

## Overview

PgAppForge applications require careful consideration of security, database configuration, caching, and monitoring when deployed to production. This guide provides best practices and configuration examples.

## Environment Configuration

### Production Settings

```python
# config.py - Production Configuration
import os
from datetime import timedelta

# Basic Flask Configuration
SECRET_KEY = os.environ.get('SECRET_KEY')  # Must be set in environment
WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = None

# Database Configuration
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'max_overflow': 20,
    'pool_size': 10,
    'echo': False
}

# Security Configuration
PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# Cache Configuration (Redis recommended)
CACHE_TYPE = 'RedisCache'
CACHE_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CACHE_DEFAULT_TIMEOUT = 300

# Logging Configuration
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        }
    },
    'handlers': {
        'wsgi': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://flask.logging.wsgi_errors_stream',
            'formatter': 'default'
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/app/app.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'formatter': 'default'
        }
    },
    'root': {
        'level': 'INFO',
        'handlers': ['wsgi', 'file']
    }
}

# AI Configuration for Production
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

# File Upload Configuration
UPLOAD_FOLDER = '/var/uploads'
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

# Performance Configuration
SQLALCHEMY_TRACK_MODIFICATIONS = False
SEND_FILE_MAX_AGE_DEFAULT = timedelta(days=365)
```

### Environment Variables

Create a `.env` file for production (never commit to version control):

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost/dbname

# Security
SECRET_KEY=your-very-long-random-secret-key-minimum-32-characters

# Cache
REDIS_URL=redis://localhost:6379/0

# AI Services
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
GOOGLE_API_KEY=your-google-api-key

# External Services
SMTP_SERVER=smtp.yourdomain.com
SMTP_USER=noreply@yourdomain.com
SMTP_PASSWORD=your-smtp-password

# Monitoring
SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
```

## Database Setup

### PostgreSQL (Recommended)

```bash
# Install PostgreSQL
sudo apt-get install postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql
CREATE DATABASE myapp;
CREATE USER myappuser WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE myapp TO myappuser;
\q

# Initialize database
export DATABASE_URL=postgresql://myappuser:secure_password@localhost/myapp
flask fab create-db
flask fab create-admin
```

### Database Migration

```python
# app.py - Database initialization
from flask import Flask
from pgappforge import AppBuilder, SQLA
from flask_migrate import Migrate

app = Flask(__name__)
app.config.from_object('config')

db = SQLA(app)
migrate = Migrate(app, db.session)
appbuilder = AppBuilder(app, db.session)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
```

```bash
# Database migration commands
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
```

## Web Server Configuration

### Nginx Configuration

```nginx
# /etc/nginx/sites-available/myapp
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /path/to/ssl/cert.pem;
    ssl_certificate_key /path/to/ssl/private.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;

    client_max_body_size 20M;
    keepalive_timeout 65;

    # Static files
    location /static {
        alias /path/to/your/app/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # WebSocket support for collaborative features
    location /ws {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }

    # Application
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
}
```

### Gunicorn Configuration

```python
# gunicorn.conf.py
import multiprocessing

# Server socket
bind = "127.0.0.1:8080"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "gevent"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Timeout
timeout = 120
keepalive = 2

# Logging
accesslog = "/var/log/app/gunicorn_access.log"
errorlog = "/var/log/app/gunicorn_error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "myapp"

# Server mechanics
daemon = False
pidfile = "/var/run/gunicorn/myapp.pid"
user = "www-data"
group = "www-data"
preload_app = True

# SSL (if terminating SSL at application level)
# keyfile = "/path/to/ssl/private.key"
# certfile = "/path/to/ssl/cert.pem"
```

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

# Create application directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Create directories for logs and uploads
RUN mkdir -p /app/logs /app/uploads

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Start command
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/myapp
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=${SECRET_KEY}
    volumes:
      - ./uploads:/app/uploads
      - ./logs:/app/logs
    depends_on:
      - db
      - redis
    networks:
      - app-network

  db:
    image: postgres:15
    restart: unless-stopped
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - app-network

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data
    networks:
      - app-network

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - ./ssl:/etc/ssl/certs
    depends_on:
      - app
    networks:
      - app-network

volumes:
  postgres_data:
  redis_data:

networks:
  app-network:
    driver: bridge
```

## Kubernetes Deployment

### Namespace and ConfigMap

```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: flask-appbuilder

---
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: flask-appbuilder
data:
  FLASK_ENV: "production"
  DATABASE_URL: "postgresql://postgres:password@postgres:5432/myapp"
  REDIS_URL: "redis://redis:6379/0"
```

### Secrets

```yaml
# k8s/secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secrets
  namespace: flask-appbuilder
type: Opaque
data:
  SECRET_KEY: <base64-encoded-secret-key>
  OPENAI_API_KEY: <base64-encoded-openai-key>
  ANTHROPIC_API_KEY: <base64-encoded-anthropic-key>
```

### Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flask-appbuilder
  namespace: flask-appbuilder
spec:
  replicas: 3
  selector:
    matchLabels:
      app: flask-appbuilder
  template:
    metadata:
      labels:
        app: flask-appbuilder
    spec:
      containers:
      - name: app
        image: myregistry/flask-appbuilder:latest
        ports:
        - containerPort: 8080
        env:
        - name: DATABASE_URL
          valueFrom:
            configMapKeyRef:
              name: app-config
              key: DATABASE_URL
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: app-config
              key: REDIS_URL
        - name: SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: SECRET_KEY
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5

---
# k8s/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: flask-appbuilder-service
  namespace: flask-appbuilder
spec:
  selector:
    app: flask-appbuilder
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8080
  type: LoadBalancer
```

## Monitoring and Logging

### Application Monitoring

```python
# monitoring.py
from flask import Blueprint, jsonify, current_app
from datetime import datetime
import psutil
import os

monitoring_bp = Blueprint('monitoring', __name__)

@monitoring_bp.route('/health')
def health_check():
    """Basic health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': current_app.config.get('VERSION', '1.0.0')
    })

@monitoring_bp.route('/metrics')
def metrics():
    """Application metrics endpoint."""
    try:
        # System metrics
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # Application metrics
        from pgappforge import appbuilder
        user_count = appbuilder.sm.get_user_model().query.count()

        return jsonify({
            'system': {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_used_mb': memory.used // (1024 * 1024),
                'disk_percent': (disk.used / disk.total) * 100,
                'disk_free_gb': disk.free // (1024 * 1024 * 1024)
            },
            'application': {
                'user_count': user_count,
                'uptime_seconds': (datetime.now() - start_time).total_seconds()
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add to your app
start_time = datetime.now()
```

### Structured Logging

```python
# logging_config.py
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        if hasattr(record, 'user_id'):
            log_data['user_id'] = record.user_id

        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id

        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data)

# Usage in config.py
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'logging_config.JSONFormatter'
        }
    },
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/app/app.json',
            'maxBytes': 10485760,
            'backupCount': 5,
            'formatter': 'json'
        }
    },
    'loggers': {
        'pgappforge': {
            'level': 'INFO',
            'handlers': ['file'],
            'propagate': False
        }
    }
}
```

## Performance Optimization

### Caching Strategy

```python
# caching.py
from flask_caching import Cache
from functools import wraps
import hashlib

cache = Cache()

def cache_key_generator(*args, **kwargs):
    """Generate cache key from function arguments."""
    key_parts = [str(arg) for arg in args]
    key_parts.extend([f"{k}:{v}" for k, v in sorted(kwargs.items())])
    key_string = "|".join(key_parts)
    return hashlib.md5(key_string.encode()).hexdigest()

def cached_view(timeout=300):
    """Decorator for caching view results."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            cache_key = f"view:{f.__name__}:{cache_key_generator(*args, **kwargs)}"
            result = cache.get(cache_key)
            if result is None:
                result = f(*args, **kwargs)
                cache.set(cache_key, result, timeout=timeout)
            return result
        return decorated_function
    return decorator

# Usage in views
class MyModelView(ModelView):
    @cached_view(timeout=600)
    def list(self):
        return super().list()
```

### Database Optimization

```python
# database_optimization.py
from sqlalchemy import event
from sqlalchemy.engine import Engine
import time
import logging

# Query performance monitoring
logger = logging.getLogger('sqlalchemy.engine')

@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.time()

@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total = time.time() - context._query_start_time
    if total > 0.1:  # Log slow queries (>100ms)
        logger.warning(f"Slow query: {total:.2f}s - {statement[:100]}...")

# Connection pooling configuration
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 20,
    'max_overflow': 30,
    'pool_pre_ping': True,
    'pool_recycle': 3600,
    'echo': False,
    'echo_pool': False
}
```

## Security Hardening

### Security Headers

```python
# security.py
from flask import Flask
from flask_talisman import Talisman

def configure_security(app: Flask):
    """Configure security headers and policies."""

    # Content Security Policy
    csp = {
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
        'style-src': "'self' 'unsafe-inline' https://fonts.googleapis.com",
        'font-src': "'self' https://fonts.gstatic.com",
        'img-src': "'self' data: https:",
        'connect-src': "'self' wss: ws:",
    }

    Talisman(app,
             force_https=True,
             strict_transport_security=True,
             content_security_policy=csp,
             feature_policy={
                 'camera': "'none'",
                 'microphone': "'none'",
                 'geolocation': "'none'"
             })

# Rate limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["1000 per hour", "100 per minute"]
)

# Apply to login endpoints
@limiter.limit("5 per minute")
def login():
    pass
```

### Environment Security

```bash
#!/bin/bash
# security_setup.sh

# File permissions
chmod 600 .env
chmod 700 logs/
chmod 755 static/

# System security
ufw enable
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp

# Fail2ban configuration
cat > /etc/fail2ban/jail.local << EOF
[nginx-auth]
enabled = true
filter = nginx-auth
logpath = /var/log/nginx/error.log
maxretry = 3
bantime = 3600
EOF

# Log rotation
cat > /etc/logrotate.d/myapp << EOF
/var/log/app/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 www-data www-data
    postrotate
        systemctl reload nginx
    endscript
}
EOF
```

## Deployment Checklist

### Pre-deployment

- [ ] Environment variables configured
- [ ] Database connections tested
- [ ] SSL certificates installed
- [ ] Backup strategy implemented
- [ ] Monitoring configured
- [ ] Security headers enabled
- [ ] Rate limiting configured
- [ ] Log rotation setup

### Deployment Process

1. **Database Migration**
   ```bash
   flask db upgrade
   ```

2. **Static Files**
   ```bash
   flask fab collect-static
   ```

3. **Service Restart**
   ```bash
   systemctl restart gunicorn
   systemctl restart nginx
   ```

4. **Health Check**
   ```bash
   curl -f https://yourdomain.com/health
   ```

### Post-deployment

- [ ] Application accessible
- [ ] Authentication working
- [ ] Database queries functional
- [ ] AI services responding
- [ ] WebSocket connections active
- [ ] Monitoring data flowing
- [ ] Logs being generated
- [ ] Backup jobs running

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Check connection string format
   - Verify database server accessibility
   - Review firewall rules
   - Check user permissions

2. **Static Files Not Loading**
   - Verify nginx static file configuration
   - Check file permissions
   - Review CORS settings
   - Confirm file paths

3. **WebSocket Connection Issues**
   - Verify nginx upgrade headers
   - Check proxy timeout settings
   - Review firewall rules for WebSocket ports
   - Confirm Redis connectivity

4. **High Memory Usage**
   - Review SQLAlchemy connection pooling
   - Check for memory leaks in AI processing
   - Monitor cache usage
   - Review worker process configuration

### Log Analysis

```bash
# Application errors
tail -f /var/log/app/app.log | grep ERROR

# Database slow queries
tail -f /var/log/app/app.log | grep "Slow query"

# Nginx access patterns
tail -f /var/log/nginx/access.log | awk '{print $1}' | sort | uniq -c | sort -nr

# System resources
htop
iotop
netstat -tulpn
```

This production deployment guide provides comprehensive coverage of deploying PgAppForge applications with proper security, monitoring, and scalability considerations.