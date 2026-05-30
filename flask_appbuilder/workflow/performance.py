"""
Performance Optimization and Caching System for Flask-AppBuilder Workflows

Provides comprehensive performance enhancements including:
- Redis-based caching for workflow state and definitions
- Database query optimization and connection pooling
- Lazy loading and pagination for large datasets
- Memory optimization and garbage collection
- Async processing for non-blocking operations
- Performance monitoring and metrics collection
- Cache invalidation strategies
- Batch processing capabilities
"""

import logging
import json
import time
import functools
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union, Callable, TYPE_CHECKING
from dataclasses import dataclass, asdict
from enum import Enum
import threading
import asyncio
from concurrent.futures import ThreadPoolExecutor
import weakref

from flask import current_app, g, request
from flask_caching import Cache
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.engine import Engine
from redis import Redis
import pickle

from ..models.mixins import AuditMixin
from .core import WorkflowState, WorkflowDefinition, get_workflow_engine

if TYPE_CHECKING:
    from .core import WorkflowStepDefinition

log = logging.getLogger(__name__)


class CacheStrategy(Enum):
    """Caching strategies for different data types."""
    NO_CACHE = "no_cache"
    MEMORY_ONLY = "memory_only"
    REDIS_ONLY = "redis_only"
    HYBRID = "hybrid"
    PERSISTENT = "persistent"


class PerformanceMetrics:
    """Tracks performance metrics for workflows."""
    
    def __init__(self):
        self.query_times = []
        self.cache_hits = 0
        self.cache_misses = 0
        self.workflow_execution_times = {}
        self.memory_usage = {}
        self._lock = threading.Lock()

    def record_query_time(self, duration: float):
        """Record database query execution time."""
        with self._lock:
            self.query_times.append(duration)
            # Keep only recent 1000 queries
            if len(self.query_times) > 1000:
                self.query_times = self.query_times[-1000:]

    def record_cache_hit(self):
        """Record cache hit."""
        with self._lock:
            self.cache_hits += 1

    def record_cache_miss(self):
        """Record cache miss."""
        with self._lock:
            self.cache_misses += 1

    def get_cache_hit_ratio(self) -> float:
        """Get cache hit ratio."""
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    def get_avg_query_time(self) -> float:
        """Get average query execution time."""
        return sum(self.query_times) / len(self.query_times) if self.query_times else 0.0


@dataclass
class CacheConfig:
    """Configuration for caching behavior."""
    strategy: CacheStrategy
    ttl: int  # Time to live in seconds
    max_memory: int  # Maximum memory usage in bytes
    compression: bool
    serialization: str  # 'json', 'pickle', 'msgpack'
    key_prefix: str


