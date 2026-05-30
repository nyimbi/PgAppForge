"""
Multi-Tenant Resource Isolation and Throttling System.

This module provides resource monitoring, limits enforcement, and throttling
for multi-tenant SaaS applications to ensure fair resource usage.
"""

import logging
import threading
import time
import psutil
import os
from functools import wraps
from typing import Dict, Optional, Any, List, Callable, Tuple
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum

from flask import current_app, g, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import redis
import json

log = logging.getLogger(__name__)


class ResourceType(Enum):
    """Types of resources that can be monitored and limited."""
    MEMORY = "memory"
    CPU = "cpu"
    STORAGE = "storage"
    API_CALLS = "api_calls"
    DATABASE_QUERIES = "database_queries"
    CONCURRENT_USERS = "concurrent_users"
    BACKGROUND_JOBS = "background_jobs"
    FILE_UPLOADS = "file_uploads"


class LimitAction(Enum):
    """Actions to take when limits are exceeded."""
    WARN = "warn"
    THROTTLE = "throttle"
    REJECT = "reject"
    SUSPEND = "suspend"


@dataclass
class ResourceLimit:
    """Resource limit configuration."""
    resource_type: ResourceType
    limit_value: float
    warning_threshold: float  # Percentage (0.8 = 80%)
    time_window: int  # Seconds
    action: LimitAction
    custom_message: Optional[str] = None


@dataclass
class ResourceUsage:
    """Current resource usage information."""
    tenant_id: int
    resource_type: ResourceType
    current_usage: float
    limit_value: float
    usage_percentage: float
    time_window_start: datetime
    last_updated: datetime
    is_warning: bool
    is_over_limit: bool


