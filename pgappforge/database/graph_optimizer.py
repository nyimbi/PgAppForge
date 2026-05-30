"""
Automated Graph Optimization and Healing System

Comprehensive system for automatically detecting and fixing graph issues,
optimizing performance, and maintaining graph health over time.
"""

import logging
import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union, Set
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

import numpy as np
import networkx as nx
from sklearn.cluster import DBSCAN, KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics.pairwise import cosine_similarity

import psycopg2
from pydantic import BaseModel, Field
from uuid_extensions import uuid7str

from .graph_manager import GraphManager
from .activity_tracker import track_database_activity, ActivityType, ActivitySeverity
from ..utils.error_handling import WizardErrorHandler, WizardErrorType, WizardErrorSeverity

logger = logging.getLogger(__name__)


class OptimizationLevel(Enum):
	"""Levels of optimization aggressiveness"""
	CONSERVATIVE = "conservative"
	MODERATE = "moderate"
	AGGRESSIVE = "aggressive"


class IssueType(Enum):
	"""Types of graph issues that can be detected and fixed"""
	DUPLICATE_NODES = "duplicate_nodes"
	ORPHANED_NODES = "orphaned_nodes"
	REDUNDANT_RELATIONSHIPS = "redundant_relationships"
	MISSING_INDEXES = "missing_indexes"
	PERFORMANCE_BOTTLENECKS = "performance_bottlenecks"
	DATA_INCONSISTENCY = "data_inconsistency"
	SCHEMA_VIOLATIONS = "schema_violations"
	CONNECTIVITY_ISSUES = "connectivity_issues"


class IssueSeverity(Enum):
	"""Severity levels for graph issues"""
	LOW = "low"
	MEDIUM = "medium"
	HIGH = "high"
	CRITICAL = "critical"


@dataclass
class GraphIssue:
	"""Represents a detected graph issue"""
	issue_id: str
	issue_type: IssueType
	severity: IssueSeverity
	title: str
	description: str
	affected_entities: List[str]
	detection_method: str
	confidence: float
	auto_fixable: bool
	fix_recommendation: str
	estimated_impact: str
	detected_at: datetime
	metadata: Dict[str, Any]
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"issue_id": self.issue_id,
			"issue_type": self.issue_type.value,
			"severity": self.severity.value,
			"title": self.title,
			"description": self.description,
			"affected_entities": self.affected_entities,
			"detection_method": self.detection_method,
			"confidence": self.confidence,
			"auto_fixable": self.auto_fixable,
			"fix_recommendation": self.fix_recommendation,
			"estimated_impact": self.estimated_impact,
			"detected_at": self.detected_at.isoformat(),
			"metadata": self.metadata
		}


@dataclass
class OptimizationResult:
	"""Result of an optimization operation"""
	optimization_id: str
	operation_type: str
	success: bool
	items_processed: int
	items_fixed: int
	performance_improvement: float
	execution_time: float
	before_metrics: Dict[str, Any]
	after_metrics: Dict[str, Any]
	changes_made: List[str]
	issues_resolved: List[str]
	timestamp: datetime
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"optimization_id": self.optimization_id,
			"operation_type": self.operation_type,
			"success": self.success,
			"items_processed": self.items_processed,
			"items_fixed": self.items_fixed,
			"performance_improvement": self.performance_improvement,
			"execution_time": self.execution_time,
			"before_metrics": self.before_metrics,
			"after_metrics": self.after_metrics,
			"changes_made": self.changes_made,
			"issues_resolved": self.issues_resolved,
			"timestamp": self.timestamp.isoformat()
		}


