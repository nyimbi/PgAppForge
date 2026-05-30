"""
Knowledge Graph Explorer for pgappforge + Apache AGE.

Interactive visual graph exploration with:
- Cytoscape.js force-directed rendering
- No-code visual query builder (click-to-explore)
- Pre-built query templates (Connected To, N Hops, Shortest Path, etc.)
- OpenCypher editor for advanced users
- Centrality and community detection overlays
- Node/edge search and property filtering

Enable::

    from pgappforge.views.graph_explorer_view import GraphExplorerView
    appbuilder.add_view(GraphExplorerView, 'Graph Explorer',
                        icon='fa-project-diagram', category='Analytics')
"""
from __future__ import annotations

import json
from flask import request, jsonify, Response
from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access

from pgappforge.widgets_postgresql._cdn import CYTOSCAPE_CDN as _CYTOSCAPE_CDN
_D3_CDN = '<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>'


class GraphExplorerView(BaseView):
	"""Interactive knowledge graph explorer with visual query interface."""

	route_base = "/graph-explorer"
	default_view = "index"

	def _get_age_manager(self):
		"""Get AGEManager connected to the current app database."""
		try:
			from pgappforge.database.age import AGEManager
		except ImportError:
			raise RuntimeError(
				"Apache AGE support requires: pip install pgappforge[age] "
				"and the PostgreSQL AGE extension installed."
			)
		engine = self.appbuilder.get_session.bind
		mgr = AGEManager(engine)
		return mgr

	# ─── Main explorer view ───────────────────────────────────────────────────

	@expose("/")
	@has_access
	def index(self):
		"""Main graph explorer page."""
		mgr = self._get_age_manager()
		graphs = mgr.list_graphs()
		return self.render_template_string(_EXPLORER_TEMPLATE, graphs=graphs)

	# ─── Data API endpoints ───────────────────────────────────────────────────

	@expose("/api/graphs")
	@has_access
	def api_graphs(self):
		"""List all AGE graphs."""
		mgr = self._get_age_manager()
		return jsonify(mgr.list_graphs())

	@expose("/api/schema/<graph_name>")
	@has_access
	def api_schema(self, graph_name: str):
		"""Return graph schema (labels and property keys)."""
		mgr = self._get_age_manager()
		graph = mgr.graph(graph_name)
		schema = graph.schema()
		# Also get edge types
		try:
			edge_rows = graph.cypher("MATCH ()-[e]->() RETURN DISTINCT type(e) AS t LIMIT 100")
			edge_types = [r.get("t") for r in edge_rows if r.get("t")]
		except Exception:
			edge_types = []
		return jsonify({"vertex_labels": schema, "edge_types": edge_types})

	@expose("/api/query", methods=["POST"])
	@has_access
	def api_query(self):
		"""Execute an OpenCypher query and return Cytoscape.js elements.

		Request body::

		    {
		      "graph": "my_graph",
		      "cypher": "MATCH (n:Person)-[r]->(m) RETURN n, r, m LIMIT 100",
		      "limit": 200
		    }

		Returns Cytoscape.js element format::

		    {
		      "elements": {
		        "nodes": [{"data": {"id": "v1", "label": "Person", "name": "Alice"}}],
		        "edges": [{"data": {"id": "e1", "source": "v1", "target": "v2",
		                            "label": "KNOWS"}}]
		      },
		      "stats": {"nodes": N, "edges": M}
		    }
		"""
		body = request.get_json() or {}
		graph_name = body.get("graph", "")
		cypher = body.get("cypher", "").strip()
		limit = min(int(body.get("limit", 200)), 1000)

		if not graph_name or not cypher:
			return jsonify({"error": "graph and cypher are required"}), 400

		# Inject LIMIT if not present
		if "limit" not in cypher.lower():
			cypher = cypher.rstrip(";") + f" LIMIT {limit}"

		try:
			mgr = self._get_age_manager()
			rows = mgr.graph(graph_name).cypher(cypher)
			elements = _rows_to_cytoscape(rows)
			return jsonify({
				"elements": elements,
				"stats": {
					"nodes": len(elements["nodes"]),
					"edges": len(elements["edges"]),
					"rows": len(rows),
				},
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 400

	@expose("/api/visual-query", methods=["POST"])
	@has_access
	def api_visual_query(self):
		"""Execute a pre-built visual query.

		Request::

		    {
		      "graph": "my_graph",
		      "query_type": "connected_to" | "n_hops" | "shortest_path" |
		                     "centrality" | "community" | "by_label" | "search",
		      "params": {...}
		    }

		Query types and params:
		  connected_to:  {vertex_id: int}
		  n_hops:        {vertex_id: int, hops: int}
		  shortest_path: {from_id: int, to_id: int}
		  centrality:    {metric: "degree"|"closeness", label: str|None}
		  community:     {algorithm: "louvain"|"label_propagation"}
		  by_label:      {label: str, limit: int}
		  search:        {property: str, value: str, label: str|None}
		"""
		body = request.get_json() or {}
		graph_name = body.get("graph", "")
		qtype = body.get("query_type", "")
		params = body.get("params", {})

		if not graph_name:
			return jsonify({"error": "graph is required"}), 400

		try:
			mgr = self._get_age_manager()
			graph = mgr.graph(graph_name)
			cypher, meta = _build_visual_query(qtype, params)

			if not cypher:
				return jsonify({"error": f"Unknown query type: {qtype}"}), 400

			rows = graph.cypher(cypher)
			elements = _rows_to_cytoscape(rows)

			# For centrality/community, add score data
			if qtype in ("centrality", "community") and rows:
				_enrich_elements_with_scores(elements, rows, qtype)

			return jsonify({
				"elements": elements,
				"cypher": cypher,
				"meta": meta,
				"stats": {
					"nodes": len(elements["nodes"]),
					"edges": len(elements["edges"]),
				},
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 400

	@expose("/api/centrality/<graph_name>")
	@has_access
	def api_centrality(self, graph_name: str):
		"""Compute centrality scores for all nodes (uses networkx)."""
		metric = request.args.get("metric", "pagerank")
		label = request.args.get("label")
		try:
			from pgappforge.database.age.analytics import AGEAnalytics
			mgr = self._get_age_manager()
			analytics = AGEAnalytics(mgr.graph(graph_name))
			scores = analytics.centrality(metric=metric)
			return jsonify({"metric": metric, "scores": scores})
		except ImportError:
			return jsonify({"error": "pgappforge.database.age.analytics not available"}), 500
		except Exception as exc:
			return jsonify({"error": str(exc)}), 400

	@expose("/api/communities/<graph_name>")
	@has_access
	def api_communities(self, graph_name: str):
		"""Detect communities (uses networkx community algorithms)."""
		algorithm = request.args.get("algorithm", "louvain")
		try:
			from pgappforge.database.age.analytics import AGEAnalytics
			mgr = self._get_age_manager()
			analytics = AGEAnalytics(mgr.graph(graph_name))
			communities = analytics.community_detection(algorithm=algorithm)
			return jsonify({"algorithm": algorithm, "communities": communities})
		except ImportError:
			return jsonify({"error": "pgappforge.database.age.analytics not available"}), 500
		except Exception as exc:
			return jsonify({"error": str(exc)}), 400

	@expose("/api/stats/<graph_name>")
	@has_access
	def api_stats(self, graph_name: str):
		"""Return summary statistics for a graph."""
		mgr = self._get_age_manager()
		return jsonify(mgr.graph_stats(graph_name))


# ─── Query builder ────────────────────────────────────────────────────────────

def _build_visual_query(qtype: str, params: dict) -> tuple[str, dict]:
	"""Build a Cypher query from a visual query type + params."""

	if qtype == "connected_to":
		vid = int(params.get("vertex_id", 0))
		cypher = (
			f"MATCH (center) WHERE id(center) = {vid} "
			f"MATCH (center)-[r]-(neighbor) "
			f"RETURN center, r, neighbor LIMIT 100"
		)
		return cypher, {"description": "All nodes directly connected to the selected node"}

	if qtype == "n_hops":
		vid = int(params.get("vertex_id", 0))
		hops = max(1, min(int(params.get("hops", 2)), 5))
		cypher = (
			f"MATCH path = (start)-[*1..{hops}]-(end) "
			f"WHERE id(start) = {vid} "
			f"RETURN path LIMIT 200"
		)
		return cypher, {"description": f"All nodes within {hops} hop(s)"}

	if qtype == "shortest_path":
		from_id = int(params.get("from_id", 0))
		to_id = int(params.get("to_id", 0))
		cypher = (
			f"MATCH (a), (b) "
			f"WHERE id(a) = {from_id} AND id(b) = {to_id} "
			f"MATCH p = shortestPath((a)-[*]-(b)) "
			f"RETURN p"
		)
		return cypher, {"description": "Shortest path between two nodes"}

	if qtype == "by_label":
		label = params.get("label", "Node")
		limit = min(int(params.get("limit", 100)), 500)
		cypher = f"MATCH (n:{label})-[r]-(m) RETURN n, r, m LIMIT {limit}"
		return cypher, {"description": f"All {label} nodes and their connections"}

	if qtype == "search":
		prop = params.get("property", "name")
		val = params.get("value", "")
		label = params.get("label", "")
		label_str = f":{label}" if label else ""
		cypher = (
			f"MATCH (n{label_str}) "
			f"WHERE toLower(toString(n.{prop})) CONTAINS toLower('{val}') "
			f"OPTIONAL MATCH (n)-[r]-(m) "
			f"RETURN n, r, m LIMIT 100"
		)
		return cypher, {"description": f"Nodes where {prop} contains '{val}'"}

	if qtype == "most_connected":
		label = params.get("label", "")
		label_str = f":{label}" if label else ""
		limit = min(int(params.get("limit", 20)), 100)
		cypher = (
			f"MATCH (n{label_str}) "
			f"WITH n, size((n)-[]-()) AS degree "
			f"ORDER BY degree DESC LIMIT {limit} "
			f"MATCH (n)-[r]-(m) RETURN n, r, m"
		)
		return cypher, {"description": f"Top {limit} most-connected nodes"}

	if qtype == "all_paths":
		from_label = params.get("from_label", "Node")
		to_label = params.get("to_label", "Node")
		rel_type = params.get("rel_type", "")
		rel_str = f":{rel_type}" if rel_type else ""
		cypher = (
			f"MATCH (a:{from_label})-[r{rel_str}]->(b:{to_label}) "
			f"RETURN a, r, b LIMIT 200"
		)
		return cypher, {"description": f"All {from_label} → {to_label} paths"}

	return "", {}


# ─── Cytoscape.js element conversion ─────────────────────────────────────────

def _rows_to_cytoscape(rows: list[dict]) -> dict:
	"""Convert AGE query result rows to Cytoscape.js elements format."""
	from pgappforge.database.age.types import Vertex, Edge, Path

	nodes: dict[int, dict] = {}
	edges: dict[int, dict] = {}

	def add_vertex(v: Vertex):
		if v.id not in nodes:
			# Primary display property (first of: name, title, id, label)
			display = (
				v.properties.get("name")
				or v.properties.get("title")
				or v.properties.get("label")
				or str(v.id)
			)
			nodes[v.id] = {
				"data": {
					"id": str(v.id),
					"label": v.label,
					"display": str(display),
					**{k: str(val)[:100] for k, val in v.properties.items()},
				}
			}

	def add_edge(e: Edge):
		if e.id not in edges:
			edges[e.id] = {
				"data": {
					"id": f"e{e.id}",
					"source": str(e.start_id),
					"target": str(e.end_id),
					"label": e.label,
					**{k: str(val)[:50] for k, val in e.properties.items()},
				}
			}

	for row in rows:
		for val in row.values():
			if isinstance(val, Vertex):
				add_vertex(val)
			elif isinstance(val, Edge):
				add_edge(val)
			elif isinstance(val, Path):
				for v in val.vertices:
					add_vertex(v)
				for e in val.edges:
					add_edge(e)
			elif isinstance(val, list):
				for item in val:
					if isinstance(item, Vertex):
						add_vertex(item)
					elif isinstance(item, Edge):
						add_edge(item)

	return {
		"nodes": list(nodes.values()),
		"edges": list(edges.values()),
	}


def _enrich_elements_with_scores(elements: dict, rows: list[dict], qtype: str):
	"""Add score/community data to node data for coloring."""
	pass  # enrichment happens client-side via /api/centrality and /api/communities


# ─── HTML Template ────────────────────────────────────────────────────────────

_EXPLORER_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Knowledge Graph Explorer</title>
  <link rel="stylesheet"
    href="{{ url_for('static', filename='appbuilder/css/bootstrap.min.css') }}">
  """ + _CYTOSCAPE_CDN + """
  <style>
    body { overflow: hidden; }
    #layout { display: flex; height: 100vh; }
    #sidebar { width: 320px; min-width: 320px; overflow-y: auto;
                background: #f8f9fa; border-right: 1px solid #dee2e6; padding: 12px; }
    #cy { flex: 1; background: #1a1a2e; }
    .query-btn { width: 100%; text-align: left; margin-bottom: 4px; }
    #info-panel { position: absolute; bottom: 12px; right: 12px;
                  background: rgba(0,0,0,0.75); color: #fff; border-radius: 6px;
                  padding: 10px 14px; font-size: 0.82em; max-width: 280px;
                  display: none; }
    #status { position: absolute; top: 8px; left: 340px; font-size: 0.8em;
               background: rgba(0,0,0,0.6); color: #fff; border-radius: 4px;
               padding: 4px 10px; }
    .spinner { display: none; }
    .legend-dot { display: inline-block; width: 12px; height: 12px;
                  border-radius: 50%; margin-right: 4px; }
  </style>
</head>
<body>
<div id="layout">
  <!-- Sidebar -->
  <div id="sidebar">
    <h5 style="margin-top:0"><i class="fa fa-project-diagram"></i> Graph Explorer</h5>

    <!-- Graph selector -->
    <div class="form-group">
      <label>Graph</label>
      <select class="form-control input-sm" id="graphSelect">
        {% for g in graphs %}
        <option value="{{ g.name }}">{{ g.name }}</option>
        {% endfor %}
      </select>
    </div>

    <!-- Visual queries -->
    <div class="panel panel-default">
      <div class="panel-heading" style="padding:6px 10px;cursor:pointer"
           data-toggle="collapse" data-target="#visualQueries">
        <b>Visual Queries</b>
      </div>
      <div id="visualQueries" class="panel-collapse collapse in">
        <div class="panel-body" style="padding:8px">

          <div class="form-group">
            <label style="font-size:0.85em">Query type</label>
            <select class="form-control input-sm" id="queryType" onchange="updateQueryParams()">
              <option value="by_label">All nodes by label</option>
              <option value="connected_to">Connected to node ID</option>
              <option value="n_hops">N hops from node</option>
              <option value="shortest_path">Shortest path</option>
              <option value="search">Search by property</option>
              <option value="most_connected">Most connected nodes</option>
              <option value="all_paths">All paths (label → label)</option>
            </select>
          </div>

          <div id="queryParams">
            <!-- populated dynamically -->
          </div>

          <button class="btn btn-primary btn-sm" onclick="runVisualQuery()">
            <i class="fa fa-play"></i> Run Query
          </button>
          <button class="btn btn-default btn-sm" onclick="clearGraph()">
            <i class="fa fa-times"></i> Clear
          </button>
        </div>
      </div>
    </div>

    <!-- Cypher editor -->
    <div class="panel panel-default">
      <div class="panel-heading" style="padding:6px 10px;cursor:pointer"
           data-toggle="collapse" data-target="#cypherPanel">
        <b>OpenCypher Editor</b>
      </div>
      <div id="cypherPanel" class="panel-collapse collapse">
        <div class="panel-body" style="padding:8px">
          <textarea id="cypherInput" class="form-control" rows="5"
            style="font-family:monospace;font-size:0.8em"
            placeholder="MATCH (n)-[r]->(m) RETURN n,r,m LIMIT 50"></textarea>
          <button class="btn btn-primary btn-sm" style="margin-top:6px"
                  onclick="runCypher()">
            <i class="fa fa-terminal"></i> Execute
          </button>
        </div>
      </div>
    </div>

    <!-- Overlays -->
    <div class="panel panel-default">
      <div class="panel-heading" style="padding:6px 10px;cursor:pointer"
           data-toggle="collapse" data-target="#overlayPanel">
        <b>Overlays</b>
      </div>
      <div id="overlayPanel" class="panel-collapse collapse">
        <div class="panel-body" style="padding:8px">
          <button class="btn btn-default btn-sm query-btn"
                  onclick="applyOverlay('centrality','pagerank')">
            PageRank centrality
          </button>
          <button class="btn btn-default btn-sm query-btn"
                  onclick="applyOverlay('centrality','degree')">
            Degree centrality
          </button>
          <button class="btn btn-default btn-sm query-btn"
                  onclick="applyOverlay('community','louvain')">
            Communities (Louvain)
          </button>
          <button class="btn btn-default btn-sm query-btn"
                  onclick="applyOverlay('community','label_propagation')">
            Communities (Label Propagation)
          </button>
          <button class="btn btn-default btn-sm query-btn"
                  onclick="resetColors()">
            Reset colors
          </button>
        </div>
      </div>
    </div>

    <!-- Layout -->
    <div class="form-group">
      <label style="font-size:0.85em">Layout</label>
      <select class="form-control input-sm" id="layoutSelect" onchange="applyLayout()">
        <option value="cose">Force-directed (CoSE)</option>
        <option value="circle">Circle</option>
        <option value="grid">Grid</option>
        <option value="breadthfirst">Breadth-first</option>
        <option value="concentric">Concentric</option>
      </select>
    </div>

    <div id="graphLegend" style="margin-top:8px;font-size:0.82em"></div>
  </div>

  <!-- Graph canvas -->
  <div style="position:relative;flex:1">
    <div id="cy"></div>
    <div id="status">No graph loaded</div>
    <div id="info-panel"></div>
  </div>
</div>

<script src="{{ url_for('static', filename='appbuilder/js/jquery-latest.js') }}"></script>
<script src="{{ url_for('static', filename='appbuilder/js/bootstrap.min.js') }}"></script>
<script>
/* ── Cytoscape init ── */
var cy = cytoscape({
  container: document.getElementById('cy'),
  style: [
    { selector: 'node',
      style: { 'background-color': '#2980b9', 'label': 'data(display)',
               'color': '#fff', 'text-valign': 'bottom', 'text-halign': 'center',
               'font-size': '11px', 'width': 30, 'height': 30,
               'text-background-color': 'rgba(0,0,0,0.5)',
               'text-background-opacity': 0.7, 'text-background-padding': '2px' } },
    { selector: 'node:selected',
      style: { 'background-color': '#e74c3c', 'border-width': 3,
               'border-color': '#fff' } },
    { selector: 'edge',
      style: { 'label': 'data(label)', 'font-size': '9px', 'color': '#aaa',
               'line-color': '#555', 'target-arrow-color': '#555',
               'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
               'width': 2 } },
    { selector: 'edge:selected',
      style: { 'line-color': '#f39c12', 'target-arrow-color': '#f39c12' } },
  ],
  layout: { name: 'cose' },
  wheelSensitivity: 0.2,
});

/* Click on node → show info + allow visual query from node */
cy.on('tap', 'node', function(e) {
  var n = e.target;
  var info = '<b>' + n.data('display') + '</b><br>' +
    '<small>Label: ' + n.data('label') + ' | ID: ' + n.id() + '</small><hr>';
  var props = Object.entries(n.data())
    .filter(function(kv){ return !['id','label','display'].includes(kv[0]); })
    .slice(0, 8);
  props.forEach(function(kv){ info += kv[0] + ': ' + kv[1] + '<br>'; });
  info += '<hr>' +
    '<button class="btn btn-xs btn-default" onclick="expandNode(' + n.id() + ')">Expand connections</button> ' +
    '<button class="btn btn-xs btn-default" onclick="nHopsFrom(' + n.id() + ', 2)">2-hop neighbourhood</button>';
  document.getElementById('info-panel').innerHTML = info;
  document.getElementById('info-panel').style.display = 'block';
});

cy.on('tap', function(e) {
  if (e.target === cy) document.getElementById('info-panel').style.display = 'none';
});

/* ── Query helpers ── */
function currentGraph() { return document.getElementById('graphSelect').value; }

function setStatus(msg) { document.getElementById('status').textContent = msg; }

function addElements(data) {
  cy.add(data.elements.nodes.concat(data.elements.edges));
  cy.layout({ name: document.getElementById('layoutSelect').value,
               animate: true, animationDuration: 400 }).run();
  setStatus(data.stats.nodes + ' nodes, ' + data.stats.edges + ' edges');
  updateLegend();
}

function clearGraph() { cy.elements().remove(); setStatus('Cleared'); }

function runCypher() {
  var cypher = document.getElementById('cypherInput').value.trim();
  if (!cypher) return;
  setStatus('Running…');
  fetch('/graph-explorer/api/query', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({graph: currentGraph(), cypher: cypher})
  }).then(r => r.json()).then(function(d) {
    if (d.error) { setStatus('Error: ' + d.error); return; }
    addElements(d);
  }).catch(function(e){ setStatus('Error: ' + e); });
}

function runVisualQuery() {
  var qtype = document.getElementById('queryType').value;
  var params = collectParams();
  setStatus('Running ' + qtype + '…');
  fetch('/graph-explorer/api/visual-query', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({graph: currentGraph(), query_type: qtype, params: params})
  }).then(r => r.json()).then(function(d) {
    if (d.error) { setStatus('Error: ' + d.error); return; }
    addElements(d);
    if (d.cypher) document.getElementById('cypherInput').value = d.cypher;
  });
}

