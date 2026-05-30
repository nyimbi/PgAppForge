"""
Graph analytics for Apache AGE — community detection, centrality, anomaly detection.

All algorithms run on a networkx in-memory copy of the AGE graph, so they work
regardless of graph size (up to a few million nodes) without requiring any
PostgreSQL graph extensions beyond AGE itself.

Usage::

    from pgappforge.database.age import AGEManager
    from pgappforge.database.age.analytics import AGEAnalytics

    mgr = AGEManager(engine)
    analytics = AGEAnalytics(mgr.graph('social'))

    # Community detection
    communities = analytics.community_detection('louvain')  # {vertex_id: community_id}

    # Centrality
    scores = analytics.centrality('pagerank')  # {vertex_id: float}

    # Graph stats
    print(analytics.density(), analytics.clustering_coefficient())
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _require_networkx():
	try:
		import networkx as nx
		return nx
	except ImportError:
		raise RuntimeError(
			"networkx is required for graph analytics. "
			"Install with: pip install networkx"
		)


class AGEAnalytics:
	"""Graph analytics on an Apache AGE graph.

	Args:
	    graph: An AGEGraph instance.
	"""

	def __init__(self, graph) -> None:
		self.graph = graph
		self._nx_cache: Any = None

	def to_networkx(self, label_filter: str | None = None) -> Any:
		"""Pull the AGE graph into networkx for algorithm execution.

		Args:
		    label_filter: If given, only include vertices with this label.

		Returns:
		    networkx.DiGraph
		"""
		nx = _require_networkx()
		from pgappforge.database.age.types import Vertex, Edge, Path

		if label_filter:
			rows = self.graph.cypher(
				f"MATCH (n:{label_filter})-[e]->(m:{label_filter}) RETURN n, e, m LIMIT 50000"
			)
		else:
			rows = self.graph.cypher(
				"MATCH (n)-[e]->(m) RETURN n, e, m LIMIT 50000"
			)

		g = nx.DiGraph()
		for row in rows:
			for val in row.values():
				if isinstance(val, Vertex):
					g.add_node(val.id, label=val.label, **val.properties)
				elif isinstance(val, Edge):
					g.add_edge(val.start_id, val.end_id, label=val.label, id=val.id,
					           **val.properties)

		self._nx_cache = g
		return g

	def _get_nx(self) -> Any:
		return self._nx_cache or self.to_networkx()

	def community_detection(
		self, algorithm: str = "louvain"
	) -> dict[int, int]:
		"""Detect communities in the graph.

		Args:
		    algorithm: "louvain" | "label_propagation" | "girvan_newman"

		Returns:
		    {vertex_id: community_id} — 0-indexed integer community labels.
		"""
		nx = _require_networkx()
		g = self._get_nx()
		ug = g.to_undirected()

		if algorithm == "louvain":
			try:
				import community as community_louvain
				partition = community_louvain.best_partition(ug)
				return {int(k): int(v) for k, v in partition.items()}
			except ImportError:
				log.warning("python-louvain not installed — falling back to label_propagation")
				algorithm = "label_propagation"

		if algorithm == "label_propagation":
			import networkx.algorithms.community as nx_comm
			communities = nx_comm.label_propagation_communities(ug)
			result = {}
			for cid, comm in enumerate(communities):
				for node in comm:
					result[int(node)] = cid
			return result

		if algorithm == "girvan_newman":
			import networkx.algorithms.community as nx_comm
			comp = nx_comm.girvan_newman(ug)
			communities = next(comp)  # first split
			result = {}
			for cid, comm in enumerate(communities):
				for node in comm:
					result[int(node)] = cid
			return result

		raise ValueError(f"Unknown algorithm: {algorithm!r}. "
		                 f"Options: louvain, label_propagation, girvan_newman")

	def centrality(self, metric: str = "pagerank") -> dict[int, float]:
		"""Compute vertex centrality scores.

		Args:
		    metric: "pagerank" | "betweenness" | "closeness" | "eigenvector" | "degree"

		Returns:
		    {vertex_id: score} — higher = more central.
		"""
		nx = _require_networkx()
		g = self._get_nx()

		metrics = {
			"pagerank": lambda: nx.pagerank(g, alpha=0.85),
			"betweenness": lambda: nx.betweenness_centrality(g),
			"closeness": lambda: nx.closeness_centrality(g),
			"eigenvector": lambda: nx.eigenvector_centrality(g, max_iter=500),
			"degree": lambda: {n: float(d) for n, d in g.degree()},
		}

		if metric not in metrics:
			raise ValueError(f"Unknown metric: {metric!r}. Options: {list(metrics)}")

		scores = metrics[metric]()
		return {int(k): float(v) for k, v in scores.items()}

	def shortest_path(self, from_vertex_id: int, to_vertex_id: int) -> list[int]:
		"""Find the shortest path between two vertices.

		Returns:
		    Ordered list of vertex IDs on the shortest path.
		    Empty list if no path exists.
		"""
		nx = _require_networkx()
		g = self._get_nx()
		try:
			path = nx.shortest_path(g, source=from_vertex_id, target=to_vertex_id)
			return [int(v) for v in path]
		except nx.NetworkXNoPath:
			return []
		except nx.NodeNotFound:
			return []

	def density(self) -> float:
		"""Return graph density (0 = sparse, 1 = complete)."""
		nx = _require_networkx()
		return nx.density(self._get_nx())

	def clustering_coefficient(self) -> float:
		"""Return average clustering coefficient."""
		nx = _require_networkx()
		ug = self._get_nx().to_undirected()
		return nx.average_clustering(ug)

	def connected_components(self) -> list[list[int]]:
		"""Return weakly connected components as lists of vertex IDs."""
		nx = _require_networkx()
		g = self._get_nx()
		comps = nx.weakly_connected_components(g)
		return [[int(n) for n in comp] for comp in comps]

	def anomaly_scores(self, method: str = "isolation_forest") -> dict[int, float]:
		"""Score each vertex for anomaly (higher = more anomalous).

		Uses degree + clustering features with IsolationForest.

		Args:
		    method: Currently only "isolation_forest".
		"""
		try:
			from sklearn.ensemble import IsolationForest
			import numpy as np
		except ImportError:
			raise RuntimeError("scikit-learn + numpy required: pip install scikit-learn numpy")

		nx = _require_networkx()
		g = self._get_nx().to_undirected()
		nodes = list(g.nodes())
		if not nodes:
			return {}

		degree = dict(g.degree())
		clust = nx.clustering(g)

		X = np.array([[degree.get(n, 0), clust.get(n, 0)] for n in nodes])

		clf = IsolationForest(contamination=0.1, random_state=42)
		scores = clf.fit_predict(X)
		# Convert: -1 = anomaly, 1 = normal → invert to 0-1 score
		decision = clf.decision_function(X)
		normalized = 1.0 - (decision - decision.min()) / (decision.max() - decision.min() + 1e-9)

		return {int(n): float(s) for n, s in zip(nodes, normalized)}

	def summary(self) -> dict[str, Any]:
		"""Return a comprehensive summary of graph properties."""
		g = self._get_nx()
		nx = _require_networkx()
		return {
			"node_count": g.number_of_nodes(),
			"edge_count": g.number_of_edges(),
			"density": self.density(),
			"is_directed": g.is_directed(),
			"weakly_connected_components": nx.number_weakly_connected_components(g),
			"average_degree": (
				sum(d for _, d in g.degree()) / max(g.number_of_nodes(), 1)
			),
		}
