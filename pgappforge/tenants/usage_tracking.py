"""
Usage Tracking and Metering System.

Automatic usage monitoring and metering for multi-tenant SaaS applications.
Tracks API calls, storage usage, user activity, and other metrics for billing
and quota enforcement.
"""

import logging
from datetime import datetime, date, timedelta, timezone
from functools import wraps
from typing import Dict, Any, Optional, Callable, List
import threading
from threading import Thread
from queue import Queue, Empty
import time

from flask import request, g, current_app
from flask_login import current_user

from .billing import get_billing_service
from ..models.tenant_context import get_current_tenant_id

log = logging.getLogger(__name__)


class UsageTracker:
    """
    Centralized usage tracking system.
    
    Monitors resource usage across the application and provides
    real-time usage data for billing and quota enforcement.
    """
    
    def __init__(self, async_processing: bool = True):
        """Initialize usage tracker"""
        self.async_processing = async_processing
        self._usage_queue = Queue() if async_processing else None
        self._worker_thread = None
        self._stop_worker = False
        self._metrics_cache = {}
        
        if async_processing:
            self._start_worker_thread()
    
    def track(self, tenant_id: int, usage_type: str, amount: float, 
             unit: str, metadata: Dict[str, Any] = None):
        """Track usage with async processing"""
        if not tenant_id:
            log.warning("Cannot track usage without tenant_id")
            return
        
        usage_data = {
            'tenant_id': tenant_id,
            'usage_type': usage_type,
            'amount': amount,
            'unit': unit,
            'metadata': metadata or {},
            'timestamp': datetime.now(tz=timezone.utc)
        }
        
        if self.async_processing and self._usage_queue:
            try:
                self._usage_queue.put(usage_data, block=False)
            except:
                # Queue full, process synchronously
                log.warning("Usage tracking queue full, processing synchronously")
                self._process_usage(usage_data)
        else:
            self._process_usage(usage_data)
    
    def track_api_call(self, tenant_id: int, endpoint: str, method: str = 'GET',
                      response_time: float = None, status_code: int = None):
        """Track API call usage"""
        metadata = {
            'endpoint': endpoint,
            'method': method,
            'user_id': getattr(current_user, 'id', None) if current_user.is_authenticated else None,
            'ip_address': request.remote_addr if request else None
        }
        
        if response_time is not None:
            metadata['response_time_ms'] = response_time
        
        if status_code is not None:
            metadata['status_code'] = status_code
        
        self.track(tenant_id, 'api_calls', 1.0, 'calls', metadata)
    
    def track_storage_usage(self, tenant_id: int, size_bytes: int, 
                           operation: str = 'upload', file_type: str = None):
        """Track storage usage"""
        size_gb = size_bytes / (1024 ** 3)  # Convert to GB
        
        metadata = {
            'operation': operation,
            'size_bytes': size_bytes,
            'user_id': getattr(current_user, 'id', None) if current_user.is_authenticated else None
        }
        
        if file_type:
            metadata['file_type'] = file_type
        
        # For storage, track cumulative usage
        if operation in ('upload', 'create'):
            self.track(tenant_id, 'storage_gb', size_gb, 'gb', metadata)
        elif operation == 'delete':
            self.track(tenant_id, 'storage_gb', -size_gb, 'gb', metadata)  # Negative for deletions
    
    def track_user_activity(self, tenant_id: int, activity_type: str, 
                           user_id: int = None, details: Dict[str, Any] = None):
        """Track user activity"""
        metadata = {
            'activity_type': activity_type,
            'user_id': user_id or (getattr(current_user, 'id', None) if current_user.is_authenticated else None)
        }
        
        if details:
            metadata.update(details)
        
        self.track(tenant_id, 'user_activity', 1.0, 'actions', metadata)
    
    def track_database_usage(self, tenant_id: int, operation: str, table_name: str, 
                            record_count: int = 1):
        """Track database operations"""
        metadata = {
            'operation': operation,  # insert, update, delete, select
            'table_name': table_name,
            'record_count': record_count
        }
        
        self.track(tenant_id, 'database_operations', record_count, 'operations', metadata)
    
    def track_export_usage(self, tenant_id: int, export_format: str, 
                          record_count: int, file_size_bytes: int):
        """Track data export usage"""
        metadata = {
            'export_format': export_format,
            'record_count': record_count,
            'file_size_bytes': file_size_bytes,
            'user_id': getattr(current_user, 'id', None) if current_user.is_authenticated else None
        }
        
        self.track(tenant_id, 'data_exports', 1.0, 'exports', metadata)
    
    def track_email_usage(self, tenant_id: int, email_type: str, recipient_count: int = 1):
        """Track email sending usage"""
        metadata = {
            'email_type': email_type,  # notification, alert, marketing, etc.
            'recipient_count': recipient_count
        }
        
        self.track(tenant_id, 'emails_sent', recipient_count, 'emails', metadata)
    
    def get_realtime_usage(self, tenant_id: int, usage_type: str, 
                          period_hours: int = 1) -> Dict[str, Any]:
        """Get real-time usage data from cache"""
        cache_key = f"usage:{tenant_id}:{usage_type}:{period_hours}"
        
        if cache_key in self._metrics_cache:
            cached_data = self._metrics_cache[cache_key]
            # Return cached data if less than 5 minutes old
            if (datetime.now(tz=timezone.utc) - cached_data['cached_at']).seconds < 300:
                return cached_data['data']
        
        # Calculate real-time usage
        try:
            from pgappforge import db
            from ..models.tenant_models import TenantUsage
            from sqlalchemy import func
            
            cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=period_hours)
            
            usage_data = db.session.query(
                func.sum(TenantUsage.usage_amount).label('total_usage'),
                func.count(TenantUsage.id).label('usage_count'),
                func.avg(TenantUsage.usage_amount).label('avg_usage'),
                func.max(TenantUsage.usage_amount).label('max_usage')
            ).filter(
                TenantUsage.tenant_id == tenant_id,
                TenantUsage.usage_type == usage_type,
                TenantUsage.created_on >= cutoff_time
            ).first()
            
            result = {
                'total_usage': float(usage_data.total_usage or 0),
                'usage_count': int(usage_data.usage_count or 0),
                'avg_usage': float(usage_data.avg_usage or 0),
                'max_usage': float(usage_data.max_usage or 0),
                'period_hours': period_hours,
                'calculated_at': datetime.now(tz=timezone.utc)
            }
            
            # Cache the result
            self._metrics_cache[cache_key] = {
                'data': result,
                'cached_at': datetime.now(tz=timezone.utc)
            }
            
            return result
            
        except Exception as e:
            log.error(f"Failed to get real-time usage: {e}")
            return {}
    
    def _start_worker_thread(self):
        """Start background worker thread for processing usage data"""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        
        self._stop_worker = False
        self._worker_thread = Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        log.info("Usage tracking worker thread started")
    
    def _worker_loop(self):
        """Background worker loop for processing usage data"""
        billing_service = get_billing_service()
        
        while not self._stop_worker:
            try:
                # Process queued usage data
                usage_data = self._usage_queue.get(timeout=1.0)
                self._process_usage(usage_data)
                self._usage_queue.task_done()
                
            except Empty:
                continue
            except Exception as e:
                log.error(f"Error in usage tracking worker: {e}")
                time.sleep(1)  # Brief pause on error
    
    def _process_usage(self, usage_data: Dict[str, Any]):
        """Process individual usage record"""
        try:
            billing_service = get_billing_service()
            
            billing_service.track_usage(
                tenant_id=usage_data['tenant_id'],
                usage_type=usage_data['usage_type'],
                amount=usage_data['amount'],
                unit=usage_data['unit'],
                metadata=usage_data['metadata']
            )
            
        except Exception as e:
            log.error(f"Failed to process usage data: {e}")
    
    def stop_worker(self):
        """Stop the background worker thread"""
        if self._worker_thread:
            self._stop_worker = True
            self._worker_thread.join(timeout=5)
            log.info("Usage tracking worker thread stopped")


