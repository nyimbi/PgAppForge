"""
pgappforge/plugins/erp/grc/privacy/views.py

Flask views for the GRC Privacy plugin.

Endpoints:
	ConsentView            POST /privacy/consent/
	                       GET  /privacy/consent/check
	                       POST /privacy/consent/withdraw
	DSRView                GET  /privacy/dsr/
	                       POST /privacy/dsr/
	                       POST /privacy/dsr/<id>/transition
	DataProcessingView     GET/POST /privacy/processing-records/
	PrivacyReportView      GET  /privacy/reports/{consent-summary,dsr-status,overdue-dsrs}
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.grc.privacy.services import PrivacyService
	return PrivacyService()


# ---------------------------------------------------------------------------
# ConsentView
# ---------------------------------------------------------------------------

class ConsentView(BaseERPView):
	route_base = "/privacy/consent"
	default_view = "grant"
	label_columns = {
		"party_id": _("Data Subject"),
		"purpose": _("Purpose"),
		"legal_basis": _("Legal Basis"),
		"granted_at": _("Granted"),
		"withdrawn_at": _("Withdrawn"),
		"expires_at": _("Expires"),
		"source": _("Source"),
		"version": _("Version"),
	}

	@expose("/", methods=["POST"])
	@has_access
	def grant(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "party_id", "purpose", "legal_basis")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().grant_consent(
				session=session,
				tenant_id=data["tenant_id"],
				party_id=data["party_id"],
				purpose=data["purpose"],
				legal_basis=data["legal_basis"],
				source=data.get("source"),
				version=data.get("version"),
				ip_address=data.get("ip_address"),
				expires_at=(
					__import__("datetime").datetime.fromisoformat(data["expires_at"])
					if data.get("expires_at") else None
				),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/check")
	@has_access
	def check(self):
		"""Check if active consent exists. Query params: tenant_id, party_id, purpose."""
		session = _get_session()
		args = request.args
		required = ("tenant_id", "party_id", "purpose")
		missing = [f for f in required if not args.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		active = _svc().is_consent_active(
			session,
			tenant_id=args["tenant_id"],
			party_id=args["party_id"],
			purpose=args["purpose"],
		)
		return jsonify({"active": active, "party_id": args["party_id"], "purpose": args["purpose"]})

	@expose("/withdraw", methods=["POST"])
	@has_access
	def withdraw(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "party_id", "purpose")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().withdraw_consent(
				session=session,
				tenant_id=data["tenant_id"],
				party_id=data["party_id"],
				purpose=data["purpose"],
				ip_address=data.get("ip_address"),
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# DSRView
# ---------------------------------------------------------------------------

class DSRView(BaseERPView):
	route_base = "/privacy/dsr"
	default_view = "list"
	label_columns = {
		"dsr_number": _("DSR Number"),
		"party_id": _("Data Subject"),
		"request_type": _("Request Type"),
		"status": _("Status"),
		"received_at": _("Received"),
		"due_at": _("Due"),
		"completed_at": _("Completed"),
		"response_url": _("Response URL"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.grc.privacy.models import DataSubjectRequest
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status_filter = request.args.get("status")
		q = sa.select(DataSubjectRequest).order_by(
			DataSubjectRequest.received_at.desc()
		).limit(200)
		if tenant_id:
			q = q.where(DataSubjectRequest.tenant_id == tenant_id)
		if status_filter:
			q = q.where(DataSubjectRequest.status == status_filter)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"dsr_number": r.dsr_number,
				"party_id": str(r.party_id),
				"request_type": r.request_type,
				"status": r.status,
				"received_at": r.received_at.isoformat() if r.received_at else None,
				"due_at": r.due_at.isoformat() if r.due_at else None,
				"completed_at": r.completed_at.isoformat() if r.completed_at else None,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "party_id", "request_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().create_dsr(
				session=session,
				tenant_id=data["tenant_id"],
				party_id=data["party_id"],
				request_type=data["request_type"],
				notes=data.get("notes"),
				deadline_days=data.get("deadline_days", 30),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:dsr_id>/transition", methods=["POST"])
	@has_access
	def transition(self, dsr_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("status"):
			return jsonify({"error": "status required"}), 400
		try:
			result = _svc().transition_dsr(
				session=session,
				dsr_id=dsr_id,
				new_status=data["status"],
				response_url=data.get("response_url"),
				notes=data.get("notes"),
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# DataProcessingView
# ---------------------------------------------------------------------------

class DataProcessingView(BaseERPView):
	route_base = "/privacy/processing-records"
	default_view = "list"
	label_columns = {
		"processing_purpose": _("Processing Purpose"),
		"data_categories": _("Data Categories"),
		"data_subjects_description": _("Data Subjects"),
		"legal_basis": _("Legal Basis"),
		"controller_name": _("Controller"),
		"processor_name": _("Processor"),
		"retention_period_days": _("Retention Days"),
		"is_cross_border": _("Cross-Border"),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		cross_border = request.args.get("is_cross_border")
		cb_filter = None
		if cross_border is not None:
			cb_filter = cross_border.lower() == "true"
		rows = _svc().get_processing_records(
			session, tenant_id=tenant_id, is_cross_border=cb_filter
		)
		return jsonify(rows)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "processing_purpose", "data_categories",
			"data_subjects_description", "legal_basis",
			"controller_name", "retention_period_days",
		)
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().create_processing_record(
				session=session,
				tenant_id=data["tenant_id"],
				processing_purpose=data["processing_purpose"],
				data_categories=data["data_categories"],
				data_subjects_description=data["data_subjects_description"],
				legal_basis=data["legal_basis"],
				controller_name=data["controller_name"],
				retention_period_days=int(data["retention_period_days"]),
				recipients=data.get("recipients"),
				processor_name=data.get("processor_name"),
				is_cross_border=data.get("is_cross_border", False),
				safeguards=data.get("safeguards"),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# PrivacyReportView
# ---------------------------------------------------------------------------

class PrivacyReportView(BaseERPView):
	"""Privacy / GDPR reports.

	GET /privacy/reports/              — Dashboard with KPI tiles
	GET /privacy/reports/consent-summary  — consent counts by purpose and legal_basis
	GET /privacy/reports/dsr-status       — DSR counts by status and type
	GET /privacy/reports/overdue-dsrs     — DSRs past their due date
	"""

	route_base = "/privacy/reports"
	default_view = "index"
	label_columns = {
		"open_dsars": _("Open DSARs"),
		"consents_active": _("Active Consents"),
		"breaches_ytd": _("Breaches YTD"),
		"processing_records": _("Processing Records"),
	}

	@expose("/")
	@has_access
	def index(self):
		"""Privacy dashboard — open DSARs, active consents, breaches YTD, processing records."""
		from pgappforge.plugins.erp.grc.privacy.models import (
			ConsentRecord, DataSubjectRequest, DataProcessingRecord,
		)
		from datetime import date as _date
		import sqlalchemy as _sa
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		open_dsars: int = 0
		consents_active: int = 0
		breaches_ytd: int = 0
		processing_records: int = 0

		try:
			open_dsars = session.execute(
				_sa.select(_sa.func.count()).select_from(DataSubjectRequest).where(
					DataSubjectRequest.status.in_(("PENDING", "IN_PROGRESS", "ACKNOWLEDGED")),
					*([DataSubjectRequest.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			consents_active = session.execute(
				_sa.select(_sa.func.count()).select_from(ConsentRecord).where(
					ConsentRecord.withdrawn_at.is_(None),
					*([ConsentRecord.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			processing_records = session.execute(
				_sa.select(_sa.func.count()).select_from(DataProcessingRecord).where(
					*([DataProcessingRecord.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Open DSARs", "value": open_dsars, "format": "integer",
			 "color": "#e02424", "icon": "fa-user-shield"},
			{"label": "Active Consents", "value": consents_active, "format": "integer",
			 "color": "#057a55", "icon": "fa-check-circle"},
			{"label": "Breaches YTD", "value": breaches_ytd, "format": "integer",
			 "color": "#e3a008", "icon": "fa-exclamation-triangle"},
			{"label": "Processing Records", "value": processing_records, "format": "integer",
			 "color": "#1a56db", "icon": "fa-database"},
		])

		if request.args.get("format") == "json":
			return jsonify({
				"open_dsars": open_dsars,
				"consents_active": consents_active,
				"breaches_ytd": breaches_ytd,
				"processing_records": processing_records,
				"reports": [
					{"name": "Consent Summary", "endpoint": "/privacy/reports/consent-summary"},
					{"name": "DSR Status", "endpoint": "/privacy/reports/dsr-status"},
					{"name": "Overdue DSRs", "endpoint": "/privacy/reports/overdue-dsrs"},
				],
			})

		def _ph(t: str, b: str) -> str:
			return (
				f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{t}</title>'
				'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
				'<style>body{padding:24px}</style>'
				f'</head><body>{b}</body></html>'
			)

		from flask import make_response as _mr
		body = (
			"<h3>Privacy Dashboard</h3>"
			+ str(kpi_html)
			+ '<p>'
			+ '<a href="/privacy/reports/consent-summary" class="btn btn-default">Consent Summary</a> '
			+ '<a href="/privacy/reports/dsr-status" class="btn btn-default">DSR Status</a> '
			+ '<a href="/privacy/reports/overdue-dsrs" class="btn btn-default">Overdue DSRs</a>'
			+ '</p>'
		)
		return _mr(_ph("Privacy Dashboard", body), 200)

	@expose("/consent-summary")
	@has_access
	def consent_summary(self):
		from pgappforge.plugins.erp.grc.privacy.models import ConsentRecord
		from sqlalchemy import func as F
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(
			ConsentRecord.purpose,
			ConsentRecord.legal_basis,
			F.count().label("total"),
			F.sum(
				sa.case((ConsentRecord.withdrawn_at.is_(None), 1), else_=0)
			).label("active"),
		).group_by(
			ConsentRecord.purpose, ConsentRecord.legal_basis
		).order_by(ConsentRecord.purpose)
		if tenant_id:
			q = q.where(ConsentRecord.tenant_id == tenant_id)
		rows = session.execute(q).all()
		return jsonify([
			{
				"purpose": r.purpose,
				"legal_basis": r.legal_basis,
				"total": r.total,
				"active": r.active,
				"withdrawn": r.total - r.active,
			}
			for r in rows
		])

	@expose("/dsr-status")
	@has_access
	def dsr_status(self):
		from pgappforge.plugins.erp.grc.privacy.models import DataSubjectRequest
		from sqlalchemy import func as F
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(
			DataSubjectRequest.request_type,
			DataSubjectRequest.status,
			F.count().label("count"),
		).group_by(
			DataSubjectRequest.request_type, DataSubjectRequest.status
		).order_by(DataSubjectRequest.request_type, DataSubjectRequest.status)
		if tenant_id:
			q = q.where(DataSubjectRequest.tenant_id == tenant_id)
		rows = session.execute(q).all()
		return jsonify([
			{
				"request_type": r.request_type,
				"status": r.status,
				"count": r.count,
			}
			for r in rows
		])

	@expose("/overdue-dsrs")
	@has_access
	def overdue_dsrs(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		rows = _svc().get_overdue_dsrs(session, tenant_id=tenant_id)
		return jsonify(rows)


__all__ = [
	"ConsentView",
	"DSRView",
	"DataProcessingView",
	"PrivacyReportView",
]
