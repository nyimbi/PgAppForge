"""
Performance Optimization View for Graph Operations

Provides web interface for monitoring performance, configuring optimizations,
and analyzing execution metrics for graph database operations.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.performance_optimizer import (
	get_query_optimizer,
	get_parallel_processor,
	get_performance_monitor,
	get_distributed_processor,
	OptimizationType,
	CacheStrategy,
	ProcessingMode,
	performance_cache
)
from ..database.graph_manager import get_graph_manager
from ..database.multi_graph_manager import get_graph_registry
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


class PerformanceOptimizationView(BaseView):
	"""
	Performance optimization interface for graph operations
	
	Provides monitoring, caching configuration, query optimization,
	and performance analytics with comprehensive web interface.
	"""
	
	route_base = "/graph/performance"
	default_view = "index"
	
	def __init__(self):
		"""Initialize performance view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		self.query_optimizer = None
		self.performance_monitor = None
	
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
	
	def _get_query_optimizer(self):
		"""Get or initialize query optimizer"""
		try:
			return get_query_optimizer()
		except Exception as e:
			logger.error(f"Failed to initialize query optimizer: {e}")
			self.error_handler.handle_error(
				e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
			)
			raise
	
	def _get_performance_monitor(self):
		"""Get or initialize performance monitor"""
		try:
			return get_performance_monitor()
		except Exception as e:
			logger.error(f"Failed to initialize performance monitor: {e}")
			raise
	
	@expose("/")
	@has_access
	@permission_name("can_optimize_performance")
	def index(self):
		"""Performance optimization dashboard"""
		try:
			self._ensure_admin_access()
			
			optimizer = self._get_query_optimizer()
			monitor = self._get_performance_monitor()
			
			# Get available graphs
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			
			# Get performance summary
			performance_summary = monitor.get_performance_summary()
			
			# Get cache statistics
			cache_stats = optimizer.execution_cache.get_stats()
			
			# Get optimization types and strategies
			optimization_types = [
				{
					"value": opt_type.value,
					"name": opt_type.value.replace("_", " ").title()
				}
				for opt_type in OptimizationType
			]
			
			cache_strategies = [
				{
					"value": strategy.value,
					"name": strategy.value.upper()
				}
				for strategy in CacheStrategy
			]
			
			processing_modes = [
				{
					"value": mode.value,
					"name": mode.value.replace("_", " ").title()
				}
				for mode in ProcessingMode
			]
			
			return render_template(
				"performance/index.html",
				title="Performance Optimization",
				graphs=[graph.to_dict() for graph in graphs],
				performance_summary=performance_summary,
				cache_stats=cache_stats,
				optimization_types=optimization_types,
				cache_strategies=cache_strategies,
				processing_modes=processing_modes
			)
			
		except Exception as e:
			logger.error(f"Error in performance dashboard: {e}")
			flash(f"Error loading performance dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/optimization/")
	@has_access
	@permission_name("can_optimize_performance")
	def optimization(self):
		"""Query optimization interface"""
		try:
			self._ensure_admin_access()
			
			# Get available graphs
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			
			return render_template(
				"performance/optimization.html",
				title="Query Optimization",
				graphs=[graph.to_dict() for graph in graphs]
			)
			
		except Exception as e:
			logger.error(f"Error in optimization interface: {e}")
			flash(f"Error loading optimization interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/monitoring/")
	@has_access
	@permission_name("can_optimize_performance")
	def monitoring(self):
		"""Performance monitoring interface"""
		try:
			self._ensure_admin_access()
			
			monitor = self._get_performance_monitor()
			
			# Get recent performance metrics
			performance_summary = monitor.get_performance_summary()
			
			return render_template(
				"performance/monitoring.html",
				title="Performance Monitoring",
				performance_summary=performance_summary
			)
			
		except Exception as e:
			logger.error(f"Error in monitoring interface: {e}")
			flash(f"Error loading monitoring interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/caching/")
	@has_access
	@permission_name("can_optimize_performance")
	def caching(self):
		"""Cache management interface"""
		try:
			self._ensure_admin_access()
			
			optimizer = self._get_query_optimizer()
			cache_stats = optimizer.execution_cache.get_stats()
			
			return render_template(
				"performance/caching.html",
				title="Cache Management",
				cache_stats=cache_stats
			)
			
		except Exception as e:
			logger.error(f"Error in caching interface: {e}")
			flash(f"Error loading caching interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	# API Endpoints
	
	@expose_api("post", "/api/optimize-query/")
	@has_access
	@permission_name("can_optimize_performance")
	def api_optimize_query(self):
		"""API endpoint to optimize Cypher query"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			query = data.get("query")
			graph_name = data.get("graph_name")
			
			if not query:
				raise BadRequest("query is required")
			
			optimizer = self._get_query_optimizer()
			result = optimizer.optimize_query(query, graph_name)
			
			# Track optimization activity
			track_database_activity(
				activity_type=ActivityType.QUERY_EXECUTED,
				target=f"Query Optimization: {graph_name or 'unknown'}",
				description=f"Optimized query with {len(result.get('applied_optimizations', []))} improvements",
				details={
					"original_query": query[:200] + "..." if len(query) > 200 else query,
					"optimizations_applied": len(result.get("applied_optimizations", [])),
					"complexity_score": result.get("complexity_score", 0)
				}
			)
			
			return jsonify({
				"success": True,
				"optimization_result": result
			})
			
		except Exception as e:
			logger.error(f"API error optimizing query: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/execute-optimized/")
	@has_access
	@permission_name("can_optimize_performance")
	def api_execute_optimized(self):
		"""API endpoint to execute optimized query with monitoring"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			query = data.get("query")
			graph_name = data.get("graph_name")
			parameters = data.get("parameters", {})
			
			if not query or not graph_name:
				raise BadRequest("query and graph_name are required")
			
			optimizer = self._get_query_optimizer()
			monitor = self._get_performance_monitor()
			
			# Check cache first
			cached_result = optimizer.get_cached_result(query, parameters)
			if cached_result:
				return jsonify({
					"success": True,
					"result": cached_result,
					"from_cache": True
				})
			
			# Start performance monitoring
			operation_id = monitor.start_operation("optimized_query_execution")
			
			# Optimize query
			optimization_result = optimizer.optimize_query(query, graph_name)
			optimized_query = optimization_result["optimized_query"]
			
			# Execute query
			graph_manager = get_graph_manager(graph_name)
			result = graph_manager.execute_cypher_query(optimized_query, parameters)
			
			# End monitoring
			metrics = monitor.end_operation(
				operation_id,
				cache_hit=False,
				optimizations=[opt["rule"] for opt in optimization_result.get("applied_optimizations", [])]
			)
			
			# Cache result
			if result.get("success"):
				optimizer.cache_query_result(query, parameters, result)
			
			return jsonify({
				"success": True,
				"result": result,
				"optimization_result": optimization_result,
				"performance_metrics": metrics.to_dict() if metrics else None,
				"from_cache": False
			})
			
		except Exception as e:
			logger.error(f"API error executing optimized query: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/performance-summary/")
	@has_access
	@permission_name("can_optimize_performance")
	def api_get_performance_summary(self):
		"""API endpoint to get performance summary"""
		try:
			self._ensure_admin_access()
			
			operation_type = request.args.get("operation_type")
			hours_back = int(request.args.get("hours_back", 24))
			
			monitor = self._get_performance_monitor()
			summary = monitor.get_performance_summary(operation_type, hours_back)
			
			return jsonify({
				"success": True,
				"performance_summary": summary
			})
			
		except Exception as e:
			logger.error(f"API error getting performance summary: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/cache-stats/")
	@has_access
	@permission_name("can_optimize_performance")
	def api_get_cache_stats(self):
		"""API endpoint to get cache statistics"""
		try:
			self._ensure_admin_access()
			
			optimizer = self._get_query_optimizer()
			stats = optimizer.execution_cache.get_stats()
			
			return jsonify({
				"success": True,
				"cache_stats": stats
			})
			
		except Exception as e:
			logger.error(f"API error getting cache stats: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/clear-cache/")
	@has_access
	@permission_name("can_optimize_performance")
	def api_clear_cache(self):
		"""API endpoint to clear query cache"""
		try:
			self._ensure_admin_access()
			
			optimizer = self._get_query_optimizer()
			optimizer.execution_cache.clear()
			
			# Track cache clearing activity
			track_database_activity(
				activity_type=ActivityType.SYSTEM_MAINTENANCE,
				target="Query Cache",
				description="Cleared query cache",
				details={"action": "cache_cleared"}
			)
			
			return jsonify({
				"success": True,
				"message": "Cache cleared successfully"
			})
			
		except Exception as e:
			logger.error(f"API error clearing cache: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/parallel-process/")
	@has_access
	@permission_name("can_optimize_performance")
	def api_parallel_process(self):
		"""API endpoint to execute parallel graph operations"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_name = data.get("graph_name")
			queries = data.get("queries", [])
			processing_mode = data.get("processing_mode", "parallel_threads")
			
			if not graph_name or not queries:
				raise BadRequest("graph_name and queries are required")
			
			# Convert processing mode
			mode = ProcessingMode(processing_mode)
			
			processor = get_parallel_processor()
			monitor = self._get_performance_monitor()
			
			# Start monitoring
			operation_id = monitor.start_operation("parallel_processing")
			
			def execute_query(query_data):
				"""Execute single query"""
				graph_manager = get_graph_manager(graph_name)
				query = query_data.get("query", "")
				parameters = query_data.get("parameters", {})
				return graph_manager.execute_cypher_query(query, parameters)
			
			# Execute queries in parallel
			results = processor.execute_parallel(execute_query, queries, mode)
			
			# End monitoring
			metrics = monitor.end_operation(
				operation_id,
				optimizations=[f"parallel_processing_{mode.value}"]
			)
			
			return jsonify({
				"success": True,
				"results": results,
				"processing_mode": mode.value,
				"performance_metrics": metrics.to_dict() if metrics else None
			})
			
		except Exception as e:
			logger.error(f"API error in parallel processing: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/distributed-tasks/")
	@has_access
	@permission_name("can_optimize_performance")
	def api_get_distributed_tasks(self):
		"""API endpoint to get distributed processing tasks"""
		try:
			self._ensure_admin_access()
			
			processor = get_distributed_processor()
			
			# Get task queue status (simplified implementation)
			tasks = []
			with processor._lock:
				tasks = processor.task_queue.copy()
			
			return jsonify({
				"success": True,
				"tasks": tasks,
				"node_count": len(processor.nodes)
			})
			
		except Exception as e:
			logger.error(f"API error getting distributed tasks: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/distributed-analysis/")
	@has_access
	@permission_name("can_optimize_performance")
	def api_start_distributed_analysis(self):
		"""API endpoint to start distributed graph analysis"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_name = data.get("graph_name")
			analysis_type = data.get("analysis_type")
			partition_strategy = data.get("partition_strategy", "node_based")
			
			if not graph_name or not analysis_type:
				raise BadRequest("graph_name and analysis_type are required")
			
			processor = get_distributed_processor()
			task_id = processor.distribute_graph_analysis(
				graph_name, analysis_type, partition_strategy
			)
			
			# Track distributed analysis
			track_database_activity(
				activity_type=ActivityType.QUERY_EXECUTED,
				target=f"Distributed Analysis: {graph_name}",
				description=f"Started distributed {analysis_type} analysis",
				details={
					"task_id": task_id,
					"analysis_type": analysis_type,
					"partition_strategy": partition_strategy
				}
			)
			
			return jsonify({
				"success": True,
				"task_id": task_id,
				"message": f"Distributed analysis {task_id} started"
			})
			
		except Exception as e:
			logger.error(f"API error starting distributed analysis: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/distributed-tasks/<task_id>/")
	@has_access
	@permission_name("can_optimize_performance")
	def api_get_distributed_task(self, task_id: str):
		"""API endpoint to get distributed task status"""
		try:
			self._ensure_admin_access()
			
			processor = get_distributed_processor()
			status = processor.get_task_status(task_id)
			
			return jsonify({
				"success": True,
				"task_status": status
			})
			
		except Exception as e:
			logger.error(f"API error getting distributed task: {e}")
			return jsonify({"success": False, "error": str(e)}), 500