class WorkflowCache:
    """
    High-performance caching system for workflows.
    """

    def __init__(self):
        self.redis_client = None
        self.memory_cache = {}
        self.cache_configs = {}
        self.metrics = PerformanceMetrics()
        self._memory_lock = threading.RLock()
        self._setup_cache_backends()
        self._setup_default_configs()

    def _setup_cache_backends(self):
        """Setup caching backends."""
        
        # Setup Redis
        redis_config = current_app.config.get('REDIS_CONFIG', {})
        if redis_config:
            try:
                self.redis_client = Redis(
                    host=redis_config.get('host', 'localhost'),
                    port=redis_config.get('port', 6379),
                    db=redis_config.get('db', 1),  # Use different DB for cache
                    password=redis_config.get('password'),
                    decode_responses=False  # For binary data
                )
                self.redis_client.ping()
                log.info("Redis cache backend initialized")
            except Exception as e:
                log.warning(f"Redis cache unavailable: {e}")
                self.redis_client = None

        # Setup Flask-Caching
        try:
            self.flask_cache = Cache(current_app)
            log.info("Flask-Caching initialized")
        except Exception as e:
            log.warning(f"Flask-Caching unavailable: {e}")
            self.flask_cache = None

    def _setup_default_configs(self):
        """Setup default cache configurations."""
        
        self.cache_configs = {
            'workflow_definitions': CacheConfig(
                strategy=CacheStrategy.HYBRID,
                ttl=3600,  # 1 hour
                max_memory=10 * 1024 * 1024,  # 10MB
                compression=True,
                serialization='pickle',
                key_prefix='wd:'
            ),
            'workflow_states': CacheConfig(
                strategy=CacheStrategy.REDIS_ONLY,
                ttl=1800,  # 30 minutes
                max_memory=50 * 1024 * 1024,  # 50MB
                compression=True,
                serialization='pickle',
                key_prefix='ws:'
            ),
            'form_data': CacheConfig(
                strategy=CacheStrategy.HYBRID,
                ttl=900,  # 15 minutes
                max_memory=20 * 1024 * 1024,  # 20MB
                compression=False,
                serialization='json',
                key_prefix='fd:'
            ),
            'user_sessions': CacheConfig(
                strategy=CacheStrategy.MEMORY_ONLY,
                ttl=3600,  # 1 hour
                max_memory=5 * 1024 * 1024,  # 5MB
                compression=False,
                serialization='json',
                key_prefix='us:'
            ),
            'analytics': CacheConfig(
                strategy=CacheStrategy.PERSISTENT,
                ttl=86400,  # 24 hours
                max_memory=100 * 1024 * 1024,  # 100MB
                compression=True,
                serialization='pickle',
                key_prefix='an:'
            )
        }

    def get(self, key: str, cache_type: str = 'workflow_states') -> Optional[Any]:
        """Get value from cache."""
        config = self.cache_configs.get(cache_type)
        if not config:
            return None

        cache_key = f"{config.key_prefix}{key}"
        
        try:
            # Try memory cache first for hybrid strategy
            if config.strategy in [CacheStrategy.MEMORY_ONLY, CacheStrategy.HYBRID]:
                with self._memory_lock:
                    if cache_key in self.memory_cache:
                        entry = self.memory_cache[cache_key]
                        if entry['expires_at'] > datetime.now(tz=timezone.utc):
                            self.metrics.record_cache_hit()
                            return self._deserialize(entry['data'], config.serialization)
                        else:
                            del self.memory_cache[cache_key]

            # Try Redis cache
            if config.strategy in [CacheStrategy.REDIS_ONLY, CacheStrategy.HYBRID, CacheStrategy.PERSISTENT] and self.redis_client:
                data = self.redis_client.get(cache_key)
                if data:
                    self.metrics.record_cache_hit()
                    
                    # Decompress if needed
                    if config.compression:
                        import gzip
                        data = gzip.decompress(data)
                    
                    return self._deserialize(data, config.serialization)

            self.metrics.record_cache_miss()
            return None

        except Exception as e:
            log.error(f"Cache get error for key {cache_key}: {e}")
            self.metrics.record_cache_miss()
            return None

    def set(self, key: str, value: Any, cache_type: str = 'workflow_states', ttl: Optional[int] = None) -> bool:
        """Set value in cache."""
        config = self.cache_configs.get(cache_type)
        if not config:
            return False

        cache_key = f"{config.key_prefix}{key}"
        ttl = ttl or config.ttl
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=ttl)
        
        try:
            # Serialize data
            serialized_data = self._serialize(value, config.serialization)
            
            # Compress if configured
            if config.compression:
                import gzip
                serialized_data = gzip.compress(serialized_data)

            # Store in memory cache
            if config.strategy in [CacheStrategy.MEMORY_ONLY, CacheStrategy.HYBRID]:
                with self._memory_lock:
                    self.memory_cache[cache_key] = {
                        'data': serialized_data,
                        'expires_at': expires_at
                    }
                    self._cleanup_memory_cache(config)

            # Store in Redis cache
            if config.strategy in [CacheStrategy.REDIS_ONLY, CacheStrategy.HYBRID, CacheStrategy.PERSISTENT] and self.redis_client:
                self.redis_client.setex(cache_key, ttl, serialized_data)

            return True

        except Exception as e:
            log.error(f"Cache set error for key {cache_key}: {e}")
            return False

    def delete(self, key: str, cache_type: str = 'workflow_states') -> bool:
        """Delete value from cache."""
        config = self.cache_configs.get(cache_type)
        if not config:
            return False

        cache_key = f"{config.key_prefix}{key}"
        
        try:
            # Remove from memory cache
            with self._memory_lock:
                self.memory_cache.pop(cache_key, None)

            # Remove from Redis cache
            if self.redis_client:
                self.redis_client.delete(cache_key)

            return True

        except Exception as e:
            log.error(f"Cache delete error for key {cache_key}: {e}")
            return False

    def invalidate_pattern(self, pattern: str, cache_type: str = 'workflow_states'):
        """Invalidate cache entries matching pattern."""
        config = self.cache_configs.get(cache_type)
        if not config:
            return

        full_pattern = f"{config.key_prefix}{pattern}"
        
        try:
            # Clear matching entries from memory cache
            with self._memory_lock:
                keys_to_delete = [key for key in self.memory_cache.keys() if self._matches_pattern(key, full_pattern)]
                for key in keys_to_delete:
                    del self.memory_cache[key]

            # Clear matching entries from Redis
            if self.redis_client:
                keys = self.redis_client.keys(full_pattern)
                if keys:
                    self.redis_client.delete(*keys)

        except Exception as e:
            log.error(f"Cache invalidation error for pattern {full_pattern}: {e}")

    def _serialize(self, data: Any, method: str) -> bytes:
        """Serialize data using specified method."""
        if method == 'json':
            return json.dumps(data).encode('utf-8')
        elif method == 'pickle':
            return pickle.dumps(data)
        elif method == 'msgpack':
            try:
                import msgpack
                return msgpack.packb(data)
            except ImportError:
                return pickle.dumps(data)
        else:
            return pickle.dumps(data)

    def _deserialize(self, data: bytes, method: str) -> Any:
        """Deserialize data using specified method."""
        if method == 'json':
            return json.loads(data.decode('utf-8'))
        elif method == 'pickle':
            return pickle.loads(data)
        elif method == 'msgpack':
            try:
                import msgpack
                return msgpack.unpackb(data)
            except ImportError:
                return pickle.loads(data)
        else:
            return pickle.loads(data)

    def _matches_pattern(self, key: str, pattern: str) -> bool:
        """Check if key matches pattern (simple wildcard support)."""
        if '*' not in pattern:
            return key == pattern
        
        # Simple wildcard matching
        import re
        regex_pattern = pattern.replace('*', '.*')
        return re.match(regex_pattern, key) is not None

    def _cleanup_memory_cache(self, config: CacheConfig):
        """Clean up expired entries and enforce memory limits."""
        now = datetime.now(tz=timezone.utc)
        
        # Remove expired entries
        expired_keys = [
            key for key, entry in self.memory_cache.items()
            if entry['expires_at'] <= now
        ]
        
        for key in expired_keys:
            del self.memory_cache[key]

        # Check memory usage and remove oldest entries if needed
        if config.max_memory > 0:
            current_size = sum(len(str(entry)) for entry in self.memory_cache.values())
            
            if current_size > config.max_memory:
                # Sort by expiration time and remove oldest
                sorted_entries = sorted(
                    self.memory_cache.items(),
                    key=lambda x: x[1]['expires_at']
                )
                
                for key, _ in sorted_entries:
                    del self.memory_cache[key]
                    current_size = sum(len(str(entry)) for entry in self.memory_cache.values())
                    if current_size <= config.max_memory * 0.8:  # 80% threshold
                        break

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'cache_hit_ratio': self.metrics.get_cache_hit_ratio(),
            'cache_hits': self.metrics.cache_hits,
            'cache_misses': self.metrics.cache_misses,
            'memory_cache_size': len(self.memory_cache),
            'avg_query_time': self.metrics.get_avg_query_time(),
            'redis_available': self.redis_client is not None
        }


