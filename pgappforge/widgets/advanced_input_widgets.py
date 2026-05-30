from __future__ import annotations

from markupsafe import Markup
from wtforms.widgets import html_params

__all__ = [
	"RecurringScheduleWidget",
	"MentionWidget",
	"CurrencyConverterWidget",
	"PhoneDialWidget",
	"DocumentPreviewWidget",
	"ConversationWidget",
]


class RecurringScheduleWidget:
	"""Visual cron/recurrence rule builder.

	Stores an RRULE string (RFC 5545) in a hidden input for form submission.
	Renders radio buttons for frequency, day checkboxes for weekly, and
	hour/minute selectors. Shows a human-readable summary line.

	Example stored value: ``FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=9;BYMINUTE=0``
	"""

	def __call__(self, field, **kwargs) -> Markup:
		fid = kwargs.get("id", field.id)
		name = kwargs.get("name", field.name)
		current_value = field.data or ""

		html = f"""
<div class="recurring-schedule-widget" id="{fid}_widget">
  <style>
    .recurring-schedule-widget {{ font-family: inherit; }}
    .rsw-section {{ margin-bottom: 10px; }}
    .rsw-section label {{ margin-right: 14px; cursor: pointer; }}
    .rsw-day-checks label {{ display: inline-block; margin-right: 10px; cursor: pointer; }}
    .rsw-summary {{ margin-top: 8px; color: #555; font-style: italic; font-size: 0.92em; }}
    .rsw-time-row {{ display: flex; align-items: center; gap: 6px; margin-top: 8px; }}
    .rsw-time-row select {{ width: auto; padding: 2px 4px; }}
    .rsw-weekly-days {{ display: none; }}
    .rsw-monthly-row {{ display: none; margin-top: 8px; }}
  </style>

  <!-- frequency radios -->
  <div class="rsw-section">
    <strong>Repeat:</strong><br/>
    <label><input type="radio" name="{fid}_freq" value="DAILY" class="rsw-freq-radio"> Daily</label>
    <label><input type="radio" name="{fid}_freq" value="WEEKLY" class="rsw-freq-radio" checked> Weekly</label>
    <label><input type="radio" name="{fid}_freq" value="MONTHLY" class="rsw-freq-radio"> Monthly</label>
    <label><input type="radio" name="{fid}_freq" value="CUSTOM" class="rsw-freq-radio"> Custom RRULE</label>
  </div>

  <!-- weekly day checkboxes -->
  <div class="rsw-weekly-days rsw-section" id="{fid}_weekly_days" style="display:block;">
    <strong>On:</strong><br/>
    <div class="rsw-day-checks">
      <label><input type="checkbox" class="rsw-day" value="MO"> Mon</label>
      <label><input type="checkbox" class="rsw-day" value="TU"> Tue</label>
      <label><input type="checkbox" class="rsw-day" value="WE"> Wed</label>
      <label><input type="checkbox" class="rsw-day" value="TH"> Thu</label>
      <label><input type="checkbox" class="rsw-day" value="FR"> Fri</label>
      <label><input type="checkbox" class="rsw-day" value="SA"> Sat</label>
      <label><input type="checkbox" class="rsw-day" value="SU"> Sun</label>
    </div>
  </div>

  <!-- monthly day-of-month -->
  <div class="rsw-monthly-row rsw-section" id="{fid}_monthly_row">
    <strong>Day of month:</strong>
    <select id="{fid}_monthday" class="form-control" style="width:auto;display:inline-block;">
      {''.join(f'<option value="{d}">{d}</option>' for d in range(1, 32))}
    </select>
  </div>

  <!-- time selectors -->
  <div class="rsw-section rsw-time-row">
    <strong>At:</strong>
    <select id="{fid}_hour" class="form-control">
      {''.join(f'<option value="{h}">{h:02d}</option>' for h in range(24))}
    </select>
    <span>:</span>
    <select id="{fid}_minute" class="form-control">
      {''.join(f'<option value="{m}">{m:02d}</option>' for m in range(0, 60, 5))}
    </select>
  </div>

  <!-- custom RRULE input (hidden unless Custom selected) -->
  <div id="{fid}_custom_row" class="rsw-section" style="display:none;">
    <label><strong>Custom RRULE:</strong><br/>
    <input type="text" id="{fid}_custom_input" class="form-control"
           placeholder="FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=9;BYMINUTE=0" style="width:100%;"/>
    </label>
  </div>

  <!-- human-readable summary -->
  <div class="rsw-summary" id="{fid}_summary">Select options above to build schedule.</div>

  <!-- hidden field submitted with the form -->
  <input type="hidden" id="{fid}" name="{name}" value="{current_value}"/>
</div>

<script>
(function() {{
  var fid = {fid!r};
  var days = {{'MO':'Monday','TU':'Tuesday','WE':'Wednesday','TH':'Thursday',
               'FR':'Friday','SA':'Saturday','SU':'Sunday'}};
  var ordinal = function(n) {{
    var s = ['th','st','nd','rd'], v = n % 100;
    return n + (s[(v-20)%10] || s[v] || s[0]);
  }};

  function rebuildRrule() {{
    var freq = document.querySelector('input[name="' + fid + '_freq"]:checked');
    if (!freq) return;
    var hidden = document.getElementById(fid);
    var summary = document.getElementById(fid + '_summary');
    var hour = document.getElementById(fid + '_hour').value;
    var minute = document.getElementById(fid + '_minute').value;
    var hNum = parseInt(hour, 10);
    var mNum = parseInt(minute, 10);
    var ampm = hNum >= 12 ? 'PM' : 'AM';
    var h12 = hNum % 12 || 12;
    var timeStr = h12 + ':' + (mNum < 10 ? '0' : '') + mNum + ' ' + ampm;

    if (freq.value === 'CUSTOM') {{
      var raw = document.getElementById(fid + '_custom_input').value.trim();
      hidden.value = raw;
      summary.textContent = raw ? 'Custom: ' + raw : 'Enter an RRULE above.';
      return;
    }}

    var parts = ['FREQ=' + freq.value];
    var summaryText = '';

    if (freq.value === 'WEEKLY') {{
      var checked = Array.from(document.querySelectorAll('#' + fid + '_widget .rsw-day:checked'))
                        .map(function(cb) {{ return cb.value; }});
      if (checked.length) {{
        parts.push('BYDAY=' + checked.join(','));
        var dayNames = checked.map(function(d) {{ return days[d]; }});
        summaryText = 'Every ' + dayNames.join(' and ') + ' at ' + timeStr;
      }} else {{
        summaryText = 'Every week at ' + timeStr;
      }}
    }} else if (freq.value === 'DAILY') {{
      summaryText = 'Every day at ' + timeStr;
    }} else if (freq.value === 'MONTHLY') {{
      var md = document.getElementById(fid + '_monthday').value;
      parts.push('BYMONTHDAY=' + md);
      summaryText = 'Every month on the ' + ordinal(parseInt(md,10)) + ' at ' + timeStr;
    }}

    parts.push('BYHOUR=' + hour);
    parts.push('BYMINUTE=' + minute);
    hidden.value = parts.join(';');
    summary.textContent = summaryText;
  }}

  function updateVisibility() {{
    var freq = document.querySelector('input[name="' + fid + '_freq"]:checked');
    if (!freq) return;
    document.getElementById(fid + '_weekly_days').style.display = freq.value === 'WEEKLY' ? 'block' : 'none';
    document.getElementById(fid + '_monthly_row').style.display = freq.value === 'MONTHLY' ? 'block' : 'none';
    document.getElementById(fid + '_custom_row').style.display = freq.value === 'CUSTOM' ? 'block' : 'none';
    rebuildRrule();
  }}

  document.querySelectorAll('input[name="' + fid + '_freq"]').forEach(function(r) {{
    r.addEventListener('change', updateVisibility);
  }});
  document.querySelectorAll('#' + fid + '_widget .rsw-day').forEach(function(cb) {{
    cb.addEventListener('change', rebuildRrule);
  }});
  ['hour','minute','monthday'].forEach(function(sel) {{
    var el = document.getElementById(fid + '_' + sel);
    if (el) el.addEventListener('change', rebuildRrule);
  }});
  var customIn = document.getElementById(fid + '_custom_input');
  if (customIn) customIn.addEventListener('input', rebuildRrule);

  // parse existing value on load
  (function parseExisting() {{
    var val = {current_value!r};
    if (!val) return;
    var map = {{}};
    val.split(';').forEach(function(part) {{
      var kv = part.split('=');
      if (kv.length === 2) map[kv[0]] = kv[1];
    }});
    // set frequency
    var freq = map['FREQ'];
    if (freq) {{
      var radio = document.querySelector('input[name="' + fid + '_freq"][value="' + freq + '"]');
      if (radio) radio.checked = true;
    }}
    // set days
    if (map['BYDAY']) {{
      map['BYDAY'].split(',').forEach(function(d) {{
        var cb = document.querySelector('#' + fid + '_widget .rsw-day[value="' + d + '"]');
        if (cb) cb.checked = true;
      }});
    }}
    // set hour/minute
    if (map['BYHOUR']) {{
      var hEl = document.getElementById(fid + '_hour');
      if (hEl) hEl.value = map['BYHOUR'];
    }}
    if (map['BYMINUTE']) {{
      var mEl = document.getElementById(fid + '_minute');
      if (mEl) mEl.value = map['BYMINUTE'];
    }}
    if (map['BYMONTHDAY']) {{
      var mdEl = document.getElementById(fid + '_monthday');
      if (mdEl) mdEl.value = map['BYMONTHDAY'];
    }}
    updateVisibility();
  }})();

  // initial state
  updateVisibility();
}})();
</script>
"""
		return Markup(html)


