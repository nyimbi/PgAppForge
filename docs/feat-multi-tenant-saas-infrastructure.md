# PgAppForge: Multi-Tenant SaaS Enhancements

## Status
Draft

## Authors
Claude Code Assistant - September 2025

## Overview
Four focused enhancements that extend PgAppForge's existing MultiTenancyMixin to provide basic SaaS capabilities by building on current tenant isolation, security patterns, and existing infrastructure.

## Features

### F1: Tenant Management View (1 week)
Create a management interface for tenant administration using existing ModelView patterns.

#### Technical Implementation
```python
from pgappforge.views import ModelView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.mixins.fab_integration import MultiTenancyMixin
from sqlalchemy import Column, String, Boolean, DateTime

class Tenant(AuditMixin, Model):
    """Tenant model using existing AuditMixin patterns"""
    
    __tablename__ = 'ab_tenants'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    domain = Column(String(100), unique=True, nullable=False)
    subdomain = Column(String(50), unique=True, nullable=False)
    status = Column(String(20), default='active')  # active, suspended, trial
    plan_type = Column(String(50), default='basic')  # basic, pro, enterprise
    max_users = Column(Integer, default=10)
    
    # Configuration settings (JSON)
    settings = Column(JSONB, default=lambda: {})

class TenantModelView(ModelView):
    """Tenant management using existing ModelView patterns"""
    
    datamodel = SQLAInterface(Tenant)
    
    # Use existing ModelView features
    list_columns = ['name', 'domain', 'subdomain', 'status', 'plan_type', 'created_on']
    edit_columns = ['name', 'domain', 'subdomain', 'status', 'plan_type', 'max_users', 'settings']
    add_columns = ['name', 'domain', 'subdomain', 'plan_type', 'max_users']
    
    # Use existing security patterns
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']
    
    @expose('/switch_tenant/<int:tenant_id>')
    @has_access
    @permission_name('tenant_switch')
    def switch_tenant(self, tenant_id):
        """Switch current user to different tenant"""
        
        # Validate user has access to this tenant
        tenant = self.datamodel.get(tenant_id)
        if not tenant or not self._can_access_tenant(tenant):
            flash('Access denied to this tenant', 'error')
            return redirect(self.get_redirect())
        
        # Set tenant in session using existing Flask patterns
        session['current_tenant_id'] = tenant_id
        session['current_tenant_name'] = tenant.name
        
        # Update PgAppForge global context
        from flask import g
        g.tenant_id = tenant_id
        
        flash(f'Switched to tenant: {tenant.name}', 'success')
        return redirect(url_for('IndexView.index'))
    
    def _can_access_tenant(self, tenant):
        """Check if current user can access tenant using existing security"""
        from flask_login import current_user
        
        # Super admin can access any tenant
        if current_user.has_role('Admin'):
            return True
        
        # Check if user belongs to this tenant
        return hasattr(current_user, 'tenant_id') and current_user.tenant_id == tenant.id

class TenantUserModelView(ModelView):
    """Manage users within tenants using existing User model"""
    
    datamodel = SQLAInterface(User)
    
    # Filter users by current tenant using existing patterns
    def get_query(self):
        """Override query to show only tenant users"""
        query = super().get_query()
        
        # Use existing MultiTenancyMixin patterns
        current_tenant = self._get_current_tenant()
        if current_tenant:
            query = query.filter(User.tenant_id == current_tenant)
        
        return query
    
    def _get_current_tenant(self):
        """Get current tenant using existing patterns"""
        from flask import g, session
        return getattr(g, 'tenant_id', None) or session.get('current_tenant_id')
```

#### Dependencies
- Existing PgAppForge ModelView system
- Existing AuditMixin for audit trails
- Existing MultiTenancyMixin for tenant isolation
- Current Flask session management

#### Testing
```python
class TestTenantManagement(FABTestCase):
    def test_tenant_creation(self):
        self.login_user('admin')
        tenant_data = {
            'name': 'Test Tenant',
            'domain': 'test.example.com',
            'subdomain': 'test'
        }
        response = self.client.post('/tenantmodelview/add', data=tenant_data)
        self.assertEqual(response.status_code, 302)
        
    def test_tenant_switching(self):
        self.login_user('admin')
        response = self.client.get('/tenantmodelview/switch_tenant/1')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(session['current_tenant_id'], 1)
```

### F2: Subdomain Routing (1 week)
Simple subdomain detection that integrates with existing MultiTenancyMixin.

