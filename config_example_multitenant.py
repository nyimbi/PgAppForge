"""
Multi-Tenant SaaS Configuration Example.

This configuration file demonstrates how to set up Flask-AppBuilder
with the multi-tenant SaaS infrastructure.
"""

import os
from datetime import timedelta

# Basic Flask configuration
SECRET_KEY = os.environ.get('SECRET_KEY', 'your-very-long-secret-key-here-change-in-production')
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///multitenant_app.db')
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Flask-AppBuilder configuration
APP_NAME = "Multi-Tenant SaaS Platform"
APP_THEME = "readable.css"  # Bootstrap theme

# Multi-tenant configuration
ENABLE_MULTI_TENANT = True

# Register the TenantManager addon
ADDON_MANAGERS = [
    'flask_appbuilder.tenants.manager.TenantManager'
]

# Tenant system configuration
TENANT_SUBDOMAIN_ENABLED = True
TENANT_CUSTOM_DOMAIN_ENABLED = True
TENANT_ONBOARDING_ENABLED = True
TENANT_DEV_DEFAULT_SLUG = 'dev'  # For development only

# Available plans
TENANT_DEFAULT_PLAN = 'free'
TENANT_AVAILABLE_PLANS = ['free', 'starter', 'professional', 'enterprise']

# Stripe billing configuration (set these in environment variables)
TENANT_BILLING_ENABLED = bool(os.environ.get('STRIPE_SECRET_KEY'))
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')

# Stripe Price IDs (create these in your Stripe dashboard)
STRIPE_STARTER_PRICE_ID = os.environ.get('STRIPE_STARTER_PRICE_ID', 'price_starter_monthly')
STRIPE_PROFESSIONAL_PRICE_ID = os.environ.get('STRIPE_PROFESSIONAL_PRICE_ID', 'price_professional_monthly')
STRIPE_ENTERPRISE_PRICE_ID = os.environ.get('STRIPE_ENTERPRISE_PRICE_ID', 'price_enterprise_monthly')

# Configuration encryption settings (IMPORTANT for production security)
PGAF_CONFIG_MASTER_KEY = os.environ.get('PGAF_CONFIG_MASTER_KEY')  # Required for sensitive config encryption
PGAF_CONFIG_SALT = os.environ.get('PGAF_CONFIG_SALT', 'fab-tenant-config-salt-v1')  # Optional custom salt

# Dynamic plan configuration (optional - overrides defaults)
TENANT_PLAN_CONFIGS = {
    'free': {
        'stripe_price_id': None,
        'usage_based': False,
        'monthly_cost': 0,
        'features': {
            'basic_crud': True,
            'export_csv': True,
            'basic_charts': True,
            'analytics_dashboard': False,
            'advanced_export': False,
            'alerting': False,
            'custom_branding': False,
            'api_access': False
        },
        'limits': {
            'max_users': 3,
            'max_records': 1000,
            'api_calls_per_month': 0,
            'storage_gb': 0.1
        }
    },
    'starter': {
        'stripe_price_id': STRIPE_STARTER_PRICE_ID,
        'usage_based': True,
        'monthly_cost': 29.99,
        'usage_rates': {
            'api_calls': 0.001,  # $0.001 per API call over limit
            'storage_gb': 0.10   # $0.10 per GB over limit
        },
        'features': {
            'basic_crud': True,
            'export_csv': True,
            'basic_charts': True,
            'analytics_dashboard': True,
            'advanced_export': True,
            'alerting': True,
            'custom_branding': False,
            'api_access': True
        },
        'limits': {
            'max_users': 10,
            'max_records': 10000,
            'api_calls_per_month': 10000,
            'storage_gb': 1
        }
    },
    'professional': {
        'stripe_price_id': STRIPE_PROFESSIONAL_PRICE_ID,
        'usage_based': True,
        'monthly_cost': 99.99,
        'usage_rates': {
            'api_calls': 0.0008,
            'storage_gb': 0.08
        },
        'features': {
            'basic_crud': True,
            'export_csv': True,
            'basic_charts': True,
            'analytics_dashboard': True,
            'advanced_export': True,
            'alerting': True,
            'custom_branding': True,
            'api_access': True
        },
        'limits': {
            'max_users': 50,
            'max_records': 100000,
            'api_calls_per_month': 100000,
            'storage_gb': 10
        }
    },
    'enterprise': {
        'stripe_price_id': STRIPE_ENTERPRISE_PRICE_ID,
        'usage_based': False,  # Flat rate, no overages
        'monthly_cost': 299.99,
        'features': {
            'basic_crud': True,
            'export_csv': True,
            'basic_charts': True,
            'analytics_dashboard': True,
            'advanced_export': True,
            'alerting': True,
            'custom_branding': True,
            'api_access': True
        },
        'limits': {
            'max_users': -1,  # Unlimited
            'max_records': -1,  # Unlimited
            'api_calls_per_month': -1,  # Unlimited
            'storage_gb': -1  # Unlimited
        }
    }
}

