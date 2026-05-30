"""
Multi-Tenant SaaS Views.

Administrative views for managing tenants, users, subscriptions,
and providing tenant onboarding and self-service functionality.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from flask import render_template, request, jsonify, flash, redirect, url_for, g
from flask_appbuilder import ModelView, BaseView, expose, has_access
from flask_appbuilder.actions import action
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import protect
from flask_login import current_user
from wtforms import Form, StringField, TextAreaField, SelectField, validators
from wtforms.validators import DataRequired, Email, Length

from ..models.tenant_models import Tenant, TenantUser, TenantConfig, TenantSubscription, TenantUsage
from ..models.tenant_context import tenant_context, require_tenant_context, get_current_tenant

log = logging.getLogger(__name__)


class TenantModelView(ModelView):
    """Administrative view for managing tenants"""
    
    datamodel = SQLAInterface(Tenant)
    
    # List view configuration
    list_columns = ['slug', 'name', 'status', 'plan_id', 'user_count', 'created_on']
    search_columns = ['slug', 'name', 'primary_contact_email', 'status']
    
    # Show view configuration
    show_columns = [
        'slug', 'name', 'description', 'status', 'plan_id',
        'primary_contact_email', 'billing_email', 'phone',
        'custom_domain', 'subscription_id', 'user_count',
        'created_on', 'changed_on'
    ]
    
    # Edit/Add view configuration
    add_columns = [
        'slug', 'name', 'description', 'primary_contact_email', 
        'billing_email', 'phone', 'plan_id', 'custom_domain'
    ]
    edit_columns = [
        'name', 'description', 'status', 'primary_contact_email',
        'billing_email', 'phone', 'plan_id', 'custom_domain',
        'resource_limits', 'branding_config'
    ]
    
    # Column labels
    label_columns = {
        'slug': 'Tenant Slug',
        'primary_contact_email': 'Primary Email',
        'billing_email': 'Billing Email',
        'plan_id': 'Subscription Plan',
        'custom_domain': 'Custom Domain',
        'user_count': 'Users',
        'resource_limits': 'Resource Limits',
        'branding_config': 'Branding Config'
    }
    
    # Validators
    validators_columns = {
        'slug': [validators.Regexp(r'^[a-z0-9-]+$', message="Slug can only contain lowercase letters, numbers, and hyphens")],
        'primary_contact_email': [validators.Email()],
        'billing_email': [validators.Optional(), validators.Email()]
    }
    
    @action("suspend", "Suspend", "Suspend selected tenants?", "fa-pause")
    def suspend_tenants(self, tenants):
        """Suspend selected tenants"""
        try:
            count = 0
            for tenant in tenants:
                if tenant.status != 'suspended':
                    tenant.suspend("Suspended by administrator")
                    count += 1
            
            self.datamodel.session.commit()
            flash(f"Suspended {count} tenant(s)", "success")
            
        except Exception as e:
            log.error(f"Failed to suspend tenants: {e}")
            flash("Failed to suspend tenants", "error")
            self.datamodel.session.rollback()
        
        return redirect(self.get_redirect())
    
    @action("activate", "Activate", "Activate selected tenants?", "fa-play")
    def activate_tenants(self, tenants):
        """Activate selected tenants"""
        try:
            count = 0
            for tenant in tenants:
                if tenant.status != 'active':
                    tenant.activate()
                    count += 1
            
            self.datamodel.session.commit()
            flash(f"Activated {count} tenant(s)", "success")
            
        except Exception as e:
            log.error(f"Failed to activate tenants: {e}")
            flash("Failed to activate tenants", "error")
            self.datamodel.session.rollback()
        
        return redirect(self.get_redirect())


class TenantUserModelView(ModelView):
    """Administrative view for managing tenant-user relationships"""
    
    datamodel = SQLAInterface(TenantUser)
    
    # Relationships
    related_views = [TenantModelView]
    
    # List view configuration
    list_columns = ['tenant.name', 'user.username', 'role_within_tenant', 'is_active', 'joined_at']
    search_columns = ['tenant.name', 'user.username', 'role_within_tenant']
    
    # Show view configuration
    show_columns = [
        'tenant.name', 'user.username', 'user.email', 'role_within_tenant',
        'is_active', 'joined_at', 'last_login_at', 'user_metadata'
    ]
    
    # Edit/Add view configuration
    add_columns = ['tenant', 'user', 'role_within_tenant', 'is_active']
    edit_columns = ['role_within_tenant', 'is_active', 'user_metadata']
    
    # Column labels
    label_columns = {
        'tenant.name': 'Tenant',
        'user.username': 'Username',
        'user.email': 'Email',
        'role_within_tenant': 'Role',
        'is_active': 'Active',
        'joined_at': 'Joined',
        'last_login_at': 'Last Login',
        'user_metadata': 'Metadata'
    }


class TenantConfigModelView(ModelView):
    """Administrative view for managing tenant configurations"""
    
    datamodel = SQLAInterface(TenantConfig)
    
    # Relationships
    related_views = [TenantModelView]
    
    # List view configuration
    list_columns = ['tenant.name', 'config_key', 'category', 'config_type', 'is_sensitive']
    search_columns = ['tenant.name', 'config_key', 'category']
    
    # Show view configuration
    show_columns = [
        'tenant.name', 'config_key', 'config_value', 'config_type',
        'category', 'description', 'is_sensitive'
    ]
    
    # Edit/Add view configuration
    add_columns = ['tenant', 'config_key', 'config_value', 'config_type', 'category', 'description', 'is_sensitive']
    edit_columns = ['config_value', 'config_type', 'category', 'description', 'is_sensitive']
    
    # Column labels
    label_columns = {
        'tenant.name': 'Tenant',
        'config_key': 'Key',
        'config_value': 'Value',
        'config_type': 'Type',
        'is_sensitive': 'Sensitive'
    }


class TenantOnboardingView(BaseView):
    """Public view for tenant signup and onboarding"""
    
    route_base = "/onboarding"
    default_view = 'index'
    
    @expose("/")
    def index(self):
        """Landing page for new tenant signup"""
        plans = self._get_available_plans()
        return self.render_template(
            'tenants/onboarding_start.html',
            plans=plans
        )
    
    @expose("/signup", methods=['GET', 'POST'])
    def signup(self):
        """Tenant signup form"""
        if request.method == 'POST':
            return self._process_signup()
        
        plans = self._get_available_plans()
        return self.render_template(
            'tenants/signup_form.html',
            plans=plans
        )
    
    @expose("/verify/<token>")
    def verify(self, token):
        """Email verification for new tenants"""
        try:
            # Decode verification token and activate tenant
            tenant_id = self._verify_token(token)
            if tenant_id:
                tenant = Tenant.query.get(tenant_id)
                if tenant and tenant.status == 'pending_verification':
                    tenant.activate()
                    self.datamodel.session.commit()
                    
                    flash("Your tenant account has been verified and activated!", "success")
                    return redirect(f"http://{tenant.slug}.{request.host}/login")
            
            flash("Invalid or expired verification token", "error")
            return redirect(url_for('TenantOnboardingView.index'))
            
        except Exception as e:
            log.error(f"Verification failed: {e}")
            flash("Verification failed. Please try again.", "error")
            return redirect(url_for('TenantOnboardingView.index'))
    
    def _process_signup(self):
        """Process new tenant signup"""
        try:
            data = request.get_json() or request.form.to_dict()
            
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
                description=data.get('description', ''),
                primary_contact_email=data['email'],
                plan_id=data.get('plan_id', 'free'),
                status='pending_verification'
            )
            
            self.datamodel.session.add(tenant)
            self.datamodel.session.commit()
            
            # Create admin user for tenant
            admin_user = self._create_tenant_admin(tenant, data)
            
            # Send verification email
            verification_token = self._send_verification_email(tenant, admin_user)
            
            response_data = {
                'success': True,
                'tenant_id': tenant.id,
                'tenant_slug': tenant.slug,
                'message': 'Please check your email to verify your account',
                'verification_token': verification_token  # Only for testing
            }
            
            if request.is_json:
                return jsonify(response_data)
            else:
                flash(response_data['message'], 'success')
                return redirect(url_for('TenantOnboardingView.index'))
            
        except Exception as e:
            log.error(f"Signup failed: {e}")
            self.datamodel.session.rollback()
            
            if request.is_json:
                return jsonify({'error': 'Signup failed. Please try again.'}), 500
            else:
                flash('Signup failed. Please try again.', 'error')
                return redirect(url_for('TenantOnboardingView.signup'))
    
    def _validate_signup_data(self, data: Dict) -> Dict[str, str]:
        """Validate signup form data"""
        errors = {}
        
        # Required fields
        required_fields = ['slug', 'company_name', 'email', 'first_name', 'last_name', 'password']
        for field in required_fields:
            if not data.get(field):
                errors[field] = 'This field is required'
        
        # Slug validation
        slug = data.get('slug', '')
        if slug:
            if len(slug) < 3 or len(slug) > 50:
                errors['slug'] = 'Slug must be between 3 and 50 characters'
            elif not slug.replace('-', '').replace('_', '').isalnum():
                errors['slug'] = 'Slug can only contain letters, numbers, hyphens, and underscores'
        
        # Email validation
        email = data.get('email', '')
        if email and '@' not in email:
            errors['email'] = 'Invalid email address'
        
        # Password validation
        password = data.get('password', '')
        if password and len(password) < 8:
            errors['password'] = 'Password must be at least 8 characters long'
        
        return errors
    
    def _create_tenant_admin(self, tenant: Tenant, signup_data: Dict):
        """Create admin user for new tenant"""
        from flask_appbuilder.security.sqla.models import User
        from werkzeug.security import generate_password_hash
        
        # Create user in main user table
        user = User(
            first_name=signup_data['first_name'],
            last_name=signup_data['last_name'],
            username=signup_data['email'],
            email=signup_data['email'],
            active=False  # Will be activated on email verification
        )
        
        user.password = generate_password_hash(signup_data['password'])
        self.datamodel.session.add(user)
        self.datamodel.session.flush()  # Get user ID
        
        # Link user to tenant with admin role
        tenant_user = TenantUser(
            tenant_id=tenant.id,
            user_id=user.id,
            role_within_tenant='admin',
            is_active=True
        )
        
        self.datamodel.session.add(tenant_user)
        self.datamodel.session.commit()
        
        return user
    
    def _send_verification_email(self, tenant: Tenant, user) -> str:
        """Send verification email with secure token storage"""
        try:
            from itsdangerous import URLSafeTimedSerializer
            from flask import current_app
            
            # Generate secure token
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            token_data = {
                'tenant_id': tenant.id,
                'user_id': user.id,
                'email': user.email,
                'action': 'verify_tenant'
            }
            token = serializer.dumps(token_data)
            
            # Store token reference in database (for invalidation if needed)
            from ..models.tenant_models import TenantConfig
            verification_config = TenantConfig(
                tenant_id=tenant.id,
                config_key='verification_token',
                config_value={'token': token, 'expires_at': (datetime.now(tz=timezone.utc) + timedelta(hours=24)).isoformat()},
                config_type='json',
                category='onboarding',
                is_sensitive=True
            )
            self.datamodel.session.add(verification_config)
            self.datamodel.session.commit()
            
            # Generate verification URL
            verify_url = url_for('TenantOnboardingView.verify', token=token, _external=True)
            
            # Send email (if Flask-Mail is configured)
            if current_app.config.get('MAIL_SERVER'):
                try:
                    from flask_mail import Message, Mail
                    mail = Mail(current_app)
                    
                    msg = Message(
                        subject=f"Verify your {tenant.name} account",
                        recipients=[user.email],
                        html=f"""
                        <h2>Welcome to {tenant.name}!</h2>
                        <p>Please click the link below to verify your account:</p>
                        <p><a href="{verify_url}" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Verify Account</a></p>
                        <p>If the button doesn't work, copy and paste this link into your browser:</p>
                        <p>{verify_url}</p>
                        <p>This link will expire in 24 hours.</p>
                        """,
                        body=f"""
                        Welcome to {tenant.name}!
                        
                        Please visit the following link to verify your account:
                        {verify_url}
                        
                        This link will expire in 24 hours.
                        """
                    )
                    mail.send(msg)
                    log.info(f"Verification email sent to {user.email} for tenant {tenant.slug}")
                    
                except Exception as e:
                    log.error(f"Failed to send verification email: {e}")
                    # Don't fail the whole process if email fails
            else:
                # Development mode - log the verification URL
                log.info(f"DEVELOPMENT: Verification link for {user.email}: {verify_url}")
            
            return token
            
        except Exception as e:
            log.error(f"Failed to generate verification token: {e}")
            raise
    
    def _verify_token(self, token: str) -> Optional[int]:
        """Verify token and return tenant ID"""
        try:
            from itsdangerous import URLSafeTimedSerializer, BadTimeSignature, SignatureExpired
            from flask import current_app
            
            # Verify token signature and decode
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            
            try:
                # Token expires after 24 hours (86400 seconds)
                token_data = serializer.loads(token, max_age=86400)
            except SignatureExpired:
                log.warning(f"Token expired: {token[:20]}...")
                return None
            except BadTimeSignature:
                log.warning(f"Invalid token signature: {token[:20]}...")
                return None
            
            # Validate token data structure
            required_fields = ['tenant_id', 'user_id', 'email', 'action']
            if not all(field in token_data for field in required_fields):
                log.warning(f"Invalid token data structure: {token_data}")
                return None
            
            if token_data['action'] != 'verify_tenant':
                log.warning(f"Invalid token action: {token_data['action']}")
                return None
            
            # Check if token was invalidated (optional additional security)
            from ..models.tenant_models import TenantConfig
            verification_config = TenantConfig.query.filter_by(
                tenant_id=token_data['tenant_id'],
                config_key='verification_token'
            ).first()
            
            if verification_config and verification_config.config_value:
                stored_data = verification_config.config_value
                if isinstance(stored_data, dict) and stored_data.get('token') != token:
                    log.warning(f"Token mismatch - possibly already used or invalidated")
                    return None
            
            log.info(f"Token verified successfully for tenant {token_data['tenant_id']}")
            return token_data['tenant_id']
            
        except Exception as e:
            log.error(f"Token verification failed: {e}")
            return None
    
    def _get_available_plans(self) -> List[Dict]:
        """Get available subscription plans"""
        from ..models.tenant_models import PLAN_FEATURES
        
        plans = []
        for plan_id, plan_config in PLAN_FEATURES.items():
            features = plan_config.get('features', {})
            limits = plan_config.get('limits', {})
            
            # Convert limits to display format
            display_limits = {}
            for key, value in limits.items():
                if value == -1:
                    display_limits[key] = 'Unlimited'
                else:
                    display_limits[key] = value
            
            plans.append({
                'id': plan_id,
                'name': plan_id.title(),
                'features': features,
                'limits': display_limits,
                'recommended': plan_id == 'starter'
            })
        
        return plans


class TenantAdminView(BaseView):
    """Administrative interface for tenant administrators"""
    
    route_base = "/tenant/admin"
    default_view = 'dashboard'
    
    @expose("/")
    @has_access
    @require_tenant_context()
    def dashboard(self):
        """Tenant admin dashboard"""
        tenant = get_current_tenant()
        
        # Get usage statistics
        usage_stats = self._get_usage_statistics(tenant)
        
        # Get subscription info
        subscription = TenantSubscription.query.filter_by(
            tenant_id=tenant.id,
            status='active'
        ).first()
        
        # Get recent activity
        recent_users = TenantUser.query.filter_by(
            tenant_id=tenant.id,
            is_active=True
        ).order_by(TenantUser.joined_at.desc()).limit(5).all()
        
        return self.render_template(
            'tenants/admin_dashboard.html',
            tenant=tenant,
            usage_stats=usage_stats,
            subscription=subscription,
            recent_users=recent_users
        )
    
    @expose("/users")
    @has_access
    @require_tenant_context()
    def manage_users(self):
        """Manage tenant users"""
        tenant = get_current_tenant()
        
        tenant_users = TenantUser.query.filter_by(
            tenant_id=tenant.id,
            is_active=True
        ).join(TenantUser.user).all()
        
        return self.render_template(
            'tenants/user_management.html',
            tenant=tenant,
            users=tenant_users,
            can_add_users=tenant.can_add_user()
        )
    
    @expose("/billing")
    @has_access
    @require_tenant_context()
    def billing_portal(self):
        """Tenant billing and subscription management"""
        tenant = get_current_tenant()
        
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
            'tenants/billing_portal.html',
            tenant=tenant,
            subscription=subscription,
            usage_records=usage_records
        )
    
    @expose("/settings", methods=['GET', 'POST'])
    @has_access
    @require_tenant_context()
    def settings(self):
        """Tenant settings management"""
        tenant = get_current_tenant()
        
        if request.method == 'POST':
            return self._update_tenant_settings(tenant)
        
        # Get current settings
        settings = {
            'name': tenant.name,
            'description': tenant.description,
            'billing_email': tenant.billing_email,
            'phone': tenant.phone,
            'branding': tenant.branding_config or {}
        }
        
        return self.render_template(
            'tenants/settings.html',
            tenant=tenant,
            settings=settings
        )
    
    def _update_tenant_settings(self, tenant: Tenant):
        """Update tenant settings"""
        try:
            data = request.get_json() or request.form.to_dict()
            
            # Update basic info
            if 'name' in data:
                tenant.name = data['name']
            if 'description' in data:
                tenant.description = data['description']
            if 'billing_email' in data:
                tenant.billing_email = data['billing_email']
            if 'phone' in data:
                tenant.phone = data['phone']
            
            # Update branding config
            if 'branding' in data:
                current_branding = tenant.branding_config or {}
                current_branding.update(data['branding'])
                tenant.branding_config = current_branding
            
            self.datamodel.session.commit()
            
            flash("Settings updated successfully", "success")
            
            if request.is_json:
                return jsonify({'success': True})
            else:
                return redirect(url_for('TenantAdminView.settings'))
        
        except Exception as e:
            log.error(f"Failed to update tenant settings: {e}")
            self.datamodel.session.rollback()
            
            flash("Failed to update settings", "error")
            
            if request.is_json:
                return jsonify({'error': 'Update failed'}), 500
            else:
                return redirect(url_for('TenantAdminView.settings'))
    
    def _get_usage_statistics(self, tenant: Tenant) -> Dict[str, Any]:
        """Get usage statistics for tenant"""
        from datetime import date, timedelta
        from sqlalchemy import func
        
        try:
            # Current month usage
            current_month = date.today().replace(day=1)
            
            usage_query = self.datamodel.session.query(
                TenantUsage.usage_type,
                func.sum(TenantUsage.usage_amount).label('total_usage')
            ).filter(
                TenantUsage.tenant_id == tenant.id,
                TenantUsage.usage_date >= current_month
            ).group_by(TenantUsage.usage_type)
            
            usage_data = {}
            for usage_type, total_usage in usage_query:
                usage_data[usage_type] = float(total_usage or 0)
            
            # Get limits
            limits = tenant.get_resource_limits()
            
            # Calculate usage percentages
            usage_percentages = {}
            for resource, limit in limits.items():
                if limit and limit > 0:  # Skip unlimited (-1) limits
                    current_usage = usage_data.get(resource, 0)
                    usage_percentages[resource] = (current_usage / limit) * 100
            
            return {
                'current_usage': usage_data,
                'limits': limits,
                'usage_percentages': usage_percentages,
                'user_count': tenant.user_count,
                'max_users': limits.get('max_users', 0)
            }
        
        except Exception as e:
            log.error(f"Failed to get usage statistics: {e}")
            return {}


class TenantSelectorView(BaseView):
    """View for switching between tenants (for platform admins)"""
    
    route_base = "/tenant/selector"
    
    @expose("/")
    @has_access
    def index(self):
        """Show tenant selector interface"""
        # Only available to platform admins
        if not self._is_platform_admin():
            return redirect("/")
        
        tenants = Tenant.query.filter_by(status='active').order_by(Tenant.name).all()
        current_tenant = get_current_tenant()
        
        return self.render_template(
            'tenants/tenant_selector.html',
            tenants=tenants,
            current_tenant=current_tenant
        )
    
    @expose("/switch/<int:tenant_id>")
    @has_access
    def switch_tenant(self, tenant_id):
        """Switch to a different tenant context"""
        if not self._is_platform_admin():
            return redirect("/")
        
        tenant = Tenant.query.get_or_404(tenant_id)
        if not tenant.is_active:
            flash("Cannot switch to inactive tenant", "error")
            return redirect(url_for('TenantSelectorView.index'))
        
        # Set tenant context
        tenant_context.set_tenant_context(tenant)
        
        flash(f"Switched to tenant: {tenant.name}", "info")
        return redirect("/")
    
    def _is_platform_admin(self) -> bool:
        """Check if current user is a platform administrator"""
        if not current_user or not current_user.is_authenticated:
            return False
        
        # Check if user has platform admin role
        platform_admin_role = self.appbuilder.sm.find_role('Platform Admin')
        if platform_admin_role in current_user.roles:
            return True
        
        # Check if user is a superuser
        return hasattr(current_user, 'is_superuser') and current_user.is_superuser