#### Technical Implementation
```python
from flask import request, g, session, current_app, abort

class TenantMiddleware:
    """Middleware for tenant detection using subdomains"""
    
    def __init__(self, app):
        self.app = app
        self.app.before_request(self.load_tenant_context)
    
    def load_tenant_context(self):
        """Load tenant context before each request"""
        
        # Skip for static files and admin endpoints
        if request.endpoint in ['static', 'admin.static']:
            return
        
        # Extract subdomain from request
        subdomain = self._extract_subdomain(request.host)
        
        if subdomain:
            tenant = self._get_tenant_by_subdomain(subdomain)
            if tenant:
                # Set tenant context for MultiTenancyMixin
                g.tenant_id = tenant.id
                g.tenant = tenant
                
                # Also set in session for consistency
                session['current_tenant_id'] = tenant.id
                session['current_tenant_name'] = tenant.name
            else:
                # Unknown subdomain
                abort(404, 'Tenant not found')
        else:
            # Main domain - could be admin or multi-tenant selector
            g.tenant_id = None
            g.tenant = None
    
    def _extract_subdomain(self, host):
        """Extract subdomain from host header"""
        
        # Get base domain from config
        base_domain = current_app.config.get('BASE_DOMAIN', 'localhost')
        
        if host == base_domain or host.startswith('www.'):
            return None
        
        # Extract subdomain
        if host.endswith(f'.{base_domain}'):
            subdomain = host.replace(f'.{base_domain}', '')
            return subdomain.split('.')[0]  # Get first part if multiple subdomains
        
        return None
    
    def _get_tenant_by_subdomain(self, subdomain):
        """Get tenant by subdomain using existing database patterns"""
        
        # Use existing PgAppForge database session
        from pgappforge import db
        
        return db.session.query(Tenant).filter(
            Tenant.subdomain == subdomain,
            Tenant.status == 'active'
        ).first()

# Integration with existing PgAppForge initialization
def create_app():
    """App factory with tenant middleware"""
    
    app = Flask(__name__)
    
    # Initialize PgAppForge as usual
    from pgappforge import AppBuilder
    appbuilder = AppBuilder(app, db.session)
    
    # Add tenant middleware
    TenantMiddleware(app)
    
    return app

# Tenant-aware URL generation
def tenant_url_for(endpoint, **values):
    """Generate URLs with tenant subdomain"""
    
    from flask import url_for, g
    
    if hasattr(g, 'tenant') and g.tenant:
        # Generate URL with tenant subdomain
        url = url_for(endpoint, **values, _external=True)
        
        # Replace host with tenant subdomain
        base_domain = current_app.config.get('BASE_DOMAIN', 'localhost')
        tenant_host = f"{g.tenant.subdomain}.{base_domain}"
        
        return url.replace(request.host, tenant_host)
    
    return url_for(endpoint, **values)
```

#### Dependencies
- Existing Flask request handling
- Existing MultiTenancyMixin context (uses g.tenant_id)
- Flask session management
- DNS configuration for wildcard subdomains

#### Testing
```python
class TestSubdomainRouting(FABTestCase):
    def test_subdomain_detection(self):
        with self.app.test_client() as client:
            # Test main domain
            response = client.get('/', base_url='http://localhost')
            self.assertIsNone(g.get('tenant_id'))
            
            # Test tenant subdomain
            response = client.get('/', base_url='http://test.localhost')
            self.assertEqual(g.tenant_id, 1)
    
    def test_unknown_subdomain(self):
        with self.app.test_client() as client:
            response = client.get('/', base_url='http://unknown.localhost')
            self.assertEqual(response.status_code, 404)
```

### F3: Tenant Configuration (1 week)
Configuration interface for tenant-specific settings using existing form patterns.

