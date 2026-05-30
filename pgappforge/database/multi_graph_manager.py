"""
Multi-Graph Management System

Provides comprehensive management of multiple graph databases, graph comparison,
temporal analysis, and cross-graph operations with unified interface.
"""

import json
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Union, Set
from dataclasses import dataclass, asdict, field
from enum import Enum
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import networkx as nx
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .graph_manager import (
    GraphDatabaseManager,
    get_graph_manager,
    GraphSchema,
    GraphNode,
    GraphEdge
)
from .activity_tracker import track_database_activity, ActivityType

logger = logging.getLogger(__name__)


class GraphOperationType(Enum):
	"""Types of multi-graph operations"""
	UNION = "union"
	INTERSECTION = "intersection"
	DIFFERENCE = "difference"
	MERGE = "merge"
	COMPARE = "compare"
	TEMPORAL_ANALYSIS = "temporal_analysis"
	CROSS_QUERY = "cross_query"


class GraphVersionType(Enum):
	"""Graph version types"""
	SNAPSHOT = "snapshot"
	INCREMENTAL = "incremental"
	CHECKPOINT = "checkpoint"
	BACKUP = "backup"


@dataclass
class GraphMetadata:
	"""
	Graph metadata information
	
	Attributes:
		name: Graph name
		description: Graph description
		created_at: Creation timestamp
		updated_at: Last update timestamp
		version: Graph version
		tags: Metadata tags
		properties: Additional properties
		schema_hash: Schema fingerprint
		statistics: Graph statistics
		connections: Connected graphs
	"""
	
	name: str
	description: str
	created_at: datetime
	updated_at: datetime
	version: str = "1.0.0"
	tags: List[str] = field(default_factory=list)
	properties: Dict[str, Any] = field(default_factory=dict)
	schema_hash: str = ""
	statistics: Dict[str, Any] = field(default_factory=dict)
	connections: List[str] = field(default_factory=list)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["created_at"] = self.created_at.isoformat()
		data["updated_at"] = self.updated_at.isoformat()
		return data


@dataclass
class GraphComparison:
	"""
	Results of graph comparison operation
	
	Attributes:
		graph_a: First graph name
		graph_b: Second graph name
		comparison_type: Type of comparison
		timestamp: When comparison was performed
		similarities: Similarity metrics
		differences: Difference analysis
		common_elements: Common nodes/edges
		unique_elements: Unique elements per graph
		statistics: Comparison statistics
	"""
	
	graph_a: str
	graph_b: str
	comparison_type: str
	timestamp: datetime
	similarities: Dict[str, Any]
	differences: Dict[str, Any]
	common_elements: Dict[str, List[str]]
	unique_elements: Dict[str, List[str]]
	statistics: Dict[str, Any]
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["timestamp"] = self.timestamp.isoformat()
		return data


@dataclass
class GraphSnapshot:
	"""
	Graph snapshot for temporal analysis
	
	Attributes:
		id: Snapshot identifier
		graph_name: Source graph name
		snapshot_type: Type of snapshot
		timestamp: When snapshot was taken
		version: Snapshot version
		schema: Graph schema at time of snapshot
		node_count: Number of nodes
		edge_count: Number of edges
		metadata: Snapshot metadata
		storage_path: Where snapshot data is stored
		size_bytes: Snapshot size in bytes
	"""
	
	id: str
	graph_name: str
	snapshot_type: GraphVersionType
	timestamp: datetime
	version: str
	schema: Dict[str, Any]
	node_count: int
	edge_count: int
	metadata: Dict[str, Any] = field(default_factory=dict)
	storage_path: str = ""
	size_bytes: int = 0
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["timestamp"] = self.timestamp.isoformat()
		data["snapshot_type"] = self.snapshot_type.value
		return data