class TenantResourceMonitor:
    """Monitor resource usage for individual tenants."""
    
    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self._usage_data = defaultdict(dict)  # tenant_id -> resource_type -> usage_info
        self._time_windows = defaultdict(dict)  # tenant_id -> resource_type -> time_window_data
        self._lock = threading.RLock()
        self._monitoring_active = True
        self._process = psutil.Process()
        
        # Start monitoring thread
        self._monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self._monitor_thread.start()
    
    def track_resource_usage(self, tenant_id: int, resource_type: ResourceType, 
                           usage_amount: float, metadata: Dict[str, Any] = None):
        """Track resource usage for a tenant."""
        if not self._monitoring_active:
            return
        
        current_time = datetime.now(tz=timezone.utc)
        
        with self._lock:
            # Initialize tenant data if not exists
            if tenant_id not in self._usage_data:
                self._usage_data[tenant_id] = {}
                self._time_windows[tenant_id] = {}
            
            # Get or create resource tracking
            resource_key = resource_type.value
            if resource_key not in self._usage_data[tenant_id]:
                self._usage_data[tenant_id][resource_key] = {
                    'total_usage': 0.0,
                    'current_usage': 0.0,
                    'peak_usage': 0.0,
                    'usage_history': deque(maxlen=1000),
                    'last_reset': current_time,
                    'violation_count': 0
                }
                self._time_windows[tenant_id][resource_key] = deque(maxlen=1000)
            
            # Update usage
            usage_info = self._usage_data[tenant_id][resource_key]
            time_window = self._time_windows[tenant_id][resource_key]
            
            # For cumulative resources (storage, api calls)
            if resource_type in [ResourceType.STORAGE, ResourceType.API_CALLS, 
                               ResourceType.DATABASE_QUERIES, ResourceType.FILE_UPLOADS]:
                usage_info['total_usage'] += usage_amount
                usage_info['current_usage'] = usage_info['total_usage']
            else:
                # For instantaneous resources (memory, cpu, concurrent users)
                usage_info['current_usage'] = usage_amount
            
            usage_info['peak_usage'] = max(usage_info['peak_usage'], usage_info['current_usage'])
            
            # Track in time window
            time_window.append({
                'timestamp': current_time,
                'usage': usage_amount,
                'metadata': metadata or {}
            })
            
            # Store in Redis for persistence
            if self.redis_client:
                try:
                    redis_key = f"tenant_usage:{tenant_id}:{resource_key}"
                    usage_data = {
                        'current_usage': usage_info['current_usage'],
                        'peak_usage': usage_info['peak_usage'],
                        'total_usage': usage_info['total_usage'],
                        'last_updated': current_time.isoformat(),
                        'violation_count': usage_info['violation_count']
                    }
                    self.redis_client.setex(redis_key, 3600, json.dumps(usage_data, default=str))
                except Exception as e:
                    log.debug(f"Redis usage tracking error: {e}")
    
    def get_current_usage(self, tenant_id: int, resource_type: ResourceType) -> float:
        """Get current usage for a tenant resource."""
        with self._lock:
            resource_key = resource_type.value
            if tenant_id in self._usage_data and resource_key in self._usage_data[tenant_id]:
                return self._usage_data[tenant_id][resource_key]['current_usage']
            return 0.0
    
    def get_usage_in_time_window(self, tenant_id: int, resource_type: ResourceType, 
                                window_seconds: int) -> float:
        """Get usage within a specific time window."""
        current_time = datetime.now(tz=timezone.utc)
        window_start = current_time - timedelta(seconds=window_seconds)
        
        with self._lock:
            resource_key = resource_type.value
            if (tenant_id not in self._time_windows or 
                resource_key not in self._time_windows[tenant_id]):
                return 0.0
            
            time_window = self._time_windows[tenant_id][resource_key]
            
            # Sum usage within time window
            total_usage = 0.0
            for entry in time_window:
                if entry['timestamp'] >= window_start:
                    total_usage += entry['usage']
            
            return total_usage
    
    def reset_usage_counters(self, tenant_id: int, resource_type: ResourceType = None):
        """Reset usage counters for a tenant."""
        current_time = datetime.now(tz=timezone.utc)
        
        with self._lock:
            if tenant_id not in self._usage_data:
                return
            
            if resource_type:
                # Reset specific resource
                resource_key = resource_type.value
                if resource_key in self._usage_data[tenant_id]:
                    usage_info = self._usage_data[tenant_id][resource_key]
                    usage_info['total_usage'] = 0.0
                    usage_info['current_usage'] = 0.0
                    usage_info['peak_usage'] = 0.0
                    usage_info['last_reset'] = current_time
                    
                    if resource_key in self._time_windows[tenant_id]:
                        self._time_windows[tenant_id][resource_key].clear()
            else:
                # Reset all resources for tenant
                for resource_key in self._usage_data[tenant_id]:
                    usage_info = self._usage_data[tenant_id][resource_key]
                    usage_info['total_usage'] = 0.0
                    usage_info['current_usage'] = 0.0
                    usage_info['peak_usage'] = 0.0
                    usage_info['last_reset'] = current_time
                
                for resource_key in self._time_windows[tenant_id]:
                    self._time_windows[tenant_id][resource_key].clear()
    
    def get_tenant_resource_summary(self, tenant_id: int) -> Dict[str, Any]:
        """Get comprehensive resource usage summary for a tenant."""
        with self._lock:
            if tenant_id not in self._usage_data:
                return {}
            
            summary = {}
            for resource_key, usage_info in self._usage_data[tenant_id].items():
                summary[resource_key] = {
                    'current_usage': usage_info['current_usage'],
                    'total_usage': usage_info['total_usage'],
                    'peak_usage': usage_info['peak_usage'],
                    'last_reset': usage_info['last_reset'].isoformat(),
                    'violation_count': usage_info['violation_count']
                }
            
            return summary
    
    def _monitoring_loop(self):
        """Background monitoring loop for system resources."""
        while self._monitoring_active:
            try:
                # Monitor system-level resources
                self._monitor_system_resources()
                time.sleep(30)  # Monitor every 30 seconds
            except Exception as e:
                log.error(f"Error in resource monitoring loop: {e}")
                time.sleep(60)  # Wait longer on error
    
    def _monitor_system_resources(self):
        """Monitor system-level resource usage."""
        try:
            # Get memory usage per tenant (estimated)
            memory_info = self._process.memory_info()
            total_memory_mb = memory_info.rss / 1024 / 1024
            
            # Get CPU usage
            cpu_percent = self._process.cpu_percent()
            
            # Track system resources for active tenants
            from flask_appbuilder.models.tenant_context import get_current_tenant_id
            
            # This would need to be enhanced to track per-tenant usage
            # For now, we track overall system usage
            
            if self.redis_client:
                try:
                    system_stats = {
                        'memory_mb': total_memory_mb,
                        'cpu_percent': cpu_percent,
                        'timestamp': datetime.now(tz=timezone.utc).isoformat()
                    }
                    self.redis_client.setex('system_stats', 300, json.dumps(system_stats))
                except Exception as e:
                    log.debug(f"Redis system stats error: {e}")
                    
        except Exception as e:
            log.debug(f"System resource monitoring error: {e}")
    
    def stop_monitoring(self):
        """Stop the monitoring thread."""
        self._monitoring_active = False


