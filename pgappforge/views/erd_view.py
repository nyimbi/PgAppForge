"""
Entity Relationship Diagram (ERD) View for pgappforge.

Provides an interactive ERD generated live from the PostgreSQL database using
EnhancedDatabaseInspector. Renders via Mermaid.js with zoom/pan, click-to-highlight,
and export endpoints for Mermaid syntax, SQL, and GraphML.
"""
from __future__ import annotations

import logging
import textwrap
import xml.etree.ElementTree as ET
from typing import Any

from flask import current_app, jsonify, render_template_string, Response

from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector
from pgappforge.views.erd_schema_manager import _to_mermaid_str

_log_ = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Inline HTML template — no template directory needed
# ---------------------------------------------------------------------------
_ERD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Entity Relationship Diagram</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f0f2f5; color: #1a1a2e; }
  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 20px; background: #1a1a2e; color: #e0e0e0;
    box-shadow: 0 2px 6px rgba(0,0,0,.4);
  }
  header h1 { font-size: 1.1rem; font-weight: 600; letter-spacing: .03em; }
  .toolbar {
    display: flex; gap: 8px; flex-wrap: wrap;
    padding: 10px 20px; background: #fff;
    border-bottom: 1px solid #dde1e7;
  }
  .toolbar a, .toolbar button {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 6px 14px; border-radius: 5px; font-size: .85rem; cursor: pointer;
    text-decoration: none; border: 1px solid #c8cdd6; background: #f7f8fa; color: #333;
    transition: background .15s, border-color .15s;
  }
  .toolbar a:hover, .toolbar button:hover { background: #e8ecf4; border-color: #9aa3b5; }
  #stats {
    padding: 6px 20px; background: #eef1f6; font-size: .78rem; color: #555;
    border-bottom: 1px solid #dde1e7;
  }
  #diagram-container {
    width: 100%; height: calc(100vh - 140px); overflow: hidden;
    position: relative; background: #fff;
  }
  #diagram-inner {
    width: 100%; height: 100%;
    display: flex; align-items: flex-start; justify-content: center;
    padding: 20px; overflow: auto; cursor: grab;
    transform-origin: top left;
  }
  #diagram-inner:active { cursor: grabbing; }
  .mermaid { min-width: 600px; }
  /* Mermaid entity highlight override */
  .er.entityBox.highlighted rect { fill: #fffbe6 !important; stroke: #f59e0b !important; stroke-width: 2px !important; }
  #zoom-controls {
    position: fixed; bottom: 24px; right: 24px;
    display: flex; flex-direction: column; gap: 4px; z-index: 100;
  }
  #zoom-controls button {
    width: 36px; height: 36px; border-radius: 6px; border: 1px solid #bbb;
    background: #fff; font-size: 1.1rem; cursor: pointer; font-weight: 700;
    box-shadow: 0 2px 6px rgba(0,0,0,.15);
    display: flex; align-items: center; justify-content: center;
  }
  #zoom-controls button:hover { background: #e8ecf4; }
  #table-list {
    position: fixed; top: 130px; left: 0; bottom: 0; width: 220px;
    background: #fff; border-right: 1px solid #dde1e7;
    overflow-y: auto; padding: 10px 0; z-index: 50;
    transform: translateX(-220px); transition: transform .25s;
  }
  #table-list.open { transform: translateX(0); }
  #table-list h3 { padding: 0 14px 8px; font-size: .85rem; color: #888; text-transform: uppercase;
    letter-spacing: .06em; border-bottom: 1px solid #eee; margin-bottom: 6px; }
  #table-list ul { list-style: none; }
  #table-list li a {
    display: block; padding: 5px 14px; font-size: .83rem; color: #333;
    text-decoration: none; border-left: 3px solid transparent;
  }
  #table-list li a:hover,
  #table-list li a.active { background: #eef1f6; border-left-color: #3b82f6; color: #1d4ed8; }
  #panel-toggle {
    position: fixed; top: 50%; left: 0; transform: translateY(-50%);
    background: #3b82f6; color: #fff; border: none; border-radius: 0 6px 6px 0;
    padding: 10px 6px; cursor: pointer; z-index: 60; font-size: .7rem;
    writing-mode: vertical-rl; letter-spacing: .08em; text-transform: uppercase;
    box-shadow: 2px 0 8px rgba(0,0,0,.15);
  }
