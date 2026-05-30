"""
Media Field Framework for PgForge

Provides comprehensive media capture and interaction fields:
- CameraField: Live camera preview and photo/video capture
- AudioRecordingField: Audio recording with waveform visualization  
- GPSField: Location detection and interactive mapping
- MediaGalleryField: Multi-media gallery with thumbnails and preview
"""

import json
import base64
import mimetypes
from typing import Optional, Dict, Any, List, Union
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from wtforms import Field, ValidationError, StringField
from wtforms.widgets import HTMLString, html_params
from markupsafe import Markup
from sqlalchemy import TypeDecorator, Text, JSON
from sqlalchemy.ext.mutable import MutableDict

from flask import current_app, url_for, request
from flask_babel import gettext as __


class MediaType(Enum):
    """Supported media types."""
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    LOCATION = "location"
    DOCUMENT = "document"


class CameraMode(Enum):
    """Camera capture modes."""
    PHOTO = "photo"
    VIDEO = "video"
    BOTH = "both"


class AudioFormat(Enum):
    """Audio recording formats."""
    WAV = "audio/wav"
    MP3 = "audio/mp3"
    OGG = "audio/ogg"
    WEBM = "audio/webm"


class VideoFormat(Enum):
    """Video recording formats."""
    MP4 = "video/mp4"
    WEBM = "video/webm"
    OGG = "video/ogg"


@dataclass
class MediaMetadata:
    """Metadata for media files."""
    filename: str
    size: int
    mime_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    created_at: Optional[datetime] = None
    device_info: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        if self.created_at:
            result['created_at'] = self.created_at.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MediaMetadata':
        """Create from dictionary."""
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)


@dataclass 
class GPSCoordinates:
    """GPS coordinates with metadata."""
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    accuracy: Optional[float] = None
    heading: Optional[float] = None
    speed: Optional[float] = None
    timestamp: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        if self.timestamp:
            result['timestamp'] = self.timestamp.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GPSCoordinates':
        """Create from dictionary."""
        if 'timestamp' in data and isinstance(data['timestamp'], str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


@dataclass
class MediaData:
    """Comprehensive media data structure."""
    media_type: MediaType
    data: str  # Base64 encoded data or URL
    metadata: MediaMetadata
    thumbnail: Optional[str] = None  # Base64 encoded thumbnail
    coordinates: Optional[GPSCoordinates] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            'media_type': self.media_type.value,
            'data': self.data,
            'metadata': self.metadata.to_dict(),
            'thumbnail': self.thumbnail,
        }
        if self.coordinates:
            result['coordinates'] = self.coordinates.to_dict()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MediaData':
        """Create from dictionary."""
        return cls(
            media_type=MediaType(data['media_type']),
            data=data['data'],
            metadata=MediaMetadata.from_dict(data['metadata']),
            thumbnail=data.get('thumbnail'),
            coordinates=GPSCoordinates.from_dict(data['coordinates']) if data.get('coordinates') else None
        )


