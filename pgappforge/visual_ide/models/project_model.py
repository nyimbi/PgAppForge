"""
Project models for the Visual IDE.

Defines data structures for IDE projects, view definitions, component configurations,
and other visual development artifacts.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from enum import Enum
import json


class ViewType(Enum):
    """Supported view types in the Visual IDE."""
    MODEL_VIEW = "ModelView"
    BASE_VIEW = "BaseView" 
    MASTER_DETAIL_VIEW = "MasterDetailView"
    COMPACT_CRUD_VIEW = "CompactCRUDView"
    CHART_VIEW = "ChartView"
    FORM_VIEW = "FormView"
    LIST_VIEW = "ListView"
    DETAIL_VIEW = "DetailView"
    CUSTOM_VIEW = "CustomView"


class ComponentType(Enum):
    """Available component types for views."""
    # Form components
    TEXT_FIELD = "TextField"
    EMAIL_FIELD = "EmailField"
    PASSWORD_FIELD = "PasswordField"
    TEXT_AREA = "TextArea"
    SELECT_FIELD = "SelectField"
    CHECKBOX = "Checkbox"
    RADIO = "Radio"
    DATE_PICKER = "DatePicker"
    FILE_UPLOAD = "FileUpload"
    
    # Display components
    LABEL = "Label"
    LINK = "Link"
    IMAGE = "Image"
    DIVIDER = "Divider"
    CARD = "Card"
    TAB = "Tab"
    ACCORDION = "Accordion"
    
    # Data components
    DATA_TABLE = "DataTable"
    CHART = "Chart"
    GRAPH = "Graph"
    METRICS = "Metrics"
    
    # Layout components
    ROW = "Row"
    COLUMN = "Column"
    PANEL = "Panel"
    CONTAINER = "Container"
    GRID = "Grid"
    
    # Action components
    BUTTON = "Button"
    DROPDOWN = "Dropdown"
    MENU = "Menu"
    TOOLBAR = "Toolbar"
    
    # Security components
    PERMISSION_GUARD = "PermissionGuard"
    ROLE_GUARD = "RoleGuard"
    LOGIN_REQUIRED = "LoginRequired"


@dataclass
class ComponentPosition:
    """Position and layout information for a component."""
    x: int = 0
    y: int = 0
    width: int = 100
    height: int = 30
    z_index: int = 0
    row: Optional[int] = None
    column: Optional[int] = None
    span: int = 1


@dataclass
class ComponentStyle:
    """Styling configuration for a component."""
    css_classes: List[str] = field(default_factory=list)
    custom_css: Dict[str, str] = field(default_factory=dict)
    theme: Optional[str] = None
    variant: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None


@dataclass
class ComponentValidation:
    """Validation rules for form components."""
    required: bool = False
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    custom_validators: List[str] = field(default_factory=list)
    error_messages: Dict[str, str] = field(default_factory=dict)


@dataclass
class ComponentConfig:
    """Configuration for a component instance."""
    component_id: str
    component_type: ComponentType
    label: Optional[str] = None
    placeholder: Optional[str] = None
    default_value: Any = None
    options: List[Dict[str, Any]] = field(default_factory=list)
    data_source: Optional[str] = None
    position: ComponentPosition = field(default_factory=ComponentPosition)
    style: ComponentStyle = field(default_factory=ComponentStyle)
    validation: ComponentValidation = field(default_factory=ComponentValidation)
    permissions: List[str] = field(default_factory=list)
    events: Dict[str, str] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)
    children: List[str] = field(default_factory=list)  # Child component IDs


@dataclass
class ViewLayout:
    """Layout configuration for a view."""
    layout_type: str = "grid"  # grid, flex, absolute
    columns: int = 12
    rows: Optional[int] = None
    gap: int = 10
    padding: int = 20
    responsive_breakpoints: Dict[str, int] = field(default_factory=lambda: {
        "xs": 576, "sm": 768, "md": 992, "lg": 1200, "xl": 1400
    })


@dataclass
class ViewSecurity:
    """Security configuration for a view."""
    requires_login: bool = True
    required_permissions: List[str] = field(default_factory=list)
    required_roles: List[str] = field(default_factory=list)
    access_control: Optional[str] = None
    audit_log: bool = True


@dataclass
class ViewDefinition:
    """
    Complete definition of a visual view.
    
    Contains all information needed to generate code for a PgForge view
    including components, layout, security, and behavior configuration.
    """
    name: str
    view_type: ViewType
    model_name: Optional[str] = None
    base_permissions: List[str] = field(default_factory=lambda: ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete'])
    
    # Component hierarchy
    components: Dict[str, ComponentConfig] = field(default_factory=dict)
    root_components: List[str] = field(default_factory=list)  # Top-level component IDs
    
    # Layout and styling
    layout: ViewLayout = field(default_factory=ViewLayout)
    
    # Security configuration  
    security: ViewSecurity = field(default_factory=ViewSecurity)
    
    # View behavior
    list_columns: List[str] = field(default_factory=list)
    show_columns: List[str] = field(default_factory=list)
    add_columns: List[str] = field(default_factory=list)
    edit_columns: List[str] = field(default_factory=list)
    search_columns: List[str] = field(default_factory=list)
    
    # Custom methods and hooks
    custom_methods: Dict[str, str] = field(default_factory=dict)
    pre_hooks: Dict[str, List[str]] = field(default_factory=dict)
    post_hooks: Dict[str, List[str]] = field(default_factory=dict)
    
    # Database relationships
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    
    # API configuration
    enable_api: bool = True
    api_permissions: List[str] = field(default_factory=lambda: ['can_get', 'can_post', 'can_put', 'can_delete'])
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    def add_component(self, component: ComponentConfig, parent_id: Optional[str] = None):
        """Add a component to this view."""
        self.components[component.component_id] = component
        
        if parent_id:
            if parent_id in self.components:
                self.components[parent_id].children.append(component.component_id)
        else:
            self.root_components.append(component.component_id)
        
        self.modified_at = datetime.now()
    
    def remove_component(self, component_id: str) -> bool:
        """Remove a component and all its children."""
        if component_id not in self.components:
            return False
        
        component = self.components[component_id]
        
        # Remove all children recursively
        for child_id in component.children:
            self.remove_component(child_id)
        
        # Remove from parent's children list
        for comp in self.components.values():
            if component_id in comp.children:
                comp.children.remove(component_id)
        
        # Remove from root components if it's a root
        if component_id in self.root_components:
            self.root_components.remove(component_id)
        
        # Remove the component itself
        del self.components[component_id]
        self.modified_at = datetime.now()
        
        return True
    
    def get_component(self, component_id: str) -> Optional[ComponentConfig]:
        """Get a component by ID."""
        return self.components.get(component_id)
    
    def get_children(self, component_id: str) -> List[ComponentConfig]:
        """Get all child components of a component."""
        if component_id not in self.components:
            return []
        
        children = []
        for child_id in self.components[component_id].children:
            if child_id in self.components:
                children.append(self.components[child_id])
        
        return children
    
    def get_root_components(self) -> List[ComponentConfig]:
        """Get all root-level components."""
        return [self.components[comp_id] for comp_id in self.root_components 
                if comp_id in self.components]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'view_type': self.view_type.value,
            'model_name': self.model_name,
            'base_permissions': self.base_permissions,
            'components': {k: self._component_to_dict(v) for k, v in self.components.items()},
            'root_components': self.root_components,
            'layout': {
                'layout_type': self.layout.layout_type,
                'columns': self.layout.columns,
                'rows': self.layout.rows,
                'gap': self.layout.gap,
                'padding': self.layout.padding,
                'responsive_breakpoints': self.layout.responsive_breakpoints
            },
            'security': {
                'requires_login': self.security.requires_login,
                'required_permissions': self.security.required_permissions,
                'required_roles': self.security.required_roles,
                'access_control': self.security.access_control,
                'audit_log': self.security.audit_log
            },
            'list_columns': self.list_columns,
            'show_columns': self.show_columns,
            'add_columns': self.add_columns,
            'edit_columns': self.edit_columns,
            'search_columns': self.search_columns,
            'custom_methods': self.custom_methods,
            'pre_hooks': self.pre_hooks,
            'post_hooks': self.post_hooks,
            'relationships': self.relationships,
            'enable_api': self.enable_api,
            'api_permissions': self.api_permissions,
            'created_at': self.created_at.isoformat(),
            'modified_at': self.modified_at.isoformat(),
            'description': self.description,
            'tags': self.tags
        }
    
    def _component_to_dict(self, component: ComponentConfig) -> Dict[str, Any]:
        """Convert component to dictionary."""
        return {
            'component_id': component.component_id,
            'component_type': component.component_type.value,
            'label': component.label,
            'placeholder': component.placeholder,
            'default_value': component.default_value,
            'options': component.options,
            'data_source': component.data_source,
            'position': {
                'x': component.position.x,
                'y': component.position.y,
                'width': component.position.width,
                'height': component.position.height,
                'z_index': component.position.z_index,
                'row': component.position.row,
                'column': component.position.column,
                'span': component.position.span
            },
            'style': {
                'css_classes': component.style.css_classes,
                'custom_css': component.style.custom_css,
                'theme': component.style.theme,
                'variant': component.style.variant,
                'size': component.style.size,
                'color': component.style.color
            },
            'validation': {
                'required': component.validation.required,
                'min_length': component.validation.min_length,
                'max_length': component.validation.max_length,
                'pattern': component.validation.pattern,
                'custom_validators': component.validation.custom_validators,
                'error_messages': component.validation.error_messages
            },
            'permissions': component.permissions,
            'events': component.events,
            'properties': component.properties,
            'children': component.children
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ViewDefinition':
        """Create ViewDefinition from dictionary."""
        view = cls(
            name=data['name'],
            view_type=ViewType(data['view_type']),
            model_name=data.get('model_name'),
            base_permissions=data.get('base_permissions', []),
            root_components=data.get('root_components', []),
            list_columns=data.get('list_columns', []),
            show_columns=data.get('show_columns', []),
            add_columns=data.get('add_columns', []),
            edit_columns=data.get('edit_columns', []),
            search_columns=data.get('search_columns', []),
            custom_methods=data.get('custom_methods', {}),
            pre_hooks=data.get('pre_hooks', {}),
            post_hooks=data.get('post_hooks', {}),
            relationships=data.get('relationships', []),
            enable_api=data.get('enable_api', True),
            api_permissions=data.get('api_permissions', []),
            created_at=datetime.fromisoformat(data.get('created_at', datetime.now().isoformat())),
            modified_at=datetime.fromisoformat(data.get('modified_at', datetime.now().isoformat())),
            description=data.get('description', ''),
            tags=data.get('tags', [])
        )
        
        # Load layout
        if 'layout' in data:
            layout_data = data['layout']
            view.layout = ViewLayout(
                layout_type=layout_data.get('layout_type', 'grid'),
                columns=layout_data.get('columns', 12),
                rows=layout_data.get('rows'),
                gap=layout_data.get('gap', 10),
                padding=layout_data.get('padding', 20),
                responsive_breakpoints=layout_data.get('responsive_breakpoints', {})
            )
        
        # Load security
        if 'security' in data:
            security_data = data['security']
            view.security = ViewSecurity(
                requires_login=security_data.get('requires_login', True),
                required_permissions=security_data.get('required_permissions', []),
                required_roles=security_data.get('required_roles', []),
                access_control=security_data.get('access_control'),
                audit_log=security_data.get('audit_log', True)
            )
        
        # Load components
        if 'components' in data:
            for comp_id, comp_data in data['components'].items():
                component = cls._component_from_dict(comp_data)
                view.components[comp_id] = component
        
        return view
    
    @classmethod
    def _component_from_dict(cls, data: Dict[str, Any]) -> ComponentConfig:
        """Create ComponentConfig from dictionary."""
        position_data = data.get('position', {})
        style_data = data.get('style', {})
        validation_data = data.get('validation', {})
        
        return ComponentConfig(
            component_id=data['component_id'],
            component_type=ComponentType(data['component_type']),
            label=data.get('label'),
            placeholder=data.get('placeholder'),
            default_value=data.get('default_value'),
            options=data.get('options', []),
            data_source=data.get('data_source'),
            position=ComponentPosition(
                x=position_data.get('x', 0),
                y=position_data.get('y', 0),
                width=position_data.get('width', 100),
                height=position_data.get('height', 30),
                z_index=position_data.get('z_index', 0),
                row=position_data.get('row'),
                column=position_data.get('column'),
                span=position_data.get('span', 1)
            ),
            style=ComponentStyle(
                css_classes=style_data.get('css_classes', []),
                custom_css=style_data.get('custom_css', {}),
                theme=style_data.get('theme'),
                variant=style_data.get('variant'),
                size=style_data.get('size'),
                color=style_data.get('color')
            ),
            validation=ComponentValidation(
                required=validation_data.get('required', False),
                min_length=validation_data.get('min_length'),
                max_length=validation_data.get('max_length'),
                pattern=validation_data.get('pattern'),
                custom_validators=validation_data.get('custom_validators', []),
                error_messages=validation_data.get('error_messages', {})
            ),
            permissions=data.get('permissions', []),
            events=data.get('events', {}),
            properties=data.get('properties', {}),
            children=data.get('children', [])
        )


@dataclass  
class IDEProject:
    """
    Complete IDE project definition.
    
    Contains all views, configuration, and metadata for a visual development project.
    """
    name: str
    created_at: datetime
    version: str = "1.0.0"
    description: str = ""
    
    # Project configuration
    flask_config: Dict[str, Any] = field(default_factory=dict)
    database_config: Dict[str, Any] = field(default_factory=dict)
    security_config: Dict[str, Any] = field(default_factory=dict)
    
    # Views and components
    views: Dict[str, ViewDefinition] = field(default_factory=dict)
    shared_components: Dict[str, ComponentConfig] = field(default_factory=dict)
    
    # Project metadata
    author: str = ""
    license: str = "MIT"
    tags: List[str] = field(default_factory=list)
    
    # Build configuration
    build_config: Dict[str, Any] = field(default_factory=dict)
    deployment_config: Dict[str, Any] = field(default_factory=dict)
    
    # Last modification tracking
    modified_at: datetime = field(default_factory=datetime.now)
    
    def add_view(self, view: ViewDefinition):
        """Add a view to the project."""
        self.views[view.name] = view
        self.modified_at = datetime.now()
    
    def remove_view(self, view_name: str) -> bool:
        """Remove a view from the project."""
        if view_name in self.views:
            del self.views[view_name]
            self.modified_at = datetime.now()
            return True
        return False
    
    def get_view(self, view_name: str) -> Optional[ViewDefinition]:
        """Get a view by name."""
        return self.views.get(view_name)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'created_at': self.created_at.isoformat(),
            'version': self.version,
            'description': self.description,
            'flask_config': self.flask_config,
            'database_config': self.database_config,
            'security_config': self.security_config,
            'views': {k: v.to_dict() for k, v in self.views.items()},
            'shared_components': {k: self._component_to_dict(v) for k, v in self.shared_components.items()},
            'author': self.author,
            'license': self.license,
            'tags': self.tags,
            'build_config': self.build_config,
            'deployment_config': self.deployment_config,
            'modified_at': self.modified_at.isoformat()
        }
    
    def _component_to_dict(self, component: ComponentConfig) -> Dict[str, Any]:
        """Convert component to dictionary (reuse from ViewDefinition)."""
        return ViewDefinition._component_to_dict(None, component)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IDEProject':
        """Create IDEProject from dictionary."""
        project = cls(
            name=data['name'],
            created_at=datetime.fromisoformat(data['created_at']),
            version=data.get('version', '1.0.0'),
            description=data.get('description', ''),
            flask_config=data.get('flask_config', {}),
            database_config=data.get('database_config', {}),
            security_config=data.get('security_config', {}),
            author=data.get('author', ''),
            license=data.get('license', 'MIT'),
            tags=data.get('tags', []),
            build_config=data.get('build_config', {}),
            deployment_config=data.get('deployment_config', {}),
            modified_at=datetime.fromisoformat(data.get('modified_at', datetime.now().isoformat()))
        )
        
        # Load views
        if 'views' in data:
            for view_name, view_data in data['views'].items():
                project.views[view_name] = ViewDefinition.from_dict(view_data)
        
        # Load shared components
        if 'shared_components' in data:
            for comp_id, comp_data in data['shared_components'].items():
                project.shared_components[comp_id] = ViewDefinition._component_from_dict(comp_data)
        
        return project