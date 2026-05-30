# Multi-Tenant SaaS Infrastructure

## Status
Draft

## Authors
Claude Code Assistant - September 2025

## Overview
Transform Flask-AppBuilder into a comprehensive multi-tenant SaaS platform by adding tenant isolation, billing integration, usage analytics, and white-label branding capabilities. This feature enables any Flask-AppBuilder application to become a scalable SaaS business with complete tenant separation and management.

## Background/Problem Statement
Flask-AppBuilder currently operates as a single-tenant framework where all users share the same data, configuration, and branding. Modern SaaS businesses require:

**Current Limitations:**
- No tenant isolation - all data is shared across users
- Single branding and configuration for entire application
- No usage tracking or billing integration
- Cannot scale to serve multiple customer organizations
- No tenant-specific customization capabilities
- Security model doesn't support tenant boundaries

**Business Requirements:**
- Complete data isolation between tenant organizations
- Tenant-specific branding, configuration, and features
- Integrated billing and subscription management
- Usage analytics and resource limiting per tenant
- White-label capabilities for reseller partners
- Tenant onboarding and self-service management
- Multi-tier pricing with feature gating

## Goals
- **Complete Tenant Isolation**: Secure data and configuration separation between tenants
- **Integrated Billing**: Stripe/subscription management with usage-based pricing
- **Usage Analytics**: Per-tenant resource usage tracking and limits
- **White-Label Branding**: Custom logos, colors, domains per tenant
- **Tenant Management**: Self-service onboarding and administration
- **Feature Gating**: Different feature sets per subscription tier
- **Scalable Architecture**: Support thousands of tenants efficiently
- **Migration Path**: Upgrade existing single-tenant apps to multi-tenant

## Non-Goals
- Multi-database per tenant (use schema/row-level isolation instead)
- Complex tenant hierarchy (focus on flat tenant structure)
- Real-time tenant provisioning (batch provisioning acceptable)
- Advanced reseller/partner portals (basic white-labeling only)
- Cross-tenant data sharing (maintain strict isolation)

## Technical Dependencies

### External Libraries
- **Stripe >= 7.0.0**: Subscription billing and payment processing
- **SQLAlchemy >= 2.0.0**: Enhanced row-level security and schema isolation
- **Celery >= 5.3.0**: Background processing for tenant operations
- **Redis >= 4.0**: Tenant configuration caching and session management
- **Pillow >= 10.0.0**: Image processing for custom tenant branding
- **boto3 >= 1.26.0**: S3 storage for tenant assets and backups

### Internal Dependencies
- Enhanced Flask-AppBuilder security system for tenant-aware access control
- Existing mixin architecture for tenant-aware models
- Widget system for tenant-specific branding components
- Analytics infrastructure for usage tracking

## Detailed Design

### Architecture Overview
```
┌─────────────────────────────────────────────────────────────────┐
│                   Multi-Tenant SaaS Platform                    │
├─────────────────────────────────────────────────────────────────┤
│  Tenant Portal    │  Billing Engine   │  White-Label System    │
│  ┌─────────────┐  │  ┌─────────────┐  │  ┌─────────────────┐   │
│  │ Self-Service│  │  │ Stripe API  │  │  │ Custom Branding │   │
│  │ Onboarding  │  │  │ Usage Track │  │  │ Domain Mapping  │   │
│  │ Admin Portal│  │  │ Subscription│  │  │ Asset Management│   │
│  └─────────────┘  │  └─────────────┘  │  └─────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                    Tenant Isolation Layer                      │
│  ┌─────────────┐  │  ┌─────────────┐  │  ┌─────────────────┐   │
│  │ Data Filter │  │  │ Config Mgmt │  │  │ Resource Limits │   │
│  │ Row-Level   │  │  │ Tenant-aware│  │  │ Usage Metering  │   │
│  │ Security    │  │  │ Settings    │  │  │ Feature Gates   │   │
│  └─────────────┘  │  └─────────────┘  │  └─────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                  Enhanced Data Models                          │
│    Tenant │ TenantUser │ TenantConfig │ Subscription │ Usage   │
├─────────────────────────────────────────────────────────────────┤
│                   Flask-AppBuilder Foundation                  │
│    Security │ Models │ Views │ Widgets │ Analytics             │
└─────────────────────────────────────────────────────────────────┘
```

### Core Data Models

