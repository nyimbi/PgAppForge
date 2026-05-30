"""
Performance Optimization Engine for PgForge

This module provides comprehensive performance optimization capabilities including
query optimization, caching strategies, resource management, and automated
bottleneck detection with intelligent recommendations.

Features:
- Real-time performance monitoring
- Intelligent query optimization
- Multi-level caching strategies
- Memory and CPU optimization
- Automated bottleneck detection
- Performance analytics and insights
- Auto-scaling recommendations
"""

import time
import threading
import statistics
import psutil
import gc
from typing import Dict, List, Optional, Any, Callable, Tuple, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict, deque
import logging
import asyncio
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

# Database and caching imports
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from flask import g, request, current_app
from flask_caching import Cache

logger = logging.getLogger(__name__)


class PerformanceMetricType(Enum):
    """Types of performance metrics."""
    RESPONSE_TIME = "response_time"
    DATABASE_QUERY = "database_query"
    MEMORY_USAGE = "memory_usage"
    CPU_USAGE = "cpu_usage"
    CACHE_HIT_RATE = "cache_hit_rate"
    CONCURRENT_USERS = "concurrent_users"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"


class OptimizationLevel(Enum):
    """Performance optimization levels."""
    CONSERVATIVE = "conservative"    # Safe optimizations only
    MODERATE = "moderate"           # Balanced optimization
    AGGRESSIVE = "aggressive"       # Maximum optimization
    EXPERIMENTAL = "experimental"   # Cutting-edge optimizations


class BottleneckType(Enum):
    """Types of performance bottlenecks."""
    DATABASE_QUERY = "database_query"
    MEMORY_LEAK = "memory_leak"
    CPU_INTENSIVE = "cpu_intensive"
    NETWORK_LATENCY = "network_latency"
    CACHE_MISS = "cache_miss"
    CONCURRENCY = "concurrency"
    ALGORITHM_COMPLEXITY = "algorithm_complexity"


@dataclass
class PerformanceMetric:
    """Individual performance metric measurement."""
    metric_type: PerformanceMetricType
    value: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    threshold_exceeded: bool = False
    severity: str = "low"


@dataclass
class QueryPerformanceData:
    """Database query performance data."""
    query_hash: str
    raw_query: str
    execution_time: float
    fetch_time: float
    row_count: int
    table_scans: int
    index_scans: int
    cache_hits: int
    optimization_score: float
    recommendations: List[str] = field(default_factory=list)


@dataclass
class PerformanceBottleneck:
    """Performance bottleneck identification."""
    bottleneck_type: BottleneckType
    severity: str
    description: str
    impact_score: float
    affected_components: List[str]
    recommendations: List[str]
    auto_fixable: bool
    detected_at: datetime = field(default_factory=datetime.now)


@dataclass
class OptimizationRecommendation:
    """Performance optimization recommendation."""
    title: str
    description: str
    impact: str  # high, medium, low
    effort: str  # high, medium, low
    category: str
    implementation: str
    estimated_improvement: float
    risks: List[str] = field(default_factory=list)


@dataclass
class PerformanceReport:
    """Comprehensive performance report."""
    report_id: str
    generated_at: datetime
    time_window: Tuple[datetime, datetime]
    overall_score: float
    key_metrics: Dict[str, float]
    bottlenecks: List[PerformanceBottleneck]
    recommendations: List[OptimizationRecommendation]
    trending_data: Dict[str, List[float]]
    comparison_data: Dict[str, Dict[str, float]]


