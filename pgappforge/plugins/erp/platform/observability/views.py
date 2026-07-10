"""
pgappforge/plugins/erp/platform/observability/views.py

Trace browser views for the OpenTelemetry observability plugin.
"""
from __future__ import annotations

import importlib
import logging

import sqlalchemy as sa
from flask import render_template_string, request
from markupsafe import Markup, escape
from pgappforge import expose
from pgappforge.security.decorators import has_access

try:
	from pgappforge.plugins.erp.base import BaseERPView
except ImportError:  # pragma: no cover - compatibility for current package layout
	from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class TraceBrowserView(BaseERPView):
	"""Browse local TraceRecord rows when present, otherwise show OTLP guidance."""

	route_base = "/platform/observability/traces"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		trace_model = self._trace_record_model()
		service_name = (request.args.get("service_name") or "").strip()
		if trace_model is None:
			content_html = self._backend_guidance()
		else:
			try:
				content_html = self._trace_table(trace_model, service_name)
			except Exception as exc:
				log.exception("TraceBrowserView.index: failed to load traces")
				content_html = Markup(
					f"<div class='alert alert-warning'>Trace records could not be loaded: {escape(exc)}</div>"
				)
		return render_template_string(
			_TRACE_BROWSER_TEMPLATE,
			content_html=content_html,
			service_name=service_name,
			appbuilder=self.appbuilder,
		)

	@staticmethod
	def _trace_record_model():
		for module_name in (
			"pgappforge.plugins.erp.platform.observability.models",
			"pgappforge.plugins.observability.models",
			"pgappforge.observability.models",
		):
			try:
				module = importlib.import_module(module_name)
			except ImportError:
				continue
			model = getattr(module, "TraceRecord", None)
			if model is not None:
				return model
		return None

	def _trace_table(self, trace_model, service_name: str) -> Markup:
		session = self._session()
		stmt = sa.select(trace_model)
		if service_name and hasattr(trace_model, "service_name"):
			stmt = stmt.where(getattr(trace_model, "service_name") == service_name)
		if hasattr(trace_model, "start_time"):
			stmt = stmt.order_by(getattr(trace_model, "start_time").desc())
		stmt = stmt.limit(50)
		traces = list(session.execute(stmt).scalars())
		rows: list[str] = []
		for trace in traces:
			rows.append(
				"<tr>"
				f"<td><code>{escape(self._value(trace, 'trace_id'))}</code></td>"
				f"<td>{escape(self._value(trace, 'service_name'))}</td>"
				f"<td>{escape(self._value(trace, 'span_count'))}</td>"
				f"<td>{escape(self._value(trace, 'duration_ms'))}</td>"
				f"<td>{escape(self._format_dt(getattr(trace, 'start_time', None)))}</td>"
				f"<td>{self._status_badge(self._value(trace, 'status'))}</td>"
				"</tr>"
			)
		if not rows:
			rows.append("<tr><td colspan='6' class='text-center text-muted'>No traces found.</td></tr>")
		filter_note = f"<p class='text-muted'>Filtered by service: {escape(service_name)}</p>" if service_name else ""
		return Markup(
			f"{filter_note}"
			"<div class='table-responsive'>"
			"<table class='table table-striped table-condensed'>"
			"<thead><tr><th>Trace ID</th><th>Service</th><th>Spans</th><th>Duration ms</th><th>Start Time</th><th>Status</th></tr></thead>"
			f"<tbody>{''.join(rows)}</tbody>"
			"</table></div>"
		)

	@staticmethod
	def _backend_guidance() -> Markup:
		return Markup(
			"<div class='alert alert-info'>"
			"<strong>OTEL traces are exported via OTLP - connect a Jaeger or Tempo backend.</strong>"
			"<p style='margin-top:8px;margin-bottom:0;'>Set <code>OTEL_SERVICE_NAME=pgappforge</code> and "
			"<code>OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces</code>, then point the endpoint "
			"at Jaeger, Grafana Tempo, or another OTLP-compatible collector.</p>"
			"</div>"
		)

	@staticmethod
	def _value(obj, attr: str) -> str:
		value = getattr(obj, attr, "")
		if value is None:
			return ""
		return str(value)

	@staticmethod
	def _format_dt(value) -> str:
		if value is None:
			return ""
		if hasattr(value, "strftime"):
			return value.strftime("%Y-%m-%d %H:%M:%S")
		return str(value)

	@staticmethod
	def _status_badge(status: str) -> Markup:
		status_text = status or "unknown"
		color = "#0e9f6e" if status_text.upper() in {"OK", "SUCCESS", "UNSET"} else "#9e1c00"
		return Markup(
			f"<span style='display:inline-block;border-radius:999px;padding:2px 9px;"
			f"font-size:11px;font-weight:700;color:#fff;background:{color};'>{escape(status_text)}</span>"
		)


_TRACE_BROWSER_TEMPLATE = """
{% extends "appbuilder/erp/base_erp.html" %}
{% block title %}OTEL Trace Browser - {{ appbuilder.app_name }}{% endblock %}
{% block page_header %}
<div class="erp-page-header">
	<h1 class="erp-page-title">OTEL Trace Browser</h1>
	<p class="erp-page-subtitle">Last 50 local traces or OTLP backend configuration guidance</p>
</div>
{% endblock %}
{% block content %}
<div class="erp-island">
	<form method="get" style="display:flex;gap:8px;align-items:end;flex-wrap:wrap;margin-bottom:16px;">
		<div>
			<label for="service_name" style="display:block;font-size:12px;color:var(--erp-text-muted);">Service Name</label>
			<input class="form-control" id="service_name" name="service_name" value="{{ service_name }}" placeholder="pgappforge">
		</div>
		<button class="btn btn-primary" type="submit"><i class="fa fa-filter"></i> Filter</button>
	</form>
	{{ content_html | safe }}
</div>
{% endblock %}
"""


__all__ = ["TraceBrowserView"]