#### Tenant
```python
class Tenant(AuditMixin, Model):
    __tablename__ = 'ab_tenants'
    
    id = Column(Integer, primary_key=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    
    # Tenant status and lifecycle
    status = Column(String(20), default='active')  # active, suspended, cancelled
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    activated_at = Column(DateTime)
    suspended_at = Column(DateTime)
    
    # Contact and billing information
    primary_contact_email = Column(String(120), nullable=False)
    billing_email = Column(String(120))
    phone = Column(String(50))
    
    # Branding configuration
    branding_config = Column(JSONB, default=lambda: {})
    custom_domain = Column(String(100))
    
    # Subscription and limits
    subscription_id = Column(String(100))  # Stripe subscription ID
    plan_id = Column(String(50))
    resource_limits = Column(JSONB, default=lambda: {})
    
    # Relationships
    users = relationship("TenantUser", back_populates="tenant", cascade="all, delete-orphan")
    configs = relationship("TenantConfig", back_populates="tenant", cascade="all, delete-orphan")
    subscriptions = relationship("TenantSubscription", back_populates="tenant")
    usage_records = relationship("TenantUsage", back_populates="tenant")
    
    @hybrid_property
    def is_active(self):
        return self.status == 'active'
    
    @hybrid_property
    def user_count(self):
        return len([u for u in self.users if u.is_active])
    
    def can_add_user(self) -> bool:
        """Check if tenant can add another user based on limits"""
        limits = self.resource_limits
        max_users = limits.get('max_users', 10)  # Default limit
        return self.user_count < max_users
    
    def get_feature_flags(self) -> Dict[str, bool]:
        """Get enabled features based on subscription plan"""
        plan_features = PLAN_FEATURES.get(self.plan_id, {})
        return plan_features.get('features', {})

class TenantUser(AuditMixin, Model):
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
    
    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    user = relationship("User")
    
    def __repr__(self):
        return f'<TenantUser {self.user_id}@{self.tenant_id}>'
```

#### Subscription Management
```python
class TenantSubscription(AuditMixin, Model):
    __tablename__ = 'ab_tenant_subscriptions'
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('ab_tenants.id'), nullable=False)
    
    # Stripe integration
    stripe_subscription_id = Column(String(100), unique=True)
    stripe_customer_id = Column(String(100))
    
    # Subscription details
    plan_id = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)  # active, cancelled, past_due, etc.
    current_period_start = Column(DateTime)
    current_period_end = Column(DateTime)
    
    # Pricing
    monthly_amount = Column(Numeric(10, 2))
    currency = Column(String(3), default='USD')
    
    # Usage-based billing
    usage_based = Column(Boolean, default=False)
    usage_rate = Column(JSONB)  # {'api_calls': 0.01, 'storage_gb': 0.10}
    
    # Relationships
    tenant = relationship("Tenant", back_populates="subscriptions")
    usage_records = relationship("TenantUsage", back_populates="subscription")
    
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

class TenantUsage(AuditMixin, Model):
    __tablename__ = 'ab_tenant_usage'
    __table_args__ = (
        Index('ix_tenant_usage_tenant_date', 'tenant_id', 'usage_date'),
        Index('ix_tenant_usage_subscription_date', 'subscription_id', 'usage_date'),
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
    metadata = Column(JSONB, default=lambda: {})
    
    # Relationships
    tenant = relationship("Tenant", back_populates="usage_records")
    subscription = relationship("TenantSubscription", back_populates="usage_records")
```

#### Tenant Configuration
```python
class TenantConfig(AuditMixin, Model):
    __tablename__ = 'ab_tenant_configs'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'config_key', name='uq_tenant_config'),
        Index('ix_tenant_configs_tenant_key', 'tenant_id', 'config_key'),
    )
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('ab_tenants.id'), nullable=False)
    
    # Configuration
    config_key = Column(String(100), nullable=False)
    config_value = Column(JSONB, nullable=False)
    config_type = Column(String(20), default='string')  # string, json, boolean, number
    
    # Metadata
    description = Column(Text)
    is_sensitive = Column(Boolean, default=False)  # Encrypt sensitive configs
    category = Column(String(50))  # branding, features, integration, etc.
    
    # Relationships
    tenant = relationship("Tenant", back_populates="configs")
```

### Tenant Isolation Implementation

#### Row-Level Security Mixin
```python
class TenantAwareMixin:
    """Mixin to add tenant isolation to models"""
    
    @declared_attr
    def tenant_id(cls):
        return Column(Integer, ForeignKey('ab_tenants.id'), nullable=False)
    
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
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise ValueError("No tenant context available")
        return cls.for_tenant(tenant_id)

# Apply to existing models
class CustomerMT(TenantAwareMixin, Customer):
    """Multi-tenant version of Customer model"""
    __tablename__ = 'ab_customers_mt'

class OrderMT(TenantAwareMixin, Order):
    """Multi-tenant version of Order model"""
    __tablename__ = 'ab_orders_mt'
```

