"""
Template Registry for pgappforge.

Manages schema templates from three sources:
1. Bundled templates (shipped with pgappforge, in pgappforge/templates/bundled/)
2. User-installed templates (~/.pgappforge/templates/)
3. Project-local templates (.pgappforge/templates/ in the current project)

Templates are JSON files with a standard format describing tables, columns,
and relationships that map directly to pgappforge ERD Designer modules and
the schema manager's apply_changes() format.

Template JSON format::

    {
      "name": "fhir-r4",
      "label": "HL7 FHIR R4",
      "description": "Healthcare resources — Patient, Encounter, Observation",
      "color": "#3498db",
      "icon": "fa-heartbeat",
      "version": "4.0.1",
      "source_url": "https://hl7.org/fhir/R4/",
      "tags": ["healthcare", "hl7", "regulation"],
      "tables": {
        "patient": [
          {"name": "id", "type": "UUID", "pk": true},
          {"name": "family_name", "type": "VARCHAR(100)"},
          ...
        ]
      }
    }
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Directory locations (in priority order — last wins on conflicts)
_BUNDLED_DIR = Path(__file__).parent / "bundled"
_USER_DIR = Path.home() / ".pgappforge" / "templates"
_PROJECT_DIR = Path.cwd() / ".pgappforge" / "templates"


class TemplateNotFoundError(Exception):
	"""Raised when a requested template does not exist."""


class TemplateRegistry:
	"""Registry of all available pgappforge schema templates.

	Scans bundled, user-installed, and project-local template directories.
	Templates are lazy-loaded — only read from disk when accessed.

	Usage::

	    registry = TemplateRegistry()

	    # List all available templates
	    for t in registry.list():
	        print(t['name'], t['label'], len(t['tables']), 'tables')

	    # Get a specific template
	    fhir = registry.get('fhir-r4')
	    print(fhir['tables'].keys())

	    # Load all as ERD Designer module format (compatible with ERP_MODULES)
	    modules = registry.load_all()  # {name: {label, color, tables, ...}}

	    # Install a new template from a URL or local file
	    registry.install_from_file('/path/to/my-template.json')

	    # Remove a user-installed template
	    registry.remove('my-template')
	"""

	def __init__(self) -> None:
		self._cache: dict[str, dict] = {}
		self._scan_done = False

	def _scan_dirs(self) -> None:
		"""Scan all template directories and populate the cache."""
		if self._scan_done:
			return
		for directory in [_BUNDLED_DIR, _USER_DIR, _PROJECT_DIR]:
			if not directory.exists():
				continue
			for path in sorted(directory.glob("*.json")):
				try:
					data = json.loads(path.read_text(encoding="utf-8"))
					name = data.get("name") or path.stem
					self._cache[name] = data
					log.debug("Loaded template: %s from %s", name, path)
				except Exception as exc:
					log.warning("Failed to load template %s: %s", path, exc)
		self._scan_done = True

	def list(self) -> list[dict[str, Any]]:
		"""Return metadata for all available templates (sorted by name)."""
		self._scan_dirs()
		return sorted(
			[
				{
					"name": t.get("name", ""),
					"label": t.get("label", ""),
					"description": t.get("description", ""),
					"version": t.get("version", ""),
					"table_count": len(t.get("tables", {})),
					"tags": t.get("tags", []),
					"source": "bundled" if self._is_bundled(t.get("name", "")) else "user",
				}
				for t in self._cache.values()
			],
			key=lambda x: x["name"],
		)

	def get(self, name: str) -> dict[str, Any]:
		"""Return the full template definition for the given name.

		Raises:
		    TemplateNotFoundError: if the template doesn't exist.
		"""
		self._scan_dirs()
		if name not in self._cache:
			available = ", ".join(sorted(self._cache))
			raise TemplateNotFoundError(
				f"Template {name!r} not found. Available: {available or 'none'}"
			)
		return self._cache[name]

	def load_all(self) -> dict[str, dict]:
		"""Return all templates in ERD Designer ERP_MODULES-compatible format.

		Returns::

		    {
		      "fhir-r4": {
		        "label": "HL7 FHIR R4",
		        "color": "#3498db",
		        "icon": "fa-heartbeat",
		        "description": "...",
		        "tables": {"patient": [...], "encounter": [...], ...},
		      },
		      ...
		    }
		"""
		self._scan_dirs()
		result = {}
		for name, t in self._cache.items():
			result[name] = {
				"label": t.get("label", name),
				"color": t.get("color", "#3498db"),
				"icon": t.get("icon", "fa-database"),
				"description": t.get("description", ""),
				"tables": t.get("tables", {}),
			}
		return result

	def install_from_file(self, path: str | Path) -> str:
		"""Install a template from a local JSON file into the user templates dir.

		Args:
		    path: Path to the template JSON file.

		Returns:
		    The template name.
		"""
		path = Path(path)
		if not path.exists():
			raise FileNotFoundError(f"Template file not found: {path}")
		data = json.loads(path.read_text(encoding="utf-8"))
		name = data.get("name") or path.stem
		_USER_DIR.mkdir(parents=True, exist_ok=True)
		dest = _USER_DIR / f"{name}.json"
		dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
		self._cache[name] = data
		log.info("Installed template %r → %s", name, dest)
		return name

	def install_from_dict(self, data: dict) -> str:
		"""Install a template from a dict into the user templates dir."""
		name = data.get("name")
		if not name:
			raise ValueError("Template dict must have a 'name' field")
		_USER_DIR.mkdir(parents=True, exist_ok=True)
		dest = _USER_DIR / f"{name}.json"
		dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
		self._cache[name] = data
		self._scan_done = True
		return name

	def remove(self, name: str) -> None:
		"""Remove a user-installed template.

		Bundled templates cannot be removed.
		"""
		if self._is_bundled(name):
			raise ValueError(f"Cannot remove bundled template: {name!r}")
		path = _USER_DIR / f"{name}.json"
		if not path.exists():
			path = _PROJECT_DIR / f"{name}.json"
		if path.exists():
			path.unlink()
			self._cache.pop(name, None)
			log.info("Removed template: %s", name)
		else:
			raise TemplateNotFoundError(f"Template {name!r} not found in user templates.")

	def _is_bundled(self, name: str) -> bool:
		return (_BUNDLED_DIR / f"{name}.json").exists()

	def refresh(self) -> None:
		"""Force rescan of all template directories."""
		self._scan_done = False
		self._cache.clear()
		self._scan_dirs()
