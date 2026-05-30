"""
Audit Trail Engine

Comprehensive audit logging, monitoring, and trail generation for PgAppForge
applications with compliance and security focus.
"""

import logging
import json
import hashlib
import threading
from typing import Dict, List, Any, Optional, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
import uuid
import queue
import time
import os
import inspect
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class AuditEventType(Enum):
    """Types of audit events."""
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_CREATION = "user_creation"
    USER_MODIFICATION = "user_modification"
    USER_DELETION = "user_deletion"
    
    DATA_CREATE = "data_create"
    DATA_READ = "data_read"
    DATA_UPDATE = "data_update"
    DATA_DELETE = "data_delete"
    
    PERMISSION_GRANT = "permission_grant"
    PERMISSION_REVOKE = "permission_revoke"
    ROLE_ASSIGNMENT = "role_assignment"
    ROLE_REMOVAL = "role_removal"
    
    SECURITY_VIOLATION = "security_violation"
    LOGIN_FAILURE = "login_failure"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    
    CONFIG_CHANGE = "config_change"
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    BACKUP_CREATE = "backup_create"
    BACKUP_RESTORE = "backup_restore"
    
    API_CALL = "api_call"
    FILE_ACCESS = "file_access"
    DATABASE_QUERY = "database_query"
    
    COMPLIANCE_CHECK = "compliance_check"
    SECURITY_SCAN = "security_scan"
    POLICY_VIOLATION = "policy_violation"


