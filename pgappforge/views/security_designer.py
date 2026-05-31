"""
Visual Security Designer for pgappforge.

Interactive graph-based UI for managing roles, permissions, and viewing the
security topology of your application.

Usage::

    from pgappforge.views.security_designer import SecurityDesignerView
    appbuilder.add_view(
        SecurityDesignerView, "Security Designer",
        icon="fa-shield", category="Security"
    )
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from flask import abort, current_app, make_response, request, jsonify, Response
from flask_login import current_user
from markupsafe import escape as _html_escape

from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.widgets_postgresql._cdn import (
	CYTOSCAPE_CDN as _CY,
	CYTOSCAPE_FCOSE_CDN as _FCOSE,
	JSYAML_CDN as _JSYAML,
)

log = logging.getLogger(__name__)


def _require_security_admin() -> None:
	"""Abort 403 unless the current user holds the Admin role."""
	if not current_user or not current_user.is_authenticated:
		abort(make_response(jsonify({"ok": False, "error": "Login required", "code": "login_required"}), 403))
	admin_role = current_app.config.get("AUTH_ROLE_ADMIN", "Admin")
	role_names = {getattr(r, "name", "") for r in getattr(current_user, "roles", [])}
	if admin_role not in role_names and "admin" not in role_names:
		abort(make_response(jsonify({"ok": False, "error": "Admin role required", "code": "admin_required"}), 403))


def _validate_csrf() -> None:
	"""Validate the X-CSRFToken header. Falls back to no-op when flask-wtf is absent."""
	try:
		from flask_wtf.csrf import validate_csrf, ValidationError
	except ImportError:
		return
	token = request.headers.get("X-CSRFToken") or request.form.get("csrf_token", "")
	try:
		validate_csrf(token)
	except Exception:
		abort(400, description="CSRF validation failed")


# ---------------------------------------------------------------------------
# Role templates
# ---------------------------------------------------------------------------

ROLE_TEMPLATES: dict[str, dict] = {
	"Admin": {
		"label": "Administrator",
		"description": "Full access to all views and operations.",
		"permissions": [
			{"view_pattern": "*", "actions": ["can_list", "can_show", "can_add", "can_edit", "can_delete", "menu_access"]},
		],
	},
	"Editor": {
		"label": "Editor",
		"description": "Can read, create and update records but cannot delete.",
		"permissions": [
			{"view_pattern": "*", "actions": ["can_list", "can_show", "can_add", "can_edit", "menu_access"]},
		],
	},
	"Viewer": {
		"label": "Viewer",
		"description": "Read-only access to all views.",
		"permissions": [
			{"view_pattern": "*", "actions": ["can_list", "can_show", "menu_access"]},
		],
	},
	"API-only": {
		"label": "API-only",
		"description": "Programmatic API access with no UI navigation.",
		"permissions": [
			{"view_pattern": "*", "actions": ["can_get", "can_post", "can_put", "can_delete"]},
		],
	},
	"Auditor": {
		"label": "Auditor",
		"description": "Read-only with access to security and audit views.",
		"permissions": [
			{"view_pattern": "*", "actions": ["can_list", "can_show"]},
			{"view_pattern": "Security*", "actions": ["can_list", "can_show", "menu_access"]},
		],
	},
}

# ---------------------------------------------------------------------------
# Inline HTML template
# ---------------------------------------------------------------------------

_DESIGNER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Security Designer</title>
{cytoscape_cdn}
{jsyaml_cdn}
{fcose_cdn}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" crossorigin="">
<style>
  body {{ margin: 0; font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }}
  #toolbar {{ background: #1a1d2e; border-bottom: 1px solid #2e3250; padding: 8px 16px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  #toolbar h1 {{ font-size: 1rem; margin: 0; color: #7c83ff; font-weight: 600; margin-right: 16px; }}
  .tb-btn {{ font-size: 0.78rem; padding: 5px 12px; border-radius: 6px; border: 1px solid #3a3f6e; background: #1e2140; color: #b0b8ff; cursor: pointer; transition: background 0.15s; }}
  .tb-btn:hover {{ background: #2a2f5a; color: #fff; }}
  .tb-btn.danger {{ border-color: #7a2020; color: #ff8080; }}
  .tb-btn.danger:hover {{ background: #3a1010; }}
  #main {{ display: flex; flex: 1; overflow: hidden; }}
  #sidebar {{ width: 300px; min-width: 220px; background: #13162a; border-right: 1px solid #2e3250; display: flex; flex-direction: column; overflow: hidden; }}
  #sidebar-tabs {{ display: flex; border-bottom: 1px solid #2e3250; }}
  .stab {{ flex: 1; padding: 8px 0; text-align: center; font-size: 0.8rem; cursor: pointer; color: #888; border-bottom: 2px solid transparent; }}
  .stab.active {{ color: #7c83ff; border-bottom-color: #7c83ff; }}
  #tab-graph, #tab-matrix {{ flex: 1; overflow-y: auto; padding: 10px; display: none; }}
  #tab-graph.active, #tab-matrix.active {{ display: block; }}
  #role-list {{ list-style: none; padding: 0; margin: 0; }}
  #role-list li {{ padding: 6px 10px; border-radius: 6px; cursor: pointer; font-size: 0.82rem; display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px; }}
  #role-list li:hover {{ background: #1e2245; }}
  #role-list li.selected {{ background: #2a2f6e; }}
  .badge-count {{ background: #3a3f6e; color: #aaa; font-size: 0.7rem; padding: 2px 7px; border-radius: 10px; }}
  #cy-wrap {{ flex: 1; position: relative; }}
  #cy-security {{ width: 100%; height: 100%; background: #0f1117; }}
  #info-panel {{ width: 260px; background: #13162a; border-left: 1px solid #2e3250; padding: 14px; overflow-y: auto; font-size: 0.82rem; }}
  #info-panel h3 {{ font-size: 0.9rem; color: #7c83ff; margin-bottom: 10px; }}
  .info-field {{ margin-bottom: 8px; }}
  .info-label {{ color: #888; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .info-value {{ color: #e0e0e0; }}
  .matrix-table {{ font-size: 0.72rem; border-collapse: collapse; width: 100%; }}
  .matrix-table th, .matrix-table td {{ border: 1px solid #2e3250; padding: 3px 6px; white-space: nowrap; }}
  .matrix-table th {{ background: #1a1d2e; color: #7c83ff; }}
  .matrix-cell-yes {{ background: #1a3a1a; color: #4caf50; text-align: center; }}
  .matrix-cell-no {{ background: #1a1d2e; color: #444; text-align: center; }}
  #modal-overlay {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 1000; align-items: center; justify-content: center; }}
  #modal-overlay.open {{ display: flex; }}
  #modal-box {{ background: #1a1d2e; border: 1px solid #3a3f6e; border-radius: 10px; padding: 24px; min-width: 420px; max-width: 600px; max-height: 80vh; overflow-y: auto; }}
  #modal-box h2 {{ font-size: 1rem; color: #7c83ff; margin-bottom: 16px; }}
  .modal-input {{ width: 100%; background: #0f1117; border: 1px solid #3a3f6e; color: #e0e0e0; border-radius: 6px; padding: 7px 10px; font-size: 0.85rem; margin-bottom: 10px; }}
  .modal-actions {{ display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }}
  #toast {{ position: fixed; bottom: 20px; right: 20px; background: #23264a; color: #b0b8ff; border: 1px solid #3a3f6e; border-radius: 8px; padding: 10px 18px; font-size: 0.82rem; display: none; z-index: 2000; }}
  #toast.error {{ background: #2a1010; color: #ff8080; border-color: #7a2020; }}
</style>
</head>
<body>

<div id="toolbar">
  <h1>&#x1F6E1; Security Designer</h1>
  <button class="tb-btn" onclick="SD.addRole()">+ Role</button>
  <button class="tb-btn" onclick="SD.grantPermission()">+ Permission</button>
  <button class="tb-btn" onclick="SD.applyTemplate()">Apply Template</button>
  <button class="tb-btn" onclick="SD.openSimulate()">Simulate</button>
  <button class="tb-btn" onclick="SD.exportYaml()">Export YAML</button>
  <button class="tb-btn" onclick="SD.openImport()">Import YAML</button>
  <button class="tb-btn" onclick="SD.runHealthCheck()">Health Check</button>
  <button class="tb-btn" onclick="SD.takeSnapshot()">Snapshot</button>
  <button class="tb-btn" onclick="SD.listSnapshots()">Snapshots</button>
</div>

<div id="main">
  <div id="sidebar">
    <div id="sidebar-tabs">
      <div class="stab active" onclick="SD.switchTab('graph')" id="stab-graph">Graph</div>
      <div class="stab" onclick="SD.switchTab('matrix')" id="stab-matrix">Matrix</div>
    </div>
    <div id="tab-graph" class="active">
      <div style="font-size:0.75rem;color:#888;margin-bottom:8px;">Roles</div>
      <ul id="role-list"></ul>
    </div>
    <div id="tab-matrix">
      <div style="font-size:0.75rem;color:#888;margin-bottom:8px;">Role × View matrix</div>
      <div id="matrix-container"><em style="color:#666">Loading…</em></div>
    </div>
  </div>

  <div id="cy-wrap">
    <div id="cy-security"></div>
  </div>

  <div id="info-panel">
    <h3>Details</h3>
    <div id="info-content">
      <div style="color:#555;font-size:0.8rem;">Click a node or edge for details.</div>
    </div>
  </div>
</div>

<!-- Modal -->
<div id="modal-overlay">
  <div id="modal-box">
    <h2 id="modal-title">Dialog</h2>
    <div id="modal-body"></div>
    <div class="modal-actions">
      <button class="tb-btn" onclick="SD.closeModal()">Cancel</button>
      <button class="tb-btn" id="modal-ok" onclick="SD.confirmModal()">OK</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
const BASE = window.location.pathname.replace(/\\/$/, '');

const SD = (() => {
  let cy = null;
  let graphData = null;
  let modalCallback = null;

  // ── Helpers ──────────────────────────────────────────────────────────────

  function toast(msg, isError = false) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = isError ? 'error' : '';
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 3500);
  }

  async function api(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(BASE + path, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { toast(data.error || 'Request failed', true); throw new Error(data.error); }
    return data;
  }

  // ── Graph ─────────────────────────────────────────────────────────────────

  async function loadGraph() {
    try {
      graphData = await api('GET', '/api/graph');
      buildCy(graphData);
      buildRoleList(graphData);
    } catch (e) { toast('Failed to load graph: ' + e.message, true); }
  }

  function buildCy(data) {
    if (cy) cy.destroy();
    const elements = [];
    (data.nodes || []).forEach(n => {
      elements.push({
        data: {
          id: n.id, label: n.label, type: n.type,
          perm_count: n.perm_count || 0
        }
      });
    });
    (data.edges || []).forEach(e => {
      elements.push({
        data: {
          id: e.id, source: e.source, target: e.target,
          type: e.type, perm_name: e.perm_name || ''
        }
      });
    });

    cy = cytoscape({
      container: document.getElementById('cy-security'),
      elements,
      style: [
        { selector: 'node[type="role"]', style: {
          'background-color': '#3d52d5', 'label': 'data(label)',
          'color': '#fff', 'font-size': '11px', 'text-valign': 'center',
          'text-halign': 'center', 'width': 80, 'height': 40, 'shape': 'roundrectangle',
          'text-wrap': 'wrap', 'text-max-width': '75px'
        }},
        { selector: 'node[type="view"]', style: {
          'background-color': '#1e3a5f', 'label': 'data(label)',
          'color': '#90c8ff', 'font-size': '9px', 'text-valign': 'bottom',
          'text-halign': 'center', 'width': 30, 'height': 30, 'shape': 'ellipse',
          'text-wrap': 'wrap', 'text-max-width': '60px'
        }},
        { selector: 'edge', style: {
          'line-color': '#3a4080', 'target-arrow-color': '#5a60c0',
          'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
          'opacity': 0.65, 'width': 1.5,
          'label': 'data(perm_name)', 'font-size': '7px', 'color': '#666'
        }},
        { selector: ':selected', style: { 'border-width': 3, 'border-color': '#ffcc44' }}
      ],
      layout: { name: 'fcose', animate: true, randomize: false,
                nodeRepulsion: 8000, idealEdgeLength: 120 }
    });

    cy.on('tap', 'node', evt => showNodeInfo(evt.target.data()));
    cy.on('tap', 'edge', evt => showEdgeInfo(evt.target.data()));
    cy.on('tap', function(evt) {
      if (evt.target === cy) clearInfo();
    });
  }

  function showNodeInfo(d) {
    const panel = document.getElementById('info-content');
    if (d.type === 'role') {
      panel.innerHTML = `
        <div class="info-field"><div class="info-label">Type</div><div class="info-value">Role</div></div>
        <div class="info-field"><div class="info-label">Name</div><div class="info-value">${d.label}</div></div>
        <div class="info-field"><div class="info-label">Permissions</div><div class="info-value">${d.perm_count}</div></div>
        <div style="margin-top:12px;display:flex;flex-direction:column;gap:6px;">
          <button class="tb-btn" onclick="SD.deleteRoleById('${d.id}')">Delete Role</button>
          <button class="tb-btn" onclick="SD.grantPermissionToRole('${d.id}','${d.label}')">Add Permission</button>
          <button class="tb-btn" onclick="SD.simulateRole('${d.id}','${d.label}')">Simulate Access</button>
        </div>`;
    } else {
      panel.innerHTML = `
        <div class="info-field"><div class="info-label">Type</div><div class="info-value">View / Menu</div></div>
        <div class="info-field"><div class="info-label">Name</div><div class="info-value">${d.label}</div></div>`;
    }
  }

  function showEdgeInfo(d) {
    const panel = document.getElementById('info-content');
    panel.innerHTML = `
      <div class="info-field"><div class="info-label">Type</div><div class="info-value">Permission</div></div>
      <div class="info-field"><div class="info-label">Permission</div><div class="info-value">${d.perm_name}</div></div>
      <div style="margin-top:12px;">
        <button class="tb-btn danger" onclick="SD.revokePermById('${d.id}')">Revoke</button>
      </div>`;
  }

  function clearInfo() {
    document.getElementById('info-content').innerHTML =
      '<div style="color:#555;font-size:0.8rem;">Click a node or edge for details.</div>';
  }

  // ── Sidebar role list ─────────────────────────────────────────────────────

  function buildRoleList(data) {
    const ul = document.getElementById('role-list');
    ul.innerHTML = '';
    const roles = (data.nodes || []).filter(n => n.type === 'role');
    roles.forEach(r => {
      const li = document.createElement('li');
      li.innerHTML = `<span>${r.label}</span><span class="badge-count">${r.perm_count}</span>`;
      li.onclick = () => {
        ul.querySelectorAll('li').forEach(x => x.classList.remove('selected'));
        li.classList.add('selected');
        if (cy) {
          cy.$('#' + r.id).select();
          cy.animate({ fit: { eles: cy.$('#' + r.id), padding: 80 }, duration: 400 });
          showNodeInfo(r);
        }
      };
      ul.appendChild(li);
    });
  }

  // ── Matrix tab ────────────────────────────────────────────────────────────

  function buildMatrix(data) {
    const container = document.getElementById('matrix-container');
    const roles = (data.nodes || []).filter(n => n.type === 'role');
    const views = [...new Set((data.edges || []).map(e => e.target))].slice(0, 40);
    if (!roles.length || !views.length) {
      container.innerHTML = '<em style="color:#666">No data yet.</em>';
      return;
    }
    const viewNames = {};
    (data.nodes || []).forEach(n => { viewNames[n.id] = n.label; });

    // role_id -> set of view node ids
    const access = {};
    roles.forEach(r => { access[r.id] = new Set(); });
    (data.edges || []).forEach(e => {
      if (access[e.source]) access[e.source].add(e.target);
    });

    let html = '<div style="overflow:auto;max-height:calc(100vh - 200px)"><table class="matrix-table"><thead><tr><th>Role</th>';
    views.forEach(vid => { html += `<th title="${viewNames[vid] || vid}">${(viewNames[vid] || vid).slice(0,12)}</th>`; });
    html += '</tr></thead><tbody>';
    roles.forEach(r => {
      html += `<tr><td>${r.label}</td>`;
      views.forEach(vid => {
        if (access[r.id] && access[r.id].has(vid)) {
          html += '<td class="matrix-cell-yes">&#x2714;</td>';
        } else {
          html += '<td class="matrix-cell-no">&#x2013;</td>';
        }
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    container.innerHTML = html;
  }

  // ── Tab switching ─────────────────────────────────────────────────────────

  function switchTab(name) {
    document.getElementById('tab-graph').classList.toggle('active', name === 'graph');
    document.getElementById('tab-matrix').classList.toggle('active', name === 'matrix');
    document.getElementById('stab-graph').classList.toggle('active', name === 'graph');
    document.getElementById('stab-matrix').classList.toggle('active', name === 'matrix');
    if (name === 'matrix' && graphData) buildMatrix(graphData);
  }

  // ── Modal helpers ─────────────────────────────────────────────────────────

  function openModal(title, bodyHtml, onOk) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    modalCallback = onOk;
    document.getElementById('modal-overlay').classList.add('open');
  }

  function closeModal() {
    document.getElementById('modal-overlay').classList.remove('open');
    modalCallback = null;
  }

  function confirmModal() {
    if (modalCallback) modalCallback();
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  async function addRole() {
    openModal('Create Role', `
      <input class="modal-input" id="m-role-name" placeholder="Role name" autofocus>
    `, async () => {
      const name = document.getElementById('m-role-name').value.trim();
      if (!name) return;
      await api('POST', '/api/roles', { name });
      closeModal();
      toast('Role created: ' + name);
      loadGraph();
    });
  }

  async function deleteRoleById(nodeId) {
    const rid = parseInt(nodeId.replace('role_', ''), 10);
    if (!confirm('Delete this role?')) return;
    await api('DELETE', '/api/roles/' + rid);
    toast('Role deleted');
    loadGraph();
  }

  async function grantPermission() {
    openModal('Grant Permission', `
      <input class="modal-input" id="m-role-id" placeholder="Role ID (number)">
      <input class="modal-input" id="m-view-name" placeholder="View name (e.g. UserModelView)">
      <input class="modal-input" id="m-perm-name" placeholder="Permission (e.g. can_list)">
    `, async () => {
      const role_id = parseInt(document.getElementById('m-role-id').value, 10);
      const view_name = document.getElementById('m-view-name').value.trim();
      const permission_name = document.getElementById('m-perm-name').value.trim();
      if (!role_id || !view_name || !permission_name) return;
      await api('POST', '/api/permissions', { role_id, view_name, permission_name });
      closeModal();
      toast('Permission granted');
      loadGraph();
    });
  }

  async function grantPermissionToRole(nodeId, roleName) {
    const rid = parseInt(nodeId.replace('role_', ''), 10);
    openModal('Add Permission to ' + roleName, `
      <input class="modal-input" id="m-view-name2" placeholder="View name">
      <input class="modal-input" id="m-perm-name2" placeholder="Permission (e.g. can_list)">
    `, async () => {
      const view_name = document.getElementById('m-view-name2').value.trim();
      const permission_name = document.getElementById('m-perm-name2').value.trim();
      if (!view_name || !permission_name) return;
      await api('POST', '/api/permissions', { role_id: rid, view_name, permission_name });
      closeModal();
      toast('Permission granted');
      loadGraph();
    });
  }

  async function revokePermById(edgeId) {
    const pvId = parseInt(edgeId.replace('pv_', ''), 10);
    if (!confirm('Revoke this permission?')) return;
    await api('DELETE', '/api/permissions/' + pvId);
    toast('Permission revoked');
    loadGraph();
  }

  async function exportYaml() {
    const data = await api('GET', '/api/export/yaml');
    openModal('Exported YAML', `
      <textarea class="modal-input" rows="16" style="font-family:monospace;font-size:0.78rem" readonly>${data.yaml || ''}</textarea>
    `, closeModal);
    document.getElementById('modal-ok').style.display = 'none';
    setTimeout(() => { document.getElementById('modal-ok').style.display = ''; }, 100);
  }

  async function openImport() {
    openModal('Import YAML', `
      <label style="font-size:0.78rem;color:#888;display:block;margin-bottom:4px">Paste YAML:</label>
      <textarea class="modal-input" id="m-yaml-text" rows="10" style="font-family:monospace;font-size:0.78rem"></textarea>
      <label style="font-size:0.78rem;color:#aaa;display:flex;gap:6px;align-items:center;margin-top:6px">
        <input type="checkbox" id="m-dry-run" checked> Dry run (preview only)
      </label>
    `, async () => {
      const yaml_text = document.getElementById('m-yaml-text').value;
      const dry_run = document.getElementById('m-dry-run').checked;
      const result = await api('POST', '/api/import/yaml', { yaml_text, dry_run });
      closeModal();
      const msg = dry_run
        ? 'Dry run: would add ' + result.added_roles.length + ' roles, ' + result.added_permissions.length + ' permissions'
        : 'Imported: ' + result.added_roles.length + ' roles, ' + result.added_permissions.length + ' permissions';
      toast(msg);
      if (!dry_run) loadGraph();
    });
  }

  async function runHealthCheck() {
    const findings = await api('GET', '/api/health-check');
    const list = findings.findings || findings;
    const rows = list.map(f => {
      const color = f.severity === 'critical' ? '#ff6060' : f.severity === 'warning' ? '#ffc060' : '#60c0ff';
      return `<div style="border-left:3px solid ${color};padding:6px 10px;margin-bottom:8px;background:#1a1d2e;border-radius:0 6px 6px 0">
        <strong style="color:${color};font-size:0.78rem">${f.severity.toUpperCase()}</strong>
        <span style="color:#888;font-size:0.75rem;margin-left:8px">${f.rule}</span>
        <div style="margin-top:4px;font-size:0.8rem;color:#ccc">${f.message}</div>
      </div>`;
    }).join('');
    openModal('Health Check Results', rows || '<div style="color:#4caf50">No issues found.</div>', closeModal);
  }

  async function openSimulate() {
    openModal('Simulate Access', `
      <input class="modal-input" id="m-sim-role-id" placeholder="Role ID (number)">
    `, async () => {
      const role_id = parseInt(document.getElementById('m-sim-role-id').value, 10);
      simulateRole('role_' + role_id, 'Role #' + role_id);
    });
  }

  async function simulateRole(nodeId, roleName) {
    const rid = parseInt(nodeId.replace('role_', ''), 10);
    const data = await api('POST', '/api/simulate', { role_id: rid });
    const views = (data.accessible_views || []);
    const html = views.length
      ? views.map(v => `<div style="padding:3px 0;border-bottom:1px solid #1e2245;font-size:0.82rem">${v}</div>`).join('')
      : '<div style="color:#888">No accessible views found.</div>';
    openModal('Accessible views for: ' + roleName, html, closeModal);
  }

  async function applyTemplate() {
    const tplData = await api('GET', '/api/templates');
    const keys = tplData.templates || [];
    const opts = keys.map(k => `<option value="${k}">${k}</option>`).join('');
    openModal('Apply Role Template', `
      <select class="modal-input" id="m-tpl-name">${opts}</select>
      <input class="modal-input" id="m-tpl-role" placeholder="New role name (leave blank to use template name)">
    `, async () => {
      const template_name = document.getElementById('m-tpl-name').value;
      const role_name = document.getElementById('m-tpl-role').value.trim() || template_name;
      await api('POST', '/api/templates/apply', { template_name, role_name });
      closeModal();
      toast('Template applied: ' + role_name);
      loadGraph();
    });
  }

  async function takeSnapshot() {
    openModal('Take Snapshot', `
      <input class="modal-input" id="m-snap-name" placeholder="Snapshot name" autofocus>
    `, async () => {
      const name = document.getElementById('m-snap-name').value.trim();
      if (!name) return;
      await api('POST', '/api/snapshots', { name });
      closeModal();
      toast('Snapshot saved: ' + name);
    });
  }

  async function listSnapshots() {
    const data = await api('GET', '/api/snapshots');
    const snaps = data.snapshots || [];
    const rows = snaps.map(s => `
      <div style="padding:8px;border-bottom:1px solid #1e2245;font-size:0.82rem;display:flex;justify-content:space-between;align-items:center">
        <div>
          <div style="color:#b0b8ff;font-weight:600">${s.name}</div>
          <div style="color:#666;font-size:0.74rem">${s.taken_at || ''}</div>
        </div>
        <button class="tb-btn" onclick="SD.showDiff(${s.id})">Diff</button>
      </div>`).join('');
    openModal('Snapshots', rows || '<div style="color:#888">No snapshots yet.</div>', closeModal);
  }

  async function showDiff(snapshotId) {
    const data = await api('GET', '/api/diff?snapshot_id=' + snapshotId);
    const added = (data.added_roles || []).concat(data.added_permissions || []);
    const removed = (data.removed_roles || []).concat(data.removed_permissions || []);
    const html = `
      <div style="font-size:0.8rem;color:#888;margin-bottom:8px">Comparing current state to snapshot #${snapshotId}</div>
      ${added.length ? '<div style="color:#4caf50;margin-bottom:6px">+ ' + added.join('<br>+ ') + '</div>' : ''}
      ${removed.length ? '<div style="color:#ff6060">- ' + removed.join('<br>- ') + '</div>' : ''}
      ${!added.length && !removed.length ? '<div style="color:#888">No differences.</div>' : ''}
    `;
    openModal('Diff vs Snapshot #' + snapshotId, html, closeModal);
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  function init() {
    loadGraph();
  }

  return {
    init, loadGraph, switchTab, addRole, deleteRoleById,
    grantPermission, grantPermissionToRole, revokePermById,
    exportYaml, openImport, runHealthCheck, openSimulate, simulateRole,
    applyTemplate, takeSnapshot, listSnapshots, showDiff,
    closeModal, confirmModal,
  };
})();

window.addEventListener('DOMContentLoaded', () => SD.init());
</script>
</body>
</html>
"""


