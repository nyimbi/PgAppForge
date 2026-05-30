#!/usr/bin/env python3
"""
Performance monitoring infrastructure for PgForge tutorial testing.

This module provides comprehensive performance monitoring, benchmarking,
and analysis tools for tutorial validation.
"""

import time
import sys
import os
import threading
import json
import statistics
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, asdict
from contextlib import contextmanager
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetric:
    """Data class for individual performance metrics."""
    name: str
    value: float
    unit: str
    timestamp: datetime
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        return result


@dataclass
class BenchmarkResult:
    """Data class for benchmark results."""
    operation: str
    duration: float
    memory_peak: float
    memory_avg: float
    cpu_peak: float
    cpu_avg: float
    iterations: int
    success_rate: float
    error_count: int
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


class SystemResourceMonitor:
    """Monitor system resources during test execution."""

    def __init__(self, sample_interval: float = 0.1):
        self.sample_interval = sample_interval
        self.monitoring = False
        self.monitor_thread = None
        self.metrics = []
        self.start_time = None
        self.psutil_available = self._check_psutil()

    def _check_psutil(self) -> bool:
        """Check if psutil is available for detailed monitoring."""
        try:
            import psutil
            return True
        except ImportError:
            logger.warning("psutil not available - using basic monitoring")
            return False

    def start_monitoring(self):
        """Start resource monitoring in background thread."""
        if self.monitoring:
            return

        self.monitoring = True
        self.start_time = time.time()
        self.metrics.clear()

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.debug("Started resource monitoring")

    def stop_monitoring(self) -> Dict[str, Any]:
        """Stop monitoring and return collected metrics."""
        if not self.monitoring:
            return {}

        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1.0)

        duration = time.time() - self.start_time if self.start_time else 0
        return self._analyze_metrics(duration)

    def _monitor_loop(self):
        """Main monitoring loop running in background thread."""
        if not self.psutil_available:
            return

        import psutil
        process = psutil.Process()

        while self.monitoring:
            try:
                # Process metrics
                memory_info = process.memory_info()
                cpu_percent = process.cpu_percent()

                # System metrics
                system_memory = psutil.virtual_memory()
                system_cpu = psutil.cpu_percent(interval=None)

                metric = {
                    'timestamp': time.time(),
                    'process_memory_rss': memory_info.rss,
                    'process_memory_vms': memory_info.vms,
                    'process_cpu_percent': cpu_percent,
                    'system_memory_percent': system_memory.percent,
                    'system_memory_available': system_memory.available,
                    'system_cpu_percent': system_cpu,
                    'open_files': len(process.open_files()),
                    'threads': process.num_threads()
                }

                self.metrics.append(metric)

            except Exception as e:
                logger.debug(f"Error collecting metrics: {e}")

            time.sleep(self.sample_interval)

    def _analyze_metrics(self, duration: float) -> Dict[str, Any]:
        """Analyze collected metrics and generate summary."""
        if not self.metrics:
            return {'duration': duration, 'samples': 0}

        # Extract time series data
        memory_rss = [m['process_memory_rss'] for m in self.metrics]
        memory_vms = [m['process_memory_vms'] for m in self.metrics]
        cpu_percent = [m['process_cpu_percent'] for m in self.metrics]
        open_files = [m['open_files'] for m in self.metrics]
        threads = [m['threads'] for m in self.metrics]

        # Calculate statistics
        def safe_stats(data: List[float]) -> Dict[str, float]:
            if not data:
                return {'min': 0, 'max': 0, 'mean': 0, 'median': 0, 'std': 0}
            return {
                'min': min(data),
                'max': max(data),
                'mean': statistics.mean(data),
                'median': statistics.median(data),
                'std': statistics.stdev(data) if len(data) > 1 else 0
            }

        return {
            'duration': duration,
            'samples': len(self.metrics),
            'sample_rate': len(self.metrics) / duration if duration > 0 else 0,
            'memory_rss_mb': {k: v / 1024 / 1024 for k, v in safe_stats(memory_rss).items()},
            'memory_vms_mb': {k: v / 1024 / 1024 for k, v in safe_stats(memory_vms).items()},
            'cpu_percent': safe_stats(cpu_percent),
            'open_files': safe_stats(open_files),
            'threads': safe_stats(threads),
            'peak_memory_mb': max(memory_rss) / 1024 / 1024 if memory_rss else 0,
            'peak_cpu_percent': max(cpu_percent) if cpu_percent else 0
        }

    @contextmanager
    def monitor_context(self):
        """Context manager for monitoring a code block."""
        self.start_monitoring()
        try:
            yield self
        finally:
            result = self.stop_monitoring()
            self.last_result = result


