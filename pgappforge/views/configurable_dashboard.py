"""
Configurable Dashboard View for PgAppForge.

Renders dashboards based on user-saved configurations with flexible layouts
and dynamic widget loading for personalized business intelligence displays.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from flask import render_template, request, jsonify, flash
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from flask_login import current_user

from ..charts.metric_widgets import MetricCardWidget, TrendChartView

log = logging.getLogger(__name__)


class ConfigurableDashboardView(BaseView):
    """
    Dashboard that renders based on user-saved configuration.
    
    Provides fully customizable dashboard experience using saved layout
    preferences, widget selections, and personalized business intelligence displays.
    """
    
    route_base = '/dashboard'
    default_view = 'index'
    
    # Default dashboard configuration for new users
    default_dashboard_config = {
        'title': 'My Dashboard',
        'layout_type': 'grid',
        'widgets': [
            {
                'type': 'metric_card',
                'title': 'Total Records',
                'position': {'row': 0, 'col': 0, 'size': 'small'},
                'config': {
                    'color': 'primary',
                    'icon': 'fa-database',
                    'metric': 'total_records'
                }
            },
            {
                'type': 'metric_card', 
                'title': 'Active Processes',
                'position': {'row': 0, 'col': 1, 'size': 'small'},
                'config': {
                    'color': 'success',
                    'icon': 'fa-play-circle',
                    'metric': 'active_processes'
                }
            },
            {
                'type': 'metric_card',
                'title': 'Pending Approval',
                'position': {'row': 0, 'col': 2, 'size': 'small'},
                'config': {
                    'color': 'warning',
                    'icon': 'fa-clock',
                    'metric': 'pending_approval'
                }
            },
            {
                'type': 'trend_chart',
                'title': 'Monthly Trends',
                'position': {'row': 1, 'col': 0, 'size': 'large'},
                'config': {
                    'time_range': '30d',
                    'chart_type': 'line'
                }
            }
        ],
        'show_refresh_button': True,
        'auto_refresh_interval': 300
    }
    
    @expose('/')
    @has_access
    def index(self):
        """
        Render dashboard based on user configuration.
        
        Returns:
            Rendered dashboard template with configured widgets and layout
        """
        try:
            # Get user's dashboard configuration
            config = self._get_user_dashboard_config()
            
            # Render configured widgets
            widgets = self._render_configured_widgets(config.get('widgets', []))
            
            # Get additional dashboard data
            dashboard_data = self._get_dashboard_context(config)
            
            # Determine template based on layout type
            template_name = self._get_layout_template(config.get('layout_type', 'grid'))
            
            return self.render_template(
                template_name,
                config=config,
                widgets=widgets,
                dashboard_data=dashboard_data,
                layout_type=config.get('layout_type', 'grid')
            )
            
        except Exception as e:
            log.error(f"Error rendering configurable dashboard: {e}")
            flash(f'Error loading dashboard: {str(e)}', 'error')
            return self.render_template(
                'analytics/dashboard_error.html',
                error_message=str(e)
            )
    
    @expose('/layout/<layout_type>')
    @has_access
    def switch_layout(self, layout_type):
        """
        Switch dashboard layout type.
        
        Args:
            layout_type: New layout type ('grid', 'tabs', 'single_column', 'two_column')
        
        Returns:
            Redirected to dashboard with new layout
        """
        try:
            # Validate layout type
            valid_layouts = ['grid', 'tabs', 'single_column', 'two_column']
            if layout_type not in valid_layouts:
                flash('Invalid layout type', 'error')
                return redirect(url_for('ConfigurableDashboardView.index'))
            
            # Update user's dashboard configuration
            config = self._get_user_dashboard_config()
            config['layout_type'] = layout_type
            
            # Save updated configuration
            if self._save_dashboard_config(config):
                flash(f'Layout changed to {layout_type.replace("_", " ").title()}', 'success')
            else:
                flash('Failed to save layout change', 'warning')
            
            return redirect(url_for('ConfigurableDashboardView.index'))
            
        except Exception as e:
            log.error(f"Error switching dashboard layout: {e}")
            flash(f'Error changing layout: {str(e)}', 'error')
            return redirect(url_for('ConfigurableDashboardView.index'))
    
    @expose('/api/widgets')
    @has_access
    def api_widgets(self):
        """
        API endpoint for getting dashboard widgets data.
        
        Returns:
            JSON response with widget data for AJAX updates
        """
        try:
            config = self._get_user_dashboard_config()
            widgets_data = []
            
            for widget_config in config.get('widgets', []):
                widget_data = self._get_widget_data(widget_config)
                if widget_data:
                    widgets_data.append(widget_data)
            
            return jsonify({
                'status': 'success',
                'widgets': widgets_data,
                'config': {
                    'title': config.get('title', 'Dashboard'),
                    'layout_type': config.get('layout_type', 'grid'),
                    'auto_refresh_interval': config.get('auto_refresh_interval', 300)
                },
                'updated_at': datetime.now().isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting dashboard widgets API: {e}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @expose('/api/refresh', methods=['POST'])
    @has_access
    def api_refresh_dashboard(self):
        """
        API endpoint to refresh dashboard data.
        
        Returns:
            JSON response with updated dashboard content
        """
        try:
            # Get current configuration
            config = self._get_user_dashboard_config()
            
            # Generate fresh widget data
            widgets = self._render_configured_widgets(config.get('widgets', []))
            
            # Convert widgets to JSON-serializable format
            widgets_data = []
            for widget in widgets:
                if hasattr(widget, 'render_metric_card'):
                    # MetricCardWidget
                    widgets_data.append({
                        'type': 'metric_card',
                        'html': widget.render_metric_card(),
                        'title': widget.title,
                        'value': widget.value,
                        'trend': widget.trend
                    })
                else:
                    # Other widget types
                    widgets_data.append({
                        'type': 'unknown',
                        'html': str(widget),
                        'title': 'Widget'
                    })
            
            return jsonify({
                'status': 'success',
                'widgets': widgets_data,
                'refreshed_at': datetime.now().isoformat()
            })
            
        except Exception as e:
            log.error(f"Error refreshing dashboard: {e}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    def _get_user_dashboard_config(self) -> Dict[str, Any]:
        """
        Get current user's dashboard configuration.
        
        Returns:
            Dictionary with dashboard configuration
        """
        try:
            if not current_user.is_authenticated:
                return self.default_dashboard_config.copy()
            
            # In a real implementation, this would query from database
            # For now, return the default configuration
            return self.default_dashboard_config.copy()
            
        except Exception as e:
            log.warning(f"Error getting user dashboard config: {e}")
            return self.default_dashboard_config.copy()
    
    def _save_dashboard_config(self, config: Dict[str, Any]) -> bool:
        """
        Save dashboard configuration for current user.
        
        Args:
            config: Dashboard configuration dictionary
            
        Returns:
            bool: True if saved successfully
        """
        try:
            if not current_user.is_authenticated:
                return False
            
            # In a real implementation, this would save to database
            # For now, simulate successful save
            log.info(f"Dashboard config updated for user {current_user.id}")
            return True
            
        except Exception as e:
            log.error(f"Error saving dashboard config: {e}")
            return False
    
    def _render_configured_widgets(self, widgets_config: List[Dict]) -> List[Any]:
        """
        Render widgets based on configuration.
        
        Args:
            widgets_config: List of widget configuration dictionaries
            
        Returns:
            List of rendered widget objects
        """
        rendered_widgets = []
        
        for widget_config in widgets_config:
            try:
                widget = self._create_widget_from_config(widget_config)
                if widget:
                    rendered_widgets.append(widget)
            except Exception as e:
                log.warning(f"Error rendering widget: {e}")
                # Add error widget
                error_widget = self._create_error_widget(
                    widget_config.get('title', 'Unknown Widget'),
                    str(e)
                )
                rendered_widgets.append(error_widget)
        
        return rendered_widgets
    
    def _create_widget_from_config(self, widget_config: Dict) -> Optional[Any]:
        """
        Create widget instance from configuration.
        
        Args:
            widget_config: Widget configuration dictionary
            
        Returns:
            Widget instance or None if creation fails
        """
        widget_type = widget_config.get('type', 'metric_card')
        widget_title = widget_config.get('title', 'Widget')
        widget_settings = widget_config.get('config', {})
        
        if widget_type == 'metric_card':
            return self._create_metric_card_widget(widget_title, widget_settings)
        elif widget_type == 'trend_chart':
            return self._create_trend_chart_widget(widget_title, widget_settings)
        elif widget_type == 'status_pie':
            return self._create_status_pie_widget(widget_title, widget_settings)
        elif widget_type == 'data_table':
            return self._create_data_table_widget(widget_title, widget_settings)
        elif widget_type == 'activity_feed':
            return self._create_activity_feed_widget(widget_title, widget_settings)
        else:
            log.warning(f"Unknown widget type: {widget_type}")
            return None
    
    def _create_metric_card_widget(self, title: str, settings: Dict) -> MetricCardWidget:
        """Create metric card widget from settings."""
        # Get metric data based on configuration
        metric_type = settings.get('metric', 'total_records')
        value, trend = self._get_metric_data(metric_type)
        
        return MetricCardWidget(
            title=title,
            value=value,
            trend=trend,
            subtitle=settings.get('subtitle', 'vs last period'),
            icon=settings.get('icon', 'fa-chart-bar'),
            color=settings.get('color', 'primary')
        )
    
    def _create_trend_chart_widget(self, title: str, settings: Dict) -> Dict[str, Any]:
        """Create trend chart widget configuration."""
        # Return chart configuration for template rendering
        return {
            'type': 'trend_chart',
            'title': title,
            'chart_type': settings.get('chart_type', 'line'),
            'time_range': settings.get('time_range', '30d'),
            'data': self._get_trend_chart_data(settings.get('time_range', '30d')),
            'height': '300px'
        }
    
    def _create_status_pie_widget(self, title: str, settings: Dict) -> Dict[str, Any]:
        """Create status pie chart widget configuration."""
        return {
            'type': 'status_pie',
            'title': title,
            'data': self._get_status_pie_data(settings.get('field', 'status')),
            'height': '250px'
        }
    
    def _create_data_table_widget(self, title: str, settings: Dict) -> Dict[str, Any]:
        """Create data table widget configuration."""
        return {
            'type': 'data_table',
            'title': title,
            'data': self._get_table_data(settings.get('limit', 10)),
            'columns': ['Name', 'Status', 'Updated'],
            'limit': settings.get('limit', 10)
        }
    
    def _create_activity_feed_widget(self, title: str, settings: Dict) -> Dict[str, Any]:
        """Create activity feed widget configuration."""
        return {
            'type': 'activity_feed',
            'title': title,
            'activities': self._get_activity_data(settings.get('limit', 5)),
            'limit': settings.get('limit', 5)
        }
    
    def _create_error_widget(self, title: str, error_message: str) -> MetricCardWidget:
        """Create error widget to display widget creation failures."""
        return MetricCardWidget(
            title=title,
            value="Error",
            subtitle=error_message,
            icon="fa-exclamation-triangle",
            color="danger"
        )
    
    def _get_metric_data(self, metric_type: str) -> tuple[int, Optional[float]]:
        """
        Get metric data for specified metric type.
        
        Args:
            metric_type: Type of metric to retrieve
            
        Returns:
            Tuple of (value, trend_percentage)
        """
        # Mock data - in real implementation would query database
        metrics_data = {
            'total_records': (1250, 15.2),
            'active_processes': (45, -5.1),
            'pending_approval': (12, 8.7),
            'completed_today': (8, 22.3),
            'error_rate': (2.3, -12.4),
            'avg_processing_time': (145, -8.9)
        }
        
        return metrics_data.get(metric_type, (0, None))
    
    def _get_trend_chart_data(self, time_range: str) -> List[Dict]:
        """Get trend chart data for specified time range."""
        # Mock trend data
        days = {'7d': 7, '30d': 30, '90d': 90, '1y': 365}.get(time_range, 30)
        
        chart_data = []
        for i in range(min(days, 30)):  # Limit to 30 points for performance
            date = datetime.now() - timedelta(days=days-i)
            value = 100 + (i * 5) + (i % 7 * 10)  # Mock trending data
            chart_data.append({
                'date': date.strftime('%Y-%m-%d'),
                'value': value,
                'label': date.strftime('%m/%d')
            })
        
        return chart_data
    
    def _get_status_pie_data(self, field: str) -> List[Dict]:
        """Get status distribution data for pie chart."""
        # Mock status data
        return [
            {'label': 'Active', 'value': 45, 'color': '#28a745'},
            {'label': 'Pending', 'value': 12, 'color': '#ffc107'},
            {'label': 'Completed', 'value': 89, 'color': '#17a2b8'},
            {'label': 'Archived', 'value': 23, 'color': '#6c757d'}
        ]
    
    def _get_table_data(self, limit: int) -> List[Dict]:
        """Get recent records data for table display."""
        # Mock table data
        return [
            {
                'name': 'Record 001',
                'status': 'Active',
                'updated': '2 hours ago',
                'id': 1
            },
            {
                'name': 'Record 002', 
                'status': 'Pending',
                'updated': '5 hours ago',
                'id': 2
            },
            {
                'name': 'Record 003',
                'status': 'Completed',
                'updated': '1 day ago',
                'id': 3
            }
        ][:limit]
    
    def _get_activity_data(self, limit: int) -> List[Dict]:
        """Get recent activity data for activity feed."""
        # Mock activity data
        activities = [
            {
                'action': 'Record Created',
                'user': 'John Doe',
                'time': '5 minutes ago',
                'icon': 'fa-plus-circle',
                'color': 'success'
            },
            {
                'action': 'Status Updated',
                'user': 'Jane Smith',
                'time': '15 minutes ago',
                'icon': 'fa-edit',
                'color': 'primary'
            },
            {
                'action': 'Record Approved',
                'user': 'Admin',
                'time': '1 hour ago',
                'icon': 'fa-check-circle',
                'color': 'success'
            },
            {
                'action': 'Comment Added',
                'user': 'Bob Johnson',
                'time': '2 hours ago',
                'icon': 'fa-comment',
                'color': 'info'
            }
        ]
        
        return activities[:limit]
    
    def _get_widget_data(self, widget_config: Dict) -> Optional[Dict]:
        """
        Get widget data for API responses.
        
        Args:
            widget_config: Widget configuration dictionary
            
        Returns:
            Widget data dictionary or None
        """
        try:
            widget_type = widget_config.get('type', 'metric_card')
            title = widget_config.get('title', 'Widget')
            
            if widget_type == 'metric_card':
                settings = widget_config.get('config', {})
                metric_type = settings.get('metric', 'total_records')
                value, trend = self._get_metric_data(metric_type)
                
                return {
                    'type': 'metric_card',
                    'title': title,
                    'value': value,
                    'trend': trend,
                    'formatted_value': self._format_metric_value(value),
                    'trend_text': self._format_trend_text(trend),
                    'position': widget_config.get('position', {'row': 0, 'col': 0})
                }
            else:
                return {
                    'type': widget_type,
                    'title': title,
                    'position': widget_config.get('position', {'row': 0, 'col': 0})
                }
        except Exception as e:
            log.warning(f"Error getting widget data: {e}")
            return None
    
    def _format_metric_value(self, value: int) -> str:
        """Format metric value for display."""
        if value >= 1000000:
            return f"{value/1000000:.1f}M"
        elif value >= 1000:
            return f"{value/1000:.1f}K"
        else:
            return str(value)
    
    def _format_trend_text(self, trend: Optional[float]) -> str:
        """Format trend percentage for display."""
        if trend is None:
            return ""
        
        direction = "increase" if trend > 0 else "decrease"
        return f"{abs(trend):.1f}% {direction}"
    
    def _get_dashboard_context(self, config: Dict) -> Dict[str, Any]:
        """Get additional dashboard context data."""
        return {
            'title': config.get('title', 'My Dashboard'),
            'last_updated': datetime.now(),
            'widget_count': len(config.get('widgets', [])),
            'layout_type': config.get('layout_type', 'grid'),
            'show_refresh_button': config.get('show_refresh_button', True),
            'auto_refresh_interval': config.get('auto_refresh_interval', 300),
            'user_name': current_user.username if current_user.is_authenticated else 'Guest'
        }
    
    def _get_layout_template(self, layout_type: str) -> str:
        """
        Get template name based on layout type.
        
        Args:
            layout_type: Layout type ('grid', 'tabs', 'single_column', 'two_column')
            
        Returns:
            Template file name
        """
        template_map = {
            'grid': 'analytics/configurable_dashboard_grid.html',
            'tabs': 'analytics/configurable_dashboard_tabs.html', 
            'single_column': 'analytics/configurable_dashboard_single.html',
            'two_column': 'analytics/configurable_dashboard_two_column.html'
        }
        
        return template_map.get(layout_type, 'analytics/configurable_dashboard_grid.html')