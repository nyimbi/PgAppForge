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
    from .media import QrCodeWidget, BarcodeWidget
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
        'BarcodeWidget',
        'AdvancedChartsWidget',
        'ColorPickerWidget'
    ])



try:
    from pgappforge.widgets.analytics.kpi import KPIDashboardWidget
    from pgappforge.widgets.analytics.pivot import PivotTableWidget
    from pgappforge.widgets.data.db_structure import DatabaseStructureWidget
    from pgappforge.widgets.data.import_export import DataImportExportWidget
    from pgappforge.widgets.data.json_editor import JSONEditorWidget
    from pgappforge.widgets.data.profiler import DataPreviewProfilerWidget
    from pgappforge.widgets.data.spreadsheet import SpreadsheetWidget
    from pgappforge.widgets.data.validation import DataValidationRulesBuilder
    from pgappforge.widgets.editing.markdown import MarkdownEditorWidget
    from pgappforge.widgets.editing.richtext import RichTextEditorWidget
    from pgappforge.widgets.forms.builder import FormBuilderWidget
    from pgappforge.widgets.forms.upload import FileUploadFieldWidget
    from pgappforge.widgets.geo.address import AddressAutocompleteWidget
    from pgappforge.widgets.geo.geopoint import GeoPointWidget
    from pgappforge.widgets.geo.heatmap import GeographicHeatmapWidget
    from pgappforge.widgets.geo.map import MapWidget
    from pgappforge.widgets.input.date import DateRangePickerWidget
    from pgappforge.widgets.input.numeric import CurrencyInputWidget, DurationWidget, RatingWidget, StarRatingWidget
    from pgappforge.widgets.input.phone import PhoneNumberWidget
    from pgappforge.widgets.input.range import RangeSliderWidget, SliderWidget
    from pgappforge.widgets.input.select import DependentSelectWidget, MultiSelectWidget, TagInputWidget
    from pgappforge.widgets.input.text import PasswordStrengthWidget
    from pgappforge.widgets.input.time import TimeField, TimePickerWidget
    from pgappforge.widgets.input.toggle import CheckBoxWidget, SwitchWidget, ToggleButtonWidget
    from pgappforge.widgets.layout.dashboard import DashboardDesignerWidget
    from pgappforge.widgets.layout.graph import RelationshipGraphWidget
    from pgappforge.widgets.layout.timeline import ActivityTimelineWidget
    from pgappforge.widgets.layout.tree import TreeViewWidget
    from pgappforge.widgets.layout.version import VersionControlWidget
    from pgappforge.widgets.layout.virtual_list import VirtualScrollingListWidget
    from pgappforge.widgets.media.audio import AudioRecordingAndPlaybackWidget
    from pgappforge.widgets.media.barcode_scanner import BarcodeQRScannerWidget
    from pgappforge.widgets.media.camera import PeriodicCameraWidget
    from pgappforge.widgets.media.document import DocumentViewerWidget
    from pgappforge.widgets.media.image import ImageCropWidget, ImageProcessingConfig
    from pgappforge.widgets.media.signature import SignaturePadWidget
    from pgappforge.widgets.media.video import VideoRecordAndPlayWidget
    from pgappforge.widgets.social.audit import AuditLogViewerWidget
    from pgappforge.widgets.social.chat import ChatMessagingWidget
    from pgappforge.widgets.social.comments import CommentAndLikeWidget
    from pgappforge.widgets.social.follow import FriendFollowWidget
    from pgappforge.widgets.workflow.designer import WorkflowDesignerWidget
    from pgappforge.widgets.workflow.diagram import WorkflowDiagramWidget
    from pgappforge.widgets.workflow.gantt import GanttChartWidget
    from pgappforge.widgets.workflow.kanban import KanbanBoardWidget
    from pgappforge.widgets.workflow.wizard import StepWizardWidget
    EXTENDED_WIDGETS_AVAILABLE = True
except ImportError:
    EXTENDED_WIDGETS_AVAILABLE = False

