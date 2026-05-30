"""
Widget Gallery and Documentation System for PgAppForge (Unified Version)

This module provides a comprehensive gallery and documentation system
for all available widgets using the unified import system, with interactive
examples and usage guides.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, current_app
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.views import ModelView

# Import all available widgets through the unified system
from . import get_available_widgets, get_widget_by_name
from .xss_security import XSSProtection

log = logging.getLogger(__name__)


class UnifiedWidgetGalleryView(BaseView):
    """
    Widget Gallery view for showcasing and testing all available widgets
    using the unified import system.

    Features:
    - Dynamic widget discovery
    - Interactive widget showcase
    - Live code examples
    - Configuration options
    - Copy-to-clipboard functionality
    - Widget performance metrics
    - Integration guides
    """

    route_base = '/admin/widget-gallery'
    default_view = 'gallery'

    def __init__(self):
        super().__init__()
        # Build widget categories dynamically from unified system
        self.widget_categories = self._build_widget_categories()

    def _get_widget_descriptions(self):
        """Static widget descriptions and example configurations."""
        return {
            'ModernTextWidget': {
                'description': 'Modern text input with floating labels and validation',
                'example_config': {
                    'icon_prefix': 'fa-user',
                    'show_counter': True,
                    'max_length': 100,
                    'floating_label': True
                }
            },
            'ModernTextAreaWidget': {
                'description': 'Advanced textarea with rich text features',
                'example_config': {
                    'auto_resize': True,
                    'rich_text': True,
                    'markdown_preview': True,
                    'show_stats': True
                }
            },
            'ColorPickerWidget': {
                'description': 'Advanced color picker with palette and history',
                'example_config': {
                    'show_palette': True,
                    'show_history': True,
                    'custom_colors': ['#ff5733', '#33ff57', '#3357ff']
                }
            },
            'CodeEditorWidget': {
                'description': 'Advanced code editor with syntax highlighting',
                'example_config': {
                    'language': 'javascript',
                    'theme': 'vs-light',
                    'font_size': 14,
                    'line_numbers': True,
                    'minimap': True
                }
            },
            'AdvancedChartsWidget': {
                'description': 'Advanced charts with Chart.js integration',
                'example_config': {
                    'chart_type': 'line',
                    'theme': 'light',
                    'responsive': True,
                    'animation': True,
                    'zoom_enabled': True
                }
            },
            'GPSTrackerWidget': {
                'description': 'GPS tracking widget with interactive maps',
                'example_config': {
                    'map_provider': 'openstreetmap',
                    'enable_tracking': True,
                    'enable_geofencing': True,
                    'enable_routes': True
                }
            },
            'MermaidEditorWidget': {
                'description': 'Mermaid diagram editor with live preview',
                'example_config': {
                    'theme': 'default',
                    'enable_live_preview': True,
                    'diagram_types': ['flowchart', 'sequence', 'class']
                }
            },
            'DbmlEditorWidget': {
                'description': 'Database schema editor using DBML',
                'example_config': {
                    'show_preview': True,
                    'enable_export': True,
                    'validate_syntax': True
                }
            },
            'QrCodeWidget': {
                'description': 'QR code generator and scanner',
                'example_config': {
                    'mode': 'generate',
                    'error_level': 'M',
                    'size': 256,
                    'enable_scanner': True
                }
            }
        }

    def _get_category_metadata(self):
        """Category metadata for organizing widgets."""
        return {
            'core': {
                'name': 'Core Widgets',
                'description': 'Essential PgAppForge widgets for basic functionality'
            },
            'field': {
                'name': 'Field Widgets',
                'description': 'Form field widgets for data input and selection'
            },
            'modern_ui': {
                'name': 'Modern UI Widgets',
                'description': 'Enhanced UI components with modern styling and interactions'
            },
            'advanced_forms': {
                'name': 'Advanced Form Widgets',
                'description': 'Sophisticated form components for complex data entry'
            },
            'specialized_data': {
                'name': 'Specialized Data Widgets',
                'description': 'Widgets for complex data types like JSON, arrays, and more'
            },
            'modular': {
                'name': 'Modular Widgets',
                'description': 'New generation widgets with specialized functionality'
            }
        }

    def _build_widget_categories(self):
        """Build widget categories dynamically from the unified system."""
        available_widgets = get_available_widgets()
        widget_descriptions = self._get_widget_descriptions()
        category_metadata = self._get_category_metadata()

        categories = {}
        for category_key, widgets_dict in available_widgets.items():
            if category_key in category_metadata:
                categories[category_key] = {
                    'name': category_metadata[category_key]['name'],
                    'description': category_metadata[category_key]['description'],
                    'widgets': {}
                }

                for widget_name, widget_class in widgets_dict.items():
                    widget_info = {
                        'class': widget_class,
                        'description': widget_descriptions.get(widget_name, {}).get(
                            'description', f'{widget_name} widget'
                        ),
                        'example_config': widget_descriptions.get(widget_name, {}).get(
                            'example_config', {}
                        )
                    }
                    categories[category_key]['widgets'][widget_name] = widget_info

        return categories

    @expose('/gallery/')
    @has_access
    def gallery(self):
        """Main widget gallery page."""
        return self.render_template('widget_gallery/gallery.html',
            widget_categories=self.widget_categories,
            title='Widget Gallery'
        )

    @expose('/widget/<category>/<widget_name>/')
    @has_access
    def widget_detail(self, category, widget_name):
        """Widget detail page with interactive example."""
        if category not in self.widget_categories:
            return self.render_template('widget_gallery/not_found.html'), 404

        widgets = self.widget_categories[category]['widgets']
        if widget_name not in widgets:
            return self.render_template('widget_gallery/not_found.html'), 404

        widget_info = widgets[widget_name]

        return self.render_template('widget_gallery/widget_detail.html',
            category_name=self.widget_categories[category]['name'],
            widget_name=widget_name,
            widget_info=widget_info,
            title=f'{widget_name} - Widget Gallery'
        )

    @expose('/api/widget-config', methods=['POST'])
    @has_access
    def update_widget_config(self):
        """API endpoint for updating widget configuration."""
        data = request.get_json()

        category = data.get('category')
        widget_name = data.get('widget_name')
        config = data.get('config', {})

        if not all([category, widget_name]):
            return jsonify({'error': 'Missing required parameters'}), 400

        try:
            # Get widget class from unified system
            widget_class = get_widget_by_name(widget_name)
            if not widget_class:
                return jsonify({'error': f'Widget {widget_name} not found'}), 404

            # Validate configuration
            widget_instance = widget_class(**config)

            return jsonify({
                'success': True,
                'message': 'Configuration updated successfully'
            })
        except Exception as e:
            return jsonify({
                'error': f'Invalid configuration: {XSSProtection.escape_json_string(str(e))}'
            }), 400

    @expose('/api/generate-code', methods=['POST'])
    @has_access
    def generate_code(self):
        """Generate code examples for widget usage."""
        data = request.get_json()

        category = data.get('category')
        widget_name = data.get('widget_name')
        config = data.get('config', {})
        usage_type = data.get('usage_type', 'basic')

        try:
            code_examples = self._generate_widget_code(category, widget_name, config, usage_type)
            return jsonify({
                'success': True,
                'code_examples': code_examples
            })
        except Exception as e:
            return jsonify({
                'error': f'Code generation failed: {XSSProtection.escape_json_string(str(e))}'
            }), 500

    def _generate_widget_code(self, category, widget_name, config, usage_type):
        """Generate code examples for widget usage."""
        widget_class = get_widget_by_name(widget_name)
        if not widget_class:
            raise ValueError(f"Widget {widget_name} not found")

        config_str = json.dumps(config, indent=4) if config else '{}'

        examples = {
            'basic': f"""
