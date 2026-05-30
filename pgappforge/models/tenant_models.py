"""
Multi-Tenant SaaS Infrastructure Models.

Core data models for implementing multi-tenant SaaS capabilities in PgAppForge.
Provides complete tenant isolation, subscription management, and usage tracking.
"""

import logging
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Dict, Any, Optional, List
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Date, 
    ForeignKey, UniqueConstraint, Index, Numeric, JSON
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy_utils import JSONType

from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from pgappforge.security.sqla.models import User

log = logging.getLogger(__name__)

# Use JSONB for PostgreSQL, fallback to JSON for other databases
JSONBType = JSONB if hasattr(JSONB, '__visit_name__') else JSONType


class TenantStatus(PyEnum):
    """Tenant status enumeration"""
    ACTIVE = "active"
    SUSPENDED = "suspended" 
    CANCELLED = "cancelled"
    PENDING_VERIFICATION = "pending_verification"


class SubscriptionStatus(PyEnum):
    """Subscription status enumeration"""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    TRIALING = "trialing"
    UNPAID = "unpaid"


# Default plan features configuration
PLAN_FEATURES = {
    'free': {
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


class Tenant(AuditMixin, Model):
    """
    Core tenant model for multi-tenant SaaS infrastructure.
    
    Represents a customer organization with complete data isolation,
    subscription management, and customization capabilities.
    """
    
    __tablename__ = 'ab_tenants'
    __table_args__ = (
        Index('ix_tenants_slug', 'slug'),
        Index('ix_tenants_status', 'status'),
        Index('ix_tenants_custom_domain', 'custom_domain'),
    )

    id = Column(Integer, primary_key=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    
    # Tenant status and lifecycle
    status = Column(String(20), default=TenantStatus.ACTIVE.value)
    activated_at = Column(DateTime)
    suspended_at = Column(DateTime)
    
    # Contact and billing information
    primary_contact_email = Column(String(120), nullable=False)
    billing_email = Column(String(120))
    phone = Column(String(50))
    
    # Branding configuration
    branding_config = Column(JSONBType, default=dict)
    custom_domain = Column(String(100))
    
    # Subscription and limits
    subscription_id = Column(String(100))  # Stripe subscription ID
    plan_id = Column(String(50), default='free')
    resource_limits = Column(JSONBType, default=dict)
    
    # Relationships
    users = relationship("TenantUser", back_populates="tenant", cascade="all, delete-orphan")
    configs = relationship("TenantConfig", back_populates="tenant", cascade="all, delete-orphan")
    subscriptions = relationship("TenantSubscription", back_populates="tenant")
    usage_records = relationship("TenantUsage", back_populates="tenant")
    
    def __repr__(self):
        return f'<Tenant {self.slug}: {self.name}>'
    
    @hybrid_property
    def is_active(self):
        """Check if tenant is active"""
        return self.status == TenantStatus.ACTIVE.value
    
    @hybrid_property
    def user_count(self):
        """Get count of active users in this tenant"""
        return len([u for u in self.users if u.is_active])
    
    def can_add_user(self) -> bool:
        """Check if tenant can add another user based on limits"""
        limits = self.get_resource_limits()
        max_users = limits.get('max_users', 10)
        
        # -1 means unlimited
        if max_users == -1:
            return True
            
        return self.user_count < max_users
    
    def get_feature_flags(self) -> Dict[str, bool]:
        """Get enabled features based on subscription plan"""
        plan_features = PLAN_FEATURES.get(self.plan_id, PLAN_FEATURES['free'])
        return plan_features.get('features', {})
    
    def get_resource_limits(self) -> Dict[str, Any]:
        """Get resource limits with plan defaults"""
        plan_limits = PLAN_FEATURES.get(self.plan_id, PLAN_FEATURES['free'])['limits']
        
        # Merge plan limits with custom limits
        limits = plan_limits.copy()
        if self.resource_limits:
            limits.update(self.resource_limits)
        
        return limits
    
    def has_feature(self, feature_name: str) -> bool:
        """Check if tenant has access to a specific feature"""
        features = self.get_feature_flags()
        return features.get(feature_name, False)
    
    def is_within_limits(self, resource_type: str, proposed_usage: float) -> bool:
        """Check if proposed usage is within limits"""
        limits = self.get_resource_limits()
        limit = limits.get(resource_type)
        
        if limit is None or limit == -1:  # No limit or unlimited
            return True
        
        # Get current usage (would be calculated from usage records)
        current_usage = self._get_current_usage(resource_type)
        
        return (current_usage + proposed_usage) <= limit
    
    def _get_current_usage(self, resource_type: str) -> float:
        """Get current usage for a resource type (placeholder for now)"""
        # This would query TenantUsage records for current period
        return 0.0
    
    def suspend(self, reason: str = None):
        """Suspend tenant access"""
        self.status = TenantStatus.SUSPENDED.value
        self.suspended_at = datetime.now(tz=timezone.utc)
        
        # Log suspension
        log.info(f"Tenant {self.slug} suspended. Reason: {reason}")
    
    def activate(self):
        """Activate suspended tenant"""
        self.status = TenantStatus.ACTIVE.value
        self.activated_at = datetime.now(tz=timezone.utc)
        self.suspended_at = None
        
        log.info(f"Tenant {self.slug} activated")
    
    def get_config(self, key: str, default=None):
        """Get tenant-specific configuration value"""
        config = next((c for c in self.configs if c.config_key == key), None)
        return config.config_value if config else default
    
    def set_config(self, key: str, value: Any, category: str = None, 
                   description: str = None, is_sensitive: bool = False):
        """Set tenant-specific configuration value"""
        from pgappforge import db
        
        config = next((c for c in self.configs if c.config_key == key), None)
        
        if config:
            config.config_value = value
            config.description = description or config.description
            config.category = category or config.category
            config.is_sensitive = is_sensitive
        else:
            config = TenantConfig(
                tenant_id=self.id,
                config_key=key,
                config_value=value,
                description=description,
                category=category,
                is_sensitive=is_sensitive
            )
            db.session.add(config)
        
        db.session.commit()


class TenantUser(AuditMixin, Model):
    """
    Association model between tenants and users.
    
    Manages user membership in tenants with role-based access control
    and tenant-specific user metadata.
    """
    
    __tablename__ = 'ab_tenant_users'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'user_id', name='uq_tenant_user'),
        Index('ix_tenant_users_tenant_active', 'tenant_id', 'is_active'),
    )
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('ab_tenants.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    
    # Tenant-specific user configuration
    role_within_tenant = Column(String(50), default='member')  # admin, member, viewer
    is_active = Column(Boolean, default=True)
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)
    
    # Additional tenant-specific user metadata
    permissions_override = Column(JSONBType, default=dict)
    user_metadata = Column(JSONBType, default=dict)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    user = relationship("User")
    
    def __repr__(self):
        return f'<TenantUser {self.user_id}@{self.tenant_id} ({self.role_within_tenant})>'
    
    @property
    def is_tenant_admin(self) -> bool:
        """Check if user is admin for this tenant"""
        return self.role_within_tenant == 'admin'
    
    def can_manage_users(self) -> bool:
        """Check if user can manage other users in tenant"""
        return self.role_within_tenant in ('admin',)
    
    def can_manage_billing(self) -> bool:
        """Check if user can manage billing for tenant"""
        return self.role_within_tenant in ('admin',)
    
    def can_manage_settings(self) -> bool:
        """Check if user can manage tenant settings"""
        return self.role_within_tenant in ('admin',)


class TenantConfig(AuditMixin, Model):
    """
    Tenant-specific configuration storage.
    
    Stores key-value configuration data for tenants with categorization
    and sensitive data handling.
    """
    
    __tablename__ = 'ab_tenant_configs'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'config_key', name='uq_tenant_config'),
        Index('ix_tenant_configs_tenant_key', 'tenant_id', 'config_key'),
        Index('ix_tenant_configs_category', 'category'),
    )
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('ab_tenants.id'), nullable=False)
    
    # Configuration
    config_key = Column(String(100), nullable=False)
    config_value = Column(JSONBType, nullable=False)
    config_type = Column(String(20), default='string')  # string, json, boolean, number
    
    # Metadata
    description = Column(Text)
    is_sensitive = Column(Boolean, default=False)  # For future encryption
    category = Column(String(50))  # branding, features, integration, etc.
    
    # Relationships
    tenant = relationship("Tenant", back_populates="configs")
    
    def __repr__(self):
        return f'<TenantConfig {self.config_key} for tenant {self.tenant_id}>'
    
    @property
    def display_value(self):
        """Get display-safe value (hide sensitive configs)"""
        if self.is_sensitive:
            return "***HIDDEN***"
        return self.config_value
    
    @property
    def decrypted_value(self):
        """Get decrypted configuration value"""
        if self.is_sensitive and self.config_value:
            try:
                from ..security.config_encryption import decrypt_sensitive_value, is_value_encrypted
                
                # Check if value is actually encrypted
                if is_value_encrypted(str(self.config_value)):
                    return decrypt_sensitive_value(str(self.config_value))
                else:
                    # Value not encrypted yet (migration scenario)
                    return self.config_value
            except Exception as e:
                import logging
                log = logging.getLogger(__name__)
                log.error(f"Failed to decrypt config {self.config_key}: {e}")
                raise
        
        return self.config_value
    
    def set_sensitive_value(self, value):
        """Set a sensitive configuration value (will be encrypted)"""
        if self.is_sensitive:
            try:
                from ..security.config_encryption import encrypt_sensitive_value
                self.config_value = encrypt_sensitive_value(value)
            except Exception as e:
                import logging
                log = logging.getLogger(__name__)
                log.error(f"Failed to encrypt config {self.config_key}: {e}")
                raise
        else:
            self.config_value = value
    
    def set_value(self, value):
        """Set configuration value (encrypted if sensitive)"""
        if self.is_sensitive:
            self.set_sensitive_value(value)
        else:
            self.config_value = value
    
    def get_value(self):
        """Get configuration value (decrypted if sensitive)"""
        return self.decrypted_value
    
    @classmethod
    def get_tenant_config(cls, tenant_id: int, config_key: str, default=None):
        """Get decrypted configuration value for tenant"""
        config = cls.query.filter_by(tenant_id=tenant_id, config_key=config_key).first()
        if config:
            return config.get_value()
        return default
    
    @classmethod
    def set_tenant_config(cls, tenant_id: int, config_key: str, value, 
                         is_sensitive: bool = False, description: str = None, 
                         category: str = None, config_type: str = 'string'):
        """Set configuration value for tenant (encrypted if sensitive)"""
        from pgappforge import db
        
        config = cls.query.filter_by(tenant_id=tenant_id, config_key=config_key).first()
        if config:
            # Update existing config
            config.set_value(value)
            config.is_sensitive = is_sensitive
            if description:
                config.description = description
            if category:
                config.category = category
            config.config_type = config_type
        else:
            # Create new config
            config = cls(
                tenant_id=tenant_id,
                config_key=config_key,
                is_sensitive=is_sensitive,
                description=description,
                category=category,
                config_type=config_type
            )
            config.set_value(value)
            db.session.add(config)
        
        db.session.commit()
        return config


