# Multi-Tenant SaaS Setup Guide

This guide provides step-by-step instructions for setting up the multi-tenant SaaS infrastructure in your Flask-AppBuilder application.

## 🚀 Quick Start

### 1. Installation

```bash
# Install with multi-tenant dependencies
pip install "Flask-AppBuilder[export,analytics,billing,mfa]"

# Or install development version
pip install -e ".[export,analytics,billing,mfa]"
```

### 2. Basic Configuration

Create or update your `config.py`:

```python
# Copy from config_example_multitenant.py and customize
from config_example_multitenant import *

# Required: Set your secret key
SECRET_KEY = 'your-very-long-secret-key-change-in-production'

# Required: Database URL
SQLALCHEMY_DATABASE_URI = 'postgresql://user:pass@localhost/dbname'

# Enable multi-tenant features
ENABLE_MULTI_TENANT = True
ADDON_MANAGERS = ['flask_appbuilder.tenants.manager.TenantManager']
```

### 3. Application Setup

Update your main application file:

```python
from flask import Flask
from flask_appbuilder import AppBuilder, SQLA

# Create Flask app
app = Flask(__name__)
app.config.from_object('config')

# Initialize database
db = SQLA(app)

# Initialize Flask-AppBuilder (will auto-load TenantManager from ADDON_MANAGERS)
appbuilder = AppBuilder(app, db.session)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
```

### 4. Database Setup

```bash
# Create database tables
flask fab create-db

# Or if using migrations
flask db init
flask db migrate -m "Add multi-tenant support"
flask db upgrade
```

### 5. Create Admin User

```bash
flask fab create-admin
```

## 📋 Complete Configuration

### Environment Variables

Set these environment variables for production:

```bash
# Required
export SECRET_KEY="your-super-secret-key-here"
export DATABASE_URL="postgresql://user:pass@host:port/database"

# Stripe Billing (Optional)
export STRIPE_PUBLISHABLE_KEY="pk_live_..."
export STRIPE_SECRET_KEY="sk_live_..."
export STRIPE_STARTER_PRICE_ID="price_..."
export STRIPE_PROFESSIONAL_PRICE_ID="price_..."
export STRIPE_ENTERPRISE_PRICE_ID="price_..."

# Email Configuration (for tenant verification)
export MAIL_SERVER="smtp.your-provider.com"
export MAIL_PORT="587"
export MAIL_USERNAME="your-email@example.com"
export MAIL_PASSWORD="your-password"

# Asset Storage (Optional - S3)
export TENANT_ASSET_STORAGE="s3"
export S3_BUCKET_NAME="your-tenant-assets-bucket"
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"

# Background Tasks (Optional)
export REDIS_URL="redis://localhost:6379/0"
export CELERY_BROKER_URL="redis://localhost:6379/0"
```

### Advanced Configuration

```python
# config.py - Advanced settings

# Custom plan definitions
TENANT_PLAN_CONFIGS = {
    'startup': {
        'stripe_price_id': 'price_startup_monthly',
        'usage_based': True,
        'monthly_cost': 19.99,
        'features': {
            'basic_crud': True,
            'export_csv': True,
            'basic_charts': True,
            'analytics_dashboard': True,
            'advanced_export': False,
            'alerting': False,
            'custom_branding': False,
            'api_access': True
        },
        'limits': {
            'max_users': 5,
            'max_records': 5000,
            'api_calls_per_month': 5000,
            'storage_gb': 0.5
        }
    }
}

# Usage tracking optimization
USAGE_TRACKING_ASYNC = True
USAGE_TRACKING_QUEUE_SIZE = 5000

# Asset storage configuration
TENANT_ASSET_STORAGE = 's3'  # or 'local'
S3_CUSTOM_DOMAIN = 'cdn.yourapp.com'  # Optional CDN

# Background job processing
EXPORT_USE_CELERY = True
BILLING_USE_CELERY = True
```

## 🔧 Development Setup

### 1. Development Configuration

```python
# config.py for development
import os

# Development overrides
if os.environ.get('FLASK_ENV') == 'development':
    DEBUG = True
    
    # Use SQLite for development
    SQLALCHEMY_DATABASE_URI = 'sqlite:///dev_multitenant.db'
    
    # Default development tenant
    TENANT_DEV_DEFAULT_SLUG = 'dev'
    
    # Disable email (will log verification links)
    MAIL_SERVER = None
    
    # Local asset storage
    TENANT_ASSET_STORAGE = 'local'
```

### 2. Create Development Tenant

After setting up your app, create a development tenant:

```python
from flask_appbuilder.models.tenant_models import Tenant, TenantUser
from flask_appbuilder.security.sqla.models import User

# Create development tenant
dev_tenant = Tenant(
    slug='dev',
    name='Development Tenant',
    primary_contact_email='dev@localhost',
    plan_id='enterprise',  # Full features for development
    status='active'
)
db.session.add(dev_tenant)
db.session.commit()

# Link admin user to tenant
admin_user = User.query.filter_by(username='admin').first()
tenant_user = TenantUser(
    tenant_id=dev_tenant.id,
    user_id=admin_user.id,
    role_within_tenant='admin',
    is_active=True
)
db.session.add(tenant_user)
db.session.commit()
```

### 3. Development URLs

Access your app:
- Main app: `http://localhost:8080`
- Dev tenant: `http://dev.localhost:8080` (requires /etc/hosts entry)
- Tenant admin: `http://localhost:8080/tenant/admin`
- Onboarding: `http://localhost:8080/onboarding`

## 🔒 Security Setup

