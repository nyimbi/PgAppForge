"""
Integration tests for complete graph analytics workflows

Tests end-to-end scenarios combining multiple features of the 
enterprise-grade graph analytics platform.
"""

import pytest
import json
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from concurrent.futures import ThreadPoolExecutor

from flask import Flask
from pgappforge import AppBuilder
from flask_login import login_user

from tests.base import FABTestCase


class TestCompleteWorkflows(FABTestCase):
	"""Integration tests for complete analytics workflows"""
	
	def setUp(self):
		"""Set up integration test environment"""
		super().setUp()
		
		# Mock database connections
		self.mock_db = Mock()
		self.mock_cursor = Mock()
		self.mock_db.cursor.return_value.__enter__.return_value = self.mock_cursor
		
		# Create test admin user
		self.admin_user = self.appbuilder.sm.find_user(username="admin")
		if not self.admin_user:
			role = self.appbuilder.sm.add_role("Admin") 
			self.admin_user = self.appbuilder.sm.add_user(
				"admin", "admin", "admin", "admin@test.com", role, "password"
			)
		
		# Test data
		self.test_graph_data = {
			"nodes": [
				{"id": 1, "name": "Alice", "type": "Person", "department": "Engineering"},
				{"id": 2, "name": "Bob", "type": "Person", "department": "Marketing"}, 
				{"id": 3, "name": "Charlie", "type": "Person", "department": "Engineering"},
				{"id": 4, "name": "DataCorp", "type": "Company"},
				{"id": 5, "name": "Project Alpha", "type": "Project"}
			],
			"edges": [
				{"from": 1, "to": 2, "type": "COLLABORATES_WITH", "strength": 0.8},
				{"from": 1, "to": 3, "type": "COLLABORATES_WITH", "strength": 0.9},
				{"from": 1, "to": 4, "type": "WORKS_FOR"},
				{"from": 2, "to": 4, "type": "WORKS_FOR"},
				{"from": 3, "to": 4, "type": "WORKS_FOR"},
				{"from": 1, "to": 5, "type": "LEADS"},
				{"from": 3, "to": 5, "type": "CONTRIBUTES_TO"}
			]
		}
	
	@patch('psycopg2.connect')
	def test_end_to_end_graph_analysis_workflow(self, mock_connect):
		"""Test complete graph creation, analysis, and insights workflow"""
		# Setup mock database
		mock_connect.return_value = self.mock_db
		
		# Mock various database responses for different stages
		self.mock_cursor.fetchall.side_effect = [
			# Graph creation
			[],
			# Node creation responses
			[(1, "Alice", "Person")], [(2, "Bob", "Person")], [(3, "Charlie", "Person")],
			[(4, "DataCorp", "Company")], [(5, "Project Alpha", "Project")],
			# Edge creation responses  
			[(1, 2, "COLLABORATES_WITH")], [(1, 3, "COLLABORATES_WITH")],
			[(1, 4, "WORKS_FOR")], [(2, 4, "WORKS_FOR")], [(3, 4, "WORKS_FOR")],
			[(1, 5, "LEADS")], [(3, 5, "CONTRIBUTES_TO")],
			# Analysis queries
			[(1, "Alice", 4), (2, "Bob", 2), (3, "Charlie", 3)],  # Degree centrality
			[(1, "Alice"), (3, "Charlie")],  # Community detection
			[(1, "Alice", "High influence"), (3, "Charlie", "High collaboration")]  # Insights
		]
		
		with self.app.test_client() as client:
			# Login as admin
			with client.session_transaction() as sess:
				sess['_user_id'] = str(self.admin_user.id)
				sess['_fresh'] = True
			
			# Step 1: Create graph using Graph Manager
			response = client.post('/graph/api/create-graph/', 
				json={"graph_name": "workflow_test_graph"}
			)
			self.assertEqual(response.status_code, 200)
			
			# Step 2: Add nodes and edges using Query Builder
			for node in self.test_graph_data["nodes"]:
				response = client.post('/graph/query-builder/api/create-node/',
					json={
						"graph_name": "workflow_test_graph",
						"node_type": node["type"],
						"properties": {k:v for k,v in node.items() if k != "id"}
					}
				)
				self.assertEqual(response.status_code, 200)
			
			for edge in self.test_graph_data["edges"]:
				response = client.post('/graph/query-builder/api/create-edge/',
					json={
						"graph_name": "workflow_test_graph", 
						"edge_type": edge["type"],
						"from_id": edge["from"],
						"to_id": edge["to"],
						"properties": {k:v for k,v in edge.items() if k not in ["from", "to", "type"]}
					}
				)
				self.assertEqual(response.status_code, 200)
			
			# Step 3: Run AI analysis
			response = client.post('/graph/ai-assistant/api/analyze-graph/',
				json={
					"graph_name": "workflow_test_graph",
					"analysis_types": ["structure_analysis", "centrality_analysis"]
				}
			)
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertTrue(data.get("success", False))
			self.assertIn("results", data)
			
			# Step 4: Get automated insights
			response = client.get('/graph/ai-assistant/api/insights/workflow_test_graph/')
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertTrue(data.get("success", False))
			self.assertIn("insights", data)
			
			# Step 5: Generate visualization
			response = client.post('/graph/visualization/api/generate-layout/',
				json={
					"graph_name": "workflow_test_graph",
					"layout_algorithm": "force_directed"
				}
			)
			self.assertEqual(response.status_code, 200)
	
	@patch('psycopg2.connect')
	def test_collaborative_analysis_workflow(self, mock_connect):
		"""Test real-time collaborative analysis workflow"""
		mock_connect.return_value = self.mock_db
		
		# Mock responses for collaboration setup
		self.mock_cursor.fetchall.side_effect = [
			[(1, "Alice", "Person")],  # Initial graph data
			[(1, "Alice", "Person"), (2, "Bob", "Person")],  # After collaborative addition
		]
		
		with self.app.test_client() as client:
			# Login as admin
			with client.session_transaction() as sess:
				sess['_user_id'] = str(self.admin_user.id)
				sess['_fresh'] = True
			
			# Step 1: Create collaboration session
			response = client.post('/graph/collaboration/api/create-session/',
				json={
					"graph_name": "collab_test_graph",
					"session_config": {
						"max_users": 3,
						"permissions": ["edit", "view"],
						"auto_save": True
					}
				}
			)
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			session_id = data["session_id"]
			
			# Step 2: Simulate multiple users joining
			response = client.post(f'/graph/collaboration/api/join-session/{session_id}/',
				json={
					"user_info": {"role": "analyst", "name": "User1"}
				}
			)
			self.assertEqual(response.status_code, 200)
			
			# Step 3: Simulate collaborative operations
			response = client.post(f'/graph/collaboration/api/broadcast-operation/{session_id}/',
				json={
					"operation": {
						"type": "node_created",
						"data": {"name": "New Collaborative Node", "type": "Person"},
						"user_id": "user1",
						"timestamp": datetime.now().isoformat()
					}
				}
			)
			self.assertEqual(response.status_code, 200)
			
			# Step 4: Run collaborative analysis
			response = client.post('/graph/ai-assistant/api/natural-language-query/',
				json={
					"query": "Show me all people in the collaborative graph",
					"graph_name": "collab_test_graph", 
					"session_id": session_id
				}
			)
			self.assertEqual(response.status_code, 200)
	
	@patch('psycopg2.connect')
	def test_ml_pipeline_workflow(self, mock_connect):
		"""Test complete ML pipeline workflow"""
		mock_connect.return_value = self.mock_db
		
		# Mock ML training data and results
		self.mock_cursor.fetchall.side_effect = [
			# Training data
			[(1, "Alice", "Person", "Engineering"), (2, "Bob", "Person", "Marketing")],
			# Prediction results
			[(1, "Person", 0.95), (2, "Person", 0.87), (3, "Company", 0.92)],
			# Anomaly detection results
			[(1, "Alice", 0.1), (4, "DataCorp", 0.8)],  # Anomaly scores
		]
		
		with self.app.test_client() as client:
			# Login as admin
			with client.session_transaction() as sess:
				sess['_user_id'] = str(self.admin_user.id)
				sess['_fresh'] = True
			
			# Step 1: Train node classification model
			response = client.post('/graph/ml/api/train-model/',
				json={
					"graph_name": "ml_test_graph",
					"model_type": "node_classification",
					"target_labels": ["Person", "Company", "Project"],
					"features": ["degree", "clustering_coefficient", "betweenness"]
				}
			)
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertTrue(data.get("success", False))
			model_id = data["model_id"]
			
			# Step 2: Make predictions
			response = client.post(f'/graph/ml/api/predict/{model_id}/',
				json={
					"graph_name": "ml_test_graph",
					"node_ids": [1, 2, 3]
				}
			)
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertIn("predictions", data)
			
			# Step 3: Run anomaly detection
			response = client.post('/graph/ml/api/detect-anomalies/',
				json={
					"graph_name": "ml_test_graph",
					"algorithm": "isolation_forest",
					"contamination": 0.1
				}
			)
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertIn("anomalies", data)
			
			# Step 4: Get ML insights
			response = client.get(f'/graph/ml/api/insights/ml_test_graph/?model_id={model_id}')
			self.assertEqual(response.status_code, 200)
	
	@patch('psycopg2.connect')
	def test_data_pipeline_workflow(self, mock_connect):
		"""Test complete data import/export pipeline workflow"""
		mock_connect.return_value = self.mock_db
		
		# Mock import/export operations
		with self.app.test_client() as client:
			# Login as admin
			with client.session_transaction() as sess:
				sess['_user_id'] = str(self.admin_user.id)
				sess['_fresh'] = True
			
			# Step 1: Import data from JSON
			import_data = {
				"nodes": self.test_graph_data["nodes"][:3],
				"edges": self.test_graph_data["edges"][:2]
			}
			
			with patch('builtins.open', create=True) as mock_file:
				mock_file.return_value.__enter__.return_value.read.return_value = json.dumps(import_data)
				
				response = client.post('/graph/import-export/api/import/',
					json={
						"source_type": "json",
						"file_path": "/tmp/test_data.json",
						"target_graph": "pipeline_test_graph",
						"merge_strategy": "append"
					}
				)
				self.assertEqual(response.status_code, 200)
			
			# Step 2: Transform data
			response = client.post('/graph/import-export/api/transform/',
				json={
					"graph_name": "pipeline_test_graph",
					"transformations": [
						{"type": "normalize_properties"},
						{"type": "add_computed_features", "features": ["degree", "clustering"]}
					]
				}
			)
			self.assertEqual(response.status_code, 200)
			
			# Step 3: Export processed data
			with patch('builtins.open', create=True) as mock_file:
				mock_file.return_value.__enter__.return_value.write = Mock()
				
				response = client.post('/graph/import-export/api/export/',
					json={
						"graph_name": "pipeline_test_graph",
						"export_format": "graphml",
						"output_path": "/tmp/exported_graph.graphml",
						"include_computed": True
					}
				)
				self.assertEqual(response.status_code, 200)
	
	@patch('psycopg2.connect')
	def test_enterprise_integration_workflow(self, mock_connect):
		"""Test enterprise integration and security workflow"""
		mock_connect.return_value = self.mock_db
		
		with self.app.test_client() as client:
			# Login as admin
			with client.session_transaction() as sess:
				sess['_user_id'] = str(self.admin_user.id)
				sess['_fresh'] = True
			
			# Step 1: Configure SSO provider
			response = client.post('/enterprise/api/sso-provider/',
				json={
					"provider_type": "saml",
					"provider_name": "CorporateSSO",
					"configuration": {
						"entity_id": "https://company.com/saml/entity",
						"sso_url": "https://company.com/saml/sso",
						"certificate": "-----BEGIN CERTIFICATE-----\nMIIC..."
					}
				}
			)
			self.assertEqual(response.status_code, 200)
			
			# Step 2: Store API credentials
			response = client.post('/enterprise/api/credentials/',
				json={
					"name": "ExternalAPI",
					"integration_type": "REST_API", 
					"auth_method": "API_KEY",
					"credential_data": {
						"api_key": "test_key_123",
						"api_secret": "test_secret_456"
					}
				}
			)
			self.assertEqual(response.status_code, 200)
			
			# Step 3: Create external connector
			response = client.post('/enterprise/api/connectors/rest-api/',
				json={
					"name": "ExternalDataSource",
					"credential_id": "test_credential_id",
					"base_url": "https://external-api.company.com",
					"headers": {"Content-Type": "application/json"}
				}
			)
			self.assertEqual(response.status_code, 200)
			
			# Step 4: Test audit logging
			response = client.get('/enterprise/api/audit-logs/?limit=10')
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertIn("logs", data)
	
	@patch('psycopg2.connect')
	def test_performance_optimization_workflow(self, mock_connect):
		"""Test performance optimization and monitoring workflow"""
		mock_connect.return_value = self.mock_db
		
		# Mock performance data
		self.mock_cursor.fetchall.side_effect = [
			[(1, "Alice", "Person")],  # Original query result
			[(1, "Alice", "Person")],  # Optimized query result  
		]
		
		with self.app.test_client() as client:
			# Login as admin
			with client.session_transaction() as sess:
				sess['_user_id'] = str(self.admin_user.id)
				sess['_fresh'] = True
			
			# Step 1: Analyze query performance
			test_query = "MATCH (n:Person)-[:WORKS_FOR]->(c:Company) RETURN n.name, c.name"
			
			response = client.post('/graph/performance/api/analyze-query/',
				json={
					"graph_name": "perf_test_graph",
					"cypher_query": test_query
				}
			)
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertIn("performance_metrics", data)
			
			# Step 2: Get optimization suggestions
			response = client.post('/graph/performance/api/optimize-query/',
				json={
					"graph_name": "perf_test_graph",
					"cypher_query": test_query,
					"optimization_level": "aggressive"
				}
			)
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertIn("optimized_query", data)
			
			# Step 3: Monitor system performance
			response = client.get('/graph/performance/api/system-metrics/')
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertIn("metrics", data)
			
			# Step 4: Cache optimization
			response = client.post('/graph/performance/api/cache-management/',
				json={
					"operation": "optimize",
					"graph_name": "perf_test_graph"
				}
			)
			self.assertEqual(response.status_code, 200)


