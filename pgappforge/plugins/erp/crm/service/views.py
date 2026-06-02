"""
pgappforge/plugins/erp/crm/service/views.py

Flask views for the Service Cloud plugin.

Route summary
-------------
CaseView              /service/cases/
SLAPolicyView         /service/sla-policies/
KnowledgeArticleView  /service/knowledge/
CaseCommentView       /service/cases/<id>/comments/
ServiceReportView     /service/reports/
  ├─ /open-by-priority   — Open Cases by Priority (HTML)
  ├─ /sla-compliance     — SLA Compliance Report (HTML)
  └─ /csat-summary       — CSAT Summary (HTML)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
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
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


# ---------------------------------------------------------------------------
# CaseView
# ---------------------------------------------------------------------------

class CaseView(BaseView):
	"""Case CRUD + business action endpoints."""

	route_base = "/service/cases"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.service.models import Case
		session = _get_session()
		cases = session.execute(sa.select(Case).order_by(Case.created_at.desc()).limit(200)).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(c.case_number)}</td><td>{_he(c.subject)}</td>"
			f"<td>{_he(c.priority)}</td><td>{_he(c.status)}</td>"
			f"<td>{_he(c.channel)}</td>"
			f"<td><a href='/service/cases/{_he(c.id)}'>View</a></td></tr>"
			for c in cases
		)
		return make_response(
			f"<html><body><h2>Cases</h2><table border='1'>"
			f"<tr><th>Number</th><th>Subject</th><th>Priority</th><th>Status</th><th>Channel</th><th></th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/<string:case_id>")
	@has_access
	def detail(self, case_id: str):
		from pgappforge.plugins.erp.crm.service.models import Case
		session = _get_session()
		case = session.execute(sa.select(Case).where(Case.id == case_id)).scalar_one_or_none()
		if case is None:
			abort(404)
		return jsonify({
			"id": case.id,
			"case_number": case.case_number,
			"subject": case.subject,
			"priority": case.priority,
			"status": case.status,
			"channel": case.channel,
			"owner_id": case.owner_id,
			"sla_breach_at": case.sla_breach_at.isoformat() if case.sla_breach_at else None,
			"resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
			"csat_score": case.csat_score,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService, ServiceValidationError
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "case_number", "subject")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing fields: {missing}"}), 400
		session = _get_session()
		try:
			case = ServiceCloudService.create_case(data, session)
			session.commit()
			return jsonify({"id": case.id, "case_number": case.case_number}), 201
		except ServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:case_id>/escalate", methods=["POST"])
	@has_access
	def escalate(self, case_id: str):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService, ServiceValidationError, CaseNotFoundError
		data = request.get_json(force=True) or {}
		escalated_to = data.get("escalated_to", "")
		session = _get_session()
		try:
			case = ServiceCloudService.escalate_case(case_id, escalated_to, session)
			session.commit()
			return jsonify({"id": case.id, "status": case.status, "priority": case.priority})
		except CaseNotFoundError:
			return jsonify({"error": "Case not found"}), 404
		except ServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:case_id>/resolve", methods=["POST"])
	@has_access
	def resolve(self, case_id: str):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService, ServiceValidationError, CaseNotFoundError
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			case = ServiceCloudService.resolve_case(case_id, data.get("resolution_notes", ""), session)
			session.commit()
			return jsonify({"id": case.id, "status": case.status})
		except CaseNotFoundError:
			return jsonify({"error": "Case not found"}), 404
		except ServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:case_id>/close", methods=["POST"])
	@has_access
	def close(self, case_id: str):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService, ServiceValidationError, CaseNotFoundError
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			case = ServiceCloudService.close_case(case_id, data.get("csat_score"), session)
			session.commit()
			return jsonify({"id": case.id, "status": case.status, "csat_score": case.csat_score})
		except CaseNotFoundError:
			return jsonify({"error": "Case not found"}), 404
		except ServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:case_id>/comments", methods=["POST"])
	@has_access
	def add_comment(self, case_id: str):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService, ServiceValidationError, CaseNotFoundError
		data = request.get_json(force=True) or {}
		if not data.get("body"):
			return jsonify({"error": "body required"}), 400
		session = _get_session()
		try:
			comment = ServiceCloudService.add_comment(case_id, data, session)
			session.commit()
			return jsonify({"id": comment.id, "is_public": comment.is_public}), 201
		except CaseNotFoundError:
			return jsonify({"error": "Case not found"}), 404
		except ServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:case_id>/survey", methods=["POST"])
	@has_access
	def submit_survey(self, case_id: str):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService, ServiceValidationError, CaseNotFoundError
		data = request.get_json(force=True) or {}
		data["case_id"] = case_id
		session = _get_session()
		try:
			resp = ServiceCloudService.submit_survey(data, session)
			session.commit()
			return jsonify({"id": resp.id, "score": resp.score}), 201
		except CaseNotFoundError:
			return jsonify({"error": "Case not found"}), 404
		except ServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# SLAPolicyView
# ---------------------------------------------------------------------------

class SLAPolicyView(BaseView):
	"""SLA Policy CRUD."""

	route_base = "/service/sla-policies"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.service.models import SLAPolicy
		session = _get_session()
		policies = session.execute(sa.select(SLAPolicy).order_by(SLAPolicy.priority)).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(p.name)}</td><td>{_he(p.priority)}</td>"
			f"<td>{p.first_response_minutes}</td><td>{p.resolution_minutes}</td>"
			f"<td>{'Yes' if p.business_hours_only else 'No'}</td></tr>"
			for p in policies
		)
		return make_response(
			f"<html><body><h2>SLA Policies</h2><table border='1'>"
			f"<tr><th>Name</th><th>Priority</th><th>First Response (min)</th>"
			f"<th>Resolution (min)</th><th>Business Hours Only</th></tr>"
			f"{rows}</table></body></html>"
		)


# ---------------------------------------------------------------------------
# KnowledgeArticleView
# ---------------------------------------------------------------------------

class KnowledgeArticleView(BaseView):
	"""Knowledge Article CRUD + publish action."""

	route_base = "/service/knowledge"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.service.models import KnowledgeArticle
		session = _get_session()
		articles = session.execute(
			sa.select(KnowledgeArticle).order_by(KnowledgeArticle.status, KnowledgeArticle.title)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(a.title)}</td><td>{_he(a.category or '')}</td>"
			f"<td>{_he(a.status)}</td><td>{a.views}</td><td>{a.helpful_votes}</td>"
			f"<td><a href='/service/knowledge/{_he(a.id)}/publish' "
			f"onclick=\"fetch(this.href,{{method:'POST'}});return false;\">Publish</a></td></tr>"
			for a in articles
		)
		return make_response(
			f"<html><body><h2>Knowledge Articles</h2><table border='1'>"
			f"<tr><th>Title</th><th>Category</th><th>Status</th><th>Views</th>"
			f"<th>Helpful</th><th></th></tr>{rows}</table></body></html>"
		)

	@expose("/<string:article_id>/publish", methods=["POST"])
	@has_access
	def publish(self, article_id: str):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService, ServiceValidationError, ArticleNotFoundError
		session = _get_session()
		try:
			article = ServiceCloudService.publish_article(article_id, session)
			session.commit()
			return jsonify({"id": article.id, "status": article.status})
		except ArticleNotFoundError:
			return jsonify({"error": "Article not found"}), 404
		except ServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ServiceReportView — 3 ReportForge-compatible report endpoints
# ---------------------------------------------------------------------------

class ServiceReportView(BaseView):
	"""Service Cloud reports: open cases, SLA compliance, CSAT summary."""

	route_base = "/service/reports"

	@expose("/open-by-priority")
	@has_access
	def open_by_priority(self):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService
		from flask import current_app, request as req
		tenant_id = req.args.get("tenant_id", "")
		session = _get_session()
		report = ServiceCloudService.case_report(tenant_id, {}, session)
		rows = "".join(
			f"<tr><td>{_he(p)}</td><td>{cnt}</td></tr>"
			for p, cnt in report["open_by_priority"].items()
		)
		return make_response(
			f"<html><body><h2>Open Cases by Priority</h2>"
			f"<table border='1'><tr><th>Priority</th><th>Count</th></tr>{rows}</table>"
			f"</body></html>"
		)

	@expose("/sla-compliance")
	@has_access
	def sla_compliance(self):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService
		from flask import request as req
		tenant_id = req.args.get("tenant_id", "")
		session = _get_session()
		report = ServiceCloudService.case_report(tenant_id, {}, session)
		pct = report["sla_compliance_pct"]
		return make_response(
			f"<html><body><h2>SLA Compliance</h2>"
			f"<p>Resolved on time: {report['on_time_resolutions']} / {report['total_resolved']}</p>"
			f"<p>Compliance rate: <strong>{pct}%</strong></p>"
			f"</body></html>"
		)

	@expose("/csat-summary")
	@has_access
	def csat_summary(self):
		from pgappforge.plugins.erp.crm.service.services import ServiceCloudService
		from flask import request as req
		tenant_id = req.args.get("tenant_id", "")
		session = _get_session()
		report = ServiceCloudService.case_report(tenant_id, {}, session)
		avg = report["avg_csat"]
		return make_response(
			f"<html><body><h2>CSAT Summary</h2>"
			f"<p>Average CSAT score: <strong>{avg if avg is not None else 'N/A'} / 5</strong></p>"
			f"</body></html>"
		)