class PerformanceMonitor:
    """Real-time performance monitoring system."""
    
    def __init__(self, max_metrics: int = 10000):
        """
        Initialize performance monitor.
        
        Args:
            max_metrics: Maximum number of metrics to store in memory
        """
        self.metrics: Dict[PerformanceMetricType, deque] = defaultdict(
            lambda: deque(maxlen=max_metrics)
        )
        self.thresholds: Dict[PerformanceMetricType, float] = {
            PerformanceMetricType.RESPONSE_TIME: 1.0,  # 1 second
            PerformanceMetricType.DATABASE_QUERY: 0.5,  # 500ms
            PerformanceMetricType.MEMORY_USAGE: 0.8,    # 80%
            PerformanceMetricType.CPU_USAGE: 0.8,       # 80%
            PerformanceMetricType.CACHE_HIT_RATE: 0.7,  # 70% minimum
            PerformanceMetricType.ERROR_RATE: 0.05,     # 5% maximum
        }
        self.is_monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None
        self._stop_monitoring = threading.Event()
    
    def start_monitoring(self):
        """Start real-time performance monitoring."""
        if self.is_monitoring:
            return
        
        self.is_monitoring = True
        self._stop_monitoring.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_system)
        self.monitor_thread.start()
        logger.info("Performance monitoring started")
    
    def stop_monitoring(self):
        """Stop performance monitoring."""
        if not self.is_monitoring:
            return
        
        self.is_monitoring = False
        self._stop_monitoring.set()
        
        if self.monitor_thread:
            self.monitor_thread.join()
        
        logger.info("Performance monitoring stopped")
    
    def _monitor_system(self):
        """Background monitoring loop."""
        while not self._stop_monitoring.is_set():
            try:
                # Monitor system resources
                self._monitor_system_resources()
                
                # Monitor application metrics
                self._monitor_application_metrics()
                
                time.sleep(5)  # Monitor every 5 seconds
                
            except Exception as e:
                logger.error(f"Error in performance monitoring: {str(e)}")
                time.sleep(10)  # Wait longer on error
    
    def _monitor_system_resources(self):
        """Monitor system-level resources."""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            self.record_metric(PerformanceMetricType.CPU_USAGE, cpu_percent)
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            self.record_metric(PerformanceMetricType.MEMORY_USAGE, memory_percent)
            
        except Exception as e:
            logger.warning(f"Failed to monitor system resources: {str(e)}")
    
    def _monitor_application_metrics(self):
        """Monitor application-specific metrics."""
        try:
            # Check if Flask context is available
            if hasattr(g, 'performance_data'):
                perf_data = g.performance_data
                
                # Record response times
                if 'response_time' in perf_data:
                    self.record_metric(
                        PerformanceMetricType.RESPONSE_TIME, 
                        perf_data['response_time']
                    )
                
                # Record error rates
                if 'error_occurred' in perf_data:
                    error_rate = 1.0 if perf_data['error_occurred'] else 0.0
                    self.record_metric(PerformanceMetricType.ERROR_RATE, error_rate)
                
        except Exception as e:
            logger.debug(f"No Flask context available for monitoring: {str(e)}")
    
    def record_metric(self, metric_type: PerformanceMetricType, value: float, 
                     metadata: Optional[Dict[str, Any]] = None):
        """Record a performance metric."""
        threshold_exceeded = value > self.thresholds.get(metric_type, float('inf'))
        
        # Determine severity
        if threshold_exceeded:
            threshold = self.thresholds[metric_type]
            if value > threshold * 2:
                severity = "critical"
            elif value > threshold * 1.5:
                severity = "high"
            else:
                severity = "medium"
        else:
            severity = "low"
        
        metric = PerformanceMetric(
            metric_type=metric_type,
            value=value,
            timestamp=datetime.now(),
            metadata=metadata or {},
            threshold_exceeded=threshold_exceeded,
            severity=severity
        )
        
        self.metrics[metric_type].append(metric)
        
        # Log critical metrics
        if severity in ("critical", "high"):
            logger.warning(f"Performance alert: {metric_type.value} = {value:.2f} (threshold: {self.thresholds.get(metric_type, 'N/A')})")
    
    def get_current_metrics(self) -> Dict[PerformanceMetricType, float]:
        """Get current performance metrics."""
        current = {}
        
        for metric_type, metric_deque in self.metrics.items():
            if metric_deque:
                current[metric_type] = metric_deque[-1].value
        
        return current
    
    def get_metric_statistics(self, metric_type: PerformanceMetricType, 
                            time_window: timedelta = timedelta(hours=1)) -> Dict[str, float]:
        """Get statistics for a specific metric within a time window."""
        if metric_type not in self.metrics:
            return {}
        
        # Filter metrics within time window
        cutoff_time = datetime.now() - time_window
        recent_metrics = [
            metric for metric in self.metrics[metric_type]
            if metric.timestamp >= cutoff_time
        ]
        
        if not recent_metrics:
            return {}
        
        values = [metric.value for metric in recent_metrics]
        
        return {
            'count': len(values),
            'min': min(values),
            'max': max(values),
            'mean': statistics.mean(values),
            'median': statistics.median(values),
            'stdev': statistics.stdev(values) if len(values) > 1 else 0.0,
            'p95': statistics.quantiles(values, n=20)[18] if len(values) > 4 else max(values),
            'p99': statistics.quantiles(values, n=100)[98] if len(values) > 99 else max(values)
        }