# Thread-safe global usage tracker instance
_usage_tracker = None
_usage_tracker_lock = threading.Lock()


def get_usage_tracker() -> UsageTracker:
    """Get thread-safe global usage tracker instance"""
    global _usage_tracker
    
    if _usage_tracker is None:
        with _usage_tracker_lock:
            # Double-checked locking pattern
            if _usage_tracker is None:
                async_processing = current_app.config.get('USAGE_TRACKING_ASYNC', True)
                _usage_tracker = UsageTracker(async_processing=async_processing)
    
    return _usage_tracker


class UsageTrackingMiddleware:
    """
    Flask middleware for automatic usage tracking.
    
    Automatically tracks API calls and request metrics for all
    tenant-aware requests.
    """
    
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize middleware with Flask app"""
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        app.teardown_request(self.teardown_request)
        
        # Store reference in app extensions
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        app.extensions['usage_tracking_middleware'] = self
    
    def before_request(self):
        """Track request start time"""
        g.request_start_time = time.time()
    
    def after_request(self, response):
        """Track API usage after request completion"""
        try:
            # Skip tracking for certain paths
            if self._should_skip_tracking():
                return response
            
            # Get tenant ID from context
            tenant_id = get_current_tenant_id()
            if not tenant_id:
                return response
            
            # Calculate response time
            request_time = None
            if hasattr(g, 'request_start_time'):
                request_time = (time.time() - g.request_start_time) * 1000  # Convert to ms
            
            # Track API call
            usage_tracker = get_usage_tracker()
            usage_tracker.track_api_call(
                tenant_id=tenant_id,
                endpoint=request.endpoint or request.path,
                method=request.method,
                response_time=request_time,
                status_code=response.status_code
            )
            
        except Exception as e:
            log.error(f"Error tracking API usage: {e}")
        
        return response
    
    def teardown_request(self, exception):
        """Clean up after request"""
        if hasattr(g, 'request_start_time'):
            delattr(g, 'request_start_time')
    
    def _should_skip_tracking(self) -> bool:
        """Check if tracking should be skipped for this request"""
        skip_paths = [
            '/health',
            '/status',
            '/_health',
            '/static/',
            '/favicon.ico',
            '/usage/api/'  # Skip tracking for usage API endpoints
        ]
        
        path = request.path
        return any(path.startswith(skip_path) for skip_path in skip_paths)


def track_usage(usage_type: str, amount: float = 1.0, unit: str = 'units',
                metadata: Dict[str, Any] = None):
    """Decorator for tracking function usage"""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            tenant_id = get_current_tenant_id()
            
            if tenant_id:
                usage_tracker = get_usage_tracker()
                
                # Add function context to metadata
                func_metadata = {
                    'function_name': f.__name__,
                    'module': f.__module__
                }
                if metadata:
                    func_metadata.update(metadata)
                
                usage_tracker.track(tenant_id, usage_type, amount, unit, func_metadata)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def track_database_operation(operation: str, table_name: str = None):
    """Decorator for tracking database operations"""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            result = f(*args, **kwargs)
            
            tenant_id = get_current_tenant_id()
            if tenant_id:
                # Try to determine record count from result
                record_count = 1
                if hasattr(result, '__len__'):
                    try:
                        record_count = len(result)
                    except:
                        pass
                
                usage_tracker = get_usage_tracker()
                usage_tracker.track_database_usage(
                    tenant_id=tenant_id,
                    operation=operation,
                    table_name=table_name or 'unknown',
                    record_count=record_count
                )
            
            return result
        return decorated_function
    return decorator


def track_export_operation(export_format: str):
    """Decorator for tracking export operations"""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            result = f(*args, **kwargs)
            
            tenant_id = get_current_tenant_id()
            if tenant_id:
                # Try to determine export details from result
                record_count = 0
                file_size_bytes = 0
                
                if isinstance(result, dict):
                    record_count = result.get('record_count', 0)
                    file_size_bytes = result.get('file_size_bytes', 0)
                
                usage_tracker = get_usage_tracker()
                usage_tracker.track_export_usage(
                    tenant_id=tenant_id,
                    export_format=export_format,
                    record_count=record_count,
                    file_size_bytes=file_size_bytes
                )
            
            return result
        return decorated_function
    return decorator


def init_usage_tracking(app):
    """Initialize usage tracking for Flask app"""
    # Initialize usage tracking middleware
    UsageTrackingMiddleware(app)
    
    # Set up usage tracking configuration
    app.config.setdefault('USAGE_TRACKING_ENABLED', True)
    app.config.setdefault('USAGE_TRACKING_ASYNC', True)
    app.config.setdefault('USAGE_TRACKING_QUEUE_SIZE', 1000)
    
    log.info("Usage tracking initialized")


# Convenience functions for common usage patterns
def track_api_call(endpoint: str = None, method: str = None):
    """Track API call with current request context"""
    tenant_id = get_current_tenant_id()
    if tenant_id:
        usage_tracker = get_usage_tracker()
        usage_tracker.track_api_call(
            tenant_id=tenant_id,
            endpoint=endpoint or (request.endpoint if request else 'unknown'),
            method=method or (request.method if request else 'GET')
        )


def track_storage(size_bytes: int, operation: str = 'upload', file_type: str = None):
    """Track storage usage with current tenant context"""
    tenant_id = get_current_tenant_id()
    if tenant_id:
        usage_tracker = get_usage_tracker()
        usage_tracker.track_storage_usage(
            tenant_id=tenant_id,
            size_bytes=size_bytes,
            operation=operation,
            file_type=file_type
        )


def track_user_action(activity_type: str, details: Dict[str, Any] = None):
    """Track user activity with current context"""
    tenant_id = get_current_tenant_id()
    if tenant_id:
        usage_tracker = get_usage_tracker()
        usage_tracker.track_user_activity(
            tenant_id=tenant_id,
            activity_type=activity_type,
            details=details
        )