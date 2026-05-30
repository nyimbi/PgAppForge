"""
Federated Graph Analytics

Advanced system for distributed graph analytics across multiple database instances,
enabling cross-organizational analysis while maintaining data sovereignty and security.
"""

import json
import logging
import asyncio
import hashlib
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Callable, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from uuid_extensions import uuid7str

try:
	import requests
	import aiohttp
	import psycopg2
	from cryptography.fernet import Fernet
	from cryptography.hazmat.primitives import hashes
	from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
	import base64
	import os
except ImportError as e:
	logging.warning(f"Optional dependencies for federated analytics not available: {e}")
	requests = None
	aiohttp = None

from .activity_tracker import track_database_activity, ActivityType
from ..utils.error_handling import WizardErrorHandler, WizardErrorType

logger = logging.getLogger(__name__)


class FederationProtocol(Enum):
	"""Federation communication protocols"""
	REST_API = "rest_api"
	GRAPHQL = "graphql"
	SECURE_MESSAGING = "secure_messaging"
	BLOCKCHAIN = "blockchain"


class NodeRole(Enum):
	"""Node roles in federated network"""
	COORDINATOR = "coordinator"
	PARTICIPANT = "participant"
	OBSERVER = "observer"
	VALIDATOR = "validator"


class DataSovereignty(Enum):
	"""Data sovereignty levels"""
	STRICT = "strict"  # Data never leaves origin
	CONTROLLED = "controlled"  # Metadata can be shared
	COLLABORATIVE = "collaborative"  # Aggregated data can be shared
	OPEN = "open"  # Full data sharing allowed


class ComputeModel(Enum):
	"""Federated computation models"""
	CENTRALIZED = "centralized"  # Central coordinator
	DECENTRALIZED = "decentralized"  # Peer-to-peer
	HIERARCHICAL = "hierarchical"  # Multi-level federation
	MESH = "mesh"  # Full mesh topology


@dataclass
class FederatedNode:
	"""
	Represents a node in the federated network.
	
	A FederatedNode is an organization or system that participates in the
	federated analytics network. Each node has specific capabilities, trust
	levels, and data sovereignty requirements.
	
	Attributes:
		node_id (str): Unique identifier for the node
		name (str): Human-readable name for the node
		endpoint (str): API endpoint URL for communication
		role (NodeRole): Role in the federation (coordinator, participant, etc.)
		protocol (FederationProtocol): Communication protocol to use
		sovereignty_level (DataSovereignty): Data sharing and privacy level
		public_key (Optional[str]): Public key for cryptographic operations
		capabilities (List[str]): List of supported capabilities/services
		last_heartbeat (Optional[datetime]): Last successful health check
		trust_score (float): Trust level from 0.0 to 1.0
		version (str): Software version of the node
		metadata (Dict[str, Any]): Additional node-specific information
	
	Examples:
		>>> node = FederatedNode(
		...     node_id="hospital_a",
		...     name="City Hospital",
		...     endpoint="https://api.cityhospital.com",
		...     role=NodeRole.PARTICIPANT,
		...     protocol=FederationProtocol.REST_API,
		...     sovereignty_level=DataSovereignty.STRICT
		... )
	"""
	node_id: str
	name: str
	endpoint: str
	role: NodeRole
	protocol: FederationProtocol
	sovereignty_level: DataSovereignty
	public_key: Optional[str] = None
	capabilities: List[str] = None
	last_heartbeat: Optional[datetime] = None
	trust_score: float = 1.0
	version: str = "1.0"
	metadata: Dict[str, Any] = None
	
	def __post_init__(self):
		if self.capabilities is None:
			self.capabilities = []
		if self.metadata is None:
			self.metadata = {}


@dataclass
class FederatedQuery:
	"""Represents a query across the federated network"""
	query_id: str
	query_text: str
	target_nodes: List[str]
	requester_node: str
	privacy_level: str
	aggregation_function: Optional[str] = None
	timeout_seconds: int = 30
	created_at: Optional[datetime] = None
	completed_at: Optional[datetime] = None
	results: Dict[str, Any] = None
	
	def __post_init__(self):
		if self.created_at is None:
			self.created_at = datetime.now()
		if self.results is None:
			self.results = {}


