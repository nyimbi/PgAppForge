"""
Enhanced Security and Audit Logging for Multi-Tenant SaaS.

This module provides comprehensive audit logging, security controls, and
monitoring for multi-tenant Flask-AppBuilder applications.
"""

import logging
import json
import hashlib
import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Union
from functools import wraps
from dataclasses import dataclass
from enum import Enum
import threading

from flask import request, g, current_app, jsonify, session
from flask_login import current_user
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declared_attr

from flask_appbuilder import Model
from flask_appbuilder.models.mixins import AuditMixin
from flask_appbuilder.models.tenant_context import get_current_tenant_id

log = logging.getLogger(__name__)


class AuditEventType(Enum):
    """Types of audit events."""
    # Authentication events
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    PASSWORD_CHANGE = "password_change"
    PASSWORD_RESET = "password_reset"
    MFA_ENABLE = "mfa_enable"
    MFA_DISABLE = "mfa_disable"
    
    # Tenant management events
    TENANT_CREATE = "tenant_create"
    TENANT_UPDATE = "tenant_update"
    TENANT_DELETE = "tenant_delete"
    TENANT_SUSPEND = "tenant_suspend"
    TENANT_ACTIVATE = "tenant_activate"
    TENANT_ACCESS = "tenant_access"
    TENANT_SWITCH = "tenant_switch"
    
    # User management events
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    USER_DELETE = "user_delete"
    USER_ROLE_CHANGE = "user_role_change"
    USER_INVITE = "user_invite"
    USER_REMOVE = "user_remove"
    
    # Data access events
    DATA_READ = "data_read"
    DATA_CREATE = "data_create"
    DATA_UPDATE = "data_update"
    DATA_DELETE = "data_delete"
    DATA_EXPORT = "data_export"
    DATA_IMPORT = "data_import"
    BULK_OPERATION = "bulk_operation"
    
    # Billing events
    SUBSCRIPTION_CREATE = "subscription_create"
    SUBSCRIPTION_UPDATE = "subscription_update"
    SUBSCRIPTION_CANCEL = "subscription_cancel"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILURE = "payment_failure"
    USAGE_LIMIT_EXCEEDED = "usage_limit_exceeded"
    
    # Security events
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    SECURITY_VIOLATION = "security_violation"
    
    # System events
    SYSTEM_ERROR = "system_error"
    CONFIGURATION_CHANGE = "configuration_change"
    BACKUP_CREATE = "backup_create"
    BACKUP_RESTORE = "backup_restore"


