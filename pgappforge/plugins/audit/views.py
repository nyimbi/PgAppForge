"""Audit Trail views — read-only audit log browser and compliance tools."""
from __future__ import annotations
import logging
from flask import request, jsonify, Response
from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)

_AUDIT_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Audit Log</title>
<style>
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e0e0e0;margin:0;padding:20px;}
.timeline{max-width:900px;margin:0 auto;}
h1{color:#7c83ff;font-size:1.4rem;}
.entry{background:#1a1d2e;border:1px solid #2e3250;border-radius:8px;padding:16px;margin-bottom:12px;}
.entry-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
.op{font-size:0.75rem;padding:2px 8px;border-radius:4px;font-weight:600;}
.op-INSERT{background:#1a3a1a;color:#4caf50;}
.op-UPDATE{background:#1a2a3a;color:#64b5f6;}
.op-DELETE{background:#3a1a1a;color:#ef5350;}
.actor{font-size:0.82rem;color:#888;}
.ts{font-size:0.75rem;color:#666;}
.diffs{font-size:0.8rem;}
.diff-row{display:flex;gap:12px;padding:4px 0;border-bottom:1px solid #1e2245;}
.diff-field{color:#9c9fff;width:140px;flex-shrink:0;}
.diff-before{color:#ef5350;flex:1;}
.diff-after{color:#4caf50;flex:1;}
.filters{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;}
input,select{background:#1a1d2e;border:1px solid #3a3f6e;color:#e0e0e0;padding:6px 10px;border-radius:6px;font-size:0.82rem;}
button{background:#3a3f6e;color:#b0b8ff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;}
</style></head>
<body>
<div class="timeline">
<h1>Audit Log</h1>
<div class="filters">
  <input id="f-model" placeholder="Model name" value="">
  <input id="f-entity" placeholder="Entity ID">
  <input id="f-actor" placeholder="Actor ID">
  <input id="f-since" type="date">
  <select id="f-op"><option value="">All ops</option><option>INSERT</option><option>UPDATE</option><option>DELETE</option></select>
  <button onclick="load()">Filter</button>
</div>
<div id="entries">Loading...</div>
</div>
<script>
async function load() {
  const params = new URLSearchParams({
    model: document.getElementById('f-model').value,
    entity_id: document.getElementById('f-entity').value,
    actor_id: document.getElementById('f-actor').value,
    since: document.getElementById('f-since').value,
    op: document.getElementById('f-op').value,
  });
  const res = await fetch('/audit/api/changes?' + params);
  const data = await res.json();
  const el = document.getElementById('entries');
  if (!data.entries || !data.entries.length) {
    el.innerHTML = '<p style="color:#666">No entries found.</p>';
    return;
  }
  el.innerHTML = data.entries.map(e => {
    const diffs = Object.entries(e.field_diffs || {}).map(([f,v]) =>
      '<div class="diff-row"><span class="diff-field">' + f + '</span>' +
      '<span class="diff-before">' + JSON.stringify(v.before) + '</span>' +
      '<span class="diff-after">' + JSON.stringify(v.after) + '</span></div>'
    ).join('');
    return '<div class="entry"><div class="entry-header"><span>' +
      '<span class="op op-' + e.operation + '">' + e.operation + '</span> ' +
      e.model_name + ' #' + e.entity_id + '</span>' +
      '<span class="ts">' + new Date(e.created_at).toLocaleString() + '</span></div>' +
      '<div class="actor">by user #' + (e.actor_id || '?') +
      (e.actor_role ? ' (' + e.actor_role + ')' : '') + '</div>' +
      (diffs ? '<div class="diffs" style="margin-top:8px">' + diffs + '</div>' : '') +
      '</div>';
  }).join('');
}
load();
</script></body></html>"""


class AuditLogView(BaseView):
	route_base = "/audit"

	@expose("/")
	@has_access
	def index(self):
		return Response(_AUDIT_HTML, mimetype="text/html")

	@expose("/api/changes")
	@has_access
	def api_changes(self):
		from pgappforge.plugins.audit.models import AuditLog
		import sqlalchemy as sa
		session = self.appbuilder.get_session
		q = sa.select(AuditLog).order_by(sa.desc(AuditLog.created_at))

		model = request.args.get("model", "").strip()
		entity_id = request.args.get("entity_id", "").strip()
		actor_id = request.args.get("actor_id", "").strip()
		since = request.args.get("since", "").strip()
		op = request.args.get("op", "").strip()
		page = max(1, int(request.args.get("page", 1)))
		per_page = min(int(request.args.get("per_page", 50)), 200)

		if model:
			q = q.where(AuditLog.model_name == model)
		if entity_id:
			q = q.where(AuditLog.entity_id == entity_id)
		if actor_id:
			try:
				q = q.where(AuditLog.actor_id == int(actor_id))
			except ValueError:
				pass
		if since:
			import datetime as dt_mod
			try:
				dt = dt_mod.datetime.fromisoformat(since)
				q = q.where(AuditLog.created_at >= dt)
			except ValueError:
				pass
		if op and op in ("INSERT", "UPDATE", "DELETE"):
			q = q.where(AuditLog.operation == op)

		q = q.offset((page - 1) * per_page).limit(per_page)
		rows = session.execute(q).scalars().all()

		return jsonify({
			"entries": [
				{
					"id": r.id,
					"model_name": r.model_name,
					"entity_id": r.entity_id,
					"operation": r.operation,
					"actor_id": r.actor_id,
					"actor_role": r.actor_role,
					"field_diffs": r.field_diffs,
					"row_hash": r.row_hash,
					"prev_hash": r.prev_hash,
					"created_at": r.created_at.isoformat() if r.created_at else None,
				}
				for r in rows
			],
			"page": page,
			"per_page": per_page,
		})

	@expose("/api/verify/<int:entity_id>")
	@has_access
	def api_verify_chain(self, entity_id: int):
		"""Verify the hash chain integrity for an entity."""
		from pgappforge.plugins.audit.models import AuditLog
		from pgappforge.plugins.audit import _compute_hash
		import sqlalchemy as sa
		session = self.appbuilder.get_session
		model = request.args.get("model", "").strip()
		rows = session.execute(
			sa.select(AuditLog)
			.where(AuditLog.model_name == model)
			.where(AuditLog.entity_id == str(entity_id))
			.order_by(sa.asc(AuditLog.created_at))
		).scalars().all()

		valid = True
		for i, row in enumerate(rows):
			prev = rows[i - 1].row_hash if i > 0 else None
			expected = _compute_hash(row.field_diffs or {}, prev)
			if expected != row.row_hash:
				valid = False
				break

		return jsonify({"valid": valid, "rows_checked": len(rows)})
