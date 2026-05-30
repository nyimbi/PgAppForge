"""
Performance Optimization Engine for Graph Operations

Provides query optimization, caching, distributed processing, and scalability
enhancements for large-scale graph analysis operations.
"""

import json
import logging
import time
import threading
import hashlib
import pickle
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Union, Set, Callable
from dataclasses import dataclass, asdict, field
from enum import Enum
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import asyncio
import weakref

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

import numpy as np
import networkx as nx
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from .graph_manager import GraphDatabaseManager, get_graph_manager
from .multi_graph_manager import get_graph_registry
from .activity_tracker import track_database_activity, ActivityType

logger = logging.getLogger(__name__)


class OptimizationType(Enum):
    """Types of performance optimizations"""
    QUERY_CACHING = "query_caching"
    RESULT_CACHING = "result_caching"
    INDEX_OPTIMIZATION = "index_optimization"
    PARALLEL_PROCESSING = "parallel_processing"
    MEMORY_OPTIMIZATION = "memory_optimization"
    CONNECTION_POOLING = "connection_pooling"
    LAZY_LOADING = "lazy_loading"
    BATCH_PROCESSING = "batch_processing"


class CacheStrategy(Enum):
    """Cache eviction strategies"""
    LRU = "lru"
    LFU = "lfu"
    TTL = "ttl"
    FIFO = "fifo"


class ProcessingMode(Enum):
    """Processing modes for different operations"""
    SEQUENTIAL = "sequential"
    PARALLEL_THREADS = "parallel_threads"
    PARALLEL_PROCESSES = "parallel_processes"
    ASYNC = "async"
    DISTRIBUTED = "distributed"


