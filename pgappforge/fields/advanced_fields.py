"""
Advanced Field Types for PgForge

Next-generation field types for modern web applications:
- ChartField: Interactive data visualization with Chart.js/D3.js
- MapField: Interactive maps with drawing tools and markers  
- CropperField: Advanced image cropping and editing
- SliderField: Multi-handle range sliders with custom formatting
- TreeSelectField: Hierarchical tree selection with lazy loading
- CalendarField: Full calendar with events and scheduling
- SwitchField: Advanced toggle switches with multiple states
- MarkdownField: Markdown editor with live preview
- MediaPlayerField: Audio/video player with playlist support
- BadgeField: Modern chip/badge selection with categories
"""

import json
import base64
import re
import hashlib
import secrets
from typing import Optional, Dict, Any, List, Union, Tuple
from enum import Enum
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, date, time
import calendar

from wtforms import Field, ValidationError, StringField, TextAreaField
from wtforms.widgets import HTMLString, html_params
from markupsafe import Markup
from sqlalchemy import TypeDecorator, Text, JSON, DateTime
from sqlalchemy.ext.mutable import MutableDict, MutableList

from flask import current_app, url_for, request
from flask_babel import gettext as __, lazy_gettext as _l


class ChartType(Enum):
    """Chart types for visualization."""
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    DOUGHNUT = "doughnut"
    RADAR = "radar"
    POLAR_AREA = "polarArea"
    SCATTER = "scatter"
    BUBBLE = "bubble"
    AREA = "area"
    HISTOGRAM = "histogram"


class MapProvider(Enum):
    """Map service providers."""
    LEAFLET = "leaflet"
    GOOGLE = "google"
    MAPBOX = "mapbox"
    OPENSTREETMAP = "osm"


class TreeSelectMode(Enum):
    """Tree selection modes."""
    SINGLE = "single"
    MULTIPLE = "multiple"
    CHECKBOX = "checkbox"
    RADIO = "radio"


class CalendarView(Enum):
    """Calendar view modes."""
    MONTH = "month"
    WEEK = "week"
    DAY = "day"
    AGENDA = "agenda"
    LIST = "list"


class SwitchType(Enum):
    """Switch types and behaviors."""
    TOGGLE = "toggle"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    SEGMENTED = "segmented"
    SLIDER = "slider"


class MarkdownFormat(Enum):
    """Markdown output formats."""
    MARKDOWN = "markdown"
    HTML = "html"
    PLAIN = "plain"
    PDF = "pdf"


class MediaType(Enum):
    """Media player types."""
    AUDIO = "audio"
    VIDEO = "video"
    PLAYLIST = "playlist"
    STREAM = "stream"


# ========================================
# Data Classes
# ========================================

@dataclass
class ChartData:
    """Chart configuration and data."""
    chart_type: str
    data: Dict[str, Any]
    options: Dict[str, Any] = field(default_factory=dict)
    plugins: List[str] = field(default_factory=list)
    width: int = 400
    height: int = 300
    responsive: bool = True
    animation: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChartData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class MapData:
    """Interactive map configuration."""
    provider: str
    center: Tuple[float, float]  # lat, lng
    zoom: int = 10
    markers: List[Dict[str, Any]] = field(default_factory=list)
    polygons: List[Dict[str, Any]] = field(default_factory=list)
    polylines: List[Dict[str, Any]] = field(default_factory=list)
    layers: List[Dict[str, Any]] = field(default_factory=list)
    drawing_enabled: bool = True
    clustering_enabled: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MapData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class CropperData:
    """Image cropper configuration and result."""
    image_data: str  # Base64 encoded image
    crop_area: Dict[str, float]  # x, y, width, height (normalized 0-1)
    aspect_ratio: Optional[float] = None
    min_crop_width: int = 50
    min_crop_height: int = 50
    rotation: float = 0.0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    quality: float = 0.8
    output_format: str = "jpeg"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CropperData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class SliderData:
    """Range slider configuration and values."""
    min_value: float
    max_value: float
    current_values: List[float]
    step: float = 1.0
    handle_count: int = 1
    logarithmic: bool = False
    format_string: str = "{value}"
    tooltips: bool = True
    connect: bool = True
    orientation: str = "horizontal"  # horizontal, vertical
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SliderData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class TreeNode:
    """Tree node structure."""
    id: str
    label: str
    children: List['TreeNode'] = field(default_factory=list)
    selected: bool = False
    expanded: bool = False
    disabled: bool = False
    icon: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        result['children'] = [child.to_dict() for child in self.children]
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TreeNode':
        """Create from dictionary."""
        children_data = data.pop('children', [])
        node = cls(**data)
        node.children = [cls.from_dict(child) for child in children_data]
        return node


@dataclass
class TreeSelectData:
    """Tree selection data."""
    nodes: List[TreeNode]
    selected_ids: List[str] = field(default_factory=list)
    mode: str = TreeSelectMode.SINGLE.value
    lazy_loading: bool = False
    search_enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'nodes': [node.to_dict() for node in self.nodes],
            'selected_ids': self.selected_ids,
            'mode': self.mode,
            'lazy_loading': self.lazy_loading,
            'search_enabled': self.search_enabled
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TreeSelectData':
        """Create from dictionary."""
        nodes_data = data.pop('nodes', [])
        tree_data = cls(**data)
        tree_data.nodes = [TreeNode.from_dict(node) for node in nodes_data]
        return tree_data


@dataclass
class CalendarEvent:
    """Calendar event structure."""
    id: str
    title: str
    start: datetime
    end: Optional[datetime] = None
    all_day: bool = False
    description: Optional[str] = None
    location: Optional[str] = None
    color: str = "#3788d8"
    recurring: Optional[Dict[str, Any]] = None
    attendees: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        result['start'] = self.start.isoformat()
        if self.end:
            result['end'] = self.end.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CalendarEvent':
        """Create from dictionary."""
        if 'start' in data and isinstance(data['start'], str):
            data['start'] = datetime.fromisoformat(data['start'])
        if 'end' in data and isinstance(data['end'], str):
            data['end'] = datetime.fromisoformat(data['end'])
        return cls(**data)


@dataclass
class CalendarData:
    """Calendar configuration and events."""
    events: List[CalendarEvent]
    view: str = CalendarView.MONTH.value
    timezone: str = "UTC"
    business_hours: Optional[Dict[str, Any]] = None
    selectable: bool = True
    editable: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'events': [event.to_dict() for event in self.events],
            'view': self.view,
            'timezone': self.timezone,
            'business_hours': self.business_hours,
            'selectable': self.selectable,
            'editable': self.editable
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CalendarData':
        """Create from dictionary."""
        events_data = data.pop('events', [])
        calendar_data = cls(**data)
        calendar_data.events = [CalendarEvent.from_dict(event) for event in events_data]
        return calendar_data


