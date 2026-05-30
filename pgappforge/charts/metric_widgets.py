"""
Metric Card Widgets for Enhanced Analytics Dashboard.

Provides card-based visualization for key metrics with trend indicators.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Union

from flask import render_template_string
from pgappforge.widgets.core import RenderTemplateWidget
from pgappforge.charts.views import BaseChartView
from pgappforge.models.group import GroupByProcessData

log = logging.getLogger(__name__)


class MetricCardWidget(RenderTemplateWidget):
    """
    Widget for displaying key metrics as cards with optional trend indicators.
    
    Integrates with existing PgAppForge chart system and provides
    card-based visualization for dashboard metrics.
    """
    
    template = "appbuilder/widgets/metric_card.html"
    
    def __init__(self, title: str, value: Union[int, float, str], 
                 trend: Optional[float] = None, 
                 subtitle: Optional[str] = None,
                 icon: Optional[str] = None,
                 color: Optional[str] = None,
                 **kwargs):
        """
        Initialize metric card widget.
        
        Args:
            title: The metric title/name
            value: Current metric value  
            trend: Trend percentage (positive = up, negative = down)
            subtitle: Optional subtitle text
            icon: Optional icon class (e.g., 'fa-users', 'fa-chart-line')
            color: Optional color theme ('primary', 'success', 'warning', 'danger')
            **kwargs: Additional template arguments
        """
        super().__init__(**kwargs)
        self.title = title
        self.value = value
        self.trend = trend
        self.subtitle = subtitle or ""
        self.icon = icon or "fa-chart-bar"
        self.color = color or "primary"
        
    def render_metric_card(self) -> str:
        """
        Render metric as a card with optional trend indicator.
        
        Returns:
            str: Rendered HTML for the metric card
        """
        # Format the value for display
        formatted_value = self._format_value(self.value)
        
        # Get trend information
        trend_class = self._get_trend_class()
        trend_icon = self._get_trend_icon()
        trend_text = self._get_trend_text()
        
        # Build template context
        context = {
            'title': self.title,
            'value': formatted_value,
            'subtitle': self.subtitle,
            'icon': self.icon,
            'color': self.color,
            'trend': self.trend,
            'trend_class': trend_class,
            'trend_icon': trend_icon,
            'trend_text': trend_text,
            'has_trend': self.trend is not None
        }
        
        # Update with any additional template args
        if self.template_args:
            context.update(self.template_args)
        
        return self._render_card_template(context)
    
    def _format_value(self, value: Union[int, float, str]) -> str:
        """
        Format the metric value for display.
        
        Args:
            value: Raw metric value
            
        Returns:
            str: Formatted value string
        """
        if isinstance(value, (int, float)):
            if value >= 1000000:
                return f"{value/1000000:.1f}M"
            elif value >= 1000:
                return f"{value/1000:.1f}K"
            elif isinstance(value, float):
                return f"{value:.1f}"
            else:
                return str(value)
        else:
            return str(value)
    
    def _get_trend_class(self) -> str:
        """
        Get CSS class based on trend direction.
        
        Returns:
            str: CSS class for trend styling
        """
        if not self.trend:
            return ''
        
        if self.trend > 0:
            return 'trend-up text-success'
        elif self.trend < 0:
            return 'trend-down text-danger' 
        else:
            return 'trend-neutral text-muted'
    
    def _get_trend_icon(self) -> str:
        """
        Get icon based on trend direction.
        
        Returns:
            str: Icon class for trend direction
        """
        if not self.trend:
            return ''
        
        if self.trend > 0:
            return 'fa-arrow-up'
        elif self.trend < 0:
            return 'fa-arrow-down'
        else:
            return 'fa-minus'
    
    def _get_trend_text(self) -> str:
        """
        Get trend text description.
        
        Returns:
            str: Trend text for display
        """
        if not self.trend:
            return ''
        
        abs_trend = abs(self.trend)
        direction = 'increase' if self.trend > 0 else 'decrease'
        
        return f"{abs_trend:.1f}% {direction}"
    
    def _render_card_template(self, context: Dict[str, Any]) -> str:
        """
        Render the metric card template.
        
        Args:
            context: Template context variables
            
        Returns:
            str: Rendered HTML
        """
        # Inline template for now - in production would use external template file
        template_html = """
        <div class="metric-card card border-0 shadow-sm">
            <div class="card-body p-3">
                <div class="d-flex align-items-center justify-content-between">
                    <div class="metric-content">
                        <h6 class="card-subtitle mb-1 text-muted">{{ title }}</h6>
                        <h3 class="card-title mb-0 fw-bold text-{{ color }}">{{ value }}</h3>
                        {% if subtitle %}
                        <small class="text-muted">{{ subtitle }}</small>
                        {% endif %}
                        {% if has_trend %}
                        <div class="metric-trend mt-1">
                            <small class="{{ trend_class }}">
                                <i class="fas {{ trend_icon }}"></i>
                                {{ trend_text }}
                            </small>
                        </div>
                        {% endif %}
                    </div>
                    <div class="metric-icon">
                        <i class="fas {{ icon }} fa-2x text-{{ color }}-emphasis opacity-75"></i>
                    </div>
                </div>
            </div>
        </div>
        """
        
        try:
            return render_template_string(template_html, **context)
        except Exception as e:
            log.error(f"Error rendering metric card template: {e}")
            return f'<div class="alert alert-warning">Error rendering metric: {self.title}</div>'


class TrendChartView(BaseChartView):
    """
    Chart view for displaying time-series trends with metric cards.
    
    Extends BaseChartView to provide time-series analysis and trend visualization
    integrated with MetricCardWidget for comprehensive dashboard displays.
    """
    
    chart_type = "LineChart"
    chart_title = "Trend Analysis"
    chart_3d = "false"  # Line charts work better in 2D
    height = "300px"
    
    # Default time ranges
    time_ranges = {
        '7d': {'days': 7, 'label': 'Last 7 Days'},
        '30d': {'days': 30, 'label': 'Last 30 Days'},
        '90d': {'days': 90, 'label': 'Last 90 Days'},
        '1y': {'days': 365, 'label': 'Last Year'}
    }
    
    def get_trend_data(self, date_field: str, value_field: str, 
                       time_range: str = '30d') -> List[Dict[str, Any]]:
        """
        Get trend data using existing GroupByProcessData patterns.
        
        Args:
            date_field: Database field containing dates
            value_field: Database field containing values to aggregate
            time_range: Time range key ('7d', '30d', '90d', '1y')
            
        Returns:
            List of data points for trend visualization
        """
        try:
            # Build on existing chart data patterns
            group_by = GroupByProcessData(
                self.datamodel,
                [date_field],
                value_field
            )
            
            # Apply time range filter
            if time_range in self.time_ranges:
                days_back = self.time_ranges[time_range]['days']
                start_date = datetime.now() - timedelta(days=days_back)
                
                # Apply date filter using existing patterns
                group_by._apply_filters([{
                    'field': date_field,
                    'op': '>=',
                    'value': start_date.strftime('%Y-%m-%d')
                }])
            
            # Get grouped data
            raw_data = group_by.apply_filter_and_group()
            
            # Format for chart display
            return self._format_trend_data(raw_data, date_field, value_field)
            
        except Exception as e:
            log.error(f"Error getting trend data: {e}")
            return []
    
    def _format_trend_data(self, raw_data: List[Dict], 
                          date_field: str, value_field: str) -> List[Dict[str, Any]]:
        """
        Format raw trend data for chart visualization.
        
        Args:
            raw_data: Raw data from GroupByProcessData
            date_field: Date field name
            value_field: Value field name
            
        Returns:
            List of formatted data points
        """
        formatted_data = []
        
        for item in raw_data:
            try:
                # Handle different data formats
                if isinstance(item, dict):
                    date_val = item.get(date_field)
                    value_val = item.get(value_field, 0)
                else:
                    date_val = getattr(item, date_field, None)
                    value_val = getattr(item, value_field, 0)
                
                # Format for chart
                formatted_item = {
                    'date': self._format_date_for_chart(date_val),
                    'value': float(value_val) if value_val else 0,
                    'label': str(date_val)
                }
                
                formatted_data.append(formatted_item)
                
            except Exception as e:
                log.warning(f"Error formatting trend data item: {e}")
                continue
        
        # Sort by date
        formatted_data.sort(key=lambda x: x['date'])
        
        return formatted_data
    
    def _format_date_for_chart(self, date_val) -> str:
        """
        Format date value for chart display.
        
        Args:
            date_val: Date value in various formats
            
        Returns:
            str: Formatted date string
        """
        if not date_val:
            return datetime.now().strftime('%Y-%m-%d')
        
        if isinstance(date_val, datetime):
            return date_val.strftime('%Y-%m-%d')
        elif isinstance(date_val, str):
            try:
                # Try to parse common date formats
                parsed_date = datetime.strptime(date_val, '%Y-%m-%d')
                return parsed_date.strftime('%Y-%m-%d')
            except ValueError:
                return date_val
        else:
            return str(date_val)
    
    def calculate_trend_percentage(self, data: List[Dict[str, Any]]) -> Optional[float]:
        """
        Calculate trend percentage from time series data.
        
        Args:
            data: List of data points with 'value' key
            
        Returns:
            Optional[float]: Trend percentage (positive = increasing trend)
        """
        if not data or len(data) < 2:
            return None
        
        try:
            # Get values from start and end of period
            start_value = data[0]['value']
            end_value = data[-1]['value']
            
            # Handle zero division
            if start_value == 0:
                return 100.0 if end_value > 0 else 0.0
            
            # Calculate percentage change
            percentage_change = ((end_value - start_value) / start_value) * 100
            
            return round(percentage_change, 1)
            
        except (KeyError, ValueError, ZeroDivisionError) as e:
            log.warning(f"Error calculating trend percentage: {e}")
            return None
    
    def get_metric_summary(self, date_field: str, value_field: str, 
                          time_range: str = '30d') -> Dict[str, Any]:
        """
        Get metric summary including current value, trend, and chart data.
        
        Args:
            date_field: Database field containing dates
            value_field: Database field containing values
            time_range: Time range for analysis
            
        Returns:
            Dict with metric summary data
        """
        try:
            # Get trend data
            trend_data = self.get_trend_data(date_field, value_field, time_range)
            
            if not trend_data:
                return {
                    'current_value': 0,
                    'trend_percentage': None,
                    'chart_data': [],
                    'time_range_label': self.time_ranges.get(time_range, {}).get('label', time_range)
                }
            
            # Calculate summary metrics
            current_value = trend_data[-1]['value'] if trend_data else 0
            trend_percentage = self.calculate_trend_percentage(trend_data)
            
            return {
                'current_value': current_value,
                'trend_percentage': trend_percentage,
                'chart_data': trend_data,
                'time_range_label': self.time_ranges.get(time_range, {}).get('label', time_range),
                'data_points': len(trend_data)
            }
            
        except Exception as e:
            log.error(f"Error getting metric summary: {e}")
            return {
                'current_value': 0,
                'trend_percentage': None,
                'chart_data': [],
                'time_range_label': 'Error',
                'error': str(e)
            }