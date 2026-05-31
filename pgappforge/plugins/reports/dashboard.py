"""
ReportForge dashboard builder — assembles multiple reports into a single page.

Accessible at /reportforge/dashboards/

Dashboard.layout_json schema::

    [
        {"report_id": 1, "x": 0, "y": 0, "w": 6, "h": 4, "params": {}},
        {"report_id": 2, "x": 6, "y": 0, "w": 6, "h": 4, "params": {}}
    ]

The grid is 12 columns wide (Bootstrap grid). Each tile renders an inline
HTML preview of its report. Dispatch sends all tiles as separate PDF attachments
or a combined HTML email.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import sqlalchemy as sa
from ._utils import _he
from flask import abort, jsonify, make_response, request
from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)



class DashboardView(BaseView):
	"""
	Dashboard builder and viewer.

	GET  /reportforge/dashboards/              — list dashboards
	GET  /reportforge/dashboards/<id>          — view dashboard (rendered HTML)
	POST /reportforge/dashboards/              — create dashboard
	PUT  /reportforge/dashboards/<id>          — update layout
	DELETE /reportforge/dashboards/<id>        — delete
	POST /reportforge/dashboards/<id>/dispatch — email all tiles as attachments
	"""

	route_base   = "/reportforge/dashboards"
	default_view = "index"

	def _get_session(self):
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		return ab.session if ab else current_app.extensions.get("sqlalchemy").session

	# ── List ──────────────────────────────────────────────────────────────

	@expose("/")
	@has_access
	def index(self):
		from .models import Dashboard
		session = self._get_session()
		boards  = session.execute(
			sa.select(Dashboard).order_by(Dashboard.name)
		).scalars().all()

		rows = "".join(
			f'<tr><td><a href="/reportforge/dashboards/{b.id}">{_he(b.name)}</a></td>'
			f'<td>{_he(b.description or "")}</td>'
			f'<td>{"Public" if b.is_public else "Private"}</td>'
			f'<td><a href="/reportforge/dashboards/{b.id}/edit" '
			f'class="btn btn-xs btn-outline-secondary">Edit</a></td></tr>'
			for b in boards
		)
		html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head><body style="padding:24px;background:#f4f6fa">
<div style="max-width:900px;margin:0 auto">
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4><i class="fas fa-th-large me-2 text-primary"></i>Dashboards</h4>
  <button class="btn btn-primary btn-sm" data-bs-toggle="modal" data-bs-target="#mNew">
    <i class="fas fa-plus me-1"></i>New Dashboard
  </button>
</div>
<table class="table table-sm table-bordered bg-white">
  <thead><tr><th>Name</th><th>Description</th><th>Visibility</th><th></th></tr></thead>
  <tbody>{rows or '<tr><td colspan="4" class="text-muted text-center">No dashboards yet</td></tr>'}</tbody>
</table></div>

<div class="modal fade" id="mNew" tabindex="-1">
<div class="modal-dialog"><div class="modal-content">
  <div class="modal-header"><h5 class="modal-title">New Dashboard</h5>
    <button class="btn-close" data-bs-dismiss="modal"></button></div>
  <div class="modal-body">
    <input id="dname" class="form-control mb-2" placeholder="Dashboard name">
    <textarea id="ddesc" class="form-control mb-2" rows="2" placeholder="Description"></textarea>
    <div class="form-check"><input class="form-check-input" type="checkbox" id="dpub">
    <label class="form-check-label" for="dpub">Public</label></div>
  </div>
  <div class="modal-footer">
    <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancel</button>
    <button class="btn btn-primary btn-sm" onclick="createBoard()">Create</button>
  </div>
</div></div></div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
async function createBoard(){{
  const r=await fetch('/reportforge/dashboards/',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{name:document.getElementById('dname').value,
      description:document.getElementById('ddesc').value,
      is_public:document.getElementById('dpub').checked}})}});
  const d=await r.json();
  if(d.ok) location.href='/reportforge/dashboards/'+d.id;
  else alert(d.error);
}}
</script></body></html>"""
		return make_response(html, 200)

	# ── View / render ─────────────────────────────────────────────────────

	@expose("/<int:board_id>")
	@has_access
	def view(self, board_id: int):
		from .models import Dashboard, Report
		from .engine import ReportEngine
		session = self._get_session()
		board   = session.get(Dashboard, board_id)
		if board is None:
			abort(404)

		from flask import current_app as _ca

		layout  = board.layout_json or []
		db_bind = None
		try:
			ab = _ca.extensions.get("appbuilder")
			db_bind = ab.session.bind if ab else _ca.extensions["sqlalchemy"].engine
		except Exception:
			pass

		def render_tile(tile: dict) -> tuple[dict, str]:
			"""Each worker uses its own session — SQLAlchemy Session is not thread-safe."""
			from sqlalchemy.orm import Session as _Sess
			rid    = tile.get("report_id")
			params = tile.get("params", {})
			try:
				with _Sess(bind=db_bind) as worker_session:
					worker_engine = ReportEngine(worker_session, preview_row_limit=20)
					html = worker_engine.generate_html(rid, params=params)
			except Exception as exc:
				html = f'<div class="alert alert-danger">{_he(str(exc))}</div>'
			return tile, html

		tiles_html: dict[int, str] = {}
		with ThreadPoolExecutor(max_workers=min(len(layout), 6) or 1) as pool:
			futures = {pool.submit(render_tile, tile): i for i, tile in enumerate(layout)}
			for fut in as_completed(futures):
				idx = futures[fut]
				try:
					tile, html = fut.result()
					tiles_html[idx] = (tile, html)
				except Exception as exc:
					tiles_html[idx] = (layout[idx], f'<div class="alert alert-danger">{_he(str(exc))}</div>')

		grid = ""
		for i in range(len(layout)):
			tile, inner = tiles_html.get(i, (layout[i], ""))
			w   = tile.get("w", 6)
			title_span = ""
			try:
				rep = session.get(Report, tile.get("report_id"))
				title_span = f'<div class="fw-bold mb-1" style="font-size:12px;color:#0066cc">{_he(rep.name if rep else "")}</div>'
			except Exception:
				pass
			grid += (
				f'<div class="col-md-{w} mb-3">'
				f'<div class="card" style="height:100%">'
				f'<div class="card-body p-2">{title_span}'
				f'<div style="overflow:auto;max-height:300px">{inner}</div>'
				f'</div></div></div>'
			)

		html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head><body style="background:#f4f6fa">
