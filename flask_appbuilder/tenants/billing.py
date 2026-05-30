"""
Multi-Tenant Billing Service.

Handles subscription management, payment processing via Stripe,
usage tracking, and billing calculations for the multi-tenant SaaS platform.
"""

import logging
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from flask import current_app
from sqlalchemy import func

from ..models.tenant_models import Tenant, TenantSubscription, TenantUsage

log = logging.getLogger(__name__)


@dataclass
class UsageMetrics:
    """Data class for usage metrics"""
    resource_type: str
    current_usage: float
    limit: float
    percentage_used: float
    is_over_limit: bool
    is_warning_level: bool  # Over 80% of limit


@dataclass
class BillingPeriod:
    """Data class for billing period"""
    start_date: date
    end_date: date
    is_current: bool


class BillingService:
    """
    Service for managing tenant billing, subscriptions, and usage tracking.
    
    Integrates with Stripe for payment processing and provides comprehensive
    usage monitoring and quota enforcement.
    """
    
    def __init__(self, stripe_api_key: str = None):
        """Initialize billing service with Stripe integration"""
        self.stripe_api_key = stripe_api_key or current_app.config.get('STRIPE_SECRET_KEY')
        self._stripe = None
        
        if self.stripe_api_key:
            try:
                import stripe
                stripe.api_key = self.stripe_api_key
                self._stripe = stripe
                log.info("Stripe billing integration initialized")
            except ImportError:
                log.warning("Stripe library not installed. Billing features will be limited.")
            except Exception as e:
                log.error(f"Failed to initialize Stripe: {e}")
        else:
            log.warning("No Stripe API key configured. Billing features disabled.")
    
    def create_stripe_customer(self, tenant: Tenant) -> str:
        """Create Stripe customer for tenant"""
        if not self._stripe:
            raise ValueError("Stripe not configured")
        
        try:
            customer = self._stripe.Customer.create(
                email=tenant.primary_contact_email,
                name=tenant.name,
                description=f"Tenant: {tenant.slug}",
                metadata={
                    'tenant_id': str(tenant.id),
                    'tenant_slug': tenant.slug
                }
            )
            
            log.info(f"Created Stripe customer {customer.id} for tenant {tenant.slug}")
            return customer.id
            
        except Exception as e:
            log.error(f"Failed to create Stripe customer for tenant {tenant.id}: {e}")
            raise
    
    def create_subscription(self, tenant: Tenant, plan_id: str, 
                          payment_method_id: str = None) -> TenantSubscription:
        """Create subscription for tenant"""
        if not self._stripe:
            raise ValueError("Stripe not configured")
        
        try:
            from flask_appbuilder import db
            
            # Get or create Stripe customer
            stripe_customer_id = tenant.subscription_id
            if not stripe_customer_id:
                stripe_customer_id = self.create_stripe_customer(tenant)
                tenant.subscription_id = stripe_customer_id
                db.session.commit()
            
            # Get plan configuration
            plan_config = self._get_plan_config(plan_id)
            if not plan_config:
                raise ValueError(f"Invalid plan ID: {plan_id}")
            
            # Create subscription data
            subscription_data = {
                'customer': stripe_customer_id,
                'items': [{'price': plan_config['stripe_price_id']}],
                'expand': ['latest_invoice.payment_intent'],
                'metadata': {
                    'tenant_id': str(tenant.id),
                    'tenant_slug': tenant.slug
                }
            }
            
            if payment_method_id:
                subscription_data['default_payment_method'] = payment_method_id
            
            # Create Stripe subscription
            stripe_subscription = self._stripe.Subscription.create(**subscription_data)
            
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
                monthly_amount=Decimal(str(stripe_subscription.items.data[0].price.unit_amount / 100)),
                usage_based=plan_config.get('usage_based', False),
                usage_rate=plan_config.get('usage_rates')
            )
            
            db.session.add(subscription)
            
            # Update tenant plan
            tenant.plan_id = plan_id
            db.session.commit()
            
            log.info(f"Created subscription {subscription.id} for tenant {tenant.slug}")
            return subscription
            
        except Exception as e:
            log.error(f"Failed to create subscription for tenant {tenant.id}: {e}")
            raise
    
    def track_usage(self, tenant_id: int, usage_type: str, 
                   amount: float, unit: str, metadata: dict = None) -> TenantUsage:
        """Track usage for billing and quota enforcement"""
        from flask_appbuilder import db
        
        try:
            tenant = Tenant.query.get(tenant_id)
            if not tenant:
                raise ValueError(f"Tenant {tenant_id} not found")
            
            # Get active subscription
            active_subscription = TenantSubscription.query.filter_by(
                tenant_id=tenant_id,
                status='active'
            ).first()
            
            # Calculate cost if usage-based pricing
            unit_cost = None
            total_cost = None
            
            if active_subscription and active_subscription.usage_based:
                rates = active_subscription.usage_rate or {}
                if usage_type in rates:
                    unit_cost = Decimal(str(rates[usage_type]))
                    total_cost = unit_cost * Decimal(str(amount))
            
            # Create usage record
            usage_record = TenantUsage(
                tenant_id=tenant_id,
                subscription_id=active_subscription.id if active_subscription else None,
                usage_type=usage_type,
                usage_amount=Decimal(str(amount)),
                unit=unit,
                unit_cost=unit_cost,
                total_cost=total_cost,
                metadata=metadata or {}
            )
            
            db.session.add(usage_record)
            db.session.commit()
            
            # Check usage limits
            self._check_usage_limits(tenant, usage_type, amount)
            
            log.debug(f"Tracked usage for tenant {tenant_id}: {amount} {unit} of {usage_type}")
            return usage_record
            
        except Exception as e:
            log.error(f"Failed to track usage for tenant {tenant_id}: {e}")
            raise
    
    def get_usage_metrics(self, tenant: Tenant, resource_types: List[str] = None) -> List[UsageMetrics]:
        """Get current usage metrics for tenant"""
        try:
            if not resource_types:
                limits = tenant.get_resource_limits()
                resource_types = list(limits.keys())
            
            metrics = []
            current_period = self.get_current_billing_period(tenant)
            
            for resource_type in resource_types:
                usage_data = self._get_usage_for_period(
                    tenant.id, 
                    resource_type,
                    current_period.start_date,
                    current_period.end_date
                )
                
                limit = tenant.get_resource_limits().get(resource_type, 0)
                if limit == -1:  # Unlimited
                    percentage_used = 0
                    is_over_limit = False
                    is_warning_level = False
                else:
                    percentage_used = (usage_data / limit * 100) if limit > 0 else 0
                    is_over_limit = usage_data > limit
                    is_warning_level = percentage_used >= 80
                
                metrics.append(UsageMetrics(
                    resource_type=resource_type,
                    current_usage=usage_data,
                    limit=limit,
                    percentage_used=percentage_used,
                    is_over_limit=is_over_limit,
                    is_warning_level=is_warning_level
                ))
            
            return metrics
            
        except Exception as e:
            log.error(f"Failed to get usage metrics for tenant {tenant.id}: {e}")
            return []
    
    def get_billing_history(self, tenant: Tenant, months: int = 6) -> List[Dict[str, Any]]:
        """Get billing history for tenant"""
        try:
            from flask_appbuilder import db
            
            end_date = date.today()
            start_date = end_date - timedelta(days=months * 30)
            
            # Get usage records grouped by month
            usage_query = db.session.query(
                func.date_trunc('month', TenantUsage.usage_date).label('month'),
                TenantUsage.usage_type,
                func.sum(TenantUsage.usage_amount).label('total_usage'),
                func.sum(TenantUsage.total_cost).label('total_cost')
            ).filter(
                TenantUsage.tenant_id == tenant.id,
                TenantUsage.usage_date >= start_date,
                TenantUsage.usage_date <= end_date
            ).group_by(
                'month', TenantUsage.usage_type
            ).order_by('month', TenantUsage.usage_type)
            
            # Organize data by month
            billing_data = {}
            for month, usage_type, total_usage, total_cost in usage_query:
                month_key = month.strftime('%Y-%m')
                if month_key not in billing_data:
                    billing_data[month_key] = {
                        'month': month,
                        'usage': {},
                        'total_cost': Decimal('0.00')
                    }
                
                billing_data[month_key]['usage'][usage_type] = {
                    'amount': float(total_usage or 0),
                    'cost': float(total_cost or 0)
                }
                billing_data[month_key]['total_cost'] += Decimal(str(total_cost or 0))
            
            # Convert to list and add subscription costs
            history = []
            for month_data in billing_data.values():
                # Add subscription cost
                subscription = TenantSubscription.query.filter_by(
                    tenant_id=tenant.id,
                    status='active'
                ).first()
                
                if subscription:
                    month_data['subscription_cost'] = float(subscription.monthly_amount or 0)
                    month_data['total_cost'] += subscription.monthly_amount or Decimal('0.00')
                else:
                    month_data['subscription_cost'] = 0
                
                month_data['total_cost'] = float(month_data['total_cost'])
                history.append(month_data)
            
            return sorted(history, key=lambda x: x['month'], reverse=True)
            
        except Exception as e:
            log.error(f"Failed to get billing history for tenant {tenant.id}: {e}")
            return []
    
    def calculate_overage_charges(self, tenant: Tenant, period: BillingPeriod = None) -> Dict[str, Decimal]:
        """Calculate overage charges for billing period"""
        try:
            if not period:
                period = self.get_current_billing_period(tenant)
            
            limits = tenant.get_resource_limits()
            overages = {}
            
            for resource_type, limit in limits.items():
                if limit == -1:  # Unlimited
                    continue
                
                usage = self._get_usage_for_period(
                    tenant.id,
                    resource_type, 
                    period.start_date,
                    period.end_date
                )
                
                if usage > limit:
                    overage_amount = usage - limit
                    overage_rate = self._get_overage_rate(tenant.plan_id, resource_type)
                    overage_charge = Decimal(str(overage_amount)) * Decimal(str(overage_rate))
                    overages[resource_type] = overage_charge
            
            return overages
            
        except Exception as e:
            log.error(f"Failed to calculate overage charges for tenant {tenant.id}: {e}")
            return {}
    
    def get_current_billing_period(self, tenant: Tenant) -> BillingPeriod:
        """Get current billing period for tenant"""
        subscription = TenantSubscription.query.filter_by(
            tenant_id=tenant.id,
            status='active'
        ).first()
        
        if subscription and subscription.current_period_start and subscription.current_period_end:
            return BillingPeriod(
                start_date=subscription.current_period_start.date(),
                end_date=subscription.current_period_end.date(),
                is_current=True
            )
        else:
            # Default to current month
            today = date.today()
            start_date = today.replace(day=1)
            # Get last day of month
            if today.month == 12:
                end_date = date(today.year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(today.year, today.month + 1, 1) - timedelta(days=1)
            
            return BillingPeriod(
                start_date=start_date,
                end_date=end_date,
                is_current=True
            )
    
    def _check_usage_limits(self, tenant: Tenant, usage_type: str, new_usage: float):
        """Check if tenant is approaching or exceeding usage limits"""
        limits = tenant.get_resource_limits()
        limit = limits.get(usage_type)
        
        if not limit or limit == -1:  # No limit or unlimited
            return
        
        # Get current period usage
        current_period = self.get_current_billing_period(tenant)
        current_usage = self._get_usage_for_period(
            tenant.id,
            usage_type,
            current_period.start_date,
            current_period.end_date
        )
        
        current_usage += new_usage
        
        # Check for limit violations
        if current_usage > limit:
            self._handle_usage_limit_exceeded(tenant, usage_type, current_usage, limit)
        elif current_usage >= (limit * 0.8):  # 80% threshold warning
            self._send_usage_warning(tenant, usage_type, current_usage, limit)
    
    def _handle_usage_limit_exceeded(self, tenant: Tenant, usage_type: str, 
                                   current_usage: float, limit: float):
        """Handle usage limit exceeded"""
        log.warning(f"Usage limit exceeded for tenant {tenant.slug}: "
                   f"{usage_type} = {current_usage}/{limit}")
        
        # In a real implementation, this could:
        # 1. Send email notification
        # 2. Create alert in system
        # 3. Throttle API access
        # 4. Suspend certain features
        
        # For now, just log
        overage = current_usage - limit
        percentage_over = (overage / limit) * 100
        
        log.info(f"Tenant {tenant.slug} is {percentage_over:.1f}% over limit for {usage_type}")
    
    def _send_usage_warning(self, tenant: Tenant, usage_type: str, 
                           current_usage: float, limit: float):
        """Send usage warning notification"""
        percentage_used = (current_usage / limit) * 100
        
        log.info(f"Usage warning for tenant {tenant.slug}: "
                f"{usage_type} at {percentage_used:.1f}% of limit")
        
        # In a real implementation, this would send email notification
    
    def _get_usage_for_period(self, tenant_id: int, usage_type: str, 
                             start_date: date, end_date: date) -> float:
        """Get total usage for specific period and type"""
        from flask_appbuilder import db
        
        result = db.session.query(
            func.sum(TenantUsage.usage_amount)
        ).filter(
            TenantUsage.tenant_id == tenant_id,
            TenantUsage.usage_type == usage_type,
            TenantUsage.usage_date >= start_date,
            TenantUsage.usage_date <= end_date
        ).scalar()
        
        return float(result or 0)
    
    def _get_plan_config(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get plan configuration from app config or database"""
        try:
            # Try to load from app configuration first
            plan_configs = current_app.config.get('TENANT_PLAN_CONFIGS')
            if plan_configs and plan_id in plan_configs:
                return plan_configs[plan_id]
            
            # Fallback to built-in plans if no config found
            default_plans = {
                'free': {
                    'stripe_price_id': None,  
                    'usage_based': False,
                    'monthly_cost': 0
                },
                'starter': {
                    'stripe_price_id': current_app.config.get('STRIPE_STARTER_PRICE_ID', 'price_starter_monthly'),
                    'usage_based': True,
                    'monthly_cost': 29.99,
                    'usage_rates': {
                        'api_calls': 0.001,  
                        'storage_gb': 0.10   
                    }
                },
                'professional': {
                    'stripe_price_id': current_app.config.get('STRIPE_PROFESSIONAL_PRICE_ID', 'price_professional_monthly'),
                    'usage_based': True, 
                    'monthly_cost': 99.99,
                    'usage_rates': {
                        'api_calls': 0.0008,
                        'storage_gb': 0.08
                    }
                },
                'enterprise': {
                    'stripe_price_id': current_app.config.get('STRIPE_ENTERPRISE_PRICE_ID', 'price_enterprise_monthly'),
                    'usage_based': False,  
                    'monthly_cost': 299.99
                }
            }
            
            config = default_plans.get(plan_id)
            if not config:
                log.error(f"Unknown plan ID: {plan_id}")
                return None
            
            # Validate Stripe price ID exists if not free plan
            if plan_id != 'free' and not config.get('stripe_price_id'):
                log.warning(f"No Stripe price ID configured for plan {plan_id}")
            
            return config
            
        except Exception as e:
            log.error(f"Failed to get plan config for {plan_id}: {e}")
            return None
    
    def _get_overage_rate(self, plan_id: str, resource_type: str) -> float:
        """Get overage rate for resource type and plan"""
        plan_config = self._get_plan_config(plan_id)
        if not plan_config or not plan_config.get('usage_rates'):
            return 0.0
        
        return plan_config['usage_rates'].get(resource_type, 0.0)


# Global billing service instance
_billing_service = None


def get_billing_service() -> BillingService:
    """Get global billing service instance"""
    global _billing_service
    
    if _billing_service is None:
        _billing_service = BillingService()
    
    return _billing_service


def track_api_usage(tenant_id: int, endpoint: str, method: str = 'GET'):
    """Helper function to track API usage"""
    try:
        billing_service = get_billing_service()
        billing_service.track_usage(
            tenant_id=tenant_id,
            usage_type='api_calls',
            amount=1.0,
            unit='calls',
            metadata={
                'endpoint': endpoint,
                'method': method,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
        )
    except Exception as e:
        # Don't break API calls if usage tracking fails
        log.error(f"Failed to track API usage: {e}")


def track_storage_usage(tenant_id: int, size_bytes: int, operation: str = 'upload'):
    """Helper function to track storage usage"""
    try:
        billing_service = get_billing_service()
        size_gb = size_bytes / (1024 ** 3)  # Convert bytes to GB
        
        billing_service.track_usage(
            tenant_id=tenant_id,
            usage_type='storage_gb',
            amount=size_gb,
            unit='gb',
            metadata={
                'operation': operation,
                'size_bytes': size_bytes,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
        )
    except Exception as e:
        log.error(f"Failed to track storage usage: {e}")


def track_user_activity(tenant_id: int, user_id: int, activity_type: str):
    """Helper function to track user activity"""
    try:
        billing_service = get_billing_service()
        billing_service.track_usage(
            tenant_id=tenant_id,
            usage_type='user_activity',
            amount=1.0,
            unit='actions',
            metadata={
                'user_id': user_id,
                'activity_type': activity_type,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
        )
    except Exception as e:
        log.error(f"Failed to track user activity: {e}")