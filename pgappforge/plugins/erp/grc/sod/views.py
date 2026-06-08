"""
pgappforge/plugins/erp/grc/sod/views.py

Flask views for the GRC Segregation of Duties (SoD) plugin.

Registered views:
  SodAnalyzerView  — dashboard + bulk_scan endpoint
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import current_app, jsonify, make_response

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _tenant_id() -> str:
	return str(current_app.config.get("DEFAULT_TENANT_ID", ""))


# ---------------------------------------------------------------------------
# SodAnalyzerView
# ---------------------------------------------------------------------------

class SodAnalyzerView(BaseView):
	"""SoD conflict analyzer — dashboard and bulk scan.

	GET  /grc/sod/            — conflict dashboard (HTML)
	POST /grc/sod/bulk_scan   — trigger full-population scan, returns JSON
	"""

	route_base = "/grc/sod"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		from flask import render_template
		conflicts = []
		try:
			from pgappforge.plugins.erp.grc.sod.models import SodConflict
			session = _get_session()
			q = (
				sa.select(SodConflict)
				.where(SodConflict.tenant_id == _tenant_id())
				.order_by(sa.desc(SodConflict.detected_at))
				.limit(500)
			)
			conflicts = session.execute(q).scalars().all()
		except Exception:
			log.exception("SodAnalyzerView.dashboard: failed to load conflicts")
			conflicts = []

		return render_template("grc/sod_dashboard.html", conflicts=conflicts)

	@expose("/bulk_scan", methods=["POST"])
	@has_access
	def bulk_scan(self):
		try:
			from pgappforge.plugins.erp.grc.sod.services import SodAnalyzerService
			session = _get_session()
			result = SodAnalyzerService().bulk_scan(session, tenant_id=_tenant_id())
			session.commit()
			return jsonify({"ok": True, "result": result})
		except Exception as exc:
			log.exception("SodAnalyzerView.bulk_scan: scan failed")
			return jsonify({"ok": False, "error": str(exc)}), 500


__all__ = ["SodAnalyzerView"]
