# Enhanced PgAppForge Setup Guide

This guide shows how to install and configure the enhanced PgAppForge with advanced analytics, export capabilities, and alerting features.

## Installation

### Base Installation

```bash
pip install PgAppForge
```

### Enhanced Features Installation

For complete functionality, install with all enhanced features:

```bash
# Install with all enhanced capabilities
pip install "PgAppForge[export,analytics,mfa]"

# Or install specific feature sets
pip install "PgAppForge[export]"      # Export functionality only
pip install "PgAppForge[analytics]"   # Analytics dashboards only
pip install "PgAppForge[mfa]"         # Multi-factor authentication only
```

### Development Installation

```bash
git clone https://github.com/your-repo/flask-appbuilder-enhanced.git
cd flask-appbuilder-enhanced
pip install -e ".[export,analytics,mfa]"
```

## Configuration

### 1. Basic Application Setup

Create your PgAppForge application as usual:

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA

app = Flask(__name__)
app.config.from_object('config')

# Your existing configuration...
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)
```

### 2. Enhanced Features Configuration

Add to your `config.py`:

```python
# Enable enhanced addon managers
ADDON_MANAGERS = [
    # Alerting System Manager
    'pgappforge.alerting.manager.AlertingManager',
    
    # Export Enhancement Manager  
    'pgappforge.export.manager.ExportManager',
]

# Export system configuration
EXPORT_CONFIG = {
    'enabled_formats': ['csv', 'xlsx', 'pdf'],
    'max_export_records': 100000,
    'export_timeout': 300,  # seconds
    'cleanup_after_days': 7,
    'temp_directory': '/tmp/fab_exports',
    'max_concurrent_exports': 5
}

# Alerting system configuration  
ALERTING_CONFIG = {
    'enabled': True,
    'check_interval': 60,  # seconds
    'max_concurrent_checks': 10,
    'default_cooldown': 15,  # minutes
    'max_alert_history': 10000
}

# Notification settings
NOTIFICATION_CONFIG = {
    'email': {
        'enabled': True,
        'smtp_server': 'localhost',
        'smtp_port': 587,
        'smtp_username': 'your-email@example.com',
        'smtp_password': 'your-password',
        'smtp_use_tls': True,
        'from_address': 'alerts@example.com',
        'default_recipients': ['admin@example.com']
    }
}
```

### 3. Database Setup

The enhanced features require additional database tables. Run migrations:

```python
# In your application startup or migration script
from pgappforge.models.alert_models import AlertRule, AlertHistory, MetricSnapshot, NotificationSettings
from pgappforge.models.dashboard_models import DashboardConfig, DashboardWidget, DashboardTemplate
from pgappforge.models.export_models import ExportJob, ExportTemplate, ExportSchedule

# Create all tables
db.create_all()
```

Or if using Flask-Migrate:

```bash
flask db init
flask db migrate -m "Add enhanced features"
flask db upgrade
```

## Feature Usage

### 1. Advanced Analytics Dashboard

Access the enhanced dashboard at `/enhanced-dashboard`:

```python
# The enhanced dashboard is automatically available
# Navigate to: http://your-app/enhanced-dashboard
```

Features:
- Real-time metric cards with trend indicators
- Customizable widget layouts (grid, tabs, columns)
- Interactive charts and visualizations
- Time-series analysis
- Configurable refresh intervals

### 2. Multi-Format Export System

Export data in multiple formats:

```python
# Available at: http://your-app/export
# Supported formats: CSV, Excel (XLSX), PDF, JSON, XML, HTML
```

Features:
- Scheduled exports with cron-like scheduling
- Export templates for reusable configurations
- Background processing for large datasets
- Email notifications when exports complete
- Automatic cleanup of old export files

### 3. Alerting System

Monitor your application metrics:

```python
# Access at: http://your-app/alerts
```

Features:
- Configurable alert rules with multiple conditions
- Real-time threshold monitoring
- Multi-channel notifications (email, webhook, in-app)
- Alert history and reporting
- Metric trend analysis

### 4. Custom Metrics Registration

Register your own metrics for monitoring:

```python
from pgappforge.alerting.manager import AlertManager

