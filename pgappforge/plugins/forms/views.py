"""Form Builder views."""
from __future__ import annotations
import json
import re
import secrets
import logging
from flask import abort, request, jsonify, Response
from flask_login import current_user
from pgappforge import BaseView, expose, has_access

log = logging.getLogger(__name__)

_BUILDER_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Form Builder</title>
<style>
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e0e0e0;margin:0;display:flex;flex-direction:column;height:100vh;}
#tb{background:#1a1d2e;padding:10px 16px;display:flex;gap:8px;align-items:center;border-bottom:1px solid #2e3250;}
#tb h1{font-size:1rem;color:#7c83ff;margin:0;margin-right:16px;}
.btn{background:#1e2140;color:#b0b8ff;border:1px solid #3a3f6e;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:0.8rem;}
.btn:hover{background:#2a2f5a;}
#main{display:flex;flex:1;overflow:hidden;}
#palette{width:200px;background:#13162a;border-right:1px solid #2e3250;padding:12px;overflow-y:auto;}
#palette h3{font-size:0.8rem;color:#7c83ff;margin-bottom:8px;}
.field-chip{background:#1e2140;border:1px solid #3a3f6e;border-radius:6px;padding:7px 10px;margin-bottom:6px;cursor:grab;font-size:0.8rem;display:flex;align-items:center;gap:6px;}
.field-chip:hover{background:#2a2f5a;}
#canvas{flex:1;padding:24px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;}
#canvas-empty{color:#555;text-align:center;margin-top:80px;}
.field-card{background:#1a1d2e;border:1px solid #2e3250;border-radius:8px;padding:14px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;}
.field-card:hover{border-color:#7c83ff;}
.field-card.selected{border-color:#7c83ff;background:#1e2245;}
.field-card-label{font-size:0.85rem;font-weight:500;}
.field-card-type{font-size:0.75rem;color:#888;}
#config-panel{width:280px;background:#13162a;border-left:1px solid #2e3250;padding:16px;overflow-y:auto;}
#config-panel h3{color:#7c83ff;font-size:0.9rem;margin-bottom:12px;}
.config-row{margin-bottom:12px;}
.config-label{font-size:0.75rem;color:#888;margin-bottom:3px;}
.config-input{width:100%;background:#0f1117;border:1px solid #3a3f6e;color:#e0e0e0;padding:5px 8px;border-radius:4px;font-size:0.82rem;box-sizing:border-box;}
#forms-list{padding:20px;}
.form-row{background:#1a1d2e;border:1px solid #2e3250;border-radius:8px;padding:14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;}
</style></head>
<body>
<div id="tb">
<h1>Form Builder</h1>
<button class="btn" onclick="showBuilder()">+ New Form</button>
<button class="btn" id="btn-save" style="display:none" onclick="saveForm()">Save</button>
<button class="btn" id="btn-publish" style="display:none" onclick="publishForm()">Publish</button>
<button class="btn" id="btn-share" style="display:none" onclick="getShareLink()">Share Link</button>
<button class="btn" onclick="showList()">All Forms</button>
</div>
<div id="forms-list">
<h2 style="color:#7c83ff">My Forms</h2>
<div id="form-rows">Loading...</div>
</div>
<div id="builder" style="display:none;flex:1;flex-direction:row">
<div id="palette">
<h3>FIELDS</h3>
<div class="field-chip" draggable="true" data-type="text">&#128221; Text</div>
<div class="field-chip" draggable="true" data-type="textarea">&#128196; Text Area</div>
<div class="field-chip" draggable="true" data-type="email">&#128231; Email</div>
<div class="field-chip" draggable="true" data-type="number">&#128290; Number</div>
<div class="field-chip" draggable="true" data-type="date">&#128197; Date</div>
<div class="field-chip" draggable="true" data-type="select">&#9660; Dropdown</div>
<div class="field-chip" draggable="true" data-type="radio">&#9673; Radio</div>
<div class="field-chip" draggable="true" data-type="checkbox">&#9745; Checkboxes</div>
<div class="field-chip" draggable="true" data-type="file">&#128206; File Upload</div>
<div class="field-chip" draggable="true" data-type="hidden">&#128065; Hidden</div>
<h3 style="margin-top:12px">STRUCTURE</h3>
<div class="field-chip" draggable="true" data-type="page_break">&#128214; Page Break</div>
<div class="field-chip" draggable="true" data-type="section">&#128204; Section</div>
</div>
<div id="canvas" ondrop="onDrop(event)" ondragover="event.preventDefault()">
<div id="canvas-empty">Drag fields here to build your form</div>
</div>
<div id="config-panel">
<h3>Field Settings</h3>
<div id="no-selection" style="color:#555;font-size:0.8rem">Select a field to configure</div>
<div id="config-form" style="display:none">
<div class="config-row"><div class="config-label">Label</div><input class="config-input" id="cfg-label" oninput="updateSelected()"></div>
<div class="config-row"><div class="config-label">Placeholder</div><input class="config-input" id="cfg-placeholder" oninput="updateSelected()"></div>
<div class="config-row"><div class="config-label">Required</div><input type="checkbox" id="cfg-required" onchange="updateSelected()"></div>
<div class="config-row"><div class="config-label">Help text</div><input class="config-input" id="cfg-help" oninput="updateSelected()"></div>
<div id="options-section" style="display:none">
<div class="config-label">Options (one per line)</div>
<textarea class="config-input" id="cfg-options" rows="5" oninput="updateSelected()"></textarea>
</div>
<div style="margin-top:14px">
<button class="btn" style="color:#ef5350" onclick="removeSelected()">Remove Field</button>
</div>
</div>
</div>
</div>
<script>
let fields=[], selectedIdx=-1, formId=null;
function uid(){return 'f_'+Math.random().toString(36).slice(2,10);}
function showBuilder(id,def){
  document.getElementById('forms-list').style.display='none';
  document.getElementById('builder').style.display='flex';
  ['btn-save','btn-publish','btn-share'].forEach(b=>document.getElementById(b).style.display='');
  if(def){fields=[...def.fields||[]];formId=id;}else{fields=[];formId=null;}
  renderCanvas();
}
function showList(){
  document.getElementById('builder').style.display='none';
  document.getElementById('forms-list').style.display='block';
  ['btn-save','btn-publish','btn-share'].forEach(b=>document.getElementById(b).style.display='none');
  loadForms();
}
function onDrop(e){
  e.preventDefault();
  const type=e.dataTransfer.getData('type')||'text';
  fields.push({id:uid(),type,label:'New '+type,required:false,placeholder:'',options:[]});
  renderCanvas();
}
document.querySelectorAll('.field-chip').forEach(c=>{
  c.addEventListener('dragstart',e=>e.dataTransfer.setData('type',c.dataset.type));
});
function renderCanvas(){
  const cv=document.getElementById('canvas');
  cv.innerHTML=fields.length?'':'<div id="canvas-empty">Drag fields here to build your form</div>';
  fields.forEach((f,i)=>{
    const d=document.createElement('div');
    d.className='field-card'+(i===selectedIdx?' selected':'');
    d.innerHTML='<div><div class="field-card-label">'+f.label+'</div><div class="field-card-type">'+f.type+'</div></div>';
    d.onclick=()=>selectField(i);
    cv.appendChild(d);
  });
}
function selectField(i){
  selectedIdx=i;const f=fields[i];
  document.getElementById('no-selection').style.display='none';
  document.getElementById('config-form').style.display='block';
  document.getElementById('cfg-label').value=f.label||'';
  document.getElementById('cfg-placeholder').value=f.placeholder||'';
  document.getElementById('cfg-required').checked=!!f.required;
  document.getElementById('cfg-help').value=f.help||'';
  const hasOpts=['select','radio','checkbox'].includes(f.type);
  document.getElementById('options-section').style.display=hasOpts?'block':'none';
  document.getElementById('cfg-options').value=(f.options||[]).map(o=>o.label||o.value||o).join('\\n');
  renderCanvas();
}
function updateSelected(){
  if(selectedIdx<0) return;
  const f=fields[selectedIdx];
  f.label=document.getElementById('cfg-label').value;
  f.placeholder=document.getElementById('cfg-placeholder').value;
  f.required=document.getElementById('cfg-required').checked;
  f.help=document.getElementById('cfg-help').value;
  const optsRaw=document.getElementById('cfg-options').value.split('\\n').filter(Boolean);
  f.options=optsRaw.map(o=>({label:o,value:o}));
  renderCanvas();
}
function removeSelected(){if(selectedIdx>=0){fields.splice(selectedIdx,1);selectedIdx=-1;renderCanvas();document.getElementById('config-form').style.display='none';document.getElementById('no-selection').style.display='block';}}
async function saveForm(){
  const title=prompt('Form title:','My Form');if(!title) return;
  const def={fields,steps:[],settings:{title,submit_label:'Submit'},conditions:[]};
  const res=await fetch('/form-builder/api/forms'+(formId?'/'+formId:''),{
    method:formId?'PUT':'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({title,definition:def})
  });
  const d=await res.json();formId=d.id;
  alert('Saved! ID: '+d.id);
}
async function publishForm(){
  if(!formId) return alert('Save first');
  const res=await fetch('/form-builder/api/forms/'+formId+'/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await res.json();alert('Published version '+d.version);
}
async function getShareLink(){
  if(!formId) return alert('Publish first');
  const res=await fetch('/form-builder/api/forms/'+formId+'/share',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await res.json();
  if(d.url) prompt('Public URL (copy this):',window.location.origin+d.url);
}
async function loadForms(){
  const res=await fetch('/form-builder/api/forms');
  const d=await res.json();
  document.getElementById('form-rows').innerHTML=d.forms.map(f=>
    '<div class="form-row"><div><b>'+f.title+'</b> <span style="color:#888;font-size:0.78rem">'+f.status+'</span></div>'+
    '<div style="display:flex;gap:6px">'+
    '<button class="btn" onclick=\'showBuilder('+f.id+','+JSON.stringify(f.definition)+')\'>Edit</button>'+
    '<a class="btn" href="/forms/public/'+f.id+'/preview" target="_blank">Preview</a>'+
    '</div></div>'
  ).join('')||'<p style="color:#666">No forms yet. Click + New Form.</p>';
}
showList();
</script></body></html>"""


class FormBuilderView(BaseView):
	route_base = "/form-builder"

	@expose("/")
	@has_access
	def index(self):
		return Response(_BUILDER_HTML, mimetype="text/html")

	@expose("/api/forms", methods=["GET"])
	@has_access
	def api_list_forms(self):
		from pgappforge.plugins.forms.models import Form
		from sqlalchemy import select, desc
		session = self.appbuilder.get_session
		forms = session.execute(
			select(Form).order_by(desc(Form.created_at)).limit(100)
		).scalars().all()
		return jsonify({"forms": [
			{"id": f.id, "title": f.title, "slug": f.slug,
			 "status": f.status, "definition": f.definition,
			 "created_at": f.created_at.isoformat() if f.created_at else None}
			for f in forms
		]})

	@expose("/api/forms", methods=["POST"])
	@has_access
	def api_create_form(self):
		from pgappforge.plugins.forms.models import Form
		data = request.get_json(silent=True) or {}
		session = self.appbuilder.get_session
		slug = re.sub(r"[^a-z0-9]+", "-", (data.get("title", "form")).lower()).strip("-")
		form = Form(
			title=data.get("title", "Untitled"),
			slug=slug + "-" + secrets.token_hex(4),
			definition=data.get("definition", {}),
			created_by_id=getattr(current_user, "id", None),
		)
		session.add(form)
		session.commit()
		return jsonify({"id": form.id, "slug": form.slug})

	@expose("/api/forms/<int:form_id>", methods=["PUT"])
	@has_access
	def api_update_form(self, form_id: int):
		from pgappforge.plugins.forms.models import Form
		from sqlalchemy import select
		session = self.appbuilder.get_session
		form = session.execute(select(Form).where(Form.id == form_id)).scalar()
		if not form:
			return jsonify({"error": "Not found"}), 404
		data = request.get_json(silent=True) or {}
		if "title" in data:
			form.title = data["title"]
		if "definition" in data:
			form.definition = data["definition"]
		session.commit()
		return jsonify({"id": form.id})

	@expose("/api/forms/<int:form_id>/publish", methods=["POST"])
	@has_access
	def api_publish_form(self, form_id: int):
		from pgappforge.plugins.forms.models import Form, FormVersion
		from sqlalchemy import select, func
		session = self.appbuilder.get_session
		form = session.execute(select(Form).where(Form.id == form_id)).scalar()
		if not form:
			return jsonify({"error": "Not found"}), 404
		max_ver = session.execute(
			select(func.max(FormVersion.version_number)).where(FormVersion.form_id == form_id)
		).scalar() or 0
		ver = FormVersion(
			form_id=form_id,
			version_number=max_ver + 1,
			definition=form.definition,
			published_by_id=getattr(current_user, "id", None),
		)
		form.status = "published"
		form.current_version_id = None  # updated after flush
		session.add(ver)
		session.flush()
		form.current_version_id = ver.id
		session.commit()
		return jsonify({"version": ver.version_number})

	@expose("/api/forms/<int:form_id>/share", methods=["POST"])
	@has_access
	def api_create_share(self, form_id: int):
		from pgappforge.plugins.forms.models import FormShareToken
		session = self.appbuilder.get_session
		token = secrets.token_urlsafe(32)
		share = FormShareToken(
			form_id=form_id,
			token=token,
			created_by_id=getattr(current_user, "id", None),
		)
		session.add(share)
		session.commit()
		return jsonify({"url": f"/forms/public/{token}", "token": token})


class PublicFormView(BaseView):
	"""Public (unauthenticated) form renderer and submission handler."""
	route_base = "/forms"

	@expose("/public/<string:token>")
	def public_form(self, token: str):
		from pgappforge.plugins.forms.models import Form, FormShareToken
		from sqlalchemy import select
		session = self.appbuilder.get_session
		share = session.execute(
			select(FormShareToken).where(FormShareToken.token == token)
		).scalar()
		if not share:
			abort(404)
		form = session.execute(
			select(Form).where(Form.id == share.form_id)
		).scalar()
		if not form or form.status != "published":
			return Response("<h1>This form is not available.</h1>", mimetype="text/html")
		from pgappforge.plugins.forms.renderer import render_form
		try:
			from flask_wtf.csrf import generate_csrf
			csrf = generate_csrf()
		except Exception:
			csrf = ""
		html = render_form(form.definition or {}, token, csrf_token=csrf)
		return Response(html, mimetype="text/html")

	@expose("/public/<string:token>/submit", methods=["POST"])
	def public_submit(self, token: str):
		from pgappforge.plugins.forms.models import Form, FormShareToken, FormSubmission
		from sqlalchemy import select
		session = self.appbuilder.get_session
		share = session.execute(
			select(FormShareToken).where(FormShareToken.token == token)
		).scalar()
		if not share:
			abort(404)
		form = session.execute(
			select(Form).where(Form.id == share.form_id)
		).scalar()
		if not form:
			abort(404)
		data = dict(request.form)
		submission = FormSubmission(
			form_id=share.form_id,
			version_id=form.current_version_id,
			data={k: (v[0] if len(v) == 1 else v) for k, v in data.items() if k != "csrf_token"},
			submitter_ip=request.remote_addr,
			submitter_ua=request.user_agent.string[:512],
		)
		share.submissions_used = (share.submissions_used or 0) + 1
		session.add(submission)
		session.commit()
		success_msg = form.definition.get("settings", {}).get(
			"success_message", "Thank you for your submission!"
		)
		return Response(f"<html><body><h2>{success_msg}</h2></body></html>", mimetype="text/html")
