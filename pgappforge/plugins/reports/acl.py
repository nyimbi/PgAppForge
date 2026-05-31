"""
ReportForge access control layer.

Three public helpers:

    can(user, report, permission) → bool
        Check whether *user* is allowed to perform *permission* on *report*.
        permissions: "view" | "run" | "download" | "edit"

    log_access(session, user_id, report_id, action, params, ip, fmt)
        Write an append-only ReportAccessLog row.

    check_token(token_str, session) → (report, params_json)
        Validate a ReportShareToken, decrement uses_remaining, and return
        the associated report + pre-filled params.  Raises abort(403/404).

Configuration
-------------
REPORTFORGE_ACL_ENABLED  (bool, default True)
    Set to False to bypass all ACL checks (useful for single-user installs).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from flask import abort, current_app

if TYPE_CHECKING:
	from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# ── Permission ordering (higher index = more access) ─────────────────────────
_PERM_RANK = {"view": 0, "run": 1, "download": 2, "edit": 3}


def _acl_enabled() -> bool:
	try:
		return current_app.config.get("REPORTFORGE_ACL_ENABLED", True)
	except RuntimeError:
		return True  # outside request context — be safe


def _is_admin(user) -> bool:
	if user is None:
		return False
	for role in getattr(user, "roles", []):
		name = getattr(role, "name", str(role))
		if name.lower() in ("admin", "administrator"):
			return True
	return False


def can(user, report, permission: str, session=None) -> bool:
	"""
	Return True if *user* has *permission* on *report*.

	Evaluation order (first match wins):
	1. ACL disabled in config → True
	2. user is Admin role → True
	3. user is the report creator → True (any permission)
	4. report.is_public AND permission in {view, run, download} → True
	5. ReportGrant row exists for (user_id, 'user') or any of user's (role_id, 'role')
	   with the requested permission (or a higher-ranked one) → True
	6. → False
	"""
	if not _acl_enabled():
		return True
	if user is None:
		return False
	if _is_admin(user):
		return True
	uid = getattr(user, "id", None)
	if uid is not None and report.created_by == uid:
		return True
	if permission in ("view", "run", "download") and getattr(report, "is_public", False):
		return True

	# Grant table lookup
	if session is None:
		try:
			ab = current_app.extensions.get("appbuilder")
			session = ab.session if ab else None
		except RuntimeError:
			pass
	if session is None:
		return False

	from .models import ReportGrant
	import sqlalchemy as sa

	perm_rank = _PERM_RANK.get(permission, 0)
	# Collect sufficient permissions (same or higher rank)
	sufficient = [p for p, r in _PERM_RANK.items() if r >= perm_rank]

	# User grant
	if uid is not None:
		user_grant = session.execute(
			sa.select(ReportGrant).where(
				sa.and_(
					ReportGrant.report_id == report.id,
					ReportGrant.principal_type == "user",
					ReportGrant.principal_id == uid,
					ReportGrant.permission.in_(sufficient),
				)
			)
		).scalar_one_or_none()
		if user_grant:
			return True

	# Role grants
	for role in getattr(user, "roles", []):
		role_id = getattr(role, "id", None)
		if role_id is None:
			continue
		role_grant = session.execute(
			sa.select(ReportGrant).where(
				sa.and_(
					ReportGrant.report_id == report.id,
					ReportGrant.principal_type == "role",
					ReportGrant.principal_id == role_id,
					ReportGrant.permission.in_(sufficient),
				)
			)
		).scalar_one_or_none()
		if role_grant:
			return True

	return False


def log_access(
	session,
	user_id: int | None,
	report_id: int,
	action: str,
	params: dict | None = None,
	ip: str | None = None,
	fmt: str | None = None,
) -> None:
	"""
	Append a row to ReportAccessLog.  Non-fatal — logs a warning on failure.

	Args:
	    action: one of "run", "download", "dispatch", "embed", "token"
	    fmt:    export format when action is "download" ("pdf", "xlsx", etc.)
	"""
	try:
		from .models import ReportAccessLog
		entry = ReportAccessLog(
			report_id=report_id,
			user_id=user_id,
			action=action,
			format=fmt,
			params_json=params or {},
			ip_address=ip,
			accessed_at=datetime.now(timezone.utc),
		)
		session.add(entry)
		session.flush()
	except Exception as exc:
		log.warning("ReportForge: could not write access log: %s", exc)


def check_token(token_str: str, session) -> tuple[Any, dict]:
	"""
	Validate a ReportShareToken.

	Returns ``(report, params_json)`` on success.
	Calls ``abort(404)`` if token does not exist.
	Calls ``abort(403)`` if token is expired or exhausted.
	Decrements ``uses_remaining`` (committing on success).
	"""
	from .models import ReportShareToken
	import sqlalchemy as sa

	tok = session.execute(
		sa.select(ReportShareToken).where(ReportShareToken.token == token_str)
	).scalar_one_or_none()
	if tok is None:
		abort(404)

	now = datetime.now(timezone.utc)
	if tok.expires_at and tok.expires_at.replace(tzinfo=timezone.utc) < now:
		abort(403)
	if tok.uses_remaining is not None and tok.uses_remaining <= 0:
		abort(403)

	# Decrement
	if tok.uses_remaining is not None:
		tok.uses_remaining -= 1
	session.commit()

	return tok.report, tok.params_json or {}


def generate_token(
	session,
	report_id: int,
	created_by: int | None,
	max_uses: int | None = None,
	expires_hours: int | None = 24,
	params: dict | None = None,
) -> str:
	"""
	Create and persist a ReportShareToken.  Returns the token string.

	Args:
	    max_uses:      None = unlimited; 1 = view-once
	    expires_hours: None = no expiry; default 24h
	    params:        pre-filled report parameters for the recipient
	"""
	import secrets
	from .models import ReportShareToken

	token_str = secrets.token_urlsafe(32)
	expires = None
	if expires_hours is not None:
		from datetime import timedelta
		expires = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

	tok = ReportShareToken(
		token=token_str,
		report_id=report_id,
		max_uses=max_uses,
		uses_remaining=max_uses,
		expires_at=expires,
		params_json=params or {},
		created_by=created_by,
	)
	session.add(tok)
	session.commit()
	return token_str
