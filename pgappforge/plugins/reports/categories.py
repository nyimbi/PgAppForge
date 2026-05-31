"""
ReportForge category/folder management.

Provides a hierarchical folder structure for organising reports.
Accessible at /reportforge/categories/
"""

from __future__ import annotations
from ._session_mixin import ReportSessionMixin

import logging
from typing import Any

import sqlalchemy as sa
from ._utils import _he
from flask import abort, jsonify, make_response, request
from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)



class ReportCategoryView(ReportSessionMixin, BaseView):
	"""
	Folder/category management for ReportForge.

	Endpoints:
	  GET  /reportforge/categories/          — HTML tree view
	  GET  /reportforge/categories/api/tree  — JSON tree
	  POST /reportforge/categories/          — create category
	  DELETE /reportforge/categories/<id>    — delete category
	  PATCH  /reportforge/categories/<id>    — rename/reparent
	"""

	route_base   = "/reportforge/categories"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""HTML folder browser."""
		session = self._get_session()
		from .models import ReportCategory, Report
		cats = session.execute(
			sa.select(ReportCategory).order_by(ReportCategory.name)
		).scalars().all()

		def count_reports(cat_id):
			return session.execute(
				sa.select(sa.func.count()).select_from(Report)
				.where(Report.category_id == cat_id)
			).scalar() or 0

		rows = ""
		for c in cats:
			parent_name = ""
			if c.parent_id:
				parent = session.get(ReportCategory, c.parent_id)
				parent_name = f" / {_he(parent.name)}" if parent else ""
			n = count_reports(c.id)
			rows += (
				f'<tr>'
				f'<td><i class="fas {_he(c.icon)} me-2" style="color:{_he(c.color)}"></i>'
				f'{_he(c.name)}{parent_name}</td>'
				f'<td><a href="/reports/?category={c.id}" class="btn btn-xs btn-outline-primary">'
				f'{n} reports</a></td>'
				f'<td>'
				f'<button class="btn btn-xs btn-outline-danger" '
				f'onclick="delCat({c.id})">Delete</button></td></tr>'
			)

		html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head><body style="padding:24px;background:#f4f6fa">
<div style="max-width:800px;margin:0 auto">
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4><i class="fas fa-folder-open me-2 text-primary"></i>Report Categories</h4>
  <button class="btn btn-primary btn-sm" data-bs-toggle="modal" data-bs-target="#mNew">
    <i class="fas fa-plus me-1"></i>New Category
  </button>
</div>
<table class="table table-sm table-bordered bg-white">
  <thead><tr><th>Name</th><th>Reports</th><th></th></tr></thead>
  <tbody>{rows or '<tr><td colspan="3" class="text-muted text-center">No categories yet</td></tr>'}</tbody>
</table>
</div>

<div class="modal fade" id="mNew" tabindex="-1">
<div class="modal-dialog"><div class="modal-content">
  <div class="modal-header"><h5 class="modal-title">New Category</h5>
    <button class="btn-close" data-bs-dismiss="modal"></button></div>
  <div class="modal-body">
    <input id="cname" class="form-control mb-2" placeholder="Category name">
    <select id="cparent" class="form-select mb-2">
      <option value="">— Top level —</option>
      {''.join(f'<option value="{c.id}">{_he(c.name)}</option>' for c in cats)}
    </select>
    <div class="row g-2">
      <div class="col-6"><input type="color" id="ccolor" class="form-control form-control-color" value="#0066cc"></div>
      <div class="col-6"><input id="cicon" class="form-control" value="fa-folder" placeholder="FA icon class"></div>
    </div>
  </div>
  <div class="modal-footer">
    <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
    <button class="btn btn-primary btn-sm" onclick="createCat()">Create</button>
  </div>
</div></div></div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
async function createCat(){{
  const r=await fetch('/reportforge/categories/',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{name:document.getElementById('cname').value,
      parent_id:document.getElementById('cparent').value||null,
      color:document.getElementById('ccolor').value,
      icon:document.getElementById('cicon').value}})}});
  const d=await r.json();
  if(d.ok) location.reload(); else alert(d.error);
}}
async function delCat(id){{
  if(!confirm('Delete this category?'))return;
  await fetch('/reportforge/categories/'+id,{{method:'DELETE'}});
  location.reload();
}}
</script>
</body></html>"""
		return make_response(html, 200)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from flask_login import current_user
		from .models import ReportCategory
		data = request.get_json(silent=True) or {}
		name = (data.get("name") or "").strip()
		if not name:
			return jsonify({"ok": False, "error": "name required"}), 400
		session = self._get_session()
		cat = ReportCategory(
			name=name,
			parent_id=data.get("parent_id"),
			color=data.get("color", "#0066cc"),
			icon=data.get("icon", "fa-folder"),
			owner_id=getattr(current_user, "id", None),
		)
		session.add(cat)
		session.commit()
		return jsonify({"ok": True, "id": cat.id})

	@expose("/<int:cat_id>", methods=["DELETE"])
	@has_access
	def delete(self, cat_id: int):
		from flask_login import current_user
		from .models import ReportCategory
		from .acl import _is_admin
		session = self._get_session()
		cat = session.get(ReportCategory, cat_id)
		if cat is None:
			abort(404)
		if cat.owner_id != getattr(current_user, "id", None) and not _is_admin(current_user):
			abort(403)
		session.delete(cat)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<int:cat_id>", methods=["PATCH"])
	@has_access
	def update(self, cat_id: int):
		from flask_login import current_user
		from .models import ReportCategory
		from .acl import _is_admin
		data    = request.get_json(silent=True) or {}
		session = self._get_session()
		cat     = session.get(ReportCategory, cat_id)
		if cat is None:
			abort(404)
		if cat.owner_id != getattr(current_user, "id", None) and not _is_admin(current_user):
			abort(403)
		if "name"      in data: cat.name      = data["name"]
		if "parent_id" in data: cat.parent_id = data["parent_id"]
		if "color"     in data: cat.color     = data["color"]
		if "icon"      in data: cat.icon      = data["icon"]
		session.commit()
		return jsonify({"ok": True})

	@expose("/api/tree")
	@has_access
	def api_tree(self):
		from .models import ReportCategory
		session = self._get_session()
		cats = session.execute(sa.select(ReportCategory).order_by(ReportCategory.name)).scalars().all()
		return jsonify({"categories": [
			{"id": c.id, "name": c.name, "parent_id": c.parent_id,
			 "color": c.color, "icon": c.icon}
			for c in cats
		]})
