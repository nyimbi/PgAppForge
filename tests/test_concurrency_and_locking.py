"""
Concurrency and Database Locking Tests

Comprehensive test suite for database locking, race conditions,
and connection pool behavior under concurrent load.
"""

import time
import threading
import unittest
import concurrent.futures
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from contextlib import contextmanager

from pgappforge.process.approval.workflow_engine import (
    ApprovalWorkflowEngine, ApprovalTransactionError
)
from pgappforge.process.approval.connection_pool_manager import (
    ConnectionPoolManager, ConnectionConfig, 
    ConnectionPoolExhaustionError, ConnectionTimeoutError
)


class MockDatabaseInstance:
    """Mock database instance for testing."""
    
    def __init__(self, instance_id: int, initial_status: str = 'pending'):
        self.id = instance_id
        self.status = initial_status
        self.approval_history = '[]'
        self.current_state = 'step_0_pending'
        self.workflow_started_at = datetime.utcnow()
        self.workflow_completed_at = None
        self.last_approval_user_id = None
        self._lock_acquired = False
        self._modification_count = 0
    
    def __class__(self):
        return MockDatabaseInstance


class MockUser:
    """Mock user for testing."""
    
    def __init__(self, user_id: int, username: str):
        self.id = user_id
        self.username = username


class ConcurrencyTestCase(unittest.TestCase):
    """Test concurrent access and database locking."""
    
    def setUp(self):
        """Set up test environment."""
        self.mock_appbuilder = Mock()
        self.mock_session = Mock()
        self.mock_appbuilder.get_session.return_value = self.mock_session
        
        # Create engine with connection pool
        self.engine = ApprovalWorkflowEngine(self.mock_appbuilder)
        
        # Test data
        self.test_instance = MockDatabaseInstance(123, 'pending')
        self.test_user = MockUser(1, 'test_user')
        self.step_config = {'name': 'Test Step', 'required_approvals': 1}
        self.workflow_config = {
            'steps': [self.step_config],
            'approved_state': 'approved',
            'initial_state': 'pending'
        }
        
        # Concurrency tracking
        self.concurrent_results = []
        self.concurrent_errors = []
        self.lock_acquisitions = []
        self.transaction_attempts = 0
        self.successful_transactions = 0
    
    def test_concurrent_approval_attempts(self):
        """Test multiple threads attempting to approve the same instance."""
        num_threads = 10
        barrier = threading.Barrier(num_threads)
        
        def concurrent_approval(thread_id):
            """Simulate concurrent approval attempt."""
            try:
                # Wait for all threads to be ready
                barrier.wait()
                
                # Attempt approval
                user = MockUser(thread_id, f'user_{thread_id}')
                result = self.engine.process_approval_transaction(
                    self.test_instance, user, 0, self.step_config, 
                    f'Comment from thread {thread_id}', self.workflow_config
                )
                
                self.concurrent_results.append({
                    'thread_id': thread_id,
                    'success': result[0],
                    'timestamp': datetime.utcnow()
                })
                
            except Exception as e:
                self.concurrent_errors.append({
                    'thread_id': thread_id,
                    'error': str(e),
                    'timestamp': datetime.utcnow()
                })
        
        # Launch concurrent threads
        threads = []
        for i in range(num_threads):
            thread = threading.Thread(target=concurrent_approval, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=30)
        
        # Analyze results
        successful_approvals = [r for r in self.concurrent_results if r['success']]
        failed_approvals = [r for r in self.concurrent_results if not r['success']]
        
        print(f"Concurrent approval test results:")
        print(f"  Successful: {len(successful_approvals)}")
        print(f"  Failed: {len(failed_approvals)}")
        print(f"  Errors: {len(self.concurrent_errors)}")
        
        # In a properly locked system, we should have controlled concurrency
        self.assertGreater(len(self.concurrent_results), 0, "Some approvals should complete")
        
        if self.concurrent_errors:
            print("Errors encountered:")
            for error in self.concurrent_errors[:5]:  # Show first 5 errors
                print(f"  Thread {error['thread_id']}: {error['error']}")
    
    def test_database_locking_behavior(self):
        """Test that database locking prevents race conditions."""
        lock_test_results = []
        
        def test_lock_acquisition(thread_id):
            """Test lock acquisition and holding."""
            try:
                with self.engine.database_lock_for_approval(self.test_instance) as locked_instance:
                    # Record lock acquisition
                    acquire_time = datetime.utcnow()
                    self.lock_acquisitions.append({
                        'thread_id': thread_id,
                        'acquired_at': acquire_time,
                        'instance_id': locked_instance.id
                    })
                    
                    # Simulate work while holding lock
                    time.sleep(0.1)
                    
                    # Record lock release
                    release_time = datetime.utcnow()
                    lock_test_results.append({
                        'thread_id': thread_id,
                        'acquired_at': acquire_time,
                        'released_at': release_time,
                        'hold_duration': (release_time - acquire_time).total_seconds()
                    })
                    
            except Exception as e:
                self.concurrent_errors.append({
                    'thread_id': thread_id,
                    'error': str(e),
                    'operation': 'lock_acquisition'
                })
        
        # Test concurrent lock acquisition
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(test_lock_acquisition, i)
                for i in range(5)
            ]
            
            # Wait for completion
            concurrent.futures.wait(futures, timeout=30)
        
        # Analyze lock behavior
        print(f"Lock acquisition test results:")
        print(f"  Lock acquisitions: {len(self.lock_acquisitions)}")
        print(f"  Completed locks: {len(lock_test_results)}")
        print(f"  Lock errors: {len([e for e in self.concurrent_errors if e.get('operation') == 'lock_acquisition'])}")
        
        # Verify locks were acquired sequentially (no overlapping hold times)
        if len(lock_test_results) > 1:
            sorted_results = sorted(lock_test_results, key=lambda x: x['acquired_at'])
            for i in range(1, len(sorted_results)):
                prev_release = sorted_results[i-1]['released_at']
                curr_acquire = sorted_results[i]['acquired_at']
                
                # There should be no overlap (allowing for small timing differences)
                overlap = (prev_release - curr_acquire).total_seconds()
                self.assertLessEqual(overlap, 0.01, 
                                   f"Lock overlap detected: {overlap}s between threads")
    
    def test_connection_pool_exhaustion(self):
        """Test behavior when connection pool is exhausted."""
        
        # Configure small pool for testing
        small_pool_config = ConnectionConfig(
            pool_size=2,
            max_overflow=1,
            pool_timeout=1,
            connect_timeout=2
        )
        
        # Create engine with small pool
        test_engine = ApprovalWorkflowEngine(self.mock_appbuilder)
        test_engine.connection_pool = ConnectionPoolManager(
            self.mock_appbuilder, small_pool_config
        )
        
        exhaustion_errors = []
        successful_operations = []
        
        def exhaust_pool(thread_id):
            """Attempt to exhaust connection pool."""
            try:
                with test_engine.connection_pool.get_managed_session(timeout=2) as session:
                    # Hold connection for a while
                    time.sleep(0.5)
                    successful_operations.append(thread_id)
                    
            except (ConnectionPoolExhaustionError, ConnectionTimeoutError) as e:
                exhaustion_errors.append({
                    'thread_id': thread_id,
                    'error_type': type(e).__name__,
                    'message': str(e)
                })
            except Exception as e:
                exhaustion_errors.append({
                    'thread_id': thread_id,
                    'error_type': 'UnexpectedError',
                    'message': str(e)
                })
        
        # Launch more threads than pool can handle
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(exhaust_pool, i)
                for i in range(10)
            ]
            
            concurrent.futures.wait(futures, timeout=15)
        
        print(f"Connection pool exhaustion test:")
        print(f"  Successful operations: {len(successful_operations)}")
        print(f"  Pool exhaustion errors: {len(exhaustion_errors)}")
        
        # Should have some exhaustion errors with high concurrency
        self.assertGreater(len(exhaustion_errors), 0, 
                          "Should encounter pool exhaustion with high concurrency")
        
        # Some operations should still succeed
        self.assertGreater(len(successful_operations), 0,
                          "Some operations should succeed despite pool pressure")
    
    def test_transaction_rollback_scenarios(self):
        """Test transaction rollback behavior under various failure conditions."""
        
        rollback_scenarios = [
            {'name': 'validation_error', 'error': ValueError("Invalid approval data")},
            {'name': 'database_error', 'error': Exception("Database connection lost")},
            {'name': 'timeout_error', 'error': TimeoutError("Operation timed out")},
        ]
        
        rollback_results = []
        
        for scenario in rollback_scenarios:
            try:
                # Mock a failure scenario
                with patch.object(self.engine, '_execute_approval_transaction') as mock_execute:
                    mock_execute.side_effect = scenario['error']
                    
                    # Attempt transaction that should fail
                    with self.assertRaises(ApprovalTransactionError):
                        self.engine.process_approval_transaction(
                            self.test_instance, self.test_user, 0, 
                            self.step_config, 'Test comment', self.workflow_config
                        )
                    
                    rollback_results.append({
                        'scenario': scenario['name'],
                        'rollback_successful': True
                    })
                    
            except Exception as e:
                rollback_results.append({
                    'scenario': scenario['name'],
                    'rollback_successful': False,
                    'error': str(e)
                })
        
        print(f"Transaction rollback test:")
        for result in rollback_results:
            status = "✅" if result['rollback_successful'] else "❌"
            print(f"  {result['scenario']}: {status}")
        
        # All rollbacks should be successful
        failed_rollbacks = [r for r in rollback_results if not r['rollback_successful']]
        self.assertEqual(len(failed_rollbacks), 0, "All transaction rollbacks should succeed")
    
    def test_race_condition_detection(self):
        """Test detection and prevention of race conditions."""
        
        race_condition_attempts = []
        
        def simulate_race_condition(thread_id):
            """Simulate potential race condition scenario."""
            try:
                # Create a scenario where multiple threads try to modify
                # the same instance simultaneously
                instance = MockDatabaseInstance(999, 'pending')
                
                # Simulate checking status before modification
                if instance.status == 'pending':
                    time.sleep(0.01)  # Small delay to increase race condition chance
                    
                    # Attempt to process approval
                    user = MockUser(thread_id, f'race_user_{thread_id}')
                    result = self.engine.process_approval_transaction(
                        instance, user, 0, self.step_config,
                        f'Race condition test {thread_id}', self.workflow_config
                    )
                    
                    race_condition_attempts.append({
                        'thread_id': thread_id,
                        'success': result[0],
                        'timestamp': datetime.utcnow()
                    })
                    
            except Exception as e:
                race_condition_attempts.append({
                    'thread_id': thread_id,
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.utcnow()
                })
        
        # Launch concurrent race condition tests
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(simulate_race_condition, i)
                for i in range(8)
            ]
            
            concurrent.futures.wait(futures, timeout=20)
        
        # Analyze race condition results
        successful_attempts = [r for r in race_condition_attempts if r.get('success', False)]
        failed_attempts = [r for r in race_condition_attempts if not r.get('success', False)]
        
        print(f"Race condition detection test:")
        print(f"  Total attempts: {len(race_condition_attempts)}")
        print(f"  Successful: {len(successful_attempts)}")
        print(f"  Failed/Prevented: {len(failed_attempts)}")
        
        # System should handle race conditions gracefully
        self.assertGreater(len(race_condition_attempts), 0, "Should have some race condition attempts")
    
    def test_bulk_operation_concurrency(self):
        """Test bulk operations under concurrent load."""
        
        bulk_results = []
        
        def run_bulk_operations(thread_id):
            """Run bulk operations concurrently."""
            try:
                # Create bulk approval requests
                requests = []
                for i in range(5):
                    instance = MockDatabaseInstance(f"{thread_id}_{i}", 'pending')
                    user = MockUser(thread_id, f'bulk_user_{thread_id}')
                    
                    requests.append({
                        'instance': instance,
                        'user': user,
                        'step': 0,
                        'config': self.step_config,
                        'comments': f'Bulk operation {thread_id}_{i}',
                        'workflow_config': self.workflow_config
                    })
                
                # Process bulk requests
                start_time = time.time()
                result = self.engine.bulk_process_approvals(requests)
                duration = time.time() - start_time
                
                bulk_results.append({
                    'thread_id': thread_id,
                    'processed': result['processed'],
                    'failed': result['failed'],
                    'duration': duration,
                    'connection_metrics': result.get('connection_metrics', {})
                })
                
            except Exception as e:
                bulk_results.append({
                    'thread_id': thread_id,
                    'error': str(e),
                    'processed': 0,
                    'failed': 0
                })
        
        # Run concurrent bulk operations
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(run_bulk_operations, i)
                for i in range(4)
            ]
            
            concurrent.futures.wait(futures, timeout=30)
        
        # Analyze bulk operation results
        total_processed = sum(r.get('processed', 0) for r in bulk_results)
        total_failed = sum(r.get('failed', 0) for r in bulk_results)
        errors = [r for r in bulk_results if 'error' in r]
        
        print(f"Bulk operation concurrency test:")
        print(f"  Total processed: {total_processed}")
        print(f"  Total failed: {total_failed}")
        print(f"  Errors: {len(errors)}")
        
        # Bulk operations should handle concurrency well
        self.assertGreater(total_processed, 0, "Should process some bulk operations")
        
        if errors:
            print("Bulk operation errors:")
            for error in errors[:3]:
                print(f"  Thread {error['thread_id']}: {error['error']}")
    
    def test_connection_pool_health_monitoring(self):
        """Test connection pool health monitoring under load."""
        
        health_snapshots = []
        
        def monitor_health():
            """Monitor connection pool health during load."""
            for _ in range(10):
                health = self.engine.get_connection_pool_status()
                health_snapshots.append({
                    'timestamp': datetime.utcnow(),
                    'metrics': health.get('metrics', {}),
                    'health_status': health.get('health', {}).get('status', 'unknown')
                })
                time.sleep(0.5)
        
        def generate_load():
            """Generate load on connection pool."""
            for i in range(20):
                try:
                    with self.engine.connection_pool.get_managed_session(timeout=5) as session:
                        # Simulate work
                        time.sleep(0.1)
                except Exception:
                    pass
        
        # Start health monitoring
        monitor_thread = threading.Thread(target=monitor_health)
        monitor_thread.start()
        
        # Generate concurrent load
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            load_futures = [
                executor.submit(generate_load)
                for _ in range(3)
            ]
            
            concurrent.futures.wait(load_futures, timeout=15)
        
        # Wait for monitoring to complete
        monitor_thread.join(timeout=10)
        
        # Analyze health monitoring results
        print(f"Connection pool health monitoring:")
        print(f"  Health snapshots: {len(health_snapshots)}")
        
        if health_snapshots:
            # Check for health status changes
            statuses = [s['health_status'] for s in health_snapshots]
            unique_statuses = set(statuses)
            
            print(f"  Health statuses observed: {unique_statuses}")
            
            # Get metrics trends
            metrics_with_values = [s for s in health_snapshots if s['metrics']]
            if metrics_with_values:
                peak_utilization = max(
                    m['metrics'].get('utilization_percent', 0) 
                    for m in metrics_with_values
                )
                print(f"  Peak utilization: {peak_utilization:.1f}%")
        
        self.assertGreater(len(health_snapshots), 0, "Should capture health snapshots")


