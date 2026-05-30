"""
Widget Gallery and Documentation System for PgAppForge

This module provides a comprehensive gallery and documentation system
for all available widgets, with interactive examples and usage guides.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify, current_app
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.views import ModelView

# Import all available widgets through the unified system
from . import get_available_widgets, get_widget_by_name
from .xss_security import XSSProtection

log = logging.getLogger(__name__)


class WidgetGalleryView(BaseView):
    """
    Widget Gallery view for showcasing and testing all available widgets.

    Features:
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

    def _build_widget_categories(self):
        """Build widget categories dynamically from the unified system."""
        available_widgets = get_available_widgets()

        # Static configuration for widget examples and descriptions
        widget_configs = {
        'modern_ui': {
            'name': 'Modern UI Widgets',
            'description': 'Enhanced UI components with modern styling and interactions',
            'widgets': {
                'ModernTextWidget': {
                    'class': ModernTextWidget,
                    'description': 'Modern text input with floating labels and validation',
                    'example_config': {
                        'icon_prefix': 'fa-user',
                        'show_counter': True,
                        'max_length': 100,
                        'floating_label': True
                    }
                },
                'ModernTextAreaWidget': {
                    'class': ModernTextAreaWidget,
                    'description': 'Advanced textarea with rich text features',
                    'example_config': {
                        'auto_resize': True,
                        'rich_text': True,
                        'markdown_preview': True,
                        'show_stats': True
                    }
                },
                'ModernSelectWidget': {
                    'class': ModernSelectWidget,
                    'description': 'Enhanced select dropdown with search and AJAX support',
                    'example_config': {
                        'searchable': True,
                        'multiple': False,
                        'placeholder': 'Select an option...'
                    }
                },
                'ColorPickerWidget': {
                    'class': ColorPickerWidget,
                    'description': 'Advanced color picker with palette and history',
                    'example_config': {
                        'show_palette': True,
                        'show_history': True,
                        'custom_colors': ['#ff5733', '#33ff57', '#3357ff']
                    }
                },
                'FileUploadWidget': {
                    'class': FileUploadWidget,
                    'description': 'Drag & drop file upload with preview and progress',
                    'example_config': {
                        'multiple': True,
                        'show_preview': True,
                        'max_files': 5,
                        'allowed_types': ['image/*', 'application/pdf']
                    }
                },
                'DateTimeRangeWidget': {
                    'class': DateTimeRangeWidget,
                    'description': 'Date and time range picker with predefined ranges',
                    'example_config': {
                        'include_time': True,
                        'predefined_ranges': True,
                        'business_hours_only': False
                    }
                },
                'TagInputWidget': {
                    'class': TagInputWidget,
                    'description': 'Tag input with autocomplete and validation',
                    'example_config': {
                        'max_tags': 10,
                        'tag_colors': True,
                        'sortable': True,
                        'allow_duplicates': False
                    }
                },
                'SignatureWidget': {
                    'class': SignatureWidget,
                    'description': 'Digital signature capture with mouse/touch drawing capability',
                    'example_config': {
                        'canvas_width': 600,
                        'canvas_height': 200,
                        'pen_color': '#000000',
                        'show_guidelines': True,
                        'require_signature': True
                    }
                }
            }
        },
        'advanced_forms': {
            'name': 'Advanced Form Widgets',
            'description': 'Sophisticated form components for complex data entry',
            'widgets': {
                'FormBuilderWidget': {
                    'class': FormBuilderWidget,
                    'description': 'Dynamic form builder with drag & drop interface',
                    'example_config': {
                        'enable_conditional_logic': True,
                        'max_fields': 20,
                        'enable_validation': True
                    }
                },
                'ValidationWidget': {
                    'class': ValidationWidget,
                    'description': 'Real-time validation with visual feedback',
                    'example_config': {
                        'validation_rules': [
                            {'type': 'required'},
                            {'type': 'minLength', 'options': {'min': 5}}
                        ],
                        'show_progress': True,
                        'debounce_delay': 300
                    }
                },
                'ConditionalFieldWidget': {
                    'class': ConditionalFieldWidget,
                    'description': 'Smart field visibility with dependency tracking',
                    'example_config': {
                        'conditions': [
                            {'field': 'type', 'operator': 'equals', 'value': 'premium'}
                        ],
                        'animation_duration': 300,
                        'show_by_default': False
                    }
                },
                'MultiStepFormWidget': {
                    'class': MultiStepFormWidget,
                    'description': 'Multi-step wizard with progress tracking',
                    'example_config': {
                        'steps': [
                            {'title': 'Step 1', 'description': 'First step'},
                            {'title': 'Step 2', 'description': 'Second step'}
                        ],
                        'show_progress': True,
                        'linear_navigation': True
                    }
                },
                'DataTableWidget': {
                    'class': DataTableWidget,
                    'description': 'Advanced data table with inline editing',
                    'example_config': {
                        'columns': [
                            {'key': 'name', 'title': 'Name', 'editable': True},
                            {'key': 'email', 'title': 'Email', 'editable': True}
                        ],
                        'editable': True,
                        'sortable': True
                    }
                }
            }
        },
        'specialized_data': {
            'name': 'Specialized Data Widgets',
            'description': 'Widgets for complex data types like JSON, arrays, and more',
            'widgets': {
                'JSONEditorWidget': {
                    'class': JSONEditorWidget,
                    'description': 'JSON editor with syntax highlighting and validation',
                    'example_config': {
                        'show_tree_view': True,
                        'enable_search': True,
                        'auto_format': True
                    }
                },
                'ArrayEditorWidget': {
                    'class': ArrayEditorWidget,
                    'description': 'Dynamic array editor with sortable items',
                    'example_config': {
                        'item_type': 'text',
                        'sortable': True,
                        'max_items': 10,
                        'min_items': 1
                    }
                }
            }
        }
    }
    
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
            # Validate configuration
            widget_class = self.widget_categories[category]['widgets'][widget_name]['class']
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
        usage_type = data.get('usage_type', 'basic')  # basic, form, view
        
        try:
            code_examples = self._generate_widget_code(category, widget_name, config, usage_type)
            return jsonify({
                'success': True,
                'code_examples': code_examples
            })
        except Exception as e:
            return jsonify({
                'error': f'Code generation failed: {XSSProtection.escape_json_string(str(e))}'
            }), 400
    
    def _generate_widget_code(self, category, widget_name, config, usage_type):
        """Generate code examples for widget usage."""
        widget_module = {
            'modern_ui': 'pgappforge.widgets.modern_ui',
            'advanced_forms': 'pgappforge.widgets.advanced_forms',
            'specialized_data': 'pgappforge.widgets.specialized_data'
        }.get(category, 'pgappforge.widgets')
        
        # Format config for Python code
        config_str = self._format_config_for_code(config)
        
        examples = {}
        
        if usage_type == 'basic':
            examples['basic_usage'] = f'''# Basic widget usage
from {widget_module} import {widget_name}

# Create widget instance
widget = {widget_name}({config_str})

# Use in WTForms field
from wtforms import StringField

class MyForm(FlaskForm):
    my_field = StringField('My Field', widget=widget)'''

        elif usage_type == 'form':
            examples['form_usage'] = f'''# Form integration
from pgappforge.forms import DynamicForm
from {widget_module} import {widget_name}

class MyModelForm(DynamicForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Apply widget to specific field
        if 'my_field' in self._fields:
            self._fields['my_field'].widget = {widget_name}({config_str})'''

        elif usage_type == 'view':
            examples['view_usage'] = f'''# ModelView integration
from pgappforge.views import ModelView
from {widget_module} import {widget_name}

class MyModelView(ModelView):
    datamodel = SQLAInterface(MyModel)
    
    def __init__(self):
        super().__init__()
        
        # Customize widget for specific field
        self.add_form_widget = {{
            'my_field': {widget_name}({config_str})
        }}
        self.edit_form_widget = {{
            'my_field': {widget_name}({config_str})
        }}'''
        
        # Add CSS/JS requirements if any
        if self._widget_has_assets(category, widget_name):
            examples['assets'] = f'''# Required assets (add to your template)
<!-- CSS -->
<link rel="stylesheet" href="/static/css/{category}_widgets.css">

<!-- JavaScript -->
<script src="/static/js/{category}_widgets.js"></script>'''
        
        return examples
    
    def _format_config_for_code(self, config):
        """Format configuration dictionary for Python code."""
        if not config:
            return ''
            
        formatted_items = []
        for key, value in config.items():
            if isinstance(value, str):
                formatted_items.append(f'{key}="{value}"')
            elif isinstance(value, bool):
                formatted_items.append(f'{key}={value}')
            elif isinstance(value, (int, float)):
                formatted_items.append(f'{key}={value}')
            elif isinstance(value, list):
                formatted_items.append(f'{key}={value!r}')
            elif isinstance(value, dict):
                formatted_items.append(f'{key}={value!r}')
            else:
                formatted_items.append(f'{key}={value!r}')
                
        return ', '.join(formatted_items)
    
    def _widget_has_assets(self, category, widget_name):
        """Check if widget requires additional CSS/JS assets."""
        # In a real implementation, this would check for asset requirements
        return category in ['modern_ui', 'advanced_forms']
    
    @expose('/export')
    @has_access
    def export_widgets(self):
        """Export widget configurations and examples."""
        export_data = {
            'widget_library_version': '1.0.0',
            'export_timestamp': json.dumps(
                datetime.now(tz=timezone.utc).isoformat(),
                default=str
            ),
            'categories': {}
        }
        
        for category_id, category_info in self.widget_categories.items():
            export_data['categories'][category_id] = {
                'name': category_info['name'],
                'description': category_info['description'],
                'widgets': {}
            }
            
            for widget_name, widget_info in category_info['widgets'].items():
                export_data['categories'][category_id]['widgets'][widget_name] = {
                    'description': widget_info['description'],
                    'example_config': widget_info['example_config'],
                    'code_examples': self._generate_widget_code(
                        category_id, widget_name,
                        widget_info['example_config'], 'basic'
                    )
                }
        
        return jsonify(export_data)
    
    @expose('/test-widget', methods=['POST'])
    @has_access
    def test_widget(self):
        """Test widget functionality with provided configuration."""
        data = request.get_json()
        
        category = data.get('category')
        widget_name = data.get('widget_name')
        config = data.get('config', {})
        test_data = data.get('test_data', '')
        
        try:
            # Get widget class
            widget_class = self.widget_categories[category]['widgets'][widget_name]['class']
            
            # Create widget instance
            widget_instance = widget_class(**config)
            
            # Create mock field for testing
            from wtforms import StringField
            from wtforms.form import Form
            
            class TestForm(Form):
                test_field = StringField('Test Field', default=test_data)
            
            form = TestForm()
            form.test_field.widget = widget_instance
            
            # Render widget HTML
            widget_html = str(widget_instance(form.test_field))
            
            return jsonify({
                'success': True,
                'widget_html': widget_html,
                'test_data': test_data,
                'config_used': config
            })
            
        except Exception as e:
            return jsonify({
                'error': f'Widget test failed: {XSSProtection.escape_json_string(str(e))}'
            }), 400
    
    @expose('/widget-performance', methods=['POST'])
    @has_access
    def analyze_widget_performance(self):
        """Analyze widget performance metrics."""
        data = request.get_json()
        
        category = data.get('category')
        widget_name = data.get('widget_name')
        
        try:
            import time
            import psutil
            import os
            
            # Get current process info
            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss
            
            start_time = time.time()
            
            # Get widget class and create instance
            widget_class = self.widget_categories[category]['widgets'][widget_name]['class']
            widget_config = self.widget_categories[category]['widgets'][widget_name]['example_config']
            
            # Test widget instantiation performance
            instances = []
            for i in range(10):  # Create 10 instances
                instance = widget_class(**widget_config)
                instances.append(instance)
            
            instantiation_time = time.time() - start_time
            
            # Test rendering performance
            from wtforms import StringField
            from wtforms.form import Form
            
            class PerfTestForm(Form):
                test_field = StringField('Test Field', default='Sample data for performance testing')
            
            render_start = time.time()
            
            for instance in instances:
                form = PerfTestForm()
                form.test_field.widget = instance
                html = str(instance(form.test_field))
            
            render_time = time.time() - render_start
            
            final_memory = process.memory_info().rss
            memory_usage = final_memory - initial_memory
            
            performance_data = {
                'widget_name': widget_name,
                'category': category,
                'instantiation_time_ms': round(instantiation_time * 1000, 2),
                'render_time_ms': round(render_time * 1000, 2),
                'memory_usage_kb': round(memory_usage / 1024, 2),
                'instances_tested': len(instances),
                'avg_instantiation_ms': round((instantiation_time / len(instances)) * 1000, 2),
                'avg_render_ms': round((render_time / len(instances)) * 1000, 2)
            }
            
            return jsonify({
                'success': True,
                'performance': performance_data
            })
            
        except Exception as e:
            return jsonify({
                'error': f'Performance analysis failed: {XSSProtection.escape_json_string(str(e))}'
            }), 400
    
    @expose('/save-custom-widget', methods=['POST'])
    @has_access
    def save_custom_widget(self):
        """Save custom widget configuration for reuse."""
        data = request.get_json()
        
        custom_name = data.get('custom_name')
        base_category = data.get('base_category')
        base_widget = data.get('base_widget')
        custom_config = data.get('custom_config', {})
        description = data.get('description', '')
        
        if not all([custom_name, base_category, base_widget]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # In a real implementation, this would save to a database
        # For now, we'll store in session/memory
        if not hasattr(current_app, 'custom_widgets'):
            current_app.custom_widgets = {}
        
        current_app.custom_widgets[custom_name] = {
            'base_category': base_category,
            'base_widget': base_widget,
            'config': custom_config,
            'description': description,
            'created_at': datetime.now(tz=timezone.utc).isoformat(),
            'class': self.widget_categories[base_category]['widgets'][base_widget]['class']
        }
        
        return jsonify({
            'success': True,
            'message': f'Custom widget "{custom_name}" saved successfully'
        })
    
    @expose('/custom-widgets')
    @has_access
    def list_custom_widgets(self):
        """List all saved custom widget configurations."""
        custom_widgets = getattr(current_app, 'custom_widgets', {})
        
        return jsonify({
            'success': True,
            'custom_widgets': custom_widgets
        })
    
    @expose('/widget-documentation/<category>/<widget_name>')
    @has_access
    def widget_documentation(self, category, widget_name):
        """Generate comprehensive documentation for a widget."""
        if category not in self.widget_categories:
            return self.render_template('widget_gallery/not_found.html'), 404
            
        widgets = self.widget_categories[category]['widgets']
        if widget_name not in widgets:
            return self.render_template('widget_gallery/not_found.html'), 404
        
        widget_info = widgets[widget_name]
        widget_class = widget_info['class']
        
        # Extract documentation from widget class
        class_doc = widget_class.__doc__ or 'No documentation available'
        init_doc = widget_class.__init__.__doc__ or 'No initialization documentation'
        
        # Get widget features from docstring
        features = []
        if 'Features:' in class_doc:
            features_section = class_doc.split('Features:')[1].split('\n\n')[0]
            features = [line.strip('- ').strip() for line in features_section.split('\n') if line.strip().startswith('-')]
        
        # Generate parameter documentation
        import inspect
        sig = inspect.signature(widget_class.__init__)
        parameters = []
        
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
                
            param_info = {
                'name': param_name,
                'type': str(param.annotation) if param.annotation != inspect.Parameter.empty else 'Any',
                'default': str(param.default) if param.default != inspect.Parameter.empty else 'Required',
                'description': f'Parameter for {param_name}'  # Could be extracted from docstring
            }
            parameters.append(param_info)
        
        documentation = {
            'widget_name': widget_name,
            'category': category,
            'description': widget_info['description'],
            'class_documentation': class_doc,
            'features': features,
            'parameters': parameters,
            'example_config': widget_info['example_config'],
            'code_examples': self._generate_widget_code(category, widget_name, widget_info['example_config'], 'basic')
        }
        
        return self.render_template('widget_gallery/documentation.html',
            documentation=documentation,
            title=f'{widget_name} Documentation'
        )


class WidgetGalleryTemplateManager:
    """Manages templates for the widget gallery system."""
    
    @staticmethod
    def get_template(template_name):
        """Get template content by name."""
        templates = {
            'gallery': gallery_template,
            'widget_detail': widget_detail_template,
            'documentation': documentation_template,
            'not_found': not_found_template
        }
        return templates.get(template_name, '')
    
    @staticmethod
    def register_templates(app):
        """Register templates with PgAppForge."""
        template_dir = app.config.get('WIDGET_GALLERY_TEMPLATE_DIR', 'widget_gallery')
        
        # Create template directory structure if it doesn't exist
        import os
        from flask import current_app
        
        template_path = os.path.join(current_app.template_folder, template_dir)
        os.makedirs(template_path, exist_ok=True)
        
        # Write templates to files
        templates = {
            'gallery.html': gallery_template,
            'widget_detail.html': widget_detail_template,
            'documentation.html': documentation_template,
            'not_found.html': not_found_template
        }
        
        for filename, content in templates.items():
            file_path = os.path.join(template_path, filename)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)


