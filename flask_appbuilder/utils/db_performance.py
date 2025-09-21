"""
Database performance optimization utilities for Flask-AppBuilder.

This module provides utilities to prevent performance issues from unbounded
database operations, implementing proper pagination, limits, and query optimization.
"""

import logging
from typing import List, Dict, Any, Optional, Union, Type, Tuple
from functools import wraps
from dataclasses import dataclass
from sqlalchemy.orm import Query
from sqlalchemy.orm.session import Session
from sqlalchemy import func, text
from flask import current_app, request

logger = logging.getLogger(__name__)


@dataclass
class QueryLimits:
    """Configuration for query limits and pagination."""

    # Default limits for different operation types
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 1000
    DEFAULT_MAX_RESULTS: int = 10000
    BULK_OPERATION_LIMIT: int = 5000

    # Memory usage limits
    MAX_MEMORY_MB: int = 100
    ESTIMATED_ROW_SIZE_BYTES: int = 1024

    # Performance monitoring
    SLOW_QUERY_THRESHOLD_MS: int = 1000
    LOG_PERFORMANCE_WARNINGS: bool = True


class DatabasePerformanceError(Exception):
    """Exception raised for database performance violations."""
    pass


class QueryOptimizer:
    """Utility class for optimizing database queries and preventing performance issues."""

    def __init__(self, limits: Optional[QueryLimits] = None):
        """
        Initialize query optimizer.

        Args:
            limits: Query limits configuration
        """
        self.limits = limits or QueryLimits()
        self._query_stats = {}

    def safe_all(self, query: Query, max_results: Optional[int] = None) -> List[Any]:
        """
        Safely execute .all() with result count protection.

        Args:
            query: SQLAlchemy query object
            max_results: Maximum number of results to return

        Returns:
            List of query results

        Raises:
            DatabasePerformanceError: If result count exceeds limits
        """
        max_results = max_results or self.limits.DEFAULT_MAX_RESULTS

        # First, count total results
        count_query = query.statement.with_only_columns([func.count()]).order_by(None)
        total_count = query.session.execute(count_query).scalar()

        if total_count > max_results:
            logger.warning(
                f"Query would return {total_count} results, exceeding limit of {max_results}. "
                f"Consider using pagination."
            )

            if self.limits.LOG_PERFORMANCE_WARNINGS:
                raise DatabasePerformanceError(
                    f"Query result count ({total_count}) exceeds maximum allowed ({max_results}). "
                    f"Use pagination with limit() and offset() instead of .all()"
                )

        # Execute the query with monitoring
        import time
        start_time = time.time()

        results = query.limit(max_results).all()

        execution_time_ms = (time.time() - start_time) * 1000

        # Log performance warnings
        if execution_time_ms > self.limits.SLOW_QUERY_THRESHOLD_MS:
            logger.warning(
                f"Slow query detected: {execution_time_ms:.2f}ms for {len(results)} results"
            )

        return results

    def paginated_query(self, query: Query, page: int = 1, per_page: Optional[int] = None) -> Tuple[List[Any], int, bool]:
        """
        Execute paginated query with performance optimization.

        Args:
            query: SQLAlchemy query object
            page: Page number (1-based)
            per_page: Results per page

        Returns:
            Tuple of (results, total_count, has_next_page)
        """
        per_page = min(per_page or self.limits.DEFAULT_PAGE_SIZE, self.limits.MAX_PAGE_SIZE)

        # Calculate offset
        offset = (page - 1) * per_page

        # Get total count efficiently
        count_query = query.statement.with_only_columns([func.count()]).order_by(None)
        total_count = query.session.execute(count_query).scalar()

        # Get paginated results
        results = query.offset(offset).limit(per_page).all()

        # Check if there's a next page
        has_next = (offset + per_page) < total_count

        return results, total_count, has_next

    def chunked_query(self, query: Query, chunk_size: Optional[int] = None):
        """
        Generator for processing large datasets in chunks.

        Args:
            query: SQLAlchemy query object
            chunk_size: Size of each chunk

        Yields:
            Chunks of query results
        """
        chunk_size = chunk_size or self.limits.DEFAULT_PAGE_SIZE
        offset = 0

        while True:
            chunk = query.offset(offset).limit(chunk_size).all()

            if not chunk:
                break

            yield chunk

            if len(chunk) < chunk_size:
                break

            offset += chunk_size

    def memory_safe_count(self, query: Query) -> int:
        """
        Get count without loading all records into memory.

        Args:
            query: SQLAlchemy query object

        Returns:
            Count of results
        """
        count_query = query.statement.with_only_columns([func.count()]).order_by(None)
        return query.session.execute(count_query).scalar()

    def estimate_memory_usage(self, result_count: int, estimated_row_size: Optional[int] = None) -> int:
        """
        Estimate memory usage for query results.

        Args:
            result_count: Number of expected results
            estimated_row_size: Estimated size per row in bytes

        Returns:
            Estimated memory usage in bytes
        """
        row_size = estimated_row_size or self.limits.ESTIMATED_ROW_SIZE_BYTES
        return result_count * row_size

    def validate_query_performance(self, query: Query, operation_name: str = "query") -> None:
        """
        Validate query performance before execution.

        Args:
            query: SQLAlchemy query object
            operation_name: Name of the operation for logging

        Raises:
            DatabasePerformanceError: If query violates performance constraints
        """
        # Estimate result count
        try:
            estimated_count = self.memory_safe_count(query)
        except Exception as e:
            logger.warning(f"Could not estimate query size for {operation_name}: {e}")
            return

        # Check memory usage
        estimated_memory = self.estimate_memory_usage(estimated_count)
        max_memory_bytes = self.limits.MAX_MEMORY_MB * 1024 * 1024

        if estimated_memory > max_memory_bytes:
            raise DatabasePerformanceError(
                f"Query '{operation_name}' would use approximately "
                f"{estimated_memory / (1024 * 1024):.1f}MB memory "
                f"(limit: {self.limits.MAX_MEMORY_MB}MB). Use pagination instead."
            )

        # Check result count
        if estimated_count > self.limits.DEFAULT_MAX_RESULTS:
            raise DatabasePerformanceError(
                f"Query '{operation_name}' would return {estimated_count} results "
                f"(limit: {self.limits.DEFAULT_MAX_RESULTS}). Use pagination instead."
            )