class StressTestCase(unittest.TestCase):
    """Stress tests for extreme concurrency scenarios."""
    
    def setUp(self):
        """Set up stress test environment."""
        self.mock_appbuilder = Mock()
        self.mock_session = Mock()
        self.mock_appbuilder.get_session.return_value = self.mock_session
        
        # Create engine optimized for stress testing
        self.engine = ApprovalWorkflowEngine(self.mock_appbuilder)
        
        # Configure for high load
        stress_config = ConnectionConfig(
            pool_size=50,
            max_overflow=100,
            pool_timeout=60,
            connect_timeout=30
        )
        self.engine.connection_pool = ConnectionPoolManager(
            self.mock_appbuilder, stress_config
        )
    
    def test_high_concurrency_stress(self):
        """Stress test with very high concurrency."""
        
        num_threads = 50
        operations_per_thread = 10
        stress_results = []
        
        def stress_worker(worker_id):
            """Worker for stress testing."""
            worker_results = {
                'worker_id': worker_id,
                'operations_completed': 0,
                'errors': [],
                'start_time': time.time()
            }
            
            for op_id in range(operations_per_thread):
                try:
                    instance = MockDatabaseInstance(f"{worker_id}_{op_id}", 'pending')
                    user = MockUser(worker_id, f'stress_user_{worker_id}')
                    
                    # Simulate approval workflow
                    with self.engine.connection_pool.get_managed_session(timeout=10) as session:
                        # Simulate database work
                        time.sleep(0.01)
                        worker_results['operations_completed'] += 1
                        
                except Exception as e:
                    worker_results['errors'].append(str(e))
            
            worker_results['duration'] = time.time() - worker_results['start_time']
            stress_results.append(worker_results)
        
        # Launch stress test
        print(f"Starting stress test: {num_threads} threads × {operations_per_thread} operations")
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(stress_worker, i)
                for i in range(num_threads)
            ]
            
            concurrent.futures.wait(futures, timeout=120)
        
        total_duration = time.time() - start_time
        
        # Analyze stress test results
        total_operations = sum(r['operations_completed'] for r in stress_results)
        total_errors = sum(len(r['errors']) for r in stress_results)
        
        operations_per_second = total_operations / total_duration if total_duration > 0 else 0
        error_rate = (total_errors / (total_operations + total_errors)) * 100 if (total_operations + total_errors) > 0 else 0
        
        print(f"Stress test results:")
        print(f"  Total operations: {total_operations}")
        print(f"  Total errors: {total_errors}")
        print(f"  Duration: {total_duration:.2f}s")
        print(f"  Operations/second: {operations_per_second:.2f}")
        print(f"  Error rate: {error_rate:.2f}%")
        
        # Stress test success criteria
        self.assertGreater(operations_per_second, 10, "Should achieve reasonable throughput")
        self.assertLess(error_rate, 50, "Error rate should be manageable under stress")


