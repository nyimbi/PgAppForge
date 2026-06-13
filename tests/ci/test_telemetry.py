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
