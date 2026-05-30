"""
Alert Views for PgAppForge Integration.

Provides web interface views for configuring alert rules, viewing alerts,
and managing notification settings.
"""

import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from flask import request, jsonify, flash, redirect, url_for
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.forms import DynamicForm
from pgappforge.widgets import FormWidget
from flask_login import current_user
from wtforms import SelectField, StringField, TextAreaField, BooleanField, FloatField, IntegerField
from wtforms.validators import DataRequired, Optional as OptionalValidator, NumberRange

from .alert_manager import AlertManager, AlertSeverity, AlertStatus
from .threshold_monitor import ThresholdMonitor
from .notification_service import NotificationService, NotificationChannel

log = logging.getLogger(__name__)


class AlertRuleForm(DynamicForm):
    """
    Form for creating and editing alert rules.
    """
    
    name = StringField(
        'Rule Name',
        validators=[DataRequired()],
        description='Human-readable name for this alert rule'
    )
    
    description = TextAreaField(
        'Description',
        validators=[OptionalValidator()],
        description='Optional description of what this rule monitors'
    )
    
    metric_name = StringField(
        'Metric Name',
        validators=[DataRequired()],
        description='Name of the metric to monitor'
    )
    
    condition = SelectField(
        'Condition',
        choices=[
            ('>', 'Greater than'),
            ('<', 'Less than'),
            ('>=', 'Greater than or equal'),
            ('<=', 'Less than or equal'),
            ('==', 'Equals'),
            ('!=', 'Not equals')
        ],
        validators=[DataRequired()],
        default='>'
    )
    
    threshold_value = FloatField(
        'Threshold Value',
        validators=[DataRequired()],
        description='Value to compare the metric against'
    )
    
    severity = SelectField(
        'Severity',
        choices=[
            ('low', 'Low'),
            ('medium', 'Medium'), 
            ('high', 'High'),
            ('critical', 'Critical')
        ],
        validators=[DataRequired()],
        default='medium'
    )
    
    enabled = BooleanField(
        'Enabled',
        default=True,
        description='Enable this alert rule'
    )
    
    cooldown_minutes = IntegerField(
        'Cooldown Period (minutes)',
        validators=[OptionalValidator(), NumberRange(min=1, max=1440)],
        default=30,
        description='Minimum time between alerts for the same rule'
    )
    
    notification_channels = SelectField(
        'Notification Channels',
        choices=[
            ('in_app', 'In-App Notifications'),
            ('email', 'Email'),
            ('webhook', 'Webhook'),
            ('slack', 'Slack')
        ],
        description='How to deliver alert notifications'
    )


class NotificationSettingsForm(DynamicForm):
    """
    Form for configuring notification settings.
    """
    
    email_address = StringField(
        'Email Address',
        validators=[OptionalValidator()],
        description='Email address for alert notifications'
    )
    
    webhook_url = StringField(
        'Webhook URL',
        validators=[OptionalValidator()],
        description='Webhook endpoint for alert notifications'
    )
    
    slack_channel = StringField(
        'Slack Channel',
        validators=[OptionalValidator()],
        description='Slack channel for notifications (e.g., #alerts)'
    )
    
    min_severity = SelectField(
        'Minimum Severity',
        choices=[
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('critical', 'Critical')
        ],
        default='medium',
        description='Only notify for alerts at or above this severity'
    )
    
    business_hours_only = BooleanField(
        'Business Hours Only',
        default=False,
        description='Only send notifications during business hours'
    )


