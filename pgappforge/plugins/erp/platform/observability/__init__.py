"""
pgappforge/plugins/erp/platform/observability/__init__.py

ObservabilityPlugin — OpenTelemetry instrumentation for PgAppForge.

Domain:    platform
Depends:   (none — zero hard dependencies)

This plugin provides zero-dependency OTEL tracing and metrics helpers.
When the opentelemetry-sdk package is installed, full distributed tracing
and metric recording are enabled. When absent, all decorators/helpers
are transparent no-ops so the rest of the framework is unaffected.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.platform.observability.instrumentation import (
	setup_otel,
	trace_service_call,
	record_metric,
)

log = logging.getLogger(__name__)


class ObservabilityPlugin(BasePlugin):
	"""OpenTelemetry Observability plugin.

	Provides setup_otel(), trace_service_call() decorator, and record_metric()
	helpers. All are transparent no-ops when the opentelemetry-sdk package
	is not installed, ensuring zero-impact on deployments that don't use OTEL.
	"""

	name = "observability"
	domain = "platform"
	depends_on: list[str] = []

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="observability",
			version="1.0.0",
			description=(
				"OpenTelemetry instrumentation — distributed tracing, metrics, "
				"OTLP export. Zero-dependency no-ops when SDK not installed."
			),
			author="PgAppForge Contributors",
			tags=["platform", "observability", "otel", "tracing", "metrics", "opentelemetry"],
			priority=PluginPriority.HIGH,
			permissions=[],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		service_name: str = self.config.get("OTEL_SERVICE_NAME", "pgappforge")
		otlp_endpoint: str | None = self.config.get("OTEL_EXPORTER_OTLP_ENDPOINT")

		configured = setup_otel(service_name, otlp_endpoint)
		if configured:
			log.info("ObservabilityPlugin: OTEL tracing active for service %r", service_name)
		else:
			log.info(
				"ObservabilityPlugin: OTEL SDK not installed — "
				"tracing/metrics disabled (install opentelemetry-sdk to enable)"
			)

	def register_models(self) -> list:
		return []

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.observability.views import TraceBrowserView
		cat = self.config.get("OBSERVABILITY_MENU_CATEGORY", "Platform")
		self.add_view(TraceBrowserView, "OTEL Trace Browser", icon="fa-search", category=cat)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ObservabilityPlugin:
	return ObservabilityPlugin(appbuilder, config=config or {})


__all__ = [
	"ObservabilityPlugin",
	"create_plugin",
	# Re-exported helpers for direct use: from pgappforge.plugins.erp.platform.observability import ...
	"setup_otel",
	"trace_service_call",
	"record_metric",
]
