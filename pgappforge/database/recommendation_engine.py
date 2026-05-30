"""
Intelligent Graph Recommendation Engine

Advanced recommendation system that uses machine learning and graph algorithms
to provide intelligent suggestions for queries, optimizations, and insights.
"""

import logging
import json
import time
import numpy as np
import networkx as nx
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

import psycopg2
from pydantic import BaseModel, Field
from uuid_extensions import uuid7str

from .graph_manager import GraphManager
from .activity_tracker import track_database_activity, ActivityType, ActivitySeverity
from ..utils.error_handling import WizardErrorHandler, WizardErrorType, WizardErrorSeverity

logger = logging.getLogger(__name__)


class RecommendationType:
	"""Types of recommendations the engine can provide"""
	QUERY_OPTIMIZATION = "query_optimization"
	SCHEMA_IMPROVEMENT = "schema_improvement" 
	INDEX_SUGGESTION = "index_suggestion"
	VISUALIZATION_HINT = "visualization_hint"
	ANALYSIS_INSIGHT = "analysis_insight"
	COLLABORATION_TIP = "collaboration_tip"
	DATA_QUALITY = "data_quality"
	PERFORMANCE_BOOST = "performance_boost"


@dataclass
class Recommendation:
	"""Individual recommendation with scoring and rationale"""
	recommendation_id: str
	type: str
	title: str
	description: str
	confidence_score: float  # 0.0 to 1.0
	potential_impact: str  # "low", "medium", "high"
	implementation_effort: str  # "easy", "moderate", "complex"
	category: str
	suggested_action: str
	rationale: str
	supporting_data: Dict[str, Any]
	created_at: datetime
	applicable_graphs: List[str]
	user_context: Optional[Dict[str, Any]] = None
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"recommendation_id": self.recommendation_id,
			"type": self.type,
			"title": self.title,
			"description": self.description,
			"confidence_score": self.confidence_score,
			"potential_impact": self.potential_impact,
			"implementation_effort": self.implementation_effort,
			"category": self.category,
			"suggested_action": self.suggested_action,
			"rationale": self.rationale,
			"supporting_data": self.supporting_data,
			"created_at": self.created_at.isoformat(),
			"applicable_graphs": self.applicable_graphs,
			"user_context": self.user_context or {}
		}


