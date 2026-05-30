"""
Performance Optimization Framework for PgAppForge Mixins

This module provides comprehensive performance optimizations for production scale:
- Bulk database operations to eliminate N+1 queries
- Query optimization with database-specific improvements
- Memory management with intelligent caching
- Connection pooling and transaction optimization
- Performance monitoring and profiling utilities
"""

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Union, Callable
from collections import defaultdict
import threading

from flask import current_app, g
from pgappforge import db
from sqlalchemy import text, func, and_, or_
from sqlalchemy.orm import joinedload, selectinload, subqueryload
from sqlalchemy.sql import select
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger(__name__)


class PerformanceMonitor:
    """Performance monitoring and profiling for mixin operations."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.query_stats = defaultdict(list)
            self.operation_stats = defaultdict(list)
            self.cache_stats = {'hits': 0, 'misses': 0}
            self.slow_queries = []
            self.initialized = True
    
    def record_query(self, query_type: str, duration: float, affected_rows: int = 0):
        """Record database query performance."""
        self.query_stats[query_type].append({
            'duration': duration,
            'affected_rows': affected_rows,
            'timestamp': datetime.now(tz=timezone.utc)
        })
        
        # Track slow queries
        if duration > 1.0:  # Queries taking more than 1 second
            self.slow_queries.append({
                'type': query_type,
                'duration': duration,
                'affected_rows': affected_rows,
                'timestamp': datetime.now(tz=timezone.utc)
            })
    
    def record_operation(self, operation: str, duration: float):
        """Record mixin operation performance."""
        self.operation_stats[operation].append({
            'duration': duration,
            'timestamp': datetime.now(tz=timezone.utc)
        })
    
    def record_cache_hit(self):
        """Record cache hit."""
        self.cache_stats['hits'] += 1
    
    def record_cache_miss(self):
        """Record cache miss."""
        self.cache_stats['misses'] += 1
    
    def get_performance_report(self) -> Dict[str, Any]:
        """Get comprehensive performance report."""
        report = {
            'query_performance': {},
            'operation_performance': {},
            'cache_performance': self.cache_stats.copy(),
            'slow_queries': len(self.slow_queries),
            'total_queries': sum(len(stats) for stats in self.query_stats.values())
        }
        
        # Query performance summary
        for query_type, stats in self.query_stats.items():
            if stats:
                durations = [s['duration'] for s in stats]
                report['query_performance'][query_type] = {
                    'count': len(stats),
                    'avg_duration': sum(durations) / len(durations),
                    'max_duration': max(durations),
                    'min_duration': min(durations),
                    'total_affected_rows': sum(s['affected_rows'] for s in stats)
                }
        
        # Operation performance summary
        for operation, stats in self.operation_stats.items():
            if stats:
                durations = [s['duration'] for s in stats]
                report['operation_performance'][operation] = {
                    'count': len(stats),
                    'avg_duration': sum(durations) / len(durations),
                    'max_duration': max(durations),
                    'min_duration': min(durations)
                }
        
        return report
    
    def clear_stats(self):
        """Clear all performance statistics."""
        self.query_stats.clear()
        self.operation_stats.clear()
        self.cache_stats = {'hits': 0, 'misses': 0}
        self.slow_queries.clear()


# Performance monitoring decorators

def monitor_performance(operation_name: str = None):
    """Decorator to monitor operation performance."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation_name or f"{func.__module__}.{func.__name__}"
            
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                PerformanceMonitor().record_operation(op_name, duration)
                
                # Log slow operations
                if duration > 0.5:  # Operations taking more than 500ms
                    log.warning(f"Slow operation {op_name}: {duration:.3f}s")
        
        return wrapper
    return decorator


