"""
Isolated test for MetricCardWidget functionality.

Tests the MetricCardWidget without complex PgAppForge imports that cause issues.
"""

import unittest
from unittest.mock import Mock, patch
from datetime import datetime

# Import the classes we're testing directly
from pgappforge.charts.metric_widgets import MetricCardWidget, TrendChartView


class TestMetricCardWidgetIsolated(unittest.TestCase):
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


class TestTrendChartViewIsolated(unittest.TestCase):
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


class TestWidgetIntegration(unittest.TestCase):
    """Test integration between widget components."""
    
    def test_metric_card_complete_workflow(self):
        """Test complete metric card workflow."""
        # Create metric card with all features
        card = MetricCardWidget(
            title="Complete Test Metric",
            value=12345,
            trend=25.7,
            subtitle="vs previous period",
            icon="fa-chart-line",
            color="info"
        )
        
        # Test all methods work together
        self.assertEqual(card._format_value(card.value), "12.3K")
        self.assertEqual(card._get_trend_class(), "trend-up text-success")
        self.assertEqual(card._get_trend_icon(), "fa-arrow-up")
        self.assertEqual(card._get_trend_text(), "25.7% increase")
        
        # Test rendering
        html = card.render_metric_card()
        
        # Verify all elements are present
        self.assertIn("Complete Test Metric", html)
        self.assertIn("12.3K", html)
        self.assertIn("25.7% increase", html)
        self.assertIn("vs previous period", html)
        self.assertIn("fa-chart-line", html)
        self.assertIn("text-info", html)
        self.assertIn("trend-up", html)
        self.assertIn("fa-arrow-up", html)
    
    def test_trend_chart_complete_workflow(self):
        """Test complete trend chart workflow."""
        chart_view = TrendChartView()
        
        # Test time range functionality
        self.assertIn('30d', chart_view.time_ranges)
        self.assertEqual(chart_view.time_ranges['30d']['days'], 30)
        
        # Test data processing
        mock_data = [
            {'value': 100, 'date': '2023-09-01'},
            {'value': 110, 'date': '2023-09-02'},
            {'value': 120, 'date': '2023-09-03'}
        ]
        
        trend = chart_view.calculate_trend_percentage(mock_data)
        self.assertEqual(trend, 20.0)  # 20% increase
        
        # Test date formatting
        test_date = datetime(2023, 9, 15)
        formatted = chart_view._format_date_for_chart(test_date)
        self.assertEqual(formatted, "2023-09-15")


if __name__ == '__main__':
    unittest.main()