class TenantSubscription(AuditMixin, Model):
    """
    Tenant subscription management.
    
    Manages billing subscriptions, payment processing integration,
    and usage-based billing calculations.
    """
    
    __tablename__ = 'ab_tenant_subscriptions'
    __table_args__ = (
        Index('ix_tenant_subscriptions_tenant', 'tenant_id'),
        Index('ix_tenant_subscriptions_stripe', 'stripe_subscription_id'),
        Index('ix_tenant_subscriptions_status', 'status'),
    )
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('ab_tenants.id'), nullable=False)
    
    # Stripe integration
    stripe_subscription_id = Column(String(100), unique=True)
    stripe_customer_id = Column(String(100))
    
    # Subscription details
    plan_id = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    current_period_start = Column(DateTime)
    current_period_end = Column(DateTime)
    
    # Pricing
    monthly_amount = Column(Numeric(10, 2))
    currency = Column(String(3), default='USD')
    
    # Usage-based billing
    usage_based = Column(Boolean, default=False)
    usage_rate = Column(JSONBType)  # {'api_calls': 0.01, 'storage_gb': 0.10}
    
    # Relationships
    tenant = relationship("Tenant", back_populates="subscriptions")
    usage_records = relationship("TenantUsage", back_populates="subscription")
    
    def __repr__(self):
        return f'<TenantSubscription {self.plan_id} for tenant {self.tenant_id}>'
    
    @property
    def is_active(self) -> bool:
        """Check if subscription is active"""
        return self.status == SubscriptionStatus.ACTIVE.value
    
    @property
    def is_trial(self) -> bool:
        """Check if subscription is in trial period"""
        return self.status == SubscriptionStatus.TRIALING.value
    
    def calculate_usage_charges(self, usage_data: Dict[str, float]) -> Decimal:
        """Calculate usage-based charges for billing period"""
        if not self.usage_based or not self.usage_rate:
            return Decimal('0.00')
        
        total_charges = Decimal('0.00')
        rates = self.usage_rate
        
        for resource, usage_amount in usage_data.items():
            if resource in rates:
                rate = Decimal(str(rates[resource]))
                charge = rate * Decimal(str(usage_amount))
                total_charges += charge
        
        return total_charges.quantize(Decimal('0.01'))
    
    def get_usage_for_period(self, start_date: date, end_date: date) -> Dict[str, float]:
        """Get usage data for a specific period"""
        from sqlalchemy import func
        from pgappforge import db
        
        usage_query = db.session.query(
            TenantUsage.usage_type,
            func.sum(TenantUsage.usage_amount).label('total_usage')
        ).filter(
            TenantUsage.subscription_id == self.id,
            TenantUsage.usage_date >= start_date,
            TenantUsage.usage_date <= end_date
        ).group_by(TenantUsage.usage_type)
        
        usage_data = {}
        for usage_type, total_usage in usage_query:
            usage_data[usage_type] = float(total_usage or 0)
        
        return usage_data


