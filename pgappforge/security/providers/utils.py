"""
pgappforge/security/providers/utils.py

Shared helpers for auth provider implementations.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def sync_external_user_to_fab(user: Any, *, lookup_by_email: bool = False) -> Any:
	"""Upsert an AuthUser from an external provider into FAB's User table.

	Used by Keycloak, Clerk, and BetterAuth providers so that FAB's existing
	RBAC, audit logging, and admin UI continue to work with externally-authed users.

	Behaviour:
	  - Looks up by username first (or email if lookup_by_email=True).
	  - Creates the user with a blank password if not found.
	  - Syncs roles from user.roles on every call.
	  - Returns None silently on any error.

	Args:
	    user: AuthUser instance from any provider.
	    lookup_by_email: if True, prefer email as lookup key (useful when
	                     usernames are not stable, e.g. Clerk user IDs).
	"""
	try:
		from flask import current_app
		sm = current_app.appbuilder.sm

		fab_user = None
		if lookup_by_email and user.email:
			fab_user = sm.find_user(email=user.email)
		if fab_user is None:
			fab_user = sm.find_user(username=user.username)
		if fab_user is None and user.email and not lookup_by_email:
			fab_user = sm.find_user(email=user.email)

		role_objs = [sm.find_role(r) or sm.add_role(r) for r in user.roles if r]
		default_role = sm.find_role(sm.auth_role_public)

		if fab_user is None:
			fab_user = sm.add_user(
				username=user.username,
				first_name=user.first_name,
				last_name=user.last_name,
				email=user.email,
				role=role_objs[0] if role_objs else default_role,
				password="",
			)
			if fab_user and role_objs and len(role_objs) > 1:
				fab_user.roles = role_objs
				sm.get_session.commit()
		else:
			if role_objs:
				fab_user.roles = role_objs
				sm.get_session.commit()

		return fab_user
	except Exception as exc:
		log.warning("sync_external_user_to_fab failed: %s", exc)
		return None


__all__ = ["sync_external_user_to_fab"]
