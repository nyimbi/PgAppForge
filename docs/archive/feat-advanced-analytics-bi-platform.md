# PgAppForge: Analytics Platform Enhancements

## Status
Draft

## Authors
Claude Code Assistant - September 2025

## Overview
Four focused enhancements that extend PgAppForge's existing analytics capabilities by building on the current chart system, dashboard infrastructure, and existing WizardAnalyticsView.

## Features

### F1: Enhanced Chart Widgets (1 week)
Extend the existing chart system with new widget types for better data visualization.

#### Technical Implementation
```python
from pgappforge.charts.widgets import ChartWidget
from pgappforge.charts.views import BaseChartView

class MetricCardWidget(ChartWidget):
    """Widget for displaying key metrics as cards"""
    
    template = 'appbuilder/widgets/metric_card.html'
    
    def __init__(self, title, value, trend=None, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.value = value
        self.trend = trend
    
    def render_metric_card(self):
        """Render metric as a card with optional trend indicator"""
        return self.render_template(
            self.template,
            title=self.title,
            value=self.value,
            trend=self.trend,
            trend_class=self._get_trend_class()
        )
    
    def _get_trend_class(self):
        """Get CSS class based on trend direction"""
        if not self.trend:
            return ''
        return 'trend-up' if self.trend > 0 else 'trend-down'

class TrendChartView(BaseChartView):
    """Chart view for displaying time-series trends"""
    
    chart_type = "LineChart"
    chart_title = "Trend Analysis"
    
    def get_trend_data(self, date_field, value_field, time_range='30d'):
        """Get trend data using existing GroupByProcessData patterns"""
        from pgappforge.models.group import GroupByProcessData
        
        # Build on existing chart data patterns
        group_by = GroupByProcessData(
            self.datamodel,
            [date_field],
            value_field
        )
        
        # Apply time range filter
        group_by.apply_date_filter(date_field, time_range)
        
        return group_by.apply_filter_and_group()

# Usage with existing dashboard system
class EnhancedDashboardView(BaseView):
    """Enhanced dashboard using new chart widgets"""
    
    route_base = '/enhanced-dashboard'
    
    @expose('/')
    @has_access
    def index(self):
        """Dashboard with metric cards and trend charts"""
        
        # Create metric cards
        total_records = MetricCardWidget("Total Records", 1250, trend=15)
        active_processes = MetricCardWidget("Active Processes", 45, trend=-5)
        
        # Create trend chart
        trend_chart = TrendChartView()
        
        return self.render_template(
            'analytics/enhanced_dashboard.html',
            metric_cards=[total_records, active_processes],
            trend_chart=trend_chart.chart()
        )
```

#### Dependencies
- Existing PgAppForge chart system (`pgappforge.charts.views`)
- Existing widget infrastructure
- Builds on existing `WizardAnalyticsView` patterns

#### Testing
```python
class TestMetricCardWidget(FABTestCase):
    def test_metric_card_rendering(self):
        widget = MetricCardWidget("Test Metric", 100, trend=10)
        html = widget.render_metric_card()
        self.assertIn("Test Metric", html)
        self.assertIn("trend-up", html)
```

### F2: Dashboard Layout Manager (1 week)
Simple dashboard customization using existing PgAppForge view patterns.

