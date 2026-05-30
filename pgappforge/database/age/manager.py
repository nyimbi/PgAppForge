"""
AGEManager — lifecycle management for Apache AGE graphs on a PostgreSQL database.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .graph import AGEGraph

log = logging.getLogger(__name__)


class AGEManager:
	"""Manages Apache AGE graphs: create, list, drop, and get handles.

	Usage::

	    from sqlalchemy import create_engine
	    from pgappforge.database.age import AGEManager

	    engine = create_engine('postgresql+psycopg2://user:pass@localhost/mydb')
	    mgr = AGEManager(engine)

	    # One-time setup (run once per database)
	    mgr.setup()

	    # Create a graph
	    graph = mgr.create_graph('knowledge_base')

	    # Get an existing graph handle
	    graph = mgr.graph('knowledge_base')

	    # Execute Cypher
	    rows = graph.cypher('MATCH (n:Concept) RETURN n.name LIMIT 5')
	"""

	def __init__(self, engine: Engine) -> None:
		self.engine = engine
		self._graphs: dict[str, AGEGraph] = {}

	def setup(self) -> None:
		"""Load the AGE extension and set the search path.

		Call once after connecting to the database.
		Creates the extension if it doesn't exist.
		"""
		with self.engine.connect() as conn:
			try:
				conn.execute(text("CREATE EXTENSION IF NOT EXISTS age"))
			except Exception:
				pass  # Extension may need superuser; skip if already exists
			try:
				conn.execute(text("LOAD 'age'"))
				conn.execute(text("SET search_path = ag_catalog, \"$user\", public"))
			except Exception as exc:
				log.warning("AGE setup partial: %s", exc)
			conn.commit()
		log.info("Apache AGE setup complete for database: %s", self.engine.url.database)

	def create_graph(self, name: str) -> AGEGraph:
		"""Create a new graph (no-op if it already exists).

		Args:
		    name: Graph name (alphanumeric, underscores allowed).

		Returns:
		    AGEGraph handle for executing Cypher queries.
		"""
		with self.engine.connect() as conn:
			conn.execute(text("LOAD 'age'"))
			conn.execute(text("SET search_path = ag_catalog, \"$user\", public"))
			try:
				conn.execute(text(f"SELECT create_graph('{name}')"))
				conn.commit()
				log.info("Created AGE graph: %s", name)
			except Exception:
				conn.rollback()
				log.debug("Graph %r may already exist — getting handle", name)
		graph = AGEGraph(self.engine, name)
		self._graphs[name] = graph
		return graph

	def drop_graph(self, name: str, cascade: bool = True) -> None:
		"""Delete a graph and all its data.

		Args:
		    name: Graph name to drop.
		    cascade: If True, also delete all vertices and edges (default: True).
		"""
		cascade_str = "true" if cascade else "false"
		with self.engine.connect() as conn:
			conn.execute(text("LOAD 'age'"))
			conn.execute(text("SET search_path = ag_catalog, \"$user\", public"))
			conn.execute(text(f"SELECT drop_graph('{name}', {cascade_str})"))
			conn.commit()
		self._graphs.pop(name, None)
		log.info("Dropped AGE graph: %s", name)

	def graph(self, name: str) -> AGEGraph:
		"""Get a handle to an existing graph.

		Does NOT verify the graph exists — call create_graph() to be safe.
		"""
		if name not in self._graphs:
			self._graphs[name] = AGEGraph(self.engine, name)
		return self._graphs[name]

	def list_graphs(self) -> list[dict[str, Any]]:
		"""Return metadata for all AGE graphs in the database.

		Returns a list of dicts with keys: name, namespace, creation_date.
		"""
		with self.engine.connect() as conn:
			conn.execute(text("LOAD 'age'"))
			conn.execute(text("SET search_path = ag_catalog, \"$user\", public"))
			try:
				result = conn.execute(
					text("SELECT name, namespace FROM ag_catalog.ag_graph")
				)
				return [{"name": row.name, "namespace": row.namespace} for row in result]
			except Exception as exc:
				log.warning("Could not list AGE graphs: %s", exc)
				return []

	def graph_exists(self, name: str) -> bool:
		"""Return True if the named graph exists."""
		graphs = self.list_graphs()
		return any(g["name"] == name for g in graphs)

	def graph_stats(self, name: str) -> dict[str, int]:
		"""Return vertex and edge counts for a graph."""
		g = self.graph(name)
		try:
			v_count = g.count()
			e_rows = g.cypher("MATCH ()-[e]->() RETURN count(e) AS c")
			e_count = int(e_rows[0].get("c", 0)) if e_rows else 0
			return {"vertices": v_count, "edges": e_count}
		except Exception:
			return {"vertices": 0, "edges": 0}

	def execute_cypher(self, graph_name: str, cypher: str,
	                   params: dict | None = None) -> list[dict]:
		"""Convenience: create graph handle and execute Cypher in one call."""
		return self.graph(graph_name).cypher(cypher, params)
