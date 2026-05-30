"""
Import/Export Pipeline for Graph Data

Provides comprehensive data exchange capabilities with support for multiple
formats (GraphML, GEXF, CSV, JSON) and integration with other graph databases.
"""

import json
import csv
import xml.etree.ElementTree as ET
import logging
import zipfile
import tempfile
import threading
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Union, IO
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
import io
import base64

try:
	import pandas as pd
	PANDAS_AVAILABLE = True
except ImportError:
	PANDAS_AVAILABLE = False

try:
	import networkx as nx
	NETWORKX_AVAILABLE = True
except ImportError:
	NETWORKX_AVAILABLE = False

try:
	from neo4j import GraphDatabase
	NEO4J_AVAILABLE = True
except ImportError:
	NEO4J_AVAILABLE = False

import numpy as np
from sqlalchemy import text

from .graph_manager import GraphDatabaseManager, get_graph_manager
from .multi_graph_manager import get_graph_registry
from .activity_tracker import track_database_activity, ActivityType
from .performance_optimizer import get_performance_monitor, performance_cache

logger = logging.getLogger(__name__)


class ExportFormat(Enum):
	"""Supported export formats"""
	GRAPHML = "graphml"
	GEXF = "gexf"
	CSV_NODES_EDGES = "csv_nodes_edges"
	JSON = "json"
	CYPHER_SCRIPT = "cypher_script"
	NEO4J_DUMP = "neo4j_dump"
	ADJACENCY_MATRIX = "adjacency_matrix"
	EDGE_LIST = "edge_list"


class ImportFormat(Enum):
	"""Supported import formats"""
	GRAPHML = "graphml"
	GEXF = "gexf"
	CSV_NODES_EDGES = "csv_nodes_edges"
	JSON = "json"
	CYPHER_SCRIPT = "cypher_script"
	NEO4J_BACKUP = "neo4j_backup"
	ADJACENCY_MATRIX = "adjacency_matrix"
	EDGE_LIST = "edge_list"


class DataSourceType(Enum):
	"""Types of data sources"""
	FILE = "file"
	DATABASE = "database"
	API = "api"
	STREAM = "stream"


class ProcessingStatus(Enum):
	"""Processing status for import/export operations"""
	PENDING = "pending"
	PROCESSING = "processing"
	COMPLETED = "completed"
	FAILED = "failed"
	CANCELLED = "cancelled"