@dataclass
class SwitchOption:
    """Switch option configuration."""
    value: str
    label: str
    icon: Optional[str] = None
    color: Optional[str] = None
    disabled: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SwitchOption':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class SwitchData:
    """Switch field configuration."""
    options: List[SwitchOption]
    selected_values: List[str]
    switch_type: str = SwitchType.TOGGLE.value
    allow_multiple: bool = False
    animation: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'options': [option.to_dict() for option in self.options],
            'selected_values': self.selected_values,
            'switch_type': self.switch_type,
            'allow_multiple': self.allow_multiple,
            'animation': self.animation
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SwitchData':
        """Create from dictionary."""
        options_data = data.pop('options', [])
        switch_data = cls(**data)
        switch_data.options = [SwitchOption.from_dict(option) for option in options_data]
        return switch_data


@dataclass
class MarkdownData:
    """Markdown editor data."""
    content: str
    format: str = MarkdownFormat.MARKDOWN.value
    preview_enabled: bool = True
    math_enabled: bool = False
    table_support: bool = True
    emoji_support: bool = True
    word_count: int = 0
    character_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarkdownData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class MediaTrack:
    """Media track information."""
    id: str
    title: str
    src: str
    duration: Optional[float] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    thumbnail: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MediaTrack':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class MediaPlayerData:
    """Media player configuration."""
    tracks: List[MediaTrack]
    media_type: str = MediaType.AUDIO.value
    autoplay: bool = False
    loop: bool = False
    shuffle: bool = False
    volume: float = 0.8
    current_track: Optional[str] = None
    current_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'tracks': [track.to_dict() for track in self.tracks],
            'media_type': self.media_type,
            'autoplay': self.autoplay,
            'loop': self.loop,
            'shuffle': self.shuffle,
            'volume': self.volume,
            'current_track': self.current_track,
            'current_time': self.current_time
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MediaPlayerData':
        """Create from dictionary."""
        tracks_data = data.pop('tracks', [])
        media_data = cls(**data)
        media_data.tracks = [MediaTrack.from_dict(track) for track in tracks_data]
        return media_data


@dataclass
class BadgeCategory:
    """Badge category configuration."""
    id: str
    name: str
    color: str
    icon: Optional[str] = None
    badges: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BadgeCategory':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class Badge:
    """Badge/chip configuration."""
    id: str
    label: str
    category_id: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    image: Optional[str] = None
    removable: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Badge':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class BadgeFieldData:
    """Badge field data structure."""
    selected_badges: List[Badge]
    categories: List[BadgeCategory]
    max_badges: int = 20
    allow_custom: bool = True
    searchable: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'selected_badges': [badge.to_dict() for badge in self.selected_badges],
            'categories': [category.to_dict() for category in self.categories],
            'max_badges': self.max_badges,
            'allow_custom': self.allow_custom,
            'searchable': self.searchable
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BadgeFieldData':
        """Create from dictionary."""
        badges_data = data.pop('selected_badges', [])
        categories_data = data.pop('categories', [])
        badge_data = cls(**data)
        badge_data.selected_badges = [Badge.from_dict(badge) for badge in badges_data]
        badge_data.categories = [BadgeCategory.from_dict(cat) for cat in categories_data]
        return badge_data


@dataclass
class DualListItem:
    """Dual list box item."""
    id: str
    label: str
    value: str = None
    icon: Optional[str] = None
    disabled: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.value is None:
            self.value = self.id
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DualListItem':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class DualListBoxData:
    """Dual list box configuration and data."""
    available_items: List[DualListItem]
    selected_items: List[DualListItem]
    searchable: bool = True
    sortable: bool = True
    show_move_all: bool = True
    show_move_up_down: bool = False
    preserve_selection_order: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'available_items': [item.to_dict() for item in self.available_items],
            'selected_items': [item.to_dict() for item in self.selected_items],
            'searchable': self.searchable,
            'sortable': self.sortable,
            'show_move_all': self.show_move_all,
            'show_move_up_down': self.show_move_up_down,
            'preserve_selection_order': self.preserve_selection_order
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DualListBoxData':
        """Create from dictionary."""
        available_data = data.pop('available_items', [])
        selected_data = data.pop('selected_items', [])
        dual_list_data = cls(**data)
        dual_list_data.available_items = [DualListItem.from_dict(item) for item in available_data]
        dual_list_data.selected_items = [DualListItem.from_dict(item) for item in selected_data]
        return dual_list_data


# ========================================
# SQLAlchemy Type Decorators
# ========================================

class ChartType(TypeDecorator):
    """SQLAlchemy type for chart data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, ChartData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return ChartData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class MapType(TypeDecorator):
    """SQLAlchemy type for map data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, MapData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return MapData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class CropperType(TypeDecorator):
    """SQLAlchemy type for cropper data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, CropperData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return CropperData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class CalendarType(TypeDecorator):
    """SQLAlchemy type for calendar data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, CalendarData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return CalendarData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class MarkdownType(TypeDecorator):
    """SQLAlchemy type for markdown data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, MarkdownData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
            elif isinstance(value, str):
                return value
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return MarkdownData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class DualListBoxType(TypeDecorator):
    """SQLAlchemy type for dual list box data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, DualListBoxData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return DualListBoxData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


# ========================================
# Widget Classes
# ========================================

