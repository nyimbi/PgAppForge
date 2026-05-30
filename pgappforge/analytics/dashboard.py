"""
Advanced Analytics and Reporting Dashboard for Multi-Tenant SaaS.

This module provides comprehensive analytics, reporting, and business intelligence
capabilities for multi-tenant PgAppForge applications.
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict
import statistics
import math

# Optional dependencies with fallbacks
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None
    HAS_PANDAS = False
    import logging
    logging.getLogger(__name__).info("pandas not available - using fallback implementations")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False
    import logging
    logging.getLogger(__name__).info("numpy not available - using fallback implementations")

from flask import current_app, request, jsonify, Blueprint, render_template
from pgappforge import BaseView, has_access, expose
from pgappforge import db
from sqlalchemy import func, text, and_, or_
from sqlalchemy.orm import joinedload

from pgappforge.models.tenant_models import (
    Tenant, TenantUser, TenantSubscription, TenantUsage
)
from pgappforge.models.tenant_context import get_current_tenant_id, require_tenant_context
from pgappforge.security.audit_logging import SecurityAuditLog
from pgappforge.tenants.resource_isolation import get_resource_monitor

log = logging.getLogger(__name__)


# Fallback functions for when numpy/pandas are not available
def _safe_mean(values: List[float]) -> float:
    """Calculate mean with fallback when numpy is not available."""
    if not values:
        return 0.0
    
    if HAS_NUMPY:
        return float(np.mean(values))
    else:
        # Fallback to Python statistics module
        try:
            return statistics.mean(values)
        except (TypeError, ValueError, statistics.StatisticsError):
            # Final fallback to basic arithmetic
            return sum(values) / len(values) if values else 0.0


def _safe_median(values: List[float]) -> float:
    """Calculate median with fallback when numpy is not available."""
    if not values:
        return 0.0
    
    if HAS_NUMPY:
        return float(np.median(values))
    else:
        # Fallback to Python statistics module
        try:
            return statistics.median(values)
        except (TypeError, ValueError, statistics.StatisticsError):
            # Final fallback to manual calculation
            sorted_values = sorted(values)
            n = len(sorted_values)
            if n % 2 == 0:
                return (sorted_values[n//2 - 1] + sorted_values[n//2]) / 2
            else:
                return sorted_values[n//2]


def _safe_std(values: List[float]) -> float:
    """Calculate standard deviation with fallback when numpy is not available."""
    if not values:
        return 0.0
    
    if HAS_NUMPY:
        return float(np.std(values))
    else:
        # Fallback to Python statistics module
        try:
            return statistics.stdev(values) if len(values) > 1 else 0.0
        except (TypeError, ValueError, statistics.StatisticsError):
            # Final fallback to manual calculation
            if len(values) < 2:
                return 0.0
            
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            return math.sqrt(variance)


def _safe_percentile(values: List[float], percentile: float) -> float:
    """Calculate percentile with fallback when numpy is not available."""
    if not values:
        return 0.0
    
    if HAS_NUMPY:
        return float(np.percentile(values, percentile))
    else:
        # Fallback to manual percentile calculation
        sorted_values = sorted(values)
        n = len(sorted_values)
        index = (percentile / 100) * (n - 1)
        
        if index.is_integer():
            return sorted_values[int(index)]
        else:
            lower = sorted_values[int(index)]
            upper = sorted_values[int(index) + 1]
            return lower + (upper - lower) * (index - int(index))


def _check_analytics_dependencies() -> Dict[str, bool]:
    """Check which analytics dependencies are available."""
    return {
        'pandas': HAS_PANDAS,
        'numpy': HAS_NUMPY,
        'fallback_available': True  # Python statistics and math are always available
    }


class MetricPeriod(Enum):
    """Time periods for analytics."""
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class ChartType(Enum):
    """Types of charts for visualization."""
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    AREA = "area"
    DONUT = "donut"
    GAUGE = "gauge"
    TABLE = "table"


@dataclass
class AnalyticsMetric:
    """Analytics metric data point."""
    name: str
    value: Union[int, float, str]
    timestamp: datetime
    tenant_id: Optional[int]
    category: str
    tags: Dict[str, Any]


@dataclass
class DashboardWidget:
    """Dashboard widget configuration."""
    id: str
    title: str
    chart_type: ChartType
    data_source: str
    query_params: Dict[str, Any]
    size: str  # small, medium, large
    position: Dict[str, int]  # x, y, width, height
    refresh_interval: int  # seconds


class TenantAnalyticsEngine:
    """Core analytics engine for tenant metrics."""
    
    def __init__(self):
        self.metric_cache = {}
        self.cache_ttl = 300  # 5 minutes
    
    def get_tenant_overview(self, tenant_id: int, period: MetricPeriod = MetricPeriod.MONTH) -> Dict[str, Any]:
        """Get comprehensive tenant overview metrics."""
        end_date = datetime.now(tz=timezone.utc)
        start_date = self._get_period_start_date(end_date, period)
        
        # Basic tenant info
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            return {}
        
        # User metrics
        total_users = db.session.query(func.count(TenantUser.id)).filter(
            TenantUser.tenant_id == tenant_id,
            TenantUser.is_active == True
        ).scalar()
        
        new_users = db.session.query(func.count(TenantUser.id)).filter(
            TenantUser.tenant_id == tenant_id,
            TenantUser.joined_at >= start_date
        ).scalar()
        
        # Active users in period
        active_users = db.session.query(func.count(func.distinct(SecurityAuditLog.user_id))).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.user_id.isnot(None)
        ).scalar()
        
        # Usage metrics
        usage_stats = self._get_usage_metrics(tenant_id, start_date, end_date)
        
        # Security metrics
        security_stats = self._get_security_metrics(tenant_id, start_date, end_date)
        
        # Billing metrics
        billing_stats = self._get_billing_metrics(tenant_id, start_date, end_date)
        
        return {
            'tenant_info': {
                'id': tenant.id,
                'name': tenant.name,
                'slug': tenant.slug,
                'plan': tenant.plan_id,
                'status': tenant.status,
                'created_at': tenant.created_on.isoformat() if tenant.created_on else None
            },
            'user_metrics': {
                'total_users': total_users,
                'new_users_period': new_users,
                'active_users_period': active_users,
                'user_growth_rate': self._calculate_growth_rate(total_users, new_users)
            },
            'usage_metrics': usage_stats,
            'security_metrics': security_stats,
            'billing_metrics': billing_stats,
            'period': period.value,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'generated_at': datetime.now(tz=timezone.utc).isoformat()
        }
    
    def get_platform_overview(self, period: MetricPeriod = MetricPeriod.MONTH) -> Dict[str, Any]:
        """Get platform-wide analytics overview."""
        end_date = datetime.now(tz=timezone.utc)
        start_date = self._get_period_start_date(end_date, period)
        
        # Tenant metrics
        total_tenants = db.session.query(func.count(Tenant.id)).scalar()
        active_tenants = db.session.query(func.count(Tenant.id)).filter(
            Tenant.status == 'active'
        ).scalar()
        
        new_tenants = db.session.query(func.count(Tenant.id)).filter(
            Tenant.created_on >= start_date
        ).scalar()
        
        # Revenue metrics
        revenue_stats = self._get_platform_revenue_metrics(start_date, end_date)
        
        # System performance metrics
        performance_stats = self._get_platform_performance_metrics(start_date, end_date)
        
        # Top tenants by usage
        top_tenants = self._get_top_tenants_by_usage(start_date, end_date, limit=10)
        
        return {
            'tenant_metrics': {
                'total_tenants': total_tenants,
                'active_tenants': active_tenants,
                'new_tenants_period': new_tenants,
                'tenant_growth_rate': self._calculate_growth_rate(total_tenants, new_tenants)
            },
            'revenue_metrics': revenue_stats,
            'performance_metrics': performance_stats,
            'top_tenants': top_tenants,
            'period': period.value,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        }
    
    def get_usage_trends(self, tenant_id: int, metric_type: str, 
                        period: MetricPeriod = MetricPeriod.DAY, 
                        num_periods: int = 30) -> Dict[str, Any]:
        """Get usage trends over time."""
        
        # Generate time series data
        end_date = datetime.now(tz=timezone.utc)
        periods = []
        
        for i in range(num_periods):
            period_end = end_date - timedelta(**{f"{period.value}s": i})
            period_start = self._get_period_start_date(period_end, period)
            
            usage = db.session.query(func.sum(TenantUsage.usage_amount)).filter(
                TenantUsage.tenant_id == tenant_id,
                TenantUsage.usage_type == metric_type,
                TenantUsage.usage_date >= period_start,
                TenantUsage.usage_date < period_end
            ).scalar() or 0
            
            periods.append({
                'period': period_start.strftime('%Y-%m-%d %H:%M:%S'),
                'value': float(usage)
            })
        
        # Reverse to get chronological order
        periods.reverse()
        
        # Calculate trend statistics
        values = [p['value'] for p in periods]
        trend_stats = {
            'average': _safe_mean(values) if values else 0,
            'min': min(values) if values else 0,
            'max': max(values) if values else 0,
            'std_dev': _safe_std(values) if values else 0,
            'total': sum(values)
        }
        
        return {
            'metric_type': metric_type,
            'period': period.value,
            'data_points': periods,
            'statistics': trend_stats,
            'generated_at': datetime.now(tz=timezone.utc).isoformat()
        }
    
    def get_comparative_analytics(self, tenant_id: int, 
                                benchmark_type: str = 'plan_peers') -> Dict[str, Any]:
        """Get comparative analytics against benchmarks."""
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            return {}
        
        end_date = datetime.now(tz=timezone.utc)
        start_date = end_date - timedelta(days=30)
        
        # Get tenant metrics
        tenant_metrics = self._get_tenant_benchmark_metrics(tenant_id, start_date, end_date)
        
        # Get comparison group
        if benchmark_type == 'plan_peers':
            # Compare with other tenants on same plan
            comparison_tenants = db.session.query(Tenant.id).filter(
                Tenant.plan_id == tenant.plan_id,
                Tenant.id != tenant_id,
                Tenant.status == 'active'
            ).all()
        else:
            # Compare with all active tenants
            comparison_tenants = db.session.query(Tenant.id).filter(
                Tenant.id != tenant_id,
                Tenant.status == 'active'
            ).all()
        
        # Calculate benchmark metrics
        benchmark_metrics = {}
        for comp_tenant_id, in comparison_tenants[:50]:  # Limit for performance
            comp_metrics = self._get_tenant_benchmark_metrics(comp_tenant_id, start_date, end_date)
            for metric, value in comp_metrics.items():
                if metric not in benchmark_metrics:
                    benchmark_metrics[metric] = []
                benchmark_metrics[metric].append(value)
        
        # Calculate percentiles
        comparison_results = {}
        for metric, tenant_value in tenant_metrics.items():
            if metric in benchmark_metrics and benchmark_metrics[metric]:
                values = sorted(benchmark_metrics[metric])
                percentile = self._calculate_percentile(tenant_value, values)
                
                comparison_results[metric] = {
                    'tenant_value': tenant_value,
                    'percentile': percentile,
                    'median': _safe_median(values),
                    'mean': _safe_mean(values),
                    'peer_count': len(values)
                }
        
        return {
            'tenant_id': tenant_id,
            'benchmark_type': benchmark_type,
            'metrics': comparison_results,
            'period_start': start_date.isoformat(),
            'period_end': end_date.isoformat()
        }
    
    def _get_usage_metrics(self, tenant_id: int, start_date: datetime, 
                          end_date: datetime) -> Dict[str, Any]:
        """Get usage metrics for a tenant."""
        
        # API calls
        api_calls = db.session.query(func.sum(TenantUsage.usage_amount)).filter(
            TenantUsage.tenant_id == tenant_id,
            TenantUsage.usage_type == 'api_calls',
            TenantUsage.usage_date >= start_date,
            TenantUsage.usage_date <= end_date
        ).scalar() or 0
        
        # Storage usage
        storage_usage = db.session.query(func.sum(TenantUsage.usage_amount)).filter(
            TenantUsage.tenant_id == tenant_id,
            TenantUsage.usage_type == 'storage',
            TenantUsage.usage_date >= start_date,
            TenantUsage.usage_date <= end_date
        ).scalar() or 0
        
        # Database queries
        db_queries = db.session.query(func.sum(TenantUsage.usage_amount)).filter(
            TenantUsage.tenant_id == tenant_id,
            TenantUsage.usage_type == 'database_queries',
            TenantUsage.usage_date >= start_date,
            TenantUsage.usage_date <= end_date
        ).scalar() or 0
        
        return {
            'api_calls': int(api_calls),
            'storage_gb': float(storage_usage),
            'database_queries': int(db_queries)
        }
    
    def _get_security_metrics(self, tenant_id: int, start_date: datetime, 
                             end_date: datetime) -> Dict[str, Any]:
        """Get security metrics for a tenant."""
        
        # Total security events
        total_events = db.session.query(func.count(SecurityAuditLog.id)).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.timestamp <= end_date
        ).scalar()
        
        # Failed login attempts
        failed_logins = db.session.query(func.count(SecurityAuditLog.id)).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.event_type == 'login_failure',
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.timestamp <= end_date
        ).scalar()
        
        # Security violations
        violations = db.session.query(func.count(SecurityAuditLog.id)).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.event_type == 'security_violation',
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.timestamp <= end_date
        ).scalar()
        
        # Unique IP addresses
        unique_ips = db.session.query(func.count(func.distinct(SecurityAuditLog.ip_address))).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.timestamp <= end_date,
            SecurityAuditLog.ip_address.isnot(None)
        ).scalar()
        
        return {
            'total_security_events': total_events,
            'failed_login_attempts': failed_logins,
            'security_violations': violations,
            'unique_ip_addresses': unique_ips,
            'security_score': self._calculate_security_score(total_events, violations, failed_logins)
        }
    
    def _get_billing_metrics(self, tenant_id: int, start_date: datetime, 
                            end_date: datetime) -> Dict[str, Any]:
        """Get billing metrics for a tenant."""
        
        subscription = db.session.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status == 'active'
        ).first()
        
        if not subscription:
            return {
                'monthly_revenue': 0,
                'usage_charges': 0,
                'total_revenue': 0,
                'subscription_status': 'none'
            }
        
        # Calculate usage charges
        usage_charges = db.session.query(func.sum(TenantUsage.total_cost)).filter(
            TenantUsage.tenant_id == tenant_id,
            TenantUsage.usage_date >= start_date,
            TenantUsage.usage_date <= end_date
        ).scalar() or 0
        
        return {
            'monthly_revenue': float(subscription.monthly_amount or 0),
            'usage_charges': float(usage_charges),
            'total_revenue': float(subscription.monthly_amount or 0) + float(usage_charges),
            'subscription_status': subscription.status,
            'current_period_end': subscription.current_period_end.isoformat() if subscription.current_period_end else None
        }
    
    def _get_platform_revenue_metrics(self, start_date: datetime, 
                                     end_date: datetime) -> Dict[str, Any]:
        """Get platform-wide revenue metrics."""
        
        # Monthly recurring revenue
        active_subscriptions = db.session.query(TenantSubscription).filter(
            TenantSubscription.status == 'active'
        ).all()
        
        mrr = sum(float(sub.monthly_amount or 0) for sub in active_subscriptions)
        
        # Usage-based revenue
        usage_revenue = db.session.query(func.sum(TenantUsage.total_cost)).filter(
            TenantUsage.usage_date >= start_date,
            TenantUsage.usage_date <= end_date
        ).scalar() or 0
        
        # Revenue by plan
        revenue_by_plan = {}
        for subscription in active_subscriptions:
            plan = subscription.plan_id
            if plan not in revenue_by_plan:
                revenue_by_plan[plan] = 0
            revenue_by_plan[plan] += float(subscription.monthly_amount or 0)
        
        return {
            'monthly_recurring_revenue': mrr,
            'usage_based_revenue': float(usage_revenue),
            'total_revenue': mrr + float(usage_revenue),
            'revenue_by_plan': revenue_by_plan,
            'active_subscriptions': len(active_subscriptions)
        }
    
    def _get_platform_performance_metrics(self, start_date: datetime, 
                                         end_date: datetime) -> Dict[str, Any]:
        """Get platform performance metrics."""
        
        # Average response time from audit logs
        avg_response_time = db.session.query(func.avg(SecurityAuditLog.processing_time_ms)).filter(
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.timestamp <= end_date,
            SecurityAuditLog.processing_time_ms.isnot(None)
        ).scalar() or 0
        
        # Error rate
        total_events = db.session.query(func.count(SecurityAuditLog.id)).filter(
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.timestamp <= end_date
        ).scalar()
        
        failed_events = db.session.query(func.count(SecurityAuditLog.id)).filter(
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.timestamp <= end_date,
            SecurityAuditLog.success == False
        ).scalar()
        
        error_rate = (failed_events / total_events * 100) if total_events > 0 else 0
        
        return {
            'average_response_time_ms': float(avg_response_time),
            'error_rate_percent': round(error_rate, 2),
            'total_requests': total_events,
            'failed_requests': failed_events
        }
    
    def _get_top_tenants_by_usage(self, start_date: datetime, end_date: datetime, 
                                 limit: int = 10) -> List[Dict[str, Any]]:
        """Get top tenants by usage."""
        
        usage_by_tenant = db.session.query(
            TenantUsage.tenant_id,
            func.sum(TenantUsage.usage_amount).label('total_usage'),
            func.sum(TenantUsage.total_cost).label('total_cost')
        ).filter(
            TenantUsage.usage_date >= start_date,
            TenantUsage.usage_date <= end_date
        ).group_by(TenantUsage.tenant_id).order_by(
            func.sum(TenantUsage.usage_amount).desc()
        ).limit(limit).all()
        
        # Enrich with tenant information
        top_tenants = []
        for tenant_id, total_usage, total_cost in usage_by_tenant:
            tenant = Tenant.query.get(tenant_id)
            if tenant:
                top_tenants.append({
                    'tenant_id': tenant_id,
                    'tenant_name': tenant.name,
                    'tenant_slug': tenant.slug,
                    'plan_id': tenant.plan_id,
                    'total_usage': float(total_usage),
                    'total_cost': float(total_cost or 0)
                })
        
        return top_tenants
    
    def _get_tenant_benchmark_metrics(self, tenant_id: int, start_date: datetime, 
                                     end_date: datetime) -> Dict[str, float]:
        """Get metrics for tenant benchmarking."""
        
        # User activity rate
        total_users = db.session.query(func.count(TenantUser.id)).filter(
            TenantUser.tenant_id == tenant_id,
            TenantUser.is_active == True
        ).scalar()
        
        active_users = db.session.query(func.count(func.distinct(SecurityAuditLog.user_id))).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.user_id.isnot(None)
        ).scalar()
        
        activity_rate = (active_users / total_users * 100) if total_users > 0 else 0
        
        # API usage per user
        api_usage = db.session.query(func.sum(TenantUsage.usage_amount)).filter(
            TenantUsage.tenant_id == tenant_id,
            TenantUsage.usage_type == 'api_calls',
            TenantUsage.usage_date >= start_date
        ).scalar() or 0
        
        api_per_user = (api_usage / total_users) if total_users > 0 else 0
        
        # Revenue per user
        subscription = db.session.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status == 'active'
        ).first()
        
        revenue_per_user = 0
        if subscription and total_users > 0:
            revenue_per_user = float(subscription.monthly_amount or 0) / total_users
        
        return {
            'user_activity_rate': activity_rate,
            'api_calls_per_user': api_per_user,
            'revenue_per_user': revenue_per_user,
            'total_users': total_users
        }
    
    def _calculate_percentile(self, value: float, sorted_values: List[float]) -> float:
        """Calculate percentile of value in sorted list."""
        if not sorted_values:
            return 0
        
        count = sum(1 for v in sorted_values if v <= value)
        return (count / len(sorted_values)) * 100
    
    def _calculate_security_score(self, total_events: int, violations: int, 
                                 failed_logins: int) -> float:
        """Calculate security health score (0-100)."""
        if total_events == 0:
            return 100  # No events = perfect security
        
        violation_rate = violations / total_events
        failed_login_rate = failed_logins / total_events
        
        # Simple scoring algorithm
        score = 100 - (violation_rate * 50) - (failed_login_rate * 30)
        return max(0, min(100, score))
    
    def _calculate_growth_rate(self, total: int, new: int) -> float:
        """Calculate growth rate percentage."""
        if total == 0 or new == 0:
            return 0
        
        previous = total - new
        if previous == 0:
            return 100  # All growth
        
        return (new / previous) * 100
    
    def _get_period_start_date(self, end_date: datetime, period: MetricPeriod) -> datetime:
        """Get start date for a period."""
        if period == MetricPeriod.HOUR:
            return end_date - timedelta(hours=1)
        elif period == MetricPeriod.DAY:
            return end_date - timedelta(days=1)
        elif period == MetricPeriod.WEEK:
            return end_date - timedelta(weeks=1)
        elif period == MetricPeriod.MONTH:
            return end_date - timedelta(days=30)
        elif period == MetricPeriod.QUARTER:
            return end_date - timedelta(days=90)
        elif period == MetricPeriod.YEAR:
            return end_date - timedelta(days=365)
        else:
            return end_date - timedelta(days=30)


class AnalyticsDashboardView(BaseView):
    """PgAppForge view for analytics dashboard."""
    
    route_base = "/analytics"
    default_view = "dashboard"
    
    def __init__(self):
        self.analytics_engine = TenantAnalyticsEngine()
        super().__init__()
    
    @expose("/dependencies")
    @has_access
    def dependencies_status(self):
        """Show analytics dependencies status."""
        deps = _check_analytics_dependencies()
        
        status_info = {
            'dependencies': deps,
            'recommendations': [],
            'performance_impact': 'minimal'
        }
        
        if not deps['numpy']:
            status_info['recommendations'].append(
                'Install numpy for better performance: pip install numpy'
            )
        
        if not deps['pandas']:
            status_info['recommendations'].append(
                'Install pandas for advanced data manipulation: pip install pandas'
            )
        
        if not deps['numpy'] or not deps['pandas']:
            status_info['performance_impact'] = 'moderate'
            status_info['message'] = 'Analytics are running with Python fallback implementations. ' \
                                   'Performance may be slower for large datasets.'
        else:
            status_info['message'] = 'All analytics dependencies are available for optimal performance.'
        
        return jsonify(status_info)
    
    @expose("/")
    @has_access
    @require_tenant_context()
    def dashboard(self):
        """Main analytics dashboard."""
        tenant_id = get_current_tenant_id()
        
        # Get overview metrics
        overview = self.analytics_engine.get_tenant_overview(tenant_id)
        
        return self.render_template(
            'analytics/dashboard.html',
            overview=overview,
            tenant_id=tenant_id
        )
    
    @expose("/api/overview")
    @has_access
    @require_tenant_context()
    def api_overview(self):
        """API endpoint for overview metrics."""
        tenant_id = get_current_tenant_id()
        period = request.args.get('period', 'month')
        
        try:
            period_enum = MetricPeriod(period)
        except ValueError:
            period_enum = MetricPeriod.MONTH
        
        overview = self.analytics_engine.get_tenant_overview(tenant_id, period_enum)
        return jsonify(overview)
    
    @expose("/api/usage-trends")
    @has_access
    @require_tenant_context()
    def api_usage_trends(self):
        """API endpoint for usage trends."""
        tenant_id = get_current_tenant_id()
        metric_type = request.args.get('metric', 'api_calls')
        period = request.args.get('period', 'day')
        num_periods = int(request.args.get('periods', '30'))
        
        try:
            period_enum = MetricPeriod(period)
        except ValueError:
            period_enum = MetricPeriod.DAY
        
        trends = self.analytics_engine.get_usage_trends(
            tenant_id, metric_type, period_enum, num_periods
        )
        return jsonify(trends)
    
    @expose("/api/comparative")
    @has_access
    @require_tenant_context()
    def api_comparative(self):
        """API endpoint for comparative analytics."""
        tenant_id = get_current_tenant_id()
        benchmark_type = request.args.get('benchmark', 'plan_peers')
        
        comparative = self.analytics_engine.get_comparative_analytics(
            tenant_id, benchmark_type
        )
        return jsonify(comparative)
    
    @expose("/reports")
    @has_access
    @require_tenant_context()
    def reports(self):
        """Analytics reports page."""
        tenant_id = get_current_tenant_id()
        return self.render_template(
            'analytics/reports.html',
            tenant_id=tenant_id
        )


class PlatformAnalyticsView(BaseView):
    """Platform-wide analytics for administrators."""
    
    route_base = "/platform-analytics"
    default_view = "overview"
    
    def __init__(self):
        self.analytics_engine = TenantAnalyticsEngine()
        super().__init__()
    
    @expose("/")
    @has_access  # Add admin role check
    def overview(self):
        """Platform analytics overview."""
        overview = self.analytics_engine.get_platform_overview()
        
        return self.render_template(
            'analytics/platform_overview.html',
            overview=overview
        )
    
    @expose("/api/platform-metrics")
    @has_access
    def api_platform_metrics(self):
        """API endpoint for platform metrics."""
        period = request.args.get('period', 'month')
        
        try:
            period_enum = MetricPeriod(period)
        except ValueError:
            period_enum = MetricPeriod.MONTH
        
        overview = self.analytics_engine.get_platform_overview(period_enum)
        return jsonify(overview)


# Create analytics blueprint
analytics_bp = Blueprint('analytics_api', __name__, url_prefix='/api/analytics')


@analytics_bp.route('/health')
def analytics_health():
    """Health check for analytics system."""
    deps = _check_analytics_dependencies()
    
    # Determine overall health based on dependency availability
    health_status = 'healthy'
    if not deps['numpy'] and not deps['pandas']:
        health_status = 'degraded'  # Still functional but with reduced performance
    
    return jsonify({
        'status': health_status,
        'timestamp': datetime.now(tz=timezone.utc).isoformat(),
        'analytics_engine': 'operational',
        'dependencies': deps,
        'fallback_mode': not (deps['numpy'] and deps['pandas']),
        'performance_notes': 'Using Python fallbacks - consider installing numpy and pandas for better performance' 
                           if not (deps['numpy'] and deps['pandas']) else 'Optimal configuration'
    })


def initialize_analytics_system(app):
    """Initialize the analytics and reporting system."""
    log.info("Initializing advanced analytics and reporting system...")
    
    # Initialize analytics engine
    analytics_engine = TenantAnalyticsEngine()
    
    # Register analytics blueprint
    app.register_blueprint(analytics_bp)
    
    # Store in app extensions
    app.extensions['analytics_engine'] = analytics_engine
    
    log.info("Advanced analytics and reporting system initialized successfully")