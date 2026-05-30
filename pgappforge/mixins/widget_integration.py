"""
Widget Integration System for Mixin-Enhanced Models

This module automatically maps appropriate widgets to model fields based on
the mixins used, providing optimal UI components for enhanced functionality.
"""

import logging
from typing import Dict, List, Any, Optional, Type, Union

log = logging.getLogger(__name__)

# Import only available PgAppForge widgets
try:
    from pgappforge.widgets import (
        FormWidget, ListWidget, ShowWidget, SearchWidget
    )
    from pgappforge.fieldwidgets import (
        Select2Widget, Select2ManyWidget, DatePickerWidget, DateTimePickerWidget
    )
    # Additional widgets that may be available
    try:
        from pgappforge.widgets import (
            GroupFormListWidget, ListMasterWidget
        )
    except ImportError:
        GroupFormListWidget = FormWidget  # Fallback
        ListMasterWidget = ListWidget      # Fallback
        
except ImportError as e:
    log.warning(f"Some PgAppForge widgets not available: {e}")
    # Define fallback widgets
    FormWidget = None
    ListWidget = None
    ShowWidget = None
    SearchWidget = None
    Select2Widget = None
    Select2ManyWidget = None
    DatePickerWidget = None
    DateTimePickerWidget = None


class MixinWidgetMapping:
    """
    Intelligent widget mapping system that selects optimal widgets
    based on model mixins and field characteristics.
    """
    
    # Widget mappings for different mixin types (using available widgets)
    MIXIN_WIDGET_MAP = {
        'MetadataMixin': {
            'metadata': FormWidget,  # Use basic form widget for JSON fields
            'metadata_json': FormWidget
        },
        
        'SearchableMixin': {
            'search_vector': FormWidget,      # Use basic form widget
            'searchable_content': FormWidget  # Use basic form widget
        },
        
        'InternationalizationMixin': {
            'translatable_fields': FormWidget  # Use basic form widget
        },
        
        'WorkflowMixin': {
            'current_state': Select2Widget() if Select2Widget else FormWidget,
            'workflow_data': FormWidget,  # Use basic form widget for JSON
            'state_history': FormWidget   # Use basic form widget
        },
        
        'ApprovalWorkflowMixin': {
            'approval_status': Select2Widget() if Select2Widget else FormWidget,
            'approval_history': FormWidget  # Use basic form widget
        },
        
        'DocumentMixin': {
            'document_path': FormWidget,      # Use basic form widget for file paths
            'document_content': FormWidget,   # Use basic form widget for content
            'keywords': FormWidget,           # Use basic form widget for keywords
            'document_text': FormWidget,      # Use basic form widget for text
            'document_context': FormWidget    # Use basic form widget
        },
        
        'CommentableMixin': {
            'comment_text': FormWidget  # Use basic form widget
        },
        
        'SchedulingMixin': {
            'start_time': DateTimePickerWidget() if DateTimePickerWidget else FormWidget,
            'end_time': DateTimePickerWidget() if DateTimePickerWidget else FormWidget,
            'recurrence_pattern': FormWidget  # Use basic form widget for JSON
        },
        
        'GeoLocationMixin': {
            'latitude': FormWidget,   # Use basic form widget for coordinates
            'longitude': FormWidget,  # Use basic form widget for coordinates
            'address': FormWidget     # Use basic form widget for address
        },
        
        'CurrencyMixin': {
            'amount': FormWidget,     # Use basic form widget for amount
            'currency': Select2Widget() if Select2Widget else FormWidget
        },
        
        'ProjectMixin': {
            'project_data': FormWidget,  # Use basic form widget for JSON
            'project_tags': FormWidget,  # Use basic form widget for tags
            'milestones': FormWidget     # Use basic form widget for arrays
        },
        
        'VersioningMixin': {
            'version_data': FormWidget,  # Use basic form widget for JSON
            'version_number': FormWidget
        },
        
        'EncryptionMixin': {
            'encrypted_fields': FormWidget  # Use basic form widget
        },
        
        'SlugMixin': {
            'slug': FormWidget  # Use basic form widget
        },
        
        'TreeMixin': {
            'parent_id': Select2Widget() if Select2Widget else FormWidget,
            'tree_path': FormWidget  # Use basic form widget
        }
    }
    
    # Field type to widget mappings (using valid widgets)
    FIELD_TYPE_WIDGET_MAP = {
        'String': {
            'default': FormWidget,     # Use basic form widget
            'email': FormWidget,       # Use basic form widget
            'url': FormWidget,         # Use basic form widget  
            'password': FormWidget,    # Use basic form widget
            'color': FormWidget,       # Use basic form widget
            'tags': FormWidget         # Use basic form widget
        },
        
        'Text': {
            'default': FormWidget,     # Use basic form widget
            'rich_text': FormWidget,   # Use basic form widget
            'code': FormWidget,        # Use basic form widget
            'json': FormWidget         # Use basic form widget
        },
        
        'Integer': {
            'default': FormWidget
        },
        
        'DateTime': {
            'default': DateTimePickerWidget() if DateTimePickerWidget else FormWidget,
            'date_only': DatePickerWidget() if DatePickerWidget else FormWidget
        },
        
        'Boolean': {
            'default': Select2Widget() if Select2Widget else FormWidget
        },
        
        'Enum': {
            'default': Select2Widget() if Select2Widget else FormWidget,
            'multiple': Select2ManyWidget() if Select2ManyWidget else FormWidget
        }
    }
    
    @classmethod
    def get_widget_for_field(cls, model_class, field_name: str, field_type: str = None, 
                           field_info: Dict = None) -> Optional[Any]:
        """
        Get the optimal widget for a field based on model mixins and field characteristics.
        
        Args:
            model_class: The SQLAlchemy model class
            field_name: Name of the field
            field_type: Type of the field
            field_info: Additional field information
            
        Returns:
            Widget instance or None if no specific widget needed
        """
        field_info = field_info or {}
        
        # First check for mixin-specific mappings
        widget = cls._get_mixin_specific_widget(model_class, field_name)
        if widget:
            return widget
        
        # Then check for field-type specific mappings
        widget = cls._get_field_type_widget(field_name, field_type, field_info)
        if widget:
            return widget
        
        # Finally check for naming convention mappings
        widget = cls._get_convention_based_widget(field_name, field_info)
        if widget:
            return widget
        
        return None
    
    @classmethod
    def _get_mixin_specific_widget(cls, model_class, field_name: str) -> Optional[Any]:
        """Get widget based on model mixins."""
        for base in model_class.__mro__:
            mixin_name = base.__name__
            if mixin_name in cls.MIXIN_WIDGET_MAP:
                mixin_widgets = cls.MIXIN_WIDGET_MAP[mixin_name]
                if field_name in mixin_widgets:
                    return mixin_widgets[field_name]
        return None
    
    @classmethod
    def _get_field_type_widget(cls, field_name: str, field_type: str, 
                             field_info: Dict) -> Optional[Any]:
        """Get widget based on field type."""
        if not field_type or field_type not in cls.FIELD_TYPE_WIDGET_MAP:
            return None
        
        type_widgets = cls.FIELD_TYPE_WIDGET_MAP[field_type]
        
        # Check for specific subtypes based on field info
        subtype = field_info.get('subtype')
        if subtype and subtype in type_widgets:
            return type_widgets[subtype]
        
        # Check for naming conventions
        field_lower = field_name.lower()
        
        if field_type == 'String':
            if 'email' in field_lower:
                return type_widgets.get('email', type_widgets['default'])
            elif 'url' in field_lower or 'link' in field_lower:
                return type_widgets.get('url', type_widgets['default'])
            elif 'password' in field_lower:
                return type_widgets.get('password', type_widgets['default'])
            elif 'color' in field_lower:
                return type_widgets.get('color', type_widgets['default'])
            elif 'tag' in field_lower:
                return type_widgets.get('tags', type_widgets['default'])
        
        elif field_type == 'Text':
            if 'json' in field_lower:
                return type_widgets.get('json', type_widgets['default'])
            elif 'code' in field_lower or 'script' in field_lower:
                return type_widgets.get('code', type_widgets['default'])
            elif 'rich' in field_lower or 'formatted' in field_lower:
                return type_widgets.get('rich_text', type_widgets['default'])
        
        elif field_type == 'Integer':
            if 'percent' in field_lower:
                return type_widgets.get('percentage', type_widgets['default'])
            elif 'rating' in field_lower or 'score' in field_lower:
                return type_widgets.get('rating', type_widgets['default'])
        
        elif field_type == 'DateTime':
            if 'range' in field_lower or ('start' in field_lower and 'end' in field_lower):
                return type_widgets.get('range', type_widgets['default'])
            elif 'date' in field_lower and 'time' not in field_lower:
                return type_widgets.get('date_only', type_widgets['default'])
        
        return type_widgets.get('default')
    
    @classmethod
    def _get_convention_based_widget(cls, field_name: str, field_info: Dict) -> Optional[Any]:
        """Get widget based on naming conventions."""
        field_lower = field_name.lower()
        
        # Common naming patterns - using available widgets only
        if field_lower.endswith('_json') or field_lower.endswith('_data'):
            return FormWidget  # Use basic form widget for JSON fields
        
        elif field_lower.endswith('_tags') or field_lower.endswith('_keywords'):
            return FormWidget  # Use basic form widget for tags
        
        elif field_lower.endswith('_array') or field_lower.endswith('_list'):
            return FormWidget  # Use basic form widget for arrays
        
        elif field_lower.endswith('_file') or field_lower.endswith('_upload'):
            return FormWidget  # Use basic form widget for file uploads
        
        elif field_lower.endswith('_color') or field_lower.endswith('_colour'):
            return FormWidget  # Use basic form widget for colors
        
        elif field_lower.endswith('_range') or ('from' in field_lower and 'to' in field_lower):
            return DateTimePickerWidget() if DateTimePickerWidget else FormWidget
        
        elif field_lower.endswith('_long') or field_lower.endswith('_text') or field_lower.endswith('_description'):
            return FormWidget  # Use basic form widget for long text
        
        return None
    
    @classmethod
    def get_form_widget_mappings(cls, model_class) -> Dict[str, Any]:
        """
        Get complete widget mappings for a model's form fields.
        
        Args:
            model_class: The SQLAlchemy model class
            
        Returns:
            Dictionary mapping field names to widget instances
        """
        widget_mappings = {}
        
        # Get model columns
        try:
            from sqlalchemy import inspect
            inspector = inspect(model_class)
            
            for column in inspector.columns:
                field_name = column.name
                field_type = str(column.type.__class__.__name__)
                
                field_info = {
                    'nullable': column.nullable,
                    'default': column.default,
                    'primary_key': column.primary_key,
                    'foreign_key': bool(column.foreign_keys)
                }
                
                widget = cls.get_widget_for_field(
                    model_class, field_name, field_type, field_info
                )
                
                if widget:
                    widget_mappings[field_name] = widget
        
        except Exception as e:
            log.warning(f"Failed to get widget mappings for {model_class.__name__}: {e}")
        
        return widget_mappings
    
    @classmethod
    def apply_validation_rules(cls, model_class, widget_mappings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply validation rules to widgets based on model constraints.
        
        Args:
            model_class: The SQLAlchemy model class
            widget_mappings: Current widget mappings
            
        Returns:
            Updated widget mappings with validation rules
        """
        enhanced_mappings = {}
        
        try:
            from sqlalchemy import inspect
            inspector = inspect(model_class)
            
            for field_name, widget in widget_mappings.items():
                # Get column info
                column = None
                for col in inspector.columns:
                    if col.name == field_name:
                        column = col
                        break
                
                if not column:
                    enhanced_mappings[field_name] = widget
                    continue
                
                # Apply validation based on column constraints
                validation_rules = []
                
                # Required validation
                if not column.nullable:
                    validation_rules.append({'type': 'required'})
                
                # String length validation
                if hasattr(column.type, 'length') and column.type.length:
                    validation_rules.append({
                        'type': 'maxLength',
                        'options': {'max': column.type.length}
                    })
                
                # Numeric range validation
                if hasattr(column.type, 'scale') and column.type.scale:
                    validation_rules.append({'type': 'number'})
                
                # For now, just use the widget as-is since we're using basic PgAppForge widgets
                # Advanced validation would require custom widget implementations
                enhanced_mappings[field_name] = widget
        
        except Exception as e:
            log.warning(f"Failed to apply validation rules: {e}")
            enhanced_mappings = widget_mappings
        
        return enhanced_mappings


def auto_configure_model_widgets(model_class) -> Dict[str, Any]:
    """
    Automatically configure widgets for a model based on its mixins and fields.
    
    Args:
        model_class: The SQLAlchemy model class
        
    Returns:
        Dictionary of widget configurations for the model
    """
    # Get base widget mappings
    widget_mappings = MixinWidgetMapping.get_form_widget_mappings(model_class)
    
    # Apply validation rules
    widget_mappings = MixinWidgetMapping.apply_validation_rules(model_class, widget_mappings)
    
    # Log the configuration
    log.info(f"Auto-configured {len(widget_mappings)} widgets for {model_class.__name__}")
    
    return widget_mappings


def enhance_view_with_widgets(view_class, model_class):
    """
    Enhance a view class with automatically configured widgets.
    
    Args:
        view_class: The PgAppForge view class
        model_class: The SQLAlchemy model class
    """
    widget_mappings = auto_configure_model_widgets(model_class)
    
    if widget_mappings:
        # Set widget mappings on the view
        if not hasattr(view_class, 'add_form_widget'):
            view_class.add_form_widget = {}
        if not hasattr(view_class, 'edit_form_widget'):
            view_class.edit_form_widget = {}
        
        view_class.add_form_widget.update(widget_mappings)
        view_class.edit_form_widget.update(widget_mappings)
        
        log.info(f"Enhanced {view_class.__name__} with {len(widget_mappings)} widget mappings")


__all__ = [
    'MixinWidgetMapping',
    'auto_configure_model_widgets',
    'enhance_view_with_widgets'
]