#### Technical Implementation
```python
from pgappforge.views import BaseView, SimpleFormView
from wtforms import SelectField, BooleanField, TextAreaField

class DashboardLayoutForm(DynamicForm):
    """Form for configuring dashboard layout"""
    
    title = StringField('Dashboard Title', validators=[DataRequired()])
    layout_type = SelectField(
        'Layout Type',
        choices=[('grid', 'Grid Layout'), ('tabs', 'Tabbed Layout')],
        default='grid'
    )
    widgets_config = TextAreaField(
        'Widget Configuration (JSON)',
        description='JSON configuration for dashboard widgets'
    )
    is_default = BooleanField('Set as Default Dashboard')

class DashboardLayoutView(SimpleFormView):
    """View for managing dashboard layouts"""
    
    route_base = '/dashboard-config'
    form = DashboardLayoutForm
    
    @expose('/configure', methods=['GET', 'POST'])
    @has_access
    def configure_layout(self):
        """Configure dashboard layout using existing form patterns"""
        
        form = self.form.refresh()
        
        if form.validate_on_submit():
            # Save dashboard configuration
            config = {
                'title': form.title.data,
                'layout_type': form.layout_type.data,
                'widgets': json.loads(form.widgets_config.data or '[]'),
                'is_default': form.is_default.data
            }
            
            self._save_dashboard_config(config)
            flash('Dashboard configuration saved', 'success')
            return redirect(url_for('DashboardLayoutView.configure_layout'))
        
        return self.render_template(
            'analytics/dashboard_config.html',
            form=form,
            available_widgets=self._get_available_widgets()
        )
    
    def _get_available_widgets(self):
        """Get list of available widgets for configuration"""
        return [
            {'id': 'metric_card', 'name': 'Metric Card'},
            {'id': 'trend_chart', 'name': 'Trend Chart'},
            {'id': 'status_pie', 'name': 'Status Pie Chart'},
            {'id': 'data_table', 'name': 'Data Table'}
        ]
    
    def _save_dashboard_config(self, config):
        """Save dashboard configuration using existing patterns"""
        # Use existing PgAppForge user preferences or database
        from flask_login import current_user
        
        # Could extend existing user model or use settings table
        current_user.dashboard_config = json.dumps(config)
        db.session.commit()

class ConfigurableDashboardView(BaseView):
    """Dashboard that uses saved configuration"""
    
    @expose('/')
    @has_access
    def index(self):
        """Render dashboard based on user configuration"""
        
        config = self._get_user_dashboard_config()
        widgets = self._render_configured_widgets(config.get('widgets', []))
        
        return self.render_template(
            'analytics/configurable_dashboard.html',
            config=config,
            widgets=widgets
        )
```

#### Dependencies
- Existing PgAppForge form system
- Existing user/session management
- JSON configuration storage

#### Testing
```python
class TestDashboardLayoutView(FABTestCase):
    def test_dashboard_configuration_save(self):
        self.login_user('admin')
        config = {'title': 'Test Dashboard', 'layout_type': 'grid'}
        response = self.client.post('/dashboard-config/configure', data=config)
        self.assertEqual(response.status_code, 302)  # Redirect after save
```

### F3: Export Enhancement (1 week)
Add export capabilities to existing analytics data using common formats.

#### Technical Implementation
```python
import csv
import json
from io import StringIO, BytesIO
from reportlab.pdfgen import canvas
from flask import make_response, send_file

class AnalyticsExportView(BaseView):
    """Export analytics data in various formats"""
    
    route_base = '/analytics-export'
    
    @expose('/export/<export_type>')
    @has_access
    def export_data(self, export_type):
        """Export analytics data using existing data sources"""
        
        # Get data using existing analytics patterns
        data = self._get_analytics_data()
        
        if export_type == 'csv':
            return self._export_csv(data)
        elif export_type == 'json':
            return self._export_json(data)
        elif export_type == 'pdf':
            return self._export_pdf(data)
        else:
            flash('Unsupported export format', 'error')
            return redirect(request.referrer)
    
    def _get_analytics_data(self):
        """Get analytics data using existing patterns"""
        # Build on existing WizardAnalyticsView data collection
        from pgappforge.views.analytics_view import wizard_analytics
        
        return wizard_analytics.get_dashboard_data(
            date_range='30d',
            include_details=True
        )
    
    def _export_csv(self, data):
        """Export data as CSV using Python standard library"""
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        if data:
            writer.writerow(data[0].keys())
            
            # Write data rows
            for row in data:
                writer.writerow(row.values())
        
        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=analytics_export.csv'
        
        return response
    
    def _export_json(self, data):
        """Export data as JSON"""
        
        response = make_response(json.dumps(data, indent=2, default=str))
        response.headers['Content-Type'] = 'application/json'
        response.headers['Content-Disposition'] = 'attachment; filename=analytics_export.json'
        
        return response
    
    def _export_pdf(self, data):
        """Export data as PDF using ReportLab"""
        
        buffer = BytesIO()
        p = canvas.Canvas(buffer)
        
        # Simple PDF generation
        y_position = 800
        p.drawString(100, y_position, "Analytics Report")
        y_position -= 40
        
        for item in data[:20]:  # Limit to first 20 items
            if y_position < 100:
                p.showPage()
                y_position = 800
            
            p.drawString(100, y_position, str(item))
            y_position -= 20
        
        p.save()
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name='analytics_report.pdf',
            mimetype='application/pdf'
        )

# Integration with existing analytics views
class ExportableDashboardView(BaseView):
    """Dashboard with export functionality"""
    
    @expose('/')
    @has_access
    def index(self):
        """Dashboard with export links"""
        
        return self.render_template(
            'analytics/exportable_dashboard.html',
            export_formats=['csv', 'json', 'pdf']
        )
```

