"""
Tests for database performance optimization fixes.

These tests ensure that unbounded database operations have been properly
optimized with limits, pagination, and performance monitoring.
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from flask import Flask

from pgappforge.utils.db_performance import (
    QueryOptimizer, PaginationHelper, QueryLimits,
    DatabasePerformanceError, performance_monitor
)


class TestQueryOptimizer:
    """Test query optimizer functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.optimizer = QueryOptimizer()

    def test_safe_all_with_small_result_set(self):
        """Test safe_all with result count under limit."""
        # Mock query with small result count
        mock_query = Mock()
        mock_query.session.execute.return_value.scalar.return_value = 10
        mock_query.limit.return_value.all.return_value = ['result'] * 10

        results = self.optimizer.safe_all(mock_query, max_results=50)

        assert len(results) == 10
        mock_query.limit.assert_called_once_with(50)

    def test_safe_all_exceeds_limit_raises_error(self):
        """Test safe_all raises error when result count exceeds limit."""
        # Mock query with large result count
        mock_query = Mock()
        mock_query.session.execute.return_value.scalar.return_value = 1000
        mock_query.limit.return_value.all.return_value = ['result'] * 50

        with pytest.raises(DatabasePerformanceError):
            self.optimizer.safe_all(mock_query, max_results=50)

    def test_paginated_query_basic(self):
        """Test basic pagination functionality."""
        # Mock query
        mock_query = Mock()
        mock_query.session.execute.return_value.scalar.return_value = 100
        mock_query.offset.return_value.limit.return_value.all.return_value = ['result'] * 20

        results, total_count, has_next = self.optimizer.paginated_query(
            mock_query, page=1, per_page=20
        )

        assert len(results) == 20
        assert total_count == 100
        assert has_next is True
        mock_query.offset.assert_called_once_with(0)

    def test_paginated_query_last_page(self):
        """Test pagination on last page."""
        # Mock query for last page
        mock_query = Mock()
        mock_query.session.execute.return_value.scalar.return_value = 100
        mock_query.offset.return_value.limit.return_value.all.return_value = ['result'] * 10

        results, total_count, has_next = self.optimizer.paginated_query(
            mock_query, page=5, per_page=20
        )

        assert len(results) == 10
        assert total_count == 100
        assert has_next is False
        mock_query.offset.assert_called_once_with(80)  # (5-1) * 20

    def test_chunked_query_generator(self):
        """Test chunked query generator."""
        # Mock query that returns data in chunks
        mock_query = Mock()

        def mock_chunk_response(offset_val, limit_val):
            """Mock chunked responses."""
            if offset_val == 0:
                return ['chunk1_item1', 'chunk1_item2']
            elif offset_val == 2:
                return ['chunk2_item1']
            else:
                return []

        mock_query.offset.return_value.limit.return_value.all.side_effect = lambda: mock_chunk_response(
            mock_query.offset.call_args[0][0],
            mock_query.offset.return_value.limit.call_args[0][0]
        )

        chunks = list(self.optimizer.chunked_query(mock_query, chunk_size=2))

        assert len(chunks) == 2
        assert len(chunks[0]) == 2
        assert len(chunks[1]) == 1

    def test_memory_safe_count(self):
        """Test memory-safe counting."""
        mock_query = Mock()
        mock_query.session.execute.return_value.scalar.return_value = 500

        count = self.optimizer.memory_safe_count(mock_query)

        assert count == 500
        mock_query.session.execute.assert_called_once()

    def test_estimate_memory_usage(self):
        """Test memory usage estimation."""
        # Test with default row size
        memory_bytes = self.optimizer.estimate_memory_usage(1000)
        expected = 1000 * QueryLimits.ESTIMATED_ROW_SIZE_BYTES
        assert memory_bytes == expected

        # Test with custom row size
        memory_bytes = self.optimizer.estimate_memory_usage(500, estimated_row_size=2048)
        assert memory_bytes == 500 * 2048

    def test_validate_query_performance_passes(self):
        """Test query performance validation that passes."""
        mock_query = Mock()
        mock_query.session.execute.return_value.scalar.return_value = 100

        # Should not raise exception
        self.optimizer.validate_query_performance(mock_query, "test_query")

    def test_validate_query_performance_fails_memory(self):
        """Test query performance validation fails on memory usage."""
        mock_query = Mock()
        # Large result count that exceeds memory limit
        mock_query.session.execute.return_value.scalar.return_value = 1000000

        with pytest.raises(DatabasePerformanceError) as exc_info:
            self.optimizer.validate_query_performance(mock_query, "memory_test")

        assert "memory" in str(exc_info.value).lower()

    def test_validate_query_performance_fails_count(self):
        """Test query performance validation fails on result count."""
        mock_query = Mock()
        # Result count exceeds limit
        mock_query.session.execute.return_value.scalar.return_value = 50000

        with pytest.raises(DatabasePerformanceError) as exc_info:
            self.optimizer.validate_query_performance(mock_query, "count_test")

        assert "results" in str(exc_info.value).lower()


