"""BarcodeWidget — 1D barcode generator using JsBarcode (CDN, no server deps).

Supported formats: CODE128, EAN13, EAN8, UPC (UPC-A), UPCE, CODE39, ITF14, MSI, pharmacode
"""

from __future__ import annotations
import re

from markupsafe import Markup, escape
from wtforms.widgets import Input
from flask_babel import gettext
from pgappforge.widgets_postgresql._cdn import JSBARCODE_CDN_URL
from pgappforge.widgets._utils import js_json as _js_json

FORMAT_CONSTRAINTS: dict[str, dict] = {
	"CODE128":    {"label": "Code 128",   "hint": "Any ASCII text"},
	"EAN13":      {"label": "EAN-13",     "hint": "13 digits", "pattern": r"^\d{13}$"},
	"EAN8":       {"label": "EAN-8",      "hint": "8 digits",  "pattern": r"^\d{8}$"},
	"UPC":        {"label": "UPC-A",      "hint": "12 digits", "pattern": r"^\d{12}$"},
	"UPCE":       {"label": "UPC-E",      "hint": "8 digits",  "pattern": r"^\d{8}$"},
	"CODE39":     {"label": "Code 39",    "hint": "A-Z 0-9 - . $ / + % space"},
	"ITF14":      {"label": "ITF-14",     "hint": "14 digits", "pattern": r"^\d{14}$"},
	"MSI":        {"label": "MSI",        "hint": "Digits only", "pattern": r"^\d+$"},
	"pharmacode": {"label": "Pharmacode", "hint": "Integer 3–131070"},
}

VALID_FORMATS = frozenset(FORMAT_CONSTRAINTS)


def _js_id(wid: str) -> str:
	"""Sanitize a DOM id for use as a JS identifier (replace non-word chars)."""
	return re.sub(r"\W", "_", wid)


