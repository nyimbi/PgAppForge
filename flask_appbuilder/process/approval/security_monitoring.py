"""
Security Monitoring and Alerting System

Provides real-time security monitoring, threat detection, and alerting
for the Flask-AppBuilder approval system security controls.

Features:
- Real-time security event monitoring
- Threat pattern detection and alerting
- Performance impact monitoring
- Security metrics collection and reporting
- Automated incident response triggers
"""

import logging
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum

from .constants import SecurityConstants, AuditConstants
from .audit_logger import ApprovalAuditLogger

log = logging.getLogger(__name__)


class ThreatLevel(Enum):
    """Security threat severity levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityEventType(Enum):
    """Types of security events to monitor."""
    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHORIZATION_VIOLATION = "authorization_violation"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SQL_INJECTION_ATTEMPT = "sql_injection_attempt"
    XSS_ATTEMPT = "xss_attempt"
    SESSION_HIJACKING = "session_hijacking_attempt"
    PRIVILEGE_ESCALATION = "privilege_escalation_attempt"
    AUDIT_TAMPERING = "audit_tampering_attempt"
    SUSPICIOUS_BEHAVIOR = "suspicious_behavior"


@dataclass
class SecurityAlert:
    """Security alert data structure."""
    alert_id: str
    event_type: SecurityEventType
    threat_level: ThreatLevel
    timestamp: datetime
    user_id: Optional[int]
    ip_address: Optional[str]
    description: str
    metadata: Dict[str, Any]
    response_actions: List[str]


@dataclass
class SecurityMetrics:
    """Security metrics for monitoring dashboard."""
    total_events: int
    threats_blocked: int
    authentication_failures: int
    authorization_violations: int
    rate_limit_blocks: int
    sql_injection_attempts: int
    xss_attempts: int
    session_anomalies: int
    performance_impact_ms: float


class SecurityMonitor:
    """
    Real-time security monitoring and threat detection system.

    Monitors security events, detects threat patterns, and triggers
    automated responses to security incidents.
    """

    def __init__(self, alert_threshold_minutes: int = 5):
        self.audit_logger = ApprovalAuditLogger()
        self.alert_threshold_minutes = alert_threshold_minutes

        # Event storage for pattern detection
        self.recent_events = deque(maxlen=1000)
        self.user_activity = defaultdict(list)
        self.ip_activity = defaultdict(list)

        # Threat pattern thresholds
        self.threat_thresholds = {
            'failed_logins_per_user': 5,
            'failed_logins_per_ip': 10,
            'rate_limit_violations': 3,
            'sql_injection_attempts': 1,
            'xss_attempts': 1,
            'session_anomalies': 2,
            'authorization_violations': 3
        }

        # Performance monitoring
        self.performance_metrics = {
            'hmac_calculation_times': deque(maxlen=100),
            'validation_times': deque(maxlen=100),
            'rate_limit_check_times': deque(maxlen=100)
        }

    def record_security_event(self, event_type: SecurityEventType,
                            user_id: Optional[int] = None,
                            ip_address: Optional[str] = None,
                            metadata: Optional[Dict] = None) -> Optional[SecurityAlert]:
        """
        Record a security event and check for threat patterns.

        Args:
            event_type: Type of security event
            user_id: User ID associated with event
            ip_address: IP address associated with event
            metadata: Additional event metadata

        Returns:
            SecurityAlert if threat pattern detected, None otherwise
        """
        timestamp = datetime.now(tz=timezone.utc)

        # Create event record
        event = {
            'event_type': event_type.value,
            'timestamp': timestamp,
            'user_id': user_id,
            'ip_address': ip_address,
            'metadata': metadata or {}
        }

        # Store event for pattern analysis
        self.recent_events.append(event)

        if user_id:
            self.user_activity[user_id].append(event)
            # Keep only recent events per user
            cutoff_time = timestamp - timedelta(minutes=self.alert_threshold_minutes)
            self.user_activity[user_id] = [
                e for e in self.user_activity[user_id]
                if e['timestamp'] > cutoff_time
            ]

        if ip_address:
            self.ip_activity[ip_address].append(event)
            # Keep only recent events per IP
            cutoff_time = timestamp - timedelta(minutes=self.alert_threshold_minutes)
            self.ip_activity[ip_address] = [
                e for e in self.ip_activity[ip_address]
                if e['timestamp'] > cutoff_time
            ]

        # Log the security event
        self.audit_logger.log_security_event(event_type.value, {
            'user_id': user_id,
            'ip_address': ip_address,
            'timestamp': timestamp.isoformat(),
            'metadata': metadata or {}
        })

        # Check for threat patterns
        alert = self._analyze_threat_patterns(event)

        if alert:
            self._trigger_security_alert(alert)

        return alert

    def _analyze_threat_patterns(self, event: Dict) -> Optional[SecurityAlert]:
        """Analyze event patterns to detect security threats."""
        event_type = SecurityEventType(event['event_type'])
        user_id = event['user_id']
        ip_address = event['ip_address']
        timestamp = event['timestamp']

        # Pattern 1: Multiple authentication failures
        if event_type == SecurityEventType.AUTHENTICATION_FAILURE:
            if user_id:
                user_failures = [
                    e for e in self.user_activity[user_id]
                    if e['event_type'] == SecurityEventType.AUTHENTICATION_FAILURE.value
                ]

                if len(user_failures) >= self.threat_thresholds['failed_logins_per_user']:
                    return SecurityAlert(
                        alert_id=self._generate_alert_id(),
                        event_type=SecurityEventType.AUTHENTICATION_FAILURE,
                        threat_level=ThreatLevel.HIGH,
                        timestamp=timestamp,
                        user_id=user_id,
                        ip_address=ip_address,
                        description=f"Multiple authentication failures from user {user_id}",
                        metadata={'failure_count': len(user_failures)},
                        response_actions=['lock_account', 'notify_security_team']
                    )

            if ip_address:
                ip_failures = [
                    e for e in self.ip_activity[ip_address]
                    if e['event_type'] == SecurityEventType.AUTHENTICATION_FAILURE.value
                ]

                if len(ip_failures) >= self.threat_thresholds['failed_logins_per_ip']:
                    return SecurityAlert(
                        alert_id=self._generate_alert_id(),
                        event_type=SecurityEventType.AUTHENTICATION_FAILURE,
                        threat_level=ThreatLevel.CRITICAL,
                        timestamp=timestamp,
                        user_id=user_id,
                        ip_address=ip_address,
                        description=f"Brute force attack detected from IP {ip_address}",
                        metadata={'failure_count': len(ip_failures)},
                        response_actions=['block_ip', 'notify_security_team', 'alert_soc']
                    )

        # Pattern 2: SQL injection attempts
        elif event_type == SecurityEventType.SQL_INJECTION_ATTEMPT:
            return SecurityAlert(
                alert_id=self._generate_alert_id(),
                event_type=SecurityEventType.SQL_INJECTION_ATTEMPT,
                threat_level=ThreatLevel.CRITICAL,
                timestamp=timestamp,
                user_id=user_id,
                ip_address=ip_address,
                description="SQL injection attempt detected",
                metadata=event.get('metadata', {}),
                response_actions=['block_request', 'log_detailed_info', 'notify_security_team']
            )

        # Pattern 3: XSS attempts
        elif event_type == SecurityEventType.XSS_ATTEMPT:
            return SecurityAlert(
                alert_id=self._generate_alert_id(),
                event_type=SecurityEventType.XSS_ATTEMPT,
                threat_level=ThreatLevel.HIGH,
                timestamp=timestamp,
                user_id=user_id,
                ip_address=ip_address,
                description="Cross-site scripting (XSS) attempt detected",
                metadata=event.get('metadata', {}),
                response_actions=['sanitize_input', 'log_detailed_info', 'monitor_user']
            )

        # Pattern 4: Session hijacking attempts
        elif event_type == SecurityEventType.SESSION_HIJACKING:
            return SecurityAlert(
                alert_id=self._generate_alert_id(),
                event_type=SecurityEventType.SESSION_HIJACKING,
                threat_level=ThreatLevel.CRITICAL,
                timestamp=timestamp,
                user_id=user_id,
                ip_address=ip_address,
                description="Session hijacking attempt detected",
                metadata=event.get('metadata', {}),
                response_actions=['invalidate_session', 'force_reauth', 'notify_user', 'alert_soc']
            )

        # Pattern 5: Multiple authorization violations
        elif event_type == SecurityEventType.AUTHORIZATION_VIOLATION:
            if user_id:
                violations = [
                    e for e in self.user_activity[user_id]
                    if e['event_type'] == SecurityEventType.AUTHORIZATION_VIOLATION.value
                ]

                if len(violations) >= self.threat_thresholds['authorization_violations']:
                    return SecurityAlert(
                        alert_id=self._generate_alert_id(),
                        event_type=SecurityEventType.PRIVILEGE_ESCALATION,
                        threat_level=ThreatLevel.HIGH,
                        timestamp=timestamp,
                        user_id=user_id,
                        ip_address=ip_address,
                        description=f"Potential privilege escalation attempt from user {user_id}",
                        metadata={'violation_count': len(violations)},
                        response_actions=['restrict_permissions', 'monitor_closely', 'notify_manager']
                    )

        # Pattern 6: Rate limiting violations
        elif event_type == SecurityEventType.RATE_LIMIT_EXCEEDED:
            if user_id:
                rate_violations = [
                    e for e in self.user_activity[user_id]
                    if e['event_type'] == SecurityEventType.RATE_LIMIT_EXCEEDED.value
                ]

                if len(rate_violations) >= self.threat_thresholds['rate_limit_violations']:
                    return SecurityAlert(
                        alert_id=self._generate_alert_id(),
                        event_type=SecurityEventType.SUSPICIOUS_BEHAVIOR,
                        threat_level=ThreatLevel.MEDIUM,
                        timestamp=timestamp,
                        user_id=user_id,
                        ip_address=ip_address,
                        description=f"Suspicious activity: repeated rate limiting from user {user_id}",
                        metadata={'violation_count': len(rate_violations)},
                        response_actions=['temporary_restriction', 'monitor_activity']
                    )

        return None

    def _trigger_security_alert(self, alert: SecurityAlert):
        """Trigger security alert and automated responses."""
        # Log the alert
        log.warning(f"SECURITY ALERT: {alert.description} (Level: {alert.threat_level.value})")

        # Record in audit log
        self.audit_logger.log_security_event('security_alert_triggered', {
            'alert_id': alert.alert_id,
            'event_type': alert.event_type.value,
            'threat_level': alert.threat_level.value,
            'user_id': alert.user_id,
            'ip_address': alert.ip_address,
            'description': alert.description,
            'response_actions': alert.response_actions,
            'timestamp': alert.timestamp.isoformat()
        })

        # Execute automated response actions
        for action in alert.response_actions:
            self._execute_response_action(action, alert)

    def _execute_response_action(self, action: str, alert: SecurityAlert):
        """Execute automated security response action."""
        try:
            if action == 'block_ip':
                self._block_ip_address(alert.ip_address)
            elif action == 'lock_account':
                self._lock_user_account(alert.user_id)
            elif action == 'invalidate_session':
                self._invalidate_user_sessions(alert.user_id)
            elif action == 'notify_security_team':
                self._notify_security_team(alert)
            elif action == 'alert_soc':
                self._alert_security_operations_center(alert)
            elif action == 'log_detailed_info':
                self._log_detailed_security_info(alert)

            log.info(f"Executed security response action: {action} for alert {alert.alert_id}")

        except Exception as e:
            log.error(f"Failed to execute security response action {action}: {e}")

    def _block_ip_address(self, ip_address: str):
        """Block IP address at firewall level."""
        # In production, this would integrate with firewall/WAF
        log.warning(f"IP blocking action triggered for {ip_address}")

    def _lock_user_account(self, user_id: int):
        """Lock user account temporarily."""
        # In production, this would integrate with user management system
        log.warning(f"Account locking action triggered for user {user_id}")

    def _invalidate_user_sessions(self, user_id: int):
        """Invalidate all sessions for user."""
        # In production, this would clear all user sessions
        log.warning(f"Session invalidation triggered for user {user_id}")

    def _notify_security_team(self, alert: SecurityAlert):
        """Send notification to security team."""
        # In production, this would send email/Slack/PagerDuty alerts
        log.warning(f"Security team notification triggered for alert {alert.alert_id}")

    def _alert_security_operations_center(self, alert: SecurityAlert):
        """Send high-priority alert to SOC."""
        # In production, this would integrate with SIEM/SOC tools
        log.critical(f"SOC alert triggered for {alert.alert_id}: {alert.description}")

    def _log_detailed_security_info(self, alert: SecurityAlert):
        """Log detailed security information for investigation."""
        detailed_info = {
            'alert_details': {
                'alert_id': alert.alert_id,
                'event_type': alert.event_type.value,
                'threat_level': alert.threat_level.value,
                'description': alert.description,
                'metadata': alert.metadata
            },
            'user_context': {
                'user_id': alert.user_id,
                'recent_activity': self.user_activity.get(alert.user_id, [])[-10:]
            },
            'ip_context': {
                'ip_address': alert.ip_address,
                'recent_activity': self.ip_activity.get(alert.ip_address, [])[-10:]
            },
            'system_state': self.get_security_metrics()
        }

        log.info(f"Detailed security info: {json.dumps(detailed_info, default=str, indent=2)}")

    def record_performance_metric(self, operation: str, duration_ms: float):
        """Record performance metrics for security operations."""
        if operation in self.performance_metrics:
            self.performance_metrics[operation].append(duration_ms)

    def get_security_metrics(self) -> SecurityMetrics:
        """Get current security metrics for monitoring dashboard."""
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=24)

        recent_events = [
            e for e in self.recent_events
            if e['timestamp'] > cutoff_time
        ]

        # Count events by type
        event_counts = defaultdict(int)
        for event in recent_events:
            event_counts[event['event_type']] += 1

        # Calculate average performance impact
        avg_performance = 0.0
        if self.performance_metrics['hmac_calculation_times']:
            avg_performance = sum(self.performance_metrics['hmac_calculation_times']) / len(self.performance_metrics['hmac_calculation_times'])

        return SecurityMetrics(
            total_events=len(recent_events),
            threats_blocked=event_counts.get('sql_injection_attempt', 0) + event_counts.get('xss_attempt', 0),
            authentication_failures=event_counts.get('authentication_failure', 0),
            authorization_violations=event_counts.get('authorization_violation', 0),
            rate_limit_blocks=event_counts.get('rate_limit_exceeded', 0),
            sql_injection_attempts=event_counts.get('sql_injection_attempt', 0),
            xss_attempts=event_counts.get('xss_attempt', 0),
            session_anomalies=event_counts.get('session_hijacking_attempt', 0),
            performance_impact_ms=avg_performance
        )

    def _generate_alert_id(self) -> str:
        """Generate unique alert ID."""
        from .crypto_config import SecureCryptoConfig
        return SecureCryptoConfig.generate_secure_token("alert")

    def get_security_dashboard_data(self) -> Dict[str, Any]:
        """Get security dashboard data for monitoring interface."""
        metrics = self.get_security_metrics()

        return {
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'security_metrics': {
                'total_events_24h': metrics.total_events,
                'threats_blocked_24h': metrics.threats_blocked,
                'authentication_failures_24h': metrics.authentication_failures,
                'authorization_violations_24h': metrics.authorization_violations,
                'rate_limit_blocks_24h': metrics.rate_limit_blocks,
                'sql_injection_attempts_24h': metrics.sql_injection_attempts,
                'xss_attempts_24h': metrics.xss_attempts,
                'session_anomalies_24h': metrics.session_anomalies,
                'avg_performance_impact_ms': metrics.performance_impact_ms
            },
            'threat_patterns': {
                'active_alerts': len([a for a in self.recent_events if 'alert' in a.get('metadata', {})]),
                'top_threat_sources': self._get_top_threat_sources(),
                'security_trend': self._calculate_security_trend()
            },
            'system_health': {
                'security_controls_active': True,
                'monitoring_operational': True,
                'last_update': datetime.now(tz=timezone.utc).isoformat()
            }
        }

    def _get_top_threat_sources(self) -> List[Dict[str, Any]]:
        """Get top threat sources by IP address."""
        ip_threat_counts = defaultdict(int)

        for event in self.recent_events:
            ip_address = event.get('ip_address')
            if ip_address and event['event_type'] in ['sql_injection_attempt', 'xss_attempt', 'authentication_failure']:
                ip_threat_counts[ip_address] += 1

        # Sort by threat count and return top 10
        sorted_threats = sorted(ip_threat_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return [
            {'ip_address': ip, 'threat_count': count}
            for ip, count in sorted_threats
        ]

    def _calculate_security_trend(self) -> str:
        """Calculate security trend (improving/stable/deteriorating)."""
        now = datetime.now(tz=timezone.utc)
        recent_window = now - timedelta(hours=4)
        previous_window = recent_window - timedelta(hours=4)

        recent_threats = len([
            e for e in self.recent_events
            if e['timestamp'] > recent_window and e['event_type'] in ['sql_injection_attempt', 'xss_attempt', 'authorization_violation']
        ])

        previous_threats = len([
            e for e in self.recent_events
            if previous_window <= e['timestamp'] <= recent_window and e['event_type'] in ['sql_injection_attempt', 'xss_attempt', 'authorization_violation']
        ])

        if recent_threats > previous_threats * 1.2:
            return "deteriorating"
        elif recent_threats < previous_threats * 0.8:
            return "improving"
        else:
            return "stable"


# Global security monitor instance
_security_monitor = None


def get_security_monitor() -> SecurityMonitor:
    """Get global security monitor instance."""
    global _security_monitor
    if _security_monitor is None:
        _security_monitor = SecurityMonitor()
    return _security_monitor


def record_security_event(event_type: SecurityEventType,
                         user_id: Optional[int] = None,
                         ip_address: Optional[str] = None,
                         metadata: Optional[Dict] = None) -> Optional[SecurityAlert]:
    """Convenience function to record security events."""
    monitor = get_security_monitor()
    return monitor.record_security_event(event_type, user_id, ip_address, metadata)


def get_security_dashboard() -> Dict[str, Any]:
    """Get security dashboard data."""
    monitor = get_security_monitor()
    return monitor.get_security_dashboard_data()


def demo_security_monitoring():
    """Demonstrate security monitoring capabilities."""
    print("🔒 SECURITY MONITORING SYSTEM DEMONSTRATION")
    print("=" * 60)

    monitor = SecurityMonitor()

    # Simulate various security events
    print("\n📊 Simulating Security Events:")
    print("-" * 30)

    # Simulate authentication failures
    for i in range(6):
        alert = monitor.record_security_event(
            SecurityEventType.AUTHENTICATION_FAILURE,
            user_id=123,
            ip_address="192.168.1.100",
            metadata={'username': 'suspicious_user', 'attempt': i+1}
        )

        if alert:
            print(f"🚨 ALERT TRIGGERED: {alert.description}")

    # Simulate SQL injection attempt
    alert = monitor.record_security_event(
        SecurityEventType.SQL_INJECTION_ATTEMPT,
        user_id=456,
        ip_address="10.0.0.50",
        metadata={'payload': "'; DROP TABLE users; --", 'field': 'search_query'}
    )

    if alert:
        print(f"🚨 CRITICAL ALERT: {alert.description}")

    # Simulate XSS attempt
    alert = monitor.record_security_event(
        SecurityEventType.XSS_ATTEMPT,
        user_id=789,
        ip_address="203.0.113.15",
        metadata={'payload': "<script>alert('xss')</script>", 'field': 'comments'}
    )

    if alert:
        print(f"🚨 HIGH ALERT: {alert.description}")

    # Get security metrics
    metrics = monitor.get_security_metrics()

    print(f"\n📈 Security Metrics Summary:")
    print("-" * 30)
    print(f"Total Events (24h): {metrics.total_events}")
    print(f"Threats Blocked: {metrics.threats_blocked}")
    print(f"Auth Failures: {metrics.authentication_failures}")
    print(f"SQL Injection Attempts: {metrics.sql_injection_attempts}")
    print(f"XSS Attempts: {metrics.xss_attempts}")

    # Get dashboard data
    dashboard = monitor.get_security_dashboard_data()

    print(f"\n🎛️ Security Dashboard Preview:")
    print("-" * 30)
    print(json.dumps(dashboard, indent=2, default=str))


if __name__ == "__main__":
    demo_security_monitoring()