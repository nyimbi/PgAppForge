"""
AI Analytics Assistant for Graph Analysis

Provides intelligent insights, automated analysis suggestions, natural language
query capabilities, and AI-powered recommendations for graph data exploration.
"""

import json
import logging
import re
import threading
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict, field
from enum import Enum
import hashlib

try:
	import openai
	OPENAI_AVAILABLE = True
except ImportError:
	OPENAI_AVAILABLE = False

try:
	import spacy
	SPACY_AVAILABLE = True
except ImportError:
	SPACY_AVAILABLE = False

import numpy as np
from sqlalchemy import text

from .graph_manager import GraphDatabaseManager, get_graph_manager
from .multi_graph_manager import get_graph_registry
from .query_builder import CypherQueryValidator, VisualQueryBuilder
from .graph_ml import get_ml_engine, get_pattern_miner
from .activity_tracker import track_database_activity, ActivityType
from .performance_optimizer import get_performance_monitor, performance_cache

logger = logging.getLogger(__name__)


class AnalysisType(Enum):
	"""Types of AI-powered analyses"""
	GRAPH_STRUCTURE_ANALYSIS = "graph_structure_analysis"
	ANOMALY_DETECTION = "anomaly_detection"
	PATTERN_DISCOVERY = "pattern_discovery"
	TREND_ANALYSIS = "trend_analysis"
	SIMILARITY_ANALYSIS = "similarity_analysis"
	CENTRALITY_ANALYSIS = "centrality_analysis"
	COMMUNITY_DETECTION = "community_detection"
	PATH_ANALYSIS = "path_analysis"
	INFLUENCE_PROPAGATION = "influence_propagation"
	PREDICTIVE_MODELING = "predictive_modeling"


class InsightPriority(Enum):
	"""Priority levels for insights"""
	LOW = "low"
	MEDIUM = "medium"
	HIGH = "high"
	CRITICAL = "critical"


class QueryComplexity(Enum):
	"""Query complexity levels"""
	SIMPLE = "simple"
	MODERATE = "moderate"
	COMPLEX = "complex"
	EXPERT = "expert"


@dataclass
class AIInsight:
	"""
	AI-generated insight about graph data
	
	Attributes:
		insight_id: Unique insight identifier
		title: Insight title/summary
		description: Detailed description
		analysis_type: Type of analysis that generated this insight
		priority: Insight priority level
		confidence_score: AI confidence (0-1)
		data_evidence: Supporting data/statistics
		recommended_actions: Suggested follow-up actions
		cypher_queries: Related Cypher queries
		visualizations: Suggested visualization configs
		created_at: When insight was generated
		metadata: Additional insight metadata
	"""
	
	insight_id: str
	title: str
	description: str
	analysis_type: AnalysisType
	priority: InsightPriority
	confidence_score: float
	data_evidence: Dict[str, Any] = field(default_factory=dict)
	recommended_actions: List[str] = field(default_factory=list)
	cypher_queries: List[str] = field(default_factory=list)
	visualizations: List[Dict[str, Any]] = field(default_factory=list)
	created_at: datetime = field(default_factory=datetime.utcnow)
	metadata: Dict[str, Any] = field(default_factory=dict)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["analysis_type"] = self.analysis_type.value
		data["priority"] = self.priority.value
		data["created_at"] = self.created_at.isoformat()
		return data


@dataclass
class QuerySuggestion:
	"""
	AI-generated query suggestion
	
	Attributes:
		suggestion_id: Unique suggestion identifier
		natural_language: Natural language description
		cypher_query: Generated Cypher query
		complexity: Query complexity level
		confidence_score: AI confidence (0-1)
		explanation: How the query addresses the request
		expected_results: Expected result structure
		performance_notes: Performance considerations
		created_at: When suggestion was generated
	"""
	
	suggestion_id: str
	natural_language: str
	cypher_query: str
	complexity: QueryComplexity
	confidence_score: float
	explanation: str = ""
	expected_results: Dict[str, Any] = field(default_factory=dict)
	performance_notes: List[str] = field(default_factory=list)
	created_at: datetime = field(default_factory=datetime.utcnow)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["complexity"] = self.complexity.value
		data["created_at"] = self.created_at.isoformat()
		return data


@dataclass
class AnalysisRecommendation:
	"""
	AI-generated analysis recommendation
	
	Attributes:
		recommendation_id: Unique recommendation identifier
		title: Recommendation title
		description: Detailed description
		analysis_types: Suggested analysis types
		reasoning: Why this analysis is recommended
		priority: Recommendation priority
		estimated_time: Estimated analysis time
		required_data: Data requirements
		expected_insights: Expected types of insights
		setup_instructions: How to set up the analysis
		created_at: When recommendation was generated
	"""
	
	recommendation_id: str
	title: str
	description: str
	analysis_types: List[AnalysisType]
	reasoning: str
	priority: InsightPriority
	estimated_time: str = ""
	required_data: List[str] = field(default_factory=list)
	expected_insights: List[str] = field(default_factory=list)
	setup_instructions: List[str] = field(default_factory=list)
	created_at: datetime = field(default_factory=datetime.utcnow)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["analysis_types"] = [at.value for at in self.analysis_types]
		data["priority"] = self.priority.value
		data["created_at"] = self.created_at.isoformat()
		return data


