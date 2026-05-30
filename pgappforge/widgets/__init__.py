"""
PgForge Widget System

Unified widget library providing core and enhanced widgets for PgForge applications.
This module consolidates all widget functionality in a single, consistent interface.

Created on Oct 12, 2013
Enhanced in 2024

@author: Daniel Gaspar
"""

# Import core widgets from the core module (equivalent to old widgets.py)
from .core import (
    RenderTemplateWidget,
    FormWidget,
    ListWidget, 
    SearchWidget,
    ShowWidget,
    GroupFormListWidget,
    ListMasterWidget,
    ListAddWidget,
    ListThumbnail,
    ListLinkWidget,
    ListCarousel,
    ListItem,
    ListBlock,
    ShowBlockWidget,
    ShowVerticalWidget,
    FormVerticalWidget,
    FormHorizontalWidget,
    FormInlineWidget,
    ApprovalWidget,
    MenuWidget,
    ChartWidget
)

# Import field widgets from parent directory
from ..fieldwidgets import (
    DatePickerWidget,
    DateTimePickerWidget,
    BS3TextFieldWidget,
    BS3PasswordFieldWidget,
    BS3TextAreaFieldWidget,
    Select2AJAXWidget,
    Select2SlaveAJAXWidget,
    Select2Widget,
    Select2ManyWidget
)

# Import enhanced widgets (only if dependencies are available)
try:
    from .modern_ui import (
        ModernTextWidget,
        ModernTextAreaWidget,
        ModernSelectWidget,
        FileUploadWidget,
        DateTimeRangeWidget,
        TagInputWidget,
        SignatureWidget
    )
    MODERN_UI_AVAILABLE = True
except ImportError:
    MODERN_UI_AVAILABLE = False

try:
    from .advanced_forms import (
        FormBuilderWidget,
        ValidationWidget
    )
    ADVANCED_FORMS_AVAILABLE = True
except ImportError:
    ADVANCED_FORMS_AVAILABLE = False

try:
    from .specialized_data import (
        JSONEditorWidget,
        ArrayEditorWidget
    )
    SPECIALIZED_DATA_AVAILABLE = True
except ImportError:
    SPECIALIZED_DATA_AVAILABLE = False

# Import modular widgets (new architecture) - These take priority over legacy widgets
try:
    from .visualization import GPSTrackerWidget
    from .editing import MermaidEditorWidget, DbmlEditorWidget, CodeEditorWidget
    from .media import QrCodeWidget
    from .charts import AdvancedChartsWidget
    from .forms import ColorPickerWidget
    MODULAR_WIDGETS_AVAILABLE = True
except ImportError:
    MODULAR_WIDGETS_AVAILABLE = False

# Core widgets - always available
CORE_WIDGETS = {
    'RenderTemplateWidget': RenderTemplateWidget,
    'FormWidget': FormWidget,
    'ListWidget': ListWidget,
    'SearchWidget': SearchWidget,
    'ShowWidget': ShowWidget,
    'GroupFormListWidget': GroupFormListWidget,
    'ListMasterWidget': ListMasterWidget,
    'ListAddWidget': ListAddWidget,
    'ListThumbnail': ListThumbnail,
    'ListLinkWidget': ListLinkWidget,
    'ListCarousel': ListCarousel,
    'ListItem': ListItem,
    'ListBlock': ListBlock,
    'ShowBlockWidget': ShowBlockWidget,
    'ShowVerticalWidget': ShowVerticalWidget,
    'FormVerticalWidget': FormVerticalWidget,
    'FormHorizontalWidget': FormHorizontalWidget,
    'FormInlineWidget': FormInlineWidget,
    'MenuWidget': MenuWidget,
    'ChartWidget': ChartWidget
}

# Field widgets - always available
FIELD_WIDGETS = {
    'DatePickerWidget': DatePickerWidget,
    'DateTimePickerWidget': DateTimePickerWidget,
    'BS3TextFieldWidget': BS3TextFieldWidget,
    'BS3PasswordFieldWidget': BS3PasswordFieldWidget,
    'BS3TextAreaFieldWidget': BS3TextAreaFieldWidget,
    'Select2AJAXWidget': Select2AJAXWidget,
    'Select2SlaveAJAXWidget': Select2SlaveAJAXWidget,
    'Select2Widget': Select2Widget,
    'Select2ManyWidget': Select2ManyWidget,
}

