"""
SQLAlchemy models for the PgAppForge alerting system.

Provides database persistence for alert rules, history, and configuration
following PgAppForge's model patterns and conventions.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from typing import Optional, Dict, Any, List

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from pgappforge.security.sqla.models import User

# Alert severity levels
class AlertSeverity(str, Enum):
    """Alert severity levels in order of importance."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def get_choices(cls):
        """Get choices for form fields."""
        return [
            (cls.LOW.value, "Low"),
            (cls.MEDIUM.value, "Medium"), 
            (cls.HIGH.value, "High"),
            (cls.CRITICAL.value, "Critical")
        ]

# Alert status types
class AlertStatus(str, Enum):
    """Alert status types."""
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged" 
    RESOLVED = "resolved"
    EXPIRED = "expired"

    @classmethod
    def get_choices(cls):
        """Get choices for form fields."""
        return [
            (cls.ACTIVE.value, "Active"),
            (cls.ACKNOWLEDGED.value, "Acknowledged"),
            (cls.RESOLVED.value, "Resolved"),
            (cls.EXPIRED.value, "Expired")
        ]

# Comparison operators for alert conditions
class AlertCondition(str, Enum):
    """Alert condition operators."""
    GREATER_THAN = ">"
    GREATER_EQUAL = ">="
    LESS_THAN = "<"
    LESS_EQUAL = "<="
    EQUAL = "=="
    NOT_EQUAL = "!="

    @classmethod
    def get_choices(cls):
        """Get choices for form fields."""
        return [
            (cls.GREATER_THAN.value, "Greater Than (>)"),
            (cls.GREATER_EQUAL.value, "Greater Than or Equal (>=)"),
            (cls.LESS_THAN.value, "Less Than (<)"),
            (cls.LESS_EQUAL.value, "Less Than or Equal (<=)"),
            (cls.EQUAL.value, "Equal (==)"),
            (cls.NOT_EQUAL.value, "Not Equal (!=)")
        ]


class AlertRule(AuditMixin, Model):
    """
    Alert rule configuration model.
    
    Defines rules for monitoring metrics and triggering alerts
    when conditions are met.
    """
    __tablename__ = 'alert_rules'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    
    # Metric configuration
    metric_name = Column(String(255), nullable=False)
    condition = Column(SQLEnum(AlertCondition), nullable=False, default=AlertCondition.GREATER_THAN)
    threshold_value = Column(Float, nullable=False)
    
    # Alert configuration
    severity = Column(SQLEnum(AlertSeverity), nullable=False, default=AlertSeverity.MEDIUM)
    enabled = Column(Boolean, nullable=False, default=True)
    cooldown_minutes = Column(Integer, default=15)
    
    # Notification settings (JSON field)
    notification_channels = Column(JSON, default=lambda: ["email"])
    notification_settings = Column(JSON, default=dict)
    
    # Metadata
    tags = Column(JSON, default=list)
    additional_config = Column(JSON, default=dict)
    
    def __repr__(self):
        return f"<AlertRule {self.name}>"

    def is_condition_met(self, value: float) -> bool:
        """Check if the given value meets the alert condition."""
        try:
            if self.condition == AlertCondition.GREATER_THAN:
                return value > self.threshold_value
            elif self.condition == AlertCondition.GREATER_EQUAL:
                return value >= self.threshold_value
            elif self.condition == AlertCondition.LESS_THAN:
                return value < self.threshold_value
            elif self.condition == AlertCondition.LESS_EQUAL:
                return value <= self.threshold_value
            elif self.condition == AlertCondition.EQUAL:
                return abs(value - self.threshold_value) < 1e-9
            elif self.condition == AlertCondition.NOT_EQUAL:
                return abs(value - self.threshold_value) >= 1e-9
            return False
        except (TypeError, ValueError):
            return False

    def get_condition_display(self) -> str:
        """Get human-readable condition display."""
        return f"{self.metric_name} {self.condition.value} {self.threshold_value}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'metric_name': self.metric_name,
            'condition': self.condition.value,
            'threshold_value': self.threshold_value,
            'severity': self.severity.value,
            'enabled': self.enabled,
            'cooldown_minutes': self.cooldown_minutes,
            'notification_channels': self.notification_channels or [],
            'created_at': self.created_on.isoformat() if self.created_on else None,
            'created_by': self.created_by_fk,
            'tags': self.tags or []
        }


