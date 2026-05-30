#!/usr/bin/env python3
"""
Test fixtures and mock data for tutorial testing.

This module provides reusable test data, mock objects, and fixtures
for comprehensive tutorial testing.
"""

import json
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from unittest.mock import MagicMock, Mock


class MockAIResponses:
    """Mock AI responses for testing AI integration."""

    TASK_SUMMARIES = [
        "This task involves implementing a user authentication system with secure login functionality.",
        "A complex data processing pipeline that requires careful optimization for performance.",
        "Frontend development task focusing on responsive design and user experience improvements.",
        "Database migration and schema updates to support new feature requirements.",
        "API endpoint development with comprehensive error handling and validation.",
        "Testing and quality assurance task to ensure system reliability and stability.",
        "DevOps automation task to streamline deployment and monitoring processes.",
        "Documentation task to improve code clarity and developer onboarding experience."
    ]

    TASK_TAGS = [
        "authentication, security, backend, validation",
        "data-processing, optimization, performance, algorithms",
        "frontend, ui-ux, responsive-design, javascript",
        "database, migration, schema, sql",
        "api, rest, validation, error-handling",
        "testing, qa, automation, reliability",
        "devops, automation, deployment, monitoring",
        "documentation, onboarding, clarity, guides"
    ]

    PROJECT_INSIGHTS = [
        "Project shows excellent progress with 85% completion rate and minimal blockers.",
        "Team productivity is high with consistent task completion over the past month.",
        "Current sprint is on track with estimated completion by end of week.",
        "Several high-priority tasks require immediate attention to maintain timeline.",
        "Resource allocation is optimal with balanced workload distribution.",
        "Recent performance improvements have reduced system latency by 40%.",
        "User feedback indicates high satisfaction with recent feature implementations.",
        "Technical debt levels are manageable and within acceptable thresholds."
    ]

    @classmethod
    def get_mock_openai_client(cls):
        """Create a mock OpenAI client with realistic responses."""
        mock_client = MagicMock()

        def mock_create(**kwargs):
            """Mock the OpenAI chat completion create method."""
            messages = kwargs.get('messages', [])
            last_message = messages[-1].get('content', '') if messages else ''

            # Determine response type based on prompt content
            if 'summary' in last_message.lower():
                content = random.choice(cls.TASK_SUMMARIES)
            elif 'tags' in last_message.lower():
                content = random.choice(cls.TASK_TAGS)
            elif 'insight' in last_message.lower():
                content = random.choice(cls.PROJECT_INSIGHTS)
            else:
                content = "AI-generated response for the given prompt."

            return MagicMock(
                choices=[MagicMock(message=MagicMock(content=content))]
            )

        mock_client.chat.completions.create.side_effect = mock_create
        return mock_client

    @classmethod
    def get_mock_anthropic_client(cls):
        """Create a mock Anthropic client with realistic responses."""
        mock_client = MagicMock()

        def mock_create(**kwargs):
            """Mock the Anthropic completion create method."""
            prompt = kwargs.get('prompt', '')

            if 'summary' in prompt.lower():
                content = random.choice(cls.TASK_SUMMARIES)
            elif 'tags' in prompt.lower():
                content = random.choice(cls.TASK_TAGS)
            elif 'insight' in prompt.lower():
                content = random.choice(cls.PROJECT_INSIGHTS)
            else:
                content = "Anthropic AI response for the given prompt."

            return MagicMock(completion=content)

        mock_client.completions.create.side_effect = mock_create
        return mock_client


