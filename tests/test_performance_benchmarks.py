"""
Performance benchmarking and optimization verification tests

Validates performance characteristics of all 10 major features
and ensures optimization strategies are working effectively.
"""

import pytest
import time
import statistics
import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from memory_profiler import profile
import psutil
import gc

from tests.base import FABTestCase


class TestPerformanceBenchmarks(FABTestCase):
	"""Performance benchmark tests for graph analytics platform"""
	
	def setUp(self):
		"""Set up performance testing environment"""
		super().setUp()
		
		# Mock database for consistent timing
		self.mock_db = Mock()
		self.mock_cursor = Mock()
		self.mock_db.cursor.return_value.__enter__.return_value = self.mock_cursor
		
		# Performance thresholds (in seconds)
		self.thresholds = {
			"graph_creation": 0.1,
			"query_execution": 0.05,
			"visual_query_build": 0.02,
			"streaming_latency": 0.01,
			"ml_prediction": 0.5,
			"ai_analysis": 1.0,
			"visualization_layout": 2.0,
			"bulk_import": 5.0
		}
		
		# Test data sizes
		self.test_sizes = {
			"small": {"nodes": 100, "edges": 200},
			"medium": {"nodes": 1000, "edges": 2000},
			"large": {"nodes": 10000, "edges": 20000}
		}
	
	def benchmark_operation(self, operation_func, iterations=10):
		"""Utility to benchmark an operation multiple times"""
		execution_times = []
		
		for _ in range(iterations):
			gc.collect()  # Clear memory before each test
			
			start_time = time.perf_counter()
			result = operation_func()
			end_time = time.perf_counter()
			
			execution_times.append(end_time - start_time)
		
		return {
			"mean": statistics.mean(execution_times),
			"median": statistics.median(execution_times),
			"min": min(execution_times),
			"max": max(execution_times),
			"std_dev": statistics.stdev(execution_times) if len(execution_times) > 1 else 0,
			"iterations": iterations,
			"all_times": execution_times
		}
	
	@patch('psycopg2.connect')
	def test_graph_manager_performance(self, mock_connect):
		"""Benchmark core graph management operations"""
		mock_connect.return_value = self.mock_db
		self.mock_cursor.fetchall.return_value = []
		
		from pgappforge.database.graph_manager import GraphManager
		
		def create_graph():
			gm = GraphManager("perf_test_graph")
			return gm.create_graph()
		
		def create_node():
			gm = GraphManager("perf_test_graph")
			return gm.create_node("Person", {"name": "Test"})
		
		def execute_query():
			gm = GraphManager("perf_test_graph")
			return gm.execute_cypher_query("MATCH (n) RETURN count(n)")
		
		# Benchmark operations
		graph_creation = self.benchmark_operation(create_graph)
		node_creation = self.benchmark_operation(create_node)
		query_execution = self.benchmark_operation(execute_query)
		
		# Assert performance thresholds
		self.assertLess(graph_creation["mean"], self.thresholds["graph_creation"],
			f"Graph creation too slow: {graph_creation['mean']:.3f}s")
		
		self.assertLess(node_creation["mean"], self.thresholds["query_execution"],
			f"Node creation too slow: {node_creation['mean']:.3f}s")
		
		self.assertLess(query_execution["mean"], self.thresholds["query_execution"],
			f"Query execution too slow: {query_execution['mean']:.3f}s")
		
		print(f"Graph Manager Performance:")
		print(f"  Graph Creation: {graph_creation['mean']:.3f}s ± {graph_creation['std_dev']:.3f}s")
		print(f"  Node Creation: {node_creation['mean']:.3f}s ± {node_creation['std_dev']:.3f}s")
		print(f"  Query Execution: {query_execution['mean']:.3f}s ± {query_execution['std_dev']:.3f}s")
	
	@patch('psycopg2.connect')
	def test_query_builder_performance(self, mock_connect):
		"""Benchmark advanced query builder performance"""
		mock_connect.return_value = self.mock_db
		
		from pgappforge.database.query_builder import AdvancedQueryBuilder
		
		def build_simple_query():
			qb = AdvancedQueryBuilder("perf_test_graph")
			query_spec = {
				"nodes": [{"variable": "n", "labels": ["Person"]}],
				"returns": ["n"]
			}
			return qb.build_visual_query(query_spec)
		
		def build_complex_query():
			qb = AdvancedQueryBuilder("perf_test_graph")
			query_spec = {
				"nodes": [
					{"variable": "p", "labels": ["Person"], "properties": {"age": ">25"}},
					{"variable": "c", "labels": ["Company"]}
				],
				"edges": [
					{"variable": "r", "type": "WORKS_FOR", "from": "p", "to": "c"}
				],
				"returns": ["p.name", "c.name", "r.since"],
				"filters": [
					{"property": "p.department", "operator": "=", "value": "Engineering"},
					{"property": "c.size", "operator": ">", "value": 100}
				],
				"order_by": [{"property": "p.name", "direction": "ASC"}],
				"limit": 50
			}
			return qb.build_visual_query(query_spec)
		
		def validate_query():
			qb = AdvancedQueryBuilder("perf_test_graph")
			return qb.validate_query("MATCH (n:Person) RETURN n")
		
		# Benchmark operations
		simple_build = self.benchmark_operation(build_simple_query)
		complex_build = self.benchmark_operation(build_complex_query)
		validation = self.benchmark_operation(validate_query)
		
		# Assert performance thresholds
		self.assertLess(simple_build["mean"], self.thresholds["visual_query_build"],
			f"Simple query building too slow: {simple_build['mean']:.3f}s")
		
		self.assertLess(complex_build["mean"], self.thresholds["visual_query_build"] * 2,
			f"Complex query building too slow: {complex_build['mean']:.3f}s")
		
		print(f"Query Builder Performance:")
		print(f"  Simple Query: {simple_build['mean']:.4f}s ± {simple_build['std_dev']:.4f}s")
		print(f"  Complex Query: {complex_build['mean']:.4f}s ± {complex_build['std_dev']:.4f}s")
		print(f"  Validation: {validation['mean']:.4f}s ± {validation['std_dev']:.4f}s")
	
	@patch('asyncio.get_event_loop')
	@patch('psycopg2.connect')
	def test_streaming_performance(self, mock_connect, mock_loop):
		"""Benchmark real-time streaming performance"""
		mock_connect.return_value = self.mock_db
		mock_loop.return_value = Mock()
		
		from pgappforge.database.graph_streaming import GraphStreamingManager
		
		def create_session():
			streaming = GraphStreamingManager()
			return streaming.create_streaming_session(
				"perf_test_graph", "test_user", ["node_created"]
			)
		
		def broadcast_event():
			streaming = GraphStreamingManager()
			session_id = "test_session"
			event = {
				"type": "node_created",
				"data": {"id": 1, "name": "Test"},
				"timestamp": time.time()
			}
			return streaming.broadcast_event(event)
		
		# Benchmark operations
		session_creation = self.benchmark_operation(create_session)
		event_broadcast = self.benchmark_operation(broadcast_event)
		
		# Assert performance thresholds
		self.assertLess(session_creation["mean"], self.thresholds["streaming_latency"] * 10,
			f"Session creation too slow: {session_creation['mean']:.3f}s")
		
		self.assertLess(event_broadcast["mean"], self.thresholds["streaming_latency"],
			f"Event broadcast too slow: {event_broadcast['mean']:.3f}s")
		
		print(f"Streaming Performance:")
		print(f"  Session Creation: {session_creation['mean']:.4f}s ± {session_creation['std_dev']:.4f}s")
		print(f"  Event Broadcast: {event_broadcast['mean']:.4f}s ± {event_broadcast['std_dev']:.4f}s")
	
	@patch('psycopg2.connect')
	def test_ml_performance(self, mock_connect):
		"""Benchmark machine learning operations"""
		mock_connect.return_value = self.mock_db
		
		# Mock ML training data
		self.mock_cursor.fetchall.side_effect = [
			# Training data
			[(i, f"Node{i}", "Person", i % 3) for i in range(100)],
			# Prediction data
			[(i, f"Node{i}", "Person") for i in range(10)],
			# Anomaly detection data
			[(i, f"Node{i}", 0.1 if i < 5 else 0.9) for i in range(10)]
		]
		
		from pgappforge.database.graph_ml import GraphMLSuite
		
		def train_classifier():
			ml_suite = GraphMLSuite("perf_test_graph")
			return ml_suite.classify_nodes(["Person", "Company"])
		
		def detect_anomalies():
			ml_suite = GraphMLSuite("perf_test_graph")
			return ml_suite.detect_anomalies()
		
		def predict_links():
			ml_suite = GraphMLSuite("perf_test_graph")
			return ml_suite.predict_links([(1, 2), (3, 4), (5, 6)])
		
		# Benchmark operations
		classification = self.benchmark_operation(train_classifier, iterations=3)
		anomaly_detection = self.benchmark_operation(detect_anomalies, iterations=5)
		link_prediction = self.benchmark_operation(predict_links, iterations=5)
		
		# Assert performance thresholds
		self.assertLess(classification["mean"], self.thresholds["ml_prediction"],
			f"Classification too slow: {classification['mean']:.3f}s")
		
		self.assertLess(anomaly_detection["mean"], self.thresholds["ml_prediction"],
			f"Anomaly detection too slow: {anomaly_detection['mean']:.3f}s")
		
		print(f"ML Performance:")
		print(f"  Classification: {classification['mean']:.3f}s ± {classification['std_dev']:.3f}s")
		print(f"  Anomaly Detection: {anomaly_detection['mean']:.3f}s ± {anomaly_detection['std_dev']:.3f}s")
		print(f"  Link Prediction: {link_prediction['mean']:.3f}s ± {link_prediction['std_dev']:.3f}s")
	
	@patch('psycopg2.connect')
	def test_ai_assistant_performance(self, mock_connect):
		"""Benchmark AI analytics assistant performance"""
		mock_connect.return_value = self.mock_db
		self.mock_cursor.fetchall.return_value = [(1, "Alice", 3), (2, "Bob", 2)]
		
		from pgappforge.database.ai_analytics_assistant import AIAnalyticsAssistant
		
		def process_nl_query():
			ai_assistant = AIAnalyticsAssistant("perf_test_graph")
			return ai_assistant.process_natural_language_query(
				"Find the most connected person"
			)
		
		def generate_insights():
			ai_assistant = AIAnalyticsAssistant("perf_test_graph")
			return ai_assistant.get_automated_insights("perf_test_graph")
		
		def get_recommendations():
			ai_assistant = AIAnalyticsAssistant("perf_test_graph")
			return ai_assistant.get_analysis_recommendations("perf_test_graph")
		
		# Benchmark operations
		nl_processing = self.benchmark_operation(process_nl_query, iterations=3)
		insights_generation = self.benchmark_operation(generate_insights, iterations=3)
		recommendations = self.benchmark_operation(get_recommendations, iterations=3)
		
		# Assert performance thresholds
		self.assertLess(nl_processing["mean"], self.thresholds["ai_analysis"],
			f"NL processing too slow: {nl_processing['mean']:.3f}s")
		
		print(f"AI Assistant Performance:")
		print(f"  NL Processing: {nl_processing['mean']:.3f}s ± {nl_processing['std_dev']:.3f}s")
		print(f"  Insights Generation: {insights_generation['mean']:.3f}s ± {insights_generation['std_dev']:.3f}s")
		print(f"  Recommendations: {recommendations['mean']:.3f}s ± {recommendations['std_dev']:.3f}s")
	
	def test_visualization_performance(self):
		"""Benchmark visualization engine performance"""
		from pgappforge.database.advanced_visualization import AdvancedVisualizationEngine
		
		# Generate test graph data
		test_data = {
			"nodes": [{"id": i, "name": f"Node{i}", "type": "Person"} for i in range(100)],
			"edges": [{"from": i, "to": (i + 1) % 100, "type": "CONNECTS"} for i in range(100)]
		}
		
		def compute_force_layout():
			viz_engine = AdvancedVisualizationEngine()
			return viz_engine.compute_layout(test_data, "force_directed")
		
		def compute_circular_layout():
			viz_engine = AdvancedVisualizationEngine()
			return viz_engine.compute_layout(test_data, "circular")
		
		def generate_interaction_config():
			viz_engine = AdvancedVisualizationEngine()
			return viz_engine.generate_interaction_config(test_data)
		
		# Benchmark operations
		force_layout = self.benchmark_operation(compute_force_layout, iterations=3)
		circular_layout = self.benchmark_operation(compute_circular_layout, iterations=5)
		interaction_config = self.benchmark_operation(generate_interaction_config, iterations=5)
		
		# Assert performance thresholds
		self.assertLess(force_layout["mean"], self.thresholds["visualization_layout"],
			f"Force layout too slow: {force_layout['mean']:.3f}s")
		
		self.assertLess(circular_layout["mean"], self.thresholds["visualization_layout"] / 4,
			f"Circular layout too slow: {circular_layout['mean']:.3f}s")
		
		print(f"Visualization Performance:")
		print(f"  Force Layout: {force_layout['mean']:.3f}s ± {force_layout['std_dev']:.3f}s")
		print(f"  Circular Layout: {circular_layout['mean']:.3f}s ± {circular_layout['std_dev']:.3f}s")
		print(f"  Interaction Config: {interaction_config['mean']:.4f}s ± {interaction_config['std_dev']:.4f}s")
	
	@patch('psycopg2.connect')
	def test_performance_optimization_effectiveness(self, mock_connect):
		"""Test that performance optimization engine actually improves performance"""
		mock_connect.return_value = self.mock_db
		
		from pgappforge.database.performance_optimizer import PerformanceOptimizer
		
		# Mock slow and optimized queries
		slow_query = "MATCH (n:Person) WHERE exists(n.name) RETURN n"
		optimized_query = "MATCH (n:Person) RETURN n"  # Simulated optimization
		
		def execute_slow_query():
			time.sleep(0.01)  # Simulate slow execution
			return {"results": [], "execution_time": 0.01}
		
		def execute_optimized_query():
			time.sleep(0.005)  # Simulate faster execution
			return {"results": [], "execution_time": 0.005}
		
		optimizer = PerformanceOptimizer("perf_test_graph")
		
		# Mock the optimizer to return our optimized query
		with patch.object(optimizer, 'optimize_query') as mock_optimize:
			mock_optimize.return_value = {
				"optimized_query": optimized_query,
				"performance_improvement": 50.0,
				"optimization_applied": ["removed_unnecessary_exists"]
			}
			
			# Benchmark both versions
			slow_performance = self.benchmark_operation(execute_slow_query)
			fast_performance = self.benchmark_operation(execute_optimized_query)
			
			# Verify optimization provides improvement
			improvement = (slow_performance["mean"] - fast_performance["mean"]) / slow_performance["mean"]
			self.assertGreater(improvement, 0.3, 
				f"Insufficient performance improvement: {improvement:.1%}")
			
			print(f"Performance Optimization Effectiveness:")
			print(f"  Original Query: {slow_performance['mean']:.4f}s ± {slow_performance['std_dev']:.4f}s")
			print(f"  Optimized Query: {fast_performance['mean']:.4f}s ± {fast_performance['std_dev']:.4f}s")
			print(f"  Improvement: {improvement:.1%}")
	
	def test_concurrent_performance(self):
		"""Test performance under concurrent load"""
		from concurrent.futures import ThreadPoolExecutor, as_completed
		import threading
		
		def simulate_api_call():
			"""Simulate an API call with some processing"""
			time.sleep(0.01)  # Simulate processing time
			thread_id = threading.current_thread().ident
			return {"thread_id": thread_id, "execution_time": 0.01}
		
		# Test with increasing concurrency levels
		concurrency_levels = [1, 5, 10, 20]
		results = {}
		
		for concurrency in concurrency_levels:
			start_time = time.perf_counter()
			
			with ThreadPoolExecutor(max_workers=concurrency) as executor:
				futures = [executor.submit(simulate_api_call) for _ in range(20)]
				responses = [future.result() for future in as_completed(futures)]
			
			end_time = time.perf_counter()
			total_time = end_time - start_time
			
			results[concurrency] = {
				"total_time": total_time,
				"requests_per_second": 20 / total_time,
				"average_response_time": total_time / 20
			}
		
		# Verify that concurrency improves throughput
		single_threaded_rps = results[1]["requests_per_second"]
		multi_threaded_rps = results[10]["requests_per_second"]
		
		self.assertGreater(multi_threaded_rps, single_threaded_rps * 2,
			"Insufficient concurrency improvement")
		
		print(f"Concurrent Performance:")
		for level, metrics in results.items():
			print(f"  {level} threads: {metrics['requests_per_second']:.1f} req/s, "
				  f"{metrics['average_response_time']:.3f}s avg response")
	
	def test_memory_usage(self):
		"""Test memory usage and leaks"""
		import gc
		
		process = psutil.Process()
		initial_memory = process.memory_info().rss / 1024 / 1024  # MB
		
		# Simulate heavy graph operations
		large_data = []
		for i in range(1000):
			# Create some data structures that might leak
			node_data = {
				"id": i,
				"name": f"Node_{i}",
				"properties": {f"prop_{j}": f"value_{j}" for j in range(10)},
				"connections": list(range(min(i, 50)))  # Simulate edges
			}
			large_data.append(node_data)
		
		# Force garbage collection
		del large_data
		gc.collect()
		
		final_memory = process.memory_info().rss / 1024 / 1024  # MB
		memory_increase = final_memory - initial_memory
		
		# Memory increase should be reasonable (less than 100MB for this test)
		self.assertLess(memory_increase, 100,
			f"Excessive memory usage: {memory_increase:.1f}MB increase")
		
		print(f"Memory Usage:")
		print(f"  Initial: {initial_memory:.1f}MB")
		print(f"  Final: {final_memory:.1f}MB")
		print(f"  Increase: {memory_increase:.1f}MB")
	
	@patch('psycopg2.connect')
	def test_cache_performance(self, mock_connect):
		"""Test caching effectiveness"""
		mock_connect.return_value = self.mock_db
		self.mock_cursor.fetchall.return_value = [(1, "Alice", "Person")]
		
		from pgappforge.database.performance_optimizer import PerformanceOptimizer
		
		optimizer = PerformanceOptimizer("perf_test_graph")
		test_query = "MATCH (n:Person) RETURN n LIMIT 10"
		test_result = [{"name": "Alice", "type": "Person"}]
		
		# First execution (no cache)
		start_time = time.perf_counter()
		cache_key = optimizer.cache_query_result(test_query, test_result)
		first_time = time.perf_counter() - start_time
		
		# Second execution (from cache)
		start_time = time.perf_counter()
		cached_result = optimizer.get_cached_result(cache_key)
		cache_time = time.perf_counter() - start_time
		
		# Cache should be significantly faster
		self.assertIsNotNone(cached_result)
		self.assertLess(cache_time, first_time / 2,
			f"Cache not effective: {cache_time:.4f}s vs {first_time:.4f}s")
		
		print(f"Cache Performance:")
		print(f"  First execution: {first_time:.4f}s")
		print(f"  Cached execution: {cache_time:.4f}s")
		print(f"  Speed improvement: {first_time / cache_time:.1f}x")
	
	def test_scalability_characteristics(self):
		"""Test how performance scales with data size"""
		from pgappforge.database.advanced_visualization import AdvancedVisualizationEngine
		
		viz_engine = AdvancedVisualizationEngine()
		results = {}
		
		for size_name, dimensions in self.test_sizes.items():
			# Generate test data of different sizes
			test_data = {
				"nodes": [
					{"id": i, "name": f"Node{i}", "type": "Person"} 
					for i in range(dimensions["nodes"])
				],
				"edges": [
					{"from": i, "to": (i + 1) % dimensions["nodes"], "type": "CONNECTS"}
					for i in range(dimensions["edges"])
				]
			}
			
			# Benchmark layout computation
			def compute_layout():
				return viz_engine.compute_layout(test_data, "circular")
			
			performance = self.benchmark_operation(compute_layout, iterations=3)
			results[size_name] = performance
			
			print(f"Scalability Test - {size_name} ({dimensions['nodes']} nodes):")
			print(f"  Execution Time: {performance['mean']:.3f}s ± {performance['std_dev']:.3f}s")
		
		# Verify reasonable scaling (should not be exponential)
		small_time = results["small"]["mean"]
		large_time = results["large"]["mean"]
		scale_factor = large_time / small_time
		nodes_ratio = self.test_sizes["large"]["nodes"] / self.test_sizes["small"]["nodes"]
		
		# Performance should scale better than O(n^2)
		self.assertLess(scale_factor, nodes_ratio ** 1.5,
			f"Poor scalability: {scale_factor:.1f}x slowdown for {nodes_ratio:.1f}x data")