class TestStreamingWorkflows(FABTestCase):
	"""Test real-time streaming workflows"""
	
	def setUp(self):
		"""Set up streaming test environment"""
		super().setUp()
		
		# Mock WebSocket and async components
		self.mock_ws = AsyncMock()
		self.mock_event_loop = Mock()
	
	@patch('asyncio.get_event_loop')
	@patch('psycopg2.connect')
	def test_real_time_collaboration_streaming(self, mock_connect, mock_loop):
		"""Test real-time streaming during collaborative editing"""
		mock_connect.return_value = Mock()
		mock_loop.return_value = AsyncMock()
		
		with self.app.test_client() as client:
			# Step 1: Create streaming session
			response = client.post('/graph/streaming/api/create-session/',
				json={
					"graph_name": "streaming_test_graph",
					"event_types": ["node_created", "edge_created", "node_updated"],
					"user_id": "test_user"
				}
			)
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			session_id = data["session_id"]
			
			# Step 2: Simulate real-time events
			events = [
				{"type": "node_created", "data": {"id": 1, "name": "Alice"}},
				{"type": "edge_created", "data": {"from": 1, "to": 2, "type": "KNOWS"}},
				{"type": "node_updated", "data": {"id": 1, "name": "Alice Smith"}}
			]
			
			for event in events:
				response = client.post(f'/graph/streaming/api/broadcast/{session_id}/',
					json={"event": event}
				)
				self.assertEqual(response.status_code, 200)
			
			# Step 3: Verify event history
			response = client.get(f'/graph/streaming/api/session/{session_id}/events/')
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.data)
			self.assertEqual(len(data["events"]), 3)
	
	def test_concurrent_analysis_workflow(self):
		"""Test handling multiple concurrent analysis requests"""
		with self.app.test_client() as client:
			# Simulate multiple concurrent analysis requests
			with ThreadPoolExecutor(max_workers=3) as executor:
				
				def run_analysis(graph_name):
					return client.post('/graph/ai-assistant/api/analyze-graph/',
						json={
							"graph_name": graph_name,
							"analysis_types": ["structure_analysis"]
						}
					)
				
				# Submit concurrent requests
				futures = [
					executor.submit(run_analysis, f"concurrent_graph_{i}") 
					for i in range(3)
				]
				
				# Wait for all to complete
				responses = [future.result() for future in futures]
				
				# Verify all succeeded
				for response in responses:
					self.assertEqual(response.status_code, 200)


