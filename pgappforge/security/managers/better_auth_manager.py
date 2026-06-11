"""
pgappforge/security/managers/better_auth_manager.py

BetterAuthSecurityManager — validates BetterAuth sessions.
Checks both Authorization Bearer header and better-auth.session_token cookie.
"""
from __future__ import annotations

import logging

from pgappforge.security.sqla.manager import SecurityManager

log = logging.getLogger(__name__)


class BetterAuthSecurityManager(SecurityManager):
	"""FAB SecurityManager that validates BetterAuth sessions."""

	def before_request(self) -> None:
		try:
			from flask import request, g
			auth_header = request.headers.get("Authorization", "")
			cookie_token = request.cookies.get("better-auth.session_token", "")
			token = auth_header[7:] if auth_header.startswith("Bearer ") else cookie_token
			if not token:
				return
			from pgappforge.security.providers.better_auth import BetterAuthProvider
			auth_user = BetterAuthProvider().validate_token(token)
			if auth_user:
				g.auth_user = auth_user
		except Exception as exc:
			log.debug("BetterAuthSecurityManager.before_request: %s", exc)


__all__ = ["BetterAuthSecurityManager"]
