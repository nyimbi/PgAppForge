"""
Alert Manager for coordinating alerting system.

Provides central management of alerts, thresholds, and notifications
with integration into the PgForge framework and SQLAlchemy database.
"""

import logging
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
import uuid

from flask import current_app
from flask_login import current_user
from sqlalchemy.orm import sessionmaker
from sqlalchemy import desc, and_, func

# Import the database models
from ..models.alert_models import (
    AlertRule, AlertHistory, AlertSeverity, AlertStatus, AlertCondition,
    MetricSnapshot, NotificationSettings
)

log = logging.getLogger(__name__)


class AlertManager:
    """
    Central alert management system with database persistence.
    
    Coordinates alert rules, monitoring, notifications, and history tracking
    using SQLAlchemy models for data persistence.
    """
    
    def __init__(self, app=None):
        """
        Initialize alert manager.
        
        Args:
            app: Flask application instance (optional)
        """
        self.app = app
        self.db_session = None
        self._metric_providers = {}
        self._notification_service = None
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """
        Initialize with Flask app and database session.
        
        Args:
            app: Flask application instance
        """
        self.app = app
        
        # Get database session from PgForge
        if hasattr(app, 'appbuilder') and hasattr(app.appbuilder, 'get_session'):
            self.db_session = app.appbuilder.get_session
        elif hasattr(app, 'extensions') and 'sqlalchemy' in app.extensions:
            # Fallback to direct SQLAlchemy session
            self.db_session = app.extensions['sqlalchemy'].db.session
        else:
            log.warning("No database session found - alert manager will have limited functionality")
        
        # Store reference in app
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        app.extensions['alert_manager'] = self
        
        # Initialize notification service
        from .notification_service import NotificationService
        self._notification_service = NotificationService(app)
        
        log.info("Alert Manager initialized with database persistence")
    
    def create_alert_rule(self, 
                         name: str,
                         metric_name: str,
                         condition: str,
                         threshold_value: float,
                         severity: AlertSeverity = AlertSeverity.MEDIUM,
                         description: str = "",
                         enabled: bool = True,
                         cooldown_minutes: int = 30,
                         notification_channels: List[str] = None,
                         **kwargs) -> AlertRule:
        """
        Create a new alert rule and save to database.
        
        Args:
            name: Human-readable name for the rule
            metric_name: Name of the metric to monitor
            condition: Condition operator (>, <, >=, <=, ==, !=)
            threshold_value: Threshold value to compare against
            severity: Alert severity level
            description: Optional description
            enabled: Whether rule is active
            cooldown_minutes: Minutes between alerts for same rule
            notification_channels: List of notification channel names
            **kwargs: Additional rule configuration
            
        Returns:
            Created AlertRule instance
            
        Raises:
            ValueError: If parameters are invalid
        """
        try:
            if not self.db_session:
                raise RuntimeError("Database session not available")
            
            # Convert string condition to enum
            condition_map = {
                '>': AlertCondition.GREATER_THAN,
                '<': AlertCondition.LESS_THAN,
                '>=': AlertCondition.GREATER_EQUAL,
                '<=': AlertCondition.LESS_EQUAL,
                '==': AlertCondition.EQUAL,
                '!=': AlertCondition.NOT_EQUAL
            }
            
            if condition not in condition_map:
                raise ValueError(f"Invalid condition '{condition}'. Must be one of: {list(condition_map.keys())}")
            
            # Create rule using SQLAlchemy model
            rule = AlertRule(
                name=name,
                description=description,
                metric_name=metric_name,
                condition=condition_map[condition],
                threshold_value=threshold_value,
                severity=severity,
                enabled=enabled,
                cooldown_minutes=cooldown_minutes,
                notification_channels=notification_channels or ["email"],
                created_by_fk=getattr(current_user, 'id', None) if hasattr(current_user, 'id') else None
            )
            
            # Add any additional configuration
            if kwargs:
                rule.additional_config = kwargs
            
            # Save to database
            session = self.db_session()
            session.add(rule)
            session.commit()
            session.refresh(rule)  # Get the ID
            
            log.info(f"Created alert rule: {name} (ID: {rule.id}) for metric {metric_name}")
            return rule
            
        except Exception as e:
            log.error(f"Error creating alert rule: {e}")
            if self.db_session:
                try:
                    session = self.db_session()
                    session.rollback()
                except:
                    pass
            raise
    
    def update_alert_rule(self, rule_id: int, **updates) -> Optional[AlertRule]:
        """
        Update an existing alert rule in database.
        
        Args:
            rule_id: ID of the rule to update
            **updates: Fields to update
            
        Returns:
            Updated AlertRule or None if not found
        """
        try:
            if not self.db_session:
                raise RuntimeError("Database session not available")
            
            session = self.db_session()
            rule = session.query(AlertRule).filter(AlertRule.id == rule_id).first()
            
            if not rule:
                log.warning(f"Alert rule not found: {rule_id}")
                return None
            
            # Handle condition conversion if needed
            if 'condition' in updates and isinstance(updates['condition'], str):
                condition_map = {
                    '>': AlertCondition.GREATER_THAN,
                    '<': AlertCondition.LESS_THAN,
                    '>=': AlertCondition.GREATER_EQUAL,
                    '<=': AlertCondition.LESS_EQUAL,
                    '==': AlertCondition.EQUAL,
                    '!=': AlertCondition.NOT_EQUAL
                }
                updates['condition'] = condition_map.get(updates['condition'], AlertCondition.GREATER_THAN)
            
            # Handle severity conversion if needed
            if 'severity' in updates and isinstance(updates['severity'], str):
                updates['severity'] = AlertSeverity(updates['severity'])
            
            # Update fields
            for field, value in updates.items():
                if hasattr(rule, field):
                    setattr(rule, field, value)
                else:
                    log.warning(f"Invalid field for alert rule update: {field}")
            
            session.commit()
            log.info(f"Updated alert rule: {rule_id}")
            return rule
            
        except Exception as e:
            log.error(f"Error updating alert rule {rule_id}: {e}")
            if self.db_session:
                try:
                    session = self.db_session()
                    session.rollback()
                except:
                    pass
            return None
    
    def delete_alert_rule(self, rule_id: int) -> bool:
        """
        Delete an alert rule from database.
        
        Args:
            rule_id: ID of the rule to delete
            
        Returns:
            True if deleted, False if not found
        """
        try:
            if not self.db_session:
                raise RuntimeError("Database session not available")
            
            session = self.db_session()
            rule = session.query(AlertRule).filter(AlertRule.id == rule_id).first()
            
            if rule:
                session.delete(rule)
                session.commit()
                log.info(f"Deleted alert rule: {rule_id} ({rule.name})")
                return True
            else:
                log.warning(f"Alert rule not found for deletion: {rule_id}")
                return False
                
        except Exception as e:
            log.error(f"Error deleting alert rule {rule_id}: {e}")
            if self.db_session:
                try:
                    session = self.db_session()
                    session.rollback()
                except:
                    pass
            return False
    
    def get_alert_rule(self, rule_id: int) -> Optional[AlertRule]:
        """Get alert rule by ID from database."""
        try:
            if not self.db_session:
                return None
            
            session = self.db_session()
            return session.query(AlertRule).filter(AlertRule.id == rule_id).first()
            
        except Exception as e:
            log.error(f"Error getting alert rule {rule_id}: {e}")
            return None
    
    def get_alert_rules(self, 
                       enabled_only: bool = False,
                       metric_name: Optional[str] = None) -> List[AlertRule]:
        """
        Get list of alert rules with optional filtering.
        
        Args:
            enabled_only: Only return enabled rules
            metric_name: Filter by metric name
            
        Returns:
            List of AlertRule instances
        """
        rules = list(self._alert_rules.values())
        
        if enabled_only:
            rules = [r for r in rules if r.enabled]
        
        if metric_name:
            rules = [r for r in rules if r.metric_name == metric_name]
        
        return sorted(rules, key=lambda r: r.created_at, reverse=True)
    
    def register_metric_provider(self, metric_name: str, provider_func: Callable[[], float]):
        """
        Register a metric provider function.
        
        Args:
            metric_name: Name of the metric
            provider_func: Function that returns current metric value
        """
        self._metric_providers[metric_name] = provider_func
        log.info(f"Registered metric provider for: {metric_name}")
    
    def get_metric_value(self, metric_name: str) -> Optional[float]:
        """
        Get current value for a metric.
        
        Args:
            metric_name: Name of the metric
            
        Returns:
            Current metric value or None if not available
        """
        try:
            if metric_name in self._metric_providers:
                value = self._metric_providers[metric_name]()
                log.debug(f"Retrieved metric value {metric_name}: {value}")
                return value
            else:
                log.warning(f"No provider registered for metric: {metric_name}")
                return None
                
        except Exception as e:
            log.error(f"Error getting metric value for {metric_name}: {e}")
            return None
    
    def evaluate_alert_rules(self) -> List[Alert]:
        """
        Evaluate all active alert rules against current metric values.
        
        Returns:
            List of new alerts that were triggered
        """
        new_alerts = []
        
        try:
            for rule in self.get_alert_rules(enabled_only=True):
                # Get current metric value
                current_value = self.get_metric_value(rule.metric_name)
                if current_value is None:
                    continue
                
                # Check if alert should be triggered
                if self._should_trigger_alert(rule, current_value):
                    alert = self._create_alert(rule, current_value)
                    if alert:
                        new_alerts.append(alert)
                        
                        # Send notifications
                        if self._notification_service:
                            self._notification_service.send_alert_notification(alert, rule)
            
            if new_alerts:
                log.info(f"Triggered {len(new_alerts)} new alerts")
            
            return new_alerts
            
        except Exception as e:
            log.error(f"Error evaluating alert rules: {e}")
            return []
    
    def _should_trigger_alert(self, rule: AlertRule, current_value: float) -> bool:
        """
        Check if an alert should be triggered for a rule.
        
        Args:
            rule: Alert rule to evaluate
            current_value: Current metric value
            
        Returns:
            True if alert should be triggered
        """
        try:
            # Check if condition is met
            condition_met = self._evaluate_condition(
                current_value, rule.condition, rule.threshold_value
            )
            
            if not condition_met:
                return False
            
            # Check for existing active alert (cooldown)
            existing_alert = self._get_active_alert_for_rule(rule.id)
            if existing_alert:
                # Check cooldown period
                time_since_alert = datetime.now() - existing_alert.created_at
                if time_since_alert.total_seconds() < (rule.cooldown_minutes * 60):
                    log.debug(f"Alert for rule {rule.id} still in cooldown")
                    return False
            
            return True
            
        except Exception as e:
            log.error(f"Error checking if alert should trigger for rule {rule.id}: {e}")
            return False
    
    def _evaluate_condition(self, current_value: float, condition: str, threshold: float) -> bool:
        """Evaluate alert condition."""
        conditions = {
            '>': lambda c, t: c > t,
            '<': lambda c, t: c < t,
            '>=': lambda c, t: c >= t,
            '<=': lambda c, t: c <= t,
            '==': lambda c, t: c == t,
            '!=': lambda c, t: c != t
        }
        
        condition_func = conditions.get(condition)
        if condition_func:
            return condition_func(current_value, threshold)
        
        log.error(f"Unknown condition: {condition}")
        return False
    
    def _create_alert(self, rule: AlertRule, current_value: float) -> Optional[Alert]:
        """
        Create a new alert instance.
        
        Args:
            rule: Alert rule that was triggered
            current_value: Current metric value
            
        Returns:
            Created Alert instance
        """
        try:
            # Generate unique alert ID
            alert_id = f"alert_{rule.id}_{datetime.now().timestamp()}"
            
            # Create alert
            alert = Alert(
                id=alert_id,
                name=rule.name,
                description=rule.description or f"Alert triggered for {rule.metric_name}",
                severity=rule.severity,
                status=AlertStatus.ACTIVE,
                metric_name=rule.metric_name,
                current_value=current_value,
                threshold_value=rule.threshold_value,
                condition=rule.condition,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                metadata={
                    'rule_id': rule.id,
                    'triggered_by': getattr(current_user, 'username', 'system') if current_user.is_authenticated else 'system'
                }
            )
            
            # Store alert
            self._active_alerts[alert_id] = alert
            self._alert_history.append(alert)
            
            log.info(f"Created alert: {alert.name} for metric {alert.metric_name}")
            return alert
            
        except Exception as e:
            log.error(f"Error creating alert for rule {rule.id}: {e}")
            return None
    
    def _get_active_alert_for_rule(self, rule_id: str) -> Optional[Alert]:
        """Get active alert for a specific rule."""
        for alert in self._active_alerts.values():
            if (alert.metadata and 
                alert.metadata.get('rule_id') == rule_id and 
                alert.status == AlertStatus.ACTIVE):
                return alert
        return None
    
    def acknowledge_alert(self, alert_id: str, acknowledged_by: Optional[str] = None) -> bool:
        """
        Acknowledge an alert.
        
        Args:
            alert_id: ID of the alert to acknowledge
            acknowledged_by: Username who acknowledged the alert
            
        Returns:
            True if successful
        """
        try:
            if alert_id in self._active_alerts:
                alert = self._active_alerts[alert_id]
                alert.status = AlertStatus.ACKNOWLEDGED
                alert.acknowledged_by = acknowledged_by or getattr(current_user, 'username', 'system')
                alert.acknowledged_at = datetime.now()
                alert.updated_at = datetime.now()
                
                log.info(f"Acknowledged alert: {alert_id}")
                return True
            else:
                log.warning(f"Alert not found for acknowledgment: {alert_id}")
                return False
                
        except Exception as e:
            log.error(f"Error acknowledging alert {alert_id}: {e}")
            return False
    
    def resolve_alert(self, alert_id: str) -> bool:
        """
        Resolve an alert.
        
        Args:
            alert_id: ID of the alert to resolve
            
        Returns:
            True if successful
        """
        try:
            if alert_id in self._active_alerts:
                alert = self._active_alerts[alert_id]
                alert.status = AlertStatus.RESOLVED
                alert.resolved_at = datetime.now()
                alert.updated_at = datetime.now()
                
                # Move to history only (keep in active for tracking)
                log.info(f"Resolved alert: {alert_id}")
                return True
            else:
                log.warning(f"Alert not found for resolution: {alert_id}")
                return False
                
        except Exception as e:
            log.error(f"Error resolving alert {alert_id}: {e}")
            return False
    
    def get_active_alerts(self, 
                         severity: Optional[AlertSeverity] = None,
                         metric_name: Optional[str] = None) -> List[Alert]:
        """
        Get active alerts with optional filtering.
        
        Args:
            severity: Filter by severity
            metric_name: Filter by metric name
            
        Returns:
            List of active Alert instances
        """
        alerts = [a for a in self._active_alerts.values() 
                 if a.status == AlertStatus.ACTIVE]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        if metric_name:
            alerts = [a for a in alerts if a.metric_name == metric_name]
        
        return sorted(alerts, key=lambda a: a.created_at, reverse=True)
    
    def get_alert_history(self, 
                         days: int = 30,
                         severity: Optional[AlertSeverity] = None) -> List[Alert]:
        """
        Get alert history with optional filtering.
        
        Args:
            days: Number of days of history to return
            severity: Filter by severity
            
        Returns:
            List of historical Alert instances
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        
        alerts = [a for a in self._alert_history if a.created_at >= cutoff_date]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        return sorted(alerts, key=lambda a: a.created_at, reverse=True)
    
    def get_alert_statistics(self) -> Dict[str, Any]:
        """
        Get alerting system statistics.
        
        Returns:
            Dictionary with alert statistics
        """
        try:
            active_alerts = self.get_active_alerts()
            recent_history = self.get_alert_history(days=7)
            
            # Count by severity
            severity_counts = {}
            for severity in AlertSeverity:
                severity_counts[severity.value] = len([
                    a for a in active_alerts if a.severity == severity
                ])
            
            # Count by status
            status_counts = {}
            for status in AlertStatus:
                status_counts[status.value] = len([
                    a for a in recent_history if a.status == status
                ])
            
            return {
                'active_alerts': len(active_alerts),
                'total_rules': len(self._alert_rules),
                'enabled_rules': len(self.get_alert_rules(enabled_only=True)),
                'recent_alerts': len(recent_history),
                'severity_breakdown': severity_counts,
                'status_breakdown': status_counts,
                'registered_metrics': len(self._metric_providers),
                'last_evaluation': datetime.now().isoformat()
            }
            
        except Exception as e:
            log.error(f"Error getting alert statistics: {e}")
            return {}
    
    def cleanup_old_alerts(self, days: int = 90) -> int:
        """
        Clean up old resolved alerts from history.
        
        Args:
            days: Number of days to keep in history
            
        Returns:
            Number of alerts cleaned up
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            # Remove from history
            initial_count = len(self._alert_history)
            self._alert_history = [
                a for a in self._alert_history 
                if a.created_at >= cutoff_date or a.status == AlertStatus.ACTIVE
            ]
            
            # Remove resolved alerts from active alerts
            resolved_alerts = [
                aid for aid, alert in self._active_alerts.items()
                if alert.status == AlertStatus.RESOLVED and alert.resolved_at 
                and alert.resolved_at <= cutoff_date
            ]
            
            for alert_id in resolved_alerts:
                del self._active_alerts[alert_id]
            
            cleaned_count = initial_count - len(self._alert_history) + len(resolved_alerts)
            
            if cleaned_count > 0:
                log.info(f"Cleaned up {cleaned_count} old alerts")
            
            return cleaned_count
            
        except Exception as e:
            log.error(f"Error cleaning up old alerts: {e}")
            return 0