</style>
</head>
<body>
<header>
  <h1>Entity Relationship Diagram &mdash; {{ db_name }}</h1>
  <span style="font-size:.8rem; color:#888;">{{ table_count }} tables &middot; {{ rel_count }} relationships</span>
</header>

<div class="toolbar">
  <a href="{{ url_for('.data_json') }}">&#x1F4E5; JSON</a>
  <a href="{{ url_for('.export_mermaid') }}">&#x1F4CB; Mermaid</a>
  <a href="{{ url_for('.export_sql') }}">&#x1F4BE; SQL</a>
  <a href="{{ url_for('.export_graphml') }}">&#x1F5E7; GraphML</a>
  <button onclick="resetZoom()">&#x1F50D; Reset</button>
</div>

<div id="stats">
  Database: <strong>{{ db_name }}</strong> &nbsp;|&nbsp;
  Tables: <strong>{{ table_count }}</strong> &nbsp;|&nbsp;
  Relationships: <strong>{{ rel_count }}</strong>
</div>

<button id="panel-toggle" onclick="togglePanel()">Tables</button>

<div id="table-list">
  <h3>Tables</h3>
  <ul id="table-nav"></ul>
</div>

<div id="diagram-container">
  <div id="diagram-inner">
    <div class="mermaid" id="erd-diagram">{{ mermaid_src }}</div>
  </div>
</div>

<div id="zoom-controls">
  <button onclick="zoom(1.2)" title="Zoom in">+</button>
  <button onclick="zoom(0.8)" title="Zoom out">&minus;</button>
  <button onclick="resetZoom()" title="Reset">&#x25A3;</button>
</div>

<script>
mermaid.initialize({
  startOnLoad: true,
  theme: 'default',
  er: { diagramPadding: 30, layoutDirection: 'TB', minEntityWidth: 100,
        minEntityHeight: 75, entityPadding: 15, useMaxWidth: false }
});

// ---- zoom / pan ----
let _scale = 1, _tx = 0, _ty = 0;
const inner = document.getElementById('diagram-inner');

function applyTransform() {
  inner.style.transform = `scale(${_scale}) translate(${_tx}px, ${_ty}px)`;
}
function zoom(factor) {
  _scale = Math.max(0.2, Math.min(5, _scale * factor));
  applyTransform();
}
function resetZoom() { _scale = 1; _tx = 0; _ty = 0; applyTransform(); }

inner.addEventListener('wheel', e => {
  e.preventDefault();
  zoom(e.deltaY < 0 ? 1.1 : 0.9);
}, { passive: false });

let _drag = false, _mx = 0, _my = 0;
inner.addEventListener('mousedown', e => { _drag = true; _mx = e.clientX; _my = e.clientY; });
window.addEventListener('mouseup', () => { _drag = false; });
window.addEventListener('mousemove', e => {
  if (!_drag) return;
  _tx += (e.clientX - _mx) / _scale;
  _ty += (e.clientY - _my) / _scale;
  _mx = e.clientX; _my = e.clientY;
  applyTransform();
});

// ---- table panel ----
function togglePanel() {
  document.getElementById('table-list').classList.toggle('open');
}

// ---- populate table nav and click-highlight after mermaid renders ----
document.addEventListener('DOMContentLoaded', () => {
  fetch('{{ url_for(".data_json") }}')
    .then(r => r.json())
    .then(data => {
      const nav = document.getElementById('table-nav');
      data.tables.forEach(t => {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = '#'; a.textContent = t.name;
        a.dataset.table = t.name;
        a.addEventListener('click', e => {
          e.preventDefault();
          highlightTable(t.name);
          document.querySelectorAll('#table-nav a').forEach(x => x.classList.remove('active'));
          a.classList.add('active');
        });
        li.appendChild(a); nav.appendChild(li);
      });
    });
});

