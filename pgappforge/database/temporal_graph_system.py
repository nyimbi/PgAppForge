"""
Temporal Graph System with Data Versioning

Advanced versioning system for graph data supporting temporal analysis,
change tracking, branching, and time-travel queries across graph evolution.
"""

import logging
import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict
import threading
import bisect

import psycopg2
import networkx as nx
import numpy as np
from pydantic import BaseModel, Field
from uuid_extensions import uuid7str

from ..utils.error_handling import WizardErrorHandler, WizardErrorType, WizardErrorSeverity

logger = logging.getLogger(__name__)


class ChangeType(Enum):
	"""Types of changes in graph evolution"""
	NODE_ADDED = "node_added"
	NODE_REMOVED = "node_removed"
	NODE_UPDATED = "node_updated"
	EDGE_ADDED = "edge_added"
	EDGE_REMOVED = "edge_removed"
	EDGE_UPDATED = "edge_updated"
	PROPERTY_CHANGED = "property_changed"
	LABEL_ADDED = "label_added"
	LABEL_REMOVED = "label_removed"


class SnapshotType(Enum):
	"""Types of graph snapshots"""
	MANUAL = "manual"
	AUTOMATIC = "automatic"
	BRANCH_POINT = "branch_point"
	MILESTONE = "milestone"
	BACKUP = "backup"


@dataclass
class Change:
	"""Individual change record in graph evolution"""
	change_id: str
	timestamp: datetime
	change_type: ChangeType
	graph_name: str
	entity_id: Union[int, str]
	entity_type: str  # "node" or "edge"
	old_value: Optional[Any] = None
	new_value: Optional[Any] = None
	user_id: str = "system"
	session_id: Optional[str] = None
	metadata: Dict[str, Any] = None
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"change_id": self.change_id,
			"timestamp": self.timestamp.isoformat(),
			"change_type": self.change_type.value,
			"graph_name": self.graph_name,
			"entity_id": str(self.entity_id),
			"entity_type": self.entity_type,
			"old_value": self.old_value,
			"new_value": self.new_value,
			"user_id": self.user_id,
			"session_id": self.session_id,
			"metadata": self.metadata or {}
		}


@dataclass
class Snapshot:
	"""Graph snapshot at a specific point in time"""
	snapshot_id: str
	graph_name: str
	timestamp: datetime
	snapshot_type: SnapshotType
	version: str
	branch_name: str
	parent_snapshot_id: Optional[str] = None
	description: str = ""
	metadata: Dict[str, Any] = None
	data_hash: str = ""
	size_bytes: int = 0
	node_count: int = 0
	edge_count: int = 0
	created_by: str = "system"
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"snapshot_id": self.snapshot_id,
			"graph_name": self.graph_name,
			"timestamp": self.timestamp.isoformat(),
			"snapshot_type": self.snapshot_type.value,
			"version": self.version,
			"branch_name": self.branch_name,
			"parent_snapshot_id": self.parent_snapshot_id,
			"description": self.description,
			"metadata": self.metadata or {},
			"data_hash": self.data_hash,
			"size_bytes": self.size_bytes,
			"node_count": self.node_count,
			"edge_count": self.edge_count,
			"created_by": self.created_by
		}


@dataclass
class Branch:
	"""Graph evolution branch"""
	branch_id: str
	branch_name: str
	graph_name: str
	created_at: datetime
	created_by: str
	parent_branch_id: Optional[str] = None
	description: str = ""
	is_active: bool = True
	latest_snapshot_id: Optional[str] = None
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"branch_id": self.branch_id,
			"branch_name": self.branch_name,
			"graph_name": self.graph_name,
			"created_at": self.created_at.isoformat(),
			"created_by": self.created_by,
			"parent_branch_id": self.parent_branch_id,
			"description": self.description,
			"is_active": self.is_active,
			"latest_snapshot_id": self.latest_snapshot_id
		}