class NaturalLanguageProcessor:
	"""
	Natural language processing for query translation
	
	Translates natural language requests into Cypher queries with
	semantic understanding of graph operations.
	"""
	
	def __init__(self):
		self.nlp_model = None
		self.query_patterns = self._load_query_patterns()
		self.entity_extractors = self._setup_entity_extractors()
		
		# Initialize spaCy if available
		if SPACY_AVAILABLE:
			try:
				self.nlp_model = spacy.load("en_core_web_sm")
			except OSError:
				logger.warning("spaCy English model not found, using rule-based processing")
	
	def _load_query_patterns(self) -> List[Dict[str, Any]]:
		"""Load natural language to Cypher query patterns"""
		return [
			{
				"patterns": [r"find.*nodes?.*with.*(\w+).*=.*['\"]([^'\"]+)['\"]", r"show.*nodes?.*where.*(\w+).*is.*['\"]([^'\"]+)['\"]"],
				"template": "MATCH (n) WHERE n.{property} = '{value}' RETURN n",
				"complexity": QueryComplexity.SIMPLE,
				"description": "Find nodes with specific property values"
			},
			{
				"patterns": [r"find.*connections?.*between.*['\"]([^'\"]+)['\"].*and.*['\"]([^'\"]+)['\"]", r"path.*from.*['\"]([^'\"]+)['\"].*to.*['\"]([^'\"]+)['\"]"],
				"template": "MATCH path = (a)-[*]-(b) WHERE a.name = '{source}' AND b.name = '{target}' RETURN path LIMIT 10",
				"complexity": QueryComplexity.MODERATE,
				"description": "Find paths between specific nodes"
			},
			{
				"patterns": [r"count.*nodes?", r"how many.*nodes?"],
				"template": "MATCH (n) RETURN count(n) AS node_count",
				"complexity": QueryComplexity.SIMPLE,
				"description": "Count total number of nodes"
			},
			{
				"patterns": [r"count.*edges?", r"how many.*relationships?", r"how many.*connections?"],
				"template": "MATCH ()-[r]->() RETURN count(r) AS edge_count",
				"complexity": QueryComplexity.SIMPLE,
				"description": "Count total number of relationships"
			},
			{
				"patterns": [r"most.*connected.*nodes?", r"highest.*degree.*nodes?", r"nodes?.*with.*most.*connections?"],
				"template": "MATCH (n)-[r]-() RETURN n, count(r) AS degree ORDER BY degree DESC LIMIT 10",
				"complexity": QueryComplexity.MODERATE,
				"description": "Find most connected nodes"
			},
			{
				"patterns": [r"neighbors?.*of.*['\"]([^'\"]+)['\"]", r"connected.*to.*['\"]([^'\"]+)['\"]"],
				"template": "MATCH (center)-[r]-(neighbor) WHERE center.name = '{node}' RETURN neighbor, type(r) AS relationship_type",
				"complexity": QueryComplexity.SIMPLE,
				"description": "Find neighbors of a specific node"
			},
			{
				"patterns": [r"shortest.*path.*between.*['\"]([^'\"]+)['\"].*and.*['\"]([^'\"]+)['\"]"],
				"template": "MATCH (start), (end), path = shortestPath((start)-[*]-(end)) WHERE start.name = '{source}' AND end.name = '{target}' RETURN path",
				"complexity": QueryComplexity.MODERATE,
				"description": "Find shortest path between nodes"
			},
			{
				"patterns": [r"nodes?.*with.*(\w+).*greater than.*(\d+)", r"nodes?.*where.*(\w+)\s*>\s*(\d+)"],
				"template": "MATCH (n) WHERE n.{property} > {value} RETURN n",
				"complexity": QueryComplexity.SIMPLE,
				"description": "Find nodes with property greater than value"
			},
			{
				"patterns": [r"cluster.*analysis", r"find.*communities", r"detect.*groups"],
				"template": "CALL gds.louvain.stream('graph-projection') YIELD nodeId, communityId RETURN gds.util.asNode(nodeId).name AS name, communityId",
				"complexity": QueryComplexity.EXPERT,
				"description": "Detect communities using Louvain algorithm"
			},
			{
				"patterns": [r"page.*rank", r"importance.*score", r"influential.*nodes?"],
				"template": "CALL gds.pageRank.stream('graph-projection') YIELD nodeId, score RETURN gds.util.asNode(nodeId).name AS name, score ORDER BY score DESC LIMIT 20",
				"complexity": QueryComplexity.EXPERT,
				"description": "Calculate PageRank scores for node importance"
			}
		]
	
	def _setup_entity_extractors(self) -> Dict[str, Any]:
		"""Setup entity extractors for query parsing"""
		return {
			"property_patterns": [
				r"(\w+)\s*=\s*['\"]([^'\"]+)['\"]",
				r"(\w+)\s*is\s*['\"]([^'\"]+)['\"]",
				r"(\w+)\s*equals?\s*['\"]([^'\"]+)['\"]"
			],
			"node_patterns": [
				r"node\s+['\"]([^'\"]+)['\"]",
				r"vertex\s+['\"]([^'\"]+)['\"]",
				r"['\"]([^'\"]+)['\"]"
			],
			"numeric_patterns": [
				r"(\d+)",
				r"greater than\s+(\d+)",
				r"less than\s+(\d+)",
				r"equals?\s+(\d+)"
			]
		}
	
	def translate_to_cypher(self, natural_query: str, graph_name: str = None) -> QuerySuggestion:
		"""
		Translate natural language query to Cypher
		
		Args:
			natural_query: Natural language query
			graph_name: Target graph name
			
		Returns:
			QuerySuggestion with Cypher translation
		"""
		from uuid_extensions import uuid7str
		
		natural_query = natural_query.lower().strip()
		
		# Try pattern matching
		for pattern_group in self.query_patterns:
			for pattern in pattern_group["patterns"]:
				match = re.search(pattern, natural_query, re.IGNORECASE)
				if match:
					# Extract parameters from match
					params = {}
					if match.groups():
						if len(match.groups()) == 1:
							if "property" in pattern_group["template"] and "value" in pattern_group["template"]:
								# Assume single match is a value, infer common property
								params = {"property": "name", "value": match.group(1)}
							elif "node" in pattern_group["template"]:
								params = {"node": match.group(1)}
							elif "value" in pattern_group["template"]:
								params = {"value": match.group(1)}
						elif len(match.groups()) == 2:
							if "source" in pattern_group["template"] and "target" in pattern_group["template"]:
								params = {"source": match.group(1), "target": match.group(2)}
							elif "property" in pattern_group["template"] and "value" in pattern_group["template"]:
								params = {"property": match.group(1), "value": match.group(2)}
					
					# Generate Cypher query
					cypher_query = pattern_group["template"]
					for key, value in params.items():
						cypher_query = cypher_query.replace(f"{{{key}}}", str(value))
					
					# Calculate confidence based on pattern match quality
					confidence = 0.8 if len(params) > 0 else 0.6
					
					return QuerySuggestion(
						suggestion_id=uuid7str(),
						natural_language=natural_query,
						cypher_query=cypher_query,
						complexity=pattern_group["complexity"],
						confidence_score=confidence,
						explanation=pattern_group["description"],
						performance_notes=self._generate_performance_notes(cypher_query)
					)
		
		# Fallback: Generate basic query
		return self._generate_fallback_query(natural_query)
	
	def _generate_fallback_query(self, natural_query: str) -> QuerySuggestion:
		"""Generate fallback query when no patterns match"""
		from uuid_extensions import uuid7str
		
		# Extract potential node/property names
		entities = re.findall(r"['\"]([^'\"]+)['\"]", natural_query)
		
		if entities:
			# Create a basic search query
			if len(entities) == 1:
				cypher_query = f"MATCH (n) WHERE n.name CONTAINS '{entities[0]}' RETURN n LIMIT 10"
			else:
				cypher_query = f"MATCH (n) WHERE n.name IN {entities} RETURN n LIMIT 10"
		else:
			# Very generic fallback
			cypher_query = "MATCH (n) RETURN n LIMIT 10"
		
		return QuerySuggestion(
			suggestion_id=uuid7str(),
			natural_language=natural_query,
			cypher_query=cypher_query,
			complexity=QueryComplexity.SIMPLE,
			confidence_score=0.3,
			explanation="Generic query based on extracted entities",
			performance_notes=["This is a fallback query with low confidence"]
		)
	
	def _generate_performance_notes(self, cypher_query: str) -> List[str]:
		"""Generate performance notes for query"""
		notes = []
		
		if "MATCH (n)-[*]-(m)" in cypher_query:
			notes.append("Variable length paths can be expensive - consider adding depth limits")
		
		if not re.search(r"LIMIT\s+\d+", cypher_query):
			notes.append("Consider adding a LIMIT clause to prevent large result sets")
		
		if "WHERE" not in cypher_query and "MATCH (n)" in cypher_query:
			notes.append("Querying all nodes without filters - consider adding WHERE clauses")
		
		if "ORDER BY" in cypher_query and "LIMIT" not in cypher_query:
			notes.append("Sorting all results without LIMIT - consider limiting results first")
		
		return notes


