"""
Comprehensive test suite for graph analytics features

Tests all 10 major features implemented in the enterprise-grade 
graph analytics platform with Apache AGE integration.
"""

import pytest
import json
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock

from flask import Flask
from pgappforge import AppBuilder
from flask_login import login_user

from tests.base import FABTestCase
from pgappforge.database.graph_manager import GraphManager
from pgappforge.database.multi_graph_manager import GraphRegistry
from pgappforge.database.query_builder import AdvancedQueryBuilder
from pgappforge.database.graph_streaming import GraphStreamingManager
from pgappforge.database.graph_ml import GraphMLSuite
from pgappforge.database.performance_optimizer import PerformanceOptimizer
from pgappforge.database.import_export_pipeline import ImportExportPipeline
from pgappforge.database.collaboration_system import CollaborationSystem
from pgappforge.database.ai_analytics_assistant import AIAnalyticsAssistant
from pgappforge.database.advanced_visualization import AdvancedVisualizationEngine
from pgappforge.database.enterprise_integration import EnterpriseIntegrationSuite


class TestGraphAnalytics(FABTestCase):
	"""Test suite for graph analytics platform"""
	
	def setUp(self):
		"""Set up test environment"""
		super().setUp()
		
		# Mock database connection for AGE
		self.mock_db = Mock()
		self.mock_cursor = Mock()
		self.mock_db.cursor.return_value.__enter__.return_value = self.mock_cursor
		
		# Create test data structures
		self.test_graph_name = "test_graph"
		self.test_nodes = [
			{"id": 1, "name": "Alice", "type": "Person"},
			{"id": 2, "name": "Bob", "type": "Person"},
			{"id": 3, "name": "Company", "type": "Organization"}
		]
		self.test_edges = [
			{"from": 1, "to": 2, "type": "KNOWS"},
			{"from": 1, "to": 3, "type": "WORKS_FOR"}
		]
	
	def test_graph_manager_basic_operations(self):
		"""Test GraphManager core functionality"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			gm = GraphManager(self.test_graph_name)
			
			# Test graph creation
			self.mock_cursor.fetchall.return_value = []
			result = gm.create_graph()
			self.assertTrue(result.get("success", False))
			
			# Test node creation
			self.mock_cursor.fetchall.return_value = [(1, "Alice", "Person")]
			result = gm.create_node("Person", {"name": "Alice"})
			self.assertTrue(result.get("success", False))
			
			# Test edge creation
			self.mock_cursor.fetchall.return_value = [(1, 2, "KNOWS")]
			result = gm.create_edge("KNOWS", 1, 2, {})
			self.assertTrue(result.get("success", False))
	
	def test_multi_graph_management(self):
		"""Test multi-graph operations"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			registry = GraphRegistry()
			
			# Test graph registration
			registry.register_graph("graph1", {"description": "Test Graph 1"})
			registry.register_graph("graph2", {"description": "Test Graph 2"})
			
			graphs = registry.list_graphs()
			self.assertEqual(len(graphs), 2)
			
			# Test graph union operation
			self.mock_cursor.fetchall.return_value = self.test_nodes + self.test_edges
			result = registry.union_graphs(["graph1", "graph2"], "union_graph")
			self.assertIn("success", result)
	
	def test_advanced_query_builder(self):
		"""Test advanced query builder functionality"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			qb = AdvancedQueryBuilder(self.test_graph_name)
			
			# Test visual query building
			query_spec = {
				"nodes": [{"variable": "n", "labels": ["Person"], "properties": {"name": "Alice"}}],
				"edges": [{"variable": "r", "type": "KNOWS", "from": "n", "to": "m"}],
				"returns": ["n", "r", "m"]
			}
			
			cypher_query = qb.build_visual_query(query_spec)
			self.assertIn("MATCH", cypher_query)
			self.assertIn("Person", cypher_query)
			self.assertIn("KNOWS", cypher_query)
			
			# Test query validation
			validation_result = qb.validate_query(cypher_query)
			self.assertTrue(validation_result.get("is_valid", False))
	
	@patch('asyncio.get_event_loop')
	def test_graph_streaming(self, mock_loop):
		"""Test real-time graph streaming"""
		mock_loop.return_value = AsyncMock()
		
		with patch('psycopg2.connect', return_value=self.mock_db):
			streaming = GraphStreamingManager()
			
			# Test session creation
			session_id = streaming.create_streaming_session(
				self.test_graph_name, 
				"test_user",
				["node_created", "edge_created"]
			)
			self.assertIsNotNone(session_id)
			
			# Test event broadcasting
			event = {
				"type": "node_created",
				"graph_name": self.test_graph_name,
				"data": {"id": 1, "name": "Alice"}
			}
			
			streaming.broadcast_event(event)
			self.assertIn(session_id, streaming.active_sessions)
	
	def test_machine_learning_integration(self):
		"""Test ML capabilities"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			ml_suite = GraphMLSuite(self.test_graph_name)
			
			# Mock graph data
			self.mock_cursor.fetchall.return_value = [
				(1, "Alice", "Person", 0.8),
				(2, "Bob", "Person", 0.6),
				(3, "Company", "Organization", 0.9)
			]
			
			# Test node classification
			result = ml_suite.classify_nodes(["Person", "Organization"])
			self.assertIn("predictions", result)
			self.assertIn("confidence_scores", result)
			
			# Test anomaly detection
			anomalies = ml_suite.detect_anomalies()
			self.assertIsInstance(anomalies, list)
	
	def test_performance_optimization(self):
		"""Test performance optimization engine"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			optimizer = PerformanceOptimizer(self.test_graph_name)
			
			# Test query optimization
			simple_query = "MATCH (n:Person) RETURN n"
			optimized = optimizer.optimize_query(simple_query)
			self.assertIn("optimized_query", optimized)
			self.assertIn("performance_score", optimized)
			
			# Test caching
			cache_key = optimizer.cache_query_result(simple_query, self.test_nodes)
			self.assertIsNotNone(cache_key)
			
			cached_result = optimizer.get_cached_result(cache_key)
			self.assertEqual(cached_result, self.test_nodes)
	
	def test_import_export_pipeline(self):
		"""Test data import/export functionality"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			pipeline = ImportExportPipeline()
			
			# Test GraphML export
			export_data = {
				"nodes": self.test_nodes,
				"edges": self.test_edges
			}
			
			with patch('builtins.open', create=True) as mock_file:
				mock_file.return_value.__enter__.return_value.write = Mock()
				
				result = pipeline.export_to_graphml(
					self.test_graph_name, 
					"/tmp/test_export.graphml"
				)
				self.assertTrue(result.get("success", False))
			
			# Test JSON import
			json_data = {
				"nodes": self.test_nodes,
				"edges": self.test_edges
			}
			
			with patch('builtins.open', create=True) as mock_file:
				mock_file.return_value.__enter__.return_value.read.return_value = json.dumps(json_data)
				
				result = pipeline.import_from_json(
					"/tmp/test_import.json",
					self.test_graph_name
				)
				self.assertTrue(result.get("success", False))
	
	def test_collaboration_system(self):
		"""Test real-time collaboration"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			collab = CollaborationSystem()
			
			# Test session creation
			session_id = collab.create_collaboration_session(
				self.test_graph_name,
				"admin_user",
				{"max_users": 5, "permissions": ["edit", "view"]}
			)
			self.assertIsNotNone(session_id)
			
			# Test user joining
			result = collab.join_session(session_id, "test_user", {"role": "editor"})
			self.assertTrue(result.get("success", False))
			
			# Test operation broadcasting
			operation = {
				"type": "node_created",
				"user_id": "test_user",
				"data": {"id": 4, "name": "Charlie"},
				"timestamp": datetime.now().isoformat()
			}
			
			collab.broadcast_operation(session_id, operation)
			session = collab.active_sessions.get(session_id)
			self.assertIsNotNone(session)
	
	def test_ai_analytics_assistant(self):
		"""Test AI-powered analytics"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			ai_assistant = AIAnalyticsAssistant(self.test_graph_name)
			
			# Mock graph analysis results
			self.mock_cursor.fetchall.return_value = [
				(1, "Alice", 5),  # node_id, name, degree
				(2, "Bob", 3),
				(3, "Company", 8)
			]
			
			# Test natural language query processing
			nl_query = "Find the most connected person in the graph"
			suggestion = ai_assistant.process_natural_language_query(nl_query)
			
			self.assertIn("cypher_query", suggestion.to_dict())
			self.assertIn("explanation", suggestion.to_dict())
			self.assertIn("confidence_score", suggestion.to_dict())
			
			# Test automated insights generation
			insights = ai_assistant.get_automated_insights(self.test_graph_name)
			self.assertIsInstance(insights, list)
	
	def test_advanced_visualization(self):
		"""Test visualization engine"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			viz_engine = AdvancedVisualizationEngine()
			
			# Test layout computation
			graph_data = {
				"nodes": self.test_nodes,
				"edges": self.test_edges
			}
			
			layout_result = viz_engine.compute_layout(graph_data, "force_directed")
			self.assertIn("positioned_nodes", layout_result)
			self.assertIn("layout_metadata", layout_result)
			
			# Test interactive features
			interaction_config = viz_engine.generate_interaction_config(graph_data)
			self.assertIn("zoom_settings", interaction_config)
			self.assertIn("selection_config", interaction_config)
	
	def test_enterprise_integration(self):
		"""Test enterprise integration suite"""
		with patch('psycopg2.connect', return_value=self.mock_db):
			enterprise = EnterpriseIntegrationSuite()
			
			# Test credential management
			cred_id = enterprise.credential_manager.store_credential(
				name="test_api_key",
				integration_type="REST_API",
				auth_method="API_KEY",
				credential_data={"api_key": "test_key", "api_secret": "test_secret"}
			)
			self.assertIsNotNone(cred_id)
			
			# Test API management
			api_key_data = enterprise.api_manager.generate_api_key(
				name="test_integration",
				permissions=["read", "write"]
			)
			self.assertIn("api_key", api_key_data)
			self.assertIn("api_secret", api_key_data)
			
			# Test audit logging
			enterprise.audit_logger.log_event(
				user_id="test_user",
				action="graph_query",
				resource=self.test_graph_name,
				outcome="success",
				details={"query": "MATCH (n) RETURN n"}
			)
			
			logs = enterprise.audit_logger.search_logs(limit=1)
			self.assertEqual(len(logs), 1)


class TestGraphAnalyticsAPI(FABTestCase):
	"""Test API endpoints for graph analytics"""
	
	def setUp(self):
		"""Set up API test environment"""
		super().setUp()
		
		# Create test user with admin privileges
		self.admin_user = self.appbuilder.sm.find_user(username="admin")
		if not self.admin_user:
			role = self.appbuilder.sm.add_role("Admin")
			self.admin_user = self.appbuilder.sm.add_user(
				"admin", "admin", "admin", "admin@test.com", role, "password"
			)
	
	def test_query_builder_api(self):
		"""Test query builder API endpoints"""
		with self.app.test_client() as client:
			# Login as admin
			with client.session_transaction() as sess:
				sess['_user_id'] = str(self.admin_user.id)
				sess['_fresh'] = True
			
			# Test visual query building
			response = client.post('/graph/query-builder/api/build-visual-query/', 
				json={
					"graph_name": "test_graph",
					"query_spec": {
						"nodes": [{"variable": "n", "labels": ["Person"]}],
						"returns": ["n"]
					}
				}
			)
			
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertTrue(data.get("success", False))
	
	def test_ai_assistant_api(self):
		"""Test AI assistant API endpoints"""
		with self.app.test_client() as client:
			# Login as admin
			with client.session_transaction() as sess:
				sess['_user_id'] = str(self.admin_user.id)
				sess['_fresh'] = True
			
			# Test natural language query
			response = client.post('/graph/ai-assistant/api/natural-language-query/',
				json={
					"query": "Find all people named Alice",
					"graph_name": "test_graph"
				}
			)
			
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertTrue(data.get("success", False))
	
	def test_streaming_api(self):
		"""Test streaming API endpoints"""
		with self.app.test_client() as client:
			# Login as admin
			with client.session_transaction() as sess:
				sess['_user_id'] = str(self.admin_user.id)
				sess['_fresh'] = True
			
			# Test session creation
			response = client.post('/graph/streaming/api/create-session/',
				json={
					"graph_name": "test_graph",
					"event_types": ["node_created", "edge_created"]
				}
			)
			
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertTrue(data.get("success", False))
			self.assertIn("session_id", data)


class TestGraphAnalyticsIntegration(FABTestCase):
	"""Integration tests for complete workflows"""
	
	def test_complete_analysis_workflow(self):
		"""Test end-to-end analysis workflow"""
		with patch('psycopg2.connect') as mock_connect:
			mock_db = Mock()
			mock_cursor = Mock()
			mock_connect.return_value = mock_db
			mock_db.cursor.return_value.__enter__.return_value = mock_cursor
			
			# Mock data returns
			mock_cursor.fetchall.side_effect = [
				[],  # Graph creation
				[(1, "Alice", "Person")],  # Node creation
				[(1, 2, "KNOWS")],  # Edge creation
				[(1, "Alice", 3), (2, "Bob", 2)],  # Analysis query
			]
			
			# Step 1: Create graph and add data
			gm = GraphManager("integration_test")
			gm.create_graph()
			gm.create_node("Person", {"name": "Alice"})
			gm.create_node("Person", {"name": "Bob"})
			gm.create_edge("KNOWS", 1, 2, {})
			
			# Step 2: Run AI analysis
			ai_assistant = AIAnalyticsAssistant("integration_test")
			insights = ai_assistant.get_automated_insights("integration_test")
			
			# Step 3: Apply ML algorithms
			ml_suite = GraphMLSuite("integration_test")
			ml_results = ml_suite.classify_nodes(["Person"])
			
			# Step 4: Optimize performance
			optimizer = PerformanceOptimizer("integration_test")
			optimized_query = optimizer.optimize_query("MATCH (n:Person) RETURN n")
			
			# Verify workflow completed successfully
			self.assertIsInstance(insights, list)
			self.assertIn("predictions", ml_results)
			self.assertIn("optimized_query", optimized_query)
	
	def test_collaborative_editing_workflow(self):
		"""Test collaborative editing workflow"""
		with patch('psycopg2.connect') as mock_connect:
			mock_db = Mock()
			mock_connect.return_value = mock_db
			
			# Create collaboration session
			collab = CollaborationSystem()
			session_id = collab.create_collaboration_session(
				"collab_graph", 
				"admin_user",
				{"max_users": 3}
			)
			
			# Multiple users join
			user1_result = collab.join_session(session_id, "user1", {"role": "editor"})
			user2_result = collab.join_session(session_id, "user2", {"role": "viewer"})
			
			# Simulate collaborative operations
			operation1 = {
				"type": "node_created",
				"user_id": "user1",
				"data": {"name": "New Node"},
				"timestamp": datetime.now().isoformat()
			}
			
			operation2 = {
				"type": "node_updated",
				"user_id": "user1", 
				"data": {"id": 1, "name": "Updated Node"},
				"timestamp": datetime.now().isoformat()
			}
			
			collab.broadcast_operation(session_id, operation1)
			collab.broadcast_operation(session_id, operation2)
			
			# Verify session state
			session = collab.active_sessions.get(session_id)
			self.assertIsNotNone(session)
			self.assertEqual(len(session["participants"]), 2)
			self.assertEqual(len(session["operation_history"]), 2)


if __name__ == '__main__':
	pytest.main([__file__, '-v'])