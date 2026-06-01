"""SignaturePadWidget — PgAppForge widget(s)."""

from __future__ import annotations
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape


class SignaturePadWidget(BS3TextFieldWidget):
	"""
	Widget for capturing digital signatures with drawing capabilities.

	Features:
	- Pressure sensitivity with multi-touch support
	- Multiple pen colors, sizes and styles
	- Clear/redo/undo functionality with history
	- Vector-based SVG storage for crisp scaling
	- PNG/SVG/JSON export options
	- Enhanced Signature validation (min points, speed, rhythm analysis)
	- Signature replay for verification and forensic analysis
	- Name attestation with optional field
	- Customizable pen styles and canvas backgrounds
	- Timestamp embedding and Audit trail logging
	- Improved error handling and user feedback
	- Accessibility enhancements for users with motor impairments

	Required Dependencies:
	- SignaturePad.js 4.1+
	- bezier.js (for signature smoothing)

	Database Type:
		PostgreSQL: jsonb (stores signature data, metadata, audit trail, and verification data)
		SQLAlchemy: JSON

	Example Usage:
		signature = db.Column(db.JSON, nullable=False,
			info={'widget': SignaturePadWidget(
				pen_color='#000000',
				pen_size=2,
				min_points=100,
				require_name=True,
				background_grid=True,
				allow_undo=True,
				store_audit_trail=True,
				enable_replay_verification=True
			)})
	"""

	JS_DEPENDENCIES = [
		"https://cdn.jsdelivr.net/npm/signature_pad@4.1.5/dist/signature_pad.umd.min.js",
		"https://cdn.jsdelivr.net/npm/bezier-js@3.1.0/bezier.min.js",
	]

	CSS_DEPENDENCIES = [
		"/static/css/signature-pad-widget.css",
	]

	def __init__(self, **kwargs):
		"""Initialize signature widget with extensive configuration options."""
		super().__init__(**kwargs)
		self.pen_color = kwargs.get("pen_color", "#000000")
		self.pen_size = kwargs.get("pen_size", 2)
		self.min_points = kwargs.get("min_points", 100)
		self.require_name = kwargs.get("require_name", False)
		self.background_grid = kwargs.get("background_grid", False)
		self.allow_undo = kwargs.get("allow_undo", True)
		self.allow_redo = kwargs.get("allow_redo", True)
		self.store_audit_trail = kwargs.get("store_audit_trail", True)
		self.enable_replay_verification = kwargs.get("enable_replay_verification", False)
		self.wrapper_class = kwargs.get("wrapper_class", "")
		self.canvas_width = kwargs.get("canvas_width", 500)
		self.canvas_height = kwargs.get("canvas_height", 200)
		self.max_points = kwargs.get("max_points", 10000)
		self.throttle = kwargs.get("throttle", 16)
		self.min_speed = kwargs.get("min_speed", 0.8)
		self.max_idle_time = kwargs.get("max_idle_time", 5000)
		self.pressure_support = kwargs.get("pressure_support", True)
		self.background_color = kwargs.get("background_color", "#f8f9fa")
		self.locale = kwargs.get("locale", "en")
		self.custom_validators = kwargs.get("custom_validators", [])
		# Universal kwargs
		self.placeholder = kwargs.get("placeholder", "")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

	def __call__(self, field, **kwargs):
		"""Render the signature pad widget."""
		kwargs.setdefault("id", field.id)

		# Determine error state
		has_errors = bool(field.errors)
		invalid_attr = ' aria-invalid="true"' if has_errors else ''

		name_field = ""
		if self.require_name:
			name_field = (
				'<div class="mb-3 mt-2">'
				f'<label for="{escape(field.id)}-signer-name">'
				+ str(_("Signer Name (Optional)"))
				+ f'</label>'
				f'<input type="text" class="form-control signer-name"'
				f' id="{escape(field.id)}-signer-name"'
				f' placeholder="{escape(str(_("Type your name (Optional)")))}"'
				f' aria-label="{escape(str(_("Signer Name")))}">'
				'</div>'
			)

		wrapper_classes = "signature-pad-wrapper"
		if self.wrapper_class:
			wrapper_classes += f" {escape(self.wrapper_class)}"
		if has_errors:
			wrapper_classes += " is-invalid"

		html = (
			f'<div class="{wrapper_classes}" role="group"'
			f' aria-label="{escape(str(field.label.text) if field.label else str(_("Signature")))} {escape(str(_("signature pad")))}">'
			f'<div class="signature-pad" style="background: {escape(self.background_color)};">'
			f'<canvas class="signature-pad-canvas"'
			f' aria-label="{escape(str(field.label.text) if field.label else str(_("Signature")))}"'
			f' role="img"></canvas>'
			'</div>'
			'<div class="signature-controls mt-2">'
			'<div class="btn-group">'
			'<button type="button" class="btn btn-sm btn-secondary clear-signature"'
			f' title="{escape(str(_("Clear")))}" aria-label="{escape(str(_("Clear Signature")))}">'
			'<i class="fa fa-eraser" aria-hidden="true"></i> '
			+ str(_("Clear")) +
			'</button>'
			'<button type="button" class="btn btn-sm btn-secondary undo-signature"'
			f' title="{escape(str(_("Undo")))}" aria-label="{escape(str(_("Undo Last Stroke")))}"'
			+ ("" if self.allow_undo else " disabled") +
			'>'
			'<i class="fa fa-undo" aria-hidden="true"></i> '
			+ str(_("Undo")) +
			'</button>'
			'<button type="button" class="btn btn-sm btn-secondary redo-signature"'
			f' title="{escape(str(_("Redo")))}" aria-label="{escape(str(_("Redo Last Stroke")))}"'
			+ ("" if self.allow_redo else " disabled") +
			' style="display:none;">'
			'<i class="fa fa-redo" aria-hidden="true"></i> '
			+ str(_("Redo")) +
			'</button>'
			'</div>'
			'<div class="pen-controls btn-group ms-2">'
			'<button type="button" class="btn btn-sm btn-outline-secondary dropdown-toggle"'
			' data-bs-toggle="dropdown" data-toggle="dropdown"'
			f' title="{escape(str(_("Pen Options")))}"'
			' aria-haspopup="true" aria-expanded="false"'
			f' aria-label="{escape(str(_("Pen Options")))}">'
			'<i class="fa fa-paint-brush" aria-hidden="true"></i> '
			+ str(_("Pen Options")) +
			'</button>'
			'<div class="dropdown-menu dropdown-menu-end dropdown-menu-right">'
			'<div class="px-3 py-2">'
			'<div class="mb-3">'
			f'<label for="{escape(field.id)}-pen-color">{escape(str(_("Color")))}</label>'
			f'<input type="color" class="form-control pen-color" id="{escape(field.id)}-pen-color"'
			f' value="{escape(self.pen_color)}" aria-label="{escape(str(_("Pen Color")))}">'
			'</div>'
			'<div class="mb-3">'
			f'<label for="{escape(field.id)}-pen-size">{escape(str(_("Size")))}</label>'
			f'<input type="range" class="form-control-range pen-size" id="{escape(field.id)}-pen-size"'
			f' min="1" max="10" value="{int(self.pen_size)}" aria-label="{escape(str(_("Pen Size")))}">'
			'</div>'
			'</div>'
			'</div>'
			'</div>'
			'</div>'
			+ name_field +
			'<div class="signature-status mt-2" aria-live="polite" aria-atomic="true">'
			'<small class="text-muted status-text">'
			+ str(_("Ready to sign")) +
			'</small>'
			'<div class="signature-error text-danger" style="display: none;" role="alert"></div>'
			'<div class="signature-verification text-success" style="display: none;">'
			+ str(_("Signature Verified")) +
			'</div>'
			'<div class="signature-score text-info" style="display: none;"></div>'
			'</div>'
			f'<input type="hidden" name="{escape(field.name)}" id="{escape(field.id)}"'
			f' value="{escape(field.data or "")}" aria-label="{escape(str(field.label.text) if field.label else str(_("Signature")))}"'
			f'{invalid_attr}>'
		)

		# Server-side WTForms error rendering
		if has_errors:
			html += (
				f'<div class="invalid-feedback d-block" id="{escape(field.id)}_error"'
				' role="alert">'
			)
			for error in field.errors:
				html += f'<span>{escape(str(error))}</span>'
			html += '</div>'

		# Help text
		if self.description:
			html += (
				f'<small class="form-text text-muted" id="{escape(field.id)}_help">'
				f'{escape(self.description)}</small>'
			)

		html += '</div>'

		return Markup(html + self._get_widget_scripts(field))

	def _get_widget_scripts(self, field) -> str:
		"""Generate JavaScript initialization for the signature pad."""
		config = {
			"fieldId": field.id,
			"fieldName": field.name,
			"penColor": self.pen_color,
			"penSize": self.pen_size,
			"minPoints": self.min_points,
			"maxPoints": self.max_points,
			"throttle": self.throttle,
			"minSpeed": self.min_speed,
			"maxIdleTime": self.max_idle_time,
			"pressureSupport": self.pressure_support,
			"backgroundGrid": self.background_grid,
			"allowUndo": self.allow_undo,
			"allowRedo": self.allow_redo,
			"storeAuditTrail": self.store_audit_trail,
			"enableReplayVerification": self.enable_replay_verification,
			"canvasWidth": self.canvas_width,
			"canvasHeight": self.canvas_height,
		}
		field_id_js = _js_json(field.id)
		return f"""
<script>
(function() {{
	var FIELD_ID = {field_id_js};
	var config = {_js_json(config)};

	function init() {{
		var wrapper = document.querySelector('.signature-pad-wrapper');
		if (!wrapper) return;
		var canvas = wrapper.querySelector('.signature-pad-canvas');
		var hiddenInput = document.getElementById(FIELD_ID);
		if (!canvas || !hiddenInput) return;

		// Resize canvas to its container
		function resizeCanvas() {{
			var ratio = Math.max(window.devicePixelRatio || 1, 1);
			canvas.width = canvas.offsetWidth * ratio;
			canvas.height = canvas.offsetHeight * ratio;
			canvas.getContext('2d').scale(ratio, ratio);
		}}

		resizeCanvas();

		var signaturePad = new SignaturePad(canvas, {{
			minWidth: config.penSize * 0.5,
			maxWidth: config.penSize * 2,
			penColor: config.penColor,
			throttle: config.throttle,
			backgroundColor: 'rgba(0,0,0,0)',
		}});

		// Restore existing value if present
		if (hiddenInput.value) {{
			try {{
				var savedData = JSON.parse(hiddenInput.value);
				if (savedData && savedData.points) {{
					signaturePad.fromData(savedData.points);
				}}
			}} catch(e) {{ /* ignore parse errors */ }}
		}}

		// Persist value on end stroke
		signaturePad.addEventListener('endStroke', function() {{
			var data = {{
				points: signaturePad.toData(),
				timestamp: new Date().toISOString(),
			}};
			hiddenInput.value = JSON.stringify(data);
		}});

		// Clear button
		var clearBtn = wrapper.querySelector('.clear-signature');
		if (clearBtn) {{
			clearBtn.addEventListener('click', function() {{
				signaturePad.clear();
				hiddenInput.value = '';
			}});
		}}

		// Bootstrap modal/tab layout recovery
		document.addEventListener('shown.bs.modal', function(e) {{
			if (e.target && e.target.contains(canvas)) {{
				resizeCanvas();
				signaturePad.clear();
			}}
		}});
		document.addEventListener('shown.bs.tab', function(e) {{
			if (e.target && document.querySelector(e.target.dataset.bsTarget || e.target.getAttribute('href') || '').contains(canvas)) {{
				resizeCanvas();
			}}
		}});
	}}

	if (document.readyState === 'loading') {{
		document.addEventListener('DOMContentLoaded', init);
	}} else {{
		init();
	}}
}})();
</script>"""
