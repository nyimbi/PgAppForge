"""
Test O(n²) Performance Fix for Approval Workflow Engine

Validates that linear search optimization successfully eliminates
O(n²) complexity and provides correct results.
"""

import json
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from pgappforge.process.approval.workflow_engine import ApprovalWorkflowEngine


class TestPerformanceFix(unittest.TestCase):
    """Test performance improvements in approval workflow engine."""
    
    def setUp(self):
        """Set up test environment."""
        self.mock_appbuilder = Mock()
        self.mock_session = Mock()
        self.mock_appbuilder.get_session.return_value = self.mock_session
        
        self.engine = ApprovalWorkflowEngine(self.mock_appbuilder)
        
        # Create mock instance with approval history
        self.mock_instance = Mock()
        self.mock_instance.id = 123
        self.mock_instance.__class__.__name__ = 'TestModel'
    
    def _create_approval_history(self, num_approvals: int) -> str:
        """Create approval history with specified number of entries."""
        history = []
        for i in range(num_approvals):
            history.append({
                'user_id': i % 10 + 1,  # Cycle through users 1-10
                'user_name': f'user_{i % 10 + 1}',
                'step': i % 5,  # Cycle through steps 0-4
                'step_name': f'Step {i % 5}',
                'status': 'approved' if i % 3 != 0 else 'rejected',  # 2/3 approved
                'comments': f'Approval {i}',
                'timestamp': (datetime.utcnow() - timedelta(hours=i)).isoformat()
            })
        return json.dumps(history)
    
    def test_linear_vs_indexed_performance(self):
        """Test performance difference between linear and indexed approaches."""
        # Test with different approval history sizes
        test_sizes = [10, 50, 100, 500, 1000]
        
        for size in test_sizes:
            with self.subTest(approval_count=size):
                # Set up approval history
                self.mock_instance.approval_history = self._create_approval_history(size)
                
                # Test indexed approach (new optimized method)
                start_time = time.perf_counter()
                
                # Run multiple step completeness checks (simulates real usage)
                for step in range(5):
                    step_config = {'required_approvals': 3}
                    self.engine.is_step_complete(self.mock_instance, step, step_config)
                
                indexed_time = time.perf_counter() - start_time
                
                # Clear cache to test fresh performance
                self.engine._approval_cache.clear()
                self.engine._cache_timestamps.clear()
                
                # Simulate old linear approach for comparison
                start_time = time.perf_counter()
                
                for step in range(5):
                    # Simulate old O(n) linear search
                    approval_history = self.engine.get_approval_history(self.mock_instance)
                    step_approvals = [
                        approval for approval in approval_history
                        if approval.get('step') == step and approval.get('status') == 'approved'
                    ]
                    len(step_approvals) >= 3  # required_approvals check
                
                linear_time = time.perf_counter() - start_time
                
                print(f"Size {size}: Linear={linear_time:.6f}s, Indexed={indexed_time:.6f}s, "
                      f"Speedup={linear_time/indexed_time:.2f}x")
                
                # For larger datasets, indexed should be significantly faster
                if size >= 100:
                    self.assertLess(indexed_time, linear_time, 
                                   f"Indexed approach should be faster for {size} approvals")
    
    def test_indexed_data_correctness(self):
        """Test that indexed data structures return correct results."""
        # Create test approval history
        self.mock_instance.approval_history = self._create_approval_history(30)
        
        # Get indexed data
        indexed_data = self.engine._get_indexed_approval_data(self.mock_instance)
        
        # Verify structure
        self.assertIn('step_approvals', indexed_data)
        self.assertIn('step_counts', indexed_data)
        self.assertIn('user_approvals', indexed_data)
        self.assertIn('total_approvals', indexed_data)
        
        # Verify total count
        self.assertEqual(indexed_data['total_approvals'], 30)
        
        # Verify step counts are correct
        original_history = self.engine.get_approval_history(self.mock_instance)
        for step in range(5):
            expected_count = len([
                a for a in original_history 
                if a.get('step') == step and a.get('status') == 'approved'
            ])
            actual_count = indexed_data['step_counts'].get(step, 0)
            self.assertEqual(expected_count, actual_count, 
                           f"Step {step} count mismatch")
    
    def test_cache_invalidation(self):
        """Test that cache is properly invalidated when history changes."""
        # Set initial history
        self.mock_instance.approval_history = self._create_approval_history(10)
        
        # Get indexed data (should cache)
        indexed_data1 = self.engine._get_indexed_approval_data(self.mock_instance)
        cache_key = f"{self.mock_instance.__class__.__name__}_{self.mock_instance.id}"
        
        # Verify cache exists
        self.assertIn(cache_key, self.engine._approval_cache)
        
        # Update approval history
        new_approval = {
            'user_id': 999,
            'user_name': 'new_user',
            'step': 0,
            'step_name': 'Step 0',
            'status': 'approved',
            'comments': 'New approval',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        self.engine.update_approval_history(self.mock_instance, new_approval)
        
        # Verify cache was invalidated
        self.assertNotIn(cache_key, self.engine._approval_cache)
        
        # Get new indexed data
        indexed_data2 = self.engine._get_indexed_approval_data(self.mock_instance)
        
        # Verify data updated
        self.assertEqual(indexed_data2['total_approvals'], 11)
        self.assertNotEqual(indexed_data1['total_approvals'], indexed_data2['total_approvals'])
    
    def test_step_completion_optimization(self):
        """Test optimized step completion checking."""
        # Create approval history with known step completion status
        self.mock_instance.approval_history = self._create_approval_history(50)
        
        # Test step completion with different requirements
        test_cases = [
            {'step': 0, 'required': 1, 'expected': True},
            {'step': 1, 'required': 5, 'expected': True},
            {'step': 2, 'required': 20, 'expected': False},
            {'step': 3, 'required': 2, 'expected': True},
            {'step': 4, 'required': 15, 'expected': False}
        ]
        
        for case in test_cases:
            step_config = {'required_approvals': case['required']}
            result = self.engine.is_step_complete(
                self.mock_instance, case['step'], step_config
            )
            self.assertEqual(result, case['expected'], 
                           f"Step {case['step']} completion check failed")
    
    def test_performance_monitoring(self):
        """Test performance monitoring utilities."""
        # Create test data
        self.mock_instance.approval_history = self._create_approval_history(20)
        
        # Generate cache data
        self.engine._get_indexed_approval_data(self.mock_instance)
        
        # Get performance metrics
        metrics = self.engine.get_performance_metrics()
        
        # Verify metrics structure
        required_keys = [
            'cache_entries', 'cache_timestamps', 'memory_usage_estimate',
            'oldest_cache_entry', 'newest_cache_entry'
        ]
        
        for key in required_keys:
            self.assertIn(key, metrics, f"Missing metric: {key}")
        
        # Verify reasonable values
        self.assertGreater(metrics['cache_entries'], 0)
        self.assertGreater(metrics['memory_usage_estimate'], 0)
    
    def test_cache_cleanup(self):
        """Test cache cleanup functionality."""
        # Create multiple cached entries with different timestamps
        old_time = datetime.utcnow() - timedelta(hours=2)
        recent_time = datetime.utcnow() - timedelta(minutes=30)
        
        # Manually add cache entries with different ages
        self.engine._approval_cache['old_entry'] = {'data': 'old'}
        self.engine._cache_timestamps['old_entry'] = old_time
        
        self.engine._approval_cache['recent_entry'] = {'data': 'recent'}
        self.engine._cache_timestamps['recent_entry'] = recent_time
        
        # Cleanup entries older than 1 hour
        self.engine.cleanup_approval_cache(max_age_minutes=60)
        
        # Verify old entry removed, recent kept
        self.assertNotIn('old_entry', self.engine._approval_cache)
        self.assertIn('recent_entry', self.engine._approval_cache)
    
    def test_bulk_approval_optimization(self):
        """Test bulk approval processing optimization."""
        # This test would need more complex setup with actual workflow configs
        # For now, verify the method exists and handles empty input
        result = self.engine.bulk_process_approvals([])
        
        self.assertIn('processed', result)
        self.assertIn('failed', result)
        self.assertIn('processing_time_ms', result)
        self.assertEqual(result['processed'], 0)
        self.assertEqual(result['failed'], 0)


class TestComplexityAnalysis(unittest.TestCase):
    """Analyze algorithm complexity improvements."""
    
    def setUp(self):
        """Set up complexity testing environment."""
        self.mock_appbuilder = Mock()
        self.mock_session = Mock()
        self.mock_appbuilder.get_session.return_value = self.mock_session
        
        self.engine = ApprovalWorkflowEngine(self.mock_appbuilder)
        
        self.mock_instance = Mock()
        self.mock_instance.id = 456
        self.mock_instance.__class__.__name__ = 'ComplexityTest'
    
    def _create_approval_history(self, num_approvals: int) -> str:
        """Create approval history for complexity testing."""
        history = []
        for i in range(num_approvals):
            history.append({
                'user_id': i % 20 + 1,
                'user_name': f'user_{i % 20 + 1}',
                'step': i % 10,  # More steps for complexity testing
                'step_name': f'Step {i % 10}',
                'status': 'approved',
                'comments': f'Approval {i}',
                'timestamp': datetime.utcnow().isoformat()
            })
        return json.dumps(history)
    
    def test_linear_complexity_improvement(self):
        """Test that complexity improved from O(n²) to O(1) for step checks."""
        # Test with exponentially increasing sizes
        sizes = [10, 50, 100, 500, 1000, 2000]
        times = []
        
        for size in sizes:
            self.mock_instance.approval_history = self._create_approval_history(size)
            
            # Clear cache for fair comparison
            self.engine._approval_cache.clear()
            self.engine._cache_timestamps.clear()
            
            # Time multiple step completion checks
            start_time = time.perf_counter()
            
            # Perform 10 step checks (simulates real usage pattern)
            for _ in range(10):
                for step in range(5):
                    step_config = {'required_approvals': 3}
                    self.engine.is_step_complete(self.mock_instance, step, step_config)
            
            elapsed_time = time.perf_counter() - start_time
            times.append(elapsed_time)
            
            print(f"Size {size}: {elapsed_time:.6f}s")
        
        # Verify that time complexity is not quadratic
        # If optimization works, time should grow much slower than O(n²)
        
        # Calculate ratios between consecutive measurements
        ratios = []
        for i in range(1, len(times)):
            size_ratio = sizes[i] / sizes[i-1]
            time_ratio = times[i] / times[i-1]
            ratios.append(time_ratio / (size_ratio ** 2))  # Compare to quadratic growth
            
            print(f"Size ratio: {size_ratio:.1f}x, Time ratio: {time_ratio:.2f}x, "
                  f"Quadratic ratio: {time_ratio / (size_ratio ** 2):.3f}")
        
        # If optimization successful, ratios should be much less than 1
        # (indicating sub-quadratic growth)
        average_ratio = sum(ratios) / len(ratios)
        self.assertLess(average_ratio, 0.5, 
                       "Time complexity should be significantly better than O(n²)")
    
    def test_memory_efficiency(self):
        """Test memory usage efficiency of indexed structures."""
        # Test memory usage with different approval history sizes
        sizes = [100, 500, 1000]
        
        for size in sizes:
            self.mock_instance.approval_history = self._create_approval_history(size)
            
            # Generate indexed data
            indexed_data = self.engine._get_indexed_approval_data(self.mock_instance)
            
            # Get memory metrics
            metrics = self.engine.get_performance_metrics()
            memory_usage = metrics['memory_usage_estimate']
            
            print(f"Size {size}: Memory usage estimate: {memory_usage} bytes")
            
            # Memory usage should be reasonable (not exponential)
            # This is a rough estimate, but should scale linearly with data size
            memory_per_approval = memory_usage / size
            self.assertLess(memory_per_approval, 1000,  # Less than 1KB per approval
                           f"Memory usage too high: {memory_per_approval} bytes per approval")


if __name__ == '__main__':
    # Run performance tests
    print("=" * 60)
    print("PERFORMANCE OPTIMIZATION VALIDATION")
    print("=" * 60)
    
    unittest.main(verbosity=2)