@dataclass
class DataExchangeJob:
	"""
	Data exchange job tracking
	
	Attributes:
		job_id: Unique job identifier
		job_type: Import or export
		format: Data format being processed
		source: Source location/identifier
		target: Target location/identifier
		status: Current processing status
		progress: Completion percentage (0-100)
		created_at: Job creation timestamp
		started_at: Processing start timestamp
		completed_at: Processing completion timestamp
		error_message: Error details if failed
		metadata: Additional job metadata
	"""
	
	job_id: str
	job_type: str  # "import" or "export"
	format: str
	source: str
	target: str
	status: ProcessingStatus = ProcessingStatus.PENDING
	progress: int = 0
	created_at: datetime = field(default_factory=datetime.utcnow)
	started_at: Optional[datetime] = None
	completed_at: Optional[datetime] = None
	error_message: Optional[str] = None
	metadata: Dict[str, Any] = field(default_factory=dict)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["status"] = self.status.value
		data["created_at"] = self.created_at.isoformat()
		data["started_at"] = self.started_at.isoformat() if self.started_at else None
		data["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
		return data


@dataclass
class ImportMapping:
	"""
	Configuration for data import mapping
	
	Defines how source data fields map to graph properties
	"""
	
	node_id_field: str = "id"
	node_label_field: str = "label"
	edge_source_field: str = "source"
	edge_target_field: str = "target"
	edge_type_field: str = "type"
	property_mappings: Dict[str, str] = field(default_factory=dict)
	ignore_fields: List[str] = field(default_factory=list)
	default_node_label: str = "Node"
	default_edge_type: str = "CONNECTED_TO"


class GraphMLExporter:
	"""GraphML format exporter"""
	
	def export(self, graph_data: Dict[str, Any], output_path: str) -> bool:
		"""Export graph data to GraphML format"""
		try:
			if not NETWORKX_AVAILABLE:
				raise ImportError("NetworkX is required for GraphML export")
			
			# Create NetworkX graph
			G = nx.Graph()
			
			# Add nodes
			for node in graph_data.get("nodes", []):
				node_id = node["id"]
				properties = node.get("properties", {})
				G.add_node(node_id, **properties)
			
			# Add edges
			for edge in graph_data.get("edges", []):
				source = edge["source"]
				target = edge["target"]
				properties = edge.get("properties", {})
				G.add_edge(source, target, **properties)
			
			# Export to GraphML
			nx.write_graphml(G, output_path)
			return True
			
		except Exception as e:
			logger.error(f"GraphML export failed: {e}")
			return False


class GEXFExporter:
	"""GEXF format exporter"""
	
	def export(self, graph_data: Dict[str, Any], output_path: str) -> bool:
		"""Export graph data to GEXF format"""
		try:
			if not NETWORKX_AVAILABLE:
				raise ImportError("NetworkX is required for GEXF export")
			
			# Create NetworkX graph
			G = nx.Graph()
			
			# Add nodes with attributes
			for node in graph_data.get("nodes", []):
				node_id = node["id"]
				properties = node.get("properties", {})
				G.add_node(node_id, **properties)
			
			# Add edges with attributes
			for edge in graph_data.get("edges", []):
				source = edge["source"]
				target = edge["target"]
				properties = edge.get("properties", {})
				G.add_edge(source, target, **properties)
			
			# Export to GEXF
			nx.write_gexf(G, output_path)
			return True
			
		except Exception as e:
			logger.error(f"GEXF export failed: {e}")
			return False


class CSVExporter:
	"""CSV format exporter (separate nodes and edges files)"""
	
	def export(self, graph_data: Dict[str, Any], output_path: str) -> bool:
		"""Export graph data to CSV format"""
		try:
			base_path = Path(output_path).with_suffix("")
			nodes_file = f"{base_path}_nodes.csv"
			edges_file = f"{base_path}_edges.csv"
			
			# Export nodes
			nodes = graph_data.get("nodes", [])
			if nodes:
				# Get all unique properties
				all_node_properties = set()
				for node in nodes:
					all_node_properties.update(node.get("properties", {}).keys())
				
				with open(nodes_file, 'w', newline='', encoding='utf-8') as f:
					fieldnames = ["id", "label"] + sorted(all_node_properties)
					writer = csv.DictWriter(f, fieldnames=fieldnames)
					writer.writeheader()
					
					for node in nodes:
						row = {
							"id": node["id"],
							"label": node.get("label", "")
						}
						row.update(node.get("properties", {}))
						writer.writerow(row)
			
			# Export edges
			edges = graph_data.get("edges", [])
			if edges:
				# Get all unique edge properties
				all_edge_properties = set()
				for edge in edges:
					all_edge_properties.update(edge.get("properties", {}).keys())
				
				with open(edges_file, 'w', newline='', encoding='utf-8') as f:
					fieldnames = ["source", "target", "type"] + sorted(all_edge_properties)
					writer = csv.DictWriter(f, fieldnames=fieldnames)
					writer.writeheader()
					
					for edge in edges:
						row = {
							"source": edge["source"],
							"target": edge["target"],
							"type": edge.get("type", "")
						}
						row.update(edge.get("properties", {}))
						writer.writerow(row)
			
			return True
			
		except Exception as e:
			logger.error(f"CSV export failed: {e}")
			return False


class CypherScriptExporter:
	"""Cypher script exporter"""
	
	def export(self, graph_data: Dict[str, Any], output_path: str) -> bool:
		"""Export graph data to Cypher script"""
		try:
			with open(output_path, 'w', encoding='utf-8') as f:
				# Write header
				f.write("// Graph Export to Cypher Script\n")
				f.write(f"// Generated at: {datetime.now(tz=timezone.utc).isoformat()}\n\n")
				
				# Clear existing data
				f.write("// Clear existing data\n")
				f.write("MATCH (n) DETACH DELETE n;\n\n")
				
				# Create nodes
				f.write("// Create nodes\n")
				for node in graph_data.get("nodes", []):
					node_id = node["id"]
					label = node.get("label", "Node")
					properties = node.get("properties", {})
					
					# Build properties string
					props_str = ""
					if properties:
						prop_parts = []
						for key, value in properties.items():
							if isinstance(value, str):
								prop_parts.append(f'{key}: "{value}"')
							else:
								prop_parts.append(f'{key}: {json.dumps(value)}')
						props_str = f" {{{', '.join(prop_parts)}}}"
					
					f.write(f'CREATE (:{label} {{id: "{node_id}"{", " + props_str[2:] if props_str else ""}}});\n')
				
				f.write("\n// Create relationships\n")
				for edge in graph_data.get("edges", []):
					source = edge["source"]
					target = edge["target"]
					edge_type = edge.get("type", "CONNECTED_TO")
					properties = edge.get("properties", {})
					
					# Build properties string
					props_str = ""
					if properties:
						prop_parts = []
						for key, value in properties.items():
							if isinstance(value, str):
								prop_parts.append(f'{key}: "{value}"')
							else:
								prop_parts.append(f'{key}: {json.dumps(value)}')
						props_str = f" {{{', '.join(prop_parts)}}}"
					
					f.write(f'MATCH (a {{id: "{source}"}}), (b {{id: "{target}"}}) ')
					f.write(f'CREATE (a)-[:{edge_type}{props_str}]->(b);\n')
			
			return True
			
		except Exception as e:
			logger.error(f"Cypher script export failed: {e}")
			return False


class GraphMLImporter:
	"""GraphML format importer"""
	
	def import_data(self, file_path: str, mapping: ImportMapping) -> Dict[str, Any]:
		"""Import data from GraphML file"""
		try:
			if not NETWORKX_AVAILABLE:
				raise ImportError("NetworkX is required for GraphML import")
			
			# Read GraphML file
			G = nx.read_graphml(file_path)
			
			# Convert to graph data format
			nodes = []
			edges = []
			
			# Process nodes
			for node_id, data in G.nodes(data=True):
				node = {
					"id": str(node_id),
					"label": data.get(mapping.node_label_field, mapping.default_node_label),
					"properties": {}
				}
				
				# Add properties
				for key, value in data.items():
					if key not in mapping.ignore_fields:
						mapped_key = mapping.property_mappings.get(key, key)
						node["properties"][mapped_key] = value
				
				nodes.append(node)
			
			# Process edges
			for source, target, data in G.edges(data=True):
				edge = {
					"source": str(source),
					"target": str(target),
					"type": data.get(mapping.edge_type_field, mapping.default_edge_type),
					"properties": {}
				}
				
				# Add properties
				for key, value in data.items():
					if key not in mapping.ignore_fields and key != mapping.edge_type_field:
						mapped_key = mapping.property_mappings.get(key, key)
						edge["properties"][mapped_key] = value
				
				edges.append(edge)
			
			return {
				"success": True,
				"nodes": nodes,
				"edges": edges,
				"metadata": {
					"source_format": "graphml",
					"node_count": len(nodes),
					"edge_count": len(edges)
				}
			}
			
		except Exception as e:
			logger.error(f"GraphML import failed: {e}")
			return {"success": False, "error": str(e)}


class CSVImporter:
	"""CSV format importer"""
	
	def import_data(self, file_path: str, mapping: ImportMapping) -> Dict[str, Any]:
		"""Import data from CSV files"""
		try:
			base_path = Path(file_path).with_suffix("")
			nodes_file = f"{base_path}_nodes.csv"
			edges_file = f"{base_path}_edges.csv"
			
			nodes = []
			edges = []
			
			# Import nodes
			if Path(nodes_file).exists():
				with open(nodes_file, 'r', encoding='utf-8') as f:
					reader = csv.DictReader(f)
					for row in reader:
						node_id = row.get(mapping.node_id_field, row.get("id"))
						if not node_id:
							continue
						
						node = {
							"id": str(node_id),
							"label": row.get(mapping.node_label_field, mapping.default_node_label),
							"properties": {}
						}
						
						# Add properties
						for key, value in row.items():
							if key not in [mapping.node_id_field, mapping.node_label_field] and key not in mapping.ignore_fields:
								mapped_key = mapping.property_mappings.get(key, key)
								# Try to convert numeric values
								if value and value.replace('.', '').replace('-', '').isdigit():
									try:
										value = float(value) if '.' in value else int(value)
									except ValueError:
										pass
								node["properties"][mapped_key] = value
						
						nodes.append(node)
			
			# Import edges
			if Path(edges_file).exists():
				with open(edges_file, 'r', encoding='utf-8') as f:
					reader = csv.DictReader(f)
					for row in reader:
						source = row.get(mapping.edge_source_field)
						target = row.get(mapping.edge_target_field)
						if not source or not target:
							continue
						
						edge = {
							"source": str(source),
							"target": str(target),
							"type": row.get(mapping.edge_type_field, mapping.default_edge_type),
							"properties": {}
						}
						
						# Add properties
						for key, value in row.items():
							if key not in [mapping.edge_source_field, mapping.edge_target_field, mapping.edge_type_field] and key not in mapping.ignore_fields:
								mapped_key = mapping.property_mappings.get(key, key)
								# Try to convert numeric values
								if value and value.replace('.', '').replace('-', '').isdigit():
									try:
										value = float(value) if '.' in value else int(value)
									except ValueError:
										pass
								edge["properties"][mapped_key] = value
						
						edges.append(edge)
			
			return {
				"success": True,
				"nodes": nodes,
				"edges": edges,
				"metadata": {
					"source_format": "csv",
					"node_count": len(nodes),
					"edge_count": len(edges)
				}
			}
			
		except Exception as e:
			logger.error(f"CSV import failed: {e}")
			return {"success": False, "error": str(e)}


class ImportExportPipeline:
	"""
	Main import/export pipeline coordinator
	
	Manages data exchange operations with progress tracking,
	format conversion, and database integration.
	"""
	
	def __init__(self):
		self.active_jobs: Dict[str, DataExchangeJob] = {}
		self.job_history: List[DataExchangeJob] = []
		self._lock = threading.Lock()
		
		# Initialize format handlers
		self.exporters = {
			ExportFormat.GRAPHML: GraphMLExporter(),
			ExportFormat.GEXF: GEXFExporter(),
			ExportFormat.CSV_NODES_EDGES: CSVExporter(),
			ExportFormat.CYPHER_SCRIPT: CypherScriptExporter(),
			ExportFormat.JSON: self._export_json
		}
		
		self.importers = {
			ImportFormat.GRAPHML: GraphMLImporter(),
			ImportFormat.CSV_NODES_EDGES: CSVImporter(),
			ImportFormat.JSON: self._import_json
		}
	
	def start_export_job(self, graph_name: str, format: ExportFormat, 
						output_path: str, options: Dict[str, Any] = None) -> str:
		"""
		Start graph export job
		
		Args:
			graph_name: Source graph name
			format: Export format
			output_path: Output file path
			options: Export options
			
		Returns:
			Job ID for tracking
		"""
		from uuid_extensions import uuid7str
		
		job_id = uuid7str()
		job = DataExchangeJob(
			job_id=job_id,
			job_type="export",
			format=format.value,
			source=graph_name,
			target=output_path,
			metadata=options or {}
		)
		
		with self._lock:
			self.active_jobs[job_id] = job
		
		# Start export in background thread
		thread = threading.Thread(target=self._execute_export, args=(job,))
		thread.daemon = True
		thread.start()
		
		return job_id
	
	def start_import_job(self, target_graph_name: str, format: ImportFormat,
						source_path: str, mapping: ImportMapping = None,
						options: Dict[str, Any] = None) -> str:
		"""
		Start graph import job
		
		Args:
			target_graph_name: Target graph name
			format: Import format
			source_path: Source file path
			mapping: Field mapping configuration
			options: Import options
			
		Returns:
			Job ID for tracking
		"""
		from uuid_extensions import uuid7str
		
		job_id = uuid7str()
		job = DataExchangeJob(
			job_id=job_id,
			job_type="import",
			format=format.value,
			source=source_path,
			target=target_graph_name,
			metadata={
				"mapping": mapping.__dict__ if mapping else ImportMapping().__dict__,
				**(options or {})
			}
		)
		
		with self._lock:
			self.active_jobs[job_id] = job
		
		# Start import in background thread
		thread = threading.Thread(target=self._execute_import, args=(job,))
		thread.daemon = True
		thread.start()
		
		return job_id
	
	def get_job_status(self, job_id: str) -> Optional[DataExchangeJob]:
		"""Get job status"""
		with self._lock:
			job = self.active_jobs.get(job_id)
			if not job:
				# Check history
				for historical_job in self.job_history:
					if historical_job.job_id == job_id:
						return historical_job
			return job
	
	def cancel_job(self, job_id: str) -> bool:
		"""Cancel active job"""
		with self._lock:
			job = self.active_jobs.get(job_id)
			if job and job.status in [ProcessingStatus.PENDING, ProcessingStatus.PROCESSING]:
				job.status = ProcessingStatus.CANCELLED
				job.completed_at = datetime.now(tz=timezone.utc)
				return True
			return False
	
	def get_active_jobs(self) -> List[DataExchangeJob]:
		"""Get all active jobs"""
		with self._lock:
			return list(self.active_jobs.values())
	
	def get_job_history(self, limit: int = 50) -> List[DataExchangeJob]:
		"""Get job history"""
		with self._lock:
			return self.job_history[:limit]
	
	def _execute_export(self, job: DataExchangeJob):
		"""Execute export job"""
		try:
			job.status = ProcessingStatus.PROCESSING
			job.started_at = datetime.now(tz=timezone.utc)
			job.progress = 10
			
			# Get graph data
			graph_manager = get_graph_manager(job.source)
			graph_data = graph_manager.get_graph_data()
			
			if not graph_data.get("success"):
				raise Exception(f"Failed to get graph data: {graph_data.get('error')}")
			
			job.progress = 50
			
			# Execute export based on format
			format_enum = ExportFormat(job.format)
			exporter = self.exporters.get(format_enum)
			
			if callable(exporter):
				# Function-based exporter
				success = exporter(graph_data, job.target)
			else:
				# Class-based exporter
				success = exporter.export(graph_data, job.target)
			
			if not success:
				raise Exception("Export operation failed")
			
			job.progress = 100
			job.status = ProcessingStatus.COMPLETED
			job.completed_at = datetime.now(tz=timezone.utc)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.DATA_EXPORTED,
				target=f"Graph: {job.source}",
				description=f"Exported graph to {job.format} format",
				details={
					"job_id": job.job_id,
					"format": job.format,
					"output_path": job.target
				}
			)
			
		except Exception as e:
			job.status = ProcessingStatus.FAILED
			job.error_message = str(e)
			job.completed_at = datetime.now(tz=timezone.utc)
			logger.error(f"Export job {job.job_id} failed: {e}")
		
		finally:
			# Move to history
			with self._lock:
				if job.job_id in self.active_jobs:
					del self.active_jobs[job.job_id]
				self.job_history.insert(0, job)
				# Keep only recent history
				if len(self.job_history) > 100:
					self.job_history = self.job_history[:100]
	
	def _execute_import(self, job: DataExchangeJob):
		"""Execute import job"""
		try:
			job.status = ProcessingStatus.PROCESSING
			job.started_at = datetime.now(tz=timezone.utc)
			job.progress = 10
			
			# Parse mapping
			mapping_data = job.metadata.get("mapping", {})
			mapping = ImportMapping(**mapping_data)
			
			# Execute import based on format
			format_enum = ImportFormat(job.format)
			importer = self.importers.get(format_enum)
			
			if callable(importer):
				# Function-based importer
				result = importer(job.source, mapping)
			else:
				# Class-based importer
				result = importer.import_data(job.source, mapping)
			
			if not result.get("success"):
				raise Exception(f"Import failed: {result.get('error')}")
			
			job.progress = 60
			
			# Create or update target graph
			graph_manager = get_graph_manager(job.target)
			
			# Import nodes
			for node in result["nodes"]:
				graph_manager.create_node(
					label=node["label"],
					properties=node["properties"],
					node_id=node["id"]
				)
			
			job.progress = 80
			
			# Import edges
			for edge in result["edges"]:
				graph_manager.create_edge(
					source_id=edge["source"],
					target_id=edge["target"],
					relationship_type=edge["type"],
					properties=edge["properties"]
				)
			
			job.progress = 100
			job.status = ProcessingStatus.COMPLETED
			job.completed_at = datetime.now(tz=timezone.utc)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.DATA_IMPORTED,
				target=f"Graph: {job.target}",
				description=f"Imported graph from {job.format} format",
				details={
					"job_id": job.job_id,
					"format": job.format,
					"source_path": job.source,
					"nodes_imported": len(result["nodes"]),
					"edges_imported": len(result["edges"])
				}
			)
			
		except Exception as e:
			job.status = ProcessingStatus.FAILED
			job.error_message = str(e)
			job.completed_at = datetime.now(tz=timezone.utc)
			logger.error(f"Import job {job.job_id} failed: {e}")
		
		finally:
			# Move to history
			with self._lock:
				if job.job_id in self.active_jobs:
					del self.active_jobs[job.job_id]
				self.job_history.insert(0, job)
				# Keep only recent history
				if len(self.job_history) > 100:
					self.job_history = self.job_history[:100]
	
	def _export_json(self, graph_data: Dict[str, Any], output_path: str) -> bool:
		"""Export to JSON format"""
		try:
			with open(output_path, 'w', encoding='utf-8') as f:
				json.dump(graph_data, f, indent=2, ensure_ascii=False)
			return True
		except Exception as e:
			logger.error(f"JSON export failed: {e}")
			return False
	
	def _import_json(self, file_path: str, mapping: ImportMapping) -> Dict[str, Any]:
		"""Import from JSON format"""
		try:
			with open(file_path, 'r', encoding='utf-8') as f:
				data = json.load(f)
			
			# Assume JSON is already in graph format
			if "nodes" in data and "edges" in data:
				return {
					"success": True,
					"nodes": data["nodes"],
					"edges": data["edges"],
					"metadata": data.get("metadata", {})
				}
			else:
				return {"success": False, "error": "Invalid JSON format"}
				
		except Exception as e:
			logger.error(f"JSON import failed: {e}")
			return {"success": False, "error": str(e)}
	
	@performance_cache(ttl_seconds=3600)
	def get_format_info(self, format_type: str) -> Dict[str, Any]:
		"""Get information about supported formats"""
		format_info = {
			"export_formats": {
				"graphml": {
					"name": "GraphML",
					"description": "XML-based graph format",
					"extensions": [".graphml", ".xml"],
					"supports_properties": True,
					"supports_labels": True
				},
				"gexf": {
					"name": "GEXF",
					"description": "Graph Exchange XML Format",
					"extensions": [".gexf"],
					"supports_properties": True,
					"supports_labels": True
				},
				"csv_nodes_edges": {
					"name": "CSV (Nodes/Edges)",
					"description": "Separate CSV files for nodes and edges",
					"extensions": [".csv"],
					"supports_properties": True,
					"supports_labels": True
				},
				"json": {
					"name": "JSON",
					"description": "JavaScript Object Notation",
					"extensions": [".json"],
					"supports_properties": True,
					"supports_labels": True
				},
				"cypher_script": {
					"name": "Cypher Script",
					"description": "Executable Cypher commands",
					"extensions": [".cypher", ".cql"],
					"supports_properties": True,
					"supports_labels": True
				}
			},
			"import_formats": {
				"graphml": {
					"name": "GraphML",
					"description": "XML-based graph format",
					"extensions": [".graphml", ".xml"],
					"requires_mapping": False
				},
				"csv_nodes_edges": {
					"name": "CSV (Nodes/Edges)",
					"description": "Separate CSV files for nodes and edges",
					"extensions": [".csv"],
					"requires_mapping": True
				},
				"json": {
					"name": "JSON",
					"description": "JavaScript Object Notation",
					"extensions": [".json"],
					"requires_mapping": False
				}
			}
		}
		
		if format_type == "export":
			return format_info["export_formats"]
		elif format_type == "import":
			return format_info["import_formats"]
		else:
			return format_info


# Global pipeline instance
_import_export_pipeline = None


def get_import_export_pipeline() -> ImportExportPipeline:
	"""Get or create global import/export pipeline instance"""
	global _import_export_pipeline
	if _import_export_pipeline is None:
		_import_export_pipeline = ImportExportPipeline()
	return _import_export_pipeline