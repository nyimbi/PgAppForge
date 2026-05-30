"""
Additional database-backed methods for AlertManager.

This module contains the remaining methods that need to be added to AlertManager
to replace all mock data with real database integration.
"""

from typing import List, Optional
from datetime import datetime, timedelta, timezone
from ..models.alert_models import AlertRule, AlertHistory, AlertStatus, AlertSeverity, MetricSnapshot


def add_database_methods_to_alert_manager():
    """
    Database-backed methods to be added to AlertManager class.
    These replace the mock data methods.
    """
    
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
    
    def get_alert_rules(self, enabled_only: bool = False) -> List[AlertRule]:
        """Get all alert rules from database."""
        try:
            if not self.db_session:
                return []
            
            session = self.db_session()
            query = session.query(AlertRule)
            
            if enabled_only:
                query = query.filter(AlertRule.enabled == True)
                
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
                'resolved_today': resolved_today
            }
            
        except Exception as e:
            log.error(f"Error getting alert statistics: {e}")
            return {
                'total_rules': 0,
                'active_alerts': 0,
                'alerts_today': 0,
                'critical_alerts': 0,
                'resolved_today': 0
            }
    
    def acknowledge_alert(self, alert_id: int, acknowledged_by: str) -> bool:
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
    
    def resolve_alert(self, alert_id: int, resolved_by: str) -> bool:
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
    
    def register_metric_provider(self, metric_name: str, provider_func: callable):
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
    
    # Add all methods to the class
    return {
        'get_alert_rule': get_alert_rule,
        'get_alert_rules': get_alert_rules,
        'get_active_alerts': get_active_alerts,
        'get_alert_history': get_alert_history,
        'get_alert_statistics': get_alert_statistics,
        'acknowledge_alert': acknowledge_alert,
        'resolve_alert': resolve_alert,
        'create_alert': create_alert,
        'record_metric_value': record_metric_value,
        'get_metric_history': get_metric_history,
        'register_metric_provider': register_metric_provider,
        'get_current_metric_value': get_current_metric_value
    }