# Build exports list
__all__ = list(CORE_WIDGETS.keys()) + list(FIELD_WIDGETS.keys())

# Add enhanced widgets if available
if MODERN_UI_AVAILABLE:
    __all__.extend([
        'ModernTextWidget',
        'ModernTextAreaWidget',
        'ModernSelectWidget',
        # 'ColorPickerWidget',  # MIGRATED TO modular/forms
        'FileUploadWidget',
        'DateTimeRangeWidget',
        'TagInputWidget',
        'SignatureWidget'
        # 'CodeEditorWidget',  # MIGRATED TO modular/editing
        # 'AdvancedChartsWidget',  # MIGRATED TO modular/charts
    ])

if ADVANCED_FORMS_AVAILABLE:
    __all__.extend([
        'FormBuilderWidget',
        'ValidationWidget'
    ])

if SPECIALIZED_DATA_AVAILABLE:
    __all__.extend([
        'JSONEditorWidget',
        'ArrayEditorWidget'
    ])

if MODULAR_WIDGETS_AVAILABLE:
    __all__.extend([
        'GPSTrackerWidget',
        'MermaidEditorWidget',
        'DbmlEditorWidget',
        'CodeEditorWidget',
        'QrCodeWidget',
        'AdvancedChartsWidget',
        'ColorPickerWidget'
    ])


def get_available_widgets():
    """
    Get all available widgets organized by category.
    
    :return: Dictionary of available widgets by category
    """
    widgets = {
        'core': CORE_WIDGETS.copy(),
        'field': FIELD_WIDGETS.copy(),
    }
    
    if MODERN_UI_AVAILABLE:
        widgets['modern_ui'] = {
            'ModernTextWidget': ModernTextWidget,
            'ModernTextAreaWidget': ModernTextAreaWidget,
            'ModernSelectWidget': ModernSelectWidget,
            # 'ColorPickerWidget': ColorPickerWidget,  # MIGRATED TO modular/forms
            'FileUploadWidget': FileUploadWidget,
            'DateTimeRangeWidget': DateTimeRangeWidget,
            'TagInputWidget': TagInputWidget,
            'SignatureWidget': SignatureWidget,
            # 'CodeEditorWidget': CodeEditorWidget,  # MIGRATED TO modular/editing
            # 'AdvancedChartsWidget': AdvancedChartsWidget,  # MIGRATED TO modular/charts
        }
    
    if ADVANCED_FORMS_AVAILABLE:
        widgets['advanced_forms'] = {
            'FormBuilderWidget': FormBuilderWidget,
            'ValidationWidget': ValidationWidget,
        }
    
    if SPECIALIZED_DATA_AVAILABLE:
        widgets['specialized_data'] = {
            'JSONEditorWidget': JSONEditorWidget,
            'ArrayEditorWidget': ArrayEditorWidget,
        }

    if MODULAR_WIDGETS_AVAILABLE:
        widgets['modular'] = {
            'GPSTrackerWidget': GPSTrackerWidget,
            'MermaidEditorWidget': MermaidEditorWidget,
            'DbmlEditorWidget': DbmlEditorWidget,
            'CodeEditorWidget': CodeEditorWidget,
            'QrCodeWidget': QrCodeWidget,
            'AdvancedChartsWidget': AdvancedChartsWidget,
            'ColorPickerWidget': ColorPickerWidget,
        }

    return widgets


def get_widget_by_name(name):
    """
    Get a widget class by name.
    
    :param name: Widget class name
    :return: Widget class or None if not found
    """
    all_widgets = get_available_widgets()
    for category_widgets in all_widgets.values():
        if name in category_widgets:
            return category_widgets[name]
    return None


def get_widget_compatibility_info():
    """
    Get information about widget availability and compatibility.
    
    :return: Dictionary with compatibility information
    """
    return {
        'core_widgets_count': len(CORE_WIDGETS),
        'field_widgets_count': len(FIELD_WIDGETS),
        'modern_ui_available': MODERN_UI_AVAILABLE,
        'advanced_forms_available': ADVANCED_FORMS_AVAILABLE,
        'specialized_data_available': SPECIALIZED_DATA_AVAILABLE,
        'modular_widgets_available': MODULAR_WIDGETS_AVAILABLE,
        'total_widgets': len(__all__)
    }