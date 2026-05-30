#!/usr/bin/env python3
"""
Mock services infrastructure for PgForge tutorial testing.

This module provides comprehensive mock implementations of external services
to enable reliable, isolated testing of tutorial functionality.
"""

import json
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from unittest.mock import Mock, MagicMock
from contextlib import contextmanager
import tempfile
import os


logger = logging.getLogger(__name__)


class MockRedisServer:
    """Comprehensive Redis mock with realistic behavior."""

    def __init__(self, initial_data: Optional[Dict] = None):
        self.data = initial_data or {}
        self.expirations = {}
        self.connected = True
        self.lock = threading.RLock()

    def ping(self) -> bool:
        """Mock Redis ping command."""
        if not self.connected:
            raise ConnectionError("Redis server is not available")
        return True

    def get(self, key: str) -> Optional[str]:
        """Mock Redis GET command."""
        with self.lock:
            self._cleanup_expired()
            return self.data.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None, px: Optional[int] = None) -> bool:
        """Mock Redis SET command with expiration support."""
        with self.lock:
            self.data[key] = value

            if ex:  # seconds
                self.expirations[key] = datetime.now() + timedelta(seconds=ex)
            elif px:  # milliseconds
                self.expirations[key] = datetime.now() + timedelta(milliseconds=px)

            return True

    def delete(self, *keys: str) -> int:
        """Mock Redis DELETE command."""
        with self.lock:
            deleted = 0
            for key in keys:
                if key in self.data:
                    del self.data[key]
                    self.expirations.pop(key, None)
                    deleted += 1
            return deleted

    def exists(self, *keys: str) -> int:
        """Mock Redis EXISTS command."""
        with self.lock:
            self._cleanup_expired()
            return sum(1 for key in keys if key in self.data)

    def ttl(self, key: str) -> int:
        """Mock Redis TTL command."""
        with self.lock:
            if key not in self.data:
                return -2  # Key doesn't exist

            if key not in self.expirations:
                return -1  # Key exists but has no expiration

            remaining = (self.expirations[key] - datetime.now()).total_seconds()
            return int(remaining) if remaining > 0 else -2

    def flushdb(self) -> bool:
        """Mock Redis FLUSHDB command."""
        with self.lock:
            self.data.clear()
            self.expirations.clear()
            return True

    def keys(self, pattern: str = "*") -> List[str]:
        """Mock Redis KEYS command with basic pattern support."""
        with self.lock:
            self._cleanup_expired()
            if pattern == "*":
                return list(self.data.keys())

            # Basic pattern matching
            import fnmatch
            return [key for key in self.data.keys() if fnmatch.fnmatch(key, pattern)]

    def hset(self, name: str, key: str = None, value: str = None, mapping: Dict = None) -> int:
        """Mock Redis HSET command."""
        with self.lock:
            if name not in self.data:
                self.data[name] = {}

            if mapping:
                self.data[name].update(mapping)
                return len(mapping)
            elif key is not None and value is not None:
                old_value = self.data[name].get(key)
                self.data[name][key] = value
                return 0 if old_value else 1

            return 0

    def hget(self, name: str, key: str) -> Optional[str]:
        """Mock Redis HGET command."""
        with self.lock:
            self._cleanup_expired()
            hash_data = self.data.get(name, {})
            return hash_data.get(key) if isinstance(hash_data, dict) else None

    def hgetall(self, name: str) -> Dict[str, str]:
        """Mock Redis HGETALL command."""
        with self.lock:
            self._cleanup_expired()
            hash_data = self.data.get(name, {})
            return hash_data if isinstance(hash_data, dict) else {}

    def lpush(self, name: str, *values: str) -> int:
        """Mock Redis LPUSH command."""
        with self.lock:
            if name not in self.data:
                self.data[name] = []

            if not isinstance(self.data[name], list):
                self.data[name] = []

            for value in reversed(values):
                self.data[name].insert(0, value)

            return len(self.data[name])

    def rpop(self, name: str) -> Optional[str]:
        """Mock Redis RPOP command."""
        with self.lock:
            if name not in self.data or not isinstance(self.data[name], list):
                return None

            return self.data[name].pop() if self.data[name] else None

    def llen(self, name: str) -> int:
        """Mock Redis LLEN command."""
        with self.lock:
            self._cleanup_expired()
            if name not in self.data or not isinstance(self.data[name], list):
                return 0
            return len(self.data[name])

    def disconnect(self):
        """Simulate Redis disconnection."""
        self.connected = False

    def reconnect(self):
        """Simulate Redis reconnection."""
        self.connected = True

    def _cleanup_expired(self):
        """Remove expired keys."""
        now = datetime.now()
        expired_keys = [
            key for key, expiry in self.expirations.items()
            if expiry <= now
        ]

        for key in expired_keys:
            self.data.pop(key, None)
            self.expirations.pop(key, None)

    def get_stats(self) -> Dict[str, Any]:
        """Get Redis server statistics."""
        with self.lock:
            self._cleanup_expired()
            return {
                'connected': self.connected,
                'total_keys': len(self.data),
                'expired_keys': len(self.expirations),
                'memory_usage': sum(len(str(k)) + len(str(v)) for k, v in self.data.items()),
                'uptime': 'mock'
            }