class MentionWidget:
	"""@mention-enabled textarea backed by Tribute.js.

	When the user types ``@``, a dropdown is fetched from ``/api/v1/users``
	and the selected username is inserted inline. Stores raw text with
	``@username`` tokens. Extends the BS3TextArea look.

	CDN: https://cdn.jsdelivr.net/npm/tributejs@5/dist/tribute.min.js
	"""

	TRIBUTE_CSS = "https://cdn.jsdelivr.net/npm/tributejs@5/dist/tribute.css"
	TRIBUTE_JS = "https://cdn.jsdelivr.net/npm/tributejs@5/dist/tribute.min.js"

	def __init__(self, rows: int = 5, users_endpoint: str = "/api/v1/users") -> None:
		self.rows = rows
		self.users_endpoint = users_endpoint

	def __call__(self, field, **kwargs) -> Markup:
		fid = kwargs.get("id", field.id)
		name = kwargs.get("name", field.name)
		value = field.data or ""
		rows = kwargs.get("rows", self.rows)
		placeholder = field.label.text if field.label else ""
		endpoint = self.users_endpoint

		html = f"""
<link rel="stylesheet" href="{self.TRIBUTE_CSS}"/>
<script src="{self.TRIBUTE_JS}"></script>

<textarea
  id="{fid}"
  name="{name}"
  class="form-control"
  rows="{rows}"
  placeholder="{placeholder}"
  style="resize:vertical;"
>{value}</textarea>

<script>
(function() {{
  var ta = document.getElementById({fid!r});
  var tribute = new Tribute({{
    trigger: '@',
    allowSpaces: false,
    lookup: 'username',
    fillAttr: 'username',
    values: function(text, cb) {{
      fetch({endpoint!r} + '?q=' + encodeURIComponent(text) + '&keys=username')
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
          // support both {{result: [...]}} and flat array responses
          cb(Array.isArray(data) ? data : (data.result || []));
        }})
        .catch(function() {{ cb([]); }});
    }},
    menuItemTemplate: function(item) {{
      return '<span>@' + item.original.username + '</span>';
    }},
    selectTemplate: function(item) {{
      return '@' + item.original.username;
    }},
  }});
  tribute.attach(ta);
}})();
</script>
"""
		return Markup(html)


