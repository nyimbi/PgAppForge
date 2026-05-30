"""
Test MetricCardWidget and TrendChartView functionality.

Tests the enhanced analytics capabilities including metric cards,
trend analysis, and dashboard integration.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json

from flask import Flask
from sqlalchemy import Column, Integer, String, DateTime, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Test the MetricCardWidget and related classes
Base = declarative_base()


class MockUser:
    """Mock user for testing dashboard views."""
    
    def __init__(self, username="testuser"):
        self.id = 123
        self.username = username
        self.is_authenticated = True


class TestAnalyticsModel(Base):
    """Test model for analytics testing."""
    
    __tablename__ = 'test_analytics_models'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    status = Column(String(50), default='active')
    value = Column(Integer, default=0)
    created_on = Column(DateTime, default=datetime.utcnow)
    changed_on = Column(DateTime, default=datetime.utcnow)


# Import the classes we're testing
from pgappforge.charts.metric_widgets import MetricCardWidget, TrendChartView
from pgappforge.views.analytics_dashboard import EnhancedDashboardView, MetricsDashboardView


class TestMetricCardWidget(unittest.TestCase):
    """Test cases for MetricCardWidget."""
    
    def test_widget_initialization_basic(self):
        """Test basic widget initialization."""
        widget = MetricCardWidget("Test Metric", 100)
        
        self.assertEqual(widget.title, "Test Metric")
        self.assertEqual(widget.value, 100)
        self.assertIsNone(widget.trend)
        self.assertEqual(widget.subtitle, "")
        self.assertEqual(widget.icon, "fa-chart-bar")
        self.assertEqual(widget.color, "primary")
    
    def test_widget_initialization_full(self):
        """Test widget initialization with all parameters."""
        widget = MetricCardWidget(
            title="Advanced Metric",
            value=2500,
            trend=15.3,
            subtitle="vs last month",
            icon="fa-users",
            color="success"
        )
        
        self.assertEqual(widget.title, "Advanced Metric")
        self.assertEqual(widget.value, 2500)
        self.assertEqual(widget.trend, 15.3)
        self.assertEqual(widget.subtitle, "vs last month")
        self.assertEqual(widget.icon, "fa-users")
        self.assertEqual(widget.color, "success")
    
    def test_format_value_integers(self):
        """Test value formatting for integers."""
        widget = MetricCardWidget("Test", 0)
        
        # Test regular numbers
        self.assertEqual(widget._format_value(42), "42")
        self.assertEqual(widget._format_value(999), "999")
        
        # Test thousands
        self.assertEqual(widget._format_value(1000), "1.0K")
        self.assertEqual(widget._format_value(1500), "1.5K")
        self.assertEqual(widget._format_value(999999), "999.9K")
        
        # Test millions
        self.assertEqual(widget._format_value(1000000), "1.0M")
        self.assertEqual(widget._format_value(2500000), "2.5M")
    
    def test_format_value_floats(self):
        """Test value formatting for floats."""
        widget = MetricCardWidget("Test", 0)
        
        # Test decimal numbers
        self.assertEqual(widget._format_value(42.7), "42.7")
        self.assertEqual(widget._format_value(1234.5), "1.2K")
        self.assertEqual(widget._format_value(1500000.0), "1.5M")
    
    def test_format_value_strings(self):
        """Test value formatting for strings."""
        widget = MetricCardWidget("Test", 0)
        
        self.assertEqual(widget._format_value("Custom"), "Custom")
        self.assertEqual(widget._format_value("N/A"), "N/A")
        self.assertEqual(widget._format_value(""), "")
    
    def test_get_trend_class_positive(self):
        """Test trend class for positive trends."""
        widget = MetricCardWidget("Test", 100, trend=15.5)
        
        trend_class = widget._get_trend_class()
        self.assertEqual(trend_class, "trend-up text-success")
    
    def test_get_trend_class_negative(self):
        """Test trend class for negative trends."""
        widget = MetricCardWidget("Test", 100, trend=-8.2)
        
        trend_class = widget._get_trend_class()
        self.assertEqual(trend_class, "trend-down text-danger")
    
    def test_get_trend_class_zero(self):
        """Test trend class for zero trend."""
        widget = MetricCardWidget("Test", 100, trend=0.0)
        
        trend_class = widget._get_trend_class()
        self.assertEqual(trend_class, "trend-neutral text-muted")
    
    def test_get_trend_class_none(self):
        """Test trend class for no trend."""
        widget = MetricCardWidget("Test", 100, trend=None)
        
        trend_class = widget._get_trend_class()
        self.assertEqual(trend_class, "")
    
    def test_get_trend_icon_positive(self):
        """Test trend icon for positive trends."""
        widget = MetricCardWidget("Test", 100, trend=12.5)
        
        trend_icon = widget._get_trend_icon()
        self.assertEqual(trend_icon, "fa-arrow-up")
    
    def test_get_trend_icon_negative(self):
        """Test trend icon for negative trends."""
        widget = MetricCardWidget("Test", 100, trend=-5.0)
        
        trend_icon = widget._get_trend_icon()
        self.assertEqual(trend_icon, "fa-arrow-down")
    
    def test_get_trend_icon_zero(self):
        """Test trend icon for zero trend."""
        widget = MetricCardWidget("Test", 100, trend=0.0)
        
        trend_icon = widget._get_trend_icon()
        self.assertEqual(trend_icon, "fa-minus")
    
    def test_get_trend_text(self):
        """Test trend text generation."""
        widget_up = MetricCardWidget("Test", 100, trend=15.3)
        widget_down = MetricCardWidget("Test", 100, trend=-8.7)
        widget_none = MetricCardWidget("Test", 100, trend=None)
        
        self.assertEqual(widget_up._get_trend_text(), "15.3% increase")
        self.assertEqual(widget_down._get_trend_text(), "8.7% decrease")
        self.assertEqual(widget_none._get_trend_text(), "")
    
    def test_render_metric_card_basic(self):
        """Test basic metric card rendering."""
        widget = MetricCardWidget("Test Metric", 150)
        
        html = widget.render_metric_card()
        
        # Check that HTML contains key elements
        self.assertIn("Test Metric", html)
        self.assertIn("150", html)
        self.assertIn("metric-card", html)
        self.assertIn("fa-chart-bar", html)
        self.assertIn("text-primary", html)
    
    def test_render_metric_card_with_trend(self):
        """Test metric card rendering with trend."""
        widget = MetricCardWidget(
            "Sales Revenue", 
            50000, 
            trend=12.5, 
            subtitle="vs last quarter",
            icon="fa-dollar-sign",
            color="success"
        )
        
        html = widget.render_metric_card()
        
        # Check content
        self.assertIn("Sales Revenue", html)
        self.assertIn("50.0K", html)  # Formatted value
        self.assertIn("vs last quarter", html)
        self.assertIn("fa-dollar-sign", html)
        self.assertIn("text-success", html)
        
        # Check trend elements
        self.assertIn("12.5% increase", html)
        self.assertIn("fa-arrow-up", html)
        self.assertIn("trend-up", html)
    
    @patch('pgappforge.charts.metric_widgets.render_template_string')
    def test_render_metric_card_template_error(self, mock_render):
        """Test metric card rendering with template error."""
        mock_render.side_effect = Exception("Template error")
        
        widget = MetricCardWidget("Test", 100)
        html = widget.render_metric_card()
        
        # Should return error message
        self.assertIn("Error rendering metric: Test", html)
        self.assertIn("alert-warning", html)


class TestTrendChartView(unittest.TestCase):
    """Test cases for TrendChartView."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.chart_view = TrendChartView()
        
        # Mock datamodel
        self.mock_datamodel = Mock()
        self.chart_view.datamodel = self.mock_datamodel
    
    def test_chart_view_initialization(self):
        """Test chart view initialization."""
        self.assertEqual(self.chart_view.chart_type, "LineChart")
        self.assertEqual(self.chart_view.chart_title, "Trend Analysis")
        self.assertEqual(self.chart_view.chart_3d, "false")
        self.assertEqual(self.chart_view.height, "300px")
        
        # Check time ranges
        self.assertIn('7d', self.chart_view.time_ranges)
        self.assertIn('30d', self.chart_view.time_ranges)
        self.assertEqual(self.chart_view.time_ranges['7d']['days'], 7)
        self.assertEqual(self.chart_view.time_ranges['30d']['label'], 'Last 30 Days')
    
    def test_format_date_for_chart_datetime(self):
        """Test date formatting with datetime objects."""
        test_date = datetime(2023, 9, 15, 14, 30)
        
        formatted = self.chart_view._format_date_for_chart(test_date)
        self.assertEqual(formatted, "2023-09-15")
    
    def test_format_date_for_chart_string(self):
        """Test date formatting with string dates."""
        test_date = "2023-09-15"
        
        formatted = self.chart_view._format_date_for_chart(test_date)
        self.assertEqual(formatted, "2023-09-15")
    
    def test_format_date_for_chart_invalid_string(self):
        """Test date formatting with invalid string."""
        test_date = "invalid-date"
        
        formatted = self.chart_view._format_date_for_chart(test_date)
        self.assertEqual(formatted, "invalid-date")  # Should return as-is
    
    def test_format_date_for_chart_none(self):
        """Test date formatting with None value."""
        formatted = self.chart_view._format_date_for_chart(None)
        
        # Should return current date
        self.assertTrue(formatted.startswith(datetime.now().strftime('%Y')))
    
    def test_calculate_trend_percentage_increasing(self):
        """Test trend percentage calculation for increasing trend."""
        data = [
            {'value': 100},
            {'value': 110},
            {'value': 115}
        ]
        
        trend = self.chart_view.calculate_trend_percentage(data)
        self.assertEqual(trend, 15.0)  # (115 - 100) / 100 * 100 = 15%
    
    def test_calculate_trend_percentage_decreasing(self):
        """Test trend percentage calculation for decreasing trend."""
        data = [
            {'value': 200},
            {'value': 180},
            {'value': 160}
        ]
        
        trend = self.chart_view.calculate_trend_percentage(data)
        self.assertEqual(trend, -20.0)  # (160 - 200) / 200 * 100 = -20%
    
    def test_calculate_trend_percentage_no_change(self):
        """Test trend percentage calculation for no change."""
        data = [
            {'value': 150},
            {'value': 150}
        ]
        
        trend = self.chart_view.calculate_trend_percentage(data)
        self.assertEqual(trend, 0.0)
    
    def test_calculate_trend_percentage_insufficient_data(self):
        """Test trend percentage calculation with insufficient data."""
        # Empty data
        trend = self.chart_view.calculate_trend_percentage([])
        self.assertIsNone(trend)
        
        # Single data point
        trend = self.chart_view.calculate_trend_percentage([{'value': 100}])
        self.assertIsNone(trend)
    
    def test_calculate_trend_percentage_zero_start(self):
        """Test trend percentage calculation starting from zero."""
        data = [
            {'value': 0},
            {'value': 50}
        ]
        
        trend = self.chart_view.calculate_trend_percentage(data)
        self.assertEqual(trend, 100.0)  # Special case: 0 to positive = 100%
    
    def test_calculate_trend_percentage_error_handling(self):
        """Test trend percentage calculation with invalid data."""
        # Missing value key
        data = [
            {'invalid': 100},
            {'invalid': 110}
        ]
        
        trend = self.chart_view.calculate_trend_percentage(data)
        self.assertIsNone(trend)
    
    @patch('pgappforge.charts.metric_widgets.GroupByProcessData')
    def test_get_trend_data_success(self, mock_group_by_class):
        """Test successful trend data retrieval."""
        # Mock GroupByProcessData behavior
        mock_group_by = Mock()
        mock_group_by_class.return_value = mock_group_by
        
        # Mock returned data
        mock_raw_data = [
            {'created_on': '2023-09-01', 'count': 10},
            {'created_on': '2023-09-02', 'count': 15}
        ]
        mock_group_by.apply_filter_and_group.return_value = mock_raw_data
        
        # Get trend data
        result = self.chart_view.get_trend_data('created_on', 'count', '7d')
        
        # Verify GroupByProcessData was called correctly
        mock_group_by_class.assert_called_once_with(
            self.mock_datamodel,
            ['created_on'],
            'count'
        )
        
        # Verify filters were applied
        mock_group_by._apply_filters.assert_called_once()
        
        # Verify data was processed
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
    
    @patch('pgappforge.charts.metric_widgets.GroupByProcessData')
    def test_get_trend_data_error(self, mock_group_by_class):
        """Test trend data retrieval with error."""
        mock_group_by_class.side_effect = Exception("Database error")
        
        result = self.chart_view.get_trend_data('created_on', 'count', '30d')
        
        # Should return empty list on error
        self.assertEqual(result, [])
    
    def test_format_trend_data_dict_format(self):
        """Test trend data formatting with dict format."""
        raw_data = [
            {'date_field': '2023-09-01', 'value_field': 10},
            {'date_field': '2023-09-02', 'value_field': 15}
        ]
        
        formatted = self.chart_view._format_trend_data(raw_data, 'date_field', 'value_field')
        
        self.assertEqual(len(formatted), 2)
        self.assertEqual(formatted[0]['date'], '2023-09-01')
        self.assertEqual(formatted[0]['value'], 10.0)
        self.assertEqual(formatted[0]['label'], '2023-09-01')
    
    def test_format_trend_data_object_format(self):
        """Test trend data formatting with object format."""
        # Mock objects
        obj1 = Mock()
        obj1.date_field = datetime(2023, 9, 1)
        obj1.value_field = 20
        
        obj2 = Mock()
        obj2.date_field = datetime(2023, 9, 2)
        obj2.value_field = 25
        
        raw_data = [obj1, obj2]
        
        formatted = self.chart_view._format_trend_data(raw_data, 'date_field', 'value_field')
        
        self.assertEqual(len(formatted), 2)
        self.assertEqual(formatted[0]['date'], '2023-09-01')
        self.assertEqual(formatted[0]['value'], 20.0)
    
    def test_format_trend_data_error_handling(self):
        """Test trend data formatting with invalid data."""
        raw_data = [
            {'invalid': 'data'},
            None,
            {'date_field': '2023-09-01', 'value_field': 'invalid'}
        ]
        
        formatted = self.chart_view._format_trend_data(raw_data, 'date_field', 'value_field')
        
        # Should handle errors gracefully - some items may be skipped
        self.assertIsInstance(formatted, list)
    
    @patch('pgappforge.charts.metric_widgets.TrendChartView.get_trend_data')
    def test_get_metric_summary_success(self, mock_get_trend_data):
        """Test successful metric summary generation."""
        # Mock trend data
        mock_trend_data = [
            {'value': 100, 'date': '2023-09-01'},
            {'value': 110, 'date': '2023-09-02'},
            {'value': 115, 'date': '2023-09-03'}
        ]
        mock_get_trend_data.return_value = mock_trend_data
        
        summary = self.chart_view.get_metric_summary('created_on', 'count', '7d')
        
        # Check summary structure
        self.assertIn('current_value', summary)
        self.assertIn('trend_percentage', summary)
        self.assertIn('chart_data', summary)
        self.assertIn('time_range_label', summary)
        self.assertIn('data_points', summary)
        
        # Check values
        self.assertEqual(summary['current_value'], 115)
        self.assertEqual(summary['trend_percentage'], 15.0)
        self.assertEqual(summary['chart_data'], mock_trend_data)
        self.assertEqual(summary['time_range_label'], 'Last 7 Days')
        self.assertEqual(summary['data_points'], 3)
    
    @patch('pgappforge.charts.metric_widgets.TrendChartView.get_trend_data')
    def test_get_metric_summary_no_data(self, mock_get_trend_data):
        """Test metric summary with no data."""
        mock_get_trend_data.return_value = []
        
        summary = self.chart_view.get_metric_summary('created_on', 'count', '30d')
        
        # Check default values
        self.assertEqual(summary['current_value'], 0)
        self.assertIsNone(summary['trend_percentage'])
        self.assertEqual(summary['chart_data'], [])
        self.assertEqual(summary['time_range_label'], 'Last 30 Days')
    
    @patch('pgappforge.charts.metric_widgets.TrendChartView.get_trend_data')
    def test_get_metric_summary_error(self, mock_get_trend_data):
        """Test metric summary with error."""
        mock_get_trend_data.side_effect = Exception("Data error")
        
        summary = self.chart_view.get_metric_summary('created_on', 'count', '90d')
        
        # Check error handling
        self.assertEqual(summary['current_value'], 0)
        self.assertIsNone(summary['trend_percentage'])
        self.assertEqual(summary['chart_data'], [])
        self.assertEqual(summary['time_range_label'], 'Error')
        self.assertIn('error', summary)


