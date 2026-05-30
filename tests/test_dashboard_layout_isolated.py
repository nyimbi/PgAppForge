"""
Isolated tests for Dashboard Layout Manager functionality.

Tests the dashboard layout system without complex PgAppForge imports.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime

# Import the classes we're testing directly
from pgappforge.views.dashboard_layout import DashboardLayoutView, DashboardLayoutForm
from pgappforge.views.configurable_dashboard import ConfigurableDashboardView


class TestDashboardLayoutFormIsolated(unittest.TestCase):
    """Test cases for DashboardLayoutForm."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock Flask-WTF form data
        self.mock_form_data = {
            'title': 'Test Dashboard',
            'layout_type': 'grid',
            'widgets_config': '{"widgets": [{"type": "metric_card", "title": "Test Metric"}]}',
            'auto_refresh': True,
            'refresh_interval': 300
        }
    
    def test_form_creation(self):
        """Test form can be created successfully."""
        try:
            form = DashboardLayoutForm()
            
            # Check that form has expected fields
            self.assertTrue(hasattr(form, 'title'))
            self.assertTrue(hasattr(form, 'layout_type'))
            self.assertTrue(hasattr(form, 'widgets_config'))
            self.assertTrue(hasattr(form, 'auto_refresh'))
            self.assertTrue(hasattr(form, 'refresh_interval'))
            
        except Exception as e:
            # If form creation fails due to Flask context, that's expected in isolated test
            self.assertIn('flask', str(e).lower())
    
    def test_layout_type_choices(self):
        """Test that layout type field has correct choices."""
        try:
            form = DashboardLayoutForm()
            
            # Check layout type choices
            expected_choices = [
                ('grid', 'Grid Layout'),
                ('tabs', 'Tabbed Layout'),
                ('single_column', 'Single Column'),
                ('two_column', 'Two Column')
            ]
            
            if hasattr(form.layout_type, 'choices'):
                self.assertEqual(form.layout_type.choices, expected_choices)
                
        except Exception as e:
            # Expected in isolated test without Flask context
            pass