#### Tenant Context Management
```python
class TenantContext:
    """Manages current tenant context for requests"""
    
    def __init__(self):
        self._tenant_cache = {}
        self._context_stack = []
    
    def get_current_tenant(self) -> Optional[Tenant]:
        """Get current tenant from request context"""
        if hasattr(g, 'current_tenant'):
            return g.current_tenant
        
        # Try to resolve from subdomain
        tenant = self._resolve_tenant_from_request()
        if tenant:
            g.current_tenant = tenant
        
        return tenant
    
    def set_tenant_context(self, tenant: Tenant):
        """Set tenant context for current request"""
        g.current_tenant = tenant
        g.current_tenant_id = tenant.id
    
    def _resolve_tenant_from_request(self) -> Optional[Tenant]:
        """Resolve tenant from request subdomain or custom domain"""
        if not request:
            return None
        
        host = request.host
        
        # Check for custom domain first
        tenant = Tenant.query.filter_by(custom_domain=host).first()
        if tenant:
            return tenant
        
        # Check for subdomain pattern: {tenant}.yourdomain.com
        if '.' in host:
            subdomain = host.split('.')[0]
            tenant = Tenant.query.filter_by(slug=subdomain).first()
            if tenant and tenant.is_active:
                return tenant
        
        return None
    
    def require_tenant_context(self):
        """Decorator to ensure tenant context is available"""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                tenant = self.get_current_tenant()
                if not tenant:
                    return jsonify({'error': 'No tenant context'}), 400
                return f(*args, **kwargs)
            return decorated_function
        return decorator

tenant_context = TenantContext()
```

#### Data Access Layer Enhancement
```python
class TenantAwareQuery:
    """Enhanced query class with automatic tenant filtering"""
    
    def __init__(self, model_class):
        self.model_class = model_class
        self.base_query = model_class.query
    
    def filter_by_tenant(self, tenant_id: int = None):
        """Add tenant filter to query"""
        if tenant_id is None:
            tenant_id = get_current_tenant_id()
        
        if hasattr(self.model_class, 'tenant_id'):
            return self.base_query.filter(self.model_class.tenant_id == tenant_id)
        else:
            # Non-tenant-aware model, return as-is
            return self.base_query
    
    def safe_get(self, record_id: int, tenant_id: int = None):
        """Get record ensuring tenant isolation"""
        query = self.filter_by_tenant(tenant_id)
        record = query.filter(self.model_class.id == record_id).first()
        
        if not record:
            raise NotFound(f"{self.model_class.__name__} not found or access denied")
        
        return record

def get_current_tenant_id() -> Optional[int]:
    """Get current tenant ID from Flask context"""
    return getattr(g, 'current_tenant_id', None)
```

### Billing Integration

#### Stripe Integration Service
```python
class BillingService:
    def __init__(self, stripe_api_key: str):
        import stripe
        stripe.api_key = stripe_api_key
        self.stripe = stripe
    
    def create_customer(self, tenant: Tenant) -> str:
        """Create Stripe customer for tenant"""
        try:
            customer = self.stripe.Customer.create(
                email=tenant.primary_contact_email,
                name=tenant.name,
                description=f"Tenant: {tenant.slug}",
                metadata={
                    'tenant_id': tenant.id,
                    'tenant_slug': tenant.slug
                }
            )
            
            return customer.id
            
        except Exception as e:
            log.error(f"Failed to create Stripe customer for tenant {tenant.id}: {e}")
            raise
    
    def create_subscription(self, tenant: Tenant, plan_id: str, 
                          payment_method_id: str = None) -> TenantSubscription:
        """Create subscription for tenant"""
        try:
            # Get or create Stripe customer
            if not tenant.subscription_id:
                stripe_customer_id = self.create_customer(tenant)
            else:
                stripe_customer_id = tenant.subscription_id
            
            # Create subscription
            subscription_data = {
                'customer': stripe_customer_id,
                'items': [{'price': plan_id}],
                'expand': ['latest_invoice.payment_intent'],
                'metadata': {
                    'tenant_id': tenant.id,
                    'tenant_slug': tenant.slug
                }
            }
            
            if payment_method_id:
                subscription_data['default_payment_method'] = payment_method_id
            
            stripe_subscription = self.stripe.Subscription.create(**subscription_data)
            
            # Create local subscription record
            subscription = TenantSubscription(
                tenant_id=tenant.id,
                stripe_subscription_id=stripe_subscription.id,
                stripe_customer_id=stripe_customer_id,
                plan_id=plan_id,
                status=stripe_subscription.status,
                current_period_start=datetime.fromtimestamp(
                    stripe_subscription.current_period_start
                ),
                current_period_end=datetime.fromtimestamp(
                    stripe_subscription.current_period_end
                ),
                monthly_amount=stripe_subscription.items.data[0].price.unit_amount / 100
            )
            
            db.session.add(subscription)
            db.session.commit()
            
            return subscription
            
        except Exception as e:
            log.error(f"Failed to create subscription for tenant {tenant.id}: {e}")
            raise
    
    def track_usage(self, tenant_id: int, usage_type: str, 
                   amount: float, unit: str, metadata: dict = None):
        """Track usage for billing"""
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")
        
        active_subscription = TenantSubscription.query.filter_by(
            tenant_id=tenant_id,
            status='active'
        ).first()
        
        if not active_subscription:
            log.warning(f"No active subscription for tenant {tenant_id} usage tracking")
            return
        
        # Calculate cost if usage-based pricing
        unit_cost = None
        total_cost = None
        
        if active_subscription.usage_based and active_subscription.usage_rate:
            rates = active_subscription.usage_rate
            if usage_type in rates:
                unit_cost = Decimal(str(rates[usage_type]))
                total_cost = unit_cost * Decimal(str(amount))
        
        # Record usage
        usage_record = TenantUsage(
            tenant_id=tenant_id,
            subscription_id=active_subscription.id,
            usage_type=usage_type,
            usage_amount=amount,
            unit=unit,
            unit_cost=unit_cost,
            total_cost=total_cost,
            metadata=metadata or {}
        )
        
        db.session.add(usage_record)
        db.session.commit()
        
        # Check usage limits
        self._check_usage_limits(tenant, usage_type, amount)
    
    def _check_usage_limits(self, tenant: Tenant, usage_type: str, new_usage: float):
        """Check if tenant is approaching or exceeding usage limits"""
        limits = tenant.resource_limits
        if usage_type not in limits:
            return
        
        limit = limits[usage_type]
        
        # Get current period usage
        today = date.today()
        start_of_month = today.replace(day=1)
        
        current_usage = db.session.query(
            func.sum(TenantUsage.usage_amount)
        ).filter(
            TenantUsage.tenant_id == tenant.id,
            TenantUsage.usage_type == usage_type,
            TenantUsage.usage_date >= start_of_month
        ).scalar() or 0
        
        current_usage += new_usage
        
        # Check for limit violations
        if current_usage > limit:
            self._handle_usage_limit_exceeded(tenant, usage_type, current_usage, limit)
        elif current_usage > (limit * 0.8):  # 80% threshold warning
            self._send_usage_warning(tenant, usage_type, current_usage, limit)
```