class MockAIProvider:
    """Base class for AI provider mocks."""

    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        self.request_count = 0
        self.total_tokens = 0
        self.error_rate = 0.0  # Percentage of requests that should fail
        self.response_delay = 0.0  # Seconds to delay responses

    def set_error_rate(self, rate: float):
        """Set the percentage of requests that should fail."""
        self.error_rate = max(0.0, min(1.0, rate))

    def set_response_delay(self, delay: float):
        """Set response delay in seconds."""
        self.response_delay = max(0.0, delay)

    def _should_error(self) -> bool:
        """Determine if this request should error."""
        import random
        return random.random() < self.error_rate

    def _apply_delay(self):
        """Apply response delay."""
        if self.response_delay > 0:
            time.sleep(self.response_delay)

    def get_stats(self) -> Dict[str, Any]:
        """Get provider statistics."""
        return {
            'provider': self.provider_name,
            'request_count': self.request_count,
            'total_tokens': self.total_tokens,
            'error_rate': self.error_rate,
            'response_delay': self.response_delay
        }


class MockOpenAI(MockAIProvider):
    """Mock OpenAI API client."""

    def __init__(self):
        super().__init__('openai')
        self.chat = MockOpenAIChat(self)

    class MockOpenAIChat:
        def __init__(self, parent):
            self.parent = parent
            self.completions = MockOpenAICompletions(parent)

    class MockOpenAICompletions:
        def __init__(self, parent):
            self.parent = parent

        def create(self, **kwargs) -> MagicMock:
            """Mock chat completion creation."""
            self.parent.request_count += 1
            self.parent._apply_delay()

            if self.parent._should_error():
                raise Exception(f"Mock {self.parent.provider_name} API error")

            # Extract prompt for context-aware responses
            messages = kwargs.get('messages', [])
            last_message = messages[-1].get('content', '') if messages else ''

            # Generate context-aware response
            if 'summary' in last_message.lower():
                content = "This is a comprehensive task summary generated by AI. The task involves multiple components and requires careful coordination across teams."
            elif 'tags' in last_message.lower():
                content = "ai, automation, development, testing, integration"
            elif 'insight' in last_message.lower():
                content = "Based on the current progress, the project is on track with 85% completion rate. Key areas for focus include performance optimization and documentation."
            else:
                content = f"AI-generated response for: {last_message[:50]}..."

            # Estimate tokens
            tokens = len(content.split()) + sum(len(msg.get('content', '').split()) for msg in messages)
            self.parent.total_tokens += tokens

            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = content
            mock_response.usage.total_tokens = tokens

            return mock_response


class MockAnthropic(MockAIProvider):
    """Mock Anthropic API client."""

    def __init__(self):
        super().__init__('anthropic')
        self.completions = self

    def create(self, **kwargs) -> MagicMock:
        """Mock completion creation."""
        self.request_count += 1
        self._apply_delay()

        if self._should_error():
            raise Exception(f"Mock {self.provider_name} API error")

        prompt = kwargs.get('prompt', '')

        # Generate context-aware response
        if 'summary' in prompt.lower():
            content = "Anthropic AI has analyzed this task and identified key dependencies and potential risks. Recommended approach includes iterative development with continuous testing."
        elif 'tags' in prompt.lower():
            content = "anthropic, ai, analysis, planning, optimization"
        elif 'insight' in prompt.lower():
            content = "The project metrics indicate strong velocity with minimal technical debt. Consider implementing additional monitoring for production readiness."
        else:
            content = f"Anthropic AI response for: {prompt[:50]}..."

        tokens = len(content.split()) + len(prompt.split())
        self.total_tokens += tokens

        mock_response = MagicMock()
        mock_response.completion = content
        return mock_response