@dataclass
class OptimizationMetrics:
    """
    Performance optimization metrics
    
    Attributes:
        operation_type: Type of operation
        execution_time: Total execution time
        cache_hit_ratio: Cache hit percentage
        memory_usage: Peak memory usage in MB
        cpu_utilization: CPU usage percentage
        throughput: Operations per second
        optimization_applied: Optimizations used
        timestamp: Measurement timestamp
    """
    
    operation_type: str
    execution_time: float
    cache_hit_ratio: float = 0.0
    memory_usage: float = 0.0
    cpu_utilization: float = 0.0
    throughput: float = 0.0
    optimization_applied: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class CacheEntry:
    """Cache entry with metadata"""
    key: str
    value: Any
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    size_bytes: int = 0
    ttl_seconds: int = 3600
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired"""
        if self.ttl_seconds <= 0:
            return False
        return datetime.now(tz=timezone.utc) - self.created_at > timedelta(seconds=self.ttl_seconds)


class InMemoryCache:
    """
    High-performance in-memory cache with multiple eviction strategies
    
    Provides LRU, LFU, TTL, and FIFO cache eviction policies with
    configurable size limits and automatic cleanup.
    """
    
    def __init__(self, max_size: int = 1000, strategy: CacheStrategy = CacheStrategy.LRU,
                 default_ttl: int = 3600):
        self.max_size = max_size
        self.strategy = strategy
        self.default_ttl = default_ttl
        self.cache: Dict[str, CacheEntry] = {}
        self.access_order: List[str] = []  # For LRU/FIFO
        self.access_counts: Dict[str, int] = {}  # For LFU
        self._lock = threading.RLock()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "total_requests": 0
        }
        
        # Start cleanup thread
        self._cleanup_thread = threading.Thread(target=self._cleanup_expired, daemon=True)
        self._cleanup_thread.start()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        with self._lock:
            self.stats["total_requests"] += 1
            
            if key not in self.cache:
                self.stats["misses"] += 1
                return None
            
            entry = self.cache[key]
            
            # Check expiration
            if entry.is_expired():
                del self.cache[key]
                self.access_order = [k for k in self.access_order if k != key]
                self.access_counts.pop(key, None)
                self.stats["misses"] += 1
                return None
            
            # Update access metadata
            entry.last_accessed = datetime.now(tz=timezone.utc)
            entry.access_count += 1
            
            # Update access order for LRU
            if self.strategy == CacheStrategy.LRU:
                if key in self.access_order:
                    self.access_order.remove(key)
                self.access_order.append(key)
            
            # Update access counts for LFU
            if self.strategy == CacheStrategy.LFU:
                self.access_counts[key] = self.access_counts.get(key, 0) + 1
            
            self.stats["hits"] += 1
            return entry.value
    
    def put(self, key: str, value: Any, ttl_seconds: int = None) -> bool:
        """Put value in cache"""
        with self._lock:
            # Calculate size estimate
            size_bytes = self._estimate_size(value)
            
            # Create cache entry
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=datetime.now(tz=timezone.utc),
                last_accessed=datetime.now(tz=timezone.utc),
                size_bytes=size_bytes,
                ttl_seconds=ttl_seconds or self.default_ttl
            )
            
            # Evict if necessary
            if len(self.cache) >= self.max_size and key not in self.cache:
                self._evict()
            
            # Store entry
            self.cache[key] = entry
            
            # Update tracking structures
            if self.strategy in [CacheStrategy.LRU, CacheStrategy.FIFO]:
                if key not in self.access_order:
                    self.access_order.append(key)
            
            if self.strategy == CacheStrategy.LFU:
                self.access_counts[key] = 1
            
            return True
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        with self._lock:
            if key in self.cache:
                del self.cache[key]
                self.access_order = [k for k in self.access_order if k != key]
                self.access_counts.pop(key, None)
                return True
            return False
    
    def clear(self):
        """Clear entire cache"""
        with self._lock:
            self.cache.clear()
            self.access_order.clear()
            self.access_counts.clear()
            self.stats = {
                "hits": 0,
                "misses": 0,
                "evictions": 0,
                "total_requests": 0
            }
    
    def _evict(self):
        """Evict entry based on strategy"""
        if not self.cache:
            return
        
        key_to_evict = None
        
        if self.strategy == CacheStrategy.LRU:
            key_to_evict = self.access_order[0]
        elif self.strategy == CacheStrategy.FIFO:
            key_to_evict = self.access_order[0]
        elif self.strategy == CacheStrategy.LFU:
            # Find key with minimum access count
            min_count = min(self.access_counts.values())
            for key, count in self.access_counts.items():
                if count == min_count:
                    key_to_evict = key
                    break
        elif self.strategy == CacheStrategy.TTL:
            # Find oldest expired entry
            oldest_time = datetime.now(tz=timezone.utc)
            for key, entry in self.cache.items():
                if entry.is_expired() and entry.created_at < oldest_time:
                    oldest_time = entry.created_at
                    key_to_evict = key
        
        if key_to_evict:
            del self.cache[key_to_evict]
            self.access_order = [k for k in self.access_order if k != key_to_evict]
            self.access_counts.pop(key_to_evict, None)
            self.stats["evictions"] += 1
    
    def _cleanup_expired(self):
        """Background cleanup of expired entries"""
        while True:
            try:
                time.sleep(60)  # Check every minute
                
                with self._lock:
                    expired_keys = [
                        key for key, entry in self.cache.items()
                        if entry.is_expired()
                    ]
                    
                    for key in expired_keys:
                        del self.cache[key]
                        self.access_order = [k for k in self.access_order if k != key]
                        self.access_counts.pop(key, None)
                        self.stats["evictions"] += 1
                
            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")
    
    def _estimate_size(self, value: Any) -> int:
        """Estimate memory size of value"""
        try:
            if isinstance(value, (str, bytes)):
                return len(value)
            elif isinstance(value, (int, float)):
                return 8
            elif isinstance(value, (list, tuple)):
                return sum(self._estimate_size(item) for item in value[:10])  # Sample first 10
            elif isinstance(value, dict):
                return sum(self._estimate_size(k) + self._estimate_size(v) 
                          for k, v in list(value.items())[:10])  # Sample first 10
            else:
                return len(str(value))
        except:
            return 1000  # Default estimate
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            hit_rate = self.stats["hits"] / max(self.stats["total_requests"], 1)
            total_size = sum(entry.size_bytes for entry in self.cache.values())
            
            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "hit_rate": hit_rate,
                "total_size_mb": total_size / 1024 / 1024,
                "strategy": self.strategy.value,
                "stats": self.stats.copy()
            }


class QueryOptimizer:
    """
    Query optimization engine for graph operations
    
    Analyzes query patterns, suggests optimizations, and applies
    automatic query rewriting for improved performance.
    """
    
    def __init__(self):
        self.query_patterns = {}
        self.optimization_rules = self._load_optimization_rules()
        self.execution_cache = InMemoryCache(max_size=500, strategy=CacheStrategy.LRU)
    
    def _load_optimization_rules(self) -> List[Dict[str, Any]]:
        """Load query optimization rules"""
        return [
            {
                "name": "add_limit_to_match",
                "pattern": r"MATCH\s+.*\s+RETURN",
                "condition": lambda query: "LIMIT" not in query.upper() and "MATCH" in query.upper(),
                "rewrite": lambda query: query.rstrip() + " LIMIT 1000",
                "description": "Add LIMIT clause to prevent large result sets"
            },
            {
                "name": "optimize_cartesian_product",
                "pattern": r"MATCH\s+.*,\s*MATCH",
                "condition": lambda query: re.search(r"MATCH\s+.*,\s*MATCH", query, re.IGNORECASE),
                "rewrite": lambda query: query.replace("MATCH", "MATCH").replace(", MATCH", " MATCH"),
                "description": "Convert cartesian product to path pattern"
            },
            {
                "name": "add_index_hints",
                "pattern": r"WHERE\s+\w+\.\w+\s*=",
                "condition": lambda query: re.search(r"WHERE\s+\w+\.\w+\s*=", query, re.IGNORECASE),
                "rewrite": self._add_index_hints,
                "description": "Add index hints for property equality filters"
            },
            {
                "name": "optimize_aggregation",
                "pattern": r"RETURN\s+count\(",
                "condition": lambda query: "count(" in query.lower() and "with" not in query.lower(),
                "rewrite": lambda query: query.replace("RETURN count(", "WITH count(") + " RETURN *",
                "description": "Use WITH clause for aggregation optimization"
            }
        ]
    
    def optimize_query(self, query: str, graph_name: str = None) -> Dict[str, Any]:
        """
        Optimize Cypher query for better performance
        
        Args:
            query: Original Cypher query
            graph_name: Target graph name
            
        Returns:
            Dictionary with optimized query and applied optimizations
        """
        try:
            import re
            
            optimized_query = query
            applied_optimizations = []
            
            # Apply optimization rules
            for rule in self.optimization_rules:
                if rule["condition"](optimized_query):
                    if callable(rule["rewrite"]):
                        new_query = rule["rewrite"](optimized_query)
                    else:
                        new_query = rule["rewrite"]
                    
                    if new_query != optimized_query:
                        optimized_query = new_query
                        applied_optimizations.append({
                            "rule": rule["name"],
                            "description": rule["description"]
                        })
            
            # Analyze query complexity
            complexity_score = self._calculate_query_complexity(optimized_query)
            
            # Generate execution plan hints
            execution_hints = self._generate_execution_hints(optimized_query, graph_name)
            
            return {
                "original_query": query,
                "optimized_query": optimized_query,
                "applied_optimizations": applied_optimizations,
                "complexity_score": complexity_score,
                "execution_hints": execution_hints,
                "optimization_applied": len(applied_optimizations) > 0
            }
            
        except Exception as e:
            logger.error(f"Query optimization failed: {e}")
            return {
                "original_query": query,
                "optimized_query": query,
                "applied_optimizations": [],
                "error": str(e)
            }
    
    def _add_index_hints(self, query: str) -> str:
        """Add index hints to query"""
        # This is a simplified implementation
        # In production, this would analyze actual indexes
        return query + " /* USE INDEX */"""
    
    def _calculate_query_complexity(self, query: str) -> int:
        """Calculate query complexity score"""
        import re
        
        score = 0
        query_upper = query.upper()
        
        # Basic clause complexity
        score += len(re.findall(r'\bMATCH\b', query_upper)) * 2
        score += len(re.findall(r'\bWHERE\b', query_upper)) * 1
        score += len(re.findall(r'\bRETURN\b', query_upper)) * 1
        score += len(re.findall(r'\bWITH\b', query_upper)) * 2
        
        # Path complexity
        score += len(re.findall(r'-\[.*?\]-', query)) * 3
        score += len(re.findall(r'-\[.*?\*.*?\]-', query)) * 5  # Variable length paths
        
        # Aggregation complexity
        score += len(re.findall(r'\b(COUNT|SUM|AVG|MIN|MAX|COLLECT)\b', query_upper)) * 2
        
        # Subquery complexity
        score += len(re.findall(r'\{.*?\}', query)) * 4
        
        return min(score, 100)  # Cap at 100
    
    def _generate_execution_hints(self, query: str, graph_name: str = None) -> List[str]:
        """Generate execution hints for query"""
        hints = []
        query_upper = query.upper()
        
        # LIMIT hints
        if "LIMIT" not in query_upper and "MATCH" in query_upper:
            hints.append("Consider adding LIMIT clause for large datasets")
        
        # Index hints
        if re.search(r'WHERE\s+\w+\.\w+\s*=', query, re.IGNORECASE):
            hints.append("Ensure indexes exist on filtered properties")
        
        # Aggregation hints
        if any(agg in query_upper for agg in ["COUNT", "SUM", "AVG"]):
            hints.append("Consider using WITH clause for complex aggregations")
        
        # Path hints
        if re.search(r'-\[.*?\*.*?\]-', query):
            hints.append("Variable length paths can be expensive - consider limiting depth")
        
        return hints
    
    def cache_query_result(self, query: str, parameters: Dict[str, Any], 
                          result: Dict[str, Any], ttl_seconds: int = 3600):
        """Cache query result for future use"""
        cache_key = self._generate_cache_key(query, parameters)
        self.execution_cache.put(cache_key, result, ttl_seconds)
    
    def get_cached_result(self, query: str, parameters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached query result"""
        cache_key = self._generate_cache_key(query, parameters)
        return self.execution_cache.get(cache_key)
    
    def _generate_cache_key(self, query: str, parameters: Dict[str, Any]) -> str:
        """Generate cache key for query and parameters"""
        query_normalized = re.sub(r'\s+', ' ', query.strip().lower())
        params_str = json.dumps(parameters, sort_keys=True) if parameters else ""
        combined = f"{query_normalized}|{params_str}"
        return hashlib.md5(combined.encode()).hexdigest()


class ParallelProcessor:
    """
    Parallel processing engine for graph operations
    
    Provides thread and process-based parallelization for CPU-intensive
    graph analysis tasks with automatic workload distribution.
    """
    
    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers or min(32, (4 + 1) * 4)  # Conservative default
        self.thread_pool = ThreadPoolExecutor(max_workers=self.max_workers // 2)
        self.process_pool = ProcessPoolExecutor(max_workers=min(4, self.max_workers // 4))
        self.active_tasks = weakref.WeakSet()
    
    def execute_parallel(self, func: Callable, data_chunks: List[Any], 
                        mode: ProcessingMode = ProcessingMode.PARALLEL_THREADS) -> List[Any]:
        """
        Execute function in parallel across data chunks
        
        Args:
            func: Function to execute
            data_chunks: List of data chunks to process
            mode: Processing mode (threads vs processes)
            
        Returns:
            List of results from parallel execution
        """
        if not data_chunks:
            return []
        
        try:
            results = []
            
            if mode == ProcessingMode.PARALLEL_THREADS:
                futures = {
                    self.thread_pool.submit(func, chunk): i 
                    for i, chunk in enumerate(data_chunks)
                }
                
                for future in as_completed(futures):
                    try:
                        result = future.result(timeout=300)  # 5 minute timeout
                        results.append((futures[future], result))
                    except Exception as e:
                        logger.error(f"Parallel task failed: {e}")
                        results.append((futures[future], None))
                
            elif mode == ProcessingMode.PARALLEL_PROCESSES:
                futures = {
                    self.process_pool.submit(func, chunk): i 
                    for i, chunk in enumerate(data_chunks)
                }
                
                for future in as_completed(futures):
                    try:
                        result = future.result(timeout=600)  # 10 minute timeout
                        results.append((futures[future], result))
                    except Exception as e:
                        logger.error(f"Parallel process failed: {e}")
                        results.append((futures[future], None))
            
            else:  # Sequential fallback
                for i, chunk in enumerate(data_chunks):
                    try:
                        result = func(chunk)
                        results.append((i, result))
                    except Exception as e:
                        logger.error(f"Sequential task failed: {e}")
                        results.append((i, None))
            
            # Sort results by original order
            results.sort(key=lambda x: x[0])
            return [result for _, result in results]
            
        except Exception as e:
            logger.error(f"Parallel execution failed: {e}")
            # Fallback to sequential processing
            return [func(chunk) for chunk in data_chunks]
    
    def chunk_data(self, data: List[Any], chunk_size: int = None) -> List[List[Any]]:
        """Split data into chunks for parallel processing"""
        if chunk_size is None:
            chunk_size = max(1, len(data) // self.max_workers)
        
        chunks = []
        for i in range(0, len(data), chunk_size):
            chunks.append(data[i:i + chunk_size])
        
        return chunks
    
    def shutdown(self):
        """Shutdown thread and process pools"""
        self.thread_pool.shutdown(wait=True)
        self.process_pool.shutdown(wait=True)


class PerformanceMonitor:
    """
    Performance monitoring and metrics collection
    
    Tracks execution times, resource usage, and optimization effectiveness
    for continuous performance improvement.
    """
    
    def __init__(self):
        self.metrics_history: List[OptimizationMetrics] = []
        self.operation_stats = {}
        self._lock = threading.Lock()
    
    def start_operation(self, operation_type: str) -> str:
        """Start monitoring an operation"""
        operation_id = f"{operation_type}_{int(time.time() * 1000)}"
        
        with self._lock:
            self.operation_stats[operation_id] = {
                "operation_type": operation_type,
                "start_time": time.time(),
                "start_memory": self._get_memory_usage()
            }
        
        return operation_id
    
    def end_operation(self, operation_id: str, cache_hit: bool = False,
                     optimizations: List[str] = None) -> OptimizationMetrics:
        """End monitoring an operation and record metrics"""
        with self._lock:
            if operation_id not in self.operation_stats:
                return None
            
            start_info = self.operation_stats.pop(operation_id)
            end_time = time.time()
            end_memory = self._get_memory_usage()
            
            execution_time = end_time - start_info["start_time"]
            memory_usage = max(0, end_memory - start_info["start_memory"])
            
            metrics = OptimizationMetrics(
                operation_type=start_info["operation_type"],
                execution_time=execution_time,
                cache_hit_ratio=1.0 if cache_hit else 0.0,
                memory_usage=memory_usage,
                optimization_applied=optimizations or []
            )
            
            self.metrics_history.append(metrics)
            
            # Keep only recent metrics
            if len(self.metrics_history) > 1000:
                self.metrics_history = self.metrics_history[-800:]
            
            return metrics
    
    def get_performance_summary(self, operation_type: str = None,
                               hours_back: int = 24) -> Dict[str, Any]:
        """Get performance summary for operations"""
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
        
        relevant_metrics = [
            m for m in self.metrics_history
            if m.timestamp >= cutoff_time and (
                operation_type is None or m.operation_type == operation_type
            )
        ]
        
        if not relevant_metrics:
            return {"message": "No metrics available for the specified period"}
        
        # Calculate summary statistics
        execution_times = [m.execution_time for m in relevant_metrics]
        memory_usages = [m.memory_usage for m in relevant_metrics]
        cache_hits = [m.cache_hit_ratio for m in relevant_metrics]
        
        summary = {
            "total_operations": len(relevant_metrics),
            "avg_execution_time": np.mean(execution_times),
            "min_execution_time": min(execution_times),
            "max_execution_time": max(execution_times),
            "p95_execution_time": np.percentile(execution_times, 95),
            "avg_memory_usage": np.mean(memory_usages),
            "peak_memory_usage": max(memory_usages),
            "overall_cache_hit_rate": np.mean(cache_hits),
            "optimization_frequency": self._calculate_optimization_frequency(relevant_metrics),
            "performance_trend": self._calculate_performance_trend(relevant_metrics)
        }
        
        return summary
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0
        except Exception:
            return 0.0
    
    def _calculate_optimization_frequency(self, metrics: List[OptimizationMetrics]) -> Dict[str, int]:
        """Calculate frequency of different optimizations"""
        optimization_counts = {}
        
        for metric in metrics:
            for opt in metric.optimization_applied:
                optimization_counts[opt] = optimization_counts.get(opt, 0) + 1
        
        return optimization_counts
    
    def _calculate_performance_trend(self, metrics: List[OptimizationMetrics]) -> str:
        """Calculate overall performance trend"""
        if len(metrics) < 10:
            return "insufficient_data"
        
        # Compare first half with second half
        mid_point = len(metrics) // 2
        first_half_avg = np.mean([m.execution_time for m in metrics[:mid_point]])
        second_half_avg = np.mean([m.execution_time for m in metrics[mid_point:]])
        
        improvement_ratio = (first_half_avg - second_half_avg) / first_half_avg
        
        if improvement_ratio > 0.1:
            return "improving"
        elif improvement_ratio < -0.1:
            return "degrading"
        else:
            return "stable"


class DistributedGraphProcessor:
    """
    Distributed processing coordinator for large-scale graph operations
    
    Coordinates work across multiple nodes for scalable graph analysis.
    Note: This is a simplified implementation for demonstration.
    """
    
    def __init__(self):
        self.nodes = []
        self.task_queue = []
        self.results = {}
        self._lock = threading.Lock()
    
    def register_node(self, node_id: str, capabilities: Dict[str, Any]):
        """Register a processing node"""
        with self._lock:
            self.nodes.append({
                "id": node_id,
                "capabilities": capabilities,
                "status": "available",
                "last_seen": datetime.now(tz=timezone.utc)
            })
    
    def distribute_graph_analysis(self, graph_name: str, analysis_type: str,
                                 partition_strategy: str = "node_based") -> str:
        """
        Distribute graph analysis across available nodes
        
        Returns:
            Task ID for tracking distributed operation
        """
        task_id = f"dist_{analysis_type}_{int(time.time())}"
        
        # This is a simplified implementation
        # In production, this would:
        # 1. Partition the graph based on strategy
        # 2. Distribute partitions to available nodes
        # 3. Coordinate execution and collect results
        # 4. Merge results from all nodes
        
        with self._lock:
            self.task_queue.append({
                "task_id": task_id,
                "graph_name": graph_name,
                "analysis_type": analysis_type,
                "partition_strategy": partition_strategy,
                "status": "queued",
                "created_at": datetime.now(tz=timezone.utc)
            })
        
        return task_id
    
    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get status of distributed task"""
        with self._lock:
            for task in self.task_queue:
                if task["task_id"] == task_id:
                    return task
            
            if task_id in self.results:
                return {
                    "task_id": task_id,
                    "status": "completed",
                    "result": self.results[task_id]
                }
        
        return {"task_id": task_id, "status": "not_found"}


def performance_cache(ttl_seconds: int = 3600, cache_size: int = 100):
    """Decorator for caching function results with performance monitoring"""
    
    # Create cache instance for this decorator
    cache = InMemoryCache(max_size=cache_size, default_ttl=ttl_seconds)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = hashlib.md5(
                f"{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}".encode()
            ).hexdigest()
            
            # Try cache first
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                cache.put(cache_key, result)
                
                execution_time = time.time() - start_time
                logger.debug(f"Function {func.__name__} executed in {execution_time:.3f}s (cached)")
                
                return result
            except Exception as e:
                logger.error(f"Cached function {func.__name__} failed: {e}")
                raise
        
        # Add cache statistics method
        wrapper.cache_stats = cache.get_stats
        wrapper.clear_cache = cache.clear
        
        return wrapper
    
    return decorator


# Global performance optimization instances
_query_optimizer = None
_parallel_processor = None
_performance_monitor = None
_distributed_processor = None


def get_query_optimizer() -> QueryOptimizer:
    """Get or create global query optimizer instance"""
    global _query_optimizer
    if _query_optimizer is None:
        _query_optimizer = QueryOptimizer()
    return _query_optimizer


def get_parallel_processor() -> ParallelProcessor:
    """Get or create global parallel processor instance"""
    global _parallel_processor
    if _parallel_processor is None:
        _parallel_processor = ParallelProcessor()
    return _parallel_processor


def get_performance_monitor() -> PerformanceMonitor:
    """Get or create global performance monitor instance"""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor


def get_distributed_processor() -> DistributedGraphProcessor:
    """Get or create global distributed processor instance"""
    global _distributed_processor
    if _distributed_processor is None:
        _distributed_processor = DistributedGraphProcessor()
    return _distributed_processor