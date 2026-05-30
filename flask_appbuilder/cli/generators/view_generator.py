"""
Beautiful View Generator for Flask-AppBuilder

Generates sophisticated, modern Flask-AppBuilder views with:
- Modern widget integration using the unified widget system
- Responsive layouts and advanced filtering
- Real-time features and interactive components
- Performance optimizations and caching
- Security and access control
- Multi-view type support (CRUD, Charts, Calendar, etc.)
"""

import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass
from jinja2 import Environment, BaseLoader, Template
import inflect

from .database_inspector import (
    EnhancedDatabaseInspector,
    TableInfo,
    ColumnInfo,
    RelationshipInfo,
    RelationshipType,
    ColumnType
)

logger = logging.getLogger(__name__)
p = inflect.engine()


@dataclass
class ViewGenerationConfig:
    """Configuration for view generation."""
    use_modern_widgets: bool = True
    generate_api_views: bool = True
    generate_chart_views: bool = True
    generate_calendar_views: bool = True
    generate_wizard_views: bool = True
    generate_report_views: bool = True
    
    # NEW: Master-Detail and Relationship Views
    generate_master_detail_views: bool = True
    generate_lookup_views: bool = True
    generate_reference_views: bool = True
    generate_relationship_views: bool = True
    
    # Inline formset configuration
    enable_inline_formsets: bool = True
    max_inline_forms: int = 50
    default_inline_forms: int = 3
    inline_form_layouts: List[str] = None  # ['stacked', 'tabular', 'accordion']
    
    # Other existing options
    enable_real_time: bool = True
    enable_caching: bool = True
    enable_search: bool = True
    enable_export: bool = True
    enable_bulk_operations: bool = True
    responsive_design: bool = True
    security_enabled: bool = True
    performance_optimizations: bool = True
    include_documentation: bool = True
    custom_templates: Optional[str] = None
    theme: str = 'modern'
    icon_set: str = 'fa'
    
    def __post_init__(self):
        """Initialize default values."""
        if self.inline_form_layouts is None:
            self.inline_form_layouts = ['stacked', 'tabular', 'accordion']