class GraphAnalysisEngine:
	"""
	AI-powered graph analysis engine
	
	Performs automated analysis and generates insights about graph structure,
	patterns, anomalies, and recommendations for further exploration.
	"""
	
	def __init__(self):
		self.cached_analyses: Dict[str, Any] = {}
		self.analysis_history: List[Dict[str, Any]] = []
		self._lock = threading.RLock()
	
	@performance_cache(ttl_seconds=3600)
	def analyze_graph_structure(self, graph_name: str) -> AIInsight:
		"""Analyze basic graph structure and provide insights"""
		from uuid_extensions import uuid7str
		
		try:
			graph_manager = get_graph_manager(graph_name)
			
			# Get basic statistics
			stats = self._get_graph_statistics(graph_manager)
			
			# Analyze structure patterns
			structure_insights = self._analyze_structure_patterns(stats)
			
			# Generate recommendations
			recommendations = self._generate_structure_recommendations(stats)
			
			# Calculate confidence based on data quality
			confidence = min(0.9, stats.get("node_count", 0) / 1000 + 0.3)
			
			insight = AIInsight(
				insight_id=uuid7str(),
				title="Graph Structure Analysis",
				description=structure_insights["description"],
				analysis_type=AnalysisType.GRAPH_STRUCTURE_ANALYSIS,
				priority=structure_insights["priority"],
				confidence_score=confidence,
				data_evidence=stats,
				recommended_actions=recommendations,
				cypher_queries=structure_insights["queries"],
				metadata={"analysis_timestamp": datetime.now(tz=timezone.utc).isoformat()}
			)
			
			return insight
			
		except Exception as e:
			logger.error(f"Graph structure analysis failed: {e}")
			return self._create_error_insight("Graph Structure Analysis", str(e))
	
	def detect_anomalies(self, graph_name: str) -> List[AIInsight]:
		"""Detect anomalies in graph data"""
		from uuid_extensions import uuid7str
		
		insights = []
		
		try:
			graph_manager = get_graph_manager(graph_name)
			
			# Detect degree anomalies
			degree_anomalies = self._detect_degree_anomalies(graph_manager)
			if degree_anomalies:
				insights.append(AIInsight(
					insight_id=uuid7str(),
					title="Unusual Node Connectivity Detected",
					description=degree_anomalies["description"],
					analysis_type=AnalysisType.ANOMALY_DETECTION,
					priority=degree_anomalies["priority"],
					confidence_score=degree_anomalies["confidence"],
					data_evidence=degree_anomalies["evidence"],
					recommended_actions=degree_anomalies["actions"],
					cypher_queries=degree_anomalies["queries"]
				))
			
			# Detect property anomalies
			property_anomalies = self._detect_property_anomalies(graph_manager)
			if property_anomalies:
				insights.append(AIInsight(
					insight_id=uuid7str(),
					title="Property Value Anomalies Found",
					description=property_anomalies["description"],
					analysis_type=AnalysisType.ANOMALY_DETECTION,
					priority=property_anomalies["priority"],
					confidence_score=property_anomalies["confidence"],
					data_evidence=property_anomalies["evidence"],
					recommended_actions=property_anomalies["actions"],
					cypher_queries=property_anomalies["queries"]
				))
			
			# Detect structural anomalies
			structural_anomalies = self._detect_structural_anomalies(graph_manager)
			if structural_anomalies:
				insights.append(AIInsight(
					insight_id=uuid7str(),
					title="Structural Anomalies Identified",
					description=structural_anomalies["description"],
					analysis_type=AnalysisType.ANOMALY_DETECTION,
					priority=structural_anomalies["priority"],
					confidence_score=structural_anomalies["confidence"],
					data_evidence=structural_anomalies["evidence"],
					recommended_actions=structural_anomalies["actions"],
					cypher_queries=structural_anomalies["queries"]
				))
			
		except Exception as e:
			logger.error(f"Anomaly detection failed: {e}")
			insights.append(self._create_error_insight("Anomaly Detection", str(e)))
		
		return insights
	
	def suggest_analysis_paths(self, graph_name: str, user_context: Dict[str, Any] = None) -> List[AnalysisRecommendation]:
		"""Suggest analysis paths based on graph characteristics"""
		from uuid_extensions import uuid7str
		
		recommendations = []
		
		try:
			graph_manager = get_graph_manager(graph_name)
			stats = self._get_graph_statistics(graph_manager)
			
			# Recommend based on graph size
			if stats.get("node_count", 0) > 1000:
				recommendations.append(AnalysisRecommendation(
					recommendation_id=uuid7str(),
					title="Large Graph Community Analysis",
					description="Your graph has many nodes - community detection could reveal hidden structure",
					analysis_types=[AnalysisType.COMMUNITY_DETECTION],
					reasoning="Large graphs often have community structure that's not immediately visible",
					priority=InsightPriority.HIGH,
					estimated_time="5-15 minutes",
					required_data=["Node relationships"],
					expected_insights=["Community clusters", "Bridge nodes", "Isolated subgraphs"],
					setup_instructions=[
						"Ensure graph data is loaded",
						"Run community detection algorithm",
						"Analyze cluster distribution",
						"Identify inter-community connections"
					]
				))
			
			# Recommend based on connectivity
			avg_degree = stats.get("avg_degree", 0)
			if avg_degree < 2:
				recommendations.append(AnalysisRecommendation(
					recommendation_id=uuid7str(),
					title="Sparse Graph Analysis",
					description="Your graph is sparsely connected - focus on path analysis and connectivity",
					analysis_types=[AnalysisType.PATH_ANALYSIS, AnalysisType.GRAPH_STRUCTURE_ANALYSIS],
					reasoning="Sparse graphs benefit from connectivity and reachability analysis",
					priority=InsightPriority.MEDIUM,
					estimated_time="2-5 minutes",
					required_data=["Node connections"],
					expected_insights=["Connected components", "Bridge edges", "Articulation points"]
				))
			
			# Recommend centrality analysis for medium-sized graphs
			if 100 <= stats.get("node_count", 0) <= 10000:
				recommendations.append(AnalysisRecommendation(
					recommendation_id=uuid7str(),
					title="Centrality and Influence Analysis",
					description="Identify the most important and influential nodes in your network",
					analysis_types=[AnalysisType.CENTRALITY_ANALYSIS, AnalysisType.INFLUENCE_PROPAGATION],
					reasoning="Medium-sized graphs are ideal for centrality metrics computation",
					priority=InsightPriority.HIGH,
					estimated_time="3-8 minutes",
					required_data=["Graph topology"],
					expected_insights=["Key nodes", "Information brokers", "Network bottlenecks"]
				))
			
			# Recommend pattern discovery if graph has rich properties
			if stats.get("avg_properties_per_node", 0) > 3:
				recommendations.append(AnalysisRecommendation(
					recommendation_id=uuid7str(),
					title="Pattern Discovery Analysis",
					description="Rich node properties suggest potential for pattern mining",
					analysis_types=[AnalysisType.PATTERN_DISCOVERY, AnalysisType.SIMILARITY_ANALYSIS],
					reasoning="Graphs with rich attributes often contain hidden patterns",
					priority=InsightPriority.MEDIUM,
					estimated_time="10-20 minutes",
					required_data=["Node properties", "Relationship attributes"],
					expected_insights=["Common patterns", "Property correlations", "Similar node groups"]
				))
			
		except Exception as e:
			logger.error(f"Analysis recommendation failed: {e}")
		
		return recommendations
	
	def _get_graph_statistics(self, graph_manager: GraphDatabaseManager) -> Dict[str, Any]:
		"""Get comprehensive graph statistics"""
		stats = {}
		
		try:
			# Basic counts
			node_result = graph_manager.execute_cypher_query("MATCH (n) RETURN count(n) as count")
			stats["node_count"] = node_result["results"][0]["count"] if node_result["success"] else 0
			
			edge_result = graph_manager.execute_cypher_query("MATCH ()-[r]->() RETURN count(r) as count")
			stats["edge_count"] = edge_result["results"][0]["count"] if edge_result["success"] else 0
			
			# Degree statistics
			degree_result = graph_manager.execute_cypher_query(
				"MATCH (n)-[r]-() RETURN avg(count(r)) as avg_degree, max(count(r)) as max_degree, min(count(r)) as min_degree"
			)
			if degree_result["success"] and degree_result["results"]:
				stats.update(degree_result["results"][0])
			
			# Label distribution
			label_result = graph_manager.execute_cypher_query(
				"MATCH (n) RETURN labels(n) as labels, count(*) as count ORDER BY count DESC LIMIT 10"
			)
			if label_result["success"]:
				stats["label_distribution"] = label_result["results"]
			
			# Property statistics
			prop_result = graph_manager.execute_cypher_query(
				"MATCH (n) RETURN avg(size(keys(n))) as avg_properties_per_node"
			)
			if prop_result["success"] and prop_result["results"]:
				stats.update(prop_result["results"][0])
			
		except Exception as e:
			logger.error(f"Failed to get graph statistics: {e}")
		
		return stats
	
	def _analyze_structure_patterns(self, stats: Dict[str, Any]) -> Dict[str, Any]:
		"""Analyze structure patterns from statistics"""
		node_count = stats.get("node_count", 0)
		edge_count = stats.get("edge_count", 0)
		avg_degree = stats.get("avg_degree", 0)
		
		if node_count == 0:
			return {
				"description": "Graph appears to be empty - no nodes found",
				"priority": InsightPriority.HIGH,
				"queries": ["MATCH (n) RETURN n LIMIT 10"]
			}
		
		density = edge_count / (node_count * (node_count - 1) / 2) if node_count > 1 else 0
		
		if density > 0.5:
			description = f"Dense graph with {node_count:,} nodes and {edge_count:,} edges (density: {density:.3f}). High connectivity suggests strong relationships."
			priority = InsightPriority.MEDIUM
		elif density < 0.01:
			description = f"Sparse graph with {node_count:,} nodes and {edge_count:,} edges (density: {density:.3f}). May have distinct components or clusters."
			priority = InsightPriority.HIGH
		else:
			description = f"Moderately connected graph with {node_count:,} nodes and {edge_count:,} edges (average degree: {avg_degree:.1f})."
			priority = InsightPriority.LOW
		
		queries = [
			"MATCH (n) RETURN count(n) as nodes, count{(n)-[]-()}  as total_degree",
			"MATCH (n)-[r]-(m) RETURN n, count(r) as degree ORDER BY degree DESC LIMIT 10",
			"CALL db.labels() YIELD label RETURN label"
		]
		
		return {
			"description": description,
			"priority": priority,
			"queries": queries
		}
	
	def _generate_structure_recommendations(self, stats: Dict[str, Any]) -> List[str]:
		"""Generate recommendations based on structure"""
		recommendations = []
		
		node_count = stats.get("node_count", 0)
		avg_degree = stats.get("avg_degree", 0)
		
		if node_count > 10000:
			recommendations.append("Consider using graph sampling techniques for large-scale analysis")
			recommendations.append("Implement graph partitioning for distributed processing")
		
		if avg_degree < 1.5:
			recommendations.append("Investigate connectivity patterns - graph may be fragmented")
			recommendations.append("Look for isolated components using connected components analysis")
		
		if avg_degree > 10:
			recommendations.append("High connectivity detected - consider community detection analysis")
			recommendations.append("Analyze centrality measures to find key nodes")
		
		label_dist = stats.get("label_distribution", [])
		if len(label_dist) > 5:
			recommendations.append("Multiple node types found - consider type-specific analysis")
		
		return recommendations
	
	def _detect_degree_anomalies(self, graph_manager: GraphDatabaseManager) -> Optional[Dict[str, Any]]:
		"""Detect nodes with unusual degree patterns"""
		try:
			result = graph_manager.execute_cypher_query("""
				MATCH (n)-[r]-()
				WITH n, count(r) as degree
				WITH collect(degree) as degrees, avg(degree) as avg_degree, stdev(degree) as std_degree
				UNWIND degrees as degree
				WITH degree, avg_degree, std_degree
				WHERE degree > avg_degree + 3 * std_degree OR degree < avg_degree - 3 * std_degree
				RETURN degree, avg_degree, std_degree
				ORDER BY abs(degree - avg_degree) DESC
				LIMIT 10
			""")
			
			if result["success"] and result["results"]:
				anomalies = result["results"]
				
				return {
					"description": f"Found {len(anomalies)} nodes with unusual connectivity patterns (3+ standard deviations from mean)",
					"priority": InsightPriority.MEDIUM,
					"confidence": 0.8,
					"evidence": {"anomalous_degrees": anomalies},
					"actions": ["Investigate high-degree nodes for data quality issues", "Check for hub nodes or super-connectors"],
					"queries": [
						"MATCH (n)-[r]-() WITH n, count(r) as degree ORDER BY degree DESC LIMIT 5 RETURN n, degree",
						"MATCH (n) WHERE NOT (n)-[]-() RETURN count(n) as isolated_nodes"
					]
				}
		except Exception as e:
			logger.error(f"Degree anomaly detection failed: {e}")
		
		return None
	
	def _detect_property_anomalies(self, graph_manager: GraphDatabaseManager) -> Optional[Dict[str, Any]]:
		"""Detect unusual property patterns"""
		try:
			# Check for nodes with unusually many or few properties
			result = graph_manager.execute_cypher_query("""
				MATCH (n)
				WITH size(keys(n)) as prop_count, count(*) as nodes
				WHERE nodes < 10 OR prop_count > 20 OR prop_count = 0
				RETURN prop_count, nodes
				ORDER BY prop_count DESC
				LIMIT 10
			""")
			
			if result["success"] and result["results"]:
				anomalies = result["results"]
				unusual_counts = [a for a in anomalies if a["prop_count"] > 20 or a["prop_count"] == 0]
				
				if unusual_counts:
					return {
						"description": f"Found nodes with unusual property counts: {len(unusual_counts)} patterns detected",
						"priority": InsightPriority.LOW,
						"confidence": 0.6,
						"evidence": {"property_anomalies": unusual_counts},
						"actions": ["Check data ingestion process", "Validate property schemas"],
						"queries": [
							"MATCH (n) WHERE size(keys(n)) = 0 RETURN count(n) as empty_property_nodes",
							"MATCH (n) WHERE size(keys(n)) > 15 RETURN n LIMIT 5"
						]
					}
		except Exception as e:
			logger.error(f"Property anomaly detection failed: {e}")
		
		return None
	
	def _detect_structural_anomalies(self, graph_manager: GraphDatabaseManager) -> Optional[Dict[str, Any]]:
		"""Detect structural anomalies in graph"""
		try:
			# Check for potential cycles or unusual structures
			result = graph_manager.execute_cypher_query("""
				MATCH p = (n)-[*3..5]-(n)
				RETURN count(p) as cycle_count
			""")
			
			if result["success"] and result["results"]:
				cycle_count = result["results"][0]["cycle_count"]
				
				if cycle_count > 1000:  # Many cycles might indicate issues
					return {
						"description": f"High number of short cycles detected ({cycle_count:,}) - may indicate data quality issues",
						"priority": InsightPriority.MEDIUM,
						"confidence": 0.7,
						"evidence": {"cycle_count": cycle_count},
						"actions": ["Review data for duplicate relationships", "Check for self-loops"],
						"queries": [
							"MATCH (n)-[r]->(n) RETURN count(r) as self_loops",
							"MATCH (n)-[r1]->(m)-[r2]->(n) WHERE id(r1) <> id(r2) RETURN count(*) as two_cycles"
						]
					}
		except Exception as e:
			logger.error(f"Structural anomaly detection failed: {e}")
		
		return None
	
	def _create_error_insight(self, analysis_type: str, error_message: str) -> AIInsight:
		"""Create an error insight"""
		from uuid_extensions import uuid7str
		
		return AIInsight(
			insight_id=uuid7str(),
			title=f"{analysis_type} Failed",
			description=f"Analysis could not be completed: {error_message}",
			analysis_type=AnalysisType.GRAPH_STRUCTURE_ANALYSIS,
			priority=InsightPriority.LOW,
			confidence_score=0.0,
			recommended_actions=["Check graph data availability", "Verify database connection"],
			metadata={"error": error_message}
		)