class ChartWidget:
    """Widget for interactive charts."""
    
    def __init__(self, chart_type: ChartType = ChartType.LINE, width: int = 400, height: int = 300):
        self.chart_type = chart_type
        self.width = width
        self.height = height
    
    def __call__(self, field, **kwargs):
        """Render the chart widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, ChartData):
                chart_data = field.data.to_dict()
            elif isinstance(field.data, dict):
                chart_data = field.data
            else:
                chart_data = {}
        else:
            chart_data = {
                'chart_type': self.chart_type.value,
                'data': {'labels': [], 'datasets': []},
                'width': self.width,
                'height': self.height
            }
        
        chart_id = f"chart_{field.id}_{secrets.token_hex(4)}"
        chart_json = json.dumps(chart_data)
        
        html = f'''
        <div class="chart-container">
            <div class="chart-toolbar">
                <select class="chart-type-selector" data-target="{chart_id}">
                    <option value="line" {"selected" if chart_data.get('chart_type') == 'line' else ""}>Line Chart</option>
                    <option value="bar" {"selected" if chart_data.get('chart_type') == 'bar' else ""}>Bar Chart</option>
                    <option value="pie" {"selected" if chart_data.get('chart_type') == 'pie' else ""}>Pie Chart</option>
                    <option value="doughnut" {"selected" if chart_data.get('chart_type') == 'doughnut' else ""}>Doughnut Chart</option>
                    <option value="radar" {"selected" if chart_data.get('chart_type') == 'radar' else ""}>Radar Chart</option>
                    <option value="scatter" {"selected" if chart_data.get('chart_type') == 'scatter' else ""}>Scatter Plot</option>
                </select>
                <button type="button" class="add-dataset-btn" data-target="{chart_id}">Add Dataset</button>
                <button type="button" class="export-chart-btn" data-target="{chart_id}">Export</button>
                <button type="button" class="fullscreen-chart-btn" data-target="{chart_id}">Fullscreen</button>
            </div>
            
            <div class="chart-canvas-container">
                <canvas id="{chart_id}" 
                        class="chart-canvas"
                        width="{self.width}" 
                        height="{self.height}"
                        data-chart-config='{chart_json}'></canvas>
            </div>
            
            <div class="chart-data-editor" style="display: none;">
                <div class="data-editor-tabs">
                    <button class="tab-btn active" data-tab="data">Data</button>
                    <button class="tab-btn" data-tab="options">Options</button>
                    <button class="tab-btn" data-tab="styling">Styling</button>
                </div>
                
                <div class="tab-content active" data-tab="data">
                    <textarea class="chart-data-input" placeholder="Enter chart data (JSON format)"></textarea>
                </div>
                
                <div class="tab-content" data-tab="options">
                    <div class="option-group">
                        <label>Animation:</label>
                        <input type="checkbox" class="animation-toggle" checked />
                    </div>
                    <div class="option-group">
                        <label>Responsive:</label>
                        <input type="checkbox" class="responsive-toggle" checked />
                    </div>
                    <div class="option-group">
                        <label>Legend:</label>
                        <input type="checkbox" class="legend-toggle" checked />
                    </div>
                </div>
                
                <div class="tab-content" data-tab="styling">
                    <div class="style-group">
                        <label>Background Color:</label>
                        <input type="color" class="bg-color-input" value="#ffffff" />
                    </div>
                    <div class="style-group">
                        <label>Border Color:</label>
                        <input type="color" class="border-color-input" value="#cccccc" />
                    </div>
                </div>
            </div>
            
            <input type="hidden" id="{chart_id}_data" name="{field.name}" value='{chart_json}' />
        </div>
        '''
        
        return HTMLString(html)


class MapWidget:
    """Widget for interactive maps."""
    
    def __init__(self, provider: MapProvider = MapProvider.LEAFLET, height: int = 400):
        self.provider = provider
        self.height = height
    
    def __call__(self, field, **kwargs):
        """Render the map widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, MapData):
                map_data = field.data.to_dict()
            elif isinstance(field.data, dict):
                map_data = field.data
            else:
                map_data = {}
        else:
            map_data = {
                'provider': self.provider.value,
                'center': [40.7128, -74.0060],  # New York
                'zoom': 10,
                'markers': [],
                'polygons': [],
                'polylines': []
            }
        
        map_id = f"map_{field.id}_{secrets.token_hex(4)}"
        map_json = json.dumps(map_data)
        
        html = f'''
        <div class="map-container">
            <div class="map-toolbar">
                <button type="button" class="map-tool active" data-tool="pan" data-target="{map_id}">
                    🤚 Pan
                </button>
                <button type="button" class="map-tool" data-tool="marker" data-target="{map_id}">
                    📍 Marker
                </button>
                <button type="button" class="map-tool" data-tool="polygon" data-target="{map_id}">
                    ⬟ Polygon
                </button>
                <button type="button" class="map-tool" data-tool="polyline" data-target="{map_id}">
                    📏 Line
                </button>
                <button type="button" class="map-tool" data-tool="circle" data-target="{map_id}">
                    ⭕ Circle
                </button>
                <button type="button" class="clear-map-btn" data-target="{map_id}">
                    🗑️ Clear
                </button>
                <button type="button" class="locate-btn" data-target="{map_id}">
                    🎯 My Location
                </button>
                <button type="button" class="fullscreen-map-btn" data-target="{map_id}">
                    ⛶ Fullscreen
                </button>
            </div>
            
            <div id="{map_id}" 
                 class="map-canvas"
                 style="height: {self.height}px;"
                 data-map-config='{map_json}'></div>
            
            <div class="map-coordinates">
                <span class="current-coords">Lat: 0.0000, Lng: 0.0000</span>
                <span class="zoom-level">Zoom: 10</span>
            </div>
            
            <div class="map-layers-panel" style="display: none;">
                <h4>Layers</h4>
                <div class="layer-list">
                    <div class="layer-item">
                        <input type="checkbox" id="markers-layer" checked />
                        <label for="markers-layer">Markers</label>
                    </div>
                    <div class="layer-item">
                        <input type="checkbox" id="polygons-layer" checked />
                        <label for="polygons-layer">Polygons</label>
                    </div>
                    <div class="layer-item">
                        <input type="checkbox" id="polylines-layer" checked />
                        <label for="polylines-layer">Lines</label>
                    </div>
                </div>
            </div>
            
            <input type="hidden" id="{map_id}_data" name="{field.name}" value='{map_json}' />
        </div>
        '''
        
        return HTMLString(html)