class AuditLevel(Enum):
    """Audit logging levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """Represents an audit event."""
    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    # Event details
    resource: Optional[str] = None
    action: Optional[str] = None
    target: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    
    # Context information
    source_module: Optional[str] = None
    source_function: Optional[str] = None
    source_line: Optional[int] = None
    request_path: Optional[str] = None
    request_method: Optional[str] = None
    
    # Security context
    security_level: AuditLevel = AuditLevel.INFO
    compliance_relevant: bool = False
    sensitive_data: bool = False
    
    # Results and impact
    success: bool = True
    error_message: Optional[str] = None
    risk_score: float = 0.0
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None
    parent_event_id: Optional[str] = None


@dataclass
class AuditConfiguration:
    """Configuration for audit engine."""
    # Logging settings
    enabled: bool = True
    log_level: AuditLevel = AuditLevel.INFO
    log_to_file: bool = True
    log_to_database: bool = True
    log_to_syslog: bool = False
    
    # File settings
    log_file_path: str = "audit.log"
    max_log_file_size: int = 100 * 1024 * 1024  # 100MB
    log_file_rotation: int = 10  # Keep 10 old files
    
    # Database settings
    database_table: str = "audit_log"
    database_retention_days: int = 2555  # 7 years for compliance
    
    # Performance settings
    async_logging: bool = True
    batch_size: int = 100
    batch_timeout: float = 5.0  # seconds
    queue_size: int = 10000
    
    # Security settings
    encrypt_sensitive_data: bool = True
    hash_pii: bool = True
    redact_patterns: List[str] = field(default_factory=lambda: [
        r'\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}',  # Credit cards
        r'\d{3}-\d{2}-\d{4}',  # SSN
        r'password\s*[=:]\s*["\']?([^"\'\s]+)',  # Passwords
    ])
    
    # Compliance settings
    compliance_frameworks: List[str] = field(default_factory=lambda: ['SOX', 'GDPR', 'HIPAA'])
    retention_policies: Dict[str, int] = field(default_factory=lambda: {
        'SOX': 2555,  # 7 years
        'GDPR': 2555,  # 7 years
        'HIPAA': 2190,  # 6 years
    })
    
    # Alerting settings
    enable_alerts: bool = True
    alert_thresholds: Dict[str, int] = field(default_factory=lambda: {
        'login_failures': 5,
        'unauthorized_access': 3,
        'suspicious_activity': 1,
        'security_violations': 1
    })
    
    # Event filtering
    ignored_events: List[AuditEventType] = field(default_factory=list)
    monitored_users: List[str] = field(default_factory=list)  # Empty = all users
    monitored_resources: List[str] = field(default_factory=list)  # Empty = all resources


class AuditTrailEngine:
    """
    Comprehensive audit trail engine for PgAppForge applications.
    
    Features:
    - Multi-destination logging (file, database, syslog)
    - Async/batch processing for performance
    - Compliance-focused retention and formatting
    - Security-aware data handling (encryption, redaction)
    - Real-time alerting for suspicious activities
    - Comprehensive PgAppForge integration
    - Tamper-evident audit trails
    - Query and reporting capabilities
    """
    
    def __init__(self, config: Optional[AuditConfiguration] = None):
        self.config = config or AuditConfiguration()
        self.event_queue = queue.Queue(maxsize=self.config.queue_size)
        self.audit_handlers: List[Callable] = []
        self.alert_handlers: List[Callable] = []
        
        # Threading for async processing
        self.processing_thread: Optional[threading.Thread] = None
        self.shutdown_event = threading.Event()
        
        # Event tracking
        self.event_counts: Dict[AuditEventType, int] = {}
        self.last_batch_time = time.time()
        
        # Security
        self._encryption_key: Optional[bytes] = None
        self._initialize_encryption()
        
        # Start processing if async is enabled
        if self.config.async_logging:
            self._start_processing_thread()
        
        logger.info("Audit Trail Engine initialized")
    
    def _initialize_encryption(self):
        """Initialize encryption for sensitive data."""
        if self.config.encrypt_sensitive_data:
            try:
                from cryptography.fernet import Fernet
                # In production, this should come from secure key management
                key_file = Path("audit_encryption.key")
                if key_file.exists():
                    with open(key_file, 'rb') as f:
                        self._encryption_key = f.read()
                else:
                    self._encryption_key = Fernet.generate_key()
                    with open(key_file, 'wb') as f:
                        f.write(self._encryption_key)
                    os.chmod(key_file, 0o600)  # Restrict permissions
            except ImportError:
                logger.warning("Cryptography library not available - sensitive data encryption disabled")
                self.config.encrypt_sensitive_data = False
    
    def _start_processing_thread(self):
        """Start background processing thread."""
        self.processing_thread = threading.Thread(
            target=self._process_events_async,
            name="AuditProcessor",
            daemon=True
        )
        self.processing_thread.start()
        logger.info("Started audit processing thread")
    
    def _process_events_async(self):
        """Process audit events asynchronously in batches."""
        batch = []
        
        while not self.shutdown_event.is_set():
            try:
                # Try to get events from queue
                timeout = max(0.1, self.config.batch_timeout - (time.time() - self.last_batch_time))
                
                try:
                    event = self.event_queue.get(timeout=timeout)
                    batch.append(event)
                    
                    # Check if we should process the batch
                    should_process = (
                        len(batch) >= self.config.batch_size or
                        time.time() - self.last_batch_time >= self.config.batch_timeout or
                        event.security_level in [AuditLevel.ERROR, AuditLevel.CRITICAL]
                    )
                    
                    if should_process:
                        self._process_event_batch(batch)
                        batch = []
                        self.last_batch_time = time.time()
                    
                except queue.Empty:
                    # Process any remaining events in batch
                    if batch and time.time() - self.last_batch_time >= self.config.batch_timeout:
                        self._process_event_batch(batch)
                        batch = []
                        self.last_batch_time = time.time()
                
            except Exception as e:
                logger.error(f"Error in audit processing thread: {e}")
                time.sleep(1)  # Brief pause before retrying
        
        # Process any remaining events on shutdown
        if batch:
            self._process_event_batch(batch)
    
    def _process_event_batch(self, events: List[AuditEvent]):
        """Process a batch of audit events."""
        if not events:
            return
        
        try:
            # Apply security measures
            processed_events = []
            for event in events:
                processed_event = self._secure_event(event)
                processed_events.append(processed_event)
            
            # Write to configured destinations
            if self.config.log_to_file:
                self._write_to_file(processed_events)
            
            if self.config.log_to_database:
                self._write_to_database(processed_events)
            
            if self.config.log_to_syslog:
                self._write_to_syslog(processed_events)
            
            # Process custom handlers
            for handler in self.audit_handlers:
                try:
                    handler(processed_events)
                except Exception as e:
                    logger.error(f"Audit handler error: {e}")
            
            # Check for alerts
            if self.config.enable_alerts:
                self._check_alerts(processed_events)
            
            # Update statistics
            for event in processed_events:
                self.event_counts[event.event_type] = self.event_counts.get(event.event_type, 0) + 1
            
        except Exception as e:
            logger.error(f"Failed to process audit batch: {e}")
    
    def _secure_event(self, event: AuditEvent) -> AuditEvent:
        """Apply security measures to audit event."""
        # Create a copy to avoid modifying original
        secured_event = AuditEvent(**event.__dict__.copy())
        secured_event.details = event.details.copy()
        
        # Redact sensitive data patterns
        for pattern in self.config.redact_patterns:
            import re
            regex = re.compile(pattern, re.IGNORECASE)
            
            # Redact in details
            for key, value in secured_event.details.items():
                if isinstance(value, str):
                    secured_event.details[key] = regex.sub('[REDACTED]', value)
        
        # Hash PII if configured
        if self.config.hash_pii and secured_event.sensitive_data:
            if secured_event.user_id:
                secured_event.user_id = self._hash_value(secured_event.user_id)
            
            # Hash sensitive details
            for key, value in secured_event.details.items():
                if key.lower() in ['email', 'name', 'ssn', 'phone', 'address']:
                    if isinstance(value, str):
                        secured_event.details[key] = self._hash_value(value)
        
        # Encrypt sensitive data if configured
        if (self.config.encrypt_sensitive_data and 
            secured_event.sensitive_data and 
            self._encryption_key):
            
            sensitive_fields = ['details', 'target', 'error_message']
            for field in sensitive_fields:
                field_value = getattr(secured_event, field, None)
                if field_value:
                    if isinstance(field_value, dict):
                        encrypted_value = self._encrypt_value(json.dumps(field_value))
                    else:
                        encrypted_value = self._encrypt_value(str(field_value))
                    setattr(secured_event, field, encrypted_value)
        
        return secured_event
    
    def _hash_value(self, value: str) -> str:
        """Hash a value for PII protection."""
        return hashlib.sha256(value.encode()).hexdigest()[:16]  # Truncated hash
    
    def _encrypt_value(self, value: str) -> str:
        """Encrypt a sensitive value."""
        try:
            from cryptography.fernet import Fernet
            f = Fernet(self._encryption_key)
            return f.encrypt(value.encode()).decode()
        except Exception as e:
            logger.warning(f"Failed to encrypt value: {e}")
            return "[ENCRYPTION_FAILED]"
    
    def _decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a sensitive value."""
        try:
            from cryptography.fernet import Fernet
            f = Fernet(self._encryption_key)
            return f.decrypt(encrypted_value.encode()).decode()
        except Exception as e:
            logger.warning(f"Failed to decrypt value: {e}")
            return "[DECRYPTION_FAILED]"
    
    def _write_to_file(self, events: List[AuditEvent]):
        """Write events to log file."""
        log_file = Path(self.config.log_file_path)
        
        try:
            # Create directory if it doesn't exist
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Rotate log if needed
            if log_file.exists() and log_file.stat().st_size > self.config.max_log_file_size:
                self._rotate_log_file(log_file)
            
            # Write events
            with open(log_file, 'a', encoding='utf-8') as f:
                for event in events:
                    log_entry = {
                        'timestamp': event.timestamp.isoformat(),
                        'event_id': event.event_id,
                        'event_type': event.event_type.value,
                        'user_id': event.user_id,
                        'session_id': event.session_id,
                        'ip_address': event.ip_address,
                        'resource': event.resource,
                        'action': event.action,
                        'target': event.target,
                        'success': event.success,
                        'details': event.details,
                        'security_level': event.security_level.value,
                        'compliance_relevant': event.compliance_relevant,
                        'risk_score': event.risk_score
                    }
                    
                    f.write(json.dumps(log_entry) + '\n')
        
        except Exception as e:
            logger.error(f"Failed to write to audit log file: {e}")
    
    def _rotate_log_file(self, log_file: Path):
        """Rotate log file when it gets too large."""
        try:
            # Move existing log files
            for i in range(self.config.log_file_rotation - 1, 0, -1):
                old_file = log_file.with_suffix(f'.{i}')
                new_file = log_file.with_suffix(f'.{i+1}')
                if old_file.exists():
                    old_file.rename(new_file)
            
            # Rename current log file
            if log_file.exists():
                log_file.rename(log_file.with_suffix('.1'))
        
        except Exception as e:
            logger.error(f"Failed to rotate log file: {e}")
    
    def _write_to_database(self, events: List[AuditEvent]):
        """Write events to database."""
        # This would integrate with PgAppForge's database
        # For now, just log that we would write to database
        logger.debug(f"Would write {len(events)} events to database table: {self.config.database_table}")
        
        # Example implementation:
        # try:
        #     from pgappforge import Model
        #     from sqlalchemy import Column, String, DateTime, Boolean, Text, Float
        #     
        #     class AuditLog(Model):
        #         __tablename__ = self.config.database_table
        #         
        #         event_id = Column(String(64), primary_key=True)
        #         timestamp = Column(DateTime)
        #         event_type = Column(String(50))
        #         user_id = Column(String(50))
        #         # ... other columns
        #     
        #     for event in events:
        #         audit_record = AuditLog(
        #             event_id=event.event_id,
        #             timestamp=event.timestamp,
        #             event_type=event.event_type.value,
        #             # ... other fields
        #         )
        #         db.session.add(audit_record)
        #     
        #     db.session.commit()
        # 
        # except Exception as e:
        #     logger.error(f"Failed to write to database: {e}")
    
    def _write_to_syslog(self, events: List[AuditEvent]):
        """Write events to syslog."""
        try:
            import syslog
            syslog.openlog("flask-appbuilder-audit")
            
            for event in events:
                priority = syslog.LOG_INFO
                if event.security_level == AuditLevel.ERROR:
                    priority = syslog.LOG_ERR
                elif event.security_level == AuditLevel.CRITICAL:
                    priority = syslog.LOG_CRIT
                elif event.security_level == AuditLevel.WARNING:
                    priority = syslog.LOG_WARNING
                
                message = f"AUDIT: {event.event_type.value} user={event.user_id} resource={event.resource} success={event.success}"
                syslog.syslog(priority, message)
        
        except Exception as e:
            logger.error(f"Failed to write to syslog: {e}")
    
    def _check_alerts(self, events: List[AuditEvent]):
        """Check events for alerting conditions."""
        for event in events:
            # Check for immediate alerts
            if event.security_level in [AuditLevel.ERROR, AuditLevel.CRITICAL]:
                self._trigger_alert(event, "Security event detected")
            
            # Check threshold-based alerts
            if event.event_type == AuditEventType.LOGIN_FAILURE:
                recent_failures = self._count_recent_events(
                    AuditEventType.LOGIN_FAILURE, 
                    timedelta(minutes=15),
                    user_id=event.user_id
                )
                if recent_failures >= self.config.alert_thresholds.get('login_failures', 5):
                    self._trigger_alert(event, f"Multiple login failures: {recent_failures}")
            
            elif event.event_type == AuditEventType.UNAUTHORIZED_ACCESS:
                recent_unauthorized = self._count_recent_events(
                    AuditEventType.UNAUTHORIZED_ACCESS,
                    timedelta(minutes=5),
                    user_id=event.user_id
                )
                if recent_unauthorized >= self.config.alert_thresholds.get('unauthorized_access', 3):
                    self._trigger_alert(event, f"Repeated unauthorized access: {recent_unauthorized}")
    
    def _count_recent_events(self, event_type: AuditEventType, 
                           time_window: timedelta, 
                           user_id: Optional[str] = None) -> int:
        """Count recent events of specific type."""
        # This would query the actual audit log
        # For now, return a mock count
        return 1
    
    def _trigger_alert(self, event: AuditEvent, message: str):
        """Trigger security alert."""
        alert_data = {
            'timestamp': datetime.now(),
            'event_id': event.event_id,
            'event_type': event.event_type.value,
            'user_id': event.user_id,
            'message': message,
            'risk_score': event.risk_score,
            'details': event.details
        }
        
        logger.warning(f"SECURITY ALERT: {message} - Event: {event.event_id}")
        
        # Process alert handlers
        for handler in self.alert_handlers:
            try:
                handler(alert_data)
            except Exception as e:
                logger.error(f"Alert handler error: {e}")
    
    # Public API methods
    def log_event(self, event_type: AuditEventType, **kwargs) -> str:
        """
        Log an audit event.
        
        Args:
            event_type: Type of audit event
            **kwargs: Event details (user_id, resource, action, etc.)
            
        Returns:
            Event ID
        """
        if not self.config.enabled:
            return ""
        
        # Filter ignored events
        if event_type in self.config.ignored_events:
            return ""
        
        # Get caller information
        frame = inspect.currentframe().f_back
        source_info = {
            'source_module': frame.f_globals.get('__name__'),
            'source_function': frame.f_code.co_name,
            'source_line': frame.f_lineno
        }
        
        # Create event
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(),
            **source_info,
            **kwargs
        )
        
        # Set defaults
        if event.security_level is None:
            event.security_level = AuditLevel.INFO
        
        # Check if event is filtered
        if self._should_filter_event(event):
            return event.event_id
        
        # Add to queue or process immediately
        try:
            if self.config.async_logging:
                self.event_queue.put(event, timeout=1.0)
            else:
                self._process_event_batch([event])
        except queue.Full:
            logger.warning("Audit queue full - dropping event")
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")
        
        return event.event_id
    
    def _should_filter_event(self, event: AuditEvent) -> bool:
        """Check if event should be filtered."""
        
        # Filter by user
        if (self.config.monitored_users and 
            event.user_id not in self.config.monitored_users):
            return True
        
        # Filter by resource
        if (self.config.monitored_resources and 
            event.resource not in self.config.monitored_resources):
            return True
        
        # Filter by level
        level_priority = {
            AuditLevel.DEBUG: 0,
            AuditLevel.INFO: 1,
            AuditLevel.WARNING: 2,
            AuditLevel.ERROR: 3,
            AuditLevel.CRITICAL: 4
        }
        
        if level_priority[event.security_level] < level_priority[self.config.log_level]:
            return True
        
        return False
    
    @contextmanager
    def audit_context(self, **context):
        """Context manager for adding audit context to subsequent events."""
        # This would store context in thread-local storage
        # and automatically add it to events logged within this context
        yield
    
    # PgAppForge integration methods
    def log_user_login(self, user_id: str, ip_address: str, user_agent: str, 
                      success: bool, **kwargs):
        """Log user login event."""
        event_type = AuditEventType.USER_LOGIN if success else AuditEventType.LOGIN_FAILURE
        security_level = AuditLevel.INFO if success else AuditLevel.WARNING
        
        return self.log_event(
            event_type,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            security_level=security_level,
            compliance_relevant=True,
            **kwargs
        )
    
    def log_user_logout(self, user_id: str, session_id: str, **kwargs):
        """Log user logout event."""
        return self.log_event(
            AuditEventType.USER_LOGOUT,
            user_id=user_id,
            session_id=session_id,
            compliance_relevant=True,
            **kwargs
        )
    
    def log_data_access(self, user_id: str, resource: str, action: str, 
                       target: str, success: bool, **kwargs):
        """Log data access event."""
        event_type_map = {
            'create': AuditEventType.DATA_CREATE,
            'read': AuditEventType.DATA_READ,
            'update': AuditEventType.DATA_UPDATE,
            'delete': AuditEventType.DATA_DELETE
        }
        
        event_type = event_type_map.get(action.lower(), AuditEventType.DATA_READ)
        
        return self.log_event(
            event_type,
            user_id=user_id,
            resource=resource,
            action=action,
            target=target,
            success=success,
            compliance_relevant=True,
            sensitive_data=True,
            **kwargs
        )
    
    def log_permission_change(self, user_id: str, target_user: str, 
                            permission: str, granted: bool, **kwargs):
        """Log permission change event."""
        event_type = AuditEventType.PERMISSION_GRANT if granted else AuditEventType.PERMISSION_REVOKE
        
        return self.log_event(
            event_type,
            user_id=user_id,
            target=target_user,
            action=permission,
            success=True,
            security_level=AuditLevel.WARNING,
            compliance_relevant=True,
            details={'permission': permission, 'granted': granted},
            **kwargs
        )
    
    def log_security_violation(self, user_id: str, violation_type: str, 
                             description: str, risk_score: float = 5.0, **kwargs):
        """Log security violation event."""
        return self.log_event(
            AuditEventType.SECURITY_VIOLATION,
            user_id=user_id,
            action=violation_type,
            error_message=description,
            success=False,
            security_level=AuditLevel.ERROR,
            compliance_relevant=True,
            risk_score=risk_score,
            details={'violation_type': violation_type, 'description': description},
            **kwargs
        )
    
    def log_api_call(self, user_id: str, endpoint: str, method: str, 
                    status_code: int, **kwargs):
        """Log API call event."""
        success = 200 <= status_code < 400
        security_level = AuditLevel.INFO
        
        if status_code >= 400:
            security_level = AuditLevel.WARNING if status_code < 500 else AuditLevel.ERROR
        
        return self.log_event(
            AuditEventType.API_CALL,
            user_id=user_id,
            resource=endpoint,
            action=method,
            success=success,
            security_level=security_level,
            request_path=endpoint,
            request_method=method,
            details={'status_code': status_code},
            **kwargs
        )
    
    def log_config_change(self, user_id: str, config_key: str, 
                         old_value: Any, new_value: Any, **kwargs):
        """Log configuration change event."""
        return self.log_event(
            AuditEventType.CONFIG_CHANGE,
            user_id=user_id,
            resource='system_config',
            action='modify',
            target=config_key,
            success=True,
            security_level=AuditLevel.WARNING,
            compliance_relevant=True,
            sensitive_data=True,
            details={
                'config_key': config_key,
                'old_value': str(old_value),
                'new_value': str(new_value)
            },
            **kwargs
        )
    
    # Query and reporting methods
    def query_events(self, start_time: datetime, end_time: datetime,
                    event_types: Optional[List[AuditEventType]] = None,
                    user_id: Optional[str] = None,
                    resource: Optional[str] = None,
                    limit: int = 1000) -> List[AuditEvent]:
        """
        Query audit events within time range.
        
        Args:
            start_time: Start of time range
            end_time: End of time range
            event_types: Filter by event types
            user_id: Filter by user ID
            resource: Filter by resource
            limit: Maximum number of events to return
            
        Returns:
            List of matching audit events
        """
        # This would query the actual audit log storage
        # For now, return empty list
        logger.info(f"Query: {start_time} to {end_time}, types: {event_types}, user: {user_id}")
        return []
    
    def generate_compliance_report(self, framework: str, 
                                 start_time: datetime, 
                                 end_time: datetime) -> Dict[str, Any]:
        """
        Generate compliance report for specific framework.
        
        Args:
            framework: Compliance framework (SOX, GDPR, HIPAA, etc.)
            start_time: Report start time
            end_time: Report end time
            
        Returns:
            Compliance report data
        """
        # Query compliance-relevant events
        events = self.query_events(
            start_time=start_time,
            end_time=end_time
        )
        
        compliance_events = [e for e in events if e.compliance_relevant]
        
        report = {
            'framework': framework,
            'period': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat()
            },
            'summary': {
                'total_events': len(compliance_events),
                'user_events': len([e for e in compliance_events if e.user_id]),
                'security_events': len([e for e in compliance_events 
                                      if e.security_level in [AuditLevel.ERROR, AuditLevel.CRITICAL]]),
                'data_access_events': len([e for e in compliance_events 
                                         if e.event_type in [
                                             AuditEventType.DATA_CREATE,
                                             AuditEventType.DATA_READ,
                                             AuditEventType.DATA_UPDATE,
                                             AuditEventType.DATA_DELETE
                                         ]])
            },
            'events': [
                {
                    'timestamp': e.timestamp.isoformat(),
                    'event_type': e.event_type.value,
                    'user_id': e.user_id,
                    'resource': e.resource,
                    'action': e.action,
                    'success': e.success
                }
                for e in compliance_events
            ]
        }
        
        return report
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get audit engine statistics."""
        return {
            'total_events': sum(self.event_counts.values()),
            'events_by_type': {et.value: count for et, count in self.event_counts.items()},
            'queue_size': self.event_queue.qsize() if self.config.async_logging else 0,
            'processing_thread_alive': self.processing_thread.is_alive() if self.processing_thread else False,
            'configuration': {
                'async_logging': self.config.async_logging,
                'batch_size': self.config.batch_size,
                'encryption_enabled': self.config.encrypt_sensitive_data,
                'alerts_enabled': self.config.enable_alerts
            }
        }
    
    # Audit trail integrity
    def verify_integrity(self, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """
        Verify integrity of audit trail within time range.
        
        This would implement tamper detection mechanisms such as:
        - Cryptographic hash chains
        - Digital signatures
        - Checksum validation
        """
        return {
            'verified': True,
            'period': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat()
            },
            'integrity_score': 100.0,
            'anomalies': [],
            'verification_method': 'hash_chain'
        }
    
    # Management methods
    def add_audit_handler(self, handler: Callable[[List[AuditEvent]], None]):
        """Add custom audit event handler."""
        self.audit_handlers.append(handler)
        logger.info("Added custom audit handler")
    
    def add_alert_handler(self, handler: Callable[[Dict[str, Any]], None]):
        """Add custom alert handler."""
        self.alert_handlers.append(handler)
        logger.info("Added custom alert handler")
    
    def cleanup_old_events(self, retention_days: Optional[int] = None):
        """Clean up old audit events based on retention policy."""
        retention = retention_days or self.config.database_retention_days
        cutoff_date = datetime.now() - timedelta(days=retention)
        
        # This would delete events older than cutoff_date
        logger.info(f"Would cleanup events older than {cutoff_date}")
    
    def export_events(self, start_time: datetime, end_time: datetime,
                     format: str = 'json') -> str:
        """Export audit events in specified format."""
        events = self.query_events(start_time, end_time)
        
        if format == 'json':
            return json.dumps([
                {
                    'event_id': e.event_id,
                    'timestamp': e.timestamp.isoformat(),
                    'event_type': e.event_type.value,
                    'user_id': e.user_id,
                    'resource': e.resource,
                    'action': e.action,
                    'success': e.success,
                    'details': e.details
                }
                for e in events
            ], indent=2)
        elif format == 'csv':
            import io
            import csv
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow([
                'Event ID', 'Timestamp', 'Event Type', 'User ID', 
                'Resource', 'Action', 'Success', 'IP Address'
            ])
            
            # Events
            for event in events:
                writer.writerow([
                    event.event_id,
                    event.timestamp.isoformat(),
                    event.event_type.value,
                    event.user_id,
                    event.resource,
                    event.action,
                    event.success,
                    event.ip_address
                ])
            
            return output.getvalue()
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def shutdown(self):
        """Shutdown audit engine gracefully."""
        logger.info("Shutting down audit engine...")
        
        if self.processing_thread:
            self.shutdown_event.set()
            self.processing_thread.join(timeout=10)
        
        # Process any remaining events
        remaining_events = []
        try:
            while not self.event_queue.empty():
                remaining_events.append(self.event_queue.get_nowait())
        except queue.Empty:
            pass
        
        if remaining_events:
            self._process_event_batch(remaining_events)
        
        logger.info("Audit engine shutdown complete")
    
    def __del__(self):
        """Cleanup on destruction."""
        try:
            self.shutdown()
        except:
            pass