function expandNode(nodeId) {
  setStatus('Expanding node ' + nodeId + '…');
  fetch('/graph-explorer/api/visual-query', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({graph: currentGraph(), query_type: 'connected_to',
                          params: {vertex_id: nodeId}})
  }).then(r => r.json()).then(addElements);
}

function nHopsFrom(nodeId, hops) {
  fetch('/graph-explorer/api/visual-query', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({graph: currentGraph(), query_type: 'n_hops',
                          params: {vertex_id: nodeId, hops: hops}})
  }).then(r => r.json()).then(addElements);
}

/* ── Overlays ── */
var COLORS20 = ['#e41a1c','#377eb8','#4daf4a','#984ea3','#ff7f00',
                '#a65628','#f781bf','#999999','#66c2a5','#fc8d62',
                '#8da0cb','#e78ac3','#a6d854','#ffd92f','#e5c494',
                '#b3b3b3','#8dd3c7','#ffffb3','#bebada','#fb8072'];

function applyOverlay(type, metric) {
  var g = currentGraph();
  var url = type === 'centrality'
    ? '/graph-explorer/api/centrality/' + g + '?metric=' + metric
    : '/graph-explorer/api/communities/' + g + '?algorithm=' + metric;
  setStatus('Computing ' + metric + '…');
  fetch(url).then(r => r.json()).then(function(d) {
    if (d.error) { setStatus('Error: ' + d.error); return; }
    if (type === 'centrality') {
      var scores = d.scores;
      var vals = Object.values(scores).map(Number);
      var min_ = Math.min.apply(null, vals), max_ = Math.max.apply(null, vals);
      cy.nodes().forEach(function(n) {
        var s = scores[n.id()] || 0;
        var pct = max_ > min_ ? (s - min_) / (max_ - min_) : 0;
        var r = Math.round(pct * 200), b = Math.round((1 - pct) * 200);
        n.style({'background-color': 'rgb(' + r + ',80,' + b + ')',
                 'width': 20 + pct * 40, 'height': 20 + pct * 40});
        n.data('score', s.toFixed(4));
      });
      setStatus('Centrality applied (' + metric + ')');
    } else {
      var comm = d.communities;
      cy.nodes().forEach(function(n) {
        var c = comm[n.id()];
        if (c !== undefined) {
          n.style({'background-color': COLORS20[c % COLORS20.length]});
          n.data('community', c);
        }
      });
      setStatus('Communities applied (' + metric + ')');
    }
  });
}

