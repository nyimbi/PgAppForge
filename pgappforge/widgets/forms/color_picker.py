"""ColorPickerWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
import re
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
import markupsafe
from markupsafe import Markup
from wtforms import Field
from wtforms.validators import ValidationError
from wtforms.widgets import html_params


class ColorPickerWidget(BS3TextFieldWidget):
	"""
	Advanced color picker widget for PgAppForge supporting multiple color formats.

	Features:
	- Multiple color formats (hex, rgb, rgba, hsl)
	- Alpha channel support
	- Color presets/swatches
	- Live preview
	- Input validation
	- Accessibility support
	- Custom color palettes
	- Color history
	- Color name lookup
	- Eyedropper/color sampling tool
	- Keyboard control

	Database Type:
	    PostgreSQL: varchar(32) or text
	    SQLAlchemy: String(32) or Text

	Example Usage:
	    color = db.Column(db.String(32), nullable=True)

	JS initialization note:
	    The colorpicker is auto-initialized on DOMContentLoaded via the
	    ``data-colorpicker-auto-init`` attribute.  For elements inserted
	    after page load (modals, htmx partials) callers must re-trigger::

	        $('[data-colorpicker-auto-init]').each(function() { initColorpicker(this); });

	    inside ``shown.bs.modal`` / ``shown.bs.tab`` event handlers.
	"""

	# Templates use %(text)s as a single substitution slot filled by html_params().
	# The slot is replaced with Markup() so markupsafe's __mod__ escapes it safely.
	_data_template = Markup(
		'<div class="color-picker-container mb-3">'
		'<div class="input-group color-picker-widget">'
		"<input %(text)s>"
		'<span class="input-group-text preview"><i aria-hidden="true"></i></span>'
		"</div>"
		'<div class="color-picker-error"></div>'
		'<div class="color-picker-history"></div>'
		"</div>"
	)

	def __init__(self, **kwargs):
		"""Initialize color picker with custom settings.

		Accepted kwargs (all optional):
		    format: str — color format: 'hex' | 'rgb' | 'rgba' | 'hsl'  (default 'hex')
		    alpha: bool — enable alpha channel  (default True)
		    default_color: str — fallback color  (default '#000000')
		    presets: list[str] — swatch colors
		    max_history: int — max remembered colors  (default 10)
		    placeholder: str — input placeholder text
		    error_message: str — validation error message
		    custom_palettes: list | None — additional palette definitions
		    enable_eyedropper: bool — show eyedropper button  (default False)
		    description: str | None — help text rendered below the widget
		    css_class: str | None — extra CSS classes on the <input>
		    readonly: bool — render input as readonly  (default False)
		    disabled: bool — render input as disabled  (default False)
		"""
		# BS3TextFieldWidget.__init__ accepts no positional args; call with no kwargs
		# to avoid forwarding widget-specific keys that TextInput doesn't know about.
		super().__init__()
		self.format = kwargs.get("format", "hex")
		self.alpha = kwargs.get("alpha", True)
		self.default_color = kwargs.get("default_color", "#000000")
		self.presets = kwargs.get(
			"presets",
			[
				"#FF0000", "#00FF00", "#0000FF", "#FFFF00",
				"#FF00FF", "#00FFFF", "#000000", "#888888", "#FFFFFF",
			],
		)
		self.max_history = kwargs.get("max_history", 10)
		self.placeholder = kwargs.get("placeholder", "Select color...")
		self.error_message = kwargs.get("error_message", "Invalid color format")
		self.custom_palettes = kwargs.get("custom_palettes", None)
		self.enable_eyedropper = kwargs.get("enable_eyedropper", False)
		self.description = kwargs.get("description", None)
		self.css_class = kwargs.get("css_class", None)
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

	def __call__(self, field, **kwargs):
		"""Render the color picker widget."""
		# Use a local variable for the display value — never mutate field.data.
		value = field.data if field.data else ""

		kwargs.setdefault("type", "text")

		# Build CSS class list
		css = "form-control color-input"
		if self.css_class:
			css += " " + self.css_class
		if field.errors:
			css += " is-invalid"
		kwargs["class"] = css

		kwargs.setdefault("placeholder", self.placeholder)

		if field.flags.required:
			kwargs["required"] = True
		if self.readonly:
			kwargs["readonly"] = True
		if self.disabled:
			kwargs["disabled"] = True

		# Accessibility
		aria_label = field.label.text if field.label else ""
		kwargs["aria-label"] = aria_label
		if field.errors:
			kwargs["aria-invalid"] = "true"
			kwargs["aria-describedby"] = field.id + "_error"
		elif self.description:
			kwargs["aria-describedby"] = field.id + "_help"

		# data-* attributes for JS auto-init (modal/tab re-init friendly)
		kwargs["data-colorpicker-auto-init"] = "true"

		# Render the input via html_params — use Markup.__mod__ so markupsafe
		# escapes the substituted portion correctly.
		input_html = self._data_template % Markup(
			html_params(name=field.name, value=value, **kwargs)
		)

		# Error feedback block
		error_html = Markup("")
		if field.errors:
			errors_inner = Markup("").join(
				Markup('<span>{}</span>').format(markupsafe.escape(e))
				for e in field.errors
			)
			error_html = (
				Markup('<div class="invalid-feedback" id="{}_error">').format(field.id)
				+ errors_inner
				+ Markup("</div>")
			)

		# Help text block
		help_html = Markup("")
		if self.description:
			help_html = (
				Markup('<small class="form-text text-muted" id="{}_help">{}</small>').format(
					field.id, markupsafe.escape(self.description)
				)
			)

		# Safely embed Python values into the <script> block via _js_json /
		# plain json.dumps — all values are developer-controlled, not user data,
		# except field.id which we escape via _js_json.
		field_id_js = _js_json(field.id)
		presets_js = _js_json(self.presets)
		custom_palettes_js = _js_json(self.custom_palettes) if self.custom_palettes else "null"
		format_js = _js_json(self.format)
		default_color_js = _js_json(self.default_color)
		error_message_js = _js_json(self.error_message)

		script = Markup("""