class QueryOptimizer:
    """
    Database query optimization for workflows.
    """

    def __init__(self):
        self.query_cache = WorkflowCache()
        self.connection_pool = None
        self._setup_query_monitoring()

    def _setup_query_monitoring(self):
        """Setup query monitoring and optimization."""
        
        @event.listens_for(Engine, "before_cursor_execute")
        def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            context._query_start_time = time.time()

        @event.listens_for(Engine, "after_cursor_execute")
        def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            total_time = time.time() - context._query_start_time
            self.query_cache.metrics.record_query_time(total_time)
            
            # Log slow queries
            if total_time > 1.0:  # Queries longer than 1 second
                log.warning(f"Slow query detected ({total_time:.2f}s): {statement[:200]}...")

    def optimize_workflow_queries(self):
        """Apply query optimizations for workflow operations."""
        
        # Add indexes for common queries
        optimization_sql = [
            # Index for workflow state lookups
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_states_name_status 
            ON ab_workflow_states(workflow_name, status);
            """,
            
            # Index for step lookups
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_states_current_step 
            ON ab_workflow_states(current_step);
            """,
            
            # Index for user workflow lookups
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_states_entity 
            ON ab_workflow_states(entity_type, entity_id);
            """,
            
            # Index for analytics queries
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_analytics_name_created 
            ON ab_workflow_analytics(workflow_name, created_on);
            """,
            
            # Index for collaboration sessions
            """
            CREATE INDEX IF NOT EXISTS idx_collaboration_sessions_workflow_active 
            ON ab_workflow_collaboration_sessions(workflow_state_id, is_active);
            """
        ]

        try:
            from ..models import db
            
            for sql in optimization_sql:
                try:
                    db.session.execute(text(sql))
                    db.session.commit()
                except Exception as e:
                    log.debug(f"Index creation skipped (may already exist): {e}")
                    db.session.rollback()

            log.info("Database query optimizations applied")

        except Exception as e:
            log.error(f"Error applying query optimizations: {e}")


