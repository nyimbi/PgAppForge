"""Data Hub view — import/export UI."""
from __future__ import annotations
import csv
import io
import json
import logging
from flask import request, jsonify, Response
from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)

_HUB_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Data Hub</title>
<style>
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e0e0e0;margin:0;}
#toolbar{background:#1a1d2e;padding:12px 20px;border-bottom:1px solid #2e3250;display:flex;gap:10px;align-items:center;}
#toolbar h1{font-size:1rem;color:#7c83ff;margin:0;margin-right:20px;}
.tab{padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.82rem;background:#1e2140;color:#b0b8ff;border:1px solid #3a3f6e;}
.tab.active{background:#3a3f6e;color:#fff;}
#content{padding:24px;max-width:900px;margin:0 auto;}
.panel{display:none;} .panel.active{display:block;}
.upload-area{border:2px dashed #3a3f6e;border-radius:12px;padding:40px;text-align:center;cursor:pointer;color:#888;}
.upload-area:hover{border-color:#7c83ff;color:#b0b8ff;}
.mapping-table{width:100%;border-collapse:collapse;font-size:0.82rem;}
.mapping-table th,.mapping-table td{border:1px solid #2e3250;padding:8px 12px;}
.mapping-table th{background:#1a1d2e;color:#7c83ff;}
select,input{background:#1e2140;border:1px solid #3a3f6e;color:#e0e0e0;padding:5px 8px;border-radius:4px;font-size:0.82rem;}
.btn{background:#3a3f6e;color:#b0b8ff;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:0.82rem;}
.btn:hover{background:#4a4f8e;}
.progress-bar{height:8px;background:#1e2140;border-radius:4px;overflow:hidden;margin:8px 0;}
.progress-fill{height:100%;background:#7c83ff;transition:width 0.3s;}
.job-card{background:#1a1d2e;border:1px solid #2e3250;border-radius:8px;padding:14px;margin-bottom:10px;}
</style></head>
<body>
<div id="toolbar">
<h1>&#128229; Data Hub</h1>
<button class="tab active" onclick="showTab('import', event)">Import</button>
<button class="tab" onclick="showTab('export', event)">Export</button>
<button class="tab" onclick="showTab('history', event)">History</button>
</div>
<div id="content">
<div id="tab-import" class="panel active">
  <h2 style="color:#7c83ff">Import Data</h2>
  <div class="upload-area" id="drop-zone" onclick="document.getElementById('file-in').click()">
    <p>Drop CSV, Excel, JSON, NDJSON, or Parquet file here</p>
    <p style="font-size:0.78rem">Max 100 MB</p>
    <input type="file" id="file-in" style="display:none" accept=".csv,.xlsx,.xls,.json,.ndjson,.parquet">
  </div>
  <div id="mapping-section" style="display:none;margin-top:20px">
    <h3>Column Mapping</h3>
    <select id="model-select" onchange="loadMapping()"><option value="">Select model...</option></select>
    <div id="mapping-table-wrap" style="margin-top:12px"></div>
    <div style="margin-top:16px;display:flex;gap:8px">
      <button class="btn" onclick="runDryRun()">Preview (dry run)</button>
      <button class="btn" onclick="runImport()">Import</button>
    </div>
    <div id="import-result" style="margin-top:14px;font-size:0.82rem"></div>
  </div>
</div>
<div id="tab-export" class="panel">
  <h2 style="color:#7c83ff">Export Data</h2>
  <div style="display:flex;flex-direction:column;gap:12px;max-width:400px">
    <div><label>Model</label><br><input id="exp-model" placeholder="Model name" style="width:100%"></div>
    <div><label>Format</label><br>
    <select id="exp-format"><option>csv</option><option>xlsx</option><option>json</option><option>ndjson</option><option>parquet</option></select></div>
    <div><label>Max rows</label><br><input id="exp-maxrows" type="number" value="10000"></div>
    <button class="btn" onclick="runExport()">Export Now</button>
    <div id="exp-result"></div>
  </div>
</div>
<div id="tab-history" class="panel">
  <h2 style="color:#7c83ff">Import/Export History</h2>
  <div id="job-list">Loading...</div>
</div>
</div>
<script>
let uploadedData = null, parsedHeaders = [];
function showTab(t, e) {
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+t).classList.add('active');
  if(e && e.target) e.target.classList.add('active');
  if(t==='history') loadHistory();
}
document.getElementById('file-in').addEventListener('change', async function(e) {
  var f = e.target.files[0]; if(!f) return;
  var buf = await f.arrayBuffer();
  uploadedData = new Uint8Array(buf);
  parsedHeaders = await getHeaders(f.name, uploadedData);
  document.getElementById('mapping-section').style.display='block';
  await loadModels();
});
async function getHeaders(name, data) {
  if(name.endsWith('.csv')||name.endsWith('.txt')){
    var text=new TextDecoder().decode(data.slice(0,4096));
    return text.split('\\n')[0].split(',').map(function(h){return h.trim().replace(/"/g,'');});
  }
  return [];
}
async function loadModels() {
  var res=await fetch('/data-hub/api/models');
  var d=await res.json();
  var sel=document.getElementById('model-select');
  sel.innerHTML='<option value="">Select model...</option>'+d.models.map(function(m){return '<option>'+m+'</option>';}).join('');
}
async function loadMapping() {
  var model=document.getElementById('model-select').value;
  if(!model||!parsedHeaders.length) return;
  var res=await fetch('/data-hub/api/suggest-mapping?model='+encodeURIComponent(model)+'&cols='+encodeURIComponent(parsedHeaders.join(',')));
  var d=await res.json();
  var wrap=document.getElementById('mapping-table-wrap');
  wrap.innerHTML='<table class="mapping-table"><thead><tr><th>Upload Column</th><th>Map to Model Field</th><th>Match Score</th></tr></thead><tbody>'+
    parsedHeaders.map(function(col){
      var s=d.mapping[col]||{};
      return '<tr><td>'+col+'</td><td><select name="map_'+col+'">' +
        '<option value="">(skip)</option>' +
        d.fields.map(function(f){return '<option'+(s.model_field===f.name?' selected':'')+' value="'+f.name+'">'+f.name+'</option>';}).join('')+
        '</select></td><td style="color:'+(s.score>0.8?'#4caf50':s.score>0.5?'#ff9800':'#888')+'">'+((s.score||0)*100).toFixed(0)+'%</td></tr>';
    }).join('')+'</tbody></table>';
}
async function doImport(dryRun) {
  var modelVal = document.getElementById('model-select').value;
  var fileEl = document.getElementById('file-in');
  if(!uploadedData||!modelVal) { alert('Select model and file first'); return; }
  var mapping={};
  document.querySelectorAll('[name^="map_"]').forEach(function(sel){
    if(sel.value) mapping[sel.name.replace('map_','')] = sel.value;
  });
  var fd=new FormData();
  fd.append('file',new Blob([uploadedData]),fileEl.files[0].name);
  fd.append('model',modelVal);
  fd.append('mapping',JSON.stringify(mapping));
  fd.append('dry_run',dryRun?'1':'0');
  var res=await fetch('/data-hub/api/import',{method:'POST',body:fd});
  var d=await res.json();
  document.getElementById('import-result').innerHTML=
    '<div style="background:#1a1d2e;border-radius:8px;padding:14px">'+
    '<b>Job '+d.job_id+'</b> &mdash; Status: '+d.status+'<br>'+
    (d.preview?'Preview: '+JSON.stringify(d.preview):'')+'</div>';
}
function runImport() { doImport(false); }
function runDryRun() { doImport(true); }
async function runExport() {
  var model=document.getElementById('exp-model').value;
  var format=document.getElementById('exp-format').value;
  var maxrows=document.getElementById('exp-maxrows').value;
  var res=await fetch('/data-hub/api/export',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model:model,format:format,options:{max_rows:parseInt(maxrows)}})});
  var d=await res.json();
  document.getElementById('exp-result').innerHTML=d.download_url?
    '<a href="'+d.download_url+'" style="color:#7c83ff">Download '+format.toUpperCase()+'</a>':'Job started: '+d.job_id;
}
async function loadHistory() {
  var res=await fetch('/data-hub/api/jobs');
  var d=await res.json();
  document.getElementById('job-list').innerHTML=d.jobs.map(function(j){
    return '<div class="job-card">'+j.file_format.toUpperCase()+' '+j.model_name+' &mdash; '+j.status+
    ' ('+j.rows_inserted+' ins, '+j.rows_updated+' upd, '+j.rows_errored+' err) &mdash; '+
    new Date(j.created_at).toLocaleString()+'</div>';
  }).join('') || '<p style="color:#666">No jobs yet.</p>';
}
</script></body></html>"""


class DataHubView(BaseView):
	route_base = "/data-hub"

	@expose("/")
	@has_access
	def index(self):
		return Response(_HUB_HTML, mimetype="text/html")

	@expose("/api/models")
	@has_access
	def api_models(self):
		try:
			from pgappforge.models.sqla import Model
			names = [
				m.__tablename__ for m in Model.__subclasses__()
				if hasattr(m, "__tablename__") and not m.__tablename__.startswith("pgaf_")
			]
			return jsonify({"models": sorted(names)})
		except Exception as exc:
			return jsonify({"models": [], "error": str(exc)})

	@expose("/api/suggest-mapping")
	@has_access
	def api_suggest_mapping(self):
		from pgappforge.plugins.data_hub.mapping import suggest_column_mapping, get_model_fields_meta
		model_name = request.args.get("model", "")
		cols = [c.strip() for c in request.args.get("cols", "").split(",") if c.strip()]
		model_cls = self._resolve_model(model_name)
		if not model_cls:
			return jsonify({"error": f"Model {model_name} not found"}), 404
		fields = get_model_fields_meta(model_cls)
		mapping = suggest_column_mapping(cols, fields)
		return jsonify({"mapping": mapping, "fields": fields})

	@expose("/api/import", methods=["POST"])
	@has_access
	def api_import(self):
		from pgappforge.plugins.data_hub.models import ImportJob
		file = request.files.get("file")
		model_name = request.form.get("model", "")
		mapping = json.loads(request.form.get("mapping", "{}"))
		dry_run = request.form.get("dry_run", "0") == "1"
		if not file or not model_name:
			return jsonify({"error": "file and model required"}), 400
		ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "csv"
		session = self.appbuilder.get_session
		job = ImportJob(
			model_name=model_name,
			filename=file.filename,
			file_format=ext,
			status="pending",
			column_mapping=mapping,
			options={"dry_run": dry_run, "chunk_size": 500},
		)
		session.add(job)
		session.commit()
		if dry_run:
			content = file.read()
			from pgappforge.plugins.data_hub.importers import get_importer
			importer = get_importer(ext)
			preview = []
			if importer:
				for i, row in enumerate(importer(content)):
					if i >= 5:
						break
					preview.append(row)
			return jsonify({"job_id": job.id, "status": "dry_run", "preview": preview})
		return jsonify({"job_id": job.id, "status": "pending"})

	@expose("/api/export", methods=["POST"])
	@has_access
	def api_export(self):
		data = request.get_json(silent=True) or {}
		model_name = data.get("model", "")
		fmt = data.get("format", "csv")
		options = data.get("options", {})
		model_cls = self._resolve_model(model_name)
		if not model_cls:
			return jsonify({"error": f"Model {model_name} not found"}), 404
		session = self.appbuilder.get_session
		from sqlalchemy import select
		rows = session.execute(
			select(model_cls).limit(options.get("max_rows", 10000))
		).scalars().all()
		if fmt == "json":
			from sqlalchemy import inspect as sa_inspect
			def to_dict(r):
				mapper = sa_inspect(type(r))
				return {c.key: getattr(r, c.key) for c in mapper.columns}
			content = json.dumps([to_dict(r) for r in rows], default=str)
			return Response(
				content,
				mimetype="application/json",
				headers={"Content-Disposition": f"attachment; filename={model_name}.json"},
			)
		# CSV fallback
		buf = io.StringIO()
		if rows:
			from sqlalchemy import inspect as sa_inspect
			cols = [c.key for c in sa_inspect(type(rows[0])).columns]
			writer = csv.DictWriter(buf, fieldnames=cols)
			writer.writeheader()
			for r in rows:
				writer.writerow({c: getattr(r, c) for c in cols})
		return Response(
			buf.getvalue(),
			mimetype="text/csv",
			headers={"Content-Disposition": f"attachment; filename={model_name}.csv"},
		)

	@expose("/api/jobs")
	@has_access
	def api_jobs(self):
		from pgappforge.plugins.data_hub.models import ImportJob
		from sqlalchemy import select, desc
		session = self.appbuilder.get_session
		jobs = session.execute(
			select(ImportJob).order_by(desc(ImportJob.created_at)).limit(50)
		).scalars().all()
		return jsonify({"jobs": [
			{
				"id": j.id,
				"model_name": j.model_name,
				"filename": j.filename,
				"file_format": j.file_format,
				"status": j.status,
				"rows_inserted": j.rows_inserted,
				"rows_updated": j.rows_updated,
				"rows_errored": j.rows_errored,
				"created_at": j.created_at.isoformat() if j.created_at else None,
			}
			for j in jobs
		]})

	def _resolve_model(self, name: str):
		try:
			from pgappforge.models.sqla import Model
			for cls in Model.__subclasses__():
				if getattr(cls, "__tablename__", "") == name or cls.__name__ == name:
					return cls
		except Exception:
			pass
		return None
