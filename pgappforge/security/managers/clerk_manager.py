"""
pgappforge/security/managers/clerk_manager.py

ClerkSecurityManager — validates Clerk JWTs on API requests.
FAB admin UI uses FAB session auth; API endpoints validate Clerk tokens.
"""
from __future__ import annotations

import logging

from pgappforge.security.sqla.manager import SecurityManager

log = logging.getLogger(__name__)


class ClerkSecurityManager(SecurityManager):
	"""FAB SecurityManager that validates Clerk session tokens on API requests."""

	def __init__(self, appbuilder):
		super().__init__(appbuilder)
		appbuilder.get_app().before_request(self.before_request)

	def before_request(self) -> None:
		try:
			from flask import request, g
			auth_header = request.headers.get("Authorization", "")
			if not auth_header.startswith("Bearer "):
				return
			token = auth_header[7:]
			from pgappforge.security.providers.clerk import ClerkAuthProvider
			provider = ClerkAuthProvider()
			auth_user = provider.validate_token(token)
			if auth_user:
				g.auth_user = auth_user
				provider.sync_to_fab(auth_user, None)
		except Exception as exc:
			log.debug("ClerkSecurityManager.before_request: %s", exc)


__all__ = ["ClerkSecurityManager"]
