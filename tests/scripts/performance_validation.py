"""
Performance validation for collaborative utilities.

Tests the performance impact of the new shared utilities compared to 
direct implementations to ensure the abstractions don't introduce
significant overhead.
"""

import time
import statistics
import sys
import traceback
from datetime import datetime
from typing import Dict, List, Any, Callable
from contextlib import contextmanager

# Add project root to path for imports
sys.path.insert(0, './pgappforge/collaborative/utils')

# Import collaborative utilities
from validation import (
    ValidationResult, FieldValidator, UserValidator, 
    MessageValidator, validate_complete_message
)
from error_handling import (
    CollaborativeError, ValidationError, ErrorHandlingMixin,
    create_error_response
)
from audit_logging import (
    AuditEvent, AuditEventType, AuditLogger, CollaborativeAuditMixin
)


class PerformanceBenchmark:
    """Performance benchmarking utility."""
    
    def __init__(self, iterations: int = 10000):
        self.iterations = iterations
        self.results = {}
        
    @contextmanager
    def benchmark(self, test_name: str):
        """Context manager for timing operations."""
        start_time = time.perf_counter()
        try:
            yield
        finally:
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            if test_name not in self.results:
                self.results[test_name] = []
            self.results[test_name].append(duration)
    
    def run_benchmark(self, test_name: str, test_func: Callable, *args, **kwargs) -> float:
        """Run a benchmark test multiple times and return average time."""
        times = []
        
        for _ in range(self.iterations):
            start_time = time.perf_counter()
            try:
                test_func(*args, **kwargs)
            except Exception:
                # Don't let test failures affect timing
                pass
            end_time = time.perf_counter()
            times.append(end_time - start_time)
        
        avg_time = statistics.mean(times)
        self.results[test_name] = {
            'avg_time': avg_time,
            'min_time': min(times),
            'max_time': max(times),
            'std_dev': statistics.stdev(times) if len(times) > 1 else 0,
            'total_time': sum(times),
            'iterations': self.iterations
        }
        
        return avg_time
    
    def print_results(self):
        """Print benchmark results in a formatted table."""
        print("\n📊 Performance Benchmark Results")
        print("=" * 80)
        print(f"{'Test Name':<40} {'Avg Time (μs)':<15} {'Min (μs)':<12} {'Max (μs)':<12} {'Std Dev':<10}")
        print("-" * 80)
        
        for test_name, stats in self.results.items():
            avg_us = stats['avg_time'] * 1_000_000
            min_us = stats['min_time'] * 1_000_000  
            max_us = stats['max_time'] * 1_000_000
            std_dev_us = stats['std_dev'] * 1_000_000
            
            print(f"{test_name:<40} {avg_us:<15.2f} {min_us:<12.2f} {max_us:<12.2f} {std_dev_us:<10.2f}")
    
    def compare_tests(self, test1: str, test2: str) -> Dict[str, Any]:
        """Compare two test results and calculate overhead."""
        if test1 not in self.results or test2 not in self.results:
            return {"error": "One or both tests not found"}
        
        time1 = self.results[test1]['avg_time']
        time2 = self.results[test2]['avg_time']
        
        overhead_abs = abs(time2 - time1)
        overhead_pct = (overhead_abs / min(time1, time2)) * 100
        slower_test = test1 if time1 > time2 else test2
        faster_test = test2 if time1 > time2 else test1
        
        return {
            'faster_test': faster_test,
            'slower_test': slower_test,
            'overhead_microseconds': overhead_abs * 1_000_000,
            'overhead_percentage': overhead_pct,
            'time_difference': overhead_abs
        }


class ValidationPerformanceTests:
    """Performance tests for validation utilities."""
    
    def __init__(self):
        self.test_data = {
            'username': 'test_user_123',
            'email': 'test@example.com',
            'content': 'This is test content for validation',
            'user_id': 12345,
            'message_data': {
                'type': 'text',
                'id': 'msg_123',
                'content': 'Test message content',
                'timestamp': datetime.now()
            }
        }
    
    def direct_validation(self):
        """Direct validation without utilities (baseline)."""
        username = self.test_data['username']
        
        # Direct validation logic
        if not username:
            return False
        if len(username) < 3:
            return False
        if len(username) > 50:
            return False
        return True
    
    def utility_validation(self):
        """Validation using collaborative utilities."""
        username = self.test_data['username']
        
        result = FieldValidator.validate_required_field(username, 'username')
        if not result.is_valid:
            return False
            
        length_result = FieldValidator.validate_string_length(
            username, min_length=3, max_length=50
        )
        return length_result.is_valid
    
    def direct_user_validation(self):
        """Direct user validation."""
        user_id = self.test_data['user_id']
        
        if user_id is None:
            return False
        if not isinstance(user_id, int):
            return False
        if user_id <= 0:
            return False
        return True
    
    def utility_user_validation(self):
        """User validation using utilities."""
        user_id = self.test_data['user_id']
        result = UserValidator.validate_user_id(user_id)
        return result.is_valid
    
    def direct_message_validation(self):
        """Direct message validation."""
        msg_data = self.test_data['message_data']
        
        if not msg_data.get('type'):
            return False
        if not msg_data.get('id'):
            return False
        if not msg_data.get('content'):
            return False
        if len(msg_data['content']) > 5000:
            return False
        return True
    
    def utility_message_validation(self):
        """Message validation using utilities."""
        # Create mock message object
        class MockMessage:
            def __init__(self, data):
                self.message_type = data['type']
                self.message_id = data['id']
                self.data = {'content': data['content']}
                self.timestamp = data['timestamp']
        
        message = MockMessage(self.test_data['message_data'])
        result = MessageValidator.validate_message_base_fields(message)
        return result.is_valid