# Widget Gallery Templates
gallery_template = '''
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">
                        <i class="fa fa-th-large"></i> {{ title }}
                    </h3>
                    <div class="card-tools">
                        <button type="button" class="btn btn-primary btn-sm" onclick="exportWidgets()">
                            <i class="fa fa-download"></i> Export Documentation
                        </button>
                    </div>
                </div>
                
                <div class="card-body">
                    <div class="widget-gallery">
                        {% for category_id, category_info in widget_categories.items() %}
                        <div class="widget-category">
                            <div class="category-header">
                                <h4>{{ category_info.name }}</h4>
                                <p class="text-muted">{{ category_info.description }}</p>
                            </div>
                            
                            <div class="widget-grid">
                                {% for widget_name, widget_info in category_info.widgets.items() %}
                                <div class="widget-card">
                                    <div class="widget-preview">
                                        <div class="preview-placeholder">
                                            <i class="fa fa-puzzle-piece fa-2x text-muted"></i>
                                        </div>
                                    </div>
                                    
                                    <div class="widget-info">
                                        <h5>{{ widget_name }}</h5>
                                        <p class="text-muted">{{ widget_info.description }}</p>
                                        
                                        <div class="widget-actions">
                                            <a href="{{ url_for('WidgetGalleryView.widget_detail', 
                                                               category=category_id, 
                                                               widget_name=widget_name) }}" 
                                               class="btn btn-primary btn-sm">
                                                <i class="fa fa-eye"></i> View Details
                                            </a>
                                            
                                            <button type="button" class="btn btn-secondary btn-sm"
                                                    onclick="copyExample('{{ category_id }}', '{{ widget_name }}')">
                                                <i class="fa fa-code"></i> Copy Code
                                            </button>
                                        </div>
                                    </div>
                                </div>
                                {% endfor %}
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<style>
.widget-gallery {
    padding: 1rem 0;
}

.widget-category {
    margin-bottom: 3rem;
}

.category-header {
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 2px solid #e9ecef;
}

.category-header h4 {
    color: #495057;
    font-weight: 600;
}

.widget-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 2rem;
}

.widget-card {
    border: 1px solid #dee2e6;
    border-radius: 8px;
    background: white;
    overflow: hidden;
    transition: all 0.3s ease;
}

.widget-card:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    transform: translateY(-2px);
}

.widget-preview {
    height: 150px;
    background: #f8f9fa;
    display: flex;
    align-items: center;
    justify-content: center;
    border-bottom: 1px solid #e9ecef;
}

.preview-placeholder {
    text-align: center;
}

.widget-info {
    padding: 1.5rem;
}

.widget-info h5 {
    margin-bottom: 0.5rem;
    color: #495057;
}

.widget-info p {
    font-size: 0.9rem;
    margin-bottom: 1rem;
}

.widget-actions {
    display: flex;
    gap: 0.5rem;
}
</style>

<script>
function copyExample(category, widgetName) {
    // Generate and copy basic usage example
    fetch('{{ url_for("WidgetGalleryView.generate_code") }}', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            category: category,
            widget_name: widgetName,
            usage_type: 'basic'
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success && data.code_examples.basic_usage) {
            navigator.clipboard.writeText(data.code_examples.basic_usage);
            // Show success message
            showToast('Code example copied to clipboard!', 'success');
        }
    });
}

function exportWidgets() {
    window.location.href = '{{ url_for("WidgetGalleryView.export_widgets") }}';
}

function showToast(message, type) {
    // Simple toast notification
    const toast = document.createElement('div');
    toast.className = `alert alert-${type} alert-dismissible`;
    toast.style.position = 'fixed';
    toast.style.top = '20px';
    toast.style.right = '20px';
    toast.style.zIndex = '9999';
    toast.innerHTML = `
        ${message}
        <button type="button" class="close" data-dismiss="alert">
            <span>&times;</span>
        </button>
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 5000);
}
</script>
{% endblock %}
'''