#### Technical Implementation
```python
from pgappforge.views import SimpleFormView
from wtforms import StringField, SelectField, IntegerField, BooleanField
from wtforms.validators import DataRequired, URL, Email

class TenantConfigurationForm(DynamicForm):
    """Form for tenant-specific configuration"""
    
    # Branding settings
    company_name = StringField('Company Name', validators=[DataRequired()])
    logo_url = StringField('Logo URL', validators=[URL()])
    primary_color = StringField(
        'Primary Color', 
        default='#007bff',
        description='Hex color code for primary theme color'
    )
    
    # Contact settings
    support_email = StringField('Support Email', validators=[Email()])
    contact_phone = StringField('Contact Phone')
    timezone = SelectField(
        'Timezone',
        choices=[
            ('UTC', 'UTC'),
            ('US/Eastern', 'Eastern Time'),
            ('US/Central', 'Central Time'),
            ('US/Pacific', 'Pacific Time'),
            ('Europe/London', 'London'),
            ('Europe/Paris', 'Paris'),
        ]
    )
    
    # Feature toggles
    enable_collaboration = BooleanField('Enable Collaboration Features')
    enable_advanced_analytics = BooleanField('Enable Advanced Analytics')
    max_storage_gb = IntegerField('Max Storage (GB)', default=10)
    
    # Notification settings
    email_notifications = BooleanField('Email Notifications', default=True)
    slack_webhook_url = StringField('Slack Webhook URL', validators=[URL()])

class TenantConfigurationView(SimpleFormView):
    """Tenant configuration using existing SimpleFormView"""
    
    route_base = '/tenant-config'
    form = TenantConfigurationForm
    
    @expose('/settings', methods=['GET', 'POST'])
    @has_access
    def configure_tenant(self):
        """Configure tenant settings using existing form patterns"""
        
        # Get current tenant using existing patterns
        tenant = self._get_current_tenant()
        if not tenant:
            flash('No active tenant found', 'error')
            return redirect(url_for('IndexView.index'))
        
        form = self.form.refresh()
        
        # Load existing settings into form
        if request.method == 'GET':
            self._populate_form_from_tenant(form, tenant)
        
        if form.validate_on_submit():
            # Save configuration using existing patterns
            config = {
                'branding': {
                    'company_name': form.company_name.data,
                    'logo_url': form.logo_url.data,
                    'primary_color': form.primary_color.data
                },
                'contact': {
                    'support_email': form.support_email.data,
                    'contact_phone': form.contact_phone.data,
                    'timezone': form.timezone.data
                },
                'features': {
                    'enable_collaboration': form.enable_collaboration.data,
                    'enable_advanced_analytics': form.enable_advanced_analytics.data,
                    'max_storage_gb': form.max_storage_gb.data
                },
                'notifications': {
                    'email_notifications': form.email_notifications.data,
                    'slack_webhook_url': form.slack_webhook_url.data
                }
            }
            
            self._save_tenant_config(tenant, config)
            flash('Tenant configuration saved successfully', 'success')
            return redirect(url_for('TenantConfigurationView.configure_tenant'))
        
        return self.render_template(
            'tenant/configuration.html',
            form=form,
            tenant=tenant
        )
    
    def _get_current_tenant(self):
        """Get current tenant using existing patterns"""
        from flask import g, session
        
        tenant_id = getattr(g, 'tenant_id', None) or session.get('current_tenant_id')
        if tenant_id:
            return db.session.query(Tenant).get(tenant_id)
        return None
    
    def _populate_form_from_tenant(self, form, tenant):
        """Populate form with existing tenant settings"""
        settings = tenant.settings or {}
        
        # Populate branding settings
        branding = settings.get('branding', {})
        form.company_name.data = branding.get('company_name', tenant.name)
        form.logo_url.data = branding.get('logo_url', '')
        form.primary_color.data = branding.get('primary_color', '#007bff')
        
        # Populate other settings
        contact = settings.get('contact', {})
        form.support_email.data = contact.get('support_email', '')
        form.contact_phone.data = contact.get('contact_phone', '')
        form.timezone.data = contact.get('timezone', 'UTC')
        
        features = settings.get('features', {})
        form.enable_collaboration.data = features.get('enable_collaboration', False)
        form.enable_advanced_analytics.data = features.get('enable_advanced_analytics', False)
        form.max_storage_gb.data = features.get('max_storage_gb', 10)
    
    def _save_tenant_config(self, tenant, config):
        """Save tenant configuration using existing database patterns"""
        tenant.settings = config
        db.session.commit()

# Helper functions for using tenant configuration
class TenantConfigHelper:
    """Helper for accessing tenant configuration in templates and views"""
    
    @staticmethod
    def get_tenant_config(key_path, default=None):
        """Get tenant configuration value by dot-notation path"""
        from flask import g
        
        if not hasattr(g, 'tenant') or not g.tenant:
            return default
        
        settings = g.tenant.settings or {}
        
        # Navigate nested dictionary using dot notation
        keys = key_path.split('.')
        value = settings
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    @staticmethod
    def get_branding_color():
        """Get tenant primary color for theming"""
        return TenantConfigHelper.get_tenant_config('branding.primary_color', '#007bff')
    
    @staticmethod
    def get_company_name():
        """Get tenant company name"""
        from flask import g
        if hasattr(g, 'tenant') and g.tenant:
            return TenantConfigHelper.get_tenant_config('branding.company_name', g.tenant.name)
        return 'PgAppForge'
```

