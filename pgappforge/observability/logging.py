"""Structured logging configuration for PgAppForge.

Provides:

* :class:`RedactionFilter` — scrubs credential-shaped keys and neutralises
  log-injection (CR/LF and control characters), then caps record size.
* :class:`SamplingFilter` — rate-limits repeated INFO/DEBUG records without
  ever dropping WARNING or above.
* :class:`JsonFormatter` / :class:`HumanFormatter` — hand-rolled so that
  ``structlog`` is not a dependency.
* :func:`configure_logging` — installs a ``dictConfig`` on the root logger.

Output is single-line JSON on stdout when ``PGAF_LOG_FORMAT=json`` or
``ENV=production``, otherwise a compact human format on stderr.

This module must never raise: a broken logging config takes the whole app down,
which is strictly worse than unstructured logs.
"""
from __future__ import annotations

import json
import logging
import logging.config
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

#: Maximum characters emitted for a single record's message.
MAX_RECORD_CHARS = 8_000

REDACTED = "***REDACTED***"

#: Keys whose values must never reach the log stream.
SENSITIVE_KEYS = (
	"password",
	"passwd",
	"token",
	"secret",
	"api_key",
	"apikey",
	"authorization",
	"cookie",
)

# Record attributes copied into the JSON payload when present.
_EXTRA_ATTRS = (
	"request_id",
	"trace_id",
	"span_id",
	"user_id",
	"tenant_id",
	"module",
	"funcName",
	"lineno",
	"process",
	"threadName",
)

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Credential assignment in a free-form message, e.g. "password=hunter2".
_KV_RE = re.compile(
	r"(?i)\b(" + "|".join(re.escape(k) for k in SENSITIVE_KEYS) + r")"
	r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&}\]]+)"
)

# Bearer/Basic credential headers pasted into a log line.
_AUTH_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}")


# ── Redaction ─────────────────────────────────────────────────────────────────

def _scrub_text(text: str) -> str:
	"""Redact credential-shaped substrings and strip CR/LF and control chars.

	CR and LF removal is the log-injection defence: a newline in user-supplied
	text would let an attacker forge an entire fake log line.
	"""
	text = _CONTROL_RE.sub("", text).replace("\r", "").replace("\n", "")
	text = _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
	text = _AUTH_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
	return text


def _scrub_value(value: Any) -> Any:
	"""Recursively redact a value, preserving its shape where possible."""
	if isinstance(value, dict):
		out: dict[Any, Any] = {}
		for key, val in value.items():
			if isinstance(key, str) and any(k in key.lower() for k in SENSITIVE_KEYS):
				out[key] = REDACTED
			else:
				out[key] = _scrub_value(val)
		return out
	if isinstance(value, (list, tuple)):
		return [_scrub_value(v) for v in value]
	if isinstance(value, str):
		return _scrub_text(value)
	return value


def _truncate(text: str, limit: int = MAX_RECORD_CHARS) -> str:
	if len(text) <= limit:
		return text
	return text[: limit - 15] + "...[TRUNCATED]"


class RedactionFilter(logging.Filter):
	"""Scrub secrets and neutralise log injection on the way to a handler.

	Handles the three shapes a record message arrives in:

	* ``record.msg`` as a plain string,
	* ``record.msg`` as a format string with ``record.args`` of strings,
	* ``record.msg`` as a format string with ``record.args`` of dicts
	  (``logger.info("x %s", {"token": "s"})``).

	A non-string ``record.msg`` (a dict or exception object) is redacted
	recursively where possible and otherwise passed through untouched.
	"""

	def filter(self, record: logging.LogRecord) -> bool:
		# 1. Structured args — this is where secrets usually leak.
		args = record.args
		if isinstance(args, tuple):
			record.args = tuple(_scrub_value(a) for a in args)
		elif isinstance(args, dict):
			record.args = _scrub_value(args)

		# 2. The message itself.
		msg = record.msg
		if isinstance(msg, str):
			record.msg = _truncate(_scrub_text(msg))
		elif isinstance(msg, (dict, list, tuple)):
			record.msg = _scrub_value(msg)

		# 3. Newlines injected through the *formatted* result (e.g. an
		#    exception whose traceback spans lines) must not reach a raw
		#    handler.  Formatting here also caps the final size.
		try:
			rendered = record.getMessage()
		except Exception:
			return True
		if "\n" in rendered or "\r" in rendered or len(rendered) > MAX_RECORD_CHARS:
			record.msg = _truncate(_scrub_text(rendered))
			record.args = ()
		return True