class TutorialTestData:
    """Test data for tutorial components."""

    TASK_CATEGORIES = [
        {
            "name": "Development",
            "description": "Software development and programming tasks",
            "color": "#007bff"
        },
        {
            "name": "Testing",
            "description": "Quality assurance and testing activities",
            "color": "#28a745"
        },
        {
            "name": "Documentation",
            "description": "Documentation and knowledge sharing tasks",
            "color": "#ffc107"
        },
        {
            "name": "DevOps",
            "description": "Infrastructure and deployment tasks",
            "color": "#dc3545"
        },
        {
            "name": "Research",
            "description": "Research and analysis activities",
            "color": "#6f42c1"
        }
    ]

    SAMPLE_TASKS = [
        {
            "title": "Implement User Authentication",
            "description": "Create a secure user authentication system with JWT tokens and password hashing.",
            "priority": "high",
            "status": "pending",
            "estimated_hours": 8,
            "category": "Development"
        },
        {
            "title": "Write API Documentation",
            "description": "Document all REST API endpoints with examples and response schemas.",
            "priority": "medium",
            "status": "in_progress",
            "estimated_hours": 6,
            "actual_hours": 3,
            "progress": 50,
            "category": "Documentation"
        },
        {
            "title": "Set Up CI/CD Pipeline",
            "description": "Configure automated testing and deployment pipeline using GitHub Actions.",
            "priority": "high",
            "status": "completed",
            "estimated_hours": 12,
            "actual_hours": 10,
            "progress": 100,
            "category": "DevOps"
        },
        {
            "title": "Performance Testing",
            "description": "Conduct load testing and performance analysis of the application.",
            "priority": "medium",
            "status": "pending",
            "estimated_hours": 4,
            "category": "Testing"
        },
        {
            "title": "Database Optimization",
            "description": "Optimize database queries and implement proper indexing strategies.",
            "priority": "urgent",
            "status": "in_progress",
            "estimated_hours": 6,
            "actual_hours": 2,
            "progress": 35,
            "category": "Development"
        },
        {
            "title": "UI/UX Research",
            "description": "Research user experience patterns and design new interface components.",
            "priority": "low",
            "status": "pending",
            "estimated_hours": 16,
            "category": "Research"
        }
    ]

    @classmethod
    def get_task_data(cls, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get sample task data."""
        tasks = cls.SAMPLE_TASKS.copy()
        if count is not None:
            return tasks[:count]
        return tasks

    @classmethod
    def get_category_data(cls) -> List[Dict[str, Any]]:
        """Get sample category data."""
        return cls.TASK_CATEGORIES.copy()

    @classmethod
    def generate_random_task(cls, category_name: str = "Development") -> Dict[str, Any]:
        """Generate a random task for testing."""
        priorities = ["low", "medium", "high", "urgent"]
        statuses = ["pending", "in_progress", "completed", "cancelled"]

        return {
            "title": f"Random Task {random.randint(1000, 9999)}",
            "description": f"Auto-generated task for testing purposes {datetime.now().isoformat()}",
            "priority": random.choice(priorities),
            "status": random.choice(statuses),
            "estimated_hours": random.randint(1, 20),
            "actual_hours": random.randint(1, 15) if random.choice([True, False]) else None,
            "progress": random.randint(0, 100),
            "category": category_name
        }

    @classmethod
    def generate_bulk_tasks(cls, count: int, category_name: str = "Development") -> List[Dict[str, Any]]:
        """Generate multiple random tasks for bulk testing."""
        return [cls.generate_random_task(category_name) for _ in range(count)]


class MockRedisClient:
    """Mock Redis client for testing."""

    def __init__(self):
        self.data = {}
        self.connected = True

    def ping(self):
        """Mock ping method."""
        if not self.connected:
            raise ConnectionError("Redis connection failed")
        return True

    def set(self, key: str, value: str, ex: Optional[int] = None):
        """Mock set method."""
        self.data[key] = {
            'value': value,
            'expiry': datetime.now() + timedelta(seconds=ex) if ex else None
        }
        return True

    def get(self, key: str) -> Optional[str]:
        """Mock get method."""
        if key in self.data:
            item = self.data[key]
            if item['expiry'] and datetime.now() > item['expiry']:
                del self.data[key]
                return None
            return item['value']
        return None

    def delete(self, key: str) -> int:
        """Mock delete method."""
        if key in self.data:
            del self.data[key]
            return 1
        return 0

    def exists(self, key: str) -> bool:
        """Mock exists method."""
        return key in self.data

    def flushdb(self):
        """Mock flushdb method."""
        self.data.clear()

    def disconnect(self):
        """Simulate disconnection."""
        self.connected = False


class TutorialTestEnvironment:
    """Test environment configuration and utilities."""

    @classmethod
    def get_test_config(cls) -> Dict[str, Any]:
        """Get test configuration dictionary."""
        return {
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'SECRET_KEY': 'tutorial-test-secret-key-for-testing-only',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'REDIS_URL': 'redis://localhost:6379/15',
            'AUTH_TYPE': 1,  # Database authentication
            'AUTH_ROLE_ADMIN': 'Admin',
            'AUTH_ROLE_PUBLIC': 'Public',
            'OPENAI_API_KEY': 'test-openai-key',
            'ANTHROPIC_API_KEY': 'test-anthropic-key',
            'GOOGLE_API_KEY': 'test-google-key',
            'GROQ_API_KEY': 'test-groq-key'
        }

    @classmethod
    def get_mock_environment(cls) -> Dict[str, str]:
        """Get mock environment variables for testing."""
        return {
            'SECRET_KEY': 'tutorial-test-secret-key-for-testing-only',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'REDIS_URL': 'redis://localhost:6379/15',
            'TESTING': 'True',
            'WTF_CSRF_ENABLED': 'False',
            'OPENAI_API_KEY': 'test-openai-key',
            'ANTHROPIC_API_KEY': 'test-anthropic-key',
            'GOOGLE_API_KEY': 'test-google-key',
            'GROQ_API_KEY': 'test-groq-key',
            'FLASK_ENV': 'testing'
        }

    @classmethod
    def create_test_database_data(cls, session):
        """Create test data in the database."""
        # Import here to avoid circular imports
        from models import TaskCategory, Task, Priority, Status

        # Create categories
        categories = {}
        for cat_data in cls.get_category_data():
            category = TaskCategory(
                name=cat_data['name'],
                description=cat_data['description']
            )
            session.add(category)
            categories[cat_data['name']] = category

        session.commit()

        # Create tasks
        tasks = []
        for task_data in cls.get_task_data():
            task = Task(
                title=task_data['title'],
                description=task_data['description'],
                category=categories[task_data['category']],
                priority=Priority(task_data['priority']),
                status=Status(task_data['status']),
                estimated_hours=task_data['estimated_hours'],
                actual_hours=task_data.get('actual_hours'),
                progress=task_data.get('progress', 0)
            )
            session.add(task)
            tasks.append(task)

        session.commit()
        return categories, tasks

    @classmethod
    def get_category_data(cls):
        """Get category data (wrapper for TutorialTestData)."""
        return TutorialTestData.get_category_data()

    @classmethod
    def get_task_data(cls):
        """Get task data (wrapper for TutorialTestData)."""
        return TutorialTestData.get_task_data()


class MockFlaskAppBuilder:
    """Mock PgForge for isolated testing."""

    def __init__(self):
        self.sm = Mock()
        self.baseviews = []
        self.menu = Mock()

        # Mock security manager
        self.sm.find_role.return_value = Mock()
        self.sm.get_all_permissions.return_value = []

        # Mock menu
        self.menu.get_list.return_value = ['Tasks', 'Categories', 'Dashboard']

    def add_view(self, view, name, href='', icon='', category=''):
        """Mock add_view method."""
        self.baseviews.append(view)

    def add_link(self, name, href='', icon='', category=''):
        """Mock add_link method."""
        pass

    def get_session(self):
        """Mock get_session method."""
        return Mock()


def create_test_app_context():
    """Create a test application context with mocked dependencies."""
    from unittest.mock import patch
    import tempfile
    import os

    # Create temporary directory for test database
    test_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(test_dir, 'test.db')

    # Set up test environment
    test_env = TutorialTestEnvironment.get_mock_environment()
    test_env['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{test_db_path}'

    # Apply environment patches
    env_patches = {}
    for key, value in test_env.items():
        env_patches[key] = os.environ.get(key)
        os.environ[key] = value

    return test_dir, env_patches


def cleanup_test_app_context(test_dir, env_patches):
    """Clean up test application context."""
    import shutil
    import os

    # Restore environment
    for key, original_value in env_patches.items():
        if original_value is None:
            if key in os.environ:
                del os.environ[key]
        else:
            os.environ[key] = original_value

    # Clean up test directory
    shutil.rmtree(test_dir, ignore_errors=True)


class TutorialTestMetrics:
    """Utilities for measuring test performance and collecting metrics."""

    @staticmethod
    def measure_execution_time(func):
        """Decorator to measure function execution time."""
        import time
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            end_time = time.time()
            execution_time = end_time - start_time

            # Store or log the execution time
            print(f"{func.__name__} executed in {execution_time:.4f} seconds")
            return result

        return wrapper

    @staticmethod
    def validate_response_time(max_time_seconds: float):
        """Decorator to validate that a function completes within specified time."""
        import time
        from functools import wraps

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                start_time = time.time()
                result = func(*args, **kwargs)
                end_time = time.time()
                execution_time = end_time - start_time

                if execution_time > max_time_seconds:
                    raise AssertionError(
                        f"{func.__name__} took {execution_time:.4f}s, "
                        f"which exceeds the maximum allowed time of {max_time_seconds}s"
                    )

                return result
            return wrapper
        return decorator

    @staticmethod
    def collect_test_metrics(test_results: Dict[str, Any]) -> Dict[str, Any]:
        """Collect and analyze test metrics."""
        return {
            'total_tests': len(test_results),
            'passed_tests': sum(1 for result in test_results.values() if result),
            'failed_tests': sum(1 for result in test_results.values() if not result),
            'success_rate': sum(1 for result in test_results.values() if result) / len(test_results) * 100,
            'timestamp': datetime.now().isoformat()
        }


# Export commonly used components
__all__ = [
    'MockAIResponses',
    'TutorialTestData',
    'MockRedisClient',
    'TutorialTestEnvironment',
    'MockFlaskAppBuilder',
    'TutorialTestMetrics',
    'create_test_app_context',
    'cleanup_test_app_context'
]