#### Dependencies
- Existing PgAppForge SimpleFormView
- WTForms for form handling
- JSON storage in existing database
- Flask template system for configuration UI

#### Testing
```python
class TestTenantConfiguration(FABTestCase):
    def test_tenant_config_save(self):
        self.login_user('tenant_admin')
        
        config_data = {
            'company_name': 'Test Company',
            'logo_url': 'https://example.com/logo.png',
            'primary_color': '#ff6b6b',
            'support_email': 'support@test.com'
        }
        
        response = self.client.post('/tenant-config/settings', data=config_data)
        self.assertEqual(response.status_code, 302)
        
        # Verify config was saved
        tenant = Tenant.query.first()
        self.assertEqual(tenant.settings['branding']['company_name'], 'Test Company')
```

### F4: Basic Usage Metrics (1 week)
Simple usage tracking that integrates with existing analytics infrastructure.

#### Technical Implementation
```python
from pgappforge.charts.views import BaseChartView
from pgappforge.views.analytics_view import WizardAnalyticsView
from datetime import datetime, timedelta

class TenantUsageMetrics:
    """Service for collecting tenant usage metrics"""
    
    def __init__(self):
        self.db = db
    
    def record_user_activity(self, user_id, activity_type, metadata=None):
        """Record user activity for current tenant"""
        from flask import g
        
        if not hasattr(g, 'tenant_id') or not g.tenant_id:
            return
        
        # Simple usage tracking table
        usage_record = {
            'tenant_id': g.tenant_id,
            'user_id': user_id,
            'activity_type': activity_type,  # login, page_view, form_submit, etc.
            'timestamp': datetime.utcnow(),
            'metadata': json.dumps(metadata or {})
        }
        
        # Could use existing PgAppForge audit tables or simple usage table
        self._store_usage_record(usage_record)
    
    def get_tenant_usage_summary(self, tenant_id, days=30):
        """Get usage summary for a tenant using existing patterns"""
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Use existing database query patterns
        usage_data = self.db.session.execute(
            text("""
                SELECT 
                    DATE(timestamp) as date,
                    activity_type,
                    COUNT(*) as count
                FROM tenant_usage 
                WHERE tenant_id = :tenant_id 
                    AND timestamp >= :start_date 
                    AND timestamp <= :end_date
                GROUP BY DATE(timestamp), activity_type
                ORDER BY date DESC
            """),
            {
                'tenant_id': tenant_id,
                'start_date': start_date,
                'end_date': end_date
            }
        ).fetchall()
        
        return self._format_usage_data(usage_data)
    
    def _store_usage_record(self, record):
        """Store usage record using existing database patterns"""
        # Simple implementation - could be enhanced with batching
        self.db.session.execute(
            text("""
                INSERT INTO tenant_usage (tenant_id, user_id, activity_type, timestamp, metadata)
                VALUES (:tenant_id, :user_id, :activity_type, :timestamp, :metadata)
            """),
            record
        )
        self.db.session.commit()

class TenantUsageChartView(BaseChartView):
    """Usage charts using existing BaseChartView patterns"""
    
    chart_title = 'Tenant Usage Overview'
    chart_type = 'LineChart'
    
    @expose('/usage-chart')
    @has_access
    def usage_chart(self):
        """Generate usage chart for current tenant"""
        
        # Get current tenant
        tenant_id = self._get_current_tenant_id()
        if not tenant_id:
            return self.render_template('errors/no_tenant.html')
        
        # Get usage data
        metrics = TenantUsageMetrics()
        usage_data = metrics.get_tenant_usage_summary(tenant_id)
        
        # Format for chart using existing patterns
        chart_data = self._format_chart_data(usage_data)
        
        return self.render_template(
            self.chart_template,
            chart_data=chart_data,
            chart_title=self.chart_title,
            chart_type=self.chart_type
        )
    
    def _format_chart_data(self, usage_data):
        """Format data for chart using existing chart patterns"""
        
        # Group by date and sum activities
        daily_totals = {}
        for row in usage_data:
            date_str = row['date'].strftime('%Y-%m-%d')
            if date_str not in daily_totals:
                daily_totals[date_str] = 0
            daily_totals[date_str] += row['count']
        
        # Return in format expected by existing chart widgets
        return [
            {'label': date, 'value': count}
            for date, count in daily_totals.items()
        ]

class TenantAnalyticsView(WizardAnalyticsView):
    """Enhanced analytics view with tenant-specific metrics"""
    
    route_base = '/tenant-analytics'
    
    @expose('/dashboard')
    @has_access
    def tenant_dashboard(self):
        """Tenant-specific analytics dashboard"""
        
        tenant_id = self._get_current_tenant_id()
        if not tenant_id:
            flash('No active tenant found', 'error')
            return redirect(url_for('IndexView.index'))
        
        # Get tenant metrics
        metrics = TenantUsageMetrics()
        usage_summary = metrics.get_tenant_usage_summary(tenant_id)
        
        # Get tenant info
        tenant = db.session.query(Tenant).get(tenant_id)
        
        # Calculate key metrics
        total_users = self._get_tenant_user_count(tenant_id)
        active_users_30d = self._get_active_users(tenant_id, 30)
        storage_used = self._get_storage_usage(tenant_id)
        
        return self.render_template(
            'tenant/analytics_dashboard.html',
            tenant=tenant,
            usage_data=usage_summary,
            metrics={
                'total_users': total_users,
                'active_users_30d': active_users_30d,
                'storage_used_gb': storage_used,
                'plan_type': tenant.plan_type,
                'usage_percentage': (active_users_30d / tenant.max_users) * 100 if tenant.max_users > 0 else 0
            }
        )
    
    def _get_current_tenant_id(self):
        """Get current tenant ID using existing patterns"""
        from flask import g, session
        return getattr(g, 'tenant_id', None) or session.get('current_tenant_id')
    
    def _get_tenant_user_count(self, tenant_id):
        """Get total user count for tenant"""
        return db.session.query(User).filter(User.tenant_id == tenant_id).count()
    
    def _get_active_users(self, tenant_id, days):
        """Get active user count for period"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # This would depend on how user activity is tracked
        # Could use existing audit logs or login tracking
        return db.session.execute(
            text("""
                SELECT COUNT(DISTINCT user_id) 
                FROM tenant_usage 
                WHERE tenant_id = :tenant_id 
                    AND timestamp >= :cutoff_date
            """),
            {'tenant_id': tenant_id, 'cutoff_date': cutoff_date}
        ).scalar()

# Middleware to automatically track usage
@before_request
def track_user_activity():
    """Automatically track user activity"""
    from flask_login import current_user
    
    if current_user.is_authenticated and request.endpoint:
        metrics = TenantUsageMetrics()
        metrics.record_user_activity(
            user_id=current_user.id,
            activity_type='page_view',
            metadata={'endpoint': request.endpoint, 'method': request.method}
        )
```

