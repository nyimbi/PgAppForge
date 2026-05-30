"""
Isolated tests for Basic Alerting System functionality.

Tests the alerting system components without complex PgAppForge imports.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import threading
import time
from datetime import datetime, timedelta

# Import the classes we're testing directly
from pgappforge.alerting.alert_manager import AlertManager, AlertSeverity, AlertStatus, Alert, AlertRule
from pgappforge.alerting.threshold_monitor import ThresholdMonitor, ThresholdCondition, MonitoringConfig
from pgappforge.alerting.notification_service import (
    NotificationService, NotificationChannel, NotificationPriority,
    NotificationRecipient, EmailNotificationProvider, InAppNotificationProvider
)


class TestAlertManagerIsolated(unittest.TestCase):
    """Test cases for AlertManager."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.alert_manager = AlertManager()
        
        # Mock metric providers
        self.alert_manager.register_metric_provider('cpu_usage', lambda: 85.5)
        self.alert_manager.register_metric_provider('memory_usage', lambda: 70.2)
        self.alert_manager.register_metric_provider('disk_usage', lambda: 45.0)
    
    def test_alert_manager_initialization(self):
        """Test alert manager initialization."""
        self.assertIsInstance(self.alert_manager, AlertManager)
        self.assertEqual(len(self.alert_manager._alert_rules), 0)
        self.assertEqual(len(self.alert_manager._active_alerts), 0)
    
    def test_create_alert_rule_basic(self):
        """Test creating basic alert rule."""
        rule = self.alert_manager.create_alert_rule(
            name='High CPU Usage',
            metric_name='cpu_usage',
            condition='>',
            threshold_value=80.0,
            severity=AlertSeverity.HIGH,
            description='CPU usage is too high'
        )
        
        self.assertIsInstance(rule, AlertRule)
        self.assertEqual(rule.name, 'High CPU Usage')
        self.assertEqual(rule.metric_name, 'cpu_usage')
        self.assertEqual(rule.condition, '>')
        self.assertEqual(rule.threshold_value, 80.0)
        self.assertEqual(rule.severity, AlertSeverity.HIGH)
        self.assertTrue(rule.enabled)
    
    def test_create_alert_rule_invalid_condition(self):
        """Test creating alert rule with invalid condition."""
        with self.assertRaises(ValueError) as context:
            self.alert_manager.create_alert_rule(
                name='Invalid Rule',
                metric_name='cpu_usage',
                condition='invalid_condition',
                threshold_value=80.0
            )
        
        self.assertIn('Invalid condition', str(context.exception))
    
    def test_update_alert_rule(self):
        """Test updating existing alert rule."""
        # Create rule
        rule = self.alert_manager.create_alert_rule(
            name='Original Rule',
            metric_name='cpu_usage',
            condition='>',
            threshold_value=80.0
        )
        
        # Update rule
        updated_rule = self.alert_manager.update_alert_rule(
            rule.id,
            name='Updated Rule',
            threshold_value=90.0,
            severity=AlertSeverity.CRITICAL
        )
        
        self.assertIsNotNone(updated_rule)
        self.assertEqual(updated_rule.name, 'Updated Rule')
        self.assertEqual(updated_rule.threshold_value, 90.0)
        self.assertEqual(updated_rule.severity, AlertSeverity.CRITICAL)
    
    def test_delete_alert_rule(self):
        """Test deleting alert rule."""
        # Create rule
        rule = self.alert_manager.create_alert_rule(
            name='Test Rule',
            metric_name='cpu_usage',
            condition='>',
            threshold_value=80.0
        )
        
        # Delete rule
        success = self.alert_manager.delete_alert_rule(rule.id)
        self.assertTrue(success)
        
        # Verify deletion
        deleted_rule = self.alert_manager.get_alert_rule(rule.id)
        self.assertIsNone(deleted_rule)
    
    def test_get_metric_value(self):
        """Test getting metric values."""
        # Test existing metric
        cpu_value = self.alert_manager.get_metric_value('cpu_usage')
        self.assertEqual(cpu_value, 85.5)
        
        # Test non-existent metric
        unknown_value = self.alert_manager.get_metric_value('unknown_metric')
        self.assertIsNone(unknown_value)
    
    def test_evaluate_alert_rules_trigger(self):
        """Test alert rule evaluation that triggers alerts."""
        # Create rule that should trigger (CPU > 80, current is 85.5)
        rule = self.alert_manager.create_alert_rule(
            name='High CPU',
            metric_name='cpu_usage',
            condition='>',
            threshold_value=80.0,
            severity=AlertSeverity.HIGH
        )
        
        # Evaluate rules
        new_alerts = self.alert_manager.evaluate_alert_rules()
        
        # Should trigger one alert
        self.assertEqual(len(new_alerts), 1)
        self.assertEqual(new_alerts[0].name, 'High CPU')
        self.assertEqual(new_alerts[0].metric_name, 'cpu_usage')
        self.assertEqual(new_alerts[0].current_value, 85.5)
        self.assertEqual(new_alerts[0].status, AlertStatus.ACTIVE)
    
    def test_evaluate_alert_rules_no_trigger(self):
        """Test alert rule evaluation that doesn't trigger alerts."""
        # Create rule that shouldn't trigger (CPU > 90, current is 85.5)
        self.alert_manager.create_alert_rule(
            name='Very High CPU',
            metric_name='cpu_usage',
            condition='>',
            threshold_value=90.0,
            severity=AlertSeverity.CRITICAL
        )
        
        # Evaluate rules
        new_alerts = self.alert_manager.evaluate_alert_rules()
        
        # Should not trigger any alerts
        self.assertEqual(len(new_alerts), 0)
    
    def test_acknowledge_alert(self):
        """Test acknowledging an alert."""
        # Create and trigger alert
        rule = self.alert_manager.create_alert_rule(
            name='Test Alert',
            metric_name='cpu_usage',
            condition='>',
            threshold_value=80.0
        )
        
        new_alerts = self.alert_manager.evaluate_alert_rules()
        alert = new_alerts[0]
        
        # Acknowledge alert
        success = self.alert_manager.acknowledge_alert(alert.id, 'test_user')
        self.assertTrue(success)
        
        # Check alert status
        acknowledged_alert = self.alert_manager._active_alerts[alert.id]
        self.assertEqual(acknowledged_alert.status, AlertStatus.ACKNOWLEDGED)
        self.assertEqual(acknowledged_alert.acknowledged_by, 'test_user')
        self.assertIsNotNone(acknowledged_alert.acknowledged_at)
    
    def test_resolve_alert(self):
        """Test resolving an alert."""
        # Create and trigger alert
        rule = self.alert_manager.create_alert_rule(
            name='Test Alert',
            metric_name='cpu_usage',
            condition='>',
            threshold_value=80.0
        )
        
        new_alerts = self.alert_manager.evaluate_alert_rules()
        alert = new_alerts[0]
        
        # Resolve alert
        success = self.alert_manager.resolve_alert(alert.id)
        self.assertTrue(success)
        
        # Check alert status
        resolved_alert = self.alert_manager._active_alerts[alert.id]
        self.assertEqual(resolved_alert.status, AlertStatus.RESOLVED)
        self.assertIsNotNone(resolved_alert.resolved_at)
    
    def test_get_alert_statistics(self):
        """Test getting alert statistics."""
        # Create some rules and alerts
        self.alert_manager.create_alert_rule(
            name='Rule 1',
            metric_name='cpu_usage',
            condition='>',
            threshold_value=80.0
        )
        
        self.alert_manager.create_alert_rule(
            name='Rule 2',
            metric_name='memory_usage',
            condition='<',
            threshold_value=50.0,
            enabled=False
        )
        
        # Trigger alerts
        new_alerts = self.alert_manager.evaluate_alert_rules()
        
        # Get statistics
        stats = self.alert_manager.get_alert_statistics()
        
        self.assertIn('total_rules', stats)
        self.assertIn('enabled_rules', stats)
        self.assertIn('active_alerts', stats)
        self.assertEqual(stats['total_rules'], 2)
        self.assertEqual(stats['enabled_rules'], 1)