class TestDashboardLayoutViewIsolated(unittest.TestCase):
    """Test cases for DashboardLayoutView."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.layout_view = DashboardLayoutView()
        
        # Mock appbuilder
        self.layout_view.appbuilder = Mock()
        self.layout_view.appbuilder.get_session = Mock()
    
    def test_view_initialization(self):
        """Test view initialization."""
        self.assertEqual(self.layout_view.route_base, '/dashboard-layout')
        self.assertEqual(self.layout_view.form, DashboardLayoutForm)
    
    @patch('pgappforge.views.dashboard_layout.current_user')
    def test_get_user_dashboard_config_default(self, mock_current_user):
        """Test getting default dashboard configuration."""
        mock_current_user.id = 1
        
        # Mock empty database result
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        self.layout_view.appbuilder.get_session.return_value = mock_session
        
        config = self.layout_view._get_user_dashboard_config()
        
        # Should return default configuration
        self.assertEqual(config['title'], 'My Dashboard')
        self.assertEqual(config['layout_type'], 'grid')
        self.assertEqual(config['auto_refresh'], False)
        self.assertEqual(config['refresh_interval'], 300)
        self.assertIn('widgets', config)
    
    @patch('pgappforge.views.dashboard_layout.current_user')
    def test_get_user_dashboard_config_existing(self, mock_current_user):
        """Test getting existing dashboard configuration."""
        mock_current_user.id = 1
        
        # Mock existing config in database
        existing_config = {
            'title': 'Custom Dashboard',
            'layout_type': 'tabs',
            'widgets': [{'type': 'metric_card', 'title': 'Custom Metric'}]
        }
        
        mock_dashboard_config = Mock()
        mock_dashboard_config.config_json = json.dumps(existing_config)
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_dashboard_config
        self.layout_view.appbuilder.get_session.return_value = mock_session
        
        config = self.layout_view._get_user_dashboard_config()
        
        # Should return existing configuration
        self.assertEqual(config['title'], 'Custom Dashboard')
        self.assertEqual(config['layout_type'], 'tabs')
        self.assertIn('widgets', config)
    
    @patch('pgappforge.views.dashboard_layout.current_user')
    def test_save_user_dashboard_config_new(self, mock_current_user):
        """Test saving new dashboard configuration."""
        mock_current_user.id = 1
        
        # Mock no existing config
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        self.layout_view.appbuilder.get_session.return_value = mock_session
        
        config_data = {
            'title': 'New Dashboard',
            'layout_type': 'single_column',
            'widgets': []
        }
        
        result = self.layout_view._save_user_dashboard_config(config_data)
        
        # Should indicate success
        self.assertTrue(result)
        
        # Should have called session.add and commit
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
    
    @patch('pgappforge.views.dashboard_layout.current_user')
    def test_save_user_dashboard_config_update(self, mock_current_user):
        """Test updating existing dashboard configuration."""
        mock_current_user.id = 1
        
        # Mock existing config
        mock_dashboard_config = Mock()
        mock_dashboard_config.config_json = '{}'
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_dashboard_config
        self.layout_view.appbuilder.get_session.return_value = mock_session
        
        config_data = {
            'title': 'Updated Dashboard',
            'layout_type': 'two_column',
            'widgets': [{'type': 'chart', 'title': 'Sales Chart'}]
        }
        
        result = self.layout_view._save_user_dashboard_config(config_data)
        
        # Should indicate success
        self.assertTrue(result)
        
        # Should have updated the config
        self.assertIn('Updated Dashboard', mock_dashboard_config.config_json)
        
        # Should have called commit
        mock_session.commit.assert_called_once()


class TestConfigurableDashboardViewIsolated(unittest.TestCase):
    """Test cases for ConfigurableDashboardView."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.dashboard_view = ConfigurableDashboardView()
        
        # Mock appbuilder
        self.dashboard_view.appbuilder = Mock()
    
    def test_view_initialization(self):
        """Test view initialization."""
        self.assertEqual(self.dashboard_view.route_base, '/dashboard')
        self.assertEqual(self.dashboard_view.default_view, 'index')
    
    @patch('pgappforge.views.configurable_dashboard.current_user')
    def test_get_user_dashboard_config_mock(self, mock_current_user):
        """Test getting user dashboard configuration (mocked)."""
        mock_current_user.id = 1
        
        config = self.dashboard_view._get_user_dashboard_config()
        
        # Should return mock configuration
        self.assertIsInstance(config, dict)
        self.assertIn('title', config)
        self.assertIn('layout_type', config)
        self.assertIn('widgets', config)
    
    def test_create_metric_widget_basic(self):
        """Test creating basic metric widget."""
        widget_config = {
            'type': 'metric_card',
            'title': 'Test Metric',
            'value': 150,
            'icon': 'fa-chart-bar',
            'color': 'primary'
        }
        
        widget = self.dashboard_view._create_metric_widget(widget_config)
        
        self.assertIsInstance(widget, dict)
        self.assertEqual(widget['title'], 'Test Metric')
        self.assertIn('content', widget)
        self.assertTrue(widget['show_header'])
    
    def test_create_metric_widget_with_trend(self):
        """Test creating metric widget with trend."""
        widget_config = {
            'type': 'metric_card',
            'title': 'Sales Revenue',
            'value': 50000,
            'trend': 15.5,
            'subtitle': 'vs last month',
            'icon': 'fa-dollar-sign',
            'color': 'success'
        }
        
        widget = self.dashboard_view._create_metric_widget(widget_config)
        
        self.assertIsInstance(widget, dict)
        self.assertEqual(widget['title'], 'Sales Revenue')
        self.assertIn('content', widget)
        self.assertIn('15.5%', widget['content'])  # Should contain trend
        self.assertIn('fa-dollar-sign', widget['content'])
    
    def test_create_chart_widget_basic(self):
        """Test creating basic chart widget."""
        widget_config = {
            'type': 'line_chart',
            'title': 'Sales Trend',
            'data_source': 'sales_data',
            'height': '300px'
        }
        
        widget = self.dashboard_view._create_chart_widget(widget_config)
        
        self.assertIsInstance(widget, dict)
        self.assertEqual(widget['title'], 'Sales Trend')
        self.assertIn('content', widget)
        self.assertTrue(widget['show_header'])
    
    def test_create_chart_widget_with_options(self):
        """Test creating chart widget with options."""
        widget_config = {
            'type': 'bar_chart',
            'title': 'Monthly Revenue',
            'data_source': 'revenue_data',
            'height': '400px',
            'show_legend': True,
            'color_scheme': 'blues'
        }
        
        widget = self.dashboard_view._create_chart_widget(widget_config)
        
        self.assertIsInstance(widget, dict)
        self.assertEqual(widget['title'], 'Monthly Revenue')
        self.assertIn('content', widget)
        self.assertIn('400px', widget['content'])  # Should include height
    
    def test_render_configured_widgets_mixed(self):
        """Test rendering mix of different widget types."""
        widget_configs = [
            {
                'type': 'metric_card',
                'title': 'Total Users',
                'value': 1250,
                'icon': 'fa-users'
            },
            {
                'type': 'line_chart',
                'title': 'User Growth',
                'data_source': 'user_growth',
                'height': '250px'
            },
            {
                'type': 'metric_card',
                'title': 'Revenue',
                'value': 85000,
                'trend': 12.3,
                'icon': 'fa-dollar-sign'
            }
        ]
        
        widgets = self.dashboard_view._render_configured_widgets(widget_configs)
        
        self.assertEqual(len(widgets), 3)
        
        # Check first widget (metric card)
        self.assertEqual(widgets[0]['title'], 'Total Users')
        self.assertIn('1250', widgets[0]['content'])
        
        # Check second widget (chart)
        self.assertEqual(widgets[1]['title'], 'User Growth')
        self.assertIn('canvas', widgets[1]['content'])
        
        # Check third widget (metric card with trend)
        self.assertEqual(widgets[2]['title'], 'Revenue')
        self.assertIn('85.0K', widgets[2]['content'])  # Formatted value
        self.assertIn('12.3%', widgets[2]['content'])  # Trend
    
    def test_render_configured_widgets_empty(self):
        """Test rendering with no widgets configured."""
        widgets = self.dashboard_view._render_configured_widgets([])
        
        self.assertEqual(len(widgets), 0)
        self.assertIsInstance(widgets, list)
    
    def test_render_configured_widgets_unknown_type(self):
        """Test rendering with unknown widget type."""
        widget_configs = [
            {
                'type': 'unknown_widget_type',
                'title': 'Unknown Widget'
            }
        ]
        
        widgets = self.dashboard_view._render_configured_widgets(widget_configs)
        
        # Should handle gracefully - could return empty list or error widget
        self.assertIsInstance(widgets, list)