class RiskLevel(Enum):
    """Risk levels for audit events."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """Audit event data structure."""
    event_type: AuditEventType
    tenant_id: Optional[int]
    user_id: Optional[int]
    resource_type: Optional[str]
    resource_id: Optional[str]
    action: str
    details: Dict[str, Any]
    ip_address: Optional[str]
    user_agent: Optional[str]
    session_id: Optional[str]
    timestamp: datetime
    risk_level: RiskLevel
    success: bool
    error_message: Optional[str] = None


class SecurityAuditLog(AuditMixin, Model):
    """Database model for security audit logs."""
    
    __tablename__ = 'ab_security_audit_logs'
    __table_args__ = (
        Index('ix_audit_tenant_timestamp', 'tenant_id', 'timestamp'),
        Index('ix_audit_user_timestamp', 'user_id', 'timestamp'),
        Index('ix_audit_event_type', 'event_type'),
        Index('ix_audit_risk_level', 'risk_level'),
        Index('ix_audit_resource', 'resource_type', 'resource_id'),
        Index('ix_audit_ip_address', 'ip_address'),
    )
    
    id = Column(Integer, primary_key=True)
    
    # Event identification
    event_type = Column(String(50), nullable=False)
    event_id = Column(String(64), unique=True, nullable=False)  # SHA256 hash
    
    # Context
    tenant_id = Column(Integer, nullable=True)  # Nullable for system events
    user_id = Column(Integer, nullable=True)
    session_id = Column(String(128))
    
    # Resource information
    resource_type = Column(String(100))
    resource_id = Column(String(100))
    action = Column(String(100), nullable=False)
    
    # Event details
    details = Column(JSONB, nullable=False, default=lambda: {})
    
    # Request context
    ip_address = Column(String(45))  # IPv6 compatible
    user_agent = Column(Text)
    request_method = Column(String(10))
    request_path = Column(String(500))
    request_params = Column(JSONB, default=lambda: {})
    
    # Security context
    risk_level = Column(String(20), nullable=False)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text)
    
    # Timing
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    processing_time_ms = Column(Integer)  # Request processing time
    
    def __repr__(self):
        return f'<SecurityAuditLog {self.event_type}:{self.event_id}>'


class TenantSecurityPolicy(AuditMixin, Model):
    """Tenant-specific security policies."""
    
    __tablename__ = 'ab_tenant_security_policies'
    __table_args__ = (
        Index('ix_security_policy_tenant', 'tenant_id'),
        Index('ix_security_policy_active', 'is_active'),
    )
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False, unique=True)
    
    # Password policies
    password_min_length = Column(Integer, default=8)
    password_require_uppercase = Column(Boolean, default=True)
    password_require_lowercase = Column(Boolean, default=True)
    password_require_numbers = Column(Boolean, default=True)
    password_require_symbols = Column(Boolean, default=False)
    password_history_count = Column(Integer, default=5)  # Remember last N passwords
    
    # Session policies
    session_timeout_minutes = Column(Integer, default=480)  # 8 hours
    max_concurrent_sessions = Column(Integer, default=5)
    require_mfa = Column(Boolean, default=False)
    
    # Access policies
    allowed_ip_ranges = Column(JSONB, default=lambda: [])  # CIDR ranges
    blocked_ip_addresses = Column(JSONB, default=lambda: [])
    allowed_countries = Column(JSONB, default=lambda: [])  # ISO country codes
    
    # Rate limiting
    api_rate_limit_per_minute = Column(Integer, default=60)
    login_rate_limit_per_hour = Column(Integer, default=10)
    
    # Audit settings
    audit_all_data_access = Column(Boolean, default=False)
    audit_retention_days = Column(Integer, default=90)
    
    # Notification settings
    notify_on_new_login = Column(Boolean, default=True)
    notify_on_permission_change = Column(Boolean, default=True)
    notify_on_security_event = Column(Boolean, default=True)
    notification_email = Column(String(120))
    
    # Status
    is_active = Column(Boolean, default=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<TenantSecurityPolicy {self.tenant_id}>'


class SecurityAuditLogger:
    """Core security audit logging system."""
    
    def __init__(self):
        self._event_buffer = []
        self._buffer_lock = threading.Lock()
        self._max_buffer_size = 1000
        self._critical_buffer_size = 1500  # Hard limit to prevent memory exhaustion
        self._auto_flush_interval = 30  # seconds
        self._last_flush = datetime.now(tz=timezone.utc)
        self._suspicious_patterns = {}
        self._flush_failure_count = 0
        self._max_flush_failures = 5  # After this many failures, start dropping events
        
        # Start background flush thread
        self._start_flush_thread()
    
    def log_event(self, event: AuditEvent):
        """Log a security audit event."""
        try:
            # Generate unique event ID
            event_data = f"{event.timestamp.isoformat()}:{event.tenant_id}:{event.user_id}:{event.action}"
            event_id = hashlib.sha256(event_data.encode()).hexdigest()
            
            # Create database record
            audit_record = SecurityAuditLog(
                event_type=event.event_type.value,
                event_id=event_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                session_id=event.session_id,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                action=event.action,
                details=event.details,
                ip_address=event.ip_address,
                user_agent=event.user_agent,
                request_method=request.method if request else None,
                request_path=request.path if request else None,
                request_params=dict(request.args) if request else {},
                risk_level=event.risk_level.value,
                success=event.success,
                error_message=event.error_message,
                timestamp=event.timestamp
            )
            
            # Buffer the event for batch processing
            with self._buffer_lock:
                # Check for critical buffer overflow condition
                if len(self._event_buffer) >= self._critical_buffer_size:
                    log.error(f"Audit buffer overflow detected! Dropping oldest events. "
                            f"Buffer size: {len(self._event_buffer)}, Critical limit: {self._critical_buffer_size}")
                    # Drop oldest 20% of events to make room
                    drop_count = len(self._event_buffer) // 5
                    self._event_buffer = self._event_buffer[drop_count:]
                    log.warning(f"Dropped {drop_count} oldest audit events to prevent memory exhaustion")
                
                self._event_buffer.append(audit_record)
                
                # Flush if buffer reaches normal limit
                if len(self._event_buffer) >= self._max_buffer_size:
                    self._flush_events()
            
            # Check for suspicious patterns
            self._analyze_security_patterns(event)
            
            # Log critical events immediately
            if event.risk_level == RiskLevel.CRITICAL:
                log.critical(f"CRITICAL SECURITY EVENT: {event.event_type.value} - {event.details}")
                self._send_security_alert(event)
            
        except Exception as e:
            log.error(f"Failed to log audit event: {e}")
            # If individual event logging fails, we don't want to crash the application
            # Log the error and continue - this prevents audit system issues from 
            # bringing down the entire application
    
    def log_authentication(self, event_type: AuditEventType, user_id: Optional[int], 
                          success: bool, details: Dict[str, Any] = None):
        """Log authentication-related events."""
        tenant_id = get_current_tenant_id()
        
        event = AuditEvent(
            event_type=event_type,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="authentication",
            resource_id=str(user_id) if user_id else None,
            action=event_type.value,
            details=details or {},
            ip_address=request.remote_addr if request else None,
            user_agent=request.headers.get('User-Agent') if request else None,
            session_id=session.get('session_id') if session else None,
            timestamp=datetime.now(tz=timezone.utc),
            risk_level=RiskLevel.HIGH if not success else RiskLevel.MEDIUM,
            success=success
        )
        
        self.log_event(event)
    
    def log_tenant_operation(self, event_type: AuditEventType, tenant_id: int,
                           action: str, details: Dict[str, Any] = None):
        """Log tenant management operations."""
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        
        event = AuditEvent(
            event_type=event_type,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="tenant",
            resource_id=str(tenant_id),
            action=action,
            details=details or {},
            ip_address=request.remote_addr if request else None,
            user_agent=request.headers.get('User-Agent') if request else None,
            session_id=session.get('session_id') if session else None,
            timestamp=datetime.now(tz=timezone.utc),
            risk_level=RiskLevel.HIGH,
            success=True
        )
        
        self.log_event(event)
    
    def log_data_access(self, action: str, resource_type: str, resource_id: str = None,
                       record_count: int = None, details: Dict[str, Any] = None):
        """Log data access operations."""
        tenant_id = get_current_tenant_id()
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        
        event_details = details or {}
        if record_count is not None:
            event_details['record_count'] = record_count
        
        # Determine risk level based on action and scope
        risk_level = RiskLevel.LOW
        if action in ['delete', 'export', 'bulk_delete']:
            risk_level = RiskLevel.MEDIUM
        if record_count and record_count > 1000:
            risk_level = RiskLevel.HIGH
        
        event = AuditEvent(
            event_type=AuditEventType.DATA_READ if action == 'read' else AuditEventType.DATA_UPDATE,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            details=event_details,
            ip_address=request.remote_addr if request else None,
            user_agent=request.headers.get('User-Agent') if request else None,
            session_id=session.get('session_id') if session else None,
            timestamp=datetime.now(tz=timezone.utc),
            risk_level=risk_level,
            success=True
        )
        
        self.log_event(event)
    
    def log_security_violation(self, violation_type: str, details: Dict[str, Any],
                             tenant_id: int = None, user_id: int = None):
        """Log security violations and suspicious activities."""
        if not tenant_id:
            tenant_id = get_current_tenant_id()
        if not user_id and current_user and current_user.is_authenticated:
            user_id = current_user.id
        
        event = AuditEvent(
            event_type=AuditEventType.SECURITY_VIOLATION,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="security",
            resource_id=violation_type,
            action=violation_type,
            details=details,
            ip_address=request.remote_addr if request else None,
            user_agent=request.headers.get('User-Agent') if request else None,
            session_id=session.get('session_id') if session else None,
            timestamp=datetime.now(tz=timezone.utc),
            risk_level=RiskLevel.CRITICAL,
            success=False,
            error_message=f"Security violation: {violation_type}"
        )
        
        self.log_event(event)
    
    def get_audit_trail(self, tenant_id: int = None, user_id: int = None,
                       event_type: AuditEventType = None, start_date: datetime = None,
                       end_date: datetime = None, limit: int = 100) -> List[SecurityAuditLog]:
        """Get audit trail with filtering options."""
        from flask_appbuilder import db
        
        # Enforce reasonable limits to prevent memory exhaustion from large queries
        if limit > 10000:
            log.warning(f"Audit trail query limit reduced from {limit} to 10000 to prevent memory issues")
            limit = 10000
        
        query = db.session.query(SecurityAuditLog)
        
        if tenant_id:
            query = query.filter(SecurityAuditLog.tenant_id == tenant_id)
        if user_id:
            query = query.filter(SecurityAuditLog.user_id == user_id)
        if event_type:
            query = query.filter(SecurityAuditLog.event_type == event_type.value)
        if start_date:
            query = query.filter(SecurityAuditLog.timestamp >= start_date)
        if end_date:
            query = query.filter(SecurityAuditLog.timestamp <= end_date)
        
        return query.order_by(SecurityAuditLog.timestamp.desc()).limit(limit).all()
    
    def get_security_summary(self, tenant_id: int, days: int = 30) -> Dict[str, Any]:
        """Get security summary for a tenant."""
        from flask_appbuilder import db
        from sqlalchemy import func
        
        end_date = datetime.now(tz=timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        # Get event counts by type
        event_counts = db.session.query(
            SecurityAuditLog.event_type,
            func.count(SecurityAuditLog.id).label('count')
        ).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.timestamp >= start_date
        ).group_by(SecurityAuditLog.event_type).all()
        
        # Get risk level distribution
        risk_counts = db.session.query(
            SecurityAuditLog.risk_level,
            func.count(SecurityAuditLog.id).label('count')
        ).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.timestamp >= start_date
        ).group_by(SecurityAuditLog.risk_level).all()
        
        # Get failed events
        failed_count = db.session.query(func.count(SecurityAuditLog.id)).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.timestamp >= start_date,
            SecurityAuditLog.success == False
        ).scalar()
        
        # Get unique IP addresses
        unique_ips = db.session.query(func.count(func.distinct(SecurityAuditLog.ip_address))).filter(
            SecurityAuditLog.tenant_id == tenant_id,
            SecurityAuditLog.timestamp >= start_date
        ).scalar()
        
        return {
            'period_days': days,
            'total_events': sum(count for _, count in event_counts),
            'event_types': {event_type: count for event_type, count in event_counts},
            'risk_levels': {risk_level: count for risk_level, count in risk_counts},
            'failed_events': failed_count,
            'unique_ip_addresses': unique_ips,
            'generated_at': datetime.now(tz=timezone.utc).isoformat()
        }
    
    def _analyze_security_patterns(self, event: AuditEvent):
        """Analyze events for suspicious patterns."""
        if not event.ip_address or not event.user_id:
            return
        
        pattern_key = f"{event.ip_address}:{event.user_id}"
        current_time = event.timestamp
        
        # Initialize pattern tracking
        if pattern_key not in self._suspicious_patterns:
            self._suspicious_patterns[pattern_key] = {
                'failed_logins': [],
                'rapid_requests': [],
                'unusual_locations': []
            }
        
        patterns = self._suspicious_patterns[pattern_key]
        
        # Track failed login attempts
        if event.event_type == AuditEventType.LOGIN_FAILURE:
            patterns['failed_logins'].append(current_time)
            # Keep only last hour
            cutoff = current_time - timedelta(hours=1)
            patterns['failed_logins'] = [t for t in patterns['failed_logins'] if t > cutoff]
            
            # Alert on multiple failures
            if len(patterns['failed_logins']) >= 5:
                self._send_security_alert(AuditEvent(
                    event_type=AuditEventType.SUSPICIOUS_ACTIVITY,
                    tenant_id=event.tenant_id,
                    user_id=event.user_id,
                    resource_type="security",
                    resource_id="brute_force",
                    action="multiple_failed_logins",
                    details={'failed_attempts': len(patterns['failed_logins']), 'ip_address': event.ip_address},
                    ip_address=event.ip_address,
                    user_agent=event.user_agent,
                    session_id=event.session_id,
                    timestamp=current_time,
                    risk_level=RiskLevel.CRITICAL,
                    success=False
                ))
    
    def _flush_events(self):
        """Flush buffered events to database with proper overflow protection."""
        if not self._event_buffer:
            return
        
        try:
            from flask_appbuilder import db
            
            events_to_flush = self._event_buffer.copy()
            self._event_buffer.clear()
            
            # Bulk insert
            db.session.bulk_save_objects(events_to_flush)
            db.session.commit()
            
            log.debug(f"Flushed {len(events_to_flush)} audit events to database")
            self._last_flush = datetime.now(tz=timezone.utc)
            self._flush_failure_count = 0  # Reset failure counter on success
            
        except Exception as e:
            log.error(f"Failed to flush audit events: {e}")
            self._flush_failure_count += 1
            
            # Implement progressive backoff and event dropping for persistent failures
            if self._flush_failure_count >= self._max_flush_failures:
                log.critical(f"Audit flush has failed {self._flush_failure_count} times. "
                           f"Dropping {len(events_to_flush)} events to prevent memory exhaustion.")
                # Don't re-add events after multiple failures - drop them to prevent overflow
                return
            
            # For early failures, re-add events but with bounds checking
            current_buffer_size = len(self._event_buffer)
            events_to_readd = events_to_flush
            
            # Ensure we don't exceed critical buffer size when re-adding
            max_events_to_readd = self._critical_buffer_size - current_buffer_size
            if len(events_to_readd) > max_events_to_readd > 0:
                log.warning(f"Buffer overflow protection: Only re-adding {max_events_to_readd} "
                          f"of {len(events_to_readd)} failed events to prevent memory exhaustion")
                # Keep the most recent events (they're likely more important)
                events_to_readd = events_to_readd[-max_events_to_readd:]
            elif max_events_to_readd <= 0:
                log.warning(f"Buffer full, dropping all {len(events_to_readd)} failed flush events")
                return
            
            # Re-add events with bounds protection
            self._event_buffer.extend(events_to_readd)
            log.info(f"Re-added {len(events_to_readd)} events to buffer after flush failure "
                   f"(attempt {self._flush_failure_count}/{self._max_flush_failures})")
    
    def _start_flush_thread(self):
        """Start background thread for periodic event flushing."""
        def flush_worker():
            while True:
                try:
                    time_since_flush = (datetime.now(tz=timezone.utc) - self._last_flush).total_seconds()
                    
                    # More aggressive flushing if buffer is getting full or we have failures
                    flush_threshold = self._auto_flush_interval
                    with self._buffer_lock:
                        buffer_size = len(self._event_buffer)
                        
                        # Reduce flush interval if buffer is getting full
                        if buffer_size > self._max_buffer_size * 0.8:
                            flush_threshold = 10  # Flush every 10 seconds if 80% full
                        elif buffer_size > self._max_buffer_size * 0.5:
                            flush_threshold = 15  # Flush every 15 seconds if 50% full
                        
                        # Force flush if approaching critical size regardless of time
                        if (buffer_size >= self._max_buffer_size or 
                            time_since_flush >= flush_threshold):
                            self._flush_events()
                    
                    # Adaptive sleep based on buffer state
                    if buffer_size > self._max_buffer_size * 0.8:
                        time.sleep(5)  # Check more frequently when buffer is nearly full
                    else:
                        time.sleep(10)  # Normal check interval
                    
                except Exception as e:
                    log.error(f"Audit flush thread error: {e}")
                    time.sleep(60)  # Wait longer on error
        
        import threading
        flush_thread = threading.Thread(target=flush_worker, daemon=True)
        flush_thread.start()
    
    def _send_security_alert(self, event: AuditEvent):
        """Send security alert for critical events."""
        # This would integrate with notification system
        log.critical(f"SECURITY ALERT: {event.event_type.value} for tenant {event.tenant_id}")
        
        # Store alert for later processing
        alert_details = {
            'event_type': event.event_type.value,
            'tenant_id': event.tenant_id,
            'user_id': event.user_id,
            'details': event.details,
            'timestamp': event.timestamp.isoformat(),
            'ip_address': event.ip_address,
            'risk_level': event.risk_level.value
        }
        
        # This would send email/Slack/webhook notifications
        # For now, we just log it
        log.critical(f"Security alert data: {json.dumps(alert_details)}")


class SecurityMiddleware:
    """Security middleware for multi-tenant applications."""
    
    def __init__(self, app=None, audit_logger=None):
        self.app = app
        self.audit_logger = audit_logger or get_audit_logger()
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize security middleware with Flask app."""
        self.app = app
        
        # Register before request handlers
        app.before_request(self.validate_request_security)
        app.after_request(self.add_security_headers)
        
        # Register error handlers
        app.errorhandler(429)(self.rate_limit_handler)
        app.errorhandler(403)(self.forbidden_handler)
    
    def validate_request_security(self):
        """Validate request security before processing."""
        try:
            # Check IP allowlist/blocklist
            if not self._validate_ip_address():
                self.audit_logger.log_security_violation(
                    'blocked_ip_access',
                    {'ip_address': request.remote_addr, 'path': request.path}
                )
                return jsonify({'error': 'Access denied'}), 403
            
            # Validate tenant context for tenant-aware endpoints
            if request.endpoint and self._is_tenant_endpoint(request.endpoint):
                if not get_current_tenant_id():
                    self.audit_logger.log_security_violation(
                        'missing_tenant_context',
                        {'endpoint': request.endpoint, 'path': request.path}
                    )
                    return jsonify({'error': 'Invalid tenant context'}), 400
            
            # Check for suspicious request patterns
            if self._detect_suspicious_request():
                self.audit_logger.log_security_violation(
                    'suspicious_request_pattern',
                    {
                        'path': request.path,
                        'method': request.method,
                        'user_agent': request.headers.get('User-Agent'),
                        'content_length': request.content_length
                    }
                )
                return jsonify({'error': 'Request blocked'}), 403
            
        except Exception as e:
            log.error(f"Security validation error: {e}")
            # Don't block requests on security validation errors
            return None
    
    def add_security_headers(self, response):
        """Add security headers to response."""
        # Security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # CSP header for tenant-specific content
        tenant_id = get_current_tenant_id()
        if tenant_id:
            csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
            response.headers['Content-Security-Policy'] = csp
        
        # Remove server information
        response.headers.pop('Server', None)
        
        return response
    
    def rate_limit_handler(self, error):
        """Handle rate limit exceeded."""
        self.audit_logger.log_security_violation(
            'rate_limit_exceeded',
            {
                'limit': str(error),
                'path': request.path,
                'method': request.method
            }
        )
        
        return jsonify({
            'error': 'Rate limit exceeded',
            'retry_after': getattr(error, 'retry_after', 60)
        }), 429
    
    def forbidden_handler(self, error):
        """Handle forbidden access."""
        self.audit_logger.log_security_violation(
            'forbidden_access',
            {
                'path': request.path,
                'method': request.method,
                'error': str(error)
            }
        )
        
        return jsonify({'error': 'Access forbidden'}), 403
    
    def _validate_ip_address(self) -> bool:
        """Validate request IP against tenant security policy."""
        if not request.remote_addr:
            return True  # Can't validate without IP
        
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            return True  # No tenant context
        
        try:
            # Get tenant security policy
            from flask_appbuilder import db
            policy = db.session.query(TenantSecurityPolicy).filter_by(
                tenant_id=tenant_id, is_active=True
            ).first()
            
            if not policy:
                return True  # No policy defined
            
            request_ip = ipaddress.ip_address(request.remote_addr)
            
            # Check blocked IPs
            for blocked_ip in policy.blocked_ip_addresses:
                if str(request_ip) == blocked_ip:
                    return False
            
            # Check allowed IP ranges
            if policy.allowed_ip_ranges:
                allowed = False
                for ip_range in policy.allowed_ip_ranges:
                    if request_ip in ipaddress.ip_network(ip_range, strict=False):
                        allowed = True
                        break
                return allowed
            
            return True  # No restrictions
            
        except Exception as e:
            log.debug(f"IP validation error: {e}")
            return True  # Allow on validation errors
    
    def _is_tenant_endpoint(self, endpoint: str) -> bool:
        """Check if endpoint requires tenant context."""
        tenant_endpoints = [
            'tenant', 'dashboard', 'customer', 'order', 'billing'
        ]
        
        return any(tenant_ep in endpoint.lower() for tenant_ep in tenant_endpoints)
    
    def _detect_suspicious_request(self) -> bool:
        """Detect suspicious request patterns."""
        # Check for common attack patterns
        suspicious_patterns = [
            'script', 'javascript:', 'vbscript:', 'onload=', 'onerror=',
            '../', '..\\', '/etc/passwd', '/proc/version',
            'union select', 'drop table', 'insert into',
            '<script', '<iframe', '<object', '<embed'
        ]
        
        # Check query parameters
        for param, value in request.args.items():
            if isinstance(value, str):
                for pattern in suspicious_patterns:
                    if pattern.lower() in value.lower():
                        return True
        
        # Check form data
        if request.form:
            for field, value in request.form.items():
                if isinstance(value, str):
                    for pattern in suspicious_patterns:
                        if pattern.lower() in value.lower():
                            return True
        
        # Check for unusually large requests
        if request.content_length and request.content_length > 10 * 1024 * 1024:  # 10MB
            return True
        
        return False


