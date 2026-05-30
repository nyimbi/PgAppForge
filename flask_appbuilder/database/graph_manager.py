"""
Apache AGE Graph Database Manager

Provides comprehensive graph analysis, visualization, and management capabilities
for PostgreSQL AGE extension with OpenCypher query support.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict
from enum import Enum
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)


class GraphElementType(Enum):
    """Types of graph elements"""
    NODE = "node"
    EDGE = "edge" 
    PATH = "path"


class GraphAlgorithmType(Enum):
    """Available graph algorithms"""
    SHORTEST_PATH = "shortest_path"
    CENTRALITY = "centrality"
    PAGERANK = "pagerank"
    COMMUNITY_DETECTION = "community_detection"
    CLUSTERING = "clustering"
    CONNECTED_COMPONENTS = "connected_components"
    TRAVERSAL = "traversal"
    SIMILARITY = "similarity"


@dataclass
class GraphNode:
    """
    Represents a graph node with properties
    
    Attributes:
        id: Unique node identifier
        label: Node type/label
        properties: Dictionary of node properties
        position: Visual position coordinates
        group: Community/cluster group
        degree: Number of connections
        centrality: Node centrality score
    """
    
    id: str
    label: str
    properties: Dict[str, Any]
    position: Optional[Dict[str, float]] = None
    group: Optional[str] = None
    degree: int = 0
    centrality: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary for serialization"""
        return {
            "id": self.id,
            "label": self.label,
            "properties": self.properties,
            "position": self.position,
            "group": self.group,
            "degree": self.degree,
            "centrality": self.centrality
        }


@dataclass
class GraphEdge:
    """
    Represents a graph edge with properties
    
    Attributes:
        id: Unique edge identifier
        source: Source node ID
        target: Target node ID
        label: Edge type/label
        properties: Dictionary of edge properties
        weight: Edge weight for algorithms
        directed: Whether edge is directed
    """
    
    id: str
    source: str
    target: str
    label: str
    properties: Dict[str, Any]
    weight: float = 1.0
    directed: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert edge to dictionary for serialization"""
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "label": self.label,
            "properties": self.properties,
            "weight": self.weight,
            "directed": self.directed
        }


@dataclass
class GraphPath:
    """
    Represents a graph path
    
    Attributes:
        id: Path identifier
        nodes: List of node IDs in path
        edges: List of edge IDs in path
        length: Path length
        cost: Total path cost/weight
        properties: Path metadata
    """
    
    id: str
    nodes: List[str]
    edges: List[str]
    length: int
    cost: float = 0.0
    properties: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert path to dictionary for serialization"""
        return {
            "id": self.id,
            "nodes": self.nodes,
            "edges": self.edges,
            "length": self.length,
            "cost": self.cost,
            "properties": self.properties or {}
        }