class WorkflowBatchProcessor:
    """
    Batch processing for workflow operations.
    """

    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.pending_operations = []
        self._lock = threading.Lock()

    def add_operation(self, operation_type: str, data: Dict[str, Any]):
        """Add operation to batch queue."""
        with self._lock:
            self.pending_operations.append({
                'type': operation_type,
                'data': data,
                'timestamp': datetime.now(tz=timezone.utc)
            })

            if len(self.pending_operations) >= self.batch_size:
                self._process_batch()

    def _process_batch(self):
        """Process pending operations in batch."""
        if not self.pending_operations:
            return

        operations = self.pending_operations.copy()
        self.pending_operations.clear()

        # Submit batch processing to thread pool
        future = self.executor.submit(self._execute_batch, operations)
        return future

    def _execute_batch(self, operations: List[Dict[str, Any]]):
        """Execute batch of operations."""
        from ..models import db

        try:
            # Group operations by type
            grouped_ops = {}
            for op in operations:
                op_type = op['type']
                if op_type not in grouped_ops:
                    grouped_ops[op_type] = []
                grouped_ops[op_type].append(op['data'])

            # Process each type
            for op_type, op_data_list in grouped_ops.items():
                if op_type == 'analytics_insert':
                    self._batch_insert_analytics(op_data_list)
                elif op_type == 'snapshot_create':
                    self._batch_create_snapshots(op_data_list)
                elif op_type == 'cache_invalidate':
                    self._batch_invalidate_cache(op_data_list)

            db.session.commit()
            log.debug(f"Processed batch of {len(operations)} operations")

        except Exception as e:
            log.error(f"Batch processing error: {e}")
            db.session.rollback()

    def _batch_insert_analytics(self, analytics_data: List[Dict[str, Any]]):
        """Batch insert analytics records."""
        from ..models import db
        from .ai_optimization import WorkflowAnalytics
        from uuid_extensions import uuid7str

        analytics_records = []
        for data in analytics_data:
            record = WorkflowAnalytics(
                id=uuid7str(),
                **data
            )
            analytics_records.append(record)

        db.session.bulk_save_objects(analytics_records)

    def _batch_create_snapshots(self, snapshot_data: List[Dict[str, Any]]):
        """Batch create workflow snapshots."""
        from ..models import db
        from .persistence import WorkflowStateSnapshot
        from uuid_extensions import uuid7str

        snapshot_records = []
        for data in snapshot_data:
            record = WorkflowStateSnapshot(
                id=uuid7str(),
                **data
            )
            snapshot_records.append(record)

        db.session.bulk_save_objects(snapshot_records)

    def _batch_invalidate_cache(self, cache_data: List[Dict[str, Any]]):
        """Batch invalidate cache entries."""
        cache = get_workflow_cache()
        
        for data in cache_data:
            cache.invalidate_pattern(
                data['pattern'],
                data.get('cache_type', 'workflow_states')
            )

    def force_process(self):
        """Force process all pending operations."""
        with self._lock:
            if self.pending_operations:
                self._process_batch()

    def shutdown(self):
        """Shutdown batch processor."""
        self.force_process()
        self.executor.shutdown(wait=True)