# Basic usage
from pgappforge.widgets import {widget_name}

widget = {widget_name}(**{config_str})
            """.strip(),

            'form': f"""
# Form usage
from wtforms import StringField
from pgappforge.fieldwidgets import {widget_name}

class MyForm(FlaskForm):
    my_field = StringField('My Field', widget={widget_name}(**{config_str}))
            """.strip(),

            'view': f"""
# ModelView usage
from pgappforge import ModelView
from pgappforge.widgets import {widget_name}

class MyModelView(ModelView):
    edit_widget = {widget_name}(**{config_str})
    add_widget = {widget_name}(**{config_str})
            """.strip()
        }

        return examples.get(usage_type, examples['basic'])

    @expose('/api/widget-list')
    @has_access
    def widget_list(self):
        """API endpoint to get list of all available widgets."""
        widget_list = []
        for category_key, category_info in self.widget_categories.items():
            for widget_name, widget_info in category_info['widgets'].items():
                widget_list.append({
                    'name': widget_name,
                    'category': category_key,
                    'category_name': category_info['name'],
                    'description': widget_info['description']
                })

        return jsonify({
            'success': True,
            'widgets': widget_list,
            'total': len(widget_list)
        })

    @expose('/api/category-stats')
    @has_access
    def category_stats(self):
        """API endpoint for widget statistics by category."""
        stats = {}
        for category_key, category_info in self.widget_categories.items():
            stats[category_key] = {
                'name': category_info['name'],
                'description': category_info['description'],
                'widget_count': len(category_info['widgets']),
                'widgets': list(category_info['widgets'].keys())
            }

        return jsonify({
            'success': True,
            'stats': stats,
            'total_categories': len(stats),
            'total_widgets': sum(s['widget_count'] for s in stats.values())
        })