class TestEnhancedDashboardView(unittest.TestCase):
    """Test cases for EnhancedDashboardView."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.dashboard_view = EnhancedDashboardView()
        self.mock_user = MockUser()
    
    def test_dashboard_view_initialization(self):
        """Test dashboard view initialization."""
        self.assertEqual(self.dashboard_view.route_base, '/enhanced-dashboard')
        self.assertEqual(self.dashboard_view.default_view, 'index')
        
        # Check default metrics
        self.assertIsInstance(self.dashboard_view.default_metrics, list)
        self.assertTrue(len(self.dashboard_view.default_metrics) > 0)
        
        # Check first metric structure
        first_metric = self.dashboard_view.default_metrics[0]
        self.assertIn('title', first_metric)
        self.assertIn('field', first_metric)
        self.assertIn('aggregation', first_metric)
        self.assertIn('icon', first_metric)
        self.assertIn('color', first_metric)
    
    def test_calculate_metric_value(self):
        """Test metric value calculation."""
        # Test different metric types
        total_records_config = {'title': 'Total Records'}
        active_processes_config = {'title': 'Active Processes'}
        pending_approval_config = {'title': 'Pending Approval'}
        completed_today_config = {'title': 'Completed Today'}
        unknown_config = {'title': 'Unknown Metric'}
        
        self.assertEqual(self.dashboard_view._calculate_metric_value(total_records_config), 1250)
        self.assertEqual(self.dashboard_view._calculate_metric_value(active_processes_config), 45)
        self.assertEqual(self.dashboard_view._calculate_metric_value(pending_approval_config), 12)
        self.assertEqual(self.dashboard_view._calculate_metric_value(completed_today_config), 8)
        self.assertEqual(self.dashboard_view._calculate_metric_value(unknown_config), 0)
    
    def test_calculate_metric_trend(self):
        """Test metric trend calculation."""
        total_records_config = {'title': 'Total Records'}
        active_processes_config = {'title': 'Active Processes'}
        pending_approval_config = {'title': 'Pending Approval'}
        completed_today_config = {'title': 'Completed Today'}
        
        self.assertEqual(self.dashboard_view._calculate_metric_trend(total_records_config, '30d'), 15.2)
        self.assertEqual(self.dashboard_view._calculate_metric_trend(active_processes_config, '30d'), -5.1)
        self.assertEqual(self.dashboard_view._calculate_metric_trend(pending_approval_config, '30d'), 8.7)
        self.assertEqual(self.dashboard_view._calculate_metric_trend(completed_today_config, '30d'), 22.3)
    
    def test_get_metric_subtitle(self):
        """Test metric subtitle generation."""
        config = {'title': 'Test Metric'}
        
        self.assertEqual(self.dashboard_view._get_metric_subtitle(config, '7d'), 'vs last week')
        self.assertEqual(self.dashboard_view._get_metric_subtitle(config, '30d'), 'vs last month')
        self.assertEqual(self.dashboard_view._get_metric_subtitle(config, '90d'), 'vs last quarter')
        self.assertEqual(self.dashboard_view._get_metric_subtitle(config, '1y'), 'vs last year')
        self.assertEqual(self.dashboard_view._get_metric_subtitle(config, 'custom'), 'vs previous custom')
    
    def test_get_time_range_label(self):
        """Test time range label generation."""
        self.assertEqual(self.dashboard_view._get_time_range_label('7d'), 'Last 7 Days')
        self.assertEqual(self.dashboard_view._get_time_range_label('30d'), 'Last 30 Days')
        self.assertEqual(self.dashboard_view._get_time_range_label('90d'), 'Last 90 Days')
        self.assertEqual(self.dashboard_view._get_time_range_label('1y'), 'Last Year')
        self.assertEqual(self.dashboard_view._get_time_range_label('custom'), 'custom')
    
    def test_get_time_range_options(self):
        """Test time range options generation."""
        options = self.dashboard_view._get_time_range_options()
        
        self.assertIsInstance(options, list)
        self.assertTrue(len(options) > 0)
        
        # Check option structure
        first_option = options[0]
        self.assertIn('value', first_option)
        self.assertIn('label', first_option)
    
    def test_get_total_users(self):
        """Test total users calculation."""
        total_users = self.dashboard_view._get_total_users()
        
        # Should return mock value
        self.assertEqual(total_users, 156)
    
    def test_get_dashboard_data(self):
        """Test dashboard data generation."""
        data = self.dashboard_view._get_dashboard_data('30d')
        
        # Check structure
        self.assertIn('last_updated', data)
        self.assertIn('total_users', data)
        self.assertIn('system_status', data)
        self.assertIn('time_range_label', data)
        self.assertIn('refresh_interval', data)
        
        # Check values
        self.assertIsInstance(data['last_updated'], datetime)
        self.assertEqual(data['total_users'], 156)
        self.assertEqual(data['system_status'], 'operational')
        self.assertEqual(data['time_range_label'], 'Last 30 Days')
        self.assertEqual(data['refresh_interval'], 300)
    
    def test_generate_metric_cards(self):
        """Test metric cards generation."""
        cards = self.dashboard_view._generate_metric_cards('30d')
        
        self.assertIsInstance(cards, list)
        self.assertEqual(len(cards), len(self.dashboard_view.default_metrics))
        
        # Check first card
        first_card = cards[0]
        self.assertIsInstance(first_card, MetricCardWidget)
        self.assertEqual(first_card.title, "Total Records")
        self.assertEqual(first_card.value, 1250)
        self.assertEqual(first_card.trend, 15.2)
    
    def test_generate_metric_cards_error_handling(self):
        """Test metric cards generation with error."""
        # Temporarily break the calculation method
        original_method = self.dashboard_view._calculate_metric_value
        self.dashboard_view._calculate_metric_value = Mock(side_effect=Exception("Test error"))
        
        cards = self.dashboard_view._generate_metric_cards('30d')
        
        # Should contain error card
        self.assertEqual(len(cards), 1)
        error_card = cards[0]
        self.assertEqual(error_card.title, "Error Loading Metrics")
        self.assertEqual(error_card.value, "--")
        self.assertEqual(error_card.color, "danger")
        
        # Restore original method
        self.dashboard_view._calculate_metric_value = original_method
    
    def test_get_models_with_state_tracking(self):
        """Test getting models with state tracking."""
        models = self.dashboard_view._get_models_with_state_tracking()
        
        # Should return empty list in test environment
        self.assertIsInstance(models, list)
        self.assertEqual(len(models), 0)


class TestMetricsDashboardView(unittest.TestCase):
    """Test cases for MetricsDashboardView."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.dashboard_view = MetricsDashboardView()
    
    def test_dashboard_view_initialization(self):
        """Test dashboard view initialization."""
        self.assertEqual(self.dashboard_view.route_base, '/metrics-dashboard')


