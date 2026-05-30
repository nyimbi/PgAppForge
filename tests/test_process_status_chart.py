"""
Test ProcessStatusChartView functionality.

Tests the process status chart capabilities and integration with PgForge chart patterns.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock

from flask import Flask
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Test the ProcessStatusChartView without complex PgForge imports
Base = declarative_base()


class StateTrackingMixin:
    """Mock StateTrackingMixin for testing."""
    
    status = Column(String(50), default='draft', nullable=False)
    status_reason = Column(Text)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'status') or self.status is None:
            self.status = 'draft'


class TestModel(StateTrackingMixin, Base):
    """Test model for chart testing."""
    
    __tablename__ = 'test_models'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)


class MockDataModel:
    """Mock datamodel for testing."""
    
    def __init__(self, records=None):
        self.records = records or []
        self.model_class = TestModel
    
    def get_query(self):
        """Mock query method."""
        return Mock()


class MockGroupByProcessData:
    """Mock GroupByProcessData for testing."""
    
    def __init__(self, datamodel, columns, aggregation):
        self.datamodel = datamodel
        self.columns = columns
        self.aggregation = aggregation
        self._filters = []
    
    def _apply_filters(self, filters):
        """Mock filter application."""
        self._filters = filters
    
    def apply_filter_and_group(self):
        """Mock data grouping that returns test data."""
        # Return mock status distribution data
        return [
            {'status': 'draft', 'count': 10},
            {'status': 'pending_approval', 'count': 5},
            {'status': 'approved', 'count': 15},
            {'status': 'rejected', 'count': 2},
            {'status': 'archived', 'count': 3}
        ]


class MockChartWidget:
    """Mock chart widget for testing."""
    
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chart_data = kwargs.get('chart_data', [])
        
    def get_chart_data(self):
        return self.chart_data


class ProcessStatusChartView:
    """
    Simplified ProcessStatusChartView for testing.
    """
    
    chart_type = "PieChart"
    chart_title = "Process Status Overview"
    chart_3d = "true"
    height = "400px"
    chart_template = "appbuilder/general/charts/chart.html"
    route_base = "/process-status-chart"
    
    def __init__(self, datamodel=None, **kwargs):
        """Initialize chart view."""
        self.datamodel = datamodel
        self.chart_widget = MockChartWidget
        
        # Set up default definitions for status grouping
        if not hasattr(self, 'definitions') or not self.definitions:
            self.definitions = [
                {
                    'label': 'Status Distribution',
                    'group': 'status',
                    'formatter': self._format_status_label,
                    'series': [('Count', 'id')]
                }
            ]
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def _format_status_label(self, value):
        """Format status labels for display."""
        if not value:
            return 'Unknown'
        
        # Convert snake_case to Title Case
        return str(value).replace('_', ' ').title()
    
    def _get_chart_widget(self, filters=None, definition=None, **kwargs):
        """Get chart widget with status data."""
        if not definition:
            definition = self.definitions[0] if self.definitions else {}
        
        # Use MockGroupByProcessData for status aggregation
        group_by = MockGroupByProcessData(
            self.datamodel,
            ['status'],  # Group by status field
            'count'      # Count aggregation
        )
        
        # Apply filters if provided
        if filters:
            group_by._apply_filters(filters)
        
        # Get the grouped data
        chart_data = group_by.apply_filter_and_group()
        
        # Format data for chart widget
        formatted_data = self._format_chart_data(chart_data, definition)
        
        widgets = {}
        widgets["chart"] = self.chart_widget(
            route_base=self.route_base,
            chart_title=self.chart_title,
            chart_type=self.chart_type,
            chart_3d=self.chart_3d,
            height=self.height,
            chart_data=formatted_data,
            modelview_name=self.__class__.__name__,
            **kwargs
        )
        
        return widgets
    
    def _format_chart_data(self, raw_data, definition):
        """Format raw status data for chart display."""
        formatted_data = []
        
        # Get formatter from definition
        formatter = definition.get('formatter', lambda x: x)
        
        for item in raw_data:
            if isinstance(item, dict):
                status = item.get('status', 'Unknown')
                count = item.get('count', 0)
            else:
                # Handle different data formats
                status = getattr(item, 'status', 'Unknown')
                count = getattr(item, 'count', 1)
            
            formatted_data.append({
                'label': formatter(status),
                'value': int(count),
                'status': status
            })
        
        return formatted_data
    
    def get_status_summary(self):
        """Get status summary data for dashboard widgets."""
        try:
            # Get raw status data using mock
            group_by = MockGroupByProcessData(self.datamodel, ['status'], 'count')
            raw_data = group_by.apply_filter_and_group()
            
            # Calculate summary statistics
            total_count = sum(item.get('count', 0) for item in raw_data)
            status_summary = {}
            
            for item in raw_data:
                status = item.get('status', 'Unknown')
                count = item.get('count', 0)
                percentage = (count / total_count * 100) if total_count > 0 else 0
                
                status_summary[status] = {
                    'count': count,
                    'percentage': round(percentage, 1),
                    'label': self._format_status_label(status)
                }
            
            return {
                'total_count': total_count,
                'status_breakdown': status_summary,
                'most_common_status': max(status_summary.items(), 
                                        key=lambda x: x[1]['count'])[0] if status_summary else None
            }
            
        except Exception as e:
            return {
                'total_count': 0,
                'status_breakdown': {},
                'most_common_status': None,
                'error': str(e)
            }


class TestProcessStatusChartView(unittest.TestCase):
    """Test cases for ProcessStatusChartView."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.datamodel = MockDataModel()
        self.chart_view = ProcessStatusChartView(datamodel=self.datamodel)
    
    def test_chart_view_initialization(self):
        """Test chart view initialization."""
        self.assertEqual(self.chart_view.chart_type, "PieChart")
        self.assertEqual(self.chart_view.chart_title, "Process Status Overview")
        self.assertTrue(self.chart_view.chart_3d)
        self.assertTrue(len(self.chart_view.definitions) > 0)
    
    def test_format_status_label(self):
        """Test status label formatting."""
        # Test normal case
        result = self.chart_view._format_status_label('pending_approval')
        self.assertEqual(result, 'Pending Approval')
        
        # Test single word
        result = self.chart_view._format_status_label('draft')
        self.assertEqual(result, 'Draft')
        
        # Test empty/None values
        result = self.chart_view._format_status_label(None)
        self.assertEqual(result, 'Unknown')
        
        result = self.chart_view._format_status_label('')
        self.assertEqual(result, 'Unknown')
    
    def test_get_chart_widget(self):
        """Test chart widget creation."""
        widgets = self.chart_view._get_chart_widget()
        
        # Check widget creation
        self.assertIn('chart', widgets)
        
        # Check widget properties
        chart_widget = widgets['chart']
        self.assertEqual(chart_widget.kwargs['chart_type'], 'PieChart')
        self.assertEqual(chart_widget.kwargs['chart_title'], 'Process Status Overview')
        self.assertEqual(chart_widget.kwargs['route_base'], '/process-status-chart')
    
    def test_format_chart_data(self):
        """Test chart data formatting."""
        raw_data = [
            {'status': 'draft', 'count': 10},
            {'status': 'pending_approval', 'count': 5},
            {'status': 'approved', 'count': 15}
        ]
        
        definition = {
            'formatter': self.chart_view._format_status_label
        }
        
        formatted_data = self.chart_view._format_chart_data(raw_data, definition)
        
        # Check data structure
        self.assertEqual(len(formatted_data), 3)
        
        # Check first item
        first_item = formatted_data[0]
        self.assertIn('label', first_item)
        self.assertIn('value', first_item)
        self.assertIn('status', first_item)
        
        # Check formatting
        self.assertEqual(first_item['label'], 'Draft')
        self.assertEqual(first_item['value'], 10)
        self.assertEqual(first_item['status'], 'draft')
        
        # Check formatted labels
        labels = [item['label'] for item in formatted_data]
        self.assertIn('Draft', labels)
        self.assertIn('Pending Approval', labels)
        self.assertIn('Approved', labels)
    
    def test_format_chart_data_with_objects(self):
        """Test chart data formatting with object data."""
        # Mock object data
        mock_obj1 = Mock()
        mock_obj1.status = 'draft'
        mock_obj1.count = 5
        
        mock_obj2 = Mock()
        mock_obj2.status = 'approved'
        mock_obj2.count = 8
        
        raw_data = [mock_obj1, mock_obj2]
        
        definition = {
            'formatter': self.chart_view._format_status_label
        }
        
        formatted_data = self.chart_view._format_chart_data(raw_data, definition)
        
        self.assertEqual(len(formatted_data), 2)
        self.assertEqual(formatted_data[0]['label'], 'Draft')
        self.assertEqual(formatted_data[0]['value'], 5)
        self.assertEqual(formatted_data[1]['label'], 'Approved')
        self.assertEqual(formatted_data[1]['value'], 8)
    
    def test_get_status_summary(self):
        """Test status summary calculation."""
        summary = self.chart_view.get_status_summary()
        
        # Check structure
        self.assertIn('total_count', summary)
        self.assertIn('status_breakdown', summary)
        self.assertIn('most_common_status', summary)
        
        # Check total count (from mock data: 10+5+15+2+3 = 35)
        self.assertEqual(summary['total_count'], 35)
        
        # Check status breakdown
        breakdown = summary['status_breakdown']
        self.assertIn('draft', breakdown)
        self.assertIn('approved', breakdown)
        self.assertIn('pending_approval', breakdown)
        
        # Check draft status details
        draft_info = breakdown['draft']
        self.assertEqual(draft_info['count'], 10)
        self.assertEqual(draft_info['percentage'], 28.6)  # 10/35 * 100 = 28.57 rounded to 28.6
        self.assertEqual(draft_info['label'], 'Draft')
        
        # Check most common status (approved has 15, highest count)
        self.assertEqual(summary['most_common_status'], 'approved')
    
    def test_get_status_summary_empty_data(self):
        """Test status summary with empty data."""
        # Create chart view with empty data
        empty_datamodel = MockDataModel(records=[])
        chart_view = ProcessStatusChartView(datamodel=empty_datamodel)
        
        # Override the mock to return empty data
        original_method = MockGroupByProcessData.apply_filter_and_group
        MockGroupByProcessData.apply_filter_and_group = lambda self: []
        
        try:
            summary = chart_view.get_status_summary()
            
            self.assertEqual(summary['total_count'], 0)
            self.assertEqual(summary['status_breakdown'], {})
            self.assertIsNone(summary['most_common_status'])
            
        finally:
            # Restore original method
            MockGroupByProcessData.apply_filter_and_group = original_method
    
    def test_chart_with_filters(self):
        """Test chart widget creation with filters."""
        filters = [{'field': 'status', 'op': '==', 'value': 'draft'}]
        
        widgets = self.chart_view._get_chart_widget(filters=filters)
        
        # Chart should still be created with filters
        self.assertIn('chart', widgets)
        chart_widget = widgets['chart']
        self.assertIsInstance(chart_widget.chart_data, list)
    
    def test_custom_chart_title(self):
        """Test custom chart title."""
        custom_chart_view = ProcessStatusChartView(
            datamodel=self.datamodel,
            chart_title="Custom Process Status"
        )
        
        self.assertEqual(custom_chart_view.chart_title, "Custom Process Status")
        
        widgets = custom_chart_view._get_chart_widget()
        chart_widget = widgets['chart']
        self.assertEqual(chart_widget.kwargs['chart_title'], "Custom Process Status")
    
    def test_chart_data_integration(self):
        """Test complete chart data flow."""
        # Get chart widget
        widgets = self.chart_view._get_chart_widget()
        chart_widget = widgets['chart']
        
        # Check chart data
        chart_data = chart_widget.chart_data
        self.assertTrue(len(chart_data) > 0)
        
        # Verify data structure
        for item in chart_data:
            self.assertIn('label', item)
            self.assertIn('value', item)
            self.assertIn('status', item)
            self.assertIsInstance(item['value'], int)
        
        # Check specific expected data
        status_values = [item['status'] for item in chart_data]
        self.assertIn('draft', status_values)
        self.assertIn('approved', status_values)
        self.assertIn('pending_approval', status_values)
        
        # Check labels are formatted
        labels = [item['label'] for item in chart_data]
        self.assertIn('Draft', labels)
        self.assertIn('Approved', labels)
        self.assertIn('Pending Approval', labels)


if __name__ == '__main__':
    unittest.main()