class AsyncWorkflowProcessor:
    """
    Asynchronous workflow processing for non-blocking operations.
    """

    def __init__(self):
        self.task_queue = asyncio.Queue()
        self.running = False
        self.loop = None

    async def start(self):
        """Start async processing loop."""
        self.running = True
        self.loop = asyncio.get_event_loop()
        
        while self.running:
            try:
                # Wait for task with timeout
                task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                await self._process_task(task)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log.error(f"Async processing error: {e}")

    async def add_task(self, task_type: str, data: Dict[str, Any]):
        """Add async task to queue."""
        task = {
            'type': task_type,
            'data': data,
            'timestamp': datetime.now(tz=timezone.utc)
        }
        await self.task_queue.put(task)

    async def _process_task(self, task: Dict[str, Any]):
        """Process individual async task."""
        task_type = task['type']
        data = task['data']

        if task_type == 'ai_analysis':
            await self._process_ai_analysis(data)
        elif task_type == 'state_sync':
            await self._process_state_sync(data)
        elif task_type == 'notification':
            await self._process_notification(data)

    async def _process_ai_analysis(self, data: Dict[str, Any]):
        """Process AI analysis task asynchronously."""
        try:
            from .ai_optimization import get_ai_optimizer
            
            optimizer = get_ai_optimizer()
            workflow_name = data['workflow_name']
            
            # Generate insights asynchronously
            insights = await optimizer.generate_workflow_insights(workflow_name)
            
            # Store insights
            for insight in insights:
                optimizer.store_insight(insight)

        except Exception as e:
            log.error(f"Async AI analysis error: {e}")

    async def _process_state_sync(self, data: Dict[str, Any]):
        """Process state synchronization task."""
        try:
            from .persistence import get_persistence_manager
            
            manager = get_persistence_manager()
            workflow_state_id = data['workflow_state_id']
            
            # Create async snapshot
            from ..models import db
            workflow_state = db.session.query(WorkflowState).filter(
                WorkflowState.id == workflow_state_id
            ).first()
            
            if workflow_state:
                manager.create_snapshot(workflow_state, 'async_checkpoint')

        except Exception as e:
            log.error(f"Async state sync error: {e}")

    async def _process_notification(self, data: Dict[str, Any]):
        """Process notification task."""
        try:
            # Send notifications (email, webhook, etc.)
            notification_type = data.get('type')
            recipients = data.get('recipients', [])
            message = data.get('message')
            
            # Implementation would depend on notification system
            log.info(f"Notification sent: {notification_type} to {len(recipients)} recipients")

        except Exception as e:
            log.error(f"Async notification error: {e}")

    def stop(self):
        """Stop async processing."""
        self.running = False


