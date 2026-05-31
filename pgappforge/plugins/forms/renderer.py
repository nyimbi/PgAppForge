"""Form → HTML renderer for public form submission."""
from __future__ import annotations
import json


FIELD_TEMPLATES: dict[str, str] = {
	"text": '<input type="text" name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" value="{value}">',
	"email": '<input type="email" name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" value="{value}">',
	"number": '<input type="number" name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" value="{value}">',
	"textarea": '<textarea name="{id}" id="{id}" placeholder="{placeholder}" {required} class="form-control" rows="4">{value}</textarea>',
	"date": '<input type="date" name="{id}" id="{id}" {required} class="form-control" value="{value}">',
	"select": '<select name="{id}" id="{id}" {required} class="form-control">{options}</select>',
	"checkbox": '<div class="form-check">{options}</div>',
	"radio": '<div>{options}</div>',
	"file": '<input type="file" name="{id}" id="{id}" {required} class="form-control">',
	"hidden": '<input type="hidden" name="{id}" id="{id}" value="{value}">',
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
.field-label .required-star{{color:#dc3545;}}
.step-progress{{display:flex;gap:6px;margin-bottom:24px;}}
.step-dot{{height:8px;flex:1;border-radius:4px;background:#dee2e6;}}
.step-dot.active{{background:#0d6efd;}}
.step-dot.done{{background:#198754;}}
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
// Conditional logic
const conditions = {conditions_json};
function evalConditions(){{
  conditions.forEach(c=>{{
    const target=document.getElementById('field_'+c.target_id);
    if(!target) return;
    const src=document.querySelector('[name="'+c.field_id+'"]');
    if(!src) return;
    const val=src.value;
    const match=(c.op==='='&&val===c.value)||(c.op==='!='&&val!==c.value)||
      (c.op==='>'&&parseFloat(val)>parseFloat(c.value))||
      (c.op==='<'&&parseFloat(val)<parseFloat(c.value))||
      (c.op==='contains'&&val.includes(c.value));
    target.style.display=(c.action==='show')?( match?'':'none'):(match?'none':'');
  }});
}}
document.querySelectorAll('input,select,textarea').forEach(el=>el.addEventListener('change',evalConditions));
evalConditions();
</script>
</body></html>"""


def render_form(form_def: dict, token: str, csrf_token: str = "", values: dict | None = None) -> str:
	"""Render a form definition to HTML for public submission."""
	values = values or {}
	settings = form_def.get("settings", {})
	title = settings.get("title", "Form")
	description = settings.get("description", "")
	submit_label = settings.get("submit_label", "Submit")
	conditions = form_def.get("conditions", [])
	fields_html_parts = []
	for field in form_def.get("fields", []):
		fid = field.get("id", "")
		ftype = field.get("type", "text")
		label = field.get("label", fid)
		required = "required" if field.get("required") else ""
		placeholder = field.get("placeholder", "")
		value = values.get(fid, field.get("default", ""))
		# Options for select/radio/checkbox
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
					options_html += (f'<div class="form-check"><input class="form-check-input" '
						f'type="radio" name="{fid}" value="{val}" {chk}>'
						f'<label class="form-check-label">{lbl}</label></div>')
				elif ftype == "checkbox":
					chk = "checked" if val in (value if isinstance(value, list) else []) else ""
					options_html += (f'<div class="form-check"><input class="form-check-input" '
						f'type="checkbox" name="{fid}[]" value="{val}" {chk}>'
						f'<label class="form-check-label">{lbl}</label></div>')
		tpl = FIELD_TEMPLATES.get(ftype, FIELD_TEMPLATES["text"])
		field_html = tpl.format(
			id=fid, placeholder=placeholder, required=required,
			value=value, options=options_html,
		)
		req_star = '<span class="required-star">*</span>' if required else ""
		fields_html_parts.append(
			f'<div class="field-group" id="field_{fid}">'
			f'<div class="field-label">{label} {req_star}</div>'
			f'{field_html}</div>'
		)
	return FORM_WRAPPER.format(
		title=title, description=description, token=token,
		csrf_token=csrf_token, submit_label=submit_label,
		fields_html="".join(fields_html_parts),
		conditions_json=json.dumps(conditions, default=str),
	)
