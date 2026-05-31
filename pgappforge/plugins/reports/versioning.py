"""
ReportForge report versioning — publish, history, restore.

Accessible at /reportforge/reports/<id>/versions
"""

from __future__ import annotations

import json
import logging

import sqlalchemy as sa
from ._utils import _he
from flask import abort, jsonify, make_response, request
from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)



def _snapshot(report, session) -> dict:
	"""Capture the full report definition as a JSON-serialisable dict."""
	from .models import ReportBand, ReportField, ReportParameter
	bands = []
	for band in report.band_list():
		fields = []
		for f in band.field_list():
			fields.append({
				"field_type": f.field_type.value,
				"x_mm": f.x_mm, "y_mm": f.y_mm,
				"width_mm": f.width_mm, "height_mm": f.height_mm,
				"data_binding": f.data_binding,
				"format_string": f.format_string,
				"compute": getattr(f, "compute", None),
				"link_url_template": getattr(f, "link_url_template", None),
				"style": dict(f.style or {}),
			})
		bands.append({
			"band_type": band.band_type.value,
			"position": band.position,
			"height_mm": band.height_mm,
			"background_color": band.background_color,
			"style": dict(band.style or {}),
			"fields": fields,
		})
	params = [
		{"name": p.name, "type": p.param_type.value, "label": p.label,
		 "default_value": p.default_value, "required": p.required,
		 "options_sql": getattr(p, "options_sql", None),
		 "depends_on":  getattr(p, "depends_on", None)}
		for p in report.parameters
	]
	return {
		"name":             report.name,
		"description":      report.description,
		"data_source":      report.data_source,
		"group_field":      report.group_field,
		"paper_size":       report.paper_size.value,
		"orientation":      report.orientation.value,
		"page_config":      dict(report.page_config or {}),
		"company_name":     report.company_name,
		"logo_url":         report.logo_url,
		"primary_color":    report.primary_color,
		"secondary_color":  report.secondary_color,
		"watermark_text":   report.watermark_text,
		"template_key":     report.template_key,
		"bands":  bands,
		"params": params,
	}


def _restore(report, snap: dict, session) -> None:
	"""Restore a report from a snapshot dict, replacing all bands/fields/params.

	Wrapped in a savepoint so a partial failure rolls back cleanly — the report
	is never left in a half-restored, data-corrupted state.

	NOTE: snapshot deliberately excludes governance fields (category_id,
	is_public, owner_id, grants, subscriptions) — only content is versioned.
	"""
	from .models import (
		ReportBand, ReportField, ReportParameter,
		BandType, FieldType, ParameterType,
	)
	sp = session.begin_nested()
	try:
		# 1. Clear existing content
		session.execute(sa.delete(ReportBand).where(ReportBand.report_id == report.id))
		session.execute(sa.delete(ReportParameter).where(ReportParameter.report_id == report.id))
		session.flush()

		# 2. Restore scalar fields
		for key in ("name", "description", "data_source", "group_field",
		            "company_name", "logo_url", "primary_color", "secondary_color",
		            "watermark_text", "template_key"):
			if key in snap:
				setattr(report, key, snap[key])
		if "page_config" in snap:
			report.page_config = snap["page_config"]

		# 3. Restore bands + fields
		for pos, band_def in enumerate(snap.get("bands", [])):
			try:
				btype = BandType(band_def["band_type"])
			except ValueError:
				btype = BandType.DETAIL
			band = ReportBand(
				report_id=report.id,
				band_type=btype,
				position=pos,
				height_mm=float(band_def.get("height_mm", 20)),
				background_color=band_def.get("background_color", "#ffffff"),
				style=band_def.get("style", {}),
			)
			session.add(band)
			session.flush()
			for field_def in band_def.get("fields", []):
				try:
					ftype = FieldType(field_def["field_type"])
				except ValueError:
					ftype = FieldType.TEXT
				session.add(ReportField(
					band_id=band.id,
					field_type=ftype,
					x_mm=float(field_def.get("x_mm", 0)),
					y_mm=float(field_def.get("y_mm", 0)),
					width_mm=float(field_def.get("width_mm", 40)),
					height_mm=float(field_def.get("height_mm", 8)),
					data_binding=field_def.get("data_binding"),
					format_string=field_def.get("format_string"),
					compute=field_def.get("compute"),
					link_url_template=field_def.get("link_url_template"),
					style=field_def.get("style", {}),
				))

		# 4. Restore parameters
		for param_def in snap.get("params", []):
			try:
				ptype = ParameterType(param_def.get("type", "string"))
			except ValueError:
				ptype = ParameterType.STRING
			session.add(ReportParameter(
				report_id=report.id,
				name=param_def["name"],
				param_type=ptype,
				label=param_def.get("label"),
				default_value=param_def.get("default_value"),
				required=bool(param_def.get("required", False)),
				options_sql=param_def.get("options_sql"),
				depends_on=param_def.get("depends_on"),
			))

		sp.commit()
	except Exception:
		sp.rollback()
		raise  # caller returns HTTP 500


