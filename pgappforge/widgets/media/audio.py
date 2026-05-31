"""AudioRecordingAndPlaybackWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms import Field
from wtforms.fields import (
    BooleanField, DateField, DateTimeField, DecimalField, FileField,
    FloatField, IntegerField, PasswordField, SelectField,
    SelectMultipleField, StringField, TextAreaField,
)
from wtforms.validators import ValidationError
from wtforms.widgets import TextInput, html_params

class AudioRecordingAndPlaybackWidget(BS3TextFieldWidget):
    """
    Widget for recording, playing, and managing audio content directly in the browser.
    Database column should be BYTEA type in PostgreSQL to store audio data with metadata in JSONB.

    Features:
    - Live audio recording with configurable quality settings
    - Playback controls (play, pause, stop, seek, speed)
    - Waveform visualization with zoom and selection
    - Real-time audio effects and filters
    - Multiple format support (MP3, WAV, OGG, FLAC) with fallbacks
    - Automatic volume normalization and gain control
    - Noise reduction and echo cancellation
    - Trim/crop with preview
    - Multiple track mixing/layering
    - Export to various formats
    - Recording quality presets
    - Dynamic microphone selection and testing
    - Advanced noise filtering
    - Voice activity detection with auto-stop
    - Real-time audio spectrum visualization
    - Configurable time limits and auto-split
    - Auto-save and recovery
    - Accessibility support (keyboard controls, ARIA labels)
    - Progress indicators and error handling
    - Resource cleanup and memory management

    Database Schema:
        audio_data = db.Column(db.LargeBinary, nullable=False)  # Raw audio data
        metadata = db.Column(db.JSON, nullable=False)  # Audio metadata
        effects = db.Column(db.JSON)  # Applied effects
        waveform = db.Column(db.JSON)  # Cached waveform data

    Required Dependencies:
    - RecordRTC.js 5.6+
    - WaveSurfer.js 6.0+
    - Web Audio API
    - MediaRecorder API
    - Lamejs (MP3 encoding)
    - Aurora.js (Audio decoding)
    - Tuna.js (Audio effects)

    Browser Compatibility:
    - Chrome 52+
    - Firefox 44+
    - Safari 14.1+
    - Edge 79+
    - Opera 39+

    Required Permissions:
    - Microphone access
    - Storage read/write
    - File download

    Performance Considerations:
    - Memory usage for buffers
    - CPU usage for effects
    - Storage for auto-save
    - Network bandwidth for upload

    Security:
    - HTTPS required
    - Input validation
    - File size limits
    - Format validation
    - Access control

    Best Practices:
    - Request permissions early
    - Use WebWorkers for encoding
    - Enable auto-save
    - Validate uploads
    - Clean up resources
    - Handle errors gracefully

    Troubleshooting:
    - Check microphone permissions
    - Verify HTTPS
    - Test browser compatibility
    - Monitor resource usage
    - Validate file formats
    - Check upload limits

    Example:
        audio = db.Column(db.LargeBinary, nullable=False,
            info={'widget': AudioRecordingAndPlaybackWidget(
                max_duration=300,  # 5 minutes
                format='mp3',
                quality='high',
                channels=2,
                sample_rate=44100,
                noise_reduction=True,
                show_waveform=True,
                enable_effects=True,
                auto_normalize=True,
                chunk_size=4096,
                auto_save_interval=30,
                max_file_size=50*1024*1024  # 50MB
            )})
    """

    # JavaScript dependencies that need to be included
    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/recordrtc@5.6.2/RecordRTC.min.js",
        "https://cdn.jsdelivr.net/npm/wavesurfer.js@6.4.0/dist/wavesurfer.min.js",
        "https://cdn.jsdelivr.net/npm/lamejs@1.2.1/lame.min.js",
        "https://cdn.jsdelivr.net/npm/aurora.js@0.4.2/aurora.min.js",
        "https://cdn.jsdelivr.net/npm/tuna-web-audio@0.4.0/dist/tuna.min.js",
        "/static/js/audio-recorder.js",  # Custom implementation
        "/static/js/audio-effects.js",  # Effects processing
        "/static/js/audio-upload.js",  # Upload handling
        "/static/js/audio-worker.js",  # Web worker for encoding
    ]

    CSS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/wavesurfer.js@6.4.0/dist/wavesurfer.min.css",
        "/static/css/audio-recorder.css",  # Custom styles
    ]

    QUALITY_PRESETS = {
        "low": {"bitrate": 96, "sampleRate": 22050},
        "medium": {"bitrate": 128, "sampleRate": 44100},
        "high": {"bitrate": 192, "sampleRate": 48000},
    }

    FORMAT_SETTINGS = {
        "mp3": {"mime": "audio/mpeg", "ext": ".mp3"},
        "wav": {"mime": "audio/wav", "ext": ".wav"},
        "ogg": {"mime": "audio/ogg", "ext": ".ogg"},
        "flac": {"mime": "audio/flac", "ext": ".flac"},
    }

    AUDIO_EFFECTS = {
        "none": {"name": "Normal", "filter": ""},
        "telephone": {"name": "Telephone", "filter": "bandpass"},
        "radio": {"name": "Radio", "filter": "lowshelf"},
        "megaphone": {"name": "Megaphone", "filter": "highpass"},
        "underwater": {"name": "Underwater", "filter": "lowpass"},
        "alien": {"name": "Alien", "filter": "frequency"},
        "echo": {"name": "Echo", "filter": "delay"},
        "reverb": {"name": "Reverb", "filter": "convolver"},
    }

    def __init__(self, **kwargs):
        """Initialize audio recording widget with configuration"""
        super().__init__(**kwargs)
        self.max_duration = kwargs.get("max_duration", 300)
        self.format = kwargs.get("format", "mp3")
        self.quality = kwargs.get("quality", "high")
        self.channels = kwargs.get("channels", 2)
        self.sample_rate = kwargs.get("sample_rate", 44100)
        self.noise_reduction = kwargs.get("noise_reduction", False)
        self.show_waveform = kwargs.get("show_waveform", True)
        self.enable_effects = kwargs.get("enable_effects", False)
        self.auto_normalize = kwargs.get("auto_normalize", True)
        self.echo_cancellation = kwargs.get("echo_cancellation", True)
        self.auto_gain_control = kwargs.get("auto_gain_control", True)
        self.save_path = kwargs.get("save_path", "uploads/audio")
        self.device_id = kwargs.get("device_id", None)
        self.chunk_size = kwargs.get("chunk_size", 4096)
        self.auto_save_interval = kwargs.get("auto_save_interval", 30)
        self.max_file_size = kwargs.get("max_file_size", 50 * 1024 * 1024)
        self.voice_activity_threshold = kwargs.get("voice_activity_threshold", 0.2)
        self.waveform_color = kwargs.get("waveform_color", "#2196F3")
        self.progress_color = kwargs.get("progress_color", "#1976D2")
        self.grid_color = kwargs.get("grid_color", "#999")
        self.background_color = kwargs.get("background_color", "#fff")
        self.retry_attempts = kwargs.get("retry_attempts", 3)
        self.retry_delay = kwargs.get("retry_delay", 1000)
        self.debug_mode = kwargs.get("debug_mode", False)
        self.fallback_mode = kwargs.get("fallback_mode", "file")
        self.cache_enabled = kwargs.get("cache_enabled", True)
        self.cache_max_age = kwargs.get("cache_max_age", 3600)
        self.mobile_optimization = kwargs.get("mobile_optimization", True)
        self.upload_chunk_size = kwargs.get("upload_chunk_size", 1024 * 1024)
        self.upload_concurrent = kwargs.get("upload_concurrent", 3)
        self.worker_count = kwargs.get("worker_count", 2)

        # Initialize Flask configs
        from flask import current_app

        self.upload_url = current_app.config.get(
            "AUDIO_UPLOAD_URL", "/api/upload/audio"
        )
        self.chunk_upload_url = current_app.config.get(
            "AUDIO_CHUNK_UPLOAD_URL", "/api/upload/audio/chunk"
        )
        self.effects_url = current_app.config.get(
            "AUDIO_EFFECTS_URL", "/api/audio/effects"
        )
        self.download_url = current_app.config.get(
            "AUDIO_DOWNLOAD_URL", "/api/audio/download"
        )
        self.auth_token = current_app.config.get("AUDIO_AUTH_TOKEN", None)

        # Create save directory if needed
        import os

        os.makedirs(self.save_path, exist_ok=True)

    def render_field(self, field, **kwargs):
        """Render the audio recording widget with controls"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("required", field.flags.required)

        # Include dependencies
        deps_html = self._include_dependencies()

        # Enhanced HTML template with ARIA labels and keyboard shortcuts
        widget_html = f"""
        {deps_html}

        <div class="audio-recorder-widget" id="{field.id}-container"
             role="application" aria-label="Audio Recorder">
            <!-- Device Selection -->
            <div class="device-selection mb-2">
                <select id="{field.id}-device" class="form-control"
                        aria-label="Microphone Selection">
                    <option value="">Select Microphone...</option>
                </select>
                <button type="button" class="btn btn-sm btn-secondary test-mic"
                        aria-label="Test Microphone">
                    <i class="fa fa-volume-up"></i> Test
                </button>
            </div>

            <!-- Recording Controls -->
            <div class="recorder-controls btn-group" role="toolbar"
                 aria-label="Recording Controls">
                <button type="button" class="btn btn-primary" id="{field.id}-record"
                        aria-label="Start Recording" title="Start Recording (Ctrl+R)">
                    <i class="fa fa-microphone"></i> Record
                </button>
                <button type="button" class="btn btn-warning" id="{field.id}-pause"
                        disabled aria-label="Pause Recording" title="Pause (Ctrl+P)">
                    <i class="fa fa-pause"></i> Pause
                </button>
                <button type="button" class="btn btn-danger" id="{field.id}-stop"
                        disabled aria-label="Stop Recording" title="Stop (Ctrl+S)">
                    <i class="fa fa-stop"></i> Stop
                </button>
            </div>

            <!-- Recording Status -->
            <div class="recording-status mt-2" role="status"
                 aria-label="Recording Status">
                <div class="d-flex justify-content-between">
                    <span class="timer" aria-label="Recording Time">00:00</span>
                    <span class="file-size" aria-label="File Size">0 KB</span>
                </div>
                <div class="progress">
                    <div class="progress-bar" role="progressbar" style="width: 0%"
                         aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">
                    </div>
                </div>
                <div class="level-meter" role="meter"
                     aria-label="Audio Level"></div>
            </div>

            <!-- Waveform Visualization -->
            {f'''
            <div class="waveform-container mt-2" role="region"
                 aria-label="Audio Waveform">
                <div id="{field.id}-waveform"></div>
                <div class="waveform-timeline"></div>
                <div class="selection-region"></div>
            </div>
            ''' if self.show_waveform else ''}

            <!-- Playback Controls -->
            <div class="playback-controls mt-2" style="display:none"
                 role="group" aria-label="Playback Controls">
                <div class="btn-group">
                    <button type="button" class="btn btn-success" id="{field.id}-play"
                            aria-label="Play/Pause" title="Play/Pause (Space)">
                        <i class="fa fa-play"></i>
                    </button>
                    <button type="button" class="btn btn-info" id="{field.id}-trim"
                            aria-label="Trim Audio" title="Trim Selection (Ctrl+T)">
                        <i class="fa fa-cut"></i>
                    </button>
                </div>
                <input type="range" class="form-range mt-2" id="{field.id}-seek"
                       min="0" max="100" value="0" step="0.1"
                       aria-label="Playback Position">
                <div class="d-flex justify-content-between">
                    <span class="current-time" aria-label="Current Time">00:00</span>
                    <span class="total-time" aria-label="Total Time">00:00</span>
                </div>
            </div>

            <!-- Effects Panel -->
            {f'''
            <div class="effects-panel mt-2" role="region"
                 aria-label="Audio Effects">
                <h5>Effects</h5>
                <div class="effect-controls">
                    <div class="form-group">
                        <label for="{field.id}-gain">Gain</label>
                        <input type="range" class="form-range" id="{field.id}-gain"
                               min="0" max="2" step="0.1" value="1"
                               aria-label="Gain Control">
                    </div>
                    <div class="form-group">
                        <label for="{field.id}-echo">Echo</label>
                        <input type="range" class="form-range" id="{field.id}-echo"
                               min="0" max="1" step="0.1" value="0"
                               aria-label="Echo Control">
                    </div>
                    <div class="form-group">
                        <label for="{field.id}-reverb">Reverb</label>
                        <input type="range" class="form-range" id="{field.id}-reverb"
                               min="0" max="1" step="0.1" value="0"
                               aria-label="Reverb Control">
                    </div>
                    <div class="form-group">
                        <label for="{field.id}-filter">Filter</label>
                        <select class="form-control" id="{field.id}-filter"
                                aria-label="Audio Filter">
                            <option value="none">None</option>
                            <option value="telephone">Telephone</option>
                            <option value="radio">Radio</option>
                            <option value="megaphone">Megaphone</option>
                            <option value="underwater">Underwater</option>
                        </select>
                    </div>
                </div>
            </div>
            ''' if self.enable_effects else ''}

            <!-- Export Options -->
            <div class="export-options mt-2" role="group"
                 aria-label="Export Options">
                <div class="btn-group">
                    <button type="button" class="btn btn-secondary dropdown-toggle"
                            data-toggle="dropdown" aria-label="Export Menu">
                        <i class="fa fa-download"></i> Export
                    </button>
                    <div class="dropdown-menu">
                        {self._render_export_options()}
                    </div>
                </div>
            </div>

            <!-- Status Messages -->
            <div class="alert mt-2" style="display:none" role="alert"
                 aria-live="polite"></div>

            <!-- Hidden Inputs -->
            <input type="hidden" name="{field.name}" id="{field.id}"
                   value="{field.data or ''}" aria-hidden="true">
            <input type="file" style="display:none" id="{field.id}-file"
                   accept=".mp3,.wav,.ogg,.flac"
                   aria-label="File Upload Fallback">

            <!-- Processing Overlay -->
            <div class="processing-overlay" style="display:none"
                 role="status" aria-label="Processing">
                <div class="spinner"></div>
                <div class="message">Processing...</div>
            </div>
        </div>

        <script>
            $(document).ready(function() {{
                // Initialize audio recorder with enhanced configuration
                const audioRecorder = new AudioRecorderWidget({{
                    containerId: '{field.id}-container',
                    fieldId: '{field.id}',
                    maxDuration: {self.max_duration},
                    format: '{self.format}',
                    quality: {_js_json(self.QUALITY_PRESETS[self.quality])},
                    channels: {self.channels},
                    sampleRate: {self.sample_rate},
                    noiseReduction: {str(self.noise_reduction).lower()},
                    showWaveform: {str(self.show_waveform).lower()},
                    enableEffects: {str(self.enable_effects).lower()},
                    autoNormalize: {str(self.auto_normalize).lower()},
                    echoCancellation: {str(self.echo_cancellation).lower()},
                    autoGainControl: {str(self.auto_gain_control).lower()},
                    deviceId: {f"'{self.device_id}'" if self.device_id else 'null'},
                    chunkSize: {self.chunk_size},
                    autoSaveInterval: {self.auto_save_interval},
                    maxFileSize: {self.max_file_size},
                    voiceActivityThreshold: {self.voice_activity_threshold},
                    waveformColor: '{self.waveform_color}',
                    progressColor: '{self.progress_color}',
                    gridColor: '{self.grid_color}',
                    backgroundColor: '{self.background_color}',
                    uploadUrl: '{self.upload_url}',
                    chunkUploadUrl: '{self.chunk_upload_url}',
                    effectsUrl: '{self.effects_url}',
                    downloadUrl: '{self.download_url}',
                    authToken: {f"'{self.auth_token}'" if self.auth_token else 'null'},
                    retryAttempts: {self.retry_attempts},
                    retryDelay: {self.retry_delay},
                    debugMode: {str(self.debug_mode).lower()},
                    fallbackMode: '{self.fallback_mode}',
                    cacheEnabled: {str(self.cache_enabled).lower()},
                    cacheMaxAge: {self.cache_max_age},
                    mobileOptimization: {str(self.mobile_optimization).lower()},
                    uploadChunkSize: {self.upload_chunk_size},
                    uploadConcurrent: {self.upload_concurrent},
                    workerCount: {self.worker_count},
                    effects: {_js_json(self.AUDIO_EFFECTS)},
                    onError: function(error) {{
                        showError(error);
                    }},
                    onProgress: function(progress) {{
                        updateProgress(progress);
                    }},
                    onComplete: function(data) {{
                        handleRecordingComplete(data);
                    }},
                    onStateChange: function(state) {{
                        updateUIState(state);
                    }},
                    onDeviceError: function(error) {{
                        handleDeviceError(error);
                    }},
                    onStorageError: function(error) {{
                        handleStorageError(error);
                    }},
                    onUploadError: function(error) {{
                        handleUploadError(error);
                    }}
                }});

                // Enhanced error handling
                function showError(error) {{
                    console.error('Audio recorder error:', error);
                    const alert = $('#{field.id}-container .alert');
                    alert.removeClass('alert-success alert-info')
                         .addClass('alert-danger')
                         .html('<i class="fa fa-exclamation-circle"></i> ' + error)
                         .show()
                         .attr('role', 'alert');
                    setTimeout(() => alert.fadeOut(), 5000);
                }}

                // Progress updates with performance monitoring
                function updateProgress(progress) {{
                    const progressBar = $('#{field.id}-container .progress-bar');
                    progressBar.css('width', progress + '%')
                              .attr('aria-valuenow', progress);

                    if (progress % 10 === 0) {{
                        audioRecorder.checkPerformance();
                    }}
                }}

                // Recording complete with validation
                function handleRecordingComplete(data) {{
                    try {{
                        data = audioRecorder.validateRecording(data);
                        $('#{field.id}').val(JSON.stringify(data));
                        showSuccess('Recording completed successfully');
                        audioRecorder.enablePlayback();
                    }} catch (error) {{
                        showError('Recording validation failed: ' + error.message);
                    }}
                }}

                // Success message
                function showSuccess(message) {{
                    const alert = $('#{field.id}-container .alert');
                    alert.removeClass('alert-danger alert-info')
                         .addClass('alert-success')
                         .html('<i class="fa fa-check-circle"></i> ' + message)
                         .show()
                         .attr('role', 'alert');
                    setTimeout(() => alert.fadeOut(), 3000);
                }}

                // UI state management
                function updateUIState(state) {{
                    const container = $('#{field.id}-container');
                    container.attr('data-state', state);

                    // Update button states
                    $('#{field.id}-record').prop('disabled', state === 'recording');
                    $('#{field.id}-pause').prop('disabled', state !== 'recording');
                    $('#{field.id}-stop').prop('disabled', state === 'idle');

                    // Update ARIA labels
                    container.find('.recording-status')
                            .attr('aria-label', 'Recording Status: ' + state);

                    // Show/hide processing overlay
                    const overlay = container.find('.processing-overlay');
                    if (state === 'processing') {{
                        overlay.show()
                               .find('.message')
                               .text('Processing recording...');
                    }} else {{
                        overlay.hide();
                    }}
                }}

                // Device error handling
                function handleDeviceError(error) {{
                    showError('Device error: ' + error);
                    if ('{self.fallback_mode}' === 'file') {{
                        $('#{field.id}-file').show()
                                           .attr('aria-label', 'File Upload Fallback Mode');
                    }}
                }}

                // Storage error handling
                function handleStorageError(error) {{
                    showError('Storage error: ' + error);
                    audioRecorder.cleanupStorage();
                }}

                // Upload error handling with retry
                function handleUploadError(error) {{
                    showError('Upload error: ' + error);
                    if ({str(self.upload_resume).lower()}) {{
                        audioRecorder.retryUpload();
                    }}
                }}

                // Enhanced keyboard shortcuts with announcements
                $(document).on('keydown', function(e) {{
                    if (e.ctrlKey || e.metaKey) {{
                        let action = '';
                        switch(e.key.toLowerCase()) {{
                            case 'r':
                                e.preventDefault();
                                action = 'Start Recording';
                                $('#{field.id}-record').click();
                                break;
                            case 'p':
                                e.preventDefault();
                                action = 'Pause Recording';
                                $('#{field.id}-pause').click();
                                break;
                            case 's':
                                e.preventDefault();
                                action = 'Stop Recording';
                                $('#{field.id}-stop').click();
                                break;
                            case 't':
                                e.preventDefault();
                                action = 'Trim Recording';
                                $('#{field.id}-trim').click();
                                break;
                            case ' ':
                                e.preventDefault();
                                action = 'Toggle Playback';
                                $('#{field.id}-play').click();
                                break;
                        }}
                        if (action) {{
                            audioRecorder.announceAction(action);
                        }}
                    }}
                }});

                // Enhanced browser compatibility check
                if (!audioRecorder.checkCompatibility()) {{
                    showError('Audio recording is not supported in this browser. ' +
                            'Please use a modern browser with microphone support.');
                    if ('{self.fallback_mode}' === 'file') {{
                        $('#{field.id}-file').show()
                                           .attr('aria-label', 'File Upload Fallback Mode');
                    }}
                }}

                // Proper cleanup on page unload
                $(window).on('unload', function() {{
                    audioRecorder.cleanup();
                    audioRecorder.disposeWorkers();
                    audioRecorder.releaseMemory();
                }});

                // Initialize voice activity detection if enabled
                if ({str(self.voice_activity_threshold > 0).lower()}) {{
                    audioRecorder.initializeVoiceDetection();
                }}

                // Setup performance monitoring
                if ({str(self.debug_mode).lower()}) {{
                    audioRecorder.startPerformanceMonitoring();
                }}

                // Mobile device optimization
                if ({str(self.mobile_optimization).lower()}) {{
                    audioRecorder.optimizeForMobile();
                }}
            }});
        </script>
        """

        return Markup(widget_html)

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{js_includes}\n{css_includes}"

    def _render_export_options(self):
        """Render export format options"""
        options = []
        for fmt, settings in self.FORMAT_SETTINGS.items():
            options.append(
                f'<a class="dropdown-item" href="#" data-format="{fmt}" '
                f'aria-label="Export as {fmt.upper()}">{fmt.upper()}</a>'
            )
        return "\n".join(options)

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_audio_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid audio data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_audio_data(self, data):
        """Validate audio data and constraints"""
        if not isinstance(data, dict) or "audio" not in data:
            raise ValueError("Invalid audio data structure")

        # Validate file size
        if len(data["audio"]) > self.max_file_size:
            raise ValueError(
                f"Audio file size exceeds maximum ({self.max_file_size/(1024*1024):.1f}MB)"
            )

        # Validate format
        if "format" not in data or data["format"] not in self.FORMAT_SETTINGS:
            raise ValueError("Unsupported audio format")

        # Validate duration
        if "duration" in data and data["duration"] > self.max_duration:
            raise ValueError(
                f"Recording exceeds maximum duration ({self.max_duration}s)"
            )

        # Validate metadata
        if "metadata" in data:
            required_fields = ["timestamp", "channels", "sampleRate", "bitrate"]
            if not all(field in data["metadata"] for field in required_fields):
                raise ValueError("Missing required metadata fields")

            # Validate metadata values
            if data["metadata"]["channels"] not in [1, 2]:
                raise ValueError("Invalid number of channels")

            if not (8000 <= data["metadata"]["sampleRate"] <= 192000):
                raise ValueError("Invalid sample rate")

            if not (8 <= data["metadata"]["bitrate"] <= 320):
                raise ValueError("Invalid bitrate")

        # Validate effects if present
        if "effects" in data:
            for effect in data["effects"]:
                if effect not in self.AUDIO_EFFECTS:
                    raise ValueError(f"Invalid effect: {effect}")

    def pre_validate(self, form):
        """Validate audio data before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Audio recording is required")
