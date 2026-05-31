"""
nx_widgets — backwards-compatible shim.

All widget classes have been moved to their respective submodules.
This file re-exports everything so existing code continues to work.
Import directly from the submodule for new code.
"""
from __future__ import annotations

from pgappforge.widgets.analytics.kpi import KPIDashboardWidget
from pgappforge.widgets.analytics.pivot import PivotTableWidget
from pgappforge.widgets.data.db_structure import DatabaseStructureWidget
from pgappforge.widgets.data.import_export import DataImportExportWidget
from pgappforge.widgets.data.json_editor import JSONEditorWidget
from pgappforge.widgets.data.profiler import DataPreviewProfilerWidget
from pgappforge.widgets.data.spreadsheet import SpreadsheetWidget
from pgappforge.widgets.data.validation import DataValidationRulesBuilder
from pgappforge.widgets.editing.code_editor import CodeEditorWidget
from pgappforge.widgets.editing.dbml import DBMLEditorWidget
from pgappforge.widgets.editing.markdown import MarkdownEditorWidget
from pgappforge.widgets.editing.mermaid import MermaidEditorWidget
from pgappforge.widgets.editing.richtext import RichTextEditorWidget
from pgappforge.widgets.forms.builder import FormBuilderWidget
from pgappforge.widgets.forms.color_picker import ColorPickerWidget
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
from pgappforge.widgets.visualization.gps import GPSTrackerWidget
from pgappforge.widgets.workflow.designer import WorkflowDesignerWidget
from pgappforge.widgets.workflow.diagram import WorkflowDiagramWidget
from pgappforge.widgets.workflow.gantt import GanttChartWidget
from pgappforge.widgets.workflow.kanban import KanbanBoardWidget
from pgappforge.widgets.workflow.wizard import StepWizardWidget

# Legacy alias — use QrCodeWidget from pgappforge.widgets.media instead
from pgappforge.widgets.media._qrcode_legacy import QRCodeWidget

__all__ = [
    'ActivityTimelineWidget',
    'AddressAutocompleteWidget',
    'AudioRecordingAndPlaybackWidget',
    'AuditLogViewerWidget',
    'BarcodeQRScannerWidget',
    'ChatMessagingWidget',
    'CheckBoxWidget',
    'CodeEditorWidget',
    'ColorPickerWidget',
    'CommentAndLikeWidget',
    'CurrencyInputWidget',
    'DBMLEditorWidget',
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
    'FormBuilderWidget',
    'FriendFollowWidget',
    'GPSTrackerWidget',
    'GanttChartWidget',
    'GeoPointWidget',
    'GeographicHeatmapWidget',
    'ImageCropWidget',
    'ImageProcessingConfig',
    'JSONEditorWidget',
    'KPIDashboardWidget',
    'KanbanBoardWidget',
    'MapWidget',
    'MarkdownEditorWidget',
    'MermaidEditorWidget',
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
    'TagInputWidget',
    'TimeField',
    'TimePickerWidget',
    'ToggleButtonWidget',
    'TreeViewWidget',
    'VersionControlWidget',
    'VideoRecordAndPlayWidget',
    'VirtualScrollingListWidget',
    'WorkflowDesignerWidget',
    'WorkflowDiagramWidget',
    'QRCodeWidget',
]
