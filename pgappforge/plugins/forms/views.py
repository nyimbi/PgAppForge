"""Form Builder views.

FormBuilderView: drag-and-drop designer with full 26-type widget palette,
type-specific config panels, table integration (FK pickers, auto-save to model),
submissions viewer, and form-level security.

PublicFormView: unauthenticated form renderer and submission handler with
share-token enforcement (expiry, max_submissions) and target_model auto-save.
"""
from __future__ import annotations
import json
import re
import secrets
import logging
from datetime import datetime, timezone
from flask import abort, current_app, request, jsonify, Response
from flask_login import current_user
from pgappforge import BaseView, expose, has_access

log = logging.getLogger(__name__)


def _resolve_model_cls(name: str):
	"""Resolve a SQLAlchemy model class by table name or class name."""
	from pgappforge import Model
	seen: set = set()
	def _walk(cls):
		if cls in seen:
			return None
		seen.add(cls)
		if (getattr(cls, "__tablename__", "") == name or cls.__name__ == name):
			if hasattr(cls, "__table__"):
				return cls
		for sub in cls.__subclasses__():
			result = _walk(sub)
			if result is not None:
				return result
		return None
	return _walk(Model)

# ─── Builder SPA ─────────────────────────────────────────────────────────────

_BUILDER_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Form Builder</title>
<style>
*{box-sizing:border-box;}
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e0e0e0;margin:0;display:flex;flex-direction:column;height:100vh;}
#tb{background:#1a1d2e;padding:8px 14px;display:flex;gap:5px;align-items:center;border-bottom:1px solid #2e3250;flex-shrink:0;}
#tb h1{font-size:0.92rem;color:#7c83ff;margin:0 10px 0 0;}
.btn{background:#1e2140;color:#b0b8ff;border:1px solid #3a3f6e;padding:4px 10px;border-radius:5px;cursor:pointer;font-size:0.78rem;}
.btn:hover{background:#252a4a;}.btn.pri{background:#3a3f6e;}
.sep{width:1px;height:18px;background:#2e3250;margin:0 3px;}
#save-st{font-size:0.7rem;color:#555;margin-left:6px;}
/* views */
.view{display:none;flex:1;overflow:hidden;}
.view.on{display:flex;}
.view.scroll{overflow-y:auto;}
#v-list{flex-direction:column;padding:20px;}
#v-list h2{color:#7c83ff;font-size:1rem;margin-bottom:14px;}
.frow{background:#1a1d2e;border:1px solid #2e3250;border-radius:7px;padding:11px 14px;margin-bottom:7px;display:flex;justify-content:space-between;align-items:center;}
.frow-meta{font-size:0.72rem;color:#888;margin-top:2px;}
/* builder 3-panel */
#v-build{flex-direction:row;overflow:hidden;}
#palette{width:186px;background:#13162a;border-right:1px solid #2e3250;overflow-y:auto;padding:9px 7px;flex-shrink:0;}
.pg{font-size:0.66rem;font-weight:700;color:#7c83ff;letter-spacing:.06em;margin:9px 0 4px 2px;}
.pg:first-child{margin-top:0;}
.chip{background:#1e2140;border:1px solid #2e3250;border-radius:5px;padding:5px 7px;margin-bottom:3px;cursor:grab;font-size:0.77rem;display:flex;align-items:center;gap:5px;user-select:none;}
.chip:hover{background:#252a4a;border-color:#5a60a0;}
#canvas{flex:1;padding:18px;overflow-y:auto;background:#0f1117;display:flex;flex-direction:column;gap:5px;min-height:0;}
#cv-empty{color:#3a3f6e;text-align:center;margin-top:80px;font-size:0.88rem;}
.fcard{background:#1a1d2e;border:1px solid #2e3250;border-radius:7px;padding:10px 12px;display:flex;justify-content:space-between;align-items:center;}
.fcard:hover{border-color:#5a60a0;}.fcard.sel{border-color:#7c83ff;background:#1e2245;}
.fc-lbl{font-size:0.83rem;font-weight:500;}.fc-type{font-size:0.7rem;color:#888;margin-top:1px;}
.fc-map{font-size:0.67rem;color:#4caf50;}
.fc-acts{display:flex;gap:3px;}
.fc-btn{background:#0f1117;border:1px solid #2e3250;color:#666;border-radius:3px;padding:1px 5px;cursor:pointer;font-size:0.7rem;}
#cfg{width:268px;background:#13162a;border-left:1px solid #2e3250;padding:12px 13px;overflow-y:auto;flex-shrink:0;}
#cfg h3{color:#7c83ff;font-size:0.83rem;margin:0 0 10px;}
.cr{margin-bottom:9px;}.cl{font-size:0.7rem;color:#888;margin-bottom:2px;}
.ci{width:100%;background:#0f1117;border:1px solid #3a3f6e;color:#e0e0e0;padding:4px 7px;border-radius:4px;font-size:0.79rem;}
.ci:focus{outline:none;border-color:#7c83ff;}
.csec{border-top:1px solid #1e2245;margin-top:10px;padding-top:9px;}
.csh{font-size:0.69rem;color:#7c83ff;font-weight:700;letter-spacing:.05em;margin-bottom:7px;}
/* settings */
#v-set{flex-direction:column;padding:22px;max-width:660px;}
#v-set h2{color:#7c83ff;font-size:0.95rem;margin-bottom:16px;}
#v-set h3{color:#7c83ff;font-size:0.82rem;margin:20px 0 10px;}
.sr{margin-bottom:12px;}.sl{font-size:0.79rem;color:#888;margin-bottom:3px;}
.si{width:100%;background:#1a1d2e;border:1px solid #3a3f6e;color:#e0e0e0;padding:6px 9px;border-radius:5px;font-size:0.8rem;}
#map-tbl{width:100%;border-collapse:collapse;font-size:0.78rem;margin-top:6px;}
#map-tbl th{background:#1a1d2e;color:#7c83ff;padding:5px 9px;text-align:left;}
#map-tbl td{padding:4px 7px;border-bottom:1px solid #1a1d2e;}
/* submissions */
#v-subs{flex-direction:column;padding:20px;}
#v-subs h2{color:#7c83ff;font-size:0.95rem;margin-bottom:14px;}
.subr{background:#1a1d2e;border:1px solid #2e3250;border-radius:6px;padding:9px 12px;margin-bottom:5px;font-size:0.78rem;}
.subm{color:#888;font-size:0.7rem;margin-bottom:3px;}
.subd{font-family:monospace;font-size:0.73rem;color:#b0b8ff;white-space:pre-wrap;word-break:break-all;max-height:120px;overflow:auto;}
</style></head>
<body>
<div id="tb">
  <h1>&#127912; Form Builder</h1>
  <button class="btn" onclick="doNew()">+ New Form</button>
  <div class="sep"></div>
  <button class="btn pri" id="b-save" style="display:none" onclick="saveForm()">Save</button>
  <button class="btn" id="b-pub" style="display:none" onclick="publishForm()">Publish</button>
  <button class="btn" id="b-share" style="display:none" onclick="shareForm()">Share</button>
  <button class="btn" id="b-set" style="display:none" onclick="showV('set')">&#9881; Settings</button>
  <button class="btn" id="b-subs" style="display:none" onclick="showSubs()">Submissions</button>
  <div class="sep"></div>
  <button class="btn" onclick="showV('list')">All Forms</button>
  <span id="save-st"></span>
</div>

<!-- LIST -->
<div id="v-list" class="view scroll on" style="flex-direction:column">
  <div style="padding:20px">
    <h2 style="color:#7c83ff;font-size:1rem;margin-bottom:14px">My Forms</h2>
    <div id="form-rows">Loading...</div>
  </div>
</div>

<!-- BUILDER -->
<div id="v-build" class="view" style="flex-direction:row">
  <div id="palette"></div>
  <div id="canvas" ondrop="onDrop(event)" ondragover="event.preventDefault()">
    <div id="cv-empty">Drop fields here to build your form</div>
  </div>
  <div id="cfg">
    <h3>Field Settings</h3>
    <div id="cfg-mt" style="color:#444;font-size:0.8rem">Select a field to configure</div>
    <div id="cfg-f" style="display:none">
      <div class="cr"><div class="cl">Label</div><input class="ci" id="ci-lbl" oninput="upd()"></div>
      <div class="cr"><div class="cl">Placeholder</div><input class="ci" id="ci-ph" oninput="upd()"></div>
      <div class="cr"><div class="cl">Help text</div><input class="ci" id="ci-help" oninput="upd()"></div>
      <div class="cr" style="display:flex;align-items:center;gap:7px">
        <input type="checkbox" id="ci-req" onchange="upd()">
        <label for="ci-req" style="font-size:0.79rem">Required</label>
      </div>
      <div class="cr"><div class="cl">Default value</div><input class="ci" id="ci-def" oninput="upd()"></div>
      <div class="cr" id="rw-mf" style="display:none">
        <div class="cl">Map to model field</div>
        <select class="ci" id="ci-mf" onchange="upd()"><option value="">-- none --</option></select>
      </div>

      <div class="csec" id="s-opts" style="display:none">
        <div class="csh">OPTIONS</div>
        <div class="cl">One per line &nbsp; (label or label:value)</div>
        <textarea class="ci" id="ci-opts" rows="5" oninput="upd()"></textarea>
        <div class="cr" style="margin-top:5px;display:flex;gap:6px;align-items:center">
          <input type="checkbox" id="ci-other" onchange="upd()">
          <label for="ci-other" style="font-size:0.77rem">Allow &ldquo;Other&rdquo; text entry</label>
        </div>
      </div>

      <div class="csec" id="s-fk" style="display:none">
        <div class="csh">RELATIONSHIP</div>
        <div class="cr"><div class="cl">Source table / model</div>
          <select class="ci" id="ci-fk-m" onchange="onFkMdl()"><option value="">-- select --</option></select>
        </div>
        <div class="cr"><div class="cl">Display column (shown to user)</div>
          <select class="ci" id="ci-fk-d" onchange="updFk()"><option value="">--</option></select>
        </div>
        <div class="cr"><div class="cl">Value column (stored as answer)</div>
          <select class="ci" id="ci-fk-s" onchange="updFk()"><option value="">id</option></select>
        </div>
        <div class="cr"><div class="cl">Min chars to trigger search</div>
          <input class="ci" type="number" id="ci-fk-mc" value="2" min="0" max="5" oninput="upd()">
        </div>
      </div>

      <!-- Custom config section — populated dynamically from registry config_schema -->
      <div class="csec" id="s-custom" style="display:none">
        <div class="csh" id="s-custom-title">CUSTOM OPTIONS</div>
        <div id="s-custom-body"></div>
      </div>

      <div style="margin-top:14px;display:flex;gap:5px;flex-wrap:wrap">
        <button class="btn" onclick="moveUp()">&#8593; Up</button>
        <button class="btn" onclick="moveDn()">&#8595; Down</button>
        <button class="btn" style="color:#ef5350;margin-left:auto" onclick="removeF()">Remove</button>
      </div>
    </div>
  </div>
</div>

<!-- SETTINGS -->
<div id="v-set" class="view scroll" style="flex-direction:column;padding:22px;max-width:660px">
  <h2 style="color:#7c83ff;font-size:0.95rem">&#9881; Form Settings</h2>
  <div class="sr"><div class="sl">Form title</div><input class="si" id="st-title" oninput="stUpd()"></div>
  <div class="sr"><div class="sl">Description (shown under title)</div><textarea class="si" id="st-desc" rows="2" oninput="stUpd()"></textarea></div>
  <div class="sr"><div class="sl">Submit button label</div><input class="si" id="st-sub" value="Submit" oninput="stUpd()"></div>
  <div class="sr"><div class="sl">Success message</div><input class="si" id="st-ok" oninput="stUpd()"></div>
  <div class="sr"><div class="sl">Redirect URL after submit (optional)</div><input class="si" id="st-redir" placeholder="https://..." oninput="stUpd()"></div>
  <h3 style="color:#7c83ff;font-size:0.82rem;margin:20px 0 8px">&#128204; Auto-save to Model</h3>
  <p style="font-size:0.8rem;color:#888;margin-bottom:10px">When set, each submission automatically creates a record in the target model.</p>
  <div class="sr"><div class="sl">Target model</div>
    <select class="si" id="st-mdl" onchange="onTgtMdl()"><option value="">-- none --</option></select>
  </div>
  <div id="map-wrap" style="display:none">
    <div class="sl" style="margin-bottom:5px">Field mapping (form field &#8594; model column)</div>
    <table id="map-tbl"><thead><tr><th>Form Field</th><th>Model Column</th></tr></thead><tbody id="map-body"></tbody></table>
  </div>
  <div style="margin-top:18px">
    <button class="btn pri" onclick="showV('build')">&#8592; Back to Canvas</button>
  </div>
</div>

<!-- SUBMISSIONS -->
<div id="v-subs" class="view scroll" style="flex-direction:column;padding:20px">
  <h2 style="color:#7c83ff;font-size:0.95rem">Submissions</h2>
  <div id="sub-list">Loading...</div>
</div>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let fields=[], sel=-1, formId=null;
let fs={title:'Untitled Form',description:'',submit_label:'Submit',
  success_message:'Thank you!',redirect_url:'',target_model:'',field_mapping:{}};
let mfCache={}, avModels=[];

// ── Palette — server-driven, supports registered custom field types ───────────
let PAL=[];

async function loadPalette(){
  try{
    const r=await fetch('/form-builder/api/field-types');
    const d=await r.json();
    PAL=d.groups||[];
    buildPalette();
  }catch(e){
    document.getElementById('palette').innerHTML='<div style="color:#ef5350;padding:8px;font-size:0.75rem">Failed to load field types</div>';
  }
}

function buildPalette(){
  const p=document.getElementById('palette');
  p.innerHTML='';
  PAL.forEach(g=>{
    const h=document.createElement('div');h.className='pg';h.innerHTML=g.group;p.appendChild(h);
    (g.fields||[]).forEach(fd=>{
      const c=document.createElement('div');c.className='chip';c.draggable=true;c.dataset.type=fd.type;
      c.title=fd.description||fd.label;
      c.innerHTML='<span style="font-size:0.73rem;width:16px;text-align:center">'+fd.icon+'</span>'+fd.label;
      c.addEventListener('dragstart',e=>e.dataTransfer.setData('type',fd.type));
      p.appendChild(c);
    });
  });
}

function findFieldSpec(type){
  for(const g of PAL){const f=(g.fields||[]).find(x=>x.type===type);if(f)return f;}
  return null;
}

// ── View routing ──────────────────────────────────────────────────────────────
function showV(v){
  document.querySelectorAll('.view').forEach(el=>{el.classList.remove('on');el.style.display='none';});
  const el=document.getElementById('v-'+v);
  el.style.display='flex';el.classList.add('on');
  ['b-save','b-pub','b-share','b-set','b-subs'].forEach(b=>{
    document.getElementById(b).style.display=['build','set','subs'].includes(v)?'':'none';});
  if(v==='list')loadForms();
  if(v==='set')initSet();
}
function showSubs(){showV('subs');loadSubs();}

// ── Canvas ────────────────────────────────────────────────────────────────────
function uid(){return 'f_'+Math.random().toString(36).slice(2,10);}
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function onDrop(e){
  e.preventDefault();
  const t=e.dataTransfer.getData('type')||'text';
  fields.push({id:uid(),type:t,label:t.replace('_',' ').replace(/\b./g,c=>c.toUpperCase()),
    required:false,placeholder:'',help:'',default:'',options:[],model_field:''});
  sel=fields.length-1;renderCanvas();renderCfg();
}

function renderCanvas(){
  const cv=document.getElementById('canvas');
  if(!fields.length){cv.innerHTML='<div id="cv-empty">Drop fields here to build your form</div>';return;}
  cv.innerHTML='';
  fields.forEach((f,i)=>{
    const d=document.createElement('div');d.className='fcard'+(i===sel?' sel':'');
    const mp=f.model_field?'<span class="fc-map">&#8594;'+esc(f.model_field)+'</span>':'';
    d.innerHTML='<div style="flex:1;cursor:pointer" onclick="selF('+i+')">'+
      '<div class="fc-lbl">'+esc(f.label)+'</div>'+
      '<div class="fc-type">'+f.type+' '+mp+'</div></div>'+
      '<div class="fc-acts">'+
      '<button class="fc-btn" onclick="mvUp('+i+')" title="Up">&#8593;</button>'+
      '<button class="fc-btn" onclick="mvDn('+i+')" title="Down">&#8595;</button>'+
      '<button class="fc-btn" style="color:#ef5350" onclick="rmF('+i+')" title="Remove">&#10005;</button>'+
      '</div>';
    cv.appendChild(d);
  });
}

// ── Config panel ──────────────────────────────────────────────────────────────
const OPTS_T=['select','radio','checkbox','toggle'];
const FK_T=['fk_lookup','m2n'];
const SEC_MAP={'s-opts':OPTS_T,'s-fk':FK_T};

function selF(i){sel=i;renderCanvas();renderCfg();}
function renderCfg(){
  const empty=document.getElementById('cfg-mt'),form=document.getElementById('cfg-f');
  if(sel<0||sel>=fields.length){empty.style.display='';form.style.display='none';return;}
  const f=fields[sel];empty.style.display='none';form.style.display='block';
  document.getElementById('ci-lbl').value=f.label||'';
  document.getElementById('ci-ph').value=f.placeholder||'';
  document.getElementById('ci-help').value=f.help||'';
  document.getElementById('ci-req').checked=!!f.required;
  document.getElementById('ci-def').value=f.default||'';
  // model field mapper
  const rwmf=document.getElementById('rw-mf'),mfs=document.getElementById('ci-mf');
  if(fs.target_model&&mfCache[fs.target_model]){
    rwmf.style.display='';
    const cols=mfCache[fs.target_model];
    mfs.innerHTML='<option value="">-- none --</option>'+
      cols.map(c=>'<option'+(f.model_field===c.name?' selected':'')+' value="'+c.name+'">'+c.name+'</option>').join('');
  }else rwmf.style.display='none';
  // show/hide type sections
  Object.entries(SEC_MAP).forEach(([id,types])=>
    document.getElementById(id).style.display=types.includes(f.type)?'':'none');
  if(OPTS_T.includes(f.type)){
    document.getElementById('ci-opts').value=(f.options||[]).map(o=>(o.label||'')+(o.value&&o.value!==o.label?':'+o.value:'')).join('\n');
    document.getElementById('ci-other').checked=!!f.allow_other;
  }
  if(FK_T.includes(f.type)) populateFk(f);
  renderCustomCfg(f);
}

// ── Custom config panel (populated from registry config_schema) ───────────────
function renderCustomCfg(f){
  const sec=document.getElementById('s-custom');
  const body=document.getElementById('s-custom-body');
  const spec=findFieldSpec(f.type);
  const schema=spec&&spec.config_schema&&Object.keys(spec.config_schema).length?spec.config_schema:null;
  if(!schema){sec.style.display='none';return;}
  document.getElementById('s-custom-title').textContent=(spec.label||'Custom').toUpperCase()+' OPTIONS';
  const extra=f.extra_config||{};
  body.innerHTML=Object.entries(schema).map(([key,cs])=>{
    const val=extra[key]!==undefined?extra[key]:(cs.default!==undefined?cs.default:'');
    const cid='cc-'+key;
    let inp;
    if(cs.type==='boolean'){
      inp='<div style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="'+cid+'" '+(val?'checked':'')+' onchange="updCustom()"><label for="'+cid+'" style="font-size:0.79rem">'+(cs.label||key)+'</label></div>';
      return '<div class="cr">'+inp+'</div>';
    }else if(cs.type==='select'){
      const opts=(cs.options||[]).map(o=>'<option'+(String(val)===o?' selected':'')+' value="'+o+'">'+o+'</option>').join('');
      inp='<select class="ci" id="'+cid+'" onchange="updCustom()">'+opts+'</select>';
    }else if(cs.type==='textarea'){
      inp='<textarea class="ci" id="'+cid+'" rows="3" oninput="updCustom()">'+val+'</textarea>';
    }else{
      inp='<input class="ci" type="'+(cs.type==='number'?'number':'text')+'" id="'+cid+'" value="'+val+'" oninput="updCustom()">';
    }
    return '<div class="cr"><div class="cl">'+(cs.label||key)+'</div>'+inp+'</div>';
  }).join('');
  sec.style.display='';
}

function updCustom(){
  if(sel<0)return;
  const f=fields[sel];const spec=findFieldSpec(f.type);
  if(!spec||!spec.config_schema)return;
  const extra={};
  Object.keys(spec.config_schema).forEach(key=>{
    const el=document.getElementById('cc-'+key);if(!el)return;
    extra[key]=el.type==='checkbox'?el.checked:el.value;
  });
  f.extra_config=extra;renderCanvas();
}

function upd(){
  if(sel<0)return;const f=fields[sel];
  f.label=document.getElementById('ci-lbl').value;
  f.placeholder=document.getElementById('ci-ph').value;
  f.help=document.getElementById('ci-help').value;
  f.required=document.getElementById('ci-req').checked;
  f.default=document.getElementById('ci-def').value;
  f.model_field=document.getElementById('ci-mf').value||'';
  if(OPTS_T.includes(f.type)){
    const raw=document.getElementById('ci-opts').value.split('\n').filter(Boolean);
    f.options=raw.map(o=>{const p=o.split(':');return{label:p[0].trim(),value:(p[1]||p[0]).trim()};});
    f.allow_other=document.getElementById('ci-other').checked;
  }
  renderCanvas();
}

// ── FK picker ─────────────────────────────────────────────────────────────────
async function populateFk(f){
  if(!avModels.length)await fetchModels();
  const ms=document.getElementById('ci-fk-m');
  ms.innerHTML='<option value="">-- select table --</option>'+avModels.map(m=>'<option'+(f.fk_model===m?' selected':'')+' value="'+m+'">'+m+'</option>').join('');
  if(f.fk_model)await populateFkCols(f.fk_model,f.fk_display||'',f.fk_store||'');
}

async function onFkMdl(){
  const m=document.getElementById('ci-fk-m').value;
  if(sel>=0){fields[sel].fk_model=m;fields[sel].fk_display='';fields[sel].fk_store='';}
  await populateFkCols(m,'','');
}

async function populateFkCols(model,disp,store){
  if(!model)return;
  if(!mfCache[model])await fetchFields(model);
  const cols=mfCache[model]||[];
  const opt='<option value="">--</option>'+cols.map(c=>'<option value="'+c.name+'">'+c.name+' ('+c.type+')</option>').join('');
  const ds=document.getElementById('ci-fk-d'),ss=document.getElementById('ci-fk-s');
  ds.innerHTML=opt;ss.innerHTML='<option value="">id (default)</option>'+cols.map(c=>'<option value="'+c.name+'">'+c.name+'</option>').join('');
  if(disp)ds.value=disp;if(store)ss.value=store;
}

function updFk(){
  if(sel<0)return;
  fields[sel].fk_display=document.getElementById('ci-fk-d').value;
  fields[sel].fk_store=document.getElementById('ci-fk-s').value;
  renderCanvas();
}

// ── Move / remove ─────────────────────────────────────────────────────────────
function mvUp(i){const idx=i??sel;if(idx<=0)return;[fields[idx-1],fields[idx]]=[fields[idx],fields[idx-1]];if(sel===idx)sel=idx-1;else if(sel===idx-1)sel=idx;renderCanvas();}
function mvDn(i){const idx=i??sel;if(idx>=fields.length-1)return;[fields[idx],fields[idx+1]]=[fields[idx+1],fields[idx]];if(sel===idx)sel=idx+1;else if(sel===idx+1)sel=idx;renderCanvas();}
function rmF(i){const idx=i??sel;fields.splice(idx,1);if(sel>=fields.length)sel=fields.length-1;renderCanvas();renderCfg();}
function moveUp(){mvUp();}function moveDn(){mvDn();}function removeF(){rmF();}

// ── Settings panel ────────────────────────────────────────────────────────────
function initSet(){
  document.getElementById('st-title').value=fs.title||'';
  document.getElementById('st-desc').value=fs.description||'';
  document.getElementById('st-sub').value=fs.submit_label||'Submit';
  document.getElementById('st-ok').value=fs.success_message||'Thank you!';
  document.getElementById('st-redir').value=fs.redirect_url||'';
  fetchModels().then(()=>{
    const ms=document.getElementById('st-mdl');
    ms.innerHTML='<option value="">-- none --</option>'+avModels.map(m=>'<option'+(fs.target_model===m?' selected':'')+' value="'+m+'">'+m+'</option>').join('');
    if(fs.target_model)onTgtMdl();
  });
}

function stUpd(){
  fs.title=document.getElementById('st-title').value;
  fs.description=document.getElementById('st-desc').value;
  fs.submit_label=document.getElementById('st-sub').value;
  fs.success_message=document.getElementById('st-ok').value;
  fs.redirect_url=document.getElementById('st-redir').value;
}

async function onTgtMdl(){
  const m=document.getElementById('st-mdl').value;fs.target_model=m;
  const wrap=document.getElementById('map-wrap');
  if(!m){wrap.style.display='none';return;}
  await fetchFields(m);
  const cols=mfCache[m]||[];
  const tbody=document.getElementById('map-body');
  tbody.innerHTML=fields.filter(f=>!['section','page_break','html_block'].includes(f.type)).map(f=>{
    const cur=fs.field_mapping[f.id]||'';
    return '<tr><td>'+esc(f.label)+'<br><span style="color:#555;font-size:0.68rem">'+f.type+'</span></td>'+
      '<td><select class="ci" style="padding:3px 6px" onchange="setMap(\''+f.id+'\',this.value)">'+
      '<option value="">-- skip --</option>'+cols.map(c=>'<option'+(cur===c.name?' selected':'')+' value="'+c.name+'">'+c.name+'</option>').join('')+
      '</select></td></tr>';
  }).join('');
  wrap.style.display='';
}

function setMap(fid,col){if(col)fs.field_mapping[fid]=col;else delete fs.field_mapping[fid];}

// ── Model/field API ───────────────────────────────────────────────────────────
async function fetchModels(){
  if(avModels.length)return;
  const r=await fetch('/form-builder/api/models');const d=await r.json();avModels=d.models||[];
}

async function fetchFields(model){
  if(mfCache[model])return;
  const r=await fetch('/form-builder/api/model-fields?model='+encodeURIComponent(model));
  const d=await r.json();mfCache[model]=d.fields||[];
  // Refresh model-field dropdown in config if active
  const mfs=document.getElementById('ci-mf');
  if(mfs&&fs.target_model===model){
    const cols=mfCache[model];const cur=sel>=0?fields[sel].model_field||'':'';
    mfs.innerHTML='<option value="">-- none --</option>'+cols.map(c=>'<option'+(cur===c.name?' selected':'')+' value="'+c.name+'">'+c.name+'</option>').join('');
    document.getElementById('rw-mf').style.display='';
  }
}

// ── Save / publish / share ────────────────────────────────────────────────────
function buildDef(){return{fields,settings:fs,conditions:[],steps:[]};}
function setSt(msg,ms=2000){const el=document.getElementById('save-st');el.textContent=msg;if(ms)setTimeout(()=>el.textContent='',ms);}

function doNew(){
  fields=[];sel=-1;formId=null;
  fs={title:'Untitled Form',description:'',submit_label:'Submit',success_message:'Thank you!',redirect_url:'',target_model:'',field_mapping:{}};
  avModels=[];mfCache={};
  showV('build');renderCanvas();renderCfg();
}

async function saveForm(){
  setSt('Saving...',0);
  const res=await fetch('/form-builder/api/forms'+(formId?'/'+formId:''),{
    method:formId?'PUT':'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({title:fs.title||'Untitled',definition:buildDef()})});
  const d=await res.json();
  if(d.id){formId=d.id;setSt('Saved &#10003;');}else setSt('Error: '+(d.error||'?'));
}

async function publishForm(){
  if(!formId)await saveForm();
  const r=await fetch('/form-builder/api/forms/'+formId+'/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await r.json();alert('Published v'+d.version);
}

async function shareForm(){
  if(!formId)await saveForm();
  const r=await fetch('/form-builder/api/forms/'+formId+'/share',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await r.json();
  if(d.url)prompt('Public URL (copy this):',location.origin+d.url);
}

// ── Submissions ───────────────────────────────────────────────────────────────
async function loadSubs(){
  const sl=document.getElementById('sub-list');
  if(!formId){sl.innerHTML='<p style="color:#555">Save the form first to see submissions.</p>';return;}
  sl.innerHTML='Loading...';
  const r=await fetch('/form-builder/api/forms/'+formId+'/submissions');
  const d=await r.json();
  sl.innerHTML=d.submissions&&d.submissions.length?
    d.submissions.map(s=>'<div class="subr"><div class="subm">#'+s.id+' &mdash; '+new Date(s.submitted_at).toLocaleString()+' &mdash; IP: '+s.submitter_ip+(s.score!=null?' &mdash; Score: '+s.score:'')+'</div><div class="subd">'+esc(JSON.stringify(s.data,null,2))+'</div></div>').join(''):
    '<p style="color:#555">No submissions yet.</p>';
}

// ── Form list ─────────────────────────────────────────────────────────────────
async function loadForms(){
  const r=await fetch('/form-builder/api/forms');const d=await r.json();
  document.getElementById('form-rows').innerHTML=d.forms.map(f=>
    '<div class="frow"><div>'+
    '<div style="font-weight:500">'+esc(f.title)+'</div>'+
    '<div class="frow-meta">'+f.status+' &mdash; '+new Date(f.created_at).toLocaleDateString()+'</div></div>'+
    '<div style="display:flex;gap:5px">'+
    '<button class="btn" onclick="loadEdit('+f.id+')">Edit</button>'+
    '<a class="btn" href="/forms/public/'+f.id+'/preview" target="_blank">Preview</a>'+
    '</div></div>'
  ).join('')||'<p style="color:#444">No forms yet.</p>';
}

async function loadEdit(id){
  const r=await fetch('/form-builder/api/forms/'+id);const d=await r.json();
  formId=id;fields=[...(d.definition?.fields||[])];
  fs=Object.assign({title:'',description:'',submit_label:'Submit',success_message:'Thank you!',redirect_url:'',target_model:'',field_mapping:{}},d.definition?.settings||{});
  sel=-1;showV('build');renderCanvas();renderCfg();
  // Pre-fetch model fields if target_model set
  if(fs.target_model)fetchFields(fs.target_model);
}

loadPalette();  // fetch built-in + registered types, then build palette chips
showV('list');
</script></body></html>"""


# ─── View classes ─────────────────────────────────────────────────────────────

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
			select(Form).order_by(desc(Form.created_at)).limit(200)
		).scalars().all()
		return jsonify({"forms": [
			{"id": f.id, "title": f.title, "slug": f.slug,
			 "status": f.status, "definition": f.definition,
			 "created_at": f.created_at.isoformat() if f.created_at else None}
			for f in forms
		]})

	@expose("/api/forms/<int:form_id>", methods=["GET"])
	@has_access
	def api_get_form(self, form_id: int):
		from pgappforge.plugins.forms.models import Form
		from sqlalchemy import select
		session = self.appbuilder.get_session
		form = session.execute(select(Form).where(Form.id == form_id)).scalar()
		if not form:
			return jsonify({"error": "Not found"}), 404
		return jsonify({
			"id": form.id, "title": form.title, "slug": form.slug,
			"status": form.status, "definition": form.definition,
			"created_at": form.created_at.isoformat() if form.created_at else None,
		})

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
		uid = getattr(current_user, "id", None)
		admin_role = current_app.config.get("AUTH_ROLE_ADMIN", "Admin")
		is_admin = any(
			r.name == admin_role for r in getattr(current_user, "roles", [])
		)
		if form.created_by_id and form.created_by_id != uid and not is_admin:
			abort(403)
		data = request.get_json(silent=True) or {}
		if "title" in data:
			form.title = data["title"]
		if "definition" in data:
			form.definition = data["definition"]
			# Sync title from settings if embedded
			embedded_title = data["definition"].get("settings", {}).get("title")
			if embedded_title:
				form.title = embedded_title
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

	@expose("/api/field-types")
	@has_access
	def api_field_types(self):
		"""Return the full palette: built-in groups merged with all registered custom types."""
		from pgappforge.plugins.forms.registry import get_palette_groups
		return jsonify({"groups": get_palette_groups()})

	@expose("/api/models")
	@has_access
	def api_list_models(self):
		"""Return list of application model table names available for FK fields."""
		try:
			from pgappforge import Model
			names = sorted(set(
				m.__tablename__
				for m in self._iter_model_classes()
				if not m.__tablename__.startswith("pgaf_") and not m.__tablename__.startswith("ab_")
			))
			return jsonify({"models": names})
		except Exception as exc:
			log.warning("api_list_models: %s", exc)
			return jsonify({"models": []})

	@expose("/api/model-fields")
	@has_access
	def api_model_fields(self):
		"""Return column metadata for a model (for FK pickers and field mapping)."""
		model_name = request.args.get("model", "")
		cls = self._resolve_model(model_name)
		if not cls:
			return jsonify({"fields": []})
		from sqlalchemy import inspect as sa_inspect
		fields_meta = []
		try:
			for col in sa_inspect(cls).columns:
				fields_meta.append({
					"name": col.key,
					"type": str(col.type).split("(")[0],
					"nullable": col.nullable,
					"is_fk": bool(col.foreign_keys),
				})
		except Exception as exc:
			log.warning("api_model_fields %s: %s", model_name, exc)
		return jsonify({"fields": fields_meta})

	@expose("/api/forms/<int:form_id>/submissions")
	@has_access
	def api_form_submissions(self, form_id: int):
		"""Return recent submissions for a form."""
		from pgappforge.plugins.forms.models import FormSubmission
		from sqlalchemy import select, desc
		session = self.appbuilder.get_session
		subs = session.execute(
			select(FormSubmission)
			.where(FormSubmission.form_id == form_id)
			.order_by(desc(FormSubmission.submitted_at))
			.limit(200)
		).scalars().all()
		return jsonify({"submissions": [
			{
				"id": s.id,
				"data": s.data,
				"score": float(s.score) if s.score is not None else None,
				"outcome": s.outcome,
				"submitter_ip": s.submitter_ip,
				"submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
			}
			for s in subs
		]})

	# ── helpers ──────────────────────────────────────────────────────────────

	def _resolve_model(self, name: str):
		return _resolve_model_cls(name)


class PublicFormView(BaseView):
	"""Unauthenticated form renderer and submission handler."""
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
		# Enforce expiry
		now = datetime.now(timezone.utc)
		if share.expires_at and share.expires_at.replace(tzinfo=timezone.utc) < now:
			return Response(
				"<html><body><h2>This form link has expired.</h2></body></html>",
				mimetype="text/html", status=410,
			)
		# Enforce submission cap
		if share.max_submissions and (share.submissions_used or 0) >= share.max_submissions:
			return Response(
				"<html><body><h2>This form has reached its submission limit.</h2></body></html>",
				mimetype="text/html", status=410,
			)
		form = session.execute(
			select(Form).where(Form.id == share.form_id)
		).scalar()
		if not form or form.status != "published":
			return Response(
				"<html><body><h2>This form is not available.</h2></body></html>",
				mimetype="text/html",
			)
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
		now = datetime.now(timezone.utc)
		if share.expires_at and share.expires_at.replace(tzinfo=timezone.utc) < now:
			return Response("<h2>This form link has expired.</h2>", mimetype="text/html", status=410)
		if share.max_submissions and (share.submissions_used or 0) >= share.max_submissions:
			return Response("<h2>Submission limit reached.</h2>", mimetype="text/html", status=410)
		form = session.execute(
			select(Form).where(Form.id == share.form_id)
		).scalar()
		if not form:
			abort(404)
		raw = dict(request.form)
		clean = {k: (v[0] if len(v) == 1 else v) for k, v in raw.items() if k != "csrf_token"}
		submission = FormSubmission(
			form_id=share.form_id,
			version_id=form.current_version_id,
			data=clean,
			submitter_ip=request.remote_addr,
			submitter_ua=request.user_agent.string[:512],
		)
		share.submissions_used = (share.submissions_used or 0) + 1
		session.add(submission)
		# Auto-save to target_model if configured
		settings = (form.definition or {}).get("settings", {})
		target = settings.get("target_model")
		mapping = settings.get("field_mapping", {})
		if target and mapping:
			model_cls = self._resolve_model(session, target)
			if model_cls:
				kwargs: dict = {}
				for field_id, col_name in mapping.items():
					if field_id in clean and col_name:
						kwargs[col_name] = clean[field_id]
				if kwargs:
					try:
						record = model_cls(**kwargs)
						session.add(record)
					except Exception as exc:
						log.warning("auto-save to %s failed: %s", target, exc)
		session.commit()
		success_msg = settings.get("success_message", "Thank you for your submission!")
		redirect_url = settings.get("redirect_url", "")
		if redirect_url:
			from flask import redirect as _redirect
			return _redirect(redirect_url)
		return Response(
			f"<html><body style='font-family:system-ui;padding:40px'><h2>{success_msg}</h2></body></html>",
			mimetype="text/html",
		)

	def _resolve_model(self, session, name: str):
		return _resolve_model_cls(name)