<div class="p-3">
<div class="d-flex justify-content-between align-items-center mb-3">
  <h5 class="mb-0"><i class="fas fa-th-large me-2 text-primary"></i>{_he(board.name)}</h5>
  <div class="d-flex gap-2">
    <a href="/reportforge/dashboards/{board_id}/edit" class="btn btn-outline-secondary btn-sm">
      <i class="fas fa-edit me-1"></i>Edit Layout
    </a>
    <button class="btn btn-primary btn-sm" onclick="location.reload()">
      <i class="fas fa-sync me-1"></i>Refresh
    </button>
  </div>
</div>
<div class="row">{grid}</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""
		return make_response(html, 200)

	# ── CRUD ──────────────────────────────────────────────────────────────

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from flask_login import current_user
		from .models import Dashboard
		data    = request.get_json(silent=True) or {}
		name    = (data.get("name") or "").strip()
		if not name:
			return jsonify({"ok": False, "error": "name required"}), 400
		session = self._get_session()
		board   = Dashboard(
			name=name,
			description=data.get("description", ""),
			layout_json=data.get("layout_json", []),
			is_public=bool(data.get("is_public", False)),
			owner_id=getattr(current_user, "id", None),
		)
		session.add(board)
		session.commit()
		return jsonify({"ok": True, "id": board.id})

	@expose("/<int:board_id>", methods=["PUT"])
	@has_access
	def update(self, board_id: int):
		from flask_login import current_user
		from .models import Dashboard
		from .acl import _is_admin
		from sqlalchemy.orm.attributes import flag_modified
		data    = request.get_json(silent=True) or {}
		session = self._get_session()
		board   = session.get(Dashboard, board_id)
		if board is None:
			abort(404)
		if board.owner_id != getattr(current_user, "id", None) and not _is_admin(current_user):
			abort(403)
		if "name"        in data: board.name        = data["name"]
		if "description" in data: board.description = data["description"]
		if "is_public"   in data: board.is_public   = bool(data["is_public"])
		if "layout_json" in data:
			board.layout_json = data["layout_json"]
			flag_modified(board, "layout_json")
		session.commit()
		return jsonify({"ok": True})

	@expose("/<int:board_id>", methods=["DELETE"])
	@has_access
	def delete(self, board_id: int):
		from .models import Dashboard
		session = self._get_session()
		board   = session.get(Dashboard, board_id)
		if board is None:
			abort(404)
		session.delete(board)
		session.commit()
		return jsonify({"ok": True})

	# ── Email dispatch ────────────────────────────────────────────────────

	@expose("/<int:board_id>/dispatch", methods=["POST"])
	@has_access
	def dispatch_board(self, board_id: int):
		"""Send all dashboard tiles as separate PDF attachments in one email."""
		from flask import current_app
		from flask_login import current_user
		from .models import Dashboard
		from .engine import ReportEngine
		from .dispatch import send_report_email
		from .models import DispatchStatus
		from .models import ReportDispatch

		to_email = request.form.get("to_email", "").strip()
		subject  = request.form.get("subject", "").strip()
		if not to_email:
			return jsonify({"ok": False, "error": "to_email required"}), 400

		session = self._get_session()
		board   = session.get(Dashboard, board_id)
		if board is None:
			abort(404)

		engine = ReportEngine(session)
		errors = []
		for tile in (board.layout_json or []):
			rid = tile.get("report_id")
			if not rid:
				continue
			try:
				report = engine._load_report(rid)
				data   = engine.generate_pdf(rid, tile.get("params", {}))
				d = ReportDispatch(
					report_id=rid,
					to_email=to_email,
					subject=subject or f"Dashboard: {board.name} — {report.name}",
					export_format="pdf",
					params_json=tile.get("params", {}),
					status=DispatchStatus.PENDING,
					created_by=getattr(current_user, "id", None),
				)
				session.add(d)
				session.flush()
				send_report_email(d, data, session, current_app._get_current_object())
			except Exception as exc:
				errors.append(str(exc))

		if errors:
			return jsonify({"ok": False, "errors": errors}), 500
		return jsonify({"ok": True})
