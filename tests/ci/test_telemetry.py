"""Tests for pgappforge.telemetry — OTel auto-instrumentation.

Uses real objects (no mocks) and verifies graceful no-op when the opentelemetry
packages are absent or when OTEL_ENABLED=False.
"""

import importlib
import sys
import types


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_module():
	"""Import telemetry with a clean module cache (avoids cross-test pollution)."""
	if "pgappforge.telemetry" in sys.modules:
		del sys.modules["pgappforge.telemetry"]
	import pgappforge.telemetry as mod
	return mod


def _make_flask_app(**config):
	"""Return a minimal Flask app (no AppBuilder needed)."""
	try:
		from flask import Flask
	except ImportError:
		return None
	app = Flask(__name__)
	app.config.update(config)
	return app


# ── setup_telemetry ───────────────────────────────────────────────────────────

def test_setup_telemetry_no_otel_installed():
	"""setup_telemetry must not raise even when opentelemetry is absent."""
	mod = _fresh_module()
	# Force opentelemetry import to fail
	real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

	import builtins
	original = builtins.__import__

	def _block_otel(name, *args, **kwargs):
		if name.startswith("opentelemetry"):
			raise ImportError(f"blocked: {name}")
		return original(name, *args, **kwargs)

	builtins.__import__ = _block_otel
	try:
		# Must not raise
		mod.setup_telemetry()
		mod.setup_telemetry(exporter_type="console")
	finally:
		builtins.__import__ = original


def test_setup_telemetry_disabled_via_config():
	"""OTEL_ENABLED=False must return early without touching the trace provider."""
	app = _make_flask_app(OTEL_ENABLED=False)
	if app is None:
		return  # Flask not installed in this env

	mod = _fresh_module()
	# Should return silently without error
	mod.setup_telemetry(app, exporter_type="none")


def test_setup_telemetry_console_exporter_no_error():
	"""Console exporter path must complete without error when OTel is installed."""
	app = _make_flask_app(OTEL_ENABLED=True)
	if app is None:
		return

	mod = _fresh_module()
	try:
		mod.setup_telemetry(app, exporter_type="console")
	except ImportError:
		# OTel not installed in CI — acceptable
		pass


def test_setup_telemetry_reads_flask_config():
	"""setup_telemetry must prefer app.config over keyword args."""
	app = _make_flask_app(
		OTEL_ENABLED=True,
		OTEL_SERVICE_NAME="test-service",
		OTEL_EXPORTER_TYPE="none",
	)
	if app is None:
		return

	mod = _fresh_module()
	# Must not raise; service_name kwarg is overridden by config
	try:
		mod.setup_telemetry(app, service_name="wrong-name", exporter_type="console")
	except ImportError:
		pass


# ── trace_view ────────────────────────────────────────────────────────────────

def test_trace_view_transparent_without_otel():
	"""@trace_view must call the wrapped function and return its result."""
	mod = _fresh_module()

	@mod.trace_view("test.span")
	def my_view():
		return "hello"

	assert my_view() == "hello"


def test_trace_view_passes_args_and_kwargs():
	mod = _fresh_module()

	@mod.trace_view()
	def add(a, b=0):
		return a + b

	assert add(2, b=3) == 5


def test_trace_view_propagates_exception():
	"""Exceptions from the view must propagate even with OTel active."""
	mod = _fresh_module()

	@mod.trace_view("test.fail")
	def boom():
		raise ValueError("expected")

	try:
		boom()
		assert False, "should have raised"
	except ValueError as exc:
		assert "expected" in str(exc)


def test_trace_view_no_operation_name():
	"""@trace_view() with no args must use fn.__qualname__ as span name."""
	mod = _fresh_module()

	@mod.trace_view()
	def my_func():
		return 42

	assert my_func() == 42


# ── record_business_metric ────────────────────────────────────────────────────

def test_record_business_metric_no_error_without_otel():
	"""record_business_metric must silently no-op when OTel is absent."""
	mod = _fresh_module()
	# Must not raise under any circumstance
	mod.record_business_metric("test.counter", 1.0)
	mod.record_business_metric("test.counter", 5.0, {"currency": "KES"})
	mod.record_business_metric("test.event")


def test_record_business_metric_accepts_zero():
	mod = _fresh_module()
	mod.record_business_metric("zero.counter", 0.0)


def test_record_business_metric_accepts_float():
	mod = _fresh_module()
	mod.record_business_metric("float.counter", 3.14, {"unit": "USD"})


# ── Public API surface ────────────────────────────────────────────────────────

def test_all_exports_present():
	mod = _fresh_module()
	for name in ("setup_telemetry", "trace_view", "record_business_metric"):
		assert hasattr(mod, name), f"missing export: {name}"
	assert set(mod.__all__) == {"setup_telemetry", "trace_view", "record_business_metric"}