class GraphRegistry:
	"""
	Registry for managing multiple graph databases
	
	Maintains metadata, connections, and lifecycle management for multiple graphs.
	"""
	
	def __init__(self, database_uri: str = None):
		self.database_uri = database_uri
		self.engine = None
		self.graphs: Dict[str, GraphMetadata] = {}
		self.managers: Dict[str, GraphDatabaseManager] = {}
		self._lock = threading.RLock()
		
		self._initialize_registry()
	
	def _initialize_registry(self):
		"""Initialize the graph registry"""
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
				self._create_registry_tables()
				self._load_registered_graphs()
				logger.info("Graph registry initialized successfully")
			
		except Exception as e:
			logger.error(f"Failed to initialize graph registry: {e}")
	
	def _create_registry_tables(self):
		"""Create registry tables for metadata storage"""
		try:
			with self.engine.begin() as conn:
				# Graph metadata table
				conn.execute(text("""
					CREATE TABLE IF NOT EXISTS graph_registry (
						name VARCHAR(255) PRIMARY KEY,
						description TEXT,
						created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
						updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
						version VARCHAR(50) DEFAULT '1.0.0',
						tags TEXT,
						properties JSONB,
						schema_hash VARCHAR(64),
						statistics JSONB,
						connections TEXT
					)
				"""))
				
				# Graph snapshots table
				conn.execute(text("""
					CREATE TABLE IF NOT EXISTS graph_snapshots (
						id VARCHAR(255) PRIMARY KEY,
						graph_name VARCHAR(255) NOT NULL,
						snapshot_type VARCHAR(50) NOT NULL,
						timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
						version VARCHAR(50),
						schema JSONB,
						node_count INTEGER DEFAULT 0,
						edge_count INTEGER DEFAULT 0,
						metadata JSONB,
						storage_path TEXT,
						size_bytes BIGINT DEFAULT 0,
						FOREIGN KEY (graph_name) REFERENCES graph_registry(name)
					)
				"""))
				
				# Create indexes
				conn.execute(text("""
					CREATE INDEX IF NOT EXISTS idx_graph_snapshots_graph_name 
					ON graph_snapshots (graph_name, timestamp DESC)
				"""))
				
				logger.info("Graph registry tables created successfully")
				
		except Exception as e:
			logger.error(f"Failed to create registry tables: {e}")
	
	def _load_registered_graphs(self):
		"""Load registered graphs from database"""
		try:
			if not self.engine:
				return
			
			with self.engine.connect() as conn:
				result = conn.execute(text("""
					SELECT name, description, created_at, updated_at, version,
						   tags, properties, schema_hash, statistics, connections
					FROM graph_registry
				"""))
				
				rows = result.fetchall()
				
				for row in rows:
					tags = row[5].split(',') if row[5] else []
					properties = json.loads(row[6]) if row[6] else {}
					statistics = json.loads(row[8]) if row[8] else {}
					connections = row[9].split(',') if row[9] else []
					
					metadata = GraphMetadata(
						name=row[0],
						description=row[1],
						created_at=row[2],
						updated_at=row[3],
						version=row[4],
						tags=tags,
						properties=properties,
						schema_hash=row[7] or "",
						statistics=statistics,
						connections=connections
					)
					
					self.graphs[row[0]] = metadata
				
				logger.info(f"Loaded {len(self.graphs)} registered graphs")
				
		except Exception as e:
			logger.error(f"Failed to load registered graphs: {e}")
	
	def register_graph(self, name: str, description: str = "", 
					  tags: List[str] = None, properties: Dict[str, Any] = None) -> GraphMetadata:
		"""Register a new graph in the registry"""
		with self._lock:
			try:
				if name in self.graphs:
					raise ValueError(f"Graph '{name}' is already registered")
				
				# Create graph metadata
				metadata = GraphMetadata(
					name=name,
					description=description,
					created_at=datetime.now(tz=timezone.utc),
					updated_at=datetime.now(tz=timezone.utc),
					tags=tags or [],
					properties=properties or {}
				)
				
				# Calculate schema hash
				try:
					manager = self.get_graph_manager(name)
					schema = manager.get_graph_schema()
					metadata.schema_hash = self._calculate_schema_hash(schema)
					metadata.statistics = schema.statistics
				except Exception as e:
					logger.warning(f"Could not get schema for graph {name}: {e}")
				
				# Store in database
				if self.engine:
					with self.engine.begin() as conn:
						conn.execute(text("""
							INSERT INTO graph_registry 
							(name, description, created_at, updated_at, version, tags, 
							 properties, schema_hash, statistics, connections)
							VALUES (:name, :description, :created_at, :updated_at, :version,
									:tags, :properties, :schema_hash, :statistics, :connections)
						"""), {
							"name": name,
							"description": description,
							"created_at": metadata.created_at,
							"updated_at": metadata.updated_at,
							"version": metadata.version,
							"tags": ','.join(metadata.tags),
							"properties": json.dumps(metadata.properties),
							"schema_hash": metadata.schema_hash,
							"statistics": json.dumps(metadata.statistics),
							"connections": ','.join(metadata.connections)
						})
				
				# Add to registry
				self.graphs[name] = metadata
				
				# Track registration
				track_database_activity(
					activity_type=ActivityType.TABLE_CREATED,
					target=f"Graph Registration: {name}",
					description=f"Registered new graph '{name}' in multi-graph registry",
					details={
						"graph_name": name,
						"description": description,
						"tags": tags,
						"schema_hash": metadata.schema_hash
					}
				)
				
				logger.info(f"Successfully registered graph: {name}")
				return metadata
				
			except Exception as e:
				logger.error(f"Failed to register graph {name}: {e}")
				raise
	
	def unregister_graph(self, name: str):
		"""Unregister a graph from the registry"""
		with self._lock:
			try:
				if name not in self.graphs:
					raise ValueError(f"Graph '{name}' is not registered")
				
				# Remove from database
				if self.engine:
					with self.engine.begin() as conn:
						conn.execute(text("""
							DELETE FROM graph_snapshots WHERE graph_name = :name
						"""), {"name": name})
						
						conn.execute(text("""
							DELETE FROM graph_registry WHERE name = :name
						"""), {"name": name})
				
				# Remove from memory
				self.graphs.pop(name, None)
				self.managers.pop(name, None)
				
				logger.info(f"Successfully unregistered graph: {name}")
				
			except Exception as e:
				logger.error(f"Failed to unregister graph {name}: {e}")
				raise
	
	def get_graph_manager(self, name: str) -> GraphDatabaseManager:
		"""Get graph manager for specified graph"""
		if name not in self.managers:
			self.managers[name] = GraphDatabaseManager(
				database_uri=self.database_uri,
				graph_name=name
			)
		return self.managers[name]
	
	def list_graphs(self, tags: List[str] = None) -> List[GraphMetadata]:
		"""List all registered graphs, optionally filtered by tags"""
		graphs = list(self.graphs.values())
		
		if tags:
			graphs = [
				graph for graph in graphs
				if any(tag in graph.tags for tag in tags)
			]
		
		return sorted(graphs, key=lambda g: g.updated_at, reverse=True)
	
	def get_graph_metadata(self, name: str) -> Optional[GraphMetadata]:
		"""Get metadata for specific graph"""
		return self.graphs.get(name)
	
	def update_graph_metadata(self, name: str, **kwargs) -> GraphMetadata:
		"""Update graph metadata"""
		with self._lock:
			try:
				if name not in self.graphs:
					raise ValueError(f"Graph '{name}' is not registered")
				
				metadata = self.graphs[name]
				
				# Update fields
				if "description" in kwargs:
					metadata.description = kwargs["description"]
				if "tags" in kwargs:
					metadata.tags = kwargs["tags"]
				if "properties" in kwargs:
					metadata.properties.update(kwargs["properties"])
				
				metadata.updated_at = datetime.now(tz=timezone.utc)
				
				# Update schema hash if needed
				if kwargs.get("update_schema", False):
					try:
						manager = self.get_graph_manager(name)
						schema = manager.get_graph_schema()
						metadata.schema_hash = self._calculate_schema_hash(schema)
						metadata.statistics = schema.statistics
					except Exception as e:
						logger.warning(f"Could not update schema for graph {name}: {e}")
				
				# Update in database
				if self.engine:
					with self.engine.begin() as conn:
						conn.execute(text("""
							UPDATE graph_registry SET
								description = :description,
								updated_at = :updated_at,
								tags = :tags,
								properties = :properties,
								schema_hash = :schema_hash,
								statistics = :statistics
							WHERE name = :name
						"""), {
							"name": name,
							"description": metadata.description,
							"updated_at": metadata.updated_at,
							"tags": ','.join(metadata.tags),
							"properties": json.dumps(metadata.properties),
							"schema_hash": metadata.schema_hash,
							"statistics": json.dumps(metadata.statistics)
						})
				
				logger.info(f"Updated metadata for graph: {name}")
				return metadata
				
			except Exception as e:
				logger.error(f"Failed to update graph metadata {name}: {e}")
				raise
	
	def _calculate_schema_hash(self, schema: GraphSchema) -> str:
		"""Calculate hash fingerprint of graph schema"""
		try:
			# Create deterministic representation
			schema_repr = {
				"node_labels": sorted(schema.node_labels),
				"edge_labels": sorted(schema.edge_labels),
				"node_properties": {k: sorted(v) for k, v in schema.node_properties.items()},
				"edge_properties": {k: sorted(v) for k, v in schema.edge_properties.items()}
			}
			
			# Calculate hash
			schema_json = json.dumps(schema_repr, sort_keys=True)
			return hashlib.sha256(schema_json.encode()).hexdigest()[:16]
			
		except Exception as e:
			logger.warning(f"Failed to calculate schema hash: {e}")
			return ""


