"""
Visual RBAC management for pgappforge.

Provides admin views for:
- Drag-and-drop permission matrix (roles × views)
- Impact assessment ("what changes if I modify this role?")
- D3.js role hierarchy graph
- Export to Keycloak JSON, SpiceDB schema, CSV

Enable by adding to AppBuilder::

    from pgappforge.security.visual_rbac import VisualRBACView
    appbuilder.add_view_no_menu(VisualRBACView)
    appbuilder.add_link('RBAC Manager', href='/security/rbac/',
                        icon='fa-shield', category='Security')
"""
from __future__ import annotations

import json
import csv
import io
from flask import request, jsonify, Response, current_app
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access

_D3_CDN = '<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>'


class VisualRBACView(BaseView):
	"""Visual RBAC management — drag-drop matrix, impact assessment, D3 hierarchy."""

	route_base = "/security/rbac"
	default_view = "matrix"

	# ─── Permission Matrix ────────────────────────────────────────────────────

	@expose("/")
	@expose("/matrix")
	@has_access
	def matrix(self):
		"""Drag-and-drop role × view permission matrix."""
		sm = self.appbuilder.sm
		roles = sm.get_all_roles()
		view_menus = sm.get_all_view_menu()
		perms = sm.get_all_permissions()

		# Build {role_id → {view_menu_id → [permission_names]}} map
		role_perms: dict[int, dict[int, list[str]]] = {}
		for role in roles:
			role_perms[role.id] = {}
			for pv in role.permissions:
				vm = pv.view_menu
				p = pv.permission
				if vm and p:
					role_perms[role.id].setdefault(vm.id, []).append(p.name)

		return self.render_template_string(
			_MATRIX_TEMPLATE,
			roles=roles,
			view_menus=view_menus,
			role_perms=json.dumps(role_perms), role_perms_dict=role_perms,
		)

	@expose("/matrix/update", methods=["POST"])
	@has_access
	def matrix_update(self):
		"""Apply a permission diff from the matrix UI.

		Expects JSON: {add: [[role_id, vm_id, perm_name], ...],
		               remove: [[role_id, vm_id, perm_name], ...]}
		"""
		sm = self.appbuilder.sm
		session = self.appbuilder.get_session
		data = request.get_json() or {}
		applied, errors = 0, []

		from pgappforge.security.sqla.models import Role, ViewMenu

		for role_id, vm_id, perm_name in data.get("add", []):
			try:
				role = session.get(Role, role_id)
				vm = session.get(ViewMenu, vm_id)
				if role and vm:
					pv = sm.find_permission_view_menu(perm_name, vm.name)
					if pv:
						sm.add_permission_role(role, pv)
						applied += 1
			except Exception as exc:
				errors.append(str(exc))

		for role_id, vm_id, perm_name in data.get("remove", []):
			try:
				role = session.get(Role, role_id)
				vm = session.get(ViewMenu, vm_id)
				if role and vm:
					pv = sm.find_permission_view_menu(perm_name, vm.name)
					if pv:
						sm.del_permission_role(role, pv)
						applied += 1
			except Exception as exc:
				errors.append(str(exc))

		return jsonify({"applied": applied, "errors": errors})

	# ─── Impact Assessment ────────────────────────────────────────────────────

	@expose("/impact/<int:role_id>")
	@has_access
	def impact(self, role_id: int):
		"""Show what this role grants and who would be affected by changes."""
		sm = self.appbuilder.sm
		from pgappforge.security.sqla.models import Role
		role = self.appbuilder.get_session.get(Role, role_id)
		if not role:
			return self.render_template_string(
				"<h3>Role not found</h3>", title="Impact Assessment"
			)

		# Users with this role
		users = [u for u in sm.get_all_users() if any(r.id == role_id for r in u.roles)]

		# Permissions granted
		granted_pvs = list(role.permissions)

		# Grouped by action type
		by_action: dict[str, list[str]] = {}
		for pv in granted_pvs:
			action = pv.permission.name if pv.permission else "?"
			vm = pv.view_menu.name if pv.view_menu else "?"
			by_action.setdefault(action, []).append(vm)

		return self.render_template_string(
			_IMPACT_TEMPLATE,
			role=role,
			users=users,
			by_action=by_action,
			granted_pvs=granted_pvs,
		)

	# ─── Hierarchy Graph ──────────────────────────────────────────────────────

	@expose("/hierarchy")
	@has_access
	def hierarchy(self):
		"""D3.js force-directed graph of roles and their users."""
		sm = self.appbuilder.sm
		roles = sm.get_all_roles()
		users = sm.get_all_users()

		nodes = [{"id": f"role_{r.id}", "label": r.name, "type": "role"} for r in roles]
		nodes += [{"id": f"user_{u.id}", "label": u.username, "type": "user"} for u in users]

		links = []
		for u in users:
			for r in u.roles:
				links.append({"source": f"user_{u.id}", "target": f"role_{r.id}"})

		graph_data = json.dumps({"nodes": nodes, "links": links})
		return self.render_template_string(_HIERARCHY_TEMPLATE, graph_data=graph_data)

	# ─── Export Endpoints ─────────────────────────────────────────────────────

	@expose("/export/keycloak")
	@has_access
	def export_keycloak(self):
		"""Download Keycloak realm JSON representation of current RBAC."""
		try:
			from pgappforge.security.integrations import KeycloakIntegration
			realm = KeycloakIntegration().export_realm(self.appbuilder)
			return Response(
				json.dumps(realm, indent=2),
				mimetype="application/json",
				headers={"Content-Disposition": "attachment; filename=keycloak-realm.json"},
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/export/spicedb")
	@has_access
	def export_spicedb(self):
		"""Download SpiceDB schema text for current RBAC."""
		try:
			from pgappforge.security.integrations import SpiceDBIntegration
			schema = SpiceDBIntegration().export_schema(self.appbuilder)
			return Response(
				schema,
				mimetype="text/plain",
				headers={"Content-Disposition": "attachment; filename=spicedb-schema.zed"},
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	@expose("/export/csv")
	@has_access
	def export_csv(self):
		"""Download roles/permissions as CSV."""
		sm = self.appbuilder.sm
		out = io.StringIO()
		writer = csv.writer(out)
		writer.writerow(["Role", "Permission", "ViewMenu"])
		for role in sm.get_all_roles():
			for pv in role.permissions:
				writer.writerow([
					role.name,
					pv.permission.name if pv.permission else "",
					pv.view_menu.name if pv.view_menu else "",
				])
		return Response(
			out.getvalue(),
			mimetype="text/csv",
			headers={"Content-Disposition": "attachment; filename=rbac.csv"},
		)


# ─── Templates ────────────────────────────────────────────────────────────────

_MATRIX_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <title>RBAC Permission Matrix</title>
  <link rel="stylesheet"
    href="{{ url_for('static', filename='appbuilder/css/bootstrap.min.css') }}">
  <style>
    .matrix-table th { writing-mode: vertical-rl; transform: rotate(180deg);
                        height:120px; white-space:nowrap; font-size:0.8em; }
    .matrix-table td { text-align:center; padding:4px; }
    .perm-check { cursor:pointer; }
    .perm-check:checked + label { color: #27ae60; }
    .export-bar { margin-bottom:12px; }
  </style>
</head>
<body>
<div class="container-fluid" style="margin-top:20px">
  <h2><i class="fa fa-shield"></i> RBAC Permission Matrix</h2>
  <div class="export-bar">
    <a href="{{ url_for('VisualRBACView.export_keycloak') }}" class="btn btn-sm btn-default">
      ↓ Keycloak JSON</a>
    <a href="{{ url_for('VisualRBACView.export_spicedb') }}" class="btn btn-sm btn-default">
      ↓ SpiceDB Schema</a>
    <a href="{{ url_for('VisualRBACView.export_csv') }}" class="btn btn-sm btn-default">
      ↓ CSV</a>
    <a href="{{ url_for('VisualRBACView.hierarchy') }}" class="btn btn-sm btn-info">
      <i class="fa fa-sitemap"></i> Role Hierarchy</a>
  </div>
  <div class="table-responsive">
  <table class="table table-bordered matrix-table" id="rbacMatrix">
    <thead>
      <tr>
        <th>View / Permission</th>
        {% for role in roles %}
        <th><a href="{{ url_for('VisualRBACView.impact', role_id=role.id) }}">{{ role.name }}</a></th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for vm in view_menus %}
      <tr>
        <td><strong>{{ vm.name }}</strong></td>
        {% for role in roles %}
        <td>
          <input type="checkbox" class="perm-check"
            data-role="{{ role.id }}" data-vm="{{ vm.id }}"
            {% if role_perms_dict.get(role.id, {}).get(vm.id) %}checked{% endif %}>
        </td>
        {% endfor %}
      </tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
  <button class="btn btn-primary" id="saveBtn">Save changes</button>
  <span id="saveStatus" style="margin-left:10px"></span>
</div>
<script>
var rolePerms = {{ role_perms | safe }};
var changes = {add: [], remove: []};
document.querySelectorAll('.perm-check').forEach(function(cb) {
  var orig = cb.checked;
  cb.addEventListener('change', function() {
    var r = parseInt(cb.dataset.role), v = parseInt(cb.dataset.vm);
    var entry = [r, v, 'can_list'];
    if (cb.checked) { changes.add.push(entry); }
    else { changes.remove.push(entry); }
    document.getElementById('saveBtn').className = 'btn btn-warning';
  });
});
document.getElementById('saveBtn').addEventListener('click', function() {
  fetch('{{ url_for("VisualRBACView.matrix_update") }}', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(changes)
  }).then(r => r.json()).then(function(d) {
    document.getElementById('saveStatus').textContent =
      'Saved: ' + d.applied + ' changes' + (d.errors.length ? ' (' + d.errors.length + ' errors)' : '');
    document.getElementById('saveBtn').className = 'btn btn-primary';
    changes = {add: [], remove: []};
  });
});
</script>
</body>
</html>
"""

_IMPACT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <title>Impact: {{ role.name }}</title>
  <link rel="stylesheet"
    href="{{ url_for('static', filename='appbuilder/css/bootstrap.min.css') }}">
</head>
<body>
<div class="container" style="margin-top:20px">
  <h2><i class="fa fa-search"></i> Impact Assessment: <strong>{{ role.name }}</strong></h2>
  <div class="row">
    <div class="col-md-4">
      <div class="panel panel-warning">
        <div class="panel-heading">Users with this role ({{ users|length }})</div>
        <ul class="list-group">
          {% for u in users %}
          <li class="list-group-item">{{ u.username }} &lt;{{ u.email }}&gt;</li>
          {% else %}
          <li class="list-group-item text-muted">No users assigned</li>
          {% endfor %}
        </ul>
      </div>
    </div>
    <div class="col-md-8">
      <div class="panel panel-info">
        <div class="panel-heading">Permissions granted ({{ granted_pvs|length }})</div>
        <table class="table table-condensed">
          <thead><tr><th>Action</th><th>Views</th></tr></thead>
          <tbody>
            {% for action, vms in by_action.items() %}
            <tr>
              <td><span class="label label-default">{{ action }}</span></td>
              <td>{{ vms | join(', ') }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <a href="{{ url_for('VisualRBACView.matrix') }}" class="btn btn-default">
    ← Back to Matrix</a>
</div>
</body>
</html>
"""

_HIERARCHY_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <title>Role Hierarchy</title>
  <link rel="stylesheet"
    href="{{ url_for('static', filename='appbuilder/css/bootstrap.min.css') }}">
  """ + _D3_CDN + """
  <style>
    #graph { width:100%; height:600px; border:1px solid #ddd; border-radius:4px; }
    .role-node circle { fill:#2980b9; }
    .user-node circle { fill:#27ae60; }
    .node text { font-size:11px; fill:#333; }
    .link { stroke:#ccc; stroke-opacity:0.6; }
  </style>
</head>
<body>
<div class="container-fluid" style="margin-top:20px">
  <h2><i class="fa fa-sitemap"></i> Role Hierarchy</h2>
  <p>
    <span style="color:#2980b9">●</span> Roles &nbsp;
    <span style="color:#27ae60">●</span> Users
  </p>
  <svg id="graph"></svg>
</div>
<script>
var data = {{ graph_data | safe }};
var svg = d3.select('#graph');
var W = svg.node().getBoundingClientRect().width || 800, H = 600;
svg.attr('viewBox', '0 0 ' + W + ' ' + H);

var sim = d3.forceSimulation(data.nodes)
  .force('link', d3.forceLink(data.links).id(d => d.id).distance(80))
  .force('charge', d3.forceManyBody().strength(-200))
  .force('center', d3.forceCenter(W/2, H/2));

var link = svg.append('g').selectAll('line')
  .data(data.links).join('line').attr('class', 'link').attr('stroke-width', 1.5);

var node = svg.append('g').selectAll('g')
  .data(data.nodes).join('g')
  .attr('class', d => d.type === 'role' ? 'role-node' : 'user-node')
  .call(d3.drag()
    .on('start', (e,d) => { if(!e.active) sim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
    .on('drag',  (e,d) => { d.fx=e.x; d.fy=e.y; })
    .on('end',   (e,d) => { if(!e.active) sim.alphaTarget(0); d.fx=null; d.fy=null; }));

node.append('circle').attr('r', d => d.type==='role' ? 12 : 7);
node.append('text').attr('dy', '0.35em').attr('x', d => d.type==='role' ? 16 : 10)
  .text(d => d.label);

sim.on('tick', function() {
  link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
  node.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');
});
</script>
</body>
</html>
"""
