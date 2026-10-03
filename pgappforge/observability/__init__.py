"""Observability entry points for PgAppForge — logging, request context, telemetry.

Import from here rather than from the submodules so that the optional
OpenTelemetry dependency stays contained::

	from pgappforge.observability import configure_logging, telemetry_health

Every import in this package is guarded; the package loads cleanly whether or
not ``opentelemetry`` is installed.
"""
from __future__ import annotations

# NOTE: this package contains a submodule named `logging`. Import the stdlib
# under an alias, otherwise the `from .logging import ...` below rebinds the
# name to the submodule and every later `logging.getLogger` blows up.
import logging as _stdlib_logging
from typing import Any

from .context import (
	CONTEXT_FIELDS,
	RequestContextFilter,
	current_request_id,
	install_request_context,
)
from .logging import (
	JsonFormatter,
	HumanFormatter,
	RedactionFilter,
	SamplingFilter,
	configure_logging,
)

log = _stdlib_logging.getLogger(__name__)

__all__ = [
	"CONTEXT_FIELDS",
	"RequestContextFilter",
	"JsonFormatter",
	"HumanFormatter",
	"RedactionFilter",
	"SamplingFilter",
	"configure_logging",
	"current_request_id",
	"init_telemetry",
	"install_request_context",
	"telemetry_health",
]


def init_telemetry(app: Any = None, engine: Any = None) -> bool:
	"""Wire OpenTelemetry into this process; never raises.

	Called from ``AppBuilder.init_app`` so that setting ``OTEL_ENABLED=true`` in
	the environment actually does something — previously ``setup_telemetry`` had
	no non-test caller, so the compose file's OTEL settings were inert.

	Args:
		app:    Flask application (config keys ``OTEL_*`` are read from it).
		engine: SQLAlchemy engine to instrument.

	Returns:
		True when telemetry is active, False when it degraded to a no-op.
	"""
	try:
		from pgappforge.telemetry import setup_telemetry
		return bool(setup_telemetry(app, engine))
	except Exception as exc:  # pragma: no cover - setup_telemetry is defensive
		log.warning("Telemetry setup failed (continuing without traces): %s", exc)
		return False


def telemetry_health() -> dict[str, Any]:
	"""Report the state of the installed OpenTelemetry SDK.

	Returns a dict with ``enabled``, ``tracer_provider``, ``meter_provider`` and
	``exporters``.  When the SDK is absent, or only the no-op API providers are
	installed, the provider names say so (``ProxyTracerProvider``,
	``_ProxyMeterProvider``, ``<unavailable>``) rather than claiming health.
	"""
	health: dict[str, Any] = {
		"enabled": False,
		"tracer_provider": "<unavailable>",
		"meter_provider": "<unavailable>",
		"exporters": 0,
	}
	try:
		from opentelemetry import metrics, trace
	except ImportError:
		health["reason"] = "opentelemetry not installed"
		return health

	try:
		tracer_provider = trace.get_tracer_provider()
		meter_provider = metrics.get_meter_provider()
	except Exception as exc:  # pragma: no cover - defensive
		health["reason"] = f"provider lookup failed: {exc}"
		return health

	health["tracer_provider"] = type(tracer_provider).__name__
	health["meter_provider"] = type(meter_provider).__name__

	# "No-op" is spelled differently per provider generation; check for the
	# marker methods rather than the class name.
	noop_trace = (
		type(tracer_provider).__name__.startswith("Proxy")
		or hasattr(tracer_provider, "force_flush") is False
	)
	noop_metrics = type(meter_provider).__name__.startswith("_Proxy")
	health["enabled"] = not (noop_trace and noop_metrics)

	exporters = 0
	try:
		processors = getattr(tracer_provider, "_active_span_processor", None)
		if processors is not None:
			exporters = sum(
				1
				for p in processors._span_processors  # type: ignore[union-attr]
				if getattr(p, "span_exporter", None) is not None
			)
	except Exception:
		pass
	try:
		readers = getattr(meter_provider, "_sdk_config", None)
		if readers is not None:
			exporters += len(getattr(readers, "metric_readers", ()) or ())
	except Exception:
		pass
	health["exporters"] = exporters
	return health
