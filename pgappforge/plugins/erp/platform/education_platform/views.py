"""
pgappforge/plugins/erp/platform/education_platform/views.py

Flask views for the Education Platform plugin.

Endpoints:
  LMSToolView           GET/POST  /education/tools/
  LearningObjectView    GET/POST  /education/objects/
  LearningPathView      GET/POST  /education/paths/
                        GET       /education/paths/<id>/progress
  LearnerActivityView   GET       /education/learners/<id>/activity
                        POST      /education/activity/xapi
  CredentialView        GET/POST  /education/credentials/
                        POST      /education/credentials/<id>/issue
                        GET       /education/credentials/verify
  LTILaunchView         POST      /education/lti/launch
  RecommendationView    GET       /education/learners/<id>/recommend
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	date_widget,
	datetime_widget,
	chart_widget,
	json_widget,
	progress_widget,
	star_widget,
	select2_widget,
	qr_widget,
)

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
	from pgappforge.plugins.erp.platform.education_platform.services import (
		EducationPlatformService,
	)
	return EducationPlatformService()


# ---------------------------------------------------------------------------
# LMSToolView
# ---------------------------------------------------------------------------

class LMSToolView(BaseView):
	"""Manage registered LMS tools (LTI 1.3, SCORM, xAPI, AICC).

	Widget config:
	  configuration  → JSONEditorWidget (tree mode)
	  is_active      → Boolean toggle
	"""

	route_base = "/education/tools"
	default_view = "list"

	# Widget hints for UI layer
	field_widgets = {
		"configuration": json_widget(mode="tree"),
	}
	label_columns = {
		"tool_name": _("Tool Name"),
		"tool_type": _("Type"),
		"launch_url": _("Launch URL"),
		"client_id": _("Client ID"),
		"deployment_id": _("Deployment ID"),
		"jwks_url": _("JWKS URL"),
		"auth_login_url": _("Auth Login URL"),
		"auth_token_url": _("Auth Token URL"),
		"is_active": _("Active"),
		"configuration": _("Configuration"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.platform.education_platform.models import LMSTool
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		tool_type = request.args.get("tool_type")
		q = sa.select(LMSTool).order_by(LMSTool.tool_name)
		if tenant_id:
			q = q.where(LMSTool.tenant_id == tenant_id)
		if tool_type:
			q = q.where(LMSTool.tool_type == tool_type)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"tool_name": r.tool_name,
				"tool_type": r.tool_type,
				"launch_url": r.launch_url,
				"client_id": r.client_id,
				"is_active": r.is_active,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "tool_name", "tool_type", "launch_url")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		from pgappforge.plugins.erp.platform.education_platform.models import LMSTool
		tool = LMSTool(
			tenant_id=data["tenant_id"],
			tool_name=data["tool_name"],
			tool_type=data["tool_type"],
			launch_url=data["launch_url"],
			client_id=data.get("client_id"),
			deployment_id=data.get("deployment_id"),
			jwks_url=data.get("jwks_url"),
			auth_login_url=data.get("auth_login_url"),
			auth_token_url=data.get("auth_token_url"),
			is_active=data.get("is_active", True),
			configuration=data.get("configuration", {}),
		)
		session.add(tool)
		session.flush()
		session.commit()
		return jsonify({"tool_id": tool.id, "status": "created"}), 201


# ---------------------------------------------------------------------------
# LearningObjectView
# ---------------------------------------------------------------------------

class LearningObjectView(BaseView):
	"""Manage learning objects (modules, quizzes, videos, etc.).

	Widget config:
	  competencies        → JSONEditorWidget
	  difficulty          → Select2Widget
	  estimated_duration  → progress_widget (display)
	"""

	route_base = "/education/objects"
	default_view = "list"

	field_widgets = {
		"competencies": json_widget(mode="tree"),
		"difficulty": select2_widget(["BEGINNER", "INTERMEDIATE", "ADVANCED"]),
		"estimated_duration_minutes": progress_widget(max_value=480),
	}
	label_columns = {
		"lo_id": _("Content ID"),
		"title": _("Title"),
		"lo_type": _("Type"),
		"difficulty": _("Difficulty"),
		"estimated_duration_minutes": _("Duration (min)"),
		"is_published": _("Published"),
		"competencies": _("Competencies"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.platform.education_platform.models import LearningObject
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		lo_type = request.args.get("lo_type")
		published_only = request.args.get("published") == "true"
		q = sa.select(LearningObject).order_by(LearningObject.title)
		if tenant_id:
			q = q.where(LearningObject.tenant_id == tenant_id)
		if lo_type:
			q = q.where(LearningObject.lo_type == lo_type)
		if published_only:
			q = q.where(LearningObject.is_published.is_(True))
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"lo_id": r.lo_id,
				"title": r.title,
				"lo_type": r.lo_type,
				"difficulty": r.difficulty,
				"estimated_duration_minutes": r.estimated_duration_minutes,
				"is_published": r.is_published,
				"tool_id": r.tool_id,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.platform.education_platform.models import LearningObject
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "lo_id", "title", "lo_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		lo = LearningObject(
			tenant_id=data["tenant_id"],
			lo_id=data["lo_id"],
			title=data["title"],
			description=data.get("description"),
			lo_type=data["lo_type"],
			tool_id=data.get("tool_id"),
			external_id=data.get("external_id"),
			estimated_duration_minutes=data.get("estimated_duration_minutes"),
			competencies=data.get("competencies", []),
			difficulty=data.get("difficulty", "INTERMEDIATE"),
			is_published=data.get("is_published", False),
		)
		session.add(lo)
		session.flush()
		session.commit()
		return jsonify({"lo_id": lo.id, "status": "created"}), 201


# ---------------------------------------------------------------------------
# LearningPathView
# ---------------------------------------------------------------------------

class LearningPathView(BaseView):
	"""Manage learning paths and query per-learner completion progress.

	Widget config:
	  estimated_hours  → progress_widget (display, max 200h)
	  is_mandatory     → Boolean toggle
	"""

	route_base = "/education/paths"
	default_view = "list"

	field_widgets = {
		"estimated_hours": progress_widget(max_value=200),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.platform.education_platform.models import LearningPath
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(LearningPath).order_by(LearningPath.name)
		if tenant_id:
			q = q.where(LearningPath.tenant_id == tenant_id)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"name": r.name,
				"target_role": r.target_role,
				"estimated_hours": float(r.estimated_hours) if r.estimated_hours else None,
				"is_mandatory": r.is_mandatory,
				"certification_id": r.certification_id,
			}
			for r in rows
		])

	@expose("/<string:path_id>/progress")
	@has_access
	def progress(self, path_id: str):
		"""GET /education/paths/<path_id>/progress?learner_id=<uuid>

		Widget: AdvancedChartsWidget (donut) showing required vs completed items.
		"""
		learner_id = request.args.get("learner_id")
		if not learner_id:
			return jsonify({"error": "learner_id required"}), 400
		session = _get_session()
		try:
			result = _svc().calculate_completion_progress(
				session, learner_id=learner_id, path_id=path_id,
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

		# Augment with chart config hint for UI
		result["_chart_config"] = chart_widget("doughnut")
		return jsonify(result)


# ---------------------------------------------------------------------------
# LearnerActivityView
# ---------------------------------------------------------------------------

class LearnerActivityView(BaseView):
	"""View and record learner activity (xAPI statements).

	Widget config:
	  progress_pct  → RangeSliderWidget (readonly)
	  score         → StarRatingWidget (readonly, max=100)
	  xapi_statements → JSONEditorWidget (readonly)
	"""

	route_base = "/education/learners"
	default_view = "activity"

	field_widgets = {
		"progress_pct": progress_widget(max_value=100),
		"score": star_widget(max_rating=100, readonly=True),
		"xapi_statements": json_widget(mode="view", readonly=True),
	}

	@expose("/<string:learner_id>/activity")
	@has_access
	def activity(self, learner_id: str):
		from pgappforge.plugins.erp.platform.education_platform.models import LearnerActivity
		session = _get_session()
		limit = int(request.args.get("limit", 50))
		q = (
			sa.select(LearnerActivity)
			.where(LearnerActivity.learner_id == learner_id)
			.order_by(LearnerActivity.started_at.desc())
			.limit(limit)
		)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"lo_id": r.lo_id,
				"started_at": r.started_at.isoformat() if r.started_at else None,
				"completed_at": r.completed_at.isoformat() if r.completed_at else None,
				"progress_pct": float(r.progress_pct),
				"score": float(r.score) if r.score is not None else None,
				"passed": r.passed,
				"time_spent_seconds": r.time_spent_seconds,
				"attempts": r.attempts,
			}
			for r in rows
		])

	@expose("/xapi", methods=["POST"])
	@has_access
	def record_xapi(self):
		"""POST /education/learners/xapi — record an xAPI statement."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("learner_id", "verb", "object_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			activity = _svc().record_xapi_statement(
				session=session,
				learner_id=data["learner_id"],
				verb=data["verb"],
				object_id=data["object_id"],
				result=data.get("result", {}),
				tenant_id=data.get("tenant_id", ""),
			)
			session.commit()
			return jsonify({
				"activity_id": activity.id,
				"progress_pct": float(activity.progress_pct),
				"passed": activity.passed,
				"status": "recorded",
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# CredentialView
# ---------------------------------------------------------------------------

class CredentialView(BaseView):
	"""Manage verifiable credentials and issuance.

	Widget config:
	  evidence_schema → JSONEditorWidget
	  verification_url QR code → QrCodeWidget
	"""

	route_base = "/education/credentials"
	default_view = "list"

	field_widgets = {
		"evidence_schema": json_widget(mode="tree"),
		"verification_url": qr_widget(size=200),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.platform.education_platform.models import VerifiableCredential
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(VerifiableCredential).order_by(VerifiableCredential.name)
		if tenant_id:
			q = q.where(VerifiableCredential.tenant_id == tenant_id)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"credential_type": r.credential_type,
				"name": r.name,
				"issuer_id": r.issuer_id,
				"valid_duration_days": r.valid_duration_days,
				"is_active": r.is_active,
			}
			for r in rows
		])

	@expose("/<string:credential_id>/issue", methods=["POST"])
	@has_access
	def issue(self, credential_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("recipient_id"):
			return jsonify({"error": "recipient_id required"}), 400
		try:
			issued = _svc().issue_credential(
				session=session,
				credential_id=credential_id,
				recipient_id=data["recipient_id"],
				evidence=data.get("evidence", {}),
				tenant_id=data.get("tenant_id", ""),
			)
			session.commit()
			return jsonify({
				"issued_credential_id": issued.id,
				"verification_url": issued.verification_url,
				"issued_at": issued.issued_at.isoformat(),
				"expires_at": issued.expires_at.isoformat() if issued.expires_at else None,
				"status": "issued",
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/verify")
	@has_access
	def verify(self):
		"""GET /education/credentials/verify?url=<verification_url>"""
		verification_url = request.args.get("url")
		if not verification_url:
			return jsonify({"error": "url parameter required"}), 400
		session = _get_session()
		result = _svc().verify_credential(session, verification_url=verification_url)
		return jsonify(result)


# ---------------------------------------------------------------------------
# LTILaunchView
# ---------------------------------------------------------------------------

class LTILaunchView(BaseView):
	"""Generate LTI 1.3 launch parameters.

	POST /education/lti/launch
	Body: {tool_id, learner_id, lo_id}
	Returns JWT claim set ready for signing.
	"""

	route_base = "/education/lti"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({"endpoints": ["/education/lti/launch"]})

	@expose("/launch", methods=["POST"])
	@has_access
	def launch(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tool_id", "learner_id", "lo_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			params = _svc().launch_lti_tool(
				session=session,
				tool_id=data["tool_id"],
				learner_id=data["learner_id"],
				lo_id=data["lo_id"],
			)
			return jsonify(params)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# RecommendationView
# ---------------------------------------------------------------------------

class RecommendationView(BaseView):
	"""Next learning recommendations for a learner.

	GET /education/learners/<learner_id>/recommend

	Widget: AdvancedChartsWidget (horizontal bar: competency gap coverage).
	"""

	route_base = "/education/learners"
	default_view = "recommend"

	@expose("/<string:learner_id>/recommend")
	@has_access
	def recommend(self, learner_id: str):
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		limit = int(request.args.get("limit", 5))
		try:
			items = _svc().recommend_next_learning(
				session=session,
				learner_id=learner_id,
				tenant_id=tenant_id,
				limit=limit,
			)
			return jsonify({
				"learner_id": learner_id,
				"recommendations": [
					{
						"id": lo.id,
						"lo_id": lo.lo_id,
						"title": lo.title,
						"lo_type": lo.lo_type,
						"difficulty": lo.difficulty,
						"estimated_duration_minutes": lo.estimated_duration_minutes,
					}
					for lo in items
				],
				"_chart_config": chart_widget("horizontalBar"),
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


__all__ = [
	"LMSToolView",
	"LearningObjectView",
	"LearningPathView",
	"LearnerActivityView",
	"CredentialView",
	"LTILaunchView",
	"RecommendationView",
]