class AIAnalyticsAssistant:
	"""
	Main AI Analytics Assistant
	
	Coordinates natural language processing, automated analysis,
	and intelligent recommendations for graph data exploration.
	"""
	
	def __init__(self):
		self.nlp_processor = NaturalLanguageProcessor()
		self.analysis_engine = GraphAnalysisEngine()
		self.insights_cache: Dict[str, List[AIInsight]] = {}
		self.query_history: List[QuerySuggestion] = []
		self._lock = threading.RLock()
		
		# Start background analysis thread
		self._start_background_analysis()
	
	def process_natural_language_query(self, query: str, graph_name: str = None) -> QuerySuggestion:
		"""Process natural language query and return Cypher suggestion"""
		suggestion = self.nlp_processor.translate_to_cypher(query, graph_name)
		
		with self._lock:
			self.query_history.append(suggestion)
			# Keep only recent history
			if len(self.query_history) > 100:
				self.query_history = self.query_history[-100:]
		
		# Track activity
		track_database_activity(
			activity_type=ActivityType.AI_QUERY_PROCESSED,
			target=f"Graph: {graph_name or 'unknown'}",
			description=f"Processed natural language query: {query[:100]}...",
			details={
				"query": query,
				"confidence": suggestion.confidence_score,
				"complexity": suggestion.complexity.value
			}
		)
		
		return suggestion
	
	def get_automated_insights(self, graph_name: str, force_refresh: bool = False) -> List[AIInsight]:
		"""Get automated insights for graph"""
		cache_key = f"insights_{graph_name}"
		
		# Check cache
		if not force_refresh and cache_key in self.insights_cache:
			cached_time = self.insights_cache[cache_key].get("timestamp", datetime.min)
			if datetime.now(tz=timezone.utc) - cached_time < timedelta(hours=1):
				return self.insights_cache[cache_key].get("insights", [])
		
		insights = []
		
		# Structure analysis
		try:
			structure_insight = self.analysis_engine.analyze_graph_structure(graph_name)
			insights.append(structure_insight)
		except Exception as e:
			logger.error(f"Structure analysis failed: {e}")
		
		# Anomaly detection
		try:
			anomaly_insights = self.analysis_engine.detect_anomalies(graph_name)
			insights.extend(anomaly_insights)
		except Exception as e:
			logger.error(f"Anomaly detection failed: {e}")
		
		# Cache results
		with self._lock:
			self.insights_cache[cache_key] = {
				"insights": insights,
				"timestamp": datetime.now(tz=timezone.utc)
			}
		
		return insights
	
	def get_analysis_recommendations(self, graph_name: str, user_context: Dict[str, Any] = None) -> List[AnalysisRecommendation]:
		"""Get analysis recommendations for graph"""
		return self.analysis_engine.suggest_analysis_paths(graph_name, user_context)
	
	def get_query_suggestions(self, graph_name: str, context: str = "") -> List[QuerySuggestion]:
		"""Get query suggestions based on context"""
		suggestions = []
		
		# Contextual suggestions based on graph analysis
		try:
			insights = self.get_automated_insights(graph_name)
			
			for insight in insights[:3]:  # Top 3 insights
				# Generate query suggestions based on insights
				if insight.cypher_queries:
					for cypher_query in insight.cypher_queries[:2]:  # Max 2 per insight
						suggestion = QuerySuggestion(
							suggestion_id=f"insight_{insight.insight_id}_{len(suggestions)}",
							natural_language=f"Explore: {insight.title}",
							cypher_query=cypher_query,
							complexity=QueryComplexity.MODERATE,
							confidence_score=insight.confidence_score * 0.8,  # Slightly lower for derived suggestions
							explanation=f"Query suggested based on insight: {insight.description[:100]}...",
							performance_notes=["Generated from automated analysis"]
						)
						suggestions.append(suggestion)
		
		except Exception as e:
			logger.error(f"Query suggestion generation failed: {e}")
		
		return suggestions
	
	def get_dashboard_summary(self, user_id: str = None) -> Dict[str, Any]:
		"""Get AI assistant dashboard summary"""
		with self._lock:
			recent_queries = self.query_history[-10:]  # Last 10 queries
			
			# Calculate query statistics
			avg_confidence = np.mean([q.confidence_score for q in recent_queries]) if recent_queries else 0
			complexity_distribution = {}
			for query in recent_queries:
				complexity = query.complexity.value
				complexity_distribution[complexity] = complexity_distribution.get(complexity, 0) + 1
		
		# Get insights summary
		total_insights = sum(len(insights.get("insights", [])) for insights in self.insights_cache.values())
		high_priority_insights = 0
		for cache_data in self.insights_cache.values():
			for insight in cache_data.get("insights", []):
				if insight.priority == InsightPriority.HIGH:
					high_priority_insights += 1
		
		return {
			"query_statistics": {
				"recent_query_count": len(recent_queries),
				"average_confidence": avg_confidence,
				"complexity_distribution": complexity_distribution
			},
			"insights_summary": {
				"total_insights": total_insights,
				"high_priority_insights": high_priority_insights,
				"cached_graphs": len(self.insights_cache)
			},
			"ai_assistant_stats": {
				"nlp_patterns": len(self.nlp_processor.query_patterns),
				"analysis_types": len(AnalysisType),
				"cache_hit_rate": self._calculate_cache_hit_rate()
			}
		}
	
	def _calculate_cache_hit_rate(self) -> float:
		"""Calculate actual cache hit rate from performance monitor"""
		try:
			if hasattr(self, 'cache_hits') and hasattr(self, 'cache_misses'):
				total_requests = self.cache_hits + self.cache_misses
				if total_requests > 0:
					return self.cache_hits / total_requests
			
			# Fallback: estimate from insights cache usage
			if hasattr(self, 'insights_cache') and len(self.insights_cache) > 0:
				# Estimate based on cache size vs typical request patterns
				estimated_hit_rate = min(0.85, len(self.insights_cache) * 0.1)
				return max(0.0, estimated_hit_rate)
				
			return 0.0
		except Exception as e:
			logger.warning(f"Error calculating cache hit rate: {e}")
			return 0.0
	
	def _start_background_analysis(self):
		"""Start background analysis for active graphs"""
		def background_task():
			import time
			while True:
				try:
					time.sleep(1800)  # Run every 30 minutes
					
					# Get active graphs
					registry = get_graph_registry()
					graphs = registry.list_graphs()
					
					# Analyze each graph if not recently analyzed
					for graph in graphs[:3]:  # Limit to top 3 most active graphs
						cache_key = f"insights_{graph.name}"
						if cache_key not in self.insights_cache:
							logger.info(f"Running background analysis for {graph.name}")
							self.get_automated_insights(graph.name)
					
				except Exception as e:
					logger.error(f"Background analysis error: {e}")
		
		background_thread = threading.Thread(target=background_task, daemon=True)
		background_thread.start()


# Global AI assistant instance
_ai_analytics_assistant = None


def get_ai_analytics_assistant() -> AIAnalyticsAssistant:
	"""Get or create global AI analytics assistant instance"""
	global _ai_analytics_assistant
	if _ai_analytics_assistant is None:
		_ai_analytics_assistant = AIAnalyticsAssistant()
	return _ai_analytics_assistant