class MockGoogleAI(MockAIProvider):
    """Mock Google AI API client."""

    def __init__(self):
        super().__init__('google')

    def generate_text(self, **kwargs) -> MagicMock:
        """Mock text generation."""
        self.request_count += 1
        self._apply_delay()

        if self._should_error():
            raise Exception(f"Mock {self.provider_name} API error")

        prompt = kwargs.get('prompt', {}).get('text', '')

        if 'summary' in prompt.lower():
            content = "Google AI analysis indicates this task requires strategic planning and resource allocation. Estimated completion timeline aligns with project milestones."
        elif 'tags' in prompt.lower():
            content = "google, ai, gemini, analysis, prediction"
        else:
            content = f"Google AI response for: {prompt[:50]}..."

        tokens = len(content.split()) + len(prompt.split())
        self.total_tokens += tokens

        mock_response = MagicMock()
        mock_response.text = content
        return mock_response


class MockDatabaseSession:
    """Mock database session with realistic behavior."""

    def __init__(self):
        self.data = {}
        self.committed = True
        self.in_transaction = False
        self.query_count = 0
        self.last_query = None

    def add(self, instance) -> None:
        """Mock session add."""
        if not hasattr(instance, '_mock_id'):
            instance._mock_id = len(self.data) + 1
            instance.id = instance._mock_id

        table_name = instance.__class__.__name__
        if table_name not in self.data:
            self.data[table_name] = {}

        self.data[table_name][instance._mock_id] = instance
        self.committed = False

    def commit(self) -> None:
        """Mock session commit."""
        self.committed = True
        self.in_transaction = False

    def rollback(self) -> None:
        """Mock session rollback."""
        # In a real implementation, we'd revert changes
        self.committed = True
        self.in_transaction = False

    def delete(self, instance) -> None:
        """Mock session delete."""
        table_name = instance.__class__.__name__
        if table_name in self.data and hasattr(instance, '_mock_id'):
            self.data[table_name].pop(instance._mock_id, None)
        self.committed = False

    def query(self, model_class):
        """Mock session query."""
        return MockQuery(self, model_class)

    def get_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        return {
            'query_count': self.query_count,
            'committed': self.committed,
            'in_transaction': self.in_transaction,
            'tables': list(self.data.keys()),
            'total_records': sum(len(records) for records in self.data.values())
        }


class MockQuery:
    """Mock database query with chainable methods."""

    def __init__(self, session: MockDatabaseSession, model_class):
        self.session = session
        self.model_class = model_class
        self.filters = []
        self.order_by_fields = []
        self.limit_count = None
        self.offset_count = None

    def filter(self, *conditions):
        """Mock query filter."""
        self.filters.extend(conditions)
        return self

    def filter_by(self, **kwargs):
        """Mock query filter_by."""
        self.filters.append(kwargs)
        return self

    def order_by(self, *fields):
        """Mock query order_by."""
        self.order_by_fields.extend(fields)
        return self

    def limit(self, count: int):
        """Mock query limit."""
        self.limit_count = count
        return self

    def offset(self, count: int):
        """Mock query offset."""
        self.offset_count = count
        return self

    def all(self) -> List:
        """Mock query all."""
        self.session.query_count += 1
        table_name = self.model_class.__name__
        records = list(self.session.data.get(table_name, {}).values())

        # Apply filters (simplified)
        filtered_records = self._apply_filters(records)

        # Apply ordering (simplified)
        if self.order_by_fields:
            # In a real implementation, we'd properly sort
            pass

        # Apply limit and offset
        if self.offset_count:
            filtered_records = filtered_records[self.offset_count:]
        if self.limit_count:
            filtered_records = filtered_records[:self.limit_count]

        return filtered_records

    def first(self):
        """Mock query first."""
        results = self.all()
        return results[0] if results else None

    def count(self) -> int:
        """Mock query count."""
        self.session.query_count += 1
        table_name = self.model_class.__name__
        records = list(self.session.data.get(table_name, {}).values())
        return len(self._apply_filters(records))

    def _apply_filters(self, records: List) -> List:
        """Apply filters to records (simplified implementation)."""
        # This is a simplified filter application
        # In a real implementation, we'd parse and apply actual filter conditions
        return records


