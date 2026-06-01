"""BarcodeQRScannerWidget — PgAppForge widget(s)."""

from __future__ import annotations

from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape


class BarcodeQRScannerWidget(BS3TextFieldWidget):
	"""
	Barcode and QR code scanner widget with camera integration.

	Features:
	- Multiple format support (1D/2D barcodes, QR codes)
	- Camera selection and switching
	- Real-time auto-detection
	- Manual entry fallback with validation
	- Batch scanning mode
	- Scan history with export
	- Custom format validation
	- Result formatting/cleaning
	- Sound/vibration feedback
	- Zoom controls
	- Torch/flash control
	- Orientation handling

	Database Type:
		PostgreSQL: VARCHAR or JSONB (for batch mode)
		SQLAlchemy: String or JSON

	Required Dependencies:
	- ZXing 0.19+
	- QuaggaJS 0.12+
	- MediaDevices API
	- WebAssembly support

	Browser Support:
	- Chrome 60+, Firefox 60+, Safari 11.1+, Edge 79+

	Required Permissions:
	- Camera access
	"""

	JS_DEPENDENCIES = [
		"https://unpkg.com/@zxing/library@0.19.1",
		"https://cdn.jsdelivr.net/npm/quagga@0.12.1/dist/quagga.min.js",
		"/static/js/barcode-scanner.js",
	]

	CSS_DEPENDENCIES = ["/static/css/barcode-scanner.css"]

	DEFAULT_FORMATS = ["qr", "ean13", "ean8", "code128", "code39", "upc"]

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.formats = kwargs.get("formats", self.DEFAULT_FORMATS)
		self.auto_submit = kwargs.get("auto_submit", True)
		self.history = kwargs.get("history", True)
		self.validate = kwargs.get("validate", True)
		self.camera_id = kwargs.get("camera_id", None)
		self.batch_mode = kwargs.get("batch_mode", False)
		self.result_handler = kwargs.get("result_handler", None)
		self.error_correction = kwargs.get("error_correction", "M")
		self.offline_support = kwargs.get("offline_support", True)
		self.sound_feedback = kwargs.get("sound_feedback", True)
		self.vibrate = kwargs.get("vibrate", True)
		self.torch = kwargs.get("torch", True)
		self.zoom = kwargs.get("zoom", True)
		self.orientation = kwargs.get("orientation", True)
		self.preprocessing = kwargs.get("preprocessing", True)
		self.confidence = kwargs.get("confidence", 0.8)
		self.scan_interval = kwargs.get("scan_interval", 100)
		self.history_size = kwargs.get("history_size", 100)
		self.timeout = kwargs.get("timeout", 30)
		# Universal kwargs
		self.placeholder = kwargs.get("placeholder", "")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

	def __call__(self, field, **kwargs):
		"""Render the barcode scanner widget."""
		kwargs.setdefault("id", field.id)
		return self.render_field(field, **kwargs)

	def render_field(self, field, **kwargs):
		"""Render the barcode scanner widget with controls and preview."""
		kwargs.setdefault("id", field.id)

		has_errors = bool(field.errors)
		invalid_attr = ' aria-invalid="true"' if has_errors else ''
		label_text = str(field.label.text) if field.label else str(_("Barcode Scanner"))
		field_id = escape(field.id)

		html = (
			self._include_dependencies() +
			f'<div class="barcode-scanner-widget" id="{field_id}-container"'
			f' role="application" aria-label="{escape(label_text)}">'

			# Camera preview
			f'<div class="camera-container">'
			f'<video id="{field_id}-preview" playsinline autoplay'
			f' aria-label="{escape(str(_("Camera preview")))}">'
			'</video>'
			f'<canvas id="{field_id}-canvas" style="display:none;" aria-hidden="true"></canvas>'
			'<div class="scanner-overlay" aria-hidden="true">'
			'<div class="scan-region"></div>'
			'</div>'
			'<div class="scanner-controls" role="toolbar"'
			f' aria-label="{escape(str(_("Scanner controls")))}">'
			+ self._render_camera_controls(field.id) +
			'</div>'
			'</div>'

			# Results area
			'<div class="results-container">'
			f'<label for="{field_id}-manual" class="visually-hidden sr-only">'
			f'{escape(str(_("Enter code manually")))}</label>'
			f'<input type="text" id="{field_id}-manual"'
			' class="form-control manual-input"'
			f' placeholder="{escape(str(_("Enter code manually...")))}"'
			f' aria-label="{escape(str(_("Manual barcode entry")))}">'
			+ (self._render_history_table(field.id) if self.history else "") +
			'</div>'

			# Loading state
			'<div class="loading-overlay" style="display:none;" role="status"'
			f' aria-label="{escape(str(_("Initializing camera...")))}">'
			'<div class="spinner-border" aria-hidden="true"></div>'
			f'<span class="visually-hidden sr-only">{escape(str(_("Initializing camera...")))}</span>'
			'</div>'

			# Error messages
			f'<div class="alert alert-danger scanner-error" style="display:none;"'
			f' role="alert" aria-live="assertive"></div>'

			# Hidden field storing the scanned value
			f'<input type="hidden" name="{escape(field.name)}" id="{field_id}"'
			f' value="{escape(field.data or "")}"'
			f' aria-label="{escape(label_text)}"{invalid_attr}>'
			'</div>'
		)

		# Inline script — all dynamic values go through _js_json
		camera_id_js = _js_json(self.camera_id) if self.camera_id else 'null'
		html += f"""
<script>
(function() {{
	var FIELD_ID = {_js_json(field.id)};

	function init() {{
		var container = document.getElementById(FIELD_ID + '-container');
		if (!container) return;

		var hiddenField = document.getElementById(FIELD_ID);
		var manualInput = document.getElementById(FIELD_ID + '-manual');

		// Sync manual input to hidden field
		if (manualInput && hiddenField) {{
			manualInput.addEventListener('input', function() {{
				hiddenField.value = this.value;
			}});
		}}

		// Orientation change
		if ({_js_json(self.orientation)}) {{
			window.addEventListener('orientationchange', function() {{
				if (window.barcodeScanner_) window.barcodeScanner_.handleOrientation();
			}});
		}}

		window.addEventListener('unload', function() {{
			if (window.barcodeScanner_) window.barcodeScanner_.cleanup();
		}});

		// Initialize scanner if BarcodeScanner class is available
		if (typeof BarcodeScanner !== 'undefined') {{
			window.barcodeScanner_ = new BarcodeScanner(FIELD_ID, {{
				formats: {_js_json(self.formats)},
				autoSubmit: {_js_json(self.auto_submit)},
				history: {_js_json(self.history)},
				validate: {_js_json(self.validate)},
				cameraId: {camera_id_js},
				batchMode: {_js_json(self.batch_mode)},
				errorCorrection: {_js_json(self.error_correction)},
				offlineSupport: {_js_json(self.offline_support)},
				soundFeedback: {_js_json(self.sound_feedback)},
				vibrate: {_js_json(self.vibrate)},
				torch: {_js_json(self.torch)},
				zoom: {_js_json(self.zoom)},
				orientation: {_js_json(self.orientation)},
				preprocessing: {_js_json(self.preprocessing)},
				confidence: {_js_json(self.confidence)},
				scanInterval: {_js_json(self.scan_interval)},
				historySize: {_js_json(self.history_size)},
				timeout: {_js_json(self.timeout)},

				onScan: function(result) {{
					if (hiddenField) hiddenField.value = result;
					if ({_js_json(self.auto_submit)}) {{
						var form = hiddenField && hiddenField.closest ? hiddenField.closest('form') : null;
						if (form) form.submit();
					}}
				}},
				onError: function(error) {{
					var alertEl = container.querySelector('.scanner-error');
					if (alertEl) {{
						alertEl.textContent = error;
						alertEl.style.display = 'block';
						setTimeout(function() {{ alertEl.style.display = 'none'; }}, 5000);
					}}
				}},
				onStateChange: function(state) {{
					var loading = container.querySelector('.loading-overlay');
					if (loading) loading.style.display = state.loading ? 'block' : 'none';
					if (state.camera === 'unavailable' && manualInput) {{
						manualInput.style.display = 'block';
					}}
				}}
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

	def _render_camera_controls(self, field_id: str) -> str:
		"""Render camera control buttons."""
		controls = []
		safe_id = escape(field_id)

		if self.torch:
			controls.append(
				f'<button type="button" class="btn btn-light torch-toggle"'
				f' aria-label="{escape(str(_("Toggle torch")))}"'
				f' title="{escape(str(_("Toggle torch")))}">'
				'<i class="fa fa-bolt" aria-hidden="true"></i>'
				'</button>'
			)

		if self.zoom:
			controls.append(
				'<div class="zoom-controls" role="group"'
				f' aria-label="{escape(str(_("Zoom controls")))}">'
				f'<button type="button" class="btn btn-light zoom-in"'
				f' aria-label="{escape(str(_("Zoom in")))}">'
				'<i class="fa fa-search-plus" aria-hidden="true"></i>'
				'</button>'
				f'<button type="button" class="btn btn-light zoom-out"'
				f' aria-label="{escape(str(_("Zoom out")))}">'
				'<i class="fa fa-search-minus" aria-hidden="true"></i>'
				'</button>'
				'</div>'
			)

		return "\n".join(controls)

	def _render_history_table(self, field_id: str) -> str:
		"""Render scan history table."""
		safe_id = escape(field_id)
		return (
			f'<div class="scan-history mt-2" role="region"'
			f' aria-label="{escape(str(_("Scan history")))}">'
			f'<h5>{escape(str(_("Scan History")))}</h5>'
			'<table class="table table-sm" role="grid"'
			f' aria-label="{escape(str(_("Scan history table")))}">'
			'<thead>'
			'<tr>'
			f'<th scope="col">{escape(str(_("Code")))}</th>'
			f'<th scope="col">{escape(str(_("Type")))}</th>'
			f'<th scope="col">{escape(str(_("Time")))}</th>'
			f'<th scope="col">{escape(str(_("Actions")))}</th>'
			'</tr>'
			'</thead>'
			'<tbody></tbody>'
			'</table>'
			'</div>'
		)

	def process_formdata(self, valuelist):
		"""Process form data and validate."""
		if valuelist:
			try:
				self.data = self._validate_scan_data(valuelist[0])
			except ValueError as e:
				raise ValueError(str(e))
		else:
			self.data = None

	def _validate_scan_data(self, value: str) -> str:
		"""Validate scanned barcode data."""
		if not value:
			raise ValueError("Empty scan result")

		if self.validate:
			format_validators = {
				"ean13": lambda x: len(x) == 13 and x.isdigit(),
				"ean8": lambda x: len(x) == 8 and x.isdigit(),
				"code128": lambda x: len(x) >= 1,
				"qr": lambda x: len(x) >= 1,
			}

			valid = False
			for fmt in self.formats:
				validator = format_validators.get(fmt)
				if validator and validator(value):
					valid = True
					break
				elif fmt not in format_validators:
					# Unknown format — accept by default
					valid = True
					break

			if not valid:
				raise ValueError("Invalid barcode format")

		return value

	def pre_validate(self, form):
		"""Validate before form processing."""
		if self.data is not None:
			try:
				self.data = self._validate_scan_data(self.data)
			except ValueError as e:
				raise ValueError(str(e))
