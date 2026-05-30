"""
Database-backed Alert Manager for PgForge.

Complete replacement that uses SQLAlchemy models instead of mock data.
"""

import logging
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta, timezone
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
    Database-backed alert management system.
    
    Provides central management of alert rules, monitoring, and notifications
    with full SQLAlchemy database persistence.
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
        try:
            from .notification_service import NotificationService
            self._notification_service = NotificationService(app)
        except ImportError:
            log.warning("NotificationService not available")
        
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
        """Create a new alert rule and save to database."""
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
            session.refresh(rule)
            
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
        """Update an existing alert rule in database."""
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
        """Delete an alert rule from database."""
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
    
    def get_alert_rules(self, enabled_only: bool = False, metric_name: Optional[str] = None) -> List[AlertRule]:
        """Get all alert rules from database."""
        try:
            if not self.db_session:
                return []
            
            session = self.db_session()
            query = session.query(AlertRule)
            
            if enabled_only:
                query = query.filter(AlertRule.enabled == True)
            
            if metric_name:
                query = query.filter(AlertRule.metric_name == metric_name)
                
            return query.order_by(AlertRule.created_on.desc()).all()
            
        except Exception as e:
            log.error(f"Error getting alert rules: {e}")
            return []
    
    def get_active_alerts(self, severity: Optional[AlertSeverity] = None) -> List[AlertHistory]:
        """Get active alerts from database."""
        try:
            if not self.db_session:
                return []
            
            session = self.db_session()
            query = session.query(AlertHistory).filter(
                AlertHistory.status == AlertStatus.ACTIVE
            )
            
            if severity:
                query = query.filter(AlertHistory.severity == severity)
                
            return query.order_by(AlertHistory.triggered_at.desc()).all()
            
        except Exception as e:
            log.error(f"Error getting active alerts: {e}")
            return []
    
    def get_alert_history(self, days: int = 30, severity: Optional[AlertSeverity] = None) -> List[AlertHistory]:
        """Get alert history from database."""
        try:
            if not self.db_session:
                return []
            
            session = self.db_session()
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=days)
            
            query = session.query(AlertHistory).filter(
                AlertHistory.triggered_at >= cutoff_date
            )
            
            if severity:
                query = query.filter(AlertHistory.severity == severity)
                
            return query.order_by(AlertHistory.triggered_at.desc()).all()
            
        except Exception as e:
            log.error(f"Error getting alert history: {e}")
            return []
    
    def get_alert_statistics(self) -> dict:
        """Get alert statistics from database."""
        try:
            if not self.db_session:
                return {
                    'total_rules': 0,
                    'active_alerts': 0,
                    'alerts_today': 0,
                    'critical_alerts': 0,
                    'resolved_today': 0
                }
            
            session = self.db_session()
            today = datetime.now(tz=timezone.utc).date()
            
            # Count total rules
            total_rules = session.query(AlertRule).count()
            
            # Count active alerts
            active_alerts = session.query(AlertHistory).filter(
                AlertHistory.status == AlertStatus.ACTIVE
            ).count()
            
            # Count alerts today
            alerts_today = session.query(AlertHistory).filter(
                func.date(AlertHistory.triggered_at) == today
            ).count()
            
            # Count critical alerts
            critical_alerts = session.query(AlertHistory).filter(
                and_(
                    AlertHistory.status == AlertStatus.ACTIVE,
                    AlertHistory.severity == AlertSeverity.CRITICAL
                )
            ).count()
            
            # Count resolved today
            resolved_today = session.query(AlertHistory).filter(
                and_(
                    func.date(AlertHistory.resolved_at) == today,
                    AlertHistory.status == AlertStatus.RESOLVED
                )
            ).count()
            
            return {
                'total_rules': total_rules,
                'active_alerts': active_alerts,
                'alerts_today': alerts_today,
                'critical_alerts': critical_alerts,
                'resolved_today': resolved_today,
                'enabled_rules': session.query(AlertRule).filter(AlertRule.enabled == True).count(),
                'registered_metrics': len(self._metric_providers),
                'last_evaluation': datetime.now(tz=timezone.utc).isoformat()
            }
            
        except Exception as e:
            log.error(f"Error getting alert statistics: {e}")
            return {
                'total_rules': 0,
                'active_alerts': 0,
                'alerts_today': 0,
                'critical_alerts': 0,
                'resolved_today': 0,
                'enabled_rules': 0,
                'registered_metrics': 0
            }
    
    def acknowledge_alert(self, alert_id: int, acknowledged_by: str = None) -> bool:
        """Acknowledge an alert in database."""
        try:
            if not self.db_session:
                return False
            
            session = self.db_session()
            alert = session.query(AlertHistory).filter(AlertHistory.id == alert_id).first()
            
            if alert and alert.status == AlertStatus.ACTIVE:
                alert.acknowledge(user_id=None)  # Would need user ID mapping
                session.commit()
                log.info(f"Alert {alert_id} acknowledged by {acknowledged_by}")
                return True
            
            return False
            
        except Exception as e:
            log.error(f"Error acknowledging alert {alert_id}: {e}")
            if self.db_session:
                try:
                    session = self.db_session()
                    session.rollback()
                except:
                    pass
            return False
    
    def resolve_alert(self, alert_id: int, resolved_by: str = None) -> bool:
        """Resolve an alert in database."""
        try:
            if not self.db_session:
                return False
            
            session = self.db_session()
            alert = session.query(AlertHistory).filter(AlertHistory.id == alert_id).first()
            
            if alert and alert.status in [AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED]:
                alert.resolve(user_id=None)  # Would need user ID mapping
                session.commit()
                log.info(f"Alert {alert_id} resolved by {resolved_by}")
                return True
            
            return False
            
        except Exception as e:
            log.error(f"Error resolving alert {alert_id}: {e}")
            if self.db_session:
                try:
                    session = self.db_session()
                    session.rollback()
                except:
                    pass
            return False
    
    def create_alert(self, rule: AlertRule, metric_value: float) -> AlertHistory:
        """Create a new alert in database."""
        try:
            if not self.db_session:
                raise RuntimeError("Database session not available")
            
            session = self.db_session()
            
            # Create alert history entry
            alert = AlertHistory(
                rule_id=rule.id,
                rule_name=rule.name,
                rule_description=rule.description,
                metric_name=rule.metric_name,
                metric_value=metric_value,
                condition=rule.condition.value,
                threshold_value=rule.threshold_value,
                severity=rule.severity,
                status=AlertStatus.ACTIVE,
                message=f"{rule.metric_name} {rule.condition.value} {rule.threshold_value} (current: {metric_value})",
                triggered_at=datetime.now(tz=timezone.utc)
            )
            
            session.add(alert)
            session.commit()
            session.refresh(alert)
            
            log.info(f"Created alert for rule {rule.name}: {alert.message}")
            return alert
            
        except Exception as e:
            log.error(f"Error creating alert: {e}")
            if self.db_session:
                try:
                    session = self.db_session()
                    session.rollback()
                except:
                    pass
            raise
    
    def record_metric_value(self, metric_name: str, value: float, timestamp: Optional[datetime] = None) -> bool:
        """Record a metric value to database."""
        try:
            if not self.db_session:
                return False
            
            session = self.db_session()
            
            snapshot = MetricSnapshot(
                metric_name=metric_name,
                value=value,
                timestamp=timestamp or datetime.now(tz=timezone.utc),
                source="system"
            )
            
            session.add(snapshot)
            session.commit()
            
            return True
            
        except Exception as e:
            log.error(f"Error recording metric {metric_name}: {e}")
            if self.db_session:
                try:
                    session = self.db_session()
                    session.rollback()
                except:
                    pass
            return False
    
    def get_metric_history(self, metric_name: str, hours: int = 24) -> List[MetricSnapshot]:
        """Get metric history from database."""
        try:
            if not self.db_session:
                return []
            
            session = self.db_session()
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
            
            return session.query(MetricSnapshot).filter(
                and_(
                    MetricSnapshot.metric_name == metric_name,
                    MetricSnapshot.timestamp >= cutoff_date
                )
            ).order_by(MetricSnapshot.timestamp.desc()).all()
            
        except Exception as e:
            log.error(f"Error getting metric history for {metric_name}: {e}")
            return []
    
    def register_metric_provider(self, metric_name: str, provider_func: Callable[[], float]):
        """Register a metric provider function."""
        self._metric_providers[metric_name] = provider_func
        log.info(f"Registered metric provider for {metric_name}")
    
    def get_current_metric_value(self, metric_name: str) -> Optional[float]:
        """Get current value for a metric using registered provider."""
        try:
            if metric_name in self._metric_providers:
                provider = self._metric_providers[metric_name]
                return provider()
            else:
                # Fallback: get latest value from database
                if self.db_session:
                    session = self.db_session()
                    latest = session.query(MetricSnapshot).filter(
                        MetricSnapshot.metric_name == metric_name
                    ).order_by(MetricSnapshot.timestamp.desc()).first()
                    
                    if latest:
                        return latest.value
                
                return None
                
        except Exception as e:
            log.error(f"Error getting current value for metric {metric_name}: {e}")
            return None
    
    def evaluate_alert_rules(self) -> List[AlertHistory]:
        """Evaluate all enabled alert rules against current metric values."""
        new_alerts = []
        
        try:
            for rule in self.get_alert_rules(enabled_only=True):
                # Get current metric value
                current_value = self.get_current_metric_value(rule.metric_name)
                if current_value is None:
                    continue
                
                # Check if alert should be triggered
                if self._should_trigger_alert(rule, current_value):
                    alert = self.create_alert(rule, current_value)
                    if alert:
                        new_alerts.append(alert)
                        
                        # Send notifications
                        if self._notification_service:
                            try:
                                self._notification_service.send_alert_notification(alert, rule)
                            except Exception as e:
                                log.error(f"Error sending notification for alert {alert.id}: {e}")
            
            if new_alerts:
                log.info(f"Triggered {len(new_alerts)} new alerts")
            
            return new_alerts
            
        except Exception as e:
            log.error(f"Error evaluating alert rules: {e}")
            return []
    
    def _should_trigger_alert(self, rule: AlertRule, current_value: float) -> bool:
        """Check if an alert should be triggered for a rule."""
        try:
            # Check if condition is met
            if not rule.is_condition_met(current_value):
                return False
            
            # Check for existing active alert (cooldown)
            if self.db_session:
                session = self.db_session()
                recent_alert = session.query(AlertHistory).filter(
                    and_(
                        AlertHistory.rule_id == rule.id,
                        AlertHistory.status == AlertStatus.ACTIVE,
                        AlertHistory.triggered_at >= datetime.now(tz=timezone.utc) - timedelta(minutes=rule.cooldown_minutes)
                    )
                ).first()
                
                if recent_alert:
                    log.debug(f"Alert for rule {rule.id} still in cooldown")
                    return False
            
            return True
            
        except Exception as e:
            log.error(f"Error checking if alert should trigger for rule {rule.id}: {e}")
            return False
    
    def cleanup_old_alerts(self, days: int = 90) -> int:
        """Clean up old resolved alerts from database."""
        try:
            if not self.db_session:
                return 0
            
            session = self.db_session()
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=days)
            
            # Delete old resolved alerts
            deleted_count = session.query(AlertHistory).filter(
                and_(
                    AlertHistory.status == AlertStatus.RESOLVED,
                    AlertHistory.resolved_at <= cutoff_date
                )
            ).delete()
            
            session.commit()
            
            if deleted_count > 0:
                log.info(f"Cleaned up {deleted_count} old alerts")
            
            return deleted_count
            
        except Exception as e:
            log.error(f"Error cleaning up old alerts: {e}")
            if self.db_session:
                try:
                    session = self.db_session()
                    session.rollback()
                except:
                    pass
            return 0