if EXTENDED_WIDGETS_AVAILABLE:
    __all__.extend([
        'ActivityTimelineWidget',
        'AddressAutocompleteWidget',
        'AudioRecordingAndPlaybackWidget',
        'AuditLogViewerWidget',
        'BarcodeQRScannerWidget',
        'ChatMessagingWidget',
        'CheckBoxWidget',
        'CommentAndLikeWidget',
        'CurrencyInputWidget',
        'DashboardDesignerWidget',
        'DataImportExportWidget',
        'DataPreviewProfilerWidget',
        'DataValidationRulesBuilder',
        'DatabaseStructureWidget',
        'DateRangePickerWidget',
        'DependentSelectWidget',
        'DocumentViewerWidget',
        'DurationWidget',
        'FileUploadFieldWidget',
        'FriendFollowWidget',
        'GanttChartWidget',
        'GeoPointWidget',
        'GeographicHeatmapWidget',
        'ImageCropWidget',
        'ImageProcessingConfig',
        'KPIDashboardWidget',
        'KanbanBoardWidget',
        'MapWidget',
        'MarkdownEditorWidget',
        'MultiSelectWidget',
        'PasswordStrengthWidget',
        'PeriodicCameraWidget',
        'PhoneNumberWidget',
        'PivotTableWidget',
        'RangeSliderWidget',
        'RatingWidget',
        'RelationshipGraphWidget',
        'RichTextEditorWidget',
        'SignaturePadWidget',
        'SliderWidget',
        'SpreadsheetWidget',
        'StarRatingWidget',
        'StepWizardWidget',
        'SwitchWidget',
        'TimeField',
        'TimePickerWidget',
        'ToggleButtonWidget',
        'TreeViewWidget',
        'VersionControlWidget',
        'VideoRecordAndPlayWidget',
        'VirtualScrollingListWidget',
        'WorkflowDesignerWidget',
        'WorkflowDiagramWidget',
    ])

    _EXTENDED_REGISTRY = {
        'ActivityTimelineWidget': ActivityTimelineWidget,
        'BarcodeQRScannerWidget': BarcodeQRScannerWidget,
        'AddressAutocompleteWidget': AddressAutocompleteWidget,
        'AudioRecordingAndPlaybackWidget': AudioRecordingAndPlaybackWidget,
        'AuditLogViewerWidget': AuditLogViewerWidget,
        'ChatMessagingWidget': ChatMessagingWidget,
        'CheckBoxWidget': CheckBoxWidget,
        'CommentAndLikeWidget': CommentAndLikeWidget,
        'CurrencyInputWidget': CurrencyInputWidget,
        'DashboardDesignerWidget': DashboardDesignerWidget,
        'DataImportExportWidget': DataImportExportWidget,
        'DataPreviewProfilerWidget': DataPreviewProfilerWidget,
        'DataValidationRulesBuilder': DataValidationRulesBuilder,
        'DatabaseStructureWidget': DatabaseStructureWidget,
        'DateRangePickerWidget': DateRangePickerWidget,
        'DependentSelectWidget': DependentSelectWidget,
        'DocumentViewerWidget': DocumentViewerWidget,
        'DurationWidget': DurationWidget,
        'FileUploadFieldWidget': FileUploadFieldWidget,
        'FriendFollowWidget': FriendFollowWidget,
        'GanttChartWidget': GanttChartWidget,
        'GeoPointWidget': GeoPointWidget,
        'GeographicHeatmapWidget': GeographicHeatmapWidget,
        'ImageCropWidget': ImageCropWidget,
        'ImageProcessingConfig': ImageProcessingConfig,
        'KPIDashboardWidget': KPIDashboardWidget,
        'KanbanBoardWidget': KanbanBoardWidget,
        'MapWidget': MapWidget,
        'MarkdownEditorWidget': MarkdownEditorWidget,
        'MultiSelectWidget': MultiSelectWidget,
        'PasswordStrengthWidget': PasswordStrengthWidget,
        'PeriodicCameraWidget': PeriodicCameraWidget,
        'PhoneNumberWidget': PhoneNumberWidget,
        'PivotTableWidget': PivotTableWidget,
        'RangeSliderWidget': RangeSliderWidget,
        'RatingWidget': RatingWidget,
        'RelationshipGraphWidget': RelationshipGraphWidget,
        'RichTextEditorWidget': RichTextEditorWidget,
        'SignaturePadWidget': SignaturePadWidget,
        'SliderWidget': SliderWidget,
        'SpreadsheetWidget': SpreadsheetWidget,
        'StarRatingWidget': StarRatingWidget,
        'StepWizardWidget': StepWizardWidget,
        'SwitchWidget': SwitchWidget,
        'TimeField': TimeField,
        'TimePickerWidget': TimePickerWidget,
        'ToggleButtonWidget': ToggleButtonWidget,
        'TreeViewWidget': TreeViewWidget,
        'VersionControlWidget': VersionControlWidget,
        'VideoRecordAndPlayWidget': VideoRecordAndPlayWidget,
        'VirtualScrollingListWidget': VirtualScrollingListWidget,
        'WorkflowDesignerWidget': WorkflowDesignerWidget,
        'WorkflowDiagramWidget': WorkflowDiagramWidget,
    }