class MediaDataType(TypeDecorator):
    """SQLAlchemy type for storing media data."""
    
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        """Convert MediaData to JSON string."""
        if value is not None:
            if isinstance(value, MediaData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
            elif isinstance(value, str):
                return value
        return value
    
    def process_result_value(self, value, dialect):
        """Convert JSON string to MediaData."""
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return MediaData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class BaseMediaWidget:
    """Base widget for media fields."""
    
    def __init__(self, multiple=False, accept=None, capture=None, **kwargs):
        """
        Initialize base media widget.
        
        Args:
            multiple: Allow multiple media items
            accept: Accepted MIME types
            capture: Camera capture preference
            **kwargs: Additional widget options
        """
        self.multiple = multiple
        self.accept = accept
        self.capture = capture
        self.options = kwargs
    
    def __call__(self, field, **kwargs):
        """Render the widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            kwargs['data-current'] = json.dumps(field.data.to_dict() if hasattr(field.data, 'to_dict') else field.data)
        
        # Add media-specific attributes
        if self.accept:
            kwargs['accept'] = self.accept
        if self.capture:
            kwargs['capture'] = self.capture
        if self.multiple:
            kwargs['multiple'] = True
            
        # Add configuration
        config = {
            'field_id': field.id,
            'multiple': self.multiple,
            'accept': self.accept,
            'capture': self.capture,
            **self.options
        }
        kwargs['data-config'] = json.dumps(config)
        
        return self._render_widget(field, **kwargs)
    
    def _render_widget(self, field, **kwargs):
        """Override in subclasses to render specific widget."""
        raise NotImplementedError()


class CameraWidget(BaseMediaWidget):
    """Widget for camera capture with live preview."""
    
    def __init__(self, mode=CameraMode.PHOTO, resolution='1280x720', quality=0.8, **kwargs):
        """
        Initialize camera widget.
        
        Args:
            mode: Camera capture mode (photo, video, both)
            resolution: Video resolution (e.g., '1280x720')
            quality: Image/video quality (0.0 to 1.0)
            **kwargs: Additional widget options
        """
        accept_types = []
        if mode in [CameraMode.PHOTO, CameraMode.BOTH]:
            accept_types.append('image/*')
        if mode in [CameraMode.VIDEO, CameraMode.BOTH]:
            accept_types.append('video/*')
            
        super().__init__(
            accept=','.join(accept_types),
            capture='environment',
            mode=mode.value,
            resolution=resolution,
            quality=quality,
            **kwargs
        )
    
    def _render_widget(self, field, **kwargs):
        """Render camera widget HTML."""
        config = json.loads(kwargs.get('data-config', '{}'))
        
        html = f'''
        <div class="fab-camera-field" data-config='{kwargs.get("data-config", "{}")}'>
            <div class="camera-controls">
                <div class="camera-preview-container">
                    <video id="{field.id}_preview" class="camera-preview" autoplay muted playsinline></video>
                    <canvas id="{field.id}_canvas" class="camera-canvas" style="display: none;"></canvas>
                    <div class="camera-overlay">
                        <div class="camera-focus-ring"></div>
                        <div class="camera-grid" style="display: none;">
                            <div class="grid-line grid-vertical-1"></div>
                            <div class="grid-line grid-vertical-2"></div>
                            <div class="grid-line grid-horizontal-1"></div>
                            <div class="grid-line grid-horizontal-2"></div>
                        </div>
                    </div>
                </div>
                
                <div class="camera-buttons">
                    <button type="button" class="btn btn-secondary camera-switch" title="Switch Camera">
                        <i class="fa fa-sync-alt"></i>
                    </button>
                    
                    <button type="button" class="btn btn-secondary camera-grid-toggle" title="Toggle Grid">
                        <i class="fa fa-th"></i>
                    </button>
                    
                    {'<button type="button" class="btn btn-primary camera-capture-photo" title="Take Photo"><i class="fa fa-camera"></i></button>' if config.get('mode') in ['photo', 'both'] else ''}
                    
                    {'<button type="button" class="btn btn-danger camera-capture-video" title="Record Video"><i class="fa fa-video"></i></button>' if config.get('mode') in ['video', 'both'] else ''}
                    
                    <button type="button" class="btn btn-secondary camera-settings" title="Settings">
                        <i class="fa fa-cog"></i>
                    </button>
                </div>
                
                <div class="camera-status">
                    <span class="status-text">Ready</span>
                    <span class="recording-indicator" style="display: none;">
                        <i class="fa fa-circle text-danger"></i> Recording
                    </span>
                </div>
            </div>
            
            <div class="camera-media-preview" style="display: none;">
                <div class="media-preview-container">
                    <img class="media-preview-image" style="display: none;" />
                    <video class="media-preview-video" controls style="display: none;"></video>
                </div>
                <div class="media-preview-actions">
                    <button type="button" class="btn btn-success media-accept">
                        <i class="fa fa-check"></i> Accept
                    </button>
                    <button type="button" class="btn btn-secondary media-retake">
                        <i class="fa fa-redo"></i> Retake
                    </button>
                </div>
            </div>
            
            <input type="hidden" id="{field.id}" name="{field.name}" value="{field.data or ''}" />
            
            <div class="camera-settings-panel" style="display: none;">
                <div class="settings-group">
                    <label>Resolution:</label>
                    <select class="form-control resolution-select">
                        <option value="640x480">640x480</option>
                        <option value="1280x720" selected>1280x720</option>
                        <option value="1920x1080">1920x1080</option>
                        <option value="3840x2160">4K</option>
                    </select>
                </div>
                <div class="settings-group">
                    <label>Quality:</label>
                    <input type="range" class="form-control quality-slider" min="0.1" max="1.0" step="0.1" value="{config.get('quality', 0.8)}" />
                    <span class="quality-value">{int(config.get('quality', 0.8) * 100)}%</span>
                </div>
                <div class="settings-group">
                    <label>Timer:</label>
                    <select class="form-control timer-select">
                        <option value="0">Off</option>
                        <option value="3">3 seconds</option>
                        <option value="5">5 seconds</option>
                        <option value="10">10 seconds</option>
                    </select>
                </div>
            </div>
        </div>
        '''
        
        return Markup(html)


class AudioRecordingWidget(BaseMediaWidget):
    """Widget for audio recording with waveform visualization."""
    
    def __init__(self, format_type=AudioFormat.WAV, max_duration=300, **kwargs):
        """
        Initialize audio recording widget.
        
        Args:
            format_type: Audio format to record
            max_duration: Maximum recording duration in seconds
            **kwargs: Additional widget options
        """
        super().__init__(
            accept='audio/*',
            format_type=format_type.value,
            max_duration=max_duration,
            **kwargs
        )
    
    def _render_widget(self, field, **kwargs):
        """Render audio recording widget HTML."""
        config = json.loads(kwargs.get('data-config', '{}'))
        
        html = f'''
        <div class="fab-audio-field" data-config='{kwargs.get("data-config", "{}")}'>
            <div class="audio-controls">
                <div class="audio-visualizer-container">
                    <canvas id="{field.id}_visualizer" class="audio-visualizer" width="400" height="100"></canvas>
                    <div class="audio-level-meter">
                        <div class="level-bar"></div>
                    </div>
                </div>
                
                <div class="audio-buttons">
                    <button type="button" class="btn btn-primary audio-record" title="Start Recording">
                        <i class="fa fa-microphone"></i>
                    </button>
                    
                    <button type="button" class="btn btn-secondary audio-stop" title="Stop Recording" disabled>
                        <i class="fa fa-stop"></i>
                    </button>
                    
                    <button type="button" class="btn btn-secondary audio-play" title="Play Recording" disabled>
                        <i class="fa fa-play"></i>
                    </button>
                    
                    <button type="button" class="btn btn-secondary audio-pause" title="Pause" disabled style="display: none;">
                        <i class="fa fa-pause"></i>
                    </button>
                    
                    <button type="button" class="btn btn-danger audio-delete" title="Delete Recording" disabled>
                        <i class="fa fa-trash"></i>
                    </button>
                </div>
                
                <div class="audio-info">
                    <span class="recording-time">00:00</span>
                    <span class="max-time">/ {config.get('max_duration', 300):02d}:{config.get('max_duration', 300) % 60:02d}</span>
                    <span class="file-size" style="display: none;"></span>
                </div>
                
                <div class="audio-waveform-container" style="display: none;">
                    <canvas id="{field.id}_waveform" class="audio-waveform" width="400" height="60"></canvas>
                    <div class="playback-cursor"></div>
                </div>
            </div>
            
            <div class="audio-settings">
                <div class="settings-group">
                    <label>Quality:</label>
                    <select class="form-control quality-select">
                        <option value="8000">8 kHz (Phone)</option>
                        <option value="16000">16 kHz (Voice)</option>
                        <option value="44100" selected>44.1 kHz (CD)</option>
                        <option value="48000">48 kHz (Studio)</option>
                    </select>
                </div>
                
                <div class="settings-group">
                    <label>Format:</label>
                    <select class="form-control format-select">
                        <option value="audio/wav" selected>WAV</option>
                        <option value="audio/mp3">MP3</option>
                        <option value="audio/ogg">OGG</option>
                        <option value="audio/webm">WebM</option>
                    </select>
                </div>
                
                <div class="settings-group">
                    <label>Noise Reduction:</label>
                    <input type="checkbox" class="form-check-input noise-reduction" checked />
                </div>
            </div>
            
            <input type="hidden" id="{field.id}" name="{field.name}" value="{field.data or ''}" />
            
            <audio id="{field.id}_audio" style="display: none;"></audio>
        </div>
        '''
        
        return Markup(html)


class GPSWidget(BaseMediaWidget):
    """Widget for GPS location with interactive mapping."""
    
    def __init__(self, map_provider='leaflet', zoom_level=15, enable_tracking=True, **kwargs):
        """
        Initialize GPS widget.
        
        Args:
            map_provider: Map provider (leaflet, google, mapbox)
            zoom_level: Default zoom level
            enable_tracking: Enable continuous location tracking
            **kwargs: Additional widget options
        """
        super().__init__(
            map_provider=map_provider,
            zoom_level=zoom_level,
            enable_tracking=enable_tracking,
            **kwargs
        )
    
    def _render_widget(self, field, **kwargs):
        """Render GPS widget HTML."""
        config = json.loads(kwargs.get('data-config', '{}'))
        
        html = f'''
        <div class="fab-gps-field" data-config='{kwargs.get("data-config", "{}")}'>
            <div class="gps-controls">
                <div class="gps-buttons">
                    <button type="button" class="btn btn-primary gps-locate" title="Get Current Location">
                        <i class="fa fa-crosshairs"></i> Locate Me
                    </button>
                    
                    <button type="button" class="btn btn-secondary gps-track" title="Track Location">
                        <i class="fa fa-route"></i> Track
                    </button>
                    
                    <button type="button" class="btn btn-secondary gps-clear" title="Clear Location">
                        <i class="fa fa-times"></i> Clear
                    </button>
                    
                    <button type="button" class="btn btn-secondary gps-share" title="Share Location">
                        <i class="fa fa-share-alt"></i> Share
                    </button>
                </div>
                
                <div class="gps-info">
                    <div class="location-display">
                        <span class="coordinates-display">No location selected</span>
                        <span class="accuracy-display" style="display: none;"></span>
                    </div>
                    
                    <div class="location-details" style="display: none;">
                        <div class="detail-group">
                            <label>Latitude:</label>
                            <span class="latitude-value">-</span>
                        </div>
                        <div class="detail-group">
                            <label>Longitude:</label>
                            <span class="longitude-value">-</span>
                        </div>
                        <div class="detail-group">
                            <label>Altitude:</label>
                            <span class="altitude-value">-</span>
                        </div>
                        <div class="detail-group">
                            <label>Accuracy:</label>
                            <span class="accuracy-value">-</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="gps-map-container">
                <div id="{field.id}_map" class="gps-map" style="height: 300px; width: 100%;"></div>
                <div class="map-loading" style="display: none;">
                    <i class="fa fa-spinner fa-spin"></i> Loading map...
                </div>
            </div>
            
            <div class="gps-address-lookup">
                <div class="input-group">
                    <input type="text" class="form-control address-input" placeholder="Enter address to locate...">
                    <div class="input-group-append">
                        <button type="button" class="btn btn-secondary address-search">
                            <i class="fa fa-search"></i>
                        </button>
                    </div>
                </div>
                <div class="address-suggestions" style="display: none;"></div>
            </div>
            
            <input type="hidden" id="{field.id}" name="{field.name}" value="{field.data or ''}" />
        </div>
        '''
        
        return Markup(html)


class MediaGalleryWidget(BaseMediaWidget):
    """Widget for media gallery with thumbnails and preview."""
    
    def __init__(self, media_types=None, max_files=10, **kwargs):
        """
        Initialize media gallery widget.
        
        Args:
            media_types: Allowed media types
            max_files: Maximum number of files
            **kwargs: Additional widget options
        """
        if media_types is None:
            media_types = [MediaType.PHOTO, MediaType.VIDEO, MediaType.AUDIO]
            
        accept_types = []
        for media_type in media_types:
            if media_type == MediaType.PHOTO:
                accept_types.append('image/*')
            elif media_type == MediaType.VIDEO:
                accept_types.append('video/*')
            elif media_type == MediaType.AUDIO:
                accept_types.append('audio/*')
        
        super().__init__(
            multiple=True,
            accept=','.join(accept_types),
            media_types=[mt.value for mt in media_types],
            max_files=max_files,
            **kwargs
        )
    
    def _render_widget(self, field, **kwargs):
        """Render media gallery widget HTML."""
        config = json.loads(kwargs.get('data-config', '{}'))
        
        html = f'''
        <div class="fab-media-gallery-field" data-config='{kwargs.get("data-config", "{}")}'>
            <div class="gallery-upload-area">
                <div class="upload-dropzone">
                    <div class="upload-icon">
                        <i class="fa fa-cloud-upload-alt"></i>
                    </div>
                    <div class="upload-text">
                        <strong>Drop files here or click to upload</strong>
                        <br>
                        <small>Supports images, videos, and audio files</small>
                    </div>
                    <input type="file" class="gallery-file-input" multiple 
                           accept="{self.accept}" style="display: none;" />
                </div>
                
                <div class="upload-progress" style="display: none;">
                    <div class="progress">
                        <div class="progress-bar" role="progressbar" style="width: 0%"></div>
                    </div>
                    <div class="progress-text">Uploading...</div>
                </div>
            </div>
            
            <div class="gallery-grid">
                <div class="gallery-items-container"></div>
                
                <div class="gallery-add-button">
                    <button type="button" class="btn btn-outline-primary gallery-add">
                        <i class="fa fa-plus"></i>
                        <br>
                        Add Media
                    </button>
                </div>
            </div>
            
            <div class="gallery-preview-modal" style="display: none;">
                <div class="preview-overlay"></div>
                <div class="preview-container">
                    <div class="preview-header">
                        <h5 class="preview-title">Media Preview</h5>
                        <button type="button" class="btn btn-sm btn-secondary preview-close">
                            <i class="fa fa-times"></i>
                        </button>
                    </div>
                    
                    <div class="preview-content">
                        <img class="preview-image" style="display: none;" />
                        <video class="preview-video" controls style="display: none;"></video>
                        <audio class="preview-audio" controls style="display: none;"></audio>
                    </div>
                    
                    <div class="preview-actions">
                        <button type="button" class="btn btn-secondary preview-edit">
                            <i class="fa fa-edit"></i> Edit
                        </button>
                        <button type="button" class="btn btn-danger preview-delete">
                            <i class="fa fa-trash"></i> Delete
                        </button>
                        <button type="button" class="btn btn-primary preview-download">
                            <i class="fa fa-download"></i> Download
                        </button>
                    </div>
                </div>
            </div>
            
            <input type="hidden" id="{field.id}" name="{field.name}" value="{field.data or ''}" />
        </div>
        '''
        
        return Markup(html)


class BaseMediaField(Field):
    """Base class for media fields."""
    
    def __init__(self, label=None, validators=None, widget=None, **kwargs):
        """Initialize base media field."""
        super().__init__(label, validators, **kwargs)
        if widget is not None:
            self.widget = widget
    
    def process_formdata(self, valuelist):
        """Process form data into field data."""
        if valuelist:
            try:
                data = json.loads(valuelist[0]) if valuelist[0] else None
                if data:
                    self.data = MediaData.from_dict(data)
                else:
                    self.data = None
            except (json.JSONDecodeError, KeyError, TypeError):
                self.data = valuelist[0] if valuelist[0] else None
        else:
            self.data = None
    
    def _value(self):
        """Return field value for form rendering."""
        if self.data:
            if hasattr(self.data, 'to_dict'):
                return json.dumps(self.data.to_dict())
            else:
                return str(self.data)
        return ''


class CameraField(BaseMediaField):
    """Camera field for photo and video capture."""
    
    widget = CameraWidget()
    
    def __init__(self, label=None, validators=None, mode=CameraMode.PHOTO, 
                 resolution='1280x720', quality=0.8, **kwargs):
        """
        Initialize camera field.
        
        Args:
            label: Field label
            validators: Field validators
            mode: Camera capture mode
            resolution: Video resolution
            quality: Image/video quality
            **kwargs: Additional field options
        """
        self.widget = CameraWidget(mode=mode, resolution=resolution, quality=quality)
        super().__init__(label, validators, **kwargs)


class AudioRecordingField(BaseMediaField):
    """Audio recording field with waveform visualization."""
    
    widget = AudioRecordingWidget()
    
    def __init__(self, label=None, validators=None, format_type=AudioFormat.WAV,
                 max_duration=300, **kwargs):
        """
        Initialize audio recording field.
        
        Args:
            label: Field label
            validators: Field validators
            format_type: Audio format
            max_duration: Maximum recording duration
            **kwargs: Additional field options
        """
        self.widget = AudioRecordingWidget(format_type=format_type, max_duration=max_duration)
        super().__init__(label, validators, **kwargs)


class GPSField(BaseMediaField):
    """GPS location field with interactive mapping."""
    
    widget = GPSWidget()
    
    def __init__(self, label=None, validators=None, map_provider='leaflet',
                 zoom_level=15, enable_tracking=True, **kwargs):
        """
        Initialize GPS field.
        
        Args:
            label: Field label
            validators: Field validators
            map_provider: Map provider
            zoom_level: Default zoom level
            enable_tracking: Enable location tracking
            **kwargs: Additional field options
        """
        self.widget = GPSWidget(map_provider=map_provider, zoom_level=zoom_level, 
                               enable_tracking=enable_tracking)
        super().__init__(label, validators, **kwargs)


class MediaGalleryField(BaseMediaField):
    """Media gallery field for multiple media items."""
    
    widget = MediaGalleryWidget()
    
    def __init__(self, label=None, validators=None, media_types=None,
                 max_files=10, **kwargs):
        """
        Initialize media gallery field.
        
        Args:
            label: Field label
            validators: Field validators
            media_types: Allowed media types
            max_files: Maximum number of files
            **kwargs: Additional field options
        """
        self.widget = MediaGalleryWidget(media_types=media_types, max_files=max_files)
        super().__init__(label, validators, **kwargs)


# Validation functions
def validate_media_size(max_size_mb=10):
    """Validate media file size."""
    def _validate(form, field):
        if field.data and hasattr(field.data, 'metadata'):
            size_mb = field.data.metadata.size / (1024 * 1024)
            if size_mb > max_size_mb:
                raise ValidationError(f'File size must be less than {max_size_mb}MB')
    return _validate


def validate_media_type(allowed_types):
    """Validate media type."""
    def _validate(form, field):
        if field.data and hasattr(field.data, 'media_type'):
            if field.data.media_type not in allowed_types:
                raise ValidationError(f'Media type must be one of: {", ".join([t.value for t in allowed_types])}')
    return _validate


def validate_gps_coordinates():
    """Validate GPS coordinates."""
    def _validate(form, field):
        if field.data and hasattr(field.data, 'coordinates') and field.data.coordinates:
            coords = field.data.coordinates
            if not (-90 <= coords.latitude <= 90):
                raise ValidationError('Latitude must be between -90 and 90 degrees')
            if not (-180 <= coords.longitude <= 180):
                raise ValidationError('Longitude must be between -180 and 180 degrees')
    return _validate


# Utility functions
def get_media_url(media_data: MediaData, thumbnail=False) -> str:
    """Get URL for media data."""
    if thumbnail and media_data.thumbnail:
        return f"data:{media_data.metadata.mime_type};base64,{media_data.thumbnail}"
    return f"data:{media_data.metadata.mime_type};base64,{media_data.data}"


def create_thumbnail(media_data: MediaData, size=(150, 150)) -> Optional[str]:
    """Create thumbnail for media data."""
    try:
        if media_data.media_type == MediaType.PHOTO:
            # Generate image thumbnail
            from PIL import Image
            import io
            
            image_data = base64.b64decode(media_data.data)
            image = Image.open(io.BytesIO(image_data))
            image.thumbnail(size, Image.Resampling.LANCZOS)
            
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=85)
            thumbnail_data = base64.b64encode(buffer.getvalue()).decode()
            
            return thumbnail_data
            
        elif media_data.media_type == MediaType.VIDEO:
            # Generate video thumbnail (would need ffmpeg in production)
            return None
            
        elif media_data.media_type == MediaType.AUDIO:
            # Generate audio waveform thumbnail
            return None
            
    except Exception:
        return None
    
    return None


def get_media_storage_path(media_data: MediaData) -> Path:
    """Get storage path for media data."""
    base_path = Path(current_app.config.get('MEDIA_STORAGE_PATH', 'media'))
    
    # Create directory structure: media/type/year/month/
    date_path = datetime.now()
    type_path = media_data.media_type.value
    
    full_path = base_path / type_path / str(date_path.year) / f"{date_path.month:02d}"
    full_path.mkdir(parents=True, exist_ok=True)
    
    return full_path / media_data.metadata.filename


def save_media_to_storage(media_data: MediaData) -> str:
    """Save media data to storage and return file path."""
    file_path = get_media_storage_path(media_data)
    
    try:
        # Decode base64 data and save to file
        file_data = base64.b64decode(media_data.data)
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        # Return relative path
        return str(file_path.relative_to(Path(current_app.config.get('MEDIA_STORAGE_PATH', 'media'))))
        
    except Exception as e:
        current_app.logger.error(f"Error saving media to storage: {e}")
        raise