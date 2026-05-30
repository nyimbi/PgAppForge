"""
Notification Service for alert delivery.

Provides multiple notification channels (email, in-app, webhook) for 
delivering alert notifications with customizable templates and formatting.
"""

import logging
import json
from enum import Enum
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from dataclasses import dataclass
from abc import ABC, abstractmethod

from flask import current_app, render_template_string
from flask_login import current_user

log = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """Available notification channels."""
    EMAIL = "email"
    IN_APP = "in_app"
    WEBHOOK = "webhook"
    SLACK = "slack"
    SMS = "sms"


class NotificationPriority(Enum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class NotificationTemplate:
    """
    Template for formatting notifications.
    """
    channel: NotificationChannel
    subject_template: str
    body_template: str
    format_type: str = "text"  # text, html, json
    variables: Optional[Dict[str, str]] = None


@dataclass
class NotificationRecipient:
    """
    Notification recipient configuration.
    """
    id: str
    name: str
    channels: List[NotificationChannel]
    channel_configs: Dict[str, Dict[str, Any]]  # Channel-specific config
    alert_filters: Optional[Dict[str, Any]] = None  # Filtering rules
    
    def __post_init__(self):
        if self.channel_configs is None:
            self.channel_configs = {}


class NotificationProvider(ABC):
    """Abstract base class for notification providers."""
    
    @abstractmethod
    def send_notification(self, 
                         recipient: NotificationRecipient,
                         subject: str,
                         content: str,
                         priority: NotificationPriority = NotificationPriority.NORMAL,
                         metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Send a notification.
        
        Args:
            recipient: Recipient configuration
            subject: Notification subject
            content: Notification content
            priority: Notification priority
            metadata: Additional metadata
            
        Returns:
            True if successful
        """
        pass


class EmailNotificationProvider(NotificationProvider):
    """Email notification provider."""
    
    def __init__(self, app=None):
        """Initialize email provider."""
        self.app = app
        self.mail = None
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize with Flask app."""
        self.app = app
        
        # Try to initialize Flask-Mail if available
        try:
            from flask_mail import Mail, Message
            self.mail = Mail(app)
            self.Message = Message
            log.info("Email notification provider initialized with Flask-Mail")
        except ImportError:
            log.warning("Flask-Mail not available - email notifications disabled")
    
    def send_notification(self, 
                         recipient: NotificationRecipient,
                         subject: str,
                         content: str,
                         priority: NotificationPriority = NotificationPriority.NORMAL,
                         metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Send email notification."""
        try:
            if not self.mail:
                log.warning("Email provider not initialized")
                return False
            
            # Get email address from recipient config
            email_config = recipient.channel_configs.get('email', {})
            email_address = email_config.get('address')
            
            if not email_address:
                log.warning(f"No email address configured for recipient {recipient.id}")
                return False
            
            # Create message
            msg = self.Message(
                subject=subject,
                recipients=[email_address],
                body=content,
                sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'alerts@example.com')
            )
            
            # Add priority header if needed
            if priority == NotificationPriority.URGENT:
                msg.extra_headers = {'X-Priority': '1'}
            elif priority == NotificationPriority.HIGH:
                msg.extra_headers = {'X-Priority': '2'}
            
            # Send email
            self.mail.send(msg)
            log.info(f"Email notification sent to {email_address}")
            return True
            
        except Exception as e:
            log.error(f"Error sending email notification: {e}")
            return False


class InAppNotificationProvider(NotificationProvider):
    """In-app notification provider."""
    
    def __init__(self):
        """Initialize in-app provider."""
        # In-memory storage (use database in production)
        self._notifications = {}  # user_id -> [notifications]
    
    def send_notification(self, 
                         recipient: NotificationRecipient,
                         subject: str,
                         content: str,
                         priority: NotificationPriority = NotificationPriority.NORMAL,
                         metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Send in-app notification."""
        try:
            # Get user ID from recipient
            user_id = recipient.id
            
            # Create notification
            notification = {
                'id': f"notification_{datetime.now().timestamp()}",
                'subject': subject,
                'content': content,
                'priority': priority.value,
                'created_at': datetime.now().isoformat(),
                'read': False,
                'metadata': metadata or {}
            }
            
            # Store notification
            if user_id not in self._notifications:
                self._notifications[user_id] = []
            
            self._notifications[user_id].append(notification)
            
            # Limit notification count per user
            if len(self._notifications[user_id]) > 100:
                self._notifications[user_id].pop(0)
            
            log.info(f"In-app notification created for user {user_id}")
            return True
            
        except Exception as e:
            log.error(f"Error sending in-app notification: {e}")
            return False
    
    def get_user_notifications(self, user_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        """Get notifications for a user."""
        if user_id not in self._notifications:
            return []
        
        notifications = self._notifications[user_id]
        
        if unread_only:
            notifications = [n for n in notifications if not n['read']]
        
        return sorted(notifications, key=lambda n: n['created_at'], reverse=True)
    
    def mark_notification_read(self, user_id: str, notification_id: str) -> bool:
        """Mark notification as read."""
        try:
            if user_id in self._notifications:
                for notification in self._notifications[user_id]:
                    if notification['id'] == notification_id:
                        notification['read'] = True
                        return True
            return False
            
        except Exception as e:
            log.error(f"Error marking notification as read: {e}")
            return False


class WebhookNotificationProvider(NotificationProvider):
    """Webhook notification provider."""
    
    def __init__(self):
        """Initialize webhook provider."""
        pass
    
    def send_notification(self, 
                         recipient: NotificationRecipient,
                         subject: str,
                         content: str,
                         priority: NotificationPriority = NotificationPriority.NORMAL,
                         metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Send webhook notification."""
        try:
            import requests
            
            # Get webhook config
            webhook_config = recipient.channel_configs.get('webhook', {})
            webhook_url = webhook_config.get('url')
            
            if not webhook_url:
                log.warning(f"No webhook URL configured for recipient {recipient.id}")
                return False
            
            # Prepare payload
            payload = {
                'subject': subject,
                'content': content,
                'priority': priority.value,
                'timestamp': datetime.now().isoformat(),
                'recipient': recipient.id,
                'metadata': metadata or {}
            }
            
            # Send webhook
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'PgForge-Alerts/1.0'
            }
            
            # Add custom headers if configured
            custom_headers = webhook_config.get('headers', {})
            headers.update(custom_headers)
            
            response = requests.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            log.info(f"Webhook notification sent to {webhook_url}")
            return True
            
        except ImportError:
            log.error("requests library not available for webhook notifications")
            return False
        except Exception as e:
            log.error(f"Error sending webhook notification: {e}")
            return False


class NotificationService:
    """
    Central notification service.
    
    Manages notification templates, recipients, and delivery through
    multiple channels with support for filtering and customization.
    """
    
    def __init__(self, app=None):
        """Initialize notification service."""
        self.app = app
        self._providers = {}
        self._templates = {}
        self._recipients = {}
        self._notification_history = []
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize with Flask app."""
        self.app = app
        
        # Initialize default providers
        self._init_default_providers()
        
        # Initialize default templates
        self._init_default_templates()
        
        # Store reference in app
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        app.extensions['notification_service'] = self
        
        log.info("Notification Service initialized")
    
    def _init_default_providers(self):
        """Initialize default notification providers."""
        # Email provider
        email_provider = EmailNotificationProvider(self.app)
        self._providers[NotificationChannel.EMAIL] = email_provider
        
        # In-app provider
        in_app_provider = InAppNotificationProvider()
        self._providers[NotificationChannel.IN_APP] = in_app_provider
        
        # Webhook provider
        webhook_provider = WebhookNotificationProvider()
        self._providers[NotificationChannel.WEBHOOK] = webhook_provider
        
        log.info("Default notification providers initialized")
    
    def _init_default_templates(self):
        """Initialize default notification templates."""
        # Email templates
        self._templates['alert_email'] = NotificationTemplate(
            channel=NotificationChannel.EMAIL,
            subject_template="Alert: {{ alert.name }} - {{ alert.severity.value.upper() }}",
            body_template="""
Alert Notification

Alert: {{ alert.name }}
Severity: {{ alert.severity.value.upper() }}
Metric: {{ alert.metric_name }}
Current Value: {{ alert.current_value }}
Threshold: {{ alert.condition }} {{ alert.threshold_value }}
Triggered: {{ alert.created_at.strftime('%Y-%m-%d %H:%M:%S') }}

Description:
{{ alert.description }}

{% if rule.notification_channels %}
This alert was configured to notify: {{ rule.notification_channels|join(', ') }}
{% endif %}

---
This alert was generated by PgForge Alert System
""",
            format_type="text"
        )
        
        # In-app templates
        self._templates['alert_in_app'] = NotificationTemplate(
            channel=NotificationChannel.IN_APP,
            subject_template="{{ alert.name }}",
            body_template="Alert triggered for {{ alert.metric_name }}: {{ alert.current_value }} {{ alert.condition }} {{ alert.threshold_value }}",
            format_type="text"
        )
        
        # Webhook templates
        self._templates['alert_webhook'] = NotificationTemplate(
            channel=NotificationChannel.WEBHOOK,
            subject_template="Alert: {{ alert.name }}",
            body_template="""
{
  "alert_id": "{{ alert.id }}",
  "alert_name": "{{ alert.name }}",
  "severity": "{{ alert.severity.value }}",
  "status": "{{ alert.status.value }}",
  "metric_name": "{{ alert.metric_name }}",
  "current_value": {{ alert.current_value }},
  "threshold_value": {{ alert.threshold_value }},
  "condition": "{{ alert.condition }}",
  "created_at": "{{ alert.created_at.isoformat() }}",
  "description": "{{ alert.description }}",
  "rule_id": "{{ rule.id if rule else 'unknown' }}"
}
""",
            format_type="json"
        )
    
    def register_provider(self, channel: NotificationChannel, provider: NotificationProvider):
        """Register a custom notification provider."""
        self._providers[channel] = provider
        log.info(f"Registered custom provider for {channel.value}")
    
    def register_template(self, name: str, template: NotificationTemplate):
        """Register a custom notification template."""
        self._templates[name] = template
        log.info(f"Registered notification template: {name}")
    
    def add_recipient(self, recipient: NotificationRecipient):
        """Add a notification recipient."""
        self._recipients[recipient.id] = recipient
        log.info(f"Added notification recipient: {recipient.name}")
    
    def remove_recipient(self, recipient_id: str) -> bool:
        """Remove a notification recipient."""
        if recipient_id in self._recipients:
            del self._recipients[recipient_id]
            log.info(f"Removed notification recipient: {recipient_id}")
            return True
        return False
    
    def get_recipient(self, recipient_id: str) -> Optional[NotificationRecipient]:
        """Get recipient by ID."""
        return self._recipients.get(recipient_id)
    
    def send_alert_notification(self, alert, rule):
        """
        Send notifications for an alert.
        
        Args:
            alert: Alert instance
            rule: AlertRule instance that triggered the alert
        """
        try:
            # Get notification channels from rule
            channels = rule.notification_channels or ['in_app']
            
            for channel_name in channels:
                try:
                    channel = NotificationChannel(channel_name)
                    self._send_alert_to_channel(alert, rule, channel)
                except ValueError:
                    log.warning(f"Unknown notification channel: {channel_name}")
                    
        except Exception as e:
            log.error(f"Error sending alert notifications: {e}")
    
    def _send_alert_to_channel(self, alert, rule, channel: NotificationChannel):
        """Send alert notification to specific channel."""
        try:
            # Get provider for channel
            if channel not in self._providers:
                log.warning(f"No provider registered for channel {channel.value}")
                return
            
            provider = self._providers[channel]
            
            # Get template for channel
            template_name = f"alert_{channel.value}"
            if template_name not in self._templates:
                log.warning(f"No template found for {template_name}")
                return
            
            template = self._templates[template_name]
            
            # Render notification content
            subject = self._render_template(template.subject_template, alert=alert, rule=rule)
            content = self._render_template(template.body_template, alert=alert, rule=rule)
            
            # Determine priority based on alert severity
            priority_mapping = {
                'low': NotificationPriority.LOW,
                'medium': NotificationPriority.NORMAL,
                'high': NotificationPriority.HIGH,
                'critical': NotificationPriority.URGENT
            }
            priority = priority_mapping.get(alert.severity.value, NotificationPriority.NORMAL)
            
            # Send to all matching recipients
            sent_count = 0
            for recipient in self._recipients.values():
                if channel in recipient.channels:
                    # Check if recipient should receive this alert
                    if self._should_notify_recipient(recipient, alert, rule):
                        success = provider.send_notification(
                            recipient=recipient,
                            subject=subject,
                            content=content,
                            priority=priority,
                            metadata={
                                'alert_id': alert.id,
                                'rule_id': rule.id,
                                'channel': channel.value
                            }
                        )
                        
                        if success:
                            sent_count += 1
            
            log.info(f"Sent alert notification via {channel.value} to {sent_count} recipients")
            
            # Record notification history
            self._record_notification_history(alert, rule, channel, sent_count)
            
        except Exception as e:
            log.error(f"Error sending alert to channel {channel.value}: {e}")
    
    def _render_template(self, template_str: str, **context) -> str:
        """Render notification template with context."""
        try:
            return render_template_string(template_str, **context)
        except Exception as e:
            log.error(f"Error rendering template: {e}")
            return template_str  # Return original template if rendering fails
    
    def _should_notify_recipient(self, recipient: NotificationRecipient, alert, rule) -> bool:
        """Check if recipient should be notified for this alert."""
        try:
            # Check alert filters if configured
            if recipient.alert_filters:
                filters = recipient.alert_filters
                
                # Severity filter
                if 'min_severity' in filters:
                    min_severity = filters['min_severity']
                    severity_levels = ['low', 'medium', 'high', 'critical']
                    
                    if severity_levels.index(alert.severity.value) < severity_levels.index(min_severity):
                        return False
                
                # Metric filter
                if 'metrics' in filters:
                    allowed_metrics = filters['metrics']
                    if alert.metric_name not in allowed_metrics:
                        return False
                
                # Time-based filter (e.g., business hours only)
                if 'time_filter' in filters:
                    # Implementation would depend on specific requirements
                    pass
            
            return True
            
        except Exception as e:
            log.error(f"Error checking recipient filters: {e}")
            return True  # Default to sending if filter check fails
    
    def _record_notification_history(self, alert, rule, channel: NotificationChannel, recipient_count: int):
        """Record notification in history."""
        history_entry = {
            'alert_id': alert.id,
            'rule_id': rule.id,
            'channel': channel.value,
            'recipient_count': recipient_count,
            'sent_at': datetime.now().isoformat(),
            'alert_severity': alert.severity.value,
            'metric_name': alert.metric_name
        }
        
        self._notification_history.append(history_entry)
        
        # Limit history size
        if len(self._notification_history) > 1000:
            self._notification_history.pop(0)
    
    def get_notification_history(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get notification history."""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            cutoff_str = cutoff_date.isoformat()
            
            return [
                entry for entry in self._notification_history
                if entry['sent_at'] >= cutoff_str
            ]
            
        except Exception as e:
            log.error(f"Error getting notification history: {e}")
            return []
    
    def get_notification_stats(self) -> Dict[str, Any]:
        """Get notification statistics."""
        try:
            recent_history = self.get_notification_history(days=7)
            
            # Count by channel
            channel_counts = {}
            for entry in recent_history:
                channel = entry['channel']
                channel_counts[channel] = channel_counts.get(channel, 0) + 1
            
            # Count by severity
            severity_counts = {}
            for entry in recent_history:
                severity = entry['alert_severity']
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
            
            return {
                'total_recipients': len(self._recipients),
                'active_providers': len(self._providers),
                'available_templates': len(self._templates),
                'recent_notifications': len(recent_history),
                'channel_breakdown': channel_counts,
                'severity_breakdown': severity_counts,
                'last_notification': recent_history[0]['sent_at'] if recent_history else None
            }
            
        except Exception as e:
            log.error(f"Error getting notification stats: {e}")
            return {}
    
    def get_in_app_notifications(self, user_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        """Get in-app notifications for a user."""
        if NotificationChannel.IN_APP in self._providers:
            provider = self._providers[NotificationChannel.IN_APP]
            if isinstance(provider, InAppNotificationProvider):
                return provider.get_user_notifications(user_id, unread_only)
        
        return []
    
    def mark_notification_read(self, user_id: str, notification_id: str) -> bool:
        """Mark in-app notification as read."""
        if NotificationChannel.IN_APP in self._providers:
            provider = self._providers[NotificationChannel.IN_APP]
            if isinstance(provider, InAppNotificationProvider):
                return provider.mark_notification_read(user_id, notification_id)
        
        return False