# Decorators for audit logging
def audit_data_access(action: str, resource_type: str):
    """Decorator to audit data access operations."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = datetime.now(tz=timezone.utc)
            success = True
            error_msg = None
            result = None
            
            try:
                result = func(*args, **kwargs)
                
                # Try to determine record count from result
                record_count = None
                if hasattr(result, '__len__'):
                    record_count = len(result)
                elif hasattr(result, 'count'):
                    record_count = result.count()
                
                return result
                
            except Exception as e:
                success = False
                error_msg = str(e)
                raise
                
            finally:
                # Log the data access
                audit_logger = get_audit_logger()
                
                processing_time = (datetime.now(tz=timezone.utc) - start_time).total_seconds() * 1000
                
                audit_logger.log_data_access(
                    action=action,
                    resource_type=resource_type,
                    record_count=getattr(result, '__len__', lambda: None)() if result else None,
                    details={
                        'function': func.__name__,
                        'success': success,
                        'error_message': error_msg,
                        'processing_time_ms': processing_time
                    }
                )
        
        return wrapper
    return decorator


def audit_tenant_operation(event_type: AuditEventType, action: str):
    """Decorator to audit tenant operations."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = datetime.now(tz=timezone.utc)
            success = True
            error_msg = None
            
            try:
                result = func(*args, **kwargs)
                return result
                
            except Exception as e:
                success = False
                error_msg = str(e)
                raise
                
            finally:
                tenant_id = get_current_tenant_id()
                if tenant_id:
                    audit_logger = get_audit_logger()
                    processing_time = (datetime.now(tz=timezone.utc) - start_time).total_seconds() * 1000
                    
                    audit_logger.log_tenant_operation(
                        event_type=event_type,
                        tenant_id=tenant_id,
                        action=action,
                        details={
                            'function': func.__name__,
                            'success': success,
                            'error_message': error_msg,
                            'processing_time_ms': processing_time,
                            'args_count': len(args),
                            'kwargs_keys': list(kwargs.keys())
                        }
                    )
        
        return wrapper
    return decorator