class TestErrorHandlingWorkflows(FABTestCase):
	"""Test error handling in complex workflows"""
	
	def setUp(self):
		"""Set up error handling test environment"""
		super().setUp()
		
		self.mock_db = Mock()
		self.mock_cursor = Mock()
		self.mock_db.cursor.return_value.__enter__.return_value = self.mock_cursor
	
	@patch('psycopg2.connect')
	def test_database_failure_recovery(self, mock_connect):
		"""Test graceful handling of database failures"""
		# Mock database connection failure
		mock_connect.side_effect = Exception("Database connection failed")
		
		with self.app.test_client() as client:
			response = client.post('/graph/api/create-graph/',
				json={"graph_name": "failing_graph"}
			)
			
			# Should return error but not crash
			self.assertEqual(response.status_code, 500)
			data = json.loads(response.data)
			self.assertFalse(data.get("success", True))
			self.assertIn("error", data)
	
	@patch('psycopg2.connect')
	def test_partial_failure_rollback(self, mock_connect):
		"""Test transaction rollback on partial failures"""
		mock_connect.return_value = self.mock_db
		
		# Mock successful operations followed by failure
		self.mock_cursor.fetchall.side_effect = [
			[],  # Graph creation success
			[(1, "Alice", "Person")],  # First node success
			Exception("Node creation failed"),  # Second node failure
		]
		
		with self.app.test_client() as client:
			# Attempt batch operation that should fail partway
			response = client.post('/graph/query-builder/api/batch-create/',
				json={
					"graph_name": "rollback_test_graph",
					"operations": [
						{"type": "create_node", "data": {"name": "Alice", "type": "Person"}},
						{"type": "create_node", "data": {"name": "Bob", "type": "Person"}},
						{"type": "create_edge", "data": {"from": 1, "to": 2, "type": "KNOWS"}}
					]
				}
			)
			
			# Should handle partial failure gracefully
			self.assertEqual(response.status_code, 500)
			data = json.loads(response.data)
			self.assertIn("error", data)
			self.assertIn("rollback", data.get("message", "").lower())


if __name__ == '__main__':
	pytest.main([__file__, '-v'])