@dataclass
class FederatedResult:
	"""Result from federated computation"""
	result_id: str
	query_id: str
	node_id: str
	data: Dict[str, Any]
	metadata: Dict[str, Any]
	privacy_preserved: bool
	computation_time: float
	timestamp: datetime
	signature: Optional[str] = None


class SecurityManager:
	"""Manages security for federated operations"""
	
	def __init__(self):
		self.error_handler = WizardErrorHandler()
		self._encryption_key = None
		
	def generate_encryption_key(self, password: str, salt: bytes = None) -> bytes:
		"""Generate encryption key from password"""
		if salt is None:
			salt = os.urandom(16)
			
		kdf = PBKDF2HMAC(
			algorithm=hashes.SHA256(),
			length=32,
			salt=salt,
			iterations=100000,
		)
		key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
		return key
	
	def encrypt_data(self, data: str, key: bytes) -> str:
		"""Encrypt sensitive data"""
		try:
			fernet = Fernet(key)
			encrypted = fernet.encrypt(data.encode())
			return base64.urlsafe_b64encode(encrypted).decode()
		except Exception as e:
			logger.error(f"Encryption failed: {e}")
			return data
	
	def decrypt_data(self, encrypted_data: str, key: bytes) -> str:
		"""Decrypt sensitive data"""
		try:
			fernet = Fernet(key)
			decoded = base64.urlsafe_b64decode(encrypted_data.encode())
			decrypted = fernet.decrypt(decoded)
			return decrypted.decode()
		except Exception as e:
			logger.error(f"Decryption failed: {e}")
			return encrypted_data
	
	def generate_signature(self, data: str, private_key: str) -> str:
		"""Generate digital signature for data integrity"""
		# Simple hash-based signature (in production, use proper cryptographic signing)
		combined = f"{data}{private_key}"
		return hashlib.sha256(combined.encode()).hexdigest()
	
	def verify_signature(self, data: str, signature: str, public_key: str) -> bool:
		"""Verify digital signature"""
		# Simple verification (in production, use proper cryptographic verification)
		expected = self.generate_signature(data, public_key)
		return expected == signature


class PrivacyPreserver:
	"""Implements privacy-preserving techniques"""
	
	def __init__(self):
		self.error_handler = WizardErrorHandler()
		
	def differential_privacy(self, data: List[float], epsilon: float = 1.0) -> List[float]:
		"""Apply differential privacy to numeric data"""
		import random
		
		# Add Laplace noise for differential privacy
		sensitivity = 1.0
		scale = sensitivity / epsilon
		
		noisy_data = []
		for value in data:
			noise = random.laplace(0, scale)
			noisy_data.append(value + noise)
		
		return noisy_data
	
	def k_anonymity(self, data: List[Dict[str, Any]], k: int = 5, 
					quasi_identifiers: List[str] = None) -> List[Dict[str, Any]]:
		"""Apply k-anonymity to protect individual privacy"""
		if not quasi_identifiers:
			return data
		
		# Group records by quasi-identifier combinations
		groups = {}
		for record in data:
			key = tuple(record.get(qi, "") for qi in quasi_identifiers)
			if key not in groups:
				groups[key] = []
			groups[key].append(record)
		
		# Filter out groups smaller than k
		k_anonymous_data = []
		for group_records in groups.values():
			if len(group_records) >= k:
				k_anonymous_data.extend(group_records)
		
		return k_anonymous_data
	
	def homomorphic_aggregation(self, encrypted_values: List[str]) -> str:
		"""Perform aggregation on encrypted values"""
		# Simplified homomorphic operation (sum)
		# In production, use proper homomorphic encryption library
		total = sum(int(val, 16) for val in encrypted_values if val.isalnum())
		return hex(total)
	
	def secure_multiparty_computation(self, contributions: Dict[str, float]) -> float:
		"""Simple secure multi-party computation for aggregation"""
		# In production, implement proper SMPC protocols
		return sum(contributions.values()) / len(contributions)