#### Dependencies
- Existing PgAppForge analytics infrastructure
- Existing BaseChartView for usage charts
- Database for usage tracking
- Existing WizardAnalyticsView patterns

#### Testing
```python
class TestTenantUsageMetrics(FABTestCase):
    def test_usage_recording(self):
        with self.app.app_context():
            g.tenant_id = 1
            
            metrics = TenantUsageMetrics()
            metrics.record_user_activity(
                user_id=1,
                activity_type='login',
                metadata={'ip': '127.0.0.1'}
            )
            
            usage_summary = metrics.get_tenant_usage_summary(1)
            self.assertGreater(len(usage_summary), 0)
```

## Implementation Plan

### Week 1: Tenant Management View
- Create Tenant model using existing AuditMixin
- Implement TenantModelView using existing ModelView patterns
- Add tenant switching functionality
- Create basic tenant user management

### Week 2: Subdomain Routing
- Implement TenantMiddleware for subdomain detection
- Integrate with existing MultiTenancyMixin context
- Add tenant-aware URL generation
- Test with different subdomain configurations

### Week 3: Tenant Configuration
- Create tenant configuration forms using existing SimpleFormView
- Implement JSON-based settings storage
- Add tenant branding and feature toggles
- Create helper functions for accessing configuration

### Week 4: Basic Usage Metrics
- Implement usage tracking service
- Create tenant usage charts using existing BaseChartView
- Add tenant analytics dashboard
- Integrate with existing WizardAnalyticsView

## Success Metrics
- All features build on existing PgAppForge MultiTenancyMixin
- No breaking changes to existing tenant isolation
- Tenant switching works with existing security model
- Usage metrics integrate with existing analytics infrastructure
- Features work with current subdomain DNS configuration

## Migration Strategy
These features enhance existing multi-tenant capabilities:
- Tenant model extends existing AuditMixin patterns
- TenantMiddleware works with existing MultiTenancyMixin (uses g.tenant_id)
- Configuration system uses existing form and database patterns  
- Usage metrics build on existing analytics infrastructure

Existing PgAppForge applications using MultiTenancyMixin can adopt these features incrementally without disrupting current tenant isolation functionality.