# ── Sampling ──────────────────────────────────────────────────────────────────

class SamplingFilter(logging.Filter):
	"""Rate-limit repeated records by ``(logger name, message template)``.

	A hot loop that logs the same message 10k times a minute is noise that
	displaces real signal.  At most ``per_minute`` (default 20) instances of a
	given template reach a handler per 60-second window.  WARNING and above are
	never dropped — sampling a warning is how incidents get missed.

	Args:
		per_minute: Maximum emissions per ``(name, msg)`` template per window.
		level: Records at or above this level bypass sampling entirely.
	"""

	def __init__(self, name: str = "", level: int = logging.WARNING, per_minute: int = 20) -> None:
		super().__init__(name)
		self.level = level
		self.per_minute = max(1, int(per_minute))
		self._window_seconds = 60.0
		self._lock = threading.Lock()
		# (logger name, template) -> (window start, count)
		self._counts: dict[tuple[str, str], tuple[float, int]] = {}
		self.suppressed = 0

	def filter(self, record: logging.LogRecord) -> bool:
		if record.levelno >= self.level:
			return True
		key = (record.name, str(record.msg)[:512])
		now = time.monotonic()
		with self._lock:
			start, count = self._counts.get(key, (now, 0))
			if now - start >= self._window_seconds:
				start, count = now, 0
			if count >= self.per_minute:
				self._counts[key] = (start, count + 1)
				self.suppressed += 1
				return False
			self._counts[key] = (start, count + 1)
			if len(self._counts) > 4096:
				# Bound memory: drop windows that have already expired.
				self._counts = {k: v for k, v in self._counts.items() if now - v[0] < self._window_seconds}
		return True


# ── Formatters ────────────────────────────────────────────────────────────────

class _BaseFormatter(logging.Formatter):
	def __init__(self) -> None:
		super().__init__()

	@staticmethod
	def _extras(record: logging.LogRecord) -> dict[str, Any]:
		out: dict[str, Any] = {}
		for name in _EXTRA_ATTRS:
			value = getattr(record, name, None)
			if value not in (None, ""):
				out[name] = value if isinstance(value, (str, int, float, bool)) else str(value)
		return out

	def formatException(self, ei) -> str:  # type: ignore[override]
		# Standard traceback, with CR/LF collapsed by the redaction filter where
		# it matters; JSON encoding handles the embedded newlines correctly.
		return super().formatException(ei)


class JsonFormatter(_BaseFormatter):
	"""Render a record as one line of JSON.

	Shape::

		{"timestamp": "...", "level": "INFO", "logger": "x", "message": "...",
		 "request_id": "...", "trace_id": "...", ...}

	Implemented by hand — ``structlog`` is not a dependency, and a JSON log
	line that a shell pipeline cannot parse is not much of a log.
	"""

	def format(self, record: logging.LogRecord) -> str:
		created = datetime.fromtimestamp(record.created, tz=timezone.utc)
		payload: dict[str, Any] = {
			"timestamp": created.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
			"level": record.levelname,
			"logger": record.name,
			"message": _truncate(record.getMessage()),
		}
		payload.update(self._extras(record))
		if record.exc_info:
			payload["exception"] = _truncate(self.formatException(record.exc_info))
		if record.stack_info:
			payload["stack"] = _truncate(record.stack_info)
		try:
			return json.dumps(payload, default=str, ensure_ascii=False)
		except Exception:  # pragma: no cover - defensive
			return json.dumps({"timestamp": payload["timestamp"], "level": "ERROR",
			                   "logger": __name__, "message": "log record not serialisable"})


