"""
Performance Tests for Process Engine.

Tests performance characteristics, load handling, concurrency,
and resource utilization of the business process engine.
"""

import unittest
import asyncio
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from pgappforge.process.models.process_models import (
    ProcessDefinition, ProcessInstance, ProcessStep, ProcessInstanceStatus
)
from pgappforge.process.engine.process_engine import ProcessEngine
from pgappforge.process.analytics.dashboard import ProcessAnalytics
from pgappforge.process.async.task_monitor import TaskMonitor


class TestProcessEnginePerformance(unittest.TestCase):
    """Test process engine performance characteristics."""
    
    def setUp(self):
        """Set up performance test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 20,
            'max_overflow': 30
        }
        
        with self.app.app_context():
            from pgappforge import db
            db.init_app(self.app)
            db.create_all()
            
            self.engine = ProcessEngine()
            self.create_test_definitions()
    
    def create_test_definitions(self):
        """Create test process definitions for performance testing."""
        from pgappforge import db
        
        # Simple linear process
        self.simple_definition = ProcessDefinition(
            name="Simple Performance Test",
            description="Simple linear process for performance testing",
            version="1.0",
            category="Performance",
            status="active",
            tenant_id=1,
            process_graph={
                "nodes": [
                    {"id": "start", "type": "event", "subtype": "start", "name": "Start"},
                    {"id": "task1", "type": "task", "subtype": "service", "name": "Task 1"},
                    {"id": "task2", "type": "task", "subtype": "service", "name": "Task 2"},
                    {"id": "end", "type": "event", "subtype": "end", "name": "End"}
                ],
                "edges": [
                    {"source": "start", "target": "task1"},
                    {"source": "task1", "target": "task2"},
                    {"source": "task2", "target": "end"}
                ]
            }
        )
        
        # Complex branching process
        self.complex_definition = ProcessDefinition(
            name="Complex Performance Test",
            description="Complex branching process for performance testing",
            version="1.0",
            category="Performance",
            status="active",
            tenant_id=1,
            process_graph={
                "nodes": [
                    {"id": "start", "type": "event", "subtype": "start", "name": "Start"},
                    {"id": "gateway1", "type": "gateway", "subtype": "parallel", "name": "Split"},
                    *[{"id": f"task_{i}", "type": "task", "subtype": "service", "name": f"Task {i}"} 
                      for i in range(1, 6)],
                    {"id": "gateway2", "type": "gateway", "subtype": "parallel", "name": "Join"},
                    {"id": "end", "type": "event", "subtype": "end", "name": "End"}
                ],
                "edges": [
                    {"source": "start", "target": "gateway1"},
                    *[{"source": "gateway1", "target": f"task_{i}"} for i in range(1, 6)],
                    *[{"source": f"task_{i}", "target": "gateway2"} for i in range(1, 6)],
                    {"source": "gateway2", "target": "end"}
                ]
            }
        )
        
        db.session.add_all([self.simple_definition, self.complex_definition])
        db.session.commit()
    
    @patch('pgappforge.process.engine.executors.ServiceExecutor.execute')
    def test_single_process_execution_time(self, mock_execute):
        """Test execution time for single process instance."""
        with self.app.app_context():
            # Mock fast executor response
            mock_execute.return_value = asyncio.Future()
            mock_execute.return_value.set_result({"result": "success"})
            
            start_time = time.time()
            
            instance = asyncio.run(
                self.engine.start_process(
                    definition_id=self.simple_definition.id,
                    input_data={"test": "performance"}
                )
            )
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            # Should complete within reasonable time (adjust threshold as needed)
            self.assertLess(execution_time, 1.0, "Single process execution took too long")
            self.assertIsNotNone(instance)
    
    @patch('pgappforge.process.engine.executors.ServiceExecutor.execute')
    def test_concurrent_process_creation(self, mock_execute):
        """Test concurrent process instance creation."""
        with self.app.app_context():
            # Mock executor response
            mock_execute.return_value = asyncio.Future()
            mock_execute.return_value.set_result({"result": "success"})
            
            num_processes = 50
            start_time = time.time()
            
            # Create processes concurrently
            async def create_processes():
                tasks = []
                for i in range(num_processes):
                    task = self.engine.start_process(
                        definition_id=self.simple_definition.id,
                        input_data={"test": f"concurrent_{i}"}
                    )
                    tasks.append(task)
                
                return await asyncio.gather(*tasks)
            
            instances = asyncio.run(create_processes())
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # Verify all instances created
            self.assertEqual(len(instances), num_processes)
            
            # Performance benchmark (adjust as needed)
            avg_time_per_process = total_time / num_processes
            self.assertLess(avg_time_per_process, 0.1, 
                          f"Average process creation time too high: {avg_time_per_process:.3f}s")
            
            print(f"Created {num_processes} processes in {total_time:.3f}s "
                  f"(avg: {avg_time_per_process:.3f}s per process)")
    
    @patch('pgappforge.process.engine.executors.ServiceExecutor.execute')
    def test_complex_process_performance(self, mock_execute):
        """Test performance of complex branching processes."""
        with self.app.app_context():
            # Mock executor with slight delay to simulate real work
            async def mock_execute_with_delay(*args, **kwargs):
                await asyncio.sleep(0.01)  # 10ms delay
                return {"result": "success"}
            
            mock_execute.side_effect = mock_execute_with_delay
            
            start_time = time.time()
            
            instance = asyncio.run(
                self.engine.start_process(
                    definition_id=self.complex_definition.id,
                    input_data={"test": "complex_performance"}
                )
            )
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            # Complex process should still complete in reasonable time
            self.assertLess(execution_time, 5.0, "Complex process execution took too long")
            self.assertIsNotNone(instance)
            
            print(f"Complex process completed in {execution_time:.3f}s")
    
    def test_memory_usage_scaling(self):
        """Test memory usage with increasing number of processes."""
        with self.app.app_context():
            import psutil
            import os
            
            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
            
            # Create multiple process instances
            instances = []
            for i in range(100):
                instance = ProcessInstance(
                    definition_id=self.simple_definition.id,
                    tenant_id=1,
                    status=ProcessInstanceStatus.RUNNING.value,
                    input_data={"test": f"memory_{i}"}
                )
                instances.append(instance)
            
            from pgappforge import db
            db.session.add_all(instances)
            db.session.commit()
            
            final_memory = process.memory_info().rss / 1024 / 1024  # MB
            memory_increase = final_memory - initial_memory
            
            # Memory increase should be reasonable (adjust threshold as needed)
            self.assertLess(memory_increase, 50, 
                          f"Memory usage increased too much: {memory_increase:.2f}MB")
            
            print(f"Memory usage increased by {memory_increase:.2f}MB for 100 process instances")
    
    def test_database_connection_pooling(self):
        """Test database connection handling under load."""
        with self.app.app_context():
            from pgappforge import db
            
            def create_and_query_instance():
                """Create instance and query database."""
                instance = ProcessInstance(
                    definition_id=self.simple_definition.id,
                    tenant_id=1,
                    status=ProcessInstanceStatus.RUNNING.value,
                    input_data={"test": "db_pool"}
                )
                db.session.add(instance)
                db.session.commit()
                
                # Query the instance back
                queried = db.session.query(ProcessInstance).filter_by(id=instance.id).first()
                return queried is not None
            
            # Execute multiple database operations concurrently
            start_time = time.time()
            
            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(create_and_query_instance) for _ in range(50)]
                results = [future.result() for future in as_completed(futures)]
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # All operations should succeed
            self.assertTrue(all(results), "Some database operations failed")
            
            # Should complete in reasonable time
            self.assertLess(total_time, 10.0, "Database operations took too long")
            
            print(f"50 concurrent database operations completed in {total_time:.3f}s")
    
    def test_analytics_performance(self):
        """Test performance of analytics calculations."""
        with self.app.app_context():
            from pgappforge import db
            
            # Create test data
            instances = []
            for i in range(1000):
                instance = ProcessInstance(
                    definition_id=self.simple_definition.id,
                    tenant_id=1,
                    status=ProcessInstanceStatus.COMPLETED.value,
                    input_data={"test": f"analytics_{i}"},
                    started_at=datetime.utcnow() - timedelta(days=i % 30),
                    completed_at=datetime.utcnow() - timedelta(days=i % 30, hours=-1)
                )
                instances.append(instance)
            
            db.session.add_all(instances)
            db.session.commit()
            
            # Test analytics performance
            analytics = ProcessAnalytics()
            
            start_time = time.time()
            dashboard_data = analytics.get_dashboard_metrics(30)
            end_time = time.time()
            
            calculation_time = end_time - start_time
            
            # Analytics should complete quickly even with lots of data
            self.assertLess(calculation_time, 5.0, "Analytics calculation took too long")
            self.assertIsInstance(dashboard_data, dict)
            self.assertIn('overview', dashboard_data)
            
            print(f"Analytics calculated for 1000 instances in {calculation_time:.3f}s")


class TestProcessEngineStress(unittest.TestCase):
    """Stress tests for process engine."""
    
    def setUp(self):
        """Set up stress test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            from pgappforge import db
            db.init_app(self.app)
            db.create_all()
            
            self.engine = ProcessEngine()
            self.create_stress_test_definition()
    
    def create_stress_test_definition(self):
        """Create process definition for stress testing."""
        from pgappforge import db
        
        # Process with many steps for stress testing
        nodes = [{"id": "start", "type": "event", "subtype": "start", "name": "Start"}]
        edges = []
        
        # Create many sequential tasks
        for i in range(1, 21):  # 20 tasks
            nodes.append({
                "id": f"task_{i}",
                "type": "task",
                "subtype": "service",
                "name": f"Task {i}"
            })
            
            if i == 1:
                edges.append({"source": "start", "target": f"task_{i}"})
            else:
                edges.append({"source": f"task_{i-1}", "target": f"task_{i}"})
        
        nodes.append({"id": "end", "type": "event", "subtype": "end", "name": "End"})
        edges.append({"source": "task_20", "target": "end"})
        
        self.stress_definition = ProcessDefinition(
            name="Stress Test Process",
            description="Process with many steps for stress testing",
            version="1.0",
            category="Stress",
            status="active",
            tenant_id=1,
            process_graph={"nodes": nodes, "edges": edges}
        )
        
        db.session.add(self.stress_definition)
        db.session.commit()
    
    @patch('pgappforge.process.engine.executors.ServiceExecutor.execute')
    def test_high_volume_process_creation(self, mock_execute):
        """Test creating large numbers of process instances."""
        with self.app.app_context():
            # Mock fast execution
            mock_execute.return_value = asyncio.Future()
            mock_execute.return_value.set_result({"result": "success"})
            
            num_processes = 500
            batch_size = 50
            
            start_time = time.time()
            total_created = 0
            
            # Create processes in batches to avoid memory issues
            for batch_start in range(0, num_processes, batch_size):
                batch_end = min(batch_start + batch_size, num_processes)
                batch_tasks = []
                
                for i in range(batch_start, batch_end):
                    task = self.engine.start_process(
                        definition_id=self.stress_definition.id,
                        input_data={"batch": batch_start // batch_size, "index": i}
                    )
                    batch_tasks.append(task)
                
                batch_instances = asyncio.run(asyncio.gather(*batch_tasks))
                total_created += len(batch_instances)
                
                print(f"Created batch {batch_start//batch_size + 1}: {len(batch_instances)} processes")
            
            end_time = time.time()
            total_time = end_time - start_time
            
            self.assertEqual(total_created, num_processes)
            
            # Performance metrics
            processes_per_second = num_processes / total_time
            print(f"Stress test: Created {num_processes} processes in {total_time:.3f}s "
                  f"({processes_per_second:.1f} processes/second)")
            
            # Should maintain reasonable throughput
            self.assertGreater(processes_per_second, 10, "Process creation rate too low")
    
    def test_long_running_process_stability(self):
        """Test stability with long-running processes."""
        with self.app.app_context():
            from pgappforge import db
            
            # Create long-running process instances
            long_running_instances = []
            
            for i in range(100):
                instance = ProcessInstance(
                    definition_id=self.stress_definition.id,
                    tenant_id=1,
                    status=ProcessInstanceStatus.RUNNING.value,
                    input_data={"test": f"long_running_{i}"},
                    started_at=datetime.utcnow() - timedelta(hours=i % 24)
                )
                long_running_instances.append(instance)
            
            db.session.add_all(long_running_instances)
            db.session.commit()
            
            # Simulate monitoring and health checks
            for _ in range(10):  # 10 monitoring cycles
                start_time = time.time()
                
                # Query running processes
                running_count = db.session.query(ProcessInstance).filter_by(
                    status=ProcessInstanceStatus.RUNNING.value
                ).count()
                
                # Get process statistics
                analytics = ProcessAnalytics()
                real_time_metrics = analytics._get_real_time_metrics(1)
                
                end_time = time.time()
                monitoring_time = end_time - start_time
                
                # Monitoring should remain fast even with many processes
                self.assertLess(monitoring_time, 1.0, "Process monitoring too slow")
                self.assertEqual(running_count, 100)
                self.assertIsInstance(real_time_metrics, dict)
                
                # Brief pause between monitoring cycles
                time.sleep(0.1)
            
            print("Long-running process stability test completed successfully")


class TestProcessEngineLoadTesting(unittest.TestCase):
    """Load testing for process engine components."""
    
    def setUp(self):
        """Set up load test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            from pgappforge import db
            db.init_app(self.app)
            db.create_all()
    
    def test_task_monitor_load(self):
        """Test task monitor under high load."""
        with self.app.app_context():
            from pgappforge.process.async.task_monitor import Base
            from pgappforge import db
            
            # Create task monitoring tables
            Base.metadata.create_all(db.engine)
            
            monitor = TaskMonitor()
            
            # Simulate high task load
            num_tasks = 1000
            start_time = time.time()
            
            # Record many task executions
            for i in range(num_tasks):
                task_id = f"load_test_task_{i}"
                
                # Start task
                monitor.record_task_start(task_id, "load_test.task", (), {"index": i})
                
                # Complete task (simulate success/failure)
                if i % 10 == 0:  # 10% failure rate
                    monitor.record_task_failure(task_id, "Simulated failure")
                else:
                    monitor.record_task_success(task_id, {"result": f"success_{i}"})
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # Get statistics
            stats = monitor.get_task_statistics(1)
            
            self.assertIsInstance(stats, dict)
            self.assertGreater(stats.get('total_tasks', 0), 0)
            
            tasks_per_second = num_tasks / total_time
            print(f"Task monitor load test: {num_tasks} tasks in {total_time:.3f}s "
                  f"({tasks_per_second:.1f} tasks/second)")
            
            # Should maintain reasonable performance
            self.assertGreater(tasks_per_second, 100, "Task monitoring rate too low")
    
    def test_concurrent_analytics_requests(self):
        """Test analytics system under concurrent load."""
        with self.app.app_context():
            from pgappforge import db
            
            # Create test data
            instances = []
            for i in range(500):
                instance = ProcessInstance(
                    definition_id=1,  # Assume definition exists
                    tenant_id=1,
                    status=ProcessInstanceStatus.COMPLETED.value if i % 3 != 0 else ProcessInstanceStatus.FAILED.value,
                    input_data={"test": f"analytics_{i}"},
                    started_at=datetime.utcnow() - timedelta(hours=i % 48),
                    completed_at=datetime.utcnow() - timedelta(hours=i % 48, minutes=-30)
                )
                instances.append(instance)
            
            db.session.add_all(instances)
            db.session.commit()
            
            analytics = ProcessAnalytics()
            
            def run_analytics():
                """Run analytics calculation."""
                return analytics.get_dashboard_metrics(30)
            
            # Run concurrent analytics requests
            num_requests = 20
            start_time = time.time()
            
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(run_analytics) for _ in range(num_requests)]
                results = [future.result() for future in as_completed(futures)]
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # All requests should succeed
            self.assertEqual(len(results), num_requests)
            for result in results:
                self.assertIsInstance(result, dict)
                self.assertIn('overview', result)
            
            requests_per_second = num_requests / total_time
            print(f"Analytics load test: {num_requests} concurrent requests in {total_time:.3f}s "
                  f"({requests_per_second:.1f} requests/second)")
            
            # Should handle concurrent requests efficiently
            self.assertLess(total_time, 30.0, "Concurrent analytics requests too slow")
    
    def test_process_engine_memory_leak(self):
        """Test for memory leaks in process engine."""
        with self.app.app_context():
            import psutil
            import gc
            import os
            
            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
            
            engine = ProcessEngine()
            
            # Create and destroy many process-related objects
            for iteration in range(10):
                temp_instances = []
                
                for i in range(100):
                    instance = ProcessInstance(
                        definition_id=1,
                        tenant_id=1,
                        status=ProcessInstanceStatus.COMPLETED.value,
                        input_data={"iteration": iteration, "index": i}
                    )
                    temp_instances.append(instance)
                
                # Clear references
                temp_instances.clear()
                
                # Force garbage collection
                gc.collect()
                
                # Check memory every few iterations
                if iteration % 3 == 0:
                    current_memory = process.memory_info().rss / 1024 / 1024  # MB
                    memory_increase = current_memory - initial_memory
                    print(f"Iteration {iteration}: Memory usage = {current_memory:.2f}MB "
                          f"(+{memory_increase:.2f}MB)")
            
            final_memory = process.memory_info().rss / 1024 / 1024  # MB
            total_memory_increase = final_memory - initial_memory
            
            # Memory increase should be minimal after garbage collection
            self.assertLess(total_memory_increase, 20, 
                          f"Possible memory leak detected: {total_memory_increase:.2f}MB increase")
            
            print(f"Memory leak test completed. Total increase: {total_memory_increase:.2f}MB")


if __name__ == '__main__':
    # Run performance tests
    unittest.main(verbosity=2)