class CurrencyConverterWidget:
	"""Amount input with live currency conversion display.

	Args:
		base_currency: The currency to store (e.g. ``"USD"``).
		allowed_currencies: List of ISO-4217 codes to show in the dropdown.
		rates_endpoint: Optional URL returning ``{rates: {CODE: float}}``.
		  Defaults to the ECB/exchangerate.host free tier.

	Stores the amount in *base_currency* in a hidden field as a decimal
	string. Conversion is done client-side using cached rates fetched once
	on page load.
	"""

	DEFAULT_RATES_ENDPOINT = "https://api.exchangerate.host/latest?base={base}"

	def __init__(
		self,
		base_currency: str = "USD",
		allowed_currencies: list[str] | None = None,
		rates_endpoint: str | None = None,
	) -> None:
		self.base_currency = base_currency.upper()
		self.allowed_currencies = [c.upper() for c in (allowed_currencies or ["USD", "EUR", "GBP", "JPY", "CAD"])]
		self.rates_endpoint = rates_endpoint or self.DEFAULT_RATES_ENDPOINT.format(base=self.base_currency)

	def __call__(self, field, **kwargs) -> Markup:
		fid = kwargs.get("id", field.id)
		name = kwargs.get("name", field.name)
		current_value = field.data or ""
		base = self.base_currency
		currencies_json = "[" + ",".join(f'"{c}"' for c in self.allowed_currencies) + "]"
		endpoint = self.rates_endpoint

		html = f"""
<div class="currency-converter-widget" id="{fid}_widget">
  <style>
    .ccw-row {{ display: flex; align-items: center; gap: 8px; }}
    .ccw-converted {{ margin-top: 6px; color: #555; font-size: 0.9em; min-height: 1.2em; }}
    .ccw-row input[type=number] {{ flex: 1; }}
    .ccw-row select {{ width: auto; }}
  </style>
  <div class="ccw-row">
    <input type="number" id="{fid}_amount" class="form-control"
           step="0.01" min="0" placeholder="0.00"
           value=""/>
    <select id="{fid}_currency" class="form-control">
      {''.join(f'<option value="{c}">{c}</option>' for c in self.allowed_currencies)}
    </select>
  </div>
  <div class="ccw-converted" id="{fid}_converted"></div>
  <!-- stores amount in {base} -->
  <input type="hidden" id="{fid}" name="{name}" value="{current_value}"/>
</div>

<script>
(function() {{
  var fid = {fid!r};
  var base = {base!r};
  var endpoint = {endpoint!r};
  var rates = null;
  var hidden = document.getElementById(fid);
  var amtEl = document.getElementById(fid + '_amount');
  var curEl = document.getElementById(fid + '_currency');
  var convEl = document.getElementById(fid + '_converted');

  function fmt(n, cur) {{
    try {{
      return new Intl.NumberFormat('en-US', {{style:'currency', currency:cur, maximumFractionDigits:2}}).format(n);
    }} catch(e) {{ return n.toFixed(2) + ' ' + cur; }}
  }}

  function update() {{
    var amt = parseFloat(amtEl.value);
    var cur = curEl.value;
    if (isNaN(amt) || amt < 0) {{ convEl.textContent = ''; hidden.value = ''; return; }}
    if (!rates) {{ hidden.value = cur === base ? amt.toFixed(2) : ''; convEl.textContent = 'Loading rates…'; return; }}
    var rate = cur === base ? 1 : (rates[cur] ? 1 / rates[cur] : null);
    if (rate === null) {{ convEl.textContent = 'Rate unavailable'; return; }}
    var inBase = amt * rate;
    hidden.value = inBase.toFixed(6);
    convEl.textContent = '= ' + fmt(inBase, base);
  }}

  amtEl.addEventListener('input', update);
  curEl.addEventListener('change', update);

  // pre-fill if hidden already has a value
  if (hidden.value) {{
    amtEl.value = parseFloat(hidden.value).toFixed(2);
    curEl.value = base;
  }}

  // fetch rates once
  fetch(endpoint)
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      rates = data.rates || data;
      update();
    }})
    .catch(function() {{
      convEl.textContent = 'Could not load exchange rates.';
    }});
}})();
</script>
"""
		return Markup(html)