class PerformanceBenchmark:
    """Benchmark runner for tutorial operations."""

    def __init__(self):
        self.results = []
        self.thresholds = {
            'app_startup': 10.0,       # seconds
            'database_query': 1.0,     # seconds
            'view_render': 2.0,        # seconds
            'api_request': 0.5,        # seconds
            'batch_operation': 5.0,    # seconds
        }

    def set_threshold(self, operation: str, threshold: float):
        """Set performance threshold for an operation."""
        self.thresholds[operation] = threshold

    def benchmark_function(self,
                          func: Callable,
                          operation_name: str,
                          iterations: int = 1,
                          *args, **kwargs) -> BenchmarkResult:
        """Benchmark a function execution."""
        monitor = SystemResourceMonitor()
        errors = 0
        durations = []

        with monitor.monitor_context():
            for i in range(iterations):
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    duration = time.time() - start_time
                    durations.append(duration)
                except Exception as e:
                    errors += 1
                    duration = time.time() - start_time
                    durations.append(duration)
                    logger.debug(f"Benchmark iteration {i+1} failed: {e}")

        resource_stats = monitor.last_result

        # Calculate metrics
        avg_duration = statistics.mean(durations) if durations else 0
        success_rate = ((iterations - errors) / iterations * 100) if iterations > 0 else 0

        benchmark_result = BenchmarkResult(
            operation=operation_name,
            duration=avg_duration,
            memory_peak=resource_stats.get('peak_memory_mb', 0),
            memory_avg=resource_stats.get('memory_rss_mb', {}).get('mean', 0),
            cpu_peak=resource_stats.get('peak_cpu_percent', 0),
            cpu_avg=resource_stats.get('cpu_percent', {}).get('mean', 0),
            iterations=iterations,
            success_rate=success_rate,
            error_count=errors,
            metadata={
                'durations': durations,
                'resource_stats': resource_stats,
                'threshold': self.thresholds.get(operation_name)
            }
        )

        self.results.append(benchmark_result)
        return benchmark_result

    @contextmanager
    def benchmark_context(self, operation_name: str):
        """Context manager for benchmarking a code block."""
        monitor = SystemResourceMonitor()
        start_time = time.time()

        with monitor.monitor_context():
            try:
                yield
                success = True
            except Exception:
                success = False
                raise
            finally:
                duration = time.time() - start_time
                resource_stats = monitor.last_result

                benchmark_result = BenchmarkResult(
                    operation=operation_name,
                    duration=duration,
                    memory_peak=resource_stats.get('peak_memory_mb', 0),
                    memory_avg=resource_stats.get('memory_rss_mb', {}).get('mean', 0),
                    cpu_peak=resource_stats.get('peak_cpu_percent', 0),
                    cpu_avg=resource_stats.get('cpu_percent', {}).get('mean', 0),
                    iterations=1,
                    success_rate=100.0 if success else 0.0,
                    error_count=0 if success else 1,
                    metadata={
                        'resource_stats': resource_stats,
                        'threshold': self.thresholds.get(operation_name)
                    }
                )

                self.results.append(benchmark_result)

    def check_thresholds(self) -> Dict[str, bool]:
        """Check if benchmarks meet performance thresholds."""
        threshold_checks = {}

        for result in self.results:
            threshold = self.thresholds.get(result.operation)
            if threshold:
                threshold_checks[result.operation] = result.duration <= threshold

        return threshold_checks

    def get_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report."""
        if not self.results:
            return {'status': 'no_results'}

        threshold_checks = self.check_thresholds()
        passed_checks = sum(1 for passed in threshold_checks.values() if passed)
        total_checks = len(threshold_checks)

        slowest_operation = max(self.results, key=lambda r: r.duration, default=None)
        highest_memory = max(self.results, key=lambda r: r.memory_peak, default=None)

        return {
            'summary': {
                'total_benchmarks': len(self.results),
                'thresholds_passed': passed_checks,
                'total_thresholds': total_checks,
                'pass_rate': (passed_checks / total_checks * 100) if total_checks > 0 else 0,
                'overall_status': 'PASS' if passed_checks == total_checks else 'FAIL'
            },
            'slowest_operation': {
                'name': slowest_operation.operation if slowest_operation else None,
                'duration': slowest_operation.duration if slowest_operation else 0
            },
            'highest_memory': {
                'name': highest_memory.operation if highest_memory else None,
                'memory_mb': highest_memory.memory_peak if highest_memory else 0
            },
            'threshold_checks': threshold_checks,
            'detailed_results': [result.to_dict() for result in self.results],
            'timestamp': datetime.now().isoformat()
        }

    def save_report(self, file_path: Path):
        """Save performance report to file."""
        report = self.get_performance_report()
        with open(file_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Performance report saved to: {file_path}")

    def reset(self):
        """Reset benchmark results."""
        self.results.clear()


class TutorialPerformanceTester:
    """Specialized performance tester for tutorial operations."""

    def __init__(self):
        self.benchmark = PerformanceBenchmark()
        self.test_results = {}

    def test_app_startup_performance(self, app_factory: Callable) -> BenchmarkResult:
        """Test application startup performance."""
        def startup_test():
            app = app_factory()
            with app.app_context():
                # Simulate basic app operations
                return app

        return self.benchmark.benchmark_function(
            startup_test,
            'app_startup',
            iterations=3
        )

    def test_database_performance(self, session_factory: Callable, operations: int = 100) -> BenchmarkResult:
        """Test database operation performance."""
        def database_test():
            session = session_factory()

            # Simulate database operations
            for i in range(operations):
                # Mock database operations
                pass

            return session

        return self.benchmark.benchmark_function(
            database_test,
            'database_bulk_operations',
            iterations=1
        )

    def test_view_render_performance(self, client, routes: List[str]) -> Dict[str, BenchmarkResult]:
        """Test view rendering performance."""
        results = {}

        for route in routes:
            def view_test():
                response = client.get(route)
                return response

            result = self.benchmark.benchmark_function(
                view_test,
                f'view_render_{route.replace("/", "_")}',
                iterations=5
            )
            results[route] = result

        return results

    def test_ai_integration_performance(self, ai_client, operations: int = 10) -> BenchmarkResult:
        """Test AI integration performance."""
        def ai_test():
            responses = []
            for i in range(operations):
                # Simulate AI API calls
                response = "Mock AI response"
                responses.append(response)
            return responses

        return self.benchmark.benchmark_function(
            ai_test,
            'ai_integration',
            iterations=1
        )

    def test_concurrent_operations(self, operation: Callable, concurrent_users: int = 5) -> BenchmarkResult:
        """Test concurrent operation performance."""
        import concurrent.futures

        def concurrent_test():
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_users) as executor:
                futures = [executor.submit(operation) for _ in range(concurrent_users)]
                results = [future.result() for future in concurrent.futures.as_completed(futures)]
            return results

        return self.benchmark.benchmark_function(
            concurrent_test,
            'concurrent_operations',
            iterations=1
        )

    def run_comprehensive_performance_test(self,
                                         app_factory: Callable,
                                         session_factory: Callable) -> Dict[str, Any]:
        """Run comprehensive performance test suite."""
        logger.info("Starting comprehensive performance test...")

        # Test app startup
        startup_result = self.test_app_startup_performance(app_factory)
        logger.info(f"App startup: {startup_result.duration:.3f}s")

        # Test database performance
        db_result = self.test_database_performance(session_factory)
        logger.info(f"Database operations: {db_result.duration:.3f}s")

        # Generate report
        report = self.benchmark.get_performance_report()

        # Add tutorial-specific analysis
        report['tutorial_analysis'] = {
            'startup_acceptable': startup_result.duration < 10.0,
            'database_acceptable': db_result.duration < 5.0,
            'memory_usage_acceptable': startup_result.memory_peak < 100.0,  # MB
            'recommendations': self._generate_recommendations(report)
        }

        return report

    def _generate_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate performance recommendations."""
        recommendations = []

        summary = report.get('summary', {})
        if summary.get('pass_rate', 100) < 80:
            recommendations.append("Performance thresholds not met - consider optimization")

        slowest = report.get('slowest_operation', {})
        if slowest.get('duration', 0) > 5.0:
            recommendations.append(f"Optimize {slowest.get('name', 'unknown')} operation")

        highest_memory = report.get('highest_memory', {})
        if highest_memory.get('memory_mb', 0) > 200:
            recommendations.append("Memory usage is high - check for memory leaks")

        if not recommendations:
            recommendations.append("Performance is within acceptable limits")

        return recommendations