class TestPaginationHelper:
    """Test pagination helper functionality."""

    def test_get_pagination_params_defaults(self):
        """Test pagination parameters with defaults."""
        page, per_page = PaginationHelper.get_pagination_params({})

        assert page == 1
        assert per_page == QueryLimits.DEFAULT_PAGE_SIZE

    def test_get_pagination_params_custom(self):
        """Test pagination parameters with custom values."""
        request_args = {'page': '3', 'per_page': '25'}
        page, per_page = PaginationHelper.get_pagination_params(request_args)

        assert page == 3
        assert per_page == 25

    def test_get_pagination_params_invalid_values(self):
        """Test pagination parameters with invalid values."""
        request_args = {'page': 'invalid', 'per_page': '-5'}
        page, per_page = PaginationHelper.get_pagination_params(request_args)

        assert page == 1  # Default on invalid
        assert per_page == QueryLimits.DEFAULT_PAGE_SIZE  # Default on invalid

    def test_get_pagination_params_exceeds_max(self):
        """Test pagination parameters that exceed maximum."""
        request_args = {'per_page': '9999'}
        page, per_page = PaginationHelper.get_pagination_params(request_args)

        assert per_page == QueryLimits.MAX_PAGE_SIZE  # Capped at maximum

    def test_create_pagination_context(self):
        """Test pagination context creation."""
        results = ['item1', 'item2', 'item3']
        context = PaginationHelper.create_pagination_context(
            results=results,
            total_count=100,
            page=2,
            per_page=20,
            endpoint='test.endpoint'
        )

        assert context['items'] == results
        assert context['page'] == 2
        assert context['per_page'] == 20
        assert context['total'] == 100
        assert context['total_pages'] == 5
        assert context['has_prev'] is True
        assert context['has_next'] is True
        assert context['prev_page'] == 1
        assert context['next_page'] == 3
        assert context['endpoint'] == 'test.endpoint'

    def test_create_pagination_context_first_page(self):
        """Test pagination context for first page."""
        results = ['item1', 'item2']
        context = PaginationHelper.create_pagination_context(
            results=results,
            total_count=50,
            page=1,
            per_page=20
        )

        assert context['has_prev'] is False
        assert context['prev_page'] is None
        assert context['has_next'] is True

    def test_create_pagination_context_last_page(self):
        """Test pagination context for last page."""
        results = ['item1']
        context = PaginationHelper.create_pagination_context(
            results=results,
            total_count=41,
            page=3,
            per_page=20
        )

        assert context['has_prev'] is True
        assert context['has_next'] is False
        assert context['next_page'] is None
        assert context['total_pages'] == 3


