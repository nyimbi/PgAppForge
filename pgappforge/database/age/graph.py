"""
AGEGraph — execute OpenCypher queries against a named Apache AGE graph.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from sqlalchemy import text
from sqlalchemy.engine import Engine, Connection

from .types import Vertex, Edge, Path

log = logging.getLogger(__name__)


def _parse_agtype(value: str) -> Any:
	"""Parse an AGE agtype string into a Python object."""
	if value is None:
		return None
	if not isinstance(value, str):
		return value
	try:
		# AGE adds type suffixes like "::vertex", "::edge", "::path"
		if value.endswith("::vertex"):
			raw = json.loads(value[: -len("::vertex")])
			return Vertex.from_agtype(raw)
		if value.endswith("::edge"):
			raw = json.loads(value[: -len("::edge")])
			return Edge.from_agtype(raw)
		# Plain JSON
		return json.loads(value)
	except (json.JSONDecodeError, ValueError):
		return value


class AGEGraph:
	"""Executes OpenCypher queries against an Apache AGE graph.

	Manages the PostgreSQL session preamble required by AGE:
	  ``SET search_path = ag_catalog, "$user", public``
	  ``LOAD 'age'``

	Args:
	    engine: SQLAlchemy Engine pointing to a PostgreSQL+AGE database.
	    graph_name: Name of the AGE graph (created with ``CREATE GRAPH``).

	Usage::

	    graph = AGEGraph(engine, 'social')
	    for row in graph.cypher('MATCH (n:Person) RETURN n.name LIMIT 10'):
	        print(row['n.name'])
	"""

	def __init__(self, engine: Engine, graph_name: str) -> None:
		self.engine = engine
		self.graph_name = graph_name

	def _execute(self, conn: Connection, cypher: str, params: dict | None = None) -> list[dict]:
		"""Execute a Cypher query and return rows as dicts."""
		# AGE requires these session-level settings
		conn.execute(text("LOAD 'age'"))
		conn.execute(text("SET search_path = ag_catalog, \"$user\", public"))

		# Wrap cypher in the ag_catalog.cypher() function call
		# Parameters are injected as PostgreSQL-side JSON to avoid SQL injection
		if params:
			param_json = json.dumps(params)
			stmt = text(
				f"SELECT * FROM cypher(:graph, $$ {cypher} $$, :params) AS (result agtype)"
			)
			result = conn.execute(stmt, {"graph": self.graph_name, "params": param_json})
		else:
			stmt = text(
				f"SELECT * FROM cypher(:graph, $$ {cypher} $$) AS (result agtype)"
			)
			result = conn.execute(stmt, {"graph": self.graph_name})

		rows = []
		for row in result:
			parsed = {}
			for key, val in row._mapping.items():
				parsed[key] = _parse_agtype(val)
			rows.append(parsed)
		return rows

	def cypher(self, query: str, params: dict | None = None) -> list[dict]:
		"""Execute an OpenCypher query and return all rows.

		Args:
		    query: OpenCypher query string (no graph name prefix).
		    params: Optional dict of query parameters (``$name`` style in Cypher).

		Returns:
		    List of result row dicts with parsed AGE types.

		Example::

		    rows = graph.cypher(
		        'MATCH (p:Person {name: $name})-[:KNOWS]->(f) RETURN f',
		        params={'name': 'Alice'}
		    )
		"""
		with self.engine.connect() as conn:
			try:
				rows = self._execute(conn, query, params)
				conn.commit()
				return rows
			except Exception as exc:
				conn.rollback()
				log.error("Cypher query failed on graph %r: %s", self.graph_name, exc)
				raise

	def cypher_iter(self, query: str, params: dict | None = None) -> Iterator[dict]:
		"""Stream results row by row (useful for large result sets)."""
		with self.engine.connect() as conn:
			for row in self._execute(conn, query, params):
				yield row

	def create_vertex(self, label: str, properties: dict) -> Vertex:
		"""Create a single vertex and return it."""
		rows = self.cypher(
			f"CREATE (v:{label} $props) RETURN v",
			params={"props": properties},
		)
		if rows:
			return rows[0].get("v") or Vertex(0, label, properties)
		return Vertex(0, label, properties)

	def create_edge(
		self,
		from_label: str,
		from_where: dict,
		rel_type: str,
		to_label: str,
		to_where: dict,
		properties: dict | None = None,
	) -> Edge | None:
		"""Create an edge between two matched vertices."""
		props = properties or {}
		match_clause = (
			f"MATCH (a:{from_label}), (b:{to_label}) "
			f"WHERE a.{list(from_where)[0]} = $fv AND b.{list(to_where)[0]} = $tv "
			f"CREATE (a)-[e:{rel_type} $props]->(b) RETURN e"
		)
		rows = self.cypher(
			match_clause,
			params={
				"fv": list(from_where.values())[0],
				"tv": list(to_where.values())[0],
				"props": props,
			},
		)
		if rows:
			return rows[0].get("e")
		return None

	def count(self, label: str | None = None) -> int:
		"""Count nodes, optionally filtered by label."""
		if label:
			rows = self.cypher(f"MATCH (n:{label}) RETURN count(n) AS c")
		else:
			rows = self.cypher("MATCH (n) RETURN count(n) AS c")
		return int(rows[0].get("c", 0)) if rows else 0

	def drop_label(self, label: str) -> None:
		"""Delete all vertices with the given label."""
		self.cypher(f"MATCH (n:{label}) DETACH DELETE n")

	def schema(self) -> dict[str, list[str]]:
		"""Return a rough schema: {label: [property_keys]}."""
		rows = self.cypher(
			"MATCH (n) RETURN DISTINCT labels(n) AS labels, keys(n) AS props LIMIT 500"
		)
		schema: dict[str, set] = {}
		for row in rows:
			lbls = row.get("labels") or []
			props = row.get("props") or []
			for lbl in (lbls if isinstance(lbls, list) else [lbls]):
				schema.setdefault(lbl, set()).update(props)
		return {k: sorted(v) for k, v in schema.items()}