function resetColors() {
  cy.nodes().style({'background-color': '#2980b9', 'width': 30, 'height': 30});
  setStatus('Colors reset');
}

function applyLayout() {
  cy.layout({name: document.getElementById('layoutSelect').value,
             animate: true, animationDuration: 500}).run();
}

/* ── Legend ── */
function updateLegend() {
  var labels = {};
  cy.nodes().forEach(function(n) {
    var l = n.data('label') || '?';
    labels[l] = (labels[l] || 0) + 1;
  });
  var html = Object.entries(labels).map(function(kv, i) {
    return '<span><span class="legend-dot" style="background:' +
      COLORS20[i % COLORS20.length] + '"></span>' + kv[0] +
      ' <span class="badge">' + kv[1] + '</span></span> ';
  }).join('');
  document.getElementById('graphLegend').innerHTML = html;
}

/* ── Query param forms ── */
var PARAM_FORMS = {
  'by_label':      '<label>Label</label><input class="form-control input-sm" id="p_label" value="Node">',
  'connected_to':  '<label>Node ID</label><input class="form-control input-sm" id="p_vertex_id" type="number" value="1">',
  'n_hops':        '<label>Node ID</label><input class="form-control input-sm" id="p_vertex_id" type="number" value="1">' +
                   '<label>Hops</label><input class="form-control input-sm" id="p_hops" type="number" value="2" min="1" max="5">',
  'shortest_path': '<label>From ID</label><input class="form-control input-sm" id="p_from_id" type="number" value="1">' +
                   '<label>To ID</label><input class="form-control input-sm" id="p_to_id" type="number" value="2">',
  'search':        '<label>Property</label><input class="form-control input-sm" id="p_property" value="name">' +
                   '<label>Contains</label><input class="form-control input-sm" id="p_value" value="">',
  'most_connected':'<label>Limit</label><input class="form-control input-sm" id="p_limit" type="number" value="20">',
  'all_paths':     '<label>From label</label><input class="form-control input-sm" id="p_from_label" value="Person">' +
                   '<label>To label</label><input class="form-control input-sm" id="p_to_label" value="Person">' +
                   '<label>Relationship (optional)</label><input class="form-control input-sm" id="p_rel_type" value="">',
};

function updateQueryParams() {
  var qtype = document.getElementById('queryType').value;
  document.getElementById('queryParams').innerHTML =
    (PARAM_FORMS[qtype] || '') + '<br>';
}

function collectParams() {
  var p = {};
  ['label','vertex_id','hops','from_id','to_id','property','value',
   'limit','from_label','to_label','rel_type'].forEach(function(k) {
    var el = document.getElementById('p_' + k);
    if (el) p[k] = el.type === 'number' ? parseInt(el.value) : el.value;
  });
  return p;
}

updateQueryParams();

/* ── Keyboard shortcuts ── */
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') document.getElementById('info-panel').style.display = 'none';
  if (e.key === 'Enter' && e.ctrlKey) runCypher();
});
</script>
</body>
</html>
"""