#### Dependencies
- Python standard library (csv, json, io)
- Optional: ReportLab for PDF generation
- Existing analytics data sources

#### Testing
```python
class TestAnalyticsExport(FABTestCase):
    def test_csv_export(self):
        self.login_user('admin')
        response = self.client.get('/analytics-export/export/csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'text/csv')
```

### F4: Basic Alerting (1 week)
Simple threshold-based alerts using existing Flask-Mail and form patterns.

#### Technical Implementation
```python
from pgappforge.views import SimpleFormView
from wtforms import SelectField, FloatField, StringField
from flask_mail import Message

class MetricAlertForm(DynamicForm):
    """Form for configuring metric alerts"""
    
    metric_name = SelectField(
        'Metric to Monitor',
        choices=[
            ('total_records', 'Total Records'),
            ('active_processes', 'Active Processes'),
            ('error_rate', 'Error Rate'),
            ('completion_time', 'Average Completion Time')
        ]
    )
    
    threshold_value = FloatField('Threshold Value', validators=[DataRequired()])
    
    comparison = SelectField(
        'Alert When',
        choices=[
            ('>', 'Greater Than'),
            ('<', 'Less Than'),
            ('=', 'Equal To')
        ]
    )
    
    notification_email = StringField(
        'Email Address',
        validators=[DataRequired(), Email()]
    )
    
    alert_frequency = SelectField(
        'Check Frequency',
        choices=[
            ('hourly', 'Every Hour'),
            ('daily', 'Daily'),
            ('weekly', 'Weekly')
        ],
        default='daily'
    )

class MetricAlertsView(SimpleFormView):
    """View for managing metric alerts"""
    
    route_base = '/metric-alerts'
    form = MetricAlertForm
    
    @expose('/configure', methods=['GET', 'POST'])
    @has_access
    def configure_alert(self):
        """Configure metric alerts using existing form patterns"""
        
        form = self.form.refresh()
        
        if form.validate_on_submit():
            alert_config = {
                'metric_name': form.metric_name.data,
                'threshold_value': form.threshold_value.data,
                'comparison': form.comparison.data,
                'notification_email': form.notification_email.data,
                'alert_frequency': form.alert_frequency.data,
                'created_by': current_user.id
            }
            
            self._save_alert_config(alert_config)
            flash('Alert configured successfully', 'success')
            return redirect(url_for('MetricAlertsView.configure_alert'))
        
        return self.render_template(
            'analytics/alert_config.html',
            form=form,
            existing_alerts=self._get_user_alerts()
        )
    
    def _save_alert_config(self, config):
        """Save alert configuration to database"""
        # Simple storage using existing patterns
        alert_json = json.dumps(config)
        # Could use existing settings table or create simple alerts table
        
    def _get_user_alerts(self):
        """Get existing alerts for current user"""
        # Return list of configured alerts
        return []

class AlertService:
    """Service for checking metrics and sending alerts"""
    
    def __init__(self, mail=None):
        self.mail = mail or current_app.extensions.get('mail')
    
    def check_metric_alerts(self):
        """Check all configured alerts and send notifications"""
        
        alerts = self._get_active_alerts()
        
        for alert in alerts:
            current_value = self._get_metric_value(alert['metric_name'])
            
            if self._should_trigger_alert(current_value, alert):
                self._send_alert_notification(alert, current_value)
    
    def _get_metric_value(self, metric_name):
        """Get current metric value using existing analytics"""
        from pgappforge.views.analytics_view import wizard_analytics
        
        # Use existing analytics data collection
        data = wizard_analytics.get_metric_data(metric_name)
        return data.get('current_value', 0)
    
    def _should_trigger_alert(self, current_value, alert):
        """Check if alert should be triggered"""
        threshold = alert['threshold_value']
        comparison = alert['comparison']
        
        if comparison == '>':
            return current_value > threshold
        elif comparison == '<':
            return current_value < threshold
        elif comparison == '=':
            return current_value == threshold
        
        return False
    
    def _send_alert_notification(self, alert, current_value):
        """Send alert email using existing Flask-Mail"""
        
        msg = Message(
            subject=f'Metric Alert: {alert["metric_name"]}',
            sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
            recipients=[alert['notification_email']]
        )
        
        msg.body = f"""
        Alert Triggered!
        
        Metric: {alert['metric_name']}
        Current Value: {current_value}
        Threshold: {alert['comparison']} {alert['threshold_value']}
        
        Time: {datetime.now()}
        """
        
        try:
            self.mail.send(msg)
        except Exception as e:
            current_app.logger.error(f'Failed to send alert: {e}')

# Background task for checking alerts (using existing Celery if available)
def check_alerts_task():
    """Background task to check metric alerts"""
    alert_service = AlertService()
    alert_service.check_metric_alerts()
```