class TenantResourceLimiter:
    """Enforce resource limits and throttling for tenants."""
    
    def __init__(self, monitor: TenantResourceMonitor, redis_client=None):
        self.monitor = monitor
        self.redis_client = redis_client
        self._tenant_limits = {}  # tenant_id -> resource_type -> ResourceLimit
        self._violations = defaultdict(list)  # tenant_id -> [violation_records]
        self._lock = threading.RLock()
    
    def set_tenant_limits(self, tenant_id: int, limits: List[ResourceLimit]):
        """Set resource limits for a tenant."""
        with self._lock:
            if tenant_id not in self._tenant_limits:
                self._tenant_limits[tenant_id] = {}
            
            for limit in limits:
                self._tenant_limits[tenant_id][limit.resource_type] = limit
                log.info(f"Set {limit.resource_type.value} limit for tenant {tenant_id}: {limit.limit_value}")
    
    def check_resource_limit(self, tenant_id: int, resource_type: ResourceType, 
                           usage_amount: float = 0.0) -> Tuple[bool, Optional[str]]:
        """Check if resource usage is within limits."""
        with self._lock:
            if (tenant_id not in self._tenant_limits or 
                resource_type not in self._tenant_limits[tenant_id]):
                return True, None  # No limit set
            
            limit = self._tenant_limits[tenant_id][resource_type]
            
            # Get current usage in time window
            if limit.time_window > 0:
                current_usage = self.monitor.get_usage_in_time_window(
                    tenant_id, resource_type, limit.time_window
                )
            else:
                current_usage = self.monitor.get_current_usage(tenant_id, resource_type)
            
            # Add proposed usage
            total_usage = current_usage + usage_amount
            usage_percentage = total_usage / limit.limit_value if limit.limit_value > 0 else 0
            
            # Check warning threshold
            if usage_percentage >= limit.warning_threshold and usage_percentage < 1.0:
                self._record_warning(tenant_id, resource_type, total_usage, limit.limit_value)
            
            # Check limit exceeded
            if usage_percentage >= 1.0:
                violation_msg = self._record_violation(tenant_id, resource_type, total_usage, limit)
                return False, violation_msg
            
            return True, None
    
    def enforce_limit(self, tenant_id: int, resource_type: ResourceType, 
                     usage_amount: float = 0.0) -> Tuple[bool, Optional[str], Optional[int]]:
        """Enforce resource limits and return action to take."""
        allowed, message = self.check_resource_limit(tenant_id, resource_type, usage_amount)
        
        if allowed:
            return True, None, None
        
        # Get limit configuration
        with self._lock:
            if (tenant_id not in self._tenant_limits or 
                resource_type not in self._tenant_limits[tenant_id]):
                return True, None, None
            
            limit = self._tenant_limits[tenant_id][resource_type]
            action = limit.action
            
            if action == LimitAction.WARN:
                log.warning(f"Resource limit warning for tenant {tenant_id}: {message}")
                return True, message, None
            
            elif action == LimitAction.THROTTLE:
                # Calculate throttle delay
                current_usage = self.monitor.get_current_usage(tenant_id, resource_type)
                over_limit_ratio = current_usage / limit.limit_value if limit.limit_value > 0 else 0
                throttle_seconds = min(int((over_limit_ratio - 1.0) * 10), 30)  # Max 30 seconds
                
                log.warning(f"Throttling tenant {tenant_id} for {resource_type.value}: {message}")
                return False, message, throttle_seconds
            
            elif action == LimitAction.REJECT:
                log.warning(f"Rejecting request for tenant {tenant_id}: {message}")
                return False, message, None
            
            elif action == LimitAction.SUSPEND:
                self._suspend_tenant(tenant_id, resource_type, message)
                return False, message, None
        
        return False, message, None
    
    def get_tenant_usage_status(self, tenant_id: int) -> List[ResourceUsage]:
        """Get current usage status for all tenant resources."""
        usage_statuses = []
        
        with self._lock:
            if tenant_id not in self._tenant_limits:
                return usage_statuses
            
            current_time = datetime.now(tz=timezone.utc)
            
            for resource_type, limit in self._tenant_limits[tenant_id].items():
                if limit.time_window > 0:
                    current_usage = self.monitor.get_usage_in_time_window(
                        tenant_id, resource_type, limit.time_window
                    )
                    time_window_start = current_time - timedelta(seconds=limit.time_window)
                else:
                    current_usage = self.monitor.get_current_usage(tenant_id, resource_type)
                    time_window_start = current_time
                
                usage_percentage = current_usage / limit.limit_value if limit.limit_value > 0 else 0
                
                usage_status = ResourceUsage(
                    tenant_id=tenant_id,
                    resource_type=resource_type,
                    current_usage=current_usage,
                    limit_value=limit.limit_value,
                    usage_percentage=usage_percentage,
                    time_window_start=time_window_start,
                    last_updated=current_time,
                    is_warning=usage_percentage >= limit.warning_threshold,
                    is_over_limit=usage_percentage >= 1.0
                )
                
                usage_statuses.append(usage_status)
        
        return usage_statuses
    
    def _record_warning(self, tenant_id: int, resource_type: ResourceType, 
                       usage: float, limit: float):
        """Record a resource usage warning."""
        warning_msg = (f"Tenant {tenant_id} approaching {resource_type.value} limit: "
                      f"{usage:.2f}/{limit:.2f}")
        log.warning(warning_msg)
        
        # Store in Redis for monitoring
        if self.redis_client:
            try:
                warning_key = f"tenant_warnings:{tenant_id}"
                warning_data = {
                    'resource_type': resource_type.value,
                    'usage': usage,
                    'limit': limit,
                    'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                    'message': warning_msg
                }
                self.redis_client.lpush(warning_key, json.dumps(warning_data, default=str))
                self.redis_client.ltrim(warning_key, 0, 99)  # Keep last 100 warnings
                self.redis_client.expire(warning_key, 86400)  # 24 hour TTL
            except Exception as e:
                log.debug(f"Redis warning storage error: {e}")
    
    def _record_violation(self, tenant_id: int, resource_type: ResourceType, 
                         usage: float, limit: ResourceLimit) -> str:
        """Record a resource limit violation."""
        violation_msg = (limit.custom_message or 
                        f"Resource limit exceeded for {resource_type.value}: "
                        f"{usage:.2f}/{limit.limit_value:.2f}")
        
        violation_record = {
            'tenant_id': tenant_id,
            'resource_type': resource_type.value,
            'usage': usage,
            'limit': limit.limit_value,
            'action': limit.action.value,
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'message': violation_msg
        }
        
        with self._lock:
            self._violations[tenant_id].append(violation_record)
            # Keep only recent violations
            if len(self._violations[tenant_id]) > 1000:
                self._violations[tenant_id] = self._violations[tenant_id][-500:]
        
        log.error(f"Resource violation for tenant {tenant_id}: {violation_msg}")
        
        # Store in Redis
        if self.redis_client:
            try:
                violation_key = f"tenant_violations:{tenant_id}"
                self.redis_client.lpush(violation_key, json.dumps(violation_record, default=str))
                self.redis_client.ltrim(violation_key, 0, 999)  # Keep last 1000 violations
                self.redis_client.expire(violation_key, 2592000)  # 30 day TTL
            except Exception as e:
                log.debug(f"Redis violation storage error: {e}")
        
        return violation_msg
    
    def _suspend_tenant(self, tenant_id: int, resource_type: ResourceType, message: str):
        """Suspend a tenant due to resource violations."""
        log.critical(f"SUSPENDING tenant {tenant_id} due to {resource_type.value} violation: {message}")
        
        # Actual tenant suspension implementation
        try:
            from flask_appbuilder.models.tenant_models import Tenant
            from flask_appbuilder import db
            
            # Update tenant status in database
            tenant = db.session.query(Tenant).get(tenant_id)
            if tenant:
                # Store previous status for potential restoration
                previous_status = tenant.status
                tenant.status = 'suspended'
                
                # Add suspension metadata
                suspension_metadata = {
                    'previous_status': previous_status,
                    'suspension_reason': message,
                    'resource_type': resource_type.value,
                    'suspended_at': datetime.now(tz=timezone.utc).isoformat(),
                    'suspended_by': 'resource_limiter'
                }
                
                # Update tenant metadata
                if not tenant.metadata:
                    tenant.metadata = {}
                tenant.metadata['suspension'] = suspension_metadata
                
                db.session.commit()
                log.info(f"Tenant {tenant_id} status updated to suspended in database")
                
                # Send notification to tenant admins
                self._send_suspension_notification(tenant, message)
            else:
                log.error(f"Tenant {tenant_id} not found in database for suspension")
                
        except Exception as db_error:
            log.error(f"Failed to suspend tenant {tenant_id} in database: {db_error}")
            # Fallback to Redis-based suspension tracking
            
        # Store suspension info in Redis for fast lookups
        if self.redis_client:
            try:
                suspension_key = f"tenant_suspensions:{tenant_id}"
                suspension_data = {
                    'resource_type': resource_type.value,
                    'reason': message,
                    'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                    'status': 'suspended',
                    'expires_at': (datetime.now(tz=timezone.utc) + timedelta(hours=24)).isoformat()  # Auto-review after 24h
                }
                self.redis_client.setex(suspension_key, 86400, json.dumps(suspension_data, default=str))
                
                # Also set a quick lookup flag
                self.redis_client.setex(f"suspended:{tenant_id}", 86400, "1")
                
            except Exception as e:
                log.debug(f"Redis suspension storage error: {e}")
    
    def _send_suspension_notification(self, tenant, message: str):
        """Send suspension notification to tenant administrators."""
        try:
            # This would integrate with notification system
            # For now, log the notification that would be sent
            notification_data = {
                'tenant_id': tenant.id,
                'tenant_name': tenant.name,
                'reason': message,
                'action_required': 'Contact support to resolve resource limit violation',
                'suspended_at': datetime.now(tz=timezone.utc).isoformat()
            }
            
            log.warning(f"TENANT SUSPENSION NOTIFICATION: {json.dumps(notification_data)}")
            
            # In production, this would send emails/alerts to:
            # - Tenant administrators
            # - System administrators
            # - Billing system (if applicable)
            
        except Exception as e:
            log.error(f"Failed to send suspension notification: {e}")
    
    def is_tenant_suspended(self, tenant_id: int) -> bool:
        """Check if a tenant is currently suspended."""
        # First check Redis for fast lookup
        if self.redis_client:
            try:
                if self.redis_client.get(f"suspended:{tenant_id}"):
                    return True
            except Exception as e:
                log.debug(f"Redis suspension check error: {e}")
        
        # Fallback to database check
        try:
            from flask_appbuilder.models.tenant_models import Tenant
            from flask_appbuilder import db
            
            tenant = db.session.query(Tenant).get(tenant_id)
            return tenant and tenant.status == 'suspended'
        except Exception as e:
            log.error(f"Database suspension check error: {e}")
            return False
    
    def unsuspend_tenant(self, tenant_id: int, reason: str = "Manual restoration") -> bool:
        """Restore a suspended tenant."""
        try:
            from flask_appbuilder.models.tenant_models import Tenant
            from flask_appbuilder import db
            
            tenant = db.session.query(Tenant).get(tenant_id)
            if tenant and tenant.status == 'suspended':
                # Restore previous status if available
                previous_status = 'active'  # Default
                if tenant.metadata and 'suspension' in tenant.metadata:
                    suspension_data = tenant.metadata['suspension']
                    previous_status = suspension_data.get('previous_status', 'active')
                    
                    # Add restoration metadata
                    suspension_data['restored_at'] = datetime.now(tz=timezone.utc).isoformat()
                    suspension_data['restoration_reason'] = reason
                
                tenant.status = previous_status
                db.session.commit()
                
                # Remove from Redis
                if self.redis_client:
                    try:
                        self.redis_client.delete(f"suspended:{tenant_id}")
                        self.redis_client.delete(f"tenant_suspensions:{tenant_id}")
                    except Exception as e:
                        log.debug(f"Redis suspension cleanup error: {e}")
                
                log.info(f"Tenant {tenant_id} restored from suspension to {previous_status}")
                return True
            
            return False
            
        except Exception as e:
            log.error(f"Failed to unsuspend tenant {tenant_id}: {e}")
            return False