### White-Label Branding System

#### Branding Configuration
```python
class BrandingManager:
    def __init__(self, storage_backend='s3'):
        self.storage = self._init_storage(storage_backend)
    
    def update_tenant_branding(self, tenant: Tenant, branding_data: dict):
        """Update tenant branding configuration"""
        current_config = tenant.branding_config or {}
        
        # Handle logo upload
        if 'logo' in branding_data:
            logo_url = self._upload_logo(tenant, branding_data['logo'])
            current_config['logo_url'] = logo_url
        
        # Handle color scheme
        if 'colors' in branding_data:
            colors = branding_data['colors']
            self._validate_color_scheme(colors)
            current_config['colors'] = colors
        
        # Handle custom CSS
        if 'custom_css' in branding_data:
            css_url = self._upload_custom_css(tenant, branding_data['custom_css'])
            current_config['custom_css_url'] = css_url
        
        # Update other branding options
        for key in ['app_name', 'tagline', 'favicon_url', 'email_footer']:
            if key in branding_data:
                current_config[key] = branding_data[key]
        
        tenant.branding_config = current_config
        db.session.commit()
        
        # Clear cached branding
        self._clear_branding_cache(tenant.id)
    
    def get_tenant_branding(self, tenant_id: int) -> dict:
        """Get tenant branding with caching"""
        cache_key = f"tenant_branding:{tenant_id}"
        cached = redis_client.get(cache_key)
        
        if cached:
            return json.loads(cached)
        
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            return self._get_default_branding()
        
        branding = tenant.branding_config or {}
        
        # Add computed values
        branding.update({
            'app_name': branding.get('app_name', tenant.name),
            'primary_color': branding.get('colors', {}).get('primary', '#007bff'),
            'logo_url': branding.get('logo_url', '/static/img/default-logo.png'),
            'custom_domain': tenant.custom_domain
        })
        
        # Cache for 1 hour
        redis_client.setex(cache_key, 3600, json.dumps(branding))
        
        return branding
    
    def _upload_logo(self, tenant: Tenant, logo_file) -> str:
        """Upload and process tenant logo"""
        from PIL import Image
        
        # Process image
        image = Image.open(logo_file)
        
        # Resize if too large
        max_size = (400, 200)
        if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Convert to RGB if necessary
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGB')
        
        # Save to storage
        filename = f"tenant-{tenant.id}/logo.png"
        
        # Upload to S3 or local storage
        logo_url = self.storage.upload_image(filename, image)
        
        return logo_url
    
    def generate_tenant_css(self, tenant_id: int) -> str:
        """Generate CSS for tenant branding"""
        branding = self.get_tenant_branding(tenant_id)
        colors = branding.get('colors', {})
        
        css_template = """
        :root {
            --primary-color: %(primary)s;
            --secondary-color: %(secondary)s;
            --accent-color: %(accent)s;
            --navbar-bg: %(navbar_bg)s;
            --sidebar-bg: %(sidebar_bg)s;
        }
        
        .navbar-brand img {
            max-height: 40px;
            width: auto;
        }
        
        .btn-primary {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
        }
        
        .sidebar {
            background-color: var(--sidebar-bg);
        }
        
        .navbar {
            background-color: var(--navbar-bg) !important;
        }
        """
        
        css_values = {
            'primary': colors.get('primary', '#007bff'),
            'secondary': colors.get('secondary', '#6c757d'),
            'accent': colors.get('accent', '#28a745'),
            'navbar_bg': colors.get('navbar_bg', '#343a40'),
            'sidebar_bg': colors.get('sidebar_bg', '#f8f9fa')
        }
        
        return css_template % css_values
```