class PhoneDialWidget:
	"""Read-only phone number display with copy and click-to-call actions.

	Formats E.164 numbers for display. Shows:
	- Formatted number text
	- Copy-to-clipboard button
	- ``tel:`` link button to launch the system phone/SIP app
	- Optional call-history badge (integer count passed via ``call_count``
	  in the field's object data; widget reads ``field.object_data`` if set)

	This is intentionally read-only — phone numbers should be edited in a
	plain text field and displayed here.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		fid = kwargs.get("id", field.id)
		name = kwargs.get("name", field.name)
		raw = field.data or ""

		# optional call count from object_data dict
		call_count: int | None = None
		if hasattr(field, "object_data") and isinstance(field.object_data, dict):
			call_count = field.object_data.get("call_count")

		badge_html = ""
		if call_count is not None:
			badge_html = (
				f'<span class="badge" title="{call_count} call(s) on record" '
				f'style="margin-left:6px;background:#6c757d;">{call_count}</span>'
			)

		html = f"""
<div class="phone-dial-widget" id="{fid}_widget" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
  <style>
    .pdw-number {{ font-family: monospace; font-size: 1.05em; letter-spacing: 0.04em; }}
    .pdw-btn {{ cursor:pointer; border:none; background:none; padding:2px 6px;
               border-radius:4px; font-size:0.9em; }}
    .pdw-btn:hover {{ background:#e9ecef; }}
  </style>
  <span class="pdw-number" id="{fid}_display">{raw}</span>
  {badge_html}
  <button type="button" class="pdw-btn btn btn-sm btn-default"
          id="{fid}_copy" title="Copy number"
          onclick="(function(){{
            var t = document.getElementById({fid!r}+'_display').textContent.replace(/\\s/g,'');
            navigator.clipboard ? navigator.clipboard.writeText(t) :
              (function(){{var ta=document.createElement('textarea');ta.value=t;
                document.body.appendChild(ta);ta.select();document.execCommand('copy');
                document.body.removeChild(ta);}})();
            var b=document.getElementById({fid!r}+'_copy');
            b.textContent='Copied!'; setTimeout(function(){{b.innerHTML='&#128203;';}},1500);
          }})();">&#128203;</button>
  <a class="pdw-btn btn btn-sm btn-success" id="{fid}_call"
     href="tel:{raw.replace(' ', '')}"
     title="Click to call" style="text-decoration:none;">&#128222; Call</a>
  <!-- hidden passthrough so the value round-trips on form submit -->
  <input type="hidden" id="{fid}" name="{name}" value="{raw}"/>