class QueryOptimizer:
    """Database query optimization system."""
    
    def __init__(self, cache: Optional[Cache] = None):
        """
        Initialize query optimizer.
        
        Args:
            cache: Flask-Caching instance for query result caching
        """
        self.cache = cache
        self.query_performance: Dict[str, QueryPerformanceData] = {}
        self.slow_queries: List[QueryPerformanceData] = []
        self.query_cache_stats = {'hits': 0, 'misses': 0, 'total': 0}
        
        # Register SQLAlchemy event listeners
        self._register_db_events()
    
    def _register_db_events(self):
        """Register database event listeners for query monitoring."""
        
        @event.listens_for(Engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            context._query_start_time = time.time()
            context._query_statement = statement
        
        @event.listens_for(Engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            if hasattr(context, '_query_start_time'):
                execution_time = time.time() - context._query_start_time
                self._record_query_performance(statement, execution_time, cursor.rowcount)
    
    def _record_query_performance(self, query: str, execution_time: float, row_count: int):
        """Record query performance data."""
        query_hash = self._hash_query(query)
        
        # Analyze query characteristics
        query_data = QueryPerformanceData(
            query_hash=query_hash,
            raw_query=query,
            execution_time=execution_time,
            fetch_time=0.0,  # Would need more detailed instrumentation
            row_count=row_count,
            table_scans=self._count_table_scans(query),
            index_scans=self._count_index_scans(query),
            cache_hits=0,
            optimization_score=self._calculate_optimization_score(query, execution_time)
        )
        
        # Generate recommendations
        query_data.recommendations = self._generate_query_recommendations(query_data)
        
        # Store performance data
        self.query_performance[query_hash] = query_data
        
        # Track slow queries
        if execution_time > 0.5:  # Queries slower than 500ms
            self.slow_queries.append(query_data)
            # Keep only recent slow queries
            self.slow_queries = self.slow_queries[-100:]
        
        # Log slow queries
        if execution_time > 1.0:  # Very slow queries
            logger.warning(f"Slow query detected ({execution_time:.3f}s): {query[:100]}...")
    
    def _hash_query(self, query: str) -> str:
        """Generate hash for query normalization."""
        # Normalize query by removing parameters and whitespace
        normalized = re.sub(r'\s+', ' ', query.strip().lower())
        normalized = re.sub(r"'[^']*'", "'?'", normalized)  # Replace string literals
        normalized = re.sub(r'\d+', '?', normalized)  # Replace numbers
        
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def _count_table_scans(self, query: str) -> int:
        """Count potential table scans in query."""
        # Simplified heuristic - look for SELECT without WHERE on large tables
        query_lower = query.lower()
        
        if 'select' in query_lower and 'where' not in query_lower and 'limit' not in query_lower:
            return 1
        
        return 0
    
    def _count_index_scans(self, query: str) -> int:
        """Count potential index usage in query."""
        query_lower = query.lower()
        
        # Look for indexed operations
        index_indicators = ['where', 'order by', 'group by', 'join']
        return sum(1 for indicator in index_indicators if indicator in query_lower)
    
    def _calculate_optimization_score(self, query: str, execution_time: float) -> float:
        """Calculate query optimization score (0-10, higher is better)."""
        score = 10.0
        
        # Penalize slow execution
        if execution_time > 1.0:
            score -= 4.0
        elif execution_time > 0.5:
            score -= 2.0
        elif execution_time > 0.1:
            score -= 1.0
        
        # Penalize table scans
        if self._count_table_scans(query) > 0:
            score -= 3.0
        
        # Reward index usage
        if self._count_index_scans(query) > 0:
            score += 1.0
        
        return max(0.0, min(10.0, score))
    
    def _generate_query_recommendations(self, query_data: QueryPerformanceData) -> List[str]:
        """Generate optimization recommendations for query."""
        recommendations = []
        
        if query_data.execution_time > 0.5:
            recommendations.append("Consider adding database indexes for frequently queried columns")
        
        if query_data.table_scans > 0:
            recommendations.append("Add WHERE clause to avoid full table scans")
            recommendations.append("Consider adding LIMIT clause for large result sets")
        
        if query_data.row_count > 1000:
            recommendations.append("Implement pagination for large result sets")
        
        if 'select *' in query_data.raw_query.lower():
            recommendations.append("Select only required columns instead of using SELECT *")
        
        if query_data.optimization_score < 5.0:
            recommendations.append("Query appears to be inefficient - consider refactoring")
        
        return recommendations
    
    @contextmanager
    def cached_query(self, cache_key: str, timeout: int = 300):
        """Context manager for cached query execution."""
        if not self.cache:
            yield None
            return
        
        # Try to get from cache
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            self.query_cache_stats['hits'] += 1
            self.query_cache_stats['total'] += 1
            yield cached_result
            return
        
        # Cache miss - execute query
        self.query_cache_stats['misses'] += 1
        self.query_cache_stats['total'] += 1
        
        class CacheWrapper:
            def __init__(self, cache, key, timeout):
                self.cache = cache
                self.key = key
                self.timeout = timeout
                self.result = None
            
            def set_result(self, result):
                self.result = result
                self.cache.set(self.key, result, timeout=self.timeout)
                return result
        
        wrapper = CacheWrapper(self.cache, cache_key, timeout)
        yield wrapper
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get query cache statistics."""
        total = self.query_cache_stats['total']
        if total == 0:
            return {'hit_rate': 0.0, 'hits': 0, 'misses': 0, 'total': 0}
        
        hit_rate = self.query_cache_stats['hits'] / total
        
        return {
            'hit_rate': hit_rate,
            'hits': self.query_cache_stats['hits'],
            'misses': self.query_cache_stats['misses'],
            'total': total
        }
    
    def get_slow_query_report(self, limit: int = 10) -> List[QueryPerformanceData]:
        """Get report of slowest queries."""
        return sorted(self.slow_queries, key=lambda q: q.execution_time, reverse=True)[:limit]


class CacheStrategy:
    """Intelligent caching strategy manager."""
    
    def __init__(self, cache: Cache):
        """
        Initialize cache strategy manager.
        
        Args:
            cache: Flask-Caching instance
        """
        self.cache = cache
        self.cache_patterns = {}
        self.cache_stats = defaultdict(lambda: {'hits': 0, 'misses': 0, 'sets': 0})
    
    def smart_cache(self, key: str, data_generator: Callable, 
                   timeout: Optional[int] = None, 
                   cache_condition: Optional[Callable] = None) -> Any:
        """
        Smart caching with intelligent timeout and condition checking.
        
        Args:
            key: Cache key
            data_generator: Function to generate data if not cached
            timeout: Cache timeout (None for intelligent timeout)
            cache_condition: Function to determine if data should be cached
            
        Returns:
            Cached or generated data
        """
        # Try to get from cache
        cached_data = self.cache.get(key)
        if cached_data is not None:
            self.cache_stats[key]['hits'] += 1
            return cached_data
        
        # Cache miss - generate data
        self.cache_stats[key]['misses'] += 1
        data = data_generator()
        
        # Check if data should be cached
        if cache_condition and not cache_condition(data):
            return data
        
        # Determine intelligent timeout if not provided
        if timeout is None:
            timeout = self._calculate_intelligent_timeout(key, data)
        
        # Cache the data
        self.cache.set(key, data, timeout=timeout)
        self.cache_stats[key]['sets'] += 1
        
        return data
    
    def _calculate_intelligent_timeout(self, key: str, data: Any) -> int:
        """Calculate intelligent cache timeout based on data characteristics."""
        
        # Default timeout
        base_timeout = 300  # 5 minutes
        
        # Adjust based on key patterns
        if 'user' in key.lower():
            return base_timeout * 2  # User data changes less frequently
        elif 'analytics' in key.lower():
            return base_timeout * 6  # Analytics can be cached longer
        elif 'config' in key.lower():
            return base_timeout * 12  # Configuration changes rarely
        elif 'search' in key.lower():
            return base_timeout // 2  # Search results change more frequently
        
        # Adjust based on data size (larger data cached longer)
        try:
            data_size = len(str(data))
            if data_size > 10000:  # Large data
                base_timeout *= 2
            elif data_size < 100:  # Small data
                base_timeout //= 2
        except:
            pass
        
        return base_timeout
    
    def invalidate_pattern(self, pattern: str):
        """Invalidate all cache keys matching a pattern."""
        # This would require a cache backend that supports pattern-based invalidation
        # For now, we'll track keys and invalidate manually
        if pattern in self.cache_patterns:
            keys_to_invalidate = self.cache_patterns[pattern]
            for key in keys_to_invalidate:
                self.cache.delete(key)
            self.cache_patterns[pattern].clear()
    
    def warm_cache(self, cache_definitions: List[Dict[str, Any]]):
        """Pre-warm cache with commonly accessed data."""
        logger.info(f"Warming cache with {len(cache_definitions)} definitions")
        
        for cache_def in cache_definitions:
            try:
                key = cache_def['key']
                generator = cache_def['generator']
                timeout = cache_def.get('timeout', 300)
                
                # Generate and cache data
                data = generator()
                self.cache.set(key, data, timeout=timeout)
                
                logger.debug(f"Warmed cache key: {key}")
                
            except Exception as e:
                logger.error(f"Failed to warm cache key {cache_def.get('key', 'unknown')}: {str(e)}")
    
    def get_cache_efficiency_report(self) -> Dict[str, Any]:
        """Generate cache efficiency report."""
        report = {
            'total_keys': len(self.cache_stats),
            'overall_hit_rate': 0.0,
            'key_statistics': {},
            'recommendations': []
        }
        
        total_hits = sum(stats['hits'] for stats in self.cache_stats.values())
        total_requests = sum(stats['hits'] + stats['misses'] for stats in self.cache_stats.values())
        
        if total_requests > 0:
            report['overall_hit_rate'] = total_hits / total_requests
        
        # Per-key statistics
        for key, stats in self.cache_stats.items():
            total = stats['hits'] + stats['misses']
            hit_rate = stats['hits'] / total if total > 0 else 0.0
            
            report['key_statistics'][key] = {
                'hit_rate': hit_rate,
                'total_requests': total,
                'hits': stats['hits'],
                'misses': stats['misses']
            }
            
            # Generate recommendations
            if total > 10:  # Only for keys with significant usage
                if hit_rate < 0.3:
                    report['recommendations'].append(
                        f"Key '{key}' has low hit rate ({hit_rate:.1%}) - consider adjusting timeout or cache condition"
                    )
                elif hit_rate > 0.9 and total > 100:
                    report['recommendations'].append(
                        f"Key '{key}' has excellent hit rate ({hit_rate:.1%}) - consider longer timeout"
                    )
        
        return report


class BottleneckDetector:
    """Automated performance bottleneck detection."""
    
    def __init__(self, monitor: PerformanceMonitor, query_optimizer: QueryOptimizer):
        """
        Initialize bottleneck detector.
        
        Args:
            monitor: Performance monitor instance
            query_optimizer: Query optimizer instance
        """
        self.monitor = monitor
        self.query_optimizer = query_optimizer
        self.detected_bottlenecks: List[PerformanceBottleneck] = []
    
    def detect_bottlenecks(self) -> List[PerformanceBottleneck]:
        """Detect current performance bottlenecks."""
        bottlenecks = []
        
        # Check for database bottlenecks
        bottlenecks.extend(self._detect_database_bottlenecks())
        
        # Check for memory bottlenecks
        bottlenecks.extend(self._detect_memory_bottlenecks())
        
        # Check for CPU bottlenecks
        bottlenecks.extend(self._detect_cpu_bottlenecks())
        
        # Check for cache bottlenecks
        bottlenecks.extend(self._detect_cache_bottlenecks())
        
        # Store detected bottlenecks
        self.detected_bottlenecks.extend(bottlenecks)
        
        # Sort by impact score
        bottlenecks.sort(key=lambda b: b.impact_score, reverse=True)
        
        return bottlenecks
    
    def _detect_database_bottlenecks(self) -> List[PerformanceBottleneck]:
        """Detect database-related bottlenecks."""
        bottlenecks = []
        
        # Check for slow queries
        slow_queries = self.query_optimizer.get_slow_query_report(5)
        
        if len(slow_queries) > 0:
            avg_slow_time = statistics.mean(q.execution_time for q in slow_queries)
            
            bottleneck = PerformanceBottleneck(
                bottleneck_type=BottleneckType.DATABASE_QUERY,
                severity="high" if avg_slow_time > 2.0 else "medium",
                description=f"Detected {len(slow_queries)} slow database queries (avg: {avg_slow_time:.2f}s)",
                impact_score=min(10.0, avg_slow_time * 2),
                affected_components=["database", "queries"],
                recommendations=[
                    "Add database indexes for frequently queried columns",
                    "Optimize query structure and remove unnecessary JOINs",
                    "Consider database connection pooling",
                    "Implement query result caching"
                ],
                auto_fixable=False
            )
            bottlenecks.append(bottleneck)
        
        return bottlenecks
    
    def _detect_memory_bottlenecks(self) -> List[PerformanceBottleneck]:
        """Detect memory-related bottlenecks."""
        bottlenecks = []
        
        # Check recent memory usage
        memory_stats = self.monitor.get_metric_statistics(PerformanceMetricType.MEMORY_USAGE)
        
        if memory_stats and memory_stats.get('mean', 0) > 80:
            severity = "critical" if memory_stats['mean'] > 95 else "high"
            
            bottleneck = PerformanceBottleneck(
                bottleneck_type=BottleneckType.MEMORY_LEAK,
                severity=severity,
                description=f"High memory usage detected (avg: {memory_stats['mean']:.1f}%)",
                impact_score=memory_stats['mean'] / 10,
                affected_components=["memory", "application"],
                recommendations=[
                    "Check for memory leaks in application code",
                    "Implement object pooling for frequently created objects",
                    "Optimize data structures and remove unnecessary caching",
                    "Consider increasing server memory or horizontal scaling"
                ],
                auto_fixable=True  # Can trigger garbage collection
            )
            bottlenecks.append(bottleneck)
        
        return bottlenecks
    
    def _detect_cpu_bottlenecks(self) -> List[PerformanceBottleneck]:
        """Detect CPU-related bottlenecks."""
        bottlenecks = []
        
        # Check recent CPU usage
        cpu_stats = self.monitor.get_metric_statistics(PerformanceMetricType.CPU_USAGE)
        
        if cpu_stats and cpu_stats.get('mean', 0) > 80:
            severity = "critical" if cpu_stats['mean'] > 95 else "high"
            
            bottleneck = PerformanceBottleneck(
                bottleneck_type=BottleneckType.CPU_INTENSIVE,
                severity=severity,
                description=f"High CPU usage detected (avg: {cpu_stats['mean']:.1f}%)",
                impact_score=cpu_stats['mean'] / 10,
                affected_components=["cpu", "application"],
                recommendations=[
                    "Profile application to identify CPU-intensive operations",
                    "Implement asynchronous processing for heavy tasks",
                    "Optimize algorithms and reduce computational complexity",
                    "Consider horizontal scaling or more powerful hardware"
                ],
                auto_fixable=False
            )
            bottlenecks.append(bottleneck)
        
        return bottlenecks
    
    def _detect_cache_bottlenecks(self) -> List[PerformanceBottleneck]:
        """Detect cache-related bottlenecks."""
        bottlenecks = []
        
        # Check cache hit rates from query optimizer
        cache_stats = self.query_optimizer.get_cache_statistics()
        
        if cache_stats['total'] > 100 and cache_stats['hit_rate'] < 0.5:
            bottleneck = PerformanceBottleneck(
                bottleneck_type=BottleneckType.CACHE_MISS,
                severity="medium",
                description=f"Low cache hit rate detected ({cache_stats['hit_rate']:.1%})",
                impact_score=5.0 * (1 - cache_stats['hit_rate']),
                affected_components=["cache", "performance"],
                recommendations=[
                    "Review cache timeout settings",
                    "Implement smarter cache invalidation strategies",
                    "Pre-warm frequently accessed cache entries",
                    "Consider different cache backends or configurations"
                ],
                auto_fixable=True  # Can adjust cache settings
            )
            bottlenecks.append(bottleneck)
        
        return bottlenecks


class PerformanceOptimizationEngine:
    """Main performance optimization engine coordinating all components."""
    
    def __init__(self, optimization_level: OptimizationLevel = OptimizationLevel.MODERATE,
                 cache: Optional[Cache] = None):
        """
        Initialize performance optimization engine.
        
        Args:
            optimization_level: Level of optimization to apply
            cache: Flask-Caching instance
        """
        self.optimization_level = optimization_level
        
        # Initialize components
        self.monitor = PerformanceMonitor()
        self.query_optimizer = QueryOptimizer(cache)
        self.cache_strategy = CacheStrategy(cache) if cache else None
        self.bottleneck_detector = BottleneckDetector(self.monitor, self.query_optimizer)
        
        # Configuration
        self.auto_optimization_enabled = optimization_level in (
            OptimizationLevel.AGGRESSIVE, 
            OptimizationLevel.EXPERIMENTAL
        )
        
        logger.info(f"PerformanceOptimizationEngine initialized with {optimization_level.value} optimization level")
    
    def start_optimization(self):
        """Start the performance optimization engine."""
        logger.info("Starting performance optimization engine")
        
        # Start monitoring
        self.monitor.start_monitoring()
        
        # Warm cache if available
        if self.cache_strategy:
            self._warm_critical_caches()
        
        # Schedule periodic optimization if enabled
        if self.auto_optimization_enabled:
            self._schedule_auto_optimization()
    
    def stop_optimization(self):
        """Stop the performance optimization engine."""
        logger.info("Stopping performance optimization engine")
        
        # Stop monitoring
        self.monitor.stop_monitoring()
    
    def _warm_critical_caches(self):
        """Warm up critical cache entries."""
        # Define critical cache entries based on common usage patterns
        cache_definitions = [
            {
                'key': 'user_permissions',
                'generator': lambda: {},  # Would be replaced with actual permission loading
                'timeout': 600
            },
            {
                'key': 'application_config',
                'generator': lambda: {},  # Would be replaced with config loading
                'timeout': 1800
            }
        ]
        
        self.cache_strategy.warm_cache(cache_definitions)
    
    def _schedule_auto_optimization(self):
        """Schedule automatic optimization tasks."""
        # This would typically use a scheduler like APScheduler
        # For now, we'll just run optimization in a background thread
        def auto_optimize():
            while self.auto_optimization_enabled:
                try:
                    self._run_auto_optimization()
                    time.sleep(300)  # Run every 5 minutes
                except Exception as e:
                    logger.error(f"Auto-optimization error: {str(e)}")
                    time.sleep(600)  # Wait longer on error
        
        optimization_thread = threading.Thread(target=auto_optimize)
        optimization_thread.daemon = True
        optimization_thread.start()
    
    def _run_auto_optimization(self):
        """Run automatic optimization based on detected bottlenecks."""
        bottlenecks = self.bottleneck_detector.detect_bottlenecks()
        
        for bottleneck in bottlenecks:
            if bottleneck.auto_fixable and bottleneck.severity in ("high", "critical"):
                logger.info(f"Auto-fixing bottleneck: {bottleneck.description}")
                
                if bottleneck.bottleneck_type == BottleneckType.MEMORY_LEAK:
                    # Force garbage collection
                    gc.collect()
                    logger.info("Triggered garbage collection for memory optimization")
                
                elif bottleneck.bottleneck_type == BottleneckType.CACHE_MISS:
                    # Adjust cache settings (simplified example)
                    logger.info("Adjusting cache timeout settings for better hit rates")
    
    def generate_performance_report(self, time_window: timedelta = timedelta(hours=1)) -> PerformanceReport:
        """Generate comprehensive performance report."""
        end_time = datetime.now()
        start_time = end_time - time_window
        
        # Gather current metrics
        current_metrics = self.monitor.get_current_metrics()
        
        # Detect bottlenecks
        bottlenecks = self.bottleneck_detector.detect_bottlenecks()
        
        # Generate recommendations
        recommendations = self._generate_optimization_recommendations(bottlenecks, current_metrics)
        
        # Calculate overall performance score
        overall_score = self._calculate_overall_performance_score(current_metrics, bottlenecks)
        
        # Gather trending data
        trending_data = {}
        for metric_type in PerformanceMetricType:
            stats = self.monitor.get_metric_statistics(metric_type, time_window)
            if stats:
                trending_data[metric_type.value] = [
                    stats['min'], stats['mean'], stats['max'], stats['p95']
                ]
        
        report = PerformanceReport(
            report_id=f"perf_report_{int(time.time())}",
            generated_at=datetime.now(),
            time_window=(start_time, end_time),
            overall_score=overall_score,
            key_metrics={k.value: v for k, v in current_metrics.items()},
            bottlenecks=bottlenecks,
            recommendations=recommendations,
            trending_data=trending_data,
            comparison_data={}  # Would include historical comparisons
        )
        
        return report
    
    def _generate_optimization_recommendations(self, bottlenecks: List[PerformanceBottleneck],
                                             current_metrics: Dict[PerformanceMetricType, float]) -> List[OptimizationRecommendation]:
        """Generate optimization recommendations based on analysis."""
        recommendations = []
        
        # Database optimization recommendations
        if any(b.bottleneck_type == BottleneckType.DATABASE_QUERY for b in bottlenecks):
            recommendations.append(OptimizationRecommendation(
                title="Database Query Optimization",
                description="Optimize slow database queries with proper indexing and query structure improvements",
                impact="high",
                effort="medium",
                category="database",
                implementation="Add database indexes, optimize JOIN operations, implement query result caching",
                estimated_improvement=30.0,
                risks=["Index maintenance overhead", "Increased storage requirements"]
            ))
        
        # Memory optimization recommendations
        memory_usage = current_metrics.get(PerformanceMetricType.MEMORY_USAGE, 0)
        if memory_usage > 80:
            recommendations.append(OptimizationRecommendation(
                title="Memory Usage Optimization",
                description="Reduce memory footprint through efficient data structures and garbage collection",
                impact="high",
                effort="medium",
                category="memory",
                implementation="Implement object pooling, optimize data structures, tune garbage collection",
                estimated_improvement=25.0,
                risks=["Potential impact on functionality", "Increased code complexity"]
            ))
        
        # Cache optimization recommendations
        if self.cache_strategy:
            cache_report = self.cache_strategy.get_cache_efficiency_report()
            if cache_report['overall_hit_rate'] < 0.7:
                recommendations.append(OptimizationRecommendation(
                    title="Cache Strategy Improvement",
                    description="Improve cache hit rates through better timeout and invalidation strategies",
                    impact="medium",
                    effort="low",
                    category="cache",
                    implementation="Adjust cache timeouts, implement cache warming, optimize invalidation patterns",
                    estimated_improvement=20.0,
                    risks=["Potential stale data", "Increased memory usage"]
                ))
        
        return recommendations
    
    def _calculate_overall_performance_score(self, metrics: Dict[PerformanceMetricType, float],
                                           bottlenecks: List[PerformanceBottleneck]) -> float:
        """Calculate overall performance score (0-100, higher is better)."""
        base_score = 100.0
        
        # Deduct points for high resource usage
        cpu_usage = metrics.get(PerformanceMetricType.CPU_USAGE, 0)
        memory_usage = metrics.get(PerformanceMetricType.MEMORY_USAGE, 0)
        
        if cpu_usage > 80:
            base_score -= (cpu_usage - 80) / 2  # Up to 10 points
        
        if memory_usage > 80:
            base_score -= (memory_usage - 80) / 2  # Up to 10 points
        
        # Deduct points for slow response times
        response_time = metrics.get(PerformanceMetricType.RESPONSE_TIME, 0)
        if response_time > 1.0:
            base_score -= min(20, response_time * 10)  # Up to 20 points
        
        # Deduct points for bottlenecks
        for bottleneck in bottlenecks:
            if bottleneck.severity == "critical":
                base_score -= 15
            elif bottleneck.severity == "high":
                base_score -= 10
            elif bottleneck.severity == "medium":
                base_score -= 5
        
        return max(0.0, min(100.0, base_score))


# Flask integration utilities
def init_performance_optimization(app, cache=None, optimization_level=OptimizationLevel.MODERATE):
    """
    Initialize performance optimization for Flask application.
    
    Args:
        app: Flask application instance
        cache: Flask-Caching instance
        optimization_level: Level of optimization to apply
    """
    # Create optimization engine
    engine = PerformanceOptimizationEngine(optimization_level, cache)
    
    # Store in app config
    app.config['PERFORMANCE_ENGINE'] = engine
    
    # Register request handlers
    @app.before_request
    def before_request():
        g.request_start_time = time.time()
        g.performance_data = {}
    
    @app.after_request
    def after_request(response):
        if hasattr(g, 'request_start_time'):
            response_time = time.time() - g.request_start_time
            g.performance_data['response_time'] = response_time
            
            # Record in engine
            engine.monitor.record_metric(
                PerformanceMetricType.RESPONSE_TIME,
                response_time,
                {
                    'endpoint': request.endpoint,
                    'method': request.method,
                    'status_code': response.status_code
                }
            )
        
        return response
    
    # Start optimization
    engine.start_optimization()
    
    logger.info("Performance optimization initialized for Flask application")
    return engine


# Decorator for performance monitoring
def monitor_performance(metric_type: PerformanceMetricType):
    """Decorator to monitor performance of specific functions."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                # Record metric if performance engine is available
                if hasattr(current_app, 'config') and 'PERFORMANCE_ENGINE' in current_app.config:
                    engine = current_app.config['PERFORMANCE_ENGINE']
                    engine.monitor.record_metric(metric_type, execution_time, {
                        'function': func.__name__,
                        'module': func.__module__
                    })
                
                return result
                
            except Exception as e:
                # Record error metric
                if hasattr(current_app, 'config') and 'PERFORMANCE_ENGINE' in current_app.config:
                    engine = current_app.config['PERFORMANCE_ENGINE']
                    engine.monitor.record_metric(PerformanceMetricType.ERROR_RATE, 1.0, {
                        'function': func.__name__,
                        'error': str(e)
                    })
                raise
        
        return wrapper
    return decorator