class CropperWidget:
    """Widget for image cropping."""
    
    def __init__(self, aspect_ratio: Optional[float] = None, min_width: int = 50, min_height: int = 50):
        self.aspect_ratio = aspect_ratio
        self.min_width = min_width
        self.min_height = min_height
    
    def __call__(self, field, **kwargs):
        """Render the cropper widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        cropper_id = f"cropper_{field.id}_{secrets.token_hex(4)}"
        aspect_ratio = self.aspect_ratio or 0  # 0 = free aspect ratio
        
        html = f'''
        <div class="cropper-container">
            <div class="cropper-toolbar">
                <input type="file" id="{cropper_id}_file" class="file-input" accept="image/*" />
                <label for="{cropper_id}_file" class="upload-btn">📷 Upload Image</label>
                
                <div class="aspect-ratio-group">
                    <label>Aspect Ratio:</label>
                    <select class="aspect-ratio-selector" data-target="{cropper_id}">
                        <option value="0" {"selected" if aspect_ratio == 0 else ""}>Free</option>
                        <option value="1" {"selected" if aspect_ratio == 1 else ""}>1:1 (Square)</option>
                        <option value="1.333" {"selected" if abs(aspect_ratio - 1.333) < 0.01 else ""}>4:3</option>
                        <option value="1.777" {"selected" if abs(aspect_ratio - 1.777) < 0.01 else ""}>16:9</option>
                        <option value="0.667" {"selected" if abs(aspect_ratio - 0.667) < 0.01 else ""}>2:3</option>
                    </select>
                </div>
                
                <button type="button" class="rotate-left-btn" data-target="{cropper_id}">↺ Rotate Left</button>
                <button type="button" class="rotate-right-btn" data-target="{cropper_id}">↻ Rotate Right</button>
                <button type="button" class="flip-horizontal-btn" data-target="{cropper_id}">⇄ Flip H</button>
                <button type="button" class="flip-vertical-btn" data-target="{cropper_id}">⇅ Flip V</button>
                <button type="button" class="reset-btn" data-target="{cropper_id}">🔄 Reset</button>
                <button type="button" class="crop-btn" data-target="{cropper_id}">✂️ Crop</button>
            </div>
            
            <div class="cropper-canvas-container">
                <div id="{cropper_id}" 
                     class="cropper-canvas"
                     data-aspect-ratio="{aspect_ratio}"
                     data-min-width="{self.min_width}"
                     data-min-height="{self.min_height}">
                    <div class="cropper-placeholder">
                        <div class="placeholder-icon">📷</div>
                        <div class="placeholder-text">Click "Upload Image" to start cropping</div>
                    </div>
                </div>
            </div>
            
            <div class="cropper-info">
                <div class="image-info">
                    <span class="image-size">No image</span>
                    <span class="crop-size">Crop: 0×0</span>
                </div>
                <div class="quality-control">
                    <label>Quality:</label>
                    <input type="range" class="quality-slider" min="0.1" max="1" step="0.1" value="0.8" data-target="{cropper_id}" />
                    <span class="quality-value">80%</span>
                </div>
            </div>
            
            <input type="hidden" id="{cropper_id}_data" name="{field.name}" />
        </div>
        '''
        
        return HTMLString(html)


class SliderWidget:
    """Widget for range sliders."""
    
    def __init__(self, min_value: float = 0, max_value: float = 100, step: float = 1, handle_count: int = 1):
        self.min_value = min_value
        self.max_value = max_value
        self.step = step
        self.handle_count = handle_count
    
    def __call__(self, field, **kwargs):
        """Render the slider widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, SliderData):
                slider_data = field.data
            elif isinstance(field.data, dict):
                slider_data = SliderData.from_dict(field.data)
            else:
                values = [float(field.data)] if field.data else [self.min_value]
                slider_data = SliderData(
                    min_value=self.min_value,
                    max_value=self.max_value,
                    current_values=values,
                    step=self.step,
                    handle_count=self.handle_count
                )
        else:
            slider_data = SliderData(
                min_value=self.min_value,
                max_value=self.max_value,
                current_values=[self.min_value] * self.handle_count,
                step=self.step,
                handle_count=self.handle_count
            )
        
        slider_id = f"slider_{field.id}_{secrets.token_hex(4)}"
        slider_json = json.dumps(slider_data.to_dict())
        
        html = f'''
        <div class="slider-container">
            <div class="slider-header">
                <div class="slider-values">
        '''
        
        for i in range(slider_data.handle_count):
            value = slider_data.current_values[i] if i < len(slider_data.current_values) else slider_data.min_value
            html += f'''
                    <div class="value-display">
                        <label>Value {i + 1}:</label>
                        <span class="value-text" data-handle="{i}">{value}</span>
                    </div>
            '''
        
        html += f'''
                </div>
                <div class="slider-controls">
                    <div class="control-group">
                        <label>Step:</label>
                        <input type="number" class="step-input" value="{slider_data.step}" 
                               min="0.01" step="0.01" data-target="{slider_id}" />
                    </div>
                    <div class="control-group">
                        <label>Logarithmic:</label>
                        <input type="checkbox" class="log-toggle" 
                               {"checked" if slider_data.logarithmic else ""} 
                               data-target="{slider_id}" />
                    </div>
                    <div class="control-group">
                        <label>Tooltips:</label>
                        <input type="checkbox" class="tooltip-toggle" 
                               {"checked" if slider_data.tooltips else ""} 
                               data-target="{slider_id}" />
                    </div>
                </div>
            </div>
            
            <div class="slider-track-container">
                <div id="{slider_id}" 
                     class="slider-track"
                     data-slider-config='{slider_json}'></div>
            </div>
            
            <div class="slider-range-display">
                <span class="range-min">{slider_data.min_value}</span>
                <span class="range-max">{slider_data.max_value}</span>
            </div>
            
            <div class="slider-format-control">
                <label>Format:</label>
                <input type="text" class="format-input" 
                       value="{slider_data.format_string}" 
                       placeholder="{{value}}" 
                       data-target="{slider_id}" />
                <small>Use {{value}} as placeholder</small>
            </div>
            
            <input type="hidden" id="{slider_id}_data" name="{field.name}" value='{slider_json}' />
        </div>
        '''
        
        return HTMLString(html)