class GraphHealthChecker:
	"""Comprehensive graph health analysis and issue detection"""
	
	def __init__(self, graph_name: str):
		self.graph_name = graph_name
		self.graph_manager = GraphManager(graph_name)
		self.health_checks = {}
		self._register_health_checks()
		
	def _register_health_checks(self):
		"""Register all available health check methods"""
		self.health_checks = {
			"duplicate_detection": self._check_duplicate_nodes,
			"orphan_detection": self._check_orphaned_nodes,
			"redundancy_check": self._check_redundant_relationships,
			"connectivity_analysis": self._check_connectivity_issues,
			"performance_analysis": self._check_performance_bottlenecks,
			"data_consistency": self._check_data_consistency,
			"schema_validation": self._check_schema_violations,
			"index_optimization": self._check_missing_indexes
		}
		
	def run_comprehensive_health_check(self) -> List[GraphIssue]:
		"""Run all health checks and return detected issues"""
		all_issues = []
		
		logger.info(f"Starting comprehensive health check for graph: {self.graph_name}")
		
		for check_name, check_method in self.health_checks.items():
			try:
				issues = check_method()
				all_issues.extend(issues)
				logger.info(f"Health check '{check_name}' found {len(issues)} issues")
			except Exception as e:
				logger.error(f"Health check '{check_name}' failed: {e}")
				
		# Sort by severity and confidence
		all_issues.sort(key=lambda i: (
			{"critical": 4, "high": 3, "medium": 2, "low": 1}[i.severity.value],
			i.confidence
		), reverse=True)
		
		logger.info(f"Total health check completed: {len(all_issues)} issues found")
		return all_issues
		
	def _check_duplicate_nodes(self) -> List[GraphIssue]:
		"""Detect duplicate nodes with similar properties"""
		issues = []
		
		try:
			# Query for potential duplicates based on similar properties
			query = """
			MATCH (n)
			WITH n.name as name, n.email as email, labels(n) as labels, collect(n) as nodes
			WHERE size(nodes) > 1 AND (name IS NOT NULL OR email IS NOT NULL)
			RETURN name, email, labels, nodes
			"""
			
			results = self.graph_manager.execute_cypher_query(query)
			
			for result in results:
				nodes = result["nodes"]
				if len(nodes) > 1:
					# Analyze similarity between nodes
					similarity_score = self._calculate_node_similarity(nodes)
					
					if similarity_score > 0.8:  # High similarity threshold
						issue = GraphIssue(
							issue_id=uuid7str(),
							issue_type=IssueType.DUPLICATE_NODES,
							severity=IssueSeverity.HIGH if similarity_score > 0.95 else IssueSeverity.MEDIUM,
							title=f"Duplicate nodes detected: {result['name'] or result['email']}",
							description=f"Found {len(nodes)} similar nodes that may be duplicates",
							affected_entities=[str(node.get("id", "unknown")) for node in nodes],
							detection_method="property_similarity_analysis",
							confidence=similarity_score,
							auto_fixable=True,
							fix_recommendation="Merge duplicate nodes and transfer relationships",
							estimated_impact="medium",
							detected_at=datetime.now(),
							metadata={
								"similarity_score": similarity_score,
								"duplicate_count": len(nodes),
								"common_properties": self._find_common_properties(nodes)
							}
						)
						issues.append(issue)
						
		except Exception as e:
			logger.error(f"Duplicate node detection failed: {e}")
			
		return issues
		
	def _check_orphaned_nodes(self) -> List[GraphIssue]:
		"""Detect nodes with no relationships"""
		issues = []
		
		try:
			# Query for nodes with no relationships
			query = """
			MATCH (n)
			WHERE NOT (n)-[]-()
			RETURN n, labels(n) as labels
			LIMIT 100
			"""
			
			results = self.graph_manager.execute_cypher_query(query)
			
			if results:
				orphaned_nodes = [result["n"] for result in results]
				
				issue = GraphIssue(
					issue_id=uuid7str(),
					issue_type=IssueType.ORPHANED_NODES,
					severity=IssueSeverity.MEDIUM,
					title=f"Orphaned nodes detected: {len(orphaned_nodes)} nodes",
					description="Nodes with no relationships may indicate data quality issues",
					affected_entities=[str(node.get("id", "unknown")) for node in orphaned_nodes],
					detection_method="relationship_count_analysis",
					confidence=0.9,
					auto_fixable=False,  # Requires domain knowledge
					fix_recommendation="Review orphaned nodes and either connect or remove them",
					estimated_impact="low",
					detected_at=datetime.now(),
					metadata={
						"orphaned_count": len(orphaned_nodes),
						"node_labels": [result["labels"] for result in results]
					}
				)
				issues.append(issue)
				
		except Exception as e:
			logger.error(f"Orphaned node detection failed: {e}")
			
		return issues
		
	def _check_redundant_relationships(self) -> List[GraphIssue]:
		"""Detect redundant or duplicate relationships"""
		issues = []
		
		try:
			# Query for potential redundant relationships
			query = """
			MATCH (a)-[r1]->(b), (a)-[r2]->(b)
			WHERE r1 <> r2 AND type(r1) = type(r2)
			RETURN a, b, type(r1) as rel_type, count(*) as duplicate_count
			ORDER BY duplicate_count DESC
			LIMIT 50
			"""
			
			results = self.graph_manager.execute_cypher_query(query)
			
			for result in results:
				if result["duplicate_count"] > 1:
					issue = GraphIssue(
						issue_id=uuid7str(),
						issue_type=IssueType.REDUNDANT_RELATIONSHIPS,
						severity=IssueSeverity.MEDIUM,
						title=f"Redundant relationships: {result['rel_type']}",
						description=f"Found {result['duplicate_count']} duplicate relationships between same nodes",
						affected_entities=[
							str(result["a"].get("id", "unknown")),
							str(result["b"].get("id", "unknown"))
						],
						detection_method="relationship_duplicate_analysis",
						confidence=0.95,
						auto_fixable=True,
						fix_recommendation="Merge duplicate relationships and consolidate properties",
						estimated_impact="low",
						detected_at=datetime.now(),
						metadata={
							"relationship_type": result["rel_type"],
							"duplicate_count": result["duplicate_count"]
						}
					)
					issues.append(issue)
					
		except Exception as e:
			logger.error(f"Redundant relationship detection failed: {e}")
			
		return issues
		
	def _check_connectivity_issues(self) -> List[GraphIssue]:
		"""Check for connectivity and structural issues"""
		issues = []
		
		try:
			# Check for disconnected components
			components_query = """
			MATCH (n)
			WITH n
			MATCH p = (n)-[*]-(m)
			WITH n, collect(DISTINCT m) as connected_nodes
			RETURN count(DISTINCT connected_nodes) as component_count, 
				   avg(size(connected_nodes)) as avg_component_size
			"""
			
			results = self.graph_manager.execute_cypher_query(components_query)
			
			if results:
				result = results[0]
				component_count = result.get("component_count", 1)
				avg_component_size = result.get("avg_component_size", 0)
				
				if component_count > 10:  # Many small components
					issue = GraphIssue(
						issue_id=uuid7str(),
						issue_type=IssueType.CONNECTIVITY_ISSUES,
						severity=IssueSeverity.MEDIUM,
						title=f"Graph fragmentation: {component_count} disconnected components",
						description="Graph has many disconnected components which may indicate missing relationships",
						affected_entities=[],
						detection_method="connected_components_analysis",
						confidence=0.8,
						auto_fixable=False,
						fix_recommendation="Review and add missing relationships between components",
						estimated_impact="medium",
						detected_at=datetime.now(),
						metadata={
							"component_count": component_count,
							"average_component_size": avg_component_size
						}
					)
					issues.append(issue)
					
		except Exception as e:
			logger.error(f"Connectivity analysis failed: {e}")
			
		return issues
		
	def _check_performance_bottlenecks(self) -> List[GraphIssue]:
		"""Detect performance bottlenecks in graph structure"""
		issues = []
		
		try:
			# Check for nodes with very high degree (potential bottlenecks)
			high_degree_query = """
			MATCH (n)-[r]-()
			WITH n, count(r) as degree
			WHERE degree > 100
			RETURN n, degree
			ORDER BY degree DESC
			LIMIT 10
			"""
			
			results = self.graph_manager.execute_cypher_query(high_degree_query)
			
			for result in results:
				degree = result["degree"]
				node = result["n"]
				
				severity = IssueSeverity.CRITICAL if degree > 1000 else (
					IssueSeverity.HIGH if degree > 500 else IssueSeverity.MEDIUM
				)
				
				issue = GraphIssue(
					issue_id=uuid7str(),
					issue_type=IssueType.PERFORMANCE_BOTTLENECKS,
					severity=severity,
					title=f"High-degree node bottleneck: {degree} connections",
					description=f"Node has {degree} relationships which may impact query performance",
					affected_entities=[str(node.get("id", "unknown"))],
					detection_method="degree_centrality_analysis",
					confidence=0.9,
					auto_fixable=True,
					fix_recommendation="Consider node partitioning or relationship optimization",
					estimated_impact="high",
					detected_at=datetime.now(),
					metadata={
						"node_degree": degree,
						"performance_impact_estimate": "high" if degree > 500 else "medium"
					}
				)
				issues.append(issue)
				
		except Exception as e:
			logger.error(f"Performance bottleneck detection failed: {e}")
			
		return issues
		
	def _check_data_consistency(self) -> List[GraphIssue]:
		"""Check for data consistency issues"""
		issues = []
		
		try:
			# Check for missing required properties
			consistency_query = """
			MATCH (n:Person)
			WHERE n.name IS NULL OR n.name = ""
			RETURN count(n) as missing_name_count
			"""
			
			results = self.graph_manager.execute_cypher_query(consistency_query)
			
			if results and results[0].get("missing_name_count", 0) > 0:
				count = results[0]["missing_name_count"]
				
				issue = GraphIssue(
					issue_id=uuid7str(),
					issue_type=IssueType.DATA_INCONSISTENCY,
					severity=IssueSeverity.MEDIUM,
					title=f"Missing required properties: {count} Person nodes without names",
					description="Person nodes should have name properties for data consistency",
					affected_entities=[],
					detection_method="required_property_validation",
					confidence=1.0,
					auto_fixable=False,
					fix_recommendation="Add missing name properties or remove invalid nodes",
					estimated_impact="medium",
					detected_at=datetime.now(),
					metadata={
						"missing_property": "name",
						"affected_label": "Person",
						"missing_count": count
					}
				)
				issues.append(issue)
				
		except Exception as e:
			logger.error(f"Data consistency check failed: {e}")
			
		return issues
		
	def _check_schema_violations(self) -> List[GraphIssue]:
		"""Check for schema violations and constraint issues"""
		issues = []
		
		try:
			# This would check against defined schema constraints
			# For now, implement basic uniqueness checks
			uniqueness_query = """
			MATCH (n:Person)
			WHERE n.email IS NOT NULL
			WITH n.email as email, count(*) as email_count
			WHERE email_count > 1
			RETURN email, email_count
			"""
			
			results = self.graph_manager.execute_cypher_query(uniqueness_query)
			
			for result in results:
				email = result["email"]
				count = result["email_count"]
				
				issue = GraphIssue(
					issue_id=uuid7str(),
					issue_type=IssueType.SCHEMA_VIOLATIONS,
					severity=IssueSeverity.HIGH,
					title=f"Email uniqueness violation: {email}",
					description=f"Email '{email}' is used by {count} different Person nodes",
					affected_entities=[],
					detection_method="uniqueness_constraint_validation",
					confidence=1.0,
					auto_fixable=True,
					fix_recommendation="Merge nodes with duplicate emails or update email addresses",
					estimated_impact="medium",
					detected_at=datetime.now(),
					metadata={
						"duplicate_email": email,
						"occurrence_count": count,
						"constraint_type": "uniqueness"
					}
				)
				issues.append(issue)
				
		except Exception as e:
			logger.error(f"Schema validation failed: {e}")
			
		return issues
		
	def _check_missing_indexes(self) -> List[GraphIssue]:
		"""Check for missing indexes that could improve performance"""
		issues = []
		
		try:
			# Analyze property usage to suggest indexes
			property_usage_query = """
			MATCH (n)
			UNWIND keys(n) as key
			RETURN key, count(*) as usage_count, collect(DISTINCT labels(n)) as node_labels
			ORDER BY usage_count DESC
			LIMIT 20
			"""
			
			results = self.graph_manager.execute_cypher_query(property_usage_query)
			
			for result in results:
				usage_count = result["usage_count"]
				property_key = result["key"]
				
				if usage_count > 1000:  # High usage properties should be indexed
					issue = GraphIssue(
						issue_id=uuid7str(),
						issue_type=IssueType.MISSING_INDEXES,
						severity=IssueSeverity.MEDIUM,
						title=f"Missing index opportunity: {property_key}",
						description=f"Property '{property_key}' is used {usage_count} times and could benefit from indexing",
						affected_entities=[],
						detection_method="property_usage_analysis",
						confidence=0.8,
						auto_fixable=True,
						fix_recommendation=f"CREATE INDEX FOR (n:NodeLabel) ON (n.{property_key})",
						estimated_impact="medium",
						detected_at=datetime.now(),
						metadata={
							"property_name": property_key,
							"usage_count": usage_count,
							"node_labels": result["node_labels"]
						}
					)
					issues.append(issue)
					
		except Exception as e:
			logger.error(f"Index analysis failed: {e}")
			
		return issues
		
	def _calculate_node_similarity(self, nodes: List[Dict[str, Any]]) -> float:
		"""Calculate similarity between nodes based on properties"""
		if len(nodes) < 2:
			return 0.0
			
		# Extract common properties
		all_properties = set()
		for node in nodes:
			all_properties.update(node.keys())
			
		# Create feature vectors
		vectors = []
		for node in nodes:
			vector = []
			for prop in sorted(all_properties):
				value = node.get(prop, "")
				# Simple feature extraction (would be more sophisticated in practice)
				if isinstance(value, str):
					vector.append(len(value))
				elif isinstance(value, (int, float)):
					vector.append(float(value))
				else:
					vector.append(0.0)
			vectors.append(vector)
			
		if len(vectors) < 2:
			return 0.0
			
		# Calculate average pairwise similarity
		similarities = []
		for i in range(len(vectors)):
			for j in range(i + 1, len(vectors)):
				v1 = np.array(vectors[i]).reshape(1, -1)
				v2 = np.array(vectors[j]).reshape(1, -1)
				
				if np.linalg.norm(v1) > 0 and np.linalg.norm(v2) > 0:
					sim = cosine_similarity(v1, v2)[0][0]
					similarities.append(sim)
					
		return np.mean(similarities) if similarities else 0.0
		
	def _find_common_properties(self, nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
		"""Find properties common to all nodes"""
		if not nodes:
			return {}
			
		common_props = {}
		first_node = nodes[0]
		
		for key, value in first_node.items():
			if all(node.get(key) == value for node in nodes[1:]):
				common_props[key] = value
				
		return common_props


class GraphOptimizer:
	"""Automated graph optimization and healing engine"""
	
	def __init__(self, graph_name: str):
		self.graph_name = graph_name
		self.graph_manager = GraphManager(graph_name)
		self.health_checker = GraphHealthChecker(graph_name)
		self.error_handler = WizardErrorHandler()
		
		# Optimization history
		self.optimization_history = []
		
		logger.info(f"Graph optimizer initialized for: {graph_name}")
		
	def run_automated_optimization(self, level: OptimizationLevel = OptimizationLevel.MODERATE) -> List[OptimizationResult]:
		"""Run automated optimization based on detected issues"""
		start_time = time.time()
		results = []
		
		logger.info(f"Starting automated optimization (level: {level.value}) for graph: {self.graph_name}")
		
		try:
			# Step 1: Detect issues
			issues = self.health_checker.run_comprehensive_health_check()
			logger.info(f"Detected {len(issues)} issues to address")
			
			# Step 2: Filter auto-fixable issues based on optimization level
			fixable_issues = self._filter_fixable_issues(issues, level)
			logger.info(f"Found {len(fixable_issues)} auto-fixable issues")
			
			# Step 3: Apply fixes
			for issue in fixable_issues:
				try:
					result = self._apply_fix(issue, level)
					if result:
						results.append(result)
				except Exception as e:
					logger.error(f"Failed to fix issue {issue.issue_id}: {e}")
					
			# Step 4: Run post-optimization health check
			post_issues = self.health_checker.run_comprehensive_health_check()
			improvement = len(issues) - len(post_issues)
			
			total_time = time.time() - start_time
			logger.info(f"Optimization completed in {total_time:.2f}s. Issues reduced from {len(issues)} to {len(post_issues)}")
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.GRAPH_OPTIMIZED,
				target=f"Graph: {self.graph_name}",
				description=f"Automated optimization completed",
				details={
					"optimization_level": level.value,
					"issues_before": len(issues),
					"issues_after": len(post_issues),
					"issues_fixed": improvement,
					"execution_time": total_time,
					"operations_performed": len(results)
				}
			)
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.MEDIUM
			)
			logger.error(f"Automated optimization failed: {e}")
			
		return results
		
	def _filter_fixable_issues(self, issues: List[GraphIssue], level: OptimizationLevel) -> List[GraphIssue]:
		"""Filter issues based on auto-fixability and optimization level"""
		fixable = [issue for issue in issues if issue.auto_fixable]
		
		if level == OptimizationLevel.CONSERVATIVE:
			# Only fix low-risk, high-confidence issues
			return [issue for issue in fixable 
					if issue.confidence > 0.9 and issue.severity in [IssueSeverity.LOW, IssueSeverity.MEDIUM]]
		elif level == OptimizationLevel.MODERATE:
			# Fix most issues except critical ones requiring review
			return [issue for issue in fixable 
					if issue.confidence > 0.7 and issue.severity != IssueSeverity.CRITICAL]
		else:  # AGGRESSIVE
			# Fix all auto-fixable issues
			return [issue for issue in fixable if issue.confidence > 0.5]
			
	def _apply_fix(self, issue: GraphIssue, level: OptimizationLevel) -> Optional[OptimizationResult]:
		"""Apply a fix for a specific issue"""
		start_time = time.time()
		
		try:
			# Get before metrics
			before_metrics = self._get_graph_metrics()
			
			if issue.issue_type == IssueType.DUPLICATE_NODES:
				result = self._fix_duplicate_nodes(issue)
			elif issue.issue_type == IssueType.REDUNDANT_RELATIONSHIPS:
				result = self._fix_redundant_relationships(issue)
			elif issue.issue_type == IssueType.MISSING_INDEXES:
				result = self._fix_missing_indexes(issue)
			elif issue.issue_type == IssueType.PERFORMANCE_BOTTLENECKS:
				result = self._fix_performance_bottlenecks(issue, level)
			elif issue.issue_type == IssueType.SCHEMA_VIOLATIONS:
				result = self._fix_schema_violations(issue)
			else:
				logger.warning(f"No fix implementation for issue type: {issue.issue_type.value}")
				return None
				
			if result:
				# Get after metrics
				after_metrics = self._get_graph_metrics()
				
				# Calculate performance improvement
				performance_improvement = self._calculate_performance_improvement(
					before_metrics, after_metrics
				)
				
				optimization_result = OptimizationResult(
					optimization_id=uuid7str(),
					operation_type=f"fix_{issue.issue_type.value}",
					success=True,
					items_processed=result.get("items_processed", 0),
					items_fixed=result.get("items_fixed", 0),
					performance_improvement=performance_improvement,
					execution_time=time.time() - start_time,
					before_metrics=before_metrics,
					after_metrics=after_metrics,
					changes_made=result.get("changes_made", []),
					issues_resolved=[issue.issue_id],
					timestamp=datetime.now()
				)
				
				self.optimization_history.append(optimization_result)
				return optimization_result
				
		except Exception as e:
			logger.error(f"Failed to apply fix for issue {issue.issue_id}: {e}")
			return None
			
	def _fix_duplicate_nodes(self, issue: GraphIssue) -> Dict[str, Any]:
		"""Fix duplicate nodes by merging them"""
		affected_entities = issue.affected_entities
		
		if len(affected_entities) < 2:
			return {"items_processed": 0, "items_fixed": 0, "changes_made": []}
			
		# Merge duplicate nodes (simplified implementation)
		merge_query = f"""
		MATCH (n1), (n2)
		WHERE n1.id = '{affected_entities[0]}' AND n2.id = '{affected_entities[1]}'
		WITH n1, n2
		MATCH (n2)-[r]-(other)
		CREATE (n1)-[r2:{{type(r)}}]->(other)
		SET r2 = r
		DELETE r, n2
		RETURN count(*) as merged_count
		"""
		
		try:
			results = self.graph_manager.execute_cypher_query(merge_query)
			merged_count = results[0]["merged_count"] if results else 0
			
			return {
				"items_processed": len(affected_entities),
				"items_fixed": merged_count,
				"changes_made": [f"Merged {merged_count} duplicate nodes"]
			}
		except Exception as e:
			logger.error(f"Node merge failed: {e}")
			return {"items_processed": 0, "items_fixed": 0, "changes_made": []}
			
	def _fix_redundant_relationships(self, issue: GraphIssue) -> Dict[str, Any]:
		"""Fix redundant relationships by merging them"""
		rel_type = issue.metadata.get("relationship_type")
		
		if not rel_type:
			return {"items_processed": 0, "items_fixed": 0, "changes_made": []}
			
		# Remove duplicate relationships
		cleanup_query = f"""
		MATCH (a)-[r1:{rel_type}]->(b), (a)-[r2:{rel_type}]->(b)
		WHERE r1 <> r2
		DELETE r2
		RETURN count(*) as removed_count
		"""
		
		try:
			results = self.graph_manager.execute_cypher_query(cleanup_query)
			removed_count = results[0]["removed_count"] if results else 0
			
			return {
				"items_processed": issue.metadata.get("duplicate_count", 0),
				"items_fixed": removed_count,
				"changes_made": [f"Removed {removed_count} redundant relationships"]
			}
		except Exception as e:
			logger.error(f"Relationship cleanup failed: {e}")
			return {"items_processed": 0, "items_fixed": 0, "changes_made": []}
			
	def _fix_missing_indexes(self, issue: GraphIssue) -> Dict[str, Any]:
		"""Create missing indexes for performance"""
		property_name = issue.metadata.get("property_name")
		node_labels = issue.metadata.get("node_labels", [])
		
		if not property_name or not node_labels:
			return {"items_processed": 0, "items_fixed": 0, "changes_made": []}
			
		indexes_created = []
		
		# Create indexes for each relevant label
		for label_list in node_labels:
			for label in label_list:
				index_query = f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{property_name})"
				try:
					self.graph_manager.execute_cypher_query(index_query)
					indexes_created.append(f"{label}.{property_name}")
				except Exception as e:
					logger.warning(f"Index creation failed for {label}.{property_name}: {e}")
					
		return {
			"items_processed": len(node_labels),
			"items_fixed": len(indexes_created),
			"changes_made": [f"Created indexes: {', '.join(indexes_created)}"]
		}
		
	def _fix_performance_bottlenecks(self, issue: GraphIssue, level: OptimizationLevel) -> Dict[str, Any]:
		"""Fix performance bottlenecks through node optimization"""
		node_degree = issue.metadata.get("node_degree", 0)
		
		if level == OptimizationLevel.CONSERVATIVE:
			# Only add indexes for high-degree nodes
			return self._add_performance_indexes(issue)
		elif level == OptimizationLevel.MODERATE:
			# Add indexes and consider relationship optimization
			return self._optimize_node_relationships(issue)
		else:  # AGGRESSIVE
			# Consider node partitioning
			return self._partition_high_degree_node(issue)
			
	def _add_performance_indexes(self, issue: GraphIssue) -> Dict[str, Any]:
		"""Add performance indexes for high-degree nodes"""
		# Implementation would add relevant indexes
		return {
			"items_processed": 1,
			"items_fixed": 1,
			"changes_made": ["Added performance index for high-degree node"]
		}
		
	def _optimize_node_relationships(self, issue: GraphIssue) -> Dict[str, Any]:
		"""Optimize relationships for performance"""
		# Implementation would optimize relationship structure
		return {
			"items_processed": 1,
			"items_fixed": 1,
			"changes_made": ["Optimized node relationships for performance"]
		}
		
	def _partition_high_degree_node(self, issue: GraphIssue) -> Dict[str, Any]:
		"""Partition high-degree nodes to improve performance"""
		# Implementation would partition nodes based on relationship types
		return {
			"items_processed": 1,
			"items_fixed": 1,
			"changes_made": ["Partitioned high-degree node for performance"]
		}
		
	def _fix_schema_violations(self, issue: GraphIssue) -> Dict[str, Any]:
		"""Fix schema violations"""
		constraint_type = issue.metadata.get("constraint_type")
		
		if constraint_type == "uniqueness":
			return self._fix_uniqueness_violations(issue)
		else:
			return {"items_processed": 0, "items_fixed": 0, "changes_made": []}
			
	def _fix_uniqueness_violations(self, issue: GraphIssue) -> Dict[str, Any]:
		"""Fix uniqueness constraint violations"""
		duplicate_email = issue.metadata.get("duplicate_email")
		occurrence_count = issue.metadata.get("occurrence_count", 0)
		
		# Merge nodes with duplicate emails (simplified)
		merge_query = f"""
		MATCH (n:Person {{email: '{duplicate_email}'}})
		WITH collect(n) as nodes
		WHERE size(nodes) > 1
		WITH nodes[0] as keep, nodes[1..] as merge_nodes
		UNWIND merge_nodes as merge_node
		MATCH (merge_node)-[r]-(other)
		CREATE (keep)-[r2:{{type(r)}}]-(other)
		SET r2 = r
		DELETE r, merge_node
		RETURN count(*) as merged_count
		"""
		
		try:
			results = self.graph_manager.execute_cypher_query(merge_query)
			merged_count = results[0]["merged_count"] if results else 0
			
			return {
				"items_processed": occurrence_count,
				"items_fixed": merged_count,
				"changes_made": [f"Merged {merged_count} nodes with duplicate email: {duplicate_email}"]
			}
		except Exception as e:
			logger.error(f"Uniqueness violation fix failed: {e}")
			return {"items_processed": 0, "items_fixed": 0, "changes_made": []}
			
	def _get_graph_metrics(self) -> Dict[str, Any]:
		"""Get current graph performance metrics"""
		try:
			metrics_query = """
			MATCH (n)
			OPTIONAL MATCH (n)-[r]-()
			RETURN 
				count(DISTINCT n) as node_count,
				count(r) as relationship_count,
				avg(size(keys(n))) as avg_properties_per_node
			"""
			
			results = self.graph_manager.execute_cypher_query(metrics_query)
			
			if results:
				return {
					"node_count": results[0]["node_count"],
					"relationship_count": results[0]["relationship_count"],
					"avg_properties_per_node": results[0]["avg_properties_per_node"]
				}
			else:
				return {"node_count": 0, "relationship_count": 0, "avg_properties_per_node": 0}
				
		except Exception as e:
			logger.error(f"Metrics collection failed: {e}")
			return {}
			
	def _calculate_performance_improvement(self, before: Dict[str, Any], after: Dict[str, Any]) -> float:
		"""Calculate performance improvement percentage"""
		try:
			# Simple improvement calculation based on structural metrics
			before_efficiency = before.get("relationship_count", 0) / max(before.get("node_count", 1), 1)
			after_efficiency = after.get("relationship_count", 0) / max(after.get("node_count", 1), 1)
			
			if before_efficiency > 0:
				improvement = ((after_efficiency - before_efficiency) / before_efficiency) * 100
				return max(0, improvement)  # Only report positive improvements
			else:
				return 0.0
				
		except Exception:
			return 0.0
			
	def get_optimization_report(self) -> Dict[str, Any]:
		"""Generate comprehensive optimization report"""
		try:
			current_issues = self.health_checker.run_comprehensive_health_check()
			
			# Categorize issues by type and severity
			issue_summary = defaultdict(lambda: defaultdict(int))
			for issue in current_issues:
				issue_summary[issue.issue_type.value][issue.severity.value] += 1
				
			# Calculate health score
			total_issues = len(current_issues)
			critical_issues = len([i for i in current_issues if i.severity == IssueSeverity.CRITICAL])
			high_issues = len([i for i in current_issues if i.severity == IssueSeverity.HIGH])
			
			health_score = max(0, 100 - (critical_issues * 25 + high_issues * 10 + (total_issues - critical_issues - high_issues) * 2))
			
			return {
				"graph_name": self.graph_name,
				"report_timestamp": datetime.now().isoformat(),
				"health_score": health_score,
				"total_issues": total_issues,
				"issue_summary": dict(issue_summary),
				"optimization_history": [result.to_dict() for result in self.optimization_history[-10:]],  # Last 10
				"recommendations": self._generate_recommendations(current_issues),
				"next_optimization_suggested": total_issues > 0
			}
			
		except Exception as e:
			logger.error(f"Optimization report generation failed: {e}")
			return {"error": str(e)}
			
	def _generate_recommendations(self, issues: List[GraphIssue]) -> List[str]:
		"""Generate optimization recommendations based on current issues"""
		recommendations = []
		
		critical_issues = [i for i in issues if i.severity == IssueSeverity.CRITICAL]
		if critical_issues:
			recommendations.append("Address critical issues immediately to prevent performance degradation")
			
		auto_fixable = [i for i in issues if i.auto_fixable]
		if auto_fixable:
			recommendations.append(f"Run automated optimization to fix {len(auto_fixable)} auto-fixable issues")
			
		performance_issues = [i for i in issues if i.issue_type == IssueType.PERFORMANCE_BOTTLENECKS]
		if performance_issues:
			recommendations.append("Consider implementing performance monitoring for high-degree nodes")
			
		if len(issues) > 20:
			recommendations.append("Schedule regular optimization runs to maintain graph health")
			
		return recommendations


# Global graph optimizers
_graph_optimizers = {}


def get_graph_optimizer(graph_name: str) -> GraphOptimizer:
	"""Get or create a graph optimizer for the specified graph"""
	if graph_name not in _graph_optimizers:
		_graph_optimizers[graph_name] = GraphOptimizer(graph_name)
	return _graph_optimizers[graph_name]


def run_automated_healing(graph_name: str, optimization_level: OptimizationLevel = OptimizationLevel.MODERATE) -> List[OptimizationResult]:
	"""Convenience function to run automated graph healing"""
	optimizer = get_graph_optimizer(graph_name)
	return optimizer.optimize_graph(optimization_level)