"""
pgappforge/plugins/erp/industry/cybersecurity/views.py

Flask views for the Cybersecurity (STIX 2.1) plugin.

Views:
  IndicatorView       — IOC CRUD with CodeEditor pattern field, Select2 type/severity
  IncidentView        — Security incident lifecycle with priority rating
  VulnerabilityView   — CVE list with CVSS range display
  ThreatDashboard     — Threat intelligence summary dashboard
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	date_widget,
	star_widget,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
	from pgappforge.plugins.erp.industry.cybersecurity.services import CybersecurityService
	return CybersecurityService()


# ---------------------------------------------------------------------------
# IndicatorView
# ---------------------------------------------------------------------------

class IndicatorView(BaseView):
	"""IOC indicator CRUD.

	CodeEditorWidget annotation for pattern field.
	Select2 for indicator_type and severity.

	GET  /cybersecurity/indicators/          — list (filterable by type, severity)
	POST /cybersecurity/indicators/          — create
	GET  /cybersecurity/indicators/<id>      — detail
	POST /cybersecurity/indicators/<id>/fp   — mark false positive on all matches
	"""

	route_base = "/cybersecurity/indicators"
	default_view = "list"

	# Widget metadata exposed for template rendering
	_field_widgets = {
		"pattern": {"widget": "CodeEditorWidget", "language": "stix"},
		"indicator_type": {"widget": "Select2Widget", "choices": [
			"MALICIOUS_URL", "FILE_HASH", "IP_ADDRESS", "DOMAIN", "EMAIL",
		]},
		"severity": {"widget": "Select2Widget", "choices": [
			"LOW", "MEDIUM", "HIGH", "CRITICAL",
		]},
		"valid_from": date_widget("YYYY-MM-DDTHH:MM:SSZ"),
		"valid_until": date_widget("YYYY-MM-DDTHH:MM:SSZ"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.cybersecurity.models import Indicator
		session = _get_session()
		ioc_type = request.args.get("indicator_type")
		severity = request.args.get("severity")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(Indicator)
			.order_by(
				sa.case(
					{"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3},
					value=Indicator.severity,
					else_=4,
				),
				Indicator.valid_from.desc(),
			)
			.limit(500)
		)
		if tenant_id:
			q = q.where(Indicator.tenant_id == tenant_id)
		if ioc_type:
			q = q.where(Indicator.indicator_type == ioc_type)
		if severity:
			q = q.where(Indicator.severity == severity)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"stix_id": r.stix_id,
				"name": r.name,
				"indicator_type": r.indicator_type,
				"severity": r.severity,
				"confidence": r.confidence,
				"valid_from": r.valid_from.isoformat() if r.valid_from else None,
				"valid_until": r.valid_until.isoformat() if r.valid_until else None,
				"labels": r.labels,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.cybersecurity.models import Indicator
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "stix_id", "indicator_type", "name", "pattern", "valid_from")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		try:
			valid_from = datetime.fromisoformat(data["valid_from"])
		except ValueError as exc:
			return jsonify({"error": f"Invalid valid_from: {exc}"}), 400

		confidence = data.get("confidence", 50)
		if not (0 <= int(confidence) <= 100):
			return jsonify({"error": "confidence must be 0–100"}), 400

		ioc = Indicator(
			tenant_id=data["tenant_id"],
			stix_id=data["stix_id"],
			indicator_type=data["indicator_type"],
			name=data["name"],
			description=data.get("description"),
			pattern=data["pattern"],
			pattern_type=data.get("pattern_type", "stix"),
			valid_from=valid_from,
			valid_until=data.get("valid_until"),
			confidence=int(confidence),
			severity=data.get("severity", "MEDIUM"),
			kill_chain_phases=data.get("kill_chain_phases", []),
			labels=data.get("labels", []),
		)
		session.add(ioc)
		session.commit()
		return jsonify({"indicator_id": ioc.id, "stix_id": ioc.stix_id}), 201

	@expose("/<string:indicator_id>")
	@has_access
	def detail(self, indicator_id: str):
		from pgappforge.plugins.erp.industry.cybersecurity.models import Indicator
		session = _get_session()
		ioc = session.get(Indicator, indicator_id)
		if ioc is None:
			abort(404)
		return jsonify({
			"id": ioc.id,
			"stix_id": ioc.stix_id,
			"name": ioc.name,
			"indicator_type": ioc.indicator_type,
			"pattern": ioc.pattern,
			"pattern_type": ioc.pattern_type,
			"severity": ioc.severity,
			"confidence": ioc.confidence,
			"valid_from": ioc.valid_from.isoformat() if ioc.valid_from else None,
			"valid_until": ioc.valid_until.isoformat() if ioc.valid_until else None,
			"kill_chain_phases": ioc.kill_chain_phases,
			"labels": ioc.labels,
			"description": ioc.description,
		})

	@expose("/search")
	@has_access
	def search(self):
		"""GET /cybersecurity/indicators/search?value=<ioc>&type=<type>&tenant_id=<id>"""
		value = request.args.get("value", "")
		ioc_type = request.args.get("type")
		tenant_id = request.args.get("tenant_id", "")
		if not value or not tenant_id:
			return jsonify({"error": "value and tenant_id required"}), 400
		session = _get_session()
		results = _svc().search_ioc(value, ioc_type, tenant_id, session)
		return jsonify({"count": len(results), "results": results})


# ---------------------------------------------------------------------------
# IncidentView
# ---------------------------------------------------------------------------

class IncidentView(BaseView):
	"""Security incident lifecycle management.

	RichTextEditor for description.
	StarRating for severity mapping (P1=5 stars … P4=1 star).
	DateTimePicker for detected_at, contained_at, resolved_at.

	GET  /cybersecurity/incidents/                    — list
	POST /cybersecurity/incidents/                    — open incident
	GET  /cybersecurity/incidents/<id>               — detail + correlated IOCs
	POST /cybersecurity/incidents/<id>/triage        — set severity + responders
	POST /cybersecurity/incidents/<id>/contain       — mark CONTAINED
	POST /cybersecurity/incidents/<id>/resolve       — mark RESOLVED
	"""

	route_base = "/cybersecurity/incidents"
	default_view = "list"

	_field_widgets = {
		"description": {"widget": "RichTextEditorWidget"},
		"severity": star_widget(max_rating=4, readonly=False),
		"detected_at": date_widget("YYYY-MM-DDTHH:MM:SSZ"),
		"contained_at": date_widget("YYYY-MM-DDTHH:MM:SSZ"),
		"resolved_at": date_widget("YYYY-MM-DDTHH:MM:SSZ"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.cybersecurity.models import SecurityIncident
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		severity = request.args.get("severity")

		q = (
			sa.select(SecurityIncident)
			.order_by(
				sa.case({"P1": 0, "P2": 1, "P3": 2, "P4": 3}, value=SecurityIncident.severity, else_=4),
				SecurityIncident.detected_at.desc(),
			)
			.limit(200)
		)
		if tenant_id:
			q = q.where(SecurityIncident.tenant_id == tenant_id)
		if status:
			q = q.where(SecurityIncident.status == status)
		if severity:
			q = q.where(SecurityIncident.severity == severity)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": inc.id,
				"incident_number": inc.incident_number,
				"title": inc.title,
				"incident_type": inc.incident_type,
				"severity": inc.severity,
				"status": inc.status,
				"detected_at": inc.detected_at.isoformat() if inc.detected_at else None,
				"data_exfiltrated": inc.data_exfiltrated,
				"estimated_impact_cents": inc.estimated_impact_cents,
			}
			for inc in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.cybersecurity.models import SecurityIncident
		from pgappforge.plugins.erp.industry.cybersecurity.events import (
			IncidentOpenedEvent,
			emit_event,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "incident_number", "title", "incident_type", "detected_at")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400

		try:
			detected_at = datetime.fromisoformat(data["detected_at"])
		except ValueError as exc:
			return jsonify({"error": f"Invalid detected_at: {exc}"}), 400

		inc = SecurityIncident(
			tenant_id=data["tenant_id"],
			incident_number=data["incident_number"],
			title=data["title"],
			description=data.get("description"),
			incident_type=data["incident_type"],
			severity=data.get("severity", "P3"),
			status="NEW",
			detected_at=detected_at,
			affected_systems=data.get("affected_systems", []),
			data_exfiltrated=data.get("data_exfiltrated", False),
			estimated_impact_cents=data.get("estimated_impact_cents", 0),
			responders=data.get("responders", []),
		)
		session.add(inc)
		session.flush()
		emit_event(
			IncidentOpenedEvent(
				incident_id=inc.id,
				incident_number=inc.incident_number,
				incident_type=inc.incident_type,
				severity=inc.severity,
			),
			session,
		)
		session.commit()
		return jsonify({"incident_id": inc.id, "incident_number": inc.incident_number}), 201

	@expose("/<string:incident_id>")
	@has_access
	def detail(self, incident_id: str):
		from pgappforge.plugins.erp.industry.cybersecurity.models import SecurityIncident
		session = _get_session()
		inc = session.get(SecurityIncident, incident_id)
		if inc is None:
			abort(404)
		correlations = _svc().correlate_indicators(incident_id, session)
		return jsonify({
			"id": inc.id,
			"incident_number": inc.incident_number,
			"title": inc.title,
			"description": inc.description,
			"incident_type": inc.incident_type,
			"severity": inc.severity,
			"status": inc.status,
			"detected_at": inc.detected_at.isoformat() if inc.detected_at else None,
			"contained_at": inc.contained_at.isoformat() if inc.contained_at else None,
			"resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
			"affected_systems": inc.affected_systems,
			"data_exfiltrated": inc.data_exfiltrated,
			"estimated_impact_cents": inc.estimated_impact_cents,
			"responders": inc.responders,
			"correlated_indicators": correlations[:10],
		})

	@expose("/<string:incident_id>/triage", methods=["POST"])
	@has_access
	def triage(self, incident_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("severity"):
			return jsonify({"error": "severity required"}), 400
		try:
			inc = _svc().triage_incident(
				incident_id,
				data["severity"],
				data.get("responders", []),
				session,
			)
			session.commit()
			return jsonify({"incident_id": inc.id, "severity": inc.severity, "status": inc.status})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:incident_id>/contain", methods=["POST"])
	@has_access
	def contain(self, incident_id: str):
		from pgappforge.plugins.erp.industry.cybersecurity.models import SecurityIncident
		from pgappforge.plugins.erp.industry.cybersecurity.events import (
			IncidentContainedEvent,
			emit_event,
		)
		session = _get_session()
		inc = session.get(SecurityIncident, incident_id)
		if inc is None:
			abort(404)
		now = datetime.now(timezone.utc)
		inc.status = "CONTAINED"
		inc.contained_at = now
		session.flush()
		emit_event(
			IncidentContainedEvent(
				incident_id=inc.id,
				incident_number=inc.incident_number,
				data_exfiltrated=inc.data_exfiltrated,
			),
			session,
		)
		session.commit()
		return jsonify({"incident_id": inc.id, "status": "CONTAINED", "contained_at": now.isoformat()})

	@expose("/<string:incident_id>/resolve", methods=["POST"])
	@has_access
	def resolve(self, incident_id: str):
		from pgappforge.plugins.erp.industry.cybersecurity.models import SecurityIncident
		from pgappforge.plugins.erp.industry.cybersecurity.events import (
			IncidentResolvedEvent,
			emit_event,
		)
		session = _get_session()
		inc = session.get(SecurityIncident, incident_id)
		if inc is None:
			abort(404)
		now = datetime.now(timezone.utc)
		inc.status = "RESOLVED"
		inc.resolved_at = now
		session.flush()
		emit_event(
			IncidentResolvedEvent(
				incident_id=inc.id,
				incident_number=inc.incident_number,
				estimated_impact_cents=inc.estimated_impact_cents,
			),
			session,
		)
		session.commit()
		return jsonify({"incident_id": inc.id, "status": "RESOLVED", "resolved_at": now.isoformat()})


# ---------------------------------------------------------------------------
# VulnerabilityView
# ---------------------------------------------------------------------------

class VulnerabilityView(BaseView):
	"""CVE vulnerability management.

	RangeSlider annotation for CVSS score display.

	GET  /cybersecurity/vulnerabilities/            — list (filterable by severity, exploited)
	POST /cybersecurity/vulnerabilities/            — create
	GET  /cybersecurity/vulnerabilities/<id>        — detail
	POST /cybersecurity/vulnerabilities/<id>/exploit-flag — set is_exploited=True
	"""

	route_base = "/cybersecurity/vulnerabilities"
	default_view = "list"

	_field_widgets = {
		"cvss_score": {
			"widget": "RangeSliderWidget",
			"min": 0.0,
			"max": 10.0,
			"step": 0.1,
			"readonly": True,
		},
		"severity": {"widget": "Select2Widget", "choices": [
			"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO",
		]},
		"published_at": date_widget(),
		"modified_at": date_widget(),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.cybersecurity.models import Vulnerability
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		severity = request.args.get("severity")
		exploited = request.args.get("exploited")

		q = (
			sa.select(Vulnerability)
			.order_by(
				sa.case(
					{"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4},
					value=Vulnerability.severity,
					else_=5,
				),
				Vulnerability.cvss_score.desc().nulls_last(),
			)
			.limit(500)
		)
		if tenant_id:
			q = q.where(Vulnerability.tenant_id == tenant_id)
		if severity:
			q = q.where(Vulnerability.severity == severity)
		if exploited is not None:
			q = q.where(Vulnerability.is_exploited == (exploited.lower() == "true"))

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": v.id,
				"cve_id": v.cve_id,
				"title": v.title,
				"severity": v.severity,
				"cvss_score": float(v.cvss_score) if v.cvss_score is not None else None,
				"is_exploited": v.is_exploited,
				"patch_available": v.patch_available,
				"published_at": v.published_at.isoformat() if v.published_at else None,
			}
			for v in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.cybersecurity.models import Vulnerability
		from pgappforge.plugins.erp.industry.cybersecurity.events import (
			VulnerabilityPublishedEvent,
			emit_event,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "cve_id", "title")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400

		vuln = Vulnerability(
			tenant_id=data["tenant_id"],
			cve_id=data["cve_id"],
			title=data["title"],
			description=data.get("description"),
			cvss_score=data.get("cvss_score"),
			cvss_vector=data.get("cvss_vector"),
			severity=data.get("severity", "MEDIUM"),
			affected_products=data.get("affected_products", []),
			published_at=data.get("published_at"),
			modified_at=data.get("modified_at"),
			is_exploited=data.get("is_exploited", False),
			patch_available=data.get("patch_available", False),
			patch_url=data.get("patch_url"),
		)
		session.add(vuln)
		session.flush()
		emit_event(
			VulnerabilityPublishedEvent(
				vulnerability_id=vuln.id,
				cve_id=vuln.cve_id,
				severity=vuln.severity,
				cvss_score=float(vuln.cvss_score) if vuln.cvss_score else 0.0,
			),
			session,
		)
		session.commit()
		return jsonify({"vulnerability_id": vuln.id, "cve_id": vuln.cve_id}), 201

	@expose("/<string:vuln_id>")
	@has_access
	def detail(self, vuln_id: str):
		from pgappforge.plugins.erp.industry.cybersecurity.models import Vulnerability
		session = _get_session()
		vuln = session.get(Vulnerability, vuln_id)
		if vuln is None:
			abort(404)
		return jsonify({
			"id": vuln.id,
			"cve_id": vuln.cve_id,
			"title": vuln.title,
			"description": vuln.description,
			"cvss_score": float(vuln.cvss_score) if vuln.cvss_score is not None else None,
			"cvss_vector": vuln.cvss_vector,
			"severity": vuln.severity,
			"affected_products": vuln.affected_products,
			"published_at": vuln.published_at.isoformat() if vuln.published_at else None,
			"modified_at": vuln.modified_at.isoformat() if vuln.modified_at else None,
			"is_exploited": vuln.is_exploited,
			"patch_available": vuln.patch_available,
			"patch_url": vuln.patch_url,
		})

	@expose("/<string:vuln_id>/exploit-flag", methods=["POST"])
	@has_access
	def exploit_flag(self, vuln_id: str):
		from pgappforge.plugins.erp.industry.cybersecurity.models import Vulnerability
		from pgappforge.plugins.erp.industry.cybersecurity.events import (
			VulnerabilityExploitedFlaggedEvent,
			emit_event,
		)
		session = _get_session()
		vuln = session.get(Vulnerability, vuln_id)
		if vuln is None:
			abort(404)
		vuln.is_exploited = True
		session.flush()
		emit_event(
			VulnerabilityExploitedFlaggedEvent(
				vulnerability_id=vuln.id,
				cve_id=vuln.cve_id,
				severity=vuln.severity,
			),
			session,
		)
		session.commit()
		return jsonify({"vulnerability_id": vuln.id, "is_exploited": True})


# ---------------------------------------------------------------------------
# ThreatDashboard
# ---------------------------------------------------------------------------

class ThreatDashboard(BaseView):
	"""Threat intelligence executive dashboard.

	AdvancedChartsWidget annotations for chart rendering.

	GET /cybersecurity/dashboard/                    — summary metrics
	GET /cybersecurity/dashboard/threat-report       — full 30-day report
	GET /cybersecurity/dashboard/risk-score          — system risk score
	"""

	route_base = "/cybersecurity/dashboard"
	default_view = "index"

	_chart_widgets = {
		"incidents_by_type": chart_widget("bar"),
		"indicators_by_severity": chart_widget("pie"),
		"vuln_by_severity": chart_widget("donut"),
		"incidents_trend": chart_widget("line"),
	}

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"endpoints": {
				"summary": "/cybersecurity/dashboard/",
				"threat_report": "/cybersecurity/dashboard/threat-report?tenant_id=<id>&days=30",
				"risk_score": "/cybersecurity/dashboard/risk-score?system_id=<id>&tenant_id=<id>",
			},
			"chart_widgets": list(self._chart_widgets.keys()),
		})

	@expose("/threat-report")
	@has_access
	def threat_report(self):
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id required"}), 400
		period_days = int(request.args.get("days", 30))
		session = _get_session()
		report = _svc().generate_threat_report(tenant_id, session, period_days=period_days)
		return jsonify(report)

	@expose("/risk-score")
	@has_access
	def risk_score(self):
		system_id = request.args.get("system_id")
		tenant_id = request.args.get("tenant_id")
		if not system_id or not tenant_id:
			return jsonify({"error": "system_id and tenant_id required"}), 400
		session = _get_session()
		score = _svc().calculate_risk_score(system_id, tenant_id, session)
		return jsonify(score)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"IndicatorView",
	"IncidentView",
	"VulnerabilityView",
	"ThreatDashboard",
]