### Tenant Management Portal

#### Self-Service Onboarding
```python
class TenantOnboardingView(BaseView):
    route_base = "/onboarding"
    
    @expose("/")
    def index(self):
        """Landing page for new tenant signup"""
        plans = self._get_available_plans()
        return self.render_template(
            'appbuilder/tenant/onboarding_start.html',
            plans=plans
        )
    
    @expose("/signup", methods=['GET', 'POST'])
    def signup(self):
        """Tenant signup form"""
        if request.method == 'POST':
            return self._process_signup()
        
        return self.render_template('appbuilder/tenant/signup_form.html')
    
    def _process_signup(self):
        """Process new tenant signup"""
        try:
            data = request.get_json()
            
            # Validate input
            errors = self._validate_signup_data(data)
            if errors:
                return jsonify({'errors': errors}), 400
            
            # Check if slug is available
            existing_tenant = Tenant.query.filter_by(slug=data['slug']).first()
            if existing_tenant:
                return jsonify({'errors': {'slug': 'This subdomain is already taken'}}), 400
            
            # Create tenant
            tenant = Tenant(
                slug=data['slug'],
                name=data['company_name'],
                primary_contact_email=data['email'],
                plan_id=data['plan_id'],
                status='pending_verification'
            )
            
            db.session.add(tenant)
            db.session.commit()
            
            # Create admin user for tenant
            admin_user = self._create_tenant_admin(tenant, data)
            
            # Send verification email
            self._send_verification_email(tenant, admin_user)
            
            # Set up subscription (if paid plan)
            if data['plan_id'] != 'free':
                subscription = billing_service.create_subscription(
                    tenant, 
                    data['plan_id'],
                    data.get('payment_method_id')
                )
            
            return jsonify({
                'success': True,
                'tenant_id': tenant.id,
                'message': 'Please check your email to verify your account'
            })
            
        except Exception as e:
            log.error(f"Signup failed: {e}")
            db.session.rollback()
            return jsonify({'error': 'Signup failed. Please try again.'}), 500
    
    def _create_tenant_admin(self, tenant: Tenant, signup_data: dict):
        """Create admin user for new tenant"""
        # Create user in main user table
        user = User(
            first_name=signup_data['first_name'],
            last_name=signup_data['last_name'],
            username=signup_data['email'],
            email=signup_data['email'],
            active=False  # Will be activated on email verification
        )
        
        user.password = generate_password_hash(signup_data['password'])
        db.session.add(user)
        db.session.flush()  # Get user ID
        
        # Link user to tenant with admin role
        tenant_user = TenantUser(
            tenant_id=tenant.id,
            user_id=user.id,
            role_within_tenant='admin',
            is_active=True
        )
        
        db.session.add(tenant_user)
        db.session.commit()
        
        return user

class TenantAdminView(BaseView):
    route_base = "/tenant/admin"
    
    @expose("/")
    @has_access
    @tenant_context.require_tenant_context()
    def dashboard(self):
        """Tenant admin dashboard"""
        tenant = tenant_context.get_current_tenant()
        
        # Get usage statistics
        usage_stats = self._get_usage_statistics(tenant)
        
        # Get subscription info
        subscription = TenantSubscription.query.filter_by(
            tenant_id=tenant.id,
            status='active'
        ).first()
        
        return self.render_template(
            'appbuilder/tenant/admin_dashboard.html',
            tenant=tenant,
            usage_stats=usage_stats,
            subscription=subscription
        )
    
    @expose("/users")
    @has_access
    @tenant_context.require_tenant_context()
    def manage_users(self):
        """Manage tenant users"""
        tenant = tenant_context.get_current_tenant()
        
        tenant_users = TenantUser.query.filter_by(
            tenant_id=tenant.id,
            is_active=True
        ).join(User).all()
        
        return self.render_template(
            'appbuilder/tenant/user_management.html',
            tenant=tenant,
            users=tenant_users,
            can_add_users=tenant.can_add_user()
        )
    
    @expose("/billing")
    @has_access
    @tenant_context.require_tenant_context()
    def billing_portal(self):
        """Tenant billing and subscription management"""
        tenant = tenant_context.get_current_tenant()
        
        # Get billing history
        usage_records = TenantUsage.query.filter_by(
            tenant_id=tenant.id
        ).order_by(TenantUsage.usage_date.desc()).limit(100).all()
        
        # Get subscription details
        subscription = TenantSubscription.query.filter_by(
            tenant_id=tenant.id,
            status='active'
        ).first()
        
        return self.render_template(
            'appbuilder/tenant/billing_portal.html',
            tenant=tenant,
            subscription=subscription,
            usage_records=usage_records
        )
```