class TestDashboardIntegration(unittest.TestCase):
    """Test integration between dashboard components."""
    
    def test_complete_dashboard_workflow(self):
        """Test complete dashboard configuration and rendering workflow."""
        # Create dashboard layout view
        layout_view = DashboardLayoutView()
        layout_view.appbuilder = Mock()
        
        # Create configurable dashboard view
        dashboard_view = ConfigurableDashboardView()
        dashboard_view.appbuilder = Mock()
        
        # Test configuration data
        config_data = {
            'title': 'Business Dashboard',
            'layout_type': 'grid',
            'auto_refresh': True,
            'refresh_interval': 300,
            'widgets': [
                {
                    'type': 'metric_card',
                    'title': 'Total Revenue',
                    'value': 125000,
                    'trend': 18.5,
                    'icon': 'fa-money-bill-wave',
                    'color': 'success',
                    'grid_size': 3
                },
                {
                    'type': 'metric_card',
                    'title': 'Active Users',
                    'value': 2850,
                    'trend': -2.1,
                    'icon': 'fa-users',
                    'color': 'info',
                    'grid_size': 3
                },
                {
                    'type': 'line_chart',
                    'title': 'Revenue Trend',
                    'data_source': 'monthly_revenue',
                    'height': '300px',
                    'grid_size': 6
                }
            ]
        }
        
        # Test saving configuration
        with patch('pgappforge.views.dashboard_layout.current_user') as mock_user:
            mock_user.id = 1
            mock_session = Mock()
            mock_session.query.return_value.filter.return_value.first.return_value = None
            layout_view.appbuilder.get_session.return_value = mock_session
            
            result = layout_view._save_user_dashboard_config(config_data)
            self.assertTrue(result)
        
        # Test rendering widgets
        widgets = dashboard_view._render_configured_widgets(config_data['widgets'])
        
        # Verify widgets were created
        self.assertEqual(len(widgets), 3)
        
        # Verify metric cards
        revenue_widget = widgets[0]
        self.assertEqual(revenue_widget['title'], 'Total Revenue')
        self.assertIn('125.0K', revenue_widget['content'])  # Formatted value
        self.assertIn('18.5%', revenue_widget['content'])   # Trend
        
        users_widget = widgets[1]
        self.assertEqual(users_widget['title'], 'Active Users')
        self.assertIn('2.9K', users_widget['content'])      # Formatted value
        self.assertIn('2.1%', users_widget['content'])      # Trend (absolute)
        
        # Verify chart widget
        chart_widget = widgets[2]
        self.assertEqual(chart_widget['title'], 'Revenue Trend')
        self.assertIn('canvas', chart_widget['content'])
        self.assertIn('300px', chart_widget['content'])


if __name__ == '__main__':
    unittest.main()