class SecurityDesignerView(BaseView):
	"""Interactive visual security designer."""

	route_base = "/security-designer"
	default_view = "index"

	# ── Helpers ────────────────────────────────────────────────────────────────

	def _secman(self):
		return current_app.appbuilder.sm

	def _get_session(self):
		return current_app.appbuilder.get_session

	# ── Main page ──────────────────────────────────────────────────────────────

	@expose("/")
	@has_access
	def index(self):
		html = _DESIGNER_HTML.format(
			cytoscape_cdn=_CY,
			jsyaml_cdn=_JSYAML,
			fcose_cdn=_FCOSE,
		)
		return Response(html, mimetype="text/html")

	# ── Graph data ─────────────────────────────────────────────────────────────

	@expose("/api/graph")
	@has_access
	def api_graph(self):
		sm = self._secman()
		nodes = []
		edges = []
		view_names_seen: set[str] = set()

		for role in sm.get_all_roles():
			perm_count = len(getattr(role, "permissions", []))
			nodes.append({
				"id": f"role_{role.id}",
				"label": role.name,
				"type": "role",
				"perm_count": perm_count,
			})
			for pvm in getattr(role, "permissions", []):
				view_name = getattr(getattr(pvm, "view_menu", None), "name", None)
				perm_name = getattr(getattr(pvm, "permission", None), "name", None)
				if not (view_name and perm_name):
					continue
				view_id = f"view_{view_name}"
				if view_name not in view_names_seen:
					view_names_seen.add(view_name)
					nodes.append({"id": view_id, "label": view_name, "type": "view"})
				edges.append({
					"id": f"pv_{pvm.id}",
					"source": f"role_{role.id}",
					"target": view_id,
					"type": "permission",
					"perm_name": perm_name,
				})

		return jsonify({"nodes": nodes, "edges": edges})

	# ── Role CRUD ──────────────────────────────────────────────────────────────

	@expose("/api/roles", methods=["POST"])
	@has_access
	def api_create_role(self):
		body = request.get_json(force=True) or {}
		name = (body.get("name") or "").strip()
		if not name:
			return jsonify({"error": "name is required"}), 400
		sm = self._secman()
		role = sm.find_role(name)
		if role:
			return jsonify({"error": f"Role '{name}' already exists"}), 409
		role = sm.add_role(name)
		return jsonify({"id": role.id, "name": role.name}), 201

	@expose("/api/roles/<int:role_id>", methods=["DELETE"])
	@has_access
	def api_delete_role(self, role_id: int):
		sm = self._secman()
		session = self._get_session()
		role = session.get(sm.role_model, role_id)
		if not role:
			return jsonify({"error": "Role not found"}), 404
		try:
			session.delete(role)
			session.commit()
		except Exception as exc:
			session.rollback()
			log.error("api_delete_role: %s", exc)
			return jsonify({"error": str(exc)}), 500
		return jsonify({"ok": True})

	# ── Permission CRUD ────────────────────────────────────────────────────────

	@expose("/api/permissions", methods=["POST"])
	@has_access
	def api_grant_permission(self):
		body = request.get_json(force=True) or {}
		role_id = body.get("role_id")
		view_name = (body.get("view_name") or "").strip()
		permission_name = (body.get("permission_name") or "").strip()
		if not (role_id and view_name and permission_name):
			return jsonify({"error": "role_id, view_name, permission_name required"}), 400
		sm = self._secman()
		session = self._get_session()
		role = session.get(sm.role_model, int(role_id))
		if not role:
			return jsonify({"error": "Role not found"}), 404
		pv = sm.find_permission_view_menu(permission_name, view_name)
		if pv is None:
			pv = sm.add_permission_view_menu(permission_name, view_name)
		sm.add_permission_role(role, pv)
		return jsonify({"ok": True, "pv_id": pv.id}), 201

	@expose("/api/permissions/<int:pv_id>", methods=["DELETE"])
	@has_access
	def api_revoke_permission(self, pv_id: int):
		sm = self._secman()
		session = self._get_session()
		pv = session.get(sm.permissionview_model, pv_id)
		if not pv:
			return jsonify({"error": "PermissionView not found"}), 404
		for role in getattr(pv, "role", []):
			sm.del_permission_role(role, pv)
		return jsonify({"ok": True})

	# ── YAML export / import ───────────────────────────────────────────────────

	@expose("/api/export/yaml")
	@has_access
	def api_export_yaml(self):
		sm = self._secman()
		try:
			yaml_text = sm.export_yaml()
		except RuntimeError as exc:
			return jsonify({"error": str(exc)}), 500
		return jsonify({"yaml": yaml_text})

	@expose("/api/import/yaml", methods=["POST"])
	@has_access
	def api_import_yaml(self):
		body = request.get_json(force=True) or {}
		yaml_text = body.get("yaml_text", "")
		dry_run = bool(body.get("dry_run", False))
		sm = self._secman()
		try:
			result = sm.import_yaml(yaml_text, dry_run=dry_run)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 400
		return jsonify(result)

	# ── Health check ───────────────────────────────────────────────────────────

	@expose("/api/health-check")
	@has_access
	def api_health_check(self):
		sm = self._secman()
		findings = sm.security_health_check()
		return jsonify({"findings": findings})

	# ── Simulation ─────────────────────────────────────────────────────────────

	@expose("/api/simulate", methods=["POST"])
	@has_access
	def api_simulate(self):
		body = request.get_json(force=True) or {}
		role_id = body.get("role_id")
		if not role_id:
			return jsonify({"error": "role_id required"}), 400
		sm = self._secman()
		session = self._get_session()
		role = session.get(sm.role_model, int(role_id))
		if not role:
			return jsonify({"error": "Role not found"}), 404
		accessible: list[str] = []
		seen: set[str] = set()
		for pvm in getattr(role, "permissions", []):
			view_name = getattr(getattr(pvm, "view_menu", None), "name", None)
			if view_name and view_name not in seen:
				seen.add(view_name)
				accessible.append(view_name)
		return jsonify({"role": role.name, "accessible_views": sorted(accessible)})

	# ── Templates ──────────────────────────────────────────────────────────────

	@expose("/api/templates")
	@has_access
	def api_list_templates(self):
		return jsonify({"templates": list(ROLE_TEMPLATES.keys())})

	@expose("/api/templates/apply", methods=["POST"])
	@has_access
	def api_apply_template(self):
		body = request.get_json(force=True) or {}
		template_name = (body.get("template_name") or "").strip()
		role_name = (body.get("role_name") or template_name).strip()
		if not template_name:
			return jsonify({"error": "template_name required"}), 400
		tpl = ROLE_TEMPLATES.get(template_name)
		if not tpl:
			return jsonify({"error": f"Template '{template_name}' not found"}), 404

		sm = self._secman()
		role = sm.find_role(role_name) or sm.add_role(role_name)
		added: list[str] = []

		# Templates use view_pattern; for simplicity we apply to all registered view menus
		all_view_menus = sm.get_all_view_menu()
		for perm_block in tpl.get("permissions", []):
			pattern = perm_block.get("view_pattern", "*")
			actions = perm_block.get("actions", [])
			for vm in all_view_menus:
				if pattern != "*" and not vm.name.startswith(pattern.rstrip("*")):
					continue
				for action_name in actions:
					pv = sm.find_permission_view_menu(action_name, vm.name)
					if pv is None:
						pv = sm.add_permission_view_menu(action_name, vm.name)
					if pv and pv not in role.permissions:
						sm.add_permission_role(role, pv)
						added.append(f"{action_name}@{vm.name}")

		return jsonify({"ok": True, "role": role_name, "added": len(added)})

	# ── Snapshots ──────────────────────────────────────────────────────────────

	@expose("/api/snapshots", methods=["POST"])
	@has_access
	def api_take_snapshot(self):
		body = request.get_json(force=True) or {}
		name = (body.get("name") or "").strip()
		if not name:
			return jsonify({"error": "name required"}), 400

		sm = self._secman()
		session = self._get_session()

		try:
			yaml_text = sm.export_yaml()
		except RuntimeError as exc:
			return jsonify({"error": str(exc)}), 500

		from pgappforge.models.security_designer_models import SecuritySnapshot
		snap = SecuritySnapshot()
		snap.name = name
		snap.snapshot_json = {"yaml": yaml_text}
		snap.taken_at = datetime.now(timezone.utc).replace(tzinfo=None)
		try:
			uid = current_user.id if current_user and current_user.is_authenticated else None
		except Exception:
			uid = None
		snap.taken_by_id = uid

		try:
			session.add(snap)
			session.commit()
		except Exception as exc:
			session.rollback()
			log.error("api_take_snapshot: %s", exc)
			return jsonify({"error": str(exc)}), 500

		return jsonify({"ok": True, "id": snap.id, "name": snap.name}), 201

	@expose("/api/snapshots")
	@has_access
	def api_list_snapshots(self):
		from sqlalchemy import select as sa_select
		from pgappforge.models.security_designer_models import SecuritySnapshot
		session = self._get_session()
		snaps = session.execute(sa_select(SecuritySnapshot).order_by(SecuritySnapshot.taken_at.desc())).scalars().all()
		return jsonify({
			"snapshots": [
				{
					"id": s.id,
					"name": s.name,
					"description": s.description,
					"taken_at": s.taken_at.isoformat() if s.taken_at else None,
					"taken_by_id": s.taken_by_id,
				}
				for s in snaps
			]
		})

	# ── Diff ───────────────────────────────────────────────────────────────────

	@expose("/api/diff")
	@has_access
	def api_diff(self):
		snapshot_id = request.args.get("snapshot_id")
		if not snapshot_id:
			return jsonify({"error": "snapshot_id query param required"}), 400

		from sqlalchemy import select as sa_select
		from pgappforge.models.security_designer_models import SecuritySnapshot
		session = self._get_session()
		snap = session.get(SecuritySnapshot, int(snapshot_id))
		if not snap:
			return jsonify({"error": "Snapshot not found"}), 404

		sm = self._secman()
		try:
			import yaml as _yaml
			old_data = _yaml.safe_load(snap.snapshot_json.get("yaml", "")) or {}
		except Exception:
			old_data = {}

		# Build sets of role names and perm strings from old snapshot
		old_roles: set[str] = {r["name"] for r in old_data.get("roles", [])}
		old_perms: set[str] = set()
		for r in old_data.get("roles", []):
			for p in r.get("permissions", []):
				old_perms.add(f"{r['name']}:{p.get('permission')}@{p.get('view')}")

		# Build sets from current state
		cur_roles: set[str] = set()
		cur_perms: set[str] = set()
		for role in sm.get_all_roles():
			cur_roles.add(role.name)
			for pvm in getattr(role, "permissions", []):
				vname = getattr(getattr(pvm, "view_menu", None), "name", "")
				pname = getattr(getattr(pvm, "permission", None), "name", "")
				if vname and pname:
					cur_perms.add(f"{role.name}:{pname}@{vname}")

		return jsonify({
			"snapshot_id": int(snapshot_id),
			"added_roles": sorted(cur_roles - old_roles),
			"removed_roles": sorted(old_roles - cur_roles),
			"added_permissions": sorted(cur_perms - old_perms),
			"removed_permissions": sorted(old_perms - cur_perms),
		})