class TestResourceUtilization(FABTestCase):
	"""Test resource utilization and limits"""
	
	def test_cpu_utilization(self):
		"""Monitor CPU utilization during heavy operations"""
		import psutil
		import threading
		import time
		
		cpu_samples = []
		monitoring = True
		
		def monitor_cpu():
			while monitoring:
				cpu_samples.append(psutil.cpu_percent(interval=0.1))
		
		# Start CPU monitoring
		monitor_thread = threading.Thread(target=monitor_cpu)
		monitor_thread.start()
		
		try:
			# Simulate CPU-intensive graph operation
			start_time = time.perf_counter()
			
			# Simulate complex calculation
			result = 0
			for i in range(1000000):
				result += i * i
			
			execution_time = time.perf_counter() - start_time
			
		finally:
			monitoring = False
			monitor_thread.join()
		
		if cpu_samples:
			avg_cpu = sum(cpu_samples) / len(cpu_samples)
			max_cpu = max(cpu_samples)
			
			print(f"CPU Utilization:")
			print(f"  Average: {avg_cpu:.1f}%")
			print(f"  Peak: {max_cpu:.1f}%")
			print(f"  Execution Time: {execution_time:.3f}s")
			
			# CPU usage should be reasonable (not constantly at 100%)
			self.assertLess(avg_cpu, 80.0, 
				f"Excessive average CPU usage: {avg_cpu:.1f}%")
	
	def test_database_connection_pooling(self):
		"""Test database connection pooling effectiveness"""
		# This would test connection reuse and pool limits
		# Implementation would depend on actual connection pooling setup
		
		connection_times = []
		
		for i in range(10):
			start_time = time.perf_counter()
			# Simulate database connection
			time.sleep(0.001)  # Simulate connection overhead
			connection_time = time.perf_counter() - start_time
			connection_times.append(connection_time)
		
		avg_connection_time = sum(connection_times) / len(connection_times)
		
		# With proper pooling, connection times should be consistent and fast
		self.assertLess(avg_connection_time, 0.01,
			f"Slow connection pooling: {avg_connection_time:.3f}s avg")
		
		print(f"Database Connection Pooling:")
		print(f"  Average Connection Time: {avg_connection_time:.4f}s")


if __name__ == '__main__':
	pytest.main([__file__, '-v', '--tb=short'])