function highlightTable(name) {
  // Mermaid generates <g class="er entityBox"> with title equal to table name
  document.querySelectorAll('.er.entityBox').forEach(g => {
    const title = g.querySelector('text');
    const rect = g.querySelector('rect');
    if (!rect) return;
    if (title && title.textContent.trim().toLowerCase() === name.toLowerCase()) {
      rect.style.fill = '#fffbe6';
      rect.style.stroke = '#f59e0b';
      rect.style.strokeWidth = '3px';
    } else {
      rect.style.fill = '';
      rect.style.stroke = '';
      rect.style.strokeWidth = '';
    }
  });
}
</script>
</body>
</html>
"""


class ERDView(BaseView):
	"""
	Interactive ERD view at /erd/.

	Generates diagrams live from the connected PostgreSQL database using
	EnhancedDatabaseInspector. All endpoints require @has_access.
	"""

	route_base = "/erd"
	default_view = "index"

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _get_db_uri(self) -> str:
		uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
		assert uri, "SQLALCHEMY_DATABASE_URI must be set in app config"
		return uri

	def _build_erd_data(self) -> dict[str, Any]:
		"""
		Return the canonical ERD payload:

		  {
		    tables: [{name, columns: [{name, type, pk, fk, nullable}]}],
		    relationships: [{from_table, from_col, to_table, to_col}]
		  }
		"""
		uri = self._get_db_uri()
		with EnhancedDatabaseInspector(uri) as inspector:
			table_names = [
				t for t in inspector.get_all_tables()
				if not t.startswith("ab_")
			]

			tables = []
			relationships = []

			for name in table_names:
				try:
					info = inspector.analyze_table(name)
				except Exception:
					_log_.warning("ERDView: skipping table %s — analyze failed", name, exc_info=True)
					continue

				tables.append({
					"name": name,
					"columns": [
						{
							"name": col.name,
							"type": col.type,
							"pk": col.primary_key,
							"fk": col.foreign_key,
							"nullable": col.nullable,
						}
						for col in info.columns
					],
				})

				for rel in info.relationships:
					for from_col, to_col in zip(rel.local_columns, rel.remote_columns):
						relationships.append({
							"from_table": name,
							"from_col": from_col,
							"to_table": rel.remote_table,
							"to_col": to_col,
						})

		return {"tables": tables, "relationships": relationships}

	@staticmethod
	def _to_mermaid(data: dict[str, Any]) -> str:
		"""Render ERD data as Mermaid erDiagram syntax.

		Delegates to the shared ``_to_mermaid_str`` in erd_schema_manager
		so both the designer and the viewer produce identical output.
		"""
		return _to_mermaid_str(data)

	@staticmethod
	def _to_sql(data: dict[str, Any]) -> str:
		"""Reconstruct CREATE TABLE SQL from ERD data."""
		blocks: list[str] = []
		# collect FK constraints by table
		fk_index: dict[str, list[dict[str, Any]]] = {t["name"]: [] for t in data["tables"]}
		for rel in data["relationships"]:
			fk_index.setdefault(rel["from_table"], []).append(rel)

		for table in data["tables"]:
			name = table["name"]
			col_defs: list[str] = []
			for col in table["columns"]:
				col_type = col["type"] or "TEXT"
				nullable = "" if col["nullable"] else " NOT NULL"
				pk = " PRIMARY KEY" if col["pk"] else ""
				col_defs.append(f'    "{col["name"]}" {col_type}{pk}{nullable}')

			for rel in fk_index.get(name, []):
				col_defs.append(
					f'    FOREIGN KEY ("{rel["from_col"]}") '
					f'REFERENCES "{rel["to_table"]}" ("{rel["to_col"]}")'
				)

			body = ",\n".join(col_defs)
			blocks.append(f'CREATE TABLE IF NOT EXISTS "{name}" (\n{body}\n);')

		return "\n\n".join(blocks)

	@staticmethod
	def _to_graphml(data: dict[str, Any]) -> str:
		"""Render ERD data as GraphML XML string."""
		graphml = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/graphml")
		graph = ET.SubElement(graphml, "graph", id="ERD", edgedefault="directed")

		# table nodes
		for table in data["tables"]:
			node = ET.SubElement(graph, "node", id=table["name"])
			cols_str = ", ".join(
				f'{c["name"]}:{c["type"]}'
				for c in table["columns"]
			)
			data_el = ET.SubElement(node, "data", key="columns")
			data_el.text = cols_str

		# FK edges
		seen: set[tuple[str, str]] = set()
		edge_id = 0
		for rel in data["relationships"]:
			pair = (rel["from_table"], rel["to_table"])
			if pair in seen:
				continue
			seen.add(pair)
			ET.SubElement(
				graph, "edge",
				id=f"e{edge_id}",
				source=rel["from_table"],
				target=rel["to_table"],
			)
			edge_id += 1

		return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(graphml, encoding="unicode")

	# ------------------------------------------------------------------
	# Routes
	# ------------------------------------------------------------------

	@expose("/")
	@has_access
	def index(self):
		"""GET /erd/ — interactive Mermaid ERD diagram."""
		try:
			data = self._build_erd_data()
			mermaid_src = self._to_mermaid(data)

			db_name = current_app.config.get("SQLALCHEMY_DATABASE_URI", "").split("/")[-1].split("?")[0] or "database"

			return render_template_string(
				_ERD_TEMPLATE,
				mermaid_src=mermaid_src,
				db_name=db_name,
				table_count=len(data["tables"]),
				rel_count=len(data["relationships"]),
			)
		except Exception as exc:
			_log_.exception("ERDView.index failed")
			return f"<pre>ERD generation failed:\n{exc}</pre>", 500

	@expose("/data.json")
	@has_access
	def data_json(self):
		"""GET /erd/data.json — ERD as structured JSON."""
		try:
			data = self._build_erd_data()
			return jsonify(data)
		except Exception as exc:
			_log_.exception("ERDView.data_json failed")
			return jsonify({"error": str(exc)}), 500

	@expose("/export/mermaid")
	@has_access
	def export_mermaid(self):
		"""GET /erd/export/mermaid — Mermaid erDiagram syntax as plain text."""
		try:
			data = self._build_erd_data()
			src = self._to_mermaid(data)
			return Response(src, mimetype="text/plain", headers={
				"Content-Disposition": "attachment; filename=erd.mmd"
			})
		except Exception as exc:
			_log_.exception("ERDView.export_mermaid failed")
			return Response(f"Error: {exc}", mimetype="text/plain", status=500)

	@expose("/export/sql")
	@has_access
	def export_sql(self):
		"""GET /erd/export/sql — CREATE TABLE SQL reconstruction."""
		try:
			data = self._build_erd_data()
			sql = self._to_sql(data)
			return Response(sql, mimetype="text/plain", headers={
				"Content-Disposition": "attachment; filename=schema.sql"
			})
		except Exception as exc:
			_log_.exception("ERDView.export_sql failed")
			return Response(f"Error: {exc}", mimetype="text/plain", status=500)

	@expose("/export/graphml")
	@has_access
	def export_graphml(self):
		"""GET /erd/export/graphml — ERD as GraphML (tables=nodes, FK=edges)."""
		try:
			data = self._build_erd_data()
			xml_str = self._to_graphml(data)
			return Response(xml_str, mimetype="application/xml", headers={
				"Content-Disposition": "attachment; filename=erd.graphml"
			})
		except Exception as exc:
			_log_.exception("ERDView.export_graphml failed")
			return Response(f"Error: {exc}", mimetype="text/plain", status=500)
