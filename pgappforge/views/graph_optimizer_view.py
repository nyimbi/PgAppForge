"""
Graph Optimizer View

Flask view for the automated graph optimization and healing system.
Provides interface for monitoring graph health and running optimizations.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden
from uuid_extensions import uuid7str

try:
	import numpy as np
except ImportError:
	# Fallback for numpy operations
	class MockNumpy:
		@staticmethod
		def mean(data):
			return sum(data) / len(data) if data else 0
	np = MockNumpy()

from ..database.graph_optimizer import (
	get_graph_optimizer,
	run_automated_healing,
	OptimizationLevel,
	IssueType,
	IssueSeverity
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


class GraphOptimizerView(BaseView):
	"""
	Graph optimization and healing interface
	
	Provides comprehensive interface for monitoring graph health,
	detecting issues, and running automated optimizations.
	"""
	
	route_base = "/graph-optimizer"
	default_view = "index"
	
	def __init__(self):
		"""Initialize graph optimizer view"""
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
	@permission_name("can_optimize_graphs")
	def index(self):
		"""Main graph optimizer dashboard"""
		try:
			self._ensure_admin_access()
			
			# Get available graphs
			available_graphs = self._get_available_graphs()
			
			# Get overall health statistics
			health_statistics = self._get_overall_health_stats(available_graphs)
			
			# Get recent optimization activities
			recent_optimizations = self._get_recent_optimizations()
			
			# Get optimization recommendations
			recommendations = self._get_optimization_recommendations(available_graphs)
			
			return render_template(
				"graph_optimizer/index.html",
				title="Graph Optimization & Healing",
				available_graphs=available_graphs,
				health_statistics=health_statistics,
				recent_optimizations=recent_optimizations,
				recommendations=recommendations,
				optimization_levels=self._get_optimization_levels(),
				issue_types=self._get_issue_types()
			)
			
		except Exception as e:
			logger.error(f"Error in optimizer dashboard: {e}")
			flash(f"Error loading optimizer dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/health/<graph_name>/")
	@has_access
	@permission_name("can_monitor_graph_health")
	def health_monitor(self, graph_name):
		"""Graph health monitoring interface"""
		try:
			self._ensure_admin_access()
			
			optimizer = get_graph_optimizer(graph_name)
			
			# Run health check
			issues = optimizer.health_checker.run_comprehensive_health_check()
			
			# Categorize issues
			categorized_issues = self._categorize_issues(issues)
			
			# Get health metrics
			health_metrics = self._calculate_health_metrics(issues)
			
			# Get optimization history
			optimization_history = optimizer.optimization_history[-10:]  # Last 10 optimizations
			
			return render_template(
				"graph_optimizer/health.html",
				title=f"Graph Health - {graph_name}",
				graph_name=graph_name,
				issues=issues,
				categorized_issues=categorized_issues,
				health_metrics=health_metrics,
				optimization_history=optimization_history
			)
			
		except Exception as e:
			logger.error(f"Error in health monitor: {e}")
			flash(f"Error loading health monitor: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/optimize/<graph_name>/")
	@has_access
	@permission_name("can_optimize_graphs")
	def optimization_interface(self, graph_name):
		"""Graph optimization interface"""
		try:
			self._ensure_admin_access()
			
			optimizer = get_graph_optimizer(graph_name)
			
			# Get current issues
			issues = optimizer.health_checker.run_comprehensive_health_check()
			
			# Filter auto-fixable issues
			auto_fixable = [issue for issue in issues if issue.auto_fixable]
			manual_review = [issue for issue in issues if not issue.auto_fixable]
			
			# Get optimization report
			optimization_report = optimizer.get_optimization_report()
			
			return render_template(
				"graph_optimizer/optimize.html",
				title=f"Optimize Graph - {graph_name}",
				graph_name=graph_name,
				issues=issues,
				auto_fixable=auto_fixable,
				manual_review=manual_review,
				optimization_report=optimization_report,
				optimization_levels=self._get_optimization_levels()
			)
			
		except Exception as e:
			logger.error(f"Error in optimization interface: {e}")
			flash(f"Error loading optimization interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	def _get_available_graphs(self) -> List[str]:
		"""Get list of available graphs"""
		# Mock implementation - would typically query database
		return ["company_knowledge", "social_network", "product_catalog", "research_data"]
	
	def _get_overall_health_stats(self, graphs: List[str]) -> Dict[str, Any]:
		"""Get overall health statistics across all graphs"""
		total_issues = 0
		critical_issues = 0
		healthy_graphs = 0
		
		for graph_name in graphs:
			try:
				optimizer = get_graph_optimizer(graph_name)
				issues = optimizer.health_checker.run_comprehensive_health_check()
				total_issues += len(issues)
				critical_issues += len([i for i in issues if i.severity == IssueSeverity.CRITICAL])
				
				if len(issues) == 0:
					healthy_graphs += 1
			except Exception as e:
				logger.warning(f"Could not get health stats for {graph_name}: {e}")
		
		return {
			"total_graphs": len(graphs),
			"healthy_graphs": healthy_graphs,
			"graphs_with_issues": len(graphs) - healthy_graphs,
			"total_issues": total_issues,
			"critical_issues": critical_issues,
			"overall_health_score": ((healthy_graphs / len(graphs)) * 100) if graphs else 100
		}
	
	def _get_recent_optimizations(self) -> List[Dict[str, Any]]:
		"""Get recent optimization activities"""
		# Mock implementation - would query optimization history
		return [
			{
				"timestamp": "2024-01-15T14:30:00",
				"graph": "company_knowledge",
				"operation": "Duplicate Node Cleanup",
				"items_fixed": 15,
				"performance_improvement": 12.5,
				"status": "completed"
			},
			{
				"timestamp": "2024-01-15T13:15:00",
				"graph": "social_network",
				"operation": "Index Creation",
				"items_fixed": 3,
				"performance_improvement": 25.3,
				"status": "completed"
			}
		]
	
	def _get_optimization_recommendations(self, graphs: List[str]) -> List[Dict[str, Any]]:
		"""Get optimization recommendations across all graphs"""
		recommendations = []
		
		for graph_name in graphs:
			try:
				optimizer = get_graph_optimizer(graph_name)
				report = optimizer.get_optimization_report()
				
				if report.get("next_optimization_suggested"):
					recommendations.append({
						"graph": graph_name,
						"priority": "high" if report.get("health_score", 100) < 70 else "medium",
						"recommendation": f"Run optimization for {graph_name}",
						"issues_count": report.get("total_issues", 0),
						"health_score": report.get("health_score", 100)
					})
			except Exception as e:
				logger.warning(f"Could not get recommendations for {graph_name}: {e}")
		
		return recommendations
	
	def _get_optimization_levels(self) -> List[Dict[str, str]]:
		"""Get available optimization levels"""
		return [
			{
				"value": OptimizationLevel.CONSERVATIVE.value,
				"name": "Conservative",
				"description": "Only fix low-risk, high-confidence issues"
			},
			{
				"value": OptimizationLevel.MODERATE.value,
				"name": "Moderate",
				"description": "Fix most issues except critical ones requiring review"
			},
			{
				"value": OptimizationLevel.AGGRESSIVE.value,
				"name": "Aggressive",
				"description": "Fix all auto-fixable issues"
			}
		]
	
	def _get_issue_types(self) -> List[Dict[str, str]]:
		"""Get available issue types"""
		return [
			{
				"value": IssueType.DUPLICATE_NODES.value,
				"name": "Duplicate Nodes",
				"description": "Nodes with similar properties that may be duplicates"
			},
			{
				"value": IssueType.ORPHANED_NODES.value,
				"name": "Orphaned Nodes",
				"description": "Nodes with no relationships"
			},
			{
				"value": IssueType.REDUNDANT_RELATIONSHIPS.value,
				"name": "Redundant Relationships",
				"description": "Duplicate relationships between same nodes"
			},
			{
				"value": IssueType.PERFORMANCE_BOTTLENECKS.value,
				"name": "Performance Bottlenecks",
				"description": "Nodes or structures causing performance issues"
			}
		]
	
	def _categorize_issues(self, issues: List) -> Dict[str, List]:
		"""Categorize issues by type and severity"""
		categorized = {
			"critical": [],
			"high": [],
			"medium": [],
			"low": []
		}
		
		for issue in issues:
			severity = issue.severity.value
			if severity in categorized:
				categorized[severity].append(issue)
		
		return categorized
	
	def _calculate_health_metrics(self, issues: List) -> Dict[str, Any]:
		"""Calculate health metrics from issues"""
		total_issues = len(issues)
		auto_fixable = len([i for i in issues if i.auto_fixable])
		critical = len([i for i in issues if i.severity == IssueSeverity.CRITICAL])
		
		# Calculate health score
		health_score = max(0, 100 - (critical * 25 + (total_issues - critical) * 5))
		
		return {
			"health_score": health_score,
			"total_issues": total_issues,
			"auto_fixable_issues": auto_fixable,
			"critical_issues": critical,
			"health_status": "healthy" if health_score > 80 else (
				"warning" if health_score > 60 else "critical"
			)
		}
	
	# API Endpoints
	
	@expose_api("post", "/api/run-health-check/<graph_name>/")
	@has_access
	@permission_name("can_monitor_graph_health")
	def api_run_health_check(self, graph_name):
		"""API endpoint to run health check"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			optimizer = get_graph_optimizer(graph_name)
			
			# Run health check
			issues = optimizer.health_checker.run_comprehensive_health_check()
			
			# Calculate metrics
			health_metrics = self._calculate_health_metrics(issues)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.HEALTH_CHECK_RUN,
				target=f"Graph: {graph_name}",
				description="Manual health check executed",
				details={
					"user_id": user_id,
					"graph_name": graph_name,
					"issues_found": len(issues),
					"health_score": health_metrics["health_score"]
				}
			)
			
			return jsonify({
				"success": True,
				"graph_name": graph_name,
				"issues": [issue.to_dict() for issue in issues],
				"health_metrics": health_metrics,
				"message": f"Health check completed: {len(issues)} issues found"
			})
			
		except Exception as e:
			logger.error(f"API error running health check: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/run-optimization/<graph_name>/")
	@has_access
	@permission_name("can_optimize_graphs")
	def api_run_optimization(self, graph_name):
		"""API endpoint to run graph optimization"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json() or {}
			level_str = data.get("optimization_level", "moderate")
			
			# Convert string to enum
			try:
				level = OptimizationLevel(level_str)
			except ValueError:
				raise BadRequest(f"Invalid optimization level: {level_str}")
			
			user_id = self._get_current_user_id()
			
			# Run optimization
			optimization_results = run_automated_healing(graph_name, level)
			
			# Calculate summary statistics
			total_fixed = sum(result.items_fixed for result in optimization_results)
			avg_improvement = np.mean([result.performance_improvement for result in optimization_results]) if optimization_results else 0
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.GRAPH_OPTIMIZED,
				target=f"Graph: {graph_name}",
				description=f"Manual optimization executed (level: {level.value})",
				details={
					"user_id": user_id,
					"graph_name": graph_name,
					"optimization_level": level.value,
					"operations_completed": len(optimization_results),
					"items_fixed": total_fixed,
					"average_improvement": avg_improvement
				}
			)
			
			return jsonify({
				"success": True,
				"graph_name": graph_name,
				"optimization_level": level.value,
				"results": [result.to_dict() for result in optimization_results],
				"summary": {
					"operations_completed": len(optimization_results),
					"items_fixed": total_fixed,
					"average_performance_improvement": avg_improvement
				},
				"message": f"Optimization completed: {len(optimization_results)} operations, {total_fixed} items fixed"
			})
			
		except Exception as e:
			logger.error(f"API error running optimization: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/optimization-report/<graph_name>/")
	@has_access
	@permission_name("can_view_optimization_reports")
	def api_get_optimization_report(self, graph_name):
		"""API endpoint to get optimization report"""
		try:
			self._ensure_admin_access()
			
			optimizer = get_graph_optimizer(graph_name)
			report = optimizer.get_optimization_report()
			
			return jsonify({
				"success": True,
				"report": report
			})
			
		except Exception as e:
			logger.error(f"API error getting optimization report: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/health-summary/")
	@has_access
	@permission_name("can_view_health_summary")
	def api_get_health_summary(self):
		"""API endpoint to get health summary across all graphs"""
		try:
			self._ensure_admin_access()
			
			available_graphs = self._get_available_graphs()
			health_statistics = self._get_overall_health_stats(available_graphs)
			
			# Get detailed health for each graph
			graph_health = {}
			for graph_name in available_graphs:
				try:
					optimizer = get_graph_optimizer(graph_name)
					issues = optimizer.health_checker.run_comprehensive_health_check()
					graph_health[graph_name] = self._calculate_health_metrics(issues)
				except Exception as e:
					logger.warning(f"Could not get health for {graph_name}: {e}")
					graph_health[graph_name] = {"health_score": 0, "error": str(e)}
			
			return jsonify({
				"success": True,
				"overall_statistics": health_statistics,
				"graph_health": graph_health,
				"timestamp": datetime.now().isoformat()
			})
			
		except Exception as e:
			logger.error(f"API error getting health summary: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/schedule-optimization/")
	@has_access
	@permission_name("can_schedule_optimizations")
	def api_schedule_optimization(self):
		"""API endpoint to schedule automated optimizations"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_names = data.get("graph_names", [])
			schedule = data.get("schedule", "daily")  # daily, weekly, monthly
			optimization_level = data.get("optimization_level", "moderate")
			enabled = data.get("enabled", True)
			
			if not graph_names:
				raise BadRequest("graph_names is required")
			
			user_id = self._get_current_user_id()
			
			# Mock implementation - would integrate with task scheduler
			scheduled_tasks = []
			for graph_name in graph_names:
				task_id = uuid7str()
				scheduled_tasks.append({
					"task_id": task_id,
					"graph_name": graph_name,
					"schedule": schedule,
					"optimization_level": optimization_level,
					"enabled": enabled,
					"created_by": user_id,
					"next_run": self._calculate_next_run(schedule)
				})
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.OPTIMIZATION_SCHEDULED,
				target=f"Graphs: {', '.join(graph_names)}",
				description=f"Scheduled {schedule} optimizations",
				details={
					"user_id": user_id,
					"graph_names": graph_names,
					"schedule": schedule,
					"optimization_level": optimization_level,
					"task_count": len(scheduled_tasks)
				}
			)
			
			return jsonify({
				"success": True,
				"scheduled_tasks": scheduled_tasks,
				"message": f"Scheduled {len(scheduled_tasks)} optimization tasks"
			})
			
		except Exception as e:
			logger.error(f"API error scheduling optimization: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	def _calculate_next_run(self, schedule: str) -> str:
		"""Calculate next run time for scheduled optimization"""
		from datetime import datetime, timedelta
		
		now = datetime.now()
		
		if schedule == "daily":
			next_run = now + timedelta(days=1)
		elif schedule == "weekly":
			next_run = now + timedelta(weeks=1)
		elif schedule == "monthly":
			next_run = now + timedelta(days=30)
		else:
			next_run = now + timedelta(days=1)  # Default to daily
			
		return next_run.isoformat()