class TenantRateLimiter:
    """Rate limiting for tenant API endpoints."""
    
    def __init__(self, limiter: Limiter, resource_limiter: TenantResourceLimiter):
        self.limiter = limiter
        self.resource_limiter = resource_limiter
    
    def limit_tenant_requests(self, rate: str, resource_type: ResourceType = ResourceType.API_CALLS):
        """Decorator for tenant-aware rate limiting."""
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                tenant_id = getattr(g, 'current_tenant_id', None)
                if not tenant_id:
                    return jsonify({'error': 'No tenant context'}), 400
                
                # Check resource limits
                allowed, message, throttle_seconds = self.resource_limiter.enforce_limit(
                    tenant_id, resource_type, 1.0
                )
                
                if not allowed:
                    if throttle_seconds:
                        # Instead of blocking with sleep, return a rate limit response
                        # with appropriate retry-after header
                        response = jsonify({
                            'error': 'Rate limited - please slow down',
                            'message': message,
                            'tenant_id': tenant_id,
                            'retry_after_seconds': throttle_seconds
                        })
                        response.status_code = 429
                        response.headers['Retry-After'] = str(throttle_seconds)
                        return response
                    else:
                        return jsonify({
                            'error': 'Resource limit exceeded',
                            'message': message,
                            'tenant_id': tenant_id
                        }), 429
                
                # Track the API call
                self.resource_limiter.monitor.track_resource_usage(
                    tenant_id, resource_type, 1.0, 
                    {'endpoint': request.endpoint, 'method': request.method}
                )
                
                return func(*args, **kwargs)
            
            # Apply Flask-Limiter rate limiting with tenant-aware key
            @self.limiter.limit(rate, key_func=lambda: f"tenant_{getattr(g, 'current_tenant_id', 'unknown')}")
            @wraps(wrapper)
            def rate_limited_wrapper(*args, **kwargs):
                return wrapper(*args, **kwargs)
            
            return rate_limited_wrapper
        return decorator