</div>

<script>
(function() {{
  // Format E.164 for display if possible
  var raw = {raw!r};
  var display = document.getElementById({fid!r} + '_display');
  var callLink = document.getElementById({fid!r} + '_call');
  if (!raw) return;
  // strip non-digits for tel: href
  var digits = raw.replace(/[^+\\d]/g, '');
  callLink.href = 'tel:' + digits;
  // simple visual formatter: +1 NXX NXX XXXX
  var formatted = raw;
  var m = digits.match(/^(\\+1|1)?(\\d{{3}})(\\d{{3}})(\\d{{4}})$/);
  if (m) {{ formatted = '+1 (' + m[2] + ') ' + m[3] + '-' + m[4]; }}
  display.textContent = formatted;
}})();
</script>
"""
		return Markup(html)


class DocumentPreviewWidget:
	"""Inline preview for PDF, image, and video files.

	Args:
		file_col: Name of the field/attribute carrying the path or URL.
		  Defaults to reading from ``field.data``.
		preview_height: CSS height string for the preview area (default ``"400px"``).

	Type detection is by file extension:
	- ``.pdf`` → PDF.js viewer (CDN)
	- ``.png/.jpg/.jpeg/.gif/.webp/.svg`` → ``<img>`` with click-to-zoom overlay
	- ``.mp4/.webm/.ogg/.mov`` → ``<video>`` with controls
	- Anything else → download link fallback

	PDF.js CDN: https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.min.mjs
	"""

	PDFJS_CDN = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.min.mjs"
	PDFJS_WORKER = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.worker.min.mjs"

	IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
	VIDEO_EXTS = {".mp4", ".webm", ".ogg", ".mov", ".avi"}

	def __init__(self, file_col: str | None = None, preview_height: str = "400px") -> None:
		self.file_col = file_col
		self.preview_height = preview_height

	def _ext(self, path: str) -> str:
		if "." not in path.split("/")[-1]:
			return ""
		return "." + path.rsplit(".", 1)[-1].lower()

	def __call__(self, field, **kwargs) -> Markup:
		fid = kwargs.get("id", field.id)
		src = field.data or ""
		height = self.preview_height
		ext = self._ext(src) if src else ""

		if not src:
			inner = '<div class="text-muted" style="padding:20px;">No file.</div>'
		elif ext == ".pdf":
			inner = self._pdf_block(fid, src, height)
		elif ext in self.IMAGE_EXTS:
			inner = self._image_block(fid, src, height)
		elif ext in self.VIDEO_EXTS:
			inner = self._video_block(src, height)
		else:
			inner = self._download_block(src)

		html = f"""
<div class="document-preview-widget" id="{fid}_preview_widget">
  <style>
    .dpw-zoom-overlay {{
      display:none; position:fixed; inset:0; background:rgba(0,0,0,.8);
      z-index:9999; align-items:center; justify-content:center; cursor:zoom-out;
    }}
    .dpw-zoom-overlay.active {{ display:flex; }}
    .dpw-zoom-overlay img {{ max-width:90vw; max-height:90vh; border-radius:4px; }}
  </style>
  {inner}
