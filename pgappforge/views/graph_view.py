"""
Apache AGE Graph Analysis View

Provides comprehensive graph visualization, analysis, and management interface
for PostgreSQL AGE extension with OpenCypher query support.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash, redirect, url_for
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from ..database.graph_manager import (
    get_graph_manager,
    GraphAlgorithmType,
    GraphDatabaseManager
)
from ..database.activity_tracker import (
    get_activity_tracker,
    track_database_activity,
    ActivityType,
    ActivitySeverity,
)
from ..utils.error_handling import (
    WizardErrorHandler,
    WizardErrorType,
    WizardErrorSeverity,
)

logger = logging.getLogger(__name__)


class GraphAnalysisView(BaseView):
    """
    Comprehensive graph analysis and visualization view
    
    Provides interactive graph visualization, OpenCypher query execution,
    graph algorithm analysis, and advanced drill-down capabilities.
    """
    
    route_base = "/graph/analysis"
    default_view = "index"
    
    def __init__(self):
        """Initialize graph analysis view"""
        super().__init__()
        self.error_handler = WizardErrorHandler()
        self.graph_manager = None
    
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
    
    def _get_graph_manager(self, graph_name: str = "default_graph") -> GraphDatabaseManager:
        """Get or initialize graph manager"""
        try:
            return get_graph_manager(graph_name=graph_name)
        except Exception as e:
            logger.error(f"Failed to initialize graph manager: {e}")
            self.error_handler.handle_error(
                e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
            )
            raise
    
    @expose("/")
    @has_access
    @permission_name("can_analyze_graphs")
    def index(self):
        """Main graph analysis dashboard"""
        try:
            self._ensure_admin_access()
            graph_manager = self._get_graph_manager()
            
            # Get graph schema and statistics
            schema = graph_manager.get_graph_schema()
            
            # Prepare dashboard data
            dashboard_data = {
                "graph_name": schema.name,
                "total_nodes": schema.statistics.get("total_nodes", 0),
                "total_edges": schema.statistics.get("total_edges", 0),
                "node_labels": schema.node_labels,
                "edge_labels": schema.edge_labels,
                "density": schema.statistics.get("density", 0),
                "statistics": schema.statistics
            }
            
            return render_template(
                "graph/index.html",
                title="Graph Analysis Dashboard",
                dashboard=dashboard_data,
                schema=schema.to_dict()
            )
            
        except Exception as e:
            logger.error(f"Error in graph analysis dashboard: {e}")
            flash(f"Error loading graph dashboard: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    @expose("/visualizer/")
    @has_access
    @permission_name("can_analyze_graphs") 
    def visualizer(self):
        """Interactive graph visualizer"""
        try:
            self._ensure_admin_access()
            
            # Get available graphs
            graph_manager = self._get_graph_manager()
            schema = graph_manager.get_graph_schema()
            
            return render_template(
                "graph/visualizer.html",
                title="Graph Visualizer",
                schema=schema.to_dict()
            )
            
        except Exception as e:
            logger.error(f"Error in graph visualizer: {e}")
            flash(f"Error loading graph visualizer: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    @expose("/query/")
    @has_access
    @permission_name("can_analyze_graphs")
    def query_interface(self):
        """OpenCypher query interface"""
        try:
            self._ensure_admin_access()
            
            # Get sample queries
            sample_queries = [
                {
                    "name": "Find All Nodes",
                    "query": "MATCH (n) RETURN n LIMIT 25",
                    "description": "Retrieve all nodes with a limit"
                },
                {
                    "name": "Find All Relationships", 
                    "query": "MATCH ()-[r]->() RETURN r LIMIT 25",
                    "description": "Retrieve all relationships with a limit"
                },
                {
                    "name": "Node Degree Distribution",
                    "query": "MATCH (n) RETURN labels(n) as label, count(n) as count ORDER BY count DESC",
                    "description": "Count nodes by label"
                },
                {
                    "name": "Shortest Path",
                    "query": "MATCH path = shortestPath((start)-[*]-(end)) WHERE id(start) = 1 AND id(end) = 10 RETURN path",
                    "description": "Find shortest path between two specific nodes"
                },
                {
                    "name": "High Degree Nodes",
                    "query": "MATCH (n)-[r]-() WITH n, count(r) as degree WHERE degree > 5 RETURN n, degree ORDER BY degree DESC",
                    "description": "Find nodes with high connectivity"
                }
            ]
            
            return render_template(
                "graph/query_interface.html",
                title="OpenCypher Query Interface",
                sample_queries=sample_queries
            )
            
        except Exception as e:
            logger.error(f"Error in query interface: {e}")
            flash(f"Error loading query interface: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    @expose("/algorithms/")
    @has_access
    @permission_name("can_analyze_graphs")
    def algorithms(self):
        """Graph algorithms interface"""
        try:
            self._ensure_admin_access()
            
            # Available algorithms
            algorithms = [
                {
                    "name": "Centrality Analysis",
                    "type": "centrality",
                    "description": "Calculate node importance using various centrality measures",
                    "algorithms": ["betweenness", "closeness", "degree", "eigenvector", "pagerank"]
                },
                {
                    "name": "Community Detection",
                    "type": "community",
                    "description": "Identify communities and clusters in the graph",
                    "algorithms": ["louvain", "connected_components"]
                },
                {
                    "name": "Path Analysis",
                    "type": "path",
                    "description": "Find shortest paths and analyze connectivity",
                    "algorithms": ["shortest_path", "all_paths"]
                },
                {
                    "name": "Graph Metrics",
                    "type": "metrics",
                    "description": "Calculate graph-level statistics and properties",
                    "algorithms": ["density", "diameter", "clustering_coefficient"]
                }
            ]
            
            return render_template(
                "graph/algorithms.html",
                title="Graph Algorithms",
                algorithms=algorithms
            )
            
        except Exception as e:
            logger.error(f"Error in algorithms interface: {e}")
            flash(f"Error loading algorithms interface: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    # API Endpoints
    
    @expose_api("get", "/api/schema/")
    @has_access
    @permission_name("can_analyze_graphs")
    def api_get_schema(self):
        """API endpoint to get graph schema"""
        try:
            self._ensure_admin_access()
            
            graph_name = request.args.get("graph", "default_graph")
            graph_manager = self._get_graph_manager(graph_name)
            
            schema = graph_manager.get_graph_schema()
            
            return jsonify({
                "success": True,
                "schema": schema.to_dict()
            })
            
        except Exception as e:
            logger.error(f"API error getting graph schema: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/data/")
    @has_access
    @permission_name("can_analyze_graphs")
    def api_get_graph_data(self):
        """API endpoint to get graph data for visualization"""
        try:
            self._ensure_admin_access()
            
            graph_name = request.args.get("graph", "default_graph")
            limit = int(request.args.get("limit", 1000))
            node_filter = request.args.get("node_filter")
            edge_filter = request.args.get("edge_filter")
            
            graph_manager = self._get_graph_manager(graph_name)
            
            data = graph_manager.get_graph_data(
                limit=limit,
                node_filter=node_filter,
                edge_filter=edge_filter
            )
            
            return jsonify(data)
            
        except Exception as e:
            logger.error(f"API error getting graph data: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/query/")
    @has_access
    @permission_name("can_analyze_graphs")
    def api_execute_query(self):
        """API endpoint to execute OpenCypher queries"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            query = data.get("query")
            if not query:
                raise BadRequest("Query is required")
            
            graph_name = data.get("graph", "default_graph")
            parameters = data.get("parameters", {})
            
            graph_manager = self._get_graph_manager(graph_name)
            result = graph_manager.execute_cypher_query(query, parameters)
            
            # Track query execution
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target=f"Graph Query: {query[:50]}..." if len(query) > 50 else f"Graph Query: {query}",
                description=f"Executed OpenCypher query on graph '{graph_name}'",
                details={
                    "query": query,
                    "graph_name": graph_name,
                    "parameters": parameters,
                    "success": result.get("success", False)
                },
                success=result.get("success", False),
                error_message=result.get("error") if not result.get("success") else None
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error executing query: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/algorithms/centrality/")
    @has_access
    @permission_name("can_analyze_graphs")
    def api_calculate_centrality(self):
        """API endpoint to calculate node centrality"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            algorithm = data.get("algorithm", "betweenness")
            graph_name = data.get("graph", "default_graph")
            limit = data.get("limit", 100)
            
            graph_manager = self._get_graph_manager(graph_name)
            result = graph_manager.calculate_centrality(algorithm, limit)
            
            # Track algorithm execution
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target=f"Centrality Analysis: {algorithm}",
                description=f"Calculated {algorithm} centrality on graph '{graph_name}'",
                details={
                    "algorithm": algorithm,
                    "graph_name": graph_name,
                    "limit": limit,
                    "success": result.get("success", False)
                },
                success=result.get("success", False)
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error calculating centrality: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/algorithms/communities/")
    @has_access
    @permission_name("can_analyze_graphs")
    def api_detect_communities(self):
        """API endpoint to detect communities"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            algorithm = data.get("algorithm", "louvain")
            graph_name = data.get("graph", "default_graph")
            resolution = data.get("resolution", 1.0)
            
            graph_manager = self._get_graph_manager(graph_name)
            result = graph_manager.detect_communities(algorithm, resolution)
            
            # Track algorithm execution
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target=f"Community Detection: {algorithm}",
                description=f"Detected communities using {algorithm} on graph '{graph_name}'",
                details={
                    "algorithm": algorithm,
                    "graph_name": graph_name,
                    "resolution": resolution,
                    "success": result.get("success", False),
                    "communities_found": result.get("num_communities", 0)
                },
                success=result.get("success", False)
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error detecting communities: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/path/shortest/")
    @has_access
    @permission_name("can_analyze_graphs")
    def api_find_shortest_path(self):
        """API endpoint to find shortest path"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            start_node = data.get("start_node")
            end_node = data.get("end_node")
            
            if not start_node or not end_node:
                raise BadRequest("Both start_node and end_node are required")
            
            graph_name = data.get("graph", "default_graph")
            max_length = data.get("max_length", 10)
            
            graph_manager = self._get_graph_manager(graph_name)
            result = graph_manager.find_shortest_path(start_node, end_node, max_length)
            
            # Track path finding
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target=f"Shortest Path: {start_node} -> {end_node}",
                description=f"Found shortest path between nodes on graph '{graph_name}'",
                details={
                    "start_node": start_node,
                    "end_node": end_node,
                    "graph_name": graph_name,
                    "max_length": max_length,
                    "path_found": result.get("found", False),
                    "success": result.get("success", False)
                },
                success=result.get("success", False)
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error finding shortest path: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/search/")
    @has_access
    @permission_name("can_analyze_graphs")
    def api_search_nodes(self):
        """API endpoint to search nodes"""
        try:
            self._ensure_admin_access()
            
            search_term = request.args.get("q", "")
            if not search_term:
                raise BadRequest("Search term is required")
            
            graph_name = request.args.get("graph", "default_graph")
            limit = int(request.args.get("limit", 50))
            search_fields = request.args.getlist("fields")
            
            graph_manager = self._get_graph_manager(graph_name)
            result = graph_manager.search_nodes(
                search_term=search_term,
                search_fields=search_fields if search_fields else None,
                limit=limit
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error searching nodes: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/neighbors/<node_id>/")
    @has_access 
    @permission_name("can_analyze_graphs")
    def api_get_neighbors(self, node_id: str):
        """API endpoint to get node neighbors"""
        try:
            self._ensure_admin_access()
            
            graph_name = request.args.get("graph", "default_graph") 
            depth = int(request.args.get("depth", 1))
            direction = request.args.get("direction", "both")
            
            graph_manager = self._get_graph_manager(graph_name)
            result = graph_manager.get_node_neighbors(node_id, depth, direction)
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error getting neighbors: {e}")
            return jsonify({"success": False, "error": str(e)}), 500


# API-only view for external integrations
class GraphAnalysisAPIView(BaseView):
    """API-only endpoints for graph analysis"""
    
    route_base = "/api/v1/graph"
    
    def __init__(self):
        super().__init__()
        self.error_handler = WizardErrorHandler()
    
    def _ensure_admin_access(self):
        """Ensure current user has admin privileges"""
        try:
            from flask_login import current_user
            
            if not current_user or not current_user.is_authenticated:
                raise Forbidden("Authentication required")
            
            # Check admin role
            if hasattr(current_user, "roles"):
                admin_roles = ["Admin", "admin", "Administrator", "administrator"]
                user_roles = [
                    role.name if hasattr(role, "name") else str(role)
                    for role in current_user.roles
                ]
                
                if not any(role in admin_roles for role in user_roles):
                    raise Forbidden("Administrator privileges required")
            else:
                if not getattr(current_user, "is_admin", False):
                    raise Forbidden("Administrator privileges required")
                    
        except Exception as e:
            logger.error(f"Admin access check failed: {e}")
            raise Forbidden("Access denied")
    
    @expose_api("get", "/graphs/")
    @has_access
    @permission_name("can_analyze_graphs")
    def api_list_graphs(self):
        """List all available graphs"""
        try:
            self._ensure_admin_access()
            
            # This would query AGE catalog for all graphs
            graph_manager = get_graph_manager()
            
            # For now, return default graph info
            schema = graph_manager.get_graph_schema()
            
            graphs = [{
                "name": schema.name,
                "nodes": schema.statistics.get("total_nodes", 0),
                "edges": schema.statistics.get("total_edges", 0),
                "node_labels": schema.node_labels,
                "edge_labels": schema.edge_labels
            }]
            
            return jsonify({
                "success": True,
                "graphs": graphs,
                "total": len(graphs)
            })
            
        except Exception as e:
            logger.error(f"API error listing graphs: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/analytics/summary/")
    @has_access
    @permission_name("can_analyze_graphs")
    def api_get_analytics_summary(self):
        """Get comprehensive graph analytics summary"""
        try:
            self._ensure_admin_access()
            
            graph_name = request.args.get("graph", "default_graph")
            graph_manager = get_graph_manager(graph_name=graph_name)
            
            # Get basic schema
            schema = graph_manager.get_graph_schema()
            
            # Calculate basic centrality for top nodes
            centrality_result = graph_manager.calculate_centrality("degree", limit=50)
            top_nodes = centrality_result.get("top_nodes", [])[:10]
            
            # Detect communities
            community_result = graph_manager.detect_communities()
            
            summary = {
                "graph_name": schema.name,
                "statistics": schema.statistics,
                "node_labels": schema.node_labels,
                "edge_labels": schema.edge_labels,
                "top_nodes_by_degree": top_nodes,
                "community_analysis": {
                    "num_communities": community_result.get("num_communities", 0),
                    "modularity": community_result.get("modularity", 0)
                }
            }
            
            return jsonify({
                "success": True,
                "summary": summary
            })
            
        except Exception as e:
            logger.error(f"API error getting analytics summary: {e}")
            return jsonify({"success": False, "error": str(e)}), 500