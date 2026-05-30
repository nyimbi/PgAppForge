"""
Dashboard Layout Manager for PgAppForge.

Provides customizable dashboard layouts using existing PgAppForge form patterns
and user preference storage for flexible business intelligence displays.
"""

import logging
import json
from typing import List, Dict, Any, Optional

from flask import render_template, request, jsonify, flash, redirect, url_for
from wtforms import SelectField, BooleanField, TextAreaField, StringField
from wtforms.validators import DataRequired, Optional as OptionalValidator
from pgappforge.baseviews import BaseView, SimpleFormView, expose
from pgappforge.security.decorators import has_access
from pgappforge.forms import DynamicForm
from flask_login import current_user

from ..charts.metric_widgets import MetricCardWidget, TrendChartView

log = logging.getLogger(__name__)


class DashboardLayoutForm(DynamicForm):
    """
    Form for configuring dashboard layout and widget placement.
    
    Provides interface for users to customize their dashboard appearance,
    widget selection, and layout preferences using standard PgAppForge patterns.
    """
    
    title = StringField(
        'Dashboard Title',
        validators=[DataRequired()],
        description='Enter a title for your custom dashboard'
    )
    
    layout_type = SelectField(
        'Layout Type',
        choices=[
            ('grid', 'Grid Layout'),
            ('tabs', 'Tabbed Layout'),
            ('single_column', 'Single Column'),
            ('two_column', 'Two Column')
        ],
        default='grid',
        description='Choose how widgets are arranged on the dashboard'
    )
    
    widgets_config = TextAreaField(
        'Widget Configuration',
        validators=[OptionalValidator()],
        description='JSON configuration for dashboard widgets (auto-generated)',
        render_kw={'rows': 8, 'class': 'form-control font-monospace'}
    )
    
    is_default = BooleanField(
        'Set as Default Dashboard',
        default=False,
        description='Make this the default dashboard when you log in'
    )
    
    show_refresh_button = BooleanField(
        'Show Refresh Button',
        default=True,
        description='Display refresh button on dashboard header'
    )
    
    auto_refresh_interval = SelectField(
        'Auto Refresh Interval',
        choices=[
            ('0', 'Disabled'),
            ('300', '5 Minutes'),
            ('600', '10 Minutes'),
            ('1800', '30 Minutes'),
            ('3600', '1 Hour')
        ],
        default='300',
        description='Automatic dashboard refresh frequency'
    )


