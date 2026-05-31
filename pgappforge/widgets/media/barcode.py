"""
BarcodeWidget — 1D barcode generator using JsBarcode (CDN, no server deps).

Supported formats: CODE128, EAN13, EAN8, UPC (UPC-A), UPCE, CODE39, ITF14, MSI, pharmacode
"""

import json
import re

from markupsafe import Markup, escape
from wtforms.widgets import Input
from flask_babel import gettext
from pgappforge.widgets_postgresql._cdn import JSBARCODE_CDN_URL

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


def _js_json(value) -> str:
	"""json.dumps safe for embedding inside an HTML <script> block.

	Escapes < and > as Unicode escapes so the HTML parser cannot
	misinterpret </script> or <script> sequences inside the JS string.
	"""
	return (
		json.dumps(value)
		.replace("<", "\\u003c")
		.replace(">", "\\u003e")
		.replace("&", "\\u0026")
	)


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

	def __call__(self, field, **kwargs):
		wid = kwargs.get("id", field.id or field.name)
		value = field.data or ""
		return Markup(
			self._css(wid)
			+ self._html(field, wid, value)
			+ self._js(wid, value)
		)

	# ------------------------------------------------------------------ #
	# CSS  (rendered once per instance; safe because all values are       #
	# developer-controlled ints/hex — not user input)                     #
	# ------------------------------------------------------------------ #

	def _css(self, wid: str) -> str:
		return f"""
<style>
#{wid}-wrap {{
  border: 1px solid #dee2e6; border-radius: 8px;
  background: #f8f9fa; padding: 16px; display: inline-block; min-width: 280px;
}}
#{wid}-header {{
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;
}}
#{wid}-header h6 {{ margin: 0; font-size: 13px; color: #495057; font-weight: 600; }}
#{wid}-input-row {{ display: flex; gap: 8px; margin-bottom: 10px; }}
#{wid}-text {{
  flex: 1; padding: 6px 10px; border: 1px solid #ced4da; border-radius: 4px;
  font-size: 14px; font-family: monospace;
}}
#{wid}-text:focus {{
  outline: none; border-color: #0d6efd; box-shadow: 0 0 0 2px rgba(13,110,253,.2);
}}
#{wid}-fmt {{
  padding: 6px 8px; border: 1px solid #ced4da; border-radius: 4px;
  font-size: 13px; background: white;
}}
#{wid}-preview {{
  text-align: center; min-height: {self.height + 30}px;
  background: {self.background}; border: 1px solid #e9ecef; border-radius: 4px; padding: 10px;
}}
#{wid}-svg {{ max-width: 100%; }}
#{wid}-error {{ color: #dc3545; font-size: 12px; margin-top: 4px; display: none; }}
#{wid}-hint {{ color: #6c757d; font-size: 11px; margin-top: 4px; }}
#{wid}-actions {{ display: flex; gap: 6px; margin-top: 10px; justify-content: flex-end; }}
#{wid}-actions button {{
  padding: 4px 10px; font-size: 12px; border: 1px solid #ced4da;
  border-radius: 4px; background: white; cursor: pointer;
}}
#{wid}-actions button:hover {{ background: #e9ecef; }}
</style>"""

	# ------------------------------------------------------------------ #
	# HTML                                                                 #
	# ------------------------------------------------------------------ #

	def _html(self, field, wid: str, value: str) -> str:
		fmt_info = FORMAT_CONSTRAINTS.get(self.fmt, {})
		hint = escape(fmt_info.get("hint", ""))
		safe_value = escape(value)
		safe_name = escape(field.name)
		safe_wid = escape(wid)

		fmt_options = "\n".join(
			f'<option value="{escape(k)}"{" selected" if k == self.fmt else ""}>'
			f'{escape(v["label"])}</option>'
			for k, v in FORMAT_CONSTRAINTS.items()
		)
		fmt_el = (
			f'<select id="{safe_wid}-fmt" title="Barcode format">{fmt_options}</select>'
			if self.enable_format_switch
			else f'<span style="font-size:12px;color:#6c757d">'
			     f'{escape(fmt_info.get("label", self.fmt))}</span>'
		)

		export_buttons = ""
		if self.enable_export:
			export_buttons = (
				f'<div id="{safe_wid}-actions">'
				f'<button type="button" data-action="svg">{escape(gettext("SVG"))}</button>'
				f'<button type="button" data-action="png">{escape(gettext("PNG"))}</button>'
				f'</div>'
			)

		return (
			f'<div id="{safe_wid}-wrap">'
			f'<div id="{safe_wid}-header">'
			f'<h6>&#x1F4CA; {escape(gettext("Barcode"))}</h6>{fmt_el}</div>'
			f'<div id="{safe_wid}-input-row">'
			f'<input type="text" id="{safe_wid}-text" value="{safe_value}"'
			f' placeholder="{escape(gettext("Enter value..."))}"'
			f' autocomplete="off" spellcheck="false" /></div>'
			f'<div id="{safe_wid}-hint">{hint}</div>'
			f'<div id="{safe_wid}-error"></div>'
			f'<div id="{safe_wid}-preview"><svg id="{safe_wid}-svg"></svg></div>'
			f'{export_buttons}'
			f'<input type="hidden" name="{safe_name}" id="{safe_wid}" value="{safe_value}" />'
			f'</div>'
		)

	# ------------------------------------------------------------------ #
	# JS                                                                   #
	# ------------------------------------------------------------------ #

	def _js(self, wid: str, initial_value: str) -> str:
		js_wid = _js_id(wid)  # safe JS identifier (hyphens → underscores)
		constraints_json = _js_json({
			k: v.get("pattern", "") for k, v in FORMAT_CONSTRAINTS.items()
		})
		display_value_js = _js_json(self.display_value)
		initial_value_js = _js_json(initial_value)

		return f"""
<script>
(function() {{
  var WID = {_js_json(wid)};    // DOM id (may contain hyphens)
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
    var el = $$('+error'); if (!el) return;
    el.textContent = msg; el.style.display = 'block';
  }}
  function clearErr() {{
    var el = $$('+error'); if (el) el.style.display = 'none';
  }}

  function currentFmt() {{
    var el = $$('+fmt');
    return (el && el.tagName === 'SELECT') ? el.value : {_js_json(self.fmt)};
  }}

  function render(val) {{
    clearErr();
    if (!val) {{ $$('+svg').innerHTML = ''; return; }}
    var fmt = currentFmt();
    var pat = PATTERNS[fmt];
    if (pat && !new RegExp(pat).test(val)) {{
      var hints = {{EAN13:'13 digits',EAN8:'8 digits',UPC:'12 digits',
                    UPCE:'8 digits',ITF14:'14 digits',MSI:'digits only'}};
      showErr('Invalid for ' + fmt + ' — ' + (hints[fmt] || 'check format'));
      return;
    }}
    try {{
      JsBarcode('#' + WID + '+svg', val, {{
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
    var svg = $$('+svg');
    if (!svg || !svg.innerHTML) return;
    var svgStr = new XMLSerializer().serializeToString(svg);
    if (fmt === 'svg') {{
      var blob = new Blob([svgStr], {{type:'image/svg+xml'}});
      var a = document.createElement('a'); a.href = URL.createObjectURL(blob);
      a.download = 'barcode.svg'; a.click();
    }} else {{
      var img = new Image();
      img.onload = function() {{
        var c = document.createElement('canvas');
        c.width = img.width; c.height = img.height;
        c.getContext('2d').drawImage(img, 0, 0);
        var a = document.createElement('a'); a.href = c.toDataURL('image/png');
        a.download = 'barcode.png'; a.click();
      }};
      // TextEncoder → Uint8Array → btoa avoids deprecated unescape
      var bytes = new TextEncoder().encode(svgStr);
      var bin = Array.from(bytes, function(b) {{ return String.fromCharCode(b); }}).join('');
      img.src = 'data:image/svg+xml;base64,' + btoa(bin);
    }}
  }}

  function init() {{
    var textEl = $$('+text'), hiddenEl = document.getElementById(WID);
    var fmtEl = $$('+fmt'), actionsEl = $$('+actions');

    if (textEl) textEl.addEventListener('input', function() {{
      if (hiddenEl) hiddenEl.value = this.value;
      render(this.value);
    }});
    if (fmtEl && fmtEl.tagName === 'SELECT') {{
      fmtEl.addEventListener('change', function() {{ render(textEl ? textEl.value : ''); }});
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