</div>
"""
		return Markup(html)

	def _pdf_block(self, fid: str, src: str, height: str) -> str:
		# Use PDF.js viewer via module script; fall back to <object> for
		# browsers that block cross-origin module workers.
		return f"""
<div id="{fid}_pdfcontainer" style="width:100%;height:{height};border:1px solid #ddd;overflow:auto;background:#525659;">
  <canvas id="{fid}_pdfcanvas" style="display:block;margin:auto;"></canvas>
</div>
<script type="module">
  import * as pdfjsLib from {self.PDFJS_CDN!r};
  pdfjsLib.GlobalWorkerOptions.workerSrc = {self.PDFJS_WORKER!r};
  var container = document.getElementById({(fid + '_pdfcontainer')!r});
  var canvas = document.getElementById({(fid + '_pdfcanvas')!r});
  var ctx = canvas.getContext('2d');
  pdfjsLib.getDocument({src!r}).promise.then(function(pdf) {{
    pdf.getPage(1).then(function(page) {{
      var vp = page.getViewport({{scale: container.clientWidth / page.getViewport({{scale:1}}).width}});
      canvas.width = vp.width;
      canvas.height = vp.height;
      page.render({{canvasContext: ctx, viewport: vp}});
    }});
  }}).catch(function(e) {{
    container.innerHTML = '<div style="color:#fff;padding:20px;">Failed to load PDF: ' + e.message + '</div>';
  }});
</script>
<noscript>
  <object data="{src}" type="application/pdf" width="100%" style="height:{height};">
    <a href="{src}">Download PDF</a>
  </object>
</noscript>
"""

	def _image_block(self, fid: str, src: str, height: str) -> str:
		return f"""
<div style="text-align:center;max-height:{height};overflow:auto;border:1px solid #ddd;padding:4px;">
  <img id="{fid}_img" src="{src}" alt="Preview"
       style="max-width:100%;max-height:{height};cursor:zoom-in;border-radius:2px;"
       onclick="document.getElementById({(fid + '_zoom')!r}).classList.add('active')"/>
</div>
<div class="dpw-zoom-overlay" id="{fid}_zoom"
     onclick="this.classList.remove('active')">
  <img src="{src}" alt="Zoomed preview"/>
</div>
"""

	def _video_block(self, src: str, height: str) -> str:
		return f"""
<video controls style="width:100%;max-height:{height};border:1px solid #ddd;background:#000;">
  <source src="{src}"/>
  Your browser does not support the video tag.
  <a href="{src}">Download video</a>
</video>
"""

	def _download_block(self, src: str) -> str:
		filename = src.split("/")[-1] or src
		return f"""
<div style="padding:12px;border:1px solid #ddd;border-radius:4px;">
  <a href="{src}" download class="btn btn-default">
    <span class="glyphicon glyphicon-download-alt"></span>
    Download {filename}
  </a>
</div>
"""


class ConversationWidget:
	"""Threaded comment thread with markdown rendering and emoji reactions.

	Args:
		messages: List of dicts with keys ``author``, ``text``,
		  ``created_at`` (ISO-8601 string), ``reactions`` (dict mapping
		  emoji → count, e.g. ``{"👍": 3, "❤️": 1}``).
		post_url: Endpoint that accepts POST for both new messages and
		  reaction toggles. New message POST body:
		  ``{action: "message", text: "..."}``.
		  Reaction POST body: ``{action: "react", emoji: "👍", message_index: N}``.
		markdown_cdn: Override the Marked.js CDN URL.

	Renders: avatar initials bubble + author + relative timestamp + rendered
	markdown text + reaction pill buttons + new-message form.
	"""

	MARKED_CDN = "https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"
	DOMPURIFY_CDN = "https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"
	REACTION_EMOJIS = ["👍", "❤️", "😀"]

	def __init__(
		self,
		messages: list[dict] | None = None,
		post_url: str = "",
		markdown_cdn: str | None = None,
	) -> None:
		self.messages = messages or []
		self.post_url = post_url
		self.markdown_cdn = markdown_cdn or self.MARKED_CDN

	def _avatar(self, author: str) -> str:
		initials = "".join(w[0].upper() for w in author.split()[:2]) if author else "?"
		# deterministic hue from author name
		hue = sum(ord(c) for c in author) % 360
		return (
			f'<span class="cwg-avatar" style="background:hsl({hue},55%,48%);">'
			f"{initials}</span>"
		)

	def _reaction_buttons(self, msg_index: int, reactions: dict) -> str:
		buttons = []
		for emoji in self.REACTION_EMOJIS:
			count = reactions.get(emoji, 0)
			label = f"{emoji} {count}" if count else emoji
			buttons.append(
				f'<button type="button" class="cwg-react-btn btn btn-xs btn-default" '
				f'data-emoji="{emoji}" data-idx="{msg_index}">{label}</button>'
			)
		return " ".join(buttons)

	def __call__(self, field, **kwargs) -> Markup:
		fid = kwargs.get("id", field.id)
		name = kwargs.get("name", field.name)
		post_url = self.post_url
		messages = self.messages

		messages_html_parts = []
		for idx, msg in enumerate(messages):
			author = msg.get("author", "Unknown")
			text = msg.get("text", "")
			created_at = msg.get("created_at", "")
			reactions = msg.get("reactions") or {}

			avatar = self._avatar(author)
			react_html = self._reaction_buttons(idx, reactions)
			# text rendered client-side; store escaped for JS template literal
			text_escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

			messages_html_parts.append(f"""
    <div class="cwg-message" id="{fid}_msg_{idx}">
      <div class="cwg-meta">
        {avatar}
        <span class="cwg-author">{author}</span>
        <span class="cwg-time" title="{created_at}">{created_at}</span>
      </div>
      <div class="cwg-body" data-raw="`{text_escaped}`"></div>
      <div class="cwg-reactions" id="{fid}_reactions_{idx}">{react_html}</div>
    </div>