# Global instances
_workflow_cache = None
_query_optimizer = None
_batch_processor = None
_async_processor = None


def get_workflow_cache() -> WorkflowCache:
    """Get global workflow cache instance."""
    global _workflow_cache
    if _workflow_cache is None:
        _workflow_cache = WorkflowCache()
    return _workflow_cache


def get_query_optimizer() -> QueryOptimizer:
    """Get global query optimizer instance."""
    global _query_optimizer
    if _query_optimizer is None:
        _query_optimizer = QueryOptimizer()
    return _query_optimizer


def get_batch_processor() -> WorkflowBatchProcessor:
    """Get global batch processor instance."""
    global _batch_processor
    if _batch_processor is None:
        batch_size = current_app.config.get('WORKFLOW_BATCH_SIZE', 100)
        _batch_processor = WorkflowBatchProcessor(batch_size)
    return _batch_processor


def get_async_processor() -> AsyncWorkflowProcessor:
    """Get global async processor instance."""
    global _async_processor
    if _async_processor is None:
        _async_processor = AsyncWorkflowProcessor()
    return _async_processor


# Decorators for performance optimization
def cached(cache_type: str = 'workflow_states', ttl: Optional[int] = None, key_func: Optional[Callable] = None):
    """Decorator for caching function results."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_workflow_cache()
            
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{hash(str(args) + str(kwargs))}"

            # Try to get from cache
            result = cache.get(cache_key, cache_type)
            if result is not None:
                return result

            # Execute function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, cache_type, ttl)
            return result

        return wrapper
    return decorator


def batched(operation_type: str):
    """Decorator for batch processing operations."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            processor = get_batch_processor()
            
            # Extract data for batching
            data = kwargs.copy()
            data.update({f'arg_{i}': arg for i, arg in enumerate(args)})
            
            # Add to batch queue
            processor.add_operation(operation_type, data)
            
            # For immediate operations, still execute function
            return func(*args, **kwargs)

        return wrapper
    return decorator


def async_task(task_type: str):
    """Decorator for async task processing."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Execute function synchronously first
            result = func(*args, **kwargs)
            
            # Schedule async processing
            processor = get_async_processor()
            if processor.loop:
                data = kwargs.copy()
                data.update({f'arg_{i}': arg for i, arg in enumerate(args)})
                asyncio.run_coroutine_threadsafe(
                    processor.add_task(task_type, data),
                    processor.loop
                )
            
            return result

        return wrapper
    return decorator


def performance_monitor(func):
    """Decorator for monitoring function performance."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            # Log performance metrics
            cache = get_workflow_cache()
            cache.metrics.workflow_execution_times[func.__name__] = execution_time
            
            # Log slow operations
            if execution_time > 2.0:  # Operations longer than 2 seconds
                log.warning(f"Slow operation detected: {func.__name__} took {execution_time:.2f}s")
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            log.error(f"Operation failed: {func.__name__} after {execution_time:.2f}s - {e}")
            raise

    return wrapper


# Performance initialization
def initialize_performance_system():
    """Initialize performance optimization system."""
    
    # Setup query optimizations
    optimizer = get_query_optimizer()
    optimizer.optimize_workflow_queries()
    
    # Start async processor
    processor = get_async_processor()
    if not processor.running:
        # Start in background thread
        import threading
        def start_async_loop():
            asyncio.run(processor.start())
        
        thread = threading.Thread(target=start_async_loop, daemon=True)
        thread.start()
    
    log.info("Workflow performance optimization system initialized")


# Cleanup function
def cleanup_performance_system():
    """Cleanup performance optimization system."""
    
    # Shutdown batch processor
    processor = get_batch_processor()
    processor.shutdown()
    
    # Stop async processor
    async_proc = get_async_processor()
    async_proc.stop()
    
    log.info("Workflow performance optimization system cleaned up")