# Decorator for resource tracking
def track_tenant_resource(resource_type: ResourceType, usage_amount: float = 1.0):
    """Decorator to track tenant resource usage."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            tenant_id = getattr(g, 'current_tenant_id', None)
            if tenant_id:
                # Get global resource monitor
                monitor = get_resource_monitor()
                monitor.track_resource_usage(tenant_id, resource_type, usage_amount)
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


def enforce_tenant_limit(resource_type: ResourceType, usage_amount: float = 1.0):
    """Decorator to enforce tenant resource limits."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            tenant_id = getattr(g, 'current_tenant_id', None)
            if tenant_id:
                # Get global resource limiter
                limiter = get_resource_limiter()
                allowed, message, throttle_seconds = limiter.enforce_limit(
                    tenant_id, resource_type, usage_amount
                )
                
                if not allowed:
                    if throttle_seconds:
                        # Return rate limit response instead of blocking
                        response = jsonify({
                            'error': 'Rate limited - please slow down',
                            'message': message,
                            'resource_type': resource_type.value,
                            'retry_after_seconds': throttle_seconds
                        })
                        response.status_code = 429
                        response.headers['Retry-After'] = str(throttle_seconds)
                        return response
                    else:
                        return jsonify({
                            'error': 'Resource limit exceeded',
                            'message': message,
                            'resource_type': resource_type.value
                        }), 429
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Global instances
_resource_monitor = None
_resource_limiter = None
_rate_limiter = None
_isolation_lock = threading.Lock()