else:
    _EXTENDED_REGISTRY = {}

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
            'BarcodeWidget': BarcodeWidget,
            'AdvancedChartsWidget': AdvancedChartsWidget,
            'ColorPickerWidget': ColorPickerWidget,
        }

    if _EXTENDED_REGISTRY:
        # Organised by subpackage
        for key in ('input', 'geo', 'media_extended', 'workflow', 'layout',
                    'data', 'analytics', 'social', 'forms_extended'):
            widgets.setdefault(key, {})
        for name, cls in _EXTENDED_REGISTRY.items():
            mod = getattr(cls, '__module__', '')
            if '.input.' in mod:       widgets['input'][name] = cls
            elif '.geo.' in mod:       widgets['geo'][name] = cls
            elif '.media.' in mod:     widgets['media_extended'][name] = cls
            elif '.workflow.' in mod:  widgets['workflow'][name] = cls
            elif '.layout.' in mod:    widgets['layout'][name] = cls
            elif '.data.' in mod:      widgets['data'][name] = cls
            elif '.analytics.' in mod: widgets['analytics'][name] = cls
            elif '.social.' in mod:    widgets['social'][name] = cls
            else:                      widgets['forms_extended'][name] = cls
        # Remove empty buckets
        widgets = {k: v for k, v in widgets.items() if v}

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

# ─── New widget modules ────────────────────────────────────────────────────────
try:
    from .display_widgets import (
        StatCardWidget, SparklineWidget, HeatmapCalendarWidget, EmbeddedChartWidget,
    )
except ImportError:
    pass

try:
    from .action_widgets import (
        ApprovalButtonWidget, BulkActionWidget, DiffViewerWidget, TimelineWidget,
    )
except ImportError:
    pass

try:
    from .advanced_input_widgets import (
        RecurringScheduleWidget, MentionWidget, CurrencyConverterWidget,
        PhoneDialWidget, DocumentPreviewWidget, ConversationWidget,
    )
except ImportError:
    pass

try:
    from .data_widgets import (
        DataGridWidget, DataImportWidget, EmbeddedMapWidget, RelationshipGraphWidget,
    )
except ImportError:
    pass

try:
    from .dev_widgets import SQLEditorWidget, APITesterWidget
except ImportError:
    pass

try:
    from .project_widgets import (
        GanttWidget, KanbanWidget, ResourceCalendarWidget,
        SprintBurndownWidget, MilestoneTimelineWidget, WBSWidget, PERTWidget,
    )
except ImportError:
    pass

try:
    from .markdown_widget import MarkdownEditorWidget, MarkdownDisplayWidget, MarkdownPreviewWidget
except ImportError:
    pass

try:
    from .icd10_widget import ICD10SearchWidget, ICD10Field, register_icd10_blueprint
except ImportError:
    pass

try:
    from .snomed_widget import SNOMEDSearchWidget, SNOMEDField, register_snomed_blueprint
except ImportError:
    pass