class TreeSelectWidget:
    """Widget for hierarchical tree selection."""
    
    def __init__(self, mode: TreeSelectMode = TreeSelectMode.SINGLE, lazy_loading: bool = False):
        self.mode = mode
        self.lazy_loading = lazy_loading
    
    def __call__(self, field, **kwargs):
        """Render the tree select widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, TreeSelectData):
                tree_data = field.data
            elif isinstance(field.data, dict):
                tree_data = TreeSelectData.from_dict(field.data)
            else:
                tree_data = TreeSelectData(nodes=[], mode=self.mode.value)
        else:
            tree_data = TreeSelectData(nodes=[], mode=self.mode.value)
        
        tree_id = f"tree_{field.id}_{secrets.token_hex(4)}"
        tree_json = json.dumps(tree_data.to_dict())
        
        html = f'''
        <div class="tree-select-container">
            <div class="tree-select-header">
                <div class="search-box" {"" if tree_data.search_enabled else 'style="display: none;"'}>
                    <input type="text" class="tree-search" placeholder="Search nodes..." 
                           data-target="{tree_id}" />
                    <button type="button" class="clear-search">✕</button>
                </div>
                
                <div class="tree-controls">
                    <button type="button" class="expand-all-btn" data-target="{tree_id}">Expand All</button>
                    <button type="button" class="collapse-all-btn" data-target="{tree_id}">Collapse All</button>
                    <button type="button" class="clear-selection-btn" data-target="{tree_id}">Clear Selection</button>
                </div>
            </div>
            
            <div class="tree-select-body">
                <div id="{tree_id}" 
                     class="tree-view"
                     data-tree-config='{tree_json}'
                     data-mode="{tree_data.mode}"
                     data-lazy-loading="{str(tree_data.lazy_loading).lower()}">
                    <!-- Tree nodes will be rendered here -->
                </div>
            </div>
            
            <div class="tree-select-footer">
                <div class="selection-summary">
                    <span class="selected-count">0 selected</span>
                    <div class="selected-items"></div>
                </div>
            </div>
            
            <input type="hidden" id="{tree_id}_data" name="{field.name}" value='{tree_json}' />
        </div>
        '''
        
        return HTMLString(html)


class CalendarWidget:
    """Widget for calendar with events."""
    
    def __init__(self, view: CalendarView = CalendarView.MONTH, editable: bool = True):
        self.view = view
        self.editable = editable
    
    def __call__(self, field, **kwargs):
        """Render the calendar widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, CalendarData):
                calendar_data = field.data
            elif isinstance(field.data, dict):
                calendar_data = CalendarData.from_dict(field.data)
            else:
                calendar_data = CalendarData(events=[], view=self.view.value)
        else:
            calendar_data = CalendarData(events=[], view=self.view.value)
        
        calendar_id = f"calendar_{field.id}_{secrets.token_hex(4)}"
        calendar_json = json.dumps(calendar_data.to_dict())
        
        html = f'''
        <div class="calendar-container">
            <div class="calendar-toolbar">
                <div class="navigation-controls">
                    <button type="button" class="prev-btn" data-target="{calendar_id}">‹ Prev</button>
                    <button type="button" class="today-btn" data-target="{calendar_id}">Today</button>
                    <button type="button" class="next-btn" data-target="{calendar_id}">Next ›</button>
                </div>
                
                <div class="view-controls">
                    <button type="button" class="view-btn {'active' if calendar_data.view == 'month' else ''}" 
                            data-view="month" data-target="{calendar_id}">Month</button>
                    <button type="button" class="view-btn {'active' if calendar_data.view == 'week' else ''}" 
                            data-view="week" data-target="{calendar_id}">Week</button>
                    <button type="button" class="view-btn {'active' if calendar_data.view == 'day' else ''}" 
                            data-view="day" data-target="{calendar_id}">Day</button>
                    <button type="button" class="view-btn {'active' if calendar_data.view == 'agenda' else ''}" 
                            data-view="agenda" data-target="{calendar_id}">Agenda</button>
                </div>
                
                <div class="action-controls">
                    <button type="button" class="add-event-btn" data-target="{calendar_id}">+ Add Event</button>
                    <button type="button" class="import-btn" data-target="{calendar_id}">Import</button>
                    <button type="button" class="export-btn" data-target="{calendar_id}">Export</button>
                </div>
            </div>
            
            <div id="{calendar_id}" 
                 class="calendar-view"
                 data-calendar-config='{calendar_json}'
                 data-editable="{str(calendar_data.editable).lower()}">
                <!-- Calendar will be rendered here -->
            </div>
            
            <input type="hidden" id="{calendar_id}_data" name="{field.name}" value='{calendar_json}' />
        </div>
        
        <!-- Event Modal -->
        <div class="event-modal" id="{calendar_id}_modal" style="display: none;">
            <div class="modal-content">
                <div class="modal-header">
                    <h3 class="modal-title">Event Details</h3>
                    <button type="button" class="close-modal">✕</button>
                </div>
                <div class="modal-body">
                    <form class="event-form">
                        <div class="form-group">
                            <label>Title:</label>
                            <input type="text" class="event-title" required />
                        </div>
                        <div class="form-group">
                            <label>Start:</label>
                            <input type="datetime-local" class="event-start" required />
                        </div>
                        <div class="form-group">
                            <label>End:</label>
                            <input type="datetime-local" class="event-end" />
                        </div>
                        <div class="form-group">
                            <label>All Day:</label>
                            <input type="checkbox" class="event-all-day" />
                        </div>
                        <div class="form-group">
                            <label>Description:</label>
                            <textarea class="event-description"></textarea>
                        </div>
                        <div class="form-group">
                            <label>Location:</label>
                            <input type="text" class="event-location" />
                        </div>
                        <div class="form-group">
                            <label>Color:</label>
                            <input type="color" class="event-color" value="#3788d8" />
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="save-event-btn">Save</button>
                    <button type="button" class="delete-event-btn" style="display: none;">Delete</button>
                    <button type="button" class="cancel-btn">Cancel</button>
                </div>
            </div>
        </div>
        '''
        
        return HTMLString(html)


