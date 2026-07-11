"""Platform system settings and API documentation views."""
from __future__ import annotations

from typing import Any

from flask import current_app

from pgappforge.baseviews import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access


def _display_value(value: Any) -> str:
	if isinstance(value, (list, tuple, set)):
		return ", ".join(str(item) for item in value)
	if isinstance(value, dict):
		return ", ".join(f"{key}={val}" for key, val in value.items())
	if value is None:
		return ""
	return str(value)


def _masked_db_uri(uri: Any) -> str:
	if not uri:
		return ""
	value = str(uri)
	return f"{'*' * 10}{value[-10:]}"


class SystemSettingsView(BaseERPView):
	"""Read-only app configuration settings."""

	route_base = "/erp/system/settings"
	default_view = "index"

	@expose("")
	@expose("/")
	@has_access
	def index(self):
		config = current_app.config
		rows = [
			{"key": "APP_NAME", "value": _display_value(config.get("APP_NAME"))},
			{"key": "APP_THEME", "value": _display_value(config.get("APP_THEME"))},
			{
				"key": "FAB_UPDATE_PERMS",
				"value": _display_value(
					config.get("FAB_UPDATE_PERMS", config.get("PGAF_UPDATE_PERMS"))
				),
			},
			{
				"key": "SQLALCHEMY_DATABASE_URI",
				"value": _masked_db_uri(config.get("SQLALCHEMY_DATABASE_URI")),
			},
			{
				"key": "ERP_PLUGINS_ENABLED",
				"value": _display_value(config.get("ERP_PLUGINS_ENABLED")),
			},
		]
		return self.render_template(
			"appbuilder/platform/system_page.html",
			title="System Settings",
			settings_rows=rows,
		)


class APIDocsView(BaseERPView):
	"""ERP API documentation landing page."""

	route_base = "/erp/api-docs"
	default_view = "index"

	@expose("")
	@expose("/")
	@has_access
	def index(self):
		return self.render_template(
			"appbuilder/platform/system_page.html",
			title="API Documentation",
			api_links=[
				{"label": "OpenAPI JSON", "href": "/api/v1/_openapi_json"},
				{"label": "Swagger UI", "href": "/swaggerui"},
			],
			api_groups=["Finance", "HCM", "Procurement", "CRM", "Projects", "GRC"],
		)


__all__ = ["APIDocsView", "SystemSettingsView"]