class QueryPatternAnalyzer:
	"""Analyzes query patterns to identify optimization opportunities"""
	
	def __init__(self):
		self.query_history = defaultdict(list)
		self.pattern_cache = {}
		self.tfidf_vectorizer = TfidfVectorizer(
			max_features=1000,
			stop_words='english',
			ngram_range=(1, 3)
		)
		
	def record_query_execution(self, user_id: str, query: str, execution_time: float,
							   result_count: int, graph_name: str):
		"""Record query execution for pattern analysis"""
		self.query_history[user_id].append({
			"query": query,
			"execution_time": execution_time,
			"result_count": result_count,
			"graph_name": graph_name,
			"timestamp": datetime.now()
		})
		
	def analyze_query_patterns(self, user_id: str) -> List[Dict[str, Any]]:
		"""Analyze user's query patterns to identify trends"""
		patterns = []
		
		user_queries = self.query_history.get(user_id, [])
		if len(user_queries) < 5:
			return patterns
			
		# Analyze query complexity trends
		complexity_scores = []
		execution_times = []
		
		for query_data in user_queries[-50:]:  # Last 50 queries
			complexity = self._calculate_query_complexity(query_data["query"])
			complexity_scores.append(complexity)
			execution_times.append(query_data["execution_time"])
			
		# Identify patterns
		avg_complexity = np.mean(complexity_scores)
		avg_execution_time = np.mean(execution_times)
		
		patterns.append({
			"pattern_type": "complexity_trend",
			"average_complexity": avg_complexity,
			"complexity_trend": self._calculate_trend(complexity_scores),
			"performance_correlation": np.corrcoef(complexity_scores, execution_times)[0, 1]
		})
		
		# Find common query structures
		query_texts = [q["query"] for q in user_queries[-20:]]
		common_patterns = self._find_common_structures(query_texts)
		
		patterns.append({
			"pattern_type": "common_structures",
			"frequent_patterns": common_patterns,
			"optimization_potential": self._assess_optimization_potential(common_patterns)
		})
		
		return patterns
		
	def _calculate_query_complexity(self, query: str) -> float:
		"""Calculate complexity score for a query"""
		complexity = 0
		
		# Basic complexity factors
		complexity += len(query.split()) * 0.1  # Word count
		complexity += query.count("JOIN") * 2
		complexity += query.count("WHERE") * 1.5
		complexity += query.count("GROUP BY") * 2
		complexity += query.count("ORDER BY") * 1
		complexity += query.count("UNION") * 3
		
		# Cypher-specific complexity
		complexity += query.count("MATCH") * 1
		complexity += query.count("OPTIONAL MATCH") * 2
		complexity += query.count("WITH") * 1.5
		complexity += query.count("UNWIND") * 2
		complexity += query.count("FOREACH") * 3
		
		return min(complexity, 100)  # Cap at 100
		
	def _calculate_trend(self, values: List[float]) -> str:
		"""Calculate if values are trending up, down, or stable"""
		if len(values) < 3:
			return "stable"
			
		# Simple linear regression slope
		x = np.arange(len(values))
		slope = np.polyfit(x, values, 1)[0]
		
		if slope > 0.5:
			return "increasing"
		elif slope < -0.5:
			return "decreasing"
		else:
			return "stable"
			
	def _find_common_structures(self, queries: List[str]) -> List[Dict[str, Any]]:
		"""Find common structural patterns in queries"""
		patterns = []
		
		# Extract query templates by replacing literals with placeholders
		templates = []
		for query in queries:
			template = self._extract_template(query)
			templates.append(template)
			
		# Count template frequency
		template_counts = Counter(templates)
		
		for template, count in template_counts.most_common(5):
			if count > 1:  # Only patterns that appear multiple times
				patterns.append({
					"template": template,
					"frequency": count,
					"percentage": count / len(queries) * 100
				})
				
		return patterns
		
	def _extract_template(self, query: str) -> str:
		"""Extract structural template from query"""
		import re
		
		# Replace string literals
		template = re.sub(r"'[^']*'", "'STRING'", query)
		template = re.sub(r'"[^"]*"', '"STRING"', template)
		
		# Replace numbers
		template = re.sub(r'\b\d+\b', 'NUMBER', template)
		
		# Replace identifiers that look like variables
		template = re.sub(r'\b[a-zA-Z_]\w*\b', 'IDENTIFIER', template)
		
		return template
		
	def _assess_optimization_potential(self, patterns: List[Dict[str, Any]]) -> str:
		"""Assess optimization potential based on patterns"""
		if not patterns:
			return "low"
			
		total_frequency = sum(p["frequency"] for p in patterns)
		
		if total_frequency > 10:
			return "high"
		elif total_frequency > 5:
			return "medium"
		else:
			return "low"