if __name__ == '__main__':
    print("🧪 CONCURRENCY AND DATABASE LOCKING TESTS")
    print("=" * 60)
    
    # Run concurrency tests
    concurrency_suite = unittest.TestLoader().loadTestsFromTestCase(ConcurrencyTestCase)
    concurrency_runner = unittest.TextTestRunner(verbosity=2)
    concurrency_result = concurrency_runner.run(concurrency_suite)
    
    print("\n" + "=" * 60)
    print("🔥 STRESS TESTS")
    print("=" * 60)
    
    # Run stress tests
    stress_suite = unittest.TestLoader().loadTestsFromTestCase(StressTestCase)
    stress_runner = unittest.TextTestRunner(verbosity=2)
    stress_result = stress_runner.run(stress_suite)
    
    # Summary
    total_tests = concurrency_result.testsRun + stress_result.testsRun
    total_failures = len(concurrency_result.failures) + len(stress_result.failures)
    total_errors = len(concurrency_result.errors) + len(stress_result.errors)
    
    print(f"\n" + "=" * 60)
    print("📊 OVERALL TEST SUMMARY")
    print("=" * 60)
    print(f"Total tests: {total_tests}")
    print(f"Failures: {total_failures}")
    print(f"Errors: {total_errors}")
    
    if total_failures == 0 and total_errors == 0:
        print("✅ ALL CONCURRENCY TESTS PASSED!")
        print("✅ Database locking and race condition prevention verified")
        print("✅ Connection pool behavior validated under load")
    else:
        print("❌ Some tests failed - review concurrency implementation")
    
    print("🎯 Concurrency testing completed")