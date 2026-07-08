"""
pgappforge/plugin_hot_reload.py

Plugin hot-reload — install, disable, and reload plugins at runtime without
restarting the Flask application.

Caveats
-------
* Flask blueprints cannot be *unregistered* once registered.  ``disable_plugin``
  removes the plugin from the dynamic registry and calls ``deactivate()`` on it,
  but the URL rules remain alive.  A full restart is required to purge routes.
* Plugins that require *new database tables* must run ``flask db upgrade`` before
  hot-installing.  The hot-reload mechanism only handles Python/view registration.
* This is deliberately not thread-safe for write operations.  Wrap
  ``install_plugin`` / ``disable_plugin`` in a distributed lock if you run
  multiple worker processes.

Admin HTTP API (registered via ``setup_hot_reload_api``)
---------------------------------------------------------
  POST /admin/plugins/install   body: {"module_path": "..."}
  POST /admin/plugins/disable   body: {"plugin_name": "..."}
  POST /admin/plugins/reload    body: {"module_path": "..."}
  GET  /admin/plugins/dynamic
"""
from __future__ import annotations

import importlib
import logging
import re
from collections.abc import Sequence
from typing import Any

log = logging.getLogger(__name__)

# Registry of dynamically loaded plugins (post-startup only).
# Keys are plugin names; values are plugin instances.
_dynamic_plugins: dict[str, Any] = {}

_MODULE_PATH_RE = re.compile(
	r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)
_DEFAULT_ADMIN_ALLOWED_PREFIXES = ("pgappforge.plugins.",)


# --------------------------------------------------------------------------- #
# Core operations                                                              #
# --------------------------------------------------------------------------- #

def install_plugin(
	plugin_module_path: str,
	appbuilder: Any,
	allowed_prefixes: Sequence[str] | None = None,
) -> tuple[bool, str]:
	"""Install a PgAppForge plugin at runtime without restarting.

	Works for plugins that:

	1. Only register views (FAB blueprints can be added at runtime).
	2. Don't require new database tables **or** those tables already exist.

	For plugins requiring DB migrations run ``flask db upgrade`` first, then
	call this function.

	Args:
		plugin_module_path: Dotted Python import path, e.g.
		                    ``"pgappforge.plugins.erp.platform.versioning"``.
		appbuilder:         PgAppForge ``AppBuilder`` instance.

	Returns:
		``(True, success_message)`` or ``(False, error_message)``.
	"""
	plugin_module_path = (plugin_module_path or "").strip()
	validation_error = _validate_module_path(plugin_module_path, allowed_prefixes)
	if validation_error:
		return False, validation_error

	try:
		mod = importlib.import_module(plugin_module_path)
	except Exception as exc:
		log.error("hot-install: import failed for %s — %s", plugin_module_path, exc)
		return False, f"Import failed: {exc}"

	# ── Resolve plugin instance ──────────────────────────────────────────────
	plugin: Any = None

	# 1. Prefer explicit create_plugin factory
	if hasattr(mod, "create_plugin") and callable(mod.create_plugin):
		try:
			plugin = mod.create_plugin(appbuilder)
		except Exception as exc:
			return False, f"create_plugin() failed: {exc}"

	# 2. Fall back: scan module for a BasePlugin subclass
	if plugin is None:
		from pgappforge.plugins.base_plugin import BasePlugin
		for attr_name in dir(mod):
			obj = getattr(mod, attr_name)
			if (
				isinstance(obj, type)
				and issubclass(obj, BasePlugin)
				and obj is not BasePlugin
			):
				try:
					plugin = obj(appbuilder)
					break
				except Exception as exc:
					return False, f"Instantiation of {attr_name} failed: {exc}"

	# 3. Legacy: any class with .activate() and .name
	if plugin is None:
		for attr_name in dir(mod):
			obj = getattr(mod, attr_name)
			if (
				isinstance(obj, type)
				and hasattr(obj, "activate")
				and hasattr(obj, "name")
				and obj is not object
			):
				try:
					plugin = obj(appbuilder)
					break
				except Exception as exc:
					return False, f"Instantiation of {attr_name} failed: {exc}"

	if plugin is None:
		return False, f"No plugin class found in {plugin_module_path}"

	validation_error = _validate_plugin_instance(plugin, plugin_module_path)
	if validation_error:
		return False, validation_error

	# ── Activate ─────────────────────────────────────────────────────────────
	try:
		result = plugin.activate()
		if result is False:
			return False, f"Plugin.activate() returned False for {plugin_module_path}"
	except Exception as exc:
		log.error("hot-install: activate() failed for %s — %s", plugin_module_path, exc)
		return False, f"Activate failed: {exc}"

	plugin_name: str = getattr(plugin, "name", plugin_module_path)
	_dynamic_plugins[plugin_name] = plugin

	msg = f"Plugin '{plugin_name}' installed successfully"
	log.info("hot-install: %s", msg)
	return True, msg


