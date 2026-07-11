"""
pgappforge/plugins/erp/grc/sod/views.py

Flask views for the GRC Segregation of Duties (SoD) plugin.
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import current_app, jsonify, make_response, redirect
from pgappforge import ModelView, expose
from pgappforge.actions import action
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.grc.sod.models import SodConflict, SodViolation

log = logging.getLogger(__name__)


def _get_session():
	try:
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			session = ab.get_session
			return session() if callable(session) else session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _tenant_id() -> str:
	return str(current_app.config.get("DEFAULT_TENANT_ID", ""))


def _he(value: object) -> str:
	return (
		str(value if value is not None else "")
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{_he(title)}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		"<style>"
		"body{padding:24px}"
		".grc-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-bottom:18px}"
		".grc-card{border:1px solid #e5e7eb;border-radius:6px;background:#fff;padding:16px}"
		".grc-card h4{margin:0 0 12px;font-size:14px;font-weight:700}"
		".metric-row{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #f3f4f6;padding:7px 0}"
		".metric-row:last-child{border-bottom:0}"
		".metric-label{text-transform:capitalize;color:#374151}"
		".metric-value{font-weight:800;font-size:18px}"
		".grc-table{width:100%;border-collapse:collapse;background:#fff;margin-bottom:18px}"
		".grc-table th,.grc-table td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left}"
		".grc-table th{background:#f9fafb;font-size:12px;text-transform:uppercase;color:#374151}"
		".badge-risk{display:inline-block;border-radius:4px;padding:2px 8px;font-size:12px;font-weight:700;color:#fff}"
		"</style></head><body>"
		f"{body}</body></html>"
	)


def _severity_color(severity: str) -> str:
	value = (severity or "").lower()
	if value == "critical":
		return "#7f1d1d"
	if value == "high":
		return "#dc2626"
	if value == "medium":
		return "#ff5a1f"
	return "#0e9f6e"


class SodConflictView(ModelView):
	datamodel = SQLAInterface(SodConflict)
	list_columns = ["name", "function_a", "function_b", "risk_level", "control_category", "is_active"]
	label_columns = {
		"name": _("Conflict"),
		"function_a": _("Function A"),
		"function_b": _("Function B"),
		"risk_level": _("Severity"),
		"control_category": _("Control Category"),
		"is_active": _("Active"),
	}
	add_exclude_columns = ["id", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_at", "updated_at"]


class SodViolationView(ModelView):
	datamodel = SQLAInterface(SodViolation)
	list_columns = ["user_id", "conflict_id", "risk_level", "detected_at", "status", "accepted_by", "remediation_date"]
	label_columns = {
		"user_id": _("User"),
		"conflict_id": _("Conflict"),
		"risk_level": _("Severity"),
		"detected_at": _("Opened"),
		"status": _("Status"),
		"accepted_by": _("Accepted By"),
		"remediation_date": _("Remediation Date"),
	}
	add_exclude_columns = ["id", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_at", "updated_at"]

	@action('false_positive', 'Mark False Positive', 'Mark selected violations as false positives?', 'fa-flag')
	def false_positive(self, items):
		for item in items:
			item.status = 'false_positive'
		self.datamodel.session.commit()
		return redirect(self.get_redirect())

	@action('accept_risk', 'Accept Risk', 'Accept risk for selected violations?', 'fa-check-circle')
	def accept_risk(self, items):
		for item in items:
			item.status = 'accepted'
		self.datamodel.session.commit()
		return redirect(self.get_redirect())


class SodAnalyzerView(BaseERPView):
	"""SoD conflict analyzer dashboard and bulk scan endpoint."""

	route_base = "/grc/sod"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		session = _get_session()
		tenant_id = _tenant_id()
		severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
		status_counts = {"open": 0, "under_review": 0, "accepted": 0, "remediated": 0}
		trend_counts = {30: 0, 60: 0, 90: 0}
		recent: list[SodViolation] = []

		try:
			severity_q = (
				sa.select(SodViolation.risk_level, sa.func.count(SodViolation.id).label("count"))
				.group_by(SodViolation.risk_level)
			)
			status_q = (
				sa.select(SodViolation.status, sa.func.count(SodViolation.id).label("count"))
				.group_by(SodViolation.status)
			)
			recent_q = sa.select(SodViolation).order_by(sa.desc(SodViolation.detected_at)).limit(25)
			if tenant_id:
				severity_q = severity_q.where(SodViolation.tenant_id == tenant_id)
				status_q = status_q.where(SodViolation.tenant_id == tenant_id)
				recent_q = recent_q.where(SodViolation.tenant_id == tenant_id)

			for row in session.execute(severity_q).all():
				key = str(row.risk_level or "").lower()
				if key in severity_counts:
					severity_counts[key] = int(row.count or 0)

			for row in session.execute(status_q).all():
				status = str(row.status or "").lower()
				count = int(row.count or 0)
				if status == "open":
					status_counts["open"] += count
				elif status == "under_review":
					status_counts["under_review"] += count
				elif status in ("accepted", "risk_accepted"):
					status_counts["accepted"] += count
				elif status == "remediated":
					status_counts["remediated"] += count

			now = datetime.now(timezone.utc)
			for days in trend_counts:
				trend_q = (
					sa.select(sa.func.count())
					.select_from(SodViolation)
					.where(SodViolation.detected_at >= now - timedelta(days=days))
				)
				if tenant_id:
					trend_q = trend_q.where(SodViolation.tenant_id == tenant_id)
				trend_counts[days] = session.execute(trend_q).scalar() or 0

			recent = session.execute(recent_q).scalars().all()
		except Exception:
			log.exception("SodAnalyzerView.dashboard: failed to load violation dashboard")

		total_violations = sum(severity_counts.values())
		resolved = status_counts["accepted"] + status_counts["remediated"]
		kpi_html = self.kpi_cards([
			{"value": total_violations, "label": "Total Violations", "format": "integer", "icon": "fa-exclamation-triangle", "color": "#dc2626" if total_violations else "#0e9f6e"},
			{"value": severity_counts["critical"], "label": "Critical", "format": "integer", "icon": "fa-ban", "color": "#7f1d1d"},
			{"value": severity_counts["high"], "label": "High", "format": "integer", "icon": "fa-fire", "color": "#ff5a1f"},
			{"value": resolved, "label": "Accepted/Remediated", "format": "integer", "icon": "fa-check-circle", "color": "#0e9f6e"},
		])
		body = (
			"<h3>Segregation of Duties Dashboard</h3>"
			"<p class=\"text-muted\">Violation severity, lifecycle status, and opened-date trend.</p>"
			f"{kpi_html}"
			f"{self._summary_cards(severity_counts, status_counts)}"
			f"{self._trend_table(trend_counts)}"
			f"{self._recent_table(recent)}"
		)
		return make_response(_page_html("SoD Violation Dashboard", body), 200)

	def _summary_cards(self, severity_counts: dict[str, int], status_counts: dict[str, int]) -> str:
		return (
			"<div class=\"grc-summary\">"
			"<div class=\"grc-card\"><h4>Severity Summary</h4>"
			+ "".join(
				"<div class=\"metric-row\">"
				f"<span class=\"metric-label\">{_he(label)}</span>"
				f"<span class=\"metric-value\" style=\"color:{_severity_color(label)}\">{count}</span>"
				"</div>"
				for label, count in severity_counts.items()
			)
			+ "</div>"
			"<div class=\"grc-card\"><h4>Status Summary</h4>"
			+ "".join(
				"<div class=\"metric-row\">"
				f"<span class=\"metric-label\">{_he(label.replace('_', ' '))}</span>"
				f"<span class=\"metric-value\">{count}</span>"
				"</div>"
				for label, count in status_counts.items()
			)
			+ "</div></div>"
		)

	def _trend_table(self, trend_counts: dict[int, int]) -> str:
		rows = [
			"<h4>Opened Trend</h4>",
			"<table class=\"grc-table\"><thead><tr><th>Window</th><th>Violations Opened</th></tr></thead><tbody>",
		]
		for days in (30, 60, 90):
			rows.append(f"<tr><td>Last {days} days</td><td>{int(trend_counts.get(days, 0))}</td></tr>")
		rows.append("</tbody></table>")
		return "".join(rows)

	def _recent_table(self, violations: list[SodViolation]) -> str:
		rows = [
			"<h4>Recent Violations</h4>",
			"<table class=\"grc-table\">",
			"<thead><tr><th>User</th><th>Conflict</th><th>Severity</th><th>Status</th><th>Opened</th></tr></thead>",
			"<tbody>",
		]
		if not violations:
			rows.append("<tr><td colspan=\"5\" class=\"text-muted\">No SoD violations found.</td></tr>")
		for violation in violations:
			severity = str(getattr(violation, "risk_level", "") or "").lower()
			detected_at = getattr(violation, "detected_at", None)
			rows.append(
				"<tr>"
				f"<td>{_he(getattr(violation, 'user_id', ''))}</td>"
				f"<td>{_he(getattr(violation, 'conflict_id', ''))}</td>"
				f"<td><span class=\"badge-risk\" style=\"background:{_severity_color(severity)}\">{_he(severity.title())}</span></td>"
				f"<td>{_he(getattr(violation, 'status', ''))}</td>"
				f"<td>{_he(detected_at.date().isoformat() if detected_at else '')}</td>"
				"</tr>"
			)
		rows.append("</tbody></table>")
		return "".join(rows)

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


SodAnalyzerDashboardView = SodAnalyzerView
SoDashboardView = SodAnalyzerView

__all__ = [
	"SodConflictView",
	"SodViolationView",
	"SodAnalyzerView",
	"SodAnalyzerDashboardView",
	"SoDashboardView",
]