class ReportVersionView(BaseView):
	"""
	Report version history and publish/restore.

	GET  /reportforge/reports/<id>/versions          — HTML version list
	POST /reportforge/reports/<id>/versions/publish  — create snapshot, mark published
	POST /reportforge/reports/<id>/versions/<v>/restore — restore to version v
	"""

	route_base   = "/reportforge/reports"
	default_view = "index"

	def _get_session(self):
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		return ab.session if ab else current_app.extensions.get("sqlalchemy").session

	@expose("/<int:report_id>/versions")
	@has_access
	def version_list(self, report_id: int):
		from .models import Report, ReportVersion
		session = self._get_session()
		report  = session.get(Report, report_id)
		if report is None:
			abort(404)
		versions = session.execute(
			sa.select(ReportVersion)
			.where(ReportVersion.report_id == report_id)
			.order_by(ReportVersion.version.desc())
		).scalars().all()

		rows = ""
		for v in versions:
			is_current   = (v.version == report.current_version)
			tr_class     = ' class="table-success fw-bold"' if is_current else ""
			badge        = '<span class="badge bg-success">Current</span>' if is_current else ""
			restore_btn  = "" if is_current else (
				f'<button class="btn btn-xs btn-outline-warning" '
				f'onclick="restoreV({v.version})">Restore</button>'
			)
			created      = v.created_on.strftime("%Y-%m-%d %H:%M") if v.created_on else ""
			rows += (
				f'<tr{tr_class}>'
				f'<td>v{v.version}</td>'
				f'<td>{created}</td>'
				f'<td>{_he(v.note or "")}</td>'
				f'<td>{badge}{restore_btn}</td>'
				f'</tr>'
			)

		html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head><body style="padding:24px;background:#f4f6fa">
<div style="max-width:700px;margin:0 auto">
<h4 class="mb-3">Version History: {_he(report.name)}</h4>
<div class="mb-3 d-flex gap-2">
  <input id="vnote" class="form-control form-control-sm" style="max-width:300px" placeholder="Optional note for this version">
  <button class="btn btn-success btn-sm" onclick="publishNow()">
    <i class="fas fa-check me-1"></i>Publish Current Version
  </button>
  <a href="/reports/designer/{report_id}" class="btn btn-outline-secondary btn-sm">
    &larr; Back to Designer
  </a>
</div>
<table class="table table-sm table-bordered bg-white">
  <thead><tr><th>Version</th><th>Published</th><th>Note</th><th></th></tr></thead>
  <tbody>{rows or '<tr><td colspan="4" class="text-muted">No versions published yet</td></tr>'}</tbody>
</table>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
const RID = {report_id};
async function publishNow(){{
  const note=document.getElementById('vnote').value;
  const r=await fetch('/reportforge/reports/'+RID+'/versions/publish',
    {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{note}})}});
  const d=await r.json();
  if(d.ok) location.reload(); else alert(d.error);
}}
async function restoreV(v){{
  if(!confirm('Restore to version '+v+'? Current unsaved changes will be overwritten.'))return;
  const r=await fetch('/reportforge/reports/'+RID+'/versions/'+v+'/restore',{{method:'POST'}});
  const d=await r.json();
  if(d.ok) location.reload(); else alert(d.error);
}}
</script>
</body></html>"""
		return make_response(html, 200)

	@expose("/<int:report_id>/versions/publish", methods=["POST"])
	@has_access
	def publish(self, report_id: int):
		from flask_login import current_user
		from .models import Report, ReportVersion
		from .acl import can as _can
		session = self._get_session()
		report  = session.get(Report, report_id)
		if report is None:
			abort(404)
		if not _can(current_user, report, "edit", session):
			abort(403)

		# Determine next version number
		last = session.execute(
			sa.select(sa.func.max(ReportVersion.version))
			.where(ReportVersion.report_id == report_id)
		).scalar() or 0
		ver = last + 1

		data = request.get_json(silent=True) or {}
		snap = _snapshot(report, session)
		rv   = ReportVersion(
			report_id=report_id,
			version=ver,
			snapshot_json=snap,
			note=data.get("note", ""),
			created_by=getattr(current_user, "id", None),
		)
		session.add(rv)
		report.current_version = ver
		report.is_draft = False
		session.commit()
		return jsonify({"ok": True, "version": ver})

	@expose("/<int:report_id>/versions/<int:version>/restore", methods=["POST"])
	@has_access
	def restore(self, report_id: int, version: int):
		from flask_login import current_user
		from .models import Report, ReportVersion
		from .acl import can as _can
		session = self._get_session()
		report_check = session.get(Report, report_id)
		if report_check is not None and not _can(current_user, report_check, "edit", session):
			abort(403)
		rv = session.execute(
			sa.select(ReportVersion)
			.where(ReportVersion.report_id == report_id)
			.where(ReportVersion.version == version)
		).scalar_one_or_none()
		if rv is None:
			abort(404)
		report = session.get(Report, report_id)
		_restore(report, rv.snapshot_json, session)
		report.is_draft = True  # mark as draft until re-published
		session.commit()
		# Invalidate render cache
		try:
			from .engine import ReportEngine
			ReportEngine(session).cache_invalidate(report_id)
		except Exception:
			pass
		return jsonify({"ok": True, "restored_to_version": version})
