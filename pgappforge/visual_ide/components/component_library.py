"""
Component Library for Visual IDE.

Manages the library of available components that can be used in the drag-and-drop
visual development interface.
"""

import json
import os
import logging
from typing import Dict, List, Optional, Any, Set
from pathlib import Path
from dataclasses import dataclass

from ..models.project_model import ComponentType, ComponentConfig, ComponentStyle, ComponentValidation

logger = logging.getLogger(__name__)


@dataclass
class ComponentTemplate:
    """Template definition for a component type."""
    component_type: ComponentType
    name: str
    description: str
    category: str
    icon: str
    default_properties: Dict[str, Any]
    configurable_properties: List[str]
    supported_events: List[str]
    requires_data_source: bool = False
    supports_children: bool = False
    max_children: Optional[int] = None
    required_permissions: List[str] = None
    flask_widget_class: Optional[str] = None
    template_code: str = ""


class ComponentLibrary:
    """
    Central library managing all available components for visual development.
    
    Provides component templates, validation, and metadata for the drag-and-drop
    interface. Components can be loaded from built-in definitions or custom
    component libraries.
    """
    
    def __init__(self, library_path: Optional[str] = None):
        self.library_path = Path(library_path) if library_path else None
        self.components: Dict[ComponentType, ComponentTemplate] = {}
        self.categories: Dict[str, List[ComponentType]] = {}
        
        # Load built-in components
        self._load_builtin_components()
        
        # Load custom components if path provided
        if self.library_path and self.library_path.exists():
            self._load_custom_components()
        
        logger.info(f"Component library loaded with {len(self.components)} components")
    
    def _load_builtin_components(self):
        """Load built-in PgForge component templates."""
        
        # Form Components
        self._register_component(ComponentTemplate(
            component_type=ComponentType.TEXT_FIELD,
            name="Text Field",
            description="Single-line text input field",
            category="Form",
            icon="text-field",
            default_properties={
                "maxlength": 255,
                "autocomplete": "on"
            },
            configurable_properties=["label", "placeholder", "required", "maxlength", "pattern"],
            supported_events=["onChange", "onFocus", "onBlur", "onKeyPress"],
            flask_widget_class="BS3TextFieldWidget",
            template_code="""
<div class="form-group">
    <label class="control-label">{{ label }}</label>
    <input type="text" class="form-control" name="{{ name }}" 
           placeholder="{{ placeholder }}" maxlength="{{ maxlength }}"
           {% if required %}required{% endif %}/>
</div>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.EMAIL_FIELD,
            name="Email Field", 
            description="Email input with validation",
            category="Form",
            icon="email",
            default_properties={
                "validation": "email"
            },
            configurable_properties=["label", "placeholder", "required"],
            supported_events=["onChange", "onFocus", "onBlur"],
            flask_widget_class="BS3TextFieldWidget",
            template_code="""
<div class="form-group">
    <label class="control-label">{{ label }}</label>
    <input type="email" class="form-control" name="{{ name }}" 
           placeholder="{{ placeholder }}"
           {% if required %}required{% endif %}/>
</div>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.PASSWORD_FIELD,
            name="Password Field",
            description="Password input field",
            category="Form",
            icon="password",
            default_properties={
                "minlength": 8
            },
            configurable_properties=["label", "required", "minlength"],
            supported_events=["onChange", "onFocus", "onBlur"],
            flask_widget_class="BS3PasswordFieldWidget",
            template_code="""
<div class="form-group">
    <label class="control-label">{{ label }}</label>
    <input type="password" class="form-control" name="{{ name }}" 
           minlength="{{ minlength }}"
           {% if required %}required{% endif %}/>
</div>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.TEXT_AREA,
            name="Text Area",
            description="Multi-line text input",
            category="Form",
            icon="textarea",
            default_properties={
                "rows": 4,
                "cols": 50
            },
            configurable_properties=["label", "placeholder", "required", "rows", "cols", "maxlength"],
            supported_events=["onChange", "onFocus", "onBlur"],
            flask_widget_class="BS3TextAreaFieldWidget",
            template_code="""
<div class="form-group">
    <label class="control-label">{{ label }}</label>
    <textarea class="form-control" name="{{ name }}" rows="{{ rows }}" 
              placeholder="{{ placeholder }}"
              {% if required %}required{% endif %}></textarea>
</div>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.SELECT_FIELD,
            name="Select Field",
            description="Dropdown selection field",
            category="Form",
            icon="select",
            default_properties={
                "multiple": False
            },
            configurable_properties=["label", "required", "multiple", "options"],
            supported_events=["onChange", "onFocus", "onBlur"],
            requires_data_source=True,
            flask_widget_class="BS3Select2FieldWidget",
            template_code="""
<div class="form-group">
    <label class="control-label">{{ label }}</label>
    <select class="form-control" name="{{ name }}"
            {% if required %}required{% endif %}
            {% if multiple %}multiple{% endif %}>
        {% for option in options %}
        <option value="{{ option.value }}">{{ option.label }}</option>
        {% endfor %}
    </select>
</div>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.CHECKBOX,
            name="Checkbox",
            description="Boolean checkbox input",
            category="Form",
            icon="checkbox",
            default_properties={
                "checked": False
            },
            configurable_properties=["label", "required", "checked"],
            supported_events=["onChange"],
            flask_widget_class="BS3CheckboxWidget",
            template_code="""
<div class="form-group">
    <div class="checkbox">
        <label>
            <input type="checkbox" name="{{ name }}" 
                   {% if checked %}checked{% endif %}
                   {% if required %}required{% endif %}/> {{ label }}
        </label>
    </div>
</div>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.DATE_PICKER,
            name="Date Picker",
            description="Date selection widget",
            category="Form", 
            icon="calendar",
            default_properties={
                "format": "%Y-%m-%d",
                "show_today": True
            },
            configurable_properties=["label", "required", "format", "min_date", "max_date"],
            supported_events=["onChange", "onFocus", "onBlur"],
            flask_widget_class="BS3DateTimePickerWidget",
            template_code="""
<div class="form-group">
    <label class="control-label">{{ label }}</label>
    <input type="date" class="form-control" name="{{ name }}" 
           {% if required %}required{% endif %}/>
</div>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.FILE_UPLOAD,
            name="File Upload",
            description="File upload component",
            category="Form",
            icon="upload",
            default_properties={
                "accept": "*/*",
                "multiple": False,
                "max_size": "10MB"
            },
            configurable_properties=["label", "required", "accept", "multiple", "max_size"],
            supported_events=["onChange", "onSelect"],
            flask_widget_class="BS3FileFieldWidget",
            template_code="""
<div class="form-group">
    <label class="control-label">{{ label }}</label>
    <input type="file" class="form-control" name="{{ name }}" 
           accept="{{ accept }}"
           {% if required %}required{% endif %}
           {% if multiple %}multiple{% endif %}/>
</div>"""
        ))
        
        # Display Components
        self._register_component(ComponentTemplate(
            component_type=ComponentType.LABEL,
            name="Label",
            description="Text label or heading",
            category="Display",
            icon="label",
            default_properties={
                "tag": "span",
                "text": "Label"
            },
            configurable_properties=["text", "tag", "css_class"],
            supported_events=[],
            template_code="""<{{ tag }} class="{{ css_class }}">{{ text }}</{{ tag }}>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.LINK,
            name="Link",
            description="Hyperlink component",
            category="Display",
            icon="link",
            default_properties={
                "url": "#",
                "text": "Link",
                "target": "_self"
            },
            configurable_properties=["text", "url", "target", "css_class"],
            supported_events=["onClick"],
            template_code="""<a href="{{ url }}" target="{{ target }}" class="{{ css_class }}">{{ text }}</a>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.CARD,
            name="Card",
            description="Bootstrap card container",
            category="Layout",
            icon="card",
            default_properties={
                "title": "Card Title",
                "show_header": True,
                "show_footer": False
            },
            configurable_properties=["title", "show_header", "show_footer", "css_class"],
            supported_events=[],
            supports_children=True,
            template_code="""
<div class="card {{ css_class }}">
    {% if show_header %}
    <div class="card-header">{{ title }}</div>
    {% endif %}
    <div class="card-body">
        {% for child in children %}{{ child }}{% endfor %}
    </div>
    {% if show_footer %}
    <div class="card-footer">Footer content</div>
    {% endif %}
</div>"""
        ))
        
        # Data Components
        self._register_component(ComponentTemplate(
            component_type=ComponentType.DATA_TABLE,
            name="Data Table",
            description="Interactive data table with sorting and filtering",
            category="Data",
            icon="table",
            default_properties={
                "sortable": True,
                "filterable": True,
                "paginated": True,
                "page_size": 20
            },
            configurable_properties=["sortable", "filterable", "paginated", "page_size", "columns"],
            supported_events=["onSort", "onFilter", "onPageChange", "onRowClick"],
            requires_data_source=True,
            flask_widget_class="ListWidget",
            template_code="""
<table class="table table-striped table-hover">
    <thead>
        <tr>
            {% for column in columns %}
            <th>{{ column.label }}</th>
            {% endfor %}
        </tr>
    </thead>
    <tbody>
        {% for row in data %}
        <tr>
            {% for column in columns %}
            <td>{{ row[column.field] }}</td>
            {% endfor %}
        </tr>
        {% endfor %}
    </tbody>
</table>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.CHART,
            name="Chart",
            description="Interactive charts and graphs",
            category="Data",
            icon="chart",
            default_properties={
                "chart_type": "line",
                "width": "100%",
                "height": "400px"
            },
            configurable_properties=["chart_type", "width", "height", "title", "x_axis", "y_axis"],
            supported_events=["onDataPointClick", "onZoom"],
            requires_data_source=True,
            template_code="""
<div class="chart-container" style="width: {{ width }}; height: {{ height }};">
    <canvas id="chart-{{ component_id }}"></canvas>
</div>"""
        ))
        
        # Layout Components
        self._register_component(ComponentTemplate(
            component_type=ComponentType.ROW,
            name="Row",
            description="Bootstrap grid row",
            category="Layout",
            icon="row",
            default_properties={
                "gutter": True
            },
            configurable_properties=["gutter", "css_class"],
            supported_events=[],
            supports_children=True,
            max_children=12,
            template_code="""
<div class="row {% if not gutter %}no-gutters{% endif %} {{ css_class }}">
    {% for child in children %}{{ child }}{% endfor %}
</div>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.COLUMN,
            name="Column",
            description="Bootstrap grid column",
            category="Layout",
            icon="column",
            default_properties={
                "size": 12,
                "md_size": None,
                "lg_size": None
            },
            configurable_properties=["size", "md_size", "lg_size", "offset", "css_class"],
            supported_events=[],
            supports_children=True,
            template_code="""
<div class="col-{{ size }}{% if md_size %} col-md-{{ md_size }}{% endif %}{% if lg_size %} col-lg-{{ lg_size }}{% endif %} {{ css_class }}">
    {% for child in children %}{{ child }}{% endfor %}
</div>"""
        ))
        
        self._register_component(ComponentTemplate(
            component_type=ComponentType.CONTAINER,
            name="Container",
            description="Bootstrap container",
            category="Layout",
            icon="container",
            default_properties={
                "fluid": False
            },
            configurable_properties=["fluid", "css_class"],
            supported_events=[],
            supports_children=True,
            template_code="""
<div class="container{% if fluid %}-fluid{% endif %} {{ css_class }}">
    {% for child in children %}{{ child }}{% endfor %}
</div>"""
        ))
        
        # Action Components
        self._register_component(ComponentTemplate(
            component_type=ComponentType.BUTTON,
            name="Button",
            description="Action button",
            category="Action",
            icon="button",
            default_properties={
                "text": "Button",
                "type": "button",
                "variant": "primary",
                "size": "md"
            },
            configurable_properties=["text", "type", "variant", "size", "disabled"],
            supported_events=["onClick"],
            template_code="""
<button type="{{ type }}" class="btn btn-{{ variant }} btn-{{ size }}" 
        {% if disabled %}disabled{% endif %}>{{ text }}</button>"""
        ))
        
        # Security Components
        self._register_component(ComponentTemplate(
            component_type=ComponentType.PERMISSION_GUARD,
            name="Permission Guard",
            description="Conditionally render based on user permissions",
            category="Security",
            icon="shield",
            default_properties={
                "required_permission": ""
            },
            configurable_properties=["required_permission", "fallback_content"],
            supported_events=[],
            supports_children=True,
            required_permissions=["can_view_permissions"],
            template_code="""
{% if current_user and current_user.has_permission('{{ required_permission }}') %}
    {% for child in children %}{{ child }}{% endfor %}
{% else %}
    {{ fallback_content }}
{% endif %}"""
        ))
    
    def _register_component(self, template: ComponentTemplate):
        """Register a component template in the library."""
        self.components[template.component_type] = template
        
        # Add to category index
        if template.category not in self.categories:
            self.categories[template.category] = []
        self.categories[template.category].append(template.component_type)
    
    def _load_custom_components(self):
        """Load custom component definitions from library path."""
        try:
            custom_files = list(self.library_path.glob("*.json"))
            
            for file_path in custom_files:
                with open(file_path, 'r') as f:
                    component_data = json.load(f)
                
                # Create template from JSON definition
                template = self._create_template_from_json(component_data)
                if template:
                    self._register_component(template)
            
            logger.info(f"Loaded {len(custom_files)} custom component files")
            
        except Exception as e:
            logger.error(f"Failed to load custom components: {e}")
    
    def _create_template_from_json(self, data: Dict[str, Any]) -> Optional[ComponentTemplate]:
        """Create ComponentTemplate from JSON definition."""
        try:
            return ComponentTemplate(
                component_type=ComponentType(data['component_type']),
                name=data['name'],
                description=data['description'],
                category=data['category'],
                icon=data['icon'],
                default_properties=data.get('default_properties', {}),
                configurable_properties=data.get('configurable_properties', []),
                supported_events=data.get('supported_events', []),
                requires_data_source=data.get('requires_data_source', False),
                supports_children=data.get('supports_children', False),
                max_children=data.get('max_children'),
                required_permissions=data.get('required_permissions'),
                flask_widget_class=data.get('flask_widget_class'),
                template_code=data.get('template_code', '')
            )
        except Exception as e:
            logger.error(f"Failed to create template from JSON: {e}")
            return None
    
    # Public API
    def get_component(self, component_type: ComponentType) -> Optional[ComponentTemplate]:
        """Get component template by type."""
        return self.components.get(component_type)
    
    def get_components_by_category(self, category: str) -> List[ComponentTemplate]:
        """Get all components in a category."""
        if category not in self.categories:
            return []
        
        return [self.components[comp_type] for comp_type in self.categories[category]]
    
    def get_all_components(self) -> Dict[ComponentType, ComponentTemplate]:
        """Get all available components."""
        return self.components.copy()
    
    def get_categories(self) -> List[str]:
        """Get all available categories."""
        return list(self.categories.keys())
    
    def search_components(self, query: str) -> List[ComponentTemplate]:
        """Search components by name or description."""
        query_lower = query.lower()
        results = []
        
        for template in self.components.values():
            if (query_lower in template.name.lower() or 
                query_lower in template.description.lower() or
                query_lower in template.category.lower()):
                results.append(template)
        
        return results
    
    def validate_component_config(self, component_type: ComponentType, 
                                 config: Dict[str, Any]) -> List[str]:
        """
        Validate component configuration against template.
        
        Returns:
            List of validation error messages
        """
        template = self.get_component(component_type)
        if not template:
            return [f"Unknown component type: {component_type}"]
        
        errors = []
        
        # Check required properties
        for prop in template.configurable_properties:
            if prop.endswith("*"):  # Required property convention
                prop_name = prop[:-1]
                if prop_name not in config:
                    errors.append(f"Required property missing: {prop_name}")
        
        # Check data source requirement
        if template.requires_data_source and not config.get('data_source'):
            errors.append("Component requires a data source")
        
        # Check children constraints
        if template.supports_children:
            children_count = len(config.get('children', []))
            if template.max_children and children_count > template.max_children:
                errors.append(f"Too many children: {children_count} > {template.max_children}")
        elif config.get('children'):
            errors.append("Component does not support children")
        
        return errors
    
    def create_component_instance(self, component_type: ComponentType,
                                component_id: str,
                                config: Optional[Dict[str, Any]] = None) -> Optional[ComponentConfig]:
        """
        Create a configured component instance from template.
        
        Args:
            component_type: Type of component to create
            component_id: Unique ID for the instance
            config: Configuration overrides
            
        Returns:
            Configured ComponentConfig instance
        """
        template = self.get_component(component_type)
        if not template:
            logger.error(f"Cannot create unknown component type: {component_type}")
            return None
        
        # Start with template defaults
        properties = template.default_properties.copy()
        
        # Apply config overrides
        if config:
            properties.update(config)
        
        # Create component configuration
        return ComponentConfig(
            component_id=component_id,
            component_type=component_type,
            label=properties.get('label', template.name),
            placeholder=properties.get('placeholder'),
            default_value=properties.get('default_value'),
            options=properties.get('options', []),
            data_source=properties.get('data_source'),
            properties=properties
        )
    
    def get_component_template_code(self, component_type: ComponentType) -> str:
        """Get the template code for a component type."""
        template = self.get_component(component_type)
        return template.template_code if template else ""
    
    def export_library(self, export_path: str) -> bool:
        """Export component library to JSON files."""
        try:
            export_dir = Path(export_path)
            export_dir.mkdir(parents=True, exist_ok=True)
            
            for comp_type, template in self.components.items():
                file_name = f"{comp_type.value.lower()}.json"
                file_path = export_dir / file_name
                
                template_data = {
                    'component_type': template.component_type.value,
                    'name': template.name,
                    'description': template.description,
                    'category': template.category,
                    'icon': template.icon,
                    'default_properties': template.default_properties,
                    'configurable_properties': template.configurable_properties,
                    'supported_events': template.supported_events,
                    'requires_data_source': template.requires_data_source,
                    'supports_children': template.supports_children,
                    'max_children': template.max_children,
                    'required_permissions': template.required_permissions,
                    'flask_widget_class': template.flask_widget_class,
                    'template_code': template.template_code
                }
                
                with open(file_path, 'w') as f:
                    json.dump(template_data, f, indent=2)
            
            logger.info(f"Exported {len(self.components)} components to {export_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to export component library: {e}")
            return False