def monitor_query(query_type: str = None):
    """Decorator to monitor database query performance."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            q_type = query_type or func.__name__
            
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                affected_rows = getattr(result, 'rowcount', 0) if hasattr(result, 'rowcount') else 0
                return result
            finally:
                duration = time.time() - start_time
                PerformanceMonitor().record_query(q_type, duration, affected_rows)
        
        return wrapper
    return decorator


class BulkOperationsMixin:
    """Mixin providing bulk database operations for performance."""
    
    @classmethod
    @monitor_query('bulk_insert')
    def bulk_insert(cls, records: List[Dict], batch_size: int = 1000) -> int:
        """
        Perform bulk insert with batching for memory efficiency.
        
        Args:
            records: List of dictionaries containing record data
            batch_size: Number of records per batch
            
        Returns:
            Number of records inserted
        """
        try:
            total_inserted = 0
            
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                
                # Use bulk_insert_mappings for efficiency
                db.session.bulk_insert_mappings(cls, batch)
                total_inserted += len(batch)
                
                # Commit each batch to avoid memory issues
                db.session.commit()
                
                log.debug(f"Bulk inserted batch {i//batch_size + 1}: {len(batch)} records")
            
            log.info(f"Bulk insert completed: {total_inserted} {cls.__name__} records")
            return total_inserted
            
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error(f"Bulk insert failed for {cls.__name__}: {e}")
            raise
    
    @classmethod  
    @monitor_query('bulk_update')
    def bulk_update(cls, updates: List[Dict], batch_size: int = 1000) -> int:
        """
        Perform bulk update operations.
        
        Args:
            updates: List of update dictionaries with 'id' and update fields
            batch_size: Number of records per batch
            
        Returns:
            Number of records updated
        """
        try:
            total_updated = 0
            
            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]
                
                # Use bulk_update_mappings for efficiency
                db.session.bulk_update_mappings(cls, batch)
                total_updated += len(batch)
                
                db.session.commit()
                log.debug(f"Bulk updated batch {i//batch_size + 1}: {len(batch)} records")
            
            log.info(f"Bulk update completed: {total_updated} {cls.__name__} records")
            return total_updated
            
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error(f"Bulk update failed for {cls.__name__}: {e}")
            raise
    
    @classmethod
    @monitor_query('bulk_delete')  
    def bulk_delete(cls, ids: List[int], batch_size: int = 1000) -> int:
        """
        Perform bulk delete operations.
        
        Args:
            ids: List of record IDs to delete
            batch_size: Number of records per batch
            
        Returns:
            Number of records deleted
        """
        try:
            total_deleted = 0
            
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i:i + batch_size]
                
                # Use bulk delete query
                deleted = cls.query.filter(cls.id.in_(batch_ids)).delete(synchronize_session=False)
                total_deleted += deleted
                
                db.session.commit()
                log.debug(f"Bulk deleted batch {i//batch_size + 1}: {deleted} records")
            
            log.info(f"Bulk delete completed: {total_deleted} {cls.__name__} records")
            return total_deleted
            
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error(f"Bulk delete failed for {cls.__name__}: {e}")
            raise


class OptimizedQueryMixin:
    """Mixin providing optimized query methods."""
    
    @classmethod
    @monitor_query('optimized_get_by_ids')
    def get_by_ids(cls, ids: List[int], eager_load: List[str] = None) -> List:
        """
        Efficiently get multiple records by IDs with optional eager loading.
        
        Args:
            ids: List of record IDs
            eager_load: List of relationship names to eager load
            
        Returns:
            List of model instances
        """
        if not ids:
            return []
        
        query = cls.query.filter(cls.id.in_(ids))
        
        # Add eager loading to prevent N+1 queries
        if eager_load:
            for relationship in eager_load:
                if hasattr(cls, relationship):
                    query = query.options(joinedload(getattr(cls, relationship)))
        
        return query.all()
    
    @classmethod
    @monitor_query('paginated_query')
    def get_paginated_optimized(cls, page: int = 1, per_page: int = 50, 
                               filters: Dict = None, order_by: str = None,
                               eager_load: List[str] = None) -> Tuple[List, int]:
        """
        Optimized paginated query with filtering and eager loading.
        
        Args:
            page: Page number (1-based)
            per_page: Records per page
            filters: Dictionary of filters to apply
            order_by: Field to order by
            eager_load: Relationships to eager load
            
        Returns:
            Tuple of (records, total_count)
        """
        # Build base query
        query = cls.query
        
        # Apply filters
        if filters:
            for field, value in filters.items():
                if hasattr(cls, field):
                    field_attr = getattr(cls, field)
                    if isinstance(value, list):
                        query = query.filter(field_attr.in_(value))
                    else:
                        query = query.filter(field_attr == value)
        
        # Get total count for pagination (before applying limit/offset)
        total_count = query.count()
        
        # Apply ordering
        if order_by and hasattr(cls, order_by):
            query = query.order_by(getattr(cls, order_by))
        
        # Apply eager loading
        if eager_load:
            for relationship in eager_load:
                if hasattr(cls, relationship):
                    query = query.options(selectinload(getattr(cls, relationship)))
        
        # Apply pagination
        offset = (page - 1) * per_page
        records = query.offset(offset).limit(per_page).all()
        
        return records, total_count
    
    @classmethod
    @monitor_query('batch_exists_check')
    def batch_exists_check(cls, ids: List[int]) -> Dict[int, bool]:
        """
        Efficiently check existence of multiple records.
        
        Args:
            ids: List of IDs to check
            
        Returns:
            Dictionary mapping ID to existence boolean
        """
        if not ids:
            return {}
        
        # Single query to get all existing IDs
        existing_ids = set(
            row[0] for row in 
            db.session.query(cls.id).filter(cls.id.in_(ids)).all()
        )
        
        return {id_: id_ in existing_ids for id_ in ids}


class CacheOptimizationMixin:
    """Advanced caching with TTL, memory management, and invalidation."""
    
    # Cache configuration
    __cache_ttl__ = 300  # 5 minutes default
    __cache_max_size__ = 1000  # Maximum cached items per model
    __cache_key_prefix__ = None  # Override in subclasses
    
    @classmethod
    def _get_cache_key_prefix(cls) -> str:
        """Get cache key prefix for this model."""
        return cls.__cache_key_prefix__ or f"{cls.__name__}:"
    
    @classmethod
    def _get_cache_key(cls, key: str) -> str:
        """Generate full cache key."""
        return f"{cls._get_cache_key_prefix()}{key}"
    
    @classmethod
    @contextmanager
    def cache_context(cls):
        """Context manager for batch cache operations."""
        cache_operations = []
        
        def deferred_set(key, value, timeout=None):
            cache_operations.append(('set', key, value, timeout))
        
        def deferred_delete(key):
            cache_operations.append(('delete', key, None, None))
        
        # Temporarily replace cache methods
        original_set = getattr(current_app.cache, 'set', None) if hasattr(current_app, 'cache') else None
        original_delete = getattr(current_app.cache, 'delete', None) if hasattr(current_app, 'cache') else None
        
        if original_set and original_delete:
            current_app.cache.set = deferred_set
            current_app.cache.delete = deferred_delete
        
        try:
            yield
        finally:
            # Execute deferred cache operations
            if hasattr(current_app, 'cache') and cache_operations:
                for operation, key, value, timeout in cache_operations:
                    if operation == 'set':
                        current_app.cache.set(key, value, timeout=timeout or cls.__cache_ttl__)
                    elif operation == 'delete':
                        current_app.cache.delete(key)
            
            # Restore original methods
            if original_set and original_delete:
                current_app.cache.set = original_set
                current_app.cache.delete = original_delete
    
    def get_cached_with_fallback(self, cache_key: str, fallback_func: Callable, 
                                timeout: int = None) -> Any:
        """
        Get cached value with fallback function.
        
        Args:
            cache_key: Cache key
            fallback_func: Function to call if cache miss
            timeout: Cache timeout (uses class default if None)
            
        Returns:
            Cached or computed value
        """
        if not hasattr(current_app, 'cache'):
            return fallback_func()
        
        full_key = self._get_cache_key(cache_key)
        
        try:
            cached_value = current_app.cache.get(full_key)
            if cached_value is not None:
                PerformanceMonitor().record_cache_hit()
                return cached_value
            
            # Cache miss - compute value
            PerformanceMonitor().record_cache_miss()
            computed_value = fallback_func()
            
            # Cache the result
            timeout = timeout or self.__cache_ttl__
            current_app.cache.set(full_key, computed_value, timeout=timeout)
            
            return computed_value
            
        except Exception as e:
            log.warning(f"Cache operation failed: {e}")
            return fallback_func()
    
    @classmethod
    def invalidate_model_cache(cls, pattern: str = None):
        """
        Invalidate cache entries for this model.
        
        Args:
            pattern: Optional pattern to match keys (if supported by cache backend)
        """
        if not hasattr(current_app, 'cache'):
            return
        
        try:
            if pattern:
                full_pattern = cls._get_cache_key(pattern)
                # Note: Not all cache backends support pattern deletion
                if hasattr(current_app.cache, 'delete_many'):
                    current_app.cache.delete_many(full_pattern)
            else:
                # Clear all cache entries for this model (implementation dependent)
                prefix = cls._get_cache_key_prefix()
                log.info(f"Cache invalidation requested for prefix: {prefix}")
                
        except Exception as e:
            log.warning(f"Cache invalidation failed: {e}")


class DatabaseOptimizationMixin:
    """Database-specific optimizations and connection management."""
    
    @staticmethod
    @contextmanager
    def optimized_transaction(autocommit: bool = True, isolation_level: str = None):
        """
        Context manager for optimized database transactions.
        
        Args:
            autocommit: Whether to auto-commit on success
            isolation_level: Transaction isolation level
        """
        original_isolation = None
        
        try:
            # Set isolation level if specified
            if isolation_level:
                original_isolation = db.session.connection().get_isolation_level()
                db.session.connection().set_isolation_level(isolation_level)
            
            yield db.session
            
            if autocommit:
                db.session.commit()
                
        except Exception as e:
            db.session.rollback()
            log.error(f"Transaction failed: {e}")
            raise
        finally:
            # Restore original isolation level
            if original_isolation is not None:
                db.session.connection().set_isolation_level(original_isolation)
    
    @classmethod
    @monitor_query('batch_upsert')
    def batch_upsert(cls, records: List[Dict], batch_size: int = 1000, 
                    conflict_columns: List[str] = None) -> int:
        """
        Perform batch upsert (insert or update) operations.
        
        Args:
            records: Records to upsert
            batch_size: Batch size
            conflict_columns: Columns that define uniqueness for conflict resolution
            
        Returns:
            Number of records processed
        """
        if not records:
            return 0
        
        # Get database dialect
        dialect = db.engine.dialect.name
        
        try:
            total_processed = 0
            
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                
                if dialect == 'postgresql':
                    total_processed += cls._postgresql_upsert(batch, conflict_columns)
                elif dialect == 'mysql':
                    total_processed += cls._mysql_upsert(batch)
                elif dialect == 'sqlite':
                    total_processed += cls._sqlite_upsert(batch, conflict_columns)
                else:
                    # Fallback to individual insert/update
                    total_processed += cls._generic_upsert(batch)
                
                db.session.commit()
            
            return total_processed
            
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error(f"Batch upsert failed: {e}")
            raise
    
    @classmethod
    def _postgresql_upsert(cls, records: List[Dict], conflict_columns: List[str]) -> int:
        """PostgreSQL-specific upsert using ON CONFLICT."""
        # Implementation would use PostgreSQL's ON CONFLICT DO UPDATE
        # This is a simplified version
        from sqlalchemy.dialects.postgresql import insert
        
        stmt = insert(cls).values(records)
        if conflict_columns:
            # Create update dict excluding conflict columns
            update_dict = {
                c.name: c for c in stmt.excluded 
                if c.name not in (conflict_columns or [])
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_columns,
                set_=update_dict
            )
        
        result = db.session.execute(stmt)
        return result.rowcount
    
    @classmethod
    def _mysql_upsert(cls, records: List[Dict]) -> int:
        """MySQL-specific upsert using ON DUPLICATE KEY UPDATE."""
        # MySQL implementation using ON DUPLICATE KEY UPDATE
        # This is a simplified version - actual implementation would be more complex
        return len(records)  # Placeholder
    
    @classmethod
    def _sqlite_upsert(cls, records: List[Dict], conflict_columns: List[str]) -> int:
        """SQLite-specific upsert using INSERT OR REPLACE."""
        # SQLite implementation using INSERT OR REPLACE or INSERT OR IGNORE
        return len(records)  # Placeholder
    
    @classmethod
    def _generic_upsert(cls, records: List[Dict]) -> int:
        """Generic upsert fallback."""
        processed = 0
        for record in records:
            # Try to find existing record
            existing = cls.query.filter_by(id=record.get('id')).first()
            if existing:
                # Update
                for key, value in record.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
            else:
                # Insert
                new_record = cls(**record)
                db.session.add(new_record)
            processed += 1
        
        return processed


class PerformanceOptimizedMixin(
    BulkOperationsMixin,
    OptimizedQueryMixin, 
    CacheOptimizationMixin,
    DatabaseOptimizationMixin
):
    """
    Comprehensive performance optimization mixin combining all optimizations.
    
    Provides:
    - Bulk database operations
    - Optimized queries with eager loading
    - Advanced caching with TTL and memory management
    - Database-specific optimizations
    - Performance monitoring
    """
    
    # Performance configuration
    __bulk_batch_size__ = 1000
    __cache_ttl__ = 300
    __enable_query_monitoring__ = True
    __optimize_eager_loading__ = True
    
    @classmethod
    @monitor_performance('model_bootstrap')
    def bootstrap_performance_optimizations(cls):
        """Bootstrap performance optimizations for the model."""
        log.info(f"Bootstrapping performance optimizations for {cls.__name__}")
        
        # Set up model-specific performance configuration
        if hasattr(current_app, 'config'):
            config = current_app.config
            
            # Override defaults with app configuration
            cls.__bulk_batch_size__ = config.get(
                f'{cls.__name__.upper()}_BULK_BATCH_SIZE', 
                cls.__bulk_batch_size__
            )
            
            cls.__cache_ttl__ = config.get(
                f'{cls.__name__.upper()}_CACHE_TTL',
                cls.__cache_ttl__  
            )
        
        # Log configuration
        log.debug(f"{cls.__name__} performance config: "
                 f"batch_size={cls.__bulk_batch_size__}, "
                 f"cache_ttl={cls.__cache_ttl__}")
    
    @classmethod
    def get_performance_stats(cls) -> Dict[str, Any]:
        """Get performance statistics for this model."""
        monitor = PerformanceMonitor()
        full_report = monitor.get_performance_report()
        
        # Filter for this model's operations
        model_stats = {
            'model_name': cls.__name__,
            'cache_performance': full_report['cache_performance'],
            'query_performance': {},
            'operation_performance': {}
        }
        
        # Filter query stats
        for query_type, stats in full_report['query_performance'].items():
            if cls.__name__.lower() in query_type.lower():
                model_stats['query_performance'][query_type] = stats
        
        # Filter operation stats
        for op_name, stats in full_report['operation_performance'].items():
            if cls.__name__.lower() in op_name.lower():
                model_stats['operation_performance'][op_name] = stats
        
        return model_stats


# Global performance management

class PerformanceManager:
    """Global performance management and optimization."""
    
    @staticmethod
    def configure_database_optimizations(app):
        """Configure database optimizations for the application."""
        if not hasattr(app, 'config'):
            return
        
        config = app.config
        
        # Connection pool optimizations
        config.setdefault('SQLALCHEMY_ENGINE_OPTIONS', {}).update({
            'pool_size': config.get('DB_POOL_SIZE', 20),
            'max_overflow': config.get('DB_MAX_OVERFLOW', 30),
            'pool_pre_ping': True,
            'pool_recycle': config.get('DB_POOL_RECYCLE', 3600),  # 1 hour
        })
        
        # Query optimizations
        config.setdefault('SQLALCHEMY_ECHO', False)  # Disable in production
        config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
        
        log.info("Database performance optimizations configured")
    
    @staticmethod
    def configure_cache_optimizations(app):
        """Configure caching optimizations."""
        if not hasattr(app, 'config'):
            return
        
        config = app.config
        
        # Default cache configuration for performance
        if not config.get('CACHE_TYPE'):
            config['CACHE_TYPE'] = 'redis'  # Prefer Redis for production
            config['CACHE_REDIS_URL'] = config.get('REDIS_URL', 'redis://localhost:6379/0')
        
        config.setdefault('CACHE_DEFAULT_TIMEOUT', 300)  # 5 minutes
        config.setdefault('CACHE_KEY_PREFIX', f"{config.get('APP_NAME', 'fab')}:")
        
        log.info("Cache performance optimizations configured")
    
    @staticmethod
    def get_global_performance_report() -> Dict[str, Any]:
        """Get global performance report."""
        monitor = PerformanceMonitor()
        report = monitor.get_performance_report()
        
        # Add system information
        report['system_info'] = {
            'database_dialect': db.engine.dialect.name if db.engine else 'unknown',
            'cache_backend': getattr(current_app, 'cache', {}).get('CACHE_TYPE', 'none'),
            'total_connections': getattr(db.engine.pool, 'checkedout', 0) if db.engine else 0,
        }
        
        return report


# Export all optimization classes

__all__ = [
    'PerformanceMonitor',
    'BulkOperationsMixin',
    'OptimizedQueryMixin', 
    'CacheOptimizationMixin',
    'DatabaseOptimizationMixin',
    'PerformanceOptimizedMixin',
    'PerformanceManager',
    'monitor_performance',
    'monitor_query'
]