class MockServiceOrchestrator:
    """Orchestrator for managing all mock services."""

    def __init__(self):
        self.redis = MockRedisServer()
        self.openai = MockOpenAI()
        self.anthropic = MockAnthropic()
        self.google = MockGoogleAI()
        self.database = MockDatabaseSession()
        self.active_patches = []
        self.start_time = time.time()

    @contextmanager
    def activate_mocks(self, services: Optional[List[str]] = None):
        """Context manager to activate mock services."""
        if services is None:
            services = ['redis', 'openai', 'anthropic', 'google', 'database']

        patches = []

        try:
            # Activate Redis mock
            if 'redis' in services:
                from unittest.mock import patch
                redis_patch = patch('redis.Redis', return_value=self.redis)
                redis_patch.start()
                patches.append(redis_patch)

            # Activate OpenAI mock
            if 'openai' in services:
                openai_patch = patch('openai.OpenAI', return_value=self.openai)
                openai_patch.start()
                patches.append(openai_patch)

            # Activate Anthropic mock
            if 'anthropic' in services:
                anthropic_patch = patch('anthropic.Anthropic', return_value=self.anthropic)
                anthropic_patch.start()
                patches.append(anthropic_patch)

            # Activate Google AI mock
            if 'google' in services:
                google_patch = patch('google.generativeai.GenerativeModel.generate_content',
                                   side_effect=self.google.generate_text)
                google_patch.start()
                patches.append(google_patch)

            logger.info(f"Activated mock services: {services}")
            yield self

        finally:
            # Clean up patches
            for patch_obj in patches:
                patch_obj.stop()
            logger.info("Deactivated mock services")

    def configure_ai_behavior(self, error_rate: float = 0.0, delay: float = 0.0):
        """Configure AI provider behavior for testing different scenarios."""
        for provider in [self.openai, self.anthropic, self.google]:
            provider.set_error_rate(error_rate)
            provider.set_response_delay(delay)

    def simulate_redis_failure(self):
        """Simulate Redis connection failure."""
        self.redis.disconnect()

    def restore_redis_connection(self):
        """Restore Redis connection."""
        self.redis.reconnect()

    def populate_test_data(self, task_count: int = 10, category_count: int = 5):
        """Populate mock database with test data."""
        # This would create test models and populate the database
        # Implementation depends on the actual model structure
        logger.info(f"Populated test data: {task_count} tasks, {category_count} categories")

    def get_comprehensive_stats(self) -> Dict[str, Any]:
        """Get statistics from all mock services."""
        return {
            'uptime': time.time() - self.start_time,
            'redis': self.redis.get_stats(),
            'openai': self.openai.get_stats(),
            'anthropic': self.anthropic.get_stats(),
            'google': self.google.get_stats(),
            'database': self.database.get_stats(),
            'timestamp': datetime.now().isoformat()
        }

    def reset_all_services(self):
        """Reset all mock services to initial state."""
        self.redis.flushdb()
        self.database = MockDatabaseSession()

        # Reset AI provider stats
        for provider in [self.openai, self.anthropic, self.google]:
            provider.request_count = 0
            provider.total_tokens = 0

        logger.info("Reset all mock services")


# Global orchestrator instance
mock_orchestrator = MockServiceOrchestrator()


# Convenience functions
def get_mock_redis() -> MockRedisServer:
    """Get the global mock Redis instance."""
    return mock_orchestrator.redis


def get_mock_database() -> MockDatabaseSession:
    """Get the global mock database session."""
    return mock_orchestrator.database


def activate_all_mocks():
    """Activate all mock services."""
    return mock_orchestrator.activate_mocks()


def activate_specific_mocks(services: List[str]):
    """Activate specific mock services."""
    return mock_orchestrator.activate_mocks(services)


# Export main components
__all__ = [
    'MockRedisServer',
    'MockOpenAI',
    'MockAnthropic',
    'MockGoogleAI',
    'MockDatabaseSession',
    'MockServiceOrchestrator',
    'mock_orchestrator',
    'get_mock_redis',
    'get_mock_database',
    'activate_all_mocks',
    'activate_specific_mocks'
]