## User Experience

### Tenant Onboarding Flow
1. **Plan Selection**: Choose subscription plan with feature comparison
2. **Company Setup**: Enter company details and choose subdomain
3. **Admin Account**: Create initial admin user account
4. **Payment Setup**: Add payment method for paid plans
5. **Email Verification**: Verify email and activate account
6. **Initial Configuration**: Set up basic branding and preferences

### Tenant Admin Portal
1. **Dashboard Overview**: Usage metrics, billing info, and system status
2. **User Management**: Invite/remove users, manage roles and permissions
3. **Billing & Usage**: View invoices, update payment methods, monitor usage
4. **Branding Setup**: Upload logo, set colors, configure custom domain
5. **Settings**: Configure tenant-specific features and integrations

### End User Experience
1. **Branded Login**: Users see tenant-specific branding on login
2. **Custom Domain**: Access via custom domain (e.g., client.company.com)
3. **Tenant-Isolated Data**: Only see data belonging to their organization
4. **Feature Access**: Features available based on subscription plan
5. **Seamless Experience**: No indication of multi-tenancy to end users

## Testing Strategy

### Unit Tests
```python
class TestTenantIsolation(unittest.TestCase):
    """Test tenant data isolation"""
    
    def test_tenant_aware_queries(self):
        """Verify queries automatically filter by tenant"""
        # Purpose: Ensures no data leakage between tenants
        tenant1 = create_test_tenant('tenant1')
        tenant2 = create_test_tenant('tenant2')
        
        # Create data for each tenant
        with tenant_context.set_tenant_context(tenant1):
            customer1 = CustomerMT(name='Customer 1', tenant_id=tenant1.id)
            db.session.add(customer1)
        
        with tenant_context.set_tenant_context(tenant2):
            customer2 = CustomerMT(name='Customer 2', tenant_id=tenant2.id)
            db.session.add(customer2)
        
        db.session.commit()
        
        # Test tenant 1 can only see their data
        with tenant_context.set_tenant_context(tenant1):
            customers = CustomerMT.current_tenant().all()
            self.assertEqual(len(customers), 1)
            self.assertEqual(customers[0].name, 'Customer 1')
        
        # Test tenant 2 can only see their data
        with tenant_context.set_tenant_context(tenant2):
            customers = CustomerMT.current_tenant().all()
            self.assertEqual(len(customers), 1)
            self.assertEqual(customers[0].name, 'Customer 2')
        # This test can fail if tenant isolation is broken
    
    def test_usage_tracking_accuracy(self):
        """Test usage tracking and billing calculations"""
        # Purpose: Ensures billing calculations are accurate
        tenant = create_test_tenant('test-billing')
        
        billing_service = BillingService('test_key')
        
        # Track some usage
        billing_service.track_usage(
            tenant_id=tenant.id,
            usage_type='api_calls',
            amount=1000,
            unit='calls'
        )
        
        billing_service.track_usage(
            tenant_id=tenant.id,
            usage_type='storage',
            amount=2.5,
            unit='gb'
        )
        
        # Verify usage records
        usage_records = TenantUsage.query.filter_by(tenant_id=tenant.id).all()
        self.assertEqual(len(usage_records), 2)
        
        api_usage = next(r for r in usage_records if r.usage_type == 'api_calls')
        self.assertEqual(api_usage.usage_amount, 1000)
        # This test can fail if usage tracking has calculation errors
```

