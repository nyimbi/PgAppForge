"""
ReportForge Visual SQL Query Editor.

Provides:
  /reportforge/sql-editor/         — browser-based SQL query builder UI
  /reportforge/sql-editor/api/*    — REST API for schema, execute, save, list, AI

Security:
  - Only SELECT / WITH statements are permitted
  - Results capped at REPORTFORGE_QUERY_ROW_LIMIT (default 500)
  - Requires has_access decorator
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import sqlalchemy as sa
from flask import current_app, jsonify, request
from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)

_MAX_DEFAULT_ROWS = 500
_FORBIDDEN_RE = re.compile(
	r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b",
	re.IGNORECASE,
)

# ── Inline HTML for the editor UI ────────────────────────────────────────────

_EDITOR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ReportForge — SQL Editor</title>
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<link rel="stylesheet"
      href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
body { background:#f4f6fa; font-family:'Segoe UI',Arial,sans-serif; margin:0; }
.topbar { background:#0066cc; color:#fff; padding:12px 24px;
          display:flex; align-items:center; gap:14px; }
.topbar h1 { font-size:1.2rem; margin:0; font-weight:700; }
.panel { background:#fff; border-radius:8px;
         box-shadow:0 2px 8px rgba(0,0,0,.08); }
#schema-tree { height:calc(100vh - 100px); overflow-y:auto; font-size:13px; }
.stbl { cursor:pointer; padding:4px 8px; border-radius:4px; }
.stbl:hover { background:#e8f0ff; }
.stbl i { color:#0066cc; margin-right:6px; }
.scol { padding:2px 8px 2px 24px; font-size:12px; color:#555; cursor:pointer; }
.scol:hover { background:#f0f5ff; }
.scol .ct { color:#888; font-size:11px; margin-left:4px; }
#editor-pane { height:calc(100vh - 100px); display:flex; flex-direction:column; }
#sql-ta { flex:1; font-family:monospace; font-size:13px; resize:none;
          border:1px solid #ddd; border-radius:6px; padding:10px;
          background:#1e1e2e; color:#cdd6f4; }
#sql-ta:focus { outline:none; border-color:#0066cc; }
.toolbar { padding:8px 0; display:flex; gap:8px; flex-wrap:wrap; }
#results-pane { flex:0 0 auto; max-height:260px; overflow:auto;
                border-top:1px solid #e0e0e0; }
#rtable { font-size:12px; width:100%; }
#rtable th { background:#0066cc; color:#fff; position:sticky; top:0; padding:4px 8px; }
#rtable td { padding:3px 8px; }
#status { font-size:12px; color:#666; padding:4px 0; }
.btn-ai { background:#7c3aed; border-color:#7c3aed; color:#fff; }
.btn-ai:hover { background:#6028ca; color:#fff; }
</style>
</head>
<body>
<div class="topbar">
  <i class="fas fa-database fa-lg"></i>
  <h1>ReportForge &mdash; SQL Query Editor</h1>
  <span class="ms-auto" style="font-size:12px;opacity:.8">PostgreSQL &bull; Read-only</span>
</div>
<div class="container-fluid py-3">
<div class="row g-3">

  <div class="col-2">
    <div class="panel p-2" id="schema-tree">
      <div class="fw-bold mb-2" style="font-size:13px;color:#0066cc;">
        <i class="fas fa-database me-1"></i>Schema
      </div>
      <div id="tlist"><em style="font-size:12px;color:#888">Loading&hellip;</em></div>
    </div>
  </div>

  <div class="col-10">
    <div class="panel p-3" id="editor-pane">
      <div class="toolbar">
        <button class="btn btn-primary btn-sm" onclick="runQ()">
          <i class="fas fa-play me-1"></i>Run <kbd>Ctrl+Enter</kbd>
        </button>
        <button class="btn btn-outline-secondary btn-sm" onclick="fmtSql()">
          <i class="fas fa-magic me-1"></i>Format
        </button>
        <button class="btn btn-outline-secondary btn-sm" onclick="clrAll()">
          <i class="fas fa-eraser me-1"></i>Clear
        </button>
        <button class="btn btn-outline-success btn-sm" onclick="saveQ()">
          <i class="fas fa-save me-1"></i>Save
        </button>
        <button class="btn btn-outline-info btn-sm" onclick="loadSaved()">
          <i class="fas fa-folder-open me-1"></i>Saved
        </button>
        <button class="btn btn-outline-warning btn-sm" onclick="saveAsReport()">
          <i class="fas fa-chart-bar me-1"></i>Save as Report
        </button>
        <button class="btn btn-ai btn-sm" onclick="aiDialog()">
          <i class="fas fa-robot me-1"></i>AI Assist
        </button>
        <select id="rlimit" class="form-select form-select-sm" style="width:110px">
          <option value="50">50 rows</option>
          <option value="100" selected>100 rows</option>
          <option value="250">250 rows</option>
          <option value="500">500 rows</option>
        </select>
      </div>
      <textarea id="sql-ta"
        placeholder="-- Enter your SELECT query here&#10;-- Click a table in the schema panel to auto-generate a starter query&#10;SELECT * FROM your_table LIMIT 10;"></textarea>
      <div id="status">Ready</div>
      <div id="results-pane">
        <table id="rtable" class="table table-sm table-bordered mb-0">
          <thead id="rhead"></thead><tbody id="rbody"></tbody>
        </table>
      </div>
    </div>
  </div>

</div>
</div>

<!-- Save Modal -->
<div class="modal fade" id="mSave" tabindex="-1">
<div class="modal-dialog"><div class="modal-content">
  <div class="modal-header"><h5 class="modal-title">Save Query</h5>
    <button class="btn-close" data-bs-dismiss="modal"></button></div>
  <div class="modal-body">
    <input id="sname" class="form-control mb-2" placeholder="Query name">
    <textarea id="sdesc" class="form-control mb-2" rows="2" placeholder="Description (optional)"></textarea>
    <div class="form-check">
      <input class="form-check-input" type="checkbox" id="spub">
      <label class="form-check-label" for="spub">Share with all users</label>
    </div>
  </div>
  <div class="modal-footer">
    <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
    <button class="btn btn-primary btn-sm" onclick="doSave()">Save</button>
  </div>
</div></div></div>

<!-- AI Modal -->
<div class="modal fade" id="mAI" tabindex="-1">
<div class="modal-dialog"><div class="modal-content">
  <div class="modal-header">
    <h5 class="modal-title"><i class="fas fa-robot me-2"></i>AI SQL Assistant</h5>
    <button class="btn-close" data-bs-dismiss="modal"></button>
  </div>
  <div class="modal-body">
    <textarea id="aprompt" class="form-control" rows="3"
      placeholder="Describe what you want to query&hellip;&#10;Example: Show me all customers who placed orders in the last 30 days"></textarea>
  </div>
  <div class="modal-footer">
    <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
    <button id="aibtn" class="btn btn-ai btn-sm" onclick="doAI()">
      <i class="fas fa-robot me-1"></i>Generate SQL
    </button>
  </div>
</div></div></div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
const B = '/reportforge/sql-editor';

async function loadSchema() {
  const r = await fetch(B + '/api/schema');
  const d = await r.json();
  const el = document.getElementById('tlist');
  el.innerHTML = '';
  (d.tables||[]).forEach(t => {
    const wrap = document.createElement('div');
    wrap.innerHTML = `<div class="stbl" onclick="toggle('${t.name}')">
      <i class="fas fa-table"></i>${t.name}
      <span style="float:right;font-size:11px;color:#888">${t.columns.length}</span>
    </div>
    <div id="c${t.name}" style="display:none">${
      t.columns.map(c => `<div class="scol" onclick="ins('${c.name}')">
        ${c.name}<span class="ct">${c.type}</span>
      </div>`).join('')
    }</div>`;
    el.appendChild(wrap);
  });
}

function toggle(n) {
  const el = document.getElementById('c' + n);
  if (!el) return;
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
  const ta = document.getElementById('sql-ta');
  if (el.style.display === 'block' && !ta.value.trim())
    ta.value = 'SELECT *\\nFROM ' + n + '\\nLIMIT 100;';
}

function ins(col) {
  const ta = document.getElementById('sql-ta');
  const p = ta.selectionStart;
  ta.value = ta.value.slice(0,p) + col + ta.value.slice(p);
  ta.focus();
}

async function runQ() {
  const sql = document.getElementById('sql-ta').value.trim();
  const lim = document.getElementById('rlimit').value;
  if (!sql) return;
  setS('Running…','text-muted');
  const t0 = Date.now();
  try {
    const r = await fetch(B+'/api/execute',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sql,limit:parseInt(lim)})
    });
    const d = await r.json();
    if (!r.ok||d.error) { setS('Error: '+(d.error||r.statusText),'text-danger'); clrRes(); return; }
    renderR(d.columns,d.rows);
    setS(d.rows.length+' rows · '+(Date.now()-t0)+'ms','text-success');
  } catch(e) { setS('Network error: '+e.message,'text-danger'); }
}

function renderR(cols,rows) {
  document.getElementById('rhead').innerHTML='<tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr>';
  document.getElementById('rbody').innerHTML=rows.map(row=>
    '<tr>'+cols.map(c=>{const v=row[c];return `<td>${v==null?'<em class=\\'text-muted\\'>NULL</em>':esc(String(v))}</td>`;}).join('')+'</tr>'
  ).join('');
}

function clrRes(){document.getElementById('rhead').innerHTML='';document.getElementById('rbody').innerHTML='';}
function setS(m,c='text-muted'){const el=document.getElementById('status');el.className='status '+c;el.textContent=m;}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function fmtSql(){
  const ta=document.getElementById('sql-ta');
  let s=ta.value;
  ['FROM','WHERE','JOIN','LEFT JOIN','RIGHT JOIN','INNER JOIN','ORDER BY','GROUP BY','HAVING','LIMIT','OFFSET'].forEach(k=>{
    s=s.replace(new RegExp('\\\\b'+k+'\\\\b','gi'),'\\n'+k);
  });
  ta.value=s.replace(/\\n\\s*\\n/g,'\\n').trim();
}

function clrAll(){document.getElementById('sql-ta').value='';clrRes();setS('Ready');}

function saveQ(){new bootstrap.Modal(document.getElementById('mSave')).show();}

async function doSave(){
  const sql=document.getElementById('sql-ta').value.trim();
  const name=document.getElementById('sname').value.trim();
  if(!sql||!name){alert('Name and SQL required.');return;}
  const r=await fetch(B+'/api/query/save',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,sql,description:document.getElementById('sdesc').value,
                          is_public:document.getElementById('spub').checked})
  });
  const d=await r.json();
  if(d.ok){bootstrap.Modal.getInstance(document.getElementById('mSave')).hide();setS('Saved: '+name,'text-success');}
  else alert('Save failed: '+(d.error||'unknown'));
}

async function loadSaved(){
  const r=await fetch(B+'/api/query/list');
  const d=await r.json();
  const qs=d.queries||[];
  if(!qs.length){alert('No saved queries yet.');return;}
  const nm=prompt('Saved queries:\\n'+qs.map((q,i)=>(i+1)+'. '+q.name).join('\\n')+'\\n\\nEnter name to load:');
  const q=qs.find(x=>x.name===nm);
  if(q) document.getElementById('sql-ta').value=q.sql;
}

function aiDialog(){new bootstrap.Modal(document.getElementById('mAI')).show();}

async function doAI(){
  const prompt=document.getElementById('aprompt').value.trim();
  if(!prompt)return;
  const btn=document.getElementById('aibtn');
  btn.disabled=true;btn.textContent='Generating…';
  const r=await fetch(B+'/api/ai-assist',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({prompt})
  });
  const d=await r.json();
  btn.disabled=false;btn.innerHTML='<i class="fas fa-robot me-1"></i>Generate SQL';
  if(d.sql){document.getElementById('sql-ta').value=d.sql;bootstrap.Modal.getInstance(document.getElementById('mAI')).hide();}
  else alert('AI error: '+(d.error||'No SQL returned'));
}

// ── Save as Report ────────────────────────────────────────────────────────
function saveAsReport(){new bootstrap.Modal(document.getElementById('mReport')).show();}
async function doSaveAsReport(){
  const sql=document.getElementById('sql-ta').value.trim();
  const name=(document.getElementById('rname').value||'').trim();
  if(!sql||!name){alert('Name and SQL required.');return;}
  const r=await fetch(B+'/api/report/create',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({sql,name})
  });
  const d=await r.json();
  if(d.ok){
    bootstrap.Modal.getInstance(document.getElementById('mReport')).hide();
    if(confirm('Report created! Open in designer now?'))
      window.open(d.designer_url,'_blank');
  } else alert('Error: '+(d.error||'unknown'));
}

// ── Schema-based autocomplete (datalist) ─────────────────────────────────
async function buildAutocomplete(){
  const r=await fetch(B+'/api/schema');
  const d=await r.json();
  const terms=[];
  (d.tables||[]).forEach(t=>{
    terms.push(t.name);
    (t.columns||[]).forEach(c=>terms.push(t.name+'.'+c.name,c.name));
  });
  const dl=document.createElement('datalist');
  dl.id='sql-ac';
  terms.filter((v,i,a)=>a.indexOf(v)===i).forEach(t=>{
    const o=document.createElement('option');o.value=t;dl.appendChild(o);
  });
  document.body.appendChild(dl);
  document.getElementById('sql-ta').setAttribute('autocomplete','sql-ac');
}
buildAutocomplete();

document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();runQ();}
});

loadSchema();
</script>

<!-- Save as Report Modal -->
<div class="modal fade" id="mReport" tabindex="-1">
<div class="modal-dialog"><div class="modal-content">
  <div class="modal-header"><h5 class="modal-title"><i class="fas fa-chart-bar me-2"></i>Save as Report</h5>
    <button class="btn-close" data-bs-dismiss="modal"></button></div>
  <div class="modal-body">
    <input id="rname" class="form-control" placeholder="Report name">
    <small class="text-muted">Creates a new tabular report with this SQL. You can then edit it in the designer.</small>
  </div>
  <div class="modal-footer">
    <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
    <button class="btn btn-warning btn-sm" onclick="doSaveAsReport()">
      <i class="fas fa-chart-bar me-1"></i>Create Report
    </button>
  </div>
</div></div></div>

</body>
</html>"""