def get_resource_monitor() -> TenantResourceMonitor:
    """Get global resource monitor instance."""
    global _resource_monitor
    if _resource_monitor is None:
        with _isolation_lock:
            if _resource_monitor is None:
                redis_client = None
                if current_app and current_app.config.get('REDIS_URL'):
                    try:
                        redis_client = redis.from_url(current_app.config['REDIS_URL'])
                    except Exception as e:
                        log.warning(f"Failed to connect to Redis for resource monitoring: {e}")
                
                _resource_monitor = TenantResourceMonitor(redis_client)
    return _resource_monitor


def get_resource_limiter() -> TenantResourceLimiter:
    """Get global resource limiter instance."""
    global _resource_limiter
    if _resource_limiter is None:
        with _isolation_lock:
            if _resource_limiter is None:
                monitor = get_resource_monitor()
                redis_client = monitor.redis_client
                _resource_limiter = TenantResourceLimiter(monitor, redis_client)
    return _resource_limiter


def get_rate_limiter() -> Optional[TenantRateLimiter]:
    """Get global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None and current_app:
        with _isolation_lock:
            if _rate_limiter is None:
                # This would be initialized by the Flask-Limiter extension
                limiter = current_app.extensions.get('limiter')
                if limiter:
                    resource_limiter = get_resource_limiter()
                    _rate_limiter = TenantRateLimiter(limiter, resource_limiter)
    return _rate_limiter


def initialize_resource_isolation(app):
    """Initialize resource isolation and monitoring."""
    log.info("Initializing tenant resource isolation system...")
    
    # Initialize global instances
    monitor = get_resource_monitor()
    limiter = get_resource_limiter()
    
    # Register middleware to check for suspended tenants
    app.before_request(check_tenant_suspension_middleware)
    
    # Store in app extensions
    app.extensions['tenant_resource_monitor'] = monitor
    app.extensions['tenant_resource_limiter'] = limiter
    
    log.info("Tenant resource isolation system initialized successfully")


def check_tenant_suspension_middleware():
    """Middleware to check if current tenant is suspended."""
    from flask import request, jsonify
    from flask_appbuilder.models.tenant_context import get_current_tenant_id
    
    # Skip suspension checks for certain paths
    skip_paths = ['/health', '/status', '/static/', '/api/health', '/login', '/logout']
    if any(request.path.startswith(path) for path in skip_paths):
        return None
    
    # Check if tenant is suspended
    tenant_id = get_current_tenant_id()
    if tenant_id:
        limiter = get_resource_limiter()
        if limiter.is_tenant_suspended(tenant_id):
            log.warning(f"Blocked request from suspended tenant {tenant_id}: {request.path}")
            
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({
                    'error': 'Tenant suspended',
                    'message': 'Your tenant account has been suspended due to resource violations. Please contact support.',
                    'tenant_id': tenant_id,
                    'status': 'suspended'
                }), 403
            else:
                # For web requests, could redirect to a suspension notice page
                # For now, return JSON response
                return jsonify({
                    'error': 'Tenant suspended',
                    'message': 'Your tenant account has been suspended due to resource violations. Please contact support.',
                    'tenant_id': tenant_id,
                    'status': 'suspended'
                }), 403
    
    return None


def setup_default_tenant_limits(tenant_id: int, plan_id: str):
    """Set up default resource limits based on tenant plan."""
    limiter = get_resource_limiter()
    
    # Default limits by plan
    plan_limits = {
        'free': [
            ResourceLimit(ResourceType.API_CALLS, 1000, 0.8, 3600, LimitAction.REJECT,
                         "Free plan API limit exceeded. Upgrade to continue."),
            ResourceLimit(ResourceType.STORAGE, 100, 0.8, 0, LimitAction.REJECT,
                         "Free plan storage limit exceeded. Upgrade for more storage."),
            ResourceLimit(ResourceType.CONCURRENT_USERS, 3, 0.8, 0, LimitAction.REJECT,
                         "Free plan user limit exceeded. Upgrade to add more users."),
        ],
        'starter': [
            ResourceLimit(ResourceType.API_CALLS, 10000, 0.8, 3600, LimitAction.THROTTLE),
            ResourceLimit(ResourceType.STORAGE, 1024, 0.8, 0, LimitAction.WARN),
            ResourceLimit(ResourceType.CONCURRENT_USERS, 10, 0.8, 0, LimitAction.REJECT),
            ResourceLimit(ResourceType.DATABASE_QUERIES, 50000, 0.8, 3600, LimitAction.THROTTLE),
        ],
        'professional': [
            ResourceLimit(ResourceType.API_CALLS, 100000, 0.8, 3600, LimitAction.THROTTLE),
            ResourceLimit(ResourceType.STORAGE, 10240, 0.8, 0, LimitAction.WARN),
            ResourceLimit(ResourceType.CONCURRENT_USERS, 50, 0.8, 0, LimitAction.WARN),
            ResourceLimit(ResourceType.DATABASE_QUERIES, 500000, 0.8, 3600, LimitAction.THROTTLE),
        ],
        'enterprise': [
            # Enterprise has higher limits but still some reasonable bounds
            ResourceLimit(ResourceType.API_CALLS, 1000000, 0.9, 3600, LimitAction.WARN),
            ResourceLimit(ResourceType.STORAGE, 102400, 0.9, 0, LimitAction.WARN),
            ResourceLimit(ResourceType.CONCURRENT_USERS, 500, 0.9, 0, LimitAction.WARN),
            ResourceLimit(ResourceType.DATABASE_QUERIES, 5000000, 0.9, 3600, LimitAction.WARN),
        ]
    }
    
    limits = plan_limits.get(plan_id, plan_limits['free'])
    limiter.set_tenant_limits(tenant_id, limits)
    
    log.info(f"Set up {len(limits)} resource limits for tenant {tenant_id} on {plan_id} plan")