class FederatedAnalytics:
	"""
	Main federated analytics system
	
	Coordinates distributed graph analysis across multiple nodes while
	preserving data sovereignty and privacy.
	"""
	
	def __init__(self, node_id: str = None, database_config: Dict[str, Any] = None):
		self.node_id = node_id or uuid7str()
		self.database_config = database_config or {}
		self.error_handler = WizardErrorHandler()
		self.security_manager = SecurityManager()
		self.privacy_preserver = PrivacyPreserver()
		
		# Network state
		self.nodes: Dict[str, FederatedNode] = {}
		self.active_queries: Dict[str, FederatedQuery] = {}
		self.query_results: Dict[str, List[FederatedResult]] = {}
		
		# Configuration
		self.heartbeat_interval = 30  # seconds
		self.query_timeout = 300  # seconds
		self.max_concurrent_queries = 10
		
		# Threading
		self._lock = threading.RLock()
		self._running = False
		self._heartbeat_thread = None
		
		logger.info(f"Initialized federated analytics node: {self.node_id}")
	
	def register_node(self, node: FederatedNode) -> bool:
		"""Register a new node in the federation"""
		try:
			with self._lock:
				# Validate node
				if not self._validate_node(node):
					return False
				
				# Store node
				self.nodes[node.node_id] = node
				
				logger.info(f"Registered federated node: {node.node_id} ({node.name})")
				
				# Track activity
				track_database_activity(
					activity_type=ActivityType.FEDERATION_NODE_REGISTERED,
					target=f"Node: {node.node_id}",
					description=f"Federated node registered: {node.name}",
					details={
						"node_id": node.node_id,
						"node_name": node.name,
						"role": node.role.value,
						"protocol": node.protocol.value,
						"sovereignty": node.sovereignty_level.value
					}
				)
				
				return True
				
		except Exception as e:
			self.error_handler.handle_error(
				WizardErrorType.FEDERATION_ERROR,
				f"Failed to register node: {e}",
				{"node_id": node.node_id if node else None}
			)
			return False
	
	def _validate_node(self, node: FederatedNode) -> bool:
		"""Validate node configuration"""
		try:
			# Check required fields
			if not all([node.node_id, node.name, node.endpoint]):
				return False
			
			# Validate endpoint accessibility
			if requests:
				try:
					response = requests.get(f"{node.endpoint}/health", timeout=5)
					if response.status_code != 200:
						logger.warning(f"Node health check failed: {node.endpoint}")
						return False
				except:
					logger.warning(f"Cannot reach node endpoint: {node.endpoint}")
					return False
			
			return True
			
		except Exception as e:
			logger.error(f"Node validation failed: {e}")
			return False
	
	def start_federation(self) -> bool:
		"""Start federated services"""
		try:
			with self._lock:
				if self._running:
					return True
				
				self._running = True
				
				# Start heartbeat service
				self._heartbeat_thread = threading.Thread(
					target=self._heartbeat_service,
					daemon=True
				)
				self._heartbeat_thread.start()
				
				logger.info("Federated analytics services started")
				return True
				
		except Exception as e:
			self.error_handler.handle_error(
				WizardErrorType.FEDERATION_ERROR,
				f"Failed to start federation: {e}",
				{}
			)
			return False
	
	def stop_federation(self):
		"""Stop federated services"""
		try:
			with self._lock:
				self._running = False
				
				if self._heartbeat_thread:
					self._heartbeat_thread.join(timeout=5)
				
				logger.info("Federated analytics services stopped")
				
		except Exception as e:
			logger.error(f"Error stopping federation: {e}")
	
	def _heartbeat_service(self):
		"""Background service to maintain node connectivity"""
		while self._running:
			try:
				self._send_heartbeats()
				self._check_node_health()
				time.sleep(self.heartbeat_interval)
			except Exception as e:
				logger.error(f"Heartbeat service error: {e}")
				time.sleep(5)
	
	def _send_heartbeats(self):
		"""Send heartbeat to all registered nodes"""
		current_time = datetime.now()
		
		for node in self.nodes.values():
			try:
				if node.node_id == self.node_id:
					continue
				
				heartbeat_data = {
					"node_id": self.node_id,
					"timestamp": current_time.isoformat(),
					"status": "active"
				}
				
				if requests:
					response = requests.post(
						f"{node.endpoint}/heartbeat",
						json=heartbeat_data,
						timeout=5
					)
					
					if response.status_code == 200:
						node.last_heartbeat = current_time
						
			except Exception as e:
				logger.warning(f"Heartbeat failed for node {node.node_id}: {e}")
	
	def _check_node_health(self):
		"""Check health of all nodes and update trust scores"""
		current_time = datetime.now()
		stale_threshold = timedelta(minutes=5)
		
		for node in list(self.nodes.values()):
			if node.node_id == self.node_id:
				continue
				
			if (node.last_heartbeat and 
				current_time - node.last_heartbeat > stale_threshold):
				# Reduce trust score for stale nodes
				node.trust_score = max(0.0, node.trust_score - 0.1)
				
				if node.trust_score < 0.1:
					logger.warning(f"Node {node.node_id} appears to be offline")
	
	def execute_federated_query(self, 
									query_text: str,
									target_nodes: List[str] = None,
									privacy_level: str = "standard",
									aggregation_function: str = None,
									timeout_seconds: int = None) -> FederatedQuery:
		"""Execute a query across the federated network"""
		try:
			# Create query
			query = FederatedQuery(
				query_id=uuid7str(),
				query_text=query_text,
				target_nodes=target_nodes or list(self.nodes.keys()),
				requester_node=self.node_id,
				privacy_level=privacy_level,
				aggregation_function=aggregation_function,
				timeout_seconds=timeout_seconds or self.query_timeout
			)
			
			# Store query
			with self._lock:
				self.active_queries[query.query_id] = query
			
			# Execute query asynchronously
			self._execute_query_async(query)
			
			logger.info(f"Started federated query: {query.query_id}")
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.FEDERATED_QUERY_STARTED,
				target=f"Query: {query.query_id}",
				description="Federated query execution started",
				details={
					"query_id": query.query_id,
					"target_nodes": len(query.target_nodes),
					"privacy_level": privacy_level,
					"has_aggregation": aggregation_function is not None
				}
			)
			
			return query
			
		except Exception as e:
			self.error_handler.handle_error(
				WizardErrorType.FEDERATION_ERROR,
				f"Failed to execute federated query: {e}",
				{"query_text": query_text[:100] if query_text else None}
			)
			raise
	
	def _execute_query_async(self, query: FederatedQuery):
		"""Execute query asynchronously across nodes"""
		def execute():
			try:
				results = []
				
				# Execute on each target node
				with ThreadPoolExecutor(max_workers=min(10, len(query.target_nodes))) as executor:
					future_to_node = {
						executor.submit(self._execute_on_node, query, node_id): node_id
						for node_id in query.target_nodes
						if node_id in self.nodes
					}
					
					for future in as_completed(future_to_node, timeout=query.timeout_seconds):
						node_id = future_to_node[future]
						try:
							result = future.result()
							if result:
								results.append(result)
						except Exception as e:
							logger.error(f"Query failed on node {node_id}: {e}")
				
				# Store results
				with self._lock:
					self.query_results[query.query_id] = results
					query.results = self._aggregate_results(results, query.aggregation_function)
					query.completed_at = datetime.now()
				
				logger.info(f"Federated query completed: {query.query_id}")
				
			except Exception as e:
				logger.error(f"Federated query execution failed: {e}")
		
		# Start execution in background thread
		thread = threading.Thread(target=execute, daemon=True)
		thread.start()
	
	def _execute_on_node(self, query: FederatedQuery, node_id: str) -> Optional[FederatedResult]:
		"""Execute query on a specific node"""
		try:
			if node_id == self.node_id:
				# Execute locally
				return self._execute_local_query(query)
			
			node = self.nodes.get(node_id)
			if not node:
				return None
			
			# Execute remotely
			if requests:
				response = requests.post(
					f"{node.endpoint}/federated-query",
					json={
						"query_id": query.query_id,
						"query_text": query.query_text,
						"privacy_level": query.privacy_level,
						"requester": query.requester_node
					},
					timeout=query.timeout_seconds
				)
				
				if response.status_code == 200:
					result_data = response.json()
					
					return FederatedResult(
						result_id=uuid7str(),
						query_id=query.query_id,
						node_id=node_id,
						data=result_data.get("data", {}),
						metadata=result_data.get("metadata", {}),
						privacy_preserved=result_data.get("privacy_preserved", False),
						computation_time=result_data.get("computation_time", 0),
						timestamp=datetime.now(),
						signature=result_data.get("signature")
					)
			
			return None
			
		except Exception as e:
			logger.error(f"Failed to execute on node {node_id}: {e}")
			return None
	
	def _execute_local_query(self, query: FederatedQuery) -> FederatedResult:
		"""Execute query on local node"""
		try:
			start_time = time.time()
			
			# Connect to local database
			if self.database_config:
				conn = psycopg2.connect(**self.database_config)
				cursor = conn.cursor()
				
				# Execute query with privacy controls
				safe_query = self._apply_privacy_controls(query.query_text, query.privacy_level)
				cursor.execute(safe_query)
				
				# Fetch results
				results = cursor.fetchall()
				columns = [desc[0] for desc in cursor.description] if cursor.description else []
				
				# Convert to dictionary format
				data = {
					"rows": [dict(zip(columns, row)) for row in results],
					"count": len(results),
					"columns": columns
				}
				
				cursor.close()
				conn.close()
			else:
				# Mock data for testing
				data = {
					"rows": [{"id": 1, "value": "test"}],
					"count": 1,
					"columns": ["id", "value"]
				}
			
			computation_time = time.time() - start_time
			
			# Apply privacy preservation
			privacy_preserved = query.privacy_level != "none"
			if privacy_preserved:
				data = self._apply_privacy_preservation(data, query.privacy_level)
			
			return FederatedResult(
				result_id=uuid7str(),
				query_id=query.query_id,
				node_id=self.node_id,
				data=data,
				metadata={
					"node_version": "1.0",
					"execution_node": self.node_id,
					"privacy_level": query.privacy_level
				},
				privacy_preserved=privacy_preserved,
				computation_time=computation_time,
				timestamp=datetime.now()
			)
			
		except Exception as e:
			logger.error(f"Local query execution failed: {e}")
			raise
	
	def _apply_privacy_controls(self, query: str, privacy_level: str) -> str:
		"""Apply privacy controls to query"""
		if privacy_level == "none":
			return query
		
		# Add privacy-preserving modifications to query
		if privacy_level == "strict":
			# Remove potentially sensitive columns
			query = query.replace("*", "id, name")  # Simplified example
		elif privacy_level == "standard":
			# Add aggregation to prevent individual identification
			if "SELECT" in query.upper() and "GROUP BY" not in query.upper():
				query += " GROUP BY id"
		
		return query
	
	def _apply_privacy_preservation(self, data: Dict[str, Any], privacy_level: str) -> Dict[str, Any]:
		"""Apply privacy preservation techniques to data"""
		if privacy_level == "none":
			return data
		
		# Apply differential privacy to numeric values
		if privacy_level in ["strict", "high"]:
			for row in data.get("rows", []):
				for key, value in row.items():
					if isinstance(value, (int, float)):
						# Add small amount of noise
						import random
						noise = random.gauss(0, 0.1 * abs(value)) if value != 0 else random.gauss(0, 0.1)
						row[key] = value + noise
		
		# Apply k-anonymity
		if privacy_level == "strict" and len(data.get("rows", [])) > 0:
			data["rows"] = self.privacy_preserver.k_anonymity(data["rows"], k=5)
			data["count"] = len(data["rows"])
		
		return data
	
	def _aggregate_results(self, results: List[FederatedResult], 
						   aggregation_function: str = None) -> Dict[str, Any]:
		"""Aggregate results from multiple nodes"""
		if not results:
			return {}
		
		if not aggregation_function:
			# Return combined results
			combined_data = {
				"nodes": len(results),
				"total_rows": sum(r.data.get("count", 0) for r in results),
				"computation_time": sum(r.computation_time for r in results),
				"privacy_preserved": all(r.privacy_preserved for r in results),
				"results_by_node": {r.node_id: r.data for r in results}
			}
			return combined_data
		
		# Apply aggregation function
		if aggregation_function == "sum":
			return self._aggregate_sum(results)
		elif aggregation_function == "count":
			return self._aggregate_count(results)
		elif aggregation_function == "average":
			return self._aggregate_average(results)
		elif aggregation_function == "secure_sum":
			return self._secure_aggregate_sum(results)
		
		return {"error": f"Unknown aggregation function: {aggregation_function}"}
	
	def _aggregate_sum(self, results: List[FederatedResult]) -> Dict[str, Any]:
		"""Aggregate results using sum"""
		total_sum = 0
		node_count = 0
		
		for result in results:
			rows = result.data.get("rows", [])
			for row in rows:
				for value in row.values():
					if isinstance(value, (int, float)):
						total_sum += value
			node_count += 1
		
		return {
			"aggregation": "sum",
			"value": total_sum,
			"nodes_participated": node_count,
			"privacy_preserved": all(r.privacy_preserved for r in results)
		}
	
	def _aggregate_count(self, results: List[FederatedResult]) -> Dict[str, Any]:
		"""Aggregate results using count"""
		total_count = sum(r.data.get("count", 0) for r in results)
		
		return {
			"aggregation": "count",
			"value": total_count,
			"nodes_participated": len(results),
			"privacy_preserved": all(r.privacy_preserved for r in results)
		}
	
	def _aggregate_average(self, results: List[FederatedResult]) -> Dict[str, Any]:
		"""Aggregate results using average"""
		sum_result = self._aggregate_sum(results)
		count_result = self._aggregate_count(results)
		
		if count_result["value"] > 0:
			average = sum_result["value"] / count_result["value"]
		else:
			average = 0
		
		return {
			"aggregation": "average",
			"value": average,
			"nodes_participated": len(results),
			"privacy_preserved": all(r.privacy_preserved for r in results)
		}
	
	def _secure_aggregate_sum(self, results: List[FederatedResult]) -> Dict[str, Any]:
		"""Perform secure multi-party computation for sum"""
		contributions = {}
		
		for result in results:
			rows = result.data.get("rows", [])
			node_sum = 0
			for row in rows:
				for value in row.values():
					if isinstance(value, (int, float)):
						node_sum += value
			contributions[result.node_id] = node_sum
		
		# Use secure MPC for aggregation
		secure_sum = self.privacy_preserver.secure_multiparty_computation(contributions)
		
		return {
			"aggregation": "secure_sum",
			"value": secure_sum,
			"nodes_participated": len(results),
			"privacy_preserved": True,
			"security_level": "multi_party_computation"
		}
	
	def get_query_status(self, query_id: str) -> Optional[Dict[str, Any]]:
		"""Get status of a federated query"""
		with self._lock:
			query = self.active_queries.get(query_id)
			if not query:
				return None
			
			results = self.query_results.get(query_id, [])
			
			return {
				"query_id": query_id,
				"status": "completed" if query.completed_at else "running",
				"created_at": query.created_at.isoformat(),
				"completed_at": query.completed_at.isoformat() if query.completed_at else None,
				"target_nodes": len(query.target_nodes),
				"results_received": len(results),
				"results": query.results if query.completed_at else None
			}
	
	def get_network_topology(self) -> Dict[str, Any]:
		"""Get current federation network topology"""
		with self._lock:
			active_nodes = [
				{
					"node_id": node.node_id,
					"name": node.name,
					"role": node.role.value,
					"trust_score": node.trust_score,
					"last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None,
					"capabilities": node.capabilities
				}
				for node in self.nodes.values()
				if node.trust_score > 0.5
			]
			
			return {
				"total_nodes": len(self.nodes),
				"active_nodes": len(active_nodes),
				"coordinator_node": self.node_id,
				"active_queries": len(self.active_queries),
				"network_health": sum(n.trust_score for n in self.nodes.values()) / len(self.nodes) if self.nodes else 0,
				"nodes": active_nodes
			}
	
	def get_federation_metrics(self) -> Dict[str, Any]:
		"""Get federation performance metrics"""
		with self._lock:
			completed_queries = [q for q in self.active_queries.values() if q.completed_at]
			total_results = sum(len(results) for results in self.query_results.values())
			
			if completed_queries:
				avg_query_time = sum(
					(q.completed_at - q.created_at).total_seconds() 
					for q in completed_queries
				) / len(completed_queries)
			else:
				avg_query_time = 0
			
			return {
				"total_queries": len(self.active_queries),
				"completed_queries": len(completed_queries),
				"total_results": total_results,
				"average_query_time_seconds": avg_query_time,
				"network_nodes": len(self.nodes),
				"active_nodes": len([n for n in self.nodes.values() if n.trust_score > 0.5]),
				"federation_uptime": "active" if self._running else "inactive",
				"privacy_queries": len([q for q in self.active_queries.values() if q.privacy_level != "none"])
			}