class TemporalGraphManager:
	"""Manages temporal aspects and versioning of graphs"""
	
	def __init__(self, graph_name: str, db_connection_string: str = None):
		self.graph_name = graph_name
		self.db_connection_string = db_connection_string
		self.error_handler = WizardErrorHandler()
		
		# In-memory caches for performance
		self.change_log = []
		self.snapshots_cache = {}
		self.branches_cache = {}
		
		# Configuration
		self.auto_snapshot_interval = timedelta(hours=1)
		self.change_log_retention = timedelta(days=90)
		self.max_snapshots_per_branch = 100
		
		# Threading for background tasks
		self.background_thread = None
		self.shutdown_flag = threading.Event()
		
		# Initialize database tables
		self._initialize_temporal_tables()
		
		# Start background tasks
		self._start_background_tasks()
		
		logger.info(f"Temporal graph manager initialized for: {graph_name}")
	
	def _get_db_connection(self):
		"""Get database connection"""
		try:
			if self.db_connection_string:
				return psycopg2.connect(self.db_connection_string)
			else:
				# Use default connection - replace with actual connection logic
				return psycopg2.connect(
					host="localhost",
					database="graph_db",
					user="postgres",
					password="postgres"
				)
		except Exception as e:
			logger.error(f"Failed to connect to database: {e}")
			raise
	
	def _initialize_temporal_tables(self):
		"""Initialize database tables for temporal data"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					# Changes table
					cursor.execute("""
						CREATE TABLE IF NOT EXISTS graph_changes (
							change_id VARCHAR(255) PRIMARY KEY,
							graph_name VARCHAR(255) NOT NULL,
							timestamp TIMESTAMP NOT NULL,
							change_type VARCHAR(50) NOT NULL,
							entity_id VARCHAR(255) NOT NULL,
							entity_type VARCHAR(20) NOT NULL,
							old_value JSONB,
							new_value JSONB,
							user_id VARCHAR(255) DEFAULT 'system',
							session_id VARCHAR(255),
							metadata JSONB DEFAULT '{}'::jsonb,
							INDEX (graph_name, timestamp),
							INDEX (graph_name, entity_id),
							INDEX (timestamp)
						)
					""")
					
					# Snapshots table
					cursor.execute("""
						CREATE TABLE IF NOT EXISTS graph_snapshots (
							snapshot_id VARCHAR(255) PRIMARY KEY,
							graph_name VARCHAR(255) NOT NULL,
							timestamp TIMESTAMP NOT NULL,
							snapshot_type VARCHAR(50) NOT NULL,
							version VARCHAR(100) NOT NULL,
							branch_name VARCHAR(255) NOT NULL,
							parent_snapshot_id VARCHAR(255),
							description TEXT DEFAULT '',
							metadata JSONB DEFAULT '{}'::jsonb,
							data_hash VARCHAR(64) NOT NULL,
							size_bytes BIGINT DEFAULT 0,
							node_count INTEGER DEFAULT 0,
							edge_count INTEGER DEFAULT 0,
							created_by VARCHAR(255) DEFAULT 'system',
							INDEX (graph_name, branch_name, timestamp),
							INDEX (graph_name, version),
							INDEX (data_hash)
						)
					""")
					
					# Branches table
					cursor.execute("""
						CREATE TABLE IF NOT EXISTS graph_branches (
							branch_id VARCHAR(255) PRIMARY KEY,
							branch_name VARCHAR(255) NOT NULL,
							graph_name VARCHAR(255) NOT NULL,
							created_at TIMESTAMP NOT NULL,
							created_by VARCHAR(255) NOT NULL,
							parent_branch_id VARCHAR(255),
							description TEXT DEFAULT '',
							is_active BOOLEAN DEFAULT TRUE,
							latest_snapshot_id VARCHAR(255),
							INDEX (graph_name, branch_name),
							INDEX (graph_name, is_active)
						)
					""")
					
					# Temporal data table for storing snapshot data
					cursor.execute("""
						CREATE TABLE IF NOT EXISTS graph_temporal_data (
							snapshot_id VARCHAR(255) NOT NULL,
							data_type VARCHAR(20) NOT NULL, -- 'nodes' or 'edges'
							entity_id VARCHAR(255) NOT NULL,
							entity_data JSONB NOT NULL,
							INDEX (snapshot_id, data_type),
							INDEX (snapshot_id, entity_id)
						)
					""")
					
					conn.commit()
					logger.info("Temporal database tables initialized")
					
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATABASE_ERROR, WizardErrorSeverity.HIGH
			)
			raise
	
	def record_change(self, change_type: ChangeType, entity_id: Union[int, str], 
					  entity_type: str, old_value: Any = None, new_value: Any = None,
					  user_id: str = "system", session_id: str = None, 
					  metadata: Dict[str, Any] = None) -> str:
		"""Record a change in the graph"""
		try:
			change_id = uuid7str()
			change = Change(
				change_id=change_id,
				timestamp=datetime.now(),
				change_type=change_type,
				graph_name=self.graph_name,
				entity_id=entity_id,
				entity_type=entity_type,
				old_value=old_value,
				new_value=new_value,
				user_id=user_id,
				session_id=session_id,
				metadata=metadata
			)
			
			# Store in database
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						INSERT INTO graph_changes 
						(change_id, graph_name, timestamp, change_type, entity_id, entity_type,
						 old_value, new_value, user_id, session_id, metadata)
						VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
					""", (
						change.change_id,
						change.graph_name,
						change.timestamp,
						change.change_type.value,
						str(change.entity_id),
						change.entity_type,
						json.dumps(change.old_value) if change.old_value is not None else None,
						json.dumps(change.new_value) if change.new_value is not None else None,
						change.user_id,
						change.session_id,
						json.dumps(change.metadata or {})
					))
					conn.commit()
			
			# Add to in-memory cache
			self.change_log.append(change)
			
			logger.debug(f"Recorded change: {change_type.value} for {entity_type} {entity_id}")
			return change_id
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATA_PROCESSING_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	def create_snapshot(self, snapshot_type: SnapshotType = SnapshotType.MANUAL,
						branch_name: str = "main", description: str = "",
						created_by: str = "system", metadata: Dict[str, Any] = None) -> str:
		"""Create a snapshot of the current graph state"""
		try:
			snapshot_id = uuid7str()
			timestamp = datetime.now()
			
			# Get current graph data
			graph_data = self._get_current_graph_data()
			
			# Generate version number
			version = self._generate_version_number(branch_name)
			
			# Calculate hash of graph data
			data_hash = self._calculate_graph_hash(graph_data)
			
			# Get parent snapshot
			parent_snapshot_id = self._get_latest_snapshot_id(branch_name)
			
			snapshot = Snapshot(
				snapshot_id=snapshot_id,
				graph_name=self.graph_name,
				timestamp=timestamp,
				snapshot_type=snapshot_type,
				version=version,
				branch_name=branch_name,
				parent_snapshot_id=parent_snapshot_id,
				description=description,
				metadata=metadata,
				data_hash=data_hash,
				size_bytes=len(json.dumps(graph_data).encode()),
				node_count=len(graph_data.get("nodes", [])),
				edge_count=len(graph_data.get("edges", [])),
				created_by=created_by
			)
			
			# Store snapshot metadata
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						INSERT INTO graph_snapshots 
						(snapshot_id, graph_name, timestamp, snapshot_type, version, branch_name,
						 parent_snapshot_id, description, metadata, data_hash, size_bytes,
						 node_count, edge_count, created_by)
						VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
					""", (
						snapshot.snapshot_id,
						snapshot.graph_name,
						snapshot.timestamp,
						snapshot.snapshot_type.value,
						snapshot.version,
						snapshot.branch_name,
						snapshot.parent_snapshot_id,
						snapshot.description,
						json.dumps(snapshot.metadata or {}),
						snapshot.data_hash,
						snapshot.size_bytes,
						snapshot.node_count,
						snapshot.edge_count,
						snapshot.created_by
					))
					
					# Store graph data
					for node in graph_data.get("nodes", []):
						cursor.execute("""
							INSERT INTO graph_temporal_data 
							(snapshot_id, data_type, entity_id, entity_data)
							VALUES (%s, %s, %s, %s)
						""", (snapshot_id, "nodes", str(node.get("id", "")), json.dumps(node)))
					
					for edge in graph_data.get("edges", []):
						cursor.execute("""
							INSERT INTO graph_temporal_data 
							(snapshot_id, data_type, entity_id, entity_data)
							VALUES (%s, %s, %s, %s)
						""", (snapshot_id, "edges", f"{edge.get('from', '')}-{edge.get('to', '')}", json.dumps(edge)))
					
					conn.commit()
			
			# Update cache
			self.snapshots_cache[snapshot_id] = snapshot
			
			# Update branch latest snapshot
			self._update_branch_latest_snapshot(branch_name, snapshot_id)
			
			logger.info(f"Created snapshot {snapshot_id} ({version}) for branch {branch_name}")
			return snapshot_id
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATA_PROCESSING_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	def create_branch(self, branch_name: str, parent_branch: str = "main",
					  description: str = "", created_by: str = "system") -> str:
		"""Create a new branch from an existing branch"""
		try:
			branch_id = uuid7str()
			
			# Get parent branch info
			parent_branch_info = self._get_branch_info(parent_branch)
			if not parent_branch_info:
				raise ValueError(f"Parent branch '{parent_branch}' not found")
			
			branch = Branch(
				branch_id=branch_id,
				branch_name=branch_name,
				graph_name=self.graph_name,
				created_at=datetime.now(),
				created_by=created_by,
				parent_branch_id=parent_branch_info.get("branch_id"),
				description=description,
				is_active=True,
				latest_snapshot_id=parent_branch_info.get("latest_snapshot_id")
			)
			
			# Store in database
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						INSERT INTO graph_branches 
						(branch_id, branch_name, graph_name, created_at, created_by,
						 parent_branch_id, description, is_active, latest_snapshot_id)
						VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
					""", (
						branch.branch_id,
						branch.branch_name,
						branch.graph_name,
						branch.created_at,
						branch.created_by,
						branch.parent_branch_id,
						branch.description,
						branch.is_active,
						branch.latest_snapshot_id
					))
					conn.commit()
			
			# Update cache
			self.branches_cache[branch_name] = branch
			
			# Create branch point snapshot
			if branch.latest_snapshot_id:
				self.create_snapshot(
					snapshot_type=SnapshotType.BRANCH_POINT,
					branch_name=branch_name,
					description=f"Branch point for {branch_name}",
					created_by=created_by
				)
			
			logger.info(f"Created branch {branch_name} from {parent_branch}")
			return branch_id
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATA_PROCESSING_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	def get_snapshot_data(self, snapshot_id: str) -> Dict[str, Any]:
		"""Retrieve graph data for a specific snapshot"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					# Get snapshot metadata
					cursor.execute("""
						SELECT * FROM graph_snapshots WHERE snapshot_id = %s
					""", (snapshot_id,))
					
					snapshot_row = cursor.fetchone()
					if not snapshot_row:
						raise ValueError(f"Snapshot {snapshot_id} not found")
					
					# Get graph data
					cursor.execute("""
						SELECT data_type, entity_id, entity_data 
						FROM graph_temporal_data 
						WHERE snapshot_id = %s
					""", (snapshot_id,))
					
					data_rows = cursor.fetchall()
					
					# Organize data
					nodes = []
					edges = []
					
					for data_type, entity_id, entity_data in data_rows:
						if data_type == "nodes":
							nodes.append(json.loads(entity_data))
						elif data_type == "edges":
							edges.append(json.loads(entity_data))
					
					return {
						"snapshot_info": {
							"snapshot_id": snapshot_row[0],
							"timestamp": snapshot_row[2].isoformat(),
							"version": snapshot_row[4],
							"branch_name": snapshot_row[5],
							"description": snapshot_row[7]
						},
						"nodes": nodes,
						"edges": edges
					}
					
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATABASE_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	def get_changes_between_snapshots(self, from_snapshot_id: str, 
									  to_snapshot_id: str) -> List[Change]:
		"""Get all changes between two snapshots"""
		try:
			# Get snapshot timestamps
			from_timestamp = self._get_snapshot_timestamp(from_snapshot_id)
			to_timestamp = self._get_snapshot_timestamp(to_snapshot_id)
			
			if not from_timestamp or not to_timestamp:
				raise ValueError("One or both snapshots not found")
			
			# Ensure proper order
			if from_timestamp > to_timestamp:
				from_timestamp, to_timestamp = to_timestamp, from_timestamp
			
			changes = []
			
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT * FROM graph_changes 
						WHERE graph_name = %s 
						AND timestamp > %s AND timestamp <= %s
						ORDER BY timestamp ASC
					""", (self.graph_name, from_timestamp, to_timestamp))
					
					rows = cursor.fetchall()
					
					for row in rows:
						change = Change(
							change_id=row[0],
							timestamp=row[2],
							change_type=ChangeType(row[3]),
							graph_name=row[1],
							entity_id=row[4],
							entity_type=row[5],
							old_value=json.loads(row[6]) if row[6] else None,
							new_value=json.loads(row[7]) if row[7] else None,
							user_id=row[8],
							session_id=row[9],
							metadata=json.loads(row[10]) if row[10] else {}
						)
						changes.append(change)
			
			return changes
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATABASE_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	def time_travel_query(self, cypher_query: str, target_time: datetime) -> Dict[str, Any]:
		"""Execute a query against graph state at a specific time"""
		try:
			# Find the snapshot closest to target time
			snapshot_id = self._find_closest_snapshot(target_time)
			
			if not snapshot_id:
				raise ValueError(f"No snapshot found near time {target_time}")
			
			# Get graph data at that time
			snapshot_data = self.get_snapshot_data(snapshot_id)
			
			# Create temporary graph for query execution
			temp_graph = self._create_networkx_graph(snapshot_data)
			
			# Execute query (simplified - in production would use actual Cypher engine)
			query_result = self._execute_temporal_query(cypher_query, temp_graph, snapshot_data)
			
			return {
				"query": cypher_query,
				"target_time": target_time.isoformat(),
				"snapshot_used": snapshot_id,
				"snapshot_time": snapshot_data["snapshot_info"]["timestamp"],
				"results": query_result
			}
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.QUERY_EXECUTION_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	def analyze_graph_evolution(self, time_range_hours: int = 24) -> Dict[str, Any]:
		"""Analyze how the graph has evolved over time"""
		try:
			end_time = datetime.now()
			start_time = end_time - timedelta(hours=time_range_hours)
			
			# Get changes in time range
			changes = []
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT * FROM graph_changes 
						WHERE graph_name = %s 
						AND timestamp >= %s AND timestamp <= %s
						ORDER BY timestamp ASC
					""", (self.graph_name, start_time, end_time))
					
					rows = cursor.fetchall()
					for row in rows:
						changes.append({
							"timestamp": row[2].isoformat(),
							"change_type": row[3],
							"entity_type": row[5],
							"user_id": row[8]
						})
			
			# Analyze patterns
			change_counts = defaultdict(int)
			hourly_activity = defaultdict(int)
			user_activity = defaultdict(int)
			entity_type_changes = defaultdict(int)
			
			for change in changes:
				change_type = change["change_type"]
				change_counts[change_type] += 1
				
				timestamp = datetime.fromisoformat(change["timestamp"])
				hour_key = timestamp.strftime("%Y-%m-%d %H:00")
				hourly_activity[hour_key] += 1
				
				user_activity[change["user_id"]] += 1
				entity_type_changes[change["entity_type"]] += 1
			
			# Get snapshots in range
			snapshots = self._get_snapshots_in_range(start_time, end_time)
			
			return {
				"time_range": {
					"start": start_time.isoformat(),
					"end": end_time.isoformat(),
					"hours": time_range_hours
				},
				"total_changes": len(changes),
				"change_breakdown": dict(change_counts),
				"hourly_activity": dict(hourly_activity),
				"user_activity": dict(user_activity),
				"entity_type_changes": dict(entity_type_changes),
				"snapshots_created": len(snapshots),
				"average_changes_per_hour": len(changes) / time_range_hours if time_range_hours > 0 else 0,
				"most_active_user": max(user_activity.items(), key=lambda x: x[1])[0] if user_activity else None,
				"most_common_change": max(change_counts.items(), key=lambda x: x[1])[0] if change_counts else None
			}
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATA_PROCESSING_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	def get_branch_history(self, branch_name: str = "main") -> List[Dict[str, Any]]:
		"""Get history of snapshots for a branch"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT * FROM graph_snapshots 
						WHERE graph_name = %s AND branch_name = %s
						ORDER BY timestamp DESC
					""", (self.graph_name, branch_name))
					
					rows = cursor.fetchall()
					
					history = []
					for row in rows:
						history.append({
							"snapshot_id": row[0],
							"timestamp": row[2].isoformat(),
							"snapshot_type": row[3],
							"version": row[4],
							"description": row[7],
							"node_count": row[11],
							"edge_count": row[12],
							"size_bytes": row[10],
							"created_by": row[13]
						})
					
					return history
					
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATABASE_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	def merge_branches(self, source_branch: str, target_branch: str, 
					   merge_strategy: str = "auto", created_by: str = "system") -> Dict[str, Any]:
		"""Merge changes from source branch into target branch"""
		try:
			# Get branch information
			source_info = self._get_branch_info(source_branch)
			target_info = self._get_branch_info(target_branch)
			
			if not source_info or not target_info:
				raise ValueError("Source or target branch not found")
			
			# Get changes to merge
			merge_point = self._find_merge_point(source_branch, target_branch)
			
			if merge_point:
				changes_to_merge = self.get_changes_between_snapshots(
					merge_point, source_info["latest_snapshot_id"]
				)
			else:
				# No common ancestor - this would be a complex merge
				raise ValueError("Branches have no common merge point")
			
			# Apply merge strategy
			if merge_strategy == "auto":
				conflicts = self._detect_merge_conflicts(changes_to_merge, target_branch)
				if conflicts:
					return {
						"success": False,
						"conflicts": conflicts,
						"message": "Automatic merge failed due to conflicts"
					}
			
			# Perform merge (simplified implementation)
			merge_snapshot_id = self.create_snapshot(
				snapshot_type=SnapshotType.MILESTONE,
				branch_name=target_branch,
				description=f"Merged {source_branch} into {target_branch}",
				created_by=created_by,
				metadata={
					"merge_source": source_branch,
					"merge_target": target_branch,
					"merge_strategy": merge_strategy,
					"changes_merged": len(changes_to_merge)
				}
			)
			
			return {
				"success": True,
				"merge_snapshot_id": merge_snapshot_id,
				"changes_merged": len(changes_to_merge),
				"message": f"Successfully merged {source_branch} into {target_branch}"
			}
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATA_PROCESSING_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	def cleanup_old_data(self, retention_days: int = 90) -> Dict[str, Any]:
		"""Clean up old temporal data based on retention policy"""
		try:
			cutoff_date = datetime.now() - timedelta(days=retention_days)
			
			deleted_counts = {
				"changes": 0,
				"snapshots": 0,
				"temporal_data": 0
			}
			
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					# Get old snapshots to delete (keep at least one per branch)
					cursor.execute("""
						WITH ranked_snapshots AS (
							SELECT snapshot_id, branch_name, timestamp,
								   ROW_NUMBER() OVER (PARTITION BY branch_name ORDER BY timestamp DESC) as rn
							FROM graph_snapshots 
							WHERE graph_name = %s AND timestamp < %s
						)
						SELECT snapshot_id FROM ranked_snapshots WHERE rn > 1
					""", (self.graph_name, cutoff_date))
					
					old_snapshots = [row[0] for row in cursor.fetchall()]
					
					# Delete old changes
					cursor.execute("""
						DELETE FROM graph_changes 
						WHERE graph_name = %s AND timestamp < %s
					""", (self.graph_name, cutoff_date))
					deleted_counts["changes"] = cursor.rowcount
					
					# Delete temporal data for old snapshots
					if old_snapshots:
						cursor.execute("""
							DELETE FROM graph_temporal_data 
							WHERE snapshot_id = ANY(%s)
						""", (old_snapshots,))
						deleted_counts["temporal_data"] = cursor.rowcount
						
						# Delete old snapshots
						cursor.execute("""
							DELETE FROM graph_snapshots 
							WHERE snapshot_id = ANY(%s)
						""", (old_snapshots,))
						deleted_counts["snapshots"] = cursor.rowcount
					
					conn.commit()
			
			logger.info(f"Cleanup completed for {self.graph_name}: {deleted_counts}")
			return {
				"success": True,
				"retention_days": retention_days,
				"cutoff_date": cutoff_date.isoformat(),
				"deleted_counts": deleted_counts
			}
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATABASE_ERROR, WizardErrorSeverity.MEDIUM
			)
			raise
	
	# Helper methods
	
	def _get_current_graph_data(self) -> Dict[str, Any]:
		"""Get current graph data (mock implementation)"""
		# This would interface with the actual graph storage
		# For now, return mock data
		return {
			"nodes": [
				{"id": 1, "name": "Alice", "type": "Person"},
				{"id": 2, "name": "Bob", "type": "Person"}
			],
			"edges": [
				{"from": 1, "to": 2, "type": "KNOWS"}
			]
		}
	
	def _generate_version_number(self, branch_name: str) -> str:
		"""Generate version number for snapshot"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT version FROM graph_snapshots 
						WHERE graph_name = %s AND branch_name = %s
						ORDER BY timestamp DESC LIMIT 1
					""", (self.graph_name, branch_name))
					
					row = cursor.fetchone()
					if row:
						last_version = row[0]
						# Extract version number and increment
						if "." in last_version:
							parts = last_version.split(".")
							parts[-1] = str(int(parts[-1]) + 1)
							return ".".join(parts)
						else:
							return f"{last_version}.1"
					else:
						return "1.0"
		except:
			return f"{branch_name}.1"
	
	def _calculate_graph_hash(self, graph_data: Dict[str, Any]) -> str:
		"""Calculate hash of graph data for deduplication"""
		try:
			data_str = json.dumps(graph_data, sort_keys=True)
			return hashlib.sha256(data_str.encode()).hexdigest()
		except:
			return ""
	
	def _get_latest_snapshot_id(self, branch_name: str) -> Optional[str]:
		"""Get latest snapshot ID for branch"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT snapshot_id FROM graph_snapshots 
						WHERE graph_name = %s AND branch_name = %s
						ORDER BY timestamp DESC LIMIT 1
					""", (self.graph_name, branch_name))
					
					row = cursor.fetchone()
					return row[0] if row else None
		except:
			return None
	
	def _get_branch_info(self, branch_name: str) -> Optional[Dict[str, Any]]:
		"""Get branch information"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT * FROM graph_branches 
						WHERE graph_name = %s AND branch_name = %s
					""", (self.graph_name, branch_name))
					
					row = cursor.fetchone()
					if row:
						return {
							"branch_id": row[0],
							"branch_name": row[1],
							"latest_snapshot_id": row[8]
						}
					return None
		except:
			return None
	
	def _update_branch_latest_snapshot(self, branch_name: str, snapshot_id: str):
		"""Update branch's latest snapshot reference"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						UPDATE graph_branches 
						SET latest_snapshot_id = %s 
						WHERE graph_name = %s AND branch_name = %s
					""", (snapshot_id, self.graph_name, branch_name))
					conn.commit()
		except Exception as e:
			logger.error(f"Failed to update branch latest snapshot: {e}")
	
	def _get_snapshot_timestamp(self, snapshot_id: str) -> Optional[datetime]:
		"""Get snapshot timestamp"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT timestamp FROM graph_snapshots WHERE snapshot_id = %s
					""", (snapshot_id,))
					
					row = cursor.fetchone()
					return row[0] if row else None
		except:
			return None
	
	def _find_closest_snapshot(self, target_time: datetime) -> Optional[str]:
		"""Find snapshot closest to target time"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT snapshot_id, ABS(EXTRACT(EPOCH FROM (timestamp - %s))) as time_diff
						FROM graph_snapshots 
						WHERE graph_name = %s
						ORDER BY time_diff ASC
						LIMIT 1
					""", (target_time, self.graph_name))
					
					row = cursor.fetchone()
					return row[0] if row else None
		except:
			return None
	
	def _create_networkx_graph(self, snapshot_data: Dict[str, Any]) -> nx.Graph:
		"""Create NetworkX graph from snapshot data"""
		G = nx.Graph()
		
		# Add nodes
		for node in snapshot_data.get("nodes", []):
			G.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})
		
		# Add edges
		for edge in snapshot_data.get("edges", []):
			G.add_edge(edge["from"], edge["to"], **{k: v for k, v in edge.items() if k not in ["from", "to"]})
		
		return G
	
	def _execute_temporal_query(self, query: str, graph: nx.Graph, snapshot_data: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""Execute query against temporal graph (simplified implementation)"""
		# This would integrate with actual Cypher query engine
		# For now, return basic graph statistics
		return [
			{
				"node_count": graph.number_of_nodes(),
				"edge_count": graph.number_of_edges(),
				"density": nx.density(graph),
				"snapshot_info": snapshot_data["snapshot_info"]
			}
		]
	
	def _get_snapshots_in_range(self, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
		"""Get snapshots in time range"""
		try:
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT snapshot_id, timestamp, version, branch_name
						FROM graph_snapshots 
						WHERE graph_name = %s 
						AND timestamp >= %s AND timestamp <= %s
						ORDER BY timestamp ASC
					""", (self.graph_name, start_time, end_time))
					
					return [
						{
							"snapshot_id": row[0],
							"timestamp": row[1].isoformat(),
							"version": row[2],
							"branch_name": row[3]
						}
						for row in cursor.fetchall()
					]
		except:
			return []
	
	def _find_merge_point(self, branch1: str, branch2: str) -> Optional[str]:
		"""Find common ancestor snapshot between branches"""
		# Simplified implementation - would trace back through parent snapshots
		return None
	
	def _detect_merge_conflicts(self, changes: List[Change], target_branch: str) -> List[Dict[str, Any]]:
		"""Detect conflicts when merging changes"""
		# Simplified implementation - would analyze overlapping changes
		return []
	
	def _start_background_tasks(self):
		"""Start background tasks for maintenance"""
		def background_worker():
			while not self.shutdown_flag.is_set():
				try:
					# Auto-snapshot if needed
					self._check_auto_snapshot()
					
					# Cleanup old data
					if datetime.now().hour == 2:  # Daily cleanup at 2 AM
						self.cleanup_old_data()
					
					# Sleep for 5 minutes
					self.shutdown_flag.wait(300)
					
				except Exception as e:
					logger.error(f"Background task error: {e}")
					self.shutdown_flag.wait(60)  # Wait 1 minute on error
		
		self.background_thread = threading.Thread(target=background_worker, daemon=True)
		self.background_thread.start()
	
	def _check_auto_snapshot(self):
		"""Check if auto-snapshot is needed"""
		try:
			# Get last snapshot time
			with self._get_db_connection() as conn:
				with conn.cursor() as cursor:
					cursor.execute("""
						SELECT timestamp FROM graph_snapshots 
						WHERE graph_name = %s AND snapshot_type = 'automatic'
						ORDER BY timestamp DESC LIMIT 1
					""", (self.graph_name,))
					
					row = cursor.fetchone()
					last_auto_snapshot = row[0] if row else None
					
					# Create auto-snapshot if needed
					if not last_auto_snapshot or datetime.now() - last_auto_snapshot > self.auto_snapshot_interval:
						self.create_snapshot(
							snapshot_type=SnapshotType.AUTOMATIC,
							description="Automatic periodic snapshot"
						)
		except Exception as e:
			logger.error(f"Auto-snapshot check failed: {e}")
	
	def shutdown(self):
		"""Shutdown temporal graph manager"""
		self.shutdown_flag.set()
		if self.background_thread:
			self.background_thread.join(timeout=10)
		logger.info(f"Temporal graph manager shut down for: {self.graph_name}")


# Global registry for temporal managers
_temporal_managers = {}


def get_temporal_manager(graph_name: str) -> TemporalGraphManager:
	"""Get temporal manager for a graph"""
	if graph_name not in _temporal_managers:
		_temporal_managers[graph_name] = TemporalGraphManager(graph_name)
	return _temporal_managers[graph_name]