"""
Recommendation Dashboard View

Flask view for the intelligent graph recommendation system.
Provides interface for viewing, managing, and interacting with recommendations.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.recommendation_engine import (
	get_recommendation_engine,
	generate_user_recommendations,
	RecommendationType,
	Recommendation
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


class RecommendationView(BaseView):
	"""
	Recommendation dashboard interface
	
	Provides comprehensive interface for viewing and managing intelligent
	recommendations across all graph analytics features.
	"""
	
	route_base = "/recommendations"
	default_view = "index"
	
	def __init__(self):
		"""Initialize recommendation view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		self.recommendation_engine = get_recommendation_engine()
	
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
	@permission_name("can_view_recommendations")
	def index(self):
		"""Main recommendation dashboard"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			graph_name = request.args.get("graph", "default")
			
			# Get personalized recommendations
			recommendations = generate_user_recommendations(user_id, graph_name)
			
			# Get recommendation analytics
			analytics = self.recommendation_engine.get_recommendation_analytics(user_id)
			
			# Categorize recommendations
			categorized_recommendations = self._categorize_recommendations(recommendations)
			
			# Get available graphs for selector
			available_graphs = self._get_available_graphs()
			
			return render_template(
				"recommendations/index.html",
				title="Intelligent Recommendations",
				recommendations=recommendations,
				categorized_recommendations=categorized_recommendations,
				analytics=analytics,
				available_graphs=available_graphs,
				selected_graph=graph_name,
				current_user_id=user_id
			)
			
		except Exception as e:
			logger.error(f"Error in recommendation dashboard: {e}")
			flash(f"Error loading recommendation dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/by-category/<category>/")
	@has_access
	@permission_name("can_view_recommendations")
	def by_category(self, category):
		"""View recommendations by specific category"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			graph_name = request.args.get("graph", "default")
			
			# Get all recommendations and filter by category
			all_recommendations = generate_user_recommendations(user_id, graph_name)
			filtered_recommendations = [
				r for r in all_recommendations 
				if r.category.lower() == category.lower()
			]
			
			return render_template(
				"recommendations/category.html",
				title=f"{category} Recommendations",
				recommendations=filtered_recommendations,
				category=category,
				total_count=len(filtered_recommendations)
			)
			
		except Exception as e:
			logger.error(f"Error in category view: {e}")
			flash(f"Error loading category recommendations: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/analytics/")
	@has_access
	@permission_name("can_view_recommendations")
	def analytics(self):
		"""Recommendation analytics dashboard"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			
			# Get comprehensive analytics
			user_analytics = self.recommendation_engine.get_recommendation_analytics(user_id)
			global_analytics = self.recommendation_engine.get_recommendation_analytics()
			
			# Get implementation trends
			implementation_trends = self._get_implementation_trends(user_id)
			
			# Get category performance
			category_performance = self._get_category_performance()
			
			return render_template(
				"recommendations/analytics.html",
				title="Recommendation Analytics",
				user_analytics=user_analytics,
				global_analytics=global_analytics,
				implementation_trends=implementation_trends,
				category_performance=category_performance
			)
			
		except Exception as e:
			logger.error(f"Error in analytics view: {e}")
			flash(f"Error loading recommendation analytics: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	def _categorize_recommendations(self, recommendations: List[Recommendation]) -> Dict[str, List[Recommendation]]:
		"""Categorize recommendations by type and category"""
		categorized = {
			"Performance": [],
			"Data Quality": [],
			"Collaboration": [],
			"Visualization": [],
			"Knowledge Sharing": [],
			"Other": []
		}
		
		for rec in recommendations:
			category = rec.category if rec.category in categorized else "Other"
			categorized[category].append(rec)
		
		return categorized
	
	def _get_available_graphs(self) -> List[str]:
		"""Get list of available graphs for user"""
		# This would typically query the database for user's accessible graphs
		# For now, return mock data
		return ["default", "social_network", "company_data", "product_catalog"]
	
	def _get_implementation_trends(self, user_id: str) -> Dict[str, Any]:
		"""Get implementation trends over time"""
		# Mock implementation - would analyze actual feedback data
		return {
			"weekly_implementations": [3, 5, 2, 7, 4, 6, 5],
			"weekly_labels": ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6", "Week 7"],
			"average_implementation_rate": 0.65,
			"trend": "increasing"
		}
	
	def _get_category_performance(self) -> Dict[str, Any]:
		"""Get performance metrics by recommendation category"""
		# Mock implementation - would analyze actual data
		return {
			"Performance": {"implementation_rate": 0.8, "satisfaction": 4.2},
			"Data Quality": {"implementation_rate": 0.6, "satisfaction": 3.8},
			"Collaboration": {"implementation_rate": 0.4, "satisfaction": 3.5},
			"Visualization": {"implementation_rate": 0.7, "satisfaction": 4.0}
		}
	
	# API Endpoints
	
	@expose_api("get", "/api/recommendations/")
	@has_access
	@permission_name("can_view_recommendations")
	def api_get_recommendations(self):
		"""API endpoint to get recommendations"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			graph_name = request.args.get("graph", "default")
			category = request.args.get("category")
			limit = int(request.args.get("limit", 20))
			
			recommendations = generate_user_recommendations(user_id, graph_name)
			
			# Filter by category if specified
			if category:
				recommendations = [r for r in recommendations if r.category.lower() == category.lower()]
			
			# Limit results
			recommendations = recommendations[:limit]
			
			return jsonify({
				"success": True,
				"recommendations": [r.to_dict() for r in recommendations],
				"total_count": len(recommendations),
				"graph_name": graph_name
			})
			
		except Exception as e:
			logger.error(f"API error getting recommendations: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/recommendations/feedback/")
	@has_access
	@permission_name("can_provide_feedback")
	def api_provide_feedback(self):
		"""API endpoint to provide feedback on recommendations"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			recommendation_id = data.get("recommendation_id")
			feedback = data.get("feedback")
			implemented = data.get("implemented", False)
			rating = data.get("rating")
			
			if not all([recommendation_id, feedback]):
				raise BadRequest("recommendation_id and feedback are required")
			
			user_id = self._get_current_user_id()
			
			# Record feedback
			self.recommendation_engine.record_user_feedback(
				user_id=user_id,
				recommendation_id=recommendation_id,
				feedback=feedback,
				implemented=implemented
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.RECOMMENDATION_FEEDBACK,
				target=f"Recommendation: {recommendation_id}",
				description="User provided recommendation feedback",
				details={
					"user_id": user_id,
					"feedback": feedback,
					"implemented": implemented,
					"rating": rating
				}
			)
			
			return jsonify({
				"success": True,
				"message": "Feedback recorded successfully"
			})
			
		except Exception as e:
			logger.error(f"API error providing feedback: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/recommendations/implement/")
	@has_access
	@permission_name("can_implement_recommendations")
	def api_implement_recommendation(self):
		"""API endpoint to mark recommendation as implemented"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			recommendation_id = data.get("recommendation_id")
			implementation_notes = data.get("notes", "")
			
			if not recommendation_id:
				raise BadRequest("recommendation_id is required")
			
			user_id = self._get_current_user_id()
			
			# Mark as implemented
			self.recommendation_engine.record_user_feedback(
				user_id=user_id,
				recommendation_id=recommendation_id,
				feedback=f"Implemented: {implementation_notes}",
				implemented=True
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.RECOMMENDATION_IMPLEMENTED,
				target=f"Recommendation: {recommendation_id}",
				description="Recommendation marked as implemented",
				details={
					"user_id": user_id,
					"implementation_notes": implementation_notes
				}
			)
			
			return jsonify({
				"success": True,
				"message": "Recommendation marked as implemented"
			})
			
		except Exception as e:
			logger.error(f"API error implementing recommendation: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/recommendations/analytics/")
	@has_access
	@permission_name("can_view_analytics")
	def api_get_analytics(self):
		"""API endpoint to get recommendation analytics"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			include_global = request.args.get("include_global", "false").lower() == "true"
			
			analytics = self.recommendation_engine.get_recommendation_analytics(user_id)
			
			if include_global:
				global_analytics = self.recommendation_engine.get_recommendation_analytics()
				analytics["global"] = global_analytics
			
			return jsonify({
				"success": True,
				"analytics": analytics
			})
			
		except Exception as e:
			logger.error(f"API error getting analytics: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/recommendations/refresh/")
	@has_access
	@permission_name("can_refresh_recommendations")
	def api_refresh_recommendations(self):
		"""API endpoint to refresh recommendations for a user/graph"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_name = data.get("graph_name", "default")
			user_id = self._get_current_user_id()
			context = data.get("context", {})
			
			# Clear any cached recommendations
			cache_key = f"{user_id}_{graph_name}_{int(time.time() // 3600)}"
			if cache_key in self.recommendation_engine.recommendation_cache:
				del self.recommendation_engine.recommendation_cache[cache_key]
			
			# Generate fresh recommendations
			recommendations = generate_user_recommendations(user_id, graph_name, context)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.RECOMMENDATIONS_REFRESHED,
				target=f"Graph: {graph_name}",
				description="User refreshed recommendations",
				details={
					"user_id": user_id,
					"graph_name": graph_name,
					"recommendation_count": len(recommendations)
				}
			)
			
			return jsonify({
				"success": True,
				"recommendations": [r.to_dict() for r in recommendations],
				"count": len(recommendations),
				"message": f"Generated {len(recommendations)} fresh recommendations"
			})
			
		except Exception as e:
			logger.error(f"API error refreshing recommendations: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/recommendations/export/")
	@has_access
	@permission_name("can_export_recommendations")
	def api_export_recommendations(self):
		"""API endpoint to export recommendations"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			graph_name = request.args.get("graph", "default")
			format_type = request.args.get("format", "json")
			
			recommendations = generate_user_recommendations(user_id, graph_name)
			
			exported_data = self.recommendation_engine.export_recommendations(
				recommendations, format_type
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.RECOMMENDATIONS_EXPORTED,
				target=f"Graph: {graph_name}",
				description=f"Exported recommendations in {format_type} format",
				details={
					"user_id": user_id,
					"graph_name": graph_name,
					"format": format_type,
					"count": len(recommendations)
				}
			)
			
			return jsonify({
				"success": True,
				"data": exported_data,
				"format": format_type
			})
			
		except Exception as e:
			logger.error(f"API error exporting recommendations: {e}")
			return jsonify({"success": False, "error": str(e)}), 500