"""QrCodeWidget — PgAppForge widget(s)."""

from __future__ import annotations

from markupsafe import Markup, escape
from wtforms.widgets import Input
from flask_babel import gettext
from pgappforge.widgets_postgresql._cdn import QRCODE_CDN_URL, JSQR_CDN_URL
from pgappforge.widgets._utils import js_json as _js_json


class QrCodeWidget(Input):
	"""
	Advanced QR Code widget with comprehensive features:

	- QR code generation with customization
	- QR code scanning via camera
	- Batch QR code generation
	- Multiple formats (URL, text, email, phone, SMS, WiFi, vCard)
	- Customizable styling (colors, logos, patterns)
	- Export capabilities (PNG, SVG, PDF)
	- History and management
	- Error correction levels
	"""

	def __init__(
		self,
		enable_generation=True,
		enable_scanning=True,
		enable_customization=True,
		enable_batch_generation=False,
		enable_export=True,
		enable_history=True,
		default_size=256,
		default_error_correction='M',
		supported_formats=None,
		enable_logo_upload=True,
		enable_color_customization=True,
		enable_pattern_selection=True,
		max_history_items=50,
		enable_bulk_download=True,
		enable_analytics=False,
		# Universal kwargs
		placeholder: str = "",
		css_class: str = "",
		description: str = "",
		readonly: bool = False,
		disabled: bool = False,
		**kwargs,
	):
		super().__init__(**kwargs)
		self.enable_generation = enable_generation
		self.enable_scanning = enable_scanning
		self.enable_customization = enable_customization
		self.enable_batch_generation = enable_batch_generation
		self.enable_export = enable_export
		self.enable_history = enable_history
		self.default_size = default_size
		self.default_error_correction = default_error_correction
		self.supported_formats = supported_formats or [
			'text', 'url', 'email', 'phone', 'sms', 'wifi', 'vcard', 'location'
		]
		self.enable_logo_upload = enable_logo_upload
		self.enable_color_customization = enable_color_customization
		self.enable_pattern_selection = enable_pattern_selection
		self.max_history_items = max_history_items
		self.enable_bulk_download = enable_bulk_download
		self.enable_analytics = enable_analytics
		self.placeholder = placeholder
		self.css_class = css_class
		self.description = description
		self.readonly = readonly
		self.disabled = disabled

	def __call__(self, field, **kwargs):
		"""Render the QR code widget."""
		widget_id = kwargs.get('id', field.id or field.name)

		css = self._generate_css(widget_id)
		html = self._generate_html(field, widget_id, **kwargs)
		js = self._generate_javascript(widget_id, field.data or '')

		return Markup(f"{css}\n{html}\n{js}")

	def _get_export_buttons_html(self, widget_id):
		"""Generate export buttons HTML."""
		if not self.enable_export:
			return ""
		safe_wid = escape(widget_id)
		return (
			f'<button type="button" id="{safe_wid}-download-png"'
			f' class="btn btn-sm btn-secondary" disabled'
			f' aria-label="{escape(gettext("Download PNG"))}">'
			f'<i class="fas fa-download" aria-hidden="true"></i> PNG'
			'</button>'
			f'<button type="button" id="{safe_wid}-download-svg"'
			f' class="btn btn-sm btn-secondary" disabled'
			f' aria-label="{escape(gettext("Download SVG"))}">'
			f'<i class="fas fa-download" aria-hidden="true"></i> SVG'
			'</button>'
		)

	def _get_color_customization_html(self, widget_id):
		"""Generate color customization HTML."""
		if not self.enable_color_customization:
			return ""
		safe_wid = escape(widget_id)
		return (
			'<div class="mb-3">'
			f'<label for="{safe_wid}-fg-color">{escape(gettext("Foreground Color"))}</label>'
			f'<div class="d-flex gap-2 align-items-center">'
			f'<input type="color" id="{safe_wid}-fg-color" value="#000000"'
			f' aria-label="{escape(gettext("Foreground Color"))}">'
			f'<span>{escape(gettext("Foreground"))}</span>'
			'</div>'
			'</div>'
			'<div class="mb-3">'
			f'<label for="{safe_wid}-bg-color">{escape(gettext("Background Color"))}</label>'
			f'<div class="d-flex gap-2 align-items-center">'
			f'<input type="color" id="{safe_wid}-bg-color" value="#ffffff"'
			f' aria-label="{escape(gettext("Background Color"))}">'
			f'<span>{escape(gettext("Background"))}</span>'
			'</div>'
			'</div>'
		)

	def _get_logo_upload_html(self, widget_id):
		"""Generate logo upload HTML."""
		if not self.enable_logo_upload:
			return ""
		safe_wid = escape(widget_id)
		return (
			'<div class="mb-3">'
			f'<label for="{safe_wid}-logo-upload">{escape(gettext("Logo Overlay"))}</label>'
			f'<input type="file" id="{safe_wid}-logo-upload" class="form-control" accept="image/*"'
			f' aria-label="{escape(gettext("Logo Overlay"))}">'
			f'<small class="form-text text-muted">{escape(gettext("Optional logo to overlay on QR code"))}</small>'
			'</div>'
		)

	def _get_customization_html(self, widget_id):
		"""Generate customization section HTML."""
		if not self.enable_customization:
			return ""
		safe_wid = escape(widget_id)
		return (
			f'<div id="{safe_wid}-customization">'
			f'<h6>{escape(gettext("Customization"))}</h6>'
			'<div class="mb-3">'
			f'<label for="{safe_wid}-size-slider">{escape(gettext("Size"))}</label>'
			f'<input type="range" id="{safe_wid}-size-slider" min="128" max="512"'
			f' value="{self.default_size}" class="form-control"'
			f' aria-label="{escape(gettext("QR Code size"))}">'
			f'<small id="{safe_wid}-size-display" aria-live="polite">{self.default_size}px</small>'
			'</div>'
			'<div class="mb-3">'
			f'<label for="{safe_wid}-error-correction">{escape(gettext("Error Correction"))}</label>'
			f'<select id="{safe_wid}-error-correction" class="form-control"'
			f' aria-label="{escape(gettext("Error Correction Level"))}">'
			'<option value="L">Low (7%)</option>'
			'<option value="M" selected>Medium (15%)</option>'
			'<option value="Q">Quartile (25%)</option>'
			'<option value="H">High (30%)</option>'
			'</select>'
			'</div>'
			+ self._get_color_customization_html(widget_id)
			+ self._get_logo_upload_html(widget_id) +
			'</div>'
		)

	def _get_generation_section_html(self, widget_id):
		"""Generate the generation section HTML."""
		if not self.enable_generation:
			return ""
		safe_wid = escape(widget_id)
		return (
			f'<div id="{safe_wid}-generate-tab" class="tab-content active">'
			f'<div id="{safe_wid}-form-section">'
			f'<h6>{escape(gettext("QR Code Content"))}</h6>'
			'<div class="mb-3">'
			f'<label for="{safe_wid}-content-type">{escape(gettext("Content Type"))}</label>'
			f'<select id="{safe_wid}-content-type" class="form-control"'
			f' aria-label="{escape(gettext("Content Type"))}">'
			f'<option value="text">{escape(gettext("Plain Text"))}</option>'
			f'<option value="url">{escape(gettext("Website URL"))}</option>'
			f'<option value="email">{escape(gettext("Email Address"))}</option>'
			f'<option value="phone">{escape(gettext("Phone Number"))}</option>'
			f'<option value="sms">{escape(gettext("SMS Message"))}</option>'
			f'<option value="wifi">{escape(gettext("WiFi Network"))}</option>'
			f'<option value="vcard">{escape(gettext("Contact Card"))}</option>'
			f'<option value="location">{escape(gettext("Geographic Location"))}</option>'
			'</select>'
			'</div>'
			'<div class="mb-3">'
			f'<label for="{safe_wid}-content-input">{escape(gettext("Content"))}</label>'
			f'<textarea id="{safe_wid}-content-input" class="form-control" rows="3"'
			f' placeholder="{escape(gettext("Enter content for QR code..."))}"'
			f' aria-label="{escape(gettext("QR Code content"))}"></textarea>'
			'</div>'
			'<div class="mb-3">'
			f'<button type="button" id="{safe_wid}-generate-btn" class="btn btn-primary"'
			f' aria-label="{escape(gettext("Generate QR Code"))}">'
			f'<i class="fas fa-magic" aria-hidden="true"></i> {escape(gettext("Generate QR Code"))}'
			'</button>'
			'</div>'
			'</div>'
			f'<div id="{safe_wid}-preview">'
			f'<div id="{safe_wid}-qr-display">'
			f'<div id="{safe_wid}-qr-placeholder"'
			f' style="width: {self.default_size}px; height: {self.default_size}px;'
			f' border: 2px dashed var(--bs-border-color, #ccc); display: flex;'
			f' align-items: center; justify-content: center;'
			f' color: var(--bs-secondary-color, #999); margin: 0 auto;"'
			f' aria-label="{escape(gettext("QR code preview placeholder"))}">'
			f'<i class="fas fa-qrcode" style="font-size: 48px;" aria-hidden="true"></i>'
			'</div>'
			f'<canvas id="{safe_wid}-qr-canvas" class="hidden"'
			f' aria-label="{escape(gettext("Generated QR code"))}"></canvas>'
			'<div style="margin-top: 12px;">'
			+ self._get_export_buttons_html(widget_id) +
			'</div>'
			'</div>'
			+ self._get_customization_html(widget_id) +
			'</div>'
			'</div>'
		)

	def _get_scanning_section_html(self, widget_id):
		"""Generate the scanning section HTML."""
		if not self.enable_scanning:
			return ""
		safe_wid = escape(widget_id)
		return (
			f'<div id="{safe_wid}-scan-tab" class="tab-content">'
			f'<div id="{safe_wid}-scanner">'
			f'<h6>{escape(gettext("QR Code Scanner"))}</h6>'
			f'<video id="{safe_wid}-camera" class="hidden"'
			f' aria-label="{escape(gettext("Camera feed for QR scanning"))}"></video>'
			f'<div id="{safe_wid}-camera-placeholder"'
			' style="width: 100%; max-width: 400px; height: 300px; margin: 0 auto;'
			' border: 2px dashed var(--bs-border-color, #ccc); display: flex;'
			' align-items: center; justify-content: center;'
			' color: var(--bs-secondary-color, #999);">'
			'<div style="text-align: center;">'
			f'<i class="fas fa-camera" style="font-size: 48px; margin-bottom: 12px;" aria-hidden="true"></i>'
			'<br>'
			f'<button type="button" id="{safe_wid}-start-camera" class="btn btn-primary"'
			f' aria-label="{escape(gettext("Start Camera"))}">'
			f'<i class="fas fa-camera" aria-hidden="true"></i> {escape(gettext("Start Camera"))}'
			'</button>'
			'</div>'
			'</div>'
			f'<canvas id="{safe_wid}-scan-canvas" class="hidden" aria-hidden="true"></canvas>'
			'<div style="margin-top: 16px;" aria-live="polite">'
			f'<p id="{safe_wid}-scan-result" class="alert alert-info hidden"'
			f' aria-label="{escape(gettext("Scan result"))}"></p>'
			'</div>'
			'</div>'
			'</div>'
		)

	def _get_batch_generation_section_html(self, widget_id):
		"""Generate the batch generation section HTML."""
		if not self.enable_batch_generation:
			return ""
		safe_wid = escape(widget_id)
		return (
			f'<div id="{safe_wid}-batch-tab" class="tab-content">'
			f'<div id="{safe_wid}-batch-form">'
			f'<h6>{escape(gettext("Batch QR Code Generation"))}</h6>'
			'<div class="mb-3">'
			f'<label for="{safe_wid}-batch-input">{escape(gettext("Batch Data"))}</label>'
			f'<textarea id="{safe_wid}-batch-input" class="form-control" rows="8"'
			f' placeholder="{escape(gettext("Enter one item per line..."))}"'
			f' aria-label="{escape(gettext("Batch data, one item per line"))}"></textarea>'
			f'<small class="form-text text-muted">'
			f'{escape(gettext("One QR code will be generated for each line"))}</small>'
			'</div>'
			'<div class="mb-3">'
			f'<button type="button" id="{safe_wid}-batch-generate" class="btn btn-primary"'
			f' aria-label="{escape(gettext("Generate All QR Codes"))}">'
			f'<i class="fas fa-magic" aria-hidden="true"></i> {escape(gettext("Generate All"))}'
			'</button>'
			'</div>'
			f'<div id="{safe_wid}-batch-progress" class="hidden">'
			'<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100">'
			f'<div id="{safe_wid}-batch-progress-bar" class="progress-bar" style="width: 0%"'
			' aria-live="polite"></div>'
			'</div>'
			'</div>'
			f'<div id="{safe_wid}-batch-download" class="hidden">'
			f'<button type="button" id="{safe_wid}-batch-download-btn" class="btn btn-secondary"'
			f' aria-label="{escape(gettext("Download All QR Codes"))}">'
			f'<i class="fas fa-download" aria-hidden="true"></i> {escape(gettext("Download All"))}'
			'</button>'
			'</div>'
			'</div>'
			'</div>'
		)

	def _get_history_section_html(self, widget_id):
		"""Generate the history section HTML."""
		if not self.enable_history:
			return ""
		safe_wid = escape(widget_id)
		return (
			f'<div id="{safe_wid}-history-tab" class="tab-content">'
			f'<div id="{safe_wid}-history-list">'
			f'<h6>{escape(gettext("QR Code History"))}</h6>'
			'<div class="mb-3">'
			f'<button type="button" id="{safe_wid}-clear-history"'
			f' class="btn btn-sm btn-secondary"'
			f' aria-label="{escape(gettext("Clear All History"))}">'
			f'<i class="fas fa-trash" aria-hidden="true"></i> {escape(gettext("Clear History"))}'
			'</button>'
			'</div>'
			f'<div id="{safe_wid}-history-items" role="list"'
			f' aria-label="{escape(gettext("QR code history"))}"></div>'
			'</div>'
			'</div>'
		)

	def _generate_css(self, widget_id):
		"""Generate CSS for the QR code widget using CSS custom properties for dark-mode support."""
		safe_wid = escape(widget_id)
		return f"""
<style>
#{safe_wid}-container {{
	border: 1px solid var(--bs-border-color, #ddd);
	border-radius: 8px;
	background: var(--bs-body-bg, #f8f9fa);
	overflow: hidden;
	box-shadow: 0 2px 4px rgba(0,0,0,0.1);
	width: 100%;
	max-width: 900px;
}}

#{safe_wid}-header {{
	background: var(--bs-dark-bg-subtle, #343a40);
	color: var(--bs-light, white);
	padding: 12px 16px;
	border-bottom: 1px solid var(--bs-border-color, #495057);
	display: flex;
	align-items: center;
	justify-content: space-between;
	flex-wrap: wrap;
	gap: 12px;
}}

#{safe_wid}-header h5 {{
	margin: 0;
	color: var(--bs-light, #f8f9fa);
	font-size: 16px;
	font-weight: 600;
}}

#{safe_wid}-tabs {{
	display: flex;
	gap: 4px;
	flex-wrap: wrap;
}}

#{safe_wid}-tabs .tab-btn {{
	background: var(--bs-secondary-bg, #495057);
	border: none;
	color: var(--bs-light, white);
	padding: 6px 12px;
	border-radius: 4px;
	cursor: pointer;
	font-size: 12px;
	transition: all 0.2s;
}}

#{safe_wid}-tabs .tab-btn:hover,
#{safe_wid}-tabs .tab-btn:focus {{
	background: var(--bs-secondary, #6c757d);
	outline: 2px solid var(--bs-focus-ring-color, #86b7fe);
}}

#{safe_wid}-tabs .tab-btn.active {{
	background: var(--bs-primary, #007bff);
}}

#{safe_wid}-content {{
	padding: 20px;
}}

#{safe_wid}-form-section {{
	background: var(--bs-body-bg, white);
	border: 1px solid var(--bs-border-color, #e9ecef);
	border-radius: 6px;
	padding: 16px;
	margin-bottom: 16px;
}}

#{safe_wid}-qr-display {{
	text-align: center;
	background: var(--bs-body-bg, white);
	border: 1px solid var(--bs-border-color, #e9ecef);
	border-radius: 6px;
	padding: 20px;
	min-width: 200px;
}}

#{safe_wid}-qr-canvas {{
	border: 1px solid var(--bs-border-color, #ddd);
	border-radius: 4px;
	margin-bottom: 12px;
	max-width: 100%;
}}

#{safe_wid}-customization {{
	flex: 1;
	background: var(--bs-body-bg, white);
	border: 1px solid var(--bs-border-color, #e9ecef);
	border-radius: 6px;
	padding: 16px;
}}

#{safe_wid}-scanner {{
	text-align: center;
	background: var(--bs-body-bg, white);
	border: 1px solid var(--bs-border-color, #e9ecef);
	border-radius: 6px;
	padding: 20px;
}}

#{safe_wid}-camera {{
	width: 100%;
	max-width: 400px;
	height: 300px;
	border: 1px solid var(--bs-border-color, #ddd);
	border-radius: 4px;
	background: #000;
}}

#{safe_wid}-preview {{
	display: flex;
	gap: 20px;
	align-items: flex-start;
	flex-wrap: wrap;
}}

.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.hidden {{ display: none !important; }}

@media (max-width: 768px) {{
	#{safe_wid}-header {{ flex-direction: column; align-items: stretch; }}
	#{safe_wid}-tabs {{ justify-content: center; }}
	#{safe_wid}-preview {{ flex-direction: column; }}
	#{safe_wid}-qr-display {{ min-width: auto; }}
}}
</style>"""

	def _generate_html(self, field, widget_id, **kwargs):
		"""Generate HTML structure for the QR code widget."""
		safe_wid = escape(widget_id)
		has_errors = bool(field.errors)
		invalid_attr = ' aria-invalid="true"' if has_errors else ''
		label_text = str(field.label.text) if field.label else gettext("QR Code")

		generate_tab_btn = (
			f'<button class="tab-btn active" data-tab="generate"'
			f' aria-label="{escape(gettext("Generate tab"))}">'
			f'{escape(gettext("Generate"))}</button>'
		) if self.enable_generation else ""

		scan_tab_btn = (
			f'<button class="tab-btn" data-tab="scan"'
			f' aria-label="{escape(gettext("Scan tab"))}">'
			f'{escape(gettext("Scan"))}</button>'
		) if self.enable_scanning else ""

		batch_tab_btn = (
			f'<button class="tab-btn" data-tab="batch"'
			f' aria-label="{escape(gettext("Batch tab"))}">'
			f'{escape(gettext("Batch"))}</button>'
		) if self.enable_batch_generation else ""

		history_tab_btn = (
			f'<button class="tab-btn" data-tab="history"'
			f' aria-label="{escape(gettext("History tab"))}">'
			f'{escape(gettext("History"))}</button>'
		) if self.enable_history else ""

		html = (
			f'<div id="{safe_wid}-container" class="qr-code-widget"'
			f' role="group" aria-label="{escape(label_text)}">'
			f'<div id="{safe_wid}-header">'
			f'<h5><i class="fas fa-qrcode" aria-hidden="true"></i>'
			f' {escape(gettext("QR Code Generator &amp; Scanner"))}</h5>'
			f'<div id="{safe_wid}-tabs" role="tablist">'
			+ generate_tab_btn + scan_tab_btn + batch_tab_btn + history_tab_btn +
			'</div>'
			'</div>'
			f'<div id="{safe_wid}-content">'
			+ self._get_generation_section_html(widget_id)
			+ self._get_scanning_section_html(widget_id)
			+ self._get_batch_generation_section_html(widget_id)
			+ self._get_history_section_html(widget_id) +
			'</div>'
			# Hidden input — properly escaped with real field values
			f'<input type="hidden" name="{escape(field.name)}"'
			f' id="{safe_wid}" value="{escape(field.data or "")}"'
			f' aria-label="{escape(label_text)}"{invalid_attr} />'
		)

		# Server-side WTForms errors
		if has_errors:
			html += (
				f'<div class="invalid-feedback d-block" id="{safe_wid}_error" role="alert">'
			)
			for error in field.errors:
				html += f'<span>{escape(str(error))}</span>'
			html += '</div>'

		# Help text
		if self.description:
			html += (
				f'<small class="form-text text-muted" id="{safe_wid}_help">'
				f'{escape(self.description)}</small>'
			)

		html += '</div>'
		return html

	def _generate_javascript(self, widget_id, initial_value):
		"""Generate JavaScript for the QR code widget."""
		safe_initial = _js_json(initial_value)
		wid_js = _js_json(widget_id)
		qrcode_url_js = _js_json(QRCODE_CDN_URL)
		jsqr_url_js = _js_json(JSQR_CDN_URL)
		max_history_js = _js_json(self.max_history_items)
		default_size_js = _js_json(self.default_size)
		clear_confirm_js = _js_json(gettext("Clear all QR code history?"))
		no_qrlib_js = _js_json(gettext("QR Code library not loaded yet"))
		no_jsqr_js = _js_json(gettext("QR scanning library not loaded yet"))
		no_camera_js = _js_json(gettext("Unable to access camera"))
		no_content_js = _js_json(gettext("Please enter content for the QR code"))
		gen_error_js = _js_json(gettext("Error generating QR code"))
		no_image_qr_js = _js_json(gettext("No QR code found in the image"))
		no_history_yet_js = _js_json(gettext("No QR codes in history yet"))
		history_key_js = _js_json(f"{widget_id}-history")

		return f"""
<script>
(function() {{
	var WID = {wid_js};
	var qrCodeLib = null;
	var jsQRLib = null;
	var currentStream = null;
	var scanInterval = null;
	var qrHistory = JSON.parse(localStorage.getItem({history_key_js}) || '[]');

	function $$(suffix) {{ return document.getElementById(WID + suffix); }}

	function loadQRLibraries() {{
		if (!window.QRCode) {{
			var s = document.createElement('script');
			s.src = {qrcode_url_js};
			s.onload = function() {{ qrCodeLib = window.QRCode; }};
			document.head.appendChild(s);
		}} else {{
			qrCodeLib = window.QRCode;
		}}
		if (!window.jsQR) {{
			var s2 = document.createElement('script');
			s2.src = {jsqr_url_js};
			s2.onload = function() {{ jsQRLib = window.jsQR; }};
			document.head.appendChild(s2);
		}} else {{
			jsQRLib = window.jsQR;
		}}
	}}

	function initQRWidget() {{
		loadQRLibraries();
		setupTabs();
		setupGeneration();
		setupScanning();
		setupBatch();
		setupHistory();
		loadHistoryDisplay();

		var initial = {safe_initial};
		if (initial) {{
			var contentInput = $$('-content-input');
			if (contentInput) {{
				contentInput.value = initial;
				generateQRCode();
			}}
		}}
	}}

	function setupTabs() {{
		var tabContainer = $$(''+ '-tabs') || $$(WID + '-tabs');
		if (!tabContainer) {{
			tabContainer = document.getElementById(WID + '-tabs');
		}}
		if (!tabContainer) return;
		var tabs = tabContainer.querySelectorAll('.tab-btn');
		tabs.forEach(function(tab) {{
			tab.addEventListener('click', function() {{
				var tabName = this.dataset.tab;
				tabs.forEach(function(t) {{
					t.classList.remove('active');
					t.setAttribute('aria-selected', 'false');
				}});
				this.classList.add('active');
				this.setAttribute('aria-selected', 'true');
				var contentEl = document.getElementById(WID + '-content');
				if (contentEl) {{
					contentEl.querySelectorAll('.tab-content').forEach(function(c) {{
						c.classList.remove('active');
					}});
				}}
				var target = document.getElementById(WID + '-' + tabName + '-tab');
				if (target) target.classList.add('active');
			}});
		}});
	}}

	function setupGeneration() {{
		var generateBtn = $$('-generate-btn');
		var contentInput = $$('-content-input');
		var hiddenField = document.getElementById(WID);

		if (generateBtn) generateBtn.addEventListener('click', generateQRCode);
		if (contentInput && hiddenField) {{
			contentInput.addEventListener('input', function() {{
				hiddenField.value = this.value;
			}});
		}}

		var sizeSlider = $$('-size-slider');
		if (sizeSlider) {{
			sizeSlider.addEventListener('input', function() {{
				var display = $$('-size-display');
				if (display) display.textContent = this.value + 'px';
				var canvas = $$('-qr-canvas');
				if (canvas && !canvas.classList.contains('hidden')) generateQRCode();
			}});
		}}

		var errorCorrection = $$('-error-correction');
		if (errorCorrection) {{
			errorCorrection.addEventListener('change', function() {{
				var canvas = $$('-qr-canvas');
				if (canvas && !canvas.classList.contains('hidden')) generateQRCode();
			}});
		}}

		var fgColor = $$('-fg-color');
		var bgColor = $$('-bg-color');
		if (fgColor) fgColor.addEventListener('change', function() {{
			var canvas = $$('-qr-canvas');
			if (canvas && !canvas.classList.contains('hidden')) generateQRCode();
		}});
		if (bgColor) bgColor.addEventListener('change', function() {{
			var canvas = $$('-qr-canvas');
			if (canvas && !canvas.classList.contains('hidden')) generateQRCode();
		}});

		var downloadPng = $$('-download-png');
		var downloadSvg = $$('-download-svg');
		if (downloadPng) downloadPng.addEventListener('click', function() {{ downloadQRCode('png'); }});
		if (downloadSvg) downloadSvg.addEventListener('click', function() {{ downloadQRCode('svg'); }});
	}}

	function setupScanning() {{
		var startCameraBtn = $$('-start-camera');
		if (startCameraBtn) startCameraBtn.addEventListener('click', startCamera);
	}}

	function setupBatch() {{
		var batchBtn = $$('-batch-generate');
		if (batchBtn) batchBtn.addEventListener('click', generateBatchQRCodes);
		var batchDl = $$('-batch-download-btn');
		if (batchDl) batchDl.addEventListener('click', downloadBatchZip);
	}}

	function setupHistory() {{
		var clearBtn = $$('-clear-history');
		if (clearBtn) {{
			clearBtn.addEventListener('click', function() {{
				if (confirm({clear_confirm_js})) {{
					qrHistory = [];
					localStorage.removeItem({history_key_js});
					loadHistoryDisplay();
				}}
			}});
		}}
	}}

	function generateQRCode() {{
		if (!qrCodeLib) {{ console.warn({no_qrlib_js}); return; }}
		var contentInput = $$('-content-input');
		if (!contentInput) return;
		var content = contentInput.value.trim();
		if (!content) {{ alert({no_content_js}); return; }}

		var canvas = $$('-qr-canvas');
		var placeholder = $$('-qr-placeholder');
		var sizeSlider = $$('-size-slider');
		var size = sizeSlider ? parseInt(sizeSlider.value) : {default_size_js};
		var ecEl = $$('-error-correction');
		var errorCorrectionLevel = ecEl ? ecEl.value : 'M';
		var fgColorEl = $$('-fg-color');
		var bgColorEl = $$('-bg-color');
		var fgColor = fgColorEl ? fgColorEl.value : '#000000';
		var bgColor = bgColorEl ? bgColorEl.value : '#ffffff';

		if (!canvas) return;
		canvas.width = size;
		canvas.height = size;

		try {{
			qrCodeLib.toCanvas(canvas, content, {{
				width: size,
				height: size,
				errorCorrectionLevel: errorCorrectionLevel,
				color: {{ dark: fgColor, light: bgColor }},
				margin: 2,
			}}, function(err) {{
				if (err) {{ console.error(err); alert({gen_error_js}); return; }}
				canvas.classList.remove('hidden');
				if (placeholder) placeholder.classList.add('hidden');
				var dlPng = $$('-download-png');
				var dlSvg = $$('-download-svg');
				if (dlPng) dlPng.disabled = false;
				if (dlSvg) dlSvg.disabled = false;
				addToHistory(content, new Date().toISOString());
			}});
		}} catch(e) {{ console.error(e); alert({gen_error_js}); }}
	}}

	function downloadQRCode(format) {{
		var canvas = $$('-qr-canvas');
		var contentInput = $$('-content-input');
		if (!canvas || !contentInput) return;
		var content = contentInput.value.trim();

		if (format === 'png') {{
			var a = document.createElement('a');
			a.download = 'qrcode-' + Date.now() + '.png';
			a.href = canvas.toDataURL('image/png');
			document.body.appendChild(a); a.click(); document.body.removeChild(a);
		}} else if (format === 'svg' && qrCodeLib) {{
			qrCodeLib.toString(content, {{ type: 'svg', width: 256, height: 256 }}, function(err, svg) {{
				if (err) return;
				var blob = new Blob([svg], {{ type: 'image/svg+xml' }});
				var url = URL.createObjectURL(blob);
				var a = document.createElement('a');
				a.download = 'qrcode-' + Date.now() + '.svg';
				a.href = url;
				document.body.appendChild(a); a.click(); document.body.removeChild(a);
				URL.revokeObjectURL(url);
			}});
		}}
	}}

	function startCamera() {{
		if (!jsQRLib) {{ alert({no_jsqr_js}); return; }}
		var video = $$('-camera');
		var placeholder = $$('-camera-placeholder');
		var startBtn = $$('-start-camera');

		navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: 'environment' }} }})
			.then(function(stream) {{
				currentStream = stream;
				video.srcObject = stream;
				video.play();
				video.classList.remove('hidden');
				if (placeholder) placeholder.classList.add('hidden');
				if (startBtn) startBtn.classList.add('hidden');
				scanInterval = setInterval(scanFromVideo, 100);
			}})
			.catch(function(err) {{
				console.error(err);
				alert({no_camera_js});
			}});
	}}

	function stopCamera() {{
		if (currentStream) {{ currentStream.getTracks().forEach(function(t) {{ t.stop(); }}); currentStream = null; }}
		if (scanInterval) {{ clearInterval(scanInterval); scanInterval = null; }}
		var video = $$('-camera');
		var placeholder = $$('-camera-placeholder');
		var startBtn = $$('-start-camera');
		if (video) video.classList.add('hidden');
		if (placeholder) placeholder.classList.remove('hidden');
		if (startBtn) startBtn.classList.remove('hidden');
	}}

	function scanFromVideo() {{
		var video = $$('-camera');
		if (!video) return;
		var canvas = document.createElement('canvas');
		canvas.width = video.videoWidth;
		canvas.height = video.videoHeight;
		canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
		var imageData = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
		var code = jsQRLib(imageData.data, imageData.width, imageData.height);
		if (code) {{ displayScanResult(code.data); stopCamera(); }}
	}}

	function displayScanResult(content) {{
		var resultEl = $$('-scan-result');
		if (resultEl) {{
			resultEl.textContent = content;
			resultEl.classList.remove('hidden');
		}}
		var hiddenField = document.getElementById(WID);
		if (hiddenField) hiddenField.value = content;
		addToHistory(content, new Date().toISOString(), 'scanned');
	}}

	function generateBatchQRCodes() {{
		var batchInput = $$('-batch-input');
		if (!batchInput) return;
		var items = batchInput.value.split('\n').filter(function(i) {{ return i.trim(); }});
		if (!items.length) {{ alert('Please enter batch data'); return; }}

		var progressBar = $$('-batch-progress-bar');
		var progressContainer = $$('-batch-progress');
		if (progressContainer) progressContainer.classList.remove('hidden');

		var completed = 0;
		var batchData = [];
		items.forEach(function(item, index) {{
			setTimeout(function() {{
				if (!qrCodeLib) return;
				qrCodeLib.toDataURL(item.trim(), {{ width: 128, height: 128, errorCorrectionLevel: 'M' }}, function(err, url) {{
					if (!err) batchData.push({{ content: item.trim(), dataURL: url, index: index }});
					completed++;
					var pct = (completed / items.length) * 100;
					if (progressBar) {{
						progressBar.style.width = pct + '%';
						progressBar.setAttribute('aria-valuenow', Math.round(pct));
					}}
					if (completed === items.length) {{
						var dlBtn = $$('-batch-download');
						if (dlBtn) dlBtn.classList.remove('hidden');
						window[WID + '_batchData'] = batchData;
					}}
				}});
			}}, index * 100);
		}});
	}}

	function downloadBatchZip() {{
		alert('Batch ZIP download requires JSZip library integration');
	}}

	function addToHistory(content, timestamp, type) {{
		type = type || 'generated';
		qrHistory.unshift({{ content: content, timestamp: timestamp, type: type, id: Date.now() + Math.random() }});
		if (qrHistory.length > {max_history_js}) qrHistory = qrHistory.slice(0, {max_history_js});
		localStorage.setItem({history_key_js}, JSON.stringify(qrHistory));
		loadHistoryDisplay();
	}}

	function loadHistoryDisplay() {{
		var historyList = $$('-history-items');
		if (!historyList) return;
		if (!qrHistory.length) {{
			historyList.innerHTML = '<div style="padding: 40px; text-align: center; color: var(--bs-secondary-color, #999);">'
				+ '<i class="fas fa-history" style="font-size: 48px; margin-bottom: 12px;" aria-hidden="true"></i>'
				+ '<p>' + {no_history_yet_js} + '</p></div>';
			return;
		}}
		historyList.innerHTML = qrHistory.map(function(item) {{
			var safeContent = item.content.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
			var safeId = String(item.id).replace(/[^0-9.]/g, '');
			return '<div class="qr-history-item d-flex align-items-center justify-content-between py-2 border-bottom" role="listitem">'
				+ '<div class="qr-history-content flex-grow-1 me-2">'
				+ '<div class="qr-history-text text-truncate" title="' + safeContent + '">' + safeContent + '</div>'
				+ '<div class="qr-history-meta small text-muted">' + new Date(item.timestamp).toLocaleString() + ' • ' + item.type + '</div>'
				+ '</div>'
				+ '<div class="qr-history-actions d-flex gap-1">'
				+ '<button class="btn btn-sm btn-outline-primary" onclick="(function(){{var h=JSON.parse(localStorage.getItem(' + {history_key_js} + ') || \\'[]\\');var i=h.find(function(x){{return String(x.id)==\\''+safeId+'\\'}});if(i){{var c=document.getElementById(' + wid_js + ');if(c)c.value=i.content;var t=document.getElementById(' + wid_js + '+\\'-content-input\\');if(t)t.value=i.content;}}}})()" aria-label="Reuse this QR code"><i class="fas fa-redo" aria-hidden="true"></i></button>'
				+ '</div>'
				+ '</div>';
		}}).join('');
	}}

	if (document.readyState === 'loading') {{
		document.addEventListener('DOMContentLoaded', initQRWidget);
	}} else {{
		initQRWidget();
	}}
}})();
</script>"""
