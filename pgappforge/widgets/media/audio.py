"""AudioRecordingAndPlaybackWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json

from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape


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
		audio_data = db.Column(db.LargeBinary, nullable=False)
		metadata = db.Column(db.JSON, nullable=False)

	Required Dependencies:
	- RecordRTC.js 5.6+
	- WaveSurfer.js 6.0+
	- Web Audio API
	- MediaRecorder API
	"""

	JS_DEPENDENCIES = [
		"https://cdn.jsdelivr.net/npm/recordrtc@5.6.2/RecordRTC.min.js",
		"https://cdn.jsdelivr.net/npm/wavesurfer.js@6.4.0/dist/wavesurfer.min.js",
		"https://cdn.jsdelivr.net/npm/lamejs@1.2.1/lame.min.js",
		"/static/js/audio-recorder.js",
		"/static/js/audio-effects.js",
		"/static/js/audio-upload.js",
	]

	CSS_DEPENDENCIES = [
		"https://cdn.jsdelivr.net/npm/wavesurfer.js@6.4.0/dist/wavesurfer.min.css",
		"/static/css/audio-recorder.css",
	]

	QUALITY_PRESETS = {
		"low":    {"bitrate": 96,  "sampleRate": 22050},
		"medium": {"bitrate": 128, "sampleRate": 44100},
		"high":   {"bitrate": 192, "sampleRate": 48000},
	}

	FORMAT_SETTINGS = {
		"mp3":  {"mime": "audio/mpeg", "ext": ".mp3"},
		"wav":  {"mime": "audio/wav",  "ext": ".wav"},
		"ogg":  {"mime": "audio/ogg",  "ext": ".ogg"},
		"flac": {"mime": "audio/flac", "ext": ".flac"},
	}

	AUDIO_EFFECTS = {
		"none":       {"name": "Normal",     "filter": ""},
		"telephone":  {"name": "Telephone",  "filter": "bandpass"},
		"radio":      {"name": "Radio",      "filter": "lowshelf"},
		"megaphone":  {"name": "Megaphone",  "filter": "highpass"},
		"underwater": {"name": "Underwater", "filter": "lowpass"},
		"echo":       {"name": "Echo",       "filter": "delay"},
		"reverb":     {"name": "Reverb",     "filter": "convolver"},
	}

	def __init__(self, **kwargs):
		"""Initialize audio recording widget with configuration."""
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
		self.background_color = kwargs.get("background_color", "#fff")
		self.retry_attempts = kwargs.get("retry_attempts", 3)
		self.retry_delay = kwargs.get("retry_delay", 1000)
		self.debug_mode = kwargs.get("debug_mode", False)
		self.fallback_mode = kwargs.get("fallback_mode", "file")
		self.mobile_optimization = kwargs.get("mobile_optimization", True)
		self.upload_resume = kwargs.get("upload_resume", True)
		# Universal kwargs
		self.placeholder = kwargs.get("placeholder", "")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

		# Initialize Flask configs lazily (avoid import at module level)
		self._upload_url = kwargs.get("upload_url", None)
		self._chunk_upload_url = kwargs.get("chunk_upload_url", None)
		self._auth_token = kwargs.get("auth_token", None)

	def _get_flask_config(self, key: str, default: str) -> str:
		"""Safely read Flask app config without crashing at import time."""
		try:
			from flask import current_app
			return current_app.config.get(key, default)
		except RuntimeError:
			return default

	def __call__(self, field, **kwargs):
		"""Render the audio recording widget."""
		kwargs.setdefault("id", field.id)
		return self.render_field(field, **kwargs)

	def render_field(self, field, **kwargs):
		"""Render the audio recording widget with controls."""
		kwargs.setdefault("id", field.id)

		upload_url = self._upload_url or self._get_flask_config("AUDIO_UPLOAD_URL", "/api/upload/audio")
		chunk_upload_url = self._chunk_upload_url or self._get_flask_config("AUDIO_CHUNK_UPLOAD_URL", "/api/upload/audio/chunk")
		auth_token = self._auth_token or self._get_flask_config("AUDIO_AUTH_TOKEN", "")

		has_errors = bool(field.errors)
		invalid_attr = ' aria-invalid="true"' if has_errors else ''
		label_text = str(field.label.text) if field.label else str(_("Audio Recording"))
		field_id = escape(field.id)
		quality_preset = self.QUALITY_PRESETS.get(self.quality, self.QUALITY_PRESETS["high"])

		html = self._include_dependencies()

		html += (
			f'<div class="audio-recorder-widget{" " + escape(self.css_class) if self.css_class else ""}"'
			f' id="{field_id}-container"'
			f' role="application" aria-label="{escape(label_text)}">'

			# Device selection
			'<div class="device-selection mb-2">'
			f'<label for="{field_id}-device">{escape(str(_("Microphone")))}</label>'
			f'<select id="{field_id}-device" class="form-control"'
			f' aria-label="{escape(str(_("Microphone Selection")))}">'
			f'<option value="">{escape(str(_("Select Microphone...")))}</option>'
			'</select>'
			f'<button type="button" class="btn btn-sm btn-secondary test-mic"'
			f' aria-label="{escape(str(_("Test Microphone")))}">'
			f'<i class="fa fa-volume-up" aria-hidden="true"></i> {escape(str(_("Test")))}'
			'</button>'
			'</div>'

			# Recording controls
			f'<div class="recorder-controls btn-group" role="toolbar"'
			f' aria-label="{escape(str(_("Recording Controls")))}">'
			f'<button type="button" class="btn btn-primary" id="{field_id}-record"'
			f' aria-label="{escape(str(_("Start Recording")))}" title="{escape(str(_("Start Recording (Ctrl+R)")))}">'
			f'<i class="fa fa-microphone" aria-hidden="true"></i> {escape(str(_("Record")))}'
			'</button>'
			f'<button type="button" class="btn btn-warning" id="{field_id}-pause"'
			f' disabled aria-label="{escape(str(_("Pause Recording")))}"'
			f' title="{escape(str(_("Pause (Ctrl+P)")))}">'
			f'<i class="fa fa-pause" aria-hidden="true"></i> {escape(str(_("Pause")))}'
			'</button>'
			f'<button type="button" class="btn btn-danger" id="{field_id}-stop"'
			f' disabled aria-label="{escape(str(_("Stop Recording")))}"'
			f' title="{escape(str(_("Stop (Ctrl+S)")))}">'
			f'<i class="fa fa-stop" aria-hidden="true"></i> {escape(str(_("Stop")))}'
			'</button>'
			'</div>'

			# Recording status
			f'<div class="recording-status mt-2" role="status"'
			f' aria-label="{escape(str(_("Recording Status")))}" aria-live="polite">'
			'<div class="d-flex justify-content-between">'
			f'<span class="timer" aria-label="{escape(str(_("Recording Time")))}" aria-live="polite">00:00</span>'
			f'<span class="file-size" aria-label="{escape(str(_("File Size")))}" aria-live="polite">0 KB</span>'
			'</div>'
			'<div class="progress">'
			'<div class="progress-bar" role="progressbar" style="width: 0%"'
			' aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">'
			'</div>'
			'</div>'
			'</div>'
		)

		# Waveform
		if self.show_waveform:
			html += (
				f'<div class="waveform-container mt-2" role="region"'
				f' aria-label="{escape(str(_("Audio Waveform")))}">'
				f'<div id="{field_id}-waveform" aria-hidden="true"></div>'
				'</div>'
			)

		# Playback controls
		html += (
			f'<div class="playback-controls mt-2" style="display:none"'
			f' role="group" aria-label="{escape(str(_("Playback Controls")))}">'
			'<div class="btn-group">'
			f'<button type="button" class="btn btn-success" id="{field_id}-play"'
			f' aria-label="{escape(str(_("Play/Pause")))}" title="{escape(str(_("Play/Pause (Space)")))}">'
			'<i class="fa fa-play" aria-hidden="true"></i>'
			'</button>'
			'</div>'
			f'<label for="{field_id}-seek" class="visually-hidden sr-only">'
			f'{escape(str(_("Playback Position")))}</label>'
			f'<input type="range" class="form-range mt-2" id="{field_id}-seek"'
			f' min="0" max="100" value="0" step="0.1"'
			f' aria-label="{escape(str(_("Playback Position")))}">'
			'<div class="d-flex justify-content-between">'
			f'<span class="current-time" aria-live="polite">00:00</span>'
			f'<span class="total-time">00:00</span>'
			'</div>'
			'</div>'
		)

		# Effects panel
		if self.enable_effects:
			html += (
				f'<div class="effects-panel mt-2" role="region"'
				f' aria-label="{escape(str(_("Audio Effects")))}">'
				f'<h5>{escape(str(_("Effects")))}</h5>'
				'<div class="effect-controls">'
				'<div class="mb-3">'
				f'<label for="{field_id}-gain">{escape(str(_("Gain")))}</label>'
				f'<input type="range" class="form-range" id="{field_id}-gain"'
				f' min="0" max="2" step="0.1" value="1"'
				f' aria-label="{escape(str(_("Gain Control")))}">'
				'</div>'
				'<div class="mb-3">'
				f'<label for="{field_id}-filter">{escape(str(_("Filter")))}</label>'
				f'<select class="form-control" id="{field_id}-filter"'
				f' aria-label="{escape(str(_("Audio Filter")))}">'
				f'<option value="none">{escape(str(_("None")))}</option>'
				f'<option value="telephone">{escape(str(_("Telephone")))}</option>'
				f'<option value="radio">{escape(str(_("Radio")))}</option>'
				f'<option value="underwater">{escape(str(_("Underwater")))}</option>'
				'</select>'
				'</div>'
				'</div>'
				'</div>'
			)

		# Export options
		html += (
			f'<div class="export-options mt-2" role="group"'
			f' aria-label="{escape(str(_("Export Options")))}">'
			'<div class="btn-group">'
			f'<button type="button" class="btn btn-secondary dropdown-toggle"'
			f' data-bs-toggle="dropdown" data-toggle="dropdown"'
			f' aria-label="{escape(str(_("Export Menu")))}" aria-haspopup="true" aria-expanded="false">'
			f'<i class="fa fa-download" aria-hidden="true"></i> {escape(str(_("Export")))}'
			'</button>'
			'<div class="dropdown-menu">'
			+ self._render_export_options() +
			'</div>'
			'</div>'
			'</div>'

			# Status messages
			f'<div class="alert mt-2" style="display:none" role="alert" aria-live="polite"></div>'

			# Hidden inputs
			f'<input type="hidden" name="{escape(field.name)}" id="{field_id}"'
			f' value="{escape(str(field.data) if field.data else "")}"'
			f' aria-label="{escape(label_text)}"{invalid_attr} aria-hidden="true">'
			f'<input type="file" style="display:none" id="{field_id}-file"'
			f' accept=".mp3,.wav,.ogg,.flac"'
			f' aria-label="{escape(str(_("File Upload Fallback")))}">'
			'</div>'
		)

		# Inline script — all Python values go through _js_json
		html += f"""
<script>
(function() {{
	var FIELD_ID = {_js_json(field.id)};
	var UPLOAD_URL = {_js_json(upload_url)};
	var CHUNK_UPLOAD_URL = {_js_json(chunk_upload_url)};
	var AUTH_TOKEN = {_js_json(auth_token or None)};
	var FALLBACK_MODE = {_js_json(self.fallback_mode)};
	var UPLOAD_RESUME = {_js_json(self.upload_resume)};

	function getContainer() {{ return document.getElementById(FIELD_ID + '-container'); }}
	function getField() {{ return document.getElementById(FIELD_ID); }}

	function showAlert(message, type) {{
		var container = getContainer();
		if (!container) return;
		var alertEl = container.querySelector('.alert');
		if (!alertEl) return;
		alertEl.className = 'alert mt-2 alert-' + (type || 'info');
		alertEl.textContent = message;
		alertEl.style.display = 'block';
		alertEl.setAttribute('role', 'alert');
		setTimeout(function() {{ alertEl.style.display = 'none'; }}, 5000);
	}}

	function init() {{
		var container = getContainer();
		if (!container) return;
		var field = getField();

		// Keyboard shortcuts
		document.addEventListener('keydown', function(e) {{
			if (!e.ctrlKey && !e.metaKey) return;
			switch (e.key.toLowerCase()) {{
				case 'r':
					e.preventDefault();
					var recBtn = document.getElementById(FIELD_ID + '-record');
					if (recBtn && !recBtn.disabled) recBtn.click();
					break;
				case 'p':
					e.preventDefault();
					var pauseBtn = document.getElementById(FIELD_ID + '-pause');
					if (pauseBtn && !pauseBtn.disabled) pauseBtn.click();
					break;
				case 's':
					e.preventDefault();
					var stopBtn = document.getElementById(FIELD_ID + '-stop');
					if (stopBtn && !stopBtn.disabled) stopBtn.click();
					break;
			}}
		}});

		// Cleanup on page unload
		window.addEventListener('unload', function() {{
			if (window._audioRecorder_) {{
				if (typeof window._audioRecorder_.cleanup === 'function') window._audioRecorder_.cleanup();
			}}
		}});

		// Initialize AudioRecorderWidget if available
		if (typeof AudioRecorderWidget !== 'undefined') {{
			window._audioRecorder_ = new AudioRecorderWidget({{
				containerId: FIELD_ID + '-container',
				fieldId: FIELD_ID,
				maxDuration: {_js_json(self.max_duration)},
				format: {_js_json(self.format)},
				quality: {_js_json(quality_preset)},
				channels: {_js_json(self.channels)},
				sampleRate: {_js_json(self.sample_rate)},
				noiseReduction: {_js_json(self.noise_reduction)},
				showWaveform: {_js_json(self.show_waveform)},
				enableEffects: {_js_json(self.enable_effects)},
				autoNormalize: {_js_json(self.auto_normalize)},
				echoCancellation: {_js_json(self.echo_cancellation)},
				autoGainControl: {_js_json(self.auto_gain_control)},
				deviceId: {_js_json(self.device_id)},
				chunkSize: {_js_json(self.chunk_size)},
				autoSaveInterval: {_js_json(self.auto_save_interval)},
				maxFileSize: {_js_json(self.max_file_size)},
				voiceActivityThreshold: {_js_json(self.voice_activity_threshold)},
				waveformColor: {_js_json(self.waveform_color)},
				progressColor: {_js_json(self.progress_color)},
				backgroundColor: {_js_json(self.background_color)},
				uploadUrl: UPLOAD_URL,
				chunkUploadUrl: CHUNK_UPLOAD_URL,
				authToken: AUTH_TOKEN,
				retryAttempts: {_js_json(self.retry_attempts)},
				retryDelay: {_js_json(self.retry_delay)},
				debugMode: {_js_json(self.debug_mode)},
				fallbackMode: FALLBACK_MODE,
				mobileOptimization: {_js_json(self.mobile_optimization)},
				effects: {_js_json(self.AUDIO_EFFECTS)},

				onError: function(error) {{ showAlert(error, 'danger'); }},
				onComplete: function(data) {{
					try {{
						if (field) field.value = JSON.stringify(data);
						showAlert({_js_json(str(_("Recording completed successfully")))}, 'success');
					}} catch (e) {{ showAlert('Recording validation failed: ' + e.message, 'danger'); }}
				}},
				onStateChange: function(state) {{
					var recBtn = document.getElementById(FIELD_ID + '-record');
					var pauseBtn = document.getElementById(FIELD_ID + '-pause');
					var stopBtn = document.getElementById(FIELD_ID + '-stop');
					if (recBtn) recBtn.disabled = (state === 'recording');
					if (pauseBtn) pauseBtn.disabled = (state !== 'recording');
					if (stopBtn) stopBtn.disabled = (state === 'idle');
				}},
				onDeviceError: function(error) {{
					showAlert({_js_json(str(_("Device error"))) + " + ': ' + "} error, 'danger');
					if (FALLBACK_MODE === 'file') {{
						var fileInput = document.getElementById(FIELD_ID + '-file');
						if (fileInput) fileInput.style.display = 'block';
					}}
				}},
			}});
		}}
	}}

	if (document.readyState === 'loading') {{
		document.addEventListener('DOMContentLoaded', init);
	}} else {{
		init();
	}}
}})();
</script>"""

		# Server-side WTForms errors
		if has_errors:
			html += (
				f'<div class="invalid-feedback d-block" id="{field_id}_error" role="alert">'
			)
			for error in field.errors:
				html += f'<span>{escape(str(error))}</span>'
			html += '</div>'

		# Help text
		if self.description:
			html += (
				f'<small class="form-text text-muted" id="{field_id}_help">'
				f'{escape(self.description)}</small>'
			)

		return Markup(html)

	def _include_dependencies(self) -> str:
		"""Include required JavaScript and CSS dependencies."""
		js_includes = "\n".join(
			f'<script src="{escape(url)}"></script>' for url in self.JS_DEPENDENCIES
		)
		css_includes = "\n".join(
			f'<link rel="stylesheet" href="{escape(url)}">' for url in self.CSS_DEPENDENCIES
		)
		return f"{css_includes}\n{js_includes}\n"

	def _render_export_options(self) -> str:
		"""Render export format options."""
		return "\n".join(
			f'<a class="dropdown-item" href="#" data-format="{escape(fmt)}"'
			f' aria-label="{escape(str(_("Export as")))} {escape(fmt.upper())}">'
			f'{escape(fmt.upper())}</a>'
			for fmt in self.FORMAT_SETTINGS
		)

	def process_formdata(self, valuelist):
		"""Process form data to database format."""
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
		"""Validate audio data and constraints."""
		if not isinstance(data, dict) or "audio" not in data:
			raise ValueError("Invalid audio data structure")
		if len(data["audio"]) > self.max_file_size:
			raise ValueError(
				f"Audio file size exceeds maximum ({self.max_file_size / (1024 * 1024):.1f}MB)"
			)
		if "format" not in data or data["format"] not in self.FORMAT_SETTINGS:
			raise ValueError("Unsupported audio format")
		if "duration" in data and data["duration"] > self.max_duration:
			raise ValueError(
				f"Recording exceeds maximum duration ({self.max_duration}s)"
			)
		if "metadata" in data:
			required_fields = ["timestamp", "channels", "sampleRate", "bitrate"]
			if not all(f in data["metadata"] for f in required_fields):
				raise ValueError("Missing required metadata fields")
			if data["metadata"]["channels"] not in [1, 2]:
				raise ValueError("Invalid number of channels")
			if not (8000 <= data["metadata"]["sampleRate"] <= 192000):
				raise ValueError("Invalid sample rate")
			if not (8 <= data["metadata"]["bitrate"] <= 320):
				raise ValueError("Invalid bitrate")
		if "effects" in data:
			for effect in data["effects"]:
				if effect not in self.AUDIO_EFFECTS:
					raise ValueError(f"Invalid effect: {effect}")

	def pre_validate(self, form):
		"""Validate audio data before form processing."""
		if form.flags.required and not self.data:
			raise ValueError("Audio recording is required")
