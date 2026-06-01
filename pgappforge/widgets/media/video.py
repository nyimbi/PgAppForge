"""VideoRecordAndPlayWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json

from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape


class VideoRecordAndPlayWidget(BS3TextFieldWidget):
	"""
	Widget for recording, playing, and managing video content directly in the browser.

	Database Type:
		PostgreSQL: BYTEA (for video data) + JSONB (for metadata)
		SQLAlchemy: LargeBinary + JSON

	Features:
	- Live video recording with audio
	- Video preview while recording
	- Playback controls with keyboard shortcuts
	- Screenshot capture
	- Multi-camera selection and testing
	- Resolution presets (480p to 4K)
	- Frame rate control
	- Real-time video filters and effects
	- Auto thumbnail generation
	- Picture-in-picture support
	- Recording timer with auto-stop
	- Quality presets
	- Automatic error recovery
	- Mobile optimization
	- Accessibility features

	Required Dependencies:
	- RecordRTC.js 5.6+
	- Video.js 7.0+
	- MediaRecorder API
	"""

	JS_DEPENDENCIES = [
		"https://cdn.jsdelivr.net/npm/recordrtc@5.6.2/RecordRTC.min.js",
		"https://vjs.zencdn.net/7.20.3/video.min.js",
		"/static/js/video-recorder.js",
		"/static/js/video-effects.js",
		"/static/js/video-upload.js",
	]

	CSS_DEPENDENCIES = [
		"https://vjs.zencdn.net/7.20.3/video-js.css",
		"/static/css/video-recorder.css",
	]

	QUALITY_PRESETS = {
		"low":    {"bitrate": "1000k", "codec": "libx264", "preset": "ultrafast"},
		"medium": {"bitrate": "2500k", "codec": "libx264", "preset": "medium"},
		"high":   {"bitrate": "5000k", "codec": "libx264", "preset": "slow"},
		"ultra":  {"bitrate": "8000k", "codec": "libx264", "preset": "veryslow"},
	}

	RESOLUTION_PRESETS = {
		"480p":  {"width": 854,  "height": 480,  "aspect": "16:9"},
		"720p":  {"width": 1280, "height": 720,  "aspect": "16:9"},
		"1080p": {"width": 1920, "height": 1080, "aspect": "16:9"},
		"4k":    {"width": 3840, "height": 2160, "aspect": "16:9"},
	}

	VIDEO_EFFECTS = {
		"none":       {"name": "Normal",        "filter": ""},
		"grayscale":  {"name": "Grayscale",     "filter": "grayscale(1)"},
		"sepia":      {"name": "Sepia",         "filter": "sepia(1)"},
		"blur":       {"name": "Blur",          "filter": "blur(5px)"},
		"brightness": {"name": "Bright",        "filter": "brightness(1.5)"},
		"contrast":   {"name": "High Contrast", "filter": "contrast(1.5)"},
		"vintage":    {"name": "Vintage",       "filter": "sepia(0.5) hue-rotate(-30deg)"},
	}

	def __init__(self, **kwargs):
		"""Initialize video recorder widget with configuration."""
		super().__init__(**kwargs)
		self.max_duration = kwargs.get("max_duration", 600)
		self.resolution = kwargs.get("resolution", "1080p")
		self.frame_rate = kwargs.get("frame_rate", 30)
		self.quality = kwargs.get("quality", "high")
		self.enable_audio = kwargs.get("enable_audio", True)
		self.screen_capture = kwargs.get("screen_capture", False)
		self.enable_effects = kwargs.get("enable_effects", False)
		self.face_detection = kwargs.get("face_detection", False)
		self.pip_enabled = kwargs.get("pip_enabled", True)
		self.auto_focus = kwargs.get("auto_focus", True)
		self.device_id = kwargs.get("device_id", None)
		self.save_path = kwargs.get("save_path", "uploads/video")
		self.generate_thumbnails = kwargs.get("generate_thumbnails", True)
		self.watermark = kwargs.get("watermark", None)
		self.chunk_size = kwargs.get("chunk_size", 1024 * 1024)
		self.max_file_size = kwargs.get("max_file_size", 1024 * 1024 * 1024)
		self.mobile_optimize = kwargs.get("mobile_optimize", True)
		self.fallback_mode = kwargs.get("fallback_mode", "file")
		self.error_recovery = kwargs.get("error_recovery", True)
		self.upload_resume = kwargs.get("upload_resume", True)
		self.auto_save = kwargs.get("auto_save", True)
		self.thumbnail_count = kwargs.get("thumbnail_count", 5)
		self.thumbnail_quality = kwargs.get("thumbnail_quality", 0.7)
		self.debug_mode = kwargs.get("debug_mode", False)
		self.retry_attempts = kwargs.get("retry_attempts", 3)
		self.retry_delay = kwargs.get("retry_delay", 1000)
		self.upload_concurrency = kwargs.get("upload_concurrency", 3)
		# Universal kwargs
		self.placeholder = kwargs.get("placeholder", "")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

		# Flask config keys — resolved lazily at render time
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
		"""Render the video recorder widget."""
		kwargs.setdefault("id", field.id)
		return self.render_field(field, **kwargs)

	def render_field(self, field, **kwargs) -> Markup:
		"""Render the video recording widget with controls."""
		kwargs.setdefault("id", field.id)

		upload_url = self._upload_url or self._get_flask_config("VIDEO_UPLOAD_URL", "/api/upload/video")
		chunk_upload_url = self._chunk_upload_url or self._get_flask_config("VIDEO_CHUNK_UPLOAD_URL", "/api/upload/video/chunk")
		auth_token = self._auth_token or self._get_flask_config("VIDEO_AUTH_TOKEN", "")

		has_errors = bool(field.errors)
		invalid_attr = ' aria-invalid="true"' if has_errors else ''
		label_text = str(field.label.text) if field.label else str(_("Video Recording"))
		field_id = escape(field.id)
		resolution_preset = self.RESOLUTION_PRESETS.get(self.resolution, self.RESOLUTION_PRESETS["1080p"])
		quality_preset = self.QUALITY_PRESETS.get(self.quality, self.QUALITY_PRESETS["high"])

		html = self._include_dependencies()

		html += (
			f'<div class="video-recorder-widget{" " + escape(self.css_class) if self.css_class else ""}"'
			f' id="{field_id}-container"'
			f' role="application" aria-label="{escape(label_text)}">'

			# Device selection
			'<div class="device-selection mb-2">'
			f'<label for="{field_id}-camera">{escape(str(_("Camera")))}</label>'
			f'<select id="{field_id}-camera" class="form-control"'
			f' aria-label="{escape(str(_("Camera Selection")))}">'
			f'<option value="">{escape(str(_("Select Camera...")))}</option>'
			'</select>'
		)

		if self.enable_audio:
			html += (
				f'<label for="{field_id}-microphone" class="mt-2">'
				f'{escape(str(_("Microphone")))}</label>'
				f'<select id="{field_id}-microphone" class="form-control mt-1"'
				f' aria-label="{escape(str(_("Microphone Selection")))}">'
				f'<option value="">{escape(str(_("Select Microphone...")))}</option>'
				'</select>'
			)

		html += (
			f'<button type="button" class="btn btn-sm btn-secondary mt-2 test-devices"'
			f' aria-label="{escape(str(_("Test Devices")))}">'
			f'<i class="fa fa-check-circle" aria-hidden="true"></i> {escape(str(_("Test Devices")))}'
			'</button>'
			'</div>'

			# Video preview
			'<div class="video-preview">'
			f'<video id="{field_id}-preview" class="video-js vjs-default-skin"'
			f' playsinline controls preload="auto"'
			f' aria-label="{escape(str(_("Video Preview")))}">'
			f'<p class="vjs-no-js">{escape(str(_("Please enable JavaScript to view this video.")))}</p>'
			'</video>'
			f'<canvas id="{field_id}-overlay" class="video-overlay" aria-hidden="true"></canvas>'
			'</div>'

			# Recording controls
			f'<div class="recording-controls btn-group mt-2" role="toolbar"'
			f' aria-label="{escape(str(_("Recording Controls")))}">'
			f'<button type="button" class="btn btn-primary" id="{field_id}-record"'
			f' aria-label="{escape(str(_("Start Recording")))}" title="{escape(str(_("Start Recording (Ctrl+R)")))}">'
			f'<i class="fa fa-video" aria-hidden="true"></i> {escape(str(_("Record")))}'
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
			f'<button type="button" class="btn btn-info" id="{field_id}-screenshot"'
			f' aria-label="{escape(str(_("Take Screenshot")))}" title="{escape(str(_("Screenshot (Ctrl+T)")))}">'
			f'<i class="fa fa-camera" aria-hidden="true"></i> {escape(str(_("Screenshot")))}'
			'</button>'
			'</div>'

			# Recording status
			f'<div class="recording-status mt-2" role="status"'
			f' aria-label="{escape(str(_("Recording Status")))}" aria-live="polite">'
			'<div class="d-flex justify-content-between">'
			f'<span class="timer" aria-live="polite">00:00</span>'
			f'<span class="file-size" aria-live="polite">0 MB</span>'
			'</div>'
			'<div class="progress">'
			'<div class="progress-bar" role="progressbar" style="width: 0%"'
			' aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">'
			'</div>'
			'</div>'
			'</div>'
		)

		# Effects panel
		if self.enable_effects:
			html += (
				f'<div class="effects-panel mt-2" role="region"'
				f' aria-label="{escape(str(_("Video Effects")))}">'
				f'<h5>{escape(str(_("Video Effects")))}</h5>'
				'<div class="effect-controls">'
				'<div class="mb-3">'
				f'<label for="{field_id}-brightness">{escape(str(_("Brightness")))}</label>'
				f'<input type="range" class="form-range" id="{field_id}-brightness"'
				f' min="-100" max="100" value="0"'
				f' aria-label="{escape(str(_("Brightness Control")))}">'
				'</div>'
				'<div class="mb-3">'
				f'<label for="{field_id}-contrast">{escape(str(_("Contrast")))}</label>'
				f'<input type="range" class="form-range" id="{field_id}-contrast"'
				f' min="-100" max="100" value="0"'
				f' aria-label="{escape(str(_("Contrast Control")))}">'
				'</div>'
				'</div>'
				f'<div class="filters btn-group mt-2" role="toolbar"'
				f' aria-label="{escape(str(_("Video Filters")))}">'
				f'<button type="button" class="btn btn-sm btn-light" data-filter="none"'
				f' aria-label="{escape(str(_("Normal Filter")))}">{escape(str(_("Normal")))}</button>'
				f'<button type="button" class="btn btn-sm btn-light" data-filter="grayscale"'
				f' aria-label="{escape(str(_("Grayscale Filter")))}">{escape(str(_("Grayscale")))}</button>'
				f'<button type="button" class="btn btn-sm btn-light" data-filter="sepia"'
				f' aria-label="{escape(str(_("Sepia Filter")))}">{escape(str(_("Sepia")))}</button>'
				f'<button type="button" class="btn btn-sm btn-light" data-filter="vintage"'
				f' aria-label="{escape(str(_("Vintage Filter")))}">{escape(str(_("Vintage")))}</button>'
				'</div>'
				'</div>'
			)

		# Error messages + hidden inputs
		html += (
			f'<div class="alert mt-2" style="display:none" role="alert" aria-live="polite"></div>'

			f'<input type="hidden" name="{escape(field.name)}" id="{field_id}"'
			f' value="{escape(str(field.data) if field.data else "")}"'
			f' aria-label="{escape(label_text)}"{invalid_attr} aria-hidden="true">'
			f'<input type="file" style="display:none" id="{field_id}-file"'
			f' accept="video/*" capture'
			f' aria-label="{escape(str(_("File Upload Fallback")))}">'
			'</div>'
		)

		# Inline script — all Python values through _js_json
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
					var btn = document.getElementById(FIELD_ID + '-record');
					if (btn && !btn.disabled) btn.click();
					break;
				case 'p':
					e.preventDefault();
					var btn = document.getElementById(FIELD_ID + '-pause');
					if (btn && !btn.disabled) btn.click();
					break;
				case 's':
					e.preventDefault();
					var btn = document.getElementById(FIELD_ID + '-stop');
					if (btn && !btn.disabled) btn.click();
					break;
				case 't':
					e.preventDefault();
					var btn = document.getElementById(FIELD_ID + '-screenshot');
					if (btn) btn.click();
					break;
			}}
		}});

		window.addEventListener('unload', function() {{
			if (window._videoRecorder_) {{
				if (typeof window._videoRecorder_.cleanup === 'function') window._videoRecorder_.cleanup();
			}}
		}});

		if (typeof VideoRecorderWidget !== 'undefined') {{
			window._videoRecorder_ = new VideoRecorderWidget({{
				containerId: FIELD_ID + '-container',
				fieldId: FIELD_ID,
				maxDuration: {_js_json(self.max_duration)},
				resolution: {_js_json(resolution_preset)},
				frameRate: {_js_json(self.frame_rate)},
				quality: {_js_json(quality_preset)},
				enableAudio: {_js_json(self.enable_audio)},
				screenCapture: {_js_json(self.screen_capture)},
				enableEffects: {_js_json(self.enable_effects)},
				faceDetection: {_js_json(self.face_detection)},
				pipEnabled: {_js_json(self.pip_enabled)},
				autoFocus: {_js_json(self.auto_focus)},
				deviceId: {_js_json(self.device_id)},
				generateThumbnails: {_js_json(self.generate_thumbnails)},
				watermark: {_js_json(self.watermark)},
				chunkSize: {_js_json(self.chunk_size)},
				maxFileSize: {_js_json(self.max_file_size)},
				mobileOptimize: {_js_json(self.mobile_optimize)},
				fallbackMode: FALLBACK_MODE,
				errorRecovery: {_js_json(self.error_recovery)},
				uploadResume: UPLOAD_RESUME,
				autoSave: {_js_json(self.auto_save)},
				thumbnailCount: {_js_json(self.thumbnail_count)},
				thumbnailQuality: {_js_json(self.thumbnail_quality)},
				debugMode: {_js_json(self.debug_mode)},
				retryAttempts: {_js_json(self.retry_attempts)},
				retryDelay: {_js_json(self.retry_delay)},
				uploadConcurrency: {_js_json(self.upload_concurrency)},
				effects: {_js_json(self.VIDEO_EFFECTS)},
				uploadUrl: UPLOAD_URL,
				chunkUploadUrl: CHUNK_UPLOAD_URL,
				authToken: AUTH_TOKEN,

				onError: function(error) {{ showAlert(error, 'danger'); }},
				onComplete: function(data) {{
					try {{
						if (field) field.value = JSON.stringify(data);
						showAlert({_js_json(str(_("Recording completed successfully")))}, 'success');
					}} catch (e) {{
						showAlert('Recording validation failed: ' + e.message, 'danger');
					}}
				}},
				onStateChange: function(state) {{
					var recBtn = document.getElementById(FIELD_ID + '-record');
					var pauseBtn = document.getElementById(FIELD_ID + '-pause');
					var stopBtn = document.getElementById(FIELD_ID + '-stop');
					if (recBtn) recBtn.disabled = (state === 'recording');
					if (pauseBtn) pauseBtn.disabled = (state !== 'recording');
					if (stopBtn) stopBtn.disabled = (state === 'idle');
					var statusEl = container.querySelector('.recording-status');
					if (statusEl) statusEl.setAttribute('aria-label', 'Recording Status: ' + state);
				}},
				onDeviceError: function(error) {{
					showAlert(error, 'danger');
					if (FALLBACK_MODE === 'file') {{
						var fileInput = document.getElementById(FIELD_ID + '-file');
						if (fileInput) {{
							fileInput.style.display = 'block';
							fileInput.setAttribute('aria-label', {_js_json(str(_("File Upload Fallback Mode")))});
						}}
					}}
				}},
				onUploadError: function(error) {{
					showAlert(error, 'danger');
					if (UPLOAD_RESUME && window._videoRecorder_ && typeof window._videoRecorder_.retryUpload === 'function') {{
						window._videoRecorder_.retryUpload();
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

	def process_formdata(self, valuelist):
		"""Process form data to database format."""
		if valuelist:
			try:
				data = json.loads(valuelist[0])
				self._validate_video_data(data)
				self.data = data
			except json.JSONDecodeError as e:
				raise ValueError("Invalid video data format") from e
			except ValueError as e:
				raise ValueError(str(e))
		else:
			self.data = None

	def _validate_video_data(self, data):
		"""Validate video data and constraints."""
		if not isinstance(data, dict) or "video" not in data:
			raise ValueError("Invalid video data structure")
		if len(data["video"]) > self.max_file_size:
			raise ValueError(
				f"Video file size exceeds maximum ({self.max_file_size / (1024 * 1024):.1f}MB)"
			)
		if "format" not in data or data["format"] not in ["mp4", "webm"]:
			raise ValueError("Unsupported video format")
		if "duration" in data and data["duration"] > self.max_duration:
			raise ValueError(
				f"Recording exceeds maximum duration ({self.max_duration}s)"
			)
		if "metadata" in data:
			required_fields = ["timestamp", "resolution", "frameRate", "quality"]
			if not all(f in data["metadata"] for f in required_fields):
				raise ValueError("Missing required metadata fields")

	def pre_validate(self, form):
		"""Validate video data before form processing."""
		if form.flags.required and not self.data:
			raise ValueError("Video recording is required")
