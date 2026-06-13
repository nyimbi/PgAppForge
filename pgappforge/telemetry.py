"""OpenTelemetry auto-instrumentation for PgAppForge.

Gracefully degrades if opentelemetry packages are absent — import this
module unconditionally; it will no-op when deps are missing.

Quickstart::

    from pgappforge.telemetry import setup_telemetry
    app = create_app()
    setup_telemetry(app, db.engine, exporter_endpoint="http://jaeger:4317")

Flask config keys (all optional):
    OTEL_ENABLED              bool   default True
    OTEL_EXPORTER_ENDPOINT    str    e.g. "http://jaeger:4317"
    OTEL_EXPORTER_TYPE        str    "otlp" | "console" | "none"
    OTEL_SERVICE_NAME         str    default "pgappforge"
    OTEL_SERVICE_VERSION      str    default "4.8.0"
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any

log = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def setup_telemetry(
	app=None,
	engine=None,
	*,
	service_name: str = "pgappforge",
	service_version: str = "4.8.0",
	exporter_endpoint: str | None = None,
	exporter_type: str = "otlp",
) -> None:
	"""Set up OpenTelemetry instrumentation for PgAppForge.

	Call once in your app factory after creating the Flask app and SQLAlchemy
	engine.  Gracefully degrades when opentelemetry packages are not installed.

	Args:
		app:               Flask application instance (optional but recommended).
		engine:            SQLAlchemy engine to instrument (optional).
		service_name:      OTel service.name resource attribute.
		service_version:   OTel service.version resource attribute.
		exporter_endpoint: OTLP collector endpoint, e.g. ``"http://jaeger:4317"``.
		                   Overridden by ``OTEL_EXPORTER_ENDPOINT`` in app.config.
		exporter_type:     ``"otlp"`` | ``"console"`` | ``"none"``.
	"""
	try:
		from opentelemetry import trace, metrics  # noqa: F401
		from opentelemetry.sdk.trace import TracerProvider
		from opentelemetry.sdk.trace.export import (
			BatchSpanProcessor,
			ConsoleSpanExporter,
		)
		from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
	except ImportError:
		log.info(
			"opentelemetry not installed — telemetry disabled. "
			"pip install opentelemetry-sdk opentelemetry-instrumentation-flask "
			"opentelemetry-instrumentation-sqlalchemy"
		)
		return

	# ── Resolve config from Flask app ────────────────────────────────────────
	if app is not None:
		cfg = app.config
		if not cfg.get("OTEL_ENABLED", True):
			log.debug("OTel: disabled via OTEL_ENABLED=False")
			return
		exporter_endpoint = exporter_endpoint or cfg.get("OTEL_EXPORTER_ENDPOINT")
		exporter_type = cfg.get("OTEL_EXPORTER_TYPE", exporter_type)
		service_name = cfg.get("OTEL_SERVICE_NAME", service_name)
		service_version = cfg.get("OTEL_SERVICE_VERSION", service_version)

	# ── Resource ─────────────────────────────────────────────────────────────
	resource = Resource.create({
		SERVICE_NAME: service_name,
		SERVICE_VERSION: service_version,
	})

	# ── Tracer provider ───────────────────────────────────────────────────────
	provider = TracerProvider(resource=resource)

	if exporter_type == "none":
		log.info("OTel: exporter_type='none' — traces collected but not exported")
	elif exporter_endpoint and exporter_type == "otlp":
		try:
			from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
			provider.add_span_processor(
				BatchSpanProcessor(OTLPSpanExporter(endpoint=exporter_endpoint))
			)
			log.info("OTel: OTLP trace exporter → %s", exporter_endpoint)
		except ImportError:
			log.warning(
				"OTel: opentelemetry-exporter-otlp-proto-grpc not installed; "
				"pip install opentelemetry-exporter-otlp-proto-grpc"
			)
	elif exporter_type == "console":
		provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
		log.info("OTel: Console trace exporter enabled")
	else:
		log.debug("OTel: no exporter configured (exporter_type=%r)", exporter_type)

	trace.set_tracer_provider(provider)

	# ── Instrument Flask ──────────────────────────────────────────────────────
	if app is not None:
		try:
			from opentelemetry.instrumentation.flask import FlaskInstrumentor
			FlaskInstrumentor().instrument_app(app)
			log.info("OTel: Flask instrumented")
		except ImportError:
			log.debug(
				"opentelemetry-instrumentation-flask not installed; "
				"pip install opentelemetry-instrumentation-flask"
			)

	# ── Instrument SQLAlchemy ─────────────────────────────────────────────────
	if engine is not None:
		try:
			from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
			SQLAlchemyInstrumentor().instrument(engine=engine)
			log.info("OTel: SQLAlchemy instrumented")
		except ImportError:
			log.debug(
				"opentelemetry-instrumentation-sqlalchemy not installed; "
				"pip install opentelemetry-instrumentation-sqlalchemy"
			)

	# ── Metrics provider (best-effort) ────────────────────────────────────────
	_setup_metrics(exporter_endpoint, exporter_type, resource)

	log.info("OTel: telemetry setup complete for service '%s' v%s", service_name, service_version)


def trace_view(operation_name: str | None = None):
	"""Decorator that wraps a PgAppForge view method in a custom OTel span.

	Silently falls back to the bare function when OTel is unavailable or the
	tracer provider is the no-op default.

	Usage::

		@expose("/invoices")
		@trace_view("invoice.list")
		def list_invoices(self):
			...
	"""
	def decorator(fn):
		@wraps(fn)
		def wrapper(*args, **kwargs):
			try:
				from opentelemetry import trace
				tracer = trace.get_tracer("pgappforge")
				span_name = operation_name or fn.__qualname__
				with tracer.start_as_current_span(span_name) as span:
					span.set_attribute("pgappforge.view", fn.__qualname__)
					span.set_attribute("code.function", fn.__name__)
					return fn(*args, **kwargs)
			except Exception:
				# Never let telemetry break the application
				return fn(*args, **kwargs)
		return wrapper
	return decorator


def record_business_metric(
	name: str,
	value: float = 1.0,
	attributes: dict[str, Any] | None = None,
) -> None:
	"""Record a custom business metric counter.

	Silently no-ops if OTel metrics are unavailable.

	Args:
		name:       Metric name, e.g. ``"loan.disbursed"`` or ``"invoice.created"``.
		value:      Numeric value to add (default 1.0).
		attributes: Optional label dict, e.g. ``{"currency": "KES", "branch": "NBI"}``.

	Usage::

		record_business_metric("loan.disbursed", amount_cents, {"currency": "KES"})
		record_business_metric("invoice.created")
	"""
	try:
		from opentelemetry import metrics
		meter = metrics.get_meter("pgappforge.business")
		counter = meter.create_counter(
			name,
			description=f"PgAppForge business metric: {name}",
		)
		counter.add(value, attributes or {})
	except Exception:
		pass


# ── Internal helpers ──────────────────────────────────────────────────────────

def _setup_metrics(
	exporter_endpoint: str | None,
	exporter_type: str,
	resource,
) -> None:
	"""Configure the OTel MeterProvider (best-effort, non-fatal)."""
	try:
		from opentelemetry import metrics
		from opentelemetry.sdk.metrics import MeterProvider
		from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

		readers = []
		if exporter_endpoint and exporter_type == "otlp":
			try:
				from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
					OTLPMetricExporter,
				)
				readers.append(
					PeriodicExportingMetricReader(
						OTLPMetricExporter(endpoint=exporter_endpoint),
						export_interval_millis=30_000,
					)
				)
			except ImportError:
				pass
		elif exporter_type == "console":
			try:
				from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
				readers.append(
					PeriodicExportingMetricReader(
						ConsoleMetricExporter(),
						export_interval_millis=60_000,
					)
				)
			except ImportError:
				pass

		meter_provider = MeterProvider(resource=resource, metric_readers=readers)
		metrics.set_meter_provider(meter_provider)
		log.debug("OTel: MeterProvider configured")
	except Exception as exc:
		log.debug("OTel: metrics setup skipped: %s", exc)


__all__ = [
	"setup_telemetry",
	"trace_view",
	"record_business_metric",
]
