"""PeriodicCameraWidget — PgAppForge widget(s)."""

from __future__ import annotations
import os
from datetime import datetime

from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape


class PeriodicCameraWidget(BS3TextFieldWidget):
	"""
	Widget for capturing periodic camera images with customizable intervals and settings.
	Stores image data and metadata in PostgreSQL JSONB column.

	Features:
	- Periodic image capture with configurable intervals
	- Multiple camera support with auto-detection
	- Image quality and resolution control
	- Motion detection with sensitivity settings
	- Face detection and counting
	- Timestamp and metadata overlays
	- Automatic storage management and cleanup
	- Background operation support
	- Custom trigger conditions
	- Privacy controls and data protection
	- Error recovery and retry logic
	- Live preview mode
	- Multiple export formats

	Database Type:
		PostgreSQL: JSONB column for storing image data and metadata
		SQLAlchemy: JSON type with schema validation

	Required Dependencies:
	- MediaDevices API
	- Canvas API
	- Face-API.js (optional)
	"""

	JS_DEPENDENCIES = [
		"https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/dist/face-api.min.js",
		"https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
		"/static/js/periodic-camera.js",
	]

	CSS_DEPENDENCIES = ["/static/css/periodic-camera.css"]

	def __init__(self, **kwargs):
		super().__init__(**kwargs)

		# Core settings
		self.interval = max(10, min(3600, kwargs.get("interval", 300)))
		self.camera = kwargs.get("camera", "back")
		self.quality = kwargs.get("quality", "high")
		self.motion_detection = kwargs.get("motion_detection", False)
		self.face_detection = kwargs.get("face_detection", False)
		self.max_images = max(10, min(1000, kwargs.get("max_images", 100)))
		self.background = kwargs.get("background", False)
		self.timestamp_overlay = kwargs.get("timestamp_overlay", True)
		self.storage_path = kwargs.get("storage_path", "images/")
		self.privacy_mode = kwargs.get("privacy_mode", False)

		self.processing_options = {
			"resize": True,
			"max_width": 1920,
			"max_height": 1080,
			"format": "jpeg",
			"quality": 0.9,
			**kwargs.get("processing_options", {}),
		}

		self.custom_triggers = {
			"motion_threshold": 0.1,
			"face_confidence": 0.8,
			"min_light_level": 10,
			**kwargs.get("custom_triggers", {}),
		}

		# Universal kwargs
		self.placeholder = kwargs.get("placeholder", "")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

		# Internal state (server-side only, not used in rendering)
		self._capturing = False
		self._stream = None
		self._last_image = None
		self._error_count = 0
		self._worker = None

		self._validate_config()

	def _validate_config(self):
		"""Validate widget configuration settings."""
		valid_qualities = ["low", "medium", "high"]
		if self.quality not in valid_qualities:
			raise ValueError(f"Invalid quality setting. Must be one of: {valid_qualities}")
		if self.interval < 10:
			raise ValueError("Interval must be at least 10 seconds")
		# Only create storage directory if it doesn't already exist
		if not os.path.exists(self.storage_path):
			os.makedirs(self.storage_path, exist_ok=True)

	def __call__(self, field, **kwargs):
		"""Render the camera widget."""
		kwargs.setdefault("id", field.id)
		return self.render_field(field, **kwargs)

	def render_field(self, field, **kwargs) -> Markup:
		"""Render the camera widget with preview and controls."""
		kwargs.setdefault("id", field.id)

		has_errors = bool(field.errors)
		invalid_attr = ' aria-invalid="true"' if has_errors else ''
		label_text = str(field.label.text) if field.label else str(_("Camera Capture"))
		field_id = escape(field.id)

		html = self._include_dependencies()

		html += (
			f'<div class="periodic-camera-widget{" " + escape(self.css_class) if self.css_class else ""}"'
			f' id="{field_id}-container"'
			f' role="application" aria-label="{escape(label_text)}">'

			# Preview area
			'<div class="camera-preview">'
			f'<video id="{field_id}-preview" autoplay playsinline'
			f' class="preview-video" style="display:none;"'
			f' aria-label="{escape(str(_("Camera preview")))}">'
			'</video>'
			f'<canvas id="{field_id}-canvas" class="preview-canvas"'
			f' role="img" aria-label="{escape(str(_("Image preview")))}"></canvas>'

			# Camera controls
			f'<div class="camera-controls" role="toolbar"'
			f' aria-label="{escape(str(_("Camera Controls")))}">'
			f'<button class="btn btn-primary start-capture" type="button"'
			f' aria-label="{escape(str(_("Start capture")))}">'
			f'<i class="fa fa-camera" aria-hidden="true"></i> {escape(str(_("Start")))}'
			'</button>'
			f'<button class="btn btn-danger stop-capture" type="button" disabled'
			f' aria-label="{escape(str(_("Stop capture")))}">'
			f'<i class="fa fa-stop" aria-hidden="true"></i> {escape(str(_("Stop")))}'
			'</button>'
			f'<button class="btn btn-secondary single-photo" type="button"'
			f' aria-label="{escape(str(_("Take single photo")))}">'
			f'<i class="fa fa-camera" aria-hidden="true"></i> {escape(str(_("Single")))}'
			'</button>'
			f'<label for="{field_id}-cam-select" class="visually-hidden sr-only">'
			f'{escape(str(_("Select camera")))}</label>'
			f'<select class="camera-select form-control" id="{field_id}-cam-select"'
			f' aria-label="{escape(str(_("Select camera")))}"></select>'
			'</div>'

			# Settings
			'<div class="capture-settings mt-2">'
			'<div class="mb-3">'
			f'<label for="{field_id}-interval">{escape(str(_("Interval (seconds)")))}</label>'
			f'<input type="number" class="interval-input form-control" id="{field_id}-interval"'
			f' min="10" max="3600" value="{int(self.interval)}"'
			f' aria-label="{escape(str(_("Capture interval in seconds")))}">'
			'</div>'
			'<div class="form-check">'
			f'<input type="checkbox" class="form-check-input motion-detection-toggle"'
			f' id="{field_id}-motion"'
			+ (' checked' if self.motion_detection else '') +
			f' aria-label="{escape(str(_("Enable Motion Detection")))}">'
			f'<label class="form-check-label" for="{field_id}-motion">'
			f'{escape(str(_("Motion Detection")))}</label>'
			'</div>'
			'</div>'
			'</div>'

			# Image gallery
			f'<div class="image-gallery mt-2" role="region"'
			f' aria-label="{escape(str(_("Captured images")))}">'
			'<div class="gallery-controls">'
			f'<button class="btn btn-secondary clear-images" type="button"'
			f' aria-label="{escape(str(_("Clear all captured images")))}">'
			f'<i class="fa fa-trash" aria-hidden="true"></i> {escape(str(_("Clear")))}'
			'</button>'
			f'<div class="btn-group">'
			f'<button class="btn btn-secondary dropdown-toggle export-images" type="button"'
			f' data-bs-toggle="dropdown" data-toggle="dropdown"'
			f' aria-haspopup="true" aria-expanded="false"'
			f' aria-label="{escape(str(_("Export images")))}">'
			f'<i class="fa fa-download" aria-hidden="true"></i> {escape(str(_("Export")))}'
			'</button>'
			'<ul class="dropdown-menu">'
			f'<li><a class="dropdown-item" href="#" data-format="zip"'
			f' aria-label="{escape(str(_("Export as ZIP archive")))}">{escape(str(_("ZIP Archive")))}</a></li>'
			f'<li><a class="dropdown-item" href="#" data-format="tar"'
			f' aria-label="{escape(str(_("Export as TAR archive")))}">{escape(str(_("TAR Archive")))}</a></li>'
			'</ul>'
			'</div>'
			'</div>'
			f'<div class="gallery-grid" id="{field_id}-gallery" role="list"'
			f' aria-label="{escape(str(_("Captured image gallery")))}"></div>'
			'</div>'

			# Status messages
			f'<div class="status-messages mt-2" aria-live="polite">'
			'<div class="capture-status"></div>'
			'<div class="storage-status"></div>'
			'</div>'

			# Error messages
			f'<div class="alert alert-danger" style="display:none;" role="alert" aria-live="assertive"></div>'

			# Hidden field
			f'<input type="hidden" name="{escape(field.name)}" id="{field_id}"'
			f' value="{escape(str(field.data) if field.data else "")}"'
			f' aria-label="{escape(label_text)}"{invalid_attr}>'
			'</div>'
		)

		# Inline script — all Python values through _js_json
		html += f"""
<script>
(function() {{
	var FIELD_ID = {_js_json(field.id)};

	function getContainer() {{ return document.getElementById(FIELD_ID + '-container'); }}
	function getField() {{ return document.getElementById(FIELD_ID); }}

	function showError(message) {{
		var container = getContainer();
		if (!container) return;
		var alertEl = container.querySelector('.alert');
		if (alertEl) {{
			alertEl.textContent = message;
			alertEl.style.display = 'block';
			setTimeout(function() {{ alertEl.style.display = 'none'; }}, 5000);
		}}
	}}

	function updateStatus(message) {{
		var container = getContainer();
		if (!container) return;
		var statusEl = container.querySelector('.capture-status');
		if (statusEl) statusEl.textContent = message;
	}}

	function init() {{
		var container = getContainer();
		if (!container) return;
		var field = getField();

		if (typeof PeriodicCamera === 'undefined') return;

		var camera = new PeriodicCamera(FIELD_ID, {{
			interval: {_js_json(self.interval)},
			camera: {_js_json(self.camera)},
			quality: {_js_json(self.quality)},
			motionDetection: {_js_json(self.motion_detection)},
			faceDetection: {_js_json(self.face_detection)},
			maxImages: {_js_json(self.max_images)},
			background: {_js_json(self.background)},
			timestampOverlay: {_js_json(self.timestamp_overlay)},
			privacyMode: {_js_json(self.privacy_mode)},
			processingOptions: {_js_json(self.processing_options)},
			customTriggers: {_js_json(self.custom_triggers)},

			onCapture: function(imageData) {{
				updateGallery(imageData);
				updateStatus({_js_json(str(_("Capture successful")))});
				if (field) field.value = JSON.stringify(imageData);
			}},
			onError: function(error) {{
				showError(error);
				updateStatus({_js_json(str(_("Capture failed")))} + ': ' + error);
			}}
		}});

		// Restore existing data
		if (field && field.value) {{
			try {{
				camera.loadImages(JSON.parse(field.value));
			}} catch(e) {{ /* ignore parse errors */ }}
		}}

		// Event handlers — scoped to container, no global functions
		var startBtn = container.querySelector('.start-capture');
		var stopBtn = container.querySelector('.stop-capture');
		var singleBtn = container.querySelector('.single-photo');
		var clearBtn = container.querySelector('.clear-images');

		if (startBtn) startBtn.addEventListener('click', function() {{ camera.startCapture(); }});
		if (stopBtn) stopBtn.addEventListener('click', function() {{ camera.stopCapture(); }});
		if (singleBtn) singleBtn.addEventListener('click', function() {{ camera.takeSinglePhoto(); }});
		if (clearBtn) clearBtn.addEventListener('click', function() {{
			if (confirm({_js_json(str(_("Clear all captured images?")))})) {{
				camera.clearImages();
			}}
		}});

		// Export links
		container.querySelectorAll('.dropdown-menu a[data-format]').forEach(function(link) {{
			link.addEventListener('click', function(e) {{
				e.preventDefault();
				camera.exportImages(this.dataset.format);
			}});
		}});

		// Visibility change for background support
		document.addEventListener('visibilitychange', function() {{
			if (document.hidden) {{ camera.handleBackground(); }}
			else {{ camera.handleForeground(); }}
		}});

		window.addEventListener('unload', function() {{ camera.cleanup(); }});
	}}

	function updateGallery(imageData) {{
		// Gallery rendering is delegated to the PeriodicCamera JS class
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
		css_includes = "\n".join(
			f'<link rel="stylesheet" href="{escape(url)}">' for url in self.CSS_DEPENDENCIES
		)
		js_includes = "\n".join(
			f'<script src="{escape(url)}"></script>' for url in self.JS_DEPENDENCIES
		)
		return f"{css_includes}\n{js_includes}\n"

	def take_single_photo(self) -> dict:
		"""Take a single photo immediately (server-side stub)."""
		return {"timestamp": datetime.now().isoformat(), "error": "Server-side capture not supported"}

	def cleanup(self):
		"""Clean up server-side resources."""
		try:
			if self._stream:
				self._stream.stop()
			if self._worker:
				self._worker.terminate()
			self._capturing = False
			self._stream = None
			self._last_image = None
		except Exception:
			pass
