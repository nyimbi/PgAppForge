"""
Federated Analytics View

Flask view for the federated graph analytics system.
Provides interface for managing distributed graph analysis across multiple nodes.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.federated_analytics import (
	get_federated_analytics,
	create_federation_network,
	execute_cross_organizational_query,
	FederatedNode,
	NodeRole,
	FederationProtocol,
	DataSovereignty
)
from ..database.activity_tracker import (
	track_database_activity,
	ActivityType,
	ActivitySeverity
)
from ..utils.error_handling import (
	WizardErrorHandler,
	WizardErrorType,
	WizardErrorSeverity
)

logger = logging.getLogger(__name__)


class FederatedAnalyticsView(BaseView):
	"""
	Federated analytics interface
	
	Provides comprehensive interface for managing distributed graph
	analysis across multiple nodes while preserving data sovereignty.
	"""
	
	route_base = "/federated"
	default_view = "index"
	
	def __init__(self):
		"""Initialize federated analytics view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		
	def _ensure_admin_access(self):
		"""Ensure current user has admin privileges"""
		try:
			from flask_login import current_user
			
			if not current_user or not current_user.is_authenticated:
				raise Forbidden("Authentication required")
			
			# Check if user has admin role
			if hasattr(current_user, "roles"):
				admin_roles = ["Admin", "admin", "Administrator", "administrator"]
				user_roles = [
					role.name if hasattr(role, "name") else str(role)
					for role in current_user.roles
				]
				
				if not any(role in admin_roles for role in user_roles):
					raise Forbidden("Administrator privileges required")
			else:
				# Fallback check for is_admin attribute
				if not getattr(current_user, "is_admin", False):
					raise Forbidden("Administrator privileges required")
					
		except Exception as e:
			logger.error(f"Admin access check failed: {e}")
			raise Forbidden("Access denied")

	def _get_current_user_id(self) -> str:
		"""Get current user ID"""
		try:
			from flask_login import current_user
			if current_user and current_user.is_authenticated:
				return str(current_user.id) if hasattr(current_user, 'id') else str(current_user)
			return "admin"
		except:
			return "admin"

	@expose("/")
	@has_access
	@permission_name("can_manage_federation")
	def index(self):
		"""Main federated analytics dashboard"""
		try:
			self._ensure_admin_access()
			
			# Get federated analytics instance
			federation = get_federated_analytics()
			
			# Get network topology
			network_topology = federation.get_network_topology()
			
			# Get federation metrics
			federation_metrics = federation.get_federation_metrics()
			
			# Get recent federated activities
			recent_activities = self._get_recent_activities()
			
			# Get available node types and configurations
			node_configurations = self._get_node_configurations()
			
			return render_template(
				"federated/index.html",
				title="Federated Graph Analytics",
				network_topology=network_topology,
				federation_metrics=federation_metrics,
				recent_activities=recent_activities,
				node_configurations=node_configurations,
				node_roles=self._get_node_roles(),
				protocols=self._get_federation_protocols(),
				sovereignty_levels=self._get_sovereignty_levels()
			)
			
		except Exception as e:
			logger.error(f"Error in federated dashboard: {e}")
			flash(f"Error loading federated dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))

	@expose("/network/")
	@has_access
	@permission_name("can_view_federation_network")
	def network_topology(self):
		"""Network topology visualization"""
		try:
			self._ensure_admin_access()
			
			federation = get_federated_analytics()
			topology = federation.get_network_topology()
			
			# Get detailed node information
			detailed_nodes = self._get_detailed_node_info()
			
			# Get network performance metrics
			performance_metrics = self._get_network_performance()
			
			return render_template(
				"federated/network.html",
				title="Federation Network Topology",
				topology=topology,
				detailed_nodes=detailed_nodes,
				performance_metrics=performance_metrics
			)
			
		except Exception as e:
			logger.error(f"Error in network topology: {e}")
			flash(f"Error loading network topology: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))

	@expose("/queries/")
	@has_access
	@permission_name("can_execute_federated_queries")
	def query_interface(self):
		"""Federated query execution interface"""
		try:
			self._ensure_admin_access()
			
			federation = get_federated_analytics()
			
			# Get active queries
			active_queries = self._get_active_queries()
			
			# Get query history
			query_history = self._get_query_history()
			
			# Get available nodes for querying
			available_nodes = federation.get_network_topology()["nodes"]
			
			return render_template(
				"federated/queries.html",
				title="Federated Query Interface",
				active_queries=active_queries,
				query_history=query_history,
				available_nodes=available_nodes,
				privacy_levels=self._get_privacy_levels(),
				aggregation_functions=self._get_aggregation_functions()
			)
			
		except Exception as e:
			logger.error(f"Error in query interface: {e}")
			flash(f"Error loading query interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))

	def _get_recent_activities(self) -> List[Dict[str, Any]]:
		"""Get recent federated activities"""
		# Mock implementation - would query activity history
		return [
			{
				"timestamp": "2024-01-15T14:30:00",
				"action": "Federated Query Executed",
				"details": "Cross-organizational analysis across 5 nodes",
				"nodes_involved": 5,
				"privacy_level": "strict",
				"status": "completed"
			},
			{
				"timestamp": "2024-01-15T13:45:00",
				"action": "Node Registered",
				"details": "Healthcare organization joined federation",
				"nodes_involved": 1,
				"privacy_level": "controlled",
				"status": "active"
			},
			{
				"timestamp": "2024-01-15T12:20:00",
				"action": "Secure Aggregation",
				"details": "Multi-party computation completed",
				"nodes_involved": 8,
				"privacy_level": "strict",
				"status": "completed"
			}
		]

	def _get_node_configurations(self) -> List[Dict[str, Any]]:
		"""Get available node configurations"""
		return [
			{
				"name": "Healthcare Provider",
				"role": "participant",
				"protocol": "rest_api",
				"sovereignty": "strict",
				"capabilities": ["patient_data", "clinical_research", "privacy_preservation"],
				"description": "Healthcare organization with strict privacy requirements"
			},
			{
				"name": "Research Institution",
				"role": "coordinator",
				"protocol": "graphql",
				"sovereignty": "controlled",
				"capabilities": ["academic_research", "data_analysis", "collaboration"],
				"description": "Academic institution coordinating research efforts"
			},
			{
				"name": "Government Agency",
				"role": "validator",
				"protocol": "secure_messaging",
				"sovereignty": "controlled",
				"capabilities": ["compliance_validation", "audit_trail", "security_monitoring"],
				"description": "Government entity ensuring compliance and security"
			}
		]

	def _get_detailed_node_info(self) -> List[Dict[str, Any]]:
		"""Get detailed information about federation nodes"""
		federation = get_federated_analytics()
		detailed_info = []
		
		for node_id, node in federation.nodes.items():
			detailed_info.append({
				"node_id": node_id,
				"name": node.name,
				"endpoint": node.endpoint,
				"role": node.role.value,
				"protocol": node.protocol.value,
				"sovereignty": node.sovereignty_level.value,
				"trust_score": node.trust_score,
				"capabilities": node.capabilities,
				"last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None,
				"status": "online" if node.trust_score > 0.5 else "offline",
				"metadata": node.metadata
			})
		
		return detailed_info

	def _get_network_performance(self) -> Dict[str, Any]:
		"""Get network performance metrics"""
		federation = get_federated_analytics()
		metrics = federation.get_federation_metrics()
		
		return {
			"query_throughput": metrics.get("completed_queries", 0) / max(1, metrics.get("average_query_time_seconds", 1)),
			"network_latency": 0.25,  # Mock latency in seconds
			"success_rate": 0.96,  # Mock success rate
			"data_transfer_mb": 1234.5,  # Mock data transfer
			"privacy_compliance": 100.0,  # Mock compliance percentage
			"uptime_percentage": 99.2  # Mock uptime
		}

	def _get_active_queries(self) -> List[Dict[str, Any]]:
		"""Get currently active federated queries"""
		# Mock implementation - would query federation instance
		return [
			{
				"query_id": "fed_query_001",
				"query_text": "SELECT COUNT(*) FROM patients WHERE condition = 'diabetes'",
				"requester": "research_node_01",
				"target_nodes": ["hospital_a", "clinic_b", "health_center_c"],
				"privacy_level": "strict",
				"status": "running",
				"progress": 75,
				"started_at": "2024-01-15T14:25:00"
			}
		]

	def _get_query_history(self) -> List[Dict[str, Any]]:
		"""Get federated query history"""
		# Mock implementation
		return [
			{
				"query_id": "fed_query_002",
				"query_text": "SELECT AVG(age) FROM patients",
				"requester": "analytics_node",
				"nodes_participated": 6,
				"privacy_level": "controlled",
				"aggregation": "secure_average",
				"completed_at": "2024-01-15T13:45:00",
				"execution_time": 12.5,
				"results_count": 1,
				"status": "completed"
			},
			{
				"query_id": "fed_query_003",
				"query_text": "SELECT medication, COUNT(*) FROM prescriptions GROUP BY medication",
				"requester": "pharma_research",
				"nodes_participated": 4,
				"privacy_level": "strict",
				"aggregation": "k_anonymous_count",
				"completed_at": "2024-01-15T12:30:00",
				"execution_time": 8.2,
				"results_count": 25,
				"status": "completed"
			}
		]

	def _get_node_roles(self) -> List[Dict[str, str]]:
		"""Get available node roles"""
		return [
			{"value": "coordinator", "name": "Coordinator", "description": "Orchestrates federated operations"},
			{"value": "participant", "name": "Participant", "description": "Contributes data to federated analysis"},
			{"value": "observer", "name": "Observer", "description": "Monitors federation without contributing data"},
			{"value": "validator", "name": "Validator", "description": "Validates results and ensures compliance"}
		]

	def _get_federation_protocols(self) -> List[Dict[str, str]]:
		"""Get available federation protocols"""
		return [
			{"value": "rest_api", "name": "REST API", "description": "Standard HTTP REST protocol"},
			{"value": "graphql", "name": "GraphQL", "description": "Flexible query language protocol"},
			{"value": "secure_messaging", "name": "Secure Messaging", "description": "End-to-end encrypted messaging"},
			{"value": "blockchain", "name": "Blockchain", "description": "Blockchain-based verification"}
		]

	def _get_sovereignty_levels(self) -> List[Dict[str, str]]:
		"""Get data sovereignty levels"""
		return [
			{"value": "strict", "name": "Strict", "description": "Data never leaves origin node"},
			{"value": "controlled", "name": "Controlled", "description": "Metadata and aggregates can be shared"},
			{"value": "collaborative", "name": "Collaborative", "description": "Processed data can be shared"},
			{"value": "open", "name": "Open", "description": "Full data sharing allowed"}
		]

	def _get_privacy_levels(self) -> List[Dict[str, str]]:
		"""Get privacy protection levels"""
		return [
			{"value": "none", "name": "None", "description": "No privacy protection"},
			{"value": "standard", "name": "Standard", "description": "Basic privacy controls"},
			{"value": "high", "name": "High", "description": "Advanced privacy preservation"},
			{"value": "strict", "name": "Strict", "description": "Maximum privacy with differential privacy"}
		]

	def _get_aggregation_functions(self) -> List[Dict[str, str]]:
		"""Get available aggregation functions"""
		return [
			{"value": "sum", "name": "Sum", "description": "Sum values across nodes"},
			{"value": "count", "name": "Count", "description": "Count records across nodes"},
			{"value": "average", "name": "Average", "description": "Calculate average across nodes"},
			{"value": "secure_sum", "name": "Secure Sum", "description": "Privacy-preserving sum using MPC"}
		]

	# API Endpoints

	@expose_api("post", "/api/register-node/")
	@has_access
	@permission_name("can_register_federation_nodes")
	def api_register_node(self):
		"""API endpoint to register a new federation node"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			user_id = self._get_current_user_id()
			federation = get_federated_analytics()
			
			# Create federated node
			node = FederatedNode(
				node_id=data.get("node_id"),
				name=data.get("name"),
				endpoint=data.get("endpoint"),
				role=NodeRole(data.get("role", "participant")),
				protocol=FederationProtocol(data.get("protocol", "rest_api")),
				sovereignty_level=DataSovereignty(data.get("sovereignty", "controlled")),
				capabilities=data.get("capabilities", []),
				metadata=data.get("metadata", {})
			)
			
			# Register node
			success = federation.register_node(node)
			
			if success:
				# Track activity
				track_database_activity(
					activity_type=ActivityType.FEDERATION_NODE_REGISTERED,
					target=f"Node: {node.node_id}",
					description=f"Federation node registered: {node.name}",
					details={
						"user_id": user_id,
						"node_id": node.node_id,
						"node_name": node.name,
						"role": node.role.value,
						"protocol": node.protocol.value
					}
				)
				
				return jsonify({
					"success": True,
					"node_id": node.node_id,
					"message": f"Node '{node.name}' registered successfully"
				})
			else:
				raise Exception("Failed to register node")
			
		except Exception as e:
			logger.error(f"API error registering node: {e}")
			return jsonify({"success": False, "error": str(e)}), 500

	@expose_api("post", "/api/execute-query/")
	@has_access
	@permission_name("can_execute_federated_queries")
	def api_execute_federated_query(self):
		"""API endpoint to execute federated query"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			query_text = data.get("query_text")
			target_nodes = data.get("target_nodes", [])
			privacy_level = data.get("privacy_level", "standard")
			aggregation_function = data.get("aggregation_function")
			timeout_seconds = data.get("timeout_seconds", 60)
			
			if not query_text:
				raise BadRequest("Query text is required")
			
			user_id = self._get_current_user_id()
			federation = get_federated_analytics()
			
			# Execute federated query
			query = federation.execute_federated_query(
				query_text=query_text,
				target_nodes=target_nodes,
				privacy_level=privacy_level,
				aggregation_function=aggregation_function,
				timeout_seconds=timeout_seconds
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.FEDERATED_QUERY_STARTED,
				target=f"Query: {query.query_id}",
				description="Federated query execution started",
				details={
					"user_id": user_id,
					"query_id": query.query_id,
					"target_nodes": len(query.target_nodes),
					"privacy_level": privacy_level,
					"has_aggregation": aggregation_function is not None
				}
			)
			
			return jsonify({
				"success": True,
				"query_id": query.query_id,
				"target_nodes": len(query.target_nodes),
				"privacy_level": privacy_level,
				"message": "Federated query started successfully"
			})
			
		except Exception as e:
			logger.error(f"API error executing federated query: {e}")
			return jsonify({"success": False, "error": str(e)}), 500

	@expose_api("get", "/api/query-status/<query_id>/")
	@has_access
	@permission_name("can_view_query_status")
	def api_get_query_status(self, query_id):
		"""API endpoint to get query status"""
		try:
			self._ensure_admin_access()
			
			federation = get_federated_analytics()
			status = federation.get_query_status(query_id)
			
			if status:
				return jsonify({
					"success": True,
					"status": status
				})
			else:
				return jsonify({
					"success": False,
					"error": "Query not found"
				}), 404
				
		except Exception as e:
			logger.error(f"API error getting query status: {e}")
			return jsonify({"success": False, "error": str(e)}), 500

	@expose_api("post", "/api/cross-organizational-query/")
	@has_access
	@permission_name("can_execute_cross_org_queries")
	def api_cross_organizational_query(self):
		"""API endpoint for cross-organizational queries"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			query_text = data.get("query_text")
			organizations = data.get("organizations", [])
			privacy_level = data.get("privacy_level", "standard")
			aggregation = data.get("aggregation")
			
			if not query_text:
				raise BadRequest("Query text is required")
			
			if not organizations:
				raise BadRequest("Organizations list is required")
			
			user_id = self._get_current_user_id()
			
			# Execute cross-organizational query
			result = execute_cross_organizational_query(
				query=query_text,
				organizations=organizations,
				privacy_level=privacy_level,
				aggregation=aggregation
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.CROSS_ORG_QUERY_EXECUTED,
				target=f"Organizations: {', '.join(organizations)}",
				description="Cross-organizational query executed",
				details={
					"user_id": user_id,
					"query_id": result.get("query_id"),
					"organizations": organizations,
					"privacy_level": privacy_level,
					"target_nodes": result.get("target_nodes", 0)
				}
			)
			
			return jsonify({
				"success": True,
				"result": result,
				"message": f"Cross-organizational query started for {len(organizations)} organizations"
			})
			
		except Exception as e:
			logger.error(f"API error in cross-organizational query: {e}")
			return jsonify({"success": False, "error": str(e)}), 500

	@expose_api("get", "/api/network-topology/")
	@has_access
	@permission_name("can_view_federation_network")
	def api_get_network_topology(self):
		"""API endpoint to get network topology"""
		try:
			self._ensure_admin_access()
			
			federation = get_federated_analytics()
			topology = federation.get_network_topology()
			
			return jsonify({
				"success": True,
				"topology": topology
			})
			
		except Exception as e:
			logger.error(f"API error getting network topology: {e}")
			return jsonify({"success": False, "error": str(e)}), 500

	@expose_api("get", "/api/federation-metrics/")
	@has_access
	@permission_name("can_view_federation_metrics")
	def api_get_federation_metrics(self):
		"""API endpoint to get federation metrics"""
		try:
			self._ensure_admin_access()
			
			federation = get_federated_analytics()
			metrics = federation.get_federation_metrics()
			
			return jsonify({
				"success": True,
				"metrics": metrics
			})
			
		except Exception as e:
			logger.error(f"API error getting federation metrics: {e}")
			return jsonify({"success": False, "error": str(e)}), 500