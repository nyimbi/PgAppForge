"""Application health endpoint registration."""
from __future__ import annotations

from typing import Any

from flask import jsonify
from sqlalchemy import text


def _as_list(value: Any) -> list[Any]:
	if value is None:
		return []
	if isinstance(value, (list, tuple, set)):
		return list(value)
	if isinstance(value, str):
		return [item.strip() for item in value.split(",") if item.strip()]
	return [value]


def _db_session(db: Any) -> Any:
	return getattr(db, "session", db)


def _check_database(db: Any) -> dict[str, Any]:
	try:
		session = _db_session(db)
		if session is None:
			raise RuntimeError("No database session configured")
		session.execute(text("SELECT 1")).scalar()
		return {"status": "ok", "detail": "SELECT 1 succeeded"}
	except Exception as exc:  # pragma: no cover - exercised by deployment wiring
		return {"status": "degraded", "detail": str(exc)}


def _erp_plugin_details(app: Any) -> dict[str, Any]:
	appbuilder = app.extensions.get("appbuilder") if hasattr(app, "extensions") else None
	appbuilder = appbuilder or getattr(app, "appbuilder", None)
	plugin_manager = getattr(appbuilder, "plugin_manager", None)

	if plugin_manager is not None:
		try:
			plugins = plugin_manager.list_plugins()
			erp_plugins = []
			for plugin in plugins:
				name = plugin.get("name", "")
				metadata = getattr(plugin_manager.registry, "get_metadata", lambda _: None)(name)
				tags = getattr(metadata, "tags", []) if metadata is not None else []
				if name.startswith("erp.") or "erp" in tags:
					erp_plugins.append(plugin)
			if erp_plugins:
				return {
					"status": "ok",
					"source": "plugin_manager",
					"registered": len(erp_plugins),
					"active": sum(
						1 for plugin in erp_plugins
						if plugin.get("status") in {"active", "loaded"}
					),
				}
		except Exception as exc:
			return {"status": "unknown", "source": "plugin_manager", "detail": str(exc)}

	enabled = _as_list(app.config.get("ERP_PLUGINS_ENABLED"))
	if enabled:
		return {
			"status": "ok",
			"source": "ERP_PLUGINS_ENABLED",
			"registered": len(enabled),
			"enabled": enabled,
		}

	try:
		from pgappforge.plugins.erp import list_plugins

		registered = list_plugins()
		return {
			"status": "ok",
			"source": "erp_registry",
			"registered": len(registered),
		}
	except Exception as exc:  # pragma: no cover - defensive fallback
		return {"status": "unknown", "source": "erp_registry", "detail": str(exc)}


def register_health_check(app: Any, db: Any) -> None:
	"""Register the unauthenticated ``/health`` endpoint once per Flask app."""
	if "health" in app.view_functions:
		return

	@app.route("/health", methods=["GET"], endpoint="health")
	def health() -> Any:
		database = _check_database(db)
		erp_plugins = _erp_plugin_details(app)
		healthy = database["status"] == "ok"
		status_code = 200 if healthy else 503
		payload = {
			"status": "ok" if healthy else "degraded",
			"components": {
				"database": database,
				"erp_plugins": erp_plugins,
			},
		}
		return jsonify(payload), status_code