class HumanFormatter(_BaseFormatter):
	"""Compact single-line format for local development."""

	def format(self, record: logging.LogRecord) -> str:
		created = datetime.fromtimestamp(record.created, tz=timezone.utc)
		stamp = created.strftime("%H:%M:%S")
		context = ""
		rid = getattr(record, "request_id", None)
		if rid and rid != "-":
			context = f" [{rid}]"
		line = f"{stamp} {record.levelname:<7} {record.name}{context} {record.getMessage()}"
		if record.exc_info:
			line += "\n" + self.formatException(record.exc_info)
		return _truncate(line)


# ── Configuration ─────────────────────────────────────────────────────────────

def _log_level() -> str:
	level = os.environ.get("PGAF_LOG_LEVEL", "INFO")
	return level if isinstance(level, str) and level.strip() else "INFO"


def _use_json(app: Any = None) -> bool:
	fmt = os.environ.get("PGAF_LOG_FORMAT")
	if fmt:
		return fmt.strip().lower() == "json"
	env = os.environ.get("ENV", "")
	return env.strip().lower() in {"production", "prod"}


def configure_logging(app: Any = None) -> bool:
	"""Install the root logging configuration for this process.

	Called from ``AppBuilder.init_app``.  Honours ``PGAF_LOG_FORMAT`` (json |
	text), ``PGAF_LOG_LEVEL`` (default INFO) and ``PGAF_LOG_SAMPLE_PER_MINUTE``
	(default 20).  Never raises — on any failure it logs a CRITICAL diagnostic
	and leaves the existing handlers in place.

	Args:
		app: Optional Flask app; if it is configured, Flask/Werkzeug request
			loggers are routed through the same handlers.

	Returns:
		True if the config was applied, False if it degraded.
	"""
	try:
		from .context import RequestContextFilter

		json_mode = _use_json(app)
		level = _log_level()
		try:
			per_minute = int(os.environ.get("PGAF_LOG_SAMPLE_PER_MINUTE", "20"))
		except ValueError:
			per_minute = 20

		if json_mode:
			# stdout: the collector (Docker/journald/Loki) reads it.
			stream = "ext://sys.stdout"
			fmt_factory: Any = JsonFormatter
		else:
			stream = "ext://sys.stderr"
			fmt_factory = HumanFormatter

		config = {
			"version": 1,
			"disable_existing_loggers": False,
			"filters": {
				"request_context": {"()": "pgappforge.observability.context.RequestContextFilter"},
				"redaction": {"()": "pgappforge.observability.logging.RedactionFilter"},
				"sampling": {
					"()": "pgappforge.observability.logging.SamplingFilter",
					"per_minute": per_minute,
				},
			},
			"formatters": {
				"pgaf": {"()": fmt_factory},
			},
			"handlers": {
				"console": {
					"class": "logging.StreamHandler",
					"formatter": "pgaf",
					"stream": stream,
					"filters": ["request_context", "redaction", "sampling"],
				},
			},
			"root": {"level": level, "handlers": ["console"]},
			"loggers": {
				"werkzeug": {"level": "WARNING", "handlers": ["console"], "propagate": False},
				"pgappforge.access": {"level": level, "handlers": ["console"], "propagate": False},
			},
		}

		logging.config.dictConfig(config)

		# dictConfig instantiates the filters per handler; attach the request
		# context filter to the root logger too so records emitted by handlers
		# added later (e.g. by an addon) still carry correlation ids.
		root = logging.getLogger()
		if not any(isinstance(f, RequestContextFilter) for f in root.filters):
			root.addFilter(RequestContextFilter())

		if app is not None:
			try:
				app.extensions.setdefault("pgappforge", {})["log_format"] = "json" if json_mode else "text"
			except Exception:
				pass
		return True
	except Exception as exc:  # pragma: no cover - defensive by design
		logging.getLogger(__name__).critical(
			"configure_logging failed, keeping existing handlers: %s", exc, exc_info=True
		)
		return False


__all__ = [
	"MAX_RECORD_CHARS",
	"REDACTED",
	"SENSITIVE_KEYS",
	"JsonFormatter",
	"HumanFormatter",
	"RedactionFilter",
	"SamplingFilter",
	"configure_logging",
]