class TestIntegration(unittest.TestCase):
    """Test integration between MetricCardWidget and dashboard views."""
    
    def test_metric_card_in_dashboard(self):
        """Test metric card integration with dashboard."""
        # Create enhanced dashboard
        dashboard = EnhancedDashboardView()
        
        # Generate metric cards
        cards = dashboard._generate_metric_cards('7d')
        
        # Verify all cards are MetricCardWidget instances
        for card in cards:
            self.assertIsInstance(card, MetricCardWidget)
            
            # Verify each card can render
            html = card.render_metric_card()
            self.assertIsInstance(html, str)
            self.assertIn('metric-card', html)
    
    def test_trend_chart_integration(self):
        """Test trend chart integration with metric widgets."""
        # Create trend chart view
        trend_view = TrendChartView()
        
        # Test metric summary generation
        summary = trend_view.get_metric_summary('created_on', 'count', '30d')
        
        # Should be able to create metric card from summary
        if summary['current_value'] is not None:
            card = MetricCardWidget(
                title="Trend Metric",
                value=summary['current_value'],
                trend=summary['trend_percentage'],
                subtitle=summary['time_range_label']
            )
            
            html = card.render_metric_card()
            self.assertIsInstance(html, str)
            self.assertIn('Trend Metric', html)


if __name__ == '__main__':
    unittest.main()