class SqlEditorView(BaseView):
	"""Visual SQL query editor — read-only SELECT queries against the app's PostgreSQL DB."""

	route_base   = "/reportforge/sql-editor"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return _EDITOR_HTML

	def _get_engine(self):
		"""
		Return the SQLAlchemy engine to use for the SQL editor.

		If ``REPORTFORGE_DB_READONLY_URI`` is set, creates a separate
		engine bound to a read-only PostgreSQL role. Otherwise falls back
		to the app's default engine (less secure — read-only is strongly
		recommended for production).
		"""
		appbuilder = current_app.extensions.get("appbuilder")
		ro_uri = current_app.config.get("REPORTFORGE_DB_READONLY_URI")
		if ro_uri:
			try:
				import sqlalchemy as _sa
				return _sa.create_engine(
					ro_uri,
					pool_size=2, max_overflow=2, pool_timeout=10,
					connect_args={"options": "-c default_transaction_read_only=on"},
				)
			except Exception as exc:
				log.warning("ReportForge: could not create read-only engine: %s — falling back", exc)
		if appbuilder:
			return appbuilder.session.bind
		raise RuntimeError("appbuilder not found and REPORTFORGE_DB_READONLY_URI not set")

	@expose("/api/schema")
	@has_access
	def api_schema(self):
		"""
		Return tables and columns from the user's schemas.

		Respects ``REPORTFORGE_SQL_SCHEMAS`` (list of schema names; defaults to
		["public"]). Pass ``?schema=myschema`` to override in the request.
		"""
		try:
			engine = self._get_engine()
			insp   = sa.inspect(engine)
			# Schema list: request param > config > ["public"]
			config_schemas = current_app.config.get("REPORTFORGE_SQL_SCHEMAS", ["public"])
			req_schema = request.args.get("schema")
			schemas = [req_schema] if req_schema else config_schemas

			tables = []
			available_schemas = set(insp.get_schema_names())
			for schema in schemas:
				if schema not in available_schemas:
					continue
				for tname in sorted(insp.get_table_names(schema=schema)):
					cols = [
						{"name": c["name"], "type": str(c["type"])}
						for c in insp.get_columns(tname, schema=schema)
					]
					tables.append({"name": tname, "schema": schema, "columns": cols})
			return jsonify({"tables": tables, "schemas": list(available_schemas)})
		except Exception as exc:
			log.exception("schema introspection failed")
			return jsonify({"tables": [], "error": str(exc)}), 500

	@expose("/api/execute", methods=["POST"])
	@has_access
	def api_execute(self):
		data  = request.get_json(silent=True) or {}
		sql   = (data.get("sql") or "").strip()
		limit = min(int(data.get("limit") or 100), _MAX_DEFAULT_ROWS)
		if not sql:
			return jsonify({"error": "sql is required"}), 400
		stripped = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
		stripped = re.sub(r"--[^\n]*", "", stripped).strip()
		first_word = stripped.split()[0].upper() if stripped.split() else ""
		if first_word not in ("SELECT", "WITH", "EXPLAIN"):
			return jsonify({"error": "Only SELECT queries are permitted."}), 403
		if _FORBIDDEN_RE.search(stripped):
			return jsonify({"error": "Query contains a forbidden statement."}), 403
		if not re.search(r"\bLIMIT\b", stripped, re.IGNORECASE):
			sql = f"{sql.rstrip(';')}\nLIMIT {limit}"

		try:
			t0 = time.perf_counter()
			engine = self._get_engine()
			with engine.connect() as conn:
				# Enforce read-only at the connection level too
				conn.execute(sa.text("SET LOCAL default_transaction_read_only = on"))
				result = conn.execute(sa.text(sql))
				columns = list(result.keys())
				rows = [dict(r._mapping) for r in result]
			elapsed_ms = int((time.perf_counter() - t0) * 1000)
			for row in rows:
				for k, v in row.items():
					if v is not None and not isinstance(v, (str, int, float, bool)):
						row[k] = str(v)
			return jsonify({"columns": columns, "rows": rows, "elapsed_ms": elapsed_ms})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 400

	@expose("/api/query/save", methods=["POST"])
	@has_access
	def api_save_query(self):
		from flask_login import current_user
		from .models import SavedQuery
		data = request.get_json(silent=True) or {}
		name = (data.get("name") or "").strip()
		sql  = (data.get("sql")  or "").strip()
		if not name or not sql:
			return jsonify({"ok": False, "error": "name and sql are required"}), 400
		appbuilder = current_app.extensions.get("appbuilder")
		if not appbuilder:
			return jsonify({"ok": False, "error": "appbuilder not found"}), 500
		q = SavedQuery(
			name=name,
			description=data.get("description", ""),
			sql_text=sql,
			is_public=bool(data.get("is_public")),
			created_by=getattr(current_user, "id", None),
		)
		appbuilder.session.add(q)
		appbuilder.session.commit()
		return jsonify({"ok": True, "id": q.id})

	@expose("/api/query/list")
	@has_access
	def api_list_queries(self):
		from flask_login import current_user
		from .models import SavedQuery
		appbuilder = current_app.extensions.get("appbuilder")
		if not appbuilder:
			return jsonify({"queries": []})
		uid = getattr(current_user, "id", None)
		qs = (
			appbuilder.session.query(SavedQuery)
			.filter(sa.or_(SavedQuery.is_public == True, SavedQuery.created_by == uid))
			.order_by(SavedQuery.changed_on.desc())
			.limit(100)
			.all()
		)
		return jsonify({"queries": [
			{"id": x.id, "name": x.name, "description": x.description, "sql": x.sql_text}
			for x in qs
		]})

	@expose("/api/report/create", methods=["POST"])
	@has_access
	def api_create_report(self):
		"""
		Save the current SQL editor query as a new Report with a tabular template.
		Returns JSON {ok, report_id, designer_url}.
		"""
		from flask import current_app
		from flask_login import current_user
		from .models import Report, PaperSize, Orientation
		from .wizard import _apply_template_bands
		from .report_templates import get_template

		data    = request.get_json(silent=True) or {}
		sql     = (data.get("sql") or "").strip()
		name    = (data.get("name") or "Untitled Report").strip()
		if not sql:
			return jsonify({"ok": False, "error": "sql is required"}), 400

		appbuilder = current_app.extensions.get("appbuilder")
		if not appbuilder:
			return jsonify({"ok": False, "error": "appbuilder not found"}), 500

		session = appbuilder.session
		report  = Report(
			name=name,
			data_source=sql,
			is_sql_source=True,
			paper_size=PaperSize.A4,
			orientation=Orientation.PORTRAIT,
			template_key="tabular",
			is_draft=True,
			created_by=getattr(current_user, "id", None),
		)
		session.add(report)
		session.flush()
		tmpl = get_template("tabular")
		if tmpl:
			_apply_template_bands(report, tmpl, session)
		session.commit()
		return jsonify({
			"ok": True,
			"report_id": report.id,
			"designer_url": f"/reports/designer/{report.id}",
		})

	@expose("/api/ai-assist", methods=["POST"])
	@has_access
	def api_ai_assist(self):
		from .ai_augment import augment_text
		data   = request.get_json(silent=True) or {}
		prompt = (data.get("prompt") or "").strip()
		if not prompt:
			return jsonify({"error": "prompt is required"}), 400
		sql = augment_text(
			f"Write a PostgreSQL SELECT query for the following request:\n{prompt}\n\n"
			"Return ONLY the SQL query. No explanation, no markdown, no code block fences.",
			{}, current_app, max_tokens=400,
		)
		if sql.startswith("Error:"):
			return jsonify({"error": sql}), 500
		sql = re.sub(r"^```\w*\n?|```$", "", sql.strip(), flags=re.MULTILINE).strip()
		return jsonify({"sql": sql})
