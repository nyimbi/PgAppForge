"""
pgappforge/plugins/erp/platform/observability/instrumentation.py

OpenTelemetry instrumentation for PgAppForge.
Zero deps if opentelemetry not installed — all imports are guarded.
"""
from __future__ import annotations

import functools
import logging
from typing import Any

log = logging.getLogger(__name__)


def setup_otel(service_name: str, otlp_endpoint: str | None = None) -> bool:
	"""Initialize OpenTelemetry SDK.

	Returns True if configured, False if SDK not installed.

	Args:
	    service_name:    OTEL service.name resource attribute.
	    otlp_endpoint:   Optional OTLP/HTTP exporter endpoint, e.g.
	                     "http://localhost:4318/v1/traces". If None, no
	                     exporter is added (spans are created but not exported).
	"""
	try:
		from opentelemetry import trace
		from opentelemetry.sdk.trace import TracerProvider
		from opentelemetry.sdk.trace.export import BatchSpanProcessor
		from opentelemetry.sdk.resources import SERVICE_NAME, Resource

		provider = TracerProvider(
			resource=Resource.create({SERVICE_NAME: service_name})
		)
		if otlp_endpoint:
			from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
			provider.add_span_processor(
				BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
			)
		trace.set_tracer_provider(provider)
		log.info("OpenTelemetry initialized for service %r", service_name)
		return True
	except ImportError:
		log.debug(
			"opentelemetry-sdk not installed — tracing disabled. "
			"pip install opentelemetry-sdk opentelemetry-exporter-otlp"
		)
		return False


def trace_service_call(service_name: str = "", method_name: str = "") -> Any:
	"""Decorator: wrap a service method with an OTEL span.

	No-op (passes through) if OTEL SDK is not installed.

	Usage::

	    @trace_service_call(service_name="pgappforge.gl", method_name="post_journal")
	    def post_journal(self, ...):
	        ...
	"""
	def decorator(func: Any) -> Any:
		@functools.wraps(func)
		def wrapper(*args: Any, **kwargs: Any) -> Any:
			try:
				from opentelemetry import trace
				tracer = trace.get_tracer(service_name or func.__module__)
				span_name = method_name or func.__qualname__
				with tracer.start_as_current_span(span_name) as span:
					span.set_attribute("service", service_name or func.__module__)
					span.set_attribute("method", func.__qualname__)
					return func(*args, **kwargs)
			except ImportError:
				return func(*args, **kwargs)
		return wrapper
	return decorator


def record_metric(
	name: str,
	value: float,
	attributes: dict[str, Any] | None = None,
) -> None:
	"""Record a counter metric via OTEL Metrics API.

	Silent no-op if opentelemetry is not installed or meter is not configured.

	Args:
	    name:        Metric name, e.g. "pgappforge.api.requests".
	    value:       Counter increment value (must be non-negative for counters).
	    attributes:  Optional dict of OTEL metric attributes/labels.
	"""
	try:
		from opentelemetry import metrics
		meter = metrics.get_meter("pgappforge")
		counter = meter.create_counter(name)
		counter.add(value, attributes or {})
	except (ImportError, Exception):
		pass


__all__ = ["setup_otel", "trace_service_call", "record_metric"]
