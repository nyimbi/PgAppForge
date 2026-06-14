"""PDL model inspector — introspect SQLAlchemy models from plugin registry."""
from __future__ import annotations

import importlib
import inspect
from typing import Any


_SA_TYPE_MAP: dict[str, str] = {
	"String": "string", "Text": "text", "Integer": "integer",
	"BigInteger": "integer", "Numeric": "decimal", "Float": "float",
	"Boolean": "boolean", "Date": "date", "DateTime": "datetime",
	"JSONB": "jsonb", "JSON": "jsonb",
}


def _sa_type_name(col: Any) -> str:
	t = col.type
	for name, pdl_type in _SA_TYPE_MAP.items():
		if type(t).__name__ == name:
			return pdl_type
	return "string"


def _inspect_model(model_cls: Any) -> dict[str, Any] | None:
	try:
		table = getattr(model_cls, "__table__", None)
		if table is None:
			return None
		fields = []
		for col in table.columns:
			if col.name in ("id", "tenant_id", "created_at", "updated_at"):
				continue
			fk_target = None
			if col.foreign_keys:
				fk = next(iter(col.foreign_keys))
				fk_target = fk.target_fullname
			fields.append({
				"name": col.name,
				"type": _sa_type_name(col),
				"nullable": col.nullable,
				"unique": bool(col.unique),
				"indexed": bool(col.index),
				"fk": fk_target,
				"label": col.name.replace("_", " ").title(),
				"max_length": getattr(col.type, "length", None),
			})
		return {
			"name": model_cls.__name__,
			"table": table.name,
			"description": (inspect.getdoc(model_cls) or "").split("\n")[0],
			"fields": fields,
		}
	except Exception:
		return None


_PLUGIN_ROOTS = [
	"pgappforge.plugins.erp.finance",
	"pgappforge.plugins.erp.grc",
	"pgappforge.plugins.erp.hcm",
	"pgappforge.plugins.erp.crm",
	"pgappforge.plugins.erp.operations",
	"pgappforge.plugins.erp.procurement",
	"pgappforge.plugins.erp.platform",
	"pgappforge.plugins.fintech",
]


def _discover_plugin_models() -> list[dict[str, Any]]:
	results: list[dict[str, Any]] = []
	for root in _PLUGIN_ROOTS:
		try:
			pkg = importlib.import_module(root)
		except ImportError:
			continue
		import pkgutil
		for _finder, subname, _ispkg in pkgutil.walk_packages(
			path=getattr(pkg, "__path__", []),
			prefix=root + ".",
			onerror=lambda _: None,
		):
			if not subname.endswith(".models"):
				continue
			try:
				mod = importlib.import_module(subname)
			except Exception:
				continue
			for attr_name in dir(mod):
				cls = getattr(mod, attr_name, None)
				if not inspect.isclass(cls) or not hasattr(cls, "__tablename__"):
					continue
				schema = _inspect_model(cls)
				if not schema:
					continue
				parts = subname.split(".")
				try:
					domain_idx = parts.index("erp") + 1 if "erp" in parts else parts.index("fintech")
					domain = parts[domain_idx] if domain_idx < len(parts) else "platform"
				except (ValueError, IndexError):
					domain = "platform"
				results.append({
					"domain": domain,
					"module": subname.rsplit(".models", 1)[0],
					"model": schema,
				})
	seen: set[str] = set()
	deduped = []
	for r in results:
		key = r["model"]["table"]
		if key not in seen:
			seen.add(key)
			deduped.append(r)
	return sorted(deduped, key=lambda r: (r["domain"], r["model"]["name"]))


def get_plugin_model_catalogue() -> dict[str, list[dict[str, Any]]]:
	"""Return {domain: [model_entry, ...]} for all discovered plugin models."""
	models = _discover_plugin_models()
	by_domain: dict[str, list[dict[str, Any]]] = {}
	for entry in models:
		by_domain.setdefault(entry["domain"], []).append(entry)
	return by_domain


__all__ = ["get_plugin_model_catalogue", "_inspect_model"]
