"""Embeddable PgAppForge views via iframe.

Provides:
- X-Frame-Options management (default DENY; per-view or global override)
- JWT token extraction from ``?_token=<jwt>`` for cross-origin embedded auth
- CORS response headers for API endpoints called from embedded contexts
- ``configure_embedding(app)`` — call once in your app factory

Quickstart::

    from pgappforge.embedding import configure_embedding, embeddable

    # In your app factory:
    configure_embedding(app)

    # On a view that should be frameable from a specific portal:
    @expose("/loan-form")
    @embeddable(origins=["https://bank.co.ke"])
    def loan_form(self):
        token = get_embedded_token_from_request()
        ...

Flask config keys:
    EMBED_ALLOWED_ORIGINS   list[str] | str   default []
        Origins allowed to frame the application.  ``"*"`` permits any origin.
        Example: ``["https://bank.co.ke", "https://portal.example.com"]``
    EMBED_JWT_COOKIE_NAME   str               default "_fab_token"
        Name of the cookie set when ?_token= is present in the request.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any

log = logging.getLogger(__name__)

# Module-level cache; populated by configure_embedding().
_EMBED_ALLOWED_ORIGINS: list[str] = []


# ── App factory integration ───────────────────────────────────────────────────

def configure_embedding(app) -> None:
	"""Register embedding middleware on the Flask app.

	Call once in your app factory, after ``AppBuilder`` is initialised.

	Reads:
		``EMBED_ALLOWED_ORIGINS`` — list of allowed parent frame origins.
		``EMBED_JWT_COOKIE_NAME`` — cookie name for JWT promotion (default ``_fab_token``).

	Effects:
		- Registers an ``after_request`` hook that sets ``X-Frame-Options``
		  and ``Content-Security-Policy: frame-ancestors`` on every response.
		- Registers a ``before_request`` hook that promotes ``?_token=<jwt>``
		  to an ``Authorization: Bearer`` header so the rest of the auth stack
		  sees a standard credential.
	"""
	global _EMBED_ALLOWED_ORIGINS

	try:
		raw = app.config.get("EMBED_ALLOWED_ORIGINS", [])
		_EMBED_ALLOWED_ORIGINS = raw if isinstance(raw, list) else [raw]

		cookie_name: str = app.config.get("EMBED_JWT_COOKIE_NAME", "_fab_token")

		# ── Before-request: promote ?_token query param ───────────────────────
		@app.before_request
		def _promote_embedded_token():
			"""Copy ?_token=<jwt> into the Authorization header (in-request only)."""
			try:
				from flask import request, g
				token = request.args.get("_token")
				if token:
					# Stash on g so downstream code can detect embedded context
					g.embedded_token = token
					# Flask's EnvironHeaders is immutable — patch environ directly
					# so werkzeug/security middleware sees a standard Bearer token
					environ = request.environ
					existing_auth = environ.get("HTTP_AUTHORIZATION", "")
					if not existing_auth:
						environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
			except Exception as exc:
				log.debug("embedding: token promotion skipped: %s", exc)

		# ── After-request: set frame / CSP headers ────────────────────────────
		@app.after_request
		def _set_embed_headers(response):
			try:
				# If the @embeddable decorator already set a frame-ancestors directive,
				# honour it and do not clobber with DENY.
				existing_csp = response.headers.get("Content-Security-Policy", "")
				if "frame-ancestors" in existing_csp:
					# Decorator already handled this response — nothing to do.
					return response

				if not _EMBED_ALLOWED_ORIGINS:
					# No origins configured → strict deny
					response.headers["X-Frame-Options"] = "DENY"
					return response

				from flask import request
				origin = request.headers.get("Origin", "")
				wildcard = "*" in _EMBED_ALLOWED_ORIGINS
				origin_allowed = wildcard or (origin and origin in _EMBED_ALLOWED_ORIGINS)

				if origin_allowed:
					# Remove legacy header; use CSP frame-ancestors (takes precedence
					# in modern browsers and is more expressive)
					response.headers.remove("X-Frame-Options")
					ancestors = " ".join(_EMBED_ALLOWED_ORIGINS)
					_merge_csp(response, f"frame-ancestors {ancestors}")
				else:
					response.headers["X-Frame-Options"] = "DENY"
			except Exception as exc:
				log.debug("embedding: header hook error: %s", exc)
				response.headers["X-Frame-Options"] = "DENY"
			return response

		log.info(
			"Embedding: configured — allowed origins: %s",
			_EMBED_ALLOWED_ORIGINS or "(none — DENY)",
		)

	except Exception as exc:
		log.warning("configure_embedding failed: %s", exc)


def configure_cors(app, *, origins: list[str] | None = None) -> None:
	"""Add permissive CORS headers for API endpoints called from embedded contexts.

	Call in addition to ``configure_embedding`` when your embedded view makes
	``fetch()`` calls back to PgAppForge REST API endpoints.

	Args:
		app:     Flask application.
		origins: Allowed CORS origins.  Defaults to ``EMBED_ALLOWED_ORIGINS``.
	"""
	try:
		allowed = origins or _EMBED_ALLOWED_ORIGINS or []

		@app.after_request
		def _set_cors_headers(response):
			try:
				from flask import request
				origin = request.headers.get("Origin", "")
				if not allowed or "*" in allowed or origin in allowed:
					grant = origin if origin else "*"
					response.headers["Access-Control-Allow-Origin"] = grant
					response.headers["Access-Control-Allow-Credentials"] = "true"
					response.headers["Access-Control-Allow-Methods"] = (
						"GET, POST, PUT, PATCH, DELETE, OPTIONS"
					)
					response.headers["Access-Control-Allow-Headers"] = (
						"Content-Type, Authorization, X-Requested-With"
					)
			except Exception as exc:
				log.debug("embedding: CORS hook error: %s", exc)
			return response

		log.info("Embedding: CORS configured for origins: %s", allowed or "(*)")
	except Exception as exc:
		log.warning("configure_cors failed: %s", exc)


# ── Per-view decorator ────────────────────────────────────────────────────────

def embeddable(origins: list[str] | None = None):
	"""Decorator to mark a specific view method as embeddable.

	Overrides the global ``X-Frame-Options`` / ``Content-Security-Policy``
	for responses from this endpoint only.  Takes precedence over the global
	``after_request`` hook because it runs on the already-built response object
	and sets headers last.

	Args:
		origins: Allowed parent-frame origins for this endpoint.
		         Falls back to ``_EMBED_ALLOWED_ORIGINS`` when ``None``.
		         Use ``["*"]`` to allow any origin.

	Usage::

		@expose("/loan-form")
		@embeddable(origins=["https://bank.co.ke", "https://sacco.example.com"])
		def loan_form(self):
			return self.render_template("loan_form.html")
	"""
	def decorator(fn):
		@wraps(fn)
		def wrapper(*args, **kwargs):
			result = fn(*args, **kwargs)
			try:
				from flask import request, make_response
				resp = make_response(result)
				allowed: list[str] = origins if origins is not None else list(_EMBED_ALLOWED_ORIGINS)
				if not allowed:
					# No origins — keep whatever the global hook set
					return resp
				origin = request.headers.get("Origin", "")
				wildcard = "*" in allowed
				if wildcard or (origin and origin in allowed):
					resp.headers.remove("X-Frame-Options")
					ancestors = " ".join(allowed)
					_merge_csp(resp, f"frame-ancestors {ancestors}")
				return resp
			except Exception as exc:
				log.debug("embeddable wrapper error: %s", exc)
				return result
		return wrapper
	return decorator


# ── Token extraction ──────────────────────────────────────────────────────────

def get_embedded_token_from_request() -> str | None:
	"""Return the JWT for the current embedded request, or ``None``.

	Resolution order:
	1. ``?_token=<jwt>`` query parameter.
	2. ``Authorization: Bearer <jwt>`` header (covers the promoted token from
	   ``configure_embedding``'s before_request hook).
	3. ``g.embedded_token`` stashed by the promotion hook.

	Usage::

		@expose("/invoice/<int:pk>")
		@embeddable()
		def invoice_detail(self, pk):
			token = get_embedded_token_from_request()
			if token:
				user = verify_jwt(token)
				...
	"""
	try:
		from flask import request, g

		# 1. Explicit query param (highest precedence in embedded context)
		token = request.args.get("_token")
		if token:
			return token

		# 2. Standard Authorization header (may have been set by promotion hook)
		auth_header = request.headers.get("Authorization", "")
		if auth_header.startswith("Bearer "):
			return auth_header[7:]

		# 3. g stash (set by before_request hook)
		return getattr(g, "embedded_token", None)

	except Exception:
		return None


def is_embedded_request() -> bool:
	"""Return True when the current request appears to come from an iframe.

	Heuristic: ``?_token`` present OR ``Sec-Fetch-Dest: iframe`` header set.
	"""
	try:
		from flask import request
		if request.args.get("_token"):
			return True
		sec_dest = request.headers.get("Sec-Fetch-Dest", "")
		if sec_dest == "iframe":
			return True
		return False
	except Exception:
		return False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _merge_csp(response, new_directive: str) -> None:
	"""Add or extend the Content-Security-Policy header without clobbering existing directives."""
	existing = response.headers.get("Content-Security-Policy", "")
	if not existing:
		response.headers["Content-Security-Policy"] = new_directive
		return

	# Replace an existing frame-ancestors directive if present
	directives = [d.strip() for d in existing.split(";") if d.strip()]
	filtered = [d for d in directives if not d.startswith("frame-ancestors")]
	filtered.append(new_directive)
	response.headers["Content-Security-Policy"] = "; ".join(filtered)


__all__ = [
	"configure_embedding",
	"configure_cors",
	"embeddable",
	"get_embedded_token_from_request",
	"is_embedded_request",
]
