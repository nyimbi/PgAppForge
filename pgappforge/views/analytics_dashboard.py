"""
Database-backed Enhanced Analytics Dashboard View.

Complete replacement that uses real database integration instead of mock data.
Integrates with DashboardConfig models and existing PgAppForge data.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from flask import render_template, request, jsonify, flash, redirect, url_for
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.models.sqla.interface import SQLAInterface
from flask_login import current_user
from sqlalchemy import func, desc, and_

# Import database models
from ..models.dashboard_models import DashboardConfig, DashboardWidget, DashboardTemplate
from ..models.alert_models import AlertHistory, AlertRule, MetricSnapshot
from ..charts.metric_widgets import MetricCardWidget, TrendChartView

log = logging.getLogger(__name__)


class DatabaseBackedDashboardView(BaseView):
    """
    Enhanced dashboard with full database integration.
    
    Provides comprehensive business intelligence using:
    - Real database metrics from PgAppForge models
    - Configurable dashboard layouts from DashboardConfig
    - Historical trending from MetricSnapshot data
    - Integration with alerting system metrics
    """
    
    route_base = '/enhanced-dashboard'
    default_view = 'index'
    
    def __init__(self):
        """Initialize dashboard view with database session."""
        super().__init__()
        self.db_session = None
    
    def _get_db_session(self):
        """Get database session from PgAppForge."""
        if not self.db_session:
            if hasattr(self.appbuilder, 'get_session'):
                self.db_session = self.appbuilder.get_session
            elif hasattr(self.appbuilder.app, 'extensions') and 'sqlalchemy' in self.appbuilder.app.extensions:
                self.db_session = self.appbuilder.app.extensions['sqlalchemy'].db.session
        return self.db_session
    
    @expose('/')
    @has_access
    def index(self):
        """Main dashboard view with database-backed metrics."""
        try:
            # Get or create user's dashboard configuration
            dashboard_config = self._get_or_create_user_dashboard()
            
            # Get time range from request
            time_range = request.args.get('time_range', '30d')
            
            # Generate metric cards using real data
            metric_cards = self._generate_database_metric_cards(time_range, dashboard_config)
            
            # Generate trend charts using real data
            trend_charts = self._generate_database_trend_charts(time_range, dashboard_config)
            
            # Get real dashboard data
            dashboard_data = self._get_database_dashboard_data(time_range)
            
            return self.render_template(
                'analytics/enhanced_dashboard.html',
                metric_cards=metric_cards,
                trend_charts=trend_charts,
                dashboard_data=dashboard_data,
                dashboard_config=dashboard_config,
                time_range=time_range,
                available_time_ranges=self._get_time_range_options()
            )
            
        except Exception as e:
            log.error(f"Error rendering database dashboard: {e}")
            flash(f"Error loading dashboard: {str(e)}", 'error')
            return self.render_template(
                'analytics/dashboard_error.html',
                error_message=str(e)
            )
    
    @expose('/api/metrics')
    @has_access 
    def api_metrics(self):
        """API endpoint for real-time metrics data."""
        try:
            time_range = request.args.get('time_range', '30d')
            dashboard_config = self._get_or_create_user_dashboard()
            metric_cards = self._generate_database_metric_cards(time_range, dashboard_config)
            
            # Convert to JSON
            metrics_data = []
            for card in metric_cards:
                metrics_data.append({
                    'title': card.title,
                    'value': card.value,
                    'trend': card.trend,
                    'subtitle': card.subtitle,
                    'icon': card.icon,
                    'color': card.color
                })
            
            return jsonify({
                'status': 'success',
                'metrics': metrics_data,
                'time_range': time_range,
                'generated_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting database metrics API: {e}")
            return jsonify({
                'status': 'error', 
                'error': str(e)
            }), 500
    
    def _get_or_create_user_dashboard(self) -> DashboardConfig:
        """Get or create dashboard configuration for current user."""
        try:
            session = self._get_db_session()()
            user_id = getattr(current_user, 'id', None) if hasattr(current_user, 'id') else 1
            
            # Try to get existing dashboard
            dashboard = session.query(DashboardConfig).filter(
                and_(
                    DashboardConfig.owner_id == user_id,
                    DashboardConfig.is_default == True
                )
            ).first()
            
            if not dashboard:
                # Create default dashboard
                dashboard = DashboardConfig(
                    name=f"default_dashboard_{user_id}",
                    title="My Dashboard",
                    description="Auto-generated default dashboard",
                    owner_id=user_id,
                    is_default=True,
                    is_active=True
                )
                session.add(dashboard)
                session.commit()
                session.refresh(dashboard)
                
                # Create default widgets
                self._create_default_widgets(session, dashboard.id)
            
            return dashboard
            
        except Exception as e:
            log.error(f"Error getting/creating dashboard: {e}")
            # Return minimal dashboard config
            return DashboardConfig(
                name="fallback_dashboard",
                title="Dashboard",
                description="Fallback dashboard",
                owner_id=1,
                is_default=True
            )
    
    def _create_default_widgets(self, session, dashboard_id: int):
        """Create default dashboard widgets."""
        try:
            default_widgets = [
                {
                    'widget_id': 'total_users',
                    'name': 'Total Users',
                    'title': 'Total Users',
                    'widget_type': 'metric_card',
                    'data_source': 'user_count',
                    'position_x': 0, 'position_y': 0, 'width': 3, 'height': 2
                },
                {
                    'widget_id': 'alert_rules',
                    'name': 'Alert Rules',
                    'title': 'Alert Rules',
                    'widget_type': 'metric_card',
                    'data_source': 'alert_rule_count',
                    'position_x': 3, 'position_y': 0, 'width': 3, 'height': 2
                },
                {
                    'widget_id': 'active_alerts',
                    'name': 'Active Alerts',
                    'title': 'Active Alerts', 
                    'widget_type': 'metric_card',
                    'data_source': 'active_alert_count',
                    'position_x': 6, 'position_y': 0, 'width': 3, 'height': 2
                },
                {
                    'widget_id': 'recent_logins',
                    'name': 'Recent Logins',
                    'title': 'Recent Logins',
                    'widget_type': 'metric_card',
                    'data_source': 'recent_login_count',
                    'position_x': 9, 'position_y': 0, 'width': 3, 'height': 2
                }
            ]
            
            for widget_config in default_widgets:
                widget = DashboardWidget(
                    dashboard_id=dashboard_id,
                    **widget_config
                )
                session.add(widget)
            
            session.commit()
            
        except Exception as e:
            log.error(f"Error creating default widgets: {e}")
            session.rollback()
    
    def _generate_database_metric_cards(self, time_range: str, dashboard_config: DashboardConfig) -> List[MetricCardWidget]:
        """Generate metric cards using real database data."""
        metric_cards = []
        
        try:
            session = self._get_db_session()()
            
            # Get widgets for this dashboard
            widgets = session.query(DashboardWidget).filter(
                and_(
                    DashboardWidget.dashboard_id == dashboard_config.id,
                    DashboardWidget.widget_type == 'metric_card',
                    DashboardWidget.is_visible == True
                )
            ).order_by(DashboardWidget.order_index).all()
            
            if not widgets:
                # Create fallback metrics if no widgets configured
                widgets = self._get_fallback_widget_configs()
            
            for widget in widgets:
                # Get current value using data source
                current_value = self._get_metric_value_from_database(widget.data_source, time_range)
                
                # Calculate trend
                trend = self._calculate_database_trend(widget.data_source, time_range)
                
                # Create metric card
                card = MetricCardWidget(
                    title=widget.title,
                    value=current_value,
                    trend=trend,
                    subtitle=self._get_metric_subtitle(widget.data_source, time_range),
                    icon=widget.widget_config.get('icon', 'fa-chart-bar') if widget.widget_config else 'fa-chart-bar',
                    color=widget.widget_config.get('color', 'primary') if widget.widget_config else 'primary'
                )
                
                metric_cards.append(card)
                
        except Exception as e:
            log.error(f"Error generating database metric cards: {e}")
            # Add error card
            error_card = MetricCardWidget(
                title="Database Error",
                value="--",
                subtitle=str(e)[:50],
                icon="fa-exclamation-triangle",
                color="danger"
            )
            metric_cards.append(error_card)
        
        return metric_cards
    
    def _get_metric_value_from_database(self, data_source: str, time_range: str) -> int:
        """Get metric value from database based on data source."""
        try:
            session = self._get_db_session()()
            
            if data_source == 'user_count':
                # Count total users
                from pgappforge.security.sqla.models import User
                return session.query(User).count()
            
            elif data_source == 'alert_rule_count':
                # Count alert rules
                return session.query(AlertRule).count()
            
            elif data_source == 'active_alert_count':
                # Count active alerts
                return session.query(AlertHistory).filter(
                    AlertHistory.status == 'active'
                ).count()
            
            elif data_source == 'recent_login_count':
                # Count recent logins (last 24 hours)
                from pgappforge.security.sqla.models import User
                cutoff = datetime.now(tz=timezone.utc) - timedelta(days=1)
                return session.query(User).filter(
                    User.last_login >= cutoff
                ).count() if hasattr(User, 'last_login') else 0
            
            elif data_source == 'metric_snapshots':
                # Count metric snapshots
                return session.query(MetricSnapshot).count()
            
            elif data_source == 'dashboard_count':
                # Count dashboards
                return session.query(DashboardConfig).count()
            
            else:
                # Try to get from metric snapshots
                latest_snapshot = session.query(MetricSnapshot).filter(
                    MetricSnapshot.metric_name == data_source
                ).order_by(MetricSnapshot.timestamp.desc()).first()
                
                return int(latest_snapshot.value) if latest_snapshot else 0
                
        except Exception as e:
            log.warning(f"Error getting metric value for {data_source}: {e}")
            return 0
    
    def _calculate_database_trend(self, data_source: str, time_range: str) -> Optional[float]:
        """Calculate trend using real database data."""
        try:
            session = self._get_db_session()()
            
            # Get time periods
            now = datetime.now(tz=timezone.utc)
            if time_range == '7d':
                current_start = now - timedelta(days=7)
                previous_start = now - timedelta(days=14)
                previous_end = now - timedelta(days=7)
            elif time_range == '30d':
                current_start = now - timedelta(days=30)
                previous_start = now - timedelta(days=60)
                previous_end = now - timedelta(days=30)
            else:
                # Default to 30 days
                current_start = now - timedelta(days=30)
                previous_start = now - timedelta(days=60)
                previous_end = now - timedelta(days=30)
            
            # Get metric snapshots for trend calculation
            current_snapshots = session.query(MetricSnapshot).filter(
                and_(
                    MetricSnapshot.metric_name == data_source,
                    MetricSnapshot.timestamp >= current_start,
                    MetricSnapshot.timestamp <= now
                )
            ).all()
            
            previous_snapshots = session.query(MetricSnapshot).filter(
                and_(
                    MetricSnapshot.metric_name == data_source,
                    MetricSnapshot.timestamp >= previous_start,
                    MetricSnapshot.timestamp <= previous_end
                )
            ).all()
            
            if current_snapshots and previous_snapshots:
                current_avg = sum(s.value for s in current_snapshots) / len(current_snapshots)
                previous_avg = sum(s.value for s in previous_snapshots) / len(previous_snapshots)
                
                if previous_avg > 0:
                    return ((current_avg - previous_avg) / previous_avg) * 100
            
            # Fallback: use simple count-based trends for core metrics
            if data_source == 'user_count':
                return self._calculate_count_trend('user', time_range, 'created_on')
            elif data_source == 'alert_rule_count':
                return self._calculate_count_trend('alert_rule', time_range, 'created_on')
            
            return None
                
        except Exception as e:
            log.warning(f"Error calculating trend for {data_source}: {e}")
            return None
    
    def _calculate_count_trend(self, model_type: str, time_range: str, date_field: str) -> Optional[float]:
        """Calculate trend based on record creation counts."""
        try:
            session = self._get_db_session()()
            now = datetime.now(tz=timezone.utc)
            
            # Get time periods
            if time_range == '7d':
                days = 7
            elif time_range == '30d':
                days = 30
            else:
                days = 30
            
            current_start = now - timedelta(days=days)
            previous_start = now - timedelta(days=days*2)
            previous_end = current_start
            
            # Query based on model type
            if model_type == 'user':
                from pgappforge.security.sqla.models import User
                model_class = User
            elif model_type == 'alert_rule':
                model_class = AlertRule
            else:
                return None
            
            if hasattr(model_class, date_field):
                current_count = session.query(model_class).filter(
                    getattr(model_class, date_field) >= current_start
                ).count()
                
                previous_count = session.query(model_class).filter(
                    and_(
                        getattr(model_class, date_field) >= previous_start,
                        getattr(model_class, date_field) <= previous_end
                    )
                ).count()
                
                if previous_count > 0:
                    return ((current_count - previous_count) / previous_count) * 100
            
            return None
            
        except Exception as e:
            log.warning(f"Error calculating count trend: {e}")
            return None
    
    def _generate_database_trend_charts(self, time_range: str, dashboard_config: DashboardConfig) -> List[Dict[str, Any]]:
        """Generate trend charts using real database data."""
        trend_charts = []
        
        try:
            session = self._get_db_session()()
            
            # Get chart widgets
            chart_widgets = session.query(DashboardWidget).filter(
                and_(
                    DashboardWidget.dashboard_id == dashboard_config.id,
                    DashboardWidget.widget_type == 'chart',
                    DashboardWidget.is_visible == True
                )
            ).all()
            
            for widget in chart_widgets:
                chart_data = self._get_chart_data_from_database(widget.data_source, time_range)
                if chart_data:
                    trend_charts.append({
                        'title': widget.title,
                        'chart_type': widget.widget_config.get('chart_type', 'LineChart') if widget.widget_config else 'LineChart',
                        'data': chart_data,
                        'height': widget.widget_config.get('height', '250px') if widget.widget_config else '250px'
                    })
                    
        except Exception as e:
            log.error(f"Error generating database trend charts: {e}")
            
        return trend_charts
    
    def _get_chart_data_from_database(self, data_source: str, time_range: str) -> List[Dict[str, Any]]:
        """Get chart data from database."""
        try:
            session = self._get_db_session()()
            now = datetime.now(tz=timezone.utc)
            
            if time_range == '7d':
                start_date = now - timedelta(days=7)
            elif time_range == '30d':
                start_date = now - timedelta(days=30)
            else:
                start_date = now - timedelta(days=30)
            
            # Get metric snapshots for charting
            snapshots = session.query(MetricSnapshot).filter(
                and_(
                    MetricSnapshot.metric_name == data_source,
                    MetricSnapshot.timestamp >= start_date
                )
            ).order_by(MetricSnapshot.timestamp).all()
            
            chart_data = []
            for snapshot in snapshots:
                chart_data.append({
                    'timestamp': snapshot.timestamp.isoformat(),
                    'value': snapshot.value
                })
            
            return chart_data
            
        except Exception as e:
            log.warning(f"Error getting chart data for {data_source}: {e}")
            return []
    
    def _get_database_dashboard_data(self, time_range: str) -> Dict[str, Any]:
        """Get additional dashboard data from database."""
        try:
            session = self._get_db_session()()
            
            # Get real system statistics
            from pgappforge.security.sqla.models import User
            total_users = session.query(User).count()
            
            return {
                'last_updated': datetime.now(tz=timezone.utc),
                'total_users': total_users,
                'system_status': 'operational',
                'time_range_label': self._get_time_range_label(time_range),
                'refresh_interval': 300,
                'database_connected': True,
                'total_dashboards': session.query(DashboardConfig).count(),
                'total_alert_rules': session.query(AlertRule).count(),
                'total_metrics': session.query(MetricSnapshot.metric_name).distinct().count()
            }
            
        except Exception as e:
            log.error(f"Error getting dashboard data: {e}")
            return {
                'last_updated': datetime.now(tz=timezone.utc),
                'total_users': 0,
                'system_status': 'error',
                'time_range_label': self._get_time_range_label(time_range),
                'refresh_interval': 300,
                'database_connected': False,
                'error_message': str(e)
            }
    
    def _get_fallback_widget_configs(self) -> List[Dict[str, Any]]:
        """Get fallback widget configurations when none exist."""
        return [
            {
                'title': 'Total Users',
                'data_source': 'user_count',
                'widget_config': {'icon': 'fa-users', 'color': 'primary'}
            },
            {
                'title': 'Alert Rules',
                'data_source': 'alert_rule_count',
                'widget_config': {'icon': 'fa-bell', 'color': 'info'}
            },
            {
                'title': 'Active Alerts',
                'data_source': 'active_alert_count',
                'widget_config': {'icon': 'fa-exclamation-triangle', 'color': 'warning'}
            },
            {
                'title': 'Dashboards',
                'data_source': 'dashboard_count',
                'widget_config': {'icon': 'fa-dashboard', 'color': 'success'}
            }
        ]
    
    def _get_metric_subtitle(self, data_source: str, time_range: str) -> str:
        """Get subtitle for metric based on data source and time range."""
        time_labels = {
            '7d': 'vs last week',
            '30d': 'vs last month', 
            '90d': 'vs last quarter',
            '1y': 'vs last year'
        }
        return time_labels.get(time_range, f'vs previous {time_range}')
    
    def _get_time_range_label(self, time_range: str) -> str:
        """Get human-readable label for time range."""
        labels = {
            '7d': 'Last 7 Days',
            '30d': 'Last 30 Days', 
            '90d': 'Last 90 Days',
            '1y': 'Last Year'
        }
        return labels.get(time_range, time_range)
    
    def _get_time_range_options(self) -> List[Dict[str, str]]:
        """Get available time range options for the UI."""
        return [
            {'value': '7d', 'label': 'Last 7 Days'},
            {'value': '30d', 'label': 'Last 30 Days'},
            {'value': '90d', 'label': 'Last 90 Days'},
            {'value': '1y', 'label': 'Last Year'}
        ]


# Create an alias for backward compatibility
EnhancedDashboardView = DatabaseBackedDashboardView
MetricsDashboardView = DatabaseBackedDashboardView