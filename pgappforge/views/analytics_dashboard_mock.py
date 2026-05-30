"""
Enhanced Analytics Dashboard View.

Provides comprehensive dashboard functionality using MetricCardWidget and TrendChartView
for advanced data visualization and business intelligence.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from flask import render_template, request, jsonify, flash, redirect, url_for
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.models.sqla.interface import SQLAInterface
from flask_login import current_user

from ..charts.metric_widgets import MetricCardWidget, TrendChartView

log = logging.getLogger(__name__)


class EnhancedDashboardView(BaseView):
    """
    Enhanced dashboard using new metric card widgets and trend charts.
    
    Provides a comprehensive business intelligence dashboard with:
    - Key metric cards with trend indicators
    - Time-series trend visualization  
    - Interactive filtering and customization
    - Integration with existing PgAppForge patterns
    """
    
    route_base = '/enhanced-dashboard'
    default_view = 'index'
    
    # Default metrics to display
    default_metrics = [
        {
            'title': 'Total Records',
            'field': 'id',
            'aggregation': 'count',
            'icon': 'fa-database',
            'color': 'primary'
        },
        {
            'title': 'Active Processes', 
            'field': 'status',
            'aggregation': 'count',
            'filter_value': 'active',
            'icon': 'fa-play-circle',
            'color': 'success'
        },
        {
            'title': 'Pending Approval',
            'field': 'status', 
            'aggregation': 'count',
            'filter_value': 'pending_approval',
            'icon': 'fa-clock',
            'color': 'warning'
        },
        {
            'title': 'Completed Today',
            'field': 'changed_on',
            'aggregation': 'count',
            'date_filter': 'today',
            'icon': 'fa-check-circle',
            'color': 'info'
        }
    ]
    
    @expose('/')
    @has_access
    def index(self):
        """
        Main dashboard view with metric cards and trend charts.
        
        Returns:
            Rendered dashboard template with metrics and charts
        """
        try:
            # Get time range from request (default to 30 days)
            time_range = request.args.get('time_range', '30d')
            
            # Generate metric cards
            metric_cards = self._generate_metric_cards(time_range)
            
            # Generate trend charts
            trend_charts = self._generate_trend_charts(time_range)
            
            # Get additional dashboard data
            dashboard_data = self._get_dashboard_data(time_range)
            
            return self.render_template(
                'analytics/enhanced_dashboard.html',
                metric_cards=metric_cards,
                trend_charts=trend_charts,
                dashboard_data=dashboard_data,
                time_range=time_range,
                available_time_ranges=self._get_time_range_options()
            )
            
        except Exception as e:
            log.error(f"Error rendering enhanced dashboard: {e}")
            flash(f"Error loading dashboard: {str(e)}", 'error')
            return self.render_template(
                'analytics/dashboard_error.html',
                error_message=str(e)
            )
    
    @expose('/api/metrics')
    @has_access 
    def api_metrics(self):
        """
        API endpoint for getting metrics data (AJAX support).
        
        Returns:
            JSON response with current metrics
        """
        try:
            time_range = request.args.get('time_range', '30d')
            metric_cards = self._generate_metric_cards(time_range)
            
            # Convert metric cards to JSON-serializable format
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
                'generated_at': datetime.now().isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting metrics API data: {e}")
            return jsonify({
                'status': 'error', 
                'error': str(e)
            }), 500
    
    def _generate_metric_cards(self, time_range: str = '30d') -> List[MetricCardWidget]:
        """
        Generate metric cards based on configured metrics.
        
        Args:
            time_range: Time range for trend calculation
            
        Returns:
            List of MetricCardWidget instances
        """
        metric_cards = []
        
        try:
            for metric_config in self.default_metrics:
                # Get current metric value
                current_value = self._calculate_metric_value(metric_config)
                
                # Calculate trend percentage
                trend_percentage = self._calculate_metric_trend(metric_config, time_range)
                
                # Create metric card
                card = MetricCardWidget(
                    title=metric_config['title'],
                    value=current_value,
                    trend=trend_percentage,
                    subtitle=self._get_metric_subtitle(metric_config, time_range),
                    icon=metric_config.get('icon', 'fa-chart-bar'),
                    color=metric_config.get('color', 'primary')
                )
                
                metric_cards.append(card)
                
        except Exception as e:
            log.error(f"Error generating metric cards: {e}")
            # Add error card
            error_card = MetricCardWidget(
                title="Error Loading Metrics",
                value="--",
                subtitle=str(e),
                icon="fa-exclamation-triangle",
                color="danger"
            )
            metric_cards.append(error_card)
        
        return metric_cards
    
    def _generate_trend_charts(self, time_range: str = '30d') -> List[Dict[str, Any]]:
        """
        Generate trend chart configurations.
        
        Args:
            time_range: Time range for trend data
            
        Returns:
            List of trend chart configurations
        """
        trend_charts = []
        
        try:
            # Create sample trend charts based on available models with StateTrackingMixin
            models_with_tracking = self._get_models_with_state_tracking()
            
            for model_class in models_with_tracking[:3]:  # Limit to 3 charts
                trend_view = TrendChartView()
                trend_view.datamodel = SQLAInterface(model_class)
                
                # Get chart data
                chart_data = trend_view.get_trend_data('changed_on', 'id', time_range)
                
                if chart_data:
                    trend_charts.append({
                        'title': f"{model_class.__name__} Trend",
                        'chart_type': 'LineChart',
                        'data': chart_data,
                        'height': '250px'
                    })
                    
        except Exception as e:
            log.error(f"Error generating trend charts: {e}")
            
        return trend_charts
    
    def _calculate_metric_value(self, metric_config: Dict[str, Any]) -> int:
        """
        Calculate current value for a metric configuration.
        
        Args:
            metric_config: Metric configuration dictionary
            
        Returns:
            int: Current metric value
        """
        try:
            # This is a simplified implementation
            # In a real application, this would query the actual database
            
            # Mock data generation based on metric type
            if 'Total Records' in metric_config['title']:
                return 1250
            elif 'Active Processes' in metric_config['title']:
                return 45
            elif 'Pending Approval' in metric_config['title']:
                return 12
            elif 'Completed Today' in metric_config['title']:
                return 8
            else:
                return 0
                
        except Exception as e:
            log.warning(f"Error calculating metric value: {e}")
            return 0
    
    def _calculate_metric_trend(self, metric_config: Dict[str, Any], 
                               time_range: str) -> Optional[float]:
        """
        Calculate trend percentage for a metric.
        
        Args:
            metric_config: Metric configuration
            time_range: Time range for trend calculation
            
        Returns:
            Optional[float]: Trend percentage (positive = increasing)
        """
        try:
            # Mock trend calculation
            # In a real application, this would compare current vs historical values
            
            if 'Total Records' in metric_config['title']:
                return 15.2
            elif 'Active Processes' in metric_config['title']:
                return -5.1
            elif 'Pending Approval' in metric_config['title']:
                return 8.7
            elif 'Completed Today' in metric_config['title']:
                return 22.3
            else:
                return None
                
        except Exception as e:
            log.warning(f"Error calculating metric trend: {e}")
            return None
    
    def _get_metric_subtitle(self, metric_config: Dict[str, Any], 
                            time_range: str) -> str:
        """
        Get subtitle text for a metric card.
        
        Args:
            metric_config: Metric configuration
            time_range: Time range being displayed
            
        Returns:
            str: Subtitle text
        """
        time_labels = {
            '7d': 'vs last week',
            '30d': 'vs last month', 
            '90d': 'vs last quarter',
            '1y': 'vs last year'
        }
        
        return time_labels.get(time_range, f'vs previous {time_range}')
    
    def _get_dashboard_data(self, time_range: str) -> Dict[str, Any]:
        """
        Get additional dashboard data and context.
        
        Args:
            time_range: Current time range selection
            
        Returns:
            Dict with additional dashboard data
        """
        return {
            'last_updated': datetime.now(),
            'total_users': self._get_total_users(),
            'system_status': 'operational',
            'time_range_label': self._get_time_range_label(time_range),
            'refresh_interval': 300  # 5 minutes
        }
    
    def _get_total_users(self) -> int:
        """Get total number of system users."""
        try:
            # This would query the actual user model in production
            return 156
        except Exception:
            return 0
    
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
    
    def _get_models_with_state_tracking(self) -> List[Any]:
        """
        Get list of model classes that use StateTrackingMixin.
        
        Returns:
            List of model classes with state tracking capabilities
        """
        # This would dynamically discover models in a real implementation
        # For now, return an empty list as we don't have real model registry
        return []


class MetricsDashboardView(BaseView):
    """
    Simplified metrics dashboard for quick metric viewing.
    
    Provides a focused view of key business metrics without the full
    dashboard complexity.
    """
    
    route_base = '/metrics-dashboard'
    
    @expose('/')
    @has_access
    def index(self):
        """
        Simple metrics dashboard view.
        
        Returns:
            Rendered metrics template
        """
        try:
            # Create key metric cards
            total_records = MetricCardWidget(
                "Total Records", 
                1250, 
                trend=15.2,
                subtitle="vs last month",
                icon="fa-database",
                color="primary"
            )
            
            active_processes = MetricCardWidget(
                "Active Processes", 
                45, 
                trend=-5.1,
                subtitle="vs last month", 
                icon="fa-play-circle",
                color="success"
            )
            
            pending_approval = MetricCardWidget(
                "Pending Approval",
                12,
                trend=8.7,
                subtitle="vs last month",
                icon="fa-clock",
                color="warning"
            )
            
            completed_today = MetricCardWidget(
                "Completed Today",
                8,
                trend=22.3,
                subtitle="vs yesterday",
                icon="fa-check-circle", 
                color="info"
            )
            
            metric_cards = [total_records, active_processes, pending_approval, completed_today]
            
            return self.render_template(
                'analytics/metrics_dashboard.html',
                metric_cards=metric_cards,
                last_updated=datetime.now()
            )
            
        except Exception as e:
            log.error(f"Error rendering metrics dashboard: {e}")
            return self.render_template(
                'analytics/dashboard_error.html',
                error_message=str(e)
            )