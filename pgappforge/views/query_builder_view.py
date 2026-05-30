"""
Visual Query Builder View for Apache AGE

Provides advanced visual query construction interface with drag-and-drop components,
templates, natural language processing, and real-time validation.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.query_builder import (
    get_query_builder,
    VisualQueryBuilder,
    CypherQueryValidator
)
from ..database.graph_manager import get_graph_manager
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


class QueryBuilderView(BaseView):
    """
    Advanced visual query builder interface
    
    Provides drag-and-drop query construction, template management,
    and natural language query processing capabilities.
    """
    
    route_base = "/graph/query-builder"
    default_view = "index"
    
    def __init__(self):
        """Initialize query builder view"""
        super().__init__()
        self.error_handler = WizardErrorHandler()
        self.query_builder = None
    
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
    
    def _get_query_builder(self) -> VisualQueryBuilder:
        """Get or initialize query builder"""
        try:
            return get_query_builder()
        except Exception as e:
            logger.error(f"Failed to initialize query builder: {e}")
            self.error_handler.handle_error(
                e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
            )
            raise
    
    @expose("/")
    @has_access
    @permission_name("can_build_queries")
    def index(self):
        """Main query builder interface"""
        try:
            self._ensure_admin_access()
            query_builder = self._get_query_builder()
            
            # Get available templates and categories
            templates = query_builder.get_templates()
            categories = query_builder.get_template_categories()
            
            # Get graph schema for context
            graph_manager = get_graph_manager()
            schema = graph_manager.get_graph_schema()
            
            return render_template(
                "query_builder/index.html",
                title="Visual Query Builder",
                templates=templates,
                categories=categories,
                schema=schema.to_dict()
            )
            
        except Exception as e:
            logger.error(f"Error in query builder interface: {e}")
            flash(f"Error loading query builder: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    @expose("/templates/")
    @has_access
    @permission_name("can_build_queries")
    def templates(self):
        """Query templates management interface"""
        try:
            self._ensure_admin_access()
            query_builder = self._get_query_builder()
            
            templates = query_builder.get_templates()
            categories = query_builder.get_template_categories()
            
            return render_template(
                "query_builder/templates.html",
                title="Query Templates",
                templates=templates,
                categories=categories
            )
            
        except Exception as e:
            logger.error(f"Error in templates interface: {e}")
            flash(f"Error loading templates: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    # API Endpoints
    
    @expose_api("get", "/api/templates/")
    @has_access
    @permission_name("can_build_queries")
    def api_get_templates(self):
        """API endpoint to get query templates"""
        try:
            self._ensure_admin_access()
            
            category = request.args.get("category")
            query_builder = self._get_query_builder()
            
            templates = query_builder.get_templates(category=category)
            
            return jsonify({
                "success": True,
                "templates": templates,
                "count": len(templates)
            })
            
        except Exception as e:
            logger.error(f"API error getting templates: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/categories/")
    @has_access
    @permission_name("can_build_queries")
    def api_get_categories(self):
        """API endpoint to get template categories"""
        try:
            self._ensure_admin_access()
            
            query_builder = self._get_query_builder()
            categories = query_builder.get_template_categories()
            
            return jsonify({
                "success": True,
                "categories": categories
            })
            
        except Exception as e:
            logger.error(f"API error getting categories: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/build/")
    @has_access
    @permission_name("can_build_queries")
    def api_build_query(self):
        """API endpoint to build query from components"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            components = data.get("components", [])
            if not components:
                raise BadRequest("Components are required")
            
            query_builder = self._get_query_builder()
            result = query_builder.build_query_from_components(components)
            
            # Track query building activity
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target="Visual Query Builder",
                description=f"Built query with {len(components)} components",
                details={
                    "component_count": len(components),
                    "query_length": len(result.get("query", "")),
                    "success": result.get("success", False),
                    "complexity_score": result.get("complexity_score", 0)
                },
                success=result.get("success", False),
                error_message=result.get("error") if not result.get("success") else None
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error building query: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/validate/")
    @has_access
    @permission_name("can_build_queries")
    def api_validate_query(self):
        """API endpoint to validate Cypher query"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            query = data.get("query")
            if not query:
                raise BadRequest("Query is required")
            
            query_builder = self._get_query_builder()
            result = query_builder.validator.validate_query(query)
            
            return jsonify({
                "success": True,
                "validation": result
            })
            
        except Exception as e:
            logger.error(f"API error validating query: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/optimize/")
    @has_access
    @permission_name("can_build_queries")
    def api_optimize_query(self):
        """API endpoint to optimize Cypher query"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            query = data.get("query")
            if not query:
                raise BadRequest("Query is required")
            
            query_builder = self._get_query_builder()
            result = query_builder.optimize_query(query)
            
            # Track optimization activity
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target="Query Optimization",
                description="Optimized Cypher query for better performance",
                details={
                    "original_length": len(query),
                    "optimized_length": len(result.get("optimized_query", "")),
                    "improvements_count": len(result.get("improvements", [])),
                    "optimization_applied": result.get("optimization_applied", False)
                },
                success=result.get("success", False)
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error optimizing query: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/natural-language/")
    @has_access
    @permission_name("can_build_queries")
    def api_natural_language_query(self):
        """API endpoint to convert natural language to Cypher"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            natural_query = data.get("natural_query")
            if not natural_query:
                raise BadRequest("Natural language query is required")
            
            query_builder = self._get_query_builder()
            result = query_builder.natural_language_to_cypher(natural_query)
            
            # Track natural language processing
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target="Natural Language Processing",
                description=f"Converted natural language to Cypher: {natural_query[:50]}...",
                details={
                    "natural_query": natural_query,
                    "confidence": result.get("confidence", 0),
                    "success": result.get("success", False),
                    "generated_cypher": result.get("cypher", "")
                },
                success=result.get("success", False),
                error_message=result.get("error") if not result.get("success") else None
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error processing natural language: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/execute/")
    @has_access
    @permission_name("can_build_queries")
    def api_execute_built_query(self):
        """API endpoint to execute built query"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            query = data.get("query")
            if not query:
                raise BadRequest("Query is required")
            
            parameters = data.get("parameters", {})
            graph_name = data.get("graph", "default_graph")
            
            # Execute query using graph manager
            graph_manager = get_graph_manager(graph_name=graph_name)
            result = graph_manager.execute_cypher_query(query, parameters)
            
            # Track query execution
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target=f"Built Query Execution: {query[:50]}...",
                description=f"Executed query built with visual query builder",
                details={
                    "query": query,
                    "parameters": parameters,
                    "graph_name": graph_name,
                    "result_count": result.get("count", 0),
                    "success": result.get("success", False)
                },
                success=result.get("success", False),
                error_message=result.get("error") if not result.get("success") else None
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API error executing built query: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/schema-hints/")
    @has_access
    @permission_name("can_build_queries")
    def api_get_schema_hints(self):
        """API endpoint to get schema hints for query building"""
        try:
            self._ensure_admin_access()
            
            graph_name = request.args.get("graph", "default_graph")
            
            # Get graph schema
            graph_manager = get_graph_manager(graph_name=graph_name)
            schema = graph_manager.get_graph_schema()
            
            # Prepare hints for query builder
            hints = {
                "node_labels": schema.node_labels,
                "edge_labels": schema.edge_labels,
                "node_properties": schema.node_properties,
                "edge_properties": schema.edge_properties,
                "common_patterns": [
                    "(n)" if schema.node_labels else "()",
                    f"(n:{schema.node_labels[0]})" if schema.node_labels else "(n)",
                    f"-[r:{schema.edge_labels[0]}]->" if schema.edge_labels else "-[r]->"
                ],
                "example_variables": ["n", "m", "node", "start", "end", "center"],
                "common_functions": [
                    "id()", "labels()", "type()", "keys()", "properties()",
                    "count()", "collect()", "avg()", "min()", "max()",
                    "shortestPath()", "allShortestPaths()"
                ]
            }
            
            return jsonify({
                "success": True,
                "hints": hints,
                "graph_name": graph_name
            })
            
        except Exception as e:
            logger.error(f"API error getting schema hints: {e}")
            return jsonify({"success": False, "error": str(e)}), 500