class AlertConfigView(BaseView):
    """
    Alert configuration and management view.
    
    Provides interface for creating, editing, and managing alert rules.
    """
    
    route_base = '/alerts'
    default_view = 'index'
    
    def __init__(self):
        """Initialize alert config view."""
        super().__init__()
        self.alert_manager = None
        self.threshold_monitor = None
        self.notification_service = None
    
    def _get_alert_manager(self) -> AlertManager:
        """Get or create alert manager instance."""
        if not self.alert_manager:
            self.alert_manager = AlertManager(self.appbuilder.app)
        return self.alert_manager
    
    def _get_threshold_monitor(self) -> ThresholdMonitor:
        """Get or create threshold monitor instance."""
        if not self.threshold_monitor:
            alert_manager = self._get_alert_manager()
            self.threshold_monitor = ThresholdMonitor(alert_manager)
        return self.threshold_monitor
    
    def _get_notification_service(self) -> NotificationService:
        """Get or create notification service instance."""
        if not self.notification_service:
            self.notification_service = NotificationService(self.appbuilder.app)
        return self.notification_service
    
    @expose('/')
    @has_access
    def index(self):
        """
        Main alerts dashboard.
        
        Shows alert statistics, active alerts, and recent activity.
        """
        try:
            alert_manager = self._get_alert_manager()
            threshold_monitor = self._get_threshold_monitor()
            notification_service = self._get_notification_service()
            
            # Get dashboard data
            active_alerts = alert_manager.get_active_alerts()
            alert_rules = alert_manager.get_alert_rules()
            alert_stats = alert_manager.get_alert_statistics()
            monitoring_stats = threshold_monitor.get_monitoring_stats()
            notification_stats = notification_service.get_notification_stats()
            
            return self.render_template(
                'alerting/alert_dashboard.html',
                active_alerts=active_alerts,
                alert_rules=alert_rules,
                alert_stats=alert_stats,
                monitoring_stats=monitoring_stats,
                notification_stats=notification_stats
            )
            
        except Exception as e:
            log.error(f"Error rendering alert dashboard: {e}")
            flash(f"Error loading alerts: {str(e)}", 'error')
            return self.render_template('alerting/alert_error.html', error=str(e))
    
    @expose('/rules')
    @has_access
    def rules(self):
        """
        Alert rules management page.
        
        Lists all alert rules with options to create, edit, and delete.
        """
        try:
            alert_manager = self._get_alert_manager()
            alert_rules = alert_manager.get_alert_rules()
            
            return self.render_template(
                'alerting/alert_rules.html',
                alert_rules=alert_rules,
                form=AlertRuleForm()
            )
            
        except Exception as e:
            log.error(f"Error rendering alert rules: {e}")
            flash(f"Error loading alert rules: {str(e)}", 'error')
            return redirect(url_for('AlertConfigView.index'))
    
    @expose('/rules/create', methods=['GET', 'POST'])
    @has_access
    def create_rule(self):
        """Create new alert rule."""
        form = AlertRuleForm()
        
        if request.method == 'POST' and form.validate_on_submit():
            try:
                alert_manager = self._get_alert_manager()
                
                # Create alert rule
                rule = alert_manager.create_alert_rule(
                    name=form.name.data,
                    metric_name=form.metric_name.data,
                    condition=form.condition.data,
                    threshold_value=form.threshold_value.data,
                    severity=AlertSeverity(form.severity.data),
                    description=form.description.data,
                    enabled=form.enabled.data,
                    cooldown_minutes=form.cooldown_minutes.data,
                    notification_channels=[form.notification_channels.data] if form.notification_channels.data else []
                )
                
                flash(f'Alert rule "{rule.name}" created successfully', 'success')
                return redirect(url_for('AlertConfigView.rules'))
                
            except Exception as e:
                log.error(f"Error creating alert rule: {e}")
                flash(f"Error creating alert rule: {str(e)}", 'error')
        
        return self.render_template(
            'alerting/alert_rule_form.html',
            form=form,
            form_widget=FormWidget(form),
            title='Create Alert Rule'
        )
    
    @expose('/rules/edit/<rule_id>', methods=['GET', 'POST'])
    @has_access
    def edit_rule(self, rule_id):
        """Edit existing alert rule."""
        try:
            alert_manager = self._get_alert_manager()
            rule = alert_manager.get_alert_rule(rule_id)
            
            if not rule:
                flash('Alert rule not found', 'error')
                return redirect(url_for('AlertConfigView.rules'))
            
            form = AlertRuleForm(obj=rule)
            
            if request.method == 'POST' and form.validate_on_submit():
                # Update rule
                updates = {
                    'name': form.name.data,
                    'description': form.description.data,
                    'metric_name': form.metric_name.data,
                    'condition': form.condition.data,
                    'threshold_value': form.threshold_value.data,
                    'severity': AlertSeverity(form.severity.data),
                    'enabled': form.enabled.data,
                    'cooldown_minutes': form.cooldown_minutes.data,
                    'notification_channels': [form.notification_channels.data] if form.notification_channels.data else []
                }
                
                updated_rule = alert_manager.update_alert_rule(rule_id, **updates)
                
                if updated_rule:
                    flash(f'Alert rule "{updated_rule.name}" updated successfully', 'success')
                    return redirect(url_for('AlertConfigView.rules'))
                else:
                    flash('Error updating alert rule', 'error')
            
            return self.render_template(
                'alerting/alert_rule_form.html',
                form=form,
                form_widget=FormWidget(form),
                title=f'Edit Rule: {rule.name}',
                rule=rule
            )
            
        except Exception as e:
            log.error(f"Error editing alert rule {rule_id}: {e}")
            flash(f"Error editing alert rule: {str(e)}", 'error')
            return redirect(url_for('AlertConfigView.rules'))
    
    @expose('/rules/delete/<rule_id>')
    @has_access
    def delete_rule(self, rule_id):
        """Delete alert rule."""
        try:
            alert_manager = self._get_alert_manager()
            rule = alert_manager.get_alert_rule(rule_id)
            
            if rule:
                if alert_manager.delete_alert_rule(rule_id):
                    flash(f'Alert rule "{rule.name}" deleted successfully', 'success')
                else:
                    flash('Error deleting alert rule', 'error')
            else:
                flash('Alert rule not found', 'error')
                
        except Exception as e:
            log.error(f"Error deleting alert rule {rule_id}: {e}")
            flash(f"Error deleting alert rule: {str(e)}", 'error')
        
        return redirect(url_for('AlertConfigView.rules'))
    
    @expose('/monitoring')
    @has_access
    def monitoring(self):
        """
        Monitoring status and control page.
        
        Shows monitoring status and provides controls to start/stop monitoring.
        """
        try:
            threshold_monitor = self._get_threshold_monitor()
            monitoring_stats = threshold_monitor.get_monitoring_stats()
            
            return self.render_template(
                'alerting/monitoring_status.html',
                monitoring_stats=monitoring_stats,
                is_monitoring=threshold_monitor.is_monitoring()
            )
            
        except Exception as e:
            log.error(f"Error rendering monitoring status: {e}")
            flash(f"Error loading monitoring status: {str(e)}", 'error')
            return redirect(url_for('AlertConfigView.index'))
    
    @expose('/monitoring/start')
    @has_access
    def start_monitoring(self):
        """Start threshold monitoring."""
        try:
            threshold_monitor = self._get_threshold_monitor()
            threshold_monitor.start_monitoring()
            flash('Threshold monitoring started', 'success')
            
        except Exception as e:
            log.error(f"Error starting monitoring: {e}")
            flash(f"Error starting monitoring: {str(e)}", 'error')
        
        return redirect(url_for('AlertConfigView.monitoring'))
    
    @expose('/monitoring/stop')
    @has_access
    def stop_monitoring(self):
        """Stop threshold monitoring."""
        try:
            threshold_monitor = self._get_threshold_monitor()
            threshold_monitor.stop_monitoring()
            flash('Threshold monitoring stopped', 'info')
            
        except Exception as e:
            log.error(f"Error stopping monitoring: {e}")
            flash(f"Error stopping monitoring: {str(e)}", 'error')
        
        return redirect(url_for('AlertConfigView.monitoring'))
    
    @expose('/monitoring/force-evaluation')
    @has_access
    def force_evaluation(self):
        """Force immediate evaluation of all alert rules."""
        try:
            threshold_monitor = self._get_threshold_monitor()
            new_alerts = threshold_monitor.force_evaluation()
            
            flash(f'Evaluation completed - {len(new_alerts)} new alerts triggered', 'info')
            
        except Exception as e:
            log.error(f"Error in force evaluation: {e}")
            flash(f"Error in evaluation: {str(e)}", 'error')
        
        return redirect(url_for('AlertConfigView.monitoring'))
    
    @expose('/notifications')
    @has_access
    def notifications(self):
        """
        Notification settings page.
        
        Configure notification channels and preferences.
        """
        try:
            notification_service = self._get_notification_service()
            
            # Get current user's notification settings
            user_id = str(current_user.id) if current_user.is_authenticated else 'anonymous'
            recipient = notification_service.get_recipient(user_id)
            
            form = NotificationSettingsForm()
            
            # Pre-populate form if recipient exists
            if recipient:
                email_config = recipient.channel_configs.get('email', {})
                webhook_config = recipient.channel_configs.get('webhook', {})
                
                form.email_address.data = email_config.get('address', '')
                form.webhook_url.data = webhook_config.get('url', '')
                
                filters = recipient.alert_filters or {}
                form.min_severity.data = filters.get('min_severity', 'medium')
            
            if request.method == 'POST' and form.validate_on_submit():
                # Update notification settings
                self._update_notification_settings(form, user_id)
                flash('Notification settings updated successfully', 'success')
                return redirect(url_for('AlertConfigView.notifications'))
            
            return self.render_template(
                'alerting/notification_settings.html',
                form=form,
                form_widget=FormWidget(form),
                recipient=recipient
            )
            
        except Exception as e:
            log.error(f"Error rendering notification settings: {e}")
            flash(f"Error loading notification settings: {str(e)}", 'error')
            return redirect(url_for('AlertConfigView.index'))
    
    def _update_notification_settings(self, form: NotificationSettingsForm, user_id: str):
        """Update notification settings for user."""
        try:
            from .notification_service import NotificationRecipient, NotificationChannel
            
            notification_service = self._get_notification_service()
            
            # Build channel configurations
            channels = []
            channel_configs = {}
            
            if form.email_address.data:
                channels.append(NotificationChannel.EMAIL)
                channel_configs['email'] = {'address': form.email_address.data}
            
            if form.webhook_url.data:
                channels.append(NotificationChannel.WEBHOOK)
                channel_configs['webhook'] = {'url': form.webhook_url.data}
            
            # Always include in-app notifications
            channels.append(NotificationChannel.IN_APP)
            
            # Build alert filters
            alert_filters = {
                'min_severity': form.min_severity.data,
                'business_hours_only': form.business_hours_only.data
            }
            
            # Create or update recipient
            recipient = NotificationRecipient(
                id=user_id,
                name=getattr(current_user, 'username', f'User {user_id}'),
                channels=channels,
                channel_configs=channel_configs,
                alert_filters=alert_filters
            )
            
            notification_service.add_recipient(recipient)
            
        except Exception as e:
            log.error(f"Error updating notification settings: {e}")
            raise
    
    @expose('/api/alerts')
    @has_access
    def api_alerts(self):
        """API endpoint for getting current alerts."""
        try:
            alert_manager = self._get_alert_manager()
            
            # Get query parameters
            severity = request.args.get('severity')
            status = request.args.get('status')
            limit = request.args.get('limit', type=int, default=50)
            
            # Get alerts
            if status == 'active':
                alerts = alert_manager.get_active_alerts(
                    severity=AlertSeverity(severity) if severity else None
                )
            else:
                alerts = alert_manager.get_alert_history(days=7)
                if severity:
                    alerts = [a for a in alerts if a.severity.value == severity]
            
            # Limit results
            alerts = alerts[:limit]
            
            # Convert to JSON-serializable format
            alerts_data = []
            for alert in alerts:
                alerts_data.append({
                    'id': alert.id,
                    'name': alert.name,
                    'description': alert.description,
                    'severity': alert.severity.value,
                    'status': alert.status.value,
                    'metric_name': alert.metric_name,
                    'current_value': alert.current_value,
                    'threshold_value': alert.threshold_value,
                    'condition': alert.condition,
                    'created_at': alert.created_at.isoformat(),
                    'updated_at': alert.updated_at.isoformat()
                })
            
            return jsonify({
                'status': 'success',
                'alerts': alerts_data,
                'count': len(alerts_data)
            })
            
        except Exception as e:
            log.error(f"Error getting alerts API data: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    @expose('/api/alerts/<alert_id>/acknowledge', methods=['POST'])
    @has_access
    def api_acknowledge_alert(self, alert_id):
        """API endpoint for acknowledging an alert."""
        try:
            alert_manager = self._get_alert_manager()
            
            success = alert_manager.acknowledge_alert(
                alert_id=alert_id,
                acknowledged_by=getattr(current_user, 'username', 'unknown')
            )
            
            if success:
                return jsonify({'status': 'success'})
            else:
                return jsonify({'status': 'error', 'error': 'Alert not found'}), 404
                
        except Exception as e:
            log.error(f"Error acknowledging alert {alert_id}: {e}")
            return jsonify({'status': 'error', 'error': str(e)}), 500


class AlertHistoryView(BaseView):
    """
    Alert history and reporting view.
    
    Provides detailed views of alert history, trends, and reporting.
    """
    
    route_base = '/alert-history'
    
    @expose('/')
    @has_access
    def index(self):
        """Alert history dashboard."""
        try:
            alert_manager = AlertManager(self.appbuilder.app)
            
            # Get history parameters
            days = request.args.get('days', type=int, default=30)
            severity = request.args.get('severity')
            
            # Get alert history
            alert_history = alert_manager.get_alert_history(
                days=days,
                severity=AlertSeverity(severity) if severity else None
            )
            
            # Get statistics
            alert_stats = alert_manager.get_alert_statistics()
            
            return self.render_template(
                'alerting/alert_history.html',
                alert_history=alert_history,
                alert_stats=alert_stats,
                days=days,
                severity=severity
            )
            
        except Exception as e:
            log.error(f"Error rendering alert history: {e}")
            flash(f"Error loading alert history: {str(e)}", 'error')
            return self.render_template('alerting/alert_error.html', error=str(e))
    
    @expose('/metrics/<metric_name>')
    @has_access
    def metric_detail(self, metric_name):
        """Detailed view for a specific metric."""
        try:
            threshold_monitor = ThresholdMonitor(AlertManager(self.appbuilder.app))
            
            # Get metric trend
            trend = threshold_monitor.get_metric_trend(metric_name, hours=24)
            
            # Get metric history
            history = threshold_monitor.get_metric_history(metric_name, hours=168)  # 7 days
            
            return self.render_template(
                'alerting/metric_detail.html',
                metric_name=metric_name,
                trend=trend,
                history=history
            )
            
        except Exception as e:
            log.error(f"Error rendering metric detail for {metric_name}: {e}")
            flash(f"Error loading metric details: {str(e)}", 'error')
            return redirect(url_for('AlertHistoryView.index'))