# Usage tracking configuration
USAGE_TRACKING_ENABLED = True
USAGE_TRACKING_ASYNC = True
USAGE_TRACKING_QUEUE_SIZE = 1000

# Asset storage configuration
TENANT_ASSET_STORAGE = os.environ.get('TENANT_ASSET_STORAGE', 'local')  # 'local' or 's3'

# Local asset storage
TENANT_ASSETS_PATH = os.path.join(os.path.dirname(__file__), 'app', 'static', 'tenant_assets')
TENANT_ASSETS_URL = '/static/tenant_assets'

# S3 asset storage (if using S3)
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
S3_REGION = os.environ.get('S3_REGION', 'us-east-1')
S3_CUSTOM_DOMAIN = os.environ.get('S3_CUSTOM_DOMAIN')  # Optional CDN domain
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')

# Email configuration (for tenant verification emails)
MAIL_SERVER = os.environ.get('MAIL_SERVER')
MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@yourapp.com')

# Security configuration
PERMANENT_SESSION_LIFETIME = timedelta(hours=1)
WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = 3600

# Logging configuration
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
        }
    },
    'root': {
        'level': 'INFO',
        'handlers': ['wsgi']
    },
    'loggers': {
        'flask_appbuilder.tenants': {
            'level': 'DEBUG' if os.environ.get('DEBUG') else 'INFO',
            'handlers': ['wsgi'],
            'propagate': False
        }
    }
}

# Development settings
if os.environ.get('FLASK_ENV') == 'development':
    DEBUG = True
    SQLALCHEMY_ECHO = False
    
    # Development-specific tenant settings
    TENANT_DEV_DEFAULT_SLUG = 'dev'
    
    # Disable email in development (logs links instead)
    MAIL_SERVER = None

# Production settings
if os.environ.get('FLASK_ENV') == 'production':
    DEBUG = False
    SQLALCHEMY_ECHO = False
    
    # Production security settings
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Require HTTPS for custom domains
    PREFERRED_URL_SCHEME = 'https'
    
    # Rate limiting
    RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL', 'memory://')


# Custom FAB Security Manager (optional)
# Uncomment to use custom tenant-aware security
# from app.security import TenantSecurityManager
# CUSTOM_SECURITY_MANAGER = TenantSecurityManager

# Database migration settings
SQLALCHEMY_MIGRATE_REPO = os.path.join(os.path.dirname(__file__), 'migrations')

# Cache configuration
CACHE_TYPE = os.environ.get('CACHE_TYPE', 'simple')
CACHE_DEFAULT_TIMEOUT = 300
if CACHE_TYPE == 'redis':
    CACHE_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Celery configuration (for background tasks)
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

# Enable background processing for heavy operations
EXPORT_USE_CELERY = os.environ.get('EXPORT_USE_CELERY', 'False').lower() == 'true'
BILLING_USE_CELERY = os.environ.get('BILLING_USE_CELERY', 'False').lower() == 'true'