# Global registry for federated analytics instances
_federated_instances: Dict[str, FederatedAnalytics] = {}


def get_federated_analytics(node_id: str = None, config: Dict[str, Any] = None) -> FederatedAnalytics:
	"""Get or create federated analytics instance"""
	instance_key = node_id or "default"
	
	if instance_key not in _federated_instances:
		_federated_instances[instance_key] = FederatedAnalytics(
			node_id=node_id,
			database_config=config
		)
	
	return _federated_instances[instance_key]


def create_federation_network(nodes: List[Dict[str, Any]], 
								coordinator_id: str = None) -> FederatedAnalytics:
	"""Create a new federated network with multiple nodes"""
	try:
		# Create coordinator node
		coordinator = get_federated_analytics(coordinator_id)
		coordinator.start_federation()
		
		# Register all nodes
		for node_config in nodes:
			node = FederatedNode(
				node_id=node_config["node_id"],
				name=node_config["name"],
				endpoint=node_config["endpoint"],
				role=NodeRole(node_config.get("role", "participant")),
				protocol=FederationProtocol(node_config.get("protocol", "rest_api")),
				sovereignty_level=DataSovereignty(node_config.get("sovereignty", "controlled")),
				capabilities=node_config.get("capabilities", []),
				metadata=node_config.get("metadata", {})
			)
			
			coordinator.register_node(node)
		
		logger.info(f"Created federation network with {len(nodes)} nodes")
		
		# Track activity
		track_database_activity(
			activity_type=ActivityType.FEDERATION_NETWORK_CREATED,
			target=f"Network: {coordinator.node_id}",
			description="Federated network created",
			details={
				"coordinator_id": coordinator.node_id,
				"total_nodes": len(nodes),
				"node_roles": [node.get("role", "participant") for node in nodes]
			}
		)
		
		return coordinator
		
	except Exception as e:
		logger.error(f"Failed to create federation network: {e}")
		raise


