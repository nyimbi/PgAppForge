"""PDL Visual Entity Designer — Flask view + JSON API."""
from __future__ import annotations

import json
import logging

from flask import Response, jsonify, render_template, request

from pgappforge import expose
from pgappforge.baseviews import BaseView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


class PDLDesignerView(BaseView):
	route_base = "/pdl-designer"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return render_template("appbuilder/pdl_designer/index.html", appbuilder=self.appbuilder)

	@expose("/api/plugins", methods=["GET"])
	@has_access
	def api_plugins(self):
		try:
			from pgappforge.pdl.inspector import get_plugin_model_catalogue
			catalogue = get_plugin_model_catalogue()
			return jsonify({"ok": True, "domains": catalogue})
		except Exception as exc:
			log.exception("plugin catalogue failed")
			return jsonify({"ok": False, "error": str(exc)}), 500

	@expose("/api/generate", methods=["POST"])
	@has_access
	def api_generate(self):
		try:
			body = request.get_json(silent=True) or {}
			entities_raw = body.get("entities", [])
			if not entities_raw:
				return jsonify({"ok": False, "error": "No entities supplied"}), 400
			from pgappforge.pdl.schema import PDLEntity, PDLField, PDLSchema
			from pgappforge.pdl.generators import PDLCodeGenerator
			entities = []
			for e in entities_raw:
				fields = [
					PDLField(
						name=f["name"],
						type=f.get("type", "string"),
						nullable=f.get("nullable", True),
						unique=f.get("unique", False),
						indexed=f.get("indexed", False),
						fk=f.get("fk"),
						label=f.get("label"),
						max_length=f.get("max_length"),
					)
					for f in e.get("fields", [])
				]
				entities.append(PDLEntity(
					name=e["name"],
					table=e.get("table", e["name"].lower()),
					description=e.get("description", ""),
					fields=fields,
					module_path=e.get("module_path", f"pgappforge.models.generated.{e['name'].lower()}"),
					generate=e.get("generate", ["model", "migration", "view", "api", "tests"]),
				))
			schema = PDLSchema(namespace="designer_output", version="1.0.0", entities=entities)
			gen = PDLCodeGenerator()
			all_files = gen.generate_all(schema)
			all_files.update(gen.generate_schema_files(schema))
			return jsonify({"ok": True, "files": all_files})
		except Exception as exc:
			log.exception("generate failed")
			return jsonify({"ok": False, "error": str(exc)}), 500

	@expose("/api/pdl-yaml", methods=["GET"])
	@has_access
	def api_pdl_yaml(self):
		try:
			schema_json = request.args.get("schema", "{}")
			entities_raw = json.loads(schema_json).get("entities", [])
			lines = ["name: designer_output", "version: 1.0.0", "entities:"]
			for e in entities_raw:
				lines.append(f"  - name: {e['name']}")
				lines.append(f"    table: {e.get('table', e['name'].lower())}")
				if e.get("description"):
					lines.append(f"    description: \"{e['description']}\"")
				lines.append("    fields:")
				for f in e.get("fields", []):
					lines.append(f"      - name: {f['name']}")
					lines.append(f"        type: {f.get('type', 'string')}")
					if not f.get("nullable", True):
						lines.append("        nullable: false")
					if f.get("unique"):
						lines.append("        unique: true")
					if f.get("fk"):
						lines.append(f"        fk: \"{f['fk']}\"")
			yaml_str = "\n".join(lines) + "\n"
			return Response(
				yaml_str, mimetype="text/yaml",
				headers={"Content-Disposition": "attachment; filename=schema.pdl.yaml"},
			)
		except Exception as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


__all__ = ["PDLDesignerView"]