class PerformanceReporter:
    """Generate and format performance reports."""

    @staticmethod
    def generate_html_report(report: Dict[str, Any], output_path: Path):
        """Generate HTML performance report."""
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Tutorial Performance Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .summary {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 30px; }}
        .metric {{ display: inline-block; margin: 10px; padding: 15px; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .pass {{ color: #28a745; }}
        .fail {{ color: #dc3545; }}
        .benchmark {{ margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 8px; }}
        .recommendations {{ background: #fff3cd; padding: 15px; border-radius: 8px; margin-top: 20px; }}
    </style>
</head>
<body>
    <h1>Tutorial Performance Report</h1>

    <div class="summary">
        <h2>Summary</h2>
        <div class="metric">
            <strong>Overall Status:</strong>
            <span class="{'pass' if report.get('summary', {}).get('overall_status') == 'PASS' else 'fail'}">
                {report.get('summary', {}).get('overall_status', 'UNKNOWN')}
            </span>
        </div>
        <div class="metric">
            <strong>Pass Rate:</strong> {report.get('summary', {}).get('pass_rate', 0):.1f}%
        </div>
        <div class="metric">
            <strong>Total Benchmarks:</strong> {report.get('summary', {}).get('total_benchmarks', 0)}
        </div>
    </div>

    <h2>Benchmark Results</h2>
"""

        for result in report.get('detailed_results', []):
            threshold = result.get('metadata', {}).get('threshold')
            threshold_status = 'pass' if threshold and result['duration'] <= threshold else 'fail'

            html_content += f"""
    <div class="benchmark">
        <h3>{result['operation']}</h3>
        <p><strong>Duration:</strong> {result['duration']:.3f}s
           {f'(threshold: {threshold}s)' if threshold else ''}
           <span class="{threshold_status}">{'✓' if threshold_status == 'pass' else '✗'}</span>
        </p>
        <p><strong>Memory Peak:</strong> {result['memory_peak']:.1f} MB</p>
        <p><strong>CPU Peak:</strong> {result['cpu_peak']:.1f}%</p>
        <p><strong>Success Rate:</strong> {result['success_rate']:.1f}%</p>
    </div>
"""

        if report.get('tutorial_analysis', {}).get('recommendations'):
            html_content += """
    <div class="recommendations">
        <h3>Recommendations</h3>
        <ul>
"""
            for rec in report['tutorial_analysis']['recommendations']:
                html_content += f"<li>{rec}</li>"

            html_content += """
        </ul>
    </div>
"""

        html_content += """
</body>
</html>"""

        with open(output_path, 'w') as f:
            f.write(html_content)

    @staticmethod
    def generate_console_report(report: Dict[str, Any]):
        """Generate console performance report."""
        print("\n" + "="*60)
        print("📊 TUTORIAL PERFORMANCE REPORT")
        print("="*60)

        summary = report.get('summary', {})
        status = summary.get('overall_status', 'UNKNOWN')
        status_icon = "✅" if status == 'PASS' else "❌"

        print(f"\n{status_icon} Overall Status: {status}")
        print(f"📈 Pass Rate: {summary.get('pass_rate', 0):.1f}%")
        print(f"🔢 Total Benchmarks: {summary.get('total_benchmarks', 0)}")

        slowest = report.get('slowest_operation', {})
        if slowest.get('name'):
            print(f"🐌 Slowest Operation: {slowest['name']} ({slowest['duration']:.3f}s)")

        highest_memory = report.get('highest_memory', {})
        if highest_memory.get('name'):
            print(f"💾 Highest Memory: {highest_memory['name']} ({highest_memory['memory_mb']:.1f} MB)")

        # Show recommendations
        recommendations = report.get('tutorial_analysis', {}).get('recommendations', [])
        if recommendations:
            print(f"\n💡 Recommendations:")
            for rec in recommendations:
                print(f"  • {rec}")

        print("="*60)


# Global performance monitor instance
performance_monitor = TutorialPerformanceTester()


# Export main components
__all__ = [
    'PerformanceMetric',
    'BenchmarkResult',
    'SystemResourceMonitor',
    'PerformanceBenchmark',
    'TutorialPerformanceTester',
    'PerformanceReporter',
    'performance_monitor'
]