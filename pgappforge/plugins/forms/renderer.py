"""Form → HTML renderer for public form submission.

Rendering priority per field type:
  1. Built-in FIELD_TEMPLATES (fast string format)
  2. Registry renderer (custom HTML template registered by a plugin)
  3. Fallback: text input with data-field-type + data-extra-config attributes
     (JS on the page can progressively enhance these)
"""
from __future__ import annotations
import json

# ── Built-in field templates ──────────────────────────────────────────────────
# {id}, {placeholder}, {required}, {value}, {options}, {extra} are substituted.
# Not all keys are used by every template — extras are ignored via ** expansion.

FIELD_TEMPLATES: dict[str, str] = {
	"text":      '<input type="text" name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" value="{value}">',
	"email":     '<input type="email" name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" value="{value}">',
	"phone":     '<input type="tel" name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" value="{value}">',
	"url":       '<input type="url" name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" value="{value}">',
	"number":    '<input type="number" name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" value="{value}">',
	"currency":  '<div class="input-group"><span class="input-group-text">{currency_sym}</span><input type="number" step="0.01" name="{id}" id="{id}" {required} class="form-control" value="{value}"></div>',
	"slider":    '<div><input type="range" name="{id}" id="{id}" min="{slider_min}" max="{slider_max}" step="{slider_step}" class="form-range" value="{value}" oninput="document.getElementById(\'{id}_disp\').textContent=this.value"><span id="{id}_disp" class="ms-2">{value}</span></div>',
	"textarea":  '<textarea name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" rows="{rows}">{value}</textarea>',
	"rich_text": '<textarea name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" rows="6" data-field-type="rich_text">{value}</textarea>',
	"date":      '<input type="date" name="{id}" id="{id}" {required} class="form-control" value="{value}">',
	"datetime":  '<input type="datetime-local" name="{id}" id="{id}" {required} class="form-control" value="{value}">',
	"time":      '<input type="time" name="{id}" id="{id}" {required} class="form-control" value="{value}">',
	"date_range":'<div class="row g-2"><div class="col"><input type="date" name="{id}_from" id="{id}_from" {required} class="form-control" placeholder="From"></div><div class="col"><input type="date" name="{id}_to" id="{id}_to" {required} class="form-control" placeholder="To"></div></div>',
	"select":    '<select name="{id}" id="{id}" {required} class="form-select">{options}</select>',
	"radio":     '<div class="pgaf-radio-group">{options}</div>',
	"checkbox":  '<div class="pgaf-checkbox-group">{options}</div>',
	"toggle":    '<div class="form-check form-switch"><input type="checkbox" name="{id}" id="{id}" class="form-check-input" value="1" {checked}></div>',
	"rating":    '<div class="pgaf-rating" data-max="{max_stars}" data-name="{id}"><input type="hidden" name="{id}" id="{id}" value="{value}">{stars_html}</div>',
	"file":      '<input type="file" name="{id}" id="{id}" {required} class="form-control">',
	"image":     '<input type="file" name="{id}" id="{id}" {required} accept="image/*" class="form-control">',
	"signature": '<div class="pgaf-signature-wrap"><canvas id="{id}_canvas" width="400" height="120" style="border:1px solid #dee2e6;border-radius:4px;cursor:crosshair;touch-action:none"></canvas><input type="hidden" name="{id}" id="{id}" value="{value}"><button type="button" class="btn btn-sm btn-outline-secondary mt-1" onclick="pgafClearSig(\'{id}\')">Clear</button></div>',
	"hidden":    '<input type="hidden" name="{id}" id="{id}" value="{value}">',
	"section":   '<div class="pgaf-section-header" style="border-bottom:2px solid #0d6efd;margin:24px 0 12px;padding-bottom:6px;font-weight:600;color:#212529">{label}</div>',
	"html_block":'<div class="pgaf-html-block">{html}</div>',
	"page_break":'<hr class="pgaf-page-break" style="border-top:2px dashed #dee2e6;margin:24px 0">',
	"formula":   '<input type="text" name="{id}" id="{id}" class="form-control" data-field-type="formula" data-expression="{expression}" value="{value}" readonly>',
}

_CURRENCY_SYMBOLS: dict[str, str] = {
	"USD": "$", "EUR": "€", "GBP": "£", "KES": "KSh", "ZAR": "R",
	"NGN": "₦", "JPY": "¥", "CAD": "CA$", "AUD": "A$",
}

