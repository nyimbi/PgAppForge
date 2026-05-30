"""
AGEGraphIO — import/export an Apache AGE graph via multiple interchange formats.

Supported formats:
  - NetworkX (in-memory)
  - GraphML, GEXF, GML, Pajek (via networkx I/O)
  - JSON (custom {vertices: [...], edges: [...]})

NetworkX is an optional dependency; all public methods that require it raise
``ImportError`` with a clear message when it is absent.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .graph import AGEGraph
from .types import Edge, Vertex

log = logging.getLogger(__name__)

try:
	import networkx as nx
	_NX_AVAILABLE = True
except ImportError:
	nx = None  # type: ignore[assignment]
	_NX_AVAILABLE = False


def _require_nx() -> None:
	if not _NX_AVAILABLE:
		raise ImportError(
			"networkx is required for this operation. "
			"Install it with: pip install networkx"
		)


class AGEGraphIO:
	"""Import and export an :class:`AGEGraph` via multiple interchange formats.

	Args:
	    graph: An initialised :class:`AGEGraph` instance.

	Example::

	    io = AGEGraphIO(graph)
	    g = io.to_networkx()
	    io.export_graphml("/tmp/social.graphml")
	    count = io.import_json(data, vertex_label="Person", edge_label="KNOWS")
	"""

	def __init__(self, graph: AGEGraph) -> None:
		self.graph = graph

	# ------------------------------------------------------------------
	# NetworkX bridge
	# ------------------------------------------------------------------

	def to_networkx(self) -> "nx.Graph":
		"""Query all vertices and edges from AGE, return a networkx DiGraph.

		Vertex properties become node attributes; edge properties become edge
		attributes. The AGE internal ``id`` is stored as the node key and also
		as the ``_age_id`` attribute so it survives round-trips.

		Returns:
		    A :class:`networkx.DiGraph` populated from the live graph.

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()

		g: nx.DiGraph = nx.DiGraph()

		# Fetch all vertices
		vertex_rows = self.graph.cypher("MATCH (v) RETURN v")
		for row in vertex_rows:
			v = row.get("v")
			if not isinstance(v, Vertex):
				continue
			attrs = dict(v.properties)
			attrs["_age_id"] = v.id
			attrs["_label"] = v.label
			g.add_node(v.id, **attrs)

		# Fetch all edges
		edge_rows = self.graph.cypher("MATCH ()-[e]->() RETURN e")
		for row in edge_rows:
			e = row.get("e")
			if not isinstance(e, Edge):
				continue
			attrs = dict(e.properties)
			attrs["_age_id"] = e.id
			attrs["_label"] = e.label
			g.add_edge(e.start_id, e.end_id, **attrs)

		log.debug(
			"to_networkx: graph=%r nodes=%d edges=%d",
			self.graph.graph_name,
			g.number_of_nodes(),
			g.number_of_edges(),
		)
		return g

	def from_networkx(
		self,
		g: "nx.Graph",
		vertex_label: str,
		edge_label: str,
	) -> int:
		"""Import a networkx graph into AGE.

		Each networkx node becomes a vertex with label *vertex_label*; each
		edge becomes a relationship with type *edge_label*. Node/edge
		attributes (except networkx internals) are stored as AGE properties.

		Node IDs are stored as ``_nx_id`` on the AGE vertex so that edges can
		be wired up in a second pass without relying on AGE-internal IDs.

		Args:
		    g: Source networkx graph (directed or undirected).
		    vertex_label: AGE vertex label for all imported nodes.
		    edge_label: AGE relationship type for all imported edges.

		Returns:
		    Total number of AGE elements created (vertices + edges).

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()

		created = 0

		# Create vertices, tagging each with its networkx node ID
		for node_id, attrs in g.nodes(data=True):
			props: dict[str, Any] = {
				k: v for k, v in attrs.items()
				if not k.startswith("_age_")  # skip round-trip metadata
			}
			props["_nx_id"] = str(node_id)
			self.graph.cypher(
				f"CREATE (v:{vertex_label} $props)",
				params={"props": props},
			)
			created += 1

		# Create edges by matching on the _nx_id property
		for src, dst, attrs in g.edges(data=True):
			edge_props: dict[str, Any] = {
				k: v for k, v in attrs.items()
				if not k.startswith("_age_")
			}
			self.graph.cypher(
				f"MATCH (a:{vertex_label} {{_nx_id: $src}}), "
				f"(b:{vertex_label} {{_nx_id: $dst}}) "
				f"CREATE (a)-[e:{edge_label} $props]->(b)",
				params={
					"src": str(src),
					"dst": str(dst),
					"props": edge_props,
				},
			)
			created += 1

		log.debug(
			"from_networkx: graph=%r created=%d",
			self.graph.graph_name,
			created,
		)
		return created

	# ------------------------------------------------------------------
	# GraphML
	# ------------------------------------------------------------------

	def export_graphml(self, path: str) -> None:
		"""Export the graph to a GraphML file.

		Args:
		    path: Destination file path.

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()
		g = self.to_networkx()
		nx.write_graphml(g, path)
		log.info("export_graphml: wrote %r", path)

	def import_graphml(
		self,
		path: str,
		vertex_label: str = "Node",
		edge_label: str = "CONNECTS",
	) -> int:
		"""Import a GraphML file into AGE.

		Args:
		    path: Source GraphML file path.
		    vertex_label: AGE vertex label for all imported nodes.
		    edge_label: AGE relationship type for all imported edges.

		Returns:
		    Number of AGE elements created.

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()
		g: nx.Graph = nx.read_graphml(path)
		log.info("import_graphml: loaded %r (%d nodes, %d edges)", path, g.number_of_nodes(), g.number_of_edges())
		return self.from_networkx(g, vertex_label, edge_label)

	# ------------------------------------------------------------------
	# GEXF
	# ------------------------------------------------------------------

	def export_gexf(self, path: str) -> None:
		"""Export the graph to a GEXF file.

		Args:
		    path: Destination file path.

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()
		g = self.to_networkx()
		nx.write_gexf(g, path)
		log.info("export_gexf: wrote %r", path)

	def import_gexf(
		self,
		path: str,
		vertex_label: str = "Node",
		edge_label: str = "CONNECTS",
	) -> int:
		"""Import a GEXF file into AGE.

		Args:
		    path: Source GEXF file path.
		    vertex_label: AGE vertex label for all imported nodes.
		    edge_label: AGE relationship type for all imported edges.

		Returns:
		    Number of AGE elements created.

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()
		g: nx.Graph = nx.read_gexf(path)
		log.info("import_gexf: loaded %r (%d nodes, %d edges)", path, g.number_of_nodes(), g.number_of_edges())
		return self.from_networkx(g, vertex_label, edge_label)

	# ------------------------------------------------------------------
	# GML
	# ------------------------------------------------------------------

	def export_gml(self, path: str) -> None:
		"""Export the graph to a GML file.

		Args:
		    path: Destination file path.

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()
		g = self.to_networkx()
		nx.write_gml(g, path)
		log.info("export_gml: wrote %r", path)

	def import_gml(
		self,
		path: str,
		vertex_label: str = "Node",
		edge_label: str = "CONNECTS",
	) -> int:
		"""Import a GML file into AGE.

		Args:
		    path: Source GML file path.
		    vertex_label: AGE vertex label for all imported nodes.
		    edge_label: AGE relationship type for all imported edges.

		Returns:
		    Number of AGE elements created.

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()
		g: nx.Graph = nx.read_gml(path)
		log.info("import_gml: loaded %r (%d nodes, %d edges)", path, g.number_of_nodes(), g.number_of_edges())
		return self.from_networkx(g, vertex_label, edge_label)

	# ------------------------------------------------------------------
	# Pajek
	# ------------------------------------------------------------------

	def export_pajek(self, path: str) -> None:
		"""Export the graph to a Pajek .net file.

		Args:
		    path: Destination file path.

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()
		g = self.to_networkx()
		nx.write_pajek(g, path)
		log.info("export_pajek: wrote %r", path)

	def import_pajek(
		self,
		path: str,
		vertex_label: str = "Node",
		edge_label: str = "CONNECTS",
	) -> int:
		"""Import a Pajek .net file into AGE.

		Args:
		    path: Source Pajek file path.
		    vertex_label: AGE vertex label for all imported nodes.
		    edge_label: AGE relationship type for all imported edges.

		Returns:
		    Number of AGE elements created.

		Raises:
		    ImportError: if networkx is not installed.
		"""
		_require_nx()
		g: nx.Graph = nx.read_pajek(path)
		log.info("import_pajek: loaded %r (%d nodes, %d edges)", path, g.number_of_nodes(), g.number_of_edges())
		return self.from_networkx(g, vertex_label, edge_label)

	# ------------------------------------------------------------------
	# JSON (native, no networkx required)
	# ------------------------------------------------------------------

	def export_json(self) -> dict[str, list[dict[str, Any]]]:
		"""Export the complete graph as a plain Python dict.

		The returned structure is::

		    {
		        "vertices": [
		            {"id": 1, "label": "Person", "properties": {...}},
		            ...
		        ],
		        "edges": [
		            {
		                "id": 10,
		                "label": "KNOWS",
		                "start_id": 1,
		                "end_id": 2,
		                "properties": {...}
		            },
		            ...
		        ]
		    }

		No networkx dependency required.

		Returns:
		    Dict with ``"vertices"`` and ``"edges"`` lists.
		"""
		vertices: list[dict[str, Any]] = []
		edges: list[dict[str, Any]] = []

		for row in self.graph.cypher("MATCH (v) RETURN v"):
			v = row.get("v")
			if isinstance(v, Vertex):
				vertices.append({
					"id": v.id,
					"label": v.label,
					"properties": dict(v.properties),
				})

		for row in self.graph.cypher("MATCH ()-[e]->() RETURN e"):
			e = row.get("e")
			if isinstance(e, Edge):
				edges.append({
					"id": e.id,
					"label": e.label,
					"start_id": e.start_id,
					"end_id": e.end_id,
					"properties": dict(e.properties),
				})

		log.debug(
			"export_json: graph=%r vertices=%d edges=%d",
			self.graph.graph_name,
			len(vertices),
			len(edges),
		)
		return {"vertices": vertices, "edges": edges}

	def import_json(
		self,
		data: dict[str, list[dict[str, Any]]],
		vertex_label: str = "Node",
		edge_label: str = "CONNECTS",
	) -> int:
		"""Import a graph from the dict format produced by :meth:`export_json`.

		When the source data contains ``"label"`` fields on vertices/edges those
		take precedence over *vertex_label* / *edge_label* fallbacks.

		The ``"id"`` value from the source is stored as ``_source_id`` on each
		AGE vertex so that edges can be re-wired correctly without depending on
		AGE's own internal IDs.

		No networkx dependency required.

		Args:
		    data: Dict with ``"vertices"`` and ``"edges"`` lists.
		    vertex_label: Fallback vertex label when the source has none.
		    edge_label: Fallback relationship type when the source has none.

		Returns:
		    Total number of AGE elements created (vertices + edges).
		"""
		created = 0

		for v_data in data.get("vertices", []):
			label = v_data.get("label") or vertex_label
			props: dict[str, Any] = dict(v_data.get("properties", {}))
			# Tag with source ID for edge wiring
			props["_source_id"] = str(v_data["id"])
			self.graph.cypher(
				f"CREATE (v:{label} $props)",
				params={"props": props},
			)
			created += 1

		for e_data in data.get("edges", []):
			label = e_data.get("label") or edge_label
			# Infer vertex labels: match any vertex carrying the source IDs
			e_props: dict[str, Any] = dict(e_data.get("properties", {}))
			src_id = str(e_data["start_id"])
			dst_id = str(e_data["end_id"])
			self.graph.cypher(
				f"MATCH (a {{_source_id: $src}}), (b {{_source_id: $dst}}) "
				f"CREATE (a)-[e:{label} $props]->(b)",
				params={
					"src": src_id,
					"dst": dst_id,
					"props": e_props,
				},
			)
			created += 1

		log.debug(
			"import_json: graph=%r created=%d",
			self.graph.graph_name,
			created,
		)
		return created