class AlertHistory(AuditMixin, Model):
    """
    Alert history model.
    
    Records all triggered alerts with their lifecycle events
    (triggered, acknowledged, resolved).
    """
    __tablename__ = 'alert_history'

    id = Column(Integer, primary_key=True)
    
    # Related alert rule (nullable in case rule is deleted)
    rule_id = Column(Integer, nullable=True)
    rule_name = Column(String(255), nullable=False)  # Snapshot of rule name
    rule_description = Column(Text)  # Snapshot of rule description
    
    # Metric information at time of alert
    metric_name = Column(String(255), nullable=False)
    metric_value = Column(Float)
    condition = Column(String(50))  # Snapshot of condition
    threshold_value = Column(Float)  # Snapshot of threshold
    
    # Alert details
    severity = Column(SQLEnum(AlertSeverity), nullable=False)
    status = Column(SQLEnum(AlertStatus), nullable=False, default=AlertStatus.ACTIVE)
    message = Column(Text)
    
    # Timestamps
    triggered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    acknowledged_at = Column(DateTime)
    resolved_at = Column(DateTime)
    
    # User actions
    acknowledged_by_fk = Column(Integer)
    resolved_by_fk = Column(Integer)
    
    # Additional data
    context_data = Column(JSON, default=dict)  # Additional context at time of alert
    notification_log = Column(JSON, default=list)  # Log of notifications sent
    
    def __repr__(self):
        return f"<AlertHistory {self.rule_name} - {self.status.value}>"

    @property
    def duration(self) -> Optional[timedelta]:
        """Get alert duration if resolved."""
        if self.resolved_at and self.triggered_at:
            return self.resolved_at - self.triggered_at
        return None

    @property
    def duration_display(self) -> str:
        """Get human-readable duration."""
        if not self.duration:
            return "Ongoing"
        
        seconds = int(self.duration.total_seconds())
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"

    def acknowledge(self, user_id: Optional[int] = None):
        """Mark alert as acknowledged."""
        if self.status == AlertStatus.ACTIVE:
            self.status = AlertStatus.ACKNOWLEDGED
            self.acknowledged_at = datetime.now(tz=timezone.utc)
            self.acknowledged_by_fk = user_id

    def resolve(self, user_id: Optional[int] = None):
        """Mark alert as resolved."""
        if self.status in [AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED]:
            self.status = AlertStatus.RESOLVED
            self.resolved_at = datetime.now(tz=timezone.utc)
            self.resolved_by_fk = user_id

    def add_notification_log(self, channel: str, status: str, details: str = ""):
        """Add notification log entry."""
        log_entry = {
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'channel': channel,
            'status': status,
            'details': details
        }
        
        if not self.notification_log:
            self.notification_log = []
        self.notification_log.append(log_entry)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'rule_id': self.rule_id,
            'rule_name': self.rule_name,
            'rule_description': self.rule_description,
            'metric_name': self.metric_name,
            'metric_value': self.metric_value,
            'condition': self.condition,
            'threshold_value': self.threshold_value,
            'severity': self.severity.value,
            'status': self.status.value,
            'message': self.message,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'duration': self.duration_display,
            'acknowledged_by': self.acknowledged_by_fk,
            'resolved_by': self.resolved_by_fk,
            'notification_count': len(self.notification_log or [])
        }