widget_detail_template = '''
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <!-- Widget Configuration Panel -->
        <div class="col-md-4">
            <div class="card">
                <div class="card-header">
                    <h5>
                        <i class="fa fa-cog"></i> Configuration
                    </h5>
                </div>
                
                <div class="card-body">
                    <form id="widget-config-form">
                        <div id="config-controls">
                            <!-- Configuration controls will be generated here -->
                        </div>
                        
                        <div class="form-group mt-3">
                            <button type="button" class="btn btn-primary btn-block" onclick="updateWidget()">
                                <i class="fa fa-refresh"></i> Update Preview
                            </button>
                        </div>
                    </form>
                </div>
            </div>
            
            <div class="card mt-3">
                <div class="card-header">
                    <h5>
                        <i class="fa fa-code"></i> Code Examples
                    </h5>
                </div>
                
                <div class="card-body">
                    <div class="btn-group btn-group-sm mb-3" role="group">
                        <button type="button" class="btn btn-outline-primary active" 
                                onclick="showCodeExample('basic')">Basic</button>
                        <button type="button" class="btn btn-outline-primary" 
                                onclick="showCodeExample('form')">Form</button>
                        <button type="button" class="btn btn-outline-primary" 
                                onclick="showCodeExample('view')">View</button>
                    </div>
                    
                    <div id="code-examples">
                        <pre><code id="code-content">Loading...</code></pre>
                        <button type="button" class="btn btn-sm btn-secondary mt-2" onclick="copyCode()">
                            <i class="fa fa-copy"></i> Copy Code
                        </button>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Widget Preview Panel -->
        <div class="col-md-8">
            <div class="card">
                <div class="card-header">
                    <h5>
                        <i class="fa fa-eye"></i> Live Preview - {{ widget_name }}
                    </h5>
                </div>
                
                <div class="card-body">
                    <div id="widget-preview" class="widget-preview-container">
                        <!-- Widget preview will be rendered here -->
                    </div>
                </div>
            </div>
            
            <div class="card mt-3">
                <div class="card-header">
                    <h5>
                        <i class="fa fa-info-circle"></i> Widget Information
                    </h5>
                </div>
                
                <div class="card-body">
                    <p><strong>Description:</strong> {{ widget_info.description }}</p>
                    <p><strong>Category:</strong> {{ category_name }}</p>
                    
                    <h6>Features:</h6>
                    <ul id="widget-features">
                        <!-- Features will be populated dynamically -->
                    </ul>
                    
                    <h6>Configuration Options:</h6>
                    <div id="config-documentation">
                        <!-- Configuration documentation will be generated -->
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<style>
.widget-preview-container {
    min-height: 200px;
    padding: 2rem;
    border: 2px dashed #dee2e6;
    border-radius: 8px;
    background: #fdfdfd;
}

#code-content {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 4px;
    padding: 1rem;
    font-size: 0.85rem;
    line-height: 1.4;
    max-height: 300px;
    overflow-y: auto;
}
</style>

<script>
const widgetCategory = '{{ category }}';
const widgetName = '{{ widget_name }}';
const defaultConfig = {{ widget_info.example_config | tojson }};

let currentConfig = {...defaultConfig};
let currentCodeType = 'basic';

// Initialize the page
document.addEventListener('DOMContentLoaded', function() {
    generateConfigControls();
    updateWidget();
    showCodeExample('basic');
});

function generateConfigControls() {
    const container = document.getElementById('config-controls');
    container.innerHTML = '';
    
    Object.entries(defaultConfig).forEach(([key, value]) => {
        const controlGroup = document.createElement('div');
        controlGroup.className = 'form-group';
        
        const label = document.createElement('label');
        label.textContent = key.replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
        label.setAttribute('for', `config-${key}`);
        
        let input;
        if (typeof value === 'boolean') {
            input = document.createElement('input');
            input.type = 'checkbox';
            input.className = 'form-check-input';
            input.checked = value;
            
            const wrapper = document.createElement('div');
            wrapper.className = 'form-check';
            wrapper.appendChild(input);
            wrapper.appendChild(label);
            controlGroup.appendChild(wrapper);
        } else if (typeof value === 'number') {
            input = document.createElement('input');
            input.type = 'number';
            input.className = 'form-control form-control-sm';
            input.value = value;
            
            controlGroup.appendChild(label);
            controlGroup.appendChild(input);
        } else if (Array.isArray(value)) {
            input = document.createElement('textarea');
            input.className = 'form-control form-control-sm';
            input.rows = 3;
            input.value = JSON.stringify(value, null, 2);
            
            controlGroup.appendChild(label);
            controlGroup.appendChild(input);
        } else {
            input = document.createElement('input');
            input.type = 'text';
            input.className = 'form-control form-control-sm';
            input.value = value;
            
            controlGroup.appendChild(label);
            controlGroup.appendChild(input);
        }
        
        input.id = `config-${key}`;
        input.addEventListener('change', () => updateConfig(key, input));
        
        container.appendChild(controlGroup);
    });
}

function updateConfig(key, input) {
    if (input.type === 'checkbox') {
        currentConfig[key] = input.checked;
    } else if (input.type === 'number') {
        currentConfig[key] = parseFloat(input.value) || 0;
    } else if (input.tagName === 'TEXTAREA') {
        try {
            currentConfig[key] = JSON.parse(input.value);
        } catch (e) {
            currentConfig[key] = input.value.split('\\n').filter(line => line.trim());
        }
    } else {
        currentConfig[key] = input.value;
    }
}

function updateWidget() {
    // In a real implementation, this would render the widget with the current config
    const preview = document.getElementById('widget-preview');
    preview.innerHTML = `
        <div class="text-center">
            <i class="fa fa-puzzle-piece fa-3x text-primary mb-3"></i>
            <h5>${widgetName}</h5>
            <p class="text-muted">Widget preview would appear here with current configuration</p>
            <code>${JSON.stringify(currentConfig, null, 2)}</code>
        </div>
    `;
}

function showCodeExample(type) {
    currentCodeType = type;
    
    // Update button states
    document.querySelectorAll('.btn-group .btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');
    
    // Generate code example
    fetch('{{ url_for("WidgetGalleryView.generate_code") }}', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            category: widgetCategory,
            widget_name: widgetName,
            config: currentConfig,
            usage_type: type
        })
    })
    .then(response => response.json())
    .then(data => {
        const codeContent = document.getElementById('code-content');
        if (data.success) {
            const exampleKey = `${type}_usage`;
            codeContent.textContent = data.code_examples[exampleKey] || 'No example available';
        } else {
            codeContent.textContent = `Error: ${data.error}`;
        }
    });
}

function copyCode() {
    const codeContent = document.getElementById('code-content');
    navigator.clipboard.writeText(codeContent.textContent);
    
    // Show feedback
    const btn = event.target;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fa fa-check"></i> Copied!';
    btn.classList.add('btn-success');
    btn.classList.remove('btn-secondary');
    
    setTimeout(() => {
        btn.innerHTML = originalText;
        btn.classList.remove('btn-success');
        btn.classList.add('btn-secondary');
    }, 2000);
}
</script>
{% endblock %}
'''