def get_active_users():
    # Your custom metric logic
    return User.query.filter(User.last_login >= datetime.utcnow() - timedelta(hours=24)).count()

# Register with alert manager
alert_manager = app.extensions['alert_manager']
alert_manager.register_metric_provider('active_users', get_active_users)
```

### 5. Dashboard Customization

Create custom dashboards:

```python
from pgappforge.views.analytics_dashboard import EnhancedDashboardView
from pgappforge.charts.metric_widgets import MetricCardWidget

class MyCustomDashboard(EnhancedDashboardView):
    route_base = '/my-dashboard'
    
    def get_dashboard_widgets(self):
        return [
            MetricCardWidget(
                title="Total Sales",
                value=self.get_total_sales(),
                trend=self.get_sales_trend(),
                format_type="currency"
            ),
            # Add more widgets...
        ]
```

## Security Configuration

Enhanced features include additional security considerations:

### Role-Based Access Control

The system automatically creates roles for enhanced features:
- **Alert Admin**: Full alerting system access
- **Alert User**: View alerts and acknowledge them
- **Export Admin**: Full export system access  
- **Export User**: Basic export functionality
- **Dashboard Admin**: Create and manage dashboards
- **Dashboard User**: View dashboards

### API Security

New API endpoints are protected with PgAppForge's security:

```python
# Alert API endpoints require proper permissions
# Export API endpoints check user access
# Dashboard API validates ownership and sharing settings
```

## Production Deployment

### Database Recommendations

- **PostgreSQL** (recommended): Full feature support
- **MySQL**: Full feature support
- **SQLite**: Basic features only (not recommended for production)

### Background Tasks

For production, consider using Celery for background tasks:

```python
# config.py
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

# Enable background export processing
EXPORT_USE_CELERY = True
ALERTING_USE_CELERY = True
```

### Caching

Enable caching for better performance:

```python
# config.py
CACHE_TYPE = "redis"
CACHE_REDIS_URL = "redis://localhost:6379"
```

### Monitoring

Monitor the enhanced features:

```python
# Built-in health endpoints
# GET /alerts/api/health
# GET /export/api/health
# GET /dashboard/api/health
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure all extra dependencies are installed
2. **Database Errors**: Run migrations to create required tables
3. **Permission Errors**: Check that addon managers are registered in config
4. **Export Failures**: Verify temp directory permissions and disk space

### Debugging

Enable debug logging:

```python
import logging
logging.getLogger('pgappforge.alerting').setLevel(logging.DEBUG)
logging.getLogger('pgappforge.export').setLevel(logging.DEBUG)
logging.getLogger('pgappforge.analytics').setLevel(logging.DEBUG)
```

### Getting Help

- Check the example configuration in `examples/enhanced_config_example.py`
- Review the test files in `tests/` for usage examples
- Ensure your PgAppForge version is 4.8.0-enhanced or later

## Example Applications

Complete example applications are available:

- **Basic Analytics**: `examples/analytics_app.py`
- **Export System**: `examples/export_app.py`  
- **Alerting System**: `examples/alerting_app.py`
- **Full Featured**: `examples/complete_enhanced_app.py`

Run examples:

```bash
cd examples
python complete_enhanced_app.py
# Navigate to http://localhost:8080
```

## Upgrading

When upgrading from standard PgAppForge:

1. Install enhanced dependencies: `pip install "PgAppForge[export,analytics]"`
2. Update config to add `ADDON_MANAGERS`
3. Run database migrations
4. Update any custom views to use enhanced base classes
5. Test all functionality in development before deploying

The enhanced version maintains full backward compatibility with existing PgAppForge applications.