def require_tenant_security_policy(policy_check: str):
    """Decorator to enforce tenant security policies."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            tenant_id = get_current_tenant_id()
            if not tenant_id:
                return jsonify({'error': 'No tenant context'}), 400
            
            # Check tenant security policy
            from flask_appbuilder import db
            policy = db.session.query(TenantSecurityPolicy).filter_by(
                tenant_id=tenant_id, is_active=True
            ).first()
            
            if policy:
                # Perform policy check
                if policy_check == 'mfa_required' and policy.require_mfa:
                    if not session.get('mfa_verified'):
                        audit_logger = get_audit_logger()
                        audit_logger.log_security_violation(
                            'mfa_required_not_satisfied',
                            {'policy_check': policy_check, 'function': func.__name__}
                        )
                        return jsonify({'error': 'MFA verification required'}), 403
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


# Global audit logger instance
_audit_logger = None
_audit_logger_lock = threading.Lock()


def get_audit_logger() -> SecurityAuditLogger:
    """Get global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        with _audit_logger_lock:
            if _audit_logger is None:
                _audit_logger = SecurityAuditLogger()
    return _audit_logger


def initialize_security_system(app):
    """Initialize the security and audit system."""
    log.info("Initializing multi-tenant security and audit system...")
    
    # Initialize audit logger
    audit_logger = get_audit_logger()
    
    # Initialize security middleware
    security_middleware = SecurityMiddleware(app, audit_logger)
    
    # Store in app extensions
    app.extensions['security_audit_logger'] = audit_logger
    app.extensions['security_middleware'] = security_middleware
    
    log.info("Multi-tenant security and audit system initialized successfully")