class SwitchWidget:
    """Widget for advanced switches."""
    
    def __init__(self, switch_type: SwitchType = SwitchType.TOGGLE, allow_multiple: bool = False):
        self.switch_type = switch_type
        self.allow_multiple = allow_multiple
    
    def __call__(self, field, **kwargs):
        """Render the switch widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, SwitchData):
                switch_data = field.data
            elif isinstance(field.data, dict):
                switch_data = SwitchData.from_dict(field.data)
            else:
                switch_data = SwitchData(
                    options=[],
                    selected_values=[],
                    switch_type=self.switch_type.value,
                    allow_multiple=self.allow_multiple
                )
        else:
            switch_data = SwitchData(
                options=[],
                selected_values=[],
                switch_type=self.switch_type.value,
                allow_multiple=self.allow_multiple
            )
        
        switch_id = f"switch_{field.id}_{secrets.token_hex(4)}"
        switch_json = json.dumps(switch_data.to_dict())
        
        html = f'''
        <div class="switch-container" data-switch-type="{switch_data.switch_type}">
            <div class="switch-options-list" id="{switch_id}" data-switch-config='{switch_json}'>
        '''
        
        for i, option in enumerate(switch_data.options):
            is_selected = option.value in switch_data.selected_values
            disabled_class = ' disabled' if option.disabled else ''
            selected_class = ' selected' if is_selected else ''
            
            if switch_data.switch_type == SwitchType.TOGGLE.value:
                html += f'''
                <div class="switch-option toggle-switch{disabled_class}{selected_class}" 
                     data-value="{option.value}">
                    <div class="switch-track">
                        <div class="switch-handle"></div>
                    </div>
                    <span class="switch-label">{option.label}</span>
                </div>
                '''
            elif switch_data.switch_type == SwitchType.SEGMENTED.value:
                html += f'''
                <button type="button" class="switch-option segmented-option{disabled_class}{selected_class}"
                        data-value="{option.value}" {"disabled" if option.disabled else ""}>
                    {f'<i class="{option.icon}"></i>' if option.icon else ''}
                    <span>{option.label}</span>
                </button>
                '''
            elif switch_data.switch_type == SwitchType.CHECKBOX.value:
                html += f'''
                <label class="switch-option checkbox-option{disabled_class}">
                    <input type="checkbox" value="{option.value}" 
                           {"checked" if is_selected else ""} 
                           {"disabled" if option.disabled else ""} />
                    <span class="checkmark"></span>
                    <span class="switch-label">{option.label}</span>
                </label>
                '''
            elif switch_data.switch_type == SwitchType.RADIO.value:
                html += f'''
                <label class="switch-option radio-option{disabled_class}">
                    <input type="radio" name="{switch_id}_radio" value="{option.value}" 
                           {"checked" if is_selected else ""} 
                           {"disabled" if option.disabled else ""} />
                    <span class="radiomark"></span>
                    <span class="switch-label">{option.label}</span>
                </label>
                '''
        
        html += f'''
            </div>
            
            <div class="switch-controls">
                <button type="button" class="add-option-btn" data-target="{switch_id}">+ Add Option</button>
                <button type="button" class="clear-selection-btn" data-target="{switch_id}">Clear All</button>
            </div>
            
            <input type="hidden" id="{switch_id}_data" name="{field.name}" value='{switch_json}' />
        </div>
        '''
        
        return HTMLString(html)


class MarkdownWidget:
    """Widget for markdown editing with preview."""
    
    def __init__(self, height: int = 400, preview_enabled: bool = True):
        self.height = height
        self.preview_enabled = preview_enabled
    
    def __call__(self, field, **kwargs):
        """Render the markdown widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, MarkdownData):
                content = field.data.content
            elif isinstance(field.data, dict):
                content = field.data.get('content', '')
            else:
                content = str(field.data) if field.data else ''
        else:
            content = ''
        
        markdown_id = f"markdown_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="markdown-container">
            <div class="markdown-toolbar">
                <div class="format-buttons">
                    <button type="button" class="md-btn" data-action="bold" data-target="{markdown_id}" title="Bold">
                        <strong>B</strong>
                    </button>
                    <button type="button" class="md-btn" data-action="italic" data-target="{markdown_id}" title="Italic">
                        <em>I</em>
                    </button>
                    <button type="button" class="md-btn" data-action="strikethrough" data-target="{markdown_id}" title="Strikethrough">
                        <s>S</s>
                    </button>
                    <span class="separator">|</span>
                    <button type="button" class="md-btn" data-action="header1" data-target="{markdown_id}" title="Header 1">
                        H1
                    </button>
                    <button type="button" class="md-btn" data-action="header2" data-target="{markdown_id}" title="Header 2">
                        H2
                    </button>
                    <button type="button" class="md-btn" data-action="header3" data-target="{markdown_id}" title="Header 3">
                        H3
                    </button>
                    <span class="separator">|</span>
                    <button type="button" class="md-btn" data-action="list" data-target="{markdown_id}" title="Bulleted List">
                        • List
                    </button>
                    <button type="button" class="md-btn" data-action="numbered-list" data-target="{markdown_id}" title="Numbered List">
                        1. List
                    </button>
                    <button type="button" class="md-btn" data-action="quote" data-target="{markdown_id}" title="Quote">
                        > Quote
                    </button>
                    <span class="separator">|</span>
                    <button type="button" class="md-btn" data-action="link" data-target="{markdown_id}" title="Link">
                        🔗 Link
                    </button>
                    <button type="button" class="md-btn" data-action="image" data-target="{markdown_id}" title="Image">
                        🖼️ Image
                    </button>
                    <button type="button" class="md-btn" data-action="code" data-target="{markdown_id}" title="Code">
                        &lt;/&gt; Code
                    </button>
                    <button type="button" class="md-btn" data-action="table" data-target="{markdown_id}" title="Table">
                        📊 Table
                    </button>
                </div>
                
                <div class="view-controls">
                    <button type="button" class="view-btn active" data-view="edit" data-target="{markdown_id}">
                        Edit
                    </button>
                    <button type="button" class="view-btn" data-view="preview" data-target="{markdown_id}">
                        Preview
                    </button>
                    <button type="button" class="view-btn" data-view="split" data-target="{markdown_id}">
                        Split
                    </button>
                </div>
            </div>
            
            <div class="markdown-content" style="height: {self.height}px;">
                <div class="markdown-editor-panel active">
                    <textarea id="{markdown_id}" 
                              class="markdown-editor"
                              name="{field.name}"
                              placeholder="Enter Markdown content...">{content}</textarea>
                </div>
                
                <div class="markdown-preview-panel" {"style='display: none;'" if not self.preview_enabled else ""}>
                    <div class="markdown-preview"></div>
                </div>
            </div>
            
            <div class="markdown-status">
                <div class="word-count">Words: 0</div>
                <div class="char-count">Characters: 0</div>
                <div class="cursor-position">Line: 1, Column: 1</div>
            </div>
        </div>
        '''
        
        return HTMLString(html)


class MediaPlayerWidget:
    """Widget for media player."""
    
    def __init__(self, media_type: MediaType = MediaType.AUDIO, controls: bool = True):
        self.media_type = media_type
        self.controls = controls
    
    def __call__(self, field, **kwargs):
        """Render the media player widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, MediaPlayerData):
                player_data = field.data
            elif isinstance(field.data, dict):
                player_data = MediaPlayerData.from_dict(field.data)
            else:
                player_data = MediaPlayerData(tracks=[], media_type=self.media_type.value)
        else:
            player_data = MediaPlayerData(tracks=[], media_type=self.media_type.value)
        
        player_id = f"player_{field.id}_{secrets.token_hex(4)}"
        player_json = json.dumps(player_data.to_dict())
        
        html = f'''
        <div class="media-player-container">
            <div class="player-header">
                <div class="now-playing">
                    <div class="track-info">
                        <div class="track-title">No track selected</div>
                        <div class="track-artist"></div>
                    </div>
                    <div class="track-thumbnail">
                        <div class="placeholder-thumbnail">🎵</div>
                    </div>
                </div>
            </div>
            
            <div class="player-controls">
                <button type="button" class="control-btn shuffle-btn" data-target="{player_id}">
                    🔀
                </button>
                <button type="button" class="control-btn prev-btn" data-target="{player_id}">
                    ⏮️
                </button>
                <button type="button" class="control-btn play-pause-btn" data-target="{player_id}">
                    ▶️
                </button>
                <button type="button" class="control-btn next-btn" data-target="{player_id}">
                    ⏭️
                </button>
                <button type="button" class="control-btn repeat-btn" data-target="{player_id}">
                    🔁
                </button>
            </div>
            
            <div class="progress-container">
                <div class="time-display current-time">0:00</div>
                <div class="progress-bar">
                    <div class="progress-track">
                        <div class="progress-fill"></div>
                        <div class="progress-handle"></div>
                    </div>
                </div>
                <div class="time-display total-time">0:00</div>
            </div>
            
            <div class="volume-container">
                <button type="button" class="volume-btn" data-target="{player_id}">
                    🔊
                </button>
                <div class="volume-slider">
                    <input type="range" class="volume-range" min="0" max="1" step="0.01" value="{player_data.volume}" />
                </div>
            </div>
            
            <div class="playlist-container">
                <div class="playlist-header">
                    <h4>Playlist</h4>
                    <button type="button" class="add-track-btn" data-target="{player_id}">+ Add Track</button>
                </div>
                <div class="playlist-body">
                    <div id="{player_id}_playlist" class="playlist">
                        <!-- Playlist items will be rendered here -->
                    </div>
                </div>
            </div>
            
            <!-- Hidden audio/video element -->
            <{'video' if player_data.media_type == 'video' else 'audio'} 
                id="{player_id}_media"
                class="media-element"
                preload="metadata"
                style="display: none;">
                Your browser does not support the media element.
            </{'video' if player_data.media_type == 'video' else 'audio'}>
            
            <input type="hidden" id="{player_id}_data" name="{field.name}" value='{player_json}' />
        </div>
        '''
        
        return HTMLString(html)


class BadgeWidget:
    """Widget for badge/chip selection."""
    
    def __init__(self, max_badges: int = 20, allow_custom: bool = True):
        self.max_badges = max_badges
        self.allow_custom = allow_custom
    
    def __call__(self, field, **kwargs):
        """Render the badge widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, BadgeFieldData):
                badge_data = field.data
            elif isinstance(field.data, dict):
                badge_data = BadgeFieldData.from_dict(field.data)
            else:
                badge_data = BadgeFieldData(
                    selected_badges=[],
                    categories=[],
                    max_badges=self.max_badges,
                    allow_custom=self.allow_custom
                )
        else:
            badge_data = BadgeFieldData(
                selected_badges=[],
                categories=[],
                max_badges=self.max_badges,
                allow_custom=self.allow_custom
            )
        
        badge_id = f"badges_{field.id}_{secrets.token_hex(4)}"
        badge_json = json.dumps(badge_data.to_dict())
        
        html = f'''
        <div class="badge-container">
            <div class="badge-input-area">
                <div class="selected-badges">
        '''
        
        for badge in badge_data.selected_badges:
            badge_color = badge.color or '#007bff'
            icon_html = f'<i class="{badge.icon}"></i>' if badge.icon else ''
            image_html = f'<img src="{badge.image}" alt="" class="badge-image">' if badge.image else ''
            
            html += f'''
                    <div class="badge-item" data-badge-id="{badge.id}" style="background-color: {badge_color};">
                        {icon_html}
                        {image_html}
                        <span class="badge-label">{badge.label}</span>
                        {"<button type='button' class='remove-badge'>×</button>" if badge.removable else ""}
                    </div>
            '''
        
        html += f'''
                </div>
                
                <div class="badge-input-container">
                    <input type="text" 
                           id="{badge_id}_input" 
                           class="badge-input"
                           placeholder="Type to search or add badges..."
                           data-target="{badge_id}" />
                    <button type="button" class="add-custom-badge" 
                            data-target="{badge_id}" 
                            {"style='display: none;'" if not badge_data.allow_custom else ""}>
                        + Add Custom
                    </button>
                </div>
            </div>
            
            <div class="badge-categories">
        '''
        
        for category in badge_data.categories:
            html += f'''
                <div class="badge-category" data-category-id="{category.id}">
                    <div class="category-header" style="background-color: {category.color};">
                        {f'<i class="{category.icon}"></i>' if category.icon else ''}
                        <span class="category-name">{category.name}</span>
                        <span class="badge-count">({len(category.badges)})</span>
                    </div>
                    <div class="category-badges">
            '''
            
            for badge_id_in_cat in category.badges:
                html += f'''
                        <button type="button" class="available-badge" 
                                data-badge-id="{badge_id_in_cat}" 
                                data-category="{category.id}">
                            {badge_id_in_cat}
                        </button>
                '''
            
            html += '''
                    </div>
                </div>
            '''
        
        html += f'''
            </div>
            
            <div class="badge-suggestions" style="display: none;">
                <!-- Badge suggestions will appear here -->
            </div>
            
            <div class="badge-stats">
                <span class="badge-count">{len(badge_data.selected_badges)}</span> / {badge_data.max_badges} badges
            </div>
            
            <input type="hidden" id="{badge_id}_data" name="{field.name}" value='{badge_json}' />
        </div>
        '''
        
        return HTMLString(html)


class DualListBoxWidget:
    """Widget for dual list box (shuttle control)."""
    
    def __init__(self, height: int = 300, searchable: bool = True, show_move_all: bool = True):
        self.height = height
        self.searchable = searchable
        self.show_move_all = show_move_all
    
    def __call__(self, field, **kwargs):
        """Render the dual list box widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, DualListBoxData):
                dual_list_data = field.data
            elif isinstance(field.data, dict):
                dual_list_data = DualListBoxData.from_dict(field.data)
            else:
                dual_list_data = DualListBoxData(
                    available_items=[],
                    selected_items=[],
                    searchable=self.searchable,
                    show_move_all=self.show_move_all
                )
        else:
            dual_list_data = DualListBoxData(
                available_items=[],
                selected_items=[],
                searchable=self.searchable,
                show_move_all=self.show_move_all
            )
        
        dual_list_id = f"duallist_{field.id}_{secrets.token_hex(4)}"
        dual_list_json = json.dumps(dual_list_data.to_dict())
        
        html = f'''
        <div class="dual-list-container">
            <div class="dual-list-header">
                <h4>Select Items</h4>
                <div class="dual-list-controls">
                    <button type="button" class="select-all-btn" data-target="{dual_list_id}">Select All</button>
                    <button type="button" class="deselect-all-btn" data-target="{dual_list_id}">Deselect All</button>
                    <button type="button" class="invert-selection-btn" data-target="{dual_list_id}">Invert</button>
                </div>
            </div>
            
            <div class="dual-list-body" style="height: {self.height}px;">
                <!-- Available Items Panel -->
                <div class="list-panel available-panel">
                    <div class="panel-header">
                        <h5>Available</h5>
                        <span class="item-count">({len(dual_list_data.available_items)})</span>
                    </div>
                    
                    {"" if not dual_list_data.searchable else f'''
                    <div class="search-box">
                        <input type="text" class="list-search" placeholder="Search available..." 
                               data-target="{dual_list_id}" data-list="available" />
                        <button type="button" class="clear-search">✕</button>
                    </div>
                    '''}
                    
                    <div class="list-container">
                        <select id="{dual_list_id}_available" 
                                class="dual-list available-list" 
                                multiple size="10"
                                data-dual-list-config='{dual_list_json}'>
        '''
        
        for item in dual_list_data.available_items:
            disabled_attr = 'disabled' if item.disabled else ''
            icon_html = f'<i class="{item.icon}"></i> ' if item.icon else ''
            html += f'''
                            <option value="{item.value}" {disabled_attr} 
                                    data-item-id="{item.id}" 
                                    data-metadata='{json.dumps(item.metadata)}'>
                                {icon_html}{item.label}
                            </option>
            '''
        
        html += f'''
                        </select>
                    </div>
                </div>
                
                <!-- Move Buttons Panel -->
                <div class="move-buttons-panel">
                    {"" if not dual_list_data.show_move_all else '''
                    <button type="button" class="move-btn move-all-right" data-target="''' + dual_list_id + ''''" title="Move All Right">
                        ≫
                    </button>
                    '''}
                    <button type="button" class="move-btn move-right" data-target="{dual_list_id}" title="Move Right">
                        ›
                    </button>
                    <button type="button" class="move-btn move-left" data-target="{dual_list_id}" title="Move Left">
                        ‹
                    </button>
                    {"" if not dual_list_data.show_move_all else '''
                    <button type="button" class="move-btn move-all-left" data-target="''' + dual_list_id + ''''" title="Move All Left">
                        ≪
                    </button>
                    '''}
                    
                    {"" if not dual_list_data.show_move_up_down else '''
                    <div class="order-buttons">
                        <button type="button" class="order-btn move-up" data-target="''' + dual_list_id + ''''" title="Move Up">
                            ▲
                        </button>
                        <button type="button" class="order-btn move-down" data-target="''' + dual_list_id + ''''" title="Move Down">
                            ▼
                        </button>
                    </div>
                    '''}
                </div>
                
                <!-- Selected Items Panel -->
                <div class="list-panel selected-panel">
                    <div class="panel-header">
                        <h5>Selected</h5>
                        <span class="item-count">({len(dual_list_data.selected_items)})</span>
                    </div>
                    
                    {"" if not dual_list_data.searchable else f'''
                    <div class="search-box">
                        <input type="text" class="list-search" placeholder="Search selected..." 
                               data-target="{dual_list_id}" data-list="selected" />
                        <button type="button" class="clear-search">✕</button>
                    </div>
                    '''}
                    
                    <div class="list-container">
                        <select id="{dual_list_id}_selected" 
                                class="dual-list selected-list" 
                                multiple size="10">
        '''
        
        for item in dual_list_data.selected_items:
            disabled_attr = 'disabled' if item.disabled else ''
            icon_html = f'<i class="{item.icon}"></i> ' if item.icon else ''
            html += f'''
                            <option value="{item.value}" {disabled_attr} 
                                    data-item-id="{item.id}" 
                                    data-metadata='{json.dumps(item.metadata)}'>
                                {icon_html}{item.label}
                            </option>
            '''
        
        html += f'''
                        </select>
                    </div>
                </div>
            </div>
            
            <div class="dual-list-footer">
                <div class="statistics">
                    <span class="available-count">{len(dual_list_data.available_items)} available</span>
                    <span class="selected-count">{len(dual_list_data.selected_items)} selected</span>
                </div>
                
                <div class="footer-controls">
                    {"" if not dual_list_data.sortable else '''
                    <button type="button" class="sort-btn" data-target="''' + dual_list_id + ''''" data-list="both">
                        Sort A-Z
                    </button>
                    '''}
                    <button type="button" class="refresh-btn" data-target="{dual_list_id}">
                        🔄 Refresh
                    </button>
                </div>
            </div>
            
            <input type="hidden" id="{dual_list_id}_data" name="{field.name}" value='{dual_list_json}' />
        </div>
        '''
        
        return HTMLString(html)


# =============================================================================
# FIELD CLASSES
# =============================================================================

class ChartField(Field):
    """Field for data visualization charts with Chart.js integration."""
    widget = ChartWidget()
    
    def __init__(self, label=None, validators=None, chart_type=ChartType.LINE, 
                 width=400, height=300, **kwargs):
        super(ChartField, self).__init__(label, validators, **kwargs)
        self.widget = ChartWidget(chart_type=chart_type, width=width, height=height)


class MapField(Field):
    """Field for interactive maps with geolocation and markers."""
    widget = MapWidget()
    
    def __init__(self, label=None, validators=None, provider=MapProvider.LEAFLET,
                 width=600, height=400, enable_drawing=True, **kwargs):
        super(MapField, self).__init__(label, validators, **kwargs)
        self.widget = MapWidget(provider=provider, width=width, height=height, 
                               enable_drawing=enable_drawing)


class CropperField(Field):
    """Field for image cropping and editing with Cropper.js."""
    widget = CropperWidget()
    
    def __init__(self, label=None, validators=None, aspect_ratio=None,
                 min_width=100, min_height=100, **kwargs):
        super(CropperField, self).__init__(label, validators, **kwargs)
        self.widget = CropperWidget(aspect_ratio=aspect_ratio, 
                                   min_width=min_width, min_height=min_height)


class SliderField(Field):
    """Field for range selection with slider controls."""
    widget = SliderWidget()
    
    def __init__(self, label=None, validators=None, min_value=0, max_value=100,
                 step=1, range_mode=False, **kwargs):
        super(SliderField, self).__init__(label, validators, **kwargs)
        self.widget = SliderWidget(min_value=min_value, max_value=max_value,
                                  step=step, range_mode=range_mode)


class TreeSelectField(Field):
    """Field for hierarchical selection with tree view."""
    widget = TreeSelectWidget()
    
    def __init__(self, label=None, validators=None, data_source=None,
                 multiple=False, lazy_load=True, **kwargs):
        super(TreeSelectField, self).__init__(label, validators, **kwargs)
        self.widget = TreeSelectWidget(data_source=data_source, multiple=multiple,
                                      lazy_load=lazy_load)


class CalendarField(Field):
    """Field for hierarchical selection with tree view."""
    widget = CalendarWidget()
    
    def __init__(self, label=None, validators=None, view_type=CalendarView.MONTH,
                 enable_events=True, time_slots=True, **kwargs):
        super(CalendarField, self).__init__(label, validators, **kwargs)
        self.widget = CalendarWidget(view_type=view_type, enable_events=enable_events,
                                    time_slots=time_slots)


class SwitchField(Field):
    """Field for advanced toggle switches with animations."""
    widget = SwitchWidget()
    
    def __init__(self, label=None, validators=None, switch_type=SwitchType.DEFAULT,
                 size=SwitchSize.MEDIUM, **kwargs):
        super(SwitchField, self).__init__(label, validators, **kwargs)
        self.widget = SwitchWidget(switch_type=switch_type, size=size)


class MarkdownField(Field):
    """Field for markdown editing with live preview."""
    widget = MarkdownWidget()
    
    def __init__(self, label=None, validators=None, enable_preview=True,
                 toolbar_mode=MarkdownToolbar.FULL, **kwargs):
        super(MarkdownField, self).__init__(label, validators, **kwargs)
        self.widget = MarkdownWidget(enable_preview=enable_preview,
                                    toolbar_mode=toolbar_mode)


class MediaPlayerField(Field):
    """Field for audio/video media playback with playlist support."""
    widget = MediaPlayerWidget()
    
    def __init__(self, label=None, validators=None, media_type=MediaType.AUDIO,
                 enable_playlist=True, **kwargs):
        super(MediaPlayerField, self).__init__(label, validators, **kwargs)
        self.widget = MediaPlayerWidget(media_type=media_type, 
                                       enable_playlist=enable_playlist)


class BadgeField(Field):
    """Field for tag/chip selection with badge display."""
    widget = BadgeWidget()
    
    def __init__(self, label=None, validators=None, badge_style=BadgeStyle.PRIMARY,
                 max_items=None, **kwargs):
        super(BadgeField, self).__init__(label, validators, **kwargs)
        self.widget = BadgeWidget(badge_style=badge_style, max_items=max_items)


class DualListBoxField(Field):
    """Field for dual list box (shuttle control) selection."""
    widget = DualListBoxWidget()
    
    def __init__(self, label=None, validators=None, height=300, searchable=True,
                 show_move_all=True, **kwargs):
        super(DualListBoxField, self).__init__(label, validators, **kwargs)
        self.widget = DualListBoxWidget(height=height, searchable=searchable,
                                       show_move_all=show_move_all)