### Integration Tests
```python
class TestTenantOnboarding(FABTestCase):
    """Test complete tenant onboarding process"""
    
    def test_signup_and_activation_flow(self):
        """Test complete tenant signup and activation"""
        # Purpose: Ensures onboarding process works end-to-end
        with self.app.test_client() as client:
            
            # Signup request
            signup_data = {
                'slug': 'testcompany',
                'company_name': 'Test Company',
                'email': 'admin@testcompany.com',
                'first_name': 'John',
                'last_name': 'Admin',
                'password': 'securepassword123',
                'plan_id': 'starter'
            }
            
            response = client.post('/onboarding/signup', json=signup_data)
            self.assertEqual(response.status_code, 200)
            
            # Verify tenant was created
            tenant = Tenant.query.filter_by(slug='testcompany').first()
            self.assertIsNotNone(tenant)
            self.assertEqual(tenant.status, 'pending_verification')
            
            # Verify admin user was created
            tenant_user = TenantUser.query.filter_by(
                tenant_id=tenant.id,
                role_within_tenant='admin'
            ).first()
            self.assertIsNotNone(tenant_user)
            # This test can fail if onboarding workflow has issues
            
    def test_subdomain_routing(self):
        """Test tenant resolution from subdomain"""
        # Purpose: Ensures tenants are correctly identified from subdomains
        tenant = create_test_tenant('routing-test')
        
        with self.app.test_client() as client:
            # Mock request with subdomain
            with client.application.test_request_context('/', 
                base_url='http://routing-test.yourdomain.com'):
                
                resolved_tenant = tenant_context._resolve_tenant_from_request()
                self.assertEqual(resolved_tenant.id, tenant.id)
        # This test can fail if subdomain resolution is broken
```

### E2E Tests  
```python
class TestMultiTenantApplication(SeleniumTestCase):
    """End-to-end multi-tenant functionality tests"""
    
    def test_tenant_branding_isolation(self):
        """Test that tenants see their own branding"""
        # Purpose: Ensures branding isolation works visually
        tenant1 = create_test_tenant_with_branding('branded1', {
            'colors': {'primary': '#ff0000'},
            'app_name': 'Branded App 1'
        })
        tenant2 = create_test_tenant_with_branding('branded2', {
            'colors': {'primary': '#00ff00'},
            'app_name': 'Branded App 2'
        })
        
        driver = self.driver
        
        # Visit tenant 1
        driver.get('http://branded1.localhost:5000/login')
        
        # Check primary color
        primary_color = driver.execute_script(
            "return getComputedStyle(document.querySelector('.btn-primary')).backgroundColor"
        )
        self.assertIn('rgb(255, 0, 0)', primary_color)  # Red
        
        # Check app name
        app_name = driver.find_element(By.CLASS_NAME, 'navbar-brand').text
        self.assertEqual(app_name, 'Branded App 1')
        
        # Visit tenant 2  
        driver.get('http://branded2.localhost:5000/login')
        
        # Check different primary color
        primary_color = driver.execute_script(
            "return getComputedStyle(document.querySelector('.btn-primary')).backgroundColor"
        )
        self.assertIn('rgb(0, 255, 0)', primary_color)  # Green
        
        # Check different app name
        app_name = driver.find_element(By.CLASS_NAME, 'navbar-brand').text
        self.assertEqual(app_name, 'Branded App 2')
        # This test can fail if branding isolation breaks
```

## Performance Considerations

### Database Performance
- **Tenant ID Indexing**: Comprehensive indexing on tenant_id columns
- **Query Optimization**: Automatic tenant filters to prevent cross-tenant queries
- **Connection Pooling**: Separate connection pools for tenant operations
- **Partitioning**: Table partitioning by tenant_id for large datasets

### Caching Strategies
- **Tenant Configuration Caching**: Cache branding and settings per tenant
- **User Context Caching**: Cache tenant membership and permissions
- **Query Result Caching**: Tenant-aware cache keys for data caching
- **Static Asset Caching**: CDN caching for tenant-specific assets

### Resource Isolation
- **Memory Limits**: Per-tenant memory usage monitoring and limits
- **CPU Throttling**: Rate limiting for resource-intensive operations
- **Storage Quotas**: Enforce storage limits per tenant subscription
- **Background Job Isolation**: Separate queues for tenant operations

### Scalability Approaches
- **Horizontal Scaling**: Distribute tenants across multiple application instances
- **Database Scaling**: Read replicas and sharding strategies for large tenant bases
- **Asset Distribution**: CDN for tenant-specific branding assets
- **Microservice Architecture**: Separate services for billing, usage tracking

## Security Considerations

### Data Isolation Security
- **Row-Level Security**: Database-level tenant isolation enforcement
- **Query Validation**: Prevent cross-tenant data access through SQL injection
- **API Endpoint Security**: Tenant context validation on all endpoints
- **File Upload Security**: Tenant-isolated file storage and access

### Authentication & Authorization
- **Tenant-Aware Authentication**: Users belong to specific tenants
- **Role Isolation**: Roles and permissions scoped to tenants
- **Session Management**: Tenant context in user sessions
- **API Key Management**: Tenant-specific API keys and rate limits