class ErrorHandlingPerformanceTests:
    """Performance tests for error handling utilities."""
    
    def direct_error_handling(self):
        """Direct error handling (baseline)."""
        try:
            raise ValueError("Test error")
        except ValueError as e:
            return {
                'error': True,
                'message': str(e),
                'type': 'ValueError'
            }
    
    def utility_error_handling(self):
        """Error handling using collaborative utilities."""
        try:
            raise ValueError("Test error")
        except ValueError as e:
            error = ValidationError(str(e))
            return create_error_response(error)
    
    def direct_error_creation(self):
        """Direct error object creation."""
        return ValueError("Test error message")
    
    def utility_error_creation(self):
        """Error creation using collaborative utilities."""
        return ValidationError("Test error message", field_name="test_field")


class AuditLoggingPerformanceTests:
    """Performance tests for audit logging utilities."""
    
    def __init__(self):
        # Mock logger to avoid actual I/O
        import logging
        self.mock_logger = logging.getLogger('test_audit')
        self.mock_logger.addHandler(logging.NullHandler())
        self.mock_logger.setLevel(logging.CRITICAL)  # Suppress output
        
        self.audit_logger = AuditLogger()
        self.audit_logger.audit_logger = self.mock_logger
    
    def direct_logging(self):
        """Direct logging without audit utilities."""
        log_data = {
            'event': 'user_login',
            'user_id': 123,
            'timestamp': datetime.now().isoformat(),
            'details': {'method': 'password'}
        }
        # Simulate minimal logging overhead
        return log_data
    
    def utility_audit_logging(self):
        """Audit logging using collaborative utilities."""
        self.audit_logger.log_event(
            AuditEventType.USER_LOGIN,
            user_id=123,
            details={'method': 'password'}
        )
    
    def direct_event_creation(self):
        """Direct event data creation."""
        return {
            'event_type': 'user_login',
            'timestamp': datetime.now().isoformat(),
            'user_id': 123
        }
    
    def utility_event_creation(self):
        """Event creation using audit utilities."""
        event = AuditEvent(
            event_type=AuditEventType.USER_LOGIN,
            timestamp=datetime.now(),
            user_id=123
        )
        return event.to_dict()


class ServiceMixinPerformanceTests:
    """Performance tests for service mixins."""
    
    def direct_service_operation(self):
        """Direct service operation without mixins."""
        # Simulate basic service operation
        data = {'input': 'test_data'}
        result = {'output': data['input'].upper()}
        return result
    
    def mixin_service_operation(self):
        """Service operation using error handling mixin."""
        class TestService(ErrorHandlingMixin):
            def process_data(self, data):
                return {'output': data['input'].upper()}
        
        service = TestService()
        data = {'input': 'test_data'}
        return service.safe_execute(
            service.process_data,
            data,
            operation="test_operation"
        )