def _validate_module_path(
	module_path: str,
	allowed_prefixes: Sequence[str] | None = None,
) -> str | None:
	if not module_path:
		return "module_path is required"
	if len(module_path) > 500:
		return "Invalid module_path: path is too long"
	if not _MODULE_PATH_RE.fullmatch(module_path):
		return "Invalid module_path: use a dotted Python import path"
	if allowed_prefixes and not _matches_allowed_prefix(module_path, allowed_prefixes):
		allowed = ", ".join(allowed_prefixes)
		return f"Module path {module_path!r} is not in the allowed prefixes: {allowed}"
	return None


def _matches_allowed_prefix(module_path: str, allowed_prefixes: Sequence[str]) -> bool:
	for prefix in allowed_prefixes:
		normalized = (prefix or "").strip()
		if not normalized:
			continue
		if module_path == normalized.rstrip("."):
			return True
		if module_path.startswith(normalized):
			return True
	return False


def _validate_plugin_instance(plugin: Any, module_path: str) -> str | None:
	if not callable(getattr(plugin, "activate", None)):
		return f"Plugin from {module_path} must expose callable activate()"
	name = getattr(plugin, "name", None)
	metadata = getattr(plugin, "metadata", None)
	if name is None and metadata is not None:
		name = getattr(metadata, "name", None)
	if name is not None and not str(name).strip():
		return f"Plugin from {module_path} has an empty name"
	return None


def disable_plugin(plugin_name: str, appbuilder: Any) -> tuple[bool, str]:
	"""Disable a dynamically-installed plugin.

	Calls ``plugin.deactivate()`` if available, removes it from the dynamic
	registry, and logs the action.

	Note: Flask blueprint URL rules persist until the next restart.

	Args:
		plugin_name: The ``plugin.name`` value used as the registry key.
		appbuilder:  PgAppForge ``AppBuilder`` instance (unused, kept for API symmetry).

	Returns:
		``(True, message)`` or ``(False, error_message)``.
	"""
	if plugin_name not in _dynamic_plugins:
		return False, f"Plugin '{plugin_name}' not found in dynamic registry"

	plugin = _dynamic_plugins.pop(plugin_name)

	try:
		if hasattr(plugin, "deactivate") and callable(plugin.deactivate):
			plugin.deactivate()
	except Exception as exc:
		# Non-fatal: log and continue
		log.warning("disable_plugin: deactivate() raised for %s — %s", plugin_name, exc)

	msg = f"Plugin '{plugin_name}' disabled (restart to fully remove routes)"
	log.info("hot-reload: %s", msg)
	return True, msg


def reload_plugin(
	plugin_module_path: str,
	appbuilder: Any,
	allowed_prefixes: Sequence[str] | None = None,
) -> tuple[bool, str]:
	"""Reload a plugin's Python module (re-reads .py files from disk).

	Useful after updating a plugin's service/business-logic layer.
	Existing blueprint URL rules are **not** re-registered; this only
	refreshes the in-process module object so subsequent service calls
	pick up code changes.

	Args:
		plugin_module_path: Dotted Python import path.
		appbuilder:         PgAppForge ``AppBuilder`` instance.

	Returns:
		``(True, message)`` or ``(False, error_message)``.
	"""
	plugin_module_path = (plugin_module_path or "").strip()
	validation_error = _validate_module_path(plugin_module_path, allowed_prefixes)
	if validation_error:
		return False, validation_error

	try:
		mod = importlib.import_module(plugin_module_path)
		importlib.reload(mod)
		msg = f"Module {plugin_module_path} reloaded"
		log.info("hot-reload: %s", msg)
		return True, msg
	except Exception as exc:
		log.error("hot-reload: reload failed for %s — %s", plugin_module_path, exc)
		return False, f"Reload failed: {exc}"