### Billing & Usage Security
- **Payment Data Security**: PCI compliance for payment processing
- **Usage Data Integrity**: Tamper-proof usage tracking
- **Subscription Validation**: Prevent unauthorized feature access
- **Audit Logging**: Complete audit trail of billing operations

### Infrastructure Security
- **Subdomain Security**: Prevent subdomain hijacking and spoofing
- **Custom Domain Verification**: Domain ownership validation
- **SSL/TLS**: Automatic SSL for custom domains
- **DDoS Protection**: Per-tenant rate limiting and protection

## Documentation

### Tenant Documentation
- **Onboarding Guide**: Step-by-step tenant setup process
- **Admin Portal Manual**: Managing users, billing, and settings
- **Branding Customization**: Logo upload, color schemes, custom domains
- **Billing & Usage Guide**: Understanding charges and usage tracking

### Developer Documentation
- **Multi-Tenant Development Guide**: Building tenant-aware features
- **Database Schema**: Complete multi-tenant data model documentation
- **API Reference**: Tenant-aware API endpoints and authentication
- **Migration Guide**: Converting single-tenant apps to multi-tenant

### Operations Documentation
- **Deployment Guide**: Setting up multi-tenant infrastructure
- **Monitoring & Alerting**: Tenant-specific monitoring and alerts
- **Backup & Recovery**: Multi-tenant data backup strategies
- **Performance Tuning**: Optimizing for large numbers of tenants

## Implementation Phases

### Phase 1: Core Multi-Tenancy Foundation
**Data Model & Isolation**
- Core tenant data models (Tenant, TenantUser, TenantConfig)
- TenantAwareMixin for model isolation
- Tenant context management and middleware
- Basic subdomain routing and tenant resolution
- Row-level security implementation
- Migration tools for existing single-tenant data

**Success Criteria:**
- Complete data isolation between tenants
- Subdomain routing working correctly
- Existing apps can be converted to multi-tenant
- No cross-tenant data leakage possible

### Phase 2: Subscription & Billing
**Stripe Integration & Usage Tracking**
- Subscription management models and APIs
- Stripe integration for payment processing
- Usage tracking and metering system
- Tenant onboarding and signup flow
- Basic tenant admin portal
- Plan-based feature gating

**Success Criteria:**
- Tenants can sign up and subscribe to plans
- Usage tracking is accurate and tamper-proof
- Billing calculations work correctly
- Feature access is properly controlled by plan

### Phase 3: Branding & Enterprise Features
**White-Label & Advanced Features**
- Complete branding system with asset management
- Custom domain support with SSL
- Advanced tenant admin features
- Usage analytics and reporting
- Enterprise security features
- Performance optimizations for scale

**Success Criteria:**
- Tenants can fully customize branding and domains
- Platform scales to hundreds of tenants
- Enterprise security requirements met
- Performance remains acceptable under load

## Open Questions

1. **Database Architecture**: Should we use schema-per-tenant or row-level security for isolation?
2. **Billing Complexity**: How complex should usage-based billing be (per-feature, per-API call, per-user)?
3. **Tenant Limits**: What are reasonable default limits for users, storage, API calls per tenant?
4. **Migration Strategy**: How do we migrate existing single-tenant applications with minimal downtime?
5. **Custom Domains**: Should we require DNS configuration or provide automatic subdomain SSL?
6. **Data Residency**: Should we support geographic data residency requirements?
7. **Tenant Analytics**: How much cross-tenant analytics should be available to platform administrators?

## References

### Multi-Tenancy Patterns
- [Multi-Tenant Data Architecture](https://docs.microsoft.com/en-us/azure/architecture/guide/multitenant/approaches/data-architecture) - Data isolation strategies
- [SaaS Tenant Isolation](https://aws.amazon.com/solutions/implementations/saas-tenant-isolation/) - AWS tenant isolation patterns
- [Row-Level Security in PostgreSQL](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) - Database-level isolation

### Billing & Subscriptions  
- [Stripe Subscriptions API](https://stripe.com/docs/api/subscriptions) - Subscription management
- [Usage-Based Billing Patterns](https://stripe.com/docs/billing/subscriptions/usage-based) - Metered billing implementation
- [SaaS Metrics Best Practices](https://www.salesforce.com/resources/articles/saas-metrics/) - Key SaaS business metrics

### Flask-AppBuilder Integration
- [Security System](../flask_appbuilder/security/) - Current security implementation to extend
- [Mixin Architecture](../flask_appbuilder/mixins/) - Reusable component patterns
- [Model Base Classes](../flask_appbuilder/models/) - Foundation for tenant-aware models
- [View System](../flask_appbuilder/views/) - View patterns for tenant admin interfaces