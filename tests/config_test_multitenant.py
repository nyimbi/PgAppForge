"""
Test configuration for multi-tenant SaaS testing.

This configuration is optimized for testing multi-tenant functionality
with in-memory databases and minimal external dependencies.
"""

import os
from datetime import timedelta

# Basic Flask configuration
SECRET_KEY = 'test-secret-key-for-multi-tenant-testing'
TESTING = True
WTF_CSRF_ENABLED = False

# Database configuration - use in-memory SQLite for speed
SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ECHO = False  # Set to True for debugging SQL queries

# PgAppForge configuration
APP_NAME = "Multi-Tenant Test App"
APP_THEME = "readable.css"

# Multi-tenant configuration
ENABLE_MULTI_TENANT = True

# Register the TenantManager addon
ADDON_MANAGERS = [
    'pgappforge.tenants.manager.TenantManager'
]

# Tenant system configuration
TENANT_SUBDOMAIN_ENABLED = True
TENANT_CUSTOM_DOMAIN_ENABLED = True
TENANT_ONBOARDING_ENABLED = True
TENANT_DEV_DEFAULT_SLUG = 'test'

# Available plans for testing
TENANT_DEFAULT_PLAN = 'free'
TENANT_AVAILABLE_PLANS = ['free', 'starter', 'professional', 'enterprise']

# Test plan configurations
TENANT_PLAN_CONFIGS = {
    'free': {
        'stripe_price_id': None,
        'usage_based': False,
        'monthly_cost': 0,
        'features': {
            'basic_crud': True,
            'export_csv': True,
            'basic_charts': False,
            'analytics_dashboard': False,
            'advanced_export': False,
            'alerting': False,
            'custom_branding': False,
            'api_access': False
        },
        'limits': {
            'max_users': 2,
            'max_records': 500,
            'api_calls_per_month': 0,
            'storage_gb': 0.1
        }
    },
    'starter': {
        'stripe_price_id': 'price_test_starter',
        'usage_based': True,
        'monthly_cost': 29.99,
        'usage_rates': {
            'api_calls': 0.001,
            'storage_gb': 0.10
        },
        'features': {
            'basic_crud': True,
            'export_csv': True,
            'basic_charts': True,
            'analytics_dashboard': True,
            'advanced_export': True,
            'alerting': False,
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
        'stripe_price_id': 'price_test_professional',
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
        'stripe_price_id': 'price_test_enterprise',
        'usage_based': False,
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

# Disable billing for tests (no Stripe required)
TENANT_BILLING_ENABLED = False
STRIPE_PUBLISHABLE_KEY = 'pk_test_fake_key_for_testing'
STRIPE_SECRET_KEY = 'sk_test_fake_key_for_testing'

# Test Stripe Price IDs
STRIPE_STARTER_PRICE_ID = 'price_test_starter'
STRIPE_PROFESSIONAL_PRICE_ID = 'price_test_professional'
STRIPE_ENTERPRISE_PRICE_ID = 'price_test_enterprise'

# Usage tracking configuration
USAGE_TRACKING_ENABLED = True
USAGE_TRACKING_ASYNC = False  # Synchronous for testing
USAGE_TRACKING_QUEUE_SIZE = 100

# Asset storage configuration - use local for testing
TENANT_ASSET_STORAGE = 'local'
TENANT_ASSETS_PATH = '/tmp/test_tenant_assets'
TENANT_ASSETS_URL = '/static/tenant_assets'

# Disable email for testing
MAIL_SERVER = None
MAIL_DEFAULT_SENDER = 'test@example.com'

# Security configuration
PERMANENT_SESSION_LIFETIME = timedelta(hours=1)
WTF_CSRF_ENABLED = False  # Disabled for testing
WTF_CSRF_TIME_LIMIT = None

# Performance optimizations for testing
TENANT_DB_POOL_SIZE = 5
TENANT_DB_MAX_OVERFLOW = 10
TENANT_DB_POOL_RECYCLE = 300
TENANT_DB_POOL_TIMEOUT = 30
TENANT_DB_ECHO_QUERIES = False

# Disable table partitioning for testing
TENANT_ENABLE_PARTITIONING = False

# Redis configuration - not required for basic testing
REDIS_URL = None
CACHE_TYPE = 'simple'
CACHE_DEFAULT_TIMEOUT = 60

# Celery configuration - disabled for testing
CELERY_BROKER_URL = None
CELERY_RESULT_BACKEND = None
EXPORT_USE_CELERY = False
BILLING_USE_CELERY = False

# Disable auto-scaling for tests
ENABLE_AUTO_SCALING = False

# AWS configuration - not needed for testing
S3_BUCKET_NAME = None
AWS_ACCESS_KEY_ID = None
AWS_SECRET_ACCESS_KEY = None
CLOUDFRONT_DISTRIBUTION_ID = None
CLOUDFRONT_DOMAIN = None

# Database read replicas - none for testing
DATABASE_READ_REPLICAS = []

# Logging configuration for testing
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'level': 'WARNING'  # Reduce log noise during testing
        }
    },
    'root': {
        'level': 'WARNING',
        'handlers': ['console']
    },
    'loggers': {
        'pgappforge.tenants': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False
        },
        'sqlalchemy.engine': {
            'level': 'WARNING',  # Reduce SQL logging noise
            'handlers': ['console'],
            'propagate': False
        }
    }
}

# Test-specific settings
TEST_TENANT_COUNT = 3
TEST_USERS_PER_TENANT = 2
TEST_LOAD_THREADS = 5
TEST_OPERATIONS_PER_THREAD = 20

# Rate limiting for testing (relaxed limits)
RATELIMIT_STORAGE_URL = 'memory://'
RATELIMIT_DEFAULT = "1000 per minute"

# Security headers - disabled for testing
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# Custom FAB Security Manager for testing
# CUSTOM_SECURITY_MANAGER = None

# Feature flags for testing
FEATURES = {
    'ENABLE_TENANT_ISOLATION_TESTS': True,
    'ENABLE_BILLING_TESTS': True,
    'ENABLE_RESOURCE_LIMIT_TESTS': True,
    'ENABLE_PERFORMANCE_TESTS': True,
    'ENABLE_SECURITY_TESTS': True,
    'ENABLE_LOAD_TESTS': False,  # Set to True to run load tests
    'ENABLE_INTEGRATION_TESTS': True
}

# Mock external service responses for testing
MOCK_STRIPE_RESPONSES = True
MOCK_EMAIL_SERVICE = True
MOCK_S3_SERVICE = True

# Test data configuration
TEST_DATA = {
    'TENANT_SLUGS': ['testtenant1', 'testtenant2', 'enterprise-test'],
    'TENANT_NAMES': ['Test Tenant 1', 'Test Tenant 2', 'Enterprise Test'],
    'TENANT_PLANS': ['starter', 'professional', 'enterprise'],
    'ADMIN_EMAILS': ['admin1@test.com', 'admin2@test.com', 'admin3@test.com']
}