class TenantUsage(AuditMixin, Model):
    """
    Tenant resource usage tracking.
    
    Tracks usage of various resources for billing, monitoring,
    and quota enforcement.
    """
    
    __tablename__ = 'ab_tenant_usage'
    __table_args__ = (
        Index('ix_tenant_usage_tenant_date', 'tenant_id', 'usage_date'),
        Index('ix_tenant_usage_subscription_date', 'subscription_id', 'usage_date'),
        Index('ix_tenant_usage_type', 'usage_type'),
    )
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('ab_tenants.id'), nullable=False)
    subscription_id = Column(Integer, ForeignKey('ab_tenant_subscriptions.id'))
    
    # Usage tracking
    usage_date = Column(Date, nullable=False, default=date.today)
    usage_type = Column(String(50), nullable=False)  # api_calls, storage, users, etc.
    usage_amount = Column(Numeric(15, 4), nullable=False)
    unit = Column(String(20), nullable=False)  # calls, gb, users, etc.
    
    # Cost calculation
    unit_cost = Column(Numeric(10, 4))
    total_cost = Column(Numeric(10, 2))
    
    # Metadata
    usage_metadata = Column(JSONBType, default=dict)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="usage_records")
    subscription = relationship("TenantSubscription", back_populates="usage_records")
    
    def __repr__(self):
        return f'<TenantUsage {self.usage_type}: {self.usage_amount} {self.unit} for tenant {self.tenant_id}>'
    
    @property
    def calculated_cost(self) -> Decimal:
        """Calculate cost if not already set"""
        if self.total_cost:
            return Decimal(str(self.total_cost))
        
        if self.unit_cost:
            return Decimal(str(self.unit_cost)) * Decimal(str(self.usage_amount))
        
        return Decimal('0.00')


class TenantAwareMixin:
    """
    Mixin to add tenant isolation to models.
    
    Automatically adds tenant_id foreign key and provides
    tenant-aware query methods for data isolation.
    """
    
    @declared_attr
    def tenant_id(cls):
        return Column(Integer, ForeignKey('ab_tenants.id'), nullable=False, index=True)
    
    @declared_attr
    def tenant(cls):
        return relationship("Tenant")
    
    @classmethod
    def for_tenant(cls, tenant_id: int):
        """Filter query for specific tenant"""
        return cls.query.filter(cls.tenant_id == tenant_id)
    
    @classmethod
    def current_tenant(cls):
        """Filter query for current tenant from context"""
        from .tenant_context import get_current_tenant_id
        
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise ValueError("No tenant context available")
        return cls.for_tenant(tenant_id)