class SchemaRecommendationEngine:
	"""Analyzes graph schema to provide improvement recommendations"""
	
	def __init__(self, graph_name: str):
		self.graph_name = graph_name
		self.graph_manager = GraphManager(graph_name)
		
	def analyze_schema_health(self) -> List[Dict[str, Any]]:
		"""Analyze schema and identify potential improvements"""
		recommendations = []
		
		try:
			# Get schema statistics
			schema_stats = self._get_schema_statistics()
			
			# Check for missing indexes
			index_recommendations = self._analyze_index_opportunities(schema_stats)
			recommendations.extend(index_recommendations)
			
			# Check for schema normalization
			normalization_recommendations = self._analyze_normalization(schema_stats)
			recommendations.extend(normalization_recommendations)
			
			# Check for relationship patterns
			relationship_recommendations = self._analyze_relationship_patterns(schema_stats)
			recommendations.extend(relationship_recommendations)
			
		except Exception as e:
			logger.error(f"Schema analysis failed: {e}")
			
		return recommendations
		
	def _get_schema_statistics(self) -> Dict[str, Any]:
		"""Get comprehensive schema statistics"""
		stats = {
			"node_types": {},
			"relationship_types": {},
			"property_usage": {},
			"connectivity_metrics": {}
		}
		
		try:
			# Get node type distribution
			node_query = """
			MATCH (n)
			RETURN labels(n) as labels, count(*) as count
			ORDER BY count DESC
			"""
			node_results = self.graph_manager.execute_cypher_query(node_query)
			
			for result in node_results:
				labels_str = str(result.get("labels", []))
				stats["node_types"][labels_str] = result.get("count", 0)
				
			# Get relationship statistics
			rel_query = """
			MATCH ()-[r]->()
			RETURN type(r) as rel_type, count(*) as count
			ORDER BY count DESC
			"""
			rel_results = self.graph_manager.execute_cypher_query(rel_query)
			
			for result in rel_results:
				rel_type = result.get("rel_type", "unknown")
				stats["relationship_types"][rel_type] = result.get("count", 0)
				
			# Property usage analysis
			prop_query = """
			MATCH (n)
			UNWIND keys(n) as key
			RETURN key, count(*) as usage_count
			ORDER BY usage_count DESC
			"""
			prop_results = self.graph_manager.execute_cypher_query(prop_query)
			
			for result in prop_results:
				key = result.get("key", "unknown")
				stats["property_usage"][key] = result.get("usage_count", 0)
				
		except Exception as e:
			logger.error(f"Schema statistics collection failed: {e}")
			
		return stats
		
	def _analyze_index_opportunities(self, schema_stats: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""Identify potential index creation opportunities"""
		recommendations = []
		
		# High-usage properties might benefit from indexes
		for prop, usage_count in schema_stats["property_usage"].items():
			if usage_count > 100:  # Threshold for index consideration
				recommendations.append({
					"type": "index_suggestion",
					"property": prop,
					"usage_count": usage_count,
					"estimated_benefit": "high" if usage_count > 1000 else "medium",
					"suggested_index": f"CREATE INDEX ON :NodeLabel({prop})"
				})
				
		return recommendations
		
	def _analyze_normalization(self, schema_stats: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""Analyze schema normalization opportunities"""
		recommendations = []
		
		# Look for properties that might be better as separate nodes
		high_cardinality_props = []
		for prop, usage_count in schema_stats["property_usage"].items():
			if usage_count > 50 and self._is_high_cardinality_property(prop):
				high_cardinality_props.append((prop, usage_count))
				
		for prop, usage_count in high_cardinality_props:
			recommendations.append({
				"type": "normalization_suggestion",
				"property": prop,
				"current_usage": usage_count,
				"suggestion": f"Consider extracting '{prop}' as separate node type",
				"rationale": "High cardinality property might benefit from normalization"
			})
			
		return recommendations
		
	def _analyze_relationship_patterns(self, schema_stats: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""Analyze relationship patterns for optimization"""
		recommendations = []
		
		# Look for relationship types that might need optimization
		for rel_type, count in schema_stats["relationship_types"].items():
			if count > 10000:  # High relationship count
				recommendations.append({
					"type": "relationship_optimization",
					"relationship_type": rel_type,
					"count": count,
					"suggestion": f"Consider partitioning or indexing for '{rel_type}' relationships",
					"impact": "performance"
				})
				
		return recommendations
		
	def _is_high_cardinality_property(self, property_name: str) -> bool:
		"""Check if a property likely has high cardinality"""
		high_cardinality_indicators = [
			"id", "email", "phone", "address", "description",
			"url", "timestamp", "date", "uuid"
		]
		
		return any(indicator in property_name.lower() for indicator in high_cardinality_indicators)


class CollaborationRecommendationEngine:
	"""Recommends collaboration opportunities and sharing strategies"""
	
	def __init__(self):
		self.user_activities = defaultdict(list)
		self.collaboration_patterns = {}
		
	def record_user_activity(self, user_id: str, activity_type: str, 
							graph_name: str, details: Dict[str, Any]):
		"""Record user activity for collaboration analysis"""
		self.user_activities[user_id].append({
			"activity_type": activity_type,
			"graph_name": graph_name,
			"details": details,
			"timestamp": datetime.now()
		})
		
	def find_collaboration_opportunities(self, user_id: str) -> List[Dict[str, Any]]:
		"""Find potential collaboration opportunities for a user"""
		opportunities = []
		
		try:
			user_graphs = self._get_user_graphs(user_id)
			similar_users = self._find_similar_users(user_id)
			
			for similar_user in similar_users[:5]:  # Top 5 similar users
				common_interests = self._find_common_interests(user_id, similar_user)
				
				if common_interests:
					opportunities.append({
						"type": "user_collaboration",
						"similar_user": similar_user,
						"common_interests": common_interests,
						"collaboration_score": self._calculate_collaboration_score(
							user_id, similar_user
						),
						"suggested_action": f"Share insights on {common_interests[0]}"
					})
					
			# Find sharing opportunities
			sharing_opportunities = self._find_sharing_opportunities(user_id, user_graphs)
			opportunities.extend(sharing_opportunities)
			
		except Exception as e:
			logger.error(f"Collaboration analysis failed: {e}")
			
		return opportunities
		
	def _get_user_graphs(self, user_id: str) -> List[str]:
		"""Get graphs that user has worked with"""
		graphs = set()
		
		for activity in self.user_activities[user_id]:
			graphs.add(activity["graph_name"])
			
		return list(graphs)
		
	def _find_similar_users(self, user_id: str) -> List[str]:
		"""Find users with similar activity patterns"""
		similar_users = []
		user_activities = self.user_activities[user_id]
		
		if not user_activities:
			return similar_users
			
		user_graphs = set(activity["graph_name"] for activity in user_activities)
		user_activity_types = set(activity["activity_type"] for activity in user_activities)
		
		for other_user_id, other_activities in self.user_activities.items():
			if other_user_id == user_id:
				continue
				
			other_graphs = set(activity["graph_name"] for activity in other_activities)
			other_activity_types = set(activity["activity_type"] for activity in other_activities)
			
			# Calculate similarity based on common graphs and activities
			graph_similarity = len(user_graphs & other_graphs) / len(user_graphs | other_graphs)
			activity_similarity = len(user_activity_types & other_activity_types) / len(user_activity_types | other_activity_types)
			
			overall_similarity = (graph_similarity + activity_similarity) / 2
			
			if overall_similarity > 0.3:  # Threshold for similarity
				similar_users.append((other_user_id, overall_similarity))
				
		# Sort by similarity and return user IDs
		similar_users.sort(key=lambda x: x[1], reverse=True)
		return [user_id for user_id, _ in similar_users]
		
	def _find_common_interests(self, user1_id: str, user2_id: str) -> List[str]:
		"""Find common interests between two users"""
		user1_graphs = self._get_user_graphs(user1_id)
		user2_graphs = self._get_user_graphs(user2_id)
		
		common_graphs = list(set(user1_graphs) & set(user2_graphs))
		return common_graphs
		
	def _calculate_collaboration_score(self, user1_id: str, user2_id: str) -> float:
		"""Calculate collaboration potential score"""
		# Simple scoring based on activity overlap and recency
		user1_recent = [a for a in self.user_activities[user1_id] 
						if a["timestamp"] > datetime.now() - timedelta(days=7)]
		user2_recent = [a for a in self.user_activities[user2_id]
						if a["timestamp"] > datetime.now() - timedelta(days=7)]
		
		if not user1_recent or not user2_recent:
			return 0.0
			
		common_graphs = len(set(a["graph_name"] for a in user1_recent) & 
						   set(a["graph_name"] for a in user2_recent))
		
		return min(common_graphs / 5.0, 1.0)  # Normalize to 0-1
		
	def _find_sharing_opportunities(self, user_id: str, user_graphs: List[str]) -> List[Dict[str, Any]]:
		"""Find opportunities to share work with others"""
		opportunities = []
		
		for graph_name in user_graphs:
			# Check if user has created valuable queries or insights
			user_graph_activities = [
				a for a in self.user_activities[user_id] 
				if a["graph_name"] == graph_name
			]
			
			if len(user_graph_activities) > 10:  # Significant activity
				opportunities.append({
					"type": "sharing_opportunity",
					"graph_name": graph_name,
					"activity_count": len(user_graph_activities),
					"suggestion": f"Consider creating a shared workspace for '{graph_name}'",
					"potential_collaborators": len([
						uid for uid in self.user_activities.keys()
						if uid != user_id and any(
							a["graph_name"] == graph_name 
							for a in self.user_activities[uid]
						)
					])
				})
				
		return opportunities


class IntelligentRecommendationEngine:
	"""Main recommendation engine coordinating all recommendation types"""
	
	def __init__(self):
		self.query_analyzer = QueryPatternAnalyzer()
		self.collaboration_engine = CollaborationRecommendationEngine()
		self.error_handler = WizardErrorHandler()
		self.recommendation_cache = {}
		self.user_feedback = defaultdict(list)
		
		logger.info("Intelligent Recommendation Engine initialized")
		
	def generate_recommendations(self, user_id: str, graph_name: str, 
								context: Optional[Dict[str, Any]] = None) -> List[Recommendation]:
		"""Generate personalized recommendations for a user and graph"""
		recommendations = []
		
		try:
			# Query optimization recommendations
			query_patterns = self.query_analyzer.analyze_query_patterns(user_id)
			query_recommendations = self._generate_query_recommendations(
				user_id, graph_name, query_patterns
			)
			recommendations.extend(query_recommendations)
			
			# Schema improvement recommendations
			schema_engine = SchemaRecommendationEngine(graph_name)
			schema_analysis = schema_engine.analyze_schema_health()
			schema_recommendations = self._generate_schema_recommendations(
				graph_name, schema_analysis
			)
			recommendations.extend(schema_recommendations)
			
			# Collaboration recommendations
			collaboration_opportunities = self.collaboration_engine.find_collaboration_opportunities(user_id)
			collaboration_recommendations = self._generate_collaboration_recommendations(
				user_id, collaboration_opportunities
			)
			recommendations.extend(collaboration_recommendations)
			
			# Performance recommendations
			performance_recommendations = self._generate_performance_recommendations(
				user_id, graph_name, context
			)
			recommendations.extend(performance_recommendations)
			
			# Visualization recommendations
			viz_recommendations = self._generate_visualization_recommendations(
				user_id, graph_name, context
			)
			recommendations.extend(viz_recommendations)
			
			# Sort by confidence and potential impact
			recommendations.sort(key=lambda r: (r.confidence_score, 
											   self._impact_score(r.potential_impact)), 
								reverse=True)
			
			# Cache recommendations
			cache_key = f"{user_id}_{graph_name}_{int(time.time() // 3600)}"  # Hourly cache
			self.recommendation_cache[cache_key] = recommendations
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATA_PROCESSING_ERROR, WizardErrorSeverity.MEDIUM
			)
			logger.error(f"Recommendation generation failed: {e}")
			
		return recommendations[:20]  # Return top 20 recommendations
		
	def _generate_query_recommendations(self, user_id: str, graph_name: str, 
									   patterns: List[Dict[str, Any]]) -> List[Recommendation]:
		"""Generate query optimization recommendations"""
		recommendations = []
		
		for pattern in patterns:
			if pattern["pattern_type"] == "complexity_trend":
				if pattern["complexity_trend"] == "increasing":
					recommendations.append(Recommendation(
						recommendation_id=uuid7str(),
						type=RecommendationType.QUERY_OPTIMIZATION,
						title="Query Complexity Trending Upward",
						description="Your queries are becoming increasingly complex over time",
						confidence_score=0.8,
						potential_impact="medium",
						implementation_effort="easy",
						category="Performance",
						suggested_action="Review recent queries for optimization opportunities",
						rationale="Complex queries can lead to performance issues",
						supporting_data={"average_complexity": pattern["average_complexity"]},
						created_at=datetime.now(),
						applicable_graphs=[graph_name]
					))
					
			elif pattern["pattern_type"] == "common_structures":
				if pattern["optimization_potential"] == "high":
					recommendations.append(Recommendation(
						recommendation_id=uuid7str(),
						type=RecommendationType.QUERY_OPTIMIZATION,
						title="Frequent Query Pattern Detected",
						description="You frequently use similar query patterns that could be optimized",
						confidence_score=0.9,
						potential_impact="high",
						implementation_effort="moderate",
						category="Performance",
						suggested_action="Consider creating optimized query templates",
						rationale="Optimizing frequently used patterns provides significant benefits",
						supporting_data={"frequent_patterns": pattern["frequent_patterns"]},
						created_at=datetime.now(),
						applicable_graphs=[graph_name]
					))
					
		return recommendations
		
	def _generate_schema_recommendations(self, graph_name: str, 
									   analysis: List[Dict[str, Any]]) -> List[Recommendation]:
		"""Generate schema improvement recommendations"""
		recommendations = []
		
		for suggestion in analysis:
			if suggestion["type"] == "index_suggestion":
				recommendations.append(Recommendation(
					recommendation_id=uuid7str(),
					type=RecommendationType.INDEX_SUGGESTION,
					title=f"Index Opportunity: {suggestion['property']}",
					description=f"Property '{suggestion['property']}' is heavily used and would benefit from an index",
					confidence_score=0.85,
					potential_impact=suggestion["estimated_benefit"],
					implementation_effort="easy",
					category="Performance",
					suggested_action=suggestion["suggested_index"],
					rationale=f"Property used {suggestion['usage_count']} times",
					supporting_data=suggestion,
					created_at=datetime.now(),
					applicable_graphs=[graph_name]
				))
				
			elif suggestion["type"] == "normalization_suggestion":
				recommendations.append(Recommendation(
					recommendation_id=uuid7str(),
					type=RecommendationType.SCHEMA_IMPROVEMENT,
					title=f"Schema Normalization: {suggestion['property']}",
					description=suggestion["suggestion"],
					confidence_score=0.7,
					potential_impact="medium",
					implementation_effort="complex",
					category="Data Quality",
					suggested_action="Consider refactoring schema",
					rationale=suggestion["rationale"],
					supporting_data=suggestion,
					created_at=datetime.now(),
					applicable_graphs=[graph_name]
				))
				
		return recommendations
		
	def _generate_collaboration_recommendations(self, user_id: str, 
											  opportunities: List[Dict[str, Any]]) -> List[Recommendation]:
		"""Generate collaboration recommendations"""
		recommendations = []
		
		for opportunity in opportunities:
			if opportunity["type"] == "user_collaboration":
				recommendations.append(Recommendation(
					recommendation_id=uuid7str(),
					type=RecommendationType.COLLABORATION_TIP,
					title="Collaboration Opportunity",
					description=f"You share similar interests with another user",
					confidence_score=opportunity["collaboration_score"],
					potential_impact="medium",
					implementation_effort="easy",
					category="Collaboration",
					suggested_action=opportunity["suggested_action"],
					rationale="Collaboration can lead to new insights",
					supporting_data=opportunity,
					created_at=datetime.now(),
					applicable_graphs=[]
				))
				
			elif opportunity["type"] == "sharing_opportunity":
				recommendations.append(Recommendation(
					recommendation_id=uuid7str(),
					type=RecommendationType.COLLABORATION_TIP,
					title="Share Your Work",
					description=opportunity["suggestion"],
					confidence_score=0.8,
					potential_impact="high",
					implementation_effort="moderate",
					category="Knowledge Sharing",
					suggested_action="Create shared workspace or documentation",
					rationale=f"High activity count: {opportunity['activity_count']}",
					supporting_data=opportunity,
					created_at=datetime.now(),
					applicable_graphs=[opportunity["graph_name"]]
				))
				
		return recommendations
		
	def _generate_performance_recommendations(self, user_id: str, graph_name: str,
											context: Optional[Dict[str, Any]]) -> List[Recommendation]:
		"""Generate performance-related recommendations"""
		recommendations = []
		
		# Generic performance recommendations based on common patterns
		recommendations.append(Recommendation(
			recommendation_id=uuid7str(),
			type=RecommendationType.PERFORMANCE_BOOST,
			title="Enable Query Result Caching",
			description="Frequently accessed query results could be cached for better performance",
			confidence_score=0.7,
			potential_impact="medium",
			implementation_effort="easy",
			category="Performance",
			suggested_action="Configure query result caching in settings",
			rationale="Caching reduces database load for repeated queries",
			supporting_data={"cache_hit_ratio_potential": 0.3},
			created_at=datetime.now(),
			applicable_graphs=[graph_name]
		))
		
		return recommendations
		
	def _generate_visualization_recommendations(self, user_id: str, graph_name: str,
											  context: Optional[Dict[str, Any]]) -> List[Recommendation]:
		"""Generate visualization improvement recommendations"""
		recommendations = []
		
		recommendations.append(Recommendation(
			recommendation_id=uuid7str(),
			type=RecommendationType.VISUALIZATION_HINT,
			title="Try Advanced Layout Algorithms",
			description="Your graph might benefit from specialized layout algorithms",
			confidence_score=0.6,
			potential_impact="medium",
			implementation_effort="easy",
			category="Visualization",
			suggested_action="Experiment with force-directed or hierarchical layouts",
			rationale="Different layouts can reveal different patterns",
			supporting_data={"available_layouts": ["force_directed", "circular", "hierarchical"]},
			created_at=datetime.now(),
			applicable_graphs=[graph_name]
		))
		
		return recommendations
		
	def _impact_score(self, impact: str) -> int:
		"""Convert impact string to numeric score"""
		return {"low": 1, "medium": 2, "high": 3}.get(impact, 1)
		
	def record_user_feedback(self, user_id: str, recommendation_id: str, 
							feedback: str, implemented: bool):
		"""Record user feedback on recommendations"""
		self.user_feedback[user_id].append({
			"recommendation_id": recommendation_id,
			"feedback": feedback,
			"implemented": implemented,
			"timestamp": datetime.now()
		})
		
		# Track feedback activity
		track_database_activity(
			activity_type=ActivityType.RECOMMENDATION_FEEDBACK,
			target=f"Recommendation: {recommendation_id}",
			description=f"User provided feedback: {feedback}",
			details={
				"user_id": user_id,
				"implemented": implemented,
				"feedback": feedback
			}
		)
		
	def get_recommendation_analytics(self, user_id: Optional[str] = None) -> Dict[str, Any]:
		"""Get analytics on recommendation effectiveness"""
		analytics = {
			"total_recommendations": 0,
			"implementation_rate": 0.0,
			"category_breakdown": defaultdict(int),
			"feedback_sentiment": {"positive": 0, "neutral": 0, "negative": 0}
		}
		
		try:
			feedback_data = self.user_feedback[user_id] if user_id else []
			if not user_id:
				# Aggregate all user feedback
				for user_feedback in self.user_feedback.values():
					feedback_data.extend(user_feedback)
					
			if feedback_data:
				analytics["total_recommendations"] = len(feedback_data)
				implemented_count = sum(1 for f in feedback_data if f["implemented"])
				analytics["implementation_rate"] = implemented_count / len(feedback_data)
				
				# Analyze feedback sentiment (simple keyword-based)
				for feedback in feedback_data:
					sentiment = self._analyze_sentiment(feedback["feedback"])
					analytics["feedback_sentiment"][sentiment] += 1
					
		except Exception as e:
			logger.error(f"Analytics generation failed: {e}")
			
		return analytics
		
	def _analyze_sentiment(self, feedback_text: str) -> str:
		"""Simple sentiment analysis for feedback"""
		positive_words = ["good", "helpful", "useful", "great", "excellent", "works"]
		negative_words = ["bad", "useless", "wrong", "poor", "terrible", "broken"]
		
		text_lower = feedback_text.lower()
		
		positive_count = sum(1 for word in positive_words if word in text_lower)
		negative_count = sum(1 for word in negative_words if word in text_lower)
		
		if positive_count > negative_count:
			return "positive"
		elif negative_count > positive_count:
			return "negative"
		else:
			return "neutral"
		
	def export_recommendations(self, recommendations: List[Recommendation], 
							  format: str = "json") -> Union[str, Dict[str, Any]]:
		"""Export recommendations in specified format"""
		if format == "json":
			return {
				"recommendations": [r.to_dict() for r in recommendations],
				"generated_at": datetime.now().isoformat(),
				"total_count": len(recommendations)
			}
		elif format == "csv":
			import csv
			from io import StringIO
			
			output = StringIO()
			writer = csv.writer(output)
			
			# Write header
			writer.writerow([
				"recommendation_id", "type", "category", "priority", "confidence",
				"title", "description", "impact_score", "implementation_effort",
				"created_at"
			])
			
			# Write data rows
			for rec in recommendations:
				writer.writerow([
					rec.recommendation_id,
					rec.recommendation_type.value,
					rec.category,
					rec.priority.value,
					rec.confidence_score,
					rec.title,
					rec.description,
					rec.impact_score,
					rec.implementation_effort.value,
					rec.created_at.isoformat()
				])
			
			return output.getvalue()
		else:
			raise ValueError(f"Unsupported export format: {format}")


# Global recommendation engine instance
_recommendation_engine = None


def get_recommendation_engine() -> IntelligentRecommendationEngine:
	"""Get the global recommendation engine instance"""
	global _recommendation_engine
	if _recommendation_engine is None:
		_recommendation_engine = IntelligentRecommendationEngine()
	return _recommendation_engine


def generate_user_recommendations(user_id: str, graph_name: str, 
								 context: Optional[Dict[str, Any]] = None) -> List[Recommendation]:
	"""Convenience function to generate recommendations for a user"""
	engine = get_recommendation_engine()
	return engine.generate_recommendations(user_id, graph_name, context or {})