@dataclass
class GraphSchema:
    """
    Graph schema information
    
    Attributes:
        name: Graph name
        node_labels: Available node labels
        edge_labels: Available edge labels
        node_properties: Node property schemas
        edge_properties: Edge property schemas
        statistics: Graph statistics
    """
    
    name: str
    node_labels: List[str]
    edge_labels: List[str]
    node_properties: Dict[str, List[str]]
    edge_properties: Dict[str, List[str]]
    statistics: Dict[str, int]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert schema to dictionary for serialization"""
        return asdict(self)


class GraphDatabaseManager:
    """
    Comprehensive Apache AGE graph database management system
    
    Provides graph analysis, visualization, querying, and algorithm execution
    capabilities for PostgreSQL AGE extension.
    """
    
    def __init__(self, database_uri: str = None, graph_name: str = "default_graph"):
        """
        Initialize graph database manager
        
        Args:
            database_uri: PostgreSQL database connection URI
            graph_name: Name of the graph to work with
        """
        self.database_uri = database_uri
        self.graph_name = graph_name
        self.engine = None
        self._initialize_connection()
        self._ensure_age_extension()
        self._create_graph_if_not_exists()
        
    def _initialize_connection(self):
        """Initialize database connection"""
        try:
            if self.database_uri:
                self.engine = create_engine(self.database_uri)
            else:
                # Try to get from Flask app context
                from flask import current_app
                
                if current_app and hasattr(current_app, "extensions"):
                    if "sqlalchemy" in current_app.extensions:
                        self.engine = current_app.extensions["sqlalchemy"].db.engine
            
            if self.engine:
                logger.info("Graph database manager initialized successfully")
            else:
                logger.warning("No database connection available for graph operations")
                
        except Exception as e:
            logger.error(f"Failed to initialize graph database manager: {e}")
            
    def _ensure_age_extension(self):
        """Ensure Apache AGE extension is installed and loaded"""
        if not self.engine:
            return
            
        try:
            with self.engine.begin() as conn:
                # Check if AGE extension is installed
                result = conn.execute(text(
                    "SELECT * FROM pg_extension WHERE extname = 'age'"
                ))
                
                if not result.fetchone():
                    # Create AGE extension
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS age"))
                    logger.info("Apache AGE extension created")
                
                # Load AGE into search path
                conn.execute(text("LOAD 'age'"))
                conn.execute(text("SET search_path = ag_catalog, '$user', public"))
                
                logger.info("Apache AGE extension loaded successfully")
                
        except Exception as e:
            logger.error(f"Failed to ensure AGE extension: {e}")
            
    def _create_graph_if_not_exists(self):
        """Create graph if it doesn't exist"""
        if not self.engine:
            return
            
        try:
            with self.engine.begin() as conn:
                # Check if graph exists
                result = conn.execute(text(
                    "SELECT * FROM ag_catalog.ag_graph WHERE name = :graph_name"
                ), {"graph_name": self.graph_name})
                
                if not result.fetchone():
                    # Create graph
                    conn.execute(text(f"SELECT create_graph('{self.graph_name}')"))
                    logger.info(f"Created graph: {self.graph_name}")
                    
        except Exception as e:
            logger.error(f"Failed to create graph: {e}")
    
    def execute_cypher_query(self, query: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute OpenCypher query using Apache AGE
        
        Args:
            query: OpenCypher query string
            parameters: Query parameters
            
        Returns:
            Dictionary containing query results and metadata
        """
        if not self.engine:
            return {"success": False, "error": "No database connection available"}
        
        try:
            with self.engine.connect() as conn:
                # Format AGE cypher query
                age_query = f"""
                SELECT * FROM cypher('{self.graph_name}', $$
                {query}
                $$) as (result agtype)
                """
                
                result = conn.execute(text(age_query), parameters or {})
                rows = result.fetchall()
                
                # Parse AGE results
                parsed_results = []
                for row in rows:
                    try:
                        # AGE returns results as agtype JSON
                        parsed_data = json.loads(row[0]) if row[0] else None
                        parsed_results.append(parsed_data)
                    except (json.JSONDecodeError, TypeError):
                        parsed_results.append(str(row[0]))
                
                return {
                    "success": True,
                    "results": parsed_results,
                    "count": len(parsed_results),
                    "query": query,
                    "execution_time": datetime.now(tz=timezone.utc).isoformat()
                }
                
        except Exception as e:
            logger.error(f"Cypher query execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query
            }
    
    def get_graph_schema(self) -> GraphSchema:
        """
        Get comprehensive graph schema information
        
        Returns:
            GraphSchema object with detailed schema information
        """
        try:
            # Get node labels
            node_query = "MATCH (n) RETURN DISTINCT labels(n) as labels, count(n) as count"
            node_result = self.execute_cypher_query(node_query)
            
            node_labels = []
            node_counts = {}
            if node_result["success"]:
                for item in node_result["results"]:
                    if item and isinstance(item, list) and len(item) > 0:
                        label = item[0] if item[0] else "unlabeled"
                        node_labels.append(label)
                        node_counts[label] = item[1] if len(item) > 1 else 0
            
            # Get edge labels
            edge_query = "MATCH ()-[r]->() RETURN DISTINCT type(r) as type, count(r) as count"
            edge_result = self.execute_cypher_query(edge_query)
            
            edge_labels = []
            edge_counts = {}
            if edge_result["success"]:
                for item in edge_result["results"]:
                    if item and isinstance(item, list) and len(item) > 0:
                        label = item[0] if item[0] else "unlabeled"
                        edge_labels.append(label)
                        edge_counts[label] = item[1] if len(item) > 1 else 0
            
            # Get node properties for each label
            node_properties = {}
            for label in node_labels:
                prop_query = f"MATCH (n:{label}) RETURN keys(n) as properties LIMIT 100"
                prop_result = self.execute_cypher_query(prop_query)
                
                properties = set()
                if prop_result["success"]:
                    for item in prop_result["results"]:
                        if item and isinstance(item, list):
                            properties.update(item)
                
                node_properties[label] = list(properties)
            
            # Get edge properties for each label
            edge_properties = {}
            for label in edge_labels:
                prop_query = f"MATCH ()-[r:{label}]->() RETURN keys(r) as properties LIMIT 100"
                prop_result = self.execute_cypher_query(prop_query)
                
                properties = set()
                if prop_result["success"]:
                    for item in prop_result["results"]:
                        if item and isinstance(item, list):
                            properties.update(item)
                
                edge_properties[label] = list(properties)
            
            # Calculate statistics
            total_nodes = sum(node_counts.values())
            total_edges = sum(edge_counts.values())
            
            statistics = {
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "node_labels_count": len(node_labels),
                "edge_labels_count": len(edge_labels),
                "density": (total_edges / (total_nodes * (total_nodes - 1))) if total_nodes > 1 else 0
            }
            statistics.update(node_counts)
            statistics.update({f"edge_{k}": v for k, v in edge_counts.items()})
            
            return GraphSchema(
                name=self.graph_name,
                node_labels=node_labels,
                edge_labels=edge_labels,
                node_properties=node_properties,
                edge_properties=edge_properties,
                statistics=statistics
            )
            
        except Exception as e:
            logger.error(f"Failed to get graph schema: {e}")
            return GraphSchema(
                name=self.graph_name,
                node_labels=[],
                edge_labels=[],
                node_properties={},
                edge_properties={},
                statistics={}
            )
    
    def get_graph_data(self, limit: int = 1000, node_filter: str = None, edge_filter: str = None) -> Dict[str, Any]:
        """
        Get graph data for visualization
        
        Args:
            limit: Maximum number of nodes to return
            node_filter: Optional node filter query
            edge_filter: Optional edge filter query
            
        Returns:
            Dictionary with nodes, edges, and metadata
        """
        try:
            nodes = []
            edges = []
            
            # Get nodes
            node_query = f"MATCH (n) RETURN n LIMIT {limit}"
            if node_filter:
                node_query = f"MATCH (n) WHERE {node_filter} RETURN n LIMIT {limit}"
                
            node_result = self.execute_cypher_query(node_query)
            
            if node_result["success"]:
                for item in node_result["results"]:
                    if item and isinstance(item, dict):
                        # Extract node information
                        node_id = item.get("id", str(len(nodes)))
                        label = item.get("label", "Node")
                        properties = {k: v for k, v in item.items() if k not in ["id", "label"]}
                        
                        node = GraphNode(
                            id=node_id,
                            label=label,
                            properties=properties
                        )
                        nodes.append(node)
            
            # Get edges for the retrieved nodes
            if nodes:
                node_ids = [f"'{node.id}'" for node in nodes[:100]]  # Limit for performance
                edge_query = f"""
                MATCH (a)-[r]->(b) 
                WHERE id(a) IN [{','.join(node_ids)}] OR id(b) IN [{','.join(node_ids)}]
                RETURN r, id(a) as source, id(b) as target
                LIMIT {limit}
                """
                
                if edge_filter:
                    edge_query = f"""
                    MATCH (a)-[r]->(b) 
                    WHERE ({edge_filter}) AND (id(a) IN [{','.join(node_ids)}] OR id(b) IN [{','.join(node_ids)}])
                    RETURN r, id(a) as source, id(b) as target
                    LIMIT {limit}
                    """
                
                edge_result = self.execute_cypher_query(edge_query)
                
                if edge_result["success"]:
                    for item in edge_result["results"]:
                        if item and isinstance(item, list) and len(item) >= 3:
                            edge_data = item[0] if isinstance(item[0], dict) else {}
                            source_id = str(item[1])
                            target_id = str(item[2])
                            
                            edge_id = edge_data.get("id", f"{source_id}_{target_id}")
                            label = edge_data.get("label", "RELATED")
                            properties = {k: v for k, v in edge_data.items() if k not in ["id", "label"]}
                            
                            edge = GraphEdge(
                                id=edge_id,
                                source=source_id,
                                target=target_id,
                                label=label,
                                properties=properties
                            )
                            edges.append(edge)
            
            return {
                "success": True,
                "nodes": [node.to_dict() for node in nodes],
                "edges": [edge.to_dict() for edge in edges],
                "metadata": {
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "limited": len(nodes) == limit,
                    "graph_name": self.graph_name
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get graph data: {e}")
            return {
                "success": False,
                "error": str(e),
                "nodes": [],
                "edges": [],
                "metadata": {}
            }
    
    def find_shortest_path(self, start_node: str, end_node: str, max_length: int = 10) -> Dict[str, Any]:
        """
        Find shortest path between two nodes
        
        Args:
            start_node: Starting node ID
            end_node: Ending node ID
            max_length: Maximum path length to search
            
        Returns:
            Dictionary with path information
        """
        try:
            query = f"""
            MATCH path = shortestPath((start)-[*1..{max_length}]->(end))
            WHERE id(start) = '{start_node}' AND id(end) = '{end_node}'
            RETURN path, length(path) as length
            """
            
            result = self.execute_cypher_query(query)
            
            if result["success"] and result["results"]:
                path_data = result["results"][0]
                
                if path_data and isinstance(path_data, list) and len(path_data) >= 2:
                    path_info = path_data[0]
                    length = path_data[1]
                    
                    # Extract nodes and edges from path
                    nodes = []
                    edges = []
                    
                    if isinstance(path_info, dict) and "nodes" in path_info:
                        nodes = [str(node_id) for node_id in path_info["nodes"]]
                    
                    if isinstance(path_info, dict) and "edges" in path_info:
                        edges = [str(edge_id) for edge_id in path_info["edges"]]
                    
                    path = GraphPath(
                        id=f"path_{start_node}_{end_node}",
                        nodes=nodes,
                        edges=edges,
                        length=length,
                        properties={"algorithm": "shortest_path"}
                    )
                    
                    return {
                        "success": True,
                        "path": path.to_dict(),
                        "found": True
                    }
            
            return {
                "success": True,
                "path": None,
                "found": False,
                "message": f"No path found between {start_node} and {end_node}"
            }
            
        except Exception as e:
            logger.error(f"Shortest path calculation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "path": None,
                "found": False
            }
    
    def calculate_centrality(self, algorithm: str = "betweenness", limit: int = 100) -> Dict[str, Any]:
        """
        Calculate node centrality using specified algorithm
        
        Args:
            algorithm: Centrality algorithm (betweenness, closeness, degree, eigenvector)
            limit: Maximum number of nodes to analyze
            
        Returns:
            Dictionary with centrality scores
        """
        try:
            # Get graph data for analysis
            graph_data = self.get_graph_data(limit=limit)
            
            if not graph_data["success"]:
                return graph_data
            
            nodes = graph_data["nodes"]
            edges = graph_data["edges"]
            
            if not nodes:
                return {"success": True, "centrality": {}, "algorithm": algorithm}
            
            # Create NetworkX graph for algorithm execution
            G = nx.DiGraph() if any(edge.get("directed", True) for edge in edges) else nx.Graph()
            
            # Add nodes
            for node in nodes:
                G.add_node(node["id"], **node["properties"])
            
            # Add edges
            for edge in edges:
                weight = edge.get("weight", 1.0)
                G.add_edge(edge["source"], edge["target"], weight=weight, **edge["properties"])
            
            # Calculate centrality
            centrality_scores = {}
            
            if algorithm == "betweenness":
                centrality_scores = nx.betweenness_centrality(G)
            elif algorithm == "closeness":
                centrality_scores = nx.closeness_centrality(G)
            elif algorithm == "degree":
                centrality_scores = nx.degree_centrality(G)
            elif algorithm == "eigenvector":
                try:
                    centrality_scores = nx.eigenvector_centrality(G, max_iter=1000)
                except nx.PowerIterationFailedConvergence:
                    centrality_scores = nx.eigenvector_centrality_numpy(G)
            elif algorithm == "pagerank":
                centrality_scores = nx.pagerank(G)
            else:
                return {
                    "success": False,
                    "error": f"Unknown centrality algorithm: {algorithm}"
                }
            
            # Sort by centrality score
            sorted_centrality = sorted(
                centrality_scores.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            return {
                "success": True,
                "centrality": dict(sorted_centrality),
                "algorithm": algorithm,
                "top_nodes": sorted_centrality[:20],  # Top 20 nodes
                "statistics": {
                    "mean": np.mean(list(centrality_scores.values())),
                    "std": np.std(list(centrality_scores.values())),
                    "max": max(centrality_scores.values()),
                    "min": min(centrality_scores.values())
                }
            }
            
        except Exception as e:
            logger.error(f"Centrality calculation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "algorithm": algorithm
            }
    
    def detect_communities(self, algorithm: str = "louvain", resolution: float = 1.0) -> Dict[str, Any]:
        """
        Detect communities in the graph
        
        Args:
            algorithm: Community detection algorithm
            resolution: Resolution parameter for algorithms
            
        Returns:
            Dictionary with community information
        """
        try:
            # Get graph data
            graph_data = self.get_graph_data()
            
            if not graph_data["success"]:
                return graph_data
            
            nodes = graph_data["nodes"]
            edges = graph_data["edges"]
            
            # Create NetworkX graph
            G = nx.Graph()  # Use undirected for community detection
            
            for node in nodes:
                G.add_node(node["id"], **node["properties"])
            
            for edge in edges:
                weight = edge.get("weight", 1.0)
                G.add_edge(edge["source"], edge["target"], weight=weight)
            
            # Detect communities
            communities = {}
            
            if algorithm == "louvain":
                try:
                    import community as community_louvain
                    partition = community_louvain.best_partition(G, resolution=resolution)
                    communities = partition
                except ImportError:
                    # Fallback to basic connected components
                    components = list(nx.connected_components(G))
                    for i, component in enumerate(components):
                        for node in component:
                            communities[node] = i
            else:
                # Default to connected components
                components = list(nx.connected_components(G))
                for i, component in enumerate(components):
                    for node in component:
                        communities[node] = i
            
            # Analyze communities
            community_stats = {}
            for node_id, community_id in communities.items():
                if community_id not in community_stats:
                    community_stats[community_id] = {"nodes": [], "size": 0}
                community_stats[community_id]["nodes"].append(node_id)
                community_stats[community_id]["size"] += 1
            
            return {
                "success": True,
                "communities": communities,
                "community_stats": community_stats,
                "algorithm": algorithm,
                "num_communities": len(community_stats),
                "modularity": nx.algorithms.community.modularity(
                    G, [set(stats["nodes"]) for stats in community_stats.values()]
                ) if community_stats else 0
            }
            
        except Exception as e:
            logger.error(f"Community detection failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "algorithm": algorithm
            }
    
    def search_nodes(self, search_term: str, search_fields: List[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Search for nodes based on properties
        
        Args:
            search_term: Search term
            search_fields: Fields to search in
            limit: Maximum results to return
            
        Returns:
            Dictionary with search results
        """
        try:
            # Build search query
            if search_fields:
                conditions = []
                for field in search_fields:
                    conditions.append(f"toLower(toString(n.{field})) CONTAINS toLower('{search_term}')")
                where_clause = " OR ".join(conditions)
            else:
                # Search in all string properties
                where_clause = f"""
                ANY(key IN keys(n) WHERE toLower(toString(n[key])) CONTAINS toLower('{search_term}'))
                """
            
            query = f"""
            MATCH (n)
            WHERE {where_clause}
            RETURN n, labels(n) as labels, id(n) as node_id
            LIMIT {limit}
            """
            
            result = self.execute_cypher_query(query)
            
            if result["success"]:
                search_results = []
                for item in result["results"]:
                    if item and isinstance(item, list) and len(item) >= 3:
                        node_data = item[0] if isinstance(item[0], dict) else {}
                        labels = item[1] if isinstance(item[1], list) else []
                        node_id = str(item[2])
                        
                        node = GraphNode(
                            id=node_id,
                            label=labels[0] if labels else "Node",
                            properties=node_data
                        )
                        search_results.append(node.to_dict())
                
                return {
                    "success": True,
                    "results": search_results,
                    "count": len(search_results),
                    "search_term": search_term,
                    "limited": len(search_results) == limit
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"Node search failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "results": [],
                "count": 0,
                "search_term": search_term
            }
    
    def get_node_neighbors(self, node_id: str, depth: int = 1, direction: str = "both") -> Dict[str, Any]:
        """
        Get neighbors of a specific node
        
        Args:
            node_id: Target node ID
            depth: Traversal depth
            direction: Direction (in, out, both)
            
        Returns:
            Dictionary with neighbor information
        """
        try:
            # Build traversal query based on direction
            if direction == "out":
                pattern = f"(n)-[r*1..{depth}]->(m)"
            elif direction == "in":
                pattern = f"(m)-[r*1..{depth}]->(n)"
            else:  # both
                pattern = f"(n)-[r*1..{depth}]-(m)"
            
            query = f"""
            MATCH {pattern}
            WHERE id(n) = '{node_id}'
            RETURN DISTINCT m, labels(m) as labels, id(m) as neighbor_id, 
                   length(r) as distance
            ORDER BY distance
            """
            
            result = self.execute_cypher_query(query)
            
            if result["success"]:
                neighbors = []
                for item in result["results"]:
                    if item and isinstance(item, list) and len(item) >= 4:
                        node_data = item[0] if isinstance(item[0], dict) else {}
                        labels = item[1] if isinstance(item[1], list) else []
                        neighbor_id = str(item[2])
                        distance = item[3]
                        
                        neighbor = GraphNode(
                            id=neighbor_id,
                            label=labels[0] if labels else "Node",
                            properties=node_data
                        )
                        neighbor_dict = neighbor.to_dict()
                        neighbor_dict["distance"] = distance
                        neighbors.append(neighbor_dict)
                
                return {
                    "success": True,
                    "node_id": node_id,
                    "neighbors": neighbors,
                    "count": len(neighbors),
                    "depth": depth,
                    "direction": direction
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"Failed to get node neighbors: {e}")
            return {
                "success": False,
                "error": str(e),
                "node_id": node_id,
                "neighbors": [],
                "count": 0
            }


# Global graph manager instance
_graph_manager = None


def get_graph_manager(database_uri: str = None, graph_name: str = "default_graph") -> GraphDatabaseManager:
    """Get or create the global graph manager instance"""
    global _graph_manager
    if _graph_manager is None or (database_uri and _graph_manager.database_uri != database_uri):
        _graph_manager = GraphDatabaseManager(database_uri, graph_name)
    return _graph_manager