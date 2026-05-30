# 🚀 PgAppForge Apache AGE Graph Analytics Platform
## **COMPREHENSIVE INSTALLATION GUIDE**

> **Production-Ready Deployment Guide**  
> Complete setup instructions for enterprise environments

---

## 📋 **TABLE OF CONTENTS**

1. [System Requirements](#system-requirements)
2. [Pre-Installation Setup](#pre-installation-setup)
3. [Docker Deployment (Recommended)](#docker-deployment-recommended)
4. [Manual Installation](#manual-installation)
5. [Configuration](#configuration)
6. [Security Setup](#security-setup)
7. [Database Initialization](#database-initialization)
8. [First-Time Setup](#first-time-setup)
9. [Monitoring & Logging](#monitoring--logging)
10. [Troubleshooting](#troubleshooting)
11. [Maintenance & Updates](#maintenance--updates)

---

## 🖥️ **SYSTEM REQUIREMENTS**

### **Minimum Requirements**
- **CPU**: 4 cores (2.0 GHz)
- **RAM**: 8 GB
- **Storage**: 50 GB available space
- **Network**: Broadband internet connection

### **Recommended Requirements**
- **CPU**: 8+ cores (3.0 GHz)
- **RAM**: 16+ GB
- **Storage**: 100+ GB SSD
- **Network**: High-speed internet with low latency

### **Operating System Support**
- ✅ Ubuntu 20.04+ LTS
- ✅ CentOS 8+ / RHEL 8+
- ✅ Debian 11+
- ✅ macOS 12+ (for development)
- ✅ Windows 10+ with WSL2

### **Software Dependencies**
- **Docker**: 20.10+
- **Docker Compose**: 2.0+
- **Python**: 3.9+ (for manual installation)
- **PostgreSQL**: 13+ with Apache AGE extension
- **Node.js**: 16+ (for frontend build tools)

---

## 🔧 **PRE-INSTALLATION SETUP**

### **1. Install Docker & Docker Compose**

#### **Ubuntu/Debian:**
```bash
# Update package index
sudo apt update

# Install required packages
sudo apt install -y apt-transport-https ca-certificates curl gnupg lsb-release

# Add Docker GPG key
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Add Docker repository
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Add user to docker group
sudo usermod -aG docker $USER
```

#### **CentOS/RHEL:**
```bash
# Install Docker
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install -y docker-ce docker-ce-cli containerd.io

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Add user to docker group
sudo usermod -aG docker $USER
```

### **2. Configure System Resources**

#### **Increase system limits:**
```bash
# Edit limits configuration
sudo nano /etc/security/limits.conf

# Add these lines:
* soft nofile 65536
* hard nofile 65536
* soft nproc 32768
* hard nproc 32768
```

#### **Configure kernel parameters:**
```bash
# Edit sysctl configuration
sudo nano /etc/sysctl.conf

# Add these lines:
vm.max_map_count=262144
net.core.somaxconn=65535
fs.file-max=2097152
```

#### **Apply changes:**
```bash
sudo sysctl -p
sudo systemctl restart docker
```

---

## 🐳 **DOCKER DEPLOYMENT (RECOMMENDED)**

### **1. Clone the Repository**
```bash
# Clone the repository
git clone https://github.com/your-org/flask-appbuilder-age-analytics.git
cd flask-appbuilder-age-analytics

# Or download and extract the release package
wget https://releases.example.com/fab-ext-v1.0.0.tar.gz
tar -xzf fab-ext-v1.0.0.tar.gz
cd fab-ext-v1.0.0
```

### **2. Configure Environment Variables**
```bash
# Copy environment template
cp .env.template .env

# Edit environment configuration
nano .env
```

#### **Required Environment Variables:**
```bash
# Database Configuration
POSTGRES_PASSWORD=your_secure_database_password_here
POSTGRES_DB=graph_analytics_db
POSTGRES_USER=graph_admin

# Redis Configuration
REDIS_PASSWORD=your_secure_redis_password_here

# Application Security
SECRET_KEY=your_very_long_secret_key_here_64_characters_minimum
SECURITY_PASSWORD_SALT=your_password_salt_here

# AI Features (Optional)
ENABLE_AI_ASSISTANT=true
OPENAI_API_KEY=your_openai_api_key_here

# Enterprise Features (Optional)
ENABLE_SSO=false
LDAP_SERVER=ldap://your-ldap-server.com
LDAP_BIND_DN=cn=admin,dc=company,dc=com
LDAP_BIND_PASSWORD=ldap_admin_password

# Monitoring
GRAFANA_PASSWORD=your_grafana_admin_password_here

# Feature Flags
ENABLE_FEDERATED_ANALYTICS=true
ENABLE_MULTIMODAL_PROCESSING=true
```

### **3. Generate Secure Passwords**
```bash
# Generate secure passwords
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))"
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('SECURITY_PASSWORD_SALT=' + secrets.token_urlsafe(32))"
```

### **4. Deploy the Stack**
```bash
# Pull all required images
docker-compose -f docker-compose.prod.yml pull

# Build and start all services
docker-compose -f docker-compose.prod.yml up -d

# Check service status
docker-compose -f docker-compose.prod.yml ps

# View logs
docker-compose -f docker-compose.prod.yml logs -f webapp
```

### **5. Initialize the Database**
```bash
# Wait for PostgreSQL to be ready
docker-compose -f docker-compose.prod.yml logs postgres-age

# Initialize the application database
docker-compose -f docker-compose.prod.yml exec webapp python init_db.py

# Create admin user
docker-compose -f docker-compose.prod.yml exec webapp python create_admin.py
```

---

## 📦 **MANUAL INSTALLATION**

### **1. Install System Dependencies**

#### **Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y \
    python3.9 python3.9-dev python3.9-venv \
    postgresql-13 postgresql-server-dev-13 \
    redis-server \
    nginx \
    git curl wget \
    build-essential \
    libjpeg-dev libpng-dev libtiff-dev \
    libffi-dev libssl-dev \
    pkg-config
```

### **2. Install Apache AGE Extension**
```bash
# Add PostgreSQL APT repository
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list

# Install Apache AGE
sudo apt update
sudo apt install -y postgresql-13-age

# Configure PostgreSQL
sudo -u postgres createuser --superuser graph_admin
sudo -u postgres createdb -O graph_admin graph_analytics_db
sudo -u postgres psql -d graph_analytics_db -c "CREATE EXTENSION IF NOT EXISTS age;"
sudo -u postgres psql -d graph_analytics_db -c "LOAD 'age';"
sudo -u postgres psql -d graph_analytics_db -c "SET search_path = ag_catalog, public;"
```

### **3. Setup Python Environment**
```bash
# Create virtual environment
python3.9 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install application
pip install -r requirements.prod.txt
pip install -e .
```

### **4. Configure Services**

#### **Configure PostgreSQL:**
```bash
# Edit PostgreSQL configuration
sudo nano /etc/postgresql/13/main/postgresql.conf

# Update these settings:
shared_preload_libraries = 'age'
max_connections = 200
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 8MB
maintenance_work_mem = 128MB
```

#### **Configure Redis:**
```bash
# Edit Redis configuration
sudo nano /etc/redis/redis.conf

# Update these settings:
requirepass your_redis_password
maxmemory 512mb
maxmemory-policy allkeys-lru
```

#### **Configure Nginx:**
```bash
# Copy nginx configuration
sudo cp nginx/nginx.conf /etc/nginx/sites-available/graph-analytics
sudo ln -s /etc/nginx/sites-available/graph-analytics /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Start services
sudo systemctl restart postgresql
sudo systemctl restart redis
sudo systemctl restart nginx
```

---

## ⚙️ **CONFIGURATION**

### **Application Configuration**
Create `config.py`:
```python
import os
from datetime import timedelta

class Config:
    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URI',
        'postgresql://graph_admin:password@localhost:5432/graph_analytics_db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 20,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
    }
    
    # Security configuration
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
    SECURITY_PASSWORD_SALT = os.environ.get('SECURITY_PASSWORD_SALT', 'salt')
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    
    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Cache configuration
    CACHE_TYPE = 'redis'
    CACHE_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    CACHE_DEFAULT_TIMEOUT = 3600
    
    # Upload configuration
    UPLOAD_FOLDER = '/app/uploads'
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB
    
    # AI features
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    ENABLE_AI_ASSISTANT = os.environ.get('ENABLE_AI_ASSISTANT', 'false').lower() == 'true'
    
    # Feature flags
    ENABLE_FEDERATED_ANALYTICS = os.environ.get('ENABLE_FEDERATED_ANALYTICS', 'true').lower() == 'true'
    ENABLE_MULTIMODAL_PROCESSING = os.environ.get('ENABLE_MULTIMODAL_PROCESSING', 'true').lower() == 'true'
    
    # Logging configuration
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = os.environ.get('LOG_FILE', '/app/logs/application.log')
```

---

## 🔒 **SECURITY SETUP**

### **1. SSL Certificate Setup**
```bash
# Generate self-signed certificate (for testing)
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout nginx/ssl/key.pem \
    -out nginx/ssl/cert.pem \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=your-domain.com"

# For production, use Let's Encrypt:
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### **2. Firewall Configuration**
```bash
# Configure UFW (Ubuntu)
sudo ufw enable
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# For development, also allow direct access:
sudo ufw allow 8080/tcp
sudo ufw allow 3000/tcp
```

### **3. Create Security Configuration**
```bash
# Create security settings file
cat > security_config.py << EOF
# Security Manager Configuration
FAB_SECURITY_MANAGER_CLASS = 'pgappforge.security.manager.SecurityManager'

# Password complexity requirements
AUTH_PASSWORD_COMPLEXITY_ENABLED = True
AUTH_PASSWORD_MIN_LENGTH = 12
AUTH_PASSWORD_COMPLEXITY_VALIDATOR = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]'

# Session security
PERMANENT_SESSION_LIFETIME = 43200  # 12 hours
SESSION_TIMEOUT_MINUTES = 720  # 12 hours

# Login security
AUTH_LOGIN_BAD_RESPONSE_MESSAGE = "Invalid credentials"
AUTH_LOGIN_USERNAME_CI = False
AUTH_RATE_LIMITED = True
AUTH_RATE_LIMIT = "5 per minute"

# LDAP configuration (if enabled)
AUTH_TYPE = AUTH_DB  # or AUTH_LDAP
AUTH_LDAP_SERVER = os.environ.get('LDAP_SERVER', 'ldap://localhost')
AUTH_LDAP_BIND_USER = os.environ.get('LDAP_BIND_DN', '')
AUTH_LDAP_BIND_PASSWORD = os.environ.get('LDAP_BIND_PASSWORD', '')
AUTH_LDAP_SEARCH = "ou=people,dc=company,dc=com"
AUTH_LDAP_UID_FIELD = "uid"
AUTH_LDAP_FIRSTNAME_FIELD = "givenName"
AUTH_LDAP_LASTNAME_FIELD = "sn"
AUTH_LDAP_EMAIL_FIELD = "mail"
EOF
```

---

## 💾 **DATABASE INITIALIZATION**

### **1. Create Initialization Scripts**
```bash
mkdir -p init-scripts
```

Create `init-scripts/01-init-age.sql`:
```sql
-- Initialize Apache AGE extension
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create initial graph
SELECT create_graph('analytics_graph');

-- Set up permissions
GRANT USAGE ON SCHEMA ag_catalog TO graph_admin;
GRANT ALL ON ALL TABLES IN SCHEMA ag_catalog TO graph_admin;
GRANT ALL ON ALL SEQUENCES IN SCHEMA ag_catalog TO graph_admin;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA ag_catalog TO graph_admin;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_ag_label_vertex_id ON ag_catalog.ag_label USING btree (id);
CREATE INDEX IF NOT EXISTS idx_ag_label_edge_id ON ag_catalog.ag_label USING btree (id);
```

### **2. Database Initialization Script**
Create `init_db.py`:
```python
#!/usr/bin/env python3
"""Database initialization script"""

import os
import sys
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.security.sqla.manager import SecurityManager

# Initialize Flask app
app = Flask(__name__)
app.config.from_object('config.Config')

# Initialize database
db = SQLA(app)
appbuilder = AppBuilder(app, db.session, security_manager_class=SecurityManager)

def init_database():
    """Initialize the database with all tables"""
    print("🗄️  Creating database tables...")
    
    try:
        # Create all tables
        db.create_all()
        print("✅ Database tables created successfully")
        
        # Initialize Apache AGE graph
        from pgappforge.database.graph_manager import get_graph_manager
        graph_manager = get_graph_manager()
        graph_manager.create_graph('analytics_graph')
        print("✅ Apache AGE graph initialized successfully")
        
        # Create default admin role and permissions
        print("🔐 Setting up security roles...")
        appbuilder.sm.sync_role_definitions()
        print("✅ Security roles configured successfully")
        
        print("🎉 Database initialization completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return False

if __name__ == '__main__':
    with app.app_context():
        success = init_database()
        sys.exit(0 if success else 1)
```

### **3. Admin User Creation Script**
Create `create_admin.py`:
```python
#!/usr/bin/env python3
"""Create admin user script"""

import getpass
import sys
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.security.sqla.manager import SecurityManager

app = Flask(__name__)
app.config.from_object('config.Config')

db = SQLA(app)
appbuilder = AppBuilder(app, db.session, security_manager_class=SecurityManager)

def create_admin_user():
    """Create the initial admin user"""
    print("👤 Creating admin user...")
    
    # Get admin details
    username = input("Enter admin username (default: admin): ").strip() or "admin"
    email = input("Enter admin email: ").strip()
    
    while not email:
        print("❌ Email is required")
        email = input("Enter admin email: ").strip()
    
    first_name = input("Enter first name: ").strip() or "Admin"
    last_name = input("Enter last name: ").strip() or "User"
    
    # Get password
    while True:
        password = getpass.getpass("Enter admin password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        
        if password != password_confirm:
            print("❌ Passwords don't match. Please try again.")
            continue
        
        if len(password) < 8:
            print("❌ Password must be at least 8 characters long.")
            continue
            
        break
    
    try:
        # Create admin user
        admin_role = appbuilder.sm.find_role("Admin")
        if not admin_role:
            print("❌ Admin role not found. Make sure database is initialized.")
            return False
        
        user = appbuilder.sm.add_user(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            role=admin_role,
            password=password
        )
        
        if user:
            print(f"✅ Admin user '{username}' created successfully!")
            print(f"📧 Email: {email}")
            print(f"🔑 You can now login at: http://localhost:8080/login")
            return True
        else:
            print("❌ Failed to create admin user")
            return False
            
    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        return False

if __name__ == '__main__':
    with app.app_context():
        success = create_admin_user()
        sys.exit(0 if success else 1)
```

---

## 🎯 **FIRST-TIME SETUP**

### **1. Access the Application**
```bash
# Check if services are running
docker-compose -f docker-compose.prod.yml ps

# Access the application
open http://localhost:8080

# Or check health status
curl http://localhost:8080/health
```

### **2. Initial Configuration**
1. **Login** with the admin credentials you created
2. **Navigate to** the Graph Analytics dashboard
3. **Create your first graph** database
4. **Import sample data** (if available)
5. **Configure user roles** and permissions
6. **Set up monitoring** dashboards

### **3. Sample Data Import**
```python
# Connect to the application
python3 -c "
import requests

# Login and get session
session = requests.Session()
login_data = {
    'username': 'admin',
    'password': 'your_admin_password'
}
response = session.post('http://localhost:8080/login', data=login_data)

# Import sample data
sample_data = {
    'nodes': [
        {'id': 1, 'label': 'Person', 'name': 'Alice'},
        {'id': 2, 'label': 'Person', 'name': 'Bob'},
        {'id': 3, 'label': 'Company', 'name': 'Tech Corp'}
    ],
    'relationships': [
        {'source': 1, 'target': 2, 'type': 'KNOWS'},
        {'source': 1, 'target': 3, 'type': 'WORKS_FOR'},
        {'source': 2, 'target': 3, 'type': 'WORKS_FOR'}
    ]
}

response = session.post('http://localhost:8080/api/graph/import', json=sample_data)
print('Sample data import:', response.json())
"
```

---

## 📊 **MONITORING & LOGGING**

### **1. Access Monitoring Dashboards**
- **Application**: http://localhost:8080
- **Grafana**: http://localhost:3000 (admin/your_grafana_password)
- **Prometheus**: http://localhost:9091

### **2. Log Locations**
```bash
# Application logs
docker-compose -f docker-compose.prod.yml logs webapp

# Database logs
docker-compose -f docker-compose.prod.yml logs postgres-age

# Nginx logs
docker-compose -f docker-compose.prod.yml logs nginx

# All services
docker-compose -f docker-compose.prod.yml logs -f
```

### **3. Health Checks**
```bash
# Application health
curl http://localhost:8080/health

# Database health
docker-compose -f docker-compose.prod.yml exec postgres-age pg_isready -U graph_admin

# Redis health
docker-compose -f docker-compose.prod.yml exec redis redis-cli ping

# Full system status
docker-compose -f docker-compose.prod.yml exec webapp python tests/validation/health_check.py
```

---

## 🛠️ **TROUBLESHOOTING**

### **Common Issues & Solutions**

#### **1. Database Connection Issues**
```bash
# Check PostgreSQL status
docker-compose -f docker-compose.prod.yml logs postgres-age

# Reset database if needed
docker-compose -f docker-compose.prod.yml down -v
docker-compose -f docker-compose.prod.yml up -d postgres-age
docker-compose -f docker-compose.prod.yml exec postgres-age createdb -U graph_admin graph_analytics_db
```

#### **2. Apache AGE Extension Issues**
```bash
# Verify AGE extension
docker-compose -f docker-compose.prod.yml exec postgres-age psql -U graph_admin -d graph_analytics_db -c "SELECT * FROM pg_extension WHERE extname = 'age';"

# Reinstall AGE extension if needed
docker-compose -f docker-compose.prod.yml exec postgres-age psql -U graph_admin -d graph_analytics_db -c "DROP EXTENSION IF EXISTS age CASCADE; CREATE EXTENSION age;"
```

#### **3. Permission Issues**
```bash
# Fix file permissions
sudo chown -R $(whoami):$(whoami) .
chmod +x init_db.py create_admin.py

# Fix Docker permissions
sudo usermod -aG docker $USER
sudo systemctl restart docker
```

#### **4. Memory Issues**
```bash
# Check memory usage
docker stats

# Increase memory limits in docker-compose.yml
# Add to webapp service:
deploy:
  resources:
    limits:
      memory: 2G
    reservations:
      memory: 1G
```

#### **5. Port Conflicts**
```bash
# Check port usage
sudo netstat -tulpn | grep :8080

# Stop conflicting services
sudo systemctl stop apache2  # or nginx, if running outside Docker
```

### **Log Analysis**
```bash
# View error logs
docker-compose -f docker-compose.prod.yml logs webapp | grep ERROR

# Monitor real-time logs
docker-compose -f docker-compose.prod.yml logs -f webapp

# Check specific service logs
docker-compose -f docker-compose.prod.yml logs postgres-age | tail -100
```

---

## 🔄 **MAINTENANCE & UPDATES**

### **1. Backup Procedures**
```bash
#!/bin/bash
# backup.sh - Database backup script

BACKUP_DIR="/backups/$(date +%Y-%m-%d)"
mkdir -p $BACKUP_DIR

# Backup PostgreSQL database
docker-compose -f docker-compose.prod.yml exec -T postgres-age pg_dump -U graph_admin graph_analytics_db > $BACKUP_DIR/database.sql

# Backup uploaded files
docker cp fab-ext-webapp:/app/uploads $BACKUP_DIR/

# Backup configuration
cp .env $BACKUP_DIR/
cp docker-compose.prod.yml $BACKUP_DIR/

# Create archive
tar -czf $BACKUP_DIR.tar.gz $BACKUP_DIR
rm -rf $BACKUP_DIR

echo "Backup completed: $BACKUP_DIR.tar.gz"
```

### **2. Update Procedures**
```bash
#!/bin/bash
# update.sh - Application update script

echo "🔄 Starting update process..."

# Backup current installation
./backup.sh

# Pull latest images
docker-compose -f docker-compose.prod.yml pull

# Stop services
docker-compose -f docker-compose.prod.yml down

# Update application code
git pull origin main

# Restart services
docker-compose -f docker-compose.prod.yml up -d

# Run migrations if needed
docker-compose -f docker-compose.prod.yml exec webapp python migrate_db.py

echo "✅ Update completed successfully!"
```

### **3. Monitoring Scripts**
```bash
#!/bin/bash
# monitor.sh - System monitoring script

echo "📊 System Status Report - $(date)"
echo "================================"

# Docker service status
echo "🐳 Docker Services:"
docker-compose -f docker-compose.prod.yml ps

# Database status
echo -e "\n💾 Database Status:"
docker-compose -f docker-compose.prod.yml exec -T postgres-age psql -U graph_admin -d graph_analytics_db -c "SELECT datname, numbackends, xact_commit, xact_rollback FROM pg_stat_database WHERE datname = 'graph_analytics_db';"

# Application health
echo -e "\n🏥 Application Health:"
curl -s http://localhost:8080/health | python3 -m json.tool

# Disk usage
echo -e "\n💽 Disk Usage:"
df -h

# Memory usage
echo -e "\n🧠 Memory Usage:"
free -h
```

---

## 📞 **SUPPORT & DOCUMENTATION**

### **Getting Help**
- **Documentation**: http://localhost:8080/docs (after installation)
- **API Reference**: http://localhost:8080/swagger
- **Health Check**: http://localhost:8080/health
- **Metrics**: http://localhost:8080/metrics

### **Support Channels**
- **GitHub Issues**: [Repository Issues](https://github.com/your-org/flask-appbuilder-age-analytics/issues)
- **Documentation**: [Online Documentation](https://docs.example.com)
- **Community**: [Discord/Slack Channel](https://discord.gg/example)

---

## ✅ **INSTALLATION CHECKLIST**

### **Pre-Installation** ☐
- [ ] System requirements verified
- [ ] Docker & Docker Compose installed
- [ ] Network ports available (80, 443, 8080, 5432, 6379)
- [ ] SSL certificates prepared (for production)

### **Installation** ☐
- [ ] Repository cloned/downloaded
- [ ] Environment variables configured
- [ ] Secure passwords generated
- [ ] Docker services deployed
- [ ] Database initialized
- [ ] Admin user created

### **Post-Installation** ☐
- [ ] Application accessible
- [ ] Health checks passing
- [ ] Sample data imported
- [ ] Monitoring dashboards configured
- [ ] Backup procedures tested
- [ ] Security hardening applied
- [ ] Documentation reviewed
- [ ] Team training scheduled

---

**🎉 Congratulations! Your PgAppForge Apache AGE Graph Analytics Platform is now ready for production use!**

> **Next Steps**: Explore the comprehensive features, import your data, and start building powerful graph analytics applications.

---

*Installation Guide v1.0 - PgAppForge Apache AGE Graph Analytics Platform*  
*Last Updated: $(date +%Y-%m-%d)*  
*For the latest updates, visit: https://docs.example.com*