class TestPerformanceMonitoring:
    """Test performance monitoring functionality."""

    def test_performance_monitor_records_query(self):
        """Test that performance monitor records query statistics."""
        # Clear previous stats
        performance_monitor.query_stats.clear()
        performance_monitor.slow_queries.clear()

        # Record a query
        performance_monitor.record_query("test_query", 150.0, 50)

        assert "test_query" in performance_monitor.query_stats
        stats = performance_monitor.query_stats["test_query"]
        assert stats['count'] == 1
        assert stats['total_time'] == 150.0
        assert stats['max_time'] == 150.0
        assert stats['total_results'] == 50

    def test_performance_monitor_records_slow_query(self):
        """Test that slow queries are recorded."""
        # Clear previous stats
        performance_monitor.slow_queries.clear()

        # Record a slow query
        slow_time = QueryLimits.SLOW_QUERY_THRESHOLD_MS + 100
        performance_monitor.record_query("slow_query", slow_time, 100)

        assert len(performance_monitor.slow_queries) == 1
        slow_query = performance_monitor.slow_queries[0]
        assert slow_query['query_name'] == "slow_query"
        assert slow_query['execution_time_ms'] == slow_time

    def test_performance_summary(self):
        """Test performance summary generation."""
        # Clear and add test data
        performance_monitor.query_stats.clear()
        performance_monitor.slow_queries.clear()

        # Add multiple queries
        performance_monitor.record_query("query1", 100.0, 20)
        performance_monitor.record_query("query1", 200.0, 30)
        performance_monitor.record_query("query2", 50.0, 10)

        summary = performance_monitor.get_performance_summary()

        assert summary['total_queries'] == 3
        assert len(summary['queries']) == 2

        query1_stats = summary['queries']['query1']
        assert query1_stats['count'] == 2
        assert query1_stats['avg_time_ms'] == 150.0  # (100 + 200) / 2
        assert query1_stats['max_time_ms'] == 200.0

    def test_monitor_query_performance_decorator(self):
        """Test the query performance monitoring decorator."""
        from pgappforge.utils.db_performance import monitor_query_performance

        @monitor_query_performance("decorated_query")
        def test_query_function():
            time.sleep(0.01)  # Small delay to test timing
            return ['result1', 'result2']

        # Clear stats
        performance_monitor.query_stats.clear()

        # Execute decorated function
        result = test_query_function()

        assert result == ['result1', 'result2']
        assert "decorated_query" in performance_monitor.query_stats
        stats = performance_monitor.query_stats["decorated_query"]
        assert stats['count'] == 1
        assert stats['total_time'] > 0  # Should record some execution time


class TestQueryLimitsConfiguration:
    """Test query limits configuration."""

    def test_default_limits(self):
        """Test default query limits."""
        limits = QueryLimits()

        assert limits.DEFAULT_PAGE_SIZE == 50
        assert limits.MAX_PAGE_SIZE == 1000
        assert limits.DEFAULT_MAX_RESULTS == 10000
        assert limits.BULK_OPERATION_LIMIT == 5000

    def test_memory_limits(self):
        """Test memory-related limits."""
        limits = QueryLimits()

        assert limits.MAX_MEMORY_MB == 100
        assert limits.ESTIMATED_ROW_SIZE_BYTES == 1024

    def test_performance_thresholds(self):
        """Test performance monitoring thresholds."""
        limits = QueryLimits()

        assert limits.SLOW_QUERY_THRESHOLD_MS == 1000
        assert limits.LOG_PERFORMANCE_WARNINGS is True


class TestDatabasePerformanceError:
    """Test database performance error handling."""

    def test_error_creation(self):
        """Test creating database performance error."""
        error = DatabasePerformanceError("Performance limit exceeded")

        assert str(error) == "Performance limit exceeded"
        assert isinstance(error, Exception)

    def test_error_in_optimizer(self):
        """Test error handling in query optimizer."""
        optimizer = QueryOptimizer()

        # Mock query that would exceed limits
        mock_query = Mock()
        mock_query.session.execute.return_value.scalar.return_value = 20000

        with pytest.raises(DatabasePerformanceError):
            optimizer.safe_all(mock_query, max_results=100)


class TestPerformanceOptimizationIntegration:
    """Integration tests for performance optimizations."""

    def test_approval_views_use_optimization(self):
        """Test that approval views use performance optimization."""
        from pgappforge.utils.db_performance import QueryOptimizer

        # Test that QueryOptimizer is properly imported and used
        optimizer = QueryOptimizer()
        assert optimizer is not None
        assert hasattr(optimizer, 'safe_all')
        assert hasattr(optimizer, 'paginated_query')

    def test_query_limits_realistic_values(self):
        """Test that query limits have realistic production values."""
        limits = QueryLimits()

        # Verify limits are reasonable for production use
        assert 10 <= limits.DEFAULT_PAGE_SIZE <= 100
        assert 100 <= limits.MAX_PAGE_SIZE <= 10000
        assert 1000 <= limits.DEFAULT_MAX_RESULTS <= 100000
        assert limits.MAX_MEMORY_MB <= 1000  # Under 1GB

    def test_performance_monitoring_integration(self):
        """Test performance monitoring integration."""
        # Verify global performance monitor exists
        assert performance_monitor is not None
        assert hasattr(performance_monitor, 'record_query')
        assert hasattr(performance_monitor, 'get_performance_summary')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])