def list_dynamic_plugins() -> list[dict[str, str]]:
	"""Return summary dicts for all dynamically installed plugins.

	Returns::

	    [
	        {
	            "name":         str,
	            "module":       str,   # Python module path
	            "domain":       str,   # plugin domain (or "unknown")
	            "installed_at": "runtime",
	        },
	        ...
	    ]
	"""
	return [
		{
			"name": getattr(plugin, "name", key),
			"module": type(plugin).__module__,
			"domain": getattr(plugin, "domain", "unknown"),
			"installed_at": "runtime",
		}
		for key, plugin in _dynamic_plugins.items()
	]


# --------------------------------------------------------------------------- #
# HTTP API                                                                     #
# --------------------------------------------------------------------------- #

def setup_hot_reload_api(app, appbuilder: Any) -> None:
	"""Register admin-only REST endpoints for hot-reload management.

	All endpoints require an authenticated session with FAB ``has_access``
	protection.  Wire this in your app factory *after* AppBuilder is fully
	initialised::

	    from pgappforge.plugin_hot_reload import setup_hot_reload_api
	    setup_hot_reload_api(app, appbuilder)

	Endpoints
	---------
	  POST /admin/plugins/install   {"module_path": "..."}
	  POST /admin/plugins/disable   {"plugin_name": "..."}
	  POST /admin/plugins/reload    {"module_path": "..."}
	  GET  /admin/plugins/dynamic
	"""
	from flask import jsonify, request
	from pgappforge.security.decorators import has_access

	@app.route("/admin/plugins/install", methods=["POST"])
	@has_access
	def _admin_plugin_install():
		data = request.get_json(silent=True) or {}
		module_path = (data.get("module_path") or "").strip()
		if not module_path:
			return jsonify({"success": False, "message": "module_path is required"}), 400
		allowed_prefixes = app.config.get(
			"PGAPPFORGE_HOT_RELOAD_ALLOWED_PREFIXES",
			_DEFAULT_ADMIN_ALLOWED_PREFIXES,
		)
		success, message = install_plugin(
			module_path,
			appbuilder,
			allowed_prefixes=allowed_prefixes,
		)
		status = 200 if success else 500
		return jsonify({"success": success, "message": message}), status

	@app.route("/admin/plugins/disable", methods=["POST"])
	@has_access
	def _admin_plugin_disable():
		data = request.get_json(silent=True) or {}
		plugin_name = (data.get("plugin_name") or "").strip()
		if not plugin_name:
			return jsonify({"success": False, "message": "plugin_name is required"}), 400
		success, message = disable_plugin(plugin_name, appbuilder)
		status = 200 if success else 400
		return jsonify({"success": success, "message": message}), status

	@app.route("/admin/plugins/reload", methods=["POST"])
	@has_access
	def _admin_plugin_reload():
		data = request.get_json(silent=True) or {}
		module_path = (data.get("module_path") or "").strip()
		if not module_path:
			return jsonify({"success": False, "message": "module_path is required"}), 400
		allowed_prefixes = app.config.get(
			"PGAPPFORGE_HOT_RELOAD_ALLOWED_PREFIXES",
			_DEFAULT_ADMIN_ALLOWED_PREFIXES,
		)
		success, message = reload_plugin(
			module_path,
			appbuilder,
			allowed_prefixes=allowed_prefixes,
		)
		status = 200 if success else 500
		return jsonify({"success": success, "message": message}), status

	@app.route("/admin/plugins/dynamic", methods=["GET"])
	@has_access
	def _admin_plugin_list():
		return jsonify({"plugins": list_dynamic_plugins()})

	log.info("Plugin hot-reload API registered at /admin/plugins/")


__all__ = [
	"install_plugin",
	"disable_plugin",
	"reload_plugin",
	"list_dynamic_plugins",
	"setup_hot_reload_api",
]