documentation_template = '''
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">
                        <i class="fa fa-book"></i> {{ documentation.widget_name }} Documentation
                    </h3>
                    <div class="card-tools">
                        <a href="{{ url_for('WidgetGalleryView.gallery') }}" class="btn btn-secondary btn-sm">
                            <i class="fa fa-arrow-left"></i> Back to Gallery
                        </a>
                    </div>
                </div>
                
                <div class="card-body">
                    <div class="documentation-content">
                        <!-- Widget Overview -->
                        <section class="doc-section">
                            <h4>Overview</h4>
                            <p class="lead">{{ documentation.description }}</p>
                            
                            {% if documentation.features %}
                            <h5>Features</h5>
                            <ul class="feature-list">
                                {% for feature in documentation.features %}
                                <li>{{ feature }}</li>
                                {% endfor %}
                            </ul>
                            {% endif %}
                        </section>
                        
                        <!-- Parameters -->
                        <section class="doc-section">
                            <h4>Parameters</h4>
                            <div class="table-responsive">
                                <table class="table table-striped">
                                    <thead>
                                        <tr>
                                            <th>Parameter</th>
                                            <th>Type</th>
                                            <th>Default</th>
                                            <th>Description</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {% for param in documentation.parameters %}
                                        <tr>
                                            <td><code>{{ param.name }}</code></td>
                                            <td><span class="badge badge-info">{{ param.type }}</span></td>
                                            <td><code>{{ param.default }}</code></td>
                                            <td>{{ param.description }}</td>
                                        </tr>
                                        {% endfor %}
                                    </tbody>
                                </table>
                            </div>
                        </section>
                        
                        <!-- Example Configuration -->
                        <section class="doc-section">
                            <h4>Example Configuration</h4>
                            <pre><code class="language-python">{{ documentation.example_config | tojson(indent=2) }}</code></pre>
                        </section>
                        
                        <!-- Usage Examples -->
                        <section class="doc-section">
                            <h4>Usage Examples</h4>
                            {% for example_name, example_code in documentation.code_examples.items() %}
                            <div class="code-example">
                                <h6>{{ example_name.replace('_', ' ').title() }}</h6>
                                <pre><code class="language-python">{{ example_code }}</code></pre>
                                <button type="button" class="btn btn-sm btn-outline-secondary" 
                                        onclick="copyCode(this)">
                                    <i class="fa fa-copy"></i> Copy
                                </button>
                            </div>
                            {% endfor %}
                        </section>
                        
                        <!-- Full Class Documentation -->
                        <section class="doc-section">
                            <h4>Class Documentation</h4>
                            <div class="class-doc">
                                <pre>{{ documentation.class_documentation }}</pre>
                            </div>
                        </section>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<style>
.documentation-content {
    max-width: 1200px;
}

.doc-section {
    margin-bottom: 3rem;
    padding-bottom: 2rem;
    border-bottom: 1px solid #e9ecef;
}

.doc-section:last-child {
    border-bottom: none;
}

.feature-list {
    columns: 2;
    column-gap: 2rem;
}

.code-example {
    margin-bottom: 2rem;
    position: relative;
}

.code-example button {
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
}

.class-doc {
    background: #f8f9fa;
    padding: 1rem;
    border-radius: 4px;
    border: 1px solid #e9ecef;
}

code {
    background: #f8f9fa;
    padding: 0.2rem 0.4rem;
    border-radius: 3px;
    font-size: 0.875rem;
}

pre code {
    background: transparent;
    padding: 0;
}
</style>

<script>
function copyCode(button) {
    const codeBlock = button.previousElementSibling.querySelector('code');
    navigator.clipboard.writeText(codeBlock.textContent);
    
    const originalText = button.innerHTML;
    button.innerHTML = '<i class="fa fa-check"></i> Copied!';
    button.classList.add('btn-success');
    button.classList.remove('btn-outline-secondary');
    
    setTimeout(() => {
        button.innerHTML = originalText;
        button.classList.remove('btn-success');
        button.classList.add('btn-outline-secondary');
    }, 2000);
}
</script>
{% endblock %}
'''

not_found_template = '''
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row justify-content-center">
        <div class="col-md-6">
            <div class="error-page">
                <div class="text-center">
                    <i class="fa fa-puzzle-piece fa-5x text-muted mb-4"></i>
                    <h2>Widget Not Found</h2>
                    <p class="lead">The requested widget could not be found in the gallery.</p>
                    <a href="{{ url_for('WidgetGalleryView.gallery') }}" class="btn btn-primary">
                        <i class="fa fa-arrow-left"></i> Back to Gallery
                    </a>
                </div>
            </div>
        </div>
    </div>
</div>

<style>
.error-page {
    padding: 4rem 2rem;
    text-align: center;
}
</style>
{% endblock %}
'''