### 1. Tenant Isolation Verification

Test tenant isolation in development:

```python
# Create test script
from your_app import app, db
from flask_appbuilder.models.tenant_models import Tenant
from flask_appbuilder.models.tenant_examples import CustomerMT

with app.app_context():
    # Create test tenants
    tenant1 = Tenant.query.filter_by(slug='tenant1').first()
    tenant2 = Tenant.query.filter_by(slug='tenant2').first()
    
    # Create test data
    customer1 = CustomerMT(name='Customer 1', tenant_id=tenant1.id)
    customer2 = CustomerMT(name='Customer 2', tenant_id=tenant2.id)
    db.session.add_all([customer1, customer2])
    db.session.commit()
    
    # Verify isolation
    from flask_appbuilder.models.tenant_context import tenant_context
    
    with tenant_context.with_tenant_context(tenant1):
        customers = CustomerMT.current_tenant().all()
        assert len(customers) == 1
        assert customers[0].name == 'Customer 1'
        print("✓ Tenant isolation working correctly")
```

### 2. Production Security Checklist

- [ ] Set strong `SECRET_KEY` (32+ characters)
- [ ] Use PostgreSQL or MySQL (not SQLite) for production
- [ ] Enable HTTPS for custom domains
- [ ] Configure proper CORS settings
- [ ] Set up rate limiting
- [ ] Configure security headers
- [ ] Enable database connection pooling
- [ ] Set up monitoring and alerting

## 🎨 Customization

### 1. Custom Tenant Models

Create tenant-aware versions of your models:

```python
from flask_appbuilder.models.tenant_models import TenantAwareMixin
from flask_appbuilder import Model
from sqlalchemy import Column, Integer, String

class MyModel(TenantAwareMixin, Model):
    __tablename__ = 'my_model_mt'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    
    # tenant_id is automatically added by TenantAwareMixin
```

### 2. Custom Views

Create tenant-aware views:

```python
from flask_appbuilder import ModelView
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.models.tenant_context import require_tenant_context

class MyModelView(ModelView):
    datamodel = SQLAInterface(MyModel)
    
    @require_tenant_context()
    def list(self):
        # Automatically filtered by tenant
        return super().list()
```

### 3. Custom Branding

Set up tenant branding programmatically:

```python
from flask_appbuilder.tenants.branding import get_branding_manager

branding_manager = get_branding_manager()

# Update tenant branding
branding_data = {
    'colors': {
        'primary': '#ff6b35',
        'secondary': '#004e89'
    },
    'app_name': 'My Custom App'
}

branding_manager.update_tenant_branding(tenant_id, branding_data)
```

## 📊 Monitoring & Analytics

### 1. Usage Monitoring

Track usage programmatically:

```python
from flask_appbuilder.tenants.usage_tracking import track_api_call, track_storage

# Track API usage
track_api_call('/api/data', 'GET')

# Track storage usage
track_storage(file_size_bytes, operation='upload', file_type='pdf')
```

### 2. Health Checks

Monitor tenant health:

```python
from flask_appbuilder.tenants.billing import get_billing_service

billing_service = get_billing_service()
metrics = billing_service.get_usage_metrics(tenant)

for metric in metrics:
    if metric.is_over_limit:
        print(f"⚠️ Tenant over limit: {metric.resource_type}")
    elif metric.is_warning_level:
        print(f"⚡ Tenant approaching limit: {metric.resource_type}")
```

## 🚨 Troubleshooting

### Common Issues

1. **"TenantManager not found"**
   - Ensure `ADDON_MANAGERS` is set in config
   - Check that Flask-AppBuilder version supports addons

2. **"No tenant context"**
   - Verify subdomain setup
   - Check tenant exists and is active
   - Ensure middleware is loaded

3. **Stripe errors**
   - Verify API keys are correct
   - Check price IDs exist in Stripe dashboard
   - Ensure webhook endpoints are configured

4. **Email not sending**
   - Check MAIL_* configuration
   - Verify SMTP credentials
   - Check firewall/security groups

### Debug Mode

Enable debug logging:

```python
import logging
logging.getLogger('flask_appbuilder.tenants').setLevel(logging.DEBUG)
```

### Development Tools

Useful management commands:

```bash
# List all tenants
flask shell -c "from flask_appbuilder.models.tenant_models import Tenant; print([t.slug for t in Tenant.query.all()])"

# Create test tenant
flask shell -c "from create_test_tenant import create_tenant; create_tenant('test')"

# Check tenant isolation
flask shell -c "from test_isolation import run_tests; run_tests()"
```

## 📚 Next Steps

1. **Customize Plans**: Modify `TENANT_PLAN_CONFIGS` for your pricing
2. **Add Custom Models**: Convert your models to use `TenantAwareMixin`
3. **Set up Stripe**: Configure webhooks and test payments
4. **Configure CDN**: Set up asset CDN for better performance
5. **Add Monitoring**: Implement health checks and alerts
6. **Write Tests**: Create comprehensive test suite for tenant isolation

## 🔗 Resources

- [Flask-AppBuilder Documentation](http://flask-appbuilder.readthedocs.io/)
- [Stripe Documentation](https://stripe.com/docs)
- [Multi-Tenant Architecture Patterns](https://docs.microsoft.com/en-us/azure/architecture/guide/multitenant/)
- [Flask-Mail Documentation](https://pythonhosted.org/Flask-Mail/)

## 🆘 Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review application logs for errors
3. Verify configuration against this guide
4. Test tenant isolation in development
5. Check environment variables are set correctly

The multi-tenant system is now ready for production use with proper configuration and setup!