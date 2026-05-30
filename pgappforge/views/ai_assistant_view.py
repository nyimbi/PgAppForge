"""
AI Analytics Assistant View

Provides web interface for AI-powered graph analysis, natural language queries,
automated insights, and intelligent recommendations.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.ai_analytics_assistant import (
	get_ai_analytics_assistant,
	AIAnalyticsAssistant,
	AnalysisType,
	InsightPriority,
	QueryComplexity
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


class AIAssistantView(BaseView):
	"""
	AI Analytics Assistant interface
	
	Provides intelligent analysis, natural language querying, automated insights,
	and smart recommendations through an intuitive web interface.
	"""
	
	route_base = "/graph/ai-assistant"
	default_view = "index"
	
	def __init__(self):
		"""Initialize AI assistant view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		self.ai_assistant = None
	
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
			return "anonymous"
		except:
			return "anonymous"
	
	def _get_ai_assistant(self) -> AIAnalyticsAssistant:
		"""Get or initialize AI assistant"""
		try:
			return get_ai_analytics_assistant()
		except Exception as e:
			logger.error(f"Failed to initialize AI assistant: {e}")
			self.error_handler.handle_error(
				e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
			)
			raise
	
	@expose("/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def index(self):
		"""AI Assistant dashboard"""
		try:
			self._ensure_admin_access()
			
			ai_assistant = self._get_ai_assistant()
			user_id = self._get_current_user_id()
			
			# Get dashboard summary
			dashboard_summary = ai_assistant.get_dashboard_summary(user_id)
			
			# Get available graphs
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			
			# Get analysis types and priorities
			analysis_types = [
				{
					"value": at.value,
					"name": at.value.replace("_", " ").title(),
					"description": self._get_analysis_description(at)
				}
				for at in AnalysisType
			]
			
			insight_priorities = [
				{
					"value": ip.value,
					"name": ip.value.title(),
					"color": self._get_priority_color(ip)
				}
				for ip in InsightPriority
			]
			
			# Get recent insights for all graphs
			recent_insights = []
			for graph in graphs[:3]:  # Top 3 graphs
				try:
					graph_insights = ai_assistant.get_automated_insights(graph.name)
					recent_insights.extend([
						{**insight.to_dict(), "graph_name": graph.name}
						for insight in graph_insights[:2]  # Top 2 per graph
					])
				except Exception as e:
					logger.warning(f"Could not get insights for {graph.name}: {e}")
			
			# Sort by priority and creation time
			recent_insights.sort(key=lambda x: (
				self._priority_sort_key(x.get("priority", "low")),
				x.get("created_at", "")
			), reverse=True)
			
			return render_template(
				"ai_assistant/index.html",
				title="AI Analytics Assistant",
				dashboard_summary=dashboard_summary,
				graphs=[graph.to_dict() for graph in graphs],
				analysis_types=analysis_types,
				insight_priorities=insight_priorities,
				recent_insights=recent_insights[:10],  # Top 10 insights
				current_user_id=user_id
			)
			
		except Exception as e:
			logger.error(f"Error in AI assistant dashboard: {e}")
			flash(f"Error loading AI assistant dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/query/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def query(self):
		"""Natural language query interface"""
		try:
			self._ensure_admin_access()
			
			ai_assistant = self._get_ai_assistant()
			
			# Get available graphs
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			
			# Get recent query history
			recent_queries = ai_assistant.query_history[-10:] if ai_assistant.query_history else []
			
			return render_template(
				"ai_assistant/query.html",
				title="Natural Language Queries",
				graphs=[graph.to_dict() for graph in graphs],
				recent_queries=[query.to_dict() for query in reversed(recent_queries)]
			)
			
		except Exception as e:
			logger.error(f"Error in query interface: {e}")
			flash(f"Error loading query interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/insights/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def insights(self):
		"""Automated insights interface"""
		try:
			self._ensure_admin_access()
			
			ai_assistant = self._get_ai_assistant()
			
			# Get available graphs
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			
			# Get insights for selected graph (default to first graph)
			selected_graph = request.args.get("graph", graphs[0].name if graphs else None)
			insights = []
			
			if selected_graph:
				try:
					insights = ai_assistant.get_automated_insights(selected_graph)
				except Exception as e:
					logger.warning(f"Could not get insights for {selected_graph}: {e}")
			
			return render_template(
				"ai_assistant/insights.html",
				title="Automated Insights",
				graphs=[graph.to_dict() for graph in graphs],
				selected_graph=selected_graph,
				insights=[insight.to_dict() for insight in insights]
			)
			
		except Exception as e:
			logger.error(f"Error in insights interface: {e}")
			flash(f"Error loading insights interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/recommendations/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def recommendations(self):
		"""Analysis recommendations interface"""
		try:
			self._ensure_admin_access()
			
			ai_assistant = self._get_ai_assistant()
			
			# Get available graphs
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			
			# Get recommendations for selected graph
			selected_graph = request.args.get("graph", graphs[0].name if graphs else None)
			recommendations = []
			
			if selected_graph:
				try:
					recommendations = ai_assistant.get_analysis_recommendations(selected_graph)
				except Exception as e:
					logger.warning(f"Could not get recommendations for {selected_graph}: {e}")
			
			return render_template(
				"ai_assistant/recommendations.html",
				title="Analysis Recommendations",
				graphs=[graph.to_dict() for graph in graphs],
				selected_graph=selected_graph,
				recommendations=[rec.to_dict() for rec in recommendations]
			)
			
		except Exception as e:
			logger.error(f"Error in recommendations interface: {e}")
			flash(f"Error loading recommendations interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	# API Endpoints
	
	@expose_api("post", "/api/natural-language-query/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def api_natural_language_query(self):
		"""API endpoint to process natural language query"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			query = data.get("query")
			graph_name = data.get("graph_name")
			
			if not query:
				raise BadRequest("query is required")
			
			ai_assistant = self._get_ai_assistant()
			suggestion = ai_assistant.process_natural_language_query(query, graph_name)
			
			return jsonify({
				"success": True,
				"suggestion": suggestion.to_dict()
			})
			
		except Exception as e:
			logger.error(f"API error processing natural language query: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/execute-suggested-query/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def api_execute_suggested_query(self):
		"""API endpoint to execute AI-suggested query"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			cypher_query = data.get("cypher_query")
			graph_name = data.get("graph_name")
			parameters = data.get("parameters", {})
			
			if not cypher_query or not graph_name:
				raise BadRequest("cypher_query and graph_name are required")
			
			# Execute query
			graph_manager = get_graph_manager(graph_name)
			result = graph_manager.execute_cypher_query(cypher_query, parameters)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.AI_QUERY_EXECUTED,
				target=f"Graph: {graph_name}",
				description=f"Executed AI-suggested query",
				details={
					"cypher_query": cypher_query[:200] + "..." if len(cypher_query) > 200 else cypher_query,
					"parameters": parameters,
					"success": result.get("success", False)
				}
			)
			
			return jsonify({
				"success": True,
				"result": result
			})
			
		except Exception as e:
			logger.error(f"API error executing suggested query: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/insights/<graph_name>/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def api_get_insights(self, graph_name: str):
		"""API endpoint to get insights for graph"""
		try:
			self._ensure_admin_access()
			
			force_refresh = request.args.get("force_refresh", "false").lower() == "true"
			
			ai_assistant = self._get_ai_assistant()
			insights = ai_assistant.get_automated_insights(graph_name, force_refresh)
			
			return jsonify({
				"success": True,
				"insights": [insight.to_dict() for insight in insights]
			})
			
		except Exception as e:
			logger.error(f"API error getting insights: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/recommendations/<graph_name>/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def api_get_recommendations(self, graph_name: str):
		"""API endpoint to get recommendations for graph"""
		try:
			self._ensure_admin_access()
			
			user_context = request.args.to_dict()
			
			ai_assistant = self._get_ai_assistant()
			recommendations = ai_assistant.get_analysis_recommendations(graph_name, user_context)
			
			return jsonify({
				"success": True,
				"recommendations": [rec.to_dict() for rec in recommendations]
			})
			
		except Exception as e:
			logger.error(f"API error getting recommendations: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/query-suggestions/<graph_name>/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def api_get_query_suggestions(self, graph_name: str):
		"""API endpoint to get query suggestions"""
		try:
			self._ensure_admin_access()
			
			context = request.args.get("context", "")
			
			ai_assistant = self._get_ai_assistant()
			suggestions = ai_assistant.get_query_suggestions(graph_name, context)
			
			return jsonify({
				"success": True,
				"suggestions": [suggestion.to_dict() for suggestion in suggestions]
			})
			
		except Exception as e:
			logger.error(f"API error getting query suggestions: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/dashboard-summary/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def api_get_dashboard_summary(self):
		"""API endpoint to get dashboard summary"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			
			ai_assistant = self._get_ai_assistant()
			summary = ai_assistant.get_dashboard_summary(user_id)
			
			return jsonify({
				"success": True,
				"summary": summary
			})
			
		except Exception as e:
			logger.error(f"API error getting dashboard summary: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/analyze-graph/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def api_analyze_graph(self):
		"""API endpoint to trigger graph analysis"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_name = data.get("graph_name")
			analysis_types = data.get("analysis_types", [])
			
			if not graph_name:
				raise BadRequest("graph_name is required")
			
			ai_assistant = self._get_ai_assistant()
			
			# Trigger analysis based on requested types
			results = {}
			
			if not analysis_types or "structure_analysis" in analysis_types:
				try:
					structure_insight = ai_assistant.analysis_engine.analyze_graph_structure(graph_name)
					results["structure_analysis"] = structure_insight.to_dict()
				except Exception as e:
					results["structure_analysis"] = {"error": str(e)}
			
			if not analysis_types or "anomaly_detection" in analysis_types:
				try:
					anomaly_insights = ai_assistant.analysis_engine.detect_anomalies(graph_name)
					results["anomaly_detection"] = [insight.to_dict() for insight in anomaly_insights]
				except Exception as e:
					results["anomaly_detection"] = {"error": str(e)}
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.AI_ANALYSIS_TRIGGERED,
				target=f"Graph: {graph_name}",
				description=f"Triggered AI analysis: {', '.join(analysis_types) if analysis_types else 'all types'}",
				details={
					"graph_name": graph_name,
					"analysis_types": analysis_types,
					"results_count": len(results)
				}
			)
			
			return jsonify({
				"success": True,
				"results": results
			})
			
		except Exception as e:
			logger.error(f"API error analyzing graph: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/query-history/")
	@has_access
	@permission_name("can_use_ai_assistant")
	def api_get_query_history(self):
		"""API endpoint to get query history"""
		try:
			self._ensure_admin_access()
			
			limit = int(request.args.get("limit", 20))
			
			ai_assistant = self._get_ai_assistant()
			recent_queries = ai_assistant.query_history[-limit:] if ai_assistant.query_history else []
			
			return jsonify({
				"success": True,
				"queries": [query.to_dict() for query in reversed(recent_queries)]
			})
			
		except Exception as e:
			logger.error(f"API error getting query history: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	def _get_analysis_description(self, analysis_type: AnalysisType) -> str:
		"""Get description for analysis type"""
		descriptions = {
			AnalysisType.GRAPH_STRUCTURE_ANALYSIS: "Analyze basic graph structure, connectivity, and topology",
			AnalysisType.ANOMALY_DETECTION: "Detect unusual patterns, outliers, and data quality issues",
			AnalysisType.PATTERN_DISCOVERY: "Find recurring patterns and structural motifs",
			AnalysisType.TREND_ANALYSIS: "Analyze temporal trends and evolution patterns",
			AnalysisType.SIMILARITY_ANALYSIS: "Find similar nodes and structural similarities",
			AnalysisType.CENTRALITY_ANALYSIS: "Identify important nodes using centrality measures",
			AnalysisType.COMMUNITY_DETECTION: "Detect communities and clusters in the graph",
			AnalysisType.PATH_ANALYSIS: "Analyze paths, reachability, and connectivity",
			AnalysisType.INFLUENCE_PROPAGATION: "Model information or influence spreading",
			AnalysisType.PREDICTIVE_MODELING: "Build predictive models using graph features"
		}
		return descriptions.get(analysis_type, "Unknown analysis type")
	
	def _get_priority_color(self, priority: InsightPriority) -> str:
		"""Get color code for priority level"""
		colors = {
			InsightPriority.LOW: "secondary",
			InsightPriority.MEDIUM: "info",
			InsightPriority.HIGH: "warning", 
			InsightPriority.CRITICAL: "danger"
		}
		return colors.get(priority, "secondary")
	
	def _priority_sort_key(self, priority_str: str) -> int:
		"""Get sort key for priority"""
		priority_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
		return priority_order.get(priority_str.lower(), 0)