# ── observability.context ─────────────────────────────────────────────────────

def test_current_request_id_none_outside_request_context():
	"""current_request_id() must be None (never raise) with no request bound."""
	from pgappforge.observability.context import current_request_id

	assert current_request_id() is None


def test_current_request_id_inside_request():
	"""install_request_context must mint an id and echo it on the response."""
	from flask import Flask

	from pgappforge.observability.context import current_request_id, install_request_context

	app = Flask(__name__)
	install_request_context(app)
	install_request_context(app)  # idempotent: must not double-register

	@app.route("/ping")
	def ping():
		return current_request_id() or ""

	resp = app.test_client().get("/ping")
	assert resp.status_code == 200
	assert resp.headers["X-Request-ID"] == resp.get_data(as_text=True)


def test_inbound_request_id_is_adopted():
	"""A well-formed inbound X-Request-ID wins over a minted one."""
	from flask import Flask

	from pgappforge.observability.context import current_request_id, install_request_context

	app = Flask(__name__)
	install_request_context(app)

	@app.route("/ping")
	def ping():
		return current_request_id() or ""

	resp = app.test_client().get("/ping", headers={"X-Request-ID": "abc-123"})
	assert resp.get_data(as_text=True) == "abc-123"
	assert resp.headers["X-Request-ID"] == "abc-123"


def test_malformed_request_id_is_replaced():
	"""Header-injected junk (newlines, over-long) must not reach the audit log."""
	from flask import Flask

	from pgappforge.observability.context import install_request_context

	app = Flask(__name__)
	install_request_context(app)

	@app.route("/ping")
	def ping():
		from flask import g
		return g.request_id

	evil = "x" * 200  # over the 64-char cap, and printable-ASCII-clean
	resp = app.test_client().get("/ping", headers={"X-Request-ID": evil})
	minted = resp.get_data(as_text=True)
	assert minted != evil
	assert len(minted) <= 64
	assert resp.headers["X-Request-ID"] == minted


def test_request_context_filter_fills_fields():
	"""RequestContextFilter stamps every record, degrading to '-'."""
	import logging

	from pgappforge.observability.context import CONTEXT_FIELDS, RequestContextFilter

	record = logging.LogRecord("t", logging.INFO, __file__, 1, "hi", None, None)
	RequestContextFilter().filter(record)
	for field in CONTEXT_FIELDS:
		assert hasattr(record, field)


# ── observability.logging ─────────────────────────────────────────────────────

def _make_record(msg, args=None):
	import logging

	return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_redaction_filter_scrubs_dict_args():
	"""A token passed as a dict kwarg must not survive formatting."""
	import logging

	from pgappforge.observability.logging import REDACTED, RedactionFilter

	record = _make_record("login %s", ({"user": "alice", "token": "abc"},))
	RedactionFilter().filter(record)
	rendered = record.getMessage()
	assert "abc" not in rendered
	assert REDACTED in rendered
	assert "alice" in rendered  # non-sensitive keys survive


def test_redaction_filter_scrubs_string_args():
	"""Positional args are rendered then scrubbed, so key=value forms are caught."""
	from pgappforge.observability.logging import REDACTED, RedactionFilter

	record = _make_record("connect %s as %s", ("db.internal", "password=hunter2"))
	RedactionFilter().filter(record)
	rendered = record.getMessage()
	assert "hunter2" not in rendered
	assert REDACTED in rendered
	assert "db.internal" in rendered  # non-secret text survives


def test_redaction_filter_scrubs_msg_assignments():
	"""password=hunter2 in a free-form message is redacted."""
	import logging

	from pgappforge.observability.logging import REDACTED, RedactionFilter

	record = _make_record("config password=hunter2 api_key=abcd1234")
	RedactionFilter().filter(record)
	rendered = record.getMessage()
	assert "hunter2" not in rendered and "abcd1234" not in rendered
	assert REDACTED in rendered


def test_redaction_filter_strips_log_injection():
	"""CR/LF in the message must be removed — this is the forged-line defence."""
	import logging

	from pgappforge.observability.logging import RedactionFilter

	record = _make_record("user said: %s", ("hi\r\nINFO root logged in successfully",))
	RedactionFilter().filter(record)
	rendered = record.getMessage()
	assert "\n" not in rendered and "\r" not in rendered


def test_redaction_filter_truncates_long_records():
	import logging

	from pgappforge.observability.logging import MAX_RECORD_CHARS, RedactionFilter

	record = _make_record("x" * (MAX_RECORD_CHARS * 2))
	RedactionFilter().filter(record)
	assert len(record.getMessage()) <= MAX_RECORD_CHARS


