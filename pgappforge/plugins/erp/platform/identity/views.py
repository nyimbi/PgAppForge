"""
pgappforge/plugins/erp/platform/identity/views.py

Flask views for the Identity plugin.

Endpoints:
  IdentityProviderView  GET/POST /identity/providers/
                        POST     /identity/providers/<id>/deactivate
  UserSessionView       POST     /identity/sessions/
                        GET      /identity/sessions/<id>/validate
                        POST     /identity/sessions/<id>/revoke
  MFADeviceView         POST     /identity/mfa/devices/
                        POST     /identity/mfa/devices/<id>/verify
  AccessPolicyView      GET/POST /identity/policies/
                        GET      /identity/policies/evaluate
  IdentityReportView    GET      /identity/reports/{active-sessions,mfa-coverage,policy-summary}
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import abort, jsonify, request

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
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.platform.identity.services import IdentityService
	return IdentityService()


# ---------------------------------------------------------------------------
# IdentityProviderView
# ---------------------------------------------------------------------------

class IdentityProviderView(BaseView):
	route_base = "/identity/providers"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.platform.identity.models import IdentityProvider
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(IdentityProvider).order_by(IdentityProvider.name)
		if tenant_id:
			q = q.where(IdentityProvider.tenant_id == tenant_id)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"name": r.name,
				"provider_type": r.provider_type,
				"is_default": r.is_default,
				"is_active": r.is_active,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "name", "provider_type", "config")
		missing = [f for f in required if not data.get(f) and data.get(f) != {}]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().create_provider(
				session=session,
				tenant_id=data["tenant_id"],
				name=data["name"],
				provider_type=data["provider_type"],
				config=data["config"],
				is_default=data.get("is_default", False),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:provider_id>/deactivate", methods=["POST"])
	@has_access
	def deactivate(self, provider_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			result = _svc().deactivate_provider(
				session, provider_id, reason=data.get("reason", "")
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# UserSessionView
# ---------------------------------------------------------------------------

class UserSessionView(BaseView):
	route_base = "/identity/sessions"
	default_view = "create"

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("tenant_id") or not data.get("user_id"):
			return jsonify({"error": "tenant_id and user_id required"}), 400
		try:
			result = _svc().create_session(
				session=session,
				tenant_id=data["tenant_id"],
				user_id=int(data["user_id"]),
				ip_address=data.get("ip_address"),
				user_agent=data.get("user_agent"),
				session_hours=data.get("session_hours"),
				mfa_required=data.get("mfa_required", False),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:session_id>/validate")
	@has_access
	def validate(self, session_id: str):
		"""Validate by session_id (not token — token is in header in real auth)."""
		from pgappforge.plugins.erp.platform.identity.models import UserSession
		from pgappforge.plugins.erp.platform.identity.services import (
			SessionExpiredError,
		)
		db_session = _get_session()
		row = db_session.get(UserSession, session_id)
		if row is None:
			abort(404, "Session not found")
		try:
			result = _svc().validate_session(
				db_session, token=row.session_token, touch=True
			)
			db_session.commit()
			return jsonify(result)
		except SessionExpiredError as exc:
			db_session.commit()
			return jsonify({"valid": False, "reason": str(exc)}), 401

	@expose("/<string:session_id>/revoke", methods=["POST"])
	@has_access
	def revoke(self, session_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			result = _svc().revoke_session(
				session, session_id, reason=data.get("reason", "")
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# MFADeviceView
# ---------------------------------------------------------------------------

class MFADeviceView(BaseView):
	route_base = "/identity/mfa/devices"
	default_view = "register"

	@expose("/", methods=["POST"])
	@has_access
	def register(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "user_id", "device_type", "device_name", "secret_encrypted")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().register_mfa_device(
				session=session,
				tenant_id=data["tenant_id"],
				user_id=int(data["user_id"]),
				device_type=data["device_type"],
				device_name=data["device_name"],
				secret_encrypted=data["secret_encrypted"],
				is_primary=data.get("is_primary", False),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:device_id>/verify", methods=["POST"])
	@has_access
	def verify(self, device_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			result = _svc().verify_mfa_device(
				session,
				device_id=device_id,
				session_id=data.get("session_id"),
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# AccessPolicyView
# ---------------------------------------------------------------------------

class AccessPolicyView(BaseView):
	route_base = "/identity/policies"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.platform.identity.models import AccessPolicy
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(AccessPolicy).order_by(AccessPolicy.policy_name)
		if tenant_id:
			q = q.where(
				AccessPolicy.tenant_id == tenant_id,
				AccessPolicy.is_active.is_(True),
			)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"policy_name": r.policy_name,
				"resource_type": r.resource_type,
				"resource_id": r.resource_id,
				"principal_type": r.principal_type,
				"principal_id": r.principal_id,
				"permissions": r.permissions,
				"effect": r.effect,
				"is_active": r.is_active,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "policy_name", "resource_type",
			"principal_type", "principal_id", "permissions",
		)
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().create_policy(
				session=session,
				tenant_id=data["tenant_id"],
				policy_name=data["policy_name"],
				resource_type=data["resource_type"],
				principal_type=data["principal_type"],
				principal_id=data["principal_id"],
				permissions=data["permissions"],
				effect=data.get("effect", "ALLOW"),
				resource_id=data.get("resource_id"),
				conditions=data.get("conditions"),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/evaluate")
	@has_access
	def evaluate(self):
		"""Evaluate access. Query params: tenant_id, principal_type, principal_id,
		resource_type, action, resource_id (optional)."""
		session = _get_session()
		args = request.args
		required = ("tenant_id", "principal_type", "principal_id", "resource_type", "action")
		missing = [f for f in required if not args.get(f)]
		if missing:
			return jsonify({"error": f"Missing query params: {missing}"}), 400
		result = _svc().evaluate_access(
			session=session,
			tenant_id=args["tenant_id"],
			principal_type=args["principal_type"],
			principal_id=args["principal_id"],
			resource_type=args["resource_type"],
			action=args["action"],
			resource_id=args.get("resource_id"),
		)
		return jsonify(result)


# ---------------------------------------------------------------------------
# IdentityReportView
# ---------------------------------------------------------------------------

class IdentityReportView(BaseView):
	"""Identity management reports.

	GET /identity/reports/active-sessions  — active sessions count by tenant
	GET /identity/reports/mfa-coverage     — % users with verified MFA device
	GET /identity/reports/policy-summary   — policy counts by effect and principal type
	"""

	route_base = "/identity/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"reports": [
				{"name": "Active Sessions", "endpoint": "/identity/reports/active-sessions"},
				{"name": "MFA Coverage", "endpoint": "/identity/reports/mfa-coverage"},
				{"name": "Policy Summary", "endpoint": "/identity/reports/policy-summary"},
			]
		})

	@expose("/active-sessions")
	@has_access
	def active_sessions(self):
		from pgappforge.plugins.erp.platform.identity.models import UserSession
		from sqlalchemy import func as F
		session = _get_session()
		rows = session.execute(
			sa.select(
				UserSession.tenant_id,
				F.count().label("count"),
				F.sum(sa.cast(UserSession.mfa_verified, sa.Integer)).label("mfa_verified_count"),
			)
			.where(UserSession.is_active.is_(True))
			.group_by(UserSession.tenant_id)
			.order_by(sa.desc("count"))
		).all()
		return jsonify([
			{
				"tenant_id": str(r.tenant_id),
				"active_sessions": r.count,
				"mfa_verified": r.mfa_verified_count,
			}
			for r in rows
		])

	@expose("/mfa-coverage")
	@has_access
	def mfa_coverage(self):
		from pgappforge.plugins.erp.platform.identity.models import MFADevice
		from sqlalchemy import func as F
		from pgappforge.security.manager import current_user
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(
			MFADevice.user_id,
			F.count().label("device_count"),
			F.sum(
				sa.case((MFADevice.verified_at.isnot(None), 1), else_=0)
			).label("verified_count"),
		).group_by(MFADevice.user_id)
		if tenant_id:
			q = q.where(MFADevice.tenant_id == tenant_id)
		rows = session.execute(q).all()
		total_users = len(rows)
		users_with_verified = sum(1 for r in rows if r.verified_count > 0)
		coverage_pct = round(
			(users_with_verified / total_users * 100) if total_users else 0, 2
		)
		return jsonify({
			"total_users_with_devices": total_users,
			"users_with_verified_mfa": users_with_verified,
			"mfa_coverage_pct": coverage_pct,
		})

	@expose("/policy-summary")
	@has_access
	def policy_summary(self):
		from pgappforge.plugins.erp.platform.identity.models import AccessPolicy
		from sqlalchemy import func as F
		session = _get_session()
		rows = session.execute(
			sa.select(
				AccessPolicy.principal_type,
				AccessPolicy.effect,
				F.count().label("count"),
			)
			.where(AccessPolicy.is_active.is_(True))
			.group_by(AccessPolicy.principal_type, AccessPolicy.effect)
			.order_by(AccessPolicy.principal_type, AccessPolicy.effect)
		).all()
		return jsonify([
			{
				"principal_type": r.principal_type,
				"effect": r.effect,
				"count": r.count,
			}
			for r in rows
		])


__all__ = [
	"IdentityProviderView",
	"UserSessionView",
	"MFADeviceView",
	"AccessPolicyView",
	"IdentityReportView",
]