class MultiGraphAnalyzer:
	"""
	Analyzer for cross-graph operations and comparisons
	
	Provides graph comparison, union, intersection, and temporal analysis capabilities.
	"""
	
	def __init__(self, registry: GraphRegistry = None):
		self.registry = registry or GraphRegistry()
		self.executor = ThreadPoolExecutor(max_workers=4)
	
	def compare_graphs(self, graph_a: str, graph_b: str) -> GraphComparison:
		"""Compare two graphs and analyze similarities/differences"""
		try:
			# Get graph managers
			manager_a = self.registry.get_graph_manager(graph_a)
			manager_b = self.registry.get_graph_manager(graph_b)
			
			# Get graph schemas
			schema_a = manager_a.get_graph_schema()
			schema_b = manager_b.get_graph_schema()
			
			# Get graph data for detailed comparison
			data_a = manager_a.get_graph_data(limit=1000)
			data_b = manager_b.get_graph_data(limit=1000)
			
			# Calculate similarities
			similarities = self._calculate_similarities(schema_a, schema_b, data_a, data_b)
			
			# Calculate differences
			differences = self._calculate_differences(schema_a, schema_b, data_a, data_b)
			
			# Find common elements
			common_elements = self._find_common_elements(data_a, data_b)
			
			# Find unique elements
			unique_elements = self._find_unique_elements(data_a, data_b)
			
			# Calculate comparison statistics
			statistics = self._calculate_comparison_statistics(
				schema_a, schema_b, similarities, differences
			)
			
			comparison = GraphComparison(
				graph_a=graph_a,
				graph_b=graph_b,
				comparison_type="full_comparison",
				timestamp=datetime.now(tz=timezone.utc),
				similarities=similarities,
				differences=differences,
				common_elements=common_elements,
				unique_elements=unique_elements,
				statistics=statistics
			)
			
			return comparison
			
		except Exception as e:
			logger.error(f"Graph comparison failed ({graph_a} vs {graph_b}): {e}")
			raise
	
	def _calculate_similarities(self, schema_a: GraphSchema, schema_b: GraphSchema, 
							   data_a: Dict[str, Any], data_b: Dict[str, Any]) -> Dict[str, Any]:
		"""Calculate similarity metrics between graphs"""
		similarities = {}
		
		try:
			# Schema similarities
			common_node_labels = set(schema_a.node_labels) & set(schema_b.node_labels)
			common_edge_labels = set(schema_a.edge_labels) & set(schema_b.edge_labels)
			
			similarities["schema"] = {
				"common_node_labels": list(common_node_labels),
				"common_edge_labels": list(common_edge_labels),
				"node_label_similarity": len(common_node_labels) / max(len(schema_a.node_labels), len(schema_b.node_labels), 1),
				"edge_label_similarity": len(common_edge_labels) / max(len(schema_a.edge_labels), len(schema_b.edge_labels), 1)
			}
			
			# Structure similarities
			if data_a.get("success") and data_b.get("success"):
				nodes_a = {node["id"]: node for node in data_a["nodes"]}
				nodes_b = {node["id"]: node for node in data_b["nodes"]}
				edges_a = {f"{edge['source']}_{edge['target']}": edge for edge in data_a["edges"]}
				edges_b = {f"{edge['source']}_{edge['target']}": edge for edge in data_b["edges"]}
				
				common_nodes = set(nodes_a.keys()) & set(nodes_b.keys())
				common_edges = set(edges_a.keys()) & set(edges_b.keys())
				
				similarities["structure"] = {
					"common_nodes": len(common_nodes),
					"common_edges": len(common_edges),
					"node_overlap": len(common_nodes) / max(len(nodes_a), len(nodes_b), 1),
					"edge_overlap": len(common_edges) / max(len(edges_a), len(edges_b), 1)
				}
			
		except Exception as e:
			logger.warning(f"Error calculating similarities: {e}")
		
		return similarities
	
	def _calculate_differences(self, schema_a: GraphSchema, schema_b: GraphSchema,
							 data_a: Dict[str, Any], data_b: Dict[str, Any]) -> Dict[str, Any]:
		"""Calculate differences between graphs"""
		differences = {}
		
		try:
			# Schema differences
			node_labels_a_only = set(schema_a.node_labels) - set(schema_b.node_labels)
			node_labels_b_only = set(schema_b.node_labels) - set(schema_a.node_labels)
			edge_labels_a_only = set(schema_a.edge_labels) - set(schema_b.edge_labels)
			edge_labels_b_only = set(schema_b.edge_labels) - set(schema_a.edge_labels)
			
			differences["schema"] = {
				"node_labels_a_only": list(node_labels_a_only),
				"node_labels_b_only": list(node_labels_b_only),
				"edge_labels_a_only": list(edge_labels_a_only),
				"edge_labels_b_only": list(edge_labels_b_only)
			}
			
			# Statistics differences
			stats_a = schema_a.statistics
			stats_b = schema_b.statistics
			
			differences["statistics"] = {
				"node_count_diff": stats_a.get("total_nodes", 0) - stats_b.get("total_nodes", 0),
				"edge_count_diff": stats_a.get("total_edges", 0) - stats_b.get("total_edges", 0),
				"density_diff": stats_a.get("density", 0) - stats_b.get("density", 0)
			}
			
		except Exception as e:
			logger.warning(f"Error calculating differences: {e}")
		
		return differences
	
	def _find_common_elements(self, data_a: Dict[str, Any], data_b: Dict[str, Any]) -> Dict[str, List[str]]:
		"""Find common elements between graphs"""
		common_elements = {"nodes": [], "edges": []}
		
		try:
			if data_a.get("success") and data_b.get("success"):
				nodes_a = {node["id"] for node in data_a["nodes"]}
				nodes_b = {node["id"] for node in data_b["nodes"]}
				edges_a = {f"{edge['source']}_{edge['target']}" for edge in data_a["edges"]}
				edges_b = {f"{edge['source']}_{edge['target']}" for edge in data_b["edges"]}
				
				common_elements["nodes"] = list(nodes_a & nodes_b)
				common_elements["edges"] = list(edges_a & edges_b)
			
		except Exception as e:
			logger.warning(f"Error finding common elements: {e}")
		
		return common_elements
	
	def _find_unique_elements(self, data_a: Dict[str, Any], data_b: Dict[str, Any]) -> Dict[str, List[str]]:
		"""Find unique elements in each graph"""
		unique_elements = {"graph_a": {"nodes": [], "edges": []}, "graph_b": {"nodes": [], "edges": []}}
		
		try:
			if data_a.get("success") and data_b.get("success"):
				nodes_a = {node["id"] for node in data_a["nodes"]}
				nodes_b = {node["id"] for node in data_b["nodes"]}
				edges_a = {f"{edge['source']}_{edge['target']}" for edge in data_a["edges"]}
				edges_b = {f"{edge['source']}_{edge['target']}" for edge in data_b["edges"]}
				
				unique_elements["graph_a"]["nodes"] = list(nodes_a - nodes_b)
				unique_elements["graph_a"]["edges"] = list(edges_a - edges_b)
				unique_elements["graph_b"]["nodes"] = list(nodes_b - nodes_a)
				unique_elements["graph_b"]["edges"] = list(edges_b - edges_a)
			
		except Exception as e:
			logger.warning(f"Error finding unique elements: {e}")
		
		return unique_elements
	
	def _calculate_comparison_statistics(self, schema_a: GraphSchema, schema_b: GraphSchema,
										similarities: Dict[str, Any], differences: Dict[str, Any]) -> Dict[str, Any]:
		"""Calculate overall comparison statistics"""
		statistics = {}
		
		try:
			# Overall similarity score
			schema_sim = similarities.get("schema", {})
			structure_sim = similarities.get("structure", {})
			
			node_label_sim = schema_sim.get("node_label_similarity", 0)
			edge_label_sim = schema_sim.get("edge_label_similarity", 0)
			node_overlap = structure_sim.get("node_overlap", 0)
			edge_overlap = structure_sim.get("edge_overlap", 0)
			
			overall_similarity = (node_label_sim + edge_label_sim + node_overlap + edge_overlap) / 4
			
			statistics = {
				"overall_similarity": overall_similarity,
				"similarity_category": self._categorize_similarity(overall_similarity),
				"comparison_summary": {
					"schema_similarity": (node_label_sim + edge_label_sim) / 2,
					"structure_similarity": (node_overlap + edge_overlap) / 2,
					"total_elements_a": schema_a.statistics.get("total_nodes", 0) + schema_a.statistics.get("total_edges", 0),
					"total_elements_b": schema_b.statistics.get("total_nodes", 0) + schema_b.statistics.get("total_edges", 0)
				}
			}
			
		except Exception as e:
			logger.warning(f"Error calculating comparison statistics: {e}")
		
		return statistics
	
	def _categorize_similarity(self, similarity_score: float) -> str:
		"""Categorize similarity score"""
		if similarity_score >= 0.8:
			return "Very Similar"
		elif similarity_score >= 0.6:
			return "Similar"
		elif similarity_score >= 0.4:
			return "Moderately Similar"
		elif similarity_score >= 0.2:
			return "Somewhat Similar"
		else:
			return "Very Different"
	
	def create_graph_union(self, graph_names: List[str], target_name: str) -> Dict[str, Any]:
		"""Create union of multiple graphs"""
		try:
			# Get all graph data
			all_nodes = {}
			all_edges = {}
			
			for graph_name in graph_names:
				manager = self.registry.get_graph_manager(graph_name)
				data = manager.get_graph_data(limit=5000)
				
				if data.get("success"):
					# Merge nodes (keeping unique IDs)
					for node in data["nodes"]:
						node_id = f"{graph_name}:{node['id']}"
						all_nodes[node_id] = {**node, "id": node_id, "source_graph": graph_name}
					
					# Merge edges (updating source/target references)
					for edge in data["edges"]:
						edge_id = f"{graph_name}:{edge['id']}"
						source_id = f"{graph_name}:{edge['source']}"
						target_id = f"{graph_name}:{edge['target']}"
						
						all_edges[edge_id] = {
							**edge,
							"id": edge_id,
							"source": source_id,
							"target": target_id,
							"source_graph": graph_name
						}
			
			# Create target graph and populate with union data
			# This is a simplified implementation - in production,
			# this would involve actual graph creation in AGE
			
			union_result = {
				"success": True,
				"target_graph": target_name,
				"source_graphs": graph_names,
				"total_nodes": len(all_nodes),
				"total_edges": len(all_edges),
				"nodes_by_source": {graph: sum(1 for n in all_nodes.values() if n["source_graph"] == graph) for graph in graph_names},
				"edges_by_source": {graph: sum(1 for e in all_edges.values() if e["source_graph"] == graph) for graph in graph_names}
			}
			
			return union_result
			
		except Exception as e:
			logger.error(f"Graph union failed: {e}")
			raise
	
	def create_graph_intersection(self, graph_names: List[str], target_name: str) -> Dict[str, Any]:
		"""Create intersection of multiple graphs"""
		try:
			if len(graph_names) < 2:
				raise ValueError("At least 2 graphs required for intersection")
			
			# Get data for all graphs
			graph_data = {}
			for graph_name in graph_names:
				manager = self.registry.get_graph_manager(graph_name)
				graph_data[graph_name] = manager.get_graph_data(limit=5000)
			
			# Find common nodes (by properties, not just ID)
			common_nodes = self._find_intersection_nodes(graph_data)
			
			# Find common edges
			common_edges = self._find_intersection_edges(graph_data, common_nodes)
			
			intersection_result = {
				"success": True,
				"target_graph": target_name,
				"source_graphs": graph_names,
				"common_nodes": len(common_nodes),
				"common_edges": len(common_edges),
				"intersection_ratio": len(common_nodes) / max(1, min(
					len(data["nodes"]) for data in graph_data.values() if data.get("success")
				))
			}
			
			return intersection_result
			
		except Exception as e:
			logger.error(f"Graph intersection failed: {e}")
			raise
	
	def _find_intersection_nodes(self, graph_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
		"""Find nodes common across all graphs"""
		common_nodes = []
		
		try:
			# Get first graph's nodes as baseline
			first_graph = next(iter(graph_data.values()))
			if not first_graph.get("success"):
				return common_nodes
			
			baseline_nodes = first_graph["nodes"]
			
			# Check each node against all other graphs
			for node in baseline_nodes:
				is_common = True
				
				for graph_name, data in graph_data.items():
					if not data.get("success"):
						is_common = False
						break
					
					# Look for similar node in this graph
					found_similar = False
					for other_node in data["nodes"]:
						if self._nodes_are_similar(node, other_node):
							found_similar = True
							break
					
					if not found_similar:
						is_common = False
						break
				
				if is_common:
					common_nodes.append(node)
			
		except Exception as e:
			logger.warning(f"Error finding intersection nodes: {e}")
		
		return common_nodes
	
	def _find_intersection_edges(self, graph_data: Dict[str, Dict[str, Any]], common_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
		"""Find edges common across all graphs"""
		common_edges = []
		
		try:
			common_node_ids = {node["id"] for node in common_nodes}
			
			# Get first graph's edges as baseline
			first_graph = next(iter(graph_data.values()))
			if not first_graph.get("success"):
				return common_edges
			
			baseline_edges = first_graph["edges"]
			
			# Check each edge against all other graphs
			for edge in baseline_edges:
				# Skip edges not between common nodes
				if edge["source"] not in common_node_ids or edge["target"] not in common_node_ids:
					continue
				
				is_common = True
				
				for graph_name, data in graph_data.items():
					if not data.get("success"):
						is_common = False
						break
					
					# Look for similar edge in this graph
					found_similar = False
					for other_edge in data["edges"]:
						if self._edges_are_similar(edge, other_edge):
							found_similar = True
							break
					
					if not found_similar:
						is_common = False
						break
				
				if is_common:
					common_edges.append(edge)
			
		except Exception as e:
			logger.warning(f"Error finding intersection edges: {e}")
		
		return common_edges
	
	def _nodes_are_similar(self, node_a: Dict[str, Any], node_b: Dict[str, Any]) -> bool:
		"""Check if two nodes are similar enough to be considered the same"""
		try:
			# Check label similarity
			if node_a.get("label") != node_b.get("label"):
				return False
			
			# Check key properties (simplified similarity check)
			props_a = node_a.get("properties", {})
			props_b = node_b.get("properties", {})
			
			# If both have 'name' property, compare it
			if "name" in props_a and "name" in props_b:
				return props_a["name"] == props_b["name"]
			
			# If both have 'id' property, compare it
			if "id" in props_a and "id" in props_b:
				return props_a["id"] == props_b["id"]
			
			# Default to true if no distinguishing properties
			return True
			
		except Exception:
			return False
	
	def _edges_are_similar(self, edge_a: Dict[str, Any], edge_b: Dict[str, Any]) -> bool:
		"""Check if two edges are similar enough to be considered the same"""
		try:
			# Check label similarity
			if edge_a.get("label") != edge_b.get("label"):
				return False
			
			# Check if they connect similar nodes (simplified check)
			return (edge_a.get("source") == edge_b.get("source") and 
					edge_a.get("target") == edge_b.get("target"))
			
		except Exception:
			return False


class TemporalGraphManager:
	"""
	Manages temporal aspects of graphs including snapshots and versioning
	
	Provides capabilities for graph versioning, temporal analysis, and rollback operations.
	"""
	
	def __init__(self, registry: GraphRegistry = None):
		self.registry = registry or GraphRegistry()
	
	def create_snapshot(self, graph_name: str, snapshot_type: GraphVersionType = GraphVersionType.SNAPSHOT,
					   version: str = None, metadata: Dict[str, Any] = None) -> GraphSnapshot:
		"""Create a snapshot of the current graph state"""
		try:
			if graph_name not in self.registry.graphs:
				raise ValueError(f"Graph '{graph_name}' is not registered")
			
			# Generate snapshot ID
			snapshot_id = f"{graph_name}_snapshot_{int(datetime.now(tz=timezone.utc).timestamp())}"
			
			# Get current graph state
			manager = self.registry.get_graph_manager(graph_name)
			schema = manager.get_graph_schema()
			
			# Create snapshot record
			snapshot = GraphSnapshot(
				id=snapshot_id,
				graph_name=graph_name,
				snapshot_type=snapshot_type,
				timestamp=datetime.now(tz=timezone.utc),
				version=version or "1.0.0",
				schema=schema.to_dict(),
				node_count=schema.statistics.get("total_nodes", 0),
				edge_count=schema.statistics.get("total_edges", 0),
				metadata=metadata or {}
			)
			
			# Store snapshot in database
			if self.registry.engine:
				with self.registry.engine.begin() as conn:
					conn.execute(text("""
						INSERT INTO graph_snapshots 
						(id, graph_name, snapshot_type, timestamp, version, schema,
						 node_count, edge_count, metadata, storage_path, size_bytes)
						VALUES (:id, :graph_name, :snapshot_type, :timestamp, :version,
								:schema, :node_count, :edge_count, :metadata, :storage_path, :size_bytes)
					"""), {
						"id": snapshot.id,
						"graph_name": snapshot.graph_name,
						"snapshot_type": snapshot.snapshot_type.value,
						"timestamp": snapshot.timestamp,
						"version": snapshot.version,
						"schema": json.dumps(snapshot.schema),
						"node_count": snapshot.node_count,
						"edge_count": snapshot.edge_count,
						"metadata": json.dumps(snapshot.metadata),
						"storage_path": snapshot.storage_path,
						"size_bytes": snapshot.size_bytes
					})
			
			# Track snapshot creation
			track_database_activity(
				activity_type=ActivityType.TABLE_CREATED,
				target=f"Graph Snapshot: {snapshot_id}",
				description=f"Created snapshot of graph '{graph_name}'",
				details={
					"graph_name": graph_name,
					"snapshot_id": snapshot_id,
					"snapshot_type": snapshot_type.value,
					"node_count": snapshot.node_count,
					"edge_count": snapshot.edge_count
				}
			)
			
			logger.info(f"Created snapshot {snapshot_id} for graph {graph_name}")
			return snapshot
			
		except Exception as e:
			logger.error(f"Failed to create snapshot for graph {graph_name}: {e}")
			raise
	
	def list_snapshots(self, graph_name: str = None) -> List[GraphSnapshot]:
		"""List snapshots, optionally filtered by graph name"""
		try:
			snapshots = []
			
			if not self.registry.engine:
				return snapshots
			
			with self.registry.engine.connect() as conn:
				query = """
					SELECT id, graph_name, snapshot_type, timestamp, version, schema,
						   node_count, edge_count, metadata, storage_path, size_bytes
					FROM graph_snapshots
				"""
				params = {}
				
				if graph_name:
					query += " WHERE graph_name = :graph_name"
					params["graph_name"] = graph_name
				
				query += " ORDER BY timestamp DESC"
				
				result = conn.execute(text(query), params)
				rows = result.fetchall()
				
				for row in rows:
					snapshot = GraphSnapshot(
						id=row[0],
						graph_name=row[1],
						snapshot_type=GraphVersionType(row[2]),
						timestamp=row[3],
						version=row[4],
						schema=json.loads(row[5]) if row[5] else {},
						node_count=row[6],
						edge_count=row[7],
						metadata=json.loads(row[8]) if row[8] else {},
						storage_path=row[9] or "",
						size_bytes=row[10] or 0
					)
					snapshots.append(snapshot)
			
			return snapshots
			
		except Exception as e:
			logger.error(f"Failed to list snapshots: {e}")
			raise
	
	def get_snapshot(self, snapshot_id: str) -> Optional[GraphSnapshot]:
		"""Get specific snapshot by ID"""
		try:
			if not self.registry.engine:
				return None
			
			with self.registry.engine.connect() as conn:
				result = conn.execute(text("""
					SELECT id, graph_name, snapshot_type, timestamp, version, schema,
						   node_count, edge_count, metadata, storage_path, size_bytes
					FROM graph_snapshots
					WHERE id = :snapshot_id
				"""), {"snapshot_id": snapshot_id})
				
				row = result.fetchone()
				if not row:
					return None
				
				snapshot = GraphSnapshot(
					id=row[0],
					graph_name=row[1],
					snapshot_type=GraphVersionType(row[2]),
					timestamp=row[3],
					version=row[4],
					schema=json.loads(row[5]) if row[5] else {},
					node_count=row[6],
					edge_count=row[7],
					metadata=json.loads(row[8]) if row[8] else {},
					storage_path=row[9] or "",
					size_bytes=row[10] or 0
				)
				
				return snapshot
			
		except Exception as e:
			logger.error(f"Failed to get snapshot {snapshot_id}: {e}")
			raise
	
	def analyze_temporal_changes(self, graph_name: str, days_back: int = 30) -> Dict[str, Any]:
		"""Analyze temporal changes in a graph over time"""
		try:
			# Get snapshots from the specified time period
			start_date = datetime.now(tz=timezone.utc) - timedelta(days=days_back)
			snapshots = []
			
			if self.registry.engine:
				with self.registry.engine.connect() as conn:
					result = conn.execute(text("""
						SELECT id, graph_name, snapshot_type, timestamp, version, schema,
							   node_count, edge_count, metadata
						FROM graph_snapshots
						WHERE graph_name = :graph_name AND timestamp >= :start_date
						ORDER BY timestamp ASC
					"""), {"graph_name": graph_name, "start_date": start_date})
					
					rows = result.fetchall()
					
					for row in rows:
						snapshot = GraphSnapshot(
							id=row[0],
							graph_name=row[1],
							snapshot_type=GraphVersionType(row[2]),
							timestamp=row[3],
							version=row[4],
							schema=json.loads(row[5]) if row[5] else {},
							node_count=row[6],
							edge_count=row[7],
							metadata=json.loads(row[8]) if row[8] else {}
						)
						snapshots.append(snapshot)
			
			# Analyze changes over time
			analysis = {
				"graph_name": graph_name,
				"analysis_period_days": days_back,
				"total_snapshots": len(snapshots),
				"changes_over_time": [],
				"growth_trends": {},
				"schema_evolution": []
			}
			
			if len(snapshots) >= 2:
				# Calculate changes between consecutive snapshots
				for i in range(1, len(snapshots)):
					prev_snapshot = snapshots[i-1]
					curr_snapshot = snapshots[i]
					
					change = {
						"from_snapshot": prev_snapshot.id,
						"to_snapshot": curr_snapshot.id,
						"time_diff_hours": (curr_snapshot.timestamp - prev_snapshot.timestamp).total_seconds() / 3600,
						"node_count_change": curr_snapshot.node_count - prev_snapshot.node_count,
						"edge_count_change": curr_snapshot.edge_count - prev_snapshot.edge_count,
						"schema_changed": prev_snapshot.schema != curr_snapshot.schema
					}
					
					analysis["changes_over_time"].append(change)
				
				# Calculate growth trends
				first_snapshot = snapshots[0]
				last_snapshot = snapshots[-1]
				
				time_diff_days = (last_snapshot.timestamp - first_snapshot.timestamp).total_seconds() / (24 * 3600)
				
				if time_diff_days > 0:
					analysis["growth_trends"] = {
						"nodes_per_day": (last_snapshot.node_count - first_snapshot.node_count) / time_diff_days,
						"edges_per_day": (last_snapshot.edge_count - first_snapshot.edge_count) / time_diff_days,
						"total_growth_rate": (last_snapshot.node_count + last_snapshot.edge_count - 
											 first_snapshot.node_count - first_snapshot.edge_count) / time_diff_days
					}
			
			return analysis
			
		except Exception as e:
			logger.error(f"Temporal analysis failed for graph {graph_name}: {e}")
			raise


# Global instances
_registry = None
_analyzer = None
_temporal_manager = None


def get_graph_registry() -> GraphRegistry:
	"""Get or create global graph registry instance"""
	global _registry
	if _registry is None:
		_registry = GraphRegistry()
	return _registry


def get_multi_graph_analyzer() -> MultiGraphAnalyzer:
	"""Get or create global multi-graph analyzer instance"""
	global _analyzer
	if _analyzer is None:
		_analyzer = MultiGraphAnalyzer()
	return _analyzer


def get_temporal_graph_manager() -> TemporalGraphManager:
	"""Get or create global temporal graph manager instance"""
	global _temporal_manager
	if _temporal_manager is None:
		_temporal_manager = TemporalGraphManager()
	return _temporal_manager