class MetricSnapshot(Model):
    """
    Metric data snapshots for historical analysis.
    
    Stores periodic snapshots of metric values to enable
    trend analysis and alert condition evaluation.
    """
    __tablename__ = 'metric_snapshots'

    id = Column(Integer, primary_key=True)
    metric_name = Column(String(255), nullable=False, index=True)
    value = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Source information
    source = Column(String(100), default="system")
    tags = Column(JSON, default=dict)
    
    # Additional metadata
    metadata = Column(JSON, default=dict)
    
    def __repr__(self):
        return f"<MetricSnapshot {self.metric_name}={self.value} @ {self.timestamp}>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'metric_name': self.metric_name,
            'value': self.value,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source,
            'tags': self.tags or {},
            'metadata': self.metadata or {}
        }

    @classmethod
    def get_recent_values(cls, metric_name: str, hours: int = 24, session=None):
        """Get recent values for a metric."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
        query = session.query(cls).filter(
            cls.metric_name == metric_name,
            cls.timestamp >= cutoff
        ).order_by(cls.timestamp.desc())
        return query.all()

    @classmethod
    def get_latest_value(cls, metric_name: str, session=None):
        """Get the most recent value for a metric."""
        return session.query(cls).filter(
            cls.metric_name == metric_name
        ).order_by(cls.timestamp.desc()).first()


class NotificationSettings(AuditMixin, Model):
    """
    Global notification settings for the alerting system.
    
    Stores configuration for email, webhook, and in-app notifications.
    """
    __tablename__ = 'notification_settings'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True, default="default")
    
    # Email settings
    email_enabled = Column(Boolean, default=True)
    email_recipients = Column(Text)  # Comma-separated email addresses
    email_severity_filter = Column(SQLEnum(AlertSeverity), default=AlertSeverity.MEDIUM)
    email_cooldown = Column(Integer, default=15)  # minutes
    email_format = Column(String(20), default="html")  # html or text
    
    # In-app settings
    inapp_enabled = Column(Boolean, default=True)
    inapp_severity_filter = Column(SQLEnum(AlertSeverity), default=AlertSeverity.LOW)
    inapp_auto_dismiss = Column(Integer, default=0)  # seconds, 0 = manual
    inapp_sound_enabled = Column(Boolean, default=True)
    inapp_desktop_enabled = Column(Boolean, default=True)
    
    # Webhook settings
    webhook_enabled = Column(Boolean, default=False)
    webhook_urls = Column(Text)  # One URL per line
    webhook_severity_filter = Column(SQLEnum(AlertSeverity), default=AlertSeverity.HIGH)
    webhook_timeout = Column(Integer, default=30)  # seconds
    webhook_retry_enabled = Column(Boolean, default=True)
    
    # Additional configuration
    additional_config = Column(JSON, default=dict)
    
    def __repr__(self):
        return f"<NotificationSettings {self.name}>"

    def get_email_recipients(self) -> List[str]:
        """Get list of email recipients."""
        if not self.email_recipients:
            return []
        return [email.strip() for email in self.email_recipients.split(',') if email.strip()]

    def get_webhook_urls(self) -> List[str]:
        """Get list of webhook URLs."""
        if not self.webhook_urls:
            return []
        return [url.strip() for url in self.webhook_urls.split('\n') if url.strip()]

    def should_send_notification(self, channel: str, severity: AlertSeverity) -> bool:
        """Check if notification should be sent for given channel and severity."""
        if channel == "email":
            return (self.email_enabled and 
                   self._severity_meets_threshold(severity, self.email_severity_filter))
        elif channel == "inapp":
            return (self.inapp_enabled and 
                   self._severity_meets_threshold(severity, self.inapp_severity_filter))
        elif channel == "webhook":
            return (self.webhook_enabled and 
                   self._severity_meets_threshold(severity, self.webhook_severity_filter))
        return False

    def _severity_meets_threshold(self, severity: AlertSeverity, threshold: AlertSeverity) -> bool:
        """Check if severity meets the threshold for notification."""
        severity_levels = {
            AlertSeverity.LOW: 1,
            AlertSeverity.MEDIUM: 2,
            AlertSeverity.HIGH: 3,
            AlertSeverity.CRITICAL: 4
        }
        return severity_levels.get(severity, 0) >= severity_levels.get(threshold, 0)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'email_enabled': self.email_enabled,
            'email_recipients': self.get_email_recipients(),
            'email_severity_filter': self.email_severity_filter.value,
            'email_cooldown': self.email_cooldown,
            'inapp_enabled': self.inapp_enabled,
            'inapp_severity_filter': self.inapp_severity_filter.value,
            'inapp_auto_dismiss': self.inapp_auto_dismiss,
            'webhook_enabled': self.webhook_enabled,
            'webhook_urls': self.get_webhook_urls(),
            'webhook_severity_filter': self.webhook_severity_filter.value,
            'webhook_timeout': self.webhook_timeout,
            'created_at': self.created_on.isoformat() if self.created_on else None
        }