class TestThresholdMonitorIsolated(unittest.TestCase):
    """Test cases for ThresholdMonitor."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.alert_manager = AlertManager()
        self.config = MonitoringConfig(interval_seconds=1, max_history_size=100)
        self.threshold_monitor = ThresholdMonitor(self.alert_manager, self.config)
        
        # Register test metrics
        self.test_metric_value = 50.0
        self.alert_manager.register_metric_provider('test_metric', lambda: self.test_metric_value)
    
    def tearDown(self):
        """Clean up after tests."""
        if self.threshold_monitor.is_monitoring():
            self.threshold_monitor.stop_monitoring()
    
    def test_monitor_initialization(self):
        """Test threshold monitor initialization."""
        self.assertIsInstance(self.threshold_monitor, ThresholdMonitor)
        self.assertFalse(self.threshold_monitor.is_monitoring())
        self.assertEqual(self.threshold_monitor.config.interval_seconds, 1)
    
    def test_start_stop_monitoring(self):
        """Test starting and stopping monitoring."""
        # Start monitoring
        self.threshold_monitor.start_monitoring()
        self.assertTrue(self.threshold_monitor.is_monitoring())
        
        # Wait briefly for thread to start
        time.sleep(0.1)
        
        # Stop monitoring
        self.threshold_monitor.stop_monitoring()
        self.assertFalse(self.threshold_monitor.is_monitoring())
    
    def test_force_evaluation(self):
        """Test force evaluation of alert rules."""
        # Create alert rule
        self.alert_manager.create_alert_rule(
            name='Test Force Eval',
            metric_name='test_metric',
            condition='>',
            threshold_value=40.0
        )
        
        # Force evaluation
        new_alerts = self.threshold_monitor.force_evaluation()
        
        # Should trigger alert (test_metric = 50 > 40)
        self.assertEqual(len(new_alerts), 1)
    
    def test_metric_history_tracking(self):
        """Test metric history tracking."""
        # Add some history
        now = datetime.now()
        self.threshold_monitor._add_to_history('test_metric', now, 10.0)
        self.threshold_monitor._add_to_history('test_metric', now + timedelta(seconds=1), 20.0)
        self.threshold_monitor._add_to_history('test_metric', now + timedelta(seconds=2), 30.0)
        
        # Get history
        history = self.threshold_monitor.get_metric_history('test_metric')
        
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0][1], 10.0)  # First value
        self.assertEqual(history[-1][1], 30.0)  # Last value
    
    def test_baseline_calculation(self):
        """Test baseline calculation."""
        # Add enough history for baseline
        now = datetime.now()
        for i in range(20):
            self.threshold_monitor._add_to_history(
                'test_metric', 
                now + timedelta(seconds=i), 
                50.0 + i  # Values from 50 to 69
            )
        
        # Calculate baseline
        baseline = self.threshold_monitor._calculate_baseline('test_metric')
        
        self.assertIsNotNone(baseline)
        self.assertGreater(baseline, 50.0)
        self.assertLess(baseline, 70.0)
    
    def test_percent_change_evaluation(self):
        """Test percentage change condition evaluation."""
        # Set baseline
        self.threshold_monitor._baselines['test_metric'] = 50.0
        
        # Test 20% increase (current=60, baseline=50)
        result = self.threshold_monitor.evaluate_percent_change_condition(
            current_value=60.0,
            threshold_percent=20.0,
            metric_name='test_metric'
        )
        self.assertTrue(result)
        
        # Test 10% increase (shouldn't trigger 20% threshold)
        result = self.threshold_monitor.evaluate_percent_change_condition(
            current_value=55.0,
            threshold_percent=20.0,
            metric_name='test_metric'
        )
        self.assertFalse(result)
    
    def test_range_condition_evaluation(self):
        """Test range condition evaluation."""
        # Test value within range
        result = self.threshold_monitor.evaluate_range_condition(50.0, (40.0, 60.0))
        self.assertFalse(result)  # False means within range (no alert)
        
        # Test value outside range (too high)
        result = self.threshold_monitor.evaluate_range_condition(70.0, (40.0, 60.0))
        self.assertTrue(result)  # True means outside range (alert)
        
        # Test value outside range (too low)
        result = self.threshold_monitor.evaluate_range_condition(30.0, (40.0, 60.0))
        self.assertTrue(result)  # True means outside range (alert)
    
    def test_get_metric_trend(self):
        """Test getting metric trend information."""
        # Add trend data
        now = datetime.now()
        for i in range(10):
            self.threshold_monitor._add_to_history(
                'test_metric',
                now + timedelta(hours=i),
                10.0 + i * 2  # Increasing trend: 10, 12, 14, ..., 28
            )
        
        # Get trend
        trend = self.threshold_monitor.get_metric_trend('test_metric', hours=24)
        
        self.assertIsNotNone(trend)
        self.assertEqual(trend['metric_name'], 'test_metric')
        self.assertEqual(trend['data_points'], 10)
        self.assertEqual(trend['first_value'], 10.0)
        self.assertEqual(trend['last_value'], 28.0)
        self.assertEqual(trend['trend_direction'], 'increasing')
    
    def test_custom_evaluator(self):
        """Test custom condition evaluator."""
        # Register custom evaluator
        def custom_evaluator(current_value, threshold_value, history):
            # Custom logic: alert if current value is more than 2x the average of last 5 values
            if len(history) < 5:
                return False
            
            recent_avg = sum(v for _, v in history[-5:]) / 5
            return current_value > (recent_avg * threshold_value)
        
        self.threshold_monitor.register_custom_evaluator('custom_2x_avg', custom_evaluator)
        
        # Add history
        now = datetime.now()
        for i in range(10):
            self.threshold_monitor._add_to_history('test_metric', now + timedelta(seconds=i), 10.0)
        
        # Test custom condition
        result = self.threshold_monitor.evaluate_custom_condition(
            condition_name='custom_2x_avg',
            current_value=25.0,  # 2.5x the average of 10.0
            threshold_value=2.0,  # 2x threshold
            metric_name='test_metric'
        )
        
        self.assertTrue(result)
    
    def test_monitoring_stats(self):
        """Test getting monitoring statistics."""
        stats = self.threshold_monitor.get_monitoring_stats()
        
        self.assertIn('is_monitoring', stats)
        self.assertIn('config', stats)
        self.assertIn('evaluations_total', stats)
        self.assertIn('custom_evaluators', stats)
        
        self.assertEqual(stats['config']['interval_seconds'], 1)


class TestNotificationServiceIsolated(unittest.TestCase):
    """Test cases for NotificationService."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create mock app for notification service
        self.mock_app = Mock()
        self.mock_app.extensions = {}
        
        self.notification_service = NotificationService()
        self.notification_service.app = self.mock_app
        self.notification_service._init_default_providers()
        self.notification_service._init_default_templates()
    
    def test_notification_service_initialization(self):
        """Test notification service initialization."""
        self.assertIsInstance(self.notification_service, NotificationService)
        self.assertIn(NotificationChannel.EMAIL, self.notification_service._providers)
        self.assertIn(NotificationChannel.IN_APP, self.notification_service._providers)
        self.assertIn('alert_email', self.notification_service._templates)
    
    def test_add_remove_recipient(self):
        """Test adding and removing notification recipients."""
        recipient = NotificationRecipient(
            id='test_user',
            name='Test User',
            channels=[NotificationChannel.EMAIL, NotificationChannel.IN_APP],
            channel_configs={
                'email': {'address': 'test@example.com'}
            }
        )
        
        # Add recipient
        self.notification_service.add_recipient(recipient)
        retrieved = self.notification_service.get_recipient('test_user')
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, 'Test User')
        
        # Remove recipient
        success = self.notification_service.remove_recipient('test_user')
        self.assertTrue(success)
        
        removed = self.notification_service.get_recipient('test_user')
        self.assertIsNone(removed)
    
    def test_in_app_notifications(self):
        """Test in-app notification functionality."""
        provider = self.notification_service._providers[NotificationChannel.IN_APP]
        
        recipient = NotificationRecipient(
            id='test_user',
            name='Test User',
            channels=[NotificationChannel.IN_APP],
            channel_configs={}
        )
        
        # Send notification
        success = provider.send_notification(
            recipient=recipient,
            subject='Test Alert',
            content='This is a test alert notification',
            priority=NotificationPriority.HIGH
        )
        
        self.assertTrue(success)
        
        # Get notifications
        notifications = self.notification_service.get_in_app_notifications('test_user')
        
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]['subject'], 'Test Alert')
        self.assertFalse(notifications[0]['read'])
        
        # Mark as read
        notification_id = notifications[0]['id']
        read_success = self.notification_service.mark_notification_read('test_user', notification_id)
        self.assertTrue(read_success)
        
        # Verify marked as read
        updated_notifications = self.notification_service.get_in_app_notifications('test_user')
        self.assertTrue(updated_notifications[0]['read'])
    
    @patch('pgappforge.alerting.notification_service.render_template_string')
    def test_alert_notification_rendering(self, mock_render):
        """Test alert notification template rendering."""
        mock_render.return_value = "Rendered notification content"
        
        # Create mock alert and rule
        alert = Mock()
        alert.id = 'test_alert'
        alert.name = 'Test Alert'
        alert.severity = Mock()
        alert.severity.value = 'high'
        alert.metric_name = 'test_metric'
        alert.current_value = 85.5
        alert.threshold_value = 80.0
        alert.condition = '>'
        alert.created_at = datetime.now()
        alert.description = 'Test alert description'
        
        rule = Mock()
        rule.id = 'test_rule'
        rule.notification_channels = ['in_app']
        
        # Add recipient
        recipient = NotificationRecipient(
            id='test_user',
            name='Test User',
            channels=[NotificationChannel.IN_APP],
            channel_configs={}
        )
        self.notification_service.add_recipient(recipient)
        
        # Send alert notification
        self.notification_service.send_alert_notification(alert, rule)
        
        # Verify template rendering was called
        mock_render.assert_called()
        
        # Verify notification was sent
        notifications = self.notification_service.get_in_app_notifications('test_user')
        self.assertGreater(len(notifications), 0)
    
    def test_recipient_filtering(self):
        """Test recipient filtering for alerts."""
        # Create recipient with severity filter
        recipient = NotificationRecipient(
            id='filtered_user',
            name='Filtered User',
            channels=[NotificationChannel.IN_APP],
            channel_configs={},
            alert_filters={'min_severity': 'high'}
        )
        
        # Create mock alert with medium severity
        alert = Mock()
        alert.severity = Mock()
        alert.severity.value = 'medium'
        alert.metric_name = 'test_metric'
        
        rule = Mock()
        rule.id = 'test_rule'
        
        # Test filtering - should not notify (medium < high)
        should_notify = self.notification_service._should_notify_recipient(recipient, alert, rule)
        self.assertFalse(should_notify)
        
        # Change alert to high severity - should notify
        alert.severity.value = 'high'
        should_notify = self.notification_service._should_notify_recipient(recipient, alert, rule)
        self.assertTrue(should_notify)
    
    def test_notification_history(self):
        """Test notification history tracking."""
        # Create mock alert and rule
        alert = Mock()
        alert.id = 'history_test'
        alert.severity = Mock()
        alert.severity.value = 'medium'
        alert.metric_name = 'test_metric'
        
        rule = Mock()
        rule.id = 'rule_history'
        
        # Record notification
        self.notification_service._record_notification_history(
            alert, rule, NotificationChannel.EMAIL, 2
        )
        
        # Get history
        history = self.notification_service.get_notification_history(days=1)
        
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['alert_id'], 'history_test')
        self.assertEqual(history[0]['channel'], 'email')
        self.assertEqual(history[0]['recipient_count'], 2)
    
    def test_notification_stats(self):
        """Test notification statistics."""
        # Add some recipients
        recipient1 = NotificationRecipient(
            id='user1', name='User 1', channels=[NotificationChannel.EMAIL], channel_configs={}
        )
        recipient2 = NotificationRecipient(
            id='user2', name='User 2', channels=[NotificationChannel.IN_APP], channel_configs={}
        )
        
        self.notification_service.add_recipient(recipient1)
        self.notification_service.add_recipient(recipient2)
        
        # Get stats
        stats = self.notification_service.get_notification_stats()
        
        self.assertIn('total_recipients', stats)
        self.assertIn('active_providers', stats)
        self.assertEqual(stats['total_recipients'], 2)
        self.assertGreater(stats['active_providers'], 0)