PAGE_BREAK_HTML = '<div class="pgaf-page-break" data-step="{step}"></div>'

FORM_WRAPPER = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<style>
body{{background:#f8f9fa;padding:20px;}}
.form-card{{max-width:680px;margin:0 auto;background:#fff;border-radius:12px;padding:32px;box-shadow:0 2px 12px rgba(0,0,0,.1);}}
.form-title{{font-size:1.5rem;font-weight:600;color:#212529;margin-bottom:8px;}}
.form-desc{{color:#6c757d;margin-bottom:24px;}}
.field-group{{margin-bottom:18px;}}
.field-label{{font-weight:500;margin-bottom:4px;}}
.field-label .req{{color:#dc3545;}}
.pgaf-rating span{{font-size:1.5rem;cursor:pointer;color:#dee2e6;}}
.pgaf-rating span.on{{color:#ffc107;}}
.btn-submit{{background:#0d6efd;color:#fff;border:none;padding:10px 28px;border-radius:8px;font-size:1rem;cursor:pointer;}}
.btn-submit:hover{{background:#0b5ed7;}}
</style></head>
<body>
<div class="form-card">
<div class="form-title">{title}</div>
<div class="form-desc">{description}</div>
<form method="POST" action="/forms/public/{token}/submit" enctype="multipart/form-data">
<input type="hidden" name="csrf_token" value="{csrf_token}">
{fields_html}
<div style="margin-top:24px">
<button type="submit" class="btn-submit">{submit_label}</button>
</div>
</form>
</div>
<script>
// Conditional visibility
const _conds={conditions_json};
function _evalConds(){{
  _conds.forEach(c=>{{
    const t=document.getElementById('field_'+c.target_id);if(!t)return;
    const s=document.querySelector('[name="'+c.field_id+'"]');if(!s)return;
    const v=s.value;
    const ok=(c.op==='='&&v===c.value)||(c.op==='!='&&v!==c.value)||
      (c.op==='>'&&parseFloat(v)>parseFloat(c.value))||
      (c.op==='<'&&parseFloat(v)<parseFloat(c.value))||
      (c.op==='contains'&&v.includes(c.value));
    t.style.display=(c.action==='show')?(ok?'':'none'):(ok?'none':'');
  }});
}}
document.querySelectorAll('input,select,textarea').forEach(el=>el.addEventListener('change',_evalConds));
_evalConds();
// Rating stars
document.querySelectorAll('.pgaf-rating').forEach(r=>{{
  const inp=r.querySelector('input[type=hidden]');
  r.querySelectorAll('span').forEach((s,i)=>{{
    s.onmouseover=()=>r.querySelectorAll('span').forEach((x,j)=>x.className=j<=i?'on':'');
    s.onclick=()=>{{inp.value=i+1;r.querySelectorAll('span').forEach((x,j)=>x.className=j<=i?'on':'');}};
  }});
  r.onmouseleave=()=>{{const v=parseInt(inp.value||0);r.querySelectorAll('span').forEach((s,i)=>s.className=i<v?'on':'');}};
}});
// Signature pad
function pgafClearSig(id){{const c=document.getElementById(id+'_canvas');c.getContext('2d').clearRect(0,0,c.width,c.height);document.getElementById(id).value='';}}
document.querySelectorAll('canvas[id$="_canvas"]').forEach(cv=>{{
  let drawing=false;const ctx=cv.getContext('2d');ctx.strokeStyle='#212529';ctx.lineWidth=2;
  cv.onmousedown=e=>{{drawing=true;const r=cv.getBoundingClientRect();ctx.beginPath();ctx.moveTo(e.clientX-r.left,e.clientY-r.top);}};
  cv.onmousemove=e=>{{if(!drawing)return;const r=cv.getBoundingClientRect();ctx.lineTo(e.clientX-r.left,e.clientY-r.top);ctx.stroke();}};
  cv.onmouseup=()=>{{drawing=false;const id=cv.id.replace('_canvas','');document.getElementById(id).value=cv.toDataURL();}};
}});
</script>
</body></html>"""


def _render_field_html(field: dict, value: str, options_html: str) -> str:
	"""Render a single field to HTML.

	Priority: built-in template → registered renderer → fallback text input.
	"""
	ftype = field.get("type", "text")
	fid = field.get("id", "")
	placeholder = field.get("placeholder", "")
	label = field.get("label", fid)
	required = "required" if field.get("required") else ""
	extra = field.get("extra_config") or {}

	# Extra substitution values
	extras: dict = {
		"id": fid,
		"placeholder": placeholder,
		"required": required,
		"value": value,
		"options": options_html,
		"label": label,
		# type-specific
		"rows": str(extra.get("rows", field.get("rows", 4))),
		"currency_sym": _CURRENCY_SYMBOLS.get(extra.get("currency", field.get("currency", "USD")), "$"),
		"slider_min": str(extra.get("slider_min", field.get("slider_min", 0))),
		"slider_max": str(extra.get("slider_max", field.get("slider_max", 100))),
		"slider_step": str(extra.get("slider_step", field.get("slider_step", 1))),
		"max_stars": str(extra.get("max_stars", field.get("max_stars", 5))),
		"stars_html": "".join(f'<span>&#9733;</span>' for _ in range(int(extra.get("max_stars", field.get("max_stars", 5))))),
		"checked": "checked" if value in ("1", "true", True) else "",
		"html": extra.get("html", field.get("html", "")),
		"expression": extra.get("expression", field.get("expression", "")),
	}

	# 1. Built-in template
	tpl = FIELD_TEMPLATES.get(ftype)
	if tpl:
		try:
			return tpl.format_map(extras)
		except Exception:
			pass

	# 2. Registry renderer (custom plugin-provided template)
	try:
		from pgappforge.plugins.forms.registry import get_renderer
		renderer_tpl = get_renderer(ftype)
		if renderer_tpl:
			try:
				return renderer_tpl.format_map({**extras, "extra_json": json.dumps(extra)})
			except Exception:
				pass
	except ImportError:
		pass

	# 3. Fallback: generic text input, JS can progressively enhance via data-field-type
	return (
		f'<input type="text" name="{fid}" id="{fid}" '
		f'placeholder="{placeholder}" {required} '
		f'class="form-control" value="{value}" '
		f'data-field-type="{ftype}" '
		f"data-extra-config='{json.dumps(extra)}'>"
	)


def render_form(form_def: dict, token: str, csrf_token: str = "", values: dict | None = None) -> str:
	"""Render a form definition to HTML for public submission."""
	values = values or {}
	settings = form_def.get("settings", {})
	title = settings.get("title", "Form")
	description = settings.get("description", "")
	submit_label = settings.get("submit_label", "Submit")
	conditions = form_def.get("conditions", [])
	parts = []
	for field in form_def.get("fields", []):
		fid = field.get("id", "")
		ftype = field.get("type", "text")
		label = field.get("label", fid)
		required = "required" if field.get("required") else ""
		value = str(values.get(fid, field.get("default", "") or ""))
		options_html = ""
		if ftype in ("select", "radio", "checkbox"):
			for opt in field.get("options", []):
				lbl = opt.get("label", opt.get("value", ""))
				val = opt.get("value", "")
				if ftype == "select":
					sel = "selected" if value == val else ""
					options_html += f'<option value="{val}" {sel}>{lbl}</option>'
				elif ftype == "radio":
					chk = "checked" if value == val else ""
					options_html += (
						f'<div class="form-check"><input class="form-check-input" '
						f'type="radio" name="{fid}" value="{val}" {chk}>'
						f'<label class="form-check-label">{lbl}</label></div>'
					)
				elif ftype == "checkbox":
					chk = "checked" if val in (value if isinstance(value, list) else []) else ""
					options_html += (
						f'<div class="form-check"><input class="form-check-input" '
						f'type="checkbox" name="{fid}[]" value="{val}" {chk}>'
						f'<label class="form-check-label">{lbl}</label></div>'
					)
		field_html = _render_field_html(field, value, options_html)
		if ftype in ("section", "html_block", "page_break"):
			parts.append(f'<div id="field_{fid}">{field_html}</div>')
		else:
			req_star = '<span class="req">*</span>' if required else ""
			parts.append(
				f'<div class="field-group" id="field_{fid}">'
				f'<div class="field-label">{label} {req_star}</div>'
				f'{field_html}</div>'
			)
	return FORM_WRAPPER.format(
		title=title, description=description, token=token,
		csrf_token=csrf_token, submit_label=submit_label,
		fields_html="".join(parts),
		conditions_json=json.dumps(conditions, default=str),
	)