class BeautifulViewGenerator:
    """
    Beautiful view generator that creates modern Flask-AppBuilder views.

    Features:
    - Integration with unified modern widget system
    - Responsive, mobile-first layouts
    - Advanced filtering and search capabilities
    - Real-time updates with WebSocket support
    - Performance optimizations (pagination, caching)
    - Security features (field-level access control)
    - Multiple view types (CRUD, Charts, Calendar, Wizard, Report)
    - Export capabilities (PDF, Excel, CSV)
    - Bulk operations support
    - Custom templates and themes
    """

    def __init__(
        self,
        inspector: EnhancedDatabaseInspector,
        config: Optional[ViewGenerationConfig] = None
    ):
        """
        Initialize the view generator.

        Args:
            inspector: Enhanced database inspector instance
            config: View generation configuration
        """
        self.inspector = inspector
        self.config = config or ViewGenerationConfig()
        self.jinja_env = Environment(loader=BaseLoader())
        self.jinja_env.filters['repr'] = repr

        # Analysis cache
        self.database_analysis = None
        self.generated_views: Dict[str, Dict[str, str]] = {}
        self.generated_api_views: Dict[str, str] = {}
        self.template_registry: Dict[str, str] = {}

        logger.info("Beautiful view generator initialized")

    def generate_all_views(self, output_dir: str) -> Dict[str, Any]:
        """
        Generate all views for all tables in the database.

        Args:
            output_dir: Directory to write generated files

        Returns:
            Dictionary with generation results and statistics
        """
        results = {
            'generated_files': [],
            'view_statistics': {},
            'master_detail_patterns': {},
            'relationship_views': {},
            'errors': []
        }
        
        try:
            # Generate supporting files (templates, CSS, JS)
            supporting = self._generate_supporting_files()
            for fname, content in supporting.items():
                fpath = os.path.join(output_dir, fname)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, 'w') as f:
                    f.write(content)
            
            # Generate inline formset templates
            if self.config.enable_inline_formsets:
                self._generate_inline_formset_templates(output_dir)
            
            all_tables = self.inspector.get_all_tables()
            
            for table_name in all_tables:
                try:
                    table_info = self.inspector.analyze_table(table_name)
                    table_views = self.generate_table_views(table_info)
                    
                    # Write view files
                    for view_type, view_code in table_views.items():
                        filename = f"{table_name}_{view_type}.py"
                        filepath = os.path.join(output_dir, 'views', filename)
                        
                        with open(filepath, 'w') as f:
                            f.write(view_code)
                        
                        results['generated_files'].append(filepath)
                    
                    # Track statistics
                    results['view_statistics'][table_name] = {
                        'view_count': len(table_views),
                        'view_types': list(table_views.keys())
                    }
                    
                    # Track master-detail patterns
                    if hasattr(self.inspector, 'analyze_master_detail_patterns'):
                        master_detail_patterns = self.inspector.analyze_master_detail_patterns(table_name)
                        if master_detail_patterns:
                            results['master_detail_patterns'][table_name] = [
                                {
                                    'child_table': pattern.child_table,
                                    'layout': pattern.child_form_layout,
                                    'inline_suitable': pattern.is_suitable_for_inline
                                }
                                for pattern in master_detail_patterns
                            ]
                    
                    # Track relationship views
                    if hasattr(self.inspector, 'get_relationship_view_variations'):
                        variations = self.inspector.get_relationship_view_variations(table_name)
                        if any(variations.values()):
                            results['relationship_views'][table_name] = variations
                    
                except Exception as e:
                    error_msg = f"Error generating views for {table_name}: {str(e)}"
                    results['errors'].append(error_msg)
                    logger.error(error_msg)
            
            # Generate view registry
            registry_code = self._generate_view_registry(results)
            registry_path = os.path.join(output_dir, 'views', '__init__.py')
            with open(registry_path, 'w') as f:
                f.write(registry_code)
            results['generated_files'].append(registry_path)
            
        except Exception as e:
            results['errors'].append(f"Failed to generate views: {str(e)}")
            logger.error(f"Failed to generate views: {str(e)}")
        
        return results

    def generate_table_views(self, table_info: TableInfo) -> Dict[str, str]:
        """
        Generate all view types for a table.

        Args:
            table_info: Table information from database analysis

        Returns:
            Dictionary mapping view types to generated code
        """
        views = {}

        # Always generate ModelView
        views['model_view'] = self.generate_model_view(table_info)

        # Generate specialized views based on table characteristics
        if not table_info.is_association_table:
            # API View
            if self.config.generate_api_views:
                views['api_view'] = self.generate_api_view(table_info)

            # Chart View (if has numeric and date columns)
            if self.config.generate_chart_views and self._can_generate_charts(table_info):
                views['chart_view'] = self.generate_chart_view(table_info)

            # Calendar View (if has date columns)
            if self.config.generate_calendar_views and self._has_date_columns(table_info):
                views['calendar_view'] = self.generate_calendar_view(table_info)

            # Wizard View (for complex forms)
            if self.config.generate_wizard_views and self._needs_wizard_view(table_info):
                views['wizard_view'] = self.generate_wizard_view(table_info)

            # Report View
            if self.config.generate_report_views:
                views['report_view'] = self.generate_report_view(table_info)
            
            # NEW: Master-Detail Views
            if self.config.generate_master_detail_views:
                master_detail_views = self.generate_master_detail_views(table_info)
                views.update(master_detail_views)
            
            # NEW: Lookup View (for tables with multiple foreign keys)
            foreign_key_count = len([col for col in table_info.columns if col.foreign_key])
            if self.config.generate_lookup_views and foreign_key_count >= 2:
                lookup_view = self.generate_lookup_view(table_info)
                if lookup_view:
                    views['lookup_view'] = lookup_view
            
            # NEW: Reference Views (for each relationship)
            if self.config.generate_reference_views:
                reference_views = self.generate_reference_views(table_info)
                views.update(reference_views)
            
            # NEW: Relationship Navigation View (for complex relationships)
            relationships = self.inspector._analyze_relationships(table_info.name)
            if self.config.generate_relationship_views and len(relationships) > 1:
                nav_view = self.generate_relationship_navigation_view(table_info)
                if nav_view:
                    views['relationship_navigation_view'] = nav_view

        return views

    def generate_model_view(self, table_info: TableInfo) -> str:
        """Generate enhanced ModelView with modern widgets."""
        template_str = self._get_model_view_template()
        template = self.jinja_env.from_string(template_str)

        # Process columns for form widgets
        form_columns = self._process_form_columns(table_info.columns)
        list_columns = self._get_list_columns(table_info.columns)
        show_columns = self._get_show_columns(table_info.columns)
        search_columns = self._get_search_columns(table_info.columns)

        # Generate fieldsets for better form organization
        fieldsets = self._generate_fieldsets(table_info.columns)

        # Generate validation rules
        validators = self._generate_form_validators(table_info.columns)

        # Generate widget configurations
        widget_config = self._generate_widget_config(table_info.columns)

        # Generate security settings
        security_settings = self._generate_view_security(table_info)

        add_edit_columns = [col['name'] if isinstance(col, dict) else col.name for col in form_columns]
        context = {
            'table_info': table_info,
            'class_name': f"{self._to_pascal_case(table_info.name)}ModelView",
            'model_name': self._to_pascal_case(table_info.name),
            'form_columns': form_columns,
            'add_columns': add_edit_columns,
            'edit_columns': add_edit_columns,
            'list_columns': list_columns,
            'show_columns': show_columns,
            'search_columns': search_columns,
            'fieldsets': fieldsets,
            'validators': validators,
            'widget_config': widget_config,
            'security_settings': security_settings,
            'relationships': table_info.relationships,
            'config': self.config,
            'icon': table_info.icon,
            'performance_settings': self._generate_performance_settings(table_info),
            'export_settings': self._generate_export_settings(table_info),
            'timestamp': datetime.now().isoformat()
        }

        return template.render(**context)

    def generate_api_view(self, table_info: TableInfo) -> str:
        """Generate REST API view with OpenAPI documentation."""
        template_str = self._get_api_view_template()
        template = self.jinja_env.from_string(template_str)

        # Generate serialization schema
        serialization_fields = self._get_serialization_fields(table_info.columns)

        # Generate API endpoints
        endpoints = self._generate_api_endpoints(table_info)

        context = {
            'table_info': table_info,
            'class_name': f"{self._to_pascal_case(table_info.name)}Api",
            'model_name': self._to_pascal_case(table_info.name),
            'serialization_fields': serialization_fields,
            'endpoints': endpoints,
            'security_settings': self._generate_api_security(table_info),
            'config': self.config,
            'timestamp': datetime.now().isoformat()
        }

        return template.render(**context)

    def generate_chart_view(self, table_info: TableInfo) -> str:
        """Generate chart view with advanced charting capabilities."""
        template_str = self._get_chart_view_template()
        template = self.jinja_env.from_string(template_str)

        # Find numeric and date columns for charting
        numeric_columns = [col for col in table_info.columns
                          if col.category == ColumnType.NUMERIC]
        date_columns = [col for col in table_info.columns
                       if col.category == ColumnType.DATE_TIME]

        # Generate chart configurations
        chart_configs = self._generate_chart_configs(numeric_columns, date_columns)

        context = {
            'table_info': table_info,
            'class_name': f"{self._to_pascal_case(table_info.name)}ChartView",
            'model_name': self._to_pascal_case(table_info.name),
            'numeric_columns': numeric_columns,
            'date_columns': date_columns,
            'chart_configs': chart_configs,
            'config': self.config,
            'timestamp': datetime.now().isoformat()
        }

        return template.render(**context)

    def generate_calendar_view(self, table_info: TableInfo) -> str:
        """Generate calendar view for date-based data."""
        template_str = self._get_calendar_view_template()
        template = self.jinja_env.from_string(template_str)

        date_columns = [col for col in table_info.columns
                       if col.category == ColumnType.DATE_TIME]
        event_fields = self._determine_event_fields(table_info.columns)

        context = {
            'table_info': table_info,
            'class_name': f"{self._to_pascal_case(table_info.name)}CalendarView",
            'model_name': self._to_pascal_case(table_info.name),
            'date_columns': date_columns,
            'event_fields': event_fields,
            'config': self.config,
            'timestamp': datetime.now().isoformat()
        }

        return template.render(**context)

    def generate_wizard_view(self, table_info: TableInfo) -> str:
        """Generate wizard view for complex multi-step forms."""
        template_str = self._get_wizard_view_template()
        template = self.jinja_env.from_string(template_str)

        # Create wizard steps
        steps = self._create_wizard_steps(table_info.columns)

        non_pk = [col for col in table_info.columns if not col.primary_key]
        required_cols = [col for col in non_pk if not col.nullable]
        optional_cols = [col for col in non_pk if col.nullable]

        def _wtf(col):
            t = str(col.type).lower()
            if 'bool' in t: return 'BooleanField'
            if 'int' in t: return 'IntegerField'
            if 'text' in t: return 'TextAreaField'
            if 'date' in t or 'time' in t: return 'DateTimeLocalField'
            return 'StringField'

        req_ctx = [{'name': c.name, 'display_name': c.display_name or c.name,
                    'wtf_field_type': _wtf(c), 'max_length': getattr(c, 'length', None)}
                   for c in required_cols]
        opt_ctx = [{'name': c.name, 'display_name': c.display_name or c.name,
                    'wtf_field_type': _wtf(c), 'max_length': getattr(c, 'length', None)}
                   for c in optional_cols]

        context = {
            'table_info': table_info,
            'class_name': f"{self._to_pascal_case(table_info.name)}WizardView",
            'model_name': self._to_pascal_case(table_info.name),
            'steps': steps,
            'required_columns': req_ctx,
            'optional_columns': opt_ctx,
            'relationships': [
                {
                    'property_name': r.name,
                    'display_name': r.display_name or r.name.replace('_', ' ').title(),
                    'target_model': self._to_pascal_case(r.remote_table),
                }
                for r in table_info.relationships
            ],
            'config': self.config,
            'timestamp': datetime.now().isoformat(),
        }

        return template.render(**context)

    def generate_report_view(self, table_info: TableInfo) -> str:
        """Generate report view with export capabilities."""
        template_str = self._get_report_view_template()
        template = self.jinja_env.from_string(template_str)

        # Generate report columns and groupings
        report_columns = self._get_report_columns(table_info.columns)
        grouping_options = self._get_grouping_options(table_info.columns)
        aggregation_options = self._get_aggregation_options(table_info.columns)

        context = {
            'table_info': table_info,
            'class_name': f"{self._to_pascal_case(table_info.name)}ReportView",
            'model_name': self._to_pascal_case(table_info.name),
            'report_columns': report_columns,
            'grouping_options': grouping_options,
            'aggregation_options': aggregation_options,
            'config': self.config,
            'timestamp': datetime.now().isoformat()
        }

        return template.render(**context)

    def generate_master_detail_views(self, table_info: TableInfo) -> Dict[str, str]:
        """
        Generate master-detail views for a table.
        
        Args:
            table_info: Parent table information
            
        Returns:
            Dictionary mapping child tables to generated master-detail view code
        """
        views = {}
        
        # Get master-detail patterns
        master_detail_patterns = self.inspector.analyze_master_detail_patterns(table_info.name)
        
        for pattern in master_detail_patterns:
            view_code = self._generate_master_detail_view(table_info, pattern)
            view_name = f"{self._to_pascal_case(table_info.name)}{self._to_pascal_case(pattern.child_table)}MasterDetailView"
            views[view_name] = view_code
            
        return views
    
    def generate_lookup_view(self, table_info: TableInfo) -> str:
        """
        Generate a lookup view for tables with multiple foreign keys.
        
        Args:
            table_info: Table information
            
        Returns:
            Generated lookup view code
        """
        relationships = self.inspector._analyze_relationships(table_info.name)
        foreign_keys = [col for col in table_info.columns if col.foreign_key]
        
        if len(foreign_keys) < 2:
            return ""
            
        template = self._get_lookup_view_template()
        
        return self.jinja_env.from_string(template).render(
            table_info=table_info,
            relationships=relationships,
            foreign_keys=foreign_keys,
            class_name=f"{self._to_pascal_case(table_info.name)}LookupView",
            model_name=self._to_pascal_case(table_info.name)
        )
    
    def generate_reference_views(self, table_info: TableInfo) -> Dict[str, str]:
        """
        Generate reference views for each significant relationship.
        
        Args:
            table_info: Table information
            
        Returns:
            Dictionary mapping reference types to generated view code
        """
        views = {}
        relationships = self.inspector._analyze_relationships(table_info.name)
        
        for relationship in relationships:
            if relationship.type in [RelationshipType.MANY_TO_ONE, RelationshipType.ONE_TO_ONE]:
                view_code = self._generate_reference_view(table_info, relationship)
                view_name = f"{self._to_pascal_case(table_info.name)}By{self._to_pascal_case(relationship.remote_table)}View"
                views[view_name] = view_code
                
        return views
    
    def generate_relationship_navigation_view(self, table_info: TableInfo) -> str:
        """
        Generate a relationship navigation view for complex related data.
        
        Args:
            table_info: Table information
            
        Returns:
            Generated relationship navigation view code
        """
        relationships = self.inspector._analyze_relationships(table_info.name)
        
        if len(relationships) <= 1:
            return ""
            
        template = self._get_relationship_navigation_template()
        
        return self.jinja_env.from_string(template).render(
            table_info=table_info,
            relationships=relationships,
            class_name=f"{self._to_pascal_case(table_info.name)}RelationshipView",
            model_name=self._to_pascal_case(table_info.name)
        )

    def _process_form_columns(self, columns: List[ColumnInfo]) -> List[Dict[str, Any]]:
        """Process columns for form display with modern widgets."""
        form_columns = []

        for column in columns:
            if not column.primary_key:  # Skip primary keys in forms
                form_col = {
                    'name': column.name,
                    'display_name': column.display_name,
                    'description': column.description,
                    'widget': self._get_modern_widget(column),
                    'validators': column.validation_rules,
                    'required': not column.nullable,
                    'sensitive': self._is_sensitive_field(column.name),
                    'category': column.category.value
                }
                form_columns.append(form_col)

        return form_columns

    def _get_modern_widget(self, column: ColumnInfo) -> Dict[str, Any]:
        """Get modern widget configuration for a column."""
        if not self.config.use_modern_widgets:
            return {'type': 'BS3TextFieldWidget', 'config': {}}

        widget_type = column.widget_type
        widget_config = {}

        # Enhanced widget configurations based on column type
        if widget_type == 'ColorPickerWidget':
            widget_config = {
                'show_palette': True,
                'show_history': True,
                'custom_colors': ['#ff5733', '#33ff57', '#3357ff']
            }
        elif widget_type == 'CodeEditorWidget':
            widget_config = {
                'language': self._detect_code_language(column.name),
                'theme': 'vs-light',
                'line_numbers': True,
                'minimap': True
            }
        elif widget_type == 'AdvancedChartsWidget':
            widget_config = {
                'chart_type': 'line',
                'responsive': True,
                'animation': True,
                'zoom_enabled': True
            }
        elif widget_type == 'GPSTrackerWidget':
            widget_config = {
                'map_provider': 'openstreetmap',
                'enable_tracking': True,
                'enable_routes': True
            }
        elif widget_type == 'FileUploadWidget':
            widget_config = {
                'multiple': column.name.endswith('s'),
                'allowed_extensions': self._get_allowed_extensions(column.name),
                'max_size': '10MB'
            }
        elif widget_type == 'TagInputWidget':
            widget_config = {
                'max_tags': 10,
                'sortable': True,
                'allow_duplicates': False
            }

        return {
            'type': widget_type,
            'config': widget_config
        }

    def _generate_fieldsets(self, columns: List[ColumnInfo]) -> List[Dict[str, Any]]:
        """Generate logical fieldsets for form organization."""
        fieldsets = {
            'Basic Information': [],
            'Contact Details': [],
            'Location': [],
            'Dates & Times': [],
            'Financial': [],
            'Status & Settings': [],
            'Media & Files': [],
            'Notes & Description': [],
            'Relationships': [],
            'System Fields': []
        }

        fieldset_icons = {
            'Basic Information': 'fa-info-circle',
            'Contact Details': 'fa-address-book',
            'Location': 'fa-map-marker',
            'Dates & Times': 'fa-calendar',
            'Financial': 'fa-dollar-sign',
            'Status & Settings': 'fa-cogs',
            'Media & Files': 'fa-images',
            'Notes & Description': 'fa-sticky-note',
            'Relationships': 'fa-link',
            'System Fields': 'fa-database'
        }

        for column in columns:
            if column.primary_key:
                continue

            name = column.name.lower()

            # Categorize columns into fieldsets
            if column.foreign_key:
                fieldsets['Relationships'].append(column.name)
            elif any(word in name for word in ['created_at', 'updated_at', 'created_by', 'updated_by']):
                fieldsets['System Fields'].append(column.name)
            elif any(word in name for word in ['email', 'phone', 'contact', 'mobile']):
                fieldsets['Contact Details'].append(column.name)
            elif any(word in name for word in ['address', 'city', 'state', 'country', 'postal', 'zip']):
                fieldsets['Location'].append(column.name)
            elif column.category == ColumnType.DATE_TIME:
                fieldsets['Dates & Times'].append(column.name)
            elif any(word in name for word in ['amount', 'price', 'cost', 'salary', 'fee']):
                fieldsets['Financial'].append(column.name)
            elif any(word in name for word in ['status', 'active', 'enabled', 'type']):
                fieldsets['Status & Settings'].append(column.name)
            elif any(word in name for word in ['photo', 'image', 'file', 'document']):
                fieldsets['Media & Files'].append(column.name)
            elif any(word in name for word in ['note', 'description', 'comment', 'detail']):
                fieldsets['Notes & Description'].append(column.name)
            else:
                fieldsets['Basic Information'].append(column.name)

        # Convert to list format with icons
        result = []
        for fieldset_name, fields in fieldsets.items():
            if fields:  # Only include non-empty fieldsets
                result.append({
                    'name': fieldset_name,
                    'fields': fields,
                    'icon': fieldset_icons.get(fieldset_name, 'fa-folder'),
                    'collapsible': fieldset_name in ['System Fields', 'Notes & Description']
                })

        return result

    def _generate_widget_config(self, columns: List[ColumnInfo]) -> Dict[str, Dict[str, Any]]:
        """Generate widget configurations for all columns."""
        config = {}
        for column in columns:
            if not column.primary_key:
                widget_info = self._get_modern_widget(column)
                config[column.name] = widget_info
        return config

    def _generate_view_security(self, table_info: TableInfo) -> Dict[str, Any]:
        """Generate security settings for views."""
        if not self.config.security_enabled:
            return {}

        sensitive_fields = [col.name for col in table_info.columns
                          if self._is_sensitive_field(col.name)]

        return {
            'security_level': table_info.security_level,
            'sensitive_fields': sensitive_fields,
            'requires_auth': table_info.security_level in ['HIGH', 'MEDIUM'],
            'field_permissions': {
                field: ['Admin', 'Manager'] for field in sensitive_fields
            },
            'audit_changes': table_info.security_level == 'HIGH'
        }

    def _generate_performance_settings(self, table_info: TableInfo) -> Dict[str, Any]:
        """Generate performance optimization settings."""
        if not self.config.performance_optimizations:
            return {}

        settings = {
            'page_size': min(50, max(10, 1000 // len(table_info.columns))),
            'lazy_loading': True,
            'enable_caching': self.config.enable_caching,
            'cache_timeout': 300,
            'optimize_queries': True
        }

        # Adjust based on estimated table size
        if table_info.estimated_rows > 10000:
            settings['page_size'] = min(settings['page_size'], 25)
            settings['enable_search_index'] = True

        return settings

    def _can_generate_charts(self, table_info: TableInfo) -> bool:
        """Check if table can generate meaningful charts."""
        has_numeric = any(col.category == ColumnType.NUMERIC for col in table_info.columns)
        has_date = any(col.category == ColumnType.DATE_TIME for col in table_info.columns)
        return has_numeric and has_date

    def _has_date_columns(self, table_info: TableInfo) -> bool:
        """Check if table has date columns for calendar view."""
        return any(col.category == ColumnType.DATE_TIME for col in table_info.columns)

    def _needs_wizard_view(self, table_info: TableInfo) -> bool:
        """Check if table needs a wizard view (complex form)."""
        non_system_columns = [col for col in table_info.columns
                             if not col.primary_key and
                             col.name not in ['created_at', 'updated_at', 'created_by', 'updated_by']]
        return len(non_system_columns) > 8

    def _get_list_columns(self, columns: List[ColumnInfo]) -> List[str]:
        """Get columns to display in list view."""
        list_cols = []

        # Add name/title columns first
        for col in columns:
            if any(word in col.name.lower() for word in ['name', 'title', 'email']):
                list_cols.append(col.name)

        # Add other important columns
        for col in columns:
            if (not col.primary_key and
                col.name not in list_cols and
                len(list_cols) < 6 and
                col.category not in [ColumnType.BINARY, ColumnType.JSON]):
                list_cols.append(col.name)

        return list_cols

    def _get_show_columns(self, columns: List[ColumnInfo]) -> List[str]:
        """Get columns to display in show view."""
        return [col.name for col in columns
                if col.category != ColumnType.BINARY]  # Exclude binary fields

    def _get_search_columns(self, columns: List[ColumnInfo]) -> List[str]:
        """Get searchable columns."""
        searchable = []
        for col in columns:
            if (col.category in [ColumnType.TEXT] and
                not self._is_sensitive_field(col.name) and
                col.name not in ['id', 'password', 'hash']):
                searchable.append(col.name)
        return searchable

    def _to_pascal_case(self, snake_str: str) -> str:
        """Convert snake_case to PascalCase."""
        return ''.join(word.capitalize() for word in snake_str.split('_'))

    def _is_sensitive_field(self, field_name: str) -> bool:
        """Check if a field contains sensitive data."""
        sensitive_patterns = [
            'password', 'pwd', 'secret', 'token', 'key', 'ssn',
            'social_security', 'credit_card', 'bank_account'
        ]
        field_lower = field_name.lower()
        return any(pattern in field_lower for pattern in sensitive_patterns)

    def _detect_code_language(self, column_name: str) -> str:
        """Detect programming language from column name."""
        name_lower = column_name.lower()
        if any(word in name_lower for word in ['sql', 'query']):
            return 'sql'
        elif any(word in name_lower for word in ['python', 'py']):
            return 'python'
        elif any(word in name_lower for word in ['json']):
            return 'json'
        elif any(word in name_lower for word in ['html']):
            return 'html'
        elif any(word in name_lower for word in ['css']):
            return 'css'
        else:
            return 'javascript'

    def _get_allowed_extensions(self, column_name: str) -> List[str]:
        """Get allowed file extensions based on column name."""
        name_lower = column_name.lower()
        if any(word in name_lower for word in ['image', 'photo', 'picture']):
            return ['jpg', 'jpeg', 'png', 'gif', 'webp']
        elif any(word in name_lower for word in ['document', 'doc']):
            return ['pdf', 'doc', 'docx', 'txt']
        elif any(word in name_lower for word in ['video']):
            return ['mp4', 'avi', 'mov', 'webm']
        else:
            return ['pdf', 'doc', 'docx', 'jpg', 'png', 'txt']

    def _generate_supporting_files(self) -> Dict[str, str]:
        """Generate supporting files for the views."""
        files = {}

        # Generate view registry
        files['__init__.py'] = self._generate_view_registry()

        # Generate base templates if custom templates enabled
        if self.config.custom_templates:
            files['base_template.html'] = self._generate_base_template()

        # Generate JavaScript for real-time features
        if self.config.enable_real_time:
            files['realtime.js'] = self._generate_realtime_js()

        # Generate CSS for modern styling
        files['modern_styles.css'] = self._generate_modern_css()

        return files

    def _get_model_view_template(self) -> str:
        """Get ModelView template with modern widgets."""
        return '''
{% if config.include_documentation %}
"""
{{ table_info.display_name }} Model View

{{ table_info.description }}

Generated: {{ timestamp }}
Features: Modern widgets, responsive design, security controls
"""
{% endif %}

from flask_appbuilder import ModelView
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.widgets import BS3TextFieldWidget, BS3TextAreaFieldWidget, Select2Widget  # noqa: F401
from flask_babel import lazy_gettext as _
from wtforms.validators import {% for validator in validators %}{{ validator }}{% if not loop.last %}, {% endif %}{% endfor %}

from ..models import {{ model_name }}


class {{ class_name }}(ModelView):
    """{{ table_info.display_name }} management view with modern widgets."""

    datamodel = SQLAInterface({{ model_name }})

    # Basic configuration
    list_title = _('{{ table_info.display_name }} List')
    show_title = _('{{ table_info.display_name }} Details')
    add_title = _('Add {{ table_info.display_name }}')
    edit_title = _('Edit {{ table_info.display_name }}')

    # Column configurations
    list_columns = {{ list_columns }}
    show_columns = {{ show_columns }}
    add_columns = {{ add_columns }}
    edit_columns = {{ edit_columns }}

    {% if search_columns %}
    search_columns = {{ search_columns }}
    {% endif %}

    # Modern fieldsets with icons
    {% if fieldsets %}
    add_fieldsets = [
        {% for fieldset in fieldsets %}
        ('{{ fieldset.name }}', {
            'fields': {{ fieldset.fields }},
            'expanded': {{ 'True' if not fieldset.collapsible else 'False' }},
            'description': _('{{ fieldset.name }} information'),
        }),
        {% endfor %}
    ]
    edit_fieldsets = add_fieldsets
    show_fieldsets = add_fieldsets
    {% endif %}

    # Modern widget configuration
    {% for column_name, widget_info in widget_config.items() %}
    {{ column_name }}_widget = {{ widget_info.type }}(
        {% for key, value in widget_info.config.items() %}
        {{ key }}={{ value|repr }}{% if not loop.last %},{% endif %}
        {% endfor %}
    )
    {% endfor %}

    # Labels and descriptions
    {% for column in form_columns %}
    label_columns = {**getattr(label_columns, 'copy', lambda: {})(),
                    '{{ column.name }}': _('{{ column.display_name }}')}
    description_columns = {**getattr(description_columns, 'copy', lambda: {})(),
                          '{{ column.name }}': _('{{ column.description }}')}
    {% endfor %}

    {% if config.performance_optimizations %}
    # Performance settings
    {% if performance_settings %}
    page_size = {{ performance_settings.page_size }}
    max_page_size = {{ performance_settings.page_size * 2 }}
    {% endif %}
    {% endif %}

    {% if config.enable_export %}
    # Export configuration
    export_types = ['csv', 'xlsx', 'pdf']
    {% endif %}

    {% if config.enable_search %}
    # Advanced search
    search_form_query_rel_fields = {
        {% for rel in relationships %}
        '{{ rel.name }}': [['name', FilterStartsWith, '']],
        {% endfor %}
    }
    {% endif %}

    {% if security_settings and security_settings.requires_auth %}
    # Security configuration
    base_permissions = ['can_list', 'can_show']
    {% if security_settings.sensitive_fields %}

    def pre_add(self, item):
        """Pre-process before adding item."""
        # Add any security checks here
        pass

    def pre_update(self, item):
        """Pre-process before updating item."""
        # Add any security checks here
        pass
    {% endif %}
    {% endif %}

    {% if config.responsive_design %}
    # Responsive design configuration
    list_template = 'appbuilder/general/model/list_responsive.html'
    show_template = 'appbuilder/general/model/show_responsive.html'
    add_template = 'appbuilder/general/model/add_responsive.html'
    edit_template = 'appbuilder/general/model/edit_responsive.html'
    {% endif %}
        '''.strip()

    def _get_api_view_template(self) -> str:
        """Get API view template."""
        return '''
"""
{{ table_info.display_name }} REST API

Provides RESTful endpoints for {{ table_info.display_name }} management.
Generated: {{ timestamp }}
"""

from flask_appbuilder import ModelRestApi
from flask_appbuilder.api import BaseApi, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import protect
from marshmallow import Schema, fields

from ..models import {{ model_name }}


class {{ model_name }}Schema(Schema):
    """{{ table_info.display_name }} serialization schema."""

    {% for field in serialization_fields %}
    {{ field.name }} = fields.{{ field.type }}({{ field.args }})
    {% endfor %}


class {{ class_name }}(ModelRestApi):
    """{{ table_info.display_name }} REST API endpoints."""

    datamodel = SQLAInterface({{ model_name }})

    # Serialization
    add_model_schema = {{ model_name }}Schema()
    edit_model_schema = {{ model_name }}Schema()
    show_model_schema = {{ model_name }}Schema()
    list_model_schema = {{ model_name }}Schema()

    # Column permissions
    {% if security_settings %}
    {% if security_settings.sensitive_fields %}
    list_exclude_columns = {{ security_settings.sensitive_fields }}
    show_exclude_columns = {{ security_settings.sensitive_fields }}
    {% endif %}
    {% endif %}

    {% for endpoint in endpoints %}
    {{ endpoint.code }}
    {% endfor %}
        '''.strip()

    def _generate_view_registry(self, results=None) -> str:
        """Generate view registry __init__.py."""
        return '''
"""
Generated Views Registry

Auto-generated view imports and registrations.
Generated: {timestamp}
"""

# Import all generated views
{view_imports}

# View registry for AppBuilder
VIEWS = [
    {view_registrations}
]

def register_views(appbuilder):
    """Register all views with AppBuilder."""
    for view_class, name, category in VIEWS:
        appbuilder.add_view(
            view_class,
            name,
            category=category,
            icon=getattr(view_class, 'default_icon', 'fa-table')
        )
        '''.format(
            timestamp=datetime.now().isoformat(),
            view_imports='# Generated imports will be added here',
            view_registrations='# Generated registrations will be added here'
        ).strip()

    def _generate_base_template(self) -> str:
        """Generate base template for views."""
        return '''
{% extends "appbuilder/baselayout.html" %}

{% block head_css %}
{{ super() }}
<link rel="stylesheet" href="{{ url_for('static', filename='css/modern_styles.css') }}">
{% endblock %}

{% block tail_js %}
{{ super() }}
<script src="{{ url_for('static', filename='js/realtime.js') }}"></script>
{% endblock %}

{% block content %}
<div class="modern-view-container">
    {% block modern_content %}{% endblock %}
</div>
{% endblock %}
        '''.strip()

    def _generate_realtime_js(self) -> str:
        """Generate JavaScript for real-time features."""
        return '''
// Real-time updates for Flask-AppBuilder views
// Generated: {timestamp}

class RealtimeUpdater {{
    constructor(tableName, viewType = 'list') {{
        this.tableName = tableName;
        this.viewType = viewType;
        this.socket = null;
        this.init();
    }}

    init() {{
        if (typeof io !== 'undefined') {{
            this.socket = io();
            this.setupListeners();
        }}
    }}

    setupListeners() {{
        this.socket.on(`${{this.tableName}}_updated`, (data) => {{
            this.handleUpdate(data);
        }});

        this.socket.on(`${{this.tableName}}_deleted`, (data) => {{
            this.handleDelete(data);
        }});
    }}

    handleUpdate(data) {{
        if (this.viewType === 'list') {{
            this.updateListRow(data);
        }}
    }}

    updateListRow(data) {{
        const row = document.querySelector(`[data-id="${{data.id}}"]`);
        if (row) {{
            // Update row content
            this.flashRow(row);
        }}
    }}

    flashRow(row) {{
        row.classList.add('table-row-updated');
        setTimeout(() => {{
            row.classList.remove('table-row-updated');
        }}, 2000);
    }}
}}

// Auto-initialize for tables with real-time enabled
document.addEventListener('DOMContentLoaded', function() {{
    const realtimeElements = document.querySelectorAll('[data-realtime]');
    realtimeElements.forEach(element => {{
        const tableName = element.dataset.table;
        const viewType = element.dataset.viewType || 'list';
        new RealtimeUpdater(tableName, viewType);
    }});
}});
        '''.format(timestamp=datetime.now().isoformat()).strip()

    def _generate_modern_css(self) -> str:
        """Generate modern CSS styles."""
        return '''
/* Modern Flask-AppBuilder Styles */
/* Generated: {timestamp} */

.modern-view-container {{
    padding: 20px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
}}

.modern-form-card {{
    background: white;
    border-radius: 15px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.1);
    padding: 30px;
    margin: 20px 0;
}}

.modern-fieldset {{
    border: none;
    margin: 20px 0;
    padding: 20px;
    background: #f8f9fa;
    border-radius: 10px;
    border-left: 4px solid #007bff;
}}

.modern-fieldset legend {{
    background: #007bff;
    color: white;
    padding: 5px 15px;
    border-radius: 5px;
    font-weight: 600;
    margin-bottom: 15px;
}}

.table-row-updated {{
    background-color: #d4edda !important;
    transition: background-color 2s ease;
}}

.widget-container {{
    margin: 15px 0;
}}

.widget-container label {{
    font-weight: 600;
    color: #495057;
    margin-bottom: 5px;
    display: block;
}}

.modern-input {{
    border-radius: 8px;
    border: 2px solid #e9ecef;
    transition: all 0.3s ease;
}}

.modern-input:focus {{
    border-color: #007bff;
    box-shadow: 0 0 0 0.2rem rgba(0,123,255,.25);
}}

/* Modern table styles */
.table-modern {{
    background: white;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 5px 15px rgba(0,0,0,0.08);
}}

.table-modern thead {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
}}

.table-modern tbody tr:hover {{
    background-color: #f8f9fa;
    transform: translateY(-2px);
    transition: all 0.3s ease;
}}

/* Modern button styles */
.btn-modern {{
    border-radius: 25px;
    padding: 10px 25px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    transition: all 0.3s ease;
}}

.btn-modern:hover {{
    transform: translateY(-2px);
    box-shadow: 0 5px 15px rgba(0,0,0,0.2);
}}

/* Responsive design */
@media (max-width: 768px) {{
    .modern-view-container {{
        padding: 10px;
    }}

    .modern-form-card {{
        padding: 20px;
        margin: 10px 0;
    }}
}}
        '''.format(timestamp=datetime.now().isoformat()).strip()

    def _generate_inline_formset_templates(self, output_dir: str):
        """Generate HTML templates for inline formsets."""
        templates_dir = os.path.join(output_dir, 'templates', 'appbuilder', 'general', 'model')
        os.makedirs(templates_dir, exist_ok=True)
        
        # Generate templates for each layout type
        for layout in self.config.inline_form_layouts:
            template_name = f'edit_master_detail_{layout}.html'
            template_path = os.path.join(templates_dir, template_name)
            template_content = self._get_inline_formset_template(layout, 'edit')
            
            with open(template_path, 'w') as f:
                f.write(template_content)
            
            # Also create add template
            add_template_name = f'add_master_detail_{layout}.html'
            add_template_path = os.path.join(templates_dir, add_template_name)
            add_template_content = self._get_inline_formset_template(layout, 'add')
            
            with open(add_template_path, 'w') as f:
                f.write(add_template_content)
        
        # Generate relationship navigation templates
        nav_template_path = os.path.join(templates_dir, 'relationship_navigation.html')
        with open(nav_template_path, 'w') as f:
            f.write(self._get_relationship_navigation_html_template())
        
        matrix_template_path = os.path.join(templates_dir, 'relationship_matrix.html')
        with open(matrix_template_path, 'w') as f:
            f.write(self._get_relationship_matrix_html_template())
    
    def _get_inline_formset_template(self, layout: str, mode: str) -> str:
        """Get HTML template for inline formsets."""
        if layout == 'stacked':
            return self._get_stacked_formset_template(mode)
        elif layout == 'tabular':
            return self._get_tabular_formset_template(mode)
        elif layout == 'accordion':
            return self._get_accordion_formset_template(mode)
        else:
            return self._get_stacked_formset_template(mode)  # Default
    
    def _get_stacked_formset_template(self, mode: str) -> str:
        """Get stacked layout template for inline formsets."""
        return '''{% extends "appbuilder/general/model/''' + mode + '''.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <div class="col-md-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">{{ title }}</h3>
                </div>
                <div class="card-body">
                    <form method="POST" class="form-horizontal master-detail-form">
                        {{ csrf_token() }}
                        
                        <!-- Master Record Fields -->
                        <div class="master-section">
                            <h4><i class="fa fa-info-circle"></i> Master Information</h4>
                            {% for fieldset in widget.fieldsets %}
                                {% if fieldset.name != 'Child Records' %}
                                <div class="fieldset">
                                    <legend>
                                        <i class="{{ fieldset.icon }}"></i> {{ fieldset.name }}
                                    </legend>
                                    {% for field in fieldset.fields %}
                                        <div class="form-group row">
                                            <label class="col-sm-3 col-form-label">{{ field.label.text }}</label>
                                            <div class="col-sm-9">
                                                {{ field(class="form-control") }}
                                                {% if field.errors %}
                                                    <div class="text-danger">
                                                        {% for error in field.errors %}
                                                            <small>{{ error }}</small><br>
                                                        {% endfor %}
                                                    </div>
                                                {% endif %}
                                            </div>
                                        </div>
                                    {% endfor %}
                                </div>
                                {% endif %}
                            {% endfor %}
                        </div>
                        
                        <!-- Child Records Section -->
                        <div class="child-section">
                            <h4><i class="fa fa-list"></i> Child Records</h4>
                            <div class="inline-formsets-container">
                                <div id="inline-forms" class="stacked-forms">
                                    <!-- Dynamic forms will be inserted here -->
                                </div>
                                <button type="button" class="btn btn-success add-form-btn">
                                    <i class="fa fa-plus"></i> Add Child Record
                                </button>
                            </div>
                        </div>
                        
                        <!-- Form Actions -->
                        <div class="form-actions">
                            <hr>
                            <button type="submit" class="btn btn-primary">
                                <i class="fa fa-save"></i> Save All
                            </button>
                            <a href="{{ url_for('.list') }}" class="btn btn-secondary">
                                <i class="fa fa-arrow-left"></i> Cancel
                            </a>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Form Template for Cloning -->
<script type="text/template" id="child-form-template">
    <div class="child-form card mb-3" data-form-index="__prefix__">
        <div class="card-header">
            <h5 class="card-title">Child Record #<span class="form-number">__prefix__</span></h5>
            <button type="button" class="btn btn-sm btn-danger remove-form">
                <i class="fa fa-trash"></i> Remove
            </button>
        </div>
        <div class="card-body">
            <!-- Child form fields will be rendered here -->
            <input type="hidden" name="child_forms-__prefix__-id" value="">
            <input type="hidden" name="child_forms-__prefix__-DELETE" value="false">
        </div>
    </div>
</script>

<style>
.master-detail-form .master-section {
    background-color: #f8f9fa;
    padding: 20px;
    margin-bottom: 30px;
    border-radius: 8px;
}

.master-detail-form .child-section {
    background-color: #fff;
    padding: 20px;
    border-radius: 8px;
    border: 1px solid #dee2e6;
}

.child-form {
    position: relative;
    margin-bottom: 15px;
}

.child-form .remove-form {
    position: absolute;
    top: 10px;
    right: 10px;
}

.add-form-btn {
    margin-top: 15px;
    width: 100%;
}

.stacked-forms .child-form:nth-child(even) {
    background-color: #f8f9fa;
}
</style>

<script>
// Inline formset management
document.addEventListener('DOMContentLoaded', function() {
    const container = document.getElementById('inline-forms');
    const addBtn = document.querySelector('.add-form-btn');
    const template = document.getElementById('child-form-template').innerHTML;
    let formCount = {{ pattern.default_child_count }};
    
    // Add initial forms
    for (let i = 0; i < formCount; i++) {
        addForm(i);
    }
    
    // Add form handler
    addBtn.addEventListener('click', function() {
        if (formCount < {{ pattern.max_child_forms }}) {
            addForm(formCount);
            formCount++;
        }
    });
    
    function addForm(index) {
        const formHtml = template.replace(/__prefix__/g, index);
        const div = document.createElement('div');
        div.innerHTML = formHtml;
        const form = div.firstElementChild;
        
        container.appendChild(form);
        
        // Add remove handler
        form.querySelector('.remove-form').addEventListener('click', function() {
            form.style.display = 'none';
            form.querySelector('input[name*="DELETE"]').value = 'true';
        });
        
        // Update form numbers
        updateFormNumbers();
    }
    
    function updateFormNumbers() {
        const forms = container.querySelectorAll('.child-form:not([style*="display: none"])');
        forms.forEach((form, index) => {
            form.querySelector('.form-number').textContent = index + 1;
        });
    }
});
</script>
{% endblock %}
'''
    
    def _get_tabular_formset_template(self, mode: str) -> str:
        """Get tabular layout template for inline formsets."""
        return '''{% extends "appbuilder/general/model/''' + mode + '''.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <div class="col-md-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">{{ title }}</h3>
                </div>
                <div class="card-body">
                    <form method="POST" class="form-horizontal master-detail-form">
                        {{ csrf_token() }}
                        
                        <!-- Master Record Fields -->
                        <div class="master-section">
                            <h4><i class="fa fa-info-circle"></i> Master Information</h4>
                            {% for fieldset in widget.fieldsets %}
                                {% if fieldset.name != 'Child Records' %}
                                <div class="fieldset">
                                    <legend>
                                        <i class="{{ fieldset.icon }}"></i> {{ fieldset.name }}
                                    </legend>
                                    <div class="row">
                                        {% for field in fieldset.fields %}
                                        <div class="col-md-6 form-group">
                                            <label>{{ field.label.text }}</label>
                                            {{ field(class="form-control") }}
                                            {% if field.errors %}
                                                <small class="text-danger">{{ field.errors[0] }}</small>
                                            {% endif %}
                                        </div>
                                        {% endfor %}
                                    </div>
                                </div>
                                {% endif %}
                            {% endfor %}
                        </div>
                        
                        <!-- Child Records Table -->
                        <div class="child-section">
                            <h4><i class="fa fa-table"></i> Child Records</h4>
                            <div class="table-responsive">
                                <table class="table table-striped table-hover" id="child-records-table">
                                    <thead class="thead-dark">
                                        <tr>
                                            <th width="40">#</th>
                                            {% for field in pattern.child_display_fields %}
                                            <th>{{ field|title }}</th>
                                            {% endfor %}
                                            <th width="80">Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody id="child-forms-tbody">
                                        <!-- Dynamic rows will be inserted here -->
                                    </tbody>
                                </table>
                            </div>
                            <button type="button" class="btn btn-success add-row-btn">
                                <i class="fa fa-plus"></i> Add Row
                            </button>
                        </div>
                        
                        <!-- Form Actions -->
                        <div class="form-actions">
                            <hr>
                            <button type="submit" class="btn btn-primary">
                                <i class="fa fa-save"></i> Save All
                            </button>
                            <a href="{{ url_for('.list') }}" class="btn btn-secondary">
                                <i class="fa fa-arrow-left"></i> Cancel
                            </a>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Row Template -->
<script type="text/template" id="child-row-template">
    <tr class="child-row" data-form-index="__prefix__">
        <td class="row-number">__prefix__</td>
        {% for field in pattern.child_display_fields %}
        <td>
            <input type="text" 
                   name="child_forms-__prefix__-{{ field }}" 
                   class="form-control form-control-sm"
                   placeholder="{{ field|title }}">
        </td>
        {% endfor %}
        <td>
            <button type="button" class="btn btn-sm btn-danger remove-row">
                <i class="fa fa-trash"></i>
            </button>
            <input type="hidden" name="child_forms-__prefix__-id" value="">
            <input type="hidden" name="child_forms-__prefix__-DELETE" value="false">
        </td>
    </tr>
</script>

<style>
.master-detail-form .master-section {
    background-color: #f8f9fa;
    padding: 20px;
    margin-bottom: 30px;
    border-radius: 8px;
}

.master-detail-form .child-section {
    background-color: #fff;
    padding: 20px;
    border-radius: 8px;
    border: 1px solid #dee2e6;
}

#child-records-table {
    margin-bottom: 15px;
}

.child-row.to-delete {
    opacity: 0.5;
    text-decoration: line-through;
}

.add-row-btn {
    margin-top: 10px;
}

.table td {
    padding: 8px;
    vertical-align: middle;
}

.form-control-sm {
    font-size: 0.875rem;
}
</style>

<script>
// Tabular formset management
document.addEventListener('DOMContentLoaded', function() {
    const tbody = document.getElementById('child-forms-tbody');
    const addBtn = document.querySelector('.add-row-btn');
    const template = document.getElementById('child-row-template').innerHTML;
    let formCount = {{ pattern.default_child_count }};
    
    // Add initial rows
    for (let i = 0; i < formCount; i++) {
        addRow(i);
    }
    
    // Add row handler
    addBtn.addEventListener('click', function() {
        if (formCount < {{ pattern.max_child_forms }}) {
            addRow(formCount);
            formCount++;
        }
    });
    
    function addRow(index) {
        const rowHtml = template.replace(/__prefix__/g, index);
        const tr = document.createElement('tr');
        tr.innerHTML = rowHtml;
        tbody.appendChild(tr);
        
        // Add remove handler
        tr.querySelector('.remove-row').addEventListener('click', function() {
            tr.classList.add('to-delete');
            tr.querySelector('input[name*="DELETE"]').value = 'true';
        });
        
        // Update row numbers
        updateRowNumbers();
    }
    
    function updateRowNumbers() {
        const rows = tbody.querySelectorAll('.child-row:not(.to-delete)');
        rows.forEach((row, index) => {
            row.querySelector('.row-number').textContent = index + 1;
        });
    }
});
</script>
{% endblock %}
'''
    
    def _get_accordion_formset_template(self, mode: str) -> str:
        """Get accordion layout template for inline formsets."""
        return '''{% extends "appbuilder/general/model/''' + mode + '''.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <div class="col-md-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">{{ title }}</h3>
                </div>
                <div class="card-body">
                    <form method="POST" class="form-horizontal master-detail-form">
                        {{ csrf_token() }}
                        
                        <!-- Master Record Fields -->
                        <div class="master-section">
                            <h4><i class="fa fa-info-circle"></i> Master Information</h4>
                            {% for fieldset in widget.fieldsets %}
                                {% if fieldset.name != 'Child Records' %}
                                <div class="fieldset">
                                    <legend>
                                        <i class="{{ fieldset.icon }}"></i> {{ fieldset.name }}
                                    </legend>
                                    <div class="row">
                                        {% for field in fieldset.fields %}
                                        <div class="col-md-6 form-group">
                                            <label>{{ field.label.text }}</label>
                                            {{ field(class="form-control") }}
                                            {% if field.errors %}
                                                <small class="text-danger">{{ field.errors[0] }}</small>
                                            {% endif %}
                                        </div>
                                        {% endfor %}
                                    </div>
                                </div>
                                {% endif %}
                            {% endfor %}
                        </div>
                        
                        <!-- Child Records Accordion -->
                        <div class="child-section">
                            <h4><i class="fa fa-list"></i> Child Records</h4>
                            <div class="accordion" id="child-records-accordion">
                                <!-- Dynamic accordion items will be inserted here -->
                            </div>
                            <button type="button" class="btn btn-success add-accordion-btn">
                                <i class="fa fa-plus"></i> Add Child Record
                            </button>
                        </div>
                        
                        <!-- Form Actions -->
                        <div class="form-actions">
                            <hr>
                            <button type="submit" class="btn btn-primary">
                                <i class="fa fa-save"></i> Save All
                            </button>
                            <a href="{{ url_for('.list') }}" class="btn btn-secondary">
                                <i class="fa fa-arrow-left"></i> Cancel
                            </a>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Accordion Item Template -->
<script type="text/template" id="child-accordion-template">
    <div class="card child-accordion-item" data-form-index="__prefix__">
        <div class="card-header" id="heading__prefix__">
            <h5 class="mb-0">
                <button class="btn btn-link collapsed" type="button" 
                        data-toggle="collapse" 
                        data-target="#collapse__prefix__" 
                        aria-expanded="false" 
                        aria-controls="collapse__prefix__">
                    <i class="fa fa-chevron-right"></i>
                    Child Record #<span class="form-number">__prefix__</span>
                </button>
                <button type="button" class="btn btn-sm btn-danger float-right remove-accordion">
                    <i class="fa fa-trash"></i>
                </button>
            </h5>
        </div>
        <div id="collapse__prefix__" 
             class="collapse" 
             aria-labelledby="heading__prefix__" 
             data-parent="#child-records-accordion">
            <div class="card-body">
                <div class="row">
                    {% for field in pattern.child_display_fields %}
                    <div class="col-md-6 form-group">
                        <label>{{ field|title }}</label>
                        <input type="text" 
                               name="child_forms-__prefix__-{{ field }}" 
                               class="form-control"
                               placeholder="Enter {{ field|title }}">
                    </div>
                    {% endfor %}
                </div>
                <input type="hidden" name="child_forms-__prefix__-id" value="">
                <input type="hidden" name="child_forms-__prefix__-DELETE" value="false">
            </div>
        </div>
    </div>
</script>

<style>
.master-detail-form .master-section {
    background-color: #f8f9fa;
    padding: 20px;
    margin-bottom: 30px;
    border-radius: 8px;
}

.master-detail-form .child-section {
    background-color: #fff;
    padding: 20px;
    border-radius: 8px;
    border: 1px solid #dee2e6;
}

.child-accordion-item {
    margin-bottom: 10px;
}

.child-accordion-item.to-delete {
    opacity: 0.5;
    background-color: #f8d7da;
}

.accordion .card-header {
    background-color: #e9ecef;
}

.accordion .btn-link {
    text-decoration: none;
    color: #495057;
}

.accordion .btn-link:hover {
    color: #007bff;
}

.accordion .btn-link i {
    transition: transform 0.2s;
}

.accordion .btn-link:not(.collapsed) i {
    transform: rotate(90deg);
}

.add-accordion-btn {
    margin-top: 15px;
    width: 100%;
}
</style>

<script>
// Accordion formset management
document.addEventListener('DOMContentLoaded', function() {
    const container = document.getElementById('child-records-accordion');
    const addBtn = document.querySelector('.add-accordion-btn');
    const template = document.getElementById('child-accordion-template').innerHTML;
    let formCount = {{ pattern.default_child_count }};
    
    // Add initial accordion items
    for (let i = 0; i < formCount; i++) {
        addAccordionItem(i);
    }
    
    // Add accordion item handler
    addBtn.addEventListener('click', function() {
        if (formCount < {{ pattern.max_child_forms }}) {
            addAccordionItem(formCount);
            formCount++;
        }
    });
    
    function addAccordionItem(index) {
        const itemHtml = template.replace(/__prefix__/g, index);
        const div = document.createElement('div');
        div.innerHTML = itemHtml;
        const item = div.firstElementChild;
        
        container.appendChild(item);
        
        // Add remove handler
        item.querySelector('.remove-accordion').addEventListener('click', function() {
            item.classList.add('to-delete');
            item.querySelector('input[name*="DELETE"]').value = 'true';
        });
        
        // Update form numbers
        updateFormNumbers();
    }
    
    function updateFormNumbers() {
        const items = container.querySelectorAll('.child-accordion-item:not(.to-delete)');
        items.forEach((item, index) => {
            item.querySelector('.form-number').textContent = index + 1;
        });
    }
});
</script>
{% endblock %}
'''
    
    def _get_relationship_navigation_html_template(self) -> str:
        """Get HTML template for relationship navigation."""
        return '''{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <div class="col-md-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">
                        <i class="fa fa-project-diagram"></i> {{ title }}
                    </h3>
                </div>
                <div class="card-body">
                    
                    <!-- Relationship Overview -->
                    <div class="row">
                        <div class="col-md-12">
                            <h4>Relationship Overview</h4>
                            <p class="text-muted">Explore all relationships for {{ model_name }} records.</p>
                        </div>
                    </div>
                    
                    <!-- Relationship Cards -->
                    <div class="row">
                        {% for rel_name, rel_info in relationship_stats.items() %}
                        <div class="col-md-4 mb-3">
                            <div class="card relationship-card">
                                <div class="card-body">
                                    <h5 class="card-title">
                                        <i class="fa fa-link"></i> {{ rel_info.display_name }}
                                    </h5>
                                    <p class="card-text">{{ rel_info.description }}</p>
                                    <div class="relationship-stats">
                                        <span class="badge badge-primary">{{ rel_info.count }} records</span>
                                        <span class="badge badge-secondary">{{ rel_info.type }}</span>
                                    </div>
                                    <div class="mt-3">
                                        <a href="{{ rel_info.url }}" class="btn btn-primary btn-sm">
                                            <i class="fa fa-eye"></i> View Records
                                        </a>
                                        <a href="{{ url_for('.relationship_matrix') }}" class="btn btn-outline-secondary btn-sm">
                                            <i class="fa fa-table"></i> Matrix View
                                        </a>
                                    </div>
                                </div>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    
                    <!-- Quick Actions -->
                    <div class="row mt-4">
                        <div class="col-md-12">
                            <h4>Quick Actions</h4>
                            <div class="btn-group" role="group">
                                <a href="{{ url_for('.relationship_matrix') }}" class="btn btn-outline-primary">
                                    <i class="fa fa-table"></i> Relationship Matrix
                                </a>
                                <a href="#" class="btn btn-outline-secondary" onclick="exportRelationships()">
                                    <i class="fa fa-download"></i> Export Data
                                </a>
                                <a href="#" class="btn btn-outline-info" onclick="showStatistics()">
                                    <i class="fa fa-chart-bar"></i> Statistics
                                </a>
                            </div>
                        </div>
                    </div>
                    
                </div>
            </div>
        </div>
    </div>
</div>

<style>
.relationship-card {
    transition: transform 0.2s;
    border: 1px solid #dee2e6;
}

.relationship-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
}

.relationship-stats .badge {
    margin-right: 5px;
}

.card-title i {
    color: #007bff;
}
</style>

<script>
function exportRelationships() {
    // Implement export functionality
    alert('Export functionality would be implemented here');
}

function showStatistics() {
    // Implement statistics modal
    alert('Statistics modal would be implemented here');
}
</script>
{% endblock %}
'''
    
    def _get_relationship_matrix_html_template(self) -> str:
        """Get HTML template for relationship matrix."""
        return '''{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <div class="col-md-12">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">
                        <i class="fa fa-table"></i> {{ title }}
                    </h3>
                    <div class="card-tools">
                        <a href="javascript:history.back()" class="btn btn-secondary btn-sm">
                            <i class="fa fa-arrow-left"></i> Back
                        </a>
                    </div>
                </div>
                <div class="card-body">
                    
                    <!-- Filter Controls -->
                    <div class="row mb-3">
                        <div class="col-md-6">
                            <select id="relationship-filter" class="form-control">
                                <option value="">All Relationships</option>
                                {% set relationships = matrix_data|map(attribute='relationship')|unique|list %}
                                {% for rel in relationships %}
                                <option value="{{ rel }}">{{ rel }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="col-md-6">
                            <input type="text" id="search-filter" class="form-control" placeholder="Search related items...">
                        </div>
                    </div>
                    
                    <!-- Matrix Table -->
                    <div class="table-responsive">
                        <table class="table table-striped table-hover" id="matrix-table">
                            <thead class="thead-dark">
                                <tr>
                                    <th>Relationship</th>
                                    <th>Related Item</th>
                                    <th>Count</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for item in matrix_data %}
                                <tr data-relationship="{{ item.relationship }}">
                                    <td>
                                        <span class="badge badge-info">{{ item.relationship }}</span>
                                    </td>
                                    <td>{{ item.related_item }}</td>
                                    <td>
                                        <span class="badge badge-primary">{{ item.count }}</span>
                                    </td>
                                    <td>
                                        <a href="{{ item.url }}" class="btn btn-sm btn-outline-primary">
                                            <i class="fa fa-eye"></i> View
                                        </a>
                                    </td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    
                    <!-- Matrix Summary -->
                    <div class="row mt-4">
                        <div class="col-md-12">
                            <div class="card">
                                <div class="card-header">
                                    <h5>Matrix Summary</h5>
                                </div>
                                <div class="card-body">
                                    <div class="row">
                                        <div class="col-md-3">
                                            <div class="info-box">
                                                <span class="info-box-icon bg-info">
                                                    <i class="fa fa-link"></i>
                                                </span>
                                                <div class="info-box-content">
                                                    <span class="info-box-text">Total Relationships</span>
                                                    <span class="info-box-number">{{ relationships|length }}</span>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="col-md-3">
                                            <div class="info-box">
                                                <span class="info-box-icon bg-success">
                                                    <i class="fa fa-database"></i>
                                                </span>
                                                <div class="info-box-content">
                                                    <span class="info-box-text">Total Records</span>
                                                    <span class="info-box-number">{{ matrix_data|sum(attribute='count') }}</span>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="col-md-3">
                                            <div class="info-box">
                                                <span class="info-box-icon bg-warning">
                                                    <i class="fa fa-list"></i>
                                                </span>
                                                <div class="info-box-content">
                                                    <span class="info-box-text">Related Items</span>
                                                    <span class="info-box-number">{{ matrix_data|length }}</span>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="col-md-3">
                                            <div class="info-box">
                                                <span class="info-box-icon bg-danger">
                                                    <i class="fa fa-chart-line"></i>
                                                </span>
                                                <div class="info-box-content">
                                                    <span class="info-box-text">Avg per Item</span>
                                                    <span class="info-box-number">{{ "%.1f"|format(matrix_data|sum(attribute='count') / matrix_data|length) }}</span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                </div>
            </div>
        </div>
    </div>
</div>

<style>
.info-box {
    display: block;
    min-height: 90px;
    background: #fff;
    width: 100%;
    box-shadow: 0 1px 1px rgba(0,0,0,0.1);
    border-radius: 2px;
    margin-bottom: 15px;
}

.info-box-icon {
    border-top-left-radius: 2px;
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
    border-bottom-left-radius: 2px;
    display: block;
    float: left;
    height: 90px;
    width: 90px;
    text-align: center;
    font-size: 45px;
    line-height: 90px;
    background: rgba(0,0,0,0.2);
}

.info-box-icon > i {
    color: #fff;
}

.info-box-content {
    padding: 5px 10px;
    margin-left: 90px;
}

.info-box-number {
    display: block;
    font-weight: bold;
    font-size: 18px;
}

.info-box-text {
    display: block;
    font-size: 14px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
</style>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const relationshipFilter = document.getElementById('relationship-filter');
    const searchFilter = document.getElementById('search-filter');
    const table = document.getElementById('matrix-table');
    const rows = table.querySelectorAll('tbody tr');
    
    // Filter by relationship
    relationshipFilter.addEventListener('change', function() {
        const selectedRel = this.value;
        
        rows.forEach(row => {
            if (selectedRel === '' || row.dataset.relationship === selectedRel) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    });
    
    // Search filter
    searchFilter.addEventListener('input', function() {
        const searchTerm = this.value.toLowerCase();
        
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            if (text.includes(searchTerm)) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    });
});
</script>
{% endblock %}
'''

    # Additional template methods would continue here...
    def _get_chart_view_template(self) -> str:
        """Get chart view template."""
        return '''"""
{{ table_info.display_name }} Chart View

Interactive charts for {{ table_info.display_name }} data analysis.
"""

from flask import render_template
from flask_appbuilder import BaseView, expose, has_access
from flask_appbuilder.charts.views import DirectByChartView
from flask_appbuilder.models.sqla.interface import SQLAInterface

from ..models import {{ model_name }}


class {{ class_name }}ChartView(DirectByChartView):
    """{{ table_info.display_name }} chart visualization."""

    datamodel = SQLAInterface({{ model_name }})
    
    chart_title = "{{ table_info.display_name }} Analytics"
    chart_type = "LineChart"
    
    # Chart configurations for different analytics
    definitions = [
        {% if date_columns %}
        {
            "group": "{{ date_columns[0].name }}",
            "series": [
                {% for col in numeric_columns[:3] %}"{{ col.name }}"{% if not loop.last %}, {% endif %}{% endfor %}
            ]
        },
        {% endif %}
        {% if categorical_columns and numeric_columns %}
        {
            "group": "{{ categorical_columns[0].name }}",  
            "series": ["{{ numeric_columns[0].name }}"]
        }
        {% endif %}
    ]
    
    @expose('/dashboard/')
    @has_access
    def dashboard(self):
        """Custom dashboard with multiple chart types."""
        widgets = [
            self._get_chart_widget("line"),
            self._get_chart_widget("bar"),
            {% if date_columns %}self._get_chart_widget("timeseries"),{% endif %}
            {% if has_location_fields %}self._get_map_widget(),{% endif %}
        ]
        
        return render_template(
            'charts/dashboard.html',
            title="{{ table_info.display_name }} Dashboard",
            widgets=widgets,
            base_template=self.appbuilder.base_template,
            appbuilder=self.appbuilder
        )
    
    def _get_chart_widget(self, chart_type: str):
        """Generate chart widget configuration."""
        return {
            'chart_type': chart_type,
            'data_endpoint': f'/api/v1/{{ table_info.name }}/chart/{chart_type}',
            'title': f'{{ table_info.display_name }} {chart_type.title()} Chart'
        }
    
    {% if has_location_fields %}
    def _get_map_widget(self):
        """Generate map widget for location data."""
        return {
            'widget_type': 'map',
            'data_endpoint': f'/api/v1/{{ table_info.name }}/geo', 
            'title': '{{ table_info.display_name }} Locations'
        }
    {% endif %}


class {{ class_name }}MetricsView(BaseView):
    """Real-time metrics view for {{ table_info.display_name }}."""
    
    default_view = 'metrics'
    
    @expose('/metrics/')
    @has_access
    def metrics(self):
        """Display real-time metrics."""
        metrics_data = {
            'total_records': self._get_total_count(),
            'recent_activity': self._get_recent_activity(),
            {% if date_columns %}
            'growth_trend': self._get_growth_trend(),
            {% endif %}
            {% if status_column %}
            'status_distribution': self._get_status_distribution(),
            {% endif %}
        }
        
        return render_template(
            'metrics/dashboard.html',
            metrics=metrics_data,
            title="{{ table_info.display_name }} Metrics",
            base_template=self.appbuilder.base_template,
            appbuilder=self.appbuilder
        )
    
    def _get_total_count(self):
        """Get total record count."""
        return self.datamodel.get_count()
    
    def _get_recent_activity(self):
        """Get recent activity data."""
        # Implementation for recent activity tracking
        return []
    
    {% if date_columns %}
    def _get_growth_trend(self):
        """Calculate growth trend over time."""
        # Implementation for growth trend analysis
        return []
    {% endif %}
    
    {% if status_column %}
    def _get_status_distribution(self):
        """Get distribution of status values."""
        # Implementation for status distribution
        return []
    {% endif %}
'''

    def _get_calendar_view_template(self) -> str:
        """Get calendar view template."""
        return '''"""
{{ table_info.display_name }} Calendar View

Calendar interface for {{ table_info.display_name }} with date-based visualization.
"""

from flask import render_template, request, jsonify
from flask_appbuilder import BaseView, expose, has_access
from flask_appbuilder.models.sqla.interface import SQLAInterface
from datetime import datetime, timedelta
import calendar

from ..models import {{ model_name }}


class {{ class_name }}CalendarView(BaseView):
    """{{ table_info.display_name }} calendar visualization."""

    datamodel = SQLAInterface({{ model_name }})
    default_view = 'calendar'
    
    @expose('/calendar/')
    @has_access
    def calendar(self):
        """Main calendar view."""
        return render_template(
            'calendar/calendar_view.html',
            title="{{ table_info.display_name }} Calendar",
            calendar_config=self._get_calendar_config(),
            base_template=self.appbuilder.base_template,
            appbuilder=self.appbuilder
        )
    
    @expose('/events/')
    @has_access
    def get_events(self):
        """Get calendar events for date range."""
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        
        if not start_date or not end_date:
            return jsonify([])
        
        try:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            
            events = self._get_events_for_range(start, end)
            return jsonify(events)
            
        except (ValueError, TypeError):
            return jsonify([])
    
    def _get_calendar_config(self):
        """Get FullCalendar configuration."""
        return {
            'initialView': 'dayGridMonth',
            'headerToolbar': {
                'left': 'prev,next today',
                'center': 'title',
                'right': 'dayGridMonth,timeGridWeek,timeGridDay,listWeek'
            },
            'events': '/{{ table_info.name }}/calendar/events/',
            'editable': {{ 'true' if has_update_permission else 'false' }},
            'selectable': {{ 'true' if has_create_permission else 'false' }},
            'eventDisplay': 'block',
            'dayMaxEvents': 3,
            'eventColor': '#3788d8',
            {% if has_categories %}
            'eventClassNames': self._get_event_styles(),
            {% endif %}
        }
    
    def _get_events_for_range(self, start_date, end_date):
        """Get events within date range."""
        events = []
        
        {% if date_columns %}
        # Query records within the date range
        date_field = {{ model_name }}.{{ date_columns[0].name }}
        records = self.datamodel.get_query().filter(
            date_field >= start_date,
            date_field <= end_date
        ).all()
        
        for record in records:
            event = {
                'id': record.id,
                'title': self._format_event_title(record),
                'start': getattr(record, '{{ date_columns[0].name }}').isoformat(),
                {% if date_columns|length > 1 %}
                'end': getattr(record, '{{ date_columns[1].name }}', None),
                {% endif %}
                'url': f'/{{ table_info.name }}/show/{record.id}',
                {% if status_column %}
                'className': f'event-{getattr(record, "{{ status_column.name }}", "default").lower()}',
                {% endif %}
                'extendedProps': {
                    'description': self._format_event_description(record),
                    {% if has_priority_field %}
                    'priority': getattr(record, '{{ priority_field.name }}', 'normal'),
                    {% endif %}
                }
            }
            
            {% if date_columns|length > 1 and date_columns[1].name %}
            if hasattr(record, '{{ date_columns[1].name }}') and getattr(record, '{{ date_columns[1].name }}'):
                event['end'] = getattr(record, '{{ date_columns[1].name }}').isoformat()
            {% endif %}
            
            events.append(event)
        {% endif %}
        
        return events
    
    def _format_event_title(self, record):
        """Format event title for calendar display."""
        {% if title_field %}
        return getattr(record, '{{ title_field.name }}', f'{{ table_info.display_name }} #{record.id}')
        {% else %}
        return f'{{ table_info.display_name }} #{record.id}'
        {% endif %}
    
    def _format_event_description(self, record):
        """Format event description with key details."""
        description_parts = []
        
        {% if description_field %}
        desc = getattr(record, '{{ description_field.name }}', None)
        if desc:
            description_parts.append(desc[:100] + ('...' if len(desc) > 100 else ''))
        {% endif %}
        
        {% if status_column %}
        status = getattr(record, '{{ status_column.name }}', None)
        if status:
            description_parts.append(f'Status: {status}')
        {% endif %}
        
        return ' | '.join(description_parts) if description_parts else ''
    
    {% if has_categories %}
    def _get_event_styles(self):
        """Get CSS classes for different event categories."""
        return {
            'urgent': 'fc-event-danger',
            'important': 'fc-event-warning', 
            'normal': 'fc-event-primary',
            'low': 'fc-event-secondary'
        }
    {% endif %}
    
    @expose('/create-event/', methods=['POST'])
    @has_access
    def create_event(self):
        """Create new event from calendar selection."""
        data = request.get_json()
        
        try:
            # Create new record with calendar data
            new_record = {{ model_name }}()
            
            {% if date_columns %}
            if 'start' in data:
                setattr(new_record, '{{ date_columns[0].name }}', 
                       datetime.fromisoformat(data['start'].replace('Z', '+00:00')))
            {% endif %}
            
            {% if date_columns|length > 1 %}
            if 'end' in data:
                setattr(new_record, '{{ date_columns[1].name }}', 
                       datetime.fromisoformat(data['end'].replace('Z', '+00:00')))
            {% endif %}
            
            {% if title_field %}
            setattr(new_record, '{{ title_field.name }}', data.get('title', ''))
            {% endif %}
            
            self.datamodel.add(new_record)
            
            return jsonify({
                'success': True, 
                'id': new_record.id,
                'message': 'Event created successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400


class {{ class_name }}TimelineView(BaseView):
    """Timeline view for {{ table_info.display_name }} chronological data."""
    
    default_view = 'timeline'
    
    @expose('/timeline/')
    @has_access 
    def timeline(self):
        """Display timeline visualization."""
        timeline_data = self._get_timeline_data()
        
        return render_template(
            'timeline/timeline_view.html',
            title="{{ table_info.display_name }} Timeline",
            timeline_data=timeline_data,
            timeline_config=self._get_timeline_config(),
            base_template=self.appbuilder.base_template,
            appbuilder=self.appbuilder
        )
    
    def _get_timeline_data(self):
        """Get data formatted for timeline display."""
        {% if date_columns %}
        records = self.datamodel.get_query().order_by(
            {{ model_name }}.{{ date_columns[0].name }}.desc()
        ).limit(100).all()
        
        timeline_items = []
        for record in records:
            item = {
                'id': record.id,
                'start': getattr(record, '{{ date_columns[0].name }}').isoformat(),
                'content': self._format_timeline_content(record),
                'group': self._get_timeline_group(record),
                {% if status_column %}
                'className': f'timeline-{getattr(record, "{{ status_column.name }}", "default").lower()}',
                {% endif %}
            }
            
            {% if date_columns|length > 1 %}
            end_date = getattr(record, '{{ date_columns[1].name }}', None)
            if end_date:
                item['end'] = end_date.isoformat()
                item['type'] = 'range'
            {% endif %}
            
            timeline_items.append(item)
            
        return timeline_items
        {% else %}
        return []
        {% endif %}
    
    def _format_timeline_content(self, record):
        """Format content for timeline display."""
        {% if title_field %}
        title = getattr(record, '{{ title_field.name }}', f'{{ table_info.display_name }} #{record.id}')
        {% else %}
        title = f'{{ table_info.display_name }} #{record.id}'
        {% endif %}
        
        {% if description_field %}
        description = getattr(record, '{{ description_field.name }}', '')
        if description:
            return f'<strong>{title}</strong><br><small>{description[:50]}...</small>'
        {% endif %}
        
        return f'<strong>{title}</strong>'
    
    def _get_timeline_group(self, record):
        """Get timeline group for record."""
        {% if categorical_columns %}
        return getattr(record, '{{ categorical_columns[0].name }}', 'Default')
        {% else %}
        return '{{ table_info.display_name }}'
        {% endif %}
    
    def _get_timeline_config(self):
        """Get Timeline.js configuration."""
        return {
            'orientation': 'both',
            'stack': True,
            'showCurrentTime': True,
            'zoomable': True,
            'moveable': True,
            'height': '400px'
        }
'''

    def _get_wizard_view_template(self) -> str:
        """Get wizard view template."""
        return '''"""
{{ table_info.display_name }} Wizard View

Multi-step wizard interface for creating {{ table_info.display_name }} records.
"""

from flask import render_template, request, jsonify, session
from flask_appbuilder import BaseView, expose, has_access
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, IntegerField, BooleanField
from wtforms.validators import DataRequired, Length, Email, Optional

from ..models import {{ model_name }}


class {{ class_name }}WizardForm(FlaskForm):
    """Multi-step form for {{ table_info.display_name }} creation."""
    
    # Step 1: Basic Information
    {% for col in required_columns[:3] %}
    {{ col.name }} = {{ col.wtf_field_type }}(
        '{{ col.display_name }}',
        validators=[DataRequired()]
        {% if col.max_length %}, render_kw={'maxlength': {{ col.max_length }}}{% endif %}
    )
    {% endfor %}
    
    # Step 2: Additional Details  
    {% for col in optional_columns[:4] %}
    {{ col.name }} = {{ col.wtf_field_type }}(
        '{{ col.display_name }}',
        validators=[Optional()]
        {% if col.max_length %}, render_kw={'maxlength': {{ col.max_length }}}{% endif %}
        {% if col.choices %}, choices={{ col.choices }}{% endif %}
    )
    {% endfor %}
    
    # Step 3: Relationships
    {% for rel in relationships[:3] %}
    {{ rel.property_name }} = SelectField(
        '{{ rel.display_name }}',
        validators=[Optional()],
        coerce=int,
        choices=[]  # Will be populated dynamically
    )
    {% endfor %}


class {{ class_name }}WizardView(BaseView):
    """Multi-step wizard for {{ table_info.display_name }} creation."""
    
    route_base = '/{{ table_info.name }}/wizard'
    default_view = 'step1'
    
    # Wizard configuration
    wizard_steps = [
        {
            'step': 1,
            'title': 'Basic Information',
            'description': 'Enter the essential {{ table_info.display_name }} details',
            'fields': [{% for col in required_columns[:3] %}'{{ col.name }}'{% if not loop.last %}, {% endif %}{% endfor %}],
            'validation_required': True
        },
        {
            'step': 2, 
            'title': 'Additional Details',
            'description': 'Provide optional information and settings',
            'fields': [{% for col in optional_columns[:4] %}'{{ col.name }}'{% if not loop.last %}, {% endif %}{% endfor %}],
            'validation_required': False
        },
        {
            'step': 3,
            'title': 'Relationships',
            'description': 'Connect with related records',
            'fields': [{% for rel in relationships[:3] %}'{{ rel.property_name }}'{% if not loop.last %}, {% endif %}{% endfor %}],
            'validation_required': False
        },
        {
            'step': 4,
            'title': 'Review & Submit',
            'description': 'Review your information and submit',
            'fields': [],
            'validation_required': False
        }
    ]
    
    @expose('/step/<int:step_num>/')
    @has_access
    def wizard_step(self, step_num):
        """Display wizard step."""
        if step_num < 1 or step_num > len(self.wizard_steps):
            return self.step1()
            
        step_config = self.wizard_steps[step_num - 1]
        form = {{ class_name }}WizardForm()
        
        # Pre-populate form with session data
        wizard_data = session.get('{{ table_info.name }}_wizard', {})
        self._populate_form_from_session(form, wizard_data)
        
        # Populate relationship choices
        if step_num == 3:
            self._populate_relationship_choices(form)
        
        return render_template(
            'wizard/wizard_step.html',
            form=form,
            step_config=step_config,
            current_step=step_num,
            total_steps=len(self.wizard_steps),
            progress_percentage=int((step_num / len(self.wizard_steps)) * 100),
            wizard_data=wizard_data,
            base_template=self.appbuilder.base_template,
            appbuilder=self.appbuilder
        )
    
    @expose('/')
    @expose('/step1/')
    @has_access
    def step1(self):
        """Step 1: Basic Information."""
        return self.wizard_step(1)
    
    @expose('/step2/')
    @has_access
    def step2(self):
        """Step 2: Additional Details."""
        return self.wizard_step(2)
    
    @expose('/step3/')
    @has_access
    def step3(self):
        """Step 3: Relationships."""
        return self.wizard_step(3)
    
    @expose('/step4/')
    @has_access
    def step4(self):
        """Step 4: Review & Submit."""
        return self.wizard_step(4)
    
    @expose('/save-step/', methods=['POST'])
    @has_access
    def save_step(self):
        """Save current step data to session."""
        data = request.get_json()
        step_num = data.get('step', 1)
        form_data = data.get('form_data', {})
        
        # Get existing wizard data from session
        wizard_data = session.get('{{ table_info.name }}_wizard', {})
        
        # Update with new step data
        wizard_data.update(form_data)
        wizard_data['current_step'] = step_num
        wizard_data['completed_steps'] = wizard_data.get('completed_steps', [])
        
        if step_num not in wizard_data['completed_steps']:
            wizard_data['completed_steps'].append(step_num)
        
        # Save to session
        session['{{ table_info.name }}_wizard'] = wizard_data
        
        # Validate current step if required
        validation_errors = []
        step_config = self.wizard_steps[step_num - 1]
        
        if step_config['validation_required']:
            validation_errors = self._validate_step_data(step_num, form_data)
        
        return jsonify({
            'success': len(validation_errors) == 0,
            'errors': validation_errors,
            'next_step': step_num + 1 if step_num < len(self.wizard_steps) else step_num
        })
    
    @expose('/submit/', methods=['POST'])
    @has_access
    def submit_wizard(self):
        """Submit complete wizard data."""
        wizard_data = session.get('{{ table_info.name }}_wizard', {})
        
        if not wizard_data:
            return jsonify({
                'success': False,
                'error': 'No wizard data found in session'
            }), 400
        
        try:
            # Create new record from wizard data
            new_record = {{ model_name }}()
            
            # Map form fields to model attributes
            {% for col in all_columns %}
            if '{{ col.name }}' in wizard_data:
                value = wizard_data['{{ col.name }}']
                {% if col.python_type == 'int' %}
                if value and str(value).isdigit():
                    value = int(value)
                {% elif col.python_type == 'bool' %}
                if isinstance(value, str):
                    value = value.lower() in ('true', '1', 'yes', 'on')
                {% endif %}
                setattr(new_record, '{{ col.name }}', value)
            {% endfor %}
            
            # Handle relationships
            {% for rel in relationships %}
            if '{{ rel.property_name }}' in wizard_data:
                rel_id = wizard_data['{{ rel.property_name }}']
                if rel_id and str(rel_id).isdigit():
                    # Load related object and set relationship
                    related_obj = self.appbuilder.get_session.query({{ rel.target_model }}).get(int(rel_id))
                    if related_obj:
                        setattr(new_record, '{{ rel.property_name }}', related_obj)
            {% endfor %}
            
            # Save the record
            self.appbuilder.get_session.add(new_record)
            self.appbuilder.get_session.commit()
            
            # Clear wizard data from session
            session.pop('{{ table_info.name }}_wizard', None)
            
            return jsonify({
                'success': True,
                'record_id': new_record.id,
                'message': '{{ table_info.display_name }} created successfully!',
                'redirect_url': f'/{{ table_info.name }}/show/{new_record.id}'
            })
            
        except Exception as e:
            self.appbuilder.get_session.rollback()
            return jsonify({
                'success': False,
                'error': f'Error creating {{ table_info.display_name }}: {str(e)}'
            }), 500
    
    @expose('/reset/')
    @has_access
    def reset_wizard(self):
        """Reset wizard data and start over."""
        session.pop('{{ table_info.name }}_wizard', None)
        return jsonify({'success': True, 'redirect_url': '/{{ table_info.name }}/wizard/'})
    
    def _populate_form_from_session(self, form, wizard_data):
        """Pre-populate form fields from session data."""
        for field_name, field in form._fields.items():
            if field_name in wizard_data:
                field.data = wizard_data[field_name]
    
    def _populate_relationship_choices(self, form):
        """Populate relationship field choices."""
        {% for rel in relationships[:3] %}
        # Populate {{ rel.property_name }} choices
        {{ rel.property_name }}_choices = [(0, 'Select {{ rel.display_name }}...')]
        {% if rel.target_model %}
        related_objects = self.appbuilder.get_session.query({{ rel.target_model }}).all()
        for obj in related_objects:
            display_value = getattr(obj, 'name', None) or getattr(obj, 'title', None) or f'{{ rel.target_model }} #{obj.id}'
            {{ rel.property_name }}_choices.append((obj.id, display_value))
        form.{{ rel.property_name }}.choices = {{ rel.property_name }}_choices
        {% endif %}
        
        {% endfor %}
    
    def _validate_step_data(self, step_num, form_data):
        """Validate data for a specific step."""
        errors = []
        step_config = self.wizard_steps[step_num - 1]
        
        for field_name in step_config['fields']:
            if field_name not in form_data or not form_data[field_name]:
                # Find field display name
                field_display = field_name.replace('_', ' ').title()
                errors.append(f'{field_display} is required')
        
        # Additional validation logic can be added here
        return errors
    
    @expose('/field-suggestions/')
    @has_access
    def get_field_suggestions(self):
        """Get suggestions for form fields based on existing data."""
        field_name = request.args.get('field')
        query = request.args.get('query', '')
        
        if not field_name or not query:
            return jsonify([])
        
        try:
            # Get unique values for the field that match the query
            suggestions = self.appbuilder.get_session.query(
                getattr({{ model_name }}, field_name)
            ).filter(
                getattr({{ model_name }}, field_name).ilike(f'%{query}%')
            ).distinct().limit(10).all()
            
            return jsonify([str(suggestion[0]) for suggestion in suggestions if suggestion[0]])
            
        except Exception:
            return jsonify([])


class {{ class_name }}BulkWizardView(BaseView):
    """Bulk import wizard for multiple {{ table_info.display_name }} records."""
    
    route_base = '/{{ table_info.name }}/bulk-wizard'
    default_view = 'upload'
    
    @expose('/')
    @expose('/upload/')
    @has_access
    def upload(self):
        """Step 1: File upload."""
        return render_template(
            'wizard/bulk_upload.html',
            title='Bulk Import {{ table_info.display_name }}',
            accepted_formats=['csv', 'xlsx', 'json'],
            sample_data=self._get_sample_data(),
            base_template=self.appbuilder.base_template,
            appbuilder=self.appbuilder
        )
    
    @expose('/preview/')
    @has_access
    def preview(self):
        """Step 2: Preview imported data."""
        return render_template(
            'wizard/bulk_preview.html',
            title='Preview Import Data',
            base_template=self.appbuilder.base_template,
            appbuilder=self.appbuilder
        )
    
    @expose('/process/', methods=['POST'])
    @has_access
    def process_bulk_import(self):
        """Process bulk import."""
        # Implementation for bulk import processing
        return jsonify({
            'success': True,
            'imported_count': 0,
            'errors': []
        })
    
    def _get_sample_data(self):
        """Get sample data for template download."""
        return {
            {% for col in required_columns[:5] %}
            '{{ col.name }}': '{{ col.sample_value }}',
            {% endfor %}
        }
'''

    def _get_report_view_template(self) -> str:
        """Get report view template."""
        # Implementation would follow similar pattern
        return "# Report view template implementation"

    def _generate_master_detail_view(self, parent_info: TableInfo, pattern: 'MasterDetailInfo') -> str:
        """Generate master-detail view code."""
        child_info = self.inspector.analyze_table(pattern.child_table)
        template = self._get_master_detail_view_template()
        
        return self.jinja_env.from_string(template).render(
            parent_info=parent_info,
            child_info=child_info,
            pattern=pattern,
            parent_class_name=self._to_pascal_case(parent_info.name),
            child_class_name=self._to_pascal_case(pattern.child_table),
            master_detail_class_name=f"{self._to_pascal_case(parent_info.name)}{self._to_pascal_case(pattern.child_table)}MasterDetailView",
            inline_formset_class=f"{self._to_pascal_case(pattern.child_table)}InlineFormSet"
        )
    
    def _generate_reference_view(self, table_info: TableInfo, relationship: 'RelationshipInfo') -> str:
        """Generate reference view code."""
        template = self._get_reference_view_template()
        
        return self.jinja_env.from_string(template).render(
            table_info=table_info,
            relationship=relationship,
            class_name=f"{self._to_pascal_case(table_info.name)}By{self._to_pascal_case(relationship.remote_table)}View",
            model_name=self._to_pascal_case(table_info.name),
            reference_model_name=self._to_pascal_case(relationship.remote_table)
        )

    def _get_master_detail_view_template(self) -> str:
        """Get template for master-detail views."""
        return '''"""
{{ parent_class_name }} Master-Detail View with {{ child_class_name }} inline forms.

This view provides a comprehensive interface for managing {{ parent_info.display_name }}
records along with their related {{ child_info.display_name }} records in a single form.
"""

from flask import flash, redirect, url_for, request
from flask_appbuilder import ModelView, BaseView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.widgets import FormWidget, ShowWidget
from flask_appbuilder.forms import DynamicForm
from wtforms import FieldList, FormField
from wtforms.validators import DataRequired, Optional
from ..models import {{ parent_class_name }}, {{ child_class_name }}


class {{ inline_formset_class }}(DynamicForm):
    """Inline formset for {{ child_class_name }} records."""
    
    # Child record fields
{% for field in pattern.child_display_fields %}
    {{ field }} = {{ child_info.columns|selectattr('name', 'equalto', field)|first|attr('form_field_type'|default('StringField')) }}()
{% endfor %}
    
    # Hidden fields for tracking
    id = HiddenField()
    delete = BooleanField('Delete')
    
    class Meta:
        csrf = False


class {{ master_detail_class_name }}(ModelView):
    """
    Master-Detail view for {{ parent_class_name }} with inline {{ child_class_name }} management.
    
    Features:
    - Inline editing of child records
    - Bulk operations on child records
    - Relationship validation
    - Transaction-safe updates
    """
    
    datamodel = SQLAInterface({{ parent_class_name }})
    
    # View configuration
    route_base = '/{{ parent_info.name.lower() }}_master_detail'
    default_view = 'list'
    
    # Master record configuration
    list_title = "{{ parent_info.display_name }} Master-Detail Management"
    show_title = "{{ parent_info.display_name }} Details"
    add_title = "Add {{ parent_info.display_name }} with {{ child_info.display_name }}"
    edit_title = "Edit {{ parent_info.display_name }} and {{ child_info.display_name }}"
    
    # Master record fields
    list_columns = {{ pattern.parent_display_fields + ['_child_count'] }}
    show_columns = {{ pattern.parent_display_fields }}
    add_columns = {{ pattern.parent_display_fields }}
    edit_columns = {{ pattern.parent_display_fields }}
    
    # Search and filters
    search_columns = {{ pattern.parent_display_fields[:3] }}
    
    # Inline configuration
    inline_models = [{{ child_class_name }}]
    inline_form_class = {{ inline_formset_class }}
    
    # UI Configuration
    {% if pattern.child_form_layout == 'accordion' %}
    edit_template = 'appbuilder/general/model/edit_master_detail_accordion.html'
    add_template = 'appbuilder/general/model/add_master_detail_accordion.html'
    {% elif pattern.child_form_layout == 'tabular' %}
    edit_template = 'appbuilder/general/model/edit_master_detail_tabular.html'
    add_template = 'appbuilder/general/model/add_master_detail_tabular.html'
    {% else %}
    edit_template = 'appbuilder/general/model/edit_master_detail_stacked.html'
    add_template = 'appbuilder/general/model/add_master_detail_stacked.html'
    {% endif %}
    
    # Inline formset configuration
    inline_formset_config = {
        'default_count': {{ pattern.default_child_count }},
        'min_forms': {{ pattern.min_child_forms }},
        'max_forms': {{ pattern.max_child_forms }},
        'enable_sorting': {{ pattern.enable_sorting|lower }},
        'enable_deletion': {{ pattern.enable_deletion|lower }},
        'layout': '{{ pattern.child_form_layout }}',
        'bulk_operations': {{ pattern.supports_bulk_operations|lower }}
    }
    
    @expose('/add', methods=['GET', 'POST'])
    def add(self):
        """Add master record with inline child records."""
        widget = self._get_add_widget()
        
        if request.method == 'POST':
            return self._handle_master_detail_add()
        
        return self.render_template(
            self.add_template,
            title=self.add_title,
            widget=widget,
            appbuilder=self.appbuilder
        )
    
    @expose('/edit/<pk>', methods=['GET', 'POST'])  
    def edit(self, pk):
        """Edit master record with inline child records."""
        master_record = self.datamodel.get(pk)
        if not master_record:
            flash("Record not found", "error")
            return redirect(url_for('.list'))
        
        widget = self._get_edit_widget(master_record)
        
        if request.method == 'POST':
            return self._handle_master_detail_edit(master_record)
        
        return self.render_template(
            self.edit_template,
            title=self.edit_title,
            widget=widget,
            pk=pk,
            appbuilder=self.appbuilder
        )
    
    @expose('/show/<pk>')
    def show(self, pk):
        """Show master record with child records."""
        master_record = self.datamodel.get(pk)
        if not master_record:
            flash("Record not found", "error") 
            return redirect(url_for('.list'))
        
        # Get child records
        child_records = self.datamodel.session.query({{ child_class_name }}).\
            filter_by({{ pattern.relationship.local_columns[0] }}=pk).all()
        
        widget = self._get_show_widget(master_record)
        
        return self.render_template(
            self.show_template,
            title=self.show_title,
            widget=widget,
            master_record=master_record,
            child_records=child_records,
            pk=pk,
            appbuilder=self.appbuilder
        )
    
    def _handle_master_detail_add(self):
        """Handle adding master record with child records."""
        try:
            # Start transaction
            session = self.datamodel.session
            session.begin()
            
            # Create master record
            master_form = self._get_add_form()
            if master_form.validate():
                master_record = {{ parent_class_name }}()
                master_form.populate_obj(master_record)
                session.add(master_record)
                session.flush()  # Get the ID
                
                # Create child records
                child_data = request.form.getlist('child_forms')
                for child_form_data in child_data:
                    if child_form_data.get('delete'):
                        continue
                        
                    child_record = {{ child_class_name }}()
                    # Set foreign key
                    setattr(child_record, '{{ pattern.relationship.local_columns[0] }}', master_record.id)
                    
                    # Populate child fields
                    {% for field in pattern.child_display_fields %}
                    if '{{ field }}' in child_form_data:
                        setattr(child_record, '{{ field }}', child_form_data['{{ field }}'])
                    {% endfor %}
                    
                    session.add(child_record)
                
                session.commit()
                flash(f"{{ parent_info.display_name }} and related records added successfully", "success")
                return redirect(url_for('.list'))
            else:
                session.rollback()
                flash("Form validation failed", "error")
                
        except Exception as e:
            session.rollback()
            flash(f"Error adding records: {str(e)}", "error")
        
        return redirect(url_for('.add'))
    
    def _handle_master_detail_edit(self, master_record):
        """Handle editing master record with child records."""
        try:
            session = self.datamodel.session
            session.begin()
            
            # Update master record
            master_form = self._get_edit_form()
            if master_form.validate():
                master_form.populate_obj(master_record)
                
                # Handle child records
                existing_children = {child.id: child for child in master_record.{{ pattern.relationship.name }}}
                child_data = request.form.getlist('child_forms')
                
                processed_ids = set()
                
                for child_form_data in child_data:
                    child_id = child_form_data.get('id')
                    
                    if child_form_data.get('delete') and child_id:
                        # Delete existing child
                        if int(child_id) in existing_children:
                            session.delete(existing_children[int(child_id)])
                        continue
                    
                    if child_id:
                        # Update existing child
                        child_record = existing_children.get(int(child_id))
                        if child_record:
                            {% for field in pattern.child_display_fields %}
                            if '{{ field }}' in child_form_data:
                                setattr(child_record, '{{ field }}', child_form_data['{{ field }}'])
                            {% endfor %}
                            processed_ids.add(int(child_id))
                    else:
                        # Add new child
                        child_record = {{ child_class_name }}()
                        setattr(child_record, '{{ pattern.relationship.local_columns[0] }}', master_record.id)
                        
                        {% for field in pattern.child_display_fields %}
                        if '{{ field }}' in child_form_data:
                            setattr(child_record, '{{ field }}', child_form_data['{{ field }}'])
                        {% endfor %}
                        
                        session.add(child_record)
                
                session.commit()
                flash("Records updated successfully", "success")
                return redirect(url_for('.list'))
            else:
                session.rollback()
                flash("Form validation failed", "error")
                
        except Exception as e:
            session.rollback() 
            flash(f"Error updating records: {str(e)}", "error")
        
        return redirect(url_for('.edit', pk=master_record.id))
    
    def _get_add_widget(self):
        """Get widget for add form with inline formsets."""
        form = self._get_add_form()
        return FormWidget(
            form=form,
            include_cols=self.add_columns,
            exclude_cols=[],
            fieldsets=self._get_fieldsets_with_inline()
        )
    
    def _get_edit_widget(self, master_record):
        """Get widget for edit form with inline formsets."""
        form = self._get_edit_form()
        form.process(obj=master_record)
        return FormWidget(
            form=form,
            include_cols=self.edit_columns,
            exclude_cols=[],
            fieldsets=self._get_fieldsets_with_inline()
        )
    
    def _get_show_widget(self, master_record):
        """Get widget for show view."""
        return ShowWidget(
            model=master_record,
            include_cols=self.show_columns,
            exclude_cols=[],
            fieldsets=self._get_fieldsets_with_inline()
        )
    
    def _get_fieldsets_with_inline(self):
        """Get fieldsets including inline child forms."""
        fieldsets = [
            {
                'name': '{{ parent_info.display_name }} Information',
                'fields': {{ pattern.parent_display_fields }},
                'icon': 'fa-info-circle'
            },
            {
                'name': '{{ child_info.display_name }} Records',
                'fields': ['_inline_{{ pattern.child_table }}'],
                'icon': 'fa-list',
                'collapsible': False
            }
        ]
        return fieldsets
    
    @property
    def _child_count(self):
        """Virtual column for child record count."""
        def child_count_formatter(item):
            return len(getattr(item, '{{ pattern.relationship.name }}', []))
        return child_count_formatter


# Register the view
appbuilder.add_view(
    {{ master_detail_class_name }},
    "{{ parent_info.display_name }} Master-Detail",
    icon="fa-edit",
    category="{{ parent_info.category or 'Master-Detail' }}"
)
'''

    def _get_lookup_view_template(self) -> str:
        """Get template for lookup views."""
        return '''"""
{{ class_name }} - Enhanced lookup view for records with multiple relationships.

This view provides advanced filtering and search capabilities based on related data.
"""

from flask_appbuilder import ModelView
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.models.sqla.filters import FilterStartsWith, FilterEqual, FilterMenu
from ..models import {{ model_name }}{% for rel in relationships %}, {{ rel.remote_table|title }}{% endfor %}


class {{ class_name }}(ModelView):
    """
    Lookup view for {{ model_name }} with advanced relationship filtering.
    
    Features:
    - Multi-relationship filtering
    - Quick lookup by related entities
    - Enhanced search capabilities
    """
    
    datamodel = SQLAInterface({{ model_name }})
    
    # View configuration
    route_base = '/{{ table_info.name.lower() }}_lookup'
    default_view = 'list'
    
    # Display configuration
    list_title = "{{ table_info.display_name }} Lookup"
    
    # Show key fields and relationships
    list_columns = [
        {% for col in table_info.columns[:4] %}
        {% if not col.primary_key %}'{{ col.name }}',{% endif %}
        {% endfor %}
        {% for rel in relationships %}
        '{{ rel.name }}',
        {% endfor %}
    ]
    
    # Enhanced search
    search_columns = [
        {% for col in table_info.columns[:3] %}
        {% if not col.primary_key and col.searchable %}'{{ col.name }}',{% endif %}
        {% endfor %}
        {% for rel in relationships %}
        '{{ rel.name }}.name',
        {% endfor %}
    ]
    
    # Relationship filters
    search_form_query_rel_fields = {
        {% for rel in relationships %}
        '{{ rel.name }}': [['name', FilterStartsWith, '']],
        {% endfor %}
    }
    
    # Base filters for quick lookup
    base_filters = []
    
    # Add menu filters for each relationship
    {% for rel in relationships %}
    filters_menu = FilterMenu('{{ rel.name }}', {{ rel.remote_table|title }})
    {% endfor %}
    
    @expose('/lookup_by/<relation>/<pk>')
    def lookup_by_relation(self, relation, pk):
        """Quick lookup by related entity."""
        # Apply filter and redirect to filtered list
        return redirect(url_for('.list', **{f'_flt_0_{relation}': pk}))


appbuilder.add_view(
    {{ class_name }},
    "{{ table_info.display_name }} Lookup", 
    icon="fa-search",
    category="{{ table_info.category or 'Lookups' }}"
)
'''

    def _get_reference_view_template(self) -> str:
        """Get template for reference views."""
        return '''"""
{{ class_name }} - View {{ table_info.display_name }} grouped by {{ relationship.remote_table|title }}.

This view provides a {{ reference_model_name }}-centric view of {{ model_name }} records.
"""

from flask_appbuilder import ModelView
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.models.sqla.filters import FilterEqual
from ..models import {{ model_name }}, {{ reference_model_name }}


class {{ class_name }}(ModelView):
    """
    View {{ model_name }} records organized by {{ reference_model_name }}.
    
    This view is optimized for scenarios where users need to see all
    {{ table_info.display_name }} records associated with specific {{ relationship.remote_table }}.
    """
    
    datamodel = SQLAInterface({{ model_name }})
    
    # View configuration
    route_base = '/{{ table_info.name.lower() }}_by_{{ relationship.remote_table.lower() }}'
    default_view = 'list'
    
    # Display configuration
    list_title = "{{ table_info.display_name }} by {{ relationship.display_name }}"
    
    # Emphasize the relationship
    list_columns = [
        '{{ relationship.name }}',
        {% for col in table_info.columns[:3] %}
        {% if not col.primary_key %}'{{ col.name }}',{% endif %}
        {% endfor %}
    ]
    
    # Default ordering by relationship
    base_order = ('{{ relationship.name }}', 'asc')
    
    # Group by relationship in list view
    formatters_columns = {
        '{{ relationship.name }}': lambda x: f"<strong>{x}</strong>" if x else "No {{ reference_model_name }}"
    }
    
    # Quick filters
    search_form_query_rel_fields = {
        '{{ relationship.name }}': [['name', FilterEqual, '']]
    }
    
    # Custom view methods
    @expose('/by_{{ relationship.remote_table.lower() }}/<pk>')
    def filter_by_reference(self, pk):
        """Filter records by specific {{ reference_model_name }}."""
        reference = appbuilder.session.query({{ reference_model_name }}).get(pk)
        if not reference:
            flash("{{ reference_model_name }} not found", "error")
            return redirect(url_for('.list'))
        
        # Apply filter and show results
        filtered_url = url_for('.list', **{f'_flt_0_{pk}': pk})
        return redirect(filtered_url)


appbuilder.add_view(
    {{ class_name }},
    "{{ table_info.display_name }} by {{ reference_model_name }}",
    icon="fa-sitemap", 
    category="{{ table_info.category or 'Reference Views' }}"
)
'''

    def _get_relationship_navigation_template(self) -> str:
        """Get template for relationship navigation views.""" 
        return '''"""
{{ class_name }} - Navigate {{ model_name }} relationships.

This view provides a dashboard for exploring all relationships of {{ table_info.display_name }}.
"""

from flask import render_template
from flask_appbuilder import BaseView, expose
from flask_appbuilder.security.decorators import has_access
from ..models import {{ model_name }}{% for rel in relationships %}, {{ rel.remote_table|title }}{% endfor %}


class {{ class_name }}(BaseView):
    """
    Relationship navigation dashboard for {{ model_name }}.
    
    Provides an overview and quick navigation to all related data.
    """
    
    route_base = '/{{ table_info.name.lower() }}_relationships'
    default_view = 'index'
    
    @expose('/')
    @has_access
    def index(self):
        """Relationship navigation dashboard."""
        
        # Get relationship statistics
        relationship_stats = {}
        {% for rel in relationships %}
        relationship_stats['{{ rel.name }}'] = {
            'count': appbuilder.session.query({{ rel.remote_table|title }}).count(),
            'display_name': '{{ rel.display_name }}',
            'description': '{{ rel.description }}',
            'type': '{{ rel.type.value }}',
            'url': url_for('{{ rel.remote_table|title }}ModelView.list')
        }
        {% endfor %}
        
        return self.render_template(
            'relationship_navigation.html',
            title="{{ table_info.display_name }} Relationships",
            model_name="{{ model_name }}",
            relationship_stats=relationship_stats
        )
    
    @expose('/matrix')
    @has_access 
    def relationship_matrix(self):
        """Show relationship matrix view."""
        
        # Build relationship matrix data
        matrix_data = []
        {% for rel in relationships %}
        # Get {{ rel.remote_table }} with {{ table_info.name }} counts
        {{ rel.remote_table }}_data = appbuilder.session.query({{ rel.remote_table|title }}).\
            outerjoin({{ model_name }}).\
            group_by({{ rel.remote_table|title }}.id).\
            with_entities(
                {{ rel.remote_table|title }},
                func.count({{ model_name }}.id).label('{{ table_info.name }}_count')
            ).all()
        
        for item, count in {{ rel.remote_table }}_data:
            matrix_data.append({
                'relationship': '{{ rel.display_name }}',
                'related_item': str(item),
                'count': count,
                'url': url_for('{{ model_name }}ModelView.list') + f'?_flt_0_{rel.name}={item.id}'
            })
        {% endfor %}
        
        return self.render_template(
            'relationship_matrix.html',
            title="{{ table_info.display_name }} Relationship Matrix",
            matrix_data=matrix_data
        )


appbuilder.add_view_no_menu({{ class_name }})
appbuilder.add_link(
    "{{ table_info.display_name }} Relationships",
    href="/{{ table_info.name.lower() }}_relationships/",
    icon="fa-project-diagram",
    category="{{ table_info.category or 'Relationships' }}"
)
'''

    def _generate_form_validators(self, columns) -> List[str]:
        """Return WTForms validator class names needed for these columns."""
        validators: set = {'DataRequired'}
        for col in columns:
            name = col.get('name', '') if isinstance(col, dict) else getattr(col, 'name', '')
            if 'email' in name.lower():
                validators.add('Email')
            length = col.get('length') if isinstance(col, dict) else getattr(col, 'length', None)
            if length:
                validators.add('Length')
        return sorted(validators)

    def _generate_export_settings(self, table_info) -> Dict[str, Any]:
        """Return export configuration for the table view."""
        return {
            'formats': ['csv', 'xlsx'],
            'max_rows': 10000,
            'include_headers': True,
        }

    def _generate_api_security(self, table_info) -> Dict[str, Any]:
        """Return API security settings for the table."""
        return {
            'requires_auth': True,
            'rate_limit': '100/hour',
            'allowed_methods': ['GET', 'POST', 'PUT', 'DELETE'],
        }

    def _get_serialization_fields(self, columns) -> List[Dict[str, Any]]:
        """Return marshmallow field dicts for API serialization."""
        _type_map = {
            'int': 'Integer', 'bool': 'Boolean', 'float': 'Float',
            'decimal': 'Float', 'date': 'DateTime', 'time': 'DateTime',
            'text': 'String', 'str': 'String',
        }
        fields_out = []
        for col in columns:
            if isinstance(col, dict):
                name, nullable, comment, type_str = (
                    col.get('name', ''), col.get('nullable', True),
                    col.get('comment', ''), str(col.get('type', 'str')).lower()
                )
            else:
                name, nullable, comment = col.name, col.nullable, col.comment or ''
                type_str = str(col.type).lower()
            ma_type = next((v for k, v in _type_map.items() if k in type_str), 'String')
            desc = comment or name.replace('_', ' ').title()
            required = not nullable
            args_parts = []
            if required:
                args_parts.append('required=True')
            if desc:
                args_parts.append(f"description='{desc}'")
            fields_out.append({
                'name': name,
                'type': ma_type,
                'required': required,
                'description': desc,
                'args': ', '.join(args_parts),
            })
        return fields_out

    def _generate_api_endpoints(self, table_info) -> List[Dict[str, Any]]:
        """Return API endpoint definitions for the table."""
        name = table_info.name
        return [
            {'method': 'GET',    'path': f'/{name}/',    'description': f'List {name}'},
            {'method': 'POST',   'path': f'/{name}/',    'description': f'Create {name}'},
            {'method': 'GET',    'path': f'/{name}/{{pk}}', 'description': f'Get {name}'},
            {'method': 'PUT',    'path': f'/{name}/{{pk}}', 'description': f'Update {name}'},
            {'method': 'DELETE', 'path': f'/{name}/{{pk}}', 'description': f'Delete {name}'},
        ]

    def _generate_chart_configs(self, numeric_columns, date_columns) -> List[Dict[str, Any]]:
        """Return chart configuration for numeric/date columns."""
        configs = []
        for col in numeric_columns:
            name = col.get('name') if isinstance(col, dict) else col.name
            configs.append({'column': name, 'chart_type': 'bar', 'label': name.replace('_', ' ').title()})
        return configs

    def _get_aggregation_options(self, columns=None) -> List[str]:
        """Return available aggregation functions for chart/report views."""
        return ['count', 'sum', 'avg', 'min', 'max']

    def _get_grouping_options(self, columns) -> List[str]:
        """Return column names suitable for grouping in chart/report views."""
        result = []
        for col in columns:
            name = col.get('name') if isinstance(col, dict) else col.name
            pk = col.get('primary_key', False) if isinstance(col, dict) else col.primary_key
            if not pk:
                result.append(name)
        return result[:5]  # limit to first 5

    def _get_report_columns(self, columns) -> List[str]:
        """Return column names to include in report views."""
        result = []
        for col in columns:
            pk = col.get('primary_key', False) if isinstance(col, dict) else col.primary_key
            if not pk:
                result.append(col.get('name') if isinstance(col, dict) else col.name)
        return result

    def _create_wizard_steps(self, columns) -> List[Dict[str, Any]]:
        """Return wizard step definitions for multi-step form views."""
        non_pk = [col for col in columns if not (col.get('primary_key', False) if isinstance(col, dict) else col.primary_key)]
        step_size = max(3, len(non_pk) // 3)
        steps = []
        for i, chunk in enumerate([non_pk[j:j+step_size] for j in range(0, len(non_pk), step_size)]):
            names = [c.get('name') if isinstance(c, dict) else c.name for c in chunk]
            steps.append({'title': f'Step {i + 1}', 'fields': names, 'description': f'Part {i + 1}'})
        return steps

    def _determine_event_fields(self, columns) -> Dict[str, str]:
        """Return start/end date column names for calendar views."""
        start, end = None, None
        for col in columns:
            lower = col.name.lower()
            if start is None and any(k in lower for k in ('start', 'begin', 'from', 'date')):
                start = col.name
            elif end is None and any(k in lower for k in ('end', 'finish', 'to', 'due')):
                end = col.name
        return {'start': start or 'created_at', 'end': end or start or 'created_at'}

    def _get_add_form(self, master_record=None) -> Dict[str, Any]:
        """Return add-form configuration."""
        return {'fields': [], 'master_record': master_record}

    def _get_edit_form(self, master_record=None) -> Dict[str, Any]:
        """Return edit-form configuration."""
        return {'fields': [], 'master_record': master_record}