class TestAlertingIntegration(unittest.TestCase):
    """Test integration between alerting components."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.alert_manager = AlertManager()
        self.threshold_monitor = ThresholdMonitor(
            self.alert_manager, 
            MonitoringConfig(interval_seconds=1)
        )
        
        # Mock app for notification service
        mock_app = Mock()
        mock_app.extensions = {}
        
        self.notification_service = NotificationService()
        self.notification_service.app = mock_app
        self.notification_service._init_default_providers()
        self.notification_service._init_default_templates()
        
        # Connect services
        self.alert_manager._notification_service = self.notification_service
        
        # Register test metric
        self.test_value = 75.0
        self.alert_manager.register_metric_provider('integration_metric', lambda: self.test_value)
    
    def tearDown(self):
        """Clean up after tests."""
        if self.threshold_monitor.is_monitoring():
            self.threshold_monitor.stop_monitoring()
    
    def test_complete_alerting_workflow(self):
        """Test complete workflow from rule creation to notification."""
        # Add notification recipient
        recipient = NotificationRecipient(
            id='integration_user',
            name='Integration User',
            channels=[NotificationChannel.IN_APP],
            channel_configs={}
        )
        self.notification_service.add_recipient(recipient)
        
        # Create alert rule
        rule = self.alert_manager.create_alert_rule(
            name='Integration Test Alert',
            metric_name='integration_metric',
            condition='>',
            threshold_value=70.0,
            severity=AlertSeverity.HIGH,
            notification_channels=['in_app']
        )
        
        # Trigger evaluation
        new_alerts = self.alert_manager.evaluate_alert_rules()
        
        # Should create one alert
        self.assertEqual(len(new_alerts), 1)
        alert = new_alerts[0]
        
        # Verify alert properties
        self.assertEqual(alert.name, 'Integration Test Alert')
        self.assertEqual(alert.current_value, 75.0)
        self.assertEqual(alert.status, AlertStatus.ACTIVE)
        
        # Verify notification was sent
        notifications = self.notification_service.get_in_app_notifications('integration_user')
        self.assertGreater(len(notifications), 0)
        
        # Test alert acknowledgment
        success = self.alert_manager.acknowledge_alert(alert.id, 'integration_user')
        self.assertTrue(success)
        
        acknowledged_alert = self.alert_manager._active_alerts[alert.id]
        self.assertEqual(acknowledged_alert.status, AlertStatus.ACKNOWLEDGED)
    
    def test_monitoring_with_notifications(self):
        """Test threshold monitoring with notification integration."""
        # Add recipient
        recipient = NotificationRecipient(
            id='monitor_user',
            name='Monitor User', 
            channels=[NotificationChannel.IN_APP],
            channel_configs={}
        )
        self.notification_service.add_recipient(recipient)
        
        # Create rule
        self.alert_manager.create_alert_rule(
            name='Monitor Test',
            metric_name='integration_metric',
            condition='>',
            threshold_value=70.0,
            notification_channels=['in_app']
        )
        
        # Start monitoring briefly
        self.threshold_monitor.start_monitoring()
        time.sleep(0.5)  # Let it run briefly
        self.threshold_monitor.stop_monitoring()
        
        # Check if alerts were created
        active_alerts = self.alert_manager.get_active_alerts()
        self.assertGreaterEqual(len(active_alerts), 1)
        
        # Check if notifications were sent
        notifications = self.notification_service.get_in_app_notifications('monitor_user')
        self.assertGreaterEqual(len(notifications), 1)
    
    def test_multiple_severity_levels(self):
        """Test alerting with multiple severity levels."""
        # Create rules with different severities
        self.alert_manager.create_alert_rule(
            name='Medium Alert',
            metric_name='integration_metric',
            condition='>',
            threshold_value=70.0,
            severity=AlertSeverity.MEDIUM
        )
        
        self.alert_manager.create_alert_rule(
            name='High Alert',
            metric_name='integration_metric',
            condition='>',
            threshold_value=70.0,
            severity=AlertSeverity.HIGH
        )
        
        # Trigger alerts
        new_alerts = self.alert_manager.evaluate_alert_rules()
        
        # Should create two alerts
        self.assertEqual(len(new_alerts), 2)
        
        # Verify different severities
        severities = {alert.severity for alert in new_alerts}
        self.assertIn(AlertSeverity.MEDIUM, severities)
        self.assertIn(AlertSeverity.HIGH, severities)
    
    def test_cooldown_behavior(self):
        """Test alert cooldown behavior."""
        # Create rule with short cooldown
        rule = self.alert_manager.create_alert_rule(
            name='Cooldown Test',
            metric_name='integration_metric',
            condition='>',
            threshold_value=70.0,
            cooldown_minutes=0  # No cooldown for test
        )
        
        # Trigger first alert
        alerts1 = self.alert_manager.evaluate_alert_rules()
        self.assertEqual(len(alerts1), 1)
        
        # Trigger again immediately - should not create new alert due to existing active alert
        alerts2 = self.alert_manager.evaluate_alert_rules()
        self.assertEqual(len(alerts2), 0)
        
        # Resolve first alert
        self.alert_manager.resolve_alert(alerts1[0].id)
        
        # Now should be able to trigger again
        alerts3 = self.alert_manager.evaluate_alert_rules()
        self.assertEqual(len(alerts3), 1)
    
    def test_disabled_rule_behavior(self):
        """Test that disabled rules don't trigger alerts."""
        # Create disabled rule
        rule = self.alert_manager.create_alert_rule(
            name='Disabled Rule',
            metric_name='integration_metric',
            condition='>',
            threshold_value=70.0,
            enabled=False
        )
        
        # Trigger evaluation
        new_alerts = self.alert_manager.evaluate_alert_rules()
        
        # Should not create any alerts
        self.assertEqual(len(new_alerts), 0)
        
        # Enable rule
        self.alert_manager.update_alert_rule(rule.id, enabled=True)
        
        # Now should trigger
        new_alerts = self.alert_manager.evaluate_alert_rules()
        self.assertEqual(len(new_alerts), 1)


if __name__ == '__main__':
    unittest.main()