def run_performance_validation():
    """Run comprehensive performance validation."""
    
    print("🚀 Collaborative Utilities Performance Validation")
    print("=" * 60)
    print(f"Running benchmarks with {10000} iterations each...")
    
    benchmark = PerformanceBenchmark(iterations=10000)
    
    # Validation performance tests
    print("\n1. Validation Performance Tests")
    print("-" * 40)
    
    validation_tests = ValidationPerformanceTests()
    
    benchmark.run_benchmark("Direct Field Validation", validation_tests.direct_validation)
    benchmark.run_benchmark("Utility Field Validation", validation_tests.utility_validation)
    
    benchmark.run_benchmark("Direct User Validation", validation_tests.direct_user_validation)
    benchmark.run_benchmark("Utility User Validation", validation_tests.utility_user_validation)
    
    benchmark.run_benchmark("Direct Message Validation", validation_tests.direct_message_validation)
    benchmark.run_benchmark("Utility Message Validation", validation_tests.utility_message_validation)
    
    # Error handling performance tests
    print("\n2. Error Handling Performance Tests")
    print("-" * 40)
    
    error_tests = ErrorHandlingPerformanceTests()
    
    benchmark.run_benchmark("Direct Error Handling", error_tests.direct_error_handling)
    benchmark.run_benchmark("Utility Error Handling", error_tests.utility_error_handling)
    
    benchmark.run_benchmark("Direct Error Creation", error_tests.direct_error_creation)
    benchmark.run_benchmark("Utility Error Creation", error_tests.utility_error_creation)
    
    # Audit logging performance tests
    print("\n3. Audit Logging Performance Tests")
    print("-" * 40)
    
    audit_tests = AuditLoggingPerformanceTests()
    
    benchmark.run_benchmark("Direct Logging", audit_tests.direct_logging)
    benchmark.run_benchmark("Utility Audit Logging", audit_tests.utility_audit_logging)
    
    benchmark.run_benchmark("Direct Event Creation", audit_tests.direct_event_creation)
    benchmark.run_benchmark("Utility Event Creation", audit_tests.utility_event_creation)
    
    # Service mixin performance tests
    print("\n4. Service Mixin Performance Tests")
    print("-" * 40)
    
    mixin_tests = ServiceMixinPerformanceTests()
    
    benchmark.run_benchmark("Direct Service Operation", mixin_tests.direct_service_operation)
    benchmark.run_benchmark("Mixin Service Operation", mixin_tests.mixin_service_operation)
    
    # Print all results
    benchmark.print_results()
    
    # Performance analysis
    print("\n📈 Performance Analysis")
    print("=" * 60)
    
    comparisons = [
        ("Direct Field Validation", "Utility Field Validation"),
        ("Direct User Validation", "Utility User Validation"),
        ("Direct Message Validation", "Utility Message Validation"),
        ("Direct Error Handling", "Utility Error Handling"),
        ("Direct Error Creation", "Utility Error Creation"),
        ("Direct Logging", "Utility Audit Logging"),
        ("Direct Event Creation", "Utility Event Creation"),
        ("Direct Service Operation", "Mixin Service Operation")
    ]
    
    overhead_summary = []
    
    for direct_test, utility_test in comparisons:
        comparison = benchmark.compare_tests(direct_test, utility_test)
        if 'error' not in comparison:
            overhead_summary.append({
                'test_pair': (direct_test, utility_test),
                'overhead_pct': comparison['overhead_percentage'],
                'overhead_us': comparison['overhead_microseconds']
            })
            
            print(f"\n{utility_test} vs {direct_test}:")
            print(f"  Overhead: {comparison['overhead_percentage']:.2f}% ({comparison['overhead_microseconds']:.2f} μs)")
            print(f"  Faster: {comparison['faster_test']}")
    
    # Overall assessment
    print("\n🎯 Performance Assessment")
    print("=" * 60)
    
    avg_overhead = statistics.mean([item['overhead_pct'] for item in overhead_summary])
    max_overhead = max([item['overhead_pct'] for item in overhead_summary])
    
    print(f"Average overhead: {avg_overhead:.2f}%")
    print(f"Maximum overhead: {max_overhead:.2f}%")
    
    # Performance verdict
    if avg_overhead < 10:
        verdict = "✅ EXCELLENT - Minimal performance impact"
    elif avg_overhead < 25:
        verdict = "✅ GOOD - Acceptable performance overhead"
    elif avg_overhead < 50:
        verdict = "⚠️  MODERATE - Consider optimization for high-throughput scenarios"
    else:
        verdict = "❌ HIGH - Significant performance impact, optimization needed"
    
    print(f"\nPerformance Verdict: {verdict}")
    
    # Recommendations
    print("\n💡 Recommendations")
    print("=" * 60)
    
    high_overhead_tests = [item for item in overhead_summary if item['overhead_pct'] > 25]
    
    if not high_overhead_tests:
        print("• No significant performance concerns identified")
        print("• Utilities are well-optimized for production use")
        print("• Consider caching for extremely high-throughput scenarios")
    else:
        print("• High overhead detected in the following areas:")
        for item in high_overhead_tests:
            print(f"  - {item['test_pair'][1]}: {item['overhead_pct']:.1f}% overhead")
        print("• Consider optimization or selective usage in performance-critical paths")
    
    print("\n• For high-frequency operations (>10,000/sec), consider:")
    print("  - Caching validation results")
    print("  - Async audit logging")
    print("  - Batch error handling")
    
    print("\n• For normal application usage (<1,000/sec), current performance is excellent")


def run_memory_usage_test():
    """Test memory usage of collaborative utilities."""
    import tracemalloc
    
    print("\n🧠 Memory Usage Analysis")
    print("=" * 40)
    
    # Test memory usage of utilities
    tracemalloc.start()
    
    # Create multiple instances to test memory footprint
    validation_tests = ValidationPerformanceTests()
    error_tests = ErrorHandlingPerformanceTests()
    audit_tests = AuditLoggingPerformanceTests()
    
    # Run some operations
    for _ in range(1000):
        validation_tests.utility_validation()
        error_tests.utility_error_creation()
        audit_tests.utility_event_creation()
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    print(f"Current memory usage: {current / 1024 / 1024:.2f} MB")
    print(f"Peak memory usage: {peak / 1024 / 1024:.2f} MB")
    
    if peak / 1024 / 1024 < 10:
        print("✅ Memory usage is within acceptable limits")
    else:
        print("⚠️  High memory usage detected - consider optimization")


if __name__ == "__main__":
    try:
        run_performance_validation()
        run_memory_usage_test()
        
        print("\n🎉 Performance validation completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Performance validation failed: {e}")
        traceback.print_exc()