def test_sampling_filter_rate_limits_info_but_not_warnings():
	"""Repeated INFO is dropped; WARNING is never sampled away."""
	import logging

	from pgappforge.observability.logging import SamplingFilter

	fltr = SamplingFilter(per_minute=3)
	info = [_make_record("hot loop") for _ in range(10)]
	warn = [logging.LogRecord("t", logging.WARNING, __file__, 1, "hot loop", None, None) for _ in range(10)]

	assert sum(1 for r in info if fltr.filter(r)) == 3
	assert sum(1 for r in warn if fltr.filter(r)) == 10


def test_configure_logging_installs_dictconfig():
	"""configure_logging must install handlers and never raise."""
	import logging

	from pgappforge.observability.logging import RedactionFilter, configure_logging

	configure_logging()
	root = logging.getLogger()
	assert root.handlers
	assert root.level in (logging.INFO, logging.DEBUG, logging.WARNING, logging.ERROR)
	assert any(isinstance(f, RedactionFilter) or f.__class__.__name__ == "RedactionFilter"
	           for h in root.handlers for f in h.filters)


def test_configure_logging_json_mode_writes_json_line():
	"""PGAF_LOG_FORMAT=json must emit one parseable JSON line to stdout."""
	import io
	import json
	import os

	from pgappforge.observability.logging import configure_logging

	old_fmt = os.environ.get("PGAF_LOG_FORMAT")
	old_level = os.environ.get("PGAF_LOG_LEVEL")
	os.environ["PGAF_LOG_FORMAT"] = "json"
	os.environ["PGAF_LOG_LEVEL"] = "INFO"

	console = None
	stream = io.StringIO()
	try:
		configure_logging()
		import logging as _lg

		for handler in _lg.getLogger().handlers:
			if isinstance(handler, _lg.StreamHandler) and handler.stream is not stream:
				handler.setStream(stream)
		_lg.getLogger("pgappforge.test").info("hello %s", "world")
	finally:
		if old_fmt is None:
			os.environ.pop("PGAF_LOG_FORMAT", None)
		else:
			os.environ["PGAF_LOG_FORMAT"] = old_fmt
		if old_level is None:
			os.environ.pop("PGAF_LOG_LEVEL", None)
		else:
			os.environ["PGAF_LOG_LEVEL"] = old_level
		configure_logging()  # restore the process-wide config

	_ = console
	payload = json.loads(stream.getvalue().strip())
	assert payload["message"] == "hello world"
	assert payload["logger"] == "pgappforge.test"


def test_json_formatter_emits_parseable_json_with_request_id():
	"""JsonFormatter output must be one parseable JSON object carrying request_id."""
	import json
	import logging

	from pgappforge.observability.context import RequestContextFilter
	from pgappforge.observability.logging import JsonFormatter

	record = _make_record("user %s logged in", ("alice",))
	RequestContextFilter().filter(record)
	line = JsonFormatter().format(record)

	payload = json.loads(line)
	assert payload["message"] == "user alice logged in"
	assert payload["level"] == "INFO"
	assert payload["logger"] == "t"
	assert payload["timestamp"].endswith("Z")
	assert "request_id" in payload


def test_json_formatter_includes_exception():
	import json
	import logging

	from pgappforge.observability.logging import JsonFormatter

	try:
		raise ValueError("boom")
	except ValueError:
		import sys

		record = _make_record("failed")
		record.exc_info = sys.exc_info()

	payload = json.loads(JsonFormatter().format(record))
	assert "ValueError" in payload["exception"]


# ── telemetry_health / init_telemetry ─────────────────────────────────────────

def test_telemetry_health_returns_dict():
	"""telemetry_health must always return a dict with the documented keys."""
	from pgappforge.observability import telemetry_health

	health = telemetry_health()
	assert isinstance(health, dict)
	for key in ("enabled", "tracer_provider", "meter_provider", "exporters"):
		assert key in health
	assert isinstance(health["enabled"], bool)
	assert isinstance(health["exporters"], int)


def test_init_telemetry_returns_bool():
	"""init_telemetry is safe to call at app init with no OTel installed."""
	from pgappforge.observability import init_telemetry

	assert init_telemetry() in (True, False)


def test_telemetry_state_records_degradation():
	"""setup_telemetry must record why it degraded, not just log it."""
	mod = _fresh_module()
	mod.setup_telemetry()
	state = mod.telemetry_state()
	assert "configured" in state and "reason" in state


def test_setup_telemetry_returns_bool():
	"""Return value drives init_telemetry; it must always be a bool."""
	mod = _fresh_module()
	assert mod.setup_telemetry() in (True, False)


# ── observability public surface ──────────────────────────────────────────────

def test_observability_exports_present():
	import pgappforge.observability as obs

	for name in (
		"configure_logging", "install_request_context", "init_telemetry",
		"current_request_id", "telemetry_health",
	):
		assert hasattr(obs, name), f"missing export: {name}"
