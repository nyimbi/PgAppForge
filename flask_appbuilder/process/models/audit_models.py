"""
Process Audit Models.

Database models for tracking and auditing process operations
for compliance, security monitoring, and troubleshooting.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any
import json

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

from ...models.mixins import AuditMixin, Model
from ...models.sqla import Base

class ProcessAuditLog(Base, Model):
    """
    Audit log for process operations.
    
    Tracks all significant operations performed on processes
    for security, compliance, and operational monitoring.
    """
    
    __tablename__ = 'fab_process_audit_log'
    
    # Primary identification
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Operation details
    operation = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False, index=True)
    resource_id = Column(Integer, nullable=True, index=True)
    
    # User and tenant context
    user_id = Column(Integer, nullable=True, index=True)
    username = Column(String(100), nullable=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    
    # Request context
    ip_address = Column(String(45), nullable=True)  # IPv6 support
    user_agent = Column(Text, nullable=True)
    
    # Operation outcome
    success = Column(Boolean, default=True, nullable=False, index=True)
    details = Column(Text, nullable=True)  # JSON string with additional details
    
    # Database indexes for common queries
    __table_args__ = (
        Index('ix_audit_operation_time', 'operation', 'timestamp'),
        Index('ix_audit_user_time', 'user_id', 'timestamp'),
        Index('ix_audit_tenant_time', 'tenant_id', 'timestamp'),
        Index('ix_audit_resource', 'resource_type', 'resource_id'),
        Index('ix_audit_failed', 'success', 'timestamp'),
    )
    
    def __repr__(self):
        return f'<ProcessAuditLog {self.operation} by {self.username} at {self.timestamp}>'
    
    @property
    def details_dict(self) -> Dict[str, Any]:
        """Get details as dictionary."""
        if self.details:
            try:
                return json.loads(self.details)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
    
    @details_dict.setter
    def details_dict(self, value: Dict[str, Any]):
        """Set details from dictionary."""
        if value:
            self.details = json.dumps(value, default=str)
        else:
            self.details = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'operation': self.operation,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'user_id': self.user_id,
            'username': self.username,
            'tenant_id': self.tenant_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'success': self.success,
            'details': self.details_dict
        }


class ProcessSecurityEvent(Base, Model):
    """
    Security events related to processes.
    
    Tracks security-relevant events such as authorization failures,
    suspicious activity, and policy violations.
    """
    
    __tablename__ = 'fab_process_security_event'
    
    # Event severity levels
    SEVERITY_INFO = 'info'
    SEVERITY_WARNING = 'warning'
    SEVERITY_ERROR = 'error'
    SEVERITY_CRITICAL = 'critical'
    
    SEVERITY_LEVELS = [SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL]
    
    # Event types
    TYPE_AUTH_FAILURE = 'auth_failure'
    TYPE_RATE_LIMIT = 'rate_limit'
    TYPE_TENANT_VIOLATION = 'tenant_violation'
    TYPE_VALIDATION_ERROR = 'validation_error'
    TYPE_SUSPICIOUS_ACTIVITY = 'suspicious_activity'
    TYPE_POLICY_VIOLATION = 'policy_violation'
    
    EVENT_TYPES = [
        TYPE_AUTH_FAILURE, TYPE_RATE_LIMIT, TYPE_TENANT_VIOLATION,
        TYPE_VALIDATION_ERROR, TYPE_SUSPICIOUS_ACTIVITY, TYPE_POLICY_VIOLATION
    ]
    
    # Primary identification
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Event classification
    event_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default=SEVERITY_INFO, index=True)
    
    # Event context
    resource_type = Column(String(50), nullable=True, index=True)
    resource_id = Column(Integer, nullable=True, index=True)
    
    # User and tenant context
    user_id = Column(Integer, nullable=True, index=True)
    username = Column(String(100), nullable=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    
    # Request context
    ip_address = Column(String(45), nullable=True, index=True)
    user_agent = Column(Text, nullable=True)
    endpoint = Column(String(200), nullable=True)
    
    # Event details
    message = Column(String(500), nullable=False)
    details = Column(Text, nullable=True)  # JSON string with additional details
    
    # Resolution tracking
    resolved = Column(Boolean, default=False, nullable=False, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    # Database indexes for common queries
    __table_args__ = (
        Index('ix_security_event_type_time', 'event_type', 'timestamp'),
        Index('ix_security_event_severity_time', 'severity', 'timestamp'),
        Index('ix_security_event_user_time', 'user_id', 'timestamp'),
        Index('ix_security_event_tenant_time', 'tenant_id', 'timestamp'),
        Index('ix_security_event_unresolved', 'resolved', 'severity', 'timestamp'),
        Index('ix_security_event_ip', 'ip_address', 'timestamp'),
    )
    
    def __repr__(self):
        return f'<ProcessSecurityEvent {self.event_type} {self.severity} at {self.timestamp}>'
    
    @property
    def details_dict(self) -> Dict[str, Any]:
        """Get details as dictionary."""
        if self.details:
            try:
                return json.loads(self.details)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
    
    @details_dict.setter
    def details_dict(self, value: Dict[str, Any]):
        """Set details from dictionary."""
        if value:
            self.details = json.dumps(value, default=str)
        else:
            self.details = None
    
    def resolve(self, resolved_by_user_id: int, notes: str = None):
        """Mark security event as resolved."""
        self.resolved = True
        self.resolved_at = datetime.now(tz=timezone.utc)
        self.resolved_by = resolved_by_user_id
        self.resolution_notes = notes
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'event_type': self.event_type,
            'severity': self.severity,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'user_id': self.user_id,
            'username': self.username,
            'tenant_id': self.tenant_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'endpoint': self.endpoint,
            'message': self.message,
            'details': self.details_dict,
            'resolved': self.resolved,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolved_by': self.resolved_by,
            'resolution_notes': self.resolution_notes
        }


class ProcessComplianceLog(Base, Model):
    """
    Compliance logging for processes.
    
    Tracks compliance-related activities and maintains
    audit trails for regulatory requirements.
    """
    
    __tablename__ = 'fab_process_compliance_log'
    
    # Compliance frameworks
    FRAMEWORK_SOX = 'sox'
    FRAMEWORK_GDPR = 'gdpr'
    FRAMEWORK_HIPAA = 'hipaa'
    FRAMEWORK_PCI_DSS = 'pci_dss'
    FRAMEWORK_ISO27001 = 'iso27001'
    FRAMEWORK_CUSTOM = 'custom'
    
    COMPLIANCE_FRAMEWORKS = [
        FRAMEWORK_SOX, FRAMEWORK_GDPR, FRAMEWORK_HIPAA,
        FRAMEWORK_PCI_DSS, FRAMEWORK_ISO27001, FRAMEWORK_CUSTOM
    ]
    
    # Compliance event types
    TYPE_DATA_ACCESS = 'data_access'
    TYPE_DATA_MODIFICATION = 'data_modification'
    TYPE_DATA_DELETION = 'data_deletion'
    TYPE_PRIVILEGE_ESCALATION = 'privilege_escalation'
    TYPE_CONFIGURATION_CHANGE = 'configuration_change'
    TYPE_POLICY_ENFORCEMENT = 'policy_enforcement'
    
    COMPLIANCE_EVENT_TYPES = [
        TYPE_DATA_ACCESS, TYPE_DATA_MODIFICATION, TYPE_DATA_DELETION,
        TYPE_PRIVILEGE_ESCALATION, TYPE_CONFIGURATION_CHANGE, TYPE_POLICY_ENFORCEMENT
    ]
    
    # Primary identification
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Compliance context
    framework = Column(String(50), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    
    # Resource context
    resource_type = Column(String(50), nullable=False, index=True)
    resource_id = Column(Integer, nullable=True, index=True)
    
    # User and tenant context
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(100), nullable=False, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    
    # Compliance details
    description = Column(String(500), nullable=False)
    justification = Column(Text, nullable=True)  # Business justification
    approver_id = Column(Integer, nullable=True)  # Who approved this action
    
    # Data context (for data protection compliance)
    data_classification = Column(String(50), nullable=True)  # public, internal, confidential, restricted
    data_categories = Column(String(200), nullable=True)  # PII, PHI, financial, etc.
    
    # Additional metadata
    metadata = Column(Text, nullable=True)  # JSON string with additional metadata
    
    # Retention and archival
    retention_period = Column(Integer, nullable=True)  # Days to retain
    archived = Column(Boolean, default=False, nullable=False)
    archived_at = Column(DateTime, nullable=True)
    
    # Database indexes for compliance queries
    __table_args__ = (
        Index('ix_compliance_framework_time', 'framework', 'timestamp'),
        Index('ix_compliance_event_time', 'event_type', 'timestamp'),
        Index('ix_compliance_user_time', 'user_id', 'timestamp'),
        Index('ix_compliance_tenant_time', 'tenant_id', 'timestamp'),
        Index('ix_compliance_resource', 'resource_type', 'resource_id'),
        Index('ix_compliance_data_class', 'data_classification', 'timestamp'),
        Index('ix_compliance_archived', 'archived', 'timestamp'),
    )
    
    def __repr__(self):
        return f'<ProcessComplianceLog {self.framework} {self.event_type} by {self.username} at {self.timestamp}>'
    
    @property
    def metadata_dict(self) -> Dict[str, Any]:
        """Get metadata as dictionary."""
        if self.metadata:
            try:
                return json.loads(self.metadata)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
    
    @metadata_dict.setter
    def metadata_dict(self, value: Dict[str, Any]):
        """Set metadata from dictionary."""
        if value:
            self.metadata = json.dumps(value, default=str)
        else:
            self.metadata = None
    
    def archive(self):
        """Mark compliance log as archived."""
        self.archived = True
        self.archived_at = datetime.now(tz=timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'framework': self.framework,
            'event_type': self.event_type,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'user_id': self.user_id,
            'username': self.username,
            'tenant_id': self.tenant_id,
            'description': self.description,
            'justification': self.justification,
            'approver_id': self.approver_id,
            'data_classification': self.data_classification,
            'data_categories': self.data_categories,
            'metadata': self.metadata_dict,
            'retention_period': self.retention_period,
            'archived': self.archived,
            'archived_at': self.archived_at.isoformat() if self.archived_at else None
        }