class DashboardLayoutView(SimpleFormView):
    """
    View for managing dashboard layouts and configurations.
    
    Allows users to create, edit, and manage custom dashboard layouts
    using existing PgAppForge form patterns and user storage.
    """
    
    route_base = '/dashboard-layout'
    form = DashboardLayoutForm
    form_title = 'Configure Dashboard Layout'
    
    # Available widget types that can be added to dashboards
    available_widget_types = [
        {
            'id': 'metric_card',
            'name': 'Metric Card',
            'description': 'Display key metrics with trend indicators',
            'icon': 'fa-chart-bar',
            'config_fields': ['title', 'color', 'icon']
        },
        {
            'id': 'trend_chart', 
            'name': 'Trend Chart',
            'description': 'Time-series line charts for trend analysis',
            'icon': 'fa-chart-line',
            'config_fields': ['title', 'chart_type', 'time_range']
        },
        {
            'id': 'status_pie',
            'name': 'Status Pie Chart', 
            'description': 'Pie chart showing status distribution',
            'icon': 'fa-chart-pie',
            'config_fields': ['title', 'field']
        },
        {
            'id': 'data_table',
            'name': 'Data Table',
            'description': 'Tabular display of recent records',
            'icon': 'fa-table',
            'config_fields': ['title', 'model', 'limit']
        },
        {
            'id': 'activity_feed',
            'name': 'Activity Feed',
            'description': 'Recent activity and changes',
            'icon': 'fa-list',
            'config_fields': ['title', 'limit']
        }
    ]
    
    @expose('/configure', methods=['GET', 'POST'])
    @has_access
    def configure_layout(self):
        """
        Configure dashboard layout using existing PgAppForge form patterns.
        
        Returns:
            Rendered template with form for dashboard configuration
        """
        try:
            form = self.form.refresh()
            
            # Pre-populate form with existing configuration
            existing_config = self._get_user_dashboard_config()
            if existing_config and request.method == 'GET':
                form.title.data = existing_config.get('title', '')
                form.layout_type.data = existing_config.get('layout_type', 'grid')
                form.widgets_config.data = json.dumps(
                    existing_config.get('widgets', []), 
                    indent=2
                )
                form.is_default.data = existing_config.get('is_default', False)
                form.show_refresh_button.data = existing_config.get('show_refresh_button', True)
                form.auto_refresh_interval.data = str(existing_config.get('auto_refresh_interval', 300))
            
            if form.validate_on_submit():
                # Parse widget configuration JSON
                try:
                    widgets_config = json.loads(form.widgets_config.data or '[]')
                except json.JSONDecodeError:
                    flash('Invalid JSON in widget configuration', 'error')
                    return self._render_configure_form(form)
                
                # Build configuration object
                config = {
                    'title': form.title.data,
                    'layout_type': form.layout_type.data,
                    'widgets': widgets_config,
                    'is_default': form.is_default.data,
                    'show_refresh_button': form.show_refresh_button.data,
                    'auto_refresh_interval': int(form.auto_refresh_interval.data),
                    'created_by': current_user.id if current_user.is_authenticated else None,
                    'updated_at': self._get_current_timestamp()
                }
                
                # Validate widget configuration
                validation_errors = self._validate_widgets_config(widgets_config)
                if validation_errors:
                    for error in validation_errors:
                        flash(error, 'warning')
                
                # Save configuration
                if self._save_dashboard_config(config):
                    flash('Dashboard configuration saved successfully!', 'success')
                    return redirect(url_for('ConfigurableDashboardView.index'))
                else:
                    flash('Failed to save dashboard configuration', 'error')
            
            return self._render_configure_form(form)
            
        except Exception as e:
            log.error(f"Error configuring dashboard layout: {e}")
            flash(f'Error configuring dashboard: {str(e)}', 'error')
            return self._render_error_page(str(e))
    
    @expose('/widget-builder')
    @has_access
    def widget_builder(self):
        """
        Interactive widget builder interface.
        
        Returns:
            Rendered widget builder template
        """
        return self.render_template(
            'analytics/widget_builder.html',
            available_widgets=self.available_widget_types,
            layout_types=self._get_layout_type_options()
        )
    
    @expose('/api/widgets')
    @has_access
    def api_available_widgets(self):
        """
        API endpoint to get available widget types.
        
        Returns:
            JSON response with available widget configurations
        """
        return jsonify({
            'status': 'success',
            'widgets': self.available_widget_types,
            'layout_types': self._get_layout_type_options()
        })
    
    @expose('/api/preview', methods=['POST'])
    @has_access
    def api_preview_dashboard(self):
        """
        API endpoint to preview dashboard configuration.
        
        Returns:
            JSON response with rendered dashboard preview
        """
        try:
            config = request.get_json()
            if not config:
                return jsonify({'status': 'error', 'message': 'No configuration provided'}), 400
            
            # Generate preview widgets
            preview_widgets = self._generate_preview_widgets(config.get('widgets', []))
            
            return jsonify({
                'status': 'success',
                'preview_html': self._render_dashboard_preview(config, preview_widgets),
                'widget_count': len(preview_widgets)
            })
            
        except Exception as e:
            log.error(f"Error generating dashboard preview: {e}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    def _render_configure_form(self, form):
        """Render the dashboard configuration form."""
        return self.render_template(
            'analytics/dashboard_config.html',
            form=form,
            available_widgets=self.available_widget_types,
            existing_dashboards=self._get_user_dashboard_list(),
            layout_examples=self._get_layout_examples()
        )
    
    def _get_user_dashboard_config(self) -> Optional[Dict[str, Any]]:
        """
        Get current user's dashboard configuration.
        
        Returns:
            Dictionary with dashboard configuration or None
        """
        try:
            if not current_user.is_authenticated:
                return None
            
            # In a real implementation, this would query a database table
            # For now, return a mock configuration
            return {
                'title': 'My Dashboard',
                'layout_type': 'grid',
                'widgets': [
                    {
                        'type': 'metric_card',
                        'title': 'Total Records',
                        'position': {'row': 0, 'col': 0},
                        'config': {'color': 'primary', 'icon': 'fa-database'}
                    },
                    {
                        'type': 'trend_chart',
                        'title': 'Monthly Trends',
                        'position': {'row': 0, 'col': 1},
                        'config': {'time_range': '30d', 'chart_type': 'line'}
                    }
                ],
                'is_default': False,
                'show_refresh_button': True,
                'auto_refresh_interval': 300
            }
            
        except Exception as e:
            log.warning(f"Error getting user dashboard config: {e}")
            return None
    
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
            log.info(f"Dashboard config saved for user {current_user.id}: {config['title']}")
            return True
            
        except Exception as e:
            log.error(f"Error saving dashboard config: {e}")
            return False
    
    def _validate_widgets_config(self, widgets_config: List[Dict]) -> List[str]:
        """
        Validate widget configuration array.
        
        Args:
            widgets_config: List of widget configuration dictionaries
            
        Returns:
            List of validation error messages
        """
        errors = []
        
        try:
            available_types = [w['id'] for w in self.available_widget_types]
            
            for i, widget in enumerate(widgets_config):
                # Check required fields
                if 'type' not in widget:
                    errors.append(f"Widget {i+1}: Missing 'type' field")
                    continue
                
                if widget['type'] not in available_types:
                    errors.append(f"Widget {i+1}: Unknown widget type '{widget['type']}'")
                
                if 'title' not in widget:
                    errors.append(f"Widget {i+1}: Missing 'title' field")
                
                # Check position if grid layout
                if 'position' in widget:
                    pos = widget['position']
                    if not isinstance(pos, dict) or 'row' not in pos or 'col' not in pos:
                        errors.append(f"Widget {i+1}: Invalid position format")
                        
        except Exception as e:
            errors.append(f"Error validating configuration: {str(e)}")
        
        return errors
    
    def _get_layout_type_options(self) -> List[Dict[str, str]]:
        """Get available layout type options."""
        return [
            {'value': 'grid', 'label': 'Grid Layout', 'description': 'Flexible grid with drag-and-drop'},
            {'value': 'tabs', 'label': 'Tabbed Layout', 'description': 'Organize widgets in tabs'},
            {'value': 'single_column', 'label': 'Single Column', 'description': 'Stack widgets vertically'},
            {'value': 'two_column', 'label': 'Two Column', 'description': 'Split into two columns'}
        ]
    
    def _get_user_dashboard_list(self) -> List[Dict[str, Any]]:
        """Get list of user's saved dashboards."""
        # Mock data - would query database in real implementation
        return [
            {
                'id': 1,
                'title': 'Executive Dashboard',
                'is_default': True,
                'widget_count': 6,
                'updated_at': '2025-09-01'
            },
            {
                'id': 2, 
                'title': 'Operations Dashboard',
                'is_default': False,
                'widget_count': 4,
                'updated_at': '2025-08-28'
            }
        ]
    
    def _get_layout_examples(self) -> Dict[str, Dict]:
        """Get layout configuration examples."""
        return {
            'grid': {
                'name': 'Grid Layout',
                'description': 'Flexible grid system with drag-and-drop positioning',
                'preview_class': 'layout-grid-preview'
            },
            'tabs': {
                'name': 'Tabbed Layout',
                'description': 'Organize related widgets into separate tabs',
                'preview_class': 'layout-tabs-preview'
            },
            'single_column': {
                'name': 'Single Column',
                'description': 'Stack all widgets in a single column',
                'preview_class': 'layout-single-preview'
            },
            'two_column': {
                'name': 'Two Column',
                'description': 'Split dashboard into left and right columns',
                'preview_class': 'layout-two-column-preview'
            }
        }
    
    def _generate_preview_widgets(self, widgets_config: List[Dict]) -> List[Dict]:
        """Generate preview widgets from configuration."""
        preview_widgets = []
        
        for widget_config in widgets_config:
            try:
                widget_type = widget_config.get('type', 'metric_card')
                widget_title = widget_config.get('title', 'Sample Widget')
                
                if widget_type == 'metric_card':
                    preview_widgets.append({
                        'type': 'metric_card',
                        'html': self._create_sample_metric_card(widget_title).render_metric_card(),
                        'title': widget_title,
                        'position': widget_config.get('position', {'row': 0, 'col': 0})
                    })
                elif widget_type == 'trend_chart':
                    preview_widgets.append({
                        'type': 'trend_chart',
                        'html': f'<div class="chart-placeholder">{widget_title} Chart Placeholder</div>',
                        'title': widget_title,
                        'position': widget_config.get('position', {'row': 0, 'col': 1})
                    })
                else:
                    preview_widgets.append({
                        'type': widget_type,
                        'html': f'<div class="widget-placeholder">{widget_title}</div>',
                        'title': widget_title,
                        'position': widget_config.get('position', {'row': 0, 'col': 0})
                    })
                    
            except Exception as e:
                log.warning(f"Error generating preview widget: {e}")
                continue
        
        return preview_widgets
    
    def _create_sample_metric_card(self, title: str) -> MetricCardWidget:
        """Create a sample metric card for preview."""
        sample_values = [1250, 45, 12, 8, 234, 1500]
        sample_trends = [15.2, -5.1, 8.7, 22.3, -12.4, 45.8]
        
        import random
        value = random.choice(sample_values)
        trend = random.choice(sample_trends)
        
        return MetricCardWidget(
            title=title,
            value=value,
            trend=trend,
            subtitle="Sample data",
            icon="fa-chart-bar",
            color="primary"
        )
    
    def _render_dashboard_preview(self, config: Dict, widgets: List[Dict]) -> str:
        """Render dashboard preview HTML."""
        layout_type = config.get('layout_type', 'grid')
        
        if layout_type == 'grid':
            return self._render_grid_preview(widgets)
        elif layout_type == 'tabs':
            return self._render_tabs_preview(widgets)
        else:
            return self._render_column_preview(widgets, layout_type)
    
    def _render_grid_preview(self, widgets: List[Dict]) -> str:
        """Render grid layout preview."""
        grid_html = '<div class="dashboard-preview dashboard-grid">'
        
        for widget in widgets:
            position = widget.get('position', {'row': 0, 'col': 0})
            grid_html += f'''
            <div class="grid-item" data-row="{position['row']}" data-col="{position['col']}">
                {widget['html']}
            </div>
            '''
        
        grid_html += '</div>'
        return grid_html
    
    def _render_tabs_preview(self, widgets: List[Dict]) -> str:
        """Render tabbed layout preview."""
        tabs_html = '''
        <div class="dashboard-preview dashboard-tabs">
            <ul class="nav nav-tabs">
                <li class="nav-item">
                    <a class="nav-link active" href="#tab1">Dashboard</a>
                </li>
            </ul>
            <div class="tab-content">
                <div class="tab-pane active" id="tab1">
                    <div class="row">
        '''
        
        for widget in widgets[:4]:  # Limit preview widgets
            tabs_html += f'''
                        <div class="col-md-6 mb-3">
                            {widget['html']}
                        </div>
            '''
        
        tabs_html += '''
                    </div>
                </div>
            </div>
        </div>
        '''
        return tabs_html
    
    def _render_column_preview(self, widgets: List[Dict], layout_type: str) -> str:
        """Render column layout preview."""
        col_class = 'col-12' if layout_type == 'single_column' else 'col-md-6'
        
        preview_html = f'<div class="dashboard-preview dashboard-{layout_type}"><div class="row">'
        
        for widget in widgets[:4]:  # Limit preview widgets
            preview_html += f'''
                <div class="{col_class} mb-3">
                    {widget['html']}
                </div>
            '''
        
        preview_html += '</div></div>'
        return preview_html
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp as string."""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def _render_error_page(self, error_message: str):
        """Render error page for dashboard configuration."""
        return self.render_template(
            'analytics/dashboard_error.html',
            error_message=error_message
        )