def performance_aware_query(max_results: int = None, chunk_size: int = None):
    """
    Decorator to make queries performance-aware.

    Args:
        max_results: Maximum results allowed
        chunk_size: Chunk size for processing
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Initialize optimizer
            optimizer = QueryOptimizer()

            # Execute function
            result = func(*args, **kwargs)

            # If result is a query, apply optimization
            if isinstance(result, Query):
                if max_results:
                    return optimizer.safe_all(result, max_results)
                else:
                    optimizer.validate_query_performance(result, func.__name__)

            return result
        return wrapper
    return decorator


class PaginationHelper:
    """Helper class for implementing pagination in views."""

    @staticmethod
    def get_pagination_params(request_args: Dict[str, Any] = None) -> Tuple[int, int]:
        """
        Extract pagination parameters from request.

        Args:
            request_args: Request arguments (defaults to Flask request.args)

        Returns:
            Tuple of (page, per_page)
        """
        if request_args is None:
            request_args = request.args if request else {}

        try:
            page = max(1, int(request_args.get('page', 1)))
        except (ValueError, TypeError):
            page = 1

        try:
            per_page = min(
                max(1, int(request_args.get('per_page', QueryLimits.DEFAULT_PAGE_SIZE))),
                QueryLimits.MAX_PAGE_SIZE
            )
        except (ValueError, TypeError):
            per_page = QueryLimits.DEFAULT_PAGE_SIZE

        return page, per_page

    @staticmethod
    def create_pagination_context(
        results: List[Any],
        total_count: int,
        page: int,
        per_page: int,
        endpoint: str = None
    ) -> Dict[str, Any]:
        """
        Create pagination context for templates.

        Args:
            results: Current page results
            total_count: Total number of results
            page: Current page number
            per_page: Results per page
            endpoint: Flask endpoint for pagination links

        Returns:
            Pagination context dictionary
        """
        total_pages = (total_count + per_page - 1) // per_page
        has_prev = page > 1
        has_next = page < total_pages

        return {
            'items': results,
            'page': page,
            'per_page': per_page,
            'total': total_count,
            'total_pages': total_pages,
            'has_prev': has_prev,
            'has_next': has_next,
            'prev_page': page - 1 if has_prev else None,
            'next_page': page + 1 if has_next else None,
            'endpoint': endpoint,
            'pages': list(range(
                max(1, page - 2),
                min(total_pages + 1, page + 3)
            ))
        }


class QueryPerformanceMonitor:
    """Monitor and log query performance statistics."""

    def __init__(self):
        """Initialize performance monitor."""
        self.query_stats = {}
        self.slow_queries = []

    def record_query(self, query_name: str, execution_time_ms: float, result_count: int):
        """
        Record query performance statistics.

        Args:
            query_name: Name/identifier for the query
            execution_time_ms: Execution time in milliseconds
            result_count: Number of results returned
        """
        if query_name not in self.query_stats:
            self.query_stats[query_name] = {
                'count': 0,
                'total_time': 0,
                'max_time': 0,
                'min_time': float('inf'),
                'total_results': 0
            }

        stats = self.query_stats[query_name]
        stats['count'] += 1
        stats['total_time'] += execution_time_ms
        stats['max_time'] = max(stats['max_time'], execution_time_ms)
        stats['min_time'] = min(stats['min_time'], execution_time_ms)
        stats['total_results'] += result_count

        # Record slow queries
        if execution_time_ms > QueryLimits.SLOW_QUERY_THRESHOLD_MS:
            self.slow_queries.append({
                'query_name': query_name,
                'execution_time_ms': execution_time_ms,
                'result_count': result_count,
                'timestamp': time.time()
            })

    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get performance summary statistics.

        Returns:
            Performance summary dictionary
        """
        summary = {
            'total_queries': sum(stats['count'] for stats in self.query_stats.values()),
            'slow_queries_count': len(self.slow_queries),
            'queries': {}
        }

        for query_name, stats in self.query_stats.items():
            summary['queries'][query_name] = {
                'count': stats['count'],
                'avg_time_ms': stats['total_time'] / stats['count'],
                'max_time_ms': stats['max_time'],
                'min_time_ms': stats['min_time'],
                'avg_results': stats['total_results'] / stats['count']
            }

        return summary


# Global performance monitor instance
performance_monitor = QueryPerformanceMonitor()


def monitor_query_performance(query_name: str):
    """
    Decorator to monitor query performance.

    Args:
        query_name: Name identifier for the query
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import time

            start_time = time.time()
            result = func(*args, **kwargs)
            execution_time_ms = (time.time() - start_time) * 1000

            # Count results
            result_count = 0
            if isinstance(result, list):
                result_count = len(result)
            elif hasattr(result, 'count'):
                try:
                    result_count = result.count()
                except:
                    result_count = 0

            # Record performance
            performance_monitor.record_query(query_name, execution_time_ms, result_count)

            return result
        return wrapper
    return decorator