class BarcodeWidget(Input):
	"""
	WTForms widget that renders a configurable 1D barcode using JsBarcode.

	The field value is the barcode payload (stored in the DB column as text).
	SVG rendering is fully client-side — no server round-trip.

	Usage::

		class ProductForm(Form):
			sku = StringField(widget=BarcodeWidget(fmt="CODE128"))
			ean = StringField(widget=BarcodeWidget(fmt="EAN13", display_value=True))
	"""

	def __init__(
		self,
		fmt: str = "CODE128",
		width: int = 2,
		height: int = 80,
		display_value: bool = True,
		font_size: int = 14,
		line_color: str = "#000000",
		background: str = "#ffffff",
		margin: int = 10,
		enable_export: bool = True,
		enable_format_switch: bool = False,
		# Universal kwargs
		placeholder: str = "",
		css_class: str = "",
		description: str = "",
		readonly: bool = False,
		disabled: bool = False,
		**kwargs,
	):
		super().__init__(**kwargs)
		fmt_upper = fmt.upper()
		self.fmt = fmt_upper if fmt_upper in VALID_FORMATS else "CODE128"
		self.width = int(width)
		self.height = int(height)
		self.display_value = bool(display_value)
		self.font_size = int(font_size)
		self.line_color = line_color
		self.background = background
		self.margin = int(margin)
		self.enable_export = enable_export
		self.enable_format_switch = enable_format_switch
		self.placeholder = placeholder
		self.css_class = css_class
		self.description = description
		self.readonly = readonly
		self.disabled = disabled

	def __call__(self, field, **kwargs):
		wid = kwargs.get("id", field.id or field.name)
		value = field.data or ""
		has_errors = bool(field.errors)

		html = (
			self._css(wid)
			+ self._html(field, wid, value, has_errors)
			+ self._js(wid, value)
		)

		# WTForms server-side errors
		if has_errors:
			html += (
				f'<div class="invalid-feedback d-block" id="{escape(wid)}_error" role="alert">'
			)
			for error in field.errors:
				html += f'<span>{escape(str(error))}</span>'
			html += '</div>'

		# Help text
		if self.description:
			html += (
				f'<small class="form-text text-muted" id="{escape(wid)}_help">'
				f'{escape(self.description)}</small>'
			)

		return Markup(html)

	# ------------------------------------------------------------------ #
	# CSS — uses CSS custom properties for dark mode compatibility         #
	# ------------------------------------------------------------------ #

	def _css(self, wid: str) -> str:
		return f"""
<style>
#{escape(wid)}-wrap {{
  border: 1px solid var(--bs-border-color, #dee2e6);
  border-radius: 8px;
  background: var(--bs-secondary-bg, #f8f9fa);
  padding: 16px;
  display: inline-block;
  min-width: 280px;
  width: 100%;
  max-width: 600px;
}}
#{escape(wid)}-wrap.is-invalid {{
  border-color: var(--bs-danger, #dc3545);
}}
#{escape(wid)}-header {{
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;
}}
#{escape(wid)}-header h6 {{
  margin: 0; font-size: 13px;
  color: var(--bs-secondary-color, #495057); font-weight: 600;
}}
#{escape(wid)}-input-row {{ display: flex; gap: 8px; margin-bottom: 10px; }}
#{escape(wid)}-text {{
  flex: 1; padding: 6px 10px;
  border: 1px solid var(--bs-border-color, #ced4da);
  border-radius: 4px;
  font-size: 14px; font-family: monospace;
  background: var(--bs-body-bg, white);
  color: var(--bs-body-color, #212529);
}}
#{escape(wid)}-text:focus {{
  outline: none;
  border-color: var(--bs-primary, #0d6efd);
  box-shadow: 0 0 0 2px rgba(13,110,253,.2);
}}
#{escape(wid)}-fmt {{
  padding: 6px 8px;
  border: 1px solid var(--bs-border-color, #ced4da);
  border-radius: 4px;
  font-size: 13px;
  background: var(--bs-body-bg, white);
  color: var(--bs-body-color, #212529);
}}
#{escape(wid)}-preview {{
  text-align: center; min-height: {self.height + 30}px;
  background: {escape(self.background)};
  border: 1px solid var(--bs-border-color, #e9ecef);
  border-radius: 4px; padding: 10px;
}}
#{escape(wid)}-svg {{ max-width: 100%; }}
#{escape(wid)}-error {{
  color: var(--bs-danger, #dc3545); font-size: 12px; margin-top: 4px; display: none;
}}
#{escape(wid)}-hint {{
  color: var(--bs-secondary-color, #6c757d); font-size: 11px; margin-top: 4px;
}}
#{escape(wid)}-actions {{ display: flex; gap: 6px; margin-top: 10px; justify-content: flex-end; }}
#{escape(wid)}-actions button {{
  padding: 4px 10px; font-size: 12px;
  border: 1px solid var(--bs-border-color, #ced4da);
  border-radius: 4px;
  background: var(--bs-body-bg, white);
  color: var(--bs-body-color, #212529);
  cursor: pointer;
}}
#{escape(wid)}-actions button:hover {{
  background: var(--bs-secondary-bg, #e9ecef);
}}
</style>"""

	# ------------------------------------------------------------------ #
	# HTML                                                                 #
	# ------------------------------------------------------------------ #

	def _html(self, field, wid: str, value: str, has_errors: bool = False) -> str:
		fmt_info = FORMAT_CONSTRAINTS.get(self.fmt, {})
		hint = escape(fmt_info.get("hint", ""))
		safe_value = escape(value)
		safe_name = escape(field.name)
		safe_wid = escape(wid)
		label_text = str(field.label.text) if field.label else gettext("Barcode")
		invalid_attr = ' aria-invalid="true"' if has_errors else ''
		wrapper_invalid = ' is-invalid' if has_errors else ''

		fmt_options = "\n".join(
			f'<option value="{escape(k)}"{" selected" if k == self.fmt else ""}>'
			f'{escape(v["label"])}</option>'
			for k, v in FORMAT_CONSTRAINTS.items()
		)
		if self.enable_format_switch:
			fmt_el = (
				f'<label for="{safe_wid}-fmt" class="visually-hidden sr-only">'
				f'{escape(gettext("Barcode format"))}</label>'
				f'<select id="{safe_wid}-fmt" title="{escape(gettext("Barcode format"))}"'
				f' aria-label="{escape(gettext("Barcode format"))}">'
				f'{fmt_options}</select>'
			)
		else:
			fmt_el = (
				f'<span style="font-size:12px;color:var(--bs-secondary-color,#6c757d)">'
				f'{escape(fmt_info.get("label", self.fmt))}</span>'
			)

		export_buttons = ""
		if self.enable_export:
			export_buttons = (
				f'<div id="{safe_wid}-actions" role="group"'
				f' aria-label="{escape(gettext("Export barcode"))}">'
				f'<button type="button" data-action="svg"'
				f' aria-label="{escape(gettext("Export as SVG"))}">'
				f'{escape(gettext("SVG"))}</button>'
				f'<button type="button" data-action="png"'
				f' aria-label="{escape(gettext("Export as PNG"))}">'
				f'{escape(gettext("PNG"))}</button>'
				'</div>'
			)

		readonly_attr = ' readonly' if self.readonly else ''
		disabled_attr = ' disabled' if self.disabled else ''
		placeholder_attr = f' placeholder="{escape(self.placeholder)}"' if self.placeholder else f' placeholder="{escape(gettext("Enter value..."))}"'

		return (
			f'<div id="{safe_wid}-wrap" class="barcode-widget{wrapper_invalid}">'
			f'<div id="{safe_wid}-header">'
			f'<h6 id="{safe_wid}-label">&#x1F4CA; {escape(gettext("Barcode"))}</h6>'
			f'{fmt_el}</div>'
			f'<div id="{safe_wid}-input-row">'
			f'<label for="{safe_wid}-text" class="visually-hidden sr-only">'
			f'{escape(label_text)}</label>'
			f'<input type="text" id="{safe_wid}-text" value="{safe_value}"'
			f'{placeholder_attr}'
			f' autocomplete="off" spellcheck="false"'
			f' aria-label="{escape(label_text)}"'
			f' aria-describedby="{safe_wid}-hint {safe_wid}-error"'
			f'{invalid_attr}{readonly_attr}{disabled_attr} />'
			'</div>'
			f'<div id="{safe_wid}-hint" aria-live="polite">{hint}</div>'
			f'<div id="{safe_wid}-error" role="alert" aria-live="assertive"></div>'
			f'<div id="{safe_wid}-preview">'
			f'<svg id="{safe_wid}-svg" aria-label="{escape(gettext("Barcode preview"))}" role="img"></svg>'
			'</div>'
			f'{export_buttons}'
			f'<input type="hidden" name="{safe_name}" id="{safe_wid}"'
			f' value="{safe_value}"'
			f' aria-label="{escape(label_text)}"{invalid_attr} />'
			'</div>'
		)

	# ------------------------------------------------------------------ #
	# JS                                                                   #
	# ------------------------------------------------------------------ #

	def _js(self, wid: str, initial_value: str) -> str:
		constraints_json = _js_json({
			k: v.get("pattern", "") for k, v in FORMAT_CONSTRAINTS.items()
		})
		display_value_js = _js_json(self.display_value)
		initial_value_js = _js_json(initial_value)

		return f"""
<script>
(function() {{
  var WID = {_js_json(wid)};
  var PATTERNS = {constraints_json};
  var INITIAL = {initial_value_js};

  function loadLib(cb) {{
    if (window.JsBarcode) {{ cb(); return; }}
    var s = document.createElement('script');
    s.src = {_js_json(JSBARCODE_CDN_URL)};
    s.onload = cb;
    s.onerror = function() {{
      showErr('JsBarcode library failed to load (check network).');
    }};
    document.head.appendChild(s);
  }}

  function $$(id) {{ return document.getElementById(WID + id); }}

  function showErr(msg) {{
    var el = $$('-error');
    if (!el) return;
    el.textContent = msg;
    el.style.display = 'block';
    var textEl = $$('-text');
    if (textEl) textEl.setAttribute('aria-invalid', 'true');
  }}

  function clearErr() {{
    var el = $$('-error');
    if (el) el.style.display = 'none';
    var textEl = $$('-text');
    if (textEl) textEl.removeAttribute('aria-invalid');
  }}

  function currentFmt() {{
    var el = $$('-fmt');
    return (el && el.tagName === 'SELECT') ? el.value : {_js_json(self.fmt)};
  }}

  function render(val) {{
    clearErr();
    if (!val) {{ $$('-svg').innerHTML = ''; return; }}
    var fmt = currentFmt();
    var pat = PATTERNS[fmt];
    if (pat && !new RegExp(pat).test(val)) {{
      var hints = {{
        EAN13: '13 digits', EAN8: '8 digits', UPC: '12 digits',
        UPCE: '8 digits', ITF14: '14 digits', MSI: 'digits only'
      }};
      showErr('Invalid for ' + fmt + ' — ' + (hints[fmt] || 'check format'));
      return;
    }}
    try {{
      JsBarcode('#' + WID + '-svg', val, {{
        format: fmt,
        width: {self.width},
        height: {self.height},
        displayValue: {display_value_js},
        fontSize: {self.font_size},
        lineColor: {_js_json(self.line_color)},
        background: {_js_json(self.background)},
        margin: {self.margin},
        valid: function(v) {{
          if (!v) showErr('Value not valid for format ' + fmt);
        }}
      }});
    }} catch(e) {{ showErr(e.message || 'Render error'); }}
  }}

  function download(fmt) {{
    var svg = $$('-svg');
    if (!svg || !svg.innerHTML) return;
    var svgStr = new XMLSerializer().serializeToString(svg);
    if (fmt === 'svg') {{
      var blob = new Blob([svgStr], {{type: 'image/svg+xml'}});
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'barcode.svg';
      a.click();
    }} else {{
      var img = new Image();
      img.onload = function() {{
        var c = document.createElement('canvas');
        c.width = img.width; c.height = img.height;
        c.getContext('2d').drawImage(img, 0, 0);
        var a = document.createElement('a');
        a.href = c.toDataURL('image/png');
        a.download = 'barcode.png';
        a.click();
      }};
      var bytes = new TextEncoder().encode(svgStr);
      var bin = Array.from(bytes, function(b) {{ return String.fromCharCode(b); }}).join('');
      img.src = 'data:image/svg+xml;base64,' + btoa(bin);
    }}
  }}

  function init() {{
    var textEl = $$('-text');
    var hiddenEl = document.getElementById(WID);
    var fmtEl = $$('-fmt');
    var actionsEl = $$('-actions');

    if (textEl) textEl.addEventListener('input', function() {{
      if (hiddenEl) hiddenEl.value = this.value;
      render(this.value);
    }});
    if (fmtEl && fmtEl.tagName === 'SELECT') {{
      fmtEl.addEventListener('change', function() {{
        render(textEl ? textEl.value : '');
      }});
    }}
    if (actionsEl) actionsEl.addEventListener('click', function(e) {{
      var btn = e.target.closest('button[data-action]');
      if (btn) download(btn.dataset.action);
    }});

    loadLib(function() {{ if (INITIAL) render(INITIAL); }});
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', init);
  }} else {{
    init();
  }}
}})();
</script>"""