""")

		messages_html = "\n".join(messages_html_parts)
		msg_count = len(messages)

		html = f"""
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js" as="script"/>
<script src="{self.markdown_cdn}"></script>
<script src="{self.DOMPURIFY_CDN}"></script>

<div class="conversation-widget" id="{fid}_widget">
  <style>
    .cwg-thread {{ max-height:480px; overflow-y:auto; border:1px solid #ddd;
                  border-radius:4px; padding:12px; background:#fafafa; }}
    .cwg-message {{ margin-bottom:14px; padding-bottom:10px;
                   border-bottom:1px solid #eee; }}
    .cwg-message:last-child {{ border-bottom:none; }}
    .cwg-meta {{ display:flex; align-items:center; gap:8px; margin-bottom:4px; }}
    .cwg-avatar {{ display:inline-flex; align-items:center; justify-content:center;
                  width:32px; height:32px; border-radius:50%; color:#fff;
                  font-weight:600; font-size:.75em; flex-shrink:0; }}
    .cwg-author {{ font-weight:600; font-size:.9em; }}
    .cwg-time {{ color:#888; font-size:.78em; }}
    .cwg-body {{ font-size:.92em; line-height:1.5; padding-left:40px; }}
    .cwg-body p:last-child {{ margin-bottom:0; }}
    .cwg-reactions {{ padding-left:40px; margin-top:4px; display:flex; gap:4px; flex-wrap:wrap; }}
    .cwg-react-btn {{ font-size:.85em !important; border-radius:999px !important;
                     padding:1px 8px !important; }}
    .cwg-react-btn.active {{ background:#e8f0fe; border-color:#4285f4; }}
    .cwg-compose {{ margin-top:12px; }}
    .cwg-compose textarea {{ width:100%; resize:vertical; }}
    .cwg-compose-actions {{ margin-top:6px; display:flex; justify-content:flex-end; }}
    .cwg-empty {{ color:#999; text-align:center; padding:20px; font-style:italic; }}
  </style>

  <div class="cwg-thread" id="{fid}_thread">
    {'<div class="cwg-empty">No messages yet. Be the first to comment.</div>' if not messages else messages_html}
  </div>

  <!-- new message composer -->
  <div class="cwg-compose">
    <textarea id="{fid}_compose" class="form-control" rows="3"
              placeholder="Write a comment (Markdown supported)…"></textarea>
    <div class="cwg-compose-actions">
      <button type="button" class="btn btn-primary btn-sm" id="{fid}_send">Send</button>
    </div>
  </div>

  <!-- hidden field: stores submitted text for server-side processing if needed -->
  <input type="hidden" id="{fid}" name="{name}" value=""/>
</div>

<script>
(function() {{
  var fid = {fid!r};
  var postUrl = {post_url!r};
  var msgCount = {msg_count};

  function renderMarkdown(raw) {{
    if (typeof marked === 'undefined') return raw;
    var html = marked.parse(raw || '');
    return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
  }}

  // render all existing message bodies
  document.querySelectorAll('#' + fid + '_widget .cwg-body').forEach(function(el) {{
    var raw = el.dataset.raw;
    // dataset.raw is the JS template-literal string stored in data-raw attr
    try {{ el.innerHTML = renderMarkdown(raw.replace(/^`|`$/g, '')); }}
    catch(e) {{ el.textContent = raw; }}
  }});

  // relative timestamps
  function relTime(isoStr) {{
    if (!isoStr) return '';
    try {{
      var d = new Date(isoStr), now = Date.now(), diff = now - d.getTime();
      if (diff < 60000) return 'just now';
      if (diff < 3600000) return Math.floor(diff/60000) + 'm ago';
      if (diff < 86400000) return Math.floor(diff/3600000) + 'h ago';
      return Math.floor(diff/86400000) + 'd ago';
    }} catch(e) {{ return isoStr; }}
  }}
  document.querySelectorAll('#' + fid + '_widget .cwg-time').forEach(function(el) {{
    el.textContent = relTime(el.getAttribute('title'));
  }});

  // reaction buttons
  document.getElementById(fid + '_widget').addEventListener('click', function(e) {{
    var btn = e.target.closest('.cwg-react-btn');
    if (!btn) return;
    var emoji = btn.dataset.emoji;
    var idx = btn.dataset.idx;
    btn.classList.toggle('active');
    // optimistic count update
    var cur = btn.textContent.trim();
    var parts = cur.split(' ');
    var count = parts.length > 1 ? parseInt(parts[1], 10) : 0;
    count = btn.classList.contains('active') ? count + 1 : Math.max(0, count - 1);
    btn.textContent = count > 0 ? (emoji + ' ' + count) : emoji;
    if (postUrl) {{
      fetch(postUrl, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json', 'X-CSRFToken': (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || ''}},
        body: JSON.stringify({{action: 'react', emoji: emoji, message_index: parseInt(idx, 10)}}),
      }}).catch(function() {{}});
    }}
  }});

  // send new message
  document.getElementById(fid + '_send').addEventListener('click', function() {{
    var ta = document.getElementById(fid + '_compose');
    var text = ta.value.trim();
    if (!text) return;
    var hidden = document.getElementById(fid);
    hidden.value = text;

    if (postUrl) {{
      fetch(postUrl, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json', 'X-CSRFToken': (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || ''}},
        body: JSON.stringify({{action: 'message', text: text}}),
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        appendMessage(data.author || 'You', text, new Date().toISOString(), {{}}, msgCount++);
        ta.value = '';
        hidden.value = '';
        // clear "no messages" placeholder
        var empty = document.querySelector('#' + fid + '_thread .cwg-empty');
        if (empty) empty.remove();
      }})
      .catch(function() {{
        // fallback: append optimistically anyway
        appendMessage('You', text, new Date().toISOString(), {{}}, msgCount++);
        ta.value = '';
      }});
    }} else {{
      // no endpoint: just show in thread for preview
      appendMessage('You', text, new Date().toISOString(), {{}}, msgCount++);
      ta.value = '';
    }}
  }});

  function appendMessage(author, text, createdAt, reactions, idx) {{
    var initials = author.split(' ').slice(0,2).map(function(w){{return w[0].toUpperCase();}}).join('');
    var hue = author.split('').reduce(function(a,c){{return a+c.charCodeAt(0);}},0) % 360;
    var reactionBtns = {self.REACTION_EMOJIS!r}.map(function(e) {{
      return '<button type="button" class="cwg-react-btn btn btn-xs btn-default" data-emoji="'+e+'" data-idx="'+idx+'">'+e+'</button>';
    }}).join(' ');
    var div = document.createElement('div');
    div.className = 'cwg-message';
    div.id = fid + '_msg_' + idx;
    div.innerHTML = [
      '<div class="cwg-meta">',
        '<span class="cwg-avatar" style="background:hsl('+hue+',55%,48%);">'+initials+'</span>',
        '<span class="cwg-author">'+author+'</span>',
        '<span class="cwg-time" title="'+createdAt+'">just now</span>',
      '</div>',
      '<div class="cwg-body">'+renderMarkdown(text)+'</div>',
      '<div class="cwg-reactions" id="'+fid+'_reactions_'+idx+'">'+reactionBtns+'</div>',
    ].join('');
    var thread = document.getElementById(fid + '_thread');
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
  }}
}})();
</script>
"""
		return Markup(html)