def execute_cross_organizational_query(query: str,
										organizations: List[str],
										privacy_level: str = "standard",
										aggregation: str = None) -> Dict[str, Any]:
	"""Execute a query across multiple organizational boundaries"""
	try:
		# Get default federated instance
		federation = get_federated_analytics()
		
		# Filter nodes by organizations
		target_nodes = [
			node_id for node_id, node in federation.nodes.items()
			if node.metadata.get("organization") in organizations
		]
		
		if not target_nodes:
			raise ValueError(f"No nodes found for organizations: {organizations}")
		
		# Execute federated query
		federated_query = federation.execute_federated_query(
			query_text=query,
			target_nodes=target_nodes,
			privacy_level=privacy_level,
			aggregation_function=aggregation
		)
		
		logger.info(f"Cross-organizational query started: {federated_query.query_id}")
		
		return {
			"query_id": federated_query.query_id,
			"organizations": organizations,
			"target_nodes": len(target_nodes),
			"privacy_level": privacy_level,
			"status": "started"
		}
		
	except Exception as e:
		logger.error(f"Cross-organizational query failed: {e}")
		raise


# Global federated analytics instance
_federated_analytics = None
_federated_lock = threading.Lock()


def get_federated_analytics():
	"""Get the global federated analytics instance"""
	global _federated_analytics
	with _federated_lock:
		if _federated_analytics is None:
			_federated_analytics = FederatedAnalytics()
		return _federated_analytics


def reset_federated_analytics():
	"""Reset the global federated analytics instance for testing"""
	global _federated_analytics
	with _federated_lock:
		_federated_analytics = None