#### Dependencies
- Existing Flask-Mail integration
- Existing form system
- Background task system (optional Celery integration)

#### Testing
```python
class TestMetricAlerts(FABTestCase):
    def test_alert_configuration(self):
        self.login_user('admin')
        form_data = {
            'metric_name': 'error_rate',
            'threshold_value': 5.0,
            'comparison': '>',
            'notification_email': 'admin@test.com'
        }
        response = self.client.post('/metric-alerts/configure', data=form_data)
        self.assertEqual(response.status_code, 302)
```

## Implementation Plan

### Week 1: Enhanced Chart Widgets
- Create MetricCardWidget and TrendChartView
- Extend existing chart system
- Add new templates for metric cards
- Test integration with existing dashboards

### Week 2: Dashboard Layout Manager
- Create dashboard configuration forms
- Implement layout persistence
- Add widget drag-and-drop interface
- Test with different user configurations

### Week 3: Export Enhancement
- Implement CSV, JSON, and PDF export
- Add export buttons to existing analytics views
- Test with various data sizes
- Optimize performance for large exports

### Week 4: Basic Alerting
- Create alert configuration forms
- Implement metric checking service
- Add email notification system
- Set up background task scheduling

## Success Metrics
- All features integrate with existing PgAppForge analytics infrastructure
- No breaking changes to existing `WizardAnalyticsView`
- Export functionality works with existing chart data
- Alert system uses existing Flask-Mail configuration
- Features can be adopted incrementally

## Migration Strategy
These features build on existing analytics capabilities:
- MetricCardWidget extends existing chart widgets
- Dashboard configuration uses existing form patterns
- Export functionality works with current analytics data
- Alert system integrates with existing notification infrastructure

Existing PgAppForge applications with analytics can adopt these features without modifications to existing code.