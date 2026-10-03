"""Request-scoped correlation context for PgAppForge.

Provides a :class:`RequestContextFilter` that stamps every ``LogRecord`` with
the current request id, the active OpenTelemetry trace/span ids, and the
authenticated user and tenant.  Also installs the Flask hooks that mint (or
adopt) a request id and echo it back on the response.

Every function here is best effort: outside a request context, or without the
OTel SDK installed, the values degrade to ``-`` rather than raising.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

log = logging.getLogger(__name__)

#: Attribute names injected into every record (also consumed by ``JsonFormatter``).
CONTEXT_FIELDS = ("request_id", "trace_id", "span_id", "user_id", "tenant_id")

_NONE = "-"

# Inbound request ids are echoed to clients and written to the audit log, so
# cap the length and keep them printable ASCII.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")

_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")

_MAX_REQUEST_ID = 64


def _has_request_context() -> bool:
	try:
		from flask import has_request_context
		return bool(has_request_context())
	except Exception:
		return False


def current_request_id() -> str | None:
	"""Return the current request id, or ``None`` outside a request.

	Safe to call from anywhere — CLI commands, background threads, and the
	audit hook all use this rather than touching ``flask.g`` directly.
	"""
	if not _has_request_context():
		return None
	try:
		from flask import g
		return getattr(g, "request_id", None)
	except Exception:
		return None


def _sanitise_request_id(value: Any) -> str | None:
	"""Return ``value`` if it is a safe, bounded correlation id, else ``None``."""
	if not isinstance(value, str):
		return None
	value = value.strip()
	if not value or len(value) > _MAX_REQUEST_ID:
		return None
	return value if _REQUEST_ID_RE.match(value) else None


def _current_trace_context() -> tuple[str, str]:
	"""Return ``(trace_id, span_id)`` from the active OTel span, or ``(None, None)``."""
	try:
		from opentelemetry import trace
		span = trace.get_current_span()
		ctx = span.get_span_context() if span is not None else None
		if ctx is None or not ctx.is_valid:
			return None, None
		return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
	except Exception:
		return None, None


class RequestContextFilter(logging.Filter):
	"""Inject request/trace/user/tenant identifiers into every ``LogRecord``.

	Attach to the root logger (see :func:`pgappforge.observability.configure_logging`)
	so that records from the ~1,000 modules that call ``getLogger`` are
	decorated without any call-site changes.

	Out-of-band libraries that already set ``request_id`` explicitly keep their
	value; the filter only fills in what is missing.
	"""

	def filter(self, record: logging.LogRecord) -> bool:
		trace_id = span_id = None
		request_id = None
		user_id = None
		tenant_id = None

		if _has_request_context():
			try:
				from flask import g
				request_id = getattr(g, "request_id", None)
				user_id = getattr(g, "user_id", None)
				tenant_id = getattr(g, "tenant_id", None)
			except Exception:
				pass

		if request_id is None or trace_id is None:
			trace_id, span_id = _current_trace_context()

		existing = {
			"request_id": request_id,
			"trace_id":   trace_id,
			"span_id":    span_id,
			"user_id":    user_id,
			"tenant_id":  tenant_id,
		}
		for name, value in existing.items():
			# An explicitly-supplied attribute (extra={...}) wins over inference.
			if getattr(record, name, None) in (None, "", _NONE):
				setattr(record, name, value if value else _NONE)
		return True


def _before_request() -> None:
	"""Adopt an inbound correlation id or mint a fresh one for this request."""
	from flask import g, request

	inbound = _sanitise_request_id(request.headers.get("X-Request-ID"))
	g.request_id = inbound or str(uuid.uuid4())

	# W3C trace context: adopt when well formed, otherwise leave it to OTel.
	tp = request.headers.get("traceparent", "")
	if _TRACEPARENT_RE.match(tp):
		g.traceparent = tp

	# Populated by the app's auth layer when available; the filter falls back
	# to whatever is on g, so these stay optional.
	if not hasattr(g, "user_id"):
		g.user_id = None
	if not hasattr(g, "tenant_id"):
		g.tenant_id = None


def _after_request(response):
	"""Echo the request id on the response so clients can correlate."""
	from flask import g
	request_id = getattr(g, "request_id", None)
	if request_id:
		response.headers["X-Request-ID"] = request_id
	return response


def install_request_context(app) -> None:
	"""Register the request-id ``before_request``/``after_request`` hooks.

	Idempotent: a second call on the same app is a no-op, so importing from a
	second extension or re-running an app factory is harmless.

	Args:
		app: Flask application instance.
	"""
	registrations = app.extensions.setdefault("pgappforge", {})
	if registrations.get("request_context"):
		return
	registrations["request_context"] = True

	try:
		app.before_request(_before_request)
		app.after_request(_after_request)
	except AssertionError as exc:
		# Flask refuses registration once the app has handled a request.  Losing
		# correlation ids is a nuisance; losing the request is not an option.
		registrations["request_context"] = False
		log.warning("install_request_context: app already serving requests: %s", exc)


__all__ = [
	"CONTEXT_FIELDS",
	"RequestContextFilter",
	"current_request_id",
	"install_request_context",
]