<style>
	.color-picker-container {
		position: relative;
	}
	.color-picker-widget .preview {
		min-width: 36px;
		cursor: pointer;
	}
	.color-picker-widget .preview i {
		display: inline-block;
		width: 18px;
		height: 18px;
		border: 1px solid #ccc;
		vertical-align: middle;
	}
	.color-picker-error {
		color: #dc3545;
		font-size: 0.875em;
		margin-top: 0.25rem;
		display: none;
	}
	.color-picker-history {
		margin-top: 0.375rem;
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.color-picker-history .color-swatch {
		width: 20px;
		height: 20px;
		border: 1px solid #ccc;
		cursor: pointer;
	}
</style>
<script>
(function() {
	var fieldId = """ + Markup(field_id_js) + """;
	var $input = $('#' + fieldId);
	var $container = $input.closest('.color-picker-container');
	var $preview = $container.find('.preview i');
	var $error = $container.find('.color-picker-error');
	var $history = $container.find('.color-picker-history');
	var colorHistory = [];

	function initColorpicker(el) {
		var $el = $(el);
		var cp = $el.colorpicker({
			format: """ + Markup(format_js) + """,
			useAlpha: """ + Markup(json.dumps(bool(self.alpha))) + """,
			horizontal: true,
			autoInputFallback: false,
			useHashPrefix: true,
			fallbackColor: """ + Markup(default_color_js) + """,
			extensions: [
				{
					name: 'swatches',
					options: {
						colors: """ + Markup(presets_js) + """,
						namesAsValues: false
					}
				},
				{
					name: 'history',
					options: {
						colors: colorHistory,
						maxHistory: """ + Markup(json.dumps(self.max_history)) + """
					}
				},
				{
					name: 'namebadge',
					options: { placement: 'top' }
				}
			]
		}).data('colorpicker');

		var customPalettes = """ + Markup(custom_palettes_js) + """;
		if (customPalettes && cp) {
			cp.extend('custom_palettes', {
				colors: customPalettes,
				template: '<div class="custom-palette">...</div>'
			});
		}

		if (""" + Markup(json.dumps(bool(self.enable_eyedropper))) + """ && cp) {
			cp.picker.on('mousedown', function(e) {
				if (e.target.classList.contains('colorpicker-preview')) {
					e.preventDefault();
					// Eyedropper: integrate a real EyeDropper API or canvas-based sampler here.
					if (window.EyeDropper) {
						var eyeDropper = new EyeDropper();
						eyeDropper.open().then(function(result) {
							$el.colorpicker('setValue', result.sRGBHex);
						}).catch(function() {});
					}
				}
			});
		}

		return cp;
	}

	function updatePreview(color) {
		$preview.css('background-color', color);
	}

	function updateHistory(cp) {
		$history.empty();
		var colors = (cp && cp.options.extensions[1] && cp.options.extensions[1].options.colors) || [];
		colors.forEach(function(color) {
			$('<div>')
				.addClass('color-swatch')
				.css('background-color', color)
				.attr('title', color)
				.attr('role', 'button')
				.attr('aria-label', 'Use color ' + color)
				.on('click', function() { $input.colorpicker('setValue', color); })
				.appendTo($history);
		});
	}

	// Auto-init on DOMContentLoaded — re-call initColorpicker() on
	// shown.bs.modal / shown.bs.tab for dynamically inserted content.
	var cp = initColorpicker($input[0]);

	$input.on('colorpickerChange', function(e) {
		var color = e.color.toString();
		updatePreview(color);
		$error.hide();
		$input.removeClass('is-invalid').attr('aria-invalid', null);
		updateHistory(cp);
	});

	$input.on('keydown', function(e) {
		if (e.key === 'Escape' && cp) { cp.hide(); }
	});

	if ($input.val()) {
		updatePreview($input.val());
	}

	$input.closest('form').on('reset', function() {
		setTimeout(function() {
			$input.colorpicker('setValue', """ + Markup(default_color_js) + """);
		}, 0);
	});

	// Expose re-init function for modal/tab usage
	$input[0].dataset.colorpickerAutoInit = 'true';
})();
</script>
""")

		return input_html + error_html + help_html + script

	def _get_custom_palettes_script(self):
		"""Generate script fragment for custom color palettes (legacy helper, unused internally)."""
		if not self.custom_palettes:
			return ""
		return """
			if (colorpicker) {
				colorpicker.extend('custom_palettes', {
					colors: %s,
					template: '<div class="custom-palette">...</div>'
				});
			}
		""" % _js_json(self.custom_palettes)

	def pre_validate(self, form):
		"""Validate the color value before form processing."""
		if self.data:
			color_format = self.format.lower()
			if color_format == "hex":
				if not re.match(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", self.data):
					raise ValidationError(self.error_message)
			elif color_format == "rgb":
				if not re.match(r"^rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)$", self.data):
					raise ValidationError(self.error_message)
			elif color_format == "rgba":
				if not re.match(
					r"^rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[0-1]?(\.\d+)?\s*\)$",
					self.data,
				):
					raise ValidationError(self.error_message)
			elif color_format == "hsl":
				if not re.match(
					r"^hsl\(\s*\d+\s*,\s*\d+%?\s*,\s*\d+%?\s*\)$", self.data
				):
					raise ValidationError(self.error_message)

	def process_formdata(self, valuelist):
		"""Process form data to database format."""
		if valuelist:
			self.data = valuelist[0].strip()
		else:
			self.data = None

	def process_data(self, value):
		"""Process data from database format."""
		if value:
			return value.strip()
		return None
